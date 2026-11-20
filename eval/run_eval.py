"""Run the 14 evaluation questions through the web host and report the results.

By default the script starts its own host on a fresh copy of the pristine database
(data/northwind-clean.db), with automatic approval switched on for that host only,
so question 13 can place its order without a human. The full stack is exercised:
HTTP -> host -> stdio -> MCP server -> SQLite, with the model on Groq.

Usage:
  uv run python eval/run_eval.py                 # all questions, own host
  uv run python eval/run_eval.py --only 9,13     # some questions
  uv run python eval/run_eval.py --url URL       # an already-running host (write question skipped)

Each answer passes when (1) at least one expected tool was called, (2) every expected
fact appears in the answer, and (3) for the write/refusal questions, the database shows
exactly the expected change (or none). Results go to eval/results/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions.json"
RESULTS = ROOT / "eval" / "results"
PRISTINE_DB = ROOT / "data" / "northwind-clean.db"
ASK_TIMEOUT = 900  # seconds; the free Groq tier (8K tokens/minute) makes long questions slow


# ---------- Normalising answers so formatting doesn't matter ----------

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‛′"), "'") | dict.fromkeys(map(ord, "“”"), '"')


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).translate(_DASHES).translate(_QUOTES)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace(" ", " ").replace("*", "").replace("\\", "")
    return re.sub(r"\s+", " ", text).lower()


def numbers_in(text: str) -> list[float]:
    text = re.sub(r"(?<=\d)[,  ](?=\d{3}\b)", "", text)  # 110,277.30 -> 110277.30
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text)]


def fact_found(fact: str | float, answer: str, answer_numbers: list[float]) -> bool:
    if isinstance(fact, (int, float)):
        return any(abs(n - fact) < 0.01 for n in answer_numbers)
    return normalise(str(fact)) in normalise(answer)


# ---------- Database checks (own-host mode only) ----------


def db_counts(db_path: Path) -> tuple[int, int]:
    """(orders, audit rows): taken before each question, so each check sees only its own change."""
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return (
            con.execute("SELECT COUNT(*) FROM Orders").fetchone()[0],
            con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
        )
    finally:
        con.close()


def check_db(db_path: Path, spec: dict, before: tuple[int, int]) -> list[str]:
    """Return a list of problems (empty = passed). `before` = db_counts() taken before the question."""
    problems = []
    orders, audit = db_counts(db_path)
    new_orders, new_audit = orders - before[0], audit - before[1]
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        if spec.get("nothing_written") and (new_orders or new_audit):
            problems.append(f"expected no change, found {new_orders} new orders and {new_audit} new audit rows")
        if want := spec.get("order_written"):
            row = con.execute(
                "SELECT o.CustomerID, d.ProductID, d.Quantity FROM Orders o JOIN [Order Details] d USING (OrderID)"
                " WHERE o.OrderID = ?",
                (want["order_id"],),
            ).fetchall()
            if row != [(want["customer_id"], want["product_id"], want["quantity"])]:
                problems.append(f"order {want['order_id']} not written as expected: {row}")
            if new_orders != 1 or new_audit != 1:
                problems.append(f"expected 1 new order and 1 new audit row, found {new_orders} and {new_audit}")
        if want := spec.get("stock"):
            units = con.execute("SELECT UnitsInStock FROM Products WHERE ProductID = ?", (want["product_id"],)).fetchone()[0]
            if units != want["units_in_stock"]:
                problems.append(f"stock of product {want['product_id']} is {units}, expected {want['units_in_stock']}")
    finally:
        con.close()
    return problems


# ---------- Starting our own host ----------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_host(db_path: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {**os.environ, "NORTHWIND_DB": str(db_path), "NORTHWIND_ALLOW_AUTO_APPROVAL": "1", "PYTHONIOENCODING": "utf-8"}
    log = open(db_path.parent / "host.log", "w", encoding="utf-8")  # noqa: SIM115 - closed with the process
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "northwind_host.app:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{url}/api/tools", timeout=2).status_code == 200:
                return process, url
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            break
        time.sleep(1)
    process.kill()
    raise SystemExit(f"The host did not start; see {db_path.parent / 'host.log'}")


# ---------- Running one question ----------


def ask(url: str, question: str, policy: str) -> dict:
    for attempt in (1, 2):
        response = httpx.post(f"{url}/api/ask", json={"question": question, "approval_policy": policy}, timeout=ASK_TIMEOUT)
        if response.status_code == 200:
            return response.json()
        if attempt == 1 and response.status_code in (429, 502, 503):
            print(f"    host said {response.status_code}; waiting 60 s and retrying once")
            time.sleep(60)
            continue
        raise RuntimeError(f"{response.status_code}: {response.text[:300]}")
    raise AssertionError("unreachable")


def grade(q: dict, body: dict, db_path: Path | None, before: tuple[int, int] | None) -> dict:
    called = [c["name"] for c in body["tool_calls"]]
    answer = body["answer"]
    answer_numbers = numbers_in(answer)
    missing = [f for f in q["must_contain"] if not fact_found(f, answer, answer_numbers)]
    tools_ok = any(t in called for t in q["expect_tools_any"])
    db_problems = check_db(db_path, q["db_check"], before) if db_path and before and "db_check" in q else []
    return {
        "passed": tools_ok and not missing and not db_problems,
        "tools_ok": tools_ok,
        "tools_called": called,
        "facts_found": len(q["must_contain"]) - len(missing),
        "facts_total": len(q["must_contain"]),
        "missing": missing,
        "db_problems": db_problems,
    }


# ---------- Main ----------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation questions through the web host.")
    parser.add_argument("--url", help="use an already-running host instead of starting one")
    parser.add_argument("--only", help="comma-separated question ids, e.g. 9,13")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.only:
        wanted = {int(x) for x in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    process, db_path = None, None
    if args.url:
        url, policy = args.url.rstrip("/"), "ask"
        skipped = [q for q in questions if q["kind"] == "write"]
        questions = [q for q in questions if q["kind"] != "write"]
        if skipped:
            print(f"--url mode: skipping question(s) {[q['id'] for q in skipped]} (they would write to a shared database)")
    else:
        if not PRISTINE_DB.exists():
            raise SystemExit("data/northwind-clean.db is missing: run `uv run python scripts/build_db.py` first")
        workdir = Path(tempfile.mkdtemp(prefix="northwind-eval-"))
        db_path = workdir / "northwind.db"
        shutil.copyfile(PRISTINE_DB, db_path)
        process, url = start_host(db_path)
        policy = "approve"
        print(f"Started a host at {url} on a fresh database copy ({db_path})")

    rows = []
    started = time.time()
    try:
        for q in questions:
            print(f"Q{q['id']:>2} {q['question']}")
            t0 = time.time()
            before = db_counts(db_path) if db_path else None
            try:
                body = ask(url, q["question"], policy)
                result = grade(q, body, db_path, before)
            except Exception as exc:  # report the failure and keep going
                body = {"answer": "", "model": "", "model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": []}
                result = {"passed": False, "tools_ok": False, "tools_called": [], "facts_found": 0,
                          "facts_total": len(q["must_contain"]), "missing": q["must_contain"], "db_problems": [str(exc)]}
            seconds = round(time.time() - t0, 1)
            rows.append({"id": q["id"], "kind": q["kind"], "question": q["question"], **result, "seconds": seconds,
                         "model": body["model"], "model_calls": body["model_calls"],
                         "tokens": body["prompt_tokens"] + body["completion_tokens"], "answer": body["answer"]})
            mark = "PASS" if result["passed"] else "FAIL"
            print(f"    {mark}  facts {result['facts_found']}/{result['facts_total']}  tools {result['tools_called']}"
                  f"  {body['model_calls']} model calls  {seconds}s")
            for problem in result["db_problems"]:
                print(f"    db: {problem}")
            if result["missing"]:
                print(f"    missing: {result['missing'][:8]}{' ...' if len(result['missing']) > 8 else ''}")
    finally:
        if process:
            process.terminate()
            process.wait(timeout=10)

    write_report(rows, time.time() - started, mode="own host" if process else f"url {url}")


def write_report(rows: list[dict], seconds: float, mode: str) -> None:
    RESULTS.mkdir(exist_ok=True)
    passed = sum(r["passed"] for r in rows)
    model = next((r["model"] for r in rows if r["model"]), "?")
    summary = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode,
        "model": model,
        "provider": "Groq",
        "passed": passed,
        "total": len(rows),
        "model_calls": sum(r["model_calls"] for r in rows),
        "tokens": sum(r["tokens"] for r in rows),
        "minutes": round(seconds / 60, 1),
        "questions": rows,
    }
    (RESULTS / "latest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        f"# Evaluation results ({summary['run_at']})",
        "",
        f"Model **{model}** on Groq, {mode}. **{passed}/{len(rows)} passed**, "
        f"{summary['model_calls']} model calls, {summary['tokens']:,} tokens, {summary['minutes']} minutes.",
        "",
        "| # | Kind | Result | Facts | Tools called | Model calls | Tokens | Seconds |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['kind']} | {'PASS' if r['passed'] else 'FAIL'} | {r['facts_found']}/{r['facts_total']} "
            f"| {', '.join(r['tools_called']) or '-'} | {r['model_calls']} | {r['tokens']:,} | {r['seconds']} |"
        )
    failures = [r for r in rows if not r["passed"]]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines.append(f"- **Q{r['id']}**: missing {r['missing'][:10]}; tools ok: {r['tools_ok']}; db: {r['db_problems'] or 'ok'}")
    (RESULTS / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[2:]))
    print(f"\nSaved eval/results/latest.json and eval/results/latest.md")


if __name__ == "__main__":
    main()
