#!/usr/bin/env python3
"""qa_review_ingest_test.py - a labelled finding can NEVER slip past the QA loop.

THE INVARIANT THIS FILE OWNS: the RECORDER (`gate_runner.py qa-round record`) and the
SHIP GATE (`final_gate.py`'s labelled-findings check) must agree, line for line, on what
a finding looks like. They read the same reviewer files, so any asymmetry is a bug in one
direction or the other, and both directions have shipped.

Holes reproduced end-to-end and now pinned:
  1. `record`'s regex required a `- ` bullet while final_gate's labelled-line check did
     not: a dashless `blocking: ...` was counted "proposed" by final_gate but never
     ingested, so the blocking-open exit never fired and an unaddressed BLOCKING finding
     shipped through an ALL-PASS.
  2. the QA driver's record guard was round-count-only (`qa_round_number == 0`), so a
     review written AFTER the first record was unrecordable forever.
  3. THE MIRROR OF (1), AND THE WORSE HALF. `record` was later widened to ingest the
     bracketed forms and the established severity label (`- [blocking] x`,
     `- [blocking]: x`, `- [HIGH] ...`, `- [MED] ...`); final_gate's separate hand-written
     copy of the same grammar was not. So a reviewer using a DOCUMENTED format had its
     finding RECORDED, `qa_blocking_open` came back empty, delivery ran, and then the ship
     gate refused the pack for having "no labelled findings" - eight of the twelve
     documented example lines below diverged, spanning three shapes. Three identical re-runs produced exit 7, exit 7, exit 7 with no state
     change: the ship gate's remedy was "re-dispatch the reviewer", which SKILL.md forbids
     and which the one-round window (QA_MAX_ROUNDS = 1, `record` no longer self-opening a
     round) had already made structurally impossible. Unshippable AND unrecoverable.

     THIS FILE MISSED IT, which is why section 1 is written the way it is. The old version
     pinned `- [blocking]` as ingested by the RECORDER and never asked the SHIP GATE about
     the same line, so half the invariant was untested. Every example form now lives in
     ONE list (`FORMS`) and is asserted against BOTH sides from that single list. Widening
     one parser without the other goes red here, and adding a form to `FORMS` tests both
     ends automatically.
Also pinned: a prose line merely starting with the word "blocking" is NOT a finding; a
genuinely finding-free review with no `FINDINGS: none` sentinel STILL fails the ship gate
(the fix removed false negatives, it did not remove the net); the ship gate no longer
prints a remedy the contract forbids; and run.py's fingerprint guard fires on new/changed
review files and stays quiet on unchanged ones. Offline.
"""
import json
import subprocess
import sys
import pathlib
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import final_gate as FG      # noqa: E402  the SHIP GATE side of the invariant
import gate_runner as GR     # noqa: E402  the RECORDER side


def check(name, cond):
    if not cond:
        raise AssertionError(name)


# --------------------------------------------------------------------------- #
# THE ONE SHARED LIST. (bucket, line, needle) - `bucket` is the label the REVIEWER chose,
# so it is also which side of qa_state.json the entry must land on; `needle` is a fragment
# unique to that line, used to find it again in the recorded state.
#
# Every form the recorder ingests belongs here, and everything here is asserted against
# the recorder AND the ship gate. Do NOT add a form to one parser without adding a row.
# The bracketed and severity rows are the exact forms of the ingested-then-refused
# deadlock (hole 3); reference/gates.md documents both, so a reviewer writing either is
# compliant and must not cost the run a round it cannot open.
FORMS = [
    ("blocking", "blocking: property=3 field=warehouseArea issue=untraceable value "
                 "action=strike to tbd", "untraceable value"),
    ("blocking", "- blocking: property=4 field=rent issue=no source cited "
                 "action=re-trace", "no source cited"),
    ("blocking", "- [blocking] property=5 field=rent issue=wrong source cited "
                 "action=re-trace", "wrong source cited"),
    ("blocking", "- [blocking]: property=6 field=eaves issue=value invented "
                 "action=strike to tbd", "value invented"),
    ("blocking", "- [HIGH] property=7 field=sitePlan issue=plan bound to the wrong unit "
                 "action=clear the plan", "wrong unit"),
    ("advisory", "advisory: cosmetic spacing on the compare table", "cosmetic spacing"),
    ("advisory", "- advisory: the hero photo could be brighter", "could be brighter"),
    ("advisory", "- [advisory] the KPI strip crowds at the narrow breakpoint",
     "narrow breakpoint"),
    ("advisory", "- [advisory]: the map legend overlaps a marker", "legend overlaps"),
    ("advisory", "- [MED] property=8 field=- issue=carousel slide order action=reorder",
     "carousel slide order"),
    ("advisory", "- [LOW] house term preference on the tenure label",
     "house term preference"),
    ("advisory", "- [ENV] the console warns about a missing favicon", "missing favicon"),
]
FORM_LINES = "".join(ln + "\n" for _b, ln, _n in FORMS)

# Lines that must NEVER be read as a finding. Prose that merely begins with the label word
# is the one the reviewers actually produce; the recorder's dashless branch requires the
# colon for exactly this reason, and the ship gate must draw the line in the same place.
NON_FORMS = [
    "Blocking the driveway access is a forklift in the hero photo, which is fine.",
    "The advisory notes below are context, not findings.",
    "VERDICT: amber",
    "FINDINGS: none",
]

work = pathlib.Path(tempfile.mkdtemp(prefix="cbre_qaing_"))
rdir = work / "reviews" / "round1"
rdir.mkdir(parents=True)
(rdir / "G-honesty.md").write_text(FORM_LINES, encoding="utf-8")
(rdir / "G-trace.md").write_text(
    "Blocking the driveway access is a forklift in the hero photo, which is fine.\n"
    "FINDINGS: none\n", encoding="utf-8")
(rdir / "G-images.md").write_text("FINDINGS: none\n", encoding="utf-8")
(rdir / "G-visual.md").write_text("FINDINGS: none\n", encoding="utf-8")

p = subprocess.run(
    [sys.executable, str(HELPERS / "gate_runner.py"), "qa-round", "record",
     "--work", str(work), "--reviews", str(work / "reviews")],
    capture_output=True, text=True, errors="replace")
check("record-ran", (work / "qa_state.json").exists())
st = json.loads((work / "qa_state.json").read_text(encoding="utf-8-sig"))
blocking = st["rounds"][-1].get("blocking") or []
advisory = st["rounds"][-1].get("advisory") or []
recorded = {"blocking": blocking, "advisory": advisory}

# --------------------------------------------------------------------------- #
# 1) SYMMETRY, FROM THE ONE LIST. Each form must be (a) ingested by the recorder into the
#    bucket the reviewer's own label names and (b) ACCEPTED by the ship gate's
#    labelled-findings check. (b) is the half that was missing when hole 3 shipped.
for bucket, line, needle in FORMS:
    check(f"recorder-ingests[{needle}]",
          any(needle in e for e in recorded[bucket]))
    check(f"recorder-bucket[{needle}]",
          not any(needle in e for e in recorded["advisory" if bucket == "blocking"
                                               else "blocking"]))
    check(f"shipgate-accepts[{needle}]", bool(FG.labelled_findings(line)))
# and in bulk: the gate sees exactly as many findings as there are forms, so a form that
# is silently swallowed by an over-greedy pattern is caught too
check("shipgate-count", len(FG.labelled_findings(FORM_LINES)) == len(FORMS))
check("recorder-count", len(blocking) + len(advisory) == len(FORMS))

# 2) the same line drawn in the same place on the NEGATIVE side: prose that merely starts
#    with the label word is a finding to neither parser.
for line in NON_FORMS:
    check(f"shipgate-rejects[{line[:24]}]", not FG.labelled_findings(line))
check("prose-not-ingested",
      not any("forklift" in e for e in blocking + advisory))

# 3) THE SHARED DEFINITION IS STRUCTURAL, not two copies kept in step by hand. Two
#    hand-synchronised regexes is what produced hole 3, so a re-introduced local copy in
#    final_gate must fail here even if it happens to be correct on the day it lands.
FGSRC = (HELPERS / "final_gate.py").read_text(encoding="utf-8")
check("shipgate-reads-recorder-finding-re", "gate_runner._FINDING_RE" in FGSRC)
check("shipgate-reads-recorder-severity-re", "gate_runner._SEVERITY_RE" in FGSRC)
check("no-local-label-regex", "(blocking|advisory)" not in FGSRC)
check("recorder-still-owns-the-patterns",
      GR._FINDING_RE is not None and GR._SEVERITY_RE is not None)

# --------------------------------------------------------------------------- #
# 4) END TO END, THROUGH THE REAL SHIP GATE CLI. The function above is the gate's own
#    acceptance predicate, but the deadlock was only visible from the printed lines, so
#    drive the CLI. The mechanical gates and deliverables are deliberately absent, so the
#    run exits non-zero for those reasons; what is asserted is the REVIEWER section:
#    every gate carrying a divergent-format finding reaches [PASS], and the count is the
#    reviewer's own number of findings. `--qa-state` is omitted so the output is the
#    parse branch alone.
e2e = pathlib.Path(tempfile.mkdtemp(prefix="cbre_qafg_"))
(e2e / "canonical.json").write_text(json.dumps({"meta": {"enrichment": {}}}),
                                    encoding="utf-8")
(e2e / "built.html").write_text("<html></html>", encoding="utf-8")
(e2e / "deliverables").mkdir()
er = e2e / "reviews" / "round1"
er.mkdir(parents=True)
# one gate per divergent shape, so a FAIL names which shape broke rather than "something"
(er / "G-honesty.md").write_text(FORM_LINES, encoding="utf-8")
(er / "G-trace.md").write_text(
    "- [blocking] property=5 field=rent issue=wrong source cited action=re-trace\n",
    encoding="utf-8")
(er / "G-images.md").write_text(
    "- [HIGH] property=7 field=sitePlan issue=plan bound to the wrong unit "
    "action=clear the plan\n", encoding="utf-8")
(er / "G-visual.md").write_text("- [MED] property=8 field=- issue=slide order "
                                "action=reorder\n", encoding="utf-8")
fg = subprocess.run(
    [sys.executable, str(HELPERS / "final_gate.py"),
     "--canonical", str(e2e / "canonical.json"), "--html", str(e2e / "built.html"),
     "--deliverables", str(e2e / "deliverables"), "--reviews", str(e2e / "reviews")],
    capture_output=True, text=True, errors="replace")
out = fg.stdout + fg.stderr
for g in ("G-honesty", "G-trace", "G-images", "G-visual"):
    check(f"e2e-shipgate-pass[{g}]", f"[PASS] {g}: " in out)
check("e2e-shipgate-count", f"[PASS] G-honesty: {len(FORMS)} finding(s)" in out)

# 5) THE NET IS STILL THERE. A review with neither an ingestable finding nor the explicit
#    `FINDINGS: none` sentinel must STILL fail: silence is indistinguishable from a
#    crashed or truncated review, and the gate exists to stop a pack shipping over an
#    unread blocking finding. Fixing an unshippable state by making the gate toothless
#    would be the worse bug.
(er / "G-visual.md").write_text(
    "I looked at the dashboard and formed some opinions about the spacing.\n"
    "Nothing here is labelled and there is no sentinel line.\n", encoding="utf-8")
fg2 = subprocess.run(
    [sys.executable, str(HELPERS / "final_gate.py"),
     "--canonical", str(e2e / "canonical.json"), "--html", str(e2e / "built.html"),
     "--deliverables", str(e2e / "deliverables"), "--reviews", str(e2e / "reviews")],
    capture_output=True, text=True, errors="replace")
out2 = fg2.stdout + fg2.stderr
check("net-blocks-unlabelled", "[PASS] G-visual: " not in out2)
check("net-still-fails", fg2.returncode != 0)
check("net-is-per-gate", "[PASS] G-honesty: " in out2)   # only the bad file is refused
check("net-not-shippable", "BLOCKED - do not ship" in out2)

# 6) THE REMEDY IS REACHABLE. The old text was "re-dispatch the reviewer" - forbidden by
#    SKILL.md's exit-15 row, and unreachable because QA_MAX_ROUNDS is 1 and `record` no
#    longer self-opens a round, so following it re-ran into the same exit forever. Whatever
#    the gate prints must be an action the operator can actually take on an intact file.
check("no-redispatch-remedy", "re-dispatch" not in out2.lower())
check("one-round-window", GR.QA_MAX_ROUNDS == 1)
check("remedy-names-the-rubric", "reference/gates.md" in out2)
check("remedy-names-the-rerun", "re-run the SAME command" in out2)

# --------------------------------------------------------------------------- #
# 7) the driver's fingerprint guard: unchanged files -> no re-record; a NEW review round
#    after the stamp -> record fires again. Imported HERE, not at module scope, so a
#    concurrent breakage in run.py cannot mask the sections above - the ones that own this
#    file's invariant.
import run as RUN  # noqa: E402

check("changed-before-stamp", RUN.qa_reviews_changed(work) is True)
RUN.qa_reviews_stamp(work)
check("quiet-when-unchanged", RUN.qa_reviews_changed(work) is False)
time.sleep(0.01)
r2 = work / "reviews" / "round2"
r2.mkdir(parents=True)
(r2 / "G-honesty.md").write_text("blocking: a round-2 finding\n", encoding="utf-8")
check("fires-on-new-round", RUN.qa_reviews_changed(work) is True)

print("QA REVIEW INGEST TEST: PASS")
