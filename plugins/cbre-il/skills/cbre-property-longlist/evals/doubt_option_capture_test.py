#!/usr/bin/env python3
"""doubt_option_capture_test.py - a figure that lives ONLY in a doubt's options is signalled. (3.6a)

THE MEASURED CASE, 2026-09-26 test run. A deck itemised four warehouse compartments and printed no
warehouse-only total. The reader raised a doubt on `warehouseArea` whose four options were the
compartment lines ("62,324 sq ft (Main Warehouse)", ...) and captured none of them as a field. An
option is a CHOICE, not a capture: once the doubt is answered the figure has no Source Ledger row,
and Python cannot combine figures from a cited field that does not exist. `capture-symmetry` now
names such a doubt as an advisory [SIGNAL] and files it in the sidecar.

Pinned, against the real CLI (synthetic extract/*.json in a temp dir; every name invented):
  1. the compartment shape (4 options, no field holds them): ONE SIGNAL naming all 4, rc 0;
  2. a dual-unit option whose figure a field holds ('4,675 sq ft / 434 sq m' beside
     officeFirstFloorArea '4,675 sq ft'): no SIGNAL;
  3. options with no area-sized figure ('Unit 2', '3 cards', 'Q4 2026'): no SIGNAL;
  4. EU formatting ('62.324 m2' beside a field '62.324 m2'): captured, no SIGNAL;
  5. a figure held only as __meta.statedTotalArea counts as held; a 'combined:' option is skipped;
  6. the sidecar carries `doubt_uncaptured`; the gate stays advisory (rc 0) on a multi-source corpus;
  7. `_doubt_figures` never fuses 'Unit 2 62,324' into one number and drops bare years.
Offline. Run: python evals/doubt_option_capture_test.py"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import gate_runner as G  # noqa: E402

GATE = ROOT / "helpers" / "gate_runner.py"
FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _rec(src, park, doubts=None, statedTotal=None, **fields):
    meta = {"source_file": src, "page_no": 1, "source_type": "pdf"}
    if doubts is not None:
        meta["doubts"] = doubts
    if statedTotal is not None:
        meta["statedTotalArea"] = statedTotal
    return dict({"park": park, "city": "Northport"}, **fields, __meta=meta)


def _work(files: dict) -> Path:
    w = Path(tempfile.mkdtemp(prefix="cbre_doubt_")) / "work"
    (w / "extract").mkdir(parents=True)
    for name, recs in files.items():
        (w / "extract" / name).write_text(json.dumps(recs), encoding="utf-8")
    return w


def _gate(w):
    r = subprocess.run([sys.executable, str(GATE), "capture-symmetry", "--work", str(w)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


COMPARTMENTS = ["62,324 sq ft (Main Warehouse)", "34,617 sq ft (Dispatch Hall)",
                "18,050 sq ft (Cold Store)", "9,480 sq ft (Mezzanine Store)"]


def main() -> int:
    print("1. the compartment shape")
    r1 = _rec("quarry.pdf", "Quarry Fields", warehouseArea="124,471 sq ft", doubts=[
        {"subject": "Warehouse area printed only as compartments", "field": "warehouseArea",
         "options": COMPARTMENTS}])
    w = _work({"quarry_vision.json": [r1]})
    rc, out = _gate(w)
    sig = [ln for ln in out.splitlines() if "[SIGNAL]" in ln and "doubt on `warehouseArea`" in ln]
    ck(rc == 0 and len(sig) == 1, f"ONE doubt SIGNAL, gate advisory (rc {rc}, {len(sig)} line(s))")
    ck(bool(sig) and all(o in sig[0] for o in COMPARTMENTS) and "Quarry Fields" in sig[0]
       and "quarry.pdf" in sig[0], "...naming all four options, the record and the source file")
    ck(bool(sig) and "Re-dispatch" in sig[0] and "Run context" in sig[0],
       "...with the remedy (re-dispatch the deck's reader with the line in Run context)")
    side = w / "capture_symmetry.json"
    sj = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    du = sj.get("doubt_uncaptured") or []
    ck(len(du) == 1 and du[0].get("field") == "warehouseArea" and len(du[0].get("options")) == 4
       and du[0].get("signal") is True, "the sidecar carries it under `doubt_uncaptured`")

    print("\n2-5. captured options stay silent")
    cases = {
        "dual-unit option held by a field": _rec(
            "bar.pdf", "Barrow Point", officeFirstFloorArea="4,675 sq ft", doubts=[
                {"field": "officeArea", "subject": "two equal floors",
                 "options": ["4,675 sq ft / 434 sq m (Office First Floor)",
                             "4,675 sq ft / 434 sq m (Office Second Floor)"]}]),
        "options with no area-sized figure": _rec(
            "one.pdf", "One Park", doubts=[{"field": "unit", "subject": "which unit",
                                            "options": ["Unit 2", "3 cards", "Q4 2026"]}]),
        "EU formatting on both sides": _rec(
            "eu.pdf", "Parc Nord", warehouseArea="62.324 m2", doubts=[
                {"field": "warehouseArea", "subject": "basis",
                 "options": ["62.324 m2 (hall)", "combined: 70.000 m2"]}]),
        "a figure held as __meta.statedTotalArea": _rec(
            "tot.pdf", "Total Park", statedTotal=106645, doubts=[
                {"field": "warehouseArea", "subject": "basis",
                 "options": ["106,645 sq ft (GEA total)"]}]),
        "a numeric field value": _rec(
            "num.pdf", "Numeric Park", warehouseArea=51295, doubts=[
                {"field": "warehouseArea", "subject": "basis", "options": ["51,295 sq ft"]}]),
    }
    for label, rec in cases.items():
        f = G.doubt_uncaptured([rec])
        ck(f == [], f"{label}: no signal ({[x.get('options') for x in f]})")

    print("\n6. advisory on a multi-source corpus, sidecar keys kept")
    w2 = _work({"quarry_vision.json": [r1], "bar_vision.json": [cases["dual-unit option held by a field"]]})
    rc, out = _gate(w2)
    ck(rc == 0 and "STATUS: ALL-PASS" in out and "doubt-option SIGNAL" in out,
       f"rc 0, ALL-PASS, the summary counts the doubt-option SIGNAL (rc {rc})")
    sj2 = json.loads((w2 / "capture_symmetry.json").read_text(encoding="utf-8"))
    ck(all(k in sj2 for k in ("findings", "form_disagreements", "shadow_findings", "doubt_uncaptured")),
       "the sidecar keeps every earlier key beside `doubt_uncaptured`")

    print("\n7. the figure reader")
    figs = G._doubt_figures("Unit 2 62,324 sq ft")
    ck(62324.0 in figs and 2.0 not in figs, f"'Unit 2 62,324' yields 62324, never only a fused figure ({figs})")
    ck(G._doubt_figures("Q4 2026") == [] and G._doubt_figures("built 1998") == [],
       "bare years and small numbers are not figures")
    ck(G._doubt_figures("1 194 sq ft") == [1194.0], "a non-breaking-space thousands separator parses")
    ck(G.doubt_uncaptured([{"__meta": {"doubts": "not a list"}}, "junk", None]) == [],
       "malformed doubts are ignored, never a crash")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
