#!/usr/bin/env python3
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C


def _fmt_thousands_k(lo: float, hi: float) -> str:
    """e.g. 33600,76000 -> '33.6 - 76k' (one decimal only if needed)."""
    def one(v):
        k = v / 1000.0
        return f"{k:.1f}".rstrip("0").rstrip(".")
    return f"{one(lo)} - {one(hi)}k"


def compute_kpis(props: list[dict], regions: dict, units: dict | None = None) -> dict:
    def distinct(key):
        return [v for v in {p.get(key) for p in props if p.get(key)}]

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
    # regions: prefer regionCode, else region label
    region_codes = [p.get("regionCode") for p in props if p.get("regionCode")]
    region_labels = [p.get("region") for p in props if p.get("region")]
    n_regions = len(set(region_codes)) or len(set(region_labels)) or len(regions)

    kpis = {
        "kpi_properties": str(len(props)),
        "kpi_countries": str(len(set(countries))),
        "kpi_regions": str(n_regions),
        "kpi_developers": str(len(set(distinct("developer")))),
        "kpi_wh_area": _fmt_thousands_k(min(areas), max(areas)) if areas else "tbd",
        "kpi_rent": ((f"{cur}{min(rents):g}" if min(rents) == max(rents)
                      else f"{cur}{min(rents):g} - {max(rents):g}") if rents else "tbd"),
        "kpi_wh_area_sub": f"{area_unit} per building",
        "kpi_rent_sub": f"per {per} / year",
        "kpi_countries_sub": " · ".join(sorted(set(countries))) if countries else "tbd",
        # ALWAYS static: region labels are often derived from source-file names
        # (intake clustering), so enumerating them leaked filename junk into the
        # hero KPI strip on a real run. The count carries the information.
        "kpi_regions_sub": "Under consideration",
    }
    return kpis


def render(data: dict, strict: bool = True) -> tuple[str, dict]:
    """Pure substitution: return (html, tokens). No file I/O. Used by both build()
    and gate_runner.py validate-html (which re-runs render and asserts byte-equality)."""
    props = [C.fill_render_sentinels(dict(p)) for p in data["properties"]]
    pois = data.get("pois", [])
    regions = data.get("regions", {})
    hero = (data.get("meta", {}) or {}).get("hero", {}) or {}

    template = C.load_template()

    # --- 1. config tokens -----------------------------------------------------
    tokens = {
        "topbar_meta": hero.get("topbar_meta", ""),
        "eyebrow": hero.get("eyebrow", ""),
        "title_html": hero.get("title_html", ""),
        "lede": hero.get("lede", ""),
        "footer_copyright": hero.get("footer_copyright", ""),
    }
    # dist_mode reflects the BUILD-time enrichment state so the dashboard can label
    # the distance/drive-time columns honestly (est. = straight-line, car / HGV =
    # routed). Only a completed OSRM bake (osrm AND osrm_done) earns car/hgv; an
    # --osrm run that baked nothing, or a geocode/pois-only build, degrades to est.
    enr = (data.get("meta") or {}).get("enrichment", {}) or {}
    tokens["dist_mode"] = (
        ("hgv" if "hgv" in str(enr.get("routing", "")).lower() else "car")
        if (enr.get("osrm") and enr.get("osrm_done")) else "est"
    )
    tokens.update(compute_kpis(props, regions, (data.get("meta", {}) or {}).get("units")))

    out = template
    for tok in C.CONFIG_TOKENS:
        out = out.replace("{{" + tok + "}}", str(tokens.get(tok, "")))

    # --- 2. data blocks -------------------------------------------------------
    def block(name, value):
        # sort_keys -> byte-deterministic across runs/machines.
        body = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        # escape < > so source-derived text (brochure caption / email body) cannot
        # break out of the <script> block; ensure_ascii also escapes U+2028/U+2029.
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
    out_path.write_text(out, encoding="utf-8")

    report = {
        "template_label": version.get("label"),
        "template_chrome_sha256": version.get("chrome_sha256"),
        "output": str(out_path),
        "output_bytes": len(out.encode("utf-8")),
        "counts": {"properties": len(props), "pois": len(pois), "regions": len(regions)},
        "config_tokens": tokens,
    }
    report_path = out_path.with_suffix(".build_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

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
