#!/usr/bin/env python3
"""Stage 5 (code half): cluster duplicate facility records AFTER geocoding.

The hardest correctness problem in the map is that one building arrives twice:
once under the occupier's name and once under its 3PL operator's name, with
addresses formatted differently each time. String-matching the address misses
these. Running this AFTER geocoding lets us use the one signal that actually
disambiguates a building, its location.

Two records are clustered as the same site when ANY of:
  * both carry street/rooftop coordinates within --radius metres (default 150).
    City-centroid pins are excluded from the proximity rule, because every site
    in one city shares the same centroid and would falsely merge.
  * their normalised addresses are equal and non-empty.
  * they share a postcode AND a normalised city.

Clustering only proposes merges. It never silently averages or picks a winner
between conflicting sources: each multi-member cluster is emitted with every
conflicting field laid out under "_conflicts" for the Stage 5 model step to
resolve by source rank. Sources are unioned so nothing is lost.

Usage:
  python dedup.py --in records_geocoded.json --out records_deduped.json \
                  --review merge_review.json [--radius 150]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    TBD,
    extract_postcode,
    haversine_m,
    is_number,
    load_records,
    normalize_address,
    save_records,
    strip_accents,
)

# Fields where a difference between two clustered records is a real conflict
# that a human/model must resolve, not something to merge blindly.
_CONFLICT_FIELDS = [
    "size_sqm",
    "in_use_since",
    "operator",
    "landlord_or_developer",
    "facility_type",
]


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _street_coord(rec: dict[str, Any]) -> tuple[float, float] | None:
    if rec.get("geocode_precision") not in {"rooftop", "street"}:
        return None
    lat, lon = rec.get("lat"), rec.get("long")
    if is_number(lat) and is_number(lon):
        return float(lat), float(lon)
    return None


def _same_site(a: dict[str, Any], b: dict[str, Any], radius_m: float) -> bool:
    ca, cb = _street_coord(a), _street_coord(b)
    if ca and cb and haversine_m(ca[0], ca[1], cb[0], cb[1]) <= radius_m:
        return True
    na = normalize_address(a.get("full_address", ""))
    nb = normalize_address(b.get("full_address", ""))
    if na and na == nb:
        return True
    pa = extract_postcode(a.get("full_address", ""), a.get("country", ""))
    pb = extract_postcode(b.get("full_address", ""), b.get("country", ""))
    if pa and pa == pb:
        cta = strip_accents(str(a.get("city", "")).strip().lower())
        ctb = strip_accents(str(b.get("city", "")).strip().lower())
        if cta and cta == ctb:
            return True
    return False


def _merge_cluster(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one representative record, flagging conflicts rather than guessing."""
    rep: dict[str, Any] = dict(members[0])

    # Union sources across all members, de-duplicated by URL.
    seen, sources = set(), []
    for m in members:
        for s in m.get("sources") or []:
            url = (s or {}).get("url")
            if url and url not in seen:
                seen.add(url)
                sources.append(s)
    rep["sources"] = sources

    # For each conflict-prone field, collect distinct non-tbd values.
    conflicts: dict[str, list[Any]] = {}
    for field in _CONFLICT_FIELDS:
        vals = []
        for m in members:
            v = m.get(field)
            if v not in (None, "", TBD) and v not in vals:
                vals.append(v)
        if len(vals) == 1:
            rep[field] = vals[0]
        elif len(vals) > 1:
            rep[field] = TBD  # do not pick; leave for source-rank resolution
            conflicts[field] = vals

    if conflicts:
        rep["_conflicts"] = conflicts
        rep["_needs_resolution"] = True
    rep["_merged_from"] = len(members)
    return rep


def run(args: argparse.Namespace) -> int:
    records = load_records(args.infile)
    n = len(records)
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _same_site(records[i], records[j], args.radius):
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    deduped, review = [], []
    for idxs in groups.values():
        members = [records[i] for i in idxs]
        if len(members) == 1:
            deduped.append(members[0])
        else:
            deduped.append(_merge_cluster(members))
            review.append({
                "cluster_size": len(members),
                "member_indices": idxs,
                "addresses": [m.get("full_address", "") for m in members],
                "operators": [m.get("operator", "") for m in members],
                "found_via": [str(m.get("comments", ""))[:80] for m in members],
            })

    save_records(args.out, deduped)
    if args.review:
        Path(args.review).write_text(
            json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    merged = sum(len(g) for g in groups.values() if len(g) > 1)
    print(f"Dedup: {n} records -> {len(deduped)} sites "
          f"({len(review)} cluster(s) merged from {merged} records)")
    needs = sum(1 for r in deduped if r.get("_needs_resolution"))
    if needs:
        print(f"  {needs} merged site(s) carry source conflicts flagged in "
              f"'_conflicts' for the Stage 5 model step to resolve by source rank.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Cluster duplicate warehouse records.")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--review", default="", help="optional merge-review JSON for QA")
    p.add_argument("--radius", type=float, default=150.0,
                   help="proximity threshold in metres (default 150)")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
