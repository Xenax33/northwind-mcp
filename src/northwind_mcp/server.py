"""The MCP server: the public surface of every tool.

This file only declares what the model sees: tool names, argument types and
descriptions, and annotations. All logic lives in `northwind_mcp.tools`, which is
tested directly. Argument limits declared here (lengths, ranges) are checked by
the SDK before a tool runs; a violation comes back to the model as a tool error.

Run with:  uv run northwind-mcp   (stdio transport, for any MCP client)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from northwind_mcp import paging
from northwind_mcp.db import read_connection
from northwind_mcp.models import (
    CustomerDetail,
    CustomerSearchResult,
    InactiveCustomersResult,
    OrderDetail,
    OrderListResult,
    ProductDetail,
    ProductSearchResult,
    ReferenceResult,
    SalesSummaryResult,
)
from northwind_mcp.tools import customers, orders, products, reports

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
CustomerId = Annotated[str, Field(min_length=1, max_length=10, description="Customer ID, e.g. 'ALFKI'.")]
Id = Annotated[int, Field(ge=1, le=1_000_000)]
DateFrom = Annotated[date | None, Field(description="Only orders on or after this date (YYYY-MM-DD).")]
DateTo = Annotated[date | None, Field(description="Only orders on or before this date (YYYY-MM-DD).")]
Category = Annotated[str | None, Field(max_length=50, description="Category name, e.g. 'Seafood'.")]


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
def get_customer(customer_id: CustomerId) -> CustomerDetail:
    """Get one customer's full profile: contact details, number of orders, total revenue,
    first and last order date, and their 5 most recent orders."""
    with read_connection() as con:
        return customers.get_customer(con, customer_id)


@mcp.tool(annotations=READ_ONLY)
def find_inactive_customers(
    since: Annotated[date, Field(description="Find customers with no order on or after this date (YYYY-MM-DD).")],
    limit: Limit = paging.DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> InactiveCustomersResult:
    """Find customers who have not ordered since a date, INCLUDING customers who have never
    ordered at all (last_order_date is null for them). Never-ordered customers come first,
    then the rest by last order date, oldest first."""
    with read_connection() as con:
        return customers.find_inactive_customers(con, since=since, limit=limit, cursor=cursor)


@mcp.tool(annotations=READ_ONLY)
def search_products(
    query: Annotated[str | None, Field(max_length=100, description="Text to match in the product name.")] = None,
    category: Category = None,
    supplier_id: Annotated[int | None, Field(ge=1, description="Only this supplier's products.")] = None,
    stock_status: Annotated[
        products.StockFilter,
        Field(
            description="out_of_stock = 0 units in stock; reorder_needed = still sold and units in stock + "
            "units on order <= reorder level; in_stock = neither."
        ),
    ] = "any",
    discontinued: Annotated[
        bool | None, Field(description="true = only discontinued products, false = only products still sold.")
    ] = None,
    limit: Limit = paging.DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> ProductSearchResult:
    """Find products by name, category, supplier, stock status or discontinued flag, sorted by name.

    Each result includes stock levels, list price, supplier and category. Use get_product for sales figures.
    """
    with read_connection() as con:
        return products.search_products(
            con,
            query=query,
            category=category,
            supplier_id=supplier_id,
            stock_status=stock_status,
            discontinued=discontinued,
            limit=limit,
            cursor=cursor,
        )


@mcp.tool(annotations=READ_ONLY)
def get_product(product_id: Annotated[int, Field(ge=1, description="Product ID, e.g. 1 for Chai.")]) -> ProductDetail:
    """Get one product with its supplier, category, stock levels and sales history
    (units sold, revenue, number of orders, first and last sale)."""
    with read_connection() as con:
        return products.get_product(con, product_id)


@mcp.tool(annotations=READ_ONLY)
def list_orders(
    customer_id: Annotated[str | None, Field(max_length=10, description="Only this customer's orders.")] = None,
    employee_id: Annotated[int | None, Field(ge=1, description="Only orders sold by this employee.")] = None,
    product_id: Annotated[int | None, Field(ge=1, description="Only orders containing this product.")] = None,
    shipper_id: Annotated[int | None, Field(ge=1, description="Only orders shipped by this shipper.")] = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    status: Annotated[
        orders.OrderStatus,
        Field(description="shipped, unshipped (no ship date yet), late (shipped after the required date), or any."),
    ] = "any",
    sort: Annotated[orders.OrderSort, Field(description="newest, oldest, or revenue (largest first).")] = "newest",
    limit: Limit = paging.DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> OrderListResult:
    """List orders matching the filters, one page at a time. Each order includes the customer,
    employee and shipper names, its status, line count, revenue and freight.
    Use get_order for the products in an order. For totals or rankings use sales_summary instead
    of adding up pages."""
    with read_connection() as con:
        return orders.list_orders(
            con,
            customer_id=customer_id,
            employee_id=employee_id,
            product_id=product_id,
            shipper_id=shipper_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            sort=sort,
            limit=limit,
            cursor=cursor,
        )


@mcp.tool(annotations=READ_ONLY)
def get_order(order_id: Annotated[int, Field(ge=1, description="Order ID, e.g. 10248.")]) -> OrderDetail:
    """Get one order in full: customer, employee (who sold it), shipper, dates and status, every
    line with product name, price paid, quantity and discount, and the totals."""
    with read_connection() as con:
        return orders.get_order(con, order_id)


@mcp.tool(annotations=READ_ONLY)
def sales_summary(
    group_by: Annotated[
        reports.GroupBy,
        Field(description="What to total by. country = the country the order was shipped to."),
    ],
    metric: Annotated[
        reports.Metric,
        Field(description="What to rank by: revenue, orders (count), units (quantity sold) or freight."),
    ] = "revenue",
    date_from: DateFrom = None,
    date_to: DateTo = None,
    customer_id: Annotated[str | None, Field(max_length=10, description="Only this customer's orders.")] = None,
    product_id: Annotated[int | None, Field(ge=1, description="Only sales of this product.")] = None,
    category: Category = None,
    employee_id: Annotated[int | None, Field(ge=1, description="Only orders sold by this employee.")] = None,
    shipper_id: Annotated[int | None, Field(ge=1, description="Only orders shipped by this shipper.")] = None,
    limit: Limit = paging.DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> SalesSummaryResult:
    """Totals and rankings, computed by the server: revenue, order count, units and freight per group.

    Groups are ranked by the chosen metric, largest first; month and year groups are in date order
    instead. Use this for any "top", "total", "most" or "by X" question rather than adding up
    orders yourself. Example: top 5 customers by revenue -> group_by="customer", limit=5.
    Example: which customers bought a product -> group_by="customer", product_id=...
    """
    with read_connection() as con:
        return reports.sales_summary(
            con,
            group_by=group_by,
            metric=metric,
            date_from=date_from,
            date_to=date_to,
            customer_id=customer_id,
            product_id=product_id,
            category=category,
            employee_id=employee_id,
            shipper_id=shipper_id,
            limit=limit,
            cursor=cursor,
        )


@mcp.tool(annotations=READ_ONLY)
def list_reference(
    kind: Annotated[reports.ReferenceKind, Field(description="Which small lookup table to list.")],
) -> ReferenceResult:
    """List one of the small lookup tables in full: categories (with descriptions), suppliers
    (with country), employees (with job title and who they report to), or shippers."""
    with read_connection() as con:
        return reports.list_reference(con, kind)


def main() -> None:
    mcp.run()
