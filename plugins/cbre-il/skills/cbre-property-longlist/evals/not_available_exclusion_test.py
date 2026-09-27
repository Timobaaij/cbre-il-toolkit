#!/usr/bin/env python3
"""not_available_exclusion_test.py - a source-marked let / sold record becomes a broker question. (3.10b)

THE MEASURED FAILURE (2026-09-26 test run). A unit the source marked LET shipped as an
availability card; no mechanism existed to drop it, and nothing asked.

THE RULE PINNED HERE (clarify side). The reader flags such a record `__meta.not_an_option: true`
(status copied verbatim) and it counts only when the flag `is True`; the legacy
`__meta.not_available` spellings (True, a marker string, a {marker|text} dict) are tolerated.
Each flagged record identity (source file, park, unit - never a value) gets ONE non-blocking,
count-material broker question with the fixed options NA_KEEP / NA_EXCLUDE, whose text shows the
record's own status. `not_available_decision` says "exclude" ONLY for an explicit exclude answer
on a flagged record; junk, a decline, no answer or an unflagged record keep the card. The merge
filter (`merge.apply_not_available`), input accounting and deliver's heading are IA-6 / IA-4's.

Every name is invented. Offline. Run: python evals/not_available_exclusion_test.py"""
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


def _rec(unit="Unit 3", status="Let", src="larkfield.pdf", park="Larkfield Park", **meta):
    m = {"source_file": src}
    m.update(meta)
    r = {"park": park, "unit": unit, "city": "Westbury", "warehouseArea": 250000,
         "__meta": m}
    if status is not None:
        r["status"] = status
    return r


def markers() -> None:
    print("1. which records are flagged, and the text shown")
    ck(CQ.not_available_marker(_rec(not_an_option=True)) == "Let", "not_an_option true -> status verbatim")
    ck(CQ.not_available_marker(_rec(status=None, not_an_option=True)) == "not available",
       "no status -> 'not available'")
    ck(CQ.not_available_marker(_rec(status="tbd", not_an_option=True)) == "not available",
       "a blank-sentinel status -> 'not available'")
    ck(CQ.not_available_marker(_rec(not_an_option="true")) == "", "a string 'true' is NOT the flag (is True only)")
    ck(CQ.not_available_marker(_rec(not_an_option=False, not_available=True)) == "",
       "the new key, when present, decides alone")
    ck(CQ.not_available_marker(_rec(status="Sold STC", not_available=True)) == "Sold STC", "legacy True")
    ck(CQ.not_available_marker(_rec(status=None, not_available="let to a parcel carrier"))
       == "let to a parcel carrier", "legacy marker string, no status")
    ck(CQ.not_available_marker(_rec(status=None, not_available={"marker": "vendu", "page": 4})) == "vendu",
       "legacy {marker} dict (any language)")
    ck(CQ.not_available_marker(_rec(not_available="false")) == "", "legacy 'false' is not a flag")
    ck(CQ.not_available_marker(_rec()) == "" and CQ.not_available_marker(None) == "",
       "unflagged / non-record -> ''")


def questions() -> None:
    print("2. one count-material question per flagged identity")
    recs = [_rec(not_an_option=True), _rec(unit="Unit 4", status="Available")]
    qs = CQ.not_available_questions(recs)
    ck(len(qs) == 1, f"only the flagged record is asked about ({len(qs)})")
    q = qs[0] if qs else {}
    ck(q.get("kind") == "not_available" and q.get("asked_of") == "broker", "kind / asked_of")
    ck(q.get("options") == [CQ.NA_KEEP, CQ.NA_EXCLUDE], "fixed options")
    ck(q.get("blocking") is False and CQ.materiality(q) == "count" and not CQ.is_blocking(q),
       "non-blocking, count-material")
    ck(q.get("question") == ("Larkfield Park, Unit 3: the source (larkfield.pdf) marks this building "
                             "as 'Let' - it is not currently available. Keep it on the longlist?"),
       f"question text ({q.get('question')!r})")
    ck(q.get("if_unanswered") == "the card ships showing the source's own status ('Let')", "if_unanswered")
    ck(q.get("anchors") == [{"park": "Larkfield Park", "unit": "Unit 3"}] and q.get("source_file") == "larkfield.pdf",
       "anchors and source_file")
    ck("—" not in q.get("question", "") and "–" not in q.get("question", ""), "no em/en dash")
    ck(CQ.not_available_qid(_rec(not_an_option=True)) == CQ.not_available_qid(_rec(status="Sold", not_an_option=True)),
       "the id is identity-keyed: a changed status keeps the id")
    ck(CQ.not_available_qid(_rec()) != CQ.not_available_qid(_rec(unit="Unit 4")), "another unit, another id")
    two = [_rec(unit="", park="", src="deck.pdf", not_an_option=True),
           _rec(unit="", park="", src="deck.pdf", status="Sold", not_an_option=True)]
    ck(len(CQ.not_available_questions(two)) == 1, "two unnamed let buildings of one deck coalesce")
    ck(CQ.not_available_questions([_rec()]) == [], "no flag, no question")


def decisions() -> None:
    print("3. not_available_decision")
    r = _rec(not_an_option=True)
    i = CQ.not_available_qid(r)
    ck(CQ.not_available_decision({i: CQ.NA_EXCLUDE}, set(), r) == "exclude", "NA_EXCLUDE -> exclude")
    ck(CQ.not_available_decision({i: "Exclude it, it's let"}, set(), r) == "exclude", "'exclude ...' -> exclude")
    ck(CQ.not_available_decision({i: CQ.NA_KEEP}, set(), r) == "keep", "NA_KEEP -> keep")
    ck(CQ.not_available_decision({i: "maybe drop it"}, set(), r) == "keep", "junk -> keep")
    ck(CQ.not_available_decision({i: CQ.NA_EXCLUDE}, {i}, r) == "keep", "declined -> keep")
    ck(CQ.not_available_decision({}, set(), r) == "keep", "no answer -> keep")
    u = _rec()
    ck(CQ.not_available_decision({CQ.not_available_qid(u): CQ.NA_EXCLUDE}, set(), u) == "keep",
       "an unflagged record is never excluded, whatever the answer")
    ck(CQ.not_available_decision(None, None, None) == "keep", "bad input -> keep")


def emit_roundtrip() -> None:
    print("4. asked once, answered, recorded")
    w = Path(tempfile.mkdtemp(prefix="na_emit_"))
    r = _rec(not_an_option=True)
    qs = CQ.not_available_questions([r])
    pend = CQ.pending(w, qs)
    ck(len(pend) == 1, "pending asks it")
    CQ.emit(w, pend)
    ck(CQ.pending(w, qs) == [], "non-blocking: never re-asked once asked")
    ck(qs[0]["id"] not in CQ.landable(w), "no landable stamp (no field)")
    (w / "answers.json").write_text(json.dumps({qs[0]["id"]: CQ.NA_EXCLUDE}), encoding="utf-8")
    ans = CQ.ingest_answers(w)
    ck(CQ.not_available_decision(ans, CQ.declined_ids(w), r) == "exclude", "the recorded answer decides")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    markers()
    questions()
    decisions()
    emit_roundtrip()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"NOT AVAILABLE EXCLUSION TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("NOT AVAILABLE EXCLUSION TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
