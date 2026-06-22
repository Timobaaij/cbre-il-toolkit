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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", help="path to a reference dashboard HTML")
    ap.add_argument("--out", default="assets/dashboard_template.html")
    ap.add_argument("--version", default="assets/VERSION")
    ap.add_argument("--label", default="v1")
    args = ap.parse_args()

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
