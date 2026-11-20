"""The eval's answer checker: formatting differences must not cause false failures,
and wrong numbers must not slip through."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def found(fact, answer):
    return run_eval.fact_found(fact, answer, run_eval.numbers_in(answer))


@pytest.mark.parametrize(
    ("fact", "answer"),
    [
        ("Save-a-lot Markets", "3. Save‑a‑lot Markets"),  # non-breaking hyphens from the model
        ("Thüringer Rostbratwurst", "Thuringer Rostbratwurst"),  # accents
        ("Chef Anton's Gumbo Mix", "Chef Anton’s Gumbo Mix"),  # curly apostrophe
        ("QUICK-Stop", "**quick-stop**"),  # case and Markdown bold
        ("Wolski  Zajazd", "Wolski Zajazd"),  # double space in the data
        (110277.30, "QUICK-Stop: $110,277.30"),
        (110277.30, "110277.3"),
        (1265793.04, "total 1,265,793.04"),
        (11077, "orders 11076, 11077"),
    ],
)
def test_formatting_differences_still_match(fact, answer):
    assert found(fact, answer)


@pytest.mark.parametrize(
    ("fact", "answer"),
    [
        (110277.30, "110,277.40"),  # a different number
        (110277.30, "110,277"),  # rounded away
        ("Ernst Handel", "Ernst"),
        (11078, "11077 and 11079"),
    ],
)
def test_wrong_answers_do_not_match(fact, answer):
    assert not found(fact, answer)


def test_question_file_matches_the_documented_questions():
    questions = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))["questions"]
    assert [q["id"] for q in questions] == list(range(1, 15))
    assert all(q["must_contain"] and q["expect_tools_any"] for q in questions)
    kinds = {q["kind"] for q in questions}
    assert {"lookup", "linked", "paging", "totals", "missing", "write", "refusal"} == kinds
