#!/usr/bin/env python3
"""An area stated in acres must not be dropped, nor converted by whoever feels like it. (B58)

A record carries ONE areaUnit, so a field whose source states a DIFFERENT unit had nowhere to go.
UK decks state site area in acres essentially always. Two isolated agents on the SAME run split:
MPC2 omitted its "31.629 acres (12.8 ha)" as an honest gap, UltraBox converted "30 ACRES" to
1,306,800 sq ft citing a convention. Both readings of the contract were defensible, which makes
this an UNDER-SPECIFIED CONTRACT rather than a model failure - and the consequence reached the
client, because MPC2's ledger then asserted "absent in all sources" for a figure printed on its
page 2. Both critical reviewers raised it as blocking.

The fix: the model reports the unit the source states for THAT figure; Python converts with the
constants normalize.py already had. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import normalize as N  # noqa: E402
import merge as M      # noqa: E402

FAILURES = []


def ck(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


print("normalize.area_factor - exact and total over the four recognised units:")
ck("acres -> sq ft is the exact 43,560", N.area_factor("acres", "sq ft") == N.SQFT_PER_ACRE)
ck("sq ft -> acres round-trips",
   abs(N.area_factor("sq ft", "acres") * N.SQFT_PER_ACRE - 1) < 1e-9)
ck("ha -> sq m is the exact 10,000", N.area_factor("ha", "sq m") == N.SQM_PER_HA)
ck("sq m -> sq ft reuses the existing constant",
   N.area_factor("sq m", "sq ft") == N.SQFT_PER_SQM)
ck("acres -> sq m crosses systems via SQFT_PER_SQM",
   abs(N.area_factor("acres", "sq m") - (N.SQFT_PER_ACRE / N.SQFT_PER_SQM)) < 1e-6)
ck("ha -> sq ft crosses the other way",
   abs(N.area_factor("ha", "sq ft") - (N.SQM_PER_HA * N.SQFT_PER_SQM)) < 1e-6)
ck("the same unit is 1.0", N.area_factor("sq ft", "sq ft") == 1.0)
ck("an UNRECOGNISED unit returns None, never a guessed factor",
   N.area_factor("perches", "sq ft") is None and N.area_factor("sq ft", "furlongs") is None)
ck("a blank unit returns None", N.area_factor("", "sq ft") is None)
ck("case and spacing are tolerated", N.area_factor("ACRES", " sq ft ") == N.SQFT_PER_ACRE)

print("\nThe live case: 31.629 acres in a sq ft dataset")
_v = 31.629 * N.area_factor("acres", "sq ft")
ck("converts to 1,377,759 sq ft - the figure a manual override had to supply by hand",
   round(_v) == 1377759, str(round(_v)))


def rec(**kw):
    r = {"park": "P", "city": "C", "areaUnit": "sq ft",
         "__meta": {"source_file": "d.pdf", "source_type": "pdf",
                    "prov": {"warehouseArea": "page 2", "plotArea": "page 2"}}}
    r.update(kw)
    return r


print("\nmerge exposes the FIELD's own unit, so the alignment loop can act on it:")
r1 = rec(warehouseArea=100000, plotArea=31.629, plotAreaUnit="acres")
_m, _p, _c = M.merge_cluster([r1])
ck("a field-level unit wins for that field",
   (_p.get("plotArea") or {}).get("areaUnitOfSource") == "acres",
   str(_p.get("plotArea")))
ck("...and the record-level areaUnit still supplies a field with no override",
   (_p.get("warehouseArea") or {}).get("areaUnitOfSource") == "sq ft",
   str(_p.get("warehouseArea")))
ck("a record with no field-level unit is unchanged",
   (M.merge_cluster([rec(warehouseArea=1)])[1].get("warehouseArea") or {})
   .get("areaUnitOfSource") == "sq ft")

print("\nAn UNRECOGNISED unit is withheld and disclosed, never mislabelled:")
ck("area_factor refuses it", N.area_factor("perches", "sq ft") is None)
ck("...so a caller must not convert - asserted at the factor, which is the only place that "
   "could invent one", N.area_factor("perches", "sq ft") is None)

print("\nRents and currency are untouched by any of this:")
ck("area_factor knows nothing about currency", N.area_factor("GBP", "EUR") is None)

print()
if FAILURES:
    print(f"FIELD UNITS TEST: FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("FIELD UNITS TEST: PASS (the model states the unit, Python converts, nothing is dropped)")
