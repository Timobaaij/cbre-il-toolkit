#!/usr/bin/env python3
"""vision_output_lookup_test.py - vision_validate finds a vision file's deck by the file's OWN name
(2026-09-26 test run, fix 3.1 item 9).

THE DEFECT. vision_validate matched a `*_vision.json` to its manifest deck by folding the file stem
against the deck's cluster label. But the spine names outputs explicitly (B2) and hash-suffixes
them when two decks share a label (`<label>__<sha8>_vision.json`), and a relabelled deck keeps its
durable old output path (B64). Neither matches the label, so EVERY page-binding check for such a
file (page_no range, image_pages / plan_page / exclude_refs range, the source_file cross-check,
the text reconciliation) was silently skipped - exactly on the multi-deck-per-label runs where a
neighbour's photo is most likely to be bound.

What this pins (synthetic manifest + records):
  1. a hash-suffixed output is matched to its deck: an off-range page_no is an ERROR again;
  2. an output whose name no longer matches a relabelled deck's label is matched by `output`;
  3. a legacy manifest without `output` still matches by label (unchanged);
  4. two decks on one label are each checked against their OWN page set.

Run: python evals/vision_output_lookup_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import vision_validate as VV  # noqa: E402


def _rec(src: str, page_no: int) -> dict:
    return {"park": "Test Park", "__meta": {"source_file": src, "source_type": "pdf",
                                             "page_no": page_no, "image_pages": [],
                                             "plan_page": None,
                                             "prov": {"park": "page 1 (text interpretation)"}}}


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    def run(decks: list, files: dict) -> tuple:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "vision").mkdir()
            (work / "extract").mkdir()
            (work / "vision" / "manifest.json").write_text(json.dumps({"decks": decks}),
                                                             encoding="utf-8")
            for name, recs in files.items():
                (work / "extract" / name).write_text(json.dumps(recs), encoding="utf-8")
            return VV.validate(work)

    pages2 = [{"page_no": 0}, {"page_no": 1}]
    pages5 = [{"page_no": i} for i in range(5)]
    # 1 + 4: two decks share the label "Northtown"; outputs are hash-suffixed
    decks = [{"source_file": "a.pdf", "cluster_label": "Northtown", "pages": pages2,
              "output": "work/extract/Northtown__1a2b3c4d_vision.json"},
             {"source_file": "b.pdf", "cluster_label": "Northtown", "pages": pages5,
              "output": "work/extract/Northtown__5e6f7a8b_vision.json"}]
    e, _ = run(decks, {"Northtown__1a2b3c4d_vision.json": [_rec("a.pdf", 4)],
                       "Northtown__5e6f7a8b_vision.json": [_rec("b.pdf", 4)]})
    check(any("Northtown__1a2b3c4d" in x and "page_no 4" in x for x in e),
          "a hash-suffixed output is checked against ITS deck (page_no 4 off a 2-page deck)")
    check(not any("Northtown__5e6f7a8b" in x for x in e),
          "the label twin is checked against its OWN 5 pages (page_no 4 is fine there)")
    # 2: the deck was relabelled but its output keeps the old durable name
    e, _ = run([{"source_file": "c.pdf", "cluster_label": "Southport", "pages": pages2,
                 "output": "work/extract/Old Label_vision.json"}],
               {"Old Label_vision.json": [_rec("c.pdf", 7)]})
    check(any("Old Label_vision.json" in x and "page_no 7" in x for x in e),
          "a relabelled deck's durable output is still matched (by `output`)")
    # 3: a legacy manifest (no `output`) still matches by label
    e, _ = run([{"source_file": "d.pdf", "cluster_label": "East Midlands", "pages": pages2}],
               {"East_Midlands_vision.json": [_rec("d.pdf", 3)]})
    check(any("East_Midlands_vision.json" in x and "page_no 3" in x for x in e),
          "a legacy manifest without `output` still matches by the folded label")
    e, _ = run([{"source_file": "d.pdf", "cluster_label": "East Midlands", "pages": pages2}],
               {"East_Midlands_vision.json": [_rec("d.pdf", 1)]})
    check(not e, "an in-range page_no on the legacy path validates clean")

    print(f"\n{'PASS' if not fails else 'FAIL'} vision_output_lookup_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
