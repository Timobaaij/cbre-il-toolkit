#!/usr/bin/env python3
"""project_properties.py - a READ-ONLY per-property view of the merged dataset.

`canonical.json` is one file, ~11 MB of which is base64 image data, so the thing a broker or
a reviewer actually wants to look at - one option, its values, its photos, where each figure
came from - is not readable in it. Everything downstream of the merge is per-property work:
checking a hero is the right building, chasing a `tbd`, seeing why a rent looks wrong. This
writes that view.

  work/properties/
    01-indurent-park-chippenham-unit-c112/
      property.json         the record, readable, media replaced by filenames
      media/                the BOUND files: hero.jpg, gallery-02.jpg ..., plan.jpg
      media/considered/     every page render + candidate image this property CONSIDERED,
                            named p<page>-render.png / p<page>-c<index>.jpg (page and index
                            0-based, the same numbering as __meta.page_no / heroRef)
      media_decisions.json  chosen vs rejected vs never-looked-at, each with WHY
      sources.csv           this property's Source Ledger rows and nothing else
      notes.md              its unknowns, its source conflicts, its repairs, its repair key
    _unassigned/            deck pages NO property claimed - same shape, once per run

The `considered/` folder is deliberately PER PROPERTY, not per brochure, and an image may
therefore appear in two of them: two units sharing one deck each get their own complete folder.
Clarity beats de-duplication here - the question being answered is "what did THIS card have to
choose from", and an answer that makes you open a second folder to find out is not an answer.

DERIVED, NEVER AUTHORITATIVE. It is rebuilt from `canonical.json` on every run and nothing
reads it back. Editing a file here changes nothing: corrections go in `work/repairs.json`,
which is applied before the gates and writes its own ledger rows. That asymmetry is the
design, not an omission - two writable copies of one dataset drift, and the drift is silent.

`notes.md` prints the property's `repair key` for exactly this reason: it is the string a
repair entry needs, so the view that shows you the problem also hands you what you need to
fix it.

CLI:  python project_properties.py --work <dir> [--canonical <path>] [--no-media]
                                    [--source-dir <input folder>] [--image-cache <dir>]
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import shutil
import sys
from pathlib import Path

# a genuinely long field (e.g. an accumulated conflict_note spanning many
# contributing sources) can exceed Python's defensive default (131072) - this
# is a legitimate long value, not a memory bomb, so the reader must accept it.
csv.field_size_limit(2**31 - 1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import match as _match
except Exception:                                    # pragma: no cover
    _match = None

MEDIA_FIELDS = ("photo", "plan")
_SLUG_RX = re.compile(r"[^a-z0-9]+")
_EXT = {"/9j/": "jpg", "iVBOR": "png", "R0lGO": "gif", "UklGR": "webp"}

# --- THE CONSIDERED SET ------------------------------------------------------------------- #
# `media/` answers "what did this card ship". It cannot answer the question people actually ask
# when a card looks thin - "was there anything better, and why was it not used?" - and on a run
# where the image layer was quietly degraded that question had no answerable form at all: every
# artefact of a blind harvest is identical to one of an empty source. `considered/` writes the
# discard pile out as openable files and `media_decisions.json` says, page by page, what happened
# to it. Derived and rebuilt each run; nothing reads it back.
CONSIDERED_DPI = 110          # page-render dpi: legible on screen, cheap; not a delivery asset
CONSIDERED_MAX_EDGE = 1400    # downscale cap for both renders and candidate images
CONSIDERED_MAX_PAGES = 60     # per property: a defensive cap, never reached by a real brochure


def slug(text: str, cap: int = 60) -> str:
    s = _SLUG_RX.sub("-", str(text or "").strip().lower()).strip("-")
    return (s[:cap].rstrip("-") or "property")


def repair_key(rec: dict) -> str:
    if _match is not None:
        try:
            return _match.match_key(rec)
        except Exception:
            pass
    return "|".join(str(rec.get(k, "") or "").strip().lower()
                    for k in ("city", "developer", "park"))


def _decode(uri: str):
    """(bytes, ext) from a data URI, or (None, None). Never raises on a malformed value."""
    if not isinstance(uri, str) or "base64," not in uri:
        return None, None
    head, _, b64 = uri.partition("base64,")
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None, None
    m = re.search(r"image/([a-z0-9.+-]+)", head, re.I)
    ext = (m.group(1).lower() if m else "")
    if ext in ("jpeg", "jpg"):
        ext = "jpg"
    if not ext or ext not in ("jpg", "png", "gif", "webp", "svg+xml"):
        ext = _EXT.get(b64[:5], "img")
    return raw, ("svg" if ext == "svg+xml" else ext)


def _is_placeholder(raw: bytes) -> bool:
    return bool(raw) and len(raw) < 12_000


def _resolve_deck(source_dir, entry: dict):
    """The deck file for a considered entry: its recorded absolute `path` when that still
    exists, else the same NAME under source_dir (a work dir moved between machines). None when
    neither resolves - the projection then records the decision without the pixels."""
    pth = entry.get("path")
    try:
        if pth and Path(pth).exists():
            return Path(pth)
    except Exception:
        pass
    if not source_dir:
        return None
    name = entry.get("file") or (Path(pth).name if pth else "")
    if not name:
        return None
    base = Path(source_dir)
    cand = base / name
    if cand.exists():
        return cand
    try:
        return next(iter(sorted(base.rglob(name))), None)
    except Exception:
        return None


def _write_considered(cdir: Path, deck: Path, pages: list, image_cache=None) -> tuple:
    """Write `p<page>-render.png` + `p<page>-c<index>.jpg` for each considered page of one deck.

    Returns (written, failures). NEVER raises: a page that will not render and an image that will
    not decode are recorded as failures and the rest of the folder is still produced - a partial
    discard pile is far more useful than none, and the reason is written down either way.

    The candidate `index` is IMG.candidates_for_page's own 0-based position, i.e. exactly the
    integer `__meta.heroRef` / `planRef` names - so a reviewer who sees the right photo here can
    read its number off the filename and put it straight into repairs.json."""
    import images as IMG
    written, failed = [], []
    cdir.mkdir(parents=True, exist_ok=True)
    for pno in list(pages)[:CONSIDERED_MAX_PAGES]:
        raster = None
        try:
            if deck.suffix.lower() == ".pptx":
                pdf = IMG.soffice_pdf(deck, image_cache)
                doc = IMG._get_doc(pdf) if pdf else None
            else:
                doc = IMG._get_doc(deck)
            raster = IMG.page_raster(doc, pno, dpi=CONSIDERED_DPI) if doc is not None else None
        except Exception as e:
            failed.append({"page": pno, "what": "render", "why": f"{type(e).__name__}: {e}"})
        if raster is not None:
            try:
                im = raster.convert("RGB")
                im.thumbnail((CONSIDERED_MAX_EDGE, CONSIDERED_MAX_EDGE))
                im.save(cdir / f"p{pno}-render.png")
                written.append(f"p{pno}-render.png")
            except Exception as e:
                failed.append({"page": pno, "what": "render", "why": f"{type(e).__name__}: {e}"})
        elif not any(f["page"] == pno and f["what"] == "render" for f in failed):
            failed.append({"page": pno, "what": "render",
                           "why": "this host could not rasterise the page (see the `media "
                                  "engine:` line and work/media_harvest.json)"})
        try:
            cands = (IMG.slide_pictures(deck, pno) if deck.suffix.lower() == ".pptx"
                     else IMG.candidates_for_page(deck, pno))
        except Exception as e:
            cands = []
            failed.append({"page": pno, "what": "candidates", "why": f"{type(e).__name__}: {e}"})
        for c in cands:
            idx = c.get("index")
            if idx is None:
                continue
            try:
                im = c["img"].convert("RGB")
                im.thumbnail((CONSIDERED_MAX_EDGE, CONSIDERED_MAX_EDGE))
                im.save(cdir / f"p{pno}-c{idx}.jpg", quality=82)
                written.append(f"p{pno}-c{idx}.jpg")
            except Exception as e:
                failed.append({"page": pno, "what": f"candidate {idx}",
                               "why": f"{type(e).__name__}: {e}"})
    return written, failed


def _considered_for_property(out_dir: Path, entry: dict, written_media: dict,
                             source_dir=None, image_cache=None) -> dict:
    """Project ONE property's considered set: the files under media/considered/ and the
    `media_decisions.json` beside them. Returns the decisions object (also written to disk)."""
    cdir = out_dir / "media" / "considered"
    decks_out: dict = {}
    total_files = 0
    for name, d in sorted((entry.get("decks") or {}).items()):
        d = dict(d)
        d["file"] = name
        deck = _resolve_deck(source_dir, d)
        looked = sorted(int(x) for x in (d.get("looked") or []))
        files, failures = [], []
        if deck is not None and looked:
            files, failures = _write_considered(cdir, deck, looked, image_cache)
        total_files += len(files)
        not_looked = []
        for pg in sorted(int(x) for x in (d.get("foreign") or [])):
            not_looked.append({"page": pg, "why": "claimed by ANOTHER property of this deck - "
                                                  "the unique-claimant guard subtracted it"})
        for pg in sorted(int(x) for x in (d.get("plan_offlimits") or [])):
            not_looked.append({"page": pg, "why": "off-limits for the site-plan slot (it belongs "
                                                  "to another property of this deck)"})
        for pg in sorted(int(x) for x in (d.get("plan_rejected") or [])):
            not_looked.append({"page": pg, "why": "REJECTED as a site plan by a visual-QA "
                                                  "reviewer (placeholder_audit_ack.json)"})
        decks_out[name] = {
            "deck_resolved": (str(deck) if deck is not None else None),
            "looked_at": looked,
            "not_looked_at": not_looked,
            "excluded_candidates": d.get("exclude_refs") or {},
            "files": sorted(files),
            "could_not_write": failures,
        }
    decisions = {
        "note": ("Pages and candidate indices are 0-BASED, the same numbering as "
                 "__meta.page_no / __meta.heroRef. This folder is DERIVED and rebuilt every "
                 "run - corrections go in work/repairs.json, never here."),
        "id": entry.get("id"),
        "property": entry.get("property"),
        "chosen": {
            "hero": {"file": written_media.get("photo"),
                     "placeholder": bool((entry.get("hero") or {}).get("placeholder")),
                     "from": (entry.get("hero") or {}).get("from")},
            "plan": {"file": written_media.get("plan"),
                     "bound": bool((entry.get("plan") or {}).get("bound")),
                     "from": (entry.get("plan") or {}).get("from")},
            "gallery": written_media.get("gallery") or [],
        },
        "rejected_plan_pages": list(entry.get("near_miss") or []),
        "decks": decks_out,
        "considered_files": total_files,
    }
    (out_dir / "media_decisions.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return decisions


def write_property(prop: dict, out_dir: Path, ledger_rows: list, conflicts: list,
                   repairs: list, media: bool = True, considered: dict | None = None,
                   source_dir=None, image_cache=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mdir = out_dir / "media"
    if mdir.exists():
        shutil.rmtree(mdir, ignore_errors=True)

    view = {k: v for k, v in prop.items() if k not in ("photo", "plan", "gallery")}
    written = {}
    if media:
        mdir.mkdir(parents=True, exist_ok=True)
        raw, ext = _decode(prop.get("photo"))
        if raw:
            name = f"hero.{ext}"
            (mdir / name).write_bytes(raw)
            written["photo"] = name + (" (placeholder)" if _is_placeholder(raw) else "")
        raw, ext = _decode(prop.get("plan"))
        if raw:
            (mdir / f"plan.{ext}").write_bytes(raw)
            written["plan"] = f"plan.{ext}"
        gal = prop.get("gallery") or []
        names = []
        for i, uri in enumerate(gal, start=1):
            raw, ext = _decode(uri)
            if not raw:
                continue
            name = f"gallery-{i:02d}.{ext}"
            (mdir / name).write_bytes(raw)
            names.append(name)
        if names:
            written["gallery"] = names
    view["__media"] = written or {"note": "no image data on this property"}
    # THE CONSIDERED SET: written only when merge recorded one for this property AND media files
    # are being written at all (--no-media means "no pixels", and that covers the discard pile).
    n_considered = 0
    if media and isinstance(considered, dict) and considered:
        try:
            n_considered = _considered_for_property(out_dir, considered, written,
                                                    source_dir, image_cache).get(
                                                        "considered_files", 0)
            view["__media_considered"] = {
                "files": n_considered,
                "where": "media/considered/ - decisions in media_decisions.json"}
        except Exception as e:                # derived view: never let it fail the projection
            view["__media_considered"] = {"error": f"{type(e).__name__}: {e}"}
    view["__repair_key"] = repair_key(prop)
    (out_dir / "property.json").write_text(
        json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    cols = ["field", "value", "source_file", "source_locator", "source_type",
            "record_type", "extractor", "confidence", "conflict_note", "verified"]
    with open(out_dir / "sources.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in ledger_rows:
            w.writerow(r)

    tbd = sorted(k for k, v in prop.items()
                 if isinstance(v, str) and v.strip().lower() in ("tbd", "tbc", "—", "-"))
    lines = [f"# {prop.get('park') or 'Property'}  (id {prop.get('id')})", ""]
    lines += [f"- **repair key**: `{view['__repair_key']}`",
              f"- **city**: {prop.get('city') or 'tbd'}    **region**: {prop.get('region') or 'tbd'}",
              ""]
    if n_considered:
        lines += [f"- **media considered**: {n_considered} file(s) in `media/considered/` - every "
                  f"page render and candidate image this property had to choose from. "
                  f"`media_decisions.json` says what was chosen, what was rejected and why, and "
                  f"which pages were never looked at.", ""]
    lines += ["## To correct anything here", "",
              "Edit `work/repairs.json`, not this folder - nothing reads these files back.", "",
              "```json", json.dumps([{
                  "id": "rp-001",
                  "property": {"key": view["__repair_key"], "id": prop.get("id")},
                  "expect": {"city": prop.get("city")},
                  "set": {"<field>": "<value>"},
                  "why": "why this is right, in one sentence",
                  "verified_by": "you@cbre.com",
              }], indent=2), "```", ""]
    lines += [f"## Unknown ({len(tbd)})", ""]
    lines += ([f"- `{k}`" for k in tbd] or ["- none"]) + [""]
    lines += [f"## Source conflicts ({len(conflicts)})", ""]
    lines += ([f"- {c}" for c in conflicts] or ["- none"]) + [""]
    lines += [f"## Repairs applied ({len(repairs)})", ""]
    lines += ([f"- `{r['id']}` {', '.join(r.get('changed', {}))} - {r.get('why','')}"
               for r in repairs] or ["- none"]) + [""]
    (out_dir / "notes.md").write_text("\n".join(lines), encoding="utf-8")
    return {"dir": out_dir.name, "media": written, "tbd": len(tbd),
            "considered": n_considered}


def build(work: Path, canonical_path: Path | None = None, media: bool = True,
          source_dir=None, image_cache=None) -> dict:
    work = Path(work)
    cpath = Path(canonical_path) if canonical_path else work / "canonical.json"
    data = json.loads(cpath.read_text(encoding="utf-8-sig"))
    props = data.get("properties") or []

    # merge's considered-set sidecar (item 5). Absent -> the projection is exactly what it was
    # before: bound media only, no considered/ folder, no _unassigned/. Never a hard dependency.
    considered_by_id: dict = {}
    unassigned: list = []
    try:
        _mc = json.loads((work / "media_considered.json").read_text(encoding="utf-8-sig"))
        for _e in (_mc.get("properties") or []):
            if isinstance(_e, dict) and _e.get("id") is not None:
                considered_by_id[str(_e["id"])] = _e
        unassigned = list(_mc.get("unassigned") or [])
    except Exception:
        pass

    by_id: dict = {}
    lpath = work / "source_ledger.csv"
    if lpath.exists():
        with open(lpath, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                by_id.setdefault(str(row.get("property_id", "")).strip(), []).append(row)

    conf_by_id: dict = {}
    for c in (data.get("meta", {}).get("conflicts") or []):
        m = re.match(r"\s*id\s+(\d+)\s+(.*)", str(c))
        if m:
            conf_by_id.setdefault(m.group(1), []).append(m.group(2))

    rep_by_id: dict = {}
    rpath = work / "repairs_report.json"
    if rpath.exists():
        try:
            for a in (json.loads(rpath.read_text(encoding="utf-8-sig")).get("applied") or []):
                rep_by_id.setdefault(str(a.get("property_id")), []).append(a)
        except Exception:
            pass

    root = work / "properties"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    made = []
    for p in props:
        pid = str(p.get("id"))
        name = f"{pid.zfill(2)}-{slug(p.get('park') or p.get('city') or 'property')}"
        made.append(write_property(p, root / name, by_id.get(pid, []),
                                   conf_by_id.get(pid, []), rep_by_id.get(pid, []), media,
                                   considered=considered_by_id.get(pid),
                                   source_dir=source_dir, image_cache=image_cache))
    n_orphan = _write_unassigned(root, unassigned, source_dir, image_cache) if media else 0
    # the considered-set render loop opens each deck through IMG's shared doc cache; release the
    # handles before returning (on Windows a held handle blocks an in-process caller's temp-dir
    # cleanup, and this projection owns no later image work).
    try:
        import images as _IMG
        _IMG.close_doc_cache()
    except Exception:
        pass
    (root / "index.json").write_text(
        json.dumps({"count": len(made), "properties": made,
                    "unassigned_pages": n_orphan}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"count": len(made), "root": str(root), "unassigned": n_orphan}


def _write_unassigned(root: Path, unassigned: list, source_dir=None, image_cache=None) -> int:
    """`properties/_unassigned/` - ONCE per run, the deck pages NO property claimed.

    These pages are the run's blind spot: no gallery scan, no plan tier and no placeholder audit
    ever reached them, so nothing else in the pipeline can even mention them. On a multi-property
    or whole-park donor deck that is exactly where a missed site plan sits. Same shape as a
    property's considered/ folder, so it is read the same way. Returns the page count."""
    if not unassigned:
        return 0
    out = root / "_unassigned"
    out.mkdir(parents=True, exist_ok=True)
    total, index = 0, []
    for entry in unassigned:
        if not isinstance(entry, dict):
            continue
        name = entry.get("file") or "?"
        pages = sorted(int(x) for x in (entry.get("pages") or []))
        deck = _resolve_deck(source_dir, entry)
        sub = out / slug(Path(name).stem, 80)
        files, failures = ([], [])
        if deck is not None and pages:
            files, failures = _write_considered(sub, deck, pages, image_cache)
        total += len(pages)
        index.append({"file": name, "deck_resolved": (str(deck) if deck else None),
                      "deck_pages": entry.get("deck_pages"),
                      "large_images": entry.get("large_images"),
                      "unclaimed_pages": pages, "folder": sub.name,
                      "files": sorted(files), "could_not_write": failures})
    (out / "README.md").write_text(
        "# Pages no property claimed\n\n"
        "Every page listed here belongs to a deck this run read, but NO property's record "
        "claimed it (neither as its `__meta.page_no` nor in its `__meta.image_pages`). Nothing "
        "in the harvest looked at them - not the carousel, not the site-plan tier, not the "
        "placeholder audit.\n\n"
        "If a site plan or a usable photo is sitting in one of these folders, the fix is a "
        "record-level one: give the page to the property it shows via `__meta.image_pages` / "
        "`__meta.plan_page` (re-read the deck), not by editing anything here. This view is "
        "DERIVED and rebuilt on every run.\n\n"
        "Page numbers are 0-BASED, matching `__meta.page_no`.\n",
        encoding="utf-8")
    (out / "index.json").write_text(
        json.dumps({"decks": index, "unclaimed_pages": total}, ensure_ascii=False, indent=1)
        + "\n", encoding="utf-8")
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True)
    ap.add_argument("--canonical")
    ap.add_argument("--no-media", action="store_true")
    ap.add_argument("--source-dir", dest="source_dir", default="",
                    help="the run's INPUT folder - enables media/considered/ (every page render "
                         "and candidate image each property had to choose from) and _unassigned/")
    ap.add_argument("--image-cache", dest="image_cache", default="",
                    help="the run's image cache dir (only used to reuse a PPTX->PDF conversion)")
    a = ap.parse_args()
    r = build(Path(a.work), Path(a.canonical) if a.canonical else None, media=not a.no_media,
              source_dir=(Path(a.source_dir) if a.source_dir else None),
              image_cache=(Path(a.image_cache) if a.image_cache else None))
    print(f"OK per-property projection: {r['count']} property folder(s) -> {r['root']}"
          + (f"; {r['unassigned']} unclaimed deck page(s) -> {r['root']}/_unassigned"
             if r.get("unassigned") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
