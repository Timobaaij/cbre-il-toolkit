#!/usr/bin/env python3
# © 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""i18n.py - dashboard CHROME localisation table (Phase 1 + Phase 2 fallback).

The dashboard renders its fixed UI vocabulary ("chrome") in a chosen European
Latin-script language, driven by this deterministic bundled table with per-key
English fallback. DATA (property/developer/region/POI names, figures, dates,
units-in-data, source citations, the canonical 'tbd'/'—' sentinel) is NEVER
translated - only chrome.

How it threads through the build:
  * build_dashboard.render() resolves meta.language -> ui_for(code) (a complete
    dict, EN-filled per key) and meta.locale/BCP47 -> locale_for(), then injects
    them into the template as the {{ui_json}} / {{locale}} tokens.
  * The template's app <script> reads `const UI = {{ui_json}}` and a
    `T(k)=>UI[k]??k` helper; static chrome carries data-i18n* attributes resolved
    once on init by applyI18n(document); JS-generated chrome calls T('KEY').

EN is the AUTHORITATIVE baseline: every key referenced by a data-i18n* attribute
or a T('...') call in the template MUST exist here (evals/i18n_test.py asserts the
template<->EN agreement in both directions). The 11 non-EN bundled languages are
dropped into TABLE from assets/i18n/<code>.json; any missing language/key degrades
gracefully to English (per-key fallback) and still builds + passes validate-html.

Phase 2 adds the SUPPORTED registry: the bundled 12 PLUS the fallback-eligible
European Latin-script languages (Nordic, Baltic, Balkan, Catalan, Galician,
Luxembourgish, ...). A SUPPORTED-but-not-bundled language is translated ONCE in
Cowork (run.py exits 11 with a request manifest), cached in the work dir, and baked
into canonical.meta.ui_overrides by merge.py so render() (and validate-html's re-run
of it) reproduce it from canonical ALONE - byte-stable by construction. is_bundled /
is_supported / needs_fallback / en_sha / load_fallback_cache / ui_for(overrides=)
are the Phase-2 surface; the no-overrides path is byte-identical to Phase 1.

Rules honoured here:
  - No DATA in this table. No key for the 'tbd'/'—' sentinel (it stays verbatim).
    v21: the modal no longer shows a present-but-unknown placeholder - an absent
    field simply omits its row - so there is no 'val_tbc' chrome key any more.
  - Values are free of {{double-brace}} sequences (would trip find_leftover_tokens).
    Single-brace {area}/{unit} placeholders appear ONLY in the two KPI-sub format
    strings, consumed by .format() in Python and never emitted raw.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Phase 2: bump this when the SHAPE/semantics of the EN baseline change in a way that
# should invalidate a cached fallback translation independent of EN's content hash
# (e.g. a key renamed but text kept). Combined with en_sha() to key the work-dir cache.
I18N_SCHEMA_VERSION = "1"

# Authoritative English baseline: EVERY chrome key the template + render JS reads.
# Shared keys: one key when the English text is identical across places.
EN = {
    # --- KPI strip labels + the two STATIC subs -----------------------------
    "kpi_properties_label": "Properties",
    "kpi_countries_label": "Countries",
    "kpi_regions_label": "Regions",
    "kpi_developers_label": "Developers",
    "kpi_wh_area_label": "Warehouse area",
    "kpi_rent_label": "Headline rent",
    "kpi_properties_sub": "Longlist",
    "kpi_developers_sub": "Major landlords",
    # KPI sub format strings (consumed by compute_kpis via .format(); the regions
    # sub is a plain phrase). The {area}/{unit} placeholders are single-brace.
    "kpi_wh_area_sub_fmt": "{area} per building",
    "kpi_rent_sub_fmt": "per {unit} / year",
    "kpi_regions_sub": "Under consideration",

    # --- View tabs ----------------------------------------------------------
    "tab_grid": "Grid",
    "tab_map": "Map",

    # --- Toolbar / filters --------------------------------------------------
    "filter_search_label": "Search",
    "filter_search_ph": "Park, developer, city…",
    "filter_country_label": "Country",
    "filter_country_all": "All countries",
    "filter_city_label": "City",
    "filter_city_all": "All cities",
    "filter_dev_label": "Developer",
    "filter_dev_all": "All developers",
    "filter_size_label": "Min warehouse area",
    "filter_reset": "Reset",

    # --- Result meta + sort -------------------------------------------------
    "result_count_suffix": "properties shown",
    "sort_label": "Sort",
    "sort_recommended": "Recommended order",
    "sort_size_desc": "Warehouse area (largest)",
    "sort_size_asc": "Warehouse area (smallest)",
    "sort_rent_asc": "Rent (lowest)",
    "sort_rent_desc": "Rent (highest)",
    "sort_city": "City (A–Z)",
    "sort_dev": "Developer (A–Z)",

    # --- Empty state --------------------------------------------------------
    "empty_title": "No properties match your filters",
    "empty_body": "Try widening the warehouse-area range or clearing a filter.",

    # --- Map legend + isochrone controls ------------------------------------
    "legend_layers": "Layers",
    "legend_property_locations": "Property locations",
    "iso_label": "Drive-time rings around focused property",
    "iso_off": "Off",
    "iso_30": "30 min",
    "iso_60": "60 min",
    "iso_both": "Both",
    "iso_caveat": ("Rings show estimated reach at ~75 km/h motorway average with "
                   "1.25× winding factor. Actual routed drive times will vary."),
    # legend-mode tag (the parenthesised drive-time mode beside "Layers")
    "legend_mode_est": "(est. drive times)",
    "legend_mode_car": "(car-baked drive times)",
    "legend_mode_hgv": "(HGV-baked drive times)",

    # --- POI category labels (shared: static legend poiCats AND modal catMeta) ---
    "poi_port": "Seaports",
    "poi_rail": "Rail terminals",
    "poi_air": "Airports",
    "poi_border": "Border crossings",
    "poi_city": "Major cities",

    # --- Compare tray -------------------------------------------------------
    "tray_clear": "Clear",
    "tray_compare": "Compare",

    # --- Lightbox aria-labels (shared a11y_* used by card/modal/lightbox) ----
    "lb_photo_viewer": "Photo viewer",
    "a11y_close": "Close",
    "a11y_prev_photo": "Previous photo",
    "a11y_next_photo": "Next photo",

    # --- Footer disclaimer --------------------------------------------------
    "footer_disclaimer": ("All information provided by CBRE in this document is subject "
                          "to change without notice. Rent levels, availability, technical "
                          "specifications, coordinates and timing are indicative, based on "
                          "landlord-provided data, and subject to negotiation. Drive-time "
                          "estimates are calculated from great-circle distance with a "
                          "1.25× road winding factor at a 75 km/h motorway average and "
                          "are for orientation only. Not for public distribution."),

    # --- Distance mode labels (DIST_LABEL / DIST_BADGE) ---------------------
    "dist_label_est": "est.",
    "dist_label_car": "car",
    "dist_label_hgv": "HGV",
    "dist_badge_est": "Straight-line estimates - not routed",
    "dist_badge_car": "Car-routed drive times (OSRM)",
    "dist_badge_hgv": "HGV / truck-routed drive times (openrouteservice)",
    # fmtMin minute unit (h/m kept verbatim per spec)
    "unit_min": " min",

    # --- Card chrome --------------------------------------------------------
    "card_compare": "Compare",
    "card_view_details": "View details",
    "row_warehouse": "Warehouse",
    "row_clear_height": "Clear height",
    "row_status": "Status",
    "row_early_access": "Early access",
    "card_alert_max_compare": "You can compare up to 4 properties at a time.",
    "tray_remove": "Remove",

    # --- Map popup + isochrone tooltips -------------------------------------
    "map_view_details": "View details",
    "iso_ring_30_tooltip": "30 min reach (est.)",
    "iso_ring_60_tooltip": "60 min reach (est.)",
    "iso_ring_30_real": "30 min drive reach (real road network)",
    "iso_ring_60_real": "60 min drive reach (real road network)",

    # --- Modal: hero / head -------------------------------------------------
    "img_toggle_photo": "Aerial / Render",
    "img_toggle_plan": "Site Plan",
    "modal_early_access_prefix": "Early access",
    "modal_open_maps": "Open in Google Maps ↗",
    "modal_approx_note": ("Coordinates are approximate — exact site location to be "
                          "confirmed by developer."),

    # --- Modal: section titles (HTML entities preserved verbatim) -----------
    "sec_availability": "Availability &amp; Site",
    "sec_technical": "Technical Specification",
    "sec_commercial": "Commercial Terms (Headline)",
    "sec_location": "Location &amp; Reach",
    "sec_workforce": "Workforce &amp; Region",
    "sec_additional": "Additional Details",

    # --- Modal + compare row labels (shared row_* where identical) ----------
    "row_total_gla": "Total GLA",
    "row_warehouse_area": "Warehouse area",
    "row_office_area": "Office area",
    "row_plot_area": "Plot area",
    "row_divisible_from": "Divisible from",
    "row_expansion_building": "Expansion in building",
    "row_expansion_park": "Expansion in park",
    "row_landlord": "Landlord",
    "row_property_status": "Property status",
    "row_permitting": "Permitting",
    "row_early_access_date": "Early access date",
    "row_floor_load": "Floor load",
    "row_sprinklers": "Sprinklers",
    "row_loading_docks": "Loading docks",
    "row_overhead_doors": "Overhead doors",
    "row_electricity": "Electricity",
    "row_truck_parking": "Truck parking",
    "row_car_parking": "Car parking",
    "row_warehouse_rent": "Warehouse rent",
    "row_warehouse_rent_monthly": "Warehouse rent (monthly)",
    "row_total_annual_rent": "Total annual rent",
    "row_total_monthly_rent": "Total monthly rent",
    "row_office_rent": "Office rent",
    "row_service_charge": "Service charge",
    "row_land_price": "Land price",
    "row_lease_term": "Lease term",
    "row_rent_free": "Rent-free period",
    "row_incentives": "Incentives",
    "row_reit": "REIT",
    # compare-only label differences
    "cmp_country": "Country",
    "cmp_city": "City",
    "cmp_developer": "Developer",
    "cmp_motorway": "Motorway",
    "cmp_status": "Status",
    "cmp_early_access": "Early access",
    "cmp_certification": "Certification",
    # --- Distance table -----------------------------------------------------
    "dist_th_destination": "Destination",
    "dist_th_distance": "Distance",
    "dist_th_drive_time": "Drive time",
    # dist-status note: v18 rendered the LEAD clause in brand-green bold; the span is
    # emitted at the call site (distStatusHtml) so these translatable strings stay free
    # of markup. Split into lead + rest. dist_status_est had no span in v18 - unchanged.
    "dist_status_hgv_lead": "● HGV / truck-routed distances from openrouteservice.",
    "dist_status_hgv_rest": ("Distances reflect the actual road network for trucks. "
                             "Border wait times not included."),
    "dist_status_car_lead": "● Car-routed distances from OSRM.",
    "dist_status_car_rest": ("Distances reflect the actual road network. Truck/HGV times "
                             "are not modelled; border wait times not included."),
    "dist_status_est": ("Distances shown as great-circle estimates. Fetching live "
                        "car-routed drive times from OSRM (truck/HGV times are not "
                        "modelled)…"),

    # --- Workforce / region block -------------------------------------------
    "wf_district_label": "District-level labour market",
    "wf_unemployment": "Unemployment",
    "wf_applicants_suffix": "applicants / vacancy",
    "wf_market_tight": "Tight labour market",
    "wf_market_balanced": "Balanced",
    "wf_market_deep": "Deep labour pool available",
    "wf_regional_unemployment": "Regional unemployment",
    "wf_population": "Population",
    "wf_labour_force": "Labour force",
    "wf_employment_rate": "Employment rate",
    "wf_gdp_per_capita": "GDP per capita",
    "wf_gdp_nominal": "GDP (nominal)",
    "wf_manufacturing_employment": "Manufacturing employment",
    "wf_transport_storage_employment": "Transport &amp; storage employment",
    "wf_logistics_share": "Logistics employment share",
    "wf_unit_pct": "%",
    "wf_unit_pct_eu27": "% EU27",
    "wf_as_of_prefix": "As of",
    "wf_pps_prefix": "PPS",
    "wf_economically_active": "Economically active",
    "wf_age_20_64": "Age 20–64",
    "wf_persons_employed": "Persons employed",
    "wf_logistics_sub": "Transport &amp; storage share of the labour force",
    "wf_sources": "Sources:",
    "wf_empty": ("Workforce and regional labour data not yet added for this option "
                 "— see the Gaps Report."),

    # --- Modal map caveats --------------------------------------------------
    "coords_prefix": "Coordinates",
    "coords_not_located": "not yet located (see Gaps Report)",
    "coords_rings_real": ("● Green and dark polygons show real 30 min and 60 min "
                          "drive-time reach"),
    "coords_rings_real_suffix": ("computed from the OSRM road network. Use the top-right "
                                 "control to switch to satellite."),
    "coords_rings_est": ("Green ring ≈ 30 min reach, dark ring ≈ 60 min reach "
                         "(estimated — fetching real isochrones…). Use the "
                         "top-right control to switch to satellite."),
    "map_not_confirmed": "Location not yet confirmed - see the Gaps Report.",
    "map_layer_streets": "Streets",
    "map_layer_satellite": "Satellite",

    # --- Compare modal ------------------------------------------------------
    "cmp_side_by_side": "Side-by-side comparison",
    "cmp_properties_compared_suffix": "properties compared",
    "cmp_highlight_note": "Largest warehouse and lowest rent highlighted",
    "cmp_attribute": "Attribute",
    "cmp_nearest_city": "Nearest major city",
    "cmp_nearest_border": "Nearest border",
    "cmp_nearest_airport": "Nearest airport",
    "cmp_nearest_rail": "Nearest rail",
    "cmp_nearest_seaport": "Nearest seaport",
    "cmp_alert_min_two": "Select at least two properties to compare.",
}

# --------------------------------------------------------------------------- #
# Phase 2: the SUPPORTED map - the AUTHORITATIVE registry of every base language
# this skill can present, BOTH the 12 bundled ones AND the fallback-eligible
# European Latin-script languages translated on demand (translate-once-cache).
#
# Each entry: code -> {"locale": <default BCP-47>, "names": [endonyms + English names]}.
# 'bundled' is NOT carried here; it is derived at load time from whether a real
# assets/i18n/<code>.json was read (is_bundled). The first 12 are the bundled set
# (a real <code>.json exists); the rest are fallback-eligible (no bundled file ->
# needs_fallback -> Phase-2 translate-once-cache; absent a cache they degrade to EN).
#
# BCP47 and _NAME2CODE are DERIVED from this single source of truth so the bundled-12
# behaviour is byte-for-byte unchanged (same locales, same accepted names) while the
# fallback languages become resolvable to THEIR OWN code (never 'en').
SUPPORTED = {
    # --- the 12 bundled languages (a real assets/i18n/<code>.json is shipped) -----
    "en": {"locale": "en-GB", "names": ["english", "en"]},
    "de": {"locale": "de-DE", "names": ["german", "deutsch", "de"]},
    "fr": {"locale": "fr-FR", "names": ["french", "francais", "français", "fr"]},
    "es": {"locale": "es-ES", "names": ["spanish", "espanol", "español", "es"]},
    "it": {"locale": "it-IT", "names": ["italian", "italiano", "it"]},
    "nl": {"locale": "nl-NL", "names": ["dutch", "nederlands", "nl"]},
    "pl": {"locale": "pl-PL", "names": ["polish", "polski", "pl"]},
    "pt": {"locale": "pt-PT", "names": ["portuguese", "portugues", "português", "pt"]},
    "cs": {"locale": "cs-CZ", "names": ["czech", "cestina", "čeština", "cs"]},
    "sk": {"locale": "sk-SK", "names": ["slovak", "slovencina", "slovenčina", "sk"]},
    "hu": {"locale": "hu-HU", "names": ["hungarian", "magyar", "hu"]},
    "ro": {"locale": "ro-RO", "names": ["romanian", "romana", "română", "ro"]},
    # --- fallback-eligible European Latin-script languages (Phase 2; translate-on- ---
    # --- demand, cached). Nordic / Baltic / Balkan / Iberian-minority / misc. ---------
    "da": {"locale": "da-DK", "names": ["danish", "dansk", "da"]},
    "sv": {"locale": "sv-SE", "names": ["swedish", "svenska", "sv"]},
    "nb": {"locale": "nb-NO", "names": ["norwegian", "norsk", "bokmal", "bokmål",
                                        "norwegian bokmal", "nb", "no", "nn"]},
    "fi": {"locale": "fi-FI", "names": ["finnish", "suomi", "fi"]},
    "is": {"locale": "is-IS", "names": ["icelandic", "islenska", "íslenska", "is"]},
    "ga": {"locale": "ga-IE", "names": ["irish", "gaeilge", "irish gaelic", "ga"]},
    "hr": {"locale": "hr-HR", "names": ["croatian", "hrvatski", "hr"]},
    "sl": {"locale": "sl-SI", "names": ["slovenian", "slovene", "slovenscina",
                                        "slovenščina", "sl"]},
    "et": {"locale": "et-EE", "names": ["estonian", "eesti", "et"]},
    "lv": {"locale": "lv-LV", "names": ["latvian", "latviesu", "latviešu", "lv"]},
    "lt": {"locale": "lt-LT", "names": ["lithuanian", "lietuviu", "lietuvių", "lt"]},
    "mt": {"locale": "mt-MT", "names": ["maltese", "malti", "mt"]},
    "ca": {"locale": "ca-ES", "names": ["catalan", "catala", "català", "ca"]},
    "gl": {"locale": "gl-ES", "names": ["galician", "galego", "gl"]},
    "lb": {"locale": "lb-LU", "names": ["luxembourgish", "letzebuergesch",
                                        "lëtzebuergesch", "lb"]},
}

# Default BCP-47 region per base language (number/date formatting + Intl.DisplayNames),
# derived from SUPPORTED. Covers BOTH bundled + fallback codes so locale_for / the
# exit-11 manifest can name a fallback language's locale.
BCP47 = {code: spec["locale"] for code, spec in SUPPORTED.items()}

# Accept either an ISO code ('de'), an endonym ('Deutsch') or an English name
# ('German'). lowercase name -> base code. Derived from SUPPORTED.
_NAME2CODE = {}
for _code, _spec in SUPPORTED.items():
    _NAME2CODE[_code] = _code
    for _nm in _spec["names"]:
        _NAME2CODE[_nm] = _code

# Per-language overrides, bundled as assets/i18n/<code>.json (Phase 1b). 'en' IS the
# authoritative EN above. Each file is read with EXPLICIT UTF-8 (a cp1252 host would
# otherwise choke on the accented characters). A missing/unreadable/empty file is skipped
# so that language degrades per-key to English rather than crashing the build; the
# integrity manifest + evals/i18n_test.py catch a corrupt or incomplete bundle in dev/CI.
_I18N_DIR = Path(__file__).resolve().parent.parent / "assets" / "i18n"


def _load_bundled() -> dict:
    table = {"en": EN}
    if _I18N_DIR.is_dir():
        for p in sorted(_I18N_DIR.glob("*.json")):
            code = p.stem.strip().lower()
            if code in ("en", "") or code not in SUPPORTED:
                continue  # never override the authoritative EN; only known languages
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue  # graceful: this language falls back to EN per key
            if isinstance(data, dict) and data:
                table[code] = data
    return table

# Load bundled translations now that SUPPORTED (the allowed-code whitelist) exists.
# TABLE = {"en": EN, "de": {...}, ...}: EN baseline + whatever real <code>.json files
# shipped. A fallback-eligible language has NO entry here until its cache is baked into
# canonical.meta.ui_overrides (Phase 2) - so is_bundled() == (code in TABLE and != 'en').
TABLE = _load_bundled()


def normalize_lang(language) -> str:
    """'English'/'de-DE'/'Deutsch'/'Dansk' -> base code ('en'/'de'/'da'), lowercased.

    A SUPPORTED language (bundled OR fallback-eligible) resolves to ITS OWN code;
    only a genuinely unknown/unsupported value (a non-Latin or nonsense language)
    returns 'en'. Default (empty) -> 'en'."""
    if not language:
        return "en"
    s = str(language).strip().lower()
    if not s:
        return "en"
    # a BCP-47 / locale tag ('de-DE', 'pt_BR', 'nb-NO') -> its base subtag
    base = s.replace("_", "-").split("-")[0]
    # exact endonym/English-name match first, then the base subtag, else 'en'
    return _NAME2CODE.get(s) or _NAME2CODE.get(base) or (base if base in SUPPORTED else "en")


def is_supported(language) -> bool:
    """True when `language` resolves to a SUPPORTED code (bundled OR fallback-eligible).

    NB a value that does not resolve returns 'en' from normalize_lang, so we must
    distinguish a genuine 'en'/'English' request from an unknown value that merely
    DEFAULTED to 'en'. Anything that maps to a non-'en' SUPPORTED code is supported;
    'en' is supported only when the input actually names English."""
    code = normalize_lang(language)
    if code != "en":
        return True  # resolved to a real non-English SUPPORTED code
    s = str(language or "").strip().lower()
    base = s.replace("_", "-").split("-")[0]
    # English was genuinely requested (not an unknown value defaulting to 'en')
    return bool(s) and (_NAME2CODE.get(s) == "en" or _NAME2CODE.get(base) == "en")


def is_bundled(code) -> bool:
    """True when a real bundled translation is loaded for this code (a shipped
    assets/i18n/<code>.json), i.e. it renders instantly with no fallback round.
    'en' is the authoritative baseline and counts as bundled."""
    c = normalize_lang(code) if code not in TABLE else code
    return c == "en" or c in TABLE


def needs_fallback(language) -> bool:
    """True when `language` is SUPPORTED but NOT bundled -> a Phase-2 translate-once-
    cache fallback is required (run.py exits 11 to request it). False for the bundled
    12 (instant) and for an unsupported value (correctly renders English)."""
    code = normalize_lang(language)
    return is_supported(language) and not is_bundled(code)


def en_sha() -> str:
    """A short, stable content hash of the EN baseline + the i18n schema version, so a
    future EN change (new/changed key) invalidates a stale fallback cache. Deterministic
    (sort_keys); 16 hex chars is ample to key a per-work-dir cache."""
    body = json.dumps(EN, sort_keys=True, ensure_ascii=True)
    h = hashlib.sha256((I18N_SCHEMA_VERSION + "\n" + body).encode("utf-8")).hexdigest()
    return h[:16]


def ui_for(language, overrides=None) -> dict:
    """Complete chrome dict for a language: EN with any per-language bundled overrides
    layered on, then (Phase 2) any canonical-borne `overrides` (the fallback cache)
    layered on top - but ONLY for keys that exist in EN (a stray/DATA key is dropped;
    a missing key falls back per-key to EN). With no overrides this is byte-identical
    to the Phase-1 behaviour."""
    code = normalize_lang(language)
    base = {**EN, **TABLE.get(code, {})}
    if isinstance(overrides, dict) and overrides:
        base = {**base, **{k: v for k, v in overrides.items() if k in EN}}
    return base


def locale_for(language, explicit=None) -> str:
    """BCP-47 locale: an explicit meta.locale wins; else the language's default; else en-GB."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return BCP47.get(normalize_lang(language)) or "en-GB"


def load_fallback_cache(path) -> dict | None:
    """Read a work-dir fallback cache <code>.json (EXPLICIT utf-8). Returns the flat
    chrome dict with any leading '_en_sha'/'_*' meta keys stripped, or None on ANY
    error (missing/corrupt/not-a-dict/empty) so the caller degrades gracefully to EN
    rather than crashing the build."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    chrome = {k: v for k, v in data.items() if not str(k).startswith("_")}
    return chrome or None
