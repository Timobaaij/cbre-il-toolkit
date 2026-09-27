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
    * (2026-09-26) a malformed `__meta.doubts[].combinable` or `__meta.not_an_option` flag, and
      a heroRef / planRef on a candidate the prep marked `off_page`

hoist_toplevel_prov(records) is the one PURE repair here: run.py applies it at record load so a
plain top-level `prov` is moved under __meta without a re-read; validate() never rewrites a file.

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
    # MUST stay identical to run.py's _vkey: folds every non-alphanumeric SEPARATOR (space, _,
    # -, .) but KEEPS non-ASCII letters (ł/ø/ß carry meaning), so a sub-agent's
    # `East_Midlands_vision.json` matches region `East Midlands`. Folding spaces alone left the
    # commonest sanitisation unmatched and made exit 3 non-convergent.
    folded = "".join(c for c in unicodedata.normalize("NFKD", str(s))
                     if not unicodedata.combining(c)).casefold()
    return "".join(c for c in folded if c.isalnum())


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
    """Inputs may live in subfolders (intake scans recursively) - resolve by name.

    Delegates to the SAME resolver merge uses, so the validator can never disagree with the
    runtime about which physical file a basename means. It used to take an unsorted first
    rglob hit, which was both machine-dependent and inconsistent with merge. (B13)"""
    if not source_dir or not name:
        return None
    import _common as _C
    return _C.resolve_by_name(source_dir, name)


def _load_page_texts(src: Path) -> list[str]:
    """The twin's per-page/per-slide text, '' where unreadable. [] on failure -
    reconciliation silently disengages (a scanned deck HAS no usable layer;
    that is why it went to vision in the first place)."""
    try:
        if src.suffix.lower() == ".pptx":
            from pptx import Presentation
            import extract_pptx as PPTX
            return PPTX.slide_texts(Presentation(str(src)))   # per-slide guard (#19)
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


def _hoistable(r) -> bool:
    """A record whose top-level `prov` is a plain {field: locator-string} object and whose
    `__meta` is an object or absent: moving it under __meta is lossless and purely structural,
    so the spine does it itself instead of sending the deck back (2026-09-26 test run, fix 1.5).
    Anything else (a list, a nested value, a non-object __meta) is NOT guessed at."""
    if not isinstance(r, dict):
        return False
    pv = r.get("prov")
    if not isinstance(pv, dict) or not pv:
        return False
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in pv.items()):
        return False
    meta = r.get("__meta")
    if meta is not None and not isinstance(meta, dict):
        return False
    mp = (meta or {}).get("prov")
    return mp is None or isinstance(mp, dict)


def hoist_toplevel_prov(records) -> list[dict]:
    """Move a top-level `prov` under `__meta.prov`, in place (2026-09-26 test run, fix 1.5a).

    3 of 22 readers on one run wrote `prov` beside the fields; the validator refused each and the
    only remedy was a full re-read (120-145 k tokens) for a purely structural slip. Per record that
    `_hoistable` accepts: a key `__meta.prov` lacks is moved; a key with the SAME locator there
    counts as moved (the duplicate is dropped); a key whose locator DIFFERS stays at top level
    (merge quarantines it, as before - never an overwrite). The top-level `prov` is popped when
    nothing is kept. Values and locators are never rewritten. Returns one note per changed record
    `{record (1-based), park, moved, kept_top_level}`; a second call returns []. Pure (no I/O)
    and never raises: this is the function run.py calls at record load, while validate() itself
    stays a strict checker that rewrites nothing."""
    notes: list[dict] = []
    try:
        for k, r in enumerate(records or [], start=1):
            try:
                if not _hoistable(r):
                    continue
                if not isinstance(r.get("__meta"), dict):
                    r["__meta"] = {}
                meta = r["__meta"]
                if not isinstance(meta.get("prov"), dict):
                    meta["prov"] = {}
                mp = meta["prov"]
                moved, kept = [], {}
                for fld, loc in r["prov"].items():
                    if fld not in mp:
                        mp[fld] = loc
                        moved.append(fld)
                    elif mp[fld] == loc:
                        moved.append(fld)          # identical duplicate: nothing is lost
                    else:
                        kept[fld] = loc            # a DIFFERENT locator is never overwritten
                if not moved:
                    continue
                if kept:
                    r["prov"] = kept
                else:
                    r.pop("prov", None)
                notes.append({"record": k, "park": str(r.get("park", ""))[:40],
                              "moved": moved, "kept_top_level": sorted(kept)})
            except Exception:
                continue
    except Exception:
        return notes
    return notes


def _deck_index(d: dict) -> dict:
    """What validate() keeps per manifest deck: its source, its page set and (fix 3.21) the
    candidate annotations interpret_prep wrote per page, {page_no: {index: {off_page, masked}}}."""
    cands: dict = {}
    for p in d.get("pages", []) or []:
        if not isinstance(p, dict):
            continue
        per = {}
        for c in p.get("candidates") or []:
            if isinstance(c, dict) and isinstance(c.get("index"), int):
                per[c["index"]] = {"off_page": c.get("off_page") is True,
                                   "masked": c.get("masked") is True}
        if per:
            cands[p.get("page_no")] = per
    return {"source": d.get("source_file", ""),
            "pages": {p.get("page_no") for p in d.get("pages", [])},
            "cands": cands}


def validate(work: Path, source_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) across every vision file in <work>/extract, checked
    against <work>/vision/manifest.json. No manifest = nothing to validate.
    With source_dir, transcribed numerics are also reconciled against the twin
    text layer (warnings only - the layer may be legitimately absent)."""
    errors: list[str] = []
    warnings: list[str] = []
    manifest_file = work / "vision" / "manifest.json"
    decks: dict[str, dict] = {}
    # 2026-09-26 test run, fix 3.1 item 9: each deck ALSO by the file name of its explicit
    # `output` (B2). A shared label gets a hash-suffixed output (`<label>__<sha8>_vision.json`)
    # and a relabel keeps the durable old path (B64), and neither matches the label, so every
    # page-binding check for that file was silently skipped. The output name is looked up first,
    # the label second (a legacy manifest without `output` is unchanged).
    decks_by_output: dict[str, dict] = {}
    if manifest_file.exists():
        try:
            for d in json.loads(manifest_file.read_text(encoding="utf-8-sig")).get("decks", []):
                # `cluster_label` first, `region` as the LEGACY fallback (B51) - a warm work dir
                # may hold a manifest written before the rename, and losing the deck index here
                # silently disarms every page-range check.
                ent = _deck_index(d)
                decks[_vkey(str(d.get("cluster_label") or d.get("region") or ""))] = ent
                try:
                    if d.get("output"):
                        decks_by_output[Path(str(d["output"])).name.lower()] = ent
                except Exception:
                    pass
        except Exception as e:
            warnings.append(f"vision manifest unreadable ({e}) - page-binding checks skipped")

    # TRIPWIRE: vision files present but NO decks to check them against. Every deck-gated
    # check below degrades to a silent no-op when `decks` is empty - and that is reachable
    # without anything looking wrong, because `{"decks": []}` is valid JSON so the "manifest
    # unreadable" warning above never fires. Preserving the decks on rewrite (B14, run.py) is
    # the fix; THIS is the half that cannot be silently bypassed the next time something
    # rewrites the file, so it stays even though that path is now closed. (B14)
    _vfs = sorted((work / "extract").glob("*_vision.json"))
    if _vfs and not decks:
        warnings.append(
            f"{len(_vfs)} vision file(s) present but the manifest lists NO decks - every "
            f"page-binding check (page_no / image_pages / plan_page / exclude_refs range, "
            f"the source_file cross-check and the text reconciliation) is SKIPPED for this "
            f"run. The transcriptions were not validated against their decks.")
    for vf in _vfs:
        region = vf.name[:-len("_vision.json")]
        deck = decks_by_output.get(vf.name.lower()) or decks.get(_vkey(region))
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
            records = json.loads(vf.read_text(encoding="utf-8-sig"))
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
        # Same-deck duplicate claims, judged AFTER the loop: a record later in the file
        # may anchor a page an earlier record over-claimed, and that changes the verdict. (B21)
        contested: list = []
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
            # A reader that writes `prov` beside the fields instead of under __meta: merge
            # quarantines the unknown top-level key, so every ledger row of the record ships
            # with no locator. Caught here, before merge, where "fix and re-run" is the contract.
            # 2026-09-26 test run, fix 1.5: the verdict is unchanged, the message now says which
            # of the two cases this is (run.py hoists the plain one at record load).
            if "prov" in r and not meta.get("prov"):
                errors.append(f"{tag}: top-level `prov` must be inside `__meta.prov` - merge "
                              f"drops a top-level prov and the ledger rows lose their "
                              f"locators; move the object under __meta "
                              + ("- the spine moves a {field: locator-string} `prov` under "
                                 "__meta automatically on its next pass" if _hoistable(r) else
                                 "- this one cannot be moved automatically (it is not a "
                                 "{field: locator string} object): rewrite it as one under "
                                 "__meta.prov"))
            # 2026-09-26 test run, fixes 3.2a / 3.10a: two optional reader flags. WARNINGS only -
            # a malformed flag is read as absent by its consumers (`is True`), so it can cost a
            # broker question but never a wrong card, and it is no reason to re-read a deck.
            for _d_i, _dbt in enumerate(meta.get("doubts") or [], start=1):
                if not isinstance(_dbt, dict) or "combinable" not in _dbt:
                    continue
                _cb = _dbt.get("combinable")
                if not isinstance(_cb, bool):
                    warnings.append(f"{tag}: __meta.doubts[{_d_i}].combinable is {_cb!r}, not "
                                    f"true/false - it is ignored (no combined option is offered)")
                elif _cb and (not _dbt.get("field") or not isinstance(_dbt.get("options"), list)
                              or len(_dbt.get("options") or []) < 2):
                    warnings.append(f"{tag}: __meta.doubts[{_d_i}].combinable is true but the "
                                    f"doubt lacks a `field` or two or more `options` - nothing "
                                    f"can be combined, so it is ignored")
            if "not_an_option" in meta:
                _na = meta.get("not_an_option")
                if not isinstance(_na, bool):
                    warnings.append(f"{tag}: __meta.not_an_option is {_na!r}, not true/false - "
                                    f"it is ignored, so no broker question is raised for it")
                elif _na and not str(r.get("status") or "").strip():
                    warnings.append(f"{tag}: __meta.not_an_option is true but the record has no "
                                    f"`status` - copy the source's own let/sold wording into "
                                    f"`status` (with its prov) so the card and the broker see it")
            # 2026-09-26 test run, fix 3.21: a hero / plan bound to a candidate the page never
            # SHOWS (placed wholly outside the visible page) is a leftover graphic, not a pick.
            if deck and isinstance(pno, int):
                _pc = (deck.get("cands") or {}).get(pno) or {}
                for _rk in ("heroRef", "planRef"):
                    _ri = meta.get(_rk)
                    if (isinstance(_ri, int) and not isinstance(_ri, bool)
                            and (_pc.get(_ri) or {}).get("off_page")):
                        warnings.append(f"{tag}: __meta.{_rk} {_ri} on page {pno} is a candidate "
                                        f"marked off_page (placed outside the visible page, so "
                                        f"the brochure never shows it) - pick a visible image or "
                                        f"null")
            # __meta.image_pages (the carousel scope): each entry must be an int >= 0
            # AND within this deck's rasterised pages (mirrors the page_no out-of-range
            # ERROR - an off-range page harvests a neighbour's photo); and no page may
            # appear in the image_pages of two DIFFERENT records (properties) of the
            # same deck (mirrors the hero mis-bind class - it would leak across
            # properties). The point-4 merge guard is the authoritative runtime enforcer;
            # this is the pre-merge advisory.
            # REQUIRED-KEY NOTE (multi-page decks only). `image_pages` and `plan_page` are
            # contractually REQUIRED on a deck of more than one page - an explicit `[]`/`null`
            # is a legitimate answer, SILENCE is not, because the two used to be written
            # identically and that is how a run whose readers were handed no visual aids at all
            # produced fourteen decks that looked like fourteen honest "one page, no plan"
            # verdicts. A WARNING, deliberately not an ERROR: an error sends the whole deck back
            # for re-reading over a key whose honest answer may well be "none", which trains the
            # re-dispatch reflex and converges on nothing. The note names the record, the
            # media-harvest gate counts the consequence, and a reviewer decides.
            if deck and len(deck["pages"] or ()) > 1:
                _absent_keys = [k2 for k2 in ("image_pages", "plan_page") if k2 not in meta]
                if _absent_keys:
                    warnings.append(
                        f"{tag}: __meta {' and '.join(_absent_keys)} "
                        f"{'are' if len(_absent_keys) > 1 else 'is'} ABSENT on a "
                        f"{len(deck['pages'])}-page deck - these keys are required there, and "
                        f"an explicit `[]` / `null` is a fine answer. An omission cannot be "
                        f"told apart from a reader that was handed no page renders and could "
                        f"not look at all (see work/vision/visual_aids.json)")
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
                                contested.append((p, prev, tag))
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
                elif isinstance(pno, int) and pp == pno:
                    # page_no must be the property's OWN hero-PHOTO page; putting its plan/divider
                    # page number in page_no binds the hero AND the whole carousel to the plan page
                    # (this shipped a decorative/plan graphic as the hero). WARN not ERROR - a
                    # genuine plan-only-hero property legitimately has page_no == plan_page.
                    warnings.append(f"{tag}: __meta.page_no equals __meta.plan_page ({pno}) - "
                                    f"page_no must be the property's OWN hero-PHOTO page, NOT its "
                                    f"plan/divider page (put the plan in plan_page, extra photo "
                                    f"pages in image_pages). Legitimate ONLY for a genuine "
                                    f"plan-only-hero property; otherwise the hero + carousel bind "
                                    f"to the plan page.")
            # __meta.exclude_refs (the interpreter's decorative-candidate deny-list): a map of
            # 0-based page (string key) -> candidate indices to drop from the carousel. Each key
            # must be a page of this deck; each index a non-negative int; and it must NEVER exclude
            # the heroRef candidate on the hero page (that would blank the carousel lead).
            er = meta.get("exclude_refs")
            if er is not None:
                if not isinstance(er, dict):
                    errors.append(f"{tag}: __meta.exclude_refs must be an object mapping a 0-based "
                                  f"page (string key) to an array of candidate indices (or omitted)")
                else:
                    href = meta.get("heroRef")
                    for pg_k, refs in er.items():
                        try:
                            pg_i = int(pg_k)
                        except (TypeError, ValueError):
                            errors.append(f"{tag}: __meta.exclude_refs key {pg_k!r} is not a page index")
                            continue
                        if deck and deck["pages"] and pg_i not in deck["pages"]:
                            errors.append(f"{tag}: __meta.exclude_refs page {pg_i} is not a rasterised "
                                          f"page of this deck (manifest pages: {sorted(deck['pages'])})")
                        if not isinstance(refs, list):
                            errors.append(f"{tag}: __meta.exclude_refs[{pg_k!r}] must be an array of "
                                          f"0-based candidate indices")
                            continue
                        for r_ in refs:
                            if not isinstance(r_, int) or isinstance(r_, bool) or r_ < 0:
                                errors.append(f"{tag}: __meta.exclude_refs[{pg_k!r}] entry {r_!r} is "
                                              f"not a non-negative integer candidate index")
                            elif isinstance(href, int) and pg_i == pno and r_ == href:
                                errors.append(f"{tag}: __meta.exclude_refs excludes the heroRef "
                                              f"candidate ({href}) on the hero page - the hero must "
                                              f"NOT be excluded from its own carousel")
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
                    # `field=fld` is load-bearing, not tidiness: a SITE is not a building, so
                    # plotArea takes PLOT_SQM_MAX / PLOT_SQFT_MAX. Omitting it judged every
                    # plot against the BUILDING ceiling, which is the T1 false-absence class
                    # one layer down - a 630,000 sq m park plot, or a 400-acre park site, both
                    # called routine by normalize's own band commentary, drew a "re-check the
                    # read" advisory telling a reviewer to doubt a figure the page plainly
                    # prints. This is a printed WARNING and never a strike, so the cost was
                    # reviewer time and the band's credibility rather than data; a band that
                    # cries wolf is still a band nobody reads.
                    # `field` can only ever WIDEN the ceiling and never touches the floor, so
                    # adding it here cannot newly warn about anything.
                    # WHAT IS NOT FIXED HERE, stated rather than assumed: this is also the one
                    # `area_band_for` caller that does NOT union the unit-aware band with the
                    # unit-unknown one the way merge's gate does, and `areaUnit` on a vision
                    # record is NOT checked against the canonical enum anywhere above, so a
                    # transcription is free to hand this line "acres", "ha" or "sq ft". Knowing
                    # the unit is therefore not monotonic here - the sq ft branch raises the
                    # FLOOR from 300 to 3,000 - and a 1,200 sq ft record can draw a spurious
                    # advisory. That predates this line and is out of scope for a warning-only
                    # path; the union belongs here too if this ever becomes an errors[] check.
                    _alo, _ahi = N.area_band_for(_au, field=fld)
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
        # SAME-DECK image_pages over-claim: a WARNING, never a round-trip. (B21)
        #
        # This used to be a blocking ERROR, which cost an exit-3 re-dispatch on a shape the
        # contract SANCTIONS: reference/interpretation.md promises the interpreter that "an
        # honest over-list is never leaked to a property that did not list it", and merge's
        # claimant guards (build_foreign_pages / _page_allowed) enforce exactly that.
        # It also fired on the blessed "two properties on ONE page" topology, where a fresh
        # sub-agent reading the same contract returns the same answer - a non-convergent
        # streak, not a fix. Two outcomes, and they differ in consequence, so they are worded
        # differently rather than merged:
        #   anchored   - one record's page_no IS this page: merge awards it to that record and
        #                drops the other's claim. Provably a no-op; noted for visibility only.
        #   unanchored - nobody (or more than one record) anchors it, so merge SHARES it between
        #                the claiming properties' carousels and keeps it out of every Site Plan
        #                slot (2026-09-26 test run, fix 3.20). Worth a note, never an error: the
        #                reader may want it on only the property it shows.
        # The genuinely protective branch is a DIFFERENT one (a page outside this deck's
        # rasterised range, above) and stays an ERROR. Note that with B14 open - the region
        # emitter overwriting the manifest with `decks: []` - `deck` is None, that range check
        # is silently skipped, and this was the ONE image_pages check still firing.
        anchored = {p for p in seen_pages if isinstance(p, int) and not isinstance(p, bool)}
        for p, prev, tag in contested:
            if p in anchored:
                warnings.append(f"{tag}: __meta.image_pages page {p} is also claimed by "
                                f"{prev}; merge awards it to the record that ANCHORS it "
                                f"(page_no == {p}) and drops the other claim - no leak, "
                                f"nothing to fix")
            else:
                warnings.append(f"{tag}: __meta.image_pages page {p} is also claimed by "
                                f"{prev} and NO record anchors it, so merge SHARES it between "
                                f"the claiming properties' carousels (never their Site Plan "
                                f"slot). If the page shows only one of them, list it on that "
                                f"one")
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
