#!/usr/bin/env python3
"""interpret_prep.py - Stage 1 brochure INTERPRETATION prep (DETERMINISTIC half).

The skill no longer reads brochure FIELDS with extract_pdf's label dictionary (a
losing battle for the heterogeneous long tail: every agent/country/template names
things differently). Instead an isolated INTERPRETATION sub-agent structures each
brochure deck, and this helper prepares the deck for it - picking the cheaper of
two modes PER DECK and emitting a manifest deck entry:

  * mode "text"   - the deck has a substantial selectable text layer, so the
                    sub-agent reads the EXTRACTED TEXT (per page, with locator).
                    ~10-20x cheaper + faster than rasterising (a 15-page deck is
                    ~2k text tokens vs ~30-60k image tokens) and just as accurate
                    for a born-digital flyer.
  * mode "raster" - the text layer is sparse/absent/garbled (a scan, an image
                    export, a vector slide), so we DELEGATE to vision_prep.prepare()
                    for the page PNGs and the sub-agent reads images (today's
                    vision path, unchanged).

It does NOT interpret - interpretation is the agentic step. The orchestrator
dispatches the sub-agent (reference/interpretation.md), which writes candidate
records (templates/record_schema.json) to work/extract/<region>_vision.json (the
"LLM-produced records" slot, reused unchanged so merge/gates need no change). See
reference/interpretation.md for the sub-agent contract (both modes).

A deck routes to "raster" only when its text layer cannot carry the data; a normal
born-digital deck stays on the cheap "text" path. xlsx trackers and emails are NOT
prepared here - they stay on their deterministic, reliable extractors.

CLI:
  python interpret_prep.py <file.pdf|.pptx> --region R --country C --out-dir work/vision
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import fitz  # PyMuPDF
except Exception:  # sandbox without PyMuPDF: pypdfium2/pdfplumber shim
    import fitz_shim as fitz
try:
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass
import vision_prep as VP
import images as IMG

# max edge (px) of a candidate thumbnail written for the interpretation sub-agent to LOOK
# at. ~384 is legible enough to tell a photo from a map/plan/logo (the only judgment the
# sub-agent makes about an image) while staying tiny - the thumbnails are NOT embedded in
# any record, so they never affect built.html bytes; only the chosen ref does.
CANDIDATE_THUMB_EDGE = 384

# max edge (px) of the PER-PAGE RENDER thumbnail written so the sub-agent can SEE a
# plan-only (low-text) page and pick __meta.plan_page. The whole page is RENDERED (so VECTOR
# line-art a placed-image crop cannot reach is visible) and downscaled small + cached per
# (source, page). Like the candidate thumbnails it is NOT embedded in any record, so it never
# affects built.html bytes; only the chosen plan_page integer does. None when the deck cannot
# be rendered (the shim/pdfplumber-only tier) - the page is still listed, just without a render.
PAGE_RENDER_THUMB_EDGE = 480
# dpi for the per-page render thumbnail - low (the thumb is downscaled small anyway), so the
# render cost stays bounded across a deck; the stage is per-(source,page) resumable.
PAGE_RENDER_THUMB_DPI = 90

# A page "carries text" when it has at least this many characters of extractable
# text. ~80 chars is roughly one or two spec lines - below it a page is a cover,
# a divider, a photo plate or a scan, none of which the text path can read.
TEXT_PAGE_MIN_CHARS = 80
# A deck is interpreted from TEXT when at least this fraction of its pages carry
# text; otherwise it is rasterised (the deck is a scan / image export / vector).
# Half is conservative: a born-digital flyer with photo plates between spec pages
# still routes to the cheap text path, while a mostly-image scan escalates.
TEXT_DECK_MIN_RATIO = 0.5


def _pdf_page_texts(path: Path) -> list[str]:
    """Per-page extractable text for a PDF, one string per page (0-based index).
    Never raises - a damaged page yields '' and a deck that will not open yields
    []; the caller then routes to raster (an honest absence, never a crash)."""
    try:
        doc = fitz.open(path)
    except Exception:
        return []
    texts: list[str] = []
    try:
        for pno in range(doc.page_count):
            try:
                texts.append(doc[pno].get_text() or "")
            except Exception:
                texts.append("")
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return texts


def _pptx_slide_texts(path: Path) -> list[str]:
    """Per-slide text for a PPTX (0-based index), via the same extractor vision_prep
    uses for its needs-vision test. [] when python-pptx is unavailable -> raster."""
    try:
        from pptx import Presentation
        import extract_pptx as PPTX
        prs = Presentation(str(path))
        return PPTX.slide_texts(prs)   # per-slide guard: one bad slide -> '' not a dead deck (#19)
    except Exception:
        return []


def _decide_mode(page_texts: list[str]) -> str:
    """'text' when at least TEXT_DECK_MIN_RATIO of the pages carry >= TEXT_PAGE_MIN_CHARS
    characters, else 'raster'. No pages at all (unopenable / textless) -> 'raster'."""
    if not page_texts:
        return "raster"
    with_text = sum(1 for t in page_texts if len((t or "").strip()) >= TEXT_PAGE_MIN_CHARS)
    return "text" if with_text >= TEXT_DECK_MIN_RATIO * len(page_texts) else "raster"


def _stamp_path(out_dir: Path, path: Path) -> Path:
    return out_dir / f"{path.stem}.interpret.stamp.json"


def _thumbs_present(entry: dict) -> bool:
    """True when every candidate thumbnail AND every per-page render thumbnail the cached
    TEXT entry references still exists - so a capped re-run reuses them, but a kill that lost
    a thumbnail recomputes the entry (the resume guard for the candidate + render images)."""
    try:
        for pg in entry.get("pages", []):
            for c in pg.get("candidates", []):
                img = c.get("image")
                if img and not Path(img).exists():
                    return False
            rnd = pg.get("render")
            if rnd and not Path(rnd).exists():
                return False
        return True
    except Exception:
        return False


def _write_candidate_thumbs(path: Path, page_index: int, out_dir: Path) -> list[dict]:
    """Write a small thumbnail PNG per hero-size embedded candidate of a page and return
    [{index, image (abs path), w, h}]. The `index` EQUALS the candidate's position in
    IMG.candidates_for_page (the SAME stable filtered order merge re-derives via
    embedded_by_index), so the sub-agent's chosen heroRef binds the exact image. The
    thumbnail is only what the sub-agent LOOKS at; the chosen ref (not the thumbnail) is
    what reaches the record, so determinism / built.html bytes are untouched. Never raises -
    a thumbnail it cannot decode/write is simply omitted (an honest absence, not a crash)."""
    out: list[dict] = []
    try:
        cands = IMG.candidates_for_page(path, page_index)
    except Exception:
        return out
    for c in cands:
        thumb = out_dir / f"{path.stem}_p{page_index}_c{c['index']}.png"
        try:
            im = c["img"].convert("RGB")
            im.thumbnail((CANDIDATE_THUMB_EDGE, CANDIDATE_THUMB_EDGE))
            im.save(str(thumb), "PNG")
        except Exception:
            continue  # undecodable candidate - skip it, never abort the page
        out.append({"index": c["index"], "image": str(thumb.resolve()),
                    "w": c["w"], "h": c["h"]})
    return out


def _write_page_render(path: Path, page_index: int, out_dir: Path) -> str | None:
    """Render the WHOLE page small and write a downscaled thumbnail PNG so the sub-agent can
    SEE the page (incl. VECTOR line-art a placed-image crop cannot reach) and pick
    __meta.plan_page. Returns the absolute thumbnail path, or None when the deck cannot be
    rendered (the pdfplumber-only shim has no rasteriser) - the page is still listed, the
    sub-agent simply has no render for it (an honest absence). RESUMABLE: an existing
    thumbnail for this (source, page) is reused, never re-rendered (matched by the source
    stamp in prepare()'s resume guard). Never raises - the render thumbnail is what the agent
    LOOKS at; only the chosen plan_page integer reaches the record, so determinism / built.html
    bytes are untouched."""
    if IMG.Image is None:
        return None
    thumb = out_dir / f"{path.stem}_p{page_index}_render.png"
    if thumb.exists() and thumb.stat().st_size > 0:
        return str(thumb.resolve())  # resume: reuse the rendered page thumbnail
    try:
        if path.suffix.lower() == ".pptx":
            pdf = IMG.soffice_pdf(path, out_dir)
            if pdf is None:
                return None
            doc = IMG._get_doc(pdf)
        else:
            doc = IMG._get_doc(path)
        if not (0 <= page_index < doc.page_count):
            return None
        raster = IMG.page_raster(doc, page_index, dpi=PAGE_RENDER_THUMB_DPI)
        if raster is None:
            return None
        im = raster.convert("RGB")
        im.thumbnail((PAGE_RENDER_THUMB_EDGE, PAGE_RENDER_THUMB_EDGE))
        im.save(str(thumb), "PNG")
    except Exception:
        return None  # renderer-less / open failure -> the page is listed without a render
    return str(thumb.resolve())


def _text_deck_entry(path: Path, region: str, country: str, page_texts: list[str],
                     source_type: str, out_dir: Path) -> dict:
    """A TEXT-mode manifest deck entry: each page carries {page_no (0-based),
    locator ('page'/'slide' N, 1-based label), text, candidates, render} and, on a
    low-text page, low_text:true. EVERY page is now listed - including a plan-only
    (low-text) page - so the sub-agent can SEE it (via the per-page render) and pick
    __meta.plan_page / __meta.image_pages, but a low-text page is VISUAL REFERENCE ONLY
    (it carries the low_text flag and the contract says NEVER emit a record for it). page_no
    stays the CANONICAL 0-based index so __meta.page_no binds the property to its OWN page,
    never a neighbour's.

    `candidates` is the page's hero-size embedded images, each with a stable 0-based
    `index` (== its position in IMG.candidates_for_page, which merge re-derives) and a
    thumbnail `image` path for the sub-agent to LOOK at when choosing __meta.heroRef /
    __meta.planRef. `render` is a small downscaled thumbnail of the WHOLE page render (so a
    VECTOR site plan, invisible as an embedded image, is visible) for picking
    __meta.plan_page; None when this deck cannot be rendered (the pdfplumber-only shim)."""
    unit = "slide" if source_type == "pptx" else "page"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for pno, text in enumerate(page_texts):
        t = (text or "").strip()
        low_text = len(t) < TEXT_PAGE_MIN_CHARS
        page = {"page_no": pno, "locator": f"{unit} {pno + 1}", "text": text,
                "candidates": _write_candidate_thumbs(path, pno, out_dir),
                "render": _write_page_render(path, pno, out_dir)}
        if low_text:
            # a cover/divider/photo plate / VECTOR PLAN page - nothing to interpret as a
            # RECORD, but offered so the agent can pick it as plan_page / an image_page. The
            # contract (reference/interpretation.md) says NEVER emit a record for a low_text page.
            page["low_text"] = True
        pages.append(page)
    # candidate + render extraction opens the deck via IMG's shared doc cache; release the
    # handle so the prep step never holds the source file open (on Windows a held handle blocks
    # a caller's temp-dir cleanup, and prep is a discrete step that owns no later image work).
    try:
        IMG.close_doc_cache()
    except Exception:
        pass
    return {"source_file": path.name, "source_type": source_type, "region": region,
            "country": country, "mode": "text", "pages": pages}


def prepare(path: Path, region: str, country: str, out_dir, dpi: int = 180,
            force: bool = True, resume: bool = True) -> dict:
    """Prepare ONE brochure deck for interpretation and return a manifest deck entry
    {source_file, source_type, region, country, mode, pages:[...]}.

    mode "text":   pages carry {page_no, locator, text} - the sub-agent reads text.
    mode "raster": delegates to vision_prep.prepare() (reused unchanged) for the page
                   PNGs; pages carry {page_no, locator, image, reason}.

    Per-deck RESUMABLE via a stamp (same idiom as vision_prep): a TEXT deck whose
    source bytes are unchanged reuses the cached manifest entry instead of
    re-reading the PDF/PPTX text on every shell-capped re-run. Raster decks resume
    per-page inside vision_prep (its own stamp). Pure/native; never crashes when
    fitz degrades to the shim - it just yields fewer text chars and may route to
    raster.

    `force` is accepted for signature-parity with vision_prep.prepare() and passed
    through on the raster path (a brochure is always interpreted whole)."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    st = path.suffix.lower().lstrip(".")

    # per-deck resume: reuse the cached TEXT entry when the source bytes match the
    # stamp (raster entries are NOT cached here - vision_prep owns that resume).
    stamp = _stamp_path(out_dir, path)
    cur = None
    try:
        s = path.stat()
        cur = {"size": s.st_size, "mtime_ns": s.st_mtime_ns}
        # honour --no-resume: only serve the cached entry when resuming (run.py threads
        # its RESUME flag in). The text entry is a pure function of the source bytes, so
        # a cache hit is byte-identical anyway - but an explicit recompute is honoured.
        if resume and stamp.exists():
            saved = json.loads(stamp.read_text(encoding="utf-8"))
            entry = saved.get("entry", {})
            # reuse the cached TEXT entry (incl. the candidate thumbnails) ONLY when the
            # source bytes match AND every cached candidate thumbnail still exists on disk -
            # a capped re-run then reuses the thumbnails, but a kill that lost a thumbnail
            # mid-write recomputes the entry instead of pointing the sub-agent at a missing
            # file. The text entry is a pure function of the source bytes, so a hit is
            # byte-identical anyway.
            if (saved.get("key") == cur and entry.get("mode") == "text"
                    and _thumbs_present(entry)):
                # the page payload + thumbnails are a pure function of the source BYTES and are
                # reused as-is, but region/country are MANIFEST INPUTS supplied by the caller:
                # intake can re-cluster a deck to a corrected region on a resume (reference/
                # config.md), and the stamp key is bytes-only - so refresh them on the reused
                # entry, or the sub-agent saves the record under the STALE <region>_vision.json
                # slot (run.py's manifest says 'region EXACTLY as in this manifest'). vision_prep
                # already rebuilds these fresh every call. (#28/#37)
                entry["region"] = region
                entry["country"] = country
                return entry
    except Exception:
        cur = None

    if st == "pptx":
        page_texts = _pptx_slide_texts(path)
    else:  # treat anything else as a PDF (intake only routes pdf/pptx brochures here)
        page_texts = _pdf_page_texts(path)

    mode = _decide_mode(page_texts)

    if mode == "text":
        entry = _text_deck_entry(path, region, country, page_texts, st, out_dir)
        if cur is not None:
            try:
                stamp.write_text(json.dumps({"key": cur, "entry": entry}, ensure_ascii=False),
                                 encoding="utf-8")
            except Exception:
                pass
        return entry

    # RASTER: reuse vision_prep.prepare() verbatim for the page PNGs, then tag mode.
    entry = VP.prepare(path, region, country, out_dir, dpi=dpi, force=force)
    entry["mode"] = "raster"
    return entry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--region", required=True)
    ap.add_argument("--country", required=True)
    ap.add_argument("--out-dir", default="vision")
    ap.add_argument("--dpi", type=int, default=180,
                    help="raster dpi for the raster-mode fallback (text mode ignores it)")
    ap.add_argument("--force", action="store_true", default=True,
                    help="rasterise EVERY page on the raster path (a brochure is interpreted whole)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    ent = prepare(Path(args.file), args.region, args.country, args.out_dir, args.dpi,
                  force=args.force)
    print(json.dumps(ent, ensure_ascii=False, indent=2))
    if ent.get("mode") == "text":
        print(f"OK mode=text: {len(ent['pages'])} page(s) of text -> interpret per "
              f"reference/interpretation.md")
    else:
        print(f"OK mode=raster: {len(ent['pages'])} page(s) rasterised for vision -> {args.out_dir}")


if __name__ == "__main__":
    main()
