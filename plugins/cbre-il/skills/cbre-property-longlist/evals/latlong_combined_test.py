#!/usr/bin/env python3
"""latlong_combined_test.py - the combined 'Lat Long' header misbind (live UK run).

A tracker column headed exactly 'Lat Long' (space, no comma) matched no latlng alias
exactly or whole-word, so the bare 'long' alias won at the whole-word tier, the whole
column bound to lng alone, and the pair cell shipped its FIRST float - the latitude -
as the longitude: every pin at ~52 degrees E. Three layers pinned here:
  1. alias: the space/ampersand combined forms map to latlng;
  2. structural guard: a header naming BOTH a lat and a lng token is latlng, always;
  3. value guard: a coordinate PAIR landing in a single lat/lng field is split,
     never truncated to its first number.
Fast + offline.
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


# 1) the exact live failure shape: header 'Lat Long', pair cell -> both coords, correct way round
p = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Lat Long"],
    ["Alpha Park", "Northampton", 61262, "52.480401, -0.652005"],
])
rec = X.detect_and_extract(p)["records"][0]
check("latlong-lat", rec.get("lat") == 52.480401)
check("latlong-lng", rec.get("lng") == -0.652005)

# 2) header classification: both-token headers are latlng regardless of punctuation;
#    single-token headers keep their single field (the legitimate bare 'Long' column)
check("hdr-lat-long", X._header_field("Lat Long") == "latlng")
check("hdr-lat-amp-long", X._header_field("Lat & Long") == "latlng")
check("hdr-long-lat", X._header_field("Long Lat") == "latlng")
check("hdr-bare-long", X._header_field("Long") == "lng")
check("hdr-bare-lat", X._header_field("Lat") == "lat")
check("hdr-latitude", X._header_field("Latitude") == "lat")
check("hdr-longitude", X._header_field("Longitude") == "lng")

# 3) value guard: a PAIR that lands in a SINGLE coord column (misbound header) is
#    split into both fields, never truncated to its first number
p3 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Longitude"],
    ["Beta Park", "Berlin", 30000, "52.520008, 13.404954"],
])
rec3 = X.detect_and_extract(p3)["records"][0]
check("pair-split-lat", rec3.get("lat") == 52.520008)
check("pair-split-lng", rec3.get("lng") == 13.404954)

# 4) regression: separate numeric Latitude/Longitude columns unchanged
p4 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Latitude", "Longitude"],
    ["Gamma Park", "Rome", 18000, 41.9028, 12.4964],
])
rec4 = X.detect_and_extract(p4)["records"][0]
check("single-cols-lat", rec4.get("lat") == 41.9028)
check("single-cols-lng", rec4.get("lng") == 12.4964)

# 5) an unresolvable pair in a single coord field is REFUSED - no coords, and the
#    refusal is DISCLOSED via the header_report (never a silent drop)
p5 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Longitude"],
    ["Delta Park", "Paris", 22000, "999.123456, 998.405"],
])
res5 = X.detect_and_extract(p5)
rec5 = res5["records"][0]
check("bad-pair-dropped", "lat" not in rec5 and "lng" not in rec5)
hr5 = next(h for h in res5["header_report"] if h.get("populated_columns"))
check("bad-pair-disclosed", any("999.123456" in str(d.get("value"))
                                for d in hr5.get("coord_unparsed", [])))

# 6) hand-typed pins with 1-2 decimals still split (the strict free-text regex
#    requires 3+; a coord-BOUND column must not)
p6 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Longitude"],
    ["Echo Park", "Leeds", 25000, "51.5, -0.12"],
])
rec6 = X.detect_and_extract(p6)["records"][0]
check("short-pair-lat", rec6.get("lat") == 51.5)
check("short-pair-lng", rec6.get("lng") == -0.12)

# 7) header token order decides assignment: a lng-first 'Long Lat' column with a
#    lng-first cell must NOT ship a Gulf-of-Guinea pin
p7 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Long Lat"],
    ["Foxtrot Park", "Corby", 28000, "-0.652005, 52.480401"],
])
rec7 = X.detect_and_extract(p7)["records"][0]
check("lngfirst-lat", rec7.get("lat") == 52.480401)
check("lngfirst-lng", rec7.get("lng") == -0.652005)

# 8) magnitude disambiguation: |value| > 90 can only be the longitude, whatever
#    order the pair arrived in
p8 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Lat Long"],
    ["Golf Park", "Milan", 31000, "120.5, 51.2"],
])
rec8 = X.detect_and_extract(p8)["records"][0]
check("magswap-lat", rec8.get("lat") == 51.2)
check("magswap-lng", rec8.get("lng") == 120.5)

# 9) a European decimal-comma SINGLE value is never split into a false pair
check("no-false-pair", X._split_bound_pair("52,480401") is None)

print("LATLONG COMBINED TEST: PASS")
