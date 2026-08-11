#!/usr/bin/env python3
"""coord_provenance_test.py - a first-party pin always beats a geocode. (B60)

THE DEFECT, from a delivered client dashboard. Three of thirty options showed a marker in the
middle of a village - and one showed no marker at all - while their own brochure pages carried
the author's pin. Two pages printed it as DMS (48°29'51.0"N 17°01'39.7"E); the third carried a
'click for location' Google Maps hyperlink. The broker opened the dashboard and saw the village.

WHY EACH HALF WAS MISSED, because they are different bugs:
  * DMS - `backfill_link_coords` scanned page text for a DECIMAL pair only. The interpretation
    reader saw the DMS, and correctly refused to convert it: it is told lat/lng are NUMBERS and
    that emitting a value absent from the source is invention. Nobody owned the conversion, so an
    exact arithmetic transform (deg + min/60 + sec/3600) - the same class as acres x43,560, which
    the pipeline does happily - simply never happened.
  * SHORT LINK - the harvester DID pull the hyperlink off every page and ship it as `mapLink`.
    But `maps.app.goo.gl/...` carries no coordinates; it has to be followed. The skill's own
    docstring said "a short goo.gl link needs a network resolve" and nothing ever resolved it.

WHAT THIS PINS:
  1. DMS parses exactly, in both hemispheres and either axis order, including the line-splitting
     and the ", ” or '' seconds marks a PDF text layer inflicts;
  2. prose and a period-thousands area list can NEVER match as DMS (the honesty guard);
  3. a resolved link prefers the DESTINATION over the `@` viewport centre - on the live link the
     viewport sat ~190 m off the site, so taking `@` would have swapped one wrong pin for another;
  4. the gate BLOCKS a town-centre pin whose own page offers better, names the property and what
     it found, and stays SILENT for an honest geocode whose source genuinely offers nothing.
Offline - the resolver is exercised through parsing, never a live fetch.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import coords as CO  # noqa: E402

GATE = ROOT / "helpers" / "gate_runner.py"


def main() -> int:
    fails = []

    def ck(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    # ---------- 1. DMS, the exact strings from the live decks ----------
    a = CO.dms_from_text('48°29\'51.0"N 17\n°01\'39.7"E')   # split across lines
    ck(a is not None and abs(a[0] - 48.4975) < 1e-6 and abs(a[1] - 17.0276944) < 1e-6,
       "DMS split across lines by the PDF text layer still parses exactly")
    b = CO.dms_from_text('47°58\'23.0"N 17°42\'10.3"E')
    ck(b is not None and abs(b[0] - 47.9730556) < 1e-6 and abs(b[1] - 17.7028611) < 1e-6,
       "the second live pair parses exactly")
    ck(CO.dms_from_text('17°01\'39.7"E 48°29\'51.0"N') == a,
       "axis order comes from the HEMISPHERE letters, not position")
    s = CO.dms_from_text('33°52\'00.0"S 151°12\'00.0"E')
    ck(s is not None and s[0] < 0 and s[1] > 0, "southern latitude signs correctly")
    ck(CO.dms_from_text('48°29\'51.0"N 47°58\'23.0"N') is None,
       "two latitudes is not a pair - rejected, never guessed")

    # ---------- 2. the honesty guard: prose must never look like a coordinate ----------
    ck(CO.dms_from_text("a 48 m x 17 m unit over 12.500, 18.500 m2") is None,
       "an area list in a period-thousands locale can never match as DMS")
    ck(CO.dms_from_text("48 29 51 N 17 01 39 E") is None,
       "digits without degree/minute marks are not DMS - the punctuation is what makes it safe")
    got, _ = CO.coords_and_link_from_text('Coordinates 48°29\'51.0"N 17°01\'39.7"E')
    ck(got is not None and abs(got[0] - 48.4975) < 1e-6,
       "the shared text scan now reaches DMS, so every input path gets it")

    # ---------- 3. a resolved short link: destination beats viewport ----------
    place = ("https://www.google.com/maps/place/48%C2%B029'51.0%22N+17%C2%B001'39.7%22E"
             "/@48.4974905,17.0251251,1005m/data=!3m2!1e3!4b1")
    r = CO.coords_from_resolved(place)
    ck(r is not None and abs(r[1] - 17.0276944) < 1e-6,
       "a /maps/place/<DMS>/@<viewport> link takes the DMS PIN, not the @ viewport centre "
       "(which sat ~190 m off on the live link)")
    r2 = CO.coords_from_resolved("https://www.google.com/maps/search/48.213046,+17.253445?entry=tts")
    ck(r2 == (48.213046, 17.253445), "a /maps/search/ destination parses")
    ck(bool(CO.SHORT_MAPS.match("https://maps.app.goo.gl/NWWYPx3uv5n8gySS8")),
       "the shortener that caused this is recognised as needing a resolve")
    ck(CO.coords_from_url("https://maps.app.goo.gl/NWWYPx3uv5n8gySS8") is None,
       "...and still yields no coordinate WITHOUT following it - the gap this closes")

    # ---------- 4. the gate ----------
    def _canon(props):
        return {"meta": {"client": "Pin", "units": {"area": "sq m"},
                         "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                                  "lede": "", "footer_copyright": ""}},
                "pois": [], "regions": {},
                "properties": [dict({"country": "SK", "city": "Velke Levare",
                                     "developer": "D", "areaUnit": "sq m"}, **p) for p in props]}

    def _run(cp, work="", ledger=""):
        cmd = [sys.executable, str(GATE), "coord-provenance", str(cp)]
        if work:
            cmd += ["--work", work]
        if ledger:
            cmd += ["--ledger", ledger]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # the live shape: a town-centre pin and a no-pin property, both carrying the author's link
        bad = d / "bad.json"
        bad.write_text(json.dumps(_canon([
            dict(id=1, park="ReONE Velke Levare", lat=48.5032707, lng=17.0022088,
                 coordsApprox=True, mapLink="https://maps.app.goo.gl/1rTfnUjNjEYArRH87"),
            dict(id=4, park="Blueprint Triblavina",
                 mapLink="https://maps.app.goo.gl/NWWYPx3uv5n8gySS8"),
            dict(id=9, park="Honest Geocode", lat=47.5, lng=17.5, coordsApprox=True),
        ])), encoding="utf-8")
        rc, out = _run(bad)
        ck(rc == 1 and "STATUS: BLOCKED" in out,
           "a town-centre pin whose own source offers a first-party link BLOCKS")
        ck("id=1" in out and "id=4" in out, "both the approximate pin and the missing pin are named")
        ck("APPROXIMATE" in out and "NO pin at all" in out,
           "the two states are distinguished, so the broker knows which is which")
        ck("id=9" not in out,
           "an honest geocode - approximate, with nothing better in its source - passes SILENTLY")

        # coordinates sitting in the page text, with no link at all
        work = d / "w"
        (work / "vision").mkdir(parents=True)
        (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [
            {"source_file": "Deck.pdf", "pages": [
                {"page_no": 0, "locator": "page 1",
                 "text": 'Site\nCoordinates 48°29\'51.0"N 17°01\'39.7"E\nRent'}]}]}),
            encoding="utf-8")
        led = d / "l.csv"
        led.write_text("property_id,record_type,field,value,source_file,source_locator,"
                       "source_type,extractor,confidence,conflict_note,verified\n"
                       "1,property,park,ReONE,Deck.pdf,page 1,brochure,x,High,,\n",
                       encoding="utf-8")
        txt = d / "txt.json"
        txt.write_text(json.dumps(_canon([
            dict(id=1, park="ReONE", lat=48.5032707, lng=17.0022088, coordsApprox=True),
        ])), encoding="utf-8")
        rc2, out2 = _run(txt, str(work), str(led))
        ck(rc2 == 1 and "coordinates in its own page text" in out2,
           "coordinates printed on the page - with NO link - are found and block too")

        # nothing available anywhere -> silent
        rc3, out3 = _run(txt)
        ck(rc3 == 0,
           "without the manifest/ledger the gate cannot see the page and does not invent a "
           "finding - it degrades to silence, never to a false accusation")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
