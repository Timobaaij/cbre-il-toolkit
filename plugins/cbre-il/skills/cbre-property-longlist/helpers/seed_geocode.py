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
    {"city": "<name>", "country": "<ISO-2, optional>", "lat": <float>, "lng": <float>,
     "cc": "<ISO-2, optional>", "postcode": "<optional - see below>"}
(or {"coords": [ ... ]}). Writes/merges <cache-dir>/geocode_cache.json in the exact
format enrich.py reads; then re-run the SAME run.py command (or `enrich.py --geocode
--cache-dir <work>` directly) with NO network to fill coordinates (and the country from cc).

    python seed_geocode.py coords.json --cache-dir <work>

WHAT A SEEDED ROW DOES ON THE NEXT PLAIN RE-RUN (D10). Two things, depending on the row:

  * A row WITHOUT `postcode` lands on the CITY key `city|country`, exactly as every seed
    file written before the option existed. It FILLS a property that has no coordinate yet.
    It does NOT move a pin that already exists, approximate or not: a city-level seed is a
    town-level answer, the same level as the pin it would replace, so there is nothing finer
    to prefer. To move an existing pin, use a row that carries the postcode (below) or
    record the coordinate in work/repairs.json.

  * A row WITH `postcode` lands on the LOCALITY key `city|country|code`, which
    `enrich._cache_lookup` prefers for the properties that state that same code. It fills
    an empty coordinate, and it also DISPLACES an existing pin flagged `coordsApprox: true`
    (a town centroid the pipeline itself wrote): `enrich.geocode` prints one line per
    property naming the old pin, the new one and the distance, so two options in ONE town
    hold two DIFFERENT pins after a plain re-run. A coordinate the SOURCE stated
    (`coordsApprox` false or absent) is never moved; the run prints a NOTE saying so and
    points at work/repairs.json. Until D10 the seed filled ONLY an empty coordinate, so on
    any warm work dir it silently did nothing and it took an undocumented `--no-resume
    --from merge` to make it land. That re-entry is no longer needed.

  Either way run.py re-runs enrichment on its own: the seed makes geocode_cache.json newer
  than the enrichment stamp, which is one of the stamp's invalidators. The ONE case that
  still needs anything is a run that puts enrichment out of scope itself (`--only` /
  `--from` past the stage, or `enrichment.geocode` off in project.yaml): the seed is then
  read on the next run that includes the stage, not before.

The code is normalised by `enrich._locality_code` (whitespace removed, upper-cased, NO
country-specific parsing - equality of the whole normalised string is the only comparison
that means the same thing in every format), on the seed row and on the record alike, so
"QX41 7ZP" in a row matches "qx417zp" in a tracker cell and this works in any market or in
none. `city` and `country` must match what the record carries in canonical.json (the key
is built from both), which is the same rule the city-level seed always had.

WHY THIS FILE RATHER THAN A GEOCODER PLUGIN. The finer coordinate has to come from
somewhere, and every helper in this sandbox may have no network at all. This is the
skill's established seam for exactly that: the ORCHESTRATOR (or the operator) fetches
real geocoder results with whatever tool it has, and the deterministic pipeline consumes
them from the work dir - the same pattern region research uses for regions_cache.json and
web_enrich.py uses for its browser bundle. It is off by default (an unseeded cache
contributes nothing), it is configured per project rather than hardcoded, and it adds NO
network dependency to the default path. Nothing here is a model estimate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich as E  # noqa: E402  the ONE place the cache key shape and the code
#                                 normalisation are decided; a private copy here would
#                                 drift from the reader and silently split a town cache


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

    n = n_loc = 0
    for r in data:
        city = str(r.get("city", "")).strip()
        country = str(r.get("country", "") or "").strip()
        lat, lng = r.get("lat"), r.get("lng")
        cc = str(r.get("cc", country) or "").upper()
        # a row with no postcode (the ordinary case) yields "" and lands on the CITY key,
        # byte-identical to every seed file written before this option existed
        code = E._locality_code(r)
        if city and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            cache[E._geo_key(city, country, code)] = {"latlng": [float(lat), float(lng)],
                                                      "cc": cc}
            n += 1
            n_loc += 1 if code else 0

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK seeded {n} geocode entries ({n_loc} at locality level, {n - n_loc} at city "
          f"level) -> {cache_path}")


if __name__ == "__main__":
    main()
