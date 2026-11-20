import shutil
import sqlite3
from pathlib import Path

import pytest

# The pristine build, never written to. The server writes to data/northwind.db instead,
# so orders placed while trying the app can't change what the tests see.
BUILT_DB = Path(__file__).resolve().parent.parent / "data" / "northwind-clean.db"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh copy of the pristine database for each test, so writes never leak between tests."""
    if not BUILT_DB.exists():
        pytest.fail("data/northwind-clean.db is missing: run `uv run python scripts/build_db.py` first")
    copy = tmp_path / "northwind.db"
    shutil.copyfile(BUILT_DB, copy)
    return copy


@pytest.fixture
def db(db_path: Path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    yield con
    con.close()
