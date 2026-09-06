#!/usr/bin/env python3
"""f24a_rederive_after_repairs_test.py - a repair to a source field re-derives its twin, and the
Source Ledger retracts the gap row the repair supersedes. (F24, contract C2, merge half)

WHAT WAS WRONG, twice. (1) `repairs` runs at stage 5, AFTER merge; `officeAreaVal` is declared
"derived by merge from officeArea" and nothing re-derived it, so on a live run the two properties
whose office area came from a repair carried None in the twin: the modal printed a raw unit-less
string and Total GLA silently excluded the office, with every gate green. The operator's
workaround was a hand-written second repair per property setting the twin itself. (2) Merge writes
a gap row ("tbd / absent in all sources / verified=no") for every unstated chrome-read field, the
repair appends a row with the value, and nothing retracts the gap row, so the ledger carried two
rows for each of five repaired fields and contradicted the dashboard on all of them.

THE FIX. `merge.DERIVED_TWINS` names every post-merge derivation a repair can change the input of;
`merge.rederive_after_repairs(canonical)` re-runs them and returns run-log lines; run.py calls it
right after the repairs stage. `merge.retract_superseded_gap_rows` MARKS (never deletes) a gap row
that a later row supersedes and RESTORES it when the superseder is gone.

WHAT THIS PINS:
  * the registry carries the full set found in merge.canonicalize (office area, office rent,
    expansion park, and the rent pair in both directions) and each twin is derived by the SAME
    function canonicalize uses (no second copy to drift);
  * an untouched canonical re-derives NOTHING (idempotent across passes, tolerant of a source's
    own rounding between two printed units);
  * a repaired officeArea fills a missing twin, refreshes a stale one, and a repair typed with a
    different unit is converted onto the dataset unit;
  * a withdrawal (the source repaired away) removes the twin ONLY when the repairs report says
    the source was repaired: a tracker-supplied twin with no source beside it is not staleness;
  * the rent pair takes direction from the report; without it a missing side is filled and two
    disagreeing sides are REPORTED, never clobbered;
  * the gap-row retraction is visible (record_type "superseded", a note naming the superseder),
    machine-invisible to every gap-row consumer (source_type stays "gap"), idempotent, and
    reversible when the superseding row disappears;
  * with the ledger path, a re-derived twin gets a provenance row copied from its basis row and
    marked derived, and a second pass does not stack a copy of it.
Offline; no build.
"""
from __future__ import annotations

import copy
import csv
import inspect
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402
import ledger as L  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def canon(*props):
    base = {"country": "GB", "developer": "Dev", "city": "Sometown", "park": "Alpha Park",
            "areaUnit": "sq ft", "rentUnit": "£/sq ft/yr"}
    return {"meta": {}, "properties": [dict(base, **p) for p in props], "pois": [], "regions": {}}


def prop(c, pid):
    return next(p for p in c["properties"] if p["id"] == pid)


def gap_row(pid, field):
    return {"property_id": str(pid), "record_type": "property", "field": field, "value": "tbd",
            "source_file": "(none)", "source_locator": "absent in all sources", "source_type": "gap",
            "extractor": "", "confidence": "", "conflict_note": "", "verified": "no"}


def repair_row(pid, field, value, rid="rp-001"):
    return {"property_id": str(pid), "record_type": "repair", "field": field, "value": str(value),
            "source_file": "repairs.json", "source_locator": rid, "source_type": "repair",
            "extractor": "repairs.py", "confidence": "verified", "conflict_note": f"repair {rid}",
            "verified": "t@cbre.com"}


def pdf_row(pid, field, value):
    return {"property_id": str(pid), "record_type": "property", "field": field, "value": str(value),
            "source_file": "deck.pdf", "source_locator": "page 2", "source_type": "pdf",
            "extractor": "E-pdf", "confidence": "high", "conflict_note": "", "verified": ""}


def write_ledger(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=L.COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    print("f24a_rederive_after_repairs_test - the derived twins follow their repaired source")

    print("== the registry ==")
    ck(M.DERIVED_TWINS.get("officeArea") == "officeAreaVal", "officeArea -> officeAreaVal (the contract's example)")
    ck(M.DERIVED_TWINS.get("officeRent") == "officeRentVal", "officeRent -> officeRentVal")
    ck(M.DERIVED_TWINS.get("expansionPark") == "expansionParkVal", "expansionPark -> expansionParkVal")
    ck(M.DERIVED_TWINS.get("warehouseRentVal") == "warehouseRent"
       and M.DERIVED_TWINS.get("warehouseRent") == "warehouseRentVal",
       "the rent pair is registered in BOTH directions (canonicalize derives whichever side is missing)")
    src = inspect.getsource(M.canonicalize)
    ck(all(fn in src for fn in ("_office_area_val_from", "_office_rent_val_from",
                                "_expansion_park_val_from", "_rent_pair_from_display")),
       "canonicalize derives through the same four functions the re-derivation calls (one copy)")
    ck(inspect.signature(M.rederive_after_repairs).parameters["canonical"].default is inspect._empty
       and callable(M.rederive_after_repairs), "rederive_after_repairs(canonical) is the entry point B1 calls")

    print("== an untouched canonical re-derives nothing ==")
    c = canon({"id": 1, "warehouseArea": 318826, "officeArea": "1,413 sq m", "officeAreaVal": 15213.0,
               "warehouseRent": "£9.5 / sq ft / year", "warehouseRentVal": 9.5,
               "officeRent": "£12.00 psf", "officeRentVal": 12.0,
               "expansionPark": "50,000 sq ft", "expansionParkVal": 50000.0,
               "motorway": "M1 J19 2 miles"})
    before = copy.deepcopy(c)
    lines = M.rederive_after_repairs(c)
    ck(lines == [] and c == before, f"no lines, no bytes moved on an untouched property ({lines})")
    ck(M.rederive_after_repairs(c, changed={}) == [], "same with an empty repairs hint")

    print("== the live defect: a repaired officeArea and a missing / stale twin ==")
    c = canon({"id": 2, "warehouseArea": 362746, "officeArea": "24513"},
              {"id": 7, "warehouseArea": 318826, "officeArea": 19482, "officeAreaVal": 15213.0})
    lines = M.rederive_after_repairs(c)
    ck(prop(c, 2)["officeAreaVal"] == 24513.0, "a missing twin is FILLED from the repaired string value")
    ck(prop(c, 7)["officeAreaVal"] == 19482.0, "a stale twin is REFRESHED from the repaired numeric value")
    ck(len(lines) == 2 and all("officeAreaVal" in x for x in lines) and any("24513" in x for x in lines),
       f"one run-log line per re-derivation, naming field, value and source ({lines})")
    c = canon({"id": 7, "warehouseArea": 318826, "officeArea": "1,413 sq m", "officeAreaVal": 19482.0})
    M.rederive_after_repairs(c, changed={"7": {"officeArea"}})
    ck(prop(c, 7)["officeAreaVal"] == 15209.0,
       "a repair typed in sq m into a sq ft dataset is CONVERTED onto the dataset unit (1,413 sq m -> 15,209)")

    print("== withdrawal needs the report ==")
    c = canon({"id": 4, "warehouseArea": 734636, "officeAreaVal": 37981.0})
    M.rederive_after_repairs(c)
    ck(prop(c, 4).get("officeAreaVal") == 37981.0,
       "no report: a twin with no source beside it is LEFT (a tracker can supply the twin alone)")
    lines = M.rederive_after_repairs(c, changed={"4": {"officeArea"}})
    ck("officeAreaVal" not in prop(c, 4) and any("withdrawn" in x for x in lines),
       "report says officeArea was repaired away: the stale twin is withdrawn and said")

    print("== the other one-way twins ==")
    c = canon({"id": 5, "officeRent": "£12.50 psf", "expansionPark": "80,000 sq ft"})
    M.rederive_after_repairs(c)
    ck(prop(c, 5).get("officeRentVal") == 12.5, "officeRentVal parsed from a repaired officeRent")
    ck(prop(c, 5).get("expansionParkVal") == 80000.0, "expansionParkVal parsed from a repaired expansionPark")

    print("== the rent pair ==")
    c = canon({"id": 6, "warehouseRent": "£9.50 psf", "warehouseRentVal": None})
    M.rederive_after_repairs(c)
    ck(prop(c, 6)["warehouseRentVal"] == 9.5 and prop(c, 6)["warehouseRent"] == M.N.rent_display(9.5, "£/sq ft/yr"),
       "display only: the numeric is parsed and the display regenerated in the house form")
    c = canon({"id": 6, "warehouseRentVal": 8.0})
    M.rederive_after_repairs(c)
    ck(prop(c, 6)["warehouseRent"] == M.N.rent_display(8.0, "£/sq ft/yr"),
       "numeric only: the display is regenerated")
    c = canon({"id": 6, "warehouseRent": "£9.50 psf", "warehouseRentVal": 7.0})
    before = copy.deepcopy(c)
    lines = M.rederive_after_repairs(c)
    ck(c == before and any("INCONSISTENT" in x for x in lines),
       "both present and disagreeing, no report: REPORTED, nothing clobbered")
    M.rederive_after_repairs(c, changed={"6": {"warehouseRent"}})
    ck(prop(c, 6)["warehouseRentVal"] == 9.5, "report says the DISPLAY was repaired: the numeric follows it")
    c = canon({"id": 6, "warehouseRent": "£9.50 psf", "warehouseRentVal": 7.0})
    M.rederive_after_repairs(c, changed={"6": {"warehouseRentVal"}})
    ck(prop(c, 6)["warehouseRent"] == M.N.rent_display(7.0, "£/sq ft/yr"),
       "report says the NUMERIC was repaired: the display follows it (canonicalize's own rule)")

    print("== in-place normalisations a repair can undo ==")
    c = canon({"id": 8})
    prop(c, 8)["country"] = "United Kingdom"
    lines = M.rederive_after_repairs(c)
    ck(prop(c, 8)["country"] == "GB" and any("country" in x for x in lines), "a repaired country name becomes its ISO code")

    print("== repaired_fields reads the report, never infers ==")
    rep = {"applied": [{"property_id": 2, "changed": {"officeArea": {"from": None, "to": 24513}}},
                       {"property_id": "7", "changed": {"officeArea": {}, "unit": {}}}], "stale": []}
    ck(M.repaired_fields(rep) == {"2": {"officeArea"}, "7": {"officeArea", "unit"}},
       "string-keyed property ids, the changed field names")
    ck(M.repaired_fields(None) == {} and M.repaired_fields({"applied": "junk"}) == {},
       "any other shape yields {}")

    print("== the Source Ledger: gap rows are RETRACTED, visibly ==")
    rows = [gap_row(2, "officeArea"), pdf_row(2, "warehouseArea", 362746), gap_row(2, "officeRent"),
            repair_row(2, "officeArea", 24513, "rp-office-02"), gap_row(3, "region")]
    lines = M.retract_superseded_gap_rows(rows)
    sup = [r for r in rows if r["record_type"] == "superseded"]
    ck(len(sup) == 1 and sup[0]["field"] == "officeArea" and len(lines) == 1,
       "exactly the gap row a repair superseded is marked; the other gap rows are untouched")
    ck(sup[0]["source_type"] == "gap" and sup[0]["value"] == "tbd",
       "source_type stays 'gap' and the value stays the sentinel: invisible to every gap-row consumer")
    ck(sup[0]["conflict_note"].startswith("SUPERSEDED:") and "rp-office-02" in sup[0]["conflict_note"]
       and "24513" in sup[0]["conflict_note"], "the note names the superseding row and its value")
    ck(M.retract_superseded_gap_rows(rows) == [], "idempotent: a second pass moves nothing")
    rows = [r for r in rows if r["record_type"] != "repair"]
    lines = M.retract_superseded_gap_rows(rows)
    back = [r for r in rows if r["field"] == "officeArea"][0]
    ck(back["record_type"] == "property" and back["conflict_note"] == "" and any("RESTORED" in x for x in lines),
       "reversible: the repair gone, the gap row is RESTORED and the restoration is said")

    print("== end to end with a ledger path: twin rows written once, gap row retracted ==")
    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "source_ledger.csv"
        write_ledger(lp, [gap_row(2, "officeArea"), pdf_row(2, "warehouseArea", 362746),
                          repair_row(2, "officeArea", 24513, "rp-office-02")])
        c = canon({"id": 2, "warehouseArea": 362746, "officeArea": "24513"})
        lines = M.rederive_after_repairs(c, changed={"2": {"officeArea"}}, ledger=lp)
        got = list(csv.DictReader(open(lp, newline="", encoding="utf-8")))
        drow = [r for r in got if r["field"] == "officeAreaVal"]
        ck(len(drow) == 1 and drow[0]["record_type"] == "derived" and drow[0]["source_type"] == "repair"
           and "rp-office-02" in drow[0]["source_locator"] and "derived from officeArea" in drow[0]["source_locator"]
           and drow[0]["verified"] == "t@cbre.com",
           "the twin's provenance row is copied from its basis (the repair row) and marked derived")
        ck([r for r in got if r["field"] == "officeArea" and r["source_type"] == "gap"][0]["record_type"] == "superseded",
           "and the gap row is retracted in the same call")
        ck(list(got[0].keys()) == L.COLUMNS, "the ledger keeps ledger.COLUMNS order")
        M.rederive_after_repairs(c, changed={"2": {"officeArea"}}, ledger=lp)
        got2 = list(csv.DictReader(open(lp, newline="", encoding="utf-8")))
        ck(len([r for r in got2 if r["field"] == "officeAreaVal"]) == 1 and len(got2) == len(got),
           "a second pass does not stack a second derived row")
        raw = lp.read_bytes()
        ck(b"\r" not in raw, "written LF, as merge's own ledger write is")

    print()
    if FAILS:
        print(f"F24A REDERIVE AFTER REPAIRS TEST: FAIL ({len(FAILS)})")
        return 1
    print("F24A REDERIVE AFTER REPAIRS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
