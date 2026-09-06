#!/usr/bin/env python3
"""d9b_gb_postcode_register_test.py - a GB postcode Nominatim does not hold is resolved from
the ONS/Royal Mail national register, and nothing else about the geocode stage changes. (D9b)

WHAT THIS IS NOT. It is not a rescue of the D9 headline case. NN6 7ES - the DIRFT 450 code
whose mis-pinning motivated the whole D9 fix - RESOLVES through Nominatim today: measured,
`_geocode_postcode(requests, 'NN67ES', 'GB')` returns ([52.3478507, -1.1643983], 'GB'), 17 m
from the ONS coordinate for that code. It never reaches the fallback. Part 9 pins that reading
into the source so the comment cannot be rewritten into a rescue story later.

THE REAL, SMALLER GAP. Nominatim's structured `postalcode` search returns a genuine EMPTY
ARRAY for GB codes the national register holds perfectly well. Three measured misses at the
time of writing: WA5 5TN, BT1 2FF and BT28 3AX. Two of the three are Northern Ireland, which is
the shape of the gap; the third is a code retired in 2001. Each of those properties was falling
back to a TOWN-CENTRE pin, which is the same wrong-county / shared-pin failure class D9 exists
to prevent, just reached by a different route.

WHY THE REGISTER IS A FALLBACK AND NEVER THE PRIMARY, which is what most of this file pins.
`_geocode_postcode` carries a deliberate THREE-OUTCOME contract that a sibling repair was
written to establish: a non-empty array is a pin; an HTTP 200 with an EMPTY array is a real,
successful "no such place", the ONE outcome the caller may memoise as a negative; everything
else RAISES and trips the caller's circuit breaker. That contract is about NOMINATIM's response,
and the caller, `web_enrich`'s browser handoff and `cmd_ingest`'s ingest rule all reason about
it. So the register is asked ONLY in the second branch, where Nominatim has honestly said "no
such place", and it can only ever upgrade that negative into a pin. It is never asked behind a
RAISE, because a raise means we do not know whether the code exists, and asking somebody else
would turn an unknown into a claim.

AND IT CANNOT INTRODUCE A NEW WAY FOR THE STAGE TO FAIL. The value being enriched is already a
valid, complete answer. So every register failure - unreachable, 5xx, non-JSON, a moved shape,
and the measured HTTP 200 that carries `"latitude": null` for a code outside the ONS grid
(Guernsey GY1 1WR, Jersey JE2 4UH, both `quality: 9`) - must land on exactly the (None, "") the
caller would have got before the fallback existed. Parts 5 to 7 fail against anything else.

WHAT THIS FILE PINS, in order:
  1. the three-outcome contract is byte-for-byte intact with the fallback in place: a pin, the
     one genuine negative, and a RAISE for a non-2xx status or a non-array body - and the
     register is never asked behind a raise;
  2. a Nominatim PIN wins and the register is never called at all;
  3. a Nominatim negative plus a LIVE register hit is a pin, from the right endpoint, with the
     right provenance;
  4. ...and a TERMINATED code is a pin too, reached by the documented 404-then-terminated
     order, and its provenance SAYS the code is retired;
  5. a register MISS (404 on both endpoints) leaves the negative exactly as it was;
  6. a register EXCEPTION leaves the negative exactly as it was and does not propagate;
  7. an HTTP 200 that is not a coordinate is not a claim, and neither is a non-postcode string
     that would otherwise have been pasted into a URL path;
  8. a NON-GB record never calls the register, so no other market pays a wasted round trip;
  9. end to end through `geocode()`: the Source Ledger names the register that answered and the
     retirement, a Nominatim pin in the same pass still credits Nominatim, the provenance note
     cannot leak between properties, and every pin is still `coordsApprox: true`.

FULLY OFFLINE. `requests` is a fake object that records every URL and never opens a socket;
`_geocode_postcode` and `_geocode_one` are stubbed wholesale for the `geocode()` pass, the way
every existing geocode eval stubs them; `time.sleep` is a no-op and is asserted never to be
called by the register leg. EVERY POSTAL CODE BELOW IS EITHER ONE OF THE MEASURED REAL MISSES
(quoted so the eval documents the actual gap) OR INVENTED.
Run: python evals/d9b_gb_postcode_register_test.py"""
from __future__ import annotations
import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import enrich as E  # noqa: E402

NOM = "https://nominatim.openstreetmap.org/search"
LIVE = "https://api.postcodes.io/postcodes/"
TERM = "https://api.postcodes.io/terminated_postcodes/"

# The three MEASURED Nominatim misses, and the register's measured answers for them. Quoted
# rather than invented, because the point of this file is the real coverage gap - an invented
# code could not show that two of the three are Northern Ireland.
CODE_LIVE, PIN_LIVE = "BT12FF", [54.601212, -5.927817]      # Belfast, live in the register
CODE_TERM, PIN_TERM = "WA55TN", [53.414873, -2.611994]      # Warrington, retired 2001-01
CODE_NONE = "QX417ZP"                                        # invented: nobody holds it
CODE_NOM = "QX419TN"                                         # invented: Nominatim answers it
PIN_NOM = [52.50304981, -0.650581854]

# The measured register bodies, trimmed to the fields the reader touches plus enough context to
# show the shape. Latitude and longitude are top-level floats on `result` in BOTH shapes.
BODY_LIVE = {"status": 200, "result": {"postcode": "BT1 2FF", "quality": 1,
                                       "country": "Northern Ireland",
                                       "latitude": PIN_LIVE[0], "longitude": PIN_LIVE[1]}}
BODY_TERM = {"status": 200, "result": {"postcode": "WA5 5TN", "year_terminated": 2001,
                                       "month_terminated": 1,
                                       "latitude": PIN_TERM[0], "longitude": PIN_TERM[1]}}
BODY_404 = {"status": 404, "error": "Postcode not found"}
# The Channel Islands case: HTTP 200, `quality: 9`, and NO coordinate. Measured on GY1 1WR.
BODY_NULL = {"status": 200, "result": {"postcode": "GY1 1WR", "quality": 9,
                                       "latitude": None, "longitude": None}}

TOWN, CC = "Cranleigh Vale", "GB"
TOWN_CENTRE = [52.4900000, -0.6900000]
CITY_KEY = E._geo_key(TOWN, CC)


class Resp:
    """The minimum of a `requests` response this module touches: a status code, a
    `raise_for_status` that raises above 400 (the Nominatim leg's contract), and `.json()`."""

    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Req:
    """A fake `requests` module that records every URL and never opens a socket.

    `nominatim` is (status, body) or an Exception instance to raise from `.get`. `register` maps
    a URL PREFIX to (status, body), to an Exception to raise, or is absent - and an absent
    prefix is a hard failure of the test rather than a quiet default, because a silent default
    is how a test stops noticing that the wrong endpoint was called."""

    def __init__(self, nominatim, register=None):
        self.nominatim, self.register = nominatim, dict(register or {})
        self.urls: list = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        if url == NOM:
            if isinstance(self.nominatim, BaseException):
                raise self.nominatim
            return Resp(*self.nominatim)
        for prefix, out in self.register.items():
            if url.startswith(prefix):
                if isinstance(out, BaseException):
                    raise out
                return Resp(*out)
        raise AssertionError(f"the code asked an endpoint this test did not stub: {url}")

    # the register legs must never be charged a courtesy sleep of their own - see part 3
    def register_urls(self):
        return [u for u in self.urls if u.startswith("https://api.postcodes.io/")]


def nom_hit(pin, cc="gb"):
    return (200, [{"lat": str(pin[0]), "lon": str(pin[1]), "address": {"country_code": cc}}])


NOM_NEGATIVE = (200, [])


def canon(props):
    return {"properties": copy.deepcopy(props), "meta": {}}


class Offline:
    """`geocode()` with every network-touching helper stubbed. `postcode` is a callable
    (code, cc) -> (latlng, cc) that may ALSO write the register provenance note exactly as the
    real `_geocode_postcode` does, which is how a stubbed-wholesale lookup still exercises the
    ledger wiring. `saves` counts `_save_cache` calls."""

    def __init__(self, postcode):
        self.postcode = postcode
        self.pc_calls: list = []
        self.city_calls: list = []
        self.sleeps = 0

    def __enter__(self):
        self.saved = (E._geocode_postcode, E._geocode_one, E._reverse_cc, E.time.sleep,
                      E.SEED_DIR, E.CACHE_DIR)

        def _pc(requests, code, cc):
            self.pc_calls.append((code, cc))
            return self.postcode(code, cc)

        def _sleep(*_a, **_k):
            self.sleeps += 1

        E._geocode_postcode = _pc
        E._geocode_one = lambda *a, **k: self.city_calls.append(a) or (None, "")
        E._reverse_cc = lambda *a, **k: ""
        E.time.sleep = _sleep
        return self

    def __exit__(self, *exc):
        (E._geocode_postcode, E._geocode_one, E._reverse_cc, E.time.sleep,
         E.SEED_DIR, E.CACHE_DIR) = self.saved
        return False


def run(workdir: Path, cache: dict, props, postcode):
    """geocode() over a temp work dir -> (canonical, gaps, updates, printed, cache_after, n, h)."""
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


def answers(code, cc, kind, pin):
    """A stubbed `_geocode_postcode` outcome that ALSO leaves the provenance note the real one
    leaves, so `_postcode_src` reads the same thing it would read on a live run. `kind` None is
    a plain Nominatim pin, which writes no note at all."""
    if kind:
        E._REGISTER_PROVENANCE[E._register_key(code, cc)] = kind
    return pin, "GB"


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    def clear():
        E._REGISTER_PROVENANCE.clear()

    # =====================================================================================
    # 1. the three-outcome contract is intact, and the register is never asked behind a raise
    # =====================================================================================
    print("1. the THREE-OUTCOME contract survives the fallback, byte for byte:")
    clear()
    r = Req(nom_hit(PIN_NOM))
    ck(E._geocode_postcode(r, CODE_NOM, CC) == (PIN_NOM, "GB"),
       "an HTTP 200 with a hit is still a pin")
    ck(r.register_urls() == [], "...and a pin never asks the register (fallback, not primary)")

    for status, body, why in ((429, [], "a rate limit (HTTP 429)"),
                              (403, {"error": "blocked"}, "a block (HTTP 403)"),
                              (500, [], "a server error (HTTP 500)"),
                              (200, {}, "an EMPTY error envelope (a dict, not an array)"),
                              (200, {"error": {"code": 400}}, "a Nominatim error envelope")):
        clear()
        r = Req((status, body), {LIVE: (200, BODY_LIVE), TERM: (200, BODY_TERM)})
        try:
            got = E._geocode_postcode(r, CODE_LIVE, CC)
            ck(False, f"{why} RAISES rather than answering (got {got!r})")
        except AssertionError:
            raise
        except Exception:
            ck(True, f"{why} RAISES rather than answering")
        ck(r.register_urls() == [],
           f"...and {why} never reaches the register: not knowing is not a licence to ask "
           f"somebody else")
        ck(not E._REGISTER_PROVENANCE, "...and writes no provenance note")

    # =====================================================================================
    # 2. a Nominatim negative plus a LIVE register hit is a pin, with the right provenance
    # =====================================================================================
    print("\n2. a GB code Nominatim does not hold is resolved from the LIVE register:")
    clear()
    r = Req(NOM_NEGATIVE, {LIVE: (200, BODY_LIVE)})
    got = E._geocode_postcode(r, CODE_LIVE, CC)
    ck(got == (PIN_LIVE, "GB"),
       f"the negative is upgraded to the register's pin ({got})")
    ck(r.urls == [NOM, LIVE + CODE_LIVE],
       f"Nominatim FIRST, then the register - one round trip each, in that order ({r.urls})")
    ck(E._postcode_src(CODE_LIVE, CC) == "postcode-register-live",
       "the provenance note says the LIVE register answered")
    ck(not E._REGISTER_PROVENANCE,
       "...and reading it CONSUMES it, so it cannot be inherited by the next property")
    sf, st, loc = E._coord_locator("postcode-register-live", TOWN, CODE_LIVE)
    ck(sf == E._REGISTER_FILE and st == "web" and "national postcode register" in loc
       and CODE_LIVE in loc and "coordsApprox" in loc and "RETIRED" not in loc,
       f"the ledger names the register, the code, and does NOT call a live code retired ({loc})")

    # =====================================================================================
    # 3. a TERMINATED code: 404 on live, then the terminated register, and the ledger says so
    # =====================================================================================
    print("\n3. a RETIRED code is real ONS data, and the ledger says it is retired:")
    clear()
    r = Req(NOM_NEGATIVE, {LIVE: (404, BODY_404), TERM: (200, BODY_TERM)})
    got = E._geocode_postcode(r, CODE_TERM, CC)
    ck(got == (PIN_TERM, "GB"), f"a code retired in 2001 still yields its ONS pin ({got})")
    ck(r.urls == [NOM, LIVE + CODE_TERM, TERM + CODE_TERM],
       f"the documented order: live register, then - only on a 404 - the terminated one ({r.urls})")
    ck(E._postcode_src(CODE_TERM, CC) == "postcode-register-terminated",
       "the provenance note distinguishes the TERMINATED register from the live one")
    _, _, loc = E._coord_locator("postcode-register-terminated", TOWN, CODE_TERM)
    ck("RETIRED" in loc and "frozen at its termination" in loc and "coordsApprox" in loc,
       f"...and the ledger states the retirement rather than passing it off as current ({loc})")
    ck(loc != E._coord_locator("postcode-register-live", TOWN, CODE_TERM)[2],
       "a retired answer and a live answer never share one trace row")

    # the register legs charge no courtesy sleep of their own: the 1.1 s in `_postcode_first`
    # is Nominatim's usage policy, and these calls sit inside the same iteration before it.
    clear()
    saved_sleep, sleeps = E.time.sleep, []
    try:
        E.time.sleep = lambda *a, **k: sleeps.append(a)
        E._geocode_postcode(Req(NOM_NEGATIVE, {LIVE: (404, BODY_404), TERM: (200, BODY_TERM)}),
                            CODE_TERM, CC)
    finally:
        E.time.sleep = saved_sleep
    ck(sleeps == [], "the register adds NO sleep: it is a different host with no usage policy")

    # =====================================================================================
    # 4. a register MISS leaves the negative exactly as it was
    # =====================================================================================
    print("\n4. a code nobody holds is still the one genuine negative:")
    clear()
    r = Req(NOM_NEGATIVE, {LIVE: (404, BODY_404), TERM: (404, BODY_404)})
    ck(E._geocode_postcode(r, CODE_NONE, CC) == (None, ""),
       "404 on both register endpoints returns the UNCHANGED Nominatim negative")
    ck(r.urls == [NOM, LIVE + CODE_NONE, TERM + CODE_NONE], f"both were asked ({r.urls})")
    ck(not E._REGISTER_PROVENANCE, "no provenance note is written for a miss")

    # =====================================================================================
    # 5. a register EXCEPTION leaves the negative as it was and does not propagate
    # =====================================================================================
    print("\n5. a register that is down can never fail the stage:")
    for label, stub in (
            ("the connection dies", {LIVE: ConnectionError("simulated dead network")}),
            ("it 500s", {LIVE: (500, {"status": 500})}),
            ("the terminated leg dies after a 404", {LIVE: (404, BODY_404),
                                                     TERM: TimeoutError("simulated timeout")}),
            ("the body is not JSON", {LIVE: (200, ValueError("not json"))}),
            ("the shape moved (no 'result')", {LIVE: (200, {"status": 200, "data": {}})}),
            ("'result' is a list, not an object", {LIVE: (200, {"status": 200, "result": []})}),
            ("latitude is a string that is not a number",
             {LIVE: (200, {"status": 200, "result": {"latitude": "n/a", "longitude": "n/a"}})}),
            ("the coordinate is out of range",
             {LIVE: (200, {"status": 200, "result": {"latitude": 999.0, "longitude": 0.0}})})):
        clear()
        try:
            got = E._geocode_postcode(Req(NOM_NEGATIVE, stub), CODE_LIVE, CC)
            ck(got == (None, ""),
               f"{label}: the caller gets the unchanged negative, nothing propagates ({got})")
        except AssertionError:
            raise
        except Exception as ex:
            ck(False, f"{label}: raised {type(ex).__name__} into the caller - it must not")
        ck(not E._REGISTER_PROVENANCE,
           f"...and {label} writes no provenance note (a failure is never a claim)")

    # =====================================================================================
    # 6. an HTTP 200 is not automatically a coordinate, and a non-postcode is never in a URL
    # =====================================================================================
    print("\n6. a 200 that carries no coordinate is not an answer:")
    clear()
    r = Req(NOM_NEGATIVE, {LIVE: (200, BODY_NULL)})
    got = E._geocode_postcode(r, "GY11WR", CC)
    ck(got == (None, ""),
       f"an ONS-grid exclusion (200, quality 9, latitude null) is a miss, not a null pin ({got})")
    ck(not E._REGISTER_PROVENANCE, "...and writes no provenance note")

    for junk, why in (("SEE/BROCHURE", "a slash would walk the URL to another endpoint"),
                      ("TBD", "too short to be any GB postcode"),
                      ("N-A", "a sentinel that survived as a hyphenated string"),
                      ("WA5 5TN?X=1", "a query string smuggled into the path")):
        clear()
        r = Req(NOM_NEGATIVE, {LIVE: (200, BODY_LIVE), TERM: (200, BODY_TERM)})
        got = E._geocode_postcode(r, junk, CC)
        ck(got == (None, "") and r.register_urls() == [],
           f"'{junk}' is never pasted into a URL path: {why}")

    # =====================================================================================
    # 7. a NON-GB record never calls the register
    # =====================================================================================
    print("\n7. the register is GB only - no other market pays a wasted round trip:")
    for cc in ("NL", "DE", "ES", "IE", "US", "", "??"):
        clear()
        r = Req(NOM_NEGATIVE, {LIVE: (200, BODY_LIVE), TERM: (200, BODY_TERM)})
        got = E._geocode_postcode(r, CODE_LIVE, cc)
        ck(got == (None, "") and r.urls == [NOM],
           f"country '{cc}': the negative is returned with no register call at all")
    ck(E._is_gb("gb") == "GB" and E._is_gb("GB") == "GB" and E._is_gb(" uk ") == "GB",
       "the gate is case- and whitespace-insensitive, and accepts the 'UK' alias "
       "(normalize.country_iso maps it to GB upstream, and Nominatim's countrycodes=uk "
       "matches nothing - so that record is exactly the one the register rescues)")
    ck(not E._is_gb("GBR") and not E._is_gb(None) and not E._is_gb("G"),
       "...and nothing else opens the gate")
    # The provenance note is filed under the SPACELESS code the register was asked with, so a
    # caller that ever passed a spaced code could not silently file the note under one key and
    # read it back under another - which would not crash, it would credit Nominatim for a code
    # Nominatim does not hold.
    ck(E._register_key("WA5 5TN", "gb") == E._register_key("wa55tn".upper(), "GB")
       == E._register_key(" WA55TN ", "GB"),
       "the provenance key collapses spacing and case, so writer and reader cannot drift")

    # =====================================================================================
    # 8. end to end through geocode(): the Source Ledger names the register that answered
    # =====================================================================================
    print("\n8. through geocode(), the ledger names the register and the retirement:")
    city_only = {CITY_KEY: {"latlng": TOWN_CENTRE, "cc": CC}}
    pl = {"id": 1, "park": "Belfast Gate", "city": TOWN, "country": CC, "postcode": "BT1 2FF"}
    pt = {"id": 2, "park": "Omega South", "city": TOWN, "country": CC, "postcode": "WA5 5TN"}
    pn = {"id": 3, "park": "Nominatim Park", "city": TOWN, "country": CC, "postcode": "QX41 9TN"}
    pins = {CODE_LIVE: ("live", PIN_LIVE), CODE_TERM: ("terminated", PIN_TERM),
            CODE_NOM: (None, PIN_NOM)}

    clear()
    with tempfile.TemporaryDirectory() as td:
        c, gaps, upd, out, after, n, h = run(
            Path(td), city_only, [pl, pt, pn],
            lambda code, cc: answers(code, cc, *pins[code]))
        got = [(p["lat"], p["lng"]) for p in c["properties"]]
        ck(got == [tuple(PIN_LIVE), tuple(PIN_TERM), tuple(PIN_NOM)] and n == 3,
           f"all three sit on their POSTCODE pin, not the town centre ({got})")
        ck(all(p.get("coordsApprox") is True for p in c["properties"]),
           "every one is still coordsApprox: a postcode unit is an area, not a building, and "
           "the register's ONS centroid is no more the building than Nominatim's is")
        locs = [u["source_locator"] for u in upd if u["field"] == "lat"]
        files = [u["source_file"] for u in upd if u["field"] == "lat"]
        ck(len(locs) == 3 and len(set(locs)) == 3,
           f"three pins, three distinct trace rows ({len(set(locs))} distinct)")
        ck(files[0] == E._REGISTER_FILE and files[1] == E._REGISTER_FILE
           and files[2] == "Nominatim (OSM geocoder)",
           f"the register-answered rows name the register; the Nominatim row still names "
           f"Nominatim ({files})")
        ck("RETIRED" in locs[1] and "RETIRED" not in locs[0] and "RETIRED" not in locs[2],
           "only the retired code's row says the code is retired")
        ck("national postcode register" not in locs[2],
           "a Nominatim answer never borrows the register's provenance (no note leak)")
        ck(not E._REGISTER_PROVENANCE,
           "the pass leaves no provenance note behind for the next stage to misread")
        ck(not h.city_calls, "the town NAME was never asked (postcode first, not as well)")
        ck(after.get(E._geo_key(TOWN, CC, CODE_LIVE)) == {"latlng": PIN_LIVE, "cc": "GB"}
           and after.get(E._geo_key(TOWN, CC, CODE_TERM)) == {"latlng": PIN_TERM, "cc": "GB"},
           "each register answer is persisted under ITS locality key, in the UNCHANGED entry "
           "shape {'latlng','cc'} - the register did not widen a shared cache contract")
        ck(after.get(CITY_KEY) == city_only[CITY_KEY],
           "...and the town key is untouched (a postcode answer is not a town answer)")
        ck(not any("does not recognise" in g for g in gaps),
           "no unresolved-postcode disclosure: every stated code resolved")

    # A register answer never invents a country. The gate already required GB, so the country
    # is known before the lookup and the country-fill branch cannot fire for it - this pins that
    # the register can only ever contribute a COORDINATE, never a country the record did not
    # already state.
    clear()
    with tempfile.TemporaryDirectory() as td:
        c, gaps, upd, out, after, n, h = run(
            Path(td), city_only, [dict(pl, id=4)],
            lambda code, cc: answers(code, cc, "live", PIN_LIVE))
        ck(not [u for u in upd if u["field"] == "country"],
           "a register answer writes no country row: the GB gate means the country was already "
           "stated, so the register contributes a coordinate and nothing else")
        ck(c["properties"][0]["country"] == "GB", "...and the stated country is untouched")

    # =====================================================================================
    # THE D10 DISPLACEMENT PATH, which is where a wrong register provenance would actually land
    # in a client Source Ledger. PASS A fills an EMPTY coordinate; this is the other call site,
    # where a property already carries an APPROXIMATE town pin and a locality-level answer
    # displaces it. It was verified by hand when D9b landed and left unpinned, which is how the
    # ledger half of a fix rots: the coordinate is right, the row saying where it came from is
    # not, and nothing fails. A register answer displacing a town pin must credit the register.
    clear()
    with tempfile.TemporaryDirectory() as td:
        pinned = dict(pl, id=7, lat=TOWN_CENTRE[0], lng=TOWN_CENTRE[1], coordsApprox=True)
        c, gaps, upd, out, after, n, h = run(Path(td), city_only, [pinned],
                                             lambda code, cc: answers(code, cc, "live", PIN_LIVE))
        got = c["properties"][0]
        ck([got["lat"], got["lng"]] == PIN_LIVE,
           f"a register answer DISPLACES an approximate town pin ({got['lat']}, {got['lng']})")
        ck(got.get("coordsApprox") is True,
           "...and the displaced pin is still coordsApprox: a postcode unit is an area")
        rows = [u for u in upd if u["field"] in ("lat", "lng")]
        ck(bool(rows) and all(u["source_file"] == E._REGISTER_FILE for u in rows),
           f"...and the ledger credits the REGISTER for it, not OSM ({[u['source_file'] for u in rows]})")
        ck(bool(rows) and all("national postcode register" in u["source_locator"] for u in rows),
           "...and the locator names the register in words a broker can read")

    # THE DISCLOSURE MUST NOT CLAIM WHICH SOURCES WERE ASKED. This check used to assert the
    # opposite: that the gap line said the register "was asked and missed too". That sentence was
    # false whenever the negative memo came from the web-enrichment round, which has no register
    # leg, and it told the operator to hand-seed a code a networked re-run would have resolved.
    # The eval was certifying the defect, so it is inverted here: the line may describe the
    # OUTCOME and may name the register as a route still worth trying, but it may never assert
    # that the register was consulted.
    clear()
    with tempfile.TemporaryDirectory() as td:
        c, gaps, upd, out, after, n, h = run(Path(td), city_only,
                                             [dict(pl, id=5, postcode="QX41 7ZP")],
                                             lambda code, cc: (None, ""))
        unres = [g for g in gaps if "resolved to no coordinate" in g]
        ck(len(unres) == 1 and "id=5" in unres[0],
           "an unresolved code is disclosed as a gap, naming the property")
        ck(all("nor does the national postcode register" not in g for g in gaps),
           "...and the line never claims the national register was asked and missed")
        ck("re-run WITH network may" in unres[0] and "helper-side" in unres[0],
           "...and it names the networked re-run as a route still open, not an exhausted one")
        ck(after.get(E._geo_key(TOWN, CC, CODE_NONE)) == {"latlng": None, "cc": ""},
           "...and the genuine negative is still memoised, exactly as before (B02)")

    # =====================================================================================
    # 9. the source says what it must, so the reasoning cannot be rewritten out
    # =====================================================================================
    print("\n9. the source states the design and the measured facts:")
    src = (ROOT / "helpers" / "enrich.py").read_text(encoding="utf-8")
    ck("NN6 7ES" in src and "resolves through the Nominatim leg" in src,
       "the code records the measured fact that NN6 7ES resolves via Nominatim, so this is "
       "never rewritten as the D9 rescue it is not")
    ck("COVERAGE improvement, not the D9 rescue" in src or "COVERAGE fix, not" in src,
       "...and says in as many words that it is a coverage improvement")
    ck("NOT THE PRIMARY" in src and "three-outcome contract" in src,
       "the source explains WHY the register is a fallback rather than the primary lookup")
    ck("WA5 5TN" in src and "BT1 2FF" in src and "BT28 3AX" in src,
       "the three measured misses are named, so a later reader can re-measure the gap")
    ck("quality: 9" in src and "latitude\": null" in src,
       "the measured 200-with-no-coordinate case is documented where the guard lives")
    # The house rule is absolute, so the check must name the characters by CODE POINT: writing
    # the literals here would put the very characters this asserts about into the file, and the
    # assertion about this file would then fail on itself.
    dashes = (chr(0x2014), chr(0x2013))   # em dash, en dash
    ck(not any(d in src for d in dashes), "no em dash or en dash in enrich.py")
    mine = Path(__file__).read_text(encoding="utf-8")
    ck(not any(d in mine for d in dashes), "...nor in this eval")

    print(f"\nD9b GB POSTCODE REGISTER TEST: {'PASS' if not fails else f'FAIL ({len(fails)})'}")
    for f in fails:
        print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
