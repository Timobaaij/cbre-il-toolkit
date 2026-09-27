#!/usr/bin/env python3
"""arithmetic_basis_question_test.py - a printed total read as the warehouse area is ASKED. (3.7b)

THE MEASURED FAILURE (2026-09-26 test run). Two decks printed one whole-building total and no
warehouse-only line; the total was read as `warehouseArea`, the office was stated beside it, and
the dashboard's total area over-counted by the office. The arithmetic gate blocked with a prose
remedy, the decision was taken in chat, and two hand repairs recorded it with no question id.

THE RULE PINNED HERE (clarify side). The gate's `warehouse_is_total` findings become BLOCKING
broker questions (kind `arithmetic_basis`, in BLOCKING_KINDS, display-material) with the fixed
options AB_KEEP / AB_DERIVE; the figures live in the text, so the id - keyed on the record's
identity (source file, park, unit), never its property id or a figure - survives a changed figure.
Only a total larger than the stated office is asked; every other shape, or a finding missing a
figure, produces nothing. `arithmetic_basis_mode` reads an answer (junk and hedges are '',
re-asked, never guessed). Unknown finding keys are ignored - here and in value_format_questions
(the gate may add `own_unit` / `exempt`, fix 3.3). The gate's `--emit-json` / waivers and run.py's
`arithmetic_basis_clarify` bridge are IA-4 / IA-7b's.

Every name is invented. Offline. Run: python evals/arithmetic_basis_question_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _f(**over):
    f = {"id": 14, "park": "Quarry Fields", "unit": "Building 2", "warehouseArea": 214000,
         "officeAreaVal": 12500, "stated_total": 214000, "area_unit": "sq ft",
         "source_file": "quarry_fields.pdf", "locator": "p.3 schedule", "over_by": 12500,
         "shape": "warehouse_is_total", "some_future_key": {"x": 1}}
    f.update(over)
    return f


def question_shape() -> None:
    print("1. a warehouse_is_total finding -> one BLOCKING question")
    ck("arithmetic_basis" in CQ.BLOCKING_KINDS and CQ.KINDS.get("arithmetic_basis") == "broker"
       and CQ.KIND_MATERIALITY.get("arithmetic_basis") == "display", "kind registered, blocking, display")
    qs = CQ.arithmetic_basis_questions([_f()])
    ck(len(qs) == 1, f"one question ({len(qs)})")
    q = qs[0] if qs else {}
    ck(q.get("kind") == "arithmetic_basis" and q.get("blocking") is True and CQ.is_blocking(q),
       "blocking")
    ck(q.get("options") == [CQ.AB_KEEP, CQ.AB_DERIVE], "fixed options")
    ck(q.get("question") == (
        "Quarry Fields, Building 2: the source prints one total of 214,000 sq ft "
        "(quarry_fields.pdf p.3 schedule) and no warehouse-only figure, and that total was read "
        "as the warehouse area. With the stated office area of 12,500 sq ft the dashboard's total "
        "area would read 226,500 sq ft, 12,500 more than the source states. What should "
        "warehouse area be?"), f"question text ({q.get('question')!r})")
    ck(q.get("if_unanswered") == CQ.AB_IF_UNANSWERED, "if_unanswered")
    ck(q.get("property_id") == 14 and q.get("stated_total") == 214000 and q.get("officeAreaVal") == 12500
       and q.get("anchors") == [{"park": "Quarry Fields", "unit": "Building 2"}],
       "the figures and the record identity travel on the question")
    ck("field" not in q, "no `field`, so emit stamps no reader-doubt landing for it")
    ck("some_future_key" not in q, "an unknown finding key is ignored")


def ids() -> None:
    print("2. identity-keyed ids")
    a = CQ.arithmetic_basis_questions([_f()])[0]["id"]
    b = CQ.arithmetic_basis_questions([_f(id=99, stated_total=215000, warehouseArea=215000,
                                          officeAreaVal=13000)])[0]["id"]
    ck(a == b, "a renumbered id and changed figures keep the question id (and its answer)")
    c = CQ.arithmetic_basis_questions([_f(unit="Building 3")])[0]["id"]
    ck(a != c, "another building, another id")
    ck(a == CQ.arithmetic_basis_qid(_f()), "arithmetic_basis_qid is the producer's id")
    dup = CQ.arithmetic_basis_questions([_f(), _f(id=15)])
    ck(len(dup) == 1, "two findings for one identity -> one question")


def refusals() -> None:
    print("3. only the pure basis shape is asked")
    ck(CQ.arithmetic_basis_questions([_f(shape="other")]) == [], "shape 'other' -> nothing (exit 6 stands)")
    ck(CQ.arithmetic_basis_questions([_f(shape=None)]) == [], "no shape -> nothing")
    ck(CQ.arithmetic_basis_questions([_f(officeAreaVal=0)]) == [], "no office -> nothing")
    ck(CQ.arithmetic_basis_questions([_f(officeAreaVal=214000)]) == [], "total not above the office -> nothing")
    ck(CQ.arithmetic_basis_questions([_f(stated_total="n/a")]) == [], "a missing figure -> nothing")
    ck(CQ.arithmetic_basis_questions(None) == [] and CQ.arithmetic_basis_questions(["x", 3]) == [],
       "bad input -> nothing, never a crash")


def modes() -> None:
    print("4. arithmetic_basis_mode")
    cases = {CQ.AB_DERIVE: "derive", CQ.AB_KEEP: "keep", "Printed total minus office": "derive",
             "as is": "keep", "leave as is": "keep", "skip": "decline", "you decide": "decline",
             "not minus the office": "", "whatever": "", "": "", None: ""}
    for raw, want in cases.items():
        got = CQ.arithmetic_basis_mode(raw)
        ck(got == want, f"arithmetic_basis_mode({raw!r}) == {want!r} ({got!r})")


def blocking_roundtrip() -> None:
    print("5. blocking: re-offered until answered or declined")
    w = Path(tempfile.mkdtemp(prefix="ab_block_"))
    qs = CQ.arithmetic_basis_questions([_f()])
    CQ.emit(w, CQ.pending(w, qs))
    ck(len(CQ.pending(w, qs)) == 1, "asked and unanswered: still pending (blocking)")
    (w / "answers.json").write_text(json.dumps({qs[0]["id"]: CQ.AB_DERIVE}), encoding="utf-8")
    ans = CQ.ingest_answers(w)
    ck(CQ.pending(w, qs) == [] and CQ.arithmetic_basis_mode(ans.get(qs[0]["id"])) == "derive",
       "answered: no longer pending, and the answer reads 'derive'")
    w2 = Path(tempfile.mkdtemp(prefix="ab_decl_"))
    CQ.emit(w2, CQ.pending(w2, qs))
    (w2 / "answers.json").write_text(json.dumps({qs[0]["id"]: "skip"}), encoding="utf-8")
    CQ.ingest_answers(w2)
    ck(CQ.pending(w2, qs) == [] and qs[0]["id"] in CQ.declined_ids(w2), "declined: resolved as a decision")


def value_format_tolerance() -> None:
    print("6. value_format_questions ignores unknown finding keys (3.3)")
    f = {"field": "clearHeight", "dominant_printed": "m", "measured_count": 3, "examples": ["12 m"],
         "own_unit": None, "twin_ok": 2,
         "bare": [{"id": 5, "value": "12", "own_unit": None, "future": True}]}
    qs = CQ.value_format_questions([f])
    ck(len(qs) == 1 and qs[0]["options"] == ["m", "leave as is"] and qs[0]["blocking"] is True,
       "one blocking question, unchanged shape, extra keys ignored")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    question_shape()
    ids()
    refusals()
    modes()
    blocking_roundtrip()
    value_format_tolerance()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"ARITHMETIC BASIS QUESTION TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ARITHMETIC BASIS QUESTION TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
