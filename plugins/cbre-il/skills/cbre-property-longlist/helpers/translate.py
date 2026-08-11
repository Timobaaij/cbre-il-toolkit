#!/usr/bin/env python3
"""translate.py - Phase 2 free-text DATA translation to output.language.
Determinism collects eligible prose + bakes translations (keeping the verbatim original in the
ledger); the LLM (an isolated sub-agent) does the actual translation. No template/chrome change."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# Blanket opt-out for offline / non-agentic runs (e.g. the extract_test end-to-end spine, which
# exercises extraction->delivery, not translation, and cannot fulfil an exit-12 handoff). Idiomatic
# here alongside CBRE_IMAGE_WORKERS/CBRE_PREWARM_SECONDS. Unset -> normal behaviour. The production
# per-run decline is the work/i18n/data_translate.SKIP file.
SKIP_ENV = "CBRE_LONGLIST_SKIP_DATA_TRANSLATE"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def text_key(text: str, target_code: str) -> str:
    return hashlib.sha256((target_code + "␟" + str(text)).encode("utf-8")).hexdigest()


# TYPOGRAPHIC FOLDS for the tolerant fallback key. The exit-12 hand-off is a RAW
# {source_text: translation} map written by a sub-agent, and the lookup hashes the source's
# EXACT BYTES - so a model that retypes a curly apostrophe as straight, an en dash as a hyphen,
# or re-wraps a long description missed the key, and the SAME item was re-requested every round.
# `gate_runner.cmd_translation` uses the same predicate, so a non-fatal exit 12 then blocked as
# exit 6, and the only escape shipped the data untranslated. These characters are pure
# typography: folding them cannot change which prose a translation belongs to.
_TYPO_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "−": "-", " ": " ", "…": "...",
}


def norm_key(text: str, target_code: str) -> str:
    """A TOLERANT companion to `text_key`: same string with typographic variants folded,
    whitespace collapsed and case ignored. Consulted only AFTER an exact miss, so an exact
    match always wins and the byte-keyed behaviour is unchanged. Deterministic."""
    # NFC first: an agent that retypes an accented word may emit it DECOMPOSED (e + combining
    # acute) where the source is composed. Those are the SAME character by Unicode canonical
    # equivalence, so folding them cannot change which prose a translation belongs to.
    # NOT NFKC - that is a COMPATIBILITY fold: it rewrites 'm2' from 'm2' and merges
    # ligatures, i.e. it can make DIFFERENT prose collide, and shipping a wrong translation is
    # far worse than re-requesting one. (B03)
    s = unicodedata.normalize("NFC", str(text))
    for a, b in _TYPO_FOLD.items():
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return hashlib.sha256((target_code + "␟~" + s).encode("utf-8")).hexdigest()


def collect_requests(canonical: dict, target_code: str, cache: dict) -> list[dict]:
    """Eligible free-text values across all properties that are NOT already cached, as
    {property_id, field, text}. Deterministic + stable order.

    RESUME-SAFETY: `bake` overwrites canonical.json in place, keyed on SOURCE text. On a
    resumed run where merge was skipped, the on-disk canonical is already BAKED (its values
    ARE the target-language translations), so the source-keyed cache lookup alone would
    re-flag already-translated prose as uncached. A value that already EQUALS a cached
    translation (i.e. is itself in cache.values()) is therefore also treated as satisfied."""
    out = []
    translated_values = {v for v in cache.values() if isinstance(v, str)}  # already-baked target strings
    for p in canonical.get("properties", []):
        pid = p.get("id")
        for field in sorted(p.keys()):
            v = p[field]
            if not C.is_translatable_value(field, v):
                continue
            if (text_key(v, target_code) in cache
                    or norm_key(v, target_code) in cache      # retyped punctuation still counts
                    or v in translated_values):
                continue  # source cached, OR already the baked translation
            out.append({"property_id": pid, "field": field, "text": v})
    return out


def bake(canonical: dict, translations: dict, target_code: str) -> list[dict]:
    """Apply cached translations to eligible fields ONLY; return audit rows preserving the
    verbatim original. A translation keyed to a NON-eligible field is ignored (identifiers /
    figures can never be altered). `translations` maps text_key -> translated string."""
    rows = []
    for p in canonical.get("properties", []):
        pid = p.get("id")
        for field in sorted(p.keys()):
            v = p[field]
            if not C.is_translatable_value(field, v):
                continue
            t = translations.get(text_key(v, target_code))
            if t is None:  # exact wins; fall back to the typography-tolerant key
                t = translations.get(norm_key(v, target_code))
            if not isinstance(t, str) or not t.strip() or t == v:
                continue  # missing / unchanged (already target) -> no-op
            rows.append({"property_id": pid, "field": field, "original": v, "translated": t})
            p[field] = t
    return rows


def _load_cache(p: Path) -> dict:
    """Load the externally-merged {text: translation} cache. This is the ONE non-deterministic
    input (a translation sub-agent writes it), so validate its SHAPE: anything that isn't a JSON
    object degrades to {} rather than crashing the run (mirrors i18n.py's cache loaders). Per-value
    hygiene (non-string translations) is handled by the callers (collect_requests filters, bake
    checks isinstance)."""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _unwrap_cache(data)


# The shapes a translation sub-agent naturally returns instead of the documented flat map.
# Each of these used to degrade to {} - and a {} cache means run.py re-emits a BYTE-IDENTICAL
# exit-12 request, so the round repeated forever with nothing in the output to explain why.
# This is the actual exit-12 livelock: a cache SHAPE problem, not the key-normalisation
# problem it was filed as. Accepting them costs nothing - a wrong-shaped cache that resolves
# no item is still caught by cache_shape_note below. (B03)
_ENVELOPE_KEYS = ("translations", "items", "results", "data", "entries")
_SRC_KEYS = ("text", "source", "source_text", "src", "key", "original")
_TGT_KEYS = ("translation", "target", "translated", "value", "text_translated")


def _unwrap_cache(data):
    """Coerce the accepted sub-agent shapes to a flat {source: translation} dict."""
    if isinstance(data, dict):
        # an envelope wrapping the real map (or the real list)
        for k in _ENVELOPE_KEYS:
            inner = data.get(k)
            if isinstance(inner, (dict, list)) and inner:
                return _unwrap_cache(inner)
        return data
    if isinstance(data, list):
        out: dict = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            src = next((row[s] for s in _SRC_KEYS if isinstance(row.get(s), str)), None)
            tgt = next((row[t] for t in _TGT_KEYS if isinstance(row.get(t), str)), None)
            if src is not None and tgt is not None:
                out.setdefault(src, tgt)
        return out
    return {}


def index_by_request(raw_cache: dict, target_code: str, requests: list) -> dict:
    """Resolve a cache addressed by ITEM IDENTITY ("<property_id>:<field>") against the
    request list that produced it.

    This is the second livelock shape, and the nastier one: the entries are well-formed
    strings, so nothing looks wrong - they simply key on the item's ADDRESS rather than its
    text, match no source, and re-request forever. Only the request list can map an address
    back to its prose, which is why this cannot live in _hashed_cache. (B03)"""
    if not isinstance(raw_cache, dict) or not requests:
        return {}
    by_addr = {}
    for r in requests:
        pid, fld = r.get("property_id"), r.get("field")
        txt = r.get("text")
        if not isinstance(txt, str):
            continue
        for form in (f"{pid}:{fld}", f"{pid}|{fld}", f"{pid}.{fld}"):
            by_addr[form.lower()] = txt
    out: dict = {}
    for k, v in raw_cache.items():
        if not (isinstance(k, str) and isinstance(v, str)):
            continue
        src = by_addr.get(k.strip().lower())
        if src is not None:
            out[text_key(src, target_code)] = v
            out.setdefault(norm_key(src, target_code), v)
    return out


def cache_shape_note(raw_cache: dict, hashed: dict, target_code: str) -> str:
    """A one-line diagnosis when a NON-EMPTY cache resolved NOTHING.

    Without this the failure is invisible: the request is re-emitted byte-identically and the
    orchestrator has no way to tell "the sub-agent has not answered yet" from "the sub-agent
    answered in a shape nothing reads". Returns "" when there is nothing to say. (B03)"""
    if hashed or not isinstance(raw_cache, dict) or not raw_cache:
        return ""
    sample = ", ".join(repr(k)[:40] for k in list(raw_cache)[:3])
    return (f"translation cache has {len(raw_cache)} entr(y/ies) but resolved 0 of this "
            f"round's items - the keys do not match any requested SOURCE TEXT. Expected a "
            f"flat {{\"<source text>\": \"<translation>\"}} map. Got keys like: {sample}")


def _hashed_cache(raw_cache: dict, target_code: str) -> dict:
    """The on-disk cache is the human/agent handoff: a RAW {source_text: translation} map (what
    the exit-12 sub-agent writes, per SKILL.md / the request instructions). `collect_requests` and
    `bake` look up by `text_key` (sha256 of target_code + source), so rekey the raw map here. Doing
    it at this boundary keeps the file human-readable AND makes a changed output.language re-translate
    (a different target_code -> different keys -> cache miss). Non-string keys/values are dropped."""
    out: dict = {}
    for k, v in raw_cache.items():
        if not (isinstance(k, str) and isinstance(v, str)):
            continue
        out[text_key(k, target_code)] = v
        # ALSO index under the typography-tolerant key so a retyped source still resolves.
        # setdefault, so an exact-byte entry always wins over a folded one.
        out.setdefault(norm_key(k, target_code), v)
    return out


def _short(v, n: int = 60) -> str:
    """60 chars + an ellipsis, like merge.py's `_short`, but COLLAPSING ALL WHITESPACE FIRST.

    The whitespace collapse is a deliberate divergence from merge.py, not an accident. A CSV field
    may legally contain a control character, and `csv.writer` under `lineterminator="\\n"` only
    quotes on the delimiter, the quote char and `\\n` - so a VERTICAL TAB (`\\x0b`) is written raw.
    `python-pptx` renders a soft line break as exactly that, and `str.splitlines()` SPLITS on it,
    plus `\\x0c`, `\\x1c-\\x1e`, `\\x85`, `\\u2028` and `\\u2029`. Any consumer that reads the ledger
    by splitting text (rather than iterating the file object) therefore shatters such a row into a
    short fragment. `" ".join(str(v).split())` splits on every one of those characters and rejoins
    on a plain space, so this writer can never emit one. See `_write_ledger_rows`, which is
    ALSO hardened at the read end - both, because merge.py still emits raw control characters.
    """
    s = " ".join(str(v).split())
    return s[:n] + ("…" if len(s) > n else "")


def _rows_path(tdir, target_code: str) -> Path:
    return Path(tdir) / f"data_translate_rows.{target_code}.json"


def _load_rows(tdir, target_code: str) -> list[dict]:
    try:
        d = json.loads(_rows_path(tdir, target_code).read_text(encoding="utf-8"))
    except Exception:
        return []
    return [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []


def _save_rows(tdir, target_code: str, rows: list[dict]) -> None:
    """RECORD what `bake` actually did, keyed by (property_id, field), merging with earlier passes.

    Why this file exists: a later reconcile has to name each translated value's VERBATIM ORIGINAL
    in the ledger locator, but by then canonical holds the TRANSLATION - the original is gone. The
    only other way to recover it is to invert the {source: translation} cache, which is a GUESS
    (two sources can share one translation). Persisting bake's own rows makes the original a
    RECORDED FACT; the inversion stays as a fallback and is tagged as reconstructed."""
    try:
        merged = {(str(r.get("property_id")), r.get("field")): r
                  for r in _load_rows(tdir, target_code)}
        for r in rows:
            merged[(str(r.get("property_id")), r.get("field"))] = {
                "property_id": r.get("property_id"), "field": r.get("field"),
                "original": r.get("original"), "translated": r.get("translated")}
        C.atomic_write_text(_rows_path(tdir, target_code),
                            json.dumps([merged[k] for k in sorted(merged)],
                                       ensure_ascii=False, indent=2))
    except Exception:
        pass  # best-effort - the audit trail must never crash the stage


def _ledger_row_set(canonical: dict, raw_cache: dict, target_code: str,
                    baked: list[dict], recorded: list[dict] | None = None) -> list[dict]:
    """The COMPLETE set of T-translate audit rows implied by the CURRENT canonical, in `bake`'s
    own order (canonical property order, then `sorted(p.keys())`) - so the pass that BAKES and
    every later pass that merely RECONCILES emit the identical byte sequence.

    Three sources of the verbatim original, most trustworthy first:
      1. `baked`   - what THIS pass just translated. Authoritative.
      2. `recorded`- what an EARLIER pass recorded (data_translate_rows.<code>.json), accepted only
                     when its `translated` still equals the current canonical value.
      3. the INVERSE of the raw {source: translation} cache - a reconstruction, tagged as such in
         the locator. Built over `sorted(...)` with `setdefault`, so when two sources share one
         translation the choice is deterministic and byte-stable rather than dict-order dependent.

    Only the parenthetical original in the locator is ever affected by falling back to (3); the
    property value itself is never inferred."""
    by_key = {(str(r.get("property_id")), r.get("field")): r for r in baked}
    rec = {(str(r.get("property_id")), r.get("field")): r for r in (recorded or [])}
    inverse: dict[str, str] = {}
    for k, v in sorted((k, v) for k, v in raw_cache.items()
                       if isinstance(k, str) and isinstance(v, str) and v != k):
        inverse.setdefault(v, k)
    rows: list[dict] = []
    for p in canonical.get("properties", []):
        pid = p.get("id")
        for field in sorted(p.keys()):
            v = p[field]
            if not C.is_translatable_value(field, v):
                continue
            key = (str(pid), field)
            hit = by_key.get(key)
            if hit is None:
                prev = rec.get(key)
                if prev is not None and prev.get("translated") == v:
                    hit = prev
            if hit is not None:
                rows.append({"property_id": pid, "field": field,
                             "original": hit.get("original"), "translated": v,
                             "reconstructed": False})
            elif v in inverse:
                rows.append({"property_id": pid, "field": field,
                             "original": inverse[v], "translated": v,
                             "reconstructed": True})
    return rows


def _write_ledger_rows(ledger_path: Path, rows: list[dict], lang: str) -> None:
    """RECONCILE source_ledger.csv so its T-translate rows are EXACTLY `rows`: read every row,
    DROP every row THIS writer owns (extractor == 'T-translate'), re-add the current set, rewrite
    ATOMICALLY. Column order comes from the ledger's OWN header, so a header change in merge.py
    can never desync the two writers. Mirrors enrich._update_ledger's read-all/rewrite pattern.

    WHY NOT APPEND ANY MORE. `open(p, "a")` could only ever ADD rows, so a row shape fixed in code
    could not replace the malformed rows an older build had already written - `ledger.py validate`
    kept blocking at exit 6 and the ONLY remedy was hand-deleting canonical.json +
    source_ledger.csv. This writer is idempotent with respect to its own rows, so the stage heals.

    THE PARSE ITERATES THE FILE OBJECT, NEVER `str.splitlines()`. This is not a style choice.
    `csv.writer` under `lineterminator="\\n"` does not quote a VERTICAL TAB, and merge.py's own
    `_short` does not strip one, so a PPTX-sourced description (python-pptx renders a soft line
    break as `\\x0b`) puts a raw control character inside a CSV field. `splitlines()` splits on it,
    which would shatter that row into a short fragment - and because the fragment then has no
    `extractor` column, THIS writer could never recognise or remove its own damage, leaving
    `ledger validate` blocked forever and hand-deletion as the only escape: precisely the failure
    this fix exists to abolish. File iteration splits on `\\n` / `\\r\\n` only. `evals/
    translate_e2e_test.py` carries a `\\x0b` fixture and asserts every row keeps its full field
    count, so a regression here fails the battery.

    The reviewer's own marks are CARRIED FORWARD. `verified` and `conflict_note` on a T-translate
    row are set by the G-trace reviewer; rewriting them to "" would be Python silently erasing an
    LLM judgement inside the very artefact whose purpose is to carry it.

    Best-effort and NO-OP-SAFE: nothing is written until the whole buffer is built, and the file is
    left untouched in BYTES AND MTIME when there is nothing of ours to remove and nothing to add,
    or when the rebuilt bytes match. An mtime bump alone would re-fire `deliver` on every
    invocation via run.py's `_deliver_inputs`."""
    p = Path(ledger_path)
    if not p.exists():
        return
    try:
        # TWO opens, deliberately: the byte-compare needs the exact current text, and the PARSE
        # must iterate the file object (see the docstring - never splitlines()).
        with open(p, "r", encoding="utf-8", newline="") as fh:
            current = fh.read()
        with open(p, "r", encoding="utf-8", newline="") as fh:
            rdr = csv.reader(fh)
            header = next(rdr, None)
            if not header:
                return
            idx = {c: header.index(c) for c in header}
            ei, ki, fi = idx.get("extractor"), idx.get("property_id"), idx.get("field")
            keep: list[list[str]] = []
            prior: dict[tuple, list[str]] = {}
            dropped = 0
            for r in rdr:
                if ei is not None and len(r) > ei and r[ei] == "T-translate":
                    dropped += 1
                    if ki is not None and fi is not None and len(r) > max(ki, fi):
                        prior[(r[ki], r[fi])] = r
                    continue
                keep.append(r)
        if not dropped and not rows:
            return  # nothing of ours present, nothing to add -> do NOT rewrite or bump mtime

        def _carry(old, col):
            i = idx.get(col)
            return old[i] if (old is not None and i is not None and len(old) > i) else ""

        out_rows = []
        for r in rows:
            old = prior.get((str(r.get("property_id")), str(r.get("field"))))
            original = _short(r.get("original"))
            translated = _short(r.get("translated"))
            loc = f"translated -> {lang} (derived-from-source; original: {original})"
            if r.get("reconstructed"):
                loc = (f"translated -> {lang} (derived-from-source; original: {original} "
                       f"[reconstructed from the translation cache])")
            row = {
                "property_id": r.get("property_id"),
                "record_type": "property",
                "field": r.get("field"),
                "value": translated,
                "source_file": "(translation)",
                "source_locator": loc,
                # MUST be non-empty: ledger.REQUIRED includes source_type, so an empty string
                # here made `ledger.py validate` BLOCK the run with "missing ['source_type']"
                # on every baked row (exit 6). Latent until now because every English run
                # declines this stage via data_translate.SKIP - it first bit on a live
                # fully-Chinese build. 'derived' (not 'gap') is the honest value: the text IS
                # traceable, to the original named in source_locator, and trace-coverage only
                # rejects 'gap', so a translated field still counts as sourced.
                "source_type": "derived",
                "extractor": "T-translate",
                "confidence": _carry(old, "confidence"),
                "conflict_note": _carry(old, "conflict_note"),
                "verified": _carry(old, "verified"),
            }
            out_rows.append([row.get(h, "") for h in header])
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerows(keep)
        w.writerows(out_rows)
        text = buf.getvalue()
        if text == current:
            return  # byte-identical -> no write, no mtime bump, deliver stays resumed
        C.atomic_write_text(p, text)
    except Exception:
        pass  # best-effort - never crash the translation stage over the audit trail


def run_stage(work, canonical_path, ledger_path, lang, quiet=False):
    """Phase-2 free-text translation stage. Returns 12 when a translation round is needed
    (having written work/i18n/data_translate_request.json), else None after baking any cached
    translations into canonical (+ appending derived-from-source ledger rows). Never calls
    sys.exit (the caller decides). Target = output.language (any European language)."""
    import i18n as I18N
    target_code = I18N.normalize_lang(lang)
    tdir = Path(work) / "i18n"
    # DECLINE (mirrors the exit-11 chrome fallback): an orchestrator (or an offline run/test that
    # is not exercising translation) drops work/i18n/data_translate.SKIP to ship the data
    # untranslated. The run then proceeds with no exit 12 and no bake (the translation gate treats
    # the SKIP as an acknowledged decline). This keeps a non-agentic/offline run from stalling on
    # a handoff nobody will fulfil.
    if os.environ.get(SKIP_ENV) == "1" or (tdir / "data_translate.SKIP").exists():
        return None
    # LANGUAGE-TAGGED cache: the file is data_translations.<code>.json so rebuilding the SAME work
    # dir under a different output.language keeps a separate cache and never reuses stale
    # translations (the old untagged data_translations.json cross-contaminated languages).
    cache_path = tdir / f"data_translations.{target_code}.json"
    canon = C.load_canonical(Path(canonical_path))
    raw_cache = _load_cache(cache_path)          # the RAW {source: translation} handoff, kept so
    cache = _hashed_cache(raw_cache, target_code)  # a reconcile can recover originals (see
    # A cache addressed by ITEM IDENTITY ("<property_id>:<field>") is well-formed but hashes to
    # nothing, so fold it in against the full item list before deciding what is outstanding.
    # Only the request list can map an address back to its prose. (B03)
    if raw_cache and not cache:
        cache = index_by_request(raw_cache, target_code,
                                 collect_requests(canon, target_code, {}))
    reqs = collect_requests(canon, target_code, cache)  # _ledger_row_set)
    if reqs:
        # A NON-EMPTY cache that resolved NOTHING is the exit-12 livelock's signature: the
        # request below is re-emitted byte-identically, so without this line the orchestrator
        # cannot tell "not answered yet" from "answered in a shape nothing reads". (B03)
        _note = cache_shape_note(raw_cache, cache, target_code)
        if _note:
            print(f"NOTE {_note}")
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "data_translate_request.json").write_text(json.dumps({
            "target_language": lang, "target_code": target_code,
            "instructions": ("Translate each item's `text` to " + str(lang) + ". Return a JSON object "
                "mapping each item's text VERBATIM to its translation. Translate PROSE only: keep "
                "numbers, units, codes, dates, proper names (companies, places), and any figure "
                "embedded in the prose EXACTLY. If a value is already in the target language or is "
                "actually a proper name/code, return it unchanged. Do NOT translate any field not "
                "listed here."),
            "items": reqs,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return 12
    rows = bake(canon, cache, target_code)
    if rows:
        C.atomic_write_text(Path(canonical_path), json.dumps(canon, ensure_ascii=False, indent=2))
        _save_rows(tdir, target_code, rows)   # record the verbatim originals while we still have them
    # RECONCILE ON EVERY NON-DECLINED PASS, not only when `bake` changed something. This is the
    # LOAD-BEARING half of the fix and the non-obvious one: on a resumed run merge is SKIPPED
    # (the earlier bake made canonical + the ledger newer than every merge input, so run.py's
    # resume predicate holds), and canonical is already baked - so `bake` returns [] and the OLD
    # call site, being inside `if rows:`, was never reached. That is EXACTLY the pass on which a
    # malformed row from an older build sits in the ledger with nothing able to remove it: merge
    # would rewrite the file, but merge stays skipped precisely because the bake touched it.
    # Recomputing the full set from canonical + the recorded rows + the cache makes the stage
    # self-healing as well as idempotent. Both no-write guards live in _write_ledger_rows, so a
    # ledger with none of our rows is untouched in bytes AND mtime.
    _write_ledger_rows(Path(ledger_path),
                       _ledger_row_set(canon, raw_cache, target_code, rows,
                                       _load_rows(tdir, target_code)), lang)
    return None
