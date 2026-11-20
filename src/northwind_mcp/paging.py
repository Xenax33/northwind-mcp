"""Cursor-based paging for list tools.

A cursor is an opaque string the model passes back unchanged to get the next
page. Inside, it is the offset plus a fingerprint of the query's filters, so a
cursor from one query cannot be reused on another (that would silently return
the wrong rows). This is the same convention MCP itself uses for tools/list.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from northwind_mcp.errors import NorthwindError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

_RESTART_HINT = "Pass next_cursor exactly as it was returned, or leave cursor out to start from the first page."


def _fingerprint(filters: dict[str, Any]) -> str:
    canonical = json.dumps(filters, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(offset: int, filters: dict[str, Any]) -> str:
    raw = json.dumps({"o": offset, "f": _fingerprint(filters)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, filters: dict[str, Any]) -> int:
    """Return the offset a cursor points to (0 when there is no cursor)."""
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        offset, fingerprint = int(data["o"]), str(data["f"])
    except (ValueError, KeyError, TypeError):
        raise NorthwindError("invalid_argument", "The cursor is not valid.", _RESTART_HINT) from None
    if offset < 0:
        raise NorthwindError("invalid_argument", "The cursor is not valid.", _RESTART_HINT)
    if fingerprint != _fingerprint(filters):
        raise NorthwindError(
            "invalid_argument",
            "This cursor belongs to a query with different filters.",
            "Repeat the exact filters of the call that returned the cursor, or leave cursor out.",
        )
    return offset


def next_cursor(offset: int, page_size: int, total: int, filters: dict[str, Any]) -> str | None:
    """The cursor for the following page, or None when this was the last page."""
    following = offset + page_size
    return encode_cursor(following, filters) if following < total else None
