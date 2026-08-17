#!/usr/bin/env python3
"""tracker_basis_diff_test.py - a size column's basis resolved via a role:size_basis
qualifier column must be DISCLOSED as such (naming the mechanism), never as a bare `None`
that reads as "this pass had no answer" - and the qualifier column's OWN index must
never generate "basis" diff noise, since a role:size_basis column has no basis of its own.

THE DEFECT: diff_tracker_maps compared each column's raw `.get("basis")` by index only,
blind to a role:size_basis companion column supplying the SAME information per-row at
PARSE time (information the map itself does not contain). A live run's primary map
expressed a size column's basis via a size_basis qualifier column (basis=None on the size
column itself, by design); the independent verify pass expressed the same conclusion as a
direct "GIA" attribute. The diff reported pass1=None, pass2="GIA", and the Gaps Report
disclosed this as "the dashboard used pass 1" - reading as pass 1 having NO answer, when it
had a legitimate alternative mechanism. NOTE: this does NOT try to prove the two mechanisms
are equivalent (that is unverifiable from the map alone, since the qualifier column's real
per-row values are unknown here) - it is still reported as a disagreement, but with an
honest value naming the mechanism instead of a bare None.

The must-NOT-regress cases matter as much as the fix: a GENUINE basis disagreement (two
DIRECT attributes that actually differ, e.g. GIA vs GEA) must still be reported unchanged; a
column with NEITHER a direct basis NOR any qualifier column on either side is a genuine gap
and must still be reported; a non-basis key (e.g. "field") must be completely unaffected;
and - the regression an earlier attempt at this fix introduced - the qualifier column's OWN
index must produce ZERO "basis" diffs, on either side, in every case below. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import extract_xlsx as X  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _map(columns):
    return {"columns": columns}


def main() -> int:
    print("== the live defect: qualifier-column basis vs direct-attribute basis ==")
    # pass 1 (the primary map): size column (idx 38) has NO basis attribute of its own;
    # a separate column (idx 39) is flagged role:size_basis - the per-row qualifier that
    # supplies the basis instead, EXACTLY as reference/interpretation.md documents it (the
    # qualifier column itself carries no "basis" attribute - that is the whole point of it).
    pass1 = _map([
        {"index": 38, "field": "warehouseArea", "areaUnit": "sq ft"},
        {"index": 39, "field": None, "role": "size_basis"},
    ])
    # pass 2 (the blind verify): same size column, basis stated directly as "GIA", no
    # qualifier column at all.
    pass2 = _map([
        {"index": 38, "field": "warehouseArea", "areaUnit": "sq ft", "basis": "GIA"},
    ])
    diffs = X.diff_tracker_maps(pass1, pass2)
    basis38 = [d for d in diffs if d["key"] == "basis" and d["index"] == 38]
    ck(len(basis38) == 1,
       f"the pair is still surfaced as a disagreement (unverifiable from the map alone), "
       f"exactly once (got {diffs!r})")
    if basis38:
        ck(basis38[0]["pass1"] is not None and "39" in str(basis38[0]["pass1"]),
           f"pass1's disclosed value NAMES the qualifier column (39), instead of a bare "
           f"None that reads as 'no answer at all' (got {basis38[0]['pass1']!r})")
        ck(basis38[0]["pass2"] == "GIA",
           f"pass2's disclosed value is untouched - it had a direct attribute "
           f"(got {basis38[0]['pass2']!r})")
    ck(not any(d["key"] == "basis" and d["index"] == 39 for d in diffs),
       f"the qualifier column's OWN index (39) produces ZERO basis diffs - it has no basis "
       f"of its own to compare (got {diffs!r})")

    print()
    print("== must NOT suppress a GENUINE basis disagreement (two direct attributes) ==")
    pass1_gia = _map([{"index": 38, "field": "warehouseArea", "basis": "GIA"}])
    pass2_gea = _map([{"index": 38, "field": "warehouseArea", "basis": "GEA"}])
    diffs2 = X.diff_tracker_maps(pass1_gia, pass2_gea)
    ck(any(d["key"] == "basis" and d["index"] == 38
           and d["pass1"] == "GIA" and d["pass2"] == "GEA" for d in diffs2),
       f"GIA vs GEA (two direct attributes, genuinely different) still reported unchanged "
       f"(got {diffs2!r})")

    print()
    print("== must NOT suppress a genuine gap (neither side resolves the basis at all) ==")
    pass1_none = _map([{"index": 38, "field": "warehouseArea"}])
    pass2_gia = _map([{"index": 38, "field": "warehouseArea", "basis": "GIA"}])
    diffs3 = X.diff_tracker_maps(pass1_none, pass2_gia)
    ck(any(d["key"] == "basis" and d["index"] == 38 and d["pass1"] is None
           and d["pass2"] == "GIA" for d in diffs3),
       f"a genuinely unresolved side (no attribute, no qualifier column anywhere on that "
       f"side) still shows a bare None - there is no mechanism to name "
       f"(got {diffs3!r})")

    print()
    print("== other _VERIFY_KEYS are completely unaffected ==")
    pass1_field = _map([{"index": 5, "field": "park"}])
    pass2_field = _map([{"index": 5, "field": "developer"}])
    diffs4 = X.diff_tracker_maps(pass1_field, pass2_field)
    ck(any(d["key"] == "field" and d["pass1"] == "park" and d["pass2"] == "developer"
           for d in diffs4),
       f"a genuine field-binding disagreement is still reported unchanged (got {diffs4!r})")

    print()
    print("== the qualifier index produces no diff even when only ONE side has it ==")
    only_one_side = _map([{"index": 38, "field": "warehouseArea"}])  # pass2 has nothing at 39
    diffs5 = X.diff_tracker_maps(pass1, only_one_side)
    ck(not any(d["key"] == "basis" and d["index"] == 39 for d in diffs5),
       f"index 39 exists only in pass1 (as the qualifier column) and absent entirely from "
       f"pass2 - still zero basis diffs there (got {diffs5!r})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
