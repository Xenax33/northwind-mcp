"""The host's compaction of tool results before they go to the model (columns + rows)."""

import json

from northwind_host.agent import compact
from northwind_mcp.db import read_connection
from northwind_mcp.tools import orders


def expand(value):
    """Undo compact(): turn {"columns", "rows"} back into a list of objects."""
    if isinstance(value, dict) and set(value) == {"columns", "rows"}:
        return [dict(zip(value["columns"], [expand(v) for v in row])) for row in value["rows"]]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value


def test_lists_of_same_shaped_objects_become_columns_and_rows():
    data = {"total": 2, "items": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}
    assert compact(data) == {"total": 2, "items": {"columns": ["id", "name"], "rows": [[1, "a"], [2, "b"]]}}


def test_nothing_is_lost(db_path):
    with read_connection(db_path) as con:
        order = orders.get_order(con, 10248).model_dump(mode="json")  # nested list of lines
        late = orders.list_orders(con, status="late", limit=100).model_dump(mode="json")
    assert expand(compact(order)) == order
    assert expand(compact(late)) == late


def test_other_shapes_are_left_alone():
    assert compact([{"a": 1}]) == [{"a": 1}]  # a single object: nothing to gain
    assert compact([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]  # different shapes
    assert compact([1, 2, 3]) == [1, 2, 3]


def test_a_page_of_37_orders_more_than_halves(db_path):
    with read_connection(db_path) as con:
        late = orders.list_orders(con, status="late", limit=100).model_dump(mode="json")
    before = len(json.dumps(late, ensure_ascii=False))
    after = len(json.dumps(compact(late), ensure_ascii=False, separators=(",", ":")))
    assert after < before / 2
