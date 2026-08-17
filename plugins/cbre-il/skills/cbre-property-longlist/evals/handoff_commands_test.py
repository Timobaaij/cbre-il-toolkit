#!/usr/bin/env python3
"""handoff_commands_test.py - the exit-0 QA-window hand-off gives the orchestrator FULL,
copy-paste-ready deliver.py/final_gate.py commands, never an ellipsis or a bare word.

THE DEFECT: the hand-off message printed at "spine done" told the orchestrator to
"deliver" (no command) and run `final_gate.py ... --qa-state {work}` (a literal ellipsis).
Every value needed to build the real command - --canonical, --html, --ledger, --out-dir,
--slug, --filename for deliver.py; --canonical, --html, --deliverables, --reviews,
--qa-state for final_gate.py - is already a local variable a few lines above in the SAME
function (run.py's own internal deliver.py call at line ~3332 proves it). An orchestrator
without those flags memorised had to discover them by triggering argparse's "required
arguments" error on both scripts before finding the right invocation - avoidable friction on
every future run, not just this one.

Source-text pin (matching this suite's convention for pipeline-wiring checks, e.g.
gate1_automation_test.py): the hand-off string must contain the actual flag names for
BOTH scripts, and must not contain a literal ellipsis standing in for arguments. Offline."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    start = src.find('"(orchestrator: spine done')
    ck(start != -1, "run.py has the exit-0 QA-window hand-off message")
    # isolate just the _say_orchestrator(...) call so a match elsewhere in the file
    # (e.g. a different hand-off for a different exit code) cannot satisfy the pin
    end = src.find('return\n', start) if start != -1 else -1
    block = src[start:end] if start != -1 and end != -1 else ""

    ck("deliver.py --canonical" in block,
       "the hand-off gives the full deliver.py command, not the bare word 'deliver'")
    for flag in ("--canonical", "--html", "--ledger", "--out-dir", "--slug", "--filename"):
        ck(flag in block.split("deliver.py", 1)[-1].split("final_gate.py", 1)[0],
           f"deliver.py's hand-off command includes {flag}")

    ck("final_gate.py --canonical" in block,
       "the hand-off gives the full final_gate.py command, starting with --canonical")
    fg_part = block.split("final_gate.py", 1)[-1] if "final_gate.py" in block else ""
    for flag in ("--canonical", "--html", "--deliverables", "--reviews", "--qa-state"):
        ck(flag in fg_part, f"final_gate.py's hand-off command includes {flag}")

    ck("final_gate.py ..." not in block,
       "the old ellipsis placeholder for final_gate.py's arguments is gone")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
