#!/usr/bin/env python3
"""xlsx_coords_test.py - Excel map-link coverage. A maps URL / bare lat,lng sitting in a NON-coord
cell (a 'Notes'/'Link' column) is stashed into __meta.map_candidates for the shared resolver; a
dedicated lat/lng COLUMN still fills coords directly (and needs no stash). Fast + offline."""
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


# 1) maps URL in a Notes column -> stashed candidate (no dedicated coord column)
p = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Notes"],
    ["Alpha Park", "Madrid", 25000, "site https://maps.google.com/?q=40.4168,-3.7038 near ring road"],
])
res = X.detect_and_extract(p)
rec = res["records"][0]
cands = rec.get("__meta", {}).get("map_candidates", [])
check("url-stashed", any("maps.google.com/?q=40.4168,-3.7038" in c for c in cands))
check("no-inline-coords", "lat" not in rec)  # the resolver, not the extractor, parses it

# 2) bare lat,lng in a Notes column -> stashed
p2 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Notes"],
    ["Gamma Park", "Rome", 18000, "coordinates 41.9028, 12.4964"],
])
rec2 = X.detect_and_extract(p2)["records"][0]
cands2 = rec2.get("__meta", {}).get("map_candidates", [])
check("plain-stashed", any("41.9028, 12.4964" in c for c in cands2))

# 3) dedicated lat/lng COLUMNS still fill coords directly; nothing to stash
p3 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Latitude", "Longitude"],
    ["Beta Park", "Berlin", 30000, 52.52, 13.405],
])
rec3 = X.detect_and_extract(p3)["records"][0]
check("col-lat", rec3.get("lat") == 52.52 and rec3.get("lng") == 13.405)
check("col-nostash", "map_candidates" not in rec3.get("__meta", {}))

print("XLSX COORDS TEST: PASS")
