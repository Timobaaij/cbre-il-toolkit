#!/usr/bin/env python3
"""enrich.py - Stage 3. OPTIONAL, broker-opt-in enrichment of canonical.json.

  --geocode : fill missing lat/lng from the record's STATED POSTCODE where it states one
              (Nominatim structured query, cached at locality level - D9; for GB, a code
              Nominatim genuinely does not hold falls back to the ONS/Royal Mail national
              register at api.postcodes.io - D9b), else from the
              city (Nominatim, cached) - both with coordsApprox=true; also reverse-geocodes
              the country code from the result and fills an unknown ('??') country - so
              any geography works without a region-specific city index. Offline ->
              bundled gazetteer / POI-library city centroid. A locality-level answer may
              replace an approximate town pin on a warm work dir (D10); a coordinate the
              source itself stated is never moved. Needed for the map view.
  --pois    : discover the GENUINE nearest port/airport/rail/border/city to each
              located property live from OSM/Overpass (cached), replacing the
              merge-seeded library (which is only the offline fallback). A type
              with no real feature, or Overpass unreachable, is an honest gap.
  --osrm    : pre-bake drive distance/time from each property to each POI via the
              public OSRM API (rate-limited + cached) into preBaked.distances.
  --regions : merge a cited workforce/region profile cache (regions_cache.json)
              keyed by regionCode. The research itself is an isolated sub-agent
              (see SKILL.md) that writes the cache into the WORK dir; this merges it.

Caches (geocode / regions / POI-OSM) are seeded read-only in the skill's
reference/ dir but WRITTEN to the work dir (--cache-dir, default = the canonical's
folder), so a read-only install can still cache and be pre-filled per project.

Every enriched figure is sourced/dated or left absent - never invented. All
network steps degrade gracefully and log a gap rather than failing the run.

CLI:
  python enrich.py canonical.json [--geocode] [--pois] [--osrm] [--regions]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

# Caches are SEEDED (read-only) in the skill's reference/ dir and WRITTEN to the
# project's work dir, so a read-only skill install (e.g. Cowork) can still cache and
# be pre-filled per project. _load_cache merges seed + work (work wins); _save_cache
# writes the work copy only. main() points CACHE_DIR at the work dir.
SEED_DIR = C.SKILL_ROOT / "reference"
CACHE_DIR = SEED_DIR
GEOCODE_CACHE = "geocode_cache.json"
REGIONS_CACHE = "regions_cache.json"
POI_OSM_CACHE = "poi_osm_cache.json"
OSRM_CACHE = "osrm_cache.json"
UA = {"User-Agent": "cbre-property-longlist/1.0 (CBRE I&L internal tooling)"}
OSRM_WORKERS = 6  # bounded concurrency for the shared public OSRM server (polite, ~8x faster than serial)


def _load_cache(name: str) -> dict:
    """Merge the read-only seed cache (skill dir) with the project's writable cache
    (work dir); the project copy wins. Either may be absent."""
    out: dict = {}
    for d in (SEED_DIR, CACHE_DIR):
        f = Path(d) / name
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    out.update(data)
            except Exception:
                pass
    return out


def _save_cache(name: str, d: dict) -> None:
    """Write a cache to the PROJECT (work) dir - never the read-only skill dir.
    Atomic (tmp + replace) so a shell-cap kill mid-write cannot corrupt the cache."""
    import os
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    target = Path(CACHE_DIR) / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _coords_cc(val):
    """Read a geocode cache entry: new {'latlng':[lat,lng],'cc':'ES'} or legacy [lat,lng]."""
    if isinstance(val, dict):
        ll = val.get("latlng")
        return (ll if isinstance(ll, list) and len(ll) >= 2 else None, str(val.get("cc", "")).upper())
    if isinstance(val, list) and len(val) >= 2:
        return (val, "")
    return (None, "")


def _geo_key(city: str, country: str, code: str = "") -> str:
    """The geocode cache key, and the ONLY place its shape is decided. (G1)

    TWO LEVELS, distinguished by segment count:
      * CITY     'city|country'        - the shape every cache in the wild already has,
                                         including the read-only seed in reference/ and every
                                         key `web_enrich.py` writes.
      * LOCALITY 'city|country|code'   - the most specific locality the RECORD ITSELF states
                                         (`_locality_code`), appended as a THIRD segment.

    WHY THE CITY LEVEL IS A PREFIX OF THE LOCALITY LEVEL, rather than the code leading the
    key. `_cache_lookup_key`'s unknown-country fallback matches on 'city|', so a locality key
    that did not start with the city would drop straight out of that scan; a code-first key
    would additionally make every legacy entry unfindable. The shape therefore only ever GROWS
    to the RIGHT, and a reader that knows nothing about codes still resolves every key it
    always did. This is the KEY-side of the same tolerance `_coords_cc` already gives the
    VALUE, and it is deliberate rather than incidental: caches in the wild are city-keyed and
    a change that orphaned them would have silently re-geocoded every existing project.

    NO COUNTRY-SPECIFIC PARSING HAPPENS HERE. `code` arrives already normalised for equality
    by `_locality_code`; this function only lower-cases the whole key, exactly as the
    city-level key has always been lower-cased. `city` is deliberately NOT stripped, because
    the city-level key never was, and a cache written yesterday must still be found today."""
    base = f"{city}|{country}".lower()
    return f"{base}|{code}".lower() if code else base


def _key_code(k: str) -> str:
    """The LOCALITY segment of a cache key, or "" for a city-level key. Every key in every
    cache that exists today is city-level, so this returns "" for all of them - which is what
    makes `_cache_lookup_key`'s scan byte-identical on a cache that carries no codes."""
    parts = str(k).split("|", 2)
    return parts[2] if len(parts) > 2 else ""


_STATED_CODE = None  # memoised match._stated_postcode (lazy - see _locality_code)


def _locality_code(p: dict) -> str:
    """The most specific locality the RECORD ITSELF states, normalised for equality, or "" when
    it states none - which is the ordinary case in most markets and in EVERY corpus that quotes
    no postal codes at all. With "" everywhere, every key built below collapses to the
    city-level key and this whole layer is inert rather than degraded.

    DELEGATED to `match._stated_postcode` rather than re-implemented, because that reader is
    already this skill's ONE answer to "what code does this record state": whitespace removed,
    upper-cased, nothing else touched; a sentinel (tbd, n/a, ...) read as ABSENCE through the
    shared `looks_unknown`; a numeric cell accepted (a numeric-postal-code market stores the
    code as a number); and - the load-bearing part - NO country-specific parsing, because an
    outward/inward split is a fact about one country and an undivided run of digits about
    several others. A private copy here would be the fifth copy `normalize.looks_unknown`
    warns about, and the copy that drifted would silently split one town cache in two, or fuse
    two localities the source printed as different.

    Imported LAZILY and memoised: `import match` costs a measured ~86 ms with `normalize`
    already warm, against a stage that sleeps 1.1 s per live geocode by usage policy. It is
    NOT gated on whether the corpus states any codes, because that gate would need a private
    copy of `match._POSTCODE_FIELDS` - the same drift, one field further out."""
    global _STATED_CODE
    if _STATED_CODE is None:
        import match as _MM
        _STATED_CODE = _MM._stated_postcode
    return _STATED_CODE(p)


def _cache_lookup_key(cache: dict, city: str, country: str, code: str = "") -> str:
    """WHICH cache entry answers this lookup, or "" for a miss - the resolution ORDER, once.
    `_cache_lookup` reads the value at this key; a caller that must know HOW SPECIFIC the
    answer was reads the key itself (`_key_code`). Two views of ONE resolution, the same split
    `_region_labels_cache` / `_region_labels_answered_keys` keep for the same reason: the
    answer and its provenance are different questions, and a second private walk of the cache
    would drift from this one.

    ORDER, most specific first:
      1. the LOCALITY key 'city|country|code' - only when the record states a code, and only
         when that entry actually carries a coordinate; for an UNKNOWN country, any
         'city|<cc>|code' entry carrying a coordinate (D9c);
      2. the CITY key 'city|country' - the coarse fallback (see below);
      3. (UNKNOWN country only) the cross-country prefix scan: locality entries for the same
         city and the same code first, then city-level ones.

    WHERE THE COARSE FALLBACK IS LEGITIMATE, AND WHERE IT MUST NOT APPLY. Step 2 is a READ of
    a town-level coordinate to fill a property that has no coordinate at all. That is exactly
    what this stage has always done, the property is already labelled `coordsApprox: true`,
    and refusing it would strip the map of every pin in every market that quotes codes - a
    regression wearing a fix's clothes. What must NEVER happen is the WRITE-BACK: a town-level
    answer served through step 2 must not be persisted under the LOCALITY key. Persisting it
    would (a) assert that the geocoder answered for that locality when it answered for the
    town, (b) lock every property in the town onto ONE identical pin with no slot left for a
    better answer, and (c) make that permanent, because `web_enrich.plan` / `_chain_spec`
    treat any key PRESENT in the cache as settled and never re-ask it. That is precisely the
    "two properties in one town still get the same pin, and you have changed nothing" trap.

    So every TOWN-level writer in this file keys on the CITY level, which is the level its
    answer is actually at: a city gazetteer centroid, a city-NAME Nominatim hit, or a
    no-such-place memo about a city NAME. The locality level is written by exactly THREE
    sources, each of which actually answered FOR THAT LOCALITY: an operator seed
    (`seed_geocode.py`, whose rows may carry a postcode), the web-enrichment round
    (`web_enrich.py` emits a postcode request keyed on the locality key and `ingest` writes
    the answer back under it), and `geocode()`'s own postcode-first step (D9), which asks the
    geocoder for the STATED POSTCODE and persists that answer - a pin, or a negative memo -
    under the locality key. Until D9 there was no writer at all here, and the reader below
    resolved a level nothing ever filled.

    A LOCALITY ENTRY WITH NO COORDINATE FALLS THROUGH to step 2 rather than answering. A
    negative memo means "the geocoder was asked for this postcode and returned no such place",
    and a locality that did not resolve should still get its town centroid - the same answer
    it gets today. Only a locality entry carrying a coordinate may outrank the town. The
    negative memo is deliberately a LOCALITY write, and it makes exactly ONE claim, the same
    claim the city-level memo makes (B02): the web-enrichment round must not re-emit a request
    the geocoder has already answered, or one unknown code would keep the run at exit 8
    forever. It is NOT a claim on the slot. The LIVE helper re-asks it whenever it can reach
    the geocoder, exactly as the city-level guard re-asks a city memo, because "no such place"
    is a fact about the geocoder's coverage on the day and a postcode can be added to OSM
    later; an operator seed overwrites it; and a web-round answer written under the same key
    replaces it. And it is written ONLY from a real, successful "no such place" answer (an
    HTTP 200 with an empty array): a transport failure - unreachable, blocked, rate-limited,
    an error envelope - writes NOTHING at this level, because in Cowork the helper-side
    network is dead by design and a negative persisted from that would have occupied every
    locality slot in the corpus on every sandboxed run, which is the D9/D10 defect re-created
    (the D9 repair). That is the one write at this level that carries no coordinate, and the
    fall-through above is what makes it safe.

    STEPS 2 AND 3 ARE UNCHANGED from the city-only reader, including the KNOWN-country cut-off
    that keeps bug #5 closed (Toledo|ES must never resolve to a cached Toledo|US) and the
    deliberate cross-country scan for an UNKNOWN one (the orchestrator seeds city|es online
    while the property is still ??  - the sandbox-offline / WebFetch pattern). With no code
    stated, step 1 and the locality half of step 3 cannot fire at all, `_key_code` is "" for
    every legacy key, and this returns exactly the entry the old reader returned."""
    if code:
        lk = _geo_key(city, country, code)
        lv = cache.get(lk)
        if lv is not None and _coords_cc(lv)[0] is not None:
            return lk
        if _is_unknown_cc(country):
            # UNKNOWN country + a stated code: a locality PIN for the same city and code under
            # ANY country outranks the town key. A UK brochure rarely states its country, so the
            # record reads 'city|??' while its postcode answer sits under 'city|gb|code'; checking
            # the town key first served the town centroid on every warm run (D9c). Only a
            # coordinate-bearing entry qualifies here, exactly as in step 1.
            pref, lcode = f"{city.strip().lower()}|", code.lower()
            for k in cache:
                if (k.startswith(pref) and _key_code(k) == lcode
                        and _coords_cc(cache[k])[0] is not None):
                    return k
    ck = _geo_key(city, country)
    if cache.get(ck) is not None:
        return ck
    if not _is_unknown_cc(country):
        return ""                # KNOWN country + exact miss -> honest miss, never cross-country
    pref = f"{city.strip().lower()}|"
    lcode = code.lower()
    if lcode:
        for k in cache:
            if k.startswith(pref) and _key_code(k) == lcode:
                return k
    for k in cache:
        if k.startswith(pref) and not _key_code(k):
            return k
    return ""


def _cache_lookup(cache: dict, city: str, country: str, code: str = ""):
    """The cached geocode for this record as `(latlng, cc)`, or `(None, "")` on a miss.
    `_cache_lookup_key` decides WHICH entry answers and records why; this reads its value
    through `_coords_cc`, so both cached VALUE shapes (a bare coordinate pair and a dict) and
    a negative memo are tolerated exactly as before. `code` is the most specific locality the
    record states (`_locality_code`) and defaults to "" so every existing three-argument
    caller, and every corpus that quotes no codes, behaves exactly as it did."""
    k = _cache_lookup_key(cache, city, country, code)
    return _coords_cc(cache[k]) if k else (None, "")


_POI_LIB_CACHE: dict | None = None  # parse poi_library.json once per process (read-only)


def _poi_lib() -> dict:
    global _POI_LIB_CACHE
    if _POI_LIB_CACHE is None:
        f = C.ASSETS / "poi_library.json"
        try:  # a corrupt/truncated library degrades the fallback, never crashes enrich
            _POI_LIB_CACHE = json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {"pois": [], "city_country": {}}
        except Exception:
            _POI_LIB_CACHE = {"pois": [], "city_country": {}}
    return _POI_LIB_CACHE


_DATASET: dict | bool | None = None  # None = not loaded; False = absent (tests may pin)


def _load_asset_json(stem: str):
    """assets/<stem> as a parsed object. The large datasets ship GZIPPED
    (assets/<stem>.json.gz) to keep the skill under the org upload-size cap; a freshly
    rebuilt plain <stem>.json (if present) is preferred so a local rebuild needs no
    re-gzip step before it takes effect. Returns None if neither file exists / parses."""
    import gzip
    pj = C.ASSETS / f"{stem}.json"
    gz = C.ASSETS / f"{stem}.json.gz"
    try:
        if pj.exists():
            return json.loads(pj.read_text(encoding="utf-8-sig"))
        if gz.exists():
            return json.loads(gzip.decompress(gz.read_bytes()))
    except Exception:
        return None
    return None


def _poi_dataset():
    """The bundled COMPLETE-coverage POI dataset (assets/poi_dataset.json.gz, built by
    helpers/build_poi_dataset.py from org exports: all scheduled airports, all
    ports, all intermodal terminals). With complete coverage, nearest-of-this-set
    IS the genuine nearest - no live discovery needed at build time."""
    global _DATASET
    if _DATASET is None:
        d = _load_asset_json("poi_dataset")
        _DATASET = d if (d and d.get("pois")) else False
    return _DATASET or None


_BORDERS: dict | bool | None = None  # None = not loaded; False = absent (tests may pin)


def _borders_dataset():
    """The bundled COMPLETE European border-crossing dataset (assets/borders_dataset.json.gz,
    built by helpers/build_borders_dataset.py from OSM barrier=border_control). With complete
    coverage, nearest-of-this-set IS the genuine nearest crossing - no live Overpass needed."""
    global _BORDERS
    if _BORDERS is None:
        d = _load_asset_json("borders_dataset")
        _BORDERS = d if (d and d.get("pois")) else False
    return _BORDERS or None


_CITY_DATASET: dict | bool | None = None  # None = not loaded; False = absent (tests may pin)
MAJOR_CITY_POP = 400_000  # the second "Major cities" result: nearest city at least this big (15e)


def _cities_major_dataset():
    """The bundled COMPLETE-coverage >=100k European city dataset
    (assets/cities_major_dataset.json.gz, built by helpers/build_cities_major_dataset.py).
    With complete coverage, nearest-of-this-set IS the genuine nearest major city, so the
    curated poi_library city role is retired. None when the asset is absent."""
    global _CITY_DATASET
    if _CITY_DATASET is None:
        d = _load_asset_json("cities_major_dataset")
        _CITY_DATASET = d if (d and d.get("cities")) else False
    return _CITY_DATASET or None


def _nearest_from_dataset(lat: float, lng: float, dataset: dict | None,
                          borders: dict | None = None, cities: dict | None = None) -> dict:
    """The genuine nearest air/port/rail facility from the complete POI dataset, the nearest
    border crossing from the complete borders dataset, and the nearest >=100k city from the
    complete cities-major dataset (plus, under 'city_major', the nearest MAJOR_CITY_POP+ city
    when that is a different one) - each capped by POI_MAX_KM (past the cap we honestly give
    up). All three are COMPLETE sets, so nearest-of-set IS the genuine nearest."""
    found: dict = {}
    for q in (dataset or {}).get("pois", []):
        t = q.get("type")
        if t not in ("air", "port", "rail"):
            continue
        km = _haversine_km(lat, lng, q["lat"], q["lng"])
        if km > POI_MAX_KM.get(t, 400):
            continue
        if t not in found or km < found[t]["km"]:
            found[t] = {"name": q["name"], "type": t, "lat": q["lat"], "lng": q["lng"],
                        "km": round(km, 1), "dataset": True}
    for q in (borders or {}).get("pois", []):
        km = _haversine_km(lat, lng, q["lat"], q["lng"])
        if km > POI_MAX_KM.get("border", 400):
            continue
        if "border" not in found or km < found["border"]["km"]:
            rec = {"name": q["name"], "type": "border", "lat": q["lat"], "lng": q["lng"],
                   "km": round(km, 1), "dataset": True}
            if q.get("country"):
                rec["country"] = q["country"]
            if q.get("crossingOf"):
                rec["crossingOf"] = q["crossingOf"]
            found["border"] = rec
    for c in (cities or {}).get("cities", []):
        km = _haversine_km(lat, lng, c["lat"], c["lng"])
        if km > POI_MAX_KM.get("city", 300):
            continue
        rec = {"name": c["name"], "type": "city", "lat": c["lat"],
               "lng": c["lng"], "km": round(km, 1), "dataset": True,
               "country": c.get("country", ""), "population": c.get("population")}
        if "city" not in found or km < found["city"]["km"]:
            found["city"] = rec
        # ALSO the nearest city of MAJOR_CITY_POP+ (15e): Leigh's nearest 100k+ city is Wigan,
        # which alone hid Manchester and Liverpool from "Major cities". Keyed apart (type still
        # 'city') and dropped below when it is the same city, so at most two city results.
        if (c.get("population") or 0) >= MAJOR_CITY_POP and (
                "city_major" not in found or km < found["city_major"]["km"]):
            found["city_major"] = rec
    if "city_major" in found and found["city_major"] is found.get("city"):
        del found["city_major"]  # the nearest 100k+ city IS a 400k+ one: one city only
    return found


def _trace(pid, field, value, source_file, locator, source_type, record_type="property") -> dict:
    """One source-ledger row for an enrichment-filled field (confidence Medium per
    source-traceability.md - enriched, not read from a client source file)."""
    return {"property_id": pid, "record_type": record_type, "field": field,
            "value": str(value)[:60], "source_file": source_file,
            "source_locator": locator, "source_type": source_type,
            "extractor": "enrich", "confidence": "Medium",
            "conflict_note": "", "verified": ""}


def _update_ledger(ledger_path: Path, updates: list[dict]) -> None:
    """Upsert enrichment trace rows into source_ledger.csv: a row with the same
    (property_id, field) REPLACES the merge-written 'gap' row, anything new appends.
    The audit artefact must never contradict the deliverable - a geocoded lat/lng
    whose ledger row still reads 'absent in all sources' is exactly the mismatch
    the G-trace reviewer is told to strike."""
    import csv
    import ledger as L
    if not updates:
        return
    rows: list[dict] = []
    if ledger_path.exists():
        with open(ledger_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    index = {(str(r.get("property_id")), r.get("field")): n for n, r in enumerate(rows)}
    for u in updates:
        key = (str(u.get("property_id")), u.get("field"))
        if key in index:
            rows[index[key]] = u
        else:
            index[key] = len(rows)
            rows.append(u)
    import io as _io
    buf = _io.StringIO()
    w = csv.DictWriter(buf, fieldnames=L.COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in L.COLUMNS})
    C.atomic_write_text(ledger_path, buf.getvalue())  # atomic + LF, resume-safe (review #2)


def _is_unknown_cc(v) -> bool:
    """Absence test for a country / city value, through the ONE shared predicate (contract C5).

    Kept as a named wrapper because web_enrich imports it by this name. Until v41 it was a
    private four-member literal: it read 'tbc', 'n/a' and '-' as REAL places (so a tracker's
    "n/a" country reached the geocoder as a country) and deleted a stated "None". The family is
    normalize.UNKNOWN_FORMS; the multilingual market phrases it adds ("a consultar", ...) are
    never a place name, so widening here costs nothing and closes the drift."""
    # CODE-scoped, not value-scoped: this test judges a country CODE, and three members of the
    # shared unknown family are also assigned ISO alpha-2 codes. Using the value-scoped reader
    # here is what moved those three countries to unknown in v41. See normalize.looks_unknown_code.
    return C._N.looks_unknown_code(v)


def _geocode_one(requests, city: str, country_cc: str):
    """One Nominatim lookup -> ([lat,lng], 'CC') or (None, ''). country_cc (ISO-2)
    biases the search; '' searches globally.

    THREE OUTCOMES, AND ONLY THE FIRST TWO ARE ANSWERS. This is the same rule `_geocode_postcode`
    states in full (D9), applied here because this function had the flaw that repair was written
    for: it read `.json()` with no status check and no type check, so a body that was not an
    answer could still be returned as one. An empty JSON object from a rate-limited or blocked
    endpoint is falsy, so `not arr` was True and the caller memoised a NEGATIVE about the city
    name (B02) - "no such place" persisted from a transport failure. Because the web-enrichment
    round treats any present cache key as settled and never re-asks it, one throttled pass could
    settle every city in the corpus on a wrong answer. A non-2xx status and a non-list body now
    RAISE, which is what the caller's circuit breaker already expects from this function: stop
    asking this pass and say how to recover, rather than write a fiction into the cache."""
    params = {"q": city, "format": "json", "limit": 1, "addressdetails": 1}
    if country_cc:
        params["countrycodes"] = country_cc.lower()
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params=params, headers=UA, timeout=12)
    r.raise_for_status()
    arr = r.json()
    if not isinstance(arr, list):
        raise ValueError("nominatim body is not a JSON array - not an answer, not memoised")
    if not arr:
        return None, ""
    cc = str((arr[0].get("address", {}) or {}).get("country_code", "")).upper()
    return [float(arr[0]["lat"]), float(arr[0]["lon"])], cc


def _postcode_query(postcode: str, country_cc: str) -> dict:
    """The Nominatim STRUCTURED query for a stated postal code, as the parameter dict both
    the live caller (`_geocode_postcode`) and the browser bundle (`web_enrich._chain_spec` /
    `cmd_plan`) build their request from. ONE place, so the URL the operator's browser fetches
    is the same request the helper would have made, and the answer lands in the same cache slot.

    `postalcode` is Nominatim's structured-search field: it matches the code as a POSTCODE and
    returns nothing for one it does not know, rather than degrading to the nearest place name
    the way a free-text `q=` does. `countrycodes` scopes it, because a postal code is only
    unambiguous WITHIN a country (several national formats share a five-digit shape), which is
    also why the callers never build this query for an unknown country. `postcode` arrives as
    `_locality_code` normalises it (whitespace removed, upper-cased); Nominatim's per-country
    postcode patterns treat the internal space as optional, so the spaceless form matches."""
    return {"postalcode": postcode, "countrycodes": country_cc.lower(), "format": "json",
            "limit": 1, "addressdetails": 1}


# ---------------------------------------------------------------------------------------------
# THE GB NATIONAL POSTCODE REGISTER - a FALLBACK behind Nominatim, never the primary. (D9b)
# ---------------------------------------------------------------------------------------------
# api.postcodes.io is a free, keyless HTTP mirror of the ONS Postcode Directory - the ONS/Royal
# Mail national register itself, not a crowd-sourced gazetteer. It is named in the ledger as
# BOTH (register and mirror) because a reader auditing a pin needs to know which body asserted
# the coordinate AND which service actually served it.
_REGISTER_HOST = "https://api.postcodes.io"
_REGISTER_FILE = "api.postcodes.io (ONS/Royal Mail GB national postcode register)"
# A URL-PATH SAFETY GATE, NOT A POSTCODE VALIDATOR - do not read it as one. `_locality_code`
# hands us whatever the SOURCE printed, upper-cased with whitespace removed and nothing else
# touched (no country-specific parsing, on purpose - see its docstring). A cell holding
# "SEE/BROCHURE" or "N-A" would otherwise be pasted straight into a URL path and could walk to a
# different endpoint entirely. Anything that is not a plain alphanumeric run of GB-postcode
# length is not a GB postcode, so it is never asked. Real normalised codes are 5-7 characters
# ("M11AA" .. "EC1A1BB"); 8 is slack, so a malformed-but-harmless code is refused by the
# register rather than by a guess made here.
_REGISTER_CODE_OK = re.compile(r"^[A-Z0-9]{5,8}$")
# WHICH REGISTER ANSWERED THE LAST `_geocode_postcode`, keyed 'CC|CODE' -> 'live'|'terminated'.
#
# WHY A MODULE-LEVEL NOTE RATHER THAN A THIRD RETURN VALUE. `_geocode_postcode` returns a
# two-tuple and that arity is load-bearing in two places outside this function: every geocode
# eval in the tree stubs it with a two-tuple lambda (d9_postcode_locality_test, and
# region_locality_cache_test), and the caller unpacks it into exactly two names. Widening the
# tuple to carry provenance would break both for a value that only ONE caller
# (`_postcode_first`'s two call sites) ever reads, one statement later. The note is written only
# on a register HIT and CONSUMED by `_postcode_src` one statement later, and `_geocode_postcode`
# clears this code's slot before it asks, so the label always describes the call that just
# happened rather than an earlier one. ONE EXCEPTION, stated because this file's comments are
# read as guarantees: if the cache write between the hit and the consume raises, the note is
# stranded for the rest of the pass. That is benign rather than wrong - the next
# `_geocode_postcode` for that key clears the slot before asking, and the circuit breaker stops
# further lookups anyway - so no ledger row can be built from a stale label, but "cannot go
# stale" would be too strong a word for it.
#
# WHERE THIS FALLBACK DOES NOT RUN AT ALL, said plainly because a sibling defect was exactly
# this. The register is reached through helper-side `requests`, so it fires only on a pass whose
# helpers have network. In Cowork they do not, by design: geocoding goes out through
# `web_enrich`'s browser bundle, and `cmd_ingest` memoises an empty Nominatim array with no
# register leg. So in that sandbox D9b contributes nothing and a GB code Nominatim misses stays
# unresolved. Teaching the browser bundle to ask the register too is a real extension and is
# deliberately NOT taken here (it widens a shared contract for one market), but the gap it leaves
# must be visible rather than discovered: the geocode gap line says so, and says a networked
# re-run may still resolve the code.
#
# DELIBERATELY NOT PERSISTED to geocode_cache.json. The cache entry shape {'latlng','cc'} is
# compared for equality by evals and read by `web_enrich`, so a third key would be a change to a
# shared contract for no gain: on a warm re-run the pin is served from the cache and
# `_coord_locator`'s "cache" branch already says so honestly ("seeded geocode cache ... locality
# ..."), which is the truthful provenance for that pass - the register was not asked.
_REGISTER_PROVENANCE: dict = {}


def _register_key(postcode: str, country_cc: str) -> str:
    """The `_REGISTER_PROVENANCE` slot for one lookup. Built from the SAME two arguments
    `_geocode_postcode` was called with, so the writer and the reader cannot drift apart.

    The code is normalised to the SPACELESS upper-case form `_postcode_register` asks the URL
    with, and not merely stripped. In practice both sides are handed `_locality_code`'s output,
    which is already spaceless, so today the two spellings coincide - but if a caller ever passed
    "WA5 5TN" the note would be filed under one key and looked up under another, and the silent
    consequence is not a crash: it is a register-answered pin carrying a ledger row that credits
    Nominatim for a code Nominatim does not hold. A wrong provenance row is worse than a missing
    one, so the two spellings are collapsed here rather than assumed equal."""
    code = str(postcode or "").strip().upper().replace(" ", "")
    return f"{str(country_cc or '').strip().upper()}|{code}"


def _is_gb(country_cc) -> str:
    """'GB' when this country is Great Britain / Northern Ireland, else "" - the ONE gate on the
    register, so no other market pays a wasted round trip for a register that only holds GB.

    'UK' is accepted alongside 'GB'. `normalize.country_iso` maps UK->GB upstream, so in a
    well-formed corpus only 'GB' arrives; but if a raw 'UK' ever reaches here the NOMINATIM leg
    is already broken for it (`countrycodes=uk` is not an ISO code and matches nothing), which is
    precisely the case the register would rescue. Refusing the alias here would turn a rescuable
    record into a silent town-centre pin, so the two-character widening is the honest gate."""
    return "GB" if str(country_cc or "").strip().upper() in ("GB", "UK") else ""


def _postcode_register(requests, postcode: str):
    """The GB national register's coordinate for a postcode -> ([lat,lng], 'live'|'terminated')
    or (None, ""). NEVER raises. GB only, and only ever called on Nominatim's genuine negative.

    WHY THIS EXISTS, AND WHAT IT IS NOT. It is NOT the D9 rescue, and describing it as one would
    be a fiction the ledger would then repeat. The D9 defect was motivated by NN6 7ES (the DIRFT
    450 site that was mis-pinned to a town centre), and that code RESOLVES through Nominatim
    today - measured, `_geocode_postcode(requests, 'NN67ES', 'GB')` returns
    ([52.3478507, -1.1643983], 'GB'), 17 m from the ONS coordinate for it - so it never reaches
    this function at all. What was measured instead is a narrower COVERAGE gap: Nominatim's
    structured `postalcode` search returns a genuine empty array for GB codes the national
    register knows perfectly well. Three measured misses: WA5 5TN, BT1 2FF and BT28 3AX. Two of
    the three are Northern Ireland, which is the shape of the gap - OSM's GB postcode coverage is
    thinner there - and the third turned out to be a code retired in 2001. Before this fallback
    each of those properties silently fell back to a TOWN-CENTRE pin, which is the same
    wrong-county / shared-pin failure class D9 exists to prevent, just reached by a different
    route.

    THE TWO ENDPOINTS, AND THEIR MEASURED SHAPES (probed live against the service):
      * GET /postcodes/<code>            -> 200 {"status":200,"result":{... "latitude":54.601212,
                                            "longitude":-5.927817, "quality":1 ...}}   a LIVE code
                                        -> 404 {"status":404,"error":"Postcode not found"}
      * GET /terminated_postcodes/<code> -> 200 {"status":200,"result":{"postcode":"WA5 5TN",
                                            "year_terminated":2001,"month_terminated":1,
                                            "latitude":53.414873,"longitude":-2.611994}}
                                        -> 404 for a code that never existed
    Latitude and longitude are top-level floats on `result` in BOTH shapes, which is why one
    reader serves both. The live 404 body sometimes ALSO carries a `terminated` block with the
    same pair; it is deliberately not read, because relying on an undocumented extra key in an
    ERROR body would make a claim rest on the least stable part of the response, and the second
    round trip only happens on a code Nominatim already missed.

    A 200 IS NOT AUTOMATICALLY A COORDINATE - the case that would have shipped a fiction. Codes
    outside the ONS grid return HTTP 200 with `"latitude": null, "longitude": null` and
    `quality: 9`: measured on Guernsey (GY1 1WR) and Jersey (JE2 4UH), both of which a UK
    industrial corpus can plausibly contain. A reader that trusted the status code would have
    written a null pair onto a property card, or crashed the stage. Every field is therefore
    coerced through `float()` inside the try, and the result is range-checked, so a null, a
    string, a missing key or a nonsense number all land on the same answer as a network failure:
    no claim.

    FAILURES ARE SWALLOWED, NOT RAISED, and that is the whole safety argument for adding a
    second network dependency to this stage. The value being enriched here is a Nominatim
    negative that is ALREADY a valid, complete answer - the caller is entitled to memoise it and
    fall through to the town-level path. So a register that is down, blocked, slow, rate-limited,
    moved, or newly returning a shape we do not recognise must cost exactly nothing: the caller
    gets the same (None, "") it would have got before this function existed, and the stage's
    failure surface is unchanged. `_geocode_postcode`'s three-outcome contract stays byte for
    byte intact because nothing in here can raise into it. The one visible cost of an unreachable
    register is latency - a second 12 s timeout, GB only, only on a code Nominatim missed.

    NO COURTESY SLEEP HERE, deliberately. The 1.1 s in `_postcode_first`'s `finally` is
    Nominatim's usage policy (max 1 request/second to nominatim.openstreetmap.org) and it is
    charged per Nominatim request, not per property. api.postcodes.io is a different host with no
    such policy, and these calls sit INSIDE the same iteration, before that `finally` runs - so
    they lengthen the gap between consecutive Nominatim requests and can never shorten it. Adding
    a second sleep would slow every GB run for a courtesy nobody asked for."""
    code = str(postcode or "").strip().upper().replace(" ", "")
    if not _REGISTER_CODE_OK.match(code):
        return None, ""
    try:
        r = requests.get(f"{_REGISTER_HOST}/postcodes/{code}", headers=UA, timeout=12)
        kind = "live"
        if int(getattr(r, "status_code", 0)) == 404:
            # A LIVE MISS IS NOT A REGISTER MISS. A code retired since the brochure was written
            # is still real ONS data about a real place - it is exactly how WA5 5TN behaves - so
            # the retired register is asked before we give up. What changes is the PROVENANCE,
            # not the confidence in the coordinate: `_coord_locator` says the code is retired.
            r = requests.get(f"{_REGISTER_HOST}/terminated_postcodes/{code}",
                             headers=UA, timeout=12)
            kind = "terminated"
        if int(getattr(r, "status_code", 0)) != 200:
            return None, ""          # 404 on both = the register does not hold it; 5xx = down
        res = r.json().get("result")
        lat, lng = float(res["latitude"]), float(res["longitude"])
    except Exception:
        return None, ""              # unreachable, non-JSON, null coords, moved shape: no claim
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None, ""              # a number, but not a coordinate - still not an answer
    return [lat, lng], kind


def _postcode_src(postcode: str, country_cc: str) -> str:
    """WHICH source answered the last `_geocode_postcode` for this code, as the `src` token
    `_coord_locator` and the country-fill branch turn into ledger provenance:
    'postcode' (Nominatim), 'postcode-register-live' or 'postcode-register-terminated'.

    CONSUMES the note (pop, not get). A note exists only when the register answered, and it is
    read exactly once, one statement after the lookup that wrote it - so a note can never be
    inherited by the next property that happens to state the same code in another town."""
    kind = _REGISTER_PROVENANCE.pop(_register_key(postcode, country_cc), "")
    return f"postcode-register-{kind}" if kind else "postcode"


def _geocode_postcode(requests, postcode: str, country_cc: str):
    """One Nominatim lookup of a STATED POSTAL CODE -> ([lat,lng], 'CC') or (None, ''). (D9)

    WHY THIS EXISTS. Not one of the seven UK industrial decks on the measured run printed a
    coordinate - the only location handle in the whole corpus was the postcode, which is normal
    for that market - so every property was geocoded from the CITY NAME to a town centroid.
    Three failures came out of that, all found by blind human reviewers and none by a gate:
    a site whose POSTAL town sits in the neighbouring county was pinned 9 km away across the
    county line, bound to the wrong NUTS-3 area, and shipped that area's entire workforce panel;
    a second property was pinned BYTE-IDENTICAL to its city's POI coordinate and printed a
    "0 min / 0.0 km" self-distance; and two sites on opposite sides of a county line shared one
    pin. Where a record states a postcode, this asks the geocoder for THAT, not for the town.

    The same signature shape as `_geocode_one` (module-level, `requests` injected) so an eval
    can stub it the way every existing geocode eval stubs `_geocode_one`, and so the network is
    never touched from a test. A separate function rather than a keyword on `_geocode_one`
    because evals in the wild stub that one with a fixed three-positional lambda.

    THREE OUTCOMES, AND ONLY THE FIRST TWO ARE ANSWERS (the D9 repair). A non-empty array is a
    pin; an EMPTY array on an HTTP 200 is a real, successful "no such place", the one answer
    the caller may memoise as a negative; everything else RAISES - a non-2xx status (blocked,
    rate-limited, down) and a body that is not a JSON array (Nominatim's error envelope is a
    dict). The distinction matters because the caller persists a negative under the LOCALITY
    key and the web-enrichment round treats any present key as settled: a transport failure
    memoised as "no such postcode" would have settled every stated code in the corpus on every
    Cowork run, where the helper-side network is dead by design. Raising is also what the
    caller's circuit breaker already expects from `_geocode_one`, so the failure path is the
    established one (stop asking this pass, print how to recover), not a second convention.
    `web_enrich.cmd_ingest` applies the same rule to the browser's answer ("nominatim body is
    not a JSON array" is skipped, never memoised).

    AND THEN, FOR GB ONLY, A NATIONAL-REGISTER FALLBACK BEHIND THAT NEGATIVE. (D9b) Nominatim
    misses GB codes the ONS register holds - WA5 5TN, BT1 2FF and BT28 3AX, all measured, two of
    them Northern Ireland - and each of those properties was silently dropping to a TOWN-CENTRE
    pin. `_postcode_register` is asked in the SECOND branch only, and the placement is the whole
    design, not a convenience:

      * NOT THE PRIMARY, because the three-outcome contract above is what makes this function
        safe, and it is a contract about NOMINATIM's response. Asking the register first would
        mean the negative the caller memoises is a register negative while the circuit breaker,
        `web_enrich`'s browser handoff and `cmd_ingest`'s ingest rule all still reason about
        Nominatim - two sources answering into one cache slot under one set of rules written for
        the other. Behind the negative, the contract is untouched: the pin branch, the
        `raise_for_status()` and the non-list `ValueError` are byte for byte what they were.
      * ONLY BEHIND A GENUINE NEGATIVE, never behind a raise. A raise means we do not KNOW
        whether the code exists, and the established answer to not knowing is to stop the pass,
        not to ask somebody else and turn an unknown into a claim.
      * AND IT CANNOT ADD A FAILURE MODE: `_postcode_register` swallows everything and returns
        (None, "") for a register that is down, blocked or shaped differently, so the outcome is
        the same negative the caller would have memoised anyway. That negative is a valid answer
        already; the register can only improve it, never break it.

    This is a COVERAGE improvement, not the D9 rescue. NN6 7ES - the DIRFT 450 code whose
    mis-pinning motivated D9 - resolves through the Nominatim leg above and never reaches the
    fallback (measured: ([52.3478507, -1.1643983], 'GB'), 17 m from the ONS coordinate)."""
    # Clear this code's provenance slot BEFORE asking, so the label `_postcode_src` reads back
    # can only have been written by THIS call. Costs nothing on the overwhelmingly common path
    # (no note is ever written unless the register answers) and removes the one way a stale
    # label could survive into a later property's ledger row.
    _REGISTER_PROVENANCE.pop(_register_key(postcode, country_cc), None)
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params=_postcode_query(postcode, country_cc), headers=UA, timeout=12)
    r.raise_for_status()
    arr = r.json()
    if not isinstance(arr, list):
        raise ValueError("nominatim body is not a JSON array - not an answer, not memoised")
    if not arr:
        # THE GENUINE "no such place" - the one outcome the caller may memoise, and the one
        # place the national register is asked (D9b). GB only; every other market returns here
        # without a round trip, exactly as before.
        if _is_gb(country_cc):
            rll, kind = _postcode_register(requests, postcode)
            if rll:
                _REGISTER_PROVENANCE[_register_key(postcode, country_cc)] = kind
                # 'GB' is a fact about the ENDPOINT, not an inference: api.postcodes.io serves
                # the GB register and nothing else, and it is only reached through `_is_gb`.
                # The register's own `country` field is a nation name ("Northern Ireland",
                # "Scotland"), not an ISO code, and the terminated shape carries no country at
                # all - so reading it would mean inventing the mapping here.
                return rll, "GB"
        return None, ""
    cc = str((arr[0].get("address", {}) or {}).get("country_code", "")).upper()
    return [float(arr[0]["lat"]), float(arr[0]["lon"])], cc


def _reverse_cc(requests, lat, lng) -> str:
    """ISO-2 country for a coordinate via Nominatim REVERSE -> 'GB' / '' (miss/offline).
    Lets an already-located property (e.g. a tracker row WITH coords) resolve its
    country instead of being stuck at '??' (P2-5). Real data only, never invented."""
    arr = requests.get("https://nominatim.openstreetmap.org/reverse",
                       params={"lat": lat, "lon": lng, "format": "json", "zoom": 3,
                               "addressdetails": 1}, headers=UA, timeout=12).json()
    return str((arr.get("address", {}) or {}).get("country_code", "")).upper()


_GAZETTEER: dict | bool | None = None  # None = not loaded; False = absent (tests may pin)
_GAZETTEER_MULTI: dict | None = None   # norm_name -> frozenset of CCs, for names in >1 country


def _gazetteer():
    """The bundled European city gazetteer (assets/cities_dataset.json.gz, built by
    helpers/build_cities_dataset.py from a GeoNames dump): name+country -> real city
    coordinates, so geocoding is a pure OFFLINE lookup and the map works in Cowork with NO
    exit-8 round-trip. None when the asset is absent (tests may pin _GAZETTEER=False)."""
    global _GAZETTEER
    if _GAZETTEER is None:
        d = _load_asset_json("cities_dataset")
        _GAZETTEER = d if d else False
    return _GAZETTEER or None


def _gazetteer_multi() -> dict:
    """{norm_name -> frozenset(CC, ...)} for every city name the gazetteer carries under MORE
    THAN ONE country (e.g. 'halle'->{DE,BE}, 'rochefort'->{BE,FR}). Derived once from the
    existing 'cities' keys - the shipped asset is unchanged, no rebuild. Lets the lookup detect
    that a bare name is AMBIGUOUS and refuse the pre-baked by_name pick unless a country (real
    or dataset-dominant) selects a specific candidate. Empty when there is no gazetteer."""
    global _GAZETTEER_MULTI
    if _GAZETTEER_MULTI is None:
        ds = _gazetteer()
        acc: dict = {}
        for key in (ds or {}).get("cities", {}):
            nm, _, cc = key.rpartition("|")
            if nm and cc:
                acc.setdefault(nm, set()).add(cc.upper())
        _GAZETTEER_MULTI = {nm: frozenset(ccs) for nm, ccs in acc.items() if len(ccs) > 1}
    return _GAZETTEER_MULTI


def _gazetteer_lookup(city, country, dominant=""):
    """([lat, lng], 'CC') for a European city from the bundled gazetteer, or (None, '').
    A known country (ISO-2) disambiguates same-named cities exactly. Without a known country:
    if the name is UNIQUE in the gazetteer we return it; if it exists in MORE THAN ONE country
    we return it ONLY when a dataset-`dominant` country (the mode of the already-located
    cluster) has a real entry for that name - otherwise (None, '') so the caller leaves an
    honest tbd+gap. Real city coordinates - never invented, never a silent guess."""
    ds = _gazetteer()
    if not ds:
        return None, ""
    import normalize as _N
    nm = _N._norm_city(city)
    if not nm:
        return None, ""
    cities = ds.get("cities", {})
    cc = "" if _is_unknown_cc(country) else (_N.country_iso(str(country).strip()) or "").upper()
    if cc:
        ll = cities.get(f"{nm}|{cc}")
        if ll:
            return [ll[0], ll[1]], cc
        # a KNOWN country with NO entry for this name is NOT a licence to fall back to a
        # different-country pick (that is bug #3 / #5): refuse rather than mislocate.
        return None, ""
    multi = _gazetteer_multi()
    if nm in multi:
        # ambiguous bare name: only resolvable via the dataset-dominant country
        dcc = (_N.country_iso(str(dominant).strip()) or "").upper() if dominant else ""
        if dcc and dcc in multi[nm]:
            ll = cities.get(f"{nm}|{dcc}")
            if ll:
                return [ll[0], ll[1]], dcc
        return None, ""            # ambiguous & no dominant match -> honest miss
    ent = ds.get("by_name", {}).get(nm)   # UNIQUE name: the single pick IS unambiguous
    if ent and ent.get("ll"):
        return [ent["ll"][0], ent["ll"][1]], ent.get("cc", "")
    return None, ""


MAPLINK_CACHE = "maplink_cache.json"


def resolve_map_links(canonical: dict, gaps: list, updates: list | None = None) -> int:
    """Follow a FIRST-PARTY maps SHORT link to the author's own pin. (B60)

    `backfill_link_coords` already harvests the 'click for location' hyperlink off every
    brochure page, but a `maps.app.goo.gl/...` shortener carries no coordinates - it has to be
    FOLLOWED. Nothing ever did, so on a live run all thirteen options shipped their link as a
    bare href while three of them showed a town-centre geocode on the map (one had no pin at
    all). The brochure author had pinned every site; the dashboard just never asked.

    Runs BEFORE geocode() so a real pin always beats a city centroid, and only for a property
    that has no numeric coordinate yet - it can never move a coordinate a source already gave.
    Cached by URL, so a re-run costs nothing. Offline it is a NO-OP: the first failure
    circuit-breaks, the coordinate stays an honest gap, and `coord-provenance` reports it.
    """
    import requests
    import coords as CO
    props = canonical.get("properties", [])
    todo = [p for p in props
            if str(p.get("mapLink") or "") and CO.SHORT_MAPS.match(str(p.get("mapLink")))
            and not isinstance(p.get("lat"), (int, float))]
    if not todo:
        return 0
    cache = _load_cache(MAPLINK_CACHE)
    dirty, done, dead = False, 0, False
    for p in todo:
        uri = str(p["mapLink"])
        hit = cache.get(uri)
        if hit is None and not dead:
            try:
                r = requests.get(uri, allow_redirects=True, timeout=25,
                                 headers={"User-Agent": "Mozilla/5.0", **UA})
                got = CO.coords_from_resolved(r.url, r.text[:300000])
                cache[uri] = list(got) if got else []
                hit = cache[uri]
                dirty = True
            except Exception:
                dead = True          # offline / blocked - do not pay N x timeout
        if not hit:
            continue
        p["lat"], p["lng"] = float(hit[0]), float(hit[1])
        p["coordsApprox"] = False    # this IS the pin, not a centroid
        # provenance goes to the LEDGER only. This runs POST-merge, where `__meta` is
        # quarantined out of PROPS - writing it here leaked a `__meta` object into the built
        # dashboard and the reconcile gate blocked the build, which is exactly its job.
        done += 1
        if updates is not None:
            updates.append(_trace(p.get("id"), "lat", hit[0], uri,
                                  "first-party map link followed to its destination", "maplink"))
            updates.append(_trace(p.get("id"), "lng", hit[1], uri,
                                  "first-party map link followed to its destination", "maplink"))
    if dirty:
        _save_cache(MAPLINK_CACHE, cache)
    unresolved = [p for p in todo if not isinstance(p.get("lat"), (int, float))]
    if unresolved:
        gaps.append(
            f"{len(unresolved)} property(ies) carry a first-party maps SHORT link that could not "
            f"be followed from here (offline or blocked), so their pin falls back to the town "
            f"centre: " + ", ".join(f"id={p.get('id')}" for p in unresolved[:8]) +
            ". Re-run this stage with network access to bake the author's own pin.")
    return done


def _coord_locator(src: str, city: str, code: str = "", from_centroid: bool = False):
    """(source_file, source_type, locator) for a geocoded coordinate's ledger rows - the ONE
    vocabulary for where a pin came from, shared by the fill of an empty coordinate and the
    displacement of an approximate one (D10), so the same answer never carries two spellings.

    `code` is the LOCALITY segment of the cache key that answered (`_key_code`), "" for a
    city-level answer - and with "" every string below is byte-identical to the legacy locator,
    which a corpus that quotes no postcodes still gets. A locality-level answer NAMES THE
    POSTCODE: two properties in one town holding two different pins must not carry identical
    provenance rows, or the audit artefact cannot tell the reader where each pin came from (G1),
    and after D9 the reader must also be able to see that the pin is the postcode's, not the
    town's. Every locator still says `(coordsApprox)`, because it still is - see the
    `coordsApprox` decision in `geocode()`."""
    if from_centroid:
        return "assets/poi_library.json", "poi_library", f"city centroid '{city}' (coordsApprox)"
    if src in ("gazetteer", "gazetteer-dominant"):
        detail = "city gazetteer" if src == "gazetteer" else "city gazetteer (dominant-country)"
        return "assets/cities_dataset.json", "dataset", f"{detail} '{city}' (coordsApprox)"
    if src == "cache":
        if code:
            return ("geocode_cache.json", "cache",
                    f"seeded geocode cache '{city}' locality '{code.upper()}' "
                    f"(pin of the stated postcode; coordsApprox)")
        return "geocode_cache.json", "cache", f"seeded geocode cache '{city}' (coordsApprox)"
    if src == "postcode":
        return ("Nominatim (OSM geocoder)", "web",
                f"geocode of the stated postcode '{code.upper()}' in '{city}' (coordsApprox)")
    if src in ("postcode-register-live", "postcode-register-terminated"):
        # THE LEDGER NAMES THE REGISTER THAT ANSWERED, AND SAYS WHEN THE CODE IS RETIRED. (D9b)
        # Both halves are load-bearing. A reader must be able to see that this pin came from the
        # national register rather than from OSM, because the two disagree about which codes
        # exist and that is the only reason this row is not a town centroid. And a retired code
        # is real ONS data whose coordinate was FROZEN at termination - the unit itself no longer
        # receives post, so the surrounding addressing may since have been redrawn. Stating that
        # in the locator is the Data Honesty Standard applied to a source that is genuine but
        # dated; hiding it behind the same string as a live code would overstate it.
        retired = ("; the code is RETIRED and this is the coordinate frozen at its termination"
                   if src.endswith("terminated") else "")
        return (_REGISTER_FILE, "web",
                f"geocode of the stated postcode '{code.upper()}' in '{city}' via the GB national "
                f"postcode register, which OSM/Nominatim does not hold{retired} (coordsApprox)")
    return "Nominatim (OSM geocoder)", "web", f"geocode '{city}' (coordsApprox)"


def geocode(canonical: dict, gaps: list, updates: list | None = None) -> int:
    """Fill missing lat/lng and reverse-geocode an unknown country. A bare city name
    is globally AMBIGUOUS (a Spanish town can also exist in Latin America/India), so
    after a first pass we take the dataset's dominant country and RE-QUERY any
    unknown-country property that landed as a far geographic outlier, constrained to
    that country. Mode-based - no hardcoded country, works for any geography.

    WHERE A RECORD STATES A POSTCODE, THE POSTCODE IS GEOCODED, NOT THE TOWN (D9), and its
    answer is persisted under the LOCALITY cache key `city|country|code` - the writer that
    `_cache_lookup_key`'s reader was built for and that nothing filled. A locality-level answer
    may also REPLACE a pin this function itself wrote as an approximate town centroid (D10),
    which is what lets an operator seed, a web-round answer or a fresh postcode geocode take
    effect on a warm work dir with a plain re-run; a coordinate the source stated is never moved.

    THE `coordsApprox` DECISION. A postcode pin is flagged `coordsApprox: true`, the same as a
    town centroid, on purpose. A postal code is an area, not a building: in a dense format it is
    a street segment, in a sparse one it can cover a whole rural district, and a large-user or
    terminated code can centroid to the sorting office. Claiming the pin is the site is the
    precision-we-do-not-have failure this whole skill exists to prevent, and the flag has three
    consumers that all want the honest answer: the map draws an approximate pin with a dashed
    marker and the modal's approximation note (template v34), the Gaps Report discloses it, and
    `gate_runner.py coord-provenance` checks an approximate pin against the property's own page
    for a first-party coordinate or map link - which must still beat a postcode centroid, and
    would be skipped if the flag were false. The LEDGER carries the finer distinction: the
    locator names the stated postcode (`_coord_locator`), so a reader can tell a postcode pin
    from a town pin without a new schema field.

    A GB NATIONAL-REGISTER PIN IS `coordsApprox: true` TOO (D9b), and the reasoning is the same
    one, not a weaker version of it. The ONS coordinate for a postcode unit is the mean of the
    addresses in that unit snapped to the nearest of them - postcodes.io reports `quality: 1`
    for exactly that - so it is a unit-level answer, never the building; a large-user code is the
    organisation's mailroom; and a TERMINATED code's coordinate is frozen at the date it was
    retired. All three are "an area, not a building", which is the test this flag encodes. The
    register is a BETTER source than a town centroid, not a more PRECISE kind of thing, and
    flipping the flag would switch off the three consumers listed above (the dashed marker, the
    Gaps disclosure and `coord-provenance`'s hunt for a first-party coordinate) for pins that
    still need every one of them. Where the register answered - and whether the code was retired
    - is carried by the ledger locator, again with no new schema field."""
    import requests
    import statistics
    import normalize as _NN
    from collections import Counter
    cache = _load_cache(GEOCODE_CACHE)
    lib = _poi_lib()
    centroids = {p["name"].lower(): (p["lat"], p["lng"]) for p in lib.get("pois", []) if p["type"] == "city"}
    props = canonical["properties"]
    dirty = False
    todo = [p for p in props
            if not (isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float)))]

    def _pinned(p) -> bool:
        return isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))

    def _name(p) -> str:
        return str(p.get("park") or p.get("name") or "")[:40]

    # THE SECOND WORKLIST: APPROXIMATE PINS A LOCALITY-LEVEL ANSWER MAY REPLACE. (D10)
    #
    # `todo` above only ever fills an EMPTY coordinate. That made the locality layer inert on
    # every warm work dir: `seed_geocode.py` promised that a row carrying a postcode is "the one
    # way a coordinate finer than a town enters this pipeline", an operator seeded seven of
    # them, re-ran the same command, and NOTHING changed and NOTHING was printed - the town
    # centroid already sat in the slot, so the seed was never read. It took `--no-resume --from
    # merge` (documented nowhere) to rebuild canonical without pins so the seed could land.
    #
    # THE RULE. A pin flagged `coordsApprox: true` is, by its own label, a town-level stand-in
    # written by THIS function. A locality-level coordinate (an operator seed, a web-round
    # answer, or a live postcode geocode below) is a finer answer to the same question and may
    # replace it. A coordinate the SOURCE ITSELF stated (`coordsApprox` false or absent - a
    # tracker column, a brochure's DMS, a followed first-party map link) is NEVER touched: a
    # geocode does not override what the document says, and that one-way rule is what makes the
    # displacement safe. Both outcomes are said out loud below, because a correction channel that
    # reports nothing is the defect being fixed here, not the cure.
    #
    # `redo` also carries an approximate pin whose stated postcode has no COORDINATE under the
    # locality key - never asked, or asked and memoised as "no such place": on a warm dir with a
    # live network, that is the only route by which the D9 postcode fix reaches a project built
    # before it existed. A NEGATIVE memo does NOT settle it for the live helper (the D9 repair):
    # the memo's one job is to stop the web-enrichment round re-emitting the request (B02), and
    # a postcode can be added to OSM later, so the live path re-asks it exactly as the city-level
    # guard re-asks a city memo. Offline, `_postcode_first` returns nothing and the pin stays,
    # byte for byte. An unknown country is never asked (a postal code is only unambiguous within
    # a country) - here; the LATE step after the country fill asks it once one is known (D9c).
    redo: dict = {}  # id(p) -> normalised stated code, for a pinned-but-approximate property
    for p in props:
        if not _pinned(p):
            continue
        code = _locality_code(p)
        if not code:
            continue  # states no locality: the layer is inert for it, exactly as before
        city = str(p.get("city", "")).strip()
        country = str(p.get("country", "")).strip()
        if not city or _is_unknown_cc(city):
            continue
        hit = _cache_lookup_key(cache, city, country, code)
        loc_ll = _coords_cc(cache[hit])[0] if (hit and _key_code(hit)) else None
        if loc_ll is not None:
            if float(loc_ll[0]) == float(p["lat"]) and float(loc_ll[1]) == float(p["lng"]):
                continue  # already ON the locality pin (the pass after a displacement)
            if not p.get("coordsApprox"):
                print(f"NOTE geocode: id={p.get('id')} '{_name(p)}' keeps its stated coordinate: "
                      f"the cache holds a locality-level pin for its postcode '{code}', but the "
                      f"property's own source states a precise coordinate (coordsApprox false) "
                      f"and a geocode never overrides that. If the stated coordinate is wrong, "
                      f"correct it through work/repairs.json.")
                continue
            redo[id(p)] = code
        elif p.get("coordsApprox") and not _is_unknown_cc(country):
            redo[id(p)] = code  # no locality PIN yet: absent, or a negative memo to re-ask

    # POSTCODE FIRST. (D9) The one resolution step that writes at LOCALITY level, and the
    # writer `_cache_lookup_key`'s docstring said was missing ("every WRITER in this file keys on
    # the CITY level ... the locality level is filled ONLY by an operator seed"). Where the
    # record states a postal code and its country is known, the geocoder is asked for the
    # POSTCODE - instead of, not in addition to, the town name: one network round per property,
    # the same 1.1 s usage-policy sleep, the same circuit breaker on the first failure. Its
    # answer is an answer ABOUT THAT LOCALITY, so persisting it under the locality key is the
    # one write-back that asserts exactly the precision it has. A postcode the geocoder does
    # not know is memoised as a NEGATIVE locality entry, which `_cache_lookup_key` deliberately
    # falls THROUGH (a locality entry with no coordinate never answers), so the property gets
    # today's town-level answer by today's path. With no code stated, or no country, this
    # returns immediately and the whole step is inert - a corpus that quotes no postcodes is
    # byte-identical to before.
    #
    # WHAT THE NEGATIVE MEMO IS, AND IS NOT (the D9 repair). It is written from ONE thing only:
    # a real, successful "no such place" answer, which `_geocode_postcode` returns as a None
    # coordinate and RAISES for everything else. A transport failure writes nothing at this
    # level: in Cowork the helper-side network is dead by design, and a negative persisted from
    # that would have occupied every locality slot in the corpus, permanently, on every sandboxed
    # run - the D9/D10 defect re-created. And a memo that IS written is not a claim on the slot.
    # It stops the web-enrichment round re-emitting the request (`web_enrich._chain_spec` /
    # `cmd_plan` treat a present key as settled - B02, the exit-8 livelock) and it is the Gaps
    # Report's evidence that the code was asked; the LIVE helper re-asks it whenever it can reach
    # the geocoder, exactly as the city-level guard below re-asks a city memo ("a place can be
    # added to OSM later"), a seed overwrites it, and a web-round answer replaces it. The first
    # version of this step treated any PRESENT key as settled and so made its own negative
    # permanent for the pipeline's own channels; that is the asymmetry this comment exists to
    # stop coming back.
    #
    # AND, FOR GB ONLY, THE NEGATIVE IS CHECKED AGAINST THE NATIONAL REGISTER BEFORE IT IS
    # MEMOISED. (D9b) Nominatim's structured postcode search genuinely misses GB codes the ONS
    # register holds - WA5 5TN, BT1 2FF, BT28 3AX, measured, two of them Northern Ireland - and
    # each of those was falling through to the town centroid, which is the D9 failure class
    # reached by a different route. `_geocode_postcode` therefore asks api.postcodes.io in its
    # negative branch and returns a pin instead. Nothing here changes: the memo is still written
    # from a genuine "no such place" ONLY, a transport failure still raises and still writes
    # nothing, and a register that is unreachable is indistinguishable from one that has never
    # heard of the code - both leave the negative exactly as it was. This is a COVERAGE fix, not
    # the D9 rescue: NN6 7ES, the code that motivated D9, resolves through Nominatim and never
    # reaches the register.
    _offline_msg = ("geocoder unreachable from this sandbox (blocked/offline) - fetch each "
                    "city's coordinates with the orchestrator's WebFetch, seed them via "
                    "`python helpers/seed_geocode.py coords.json --cache-dir <work>` "
                    "(SKILL.md 'Sandbox offline'), then re-run enrich --geocode")

    def _postcode_first(p, city, country, known, code):
        """([lat,lng], 'CC') freshly resolved for the record's STATED postcode, else (None, '').
        Writes the locality-level cache entry itself: a pin, or the negative memo (a None
        coordinate and an empty cc, exactly the pair `_geocode_postcode` returns for "no such
        place", so the memo has one spelling and cannot drift from the answer it records).
        Guards on the COORDINATE, never on key presence: a negative memo is re-asked when the
        geocoder is reachable (B02). A transport failure writes nothing and trips the circuit
        breaker, the same path `_geocode_one`'s failure takes below."""
        nonlocal dead, dirty
        if not code or not known:
            return None, ""       # nothing stated, or ambiguous without a country: not asked
        lk = _geo_key(city, country, code)
        if _coords_cc(cache.get(lk))[0] is not None:
            return None, ""       # a locality PIN is already there; the caller read it from the cache
        if dead:
            return None, ""       # offline: nothing asked, nothing written, the pin stays
        try:
            pll, pcc = _geocode_postcode(requests, code, country)
            ent = {"latlng": pll, "cc": pcc}     # a pin, or the negative memo
            if cache.get(lk) != ent:             # a re-asked memo that is still "no" is not a write
                cache[lk] = ent
                dirty = True
                _save_cache(GEOCODE_CACHE, cache)  # incremental - a kill keeps progress
            return (pll, pcc) if pll else (None, "")
        except Exception:
            dead = True  # offline/blocked - stop trying, serve cache + fallbacks
            gaps.append(_offline_msg)
            print(f"NOTE {_offline_msg}")
            return None, ""
        finally:
            time.sleep(1.1)  # Nominatim usage policy - also on the failure path

    # PASS A: resolve each UNAMBIGUOUS city (cached, or a unique-name gazetteer/network hit).
    # An AMBIGUOUS bare name (same name in >1 country, unknown country) MISSES here - the
    # ambiguity-aware _gazetteer_lookup returns nothing without a dominant country - and is
    # DEFERRED to the dominant-country PASS B, never resolved to a pre-baked wrong-country
    # pick (bug #3). In Cowork the helper-side network is dead BY DESIGN (the orchestrator
    # seeds the cache via seed_geocode.py); the first network failure circuit-breaks.
    dead = False
    res = {}  # id(p) -> [latlng, cc, known, city, country, source]
    # WHICH cache entry answered, per property: id(p) -> the resolved key. Kept in its OWN map
    # rather than as a seventh element of `res`, because PASS B unpacks a `res` row positionally
    # into exactly six names and a widened row would break there. It feeds the LEDGER locator
    # only: two properties in one town holding two DIFFERENT pins must not carry IDENTICAL
    # provenance rows, or the audit artefact cannot tell the reader where each pin came from.
    # City-level (so `_key_code` -> "") for every record that states no locality code. (G1)
    gkeys: dict = {}
    for p in todo:
        city = str(p.get("city", "")).strip()
        country = str(p.get("country", "")).strip()
        known = not _is_unknown_cc(country)
        # THE MOST SPECIFIC LOCALITY THIS RECORD STATES - "" in most markets, and with "" every
        # line below is byte-identical to the city-only reader. `_cache_lookup` is taken in its
        # two documented halves here (the KEY, then its value through `_coords_cc`) so the
        # provenance is captured without resolving the same lookup twice. (G1)
        code = _locality_code(p)
        gkeys[id(p)] = _gk = _cache_lookup_key(cache, city, country, code)
        latlng, cc = _coords_cc(cache[_gk]) if _gk else (None, "")
        src = "cache" if latlng is not None else ""
        # POSTCODE FIRST (D9): when the cache answered at TOWN level or not at all, and the
        # record states a postcode, ask for the postcode BEFORE accepting the town centroid.
        # A locality-level cache hit (`_key_code(_gk)` non-empty) is already the finer answer.
        if not _key_code(_gk):
            pll, pcc = _postcode_first(p, city, country, known, code)
            if pll:
                # `_postcode_src`, not a literal "postcode": the answer may have come from the GB
                # national register behind Nominatim's negative (D9b), and the ledger has to be
                # able to name which one - see `_coord_locator`. It reads (and consumes) a note
                # written one statement ago, so it must sit immediately after the lookup.
                latlng, cc, src = pll, pcc, _postcode_src(code, country)
                gkeys[id(p)] = _geo_key(city, country, code)
        # OFFLINE FIRST: the bundled European city gazetteer resolves real city coordinates
        # (+ country) with ZERO network, so the map works in Cowork without the exit-8
        # round-trip; the browser handoff is reserved strictly for live ROUTING.
        if latlng is None and city and not _is_unknown_cc(city):
            gll, gcc = _gazetteer_lookup(city, country)
            if gll:
                latlng, cc, src = gll, (gcc or cc), "gazetteer"
                # CITY-LEVEL KEY, ON PURPOSE - and the same holds for every other TOWN-level
                # writer in this function. A city gazetteer centroid, a city-NAME geocode and a
                # no-such-place memo are all answers about the TOWN; writing one under a
                # LOCALITY key would assert a precision it does not have and would settle that
                # locality forever, since any key present in the cache is never re-asked. The
                # ONLY locality-level writer here is `_postcode_first` (D9), whose answer is
                # about the stated postcode itself. See `_cache_lookup_key`.
                cache[f"{city}|{country}".lower()] = {"latlng": latlng, "cc": cc}
                dirty = True
        # never geocode a sentinel/placeholder city ('tbd', '??') - it would land a bogus
        # pin. An AMBIGUOUS unknown-country name is NOT network-queried here either (a global
        # Nominatim guess would re-introduce bug #3) - it is deferred to the dominant-country
        # PASS B. Unique names and known countries still resolve live.
        ambiguous = (not known) and bool(city) and (_NN._norm_city(city) in _gazetteer_multi())
        if latlng is None and city and not _is_unknown_cc(city) and not dead and not ambiguous:
            try:
                latlng, cc = _geocode_one(requests, city, country if known else "")
                if latlng:
                    src = "nominatim"
                    cache[f"{city}|{country}".lower()] = {"latlng": latlng, "cc": cc}
                    dirty = True
                    _save_cache(GEOCODE_CACHE, cache)  # incremental - a kill keeps progress
                else:
                    # NEGATIVE MEMO on the LIVE path too (B02). "No such place" is a real,
                    # successful answer - usually a mis-parsed city cell ("Available Q3
                    # 2027"). Caching only successes meant the same name was re-queried
                    # every round and kept the run emitting exit 8 forever; `geocode: true`
                    # is the DEFAULT in every generated project.yaml, so one bad cell was
                    # enough. `latlng: None` is already tolerated by _cache_lookup /
                    # _coords_cc, so the property keeps an honest missing coordinate.
                    cache[f"{city}|{country}".lower()] = {"latlng": None, "cc": ""}
                    dirty = True
                    _save_cache(GEOCODE_CACHE, cache)
            except Exception:
                latlng, cc = None, ""
                dead = True  # offline/blocked - stop trying, serve cache + fallbacks
                # say HOW to recover immediately, not after a silent degrade: the
                # orchestrator's web tools work even when this sandbox's don't
                msg = ("geocoder unreachable from this sandbox (blocked/offline) - fetch each "
                       "city's coordinates with the orchestrator's WebFetch, seed them via "
                       "`python helpers/seed_geocode.py coords.json --cache-dir <work>` "
                       "(SKILL.md 'Sandbox offline'), then re-run enrich --geocode")
                gaps.append(msg)
                print(f"NOTE {msg}")
            finally:
                time.sleep(1.1)  # Nominatim usage policy - also on the failure path
        res[id(p)] = [latlng, cc, known, city, country, src]

    # dataset-dominant country = mode of the well-clustered located points (robust median).
    pts = [(ll, cc) for ll, cc, *_ in res.values() if ll and ll[0] is not None]
    med_lat = statistics.median([ll[0] for ll, _ in pts]) if pts else None
    med_lng = statistics.median([ll[1] for ll, _ in pts]) if pts else None
    near = [cc for ll, cc in pts if cc and med_lat is not None
            and _haversine_km(ll[0], ll[1], med_lat, med_lng) < 1000]
    dominant = Counter(near).most_common(1)[0][0] if near else ""

    # PASS B: resolve every STILL-unresolved property. For an unknown-country bare name we
    # constrain to the dataset-dominant country OFFLINE (the gazetteer carries the per-country
    # key), so an ambiguous name lands in the RIGHT country or stays tbd - NEVER a pre-baked
    # wrong-country pick (bug #3). Only a genuinely unresolvable name hits the network, and
    # only when it is live; otherwise it is left as an honest gap (no invented pin).
    for p in todo:
        r = res[id(p)]
        latlng, cc, known, city, country, src = r
        if latlng and latlng[0] is not None:
            continue  # already resolved in PASS A (cache / unique-name gazetteer / network)
        if not city or _is_unknown_cc(city):
            continue  # sentinel city - honest gap emitted at fill time
        gll, gcc = _gazetteer_lookup(city, country, dominant=("" if known else dominant))
        if gll:
            r[0], r[1], r[5] = gll, (gcc or cc), "gazetteer-dominant"
            cache[f"{city}|{country}".lower()] = {"latlng": gll, "cc": gcc or cc}
            dirty = True
            if not known and _NN._norm_city(city) in _gazetteer_multi():
                gaps.append(f"geocode: '{city}' is ambiguous across countries - resolved to "
                            f"{gcc or dominant} (dataset-dominant); verify the pin")
            continue
        # An AMBIGUOUS unknown-country name with NO dominant country cannot be constrained, so
        # it must NOT fall through to a GLOBAL Nominatim query (country="") - that would
        # re-introduce bug #3's wrong-country pick with no safety flag. Leave an honest tbd+gap.
        # A UNIQUE unknown-country name (amb False) may still be globally geocoded; a known
        # country is queried directly.
        amb = (not known) and (_NN._norm_city(city) in _gazetteer_multi())
        if not dead and (known or dominant or not amb):
            try:
                ll2, cc2 = _geocode_one(requests, city, country if known else (dominant or ""))
                if ll2:
                    r[0], r[1], r[5] = ll2, (cc2 or (dominant if not known else "")), "nominatim"
                    cache[f"{city}|{country}".lower()] = {
                        "latlng": ll2, "cc": cc2 or (dominant if not known else "")}
                    dirty = True
                    _save_cache(GEOCODE_CACHE, cache)
            except Exception:
                dead = True
                gaps.append("geocoder unreachable from this sandbox - seed coordinates via "
                            "`python helpers/seed_geocode.py coords.json --cache-dir <work>` "
                            "(SKILL.md 'Sandbox offline'), then re-run enrich --geocode")
            finally:
                time.sleep(1.1)
        if r[0] is None or r[0][0] is None:
            if amb:
                gaps.append(f"geocode: '{city}' is ambiguous across countries and no dominant "
                            f"country could constrain it - left as a gap (verify)")
            else:
                gaps.append(f"geocode: could not resolve '{city}' to a confident location "
                            f"(country {'unknown' if not known else country}) - left as a gap, "
                            f"verify manually")

    # SAFETY / correction: a point resolved with an UNKNOWN country that lands >2000 km from
    # the cluster is almost certainly a wrong same-name hit on another continent (a stale cache
    # or a unique-name Nominatim pick). Re-query it constrained to the dominant country when the
    # network is live; whenever it cannot be CORRECTED (offline, the re-query raised, or no
    # in-country match) emit an HONEST gap so a wrong-continent pin never ships silently. A
    # dominant-country resolution above is already constrained, so it is exempt.
    if dominant and med_lat is not None:
        for p in todo:
            r = res[id(p)]
            ll, cc, known, city, country = r[0], r[1], r[2], r[3], r[4]
            if known or not ll or ll[0] is None or r[5] == "gazetteer-dominant":
                continue
            if _haversine_km(ll[0], ll[1], med_lat, med_lng) <= 2000:
                continue
            corrected = False
            if not dead:
                try:
                    ll2, cc2 = _geocode_one(requests, city, dominant)
                    time.sleep(1.1)
                    if ll2:
                        r[0], r[1], r[5] = ll2, (cc2 or dominant), "nominatim"
                        cache[f"{city}|{country}".lower()] = {"latlng": ll2, "cc": cc2 or dominant}
                        dirty = True
                        gaps.append(f"geocode: '{city}' was ambiguous worldwide - constrained to "
                                    f"{dominant} (verify the pin)")
                        corrected = True
                except Exception:
                    dead = True  # the network is down after all - stop trying, flag the rest
            if not corrected:
                gaps.append(f"geocode: '{city}' (country unknown) landed far from the other "
                            f"options and could not be re-checked - verify the pin")

    # THE REDO WORKLIST (D10): resolve each approximate pin's LOCALITY answer - from the cache
    # when a locality entry already holds a coordinate (an operator seed, a web-round answer, or
    # last pass's postcode geocode), else by asking for the stated postcode live. Runs AFTER the
    # passes above so the unpinned properties - the primary job - get the network first and the
    # dominant-country statistics are computed from exactly the points they always were. No
    # city-level resolution happens here at all: the property already HAS its town pin, so a
    # city query would be a second network round that can only repeat what is on the card.
    for p in props:
        code = redo.get(id(p))
        if not code:
            continue
        city = str(p.get("city", "")).strip()
        country = str(p.get("country", "")).strip()
        known = not _is_unknown_cc(country)
        _gk = _cache_lookup_key(cache, city, country, code)
        if _key_code(_gk):
            latlng, cc = _coords_cc(cache[_gk])
            src = "cache"
        else:
            latlng, cc = _postcode_first(p, city, country, known, code)
            # The same provenance read as PASS A: a displaced pin must name the register that
            # answered just as an original pin does, or the D10 correction channel would report
            # a register answer as a Nominatim one. (D9b)
            src = _postcode_src(code, country) if latlng else ""
            _gk = _geo_key(city, country, code) if latlng else ""
        gkeys[id(p)] = _gk
        if latlng and latlng[0] is not None:
            res[id(p)] = [latlng, cc, known, city, country, src]

    # Records whose country is still UNKNOWN here: every postcode step above skipped them. The
    # fill below may give them one (the town lookup's cc, or the pin's reverse geocode), and the
    # LATE postcode step after it gives them the ask they were denied. (D9c)
    cc_unknown0 = {id(p) for p in props if _is_unknown_cc(p.get("country"))}
    filled = 0
    displaced = 0
    for p in props:
        if id(p) in redo:
            # DISPLACEMENT (D10): a locality-level coordinate replaces the approximate town pin.
            # Said out loud, per property, naming what moved and by how much - the operator who
            # seeded it must be able to see it land. A redo property whose postcode did NOT
            # resolve (or could not be asked) has no `res` row and keeps its pin untouched,
            # byte for byte; the Gaps Report line below discloses that state.
            r = res.get(id(p))
            if r and r[0] and r[0][0] is not None:
                old_lat, old_lng = p["lat"], p["lng"]
                p["lat"], p["lng"], p["coordsApprox"] = r[0][0], r[0][1], True
                km = _haversine_km(old_lat, old_lng, p["lat"], p["lng"])
                city = str(p.get("city", "")).strip()
                print(f"geocode: id={p.get('id')} '{_name(p)}': approximate town pin "
                      f"({old_lat:.5f}, {old_lng:.5f}) replaced by the locality-level coordinate "
                      f"for its stated postcode '{redo[id(p)]}' ({p['lat']:.5f}, {p['lng']:.5f}), "
                      f"{km:.1f} km away")
                displaced += 1
                if updates is not None:
                    sf, st, loc = _coord_locator(r[5], city, _key_code(gkeys.get(id(p), "")))
                    updates.append(_trace(p.get("id"), "lat", p["lat"], sf, loc, st))
                    updates.append(_trace(p.get("id"), "lng", p["lng"], sf, loc, st))
        if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float)):
            # P2-5 / bug #4: an already-located property (a tracker/email row that ARRIVED
            # with coords) can still have country '??'. The AUTHORITATIVE signal is its OWN
            # pin - a name lookup must NEVER override where the pin actually is. So reverse-
            # geocode the pin FIRST (ground truth) when the network is live; only offline do
            # we accept a name-based country, and ONLY when the gazetteer's coordinate for
            # that name/country AGREES with the pin (<=75 km). Never overrides/invents.
            if _is_unknown_cc(p.get("country")):
                city = str(p.get("city", "")).strip()
                cc = ""
                cc_sf, cc_st = "Nominatim (OSM geocoder)", "web"
                cc_loc = f"country for the pin of '{city or p.get('id')}'"
                if not dead:
                    try:
                        cc = _reverse_cc(requests, p["lat"], p["lng"])
                    except Exception:
                        dead = True
                    finally:
                        time.sleep(1.1)
                if not cc and city and not _is_unknown_cc(city):
                    # a CACHE hit is operator-seeded (seed_geocode.py) - its coord IS the pin;
                    # trust its country when that coord agrees with the pin (or carries none), so
                    # the documented offline seed workflow still fills a city the bundled
                    # gazetteer does not carry (a small/non-European town).
                    # the record's own locality is passed through: a locality entry sits
                    # CLOSER to the pin than the town centroid, so it is a strictly better
                    # input to the 75 km agreement test below. No code stated -> the city
                    # entry, exactly as before. (A country is a fact about the town either
                    # way, so the cc this yields is unchanged.)
                    _ll, ccn = _cache_lookup(cache, city, "", _locality_code(p))
                    if ccn and (not _ll or _ll[0] is None
                                or _haversine_km(p["lat"], p["lng"], _ll[0], _ll[1]) <= 75):
                        cc = ccn
                        cc_sf, cc_st = "geocode_cache.json", "cache"
                        cc_loc = f"seeded geocode cache '{city}'"
                    # else fall back to the NAME gazetteer, accepted ONLY when its city-centroid
                    # agrees with the pin within 75 km (never override where the pin actually is).
                    if not cc:
                        _gll, ccn = _gazetteer_lookup(city, "")
                        if ccn:
                            gll = _gazetteer_lookup(city, ccn)[0]
                            if gll and _haversine_km(p["lat"], p["lng"], gll[0], gll[1]) <= 75:
                                cc = ccn
                                cc_sf, cc_st = "assets/cities_dataset.json", "dataset"
                                cc_loc = f"city gazetteer '{city}' (agrees with pin)"
                            else:
                                gaps.append(f"country for id={p.get('id')} ('{city}') left tbd: the "
                                            f"name-based country pick disagrees with the property's "
                                            f"own coordinates - verify (reverse-geocode unavailable)")
                if cc and _is_unknown_cc(p.get("country")):
                    p["country"] = cc
                    if updates is not None:
                        updates.append(_trace(p.get("id"), "country", cc, cc_sf, cc_loc, cc_st))
            continue
        r = res.get(id(p))
        latlng, cc, src = (r[0], r[1], (r[5] if len(r) > 5 else "")) if r else (None, "", "")
        city = str(p.get("city", "")).strip()
        from_centroid = False
        if latlng is None:  # offline / not found -> city-centroid fallback (CEE seed data)
            latlng = list(centroids.get(city.lower(), (None, None)))
            from_centroid = latlng[0] is not None
        if latlng and latlng[0] is not None:
            p["lat"], p["lng"], p["coordsApprox"] = latlng[0], latlng[1], True
            if cc and _is_unknown_cc(p.get("country")):  # fill unknown country from the same source
                p["country"] = cc
                if updates is not None:
                    if src in ("gazetteer", "gazetteer-dominant"):
                        csf, cst, cloc = "assets/cities_dataset.json", "dataset", f"city gazetteer '{city}'"
                    elif src == "cache":
                        csf, cst, cloc = "geocode_cache.json", "cache", f"geocode cache '{city}'"
                    elif src.startswith("postcode"):
                        # A register answer fills the country from the register, not from OSM
                        # (D9b). The value is the same 'GB' either way, but a ledger row that
                        # credited Nominatim for a code Nominatim does not hold would be a
                        # traceable-looking row pointing at a source that cannot corroborate it.
                        _pc = _key_code(gkeys.get(id(p), "")).upper()
                        # The register arm below is UNREACHABLE as the gate stands today, and is
                        # kept deliberately rather than by oversight: this whole block only runs
                        # when the record's country is UNKNOWN, while `_is_gb` has already
                        # required it to be GB or UK for the register to have been asked at all.
                        # It is here so that the ledger row stays truthful if that gate ever
                        # widens to a market where the country IS unknown at fill time. The cost
                        # of keeping it is four lines; the cost of dropping it is a row crediting
                        # OSM for a coordinate only the register holds, which is the exact class
                        # of untraceable claim the arm exists to prevent.
                        if src.startswith("postcode-register-"):
                            csf, cst, cloc = (_REGISTER_FILE, "web",
                                              f"GB national postcode register entry for the "
                                              f"stated postcode '{_pc}' ('{city}')")
                        else:
                            csf, cst, cloc = ("Nominatim (OSM geocoder)", "web",
                                              f"geocode of the stated postcode '{_pc}' ('{city}')")
                    else:
                        csf, cst, cloc = "Nominatim (OSM geocoder)", "web", f"geocode of '{city}'"
                    updates.append(_trace(p.get("id"), "country", cc, csf, cloc, cst))
            filled += 1
            if updates is not None:  # trace rows so the ledger matches the deliverable
                sf, st, loc = _coord_locator(src, city, _key_code(gkeys.get(id(p), "")),
                                             from_centroid=from_centroid)
                updates.append(_trace(p.get("id"), "lat", p["lat"], sf, loc, st))
                updates.append(_trace(p.get("id"), "lng", p["lng"], sf, loc, st))
        else:
            gaps.append(f"could not geocode '{city}' (property id={p.get('id')})")

    # LATE POSTCODE FIRST. (D9c) A UK brochure rarely states its country: GB arrives only in the
    # fill above, AFTER pass A and the redo list skipped the postcode as ambiguous without one.
    # So the town centroid shipped (measured: 9 of 28 cards 1.6-8.6 km off, one in the wrong
    # NUTS-3 area), and the disclosure below then counted each code as never asked - sending a
    # run WITH network to exit 8 for a request this pass could have made itself. Each record
    # whose country was unknown above and is known now gets the step it was denied: the
    # locality pin when the cache holds one, else a live ask through `_postcode_first`, so a
    # genuine "no such place" is memoised exactly as before and exit 8 cannot loop on it. The
    # D10 one-way rule holds: only an approximate or absent pin is touched. A code that is NOT
    # asked says why, on stdout and in the disclosure below.
    skip_why: dict = {}  # id(p) -> why its stated postcode was not asked
    todo_ids = {id(q) for q in todo}
    for p in props:
        if id(p) not in cc_unknown0 or (_pinned(p) and not p.get("coordsApprox")):
            continue
        code = _locality_code(p)
        city = str(p.get("city", "")).strip()
        country = str(p.get("country", "")).strip()
        if not code or not city or _is_unknown_cc(city) or _key_code(gkeys.get(id(p), "")):
            continue  # nothing stated, or already answered at locality level this pass
        lk = _geo_key(city, country, code)
        pll, pcc = _coords_cc(cache.get(lk))
        src = "cache"
        if pll is None:
            why = ("country still unknown" if _is_unknown_cc(country)
                   else "circuit breaker tripped earlier in this pass" if dead else "")
            if not why:
                pll, pcc = _postcode_first(p, city, country, True, code)
                src = _postcode_src(code, country) if pll else ""  # D9b provenance, read at once
                why = "offline (the postcode ask failed)" if dead else ""
            if why:
                skip_why[id(p)] = why
                print(f"NOTE geocode: id={p.get('id')} '{_name(p)}' postcode '{code}' "
                      f"not asked: {why}")
            if pll is None:
                continue  # not asked, or a genuine "no such place" (memoised): the pin stays
        if _pinned(p) and float(p["lat"]) == float(pll[0]) and float(p["lng"]) == float(pll[1]):
            continue
        old = (p["lat"], p["lng"]) if _pinned(p) else None
        p["lat"], p["lng"], p["coordsApprox"] = pll[0], pll[1], True
        gkeys[id(p)] = lk
        if old is None:
            filled += 1
        elif id(p) not in todo_ids:  # a town pin THIS pass wrote is already counted as filled
            km = _haversine_km(old[0], old[1], p["lat"], p["lng"])
            print(f"geocode: id={p.get('id')} '{_name(p)}': approximate town pin "
                  f"({old[0]:.5f}, {old[1]:.5f}) replaced by the locality-level coordinate "
                  f"for its stated postcode '{code}' ({p['lat']:.5f}, {p['lng']:.5f}), "
                  f"{km:.1f} km away")
            displaced += 1
        if updates is not None:
            sf, st, loc = _coord_locator(src, city, _key_code(lk))
            updates.append(_trace(p.get("id"), "lat", p["lat"], sf, loc, st))
            updates.append(_trace(p.get("id"), "lng", p["lng"], sf, loc, st))
    if dirty:
        _save_cache(GEOCODE_CACHE, cache)

    # DISCLOSURE (D9): a property that STATES a postcode and still sits on a TOWN pin says so in
    # the Gaps Report, in one line per cause, naming each property and its code. On the measured
    # run the town pin was 9 km across a county line and nothing anywhere said the postcode had
    # not been used; the Source Ledger even called the resulting region change a "harmonisation".
    # Two causes, two remedies: a code the geocoder does not KNOW (negative memo - the operator
    # seeds the coordinate or repairs the pin) and a code that could not be ASKED from here
    # (offline - the web-enrichment round or a seed supplies it). Rebuilt every pass, because the
    # geocode layer's gap bucket is the FINAL state, and the state persists until the pin moves.
    unresolved, waiting = [], []
    for p in props:
        if not _pinned(p) or not p.get("coordsApprox"):
            continue
        code = _locality_code(p)
        city = str(p.get("city", "")).strip()
        country = str(p.get("country", "")).strip()
        if not code or not city or _is_unknown_cc(city) or _is_unknown_cc(country):
            continue
        ent = cache.get(_geo_key(city, country, code))
        if ent is None:
            why = skip_why.get(id(p))  # the late step's reason, when it is the one that skipped (D9c)
            waiting.append(f"id={p.get('id')} '{_name(p)}' {code}" + (f" ({why})" if why else ""))
        elif _coords_cc(ent)[0] is None:
            unresolved.append(f"id={p.get('id')} '{_name(p)}' {code}")
    # THE SANDBOX HANDOFF NEEDS TO KNOW (the D9 repair). run.py asks the web-enrichment round
    # for `--geocode` only when a property has NO coordinate at all; in Cowork the bundled
    # gazetteer pins every European town, so every property arrives pinned and the postcode
    # request `web_enrich.plan` builds for an approximate pin would never be handed over - the
    # fix would be inert in exactly the sandbox it was written for. The count of stated
    # postcodes this pass could not ask travels in `meta.enrichment`, beside `pois_live` and
    # `osrm_done` which run.py already reads for the same exit-8 decision, so the handoff can
    # fire on it. A settled code (a pin or a memo) is not counted: the round has nothing to ask.
    enr_flags = canonical.setdefault("meta", {}).setdefault("enrichment", {})
    enr_flags["postcodes_unasked"] = len(waiting)
    if unresolved:
        gaps.append(
            # THIS LINE MUST NOT CLAIM WHICH SOURCES WERE ASKED, and an earlier draft did.
            # It said "and, for GB, nor does the national postcode register", but this bucket is
            # built from CACHE STATE alone - a locality entry whose coordinate is None - and it
            # records nothing about who was asked. That memo can equally have been written by the
            # web-enrichment round, whose `cmd_ingest` memoises an empty Nominatim array with NO
            # register leg (D9b runs only in this process, behind helper-side `requests`). So on
            # a Cowork work dir the sentence asserted an enquiry that never happened, about the
            # one code class the register is most likely to hold, and then told the operator the
            # remaining route was a hand-seed. That is worse than saying nothing: the clause
            # exists to stop a pointless re-run, and there it discouraged the re-run that would
            # have WORKED. It now states only what the bucket knows, and names the register as a
            # route still worth trying rather than one already exhausted.
            f"{len(unresolved)} property(ies) state a postcode that resolved to no coordinate, "
            f"so their pin is the TOWN centre (coordsApprox): " + ", ".join(unresolved[:8]) +
            ". Verify each pin against the brochure. For a GB code, check whether this pass could "
            "reach the national postcode register (D9b asks it only from a run with helper-side "
            "network, never through the web-enrichment round), because a re-run WITH network may "
            "resolve it. Otherwise supply the site's coordinate: seed it with `python "
            "helpers/seed_geocode.py coords.json --cache-dir <work>` using a row that carries the "
            "postcode, or record the pin in work/repairs.json, then re-run.")
    if waiting:
        gaps.append(
            f"{len(waiting)} property(ies) state a postcode that could not be asked from this "
            f"sandbox (geocoder unreachable), so their pin is the town centre until the "
            f"web-enrichment round or a seed supplies the postcode coordinate: "
            + ", ".join(waiting[:8]) + ".")
    # the third cause (D9c): no country, so the code was never asked - not counted as waiting,
    # because the web round cannot ask it either
    nocc = [f"id={p.get('id')} '{_name(p)}' {_locality_code(p)}" for p in props
            if skip_why.get(id(p)) == "country still unknown"]
    if nocc:
        gaps.append(
            f"{len(nocc)} property(ies) state a postcode but no country could be established, so "
            f"the postcode was not asked (a postal code is ambiguous without a country) and the "
            f"pin is the town centre: " + ", ".join(nocc[:8]) + ". State the country in the "
            f"source or work/repairs.json, then re-run.")
    if displaced:
        print(f"geocode: {displaced} approximate town pin(s) replaced by locality-level "
              f"coordinates (see the lines above)")
    return filled + displaced


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
POI_TYPES = ("air", "port", "rail", "border", "city")
# per-type give-up caps (km): inside OVERPASS_RADIUS_M the genuine OSM nearest
# wins; beyond it the curated MAJOR-facilities library supplements up to these
# caps (labelled as such); past the cap we honestly give up - never a far stand-in.
POI_MAX_KM = {"air": 600, "port": 800, "rail": 300, "border": 400, "city": 300, "city_major": 300}


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _classify_osm(tags: dict):
    if tags.get("aeroway") == "aerodrome":
        return "air"
    if tags.get("industrial") == "port" or tags.get("landuse") == "port":
        return "port"
    if tags.get("seamark:type") == "harbour":
        # FREIGHT harbours only - tag-based, language-neutral filters (a Madrid
        # park boat jetty shipped as "nearest port" before): marinas carry
        # leisure=marina / a marina-ish seamark category
        if tags.get("leisure") == "marina":
            return None
        cat = str(tags.get("seamark:harbour:category", ""))
        if cat and not re.search(r"port|cargo|container|ferry|ro.?ro|bulk", cat, re.I):
            return None
        return "port"
    if tags.get("railway") == "yard" or tags.get("landuse") == "railway":
        return "rail"
    if tags.get("barrier") == "border_control":
        # airport/indoor security checkpoints (amenity=security_control, indoor
        # 'level') are not country border crossings
        if tags.get("amenity") == "security_control" or "level" in tags:
            return None
        return "border"
    if tags.get("place") == "city":
        return "city"
    return None


# the ONE radius the public Overpass server demonstrably handles for this combined
# query (empirically calibrated 2026-06-11: 180km = 31KB/all types found; 540km+
# = "runtime error: out of memory using about 2048 MB" EVEN nodes-only, on the
# main server and both mirrors). Beyond it, attach_pois supplements missing types
# from the curated major-facilities library, explicitly labelled.
OVERPASS_RADIUS_M = 180000


def _overpass_query(lat: float, lng: float, radius_m: int | None = None, cap: int = 80) -> str:
    """The combined all-POI-types Overpass query for one point (radius defaults to
    the calibrated OVERPASS_RADIUS_M; bigger per-point scans OOM the public
    servers - verified, not assumed).

    Ways CANNOT be dropped for lightness (major airports/ports/terminals are
    polygons in OSM - the IATA tag sits on the perimeter, not a node; node-only
    would silently lose the biggest facilities). Instead the output is SPLIT:
    nodes print with coordinates (`out qt`), ways print TAGS + CENTRE ONLY
    (`out tags center qt`) - dropping the polygons' node-ID arrays, the actual
    payload bulk, while the nearest-of-type result stays identical."""
    r = radius_m if radius_m is not None else OVERPASS_RADIUS_M
    nodes = (f'node["aeroway"="aerodrome"]["iata"](around:{r},{lat},{lng});'
             f'node["industrial"="port"](around:{r},{lat},{lng});'
             f'node["seamark:type"="harbour"](around:{r},{lat},{lng});'
             f'node["railway"="yard"](around:{r},{lat},{lng});'
             f'node["barrier"="border_control"](around:{r},{lat},{lng});'
             f'node["place"="city"](around:{r},{lat},{lng});')
    ways = (f'way["aeroway"="aerodrome"]["iata"](around:{r},{lat},{lng});'
            f'way["landuse"="port"](around:{r},{lat},{lng});'
            f'way["railway"="yard"]["name"](around:{r},{lat},{lng});')
    return (f"[out:json][timeout:60];({nodes});out qt {cap};"
            f"({ways});out tags center qt {cap};")


def _overpass_around(lat: float, lng: float, radius_m: int | None = None,
                     timeout: int = 90) -> list:
    """One combined Overpass query for all POI types around a point. RAISES on a
    failed response - including the server's HTTP-200 'runtime error: out of
    memory' remark and busy-server 504s, which MUST NOT parse as an empty result
    (an errored response cached as 'no POIs nearby' poisons the cache silently).
    One retry with backoff for the transient-busy case."""
    import requests
    q = _overpass_query(lat, lng, radius_m)
    last = None
    for attempt in (1, 2):
        try:
            resp = requests.post(OVERPASS_ENDPOINT, data={"data": q}, headers=UA, timeout=timeout)
            if resp.status_code in (429, 504):
                last = RuntimeError(f"Overpass busy (HTTP {resp.status_code})")
                time.sleep(6 * attempt)
                continue
            j = resp.json()
            remark = str(j.get("remark", ""))
            if "error" in remark.lower():
                raise RuntimeError(f"Overpass remark: {remark[:120]}")
            return j.get("elements", [])
        except RuntimeError:
            raise
        except Exception as e:
            last = e
            time.sleep(4 * attempt)
    raise RuntimeError(f"Overpass unreachable: {last}")


def _nearest_from_elements(lat: float, lng: float, elements: list, found: dict | None = None) -> dict:
    """Fold raw Overpass elements into the nearest-of-each-type dict. Shared by the
    live expanding-radius path and web_enrich's ingest, so both produce identical
    genuine-nearest results."""
    found = found if found is not None else {}
    for el in elements:
        t = _classify_osm(el.get("tags") or {})
        if not t:
            continue
        c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        if c.get("lat") is None:
            continue
        km = round(_haversine_km(lat, lng, c["lat"], c["lon"]), 1)
        if km > POI_MAX_KM.get(t, 400):
            continue
        if t not in found or km < found[t]["km"]:
            name = (el.get("tags") or {}).get("name") or t.title()
            found[t] = {"name": name, "type": t, "lat": round(c["lat"], 5),
                        "lng": round(c["lon"], 5), "km": km}
    return found


def nearest_pois_for(lat: float, lng: float) -> dict:
    """The genuine nearest of each type via OSM/Overpass within the calibrated
    radius (one light query; bigger per-point scans OOM the public servers).
    Missing types are simply absent - attach_pois supplements them from the
    curated major-facilities library, explicitly labelled. Raises on a
    network/Overpass failure so the caller can record an honest gap rather than
    invent a far stand-in."""
    return _nearest_from_elements(lat, lng, _overpass_around(lat, lng))


def _library_supplement(lat: float, lng: float, found: dict, types: tuple = POI_TYPES) -> dict:
    """Outage-only fallback: fill the requested `types` NOT already in `found` from the curated
    major-facilities library, capped by POI_MAX_KM and LABELLED `library:True`. Callers pass
    only the types whose COMPLETE dataset is ABSENT (air/port/rail from poi_dataset, border from
    borders_dataset, city from cities_major_dataset), so when those assets are present the
    curated CEE stand-ins are NEVER used for a type that has a complete set (retiring committee
    bug #1). It remains a graceful stopgap only when an asset is missing, or (OSM path) for a
    type beyond the scan radius - the note says exactly what it is; live discovery refines it."""
    lib = _poi_lib()
    for t in types:
        if t in found:
            continue
        best = None
        for q in lib.get("pois", []):
            if q.get("type") != t or not isinstance(q.get("lat"), (int, float)):
                continue
            km = round(_haversine_km(lat, lng, q["lat"], q["lng"]), 1)
            if km <= POI_MAX_KM.get(t, 400) and (best is None or km < best["km"]):
                best = {"name": q["name"], "type": t, "lat": q["lat"], "lng": q["lng"],
                        "km": km, "library": True}
        if best is not None:
            found[t] = best
    return found


def attach_pois(canonical: dict, gaps: list) -> int:
    """Attach the GENUINE nearest port/airport/rail/border/city to each option,
    discovered live from OSM/Overpass - never a preloaded stand-in (a curated set
    would make the skill lazily return a far 'major' POI instead of the true
    nearest). A type with no real feature found, or Overpass unreachable (e.g. an
    offline build), is an honest Gaps line; the dashboard's client-side lookup
    fills it when the broker opens the file online."""
    cache = _load_cache(POI_OSM_CACHE)
    located = [p for p in canonical["properties"]
               if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))]
    if not located:
        canonical["pois"] = []
        gaps.append("no property coordinates yet (run --geocode first) - nearest POIs left "
                    "to the dashboard's client-side lookup")
        return 0, False  # honour the (count, live) contract - a bare int crashes the caller's unpack

    # PRIMARY: the bundled COMPLETE-coverage datasets - air/port/rail (poi_dataset), border
    # crossings (borders_dataset) and >=100k cities (cities_major_dataset). Pure offline
    # computation, genuinely the nearest because each set is complete. The curated poi_library
    # is only an outage fallback for whichever of these assets is absent from this skill copy.
    dataset = _poi_dataset()
    borders = _borders_dataset()
    cities_major = _cities_major_dataset()
    if dataset or borders or cities_major:
        by_key = {}
        lib_types = tuple(t for t, present in
                          (("air", dataset), ("port", dataset), ("rail", dataset),
                           ("border", borders), ("city", cities_major)) if not present)
        for p in located:
            found = _nearest_from_dataset(p["lat"], p["lng"], dataset, borders, cities_major)
            if lib_types:        # outage fallback only for a type whose complete asset is absent
                found = _library_supplement(p["lat"], p["lng"], found, lib_types)
            for slot, poi in found.items():
                # 'city_major' is a second CITY result (15e), typed apart so the template can flag
                # it major; the template folds it back into the cities (dashboard v46)
                t = "city_major" if slot == "city_major" else poi.get("type", slot)
                key = (poi["name"], t, round(poi["lat"], 3), round(poi["lng"], 3))
                if poi.get("dataset"):
                    src = ("CBRE border dataset" if t == "border"
                           else "CBRE cities dataset" if t in ("city", "city_major")
                           else "CBRE POI dataset")
                else:
                    src = "curated library"
                note = f"nearest {t} ({src})"
                if t == "border" and poi.get("crossingOf"):
                    note = f"nearest border crossing {poi['crossingOf']} ({src})"
                if t in ("city", "city_major") and poi.get("population"):
                    # population is SHOWN here (renders in the modal distance note + map popup);
                    # no chrome change needed - the template already renders poi.note verbatim.
                    note = (f"nearest major city ({src}; pop {poi['population']:,})" if slot == "city"
                            else f"nearest city of {MAJOR_CITY_POP:,}+ ({src}; pop {poi['population']:,})")
                rec = {"name": poi["name"], "type": t, "lat": poi["lat"], "lng": poi["lng"],
                       "note": note}
                if poi.get("country"):
                    rec["country"] = poi["country"]
                if poi.get("population") is not None:
                    rec["population"] = poi["population"]
                by_key[key] = rec
            missing = [t for t in ("port", "air", "rail", "border", "city") if t not in found]
            if missing:
                gaps.append(f"property id={p.get('id')} ({p.get('city', '?')}): no "
                            f"{'/'.join(missing)} within the distance caps - a genuine "
                            f"geography gap, not an outage")
        canonical["pois"] = list(by_key.values())
        return len(canonical["pois"]), True

    # FALLBACK (dataset missing from this skill copy): live OSM discovery
    by_key, unreachable, dead, osm_ok = {}, 0, False, False
    for p in located:
        ck = f"{round(p['lat'], 3)},{round(p['lng'], 3)}"
        res = cache.get(ck)
        if res is None:
            if dead:  # Overpass already proven unreachable this run - don't stall on every site
                unreachable += 1
                res = None
            else:
                try:
                    res = nearest_pois_for(p["lat"], p["lng"])
                    cache[ck] = res  # cache stores the PURE OSM result only
                    _save_cache(POI_OSM_CACHE, cache)
                    time.sleep(2.0)  # be polite - the public server OOMs under pressure
                except Exception:
                    unreachable += 1
                    dead = True  # circuit-break: a blocked build must not hang N x timeout
                    res = None
        if res is None:
            continue  # errored - NEVER treat as 'no POIs nearby'
        osm_ok = True
        # types beyond the calibrated OSM scan radius come from the curated
        # major-facilities library, capped + explicitly labelled (at 200+ km the
        # nearest MAJOR gateway is the logistics answer; a minor harbour is noise)
        full = _library_supplement(p["lat"], p["lng"], dict(res))
        for t, poi in full.items():
            key = (poi["name"], t, round(poi["lat"], 3), round(poi["lng"], 3))
            note = (f"nearest major {t} (library - beyond the "
                    f"{OVERPASS_RADIUS_M // 1000} km OSM scan)" if poi.get("library")
                    else f"nearest {t} (OSM)")
            by_key[key] = {"name": poi["name"], "type": t, "lat": poi["lat"],
                           "lng": poi["lng"], "note": note}
        missing = [t for t in ("port", "air", "rail", "border", "city") if t not in full]
        if missing:
            gaps.append(f"property id={p.get('id')} ({p.get('city', '?')}): no nearest "
                        f"{'/'.join(missing)} via OSM (dashboard resolves client-side online, or confirm locally)")
    live = osm_ok  # OSM discovery genuinely ran (live or web-seeded cache), not library-only
    if by_key:
        canonical["pois"] = list(by_key.values())
    elif unreachable:
        # discovery COMPLETELY failed: keep the merge-seeded library POIs as a
        # stopgap so the map is not empty - but they are NOT the genuine nearest;
        # the caller must surface the web_enrich seeding workflow (run.py exit 8)
        kept = len(canonical.get("pois") or [])
        gaps.append(f"Overpass unreachable - kept {kept} library POI(s) as a STOPGAP only; "
                    f"fulfil web_requests.json (helpers/web_enrich.py) for the genuine nearest")
    else:
        canonical["pois"] = []
    if unreachable:
        gaps.append(f"OSM/Overpass unreachable for {unreachable} site(s) at build time - fetch the "
                    f"emitted web_requests.json with WebFetch + web_enrich ingest (genuine nearest, baked)")
    return len(canonical.get("pois") or []), live


ORS_ENDPOINT = "https://api.openrouteservice.org"
ORS_SPACING_S = 1.6  # free tier = 40 requests/minute; 1.6s spacing stays under it


def _pair_key(hgv: bool, plat, plng, qlat, qlng) -> str:
    """Route-cache key, PROFILE-TAGGED: trucking (ORS driving-hgv) entries must
    never be satisfied by legacy car-routed values and vice versa."""
    return ("hgv|" if hgv else "") + f"{plat},{plng};{qlat},{qlng}"


def _relevant_pois(p: dict, pois: list) -> list:
    """POIs worth routing for this property: within the same straight-line cap
    used to DISCOVER that POI type, so every possible nearest-of-type is routed
    and cross-region pairs the dashboard never surfaces are skipped."""
    return [q for q in pois
            if _haversine_km(p["lat"], p["lng"], q["lat"], q["lng"])
            <= POI_MAX_KM.get(q.get("type", ""), 800)]


def _ors_matrix(requests, key: str, plat: float, plng: float, dests: list,
                endpoint: str = ORS_ENDPOINT, timeout: int = 30):
    """One openrouteservice TRUCKING matrix call: property -> all its relevant
    POIs (distances + durations, profile driving-hgv) in a single request -
    37 properties = 37 requests, well inside the free tier's 40/min."""
    body = {"locations": [[plng, plat]] + [[q["lng"], q["lat"]] for q in dests],
            "sources": [0], "destinations": list(range(1, len(dests) + 1)),
            "metrics": ["distance", "duration"]}
    for attempt in range(3):
        resp = requests.post(f"{endpoint}/v2/matrix/driving-hgv", json=body,
                             headers={"Authorization": key,
                                      "Content-Type": "application/json", **UA},
                             timeout=timeout)
        if resp.status_code == 429:  # minute quota - back off and retry
            time.sleep(15 * (attempt + 1))
            continue
        if resp.status_code != 200:
            return None
        return resp.json()
    return None


def osrm_prebake(canonical: dict, gaps: list, endpoint: str,
                 updates: list | None = None, ors_key: str = "") -> int:
    """Pre-bake drive distance/time from each property to each RELEVANT POI.

    With an openrouteservice key (project.yaml enrichment.ors_api_key or the
    ORS_API_KEY env var): TRUCKING routing (driving-hgv) via the ORS matrix API,
    one call per property, throttled to the free tier's 40/min. Without a key:
    legacy car routing via the public OSRM demo (flagged in the ledger - the
    dashboard's audience plans HGV movements, so the key path is the product).
    Pairs are pruned by the same straight-line caps used to discover the POIs.
    """
    import requests
    from concurrent.futures import ThreadPoolExecutor

    pois = canonical.get("pois", [])
    props = [p for p in canonical["properties"] if isinstance(p.get("lat"), (int, float))]
    if not pois or not props:
        return 0

    # route cache: keyed on the exact coordinate pair (profile-tagged), so a
    # gate-failure re-run never re-routes against the shared servers.
    route_cache = _load_cache(OSRM_CACHE)
    cache_dirty = False

    if ors_key:  # TRUCKING via openrouteservice matrix - the product path
        done, dead = 0, False
        for p in props:
            dests = _relevant_pois(p, pois)
            if not dests:
                continue
            missing = [q for q in dests
                       if _pair_key(True, p["lat"], p["lng"], q["lat"], q["lng"]) not in route_cache]
            if missing and not dead:
                try:
                    data = _ors_matrix(requests, ors_key, p["lat"], p["lng"], dests,
                                       endpoint=ORS_ENDPOINT)
                except Exception:
                    data = None
                    dead = True  # offline/blocked - serve cache only, no N x timeout
                if data:
                    durations = (data.get("durations") or [[]])[0]
                    distances = (data.get("distances") or [[]])[0]
                    for j, q in enumerate(dests):
                        if j < len(durations) and durations[j] is not None:
                            entry = {"min": round(durations[j] / 60)}
                            if j < len(distances) and distances[j] is not None:
                                entry["km"] = round(distances[j] / 1000, 1)
                            entry.setdefault("km", round(_haversine_km(
                                p["lat"], p["lng"], q["lat"], q["lng"]), 1))
                            route_cache[_pair_key(True, p["lat"], p["lng"],
                                                  q["lat"], q["lng"])] = entry
                            cache_dirty = True
                time.sleep(ORS_SPACING_S)  # free tier: 40 requests/minute
            distances_out = {}
            for q in dests:
                e = route_cache.get(_pair_key(True, p["lat"], p["lng"], q["lat"], q["lng"]))
                if e:
                    distances_out[q["name"]] = e
            if distances_out:
                p.setdefault("preBaked", {})["distances"] = distances_out
                done += 1
                if updates is not None:
                    updates.append(_trace(p.get("id"), "preBaked.distances",
                                          f"{len(distances_out)} drive-time(s)",
                                          "api.openrouteservice.org",
                                          "ORS matrix API (driving-hgv, trucking)", "osrm"))
            else:
                gaps.append(f"ORS unreachable for property id={p.get('id')} - fulfil the "
                            f"web_enrich requests for trucking drive-times")
        if cache_dirty:
            _save_cache(OSRM_CACHE, route_cache)
        if done == 0 and props:
            msg = ("routing unreachable from this sandbox - the drive-time handoff is "
                   "STANDALONE (no run.py needed): `python helpers/web_enrich.py plan "
                   "<work>/canonical.json --work <work> --osrm [--pois --geocode]`, deliver "
                   "web_enrich.html in the chat, save the returned web_seeds.json to the work "
                   "dir, `python helpers/web_enrich.py ingest --work <work>`, then re-run "
                   "enrich - real trucking drive-times bake fully offline")
            gaps.append(msg)
            print(f"NOTE {msg}")
        return done

    def one_route(p, poi):
        nonlocal cache_dirty
        # PREFER a trucking (hgv) entry already in the cache: when the operator pasted an
        # openrouteservice key into the FETCHER PAGE (web_enrich.html), the browser routed
        # HGV and ingest cached hgv| pairs. Those are strictly better than re-routing as
        # car, and using them here means the key stayed in the operator's browser - it never
        # re-entered the chat or project.yaml (key hygiene).
        hk = route_cache.get(_pair_key(True, p["lat"], p["lng"], poi["lat"], poi["lng"]))
        if hk:
            return hk
        ck = _pair_key(False, p["lat"], p["lng"], poi["lat"], poi["lng"])
        if ck in route_cache:
            return route_cache[ck]
        url = (f"{endpoint}/route/v1/driving/"
               f"{p['lng']},{p['lat']};{poi['lng']},{poi['lat']}?overview=false")
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=UA, timeout=12)
                if resp.status_code == 429:  # rate-limited - back off and retry
                    time.sleep(0.5 * (attempt + 1))
                    continue
                rt = (resp.json().get("routes") or [None])[0]
                if rt:
                    res = {"km": round(rt["distance"] / 1000, 1),
                           "min": round(rt["duration"] / 60)}
                    route_cache[ck] = res
                    cache_dirty = True
                    return res
                return None
            except Exception:
                return None
        return None

    # one task per RELEVANT (property, POI): skip pairs whose straight-line
    # distance exceeds the POI type's discovery cap - those are another region's
    # POIs, never this property's nearest, so routing them is pure waste. ex.map
    # preserves order, so each property's distance dict keeps a stable key order.
    tasks = [(pi, poi) for pi, p in enumerate(props) for poi in pois
             if _haversine_km(p["lat"], p["lng"], poi["lat"], poi["lng"])
             <= POI_MAX_KM.get(poi.get("type", ""), 800)]
    with ThreadPoolExecutor(max_workers=OSRM_WORKERS) as ex:
        results = list(ex.map(lambda t: one_route(props[t[0]], t[1]), tasks))
    if cache_dirty:
        _save_cache(OSRM_CACHE, route_cache)

    per_prop = [{} for _ in props]
    for (pi, poi), res in zip(tasks, results):
        if res:
            per_prop[pi][poi["name"]] = res

    done = 0
    for p, distances in zip(props, per_prop):
        if distances:
            p.setdefault("preBaked", {})["distances"] = distances
            done += 1
            # label honestly: if every one of this property's times came from browser-
            # supplied TRUCKING (hgv) cache entries, cite ORS/HGV, not the car fallback
            named = [q for q in _relevant_pois(p, pois) if q.get("name") in distances]
            all_hgv = bool(named) and all(
                _pair_key(True, p["lat"], p["lng"], q["lat"], q["lng"]) in route_cache
                for q in named)
            if updates is not None:
                updates.append(_trace(
                    p.get("id"), "preBaked.distances", f"{len(distances)} drive-time(s)",
                    "api.openrouteservice.org" if all_hgv else "router.project-osrm.org",
                    ("ORS matrix API (driving-hgv, trucking - supplied via the fetcher page)"
                     if all_hgv else "OSRM route API (driving-CAR fallback - set an "
                     "openrouteservice key for trucking)"), "osrm"))
        else:
            gaps.append(f"OSRM unreachable for property id={p.get('id')} (drive-times left to in-browser fallback)")
    if done == 0 and props:
        msg = ("routing unreachable from this sandbox - the drive-time handoff is "
               "STANDALONE (no run.py needed): `python helpers/web_enrich.py plan "
               "<work>/canonical.json --work <work> --osrm [--pois --geocode]`, deliver "
               "web_enrich.html in the chat, save the returned web_seeds.json to the work "
               "dir, `python helpers/web_enrich.py ingest --work <work>`, then re-run "
               "enrich - real routed drive-times bake fully offline")
        gaps.append(msg)
        print(f"NOTE {msg}")
    return done


_REGIONS_DS: dict | bool | None = None  # None = not loaded; False = absent (tests may pin)


def _regions_dataset():
    """The bundled regional-economics dataset (assets/regions_dataset.json, built
    from the org's Oxford Economics NUTS3 export): population, labour force,
    unemployment, nominal GDP and logistics employment splits for ~1,500 European
    provinces, current-year baseline, citation embedded. Supplies the ENTIRE default
    workforce snapshot (incl. the derived logistics-employment-share tile); the
    research sub-agent is now an optional fallback only for a region the dataset does
    not carry, so a standard run needs no live region research."""
    global _REGIONS_DS
    if _REGIONS_DS is None:
        d = _load_asset_json("regions_dataset")
        _REGIONS_DS = d if (d and d.get("regions")) else False
    return _REGIONS_DS or None


def _norm_region(s: str) -> str:
    import unicodedata
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                            if not unicodedata.combining(c)).lower().split())


def _alias_norm(s) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


# Curated NUTS-1/2 region aliases - EXACT match ONLY (a fuzzy bind would attach the
# WRONG region's workforce, e.g. 'midland'->IE063). Every prefix is verified to resolve
# to real NUTS-3 provinces in assets/regions_dataset.json. A broad label resolves to an
# HONEST AGGREGATE (sum of the additive figures + labour-weighted unemployment) of its
# provinces - never one province's stats mislabelled as the whole region. PROVINCE-level
# labels are still preferred; this is the fallback so a broad label is not a dead end.
_NUTS_SPEC = [
    ("UKF", "East Midlands"), ("UKG", "West Midlands"), ("UKE", "Yorkshire and the Humber"),
    ("UKD", "North West England", "north west"), ("UKJ", "South East England", "south east"),
    ("UKH", "East of England"), ("UKI", "London", "greater london"),
    ("UKK", "South West England", "south west"), ("UKC", "North East England", "north east"),
    ("UKM", "Scotland"), ("UKL", "Wales", "cymru"),
    ("DE1", "Baden-Wurttemberg", "baden wurttemberg", "baden wuerttemberg"),
    ("DE2", "Bayern", "bavaria"), ("DEA", "Nordrhein-Westfalen", "north rhine westphalia", "nrw"),
    ("DE7", "Hessen", "hesse"), ("DE9", "Niedersachsen", "lower saxony"), ("DE3", "Berlin"),
    ("ES51", "Cataluna", "catalonia", "catalunya"), ("ES30", "Comunidad de Madrid"),
    ("ES52", "Comunidad Valenciana"), ("ES61", "Andalucia", "andalusia"), ("ES24", "Aragon"),
    ("ES21", "Pais Vasco", "basque country", "euskadi"),
    ("ITC4", "Lombardia", "lombardy"), ("ITH3", "Veneto"), ("ITH5", "Emilia-Romagna"),
    ("ITC1", "Piemonte", "piedmont"), ("ITI4", "Lazio"),
    ("FR10", "Ile-de-France", "paris region"), ("FRE", "Hauts-de-France"),
    ("FRK", "Auvergne-Rhone-Alpes"),
    ("PL9", "Mazowieckie", "masovia", "mazovia"), ("PL22", "Slaskie", "silesia", "silesian"),
    ("PL41", "Wielkopolskie", "greater poland"), ("PL51", "Dolnoslaskie", "lower silesia"),
    ("PL71", "Lodzkie"),
    ("NL3", "West Netherlands", "randstad"), ("NL41", "Noord-Brabant", "north brabant"),
    ("IE05", "Southern Ireland"), ("IE06", "Eastern and Midland"),
]
# A label that is ONLY a compass direction ('North East', 'South-West', 'Mid'). `_dataset_region`
# never binds one through a bracket-derived name-index piece; the same pattern keeps
# build_regions_dataset._name_variants from indexing such pieces at all (15a).
_COMPASS_ONLY = re.compile(r"^(north|south|east|west|central|mid)([ -]?(north|south|east|west))?$")
_NUTS_ALIASES: dict = {}
for _spec in _NUTS_SPEC:
    for _nm in (_spec[1],) + _spec[2:]:
        _NUTS_ALIASES[_alias_norm(_nm)] = (_spec[0], _spec[1])

_NUTS_ADDITIVE = ("population", "labourForce", "emplManufacturing", "emplTransportStorage", "gdpNominalMeur")


def _aggregate_nuts(ds: dict, prefix: str, display: str):
    """Honest region-level profile: SUM the additive figures and labour-weight the
    unemployment rate across every NUTS-3 province whose code starts with `prefix`.
    None when the prefix matches nothing."""
    rows = [r for c, r in ds.get("regions", {}).items() if c.startswith(prefix)]
    if not rows:
        return None
    prof = {"name": display, "nuts": prefix,
            "country": next((r.get("country") for r in rows if r.get("country")), prefix[:2])}
    for f in _NUTS_ADDITIVE:
        vals = [r[f] for r in rows if isinstance(r.get(f), (int, float))]
        if vals:
            prof[f] = round(sum(vals))
    wp = [(r["unemployment"], (r.get("labourForce") or r.get("population") or 1))
          for r in rows if isinstance(r.get("unemployment"), (int, float))]
    if wp:
        tw = sum(w for _, w in wp)
        prof["unemployment"] = round(sum(u * w for u, w in wp) / tw, 2) if tw else \
            round(sum(u for u, _ in wp) / len(wp), 2)
    asof = next((r.get("unemploymentAsOf") or r.get("populationAsOf") for r in rows
                 if r.get("unemploymentAsOf") or r.get("populationAsOf")), ds.get("asOf", ""))
    prof["unemploymentAsOf"] = prof["populationAsOf"] = asof
    base_src = next((r.get("sources") for r in rows if r.get("sources")), "")
    prof["sources"] = f"{base_src} (aggregated across {len(rows)} NUTS-3 areas in {prefix})".strip()
    prof["notes"] = (f"Region-level figures aggregated across {len(rows)} NUTS-3 provinces "
                     f"({prefix}); unemployment is labour-force-weighted.")
    return prof


def _dataset_region(ds: dict, code: str):
    """Look a property regionCode up in the dataset: as a NUTS code directly, else by
    unique normalised PROVINCE name ('Guadalajara' -> ES424), else as a curated broad
    NUTS-1/2 region alias -> an honest AGGREGATE of its provinces ('Bayern' -> sum of 96
    NUTS-3 areas). None when ambiguous/absent (the gate then blocks loudly)."""
    if code in ds.get("regions", {}):
        return ds["regions"][code]
    ni = ds.get("name_index", {})

    def _hit(k):
        h = ni.get(k)
        if not h or len(h) != 1:
            return None
        # A COMPASS-ONLY key ('north east') binds only a region whose WHOLE name it is (IE042
        # 'West'). The shipped index also carries bracket pieces - 'West Sussex (North East)'
        # indexes 'north east' -> UKJ28 - which captured the UK macro-region label and bound
        # a North East England site to one West Sussex district; such a query falls through
        # to the aliases below instead (15a).
        if _COMPASS_ONLY.match(k) and _norm_region(ds["regions"][h[0]].get("name", "")) != k:
            return None
        return ds["regions"][h[0]]

    reg = _hit(_norm_region(code))
    if reg:
        return reg
    # bilingual / dual-name fallback: split the QUERY on / , ; and parentheticals too, so a
    # property carrying a joined ('Valencia / Valencia') or local-language ('Alacant') form
    # resolves even against a dataset that was not re-indexed with variants (defense in depth)
    try:
        from build_regions_dataset import _name_variants
        variants = _name_variants(code)
    except Exception:
        variants = {_norm_region(code)}
    for v in variants:
        reg = _hit(v)
        if reg:
            return reg
    alias = _NUTS_ALIASES.get(_alias_norm(code))
    if alias:
        return _aggregate_nuts(ds, alias[0], alias[1])
    return None


_REGIONS_GEO: dict | bool | None = None  # None = not loaded; False = absent


def _regions_geo() -> dict | None:
    """Bundled NUTS-3 BOUNDARY polygons (assets/regions_geo.json.gz, GISCO NUTS_RG) for
    point-in-polygon region binding. Memoised; None when the asset is absent (an older
    install) so binding degrades to label/city without crashing."""
    global _REGIONS_GEO
    if _REGIONS_GEO is None:
        import gzip
        f = C.ASSETS / "regions_geo.json.gz"
        try:
            _REGIONS_GEO = json.loads(gzip.decompress(f.read_bytes())) if f.exists() else False
            if _REGIONS_GEO and not _REGIONS_GEO.get("regions"):
                _REGIONS_GEO = False
        except Exception:
            _REGIONS_GEO = False
    return _REGIONS_GEO or None


def _pip_ring(x: float, y: float, ring: list) -> bool:
    """Ray-casting: is (x=lng, y=lat) inside the ring [[lng,lat],...]?"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _poly_contains(x: float, y: float, poly: list) -> bool:
    """poly = [exterior_ring, hole1, ...]: inside the exterior and inside NO hole."""
    if not poly or not _pip_ring(x, y, poly[0]):
        return False
    return not any(_pip_ring(x, y, h) for h in poly[1:])


def _region_for_point(lat: float, lng: float, geo: dict) -> str | None:
    """The NUTS-3 code whose boundary CONTAINS (lat,lng) - exact point-in-polygon,
    bbox-prefiltered. None when the point is outside every polygon (offshore / a coastline
    simplification gap / a non-NUTS country) so the caller falls back to label/city.
    Deterministic (stable dict order; the polygons partition the land, so at most one hit)."""
    for code, g in geo.get("regions", {}).items():
        bb = g.get("bbox")
        if not bb or not (bb[0] <= lng <= bb[2] and bb[1] <= lat <= bb[3]):
            continue
        if any(_poly_contains(lng, lat, poly) for poly in g.get("poly", [])):
            return code
    return None


def _region_label_key(raw_label, cc, city) -> str:
    """Stable cache key for an LLM region-label resolution: the raw label + the ISO-2
    country + the city, each normalised through `_alias_norm`, so 'Yorkshire And North
    East' and 'yorkshire and north east' collapse to one key, accents fold, and the SAME
    fuzzy label in two different countries (or two cities) can never cross-bind."""
    return f"{_alias_norm(raw_label)}|{(cc or '').strip().upper()}|{_alias_norm(city)}"


def _region_labels_cache() -> dict:
    """The isolated interpretation sub-agent's region-label resolutions, written to
    work/extract/region_labels.json (alongside the other exit-3 sub-agent outputs).
    Shape: {"resolutions": [{"raw_label","city","code"|null,...}], ...}. Returns a
    {key -> code} map keyed by `_region_label_key`; {} when the file is absent or
    malformed (the offline / no-LLM path, which then behaves exactly as before)."""
    f = CACHE_DIR / "extract" / "region_labels.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    out: dict = {}
    for r in (data.get("resolutions") if isinstance(data, dict) else None) or []:
        if not isinstance(r, dict):
            continue
        code = r.get("code")
        if not (isinstance(code, str) and code.strip()):
            continue  # null / absent = the model declined; falls back to the gap
        out[_region_label_key(r.get("raw_label"), r.get("country_cc") or r.get("country"),
                              r.get("city"))] = code.strip()
    return out


def _region_labels_answered_keys() -> set:
    """EVERY answered resolution key in work/extract/region_labels.json - code-bearing
    AND declined (code null) alike - for the exit-3 job emitter's "already asked" set.
    A strict superset of _region_labels_cache()'s keys, built the same way from the same
    file. The two views MUST stay separate: the bind path rightly drops declines (a null
    never binds a code), but the emitter must NOT re-ask them - keyed on the bind cache,
    a legitimately declined label re-emitted its job on every re-run and the exit-3
    round-trip never converged (the sub-agent is instructed 'null over a guess', so it
    declined again, forever). A declined label is asked ONCE, then falls back to the
    self-documenting difflib gap."""
    f = CACHE_DIR / "extract" / "region_labels.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    out: set = set()
    for r in (data.get("resolutions") if isinstance(data, dict) else None) or []:
        if not isinstance(r, dict):
            continue
        out.add(_region_label_key(r.get("raw_label"), r.get("country_cc") or r.get("country"),
                                  r.get("city")))
    return out


def _ok_region_city(c) -> bool:
    # the shared family (C5); this was an eighth private literal that every count missed
    return isinstance(c, str) and bool(c.strip()) and not C._N.looks_unknown(c)


def _property_country_cc(p: dict) -> str:
    cc = str(p.get("country") or "").strip().upper()
    return cc if len(cc) == 2 and cc.isalpha() else ""


def unresolved_region_labels(canonical: dict, ds: dict | None) -> list:
    """The SINGLE source of truth for 'which region labels neither the dataset nor the
    city can resolve, AND that have no coordinate point-in-polygon bind' - so the exit-3
    job emitter (run.py) and the difflib gap (merge_regions) never drift. Returns a
    deterministic, de-duplicated list of (raw_label, city, country_cc): a property whose
    current regionCode does NOT resolve via `_dataset_region`, whose CITY does not resolve
    either, and that has NO usable coords (so PIP would never override an LLM resolution).
    A property with coords is EXCLUDED here because the authoritative point-in-polygon bind
    wins outright (bind_region_codes runs the PIP branch first)."""
    if not ds:
        return []
    geo = _regions_geo()
    seen, out = set(), []
    for p in canonical.get("properties", []):
        lat, lng = p.get("lat"), p.get("lng")
        # a property with coords inside a NUTS-3 polygon is bound authoritatively by PIP -
        # never burn a label job on it (and the LLM resolution would never be consulted)
        if geo and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            code = _region_for_point(lat, lng, geo)
            if code and _dataset_region(ds, code):
                continue
        cur = p.get("regionCode")
        if cur and _dataset_region(ds, cur):
            continue  # the label/code already resolves deterministically
        city = p.get("city")
        if _ok_region_city(city) and _dataset_region(ds, city):
            continue  # the city resolves deterministically
        raw = cur if (isinstance(cur, str) and cur.strip()) else None
        if not raw:
            continue  # no label string to resolve
        cc = _property_country_cc(p)
        key = _region_label_key(raw, cc, city if _ok_region_city(city) else "")
        if key in seen:
            continue
        seen.add(key)
        out.append((raw, city if _ok_region_city(city) else "", cc))
    return out


def region_label_candidates(ds: dict | None, country_ccs) -> list:
    """The CLOSED candidate set handed to the LLM: {code, name, country} for every NUTS-3
    province in the dataset PLUS the curated broad-region aliases, scoped to the given ISO-2
    country prefixes (the prefixes already present among the project's other properties).
    Empty `country_ccs` -> the full list (a single-property project with no known country).
    The model may ONLY return a code from this set, so it can never invent a bindable code."""
    if not ds:
        return []
    ccs = {str(c).strip().upper() for c in (country_ccs or []) if str(c).strip()}
    out, seen = [], set()
    for code, r in ds.get("regions", {}).items():
        cc = str(r.get("country") or code[:2]).upper()
        if ccs and cc not in ccs:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": r.get("name") or code, "country": cc})
    for _spec in _NUTS_SPEC:
        prefix, display = _spec[0], _spec[1]
        # the alias country is the ISO-2 of its member provinces in the dataset (a UK NUTS
        # prefix is country 'GB', not 'UK'), so the country-prefix scope matches the property
        cc = next((str(r.get("country")).upper() for c, r in ds.get("regions", {}).items()
                   if c.startswith(prefix) and r.get("country")), prefix[:2].upper())
        if ccs and cc not in ccs:
            continue
        if prefix in seen:
            continue
        seen.add(prefix)
        out.append({"code": prefix, "name": display, "country": cc})
    out.sort(key=lambda d: (d["country"], d["code"]))
    return out


def _stated_region_label(p: dict, ds: dict, prior: dict | None = None) -> str:
    """The region the RECORD ITSELF states, for the cross-check below, or "" when it states
    none. Three sources, in order:

      1. the ORIGINAL stated label `harmonise_regions` recorded in `meta.regionHarmonised`,
         when that harmonisation is still in force. THIS IS LOAD-BEARING, not belt-and-braces:
         once `harmonise_regions` has rewritten `p['region']` to the bound NUTS-3 name, the
         record no longer carries what its SOURCE said, so a SECOND `--regions` pass would
         find the bound name agreeing with the bound code and the disclosure would silently
         vanish on every re-run. That is the exact defect recorded in that function's
         IDEMPOTENT DISCLOSURE note, and a disclosure that disappears when you re-run is worse
         than none. "Still in force" is tested the same way that function tests it - the
         property must still carry the bound name the record claims - so a label edited since
         is not resurrected from a stale record;
      2. `p['region']`, through `_stated_region`, so a sentinel is ABSENCE and not a level;
      3. a `regionCode` that is a LABEL rather than a dataset code. merge.py derives
         `regionCode` from the stated label for a property with no coordinates, so on that
         path the label is the only place the record's own claim survives. A `regionCode` that
         IS a real dataset key is excluded, because that is not a claim the record made in
         prose and the bind is about to overwrite it by design."""
    if prior:
        rec = prior.get(p.get("id"))
        cur_norm = _norm_region(_stated_region(p))
        if rec and rec[1] and cur_norm == rec[1]:
            return rec[0]
    lab = _stated_region(p)
    if lab:
        return lab
    cur = p.get("regionCode")
    if _ok_region_city(cur) and str(cur).strip() not in (ds.get("regions") or {}):
        return str(cur).strip()
    return ""


def _region_conflict(ds: dict, stated: str, bound: str):
    """Does a record's own stated region GENUINELY contradict the code its own coordinates were
    bound to, or is it merely the same place named at a coarser administrative level? Returns
    the resolved profile of the stated label when the two CONFLICT, else None. (G2)

    THE RULE, in one sentence: resolve the stated label the way everything else in this file
    resolves one (`_dataset_region`, so a province name, a bilingual variant and a curated
    broad alias all count), take its `nuts` code, and compare LINEAGE - if either code is a
    prefix of the other, the two labels name the SAME place at two levels and there is nothing
    to disclose.

    WHY A PREFIX TEST IS LINEAGE AND NOT A COINCIDENCE. NUTS codes are hierarchical by
    construction: a code's leading substring IS its parent area. So 'East Midlands' resolving
    to the UKF aggregate against a bind of UKF25 is a property whose brochure is CORRECT, just
    coarser - and `_aggregate_nuts` exists for precisely that case, so this reuses its prefix
    instead of inventing a second hierarchy. Without this test the disclosure would fire on
    the ordinary shape of this data (a county from one source, the wider region from another -
    `harmonise_regions`' founding incident) and would be ignored inside a day.

    AN UNRESOLVABLE LABEL IS NOT A CONFLICT, and that is the decision that keeps this quiet
    enough to be worth reading. 'Northamptonshire' resolves to nothing in the bundled NUTS-3
    dataset (MEASURED: `_dataset_region` returns None for it), and neither does any label in a
    market the dataset does not cover at all, which is most of them. Firing there would be
    claiming a contradiction that cannot be demonstrated: two labels that cannot both be
    placed on the same map cannot be shown to disagree. Silence is the honest answer, and it
    is also what makes this whole check INERT outside the dataset's coverage rather than
    degraded - the same discipline `_postcode_conflict` applies to a market that quotes no
    codes.

    A CROSS-BOUNDARY MARKETING LABEL DOES FIRE, on purpose, and it is the reason this exists.
    A label naming a NEIGHBOURING region (the corridor name a broker puts on a shed just over
    an administrative border) resolves to a code in a DIFFERENT lineage, so it is not a level
    difference in any sense: it is a different place, the workforce profile that ships is the
    bound area's and not the named one's, and the reader is entitled to know which they got."""
    prof = _dataset_region(ds, stated) if stated else None
    scode = str((prof or {}).get("nuts") or "")
    if not scode or not bound:
        return None
    if bound.startswith(scode) or scode.startswith(bound):
        return None          # one lineage, two levels - `_aggregate_nuts`' own case
    return prof


def _disclose_region_bind(p: dict, ds: dict, bound: str, gaps: list,
                          prior: dict | None = None) -> None:
    """One Gaps-Report line when a property's OWN stated region contradicts the region its OWN
    coordinates were bound to. WARN ONLY, and the polygon still wins: `bind_region_codes` binds
    the point-in-polygon code either way, for the measured reason in its docstring (a centroid
    picks the NEIGHBOUR for an edge-of-province town; point-in-polygon does not). Nothing here
    reads or writes `regionCode`.

    WHY THIS IS WORTH A LINE. A supplied coordinate wrong by a few hundred metres is invisible
    on a map and can fall the wrong side of a simplified administrative boundary. The bind then
    attaches a wholly different area's workforce profile - population, labour force,
    unemployment, manufacturing and transport employment - and every one of those figures
    ships cited and looking sourced, because it IS sourced; it is just about somewhere else.
    The record's own stated region is the only independent witness this pipeline has, so when
    it disagrees the disagreement IS the finding, not something to settle silently in either
    direction.

    ROUTED THROUGH THE CALLER'S `gaps` LIST, which is the regions layer's own bucket in
    `meta.enrichmentGapsByLayer` and therefore reaches the Gaps Report by the path
    `merge_regions`' unresolved-code line and `harmonise_regions`' level line already take.
    Nothing new was invented to carry it. `gaps=None` (every existing two-argument caller,
    including the evals) leaves the bind untouched and says nothing."""
    stated = _stated_region_label(p, ds, prior)
    prof = _region_conflict(ds, stated, bound)
    if not prof:
        return
    bname = str((_dataset_region(ds, bound) or {}).get("name") or bound)
    sname = str(prof.get("name") or stated)
    gaps.append(
        f"region conflict: id={p.get('id')} states '{stated}' (resolves to "
        f"{prof.get('nuts')} {sname}) but its OWN coordinates ({p.get('lat')}, "
        f"{p.get('lng')}) fall inside {bound} ({bname}). The coordinates decide the bind, so "
        f"the workforce profile shipped is {bound}'s - VERIFY THE PIN: a coordinate wrong by "
        f"a few hundred metres can cross an administrative boundary and attach the wrong "
        f"area's figures. These are different areas, not the same one at two levels.")


def bind_region_codes(canonical: dict, ds: dict | None, gaps: list | None = None) -> None:
    """Bind each property to its workforce region by its LOCATION - exact point-in-polygon
    on the property's coordinates - so a brochure's broad/wrong text region label ('Yorkshire
    And North East', which is no NUTS-3 province) never breaks the bind. Precedence:
      1. COORDINATES -> the NUTS-3 polygon that CONTAINS the point (authoritative + exact);
      2. (no coords / point outside every polygon) an existing regionCode/label that RESOLVES;
      2b. (lexical miss) an isolated-LLM resolution of the fuzzy label -> a KNOWN dataset code,
          read from work/extract/region_labels.json and RE-VERIFIED via `_dataset_region`;
      3. the property's CITY name -> its NUTS-3 province.
    Sets p['regionCode'] to a code that also resolves in the stats dataset; leaves it for
    merge_regions to gap when nothing binds.

    WHY point-in-polygon, not nearest-centroid: a centroid picks the NEIGHBOUR for an
    edge-of-province town - MEASURED: Azuqueca de Henares (a Guadalajara logistics hub on
    the Madrid border) is nearest Madrid's centroid but is INSIDE Guadalajara's polygon, so
    point-in-polygon binds it correctly (ES424). Exact, so coordinates are authoritative.

    WHY the LLM step is SAFE: it is the lexical step-2 fallback ONLY. The coords->PIP branch
    runs FIRST and `continue`s, so for any property WITH coordinates the authoritative
    point-in-polygon result wins and the cached resolution is never consulted; the LLM fills
    ONLY properties PIP left unbound. The cached code is NEVER bound directly - it is verified
    through `_dataset_region` exactly like a None lookup, so an unknown/stale code is discarded,
    and the difflib gap in merge_regions remains the fallback when the resolution is null.

    THE BIND IS NOW CROSS-CHECKED AGAINST WHAT THE RECORD ITSELF STATES (G2). Nothing ever
    asked whether the polygon's answer AGREED with the property's own region label, so a
    supplied coordinate wrong by a few hundred metres could fall the wrong side of a simplified
    boundary, bind the property to the neighbouring area, and ship that area's entire workforce
    profile with it - cited, sourced and about somewhere else - with nothing flagged. When
    `gaps` is supplied, a GENUINE disagreement (not a mere level difference: see
    `_region_conflict`) is disclosed there. The polygon is still authoritative and is still
    what gets bound; the disclosure changes no value in the dataset."""
    if not ds:
        return
    geo = _regions_geo()
    label_cache = _region_labels_cache()  # {} when work/extract/region_labels.json is absent
    # the ORIGINAL stated label per property id, for a canonical `harmonise_regions` has
    # already rewritten - see `_stated_region_label` for why reading it back matters
    prior = {}
    for _e in ((canonical.get("meta") or {}).get("regionHarmonised") or []):
        if isinstance(_e, dict) and _e.get("stated"):
            prior[_e.get("id")] = (str(_e["stated"]), _norm_region(str(_e.get("bound") or "")))
    # a label `fill_region_from_code` derived last pass is not a claim the record made (15b)
    for _pid, _e in _derived_regions(canonical).items():
        prior.setdefault(_pid, ("", _norm_region(str(_e.get("region") or ""))))

    def _ok_city(c):
        return _ok_region_city(c)

    for p in canonical.get("properties", []):
        lat, lng = p.get("lat"), p.get("lng")
        if geo and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            code = _region_for_point(lat, lng, geo)
            if code and _dataset_region(ds, code):  # the polygon's code must have a profile
                # BEFORE the overwrite: `_stated_region_label` may need to read the incoming
                # `regionCode` (merge.py puts the stated LABEL there for a property that had
                # no coordinates), and this line is about to replace it.
                if gaps is not None:
                    _disclose_region_bind(p, ds, code, gaps, prior)
                p["regionCode"] = code
                continue
        cur = p.get("regionCode")
        if cur and _dataset_region(ds, cur):
            continue  # no usable coords, but the existing label/code resolves - keep it
        city = p.get("city")
        # 2b. an isolated-LLM closed-set resolution of the fuzzy label, RE-VERIFIED here
        if label_cache and isinstance(cur, str) and cur.strip():
            cached = label_cache.get(_region_label_key(
                cur, _property_country_cc(p), city if _ok_city(city) else ""))
            prof = _dataset_region(ds, cached) if cached else None
            if prof and prof.get("nuts"):
                p["regionCode"] = prof["nuts"]  # bind the VERIFIED code, never the raw cached string
                continue
        prof = _dataset_region(ds, city) if _ok_city(city) else None
        if prof and prof.get("nuts"):
            p["regionCode"] = prof["nuts"]


def _stated_region(p: dict) -> str:
    """The property's OWN stated region label, or "" when absent or a sentinel. Delegates
    to the same non-sentinel test the region-side city check uses, so 'tbd'/'??'/'n/a'
    can never be mistaken for an administrative level."""
    v = p.get("region")
    return str(v).strip() if _ok_region_city(v) else ""


def _derived_regions(canonical: dict) -> dict:
    """id -> the `meta.regionFromCode` record for a region label `fill_region_from_code`
    DERIVED on an earlier pass, kept only while the property still carries that exact name
    (a label a source or repair has since supplied is stated again). A derived label is not
    a claim the record made, so the bind's cross-check and `harmonise_regions` skip it. (15b)"""
    by_id = {p.get("id"): p for p in canonical.get("properties", []) or []}
    out = {}
    for e in ((canonical.get("meta") or {}).get("regionFromCode") or []):
        if isinstance(e, dict) and e.get("id") in by_id and _norm_region(
                str(by_id[e["id"]].get("region") or "")) == _norm_region(str(e.get("region") or "")):
            out[e["id"]] = e
    return out


def fill_region_from_code(canonical: dict, ds: dict | None, updates: list | None = None) -> int:
    """A BLANK region beside a bound regionCode reads the dataset's NUTS-3 name. (15b)

    Cards shipped `region` 'TBC' while carrying a valid regionCode: `harmonise_regions`
    deliberately skips a blank region and nothing else read the code back into the label.
    Only a blank/sentinel region is filled, only from a code that is a KEY of `ds['regions']`
    (a real NUTS-3 area, as the bind produces - never a label or an aggregate), and a stated
    region is NEVER overwritten. The value is DERIVED and says so: a ledger row naming the
    regions dataset with a conflict_note, and `meta.regionFromCode` per property, which is
    also how a re-run recognises its own fill (refreshed from the current bind, or restored
    to what it replaced when the code no longer binds). Returns the number changed."""
    if not ds:
        return 0
    regions = ds.get("regions", {}) or {}
    mine = _derived_regions(canonical)
    rec, n = [], 0
    for p in canonical.get("properties", []) or []:
        pid = p.get("id")
        if _stated_region(p) and pid not in mine:
            continue  # a stated region is never overwritten
        code = p.get("regionCode")
        name = str((regions.get(code) or {}).get("name") or "").strip() if isinstance(code, str) else ""
        was = mine[pid].get("was", "") if pid in mine else p.get("region", "")
        if not name:
            if pid in mine:
                p["region"] = was  # its code no longer binds: back to the gap it filled
                n += 1
            continue
        rec.append({"id": pid, "region": name, "code": code, "was": was})
        if p.get("region") != name:
            p["region"] = name
            n += 1
        if updates is not None:
            row = _trace(pid, "region", name, f"assets/regions_dataset.json ({code})",
                         f"NUTS-3 name of the bound regionCode {code}", "dataset")
            row["conflict_note"] = ("derived from the regions dataset (the name of the bound "
                                    "NUTS-3 area); no source stated a region")
            updates.append(row)
    meta = canonical.setdefault("meta", {})
    if rec:
        meta["regionFromCode"] = rec
    else:
        meta.pop("regionFromCode", None)
    return n


def harmonise_regions(canonical: dict, ds: dict | None, gaps: list,
                      updates: list | None = None) -> int:
    """ONE administrative level for `region` across the longlist. (I11)

    THE DEFECT. `region` is decided per property by source precedence, and nothing ever
    asked whether the resulting SET was mutually consistent - only whether each value
    traced to a source. On the Corby run, two properties took the county from their
    brochure ('Northamptonshire') and two took the wider region from the tracker ('East
    Midlands'), because their brochures named none. Every value was correct and correctly
    sourced; the set was incoherent, because Northamptonshire is INSIDE the East Midlands.
    Four units in one town, three miles apart, shipped the client Excel's Region column
    reading a parent and its child as siblings.

    THE RULE. When the stated labels sit at more than one level, each property's region
    becomes the name of the NUTS-3 area ITS OWN COORDINATES FALL INSIDE - the bind
    `bind_region_codes` has already made by exact point-in-polygon, and the same one the
    workforce block displays. Corby reads 'North Northamptonshire' throughout.

    WHY NOT A HIERARCHY LOOKUP OR A MAJORITY VOTE, which is what the finding proposed.
    The bundled dataset is NUTS-3 ONLY (1543 codes, every one 5 characters); it carries
    neither 'East Midlands' nor 'Northamptonshire'. `_NUTS_ALIASES` resolves the former to
    the prefix UKF, but the latter resolves to nothing, so no parent/child test can decide
    this pair - and a majority vote ties 2/2 and would still overwrite two properties'
    sourced values with a label their own sources never stated. A proven location is the
    only tiebreak here that is evidence rather than arithmetic.

    THREE GUARDS, each load-bearing:

      * FIRES ONLY ON DISAGREEMENT. Fewer than two distinct stated levels -> return 0 and
        touch nothing. An already-coherent dataset is a provable no-op, so this can never
        quietly restate a region every source agreed on. Note that more than one label is
        a TRIGGER FOR INSPECTION, NOT A FINDING: a longlist spanning two real regions also
        has two labels. The defect is only ever demonstrated per property, by its own label
        disagreeing with its own proven region - so when nothing is rewritten, nothing is
        reported either. Claiming an unreconciled level clash we never demonstrated would
        put a false statement in the honesty document.
      * THE SOURCE MUST BE A PROVEN LOCATION, not a resolvable string: the code must be a
        KEY in `ds['regions']`, i.e. a real NUTS-3 province, which is exactly what
        point-in-polygon produces. `_dataset_region` would also resolve the literal label
        'East Midlands' to the UKF aggregate - but resolving a label is not proving a
        location, and harmonising the dataset onto one source's broad label would be a
        vote wearing a bind's clothes.
      * ONLY A PROPERTY THAT STATED A LABEL is rewritten. A blank region stays an honest
        gap for the coverage gate; filling gaps is not this function's job.

    DISCLOSURE, because the shipped label becomes derived rather than source-stated:
    `meta.regionHarmonised` records stated -> bound per property, a ledger row per change
    carries the stated value in `conflict_note` (and REPLACES the merge-written row, so the
    audit artefact cannot contradict the deliverable), and one Gaps Report line names the
    levels found. Nothing is rewritten silently.

    Returns the number of properties changed."""
    if not ds:
        return 0
    props = canonical.get("properties", []) or []
    derived = _derived_regions(canonical)  # a label filled from the code is not a stated level (15b)
    levels = {_norm_region(v) for v in (_stated_region(p) for p in props
                                        if p.get("id") not in derived) if v}
    if len(levels) < 2:
        return 0  # one level (or none) - already coherent, change nothing

    regions = ds.get("regions", {}) or {}
    changed: list[dict] = []
    unbound: list[str] = []
    for p in props:
        cur = _stated_region(p)
        if not cur or p.get("id") in derived:
            continue  # a blank region is a gap, not a level
        code = p.get("regionCode")
        prof = regions.get(code) if isinstance(code, str) else None
        name = str((prof or {}).get("name") or "").strip()
        if not name:
            unbound.append(cur)
            continue
        if _norm_region(name) == _norm_region(cur):
            continue
        p["region"] = name
        changed.append({"id": p.get("id"), "stated": cur, "bound": name, "code": code})
        if updates is not None:
            lat, lng = p.get("lat"), p.get("lng")
            where = (f"NUTS-3 area containing {lat}, {lng}"
                     if isinstance(lat, (int, float)) and isinstance(lng, (int, float))
                     else f"NUTS-3 area {code}")
            row = _trace(p.get("id"), "region", name,
                         f"assets/regions_dataset.json ({code})", where, "web")
            row["conflict_note"] = (
                f"harmonised to one administrative level: source stated '{cur}', "
                f"which is a different level from other properties in this longlist")
            updates.append(row)

    _meta = canonical.setdefault("meta", {})
    # IDEMPOTENT DISCLOSURE. A SECOND `--regions` pass over an already-harmonised canonical
    # rewrites nothing (each property's region already IS its bound NUTS-3 name), so
    # `changed` comes back empty - and because the regions layer REPLACES its gap bucket
    # every run, the harmonisation line silently dropped out of the delivered Gaps Report on
    # every re-run while `meta.regionHarmonised` still recorded it. A disclosure that
    # disappears when you re-run is worse than no disclosure: the deliverable stopped saying
    # the shipped region label is DERIVED rather than source-stated. So restate the SAME line
    # from the recorded harmonisation - and only while it is still true, i.e. every recorded
    # property still carries the bound name it records. `restated` keeps the return value
    # honest: nothing was rewritten this pass.
    restated = False
    if not changed:
        prior = _meta.get("regionHarmonised")
        if isinstance(prior, list) and prior:
            by_id = {p.get("id"): p for p in props}
            if all(_norm_region(str((by_id.get(c.get("id")) or {}).get("region") or ""))
                   == _norm_region(str(c.get("bound") or "")) for c in prior):
                changed, restated = list(prior), True
    if not changed:
        return 0
    _meta["regionHarmonised"] = changed
    stated_levels = "; ".join(sorted({c["stated"] for c in changed} | set(unbound)))
    bound_names = "; ".join(sorted({c["bound"] for c in changed}))
    msg = (f"Region labels were stated at more than one administrative level "
           f"({stated_levels}). Each property's region is now the NUTS-3 area its own "
           f"coordinates fall inside ({bound_names}), so the longlist reports one level; "
           f"every value stated at source is preserved in the Source Ledger.")
    if unbound:
        msg += (f" {len(unbound)} propert{'y' if len(unbound) == 1 else 'ies'} could not be "
                f"bound to a NUTS-3 area (no usable coordinates) and keep the label their "
                f"source stated.")
    gaps.append(msg)
    return 0 if restated else len(changed)


def merge_regions(canonical: dict, gaps: list, updates: list | None = None) -> int:
    # ignore the cache's documentation keys (_comment, _EXAMPLE_CODE, ...) - they
    # are not region profiles and would fail schema validation if injected
    cache = {k: v for k, v in _load_cache(REGIONS_CACHE).items() if not k.startswith("_")}
    ds = _regions_dataset()
    needed = {p.get("regionCode") for p in canonical["properties"] if p.get("regionCode")}
    # researcher profiles win field-by-field; the bundled dataset pre-fills the
    # rest. NEVER inject profiles for codes this dataset does not use.
    matched: dict = {}
    for code in sorted(c for c in needed if c):
        prof = dict(cache.get(code, {}))
        base = _dataset_region(ds, code) if ds else None
        if base:
            for k, v in base.items():
                if k in ("lat", "lng"):
                    continue  # the NUTS centroid is a binding aid, not a workforce figure
                if prof.get(k) in (None, ""):  # researcher's value always wins
                    prof[k] = v
        if prof:
            matched[code] = prof
    canonical["regions"] = matched
    # any requested code that resolved to NOTHING (not the cache, not the dataset) is a gap
    # that is SELF-DOCUMENTING: print the closest known dataset names so a bilingual /
    # mis-spelled label is fixable at a glance (covers a PARTIAL miss too, which used to be
    # silent unless EVERY code missed)
    unresolved = sorted(c for c in needed if c and c not in matched)
    if unresolved and ds:
        import difflib
        ni_keys = list(ds.get("name_index", {}).keys())
        bits = []
        for code in unresolved:
            near = difflib.get_close_matches(_norm_region(str(code)), ni_keys, n=3, cutoff=0.6)
            bits.append(f"'{code}'" + (f" (closest known: {', '.join(near)})" if near else ""))
        gaps.append("regionCode(s) did not match the bundled Oxford Economics dataset: "
                    + "; ".join(bits) + " - use a PROVINCE-level region label (the dataset is "
                    "NUTS-3), run the region research sub-agent, or add the profile to "
                    "regions_cache.json")
    if updates is not None:  # one trace row per stated figure, citing the profile's sources
        for code, r in matched.items():
            srcs = str(r.get("sources", "")).strip() or "regions_cache.json (uncited)"
            for fig in ("unemployment", "gdpPpsEu",
                        "population", "labourForce", "gdpNominalMeur",
                        "emplManufacturing", "emplTransportStorage"):
                if isinstance(r.get(fig), (int, float)):
                    updates.append(_trace(code, fig, r[fig], "regions dataset / research",
                                          srcs[:120], "web", record_type="region"))
    return len(matched)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("canonical")
    ap.add_argument("--geocode", action="store_true")
    ap.add_argument("--pois", action="store_true")
    ap.add_argument("--osrm", action="store_true")
    ap.add_argument("--regions", action="store_true")
    ap.add_argument("--osrm-endpoint", default="https://router.project-osrm.org")
    ap.add_argument("--ors-key", default="", help="openrouteservice API key -> TRUCKING "
                    "(driving-hgv) distances/drive-times via the ORS matrix API "
                    "(default: the ORS_API_KEY env var); blank = car via public OSRM")
    ap.add_argument("--cache-dir", help="writable dir for the geocode/regions/POI caches "
                    "(default: the canonical's folder, i.e. the work dir). The skill's "
                    "reference/ dir is read-only seed, merged in at load time.")
    ap.add_argument("--ledger", help="source_ledger.csv to upsert enrichment trace rows into "
                    "(every enrichment-filled field gets a row, replacing its 'gap' row)")
    args = ap.parse_args()

    path = Path(args.canonical)
    global CACHE_DIR
    CACHE_DIR = Path(args.cache_dir) if args.cache_dir else path.resolve().parent
    canonical = json.loads(path.read_text(encoding="utf-8-sig"))
    meta = canonical.setdefault("meta", {})
    flags = meta.setdefault("enrichment", {})
    meta.setdefault("enrichmentGaps", [])
    updates: list[dict] = []  # ledger trace rows for everything enrichment fills
    # PER-LAYER gap buckets: each enrichment layer OWNS its bucket and REPLACES it when it
    # runs, so a failure a later pass RESOLVED (e.g. geocode succeeding after the web
    # round-trip) no longer lingers - the Gaps Report is the FINAL state, not the union of
    # every attempt. A layer NOT run this invocation keeps its prior bucket. (The flat
    # meta.enrichmentGaps that deliver.py reads is rebuilt from the buckets at the end.)
    by_layer = meta.setdefault("enrichmentGapsByLayer", {})

    if args.geocode:
        g = by_layer["geocode"] = []
        # B60: follow first-party map SHORT links FIRST - the author's own pin always beats a
        # town centroid, and geocode() must not fill a coordinate this pass can supply exactly.
        nl = resolve_map_links(canonical, g, updates)
        if nl:
            print(f"map links: resolved {nl} first-party pin(s)")
        n = geocode(canonical, g, updates); flags["geocode"] = True
        print(f"geocode: filled {n} coordinates")
    if args.pois:
        g = by_layer["pois"] = []
        n, live = attach_pois(canonical, g); flags["pois"] = True
        flags["pois_live"] = live  # genuine OSM nearest (live or web-seeded), not library stopgap
        print(f"pois: attached {n}" + ("" if live else " (library stopgap - web seeding pending)"))
    if args.osrm:
        import os
        ors_key = (args.ors_key or os.environ.get("ORS_API_KEY", "")).strip()
        g = by_layer["osrm"] = []
        n = osrm_prebake(canonical, g, args.osrm_endpoint, updates, ors_key=ors_key)
        flags["osrm"] = True
        flags["osrm_done"] = n > 0
        flags["routing"] = ("driving-hgv (openrouteservice)" if ors_key
                            else "driving-car (public OSRM fallback)")
        # a drive-times request with NO key SILENTLY gives CAR times; for an I&L brief
        # truck/HGV time is the metric that matters, so surface the downgrade in the Gaps
        # Report (it was previously only in the ledger trace - the broker never saw it)
        if not ors_key:
            g.append("Drive-times use CAR routing, not truck/HGV: no openrouteservice key "
                     "was set. For truck times set the ORS_API_KEY env var (or "
                     "project.yaml enrichment.ors_api_key) and re-run.")
        print(f"osrm: pre-baked drive-times for {n} properties ({flags['routing']})")
    if args.regions:
        g = by_layer["regions"] = []
        # LOCATION-FIRST region binding: set each property's regionCode from its
        # coordinates (exact point-in-polygon on the NUTS-3 boundaries), then a resolving
        # label, then the city - BEFORE matching profiles - so a broad/wrong text region
        # label no longer breaks the workforce bind.
        # `g` is the regions layer's OWN gap bucket, so the bind's stated-vs-polygon
        # disclosure reaches the Gaps Report by the same path the layer's other lines take.
        bind_region_codes(canonical, _regions_dataset(), g)
        # 15b: a BLANK region beside the code just bound reads that area's dataset name
        # (derived, ledgered as such; a stated region is never touched)
        nf = fill_region_from_code(canonical, _regions_dataset(), updates)
        if nf:
            print(f"regions: filled {nf} blank region label(s) from the bound NUTS-3 code")
        # I11: with each property bound to the area its coordinates PROVE it is in, a
        # dataset whose `region` labels sit at different administrative levels (a county
        # from one source, the wider region from another) is harmonised to that bind.
        # Runs AFTER the bind (it has nothing to work from before) and BEFORE the profile
        # match, so the printed narrative reads bind -> harmonise -> attach.
        nh = harmonise_regions(canonical, _regions_dataset(), g, updates)
        if nh:
            print(f"regions: harmonised {nh} region label(s) to the NUTS-3 bind")
        n = merge_regions(canonical, g, updates); flags["regions"] = True
        print(f"regions: {n} profiles attached")

    if args.ledger and updates:
        try:
            _update_ledger(Path(args.ledger), updates)
            print(f"ledger: upserted {len(updates)} enrichment trace rows")
        except Exception as e:
            by_layer.setdefault("ledger", []).append(
                f"could not write enrichment trace rows to the source ledger: {e}")

    # offline / network-dead: requested enrichment that produced nothing -> mark
    # DEGRADED explicitly (the gate then allows the empties but flags them, instead
    # of a silent thin ship). The dashboard resolves these client-side when opened online.
    degraded = []
    if args.geocode and not any(isinstance(p.get("lat"), (int, float))
                                for p in canonical.get("properties", [])):
        degraded.append("coordinates (geocoder unreachable and cache unseeded - "
                        "seed via helpers/seed_geocode.py)")
    if args.pois and not canonical.get("pois"):
        degraded.append("nearest POIs/distances (Overpass unreachable)")
    if args.regions and not canonical.get("regions"):
        degraded.append("workforce/region profiles (no cache)")
    by_layer["degraded"] = []  # rebuilt each run: a resolved degradation drops its line
    if degraded:
        flags["degraded"] = True
        by_layer["degraded"].append(
            "ENRICHMENT DEGRADED (offline / no data): " + "; ".join(degraded)
            + " - the dashboard resolves these client-side when opened online")

    # rebuild the flat list deliver.py reads from the per-layer buckets (stable order,
    # de-duped) so it always reflects the FINAL state of every layer
    _order = ["geocode", "pois", "osrm", "regions", "ledger", "degraded"]
    flat: list[str] = []
    for k in _order + [k for k in by_layer if k not in _order]:
        flat.extend(by_layer.get(k, []))
    meta["enrichmentGaps"] = list(dict.fromkeys(flat))
    gaps = meta["enrichmentGaps"]
    # ATOMIC write: enrich mutates canonical IN PLACE; a shell-cap kill mid-write
    # (routine under Cowork's ~45s cap) used to leave a truncated canonical that
    # --resume then treated as current, wedging every subsequent run
    C.atomic_write_text(path, json.dumps(canonical, ensure_ascii=False, indent=2))
    if gaps:
        print(f"NOTE {len(gaps)} enrichment gaps (see meta.enrichmentGaps / Gaps Report)")


if __name__ == "__main__":
    main()
