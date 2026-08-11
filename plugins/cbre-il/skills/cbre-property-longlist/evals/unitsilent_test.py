#!/usr/bin/env python3
"""unitsilent_test.py - a rent with no stated unit never invents one. (B06)

rent_display defaulted to EUR/sq m, so a UK deck quoting a bare `Rent: 7.25` shipped
'€7.25 / sq m / year' - a specific claim about currency AND basis that no source made, and
one a broker cannot tell from a sourced figure. Currency is unrecoverable downstream
(merge refuses to convert it because FX would be invention), so a wrong one is wrong for
good. extract_pdf._rent_unit_assumed, the honesty flag built for exactly this, had zero
callers - but the real choke point was rent_display, reached from every path.

Second, unreported, defect: extract_xlsx STAMPED the fabricated default as a real
`rentUnit`, which fed merge.dominant_units - two unit-silent tracker rows were enough to
flip a GBP/sq ft dataset to EUR/sq m for every property on it.

The number is kept in both cases. It is the UNIT that is unknown, and `tbd` would throw
away a figure the source did give. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import normalize as N  # noqa: E402
import merge as M  # noqa: E402

XSRC = (HELPERS / "extract_xlsx.py").read_text(encoding="utf-8", errors="replace")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # --- the choke point --------------------------------------------------------
    bare = N.rent_display(7.25)
    ck("7.25" in bare, f"the NUMBER is kept {ascii(bare)}")
    for token in ("EUR", "€", "sq m", "£", "$"):
        ck(token not in bare, f"no invented {ascii(token)} in a unit-silent rent {ascii(bare)}")
    ck("not stated" in bare, f"...and it says the unit is unknown {ascii(bare)}")
    ck(N.rent_display(7.25, None) == bare, "an explicit None behaves the same as omitted")

    # a STATED unit is completely unaffected - this must not move a single sourced card
    ck(N.rent_display(8.5, "£/sq ft/yr") == "£8.5 / sq ft / year",
       "a stated GBP/sq ft rent renders exactly as before")
    ck(N.rent_display(60, "€/sq m/yr") == "€60 / sq m / year",
       "a stated EUR/sq m rent renders exactly as before")

    # --- the fabricated rentUnit must not reach the dataset vote ----------------
    ck("if not unit_assumed:" in XSRC and 'rec["rentUnit"] = unit' in XSRC,
       "extract_xlsx only stamps rentUnit when the source actually stated one")
    i_guard = XSRC.find("if not unit_assumed:")
    i_stamp = XSRC.find('rec["rentUnit"] = unit')
    ck(-1 < i_guard < i_stamp, "the guard precedes the stamp")

    # dominant_units must not be tipped by unit-silent records
    def _r(unit=None, val=7.0):
        r = {"park": "P", "warehouseRentVal": val, "warehouseArea": 1000, "areaUnit": "sq ft",
             "__meta": {"source_file": "t.xlsx", "source_type": "xlsx"}}
        if unit:
            r["rentUnit"] = unit
        return r

    stated = [_r("£/sq ft/yr") for _ in range(3)]
    silent = [_r() for _ in range(2)]
    au, ru = M.dominant_units(stated + silent)
    ck("£" in ru or "sq ft" in ru,
       f"3 stated GBP/sq ft rents + 2 unit-silent ones stay GBP/sq ft {ascii(ru)}")

    # --- the flag the honesty pipeline reads is still set -----------------------
    ck("rentUnitAssumed" in XSRC, "the rentUnitAssumed honesty flag is still recorded")
    ck("rentUnit" in XSRC and "ASSUMED" in XSRC,
       "and the provenance still explains the assumption to the broker")
    # ...and it must NOT reach the client card (B05's sweep owns that)
    ck("rentUnitAssumed" in M._INTERNAL_FLAGS,
       "rentUnitAssumed is swept off the property before it ships")

    if fails:
        print(f"\nUNITSILENT TEST: FAIL ({len(fails)})")
        return 1
    print("\nUNITSILENT TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
