"""The host's MCP client: starts the server as a child process and talks to it over stdio.

`TappedTransport` sits between the SDK client and the stdio pipe and reports every
JSON-RPC message in both directions to the live log, serialized exactly the way the
stdio transport writes it to the pipe.

Approvals: when the server asks for approval (MCP elicitation), `Approvals` puts the
request on the page and waits for the human's click. Only a host started for the
evaluation may answer automatically (see `ApprovalPolicy`).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Literal

import anyio
from mcp import types
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.message import SessionMessage

from northwind_host.events import EventBus

ApprovalPolicy = Literal["ask", "approve", "decline"]
APPROVAL_TIMEOUT_SECONDS = 300


def _wire_json(message: Any) -> dict[str, Any]:
    """The message as JSON, serialized the same way the stdio transport puts it on the pipe."""
    return json.loads(message.model_dump_json(by_alias=True, exclude_unset=True))


class TappedTransport:
    """An MCP transport that wraps stdio and reports every message to the event bus."""

    def __init__(self, server: StdioServerParameters, bus: EventBus) -> None:
        self._server = server
        self._bus = bus
        self._stack = AsyncExitStack()

    async def __aenter__(self):
        pipe_read, pipe_write = await self._stack.enter_async_context(stdio_client(self._server))
        to_client_send, to_client_recv = anyio.create_memory_object_stream[SessionMessage | Exception](100)
        to_server_send, to_server_recv = anyio.create_memory_object_stream[SessionMessage](100)
        task_group = await self._stack.enter_async_context(anyio.create_task_group())

        async def server_to_client() -> None:
            async with to_client_send:
                async for item in pipe_read:
                    if isinstance(item, SessionMessage):
                        self._bus.emit("mcp", direction="in", message=_wire_json(item.message))
                    await to_client_send.send(item)

        async def client_to_server() -> None:
            async with to_server_recv:
                async for item in to_server_recv:
                    self._bus.emit("mcp", direction="out", message=_wire_json(item.message))
                    await pipe_write.send(item)

        task_group.start_soon(server_to_client)
        task_group.start_soon(client_to_server)
        self._stack.callback(task_group.cancel_scope.cancel)
        return to_client_recv, to_server_send

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._stack.__aexit__(*exc_info)


class Approvals:
    """Pending approval requests, answered by a click on the page (or by the eval policy)."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self.policy: ApprovalPolicy = "ask"
        # The browser that asked the current question. Only it may answer the approval, so on a
        # shared demo one visitor can't approve another visitor's order.
        self.owner: str | None = None

    async def ask(self, message: str) -> bool:
        if self.policy != "ask":
            approved = self.policy == "approve"
            self._bus.emit("approval", status="auto", approved=approved, text=message)
            return approved
        approval_id = uuid.uuid4().hex
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = future
        self._bus.emit("approval", status="requested", approval_id=approval_id, text=message, owner=self.owner)
        try:
            approved = await asyncio.wait_for(future, APPROVAL_TIMEOUT_SECONDS)
        except TimeoutError:
            approved = False
        finally:
            self._pending.pop(approval_id, None)
        self._bus.emit("approval", status="answered", approval_id=approval_id, approved=approved)
        return approved

    def answer(self, approval_id: str, approved: bool, client_id: str | None = None) -> bool:
        future = self._pending.get(approval_id)
        if future is None or future.done():
            return False
        if self.owner is not None and client_id != self.owner:
            return False
        future.set_result(approved)
        return True


@asynccontextmanager
async def connect(bus: EventBus, approvals: Approvals, db_path: str | None = None) -> AsyncIterator[Client]:
    """Start the Northwind MCP server as a child process and connect to it."""
    env = {"PYTHONIOENCODING": "utf-8"}
    if db_path or os.environ.get("NORTHWIND_DB"):
        env["NORTHWIND_DB"] = db_path or os.environ["NORTHWIND_DB"]
    server = StdioServerParameters(command=sys.executable, args=["-m", "northwind_mcp"], env=env)

    async def on_elicit(context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        approved = await approvals.ask(params.message)
        if approved:
            return types.ElicitResult(action="accept", content={"approve": True})
        return types.ElicitResult(action="decline")

    client = Client(
        TappedTransport(server, bus),
        elicitation_callback=on_elicit,
        client_info=types.Implementation(name="northwind-web-host", version="0.1.0"),
    )
    async with client:
        bus.emit("status", text=f"Connected to MCP server (protocol {client.protocol_version}).")
        yield client
