#!/usr/bin/env python3
"""pick_gate_test.py - the plausibility gate must not reinstate the value it rejected. (B3)

THE DEFECT. `merge._pick_passes_gate` returned a BOOLEAN, and its final line was
`return False  # no defined gate -> precedence stands`. So "there is no gate for this field" and
"this value failed its gate" were the same answer, with two consequences:

  1. For every field outside rents / areas / lat-lng an adjudicated override was discarded
     UNCONDITIONALLY, and the discard was then narrated to the broker as a plausibility failure by a
     gate that does not exist. Live text: `id 3 breeam: LLM pick 'EPC A+' rejected (failed breeam
     plausibility gate); kept precedence 'A+'`. An LLM adjudicated 34 conflicts across two rounds on
     that run and only a rent, an area or a coordinate could ever have moved.
  2. Where a gate DID exist, a failing candidate caused the pipeline to reinstate the precedence
     winner - so the gate could only ever protect the default and could never catch it. That is how
     an impossible BREEAM "A+" reached a client card.

WHAT THIS PINS: a three-state verdict; enum/count/height gates that catch a bad value from EITHER
source; an ungated field HONOURING the selection rather than silently dropping it; and the failure
direction - a rejected pick keeps the default only when the default passes the same check, otherwise
the field is struck rather than shipping something nothing verified. Offline, no build."""
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

    V = merge._pick_gate_verdict

    # --- three states, not a boolean ---------------------------------------- #
    ck(V("warehouseRentVal", 8.5, "GBP/sq ft/yr") == "pass", "a plausible rent passes")
    ck(V("warehouseRentVal", 9000, "GBP/sq ft/yr") == "fail", "an implausible rent fails")
    ck(V("landlord", "KZN Real Estate") == "none",
       "an ungated field reports 'none' - NOT 'fail', which is the whole defect")
    ck(V("motorway", "A14 (J17) 11 miles") == "none", "...and so does motorway")
    ck(V("lat", 52.5) == "pass" and V("lat", 999) == "fail", "coordinate bounds still gate")

    # --- the enum gates B3 asked for: they catch a bad value from EITHER source --- #
    ck(V("breeam", "Excellent") == "pass", "a BREEAM band passes")
    ck(V("breeam", "Very Good") == "pass", "a two-word BREEAM band passes")
    ck(V("breeam", "Target BREEAM Excellent") == "pass", "a qualified BREEAM band passes")
    ck(V("breeam", "Excellent (targeted)") == "pass", "a parenthesised qualifier still passes")
    ck(V("breeam", "A+") == "fail", "an EPC letter band in breeam FAILS - the live defect")
    ck(V("breeam", "A") == "fail", "...including a bare letter")
    ck(V("epc", "A+") == "pass", "an EPC band passes in epc")
    ck(V("epc", "Target A") == "pass", "a targeted EPC band passes")
    ck(V("epc", "Excellent") == "fail", "a BREEAM word in epc FAILS")

    # --- counts and heights ------------------------------------------------- #
    ck(V("carParking", 108) == "pass", "a sane count passes")
    ck(V("loadingDocks", 0) == "pass", "zero docks is DATA, not a failure")
    ck(V("carParking", -3) == "fail", "a negative count fails")
    ck(V("truckParking", 99999) == "fail", "an absurd count fails")
    ck(V("overheadDoors", 2.5) == "fail", "a fractional door count fails")
    ck(V("clearHeight", "12.5 m") == "pass", "a metric eaves height passes")
    ck(V("clearHeight", 15) == "pass", "a bare metric eaves height passes")
    ck(V("clearHeight", 400) == "fail", "an absurd eaves height fails")
    ck(V("clearHeight", "40 ft") == "none",
       "an IMPERIAL eaves height is UNGATED, never judged against a metre band")

    # --- the boolean wrapper still behaves for any existing caller ---------- #
    ck(merge._pick_passes_gate("warehouseRentVal", 8.5, "GBP/sq ft/yr") is True,
       "the back-compatible boolean wrapper passes a good rent")
    ck(merge._pick_passes_gate("landlord", "X", None) is False,
       "...and is False for an ungated field, exactly as before")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
