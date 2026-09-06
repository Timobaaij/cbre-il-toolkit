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
import _common as C  # atomic_save_image: these thumbnails are handoff artefacts (B16)

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


# --- the READER FIELD REGISTRY (contract C1: this module writes it, run.py hands it over in the
# exit-3 manifest's `fields`, the reader prompts render it) -----------------------------------
#
# The manifest used to hand every reader a FLAT LIST OF 47 BARE NAMES and nothing else: no type,
# no format, no note of who fills a field. Measured on a live run, validate-data failed 12 times
# and NOT ONE failure was an open-schema problem - every one was a DECLARED canonical field filled
# with the wrong type. Ten were `warehouseAreaSqm: <integer>` (six readers, independently, wrote
# the raw integer the deck printed - which is exactly what "write the value the way the source
# prints it" asks for when nothing states otherwise). Two were a prose paragraph in
# `districtProfile`, whose schema type is `object` and whose own description says the spine never
# populates it: that collision class was diagnosed once already (v38 renamed the object away from
# `district` because readers kept filling it) and the renamed orchestrator-only key was simply
# left in the list handed to readers. Four more names (lat, lng, warehouseArea, warehouseRentVal)
# only got away with it because the reader prompt spelled each out in prose - a workaround for
# the missing types that does not scale to 47 fields.
#
# So each registry entry now carries what a reader needs to produce a TYPE-VALID value:
#
#     {"name": "warehouseAreaSqm", "type": ["string", "null"], "fills": "reader",
#      "format": "the square-metre figure as a display string, e.g. '21,891 sq m'"}
#
#   * `type`   is READ OFF A SCHEMA, never restated here. Which schema matters (SEAM-18): a reader
#              writes the PRE-MERGE record shape (templates/record_schema.json), and merge converts
#              it into the POST-MERGE shape (canonical.schema.json). The two disagree exactly where
#              a reader is most likely to be got wrong: canonical declares `warehouseArea` a bare
#              `number`, but the reader contract says WRITE IT THE WAY THE SOURCE PRINTS IT (a
#              dimensioned string carrying its unit) and merge turns that into the number; the
#              record schema correctly says `number|string`. Rendering the canonical type told a
#              reader something the contract contradicts, on a headline field. So `type` comes from
#              record_schema.json's `properties.<name>.type` WHERE THAT FILE DECLARES THE FIELD, and
#              from canonical.schema.json only for a field it does not (the record schema is
#              illustrative and open, so most names fall through). A name neither declares (a
#              template-only `p.<field>`) gets canonical's own open-field scalar union.
#   * `fills`  is "orchestrator" when the schema description carries ORCHESTRATOR_MARK, else
#              "reader". An orchestrator-filled entry is EXCLUDED from what readers are handed -
#              a reader cannot fill it correctly, so offering it only invites the wrong type.
#   * `format` is present ONLY where the type alone is not enough. It is read from the schema
#              node's `x-reader-format` (a reader-facing hint; JSON Schema's own `format` keyword
#              is deliberately not reused because validators give it semantics) or, when the node
#              declares an `enum`, derived from that enum so the two can never disagree.
#
# Deterministic and pure: sorted by name, JSON-serialisable, ASCII-only (see F8 below), and it
# never raises - an unreadable schema degrades every entry to the open-field type rather than
# crashing the exit-3 handoff. evals/f19_typed_field_registry_test.py pins the shape.
ORCHESTRATOR_MARK = "ORCHESTRATOR-FILLED"
READER_FORMAT_KEY = "x-reader-format"
# the PRE-MERGE record shape a reader actually writes; the type source of first resort (SEAM-18)
RECORD_SCHEMA_FILE = C.TEMPLATES / "record_schema.json"
# what the canonical schema admits for an undeclared (open) scalar field; the fallback when the
# schema's own `additionalProperties` cannot be read
_OPEN_FIELD_TYPE = ["string", "number", "boolean", "null"]


def _property_schema() -> dict:
    """`$defs.property` of canonical.schema.json, or {} when it cannot be read. Read with
    utf-8-sig like every other helper, so a BOM on either platform is tolerated."""
    try:
        schema = json.loads(Path(C.SCHEMA_FILE).read_text(encoding="utf-8-sig"))
        return ((schema.get("$defs") or {}).get("property") or {})
    except Exception:
        return {}


def _record_schema_properties() -> dict:
    """`properties` of record_schema.json (the pre-merge record a reader writes), or {} when it
    cannot be read - the registry then types every field off canonical alone, which is what it did
    before SEAM-18, so an unreadable record schema degrades rather than crashing the handoff."""
    try:
        schema = json.loads(Path(RECORD_SCHEMA_FILE).read_text(encoding="utf-8-sig"))
        props = schema.get("properties") or {}
        return props if isinstance(props, dict) else {}
    except Exception:
        return {}


def _enum_format(enum: list) -> str:
    """A reader-facing hint derived from a schema `enum`, so the hint and the validator can
    never disagree about the admitted values."""
    return "exactly one of " + ", ".join(repr(str(v)) for v in enum)


def reader_field_registry(names, include_orchestrator: bool = False) -> list[dict]:
    """Type each canonical field NAME and return the typed registry
    `[{name, type, fills, format?}, ...]`, sorted by name.

    `type` is record_schema.json's where that file declares the name (the PRE-MERGE shape a reader
    writes), else canonical.schema.json's (SEAM-18; see the block comment above). `fills` is always
    judged off canonical, the only schema that carries the orchestrator marker. `format` is the
    declaring node's `x-reader-format` (record first, canonical second) or an enum-derived hint.

    `names` is the caller's field set (run.py's `_reader_field_list()`: the canonical registry
    minus the pipeline-assigned fields). This function owns only WHAT A READER NEEDS TO KNOW about
    each name, never which names exist. Orchestrator-filled entries are dropped unless
    `include_orchestrator` is set (a caller that wants the full typed picture, never a reader)."""
    prop = _property_schema()
    declared = prop.get("properties") or {}
    record = _record_schema_properties()
    open_type = (prop.get("additionalProperties") or {}).get("type") or _OPEN_FIELD_TYPE
    out: list[dict] = []
    for name in sorted({str(n) for n in (names or ()) if str(n)}):
        node = declared.get(name)
        node = node if isinstance(node, dict) else {}
        rnode = record.get(name)
        rnode = rnode if isinstance(rnode, dict) else {}
        desc = str(node.get("description") or "")
        fills = "orchestrator" if ORCHESTRATOR_MARK in desc else "reader"
        if fills == "orchestrator" and not include_orchestrator:
            continue
        if rnode.get("type") is not None:
            ftype = rnode["type"]           # the shape the reader WRITES (pre-merge)
        elif node.get("type") is not None:
            ftype = node["type"]            # not in the record schema: canonical's is all there is
        else:
            ftype = open_type
        entry = {"name": name, "type": ftype, "fills": fills}
        fmt = rnode.get(READER_FORMAT_KEY) or node.get(READER_FORMAT_KEY)
        enum = rnode.get("enum") if isinstance(rnode.get("enum"), list) else node.get("enum")
        if not fmt and isinstance(enum, list) and enum:
            fmt = _enum_format(enum)
        if fmt:
            entry["format"] = str(fmt)
        out.append(entry)
    return out


def reader_field_names(registry) -> list[str]:
    """The bare names of a typed registry, in registry order - for any code path that wants the
    pre-C1 flat list (there is deliberately NO parallel bare-name list in the manifest itself:
    a reader offered both would read the untyped one and reproduce the defect)."""
    return [str(e.get("name")) for e in (registry or ()) if isinstance(e, dict) and e.get("name")]


def _country_kv(country) -> dict:
    """`{"country": <code>}` when the caller KNOWS the deck's country, `{}` when it does not.

    The deck entry used to carry `"country": "??"` whenever intake could not resolve the cluster's
    country (run.py hands `cl.get("country") or "??"`). Five of seven readers on a live run said,
    unprompted, that the manifest gave `??` and derived the country from the page themselves - and
    across seven decks that produced three different spellings and cost one broker question.
    Passing a sentinel where ABSENCE is meant makes every agent recognise and reason about it;
    omitting the key is unambiguous and needs no rule. Never `null` either: a present key is read
    as a value. (F7, manifest half.)

    The rule has ONE implementation, vision_prep.country_kv, and this is a thin alias to it: run.py
    calls vision_prep.prepare DIRECTLY for a raster deck (bypassing the router below), so the rule
    had to live in the lower module or a raster deck kept its sentinel (SEAM-9). It strips the
    sentinel character rather than delegating to the shared predicate (normalize.looks_unknown,
    contract C5) on purpose: that family carries two-letter tokens that are also assigned ISO
    country codes, so a known country would be lost. See country_kv for the full reasoning."""
    return VP.country_kv(country)


# PREP SCHEMA VERSION - bumped whenever this helper changes WHAT it prepares or how it decides a
# cached entry is still good. It is folded into the stamp KEY, which was otherwise bytes-only
# (source size + mtime): a deck that has not changed matches the key for ever, so an entry
# produced by an older, weaker or degraded prep was served to every later run no matter what was
# fixed in between. That is not a hypothetical - see `_entry_aids_intact` below.
#   1/2 - pre-versioning (implicit)
#   3   - aids integrity: an entry with no page renders is no longer accepted while the host CAN
#         render; entries carry `visual_aids` and, when degraded, `aids_degraded`.
PREP_SCHEMA = 3


def _stamp_path(out_dir: Path, path: Path) -> Path:
    return out_dir / f"{path.stem}.interpret.stamp.json"


def _visual_aids(entry: dict) -> dict:
    """What this deck entry ACTUALLY hands its interpretation agent to LOOK at:
    `{pages, renders, candidates, sheets}`. Counting is the whole point - the manifest already
    carried these fields, and every one of them being empty was indistinguishable from a deck
    that legitimately has no images. run.py writes the per-deck counts to
    work/vision/visual_aids.json and the media-harvest gate reads them back."""
    pages = entry.get("pages") or []
    renders = sum(1 for p in pages if p.get("render"))
    cands = sum(len(p.get("candidates") or []) for p in pages)
    sheets = sum(1 for p in pages if p.get("candidates_sheet"))
    return {"pages": len(pages), "renders": renders, "candidates": cands, "sheets": sheets,
            "mode": entry.get("mode")}


def _can_render(path: Path) -> bool:
    """True when THIS host can rasterise THIS deck right now - Pillow present, the engine has a
    renderer, and the deck opens. A hard probe of the capability, so the guard below can tell
    "this deck has no renders because nothing here can render" (an honest, re-attempted absence)
    from "this deck has no renders although rendering works" (a poisoned entry)."""
    try:
        if IMG.Image is None:
            return False
        if not IMG.media_capabilities().get("renderer"):
            return False
        path = Path(path)
        if path.suffix.lower() == ".pptx":
            # A PPTX renders only via a LibreOffice conversion, and the only cheap way to prove
            # that works is to run it (20-180 s). Proving it here would either cost that on every
            # resume or, if assumed True, condemn a soffice-less host to recompute the whole
            # entry - thumbnails and all - on every single run. So the non-vacuous rule is not
            # applied to PPTX: the PREP_SCHEMA bump still invalidates any already-poisoned entry
            # once, and run.py's `[SIGNAL] visual aids` line + the media-harvest gate still name
            # a slide deck that reached its agent with no renders. Visible, not silent.
            return False
        # a SHORT-LIVED open, deliberately not IMG's shared doc cache: this probe runs on the
        # RESUME path, which returns without ever calling close_doc_cache(), so a cached handle
        # would outlive the prep step - and on Windows a held handle blocks a caller's temp-dir
        # cleanup (the same leak class fixed in merge / gate_runner / project_properties).
        doc = fitz.open(path)
        try:
            return doc.page_count > 0
        finally:
            try:
                doc.close()
            except Exception:
                pass
    except Exception:
        return False


def _entry_aids_intact(entry: dict, path: Path) -> bool:
    """Is this cached TEXT entry still a USABLE set of visual aids for the interpretation agent?

    Two questions, and only the first one used to be asked.

    (a) REFERENTIAL: every candidate thumbnail, per-page render and contact sheet the entry
        names still exists on disk, so a shell-capped re-run reuses them while a kill that lost
        one recomputes.

    (b) NON-VACUOUS (the fix): an entry that references NO thumbnails and NO renders at all
        passed (a) trivially - every one of zero files exists - so a deck prepared in a moment
        when the image layer was unavailable was cached with `render: null` and `candidates: []`
        on every page and then served for ever, the stamp key being bytes-only. Measured on a
        live run: fourteen decks' agents were handed manifests with zero visual aids, wrote no
        `__meta.image_pages` and no `__meta.plan_page`, and the whole gallery/plan harvest
        collapsed to each property's single anchor page. Re-running the prep produced 7/7
        renders and 64 candidate thumbnails in 6.6 s - the machinery was fine, the CACHE was
        poisoned. So: when the host CAN render, a multi-page entry carrying zero renders is
        REJECTED and recomputed. When it genuinely cannot render, the entry is still accepted
        (nothing better is obtainable) and `aids_degraded` says so on the entry.
    """
    try:
        for pg in entry.get("pages", []):
            for c in pg.get("candidates", []):
                img = c.get("image")
                if img and not Path(img).exists():
                    return False
            rnd = pg.get("render")
            if rnd and not Path(rnd).exists():
                return False
            # the tiled sheet too, or a kill that lost it serves a manifest pointing at a
            # file the agent cannot read (B19)
            for sh in (pg.get("candidates_sheet") or []):
                if sh and not Path(sh).exists():
                    return False
        aids = _visual_aids(entry)
        if aids["pages"] and aids["renders"] == 0 and _can_render(path):
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
            C.atomic_save_image(im, thumb)
        except Exception:
            continue  # undecodable candidate - skip it, never abort the page
        out.append({"index": c["index"], "image": str(thumb.resolve()),
                    "w": c["w"], "h": c["h"]})
    return out


def _write_candidate_montage(path: Path, page_index: int, out_dir: Path,
                             cands: list[dict]) -> list | None:
    """One contact sheet per page tiling that page's candidate thumbnails. (B19)

    ADDITIVE: the per-candidate PNGs stay on disk. The sheet turns N image reads into one,
    and each read replays the agent's whole context - that, not pixels, is the exit-3 cost.
    An agent that ignores the sheet loses nothing, and one that finds a tile ambiguous can
    still open the individual thumbnail.

    None when there is nothing to gain: no candidates, or exactly one (its thumbnail already
    IS a single image). Never raises - a sheet that cannot be written is an honest absence,
    exactly like a thumbnail that cannot be decoded.

    The page number stays in the MANIFEST key, never in a caption: only the candidate
    `index` is captioned, so the one thing the agent must read off the sheet is a small
    integer it also has in the JSON."""
    if not cands or len(cands) < 2:
        return None
    try:
        import contact_sheet as CSH
        out = CSH.tile_native(cands, Path(out_dir) / f"{path.stem}_p{page_index}_sheet.png",
                              tile_px=CANDIDATE_THUMB_EDGE)
        return out or None
    except Exception:
        return None


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
        C.atomic_save_image(im, thumb)
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
        _cands = _write_candidate_thumbs(path, pno, out_dir)
        page = {"page_no": pno, "locator": f"{unit} {pno + 1}", "text": text,
                "candidates": _cands,
                # ONE tiled image of the same candidates, so the page costs one read
                # instead of len(_cands). Additive - `candidates` above is unchanged. (B19)
                "candidates_sheet": _write_candidate_montage(path, pno, out_dir, _cands),
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
    # `cluster_label`, NOT `region` (B51). This string is derived from the input FILENAME by
    # intake's clustering; it exists so the sub-agent's output file lands in the right slot. It
    # is not evidence, and `region` is also a real displayed field - handing an agent a
    # pre-filled field of that name invited three of eleven to ship it as sourced data.
    # `country` is present ONLY when known (F7): see _country_kv for why a sentinel is worse
    # than an absent key on an agent-facing handoff.
    return {"source_file": path.name, "source_type": source_type,
            "cluster_label": region, "cluster_label_is_routing_only": True,
            **_country_kv(country), "mode": "text", "pages": pages}


def prepare(path: Path, region: str, country: str, out_dir, dpi: int = 180,
            force: bool = True, resume: bool = True) -> dict:
    """Prepare ONE brochure deck for interpretation and return a manifest deck entry
    {source_file, source_type, cluster_label, country?, mode, pages:[...]} - `country` only
    when the caller knows it (F7; see _country_kv).

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
        # SCHEMA is part of the key, not just the bytes. A bytes-only key says "this deck has
        # not changed", which is not the question - the question is "is the entry I cached for
        # it still the entry this prep would produce", and a helper/feature change makes the
        # answer no while the bytes are identical. Without this a pre-feature (or degraded)
        # entry is served for ever.
        cur = {"size": s.st_size, "mtime_ns": s.st_mtime_ns, "schema": PREP_SCHEMA}
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
                    and _entry_aids_intact(entry, path)):
                # the page payload + thumbnails are a pure function of the source BYTES and are
                # reused as-is, but region/country are MANIFEST INPUTS supplied by the caller:
                # intake can re-cluster a deck to a corrected region on a resume (reference/
                # config.md), and the stamp key is bytes-only - so refresh them on the reused
                # entry, or the sub-agent saves the record under the STALE <region>_vision.json
                # slot (run.py's manifest says 'region EXACTLY as in this manifest'). vision_prep
                # already rebuilds these fresh every call. (#28/#37)
                entry["cluster_label"] = region
                entry["cluster_label_is_routing_only"] = True
                entry.pop("region", None)   # a REUSED entry may still carry the legacy key (B51)
                # a warm work dir's cached entry may still carry the pre-F7 `"country": "??"`;
                # drop it and re-state the country only when the caller knows it
                entry.pop("country", None)
                entry.update(_country_kv(country))
                entry["visual_aids"] = _visual_aids(entry)   # refreshed, never trusted from cache
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
        entry["visual_aids"] = _visual_aids(entry)
        # HONEST ADMISSION. Producing an entry with no visual aids is a legitimate outcome on a
        # host that cannot render - but it must SAY so on the entry, because the agent reading
        # that manifest is being asked to pick __meta.plan_page / image_pages from text alone and
        # nothing else downstream can tell that from "this deck holds no images". It is the entry
        # itself that carries the admission, so it travels with the manifest into the agent's
        # own context. (Two shapes: nothing to look at at all, or pages without renders.)
        degraded = []
        aids = entry["visual_aids"]
        if aids["pages"] and aids["renders"] == 0:
            degraded.append(
                "no page RENDER was produced for any page - this agent cannot SEE any page, so "
                "__meta.plan_page cannot be judged visually here"
                + ("" if _can_render(path) else
                   " (this host cannot rasterise this deck: "
                   + ("Pillow is unavailable" if IMG.Image is None else "the engine has no renderer")
                   + ")"))
        if aids["pages"] and aids["candidates"] == 0:
            degraded.append(
                "no candidate image thumbnail was produced for any page - either the deck holds "
                "no hero-size embedded raster, or the image layer could not decode one")
        if degraded:
            entry["aids_degraded"] = degraded
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
    # vision_prep applies the absence rule itself now (SEAM-9: run.py also calls it directly, so
    # the rule lives there). Re-applying it here is deliberate belt-and-braces: the router must hold
    # the F7 guarantee for a raster entry no matter what the delegate returned (a stubbed or older
    # vision_prep still hands back `"country": "??"`), and evals/f07 pins exactly that.
    entry.pop("country", None)
    entry.update(_country_kv(country))
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
    # F8: AGENT-FACING JSON IS WRITTEN ASCII-ONLY. Page text legitimately carries non-ASCII, and
    # with ensure_ascii=False those bytes reach whoever captures this output; on a host whose
    # default text encoding is not UTF-8 (Windows cp1252 is the common case) the idiomatic
    # `json.load(open(path))` then raises UnicodeDecodeError - reproduced on a live run against
    # the manifest, where an agent told to "load the JSON in a small script" crashed and burned
    # tool calls. Escaping costs nothing on a machine-to-agent file and removes the failure mode
    # on every platform; json.loads restores the exact same strings. The manifest writer itself
    # lives in run.py (`_write_manifest`) and needs the same one-word change.
    print(json.dumps(ent, ensure_ascii=True, indent=2))
    if ent.get("mode") == "text":
        print(f"OK mode=text: {len(ent['pages'])} page(s) of text -> interpret per "
              f"reference/interpretation.md")
    else:
        print(f"OK mode=raster: {len(ent['pages'])} page(s) rasterised for vision -> {args.out_dir}")


if __name__ == "__main__":
    main()
