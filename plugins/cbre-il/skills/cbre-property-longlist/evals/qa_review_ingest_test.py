#!/usr/bin/env python3
"""qa_review_ingest_test.py - a labelled finding can NEVER slip past the QA loop.

Two holes the Phase-3 blind review reproduced end-to-end, both of which shipped an
unaddressed BLOCKING finding through an ALL-PASS:
  1. `qa-round record`'s regex required a `- ` bullet while final_gate's labelled-line
     check does not: a dashless `blocking: ...` was counted "proposed" by final_gate but
     never ingested, so exit 15 never fired.
  2. the QA driver's record guard was round-count-only (`qa_round_number == 0`), so a
     review written AFTER the first record (final_gate's own remedy for a garbled file is
     "re-dispatch the reviewer") was unrecordable forever.
Pinned here: dashless and bracket label forms are ingested; a prose line merely starting
with the word "blocking" is NOT; and run.py's fingerprint guard fires on new/changed
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
import run as RUN  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


work = pathlib.Path(tempfile.mkdtemp(prefix="cbre_qaing_"))
rdir = work / "reviews" / "round1"
rdir.mkdir(parents=True)
(rdir / "G-honesty.md").write_text(
    "blocking: property=3 field=warehouseArea issue=untraceable value action=fix\n"
    "advisory: cosmetic spacing on the compare table\n", encoding="utf-8")
(rdir / "G-trace.md").write_text(
    "- [blocking] property=5 field=rent issue=wrong source cited action=re-trace\n",
    encoding="utf-8")
(rdir / "G-images.md").write_text(
    "Blocking the driveway access is a forklift in the hero photo, which is fine.\n"
    "FINDINGS: none\n", encoding="utf-8")
(rdir / "G-visual.md").write_text("FINDINGS: none\n", encoding="utf-8")

p = subprocess.run(
    [sys.executable, str(HELPERS / "gate_runner.py"), "qa-round", "record",
     "--work", str(work), "--reviews", str(work / "reviews")],
    capture_output=True, text=True, errors="replace")
st = json.loads((work / "qa_state.json").read_text(encoding="utf-8-sig"))
blocking = st["rounds"][-1].get("blocking") or []
advisory = st["rounds"][-1].get("advisory") or []

# 1) dashless and bracket forms are both INGESTED
check("dashless-ingested", any("untraceable value" in b for b in blocking))
check("bracket-ingested", any("wrong source cited" in b for b in blocking))
check("advisory-ingested", any("cosmetic spacing" in a for a in advisory))
# 2) a prose line merely starting with 'Blocking' is NOT a finding
check("prose-not-ingested", not any("forklift" in b for b in blocking + advisory))

# 3) the driver's fingerprint guard: unchanged files -> no re-record; a NEW review
#    round after the stamp -> record fires again
check("changed-before-stamp", RUN.qa_reviews_changed(work) is True)
RUN.qa_reviews_stamp(work)
check("quiet-when-unchanged", RUN.qa_reviews_changed(work) is False)
time.sleep(0.01)
r2 = work / "reviews" / "round2"
r2.mkdir(parents=True)
(r2 / "G-honesty.md").write_text("blocking: a round-2 finding\n", encoding="utf-8")
check("fires-on-new-round", RUN.qa_reviews_changed(work) is True)

print("QA REVIEW INGEST TEST: PASS")
