"""The SQL views hold the joins and business rules, so their numbers are pinned here.

Expected values were checked against the cleaned data and, where available,
against figures published for the original Northwind database.
"""

import pytest


def scalar(db, sql, *params):
    return db.execute(sql, params).fetchone()[0]


@pytest.mark.parametrize(
    ("view", "rows"),
    [("v_orders", 830), ("v_order_lines", 2155), ("v_products", 77), ("v_customers", 91)],
)
def test_view_row_counts(db, view, rows):
    assert scalar(db, f"SELECT COUNT(*) FROM {view}") == rows


def test_total_revenue_matches_published_northwind_total(db):
    assert scalar(db, "SELECT ROUND(SUM(revenue), 2) FROM v_order_lines") == 1265793.04


def test_revenue_uses_price_paid_not_current_list_price(db):
    # Order 10248 sold Singaporean Hokkien Fried Mee (product 42) at 9.80; its list price is 14.00.
    line = db.execute(
        "SELECT unit_price, revenue FROM v_order_lines WHERE order_id = 10248 AND product_id = 42"
    ).fetchone()
    assert line["unit_price"] == 9.8
    assert line["revenue"] == pytest.approx(98.0)
    assert scalar(db, "SELECT list_price FROM v_products WHERE product_id = 42") == 14.0
    # 12 x 14.00 + 10 x 9.80 + 5 x 34.80
    assert scalar(db, "SELECT revenue FROM v_orders WHERE order_id = 10248") == pytest.approx(440.0)


def test_order_joins_carry_names(db):
    order = db.execute("SELECT * FROM v_orders WHERE order_id = 10248").fetchone()
    assert order["customer_name"] == "Vins et alcools Chevalier"
    assert order["employee_name"] == "Steven Buchanan"
    assert order["shipper_name"] == "Federal Shipping"
    assert order["freight"] == 32.38  # restored from Microsoft's original
    assert order["line_count"] == 3


def test_order_status_counts(db):
    assert scalar(db, "SELECT COUNT(*) FROM v_orders WHERE status = 'unshipped'") == 21
    assert scalar(db, "SELECT COUNT(*) FROM v_orders WHERE is_late = 1") == 37


def test_stock_status(db):
    reorder = {
        r[0] for r in db.execute("SELECT product_name FROM v_products WHERE stock_status = 'reorder_needed'")
    }
    assert reorder == {"Nord-Ost Matjeshering", "Outback Lager"}
    assert scalar(db, "SELECT COUNT(*) FROM v_products WHERE stock_status = 'out_of_stock'") == 5
    assert scalar(db, "SELECT COUNT(*) FROM v_products WHERE discontinued = 1") == 8


def test_customers_without_orders_are_included(db):
    rows = db.execute(
        "SELECT customer_id, order_count, revenue, last_order_date FROM v_customers WHERE order_count = 0"
    ).fetchall()
    assert {r["customer_id"] for r in rows} == {"FISSA", "PARIS"}
    assert all(r["revenue"] == 0 and r["last_order_date"] is None for r in rows)


def test_top_customer_by_revenue(db):
    top = db.execute(
        "SELECT customer_name, ROUND(revenue, 2) AS revenue FROM v_customers ORDER BY revenue DESC LIMIT 1"
    ).fetchone()
    assert (top["customer_name"], top["revenue"]) == ("QUICK-Stop", 110277.3)


def test_inactive_customers_in_last_six_months_of_data(db):
    rows = db.execute(
        "SELECT customer_id FROM v_customers WHERE last_order_date IS NULL OR last_order_date < '2017-11-06'"
    ).fetchall()
    assert {r[0] for r in rows} == {"FISSA", "PARIS", "CENTC", "LAZYK", "HUNGC", "MEREP", "FAMIA"}
