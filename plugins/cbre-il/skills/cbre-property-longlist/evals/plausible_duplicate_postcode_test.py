#!/usr/bin/env python3
"""plausible_duplicate_postcode_test.py - fix 3.16 (2026-09-26 test run).

`merge.shipped_forbidden_conflicts` wrote "'A' and 'B' are plausibly the SAME building
described twice (shared identity, but a >15% size conflict ...)" for any cross-source pair that
is forbidden AND shares an identity token. Two schemes of one national brand in two towns (each
with its own stated postal code) drew that note, although two stated, DIFFERENT postal codes AND
two stated, different towns are two addresses.

Pins (synthetic records, shared name token, >15% size gap, different files):
  * different postcodes + different towns -> no note;
  * same town + different postcodes -> note kept;
  * one side without a postcode -> note kept;
  * 'qx41 7zp' vs 'QX417ZP' (equal after normalising) + different towns -> note kept;
  * a numeric-code market (12345 vs 67890, towns differ) -> suppressed;
  * an unknown town on one side -> note kept.

Run: python evals/plausible_duplicate_postcode_test.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import merge  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def rec(src, city, area, postcode=None):
    r = {"park": "Zephyr Park", "city": city, "country": "XX", "warehouseArea": area,
         "areaUnit": "sq m", "__meta": {"source_file": src, "source_type": "pdf"}}
    if postcode is not None:
        r["postcode"] = postcode
    return r


def notes(a, b):
    return merge.shipped_forbidden_conflicts([[a], [b]])


def main() -> int:
    base = notes(rec("a.pdf", "Northtown", 20000), rec("b.pdf", "Northtown", 40000))
    ck(len(base) == 1 and "plausibly the SAME building" in base[0],
       f"control: shared name + >15% size gap, no postcodes -> the note fires ({len(base)})")

    ck(notes(rec("a.pdf", "Northtown", 20000, "QX41 7ZP"),
             rec("b.pdf", "Southville", 40000, "QY9 2AB")) == [],
       "different postcodes + different towns -> no 'plausibly the SAME building' note")
    ck(len(notes(rec("a.pdf", "Northtown", 20000, "QX41 7ZP"),
                 rec("b.pdf", "Northtown", 40000, "QY9 2AB"))) == 1,
       "same town + different postcodes -> note kept")
    ck(len(notes(rec("a.pdf", "Northtown", 20000, "QX41 7ZP"),
                 rec("b.pdf", "Southville", 40000))) == 1,
       "one side without a postcode -> note kept (absence is not a disagreement)")
    ck(len(notes(rec("a.pdf", "Northtown", 20000, "qx41 7zp"),
                 rec("b.pdf", "Southville", 40000, "QX417ZP"))) == 1,
       "equal postcodes after normalising + different towns -> note kept")
    ck(notes(rec("a.pdf", "Northtown", 20000, "12345"),
             rec("b.pdf", "Southville", 40000, 67890)) == [],
       "numeric-code market (12345 vs 67890, towns differ) -> suppressed")
    ck(len(notes(rec("a.pdf", "Northtown", 20000, "12345"),
                 rec("b.pdf", "tbd", 40000, "67890"))) == 1,
       "an unknown town on one side -> note kept")
    ck(notes(rec("a.pdf", "Northtown", 20000), rec("a.pdf", "Northtown", 40000)) == [],
       "same-file pairs are still skipped (unchanged)")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} plausible_duplicate_postcode_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
