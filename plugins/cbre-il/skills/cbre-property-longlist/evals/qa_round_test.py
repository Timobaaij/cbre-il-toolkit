#!/usr/bin/env python3
"""qa_round_test.py - the QA WINDOW: isolated reviewers PROPOSE, the orchestrator IMPLEMENTS, deliver.

WHY THIS EXISTS. The QA stage could iterate forever. `reference/visual-qa.md` literally said
"re-render and re-review with a fresh reviewer UNTIL ZERO HIGH/MED" - an unbounded loop whose exit
condition is a subjective verdict, re-earned from scratch by a deliberately memoryless reviewer
(`gates.md` rule 4 forbids continuity, correctly, for independence). The blocking bar was MED, which
the same file assigns to aesthetics ("crushed layout", "clipped label") - matters of degree, so a
fresh reviewer can always find one more. The only bound anywhere was the prose "~3".

WHY THE TWO-ROUND BUDGET AND THE ADJUDICATION PASS ARE GONE, and why this suite no longer pins them.
The first cut bounded the loop at ONE discovery round plus ONE adjudication round, gated on per-gate
VERDICT WORDS. On one live run that mechanism produced three ship-blockages that were every one of
them a MECHANISM failure rather than a data problem: PASS-WITH-REMEDIATION read blocking findings
from `rounds[-1]`, but `adjudicate` creates that round with `blocking: []` by construction, so a
CRITICAL-tier red could never be cleared even with every finding fixed and recorded (B8); `resolve`
refused unless the artefact had moved since the CURRENT round's fingerprint, which was stamped AFTER
the repairs, so it was unreachable in the documented order and a delivered Gaps Report shipped a
"Known limitations" line asserting a defect the pack no longer had (B9); and the budget itself had to
be reasoned about on every run. The data work - five genuine findings, all fixed - was the small
part. So `QA_MAX_ROUNDS` is 1, `record` opens the single round itself and is IDEMPOTENT, and
`qa-round open` / `diff` / `adjudicate`, `qa_gate_remediated`, `qa_adjudication_open` and
final_gate's verdict-tier sets no longer exist.

WHAT IS KEPT, and what this suite therefore still locks: isolated blind reviewers (one gate, one
agent), the reviewer's OWN `blocking:` / `advisory:` labels, the mechanical gates and the freeze as
hard blockers, and the rule that a `blocking:` finding - a FALSE CLAIM by the reviewer's own rubric -
cannot ship until the orchestrator RECORDS what it changed. What changed is only what counts as
addressed: a recorded repair, not a second reviewer re-blessing it.

WHAT IS DELIBERATELY *NOT* TESTED HERE, because it must not exist: any Python that classifies a
finding's severity. The skill is LLM-driven by design - judging a novel defect on an unseen deck in
an unseen language is a perception call that belongs to the reviewer. Python remembers labels; the
REVIEWER writes `blocking:` / `advisory:` itself. These tests assert that boundary holds (an
unlabelled finding is reported, never guessed at).

Locks:
  1. exactly ONE review pass: `record` self-opens it, is idempotent, and NEVER refuses - a refusal
     made the orchestrator investigate and retry, spending more bash and more agents
  2. the window survives a canonical.json edit but resets for a new corpus  <-- the most likely
     implementation bug: keying on artefact bytes would hand every data fix a fresh window
  3. the reviewer's own labels are recorded verbatim; the long-mandated `[HIGH]/[MED]/[LOW]` format
     still counts as its own judgement; an unlabelled finding is surfaced, not classified
  4. `--reviews` is REQUIRED for `record`: with none it must FAIL, never silently record a
     zero-finding round that wipes every carried limitation (a real false clear)
  5. carried advisory findings reach the Gaps Report's "Known limitations"
  6. final_gate has no verdict tiers and no round budget left; the one kept blocker is a `blocking:`
     finding with no recorded repair, and with no --qa-state nothing QA-specific fires at all
  7. the DELIVERED report's "Known limitations" IS the recorded round's carried list - final_gate
     BLOCKS a report written before the last `record`/`resolve` (the live failure: stale text
     overstating the area basis by 6-13% in the wrong direction). Compared by CONTAINMENT both ways,
     not byte-exact, so the section stays curatable and localisable. Includes the anti-deadlock
     proof: without qa_state.json in run.py's _deliver_inputs, `--resume` (the DEFAULT) skips
     Stage 7 and the block is unclearable via the spine.

Offline. Run: python evals/qa_round_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import deliver as DEL  # noqa: E402
import final_gate as FG  # noqa: E402
import gate_runner as GR  # noqa: E402


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _work(td: Path, input_hash: str = "abc123") -> Path:
    w = td / "work"
    w.mkdir(parents=True, exist_ok=True)
    (w / "inventory.json").write_text(json.dumps({"folder": "x", "input_hash": input_hash}),
                                      encoding="utf-8")
    return w


def _reviews(td: Path, name: str, body: str) -> Path:
    r = td / "reviews"
    r.mkdir(parents=True, exist_ok=True)
    (r / f"{name}.md").write_text(body, encoding="utf-8")
    return r


def _rec(w: Path, reviews) -> tuple:
    """`qa-round record` through the real command, output captured. Returns (rc, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = GR.cmd_qa_round(_Args(mode="record", work=str(w), reviews=str(reviews)))
    return rc, buf.getvalue()


def _qa(w: Path, mode: str, **kw) -> tuple:
    """Any other qa-round mode through the real command. Returns (rc, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = GR.cmd_qa_round(_Args(mode=mode, work=str(w), reviews="", **kw))
    return rc, buf.getvalue()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    gsrc = (HELPERS / "gate_runner.py").read_text(encoding="utf-8")

    # ---------- 1 + 2: ONE review pass, keyed on the CORPUS not the artefact ----------
    print("The window is ONE review pass, keyed on the CORPUS not the artefact")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        r = _reviews(td, "G-visual", "- advisory: Compare columns crowd at 12+ properties\n")
        rc1, _ = _rec(w, r)
        ck(rc1 == 0, "`record` opens and records the single review pass in one command")
        ck(GR.qa_round_number(w) == 1, "one round exists after the first `record`")
        # A RE-RECORD IS NOT A FAILURE. The old cut returned 1 with `[FAIL]`/`STATUS: BLOCKED` once
        # the budget was spent, which an orchestrator reads as a broken command - so it investigated
        # and retried, spending MORE bash and MORE agents exactly when the bound was reached. That
        # inverted the purpose of the bound and was a live regression.
        rc2, out2 = _rec(w, r)
        ck(rc2 == 0, "a re-record exits 0 - an already-recorded window is a normal state")
        ck("FAIL" not in out2 and "BLOCKED" not in out2,
           "and it is never PHRASED as a failure the orchestrator should investigate")
        ck("deliver" in out2.lower(), "it says what to do next (deliver)")
        ck("ROUND:" not in out2 and "/2" not in out2 and "COMPLETE" not in out2,
           "no round budget is printed or implied any more (there is nothing to ration)")
        ck(GR.qa_round_number(w) == 1, "the counter stops at ONE pass, it does not creep")
        # a legitimate DATA FIX must NOT mint a fresh window
        (w / "canonical.json").write_text(json.dumps({"meta": {}, "properties": [{"id": 1}]}),
                                          encoding="utf-8")
        ck(GR.qa_round_number(w) == 1,
           "a canonical.json edit does NOT reset the window (keyed on work dir + input hash, "
           "never on the artefact SHA - else every data fix restores the infinite loop)")
        ck(GR.qa_carried(w) == ["G-visual: Compare columns crowd at 12+ properties"],
           "...and the recorded findings survive the edit intact")
        # a genuinely different corpus in the same work dir SHOULD start a new window
        (w / "inventory.json").write_text(json.dumps({"folder": "y", "input_hash": "zzz999"}),
                                          encoding="utf-8")
        ck(GR.qa_round_number(w) == 0, "a DIFFERENT corpus starts a fresh QA window")
        ck(GR.qa_carried(w) == [], "...carrying nothing over from the previous corpus")

    # ---------- 4: --reviews is REQUIRED for `record` (the false-clear bug) ----------
    print("\n`record` REFUSES without --reviews rather than recording a zero-finding round")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        r = _reviews(td, "G-visual", "- advisory: Compare columns crowd at 12+ properties\n")
        _rec(w, r)
        before = GR.qa_carried(w)
        ck(before, "a round with a carried limitation is on disk to be endangered")
        # "required" was PROSE ONLY: argparse defaults --reviews to "", Path("") is ".", and "."
        # exists - so `record --work W` with no --reviews globbed the CURRENT DIRECTORY, found no
        # verdicts, and still marked the round recorded. A zero-finding round wipes every carried
        # limitation and prints "no blocking findings ... DELIVER": a silent false clear. (B44)
        rc, out = _rec(w, "")
        ck(rc == 1, "no --reviews FAILS (exit 1), it does not record an empty round")
        ck("--reviews is required" in out, "and says which argument is missing")
        ck("STATUS: BLOCKED" in out, "with the machine-readable BLOCKED status")
        ck(GR.qa_carried(w) == before,
           "THE POINT: the carried limitations survive the refusal - a false clear erased them")
        ck(GR.qa_round_number(w) == 1, "and no extra round is persisted by the refusal")
        rc, out = _rec(w, td / "nope")
        ck(rc == 1 and "reviews dir not found" in out,
           "a --reviews path that does not exist FAILS too (never silently zero findings)")
        ck(GR.qa_carried(w) == before, "...and again leaves the recorded round untouched")

    # ---------- review discovery is ROUND-SCOPED, with the flat root as round 0 ----------
    print("\nReview discovery is round-scoped (reviews/round<N>/), flat root = round 0")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        root = td / "reviews"
        (root / "round1").mkdir(parents=True, exist_ok=True)
        # the round is in the PATH so a re-dispatched reviewer writes a NEW file - a flat path
        # could only be re-used by OVERWRITING, which made an ostensibly independent reviewer
        # read the previous verdict first. Reviewer independence is the whole basis of the
        # judgement gates. (B24)
        (root / "round1" / "G-visual.md").write_text(
            "- advisory: round1 says the Compare columns crowd\n", encoding="utf-8")
        (root / "G-images.md").write_text(
            "- advisory: the flat root holds this gate's only verdict\n", encoding="utf-8")
        ck([n for n, _ in GR.review_round_dirs(root)] == [1],
           "review_round_dirs finds round1/ and ignores the loose *.md files")
        ck(GR.review_dir_for(root, 1).name == "round1",
           "review_dir_for(root, 1) is round1/, not the root")
        flat = td / "flat"
        flat.mkdir(parents=True, exist_ok=True)
        ck(GR.review_dir_for(flat, 1) == flat,
           "a flat root with no round dirs is still supported permanently, as round 0")
        ck(GR.review_file(root, "G-images", 1) == root / "G-images.md",
           "review_file falls DOWN to the flat root, so a gate reviewed once is not 'never "
           "reviewed' (that blocked a shippable pack)")
        ck(GR.review_file(root, "G-nosuch", 1) is None, "and an unreviewed gate reports None")
        rc, out = _rec(w, root)
        ck(rc == 0 and "reviews read from round1" in out,
           f"`record` names the round dir it actually read {ascii(out[:60])}")
        carried = GR.qa_carried(w)
        ck(any("round1 says" in c for c in carried), "the round1/ finding is recorded")
        ck(not any("flat root holds" in c for c in carried),
           "and the loose root file is NOT double-read once a round dir exists")

    # ---------- 3: the reviewer classifies; Python only records ----------
    print("\nThe REVIEWER labels findings; Python records them verbatim and never classifies")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        r = _reviews(td, "G-visual",
                     "- blocking: property=3 field=plan issue=Site Plan shows a location map "
                     "action=clear p.plan\n"
                     "- advisory: Compare columns crowd at 12+ properties\n"
                     "- advisory: modal header tight on long German labels\n"
                     "- [MED] this line has a severity but NO blocking/advisory label\n"
                     "- this line carries NO label and NO severity at all\n"
                     "VERDICT: red\n")
        rc, out = _rec(w, r)
        st = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))
        cur = st["rounds"][-1]
        ck(rc == 0, "record succeeds")
        ck(len(cur["blocking"]) == 1 and "location map" in cur["blocking"][0],
           "the reviewer's `blocking:` finding is recorded as blocking")
        # 3, not 2: the two explicit `advisory:` lines PLUS the `[MED]` line, which is read via
        # the reviewer's own severity so an older-format review needs no correction round
        ck(len(cur["advisory"]) == 3,
           f"both `advisory:` lines AND the older-format [MED] line are recorded "
           f"({len(cur['advisory'])})")
        # THE BOUNDARY: a finding with neither label nor severity is NOT guessed at
        ck(not any("NO label and NO severity" in f
                   for f in cur["blocking"] + cur["advisory"]),
           "a finding with NO label and NO severity is classified into NEITHER bucket")
        ck("OK recorded 1 blocking, 3 advisory finding(s)" in out,
           f"the counts it reports back are the reviewer's own {ascii(out[:60])}")
        ck(set(GR._SEVERITY_BUCKET) == {"high", "med", "medium", "low", "env"}
           and GR._SEVERITY_BUCKET["high"] == "blocking"
           and set(GR._SEVERITY_BUCKET.values()) == {"blocking", "advisory"},
           "the fallback maps the reviewer's SEVERITY WORD and nothing else - no text inspection")
        ck(cur["blocking"][0].startswith("G-visual: "),
           "each finding is normalised to '<gate>: <rest>', so it is gate-attributed")
        ck(cur["verdicts"].get("G-visual") == "red",
           "the verdict word is still captured for the audit trail (nothing gates on it now)")
        ck(GR.qa_carried(w) == cur["advisory"], "qa_carried() exposes the advisory findings")
        ck(f"BLOCKING {GR.finding_id(cur['blocking'][0])}" in out,
           "the BLOCKING finding's id is PRINTED - `resolve --id` needs it, and it used to have "
           "to be derived by importing gate_runner and calling finding_id() by hand")
        ck(all(f"ADVISORY {GR.finding_id(e)}" in out for e in cur["advisory"]),
           "every advisory id is printed too")
        ck("REVIEW-PASS: 1" in out and "BLOCKING: 1" in out,
           "it prints the pass and the blocking count in machine-readable form")
        ck("NEXT:" in out, "and tells the orchestrator what to do, so it never reasons its way "
                           "into another command")
        ck("ORDER: record -> implement -> resolve -> deliver -> final_gate." in out,
           "the whole remaining order is printed on every record")
    # a verdict line is now OPTIONAL - the labels carry the meaning
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        r = _reviews(td, "G-trace", "- blocking: property=1 field=rent issue=untraceable value\n")
        rc, out = _rec(w, r)
        ck(rc == 0 and "1 blocking, 0 advisory" in out,
           "a review with NO `VERDICT:` line still records its findings (the word is optional)")
        st = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))
        ck(st["rounds"][-1]["verdicts"] == {},
           "...and no verdict is invented for it")
        ck(FG.parse_verdict("- blocking: x\n") is None
           and FG.parse_verdict("VERDICT: red\n") == "red",
           "parse_verdict survives for reviewers that still write one, and reports None otherwise")

    # ---------- COST: one command, and the format the reviewers already write ----------
    print("\nthe QA window costs ONE command and accepts the ESTABLISHED finding format")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        # a reviewer using the long-mandated `- [HIGH|MED|LOW]` format must need NO correction:
        # the first cut only accepted blocking:/advisory:, so a compliant review looked
        # "unlabelled" and invited ANOTHER agent - the extra-round cost this feature must remove
        r = _reviews(td, "G-visual",
                     "- [HIGH] property=3 field=plan issue=Site Plan shows a location map\n"
                     "- [MED] Compare columns crowd at 12+ properties\n"
                     "- [ENV] map tiles blocked in the preview sandbox\n"
                     "VERDICT: red\n")
        rc, out = _rec(w, r)
        st = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))
        ck(rc == 0 and GR.qa_round_number(w) == 1,
           "`record` alone opens and records the pass - no separate `open` call exists any more")
        ck(len(st["rounds"][-1]["blocking"]) == 1,
           "a [HIGH] counts as the reviewer's own 'this blocks'")
        ck(len(st["rounds"][-1]["advisory"]) == 2,
           f"[MED] and [ENV] count as advisory ({len(st['rounds'][-1]['advisory'])})")
        ck("REVIEW-PASS: 1" in out and "BLOCKING: 1" in out,
           "it prints the pass and the blocking count in machine-readable form")
        ck("NEXT: IMPLEMENT" in out,
           "with a blocking finding open, NEXT names the orchestrator's own job (implement)")
        rc2, _ = _rec(w, r)
        ck(rc2 == 0 and GR.qa_round_number(w) == 1,
           "a second `record` does NOT mint a second round")
        rc3, _ = _rec(w, r)
        ck(rc3 == 0 and GR.qa_round_number(w) == 1,
           "nor does a third - `record` is idempotent, and QA_MAX_ROUNDS is the reason")
        _after = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))["rounds"][-1]
        ck(len(_after["advisory"]) == 2 and len(_after["blocking"]) == 1,
           f"and re-recording the same reviews does not duplicate their findings "
           f"({len(_after['blocking'])}b/{len(_after['advisory'])}a)")
        ck(GR.QA_MAX_ROUNDS == 1, "QA_MAX_ROUNDS is 1: the window is exactly one review pass")
        ck('choices=["record", "status", "resolve"]' in gsrc,
           "the CLI offers exactly the three surviving modes (open/diff/adjudicate are gone)")
        ck(not hasattr(GR, "qa_gate_remediated") and not hasattr(GR, "qa_adjudication_open"),
           "the two-round helpers qa_gate_remediated / qa_adjudication_open are gone")

    # ---------------- carried findings must describe the CURRENT artefact ----------------
    print("\nqa_carried() is the LATEST recorded round's list, never the union")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        # Written straight to disk with a real run_key and schema_version 2 (else `_qa_load`
        # discards it and every assertion below would pass for the wrong reason). deliver.py and
        # final_gate both read qa_carried(), so its contract is asserted here directly: unioning
        # across rounds shipped a stale note as a live limitation - caught on a live run, where the
        # Gaps Report told the broker "all 12 carry the tracker's GIA gross total" after the fixes
        # had already corrected 11 of them. A Known-limitations list that misdescribes the delivered
        # data is a false statement in the one document whose job is honesty.
        old = "G-trace: all 12 areas are the tracker's GIA gross total"
        new = "G-trace: Compare columns crowd at 12+ properties"
        (w / "qa_state.json").write_text(json.dumps({
            "schema_version": 2, "run_key": GR._qa_run_key(w), "advisory_carried": [],
            "rounds": [
                {"n": 1, "blocking": [], "advisory": [old], "verdicts": {}, "recorded": True},
                {"n": 2, "blocking": [], "advisory": [new], "verdicts": {}, "recorded": True},
            ]}), encoding="utf-8")
        carried = GR.qa_carried(w)
        ck(not any("GIA gross total" in f for f in carried),
           f"a superseded earlier finding is NOT carried once a later round re-judged the "
           f"artefact ({carried})")
        ck(carried == [new], "only the latest recorded round's own findings are carried")
        # a round that is merely OPEN is an empty shell: reading it silently vanished every
        # limitation while final_gate still passed - a resolve-everything path with no resolve
        st = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))
        st["rounds"].append({"n": 3, "blocking": [], "advisory": [], "verdicts": {}})
        (w / "qa_state.json").write_text(json.dumps(st), encoding="utf-8")
        ck(GR.qa_carried(w) == [new], "an UNRECORDED round is skipped, not read as 'nothing open'")
        # a RESOLVED finding was fixed, on the record - it must not ship as a limitation
        st["rounds"][1]["resolved"] = {GR.finding_id(new): {"finding": new, "because": "x" * 25}}
        (w / "qa_state.json").write_text(json.dumps(st), encoding="utf-8")
        ck(GR.qa_carried(w) == [], "a RESOLVED advisory is struck from the carried list")
        ck(GR.qa_resolved_count(w) == 1,
           "qa_resolved_count counts it, which is what makes PASS-WITH-REMEDIATION reachable")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        # a window written by the two-round/verdict-gated design carries an `adjudication` map and
        # a budget this code no longer understands: start fresh rather than half-read it, or a
        # misread state could mark a blocking finding addressed when it was not
        (w / "qa_state.json").write_text(json.dumps({
            "schema_version": 1, "run_key": GR._qa_run_key(w), "advisory_carried": [],
            "rounds": [{"n": 1, "blocking": ["G-honesty: fabricated rent"], "advisory": ["x"],
                        "recorded": True, "adjudication": {"deadbeef": {"verdict": "not fixed"}}}],
        }), encoding="utf-8")
        ck(GR.qa_round_number(w) == 0 and GR.qa_carried(w) == []
           and GR.qa_blocking_open(w) == [],
           "a schema-1 window is discarded as a fresh window, never partially interpreted")

    # ---------- `status` reports the window without budget arithmetic ----------
    print("\n`status` reports the pass, the carried count and what is still unaddressed")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        r = _reviews(td, "G-honesty",
                     "- blocking: property=2 field=breeam issue=impossible grade action=strike\n"
                     "- advisory: two region granularities across the dataset\n")
        _rec(w, r)
        rc, out = _qa(w, "status")
        ck(rc == 0, "status exits 0")
        ck("REVIEW-PASS: 1" in out, "it reports the single review pass")
        ck("BLOCKING: 1" in out, "how many blocking findings the reviewers raised")
        ck("ADVISORY-CARRIED: 1" in out, "how many advisories will ship as Known limitations")
        ck("BLOCKING-OPEN: 1" in out,
           "and how many blocking findings still have NO recorded repair - what final_gate blocks on")
        ck("ROUND:" not in out and "/2" not in out and "ADJUDICATION-OPEN" not in out,
           "no round budget and no adjudication state are reported (neither exists)")
        fid = GR.qa_blocking_open(w)[0]["id"]
        _qa(w, "resolve", id=fid, because="struck the field to tbd and logged the gap row")
        rc, out = _qa(w, "status")
        ck("BLOCKING-OPEN: 0" in out, "a recorded repair closes BLOCKING-OPEN")
        ck("BLOCKING: 1" in out,
           "...while BLOCKING still says the finding was RAISED (the record is not rewritten)")

    # ---------- `resolve`: the guards that carry meaning, and the one that did not ----------
    print("\n`resolve` records a repair: a real id and a real reason, and NO freshness guard")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        (w / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}),
                                          encoding="utf-8")
        rc, out = _qa(w, "resolve", id="deadbeef00", because="a long enough reason string here")
        ck(rc == 1 and "no recorded QA round" in out,
           "resolve before any `record` FAILS - there is nothing to resolve against")
        r = _reviews(td, "G-honesty",
                     "- blocking: property=2 field=breeam issue=impossible grade action=strike\n"
                     "- advisory: two region granularities across the dataset\n")
        _rec(w, r)
        fid = GR.qa_blocking_open(w)[0]["id"]
        rc, out = _qa(w, "resolve", id="nosuchid00", because="a perfectly long and plausible reason")
        ck(rc == 1 and "no finding with id" in out,
           "an id that was never raised in this window is refused")
        ck(f"BLOCKING {fid}" in out,
           "...and the refusal lists the real ids, so the next attempt cannot guess wrong")
        rc, out = _qa(w, "resolve", id=fid, because="too short")
        ck(rc == 1 and "20 chars" in out,
           "a reason under 20 chars is refused - a resolve is a claim about the artefact")
        ck(GR.qa_blocking_open(w) and GR.qa_blocking_open(w)[0]["id"] == fid,
           "...and the finding is still open after both refusals")
        # NO ARTEFACT-FRESHNESS GUARD (B9). It used to refuse unless the artefact had moved since
        # THIS round's fingerprint - stamped AFTER the repairs, so by the time you knew a finding
        # was addressed the baseline already contained the fix and `resolve` was unreachable in the
        # documented order. The consequence was not cosmetic: a delivered Gaps Report shipped a
        # "Known limitations" line asserting a defect the pack no longer had.
        rc, out = _qa(w, "resolve", id=fid,
                      because="struck breeam to tbd and added a gap row citing the empty cell")
        ck(rc == 0, "resolve succeeds with the artefact BYTE-IDENTICAL (no freshness guard left)")
        ck("nothing changed" not in out.lower() and "STATUS: BLOCKED" not in out,
           "...and never prints the old freshness refusal")
        ck(GR.qa_blocking_open(w) == [], "the blocking finding is now addressed")
        st = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))
        ck("empty cell" in st["rounds"][-1]["resolved"][fid]["because"],
           "the WRITTEN REASON is in the audit trail - that is what 'addressed' means now")
        ck("CARRIED:" in out and "deliver.py" in out,
           "and it says to re-run deliver so the delivered report matches the recorded round")
        aid = GR.finding_id(GR.qa_carried(w)[0])
        rc, out = _qa(w, "resolve", id=aid,
                      because="the blocking fix normalised region, so this advisory is now false")
        ck(rc == 0 and GR.qa_carried(w) == [],
           "an ADVISORY can be resolved too, and is then struck from Known limitations")
        ck(GR.qa_resolved_count(w) == 2, "both repairs count toward PASS-WITH-REMEDIATION")

    # ---------- 6: final_gate has no verdict tiers and no round budget ----------
    print("\nfinal_gate: no verdict tiers, no budget - the one blocker is an unaddressed blocking finding")
    src = (HELPERS / "final_gate.py").read_text(encoding="utf-8")
    ck(not hasattr(FG, "QA_ADVISORY_GATES") and not hasattr(FG, "QA_CRITICAL_GATES"),
       "the per-gate verdict TIER sets are gone - the reviewer's own label decides, per FINDING")
    ck("QA_ADVISORY_GATES" not in src and "QA_CRITICAL_GATES" not in src,
       "...and nothing in final_gate still reads them")
    ck("qa_round >= gate_runner.QA_MAX_ROUNDS" not in src,
       "the carry rule no longer keys on a round budget")
    ck(src.count("BLOCKING_VERDICTS") == 1 and src.count("PASSING_VERDICTS") == 1,
       "the verdict word sets are DEFINED but never consulted - no verdict-word gating remains")
    ck("[CARRIED]" in src, "a carried finding is printed, never silently dropped")
    ck('args.qa_state else 0' in src or "if args.qa_state" in src,
       "with no --qa-state nothing QA-specific fires, so an existing flow is unchanged")
    ck("DEGRADED" in src and "no_reviews" in src,
       "--no-reviews reports DEGRADED instead of 'ALL-PASS - shippable'")
    ck("qa_blocking_open(" in src and "checks.extend([False] * len(_open))" in src,
       "an unaddressed BLOCKING finding reaches `checks` (BLOCKING), not just stdout")
    ck("qa-round" in src and "resolve --work" in src,
       "...and the printed remedy is the resolve command, not another review round")
    ck("no labelled findings" in src and "FINDINGS: none" in src,
       "a review with no labelled findings is REPORTED for re-dispatch, never classified by Python")

    # ---------- 5: carried findings reach the Gaps Report ----------
    print("\nCarried advisory findings ship in the Gaps Report's 'Known limitations'")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        r = _reviews(td, "G-visual",
                     "- advisory: Compare columns crowd at 12+ properties\nVERDICT: amber\n")
        _rec(w, r)
        canon = {"meta": {}, "properties": [
            {"id": 1, "park": "P", "city": "C", "country": "GB", "developer": "D",
             "warehouseArea": 10000, "warehouseRent": "tbd"}]}
        md = DEL.gaps_report(canon, "Test", work_dir=w)
        ck("Known limitations" in md, "the section appears when findings were carried")
        ck("Compare columns crowd" in md, "the reviewer's own wording is delivered verbatim")
        # and it must NOT appear when nothing was carried
        w2 = _work(td / "second", "other")
        md2 = DEL.gaps_report(canon, "Test", work_dir=w2)
        ck("Known limitations" not in md2,
           "the section is absent when there is nothing to carry (no empty scaffolding)")
        # a repair the orchestrator RECORDED must not ship as a live limitation
        _qa(w, "resolve", id=GR.finding_id(GR.qa_carried(w)[0]),
            because="widened the Compare grid, the columns no longer crowd at 12 properties")
        md3 = DEL.gaps_report(canon, "Test", work_dir=w)
        ck("Compare columns crowd" not in md3,
           "a RESOLVED advisory disappears from the delivered report (it was fixed, on the record)")

    # ---------- 7: the DELIVERED report must match the RECORDED round (P1-5) ----------
    # deliver.py writes "Known limitations" DURING the spine from qa_carried(<work>); `qa-round
    # record` / `resolve` are SEPARATE commands. Record or resolve AFTER deliver and the shipped
    # report carries the older list. That happened live: the report described the area basis with
    # text the repairs had already corrected, overstating the figures by 6-13% in the WRONG
    # direction. qa_carried() is latest-round-only for exactly this reason; this closes the other
    # half of it - the delivered FILE, not just the in-memory list.
    print("\nThe delivered Gaps Report's 'Known limitations' must be the RECORDED carried list")
    _CANON = {"meta": {}, "properties": [
        {"id": 1, "park": "P", "city": "C", "country": "GB", "developer": "D",
         "warehouseArea": 10000, "warehouseRent": "tbd"}]}

    def _deliver(td: Path, w: Path, slug: str = "Test") -> Path:
        """Write <deliverables>/<slug>_Gaps_Report.md via the REAL writer - never a hand fixture,
        so this section fails the moment deliver.gaps_report's format drifts."""
        d = td / "deliverables"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{slug}_Gaps_Report.md").write_text(
            DEL.gaps_report(_CANON, slug, work_dir=w), encoding="utf-8")
        return d

    def _round(td: Path, w: Path, body: str, name: str = "G-visual") -> None:
        _rec(w, _reviews(td, name, body))

    # (a) THE LIVE SHAPE: deliver ran, then a further reviewer's findings were recorded
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        rroot = _reviews(td, "G-trace", "- advisory: all 12 areas are the tracker's GIA gross "
                                        "total\nVERDICT: amber\n")
        _rec(w, rroot)
        d = _deliver(td, w)                                   # carries ONE finding
        (rroot / "G-images.md").write_text(
            "- advisory: Compare columns crowd at 12+ properties\nVERDICT: amber\n",
            encoding="utf-8")
        _rec(w, rroot)                                        # a second gate's findings land
        cn = str(w / "canonical.json")
        st, missing, stale, gf = FG.qa_carry_consistency(d, str(w), canonical=cn)
        ck(st == "fail", "a report written BEFORE the latest `qa-round record` is caught as STALE")
        ck(any("Compare columns crowd" in m for m in missing),
           "the finding the broker never saw is reported as MISSING")
        ck(not stale, "and the still-current line is NOT mis-reported as stale")
        ck(gf is not None and gf.name == "Test_Gaps_Report.md",
           "the FAIL names the report file it actually inspected")
        # the printed remedy, exactly: ONE deliver re-run, no QA round opened
        _deliver(td, w)
        st2, m2, s2, _ = FG.qa_carry_consistency(d, str(w), canonical=cn)
        ck(st2 == "pass" and not m2 and not s2,
           "re-running deliver clears the block in ONE step (the remedy terminates)")
        ck(GR.qa_round_number(w) == 1, "the remedy spends no QA round (still the one review pass)")

    # (b) the writer and the checker agree on ADVERSARIAL bodies. Non-ASCII lives in the DATA,
    #     never in a check label - a non-Latin label crashes the whole suite on a cp1252 console.
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        _round(td, w, "- advisory: [MED] `warehouseArea` basis - the tracker's GIA total, off by "
                      "6-13% — confirm with the developer (Blåklädder park)\n"
                      "VERDICT: amber\n")
        d = _deliver(td, w)
        st, missing, stale, _ = FG.qa_carry_consistency(d, str(w),
                                                        canonical=str(w / "canonical.json"))
        ck(st == "pass",
           "a severity prefix, backticks, a colon, an em dash and non-ASCII survive the round trip")
        if st != "pass":
            print(f"      missing={ascii(missing)}  stale={ascii(stale)}")

    # (c) CONTAINMENT both directions, NOT byte-exact set equality (PLAN 4.3, lens finding F5).
    #     Locked here so nobody "simplifies" it back to equality. final_gate's own docstring cites
    #     this case as "qa_round_test section 7c" - keep the label.
    #
    #     NOTE THE REAL LIMIT, measured not assumed: qa_carried() returns each entry PREFIXED with
    #     the gate name ("G-visual: ..."), so a bullet only passes if it contains that whole string.
    #     Containment therefore permits curation by ADDING context around an entry - it does NOT
    #     permit rewording it or TRANSLATING it. deliver.py has no i18n today (the Gaps Report is
    #     English-only), so nothing is broken; but if that section is ever localised, this check
    #     must move to comparing a stable finding ID rather than prose. The last case below pins
    #     that boundary so the limitation is discovered by a failing test, not by a blocked run.
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        _round(td, w, "- advisory: Compare columns crowd at 12+ properties\nVERDICT: amber\n")
        d = td / "deliverables"
        d.mkdir(parents=True, exist_ok=True)
        rep = d / "Test_Gaps_Report.md"
        cn = str(w / "canonical.json")
        carried = GR.qa_carried(w)
        ck(carried and carried[0].startswith("G-visual: "),
           "a carried entry keeps its gate-name prefix (what a curated bullet must preserve)")
        rep.write_text("## Known limitations (reviewed and accepted at QA)\n"
                       f"- {carried[0]} - accepted at QA, cosmetic only at this list length\n\n",
                       encoding="utf-8")
        st, missing, stale, _ = FG.qa_carry_consistency(d, str(w), canonical=cn)
        ck(st == "pass" and not missing and not stale,
           "a CURATED bullet that ADDS context around the entry passes (containment, not exact)")
        rep.write_text("## Known limitations (reviewed and accepted at QA)\n"
                       "- Something no reviewer ever said\n\n", encoding="utf-8")
        st, missing, stale, _ = FG.qa_carry_consistency(d, str(w), canonical=cn)
        ck(st == "fail" and stale and missing,
           "containment is not a free pass: an unrelated bullet is STALE, the finding MISSING")
        # the boundary: a REWORDED/translated bullet does NOT satisfy containment
        rep.write_text("## Known limitations (reviewed and accepted at QA)\n"
                       "- Die Compare-Spalten sind bei 12+ Objekten zu eng\n\n", encoding="utf-8")
        ck(FG.qa_carry_consistency(d, str(w), canonical=cn)[0] == "fail",
           "KNOWN LIMIT: a reworded/translated bullet does NOT pass - localising this section "
           "would require a stable finding ID, not prose matching")

    # (d) a limitation the orchestrator FIXED and RECORDED must leave the report - the exact
    #     direction of the live failure
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)
        _round(td, w, "- advisory: Compare columns crowd at 12+ properties\nVERDICT: amber\n")
        d = _deliver(td, w)
        cn = str(w / "canonical.json")
        _qa(w, "resolve", id=GR.finding_id(GR.qa_carried(w)[0]),
            because="widened the Compare grid so the columns no longer crowd at 12 properties")
        ck(GR.qa_carried(w) == [], "a recorded repair leaves nothing to carry")
        st, _, stale, _ = FG.qa_carry_consistency(d, str(w), canonical=cn)
        ck(st == "fail" and any("Compare columns crowd" in s for s in stale),
           "a limitation the orchestrator FIXED is caught as STALE, not shipped")
        _deliver(td, w)
        ck("Known limitations" not in (d / "Test_Gaps_Report.md").read_text(encoding="utf-8"),
           "re-delivering removes the section entirely (no empty scaffolding)")
        ck(FG.qa_carry_consistency(d, str(w), canonical=cn)[0] == "pass", "and the gate passes")

    # (e) INERT offline, and an unsatisfiable comparison WARNs instead of deadlocking
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        w = _work(td)                          # inventory.json but NO qa_state.json
        d = td / "deliverables"
        d.mkdir(parents=True, exist_ok=True)
        (d / "Test_Gaps_Report.md").write_text("# gaps\n", encoding="utf-8")
        ck(FG.qa_carry_consistency(d, str(w))[0] == "skip",
           "INERT with no recorded QA round (fixture_test / extract_test unaffected)")
        ck(FG.qa_carry_consistency(d, "")[0] == "skip", "INERT when --qa-state is omitted")
        _round(td, w, "- advisory: x\nVERDICT: amber\n")
        other = td / "elsewhere"
        other.mkdir(parents=True, exist_ok=True)
        stt, mm, ss, _ = FG.qa_carry_consistency(d, str(w),
                                                 canonical=str(other / "canonical.json"))
        ck(stt == "skip-mismatch" and not mm and not ss,
           "a mismatched work dir WARNs (skip-mismatch), never blocks - it is unsatisfiable")

    src = (HELPERS / "final_gate.py").read_text(encoding="utf-8")
    _wired = 'elif _cs != "skip"' in src and 'checks.append(_cs == "pass")' in src
    ck(_wired, "the result reaches `checks` (BLOCKING), not just stdout")
    ck(_wired and src.index('elif _cs != "skip"') < src.index('checks.append(_cs == "pass")'),
       "checks.append sits INSIDE the non-skip branch, so a skip appends nothing")
    ck("_Gaps_Report.md" in src and "--slug" in src,
       "the FIX line derives the slug from the inspected report (a guessed slug writes a 2nd file)")

    # (f) the remedy is REACHABLE through the spine. Without this, `run.py --resume` (resume is the
    #     DEFAULT) skips Stage 7 forever and the new block is unclearable via the spine.
    print("\nThe remedy is reachable through the spine (anti-deadlock)")
    rsrc = (HELPERS / "run.py").read_text(encoding="utf-8")
    _dl = rsrc.split("_deliver_inputs = [", 1)
    ck(len(_dl) == 2 and 'work / "qa_state.json"' in _dl[1].split("]", 1)[0],
       "run.py lists qa_state.json in _deliver_inputs, so a new record/resolve re-fires Stage 7")
    import os as _os  # noqa: E402
    import run as RUN  # noqa: E402
    _saved_resume = RUN.RESUME
    RUN.RESUME = True
    try:
        with tempfile.TemporaryDirectory() as td_s:
            td = Path(td_s)
            out = td / "out.html"
            out.write_text("x", encoding="utf-8")
            om = out.stat().st_mtime
            old = td / "old.json"
            old.write_text("{}", encoding="utf-8")
            _os.utime(old, (om - 60, om - 60))
            ck(RUN._is_current(out, [old]) is True,
               "_is_current: an OLDER input leaves the stage resume-skipped")
            qs = td / "qa_state.json"
            qs.write_text("{}", encoding="utf-8")
            _os.utime(qs, (om + 60, om + 60))
            ck(RUN._is_current(out, [old, qs]) is False,
               "_is_current: a NEWER qa_state.json forces exactly ONE re-deliver")
            ck(RUN._is_current(out, [old, td / "absent.json"]) is True,
               "_is_current skips a non-existent input, so offline runs are unaffected")
    finally:
        RUN.RESUME = _saved_resume

    # ---------- 6 (prose): the unbounded instructions are gone from reviewer-facing text ----------
    print("\nThe unbounded instructions are gone from the reviewer-facing prose")
    vq = (HELPERS.parent / "reference" / "visual-qa.md").read_text(encoding="utf-8")
    ck("until zero HIGH/MED" not in vq,
       "'re-review ... until zero HIGH/MED' is removed from visual-qa.md")
    ck("blocking:" in vq and "advisory:" in vq,
       "visual-qa.md tells the reviewer to label each finding itself")
    gd = (HELPERS.parent / "reference" / "gates.md").read_text(encoding="utf-8")
    ck("Bounded loops (~3)" not in gd, "the vague '~3' bound is replaced in gates.md")
    ck("qa-round" in gd, "gates.md points at the qa-round command")
    sk = (HELPERS.parent / "SKILL.md").read_text(encoding="utf-8")
    ck("The QA window" in sk and "qa-round" in sk,
       "SKILL.md documents the QA window for the orchestrator")

    print(f"\n{'OK' if not fails else 'FAIL'} qa_round_test: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
