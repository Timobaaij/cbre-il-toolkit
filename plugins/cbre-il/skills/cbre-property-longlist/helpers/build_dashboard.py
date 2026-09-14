#!/usr/bin/env python3
# © 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""build_dashboard.py - Stage 5. Inject the canonical dataset into the frozen template.

Deterministic, no LLM, no new claims. It:
  1. Loads canonical.json and (best-effort) validates it against the schema.
  2. Computes the hero KPI tokens from the data so they cannot drift.
  3. Forward-substitutes the {{config}} tokens and the three /* @@INJECT:X@@ */ markers.
  4. Asserts no token or marker is left behind, then writes the .html + build_report.json.

The output is, by construction, the template plus exactly these substitutions and
nothing else - which is what guarantees the CBRE chrome never drifts. The matching
check lives in gate_runner.py validate-html (it re-runs this same substitution and
asserts byte-equality with the delivered file).

Usage:
  python build_dashboard.py <canonical.json> --out <output.html>
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C
import i18n as I18N


def _fmt_thousands_k(lo: float, hi: float) -> str:
    """e.g. 33600,76000 -> '33.6 - 76k' (one decimal only if needed)."""
    def one(v):
        k = v / 1000.0
        return f"{k:.1f}".rstrip("0").rstrip(".")
    return f"{one(lo)} - {one(hi)}k"


#: POI types the chrome renders. v45 retired the BORDER category from every surface (the
#: filter chips, Location and Reach, the modal mini-map, Compare and the Flyover), so a border
#: crossing would ship as a row of data that nothing on the page can show. Filtering HERE, at
#: the render boundary, rather than in enrich: the border dataset, its selection and its
#: coverage checks are all still correct and still tested, and re-enabling the category is a
#: one-line change in both places. A POI with no stated type is KEPT - dropping records on a
#: missing field is how a filter becomes a silent data loss.
DISPLAY_POI_TYPES = frozenset({"air", "port", "rail", "city"})


def _display_pois(pois: list) -> list:
    out = []
    for q in (pois or []):
        t = str((q or {}).get("type") or "").strip().lower()
        if t and t not in DISPLAY_POI_TYPES:
            continue
        out.append(q)
    return out


def _hero_copy(hero: dict, ui: dict, client: str = "") -> dict:
    """The two hero CONFIG TOKENS (eyebrow / title_html), localised.

    Precedence: whatever the broker authored in project.yaml ships VERBATIM (in any
    language, unmodified - no English prefix is composed onto it any more); a BLANK value
    falls back to the dashboard language's default from the i18n table. These used to be
    hard-coded English literals in merge.load_hero, which is why the largest text on the
    page rendered in English in all 12 supported languages.

    v45: the DEFAULT headline names the occupier - "{client} - Industrial & Logistics
    opportunities" - so the biggest text on the page says who the longlist is FOR instead
    of describing the asset class to the person who commissioned it. Three details:
      * {client} is filled with .replace(), NOT .format(), for the reason the removed
        lede's {count} was: a translator's stray brace must degrade the headline, never
        crash the build. A pack that carries no placeholder ships its wording untouched.
      * a BLANK client drops the placeholder AND the separator standing in front of it, so
        no dashboard opens on a dangling dash. The separator is matched as a CLASS rather
        than as the EN " - ", because a pack is free to join the two halves its own way and
        the dangling-punctuation problem is identical in every language.
      * an AUTHORED title_html is never touched: a broker who wrote their own headline did
        not ask for a client name to be composed into it.
    The v44 `lede` token is gone with the paragraph it filled (_common.CONFIG_TOKENS).
    Everything here is derived from canonical + the resolved UI, so validate-html's
    byte-identity re-render is unaffected."""
    authored = str(hero.get("title_html") or "").strip()
    title = authored or str(ui.get("hero_title_html") or "")
    if not authored and "{client}" in title:
        name = str(client or "").strip()
        title = (title.replace("{client}", name) if name
                 else re.sub(r"^\s*\{client\}\s*[-\u2013\u2014\u00b7:,|]?\s*", "", title)
                        .replace("{client}", ""))
    return {
        "eyebrow": str(hero.get("eyebrow") or "").strip() or str(ui.get("hero_eyebrow") or ""),
        "title_html": title,
    }


def _doc_title(hero: dict, meta: dict, authored: dict | None = None) -> str:
    """The browser-tab <title> ({{doc_title}}). An explicit hero.doc_title wins (authored
    per project, in the chosen language); else DERIVE from the eyebrow / headline / client
    so the tab ALWAYS adapts to the project instead of the old hardcoded 'CEE ... Shortlist'
    default. HTML tags are stripped (title_html carries <em>); the CBRE brand suffix is kept
    on the derived path. Always returns a non-empty string (so the token never stays empty)."""
    def strip(s):
        return re.sub(r"<[^>]+>", "", str(s or "")).strip()
    explicit = strip(hero.get("doc_title"))
    if explicit:
        return explicit
    # v45: AUTHORED first, then the resolved default, and the HEADLINE ahead of the eyebrow
    # within each. Two rules meet here and the order is what keeps both:
    #   * v20 - the tab adapts to the PROJECT. A broker who wrote an eyebrow (often the only
    #     hero string they write, and often the market: "Lista de naves ... Espana") must see
    #     it in the tab, so an authored string of either kind outranks any default.
    #   * v45 - with nothing authored, the DEFAULT headline now names the occupier
    #     ("Matalan - Industrial & Logistics opportunities"), which identifies the file among
    #     nine open tabs far better than an eyebrow that reads the same on every project.
    # `authored` is the raw project.yaml hero; `hero` is that merged with the resolved copy,
    # so the two are only distinguishable by passing both (see the call site).
    a = authored or {}
    base = (strip(a.get("title_html")) or strip(a.get("eyebrow"))
            or strip(hero.get("title_html")) or strip(hero.get("eyebrow"))
            or strip(meta.get("client")))
    if not base:
        return "CBRE Property Longlist"
    return base if "cbre" in base.lower() else base + " · CBRE"


def _dominant_country(props: list[dict]) -> str:
    """The ISO country most properties state ("" when none does), for the D11 rent-basis
    fallback on a canonical whose meta.units predates the key. Mirrors merge.dominant_country
    on canonical properties (already ISO after merge; names still normalise)."""
    from collections import Counter
    c = Counter(C._N.country_iso(p.get("country")) for p in props
                if isinstance(p, dict) and p.get("country")
                and not C._N.looks_unknown_code(p.get("country")))
    return c.most_common(1)[0][0] if c else ""


def compute_kpis(props: list[dict], regions: dict, units: dict | None = None,
                 ui: dict | None = None) -> dict:
    # ui = the localised chrome dict (i18n.ui_for); the three sub-labels below are
    # CHROME (localised), the figures/enumerations they wrap are DATA (untouched).
    ui = ui or {}

    # the unknown sentinels, through the ONE shared predicate: 'tbd' is a TRUTHY STRING, so a
    # truthiness-only filter counts every unknown as a real value. `countries` and `region_codes`
    # below were each fixed for this (with audit references); `developers` was not, and shipped
    # "Developers 3 / Major landlords" for a two-landlord longlist - a FABRICATED count in the
    # client-facing KPI band. Worse, `reconcile` "validates" the hero KPI by re-running THIS
    # function, so the gate agreed with the wrong number. Filter once, use everywhere.
    #
    # v41 (F5): this function used to carry TWO private sentinel literals of its own, and the
    # one guarding the country KPI lacked 'n/a', 'na' and 'tbc', so a source writing `n/a` for a
    # country was counted as a real country in the headline KPI while every other consumer read
    # it as absent. Both now delegate to normalize.looks_unknown (contract C5), which also stops
    # deleting a stated "None": the extraction contract names that as DATA. Note the direction
    # for the KPI: a stated negative is a real value and now counts, exactly as the card shows it.
    def _known(v) -> bool:
        return bool(v) and not C._N.looks_unknown(v)

    def distinct(key, code_like=False):
        keep = (lambda v: not C._N.looks_unknown_code(v)) if code_like else _known
        return [v for v in {p.get(key) for p in props if p.get(key)} if keep(v)]

    # dataset unit convention (merge meta.units; source units are KEPT). The hero
    # rent range only aggregates rents quoted in the DOMINANT convention - a lone
    # €/m² figure in a £/sq ft dataset keeps its own honest unit on its card and
    # sits out the strip (currencies are never converted, FX would be invention).
    units = units or {}
    area_unit = units.get("area") or "sq m"
    # D11: merge writes meta.units.rent on every canonical it produces (the market-derived
    # default when no source states a unit, disclosed in meta.unitAssumptions). The fallback
    # here is for a canonical that predates that key, and it is the SAME derivation - the
    # dominant area unit and the dominant country of the properties - never a fixed "€/sq m/yr":
    # that constant is what put "per sq m / year" in euros on the hero KPI of a UK sq ft run.
    rent_unit = units.get("rent") or C._N.default_rent_unit(area_unit, _dominant_country(props))
    cur = rent_unit.split("/")[0] or "€"
    per = rent_unit.split("/")[1] if "/" in rent_unit else "sq m"

    areas = [p["warehouseArea"] for p in props
             if isinstance(p.get("warehouseArea"), (int, float))]
    # D11: only a rent whose OWN source states the dataset convention aggregates into the
    # headline range. A unit-silent figure (numeric, no rentUnit) used to be counted as if it
    # were quoted in the default convention, so the strip could print "£8.5" over a number
    # whose source named no currency - the same invention B06 removed from the card, which
    # renders that figure "8.5 (unit not stated)". It sits out the strip like a minority unit.
    rents = [p["warehouseRentVal"] for p in props
             if isinstance(p.get("warehouseRentVal"), (int, float))
             and p.get("rentUnit") == rent_unit]

    # P2-5: the '??' / unknown sentinel must never appear in the hero KPI strip (it is
    # an honest per-card gap, not a "country") - filter it from the count and the list.
    # distinct() already applies the shared predicate, so no second filter is stated here.
    # code-scoped: `country` holds an ISO alpha-2 code after merge, and three members of the
    # shared unknown family are also assigned codes. Filtering this list with the value-scoped
    # reader would drop those countries out of the headline count. (normalize.looks_unknown_code)
    countries = distinct("country", code_like=True)
    country_set = set(countries)  # #55: derive once, reuse for the count AND the sorted sub-label
    # regions: prefer regionCode, else region label
    # exclude the unknown-region sentinel ('tbd'/'??') so it never inflates the KPI,
    # mirroring the countries filter above (audit S5-15) - same predicate, same verdicts
    region_codes = [c for c in (p.get("regionCode") for p in props) if _known(c)]
    region_labels = [r for r in (p.get("region") for p in props) if _known(r)]
    n_regions = len(set(region_codes)) or len(set(region_labels)) or len(regions)

    kpis = {
        "kpi_properties": str(len(props)),
        "kpi_countries": str(len(country_set)),
        "kpi_regions": str(n_regions),
        "kpi_wh_area": _fmt_thousands_k(min(areas), max(areas)) if areas else C.BLANK,
        "kpi_rent": ((f"{cur}{min(rents):g}" if min(rents) == max(rents)
                      else f"{cur}{min(rents):g} - {max(rents):g}") if rents else C.BLANK),
        "kpi_wh_area_sub": (ui.get("kpi_wh_area_sub_fmt") or "{area} per building").format(area=area_unit),
        "kpi_rent_sub": (ui.get("kpi_rent_sub_fmt") or "per {unit} / year").format(unit=per),
        "kpi_countries_sub": " · ".join(sorted(country_set)) if countries else C.BLANK,
        # ALWAYS static: region labels are often derived from source-file names
        # (intake clustering), so enumerating them leaked filename junk into the
        # hero KPI strip on a real run. The count carries the information.
        "kpi_regions_sub": ui.get("kpi_regions_sub") or "Under consideration",
    }
    return kpis


def stated_total_tolerance(total: float) -> float:
    """The ARITHMETIC GATE'S OWN tolerance, quoted rather than re-invented.

    `gate_runner.cmd_arithmetic` writes exactly

        tol = max(50.0, 0.005 * total)

    and that gate is the only other place in the pipeline that compares a source's printed
    total against the chrome's derived GLA. Two independently chosen thresholds would mean a
    card that flags a difference the gate calls noise - or, far worse, a card that stays silent
    about one the gate blocks on - so the card and the gate must share the expression, not just
    the intent. `evals/statedtotal_card_test.py` extracts the expression from BOTH files and
    fails if they ever diverge, which is the only thing that keeps a quotation honest.
    """
    return max(50.0, 0.005 * total)


def _attach_stated_totals(props: list[dict], meta: dict) -> None:
    """Surface each source's OWN printed total area, for the card to show beside the derived one.

    THE DEFECT. `merge` already lifts every source's stated total into
    `canonical.meta.statedTotals` (keyed by property id), and until now the arithmetic gate was
    its ONLY consumer: the figure reached neither this builder nor the template. Meanwhile the
    card's area figure is DERIVED - the chrome sums components (`glaVal` = warehouseArea +
    officeAreaVal) - and a derivation reads BELOW the source's own printed total whenever real
    space sits inside that total and in no summed field: mezzanine, ancillary, plant. The client
    saw a smaller building than the brochure states, with nothing on the page to say so.

    WHERE IT IS PUT, and why not on the property itself. `preBaked` is the pipeline-assigned
    render container (it already carries `distances`/`isochrones`), it is in
    `run._PIPELINE_ASSIGNED_FIELDS`, `extract_xlsx._OPEN_DENY`, `merge._OV_FORBIDDEN` and
    `deliver`'s deny list, and `_common.canonical_property_fields()` already declares it - so the
    figure rides to the chrome without becoming a reader-fillable name, without appearing in a
    deliverable's columns, and without tripping the render-boundary gate that blocks a
    non-canonical OBJECT on a property. A top-level scalar is exactly what
    `extract_xlsx` refuses for this value and records the reason for: the record top level is
    client-facing surface and a raw figure would print there uninvited.

    WHEN IT IS ATTACHED. Only when the two figures differ by more than
    `stated_total_tolerance()`, the arithmetic gate's own expression, so agreement renders
    nothing at all and the card can never disagree with the gate about whether a difference
    matters. Every skip mirrors the gate's own skips exactly (no stated total, a non-numeric or
    absent contributor, a total <= 0, a warehouseArea `glaVal` would refuse), and no unit
    reconciliation is attempted HERE for the same reason the gate attempts none:
    `merge.stated_total_for` already refuses to record an un-converted record, so a figure in a
    foreign unit cannot reach this point.

    WHAT THE CHROME THEN DOES WITH IT (v41, F26). Before v41 the card printed this stated total
    as a qualifier while the modal's and the compare matrix's "Total GLA" row still printed the
    derived sum, so ONE label carried TWO figures on the same page whenever the source's total
    included space the two summed fields do not hold. The chrome's `glaVal()` now ADOPTS the
    stated total whenever this attach has placed one and falls back to warehouse + office only
    when it has not; the derivation above is therefore glaVal()'s fallback branch, and the
    tolerance comparison decides only whether the stated figure is surfaced at all.

    Mutates the SHALLOW property copies render() made; `preBaked` is rebuilt as a new dict so
    the caller's canonical object is never touched. Derived from canonical alone, so
    validate-html's byte-identity re-render is unaffected.
    """
    stated = meta.get("statedTotals") or {}
    if not isinstance(stated, dict) or not stated:
        return

    def _num(v):
        """The chrome's own test, and the gate's: a finite number, bool excluded."""
        return v if (isinstance(v, (int, float)) and not isinstance(v, bool)
                     and math.isfinite(v)) else None

    for p in props:
        st = stated.get(str(p.get("id")))
        if not isinstance(st, dict):
            continue
        total = _num(st.get("value"))
        if total is None or total <= 0:
            continue                     # no comparable stated total -> nothing to surface
        wa = _num(p.get("warehouseArea"))
        if wa is None:
            continue                     # glaVal() returns null here, so there is no derivation
        oa = _num(p.get("officeAreaVal"))
        gla = wa + (oa if (oa is not None and oa > 0) else 0)      # exactly glaVal()'s FALLBACK
        if abs(gla - total) <= stated_total_tolerance(total):
            continue                     # they agree - the derived figure already tells the truth
        pb = dict(p.get("preBaked") or {})
        pb["statedTotal"] = {"value": total,
                             "unit": str(st.get("unit") or p.get("areaUnit") or "")}
        p["preBaked"] = pb


def render(data: dict, strict: bool = True) -> tuple[str, dict]:
    """Pure substitution: return (html, tokens). No file I/O. Used by both build()
    and gate_runner.py validate-html (which re-runs render and asserts byte-equality)."""
    if "properties" not in data:
        raise ValueError("canonical has no 'properties' key - cannot build (a hand-built or "
                         "truncated canonical? re-run the pipeline to regenerate it) - S5-50")
    props = [C.fill_render_sentinels(dict(p)) for p in data["properties"]]
    pois = data.get("pois", [])
    regions = data.get("regions", {})
    meta = data.get("meta", {}) or {}
    hero = meta.get("hero", {}) or {}

    # v40: the source's own printed total area, for the card to show where it disagrees with the
    # derived figure. Reads canonical.meta only, so validate-html's re-render stays byte-stable.
    _attach_stated_totals(props, meta)

    # v19 localisation: resolve the chosen language -> a COMPLETE chrome dict (EN-
    # filled per key) + a BCP-47 locale. Missing language / missing key both fall
    # back to English; this resolves INSIDE render() so validate-html (which re-runs
    # render) stays byte-stable for a given canonical+language.
    #
    # Phase 2 (fallback): a SUPPORTED-but-not-bundled language carries its translated
    # chrome on canonical.meta.ui_overrides (baked there by merge.py from the work-dir
    # cache). Layering it HERE - the single render() both build() and gate_runner
    # validate-html call - is what keeps the fallback byte-stable: validate-html
    # re-runs render(canonical) and asserts byte-equality, so anything render consumes
    # for a language MUST be derivable from canonical alone (ui_overrides rides
    # canonical). Absent/invalid ui_overrides -> overrides=None -> Phase-1 path, byte-
    # identical to the bundled/EN build. ui_for() honours ONLY keys present in EN.
    ov = meta.get("ui_overrides") or None
    ui = I18N.ui_for(meta.get("language") or "en",
                     overrides=ov if isinstance(ov, dict) else None)
    locale = I18N.locale_for(meta.get("language") or "en", meta.get("locale"))

    template = C.load_template()

    # --- 1. config tokens -----------------------------------------------------
    # HERO COPY is resolved here, not in merge: a blank eyebrow/title_html/lede picks up
    # the LOCALISED default from the i18n table (they were English literals in
    # merge.load_hero, so the biggest text on the page was English in every language);
    # a broker-authored value ships verbatim. Derived from canonical + the resolved UI,
    # so validate-html's byte-identity re-render is unaffected.
    # v45: the CLIENT is passed in (not the property count the removed lede needed), so the
    # default headline can name the occupier this longlist was built for.
    hero_copy = _hero_copy(hero, ui, meta.get("client", ""))
    tokens = {
        "topbar_meta": hero.get("topbar_meta", ""),
        "eyebrow": hero_copy["eyebrow"],
        "title_html": hero_copy["title_html"],
        "footer_copyright": hero.get("footer_copyright", ""),
        # browser-tab <title> ({{doc_title}}): adapts per project + language (was a
        # hardcoded "CEE Logistics Property Shortlist" default baked into the template).
        # Fed the RESOLVED hero so the tab derives from the localised eyebrow/headline
        # instead of the now-blank merge value.
        # `hero` (raw, as authored) is passed alongside the merge so _doc_title can tell an
        # authored string from a localised default - see its docstring.
        "doc_title": _doc_title({**hero, **hero_copy}, meta, authored=hero),
    }
    # dist_mode reflects the BUILD-time enrichment state so the dashboard can label
    # the distance/drive-time columns honestly (est. = straight-line, car / HGV =
    # routed). Only a completed OSRM bake (osrm AND osrm_done) earns car/hgv; an
    # --osrm run that baked nothing, or a geocode/pois-only build, degrades to est.
    enr = meta.get("enrichment", {}) or {}
    tokens["dist_mode"] = (
        ("hgv" if "hgv" in str(enr.get("routing", "")).lower() else "car")
        if (enr.get("osrm") and enr.get("osrm_done")) else "est"
    )
    # v19 i18n tokens. ui_json is the chrome dict as COMPACT JSON, sort_keys for
    # determinism (byte-stable ui_json per language); ensure_ascii so any non-ASCII
    # endonym/label is \uXXXX-escaped. < and > are escaped to < / > so the
    # JSON cannot break out of the <script> block. NOT quoted (it is a JS object
    # literal); locale IS quoted in the template.
    #
    # HOW TO VERIFY A CJK (or any non-Latin) BUILD - read this before grepping:
    # ensure_ascii=True means the output file contains NO raw CJK bytes. A `zh`
    # dashboard ships each Chinese character as a 6-byte \uXXXX escape inside a JS
    # string literal, which the browser decodes correctly - the build is RIGHT and
    # the shipped file is pure ASCII.
    # So a raw-byte grep for the target script FAILS ON A CORRECT BUILD. Do not
    # "fix" that. Verify by loading the HTML, or by grepping for the \uXXXX escapes
    # (json.dumps(s)[1:-1] gives you the needle for a string s).
    # Do NOT switch to ensure_ascii=False: it would move rendered bytes for every
    # language, drift the oracle, and re-open the U+2028/U+2029 hole noted below.
    ui_body = json.dumps(ui, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    bs = chr(92)
    ui_body = ui_body.replace("<", bs + "u003c").replace(">", bs + "u003e")
    tokens["ui_json"] = ui_body
    tokens["locale"] = locale
    tokens.update(compute_kpis(props, regions, meta.get("units"), ui))

    out = template
    for tok in C.CONFIG_TOKENS:
        out = out.replace("{{" + tok + "}}", str(tokens.get(tok, "")))

    # --- 2. data blocks -------------------------------------------------------
    def block(name, value):
        # sort_keys -> byte-deterministic across runs/machines.
        body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        # escape < > so source-derived text (brochure caption / email body) cannot
        # break out of the <script> block; ensure_ascii also escapes U+2028/U+2029.
        # Non-Latin DATA is \uXXXX-escaped here too - see the ui_json comment above
        # for why a raw-byte grep for CJK fails on a CORRECT build.
        bs = chr(92)  # one backslash; build the JS < / > escapes without source ambiguity
        body = body.replace("<", bs + "u003c").replace(">", bs + "u003e")
        return f"const {name} = {body};"

    out = out.replace(C.DATA_MARKERS["PROPS"], block("PROPS", props))
    out = out.replace(C.DATA_MARKERS["POIS"], block("POIS", _display_pois(pois)))
    out = out.replace(C.DATA_MARKERS["REGIONS"], block("REGIONS", regions))

    # --- 3. integrity ---------------------------------------------------------
    if strict:
        leftover = C.find_leftover_tokens(out)
        if leftover:
            raise SystemExit(f"ERROR: unfilled tokens remain in output: {leftover}")
        for marker in C.DATA_MARKERS.values():
            if marker in out:
                raise SystemExit(f"ERROR: data marker not replaced: {marker}")
    return out, tokens


def build(canonical_path: Path, out_path: Path) -> dict:
    data = C.load_canonical(canonical_path)

    errs = C.validate_canonical(data)
    if errs:
        print("WARNING: canonical.json has schema issues (build continues; pre-build gate is authoritative):",
              file=sys.stderr)
        for e in errs[:20]:
            print(f"  - {e}", file=sys.stderr)

    version = C.load_version()
    out, tokens = render(data)

    missing = [t for t in C.CONFIG_TOKENS if not tokens.get(t)]
    if missing:
        print(f"WARNING: empty config tokens: {missing} (hero strings should come from project.yaml)",
              file=sys.stderr)

    props = data["properties"]
    pois = data.get("pois", [])
    regions = data.get("regions", {})

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    C.atomic_write_text(out_path, out)

    report = {
        "template_label": version.get("label"),
        "template_chrome_sha256": version.get("chrome_sha256"),
        "output": str(out_path),
        "output_bytes": len(out.encode("utf-8")),
        # v45: the POI count is what SHIPPED, not what canonical carried - _display_pois
        # drops a type the chrome has no surface for (see DISPLAY_POI_TYPES), and a report
        # that counted the input would disagree with the file it describes.
        "counts": {"properties": len(props), "pois": len(_display_pois(pois)),
                   "regions": len(regions)},
        "config_tokens": tokens,
    }
    report_path = out_path.with_suffix(".build_report.json")
    C.atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))

    mb = report["output_bytes"] / (1024 * 1024)
    print(f"OK built {out_path} ({mb:.2f} MB) | "
          f"{len(props)} properties, {len(_display_pois(pois))} POIs, "
          f"{len(regions)} regions")
    print(f"   report: {report_path}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("canonical", help="path to canonical.json")
    ap.add_argument("--out", required=True, help="output .html path")
    args = ap.parse_args()
    build(Path(args.canonical), Path(args.out))


if __name__ == "__main__":
    C.force_utf8_stdout()   # D16: a non-ASCII value in printed output must not
    #                        crash the print on a cp1252 Windows console
    main()
