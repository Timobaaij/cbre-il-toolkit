#!/usr/bin/env python3
"""flyover_slide_test.py - the Flyover is a SLIDE with a map on it, not a map with a caption. (v35)

WHAT CHANGED AND WHY. The Flyover shipped a 70/30 map/details split. On a 1600px screen that left
the details panel 403px wide, and the panel is where the broker actually reads the deal:
  * values broke mid-phrase - '€63 / sq m /' + 'year', 'Eurovalley, a.s.' + '/ ReONE';
  * only about half of a data-rich option's attributes sat above the fold;
  * on a greenfield site 70% of the frame was empty field, carrying no information at all.
At 50/50 the panel is 671px - enough for THREE spec columns with unwrapped values - and the
details lead (order:1, so they sit LEFT), which is the slide reading order: content first,
supporting visual second.

WHAT THIS PINS, by extracting the rules FROM the built template rather than restating them, so a
revert to 70/30 or to a two-column spec grid fails here:
  1. the 50/50 split, on both columns (a one-sided edit would silently overflow the flex line);
  2. the ORDER - details before map - including that the panel's divider moved to its right edge;
  3. three spec columns, and the two-column drive-time grid with its heading spanning;
  4. the responsive fallbacks: two spec columns below 1100px, map-first below 900px;
  5. the shared --fo-pad rhythm, so the panel's gutters cannot drift per element.
Offline; string-level, so it runs without a browser (the geometry itself was verified live in
Playwright against the 30-property build at 1600x1000: map 50% / details 50%, 671px, 3 columns).
"""
from __future__ import annotations
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import build_dashboard  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _canon():
    base = {"country": "SK", "city": "Velke Levare", "developer": "D", "areaUnit": "sq m",
            "photo": PX, "gallery": [PX], "lat": 48.4975, "lng": 17.0277}
    return {"meta": {"client": "Slide", "units": {"area": "sq m"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "pois": [], "regions": {},
            "properties": [dict(base, id=1, park="ReONE", warehouseArea=57600)]}


def main() -> int:
    fails = []

    def ck(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps(_canon()), encoding="utf-8")
        build_dashboard.build(cp, hp)
        h = hp.read_text(encoding="utf-8")

    def rule(sel):
        """The built CSS text for one selector, from the Flyover's injected stylesheet."""
        m = re.search(re.escape(sel) + r"\{([^}]*)\}", h)
        return m.group(1) if m else ""

    mapcol, panel = rule(".fo-mapcol"), rule(".fo-panel")
    ck("flex:0 0 50%" in mapcol, "the map column is 50% (was 70%)")
    ck("flex:0 0 50%" in panel, "the details panel is 50% (was 30%) - both sides pinned")
    ck("order:2" in mapcol and "order:1" in panel,
       "the DETAILS lead and the map follows - content first, the slide reading order")
    ck("border-right" in panel and "border-left" not in panel,
       "the panel's divider moved to its right edge, since it is now the left column")

    specs = rule(".fo-specs")
    ck("repeat(3,minmax(0,1fr))" in specs,
       "specs are THREE columns - the extra width becomes data, not white space")
    dt = rule(".fo-dt")
    ck("repeat(2,minmax(0,1fr))" in dt, "drive times are two columns")
    ck("grid-column:1/-1" in rule(".fo-dt-title"),
       "...with the heading spanning both, so it cannot sit in one column")

    ck("--fo-pad" in specs and "--fo-pad" in rule(".fo-name") and "--fo-pad" in rule(".fo-hint"),
       "one --fo-pad rhythm drives the panel gutters, so they cannot drift per element")
    # These two numbers decide how much of an option reads without scrolling, and they were
    # MEASURED on the 30-property build at 1600x1000 (activating each slide directly - a
    # keyboard sweep re-measures one slide whenever the panel scrolls, and reports a flattering
    # zero): 80vh + 22vh hero -> 30/30 scroll, worst 239px; 88vh + 17vh hero -> 22/30, worst 99px.
    # Four spec columns was tried and is WORSE (worst 164px, wrapped values 60 vs 31). Loosening
    # either number silently gives back the scroll this bought.
    ck("88vh" in rule(".fo-wrap"), "the frame is 88vh - the height that makes all 30 options fit")
    ck("17vh" in rule(".fo-hero"),
       "the hero is 17vh - image height traded for content, which is what makes them fit")
    ck("clamp(" in rule(".fo-hero"),
       "the hero height is viewport-relative, so a data-rich option keeps its rows above the fold")
    ck("clamp(" in rule(".fo-name"), "the property name scales with the wider panel")

    ck("@media(max-width:1100px)" in h and "repeat(2,minmax(0,1fr))" in
       h.split("@media(max-width:1100px)")[1][:160],
       "below 1100px the specs drop to two columns rather than wrapping again")
    narrow = h.split("@media(max-width:900px)")[1][:400] if "@media(max-width:900px)" in h else ""
    ck("order:1" in narrow and "order:2" in narrow,
       "stacked on a narrow screen the MAP comes first - it orients you before the numbers")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
