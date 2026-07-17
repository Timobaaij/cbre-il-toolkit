#!/usr/bin/env python3
"""flyover_test.py - the Flyover view is baked into the FROZEN template, GENERIC (no hardcoded
en-US number format / country dictionary / Poland map centre), fully i18n-wired, and reads PROPS at
runtime. Source-level assertions over a real build round-trip; JS EXECUTION (the flyover IIFE runs
without throwing) and byte-identity are covered by modal_render_test + smoke_test, which concatenate
and run every inline script. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import build_dashboard  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

NEW_KEYS = ["tab_flyover", "flyover_hint", "flyover_dt_title",
            "open_in_maps", "label_option", "row_plot", "row_developer", "row_motorway"]


def _canon():
    meta = {"client": "FlyCo", "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
            "lede": "", "footer_copyright": ""}}
    return {"meta": meta, "properties": [
        {"id": 1, "country": "ES", "park": "Alpha", "developer": "D", "city": "Madrid",
         "status": "Existing", "warehouseArea": 50000, "photo": PX, "gallery": [PX],
         "lat": 40.4, "lng": -3.7,
         "preBaked": {"distances": {"Madrid Airport": {"min": 25, "km": 30}}}},
        {"id": 2, "country": "ES", "park": "Beta", "developer": "D", "city": "Sevilla",
         "status": "Land", "warehouseArea": 20000, "photo": PX, "gallery": [PX],
         "lat": 37.4, "lng": -6.0},
        {"id": 3, "country": "ES", "park": "Gamma", "city": "Bilbao", "status": "Existing",
         "warehouseArea": 10000, "photo": PX, "gallery": [PX]},  # no coords -> must not break
    ], "pois": [], "regions": {}}


def main() -> int:
    fails = []
    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_fly_"))
    cp = d / "c.json"; cp.write_text(json.dumps(_canon()), encoding="utf-8")
    hp = d / "b.html"; build_dashboard.build(cp, hp)
    h = hp.read_text(encoding="utf-8")

    # structure: the flyover view + tab survive the build (frozen chrome that reads PROPS)
    ck("view-flyover" in h, "flyover view present in the built html")
    ck("tab-flyover" in h, "flyover tab id present")

    # i18n wired: every NEW key is used via T() (the i18n orphan gate also enforces this)
    for k in NEW_KEYS:
        ck(f'T("{k}")' in h or f"T('{k}')" in h, f'flyover uses T("{k}")')

    # GENERIC: locale-aware helpers, no client/locale/geo hardcoding
    ck("regionName(" in h, "uses regionName() for country (locale-aware, any ISO code)")
    # regionName is function-local to populateFilters() in the chrome, so the flyover MUST define
    # its own (else ReferenceError on first open). Guard that fatal-bug class explicitly.
    ck("var regionName" in h, "flyover defines regionName LOCALLY (own Intl.DisplayNames, not a missing global)")
    # derived numbers stay LOCALE-formatted: plotArea via fmt(), never raw
    ck("fmt(p.plotArea)" in h, "plotArea is locale-formatted via fmt() (+ AREA_UNIT), not raw")
    ck("fitBounds(" in h, "fits the map to the properties (no hardcoded centre)")
    ck('toLocaleString("en-US")' not in h and "toLocaleString('en-US')" not in h,
       "no hardcoded en-US number formatting")
    ck("setView([51.05" not in h, "no hardcoded Poland map centre")
    ck("var COUNTRIES" not in h and "COUNTRIES = {" not in h and "COUNTRIES={" not in h,
       "no hardcoded country dictionary")

    if fails:
        print(f"\nFLYOVER TEST: FAIL ({len(fails)})")
        return 1
    print("\nFLYOVER TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
