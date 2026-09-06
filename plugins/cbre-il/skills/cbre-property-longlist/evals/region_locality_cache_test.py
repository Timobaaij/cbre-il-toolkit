#!/usr/bin/env python3
"""region_locality_cache_test.py - two properties in one town are two places. (G1 + G2)

THE DEFECT, in two halves that meet at the same failure.

G1 - THE GEOCODE CACHE WAS KEYED ON THE TOWN. `_cache_lookup` and every writer around it
keyed on `city|country`, so a town had exactly ONE coordinate slot and every option in it
was served the same pin. That is not a cosmetic imprecision. `match._cross_source_auto` has
a COORDINATE NET that auto-merges two records whose pins are within ~300 m, and an
auto-merged pair is never offered for adjudication - `grey_pairs` never sees it and no
'same' verdict can reach it - so an identical pin is the strongest input that net can be
given. A postal-code veto was added at the top of that tier and it catches the pairs where
BOTH sides state a code; the town-wide cache slot upstream of it was still the reason two
genuinely different buildings held one coordinate in the first place. The key now prefers
the most specific locality THE RECORD ITSELF states and falls back to the city.

G2 - NOTHING CROSS-CHECKED THE REGION BIND AGAINST THE RECORD. `bind_region_codes` derives
the workforce region by point-in-polygon and the coordinate branch returns first, so a
supplied coordinate wrong by a few hundred metres - invisible on a map - could fall the
wrong side of a simplified administrative boundary and ship a wholly different area's
workforce profile: population, labour force, unemployment, manufacturing and transport
employment, every figure cited and every figure about somewhere else. The property's own
stated region is the only independent witness available, and nobody asked it.

WHAT THIS FILE PINS, in order:
  1. two properties in one town with DIFFERENT stated codes get DIFFERENT cache keys and
     hold DIFFERENT coordinates;
  2. a corpus that states NO codes is byte-identical to the pre-change reader - proved
     against a verbatim copy of it over a matrix, and end-to-end through `geocode()`;
  3. a legacy city-keyed entry (both value shapes) still reads, and the SHIPPED seed cache
     in reference/ still loads and still resolves every one of its entries;
  4. the coarse fallback is a READ ONLY - a town-level answer is never written back under a
     locality key, which is the case where inheriting it would change nothing at all;
  5. a stated region that GENUINELY conflicts with the polygon bind is disclosed; one at a
     merely different administrative level, and one that resolves to nothing, are not;
  6. the polygon bind still wins in every one of those cases, and still wins silently for
     every existing two-argument caller.

EVERY POSTAL CODE IN THIS FILE IS INVENTED, and the shapes are mixed on purpose - the same
discipline `match._stated_postcode` and evals/overmerge_guard_test.py keep, and for the same
reason: a real national code quoted as THE example is how a country-specific parser gets
written by the next maintainer. Nothing here is country-specific, and the whole G1 layer is
inert in a market that quotes no codes at all.

Offline (bundled assets only), no network - a live geocode is asserted NEVER to be attempted.
Run: python evals/region_locality_cache_test.py"""
from __future__ import annotations
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import enrich as E  # noqa: E402

# --- the PRE-CHANGE reader, copied verbatim, as the equivalence oracle for part 2 ----------
# Kept as a literal copy rather than a call into the shipped one: the whole claim is that the
# new resolution order collapses onto THIS behaviour when no record states a code, and a claim
# cannot be checked against the thing it is about.


def _old_cache_lookup(cache: dict, city: str, country: str):
    hit = cache.get(f"{city}|{country}".lower())
    if hit is not None:
        return E._coords_cc(hit)
    if not E._is_unknown_cc(country):
        return None, ""
    pref = f"{city.strip().lower()}|"
    for k, v in cache.items():
        if k.startswith(pref):
            return E._coords_cc(v)
    return None, ""


# invented codes, deliberately different shapes
CODE_A = "QX41 7ZP"
CODE_B = "QX41 9TN"
CODE_NUM = "48215"

# the one town both options sit in, and two pins ~5 km apart inside it
TOWN, CC = "Cranleigh Vale", "GB"
PIN_A = [52.50304981, -0.650581854]
PIN_B = [52.46850533, -0.737056454]
TOWN_CENTRE = [52.4900000, -0.6900000]

# the delivered Corby coordinates region_harmony_test also runs, so a change to the bundled
# polygons fails both files rather than only one
CORBY_PIN = (52.50304981, -0.650581854)


def canon(props):
    return {"properties": copy.deepcopy(props), "meta": {}}


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    src = (ROOT / "helpers" / "enrich.py").read_text(encoding="utf-8")

    # =====================================================================================
    # 1. two options in one town, two stated codes, two keys, two pins
    # =====================================================================================
    print("two properties in one town with different stated codes:")
    pa = {"id": 1, "city": TOWN, "country": CC, "postcode": CODE_A}
    pb = {"id": 2, "city": TOWN, "country": CC, "postcode": CODE_B}
    ka = E._geo_key(TOWN, CC, E._locality_code(pa))
    kb = E._geo_key(TOWN, CC, E._locality_code(pb))
    ck(ka != kb, f"the two records key differently ({ka} vs {kb})")
    ck(ka.startswith(E._geo_key(TOWN, CC) + "|") and kb.startswith(E._geo_key(TOWN, CC) + "|"),
       "...and both keys still START with the city-level key, so no legacy entry is orphaned")
    ck(E._key_code(ka) == "qx417zp" and E._key_code(E._geo_key(TOWN, CC)) == "",
       "_key_code separates a locality key from a city-level one")
    ck(E._locality_code({"postalCode": CODE_NUM}) == "48215"
       and E._locality_code({"postcode": "  qx41   7zp "}) == CODE_A.replace(" ", ""),
       "the code is normalised for equality only (numeric cell accepted, whitespace folded)")
    ck(E._locality_code({"postcode": "tbd"}) == "" and E._locality_code({"postcode": "n/a"}) == ""
       and E._locality_code({}) == "",
       "...and a sentinel or an absent field is ABSENCE, so the layer stays inert")

    cache = {E._geo_key(TOWN, CC): {"latlng": TOWN_CENTRE, "cc": CC},
             ka: {"latlng": PIN_A, "cc": CC},
             kb: {"latlng": PIN_B, "cc": CC}}
    ck(E._cache_lookup(cache, TOWN, CC, E._locality_code(pa))[0] == PIN_A
       and E._cache_lookup(cache, TOWN, CC, E._locality_code(pb))[0] == PIN_B,
       "each record reads ITS OWN locality entry, not the town centre")
    ck(E._cache_lookup(cache, TOWN, CC)[0] == TOWN_CENTRE,
       "...and a record stating no code still reads the town centre")

    # end to end through geocode(): the two properties come out with DIFFERENT pins
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        (w / "geocode_cache.json").write_text(json.dumps(cache), encoding="utf-8")
        saved_seed, saved_cache = E.SEED_DIR, E.CACHE_DIR
        called = []
        saved_geo, saved_rev = E._geocode_one, E._reverse_cc
        E._geocode_one = lambda *a, **k: called.append(a) or (None, "")
        E._reverse_cc = lambda *a, **k: called.append(a) or ""
        try:
            E.SEED_DIR = E.CACHE_DIR = w
            c = canon([pa, pb])
            gaps, upd = [], []
            n = E.geocode(c, gaps, upd)
            got = [(p["lat"], p["lng"]) for p in c["properties"]]
            ck(n == 2 and got == [(PIN_A[0], PIN_A[1]), (PIN_B[0], PIN_B[1])],
               f"geocode() fills two DIFFERENT pins in one town (got {got})")
            ck(not called, "...with no live geocode attempted at all (the default path is offline)")
            ck(all(p.get("coordsApprox") is True for p in c["properties"]),
               "...both still flagged coordsApprox - a locality pin is not the building's own")
            locs = [u["source_locator"] for u in upd if u["field"] == "lat"]
            ck(len(locs) == 2 and locs[0] != locs[1]
               and "QX417ZP" in locs[0] and "QX419TN" in locs[1],
               "...and the LEDGER names each locality, so two pins never share one trace row")
        finally:
            E.SEED_DIR, E.CACHE_DIR = saved_seed, saved_cache
            E._geocode_one, E._reverse_cc = saved_geo, saved_rev

    # =====================================================================================
    # 2. a corpus that states NO codes behaves exactly as it did
    # =====================================================================================
    print("\na corpus that states no codes, against a verbatim copy of the old reader:")
    legacy = {
        "velke levare|sk": [48.5032707, 17.0022088],        # legacy BARE-PAIR value shape
        "toledo|us": {"latlng": [41.6528, -83.5379], "cc": "US"},
        "madrid|es": {"latlng": [40.4165, -3.7026], "cc": "ES"},
        "nowhere|es": {"latlng": None, "cc": ""},            # negative memo
        "blank|": {"latlng": [1.0, 2.0], "cc": ""},
        "nulled|es": None,                                   # a null value, tolerated
    }
    matrix = [(city, cc) for city in ("Velke Levare", "Toledo", "Madrid", "Nowhere",
                                      "Blank", "Nulled", "Absent", " Toledo ")
              for cc in ("ES", "US", "SK", "??", "", "tbd")]
    diffs = [(c, k) for c, k in matrix
             if E._cache_lookup(legacy, c, k) != _old_cache_lookup(legacy, c, k)]
    ck(not diffs, f"all {len(matrix)} (city, country) lookups agree with the old reader "
                  f"({len(diffs)} disagreement(s))")
    ck(E._cache_lookup(legacy, "Toledo", "ES") == (None, ""),
       "bug #5 stays closed: a KNOWN country never adopts a different-country entry")
    ck(E._cache_lookup(legacy, "Toledo", "??")[0] == [41.6528, -83.5379],
       "...and an UNKNOWN country still uses the cross-country scan (the seed pattern)")

    # end to end: a codeless corpus writes ONLY city-level keys and the legacy locator string
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        (w / "geocode_cache.json").write_text(json.dumps(
            {E._geo_key(TOWN, CC): {"latlng": TOWN_CENTRE, "cc": CC}}), encoding="utf-8")
        saved_seed, saved_cache = E.SEED_DIR, E.CACHE_DIR
        try:
            E.SEED_DIR = E.CACHE_DIR = w
            c = canon([{"id": 1, "city": TOWN, "country": CC},
                       {"id": 2, "city": TOWN, "country": CC}])
            upd: list = []
            E.geocode(c, [], upd)
            got = {(p["lat"], p["lng"]) for p in c["properties"]}
            ck(got == {(TOWN_CENTRE[0], TOWN_CENTRE[1])},
               "with no codes stated, both properties still share the town centre exactly as before")
            after = json.loads((w / "geocode_cache.json").read_text(encoding="utf-8"))
            ck(all(not E._key_code(k) for k in after),
               f"...and every key written is city-level ({sorted(after)})")
            locs = {u["source_locator"] for u in upd if u["field"] == "lat"}
            ck(locs == {f"seeded geocode cache '{TOWN}' (coordsApprox)"},
               f"...and the ledger locator is byte-identical to the legacy string ({locs})")
        finally:
            E.SEED_DIR, E.CACHE_DIR = saved_seed, saved_cache

    # the seed writer keeps the city key when a row carries no code
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        rows = [{"city": TOWN, "country": CC, "lat": 1.0, "lng": 2.0, "cc": CC},
                {"city": TOWN, "country": CC, "postcode": CODE_A, "lat": 3.0, "lng": 4.0}]
        (w / "in.json").write_text(json.dumps(rows), encoding="utf-8")
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "helpers" / "seed_geocode.py"),
                            str(w / "in.json"), "--cache-dir", str(w)],
                           capture_output=True, text=True)
        seeded = json.loads((w / "geocode_cache.json").read_text(encoding="utf-8"))
        ck(r.returncode == 0 and set(seeded) == {E._geo_key(TOWN, CC), ka},
           f"seed_geocode: a codeless row lands on the CITY key, a coded row on the locality "
           f"key ({sorted(seeded)})")
        ck("1 at locality level, 1 at city level" in (r.stdout or ""),
           "...and it says which level each row landed at")

    # =====================================================================================
    # 3. legacy entries, and the SHIPPED seed cache
    # =====================================================================================
    print("\nbackward compatibility on read:")
    ck(E._cache_lookup(legacy, "Velke Levare", "SK")[0] == [48.5032707, 17.0022088],
       "a legacy BARE-PAIR value under a city key still reads")
    ck(E._cache_lookup(legacy, "Velke Levare", "SK", "QX417ZP")[0] == [48.5032707, 17.0022088],
       "...and is still found by a record that DOES state a code (the coarse read fallback)")
    shipped_path = ROOT / "reference" / "geocode_cache.json"
    shipped = json.loads(shipped_path.read_text(encoding="utf-8-sig"))
    ck(isinstance(shipped, dict) and len(shipped) >= 10 and all(not E._key_code(k) for k in shipped),
       f"the shipped seed cache is city-keyed throughout ({len(shipped)} entries)")
    unresolved = []
    for k, v in shipped.items():
        city, _, country = k.partition("|")
        if E._cache_lookup(shipped, city, country)[0] != E._coords_cc(v)[0]:
            unresolved.append(k)
    ck(not unresolved, f"...and every one of its entries still resolves ({unresolved})")
    saved_seed, saved_cache = E.SEED_DIR, E.CACHE_DIR
    try:
        E.SEED_DIR = E.CACHE_DIR = ROOT / "reference"
        merged = E._load_cache(E.GEOCODE_CACHE)
        ck(len(merged) == len(shipped), f"_load_cache still loads it whole ({len(merged)})")
    finally:
        E.SEED_DIR, E.CACHE_DIR = saved_seed, saved_cache

    # =====================================================================================
    # 4. the coarse fallback is a READ, never a WRITE-BACK
    # =====================================================================================
    print("\nwhere the coarse fallback may NOT apply - the write-back:")
    city_only = {E._geo_key(TOWN, CC): {"latlng": TOWN_CENTRE, "cc": CC}}
    ck(E._cache_lookup_key(city_only, TOWN, CC, "QX417ZP") == E._geo_key(TOWN, CC),
       "a locality lookup with only a city entry present RESOLVES to the city key...")
    ck(E._key_code(E._cache_lookup_key(city_only, TOWN, CC, "QX417ZP")) == "",
       "...and says so, so the caller can never mistake it for a locality answer")
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        (w / "geocode_cache.json").write_text(json.dumps(city_only), encoding="utf-8")
        saved_seed, saved_cache = E.SEED_DIR, E.CACHE_DIR
        saved_pc = E._geocode_postcode
        # OFFLINE BY CHARTER. This section asks what the CACHE does with a town-level answer, and
        # it invents its postcodes, so it must never put one to a real geocoder. Since D9 the
        # geocode stage asks about a stated postcode BEFORE accepting a town centroid, so on a
        # machine with live network this reached Nominatim, got a truthful "no such place" for the
        # invented code, and wrote the locality negative memo that B02 licenses - turning a
        # deterministic unit check into a network-dependent one that passed or failed by machine.
        # Raising is the honest stub: it models the dead sandbox this eval has always assumed, and
        # it exercises the circuit breaker rather than pretending an answer came back.
        E._geocode_postcode = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
        try:
            E.SEED_DIR = E.CACHE_DIR = w
            c = canon([pa, pb])
            E.geocode(c, [], [])
            after = json.loads((w / "geocode_cache.json").read_text(encoding="utf-8"))
            ck(all(not E._key_code(k) for k in after),
               f"NO locality key is written back from a town-level answer ({sorted(after)})")
            ck(set(after) == set(city_only),
               "...the cache is untouched, so a better answer can still land on either locality")
        finally:
            E.SEED_DIR, E.CACHE_DIR = saved_seed, saved_cache
            E._geocode_postcode = saved_pc
    # the reason it must not: web_enrich treats a PRESENT key as settled and never re-asks
    wsrc = (ROOT / "helpers" / "web_enrich.py").read_text(encoding="utf-8")
    ck('if f"{city}|{country}".lower() in _gcache:' in wsrc
       and 'gkey = f"{city}|{country}".lower()' in wsrc,
       "web_enrich's settledness keys stay CITY-level, so a city-level negative memo still "
       "suppresses the request (the B02 exit-8 livelock)")
    ck('cache[f"{city}|{country}".lower()] = {"latlng": None, "cc": ""}' in src,
       "...and the live negative memo is still written about the city NAME, not a locality")
    # a locality NEGATIVE memo does not strand the property: it falls through to the town
    neg = dict(city_only); neg[ka] = {"latlng": None, "cc": ""}
    ck(E._cache_lookup(neg, TOWN, CC, "QX417ZP")[0] == TOWN_CENTRE,
       "a locality entry with NO coordinate falls through to the town centre, never strands")
    # the unknown-country scan matches on the code segment, in both directions
    scan = {f"{TOWN.lower()}|es|qx417zp": {"latlng": PIN_A, "cc": "ES"},
            f"{TOWN.lower()}|es": {"latlng": TOWN_CENTRE, "cc": "ES"}}
    ck(E._cache_lookup(scan, TOWN, "??", "QX417ZP")[0] == PIN_A,
       "the cross-country scan prefers a SAME-CODE locality entry")
    ck(E._cache_lookup(scan, TOWN, "??")[0] == TOWN_CENTRE,
       "...and a record with no code is never handed somebody else's locality pin")
    ck(E._cache_lookup(scan, TOWN, "??", "QX419TN")[0] == TOWN_CENTRE,
       "...nor is a record whose code does not match that entry")

    # =====================================================================================
    # 5 + 6. the region cross-check: the polygon wins, and only a REAL conflict is disclosed
    # =====================================================================================
    print("\nthe region bind, cross-checked against what the record states:")
    ds = E._regions_dataset()
    if not ds:
        print("  [FAIL] the bundled regions dataset did not load")
        return 1
    geo = E._regions_geo()
    ck(bool(geo) and E._region_for_point(CORBY_PIN[0], CORBY_PIN[1], geo) == "UKF25",
       "the fixture coordinates bind to UKF25 by point-in-polygon")

    def bound_with(label, **kw):
        p = dict({"id": 7, "city": "Corby", "region": label,
                  "lat": CORBY_PIN[0], "lng": CORBY_PIN[1]}, **kw)
        c = canon([p])
        g: list = []
        E.bind_region_codes(c, ds, g)
        return c["properties"][0].get("regionCode"), g

    code, g = bound_with("Greater London")
    ck(code == "UKF25" and len(g) == 1,
       "a GENUINE conflict (a label in another lineage) is disclosed, exactly once")
    ck("region conflict" in g[0] and "id=7" in g[0] and "Greater London" in g[0]
       and "UKI" in g[0] and "UKF25" in g[0] and "North Northamptonshire" in g[0],
       "...naming the property, the stated label, both codes and the bound area")
    ck("VERIFY THE PIN" in g[0] and "not the same one at two levels" in g[0],
       "...saying what to do and why it is not merely a level difference")
    ck("workforce profile shipped is UKF25's" in g[0],
       "...and naming the consequence: whose figures actually shipped")

    code, g = bound_with("East Midlands")
    ck(code == "UKF25" and not g,
       "a label at a COARSER LEVEL of the same lineage ('East Midlands' -> UKF, and UKF25 is "
       "inside UKF) is NOT disclosed")
    code, g = bound_with("North Northamptonshire")
    ck(code == "UKF25" and not g, "a label that resolves to the bound code itself is silent")
    code, g = bound_with("Northamptonshire")
    ck(code == "UKF25" and not g,
       "a label the bundled dataset cannot resolve at all is silent - a contradiction that "
       "cannot be demonstrated is not reported")
    code, g = bound_with("")
    ck(code == "UKF25" and not g, "a property that states no region is silent (a gap, not a clash)")
    code, g = bound_with("tbd")
    ck(code == "UKF25" and not g, "...and a sentinel is ABSENCE, not an administrative level")

    ck(E._region_conflict(ds, "Northamptonshire", "UKF25") is None
       and E._region_conflict(ds, "East Midlands", "UKF25") is None
       and (E._region_conflict(ds, "Greater London", "UKF25") or {}).get("nuts") == "UKI",
       "_region_conflict: unresolvable -> None, coarser lineage -> None, other lineage -> the profile")
    ck(E._region_conflict(ds, "Comunidad de Madrid", "ES300") is None
       and (E._region_conflict(ds, "Comunidad de Madrid", "ES424") or {}).get("nuts") == "ES30",
       "...and the lineage rule is not UK-specific: ES30 contains ES300 but not ES424")
    ck((E._region_conflict(ds, "Madrid", "ES424") or {}).get("nuts") == "ES300",
       "a NEIGHBOURING-area marketing label (a corridor name across a boundary) DOES fire - "
       "it is a different place, not a coarser name for the same one")
    ck("if not scode or not bound:" in src,
       "the unresolvable-label guard is stated EXPLICITLY, not left to startswith('') being "
       "true, so a future change to the lineage test cannot silently un-silence it")

    print("\nthe polygon stays authoritative, and silent for existing callers:")
    c = canon([{"id": 8, "city": "Corby", "region": "Greater London",
                "regionCode": "Greater London", "lat": CORBY_PIN[0], "lng": CORBY_PIN[1]}])
    E.bind_region_codes(c, ds)          # the EXISTING two-argument call
    ck(c["properties"][0]["regionCode"] == "UKF25",
       "a two-argument caller still binds the polygon's code and says nothing")
    # the label may live in regionCode (merge.py puts it there for a coordinate-less property)
    c = canon([{"id": 9, "city": "Corby", "regionCode": "Greater London",
                "lat": CORBY_PIN[0], "lng": CORBY_PIN[1]}])
    g = []
    E.bind_region_codes(c, ds, g)
    ck(c["properties"][0]["regionCode"] == "UKF25" and len(g) == 1 and "id=9" in g[0],
       "a label carried in regionCode is read BEFORE the bind overwrites it")
    c = canon([{"id": 10, "city": "Corby", "regionCode": "ES300",
                "lat": CORBY_PIN[0], "lng": CORBY_PIN[1]}])
    g = []
    E.bind_region_codes(c, ds, g)
    ck(c["properties"][0]["regionCode"] == "UKF25" and not g,
       "...but a regionCode that IS a dataset code is a previous BIND, not the record's own "
       "claim, and is not cross-checked against this one")

    # the disclosure must survive a second --regions pass over an already-harmonised canonical
    print("\nthe disclosure does not vanish on a re-run:")
    mixed = [{"id": 1, "city": "Corby", "region": "Greater London",
              "lat": CORBY_PIN[0], "lng": CORBY_PIN[1]},
             {"id": 2, "city": "Corby", "region": "East Midlands",
              "lat": 52.46850533, "lng": -0.737056454}]
    c = canon(mixed)
    g1: list = []
    E.bind_region_codes(c, ds, g1)
    nh = E.harmonise_regions(c, ds, g1, [])
    ck(len(g1) >= 1 and any("region conflict" in x for x in g1) and nh == 2,
       "pass 1: the conflict is disclosed and harmonisation then rewrites both labels")
    ck([p["region"] for p in c["properties"]] == ["North Northamptonshire"] * 2,
       "...so neither property still carries the label its source stated")
    g2: list = []
    E.bind_region_codes(c, ds, g2)
    conf2 = [x for x in g2 if "region conflict" in x]
    ck(len(conf2) == 1 and "Greater London" in conf2[0],
       "pass 2: the SAME conflict is still disclosed, read back from meta.regionHarmonised")
    ck(not any("id=2" in x for x in conf2),
       "...and the level-difference property is still silent on the second pass too")
    # a stale record must not resurrect a disclosure
    c["properties"][0]["region"] = "Kent"
    g3: list = []
    E.bind_region_codes(c, ds, g3)
    ck(not [x for x in g3 if "region conflict" in x],
       "a region edited since harmonisation is NOT re-read from the stale record")

    print("\nwiring:")
    i_branch = src.find("if args.regions:")
    i_bind = src.find("bind_region_codes(canonical", i_branch)
    ck(i_branch != -1 and i_bind != -1 and ", g)" in src[i_bind:i_bind + 90],
       "enrich passes the regions layer's own gap bucket to the bind, so the disclosure "
       "reaches the Gaps Report by the existing path")
    ck(src.find("_disclose_region_bind(p, ds, code, gaps, prior)")
       < src.find('p["regionCode"] = code\n                continue'),
       "the cross-check runs BEFORE regionCode is overwritten")

    if fails:
        print(f"\nREGION/LOCALITY CACHE TEST: FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nREGION/LOCALITY CACHE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
