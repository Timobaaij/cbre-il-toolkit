#!/usr/bin/env python3
"""seed_geocode.py - pre-fill the work-dir geocode cache from coordinates the
ORCHESTRATOR fetched online (WebFetch / WebSearch).

For sandboxes where the Python helpers have NO outbound network but the
orchestrator's web tools DO (e.g. Cowork): do the geocoding with your tools, then
hand the results to the deterministic pipeline via the work-dir cache - the same
pattern region research uses to write regions_cache.json. Honest: these are real
geocoder results, just fetched by the orchestrator instead of by the sandboxed
script (so they are NOT model estimates).

Input JSON: a list of objects, each
    {"city": "<name>", "country": "<ISO-2, optional>", "lat": <float>, "lng": <float>, "cc": "<ISO-2, optional>"}
(or {"coords": [ ... ]}). Writes/merges <cache-dir>/geocode_cache.json in the exact
format enrich.py reads; then run `enrich.py --geocode --cache-dir <work>` with NO
network to fill coordinates (and the country from cc).

    python seed_geocode.py coords.json --cache-dir <work>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("coords", help="JSON list of {city, country?, lat, lng, cc?}")
    ap.add_argument("--cache-dir", required=True, help="work dir (where geocode_cache.json lives)")
    args = ap.parse_args()

    data = json.loads(Path(args.coords).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("coords", [])
    cache_path = Path(args.cache_dir) / "geocode_cache.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    n = 0
    for r in data:
        city = str(r.get("city", "")).strip()
        country = str(r.get("country", "") or "").strip()
        lat, lng = r.get("lat"), r.get("lng")
        cc = str(r.get("cc", country) or "").upper()
        if city and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            cache[f"{city}|{country}".lower()] = {"latlng": [float(lat), float(lng)], "cc": cc}
            n += 1

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK seeded {n} geocode entries -> {cache_path}")


if __name__ == "__main__":
    main()
