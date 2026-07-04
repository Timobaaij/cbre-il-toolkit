#!/usr/bin/env python3
"""build_borders_dataset.py - fetch a COMPLETE set of European road border crossings from
OpenStreetMap (Overpass) into assets/borders_dataset.json.gz.

THE STRUCTURAL IDEA (same as poi_dataset / cities_dataset): bundle the COMPLETE set so
nearest-border becomes a pure OFFLINE computation - nearest-of-this-set IS the genuine
nearest crossing, no live Overpass at build/run time. Org-maintainable: re-run this (needs
network once), then helpers/make_integrity.py. Unlike the air/port/rail dataset (static org
exports) borders come from OSM, so this builder DOES hit Overpass - politely, chunked by
country, retried across mirror endpoints, cached to a temp dir (--raw) so a partial run
resumes without re-fetching completed countries.

CLI:
  python helpers/build_borders_dataset.py [--out assets/borders_dataset.json]
      [--endpoint <one overpass url>] [--only PL,DE] [--raw <cache dir>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cities_dataset import EUROPEAN_CC, _write_gz   # ONE definition of Europe + gzip idiom

# Public Overpass mirrors - rotated on 429/timeout so a busy primary does not fail the build.
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = {"User-Agent": "cbre-property-longlist/1.0 (CBRE I&L internal tooling)"}


def _query(cc: str) -> str:
    return (f'[out:json][timeout:180];'
            f'area["ISO3166-1"="{cc}"][admin_level=2]->.a;'
            f'(node["barrier"="border_control"](area.a);'
            f'way["barrier"="border_control"](area.a););'
            f'out tags center qt;')


def _fetch(requests, endpoints: list, cc: str) -> list:
    """One country's crossings, trying each mirror with backoff. RAISES on an errored
    'remark' response (never cache an error as 'no crossings'); rotates endpoints and
    retries on 429/504/network error. Mirrors enrich._overpass_around's error discipline."""
    last = None
    q = _query(cc)
    for endpoint in endpoints:
        for attempt in (1, 2, 3):
            try:
                resp = requests.post(endpoint, data={"data": q}, headers=UA, timeout=200)
                if resp.status_code in (429, 504):
                    last = RuntimeError(f"{endpoint} busy (HTTP {resp.status_code})")
                    time.sleep(8 * attempt)
                    continue
                j = resp.json()
                if "error" in str(j.get("remark", "")).lower():
                    raise RuntimeError(f"Overpass remark: {str(j['remark'])[:120]}")
                return j.get("elements", [])
            except RuntimeError:
                raise                       # a genuine query error - do not silently retry
            except Exception as e:
                last = e
                time.sleep(5 * attempt)
    raise RuntimeError(f"Overpass unreachable for {cc}: {last}")


_NONCROSSING_RE = re.compile(
    r"customs|aduana|douane|zoll|dogana|alfandega|alfândega|celni|celní|"
    r"passport|inland border|ticket|check-?in|waiting|dry port|bonded|security",
    re.I)


def _is_noncrossing(tags: dict) -> bool:
    """True for a barrier=border_control node that is NOT a road LAND crossing: an inland
    customs office / bonded depot, a passport-or-ticket booth, a ferry check-in, a security
    post. Matched on amenity + the name-ish tags (multilingual customs synonyms). Keeps the
    dataset to genuine crossings so 'nearest border' is never a customs office 4 km inland or a
    'Warrington Inland Border Facility'."""
    if tags.get("amenity") in ("customs", "security_control"):
        return True
    blob = " ".join(str(v) for k, v in tags.items()
                    if k in ("name", "name:en", "int_name", "official_name", "description"))
    return bool(_NONCROSSING_RE.search(blob))


def _name(tags: dict, cc: str) -> str:
    for k in ("name", "name:en", "int_name"):
        v = str(tags.get(k, "")).strip()
        if v:
            return v if v.lower().endswith("border") else f"{v} (Border)"
    return f"{cc} border crossing (Border)"


def _crossing_of(tags: dict) -> str:
    # e.g. name "Swiecko (PL/DE)" -> "PL/DE"; else "" (never invent)
    m = re.search(r"\b([A-Z]{2})\s*[/-]\s*([A-Z]{2})\b", " ".join(str(v) for v in tags.values()))
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def _parse(elements: list, cc: str) -> list:
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        if tags.get("barrier") != "border_control":
            continue          # keep only manned road border-control posts (drop inland customs
            #                    offices, bonded depots and airport customs, which are NOT crossings)
        if "level" in tags or "building" in tags:
            continue    # an INDOOR checkpoint (level) or a mapped control BUILDING/guardhouse
            #             (building) - not the road crossing node itself (a node ON the highway);
            #             e.g. a building=guardhouse 16 km inland from Madrid is not a crossing
        if _is_noncrossing(tags):
            continue    # a customs office / inland facility / passport-or-ticket / ferry booth -
            #             not a road land crossing ('Aduana', 'Warrington Inland Border Facility')
        c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        rec = {"name": _name(tags, cc), "type": "border",
               "lat": round(float(lat), 4), "lng": round(float(lon), 4), "country": cc}
        co = _crossing_of(tags)
        if co:
            rec["crossingOf"] = co
        out.append(rec)
    return out


def _load_hubs() -> list:
    """Bundled airport + seaport coords (assets/poi_dataset.json.gz, type in air/port). Used to
    drop transport-hub IMMIGRATION checkpoints: OSM tags airport passport control AND seaport /
    ferry passport control as barrier=border_control, but neither is a road/freight LAND border
    crossing (an airport node 16 km from Madrid = Barajas; a ferry booth at Dover is a seaport,
    already covered by the nearest-port metric)."""
    import gzip
    p = Path(__file__).resolve().parent.parent / "assets" / "poi_dataset.json.gz"
    try:
        d = json.loads(gzip.decompress(p.read_bytes()))
    except Exception:
        return []
    return [(q["lat"], q["lng"]) for q in d.get("pois", []) if q.get("type") in ("air", "port")]


def _hav_km(a1, b1, a2, b2) -> float:
    import math
    p1, p2 = math.radians(a1), math.radians(a2)
    dp, dl = math.radians(a2 - a1), math.radians(b2 - b1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(x)))


def _drop_hub_immigration(pois: list, hubs: list, km: float = 2.0) -> list:
    """Drop border-control points within `km` of a bundled (medium/large) airport OR seaport -
    these are transport-hub passport control, not road land crossings (an airport immigration
    node; a ferry/seaport passport booth, already covered by the nearest-port metric). A TIGHT
    2 km radius so a genuine road crossing near a border airport/port (Basel EuroAirport, a
    river-port border town) is NOT dropped; small airfields/harbours are absent from the set."""
    if not hubs:
        return pois
    # coarse 1-degree bucketing so each crossing only checks nearby hubs (not all ~3.8k)
    buckets: dict = {}
    for a in hubs:
        buckets.setdefault((round(a[0]), round(a[1])), []).append(a)
    out = []
    for p in pois:
        blat, blng = round(p["lat"]), round(p["lng"])
        near = []
        for dla in (-1, 0, 1):
            for dlo in (-1, 0, 1):
                near += buckets.get((blat + dla, blng + dlo), [])
        if any(_hav_km(p["lat"], p["lng"], a[0], a[1]) <= km for a in near):
            continue
        out.append(p)
    return out


# Countries with a MAJOR land border to a non-European-gazetteer neighbour (RU / TR) or that are
# no-land-border / divided islands: the "near a different-country city" inland-stray filter below
# would wrongly drop their genuine EU-external crossings (FI/RU Vaalimaa, PL/RU Kaliningrad,
# GR/TR Kipoi, the CY Green Line), so we DO NOT filter these - their real external crossings stay.
_BORDER_NOFILTER_CC = {"NO", "FI", "EE", "LV", "LT", "PL", "BY", "UA", "GR", "BG",
                       "RU", "TR", "IS", "MT", "CY"}


def _load_gaz_by_cc() -> dict:
    """Gazetteer cities bucketed by 1-degree cell -> [(lat,lng,cc)] from cities_dataset.json.gz.
    Used to test whether a border node sits near a DIFFERENT country: a genuine international
    crossing does; an inland OSM-mistagged border_control node (a nameless guardhouse, a stray
    city node) does not."""
    import gzip
    p = Path(__file__).resolve().parent.parent / "assets" / "cities_dataset.json.gz"
    buckets: dict = {}
    try:
        d = json.loads(gzip.decompress(p.read_bytes()))
    except Exception:
        return buckets
    for key, ll in d.get("cities", {}).items():
        cc = key.rsplit("|", 1)[-1].upper()
        buckets.setdefault((round(ll[0]), round(ll[1])), []).append((ll[0], ll[1], cc))
    return buckets


def _drop_inland_strays(pois: list, buckets: dict, km: float = 60.0) -> list:
    """For a crossing whose country is NOT in _BORDER_NOFILTER_CC (all its land neighbours are in
    the European gazetteer), keep it ONLY if a DIFFERENT-country gazetteer city lies within `km`
    - i.e. it genuinely sits near an international boundary. Drops nameless inland OSM-mistagged
    border_control nodes (a central-London point; an inland Seville node) that would otherwise be
    a confidently-wrong 'nearest border'. Countries bordering a non-gazetteer neighbour (RU/TR)
    or island/divided states are exempt so their real external crossings are never dropped.
    No-op without the gazetteer (never silently empties the set)."""
    if not buckets:
        return pois
    out = []
    for p in pois:
        cc = p["country"]
        if cc in _BORDER_NOFILTER_CC:
            out.append(p)
            continue
        blat, blng = round(p["lat"]), round(p["lng"])
        near_foreign = False
        for dla in range(-2, 3):
            for dlo in range(-2, 3):
                for (a, b, c) in buckets.get((blat + dla, blng + dlo), ()):  # noqa: E741
                    if c != cc and _hav_km(p["lat"], p["lng"], a, b) <= km:
                        near_foreign = True
                        break
                if near_foreign:
                    break
            if near_foreign:
                break
        if near_foreign:
            out.append(p)
    return out


def _dedupe(pois: list, km: float = 1.0) -> list:       # mirror build_poi_dataset._dedupe
    grid, step = {}, km / 111.0
    for p in sorted(pois, key=lambda x: -len(x["name"])):   # richer name wins a collision
        key = (round(p["lat"] / step), round(p["lng"] / step))   # type is always 'border'
        grid.setdefault(key, p)
    return sorted(grid.values(), key=lambda p: (p["country"], p["name"], p["lat"], p["lng"]))


def main() -> None:
    import requests
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "assets" / "borders_dataset.json"))
    ap.add_argument("--endpoint", default="", help="force a single overpass endpoint")
    ap.add_argument("--only", default="", help="comma ISO-2 subset (debug)")
    ap.add_argument("--raw", default="", help="dir to cache each country's raw elements (resume)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    endpoints = [args.endpoint] if args.endpoint else ENDPOINTS
    ccs = ([c.strip().upper() for c in args.only.split(",") if c.strip()]
           if args.only else sorted(EUROPEAN_CC))
    raw = Path(args.raw) if args.raw else None
    if raw:
        raw.mkdir(parents=True, exist_ok=True)

    pois, sources = [], []
    for cc in ccs:
        cache = raw / f"{cc}.json" if raw else None
        if cache and cache.exists():
            elements = json.loads(cache.read_text(encoding="utf-8"))
        else:
            elements = _fetch(requests, endpoints, cc)
            if cache:
                cache.write_text(json.dumps(elements), encoding="utf-8")
            time.sleep(2.5)                              # polite - avoid Overpass 429
        rows = _parse(elements, cc)
        print(f"  {cc}: {len(elements)} elements -> {len(rows)} crossings", flush=True)
        pois += rows
        sources.append({"cc": cc, "elements": len(elements), "kept": len(rows)})

    before = len(pois)
    pois = _drop_hub_immigration(pois, _load_hubs())
    dropped_hub = before - len(pois)
    n1 = len(pois)
    pois = _drop_inland_strays(pois, _load_gaz_by_cc())
    dropped_inland = n1 - len(pois)
    pois = _dedupe(pois)
    print(f"  (dropped {dropped_hub} hub-immigration + {dropped_inland} inland-stray points; "
          f"external-EU crossings in {len(_BORDER_NOFILTER_CC)} exempt countries kept)")
    out = _write_gz(Path(args.out), json.dumps({
        "version": 1,
        "note": ("COMPLETE-coverage European road border-crossing dataset (OSM "
                 "barrier=border_control), LEAN by design (name/type/coords/country) - "
                 "nearest-of-this-set IS the genuine nearest border. Rebuild: "
                 "python helpers/build_borders_dataset.py; then helpers/make_integrity.py."),
        "sources": sources,
        "counts": {"border": len(pois)},
        "pois": pois,
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"OK {len(pois)} crossings ({before - len(pois)} near-duplicates dropped) -> {out}")
    print("Now run: python helpers/make_integrity.py")


if __name__ == "__main__":
    main()
