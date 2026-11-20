"""Build the cleaned Northwind SQLite database used by the MCP server.

Sources (both pinned to a commit and checked by SHA-256):
  * jpwhite3/northwind-SQLite3 - Microsoft's Northwind converted to SQLite (MIT).
  * microsoft/sql-server-samples - Microsoft's original instnwnd.sql.

The SQLite file is padded with ~15.4k random orders. It also rewrote Freight on
the 830 real orders and holds two test customers. This script keeps only the real
data and restores the original Freight values from Microsoft's script. Finally it
applies our own SQL views (src/northwind_mcp/views.sql) and checks the result.

Usage:  uv run python scripts/build_db.py [--out data/northwind.db]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_OUT = ROOT / "data" / "northwind.db"
VIEWS_SQL = ROOT / "src" / "northwind_mcp" / "views.sql"
OUR_VIEWS = ("v_order_lines", "v_orders", "v_products", "v_customers")

# Total revenue of the original Northwind data, as published in Microsoft's samples
# (sum of UnitPrice * Quantity * (1 - Discount)). An independent check on the cleanup.
EXPECTED_TOTAL_REVENUE = 1265793.04

SQLITE_SOURCE = {
    "url": "https://raw.githubusercontent.com/jpwhite3/northwind-SQLite3/"
    "4f56e7f5906dfd23b25244c5bfe8fb5da6402efd/dist/northwind.db",
    "file": "northwind-jpwhite3.db",
    "sha256": "2f4f5c68dfcd33ba27373eae48c7a4869800c68095ee0f9f0da494f83382a877",
}
MSSQL_SOURCE = {
    "url": "https://raw.githubusercontent.com/microsoft/sql-server-samples/"
    "2f85f3724ee45776a5183ed34d064488a6e1dc53/samples/databases/northwind-pubs/instnwnd.sql",
    "file": "instnwnd.sql",
    "sha256": "3cc62b3fca6d244a47dbde698b809331e4f85988a0685b2b370717d431e94871",
}

LAST_REAL_ORDER_ID = 11077  # Microsoft's data ends at 11077; higher IDs are random padding.
JUNK_CUSTOMER_IDS = ("Val2 ", "VALON")  # Test rows (CompanyName 'IT') not in the original.

# Every change made through the MCP server is recorded here, so writes stay visible afterwards.
AUDIT_LOG_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,      -- UTC timestamp, ISO 8601
    action    TEXT NOT NULL,      -- e.g. 'place_order'
    order_id  INTEGER,
    client    TEXT,               -- the MCP client's name, when it sent one
    details   TEXT NOT NULL       -- JSON: what was written
);
"""

EXPECTED_COUNTS = {
    "Orders": 830,
    "Order Details": 2155,
    "Customers": 91,
    "Products": 77,
    "Categories": 8,
    "Suppliers": 29,
    "Employees": 9,
    "Shippers": 3,
}

# One Orders INSERT in instnwnd.sql looks like:
#   VALUES (10248,N'VINET',5,'7/4/1996','8/1/1996','7/16/1996',3,32.38, ...
FREIGHT_RE = re.compile(
    r"VALUES \((\d+),N'\w+',\d+,'[\d/]+','[\d/]+',(?:NULL|'[\d/]+'),\d+,([\d.]+),"
)


def fetch(source: dict[str, str]) -> Path:
    """Download a source once into data/raw and verify its SHA-256."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / source["file"]
    if not path.exists():
        print(f"downloading {source['url']}")
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(source["url"], timeout=60) as resp, tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        tmp.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        path.unlink()
        raise SystemExit(f"checksum mismatch for {source['file']}: got {digest}")
    return path


def parse_original_freight(sql_path: Path) -> dict[int, float]:
    text = sql_path.read_text(encoding="latin-1")
    freight = {int(oid): float(value) for oid, value in FREIGHT_RE.findall(text)}
    if len(freight) != EXPECTED_COUNTS["Orders"]:
        raise SystemExit(f"expected 830 freight values in instnwnd.sql, found {len(freight)}")
    return freight


def clean(db_path: Path, freight: dict[int, float]) -> None:
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute("DELETE FROM [Order Details] WHERE OrderID > ?", (LAST_REAL_ORDER_ID,))
            con.execute("DELETE FROM Orders WHERE OrderID > ?", (LAST_REAL_ORDER_ID,))
            con.execute(
                f"DELETE FROM Customers WHERE CustomerID IN ({','.join('?' * len(JUNK_CUSTOMER_IDS))})",
                JUNK_CUSTOMER_IDS,
            )
            con.executemany(
                "UPDATE Orders SET Freight = ? WHERE OrderID = ?",
                [(value, oid) for oid, value in freight.items()],
            )
            con.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = 'Orders'", (LAST_REAL_ORDER_ID,)
            )
        con.executescript(VIEWS_SQL.read_text(encoding="utf-8"))
        con.executescript(AUDIT_LOG_SQL)
        con.execute("VACUUM")
    finally:
        con.close()


def verify(db_path: Path, freight: dict[int, float]) -> None:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for table, expected in EXPECTED_COUNTS.items():
            actual = con.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            if actual != expected:
                raise SystemExit(f"{table}: expected {expected} rows, found {actual}")
        if broken := con.execute("PRAGMA foreign_key_check").fetchall():
            raise SystemExit(f"foreign key violations: {broken[:5]}")
        stored = dict(con.execute("SELECT OrderID, Freight FROM Orders").fetchall())
        wrong = [oid for oid, value in freight.items() if abs(stored[oid] - value) > 1e-9]
        if wrong:
            raise SystemExit(f"freight not restored for orders {wrong[:5]}")
        views = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
        if missing := set(OUR_VIEWS) - views:
            raise SystemExit(f"views not created: {sorted(missing)}")
        if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'audit_log'").fetchone() is None:
            raise SystemExit("audit_log table not created")
        total = con.execute("SELECT ROUND(SUM(revenue), 2) FROM v_order_lines").fetchone()[0]
        if total != EXPECTED_TOTAL_REVENUE:
            raise SystemExit(f"total revenue {total} != expected {EXPECTED_TOTAL_REVENUE}")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the working database the server uses")
    args = parser.parse_args()
    # Two files: a pristine copy that is never written to (tests and the eval start from it),
    # and the working copy that the server writes orders into. Re-running this script resets both.
    pristine = args.out.with_name(args.out.stem + "-clean" + args.out.suffix)

    source_db = fetch(SQLITE_SOURCE)
    freight = parse_original_freight(fetch(MSSQL_SOURCE))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = args.out.with_suffix(".building")
    shutil.copyfile(source_db, tmp_out)
    clean(tmp_out, freight)
    verify(tmp_out, freight)
    tmp_out.replace(pristine)
    shutil.copyfile(pristine, args.out)
    print(f"built {pristine} (pristine) and {args.out} (working copy), {args.out.stat().st_size // 1024} KiB each")


if __name__ == "__main__":
    sys.exit(main())
