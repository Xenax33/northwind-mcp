"""Reading the audit log: every change made through this server, newest first."""

from __future__ import annotations

import json
import sqlite3

from northwind_mcp import paging
from northwind_mcp.models import ChangeEntry, RecentChangesResult


def list_recent_changes(
    con: sqlite3.Connection, limit: int = 10, cursor: str | None = None
) -> RecentChangesResult:
    filters: dict = {}
    offset = paging.decode_cursor(cursor, filters)
    total = con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    rows = con.execute(
        "SELECT id, at, action, order_id, client, details FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    changes = []
    for r in rows:
        details = json.loads(r["details"])
        changes.append(
            ChangeEntry(
                change_id=r["id"],
                at=r["at"],
                action=r["action"],
                order_id=r["order_id"],
                client=r["client"],
                customer_id=details.get("customer_id"),
                customer_name=details.get("customer_name"),
                line_count=len(details.get("lines", [])),
                total=details.get("total"),
            )
        )
    return RecentChangesResult(
        changes=changes,
        total_count=total,
        next_cursor=paging.next_cursor(offset, len(rows), total, filters),
    )
