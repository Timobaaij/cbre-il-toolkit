#!/usr/bin/env python3
"""conflict_note_catchall_test.py - a repair that SETS a field annotates EVERY stale conflict
note about that field, not just three known shapes. (2026-09-26 test run, fix 3.12)

WHY THIS EXISTS. `repairs.apply` annotated `meta.conflicts` notes for an allow-list of shapes
("ships tbd", "kept 'X')", "does NOT reconcile"). Any other note about the repaired field - merge's
"the source itemises office space ... NOT summed", a source-internal disagreement - survived the
repair unannotated, so the Gaps Report kept reasoning about a value the card no longer ships.
Fix 3.17 also changes the strike note to "ships <normalize.BLANK>", which the old literal
"ships tbd" match would have pushed into the catch-all instead of its own wording.

What this pins:
  * the four known shapes (ships tbd, ships TBC, kept 'X', does NOT reconcile) keep their
    [RESOLVED ...] wording, and the pre-change "ships tbd" annotation is byte-identical;
  * a "NOT summed" note and a source-internal note get
    [SUPERSEDED by repair rp-x: the card now ships '9,000 sq ft'];
  * an `id 1 officeAreaVal:` note is untouched when only officeArea was set (the colon);
  * an `id 10 ...` note is untouched for property 1;
  * a CLEAR annotates nothing;
  * a second apply never double-annotates.
Offline; synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import normalize as N                    # noqa: E402
import repairs as R                      # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


NOTES = [
    "id 1 warehouseArea: the parsed value '1' falls outside the warehouseArea plausibility band, "
    "so the card ships tbd rather than a figure that may be a parse or unit error.",
    f"id 1 clearHeight: the parsed value '400m' falls outside the clearHeight plausibility band, "
    f"so the card ships {N.BLANK} rather than a figure that may be a parse or unit error.",
    "id 1 status: discarded 'Let' from b.pdf (kept 'Available')",
    "id 1 officeArea: computed from itemised office lines, but does NOT reconcile: leaves 50 "
    "sq ft unexplained.",
    "id 1 officeArea: the source itemises office space on two floors; NOT summed.",
    "id 1 officeArea: the source disagrees with itself (page 2 vs page 5).",
    "id 1 officeAreaVal: derived from officeArea.",
    "id 10 officeArea: another property's note.",
]


def canon():
    return {"meta": {"conflicts": list(NOTES)}, "properties": [
        {"id": 1, "park": "Alpha Park", "city": "Northtown", "developer": "Devco",
         "country": "ZZ", "status": "Available", "clearHeight": None,
         "officeArea": "8,000 sq ft", "officeAreaVal": 8000.0, "tenure": "Leasehold"},
        {"id": 10, "park": "Zeta Park", "city": "Southtown", "developer": "Otherco",
         "country": "ZZ", "status": "Available", "officeArea": "1,000 sq ft"}]}


def entry(rid="rp-x", **kw):
    e = {"id": rid, "property": {"key": "northtown|devco|alpha park", "id": 1},
         "why": "the schedule states it", "verified_by": "analyst"}
    e.update(kw)
    return e


def main() -> int:
    saved = R.DERIVED_TWINS
    R.DERIVED_TWINS = {}              # isolate from the twin guard: this eval is about notes
    try:
        return _main()
    finally:
        R.DERIVED_TWINS = saved


def _main() -> int:
    print("== the known shapes keep their RESOLVED wording ==")
    c = canon()
    rep = R.apply(c, [entry(set={"warehouseArea": 12000, "clearHeight": "12 m",
                                 "status": "Under offer", "officeArea": "9,000 sq ft"})])
    ck(len(rep["applied"]) == 1,
       f"the entry applied ({ {k: len(v) for k, v in rep.items() if v} })")
    n = c["meta"]["conflicts"]
    ck(n[0] == NOTES[0] + " [RESOLVED by repair rp-x: the card now ships 12000, not tbd - see "
       "\"Manual corrections applied (property-level repairs)\" below.]",
       "'ships tbd' annotation is byte-identical to the pre-change wording")
    ck(n[1].startswith(NOTES[1] + " [RESOLVED by repair rp-x: the card now ships '12 m', not "
                       + N.BLANK),
       f"'ships {N.BLANK}' (fix 3.17 spelling) is still the KNOWN shape, not the catch-all")
    ck(n[2].endswith("[RESOLVED by repair rp-x: the card now ships 'Under offer', not "
                     "'Available' - see \"Manual corrections applied (property-level repairs)\" "
                     "below.]"), "\"kept 'X')\" keeps its wording")
    ck("does NOT reconcile" in n[3] and "[RESOLVED by repair rp-x: the card now ships "
       "'9,000 sq ft' - see" in n[3], "'does NOT reconcile' keeps its wording")

    print()
    print("== every other note about the field gets the catch-all ==")
    tail = " [SUPERSEDED by repair rp-x: the card now ships '9,000 sq ft']"
    ck(n[4] == NOTES[4] + tail, "the 'NOT summed' note is annotated")
    ck(n[5] == NOTES[5] + tail, "a source-internal note is annotated")
    ck(n[6] == NOTES[6], "an `officeAreaVal:` note is untouched by an officeArea repair")
    ck(n[7] == NOTES[7], "a note about ANOTHER property (id 10) is untouched")

    print()
    print("== idempotent: a second apply adds nothing ==")
    before = copy.deepcopy(n)
    R.apply(c, [entry(set={"warehouseArea": 12000, "clearHeight": "12 m",
                           "status": "Under offer", "officeArea": "9,000 sq ft"})])
    ck(c["meta"]["conflicts"] == before, "no second tail on any note")
    ck(all(x.count("[RESOLVED") + x.count("[SUPERSEDED by repair") <= 1
           for x in c["meta"]["conflicts"]), "at most one annotation per note")

    print()
    print("== a clear annotates nothing ==")
    c2 = canon()
    rep2 = R.apply(c2, [entry(unset=["officeArea", "officeAreaVal"])])
    ck(len(rep2["applied"]) == 1, "the clear applied")
    ck(c2["meta"]["conflicts"] == NOTES,
       "no note gains [RESOLVED or [SUPERSEDED by repair from a withdrawal")

    print()
    print("== a set to an unknown form annotates nothing ==")
    c3 = canon()
    R.apply(c3, [entry(set={"officeArea": N.BLANK})])
    ck(c3["meta"]["conflicts"] == NOTES, "nothing to correct the note WITH, so nothing is said")

    print()
    if FAILS:
        print(f"CONFLICT NOTE CATCH-ALL TEST: FAIL ({len(FAILS)})")
        return 1
    print("CONFLICT NOTE CATCH-ALL TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
