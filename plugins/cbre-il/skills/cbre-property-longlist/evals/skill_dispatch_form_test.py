#!/usr/bin/env python3
"""skill_dispatch_form_test.py - SKILL.md sanctions the POINTER dispatch, points at the model
tiers, and every card note added on 2026-09-26 names something the code really has.
(fixes 1.8, 2.8 doc lines, 1.11 exit-3 row, 1.3 SKILL line, model-tier pointer; 2026-09-26 test run)

WHY. The card only sanctioned PASTING a rendered prompt, which re-emits 2-3 k output tokens per
sub-agent. The real run dispatched all 32 agents with a one-line pointer to the rendered file
and none deviated, so step 3 now sanctions both forms: (a) POINTER, the preferred one, with the
exact sentence to send, and (b) PASTE. The rendered file stays the whole prompt either way. The
exit rows that dispatch say so. Pinned here: the pointer sentence is present in full, on one
line (so it can be copied as is); VERBATIM survives in exits 3 and 14; each dispatching row
names the step-3 form; step 3 points at the gates.md model-tier note that exists.

The same round added one-clause notes to the card for new behaviour (exit-13 question kinds,
reader-repair prompts, per-file master-list rows, `--batch`, the strict-alias ack, the host
tool cap, `--rebuild-media`, the print digests). A note that names a key, file, flag or kind
the code does not have misleads every session that reads it, so each one is checked against
the code here, not only for presence. Offline. Run: python evals/skill_dispatch_form_test.py"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

FAILS: list = []

POINTER = ("Your complete instructions are the verbatim contents of <absolute path of the rendered "
           "file>. Read that file in full first and follow it exactly; nothing in this message adds "
           "to or overrides it. If you cannot open it, stop and say so.")
FORM = "pointer or paste, step 3"


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _row(md: str, n: int) -> str:
    return next((ln for ln in md.splitlines() if ln.startswith(f"| {n} |")), "")


def _step(md: str, n: int) -> str:
    m = re.search(rf"^{n}\. \*\*.*?(?=^\d+\. \*\*|\Z)", md, re.S | re.M)
    return m.group(0) if m else ""


def main() -> int:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    gates = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8")
    env = (ROOT / "reference" / "environment.md").read_text(encoding="utf-8")
    maint = (ROOT / "docs" / "MAINTENANCE.md").read_text(encoding="utf-8")
    run_src = (HELPERS / "run.py").read_text(encoding="utf-8")
    step3 = _step(skill, 3)

    print("1. step 3 sanctions the pointer form (fix 1.8)")
    ck(bool(step3), "SKILL.md has a numbered step 3")
    ck("POINTER" in step3 and "PASTE" in step3, "step 3 names both forms, POINTER and PASTE")
    ck(any(POINTER in ln for ln in skill.splitlines()),
       "the exact pointer sentence is present, on ONE line (copyable as is)")
    ck("that file IS the sub-agent's prompt, VERBATIM" in step3,
       "the rendered file stays the whole prompt in either form")
    ck("'Run context' heading" in step3 and "never in the dispatch message" in step3,
       "run facts go under 'Run context' in the file, never in the dispatch message")
    ck("The pointer form (SKILL.md step 3) satisfies this" in gates,
       "gates.md rule 2 points back at step 3, which now carries the form")

    print("\n2. the dispatching exit rows name the form; VERBATIM survives")
    for n in (3, 9, 10, 14, 17):
        ck(FORM in _row(skill, n), f"exit-{n} row names '{FORM}'")
    ck("VERBATIM" in _row(skill, 3) and "VERBATIM" in _row(skill, 14),
       "exits 3 and 14 still say VERBATIM")
    ck("each file is that agent's VERBATIM prompt" in _row(skill, 14),
       "exit 14 keeps 'each file is that agent's VERBATIM prompt'")

    print("\n3. model tiers and the host tool cap (pointers that must resolve)")
    ck('"Sub-agent model tiers"' in step3 and "reference/gates.md" in step3,
       "step 3 points at gates.md 'Sub-agent model tiers'")
    ck("**Sub-agent model tiers" in gates and "ONLY where the host lets you pick" in gates,
       "...and gates.md carries that note, advisory-only")
    ck("reference/environment.md" in step3, "step 3 points at environment.md for the host tool cap")
    try:
        import prompts_render as PR
        names = tuple(PR.HOST_CAP_ENV)
    except Exception as e:  # pragma: no cover - reported as a failure, never a crash
        names = ()
        ck(False, f"prompts_render imports ({type(e).__name__}: {e})")
    ck(bool(names) and all(n in env for n in names),
       f"environment.md names every env var prompts_render reads {names!r}")

    print("\n4. every new card note names what the code has")
    r3 = _row(skill, 3)
    ck("you need not read it to dispatch" in r3, "exit 3: the orchestrator need not read the contract (1.11)")
    ck("not the dispatching orchestrator" in run_src,
       "...matching run.py's contract_reads line")
    ck("inputs.cluster_labels: agent" in r3, "exit 3: cluster labels only on opt-in (1.3)")
    try:
        import intake as IN
        opted = IN.cluster_labels_opted_in({"inputs": {"cluster_labels": "agent"}})
        not_opted = IN.cluster_labels_opted_in({})
        ck(opted and not not_opted, "...and intake opts in on exactly that key")
        _skips = IN.CLUSTER_SKIP if isinstance(IN.CLUSTER_SKIP, (tuple, list)) else (IN.CLUSTER_SKIP,)
        ck("intake_clusters.SKIP" in _skips and "work/intake_clusters.SKIP" in r3,
           "...and the .SKIP sentinel the card names is one intake reads")
    except Exception as e:
        ck(False, f"intake opt-in helpers exist ({type(e).__name__}: {e})")
    ck("reader-repair--" in r3 and "RESUME" in r3 and "never re-dispatch the full deck" in r3,
       "exit 3: a reader-repair prompt resumes the reader, never a full re-dispatch")
    ck((ROOT / "prompts" / "reader-repair.md").exists() and '"reader-repair"' in run_src,
       "...and the reader-repair prompt kind exists")

    r13 = _row(skill, 13)
    try:
        import clarify as CQ
        kinds = set(getattr(CQ, "KINDS", {}) or {})
    except Exception as e:
        kinds = set()
        ck(False, f"clarify imports ({type(e).__name__}: {e})")
    for k in ("combine_policy", "not_available", "arithmetic_basis"):
        ck(f"`{k}`" in r13 and k in kinds, f"exit 13 names question kind {k!r}, which clarify defines")
    ck("arithmetic_basis" in set(getattr(CQ, "BLOCKING_KINDS", ()) or ()) if kinds else False,
       "...and arithmetic_basis is blocking, as the card says")
    ck("answered as shipped closes with no change" in r13 and "re-reads that ONE deck" in r13,
       "exit 13: a count doubt closes as shipped, otherwise re-reads one deck (3.18)")

    r6 = _row(skill, 6)
    ck("strict_alias_ok=<pid>:<key>" in r6, "exit 6: the strict-alias ack")
    ck('"strict_alias_ok"' in (HELPERS / "gate_runner.py").read_text(encoding="utf-8"),
       "...and gate_runner's ack key is spelled the same")
    ck("BLANK title" in r6 and "bare count" in r6, "exit 6: the blank-title block and the value-format exemptions")

    r15 = _row(skill, 15)
    ck("--batch <file.json>" in r15 and "fix one only when it is one edit" in r15,
       "exit 15: the --batch form beside the kept advisory rule (2.8)")
    ck("--batch <file.json>" in _qa_window(skill), "QA-window step 2 names --batch too")
    ck('"--batch"' in (HELPERS / "gate_runner.py").read_text(encoding="utf-8"),
       "...and gate_runner defines --batch")

    r17 = _row(skill, 17)
    ck("deck FILE" in r17 and "work/email_bodies.md" in r17,
       "exit 17: rows per deck FILE; the agent reads work/email_bodies.md")
    try:
        import master_list as ML
        ck(ML.EMAIL_BODIES == "email_bodies.md", "...the file name master_list writes")
    except Exception as e:
        ck(False, f"master_list imports ({type(e).__name__}: {e})")

    ck("--rebuild-media" in skill
       and "--rebuild-media" in (HELPERS / "project_properties.py").read_text(encoding="utf-8"),
       "correcting data: --rebuild-media exists in project_properties.py")
    m = re.search(r'^PRINT_DIGESTS\s*=\s*"([^"]+)"', run_src, re.M)
    ck(bool(m) and f"work/{m.group(1)}" in skill, "output discipline names run.py's print-digest file")
    ck("work/recorded_only_repairs.md" in skill and '"recorded_only_repairs.md"' in run_src,
       "...and the recorded-only file")

    print("\n5. MAINTENANCE carries the reader-contract markers rule")
    ck("Every reader rule must sit INSIDE a `reader-contract` block" in maint,
       "MAINTENANCE.md states the markers rule")
    rc = (ROOT / "evals" / "reader_contract_render_test.py").read_text(encoding="utf-8")
    ck("OUTSIDE_ALLOWED" in maint and "OUTSIDE_ALLOWED" in rc,
       "...and names the allow-list the eval really uses")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


def _qa_window(md: str) -> str:
    i = md.find("## The QA window")
    j = md.find("\n## ", i + 1)
    return md[i:j] if i != -1 else ""


if __name__ == "__main__":
    sys.exit(main())
