#!/usr/bin/env python3
"""f13_raster_exclude_refs_test.py - F13: raster mode required `exclude_refs` but could not
supply the indices it needs.

THE DEFECT (reported unprompted by a raster reader). The raster prompt inherited the
text-mode `__meta` rules including `exclude_refs` for decorative graphics, but a raster page
carries a page `image` only - no `candidates`, so no index space - and the agent correctly
identified a decorative graphic filling half a page and correctly reported it had no way to
exclude it. The prompt-side fix states that `exclude_refs` is UNAVAILABLE in raster mode and
names the fallback (a `decorative graphic:` line in `__meta.notes`, and leaving a
decoration-only page out of `image_pages`). The deeper fix - attaching candidates to raster
pages in the prep stage - lives outside the prompt files and is recorded in the contract.

What this pins:
(1) the raster manifest shape really has no candidate index space (vision_prep's page entry
    carries page_no / locator / image / reason only), so the statement is true, not a policy;
(2) the rendered raster prompt says exclude_refs is unavailable, says to OMIT it, and names
    both fallback levers;
(3) the contract's Raster mode section says the same, so the "inherits every text-mode
    `__meta` rule" sentence is qualified where it is read;
(4) the text-mode prompt still instructs exclude_refs by candidate index (the fix is scoped).

Run: python evals/f13_raster_exclude_refs_test.py"""
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

    # (1) the raster page entry has no candidate index space (source-text pin on vision_prep)
    vp = (ROOT / "helpers" / "vision_prep.py").read_text(encoding="utf-8", errors="replace")
    check('"candidates"' not in vp and "candidates_sheet" not in vp,
          "vision_prep.py page entries carry no `candidates` / `candidates_sheet` (raster has "
          "no index space; if this changes, re-decide the raster exclude_refs rule)")
    check('{"page_no": pno, "locator": f"page {pno + 1}",' in vp,
          "vision_prep.py page entry shape is page_no / locator / image / reason")

    # (2) the raster prompt
    raster = _render("reader-raster")
    check("`__meta.exclude_refs` is UNAVAILABLE in raster mode" in raster,
          "reader-raster: states exclude_refs is unavailable")
    check("OMIT the key" in raster, "reader-raster: says to omit the key rather than guess an index")
    check("no `candidates` index space" in raster,
          "reader-raster: says WHY (no candidate index space)")
    check("`__meta.notes` beginning\n  `decorative graphic:`" in raster
          or "`decorative graphic:`" in raster,
          "reader-raster: names the notes-line fallback a later repair can act on")
    check("out of `image_pages`" in raster,
          "reader-raster: names the image_pages lever for a decoration-only page")
    check("Never drop\n  a page that also carries a real photo" in raster
          or "also carries a real photo" in raster,
          "reader-raster: bounds the lever (never drop a page with a real photo)")
    check("never move `page_no`" in raster,
          "reader-raster: forbids moving page_no to dodge a graphic (hero binding)")
    check("`heroRef`/`planRef`/`exclude_refs` per the contract" not in raster,
          "reader-raster: no longer lists exclude_refs among the keys to set")
    check("except where it says otherwise" in raster,
          "reader-raster: the 'inherits every text-mode rule' sentence is qualified")

    # (3) the contract's raster section agrees
    contract = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    i = contract.find("### Raster mode")
    j = contract.find("## Tracker mode", i)
    sect = contract[i:j]
    check("`exclude_refs` is unavailable in raster\nmode" in sect
          or "`exclude_refs` is unavailable in raster" in sect,
          "interpretation.md Raster mode: says exclude_refs is unavailable")
    check("`decorative graphic:`" in sect and "`image_pages`" in sect,
          "interpretation.md Raster mode: names both fallback levers")
    check("attach `candidates` and a `candidates_sheet` to\nraster pages" in sect
          or "attach `candidates`" in sect,
          "interpretation.md Raster mode: records the deeper prep-stage fix")

    # (4) the text prompt still uses exclude_refs by index
    text = _render("reader-text")
    check("`exclude_refs` (decorative\n  graphics, by candidate index)" in text
          or "by candidate index" in text,
          "reader-text: still instructs exclude_refs by candidate index (fix is scoped to raster)")
    check("UNAVAILABLE" not in text, "reader-text: does not carry the raster-only statement")

    print(f"\n{'PASS' if not fails else 'FAIL'} f13_raster_exclude_refs_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
