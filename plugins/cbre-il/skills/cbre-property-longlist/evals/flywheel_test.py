#!/usr/bin/env python3
"""flywheel_test.py - the P5 finding-to-gate flywheel contract.

Asserts: (1) findings recorded in ONE run never nudge (a single occurrence is not a
pattern); (2) the SAME finding class recorded from a SECOND distinct run nudges, naming the
class; (3) `flywheel` report flags recurring classes as CANDIDATE GATE; (4) the class key is
gate+field with a '-' fallback; (5) everything is best-effort (an unwritable ledger returns
[] rather than raising, so the QA round can never be blocked by the flywheel).

The ledger path is overridden via CBRE_FLYWHEEL_PATH so the test never touches the real
state/ dir.

Run: python evals/flywheel_test.py"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    with tempfile.TemporaryDirectory() as td:
        os.environ["CBRE_FLYWHEEL_PATH"] = str(Path(td) / "ledger.jsonl")
        import gate_runner as G

        # (4) class key derivation
        check(G.finding_class("G-honesty: property=2 field=motorway issue=ships tbd")
              == "G-honesty|motorway", "class key = gate|field")
        check(G.finding_class("G-visual: map view below the fold") == "G-visual|-",
              "class key falls back to gate|- when no field is named")

        cur = {"blocking": ["G-honesty: property=2 field=motorway issue=ships tbd though "
                            "slide 2 states it"],
               "advisory": ["G-visual: map view below the fold"]}

        # (1) first run: recorded, no nudge
        n1 = G.flywheel_append(Path(td) / "runA", cur)
        check(n1 == [], "first occurrence of a class never nudges")
        check((Path(td) / "ledger.jsonl").exists(), "ledger written")

        # same run again (a re-record): still no cross-RUN recurrence
        n1b = G.flywheel_append(Path(td) / "runA", cur)
        check(n1b == [], "re-recording within the same run never nudges")

        # (2) a second DISTINCT run: nudge naming the class
        n2 = G.flywheel_append(Path(td) / "runB", cur)
        check(bool(n2) and any("G-honesty|motorway" in n for n in n2),
              "a class recurring across two runs nudges, naming the class")

        # (3) the report flags it
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = G.cmd_flywheel(argparse.Namespace())
        out = buf.getvalue()
        check(rc == 0 and "CANDIDATE GATE" in out and "G-honesty|motorway" in out,
              "`flywheel` report flags the recurring class as CANDIDATE GATE")
        check("seen once" not in out.split("G-honesty|motorway")[0],
              "recurring classes sort above seen-once classes")

        # (5) best-effort: an unwritable ledger path (its parent is a FILE, so mkdir fails)
        # returns [] rather than raising
        blocker = Path(td) / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        os.environ["CBRE_FLYWHEEL_PATH"] = str(blocker / "sub" / "ledger.jsonl")
        try:
            n_bad = G.flywheel_append(Path(td) / "runC", cur)
            check(n_bad == [], "an unwritable ledger degrades to [] (never blocks the round)")
        except Exception as e:
            check(False, f"flywheel_append raised on an unwritable ledger: {e}")

    print(f"\n{'PASS' if not fails else 'FAIL'} flywheel_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
