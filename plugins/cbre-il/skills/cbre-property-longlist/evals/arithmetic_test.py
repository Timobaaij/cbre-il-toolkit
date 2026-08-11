#!/usr/bin/env python3
"""arithmetic_test.py - P1-1: derived GLA must not exceed the source's OWN stated total.

THE LIVE DEFECT. A tracker column holding each brochure's TOTAL GIA was mapped into
`warehouseArea`. The chrome derives `Total GLA = warehouseArea + officeAreaVal` and
`rent = GLA x rate`, so the office area was added to a figure that already contained it: derived
GLA 557,232 against the source's own stated 498,723 (11.7% over) and rent overstated by up to
GBP 702,108/yr - figures in no source. Two Opus reviewers caught it by hand; arithmetic is free.

THE HARD PART IS NOT THE ARITHMETIC, IT IS NOT BLOCKING A GOOD RUN. Most of this suite is
skip-path coverage: a gate in `g1` exits 6, so every unsound comparison must be declined rather
than guessed at. The ack is the always-available terminating remedy (the "fix the datum" remedy is
only DURABLE once P1-4 lands - editing work/extract/ is discarded on re-extraction).

WHAT IS DELIBERATELY NOT TESTED, because it must not exist: any Python that decides WHICH of the
two figures is wrong. The gate reports arithmetic; the tracker mapping, the office area and the
stated total all remain LLM/reviewer judgements.

Locks:
  1. the LIVE numbers block (498,723 stated + 58,509 office on a kept gross -> 557,232, 11.7%)
  2. tolerance max(50, 0.5%): the live near-misses (2 sq ft; ~700 on ~440,000 = 0.159%) PASS
  3. ASYMMETRY: over-derivation blocks, under-derivation is a [note] only
  4. every unsound comparison SKIPS - no stated total, non-numeric/absent/sentinel contributor,
     officeAreaVal <= 0, a non-finite number
  5. the gate replicates the chrome's glaVal() guard exactly (office counted only when > 0)
  6. the ack (`arithmetic_ok` in placeholder_audit_ack.json) clears a property and TERMINATES
  7. merge.stated_total_for refuses an un-aligned unit rather than comparing across units
     (a unit flip is the 10.76x class), and never invents a unit
  8. the extract_xlsx FREE WIN emits the gross total ONLY when the size is GIA-qualified, and the
     value is the figure PRINTED IN THE SHEET - not a re-derivation (which would be circular)

Offline. Run: python evals/arithmetic_test.py"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import gate_runner as GR  # noqa: E402
import merge as M         # noqa: E402

FAILS: list[str] = []


def check(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def run_gate(props, stated, ack=None, tmp=None) -> tuple[int, str]:
    """Drive cmd_arithmetic on a canonical built from `props` + meta.statedTotals."""
    d = Path(tmp or tempfile.mkdtemp(prefix="cbre_arith_"))
    canon = d / "canonical.json"
    meta = {"client": "T", "statedTotals": stated} if stated else {"client": "T"}
    for i, p in enumerate(props, start=1):
        p.setdefault("id", i)
        p.setdefault("areaUnit", "sq ft")
    canon.write_text(json.dumps({"meta": meta, "properties": props}), encoding="utf-8")
    if ack is not None:
        (d / "placeholder_audit_ack.json").write_text(json.dumps(ack), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = GR.cmd_arithmetic(_Args(canonical=str(canon)))
    return rc, buf.getvalue()


def _stated(value, unit="sq ft", **kw):
    return {"1": {"value": value, "unit": unit, "source_file": "tracker.xlsx",
                  "locator": "Longlist!r2", "contributors": ["warehouseArea", "officeAreaVal"],
                  **kw}}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("THE LIVE DEFECT - a GROSS total kept in warehouseArea, office added on top:")
    rc, out = run_gate([{"park": "Magna Park", "warehouseArea": 498723, "officeAreaVal": 58509}],
                       _stated(498723))
    check(rc == 1, "the live case BLOCKS (derived 557,232 vs stated 498,723)")
    check("557,232" in out and "498,723" in out, "both figures are printed, so the broker can see why")
    check("11.7%" in out, f"the overshoot is quantified as 11.7%")
    check("arithmetic_ok" in out and "placeholder_audit_ack.json" in out,
          "the FAIL names the ack remedy, which always terminates")
    check("NET warehouse area" in out, "and names the usual cause (a gross size column)")

    print("\nTOLERANCE max(50, 0.5%) - the LIVE near-misses must PASS:")
    rc, _ = run_gate([{"warehouseArea": 440000, "officeAreaVal": 2}], _stated(440000))
    check(rc == 0, "out by 2 area units on 440,000 passes (a real schedule is imprecise)")
    rc, _ = run_gate([{"warehouseArea": 440000, "officeAreaVal": 700}], _stated(440000))
    check(rc == 0, "out by ~700 on ~440,000 (0.159%) passes - 3x inside the margin")
    rc, _ = run_gate([{"warehouseArea": 10000, "officeAreaVal": 49}], _stated(10000))
    check(rc == 0, "the 50-unit floor protects a SMALL property (0.5% would be only 50)")
    rc, _ = run_gate([{"warehouseArea": 440000, "officeAreaVal": 2500}], _stated(440000))
    check(rc == 1, "but 2,500 over on 440,000 (0.57%) BLOCKS - just past the tolerance")

    print("\nASYMMETRY - over-derivation blocks, under-derivation is only a note:")
    rc, out = run_gate([{"warehouseArea": 400000}], _stated(498723))
    check(rc == 0, "UNDER-derivation does NOT block (mezzanine / ancillary / plant)")
    check("[note]" in out and "under by" in out, "it is reported as a [note], not silently dropped")

    print("\nEVERY UNSOUND COMPARISON SKIPS (a g1 gate exits 6 - it must never guess):")
    rc, out = run_gate([{"warehouseArea": 1, "officeAreaVal": 999999}], {})
    check(rc == 0 and "not applicable" in out,
          "no source states a total -> not applicable (the common case; gate is inert)")
    rc, out = run_gate([{"warehouseArea": "tbd", "officeAreaVal": 58509}], _stated(498723))
    check(rc == 0 and "none comparable" in out, "a SENTINEL warehouseArea skips (glaVal returns null)")
    rc, _ = run_gate([{"officeAreaVal": 58509}], _stated(498723))
    check(rc == 0, "an ABSENT warehouseArea skips")
    rc, _ = run_gate([{"warehouseArea": 498723, "officeAreaVal": "tbd"}], _stated(498723))
    check(rc == 0, "a non-numeric officeAreaVal is treated as 0, exactly like glaVal()")
    rc, _ = run_gate([{"warehouseArea": 498723}], _stated(0))
    check(rc == 0, "a zero/absent stated total skips rather than dividing by it")
    rc, _ = run_gate([{"warehouseArea": 498723, "officeAreaVal": True}], _stated(498723))
    check(rc == 0, "a BOOLEAN is not a number (isinstance(True, int) is True in Python)")
    rc, _ = run_gate([{"warehouseArea": float("inf"), "officeAreaVal": 10}], _stated(498723))
    check(rc == 0, "a non-finite area skips (glaVal's isFinite guard)")
    rc, _ = run_gate([{"warehouseArea": 498723, "officeAreaVal": -5000}], _stated(498723))
    check(rc == 0, "a NEGATIVE officeAreaVal counts as 0, exactly like glaVal's `> 0` guard")

    print("\nTHE ACK clears one property and terminates:")
    d = Path(tempfile.mkdtemp(prefix="cbre_arith_ack_"))
    props = [{"park": "Magna Park", "warehouseArea": 498723, "officeAreaVal": 58509}]
    rc, _ = run_gate([dict(props[0])], _stated(498723), tmp=d)
    check(rc == 1, "blocks before the ack")
    rc, out = run_gate([dict(props[0])], _stated(498723),
                       ack={"arithmetic_ok": ["1"]}, tmp=d)
    check(rc == 0, "ALL-PASS once the property is acked (the remedy TERMINATES)")
    check("ACKED" in out, "and the ack is still reported, never silently swallowed")
    rc, out = run_gate([dict(props[0])], _stated(498723),
                       ack={"confirmed": ["1"]}, tmp=Path(tempfile.mkdtemp()))
    check(rc == 1, "the IMAGES ack key does not clear an arithmetic block (separate keys)")

    print("\nmerge.stated_total_for - unit safety and no invention:")
    cl = [{"__meta": {"statedTotalArea": 46330.0, "statedTotalUnit": "sq m",
                      "source_file": "t.xlsx", "statedTotalLocator": "L!r2"}}]
    got = M.stated_total_for(cl, {"areaUnit": "sq m"}, "sq ft")
    check(got is not None and abs(got["value"] - round(46330.0 * M.N.SQFT_PER_SQM)) < 1,
          "a sq m total is CONVERTED with merge's own SQFT_PER_SQM factor")
    check(got is not None and got["unit"] == "sq ft" and "converted" in got["locator"],
          "and the conversion is recorded in the locator")
    check(M.stated_total_for(cl, {"areaUnitAssumed": True}, "sq ft") is None,
          "an ASSUMED unit refuses outright - merge did NOT convert those areas (10.76x class)")
    check(M.stated_total_for([{"__meta": {"statedTotalArea": 1000}}], {}, "sq ft") is None,
          "an UNKNOWN unit refuses rather than inferring one")
    check(M.stated_total_for([{"__meta": {"statedTotalArea": 0}}], {}, "sq ft") is None
          and M.stated_total_for([{"__meta": {}}], {}, "sq ft") is None,
          "a zero or absent stated total yields None")
    check(M.stated_total_for(cl, {"areaUnit": "sq m"}, "sq m")["contributors"]
          == ["warehouseArea", "officeAreaVal"],
          "contributors name the fields the chrome's glaVal() actually sums")

    print("\nThe gate replicates the CHROME's formula, quoted not re-derived:")
    tpl = (HELPERS.parent / "assets" / "dashboard_template.html").read_text(encoding="utf-8")
    check("return w + o;" in tpl,
          "assets/dashboard_template.html still derives GLA as warehouse + office")
    src = (HELPERS / "gate_runner.py").read_text(encoding="utf-8")
    check("glaVal" in src, "cmd_arithmetic quotes glaVal so a template change is traceable to it")
    check("p.get(\"officeAreaVal\")" in src and "oa > 0" in src,
          "and reproduces its `> 0` office guard rather than summing blindly")

    print("\nThe FREE WIN is not circular - extract_xlsx emits a PRINTED figure:")
    xs = (HELPERS / "extract_xlsx.py").read_text(encoding="utf-8")
    check("stated_total = float(wh)" in xs,
          "the emitted total is `wh`, the value READ from the sheet's size cell")
    i_gia, i_set = xs.index("_GIA_RX.search(wh_hdr)"), xs.index("stated_total = float(wh)")
    check(i_gia < i_set,
          "it is emitted ONLY inside the GIA/GEA/GLA-qualified branch (a plain size is not a total)")
    check(xs.index("stated_total = float(wh)") < xs.index('rec["warehouseArea"] = round(wh - office_num)'),
          "and captured BEFORE the office subtraction, so it is the GROSS figure")
    check('rec["__meta"]["statedTotalArea"]' in xs,
          "it lands in __meta, never at the record top level (else it PRINTS on the client's card)")

    # END TO END on a REAL xlsx. Everything above drives cmd_arithmetic and stated_total_for
    # DIRECTLY; this is the only part that proves the wiring. This project has twice shipped a fix
    # whose function was correct and whose PATH was dead, so a unit-tested gate is not evidence.
    print("\nEND TO END - a real tracker through extract_xlsx -> merge -> the gate:")
    try:
        import openpyxl
    except Exception:                                  # pragma: no cover - bundled shim absent
        print("  [note] openpyxl unavailable - end-to-end leg skipped (unit legs still ran)")
        openpyxl = None
    if openpyxl is not None:
        import extract_xlsx as X
        d = Path(tempfile.mkdtemp(prefix="cbre_arith_e2e_"))
        xl = d / "tracker.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Longlist"
        # The LIVE shape: the size is GIA-qualified by a separate 'Area basis' column and the
        # tracker quotes NO office area - so warehouseArea keeps the GROSS total, and the office
        # figure arrives from a brochure afterwards. That is the defect's exact anatomy.
        ws.append(["Park", "City", "Country", "Developer", "Size (sq ft)", "Area basis",
                   "Clear height", "Status"])
        ws.append(["Magna Park Corby", "Corby", "United Kingdom", "GLP", 498723, "GIA",
                   "15 m", "Existing"])
        wb.save(xl)
        recs = X.detect_and_extract(xl, "", "")["records"]
        m0 = (recs[0].get("__meta") or {}) if recs else {}
        check(m0.get("statedTotalArea") == 498723.0,
              f"extract_xlsx emits the GROSS total from the sheet "
              f"(got {m0.get('statedTotalArea')!r})")
        check(recs and "statedTotalArea" not in recs[0],
              "and NOT at the record top level (a top-level scalar renders in the v21 modal)")
        if recs:
            recs[0]["officeArea"] = "58509"          # the brochure's office figure, second source
            recs[0]["__meta"].setdefault("prov", {})["officeArea"] = "page 4"
            rec_f = d / "records.json"
            rec_f.write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")
            src2 = d / "inputs"
            src2.mkdir(exist_ok=True)
            canon2, led2 = d / "canonical.json", d / "source_ledger.csv"
            saved = sys.argv
            sys.argv = ["merge", "--records", str(rec_f), "--source-dir", str(src2),
                        "--out", str(canon2), "--ledger", str(led2)]
            try:
                with redirect_stdout(io.StringIO()):
                    M.main()
                mrc = 0
            except SystemExit as e:
                mrc = e.code if isinstance(e.code, int) else 0
            finally:
                sys.argv = saved
            check(mrc == 0, "merge completes")
            data = json.loads(canon2.read_text(encoding="utf-8"))
            st2 = (data.get("meta") or {}).get("statedTotals") or {}
            prop = (data.get("properties") or [{}])[0]
            check(st2.get("1", {}).get("value") == 498723.0,
                  "merge lifts it to canonical.meta.statedTotals[id]")
            check(not [k for k in prop if "statedTotal" in k],
                  "and nothing leaks onto the property (no chrome bump, no modal row)")
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                grc2 = GR.cmd_arithmetic(_Args(canonical=str(canon2)))
            o2 = buf2.getvalue()
            check(grc2 == 1, "the gate BLOCKS the real chain")
            check("557,232" in o2 and "498,723" in o2 and "11.7%" in o2,
                  "with the live figures: 557,232 derived vs 498,723 stated, 11.7% over")

    if FAILS:
        print(f"\nARITHMETIC TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nARITHMETIC TEST: PASS (live defect blocks, near-misses pass, every unsound "
          "comparison skips, ack terminates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
