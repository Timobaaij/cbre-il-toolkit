#!/usr/bin/env python3
"""build_cities_major_dataset.py - GeoNames cities dump -> assets/cities_major_dataset.json.gz.

COMPANION to build_cities_dataset.py. That builds the GEOCODING gazetteer (name->coords,
population dropped). THIS builds the "nearest city" POI LAYER: European cities with
population >= 100,000, each carrying country + population so the dashboard can show the
nearest major consumption centre. Like air/port/rail, nearest-of-complete-set IS the
genuine nearest - no far curated stand-in. Org-maintainable: download a fresh
cities15000.zip from https://download.geonames.org/export/dump/, unzip, re-run this, then
helpers/make_integrity.py.

Input: a GeoNames 'cities' tab-separated dump (cities15000.txt recommended - contains all
>=100k cities). Columns (0-based): 1 name, 2 asciiname, 4 lat, 5 lng, 6 feature-class,
8 country-code, 14 population. Only populated places (class 'P') in European countries
(the shared EUROPEAN_CC scope) with population >= --min-pop are kept.

CLI:
  python helpers/build_cities_major_dataset.py <cities15000.txt>
      [--out assets/cities_major_dataset.json] [--min-pop 100000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import _norm_city as _norm            # only for collision-dedupe keying (not stored)
from build_cities_dataset import EUROPEAN_CC, _write_gz  # ONE definition of Europe + gzip idiom

# GeoNames feature-CODES to exclude even within feature-class 'P': PPLX = a SECTION of a
# populated place (a city district / borough / numbered sector / arrondissement / kerület /
# circoscrizione) - not a city, so "nearest major city" must not resolve to a neighbourhood;
# plus non-current places (destroyed/abandoned/historical/religious). Genuine cities are
# PPL/PPLC/PPLA*/PPLG, which are kept.
_EXCLUDE_CODES = {"PPLX", "PPLW", "PPLQ", "PPLH", "PPLR", "PPLCH", "PPLDR"}


def build(src: Path, min_pop: int) -> dict:
    best: dict[str, dict] = {}  # "norm|cc" -> record (highest pop wins a same-place collision)
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 15 or f[6] != "P" or f[7] in _EXCLUDE_CODES:
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
            name = f[1].strip()
            key = f"{_norm(name)}|{cc}"
            if key not in best or pop > best[key]["population"]:
                best[key] = {"name": name, "type": "city", "lat": lat, "lng": lng,
                             "country": cc, "population": pop}
    cities = sorted(best.values(),
                    key=lambda r: (r["country"], -r["population"], r["name"]))
    return {"version": 1,
            "note": ("European cities with population >= %d (GeoNames %s, CC-BY 4.0). "
                     "Complete-coverage 'nearest city' POI layer; nearest-of-this-set IS "
                     "the genuine nearest. Rebuild: python helpers/build_cities_major_"
                     "dataset.py <cities15000.txt>; then helpers/make_integrity.py."
                     % (min_pop, src.stem)),
            "source": f"GeoNames {src.stem} (CC-BY 4.0)",
            "min_pop": min_pop, "count": len(cities), "cities": cities}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="a GeoNames cities dump (cities15000.txt recommended)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "assets" / "cities_major_dataset.json"))
    ap.add_argument("--min-pop", type=int, default=100000)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    ds = build(Path(args.src), args.min_pop)
    out = _write_gz(Path(args.out), json.dumps(ds, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {out}: {ds['count']} European cities pop>={args.min_pop} ({ds['source']})")
    print("Now run: python helpers/make_integrity.py")


if __name__ == "__main__":
    main()
