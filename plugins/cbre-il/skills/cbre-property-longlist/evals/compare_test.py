#!/usr/bin/env python3
"""compare_test.py - the COMPARE view is baked into the FROZEN template (v25), GENERIC (any client /
format / language / N properties), reuses the chrome's compareHTML(items) renderer, and leaves the
card tick-box popup (state.compare + its 4-cap) UNTOUCHED. Source-level assertions over a real build
round-trip; JS EXECUTION (the compare IIFE runs without throwing) + byte-identity are covered by
modal_render_test + smoke_test, which concatenate and run every inline script. The BEHAVIOURAL /
SCALE proof (columns == N for 4/8/12, chip deselect drops one column, filter reduces columns, popup
independent) is the live G-visual reviewer + a browser check - see reference/visual-qa.md. Offline."""
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

NEW_KEYS = ["tab_compare", "cmp_tab_title", "cmp_select_all", "cmp_clear_all",
            "cmp_shown_count", "cmp_empty", "cmp_no_match"]


def _canon(n=6):
    meta = {"client": "CmpCo", "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
            "lede": "", "footer_copyright": ""}}
    props = []
    for i in range(1, n + 1):
        props.append({"id": i, "country": "ES", "park": f"Park {i}", "developer": "D",
                      "city": "Madrid" if i % 2 else "Sevilla", "status": "Existing",
                      "warehouseArea": 10000 + i * 5000, "warehouseRent": "€60 / sq m / year",
                      "warehouseRentVal": 60.0 + i, "photo": PX, "gallery": [PX],
                      "lat": 40.0 + i * 0.1, "lng": -3.0 - i * 0.1})
    return {"meta": meta, "properties": props, "pois": [], "regions": {}}


def main() -> int:
    fails = []
    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_cmp_"))
    cp = d / "c.json"; cp.write_text(json.dumps(_canon(6)), encoding="utf-8")
    hp = d / "b.html"; build_dashboard.build(cp, hp)
    h = hp.read_text(encoding="utf-8")

    # structure: the compare view + tab survive the build (frozen chrome that reads PROPS)
    ck("tab-compare" in h, "compare tab id present")
    ck('id="view-compare"' in h or 'id = "view-compare"' in h or '"view-compare"' in h,
       "compare view container present")
    ck("switchView('compare')" in h, "compare tab wired to switchView('compare')")

    # i18n wired: every NEW key is used via T() (the i18n orphan gate also enforces this)
    for k in NEW_KEYS:
        ck(f'T("{k}")' in h or f"T('{k}')" in h, f'compare uses T("{k}")')

    # REUSE the single N-agnostic renderer - never a second comparison table
    ck("compareHTML(shown)" in h, "compare REUSES chrome compareHTML(shown) (no drift, any-N)")
    ck('typeof compareHTML !== "function"' in h, "guard: bails if compareHTML is absent")

    # DEFAULT = ALL (any N): the selection Set is seeded from every PROPS id, never a hardcoded count
    ck("new Set(PROPS.map(" in h, "default selection = all PROPS (new Set(PROPS.map(...)) - not 4)")
    # chips + shown set derive from the LIVE filtered list; deselections persist across filtering
    ck("filterList()" in h, "chips + shown derive from filterList() (honours filters + sort)")
    ck("selected.has(p.id)" in h, "shown = filtered INTERSECT selected (selected.has(p.id))")
    ck("filterList().forEach" in h, "Select-all / Clear-all operate on the current FILTERED set")

    # wraps switchView + applyFilters, preserving the chain (which already includes Flyover)
    ck("var origSwitch = window.switchView" in h, "wraps window.switchView (origSwitch preserved)")
    ck("var origApply = window.applyFilters" in h, "wraps window.applyFilters (live re-render on filter/sort)")

    # the CARD tick-box popup + its 4-cap are UNTOUCHED (independent selection state)
    ck("state.compare" in h, "popup compare state (state.compare) still present")
    ck("compare up to 4" in h, "popup's deliberate 4-property cap alert is UNTOUCHED")
    ck("function openCompare(" in h, "popup openCompare() still present")

    # SCALE to many properties: attribute column pinned + horizontal scroll (the v25 scale CSS)
    ck("#view-compare .cmp-table thead th:not(:first-child){position:static}" in h,
       "scale CSS: non-first header cells un-stuck so only the attribute column pins")
    ck("#view-compare .cmp-table-wrap{overflow-x:auto" in h, "scale CSS: horizontal scroll for many columns")

    # Compare KEEPS the filters/sort toolbar visible (unlike Flyover, which hides it)
    ck('["toolbar", "result-meta"].forEach' in h and 'el.style.display = ""' in h,
       "compare keeps the toolbar + result-meta visible")

    # GENERIC: no hardcoded property count in the compare module (the popup's 4-cap is separate)
    cmp_start = h.find("COMPARE view (v25")
    cmp_seg = h[cmp_start:cmp_start + 6000] if cmp_start >= 0 else ""
    ck(bool(cmp_seg), "compare module block located")
    ck(".slice(0, 4)" not in cmp_seg and "slice(0,4)" not in cmp_seg and "=== 4" not in cmp_seg,
       "compare module has NO hardcoded property count (any N)")

    if fails:
        print(f"\nCOMPARE TEST: FAIL ({len(fails)})")
        return 1
    print("\nCOMPARE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
