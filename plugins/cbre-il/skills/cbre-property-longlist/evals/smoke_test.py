#!/usr/bin/env python3
"""smoke_test.py - prove the template round-trip without any extraction.

Builds a 2-property canonical.json, injects it, and asserts:
  * output written and non-trivial
  * the three const data blocks are present and JSON round-trippable
  * validate-html passes (output == render(canonical) byte-for-byte; chrome sha matches)

Run: python evals/smoke_test.py
Exit 0 on success, 1 on any failure.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C
import build_dashboard

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

CANON = {
    "meta": {
        "client": "SmokeCo",
        "hero": {
            "topbar_meta": "CEE · Test 2026",
            "eyebrow": "Property Shortlist · Smoke Test",
            "title_html": "Test logistics <em>options</em> for your next facility.",
            "lede": "Two fixture properties to prove the template round-trip end to end.",
            "footer_copyright": "© 2026 CBRE · Smoke test build",
        },
    },
    "properties": [
        {"id": 1, "country": "HU", "park": "Test Park One", "developer": "DevA",
         "city": "Budapest", "region": "Budapest", "regionCode": "BUD",
         "lat": 47.4979, "lng": 19.0402, "status": "BTS (Lease)",
         "warehouseArea": 40000, "warehouseRent": "€60 / sq m / year",
         "warehouseRentVal": 60.0, "clearHeight": "12 m", "earlyAccess": "2027",
         "motorway": "M0", "photo": PX, "gallery": [PX, PX, PX]},
        {"id": 2, "country": "CZ", "park": "Test Park Two", "developer": "DevB",
         "city": "Pilsen", "region": "Pilsen", "regionCode": "PLZ",
         "lat": 49.7384, "lng": 13.3736, "status": "Speculative",
         "warehouseArea": 76000, "warehouseRent": "€48 / sq m / year",
         "warehouseRentVal": 48.0, "clearHeight": "tbd", "earlyAccess": "2026",
         "motorway": "D5", "photo": PX},
    ],
    "pois": [
        {"name": "Hamburg (Port)", "type": "port", "lat": 53.5441, "lng": 9.9685, "country": "DE"},
    ],
    "regions": {
        "BUD": {"name": "Budapest", "country": "Hungary", "unemployment": 4.0},
        "PLZ": {"name": "Pilsen", "country": "Czech Republic", "unemployment": 2.9},
    },
}


def main() -> int:
    # write to a temp dir so running the test never bloats the installed skill
    import tempfile
    outdir = Path(tempfile.mkdtemp(prefix="cbre_longlist_smoke_"))
    canon_path = outdir / "smoke_canonical.json"
    html_path = outdir / "smoke.html"
    canon_path.write_text(json.dumps(CANON, ensure_ascii=False, indent=2), encoding="utf-8")

    fails = []

    # build
    build_dashboard.build(canon_path, html_path)
    html = html_path.read_text(encoding="utf-8")

    if len(html) < 100_000:
        fails.append(f"output suspiciously small: {len(html)} bytes")

    # three blocks round-trip
    for name, typ in (("PROPS", list), ("POIS", list), ("REGIONS", dict)):
        m = re.search(rf"const {name} = (.*?);(?:\n|$)", html, re.DOTALL)
        if not m:
            fails.append(f"block const {name} missing")
            continue
        try:
            val = json.loads(m.group(1))
            if not isinstance(val, typ):
                fails.append(f"block {name} wrong type: {type(val).__name__}")
        except Exception as e:
            fails.append(f"block {name} not valid JSON: {e}")

    # no leftover tokens/markers
    leftover = C.find_leftover_tokens(html)
    if leftover:
        fails.append(f"leftover tokens: {leftover}")

    # v12: the gallery DATA round-trips into the PROPS block (the grid/modal render
    # client-side, so the static HTML carries the data + the carousel JS source, not
    # executed markup; the live carousel render is verified separately via Playwright).
    mg = re.search(r"const PROPS = (.*?);(?:\n|$)", html, re.DOTALL)
    gallery_ok = False
    if mg:
        try:
            gallery_ok = any(isinstance(pp.get("gallery"), list) and len(pp["gallery"]) == 3
                             for pp in json.loads(mg.group(1)))
        except Exception:
            pass
    if not gallery_ok:
        fails.append("v12: the 3-photo gallery did not round-trip into the PROPS data block")

    # byte-for-byte render match (the chrome-stability guarantee)
    expected, _ = build_dashboard.render(CANON)
    if html != expected:
        fails.append("delivered HTML != render(canonical) (chrome drift)")

    # KPIs computed
    if '<div class="kpi-value">2</div>' not in html:
        fails.append("KPI properties count (2) not rendered")

    # regions KPI sub-label is ALWAYS the static phrase - never an enumeration of
    # region labels (filename-derived labels leaked into the hero strip on a real run)
    if '<div class="kpi-sub">Under consideration</div>' not in html:
        fails.append('regions KPI sub-label is not the static "Under consideration"')
    if "Budapest · Pilsen" in html:
        fails.append("regions KPI sub-label enumerates region names again (v8 regression)")

    # v8 template guard: the modal maps anchor must never render a raw/empty
    # p.mapLink href (href="" reloads the dashboard itself)
    tpl = C.load_template()
    if 'href="${p.mapLink}"' in tpl:
        fails.append('template renders unguarded href="${p.mapLink}" (v8 regression)')
    if "const mapHref" not in tpl:
        fails.append("template missing the v8 mapHref derivation (explicit link -> coords -> omit)")

    # v10 template guards: unit-aware labels (source convention KEPT)
    if "const AREA_UNIT" not in tpl or "{{kpi_wh_area_sub}}" not in tpl or "{{kpi_rent_sub}}" not in tpl:
        fails.append("template missing the v10 unit machinery (AREA_UNIT const / KPI sub tokens)")
    if '<div class="kpi-sub">sq m per building</div>' in tpl:
        fails.append("template still hardcodes the metric KPI sub-label (v10 regression)")
    if "} sq m</div>" in tpl or "+' sq m'" in tpl or "+ ' sq m'" in tpl:
        fails.append("template still hardcodes a ' sq m' suffix somewhere (v10 regression)")
    if '<div class="kpi-sub">sq m per building</div>' not in html:
        fails.append("builder did not fill the metric default KPI sub-label for a unit-less canonical")
    imp = build_dashboard.compute_kpis(
        [{"warehouseArea": 170000, "warehouseRentVal": 8.5, "rentUnit": "£/sq ft/yr",
          "country": "GB", "developer": "EVO"}], {},
        {"area": "sq ft", "rent": "£/sq ft/yr"})
    if imp["kpi_rent"] != "£8.5" or imp["kpi_rent_sub"] != "per sq ft / year" \
            or imp["kpi_wh_area_sub"] != "sq ft per building":
        fails.append(f"imperial KPI strip wrong: {imp['kpi_rent']!r} / {imp['kpi_rent_sub']!r}")

    # v9 template guards: dataset-wide field presence + present-only workforce tiles
    if "const FIELD_PRESENT" not in tpl:
        fails.append("template missing the v9 FIELD_PRESENT map (dataset-empty variables must not render)")
    # v19: the tile LABELS are now localised via T('KEY') (the tile still exists, now keyed)
    if "stat(T('wf_gdp_nominal')" not in tpl or "emplManufacturing" not in tpl:
        fails.append("template missing the v9 Oxecon workforce tiles (nominal GDP / employment)")
    if '<div class="region-k">Employment rate</div>' in tpl:
        fails.append("template still hardcodes the Employment-rate tile (v9 regression - tiles must be value-gated)")
    if "${rStr(reg.notes)}" in tpl:
        fails.append("template still renders region notes unconditionally (a lone 'tbd' paragraph shipped)")

    # v11 template guards: the avg-gross-wage tile (the one researched figure) is
    # replaced by a logistics-employment-share tile derived from two dataset figures
    if "reg.avgWageGross" in tpl or "Avg monthly gross wage" in tpl:
        fails.append("template still renders the avg-gross-wage tile (v11 regression - wage was removed)")
    # v19: the tile label is localised (T('wf_logistics_share')); the derivation const stays
    if "const logiShare" not in tpl or "T('wf_logistics_share')" not in tpl:
        fails.append("template missing the v11 logistics-employment-share tile (transport&storage / labour force)")
    if "reg.avgWageNote" in tpl or "reg.minWageNote" in tpl:
        fails.append("template still renders the wage-note source appendix (v11 regression)")

    # v12 template guards: photo carousel (cards + modal), MANUAL nav only (no autoplay)
    if "function gal(" not in tpl or "function cardNav(" not in tpl:
        fails.append("template missing the v12 carousel helpers (gal / cardNav)")
    if 'class="cm-nav' not in tpl or "cm-count" not in tpl or 'id="modal-prev"' not in tpl:
        fails.append("template missing the v12 carousel markup (.cm-nav / .cm-count / #modal-prev)")
    if "gal(p)[0]" not in tpl:
        fails.append("template hero is not gallery-aware (cardHTML/detailHTML must use gal(p)[0])")
    if "setInterval" in tpl:
        fails.append("template uses setInterval - the carousel must be MANUAL (no autoplay/timer)")

    # v13 template guards: data-driven slider, single-country header, monthly rent
    if "function initSizeSlider(" not in tpl:
        fails.append("template missing the v13 data-driven size slider (initSizeSlider)")
    if 'min="30000"' in tpl or 'max="76000"' in tpl:
        fails.append("template still hardcodes the CEE size-slider bounds 30000-76000 (v13 regression)")
    if "AREA_UNIT.replace" not in tpl:
        fails.append("template size-slider label is not unit-aware (v13: must suffix AREA_UNIT, not 'sq m')")
    if "function adaptSingleCountryHeader(" not in tpl or "kpi-regions-expanded" not in tpl:
        fails.append("template missing the v13 single-country header adaptation")
    if "function rentMonthlyStr(" not in tpl or "const RENT_CUR" not in tpl:
        fails.append("template missing the v13 monthly-rent helper (rentMonthlyStr / RENT_CUR)")
    # v19: the monthly-rent row label is localised via T('row_warehouse_rent_monthly')
    if "T('row_warehouse_rent_monthly')" not in tpl or 'class="rent-mo"' not in tpl:
        fails.append("template missing the v13 monthly-rent rows/markup")
    # the monthly rent must round-trip into the built HTML for a rent-bearing property
    if "/ mo" not in html:
        fails.append("v13: a monthly rent ('/ mo') did not render for a rent-bearing fixture property")
    # v13: the compare 'lowest rent' must skip non-numeric rents (a null/tbd rent coerces
    # to 0 and would otherwise win 'lowest' AND highlight the new monthly row too)
    if "p.warehouseRentVal < items[best].warehouseRentVal ? i : best, 0)" in tpl:
        fails.append("compare minRentIdx still treats a null/tbd rent as 0 (v13: must skip non-numeric)")

    # v14 template guards: TOTAL rent (GLA x rate) on top of the per-area rate
    if "function totalAnnualRent(" not in tpl or "function totalRentStr(" not in tpl:
        fails.append("template missing the v14 total-rent helpers (totalAnnualRent / totalRentStr)")
    # v19: the row labels are localised via T('KEY') (the rows still exist, now keyed)
    if "T('row_total_annual_rent')" not in tpl or "T('row_total_monthly_rent')" not in tpl:
        fails.append("template missing the v14 total-rent rows ('Total annual rent' / 'Total monthly rent')")
    if "officeRentVal" not in tpl or "officeAreaVal" not in tpl:
        fails.append("template total-rent maths does not reference officeRentVal/officeAreaVal (the split)")

    # v15 guard: a tbd/absent description must NOT render as a bare 'tbd' paragraph -
    # the desc <p> must be wrapped in the isTbd ternary (the wrapper exists ONLY in the
    # guarded form, so its absence catches a regression to the unconditional render)
    if "${isTbd(p.description) ? '' :" not in tpl:
        fails.append("modal description not guarded (v15: a tbd description must not render a bare 'tbd' paragraph)")

    # v16 guards: Total GLA row (warehouse + office, shown alongside both) + photo lightbox
    if "function glaVal(" not in tpl or "function glaStr(" not in tpl:
        fails.append("template missing the v16 GLA helpers (glaVal / glaStr)")
    if "Total GLA" not in tpl:
        fails.append("template missing the v16 'Total GLA' row")
    if 'id="lightbox"' not in tpl or 'id="lb-img"' not in tpl or "function openLightbox(" not in tpl:
        fails.append("template missing the v16 photo lightbox (#lightbox / #lb-img / openLightbox)")
    if "openLightbox(g, i)" not in tpl:
        fails.append("template: clicking the modal photo does not open the lightbox at the current index")

    # v17 guards: honest drive-time labelling driven by the build-time enrichment state
    # via the single {{dist_mode}} config token.
    if "{{dist_mode}}" not in tpl:
        fails.append("template missing the v17 {{dist_mode}} config token")
    if "const DIST_MODE" not in tpl or "const DIST_BADGE" not in tpl or "const DIST_LABEL" not in tpl:
        fails.append("template missing the v17 DIST_MODE/DIST_LABEL/DIST_BADGE machinery")
    # v19: the "Drive time" label is localised (T('dist_th_drive_time')); the DIST_LABEL
    # mode suffix is preserved
    if 'T("dist_th_drive_time")} (${DIST_LABEL[DIST_MODE]' not in tpl:
        fails.append("template Drive-time column header is not mode-aware (v17: must suffix DIST_LABEL[DIST_MODE])")
    # v19: the live-status disclosure strings moved into i18n.EN; FIX 2 split the baked
    # car/HGV line into a brand-green lead + plain rest, so the template calls
    # T('dist_status_car_lead')/_rest + T('dist_status_est'); disclosure preserved, now keyed.
    import i18n as _I18N_v17
    if "T('dist_status_car_lead')" not in tpl and "T(\"dist_status_car_lead\")" not in tpl:
        fails.append("template live-status is not keyed to T('dist_status_car_lead') (v19)")
    if "truck/hgv times are not modelled" not in _I18N_v17.EN.get("dist_status_car_rest", "").lower() \
            or "truck/hgv times are not modelled" not in _I18N_v17.EN.get("dist_status_est", "").lower():
        fails.append("i18n.EN no longer discloses that truck/HGV times are not modelled (v17)")
    # the no-enrichment smoke fixture (no meta.enrichment) must label as straight-line estimates
    if 'const DIST_MODE = "est";' not in html:
        fails.append('v17: a no-enrichment build did not render const DIST_MODE = "est"')
    # v17: prove ALL THREE label states render straight from meta.enrichment (offline proof)
    import copy
    for mode, routing in (("car", "driving-car (public OSRM fallback)"),
                          ("hgv", "driving-hgv (openrouteservice)")):
        variant = copy.deepcopy(CANON)
        variant["meta"]["enrichment"] = {"osrm": True, "osrm_done": True, "routing": routing}
        if f'const DIST_MODE = "{mode}";' not in build_dashboard.render(variant)[0]:
            fails.append(f'v17: an osrm {mode}-profile build did not render const DIST_MODE = "{mode}"')
    # an --osrm run that baked NOTHING (osrm_done False) must honestly degrade to est, never claim a route
    _nb = copy.deepcopy(CANON)
    _nb["meta"]["enrichment"] = {"osrm": True, "osrm_done": False, "routing": "driving-hgv (openrouteservice)"}
    if 'const DIST_MODE = "est";' not in build_dashboard.render(_nb)[0]:
        fails.append('v17: an --osrm run that baked nothing (osrm_done False) must degrade to DIST_MODE "est"')

    # v18 guards: LANDLORD surfaced as a DISTINCT party from the developer, in the
    # detail modal (Availability & Site) + the compare table, EACH gated by
    # FIELD_PRESENT['landlord'] so a no-landlord dataset renders no landlord row
    # (the modal/compare are CLIENT-SIDE JS, so these rows live in the TEMPLATE; the
    # landlord VALUE rides inside the PROPS data block - no new {{config}} token).
    # v19: the Landlord label is localised via T('row_landlord'); the FIELD_PRESENT
    # gating key ('landlord') is unchanged, so the row still hides on a no-landlord dataset
    if "row(T('row_landlord'), p.landlord, 'landlord')" not in tpl:
        fails.append("template missing the v18 modal Landlord row (FIELD_PRESENT-gated row(T('row_landlord'), p.landlord, 'landlord'))")
    if "[T('row_landlord'), p=>p.landlord, 'landlord']" not in tpl:
        fails.append("template missing the v18 compare Landlord row ([T('row_landlord'), p=>p.landlord, 'landlord'])")
    # the landlord must NOT leak onto the card hero line, the filters, the search index
    # or the sort (the card stays clean; developer remains the primary axis).
    import re as _re18
    m_dev = _re18.search(r'class="dev-line">\$\{([^}]*)\}', tpl)
    if m_dev and "landlord" in m_dev.group(1):
        fails.append("v18: the card hero dev-line must stay developer-only (landlord must not ride the card)")
    if 'f-land' in tpl or 'All landlords' in tpl or '>All landlords<' in tpl:
        fails.append("v18: landlord must NOT add a filter (it rides inside PROPS, no new config token / filter)")
    if "p.landlord, p.city" in tpl or "p.developer, p.landlord" in tpl.replace(" ", ""):
        fails.append("v18: landlord must NOT join the search haystack / hero line")
    if "localeCompare" in tpl and "a.landlord" in tpl:
        fails.append("v18: landlord must NOT add a sort comparator")
    # the landlord VALUE round-trips into the PROPS data block for a landlord-bearing
    # property (offline proof the field reaches the client without a new token)
    import copy as _copy18
    ll_variant = _copy18.deepcopy(CANON)
    ll_variant["properties"][0]["landlord"] = "NFU Mutual"
    ll_html = build_dashboard.render(ll_variant)[0]
    mll = re.search(r"const PROPS = (.*?);(?:\n|$)", ll_html, re.DOTALL)
    landlord_round_trips = False
    if mll:
        try:
            landlord_round_trips = any(pp.get("landlord") == "NFU Mutual"
                                       for pp in json.loads(mll.group(1)))
        except Exception:
            pass
    if not landlord_round_trips or "NFU Mutual" not in ll_html:
        fails.append("v18: a landlord value did not round-trip into the PROPS data block")
    # the no-landlord smoke fixture carries NO landlord key set to a real value: every
    # property's landlord is the 'tbd' sentinel (filled by fill_render_sentinels), so
    # FIELD_PRESENT['landlord'] is false at runtime and the gated row renders nowhere.
    mnl = re.search(r"const PROPS = (.*?);(?:\n|$)", html, re.DOTALL)
    if mnl:
        try:
            if any(str(pp.get("landlord", "tbd")).strip().lower() not in ("tbd", "", "—")
                   for pp in json.loads(mnl.group(1))):
                fails.append("v18: the no-landlord fixture unexpectedly carries a real landlord value")
        except Exception:
            pass

    # v20 guards: the browser-tab <title> is the adaptive {{doc_title}} token (was a
    # hardcoded "CEE Logistics Property Shortlist" default); it derives per project +
    # language from the hero, so the built tab title is a real project string.
    if "{{doc_title}}" not in tpl:
        fails.append("template <title> is not the adaptive {{doc_title}} token (v20)")
    if "CEE Logistics Property Shortlist" in tpl:
        fails.append("v20: template still carries the hardcoded 'CEE Logistics Property Shortlist' <title>")
    m_title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    built_title = m_title.group(1) if m_title else ""
    if (not built_title) or "{{" in built_title or "CEE Logistics Property Shortlist" in built_title:
        fails.append(f"v20: built <title> is not an adapted project title (got {built_title!r})")
    import copy as _copy20
    es_variant = _copy20.deepcopy(CANON)
    es_hero = es_variant["meta"].setdefault("hero", {})
    es_hero["eyebrow"] = "Lista de naves logísticas · España"; es_hero.pop("doc_title", None)
    m_es = re.search(r"<title>(.*?)</title>", build_dashboard.render(es_variant)[0], re.DOTALL)
    if not (m_es and "España" in m_es.group(1)):
        fails.append("v20: <title> does not adapt to the project (Spanish eyebrow did not reach the tab title)")

    # v21 guards: data-driven modal fields (generic catch-all + per-property omit)
    # NOTE: DENY_CONTAINERS was v21's flatten-denylist; v22 Phase 1 removes the flatten
    # entirely (see v22 guards below), so DENY_CONTAINERS is intentionally gone and is no
    # longer part of this guard - only DENY_FIELDS (still in use) is checked here.
    if "const DENY_FIELDS" not in tpl:
        fails.append("template missing the v21 DENY_FIELDS denylist")
    if "const autoLabel" not in tpl:
        fails.append("template missing the v21 autoLabel data-label helper")
    if "const consumed = new Set()" not in tpl:
        fails.append("template missing the v21 per-call consumed Set in detailHTML")
    if "T('sec_additional')" not in tpl and 'T("sec_additional")' not in tpl:
        fails.append("template missing the v21 Additional Details catch-all section header")
    if 'T("val_tbc")' in tpl or "T('val_tbc')" in tpl:
        fails.append("v21 regression: modal row() still emits a val_tbc placeholder (must omit absent rows)")
    import i18n as _I18N_v21
    if "val_tbc" in _I18N_v21.EN:
        fails.append("v21: val_tbc must be removed from i18n.EN (now an orphan key)")
    if "sec_additional" not in _I18N_v21.EN:
        fails.append("v21: sec_additional missing from i18n.EN")
    # FIELD_PRESENT is RETAINED for the compare matrix (uniform rows), just dropped from the modal row()
    if ".filter(r => !r[2] || FIELD_PRESENT[r[2]])" not in tpl:
        fails.append("v21: compare table must retain its FIELD_PRESENT row gating")

    # v22 guards: render-boundary (scalars only, no flatten, locator skip)
    if "const LOCATOR_RE" not in tpl:
        fails.append("template missing the v22 LOCATOR_RE guard")
    if "for(const sk of Object.keys(v))" in tpl:
        fails.append("v22 regression: the v21 object-flatten loop is still present (must be removed)")
    if "typeof v === 'object'" not in tpl:
        fails.append("v22: catch-all must skip object-valued keys (scalars only)")

    # v23 guard: derived numbers use a locale formatter, not raw toFixed
    if "const nfmt" not in tpl:
        fails.append("template missing the v23 nfmt locale number helper")
    if "(v / 12).toFixed(2)" in tpl:
        fails.append("v23 regression: monthly rent still uses toFixed(2) (must be nfmt)")

    if fails:
        print("\nSMOKE TEST: FAIL")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nSMOKE TEST: PASS (3 blocks round-trip, byte-stable chrome, KPIs computed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
