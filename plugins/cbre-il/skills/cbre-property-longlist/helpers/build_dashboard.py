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


def _hero_copy(hero: dict, ui: dict, n: int) -> dict:
    """The three hero CONFIG TOKENS (eyebrow / title_html / lede), localised.

    Precedence: whatever the broker authored in project.yaml ships VERBATIM (in any
    language, unmodified - no English prefix is composed onto it any more); a BLANK value
    falls back to the dashboard language's default from the i18n table. These three used
    to be hard-coded English literals in merge.load_hero, which is why the largest text on
    the page rendered in English in all 12 supported languages.

    {count} is filled with .replace(), NOT .format(): a translator's stray brace must
    degrade the lede, never crash the build. And a pack whose hero_lede_fmt LOST {count}
    self-heals to the EN string rather than shipping a lede with no number - the graceful
    path matters because cmd_i18n runs POST-build, so a blocking check here would be an
    unclearable exit 7 for a bundled language (its pack is a shipped, integrity-tracked
    asset with no runtime override). Everything here is derived from canonical + the
    resolved UI, so validate-html's byte-identity re-render is unaffected."""
    lede_fmt = str(ui.get("hero_lede_fmt") or "")
    if "{count}" not in lede_fmt:
        lede_fmt = str(I18N.EN.get("hero_lede_fmt", ""))
    return {
        "eyebrow": str(hero.get("eyebrow") or "").strip() or str(ui.get("hero_eyebrow") or ""),
        "title_html": (str(hero.get("title_html") or "").strip()
                       or str(ui.get("hero_title_html") or "")),
        "lede": str(hero.get("lede") or "").strip() or lede_fmt.replace("{count}", str(n)),
    }


def _doc_title(hero: dict, meta: dict) -> str:
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
    base = strip(hero.get("eyebrow")) or strip(hero.get("title_html")) or strip(meta.get("client"))
    if not base:
        return "CBRE Property Shortlist"
    return base if "cbre" in base.lower() else base + " — CBRE"


def compute_kpis(props: list[dict], regions: dict, units: dict | None = None,
                 ui: dict | None = None) -> dict:
    # ui = the localised chrome dict (i18n.ui_for); the three sub-labels below are
    # CHROME (localised), the figures/enumerations they wrap are DATA (untouched).
    ui = ui or {}

    # the unknown sentinels, in one place: 'tbd' is a TRUTHY STRING, so a truthiness-only
    # filter counts every unknown as a real value. `countries` and `region_codes` below were
    # each fixed for this (with audit references); `developers` was not, and shipped
    # "Developers 3 / Major landlords" for a two-landlord longlist - a FABRICATED count in the
    # client-facing KPI band. Worse, `reconcile` "validates" the hero KPI by re-running THIS
    # function, so the gate agreed with the wrong number. Filter once, use everywhere.
    _UNKNOWN = {"??", "tbd", "tbc", "n/a", "na", "none", "—", "-", ""}

    def distinct(key):
        return [v for v in {p.get(key) for p in props if p.get(key)}
                if str(v).strip().lower() not in _UNKNOWN]

    # dataset unit convention (merge meta.units; source units are KEPT). The hero
    # rent range only aggregates rents quoted in the DOMINANT convention - a lone
    # €/m² figure in a £/sq ft dataset keeps its own honest unit on its card and
    # sits out the strip (currencies are never converted, FX would be invention).
    units = units or {}
    rent_unit = units.get("rent") or "€/sq m/yr"
    area_unit = units.get("area") or "sq m"
    cur = rent_unit.split("/")[0] or "€"
    per = rent_unit.split("/")[1] if "/" in rent_unit else "sq m"

    areas = [p["warehouseArea"] for p in props
             if isinstance(p.get("warehouseArea"), (int, float))]
    rents = [p["warehouseRentVal"] for p in props
             if isinstance(p.get("warehouseRentVal"), (int, float))
             and (p.get("rentUnit") or "€/sq m/yr") == rent_unit]

    # P2-5: the '??' / unknown sentinel must never appear in the hero KPI strip (it is
    # an honest per-card gap, not a "country") - filter it from the count and the list
    countries = [c for c in distinct("country")
                 if str(c).strip().upper() not in ("??", "TBD", "—", "-", "")]
    country_set = set(countries)  # #55: derive once, reuse for the count AND the sorted sub-label
    # regions: prefer regionCode, else region label
    # exclude the unknown-region sentinel ('tbd'/'??') so it never inflates the KPI,
    # mirroring the countries filter above (audit S5-15)
    _unk = {"??", "tbd", "—", "-", "", "none"}
    region_codes = [c for c in (p.get("regionCode") for p in props)
                    if c and str(c).strip().lower() not in _unk]
    region_labels = [r for r in (p.get("region") for p in props)
                     if r and str(r).strip().lower() not in _unk]
    n_regions = len(set(region_codes)) or len(set(region_labels)) or len(regions)

    kpis = {
        "kpi_properties": str(len(props)),
        "kpi_countries": str(len(country_set)),
        "kpi_regions": str(n_regions),
        "kpi_wh_area": _fmt_thousands_k(min(areas), max(areas)) if areas else "tbd",
        "kpi_rent": ((f"{cur}{min(rents):g}" if min(rents) == max(rents)
                      else f"{cur}{min(rents):g} - {max(rents):g}") if rents else "tbd"),
        "kpi_wh_area_sub": (ui.get("kpi_wh_area_sub_fmt") or "{area} per building").format(area=area_unit),
        "kpi_rent_sub": (ui.get("kpi_rent_sub_fmt") or "per {unit} / year").format(unit=per),
        "kpi_countries_sub": " · ".join(sorted(country_set)) if countries else "tbd",
        # ALWAYS static: region labels are often derived from source-file names
        # (intake clustering), so enumerating them leaked filename junk into the
        # hero KPI strip on a real run. The count carries the information.
        "kpi_regions_sub": ui.get("kpi_regions_sub") or "Under consideration",
    }
    return kpis


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
    hero_copy = _hero_copy(hero, ui, len(props))
    tokens = {
        "topbar_meta": hero.get("topbar_meta", ""),
        "eyebrow": hero_copy["eyebrow"],
        "title_html": hero_copy["title_html"],
        "lede": hero_copy["lede"],
        "footer_copyright": hero.get("footer_copyright", ""),
        # browser-tab <title> ({{doc_title}}): adapts per project + language (was a
        # hardcoded "CEE Logistics Property Shortlist" default baked into the template).
        # Fed the RESOLVED hero so the tab derives from the localised eyebrow/headline
        # instead of the now-blank merge value.
        "doc_title": _doc_title({**hero, **hero_copy}, meta),
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
    out = out.replace(C.DATA_MARKERS["POIS"], block("POIS", pois))
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
        "counts": {"properties": len(props), "pois": len(pois), "regions": len(regions)},
        "config_tokens": tokens,
    }
    report_path = out_path.with_suffix(".build_report.json")
    C.atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))

    mb = report["output_bytes"] / (1024 * 1024)
    print(f"OK built {out_path} ({mb:.2f} MB) | "
          f"{len(props)} properties, {len(pois)} POIs, {len(regions)} regions")
    print(f"   report: {report_path}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("canonical", help="path to canonical.json")
    ap.add_argument("--out", required=True, help="output .html path")
    args = ap.parse_args()
    build(Path(args.canonical), Path(args.out))


if __name__ == "__main__":
    main()
