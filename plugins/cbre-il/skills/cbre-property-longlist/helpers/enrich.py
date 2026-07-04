#!/usr/bin/env python3
"""enrich.py - Stage 3. OPTIONAL, broker-opt-in enrichment of canonical.json.

  --geocode : fill missing lat/lng from the city (Nominatim, cached) with
              coordsApprox=true; also reverse-geocodes the country code from the
              result and fills an unknown ('??') country - so any geography works
              without a region-specific city index. Offline -> POI-library city
              centroid (CEE seed). Needed for the map view.
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
                data = json.loads(f.read_text(encoding="utf-8"))
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


def _cache_lookup(cache: dict, city: str, country: str):
    """Find a cached geocode for this city: exact 'city|country' key first. The cross-country
    prefix fallback (any entry for the same city under a DIFFERENT/unknown country) is taken
    ONLY when this property's country is itself UNKNOWN - so a cache the orchestrator seeded
    online as 'city|es' is still found when the property is still '??' (the sandbox-offline /
    WebFetch pattern), but a KNOWN country never adopts a wrong-country cache entry
    (bug #5: 'Toledo|ES' must not resolve to a cached 'Toledo|US')."""
    hit = cache.get(f"{city}|{country}".lower())
    if hit is not None:
        return _coords_cc(hit)
    if not _is_unknown_cc(country):
        return None, ""          # KNOWN country + exact miss -> honest miss, never cross-country
    pref = f"{city.strip().lower()}|"
    for k, v in cache.items():
        if k.startswith(pref):
            return _coords_cc(v)
    return None, ""


_POI_LIB_CACHE: dict | None = None  # parse poi_library.json once per process (read-only)


def _poi_lib() -> dict:
    global _POI_LIB_CACHE
    if _POI_LIB_CACHE is None:
        f = C.ASSETS / "poi_library.json"
        try:  # a corrupt/truncated library degrades the fallback, never crashes enrich
            _POI_LIB_CACHE = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"pois": [], "city_country": {}}
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
            return json.loads(pj.read_text(encoding="utf-8"))
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
    complete cities-major dataset - each capped by POI_MAX_KM (past the cap we honestly give
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
        if "city" not in found or km < found["city"]["km"]:
            found["city"] = {"name": c["name"], "type": "city", "lat": c["lat"],
                             "lng": c["lng"], "km": round(km, 1), "dataset": True,
                             "country": c.get("country", ""), "population": c.get("population")}
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
    return not str(v or "").strip() or str(v).strip().lower() in ("??", "tbd", "—", "none")


def _geocode_one(requests, city: str, country_cc: str):
    """One Nominatim lookup -> ([lat,lng], 'CC') or (None, ''). country_cc (ISO-2)
    biases the search; '' searches globally."""
    params = {"q": city, "format": "json", "limit": 1, "addressdetails": 1}
    if country_cc:
        params["countrycodes"] = country_cc.lower()
    arr = requests.get("https://nominatim.openstreetmap.org/search",
                       params=params, headers=UA, timeout=12).json()
    if not arr:
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


def geocode(canonical: dict, gaps: list, updates: list | None = None) -> int:
    """Fill missing lat/lng and reverse-geocode an unknown country. A bare city name
    is globally AMBIGUOUS (a Spanish town can also exist in Latin America/India), so
    after a first pass we take the dataset's dominant country and RE-QUERY any
    unknown-country property that landed as a far geographic outlier, constrained to
    that country. Mode-based - no hardcoded country, works for any geography."""
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

    # PASS A: resolve each UNAMBIGUOUS city (cached, or a unique-name gazetteer/network hit).
    # An AMBIGUOUS bare name (same name in >1 country, unknown country) MISSES here - the
    # ambiguity-aware _gazetteer_lookup returns nothing without a dominant country - and is
    # DEFERRED to the dominant-country PASS B, never resolved to a pre-baked wrong-country
    # pick (bug #3). In Cowork the helper-side network is dead BY DESIGN (the orchestrator
    # seeds the cache via seed_geocode.py); the first network failure circuit-breaks.
    dead = False
    res = {}  # id(p) -> [latlng, cc, known, city, country, source]
    for p in todo:
        city = str(p.get("city", "")).strip()
        country = str(p.get("country", "")).strip()
        known = not _is_unknown_cc(country)
        latlng, cc = _cache_lookup(cache, city, country)
        src = "cache" if latlng is not None else ""
        # OFFLINE FIRST: the bundled European city gazetteer resolves real city coordinates
        # (+ country) with ZERO network, so the map works in Cowork without the exit-8
        # round-trip; the browser handoff is reserved strictly for live ROUTING.
        if latlng is None and city and not _is_unknown_cc(city):
            gll, gcc = _gazetteer_lookup(city, country)
            if gll:
                latlng, cc, src = gll, (gcc or cc), "gazetteer"
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

    filled = 0
    for p in props:
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
                    _ll, ccn = _cache_lookup(cache, city, "")
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
                    else:
                        csf, cst, cloc = "Nominatim (OSM geocoder)", "web", f"geocode of '{city}'"
                    updates.append(_trace(p.get("id"), "country", cc, csf, cloc, cst))
            filled += 1
            if updates is not None:  # trace rows so the ledger matches the deliverable
                if from_centroid:
                    sf, st, loc = "assets/poi_library.json", "poi_library", f"city centroid '{city}' (coordsApprox)"
                elif src in ("gazetteer", "gazetteer-dominant"):
                    detail = "city gazetteer" if src == "gazetteer" else "city gazetteer (dominant-country)"
                    sf, st, loc = "assets/cities_dataset.json", "dataset", f"{detail} '{city}' (coordsApprox)"
                elif src == "cache":
                    sf, st, loc = "geocode_cache.json", "cache", f"seeded geocode cache '{city}' (coordsApprox)"
                else:
                    sf, st, loc = "Nominatim (OSM geocoder)", "web", f"geocode '{city}' (coordsApprox)"
                updates.append(_trace(p.get("id"), "lat", p["lat"], sf, loc, st))
                updates.append(_trace(p.get("id"), "lng", p["lng"], sf, loc, st))
        else:
            gaps.append(f"could not geocode '{city}' (property id={p.get('id')})")
    if dirty:
        _save_cache(GEOCODE_CACHE, cache)
    return filled


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
POI_TYPES = ("air", "port", "rail", "border", "city")
# per-type give-up caps (km): inside OVERPASS_RADIUS_M the genuine OSM nearest
# wins; beyond it the curated MAJOR-facilities library supplements up to these
# caps (labelled as such); past the cap we honestly give up - never a far stand-in.
POI_MAX_KM = {"air": 600, "port": 800, "rail": 300, "border": 400, "city": 300}


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
            for t, poi in found.items():
                key = (poi["name"], t, round(poi["lat"], 3), round(poi["lng"], 3))
                if poi.get("dataset"):
                    src = ("CBRE border dataset" if t == "border"
                           else "CBRE cities dataset" if t == "city"
                           else "CBRE POI dataset")
                else:
                    src = "curated library"
                note = f"nearest {t} ({src})"
                if t == "border" and poi.get("crossingOf"):
                    note = f"nearest border crossing {poi['crossingOf']} ({src})"
                if t == "city" and poi.get("population"):
                    # population is SHOWN here (renders in the modal distance note + map popup);
                    # no chrome change needed - the template already renders poi.note verbatim.
                    note = f"nearest major city ({src}; pop {poi['population']:,})"
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
    ("UKD", "North West England"), ("UKJ", "South East England"), ("UKH", "East of England"),
    ("UKI", "London", "greater london"), ("UKK", "South West England"), ("UKC", "North East England"),
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
    hit = ni.get(_norm_region(code))
    if hit and len(hit) == 1:
        return ds["regions"][hit[0]]
    # bilingual / dual-name fallback: split the QUERY on / , ; and parentheticals too, so a
    # property carrying a joined ('Valencia / Valencia') or local-language ('Alacant') form
    # resolves even against a dataset that was not re-indexed with variants (defense in depth)
    try:
        from build_regions_dataset import _name_variants
        variants = _name_variants(code)
    except Exception:
        variants = {_norm_region(code)}
    for v in variants:
        h = ni.get(v)
        if h and len(h) == 1:
            return ds["regions"][h[0]]
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
        data = json.loads(f.read_text(encoding="utf-8"))
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


def _ok_region_city(c) -> bool:
    return isinstance(c, str) and bool(c.strip()) and \
        c.strip().lower() not in ("tbd", "tbc", "??", "—", "-", "n/a", "na")


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


def bind_region_codes(canonical: dict, ds: dict | None) -> None:
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
    and the difflib gap in merge_regions remains the fallback when the resolution is null."""
    if not ds:
        return
    geo = _regions_geo()
    label_cache = _region_labels_cache()  # {} when work/extract/region_labels.json is absent

    def _ok_city(c):
        return _ok_region_city(c)

    for p in canonical.get("properties", []):
        lat, lng = p.get("lat"), p.get("lng")
        if geo and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            code = _region_for_point(lat, lng, geo)
            if code and _dataset_region(ds, code):  # the polygon's code must have a profile
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
    canonical = json.loads(path.read_text(encoding="utf-8"))
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
        bind_region_codes(canonical, _regions_dataset())
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
