#!/usr/bin/env python3
"""d9_postcode_locality_test.py - a stated postcode is geocoded, not the town; the answer
lives at LOCALITY level; and a locality answer displaces an approximate pin. (D9 + D10)

THE DEFECTS. On the measured run not one UK deck printed a coordinate, so every property was
geocoded from its CITY NAME to a town centroid. A site whose POSTAL town sits in the next
county was pinned 9 km across the county line and shipped that county's whole workforce
panel; another was pinned byte-identical to its city POI and printed "0 min / 0.0 km" (D9).
The operator then seeded locality coordinates and re-ran, and NOTHING changed: geocode()
only ever filled an EMPTY coordinate, so the seed was never read on a warm work dir (D10).

THE REPAIR THIS FILE ALSO PINS. The first D9 implementation persisted a negative memo under
the LOCALITY key whenever the postcode query "yielded nothing" and then treated any PRESENT
key as settled. Two consequences: a transport failure (the ordinary state of a Cowork
sandbox, and what a rate limit or an error envelope look like from the caller) would have
occupied every locality slot permanently, and even a genuine "no such place" could never be
re-asked by the live helper - the D9/D10 defect re-created. Parts 5 and 6 fail against that.

WHAT THIS FILE PINS, in order:
  1. a record stating a postcode is resolved from the POSTCODE, the pin lands under the
     LOCALITY key, the town key is untouched, and the ledger names the postcode;
  2. a record stating NO postcode behaves exactly as before: town centre, city keys only,
     the postcode geocoder never called;
  3. a locality-level answer already in the cache (a seed) DISPLACES a `coordsApprox: true`
     pin on a plain re-run, says so, and counts it;
  4. a locality-level answer does NOT displace a precise stated coordinate, and says why;
  5. NO locality key is created from a town-level answer or from a TRANSPORT FAILURE: the
     cache is byte-identical afterwards and the town pin is served; and `_geocode_postcode`
     itself raises for a non-2xx status and for a non-array body, so neither can ever be
     mistaken for "no such place";
  6. a genuine "no such place" IS memoised at locality level (so the web round does not
     re-emit it), but the memo does NOT block a live retry: the next pass asks again and a
     pin lands, for an unpinned property and for an approximate one alike, and a memo that is
     still "no" is not rewritten;
  7. the count of stated postcodes the pass could not ask travels in meta.enrichment for
     run.py's exit-8 decision.

EVERY POSTAL CODE IS INVENTED and nothing here is country-specific (the same discipline
region_locality_cache_test keeps). Offline: `_geocode_postcode`, `_geocode_one` and
`_reverse_cc` are stubbed, `time.sleep` is a no-op, and a live call is asserted never made.
Run: python evals/d9_postcode_locality_test.py"""
from __future__ import annotations
import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import enrich as E  # noqa: E402

TOWN, CC = "Cranleigh Vale", "GB"
CODE_A, CODE_B = "QX41 7ZP", "QX41 9TN"
NORM_A, NORM_B = "QX417ZP", "QX419TN"
TOWN_CENTRE = [52.4900000, -0.6900000]
PIN_A = [52.50304981, -0.650581854]
PIN_B = [52.46850533, -0.737056454]
STATED = [52.5100000, -0.6600000]  # a coordinate the SOURCE printed (coordsApprox absent)
NEGATIVE = {"latlng": None, "cc": ""}

CITY_KEY = E._geo_key(TOWN, CC)
KA = E._geo_key(TOWN, CC, NORM_A)
KB = E._geo_key(TOWN, CC, NORM_B)


def canon(props):
    return {"properties": copy.deepcopy(props), "meta": {}}


class Offline:
    """Every network-touching helper stubbed and every call recorded. `postcode` is a
    callable (code, cc) -> (latlng, cc) or raises, so one harness covers a pin, a genuine
    negative and a transport failure. `saves` counts `_save_cache` calls."""

    def __init__(self, postcode):
        self.postcode = postcode
        self.pc_calls: list = []
        self.city_calls: list = []
        self.saves = 0

    def __enter__(self):
        self.saved = (E._geocode_postcode, E._geocode_one, E._reverse_cc, E.time.sleep,
                      E._save_cache, E.SEED_DIR, E.CACHE_DIR)

        def _pc(requests, code, cc):
            self.pc_calls.append((code, cc))
            return self.postcode(code, cc)

        real_save = E._save_cache

        def _save(name, d):
            self.saves += 1
            real_save(name, d)

        E._geocode_postcode = _pc
        E._geocode_one = lambda *a, **k: self.city_calls.append(a) or (None, "")
        E._reverse_cc = lambda *a, **k: ""
        E.time.sleep = lambda *_a, **_k: None
        E._save_cache = _save
        return self

    def __exit__(self, *exc):
        (E._geocode_postcode, E._geocode_one, E._reverse_cc, E.time.sleep,
         E._save_cache, E.SEED_DIR, E.CACHE_DIR) = self.saved
        return False


def run(workdir: Path, cache: dict | None, props, postcode):
    """geocode() over a temp work dir. `cache` None = leave the work dir's file as it is (a
    second pass over the same dir). Returns (canonical, gaps, updates, printed, cache_after,
    n, harness)."""
    if cache is not None:
        (workdir / "geocode_cache.json").write_text(json.dumps(cache), encoding="utf-8")
    with Offline(postcode) as h:
        E.SEED_DIR = E.CACHE_DIR = workdir
        c = canon(props)
        gaps: list = []
        upd: list = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            n = E.geocode(c, gaps, upd)
    after = json.loads((workdir / "geocode_cache.json").read_text(encoding="utf-8"))
    return c, gaps, upd, buf.getvalue(), after, n, h


def _raise(*_a):
    raise ConnectionError("simulated dead sandbox network")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    pins = {NORM_A: PIN_A, NORM_B: PIN_B}
    pa = {"id": 1, "park": "Alpha Park", "city": TOWN, "country": CC, "postcode": CODE_A}
    pb = {"id": 2, "park": "Beta Park", "city": TOWN, "country": CC, "postcode": CODE_B}
    city_only = {CITY_KEY: {"latlng": TOWN_CENTRE, "cc": CC}}

    # =====================================================================================
    # 1. the POSTCODE is geocoded, and the answer lands at LOCALITY level
    # =====================================================================================
    print("1. a record stating a postcode is resolved from the postcode, not the town:")
    with tempfile.TemporaryDirectory() as td:
        c, gaps, upd, out, after, n, h = run(Path(td), city_only, [pa, pb],
                                             lambda code, cc: (pins[code], cc))
        got = [(p["lat"], p["lng"]) for p in c["properties"]]
        ck(got == [tuple(PIN_A), tuple(PIN_B)] and n == 2,
           f"both properties sit on their POSTCODE pin, not the town centre ({got})")
        ck(h.pc_calls == [(NORM_A, CC), (NORM_B, CC)],
           f"the geocoder was asked for each stated code, normalised, scoped to the country "
           f"({h.pc_calls})")
        ck(not h.city_calls, "...and the town NAME was never asked (postcode first, not as well)")
        ck(after.get(KA) == {"latlng": PIN_A, "cc": CC} and after.get(KB) == {"latlng": PIN_B, "cc": CC},
           "each answer is persisted under ITS locality key")
        ck(after.get(CITY_KEY) == city_only[CITY_KEY],
           "...and the town key is untouched (a postcode answer is not a town answer)")
        ck(all(p.get("coordsApprox") is True for p in c["properties"]),
           "both still flagged coordsApprox: a postcode is an area, not a building")
        locs = [u["source_locator"] for u in upd if u["field"] == "lat"]
        ck(len(locs) == 2 and NORM_A in locs[0] and NORM_B in locs[1] and locs[0] != locs[1],
           f"the ledger names each stated postcode, so two pins never share one trace row ({locs})")
        ck(not any("state a postcode" in g for g in gaps),
           "no D9 disclosure: every stated postcode resolved")
        ck(c["meta"]["enrichment"].get("postcodes_unasked") == 0,
           "meta.enrichment.postcodes_unasked is 0 when every code was asked")

    # =====================================================================================
    # 2. a record stating NO postcode behaves exactly as before
    # =====================================================================================
    print("\n2. a record stating no postcode is byte-identical to the pre-D9 path:")
    with tempfile.TemporaryDirectory() as td:
        plain = [{"id": 1, "city": TOWN, "country": CC}, {"id": 2, "city": TOWN, "country": CC}]
        c, gaps, upd, out, after, n, h = run(Path(td), city_only, plain,
                                             lambda code, cc: (PIN_A, cc))
        got = {(p["lat"], p["lng"]) for p in c["properties"]}
        ck(got == {tuple(TOWN_CENTRE)} and n == 2, f"both get the town centre ({got})")
        ck(not h.pc_calls and not h.city_calls, "no geocoder of either kind was called")
        ck(after == city_only, "the cache is untouched (city key only, unchanged)")
        ck({u["source_locator"] for u in upd if u["field"] == "lat"}
           == {f"seeded geocode cache '{TOWN}' (coordsApprox)"},
           "the ledger locator is the legacy string")
        ck(not gaps and "state a postcode" not in out, "no D9 disclosure and nothing printed about postcodes")

    # =====================================================================================
    # 3. a locality answer in the cache DISPLACES an approximate pin on a plain re-run (D10)
    # =====================================================================================
    print("\n3. a seeded locality coordinate displaces an approximate town pin:")
    with tempfile.TemporaryDirectory() as td:
        seeded = dict(city_only); seeded[KA] = {"latlng": PIN_A, "cc": CC}
        pinned = [dict(pa, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1], coordsApprox=True),
                  dict(pb, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1], coordsApprox=True)]
        c, gaps, upd, out, after, n, h = run(Path(td), seeded, pinned, _raise)  # offline
        p1, p2 = c["properties"]
        ck((p1["lat"], p1["lng"]) == tuple(PIN_A) and p1.get("coordsApprox") is True,
           "the property whose postcode is seeded now sits on the seeded pin (still coordsApprox)")
        ck(n == 1, f"the displacement is counted in the return value ({n})")
        line = next((l for l in out.splitlines() if "approximate town pin" in l), "")
        ck("id=1" in line and "Alpha Park" in line and NORM_A in line and "replaced by the locality-level" in line
           and "km away" in line,
           f"...and is said out loud, naming the property, the code and the distance: {line!r}")
        ck((p2["lat"], p2["lng"]) == tuple(TOWN_CENTRE),
           "the property whose postcode could NOT be asked (offline) keeps its town pin, byte for byte")
        ck(any("could not be asked" in g and "id=2" in g and NORM_B in g for g in gaps),
           "...and the Gaps Report says so, naming it")
        ck(any(u["field"] == "lat" and u["property_id"] == 1 and NORM_A in u["source_locator"]
               for u in upd),
           "the ledger carries the displaced coordinate with a locator naming the postcode")
        ck(KB not in after, "no locality key was created for the code that could not be asked")

    # =====================================================================================
    # 4. a precise STATED coordinate is never displaced
    # =====================================================================================
    print("\n4. a locality answer does not override a coordinate the source stated:")
    with tempfile.TemporaryDirectory() as td:
        seeded = dict(city_only); seeded[KA] = {"latlng": PIN_A, "cc": CC}
        precise = [dict(pa, lat=STATED[0], lng=STATED[1])]  # coordsApprox absent = stated
        c, gaps, upd, out, after, n, h = run(Path(td), seeded, precise,
                                             lambda code, cc: (PIN_B, cc))
        p1 = c["properties"][0]
        ck((p1["lat"], p1["lng"]) == tuple(STATED) and "coordsApprox" not in p1,
           "the stated coordinate is untouched and not re-flagged")
        ck(n == 0 and not h.pc_calls, "nothing displaced, nothing asked")
        ck("keeps its stated coordinate" in out and "id=1" in out and "repairs.json" in out,
           "...and a NOTE says why and names the correction channel")
        precise_false = [dict(pa, lat=STATED[0], lng=STATED[1], coordsApprox=False)]
        c2, *_rest = run(Path(td), seeded, precise_false, lambda code, cc: (PIN_B, cc))
        ck((c2["properties"][0]["lat"], c2["properties"][0]["lng"]) == tuple(STATED),
           "coordsApprox: false is treated the same as absent (stated)")

    # =====================================================================================
    # 5. FAILURE 1 regression: no locality key from a town-level answer or a transport failure
    # =====================================================================================
    print("\n5. a transport failure writes NOTHING at locality level:")
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        before = json.dumps(city_only, sort_keys=True)
        c, gaps, upd, out, after, n, h = run(w, city_only, [pa, pb], _raise)
        got = {(p["lat"], p["lng"]) for p in c["properties"]}
        ck(got == {tuple(TOWN_CENTRE)} and n == 2,
           f"both are served the town centre through the coarse READ ({got})")
        ck(json.dumps(after, sort_keys=True) == before,
           f"the cache is byte-identical: no locality key, no negative memo ({sorted(after)})")
        ck(all(not E._key_code(k) for k in after), "every key present is still city-level")
        ck(len(h.pc_calls) == 1, f"the circuit breaker stopped after the first failure ({len(h.pc_calls)} call(s))")
        ck("geocoder unreachable" in out and any("geocoder unreachable" in g for g in gaps),
           "the failure is said out loud, on stdout and in the gaps")
        ck(any("could not be asked" in g and "id=1" in g and "id=2" in g for g in gaps),
           "...and the D9 disclosure names both properties as WAITING, not as unknown codes")
        ck(c["meta"]["enrichment"].get("postcodes_unasked") == 2,
           "meta.enrichment.postcodes_unasked counts both, for run.py's exit-8 decision")

    print("\n   ...and `_geocode_postcode` itself cannot mistake a failure for an answer:")

    class _Resp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._body

    def _req(status, body):
        return SimpleNamespace(get=lambda *a, **k: _Resp(status, body))

    hit = [{"lat": "52.5", "lon": "-0.65", "address": {"country_code": "gb"}}]
    ck(E._geocode_postcode(_req(200, hit), NORM_A, CC) == ([52.5, -0.65], "GB"),
       "an HTTP 200 with a hit is a pin")
    ck(E._geocode_postcode(_req(200, []), NORM_A, CC) == (None, ""),
       "an HTTP 200 with an EMPTY array is the one genuine negative")
    for status, body, why in ((429, [], "a rate limit (HTTP 429) with an empty body"),
                              (403, {"error": "blocked"}, "a block (HTTP 403)"),
                              (200, {}, "an EMPTY error envelope (a dict, not an array)"),
                              (200, {"error": {"code": 400}}, "a Nominatim error envelope")):
        try:
            r = E._geocode_postcode(_req(status, body), NORM_A, CC)
            ck(False, f"{why} RAISES rather than answering (got {r!r})")
        except Exception:
            ck(True, f"{why} RAISES rather than answering")

    # =====================================================================================
    # 6. FAILURE 2 regression: a genuine negative is memoised but never blocks a live retry
    # =====================================================================================
    print("\n6. a genuine 'no such place' is remembered for the web round and re-asked live:")
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        # pass 1: the geocoder genuinely does not know the code
        c, gaps, upd, out, after, n, h = run(w, city_only, [pa], lambda code, cc: (None, ""))
        p1 = c["properties"][0]
        ck((p1["lat"], p1["lng"]) == tuple(TOWN_CENTRE) and n == 1,
           "pass 1: the property falls through to the town centre")
        ck(after.get(KA) == NEGATIVE, "...and the negative memo is written under the LOCALITY key")
        # wording follows the D9b correction: the line reports the OUTCOME (no coordinate) and
        # never asserts which sources were asked, because this bucket is built from cache state
        # and cannot know that.
        ck(any("resolved to no coordinate" in g and "id=1" in g and NORM_A in g for g in gaps),
           "...and the Gaps Report says the code resolved to no coordinate, naming the property")
        # the memo's ONE job: the web-enrichment round does not re-emit the request
        saved_dirs = E.SEED_DIR, E.CACHE_DIR
        try:
            E.SEED_DIR = E.CACHE_DIR = w
            import web_enrich as W
            wargs = SimpleNamespace(osrm=False, ors_key="", osrm_endpoint="", geocode=True, pois=False)
            spec = W._chain_spec(canon([dict(pa, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1],
                                             coordsApprox=True)]), wargs)
            ck(not any(e.get("geocode_url") for e in spec["properties"]),
               "web_enrich._chain_spec treats the memo as settled: no postcode request re-emitted (B02)")
            (w / "geocode_cache.json").write_text(json.dumps(city_only), encoding="utf-8")
            spec2 = W._chain_spec(canon([dict(pa, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1],
                                              coordsApprox=True)]), wargs)
            ck(any(e.get("geokey") == KA and "postalcode" in e.get("geocode_url", "")
                   for e in spec2["properties"]),
               "...whereas with NO memo it asks for the postcode under the locality key")
            (w / "geocode_cache.json").write_text(json.dumps(after), encoding="utf-8")
        finally:
            E.SEED_DIR, E.CACHE_DIR = saved_dirs
        # pass 2, same work dir, the geocoder now knows the code: an UNPINNED property
        c, gaps, upd, out, after2, n, h = run(w, None, [pa], lambda code, cc: (PIN_A, cc))
        p1 = c["properties"][0]
        ck(h.pc_calls == [(NORM_A, CC)], "pass 2: the memo did NOT stop the live re-ask")
        ck((p1["lat"], p1["lng"]) == tuple(PIN_A) and after2.get(KA) == {"latlng": PIN_A, "cc": CC},
           "...and the pin lands on the property and replaces the memo in the cache")
        # pass 3: an APPROXIMATE pin whose code carries a memo is re-asked and displaced too
        neg = dict(city_only); neg[KA] = NEGATIVE
        c, gaps, upd, out, after3, n, h = run(w, neg, [dict(pa, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1],
                                                            coordsApprox=True)],
                                              lambda code, cc: (PIN_A, cc))
        p1 = c["properties"][0]
        ck(h.pc_calls == [(NORM_A, CC)] and (p1["lat"], p1["lng"]) == tuple(PIN_A) and n == 1,
           "an approximate pin with a memo'd code is re-asked live and displaced")
        # a memo that is still "no" is not rewritten
        c, gaps, upd, out, after4, n, h = run(w, neg, [pa], lambda code, cc: (None, ""))
        ck(h.pc_calls == [(NORM_A, CC)] and after4.get(KA) == NEGATIVE and h.saves == 0,
           f"a re-asked memo that is still 'no' is not a cache write ({h.saves} save(s))")
        # and offline, the memo'd property is simply left alone
        c, gaps, upd, out, after5, n, h = run(w, neg, [dict(pa, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1],
                                                            coordsApprox=True)], _raise)
        ck((c["properties"][0]["lat"], c["properties"][0]["lng"]) == tuple(TOWN_CENTRE)
           and after5 == neg,
           "offline, a memo'd approximate pin stays and the cache stays")

    # =====================================================================================
    # 7. the redo list never asks an unknown country, and a seed overwrites a memo
    # =====================================================================================
    print("\n7. boundaries:")
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        unk = {E._geo_key(TOWN, "??"): {"latlng": TOWN_CENTRE, "cc": ""}}
        c, gaps, upd, out, after, n, h = run(w, unk, [dict(pa, country="??", lat=TOWN_CENTRE[0],
                                                           lng=TOWN_CENTRE[1], coordsApprox=True)],
                                             lambda code, cc: (PIN_A, cc))
        ck(not h.pc_calls, "an unknown country is never asked for a postcode (ambiguous without one)")
        neg = dict(city_only); neg[KA] = NEGATIVE
        (w / "geocode_cache.json").write_text(json.dumps(neg), encoding="utf-8")
        import subprocess
        rows = [{"city": TOWN, "country": CC, "postcode": CODE_A, "lat": PIN_A[0], "lng": PIN_A[1]}]
        (w / "in.json").write_text(json.dumps(rows), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "helpers" / "seed_geocode.py"),
                            str(w / "in.json"), "--cache-dir", str(w)], capture_output=True, text=True)
        seeded = json.loads((w / "geocode_cache.json").read_text(encoding="utf-8"))
        ck(r.returncode == 0 and seeded.get(KA) == {"latlng": PIN_A, "cc": CC},
           "seed_geocode.py overwrites a negative memo: the memo is never a claim on the slot")

    # the docstring promise matches the behaviour above
    sdoc = (ROOT / "helpers" / "seed_geocode.py").read_text(encoding="utf-8")
    ck("DISPLACES an existing pin flagged `coordsApprox: true`" in sdoc
       and "That re-entry is no longer needed" in sdoc and "--only" in sdoc,
       "seed_geocode.py's docstring states the plain re-run behaviour and names the one case "
       "that still needs anything")
    ck("IS THE ONE WAY A COORDINATE FINER THAN A TOWN ENTERS THIS PIPELINE" not in sdoc,
       "...and the stale pre-D10 promise is gone")

    print(f"\nD9/D10 POSTCODE LOCALITY TEST: {'PASS' if not fails else f'FAIL ({len(fails)})'}")
    for f in fails:
        print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
