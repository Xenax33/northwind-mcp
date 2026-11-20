"""Customer tools: plain functions over our views, tested without MCP."""

from __future__ import annotations

import sqlite3

from northwind_mcp import paging
from northwind_mcp.errors import NorthwindError
from northwind_mcp.models import CustomerDetail, CustomerSearchResult, CustomerSummary, RecentOrder


def _like(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with LIKE's own wildcards escaped."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_customers(
    con: sqlite3.Connection,
    query: str | None = None,
    country: str | None = None,
    limit: int = paging.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> CustomerSearchResult:
    filters = {"query": query, "country": country}
    offset = paging.decode_cursor(cursor, filters)

    where, params = [], []
    if query:
        where.append(
            "(customer_id LIKE :q ESCAPE '\\' OR customer_name LIKE :q ESCAPE '\\'"
            " OR contact_name LIKE :q ESCAPE '\\' OR city LIKE :q ESCAPE '\\')"
        )
        params.append(("q", _like(query.strip())))
    if country:
        where.append("country = :country COLLATE NOCASE")
        params.append(("country", country.strip()))
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    args = dict(params)

    total = con.execute(f"SELECT COUNT(*) FROM v_customers {clause}", args).fetchone()[0]
    rows = con.execute(
        f"SELECT * FROM v_customers {clause} ORDER BY customer_name LIMIT :limit OFFSET :offset",
        {**args, "limit": limit, "offset": offset},
    ).fetchall()

    return CustomerSearchResult(
        customers=[
            CustomerSummary(
                customer_id=r["customer_id"],
                customer_name=r["customer_name"],
                contact_name=r["contact_name"],
                city=r["city"],
                country=r["country"],
                order_count=r["order_count"],
                revenue=round(r["revenue"], 2),
                last_order_date=r["last_order_date"],
            )
            for r in rows
        ],
        total_count=total,
        next_cursor=paging.next_cursor(offset, len(rows), total, filters),
    )


def get_customer(con: sqlite3.Connection, customer_id: str) -> CustomerDetail:
    row = con.execute(
        "SELECT * FROM v_customers WHERE customer_id = ? COLLATE NOCASE", (customer_id.strip(),)
    ).fetchone()
    if row is None:
        raise NorthwindError(
            "not_found",
            f"No customer with ID '{customer_id}'.",
            "Customer IDs are 5-letter codes like 'ALFKI'. Use search_customers to find one by name.",
        )
    recent = con.execute(
        "SELECT order_id, order_date, status, revenue FROM v_orders"
        " WHERE customer_id = ? ORDER BY order_date DESC, order_id DESC LIMIT 5",
        (row["customer_id"],),
    ).fetchall()
    return CustomerDetail(
        customer_id=row["customer_id"],
        customer_name=row["customer_name"],
        contact_name=row["contact_name"],
        contact_title=row["contact_title"],
        phone=row["phone"],
        city=row["city"],
        country=row["country"],
        order_count=row["order_count"],
        revenue=round(row["revenue"], 2),
        first_order_date=row["first_order_date"],
        last_order_date=row["last_order_date"],
        recent_orders=[
            RecentOrder(
                order_id=o["order_id"],
                order_date=o["order_date"],
                status=o["status"],
                revenue=round(o["revenue"], 2),
            )
            for o in recent
        ],
    )
