#!/usr/bin/env python3
"""prompt_render_test.py - the P1 prompts-as-files contract.

Asserts the four properties that make rendered dispatch prompts safe to hand out verbatim:
(1) every shipped template renders with no unresolved {{SLOT}} left behind;
(2) the load-bearing clauses of the reader contract survive rendering (the historically
    dropped rules - the pasted-short field list class of failure - are pinned by string);
(3) write_prompts() wipes stale prompts per pass and names files <kind>[--<job>].md;
(4) the renderer is fail-loud in render() (unfilled slot / missing template raise) and
    fail-SOFT in write_prompts() (a bad job is skipped, never a crash) - the spine must
    survive any rendering failure.

Run: python evals/prompt_render_test.py"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import prompts_render as PR  # noqa: E402

_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_AUTO = {"SKILL_DIR", "CONTEXT"}

# the rules whose omission from hand-written prompts caused real shipped defects; a template
# edit that drops one of these must fail here, not in a client run
READER_NEEDLES = (
    "FLOOR, not a ceiling",          # the fields array is not a limit
    "copied VERBATIM",               # page_no verbatim (hero binding)
    "cluster_label",                 # routing name, never evidence
    "NEVER convert",                 # units: report, never convert
    "Transcribe, never invent",      # the honesty core
    "map_candidates",                # DMS/links go to the resolver
    "Run context",                   # the bounded additive-context slot
)
BLIND_NEEDLES = ("NEVER", "blind")   # both verify templates must assert independence


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    kinds = PR.template_kinds()
    check(len(kinds) >= 15, f"template set shipped ({len(kinds)} kinds)")

    # (1) every template renders clean with dummy slots
    unresolved = []
    for k in kinds:
        tpl = (PR.TEMPLATE_DIR / f"{k}.md").read_text(encoding="utf-8")
        slots = {s: f"<{s}>" for s in set(_SLOT_RE.findall(tpl)) if s not in _AUTO}
        out = PR.render(k, slots)
        if "{{" in out:
            unresolved.append(k)
    check(not unresolved, f"no unresolved slots after render (bad: {unresolved or 'none'})")

    # (2) load-bearing reader clauses survive rendering
    rt_tpl = (PR.TEMPLATE_DIR / "reader-text.md").read_text(encoding="utf-8")
    rt = PR.render("reader-text",
                   {s: f"<{s}>" for s in set(_SLOT_RE.findall(rt_tpl)) if s not in _AUTO})
    for needle in READER_NEEDLES:
        check(needle in rt, f"reader-text carries the load-bearing clause: {needle!r}")
    for k in ("tracker-verify", "match-verify"):
        tpl = (PR.TEMPLATE_DIR / f"{k}.md").read_text(encoding="utf-8")
        out = PR.render(k, {s: f"<{s}>" for s in set(_SLOT_RE.findall(tpl)) if s not in _AUTO})
        check(all(n.lower() in out.lower() for n in BLIND_NEEDLES),
              f"{k} asserts blindness/independence")

    # (3) write_prompts: naming + wipe-per-pass
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        f1 = PR.write_prompts(work, [("reader-text", "Bratislava__a0807f12_vision", {
            "DECK_NAME": "d.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": 3, "COUNTRY": "SK",
            "MANIFEST_PATH": "m.json", "OUTPUT_PATH": "o.json"})])
        check(len(f1) == 1 and f1[0].name == "reader-text--Bratislava__a0807f12_vision.md",
              "job files named <kind>--<job>.md")
        f2 = PR.write_prompts(work, [("g-images", None,
                                      {"WORK": "w", "REVIEWS_ROUND_DIR": "r"})])
        check(len(f2) == 1 and f2[0].name == "g-images.md",
              "singleton jobs named <kind>.md")
        check(not f1[0].exists(), "stale prompts from a prior pass are wiped")

        # (4a) fail-soft: an unknown kind and an under-filled job are skipped, never raised
        bad = PR.write_prompts(work, [("no-such-kind", None, {}),
                                      ("reader-text", "x", {})])
        check(bad == [], "write_prompts skips unrenderable jobs without raising")

    # (4b) fail-loud in render(): unfilled slot + missing template both raise
    try:
        PR.render("reader-text", {})
        check(False, "render() raises on an unfilled slot")
    except KeyError:
        check(True, "render() raises on an unfilled slot")
    try:
        PR.render("no-such-kind", {})
        check(False, "render() raises on a missing template")
    except (FileNotFoundError, OSError):
        check(True, "render() raises on a missing template")

    print(f"\n{'PASS' if not fails else 'FAIL'} prompt_render_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
