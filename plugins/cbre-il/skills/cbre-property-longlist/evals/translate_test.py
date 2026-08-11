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

    # --- P1-7: the ledger writer RECONCILES its own rows instead of appending -------------------
    # The old writer opened the ledger in append mode, so a row shape fixed in CODE could not
    # replace the malformed rows an older build had already written: `ledger validate` blocked at
    # exit 6 and the only escape was hand-deleting canonical.json + source_ledger.csv. The subtle
    # half is the CALL SITE: the stale rows only exist on a pass where merge is resume-SKIPPED and
    # canonical is already baked, so `bake` returns [] - exactly when the old `if rows:` guard
    # meant the writer never ran at all.
    import csv as _csv
    import io as _io
    from contextlib import redirect_stdout as _rso

    import ledger as LG

    _HDR = ("property_id,record_type,field,value,source_file,source_locator,"
            "source_type,extractor,confidence,conflict_note,verified\n")

    def call_validate(p: Path) -> int:
        """`ledger.py validate` through its real CLI; returns the exit code."""
        saved = sys.argv
        sys.argv = ["ledger", "validate", str(p)]
        try:
            with _rso(_io.StringIO()):
                LG.main()
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        except Exception:
            return 1
        finally:
            sys.argv = saved

    def _seed(work: Path, desc: str, cache: dict, extra_rows: str = "") -> tuple[Path, Path]:
        # `description` must be the ONLY translatable field: any other eligible value that is not
        # in the cache (e.g. `status`) makes run_stage correctly return 12 instead of reconciling.
        (work / "i18n").mkdir(parents=True, exist_ok=True)
        canonical = work / "canonical.json"
        ledger = work / "source_ledger.csv"
        canonical.write_text(json.dumps({"meta": {}, "properties": [
            {"id": 7, "developer": "D", "clearHeight": "12 m", "description": desc}]}),
            encoding="utf-8")
        (work / "i18n" / "data_translations.en.json").write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        ledger.write_text(
            _HDR + '7,property,description,Una nave,deck.pdf,page 3,pdf,X-pdf,,,\n' + extra_rows,
            encoding="utf-8")
        return canonical, ledger

    def _trows(p: Path) -> list[dict]:
        with open(p, newline="", encoding="utf-8") as fh:
            return [r for r in _csv.DictReader(fh) if r.get("extractor") == "T-translate"]

    spanish, english = "Una nave logistica moderna", "A modern logistics warehouse"

    # (a) THE OPERATOR'S CASE: canonical ALREADY baked, so bake returns [] - a malformed row from
    #     an older build must still be healed.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        canonical, ledger = _seed(
            work, english, {spanish: english},
            # an OLD-SHAPE T-translate row: source_type EMPTY (the shipped bug)
            f'7,property,description,{english},(translation),translated -> English,'
            f',T-translate,,,\n')
        ck(call_validate(ledger) != 0,
           "P1-7 (a): the seeded malformed row BLOCKS ledger validate (the state that shipped)")
        ck(TR.run_stage(work, canonical, ledger, "English") is None,
           "P1-7 (a): run_stage returns None on an already-baked canonical (bake returns [])")
        t = _trows(ledger)
        ck(len(t) == 1, f"P1-7 (a): exactly ONE T-translate row survives the heal (got {len(t)})")
        ck(t and t[0]["source_type"] == "derived",
           "P1-7 (a): the malformed row is REPLACED, source_type now 'derived'")
        ck(t and spanish in t[0]["source_locator"],
           "P1-7 (a): the locator names the verbatim original recovered from the cache")
        ck(t and "reconstructed" in t[0]["source_locator"],
           "P1-7 (a): a cache-recovered original is TAGGED reconstructed, not passed off as recorded")
        with open(ledger, newline="", encoding="utf-8") as fh:
            allr = [r for r in _csv.DictReader(fh)]
        ck(any(r["extractor"] == "X-pdf" for r in allr),
           "P1-7 (a): the merge row is untouched by the reconcile")
        ck(call_validate(ledger) == 0,
           "P1-7 (a): ledger validate ALL-PASS after the heal (was exit 6 forever)")

    # (b) a bake over an UNBAKED canonical REPLACES a pre-existing row, never duplicates it
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        canonical, ledger = _seed(
            work, spanish, {spanish: english},
            f'7,property,description,STALE,(translation),translated -> English,'
            f'derived,T-translate,,,\n')
        ck(TR.run_stage(work, canonical, ledger, "English") is None, "P1-7 (b): run_stage bakes")
        t = _trows(ledger)
        ck(len(t) == 1, f"P1-7 (b): still exactly ONE T-translate row, not two (got {len(t)})")
        ck(t and t[0]["value"] == english, "P1-7 (b): and it carries the NEW translation")

    # (c) F4: the reviewer's own marks survive a reconcile. `verified` is G-trace's judgement;
    #     rewriting it to "" would be Python erasing an LLM verdict inside the audit artefact.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        canonical, ledger = _seed(
            work, english, {spanish: english},
            f'7,property,description,{english},(translation),translated -> English,'
            f'derived,T-translate,,checked by hand,no\n')
        ck(TR.run_stage(work, canonical, ledger, "English") is None, "P1-7 (c): run_stage reconciles")
        t = _trows(ledger)
        ck(t and t[0]["verified"] == "no",
           "P1-7 (c): a hand-marked `verified: no` SURVIVES the reconcile (LLM judgement kept)")
        ck(t and t[0]["conflict_note"] == "checked by hand",
           "P1-7 (c): `conflict_note` survives too")

    # (d) a ledger with NO T-translate rows is untouched in BYTES and MTIME. An mtime bump alone
    #     would re-fire deliver on every invocation via run.py's _deliver_inputs.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "i18n").mkdir(parents=True, exist_ok=True)
        canonical = work / "canonical.json"
        ledger = work / "source_ledger.csv"
        canonical.write_text(json.dumps({"meta": {}, "properties": [
            {"id": 1, "developer": "7R", "clearHeight": "12 m"}]}), encoding="utf-8")
        (work / "i18n" / "data_translations.en.json").write_text("{}", encoding="utf-8")
        # values embedding a comma and a double quote, so ANY re-quoting drift is visible
        ledger.write_text(_HDR
                          + '1,property,clearHeight,"12 m, clear",deck.pdf,page 3,pdf,X-pdf,,,\n'
                          + '1,property,developer,"7R ""Group""",deck.pdf,page 3,pdf,X-pdf,,,\n',
                          encoding="utf-8")
        b0, m0 = ledger.read_bytes(), ledger.stat().st_mtime_ns
        ck(TR.run_stage(work, canonical, ledger, "English") is None, "P1-7 (d): run_stage no-ops")
        ck(ledger.read_bytes() == b0,
           "P1-7 (d): a T-translate-free ledger is byte-identical (no re-quoting drift)")
        ck(ledger.stat().st_mtime_ns == m0,
           "P1-7 (d): and its MTIME is untouched, so `deliver` stays resume-skipped")

    # (e) the writer must NOT read the ledger by splitting text. A raw vertical tab (python-pptx
    #     renders a soft line break as one, and csv.writer does not quote it) would shatter the row.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        canonical, ledger = _seed(
            work, english, {spanish: english},
            '1,property,description,"has a \x0b vertical tab",deck.pdf,page 3,pdf,X-pdf,,,\n'
            f'7,property,description,{english},(translation),translated -> English,'
            f',T-translate,,,\n')
        ck(TR.run_stage(work, canonical, ledger, "English") is None, "P1-7 (e): run_stage reconciles")
        with open(ledger, newline="", encoding="utf-8") as fh:
            raw = [r for r in _csv.reader(fh) if r]
        ragged = [(i, len(r)) for i, r in enumerate(raw) if len(r) != 11]
        ck(not ragged, f"P1-7 (e): a VERTICAL TAB row survives the rewrite intact (ragged: {ragged})")
        ck(b"\x0b" in ledger.read_bytes(),
           "P1-7 (e): and the control character is still there - not silently scrubbed from a "
           "row this writer does not own")
        ck(call_validate(ledger) == 0, "P1-7 (e): ledger validate ALL-PASS afterwards")

    # Source assertions over the AST, NOT raw text: `_write_ledger_rows`'s docstring DISCUSSES
    # splitlines() and append mode at length, so a substring search matches the explanation rather
    # than the code and passes/fails for the wrong reason.
    import ast as _ast
    _tree = _ast.parse((HELPERS / "translate.py").read_text(encoding="utf-8"))
    _calls = [n for n in _ast.walk(_tree) if isinstance(n, _ast.Call)]
    _splits = [n for n in _calls
               if isinstance(n.func, _ast.Attribute) and n.func.attr == "splitlines"]
    ck(not _splits,
       f"P1-7: translate.py makes NO splitlines() CALL (the spec's own draft did - it would "
       f"shatter a vertical-tab row); found {len(_splits)}")
    _opens = [n for n in _calls
              if isinstance(n.func, _ast.Name) and n.func.id == "open"
              and len(n.args) > 1 and isinstance(n.args[1], _ast.Constant)
              and "a" in str(n.args[1].value)]
    ck(not _opens, f"P1-7: no append-mode open() remains; found {len(_opens)}")
    ck(any(isinstance(n.func, _ast.Attribute) and n.func.attr == "reader" for n in _calls),
       "P1-7: the ledger is parsed with csv.reader over the file object")

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
