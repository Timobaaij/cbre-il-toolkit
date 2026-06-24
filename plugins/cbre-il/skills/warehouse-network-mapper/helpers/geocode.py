#!/usr/bin/env python3
"""Stage 4: assign lat/long to facility records IN CODE, offline.

This runs inside the Cowork sandbox, which has NO outbound internet, so there
are no live geocoder calls here. Coordinates still never come from a model.
They come from one of two real sources:

  1. An offline city-centroid gazetteer (gazetteer.json), keyed on
     (country, city).                                     -> precision "city"
  2. coordinates.json handed back by geocode.html, which the USER opens in
     their own browser (which does have internet) to geocode addresses at
     street/rooftop precision via a real geocoder.        -> precision "street"/"rooftop"

Anything neither layer resolves is left as "tbd". Nothing is guessed.

Typical Cowork flow:
  # baseline, instant, no internet:
  python geocode.py --in records.json --out records_geocoded.json
  # optional precision upgrade, after the user runs geocode.html in a browser:
  python geocode.py --in records_geocoded.json --merge-coords coordinates.json \
                    --out records_geocoded.json

The merge join key is the record's array index in --in, which geocode.html
preserves, so the two files must derive from the same records list.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import TBD, is_number, load_records, save_records, strip_accents  # noqa: E402

# Higher rank wins when merging browser coords over the gazetteer baseline.
_PRECISION_RANK = {"tbd": 0, "city": 1, "street": 2, "rooftop": 3}


def gazetteer_lookup(gaz: dict[str, Any], country: str, city: str) -> dict[str, Any] | None:
    c = strip_accents((country or "").strip().lower())
    t = strip_accents((city or "").strip().lower())
    if not t:
        return None
    cities = gaz.get(c)
    if not isinstance(cities, dict):
        return None
    coord = cities.get(t)
    if not coord:  # loose contains match, e.g. "Greater Warsaw" -> "warsaw"
        for name, xy in cities.items():
            if name.startswith("_"):
                continue
            if name in t or t in name:
                coord = xy
                break
    if not coord:
        return None
    return {"lat": coord[0], "long": coord[1], "precision": "city"}


def _load_merge(path: str) -> dict[int, dict[str, Any]]:
    """coordinates.json -> {record_index: {lat, long, precision}} for resolved rows."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw["coordinates"] if isinstance(raw, dict) and "coordinates" in raw else raw
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        idx = row.get("i", row.get("index"))
        lat = row.get("lat")
        lon = row.get("long", row.get("lon"))
        prec = (row.get("precision") or "tbd").lower()
        if idx is None or not is_number(lat) or not is_number(lon):
            continue  # unresolved rows stay on the gazetteer baseline
        if prec not in _PRECISION_RANK:
            prec = "street"
        out[int(idx)] = {"lat": round(float(lat), 6),
                         "long": round(float(lon), 6),
                         "precision": prec}
    return out


def run(args: argparse.Namespace) -> int:
    records = load_records(args.infile)
    gaz = json.loads(Path(args.gazetteer).read_text(encoding="utf-8"))
    merge = _load_merge(args.merge_coords) if args.merge_coords else {}

    counts = {"rooftop": 0, "street": 0, "city": 0, "tbd": 0}
    upgraded = 0

    for i, rec in enumerate(records):
        # Start from whatever the record already has (so re-runs are stable).
        cur_prec = (rec.get("geocode_precision") or "tbd").lower()
        if cur_prec not in _PRECISION_RANK or not is_number(rec.get("lat")):
            cur_prec = "tbd"

        # Layer 1: gazetteer baseline (only if we have nothing better yet).
        if cur_prec == "tbd":
            g = gazetteer_lookup(gaz, rec.get("country", ""), rec.get("city", ""))
            if g:
                rec["lat"], rec["long"], rec["geocode_precision"] = (
                    g["lat"], g["long"], "city")
                cur_prec = "city"

        # Layer 2: browser-geocoded coords, if they are more precise.
        m = merge.get(i)
        if m and _PRECISION_RANK[m["precision"]] > _PRECISION_RANK[cur_prec]:
            rec["lat"], rec["long"], rec["geocode_precision"] = (
                m["lat"], m["long"], m["precision"])
            cur_prec = m["precision"]
            upgraded += 1

        if cur_prec == "tbd":
            rec["lat"], rec["long"], rec["geocode_precision"] = TBD, TBD, TBD
        counts[cur_prec] += 1

    save_records(args.out, records)
    print(f"Geocoded {len(records)} records -> {args.out}")
    print(f"  rooftop={counts['rooftop']}  street={counts['street']}  "
          f"city={counts['city']}  tbd={counts['tbd']}")
    if merge:
        print(f"  merged {upgraded} street/rooftop coordinate(s) from "
              f"{args.merge_coords}")
    if counts["tbd"]:
        print(f"  {counts['tbd']} record(s) left tbd (no city match, no browser "
              "coordinate). Real gaps, surfaced in the Coverage and Gaps sheet.")
    if counts["city"] and not merge:
        print("  Tip: for street-level pins, run make_geocoder_html.py, have the "
              "user open geocode.html in a browser, then re-run with --merge-coords.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Assign coordinates offline, never modelled.")
    p.add_argument("--in", dest="infile", required=True, help="input records JSON")
    p.add_argument("--out", required=True, help="output geocoded records JSON")
    p.add_argument("--gazetteer",
                   default=str(Path(__file__).resolve().parent / "gazetteer.json"))
    p.add_argument("--merge-coords", dest="merge_coords", default="",
                   help="coordinates.json from geocode.html (browser geocoding)")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
