#!/usr/bin/env python3
"""formula_rent_rounding_test.py - a formula-noise rent never blocks validate-data.

A tracker's derived rent column (=(rate*area)/area_sqm) hands openpyxl the raw
float (102.257192986233). The display string rounds, validate-data demands the
value match its own display, and the dictionary path BLOCKED on every
formula-valued tracker (the LLM map masked it on live runs). Rents are currency
rates: the extractor now rounds the annual figure to 2 decimals, exactly like
the monthly x12 path always has. Literal 2dp quotes are untouched. Offline.
"""
import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
from openpyxl import Workbook  # noqa: E402
import extract_xlsx as X  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


def _write(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    p = pathlib.Path(tempfile.mkdtemp()) / "tracker.xlsx"
    wb.save(str(p))
    return p


p = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Quoting Rent (GBP/sqm/y)"],
    ["Alpha Park", "Corby", 35977, 102.257192986233],
    ["Beta Park", "Rugby", 30000, 9.75],
])
recs = X.detect_and_extract(p)["records"]
check("noise-rounded", recs[0].get("warehouseRentVal") == 102.26)
check("literal-untouched", recs[1].get("warehouseRentVal") == 9.75)

print("FORMULA RENT ROUNDING TEST: PASS")
