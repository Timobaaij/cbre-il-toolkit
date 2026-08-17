#!/usr/bin/env python3
"""gate1_automation_test.py - input-accounting and capture-symmetry run AUTOMATICALLY as
part of the pre-build gate batch; the orchestrator has nothing to remember.

THE DEFECT: both gates are fully mechanical and deterministic (capture-symmetry always
returns 0; input-accounting can return 1, exactly like every other pre-build gate), yet
`run.py`'s Stage-4 gate list never called either - SKILL.md and reference/gates.md instead
told the ORCHESTRATOR to run them "yourself alongside the batch", which is the exact kind of
manual step that gets skipped under time pressure. Every sibling mechanical gate in the same
spirit (self-check, validate-data, coverage, ...) is already wired into `run.py`'s own `g1`
list - these two belong there too.

Pins, source-text style (matching this suite's existing convention, e.g.
header_brochure_motorway_test.py's `"N.short_motorway(...)" in mg` check):
  1. run.py's Stage-4 section literally invokes both gates via run_gate(gate_runner, ...).
  2. the orchestrator-must-run-it-yourself language is gone from SKILL.md and gates.md.
  3. both gate names are still mentioned in SKILL.md/gates.md (capture_contract_test.py
     already pins that - this test does not weaken or duplicate that pin, only adds the
     "no longer manual" half).
Offline, no build.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    run_src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    # isolate the Stage-4 pre-build gate section so a match elsewhere in the file
    # (e.g. a docstring) cannot satisfy the pin by accident
    start = run_src.find("# Stage 4 - pre-build gates")
    end = run_src.find("# Stage 5 - build")
    ck(start != -1 and end != -1 and end > start,
       "run.py has a locatable Stage 4 -> Stage 5 pre-build gate section")
    stage4 = run_src[start:end] if start != -1 and end != -1 else ""

    ck('"input-accounting"' in stage4,
       "run.py's Stage-4 section calls the input-accounting gate itself")
    ck('"capture-symmetry"' in stage4,
       "run.py's Stage-4 section calls the capture-symmetry gate itself")
    ck("run_gate(gate_runner, \"input-accounting\"" in stage4,
       "input-accounting is invoked the same way as every other mechanical gate (run_gate(...))")
    ck("run_gate(gate_runner, \"capture-symmetry\"" in stage4,
       "capture-symmetry is invoked the same way as every other mechanical gate (run_gate(...))")
    # input-accounting joins g1 (it can block, like coverage/validate-data/...);
    # capture-symmetry is advisory-only but its OUTPUT still belongs in the scorecard, so it
    # is called via run_gate too (its return code is always 0, appending it is harmless).
    ck("g1.append(run_gate(gate_runner, \"input-accounting\"" in stage4,
       "input-accounting's result joins g1 (it can block a build, exactly like coverage etc.)")

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ck("ORCHESTRATOR-run" not in skill,
       "SKILL.md no longer tells the orchestrator to run these two by hand")
    ck("capture-symmetry" in skill, "SKILL.md still mentions capture-symmetry")
    ck("input-accounting" in skill, "SKILL.md still mentions input-accounting")

    gates = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8")
    ck("ORCHESTRATOR-RUN" not in gates,
       "reference/gates.md no longer marks G-inputs as orchestrator-run-by-hand")
    ck("G-inputs" in gates, "reference/gates.md still documents G-inputs")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
