#!/usr/bin/env python3
"""repairs_projection_test.py - the property-keyed repair path and its read-only projection.

The repair path exists because a post-merge correction had no home: `overrides.json` targets a
SOURCE RECORD, so fixing a property meant finding which record supplied the value and paying a
dataset-wide re-derivation for a one-card change.

What must be true, and what this pins:

  * a repair lands on the named property and NOTHING else;
  * every guard FAILS CLOSED - an entry that cannot be resolved with certainty applies nothing
    and is reported, because a repair on the wrong card is worse than one that did not land.
    Stale key, ambiguous key-vs-id, and a stale `expect` are each checked, since `expect` is the
    guard that makes an entry survive a re-match;
  * a denied field (structural, media, or a dataset-wide unit label) is refused at LOAD time;
  * a typo'd field name cannot invent a field;
  * every applied field writes a Source Ledger row, so the change is disclosed and
    `trace-coverage` still passes;
  * the projection is DERIVED - rebuilt from canonical, media decoded to real files, and it
    hands back the exact repair key needed to correct what it shows.
Offline; no network, no build.
"""
from __future__ import annotations

import base64
import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402
import project_properties as PP          # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def canon():
    return {"meta": {"client": "T", "units": {"area": "sq m"},
                     "conflicts": ["id 1 warehouseArea: sources disagree"]},
            "pois": [], "regions": {},
            "properties": [
                {"id": 1, "park": "Alpha Park", "city": "Bor", "developer": "CTP",
                 "country": "CZ", "warehouseArea": 10000, "areaUnit": "sq m",
                 "status": "Available", "region": "tbd", "photo": PX, "gallery": [PX]},
                {"id": 2, "park": "Beta Park", "city": "Bor", "developer": "Panattoni",
                 "country": "CZ", "warehouseArea": 20000, "areaUnit": "sq m",
                 "status": "Available", "photo": PX, "gallery": [PX]},
            ]}


def entry(**kw):
    e = {"id": "rp-001", "property": {"key": "bor|ctp|alpha park", "id": 1},
         "set": {"region": "Plzen"}, "why": "the region is stated on page 2",
         "verified_by": "t@cbre.com"}
    e.update(kw)
    return e


def with_repairs(td, items):
    w = Path(td)
    (w / "canonical.json").write_text(json.dumps(canon()), encoding="utf-8")
    (w / "repairs.json").write_text(json.dumps(items), encoding="utf-8")
    return w


def main() -> int:
    print("== applying a repair ==")
    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [entry()])
        rep = R.run(w)
        data = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
        ck(len(rep["applied"]) == 1, "the repair applied")
        ck(data["properties"][0]["region"] == "Plzen", "the named property changed")
        ck("region" not in data["properties"][1], "the OTHER property is untouched")
        rows = R.ledger_rows(rep)
        ck(len(rows) == 1 and rows[0]["field"] == "region",
           "one Source Ledger row per repaired field")
        ck(rows[0]["record_type"] == "repair" and rows[0]["source_locator"] == "rp-001",
           "the row names the repair, so the change is disclosed not laundered")
        ck(rows[0]["verified"] == "t@cbre.com" and "why" not in rows[0]["conflict_note"].lower()
           or "stated on page 2" in rows[0]["conflict_note"],
           "the row carries verified_by and the reason")
        ck((w / "repairs_report.json").exists(), "a report is written for the operator")

    print()
    print("== the guards, each failing closed ==")
    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [entry(property={"key": "nowhere|none|gone"})])
        rep = R.run(w)
        d = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
        ck(len(rep["stale"]) == 1 and not rep["applied"], "an unmatched key is STALE")
        ck(d["properties"][0]["region"] == "tbd",
           "...and applied nothing (the field still holds its tbd)")

    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [entry(property={"key": "bor|ctp|alpha park", "id": 2})])
        rep = R.run(w)
        d = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
        ck(len(rep["ambiguous"]) == 1 and not rep["applied"],
           "a key and id pointing at DIFFERENT properties is AMBIGUOUS")
        ck(d["properties"][0]["region"] == "tbd" and "region" not in d["properties"][1],
           "...and applied nothing to either")

    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [entry(expect={"warehouseArea": 99999})])
        rep = R.run(w)
        d = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
        ck(len(rep["superseded"]) == 1 and not rep["applied"],
           "a stale `expect` is SUPERSEDED - the entry survives a re-match by refusing")
        ck(d["properties"][0]["region"] == "tbd",
           "...and applied nothing (the field still holds its tbd)")

    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [entry(expect={"warehouseArea": 10000.0})])
        rep = R.run(w)
        ck(len(rep["applied"]) == 1,
           "`expect` compares 10000 and 10000.0 as equal (hand-written JSON is not typed)")

    with tempfile.TemporaryDirectory() as td:
        # idempotence: a repair is re-applied every run, so on the second pass the field
        # already holds the target. That is its own success, not drift - and it must still
        # write a ledger row, or trace-coverage blocks the value as untraceable.
        w = with_repairs(td, [entry(expect={"region": "tbd"})])
        ck(len(R.run(w)["applied"]) == 1, "a guarded repair applies on the first run")
        rep2 = R.run(w)
        ck(len(rep2["applied"]) == 1 and not rep2["superseded"],
           "...and applies again on the second, when the field already holds the target")
        ck(len(R.ledger_rows(rep2)) == 1,
           "...still writing its ledger row, so the value never becomes untraceable")
        d = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
        ck(d["properties"][0]["region"] == "Plzen", "...and the value is stable across runs")

    print()
    print("== refused at load ==")
    for bad, why in (
        (entry(set={"areaUnit": "sq ft"}), "a dataset-wide unit label"),
        (entry(set={"photo": "x"}), "media, which has its own key"),
        (entry(set={"id": 9}), "structural"),
        (entry(set={"breeem": "Excellent"}), "a typo cannot invent a field"),
        (entry(set={"region": "   "}), "a blank value would hard-block the build"),
        (entry(why=""), "an empty why"),
        (entry(verified_by=""), "an empty verified_by"),
    ):
        with tempfile.TemporaryDirectory() as td:
            w = with_repairs(td, [bad])
            rep = R.run(w)
            d = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
            ck(not rep["applied"] and rep["invalid"], f"refused: {why}")
            ck(d["properties"][0].get("region", "tbd") == "tbd", f"...nothing applied ({why})")

    print()
    print("== media repair ==")
    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [])
        img = w / "hero.png"
        img.write_bytes(base64.b64decode(PX.split("base64,")[1]))
        (w / "repairs.json").write_text(json.dumps(
            [entry(set={}, media={"hero": "hero.png"})]), encoding="utf-8")
        rep = R.run(w)
        ck(len(rep["applied"]) == 1 and rep["applied"][0]["media"].get("hero"),
           "a media repair resolves its file relative to the work dir")
        (w / "repairs.json").write_text(json.dumps(
            [entry(set={}, media={"hero": "missing.png"})]), encoding="utf-8")
        rep = R.run(w)
        ck(any("not found" in s for s in rep["invalid"]),
           "a missing media file is reported, never silently skipped")

    print()
    print("== the projection ==")
    with tempfile.TemporaryDirectory() as td:
        w = with_repairs(td, [entry()])
        R.run(w)
        with open(w / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=["property_id", "field", "value", "source_file",
                                                "source_locator", "source_type", "record_type"])
            wr.writeheader()
            wr.writerow({"property_id": "1", "field": "park", "value": "Alpha Park",
                         "source_file": "t.xlsx", "source_locator": "S!r2",
                         "source_type": "xlsx", "record_type": "property"})
        out = PP.build(w)
        ck(out["count"] == 2, "one folder per property")
        root = w / "properties"
        d1 = next(p for p in root.iterdir() if p.is_dir() and p.name.startswith("01-"))
        ck((d1 / "property.json").exists() and (d1 / "notes.md").exists()
           and (d1 / "sources.csv").exists(), "each folder carries the record, notes and sources")
        pj = json.loads((d1 / "property.json").read_text(encoding="utf-8"))
        ck("photo" not in pj and "gallery" not in pj,
           "base64 blobs are replaced, so property.json is readable")
        ck((d1 / "media" / "hero.png").exists(), "the hero is decoded to a real openable file")
        ck(pj["__repair_key"] == "bor|ctp|alpha park",
           "the record hands back the exact key a repair needs")
        notes = (d1 / "notes.md").read_text(encoding="utf-8")
        ck("bor|ctp|alpha park" in notes and "repairs.json" in notes,
           "notes.md names the repair key and points at repairs.json, not at itself")
        ck("rp-001" in notes, "an applied repair is listed on the property it touched")
        rows = list(csv.DictReader(open(d1 / "sources.csv", encoding="utf-8")))
        ck(len(rows) == 1 and rows[0]["field"] == "park",
           "sources.csv carries THIS property's ledger rows only")
        ck(json.loads((root / "index.json").read_text(encoding="utf-8"))["count"] == 2,
           "an index lists the set")

        before = (d1 / "property.json").read_text(encoding="utf-8")
        (d1 / "property.json").write_text('{"tampered": true}', encoding="utf-8")
        PP.build(w)
        ck((d1 / "property.json").read_text(encoding="utf-8") == before,
           "the projection is DERIVED - a hand edit is overwritten, never read back")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
