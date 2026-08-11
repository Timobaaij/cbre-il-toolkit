#!/usr/bin/env python3
"""remediated_round_test.py - a BLOCKING finding blocks until a repair is RECORDED. (B8)

THE DEADLOCK THIS FILE WAS BORN FROM. `final_gate` used to block unconditionally on a CRITICAL-tier
red (G-honesty / G-trace / G-enrich) and `qa-round` refused a third round, so `qa_gate_remediated`
existed as the escape hatch: a RECORDED, artefact-backed repair could answer that red. But it read
the gate's blocking findings from `rounds[-1]`, and in the documented flow blocking findings were
recorded in the DISCOVERY round while the ADJUDICATION round - opened by `qa-round adjudicate` to
JUDGE the previous round's repairs, not to discover - carried `blocking: []` by construction. So
`rounds[-1]["blocking"]` was empty on every real run, the gate's own findings were never found, and
the function returned False as "unexplained". A live run had all four critical findings fixed,
independently re-verified against source, and recorded through the guarded `qa-round resolve` - and
final_gate still printed `STATUS: BLOCKED - do not ship`. Every precondition was met; it looked in
the wrong round.

WHAT HAPPENED NEXT: the mechanism was REPLACED, not patched. The QA window is now three steps -
isolated reviewers PROPOSE findings, the orchestrator IMPLEMENTS, then we deliver. The round budget,
`qa-round open|diff|adjudicate`, the adjudication pass, `qa_gate_remediated`, `qa_adjudication_open`
and every verdict-word gate are gone. There is no second round for an escape hatch to live in, so
there is nothing left to deadlock: exactly one review pass, and "addressed" means the orchestrator
recorded what it changed.

WHAT THIS FILE NOW GUARDS is the one safety property that survived the restructure, in both
directions - `gate_runner.qa_blocking_open`. A `blocking:` finding is a FALSE CLAIM by the
reviewer's own rubric, so it stays open (and the ship gate blocks) until a repair is recorded
against its id; PARTIAL repair of several is not repair; advisory findings are never open, they
carry into the Gaps Report; and every unreadable, unrecorded or stale-schema window fails SAFE by
returning `[]` rather than raising or being half-interpreted. The guard is still "did this finding
get recorded as repaired", never "is there no finding".

Offline, pure state - no build, no network. Drives the real `qa-round` CLI where practical; the
hand-written windows exist only for shapes the CLI cannot produce (an unrecorded round, a corrupt
file, a schema-1 window). Those MUST carry `run_key = _qa_run_key(work)` and `schema_version: 2`,
or `_qa_load` discards them as a different corpus and every assertion below passes for the wrong
reason. The original file fell into exactly that trap, so section 3 opens with a positive control.
"""
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

GATE_H, GATE_T, GATE_I = "G-honesty", "G-trace", "G-images"

# Finding BODIES. A review file writes `- blocking: <body>`; `record` normalises the entry to
# "<gate>: <body>", consuming the raw label - so the two forms are derived from ONE string here and
# the normalisation contract is pinned rather than assumed.
B_HON = ('property=3 field=breeam issue=Saxon 132 ships Certification "A+" but the tracker\'s '
         'BREEAM cell is empty action=strike it to tbd')
B_HON2 = ('property=3 field=breeam issue=the Source Ledger certifies that value at High '
          'confidence against a blank cell action=replace it with a gap row')
B_TRC = ('property=3 field=breeam issue=cited to Building Data!r4 but that cell is empty '
         'action=strike it to tbd')
A_HON = ('property=- field=region issue=two granularities across the dataset '
         'action=normalise to one level')
A_IMG = ('property=4 field=photo issue=the hero is an estate-wide aerial '
         'action=swap with gallery[1]')

WHY = "struck the field to tbd and added a gap row citing the empty source cell"


def _norm(gate: str, body: str) -> str:
    """What `record` stores for a finding: gate-attributed, label consumed."""
    return f"{gate}: {body}"


def qa(work, *args):
    r = subprocess.run([sys.executable, GRP, "qa-round", *args, "--work", str(work)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _round(n: int, blocking, advisory=(), *, recorded=True, resolved=()) -> dict:
    return {"n": n, "blocking": list(blocking), "advisory": list(advisory), "verdicts": {},
            "recorded": recorded, "fingerprint": "aaaa", "enrichment": "",
            "resolved": {i: {"finding": "(recorded elsewhere)", "because": WHY, "fingerprint": "b"}
                         for i in resolved}}


def _open_safe(work):
    """`qa_blocking_open` on a degraded window, with a RAISE turned into a reportable value.

    Calling it bare would abort the eval on a traceback and lose every assertion after it - but
    "returns [] instead of raising" is itself one of the properties under test, so the failure has
    to be printed as a [FAIL] like any other."""
    try:
        return GR.qa_blocking_open(work)
    except Exception as exc:            # noqa: BLE001 - raising IS the failure mode being pinned
        return f"raised {type(exc).__name__}"


def _write_state(work: Path, rounds, *, schema: int = 2, run_key=None, raw=None) -> None:
    """A hand-written QA window.

    `run_key` defaults to the key `_qa_load` derives for THIS work dir; a mismatch is treated as a
    different corpus and the whole window is discarded as stale, which is the trap that would make
    every fail-safe assertion below pass for the wrong reason. Section 3 proves it is not sprung."""
    if raw is not None:
        (work / "qa_state.json").write_text(raw, encoding="utf-8")
        return
    st = {"schema_version": schema,
          "run_key": GR._qa_run_key(work) if run_key is None else run_key,
          "rounds": list(rounds), "advisory_carried": []}
    (work / "qa_state.json").write_text(json.dumps(st), encoding="utf-8")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    fid = GR.finding_id
    N_HON, N_HON2, N_TRC = _norm(GATE_H, B_HON), _norm(GATE_H, B_HON2), _norm(GATE_T, B_TRC)
    ALL3 = [N_HON, N_HON2, N_TRC]

    # --- 0. the mechanism was REPLACED, not patched -------------------------- #
    print("the deadlocked escape hatch is gone, not repaired:")
    ck(not hasattr(GR, "qa_gate_remediated"),
       "qa_gate_remediated no longer exists (no CRITICAL-tier red to buy off)")
    ck(not hasattr(GR, "qa_adjudication_open"),
       "...nor the adjudication pass whose empty round it misread")
    ck(GR.QA_MAX_ROUNDS == 1,
       "exactly ONE review pass, so there is no second round for a deadlock to live in")
    fg_src = (HELPERS / "final_gate.py").read_text(encoding="utf-8", errors="replace")
    ck("gate_runner.qa_blocking_open(" in fg_src and "[False] * len(_open)" in fg_src,
       "final_gate blocks on qa_blocking_open - the property below is wired to the ship gate")
    ck("qa_gate_remediated" not in fg_src and "QA_CRITICAL_GATES" not in fg_src,
       "...and no longer gates on gate tiers or verdict words")

    # --- 1. the real CLI: reviewers propose, nothing is addressed yet -------- #
    print("a recorded blocking finding is OPEN until a repair is recorded:")
    d = Path(tempfile.mkdtemp(prefix="cbre_rem_"))
    rv = d / "reviews" / "round1"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / f"{GATE_H}.md").write_text(
        f"- blocking: {B_HON}\n- blocking: {B_HON2}\n- advisory: {A_HON}\n", encoding="utf-8")
    (rv / f"{GATE_T}.md").write_text(f"- blocking: {B_TRC}\n", encoding="utf-8")
    (rv / f"{GATE_I}.md").write_text(f"- advisory: {A_IMG}\n", encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}), encoding="utf-8")

    rc, out = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0, f"record succeeds (rc={rc}) {ascii(out[:100])}")
    op = GR.qa_blocking_open(d)
    ck(sorted(o["finding"] for o in op) == sorted(ALL3),
       f"all three blocking findings are open, gate-attributed, raw label consumed "
       f"{ascii(str([o['finding'][:24] for o in op]))}")
    ck(all(o["id"] == fid(o["finding"]) for o in op) and all(o["id"] for o in op),
       "each one carries the id `qa-round resolve --id` takes")
    ck(not any(t in " ".join(o["finding"] for o in op)
               for t in ("estate-wide aerial", "two granularities")),
       "an advisory finding is NEVER reported as open")
    ck(len(GR.qa_carried(d)) == 2,
       f"...both advisories carry instead, for the Gaps Report {len(GR.qa_carried(d))}")
    h1, h2, t1 = fid(N_HON), fid(N_HON2), fid(N_TRC)
    ck({o["id"] for o in op} == {h1, h2, t1},
       "the ids are derived from the stored finding text, so they are addressable")

    # --- 2. only a REAL recorded repair closes a finding --------------------- #
    print("partial repair does not open the ship gate:")
    rc, out = qa(d, "resolve", "--id", "deadbeef00", "--because", WHY)
    ck(rc != 0 and len(GR.qa_blocking_open(d)) == 3,
       "an id that was never raised is refused - a blocking finding cannot be closed by "
       "resolving something else")
    rc, out = qa(d, "resolve", "--id", h1, "--because", "fixed it")
    ck(rc != 0 and h1 in {o["id"] for o in GR.qa_blocking_open(d)},
       "a reason under 20 chars is refused and the finding stays open")
    rc, out = qa(d, "resolve", "--id", h1, "--because", WHY)
    ck(rc == 0, f"resolve records a repair with the artefact byte-identical (rc={rc})")
    op = GR.qa_blocking_open(d)
    ck({o["id"] for o in op} == {h2, t1},
       f"one of three resolved -> the OTHER TWO are still open {sorted(o['id'] for o in op)}")
    rc, out = qa(d, "resolve", "--id", h2, "--because", WHY + " for the second finding too")
    op = GR.qa_blocking_open(d)
    ck([o["id"] for o in op] == [t1],
       "both G-honesty findings repaired and G-trace's is STILL open - a repaired sibling "
       "does not clear another finding")
    rc, out = qa(d, "resolve", "--id", t1, "--because", WHY + " and re-checked the cited cell")
    ck(rc == 0 and GR.qa_blocking_open(d) == [],
       "every blocking finding recorded as repaired -> nothing open, the pack can ship")
    ck(GR.qa_resolved_count(d) == 3, f"three repairs on the record {GR.qa_resolved_count(d)}")
    ck(len(GR.qa_carried(d)) == 2,
       "...and the advisories still carry - repairing a blocking finding is not a retirement")
    rc, out = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0 and GR.qa_blocking_open(d) == [],
       "a re-record does not re-open what was repaired (the ids are stable)")

    # --- 3. the fixture is really being read (the trap the old file sprang) --- #
    print("hand-written windows: positive control first, then the fail-safes:")
    e = Path(tempfile.mkdtemp(prefix="cbre_rem_state_"))
    _write_state(e, [_round(1, ALL3, [_norm(GATE_I, A_IMG)])])
    ck(sorted(o["finding"] for o in GR.qa_blocking_open(e)) == sorted(ALL3),
       "POSITIVE CONTROL: a correctly keyed schema-2 window IS read, so an empty result "
       "below means the fail-safe fired")
    _write_state(e, [_round(1, ALL3)], run_key="0" * 16)
    ck(GR.qa_blocking_open(e) == [],
       "a run_key from a different corpus discards the window - the mis-keying that made the "
       "original fixture pass for the wrong reason")

    _write_state(e, [_round(1, ALL3, resolved=[h1, h2])])
    ck([o["id"] for o in GR.qa_blocking_open(e)] == [t1],
       "two of three resolved in recorded state -> the third still blocks")
    _write_state(e, [_round(1, ALL3, resolved=[h1, h2, t1])])
    ck(GR.qa_blocking_open(e) == [], "all three resolved -> nothing open")

    # --- 4. every fail-safe: [] rather than raise, never half-read ----------- #
    print("fail-safe in every degraded shape:")
    _write_state(e, [_round(1, ALL3, recorded=False)])
    ck(_open_safe(e) == [],
       "findings in an UNRECORDED round contribute nothing (an open shell is not a proposal)")
    _write_state(e, [_round(1, ALL3), _round(2, [], recorded=False)])
    ck(sorted(o["finding"] for o in GR.qa_blocking_open(e)) == sorted(ALL3),
       "...and an unrecorded shell does NOT mask the recorded round's findings - it fails "
       "toward blocking, not toward shipping")
    _write_state(e, [])
    ck(_open_safe(e) == [], "a window with no rounds at all -> []")
    _write_state(e, [_round(1, ALL3)], schema=1)
    ck(_open_safe(e) == [],
       "a schema-1 window is DISCARDED, never partially interpreted (its adjudication map and "
       "round budget mean nothing here)")
    _write_state(e, None, raw="{not json at all")
    ck(_open_safe(e) == [], "an unreadable qa_state.json -> [], not an exception")
    _write_state(e, None, raw=json.dumps(["not", "a", "dict"]))
    ck(_open_safe(e) == [], "a JSON non-object -> [], not an exception")
    ck(_open_safe(Path(tempfile.mkdtemp(prefix="cbre_rem_empty_"))) == [],
       "no qa_state.json -> [], not an exception")
    ck(_open_safe(e / "no" / "such" / "dir") == [],
       "a work dir that does not exist -> [], not an exception")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
