#!/usr/bin/env python3
"""f04_handoff_once_per_exit_test.py - a long handoff prints in FULL once per exit kind, and a
re-fire prints a two-line reminder, while the [pending] diagnosis keeps printing in full. (F4)

MEASURED. The exit-3 handoff is about 2,300 characters and reprinted verbatim on every re-fire
of the same exit, so the one thing that changed between passes (the [pending] lines naming why
the guard was still unsatisfied) sat under a wall of text the operator had already read twice.

WHAT IS PINNED:
  1. `run._handoff_once` returns the full text when the previous exit was a DIFFERENT code
     (or there was none), and a reminder of two lines plus the work/prompts/ path plus the
     caller's tail when the previous exit was the SAME code.
  2. The exit-3 interpretation handoff site routes its message through it, before printing.
  3. `_exit_round_trip` still prints EVERY [pending] line on a re-fire: the reminder must never
     shorten the diagnosis, which is the one thing a repeat handoff must not lose.

Offline, pure state. Run: python evals/f04_handoff_once_per_exit_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import run as RUN  # noqa: E402

FAILS: list = []
RSRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    w = Path(tempfile.mkdtemp(prefix="cbre_f04_"))
    full = "X" * 2300
    print("1. first fire of an exit kind: the full handoff")
    ck(RUN._handoff_once(w, 3, {}, "interp", full, tail=" T") == full,
       "no prior exit -> full text, verbatim")
    ck(RUN._handoff_once(w, 3, {"last": 6, "streak": 2}, "interp", full, tail=" T") == full,
       "a DIFFERENT prior exit code -> full text (per exit kind, not per run)")
    print("\n2. a re-fire of the SAME exit: two lines, the prompts path, the caller's tail")
    short = RUN._handoff_once(w, 3, {"last": 3, "streak": 1}, "interp", full, tail=" TAIL")
    ck(short != full and len(short) < 600, f"the reminder is short ({len(short)} chars)")
    ck(short.count("\n") == 1, f"...exactly two lines ({short.count(chr(10)) + 1})")
    ck(str(w / "prompts") in short, "...and names the work/prompts/ path")
    ck(short.endswith(" TAIL"), "...and keeps the caller's tail (setup prefix, prompts sentence)")
    ck("[pending]" in short, "...and points the reader at the [pending] lines")
    print("\n3. the exit-3 interpretation handoff is routed through it")
    i = RSRC.find('_handoff_once(work, 3, _attempts, "brochure/tracker interpretation", msg')
    j = RSRC.find("_say_orchestrator(msg)", i)
    k = RSRC.find('_exit_round_trip(work, 3, _attempts, "brochure/tracker interpretation"', i)
    ck(i != -1 and j != -1 and i < j < k,
       "run.py shortens the exit-3 message BEFORE printing it and before the exit")
    print("\n4. [pending] lines are printed in FULL on a re-fire, all of them")
    diag = [f"deck 'd{n}.pdf' (text) pending: its interpretation output does not exist yet: "
            f"{w / 'extract' / f'd{n}.json'}" for n in range(7)]
    (w / "attempts.json").write_text(json.dumps({"n": 1, "last": 3, "streak": 1}),
                                     encoding="utf-8")
    prior = json.loads((w / "attempts.json").read_text(encoding="utf-8"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            RUN._exit_round_trip(w, 3, prior, "brochure/tracker interpretation", diagnosis=diag)
        except SystemExit as e:
            code = e.code
    out = buf.getvalue()
    ck(code == 3, f"the exit code is untouched ({code})")
    ck(all(d in out for d in diag), f"all {len(diag)} [pending] lines are printed verbatim")
    ck(out.count("[pending]") == len(diag), f"...one [pending] tag per line ({out.count('[pending]')})")
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F04 HANDOFF ONCE PER EXIT TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F04 HANDOFF ONCE PER EXIT TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
