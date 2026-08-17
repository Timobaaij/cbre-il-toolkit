#!/usr/bin/env python3
"""forbidden_cluster_test.py - the T1 forbidden-aware clustering contract.

Reconstructs the shipped BHM Dunajska Streda over-merge: a PDF and a PPTX of ONE deck, each
carrying TWO DISTINCT schemes (60,000 vs 53,000 sq m - an 11.7% gap, under the coordinate
net's 15%) that share one printed map pin and one developer. The pairwise tiers were always
right (the same-source pairs are `forbidden`); naive single-link closure fused all four
records through the cross-format `auto` links anyway, manufacturing 11 phantom source
disagreements in a delivered ledger. Asserts:
(1) the pairwise verdicts themselves (the fixture must actually reproduce the shape);
(2) dedupe yields TWO clusters of two, format-twin with format-twin;
(3) a corpus with no forbidden edge clusters exactly as before (back-compat).

Run: python evals/forbidden_cluster_test.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import match  # noqa: E402


def _rec(src, page, park, area, office):
    return {
        "park": park, "developer": "BHM", "city": "Dunajska Streda", "country": "SK",
        "warehouseArea": area, "officeArea": office, "areaUnit": "sq m",
        "lat": 47.990144, "lng": 17.574837,
        "__meta": {"source_file": src, "page_no": page},
    }


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    pdf7 = _rec("deck.pdf", 6, "BHM Dunajska Streda", 60000, 391)
    pdf8 = _rec("deck.pdf", 7, "BHM Dunajska Streda - Existing", 53000, 5200)
    pptx7 = _rec("deck.pptx", 6, "BHM Dunajska Streda", 60000, 391)
    pptx8 = _rec("deck.pptx", 7, "BHM Dunajska Streda - Existing", 53000, 5200)

    # (1) the fixture reproduces the live shape - if any of these drift, the test is void
    check(match.pair_class(pdf7, pdf8) == "forbidden",
          "same-source differing-area pair is forbidden (pdf7 vs pdf8)")
    check(match.pair_class(pptx7, pptx8) == "forbidden",
          "same-source differing-area pair is forbidden (pptx7 vs pptx8)")
    check(match.pair_class(pdf7, pptx7) == "auto",
          "the format twin of the SAME scheme auto-merges (pdf7 vs pptx7)")
    check(match.pair_class(pdf8, pptx8) == "auto",
          "the format twin of the SAME scheme auto-merges (pdf8 vs pptx8)")
    check(match.pair_class(pdf7, pptx8) == "auto",
          "the CROSS link fires too (identical pin, <=15% gap) - the bug's fuel")

    # (2) forbidden-aware dedupe: two clusters of two, never one of four
    clusters = match.dedupe([pdf7, pdf8, pptx7, pptx8])
    sizes = sorted(len(c) for c in clusters)
    check(sizes == [2, 2], f"dedupe yields two clusters of two (got sizes {sizes})")
    if sizes == [2, 2]:
        for cl in clusters:
            pages = {r["__meta"]["page_no"] for r in cl}
            srcs = {r["__meta"]["source_file"] for r in cl}
            check(len(pages) == 1 and len(srcs) == 2,
                  f"each cluster is one scheme across two formats (pages {pages})")

    # (3) back-compat: no forbidden edge -> identical clustering to the old closure
    clusters2 = match.dedupe([pdf7, pptx7])
    check(len(clusters2) == 1 and len(clusters2[0]) == 2,
          "a corpus with no forbidden edge still merges its restatement pair")
    lone = match.dedupe([pdf7, pdf8])
    check(sorted(len(c) for c in lone) == [1, 1],
          "a forbidden pair alone still never merges")

    print(f"\n{'PASS' if not fails else 'FAIL'} forbidden_cluster_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
