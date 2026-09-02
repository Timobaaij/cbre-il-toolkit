#!/usr/bin/env python3
"""setup_gate_test.py - the broker is ASKED the Stage-0 six questions. (B63)

THE LIVE FAILURE. A colleague's run on an up-to-date install asked nothing at the opening.
The cause was not the model. `intake.scaffold_yaml` writes a COMPLETE project.yaml on the
first pass - client name from --client, `output.language: English`,
`inputs.emails.source: none`, the enrichment flags, `clarify.mode: interactive` - i.e. all
six Stage-0 answers pre-filled with guesses, BEFORE anything told the orchestrator to ask.
SKILL.md then said to skip the form when "project.yaml already carries the answers". It
always did. So skipping the form was the COMPLIANT behaviour, and runs shipped English
dashboards with no email ingestion and car drive-times to brokers who were never offered a
choice.

Two things were wrong and both are pinned here:
  1. Presence of values is not consent. `setup.confirmed` is the only signal a human
     answered, and intake writes it false.
  2. The instruction to ask lived in ONE place: a trailing clause of the exit-3
     interpretation hand-off, phrased as a question. A corpus with no decks and no trackers
     to map (email-only, image-only, or a fully cached work dir) never printed it at all.
     It is now a prefix on every exit-3 hand-off plus its own blocking exit-13 stop.

Also pinned: clarify.skip_all reads project.yaml from the WORK dir. run.py resolves it as
`work / "project.yaml"`, but skip_all read `work.parent` only, so `clarify.assume_defaults`
in the real file was dead wiring while failure-modes.md documented it as an escape.
Offline.
"""
import json
import sys
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402
import intake as INTAKE  # noqa: E402
import run as RUN  # noqa: E402

fails = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


def work_with(yaml_text: str) -> pathlib.Path:
    w = pathlib.Path(tempfile.mkdtemp(prefix="cbre_setup_")) / "2. Work Files"
    w.mkdir(parents=True)
    if yaml_text is not None:
        (w / "project.yaml").write_text(yaml_text, encoding="utf-8")
    return w


# ----------------------------------------------- 1. the scaffold is not consent
INV = {"clusters": {"alpha": {"country": "ES"}}, "emails": [], "xlsx": [], "images": [],
       "pdf": [], "pptx": [], "present_types": ["pdf"]}
scaffold = INTAKE.scaffold_yaml(INV, "Acme Retail")
import yaml as _Y  # noqa: E402
sc = _Y.safe_load(scaffold)
ck((sc.get("setup") or {}).get("confirmed") is False,
   "intake scaffolds `setup.confirmed: false`")
# the scaffold DOES carry every Stage-0 key - which is exactly why presence cannot be the test
for _k, _path in (("client", ("client", "name")), ("language", ("output", "language")),
                  ("emails", ("inputs", "emails", "source")),
                  ("enrichment", ("enrichment", "geocode")),
                  ("ask mode", ("clarify", "mode"))):
    _v = sc
    for _seg in _path:
        _v = (_v or {}).get(_seg)
    ck(_v is not None, f"the scaffold pre-fills {_k} (so 'carries the answers' is always true)")
ck(RUN.setup_pending(sc, work_with(scaffold)) is True,
   "a scaffolded project.yaml leaves setup PENDING - values are not consent")
ck(RUN.setup_pending(_Y.safe_load(scaffold.replace("confirmed: false", "confirmed: true")),
                     work_with(scaffold)) is False,
   "`setup.confirmed: true` is what clears it")
ck(RUN.setup_pending({}, work_with(None)) is True,
   "no project.yaml at all also leaves it pending")

# ----------------------------------------------- 2. the headless escapes clear it
w_skip = work_with(scaffold)
(w_skip / CQ.SKIP_ALL_FILE).touch()
ck(RUN.setup_pending(sc, w_skip) is False,
   "work/clarify.SKIP_ALL declines the form (headless, recorded as a decision)")
ck(RUN.setup_pending({"clarify": {"assume_defaults": True}}, work_with(scaffold)) is False,
   "clarify.assume_defaults declines it too")
# THE PATH BUG: skip_all must read project.yaml where run.py puts it (the WORK dir)
w_yaml = work_with("clarify:\n  assume_defaults: true\n")
ck(CQ.skip_all(w_yaml) is True,
   "clarify.skip_all reads work/project.yaml (it read work.parent only - dead wiring)")
w_parent = work_with(None)
(w_parent.parent / "project.yaml").write_text("clarify:\n  assume_defaults: true\n",
                                              encoding="utf-8")
ck(CQ.skip_all(w_parent) is True, "...and still honours a file beside a legacy work dir")
ck(CQ.skip_all(work_with(scaffold)) is False,
   "a scaffolded project.yaml does NOT accidentally decline everything")

# ----------------------------------------------- 3. the instruction leads the hand-off
w = work_with(scaffold)
proj = w / "project.yaml"
pref = RUN.setup_prefix(sc, w, proj)
ck(pref.startswith("SETUP FIRST"), "the prefix LEADS with the instruction, not a question")
for _needle, _why in (("show_widget", "names the widget tool"),
                      ("setup-form.md", "names the verbatim form"),
                      ("setup.confirmed: true", "names the ONE thing that clears it"),
                      ("is a GUESS", "warns that the file's values are guesses"),
                      ("clarify.SKIP_ALL", "names the headless decline")):
    ck(_needle in pref, f"...and it {_why}")
ck("FIRST PASS?" not in pref,
   "the old conditional phrasing is gone (it was read as optional and skipped)")
ck(RUN.setup_prefix(
    _Y.safe_load(scaffold.replace("confirmed: false", "confirmed: true")), w, proj) == "",
   "a confirmed setup adds no prefix")

# ----------------------------------------------- 4. wiring: EVERY exit-3 site carries it
RSRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")
_sites = RSRC.count("_exit_round_trip(work, 3")
_pref_calls = RSRC.count("setup_prefix(cfg, work, proj")
ck(_pref_calls >= 2,
   f"setup_prefix is applied at the exit-3 sites that precede the stop ({_pref_calls})")
ck("setup_pending(cfg, work)" in RSRC, "run.py gates on setup_pending (not dead wiring)")
ck('"setup_form"' in RSRC and "SETUP_QID_SUBJECT" in RSRC,
   "the standalone stop emits a setup_form question")
# the stop must sit AFTER the no-usable-inputs exit: six questions then "nothing to read"
# would be the wrong order for the broker
ck(RSRC.index("SETUP IS A FIRST-PASS INVARIANT") > RSRC.index("No property sources extracted"),
   "the setup stop comes after the no-usable-inputs exit, not before it")
ck(_sites == 3, f"exit-3 site count unchanged ({_sites}) - a new one needs the prefix too")

# ----------------------------------------------- 5. the question itself
ck(CQ.KINDS.get("setup_form") == "broker", "setup_form is a BROKER question")
ck("setup_form" in CQ.BLOCKING_KINDS,
   "...and BLOCKING: the scaffold's six guesses are exactly the damage")
ck(CQ.is_material({"kind": "setup_form"}),
   "...and material, so the materiality filter can never suppress it")
w5 = work_with(scaffold)
qid = CQ.qid("setup_form", RUN.SETUP_QID_SUBJECT)
CQ.emit(w5, [{"id": qid, "kind": "setup_form", "asked_of": "broker", "blocking": True,
              "subject": "Stage-0 setup", "question": "present the form"}])
payload = json.loads((w5 / CQ.QUESTIONS_FILE).read_text(encoding="utf-8-sig"))
ck([q["kind"] for q in payload["questions"]] == ["setup_form"],
   "it is written to work/questions.json, where the exit-13 row says to look")
# a stray answers.json entry must NOT be able to clear it - the answers belong in project.yaml
(w5 / CQ.ANSWERS_FILE).write_text(json.dumps({qid: "English"}), encoding="utf-8")
CQ.ingest_answers(w5)
ck(RUN.setup_pending(sc, w5) is True,
   "an answers.json entry does NOT clear the setup gate (the answers go in project.yaml)")
# an explicit DECLINE does clear it, and is recorded as a decision
w5b = work_with(scaffold)
CQ.emit(w5b, [{"id": qid, "kind": "setup_form", "asked_of": "broker", "blocking": True,
               "subject": "Stage-0 setup", "question": "present the form"}])
(w5b / CQ.ANSWERS_FILE).write_text(json.dumps({qid: "skip"}), encoding="utf-8")
CQ.ingest_answers(w5b)
ck(qid in CQ.declined_ids(w5b), "an explicit 'skip' is recorded as a decline, not silence")

# ----------------------------------------------- 6. the docs that caused it
SK = (ROOT / "SKILL.md").read_text(encoding="utf-8", errors="replace")
ck("SKIP the widget only when\n`project.yaml` already carries the answers" not in SK
   and "SKIP the widget ONLY when `setup.confirmed` is already true" in SK,
   "SKILL.md no longer says presence of values means the form was answered")
ck("setup.confirmed" in (ROOT / "reference" / "setup-form.md").read_text(
    encoding="utf-8", errors="replace"),
   "reference/setup-form.md tells the orchestrator to set the flag")
ck("setup:" in (ROOT / "reference" / "config.md").read_text(encoding="utf-8", errors="replace"),
   "reference/config.md documents the setup block")

print("\nSETUP GATE TEST: " + ("FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
