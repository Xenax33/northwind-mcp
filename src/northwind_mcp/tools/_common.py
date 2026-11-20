"""Small helpers shared by the tool modules."""

from __future__ import annotations

import sqlite3
from datetime import date

from northwind_mcp.errors import NorthwindError


def like(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with LIKE's own wildcards escaped (use ESCAPE '\\')."""
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def check_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise NorthwindError(
            "invalid_argument",
            f"date_from ({date_from}) is after date_to ({date_to}).",
            "Swap the two dates. Both are inclusive, in YYYY-MM-DD format.",
        )


# What each referenced ID is checked against, and the hint for a miss.
_LOOKUPS = {
    "customer": ("SELECT 1 FROM Customers WHERE CustomerID = ? COLLATE NOCASE", "Use search_customers to find IDs."),
    "employee": ("SELECT 1 FROM Employees WHERE EmployeeID = ?", "Use list_reference(kind='employees')."),
    "product": ("SELECT 1 FROM Products WHERE ProductID = ?", "Use search_products to find IDs."),
    "shipper": ("SELECT 1 FROM Shippers WHERE ShipperID = ?", "Use list_reference(kind='shippers')."),
    "supplier": ("SELECT 1 FROM Suppliers WHERE SupplierID = ?", "Use list_reference(kind='suppliers')."),
    "order": ("SELECT 1 FROM Orders WHERE OrderID = ?", "Use list_orders to find order IDs."),
}


def require(con: sqlite3.Connection, kind: str, value: object) -> None:
    """Refuse with not_found if a referenced ID does not exist, instead of silently returning nothing."""
    sql, hint = _LOOKUPS[kind]
    if con.execute(sql, (value,)).fetchone() is None:
        raise NorthwindError("not_found", f"No {kind} with ID {value!r}.", hint)


def require_category(con: sqlite3.Connection, name: str) -> int:
    row = con.execute(
        "SELECT CategoryID FROM Categories WHERE CategoryName = ? COLLATE NOCASE", (name.strip(),)
    ).fetchone()
    if row is None:
        names = ", ".join(r[0] for r in con.execute("SELECT CategoryName FROM Categories ORDER BY 1"))
        raise NorthwindError("not_found", f"No category named {name!r}.", f"Categories are: {names}.")
    return row[0]
