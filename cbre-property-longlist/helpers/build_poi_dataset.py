#!/usr/bin/env python3
"""build_poi_dataset.py - normalise raw POI exports into assets/poi_dataset.json.

THE STRUCTURAL IDEA: with COMPLETE datasets bundled in the skill, nearest-POI
becomes a pure offline computation - "nearest of a complete set" IS the genuine
nearest, so the build needs no Overpass at all (no server OOMs, no radius
limits, no marina/glider noise) and the web handoff shrinks to drive-times +
geocoding. The dataset is versioned, integrity-covered and org-maintainable:
drop updated exports into a folder, re-run this, re-run make_integrity.py.

Auto-detected input schemas (mix freely in one folder):
  * OurAirports airports.csv (public domain, the canonical airport dataset) -
    filtered to large/medium airports WITH scheduled service (no glider strips,
    no military) -> type "air"
  * the flight-API viewport JSON ({"response":{"airports":[...]}}) - same
    filter (type large/medium, restriction public) -> type "air"
  * the port-directory JSON ({"data":[{name, lat, lng, country_id,...}]})
    -> type "port"
  * the SGKV intermodal-terminal JSON ([{TERMINAL_NAME, LATITUDE, LONGITUDE,
    TERMINAL_LAND,...}]) -> type "rail"
Border crossings and cities stay in assets/poi_library.json (small, curated).

CLI:
  python helpers/build_poi_dataset.py <exports-folder> [--out assets/poi_dataset.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


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


def _f(v):
    try:
        x = float(str(v).strip())
        return x if x == x else None  # NaN guard
    except Exception:
        return None


# LEAN entries by design (the dataset ships inside the skill): name, type,
# 4-decimal coordinates (~11 m), and a size class ONLY where the source
# genuinely states one. Nothing else - no operators, addresses or countries.
def _entry(name: str, typ: str, lat: float, lng: float, size: str = "") -> dict:
    e = {"name": str(name).strip(), "type": typ,
         "lat": round(lat, 4), "lng": round(lng, 4)}
    if size:
        e["size"] = size
    return e


def _parse_ourairports_csv(path: Path) -> list[dict]:
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("type") not in ("large_airport", "medium_airport"):
                continue
            if r.get("scheduled_service") != "yes":
                continue
            lat, lng = _f(r.get("latitude_deg")), _f(r.get("longitude_deg"))
            if lat is None or lng is None:
                continue
            out.append(_entry(r["name"], "air", lat, lng,
                              r["type"].replace("_airport", "")))
    return out


def _parse_ourairports_json(data: list) -> list[dict]:
    """OurAirports-style records as a JSON array (the org's airport export):
    same filter as the CSV - large/medium WITH scheduled service; 'closed' and
    small strips never become 'nearest airport'."""
    out = []
    for r in data:
        if r.get("type") not in ("large_airport", "medium_airport"):
            continue
        if str(r.get("has_scheduled_service", r.get("scheduled_service", ""))) not in ("1", "yes"):
            continue
        lat, lng = _f(r.get("latitude_deg")), _f(r.get("longitude_deg"))
        if lat is None or lng is None:
            continue
        out.append(_entry(r.get("name", "Airport"), "air", lat, lng,
                          r["type"].replace("_airport", "")))
    return out


def _parse_airport_api_json(data: dict) -> list[dict]:
    out = []
    for a in (data.get("response", {}) or {}).get("airports", []):
        if a.get("type") not in ("large", "medium") or a.get("restriction") != "public":
            continue
        lat, lng = _f(a.get("lat")), _f(a.get("lon"))
        if lat is None or lng is None:
            continue
        out.append(_entry(a.get("name", a.get("ICAO", "Airport")), "air",
                          lat, lng, a["type"]))
    return out


def _parse_ports_json(data) -> list[dict]:
    rows = data.get("data", []) if isinstance(data, dict) else data
    out = []
    for p in rows:
        # PHYSICAL facilities only: the directory also lists shipping-line OFFICES
        # (itemtype 'operator'/'business' at street addresses - one shipped as
        # "nearest port, 40 km inland of Madrid" before this filter)
        if str(p.get("itemtype_id", "port")) not in ("port", "terminal"):
            continue
        lat, lng = _f(p.get("lat")), _f(p.get("lng"))
        if lat is None or lng is None or not p.get("name"):
            continue
        out.append(_entry(f"{p['name']} (Port)", "port", lat, lng))
    return out


def _parse_sgkv_json(data: list) -> list[dict]:
    out = []
    for t in data:
        lat, lng = _f(t.get("LATITUDE")), _f(t.get("LONGITUDE"))
        if lat is None or lng is None or not t.get("TERMINAL_NAME"):
            continue
        out.append(_entry(t["TERMINAL_NAME"], "rail", lat, lng))
    return out


def _detect_and_parse(path: Path) -> tuple[str, list[dict]]:
    if path.suffix.lower() == ".csv":
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
        if "latitude_deg" in head:
            return "ourairports csv", _parse_ourairports_csv(path)
        return "unknown csv", []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return "unreadable", []
    if isinstance(data, dict) and isinstance(data.get("response"), dict) \
            and "airports" in data["response"]:
        return "airport-api json", _parse_airport_api_json(data)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return "port-directory json", _parse_ports_json(data)
    if isinstance(data, list) and data and "TERMINAL_NAME" in data[0]:
        return "sgkv intermodal json", _parse_sgkv_json(data)
    if isinstance(data, list) and data and "latitude_deg" in data[0]:
        return "ourairports json", _parse_ourairports_json(data)
    return "unknown json", []


def _dedupe(pois: list[dict], km: float = 1.5) -> list[dict]:
    """Drop same-type near-duplicates (two exports covering the same facility);
    the longer name (usually the richer one) wins. O(n) via rounded-grid buckets."""
    grid: dict[tuple, dict] = {}
    step = km / 111.0
    for p in sorted(pois, key=lambda x: -len(x["name"])):
        key = (p["type"], round(p["lat"] / step), round(p["lng"] / step))
        if key not in grid:
            grid[key] = p
    return sorted(grid.values(), key=lambda p: (p["type"], p["name"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="folder of raw exports (mixed schemas auto-detected)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "assets" / "poi_dataset.json"))
    args = ap.parse_args()
    folder = Path(args.folder)
    sys.stdout.reconfigure(encoding="utf-8")

    pois, sources = [], []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".json", ".txt", ".csv"):
            continue
        kind, rows = _detect_and_parse(f)
        print(f"  {f.name}: {kind} -> {len(rows)} entries")
        if rows:
            pois += rows
            sources.append({"file": f.name, "schema": kind, "entries": len(rows)})
        elif kind.startswith("unknown"):
            print(f"    WARNING: schema not recognised - file skipped")

    before = len(pois)
    pois = _dedupe(pois)
    counts = {}
    for p in pois:
        counts[p["type"]] = counts.get(p["type"], 0) + 1
    out = _write_gz(Path(args.out), json.dumps({
        "version": 1,
        "note": ("COMPLETE-coverage POI dataset, LEAN by design (name/type/coords/size "
                 "only) - nearest-of-this-set IS the genuine nearest. Rebuild: "
                 "python helpers/build_poi_dataset.py <exports folder>; then "
                 "helpers/make_integrity.py. Borders/cities live in poi_library.json."),
        "sources": sources,
        "counts": counts,
        "pois": pois,
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"OK {len(pois)} POIs ({before - len(pois)} near-duplicates dropped) -> {out}")
    print(f"   by type: {counts}")


if __name__ == "__main__":
    main()
