#!/usr/bin/env python3
"""skill_forbidden_moves_test.py - SKILL.md's forbidden moves are a TABLE, and no rule was lost
in the conversion. (fix 1.7, 2026-09-26 test run)

WHY. SKILL.md is read at the start of every session, so its forbidden-moves block was turned
from eight bullets plus wrapped continuation lines into a two-column table: the move in the
first cell (always starting "Do NOT"), the reason or the right move in the second. It reads
faster and costs fewer tokens. The risk of a reformat like this is a rule quietly dropped or
reworded. So this pins: the block is a table with that header; all eight rules survive, in
their original order, each in its own "Do NOT" row; the three phrases capture_contract_test
pins sit inside the table rows; and the trailer line still follows the table.
Offline. Run: python evals/skill_forbidden_moves_test.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FAILS: list = []

# One key per original bullet, in the original order (P6 1.7 row map).
RULE_KEYS = [
    "hand-write or edit `canonical.json`",
    "monkey-patch",
    "type the data in yourself",
    "invent or estimate",
    "exit-13 question yourself",
    "abbreviated field list",
    "accepted limitation",
    "hand-edit `work/extract/*.json`",
]
HEADER = "| Forbidden move (each was actually tried in a real run and is WRONG) | Why / do this instead |"
TRAILER = "When you feel the urge to improvise"


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    lines = skill.splitlines()

    print("1. the block is a table")
    hi = next((i for i, ln in enumerate(lines) if ln.startswith("| Forbidden move")), -1)
    ck(hi != -1, "SKILL.md has a '| Forbidden move' table header")
    ck(hi != -1 and lines[hi] == HEADER, "the header names both columns exactly")
    ck(hi != -1 and hi + 1 < len(lines) and lines[hi + 1].replace(" ", "") == "|---|---|",
       "the header is followed by a two-column separator row")
    rows = []
    if hi != -1:
        for ln in lines[hi + 2:]:
            if not ln.startswith("|"):
                break
            rows.append(ln)
    ck(len(rows) == len(RULE_KEYS), f"the table has one row per rule ({len(rows)} of {len(RULE_KEYS)})")
    ck(all(r.startswith("| Do NOT ") for r in rows), "every first cell starts 'Do NOT'")
    ck(all(r.count(" | ") >= 1 and r.rstrip().endswith("|") for r in rows),
       "every row has two cells")
    ck("**Forbidden moves (each was actually tried" not in skill,
       "the old bullet-list heading is gone (one form, not two)")

    print("\n2. every rule survives, in the original order, one per row")
    for i, key in enumerate(RULE_KEYS):
        ok = i < len(rows) and key in rows[i]
        ck(ok, f"row {i + 1} carries {key!r}")

    print("\n3. the capture_contract_test phrases live inside the table")
    body = "\n".join(rows)
    for phrase in ("Do NOT paste an abbreviated field list", "BLOCKING signal, not an accepted limitation",
                   "CAPTURE EVERY FIELD THE SOURCE STATES"):
        ck(phrase in body, f"table row carries {phrase!r}")
    ck("~100 false \"absent in all sources\" claims shipped" in body,
       "the evidence sentence for the capture rule is kept")

    print("\n4. the trailer still follows the table")
    after = "\n".join(lines[hi + 2 + len(rows):hi + 2 + len(rows) + 3]) if hi != -1 else ""
    ck(TRAILER in after, "'When you feel the urge to improvise' follows the table")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
