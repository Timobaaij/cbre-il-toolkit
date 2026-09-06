#!/usr/bin/env python3
"""f24c_rederive_called_after_repairs_test.py - the spine CALLS merge's re-derivation right after
the repairs stage, an answer-bridge repair carries its derived twin, and a moved region-bind
input is named rather than left silently stale. (F24, run half)

MEASURED. `officeAreaVal` is derived by merge from `officeArea`; repairs run after merge. On the
live run the two properties whose office area came from a repair carried None in the twin, so
their modals printed a unit-less string and their Total GLA silently excluded the office.

WHAT IS PINNED:
  1. run.py calls `_rederive_after_repairs(canonical, ...)` inside the repairs stage, after
     `repairs.run` and before the projection stage, only when something applied;
  2. the helper re-derives the twin through merge (the real `merge.rederive_after_repairs`),
     writes canonical back, and is INERT (one stderr aside, no exception) when merge lacks it;
  3. a repair that moved a field the enrichment stamp hashes (`_ENRICH_INPUT_FIELDS`) yields a
     line naming the property, the repair and the field as a STALE region bind;
  4. `AnswerRepairs.add` on a twin SOURCE writes the twin in the same entry (a set carries the
     derived value; a clear unsets both), which is what repairs.py's stranding guard demands.

Offline. Run: python evals/f24c_rederive_called_after_repairs_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402
import run as RUN  # noqa: E402

FAILS: list = []
RSRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _canon(props: list) -> Path:
    w = Path(tempfile.mkdtemp(prefix="cbre_f24c_"))
    p = w / "canonical.json"
    p.write_text(json.dumps({"meta": {"client": "x"}, "properties": props}), encoding="utf-8")
    return p


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("1. the call sits in the repairs stage, after repairs.run, before projection")
    a = RSRC.find("_rrep = _repairs.run(work, write=True)")
    b = RSRC.find("_rederive_after_repairs(canonical, _rrep.get(\"applied\")", a)
    c = RSRC.find('_stage("projection")', a)
    ck(a != -1 and b != -1 and a < b < c, "repairs.run -> _rederive_after_repairs -> projection")
    ck('if _rrep.get("applied"):' in RSRC[a:b], "...and only when a repair applied")
    ck("ledger=ledger_csv" in RSRC[b:b + 200], "...passing the Source Ledger path for the twin's row")

    print("\n2. the helper re-derives through merge and writes canonical back")
    ck(hasattr(M, "rederive_after_repairs") and hasattr(M, "DERIVED_TWINS"),
       "merge carries rederive_after_repairs and DERIVED_TWINS (contract C2 landed)")
    cn = _canon([{"id": 1, "park": "Kestrel Reach", "areaUnit": "sq m",
                  "officeArea": "450 sq m", "officeAreaVal": 4500}])
    applied = [{"id": "ad-q_1-0", "property_id": 1,
                "changed": {"officeArea": {"from": "4,500 sq m", "to": "450 sq m"}}}]
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        lines = RUN._rederive_after_repairs(cn, applied)
    got = json.loads(cn.read_text(encoding="utf-8"))["properties"][0].get("officeAreaVal")
    ck(got == 450, f"officeAreaVal follows the repaired officeArea ({got})")
    ck(any("officeAreaVal" in ln for ln in lines), f"...and a line says so ({lines[:1]})")
    # absent function -> inert
    saved = M.rederive_after_repairs
    try:
        delattr(M, "rederive_after_repairs")
        cn2 = _canon([{"id": 1, "officeArea": "450 sq m", "officeAreaVal": 4500}])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            lines2 = RUN._rederive_after_repairs(cn2, applied)
        raised = False
    except Exception as exc:  # noqa: BLE001
        raised, lines2 = repr(exc), []
    finally:
        M.rederive_after_repairs = saved
    ck(not raised and "not available" in err.getvalue(),
       f"an older merge.py without the function is INERT with one stderr aside ({raised})")
    ck(json.loads(cn2.read_text(encoding="utf-8"))["properties"][0]["officeAreaVal"] == 4500,
       "...and touches nothing")

    print("\n3. a moved region-bind input is NAMED as stale, never silent")
    cn3 = _canon([{"id": 7, "lat": 1.0, "lng": 2.0}])
    lines3 = RUN._rederive_after_repairs(
        cn3, [{"id": "r-lat", "property_id": 7, "changed": {"lat": {"from": 0, "to": 1.0}}}])
    st = [ln for ln in lines3 if "STALE" in ln]
    ck(len(st) == 1 and "property 7" in st[0] and "r-lat" in st[0] and "lat" in st[0],
       f"one line names property, repair id and field ({st[:1]})")
    lines4 = RUN._rederive_after_repairs(
        cn3, [{"id": "r-docks", "property_id": 7, "changed": {"loadingDocks": {"from": 1, "to": 2}}}])
    ck(not any("STALE" in ln for ln in lines4),
       "a field the bind does not read (loadingDocks) raises no stale line")

    print("\n4. an answer-bridge repair on a twin SOURCE carries the twin")
    w = Path(tempfile.mkdtemp(prefix="cbre_f24c_ar_"))
    chan = RUN.AnswerRepairs(w, "unit-test")
    prop = {"id": 1, "park": "Kestrel Reach", "areaUnit": "sq m",
            "officeArea": "4,500 sq m", "officeAreaVal": 4500}
    ck(chan.add("t-set", prop, "officeArea", "450 sq m", "why"), "add() accepts the set")
    ck(chan.add("t-clr", prop, "officeArea", None, "why", clear=True), "add() accepts the clear")
    chan.flush()
    reps = json.loads((w / "repairs.json").read_text(encoding="utf-8-sig"))
    s = next(r for r in reps if r["id"] == "t-set")
    u = next(r for r in reps if r["id"] == "t-clr")
    ck(s["set"].get("officeArea") == "450 sq m" and s["set"].get("officeAreaVal") == 450,
       f"the set carries officeAreaVal derived by merge from the NEW value ({s['set']})")
    ck(sorted(u.get("unset") or []) == ["officeArea", "officeAreaVal"],
       f"the clear unsets both, so the derived number cannot outlive the withdrawn string "
       f"({u.get('unset')})")
    chan2 = RUN.AnswerRepairs(Path(tempfile.mkdtemp(prefix="cbre_f24c_wa_")), "unit-test")
    chan2.add("t-wa", {"id": 1, "warehouseArea": 125000}, "warehouseArea", 12500, "why")
    ck(chan2.list[0]["set"] == {"warehouseArea": 12500},
       "a field with no twin is written exactly as before")

    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F24C REDERIVE CALLED AFTER REPAIRS TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F24C REDERIVE CALLED AFTER REPAIRS TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
