#!/usr/bin/env python3
"""major_cities_test.py - "Major cities" carries the nearest 400k+ city as well as the nearest
100k+ one. (15e)

THE DEFECT. `_nearest_from_dataset` kept only the single nearest city of 100k or more, so a
site in Leigh listed Wigan (9 km) and nothing else: Manchester (19 km) never reached the
POI set, and neither did any other genuinely major city. The rule now: ALSO return the
nearest city of MAJOR_CITY_POP (400k) or more when it is a DIFFERENT city, so there are at
most two city results, and exactly one when the nearest 100k+ city is itself 400k+.

Offline: the bundled cities-major dataset for the real towns, plus two tiny synthetic
datasets for the boundary. Run: python evals/major_cities_test.py"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import enrich as E  # noqa: E402

LEIGH = (53.497, -2.519)
MANCHESTER = (53.4808, -2.2426)


def cities_of(found: dict) -> list:
    return [q["name"] for q in found.values() if q.get("type") == "city"]


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    ds = E._cities_major_dataset()
    if not ds:
        print("  [FAIL] the bundled cities-major dataset did not load")
        return 1

    print("the bundled dataset:")
    f1 = E._nearest_from_dataset(*LEIGH, None, None, ds)
    ck(cities_of(f1) == ["Wigan", "Manchester"],
       f"Leigh -> Wigan (nearest 100k+) and Manchester (nearest 400k+) ({cities_of(f1)})")
    ck(f1["city"]["name"] == "Wigan",
       "...and the 'city' slot is still the nearest one, so 'Nearest major city' is unchanged")
    f2 = E._nearest_from_dataset(*MANCHESTER, None, None, ds)
    ck(cities_of(f2) == ["Manchester"] and "city_major" not in f2,
       f"a point whose nearest 100k+ city is itself 400k+ gets ONE city ({cities_of(f2)})")

    print("\nsynthetic boundary:")
    town = {"name": "Smallton", "lat": 50.00, "lng": 0.00, "population": 150_000, "country": "XX"}
    big = {"name": "Bigcity", "lat": 50.20, "lng": 0.00, "population": 900_000, "country": "XX"}
    f3 = E._nearest_from_dataset(50.01, 0.0, None, None, {"cities": [town, big]})
    ck(cities_of(f3) == ["Smallton", "Bigcity"] and f3["city_major"]["population"] == 900_000,
       f"a nearer small city and a farther big one -> both ({cities_of(f3)})")
    f4 = E._nearest_from_dataset(50.01, 0.0, None, None,
                                 {"cities": [dict(town, population=E.MAJOR_CITY_POP), big]})
    ck(cities_of(f4) == ["Smallton"],
       f"the nearest city at exactly MAJOR_CITY_POP counts as major -> one city ({cities_of(f4)})")
    far = dict(big, lat=60.0)  # ~1,100 km: past the city cap
    f5 = E._nearest_from_dataset(50.01, 0.0, None, None, {"cities": [town, far]})
    ck(cities_of(f5) == ["Smallton"], "a 400k+ city beyond the distance cap is not returned")

    print("\nattach_pois ships both into the POI set:")
    saved = (E.CACHE_DIR, E.SEED_DIR, E._DATASET, E._BORDERS)
    try:
        with tempfile.TemporaryDirectory() as td:
            E.CACHE_DIR = E.SEED_DIR = Path(td)
            E._DATASET = E._BORDERS = False  # cities only: the other layers are not under test
            c = {"properties": [{"id": 1, "city": "Leigh", "lat": LEIGH[0], "lng": LEIGH[1]}],
                 "meta": {}}
            _, live = E.attach_pois(c, [])
            # the 400k+ result is typed 'city_major' so the dashboard (v46) can flag it major
            cities = {q["name"]: q for q in c["pois"] if q["type"] in ("city", "city_major")}
            ck({"Wigan", "Manchester"} <= set(cities) and live
               and cities.get("Manchester", {}).get("type") == "city_major"
               and cities.get("Wigan", {}).get("type") == "city",
               f"canonical.pois carries both city POIs, the major one typed apart ({sorted(cities)})")
            ck("nearest major city" in cities.get("Wigan", {}).get("note", "")
               and "400,000+" in cities.get("Manchester", {}).get("note", ""),
               "...each note says which rule picked it")
    finally:
        E.CACHE_DIR, E.SEED_DIR, E._DATASET, E._BORDERS = saved

    print(f"\nMAJOR CITIES TEST: {'PASS' if not fails else f'FAIL ({len(fails)})'}")
    for f in fails:
        print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
