#!/usr/bin/env python3
"""translate.py - Phase 2 free-text DATA translation to output.language.
Determinism collects eligible prose + bakes translations (keeping the verbatim original in the
ledger); the LLM (an isolated sub-agent) does the actual translation. No template/chrome change."""
from __future__ import annotations
import csv
import hashlib
import json
import os
import sys
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
            if text_key(v, target_code) in cache or v in translated_values:
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
    return data if isinstance(data, dict) else {}


def _hashed_cache(raw_cache: dict, target_code: str) -> dict:
    """The on-disk cache is the human/agent handoff: a RAW {source_text: translation} map (what
    the exit-12 sub-agent writes, per SKILL.md / the request instructions). `collect_requests` and
    `bake` look up by `text_key` (sha256 of target_code + source), so rekey the raw map here. Doing
    it at this boundary keeps the file human-readable AND makes a changed output.language re-translate
    (a different target_code -> different keys -> cache miss). Non-string keys/values are dropped."""
    return {text_key(k, target_code): v for k, v in raw_cache.items()
            if isinstance(k, str) and isinstance(v, str)}


def _short(v, n: int = 60) -> str:
    """Mirrors merge.py's `_short` truncator exactly, so a translated/original value in the
    ledger reads the same as every other ledger value (60 chars + an ellipsis)."""
    s = str(v)
    return s[:n] + ("…" if len(s) > n else "")


def _append_ledger_rows(ledger_path: Path, rows: list[dict], lang: str) -> None:
    """Append one CSV row per baked field to source_ledger.csv, MATCHING merge.py's exact
    column order (ledger_rows.append({...}) in merge.py's per-property loop: property_id,
    record_type, field, value, source_file, source_locator, source_type, extractor,
    confidence, conflict_note, verified). Read from the ledger's OWN header (not hard-coded)
    so a future header change in merge.py can never desync the two writers.

    Append-only (open "a") and best-effort: if the ledger doesn't exist yet (or anything
    about the append fails), do nothing - the translation stage must never crash the run
    over an audit-trail nicety."""
    p = Path(ledger_path)
    if not p.exists():
        return
    try:
        with open(p, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh), None)
        if not header:
            return
        out_rows = []
        for r in rows:
            original = _short(r.get("original"))
            translated = _short(r.get("translated"))
            row = {
                "property_id": r.get("property_id"),
                "record_type": "property",
                "field": r.get("field"),
                "value": translated,
                "source_file": "(translation)",
                "source_locator": f"translated -> {lang} (derived-from-source; original: {original})",
                "source_type": "",
                "extractor": "T-translate",
                "confidence": "",
                "conflict_note": "",
                "verified": "",
            }
            out_rows.append([row.get(h, "") for h in header])
        with open(p, "a", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerows(out_rows)
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
    cache = _hashed_cache(_load_cache(cache_path), target_code)
    reqs = collect_requests(canon, target_code, cache)
    if reqs:
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
        _append_ledger_rows(Path(ledger_path), rows, lang)
    return None
