"""Report tools: ranked totals and the small reference tables.

sales_summary exists so the model never adds up order lines itself: the sums are
computed here, in tested SQL, from the price actually paid on each line.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Literal

from northwind_mcp import paging
from northwind_mcp.errors import NorthwindError
from northwind_mcp.models import ReferenceItem, ReferenceResult, SalesGroup, SalesSummaryResult
from northwind_mcp.tools._common import check_date_range, require, require_category

GroupBy = Literal["customer", "product", "category", "employee", "country", "shipper", "month", "year"]
Metric = Literal["revenue", "orders", "units", "freight"]
ReferenceKind = Literal["categories", "suppliers", "employees", "shippers"]

# (key expression, name expression). The same column names exist in v_order_lines and
# v_orders, so the order-level groups can be computed on either view.
_GROUPS: dict[str, tuple[str, str]] = {
    "customer": ("customer_id", "customer_name"),
    "product": ("product_id", "product_name"),
    "category": ("category_id", "category_name"),
    "employee": ("employee_id", "employee_name"),
    "country": ("ship_country", "ship_country"),
    "shipper": ("shipper_id", "shipper_name"),
    "month": ("substr(order_date, 1, 7)", "substr(order_date, 1, 7)"),
    "year": ("substr(order_date, 1, 4)", "substr(order_date, 1, 4)"),
}
_PER_PRODUCT = {"product", "category"}  # freight is charged per order, so it can't be split this way
_METRIC_FIELD = {"revenue": "revenue", "orders": "order_count", "units": "units", "freight": "freight"}


def sales_summary(
    con: sqlite3.Connection,
    group_by: GroupBy,
    metric: Metric = "revenue",
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: str | None = None,
    product_id: int | None = None,
    category: str | None = None,
    employee_id: int | None = None,
    shipper_id: int | None = None,
    limit: int = paging.DEFAULT_LIMIT,
    cursor: str | None = None,
) -> SalesSummaryResult:
    check_date_range(date_from, date_to)
    per_product = group_by in _PER_PRODUCT or product_id is not None or category is not None
    if metric == "freight" and per_product:
        raise NorthwindError(
            "invalid_argument",
            "Freight can't be split by product or category: it is charged once per order.",
            "Group freight by customer, employee, country, shipper, month or year, without a product or "
            "category filter.",
        )
    filters = {
        "group_by": group_by,
        "metric": metric,
        "date_from": date_from,
        "date_to": date_to,
        "customer_id": customer_id.upper().strip() if customer_id else None,
        "product_id": product_id,
        "category": category.lower().strip() if category else None,
        "employee_id": employee_id,
        "shipper_id": shipper_id,
    }
    offset = paging.decode_cursor(cursor, filters)

    # Filters on the order itself apply to both views; product filters only to order lines.
    order_where, line_where, args = [], [], {}
    if date_from:
        order_where.append("order_date >= :date_from")
        args["date_from"] = date_from.isoformat()
    if date_to:
        order_where.append("order_date <= :date_to")
        args["date_to"] = date_to.isoformat()
    if customer_id:
        require(con, "customer", customer_id.strip())
        order_where.append("customer_id = :customer_id COLLATE NOCASE")
        args["customer_id"] = customer_id.strip()
    if employee_id is not None:
        require(con, "employee", employee_id)
        order_where.append("employee_id = :employee_id")
        args["employee_id"] = employee_id
    if shipper_id is not None:
        require(con, "shipper", shipper_id)
        order_where.append("shipper_id = :shipper_id")
        args["shipper_id"] = shipper_id
    if product_id is not None:
        require(con, "product", product_id)
        line_where.append("product_id = :product_id")
        args["product_id"] = product_id
    if category:
        line_where.append("category_id = :category_id")
        args["category_id"] = require_category(con, category)

    key, name = _GROUPS[group_by]
    line_clause = " AND ".join(order_where + line_where)
    rows = con.execute(
        f"SELECT {key} AS key, {name} AS name, SUM(revenue) AS revenue,"
        f" COUNT(DISTINCT order_id) AS order_count, SUM(quantity) AS units"
        f" FROM v_order_lines {'WHERE ' + line_clause if line_clause else ''} GROUP BY {key}",
        args,
    ).fetchall()

    freight: dict[str, float] = {}
    if not per_product:
        order_clause = " AND ".join(order_where)
        freight = {
            str(r[0]): r[1]
            for r in con.execute(
                f"SELECT {key}, SUM(freight) FROM v_orders"
                f" {'WHERE ' + order_clause if order_clause else ''} GROUP BY {key}",
                {k: v for k, v in args.items() if k not in ("product_id", "category_id")},
            )
        }

    groups = [
        SalesGroup(
            key=str(r["key"]),
            name=str(r["name"]),
            revenue=round(r["revenue"], 2),
            order_count=r["order_count"],
            units=r["units"],
            freight=None if per_product else round(freight.get(str(r["key"]), 0.0), 2),
        )
        for r in rows
    ]
    if group_by in ("month", "year"):
        groups.sort(key=lambda g: g.key)  # time series read best in date order
    else:
        field = _METRIC_FIELD[metric]
        groups.sort(key=lambda g: (-(getattr(g, field) or 0), g.name))

    page = groups[offset : offset + limit]
    return SalesSummaryResult(
        group_by=group_by,
        metric=metric,
        total_revenue=round(sum(r["revenue"] for r in rows), 2),
        groups=page,
        total_count=len(groups),
        next_cursor=paging.next_cursor(offset, len(page), len(groups), filters),
    )


def list_reference(con: sqlite3.Connection, kind: ReferenceKind) -> ReferenceResult:
    if kind == "categories":
        items = [
            ReferenceItem(id=r[0], name=r[1], description=r[2])
            for r in con.execute("SELECT CategoryID, CategoryName, Description FROM Categories ORDER BY CategoryName")
        ]
    elif kind == "suppliers":
        items = [
            ReferenceItem(id=r[0], name=r[1], country=r[2], phone=r[3])
            for r in con.execute("SELECT SupplierID, CompanyName, Country, Phone FROM Suppliers ORDER BY CompanyName")
        ]
    elif kind == "employees":
        items = [
            ReferenceItem(id=r[0], name=r[1], title=r[2], country=r[3], reports_to_id=r[4], reports_to_name=r[5])
            for r in con.execute(
                "SELECT e.EmployeeID, e.FirstName || ' ' || e.LastName, e.Title, e.Country, e.ReportsTo,"
                " m.FirstName || ' ' || m.LastName"
                " FROM Employees e LEFT JOIN Employees m ON m.EmployeeID = e.ReportsTo ORDER BY e.EmployeeID"
            )
        ]
    elif kind == "shippers":
        items = [
            ReferenceItem(id=r[0], name=r[1], phone=r[2])
            for r in con.execute("SELECT ShipperID, CompanyName, Phone FROM Shippers ORDER BY ShipperID")
        ]
    else:
        raise NorthwindError(
            "invalid_argument", f"Unknown kind {kind!r}.", "Use categories, suppliers, employees or shippers."
        )
    return ReferenceResult(kind=kind, items=items)
