#!/usr/bin/env python3
"""as_shipped_compat_test - fix 3.18 compat read (2026-09-26 regression run).

A count-affecting doubt asked BEFORE clarify recorded `as_shipped` keeps only the reader's short
default in `if_unanswered` ('proceeds with: one combined record (as shipped)'), while the broker
picked the longer OPTION that default abbreviates. On the regression copy of a real run that
answer kept printing a "still RECORDED ONLY" nag on every pass although it changed nothing.

Pins:
  1. old title (no `as_shipped` key): an answer carrying every word of a multi-word default is
     as-shipped; a different option is not; a one-word default never triggers the word test;
  2. new title (records `as_shipped`): the strict equality rules alone decide (no word test);
  3. the exact-equality and AS_SHIPPED_TOKENS paths still hold.
Synthetic strings only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
import clarify as C  # noqa: E402

FAILS = 0


def ck(cond, msg):
    global FAILS
    print(("[PASS] " if cond else "[FAIL] ") + msg)
    if not cond:
        FAILS += 1


old = {"if_unanswered": "proceeds with: one combined record (as shipped)"}
ck(C.answer_is_as_shipped(old, "one combined record for the whole 12,000 sq m campus (as shipped)"),
   "old title: the longer option the default abbreviates is as-shipped")
ck(not C.answer_is_as_shipped(old, "three separate records: Unit A 4,000 sq m, Unit B 8,000 sq m"),
   "old title: a different option is NOT as-shipped")
ck(C.answer_is_as_shipped(old, "one combined record (as shipped)"),
   "old title: the default itself is as-shipped (equality path)")

one_word = {"if_unanswered": "proceeds with: whole"}
ck(not C.answer_is_as_shipped(one_word, "split into two units, not the whole building"),
   "a one-word default never triggers the word-subset test")

new = {"if_unanswered": "proceeds with: one combined record (as shipped)",
       "as_shipped": "one combined record (as shipped)"}
ck(not C.answer_is_as_shipped(new, "one combined record for the whole campus (as shipped)"),
   "new title: strict equality only (no word test)")
ck(C.answer_is_as_shipped(new, "one combined record (as shipped)"),
   "new title: the recorded as_shipped option is as-shipped")
ck(C.answer_is_as_shipped({}, "keep as is"), "AS_SHIPPED_TOKENS still recognised")
ck(not C.answer_is_as_shipped(old, ""), "an empty answer is never as-shipped")

print(f"\nAS SHIPPED COMPAT TEST: {'PASS' if not FAILS else 'FAIL'}"
      + (f" ({FAILS})" if FAILS else ""))
sys.exit(1 if FAILS else 0)
