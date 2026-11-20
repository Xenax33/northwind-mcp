"""The AI loop: Groq decides which MCP tools to call; the host calls them over MCP.

1. Send the question, the server's instructions and the MCP tool list to the model.
2. If the model asks for a tool, call it on the MCP server and give it the result.
3. Repeat until the model answers in plain text, or MAX_STEPS model calls are used.

Each model request and response goes to the "ai" lane of the live log, with token counts.
The model only ever sees data that came back from MCP tools.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from mcp import types
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from openai import AsyncOpenAI

from northwind_host.events import EventBus

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_STEPS = 8

HOST_GUIDANCE = """\
You answer questions about the Northwind trading company using only the tools provided.
- Base every fact and number on tool results. Never guess or invent data.
- If a tool returns an error, read its "hint" and correct the call.
- Answer concisely. Use a short list or table when there are several items.
- Placing an order changes data: only call place_order when the user clearly asks to order,
  and tell them whether it was placed. The user approves it in a dialog, not in the chat.
"""


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    is_error: bool


@dataclass
class AnswerResult:
    answer: str
    model: str
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    stopped_early: bool = False


def to_openai_tools(tools: list[types.Tool]) -> list[dict[str, Any]]:
    """MCP tool definitions -> the function-calling format the model API expects."""
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema},
        }
        for t in tools
    ]


def tool_result_text(result: types.CallToolResult) -> str:
    """What the model reads back: the structured result as JSON, else the text content."""
    if result.structured_content is not None and not result.is_error:
        return json.dumps(result.structured_content, ensure_ascii=False)
    texts = [c.text for c in result.content if isinstance(c, types.TextContent)]
    return "\n".join(texts) or ("Tool error." if result.is_error else "")


class Agent:
    def __init__(self, client: Client, tools: list[types.Tool], bus: EventBus, model: str | None = None) -> None:
        self.client = client
        self.tools = to_openai_tools(tools)
        self.bus = bus
        self.model = model or os.environ.get("NORTHWIND_MODEL", DEFAULT_MODEL)
        # The SDK retries rate-limit (429) and server errors itself, waiting as Groq asks.
        self.llm = AsyncOpenAI(base_url=GROQ_BASE_URL, api_key=os.environ.get("GROQ_API_KEY", ""), max_retries=6)

    async def answer(self, question: str) -> AnswerResult:
        system = HOST_GUIDANCE + "\n" + (self.client.instructions or "")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]
        result = AnswerResult(answer="", model=self.model)

        for step in range(1, MAX_STEPS + 1):
            self.bus.emit("ai", stage="request", step=step, model=self.model, messages=len(messages))
            response = await self.llm.chat.completions.create(model=self.model, messages=messages, tools=self.tools)
            result.model_calls += 1
            usage = response.usage
            if usage:
                result.prompt_tokens += usage.prompt_tokens
                result.completion_tokens += usage.completion_tokens
            message = response.choices[0].message
            calls = message.tool_calls or []
            self.bus.emit(
                "ai",
                stage="response",
                step=step,
                tool_calls=[{"name": c.function.name, "arguments": c.function.arguments} for c in calls],
                text=message.content or "",
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )
            if not calls:
                result.answer = message.content or ""
                return result

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in calls
                    ],
                }
            )
            for call in calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = None
                if not isinstance(arguments, dict):
                    content, is_error = "The tool arguments were not a valid JSON object. Send a JSON object.", True
                else:
                    try:
                        tool_result = await self.client.call_tool(call.function.name, arguments)
                        content, is_error = tool_result_text(tool_result), bool(tool_result.is_error)
                    except MCPError as exc:  # a protocol-level refusal, e.g. a capability is missing
                        content, is_error = f"The MCP server refused the call: {exc}", True
                result.tool_calls.append(ToolCallRecord(call.function.name, arguments or {}, is_error))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

        result.stopped_early = True
        result.answer = f"I stopped after {MAX_STEPS} model calls without a final answer. Try a narrower question."
        return result
