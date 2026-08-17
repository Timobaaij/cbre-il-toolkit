#!/usr/bin/env python3
"""qualifier_upgrade_test.py - a "Target"/"Targeting"/"Targeted" hedge on a certification
field (breeam/epc) never silently disappears just because the un-hedged notation happens
to win source precedence.

THE DEFECT: `breeam` is TRACKER_AUTHORITATIVE, so a rich tracker's bare "Excellent" beats a
brochure's "Target Excellent" on PRECEDENCE alone - even though _values_equivalent correctly
recognises them as the SAME underlying grade (evals/value_equivalence_test.py:53 pins that
equivalence as intended). Once recognised as equivalent, nothing compared which of the two
equivalent SPELLINGS is safe to ship: dropping "Target" on a building still under
construction overclaims an achieved certification. A live run shipped exactly this - breeam
"Excellent" from a rich tracker, while the SAME property's epc correctly kept the brochure's
"Target A" (epc is not tracker-authoritative, so ordinary spec-precedence - brochure wins -
applied instead). The fix does NOT touch _values_equivalent/_ENUM_STRIP_RX/_enum_token -
those are correct and pinned; it only changes which of two EQUIVALENT values `merge_cluster`
keeps once they are already known to describe the same fact.

The must-NOT-fire cases matter as much as the fix: two equally-hedged (or equally bare)
equivalent values must still resolve by ordinary precedence, and a GENUINE conflict (two
DIFFERENT grades, e.g. "Excellent" vs "Very Good") must still go through the normal
conflict path, never the qualifier-upgrade path. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def trk(**fields):
    r = {"park": "P", "city": "C", "developer": "D",
         "__meta": {"source_file": "t.xlsx", "source_type": "xlsx", "tracker_rich": True,
                    "locator_base": "Tracker", "prov": {}}}
    r.update(fields)
    return r


def broc(**fields):
    r = {"park": "P", "city": "C", "developer": "D",
         "__meta": {"source_file": "d.pdf", "source_type": "pdf", "page_no": 3,
                    "locator_base": "page 4", "prov": {}}}
    r.update(fields)
    return r


def main() -> int:
    print("== the live defect: rich tracker's bare grade vs brochure's Target-hedged grade ==")
    variants: dict = {}
    out, prov, conflicts = M.merge_cluster(
        [trk(breeam="Excellent"), broc(breeam="Target Excellent")], variants=variants)
    ck(out.get("breeam") == "Target Excellent",
       f"the Target-hedged spelling ships even though the rich tracker wins ordinary "
       f"precedence for breeam (got {out.get('breeam')!r})")
    ck("breeam" not in conflicts,
       "this stays a notation variant, never a genuine conflict needing adjudication")
    ck("breeam" in variants, "the variant is still disclosed (I10), just not as a conflict")

    print()
    print("== reverse order: brochure listed first, tracker second - same outcome ==")
    out2, _p2, _c2 = M.merge_cluster(
        [broc(breeam="Target Excellent"), trk(breeam="Excellent")])
    ck(out2.get("breeam") == "Target Excellent",
       f"record order must not matter, only which value carries the hedge "
       f"(got {out2.get('breeam')!r})")

    print()
    print("== epc is unaffected (not TRACKER_AUTHORITATIVE - brochure already wins precedence) ==")
    out3, _p3, _c3 = M.merge_cluster(
        [trk(epc="A"), broc(epc="Target A")])
    ck(out3.get("epc") == "Target A",
       f"epc already kept the hedge before this fix (ordinary spec precedence); confirm "
       f"it still does (got {out3.get('epc')!r})")

    print()
    print("== must NOT fire when BOTH sides already carry (or both lack) the hedge ==")
    out4, _p4, _c4 = M.merge_cluster(
        [trk(breeam="Target Excellent"), broc(breeam="Excellent, Target BREEAM")])
    ck(out4.get("breeam") == "Target Excellent",
       f"the tracker's own value (already hedged) wins ordinary precedence unchanged "
       f"(got {out4.get('breeam')!r})")

    print()
    print("== must NOT suppress a GENUINE grade conflict ==")
    out5, _p5, conflicts5 = M.merge_cluster(
        [trk(breeam="Excellent"), broc(breeam="Very Good")])
    ck("breeam" in conflicts5,
       f"two DIFFERENT grades are a real conflict, not a qualifier upgrade "
       f"(got out={out5.get('breeam')!r}, conflicts={conflicts5!r})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
