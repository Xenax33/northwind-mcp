import shutil
import sqlite3
from pathlib import Path

import pytest

BUILT_DB = Path(__file__).resolve().parent.parent / "data" / "northwind.db"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh copy of the built database for each test, so writes never leak between tests."""
    if not BUILT_DB.exists():
        pytest.fail("data/northwind.db is missing: run `uv run python scripts/build_db.py` first")
    copy = tmp_path / "northwind.db"
    shutil.copyfile(BUILT_DB, copy)
    return copy


@pytest.fixture
def db(db_path: Path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    yield con
    con.close()
