from datetime import date

import pytest

from northwind_mcp.errors import NorthwindError
from northwind_mcp.tools import orders


def test_get_order_joins_everything(db):
    o = orders.get_order(db, 10248)
    assert (o.customer_name, o.employee_name, o.shipper_name) == (
        "Vins et alcools Chevalier",
        "Steven Buchanan",
        "Federal Shipping",
    )
    assert {line.product_name: line.unit_price for line in o.lines} == {
        "Queso Cabrales": 14.0,
        "Singaporean Hokkien Fried Mee": 9.8,  # the price paid, not the 14.00 list price
        "Mozzarella di Giovanni": 34.8,
    }
    assert (o.revenue, o.freight, o.total_with_freight) == (440.0, 32.38, 472.38)


def test_unshipped_orders_page_through_all_21(db):
    seen, cursor = [], None
    while True:
        page = orders.list_orders(db, status="unshipped", limit=10, cursor=cursor)
        seen += [o.order_id for o in page.orders]
        assert all(o.shipped_date is None for o in page.orders)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 21


def test_late_orders(db):
    result = orders.list_orders(db, status="late", limit=100)
    assert result.total_count == 37
    assert all(o.is_late and o.shipped_date > o.required_date for o in result.orders)


def test_filters_by_product_customer_and_dates(db):
    assert orders.list_orders(db, product_id=1).total_count == 38
    assert orders.list_orders(db, customer_id="ernsh").total_count == 30
    in_2017 = orders.list_orders(db, date_from=date(2017, 1, 1), date_to=date(2017, 12, 31), limit=100)
    assert all("2017-01-01" <= o.order_date <= "2017-12-31" for o in in_2017.orders)


def test_sort_by_revenue(db):
    top = orders.list_orders(db, sort="revenue", limit=3).orders
    assert top[0].revenue >= top[1].revenue >= top[2].revenue


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"customer_id": "NOPE1"}, "not_found"),
        ({"employee_id": 99}, "not_found"),
        ({"product_id": 999}, "not_found"),
        ({"shipper_id": 9}, "not_found"),
        ({"date_from": date(2018, 1, 1), "date_to": date(2017, 1, 1)}, "invalid_argument"),
    ],
)
def test_bad_filters_are_refused(db, kwargs, code):
    with pytest.raises(NorthwindError) as err:
        orders.list_orders(db, **kwargs)
    assert err.value.code == code


def test_cursor_cannot_be_reused_with_other_filters(db):
    page = orders.list_orders(db, status="late", limit=5)
    with pytest.raises(NorthwindError):
        orders.list_orders(db, status="unshipped", limit=5, cursor=page.next_cursor)


def test_get_unknown_order(db):
    with pytest.raises(NorthwindError) as err:
        orders.get_order(db, 1)
    assert err.value.code == "not_found"
