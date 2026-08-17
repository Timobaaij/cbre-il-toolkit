#!/usr/bin/env python3
"""workdir_exclusion_test.py - the T1 own-output exclusion contract.

Putting `--work` INSIDE the inputs folder is the natural thing to do, and a live run that
did it ingested its own per-property `sources.csv` views as 31 phantom trackers. Asserts:
(1) with exclude_dir set (what intake.main now passes), nothing under the work dir is
    discovered, and the exclusion is DISCLOSED via inventory `excluded_workdir`;
(2) without exclude_dir the same layout IS ingested - proving the test bites;
(3) a work dir outside the inputs folder is a no-op (the common case is unchanged).

Run: python evals/workdir_exclusion_test.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import intake  # noqa: E402


def _all_rels(inv) -> str:
    import json
    return json.dumps(inv, ensure_ascii=False, default=str)


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    with tempfile.TemporaryDirectory() as td:
        folder = Path(td) / "inputs"
        (folder / "work" / "properties" / "01-park").mkdir(parents=True)
        (folder / "Options - Testville.pdf").write_bytes(b"%PDF-1.4 fake")
        (folder / "work" / "properties" / "01-park" / "sources.csv").write_text(
            "field,value\ncity,Testville\n", encoding="utf-8")
        (folder / "work" / "canonical.json").write_text("{}", encoding="utf-8")

        # (1) excluded: the work tree contributes nothing, and the exclusion is disclosed
        inv = intake.discover(folder, exclude_dir=folder / "work")
        blob = _all_rels(inv)
        check("sources.csv" not in blob and "canonical.json" not in blob,
              "nothing under the work dir is discovered when exclude_dir is set")
        check("Options - Testville.pdf" in blob,
              "real inputs are still discovered")
        excl = inv.get("excluded_workdir") or {}
        check(int(excl.get("files") or 0) == 2,
              f"the exclusion is disclosed (excluded_workdir.files == 2, "
              f"got {excl.get('files')})")

        # (2) the control: without exclude_dir the same layout IS ingested
        inv2 = intake.discover(folder)
        check("sources.csv" in _all_rels(inv2),
              "control: without exclude_dir the work dir's csv IS ingested "
              "(the test genuinely bites)")

        # (3) a work dir OUTSIDE the inputs folder changes nothing
        inv3 = intake.discover(folder, exclude_dir=Path(td) / "elsewhere_work")
        check("excluded_workdir" not in inv3 and "Options - Testville.pdf" in _all_rels(inv3),
              "an outside work dir is a no-op (common case unchanged)")

    print(f"\n{'PASS' if not fails else 'FAIL'} workdir_exclusion_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
