from datetime import date

import pytest

from northwind_mcp.errors import NorthwindError
from northwind_mcp.tools import reports

YEAR_2017 = {"date_from": date(2017, 1, 1), "date_to": date(2017, 12, 31)}


def test_top_five_customers_by_revenue(db):
    result = reports.sales_summary(db, group_by="customer", limit=5)
    assert [(g.name, g.revenue) for g in result.groups] == [
        ("QUICK-Stop", 110277.3),
        ("Ernst Handel", 104874.98),
        ("Save-a-lot Markets", 104361.95),
        ("Rattlesnake Canyon Grocery", 51097.8),
        ("Hungry Owl All-Night Grocers", 49979.9),
    ]
    assert result.total_revenue == 1265793.04


def test_sales_by_category_in_2017(db):
    result = reports.sales_summary(db, group_by="category", **YEAR_2017)
    assert result.total_count == 8
    assert (result.groups[0].name, result.groups[0].revenue) == ("Dairy Products", 115387.64)
    assert result.total_revenue == pytest.approx(sum(g.revenue for g in result.groups), abs=0.05)


def test_shipper_with_most_freight(db):
    result = reports.sales_summary(db, group_by="shipper", metric="freight")
    assert [(g.name, g.freight) for g in result.groups] == [
        ("United Package", 28244.85),
        ("Federal Shipping", 20512.51),
        ("Speedy Express", 16185.33),
    ]


def test_customers_who_bought_a_product(db):
    result = reports.sales_summary(db, group_by="customer", product_id=1, limit=100)
    assert result.total_count == 31
    assert result.total_revenue == 12788.1
    assert all(g.freight is None for g in result.groups)  # freight can't be split per product


def test_employee_sales_in_a_year(db):
    result = reports.sales_summary(db, group_by="employee", employee_id=6, **YEAR_2017)
    (suyama,) = result.groups
    assert (suyama.name, suyama.revenue, suyama.order_count) == ("Michael Suyama", 43126.37, 33)


def test_months_are_in_date_order(db):
    result = reports.sales_summary(db, group_by="month", limit=100)
    keys = [g.key for g in result.groups]
    assert keys == sorted(keys)
    assert (keys[0], keys[-1]) == ("2016-07", "2018-05")


def test_freight_by_product_is_refused(db):
    with pytest.raises(NorthwindError) as err:
        reports.sales_summary(db, group_by="product", metric="freight")
    assert err.value.code == "invalid_argument"


def test_reference_lists(db):
    employees = {e.name: e for e in reports.list_reference(db, "employees").items}
    assert employees["Michael Suyama"].reports_to_name == "Steven Buchanan"
    assert employees["Andrew Fuller"].reports_to_id is None
    assert len(reports.list_reference(db, "categories").items) == 8
    assert len(reports.list_reference(db, "suppliers").items) == 29
    assert len(reports.list_reference(db, "shippers").items) == 3
