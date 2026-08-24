#!/usr/bin/env python3
"""handoff_commands_test.py - the QA window's hand-offs are complete and loop-driven.

HISTORY. This eval originally pinned the exit-0 "spine done" hand-off to carry FULL
copy-paste deliver.py/final_gate.py commands (an earlier version printed a bare
"deliver" and a literal `final_gate.py ...` ellipsis, forcing the orchestrator to
discover the flags via argparse errors). Workstream 1 item 1.2 made that defect
STRUCTURALLY impossible: the spine now runs qa-round record, deliver and final_gate
ITSELF, and the QA window is exit-code driven (14 = reviews missing, 15 = blocking
findings unresolved, 0 = final_gate green). What this eval pins is therefore the NEW
contract - and that no trace of the old prose-ordered hand-off survives to contradict
it.

Source-text pin (this suite's convention for pipeline-wiring checks). Offline."""
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
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")

    # the old prose-ordered hand-off is GONE - two contradictory contracts must not coexist
    ck('"(orchestrator: spine done' not in src,
       "the old 'spine done' prose hand-off is gone from run.py")

    # exit 14: names the rendered prompts and demands verbatim dispatch
    i14 = src.find("independent QA review needed (exit 14)")
    ck(i14 != -1, "run.py has the exit-14 hand-off")
    b14 = src[i14:i14 + 900]
    ck("VERBATIM" in b14 and "prompts" in b14,
       "exit-14 hand-off points at the rendered prompts, dispatched verbatim")
    ck("_exit_round_trip(work, 14" in src,
       "exit 14 goes through the round-trip guard (pending diagnosis + streak detection)")

    # exit 15: carries the FULL qa-round resolve command, never a bare word
    i15 = src.find("(exit 15)")
    ck(i15 != -1, "run.py has the exit-15 hand-off")
    b15 = src[i15:i15 + 900]
    ck("resolve --work" in b15 and "--id <id> --because" in b15,
       "exit-15 hand-off gives the full qa-round resolve command (with --id/--because)")
    ck("_exit_round_trip(work, 15" in src,
       "exit 15 goes through the round-trip guard")

    # the spine RUNS the tail itself - deliver re-folds advisories, final_gate is the
    # backstop, and its reasons survive quiet mode via the report file
    tail = src[src.find("QA WINDOW, LOOP-DRIVEN"):]
    ck("QA WINDOW, LOOP-DRIVEN" in src, "the loop-driven QA tail exists")
    ck('call(gate_runner, "qa-round", "record"' in tail,
       "the spine records the QA round itself")
    ck("qa_round_number(work) == 0" in tail,
       "record is guarded against round inflation (self-opening record)")
    ck('call(deliver, "--canonical"' in tail,
       "the spine re-delivers itself (advisories folded)")
    ck("run_gate(_final_gate_mod" in tail,
       "the spine runs final_gate itself, captured via run_gate")
    ck("final_gate_report.md" in tail,
       "a red final gate names work/final_gate_report.md (quiet mode cannot swallow it)")
    ck("sys.exit(7)" in tail, "a red final gate is exit 7")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
