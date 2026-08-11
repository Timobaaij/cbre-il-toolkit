#!/usr/bin/env python3
"""overrides_test.py - P1-4: DURABLE manual corrections (work/overrides.json).

THE BUG. The only sanctioned remedy for a flagged datum was "edit the records in work/extract/".
Those files are DERIVED: anything that invalidates extraction regenerates them and silently
discards the correction. Live symptom - a corrected tracker cell reverted TWICE, two properties
stopped clustering, the property count went 12 -> 13 with NO message at all, and the only visible
effect was a coverage gate failing on a thin record several steps later.

THE TEST THAT MATTERS is the first one: apply a correction, then overwrite the records file with
its ORIGINAL broken bytes (exactly what a re-extraction does) and assert the correction is STILL
there. Everything else guards the ways this mechanism could become dangerous.

WHAT IS DELIBERATELY NOT TESTED, because it must not exist: any Python that decides whether a
correction is right, or that guesses a target. Zero matches and ambiguous matches apply NOTHING and
report; Python only verifies the target exists (0/1/N) and prepares the evidence.

Locks:
  1. a correction SURVIVES a simulated re-extraction, and work/extract still holds the broken value
  2. a stale / ambiguous / superseded / invalid entry applies NOTHING and is surfaced in all three
     places (merge stdout, overrides_report.json, canonical.meta.overrides -> the Gaps Report)
  3. the `override` ledger row satisfies ledger.REQUIRED and keeps trace-coverage green - the
     precise trap the translation bake fell into (an empty source_type hard-blocked a live build),
     so it is proven against `ledger.py validate`, never eyeballed
  4. it can NEVER fabricate: no new record, no new field, no structural key, no dict/list, no empty
     value - and areaUnit/rentUnit are DENIED outright (the 10.76x class)
  5. the PRECEDENCE PIN: a correction on a record that LOSES the precedence contest still wins, and
     an LLM --field-decisions pick cannot un-pick it. Without this the override is a silent no-op
     that looks exactly like the bug it was meant to fix
  6. a corrected city RE-CLUSTERS (the live 12 -> 13 symptom) because overrides are applied before
     match.dedupe
  7. an overrides-FREE run is byte-identical to today (meta.overrides is conditional)

Offline, no network, no PDF engine. Run: python evals/overrides_test.py"""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import deliver as DEL      # noqa: E402
import gate_runner as GR   # noqa: E402
import ledger as LG        # noqa: E402
import merge as M          # noqa: E402

FAILS: list[str] = []


def check(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def call(module, *cmd) -> tuple[int, str]:
    saved = sys.argv
    sys.argv = [getattr(module, "__name__", "h"), *[str(c) for c in cmd]]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            module.main()
        return 0, buf.getvalue()
    except SystemExit as e:
        return (e.code if isinstance(e.code, int) else 0), buf.getvalue()
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}\n{buf.getvalue()}"
    finally:
        sys.argv = saved


def tracker_records(city_r3="Northamptonshire") -> list:
    """Two xlsx-shaped rows. r3's city holds a COUNTY where the city belongs - the live defect
    shape, and the thing that stops it clustering with the deck record in lock 6."""
    def rec(row, park, city, area):
        return {"park": park, "city": city, "country": "United Kingdom", "developer": "GLP",
                "warehouseArea": area, "areaUnit": "sq ft", "status": "Existing",
                "__meta": {"source_file": "tracker.xlsx", "source_type": "xlsx",
                           "locator_base": "Longlist", "tracker_rich": True,
                           "prov": {k: f"Longlist!r{row}" for k in
                                    ("park", "city", "country", "developer", "warehouseArea",
                                     "status")}}}
    return [rec(2, "Alpha Park", "Swindon", 250000),
            rec(3, "Magna Park", city_r3, 498723)]


def ov(**kw) -> dict:
    base = {"id": "ov-001",
            "where": {"source_file": "tracker.xlsx", "sheet": "Longlist", "row": 3},
            "set": {"city": "Corby"}, "why": "the county sat in the city column"}
    base.update(kw)
    return base


def build(td: Path, records: list, overrides: list | None, name="records.json"):
    """Run the REAL merge over `records` (+ optional overrides). Returns (rc, out, canonical, ledger)."""
    rf = td / name
    rf.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    src = td / "inputs"
    src.mkdir(exist_ok=True)
    canon, led = td / "canonical.json", td / "source_ledger.csv"
    args = ["--records", rf, "--source-dir", src, "--out", canon, "--ledger", led]
    if overrides is not None:
        of = td / "overrides.json"
        of.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
        args += ["--overrides", of]
    rc, out = call(M, *args)
    return rc, out, canon, led


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("THE LIVE DEFECT - a correction must SURVIVE re-extraction:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, tracker_records(), [ov()])
        check(rc == 0, "merge accepts --overrides and completes")
        d1 = json.loads(canon.read_text(encoding="utf-8"))
        cities1 = sorted(str(p.get("city")) for p in d1["properties"])
        n1 = len(d1["properties"])
        check("Corby" in cities1, f"the correction is applied (cities={cities1})")
        check("[OVERRIDE] ov-001" in out, "and reported on merge's stdout")
        # NOW simulate a re-extraction: rewrite the records file with the ORIGINAL broken bytes
        rc2, out2, canon2, led2 = build(td, tracker_records(), [ov()])
        d2 = json.loads(canon2.read_text(encoding="utf-8"))
        check(rc2 == 0 and "Corby" in [str(p.get("city")) for p in d2["properties"]],
              "STILL corrected after the records file is regenerated (the live bug is fixed)")
        check(len(d2["properties"]) == n1,
              f"and the property COUNT is unchanged ({n1}) - no silent 12 -> 13")
        raw = json.loads((td / "records.json").read_text(encoding="utf-8"))
        check(any(r.get("city") == "Northamptonshire" for r in raw),
              "the DERIVED extract still holds the BROKEN value - it was never written back")

    print("\nZERO / MANY / SUPERSEDED apply NOTHING and are surfaced in all three places:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        _, base_out, base_canon, _ = build(td, tracker_records(), None)
        base_props = json.loads(base_canon.read_text(encoding="utf-8"))["properties"]
    for tag, entry, needle in (
            ("stale", ov(where={"source_file": "tracker.xlsx", "sheet": "Longlist", "row": 99}),
             "matched NOTHING"),
            ("ambiguous", ov(where={"source_file": "tracker.xlsx"}), "matched 2 records"),
            ("superseded", ov(expect={"city": "Somewhere Else"}), "`expect` said")):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            rc, out, canon, led = build(td, tracker_records(), [entry])
            d = json.loads(canon.read_text(encoding="utf-8"))
            rep = json.loads((td / "overrides_report.json").read_text(encoding="utf-8"))
            gaps = DEL.gaps_report(d, "Test", work_dir=td)
            check(rc == 0, f"{tag}: merge still succeeds (never a mid-stage failure)")
            check(f"[{tag.upper()} OVERRIDE]" in out and needle in out,
                  f"{tag}: (a) merge stdout names it")
            check(entry["id"] in [e.get("id") for e in rep.get(tag, [])]
                  and not rep.get("applied"),
                  f"{tag}: (b) overrides_report.json lists it, and NOT under applied")
            check(bool((d.get("meta", {}).get("overrides") or {}).get(tag)),
                  f"{tag}: (c) canonical.meta.overrides carries it")
            check("matched NOTHING (stale" in gaps and entry["id"] in gaps,
                  f"{tag}: and it reaches the Gaps Report")
            check([{k: v for k, v in p.items() if k != "id"} for p in d["properties"]]
                  == [{k: v for k, v in p.items() if k != "id"} for p in base_props],
                  f"{tag}: NO property value changed vs the no-overrides baseline")

    print("\nTHE LEDGER ROW - proven against ledger.py validate, not eyeballed:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, tracker_records(),
                                    [ov(verified_by="timo.baaij@cbre.com")])
        with open(led, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        orows = [r for r in rows if r.get("record_type") == "override"]
        check(len(orows) == 1, f"exactly ONE override row is emitted (got {len(orows)})")
        r0 = orows[0] if orows else {}
        missing = [c for c in LG.REQUIRED if not str(r0.get(c, "")).strip()]
        check(not missing, f"every ledger.REQUIRED column is non-empty (missing: {missing})")
        check(r0.get("source_type") == "override",
              "source_type == 'override' (non-empty, and != 'gap' so it still traces)")
        loc = str(r0.get("source_locator") or "")
        check("ov-001" in loc and "Northamptonshire" in loc and "Corby" in loc
              and "county sat in the city column" in loc,
              "source_locator carries the id, old -> new, and the WHY")
        check(r0.get("verified") == "yes", "verified_by lands in the ledger's verified column")
        check(call(LG, "validate", led)[0] == 0, "`ledger.py validate` ALL-PASS")
        check(call(GR, "trace-coverage", canon, "--ledger", led)[0] == 0,
              "`gate_runner trace-coverage` ALL-PASS (an override never makes a field untraceable)")
        prop_row = next((r for r in rows if r.get("record_type") == "property"
                         and r.get("field") == "city" and "Corby" in str(r.get("value"))), None)
        check(prop_row is not None and "manual override" in str(prop_row.get("source_locator")),
              "the FIELD's own property row shows the correction inline against its locator "
              "(never laundered into a clean-looking extract row)")

    print("\nIT CAN NEVER FABRICATE:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        _, _, bc, _ = build(td, tracker_records(), None)
        n_base = len(json.loads(bc.read_text(encoding="utf-8"))["properties"])
    for label, entry, why in (
            # B7 widened "existing" to canonical UNION fields present on the records, so the reason
            # is now pinned on the FABRICATION claim rather than on the word "canonical".
            # `wormholeDistance` is in no schema and on no record, so it is still refused.
            ("a brand-new field", ov(set={"wormholeDistance": 3}), "would be INVENTING it"),
            ("a structural key", ov(set={"id": 99}), "structural/derived"),
            ("an image key", ov(set={"hero": "data:image/png;base64,AAA"}), "structural/derived"),
            ("a dict value", ov(set={"city": {"a": 1}}), "must be a scalar"),
            ("an empty value", ov(set={"city": "   "}), "write the literal"),
            ("areaUnit (the 10.76x class)", ov(set={"areaUnit": "sq m"}), "DENIED"),
            ("rentUnit", ov(set={"rentUnit": "EUR/sq m/yr"}), "DENIED")):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            rc, out, canon, led = build(td, tracker_records(), [entry])
            d = json.loads(canon.read_text(encoding="utf-8"))
            inv = (d.get("meta", {}).get("overrides") or {}).get("invalid") or []
            bad_key = list(entry["set"])[0]
            leaked = [p for p in d["properties"]
                      if bad_key not in ("id", "city", "areaUnit", "rentUnit", "hero")
                      and bad_key in p]
            check(rc == 0 and any(why in str(x) for x in inv),
                  f"{label} -> INVALID, reason names why ({why!r})")
            check(not leaked, f"{label}: the key never reaches a canonical property")
            check(len(d["properties"]) == n_base,
                  f"{label}: the property count is unchanged (no record was created)")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, _ = build(td, tracker_records(),
                                  [ov(id="ov-bad", set={"wormholeDistance": 1}),
                                   ov(id="ov-good", set={"city": "Corby"})])
        d = json.loads(canon.read_text(encoding="utf-8"))
        check(rc == 0 and "Corby" in [str(p.get("city")) for p in d["properties"]],
              "an INVALID entry does not abort the run - the other valid override still applies")
    # a zero-match override cannot create a record - asserted on the applier DIRECTLY as well as
    # end-to-end, since "no append/insert/extend anywhere in the code path" is the real invariant
    with tempfile.TemporaryDirectory() as t:
        of = Path(t) / "overrides.json"
        of.write_text(json.dumps([ov(where={"source_file": "nope.xlsx"})]), encoding="utf-8")
        loaded, errs = M.load_overrides(of)
        check(len(loaded) == 1 and not errs, "load_overrides accepts a well-formed entry")
        recs = tracker_records()
        rep = M.apply_overrides(recs, loaded)
        check(len(recs) == 2 and rep["stale"] and not rep["applied"],
              "apply_overrides never appends a record on a zero match (len unchanged)")

    print("\nTHE PRECEDENCE PIN - a correction must not be silently out-voted:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        # A brochure record for the SAME property. For a spec field the brochure normally WINS
        # over the tracker, so without the pin the corrected tracker value would be discarded.
        deck = {"park": "Magna Park", "city": "Corby", "country": "United Kingdom",
                "developer": "GLP", "clearHeight": "12 m", "status": "Existing",
                "__meta": {"source_file": "deck.pdf", "source_type": "pdf",
                           "locator_base": "page 2", "page_no": 1,
                           "prov": {"park": "page 2", "city": "page 2", "clearHeight": "page 2"}}}
        tr = tracker_records("Corby")
        tr[1]["clearHeight"] = "10 m"
        rc, out, canon, led = build(td, tr + [deck],
                                    [ov(id="ov-ch", set={"clearHeight": "15 m"},
                                        why="corrected from the signed spec sheet")])
        d = json.loads(canon.read_text(encoding="utf-8"))
        magna = next((p for p in d["properties"] if p.get("park") == "Magna Park"), {})
        check(magna.get("clearHeight") == "15 m",
              f"the override WINS over the brochure's value (got {magna.get('clearHeight')!r})")
        # meta.conflicts is a LIST of conflict lines (not a dict) - the discarded value must appear
        # in it, so the override's displacement of the brochure is audited rather than silent.
        _conf = json.dumps(d.get("meta", {}).get("conflicts") or [], ensure_ascii=False)
        with open(led, newline="", encoding="utf-8") as fh:
            _notes = " | ".join(str(r.get("conflict_note") or "") for r in csv.DictReader(fh))
        check("12 m" in _conf or "12 m" in _notes,
              "and the displaced brochure value is recorded as a conflict, never silently dropped")
    src_m = (HELPERS / "merge.py").read_text(encoding="utf-8")
    check("and not _locked" in src_m,
          "an LLM --field-decisions pick cannot un-pick a human correction (`not _locked` guard)")

    print("\nRE-CLUSTERING - the live 12 -> 13 symptom:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        deck = {"park": "Magna Park", "city": "Corby", "country": "United Kingdom",
                "developer": "GLP", "status": "Existing", "warehouseArea": 498723,
                "areaUnit": "sq ft",
                "__meta": {"source_file": "deck.pdf", "source_type": "pdf",
                           "locator_base": "page 2", "page_no": 1,
                           "prov": {"park": "page 2", "city": "page 2"}}}
        rc_b, _, cb, _ = build(td, tracker_records() + [deck], None, name="r_before.json")
        n_before = len(json.loads(cb.read_text(encoding="utf-8"))["properties"])
        rc_a, _, ca, _ = build(td, tracker_records() + [deck], [ov()], name="r_after.json")
        n_after = len(json.loads(ca.read_text(encoding="utf-8"))["properties"])
        check(n_before == 3 and n_after == 2,
              f"correcting the city RE-JOINS the cluster: {n_before} -> {n_after} properties")
        after = json.loads(ca.read_text(encoding="utf-8"))
        magna = next((p for p in after["properties"] if p.get("park") == "Magna Park"), {})
        files = json.dumps(after.get("meta", {}).get("sourceFiles") or [])
        check("tracker.xlsx" in files and "deck.pdf" in files,
              "and the surviving cluster carries both source files")

    print("\nAn overrides-FREE run must be byte-identical to today:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        _, _, c_none, l_none = build(td, tracker_records(), None, name="a.json")
        b_canon, b_led = c_none.read_bytes(), l_none.read_bytes()
        _, _, c_empty, l_empty = build(td, tracker_records(), [], name="b.json")
        check(c_empty.read_bytes() == b_canon and l_empty.read_bytes() == b_led,
              "an EMPTY overrides list produces identical canonical + ledger bytes")
        d = json.loads(c_empty.read_text(encoding="utf-8"))
        check("overrides" not in (d.get("meta") or {}),
              "meta.overrides is absent (conditional, like meta.offspec) - fixture bytes safe")
        check("Manual corrections" not in DEL.gaps_report(d, "Test", work_dir=td),
              "and the Gaps Report emits no override section at all")

    print("\nRESUME wiring (the deletion case is the one a naive fix misses):")
    src_r = (HELPERS / "run.py").read_text(encoding="utf-8")
    seg = src_r.split("merge_inputs.append(overrides_f)", 1)
    check(len(seg) == 2, "run.py adds overrides.json to merge_inputs")
    check(".overrides_sha" in src_r and "_write_if_changed" in src_r,
          "and a CONTENT sentinel, so DELETING overrides.json also invalidates the resume guard "
          "(_is_current skips a missing input, so an mtime-only list cannot see a removal)")
    check("--overrides" in src_r, "run.py passes --overrides to merge")

    if FAILS:
        print(f"\nOVERRIDES TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nOVERRIDES TEST: PASS (survives re-extraction, fails closed, cannot fabricate, "
          "wins precedence, re-clusters, byte-identical when unused)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
