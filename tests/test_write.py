"""The one write: checks before writing, all-or-nothing, and visible afterwards."""

import json
from datetime import date

import pytest

from northwind_mcp.db import read_connection, write_connection
from northwind_mcp.errors import NorthwindError
from northwind_mcp.models import OrderLineInput
from northwind_mcp.tools import orders, write

TODAY = date(2026, 11, 20)


def lines(*pairs):
    return [OrderLineInput(product_id=p, quantity=q) for p, q in pairs]


def counts(db_path):
    with read_connection(db_path) as con:
        return (
            con.execute("SELECT COUNT(*) FROM Orders").fetchone()[0],
            con.execute("SELECT COUNT(*) FROM [Order Details]").fetchone()[0],
            con.execute("SELECT UnitsInStock FROM Products WHERE ProductID = 1").fetchone()[0],
            con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
        )


def test_draft_prices_the_order_and_writes_nothing(db_path):
    before = counts(db_path)
    with read_connection(db_path) as con:
        draft = write.draft_order(con, "alfki", 1, 1, lines((1, 10), (2, 5)))
    assert draft.customer_name == "Alfreds Futterkiste"
    assert [(p.product_name, p.unit_price, p.line_total, p.stock_after) for p in draft.lines] == [
        ("Chai", 18.0, 180.0, 29),
        ("Chang", 19.0, 95.0, 12),
    ]
    assert draft.total == 275.0
    assert "Total: 275.00" in write.describe_draft(draft)
    assert counts(db_path) == before


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (("NOPE1", 1, 1, lines((1, 1))), "not_found"),
        (("ALFKI", 99, 1, lines((1, 1))), "not_found"),
        (("ALFKI", 1, 9, lines((1, 1))), "not_found"),
        (("ALFKI", 1, 1, lines((999, 1))), "not_found"),
        (("ALFKI", 1, 1, lines((9, 50))), "discontinued"),  # question 14: Mishi Kobe Niku
        (("ALFKI", 1, 1, lines((1, 40))), "out_of_stock"),  # Chai has 39
        (("ALFKI", 1, 1, lines((1, 1), (1, 2))), "invalid_argument"),  # same product twice
        (("ALFKI", 1, 1, []), "invalid_argument"),
    ],
)
def test_invalid_orders_are_refused(db_path, args, code):
    with read_connection(db_path) as con, pytest.raises(NorthwindError) as err:
        write.draft_order(con, *args)
    assert err.value.code == code


def test_place_order_writes_everything(db_path):
    with write_connection(db_path) as con:
        placed = write.place_order(con, "ALFKI", 1, 1, lines((1, 10), (2, 5)), today=TODAY, client="pytest")
    assert placed.order_id == 11078
    assert (placed.order_date, placed.required_date) == ("2026-11-20", "2026-12-18")

    with read_connection(db_path) as con:
        order = orders.get_order(con, placed.order_id)
        assert order.status == "unshipped" and order.freight == 0
        assert order.revenue == 275.0
        assert order.customer_name == "Alfreds Futterkiste"
        assert con.execute("SELECT UnitsInStock FROM Products WHERE ProductID = 1").fetchone()[0] == 29
        audit = con.execute("SELECT action, order_id, client, details FROM audit_log").fetchone()
        assert (audit["action"], audit["order_id"], audit["client"]) == ("place_order", 11078, "pytest")
        assert json.loads(audit["details"])["total"] == 275.0


def test_failing_line_means_nothing_is_written(db_path):
    before = counts(db_path)
    with write_connection(db_path) as con, pytest.raises(NorthwindError) as err:
        # line 1 is fine, line 2 is discontinued: the whole order must be refused
        write.place_order(con, "ALFKI", 1, 1, lines((1, 10), (9, 1)), today=TODAY)
    assert err.value.code == "discontinued"
    assert counts(db_path) == before


def test_stock_is_rechecked_at_write_time(db_path):
    # Two orders that each fit the stock on their own, but not together (Chai has 39).
    with write_connection(db_path) as con:
        write.place_order(con, "ALFKI", 1, 1, lines((1, 30)), today=TODAY)
    with write_connection(db_path) as con, pytest.raises(NorthwindError) as err:
        write.place_order(con, "ALFKI", 1, 1, lines((1, 30)), today=TODAY)
    assert err.value.code == "out_of_stock"
    assert counts(db_path)[2] == 9


def test_read_connection_cannot_write(db_path):
    import sqlite3

    with read_connection(db_path) as con, pytest.raises(sqlite3.OperationalError, match="readonly"):
        con.execute("DELETE FROM Orders")


def test_recent_changes_show_placed_orders_newest_first(db_path):
    from northwind_mcp.tools import audit

    with read_connection(db_path) as con:
        assert audit.list_recent_changes(con).total_count == 0
    with write_connection(db_path) as con:
        write.place_order(con, "ALFKI", 1, 1, lines((1, 10)), today=TODAY, client="first")
    with write_connection(db_path) as con:
        write.place_order(con, "ERNSH", 2, 3, lines((2, 1), (3, 2)), today=TODAY, client="second")
    with read_connection(db_path) as con:
        changes = audit.list_recent_changes(con).changes
    assert [(c.order_id, c.client, c.customer_name, c.line_count) for c in changes] == [
        (11079, "second", "Ernst Handel", 2),
        (11078, "first", "Alfreds Futterkiste", 1),
    ]
    assert changes[1].total == 180.0
