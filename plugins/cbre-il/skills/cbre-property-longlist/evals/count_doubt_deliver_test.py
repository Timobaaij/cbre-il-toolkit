#!/usr/bin/env python3
"""count_doubt_deliver_test.py - fix 3.18, deliver half (2026-09-26 test run).

A count-affecting / no-field reader doubt ("does this deck describe one property or two?") has no
repair that can carry its answer. Clarify now routes it (count_doubt_route_test.py pins that); the
Gaps Report's Clarifications line says what became of the answer:
  * an answer that keeps the cards as shipped -> " - this is how it already shipped; nothing
    changed" (also for an OLD title, via its "proceeds with:" default);
  * another option on a re-read-route question -> " - queued for a re-read with this decision";
  * once work/vision/reread.json records that re-read (same answer key) as done -> " - the deck
    was re-read with this decision"; a done entry for a DIFFERENT answer key stays "queued";
  * free text and non-doubt questions get no suffix; a malformed reread.json degrades to "queued".

Every name is invented. Offline. Run: python evals/count_doubt_deliver_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402
import deliver  # noqa: E402

FAILS: list = []
ONE = "one property (the whole building)"
TWO = "two properties (north and south halls)"
CANON = {"properties": [], "meta": {}}
SHIPPED = " - this is how it already shipped; nothing changed"
QUEUED = " - queued for a re-read with this decision"
DONE = " - the deck was re-read with this decision"


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _answer(w, mapping):
    (w / "answers.json").write_text(json.dumps(mapping), encoding="utf-8")
    CQ.ingest_answers(w)


def _line(w, qid_subject="Northgate 360"):
    md = deliver.gaps_report(CANON, "t", w)
    sec = md.split("## Clarifications", 1)[1].split("\n## ", 1)[0] if "## Clarifications" in md else ""
    return next((ln for ln in sec.splitlines() if ln.startswith(f"- **{qid_subject}**")), "")


def main() -> int:
    print("1. a routed count doubt")
    w = Path(tempfile.mkdtemp(prefix="cdd_"))
    rec = {"park": "Northgate 360", "unit": "", "city": "Southwold",
           "__meta": {"source_file": "northgate.pdf", "doubts": [{
               "subject": "Northgate 360", "question": "does this deck describe one property or two?",
               "options": [ONE, TWO], "default": ONE}]}}
    q = CQ.agent_doubt_questions([rec])[0]
    CQ.emit(w, CQ.pending(w, [q]))
    ck(q.get("answer_route") == "reread", "setup: the doubt is on the re-read route")
    _answer(w, {q["id"]: ONE})
    ln = _line(w)
    ck(f"answered **{ONE}**{SHIPPED}." in ln, f"as shipped -> '{SHIPPED.strip()}' ({ascii(ln[:140])})")
    _answer(w, {q["id"]: TWO})
    ln = _line(w)
    ck(QUEUED in ln and DONE not in ln, f"another option -> queued ({ascii(ln[:140])})")
    key = CQ.reread_requests(w)[0]["key"]
    (w / "vision").mkdir(exist_ok=True)
    rr = w / "vision" / "reread.json"
    rr.write_text(json.dumps({"schema_version": 1, "decks": {"northgate.pdf": {
        "qid": q["id"], "key": key, "source_file": "northgate.pdf", "answer": TWO, "done": True}}}),
        encoding="utf-8")
    ln = _line(w)
    ck(DONE in ln and QUEUED not in ln, f"reread.json done for this key -> re-read ({ascii(ln[:140])})")
    rr.write_text(json.dumps({"schema_version": 1, "decks": {"northgate.pdf": {
        "qid": q["id"], "key": "0000000000", "done": True}}}), encoding="utf-8")
    ck(QUEUED in _line(w), "a done entry for ANOTHER answer key stays queued")
    rr.write_text("{not json", encoding="utf-8")
    ck(QUEUED in _line(w), "a malformed reread.json degrades to queued, never crashes")
    _answer(w, {q["id"]: "it is two, I think"})
    ln = _line(w)
    ck(QUEUED not in ln and DONE not in ln and SHIPPED not in ln, "free text: no suffix")

    print("2. an OLD title closes as shipped")
    w2 = Path(tempfile.mkdtemp(prefix="cdd_old_"))
    qid = "q_0ldc0unt01"
    st = CQ.load_state(w2)
    st["asked"] = [qid]
    st["titles"] = {qid: {"kind": "agent_doubt", "subject": "Northgate 360",
                          "question": "does this deck describe one property or two?",
                          "blocking": False, "if_unanswered": "proceeds with: one property",
                          "answer_handling": CQ.ANSWER_RECORDED_NO_FIELD}}
    CQ.save_state(w2, st)
    _answer(w2, {qid: "one property"})
    ck(SHIPPED in _line(w2), "old title answered with its default -> as shipped")
    _answer(w2, {qid: "two properties"})
    ck(SHIPPED not in _line(w2) and QUEUED not in _line(w2), "old title, other answer: no suffix (never a re-read)")

    print("3. other questions are untouched")
    ck(deliver._answer_route_suffix("x", {"kind": "source_authority", "if_unanswered": "proceeds with: union"},
                                    "union", {}) == "", "a non-doubt question gets no suffix")
    ck(deliver._answer_route_suffix("x", {"kind": "agent_doubt", "answer_handling": CQ.ANSWER_APPLIED,
                                          "if_unanswered": "proceeds with: 10 m"}, "10 m", {}) == "",
       "a field-landing doubt gets no suffix (its answer is a repair)")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} count_doubt_deliver_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
