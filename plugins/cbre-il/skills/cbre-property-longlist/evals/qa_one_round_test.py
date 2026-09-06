#!/usr/bin/env python3
"""qa_one_round_test.py - EXACTLY ONE review round per run, and never a second.

THE HARD REQUIREMENT THIS PINS. The shape of the review phase, on every run without
exception, is: spawn the independent review agents ONCE; implement every blocking finding
plus any advisory that is cheap and material; deliver. A second review round is never
correct. Structurally the pipeline was already close - the review-missing exit fires once and
the blocking-findings exit is a fix loop WITHIN a round - but one mechanism pulled a second
round in anyway: `qa-round record` SELF-OPENED the next round whenever the last was recorded,
capped only by the arithmetic `len(rounds) < QA_MAX_ROUNDS`. Arithmetic is the wrong kind of
guard for a structural rule: raise the constant, or arrive with a work dir that already holds
two rounds, and the second round is back.

AND THE INCIDENT THAT MAKES THIS DELICATE, which is why the file is this long. The driver's
record guard used to be round-count-only (`qa_round_number == 0`), so a review written AFTER
the first record was unrecordable for ever: final_gate's own remedy for a garbled review file
is to RE-DISPATCH that reviewer, a re-dispatched reviewer must write a NEW file (B24 -
otherwise an ostensibly independent agent reads the previous verdict first), the new file
landed in reviews/round2/, and no pass ever recorded it - the run exited 0 over an unread
BLOCKING finding. `run.qa_reviews_changed` fixed the driver half by fingerprinting the review
FILES. The other half was still open and is closed here: `record` read only
`review_dir_for(rroot, cur["n"])`, i.e. round1/ and nothing else, so it re-ran, re-read
round1/, found nothing new and stamped.

So the two properties are ONE property, and they are asserted together throughout:
    a review file that changes after the round is recorded FOLDS INTO THAT ROUND
    as additional findings, which is simultaneously why a changed review is still
    recorded AND why a second round is impossible.

Pinned here:
  1. however many times the reviews change, a run records ONE round and never opens a second
  2. reviews that change after a round is recorded fold into it - a changed or ADDED review
     file is still recorded, in a later round DIR, which is the incident above
  3. the blocking-findings fix loop still works and re-dispatches no reviewer
  4. a work dir that already carries more than one round is FOLDED, honestly: the latest
     round's advisory list survives (never the union - B26), every UNRESOLVED blocking
     finding is carried forward, every recorded repair is kept, the superseded rounds are
     preserved verbatim, and it says so on stdout
  5. advisory findings are not forced: they still carry to the Gaps Report

Offline, pure state. No build, no network. Run: python evals/qa_one_round_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
# isolate the cross-run flywheel ledger BEFORE any qa-round call (run_all.py does this too,
# but this eval must be runnable on its own without polluting the maintainer's signal)
os.environ.setdefault("CBRE_FLYWHEEL_PATH",
                      str(Path(tempfile.mkdtemp(prefix="cbre_1r_fw_")) / "fw.jsonl"))
import gate_runner as GR  # noqa: E402
import run as RUN  # noqa: E402

FAILS: list = []
GSRC = (HELPERS / "gate_runner.py").read_text(encoding="utf-8", errors="replace")
RSRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _work(td: Path, input_hash: str = "onehash") -> Path:
    w = td / "work"
    (w / "reviews").mkdir(parents=True, exist_ok=True)
    (w / "inventory.json").write_text(json.dumps({"folder": "x", "input_hash": input_hash}),
                                      encoding="utf-8")
    (w / "canonical.json").write_text(json.dumps({"meta": {}, "properties": [{"id": 1}]}),
                                      encoding="utf-8")
    return w


def _review(w: Path, rnd: int, gate: str, body: str) -> Path:
    d = w / "reviews" / f"round{rnd}"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{gate}.md"
    # a distinct mtime, so run.qa_reviews_changed's fingerprint (relpath+size+mtime) is a
    # real signal rather than an artefact of two writes landing in the same clock tick
    time.sleep(0.01)
    p.write_text(body, encoding="utf-8")
    return p


def _rec(w: Path) -> tuple:
    """`qa-round record` through the real command, stdout captured."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = GR.cmd_qa_round(_Args(mode="record", work=str(w),
                                   reviews=str(w / "reviews")))
    return rc, buf.getvalue()


def _resolve(w: Path, fid: str, because: str) -> tuple:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = GR.cmd_qa_round(_Args(mode="resolve", work=str(w), reviews="",
                                   id=fid, because=because))
    return rc, buf.getvalue()


def _state(w: Path) -> dict:
    return json.loads((w / "qa_state.json").read_text(encoding="utf-8-sig"))


def _all(w: Path) -> list:
    st = _state(w)
    return [e for r in st.get("rounds") or []
            for e in (r.get("blocking") or []) + (r.get("advisory") or [])]


# --------------------------------------------------------------------------- #
def one_round_however_many_changes() -> None:
    print("1. ONE round, however many times the reviews change")
    with tempfile.TemporaryDirectory() as td_s:
        w = _work(Path(td_s))
        _review(w, 1, "G-honesty", "- advisory: r1 honesty note\n")
        _review(w, 1, "G-trace", "- advisory: r1 trace note\n")
        rc, out = _rec(w)
        ck(rc == 0 and GR.qa_round_number(w) == 1,
           f"the first record opens and records the single round (rc={rc}, "
           f"n={GR.qa_round_number(w)})")
        # THE SELF-OPEN IS GONE, and it is gone structurally rather than by arithmetic.
        for i in range(4):
            rc, out = _rec(w)
            ck(rc == 0 and GR.qa_round_number(w) == 1,
               f"re-record #{i + 1} exits 0 and STILL one round ({GR.qa_round_number(w)})")
        ck("FAIL" not in out and "BLOCKED" not in out,
           "...and a re-record is never phrased as a failure to investigate")
        # ...and each new DISPATCH dir is a new dir, not a new round
        for rnd in (2, 3, 4):
            _review(w, rnd, "G-honesty", f"- advisory: round{rnd} dispatch note\n")
            rc, out = _rec(w)
            ck(rc == 0 and GR.qa_round_number(w) == 1,
               f"a reviews/round{rnd}/ dispatch dir does NOT open round {rnd} "
               f"({GR.qa_round_number(w)})")
        ck(len(_state(w)["rounds"]) == 1,
           f"four dispatch directories, ONE recorded round "
           f"({len(_state(w)['rounds'])})")
        ck(GR.QA_MAX_ROUNDS == 1, "QA_MAX_ROUNDS is 1 - the declared invariant")
        # the mechanism, asserted at the source: `record` must not append a round because the
        # last one is recorded. The old shape was an `elif ... .get("recorded") and len(...) <
        # QA_MAX_ROUNDS: st["rounds"].append(...)`.
        ck('st["rounds"][-1].get("recorded") and len(st["rounds"]) < QA_MAX_ROUNDS' not in GSRC,
           "the self-opening branch is REMOVED from the source, not merely unreachable")
        ck("_coalesce_rounds(st) if len(st[\"rounds\"]) > QA_MAX_ROUNDS" in GSRC,
           "QA_MAX_ROUNDS is now a CHECKED invariant rather than a budget counted down")


def changed_reviews_fold_in() -> None:
    print("\n2. reviews that change AFTER the record fold into that round "
          "(and the fingerprint incident still cannot happen)")
    with tempfile.TemporaryDirectory() as td_s:
        w = _work(Path(td_s))
        _review(w, 1, "G-honesty", "- blocking: r1 fabricated rent on property 2\n"
                                   "- advisory: r1 cosmetic spacing\n")
        rc, out = _rec(w)
        ck(rc == 0 and "reviews read from round1" in out,
           f"round1 is read and named {ascii(out[:60])}")
        RUN.qa_reviews_stamp(w)
        ck(RUN.qa_reviews_changed(w) is False,
           "the driver's fingerprint is quiet while nothing changed")

        # THE INCIDENT, END TO END. final_gate's remedy for a garbled review is to re-dispatch
        # that reviewer; B24 makes the re-dispatch write a NEW file, so it lands in round2/.
        _review(w, 2, "G-honesty", "- blocking: the RE-DISPATCHED reviewer's finding\n")
        ck(RUN.qa_reviews_changed(w) is True,
           "the driver fires on the re-dispatched review file")
        rc, out = _rec(w)
        ck(rc == 0, f"record accepts it (rc={rc})")
        ck(GR.qa_round_number(w) == 1,
           f"...WITHOUT opening a second round ({GR.qa_round_number(w)})")
        got = _all(w)
        ck(any("RE-DISPATCHED reviewer's finding" in e for e in got),
           "THE POINT: the re-dispatched finding IS RECORDED - it is not silently skipped, "
           "which is the bug that shipped an unread blocking finding through an exit 0")
        ck(any("r1 fabricated rent" in e for e in got)
           and any("r1 cosmetic spacing" in e for e in got),
           "...and round 1's own findings are still there - it FOLDED, it did not replace")
        ck("round1" in out and "round2" in out,
           f"record names BOTH dispatch dirs it read {ascii(out[:80])}")
        _open = {o["finding"] for o in GR.qa_blocking_open(w)}
        ck(any("RE-DISPATCHED" in f for f in _open),
           "the folded blocking finding is OPEN, so the ship gate holds it")

        # an EDIT IN PLACE to an already-read file folds in too
        _review(w, 1, "G-honesty", "- blocking: r1 fabricated rent on property 2\n"
                                   "- advisory: r1 cosmetic spacing\n"
                                   "- advisory: a note the reviewer added afterwards\n")
        ck(RUN.qa_reviews_changed(w) is True, "an edited review file changes the fingerprint")
        _rec(w)
        ck(any("added afterwards" in e for e in _all(w))
           and GR.qa_round_number(w) == 1,
           "an in-place edit folds into the SAME round")
        # additive, never subtractive: a later dispatch's SILENCE does not retire a finding
        _review(w, 2, "G-honesty", "FINDINGS: none\n")
        _rec(w)
        ck(any("RE-DISPATCHED reviewer's finding" not in e for e in _all(w))
           and any("r1 fabricated rent" in e for e in _all(w)),
           "a later dispatch going quiet does not retire an earlier finding "
           "(only `qa-round resolve` strikes one, on the record)")
        ck(GR.qa_round_number(w) == 1, "still one round after all of that")
        ck("rdirs = [d for _rd_n, d in review_round_dirs(rroot)] or [rroot]" in GSRC,
           "record reads EVERY round dir, with the flat root as round 0 when there are none")

    # the flat root is still round 0, and is NOT double-read once a round dir exists
    with tempfile.TemporaryDirectory() as td_s:
        w = _work(Path(td_s))
        (w / "reviews" / "G-images.md").write_text(
            "- advisory: the flat root holds this gate's only verdict\n", encoding="utf-8")
        rc, out = _rec(w)
        ck(rc == 0 and any("flat root holds" in e for e in _all(w)),
           "a flat reviews/*.md is still read as round 0")
        _review(w, 1, "G-honesty", "- advisory: a round dir now exists\n")
        _rec(w)
        ck(sum(1 for e in _all(w) if "flat root holds" in e) == 1,
           "...and is not DOUBLE-read once a round dir exists (one entry, not two)")


def fix_loop_still_works() -> None:
    print("\n3. the blocking-findings fix loop works and re-dispatches NO reviewer")
    with tempfile.TemporaryDirectory() as td_s:
        w = _work(Path(td_s))
        _review(w, 1, "G-honesty",
                "- blocking: property=3 field=breeam issue=impossible grade action=strike\n"
                "- advisory: two region granularities across the dataset\n")
        rc, out = _rec(w)
        op = GR.qa_blocking_open(w)
        ck(rc == 0 and len(op) == 1, f"one blocking finding is open ({len(op)})")
        ck("NEXT: IMPLEMENT" in out, "NEXT names the orchestrator's own job")
        ck("Do NOT re-dispatch the reviewers" in out,
           "...and forbids re-dispatching a reviewer, in the same breath")
        ck("second review round is never correct" in out,
           "...and says a second review round is never correct")
        rc, _ = _resolve(w, op[0]["id"], "struck breeam to tbd and added a gap row citing "
                                         "the empty source cell")
        ck(rc == 0 and GR.qa_blocking_open(w) == [],
           "a recorded repair closes it - the fix loop terminates")
        ck(GR.qa_round_number(w) == 1,
           f"the whole fix loop spends NO extra round ({GR.qa_round_number(w)})")
        rc, out = _rec(w)
        ck(rc == 0 and GR.qa_blocking_open(w) == [] and GR.qa_round_number(w) == 1,
           "a re-record after the repair neither re-opens the finding nor a round")
        ck(len(GR.qa_carried(w)) == 1,
           f"the advisory still CARRIES - it is not forced, it ships disclosed "
           f"({len(GR.qa_carried(w))})")
        # the DRIVER's exit-15 handoff must not send anybody back to the reviewers
        i15 = RSRC.find("blocking QA finding(s) unresolved")
        blk = RSRC[i15:i15 + 1200] if i15 != -1 else ""
        ck(bool(blk) and "IMPLEMENT each fix" in blk,
           "run.py's exit-15 handoff tells the orchestrator to IMPLEMENT")
        ck(bool(blk) and "Dispatch" not in blk and "dispatch" not in blk,
           "...and says nothing about dispatching an agent - exit 15 is not a review round")
        i14 = RSRC.find("independent QA review needed (exit 14)")
        ck(i14 != -1 and "CONCURRENTLY" in RSRC[i14:i14 + 800],
           "exit 14 remains the ONE dispatch, concurrent, one agent per prompt")


def legacy_multi_round_folds_honestly() -> None:
    print("\n4. a work dir that ALREADY carries more than one round is folded, honestly")
    old_adv = "G-trace: all 12 areas are the tracker's GIA gross total"
    new_adv = "G-visual: Compare columns crowd at 12+ properties"
    kept_blk = "G-honesty: property=3 field=breeam issue=fabricated grade"
    fixed_blk = "G-honesty: property=1 field=rent issue=untraceable value"
    with tempfile.TemporaryDirectory() as td_s:
        w = _work(Path(td_s))
        fid_fixed = GR.finding_id(fixed_blk)
        (w / "qa_state.json").write_text(json.dumps({
            "schema_version": 2, "run_key": GR._qa_run_key(w), "advisory_carried": [],
            "rounds": [
                {"n": 1, "blocking": [kept_blk, fixed_blk], "advisory": [old_adv],
                 "verdicts": {"G-trace": "amber"}, "recorded": True,
                 "resolved": {fid_fixed: {"finding": fixed_blk,
                                          "because": "re-traced it to the tracker cell and "
                                                     "corrected the value",
                                          "fingerprint": "aaaa"}}},
                {"n": 2, "blocking": [], "advisory": [new_adv],
                 "verdicts": {"G-visual": "green"}, "recorded": True},
            ]}), encoding="utf-8")
        ck(GR.qa_round_number(w) == 2, "the fixture really carries TWO rounds before the fold")
        _review(w, 3, "G-images", "- advisory: the hero is an estate-wide aerial\n")
        rc, out = _rec(w)
        ck(rc == 0, f"record does NOT crash on it (rc={rc}) {ascii(out[:120])}")
        ck(GR.qa_round_number(w) == 1,
           f"it is folded to ONE round ({GR.qa_round_number(w)})")
        st = _state(w)
        cur = st["rounds"][0]
        ck("Folded into ONE round" in out and "nothing discarded" in out,
           f"...and it SAYS SO, rather than folding silently {ascii(out[:160])}")
        # the advisory list is the LATEST round's, never the union (B26)
        ck(new_adv in cur["advisory"], "the latest round's advisory survives")
        ck(old_adv not in cur["advisory"],
           "the SUPERSEDED round's advisory is NOT unioned in - a fresh reviewer judged the "
           "artefact after it, so shipping it would assert a defect that may be fixed (B26)")
        ck(any("estate-wide aerial" in e for e in cur["advisory"]),
           "...and this pass's own review folds in beside it")
        # nothing is DISCARDED: the unrepaired blocking finding is carried forward and OPEN
        _open = {o["finding"] for o in GR.qa_blocking_open(w)}
        ck(kept_blk in _open,
           "the UNRESOLVED blocking finding from the superseded round is carried forward and "
           "still blocks - a false claim may not ship because a later pass did not repeat it")
        ck(fixed_blk not in _open,
           "...while the one with a RECORDED repair stays closed (the resolved maps are "
           "unioned, so the fold cannot re-block a fix)")
        ck(GR.qa_resolved_count(w) == 1, "the recorded repair is kept, once")
        ck(cur.get("verdicts", {}).get("G-trace") == "amber"
           and cur.get("verdicts", {}).get("G-visual") == "green",
           "both rounds' verdict words survive in the audit trail")
        sup = st.get("superseded_rounds") or []
        ck(len(sup) == 1 and (sup[0].get("advisory") or []) == [old_adv],
           f"the superseded round is preserved VERBATIM, not deleted ({len(sup)})")
        rc, out = _rec(w)
        ck(rc == 0 and GR.qa_round_number(w) == 1 and "Folded into ONE round" not in out,
           "the fold is idempotent, and does not re-announce itself once done")
        # ...and the honest state is reportable
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            GR.cmd_qa_round(_Args(mode="status", work=str(w), reviews=""))
        ck("REVIEW-PASS: 1" in buf.getvalue(),
           f"`status` then reports the single pass {ascii(buf.getvalue()[:40])}")

    # a window of two UNRECORDED shells folds too, without inventing a recorded round
    with tempfile.TemporaryDirectory() as td_s:
        w = _work(Path(td_s))
        (w / "qa_state.json").write_text(json.dumps({
            "schema_version": 2, "run_key": GR._qa_run_key(w), "advisory_carried": [],
            "rounds": [{"n": 1, "blocking": [], "advisory": [], "verdicts": {}},
                       {"n": 2, "blocking": [], "advisory": [], "verdicts": {}}],
        }), encoding="utf-8")
        _review(w, 1, "G-honesty", "- advisory: a note\n")
        rc, out = _rec(w)
        ck(rc == 0 and GR.qa_round_number(w) == 1 and len(GR.qa_carried(w)) == 1,
           f"two open shells fold to one recorded round carrying its findings (rc={rc})")


def docs_state_the_shape() -> None:
    print("\n5. the operator-facing guidance states the shape")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    steps = (ROOT / "reference" / "agentic-steps.md").read_text(encoding="utf-8",
                                                                errors="replace")
    for name, txt in (("SKILL.md", skill), ("agentic-steps.md", steps)):
        low = txt.lower()
        ck("a second review round is never correct" in low,
           f"{name} says a second review round is never correct")
        ck("once" in low and "deliver" in low,
           f"{name} states the spawn-once / implement / deliver order")
        ck("cheap and material" in low,
           f"{name} names the advisory rule: blocking, plus any advisory that is cheap and "
           f"material")
        ck("no threshold" in low,
           f"{name} says there is NO threshold for which advisories to fix - it is the "
           f"operator's judgement")
        ck("one edit" in low and ("concludes" in low or "conclude" in low),
           f"{name} gives the judgement in the right voice (one edit; changes what a reader "
           f"concludes)")
    ck("never re-dispatch" in skill.lower() or "not re-dispatch" in skill.lower(),
       "SKILL.md forbids re-dispatching a reviewer")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    one_round_however_many_changes()
    changed_reviews_fold_in()
    fix_loop_still_works()
    legacy_multi_round_folds_honestly()
    docs_state_the_shape()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"QA ONE ROUND TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("QA ONE ROUND TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
