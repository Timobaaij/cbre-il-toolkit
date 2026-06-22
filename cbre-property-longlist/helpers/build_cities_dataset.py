#!/usr/bin/env python3
"""build_cities_dataset.py - normalise a GeoNames cities dump into assets/cities_dataset.json.

THE STRUCTURAL IDEA (same as poi_dataset / regions_dataset): bundle a COMPLETE European
city gazetteer so resolving a city to its coordinates + country is a pure OFFLINE lookup -
the map works in Cowork with ZERO network round-trip, and the exit-8 browser handoff is
reserved strictly for live ROUTING. Org-maintainable: download a fresh GeoNames cities file
(https://download.geonames.org/export/dump/, e.g. cities5000.zip), unzip, re-run this, then
helpers/make_integrity.py.

Input: a GeoNames 'cities' tab-separated dump (cities500/1000/5000/15000.txt). Columns
(0-based): 1 name, 2 asciiname, 4 lat, 5 lng, 6 feature-class, 8 country-code, 14 population.
Only populated places (class 'P') in European countries are kept; coordinates are the city
centre (the property sits WITHIN the city, so the geocode is coordsApprox, exactly like the
Nominatim path it replaces offline).

CLI:
  python helpers/build_cities_dataset.py <cities.txt> [--out assets/cities_dataset.json] [--min-pop 0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import _norm_city as _norm  # ONE normaliser, shared with enrich (no drift)


def _write_gz(out: Path, text: str) -> Path:
    """Write `text` GZIPPED to <stem>.json.gz (the big datasets ship gzipped to keep the
    skill under the org upload-size cap; enrich._load_asset_json reads it). Drops a stale
    uncompressed sibling so the loader never picks up stale plain JSON. Returns the path."""
    import gzip
    if out.suffix == ".json":
        out = out.with_name(out.name + ".gz")
    out.write_bytes(gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0))
    plain = out.with_suffix("")
    if plain != out and plain.exists():
        plain.unlink()
    return out

# Europe = continental + UK & Ireland + micro-states (the skill's stated scope). ISO-2.
EUROPEAN_CC = {
    "AD", "AL", "AT", "BA", "BE", "BG", "BY", "CH", "CY", "CZ", "DE", "DK", "EE", "ES",
    "FI", "FO", "FR", "GB", "GG", "GI", "GR", "HR", "HU", "IE", "IM", "IS", "IT", "JE",
    "LI", "LT", "LU", "LV", "MC", "MD", "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO",
    "RS", "SE", "SI", "SK", "SM", "UA", "VA", "XK",
}


def build(src: Path, min_pop: int) -> dict:
    cities: dict[str, list] = {}   # "norm|cc" -> [lat, lng, pop]  (exact city+country)
    by_name: dict[str, dict] = {}  # "norm"    -> {"cc", "ll":[lat,lng], "_p":pop}  (pop-max fallback)
    kept = 0
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 15 or f[6] != "P":
                continue
            cc = f[8].strip().upper()
            if cc not in EUROPEAN_CC:
                continue
            try:
                lat, lng = round(float(f[4]), 4), round(float(f[5]), 4)
                pop = int(f[14] or 0)
            except Exception:
                continue
            if pop < min_pop:
                continue
            for nm in {_norm(f[1]), _norm(f[2])}:  # name + asciiname (diacritic variants)
                if not nm:
                    continue
                key = f"{nm}|{cc}"
                if key not in cities or pop > cities[key][2]:  # highest pop wins a collision
                    cities[key] = [lat, lng, pop]
                if nm not in by_name or pop > by_name[nm]["_p"]:
                    by_name[nm] = {"cc": cc, "ll": [lat, lng], "_p": pop}
            kept += 1
    cities = {k: v[:2] for k, v in cities.items()}  # drop the pop helper -> lean [lat,lng]
    for v in by_name.values():
        v.pop("_p", None)
    return {"version": 1, "source": f"GeoNames {src.stem} (CC-BY 4.0)",
            "count": kept, "cities": cities, "by_name": by_name}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="a GeoNames cities tab-separated dump (e.g. cities5000.txt)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "assets" / "cities_dataset.json"))
    ap.add_argument("--min-pop", type=int, default=0)
    args = ap.parse_args()
    ds = build(Path(args.src), args.min_pop)
    out = _write_gz(Path(args.out), json.dumps(ds, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {out}: {len(ds['cities'])} city|cc keys, {len(ds['by_name'])} unique "
          f"names from {ds['count']} European populated places ({ds['source']})")
    print("Now run: python helpers/make_integrity.py")


if __name__ == "__main__":
    main()
