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

TWO HALVES, ONE OF THEM EXPENSIVE (F20, contract C4). `property.json`, `sources.csv`,
`notes.md` and `index.json` cost under a second for a whole run. `media/`, `media/considered/`,
`media_decisions.json` and `_unassigned/` are page renders and decoded images: on a measured
pass they were 84% of the ENTIRE run (42 s of 50 s; the dashboard build itself took 0.15 s) and
82 MB across 352 files, rewritten every pass into a folder a sync client then re-uploads, for a
view nothing reads back. `--media-view` splits the halves: `always` writes both, `never` writes
the cheap half only, `auto` (the CLI default) is `never`. The spine asks for `always` exactly
when a pre-build gate has BLOCKED, because that is when a human is about to open this folder.
The in-process default (`build(work)` with nothing said) stays `always`, so every caller
written before the flag gets what it asked for; the spine passes `media_view=` explicitly.

A skipped media half must never look like an EMPTY one: a `media/` that is silently absent is
indistinguishable from a harvest that found nothing, which is a documented failure class of
this skill. So when it is skipped, `property.json["__media"]` and `notes.md` say so on every
property, `index.json` records the mode, and `MEDIA_VIEW_SKIPPED.md` at the root carries the
exact command that writes the full view. The repair key is in the cheap half and never skipped.

PRUNED, NOT ACCUMULATED (F27). A property directory is named `<id>-<slug>`, so a run whose
count DROPS (a broker collapsing records, an exclusion, a re-read producing fewer) leaves
numbered directories that match nothing; a blind reviewer of one live run counted eleven
folders against nine shipped records and could not close the question. The previous
`rmtree(root, ignore_errors=True)` did try to clear everything, and silently left two empty
husks behind because a cloud-synced folder was holding the entries. Now every numbered
directory no property claims is removed one by one, with a retry, and whatever STILL survives
is named in `index.json["could_not_prune"]` and on stderr rather than left as a quiet eleventh
folder. `_unassigned/` is cleared and rebuilt with the media half, never mistaken for an
orphan; anything unrecognised is left alone and listed. `index.json` is removed FIRST and
written LAST, atomically, so a projection that crashed mid-write leaves a folder with no index
rather than a stale one claiming completeness.

THE MEDIA HALF IS CARRIED WHILE ITS INPUTS ARE UNCHANGED (2026-09-26 test run, fix 2.2). The
media half used to have no identity, so every pass either deleted it (`never`) or re-rendered
all of it (`always`): a blocked pass on a 22-deck run paid ~95 s to re-render 209 pages it had
rendered the pass before, and a run whose gates passed never wrote a media view at all, so the
QA reviewers told to "verify against the per-property media" had none. Now each property's
`media/` carries a `.media_stamp.json` (and `_unassigned/` its own), written LAST, holding
`media_key` - a hash over the images the card ships, the property's considered set, each
considered deck's resolved path + size + mtime, the render parameters and the bytes of this
module and images.py - plus the size and mtime of every file the half wrote. A half is CURRENT
only when the key matches, nothing failed to write, and the files on disk are exactly the files
the stamp lists; then it is carried (not deleted on `never`, not re-rendered on `always`). Any
doubt - an unreadable stamp, a key that cannot be computed, a hand-edited file - means rebuild
(`always`) or delete (`never`), which is the old behaviour. `force_media=True`
(`--rebuild-media`) ignores the stamps. A carried half on a `never` pass says so in
`property.json["__media"]["carried"]`, `notes.md` and `index.json["media_carried"]`; on an
`always` pass it is by construction what a rebuild would write, so property.json reads the same.

CLI:  python project_properties.py --work <dir> [--canonical <path>]
                                    [--media-view {auto,always,never}] [--no-media]
                                    [--rebuild-media]
                                    [--source-dir <input folder>] [--image-cache <dir>]
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
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

# THE shared unknown predicate (contract C5). Until 2026-09-05 the notes.md "Unknown" list read
# its own four-member tuple, so a field holding `??`, `TBA` or `n/a` was listed as KNOWN here
# while the card showed `tbd` for it. Unguarded on purpose: a fallback literal would be a ninth
# private sentinel set, which evals/f05_no_private_sentinel_sets_test.py exists to refuse.
import normalize as _N  # noqa: E402  (helpers/ is on path by the line above)

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

# --- THE MEDIA VIEW FLAG (contract C4) ---------------------------------------------------- #
MEDIA_VIEW_CHOICES = ("auto", "always", "never")
MEDIA_VIEW_MARKER = "MEDIA_VIEW_SKIPPED.md"   # at the root of properties/, present ONLY when skipped
# a property directory is `<id zero-padded>-<slug>`. This is what "numbered" means below and the
# ONLY shape pruning ever removes as an orphan; `_unassigned/` starts with an underscore for it.
_NUMBERED_DIR_RX = re.compile(r"^\d+-")
# the root-level files this module owns: removed before a pass writes, so a crash mid-write
# leaves no index claiming the folder is complete, and re-created last
_OWNED_ROOT_FILES = ("index.json", "index.json.tmp", MEDIA_VIEW_MARKER)

# --- THE MEDIA STAMP (2026-09-26 test run, fix 2.2) ---------------------------------------- #
# Lives INSIDE the half it describes (`media/`, `_unassigned/`), so removing the half removes its
# stamp and a stale stamp can never outlive its files. See the module docstring.
MEDIA_STAMP = ".media_stamp.json"
MEDIA_STAMP_VERSION = 1
_DECISIONS_REL = "../media_decisions.json"   # the one media-half file outside media/
_CARRY_NOTE = ("media half carried from an earlier full view - its inputs (images, considered "
               "set, deck files, render code) are unchanged")


def _code_fingerprint() -> str:
    """sha256 over the bytes of this module and images.py - the code that decides what the media
    half contains - so an image-code change invalidates every stamp by construction. "" on any
    error, and an empty fingerprint never matches (no key is computed from it)."""
    try:
        here = Path(__file__).resolve()
        h = hashlib.sha256()
        for f in (here, here.parent / "images.py"):
            h.update(f.name.encode("utf-8"))
            h.update(b"\0")
            h.update(f.read_bytes())
            h.update(b"\0")
        return h.hexdigest()
    except Exception:
        return ""


def _key_params(code_fp: str, image_cache) -> bytes:
    return json.dumps({"v": MEDIA_STAMP_VERSION, "code": code_fp, "dpi": CONSIDERED_DPI,
                       "edge": CONSIDERED_MAX_EDGE, "maxp": CONSIDERED_MAX_PAGES,
                       "cache": bool(image_cache)}, sort_keys=True).encode("utf-8")


def _deck_stat(source_dir, entry: dict, deck_cache: dict) -> str:
    """`name|resolved path|size|mtime_ns` for one deck entry (`name|-1` when it does not
    resolve), cached per (name, recorded path) so a deck shared by many properties is resolved
    once per build."""
    name = str(entry.get("file") or Path(str(entry.get("path") or "")).name)
    ck = (name, str(entry.get("path") or ""))
    if ck in deck_cache:
        return deck_cache[ck]
    try:
        deck = _resolve_deck(source_dir, entry)
        if deck is None:
            s = f"{name}|-1"
        else:
            st = deck.stat()
            s = f"{name}|{deck}|{st.st_size}|{st.st_mtime_ns}"
    except Exception:
        s = f"{name}|-1"
    deck_cache[ck] = s
    return s


def media_key(prop: dict, considered, source_dir, image_cache, code_fp: str,
              deck_cache: dict | None = None) -> str | None:
    """The identity of ONE property's media half: sha256 over the render parameters and code
    fingerprint, the photo / plan / gallery strings the card ships, the property's considered
    set (merge's media_considered.json entry) and each considered deck's stat. None on any
    error or with no code fingerprint, and None is never reusable."""
    if not code_fp:
        return None
    try:
        deck_cache = {} if deck_cache is None else deck_cache
        h = hashlib.sha256(_key_params(code_fp, image_cache))
        for k in ("photo", "plan"):
            h.update(b"\0")
            h.update(str(prop.get(k) or "").encode("utf-8", "replace"))
        for g in (prop.get("gallery") or []):
            h.update(b"\0")
            h.update(str(g).encode("utf-8", "replace"))
        h.update(b"\x01")
        h.update(json.dumps(considered or {}, sort_keys=True, default=str).encode("utf-8"))
        decks = (considered or {}).get("decks") if isinstance(considered, dict) else None
        for name, d in sorted((decks or {}).items()):
            dd = dict(d) if isinstance(d, dict) else {}
            dd["file"] = name
            h.update(b"\0")
            h.update(_deck_stat(source_dir, dd, deck_cache).encode("utf-8", "replace"))
        return h.hexdigest()
    except Exception:
        return None


def _unassigned_key(unassigned: list, source_dir, image_cache, code_fp: str,
                    deck_cache: dict | None = None) -> str | None:
    """The same identity for `_unassigned/`: the unclaimed-page list, its decks' stats, the
    render parameters and the code fingerprint. None on any error."""
    if not code_fp:
        return None
    try:
        deck_cache = {} if deck_cache is None else deck_cache
        h = hashlib.sha256(_key_params(code_fp, image_cache))
        h.update(b"\x02")
        h.update(json.dumps(unassigned or [], sort_keys=True, default=str).encode("utf-8"))
        for entry in (unassigned or []):
            if isinstance(entry, dict):
                h.update(b"\0")
                h.update(_deck_stat(source_dir, entry, deck_cache).encode("utf-8", "replace"))
        return h.hexdigest()
    except Exception:
        return None


def _listing(base: Path, with_decisions: bool) -> dict:
    """{relative posix path: [size, mtime_ns]} for every file under `base` except the stamp
    itself, plus `../media_decisions.json` when asked and present. Raises on I/O errors; every
    caller treats that as "not current"."""
    out = {}
    if base.is_dir():
        for f in sorted(base.rglob("*")):
            if f.is_file() and not (f.parent == base and f.name == MEDIA_STAMP):
                st = f.stat()
                out[f.relative_to(base).as_posix()] = [st.st_size, st.st_mtime_ns]
    if with_decisions:
        dec = base.parent / "media_decisions.json"
        if dec.is_file():
            st = dec.stat()
            out[_DECISIONS_REL] = [st.st_size, st.st_mtime_ns]
    return out


def _write_stamp(base: Path, key, extra: dict, with_decisions: bool) -> bool:
    """Write `base/.media_stamp.json` LAST, after every file of the half. Never raises; a stamp
    that cannot be written is simply absent, so the next pass rebuilds (today's cost)."""
    if not key or not base.is_dir():
        return False
    try:
        stamp = {"v": MEDIA_STAMP_VERSION, "key": key}
        stamp.update(extra)
        stamp["files"] = _listing(base, with_decisions)
        stamp["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_json_atomic(base / MEDIA_STAMP, stamp)
        return True
    except Exception as e:
        try:
            (base / MEDIA_STAMP).unlink()
        except Exception:
            pass
        print(f"(per-property view: media stamp not written for {base}: {type(e).__name__}: "
              f"{e} - the half is rebuilt next time)", file=sys.stderr)
        return False


def _current_stamp(base: Path, key, with_decisions: bool) -> dict | None:
    """The stamp of `base` when it is CURRENT, else None. Never raises. Current means: it parses,
    it is this version, its key equals `key` (never None), nothing failed to write when it was
    made, and the files on disk are EXACTLY the listed files with the listed size and mtime - so
    a hand edit, a deleted render or a stray file all read as "rebuild"."""
    if not key:
        return None
    try:
        sp = base / MEDIA_STAMP
        if not sp.is_file():
            return None
        s = json.loads(sp.read_text(encoding="utf-8"))
        if not isinstance(s, dict) or s.get("v") != MEDIA_STAMP_VERSION or s.get("key") != key:
            return None
        if s.get("could_not_write"):
            return None
        files = s.get("files")
        if not isinstance(files, dict):
            return None
        want = {str(k): [int(x) for x in v] for k, v in files.items()}
        return s if _listing(base, with_decisions) == want else None
    except Exception:
        return None


def _want_media(media_view, media: bool = True) -> bool:
    """The one place the flag is read. `media_view` wins when given; None keeps the older
    `media` boolean, so an in-process caller written before the flag (the evals, a hand
    script) still gets the full view it always got. Only the CLI defaults to `auto`."""
    if media_view is None:
        return bool(media)
    if media_view not in MEDIA_VIEW_CHOICES:
        raise ValueError(f"media_view must be one of {MEDIA_VIEW_CHOICES}, got {media_view!r}")
    return media_view == "always"


def rebuild_command(work, source_dir=None, image_cache=None) -> str:
    """The exact command that writes the FULL view for this work dir. Printed wherever the
    media half was skipped, so the reader who needs the pixels is never left to reconstruct
    the invocation from a docstring."""
    parts = [f'python "{Path(__file__).resolve()}"', f'--work "{Path(work)}"',
             "--media-view always",
             (f'--source-dir "{Path(source_dir)}"' if source_dir
              else "--source-dir \"<the run's input folder>\"")]
    if image_cache:
        parts.append(f'--image-cache "{Path(image_cache)}"')
    return " ".join(parts)


def _shown(v) -> str:
    """A value for notes.md prose: the honest blank for any unknown form, else as stated."""
    return _N.BLANK if _N.looks_unknown(v) else str(v)


def _rmtree(path: Path, retries: int = 2, pause: float = 0.4) -> list:
    """Remove one tree and REPORT what survived, never raise.

    `shutil.rmtree(..., ignore_errors=True)` is how the F27 orphans came to exist: it returns
    without a word when a sync client or an open viewer holds a handle, and the directory entry
    outlives the run. So: clear a read-only bit an errant sync can leave, retry after a pause
    (a handle is released in well under a second), then LIST whatever is still on disk so the
    caller can say so instead of assuming."""
    def _on_err(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except Exception:
            pass
    kw = {"onexc": _on_err} if sys.version_info >= (3, 12) else {"onerror": _on_err}
    for attempt in range(retries + 1):
        try:
            shutil.rmtree(path, **kw)
        except Exception:
            pass
        if not path.exists():
            return []
        if attempt < retries:
            time.sleep(pause)
    try:
        left = sorted(str(p.relative_to(path.parent)) for p in path.rglob("*"))
    except Exception:
        left = []
    return [path.name] + left


def _prune_root(root: Path, keep: set, keep_unassigned: bool = False) -> dict:
    """Bring `properties/` to the state this pass will overwrite, BEFORE anything is written.

    Every entry is handled BY NAME; there is no blanket rmtree of the root any more:
      numbered `<id>-<slug>`, in `keep`   left alone; write_property rewrites every file in it
      numbered, NOT in `keep`             an ORPHAN (its property is gone, or its slug moved with a
                                          park rename): removed, and named under `pruned`
      `_unassigned/`                      the media half's once-per-run folder: cleared here and
                                          rebuilt later only when media is written, so a skipped
                                          pass never leaves a stale render behind - UNLESS the
                                          caller found its stamp CURRENT (`keep_unassigned`, fix
                                          2.2), in which case it is carried as it stands
      the files this module owns          removed here, written LAST (see _OWNED_ROOT_FILES)
      anything else                       not ours: left alone and named under `unrecognised`
    A removal that fails is named under `could_not_prune` and on stderr. That is the whole
    fix: the old code could not tell the operator it had left something behind."""
    out = {"pruned": [], "could_not_prune": [], "unrecognised": []}
    if not root.exists():
        return out
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        n = child.name
        if child.is_dir() and n in keep:
            continue
        if child.is_dir() and n == "_unassigned" and keep_unassigned:
            continue
        if child.is_dir() and (_NUMBERED_DIR_RX.match(n) or n == "_unassigned"):
            left = _rmtree(child)
            if left:
                out["could_not_prune"].append(n)
                print(f"WARN per-property view: could not remove {child} ({len(left)} entr(y/ies) "
                      f"still on disk; something is holding them). It is NOT a property of this "
                      f"run; delete it by hand once whatever holds it lets go.", file=sys.stderr)
            elif n != "_unassigned":
                out["pruned"].append(n)
            continue
        if child.is_file() and n in _OWNED_ROOT_FILES:
            try:
                child.unlink()
            except Exception:
                out["could_not_prune"].append(n)
            continue
        out["unrecognised"].append(n)
    return out


def _write_json_atomic(path: Path, obj, indent: int = 1) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_skip_marker(root: Path, cmd: str, carried: int = 0, total: int = 0) -> None:
    # fix 2.2: a `never` pass now CARRIES every media half whose inputs are unchanged, so the
    # marker names how many folders still hold one; those say `"carried": true` instead
    carried_line = (f"{carried} of {total} property folder(s) still hold a media half carried "
                    f"from an earlier full view whose inputs are unchanged (index.json "
                    f"media_carried); their `property.json` says `\"carried\": true`. The rest "
                    f"were not written on this pass.\n\n" if carried else "")
    (root / MEDIA_VIEW_MARKER).write_text(
        "# The media half of this view was NOT written on this pass\n\n" + carried_line +
        "`--media-view never` (or `auto`, the default) writes `property.json`, `sources.csv`, "
        "`notes.md` and `index.json` for every property and SKIPS the expensive half: `media/`, "
        "`media/considered/`, `media_decisions.json` and `_unassigned/`. Their absence here means "
        "*not asked for*, NOT *nothing was found*. A harvest that found nothing is reported "
        "inside `property.json[\"__media\"]` on a full pass, and every `property.json` on this "
        "pass says `\"skipped\": true` instead.\n\n"
        "Why: those files are page renders and decoded images, about 84% of an entire run's "
        "wall-clock on a measured pass and tens of MB rewritten into a folder a sync client then "
        "re-uploads, for a view that nothing reads back. The repair path is untouched: every "
        "`notes.md` still carries its property's repair key, and corrections go in "
        "`work/repairs.json` either way.\n\n"
        "To write the full view (the spine does this by itself whenever a pre-build gate blocks):"
        "\n\n    " + cmd + "\n", encoding="utf-8")


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
                   source_dir=None, image_cache=None, open_capture: list = (),
                   rebuild_cmd: str = "", media_key: str | None = None,
                   force_media: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mdir = out_dir / "media"
    # fix 2.2: a media half whose stamp is CURRENT (same inputs, same code, files on disk exactly
    # as written) is CARRIED - neither deleted on `never` nor re-rendered on `always`. Anything
    # less than certain (no key, a forced rebuild, any stamp doubt) takes the old path below.
    stamp = None if (force_media or not media_key) else _current_stamp(mdir, media_key, True)
    carried = stamp is not None
    media_left = []
    if not carried:
        # the media half of THIS directory from a previous pass goes first, whatever this pass
        # writes: a stale media_decisions.json describing files that are no longer there is the
        # same silent lie as a stale numbered folder, only one level down
        media_left = _rmtree(mdir) if mdir.exists() else []
        try:
            (out_dir / "media_decisions.json").unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            media_left.append(f"media_decisions.json ({type(e).__name__})")

    view = {k: v for k, v in prop.items() if k not in ("photo", "plan", "gallery")}
    written = {}
    if carried:
        written = dict(stamp.get("written") or {})
    elif media:
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
    if carried and media:
        # an `always` pass carrying a current half: by construction exactly what a rebuild would
        # write (same inputs, same code), so property.json reads as a fresh full view would.
        # index.json `media_carried` still records that nothing was re-rendered.
        view["__media"] = written or {"note": "no image data on this property"}
    elif carried:
        # a `never` pass that did NOT write media but still HAS a current half on disk: say so,
        # so it is never mistaken for either "written this pass" or "skipped"
        view["__media"] = dict(written, carried=True,
                               note=_CARRY_NOTE + ("" if written else
                                                   "; no image data on this property"))
    elif media:
        view["__media"] = written or {"note": "no image data on this property"}
    else:
        # NOT the "no image data" note above: that one means a full pass looked and found
        # nothing. This pass did not look, and the two must never read the same.
        view["__media"] = {
            "skipped": True,
            "note": ("media view NOT written on this pass (--media-view never): no media/, "
                     "media/considered/ or media_decisions.json exists for this property "
                     "because none was asked for, not because nothing was found"),
            "rebuild": rebuild_cmd or rebuild_command(out_dir.parent.parent)}
    if media_left:
        view["__media_could_not_clear"] = media_left
    # THE CONSIDERED SET: written only when merge recorded one for this property AND media files
    # are being written at all (--no-media means "no pixels", and that covers the discard pile).
    n_considered = 0
    failures: list = []
    if carried:
        n_considered = int(stamp.get("considered_files") or 0)
        if stamp.get("considered"):
            view["__media_considered"] = {
                "files": n_considered,
                "where": "media/considered/ - decisions in media_decisions.json"}
    elif media and isinstance(considered, dict) and considered:
        try:
            _dec = _considered_for_property(out_dir, considered, written, source_dir,
                                            image_cache)
            n_considered = _dec.get("considered_files", 0)
            for _d in (_dec.get("decks") or {}).values():
                failures.extend(_d.get("could_not_write") or [])
            view["__media_considered"] = {
                "files": n_considered,
                "where": "media/considered/ - decisions in media_decisions.json"}
        except Exception as e:                # derived view: never let it fail the projection
            view["__media_considered"] = {"error": f"{type(e).__name__}: {e}"}
            failures.append({"what": "considered set", "why": f"{type(e).__name__}: {e}"})
    if media and not carried and media_key:
        # LAST for the media half: after media/, media/considered/ and media_decisions.json, so a
        # crash mid-write leaves no stamp. A half with any write failure is stamped with them and
        # therefore never current - a host that could not render retries next time.
        _write_stamp(mdir, media_key,
                     {"written": written, "considered_files": n_considered,
                      "considered": "files" in (view.get("__media_considered") or {}),
                      "could_not_write": failures + [str(x) for x in media_left]},
                     with_decisions=True)
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

    # the shared predicate (contract C5): a string in any unknown form, or a key holding None
    # (a plausibility gate struck it; the card reads `tbd`). Numbers, lists and dicts are data.
    tbd = sorted(k for k, v in prop.items()
                 if (v is None or isinstance(v, str)) and _N.looks_unknown(v))
    lines = [f"# {prop.get('park') or 'Property'}  (id {prop.get('id')})", ""]
    lines += [f"- **repair key**: `{view['__repair_key']}`",
              f"- **city**: {_shown(prop.get('city'))}    **region**: {_shown(prop.get('region'))}",
              ""]
    if not media and carried:
        lines += ["- **media**: carried from an earlier full view (inputs unchanged)", ""]
    elif not media:
        lines += ["- **media**: NOT written on this pass (`--media-view never`). No `media/`, "
                  "`media/considered/` or `media_decisions.json` here means none was asked for, "
                  "not that the harvest found nothing. For the full view run:", "",
                  "```", view["__media"]["rebuild"], "```", ""]
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
    if open_capture:
        # commentary / denied-key / CJK-only tracker columns: READ (and visible
        # here + in the yield/Gaps chain) but deliberately never client-shown
        lines += [f"## Read but not shown on the card ({len(open_capture)})", ""]
        lines += [f"- `{e.get('column')}` = {e.get('value')}  "
                  f"({e.get('source_file')}, {e.get('locator')})"
                  for e in open_capture] + [""]
    lines += [f"## Repairs applied ({len(repairs)})", ""]
    lines += ([f"- `{r['id']}` {', '.join(r.get('changed', {}))} - {r.get('why','')}"
               for r in repairs] or ["- none"]) + [""]
    (out_dir / "notes.md").write_text("\n".join(lines), encoding="utf-8")
    # `_carried` is popped by build (it feeds index.json media_carried / media_rebuilt), so the
    # per-property entries of index.json keep their shape
    return {"dir": out_dir.name, "media": written, "tbd": len(tbd),
            "considered": n_considered, "_carried": carried}


def build(work: Path, canonical_path: Path | None = None, media: bool = True,
          source_dir=None, image_cache=None, media_view: str | None = None,
          force_media: bool = False) -> dict:
    """`media_view` is contract C4's flag ("auto" | "always" | "never"); it wins over the older
    `media` boolean when given. The spine passes it explicitly; see _want_media for the default.

    `force_media` (fix 2.2, CLI `--rebuild-media`) ignores every media stamp: `always` re-renders
    every half, `never` deletes every half. Without it a half whose stamp is current is CARRIED.
    The return dict gains `carried` / `rebuilt` (property folders) and `unassigned_carried`;
    index.json gains `media_carried` / `media_rebuilt` / `unassigned_carried`. All additive."""
    work = Path(work)
    media = _want_media(media_view, media)
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
    # the directory each property WILL occupy, decided up front so pruning knows what to keep.
    # Names are deterministic (`<id>-<slug>`), which is also why a crashed previous pass heals:
    # every file in every kept directory is rewritten below, whatever state it was left in.
    names = {str(p.get("id")): f"{str(p.get('id')).zfill(2)}-"
                               f"{slug(p.get('park') or p.get('city') or 'property')}"
             for p in props}
    # fix 2.2: the identity of every media half, computed ONCE per build (the code fingerprint
    # once, each deck's stat once). Computed even when `force_media`, because a forced rebuild
    # must still leave stamps behind for the next pass to carry. Any error -> None -> rebuild.
    try:
        code_fp = _code_fingerprint()
    except Exception:
        code_fp = ""
    deck_cache: dict = {}
    keys = {str(p.get("id")): media_key(p, considered_by_id.get(str(p.get("id"))), source_dir,
                                        image_cache, code_fp, deck_cache)
            for p in props}
    ua_key = _unassigned_key(unassigned, source_dir, image_cache, code_fp, deck_cache) \
        if unassigned else None
    ua_stamp = (None if (force_media or not ua_key)
                else _current_stamp(root / "_unassigned", ua_key, False))
    prune = _prune_root(root, set(names.values()), keep_unassigned=ua_stamp is not None)
    root.mkdir(parents=True, exist_ok=True)
    cmd = rebuild_command(work, source_dir, image_cache)

    made, carried_dirs, rebuilt_dirs = [], [], []
    for p in props:
        pid = str(p.get("id"))
        res = write_property(p, root / names[pid], by_id.get(pid, []),
                             conf_by_id.get(pid, []), rep_by_id.get(pid, []), media,
                             considered=considered_by_id.get(pid),
                             source_dir=source_dir, image_cache=image_cache,
                             open_capture=(data.get("meta", {})
                                           .get("openCapture") or {}).get(pid, []),
                             rebuild_cmd=cmd, media_key=keys.get(pid),
                             force_media=force_media)
        if res.pop("_carried", False):
            carried_dirs.append(res["dir"])
        elif media:
            rebuilt_dirs.append(res["dir"])
        made.append(res)
    ua_carried = ua_stamp is not None
    if ua_carried:
        n_orphan = int(ua_stamp.get("total") or 0)
    elif media:
        ua_fail: list = []
        n_orphan = _write_unassigned(root, unassigned, source_dir, image_cache,
                                     failures_out=ua_fail)
        if unassigned and ua_key:
            _write_stamp(root / "_unassigned", ua_key,
                         {"total": n_orphan, "could_not_write": ua_fail}, with_decisions=False)
    else:
        n_orphan = 0
    # a `never` pass whose every media half (and _unassigned/, if the run has one) was carried
    # skipped NOTHING, so it writes no skip marker; any folder lacking a current half keeps it
    lacking = len(made) - len(carried_dirs)
    ua_lacking = bool(unassigned) and not ua_carried
    all_carried = bool(made) and not lacking and not ua_lacking
    if not media and not all_carried:
        _write_skip_marker(root, cmd, carried=len(carried_dirs), total=len(made))
    # the considered-set render loop opens each deck through IMG's shared doc cache; release the
    # handles before returning (on Windows a held handle blocks an in-process caller's temp-dir
    # cleanup, and this projection owns no later image work). Only when images was imported at
    # all: a pass that carried every half never touched it and need not pay its import.
    try:
        _IMG = sys.modules.get("images")
        if _IMG is not None:
            _IMG.close_doc_cache()
    except Exception:
        pass
    index = {"count": len(made), "properties": made,
             # None, not 0, when the media half was skipped: "no unclaimed pages" is a finding,
             # "did not look" is not one, and the two must not share a value
             "unassigned_pages": (n_orphan if (media or ua_carried) else None),
             "media_view": ("always" if media else "never"),
             # fix 2.2, additive: which folders' media halves were carried unchanged from an
             # earlier full view, and which were (re)written on this pass
             "media_carried": carried_dirs, "media_rebuilt": rebuilt_dirs,
             "unassigned_carried": ua_carried,
             "pruned": prune["pruned"], "could_not_prune": prune["could_not_prune"],
             "unrecognised": prune["unrecognised"]}
    if not media:
        if all_carried:
            index["media_note"] = ("no media half was written on this pass, and none was "
                                   "needed: every property folder (and _unassigned/, if any) "
                                   "holds a media half carried from an earlier full view whose "
                                   "inputs are unchanged (media_carried)")
        else:
            index["media_note"] = (f"media/, media/considered/, media_decisions.json and "
                                   f"_unassigned/ were deliberately not written; see "
                                   f"{MEDIA_VIEW_MARKER}"
                                   + (f". {len(carried_dirs)} of {len(made)} property "
                                      f"folder(s) still hold a media half carried from an "
                                      f"earlier full view whose inputs are unchanged "
                                      f"(media_carried)" if carried_dirs else ""))
        index["rebuild"] = cmd
    if prune["pruned"]:
        print(f"(per-property view: removed {len(prune['pruned'])} orphaned folder(s) no property "
              f"of this run owns: {', '.join(prune['pruned'])})", file=sys.stderr)
    # LAST, and atomically: a folder with no index.json is a projection that did not finish
    _write_json_atomic(root / "index.json", index)
    return {"count": len(made), "root": str(root), "unassigned": n_orphan,
            "media_view": index["media_view"], "pruned": prune["pruned"],
            "could_not_prune": prune["could_not_prune"],
            "carried": len(carried_dirs), "rebuilt": len(rebuilt_dirs),
            "unassigned_carried": ua_carried}


def _write_unassigned(root: Path, unassigned: list, source_dir=None, image_cache=None,
                      failures_out: list | None = None) -> int:
    """`properties/_unassigned/` - ONCE per run, the deck pages NO property claimed.

    These pages are the run's blind spot: no gallery scan, no plan tier and no placeholder audit
    ever reached them, so nothing else in the pipeline can even mention them. On a multi-property
    or whole-park donor deck that is exactly where a missed site plan sits. Same shape as a
    property's considered/ folder, so it is read the same way. Returns the page count.
    `failures_out` (fix 2.2) collects every render/candidate failure, so the folder's stamp can
    record them and the next pass retries instead of carrying a partial folder."""
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
        if failures_out is not None:
            failures_out.extend(failures)
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
        "DERIVED: rebuilt whenever its inputs change (and carried unchanged otherwise), "
        "never read back.\n\n"
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
    ap.add_argument("--media-view", dest="media_view", choices=MEDIA_VIEW_CHOICES, default="auto",
                    help="always: media/, media/considered/, media_decisions.json and _unassigned/ "
                         "as well as the cheap files; never: the cheap files only, with "
                         f"{MEDIA_VIEW_MARKER} saying so and giving the command for the rest; "
                         "auto (default) is never. The spine passes always only when a pre-build "
                         "gate has blocked, which is when a human is about to open the folder")
    ap.add_argument("--no-media", action="store_true",
                    help="the older spelling of --media-view never; an explicit no wins if both are given")
    ap.add_argument("--source-dir", dest="source_dir", default="",
                    help="the run's INPUT folder - enables media/considered/ (every page render "
                         "and candidate image each property had to choose from) and _unassigned/")
    ap.add_argument("--image-cache", dest="image_cache", default="",
                    help="the run's image cache dir (only used to reuse a PPTX->PDF conversion)")
    ap.add_argument("--rebuild-media", dest="rebuild_media", action="store_true",
                    help="ignore every media stamp and re-render the whole media half (a half "
                         "whose inputs are unchanged is otherwise carried as it stands). Implies "
                         "--media-view always unless never/--no-media is given explicitly")
    a = ap.parse_args()
    mv = "never" if a.no_media else a.media_view
    if a.rebuild_media and mv == "auto":
        mv = "always"          # "rebuild the media" with the default mode would delete it
    r = build(Path(a.work), Path(a.canonical) if a.canonical else None, media_view=mv,
              source_dir=(Path(a.source_dir) if a.source_dir else None),
              image_cache=(Path(a.image_cache) if a.image_cache else None),
              force_media=bool(a.rebuild_media))
    print(f"OK per-property projection: {r['count']} property folder(s) -> {r['root']}"
          + (f"; {r['unassigned']} unclaimed deck page(s) -> {r['root']}/_unassigned"
             if r.get("unassigned") else "")
          + (f"; media half: {r.get('carried', 0)} carried unchanged, "
             f"{r.get('rebuilt', 0)} rebuilt" if (r.get("carried") or r.get("rebuilt")) else "")
          + (f"; media view skipped (--media-view {mv}), see {r['root']}/{MEDIA_VIEW_MARKER}"
             if r.get("media_view") == "never" and (Path(r["root"]) / MEDIA_VIEW_MARKER).exists()
             else "")
          + (f"; pruned {len(r['pruned'])} orphaned folder(s)" if r.get("pruned") else "")
          + (f"; COULD NOT REMOVE {len(r['could_not_prune'])} stale entr(y/ies), see index.json"
             if r.get("could_not_prune") else ""))
    return 0


if __name__ == "__main__":
    try:                     # D16: UTF-8 console. Guarded and locally imported so a
        import _common as _C  # bootstrap tool is never stopped by this call itself.
        _C.force_utf8_stdout()
    except Exception:
        pass
    raise SystemExit(main())
