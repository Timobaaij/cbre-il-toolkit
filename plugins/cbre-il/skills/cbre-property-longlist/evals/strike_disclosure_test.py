#!/usr/bin/env python3
"""strike_disclosure_test.py - the T1 never-strike-stated-data contract.

Pins the three mechanisms that once struck five CORRECT printed values to tbd (each with a
ledger row calling the source implausible):
(1) a RANGE is ungated - "10-12 m" / "EUR 114-126" judge as "none", never "fail"
    (extract_first_number still refuses ranges for ARITHMETIC - that contract is unchanged);
(2) plotArea uses the SITE ceiling (a 630,000 / 772,000 sq m park plot passes; a building
    that size still fails; a 12M sq m plot garble still fails);
(3) the strike note names the PARSE, never accuses the source, and points at repairs.json.
Plus the BTS half: the reader contract (run.py field_rules + interpretation.md) now says a
printed BTS is DATA, and no Python sentinel list swallows "bts".

Run: python evals/strike_disclosure_test.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import merge  # noqa: E402
import normalize as N  # noqa: E402
import run as R  # noqa: E402


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    # (1) ranges: ungated in the verdict, still range-refusing in arithmetic
    check(N.extract_first_number("10-12 m") is None,
          "extract_first_number still refuses ranges for arithmetic (unchanged)")
    check(merge._pick_gate_verdict("clearHeight", "10-12 m") == "none",
          "a clear-height RANGE judges 'none', never 'fail'")
    check(merge._pick_gate_verdict("officeRent", "€ 114-126 per sq. m. per annum") == "none",
          "an office-rent RANGE judges 'none', never 'fail'")
    check(merge._pick_gate_verdict("loadingDocks", "10-12") == "none",
          "a count RANGE judges 'none', never 'fail'")
    check(merge._pick_gate_verdict("clearHeight", "10 m") == "pass",
          "a plain in-band height still passes")
    check(merge._pick_gate_verdict("warehouseRentVal", 63) == "pass",
          "a plain in-band rent still passes")
    check(merge._pick_gate_verdict("clearHeight", "garble") == "fail",
          "a non-numeric non-range still fails (garble protection intact)")

    # (2) plotArea site ceiling; building ceiling intact; garble still caught
    check(merge._pick_gate_verdict("plotArea", 630000, None, "sq m") == "pass",
          "a 630,000 sq m PLOT passes (63 ha site is routine)")
    check(merge._pick_gate_verdict("plotArea", 772000, None, "sq m") == "pass",
          "a 772,000 sq m PLOT passes")
    check(merge._pick_gate_verdict("warehouseArea", 630000, None, "sq m") == "fail",
          "a 630,000 sq m BUILDING still fails (building ceiling intact)")
    check(merge._pick_gate_verdict("plotArea", 12_000_000, None, "sq m") == "fail",
          "a 12M sq m plot still fails (garble ceiling intact)")
    check(N.area_band_for("sq m") == (N.AREA_SQM_MIN, N.AREA_SQM_MAX),
          "area_band_for without a field is unchanged (back-compat)")
    check(N.area_band_for("sq ft", field="plotArea")[1] == N.PLOT_SQFT_MAX,
          "the sq ft plot ceiling rides the same field switch")
    check(N.PLOT_SQFT_MAX >= N.PLOT_SQM_MAX * 10.764,
          "the sq ft plot ceiling never straddles the sq m one")

    # (3) the strike note: names the parse, points at repairs.json, never accuses the source
    src = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8")
    check("falls outside the {field} " in src and "work/repairs.json" in src,
          "the strike note names the parse and the repairs.json recovery path")
    check("fails the {field} plausibility gate, so the field is" not in src,
          "the old source-accusing strike wording is gone")

    # BTS is data: contract text pinned in both places, and no sentinel swallows it
    check("BUILT TO SUIT" in R._FIELD_RULES and "tbd/TBC/BTS/TBS" not in R._FIELD_RULES,
          "run.py field_rules: BTS is data, no longer an unknown sentinel")
    interp = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    check("`BTS` is NOT unknown" in interp,
          "interpretation.md carries the BTS-is-data rule")
    check(not N.looks_unknown("BTS") and N.sentinel("BTS") == "BTS",
          "no Python sentinel swallows a printed 'BTS'")

    print(f"\n{'PASS' if not fails else 'FAIL'} strike_disclosure_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
