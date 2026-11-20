"""End-to-end over the real MCP protocol, with an in-memory client.

These check what a client actually receives: tool list, schemas, annotations,
structured results, and that bad requests come back as clean tool errors.
"""

import json

import pytest
from mcp.client.client import Client

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
    }
    for name in tools:
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].output_schema is not None


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
