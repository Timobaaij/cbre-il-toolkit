#!/usr/bin/env python3
"""value_format_single_pass_test.py - value-format asks only what is ambiguous, ONCE. (3.3 / 2.3)

THE DEFECT, 2026-09-26 test run. The value-format gate raised 32 blocking broker questions (officeArea
11, carParking 10, overheadDoors 10, divisibleFrom 1) and 31 of them were about values that were never
ambiguous:
  * COUNTS judged like measurements - a bare '130' beside '72 parking spaces' was asked what unit it
    was in, as if 'parking spaces' were a unit the figure had lost;
  * a bare officeArea asked about although the chrome never prints it bare (`officeAreaStr` renders
    fmt(officeAreaVal) + the dataset unit);
  * a bare area whose OWN record's source printed the very unit its siblings write;
  * and a CASCADE: each answer the broker bridge wrote ('5000' -> '5000 sq m', a `vf-*` repair) was
    counted as a new measured source - crediting the ORIGINAL source, which printed it bare, with
    writing the unit (F21) - so under-threshold fields crossed the line and a second round opened.

WHAT THIS PINS, against the REAL gate in a subprocess (synthetic canonical + ledger, temp dirs):
  a. counts beside counts-with-a-noun PASS with a note; the same values on a non-count field BLOCK
     (control: the exemption, not the fixture, is what passes it);
  b. a count whose siblings write an AREA unit ('1.2 acres' of truck parking) is still asked;
  c. the officeArea chrome twin passes; an ASSUMED unit (meta.unitAssumptions) or a missing twin
     still blocks;
  d. the own-unit rule passes a bare area on a record whose own pdf row states the siblings' unit,
     and BLOCKS for every weaker case: a different stated unit (the findings json then carries
     `own_unit`), a converted record (the 10.76x class), an assumed unit, a tracker (xlsx) row, and
     no ledger at all;
  e. no second round: once the bridge's answer lands, the gate passes, and a vf-composed value never
     counts toward `measured_sources`;
  f. repaired door counts written with their noun do not open a round against bare counts;
  g. the template markers the chrome-twin rule relies on are still in the chrome.
Offline, no client data.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"
LEDGER_COLS = ["property_id", "record_type", "field", "value", "source_file",
               "source_locator", "source_type"]
FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _prop(pid, **fields):
    base = {"id": pid, "park": f"Park {pid}", "city": "Northport", "developer": "D",
            "country": "ZZ", "status": "Available", "areaUnit": "sq m"}
    base.update(fields)
    return base


def _row(pid, field, value, src, loc="page 2", typ="pdf"):
    return {"property_id": str(pid), "record_type": "property", "field": field,
            "value": str(value), "source_file": src, "source_locator": loc, "source_type": typ}


def _run(props, ledger=None, meta=None, emit=False):
    d = Path(tempfile.mkdtemp(prefix="cbre_vf1_"))
    canon = d / "canonical.json"
    canon.write_text(json.dumps({"meta": dict({"client": "T"}, **(meta or {})), "pois": [],
                                 "regions": {}, "properties": props}), encoding="utf-8")
    if ledger is not None:
        with open(d / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=LEDGER_COLS, lineterminator="\n")
            wr.writeheader()
            wr.writerows(ledger)
    cmd = [sys.executable, str(GATE), "value-format", str(canon)]
    if emit:
        cmd += ["--emit-json", str(d / "value_format_findings.json")]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    found = None
    if emit and (d / "value_format_findings.json").exists():
        found = json.loads((d / "value_format_findings.json").read_text(encoding="utf-8-sig"))
    return p.returncode, out, found, d


def main() -> int:
    print("== a. counts beside counts-with-a-noun are not asked ==")
    props = [_prop(1, carParking="72 parking spaces"), _prop(2, carParking="95 Car Parking Spaces"),
             _prop(3, carParking="130")]
    led = [_row(1, "carParking", "72 parking spaces", "A.pdf"),
           _row(2, "carParking", "95 Car Parking Spaces", "B.pdf"),
           _row(3, "carParking", "130", "C.pdf")]
    rc, out, _, _ = _run(props, led)
    ck(rc == 0 and "STATUS: ALL-PASS" in out, f"carParking '130' beside two noun-counts: ALL-PASS (rc {rc})")
    ck("a COUNT field" in out and "`carParking`" in out, "...with the count note naming the field")
    # control: the same strings on a NON-count canonical field still block
    ctl = [_prop(1, clearHeight="72 parking spaces"), _prop(2, clearHeight="95 Car Parking Spaces"),
           _prop(3, clearHeight="130")]
    cled = [dict(r, field="clearHeight") for r in led]
    rc, out, _, _ = _run(ctl, cled)
    ck(rc == 1 and "STATUS: BLOCKED" in out,
       "control: the same values on a non-count field (clearHeight) BLOCK - the exemption is what passed (a)")

    print("\n== b. a count whose siblings write an AREA unit is still asked ==")
    props = [_prop(1, truckParking="1.2 acres"), _prop(2, truckParking="2 acres"),
             _prop(3, truckParking="40")]
    led = [_row(1, "truckParking", "1.2 acres", "A.pdf"), _row(2, "truckParking", "2 acres", "B.pdf"),
           _row(3, "truckParking", "40", "C.pdf")]
    rc, out, _, _ = _run(props, led)
    ck(rc == 1 and "`truckParking`" in out and "STATUS: BLOCKED" in out,
       f"truckParking '40' beside '1.2 acres'/'2 acres': BLOCKED (rc {rc})")

    print("\n== c. the officeArea chrome twin ==")
    base_c = [_prop(1, areaUnit="sq ft", officeArea="16,001 sq ft", officeAreaVal=16001),
              _prop(2, areaUnit="sq ft", officeArea="9,350 sq ft", officeAreaVal=9350)]
    led_c = [_row(1, "officeArea", "16,001 sq ft", "A.pdf"), _row(2, "officeArea", "9,350 sq ft", "B.pdf"),
             _row(3, "officeArea", "4614", "C.pdf")]
    rc, out, _, _ = _run(base_c + [_prop(3, areaUnit="sq ft", officeArea="4614", officeAreaVal=4614)], led_c)
    ck(rc == 0 and "numeric twin `officeAreaVal`" in out,
       f"officeArea '4614' with officeAreaVal 4614: ALL-PASS with the twin note (rc {rc})")
    rc, out, _, _ = _run(base_c + [_prop(3, areaUnit="sq ft", officeArea="4614", officeAreaVal=4614)], led_c,
                         meta={"unitAssumptions": [{"id": 3, "field": "areaUnit", "assumed": "sq ft"}]})
    ck(rc == 1 and "`officeArea`" in out, f"...the same with id 3's unit ASSUMED: BLOCKED (rc {rc})")
    rc, out, _, _ = _run(base_c + [_prop(3, areaUnit="sq ft", officeArea="4614")], led_c)
    ck(rc == 1, f"...the same with NO numeric twin: BLOCKED (rc {rc})")

    print("\n== d. the record's OWN stated unit ==")
    sib = [_prop(1, divisibleFrom="10,000 sq m"), _prop(2, divisibleFrom="10,000 sq m")]
    sib_led = [_row(1, "divisibleFrom", "10,000 sq m", "A.pdf"),
               _row(2, "divisibleFrom", "10,000 sq m", "B.pdf"),
               _row(3, "divisibleFrom", "5000", "C.pdf", "page 4")]
    p3 = _prop(3, divisibleFrom="5000", warehouseArea=20000)
    rc, out, _, _ = _run(sib + [p3], sib_led + [_row(3, "areaUnit", "sq m", "C.pdf", "page 3")])
    ck(rc == 0 and "its record's own source states the area unit" in out and "C.pdf" in out,
       f"a pdf areaUnit row 'sq m' for the bare record: ALL-PASS with the own-unit note citing it (rc {rc})")
    rc, out, found, _ = _run(sib + [dict(p3, areaUnit="sq ft")],
                             sib_led + [_row(3, "areaUnit", "sq ft", "C.pdf", "page 3")], emit=True)
    ck(rc == 1 and found and found[0]["bare"] == [{"id": 3, "value": "5000", "own_unit": "sq ft"}],
       f"its own source states 'sq ft' (not the siblings' sq m): BLOCKED, and the finding carries "
       f"own_unit 'sq ft' ({found[0]['bare'] if found else None})")
    rc, out, _, _ = _run(sib + [p3], sib_led + [_row(3, "areaUnit", "sq ft", "C.pdf", "page 3")])
    ck(rc == 1, f"the record says sq m but its areaUnit row says sq ft: BLOCKED (rc {rc})")
    rc, out, _, _ = _run(sib + [p3], sib_led + [
        _row(3, "areaUnit", "sq m", "C.pdf", "page 3"),
        _row(3, "warehouseArea", "20000", "C.pdf",
             "page 3 (stated as 215,278 sq ft; converted at 0.0929 sq m per sq ft)")])
    ck(rc == 1, f"a CONVERTED warehouseArea on the record (the 10.76x class): BLOCKED (rc {rc})")
    rc, out, _, _ = _run(sib + [p3], sib_led + [_row(3, "areaUnit", "sq m", "C.pdf", "page 3")],
                         meta={"unitAssumptions": [{"id": 3, "field": "areaUnit", "assumed": "sq m"}]})
    ck(rc == 1, f"the record's unit in meta.unitAssumptions: BLOCKED (rc {rc})")
    rc, out, _, _ = _run(sib + [p3], sib_led + [_row(3, "areaUnit", "sq m", "T.xlsx", "row 4", "xlsx")])
    ck(rc == 1, f"a TRACKER (xlsx) areaUnit row does not count as a printed unit: BLOCKED (rc {rc})")
    rc, out, _, _ = _run(sib + [p3], None)
    ck(rc == 1, f"no ledger at all: BLOCKED - the 10.76x protection holds where evidence is missing (rc {rc})")
    rc, out, _, _ = _run(sib + [_prop(3, divisibleFrom="5000", plotArea=40000)], sib_led + [
        _row(3, "areaUnit", "sq m", "C.pdf", "page 3"),
        _row(3, "plotArea", "40000", "C.pdf", "page 3 (stated as 4 ha; converted at 10000 sq m per ha)")])
    ck(rc == 0, f"a routine PLOT conversion (ha -> sq m) does not disqualify the own-unit rule (rc {rc})")

    print("\n== e. no second round ==")
    props_e = sib + [_prop(3, divisibleFrom="5000")]
    rc1, out1, _, _ = _run(props_e, sib_led)
    ck(rc1 == 1, f"round 1: the bare '5000' is asked (rc {rc1})")
    ans = sib + [_prop(3, divisibleFrom="5000 sq m")]
    ans_led = sib_led + [_row(3, "divisibleFrom", "5000 sq m", "repairs.json", "vf-q_x", "repair")]
    rc2, out2, _, _ = _run(ans, ans_led)
    ck(rc2 == 0 and "STATUS: ALL-PASS" in out2, f"after the bridge's answer lands: ALL-PASS (rc {rc2})")
    # a vf-composed value never votes: two real sources + two vf answers + one bare
    props_v = [_prop(1, divisibleFrom="10,000 sq m"), _prop(5, divisibleFrom="12,000 sq m"),
               _prop(2, divisibleFrom="5000 sq m"), _prop(6, divisibleFrom="7000 sq m"),
               _prop(4, divisibleFrom="3000")]
    led_v = [_row(1, "divisibleFrom", "10,000 sq m", "A.pdf"), _row(5, "divisibleFrom", "12,000 sq m", "E.pdf"),
             _row(2, "divisibleFrom", "5000", "B.pdf"),
             _row(2, "divisibleFrom", "5000 sq m", "repairs.json", "vf-q_a", "repair"),
             _row(6, "divisibleFrom", "7000", "F.pdf"),
             _row(6, "divisibleFrom", "7000 sq m", "repairs.json", "vf-q_b", "repair"),
             _row(4, "divisibleFrom", "3000", "D.pdf")]
    rc, out, found, _ = _run(props_v, led_v, emit=True)
    f0 = (found or [{}])[0]
    ck(rc == 1 and f0.get("measured_sources") == 2 and f0.get("measured_count") == 4,
       f"two vf answers stay on the grid (measured_count {f0.get('measured_count')}) but cast no vote "
       f"(measured_sources {f0.get('measured_sources')}, want 2)")
    rc, out, _, _ = _run([p for p in props_v if p["id"] != 5], [r for r in led_v if r["property_id"] != "5"])
    ck(rc == 0, f"with ONE real source left, vf answers cannot push the field over the threshold (rc {rc})")

    print("\n== f. repaired door counts with their noun do not open a round ==")
    props_f = [_prop(1, overheadDoors="2 Level Access Doors"), _prop(2, overheadDoors="2 Level Access Doors")]
    props_f += [_prop(i, overheadDoors="2") for i in range(3, 8)]
    led_f = [_row(1, "overheadDoors", "2 Level Access Doors", "A.pdf", "rp-007", "repair"),
             _row(2, "overheadDoors", "2 Level Access Doors", "B.pdf", "rp-008", "repair")]
    led_f += [_row(i, "overheadDoors", "2", f"S{i}.pdf") for i in range(3, 8)]
    rc, out, _, _ = _run(props_f, led_f)
    ck(rc == 0 and "a COUNT field" in out, f"5 bare '2' beside 2 repaired noun-counts: ALL-PASS (rc {rc})")

    print("\n== g. the chrome markers the twin rule relies on ==")
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")
    for m in ("function officeAreaStr(p){", "NUMOK(p.officeAreaVal) && !/[a-z]/i.test(s)"):
        ck(m in tpl, f"template still carries {m!r}")
    sys.path.insert(0, str(ROOT / "helpers"))
    import _common as C  # noqa: E402
    ck(C.COUNT_FIELDS == frozenset({"loadingDocks", "overheadDoors", "truckParking", "carParking"}),
       "_common.COUNT_FIELDS is the four count fields")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
