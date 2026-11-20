import pytest

from northwind_mcp.errors import NorthwindError
from northwind_mcp.tools import products


def test_reorder_needed_counts_stock_already_on_order(db):
    result = products.search_products(db, stock_status="reorder_needed")
    assert {p.product_name for p in result.products} == {"Nord-Ost Matjeshering", "Outback Lager"}


def test_out_of_stock_and_discontinued_filters(db):
    assert products.search_products(db, stock_status="out_of_stock").total_count == 5
    discontinued = products.search_products(db, discontinued=True)
    assert discontinued.total_count == 8
    assert all(p.discontinued for p in discontinued.products)


def test_category_filter_is_case_insensitive_and_pages(db):
    first = products.search_products(db, category="seafood", limit=5)
    assert first.total_count == 12
    second = products.search_products(db, category="seafood", limit=5, cursor=first.next_cursor)
    assert {p.product_id for p in first.products}.isdisjoint(p.product_id for p in second.products)


def test_seafood_comes_from_eight_suppliers(db):
    result = products.search_products(db, category="Seafood", limit=100)
    assert len({p.supplier_id for p in result.products}) == 8


def test_unknown_category_lists_the_real_ones(db):
    with pytest.raises(NorthwindError) as err:
        products.search_products(db, category="Toys")
    assert err.value.code == "not_found"
    assert "Seafood" in err.value.hint


def test_get_product_with_sales(db):
    chai = products.get_product(db, 1)
    assert (chai.product_name, chai.supplier_name, chai.category_name) == ("Chai", "Exotic Liquids", "Beverages")
    assert (chai.units_sold, chai.revenue, chai.order_count) == (828, 12788.1, 38)


def test_get_unknown_product(db):
    with pytest.raises(NorthwindError) as err:
        products.get_product(db, 999)
    assert err.value.code == "not_found"
