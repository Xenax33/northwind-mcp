"""Product tools: plain functions over our views, tested without MCP."""

from __future__ import annotations

import sqlite3
from typing import Literal

from northwind_mcp import paging
from northwind_mcp.errors import NorthwindError
from northwind_mcp.models import ProductDetail, ProductSearchResult, ProductSummary
from northwind_mcp.tools._common import like, require, require_category

StockFilter = Literal["any", "in_stock", "out_of_stock", "reorder_needed"]


def _summary_fields(r: sqlite3.Row) -> dict:
    return {
        "product_id": r["product_id"],
        "product_name": r["product_name"],
        "category_id": r["category_id"],
        "category_name": r["category_name"],
        "supplier_id": r["supplier_id"],
        "supplier_name": r["supplier_name"],
        "list_price": r["list_price"],
        "units_in_stock": r["units_in_stock"],
        "units_on_order": r["units_on_order"],
        "reorder_level": r["reorder_level"],
        "discontinued": bool(r["discontinued"]),
        "stock_status": r["stock_status"],
    }


def search_products(
    con: sqlite3.Connection,
    query: str | None = None,
    category: str | None = None,
    supplier_id: int | None = None,
    stock_status: StockFilter = "any",
    discontinued: bool | None = None,
    limit: int = paging.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> ProductSearchResult:
    filters = {
        "query": query,
        "category": category,
        "supplier_id": supplier_id,
        "stock_status": stock_status,
        "discontinued": discontinued,
    }
    offset = paging.decode_cursor(cursor, filters)

    where, args = [], {}
    if query:
        where.append("product_name LIKE :q ESCAPE '\\'")
        args["q"] = like(query)
    if category:
        where.append("category_id = :category_id")
        args["category_id"] = require_category(con, category)
    if supplier_id is not None:
        require(con, "supplier", supplier_id)
        where.append("supplier_id = :supplier_id")
        args["supplier_id"] = supplier_id
    if stock_status != "any":
        where.append("stock_status = :stock_status")
        args["stock_status"] = stock_status
    if discontinued is not None:
        where.append("discontinued = :discontinued")
        args["discontinued"] = int(discontinued)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = con.execute(f"SELECT COUNT(*) FROM v_products {clause}", args).fetchone()[0]
    rows = con.execute(
        f"SELECT * FROM v_products {clause} ORDER BY product_name LIMIT :limit OFFSET :offset",
        {**args, "limit": limit, "offset": offset},
    ).fetchall()
    return ProductSearchResult(
        products=[ProductSummary(**_summary_fields(r)) for r in rows],
        total_count=total,
        next_cursor=paging.next_cursor(offset, len(rows), total, filters),
    )


def get_product(con: sqlite3.Connection, product_id: int) -> ProductDetail:
    row = con.execute("SELECT * FROM v_products WHERE product_id = ?", (product_id,)).fetchone()
    if row is None:
        raise NorthwindError(
            "not_found", f"No product with ID {product_id}.", "Use search_products to find product IDs."
        )
    sales = con.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS units, COALESCE(SUM(revenue), 0) AS revenue,"
        " COUNT(DISTINCT order_id) AS orders, MIN(order_date) AS first, MAX(order_date) AS last"
        " FROM v_order_lines WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    return ProductDetail(
        **_summary_fields(row),
        supplier_country=row["supplier_country"],
        quantity_per_unit=row["quantity_per_unit"],
        units_sold=sales["units"],
        revenue=round(sales["revenue"], 2),
        order_count=sales["orders"],
        first_sold_date=sales["first"],
        last_sold_date=sales["last"],
    )
