#!/usr/bin/env python3
"""d5_office_area_companion_test.py - officeAreaVal is never the FIRST number of a multi-clause string. (D5)

THE DEFECT. `officeAreaVal`, the numeric companion `canonicalize` derives from the `officeArea`
text for Total GLA and the rent basis, was parsed as the first number found in the string. Where a
reader shipped several stated office lines in one string, a live client run produced:

    Novus 387:        "899 sq m / 9,681 sq ft ground floor office; 880 sq m / 9,469 sq ft first
                       floor; ..."                                -> officeAreaVal 899.0
    Worksop Link 460: "11,829 sq ft (GF Offices); 11,807 sq ft (FF Offices)"
                                                                  -> officeAreaVal 11,829.0

Novus is a 27x understatement AND a unit confusion: 899 is a SQ M figure, shipped as the sq ft
office area on a sq ft dashboard. Neither gate saw it: the value-format gate did not fire (899 is
not "bare", its string carries units) and the arithmetic gate did not fire (a too-SMALL office
cannot inflate the GLA). A human reviewer found it in the client pack.

THE REAL CONTRACT, which is what this pins (the defects log offered "refuse, or require the parse
to match the record's own areaUnit"; the implementation does BOTH, and does NOT sum):
  1. The common case is a NO-OP: "2,500 sq ft" -> 2500.0 exactly, a numeric 2500 -> 2500.0, a
     bare "24230" -> 24230.0, "2,500 sq ft over 2 floors" -> 2500.0 (a small bare number beside a
     unit-bearing figure is a floor count, not an area). Asserted explicitly: a fix that moved the
     one-clause case would touch every office on every longlist.
  2. A figure RESTATED in two units ("1,413 sq m / 15,213 sq ft") yields the figure printed in the
     RECORD's own unit, so a wrong-unit twin is never taken. A single figure in the OTHER unit
     ("1,413 sq m" on a sq ft record) is taken in its own unit and CONVERTED by the alignment step,
     so the shipped value is ~15,209 and never the raw 1,413.
  3. A leading total whose later figures sum to it ("24,230 (offices 20,000; gatehouse 4,230)")
     yields the total; the arithmetic identity is checked, never assumed.
  4. Anything else with several figures is REFUSED: the exact Novus and Worksop strings yield NO
     value (not 899, not 11,829, and NOT a sum: the Novus clauses restate the same area in two
     units, so 899 + 9,681 + 880 + 9,469 would have been catastrophic). The field ships ABSENT.
  5. The refusal is DISCLOSED on three surfaces the real `merge.main` writes: stdout, the
     `meta.conflicts` channel the Gaps Report prints, and a gap ledger row whose locator reads
     "NOT derived from officeArea" (never "absent in all sources" when the source printed three
     office lines). The refusal names every figure so the operator can state the total by repair.

HOW IT CATCHES THE REGRESSION. A first-number parse returns 899.0 for the Novus string and
11,829.0 for Worksop; checks 4 assert the value is None at the parser, absent/non-numeric after
`canonicalize`, and absent after the real merge, and each names the old value in its label. A
parser that summed the clauses would trip the "not summed" checks. A refusal that stopped being
disclosed would trip check 5 while every value check still passed, which is why 5 is here.

The third Novus clause is elided in the defects log ("...") and is reconstructed here as a
second-floor line whose sq ft figure closes the stated 24,230 total; the literal elided form is
tested as well. Offline: pure-function checks, `canonicalize`, and the real merge.main via subprocess.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import merge  # noqa: E402
import normalize as N  # noqa: E402

FAILS: list[str] = []

NOVUS_LOGGED = ("899 sq m / 9,681 sq ft ground floor office; 880 sq m / 9,469 sq ft first "
                "floor; ...")
NOVUS_FULL = ("899 sq m / 9,681 sq ft ground floor office; 880 sq m / 9,469 sq ft first floor; "
              "472 sq m / 5,080 sq ft second floor")
WORKSOP = "11,829 sq ft (GF Offices); 11,807 sq ft (FF Offices)"
OLD_NOVUS, OLD_WORKSOP = 899.0, 11829.0          # what the first-number parse shipped
SUM_NOVUS_FT, SUM_WORKSOP = 24230.0, 26208.0     # the true totals, which the strings never print
SQM_TO_SQFT = N.area_factor("sq m", "sq ft") or 10.7639


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _r(src, park, **kw):
    r = {"park": park, "city": "Corby", "country": "GB", "developer": "Dev",
         "warehouseArea": 200000, "areaUnit": "sq ft",
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": "page 1"}}
    r.update(kw)
    return r


def _run_merge(recs: list[dict], tag: str):
    d = Path(tempfile.mkdtemp(prefix=f"cbre_d5_{tag}_"))
    (d / "inputs").mkdir()
    (d / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (p.stderr or "")
    if not (d / "c.json").exists():
        return None, None, out
    canon = json.loads((d / "c.json").read_text(encoding="utf-8"))
    rows = []
    if (d / "l.csv").exists():
        rows = list(csv.DictReader(io.StringIO((d / "l.csv").read_text(encoding="utf-8-sig"))))
    return canon, rows, out


def main() -> int:
    P = merge._office_area_parse

    print("== 1. the common case is a NO-OP (byte-identical to before) ==")
    r = P("2,500 sq ft", "sq ft")
    ck(r is not None and r.get("value") == 2500.0 and r.get("unit") == "sq ft" and not r.get("note"),
       f"'2,500 sq ft' -> 2500.0 sq ft, no note ({ascii(str(r))})")
    ck((P(2500, "sq ft") or {}).get("value") == 2500.0, "a numeric 2500 -> 2500.0")
    ck((P("24230", "sq ft") or {}).get("value") == 24230.0, "a bare '24230' -> 24230.0")
    ck((P("2,500 sq ft over 2 floors", "sq ft") or {}).get("value") == 2500.0,
       "'2,500 sq ft over 2 floors' -> 2500.0 (the floor count is not an area)")
    ck(merge._office_area_val_from({"officeArea": "2,500 sq ft", "areaUnit": "sq ft"}) == 2500.0,
       "_office_area_val_from on the one-clause case is 2500.0")
    for bad in (None, "", "tbd", "5% of GLA", "2,000-3,000 sq ft", "offices to suit"):
        ck(P(bad, "sq ft") is None, f"{ascii(str(bad))} -> None (unknown, share, range, no figure)")

    print()
    print("== 2. a figure whose printed unit disagrees with the record's areaUnit is never taken ==")
    r = P("1,413 sq m / 15,213 sq ft", "sq ft")
    ck(r is not None and r.get("value") == 15213.0 and r.get("unit") == "sq ft",
       f"dual restatement on a sq ft record -> the sq ft figure 15,213, not 1,413 ({ascii(str((r or {}).get('value')))})")
    ck(bool((r or {}).get("note")), "...and the choice is noted for the ledger")
    r = P("1,413 sq m / 15,213 sq ft", "sq m")
    ck(r is not None and r.get("value") == 1413.0 and r.get("unit") == "sq m",
       "the same string on a sq m record -> the sq m figure 1,413")
    r = P("9,681 sq ft (899 sq m)", "sq ft")
    ck(r is not None and r.get("value") == 9681.0 and r.get("unit") == "sq ft",
       f"'9,681 sq ft (899 sq m)' on a sq ft record -> 9,681, never 899 ({ascii(str((r or {}).get('value')))})")
    r = P("899 sq m (9,681 sq ft)", "sq ft")
    ck(r is not None and r.get("value") == 9681.0,
       f"...and with the sq m figure FIRST it is still 9,681 (order does not decide) ({ascii(str((r or {}).get('value')))})")
    r = P("1,413 sq m", "sq ft")
    ck(r is not None and r.get("value") == 1413.0 and r.get("unit") == "sq m",
       "a single sq m figure on a sq ft record is taken in ITS OWN unit (sq m), for conversion downstream")

    print()
    print("== 3. a leading total confirmed by its parts is taken; an unconfirmed one is not ==")
    r = P("24,230 (offices 20,000; gatehouse 4,230)", "sq ft")
    ck(r is not None and r.get("value") == 24230.0 and "total" in str(r.get("note")),
       "'24,230 (offices 20,000; gatehouse 4,230)' -> 24,230 with a note")
    r = P("45,649 sq ft total non-warehouse area (offices 28,804 sq ft; hub 15,134 sq ft; gatehouse 1,711 sq ft)", "sq ft")
    ck(r is not None and r.get("value") == 45649.0, "a unit-bearing leading total whose parts sum to it -> the total")
    r = P("24,230 (offices 20,000; gatehouse 3,000)", "sq ft")
    ck(r is not None and r.get("refused") and r.get("value") is None,
       "a leading figure that does NOT equal its parts is refused, not assumed to be the total")

    print()
    print("== 4. the exact live strings: REFUSED, not first-number, not summed ==")
    for label, s, old, summed in (("Novus (as logged)", NOVUS_LOGGED, OLD_NOVUS, SUM_NOVUS_FT),
                                  ("Novus (full)", NOVUS_FULL, OLD_NOVUS, SUM_NOVUS_FT),
                                  ("Worksop", WORKSOP, OLD_WORKSOP, SUM_WORKSOP)):
        r = P(s, "sq ft")
        ck(r is not None and r.get("refused") is True, f"{label}: the parser REFUSES")
        v = (r or {}).get("value")
        ck(v is None, f"{label}: value is None ({ascii(str(v))})")
        ck(v != old, f"{label}: ...and in particular not the old first-number {old:g}")
        ck(v != summed, f"{label}: ...and not a sum the source never printed ({summed:g})")
        figs = (r or {}).get("figures") or []
        ck(len(figs) >= 2 and any("sq" in f.lower() for f in figs),
           f"{label}: the refusal names every figure ({ascii(str(figs))})")
        ck("not summed" in str((r or {}).get("why", "")).lower()
           or "none is identifiably the total" in str((r or {}).get("why", "")),
           f"{label}: the why explains the refusal ({ascii(str((r or {}).get('why', ''))[:90])})")
        ck(merge._office_area_val_from({"officeArea": s, "areaUnit": "sq ft"}) is None,
           f"{label}: _office_area_val_from -> None")
    r = P(NOVUS_FULL, "sq m")
    ck(r is not None and r.get("refused") is True and r.get("value") is None,
       "Novus on a sq m record is refused too (three lines are three lines whatever the dataset unit)")

    print()
    print("== 5. canonicalize: the field ships NON-NUMERIC on refusal, exact on the plain case ==")
    c = merge.canonicalize({"park": "N", "officeArea": NOVUS_FULL, "areaUnit": "sq ft",
                            "warehouseArea": 200000})
    ck(not _isnum(c.get("officeAreaVal")),
       f"Novus after canonicalize: officeAreaVal is not a number ({ascii(str(c.get('officeAreaVal')))})")
    ck(c.get("officeAreaVal") != OLD_NOVUS, "...and is not 899.0")
    c = merge.canonicalize({"park": "W", "officeArea": WORKSOP, "areaUnit": "sq ft",
                            "warehouseArea": 200000})
    ck(not _isnum(c.get("officeAreaVal")) and c.get("officeAreaVal") not in (OLD_WORKSOP, SUM_WORKSOP),
       f"Worksop after canonicalize: not 11,829 and not 26,208 ({ascii(str(c.get('officeAreaVal')))})")
    c = merge.canonicalize({"park": "P", "officeArea": "2,500 sq ft", "areaUnit": "sq ft",
                            "warehouseArea": 200000})
    ck(c.get("officeAreaVal") == 2500.0, f"plain '2,500 sq ft' after canonicalize -> 2500.0 ({ascii(str(c.get('officeAreaVal')))})")
    c = merge.canonicalize({"park": "S", "officeArea": NOVUS_FULL, "areaUnit": "sq ft",
                            "officeAreaVal": 24230, "warehouseArea": 200000})
    ck(c.get("officeAreaVal") == 24230, "a STATED officeAreaVal (a repair or a source column) is left alone")

    print()
    print("== 6. the real merge: refused fields ship absent and the refusal is disclosed ==")
    recs = [
        _r("Novus.pdf", "Novus 387", officeArea=NOVUS_FULL),
        _r("Worksop.pdf", "Worksop Link 460", officeArea=WORKSOP),
        _r("Plain.pdf", "Plain Park", officeArea="2,500 sq ft"),
        _r("Metric.pdf", "Metric Line", officeArea="1,413 sq m"),
        _r("Dual.pdf", "Dual Line", officeArea="1,413 sq m / 15,213 sq ft"),
    ]
    canon, rows, out = _run_merge(recs, "live")
    ck(canon is not None, f"merge completes {ascii(out[-200:]) if canon is None else ''}")
    if canon is not None:
        by = {q.get("park"): q for q in canon.get("properties") or []}
        conflicts = "\n".join((canon.get("meta") or {}).get("conflicts") or [])
        gap_rows = [x for x in (rows or []) if x.get("field") == "officeAreaVal"
                    and str(x.get("source_type", "")).lower() == "gap"]
        gap_by_id = {str(x.get("property_id")): x for x in gap_rows}

        for park, old in (("Novus 387", OLD_NOVUS), ("Worksop Link 460", OLD_WORKSOP)):
            q = by.get(park) or {}
            v = q.get("officeAreaVal")
            ck(not _isnum(v), f"{park}: officeAreaVal is absent/non-numeric on the shipped property ({ascii(str(v))})")
            ck(v != old, f"{park}: ...not the old {old:g}")
            pid = str(q.get("id"))
            ck(f"id {pid} officeAreaVal: NOT derived from officeArea" in conflicts,
               f"{park}: meta.conflicts carries the refusal")
            g = gap_by_id.get(pid)
            ck(g is not None, f"{park}: a gap ledger row exists for officeAreaVal")
            if g is not None:
                loc = str(g.get("source_locator", ""))
                ck(loc.startswith("NOT derived from officeArea"),
                   f"{park}: the gap row's locator says WHY ({ascii(loc[:70])})")
                ck("absent in all sources" not in loc.lower(),
                   f"{park}: ...and never claims the source was silent")
                ck("899" in loc if park.startswith("Novus") else "11,829" in loc,
                   f"{park}: the gap row names the figures so the operator can repair it")
            ck(f"id {pid}" in out and "officeAreaVal NOT derived" in out,
               f"{park}: the refusal is said on stdout")

        q = by.get("Plain Park") or {}
        ck(q.get("officeAreaVal") == 2500, f"Plain Park: officeAreaVal is 2500 ({ascii(str(q.get('officeAreaVal')))})")
        ck(str(q.get("id")) not in gap_by_id, "Plain Park: NO gap row (the refusal path does not over-fire)")
        ck(f"id {q.get('id')} officeAreaVal" not in conflicts, "Plain Park: no conflicts entry")

        q = by.get("Metric Line") or {}
        v = q.get("officeAreaVal")
        ck(_isnum(v) and v != 1413, f"Metric Line: a lone sq m figure on a sq ft record is not shipped raw as 1,413 ({ascii(str(v))})")
        ck(_isnum(v) and abs(v - 1413 * SQM_TO_SQFT) <= 20,
           f"Metric Line: ...it is converted to ~{1413 * SQM_TO_SQFT:,.0f} sq ft ({ascii(str(v))})")

        q = by.get("Dual Line") or {}
        ck(q.get("officeAreaVal") == 15213, f"Dual Line: the sq ft twin 15,213 is taken as-is ({ascii(str(q.get('officeAreaVal')))})")

        ck(len(gap_rows) == 2, f"exactly two officeAreaVal gap rows across the five properties ({len(gap_rows)})")

    print()
    if FAILS:
        print(f"D5 OFFICE AREA COMPANION TEST: FAIL ({len(FAILS)})")
        return 1
    print("D5 OFFICE AREA COMPANION TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
