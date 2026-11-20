import pytest

from northwind_mcp import paging
from northwind_mcp.errors import NorthwindError

FILTERS = {"query": "a", "country": None}


def test_no_cursor_starts_at_zero():
    assert paging.decode_cursor(None, FILTERS) == 0


def test_cursor_round_trip():
    cursor = paging.encode_cursor(40, FILTERS)
    assert paging.decode_cursor(cursor, FILTERS) == 40


def test_next_cursor_is_none_on_last_page():
    assert paging.next_cursor(offset=80, page_size=11, total=91, filters=FILTERS) is None
    assert paging.next_cursor(offset=60, page_size=20, total=91, filters=FILTERS) is not None


@pytest.mark.parametrize("garbage", ["not-a-cursor", "e30", "%%%", paging.encode_cursor(-5, FILTERS)])
def test_invalid_cursor_is_refused(garbage):
    with pytest.raises(NorthwindError) as err:
        paging.decode_cursor(garbage, FILTERS)
    assert err.value.code == "invalid_argument"


def test_cursor_from_another_query_is_refused():
    cursor = paging.encode_cursor(20, {"query": "a", "country": None})
    with pytest.raises(NorthwindError) as err:
        paging.decode_cursor(cursor, {"query": "a", "country": "Germany"})
    assert err.value.code == "invalid_argument"
    assert "different filters" in err.value.message
