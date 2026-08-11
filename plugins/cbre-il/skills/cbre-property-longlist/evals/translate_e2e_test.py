#!/usr/bin/env python3
"""translate_e2e_test.py - the exit-12 free-text DATA translation path, END TO END.

WHY THIS EXISTS. The exit-12 path had never run end to end, and it was BROKEN:
`_append_ledger_rows` wrote an EMPTY `source_type`, while `ledger.REQUIRED` demands it - so the
first genuinely non-English build hard-blocked at exit 6 with "36 incomplete rows". It stayed
latent for the whole life of the feature because every ENGLISH run declines the stage via
`i18n/data_translate.SKIP`, and because the appender swallows every exception
(`translate.py` `except Exception: pass`) so it can never fail loudly - only a downstream
`ledger.py validate` sees the damage.

`evals/translate_test.py` did not catch it: it FABRICATES the ledger header by hand and then
asserts only the row's SHAPE (a row of `,,,,` after `(translation)` satisfied every assertion in
it). It never imports `helpers/ledger.py` and never reads a single column VALUE. This suite closes
that loop on a REAL merge output:

    real merge -> collect_requests -> (exit 12) -> raw cache -> bake -> _append_ledger_rows
              -> ledger.py validate + gate_runner translation + gate_runner trace-coverage

WHAT THIS DOES *NOT* PROVE. The cache here is canned (`ES::` + source), so this closes the
MECHANICAL loop only - never translation quality, register, or prose-vs-proper-noun. Those stay
with the exit-12 sub-agent and the blind G-lang / G-i18n rubric, and a LIVE non-English Cowork run
remains the decisive test. run.py's own `if _t_rc == 12` / `_exit_round_trip` plumbing is
`cowork_sim.py`'s job; this suite asserts the exact integer 12 that run.py switches on.

Locks:
  1. `ledger.py validate` ALL-PASS over the APPENDED ledger (the shipped bug: BLOCKED, exit 6)
  2. every `ledger.REQUIRED` column non-empty on every `(translation)` row - read from
     `ledger.REQUIRED` itself, so a future column addition is picked up automatically
  3. `source_type == 'derived'`, and never `'gap'` - a translated field still COUNTS as sourced,
     so `trace-coverage` does not read it as untraceable
  4. G-translation BLOCKS an unfulfilled round and ALL-PASSes after the bake
  5. a third pass duplicates nothing, strands nothing, and is byte-identical
  6. NEGATIVE: a doctored empty `source_type` still BLOCKS - the meta-assertion that this suite
     can actually SEE the defect, so it cannot silently become a no-op
  7. CSV INTEGRITY on adversarial prose: the fixture description carries a VERTICAL TAB, a comma
     and a double quote, all inside the 60-char `_short` window. Every ledger row must still have
     exactly one field per header column. `csv.writer` does not quote `\\x0b` under
     `lineterminator="\\n"`, and `str.splitlines()` SPLITS on it - so rewriting the ledger via
     `splitlines()` shatters such a row into a short fragment that, having no `extractor` column,
     the translation writer can never recognise or remove, blocking `ledger validate` at exit 6
     forever. python-pptx renders a soft line break as exactly this character, so it is a live
     carrier, not a hypothetical. P1-7 hardened `translate._short` to collapse whitespace, so THIS
     writer no longer emits one - but `merge._short` is unchanged, so merge's own row still does.
     Measured on this fixture: `splitlines()` sees 87 rows where file iteration sees 86. The suite
     asserts that DISAGREEMENT, so if it ever vanishes the loss of coverage is visible rather than
     silent.

Offline: no network, no LLM, no PDF engine, no HTML build (so the byte-frozen template is never
touched). The fixture is JSON records only and `--source-dir` is an empty dir.
Run: python evals/translate_e2e_test.py"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))

import _common as C          # noqa: E402
import gate_runner           # noqa: E402
import i18n as I18N          # noqa: E402
import ledger as L           # noqa: E402
import merge                 # noqa: E402
import translate as TR       # noqa: E402

# evals/extract_test.py sets CBRE_LONGLIST_SKIP_DATA_TRANSLATE=1 process-wide. This suite EXISTS
# to drive that stage, and a declined run_stage returns None while the gate reports ALL-PASS - so
# under a future single-process battery runner every assertion below would silently no-op GREEN.
os.environ.pop(TR.SKIP_ENV, None)

FAILS: list[str] = []
LANG = "Spanish"

# A vertical tab, a comma and a double quote, ALL inside the first 60 characters, because
# translate._short truncates at 60 - outside that window the trap is silently disarmed. The
# arming assertion below proves they actually reached the ledger value.
ADVERSARIAL = ('Cross-dock unit, "Building A", with a mezzanine\x0boffice block, dock levellers '
               'and a fully fitted two-storey office to the rear of the plot')

PROSE = {
    "description": ADVERSARIAL,
    "permitting": "Building permit granted and valid for the whole plot",
    "leaseTerm": "Five years firm with a five year extension option",
    "incentives": "Rent free period negotiable subject to lease length",
}


def check(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def call(module, *cmd, quiet=True) -> int:
    """Run a helper main() in-process (the fixture_test/run.py pattern); return its exit code."""
    saved = sys.argv
    sys.argv = [getattr(module, "__name__", "helper"), *[str(c) for c in cmd]]
    buf = io.StringIO()
    try:
        if quiet:
            with redirect_stdout(buf):
                module.main()
        else:
            module.main()
        rc = 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:
        print(f"    (crash: {type(e).__name__}: {e})")
        rc = 1
    finally:
        sys.argv = saved
    return rc


def records(work: Path) -> Path:
    """Plain JSON records driven through the REAL merge - never a hand-written canonical.

    Fixture filenames are DELIBERATELY unique to this suite: merge._SRC_RESOLVE memoises source
    paths by BARE FILENAME for the whole process (reference/memory.md), so sharing
    fixture_test's "Brochure A.pdf" can serve a stale deleted-temp-dir path.
    """
    prov = {k: "page 3" for k in
            ("park", "developer", "city", "country", "status", "warehouseArea", *PROSE)}
    rec = [{
        "park": "Alpha Park", "developer": "CTP", "city": "Pilsen", "country": "CZ",
        "status": "Existing", "warehouseArea": 40000, **PROSE,
        "__meta": {"source_file": "translate_e2e_deck.pdf", "source_type": "pdf",
                   "locator_base": "page 3", "prov": prov},
    }, {
        "park": "Beta Park", "developer": "Panattoni", "city": "Brno", "country": "CZ",
        "status": "Existing", "warehouseArea": 25000,
        "description": "Speculative unit under construction on a serviced plot next to the "
                       "existing distribution park",
        "__meta": {"source_file": "translate_e2e_tracker.xlsx", "source_type": "xlsx",
                   "locator_base": "Sheet1!r4",
                   "prov": {"park": "Sheet1!r4", "developer": "Sheet1!r4", "city": "Sheet1!r4",
                            "country": "Sheet1!r4", "status": "Sheet1!r4",
                            "warehouseArea": "Sheet1!r4", "description": "Sheet1!r4"}},
    }]
    f = work / "translate_e2e_records.json"
    f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return f


def rows_of(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def raw_rows(p: Path) -> tuple[list[str], list[list[str]]]:
    """Header + every data row as raw field lists, so a SHATTERED row is visible as a wrong
    field count. csv.reader over the FILE OBJECT splits on \\n / \\r\\n only - never on \\x0b."""
    with open(p, newline="", encoding="utf-8") as fh:
        all_rows = [r for r in csv.reader(fh) if r]
    return all_rows[0], all_rows[1:]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    work = Path(tempfile.mkdtemp(prefix="cbre_translate_e2e_"))
    src = work / "inputs"
    src.mkdir()
    canonical = work / "canonical.json"
    ledger_csv = work / "source_ledger.csv"
    code = I18N.normalize_lang(LANG)
    cache_f = work / "i18n" / f"data_translations.{code}.json"

    print(f"Real merge (English prose, output.language={LANG}/{code}):")
    rc = call(merge, "--records", records(work), "--source-dir", src,
              "--out", canonical, "--ledger", ledger_csv, "--language", LANG)
    check(rc == 0, "merge completes and writes canonical + source_ledger.csv")
    check(call(L, "validate", ledger_csv) == 0,
          "baseline: ledger validate ALL-PASS before translation")
    check(call(gate_runner, "trace-coverage", canonical, "--ledger", ledger_csv) == 0,
          "baseline: trace-coverage ALL-PASS before translation")
    base_rows = len(rows_of(ledger_csv))
    _c0 = json.loads(canonical.read_text(encoding="utf-8"))
    _d0 = str((_c0.get("properties") or [{}])[0].get("description", ""))
    check("\x0b" in _d0 and "," in _d0 and '"' in _d0,
          "ARMED: the merged canonical description carries a vertical tab, a comma and a quote")

    print("Round 1 - run_stage must ask for a translation round (run.py's exit 12):")
    rc1 = TR.run_stage(work, canonical, ledger_csv, LANG, quiet=True)
    check(rc1 == 12, f"run_stage returns exactly 12 (run.py switches on it), got {rc1!r}")
    req_p = work / "i18n" / "data_translate_request.json"
    req = json.loads(req_p.read_text(encoding="utf-8")) if req_p.exists() else {}
    items = req.get("items") or []
    check(bool(items) and req.get("target_code") == code,
          f"request names target_code {code!r} and {len(items)} item(s)")
    check(all(C.is_translatable_value(it["field"], it["text"]) for it in items),
          "every requested item is an ELIGIBLE free-text field")
    check(call(gate_runner, "translation", canonical, "--work", work, "--lang", LANG) != 0,
          "G-translation BLOCKS while the round is unfulfilled (live on a real canonical)")

    print("Round 2 - the sub-agent's RAW {source: translation} cache -> bake:")
    cache_f.parent.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps({it["text"]: "ES::" + it["text"] for it in items},
                                  ensure_ascii=False), encoding="utf-8")
    rc2 = TR.run_stage(work, canonical, ledger_csv, LANG, quiet=True)
    check(rc2 is None, f"run_stage returns None once the cache is present, got {rc2!r}")
    canon = json.loads(canonical.read_text(encoding="utf-8"))
    baked = [p for p in canon["properties"] if str(p.get("description", "")).startswith("ES::")]
    check(len(baked) == len(canon["properties"]), "every property's description is baked")

    print("THE REGRESSION - the appended ledger rows must be COMPLETE:")
    rows = rows_of(ledger_csv)
    trows = [r for r in rows if r.get("source_file") == "(translation)"]
    check(len(trows) == len(items),
          f"one (translation) row per baked field ({len(items)}, got {len(trows)})")
    incomplete = [[c for c in L.REQUIRED if not str(r.get(c, "")).strip()]
                  for r in trows if any(not str(r.get(c, "")).strip() for c in L.REQUIRED)]
    check(not incomplete,
          f"every ledger.REQUIRED column non-empty on every (translation) row "
          f"(missing: {ascii(incomplete[:3])})")
    check(all(r.get("source_type") == "derived" for r in trows),
          "source_type == 'derived' on every (translation) row (translate.py's literal)")
    check(all((r.get("source_type") or "") != "gap" for r in trows),
          "source_type != 'gap' - the INVARIANT: a translated field still counts as sourced")
    check(call(L, "validate", ledger_csv) == 0,
          "ledger validate ALL-PASS over the BAKED ledger (was: BLOCKED, missing [source_type])")
    check(call(gate_runner, "trace-coverage", canonical, "--ledger", ledger_csv) == 0,
          "trace-coverage ALL-PASS over the baked canonical")
    check(call(gate_runner, "translation", canonical, "--work", work, "--lang", LANG) == 0,
          "G-translation ALL-PASS after the bake (run.py's g1 gate)")

    print("CSV INTEGRITY on adversarial prose (the P1-7 trap):")
    header, data = raw_rows(ledger_csv)
    ragged = [(i, len(r)) for i, r in enumerate(data) if len(r) != len(header)]
    check(not ragged,
          f"every ledger row has exactly {len(header)} fields - no row shattered by a control "
          f"character (ragged: {ragged[:3]})")
    # ARMING, at the READ end - the half that matters. P1-7 hardened translate._short to collapse
    # whitespace, so T-translate rows no longer carry the VT; but merge._short is UNCHANGED, so
    # MERGE's own row for this description still puts a raw \x0b in the file. That is what keeps
    # the reader choice load-bearing: measured on this very fixture, str.splitlines() sees 87 rows
    # where file iteration sees 86. If both numbers ever agree, this suite has stopped testing the
    # corruption class and the ragged-row check above is decoration - so assert the DISAGREEMENT.
    _raw = ledger_csv.read_bytes()
    _txt = ledger_csv.read_text(encoding="utf-8")
    check(_raw.count(b"\x0b") > 0,
          "ARMED: a raw vertical tab is present in the ledger file (via merge's own row)")
    check(len(_txt.splitlines()) != len(data) + 1,
          f"str.splitlines() DISAGREES with file iteration ({len(_txt.splitlines())} vs "
          f"{len(data) + 1}) - so reading the ledger by splitting text WOULD shatter a row, and "
          f"translate._write_ledger_rows must keep iterating the file object")
    check(not any("\x0b" in str(r.get("value", "")) for r in trows),
          "translate._short collapses whitespace, so THIS writer never emits a control character")
    check(any("," in str(r.get("value", "")) for r in trows)
          and any('"' in str(r.get("value", "")) for r in trows),
          "a comma and a double quote round-trip through csv quoting intact")

    print("IDEMPOTENCE - a third pass must not duplicate or strand a row:")
    before_ledger = ledger_csv.read_bytes()
    before_canon = canonical.read_bytes()
    rc3 = TR.run_stage(work, canonical, ledger_csv, LANG, quiet=True)
    check(rc3 is None, f"a third run_stage returns None (no new exit-12 round), got {rc3!r}")
    check(ledger_csv.read_bytes() == before_ledger,
          "the ledger is byte-identical after the third pass")
    check(canonical.read_bytes() == before_canon, "canonical is byte-identical after the third pass")
    keys = [(r["property_id"], r["field"]) for r in rows_of(ledger_csv)
            if r.get("source_file") == "(translation)"]
    check(len(keys) == len(set(keys)), f"no duplicate (property_id, field) translation row")
    canon2 = json.loads(canonical.read_text(encoding="utf-8"))
    byid = {str(p.get("id")): p for p in canon2["properties"]}
    stranded = [(r["property_id"], r["field"]) for r in rows_of(ledger_csv)
                if r.get("source_file") == "(translation)"
                and r.get("value") != TR._short(byid.get(str(r["property_id"]), {}).get(r["field"]))]
    check(not stranded, f"no STRANDED translation row (value matches the canonical) "
                        f"{ascii(stranded[:3])}")
    check(len(rows_of(ledger_csv)) == base_rows + len(items),
          "the ledger grew by exactly the baked-field count")

    print("NEGATIVE - the detector bites: an empty source_type must BLOCK:")
    doctored = work / "ledger_empty_source_type.csv"
    txt = ledger_csv.read_text(encoding="utf-8")
    doctored.write_text(txt.replace(",derived,T-translate,", ",,T-translate,"), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_neg = call(L, "validate", doctored, quiet=False)
    check(rc_neg != 0 and "source_type" in buf.getvalue(),
          "ledger validate BLOCKS a (translation) row with an EMPTY source_type (the shipped bug)")

    print("SKIP - the offline decline still short-circuits the whole path:")
    sk = Path(tempfile.mkdtemp(prefix="cbre_translate_skip_"))
    (sk / "i18n").mkdir()
    (sk / "i18n" / "data_translate.SKIP").write_text("", encoding="utf-8")
    sk_canon = sk / "canonical.json"
    sk_canon.write_text(json.dumps({"meta": {}, "properties": [
        {"id": 1, "park": "P", "developer": "D", "city": "X", "country": "CZ",
         "status": "Existing", "description": PROSE["permitting"]}]}), encoding="utf-8")
    check(TR.run_stage(sk, sk_canon, sk / "source_ledger.csv", LANG, quiet=True) is None,
          "a data_translate.SKIP -> no exit 12 and no bake")
    check(call(gate_runner, "translation", sk_canon, "--work", sk, "--lang", LANG) == 0,
          "G-translation PASSES on an acknowledged decline")

    if FAILS:
        print(f"\nTRANSLATE E2E TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nTRANSLATE E2E TEST: PASS (exit-12 bake -> ledger.REQUIRED -> G-translation, "
          "idempotent, CSV-integrity trap armed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
