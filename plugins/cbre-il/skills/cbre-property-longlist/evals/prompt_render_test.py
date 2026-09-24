#!/usr/bin/env python3
"""prompt_render_test.py - the P1 prompts-as-files contract.

Asserts the four properties that make rendered dispatch prompts safe to hand out verbatim:
(1) every shipped template renders with no unresolved {{SLOT}} left behind;
(2) the load-bearing clauses of the reader contract survive rendering (the historically
    dropped rules - the pasted-short field list class of failure - are pinned by string);
(3) write_prompts() wipes stale prompts per pass (MOVING them to prompts/_done/, so an earlier
    deck can be re-dispatched) and names files <kind>[--<job>].md;
(4) the renderer is fail-loud in render() (unfilled slot / missing template raise) and
    fail-SOFT in write_prompts() (a bad job is skipped, never a crash) - the spine must
    survive any rendering failure.

Run: python evals/prompt_render_test.py"""
from __future__ import annotations

import os
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
    # D1: the reader agents were ~80% of a measured run's wall-clock and tool-call COUNT, not
    # page count, predicted a deck's duration. The one-batch rule already existed as a
    # permission and was not followed, so it is now an obligation with a self-check the
    # agent can apply mid-run (message count, not tool-call count, is what costs time).
    "NO IMAGE OPENED BEFORE IT",     # the visual-aid batch is an obligation, not a permission
    "MESSAGE count",                 # the calibrated self-check (well-run deck = 5 messages)
    # D13/D4: 5 of 8 broker answers never reached a card because the doubt named no field or
    # no options, and where options existed they were prose ('all three office lines
    # combined'), which the auto-repair wrote into the field with a null companion.
    "LEADS WITH THE FIGURE AND ITS UNIT",   # value-led options on an arithmetic field
    "NEVER offer a total you did not read",  # Python owns all arithmetic; no summed total
    # D6: two records from one deck shipped the same hero (page 1 / heroRef 0) while a
    # distinct aerial photograph sat in one record's own page pool
    "DO NOT SHARE A HERO",           # distinct heroes per record where the deck offers them
)
# the same pinning for the raster reader, which was never pinned before D1: it carries its own
# wording of the batch rule (bounded to FIVE full-page renders per message, with the reason)
# and the same D6 and D13/D4 rules, so a template edit there must fail here too
RASTER_NEEDLES = (
    "FLOOR, not a ceiling",
    "copied VERBATIM",
    "cluster_label",
    "NEVER convert",
    "Transcribe, never invent",
    "map_candidates",
    "Run context",
    "up to FIVE per message",        # D1: bounded batches, back to back
    "MESSAGE count",                 # D1: the calibrated self-check
    "LEADS WITH THE FIGURE AND ITS UNIT",   # D13/D4
    "NEVER offer a total you did not read",  # D4
    "DO NOT SHARE A HERO PAGE",      # D6, in raster terms (page_no is the hero binding)
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
    rr_tpl = (PR.TEMPLATE_DIR / "reader-raster.md").read_text(encoding="utf-8")
    rr = PR.render("reader-raster",
                   {s: f"<{s}>" for s in set(_SLOT_RE.findall(rr_tpl)) if s not in _AUTO})
    for needle in RASTER_NEEDLES:
        check(needle in rr, f"reader-raster carries the load-bearing clause: {needle!r}")
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
        common1 = work / "prompts" / "common" / "reader-text.md"
        stub1_bytes = f1[0].read_bytes()
        common1_bytes = common1.read_bytes() if common1.exists() else b""
        f2 = PR.write_prompts(work, [("g-images", None,
                                      {"WORK": "w", "REVIEWS_ROUND_DIR": "r"})])
        check(len(f2) == 1 and f2[0].name == "g-images.md",
              "singleton jobs named <kind>.md")
        check(not f1[0].exists(), "stale prompts from a prior pass are wiped")
        # ...wiped by MOVING them to prompts/_done/, so one deck can be re-dispatched later
        top = sorted(p.name for p in (work / "prompts").glob("*.md"))
        check(top == ["g-images.md"],
              f"prompts/ holds ONLY the new pass's job, so the handoff sees one pending job ({top})")
        done = work / "prompts" / "_done"
        done_stub, done_common = done / f1[0].name, done / "common" / "reader-text.md"
        repointed = stub1_bytes.replace(
            (str(common1.parent.resolve()) + os.sep).encode("utf-8"),
            (str(done_common.parent.resolve()) + os.sep).encode("utf-8"))
        check(bool(common1_bytes) and done_common.exists()
              and done_common.read_bytes() == common1_bytes,
              "the earlier pass's common half is in _done/common/, byte-identical")
        check(done_stub.exists() and repointed != stub1_bytes
              and done_stub.read_bytes() == repointed,
              "the earlier stub is in _done/, byte-identical but for its pointer, which now "
              "names _done/common/")
        ptr = [ln for ln in done_stub.read_text(encoding="utf-8").splitlines()
               if ln.strip().endswith("reader-text.md")] if done_stub.exists() else []
        check(len(ptr) == 1 and Path(ptr[0].strip()).is_file()
              and Path(ptr[0].strip()).read_bytes() == common1_bytes,
              f"...and that pointer resolves to the earlier common half ({ptr})")
        check(not list((work / "prompts" / "common").glob("*.md")),
              "prompts/common/ no longer holds the earlier pass's common half")

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

    # cluster-labels (workstream 1 item 1.4): the intake refinement rides exit 3 as a
    # rendered OPTIONAL job instead of an inline SKILL.md-prose judgement task
    cl = (PR.TEMPLATE_DIR / "cluster-labels.md").read_text(encoding="utf-8")
    for needle in ("VERBATIM", "OMITTED", "fabricate", "routing"):
        check(needle in cl, f"cluster-labels.md pins '{needle}'")

    print(f"\n{'PASS' if not fails else 'FAIL'} prompt_render_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
