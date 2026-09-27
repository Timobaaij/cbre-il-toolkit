#!/usr/bin/env python3
"""ledger_value_superseded_test.py - fix 3.15, merge side (2026-09-26 test run).

`merge.retract_superseded_gap_rows` marked only GAP rows a repair superseded. Merge's own VALUE
row stayed live beside the repair row that replaced it (the real run: 451,919 next to 439,363),
so the Source Ledger contradicted the dashboard. The same function now also marks value rows.

Pins (synthetic CSV rows):
  * a value row + a repair SET row for the same key -> the value row becomes `superseded`, its
    note starts `SUPERSEDED BY REPAIR:`, names the repair, keeps the original note after
    " || was: ", and source_type / value are unchanged;
  * a second pass is a no-op (idempotent);
  * once the repair row is gone, the value row is RESTORED with its original note;
  * a CLEARED repair row does not mark; a set followed by a clear leaves the row live;
  * a T-translate row is never marked;
  * a derived row supersedes merge's officeAreaVal property row;
  * gap rows keep today's behaviour (marked by the repair, not by a marked value row);
  * repairs.read_provenance still returns the marked value row; the prefix constants agree;
  * trace-coverage over the file passes (a path round-trip through the real CSV writer).

Run: python evals/ledger_value_superseded_test.py"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

import merge  # noqa: E402
import repairs as R  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def row(pid, field, value, rt="property", st="pdf", src="deck.pdf", loc="page 2", note="",
        extractor="merge"):
    return {"property_id": str(pid), "record_type": rt, "field": field, "value": value,
            "source_file": src, "source_locator": loc, "source_type": st, "extractor": extractor,
            "confidence": "", "conflict_note": note, "verified": ""}


def rep(pid, field, value, rid="rp-001", cleared=False):
    note = (f"property-keyed repair {rid} CLEARED this field: why (was 'x'). The key is now ABSENT"
            if cleared else f"property-keyed repair {rid}: the brochure says so (was 'x')")
    return row(pid, field, "tbd" if cleared else value, rt="repair", st="repair",
               src="repairs.json", loc=rid, note=note, extractor="repairs.py")


def main() -> int:
    ck(merge.SUPERSEDED_BY_REPAIR_PREFIX == getattr(R, "SUPERSEDED_BY_REPAIR_PREFIX", None),
       "merge and repairs share the SUPERSEDED BY REPAIR: prefix")

    print("== a repair SET supersedes merge's value row ==")
    rows = [row(5, "warehouseArea", "451919", note="tracker figure"),
            row(5, "carParking", "tbd", st="gap", loc="absent in all sources"),
            rep(5, "warehouseArea", "439363"),
            rep(5, "carParking", "120", rid="rp-002")]
    lines = merge.retract_superseded_gap_rows(rows)
    v = rows[0]
    ck(v["record_type"] == "superseded" and v["conflict_note"].startswith("SUPERSEDED BY REPAIR:"),
       f"value row marked ({v['record_type']}, {v['conflict_note'][:40]!r})")
    ck("rp-001" in v["conflict_note"] and "'439363'" in v["conflict_note"]
       and v["conflict_note"].endswith(" || was: tracker figure"),
       "the note names the repair row, its value, and keeps the original note")
    ck(v["source_type"] == "pdf" and v["value"] == "451919", "source_type and value are unchanged")
    ck(rows[1]["record_type"] == "superseded" and rows[1]["conflict_note"].startswith("SUPERSEDED:"),
       "the gap row is still marked by its repair (today's behaviour)")
    ck(any("value row marked superseded" in ln for ln in lines), "a run-log line says so")
    snap = json.dumps(rows, sort_keys=True)
    ck(merge.retract_superseded_gap_rows(rows) == [] and json.dumps(rows, sort_keys=True) == snap,
       "a second pass is a no-op")

    print("== restore once the superseder is gone ==")
    rows2 = [r for r in rows if r["record_type"] != "repair"]
    lines = merge.retract_superseded_gap_rows(rows2)
    ck(rows2[0]["record_type"] == "property" and rows2[0]["conflict_note"] == "tracker figure",
       f"value row RESTORED with its original note ({rows2[0]['conflict_note']!r})")
    ck(any("value row RESTORED" in ln for ln in lines), "...and the run log says so")
    rows3 = [row(1, "epc", "C55")]
    merge.retract_superseded_gap_rows(rows3 + [rep(1, "epc", "B")])
    ck(rows3[0]["conflict_note"].endswith("NOT the live value."),
       "a row with no original note gets no ' || was: ' tail")
    merge.retract_superseded_gap_rows(rows3)
    ck(rows3[0]["record_type"] == "property" and rows3[0]["conflict_note"] == "",
       "...and restores to an empty note")

    print("== clears, translations, derived rows ==")
    rows = [row(2, "landlord", "Acme"), rep(2, "landlord", None, cleared=True)]
    merge.retract_superseded_gap_rows(rows)
    ck(rows[0]["record_type"] == "property", "a CLEARED repair row does not mark the value row")
    rows = [row(2, "landlord", "Acme"), rep(2, "landlord", "Beta", rid="rp-1"),
            rep(2, "landlord", None, rid="rp-2", cleared=True)]
    merge.retract_superseded_gap_rows(rows)
    ck(rows[0]["record_type"] == "property", "a set followed by a clear: the last word is the clear, no mark")
    rows = [row(3, "description", "Lager", extractor="T-translate"), rep(3, "description", "Warehouse")]
    merge.retract_superseded_gap_rows(rows)
    ck(rows[0]["record_type"] == "property", "a T-translate row is never marked")
    rows = [row(4, "officeAreaVal", "4614"),
            row(4, "officeAreaVal", "5000", rt=merge.DERIVED_RECORD_TYPE,
                loc="page 2 (derived from officeArea after repairs)",
                extractor="merge.rederive_after_repairs")]
    merge.retract_superseded_gap_rows(rows)
    ck(rows[0]["record_type"] == "superseded" and "derived row" in rows[0]["conflict_note"],
       "a derived row supersedes merge's officeAreaVal property row")
    ck(rows[1]["record_type"] == merge.DERIVED_RECORD_TYPE, "the derived row itself is untouched")

    print("== read_provenance and a real file round-trip ==")
    d = Path(tempfile.mkdtemp(prefix="cbre_ledger_val_"))
    lp = d / "source_ledger.csv"
    import ledger as L  # noqa: E402
    with open(lp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=L.COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in [row(5, "warehouseArea", "451919", note="tracker figure"),
                  row(5, "park", "Alpha Park"), row(5, "city", "Northtown"),
                  rep(5, "warehouseArea", "439363")]:
            w.writerow(r)
    merge.retract_superseded_gap_rows(lp)
    back = list(csv.DictReader(open(lp, encoding="utf-8-sig", newline="")))
    ck(back[0]["record_type"] == "superseded", "the path form rewrites the file with the mark")
    prov = R.read_provenance(lp) or []
    ck(any(p.get("field") == "warehouseArea" and p.get("value") == "451919" for p in prov),
       "repairs.read_provenance still returns the marked value row")
    ck(merge.retract_superseded_gap_rows(lp) == [], "the path form is idempotent too")
    canon = {"meta": {}, "properties": [{"id": 5, "park": "Alpha Park", "city": "Northtown",
                                         "warehouseArea": 439363}]}
    (d / "canonical.json").write_text(json.dumps(canon), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"), "trace-coverage",
                        str(d / "canonical.json"), "--ledger", str(lp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    ck(p.returncode == 0, f"trace-coverage passes over the marked ledger (rc {p.returncode}) {ascii(out[-200:]) if p.returncode else ''}")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} ledger_value_superseded_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
