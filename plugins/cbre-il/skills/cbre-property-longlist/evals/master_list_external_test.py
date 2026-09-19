#!/usr/bin/env python3
"""master_list_external_test.py - a wrapper skill that already owns scope is not asked again.

THE DEFECT THIS PINS. kato-longlist wraps this toolkit. It builds its OWN master list at its
step 2.5, the operator answers that workbook, and only then does `toolkit_tracker.py` generate
this skill's project.yaml and inputs folder FROM the rows that survived. Item 4 then added the
spine's own exit-17 stop, which on a Kato run would hand the same operator a second sheet
listing the same options they had just finished striking off, with nothing new on it. A gate
that visibly re-asks an answered question is answered "Yes to everything" from the second time
onwards, and then it is not a gate on the run where it would have mattered.

`master_list: {mode: external, confirmed_by: "..."}` in project.yaml declines the stop. What
makes it safe is everything it does NOT do, so that is what most of this file checks: it is not
an answer, so no `master_list.json` is written, so none of the four consumers can read one - no
derived source authority (exit 13 asks its question exactly as it did before item 4), no `same`
seeding into match_decisions.json, no deck skipped. One line in the Gaps Report names where scope
was settled, because a reader of that report cannot otherwise tell.

THE CONTROL IS THE POINT. The same fixture is driven one round WITHOUT the setting and must stop
at 17. Without that half, a test asserting "17 never appeared" would pass just as happily against
a spine that had lost the stop altogether.

Offline, tracker-only corpus, driven exactly the way conformance_sim_test.py drives the spine.
"""
from __future__ import annotations

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

CONFIRMED_BY = "kato-longlist step 2.5 - the operator answered OUR master list workbook"
EXTERNAL_BLOCK = f"""
master_list:
  mode: external
  confirmed_by: "{CONFIRMED_BY}"
"""

fails = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


def _run(argv):
    return subprocess.run([sys.executable, *argv], capture_output=True, text=True,
                          errors="replace", timeout=ROUND_TIMEOUT)


def _fixture(tag: str, external: bool) -> tuple:
    """A project with its project.yaml already scaffolded, optionally carrying the setting.

    intake is run first, on purpose. The spine scaffolds the same file on its first pass, but the
    master-list stage sits inside that same pass, so patching afterwards would test a run that had
    already been stopped - which is the thing being ruled out.
    """
    proj = Path(tempfile.mkdtemp(prefix=f"cbre_mlext_{tag}_")) / "project"
    CS.build_xlsx(proj / "1. Input", 5)
    work = proj / "2. Work Files"
    work.mkdir(parents=True, exist_ok=True)
    p = _run([str(HELPERS / "intake.py"), str(proj / "1. Input"),
              "--out-dir", str(work), "--client", "Wrapper"])
    if p.returncode != 0:
        raise AssertionError(f"intake failed to scaffold: {p.stderr[-400:]}")
    yml = work / "project.yaml"
    if external:
        yml.write_text(yml.read_text(encoding="utf-8-sig") + EXTERNAL_BLOCK, encoding="utf-8")
    return proj, work


def _drive(proj: Path, work: Path, max_rounds: int) -> list:
    """The conformance sim's loop, minus its exit-17 arm - which is the assertion."""
    run_cmd = [str(HELPERS / "run.py"), "--project", str(proj), "--client", "Wrapper"]
    seq = []
    for _ in range(max_rounds):
        p = _run(run_cmd)
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
        seq.append(rc)
        print(f"    round {len(seq)}: exit {rc}")
        if rc == 0 or rc == 17:
            break
        if rc == 3:
            m = re.search(r"Manifest: (.+?\.json)", out)
            if not m:
                break
            man = json.loads(Path(m.group(1).strip()).read_text(encoding="utf-8-sig"))
            for job in (man.get("decks") or []) + (man.get("jobs") or []):
                o = str(job.get("output") or "")
                if not o:
                    continue
                op = work / o[len("work/"):] if o.startswith("work/") else Path(o)
                op.parent.mkdir(parents=True, exist_ok=True)
                (op.parent / (op.name + ".SKIP")).touch()
        elif rc == 11:
            m = re.search(r"i18n[\\/](\w+)_request\.json", out)
            (work / "i18n").mkdir(parents=True, exist_ok=True)
            (work / "i18n" / f"{m.group(1) if m else 'chrome'}.SKIP").touch()
        elif rc == 12:
            (work / "i18n").mkdir(parents=True, exist_ok=True)
            (work / "i18n" / "data_translate.SKIP").touch()
        elif rc == 13:
            (work / "clarify.SKIP_ALL").touch()
        elif rc == 14:
            m = re.search(r"in (.+?) - each file is that agent's VERBATIM", out)
            if not m:
                break
            for g in sorted(Path(m.group(1).strip()).glob("g-*.md")):
                mw = re.search(r"WRITE your findings to:\s*\n(.+)", g.read_text(encoding="utf-8"))
                if not mw:
                    continue
                dest = Path(mw.group(1).strip())
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    dest.write_text("FINDINGS: none\n", encoding="utf-8")
        else:
            break
    return seq


print("== the control: without the setting the fixture STOPS at 17 ==")
_cproj, _cwork = _fixture("ctl", external=False)
_cseq = _drive(_cproj, _cwork, 1)
ck(_cseq == [17],
   f"one round on the untouched fixture exits 17 - the stop is real (got {_cseq})")

print("\n== with master_list.mode external the stop never fires ==")
_proj, _work = _fixture("ext", external=True)
_seq = _drive(_proj, _work, MAX_ROUNDS)
ck(17 not in _seq, f"exit 17 is absent from the whole round sequence {_seq}")
ck(_seq and _seq[0] != 17,
   "...including the FIRST round, before any sentinel exists that could have bypassed it")
ck(_seq and _seq[-1] == 0, f"...and the run still converges to exit 0 (got {_seq})")

print("\n== it declines the stop and does nothing else ==")
ck(not (_work / "master_list.json").exists(),
   "no master_list.json: an external scope is NOT recorded as an answer, so none of the four "
   "consumers can read one")
ck(not (_work / "master_candidates_auto.json").exists(),
   "...and no candidate enumeration was built either - nobody was going to be shown it")
ck(not (_work / "Master List.xlsx").exists(), "...and no workbook")
_ext = {}
try:
    _ext = json.loads((_work / "master_list_external.json").read_text(encoding="utf-8-sig"))
except Exception:
    pass
ck(_ext.get("mode") == "external", "the declined stop IS recorded, under its own filename")
ck(CONFIRMED_BY in str(_ext.get("confirmed_by") or ""),
   "...carrying the confirmed_by text verbatim, so the provenance survives the run")

sys.path.insert(0, str(HELPERS))
import master_list as ML  # noqa: E402

ck(ML.user_answered(_work) is False,
   "user_answered() is False, so the source authority is not derived from a sheet nobody filled")
ck(ML.load_answers(_work) == {}, "...and there are no answers to read")
ck(ML.seed_match_decisions([], _work) == {},
   "...and nothing is seeded into match_decisions.json")
_kept, _dropped = ML.apply_to_clusters([[{"__meta": {"source_file": "x.pdf"}}]], _work)
ck(len(_kept) == 1 and not _dropped,
   "...and apply_to_clusters drops nothing, so no option leaves the longlist by this route")

print("\n== the Gaps Report says where scope was settled, in one line and no more ==")
_gaps = ""
for _p in Path(_proj).rglob("*Gaps*"):
    if _p.is_file() and _p.suffix.lower() in (".md", ".txt"):
        _gaps = _p.read_text(encoding="utf-8", errors="replace")
        break
ck(bool(_gaps), "a Gaps Report was delivered")
ck("Scope for this longlist was settled before this run" in _gaps,
   "...and it names that scope was settled upstream")
ck(CONFIRMED_BY in _gaps, "...and who confirmed it")
ck("Options excluded by the master list" not in _gaps
   and "Scope was not put to you" not in _gaps,
   "...and carries NO master-list section: there was no sheet here, and claiming either the "
   "exclusion list or the headless disclosure would be a false statement about this run")

print("\n== the config route itself refuses to be switched off by a typo ==")
ck(ML.external_scope(None) is None, "absent config is interactive")
ck(ML.external_scope({}) is None, "absent key is interactive")
ck(ML.external_scope({"master_list": {"mode": "extrenal"}}) is None,
   "a MISSPELT mode is interactive - the acceptable failure of a scope gate is firing when it "
   "need not, never a typo turning it off")
ck(ML.external_scope({"master_list": "external"}) is None,
   "a scalar where a mapping belongs is interactive")
ck((ML.external_scope({"master_list": {"mode": "EXTERNAL"}}) or {}).get("mode") == "external",
   "case does not matter on the mode itself")
ck("not stated" in (ML.external_scope({"master_list": {"mode": "external"}}) or {})
   .get("confirmed_by", ""),
   "a missing confirmed_by is PRINTED as missing rather than left blank in the Gaps Report")

print("\n== it is documented where a wrapper author and an operator will look ==")
_cfg_md = (SKILL / "reference" / "config.md").read_text(encoding="utf-8")
_ml_md = (SKILL / "reference" / "master-list.md").read_text(encoding="utf-8")
ck("master_list:" in _cfg_md and "mode: external" in _cfg_md,
   "reference/config.md documents the key")
ck("mode: external" in _ml_md, "reference/master-list.md documents it too")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S):"))
for f in fails:
    print(f"  - {f}")
sys.exit(1 if fails else 0)
