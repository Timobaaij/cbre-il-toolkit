#!/usr/bin/env python3
"""propose_implement_deliver_test.py - the QA window is propose -> implement -> deliver.

WHY THE OLD DESIGN WENT. The window was `record -> fix -> adjudicate -> resolve -> deliver ->
final_gate`, gated on per-gate VERDICT WORDS with a two-round budget. On one live run it produced
three ship-blockages that were all mechanism failures rather than data problems:

  * PASS-WITH-REMEDIATION read blocking findings from `rounds[-1]`, but `adjudicate` creates the last
    round with `blocking: []` by construction - so a CRITICAL-tier red could never be cleared even
    with every finding fixed, source-verified and recorded (B8);
  * `resolve` refused unless the artefact had moved since the CURRENT round's fingerprint, which was
    stamped after the repairs - so it was unreachable in the documented order, and a delivered Gaps
    Report shipped a "Known limitations" line asserting a defect the pack no longer had (B9);
  * and the round budget itself had to be reasoned about on every run.

WHAT IS KEPT, and this suite exists to prove it is still kept: isolated blind reviewers (one gate,
one agent), the reviewer's OWN blocking/advisory labels, and the rule that a `blocking:` finding -
a FALSE CLAIM by that rubric - cannot ship until the orchestrator records what it changed. What
changed is that "addressed" means the orchestrator recording a repair, not a second reviewer
re-blessing it. Offline, drives the real gate_runner CLI."""
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

GRP = str(HELPERS / "gate_runner.py")
BLOCK = ("- blocking: property=3 field=breeam issue=Saxon 132 ships an impossible BREEAM grade "
         "action=strike it to tbd")
ADV = ("- advisory: property=- field=region issue=two granularities across the dataset "
       "action=normalise to one level")


def qa(work, *args):
    r = subprocess.run([sys.executable, GRP, "qa-round", *args, "--work", str(work)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    d = Path(tempfile.mkdtemp(prefix="cbre_pid_"))
    rv = d / "reviews" / "round1"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / "G-honesty.md").write_text(BLOCK + "\n" + ADV + "\n", encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}), encoding="utf-8")

    # --- 1. record: one pass, no budget arithmetic -------------------------- #
    rc, out = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0, f"record succeeds (rc={rc})")
    ck("1 blocking, 1 advisory" in out, f"it counts the reviewer's own labels {ascii(out[:90])}")
    ck("/2" not in out and "ROUND:" not in out,
       "no two-round budget is printed any more (the window is one review pass)")
    ck("REVIEW-PASS: 1" in out, "it reports a single review pass")

    # --- 2. the blocking finding is open ------------------------------------ #
    op = GR.qa_blocking_open(d)
    # `record` normalises each finding to "<gate>: <rest>", so the raw "- blocking:" prefix is
    # consumed by then - what must survive is the gate name and the finding's own content.
    ck(len(op) == 1 and op[0]["finding"].startswith("G-honesty:")
       and "breeam" in op[0]["finding"],
       f"qa_blocking_open returns the blocking finding, gate-attributed {ascii(str(op)[:80])}")
    fid = op[0]["id"]
    ck(bool(fid), "...with an id to resolve it by")

    # advisories are NEVER blocking - they carry
    ck(all("advisory" not in str(o["finding"]).lower() for o in op),
       "an advisory finding is not treated as blocking")
    ck(any("region" in str(c) for c in GR.qa_carried(d)),
       "the advisory is carried for the Gaps Report's Known limitations")

    # --- 3. resolve needs NO artefact change (the B9 trap is gone) ---------- #
    rc, out = qa(d, "resolve", "--id", fid, "--because",
                 "struck the field to tbd and added a gap row citing the empty source cell")
    ck(rc == 0, f"resolve succeeds with the artefact byte-identical (rc={rc}) {ascii(out[:110])}")
    ck("nothing changed" not in out.lower(), "...and never reports the old freshness refusal")
    ck(GR.qa_blocking_open(d) == [], "the blocking finding is now addressed")

    # --- 4. the guards that DO carry meaning are still there ---------------- #
    rc, out = qa(d, "resolve", "--id", fid, "--because", "too short")
    ck(rc != 0 and "20 chars" in out, "a reason under 20 chars is still refused")
    rc, out = qa(d, "resolve", "--id", "nosuchid00", "--because",
                 "a perfectly long and plausible sounding reason string")
    ck(rc != 0, "an id that was never raised in this window is still refused")

    # --- 5. record is idempotent, never a second round, never a refusal ----- #
    rc, out = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0, "record can be re-run without refusing")
    st = json.loads((d / "qa_state.json").read_text(encoding="utf-8"))
    ck(len(st["rounds"]) == 1, f"still exactly ONE round {len(st['rounds'])}")
    ck(st.get("schema_version") == 2, f"state is schema 2 {st.get('schema_version')}")

    # --- 6. the removed modes are gone from the CLI ------------------------- #
    for mode in ("open", "diff", "adjudicate"):
        rc, out = qa(d, mode)
        ck(rc != 0 and ("invalid choice" in out or "usage" in out.lower()),
           f"`qa-round {mode}` no longer exists")

    # --- 7. status still reports without budget arithmetic ------------------ #
    rc, out = qa(d, "status")
    ck(rc == 0 and "REVIEW-PASS: 1" in out, f"status reports the pass {ascii(out[:70])}")
    ck("ADJUDICATION-OPEN" not in out, "status no longer reports adjudication state")
    ck("BLOCKING-OPEN: 0" in out, "...it reports how many blocking findings are still unaddressed")

    # --- 8. a stale schema-1 window is discarded, not half-read ------------- #
    d2 = Path(tempfile.mkdtemp(prefix="cbre_pid_old_"))
    (d2 / "qa_state.json").write_text(json.dumps({
        "schema_version": 1, "run_key": GR._qa_run_key(d2),
        "rounds": [{"n": 1, "blocking": [BLOCK], "advisory": [], "recorded": True,
                    "adjudication": {"deadbeef": {"verdict": "not fixed"}}}],
        "advisory_carried": []}), encoding="utf-8")
    ck(GR.qa_blocking_open(d2) == [],
       "a schema-1 window is treated as a fresh window, never partially interpreted")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
