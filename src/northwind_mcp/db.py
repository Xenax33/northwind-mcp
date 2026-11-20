"""Database connections.

Reads use a read-only connection (SQLite `mode=ro`), so even a bug in a read
tool cannot change data. Only the write tool opens a writable connection.
A new connection is opened per tool call: SQLite connections are cheap, and it
keeps calls independent of each other and of threads.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "northwind.db"


def db_path() -> Path:
    """The database file: $NORTHWIND_DB if set, otherwise data/northwind.db in the repo."""
    return Path(os.environ.get("NORTHWIND_DB", DEFAULT_DB_PATH))


def _require(path: Path) -> Path:
    if not path.exists():
        raise RuntimeError(f"Database not found at {path}. Run `uv run python scripts/build_db.py` first.")
    return path


@contextmanager
def read_connection(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    uri = _require(path or db_path()).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


@contextmanager
def write_connection(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(_require(path or db_path()))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
    finally:
        con.close()
