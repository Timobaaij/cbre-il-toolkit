#!/usr/bin/env python3
"""adjudicate_test.py - the REPAIR-VERIFICATION end of the QA window. (B44, restructured)

The window is now three steps: isolated reviewers PROPOSE findings -> the orchestrator IMPLEMENTS
-> deliver. This suite owns the second half of that: what happens to a `blocking:` finding between
being proposed and being shipped.

WHY THE OLD DESIGN WENT. This file used to pin `record -> fix -> diff -> ADJUDICATE -> resolve`: a
two-round budget in which a second reviewer, handed the finding list and a field-level data diff,
re-blessed the repair before it could ship. On one live run that mechanism produced three
ship-blockages that were mechanism failures rather than data problems - a CRITICAL-tier red that no
amount of fixing could clear because `adjudicate` created the final round with `blocking: []`; a
`resolve` made unreachable by an artefact-freshness guard stamped AFTER the repairs, which shipped a
Gaps Report asserting a defect the pack no longer had; and a round budget that had to be reasoned
about on every run. So `qa-round open`, `qa-round diff` and `qa-round adjudicate` are gone, the
budget is gone (QA_MAX_ROUNDS = 1, one round, `record` idempotent), and per-gate verdict-word gating
is gone - a `VERDICT:` line is optional and IGNORED.

WHAT IS KEPT, and what this suite therefore proves is still kept:
  1. A `blocking:` finding is a FALSE CLAIM by the reviewer's own rubric, so it BLOCKS until the
     orchestrator records what it changed. `qa_blocking_open` is the whole safety property; without
     it the restructure would just be "stop checking".
  2. Recording that repair needs NO artefact change. The byte-identity assertion below is the
     regression test for the guard that made `resolve` unreachable in the documented order.
  3. An advisory CARRIES into the Gaps Report's "Known limitations"; it never blocks, and it is
     struck from that list only by a recorded `resolve` - a limitations list that misdescribes the
     delivered data is a false statement in the one document whose job is honesty.
  4. Silence still fails safe: final_gate needs each expected reviewer file to EXIST and to say
     something, either a labelled finding or an explicit `FINDINGS: none`.
  5. And final_gate must still be ABLE to check any of that. Ripping a QA function out without
     cleaning up its caller already broke this once, in a way no per-function test could see: the
     `--qa-state` mode - the only one that can block on an unaddressed finding - died on
     AttributeError before printing a line, so the safety property above was silently unreachable.
A hole and a loop are the two ways this fails: shipping an unrepaired false claim, or making the
repair unrecordable so the window cannot close. Offline, drives the real gate_runner CLI."""
from __future__ import annotations
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import gate_runner as GR  # noqa: E402
import final_gate as FG  # noqa: E402

PX = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg" + "A" * 400
BLOCK = "the Raven Park rent renders EUR 7.25 / sq m but the deck states GBP 7.25 per sq ft"
ADV = "nine of twelve carry the deck name in region"
WHY = "reworked the rent basis to sq ft exactly as the deck states it"


def _canon(rent="EUR7.25 / sq m / year", extra=None):
    p = {"id": 1, "park": "Raven Park", "city": "Corby", "country": "GB", "developer": "D",
         "warehouseArea": 120000, "areaUnit": "sq ft", "warehouseRent": rent,
         "photo": PX, "gallery": [PX, PX]}
    if extra:
        p.update(extra)
    return {"meta": {"client": "Acme", "units": {"area": "sq ft"}}, "properties": [p],
            "pois": [], "regions": {}}


def _qa(work, *argv):
    r = subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"), "qa-round", *argv,
                        "--work", str(work)],
                       capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _state(work):
    return json.loads((Path(work) / "qa_state.json").read_text(encoding="utf-8"))


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_adj_"))
    work = d / "work"
    rv = work / "reviews" / "round1"
    rv.mkdir(parents=True)
    (work / "inventory.json").write_text(json.dumps({"input_hash": "h1"}), encoding="utf-8")
    (work / "canonical.json").write_text(json.dumps(_canon()), encoding="utf-8")
    # Created BEFORE any fingerprint is taken, so the byte-identity assertion in section 4 compares
    # like with like. The mechanical gates and the deliverables will FAIL in a stub work dir; that
    # is fine - every check below reads a SPECIFIC printed line, never the overall verdict.
    (work / "deliverables").mkdir()
    (work / "built.html").write_text("<html>d</html>", encoding="utf-8")

    def _fg(*extra):
        r = subprocess.run([sys.executable, str(HELPERS / "final_gate.py"),
                            "--canonical", str(work / "canonical.json"),
                            "--html", str(work / "built.html"),
                            "--deliverables", str(work / "deliverables"),
                            "--reviews", str(work / "reviews"), *extra],
                           capture_output=True, text=True, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    # --- 0. one round, and nothing to repair before anything is recorded ------
    ck(GR.QA_MAX_ROUNDS == 1, f"the round budget is gone: QA_MAX_ROUNDS == 1 ({GR.QA_MAX_ROUNDS})")
    rc, out = _qa(work, "resolve", "--id", "deadbeef00", "--because",
                  "a plausible sounding reason of ample length")
    ck(rc != 0 and "no recorded QA round" in out,
       "`resolve` before any `record` is refused - a repair is a claim about a RAISED finding")
    ck(GR.qa_blocking_open(work) == [], "qa_blocking_open with no rounds at all is [] (inert)")

    # --- 1. record: the reviewer's OWN labels, verdict word ignored -----------
    for g in ("G-trace", "G-images", "G-visual"):
        (rv / f"{g}.md").write_text("FINDINGS: none\n", encoding="utf-8")
    # `VERDICT: green` on a file that ALSO raises a blocking finding: under the old design the
    # per-gate verdict word decided, so this pairing is exactly what must no longer be gated on.
    (rv / "G-honesty.md").write_text(
        f"VERDICT: green\n\n- blocking: {BLOCK}\n- advisory: {ADV}\n", encoding="utf-8")
    rc, rec = _qa(work, "record", "--reviews", str(work / "reviews"))
    ck(rc == 0, f"record succeeds (rc={rc}) {ascii(rec[-70:])}")
    ck("OK recorded 1 blocking, 1 advisory finding(s)" in rec,
       f"it counts the reviewer's own blocking:/advisory: labels {ascii(rec[:80])}")
    ck("reviews read from round1" in rec,
       "--reviews names the reviews ROOT and `record` reads round1/ itself (a flat root is round 0)")
    ck("REVIEW-PASS: 1" in rec and "BLOCKING: 1" in rec, "it reports one review pass, one blocker")

    snap = work / "canonical_review.round1.json"
    ck(snap.exists(), "`record` snapshots the round's BEFORE (`open` used to, and `open` is gone)")
    body = snap.read_text(encoding="utf-8")
    ck("data:image" not in body and "base64" not in body,
       "the snapshot is photo-STRIPPED (an unstripped copy is tens of MB, 99.56% base64 by weight)")

    st = _state(work)
    ck(len(st["rounds"]) == 1, f"exactly ONE round exists ({len(st['rounds'])})")
    ck(GR.qa_round_number(work) == GR.QA_MAX_ROUNDS,
       f"...and the window is complete at that round ({GR.qa_round_number(work)})")
    ck(st.get("schema_version") == 2, f"state is schema 2 ({st.get('schema_version')})")

    # --- 2. the blocking finding is OPEN - this is the whole safety property --
    op = GR.qa_blocking_open(work)
    ck(len(op) == 1 and op[0]["finding"].startswith("G-honesty:") and "EUR" in op[0]["finding"],
       f"qa_blocking_open returns it, gate-attributed {ascii(str(op)[:80])}")
    # degrade rather than explode: a regression that empties this list must still reach the
    # STATUS line, so the report names WHICH invariants broke instead of showing a bare traceback.
    bid = op[0]["id"] if op else ""
    ck(bool(bid) and f"BLOCKING {bid}" in rec,
       "record PRINTS the blocking id - the handle `resolve --id` needs, so it is never derived")
    ck(st["rounds"][0].get("verdicts", {}).get("G-honesty") == "green" and len(op) == 1,
       "a `VERDICT: green` line is remembered but IGNORED - it does not suppress the file's own "
       "blocking: finding, and it does not gate")
    car = GR.qa_carried(work)
    ck(len(car) == 1 and "region" in car[0],
       f"the advisory is CARRIED for the Gaps Report's Known limitations {ascii(str(car)[:60])}")
    aid = GR.finding_id(car[0]) if car else ""
    ck(bool(aid) and all(o["id"] != aid for o in op),
       "an advisory NEVER blocks - it is not in qa_blocking_open")
    ck(GR.qa_resolved_count(work) == 0, "an OPEN blocking finding is not counted as a remediation")
    ck(not st["rounds"][0].get("resolved"),
       "...and `resolved` is empty until a repair is actually recorded")
    rc, sout = _qa(work, "status")
    ck(rc == 0 and "BLOCKING-OPEN: 1" in sout,
       f"status reports it OPEN - this is what final_gate blocks on {ascii(sout[:70])}")
    ck("ADVISORY-CARRIED: 1" in sout, "...and the advisory as carried, not open")

    # final_gate is the ship gate, and it must refuse for the same reason
    rc, fg1 = _fg("--qa-state", str(work))
    ck(rc != 0 and "[FAIL] BLOCKING finding not addressed:" in fg1,
       f"final_gate BLOCKS while a blocking finding is unaddressed {ascii(fg1[-80:])}")
    ck("qa-round resolve --work" in fg1 and f"--id {bid}" in fg1,
       "...and prints the EXACT remedy, carrying the finding's own id")

    # the remedy has to be printed, or the orchestrator reasons its way to another command
    ck("qa-round resolve --id" in rec and "--because" in rec, "record prints the EXACT remedy")
    ck("no second review pass" in rec,
       "...and the convergence promise: the reviewers proposed, there is no further review")
    ck("ORDER: record -> implement -> resolve -> deliver -> final_gate." in rec,
       "...and the order the whole window depends on")

    # --- 3. the guards that still bite --------------------------------------- #
    rc, out = _qa(work, "resolve", "--id", bid, "--because", "too short")
    ck(rc != 0 and "20 chars" in out, "a reason under 20 characters is still refused")
    ck(len(GR.qa_blocking_open(work)) == 1,
       "...and a refused resolve leaves the finding OPEN (no half-written repair)")
    rc, out = _qa(work, "resolve", "--id", "q00deadbeef", "--because",
                  "a perfectly long and plausible sounding reason string")
    ck(rc != 0 and "no finding with id" in out,
       "an id never raised in this window is refused (was: an adjudication naming no known finding)")
    ck(f"BLOCKING {bid}" in out,
       "...and the refusal lists the ids that WERE raised, so the real remedy stays reachable")

    # the --reviews CWD bug: "required" was prose only, and a bare `record` silently false-cleared
    d2 = Path(tempfile.mkdtemp(prefix="cbre_adj2_")) / "w"
    d2.mkdir(parents=True)
    (d2 / "inventory.json").write_text(json.dumps({"input_hash": "h9"}), encoding="utf-8")
    rc, out = _qa(d2, "record")
    ck(rc != 0 and "--reviews is required" in out,
       "`record` with NO --reviews is REFUSED (it used to glob the CWD and mark the round done)")
    ck(GR.qa_round_number(d2) == 0, "...and that refusal records NO round (the false clear is dead)")
    rc, out = _qa(d2, "record", "--reviews", str(d2 / "nope"))
    ck(rc != 0 and "reviews dir not found" in out, "a --reviews path that does not exist is refused")

    # --- 4. the repair: recorded, with NO artefact change (the B9 trap) ------- #
    before_bytes = (work / "canonical.json").read_bytes()
    before_fp = GR._artefact_fingerprint(work)
    rc, out = _qa(work, "resolve", "--id", bid, "--because", WHY)
    ck(rc == 0, f"a BLOCKING finding is resolvable - only advisories used to be {ascii(out[:70])}")
    ck((work / "canonical.json").read_bytes() == before_bytes
       and GR._artefact_fingerprint(work) == before_fp,
       "...with the artefact BYTE-IDENTICAL: the freshness guard that made `resolve` unreachable "
       "in the documented order is gone")
    ck("nothing changed" not in out.lower(),
       "...and no freshness refusal is printed on the path the docs tell you to walk")
    ck(GR.qa_blocking_open(work) == [], "the blocking finding is ADDRESSED - it no longer blocks")
    ck(GR.qa_resolved_count(work) == 1,
       "...and counts as ONE remediation (final_gate's PASS-WITH-REMEDIATION line)")
    res = _state(work)["rounds"][0].get("resolved") or {}
    ck(list(res) == [bid] and res[bid].get("because", "").startswith("reworked")
       and res[bid].get("finding", "").startswith("G-honesty:"),
       "the repair lands in `resolved` WITH its written reason and the finding it answers")
    rc, sout = _qa(work, "status")
    ck("BLOCKING-OPEN: 0" in sout and "ADVISORY-CARRIED: 1" in sout,
       f"status: nothing blocking is open, the advisory still carries {ascii(sout[:70])}")
    rc, fg2 = _fg("--qa-state", str(work))
    ck("BLOCKING finding not addressed" not in fg2,
       "final_gate no longer blocks on it - implemented, recorded, ships with NO further review")

    # --- 5. record is idempotent and must never UNDO the repair -------------- #
    rc, out = _qa(work, "record", "--reviews", str(work / "reviews"))
    ck(rc == 0, "record is idempotent - re-running it never refuses")
    ck(len(_state(work)["rounds"]) == 1, "...and never opens a second round")
    ck(GR.qa_blocking_open(work) == [] and GR.qa_resolved_count(work) == 1,
       "...and never REOPENS a recorded repair (a re-record that wiped `resolved` would un-ship it)")
    ck(len(GR.qa_carried(work)) == 1,
       "...and the carried advisory survives it (Known limitations must not silently empty)")

    # --- 6. an advisory is closed by being recorded false, not by being ignored
    rc, out = _qa(work, "resolve", "--id", aid, "--because",
                  "the region field was struck to tbd so that limitation is now false")
    ck(rc == 0, f"an ADVISORY is resolvable when the blocking fix made it false {ascii(out[:60])}")
    ck(GR.qa_carried(work) == [],
       "...and is struck from Known limitations rather than shipped as a false statement")
    ck(GR.qa_resolved_count(work) == 2, "...counted as a second in-window remediation")

    # --- 7. qa_blocking_open fails INERT, never half-read ------------------- #
    d3 = Path(tempfile.mkdtemp(prefix="cbre_adj3_"))
    ck(GR.qa_blocking_open(d3) == [], "a missing qa_state.json yields [] (never a crash)")
    (d3 / "qa_state.json").write_text("{ not json", encoding="utf-8")
    ck(GR.qa_blocking_open(d3) == [], "...and so does an unreadable one")
    # run_key MUST come from the real helper: a hand-written key is discarded as a foreign corpus
    # and every assertion below would pass for the wrong reason.
    rnd = {"n": 1, "blocking": [f"G-honesty: {BLOCK}"], "advisory": [], "verdicts": {}}
    (d3 / "qa_state.json").write_text(json.dumps({
        "schema_version": 2, "run_key": GR._qa_run_key(d3), "rounds": [dict(rnd)],
        "advisory_carried": []}), encoding="utf-8")
    ck(GR.qa_blocking_open(d3) == [],
       "an OPENED-but-unrecorded round yields [] - an empty shell is not a review pass")
    (d3 / "qa_state.json").write_text(json.dumps({
        "schema_version": 2, "run_key": GR._qa_run_key(d3),
        "rounds": [dict(rnd, recorded=True)], "advisory_carried": []}), encoding="utf-8")
    ck(len(GR.qa_blocking_open(d3)) == 1,
       "...and the SAME round marked recorded does yield the finding (the check above is not vacuous)")
    (d3 / "qa_state.json").write_text(json.dumps({
        "schema_version": 1, "run_key": GR._qa_run_key(d3),
        "rounds": [dict(rnd, recorded=True, adjudication={"deadbeef": {"verdict": "not fixed"}})],
        "advisory_carried": []}), encoding="utf-8")
    ck(GR.qa_blocking_open(d3) == [],
       "a schema-1 window (the two-round/adjudication design) is a FRESH window, never half-read")
    (d3 / "qa_state.json").write_text(json.dumps({
        "schema_version": 2, "run_key": "notthisworkdir",
        "rounds": [dict(rnd, recorded=True)], "advisory_carried": []}), encoding="utf-8")
    ck(GR.qa_blocking_open(d3) == [], "...as is a state whose run_key names a different corpus")

    # --- 8. the removed surface is genuinely GONE --------------------------- #
    for mode in ("open", "diff", "adjudicate"):
        rc, out = _qa(work, mode)
        ck(rc != 0 and ("invalid choice" in out or "usage" in out.lower()),
           f"`qa-round {mode}` no longer exists")
    ck(not hasattr(GR, "qa_adjudication_open"),
       "gate_runner.qa_adjudication_open is gone - there is no adjudication verdict to be open")
    ck(not hasattr(GR, "qa_gate_remediated"),
       "gate_runner.qa_gate_remediated is gone - it existed only to answer a per-gate verdict word")
    ck(not hasattr(FG, "QA_ADVISORY_GATES") and not hasattr(FG, "QA_CRITICAL_GATES"),
       "final_gate's per-gate verdict TIERS are gone - the reviewer's per-finding label decides")
    fsrc = Path(FG.__file__).read_text(encoding="utf-8")
    ck("gate_runner.qa_resolved_count(" in fsrc and "PASS-WITH-REMEDIATION" in fsrc,
       "final_gate's PASS-WITH-REMEDIATION line is still driven by the recorded repair count")
    # Deleting a QA function without cleaning up its CALLER is the specific way this restructure
    # broke once: final_gate kept calling gate_runner.qa_adjudication_open after it was removed, so
    # every `final_gate --qa-state` run - the only mode that can block on an unaddressed finding -
    # died on AttributeError before printing a single reviewer line.
    # the call form only: a bare `gate_runner.py` inside a printed remedy string is a filename.
    refs = sorted(set(re.findall(r"gate_runner\.([A-Za-z_]\w*)\s*\(", fsrc)))
    gone = [n for n in refs if not hasattr(GR, n)]
    ck(len(refs) > 3 and not gone,
       f"every gate_runner.* function final_gate CALLS still exists ({len(refs)} of them); "
       f"missing: {gone}")

    # --- 9. final_gate: reviewers must exist AND speak; verdict words do not gate
    # a reviewer that raises a red VERDICT but labels its own finding `advisory:` is NOT a blocker
    (rv / "G-images.md").write_text(
        "- advisory: two cards crowd at 1280px\n\nVERDICT: red\n", encoding="utf-8")
    rc, out = _fg()
    # excerpt only the reviewer block: dumping final_gate's whole tail would echo its OWN
    # [PASS]/STATUS lines into this suite's output and make the report unreadable.
    seen = [ln.split("]", 1)[-1].strip() for ln in out.splitlines() if "finding(s) proposed" in ln]
    ck("[PASS] G-honesty: 2 finding(s) proposed" in out,
       f"final_gate counts the findings each reviewer PROPOSED {ascii(str(seen)[:80])}")
    ck("[PASS] G-images: 1 finding(s) proposed" in out,
       "a `VERDICT: red` reviewer no longer blocks - only its own blocking: labels can")
    ck("[PASS] G-trace: 0 finding(s) proposed" in out,
       "an explicit `FINDINGS: none` with no VERDICT line at all is accepted")

    (rv / "G-trace.md").write_text("Everything looks fine to me.\n", encoding="utf-8")
    rc, out = _fg()
    ck("[FAIL] G-trace: no labelled findings and no explicit 'FINDINGS: none'" in out,
       "a SILENT reviewer file fails safe - silence is a crashed review, not a clean one")
    ck(rc != 0, "...and final_gate does not ship on it")
    (rv / "G-trace.md").write_text("FINDINGS: none\n", encoding="utf-8")

    (rv / "G-visual.md").unlink()
    rc, out = _fg()
    ck("[FAIL] G-visual.md missing" in out,
       "a MISSING reviewer file blocks - isolated blind reviewers, one gate one agent, still stand")
    rc, out = _fg("--no-reviews")
    ck("[WARN] G-visual.md absent (DEGRADED mode acknowledged via --no-reviews)" in out
       and "[FAIL] G-visual.md missing" not in out,
       "--no-reviews downgrades that to a WARN and says so - the build was never judged")

    print("STATUS:", "ALL-PASS" if not fails else f"BLOCKED ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
