#!/usr/bin/env python3
"""vision_validate.py - deterministic validators for vision-transcribed records.

For a graphics-heavy or scanned deck, vision transcription IS the entire
extraction (a real run routed 100% of its dataset through it), and that path is
where the worst errors hide: a hero bound to the neighbouring property's page,
a monthly rent shipped as annual, an invented coordinate, several properties
collapsed into one record. These checks are STRUCTURAL - no language, market or
model trust involved - and run on every `*_vision.json` before its records are
folded into the merge:

  ERRORS (the file is rejected; fix the transcription and re-run):
    * __meta.page_no missing, non-integer, or NOT one of the pages this deck's
      manifest actually rasterised (the page-binding failure that mis-binds heroes)
    * __meta.plan_page present but not a non-negative int, or off-range (it would
      render a neighbour's page as the site plan); null/omitted is allowed
    * warehouseRentVal outside the plausibility band (1.5-500 EUR/m2/yr)
    * lat/lng out of range
  WARNINGS (folded, but printed + persisted for the honesty reviewers):
    * warehouseRentVal suspiciously LOW (< 15) - likely an un-annualised monthly
      quote; confirm x12 (the conversion note belongs in prov)
    * warehouseArea/plotArea outside sane bounds (200 - 2,000,000 m2)
    * NUMERIC RECONCILIATION vs the twin text layer: vision is the least
      reliable source for DIGITS, but the same page's text layer (even a
      layout-garbled one) usually carries the exact numbers. When the source
      file is resolvable and its page text holds numbers, a transcribed
      rent/area that appears NOWHERE on that page (rent also checked as its
      monthly /12 form) is flagged as a suspected digit misread (a real run
      shipped 43->63, 60->60.63 and 54->54.66 with no check)
    * __meta.source_file differs from the manifest's deck
    * manifest pages with NO record at all - on multi-property pages the model
      may have COLLAPSED several properties into one record; each property on a
      page must be its own record (same page_no repeated is correct)
    * far fewer records than rasterised pages (same collapse smell, deck-level)

Standalone:  python helpers/vision_validate.py --work <work dir> [--folder <inputs>]
run.py runs it automatically before folding vision records (errors stop the run
with the same exit-3 contract as the vision manifest itself) and passes the
inputs folder so the numeric reconciliation can read the twin text layers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normalize as N

AREA_MIN, AREA_MAX = 200, 2_000_000
RENT_LOW_SUSPECT = 15.0  # plausible-but-low: smells like an un-annualised monthly quote


def _vkey(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s))
                   if not unicodedata.combining(c)).casefold().replace(" ", "")


_NUM_TOKEN = re.compile(r"\d(?:[\d ., ]*\d)?")


def _page_numbers(text: str) -> set[float]:
    """Every plausible numeric reading of the page's digit tokens, EU formats
    included: '39 471' -> 39471, '4,50' -> 4.5 (and 450 - extra readings are
    harmless, the test is membership of the EXPECTED value)."""
    out: set[float] = set()
    for tok in _NUM_TOKEN.findall(text or ""):
        t = tok.replace(" ", " ").strip()
        plain = re.sub(r"[ .,]", "", t)
        if plain.isdigit():
            try:
                out.add(float(plain))  # every separator read as thousands
            except ValueError:
                pass
        m = re.match(r"^(.+?)[.,](\d{1,2})$", t)  # last separator as the decimal
        if m:
            ip = re.sub(r"[ .,]", "", m.group(1))
            if ip.isdigit():
                try:
                    out.add(float(f"{ip}.{m.group(2)}"))
                except ValueError:
                    pass
    return out


def _near(val: float, nums: set[float], rel: float = 0.005) -> bool:
    return any(abs(val - n) <= max(0.05, rel * max(abs(val), abs(n))) for n in nums)


def _resolve_source(source_dir: Path | None, name: str) -> Path | None:
    """Inputs may live in subfolders (intake scans recursively) - resolve by name."""
    if not source_dir or not name:
        return None
    p = Path(source_dir) / name
    if p.is_file():
        return p
    try:
        return next((q for q in Path(source_dir).rglob("*")
                     if q.is_file() and q.name == name), None)
    except Exception:
        return None


def _load_page_texts(src: Path) -> list[str]:
    """The twin's per-page/per-slide text, '' where unreadable. [] on failure -
    reconciliation silently disengages (a scanned deck HAS no usable layer;
    that is why it went to vision in the first place)."""
    try:
        if src.suffix.lower() == ".pptx":
            from pptx import Presentation
            import extract_pptx as PPTX
            return [PPTX.slide_text(s) for s in Presentation(str(src)).slides]
        try:
            import fitz
        except Exception:
            import fitz_shim as fitz
        doc = fitz.open(str(src))
        out = []
        for i in range(doc.page_count):
            try:
                out.append(doc[i].get_text())
            except Exception:
                out.append("")
        doc.close()
        return out
    except Exception:
        return []


def validate(work: Path, source_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) across every vision file in <work>/extract, checked
    against <work>/vision/manifest.json. No manifest = nothing to validate.
    With source_dir, transcribed numerics are also reconciled against the twin
    text layer (warnings only - the layer may be legitimately absent)."""
    errors: list[str] = []
    warnings: list[str] = []
    manifest_file = work / "vision" / "manifest.json"
    decks: dict[str, dict] = {}
    if manifest_file.exists():
        try:
            for d in json.loads(manifest_file.read_text(encoding="utf-8")).get("decks", []):
                decks[_vkey(d.get("region", ""))] = {
                    "source": d.get("source_file", ""),
                    "pages": {p.get("page_no") for p in d.get("pages", [])},
                }
        except Exception as e:
            warnings.append(f"vision manifest unreadable ({e}) - page-binding checks skipped")

    for vf in sorted((work / "extract").glob("*_vision.json")):
        region = vf.name[:-len("_vision.json")]
        deck = decks.get(_vkey(region))
        # the twin text layer's numbers, per page (empty when the source is not
        # resolvable or carries no usable layer - reconciliation then disengages)
        page_nums: dict[int, set[float]] = {}
        if deck and source_dir:
            src = _resolve_source(source_dir, deck["source"])
            if src:
                page_nums = {i: _page_numbers(tx)
                             for i, tx in enumerate(_load_page_texts(src))}
        # reconcile transcribed numbers against the WHOLE deck text, NOT the hero-bound
        # page: the hero legitimately binds to a photo/aerial page while the spec numbers
        # sit on a different page, so the per-page check false-flagged correct values (a
        # confirmed false-positive generator). The deck-wide union disengages entirely when
        # the deck carries no usable text layer (image-only), so it never invents noise.
        deck_nums: set = set().union(*page_nums.values()) if page_nums else set()
        try:
            records = json.loads(vf.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{vf.name}: not valid JSON ({e})")
            continue
        if not isinstance(records, list):
            errors.append(f"{vf.name}: must be a JSON array of records")
            continue
        seen_pages: set = set()
        # __meta.image_pages cross-property uniqueness within THIS deck: page -> the
        # tag of the FIRST record that claimed it (a second, different record claiming
        # the same page is a leak across two properties of the same deck -> ERROR).
        image_page_owner: dict[int, str] = {}
        n_real = 0
        for k, r in enumerate(records, start=1):
            if not isinstance(r, dict):
                errors.append(f"{vf.name} record {k}: not an object")
                continue
            if r.get("unreadable"):
                seen_pages.add((r.get("__meta", {}) or {}).get("page_no"))
                continue
            if (r.get("__meta", {}) or {}).get("needs_raster"):
                continue  # a text-deck garble escalation stub (run.py consumes it -> raster), not a record
            n_real += 1
            meta = r.get("__meta", {}) or {}
            tag = f"{vf.name} record {k} ({str(r.get('park', '?'))[:24]})"
            pno = meta.get("page_no")
            if not isinstance(pno, int):
                errors.append(f"{tag}: __meta.page_no missing/non-integer - the hero "
                              f"binds to this page; copy the manifest's page_no VERBATIM "
                              f"(0-based; the PNG filename suffix is 1-based)")
            elif deck and deck["pages"] and pno not in deck["pages"]:
                errors.append(f"{tag}: page_no {pno} is not a rasterised page of this deck "
                              f"(manifest pages: {sorted(deck['pages'])}) - off-by-one binds "
                              f"the NEIGHBOUR'S photo")
            else:
                seen_pages.add(pno)
            # __meta.image_pages (the carousel scope): each entry must be an int >= 0
            # AND within this deck's rasterised pages (mirrors the page_no out-of-range
            # ERROR - an off-range page harvests a neighbour's photo); and no page may
            # appear in the image_pages of two DIFFERENT records (properties) of the
            # same deck (mirrors the hero mis-bind class - it would leak across
            # properties). The point-4 merge guard is the authoritative runtime enforcer;
            # this is the pre-merge advisory.
            ip = meta.get("image_pages")
            if ip is not None:
                if not isinstance(ip, list):
                    errors.append(f"{tag}: __meta.image_pages must be an array of "
                                  f"0-based integer page indices (or omitted)")
                else:
                    for p in ip:
                        if not isinstance(p, int) or isinstance(p, bool) or p < 0:
                            errors.append(f"{tag}: __meta.image_pages entry {p!r} is not a "
                                          f"non-negative integer page index")
                        elif deck and deck["pages"] and p not in deck["pages"]:
                            errors.append(f"{tag}: __meta.image_pages page {p} is not a "
                                          f"rasterised page of this deck (manifest pages: "
                                          f"{sorted(deck['pages'])}) - it would harvest a "
                                          f"NEIGHBOUR'S photo")
                        else:
                            prev = image_page_owner.get(p)
                            if prev is not None and prev != tag:
                                errors.append(f"{tag}: __meta.image_pages page {p} is also "
                                              f"claimed by {prev} - a deck page may feed only "
                                              f"ONE property's carousel (cross-property leak)")
                            else:
                                image_page_owner.setdefault(p, tag)
            # __meta.plan_page (the rendered-site-plan page): an int >= 0 (a bool is
            # rejected) AND within this deck's rasterised pages (mirrors the page_no
            # out-of-range ERROR - an off-range page would render a NEIGHBOUR'S page as
            # the plan); null/omitted is always allowed (the deterministic detector is the
            # fallback). It binds the PLAN SLOT ONLY, never the hero.
            pp = meta.get("plan_page")
            if pp is not None:
                if not isinstance(pp, int) or isinstance(pp, bool) or pp < 0:
                    errors.append(f"{tag}: __meta.plan_page {pp!r} is not a non-negative "
                                  f"integer page index (or null)")
                elif deck and deck["pages"] and pp not in deck["pages"]:
                    errors.append(f"{tag}: __meta.plan_page {pp} is not a rasterised page of "
                                  f"this deck (manifest pages: {sorted(deck['pages'])}) - it "
                                  f"would render a NEIGHBOUR'S page as the site plan")
            if deck and meta.get("source_file") and deck["source"] \
                    and meta["source_file"] != deck["source"]:
                warnings.append(f"{tag}: source_file '{meta['source_file']}' differs from "
                                f"the manifest's '{deck['source']}'")
            rv = r.get("warehouseRentVal")
            if isinstance(rv, (int, float)):
                _lo, _hi = N.rent_unit_band(r.get("rentUnit"))
                _metric = "ft" not in str(r.get("rentUnit") or "")
                if not (_lo <= rv <= _hi):
                    errors.append(f"{tag}: warehouseRentVal {rv} outside the plausibility "
                                  f"band ({_lo}-{_hi} for {r.get('rentUnit') or 'EUR/m2/yr'})")
                elif _metric and rv < RENT_LOW_SUSPECT and not re.search(
                        r"x\s*12|annualis", str(meta.get("prov", {}).get("warehouseRentVal", "")), re.I):
                    warnings.append(f"{tag}: warehouseRentVal {rv} is suspiciously low - "
                                    f"likely an UN-ANNUALISED monthly quote; if the page "
                                    f"shows /month|/mes|/Monat, multiply x12 and note the "
                                    f"conversion in prov")
            for fld in ("warehouseArea", "plotArea"):
                v = r.get(fld)
                if isinstance(v, (int, float)):
                    _au = r.get("areaUnit") or "sq m"
                    _alo, _ahi = N.area_band_for(_au)
                    if not (_alo <= v <= _ahi):
                        warnings.append(f"{tag}: {fld} {v} outside the plausibility band "
                                        f"({_alo:g}-{_ahi:g} {_au}) - re-check the read")
                    _amn = N.area_magnitude_mismatch(v, _au)
                    if _amn:
                        warnings.append(f"{tag}: {fld} {v} - {_amn}")
            lat, lng = r.get("lat"), r.get("lng")
            if lat is not None and not (isinstance(lat, (int, float)) and -90 <= lat <= 90
                                        and isinstance(lng, (int, float)) and -180 <= lng <= 180):
                errors.append(f"{tag}: lat/lng out of range ({lat}, {lng})")
            # NUMERIC RECONCILIATION vs the twin text layer: only when this page's
            # text actually carries numbers (>= 2, so a sparse/dead layer never
            # false-flags); warnings only - the reviewers re-read the page image
            # reconcile against the deck-wide number set (>= 2 so a near-empty layer never
            # false-flags); a value present ANYWHERE in the deck text is trusted, killing
            # the photo-page-vs-spec-page false positive while still catching a digit misread
            if deck_nums and len(deck_nums) >= 2:
                if isinstance(rv, (int, float)) and N.RENT_MIN <= rv <= N.RENT_MAX \
                        and not (_near(float(rv), deck_nums) or _near(float(rv) / 12.0, deck_nums)):
                    warnings.append(f"{tag}: warehouseRentVal {rv} appears NOWHERE in the "
                                    f"deck's text layer (nor as its monthly /12 form) - "
                                    f"vision digit misread suspected; re-read the page image")
                for fld in ("warehouseArea", "plotArea"):
                    v = r.get(fld)
                    if isinstance(v, (int, float)) and AREA_MIN <= v <= AREA_MAX \
                            and not _near(float(v), deck_nums):
                        warnings.append(f"{tag}: {fld} {v} appears nowhere in the deck's "
                                        f"text layer - vision digit misread suspected; "
                                        f"re-read the page image")
        if deck and deck["pages"]:
            missing = sorted(deck["pages"] - seen_pages)
            if missing:
                warnings.append(f"{vf.name}: rasterised page(s) {missing} have NO record - "
                                f"if a page shows SEVERAL properties they must be SEPARATE "
                                f"records (repeating the same page_no is correct), never "
                                f"collapsed into one")
            if n_real and n_real < len(deck["pages"]) / 2:
                warnings.append(f"{vf.name}: only {n_real} record(s) for "
                                f"{len(deck['pages'])} rasterised pages - check for "
                                f"collapsed multi-property pages")
    return errors, warnings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True)
    ap.add_argument("--folder", default=None,
                    help="inputs folder - enables the numeric cross-check vs the twin text layer")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    errors, warnings = validate(Path(args.work),
                                Path(args.folder) if args.folder else None)
    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[FAIL] {e}")
    print(f"STATUS: {'BLOCKED' if errors else 'ALL-PASS'} "
          f"({len(errors)} error(s), {len(warnings)} warning(s))")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
