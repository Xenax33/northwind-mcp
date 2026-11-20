"""The MCP server: the public surface of every tool.

This file only declares what the model sees: tool names, argument types and
descriptions, and annotations. All logic lives in `northwind_mcp.tools`, which is
tested directly. Argument limits declared here (lengths, ranges) are checked by
the SDK before a tool runs; a violation comes back to the model as a tool error.

Run with:  uv run northwind-mcp   (stdio transport, for any MCP client)
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from northwind_mcp import paging
from northwind_mcp.db import read_connection
from northwind_mcp.models import CustomerDetail, CustomerSearchResult
from northwind_mcp.tools import customers

INSTRUCTIONS = """\
Northwind trading company data: customers, orders, order lines, products, categories,
suppliers, employees and shippers.

- The orders run from 2016-07-04 to 2018-05-06. When the user says "recent" or "the last
  N months" without giving dates, count back from 2018-05-06.
- Revenue = price actually paid x quantity x (1 - discount). Freight is not revenue.
- Never invent IDs. Get them from the search and list tools.
- List tools return one page at a time. If next_cursor is not null there are more results:
  call the same tool again with the same filters and cursor=next_cursor.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

mcp = MCPServer(name="northwind", instructions=INSTRUCTIONS)

Limit = Annotated[
    int, Field(ge=1, le=paging.MAX_LIMIT, description=f"Results per page (1-{paging.MAX_LIMIT}).")
]
Cursor = Annotated[
    str | None, Field(max_length=200, description="next_cursor from the previous page; leave out for page 1.")
]


@mcp.tool(annotations=READ_ONLY)
def search_customers(
    query: Annotated[
        str | None,
        Field(max_length=100, description="Text to match in the customer ID, company name, contact name or city."),
    ] = None,
    country: Annotated[str | None, Field(max_length=50, description="Exact country, e.g. 'Germany'.")] = None,
    limit: Limit = paging.DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> CustomerSearchResult:
    """Find customers by name, contact, city or country, sorted by company name.

    Each result includes the customer's order count, total revenue and last order date.
    Use this to find a customer_id before calling get_customer or list_orders.
    """
    with read_connection() as con:
        return customers.search_customers(con, query=query, country=country, limit=limit, cursor=cursor)


@mcp.tool(annotations=READ_ONLY)
def get_customer(
    customer_id: Annotated[str, Field(min_length=1, max_length=10, description="Customer ID, e.g. 'ALFKI'.")],
) -> CustomerDetail:
    """Get one customer's full profile: contact details, number of orders, total revenue,
    first and last order date, and their 5 most recent orders."""
    with read_connection() as con:
        return customers.get_customer(con, customer_id)


def main() -> None:
    mcp.run()
