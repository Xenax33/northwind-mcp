import pytest

from northwind_mcp.errors import NorthwindError
from northwind_mcp.tools import customers


def test_search_by_name_is_case_insensitive(db):
    result = customers.search_customers(db, query="ernst")
    assert [c.customer_id for c in result.customers] == ["ERNSH"]
    assert result.total_count == 1
    assert result.next_cursor is None


def test_search_by_country(db):
    result = customers.search_customers(db, country="germany")
    assert result.total_count == 11
    assert all(c.country == "Germany" for c in result.customers)


def test_paging_walks_every_customer_exactly_once(db):
    seen, cursor, pages = [], None, 0
    while True:
        page = customers.search_customers(db, limit=20, cursor=cursor)
        seen += [c.customer_id for c in page.customers]
        pages += 1
        cursor = page.next_cursor
        if cursor is None:
            break
    assert pages == 5
    assert len(seen) == len(set(seen)) == 91


def test_like_wildcards_in_query_are_literal(db):
    assert customers.search_customers(db, query="%").total_count == 0
    assert customers.search_customers(db, query="_").total_count == 0


def test_customers_without_orders_are_found(db):
    result = customers.search_customers(db, query="FISSA")
    assert result.customers[0].order_count == 0
    assert result.customers[0].last_order_date is None


def test_get_customer(db):
    c = customers.get_customer(db, "ernsh")  # IDs are matched case-insensitively
    assert c.customer_id == "ERNSH"
    assert c.customer_name == "Ernst Handel"
    assert c.contact_name == "Roland Mendel"
    assert c.country == "Austria"
    assert c.order_count == 30
    assert c.revenue == 104874.98
    assert (c.first_order_date, c.last_order_date) == ("2016-07-17", "2018-05-05")
    assert [o.order_id for o in c.recent_orders] == [11072, 11017, 11008, 10990, 10979]


def test_get_customer_who_never_ordered(db):
    c = customers.get_customer(db, "PARIS")
    assert c.order_count == 0
    assert c.revenue == 0
    assert c.recent_orders == []


def test_get_unknown_customer_is_refused_with_hint(db):
    with pytest.raises(NorthwindError) as err:
        customers.get_customer(db, "NOPE1")
    assert err.value.code == "not_found"
    assert "search_customers" in err.value.hint
