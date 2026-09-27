#!/usr/bin/env python3
"""combine_policy_deliver_test.py - fix 3.2c, merge + deliver halves (2026-09-26 test run).

The clarify half (one policy question per field, fanned out per card) is pinned by
combine_policy_question_test.py. This pins what IA-6 owns:
  * merge `_area_candidate`: a STOREY word in an office key ("threeStoreyOffices") no longer
    hides a printed AREA - "20,000 sq ft (1,858 sq m)" joins the office sum (the real run summed
    two of three lines, 5,000 instead of 25,000); `officeStoreys: 3`, "2 floors" and every other
    non-area token (height, rent, parking) are still refused;
  * deliver Clarifications: a POLICY answer prints ONE line per member card, naming the card,
    the field, the policy question and what the card shows (combine / first line / unstated);
    "ask me per card", a decline and a directly-answered member print no fan-out line;
  * deliver "Settled without asking": a merge-settled doubt gets its own heading and line, and
    no longer appears under "Noticed but not asked about";
  * deliver._WHY_MERGED == clarify.WHY_MERGED.

Every name is invented. Offline. Run: python evals/combine_policy_deliver_test.py"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402
import deliver  # noqa: E402
import merge  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _card(park, parts, extra=None):
    d = {"subject": "office area", "question": "office lines, no total; which is it?",
         "field": "officeArea", "options": list(parts), "default": parts[0], "combinable": True}
    r = {"park": park, "unit": "Unit 1", "city": "Eastmere", "areaUnit": "sq ft",
         "warehouseArea": 150000,
         "__meta": {"source_file": park.lower().replace(" ", "_") + ".pdf", "doubts": [d]}}
    r.update(extra or {})
    return r


A = _card("Alder Point", ["3,080 sq ft (GF)", "6,155 sq ft (FF)", "1,620 sq ft (SF)"])
B = _card("Birch Row", ["2,000 sq ft (GF)", "2,500 sq ft (FF)"])
C_ = _card("Cedar Gate", ["1,100 sq ft (hub 1)", "900 sq ft (hub 2)"])
S = _card("Sorrel Yard", ["4,000 sq ft (GF)", "1,000 sq ft (FF)"],
          extra={"officeGroundFloor": "4,000 sq ft", "officeFirstFloor": "1,000 sq ft"})
CANON = {"properties": [], "meta": {}}


def _answer(w, mapping):
    (w / "answers.json").write_text(json.dumps(mapping), encoding="utf-8")
    CQ.ingest_answers(w)


def _policy_dir():
    w = Path(tempfile.mkdtemp(prefix="cpd_"))
    out, _ = CQ.group_combinable(w, CQ.agent_doubt_questions([A, B, C_]))
    out = CQ.apply_doubt_cap(out)
    CQ.emit(w, CQ.pending(w, out))
    return w, out[0]


def _section(md, heading):
    if heading not in md:
        return ""
    return md.split(heading, 1)[1].split("\n## ", 1)[0]


def merge_storey() -> None:
    print("1. merge: a storey word no longer hides a printed office area")
    ck(merge._area_candidate("threeStoreyOffices", "20,000 sq ft (1,858 sq m)", "sq ft")
       == (20000.0, "sq ft", ["three", "storey", "offices"]),
       "threeStoreyOffices '20,000 sq ft (1,858 sq m)' is an area candidate")
    for k, v in (("officeStoreys", 3), ("officeFloors", "2 floors"), ("officeStoreys", "3"),
                 ("officeHeight", "12 m"), ("officeRent", "12.50 sq ft"),
                 ("officeParkingSpaces", "40"), ("officeStoreyHeight", "4,000 sq ft")):
        ck(merge._area_candidate(k, v, "sq ft") is None, f"{k}={v!r} is still refused")
    rec = {"park": "Pine Hub", "warehouseArea": 100000, "areaUnit": "sq ft",
           "hubOffice1": "2,500 sq ft", "hubOffice2": "2,500 sq ft",
           "threeStoreyOffices": "20,000 sq ft (1,858 sq m)", "officeStoreys": 3,
           "__meta": {"source_file": "pine.pdf", "source_type": "pdf", "locator_base": "page 2"}}
    m = copy.deepcopy(rec)
    m.pop("__meta")
    e = merge.derive_office_sum([rec], m, {})
    ck(e and e.get("status") == "computed" and e.get("value") == 25000
       and m.get("officeArea") == "25,000 sq ft",
       f"the office sum takes all three lines: 25,000 sq ft ({e and e.get('value')}, {m.get('officeArea')!r})")
    ck(e and "officeStoreys" not in {c["key"] for c in e.get("components") or []},
       "officeStoreys (a count) does not join the sum")


def deliver_fanout() -> None:
    print("2. deliver: one Clarifications line per card a policy answer covered")
    ck(deliver._WHY_MERGED == CQ.WHY_MERGED, "deliver._WHY_MERGED == clarify.WHY_MERGED")
    w, P = _policy_dir()
    _answer(w, {P["id"]: CQ.POLICY_COMBINE})
    md = deliver.gaps_report(CANON, "t", w)
    sec = _section(md, "## Clarifications")
    fan = [ln for ln in sec.splitlines() if "by your answer to" in ln]
    ck(len(fan) == 3, f"combine: three fan-out lines, one per card ({len(fan)})")
    ck(any("Alder Point" in ln and "(officeArea)" in ln and "10,855 sq ft" in ln
           and "3,080 sq ft (GF) + 6,155 sq ft (FF) + 1,620 sq ft (SF)" in ln for ln in fan),
       "the line names the card, the field, the sum and its parts")
    ck(all(CQ.POLICY_COMBINE in ln for ln in fan), "each line quotes the policy answer")
    _answer(w, {P["id"]: CQ.POLICY_FIRST})
    fan = [ln for ln in _section(deliver.gaps_report(CANON, "t", w), "## Clarifications").splitlines()
           if "by your answer to" in ln]
    ck(len(fan) == 3 and any("Birch Row" in ln and "the first printed line, 2,000 sq ft (GF)" in ln
                             for ln in fan), "first: 'the first printed line, <first>'")
    _answer(w, {P["id"]: CQ.POLICY_UNSTATED})
    fan = [ln for ln in _section(deliver.gaps_report(CANON, "t", w), "## Clarifications").splitlines()
           if "by your answer to" in ln]
    ck(len(fan) == 3 and all("left unstated" in ln for ln in fan), "unstated: 'left unstated'")
    _answer(w, {P["id"]: CQ.POLICY_PER_CARD})
    ck("by your answer to" not in deliver.gaps_report(CANON, "t", w), "ask me per card: no fan-out lines")
    _answer(w, {P["id"]: "skip"})
    ck("by your answer to" not in deliver.gaps_report(CANON, "t", w), "declined: no fan-out lines")
    # a directly answered member keeps its own answer line and gets no fan-out line
    w2, P2 = _policy_dir()
    mid = P2["members"][1]["id"]
    _answer(w2, {P2["id"]: CQ.POLICY_COMBINE, mid: "2,000 sq ft (GF)"})
    fan = [ln for ln in _section(deliver.gaps_report(CANON, "t", w2), "## Clarifications").splitlines()
           if "by your answer to" in ln]
    ck(len(fan) == 2 and not any("Birch Row" in ln for ln in fan),
       f"a direct per-card answer wins: two fan-out lines, none for that card ({len(fan)})")


def deliver_settled() -> None:
    print("3. deliver: 'Settled without asking'")
    w = Path(tempfile.mkdtemp(prefix="cpd_set_"))
    out, settled = CQ.group_combinable(w, CQ.agent_doubt_questions([S]))
    CQ.note_suppressed(w, settled, why=CQ.WHY_MERGED)
    md = deliver.gaps_report(CANON, "t", w)
    sec = _section(md, "## Settled without asking (the pipeline's own sum is the combined figure)")
    ck(bool(sec), "the heading appears")
    ck("Sorrel Yard Unit 1" in sec and "printed as 2 lines" in sec and "5,000 sq ft" in sec
       and "work/repairs.json" in sec, f"one line: card, line count, the sum, how to change it ({ascii(sec[:200])})")
    ck("Sorrel Yard" not in _section(md, "## Noticed but not asked about"), "not also under 'Noticed but not asked about'")
    ck("Sorrel Yard" not in _section(md, "## Noted, not put to you"), "not under the ledger heading either")


def main() -> int:
    merge_storey()
    deliver_fanout()
    deliver_settled()
    print(f"\n{'PASS' if not FAILS else 'FAIL'} combine_policy_deliver_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
