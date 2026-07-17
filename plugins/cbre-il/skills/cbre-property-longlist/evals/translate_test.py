#!/usr/bin/env python3
"""translate_test.py - Phase 2 data-translation unit tests. Offline (no LLM).
Run: python evals/translate_test.py   (exit 0 on success, 1 on failure)"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import translate as TR  # noqa: E402

def main() -> int:
    fails = []
    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}");  (fails.append(l) if not ok else None)

    canon = {"properties": [
        {"id": 1, "description": "Plataforma logística en construcción", "status": "En construcción",
         "developer": "7R", "clearHeight": "12 m", "landUse": "uso industrial"},
        {"id": 2, "description": "Existing warehouse", "status": "Existing", "developer": "GLP"},
    ]}
    reqs = TR.collect_requests(canon, "en", {})
    fields = {(r["property_id"], r["field"]) for r in reqs}
    ck((1, "description") in fields and (1, "status") in fields and (1, "landUse") in fields,
       "collect_requests picks prose fields (description/status/landUse)")
    ck((1, "developer") not in fields and (1, "clearHeight") not in fields,
       "collect_requests excludes proper-name/figure fields")

    # bake: only eligible fields change; original preserved in the returned audit; non-eligible ignored
    translations = {
        TR.text_key("Plataforma logística en construcción", "en"): "Logistics platform under construction",
        TR.text_key("En construcción", "en"): "Under construction",
        TR.text_key("uso industrial", "en"): "industrial use",
        TR.text_key("7R", "en"): "SEVEN-R",            # a doctored translation of a NON-eligible field
    }
    rows = TR.bake(canon, translations, "en")
    ck(canon["properties"][0]["description"] == "Logistics platform under construction",
       "bake applies the translation to an eligible field")
    ck(canon["properties"][0]["developer"] == "7R",
       "bake NEVER changes a non-eligible field, even if a translation is supplied for it")
    ck(any(r["field"] == "description" and r["original"] == "Plataforma logística en construcción"
           for r in rows), "bake returns an audit row preserving the verbatim original")
    # cache no-op: with everything cached, collect_requests returns nothing
    cache = {TR.text_key(r["text"], "en"): "x" for r in TR.collect_requests(canon, "en", {})}
    ck(TR.collect_requests(canon, "en", cache) == [], "collect_requests is empty when all cached")

    # --- RESUME-SAFETY GUARD: a value that already EQUALS a cached translation (a resumed
    # run whose on-disk canonical is already baked) must not be re-flagged as uncached, even
    # though its SOURCE-keyed cache lookup misses (the cache is keyed on the Spanish source
    # text, not the already-baked English value now sitting in the field). ---------------
    cache_rg = {TR.text_key("En construcción", "en"): "Under construction"}
    canon_rg = {"properties": [{"id": 5, "status": "Under construction"}]}
    ck(TR.collect_requests(canon_rg, "en", cache_rg) == [],
       "collect_requests resume-guard: a value already equal to a cached translation is not re-flagged")

    # --- run_stage round-trip (offline, no LLM): exit-12 request -> bake -> idempotent ----
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        canonical = work / "canonical.json"
        ledger = work / "source_ledger.csv"
        spanish = "Nave industrial con acceso directo a la autopista principal"
        english = "Industrial warehouse with direct access to the main highway"
        canonical.write_text(json.dumps({"properties": [{"id": 7, "description": spanish}]},
                                         ensure_ascii=False), encoding="utf-8")

        rc1 = TR.run_stage(work, canonical, ledger, "English")
        ck(rc1 == 12, "run_stage returns 12 when a translation round is needed")
        req_path = work / "i18n" / "data_translate_request.json"
        req = json.loads(req_path.read_text(encoding="utf-8")) if req_path.exists() else {}
        item_texts = {it.get("text") for it in req.get("items", [])}
        ck(spanish in item_texts,
           "run_stage writes data_translate_request.json containing the source text")

        # supply the cache in the DOCUMENTED raw {source_text: translation} handoff shape (NOT the
        # internal hash key) - this is exactly what the exit-12 sub-agent writes; run_stage rekeys it.
        (work / "i18n" / "data_translations.en.json").write_text(
            json.dumps({spanish: english}, ensure_ascii=False), encoding="utf-8")
        ledger_header = ("property_id,record_type,field,value,source_file,source_locator,"
                          "source_type,extractor,confidence,conflict_note,verified\n")
        ledger.write_text(ledger_header, encoding="utf-8")

        rc2 = TR.run_stage(work, canonical, ledger, "English")
        ck(rc2 is None, "run_stage returns None once the translation is cached")
        canon2 = json.loads(canonical.read_text(encoding="utf-8"))
        ck(canon2["properties"][0]["description"] == english,
           "run_stage bakes the cached translation into canonical")
        ledger_lines_1 = ledger.read_text(encoding="utf-8").splitlines()
        ck(len(ledger_lines_1) == 2 and "(translation)" in ledger_lines_1[1],
           "run_stage appends a (translation) row to source_ledger.csv, matching merge's header")

        rc3 = TR.run_stage(work, canonical, ledger, "English")
        ck(rc3 is None, "run_stage is idempotent on a third call")
        canon3 = json.loads(canonical.read_text(encoding="utf-8"))
        ledger_lines_2 = ledger.read_text(encoding="utf-8").splitlines()
        ck(canon3 == canon2 and ledger_lines_2 == ledger_lines_1,
           "a third run_stage call makes no further canonical/ledger change (resume-safe)")

    # --- PER-LANGUAGE CACHE (backlog cleanup): the on-disk cache is language-TAGGED
    # (data_translations.<code>.json), so two languages built in ONE work dir keep separate caches
    # and never cross-contaminate (the old untagged data_translations.en.json reused a German
    # translation for a French rebuild of the same work dir). -------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "i18n").mkdir(parents=True, exist_ok=True)
        canonical = work / "canonical.json"
        ledger = work / "source_ledger.csv"
        ledger.write_text("property_id,record_type,field,value,source_file,source_locator,"
                          "source_type,extractor,confidence,conflict_note,verified\n", encoding="utf-8")
        src = "Nave logística en venta con acceso directo a la autopista"
        # a GERMAN-tagged cache is present; there is NO French cache
        (work / "i18n" / "data_translations.de.json").write_text(
            json.dumps({src: "Logistikhalle zu verkaufen mit direktem Autobahnzugang"},
                       ensure_ascii=False), encoding="utf-8")
        # (1) the DE build bakes from the German-tagged cache
        canonical.write_text(json.dumps({"properties": [{"id": 1, "description": src}]},
                                        ensure_ascii=False), encoding="utf-8")
        ck(TR.run_stage(work, canonical, ledger, "de") is None,
           "per-lang: run_stage(de) bakes from data_translations.de.json")
        ck(json.loads(canonical.read_text(encoding="utf-8"))["properties"][0]["description"]
           == "Logistikhalle zu verkaufen mit direktem Autobahnzugang",
           "per-lang: the DE build uses the German-tagged cache")
        # (2) a FR build in the SAME work dir must NOT reuse the German translation
        canonical.write_text(json.dumps({"properties": [{"id": 1, "description": src}]},
                                        ensure_ascii=False), encoding="utf-8")
        ck(TR.run_stage(work, canonical, ledger, "fr") == 12,
           "per-lang: run_stage(fr) requests a NEW round (no French cache reused)")
        ck(json.loads(canonical.read_text(encoding="utf-8"))["properties"][0]["description"] == src,
           "per-lang: the FR build leaves the source untranslated (no cross-language contamination)")

    # malformed externally-produced cache degrades gracefully (never crashes the run)
    ck(TR._load_cache(Path("/no/such/file.json")) == {}, "_load_cache: missing file -> {}")
    with tempfile.TemporaryDirectory() as td:
        arr = Path(td) / "arr.json"; arr.write_text("[1,2,3]", encoding="utf-8")
        ck(TR._load_cache(arr) == {}, "_load_cache: a JSON array -> {} (not a dict)")
        bad = Path(td) / "bad.json"; bad.write_text("{ not json", encoding="utf-8")
        ck(TR._load_cache(bad) == {}, "_load_cache: corrupt JSON -> {}")
    # a dict cache carrying a non-string value must not crash collect_requests (unhashable set)
    try:
        _ = TR.collect_requests(canon, "en", {"k": ["oops", "list"], TR.text_key("x", "en"): "y"})
        ck(True, "collect_requests tolerates a non-string cache value (no crash)")
    except Exception as e:
        ck(False, f"collect_requests crashed on a non-string cache value: {e}")

    # --- gate_runner cmd_translation: mechanical pre-build gate over the built canonical ---
    import gate_runner as G, types, io, contextlib

    def _tgate(work, canonical_path, lang="English"):
        ns = types.SimpleNamespace(canonical=str(canonical_path), work=str(work), lang=lang)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = G.cmd_translation(ns)
        return rc

    with tempfile.TemporaryDirectory() as td:
        w = Path(td); (w / "i18n").mkdir()
        cpath = w / "canonical.json"
        # (a) unprocessed: a Spanish description, EMPTY cache -> collect_requests non-empty -> BLOCK
        cpath.write_text(json.dumps({"properties": [
            {"id": 1, "description": "Plataforma logística en construcción", "developer": "7R"}]}),
            encoding="utf-8")
        (w / "i18n" / "data_translations.en.json").write_text("{}", encoding="utf-8")
        ck(_tgate(w, cpath, "English") != 0, "translation gate BLOCKS an unprocessed eligible field")
        # (b) processed: same source now cached (RAW {source: translation} handoff) -> gate PASS
        (w / "i18n" / "data_translations.en.json").write_text(
            json.dumps({"Plataforma logística en construcción": "Logistics platform"},
                       ensure_ascii=False), encoding="utf-8")
        ck(_tgate(w, cpath, "English") == 0, "translation gate PASSES when every eligible field is cached")
        # (c) request named a non-eligible field -> BLOCK
        (w / "i18n" / "data_translate_request.json").write_text(json.dumps({
            "target_code": "en", "items": [{"property_id": 1, "field": "developer", "text": "7R"}]}),
            encoding="utf-8")
        ck(_tgate(w, cpath, "English") != 0, "translation gate BLOCKS a request naming a non-eligible field")

    # DECLINE: a data_translate.SKIP makes run_stage a no-op (never exit 12) and the gate PASS,
    # so an offline/non-agentic run ships the data untranslated instead of stalling on exit 12.
    with tempfile.TemporaryDirectory() as td:
        w = Path(td); (w / "i18n").mkdir()
        cpath = w / "canonical.json"
        cpath.write_text(json.dumps({"properties": [
            {"id": 1, "description": "Plataforma logística en construcción"}]}), encoding="utf-8")
        (w / "i18n" / "data_translate.SKIP").write_text("", encoding="utf-8")
        ck(TR.run_stage(w, cpath, w / "source_ledger.csv", "English") is None,
           "run_stage: a data_translate.SKIP -> no exit 12 (ship untranslated)")
        ck(_tgate(w, cpath, "English") == 0, "translation gate PASSES when translation is declined (.SKIP)")

    if fails:
        print(f"\nTRANSLATE TEST: FAIL ({len(fails)})"); return 1
    print("\nTRANSLATE TEST: PASS"); return 0

if __name__ == "__main__":
    sys.exit(main())
