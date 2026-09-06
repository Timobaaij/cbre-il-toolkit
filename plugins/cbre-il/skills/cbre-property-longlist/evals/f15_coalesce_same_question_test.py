#!/usr/bin/env python3
"""f15_coalesce_same_question_test.py - the same question is asked ONCE and lands on EVERY record. (F15)

THE MEASURED FAILURE. Two records from the SAME deck on the SAME park each asked which region
the park sits in, with near-identical wording and identical rationale. A deck marketing six
units would have asked six times, and each answer could reach at most one card.

THE RULE PINNED HERE. Two reader doubts are the same question when ONE answer is correct for
all the records they cover. Concretely: same source file, same declared field, same normalised
subject, same option set, same reader default, same park, AND the field is one a deck states
once for the whole park (`clarify.PARK_LEVEL_FIELDS`). Those collapse to ONE question whose
`anchors` lists every record it stands for, so the lander can apply the one answer to each and
the Gaps Report can name them. Everything that could resolve differently stays apart: another
option set, another default, another deck, another park, or a PER-UNIT field (two units can be
torn between the same two printed figures and resolve differently), which is now asked once per
record even when the wording is identical - the pre-change dedupe would have collapsed those
and, with fan-out, applied one unit's answer to another.

Doubts are shaped the way a real reader writes them. Every name is invented. Offline.
Run: python evals/f15_coalesce_same_question_test.py"""
from __future__ import annotations

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


def _rec(park, unit, src, doubt, **fields):
    r = {"park": park, "unit": unit, "city": "Northport", "developer": "Kestrel Estates",
         "__meta": {"source_file": src, "doubts": [doubt]}}
    r.update(fields)
    return r


def _region_doubt(i, **over):
    d = {"subject": "property region",
         # near-identical, NOT identical, wording: the measured shape
         "question": f"which region does the park sit in? page {i} names none explicitly",
         "field": "region", "options": ["North", "South"], "default": "North",
         "why_it_matters": "the region label filters the grid"}
    d.update(over)
    return d


def _six(src="deck.pdf", park="Kestrel Reach", **over):
    return [_rec(park, f"Unit {i}", src, _region_doubt(i, **over), region="North")
            for i in range(1, 7)]


def _wd(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def one_question_many_records() -> None:
    print("1. six units, one deck, one park, one park-level field -> ONE question")
    recs = _six()
    qs = CQ.agent_doubt_questions(recs)
    ck(len(qs) == 1, f"six near-identical region doubts become ONE question ({len(qs)})")
    q = qs[0] if qs else {}
    ck(q.get("field") == "region" and q.get("options") == ["North", "South"],
       "...carrying the shared field and options")
    ck(q.get("subject") == "property region", "...and the reader's topic, unchanged")
    anchors = q.get("anchors") or []
    ck(anchors == [{"park": "Kestrel Reach", "unit": f"Unit {i}"} for i in range(1, 7)],
       f"`anchors` lists EVERY record it covers, in record order ({len(anchors)})")
    ck(q.get("anchor_park") == "Kestrel Reach" and q.get("anchor_unit") == "Unit 1",
       "the scalar pair is the FIRST anchor, so a scalar-only reader degrades to one record")
    ck("one answer covers 6 records from this file" in q.get("question", "")
       and "Kestrel Reach, Unit 6" in q.get("question", ""),
       f"the broker-facing text says how many records one answer moves, and names them "
       f"({q.get('question')!r})")
    ck(q.get("answer_handling") == CQ.ANSWER_APPLIED,
       "...and that the answer will be applied (field and options both present)")
    rev = CQ.agent_doubt_questions(list(reversed(recs)))
    ck(len(rev) == 1 and rev[0]["id"] == q.get("id"),
       "the id is keyed on the AMBIGUITY, so record order does not change it")
    ck(rev[0].get("anchor_unit") == "Unit 6",
       "...while the scalar anchor follows record order (it is only the first entry)")

    print("\n2. the stamp and the disclosure both carry every anchor")
    w = _wd("cbre_f15_stamp_")
    CQ.emit(w, CQ.pending(w, qs))
    st = CQ.load_state(w)
    stamp = (st.get("landable") or {}).get(q.get("id")) or {}
    ck(len(stamp.get("anchors") or []) == 6
       and stamp.get("anchor_park") == "Kestrel Reach" and stamp.get("anchor_unit") == "Unit 1",
       f"the landable stamp has all six anchors plus the scalar pair "
       f"({len(stamp.get('anchors') or [])})")
    aff = ((st.get("titles") or {}).get(q.get("id")) or {}).get("affected") or []
    ck(aff == [f"Kestrel Reach, Unit {i}" for i in range(1, 7)],
       f"the durable title lists the affected records for the Gaps Report ({len(aff)})")

    print("\n3. a coalesced question costs the cap ONE slot")
    per_unit = [_rec("Kestrel Reach", f"Unit {i}", "deck.pdf",
                     {"subject": "warehouse area", "field": "warehouseArea",
                      "question": "two figures are printed; which is the hall?",
                      "options": [str(1000 * i), str(10000 * i)]}, warehouseArea=10000 * i)
                for i in range(1, 12)]
    out = CQ.agent_doubt_questions(_six() + per_unit)
    ck(len(out) == 12, f"6 coalesced + 11 distinct = 12 questions ({len(out)})")
    ck(not any(x.get("over_cap") for x in out),
       f"...all within MAX_DOUBT_QUESTIONS={CQ.MAX_DOUBT_QUESTIONS}: the six did not spend six slots")


def what_stays_apart() -> None:
    print("\n4. anything that could resolve DIFFERENTLY stays a separate question")
    a = _rec("Kestrel Reach", "Unit 1", "deck.pdf", _region_doubt(1))
    ck(len(CQ.agent_doubt_questions([a, _rec("Kestrel Reach", "Unit 2", "deck.pdf",
                                             _region_doubt(2, options=["North", "East"]))])) == 2,
       "a different option set")
    ck(len(CQ.agent_doubt_questions([a, _rec("Kestrel Reach", "Unit 2", "deck.pdf",
                                             _region_doubt(2, default="South"))])) == 2,
       "a different reader default (positive evidence the two lean different ways)")
    ck(len(CQ.agent_doubt_questions([a, _rec("Kestrel Reach", "Unit 2", "other.pdf",
                                             _region_doubt(2))])) == 2,
       "a different source file")
    ck(len(CQ.agent_doubt_questions([a, _rec("Harrier Point", "Unit 2", "deck.pdf",
                                             _region_doubt(2))])) == 2,
       "a different park on the same deck (a portfolio deck can span regions)")
    ck(len(CQ.agent_doubt_questions([a, _rec("Kestrel Reach", "Unit 2", "deck.pdf",
                                             _region_doubt(2, subject="region label"))])) == 2,
       "a different subject")
    nopark = [_rec("", "", "deck.pdf", _region_doubt(i)) for i in (1, 2)]
    ck(len(CQ.agent_doubt_questions(nopark)) == 2,
       "records naming NO park cannot be shown to share one, so they are not coalesced")
    ck("region" in CQ.PARK_LEVEL_FIELDS and "officeArea" not in CQ.PARK_LEVEL_FIELDS
       and "warehouseArea" not in CQ.PARK_LEVEL_FIELDS and "unit" not in CQ.PARK_LEVEL_FIELDS,
       "the whitelist holds park-wide fields and none of the per-unit ones")

    print("\n5. a PER-UNIT field is asked once per record, even with identical wording")
    same = {"question": "the page prints 450 and 4,500 for the office; which is this unit's?",
            "field": "officeArea", "options": ["450", "4500"]}
    # no `subject`, so it defaults to the park name and the two are word-for-word identical:
    # the pre-change dedupe collapsed these into one question anchored to the park
    two = [_rec("Kestrel Reach", "Unit 1", "deck.pdf", dict(same), officeArea=4500),
           _rec("Kestrel Reach", "Unit 2", "deck.pdf", dict(same), officeArea=450)]
    qs = CQ.agent_doubt_questions(two)
    ck(len(qs) == 2, f"two units, one per-unit field, identical words -> TWO questions ({len(qs)})")
    ck([x.get("anchor_unit") for x in qs] == ["Unit 1", "Unit 2"]
       and all(len(x.get("anchors") or []) == 1 for x in qs),
       "...each anchored to its own record only, so one answer is never fanned out across units")
    ck(all(f"[record: Kestrel Reach, Unit {i}]" in qs[i - 1].get("question", "") for i in (1, 2)),
       "...and the broker can tell them apart, because each names its record")
    ck(len({x["id"] for x in qs}) == 2, "...under two ids")


def disclosure_only_doubts() -> None:
    print("\n6. a doubt naming no field keeps the wording key, and its anchors are still kept")
    tint = {"question": "the cover tint looks unusual", "default": "the file as read"}
    recs = [_rec("Kestrel Reach", f"Unit {i}", "deck.pdf", dict(tint, subject="Kestrel Reach"))
            for i in (1, 2)]
    qs = CQ.agent_doubt_questions(recs)
    ck(len(qs) == 1 and len(qs[0].get("anchors") or []) == 2,
       "identical wording on two records is one disclosure line covering both")
    ck(qs[0].get("answer_handling") == CQ.ANSWER_RECORDED_NO_FIELD,
       "...marked recorded-only (no field to write)")
    w = _wd("cbre_f15_sup_")
    CQ.pending(w, qs)        # ledger -> suppressed, not asked
    sup = CQ.load_state(w).get("suppressed") or {}
    ck(len(sup) == 1 and list(sup.values())[0].get("affected") == ["Kestrel Reach, Unit 1",
                                                                     "Kestrel Reach, Unit 2"],
       f"the suppressed record names the records it covered ({list(sup.values())})")
    ck(CQ.landable(w) == {}, "...and nothing is stamped landable")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    one_question_many_records()
    what_stays_apart()
    disclosure_only_doubts()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F15 COALESCE SAME QUESTION TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F15 COALESCE SAME QUESTION TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
