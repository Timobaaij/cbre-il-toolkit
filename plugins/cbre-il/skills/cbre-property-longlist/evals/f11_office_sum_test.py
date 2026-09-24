#!/usr/bin/env python3
"""f11_office_sum_test.py - an office total the source never printed is SUMMED, conservatively. (F11)

WHAT WAS WRONG. 3 of 7 decks on a live run itemise office space across several schedule lines
(ground floor, first floor, hub office, pod office) and print no single office total. Every reader
correctly refused to add them (the contract's own rule: Python owns all arithmetic), shipped each
line under its own key, and raised a doubt. No Python step then did the sum they deferred, so
`officeArea` shipped `tbd`, the modal's Total GLA silently excluded the office, and four of the
run's twelve broker questions were this one missing addition.

THE FIX. `merge.derive_office_sum` runs on the merged record before `canonicalize`: it reads the
KEY NAMES the reader used (a component is a key whose tokens carry "office" and whose value is a
single stated area with a knowable unit), sums them into `officeArea`, notes the result in
provenance as a COMPUTED SUM naming every line, and reconciles against the deck's own printed
total where there is one.

WHAT THIS PINS, and why each guard exists:
  * two itemised decks of the live shape compute, and warehouse + office sum + the gatehouse the
    source states equals the printed total EXACTLY (the reconciliation is by subset of the other
    stated lines, so the gatehouse is found, not assumed);
  * a stated total wins, always, under any spelling or unit of the total's own family;
  * a gatehouse is NOT an office (the broker's live answers were "total minus warehouse", which
    folds the gatehouse in; f26 records that inflating an office figure to make a total agree was
    refused once, and Total GLA reconciliation is the stated total's job);
  * a rent, a percentage, a description and a count that happen to say "office" are not areas;
  * one line is not a sum; a subtotal beside its own parts (a key that is a token-prefix of
    another) is ambiguous and refused; a line stated in two units is one line; a sum at or above
    the warehouse figure is a unit mismatch and refused;
  * the whole pipeline: `officeAreaVal` is derived from the sum by canonicalize, and the
    provenance the derivation stamps carries the target unit so the dominant-unit alignment can
    convert it on its own footing.
Offline; no build.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def rec(**fields):
    """A merged record plus a provenance map of the shape merge_cluster produces."""
    meta = fields.pop("__meta", {})
    merged = dict(fields)
    prov = {k: {"source_file": "deck.pdf", "source_type": "pdf", "locator": f"page 3 ({k})"}
            for k in merged}
    cluster = [dict(merged, __meta=dict({"source_file": "deck.pdf", "source_type": "pdf"}, **meta))]
    return cluster, merged, prov


def main() -> int:
    print("f11_office_sum_test - sum the office lines the source itemised, never a stated total")

    print("== the live shape: four lines, no total, a gatehouse, a printed total ==")
    cl, m, pv = rec(warehouseArea="362746", areaUnit="sq ft",
                    groundFloorOffice="9,681 sq ft", firstFloorOffice="9,469 sq ft",
                    groundFloorPodOffice="2,570 sq ft", firstFloorPodOffice="2,510 sq ft",
                    securityGatehouseArea="283 sq ft", headlineArea="387,259 sq ft",
                    warehouseAreaSqm="33700",
                    __meta={"statedTotalArea": 387259, "statedTotalUnit": "sq ft"})
    out = M.derive_office_sum(cl, m, pv)
    # written with the dataset unit, the way sibling officeArea strings print: a bare int tripped
    # the value-format gate on the pipeline's own output
    ck(out and out["status"] == "computed" and m["officeArea"] == "24,230 sq ft",
       f"four office lines sum to '24,230 sq ft' (got {m.get('officeArea')!r})")
    ck("securityGatehouseArea" not in {c["key"] for c in out["components"]},
       "the gatehouse is NOT an office component")
    ck("headlineArea" not in {c["key"] for c in out["components"]} and "warehouseAreaSqm" not in
       {c["key"] for c in out["components"]}, "the headline and the sq m twin are not components")
    ck(out.get("residual") == 283 and "securityGatehouseArea" in str(out.get("reconciles")),
       f"RECONCILES: warehouse + office sum + gatehouse equals the printed total exactly "
       f"({out.get('reconciles')})")
    loc = pv["officeArea"]["locator"]
    ck(loc.startswith("COMPUTED SUM of 4 stated office lines") and "groundFloorOffice (9,681 sq ft)" in loc
       and "= 24,230 sq ft" in loc and "printed no single office total" in loc,
       "provenance names it a COMPUTED SUM, lists every line with its printed value, states the total")
    ck(pv["officeArea"]["areaUnitOfSource"] == "sq ft", "the provenance carries the unit for alignment")
    c = M.canonicalize(dict(m))
    ck(c.get("officeAreaVal") == 24230.0, "canonicalize derives officeAreaVal from the sum")

    print("== the second live shape: '...Area' suffixes, mixed-case unit, hub office split by floor ==")
    cl, m, pv = rec(warehouseArea="437775", areaUnit="Sq Ft",
                    groundFloorOfficeArea="11,829 Sq Ft", firstFloorOfficeArea="11,807 Sq Ft",
                    hubOfficeGroundFloorArea="1,286 Sq Ft", hubOfficeFirstFloorArea="1,286 Sq Ft",
                    gatehouseArea="1,006 Sq Ft",
                    __meta={"statedTotalArea": 464989, "statedTotalUnit": "Sq Ft"})
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "computed" and m["officeArea"] == "26,208 sq ft",
       f"sums to '26,208 sq ft' (got {m.get('officeArea')!r})")
    ck(M.canonicalize(dict(m)).get("officeAreaVal") == 26208.0
       and (M._office_area_parse(m["officeArea"]) or {}).get("value") == 26208.0,
       "the unit string still yields officeAreaVal == 26208 (canonicalize and _office_area_parse)")
    ck(out.get("residual") == 1006 and "gatehouseArea" in str(out.get("reconciles")),
       "reconciles exactly once the stated gatehouse is added")

    print("== a stated total wins, always ==")
    cl, m, pv = rec(officeArea="15213", areaUnit="sq ft", hubOffice="3,975 sq ft",
                    mainOfficeAreaSqm="1,413 sq m", warehouseArea="318826")
    ck(M.derive_office_sum(cl, m, pv) is None and m["officeArea"] == "15213",
       "a stated officeArea is never overwritten, even with more office lines beside it")
    cl, m, pv = rec(officeAreaSqm="1,166 sq m", areaUnit="sq ft", groundFloorOffice="5,000 sq ft",
                    firstFloorOffice="5,000 sq ft", warehouseArea="439363")
    ck(M.derive_office_sum(cl, m, pv) is None and "officeArea" not in m,
       "a total stated in another unit (officeAreaSqm) also wins: nothing is summed")
    cl, m, pv = rec(officeAreaVal=12556.0, areaUnit="sq ft", groundFloorOffice="5,000 sq ft",
                    firstFloorOffice="5,000 sq ft", warehouseArea="439363")
    ck(M.derive_office_sum(cl, m, pv) is None, "a numeric officeAreaVal from a tracker wins")

    print("== what is not an office component ==")
    cl, m, pv = rec(warehouseArea="200000", areaUnit="sq ft",
                    groundFloorOffice="4,000 sq ft", firstFloorOffice="4,000 sq ft",
                    officeRent="8.50 psf", epcOffices="A+", officeDescription="Three storey fitted",
                    officeParking="20 spaces", officeFloors=2, officeRatio="5%", gatehouseArea="200 sq ft")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and m["officeArea"] == "8,000 sq ft" and {c["key"] for c in out["components"]} ==
       {"groundFloorOffice", "firstFloorOffice"},
       f"rent, EPC, description, parking, floors, ratio and gatehouse are excluded "
       f"({[c['key'] for c in out['components']]})")

    print("== refusals that leave an honest gap ==")
    cl, m, pv = rec(warehouseArea="200000", areaUnit="sq ft", hubOfficeArea="10,429 sq ft")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "refused" and "officeArea" not in m and "not a sum" in out["why"],
       "one office line is not a sum")
    cl, m, pv = rec(warehouseArea="200000", areaUnit="sq ft", hubOffice="5,000 sq ft",
                    hubOfficeGroundFloor="2,500 sq ft", hubOfficeFirstFloor="2,500 sq ft",
                    mainOffice="8,000 sq ft")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "refused" and "subtotal" in out["why"] and "officeArea" not in m,
       "a subtotal beside its own parts is AMBIGUOUS and refused")
    cl, m, pv = rec(warehouseArea="200000", areaUnit="sq ft", groundFloorOffice="4,000 sq ft",
                    firstFloorOffice="4,000 sq ft", firstFloorOfficeAreaSqm="372 sq m")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "computed" and m["officeArea"] == "8,000 sq ft",
       "a line stated in two units counts ONCE, in the record's unit")
    cl, m, pv = rec(warehouseArea="4000", areaUnit="sq m", groundFloorOffice="30,000 sq ft",
                    firstFloorOffice="30,000 sq ft")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "refused" and "unit mismatch" in out["why"] and "officeArea" not in m,
       "a sum at or above the warehouse figure is refused as a unit mismatch")
    cl, m, pv = rec(warehouseArea="200000", groundFloorOffice="4000", firstFloorOffice="4000")
    out = M.derive_office_sum(cl, m, pv)
    ck(out is None and "officeArea" not in m,
       "bare numbers under keys that never say 'area', with no unit anywhere, are not summed")
    cl, m, pv = rec(warehouseArea="200000", groundFloorOfficeArea="4000", firstFloorOfficeArea="4000")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "refused" and "unit" in out["why"] and "officeArea" not in m,
       "area-named lines with NO knowable unit (no text unit, no record areaUnit) are refused")

    print("== a residual the source does not explain is DISCLOSED, not hidden ==")
    cl, m, pv = rec(warehouseArea="300000", areaUnit="sq ft", groundFloorOffice="5,000 sq ft",
                    firstFloorOffice="5,000 sq ft",
                    __meta={"statedTotalArea": 320000, "statedTotalUnit": "sq ft"})
    out = M.derive_office_sum(cl, m, pv)
    ck(out and out["status"] == "computed" and str(out.get("reconciles")).startswith("does NOT")
       and out.get("residual") == 10000,
       f"an unexplained 10,000 residual is named ({out.get('reconciles')})")

    print("== a sq m deck with sq m lines computes in sq m ==")
    cl, m, pv = rec(warehouseArea="30000", areaUnit="sq m", groundFloorOffice="900 sq m",
                    firstFloorOffice="900 sq m")
    out = M.derive_office_sum(cl, m, pv)
    ck(out and m["officeArea"] == "1,800 sq m" and out["unit"] == "sq m" and pv["officeArea"]["areaUnitOfSource"] == "sq m",
       "the target unit is the record's own")
    ck(M.canonicalize(dict(m)).get("officeAreaVal") == 1800.0,
       "...and officeAreaVal is still the number")

    print()
    if FAILS:
        print(f"F11 OFFICE SUM TEST: FAIL ({len(FAILS)})")
        return 1
    print("F11 OFFICE SUM TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
