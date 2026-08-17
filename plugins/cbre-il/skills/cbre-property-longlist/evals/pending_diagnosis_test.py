#!/usr/bin/env python3
"""pending_diagnosis_test.py - the P3 guard self-diagnosis contract.

A repeat-handoff exit must EXPLAIN itself: _exit_round_trip(diagnosis=[...]) always persists
the caller's exact pending predicates to work/pending_diagnosis.json, and prints them as
[pending] lines once the SAME exit code repeats (streak >= 2) - the point at which the
orchestrator's answer was not recognised and guessing at the predicate becomes code
archaeology. Also pins backward compatibility: the parameter is optional, and a first
emission (streak 1) stays quiet on stdout.

Run: python evals/pending_diagnosis_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import run  # noqa: E402  (top-level imports are stdlib-only by design)


def _call(work, code, prior, diagnosis):
    buf = io.StringIO()
    rc = None
    with contextlib.redirect_stdout(buf):
        try:
            run._exit_round_trip(work, code, prior, "eval", diagnosis=diagnosis)
        except SystemExit as e:
            rc = e.code
    return rc, buf.getvalue()


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        diag = ["deck 'X.pdf' (text) pending: its interpretation output does not exist yet: "
                "work/extract/X_vision.json"]

        # first emission of this code (prior last differs): file written, stdout quiet
        rc, out = _call(work, 3, {"n": 1, "last": 0, "streak": 0}, diag)
        check(rc == 3, "exit code preserved")
        pd = json.loads((work / "pending_diagnosis.json").read_text(encoding="utf-8"))
        check(pd.get("exit") == 3 and pd.get("pending") == diag,
              "pending_diagnosis.json persists the exact predicates on every emission")
        check("[pending]" not in out, "streak 1 stays quiet on stdout (normal handoff)")

        # the SAME code repeating (streak 2): predicates print as [pending] lines
        rc, out = _call(work, 3, {"n": 2, "last": 3, "streak": 1}, diag)
        check(rc == 3 and "[pending]" in out and "X.pdf" in out,
              "streak >= 2 prints the exact pending predicates")

        # capping: >20 items print 20 + a pointer to the file
        many = [f"item {i} pending: no answer for id q-{i}" for i in range(30)]
        rc, out = _call(work, 13, {"n": 3, "last": 13, "streak": 1}, many)
        check(out.count("[pending]") == 21 and "and 10 more" in out,
              "long diagnosis lists cap at 20 printed + a pointer")
        pd = json.loads((work / "pending_diagnosis.json").read_text(encoding="utf-8"))
        check(len(pd.get("pending") or []) == 30,
              "the persisted file always holds the full list")

        # backward compatibility: no diagnosis argument -> old behaviour, no crash, no file churn
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                run._exit_round_trip(work, 9, {"n": 4, "last": 9, "streak": 1}, "eval")
            except SystemExit as e:
                check(e.code == 9, "diagnosis parameter is optional (back-compat)")
        check("[pending]" not in buf.getvalue(),
              "no diagnosis -> no [pending] output (unchanged behaviour)")

    print(f"\n{'PASS' if not fails else 'FAIL'} pending_diagnosis_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
