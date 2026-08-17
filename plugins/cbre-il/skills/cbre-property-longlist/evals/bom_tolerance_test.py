#!/usr/bin/env python3
"""bom_tolerance_test.py - the T1 BOM-tolerant read contract.

A PowerShell-writing orchestrator produces UTF-8 files with a BOM, and a BOM'd
match_decisions.json once read as "absent" to the exit-10 guard - five silent re-emissions
before the cause was found. Every read of an orchestrator/agent-written JSON now decodes
utf-8-sig (which reads plain UTF-8 byte-identically). Asserts the three highest-risk
readers accept a BOM'd file: run._load_match_decisions, run._load_records (vision outputs)
and _common.load_json.

Run: python evals/bom_tolerance_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import _common as C  # noqa: E402
import run as R  # noqa: E402


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

        # a BOM'd match_decisions.json must read as ANSWERED, not absent
        (work / "match_decisions.json").write_text(
            json.dumps({"abc123": {"verdict": "different", "reason": "eval"}}),
            encoding="utf-8-sig")
        md = R._load_match_decisions(work)
        check(bool(md) and "abc123" in md,
              "a BOM'd match_decisions.json reads as answered, not absent")

        # a BOM'd vision output must still yield its records
        vf = work / "X_vision.json"
        vf.write_text(json.dumps([{"park": "P", "__meta": {"source_file": "x.pdf"}}]),
                      encoding="utf-8-sig")
        recs = R._load_records(vf)
        check(len(recs) == 1 and recs[0].get("park") == "P",
              "a BOM'd vision output still yields its records")

        # the shared loader tolerates a BOM, and plain UTF-8 is byte-identical behaviour
        (work / "plain.json").write_text('{"a": 1}', encoding="utf-8")
        (work / "bom.json").write_text('{"a": 1}', encoding="utf-8-sig")
        check(C.load_json(work / "plain.json") == C.load_json(work / "bom.json") == {"a": 1},
              "_common.load_json reads plain and BOM'd UTF-8 identically")

    print(f"\n{'PASS' if not fails else 'FAIL'} bom_tolerance_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
