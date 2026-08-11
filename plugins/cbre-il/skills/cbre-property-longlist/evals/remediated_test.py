#!/usr/bin/env python3
"""remediated_test.py - PASS-WITH-REMEDIATION still exists, and is still EARNED. (B25/B50)

WHAT THIS GUARDS. A pack whose findings were raised and fixed INSIDE the QA window must ship and
must SAY so - `ALL-PASS - shippable (PASS-WITH-REMEDIATION: n finding(s) raised and fixed
in-window)` - rather than printing the same plain ALL-PASS as a pack that was clean first try. That
distinction is the only trace the window leaves in the shipped record, and `n` is the count of
repairs the orchestrator actually recorded, so it cannot be talked up.

WHAT WENT, AND WHY THIS FILE CHANGED. The old window was two rounds gated on per-gate VERDICT
WORDS, and remediation was a per-TIER escape hatch: `qa_gate_remediated(work, gate)` asked whether
every blocking finding of a CRITICAL-tier gate had been answered, and `final_gate` consulted it only
for `QA_CRITICAL_GATES` and only once the round budget was spent. On one live run that machinery
produced three ship-blockages that were mechanism failures rather than data problems, so it is gone:
no round budget, no `qa-round open|diff|adjudicate`, no `qa_gate_remediated`, no
`qa_adjudication_open`, no verdict tiers. A `VERDICT:` line in a review file is now optional and
ignored. The window is reviewers PROPOSE -> the orchestrator IMPLEMENTS -> deliver.

The PROPERTY survived the mechanism. `qa_resolved_count` and the PASS-WITH-REMEDIATION status line
are both still there, so what the old verdict-tier assertions said per gate this file now says per
FINDING, through `qa_blocking_open`: a `blocking:` finding is a FALSE CLAIM by the reviewer's own
rubric and may not ship until the orchestrator records what it changed; a partial answer clears
nothing; and a REFUSED `resolve` (no such id, or a reason under 20 characters) buys no credit -
which is what stops PASS-WITH-REMEDIATION from becoming a way to wave a finding away.

The ship-gate half is pinned by reading final_gate's wiring rather than by running it: final_gate
needs a whole deliverables tree (a real dashboard, ledger, Gaps Report, a passing freeze) that this
eval deliberately does not build. Everything else drives the real `gate_runner` CLI. Offline - no
build, no network.

Run: python evals/remediated_test.py
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import gate_runner as G  # noqa: E402

GRP = str(HELPERS / "gate_runner.py")

# The live shapes: two blocking findings (a phantom site plan, a certification asserted against an
# empty cell) and one advisory that must never block.
BLOCK1 = ("- blocking: property=12 field=plan issue=the `plan` ledger row cites a site plan the "
          "deck does not publish action=clear p.plan")
BLOCK2 = ("- blocking: property=3 field=breeam issue=Saxon 132 ships Certification \"A+\" against "
          "an empty tracker cell action=strike to tbd")
ADV = ("- advisory: property=3 field=region issue=region is the input filename, not a market "
       "region action=normalise to one granularity")
GOOD_REASON = "cleared p.plan and added a gap row citing the empty source cell"


def qa(work, *args):
    r = subprocess.run([sys.executable, GRP, "qa-round", *args, "--work", str(work)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def window(*review_lines, gate: str = "G-honesty") -> Path:
    """A work dir holding ONE reviews/round1/<gate>.md, ready for `qa-round record`."""
    d = Path(tempfile.mkdtemp(prefix="cbre_rem_"))
    rv = d / "reviews" / "round1"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / f"{gate}.md").write_text("\n".join(review_lines) + "\n", encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}), encoding="utf-8")
    return d


def raw_state(rounds, *, schema: int = 2, run_key=None) -> Path:
    """A work dir whose qa_state.json carries `rounds` verbatim - only for the shapes the CLI
    cannot produce: an UNRECORDED round, a stale schema, another corpus's state.

    The run_key must be the one `_qa_load` derives for THIS dir (work path + intake input hash),
    or the loader treats the state as a different corpus and resets the window. That is correct
    behaviour, and it is exactly what makes a hand-written fixture look empty - every assertion
    below would then pass for the wrong reason."""
    d = Path(tempfile.mkdtemp(prefix="cbre_rem_raw_"))
    st = {"schema_version": schema,
          "run_key": G._qa_run_key(d) if run_key is None else run_key,
          "rounds": rounds, "advisory_carried": []}
    (d / "qa_state.json").write_text(json.dumps(st), encoding="utf-8")
    return d


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ------------------------------------------------------------------ #
    print("A repair is COUNTED - and the count starts at zero:")
    d = window("VERDICT: red", BLOCK1, BLOCK2, ADV)
    rc, out = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0, f"record succeeds (rc={rc}) {ascii(out[:100])}")
    ck("2 blocking, 1 advisory" in out, "it counts the reviewer's OWN blocking/advisory labels")
    ck("REVIEW-PASS: 1" in out, "one review pass - there is no round budget to spend")
    ck("ORDER: record -> implement -> resolve -> deliver -> final_gate." in out,
       "it prints the order the count is earned in")
    ck("NEXT:" in out and "resolve --id" in out,
       "...and tells the orchestrator to IMPLEMENT, then record the repair")
    ck(G.qa_resolved_count(d) == 0,
       "a freshly recorded window has counted NO repair - remediation is never free")

    _open = G.qa_blocking_open(d)
    ck(len(_open) == 2 and all(o["finding"].startswith("G-honesty:") for o in _open),
       f"both UNRESOLVED blocking findings are open, gate-attributed {ascii(str(_open)[:70])}")
    ck(all("advisory" not in str(o["finding"]).lower() for o in _open)
       and any("region" in str(c) for c in G.qa_carried(d)),
       "the advisory never blocks - qa_carried still carries it to Known limitations")
    # Defensive unpack: if a regression empties this list the assertions below must FAIL with a
    # label, not disappear behind an IndexError in the harness.
    b1, b2 = ([o["id"] for o in _open] + ["missing-id-1", "missing-id-2"])[:2]

    # ------------------------------------------------------------------ #
    print("\n...and the count cannot be reached without recording a real repair:")
    rc, out = qa(d, "resolve", "--id", b1, "--because", "fixed it")
    ck(rc != 0 and "20 chars" in out, "a reason under 20 characters is refused")
    ck(G.qa_resolved_count(d) == 0, "...and that refusal buys NO remediation credit")
    rc, out = qa(d, "resolve", "--id", "deadbeef00", "--because", GOOD_REASON)
    ck(rc != 0, "an id never raised in this window is refused")
    ck(G.qa_resolved_count(d) == 0, "...and that refusal buys no credit either")
    ck(G.qa_blocking_open(d) == _open, "a refused resolve leaves both findings open")

    before = sha(d / "canonical.json")
    rc, out = qa(d, "resolve", "--id", b1, "--because", GOOD_REASON)
    ck(rc == 0 and sha(d / "canonical.json") == before,
       f"a recorded repair is accepted with the artefact byte-identical (rc={rc})")
    ck("nothing changed" not in out.lower(),
       "...the old artefact-freshness refusal is gone, not merely bypassed")
    ck(G.qa_resolved_count(d) == 1, "the recorded repair is COUNTED")
    ck([o["id"] for o in G.qa_blocking_open(d)] == [b2],
       "PARTIAL remediation clears nothing - the unanswered finding still blocks")

    rc, out = qa(d, "resolve", "--id", b2, "--because",
                 "struck the certification to tbd and cited the empty tracker cell")
    ck(rc == 0 and G.qa_blocking_open(d) == [],
       "every blocking finding answered by a RECORDED repair -> nothing open, it ships")
    ck(G.qa_resolved_count(d) == 2, "each recorded repair increments the count")

    adv_id = next((G.finding_id(c) for c in G.qa_carried(d)), "missing-advisory-id")
    rc, out = qa(d, "resolve", "--id", adv_id, "--because",
                 "the blocking fix normalised region, so the note is now false")
    ck(rc == 0 and G.qa_resolved_count(d) == 3,
       "a resolved ADVISORY counts as remediation too")
    ck(G.qa_carried(d) == [], "...and is struck from the Gaps Report's Known limitations")

    st = json.loads((d / "qa_state.json").read_text(encoding="utf-8"))
    ck(len(st["rounds"]) == 1 and st.get("schema_version") == 2,
       f"all three repairs live in ONE schema-2 round {len(st['rounds'])}/"
       f"{st.get('schema_version')}")
    ck(G.QA_MAX_ROUNDS == 1, "there is exactly one round - no second pass to earn credit in")
    rc, out = qa(d, "adjudicate")
    ck(rc != 0, "the adjudication pass that used to stand between a repair and the count is gone")

    # ------------------------------------------------------------------ #
    print("\nFail-safe: nothing recorded, nothing credited - and a red word alone is inert:")
    d2 = window("VERDICT: red", "FINDINGS: none", gate="G-trace")
    rc, out = qa(d2, "record", "--reviews", str(d2 / "reviews"))
    ck(rc == 0 and G.qa_blocking_open(d2) == [],
       "a `VERDICT: red` with no blocking finding no longer blocks (verdict tiers are gone)")
    ck(G.qa_resolved_count(d2) == 0, "...and it earns no PASS-WITH-REMEDIATION either")

    d3 = window(BLOCK1, gate="G-images")           # no VERDICT line at all
    rc, out = qa(d3, "record", "--reviews", str(d3 / "reviews"))
    ck(rc == 0 and len(G.qa_blocking_open(d3)) == 1,
       "a review with NO verdict line is still fully read - the verdict word is optional")

    empty = Path(tempfile.mkdtemp(prefix="cbre_rem_empty_"))
    ck(G.qa_blocking_open(empty) == [] and G.qa_resolved_count(empty) == 0,
       "a work dir with no qa_state.json degrades to nothing open / nothing counted, never raises")

    d4 = raw_state([{"n": 1, "blocking": [f"G-honesty: {BLOCK1}"], "advisory": []}])
    ck(G.qa_blocking_open(d4) == [], "findings in an UNRECORDED round do not count")

    _res = {G.finding_id(f"G-honesty: {BLOCK1}"): {"because": "fixed and independently verified"}}
    d5 = raw_state([{"n": 1, "blocking": [f"G-honesty: {BLOCK1}"], "advisory": [],
                     "recorded": True, "verdicts": {"G-honesty": "red"},
                     "adjudication": {}, "resolved": _res}], schema=1)
    ck(G.qa_blocking_open(d5) == [] and G.qa_resolved_count(d5) == 0,
       "a schema-1 window is discarded whole, never mined for remediation credit")

    d6 = raw_state([{"n": 1, "blocking": [f"G-honesty: {BLOCK1}"], "advisory": [],
                     "recorded": True, "resolved": _res}], run_key="notthisworkdir")
    ck(G.qa_blocking_open(d6) == [] and G.qa_resolved_count(d6) == 0,
       "another corpus's state is discarded - a run_key mismatch credits nothing")

    # ------------------------------------------------------------------ #
    print("\nWiring - the ship gate must read the count, say it, and still block on an open finding:")
    src = (HELPERS / "final_gate.py").read_text(encoding="utf-8")
    ck("_remediated = gate_runner.qa_resolved_count(args.qa_state)" in src,
       "final_gate takes the number from qa_resolved_count, not from anywhere it could invent")
    ck("PASS-WITH-REMEDIATION: {_remediated} " in src,
       "...and the status line reports THAT count, interpolated, never a bare word")
    ck("ALL-PASS - shippable (PASS-WITH-REMEDIATION" in src,
       "...as an ALL-PASS: a remediated pack SHIPS")
    ck("elif _remediated:" in src,
       "...and only when a repair was actually recorded (0 -> the plain ALL-PASS)")
    ck("qa_blocking_open(" in src and "BLOCKING finding not addressed" in src,
       "an unanswered blocking finding still blocks the ship gate")
    ck(r"FINDINGS:\s*none" in src and "no labelled findings" in src,
       "a silent reviewer fails safe - labelled findings or an explicit 'FINDINGS: none'")
    ck("DEGRADED - mechanical gates pass" in src,
       "--no-reviews still yields DEGRADED, never a remediation claim")

    print("\n...and the verdict-tier machinery it replaced is really gone:")
    ck(not hasattr(G, "qa_gate_remediated"), "gate_runner.qa_gate_remediated is gone")
    ck(not hasattr(G, "qa_adjudication_open"), "gate_runner.qa_adjudication_open is gone")
    ck("qa_gate_remediated" not in src, "final_gate no longer consults a per-gate remediation")
    ck("QA_CRITICAL_GATES" not in src and "QA_ADVISORY_GATES" not in src,
       "no CRITICAL/ADVISORY verdict tiers survive in the ship gate")
    ck("[REMEDIATED]" not in src, "the per-gate [REMEDIATED] tier marker is gone with them")
    ck(hasattr(G, "qa_carried") and hasattr(G, "qa_resolved_count"),
       "qa_carried and qa_resolved_count are unchanged and still exported")

    print("\nSTATUS:", "ALL-PASS" if not fails else "BLOCKED")
    if fails:
        for f in fails:
            print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
