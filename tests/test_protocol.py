"""End-to-end over the real MCP protocol, with an in-memory client.

These check what a client actually receives: tool list, schemas, annotations,
structured results, and that bad requests come back as clean tool errors.
"""

import json
import sqlite3

import pytest
from mcp import types
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError

from northwind_mcp.server import mcp

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_db(db_path, monkeypatch):
    monkeypatch.setenv("NORTHWIND_DB", str(db_path))


async def test_tools_are_listed_with_read_only_annotations():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools.keys() == {
        "search_customers",
        "get_customer",
        "find_inactive_customers",
        "search_products",
        "get_product",
        "list_orders",
        "get_order",
        "sales_summary",
        "list_reference",
        "list_recent_changes",
        "place_order",
    }
    for name in tools.keys() - {"place_order"}:
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].output_schema is not None
    assert tools["place_order"].annotations.read_only_hint is False


async def test_structured_result():
    async with Client(mcp) as client:
        result = await client.call_tool("get_customer", {"customer_id": "ERNSH"})
    assert not result.is_error
    assert result.structured_content["customer_name"] == "Ernst Handel"
    assert result.structured_content["order_count"] == 30
    # The same data is also sent as text, for clients that only read text.
    assert json.loads(result.content[0].text)["customer_id"] == "ERNSH"


async def test_not_found_is_a_clean_tool_error():
    async with Client(mcp) as client:
        result = await client.call_tool("get_customer", {"customer_id": "NOPE1"})
    assert result.is_error
    text = result.content[0].text
    body = json.loads(text[text.index("{") :])
    assert body["error"] == "not_found"
    assert "hint" in body


async def test_out_of_range_argument_is_refused():
    async with Client(mcp) as client:
        result = await client.call_tool("search_customers", {"limit": 500})
    assert result.is_error


async def test_bad_cursor_is_refused():
    async with Client(mcp) as client:
        result = await client.call_tool("search_customers", {"cursor": "garbage"})
    assert result.is_error
    assert "invalid_argument" in result.content[0].text


async def test_unknown_tool_is_refused():
    async with Client(mcp) as client:
        result = await client.call_tool("drop_all_tables", {})
    assert result.is_error


# --- The write, through real elicitation ------------------------------------

ORDER = {
    "customer_id": "ALFKI",
    "employee_id": 1,
    "shipper_id": 1,
    "lines": [{"product_id": 1, "quantity": 10}],
}


def human(action, content=None, seen=None):
    """A fake client UI: records the dialog text and answers it."""

    async def answer(context, params):
        if seen is not None:
            seen.append(params.message)
        return types.ElicitResult(action=action, content=content)

    return answer


def order_count(db_path):
    with sqlite3.connect(db_path) as con:
        return con.execute("SELECT COUNT(*) FROM Orders").fetchone()[0]


async def test_approved_order_is_placed(db_path):
    seen = []
    async with Client(mcp, elicitation_callback=human("accept", {"approve": True}, seen)) as client:
        result = await client.call_tool("place_order", ORDER)
    assert not result.is_error
    assert result.structured_content["order_id"] == 11078
    assert "10 x Chai" in seen[0] and "Total: 180.00" in seen[0]
    assert order_count(db_path) == 831


@pytest.mark.parametrize(
    "answer", [human("decline"), human("cancel"), human("accept", {"approve": False})], ids=str
)
async def test_anything_but_approval_writes_nothing(db_path, answer):
    async with Client(mcp, elicitation_callback=answer) as client:
        result = await client.call_tool("place_order", ORDER)
    assert result.is_error
    assert '"declined"' in result.content[0].text
    assert order_count(db_path) == 830


async def test_client_that_cannot_ask_the_user_cannot_write(db_path):
    async with Client(mcp) as client:  # no elicitation support declared
        with pytest.raises(MCPError, match="elicitation"):
            await client.call_tool("place_order", ORDER)
    assert order_count(db_path) == 830


async def test_invalid_order_is_refused_before_asking(db_path):
    seen = []
    discontinued = {**ORDER, "lines": [{"product_id": 9, "quantity": 50}]}
    async with Client(mcp, elicitation_callback=human("accept", {"approve": True}, seen)) as client:
        result = await client.call_tool("place_order", discontinued)
    assert result.is_error and '"discontinued"' in result.content[0].text
    assert seen == []  # the human was never asked
    assert order_count(db_path) == 830
