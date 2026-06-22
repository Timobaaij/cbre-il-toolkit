#!/usr/bin/env python3
"""build_regions_dataset.py - Oxford Economics regional export -> assets/regions_dataset.json.

Converts the org's Oxford Economics NUTS3 download (one row per region x
indicator, a single current-year value column) into a bundled regional-economics
dataset that PRE-FILLS the workforce profiles: population, labour force,
unemployment, nominal GDP and the logistics-relevant employment splits for
~1,500 European provinces, all current-year baseline values with the citation
built in. This dataset supplies the ENTIRE default workforce snapshot (the
dashboard's logistics-employment-share tile is derived from the transport &
storage and labour-force figures here), so a standard run needs NO region
research. The research sub-agent is now an optional fallback only for a region
this dataset does not carry - and the SOURCE RULE still stands for anything it
researches: quality decides, never convenience.

Refresh (org maintenance): download a new export, re-run this, re-run
helpers/make_integrity.py.

CLI:
  python helpers/build_regions_dataset.py "<oxecon export.csv>"
                                          [--out assets/regions_dataset.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import re
import sys
import unicodedata
from pathlib import Path


def _write_gz(out: Path, text: str) -> Path:
    """Write `text` GZIPPED to <stem>.json.gz (the big datasets ship gzipped to keep the
    skill under the org upload-size cap; enrich._load_asset_json reads it). Drops a stale
    uncompressed sibling so the loader never picks up stale plain JSON. Returns the path."""
    import gzip
    if out.suffix == ".json":
        out = out.with_name(out.name + ".gz")
    out.write_bytes(gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0))
    plain = out.with_suffix("")
    if plain != out and plain.exists():
        plain.unlink()
    return out


# CSV indicator -> (profile field, unit multiplier). Thousands of persons -> persons.
INDICATORS = {
    "ILO unemployment rate": ("unemployment", 1.0),
    "Total population": ("population", 1000.0),
    "Workforce": ("labourForce", 1000.0),
    "Employment - Manufacturing": ("emplManufacturing", 1000.0),
    "Employment - Transportation & storage": ("emplTransportStorage", 1000.0),
}
GDP_PREFIX = "GDP, nominal"  # encoding-fragile euro sign -> match by prefix
_NUTS_CC = {"EL": "GR", "UK": "GB"}  # NUTS prefixes that differ from ISO2


def _norm_name(s: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                            if not unicodedata.combining(c)).lower().split())


def _name_variants(name: str) -> set:
    """Every normalised lookup key for a region name, incl. bilingual / dual-language
    forms so a property binds whichever spelling it carries: 'Valencia / Valencia' ->
    {'valencia / valencia', 'valencia'}; 'Alicante / Alacant' -> {..., 'alicante',
    'alacant'}; 'Bolzano (Bozen)' -> {..., 'bolzano', 'bozen'}. Accent-stripped, lowered.
    Splits on / , ; and ' - '; indexes both the outside and the inside of parentheses."""
    raw = str(name or "")
    out = set()
    full = _norm_name(raw)
    if full:
        out.add(full)
    inside = re.findall(r"\(([^)]*)\)", raw)        # parenthetical local name(s)
    base = re.sub(r"\([^)]*\)", " ", raw)           # the name without the parenthetical
    for piece in [base] + inside:
        for part in re.split(r"[/,;]| - ", piece):
            v = _norm_name(part)
            if v:
                out.add(v)
    return out


def _build_name_index(regions: dict) -> dict:
    """name-variant -> [code], keeping only the UNAMBIGUOUS variants (a fragment shared by
    two provinces is dropped, exactly like the original full-name index) so a split never
    invents a wrong bind. Used at build time AND to re-derive the index of a shipped dataset."""
    idx: dict = {}
    for code, reg in regions.items():
        for v in _name_variants(reg.get("name", "")):
            idx.setdefault(v, set()).add(code)
    return {k: [next(iter(v))] for k, v in idx.items() if len(v) == 1}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", help="the Oxford Economics regional export")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "assets" / "regions_dataset.json"))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(args.csv, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("empty export"); sys.exit(1)
    # the value column is the first 4-digit-year header
    year_col = next((c for c in rows[0] if re.fullmatch(r"(?:19|20)\d{2}", str(c).strip())), None)
    if not year_col:
        print("no year value column found in the export header"); sys.exit(1)
    updated = next((r.get("Date of last update", "") for r in rows
                    if r.get("Date of last update")), "")

    regions: dict[str, dict] = {}
    skipped = 0
    for r in rows:
        code = str(r.get("Location code", "")).strip()
        loc = str(r.get("Location", "")).strip()
        ind = str(r.get("Indicator", "")).strip()
        try:
            val = float(str(r.get(year_col, "")).replace(",", ""))
        except Exception:
            skipped += 1
            continue
        name = loc.split(" - ", 1)[1].strip() if " - " in loc else loc
        reg = regions.setdefault(code, {
            "name": name, "nuts": code,
            "country": _NUTS_CC.get(code[:2], code[:2]),
        })
        if ind in INDICATORS:
            field, mult = INDICATORS[ind]
            reg[field] = round(val * mult, 2 if field == "unemployment" else 0)
        elif ind.startswith(GDP_PREFIX):
            reg["gdpNominalMeur"] = round(val)
        else:
            skipped += 1

    asof = f"{year_col} (Oxford Economics baseline" + (f", updated {updated})" if updated else ")")
    src = ("Oxford Economics regional baseline (CBRE licence)"
           + (f", updated {updated}" if updated else "")
           + "; underlying: national statistics offices / Eurostat")
    for code, reg in regions.items():
        reg["unemploymentAsOf"] = asof if "unemployment" in reg else ""
        reg["populationAsOf"] = asof if "population" in reg else ""
        reg["sources"] = src
    name_index = _build_name_index(regions)  # indexes bilingual/dual-name variants too

    out = _write_gz(Path(args.out), json.dumps({
        "version": 1,
        "asOf": asof,
        "note": ("Bundled regional-economics dataset (NUTS3) - supplies the entire "
                 "default workforce snapshot (incl. the derived logistics-employment "
                 "share); region research is an optional fallback only for a region "
                 "this dataset does not carry. Rebuild from a fresh export with "
                 "helpers/build_regions_dataset.py, then helpers/make_integrity.py."),
        "name_index": name_index,  # already uniqueness-filtered, with bilingual variants
        "regions": regions,
    }, ensure_ascii=False, separators=(",", ":")))
    cs = {}
    for code in regions:
        cs[code[:2]] = cs.get(code[:2], 0) + 1
    print(f"OK {len(regions)} regions ({len(cs)} countries) -> {out}")
    print(f"   as-of: {asof}")
    if skipped:
        print(f"   ({skipped} unmapped/unparseable rows skipped)")


if __name__ == "__main__":
    main()
