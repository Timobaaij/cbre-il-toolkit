#!/usr/bin/env python3
"""make_template.py - MAINTENANCE script (run once per template version).

Turns a reference CBRE longlist dashboard HTML into the skill's frozen template:
  1. Replaces the three data lines (const PROPS / POIS / REGIONS) with injection markers.
  2. Replaces the project-specific hero/footer/KPI strings with {{config}} tokens.
  3. Writes assets/dashboard_template.html and assets/VERSION (template label + SHA-256).

Design rule: every replacement MUST hit exactly once. If a literal is not found
(or found more than once) the script aborts loudly rather than producing a subtly
broken 11 MB template. This is the single point where the byte-stable "chrome" is
separated from the per-project "data"; it must be exact.

Usage:
  python make_template.py <reference.html> [--out assets/dashboard_template.html]
                          [--version assets/VERSION] [--label v1]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# v16 NOTE (2026-06-17, HAND-APPLIED to assets/dashboard_template.html like v5-v15 -
# re-add if ever regenerating from a raw reference). Two broker requests:
#  a) TOTAL GLA in Availability & Site: a `glaVal(p)` (warehouseArea + officeAreaVal,
#     plot is LAND not GLA) + `glaStr(p)` helper, and a 'Total GLA' row ABOVE the
#     'Warehouse area' + 'Office area' rows (all three shown separately) in the detail
#     modal AND the compare table (compare also gained the 'Office area' row it lacked).
#  b) PHOTO LIGHTBOX: clicking the modal photo opens it isolated + full-size in a
#     z-60 overlay (`#lightbox` with #lb-img / #lb-prev / #lb-next / #lb-close / #lb-count),
#     slide through the gallery (prev/next + Left/Right keys), close via X / backdrop /
#     Esc. Helpers openLightbox/lbRender/lbStep/closeLightbox/lbOpen; bindImageToggle's
#     #modal-img gains a click->openLightbox (the plan opens on its own, a photo opens
#     the gallery at the current carousel index); static lb controls bound once at init;
#     the Esc handler closes the lightbox first, then the modal. CSS: .lightbox/.lb-*
#     + `#modal-img{cursor:zoom-in}`.

# v21 NOTE (2026-07-09, HAND-APPLIED to assets/dashboard_template.html like v5-v20 -
# re-add if ever regenerating from a raw reference). Data-driven modal fields:
#  a) detailHTML's row() now OMITS an absent row (was a T('val_tbc') placeholder); the
#     dataset-wide FIELD_PRESENT gate is dropped from row() (per-property absence subsumes
#     it) but RETAINED in compareHTML (a matrix needs uniform rows). The T('val_tbc') key
#     is removed from i18n.EN + the 11 bundled JSONs - a future --patch-only/regen MUST
#     drop the make_template val_tbc patch literal (~line 616) and the key together.
#  b) module consts DENY_FIELDS / DENY_CONTAINERS / LABEL_OVERRIDES / autoLabel + a per-call
#     `consumed` Set; a generic catch-all after Commercial Terms renders every real field
#     not consumed/denylisted (flattening one level of nested scalars) under a new
#     T('sec_additional') "Additional Details" section. Auto-labels are DATA (no T() key).

# v23 NOTE (2026-07-15, HAND-APPLIED like v5-v22). Right formatting (Phase 3): a client-side
# nfmt(n,mn,mx) locale number helper; applied to rentMonthlyStr (monthly rate), rNum (workforce
# %), rK (workforce thousands) and regional GDP bn, so derived numbers follow output.language's
# separators. Source strings/currencies/units stay verbatim. Also folded the Phase-1 deferred
# cleanups: removed the stale DENY_CONTAINERS mention in the module-const comment and the
# redundant `v === null` in the catch-all.

# v24 NOTE (2026-07-16, HAND-APPLIED like v5-v23 - re-add if ever regenerating). FLYOVER view:
# a third view (tab after Grid/Map) appended as a self-contained <script> IIFE before </body> - a
# 70/30 satellite-map + scroll-snap slide panel that flyTo()s each property, with prev/next +
# arrow-key + marker-click nav, per-property spec slide, drive-time highlights and openModal(). It
# reads PROPS at runtime and REUSES the chrome's generic primitives (T / fmt / nfmt / regionName /
# AREA_UNIT / openModal / switchView[wrapped, origSwitch preserved]), so it is locale-, client- and
# format-agnostic: no hardcoded country dict (regionName via Intl.DisplayNames), no en-US numbers
# (fmt/nfmt on LOCALE), no hardcoded map centre (fitBounds to the geocoded PROPS). New i18n keys:
# tab_flyover, flyover_hint, flyover_dt_title, open_in_maps, label_option, row_plot, row_developer,
# row_motorway (EN + 11 bundled langs; machine first-cut pending CBRE house-term review). An unknown
# rent is OMITTED (never an unsourced "On application"); plotArea is fmt()+AREA_UNIT; the maps link
# falls back to a coord URL like the modal. Online ESRI/CARTO tiles (same sources as the main + modal
# maps). regionName is defined LOCALLY in the IIFE (the chrome's is function-local). Frozen chrome
# (injects no data) -> byte-identity holds; VERSION v23->v24 + new chrome_sha256.

# v22 NOTE (2026-07-15, HAND-APPLIED to assets/dashboard_template.html like v5-v21 -
# re-add if ever regenerating). Render-boundary correctness (Phase 1): the detailHTML
# catch-all now renders real SCALAR attributes only - it no longer flattens objects one
# level (the v21 DENY_CONTAINERS flatten is removed) and skips any value matching
# LOCATOR_RE (a "page N (...)" / bare "page N" provenance reference). merge._normalise_offspec
# quarantines non-canonical objects + locator scalars into __meta.offspec (ledger + Gaps)
# before clustering. Auto-show of genuine scalar attributes (canonical or brand-new) is preserved.

# v15 NOTE (2026-06-17, HAND-APPLIED to assets/dashboard_template.html like v5-v14 -
# re-add if ever regenerating from a raw reference). The modal description paragraph
# `<p class="desc">${p.description}</p>` rendered UNCONDITIONALLY, so a property with no
# captured description printed a bare 'tbd' line above 'Availability & Site'. Guard it
# like the spec rows: `${isTbd(p.description) ? '' : `<p class="desc">${p.description}</p>`}`
# (description is harvested only from machine-readable PDF prose - extract_pdf - so an
# image-only/photo-matched brochure or a tracker-only property legitimately has none).

# v14 NOTE (2026-06-17, HAND-APPLIED to assets/dashboard_template.html like v5-v13 -
# re-add these if ever regenerating from a raw reference). EXHAUSTIVE RENT: on top of
# the v13 per-area rate (annual + monthly), the detail modal AND the compare table now
# also show TOTAL annual + TOTAL monthly rent. Concretely:
#  - add `totalAnnualRent(p)` (GLA x rate: SPLIT warehouse@warehouseRate +
#    office@officeRate when a separate officeRentVal exists, else the single warehouse
#    rate over the whole warehouse+office GLA; null when no positive warehouse rate/area)
#    and `totalRentStr(p, monthly)` (Math.round + currency prefix + ' / yr' or ' / mo')
#    right after rentMonthlyStr;
#  - add two modal rows + two compare rows 'Total annual rent' / 'Total monthly rent'
#    (keyed warehouseRent so they share its FIELD_PRESENT gating; deliberately NOT
#    highlighted by the compare 'lowest rent' rule - that stays on the per-area rate rows).
#  The office numerics it multiplies (officeRentVal + officeAreaVal) are derived + TRACED
#  in merge.canonicalize, NOT parsed in the template. The card is unchanged (rates only).

# v13 NOTE (2026-06-17, HAND-APPLIED to assets/dashboard_template.html like v5-v12 -
# re-add these if ever regenerating from a raw reference). Four broker-requested fixes:
#  a) DATA-DRIVEN SIZE SLIDER: the reference hardcoded the warehouse-area slider to
#     min=30000 max=76000 step=1000 (a CEE/sq-m accident) - it filtered nothing on any
#     other dataset, and broke outright on sq ft (areas ~10x larger). Now a runtime
#     `initSizeSlider()` (called from populateFilters) sets the input min/max/step/value
#     and `state.filters.size` from the actual PROPS warehouseArea range (nice-rounded
#     step), records the floor in a module-level `SIZE_MIN`, and the Reset handler resets
#     to SIZE_MIN (was 30000). The static <input> ships neutral min=0 max=100 (overwritten
#     on load). `updateSizeLabel()` now suffixes AREA_UNIT (nbsp-joined) instead of a
#     hardcoded "sq m".
#  b) SINGLE-COUNTRY HEADER: a new runtime `adaptSingleCountryHeader()` (also from
#     populateFilters) - when the dataset has exactly ONE country it removes the
#     'Countries' hero KPI tile, adds `.kpi-regions-expanded` (grid-column:span 2) to the
#     'Regions' tile, and rewrites its sub to the spelled-out region names
#     (`regionDisplayNames()`: enriched REGIONS name, else the label; deduped). Runtime
#     DOM only - the static byte-chrome is untouched so validate-html stays byte-identical.
#     The country FILTER dropdown is intentionally kept.
#  c) MONTHLY RENT: a `const RENT_CUR` next to RENT_PER + a `rentMonthlyStr(p)` helper
#     (annual warehouseRentVal / 12, KEPT in its own currency + per-area convention - no
#     FX, no area maths; null when there is no numeric rate). Shown on the card (a
#     `<small class="rent-mo">` under the annual rent) and as a 'Warehouse rent (monthly)'
#     row in BOTH the detail modal and the compare table (keyed on warehouseRent so it
#     follows the same FIELD_PRESENT gating).
#  d) CSS: `.kpi-regions-expanded` and `.rent-mo`.

# v12 NOTE (2026-06-16, HAND-APPLIED to assets/dashboard_template.html like v5-v11 -
# re-add these if ever regenerating from a raw reference):
#  PHOTO CAROUSEL (cards + modal), manual prev/next ONLY (no autoplay/timer). Each
#  property carries p.gallery (a best-first list of photo data URIs, hero = gallery[0],
#  page-scoped in merge so a multi-property deck never leaks a neighbour's photo;
#  capped at images.GALLERY_MAX). Concretely:
#   - add `function gal(p){ return (Array.isArray(p.gallery)&&p.gallery.length)?p.gallery:[p.photo]; }`
#     and a `cardNav(id,dir,btn)` helper before cardHTML();
#   - card .thumb: the hero <img> gains class `thumb-img` + data-i, and when gal(p).length>1
#     two `.cm-nav` buttons (onclick event.stopPropagation();cardNav(...)) + a `.cm-count`;
#   - modal .modal-hero: #modal-img gains data-i, and when gal>1 `#modal-prev`/`#modal-next`
#     `.cm-nav` + `#modal-count`; the existing Site Plan image-toggle is KEPT;
#   - bindImageToggle(p) rewritten to drive the carousel (photo mode) AND the plan toggle
#     (switches mode); manual step() only, never a setInterval;
#   - CSS: `.cm-nav` (absolute, hover-reveal on cards / always-on in the modal) + `.cm-count`.

# v11 NOTE (2026-06-15, HAND-APPLIED to assets/dashboard_template.html like v5-v10 -
# re-add these if ever regenerating from a raw reference):
#  WORKFORCE: avg-gross-wage was the ONE region figure the bundled Oxford Economics
#  dataset could not supply, so it forced a slow per-figure research sub-agent. It is
#  REMOVED and replaced by a LOGISTICS-EMPLOYMENT-SHARE tile derived purely from two
#  figures the dataset already carries (and the Source Ledger already traces):
#  transport & storage employment / labour force, as a %. Concretely:
#   - delete the wage tile (raw: `€ ${reg.avgWageGross.toLocaleString()}`; the old
#     v6 POST_PATCH that fmt-wrapped it is removed below);
#   - add `const logiShare = (typeof reg.emplTransportStorage === 'number' && typeof
#     reg.labourForce === 'number' && reg.labourForce > 0) ? Number((reg
#     .emplTransportStorage / reg.labourForce * 100).toFixed(1)) : null;` before the
#     region-grid, and a stat('Logistics employment share', logiShare, '%', ...) tile;
#   - drop the Wage/Min-wage <em> appendix from the region-sources line.
#  The workforce snapshot is now 100% dataset-sourced (no research sub-agent by default).

# v10 NOTE (2026-06-12, HAND-APPLIED to assets/dashboard_template.html like v5-v9 -
# re-add these if ever regenerating from a raw reference):
#  UNIT-AWARE LABELS (source convention is KEPT - a UK dataset ships sq ft and
#  £/sq ft/yr): the two hero KPI sub-labels became the {{kpi_wh_area_sub}} /
#  {{kpi_rent_sub}} tokens (builder fills them from canonical meta.units); the
#  chrome gained `const AREA_UNIT` (from PROPS[i].areaUnit, merge stamps it on
#  every property) and `const RENT_PER` next to the v9 FIELD_PRESENT block; every
#  hardcoded ' sq m' suffix (card spec, card rent line, map popup, map list item,
#  modal Plot/Warehouse rows, compare Plot/Warehouse rows) now renders AREA_UNIT,
#  and the card rent line strips/re-applies the per-area tail per the property's
#  own rentUnit instead of assuming ' / sq m / year'.

# v9 NOTE (2026-06-12, HAND-APPLIED to assets/dashboard_template.html like v5-v8 -
# re-add these if ever regenerating from a raw reference):
#  a) DATASET-WIDE FIELD PRESENCE: a global `FIELD_PRESENT` map (built from PROPS
#     with `isAbsent`) hides any variable NO input ever carried: detailHTML's
#     `row(label, value, key)` returns '' for dataset-empty keys (each spec
#     section's heading renders only when the section still has rows), and
#     compareHTML's rows carry the same keys and are filtered up front.
#  b) WORKFORCE & REGION v9: the region-grid renders tiles ONLY for values that
#     exist (a `stat()` helper) - the reference's hardcoded Employment-rate and
#     GDP-per-capita-PPS tiles sat as permanent 'tbd' (no data source carries
#     them) while the bundled Oxford Economics fields gdpNominalMeur,
#     emplManufacturing and emplTransportStorage were never shown; all three
#     now have tiles. region-notes and the Wage/Min-wage source lines render
#     only when present (a lone 'tbd' paragraph used to ship).

# v8 NOTE (2026-06-11, HAND-APPLIED to assets/dashboard_template.html like v5-v7 -
# re-add these if ever regenerating from a raw reference):
#  the modal's "Open in Google Maps" anchor rendered href="${p.mapLink}"
#  UNCONDITIONALLY; mapLink is coerced to "" when unknown, and href="" navigates
#  to the dashboard itself (field report: every maps link reloaded the page).
#  detailHTML() now derives `const mapHref`: an explicit http(s) p.mapLink wins,
#  else https://www.google.com/maps?q=lat,lng from the property's traced
#  coordinates, else null - and the whole <span> renders only when mapHref is
#  truthy. (The companion fix in extract_pdf.py ships the brochure's own maps
#  hyperlink as mapLink, and build_dashboard.py makes kpi_regions_sub the static
#  "Under consideration" - region labels can be filename-derived and must never
#  be enumerated in the hero KPI strip.)

# v7 NOTE (2026-06-11, HAND-APPLIED to assets/dashboard_template.html like v5/v6 -
# re-add these if ever regenerating from a raw reference):
#  a) the #f-country <select> ships with ONLY the "All countries" option; country
#     options derive from PROPS in populateFilters() via Intl.DisplayNames (the
#     reference's hardcoded HU/CZ/SK stuck on every new market's dashboard);
#  b) the modal's Photo/Site-Plan toggle renders only when p.plan exists
#     (clicking it on a plan-less property showed a broken image);
#  c) coordinate-less properties (geocode declined/unresolved - legitimate per the
#     coverage gate) no longer crash the modal: initModalMap() and the coordinates
#     caveat both guard typeof p.lat !== "number" with an honest
#     "not yet located - see the Gaps Report" note.

# --- The three data blocks (each occupies one whole line in the reference) ------
DATA_MARKERS = {
    "const PROPS =": "/* @@INJECT:PROPS@@ */",
    "const POIS =": "/* @@INJECT:POIS@@ */",
    "const REGIONS =": "/* @@INJECT:REGIONS@@ */",
}

# --- Project-specific literals -> {{tokens}} (substring replacements) ------------
# Each key MUST appear exactly once in the reference. Order does not matter.
CONFIG_REPLACEMENTS = {
    # topbar meta (region label + compiled month/year)
    ">CEE · April 2026<": ">{{topbar_meta}}<",
    # hero eyebrow
    "Property Shortlist · Hungary, Czech Republic &amp; Slovakia": "{{eyebrow}}",
    # hero title (contains an <em> emphasis word -> HTML-bearing token)
    "CEE logistics <em>options</em> for your next facility.": "{{title_html}}",
    # hero lede paragraph (full sentence, distinctive)
    ("Thirty Build-to-Suit and speculative development opportunities across the "
     "Budapest metropolitan area, the Pilsen region and the Bratislava / Trnava "
     "corridor, delivering between late-2026 and 2028. Switch between the map and "
     "grid, filter by country, city, developer or scale, and compare up to four "
     "properties side-by-side with drive-time estimates to the main ports, rail "
     "terminals, airports and border crossings."): "{{lede}}",
    # KPI values (anchored by their label so the digits cannot collide)
    '<div class="kpi-label">Properties</div><div class="kpi-value">30</div>':
        '<div class="kpi-label">Properties</div><div class="kpi-value">{{kpi_properties}}</div>',
    '<div class="kpi-label">Countries</div><div class="kpi-value">3</div>':
        '<div class="kpi-label">Countries</div><div class="kpi-value">{{kpi_countries}}</div>',
    '<div class="kpi-label">Regions</div><div class="kpi-value">5</div>':
        '<div class="kpi-label">Regions</div><div class="kpi-value">{{kpi_regions}}</div>',
    '<div class="kpi-label">Developers</div><div class="kpi-value">18</div>':
        '<div class="kpi-label">Developers</div><div class="kpi-value">{{kpi_developers}}</div>',
    '<div class="kpi-label">Warehouse area</div><div class="kpi-value">33.6 – 76k</div>':
        '<div class="kpi-label">Warehouse area</div><div class="kpi-value">{{kpi_wh_area}}</div>',
    '<div class="kpi-label">Headline rent</div><div class="kpi-value">€48 – 78</div>':
        '<div class="kpi-label">Headline rent</div><div class="kpi-value">{{kpi_rent}}</div>',
    # dynamic KPI sub-labels
    '<div class="kpi-sub">HU · CZ · SK</div>': '<div class="kpi-sub">{{kpi_countries_sub}}</div>',
    '<div class="kpi-sub">Budapest · Pilsen · Karlovy Vary · Bratislava · Trnava</div>':
        '<div class="kpi-sub">{{kpi_regions_sub}}</div>',
    # v10 unit-convention sub-labels (builder fills from canonical meta.units)
    '<div class="kpi-sub">sq m per building</div>': '<div class="kpi-sub">{{kpi_wh_area_sub}}</div>',
    '<div class="kpi-sub">per sq m / year</div>': '<div class="kpi-sub">{{kpi_rent_sub}}</div>',
    # footer copyright + compiled date
    "© 2026 CBRE · Shortlist compiled 23 April 2026": "{{footer_copyright}}",
}

# Robustness patches: the original reference assumed every property carried every
# numeric. A general tool ingests messy inputs, so make the render tolerant of
# missing values (show "tbd" instead of crashing the whole grid/modal). Each must
# hit exactly once.
#
# v5 NOTE (2026-06-05): the client-side live nearest-POI block (ensureNearestPois /
# rebuildPoiMarkers / populateMapPois + the openModal/openCompare/switchView hooks)
# was applied DIRECTLY to assets/dashboard_template.html, because the raw reference
# HTML is not on disk to regenerate from. If a raw reference is ever re-supplied and
# you regenerate, you must re-add that block here as POST_PATCHES (and keep VERSION
# at v6+). See reference/template-contract.md and reference/memory.md.
#
# v6 NOTE (2026-06-05): the detailHTML "Workforce & Region" guard (reg/dist null-safe
# + rNum/rK/rStr honest-tbd helpers + an honest placeholder when neither exists) was
# likewise hand-applied to the template, so a build with no district/regions data no
# longer throws when a detail modal opens. Re-add it too if regenerating from a raw reference.
POST_PATCHES = {
    'const fmt = n => n.toLocaleString("en-US");':
        'const fmt = n => (typeof n === "number" && isFinite(n)) ? n.toLocaleString("en-US") : (n == null ? "tbd" : n);',
    # (v6 wage POST_PATCH removed at v11: the avg-gross-wage tile no longer exists -
    #  see the v11 NOTE above for the wage -> logistics-employment-share replacement.)
    # guard the comparison-table distance rows: a property may have no POI of a
    # given type (or POIs may be off), so [0] can be undefined -> show "tbd".
    "const d = groupedDistances(p).city[0]; return ":
        "const d = groupedDistances(p).city[0]; if(!d) return 'tbd'; return ",
    "const d = groupedDistances(p).border[0]; return ":
        "const d = groupedDistances(p).border[0]; if(!d) return 'tbd'; return ",
    "const d = groupedDistances(p).air[0]; return ":
        "const d = groupedDistances(p).air[0]; if(!d) return 'tbd'; return ",
    "const d = groupedDistances(p).rail[0]; return ":
        "const d = groupedDistances(p).rail[0]; if(!d) return 'tbd'; return ",
    "const d = groupedDistances(p).port[0]; return ":
        "const d = groupedDistances(p).port[0]; if(!d) return 'tbd'; return ",
    # --- v4 visual fixes (reported from real ES/SK builds) ---
    # 1. card: the mono ref badge (#NN) overlapped the country flag chip -> push the
    #    chip right so they never collide; and use '#' (the numero sign tofus in Space Mono).
    ".flag-chip{position:absolute;top:14px;left:56px;":
        ".flag-chip{position:absolute;top:14px;left:74px;",
    '<div class="ref">№ ${String(p.id).padStart(2,\'0\')}</div>':
        '<div class="ref"># ${String(p.id).padStart(2,\'0\')}</div>',
    # 2. map markers: only prop-hu/prop-cz had a fill, so SK / ES / any other country
    #    rendered a transparent circle with an unreadable white number. Give .cm a solid
    #    default fill, add prop-sk, bump the digit size, and drop the faint city opacity.
    (".cm{width:24px;height:24px;border-radius:50%;border:3px solid #fff;box-shadow:0 2px 6px "
     "rgba(0,0,0,.35),0 0 0 1px rgba(0,0,0,.2);display:grid;place-items:center;color:#fff;"
     "font-size:10px;font-weight:700;font-family:var(--font-body)}"):
        (".cm{width:24px;height:24px;border-radius:50%;border:3px solid #fff;box-shadow:0 2px 6px "
         "rgba(0,0,0,.35),0 0 0 1px rgba(0,0,0,.2);display:grid;place-items:center;background:#003F2D;"
         "color:#fff;font-size:11px;font-weight:700;font-family:var(--font-body)}"),
    ".cm.prop-cz{background:var(--cz)}":
        ".cm.prop-cz{background:var(--cz)}\n.cm.prop-sk{background:var(--sk)}",
    ".cm.city{background:#6d4c41;width:14px;height:14px;border-width:2px;opacity:.75}":
        ".cm.city{background:#6d4c41;width:14px;height:14px;border-width:2px}",
    # 3. compare tray: the global ghost button is white-bg/green-text (correct on light
    #    surfaces like Reset), but on the dark tray its white text was invisible. Scope a
    #    transparent-on-dark variant just for the tray.
    ".compare-tray{ background:var(--dark-green); }":
        (".compare-tray{ background:var(--dark-green); }\n"
         ".compare-tray .btn.ghost{ background:transparent; color:#fff; border-color:rgba(255,255,255,.35); }\n"
         ".compare-tray .btn.ghost:hover{ background:rgba(255,255,255,.14); color:#fff; border-color:#fff; }"),
}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def replace_config(text: str) -> str:
    for old, new in CONFIG_REPLACEMENTS.items():
        n = text.count(old)
        if n != 1:
            fail(f"config literal expected exactly once, found {n}x:\n  {old[:80]!r}")
        text = text.replace(old, new)
    return text


def replace_data_lines(text: str) -> str:
    lines = text.splitlines(keepends=True)
    hits = {prefix: 0 for prefix in DATA_MARKERS}
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        for prefix, marker in DATA_MARKERS.items():
            if stripped.startswith(prefix):
                # preserve trailing newline so line count is unchanged
                nl = "\n" if line.endswith("\n") else ""
                lines[i] = marker + nl
                hits[prefix] += 1
    for prefix, count in hits.items():
        if count != 1:
            fail(f"data line {prefix!r} expected exactly once, found {count}x")
    return "".join(lines)


# ===========================================================================
# v19 PATCH-ONLY PATH (i18n localisation)
# ===========================================================================
# The raw reference HTML is not on disk (v5-v18 were patched in place), so v19 is
# produced by patching the EXISTING frozen template - NOT a regen-from-reference.
# Each patch asserts text.count(old) == 1 or fails loudly. Apply order is fixed:
#   INJECT_BLOCK -> static block patches -> JS patches -> applyI18n call ->
#   adaptSingleCountryHeader key-based fix -> format/locale patches.
# All static chrome carries data-i18n / data-i18n-ph / data-i18n-al; JS-generated
# chrome calls T('KEY'); the country-filter / number formatting become LOCALE-aware.

# 1. The i18n bootstrap, inserted IMMEDIATELY BEFORE the unique `const ROUTES`
#    line. {{ui_json}} is NOT quoted (a JS object literal); {{locale}} IS quoted -
#    render() fills both. Kept as literal tokens here.
INJECT_BLOCK_ANCHOR = 'const ROUTES = {}; // cache:'
INJECT_BLOCK = (
    "const UI = {{ui_json}};\n"
    "const LOCALE = \"{{locale}}\";\n"
    "const T = k => (UI && UI[k] != null) ? UI[k] : k;\n"
    "function applyI18n(root){\n"
    "  const r = root || document;\n"
    "  r.querySelectorAll('[data-i18n]').forEach(el => { const v = UI[el.getAttribute('data-i18n')]; if(v != null) el.textContent = v; });\n"
    "  r.querySelectorAll('[data-i18n-ph]').forEach(el => { const v = UI[el.getAttribute('data-i18n-ph')]; if(v != null) el.setAttribute('placeholder', v); });\n"
    "  r.querySelectorAll('[data-i18n-al]').forEach(el => { const v = UI[el.getAttribute('data-i18n-al')]; if(v != null) el.setAttribute('aria-label', v); });\n"
    "}\n"
)

# 3. STATIC-HTML chrome -> data-i18n / data-i18n-ph / data-i18n-al, applied as a
#    small number of LARGE unique block patches (one per contiguous region). Where
#    an element wraps child nodes whose text must NOT be destroyed, the text is
#    wrapped in <span data-i18n="KEY">.
STATIC_PATCHES = [
    # --- KPI strip (labels localised; values are the {{kpi_*}} data tokens) ----
    (
        '<div class="kpi"><div class="kpi-label">Properties</div><div class="kpi-value">{{kpi_properties}}</div><div class="kpi-sub">Longlist</div></div>\n'
        '      <div class="kpi"><div class="kpi-label">Countries</div><div class="kpi-value">{{kpi_countries}}</div><div class="kpi-sub">{{kpi_countries_sub}}</div></div>\n'
        '      <div class="kpi"><div class="kpi-label">Regions</div><div class="kpi-value">{{kpi_regions}}</div><div class="kpi-sub">{{kpi_regions_sub}}</div></div>\n'
        '      <div class="kpi"><div class="kpi-label">Developers</div><div class="kpi-value">{{kpi_developers}}</div><div class="kpi-sub">Major landlords</div></div>\n'
        '      <div class="kpi"><div class="kpi-label">Warehouse area</div><div class="kpi-value">{{kpi_wh_area}}</div><div class="kpi-sub">{{kpi_wh_area_sub}}</div></div>\n'
        '      <div class="kpi"><div class="kpi-label">Headline rent</div><div class="kpi-value">{{kpi_rent}}</div><div class="kpi-sub">{{kpi_rent_sub}}</div></div>',
        '<div class="kpi"><div class="kpi-label" data-i18n="kpi_properties_label">Properties</div><div class="kpi-value">{{kpi_properties}}</div><div class="kpi-sub" data-i18n="kpi_properties_sub">Longlist</div></div>\n'
        '      <div class="kpi"><div class="kpi-label" data-i18n="kpi_countries_label">Countries</div><div class="kpi-value">{{kpi_countries}}</div><div class="kpi-sub">{{kpi_countries_sub}}</div></div>\n'
        '      <div class="kpi"><div class="kpi-label" data-i18n="kpi_regions_label">Regions</div><div class="kpi-value">{{kpi_regions}}</div><div class="kpi-sub">{{kpi_regions_sub}}</div></div>\n'
        '      <div class="kpi"><div class="kpi-label" data-i18n="kpi_developers_label">Developers</div><div class="kpi-value">{{kpi_developers}}</div><div class="kpi-sub" data-i18n="kpi_developers_sub">Major landlords</div></div>\n'
        '      <div class="kpi"><div class="kpi-label" data-i18n="kpi_wh_area_label">Warehouse area</div><div class="kpi-value">{{kpi_wh_area}}</div><div class="kpi-sub">{{kpi_wh_area_sub}}</div></div>\n'
        '      <div class="kpi"><div class="kpi-label" data-i18n="kpi_rent_label">Headline rent</div><div class="kpi-value">{{kpi_rent}}</div><div class="kpi-sub">{{kpi_rent_sub}}</div></div>',
    ),
    # --- View tabs (button wraps an <svg> + text; wrap the text in a span) -----
    (
        '<button id="tab-grid" class="active" onclick="switchView(\'grid\')">\n'
        '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>\n'
        '      Grid\n'
        '    </button>\n'
        '    <button id="tab-map" onclick="switchView(\'map\')">\n'
        '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 20L3 17V4l6 3 6-3 6 3v13l-6-3-6 3z"/><line x1="9" y1="7" x2="9" y2="20"/><line x1="15" y1="4" x2="15" y2="17"/></svg>\n'
        '      Map\n'
        '    </button>',
        '<button id="tab-grid" class="active" onclick="switchView(\'grid\')">\n'
        '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>\n'
        '      <span data-i18n="tab_grid">Grid</span>\n'
        '    </button>\n'
        '    <button id="tab-map" onclick="switchView(\'map\')">\n'
        '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 20L3 17V4l6 3 6-3 6 3v13l-6-3-6 3z"/><line x1="9" y1="7" x2="9" y2="20"/><line x1="15" y1="4" x2="15" y2="17"/></svg>\n'
        '      <span data-i18n="tab_map">Map</span>\n'
        '    </button>',
    ),
    # --- Toolbar / filters (labels, search placeholder, select default options,
    #     the size label which has a trailing &nbsp;<span> -> wrap the text) -----
    (
        '<label class="field-label" for="f-search">Search</label>\n'
        '      <input type="search" id="f-search" placeholder="Park, developer, city…" autocomplete="off">',
        '<label class="field-label" for="f-search" data-i18n="filter_search_label">Search</label>\n'
        '      <input type="search" id="f-search" placeholder="Park, developer, city…" data-i18n-ph="filter_search_ph" autocomplete="off">',
    ),
    (
        '<label class="field-label" for="f-country">Country</label>\n'
        '      <select id="f-country"><option value="">All countries</option></select>',
        '<label class="field-label" for="f-country" data-i18n="filter_country_label">Country</label>\n'
        '      <select id="f-country"><option value="" data-i18n="filter_country_all">All countries</option></select>',
    ),
    (
        '<label class="field-label" for="f-city">City</label>\n'
        '      <select id="f-city"><option value="">All cities</option></select>',
        '<label class="field-label" for="f-city" data-i18n="filter_city_label">City</label>\n'
        '      <select id="f-city"><option value="" data-i18n="filter_city_all">All cities</option></select>',
    ),
    (
        '<label class="field-label" for="f-dev">Developer</label>\n'
        '      <select id="f-dev"><option value="">All developers</option></select>',
        '<label class="field-label" for="f-dev" data-i18n="filter_dev_label">Developer</label>\n'
        '      <select id="f-dev"><option value="" data-i18n="filter_dev_all">All developers</option></select>',
    ),
    (
        '<label class="field-label" for="f-size">Min warehouse area &nbsp;<span id="f-size-val" class="range-value"></span></label>',
        '<label class="field-label" for="f-size"><span data-i18n="filter_size_label">Min warehouse area</span> &nbsp;<span id="f-size-val" class="range-value"></span></label>',
    ),
    (
        '<button id="f-reset" class="btn ghost">Reset</button>',
        '<button id="f-reset" class="btn ghost" data-i18n="filter_reset">Reset</button>',
    ),
    # --- Result-meta + sort (count has a leading <strong>; wrap the text node;
    #     each <option> gets data-i18n directly) -------------------------------
    (
        '<div class="count"><strong id="count-n">17</strong>properties shown</div>\n'
        '    <div class="sort-wrap">\n'
        '      <label for="sort" class="field-label" style="margin:0">Sort</label>\n'
        '      <select id="sort">\n'
        '        <option value="id">Recommended order</option>\n'
        '        <option value="size-desc">Warehouse area (largest)</option>\n'
        '        <option value="size-asc">Warehouse area (smallest)</option>\n'
        '        <option value="rent-asc">Rent (lowest)</option>\n'
        '        <option value="rent-desc">Rent (highest)</option>\n'
        '        <option value="city">City (A–Z)</option>\n'
        '        <option value="dev">Developer (A–Z)</option>\n'
        '      </select>',
        '<div class="count"><strong id="count-n">17</strong><span data-i18n="result_count_suffix">properties shown</span></div>\n'
        '    <div class="sort-wrap">\n'
        '      <label for="sort" class="field-label" style="margin:0" data-i18n="sort_label">Sort</label>\n'
        '      <select id="sort">\n'
        '        <option value="id" data-i18n="sort_recommended">Recommended order</option>\n'
        '        <option value="size-desc" data-i18n="sort_size_desc">Warehouse area (largest)</option>\n'
        '        <option value="size-asc" data-i18n="sort_size_asc">Warehouse area (smallest)</option>\n'
        '        <option value="rent-asc" data-i18n="sort_rent_asc">Rent (lowest)</option>\n'
        '        <option value="rent-desc" data-i18n="sort_rent_desc">Rent (highest)</option>\n'
        '        <option value="city" data-i18n="sort_city">City (A–Z)</option>\n'
        '        <option value="dev" data-i18n="sort_dev">Developer (A–Z)</option>\n'
        '      </select>',
    ),
    # --- Empty state ---------------------------------------------------------
    (
        '<h3>No properties match your filters</h3>\n'
        '      <p>Try widening the warehouse-area range or clearing a filter.</p>',
        '<h3 data-i18n="empty_title">No properties match your filters</h3>\n'
        '      <p data-i18n="empty_body">Try widening the warehouse-area range or clearing a filter.</p>',
    ),
    # --- Map legend + isochrone controls (legend-title has a trailing
    #     <span id="legend-mode">; wrap the "Layers" text) --------------------
    (
        '<div class="legend-title">Layers <span id="legend-mode"',
        '<div class="legend-title"><span data-i18n="legend_layers">Layers</span> <span id="legend-mode"',
    ),
    (
        '<div class="label">Drive-time rings around focused property</div>\n'
        '            <div class="iso-options">\n'
        '              <button data-iso="0" class="active">Off</button>\n'
        '              <button data-iso="30">30 min</button>\n'
        '              <button data-iso="60">60 min</button>\n'
        '              <button data-iso="both">Both</button>\n'
        '            </div>\n'
        '            <div class="dist-caveat" style="margin-top:4px">Rings show estimated reach at ~75 km/h motorway average with 1.25× winding factor. Actual routed drive times will vary.</div>',
        '<div class="label" data-i18n="iso_label">Drive-time rings around focused property</div>\n'
        '            <div class="iso-options">\n'
        '              <button data-iso="0" class="active" data-i18n="iso_off">Off</button>\n'
        '              <button data-iso="30" data-i18n="iso_30">30 min</button>\n'
        '              <button data-iso="60" data-i18n="iso_60">60 min</button>\n'
        '              <button data-iso="both" data-i18n="iso_both">Both</button>\n'
        '            </div>\n'
        '            <div class="dist-caveat" style="margin-top:4px" data-i18n="iso_caveat">Rings show estimated reach at ~75 km/h motorway average with 1.25× winding factor. Actual routed drive times will vary.</div>',
    ),
    # --- Compare tray --------------------------------------------------------
    (
        '<button class="btn ghost" id="tray-clear" style="color:#fff;border-color:rgba(255,255,255,.3)">Clear</button>\n'
        '    <button class="btn accent" id="tray-open">Compare</button>',
        '<button class="btn ghost" id="tray-clear" style="color:#fff;border-color:rgba(255,255,255,.3)" data-i18n="tray_clear">Clear</button>\n'
        '    <button class="btn accent" id="tray-open" data-i18n="tray_compare">Compare</button>',
    ),
    # --- Lightbox aria-labels (data-i18n-al; the glyphs ×/‹/› stay as content) ---
    (
        '<div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer">\n'
        '  <button class="lb-close" id="lb-close" aria-label="Close">×</button>\n'
        '  <button class="lb-nav lb-prev" id="lb-prev" aria-label="Previous photo">‹</button>\n'
        '  <img class="lb-img" id="lb-img" alt="">\n'
        '  <button class="lb-nav lb-next" id="lb-next" aria-label="Next photo">›</button>',
        '<div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer" data-i18n-al="lb_photo_viewer">\n'
        '  <button class="lb-close" id="lb-close" aria-label="Close" data-i18n-al="a11y_close">×</button>\n'
        '  <button class="lb-nav lb-prev" id="lb-prev" aria-label="Previous photo" data-i18n-al="a11y_prev_photo">‹</button>\n'
        '  <img class="lb-img" id="lb-img" alt="">\n'
        '  <button class="lb-nav lb-next" id="lb-next" aria-label="Next photo" data-i18n-al="a11y_next_photo">›</button>',
    ),
    # --- Footer disclaimer ---------------------------------------------------
    (
        '<div class="disclaimer">All information provided by CBRE in this document is subject to change without notice. Rent levels, availability, technical specifications, coordinates and timing are indicative, based on landlord-provided data, and subject to negotiation. Drive-time estimates are calculated from great-circle distance with a 1.25× road winding factor at a 75 km/h motorway average and are for orientation only. Not for public distribution.</div>',
        '<div class="disclaimer" data-i18n="footer_disclaimer">All information provided by CBRE in this document is subject to change without notice. Rent levels, availability, technical specifications, coordinates and timing are indicative, based on landlord-provided data, and subject to negotiation. Drive-time estimates are calculated from great-circle distance with a 1.25× road winding factor at a 75 km/h motorway average and are for orientation only. Not for public distribution.</div>',
    ),
]

# 4. JS-GENERATED chrome -> T('KEY') (or ${T('KEY')} inside template literals).
#    One patch per unique enclosing construct; enough context to be unique.
JS_PATCHES = [
    # DIST_LABEL / DIST_BADGE objects (whole object)
    (
        'const DIST_LABEL = { est:"est.", car:"car", hgv:"HGV" };\n'
        'const DIST_BADGE = { est:"Straight-line estimates - not routed", car:"Car-routed drive times (OSRM)", hgv:"HGV / truck-routed drive times (openrouteservice)" };',
        'const DIST_LABEL = { est:T("dist_label_est"), car:T("dist_label_car"), hgv:T("dist_label_hgv") };\n'
        'const DIST_BADGE = { est:T("dist_badge_est"), car:T("dist_badge_car"), hgv:T("dist_badge_hgv") };',
    ),
    # fmtMin " min" unit (h/m kept verbatim)
    (
        '  if(min < 60) return min + " min";\n',
        '  if(min < 60) return min + T("unit_min");\n',
    ),
    # populateFilters: poiCats labels (whole array)
    (
        '  const poiCats = [\n'
        '    {t:"port", label:"Seaports"},\n'
        '    {t:"rail", label:"Rail terminals"},\n'
        '    {t:"air",  label:"Airports"},\n'
        '    {t:"border", label:"Border crossings"},\n'
        '    {t:"city", label:"Major cities"},\n'
        '  ];',
        '  const poiCats = [\n'
        '    {t:"port", label:T("poi_port")},\n'
        '    {t:"rail", label:T("poi_rail")},\n'
        '    {t:"air",  label:T("poi_air")},\n'
        '    {t:"border", label:T("poi_border")},\n'
        '    {t:"city", label:T("poi_city")},\n'
        '  ];',
    ),
    # populateFilters: "Property locations" legend label
    (
        '<span style="flex:1">Property locations</span>',
        '<span style="flex:1">${T("legend_property_locations")}</span>',
    ),
    # cardHTML: carousel nav aria-labels (shared a11y_* keys)
    (
        '<button class="cm-nav cm-prev" aria-label="Previous photo" onclick="event.stopPropagation();cardNav(${p.id},-1,this)">‹</button><button class="cm-nav cm-next" aria-label="Next photo" onclick="event.stopPropagation();cardNav(${p.id},1,this)">›</button>',
        '<button class="cm-nav cm-prev" aria-label="${T(\'a11y_prev_photo\')}" onclick="event.stopPropagation();cardNav(${p.id},-1,this)">‹</button><button class="cm-nav cm-next" aria-label="${T(\'a11y_next_photo\')}" onclick="event.stopPropagation();cardNav(${p.id},1,this)">›</button>',
    ),
    # cardHTML: spec labels + Compare + View details
    (
        '        Compare\n'
        '      </label>',
        '        ${T("card_compare")}\n'
        '      </label>',
    ),
    # detailHTML modal hero: carousel nav aria-labels (shared a11y_* keys)
    (
        '<button class="cm-nav cm-prev" id="modal-prev" aria-label="Previous photo">‹</button><button class="cm-nav cm-next" id="modal-next" aria-label="Next photo">›</button>',
        '<button class="cm-nav cm-prev" id="modal-prev" aria-label="${T(\'a11y_prev_photo\')}">‹</button><button class="cm-nav cm-next" id="modal-next" aria-label="${T(\'a11y_next_photo\')}">›</button>',
    ),
    (
        '<div class="spec"><div class="spec-k">Warehouse</div><div class="spec-v">${fmt(p.warehouseArea)} ${AREA_UNIT}</div></div>\n'
        '        <div class="spec"><div class="spec-k">Clear height</div><div class="spec-v">${p.clearHeight}</div></div>\n'
        '        <div class="spec"><div class="spec-k">Status</div><div class="spec-v small">${p.status}</div></div>\n'
        '        <div class="spec"><div class="spec-k">Early access</div><div class="spec-v">${p.earlyAccess}</div></div>',
        '<div class="spec"><div class="spec-k">${T("row_warehouse")}</div><div class="spec-v">${fmt(p.warehouseArea)} ${AREA_UNIT}</div></div>\n'
        '        <div class="spec"><div class="spec-k">${T("row_clear_height")}</div><div class="spec-v">${p.clearHeight}</div></div>\n'
        '        <div class="spec"><div class="spec-k">${T("row_status")}</div><div class="spec-v small">${p.status}</div></div>\n'
        '        <div class="spec"><div class="spec-k">${T("row_early_access")}</div><div class="spec-v">${p.earlyAccess}</div></div>',
    ),
    (
        '<button class="view-btn" onclick="openModal(${p.id})">View details <span class="arrow">→</span></button>',
        '<button class="view-btn" onclick="openModal(${p.id})">${T("card_view_details")} <span class="arrow">→</span></button>',
    ),
    # toggleCompare alert
    (
        'alert("You can compare up to 4 properties at a time.");',
        'alert(T("card_alert_max_compare"));',
    ),
    # updateTray: Remove aria-label
    (
        '<button onclick="toggleCompare(${id}, false)" aria-label="Remove">×</button>',
        '<button onclick="toggleCompare(${id}, false)" aria-label="${T(\'tray_remove\')}">×</button>',
    ),
    # initMap: layer control labels (the map-popup pair also uses these keys)
    (
        'L.control.layers({ "Streets": streetsLayer, "Satellite": satelliteLayer }, null, { position: \'topright\', collapsed: false }).addTo(map);',
        'L.control.layers({ [T("map_layer_streets")]: streetsLayer, [T("map_layer_satellite")]: satelliteLayer }, null, { position: \'topright\', collapsed: false }).addTo(map);',
    ),
    # propPopupHTML: View details
    (
        '<a href="#" class="popup-btn" onclick="event.preventDefault();openModal(${p.id})">View details</a>',
        '<a href="#" class="popup-btn" onclick="event.preventDefault();openModal(${p.id})">${T("map_view_details")}</a>',
    ),
    # renderIsochrones ring tooltips (the main-map " reach (est.)" labels keyed by ring)
    (
        '  if(state.iso === "30" || state.iso === "both") rings.push({ r: 30000, color: "#17E88F", label: "30 min" });\n'
        '  if(state.iso === "60" || state.iso === "both") rings.push({ r: 60000, color: "#003F2D", label: "60 min" });',
        '  if(state.iso === "30" || state.iso === "both") rings.push({ r: 30000, color: "#17E88F", label: T("iso_30"), tip: T("iso_ring_30_tooltip") });\n'
        '  if(state.iso === "60" || state.iso === "both") rings.push({ r: 60000, color: "#003F2D", label: T("iso_60"), tip: T("iso_ring_60_tooltip") });',
    ),
    (
        '    c.bindTooltip(ring.label + " reach (est.)", { permanent: false });',
        '    c.bindTooltip(ring.tip || (ring.label + " reach (est.)"), { permanent: false });',
    ),
    # computeAndDrawIsochrones: the modal real-isochrone tooltips
    (
        '    pg60.bindTooltip("60 min drive reach (real road network)", { sticky:true });',
        '    pg60.bindTooltip(T("iso_ring_60_real"), { sticky:true });',
    ),
    (
        '    pg30.bindTooltip("30 min drive reach (real road network)", { sticky:true });',
        '    pg30.bindTooltip(T("iso_ring_30_real"), { sticky:true });',
    ),
    # computeAndDrawIsochrones: the modal-map caveat (real-rings form)
    (
        'caveat.innerHTML = `Coordinates: ${typeof p.lat === "number" ? p.lat.toFixed(5) + ", " + p.lng.toFixed(5) : "not yet located (see Gaps Report)"}. <span style="color:var(--brand);font-weight:500">● Green and dark polygons show real 30 min and 60 min drive-time reach</span> computed from the OSRM road network. Use the top-right control to switch to satellite.`;',
        'caveat.innerHTML = `${T("coords_prefix")}: ${typeof p.lat === "number" ? p.lat.toFixed(5) + ", " + p.lng.toFixed(5) : T("coords_not_located")}. <span style="color:var(--brand);font-weight:500">${T("coords_rings_real")}</span> ${T("coords_rings_real_suffix")}`;',
    ),
    # detailHTML: the row(...) TBC display label + catMeta object
    (
        '    ? `<div class="spec"><div class="spec-k">${k}</div><div class="spec-v" style="color:var(--muted)">TBC</div></div>`',
        '    ? `<div class="spec"><div class="spec-k">${k}</div><div class="spec-v" style="color:var(--muted)">${T("val_tbc")}</div></div>`',
    ),
    (
        'const catMeta = { city:"Major cities", border:"Border crossings", air:"Airports", rail:"Rail terminals", port:"Seaports" };',
        'const catMeta = { city:T("poi_city"), border:T("poi_border"), air:T("poi_air"), rail:T("poi_rail"), port:T("poi_port") };',
    ),
    # detailHTML: distStatusHtml (the OSRM status strings). The hgv/car LEAD clause keeps
    # its brand-green bold span (v18 behaviour) - emitted at the call site (mirrors the
    # coords_rings_real pattern) so the translatable strings stay markup-free. The est
    # branch had no span in v18 - left as a single key.
    (
        '    ? (DIST_MODE === "hgv"\n'
        '        ? `<span style="color:var(--brand);font-weight:500">● HGV / truck-routed distances from openrouteservice.</span> Distances reflect the actual road network for trucks. Border wait times not included.`\n'
        '        : `<span style="color:var(--brand);font-weight:500">● Car-routed distances from OSRM.</span> Distances reflect the actual road network. Truck/HGV times are not modelled; border wait times not included.`)\n'
        '    : `Distances shown as great-circle estimates. Fetching live car-routed drive times from OSRM (truck/HGV times are not modelled)…`;',
        '    ? (DIST_MODE === "hgv"\n'
        '        ? `<span style="color:var(--brand);font-weight:500">${T(\'dist_status_hgv_lead\')}</span> ${T(\'dist_status_hgv_rest\')}`\n'
        '        : `<span style="color:var(--brand);font-weight:500">${T(\'dist_status_car_lead\')}</span> ${T(\'dist_status_car_rest\')}`)\n'
        '    : T("dist_status_est");',
    ),
    # detailHTML modal hero: image toggle labels
    (
        '${p.plan ? \'<div class="image-toggle"> <button class="active" data-view="photo">Aerial / Render</button> <button data-view="plan">Site Plan</button> </div>\' : \'\'}',
        '${p.plan ? `<div class="image-toggle"> <button class="active" data-view="photo">${T("img_toggle_photo")}</button> <button data-view="plan">${T("img_toggle_plan")}</button> </div>` : \'\'}',
    ),
    # detailHTML modal head: "Early access" prefix + "Open in Google Maps"
    (
        '<span>Early access ${p.earlyAccess}</span>',
        '<span>${T("modal_early_access_prefix")} ${p.earlyAccess}</span>',
    ),
    (
        '<a class="map-link" href="${mapHref}" target="_blank" rel="noopener">Open in Google Maps ↗</a>',
        '<a class="map-link" href="${mapHref}" target="_blank" rel="noopener">${T("modal_open_maps")}</a>',
    ),
    # detailHTML: approx-note
    (
        '<div class="approx-note">Coordinates are approximate — exact site location to be confirmed by developer.</div>',
        '<div class="approx-note">${T("modal_approx_note")}</div>',
    ),
    # detailHTML: Availability & Site section title + its row() labels
    (
        '<h3 class="section-title">Availability &amp; Site</h3>',
        '<h3 class="section-title">${T("sec_availability")}</h3>',
    ),
    (
        "        row('Total GLA', glaStr(p), 'warehouseArea'),\n"
        "        row('Warehouse area', fmt(p.warehouseArea) + ' ' + AREA_UNIT, 'warehouseArea'),\n"
        "        row('Office area', p.officeArea, 'officeArea'),\n"
        "        row('Plot area', p.plotArea ? fmt(p.plotArea) + ' ' + AREA_UNIT : '—', 'plotArea'),\n"
        "        row('Divisible from', p.divisibleFrom, 'divisibleFrom'),\n"
        "        row('Expansion in building', p.expansionBuilding, 'expansionBuilding'),\n"
        "        row('Expansion in park', p.expansionPark, 'expansionPark'),\n"
        "        row('Landlord', p.landlord, 'landlord'),\n"
        "        row('Property status', p.status, 'status'),\n"
        "        row('Permitting', p.permitting, 'permitting'),\n"
        "        row('Early access date', p.earlyAccess, 'earlyAccess'),",
        "        row(T('row_total_gla'), glaStr(p), 'warehouseArea'),\n"
        "        row(T('row_warehouse_area'), fmt(p.warehouseArea) + ' ' + AREA_UNIT, 'warehouseArea'),\n"
        "        row(T('row_office_area'), p.officeArea, 'officeArea'),\n"
        "        row(T('row_plot_area'), p.plotArea ? fmt(p.plotArea) + ' ' + AREA_UNIT : '—', 'plotArea'),\n"
        "        row(T('row_divisible_from'), p.divisibleFrom, 'divisibleFrom'),\n"
        "        row(T('row_expansion_building'), p.expansionBuilding, 'expansionBuilding'),\n"
        "        row(T('row_expansion_park'), p.expansionPark, 'expansionPark'),\n"
        "        row(T('row_landlord'), p.landlord, 'landlord'),\n"
        "        row(T('row_property_status'), p.status, 'status'),\n"
        "        row(T('row_permitting'), p.permitting, 'permitting'),\n"
        "        row(T('row_early_access_date'), p.earlyAccess, 'earlyAccess'),",
    ),
    # detailHTML: Technical Specification section title + rows
    (
        '<h3 class="section-title">Technical Specification</h3>',
        '<h3 class="section-title">${T("sec_technical")}</h3>',
    ),
    (
        "        row('Clear height', p.clearHeight, 'clearHeight'),\n"
        "        row('Floor load', p.floorLoad, 'floorLoad'),\n"
        "        row('Sprinklers', p.sprinklers, 'sprinklers'),\n"
        "        row('Loading docks', p.loadingDocks, 'loadingDocks'),\n"
        "        row('Overhead doors', p.overheadDoors, 'overheadDoors'),\n"
        "        row('Electricity', p.electricity, 'electricity'),\n"
        "        row('Truck parking', p.truckParking, 'truckParking'),\n"
        "        row('Car parking', p.carParking, 'carParking'),",
        "        row(T('row_clear_height'), p.clearHeight, 'clearHeight'),\n"
        "        row(T('row_floor_load'), p.floorLoad, 'floorLoad'),\n"
        "        row(T('row_sprinklers'), p.sprinklers, 'sprinklers'),\n"
        "        row(T('row_loading_docks'), p.loadingDocks, 'loadingDocks'),\n"
        "        row(T('row_overhead_doors'), p.overheadDoors, 'overheadDoors'),\n"
        "        row(T('row_electricity'), p.electricity, 'electricity'),\n"
        "        row(T('row_truck_parking'), p.truckParking, 'truckParking'),\n"
        "        row(T('row_car_parking'), p.carParking, 'carParking'),",
    ),
    # detailHTML: Commercial Terms section title + rows
    (
        '<h3 class="section-title">Commercial Terms (Headline)</h3>',
        '<h3 class="section-title">${T("sec_commercial")}</h3>',
    ),
    (
        "        row('Warehouse rent', p.warehouseRent, 'warehouseRent'),\n"
        "        row('Warehouse rent (monthly)', rentMonthlyStr(p) || '—', 'warehouseRent'),\n"
        "        row('Total annual rent', totalRentStr(p,false) || '—', 'warehouseRent'),\n"
        "        row('Total monthly rent', totalRentStr(p,true) || '—', 'warehouseRent'),\n"
        "        row('Office rent', p.officeRent, 'officeRent'),\n"
        "        row('Service charge', p.serviceCharge, 'serviceCharge'),\n"
        "        row('Land price', p.landPrice, 'landPrice'),\n"
        "        p.leaseTerm ? row('Lease term', p.leaseTerm, 'leaseTerm') : '',\n"
        "        p.rentFree ? row('Rent-free period', p.rentFree, 'rentFree') : '',\n"
        "        p.incentives && p.incentives !== 'Not mentioned in first offer' ? row('Incentives', p.incentives, 'incentives') : '',\n"
        "        p.reit ? row('REIT', p.reit, 'reit') : '',",
        "        row(T('row_warehouse_rent'), p.warehouseRent, 'warehouseRent'),\n"
        "        row(T('row_warehouse_rent_monthly'), rentMonthlyStr(p) || '—', 'warehouseRent'),\n"
        "        row(T('row_total_annual_rent'), totalRentStr(p,false) || '—', 'warehouseRent'),\n"
        "        row(T('row_total_monthly_rent'), totalRentStr(p,true) || '—', 'warehouseRent'),\n"
        "        row(T('row_office_rent'), p.officeRent, 'officeRent'),\n"
        "        row(T('row_service_charge'), p.serviceCharge, 'serviceCharge'),\n"
        "        row(T('row_land_price'), p.landPrice, 'landPrice'),\n"
        "        p.leaseTerm ? row(T('row_lease_term'), p.leaseTerm, 'leaseTerm') : '',\n"
        "        p.rentFree ? row(T('row_rent_free'), p.rentFree, 'rentFree') : '',\n"
        "        p.incentives && p.incentives !== 'Not mentioned in first offer' ? row(T('row_incentives'), p.incentives, 'incentives') : '',\n"
        "        p.reit ? row(T('row_reit'), p.reit, 'reit') : '',",
    ),
    # detailHTML: Location & Reach section title
    (
        '<h3 class="section-title">Location &amp; Reach</h3>',
        '<h3 class="section-title">${T("sec_location")}</h3>',
    ),
    # detailHTML: the modal-map caveat (estimated-rings initial form)
    (
        '<div class="dist-caveat" id="modal-map-caveat" style="margin-top:8px">Coordinates: ${typeof p.lat === "number" ? p.lat.toFixed(5) + ", " + p.lng.toFixed(5) : "not yet located (see Gaps Report)"}. Green ring ≈ 30 min reach, dark ring ≈ 60 min reach (estimated — fetching real isochrones…). Use the top-right control to switch to satellite.</div>',
        '<div class="dist-caveat" id="modal-map-caveat" style="margin-top:8px">${T("coords_prefix")}: ${typeof p.lat === "number" ? p.lat.toFixed(5) + ", " + p.lng.toFixed(5) : T("coords_not_located")}. ${T("coords_rings_est")}</div>',
    ),
    # detailHTML: distance table headers (Drive time already suffixed with DIST_LABEL)
    (
        '<thead><tr><th>Destination</th><th style="text-align:right">Distance</th><th style="text-align:right">Drive time (${DIST_LABEL[DIST_MODE]||\'est.\'})</th></tr></thead>',
        '<thead><tr><th>${T("dist_th_destination")}</th><th style="text-align:right">${T("dist_th_distance")}</th><th style="text-align:right">${T("dist_th_drive_time")} (${DIST_LABEL[DIST_MODE]||\'est.\'})</th></tr></thead>',
    ),
    # detailHTML: Workforce & Region section title
    (
        '<h3 class="section-title">Workforce &amp; Region</h3>',
        '<h3 class="section-title">${T("sec_workforce")}</h3>',
    ),
    # detailHTML: district panel labels
    (
        '<div class="district-label">District-level labour market</div>',
        '<div class="district-label">${T("wf_district_label")}</div>',
    ),
    (
        '<div class="metric-label">Unemployment · ${rStr(dist.asOf)}</div>',
        '<div class="metric-label">${T("wf_unemployment")} · ${rStr(dist.asOf)}</div>',
    ),
    (
        "<span class=\"apv-chip\">${dist.applicantsPerVacancy} applicants / vacancy</span>\n"
        "            <span class=\"apv-meaning\">${dist.applicantsPerVacancy < 3 ? 'Tight labour market' : dist.applicantsPerVacancy < 8 ? 'Balanced' : 'Deep labour pool available'}</span>",
        "<span class=\"apv-chip\">${dist.applicantsPerVacancy} ${T('wf_applicants_suffix')}</span>\n"
        "            <span class=\"apv-meaning\">${dist.applicantsPerVacancy < 3 ? T('wf_market_tight') : dist.applicantsPerVacancy < 8 ? T('wf_market_balanced') : T('wf_market_deep')}</span>",
    ),
    # detailHTML: region stat tiles (whole block of stat(...) calls)
    (
        "          ${stat('Regional unemployment', (typeof reg.unemployment === 'number') ? rNum(reg.unemployment) : null, '%', reg.unemploymentAsOf)}\n"
        "          ${stat('Population', (typeof reg.population === 'number') ? rK(reg.population) : null, '', reg.populationAsOf ? `As of ${reg.populationAsOf}` : '')}\n"
        "          ${stat('Labour force', (typeof reg.labourForce === 'number') ? rK(reg.labourForce) : null, '', 'Economically active')}\n"
        "          ${stat('Employment rate', (typeof reg.employmentRate === 'number') ? rNum(reg.employmentRate) : null, '%', 'Age 20–64')}\n"
        "          ${stat('GDP per capita', (typeof reg.gdpPpsEu === 'number') ? rNum(reg.gdpPpsEu) : null, '% EU27', reg.gdpPpsAsOf ? `PPS, ${reg.gdpPpsAsOf}` : 'PPS')}\n"
        "          ${stat('GDP (nominal)', gdp, '', reg.gdpAsOf || baselineAsOf)}\n"
        "          ${stat('Manufacturing employment', (typeof reg.emplManufacturing === 'number') ? rK(reg.emplManufacturing) : null, '', 'Persons employed')}\n"
        "          ${stat('Transport &amp; storage employment', (typeof reg.emplTransportStorage === 'number') ? rK(reg.emplTransportStorage) : null, '', 'Persons employed')}\n"
        "          ${stat('Logistics employment share', (logiShare !== null) ? rNum(logiShare) : null, '%', 'Transport &amp; storage share of the labour force')}",
        "          ${stat(T('wf_regional_unemployment'), (typeof reg.unemployment === 'number') ? rNum(reg.unemployment) : null, T('wf_unit_pct'), reg.unemploymentAsOf)}\n"
        "          ${stat(T('wf_population'), (typeof reg.population === 'number') ? rK(reg.population) : null, '', reg.populationAsOf ? `${T('wf_as_of_prefix')} ${reg.populationAsOf}` : '')}\n"
        "          ${stat(T('wf_labour_force'), (typeof reg.labourForce === 'number') ? rK(reg.labourForce) : null, '', T('wf_economically_active'))}\n"
        "          ${stat(T('wf_employment_rate'), (typeof reg.employmentRate === 'number') ? rNum(reg.employmentRate) : null, T('wf_unit_pct'), T('wf_age_20_64'))}\n"
        "          ${stat(T('wf_gdp_per_capita'), (typeof reg.gdpPpsEu === 'number') ? rNum(reg.gdpPpsEu) : null, T('wf_unit_pct_eu27'), reg.gdpPpsAsOf ? `${T('wf_pps_prefix')}, ${reg.gdpPpsAsOf}` : T('wf_pps_prefix'))}\n"
        "          ${stat(T('wf_gdp_nominal'), gdp, '', reg.gdpAsOf || baselineAsOf)}\n"
        "          ${stat(T('wf_manufacturing_employment'), (typeof reg.emplManufacturing === 'number') ? rK(reg.emplManufacturing) : null, '', T('wf_persons_employed'))}\n"
        "          ${stat(T('wf_transport_storage_employment'), (typeof reg.emplTransportStorage === 'number') ? rK(reg.emplTransportStorage) : null, '', T('wf_persons_employed'))}\n"
        "          ${stat(T('wf_logistics_share'), (logiShare !== null) ? rNum(logiShare) : null, T('wf_unit_pct'), T('wf_logistics_sub'))}",
    ),
    # detailHTML: region sources label
    (
        '<div class="region-sources"><strong>Sources:</strong> ${reg.sources}</div>',
        '<div class="region-sources"><strong>${T("wf_sources")}</strong> ${reg.sources}</div>',
    ),
    # detailHTML: empty-workforce sentence
    (
        '` : `<p class="desc" style="color:var(--muted)">Workforce and regional labour data not yet added for this option — see the Gaps Report.</p>`}',
        '` : `<p class="desc" style="color:var(--muted)">${T("wf_empty")}</p>`}',
    ),
    # initModalMap: not-located note + layer control
    (
        "    el.innerHTML = '<p class=\"desc\" style=\"padding:12px;color:var(--muted)\">Location not yet confirmed - see the Gaps Report.</p>';",
        "    el.innerHTML = `<p class=\"desc\" style=\"padding:12px;color:var(--muted)\">${T('map_not_confirmed')}</p>`;",
    ),
    (
        'L.control.layers({ "Streets": mStreets, "Satellite": mSatellite }, null, { position: \'topright\', collapsed: false }).addTo(miniMap);',
        'L.control.layers({ [T("map_layer_streets")]: mStreets, [T("map_layer_satellite")]: mSatellite }, null, { position: \'topright\', collapsed: false }).addTo(miniMap);',
    ),
    # openCompare alert
    (
        'alert("Select at least two properties to compare.");',
        'alert(T("cmp_alert_min_two"));',
    ),
    # compareHTML: the rows array labels (whole array)
    (
        "    ['Country', p=>p.country, 'country'],\n"
        "    ['City', p=>p.city, 'city'],\n"
        "    ['Developer', p=>p.developer, 'developer'],\n"
        "    ['Landlord', p=>p.landlord, 'landlord'],\n"
        "    ['Motorway', p=>p.motorway, 'motorway'],\n"
        "    ['Status', p=>p.status, 'status'],\n"
        "    ['Early access', p=>p.earlyAccess, 'earlyAccess'],\n"
        "    ['Permitting', p=>p.permitting, 'permitting'],\n"
        "    ['Total GLA', p=>glaStr(p), 'warehouseArea'],\n"
        "    ['Warehouse area', p=>fmt(p.warehouseArea)+' '+AREA_UNIT, 'warehouseArea'],\n"
        "    ['Office area', p=>p.officeArea, 'officeArea'],\n"
        "    ['Plot area', p=>p.plotArea ? fmt(p.plotArea)+' '+AREA_UNIT : '—', 'plotArea'],\n"
        "    ['Divisible from', p=>p.divisibleFrom, 'divisibleFrom'],\n"
        "    ['Expansion in building', p=>p.expansionBuilding, 'expansionBuilding'],\n"
        "    ['Expansion in park', p=>p.expansionPark, 'expansionPark'],\n"
        "    ['Clear height', p=>p.clearHeight, 'clearHeight'],\n"
        "    ['Floor load', p=>p.floorLoad, 'floorLoad'],\n"
        "    ['Sprinklers', p=>p.sprinklers, 'sprinklers'],\n"
        "    ['Loading docks', p=>p.loadingDocks, 'loadingDocks'],\n"
        "    ['Overhead doors', p=>p.overheadDoors, 'overheadDoors'],\n"
        "    ['Electricity', p=>p.electricity, 'electricity'],\n"
        "    ['Truck parking', p=>p.truckParking, 'truckParking'],\n"
        "    ['Car parking', p=>p.carParking, 'carParking'],\n"
        "    ['Warehouse rent', p=>p.warehouseRent, 'warehouseRent'],\n"
        "    ['Warehouse rent (monthly)', p=>rentMonthlyStr(p) || '—', 'warehouseRent'],\n"
        "    ['Total annual rent', p=>totalRentStr(p,false) || '—', 'warehouseRent'],\n"
        "    ['Total monthly rent', p=>totalRentStr(p,true) || '—', 'warehouseRent'],\n"
        "    ['Office rent', p=>p.officeRent, 'officeRent'],\n"
        "    ['Service charge', p=>p.serviceCharge, 'serviceCharge'],\n"
        "    ['Lease term', p=>p.leaseTerm || '—', 'leaseTerm'],\n"
        "    ['Rent-free period', p=>p.rentFree || '—', 'rentFree'],\n"
        "    ['Certification', p=>p.breeam || '—', 'breeam'],",
        "    [T('cmp_country'), p=>p.country, 'country'],\n"
        "    [T('cmp_city'), p=>p.city, 'city'],\n"
        "    [T('cmp_developer'), p=>p.developer, 'developer'],\n"
        "    [T('row_landlord'), p=>p.landlord, 'landlord'],\n"
        "    [T('cmp_motorway'), p=>p.motorway, 'motorway'],\n"
        "    [T('cmp_status'), p=>p.status, 'status'],\n"
        "    [T('cmp_early_access'), p=>p.earlyAccess, 'earlyAccess'],\n"
        "    [T('row_permitting'), p=>p.permitting, 'permitting'],\n"
        "    [T('row_total_gla'), p=>glaStr(p), 'warehouseArea'],\n"
        "    [T('row_warehouse_area'), p=>fmt(p.warehouseArea)+' '+AREA_UNIT, 'warehouseArea'],\n"
        "    [T('row_office_area'), p=>p.officeArea, 'officeArea'],\n"
        "    [T('row_plot_area'), p=>p.plotArea ? fmt(p.plotArea)+' '+AREA_UNIT : '—', 'plotArea'],\n"
        "    [T('row_divisible_from'), p=>p.divisibleFrom, 'divisibleFrom'],\n"
        "    [T('row_expansion_building'), p=>p.expansionBuilding, 'expansionBuilding'],\n"
        "    [T('row_expansion_park'), p=>p.expansionPark, 'expansionPark'],\n"
        "    [T('row_clear_height'), p=>p.clearHeight, 'clearHeight'],\n"
        "    [T('row_floor_load'), p=>p.floorLoad, 'floorLoad'],\n"
        "    [T('row_sprinklers'), p=>p.sprinklers, 'sprinklers'],\n"
        "    [T('row_loading_docks'), p=>p.loadingDocks, 'loadingDocks'],\n"
        "    [T('row_overhead_doors'), p=>p.overheadDoors, 'overheadDoors'],\n"
        "    [T('row_electricity'), p=>p.electricity, 'electricity'],\n"
        "    [T('row_truck_parking'), p=>p.truckParking, 'truckParking'],\n"
        "    [T('row_car_parking'), p=>p.carParking, 'carParking'],\n"
        "    [T('row_warehouse_rent'), p=>p.warehouseRent, 'warehouseRent'],\n"
        "    [T('row_warehouse_rent_monthly'), p=>rentMonthlyStr(p) || '—', 'warehouseRent'],\n"
        "    [T('row_total_annual_rent'), p=>totalRentStr(p,false) || '—', 'warehouseRent'],\n"
        "    [T('row_total_monthly_rent'), p=>totalRentStr(p,true) || '—', 'warehouseRent'],\n"
        "    [T('row_office_rent'), p=>p.officeRent, 'officeRent'],\n"
        "    [T('row_service_charge'), p=>p.serviceCharge, 'serviceCharge'],\n"
        "    [T('row_lease_term'), p=>p.leaseTerm || '—', 'leaseTerm'],\n"
        "    [T('row_rent_free'), p=>p.rentFree || '—', 'rentFree'],\n"
        "    [T('cmp_certification'), p=>p.breeam || '—', 'breeam'],",
    ),
    # compareHTML: distRows labels (only the labels change; the fn bodies are DATA)
    (
        "    ['Nearest major city', p=>{ const d = groupedDistances(p).city[0]; if(!d) return 'tbd';",
        "    [T('cmp_nearest_city'), p=>{ const d = groupedDistances(p).city[0]; if(!d) return 'tbd';",
    ),
    (
        "    ['Nearest border', p=>{ const d = groupedDistances(p).border[0]; if(!d) return 'tbd';",
        "    [T('cmp_nearest_border'), p=>{ const d = groupedDistances(p).border[0]; if(!d) return 'tbd';",
    ),
    (
        "    ['Nearest airport', p=>{ const d = groupedDistances(p).air[0]; if(!d) return 'tbd';",
        "    [T('cmp_nearest_airport'), p=>{ const d = groupedDistances(p).air[0]; if(!d) return 'tbd';",
    ),
    (
        "    ['Nearest rail', p=>{ const d = groupedDistances(p).rail[0]; if(!d) return 'tbd';",
        "    [T('cmp_nearest_rail'), p=>{ const d = groupedDistances(p).rail[0]; if(!d) return 'tbd';",
    ),
    (
        "    ['Nearest seaport', p=>{ const d = groupedDistances(p).port[0]; if(!d) return 'tbd';",
        "    [T('cmp_nearest_seaport'), p=>{ const d = groupedDistances(p).port[0]; if(!d) return 'tbd';",
    ),
    # compareHTML: side-by-side header + count + highlight note + Attribute
    (
        '<div class="modal-dev">Side-by-side comparison</div>\n'
        '        <h2 class="modal-title">${items.length} properties compared</h2>\n'
        '        <div class="modal-meta"><span>Largest warehouse and lowest rent highlighted</span></div>',
        '<div class="modal-dev">${T("cmp_side_by_side")}</div>\n'
        '        <h2 class="modal-title">${items.length} ${T("cmp_properties_compared_suffix")}</h2>\n'
        '        <div class="modal-meta"><span>${T("cmp_highlight_note")}</span></div>',
    ),
    (
        '<thead><tr><th style="min-width:170px">Attribute</th>',
        '<thead><tr><th style="min-width:170px">${T("cmp_attribute")}</th>',
    ),
    # compareHTML highlight: the size/rent highlight matched `label` against HARDCODED
    # English literals - broken in every non-EN language (the largest-warehouse / lowest-
    # rent highlight silently vanished once `label` came from T()). Compare against the
    # SAME T('key') the compare rows use. EXACT v18 behaviour preserved: only the per-area
    # 'Warehouse area' row highlights for size; only the two warehouse-rent RATE rows
    # ('Warehouse rent' + 'Warehouse rent (monthly)') highlight for rent - the
    # 'Total annual/monthly rent' rows stay UN-highlighted (we match on the localised LABEL,
    # NOT the shared 'warehouseRent' field key, which would wrongly catch the totals).
    (
        "                if(label==='Warehouse area' && i===minSizeIdx) hl='cmp-highlight';\n"
        "                if((label==='Warehouse rent' || label==='Warehouse rent (monthly)') && i===minRentIdx) hl='cmp-highlight';",
        "                if(label===T('row_warehouse_area') && i===minSizeIdx) hl='cmp-highlight';\n"
        "                if((label===T('row_warehouse_rent') || label===T('row_warehouse_rent_monthly')) && i===minRentIdx) hl='cmp-highlight';",
    ),
    # legend-mode tag object at the end of the script
    (
        'const tag = { est:"(est. drive times)", car:"(car-baked drive times)", hgv:"(HGV-baked drive times)" };',
        'const tag = { est:T("legend_mode_est"), car:T("legend_mode_car"), hgv:T("legend_mode_hgv") };',
    ),
]

# 6. Locale-aware number/region formatting (DATA-safe: reformat separators / render
#    country names from ISO codes; never alter traced figures).
FORMAT_PATCHES = [
    (
        'const fmt = n => (typeof n === "number" && isFinite(n)) ? n.toLocaleString("en-US") : (n == null ? "tbd" : n);',
        'const fmt = n => (typeof n === "number" && isFinite(n)) ? n.toLocaleString(LOCALE) : (n == null ? "tbd" : n);',
    ),
    (
        'return cur + " " + Math.round(v).toLocaleString("en-US") + (monthly ? " / mo" : " / yr");',
        'return cur + " " + Math.round(v).toLocaleString(LOCALE) + (monthly ? " / mo" : " / yr");',
    ),
    (
        'try { const dn = new Intl.DisplayNames(["en"], {type:"region"}); regionName = c => { try { return dn.of(c) || c; } catch(e) { return c; } }; } catch(e) {}',
        'try { const dn = new Intl.DisplayNames([LOCALE], {type:"region"}); regionName = c => { try { return dn.of(c) || c; } catch(e) { return c; } }; } catch(e) {}',
    ),
]

# 2. applyI18n(document) invocation: prepend before the unique populateFilters() call.
APPLY_ANCHOR = "populateFilters();"
APPLY_PREPEND = "applyI18n(document);\n"

# 5. adaptSingleCountryHeader: match the KPI tiles by data-i18n KEY, not textContent
#    (the labels are localised at runtime before this runs).
ADAPT_PATCHES = [
    (
        '      const lbl = ((k.querySelector(".kpi-label") || {}).textContent || "").trim();\n'
        '      if(lbl === "Countries") countriesTile = k;\n'
        '      if(lbl === "Regions") regionsTile = k;',
        '      if(k.querySelector(\'.kpi-label[data-i18n="kpi_countries_label"]\')) countriesTile = k;\n'
        '      if(k.querySelector(\'.kpi-label[data-i18n="kpi_regions_label"]\')) regionsTile = k;',
    ),
]


def _apply_once(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        fail(f"{what}: expected exactly once, found {n}x:\n  {old[:120]!r}")
    return text.replace(old, new)


def patch_template(out_path: str, version_path: str, label: str) -> None:
    """v19 patch-only path: patch the EXISTING frozen template in place to add the
    i18n bootstrap, data-i18n attributes, T('KEY') calls, the applyI18n pass, the
    adaptSingleCountryHeader key-based fix, and the locale-aware formatting; then
    recompute chrome_sha256 and write VERSION. Every patch asserts count == 1."""
    out = Path(out_path)
    if not out.exists():
        fail(f"template to patch not found: {out}")
    text = out.read_text(encoding="utf-8")

    # guard: do not double-patch an already-i18n template
    if "const UI =" in text or "data-i18n" in text:
        fail("template already contains i18n markup (const UI / data-i18n) - patch-only "
             "expects the pre-i18n frozen template; restore assets/dashboard_template.v18.html first")

    # 1. INJECT_BLOCK immediately before the ROUTES line
    text = _apply_once(text, INJECT_BLOCK_ANCHOR, INJECT_BLOCK + INJECT_BLOCK_ANCHOR,
                       "inject i18n bootstrap")
    # 3. static block patches
    for i, (old, new) in enumerate(STATIC_PATCHES):
        text = _apply_once(text, old, new, f"static patch #{i}")
    # 4. JS patches
    for i, (old, new) in enumerate(JS_PATCHES):
        text = _apply_once(text, old, new, f"JS patch #{i}")
    # 2. applyI18n(document) before populateFilters()
    text = _apply_once(text, APPLY_ANCHOR, APPLY_PREPEND + APPLY_ANCHOR,
                       "applyI18n invocation")
    # 5. adaptSingleCountryHeader key-based fix
    for i, (old, new) in enumerate(ADAPT_PATCHES):
        text = _apply_once(text, old, new, f"adaptSingleCountryHeader patch #{i}")
    # 6. format/locale patches
    for i, (old, new) in enumerate(FORMAT_PATCHES):
        text = _apply_once(text, old, new, f"format patch #{i}")

    # the modal-close aria-label "Close" appears EXACTLY twice (detailHTML +
    # compareHTML) with identical markup - replace both (shared a11y_close key).
    mc_old = '<button class="modal-close" onclick="closeModal()" aria-label="Close">×</button>'
    mc_new = '<button class="modal-close" onclick="closeModal()" aria-label="${T(\'a11y_close\')}">×</button>'
    mc_n = text.count(mc_old)
    if mc_n != 2:
        fail(f"modal-close aria-label: expected exactly twice, found {mc_n}x")
    text = text.replace(mc_old, mc_new)

    # v20: the browser-tab <title> was a hardcoded project default ("CEE Logistics
    # Property Shortlist") - point it at the {{doc_title}} config token so the tab label
    # adapts per project + language (build_dashboard derives it from the hero).
    text = _apply_once(
        text,
        "<title>CEE Logistics Property Shortlist — CBRE</title>",
        "<title>{{doc_title}}</title>",
        "doc_title <title> token")

    # invariants: the new tokens present, markers intact, UI/LOCALE consts present
    for tok in ("{{ui_json}}", "{{locale}}", "{{doc_title}}"):
        if tok not in text:
            fail(f"token {tok} missing after patch")
    for marker in DATA_MARKERS.values():
        if marker not in text:
            fail(f"data marker {marker} missing after patch (must stay intact)")
    if "const UI =" not in text or "const LOCALE =" not in text:
        fail("const UI = / const LOCALE = missing after patch")

    out.write_text(text, encoding="utf-8")
    # recompute the sha on the read-back (universal-newline normalised) form so it
    # matches exactly what _common.load_template() hashes at validate-html time.
    readback = out.read_text(encoding="utf-8")
    chrome_sha = hashlib.sha256(readback.encode("utf-8")).hexdigest()
    ver = Path(version_path)
    ver.parent.mkdir(parents=True, exist_ok=True)
    ver.write_text(f"{label}\nchrome_sha256={chrome_sha}\n", encoding="utf-8")

    kb = len(readback.encode("utf-8")) / 1024
    print(f"OK template patched ({label}): {out} ({kb:.0f} KB)")
    print(f"OK version: {label}  chrome_sha256={chrome_sha}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", nargs="?", help="path to a reference dashboard HTML "
                    "(omit with --patch-only)")
    ap.add_argument("--out", default="assets/dashboard_template.html")
    ap.add_argument("--version", default="assets/VERSION")
    ap.add_argument("--label", default="v1")
    ap.add_argument("--patch-only", action="store_true",
                    help="v19+ i18n: PATCH the existing frozen --out template in place "
                         "(assert-exactly-once-or-abort) instead of regenerating from a "
                         "raw reference; recomputes chrome_sha256 and writes VERSION.")
    args = ap.parse_args()

    if args.patch_only:
        patch_template(args.out, args.version, args.label)
        return

    if not args.reference:
        fail("a reference path is required for the v1 regen path (use --patch-only to "
             "patch the existing template instead)")
    ref = Path(args.reference)
    if not ref.exists():
        fail(f"reference not found: {ref}")
    text = ref.read_text(encoding="utf-8")

    text = replace_config(text)
    for old, new in POST_PATCHES.items():
        n = text.count(old)
        if n != 1:
            fail(f"post-patch literal expected exactly once, found {n}x:\n  {old[:80]!r}")
        text = text.replace(old, new)
    text = replace_data_lines(text)

    # markers must now all be present
    for marker in DATA_MARKERS.values():
        if marker not in text:
            fail(f"marker missing after replace: {marker}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    chrome_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ver = Path(args.version)
    ver.parent.mkdir(parents=True, exist_ok=True)
    ver.write_text(f"{args.label}\nchrome_sha256={chrome_sha}\n", encoding="utf-8")

    kb = len(text.encode("utf-8")) / 1024
    print(f"OK template written: {out} ({kb:.0f} KB)")
    print(f"OK version: {args.label}  chrome_sha256={chrome_sha}")
    print(f"tokens: {sorted(set(v.strip('/* ') if v.startswith('/*') else v for v in DATA_MARKERS.values()))}")


if __name__ == "__main__":
    main()
