#!/usr/bin/env python3
"""open_capture_xlsx_test.py - READ EVERYTHING, DISPLAY SELECTIVELY (tracker path).

The xlsx extractor used to be a CLOSED schema: a populated column the dictionary
could not map was dropped wholesale, with a yield-report line as its only trace.
On a live run that let a second-hand unit ship described as a BTS - the tracker's
'Type of build' column plainly said otherwise but never entered the dataset.

Contract pinned here:
  1. common columns gain first-class homes (address, postcode, buildType, description);
  2. every other populated-but-unbound column is READ - a top-level scalar (data,
     auto-shows on the dashboard detail view) or __meta.open_capture (commentary,
     denied/colliding keys, CJK-only headers - never client-shown);
  3. only ordinals and link-text stubs are skipped, and every column lands in a
     named header_report bucket - unmapped_headers (NOT READ) must be empty.
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


p = _write([
    ["No.", "Address", "Town（城镇）", "Postcode", "Total Size (sq m)",
     "Type of build建筑类型", "Cross Dock?是否有交叉码头", "24/7",
     "Total No. Doors总计数量", "Comments", "Map地图", "备注", "Landlord房东"],
    [1, "100 Example Road", "Northampton", "NN17 3JG", 61262,
     "Second hand", "Yes", "Yes", 75, "internal note text", "Map", "flagged",
     "Acme REIT"],
])
res = X.detect_and_extract(p)
rec = res["records"][0]

# 1) new first-class homes
check("address", rec.get("address") == "100 Example Road")
check("postcode", rec.get("postcode") == "NN17 3JG")
check("buildtype", rec.get("buildType") == "Second hand")

# 2) open capture: data columns become top-level scalars under derived keys
check("crossdock", rec.get("crossDock") == "Yes")
check("c247", rec.get("c247") == "Yes")
check("totaldoors", str(rec.get("totalNoDoors")) == "75")

# 3) commentary is read but NOT client-shown (top-level prints on the card modal)
check("comments-not-toplevel", "comments" not in rec)
oc = rec.get("__meta", {}).get("open_capture", [])
check("comments-in-meta", any(e.get("column") == "Comments"
                              and e.get("value") == "internal note text" for e in oc))
check("cjk-in-meta", any(e.get("column") == "备注" and e.get("value") == "flagged"
                         for e in oc))

# 4) provenance rows exist for the top-level captures (ledger-traceable)
prov = rec.get("__meta", {}).get("prov", {})
check("prov-crossdock", "open capture" in str(prov.get("crossDock", "")))
check("prov-buildtype", prov.get("buildType", "") != "")

# 5) header_report buckets: nothing is silently unread
hr = next(h for h in res["header_report"] if h.get("populated_columns"))
check("no-unread", hr.get("unmapped_headers") == [])
check("skip-ordinal", any(s.startswith("No.") for s in hr.get("skipped_headers", [])))
check("skip-map-stub", any(s.startswith("Map") for s in hr.get("skipped_headers", [])))
check("meta-bucket", any(s.startswith("Comments") for s in hr.get("meta_captured_headers", [])))
check("open-bucket", any(s.startswith("Cross Dock") for s in hr.get("open_captured_headers", [])))

# 6) a mapped field is never overwritten by an open key (Landlord stays landlord)
check("landlord", rec.get("landlord") == "Acme REIT")

# 7) a HEADERLESS column with data is still read (to __meta, labelled by its
#    column letter) - the one shape the old accounting could not even see
p7 = _write([
    ["Property", "City", "Warehouse Area (sq m)", None],
    ["Hotel Park", "Leeds", 20000, "orphan data"],
])
res7 = X.detect_and_extract(p7)
rec7 = res7["records"][0]
oc7 = rec7.get("__meta", {}).get("open_capture", [])
check("headerless-read", any(e.get("value") == "orphan data" for e in oc7))
hr7 = next(h for h in res7["header_report"] if h.get("populated_columns"))
check("headerless-bucket", any("no header" in s for s in hr7.get("meta_captured_headers", [])))

# 8) non-English commentary stays off the client surface (NL here; the regex
#    covers the skill's supported tracker languages)
p8 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Opmerkingen"],
    ["India Park", "Breda", 18000, "intern: niet delen met klant"],
])
rec8 = X.detect_and_extract(p8)["records"][0]
check("nl-commentary-not-toplevel", "opmerkingen" not in rec8)
check("nl-commentary-in-meta", any(e.get("value") == "intern: niet delen met klant"
                                   for e in rec8.get("__meta", {}).get("open_capture", [])))

# 9) a headed but EMPTY column is claimed by no bucket (a read that never
#    happened must not be reported as one)
p9 = _write([
    ["Property", "City", "Warehouse Area (sq m)", "Cross Dock?", "Empty Col"],
    ["Juliet Park", "York", 22000, "Yes", None],
])
hr9 = next(h for h in X.detect_and_extract(p9)["header_report"]
           if h.get("populated_columns"))
check("empty-col-unlisted", not any("Empty Col" in s for s in
                                    (hr9.get("open_captured_headers", [])
                                     + hr9.get("meta_captured_headers", [])
                                     + hr9.get("skipped_headers", []))))

print("OPEN CAPTURE XLSX TEST: PASS")
