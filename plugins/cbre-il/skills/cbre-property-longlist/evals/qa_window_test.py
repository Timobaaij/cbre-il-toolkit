#!/usr/bin/env python3
"""qa_window_test.py - the QA window's overall behaviour and its CARRY semantics.

The window is now THREE steps: isolated reviewers PROPOSE findings -> the orchestrator
IMPLEMENTS -> deliver. B24 + B26 + B25 are still ONE mechanism, so they are still proved
together, end to end through the real CLI rather than against the functions.

B24: reviews/<gate>.md was flat and round-free, so a re-dispatched reviewer had to overwrite
the standing file - and the harness made it READ that verdict first. Independence is the entire
basis of the judgement gates. The round lives in the path: reviews/round<N>/<gate>.md, N a
dispatch-uniqueness token rather than a budget counter. The flat root stays supported as round 0.
The resolver is UNCHANGED by the restructure and is still pinned here in full.

B26: a finding was a bare prose string with no id, so nothing could be marked resolved and the
Gaps Report asserted defects the improvement pass had fixed. Findings carry a stable id and
`qa-round resolve` records WHY. Also fixed here: qa_carried() read rounds[-1] without checking
`recorded`, so an unrecorded round shell silently dropped EVERY limitation.

B25: final_gate could not say "raised and fixed in-window" - a remediated pack printed plain
ALL-PASS, indistinguishable from one clean first try.

WHAT WENT, and why this file changed. The two-round, verdict-word-gated window with its
adjudication pass is gone: on one live run it produced three ship-blockages that were mechanism
failures rather than data problems, while the data work - five genuine findings, all fixed - was
the small part. Removed: the round budget (QA_MAX_ROUNDS == 1, so there is no second round to
open), `qa-round open` / `diff` / `adjudicate`, gate_runner.qa_gate_remediated,
gate_runner.qa_adjudication_open, and final_gate's verdict-tier sets and verdict-word gating.

ONE EXPECTATION IS DELIBERATELY INVERTED HERE. `resolve` used to REFUSE unless the artefact had
moved since the current round's fingerprint - but that fingerprint was stamped AFTER the repairs,
so by the time you knew a finding was addressed the baseline already contained the fix and
`resolve` was unreachable in the documented order. A delivered Gaps Report shipped a "Known
limitations" line asserting a defect the pack no longer had, contradicting the corrections block in
the same document. So the old assertion "resolve REFUSED while no artefact has changed" now asserts
the OPPOSITE: it SUCCEEDS, with the artefact byte-identical, and the test proves the artefact really
did not move. The guards that carry meaning survive and are still pinned: the id must name a
finding raised in this window, and the reason must be >= 20 characters.

WHAT IS KEPT, and this file exists to prove it is still kept: isolated blind reviewers (one gate,
one agent), the reviewer's OWN blocking:/advisory: labels, the mechanical gates and the freeze as
hard blockers, nothing silently dropped from "Known limitations", and the rule that a `blocking:`
finding - a FALSE CLAIM by the reviewer's own rubric - cannot ship until the orchestrator records
what it changed.

Offline; no network, no build. Writes only into a TemporaryDirectory."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import gate_runner as GR  # noqa: E402
import final_gate as FG  # noqa: E402

GATES = ["G-honesty", "G-trace", "G-images", "G-visual"]

ADV_A = "the tracker's GIA gross total is carried on all 12 records"
ADV_B = "nine of twelve carry the deck name in region"
BLOCK = ("property=3 field=breeam issue=Saxon 132 ships an impossible BREEAM grade "
         "action=strike it to tbd")
WHY = "the improvement pass reconverted all twelve areas from the deck tables"


def _review(verdict="green", findings=()):
    # A `VERDICT:` line is now OPTIONAL and IGNORED - it is written here precisely so the
    # suite proves it no longer gates anything (see section 6).
    body = [f"VERDICT: {verdict}", ""]
    body += [f"- {label}: {text}" for label, text in findings]
    return "\n".join(body) + "\n"


def _qa(work, *argv):
    p = subprocess.run(
        [sys.executable, str(HELPERS / "gate_runner.py"), "qa-round", *argv,
         "--work", str(work)],
        capture_output=True, text=True, errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _gaps(dl: Path, *bullets: str) -> None:
    """A delivered Gaps Report whose "Known limitations" section holds exactly `bullets`."""
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "ACME_Gaps_Report.md").write_text(
        "# Gaps\n\n## Known limitations\n\n"
        + "".join(f"- {b}\n" for b in bullets)
        + "\n## Coverage\n\n- 12 of 12 records carry an area\n", encoding="utf-8")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    td = Path(tempfile.mkdtemp(prefix="cbre_qaw_"))
    work = td / "work"
    (work / "reviews").mkdir(parents=True)
    (work / "inventory.json").write_text(json.dumps({"input_hash": "h1"}), encoding="utf-8")
    (work / "canonical.json").write_text(json.dumps({"properties": [{"id": 1}]}),
                                         encoding="utf-8")

    # ---- B24: the resolver (untouched by the restructure) --------------------
    rv = work / "reviews"
    for fn in ("review_round_dirs", "review_dir_for", "review_file"):
        ck(hasattr(GR, fn), f"gate_runner.{fn} exists")
    if not all(hasattr(GR, f) for f in ("review_round_dirs", "review_dir_for", "review_file")):
        print(f"\nQA WINDOW TEST: FAIL ({len(fails)})")
        return 1

    # round 0 compat: a flat reviews/<gate>.md is still found
    (rv / "G-honesty.md").write_text(_review(), encoding="utf-8")
    ck(GR.review_dir_for(rv) == rv, "no round dirs -> the flat root is round 0")
    ck(GR.review_file(rv, "G-honesty") == rv / "G-honesty.md", "flat gate file resolves")
    ck(GR.review_file(rv, "G-nope") is None, "an unreviewed gate resolves to None")

    # round dirs win, and the newest is the live one. The window records ONE pass, but the
    # path token is still resolved highest-first so a re-dispatch can never be read as the
    # standing verdict of a gate that was not re-dispatched.
    (rv / "round1").mkdir()
    for g in GATES:
        (rv / "round1" / f"{g}.md").write_text(_review(), encoding="utf-8")
    ck(GR.review_dir_for(rv) == rv / "round1", "round1 wins over the flat root")
    (rv / "round2").mkdir()
    (rv / "round2" / "G-images.md").write_text(_review("amber"), encoding="utf-8")
    ck(GR.review_dir_for(rv) == rv / "round2", "the newest round dir is the live dir")
    ck(GR.review_file(rv, "G-images") == rv / "round2" / "G-images.md",
       "a re-dispatched gate resolves to its HIGHER-numbered file")
    ck(GR.review_file(rv, "G-trace") == rv / "round1" / "G-trace.md",
       "a gate NOT re-dispatched keeps its standing round-1 file")
    ck(GR.review_file(rv, "G-images", round_no=1) == rv / "round1" / "G-images.md",
       "an explicit round_no pins the round")
    # the independence property itself: a re-dispatch is a NEW file, never an overwrite
    ck((rv / "round1" / "G-images.md").read_text(encoding="utf-8") == _review(),
       "writing the second dir did NOT touch round 1's bytes")

    # ---- record: ONE review pass, the reviewers' own labels -------------------
    w2 = td / "w2"
    (w2 / "reviews" / "round1").mkdir(parents=True)
    (w2 / "inventory.json").write_text(json.dumps({"input_hash": "h2"}), encoding="utf-8")
    (w2 / "canonical.json").write_text(json.dumps({"p": 1}), encoding="utf-8")
    r1 = w2 / "reviews" / "round1"
    for g in GATES:
        (r1 / f"{g}.md").write_text(_review(), encoding="utf-8")
    (r1 / "G-images.md").write_text(
        _review("amber", [("advisory", ADV_A), ("advisory", ADV_B)]), encoding="utf-8")

    rc, out = _qa(w2, "record", "--reviews", str(w2 / "reviews"))
    ck(rc == 0, f"record exits 0 {ascii(out[-90:])}")
    ck("reviews read from round1" in out,
       "record read the ROUND-SCOPED dir without being pointed at it")
    ck("OK recorded 0 blocking, 2 advisory finding(s)" in out,
       f"it counts the reviewer's OWN labels {ascii(out[:80])}")
    ck("REVIEW-PASS: 1" in out, "it reports a SINGLE review pass")
    ck("ORDER: record -> implement -> resolve -> deliver -> final_gate." in out,
       "record prints the propose -> implement -> deliver order")
    ck(GR.QA_MAX_ROUNDS == 1, f"QA_MAX_ROUNDS is 1 - exactly one round {GR.QA_MAX_ROUNDS}")

    carried = GR.qa_carried(w2)
    ck(len(carried) == 2, f"both advisories are carried ({len(carried)})")
    ck(all(str(e).startswith("G-images: ") for e in carried),
       f"each finding is normalised to '<gate>: <rest>' {ascii(str(carried[:1]))}")

    ids = [GR.finding_id(e) for e in carried]
    ck(len(set(ids)) == 2 and all(len(i) >= 8 for i in ids), "each finding has a stable id")
    ck(GR.finding_id(carried[0]) == GR.finding_id(carried[0].upper()),
       "the id is stable across case")
    ck(all(i in out for i in ids), "record PRINTS the ids so they can be referenced")
    st = json.loads((w2 / "qa_state.json").read_text(encoding="utf-8"))
    ck(st.get("schema_version") == 2, f"state is schema 2 {st.get('schema_version')}")
    ck(len(st.get("rounds") or []) == 1,
       f"exactly ONE round is opened {len(st.get('rounds') or [])}")

    # ---- resolve: the INVERTED expectation ------------------------------------
    # WAS: "resolve REFUSED while no artefact has changed". The freshness guard was stamped
    # AFTER the repairs, so resolve was unreachable in the documented order and a Gaps Report
    # shipped a limitation the pack no longer had. It now SUCCEEDS. (B9)
    fp_before = GR._artefact_fingerprint(w2)
    bytes_before = (w2 / "canonical.json").read_bytes()
    rc, out = _qa(w2, "resolve", "--id", ids[0], "--because", WHY)
    ck(rc == 0, f"resolve SUCCEEDS while no artefact has changed (INVERTED) {ascii(out[-90:])}")
    ck("OK resolved" in out and "nothing changed" not in out.lower()
       and "has not changed" not in out.lower(),
       "...and never prints the old freshness refusal")
    ck(GR._artefact_fingerprint(w2) == fp_before
       and (w2 / "canonical.json").read_bytes() == bytes_before,
       "...and the artefact genuinely did NOT move (so the pass is not an accident)")

    left = GR.qa_carried(w2)
    ck(len(left) == 1 and left[0] == carried[1],
       "the resolved finding leaves Known limitations")
    _struck = set(json.loads((w2 / "qa_state.json").read_text(
        encoding="utf-8"))["rounds"][0]["resolved"])
    ck(carried[1] in left and _struck == {ids[0]},
       f"and nothing was dropped - only the named finding is struck {ascii(str(_struck))}")
    ck(GR.qa_resolved_count(w2) == 1, "the repair is recorded once, with its reason")
    _res = json.loads((w2 / "qa_state.json").read_text(
        encoding="utf-8"))["rounds"][0]["resolved"][ids[0]]
    ck(_res.get("because") == WHY, "the WHY is written into the audit trail verbatim")

    # the guards that DO carry meaning are untouched
    rc, out = _qa(w2, "resolve", "--id", ids[1], "--because", "too short")
    ck(rc != 0 and "20 chars" in out, "resolve REFUSED without a real reason (>= 20 chars)")
    rc, out = _qa(w2, "resolve", "--id", "deadbeef99", "--because",
                  "this id was never recorded in this window at all")
    ck(rc != 0, "resolve REFUSED for an id never raised in this window")
    ck(len(GR.qa_carried(w2)) == 1, "no silent mass-resolution")
    (td / "w_empty").mkdir()
    rc, out = _qa(td / "w_empty", "resolve", "--id", ids[0], "--because", WHY)
    ck(rc != 0 and "no recorded QA round" in out,
       "resolve REFUSED before any round is recorded")

    # a real artefact change is accepted TOO - the guard is gone, not flipped into a refusal
    (w2 / "canonical.json").write_text(json.dumps({"p": 2}), encoding="utf-8")
    rc, out = _qa(w2, "resolve", "--id", ids[0], "--because", WHY)
    ck(rc == 0, f"resolve is also accepted after a real fix {ascii(out[-70:])}")
    ck(GR.qa_carried(w2) == left and GR.qa_resolved_count(w2) == 1,
       "re-recording the same repair neither double-counts nor drops the live limitation")

    # ---- the carry reaches the DELIVERED Gaps Report --------------------------
    # qa_carried() is only half the promise; the other half is that the shipped document says
    # it. final_gate.qa_carry_consistency compares the two, both directions.
    dl = w2 / "deliverables"
    live = GR.qa_carried(w2)[0]
    _gaps(dl, live)
    cs, missing, stale, gf = FG.qa_carry_consistency(dl, w2, w2 / "canonical.json")
    ck(cs == "pass" and not missing and not stale,
       f"a carried advisory survives into the delivered 'Known limitations' {cs}")
    ck(gf is not None and gf.name.endswith("_Gaps_Report.md"),
       "...and the check names the report it actually inspected")
    _gaps(dl, "12 of 12 records carry an area from the tracker")
    cs, missing, stale, _ = FG.qa_carry_consistency(dl, w2, w2 / "canonical.json")
    ck(cs == "fail" and live in missing,
       f"a report that DROPS it is caught, by name {ascii(str(missing)[:60])}")
    _gaps(dl, live, carried[0])
    cs, missing, stale, _ = FG.qa_carry_consistency(dl, w2, w2 / "canonical.json")
    ck(cs == "fail" and carried[0] in stale,
       "a report still asserting the RESOLVED finding is caught as stale")
    _gaps(dl, live)

    # the qa_carried `recorded` hole: an unrecorded round shell must not wipe the limitations.
    # WAS driven by `qa-round open`, which is gone - so the shell is written directly, with the
    # real run_key and schema_version, or _qa_load would discard it and this would pass vacuously.
    raw = (w2 / "qa_state.json").read_text(encoding="utf-8")
    shell = json.loads(raw)
    ck(shell.get("run_key") == GR._qa_run_key(w2), "the state's run_key is the live one")
    shell["rounds"].append({"n": 2, "blocking": [], "advisory": [], "verdicts": {}})
    (w2 / "qa_state.json").write_text(json.dumps(shell), encoding="utf-8")
    ck(GR.qa_carried(w2) == [live],
       "an UNRECORDED round shell does NOT drop the live limitations")
    ck(GR.qa_blocking_open(w2) == [], "...nor invents an open blocking finding")
    (w2 / "qa_state.json").write_text(raw, encoding="utf-8")

    # record is idempotent: it never refuses, never opens a second round, and never resurrects
    # a finding the orchestrator already recorded a repair for.
    rc, out = _qa(w2, "record", "--reviews", str(w2 / "reviews"))
    ck(rc == 0 and "REVIEW-PASS: 1" in out, f"a re-record is accepted, still one pass {rc}")
    ck(len(json.loads((w2 / "qa_state.json").read_text(encoding="utf-8"))["rounds"]) == 1,
       "no second round is ever opened")
    ck(GR.qa_carried(w2) == [live] and GR.qa_resolved_count(w2) == 1,
       "a re-record does not resurrect the resolved finding")
    rc, out = _qa(w2, "status")
    ck(rc == 0 and "REVIEW-PASS: 1" in out and "ADVISORY-CARRIED: 1" in out,
       f"status reports the pass and the carried count {ascii(out[:60])}")

    # ---- a BLOCKING finding keeps the ship gate closed until recorded ---------
    w3 = td / "w3"
    (w3 / "reviews" / "round1").mkdir(parents=True)
    (w3 / "canonical.json").write_text(json.dumps({"p": 1}), encoding="utf-8")
    (w3 / "reviews" / "round1" / "G-honesty.md").write_text(
        _review("red", [("blocking", BLOCK), ("advisory", ADV_B)]), encoding="utf-8")
    rc, out = _qa(w3, "record", "--reviews", str(w3 / "reviews"))
    ck(rc == 0 and "OK recorded 1 blocking, 1 advisory" in out,
       f"record buckets by the reviewer's own label {ascii(out[:70])}")
    op = GR.qa_blocking_open(w3)
    ck(len(op) == 1 and op[0]["finding"].startswith("G-honesty:") and "BREEAM" in op[0]["finding"],
       f"the blocking finding is OPEN, gate-attributed {ascii(str(op)[:70])}")
    ck(bool(op and op[0].get("id")), "...with an id to record the repair against")
    ck(GR.qa_carried(w3) == [f"G-honesty: {ADV_B}"],
       "the advisory carries to Known limitations; the blocking one does not")
    rc, out = _qa(w3, "status")
    ck("BLOCKING-OPEN: 1" in out, "status reports the unaddressed blocking finding")
    rc, out = _qa(w3, "resolve", "--id", op[0]["id"], "--because",
                  "struck breeam to tbd on property 3 and added a gap row citing the source")
    ck(rc == 0, f"the orchestrator can record what it changed {ascii(out[-70:])}")
    ck(GR.qa_blocking_open(w3) == [], "the ship gate opens only once the repair is RECORDED")
    ck(GR.qa_resolved_count(w3) == 1, "and the repair counts as in-window remediation")
    _rc2, out2 = _qa(w3, "status")
    ck("BLOCKING-OPEN: 0" in out2, "status agrees the blocking finding is addressed")

    fg = (HELPERS / "final_gate.py").read_text(encoding="utf-8", errors="replace")
    ck("qa_blocking_open" in fg, "final_gate blocks on any open blocking finding")
    ck('gate("freeze", args.canonical, "--check")' in fg,
       "the freeze is still a HARD mechanical blocker in the reviewed path")
    ck('gate("validate-html"' in fg and 'gate("reconcile"' in fg,
       "...as are the mechanical gates")

    # ---- no verdict-word gating, and the removed surface is really gone -------
    w5 = td / "w5"
    (w5 / "reviews" / "round1").mkdir(parents=True)
    (w5 / "canonical.json").write_text(json.dumps({"p": 1}), encoding="utf-8")
    (w5 / "reviews" / "round1" / "G-visual.md").write_text(
        _review("red", [("advisory", "the hero strip crowds at 1280px")]), encoding="utf-8")
    rc, out = _qa(w5, "record", "--reviews", str(w5 / "reviews"))
    # INVERTED from the old design: a red VERDICT word used to block. The reviewer's per-FINDING
    # label decides now, so a red verdict over advisory-only findings ships with notes.
    ck(rc == 0 and GR.qa_blocking_open(w5) == [],
       "a red VERDICT word with only advisory findings does NOT block (no verdict gating)")
    ck(len(GR.qa_carried(w5)) == 1, "...it carries as a Known limitation instead")

    for mode in ("open", "diff", "adjudicate"):
        rc, out = _qa(w2, mode)
        ck(rc != 0 and ("invalid choice" in out or "usage" in out.lower()),
           f"`qa-round {mode}` no longer exists")
    for gone in ("qa_gate_remediated", "qa_adjudication_open"):
        ck(not hasattr(GR, gone), f"gate_runner.{gone} is gone")
    hp = subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"), "qa-round", "--help"],
                        capture_output=True, text=True, errors="replace")
    ck("{record,status,resolve}" in (hp.stdout or ""),
       f"the modes are exactly record, status, resolve {ascii((hp.stdout or '')[:70])}")
    ck(fg.count("BLOCKING_VERDICTS") == 1,
       "final_gate's blocking-verdict set is retained but never consulted")
    ck(not any(t in fg for t in ("CRITICAL_GATES", "ADVISORY_GATES", "_VERDICT_TIER")),
       "final_gate's verdict-TIER sets are gone - no gate is inherently critical")
    ck("FINDINGS:" in fg and "no labelled findings and no explicit" in fg,
       "a silent reviewer fails safe: a labelled finding or an explicit 'FINDINGS: none'")

    # ---- B25: PASS-WITH-REMEDIATION ------------------------------------------
    ck(hasattr(GR, "qa_resolved_count"), "gate_runner.qa_resolved_count exists")
    if hasattr(GR, "qa_resolved_count"):
        ck(GR.qa_resolved_count(w2) == 1, "one remediation is counted")
        ck(GR.qa_resolved_count(work) == 0, "a work dir with no QA window counts zero")
    ck("PASS-WITH-REMEDIATION" in fg, "final_gate can emit PASS-WITH-REMEDIATION")
    ck("qa_resolved_count" in fg, "final_gate reads the recorded remediation count")
    gates_md = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8", errors="replace")
    ck("PASS-WITH-REMEDIATION" in gates_md,
       "reference/gates.md's STATUS contract lists the remediated state")

    if fails:
        print(f"\nQA WINDOW TEST: FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nQA WINDOW TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
