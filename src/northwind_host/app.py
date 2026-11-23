"""The web host's backend (FastAPI).

At startup it starts the MCP server as a child process, connects over stdio and lists
the tools. The page then uses:

  GET  /api/tools                  the tool list
  GET  /api/events                 the live log (Server-Sent Events)
  POST /api/ask                    ask a question; returns the answer when done
  POST /api/approvals/{id}         answer an approval request (Approve / Decline)
  GET  /api/changes                recent changes, via the MCP tool list_recent_changes

One question runs at a time: the live log and the approval dialog belong to that run.

Run with:  uv run northwind-host   (then open http://127.0.0.1:8000)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from northwind_host.agent import Agent
from northwind_host.events import EventBus
from northwind_host.mcp_link import Approvals, ApprovalPolicy, connect

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger("northwind_host")
load_dotenv()


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    # Only "ask" (a human clicks) is allowed unless the host was started for the evaluation,
    # so nobody can skip the human approval through the public API.
    approval_policy: ApprovalPolicy = "ask"
    # A random ID the page makes when it loads. Only this page may answer the approval dialog.
    client_id: str | None = Field(default=None, max_length=64)


class ApprovalAnswer(BaseModel):
    approve: bool
    client_id: str | None = Field(default=None, max_length=64)


def auto_approval_allowed() -> bool:
    return os.environ.get("NORTHWIND_ALLOW_AUTO_APPROVAL") == "1"


class QuestionLimit:
    """At most N questions per rolling hour, across all visitors (NORTHWIND_MAX_QUESTIONS_PER_HOUR).

    Protects the model provider's free quota on a public demo. Unset or 0 means no limit.
    """

    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self._times: deque[float] = deque()

    @classmethod
    def from_env(cls) -> QuestionLimit:
        return cls(int(os.environ.get("NORTHWIND_MAX_QUESTIONS_PER_HOUR") or 0))

    def try_take(self, now: float) -> float | None:
        """Take one slot. Returns None if allowed, else the seconds until a slot frees up."""
        if self.per_hour <= 0:
            return None
        while self._times and now - self._times[0] >= 3600:
            self._times.popleft()
        if len(self._times) >= self.per_hour:
            return 3600 - (now - self._times[0])
        self._times.append(now)
        return None


def describe_failure(exc: Exception) -> str:
    """A safe message for the page. The provider's raw error text can include account identifiers,
    so it is logged on the server only."""
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code == 413:
            return (
                "The question failed: the conversation grew larger than the model provider accepts in one "
                "request on this plan (8,000 tokens per minute on Groq's free tier). Try a narrower question."
            )
        if exc.status_code == 429:
            return "The question failed: the model provider's rate limit was reached. Wait a minute and try again."
        if exc.status_code in (401, 403):
            return "The question failed: the model provider rejected the API key. Check GROQ_API_KEY in .env."
        return f"The question failed: the model provider returned HTTP {exc.status_code}."
    if isinstance(exc, openai.APIConnectionError):
        return "The question failed: the model provider could not be reached."
    return f"The question failed unexpectedly ({type(exc).__name__}). See the server log."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bus = EventBus()
    approvals = Approvals(bus)
    async with connect(bus, approvals) as client:
        tools = (await client.list_tools()).tools
        app.state.bus = bus
        app.state.approvals = approvals
        app.state.client = client
        app.state.tools = tools
        app.state.agent = Agent(client, tools, bus)
        app.state.run_lock = asyncio.Lock()
        app.state.question_limit = QuestionLimit.from_env()
        yield


app = FastAPI(title="Northwind MCP host", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/tools")
async def list_tools(request: Request) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "read_only": bool(t.annotations and t.annotations.read_only_hint),
            "input_schema": t.input_schema,
        }
        for t in request.app.state.tools
    ]


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    bus: EventBus = request.app.state.bus
    queue = bus.subscribe()

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
                if await request.is_disconnected():
                    break
        finally:
            bus.unsubscribe(queue)

    # X-Accel-Buffering: tells reverse proxies (as on hosting platforms) not to hold the stream back.
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request) -> dict[str, Any]:
    state = request.app.state
    if body.approval_policy != "ask" and not auto_approval_allowed():
        raise HTTPException(403, "Automatic approval is only enabled for the evaluation run.")
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(503, "GROQ_API_KEY is not set. Add it to the .env file and restart the host.")
    if state.run_lock.locked():
        raise HTTPException(409, "Another question is still running. Try again when it has finished.")
    if (wait := state.question_limit.try_take(time.monotonic())) is not None:
        raise HTTPException(
            429,
            f"This demo allows {state.question_limit.per_hour} questions per hour to protect its free "
            f"model quota. Try again in about {max(1, round(wait / 60))} minute(s).",
        )
    async with state.run_lock:
        state.approvals.policy = body.approval_policy
        state.approvals.owner = body.client_id
        state.bus.emit("question", text=body.question)
        try:
            result = await state.agent.answer(body.question)
        except Exception as exc:  # e.g. the model API is down: report it, keep the host running
            message = describe_failure(exc)
            logger.exception("Question failed")  # full details stay in the server log
            state.bus.emit("status", text=message)
            raise HTTPException(502, message) from exc
        finally:
            state.approvals.policy = "ask"
            state.approvals.owner = None
        state.bus.emit("answer", text=result.answer)
        return asdict(result)


@app.post("/api/approvals/{approval_id}")
async def answer_approval(approval_id: str, body: ApprovalAnswer, request: Request) -> dict[str, bool]:
    if not request.app.state.approvals.answer(approval_id, body.approve, body.client_id):
        raise HTTPException(404, "No pending approval with that ID for this page (it may have timed out).")
    return {"ok": True}


@app.get("/api/changes")
async def recent_changes(request: Request) -> dict[str, Any]:
    result = await request.app.state.client.call_tool("list_recent_changes", {"limit": 10})
    if result.is_error or result.structured_content is None:
        raise HTTPException(502, "The MCP server could not list recent changes.")
    return result.structured_content


def main() -> None:
    import uvicorn

    uvicorn.run(
        "northwind_host.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
