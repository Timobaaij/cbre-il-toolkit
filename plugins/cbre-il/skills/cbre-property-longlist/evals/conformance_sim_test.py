#!/usr/bin/env python3
"""conformance_sim_test.py - the NO-RECALL bar for Sonnet-drivability (workstream 1).

Drives the REAL run.py through the FULL lifecycle - spine, QA window, deliver,
final_gate - as an orchestrator that knows NOTHING but the slim card's exit table.
Every command it executes comes VERBATIM from a printed handoff or from a file a
handoff names (the manifest, work/prompts/*). If any step needs knowledge from
SKILL.md prose that the handoffs do not carry, this eval goes red - the regression
guard for the SKILL.md diet: an edit that reintroduces a prose-only obligation
fails HERE, not on a live run.

CARD RULES the sim is allowed (the slim card's exit table, one line each):
  - after any handoff, re-run the SAME command (resume continues)
  - exit 3: a manifest job's `output` + '.SKIP' declines to the deterministic path
    (the `work/` prefix resolves against the real work dir - documented convention)
  - exit 11/12: the named .SKIP sentinel declines translation
  - exit 13: work/clarify.SKIP_ALL declines every question (the headless escape)
  - exit 14: simulate each work/prompts/g-*.md reviewer by writing 'FINDINGS: none'
    to the path after 'WRITE your findings to:' (a real orchestrator dispatches the
    file verbatim; the output contract is IN the file either way)
  - exit 15: never on a clean fixture (FINDINGS: none has no blocking findings)
  - exit 0: DONE-DONE - the spine recorded the QA round, delivered and ran
    final_gate itself; the handoff names where the deliverables are
Anything else is FORBIDDEN knowledge and a defect in the sim itself.

Offline, tracker-only corpus (fast). Asserts: convergence (no repeated exit with
identical state), exit 0 reached, and the four deliverables at the handoff-named path.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
HELPERS = SKILL / "helpers"
sys.path.insert(0, str(SKILL / "evals"))
sys.path.insert(0, str(HELPERS))
import cowork_sim as CS  # noqa: E402  (corpus builder only)

MAX_ROUNDS = 12
ROUND_TIMEOUT = 300


def check(name, cond):
    if not cond:
        raise AssertionError(name)


def _run(argv, cwd=None):
    return subprocess.run([sys.executable, *argv], capture_output=True, text=True,
                          errors="replace", timeout=ROUND_TIMEOUT, cwd=cwd)


def main() -> int:
    proj = Path(tempfile.mkdtemp(prefix="cbre_conform_")) / "project"
    CS.build_xlsx(proj / "1. Input", 5)
    work = proj / "2. Work Files"
    run_cmd = [str(HELPERS / "run.py"), "--project", str(proj), "--client", "Conform"]

    seen = set()
    out = ""
    for rnd in range(1, MAX_ROUNDS + 1):
        p = _run(run_cmd)
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
        fp = hashlib.sha1(
            b"|".join(sorted(f"{q.relative_to(work)}:{q.stat().st_size}".encode()
                             for q in work.rglob("*") if q.is_file()))).hexdigest() \
            if work.exists() else "none"
        print(f"  round {rnd}: exit {rc}")
        check(f"round {rnd}: no repeated (exit, state) - livelock", (rc, fp) not in seen)
        seen.add((rc, fp))
        if rc == 0:
            break
        if rc == 3:
            m = re.search(r"Manifest: (.+?\.json)", out)
            check("exit-3 handoff names the manifest", m)
            man = json.loads(Path(m.group(1).strip()).read_text(encoding="utf-8-sig"))
            for job in (man.get("decks") or []) + (man.get("jobs") or []):
                o = str(job.get("output") or "")
                if not o:
                    continue
                # card rule: the work/ prefix is a work-dir-relative convention
                op = work / o[len("work/"):] if o.startswith("work/") else Path(o)
                op.parent.mkdir(parents=True, exist_ok=True)
                (op.parent / (op.name + ".SKIP")).touch()
        elif rc == 11:
            m = re.search(r"i18n[\\/](\w+)_request\.json", out)
            check("exit-11 handoff names the request", m)
            (work / "i18n").mkdir(parents=True, exist_ok=True)
            (work / "i18n" / f"{m.group(1)}.SKIP").touch()
        elif rc == 12:
            (work / "i18n").mkdir(parents=True, exist_ok=True)
            (work / "i18n" / "data_translate.SKIP").touch()
        elif rc == 13:
            (work / "clarify.SKIP_ALL").touch()
        elif rc == 14:
            m = re.search(r"in (.+?) - each file is that agent's VERBATIM", out)
            check("exit-14 handoff names the prompts dir", m)
            gates = sorted(Path(m.group(1).strip()).glob("g-*.md"))
            check("rendered reviewer prompts exist", len(gates) >= 4)
            for g in gates:
                mw = re.search(r"WRITE your findings to:\s*\n(.+)",
                               g.read_text(encoding="utf-8"))
                check(f"{g.name} names its output path", mw)
                dest = Path(mw.group(1).strip())
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    dest.write_text("FINDINGS: none\n", encoding="utf-8")
        else:
            raise AssertionError(
                f"round {rnd}: exit {rc} - not answerable from the card's exit table "
                f"(a clean fixture must never hit it; 15 means FINDINGS: none raised a "
                f"blocking finding). Tail: {out[-400:]}")
    else:
        raise AssertionError(f"no exit 0 within {MAX_ROUNDS} rounds")

    # ---- exit 0 is DONE-DONE: the handoff names the deliverables ----------
    md = re.search(r"ready in (.+?)\.\s*$", out, re.MULTILINE) \
        or re.search(r"Deliverables in (.+?) - ", out)
    check("exit-0 handoff names the deliverables folder", md)
    out_dir = Path(md.group(1).strip())
    names = sorted(q.name for q in out_dir.iterdir())
    check(f"four deliverables (got {names})", len(names) == 4)
    check("dashboard html present", any(n.endswith(".html") for n in names))
    check("QA round was recorded by the spine", (work / "qa_state.json").exists())
    check("final gate report written", (work / "final_gate_report.md").exists())

    print("CONFORMANCE SIM: PASS (spine + loop-driven QA window + deliver + "
          "final_gate, driven by handoffs alone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
