#!/usr/bin/env python3
"""f02_batched_reads_test.py - F2: the reader ground rules multiplied round trips.

THE DEFECT. Every reader prompt carried "maximum three tool calls per message" and "one short
line of visible text before EVERY tool call". Measured per deck on a live run: 7 to 23 tool
calls at roughly 17 s each, the biggest deck 472 s. The dominant consumer was the per-page
`candidates_sheet` read, which is a FIXED set of independent reads known in full the moment
the agent has printed its deck's manifest entry - there is nothing to learn between one
page's read and the next. The fix lifts the three-call cap for exactly that batchable class
and nothing else: the pacing rule and the narration rule both stay, because both exist for
good reasons (a runaway agent, and a transcript a human can follow).

What this pins, on the RENDERED prompts (render() is the canonical single-file instruction):
(1) the text reader still carries both original rules, word for word;
(2) it names the exception - all pages' `candidates_sheet` and `render` reads in ONE message -
    and re-imposes the cap afterwards, so the exception cannot be read as a global lift;
(3) the narration rule is adapted for the batch (one line naming the batch), not dropped;
(4) the raster reader batches its page images too, but bounded (a full-page render is large);
(5) the contract file says the same thing where it describes `candidates_sheet`, so an
    orchestrator reading the contract directly sees one rule, not two.

Run: python evals/f02_batched_reads_test.py"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import prompts_render as PR  # noqa: E402

_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_AUTO = {"SKILL_DIR", "CONTEXT", "FIELD_REGISTRY", "COMMON_POINTER"}


def _render(kind: str) -> str:
    tpl = (PR.TEMPLATE_DIR / f"{kind}.md").read_text(encoding="utf-8")
    return PR.render(kind, {s: f"<{s}>" for s in set(_SLOT_RE.findall(tpl)) if s not in _AUTO})


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    text = _render("reader-text")
    raster = _render("reader-raster")

    # (1) both original rules survive in both readers
    for name, out in (("reader-text", text), ("reader-raster", raster)):
        check("Write one short line of visible text before EVERY tool call" in out,
              f"{name}: the narration rule survives")
        check("Maximum three tool calls per message" in out,
              f"{name}: the three-call cap survives")
        check("Tool-call budget 60" in out, f"{name}: the overall budget survives")

    # (2) the exception is named, scoped to the visual-aid reads, and the cap returns
    check("with ONE exception" in text, "reader-text: the cap has exactly one named exception")
    check("`candidates_sheet` and `render` thumbnail" in text,
          "reader-text: the exception is the per-page candidates_sheet + render reads")
    check("request ALL of\n   them in ONE message" in text or "in ONE message" in text,
          "reader-text: all pages' sheets are requested in ONE message")
    check("applies again to everything after that batch" in text,
          "reader-text: the cap is re-imposed after the batch (no global lift)")
    check("7 to 23 round trips" in text,
          "reader-text: the measured cost is stated, so the next editor knows why")
    check("(all pages in the ONE batched message of rule 2)" in text,
          "reader-text: the hero-pick reminder points at the batch instead of 'one call per page'")
    check("(one call per page)" not in text,
          "reader-text: the old per-page phrasing is gone")

    # (3) narration adapted, not dropped
    check("one line naming the batch (which pages) is that line" in text,
          "reader-text: the narration rule says how it applies to the batched message")

    # (4) raster batches page images, bounded
    check("with ONE exception: the page `image` reads" in raster,
          "reader-raster: the exception is the page image reads")
    check("up to FIVE per message" in raster,
          "reader-raster: page-image batches are bounded (a full-page render is large)")
    check("applies again to everything else" in raster,
          "reader-raster: the cap is re-imposed after the batch")

    # (5) the contract agrees
    contract = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    check("request EVERY page's sheet and `render` thumbnail in ONE message" in contract,
          "interpretation.md: the candidates_sheet paragraph says to batch all pages")
    check("lifts its per-message tool-call cap\n  for exactly this batch" in contract
          or "for exactly this batch" in contract,
          "interpretation.md: names the prompt's cap exception as being for this batch only")
    check("Read `candidates_sheet` once per page rather than opening each" in contract,
          "interpretation.md: the once-per-page (not once-per-candidate) rule survives")

    print(f"\n{'PASS' if not fails else 'FAIL'} f02_batched_reads_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
