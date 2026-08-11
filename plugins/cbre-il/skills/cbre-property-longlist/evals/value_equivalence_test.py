#!/usr/bin/env python3
"""value_equivalence_test.py - a notation variant is not a source conflict. (I10)

THE DEFECT. Two sites compared cross-source values with RAW STRING IDENTITY:
`merge_cluster` (`elif str(v) != str(chosen)`) decided whether to record a conflict, and
`conflict_candidates` (`if str(v) in seen_vals`) decided whether a second candidate exists - which is
what triggers an LLM adjudication. So `12.5 m` vs `12.5`, `1000 KVA` vs `1 MVA`, `800 KVA` vs
`800 kVa`, `8500 sq ft` vs `8500`, `2026-04-01` vs `April 2026`, `Available` vs `Available now`,
`Excellent` vs `Target BREEAM Excellent`, and `Raven Park` vs its own full postal address were all
reported as source conflicts and each cost an adjudication. On one live run that was ~24 of 34.

Two harms: the adjudication cost, and - worse - the Gaps Report's "Source conflicts" section is the
ONE list a broker acts on, so padding it with `12.5 m vs 12.5` teaches them to skim past the
material entries in the same list (108 vs 81 car spaces, 6 vs 8 dock doors, two different landlords).

WHAT THIS PINS: equivalence must be PROVEN, never assumed. The second half of this suite is the more
important half - the cases that MUST remain genuine conflicts. Offline, no build."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge  # noqa: E402


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    EQ = merge._values_equivalent

    # --- 1. magnitude + unit ------------------------------------------------ #
    ck(EQ("clearHeight", "12.5 m", 12.5), "12.5 m == 12.5")
    ck(EQ("clearHeight", "15 m", 15), "15 m == 15")
    ck(EQ("floorLoad", "50 kN/sq m", 50), "50 kN/sq m == 50")
    ck(EQ("electricity", "1000 KVA", "1 MVA"), "1000 kVA == 1 MVA")
    ck(EQ("electricity", "800 KVA", "800 kVa"), "unit case is irrelevant")
    ck(EQ("officeArea", "8500 sq ft", 8500), "8500 sq ft == 8500")
    ck(EQ("warehouseArea", "131,536 sq ft", 131536), "thousands separators are irrelevant")

    # --- 2. dates ----------------------------------------------------------- #
    ck(EQ("earlyAccess", "2026-04-01", "April 2026"), "ISO == month-precision prose")
    ck(EQ("earlyAccess", "2026-04", "April 2026"), "year-month == month-precision prose")

    # --- 3. short enumerations ---------------------------------------------- #
    ck(EQ("status", "Available", "Available now"), "a trailing 'now' is the same state")
    ck(EQ("status", "Available", "Available for immediate occupation"), "...and so is that")
    ck(EQ("breeam", "Excellent", "Target BREEAM Excellent"), "the BREEAM word and Target drop out")
    ck(EQ("epc", "A+", "EPC A+"), "the EPC word drops out")

    # --- 4. containment, park ONLY ------------------------------------------ #
    ck(EQ("park", "Raven Park",
          "Unit 1, Raven Park, Earlstree Industrial Estate, Corby, NN17 4XD"),
       "a scheme name inside its own full postal address")

    # --- the cases that MUST remain genuine conflicts (the important half) --- #
    ck(not EQ("officeArea", "6458 sq ft", 6790), "6458 != 6790 is a REAL conflict")
    ck(not EQ("warehouseArea", 125078, 124746), "a 0.27% area gap is a REAL conflict")
    ck(not EQ("loadingDocks", 6, 8), "6 != 8 docks is a REAL conflict")
    ck(not EQ("carParking", 108, 81), "108 != 81 spaces is a REAL conflict")
    ck(not EQ("motorway", "M1 [J19] 24 miles / 27 mins", "A43"), "M1 != A43 is a REAL conflict")
    ck(not EQ("region", "Northamptonshire", "East Midlands"),
       "region granularity is NOT suppressed - that is finding I11, not this one")
    ck(not EQ("landlord", "KZN Real Estate", "Block Industrial"), "two owners is a REAL conflict")
    ck(not EQ("clearHeight", "12.5 m", "15 m"), "different heights are a REAL conflict")
    ck(not EQ("status", "Available", "Under construction"), "a different STATE is a REAL conflict")
    ck(not EQ("breeam", "Excellent", "Very Good"), "different BREEAM bands are a REAL conflict")
    ck(not EQ("park", "Alpha Park", "Beta Park"), "two schemes are a REAL conflict")
    ck(not EQ("electricity", "50 kN/sq m", "50 kVA"), "different unit FAMILIES never match")
    ck(not EQ("earlyAccess", "2026-04-01", "May 2026"), "a different month is a REAL conflict")
    ck(not EQ("developer", "", "Canmoor"), "an empty value proves nothing")
    ck(not EQ("electricity", "1 MVA", "1 mystery-unit"),
       "an UNRECOGNISED unit suffix is never proof of equivalence")

    # --- the dedupe helper both call sites share ---------------------------- #
    seen = ["12.5 m"]
    ck(any(EQ("clearHeight", 12.5, s) for s in seen),
       "the seen-value scan the candidate dedupe uses recognises the variant")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
