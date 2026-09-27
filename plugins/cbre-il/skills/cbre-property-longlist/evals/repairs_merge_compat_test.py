#!/usr/bin/env python3
"""repairs_merge_compat_test.py - hand repairs written BEFORE two merge-side fixes still apply
after a re-merge that now does the same thing at source. (2026-09-26 test run, fixes 3.5a and
3.3c, repairs.py compat half)

WHY THIS EXISTS. Two merge changes of this round do at SOURCE what the broker did by hand on the
real run:
  * 3.5a strict alias promotion: merge moves an exact synonym key (`levelAccessDoors`) into a
    blank canonical field (`overheadDoors`) and lists the move in `canonical.meta.
    aliasPromotions` = [{id, field, aliasKey}]. The run's hand repairs (rp-007 shape: `expect`
    overheadDoors "tbd", `set` overheadDoors, `unset` levelAccessDoors) would then read the
    promoted value as drift and SUPERSEDE, and their `unset` would say "check the spelling".
  * 3.3c officeArea shape: merge writes a bare "4614" as "4,614 sq ft" when the record's own
    source states the unit. The run's value-format repairs (`expect` "4614", `set` "4614 sq ft")
    would SUPERSEDE for the same reason.
Both must keep APPLYING exactly as before (the entry's value lands, its ledger row is written),
and real drift must still supersede. Synthetic canonicals stand in for the re-merged output, so
this runs whether or not the merge half has landed. Offline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

FAILS = []
KEY = "northtown|devco|alpha park"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def prop(**kw):
    p = {"id": 7, "park": "Alpha Park", "city": "Northtown", "developer": "Devco",
         "country": "ZZ", "status": "Available", "warehouseArea": 50000}
    p.update(kw)
    return p


def entry(rid, **kw):
    e = {"id": rid, "property": {"key": KEY, "id": 7}, "why": "the spec page states it",
         "verified_by": "analyst", "source_file": "deck.pdf", "source_locator": "page 3"}
    e.update(kw)
    return e


def run(canonical, entries, ledger=()):
    c = json.loads(json.dumps(canonical))
    return c, R.apply(c, entries, provenance=list(ledger))


def alias_compat():
    print("== 3.5a: an rp-007-shaped entry after merge promoted the alias ==")
    rp = entry("rp-007", expect={"overheadDoors": "tbd"}, set={"overheadDoors": "4"},
               unset=["levelAccessDoors"])
    promoted_meta = {"aliasPromotions": [{"id": 7, "field": "overheadDoors",
                                          "aliasKey": "levelAccessDoors"}]}
    # merge promoted the SAME figure: already covered by the "already holds its set" rule
    c, rep = run({"meta": promoted_meta, "properties": [prop(overheadDoors="4")]}, [rp])
    ck(len(rep["applied"]) == 1 and not rep["superseded"], "same figure: APPLIED, not superseded")
    st = rep["stale"][0] if rep["stale"] else {}
    ck("promoted into overheadDoors by merge's strict alias step" in st.get("reason", ""),
       "the unset's stale note says merge promoted the key, not 'check the spelling'")
    ck("check the spelling" not in st.get("reason", ""), "...and no spelling hint")
    ck(st.get("alias_promoted") is True and st.get("landed_earlier") is False,
       "the stale entry carries alias_promoted True (counted in the quiet report)")

    # merge promoted a DIFFERENT spelling of the figure: only the new rule stops a supersede
    c, rep = run({"meta": promoted_meta, "properties": [prop(overheadDoors="4 doors")]}, [rp])
    ck(len(rep["applied"]) == 1 and not rep["superseded"],
       "promoted value differs from the repair's: the entry still APPLIES (the same move)")
    ck(c["properties"][0]["overheadDoors"] == "4", "...and the repair's own value lands")
    ck(R.ledger_rows(rep) and R.ledger_rows(rep)[0]["field"] == "overheadDoors",
       "...and it writes its ledger row as before")

    # WITHOUT the promotion record the same state is real drift and still supersedes
    c, rep = run({"meta": {}, "properties": [prop(overheadDoors="4 doors")]}, [rp])
    ck(len(rep["superseded"]) == 1 and not rep["applied"],
       "no aliasPromotions entry: the same state is drift and SUPERSEDES (guard not loosened)")
    # a promotion of a DIFFERENT alias key does not excuse this entry
    other = {"aliasPromotions": [{"id": 7, "field": "overheadDoors", "aliasKey": "driveInDoors"}]}
    c, rep = run({"meta": other, "properties": [prop(overheadDoors="4 doors")]}, [rp])
    ck(len(rep["superseded"]) == 1, "a promotion of another alias key still supersedes")
    # a promotion on ANOTHER property does not excuse this one
    far = {"aliasPromotions": [{"id": 8, "field": "overheadDoors",
                                "aliasKey": "levelAccessDoors"}]}
    c, rep = run({"meta": far, "properties": [prop(overheadDoors="4 doors")]}, [rp])
    ck(len(rep["superseded"]) == 1, "a promotion on another property id still supersedes")
    # malformed meta degrades to today's behaviour
    for bad in ({"aliasPromotions": "nope"}, {"aliasPromotions": [None, 3, {"id": 7}]}):
        c, rep = run({"meta": bad, "properties": [prop(overheadDoors="4 doors")]}, [rp])
        ck(len(rep["superseded"]) == 1 and not rep["invalid"],
           f"malformed aliasPromotions {str(bad)[:40]} is ignored, never raises")
    # the pre-promotion state (in-flight dir, no re-merge yet) is untouched
    c, rep = run({"meta": {}, "properties": [prop(levelAccessDoors="4")]}, [rp])
    ck(len(rep["applied"]) == 1 and "levelAccessDoors" not in c["properties"][0]
       and c["properties"][0].get("overheadDoors") == "4",
       "in-flight (not yet re-merged): the entry does the move itself, as it always did")


def office_compat():
    print()
    print("== 3.3c: a value-format entry after merge reformatted officeArea ==")
    saved = R.DERIVED_TWINS
    R.DERIVED_TWINS = {}              # isolate from the twin guard: this is about `expect`
    try:
        vf = entry("vf-q_1", expect={"officeArea": "4614"}, set={"officeArea": "4614 sq ft"})
        c, rep = run({"meta": {}, "properties": [prop(officeArea="4,614 sq ft")]}, [vf])
        ck(len(rep["applied"]) == 1 and not rep["superseded"],
           "merge now ships '4,614 sq ft': the vf entry APPLIES, not superseded")
        ck(c["properties"][0]["officeArea"] == "4614 sq ft", "...exactly as before (its value)")
        c, rep = run({"meta": {}, "properties": [prop(officeArea="4614")]}, [vf])
        ck(len(rep["applied"]) == 1, "the in-flight bare '4614' still applies (unchanged)")
        c, rep = run({"meta": {}, "properties": [prop(officeArea="5,000 sq ft")]}, [vf])
        ck(len(rep["superseded"]) == 1, "a DIFFERENT figure is still drift and supersedes")
        c, rep = run({"meta": {}, "properties": [prop(officeArea="4,614 sq m")]}, [vf])
        ck(len(rep["superseded"]) == 1, "the same figure in a DIFFERENT unit still supersedes")
        other = entry("rp-9", expect={"clearHeight": "12"}, set={"clearHeight": "12 m"})
        c, rep = run({"meta": {}, "properties": [prop(clearHeight="12.0 m")]}, [other])
        ck(len(rep["superseded"]) == 1,
           "the widening is officeArea-only: another field's reformat still supersedes")
    finally:
        R.DERIVED_TWINS = saved
    ck(R._same_area_text("4,614 sq ft", "4614 sq ft") and R._same_area_text("4.614 m2",
                                                                             "4614 sq m"),
       "_same_area_text: same figure + same unit, thousands separators either way")
    ck(not R._same_area_text("4614", "4614 sq ft") and not R._same_area_text(None, "x"),
       "_same_area_text: a unit-less side or garbage is never 'the same'")


def main() -> int:
    alias_compat()
    office_compat()
    print()
    if FAILS:
        print(f"REPAIRS MERGE COMPAT TEST: FAIL ({len(FAILS)})")
        return 1
    print("REPAIRS MERGE COMPAT TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
