#!/usr/bin/env python3
"""cli_verbosity_test.py - run.py's stdout discipline and its verbosity flags.

B23: the tracker-yield block printed EVERY note (200 chars each) immediately above the
report that already lists them - in a real run ~24 full URLs. Judgement-bearing notes
(thin parse / rent_unit_assumed / area_unit_suspect / area_out_of_band /
semantic_disagreements) must stay LOUD and verbatim; linked-source notes collapse to a
count plus the report path.

B27: --quiet was a store_true default-off and there was no --verbose at all, while the
two commands SKILL.md actually hands the orchestrator omit the flag. Quiet is now the
DEFAULT, --verbose opts out, --quiet survives as an accepted no-op (extract_test passes
it into ~35 spine calls), and the orchestrator instruction blocks print to STDOUT in
both modes - they are the machine-readable product of the run, and this project's own
environment rule is that mcp__shell does not surface stderr.

Assertions are over the real module: the helper is called for its value AND run.py's
source is checked to prove the call site actually uses it (this project has twice
shipped a fix whose function was correct and whose wiring was dead). Offline, no I/O."""
from __future__ import annotations
import io
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import run as RUN  # noqa: E402

SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")

JUDGEMENT = [
    "big.xlsx [Sheet1]: 7/75 populated columns mapped; unmapped: a, b, c",
    "big.xlsx [Sheet1]: rent column states no currency or unit - shipped on the "
    "EUR/sq m/yr default (ASSUMED); confirm the real convention",
]
LINKS = [f"big.xlsx linked source (not embedded; fetch separately) at B{i}: "
         f"https://landlord.example.com/brochure/{i}.pdf" for i in range(1, 25)]


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # ---- B23: the [yield] stdout block ---------------------------------------
    notes = JUDGEMENT + LINKS
    link_ix = set(range(len(JUDGEMENT), len(notes)))
    fn = getattr(RUN, "_yield_stdout_lines", None)
    ck(callable(fn), "run._yield_stdout_lines exists")
    if callable(fn):
        lines = fn(notes, link_ix, "W/yield_report.md")
        blob = "\n".join(lines)
        for j in JUDGEMENT:
            ck(j[:120] in blob, f"judgement note still printed verbatim: {ascii(j[:44])}")
        ck("https://" not in blob, "no URL reaches stdout")
        ck(not any("linked source (not embedded" in l for l in lines),
           "no per-link line reaches stdout")
        ck(any(re.search(r"\b24\b.*linked source", l) for l in lines),
           "the 24 linked sources collapse to ONE counted line")
        ck(any("W/yield_report.md" in l for l in lines), "the report path is printed")
        ck(all(l.startswith("  ") for l in lines), "block keeps its two-space indent")
        ck(sum(1 for l in lines if "[yield]" in l) == len(JUDGEMENT) + 1,
           "[yield] tag kept, one line per judgement note plus the count")
        # a link-only run must still say something, and must still point at the report
        only = fn(LINKS, set(range(len(LINKS))), "W/yield_report.md")
        ck(len(only) == 2 and "https://" not in "\n".join(only),
           "a link-only yield prints exactly the count and the report path")
        # no links -> no count line at all (do not print a zero)
        none = fn(JUDGEMENT, set(), "W/yield_report.md")
        ck(not any("linked source" in l for l in none),
           "no linked sources -> no count line")

    # WIRING: the call site must actually use the helper (test the PATH, not the function)
    ck("_yield_stdout_lines(yield_notes" in SRC,
       "run.py calls _yield_stdout_lines at the yield block")
    ck('print(f"  [yield] {n[:200]}")' not in SRC,
       "the old per-note print loop is gone")
    ck("link_note_ix" in SRC, "linked-source notes are tagged as they are appended")

    # ---- B27: verbosity flags -------------------------------------------------
    ck(RUN.QUIET is True, "QUIET defaults to True (quiet is the failure-safe default)")
    ck("--verbose" in SRC, "--verbose exists")
    ck('"--quiet"' in SRC or "'--quiet'" in SRC, "--quiet is still accepted (no-op)")

    def _flags(argv):
        """Parse argv through run.py's OWN parser and report the resulting QUIET."""
        p = RUN._build_parser() if hasattr(RUN, "_build_parser") else None
        if p is None:
            return None
        ns = p.parse_args(argv)
        return RUN._resolve_quiet(ns) if hasattr(RUN, "_resolve_quiet") else None

    base = ["--folder", "F", "--work", "W", "--client", "C"]
    got = _flags(base)
    ck(got is True, "no flag -> quiet")
    ck(_flags(base + ["--verbose"]) is False, "--verbose -> not quiet")
    ck(_flags(base + ["--quiet"]) is True, "--quiet -> quiet (still accepted)")
    ck(_flags(base + ["--quiet", "--verbose"]) is False, "--verbose wins over --quiet")

    # the orchestrator instruction blocks are the product of the run: STDOUT, both modes
    ck(not re.search(r"NEXT STEP[^\n]*\n[^\n]*file=sys\.stderr", SRC),
       "no instruction block is routed to stderr")
    say = getattr(RUN, "_say_orchestrator", None)
    ck(callable(say), "run._say_orchestrator exists (single channel for handoff blocks)")
    if callable(say):
        for quiet in (True, False):
            o, e = io.StringIO(), io.StringIO()
            prev = RUN.QUIET
            RUN.QUIET = quiet
            try:
                with redirect_stdout(o), redirect_stderr(e):
                    say("HANDOFF-MARKER")
            finally:
                RUN.QUIET = prev
            ck("HANDOFF-MARKER" in o.getvalue(),
               f"instruction block reaches stdout (QUIET={quiet})")
            ck("HANDOFF-MARKER" not in e.getvalue(),
               f"instruction block does NOT go to stderr (QUIET={quiet})")

    if fails:
        print(f"\nCLI VERBOSITY TEST: FAIL ({len(fails)})")
        return 1
    print("\nCLI VERBOSITY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
