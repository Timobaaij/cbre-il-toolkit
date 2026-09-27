#!/usr/bin/env python3
"""office_area_shape_test.py - fix 3.3c, merge side (2026-09-26 test run).

A reader's bare officeArea ("4614") shipped verbatim beside a same-file areaUnit 'sq ft', and
the broker had to answer value-format questions whose repairs set "4614 sq ft". merge now writes
ONE shape - "4,614 sq ft" - but ONLY when the supplier record itself states the unit, that unit is
the dataset unit (nothing converted), the supplier is not a tracker, and the figure is integral.

Pins (real merge.py subprocess runs):
  * pdf record officeArea "4614", areaUnit "sq ft", sq ft dataset -> "4,614 sq ft",
    officeAreaVal 4614, ledger locator contains "printed as '4614'";
  * the same shape as an int (4614) -> "4,614 sq ft";
  * a sq m record inside a sq ft dataset -> officeArea unchanged, officeAreaVal converted;
  * no areaUnit on the record -> unchanged;
  * an xlsx supplier -> unchanged;
  * a decimal ("4614.5") -> unchanged (a grouped decimal would misparse downstream);
  * a figure with words ("approx 4614") -> unchanged;
  * repairs compat: a vf-shaped entry (expect "4614", set "4614 sq ft") APPLIES, not superseded.

Run: python evals/office_area_shape_test.py"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

import match  # noqa: E402
import repairs as R  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def rec(park, city, src="deck.pdf", stype="pdf", **kw):
    r = {"park": park, "city": city, "country": "ZZ", "developer": "Devco",
         "warehouseArea": 100000,
         "__meta": {"source_file": src, "source_type": stype, "locator_base": "page 2"}}
    r.update(kw)
    return r


def run(recs):
    d = Path(tempfile.mkdtemp(prefix="cbre_office_shape_"))
    (d / "inputs").mkdir()
    (d / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if not (d / "c.json").exists():
        print(ascii((p.stdout + p.stderr)[-400:]))
        return None, []
    rows = list(csv.DictReader(open(d / "l.csv", encoding="utf-8-sig", newline="")))
    return json.loads((d / "c.json").read_text(encoding="utf-8")), rows


def by_park(canon):
    return {q.get("park"): q for q in (canon or {}).get("properties") or []}


def main() -> int:
    sqft = dict(areaUnit="sq ft")
    canon, rows = run([rec("Alpha Park", "Northtown", officeArea="4614", **sqft),
                       rec("Beta Park", "Southville", src="b.pdf", officeArea=4614, **sqft),
                       rec("Gamma Park", "Eastham", src="g.pdf", officeArea="4614.5", **sqft),
                       rec("Delta Park", "Westby", src="w.pdf", officeArea="approx 4614", **sqft)])
    ck(canon is not None, "merge completes (sq ft dataset)")
    P = by_park(canon)
    a = P.get("Alpha Park") or {}
    ck(a.get("officeArea") == "4,614 sq ft", f"bare '4614' + own 'sq ft' -> '4,614 sq ft' ({a.get('officeArea')!r})")
    ck(a.get("officeAreaVal") == 4614, f"officeAreaVal untouched at 4614 ({a.get('officeAreaVal')!r})")
    loc = [x.get("source_locator", "") for x in rows
           if x.get("field") == "officeArea" and x.get("record_type") == "property"
           and str(x.get("property_id")) == str(a.get("id"))]
    ck(bool(loc) and "printed as '4614'" in loc[0], f"the ledger locator says how it was printed ({loc[:1]})")
    ck((P.get("Beta Park") or {}).get("officeArea") == "4,614 sq ft", "an int 4614 gets the same shape")
    ck((P.get("Gamma Park") or {}).get("officeArea") == "4614.5", "a decimal is left as printed")
    ck((P.get("Delta Park") or {}).get("officeArea") == "approx 4614", "a figure with words is left as printed")

    canon, _ = run([rec("Alpha Park", "Northtown", areaUnit="sq ft"),
                    rec("Beta Park", "Southville", src="b.pdf", areaUnit="sq ft"),
                    rec("Metric Park", "Eastham", src="m.pdf", warehouseArea=9000, areaUnit="sq m",
                        officeArea="500")])
    m = by_park(canon).get("Metric Park") or {}
    ck(m.get("officeArea") == "500", f"a sq m record in a sq ft dataset keeps its officeArea ({m.get('officeArea')!r})")
    ck(isinstance(m.get("officeAreaVal"), (int, float)) and abs(m["officeAreaVal"] - 500 * 10.7639) < 2,
       f"...and its officeAreaVal is converted ({m.get('officeAreaVal')!r})")

    canon, _ = run([rec("Alpha Park", "Northtown", officeArea="4614")])
    ck((by_park(canon).get("Alpha Park") or {}).get("officeArea") == "4614",
       "no areaUnit on the supplier -> unchanged")
    canon, _ = run([rec("Alpha Park", "Northtown", src="t.xlsx", stype="xlsx", officeArea="4614", **sqft)])
    ck((by_park(canon).get("Alpha Park") or {}).get("officeArea") == "4614", "an xlsx supplier -> unchanged")

    # repairs compat: the in-flight vf answer written against the bare value still applies
    canon, rows = run([rec("Alpha Park", "Northtown", officeArea="4614", **sqft)])
    q = (canon or {}).get("properties", [{}])[0]
    vf = {"id": "vf-q_abc123", "property": {"key": match.match_key(q), "id": q.get("id")},
          "expect": {"officeArea": "4614"}, "set": {"officeArea": "4614 sq ft"},
          "why": "broker answered the value-format question", "verified_by": "broker"}
    rep = R.apply(json.loads(json.dumps(canon)), [vf],
                  provenance=[x for x in rows if x.get("record_type") == "property"])
    ck(len(rep["applied"]) == 1 and not rep["superseded"],
       f"a vf-shaped entry APPLIES after the reformat (applied {len(rep['applied'])}, "
       f"superseded {len(rep['superseded'])})")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} office_area_shape_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
