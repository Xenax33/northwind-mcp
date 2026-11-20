"""The one action that changes data: placing an order.

Two steps, kept separate on purpose:

1. `draft_order` checks and prices the order on a read-only connection. Nothing is
   written. The MCP layer shows this draft to the human and asks for approval
   (MCP elicitation) before step 2 can run.
2. `place_order` writes it, all or nothing, in one transaction. It checks everything
   again inside the transaction, because stock may have changed while the human
   was deciding.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from northwind_mcp.errors import NorthwindError
from northwind_mcp.models import (
    MAX_ORDER_LINES,
    OrderDraft,
    OrderLineInput,
    PlacedOrder,
    PricedLine,
)

REQUIRED_AFTER_DAYS = 28  # 701 of the 830 historical orders use exactly 28 days


def _one(con: sqlite3.Connection, sql: str, params: tuple, error: NorthwindError) -> sqlite3.Row:
    row = con.execute(sql, params).fetchone()
    if row is None:
        raise error
    return row


def draft_order(
    con: sqlite3.Connection,
    customer_id: str,
    employee_id: int,
    shipper_id: int,
    lines: list[OrderLineInput],
) -> OrderDraft:
    """Check every part of the order and price it. Raises NorthwindError on the first problem."""
    if not 1 <= len(lines) <= MAX_ORDER_LINES:
        raise NorthwindError(
            "invalid_argument",
            f"An order needs 1 to {MAX_ORDER_LINES} lines; got {len(lines)}.",
            "Split very large orders into several orders.",
        )
    product_ids = [line.product_id for line in lines]
    if duplicates := sorted({p for p in product_ids if product_ids.count(p) > 1}):
        raise NorthwindError(
            "invalid_argument",
            f"Product(s) {duplicates} appear on more than one line.",
            "Put each product on one line and add the quantities together.",
        )

    customer = _one(
        con,
        "SELECT CustomerID, CompanyName FROM Customers WHERE CustomerID = ? COLLATE NOCASE",
        (customer_id.strip(),),
        NorthwindError("not_found", f"No customer with ID {customer_id!r}.", "Use search_customers to find IDs."),
    )
    employee = _one(
        con,
        "SELECT EmployeeID, FirstName || ' ' || LastName FROM Employees WHERE EmployeeID = ?",
        (employee_id,),
        NorthwindError(
            "not_found", f"No employee with ID {employee_id}.", "Use list_reference(kind='employees')."
        ),
    )
    shipper = _one(
        con,
        "SELECT ShipperID, CompanyName FROM Shippers WHERE ShipperID = ?",
        (shipper_id,),
        NorthwindError("not_found", f"No shipper with ID {shipper_id}.", "Use list_reference(kind='shippers')."),
    )

    priced: list[PricedLine] = []
    for n, line in enumerate(lines, start=1):
        product = _one(
            con,
            "SELECT product_id, product_name, list_price, units_in_stock, discontinued"
            " FROM v_products WHERE product_id = ?",
            (line.product_id,),
            NorthwindError(
                "not_found", f"Line {n}: no product with ID {line.product_id}.", "Use search_products to find IDs."
            ),
        )
        if product["discontinued"]:
            raise NorthwindError(
                "discontinued",
                f"Line {n}: {product['product_name']} is discontinued and can no longer be ordered.",
                "Use search_products(discontinued=false) to find a product that is still sold.",
            )
        if line.quantity > product["units_in_stock"]:
            raise NorthwindError(
                "out_of_stock",
                f"Line {n}: only {product['units_in_stock']} units of {product['product_name']} in stock, "
                f"{line.quantity} requested.",
                "Lower the quantity or choose another product.",
            )
        priced.append(
            PricedLine(
                product_id=product["product_id"],
                product_name=product["product_name"],
                unit_price=product["list_price"],
                quantity=line.quantity,
                line_total=round(product["list_price"] * line.quantity, 2),
                stock_before=product["units_in_stock"],
                stock_after=product["units_in_stock"] - line.quantity,
            )
        )

    return OrderDraft(
        customer_id=customer[0],
        customer_name=customer[1],
        employee_id=employee[0],
        employee_name=employee[1],
        shipper_id=shipper[0],
        shipper_name=shipper[1],
        lines=priced,
        total=round(sum(p.line_total for p in priced), 2),
    )


def describe_draft(draft: OrderDraft) -> str:
    """The text the human sees in the approval dialog."""
    lines = "\n".join(
        f"  - {p.quantity} x {p.product_name} @ {p.unit_price:.2f} = {p.line_total:.2f}"
        f"  (stock {p.stock_before} -> {p.stock_after})"
        for p in draft.lines
    )
    return (
        f"Place this order?\n"
        f"Customer: {draft.customer_name} ({draft.customer_id})\n"
        f"Sold by: {draft.employee_name}. Shipped by: {draft.shipper_name}.\n"
        f"{lines}\n"
        f"Total: {draft.total:.2f} (no discount; freight is added when it ships)"
    )


def place_order(
    con: sqlite3.Connection,
    customer_id: str,
    employee_id: int,
    shipper_id: int,
    lines: list[OrderLineInput],
    today: date | None = None,
    client: str | None = None,
) -> PlacedOrder:
    """Write the order, all or nothing. `con` must be a writable connection."""
    today = today or date.today()
    con.isolation_level = None  # we manage the transaction ourselves
    con.execute("BEGIN IMMEDIATE")  # take the write lock now, so nobody changes stock under us
    try:
        draft = draft_order(con, customer_id, employee_id, shipper_id, lines)  # re-check inside the transaction
        customer = con.execute(
            "SELECT CompanyName, Address, City, Region, PostalCode, Country FROM Customers WHERE CustomerID = ?",
            (draft.customer_id,),
        ).fetchone()
        required = today + timedelta(days=REQUIRED_AFTER_DAYS)
        order_id = con.execute(
            "INSERT INTO Orders (CustomerID, EmployeeID, OrderDate, RequiredDate, ShippedDate, ShipVia, Freight,"
            " ShipName, ShipAddress, ShipCity, ShipRegion, ShipPostalCode, ShipCountry)"
            " VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?, ?, ?, ?, ?)",
            (
                draft.customer_id,
                draft.employee_id,
                today.isoformat(),
                required.isoformat(),
                draft.shipper_id,
                *customer,
            ),
        ).lastrowid
        for p in draft.lines:
            con.execute(
                "INSERT INTO [Order Details] (OrderID, ProductID, UnitPrice, Quantity, Discount) VALUES (?, ?, ?, ?, 0)",
                (order_id, p.product_id, p.unit_price, p.quantity),
            )
            updated = con.execute(
                "UPDATE Products SET UnitsInStock = UnitsInStock - ? WHERE ProductID = ? AND UnitsInStock >= ?",
                (p.quantity, p.product_id, p.quantity),
            ).rowcount
            if updated != 1:  # cannot happen under BEGIN IMMEDIATE, but never go below zero
                raise NorthwindError("out_of_stock", f"Stock of {p.product_name} changed; nothing was written.")
        placed = PlacedOrder(
            **draft.model_dump(),
            order_id=order_id,
            order_date=today.isoformat(),
            required_date=required.isoformat(),
        )
        con.execute(
            "INSERT INTO audit_log (at, action, order_id, client, details) VALUES (?, 'place_order', ?, ?, ?)",
            (datetime.now(UTC).isoformat(timespec="seconds"), order_id, client, json.dumps(placed.model_dump())),
        )
        con.execute("COMMIT")
        return placed
    except BaseException:
        con.execute("ROLLBACK")
        raise
