#!/usr/bin/env python3
"""make_integrity.py - (re)generate assets/integrity.json.

Records the byte size + sha256 of every helper and the core assets/templates so
preflight.py can detect a TRUNCATED or partial skill copy (e.g. a flaky sandbox
mount that delivers a half-written file) and stop with a plain message instead of
a mid-file SyntaxError. Run this after editing any helper or template:

    python helpers/make_integrity.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = (
    sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "helpers").glob("*.py"))
    # bundled per-language chrome translations (Phase 1b); a truncated file would silently
    # degrade that language to the English fallback, so integrity-guard each one
    + sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "assets" / "i18n").glob("*.json"))
    + ["NOTICE",  # author's copyright/ownership mark (tamper-evidence; see NOTICE)
       "assets/dashboard_template.html",
       # the PRIOR template, kept so old projects rebuild identically (contract rule);
       # v18 = the last pre-i18n template, preserved when v19 added localisation
       "assets/dashboard_template.v18.html", "assets/VERSION",
       # the load-bearing JSON assets: a truncated poi_library crashes intake, a
       # truncated label_ledger silently degrades multilingual extraction. The three
       # big datasets ship GZIPPED (.json.gz) to keep the skill under the org upload-
       # size cap - enrich._load_asset_json reads .json.gz (or a rebuilt plain .json).
       "assets/poi_library.json", "assets/label_ledger.json", "assets/plan_lexicon.json",
       "assets/poi_dataset.json.gz",
       "assets/regions_dataset.json.gz", "assets/cities_dataset.json.gz",
       # the >=100k European city POI layer + complete OSM border-crossing dataset (both
       # nearest-of-complete-set; a truncated copy would degrade nearest-city / nearest-border)
       "assets/cities_major_dataset.json.gz", "assets/borders_dataset.json.gz",
       # the NUTS-3 boundary polygons for point-in-polygon region binding (a truncated
       # copy would silently degrade the workforce bind to label/city)
       "assets/regions_geo.json.gz",
       # the pre-baked placeholder served when Pillow is absent (no-PIL Cowork): a
       # truncated copy would ship a broken hero data URI, so integrity-guard it
       "assets/placeholder.uri",
       "templates/canonical.schema.json", "templates/record_schema.json"]
)


def _entry(rel: str) -> dict:
    b = (ROOT / rel).read_bytes()
    return {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()}


def main() -> None:
    manifest = {rel: _entry(rel) for rel in TARGETS if (ROOT / rel).exists()}
    out = ROOT / "assets" / "integrity.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"OK wrote {out} ({len(manifest)} files)")


if __name__ == "__main__":
    main()
