#!/usr/bin/env python3
"""read_provenance_superseded_test.py - a merge value row marked SUPERSEDED BY REPAIR is still
provenance, so a strike's targets never depend on which pass marked it. (2026-09-26 test run,
fix 3.15, repairs.py half)

WHY THIS EXISTS. Merge's ledger retraction now also marks a merge VALUE row that a later repair
row replaced (record_type -> "superseded", conflict_note starting "SUPERSEDED BY REPAIR:"), so
the delivered ledger no longer shows 451,919 next to the repair's 439,363 as two live values.
`repairs.read_provenance` read ONLY record_type=property rows. Without this change, the same
`strike_from_source` would strike a field on the pass before the row was marked and skip it on
the pass after - the resumed-vs-full flip the module refuses everywhere else.

What this pins:
  * a marked value row (non-gap source_type + the prefix) is returned by read_provenance;
  * a `superseded` GAP row, and a `superseded` row with any other note, are not;
  * a live `property` row is returned as before; gap/repair/offspec rows are not;
  * a strike reaches the field through a marked row: the SAME fields are struck whether or not
    the row was marked.
The merge half (marking, restoring, the value-row pass) is pinned by the merge owner. Offline.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

FAILS = []
COLS = ["property_id", "record_type", "field", "value", "source_file", "source_locator",
        "source_type", "conflict_note"]


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def ledger(rows) -> Path:
    p = Path(tempfile.mkdtemp(prefix="cbre_rp_prov_")) / R.LEDGER_NAME
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})
    return p


def row(field, rt="property", st="pdf", note="", src="deck.pdf", value="1"):
    return {"property_id": "1", "record_type": rt, "field": field, "value": value,
            "source_file": src, "source_locator": "page 2", "source_type": st,
            "conflict_note": note}


MARK = (f"{R.SUPERSEDED_BY_REPAIR_PREFIX} merge wrote this value from deck.pdf; a later repair "
        f"row (repairs.json: rp-001) supplies '439,363', which is what the card ships. Kept so "
        f"the change is visible; NOT the live value. || was: two sources disagreed")


def main() -> int:
    print("== which rows read_provenance returns ==")
    p = ledger([
        row("park"),
        row("warehouseArea", rt="superseded", note=MARK, value="451919"),
        row("region", rt="superseded", st="gap", note=MARK, src="(none)"),
        row("epc", rt="superseded", note="SUPERSEDED: gap row replaced by a later value"),
        row("status", rt="gap", st="gap", src="(none)"),
        row("warehouseArea", rt="repair", st="repair", src="repairs.json", value="439363"),
        row("oddStructure", rt="offspec"),
    ])
    got = {(r["field"], r["record_type"]) for r in R.read_provenance(p)}
    ck(("park", "property") in got, "a live property row is returned (unchanged)")
    ck(("warehouseArea", "superseded") in got,
       "a merge value row marked SUPERSEDED BY REPAIR is still provenance")
    ck(("region", "superseded") not in got, "a superseded GAP row is not")
    ck(("epc", "superseded") not in got, "a superseded row with another note is not")
    ck(not any(rt in ("gap", "repair", "offspec") for _, rt in got),
       "gap / repair / offspec rows are still excluded")
    ck(R.read_provenance(p.parent / "absent.csv") is None, "no ledger -> None, as before")

    print()
    print("== a strike strikes the SAME fields before and after the row was marked ==")
    canonical = {"meta": {}, "properties": [
        {"id": 1, "park": "Alpha Park", "city": "Northtown", "developer": "Devco",
         "country": "ZZ", "status": "Available", "warehouseArea": 439363, "tenure": "Lease"}]}
    e = {"id": "rp-s", "property": {"key": "northtown|devco|alpha park", "id": 1},
         "strike_from_source": "deck.pdf", "why": "wrong deck", "verified_by": "analyst"}
    live = [row("warehouseArea", value="451919"), row("tenure", value="Lease")]
    marked = [row("warehouseArea", rt="superseded", note=MARK, value="451919"),
              row("tenure", value="Lease")]
    out = {}
    for name, rows in (("live", live), ("marked", marked)):
        c = json.loads(json.dumps(canonical))
        rep = R.apply(c, [e], provenance=R.read_provenance(ledger(rows)))
        out[name] = sorted((rep["applied"][0]["changed"] if rep["applied"] else {}).keys())
    ck(out["live"] == out["marked"] == ["tenure", "warehouseArea"],
       f"identical strike targets either way: {out}")

    print()
    if FAILS:
        print(f"READ PROVENANCE SUPERSEDED TEST: FAIL ({len(FAILS)})")
        return 1
    print("READ PROVENANCE SUPERSEDED TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
