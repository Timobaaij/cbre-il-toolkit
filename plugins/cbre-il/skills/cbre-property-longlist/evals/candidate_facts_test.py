#!/usr/bin/env python3
"""candidate_facts_test.py - candidate placement facts for the reader (2026-09-26 test run,
fixes 3.21 and 3.22). ANNOTATE, NEVER FILTER.

THE DEFECTS (one live 22-deck run, 220 candidates):
  3.21  readers saw solid-black candidate tiles and could not tell why: 41 candidates carry a soft
        mask (the raw base of an overlay is a black silhouette), 15 are placed ENTIRELY outside the
        visible page (a leftover the brochure never shows) - one was the only candidate on its page.
  3.22  8 pages showed photos in their render but listed zero candidates: every photo on them is
        below the 640x400 hero floor, a correct floor applied silently, which reads as an
        extraction failure.

THE FIX. images.page_image_facts() reads masks and placement per image; interpret_prep annotates
each candidate `masked` / `visible_fraction` / `off_page` and a page `images_below_hero_floor`;
vision_validate warns on a heroRef / planRef bound to an off-page candidate. The candidate INDEX
SPACE is frozen (it is what every in-flight heroRef binds to), so nothing is removed or reordered.

What this pins (synthetic PDF, no client data):
  1. the candidates_for_page index list is identical with the facts on and with them off;
  2. the manifest annotates exactly the masked and the off-page candidate, nothing else;
  3. a page of only sub-floor photos says `images_below_hero_floor: 2` with no candidates;
     a page with only a hero-size photo carries no such key;
  4. captions on the per-page and deck sheets carry ` off-page` / ` masked`;
  5. a heroRef on the off-page candidate draws exactly one validator warning, no error;
  6. fail-safe: page_image_facts raising -> the entry still builds, with no annotation keys;
  7. the text reader common file tells the reader what the flags mean.

Run: python evals/candidate_facts_test.py"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

try:
    import fitz  # noqa: E402
except Exception:  # pragma: no cover - the shim cannot build the fixture
    fitz = None
import images as IMG  # noqa: E402
import interpret_prep as IP  # noqa: E402
import contact_sheet as CS  # noqa: E402
import vision_validate as VV  # noqa: E402
import prompts_render as PR  # noqa: E402

FILLER = ("Unit specification: warehouse area 12,500 sq m, clear height 12 m, 10 dock doors, "
          "two level access doors, 40 m yard depth, BREEAM Very Good. ")


def _png(color, size, mode="RGB") -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new(mode, size, color).save(b, "PNG")
    return b.getvalue()


def _fixture(path: Path) -> None:
    doc = fitz.open()
    # page 0: visible 1000x700, masked RGBA 900x600, and an 800x500 placed in the margin that the
    # CropBox then cuts off (all hero-size, so all three are candidates, area order 0, 1, 2)
    p = doc.new_page(width=1000, height=800)
    p.insert_text((20, 700), FILLER, fontsize=8)
    p.insert_image(fitz.Rect(10, 10, 410, 290), stream=_png((200, 40, 40), (1000, 700)))
    p.insert_image(fitz.Rect(10, 400, 410, 667), stream=_png((40, 40, 200, 120), (900, 600), "RGBA"))
    p.insert_image(fitz.Rect(820, 10, 990, 116), stream=_png((40, 200, 40), (800, 500)))
    p.set_cropbox(fitz.Rect(0, 0, 800, 800))
    # page 1: two photos below the hero floor (480x344), nothing hero-size
    p = doc.new_page(width=800, height=600)
    p.insert_text((20, 560), FILLER, fontsize=8)
    p.insert_image(fitz.Rect(10, 10, 390, 282), stream=_png((120, 90, 30), (480, 344)))
    p.insert_image(fitz.Rect(400, 10, 780, 282), stream=_png((30, 120, 90), (480, 344)))
    # page 2: one hero-size photo only
    p = doc.new_page(width=800, height=600)
    p.insert_text((20, 560), FILLER, fontsize=8)
    p.insert_image(fitz.Rect(10, 10, 790, 500), stream=_png((90, 30, 120), (1200, 750)))
    doc.save(str(path))
    doc.close()


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    if fitz is None or IMG.Image is None or not hasattr(fitz, "Rect"):
        print("[SKIP] native PyMuPDF + Pillow are needed to build the fixture")
        print("\nPASS candidate_facts_test (skipped)")
        return 0

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pdf = td / "Facts Deck.pdf"
        _fixture(pdf)

        # 1. the index space is frozen
        cfp = IMG.candidates_for_page(pdf, 0)
        IMG.close_doc_cache()
        check([(c["index"], c["w"], c["h"]) for c in cfp] == [(0, 1000, 700), (1, 900, 600),
                                                                (2, 800, 500)],
              f"page 0 lists the three hero-size candidates in area order "
              f"({[(c['index'], c['w'], c['h']) for c in cfp]})")
        check(all(isinstance(c.get("xref"), int) for c in cfp),
              "candidates_for_page carries each candidate's PDF xref (additive)")
        facts = IMG.page_image_facts(pdf, 0)
        IMG.close_doc_cache()
        bx = facts.get("by_xref") or {}
        f_by_idx = {c["index"]: bx.get(c["xref"]) or {} for c in cfp}
        check(f_by_idx[1].get("masked") is True and not f_by_idx[0].get("masked")
              and not f_by_idx[2].get("masked"), "facts: exactly the RGBA image is masked")
        check(f_by_idx[2].get("visible") == 0.0 and (f_by_idx[0].get("visible") or 0) > 0.95,
              f"facts: the margin image is 0% visible, the normal one fully "
              f"({f_by_idx[2].get('visible')}, {f_by_idx[0].get('visible')})")

        saved = IMG.page_image_facts
        try:
            IMG.page_image_facts = lambda *a, **k: {}
            base = IP.prepare(pdf, "Facts", "XX", td / "v_off", resume=False)
        finally:
            IMG.page_image_facts = saved
        ent = IP.prepare(pdf, "Facts", "XX", td / "v_on", resume=False)
        pages = {p["page_no"]: p for p in ent.get("pages", [])}
        bpages = {p["page_no"]: p for p in base.get("pages", [])}
        check(ent.get("mode") == "text", f"the fixture routes to text mode ({ent.get('mode')})")
        check([(c["index"], c["w"], c["h"]) for c in pages[0]["candidates"]]
              == [(c["index"], c["w"], c["h"]) for c in bpages[0]["candidates"]],
              "the manifest's candidate list is IDENTICAL with the facts on and off (no filter)")

        # 2. annotations on exactly the right indices
        c0 = {c["index"]: c for c in pages[0]["candidates"]}
        check(set(c0[0]) == {"index", "image", "w", "h"},
              f"candidate 0 (visible, unmasked) carries no annotation ({sorted(c0[0])})")
        check(c0[1].get("masked") is True and "off_page" not in c0[1],
              "candidate 1 is annotated masked (and only that)")
        check(c0[2].get("off_page") is True and c0[2].get("visible_fraction") == 0.0
              and "masked" not in c0[2], "candidate 2 is annotated off_page, visible_fraction 0.0")
        check(all(set(c) == {"index", "image", "w", "h"} for c in bpages[0]["candidates"]),
              "with no facts, no annotation key appears (today's manifest)")

        # 3. the sub-floor page and the hero-only page
        check(pages[1].get("candidates") == [] and pages[1].get("images_below_hero_floor") == 2,
              f"page 1: no candidates, images_below_hero_floor == 2 "
              f"({pages[1].get('images_below_hero_floor')})")
        check("images_below_hero_floor" not in pages[2] and len(pages[2]["candidates"]) == 1,
              "page 2: a hero-size photo only -> no images_below_hero_floor key")
        check("images_below_hero_floor" not in pages[0],
              "page 0: the off-page image is not counted as a sub-floor photo")
        check(ent.get("visual_aids", {}).get("below_floor_images") == 2,
              "visual_aids counts the sub-floor photos for the media-harvest gate")

        # 4. captions carry the flags (per-page sheet and deck sheet)
        seen: list = []
        real = CS.tile_native

        def spy(cells, out_path, *a, **k):
            seen.append((Path(out_path).name, [c.get("caption") for c in cells]))
            return real(cells, out_path, *a, **k)

        CS.tile_native = spy
        try:
            IP.prepare(pdf, "Facts", "XX", td / "v_cap", resume=False)
        finally:
            CS.tile_native = real
        per_page = next((caps for n, caps in seen if n.endswith("_p0_sheet.png")), [])
        deck = next((caps for n, caps in seen if n.endswith("_deck_candidates.png")), [])
        check(per_page == ["index 0", "index 1 masked", "index 2 off-page"],
              f"per-page sheet captions carry the flags ({per_page})")
        check("page_no 0 / index 2 off-page" in deck and "page_no 0 / index 1 masked" in deck
              and "page_no 2 / index 0" in deck,
              f"deck sheet captions carry page_no, index and the flags ({deck})")

        # 5. the validator warns on a hero bound to the off-page candidate
        work = td / "work"
        (work / "vision").mkdir(parents=True)
        (work / "extract").mkdir()
        e2 = dict(ent, output="work/extract/Facts_vision.json")
        (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [e2]}),
                                                         encoding="utf-8")

        def _out(href):
            recs = [{"park": "Facts Park", "__meta": {
                "source_file": pdf.name, "source_type": "pdf", "page_no": 0, "heroRef": href,
                "image_pages": [0, 1, 2], "plan_page": None,
                "prov": {"park": "page 1 (text interpretation)"}}}]
            (work / "extract" / "Facts_vision.json").write_text(json.dumps(recs), encoding="utf-8")
            return VV.validate(work)

        e, w = _out(2)
        offw = [x for x in w if "off_page" in x]
        check(not e and len(offw) == 1 and "heroRef 2" in offw[0],
              f"heroRef on the off-page candidate -> one warning, no error ({ascii(offw[:1])})")
        e, w = _out(0)
        check(not e and not any("off_page" in x for x in w),
              "heroRef on a visible candidate -> no off-page note")

        # 6. fail-safe
        def boom(*a, **k):
            raise RuntimeError("synthetic facts failure")

        IMG.page_image_facts = boom
        try:
            ent3 = IP.prepare(pdf, "Facts", "XX", td / "v_boom", resume=False)
        finally:
            IMG.page_image_facts = saved
        p3 = {p["page_no"]: p for p in ent3.get("pages", [])}
        check(ent3.get("mode") == "text" and len(p3.get(0, {}).get("candidates") or []) == 3
              and all(set(c) == {"index", "image", "w", "h"} for c in p3[0]["candidates"])
              and "images_below_hero_floor" not in p3.get(1, {}),
              "page_image_facts raising -> the entry builds with no annotation keys")
        check(IMG.page_image_facts(td / "missing.pdf", 0) == {}
              and IMG.page_image_facts(td / "x.pptx", 0) == {},
              "page_image_facts never raises: {} for a missing file or a PPTX")
        IMG.close_doc_cache()

        # 7. the reader is told what the flags mean
        (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [], "fields": []}),
                                                         encoding="utf-8")
        PR.write_prompts(work, [("reader-text", "Facts_vision", {
            "DECK_NAME": pdf.name, "SOURCE_TYPE": "pdf", "PAGE_COUNT": 3, "COUNTRY": "XX",
            "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
            "OUTPUT_PATH": str(work / "extract" / "Facts_vision.json")})])
        common = (work / "prompts" / PR.COMMON_DIRNAME / "reader-text.md").read_text(encoding="utf-8")
        for n in ("off_page", "masked", "images_below_hero_floor", "never `heroRef` or `planRef`",
                  "not an extraction failure"):
            check(n in common, f"reader-text common file explains {n!r}")

    print(f"\n{'PASS' if not fails else 'FAIL'} candidate_facts_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
