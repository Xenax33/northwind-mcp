"""The web host, end to end: it starts the real MCP server as a child process over stdio.

The model is replaced by a scripted fake so these tests are free, fast and deterministic;
everything else (FastAPI, the stdio pipe, the MCP server, the database) is real.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def tool_call(name, arguments, call_id="call_1"):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(id=call_id, type="function", function=function)


def reply(content="", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=10)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class ScriptedModel:
    """Stands in for the Groq client: returns the scripted replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []  # the messages the model was sent each time
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, model, messages, tools):
        self.seen.append(list(messages))
        return self.replies.pop(0)


@pytest.fixture
def host(db_path, monkeypatch):
    monkeypatch.setenv("NORTHWIND_DB", str(db_path))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-used")
    from northwind_host.app import app

    with TestClient(app) as client:
        yield client


def events(client):
    return client.app.state.bus.history()


def test_host_starts_server_and_lists_tools(host):
    tools = {t["name"]: t for t in host.get("/api/tools").json()}
    assert len(tools) == 11
    assert tools["place_order"]["read_only"] is False
    assert tools["sales_summary"]["read_only"] is True
    # The handshake went over the real pipe and is in the log, in both directions.
    mcp = [e for e in events(host) if e["kind"] == "mcp"]
    assert mcp[0]["direction"] == "out"
    assert any(e["direction"] == "in" for e in mcp)
    assert any(e["message"].get("method") == "tools/list" for e in mcp)


def test_question_runs_tools_over_mcp_and_logs_both_lanes(host):
    model = ScriptedModel(
        reply(tool_calls=[tool_call("sales_summary", {"group_by": "customer", "limit": 1})]),
        reply("QUICK-Stop is the top customer."),
    )
    host.app.state.agent.llm = model
    body = host.post("/api/ask", json={"question": "Top customer?"}).json()

    assert body["answer"] == "QUICK-Stop is the top customer."
    assert body["model_calls"] == 2
    assert body["tool_calls"] == [{"name": "sales_summary", "arguments": {"group_by": "customer", "limit": 1}, "is_error": False}]
    # The model received the real tool result from the server.
    tool_message = model.seen[1][-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"])["groups"][0]["name"] == "QUICK-Stop"
    kinds = {(e["kind"], e.get("direction") or e.get("stage")) for e in events(host)}
    assert {("mcp", "out"), ("mcp", "in"), ("ai", "request"), ("ai", "response")} <= kinds


def test_tool_errors_reach_the_model(host):
    model = ScriptedModel(
        reply(tool_calls=[tool_call("get_customer", {"customer_id": "NOPE1"})]),
        reply("No such customer."),
    )
    host.app.state.agent.llm = model
    body = host.post("/api/ask", json={"question": "Customer NOPE1?"}).json()
    assert body["tool_calls"][0]["is_error"] is True
    assert '"not_found"' in model.seen[1][-1]["content"]


def test_public_api_cannot_skip_human_approval(host, monkeypatch):
    monkeypatch.delenv("NORTHWIND_ALLOW_AUTO_APPROVAL", raising=False)
    response = host.post("/api/ask", json={"question": "Order 1 Chai", "approval_policy": "approve"})
    assert response.status_code == 403


def test_eval_policy_places_order_and_it_shows_in_recent_changes(host, monkeypatch):
    monkeypatch.setenv("NORTHWIND_ALLOW_AUTO_APPROVAL", "1")
    order = {"customer_id": "ALFKI", "employee_id": 1, "shipper_id": 1, "lines": [{"product_id": 1, "quantity": 10}]}
    host.app.state.agent.llm = ScriptedModel(reply(tool_calls=[tool_call("place_order", order)]), reply("Placed."))
    body = host.post("/api/ask", json={"question": "Order 10 Chai", "approval_policy": "approve"}).json()
    assert body["tool_calls"][0] == {"name": "place_order", "arguments": order, "is_error": False}
    approvals = [e for e in events(host) if e["kind"] == "approval"]
    assert approvals[0]["status"] == "auto" and approvals[0]["approved"] is True
    assert "10 x Chai" in approvals[0]["text"]
    changes = host.get("/api/changes").json()["changes"]
    assert changes[0]["order_id"] == 11078
    assert changes[0]["client"] == "northwind-web-host"


def test_declined_order_writes_nothing(host, monkeypatch):
    monkeypatch.setenv("NORTHWIND_ALLOW_AUTO_APPROVAL", "1")
    order = {"customer_id": "ALFKI", "employee_id": 1, "shipper_id": 1, "lines": [{"product_id": 1, "quantity": 10}]}
    model = ScriptedModel(reply(tool_calls=[tool_call("place_order", order)]), reply("Not placed."))
    host.app.state.agent.llm = model
    body = host.post("/api/ask", json={"question": "Order 10 Chai", "approval_policy": "decline"}).json()
    assert body["tool_calls"][0]["is_error"] is True
    assert '"declined"' in model.seen[1][-1]["content"]
    assert host.get("/api/changes").json()["changes"] == []


def test_approval_endpoint_rejects_unknown_ids(host):
    assert host.post("/api/approvals/nope", json={"approve": True}).status_code == 404
