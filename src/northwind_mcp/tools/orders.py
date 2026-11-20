"""Order tools (read side): plain functions over our views, tested without MCP."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Literal

from northwind_mcp import paging
from northwind_mcp.errors import NorthwindError
from northwind_mcp.models import OrderDetail, OrderLine, OrderListResult, OrderSummary
from northwind_mcp.tools._common import check_date_range, require

OrderStatus = Literal["any", "shipped", "unshipped", "late"]
OrderSort = Literal["newest", "oldest", "revenue"]

_SORTS = {
    "newest": "order_date DESC, order_id DESC",
    "oldest": "order_date, order_id",
    "revenue": "revenue DESC, order_id",
}


def _summary_fields(r: sqlite3.Row) -> dict:
    return {
        "order_id": r["order_id"],
        "order_date": r["order_date"],
        "required_date": r["required_date"],
        "shipped_date": r["shipped_date"],
        "status": r["status"],
        "is_late": bool(r["is_late"]),
        "customer_id": r["customer_id"],
        "customer_name": r["customer_name"],
        "employee_id": r["employee_id"],
        "employee_name": r["employee_name"],
        "shipper_id": r["shipper_id"],
        "shipper_name": r["shipper_name"],
        "line_count": r["line_count"],
        "revenue": round(r["revenue"], 2),
        "freight": round(r["freight"], 2),
    }


def list_orders(
    con: sqlite3.Connection,
    customer_id: str | None = None,
    employee_id: int | None = None,
    product_id: int | None = None,
    shipper_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: OrderStatus = "any",
    sort: OrderSort = "newest",
    limit: int = paging.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> OrderListResult:
    check_date_range(date_from, date_to)
    filters = {
        "customer_id": customer_id.upper().strip() if customer_id else None,
        "employee_id": employee_id,
        "product_id": product_id,
        "shipper_id": shipper_id,
        "date_from": date_from,
        "date_to": date_to,
        "status": status,
        "sort": sort,
    }
    offset = paging.decode_cursor(cursor, filters)

    where, args = [], {}
    if customer_id:
        require(con, "customer", customer_id.strip())
        where.append("customer_id = :customer_id COLLATE NOCASE")
        args["customer_id"] = customer_id.strip()
    if employee_id is not None:
        require(con, "employee", employee_id)
        where.append("employee_id = :employee_id")
        args["employee_id"] = employee_id
    if product_id is not None:
        require(con, "product", product_id)
        where.append("order_id IN (SELECT OrderID FROM [Order Details] WHERE ProductID = :product_id)")
        args["product_id"] = product_id
    if shipper_id is not None:
        require(con, "shipper", shipper_id)
        where.append("shipper_id = :shipper_id")
        args["shipper_id"] = shipper_id
    if date_from:
        where.append("order_date >= :date_from")
        args["date_from"] = date_from.isoformat()
    if date_to:
        where.append("order_date <= :date_to")
        args["date_to"] = date_to.isoformat()
    if status in ("shipped", "unshipped"):
        where.append("status = :status")
        args["status"] = status
    elif status == "late":
        where.append("is_late = 1")
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = con.execute(f"SELECT COUNT(*) FROM v_orders {clause}", args).fetchone()[0]
    rows = con.execute(
        f"SELECT * FROM v_orders {clause} ORDER BY {_SORTS[sort]} LIMIT :limit OFFSET :offset",
        {**args, "limit": limit, "offset": offset},
    ).fetchall()
    return OrderListResult(
        orders=[OrderSummary(**_summary_fields(r)) for r in rows],
        total_count=total,
        next_cursor=paging.next_cursor(offset, len(rows), total, filters),
    )


def get_order(con: sqlite3.Connection, order_id: int) -> OrderDetail:
    row = con.execute("SELECT * FROM v_orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise NorthwindError("not_found", f"No order with ID {order_id}.", "Use list_orders to find order IDs.")
    lines = con.execute(
        "SELECT product_id, product_name, unit_price, quantity, discount, revenue"
        " FROM v_order_lines WHERE order_id = ? ORDER BY product_name",
        (order_id,),
    ).fetchall()
    summary = _summary_fields(row)
    return OrderDetail(
        **summary,
        ship_name=row["ship_name"],
        ship_city=row["ship_city"],
        ship_country=row["ship_country"],
        lines=[
            OrderLine(
                product_id=line["product_id"],
                product_name=line["product_name"],
                unit_price=line["unit_price"],
                quantity=line["quantity"],
                discount=line["discount"],
                revenue=round(line["revenue"], 2),
            )
            for line in lines
        ],
        total_with_freight=round(row["revenue"] + row["freight"], 2),
    )
