#!/usr/bin/env python3
"""build_region_geo.py - GISCO NUTS-3 boundary GeoJSON -> assets/regions_geo.json.gz.

Builds the bundled NUTS-3 BOUNDARY asset that lets enrich.py bind a property to its
workforce region by POINT-IN-POLYGON on the property's coordinates - exact, and
label-independent. This replaces the earlier nearest-centroid idea, which wrongly
bound an edge-of-province town to its big-city neighbour (measured: Azuqueca de
Henares, a Guadalajara logistics hub on the Madrid border, fell on Madrid's centroid).
Point-in-polygon puts Azuqueca correctly in Guadalajara (ES424).

SOURCE: Eurostat GISCO NUTS regions (NUTS_RG), WGS84, level 3 - official, free, the
NUTS_ID matches the workforce dataset's codes. Download once (03M = 1:3M scale, a good
border-fidelity/size balance; 10M/20M are smaller and still classify inland borders):
  Invoke-WebRequest `
    'https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_03M_2021_4326_LEVL_3.geojson' `
    -OutFile nuts_rg_03M.geojson

OUTPUT (compact + GZIPPED, deterministic via mtime=0 so the bytes are byte-stable for
the integrity manifest): a dict {version, note, regions: {NUTS_ID: {bbox:[minlng,minlat,
maxlng,maxlat], poly:[[ring,...],...]}}} where each ring is [[lng,lat],...] rounded to 4dp.
A Polygon becomes one poly; a MultiPolygon several.

Org maintenance: after build_regions_dataset.py, run this against the GISCO NUTS_RG
file (same NUTS version), then helpers/make_integrity.py.

CLI:
  python helpers/build_region_geo.py <NUTS_RG_..._LEVL_3.geojson>
                                     [--out assets/regions_geo.json.gz]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

_DP = 4  # ~11 m; 03M simplification is coarser than this, so it is lossless in practice


def _round_ring(ring):
    return [[round(pt[0], _DP), round(pt[1], _DP)] for pt in ring]


def _normalise(geom):
    """GeoJSON geometry -> a list of polygons, each = [exterior_ring, hole1, ...]."""
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Polygon":
        return [[_round_ring(r) for r in c]]
    if t == "MultiPolygon":
        return [[_round_ring(r) for r in poly] for poly in c]
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("geojson", help="GISCO NUTS_RG boundary GeoJSON (level 3, EPSG:4326)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "assets" / "regions_geo.json.gz"))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    gj = json.loads(Path(args.geojson).read_text(encoding="utf-8"))
    regions: dict[str, dict] = {}
    for feat in gj.get("features", []):
        nid = str((feat.get("properties") or {}).get("NUTS_ID", "")).strip()
        polys = _normalise(feat.get("geometry") or {})
        if not nid or not polys:
            continue
        xs, ys = [], []
        for poly in polys:
            for ring in poly:
                for x, y in ring:
                    xs.append(x); ys.append(y)
        regions[nid] = {"bbox": [min(xs), min(ys), max(xs), max(ys)], "poly": polys}

    payload = json.dumps({
        "version": 1,
        "note": ("Bundled NUTS-3 boundary polygons (GISCO NUTS_RG, level 3, WGS84) for "
                 "point-in-polygon region binding. Rebuild from a fresh GISCO file with "
                 "helpers/build_region_geo.py, then helpers/make_integrity.py."),
        "regions": regions,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(payload, mtime=0))  # mtime=0 -> deterministic bytes

    print(f"OK {len(regions)} NUTS-3 polygons -> {out} "
          f"({out.stat().st_size / 1024:.0f} KB gzipped, {len(payload) / 1024:.0f} KB raw)")


if __name__ == "__main__":
    main()
