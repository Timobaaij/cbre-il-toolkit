#!/usr/bin/env python3
"""The QA window's PAPERCUTS - the small details that each cost a real run a round-trip. (B60)

The window itself was restructured: isolated reviewers PROPOSE findings, the orchestrator
IMPLEMENTS, then we deliver. The two-round, verdict-word-gated design with an adjudication pass is
gone - on one live run it produced three ship-blockages that were mechanism failures rather than
data problems. Kept: blind isolated reviewers (one gate, one agent), the reviewer's OWN
`blocking:`/`advisory:` labels, the mechanical gates and the freeze as hard blockers, and the rule
that a `blocking:` finding cannot ship until the orchestrator records what it changed.

This suite guards the USABILITY of that window, not its safety properties
(propose_implement_deliver_test.py owns those). Every check below is a papercut that was paid for:

F24 - SKILL.md tells the orchestrator to act on "the blocking finding list WITH ITS IDS (printed by
record)". record printed every ADVISORY id and no blocking one, so the ids had to be derived by
importing gate_runner and calling finding_id() by hand. An id the orchestrator never saw is an id
it cannot use, so record must print BOTH, and `resolve --id` must accept them verbatim.

F28 - the printed ORDER line is the one place the orchestrator learns the sequence without reading
SKILL.md, so it must state the CURRENT one (`record -> implement -> resolve -> deliver ->
final_gate`) and must NOT hard-require recording before fixing: the artefact-freshness guard that
made `resolve` unreachable in the documented order is gone, so either order now works. The two
assertions that pinned that guard's refusal wording ("since the round was recorded", "re-record if
you fixed first") describe behaviour that no longer exists and are replaced by checks that the
REMAINING refusals - unknown id, thin reason, no round yet - each name their own remedy.

F30 - enabling an enrichment layer AFTER the window closed left verdicts describing an artefact that
no longer existed. Resetting the window via _qa_run_key was REJECTED: it would wipe an
already-recorded round and re-block a verified pack. So staleness is made VISIBLE instead, and
deliberately does NOT block - added layers do not falsify fields already reviewed, and G-enrich is
already a required reviewer whenever regions ran. Offline; drives the real gate_runner CLI."""
from __future__ import annotations
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
SECRET = "eyJvcmciOiJTRUNSRVQtTVVTVC1OT1QtQVBQRUFSIn0="
BLOCK = ("- blocking: property=3 field=breeam issue=Saxon 132 ships an impossible BREEAM grade "
         "action=strike it to tbd")
ADV = ("- advisory: property=- field=region issue=two granularities across the dataset "
       "action=normalise to one level")
WHY = "struck the field to tbd and added a gap row citing the empty source cell"


def qa(work, *args):
    """The real CLI, exactly as the orchestrator invokes it."""
    r = subprocess.run([sys.executable, GRP, "qa-round", *args, "--work", str(work)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def printed_ids(out: str, kind: str) -> list:
    """The ids printed under one label - the handles `resolve --id` needs.

    Matches the `  BLOCKING <id>  <text>` finding lines and never the `BLOCKING: <n>` count
    line, whose first token carries the colon."""
    ids = []
    for ln in out.splitlines():
        tok = ln.strip().split()
        if len(tok) >= 2 and tok[0] == kind:
            ids.append(tok[1])
    return ids


def line_with(out: str, prefix: str) -> str:
    return next((ln for ln in out.splitlines() if ln.strip().startswith(prefix)), "")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # --- enrich_signature: the layers, NEVER the key ------------------------- #
    print("enrich_signature - the layers, NEVER the key:")
    d1 = Path(tempfile.mkdtemp(prefix="cbre_qa_pc_"))
    (d1 / ".enrich.stamp").write_text(json.dumps(
        {"args": f"--geocode|--ors-key|--osrm|--pois|--regions|{SECRET}", "hash": "x"}),
        encoding="utf-8")
    sig = G.enrich_signature(d1)
    ck(all(f"--{k}" in sig for k in ("geocode", "osrm", "pois", "regions")),
       "the enabled layers are captured")
    ck(SECRET not in sig, "the ORS KEY VALUE never appears in the signature")
    ck("eyJ" not in sig, "...nor does any non-flag token")
    ck(sig == G.enrich_signature(d1), "the signature is order-stable")

    d1b = Path(tempfile.mkdtemp(prefix="cbre_qa_pc2_"))
    (d1b / ".enrich.stamp").write_text(json.dumps({"args": "--geocode|--pois"}), encoding="utf-8")
    ck(G.enrich_signature(d1b) != sig, "a DIFFERENT layer set gives a different signature")
    ck(G.enrich_signature(Path(tempfile.mkdtemp(prefix="cbre_qa_pc3_"))) == "",
       "a missing stamp is inert, never a crash")
    (d1b / ".enrich.stamp").write_text("not json", encoding="utf-8")
    ck(G.enrich_signature(d1b) == "", "a corrupt stamp is inert")

    # --- the work dir every later section reads ------------------------------ #
    d = Path(tempfile.mkdtemp(prefix="cbre_qa_pcrec_"))
    rv = d / "reviews" / "round1"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / "G-honesty.md").write_text(BLOCK + "\n" + ADV + "\n", encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}),
                                      encoding="utf-8")

    print("\nF24 - record's own output is the whole brief: counts, ids, next step:")
    rc, rec = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0, f"record succeeds (rc={rc}) {ascii(rec[:90])}")
    ck("recorded 1 blocking, 1 advisory" in rec,
       "the count line names both buckets, using the reviewer's own labels")
    ck("reviews read from round1" in rec,
       "...and WHICH review dir it read, so a mis-pointed --reviews is visible immediately")

    bids, aids = printed_ids(rec, "BLOCKING"), printed_ids(rec, "ADVISORY")
    open_ = G.qa_blocking_open(d)
    ck(len(bids) == 1 and bids == [o["id"] for o in open_],
       f"a BLOCKING id is printed, and it IS the handle resolve needs {ascii(str(bids))}")
    ck(len(aids) == 1 and aids == [G.finding_id(f) for f in G.qa_carried(d)],
       f"...alongside the existing ADVISORY one {ascii(str(aids))}")
    bline = line_with(rec, "BLOCKING ")
    # `record` normalises each finding to "<gate>: <rest>", so an id alone would leave the
    # orchestrator re-reading the reviews to learn WHO raised WHAT.
    ck("G-honesty:" in bline and "breeam" in bline.lower(),
       f"the printed finding carries its gate and its text, not just an id {ascii(bline[:70])}")
    ck("REVIEW-PASS: 1" in rec, "the review-pass count is stated")
    ck("BLOCKING: 1" in rec, "...and the blocking count")
    ck("/2" not in rec and "ROUND:" not in rec,
       "no round-budget arithmetic is printed - the window is ONE review pass")

    nxt = line_with(rec, "NEXT:")
    ck("resolve --id" in nxt and "IMPLEMENT" in nxt,
       f"NEXT names the exact command that closes a blocking finding {ascii(nxt[:80])}")
    ck("no second review pass" in nxt.lower(),
       "...and says there is no second review pass, so nothing is needlessly re-dispatched")

    print("\nF28 - the ORDER line states the CURRENT sequence, up front:")
    order = line_with(rec, "ORDER:")
    ck("record -> implement -> resolve -> deliver -> final_gate" in order,
       f"record states the required order up front {ascii(order[:90])}")
    ck("before or after" in order.lower() and "no longer requires" in order.lower(),
       "...and that fixing BEFORE or AFTER recording both work (the freshness guard is gone)")
    ck("record, then fix, then resolve" not in rec.lower(),
       "the stale record-then-fix-then-resolve sequence is no longer instructed")
    ck(bool(order) and not any(w in order.lower() for w in
                               ("adjudicat", "qa-round open", "qa-round diff", "-> diff")),
       f"the order names no removed command {ascii(order[:90])}")
    ck("adjudicat" not in rec.lower(),
       "record never mentions an adjudication pass anywhere (that pass is gone)")

    print("\nF28 - the printed ids round-trip, with no artefact change needed:")
    rc, res = qa(d, "resolve", "--id", bids[0], "--because", WHY)
    ck(rc == 0, f"the id record printed is accepted by resolve verbatim (rc={rc}) "
                f"{ascii(res[:110])}")
    ck(not any(w in res.lower() for w in
               ("nothing changed", "since the round was recorded", "re-record")),
       "a byte-identical artefact never triggers the removed freshness refusal")
    ck("because: struck the field to tbd" in res, "the recorded reason is echoed back")
    ck("CARRIED: 1" in res, "...with the carried-advisory count, so no `status` call is needed")
    ck("deliver.py" in line_with(res, "NEXT:"),
       "resolve's NEXT names deliver.py, so the delivered report matches the recorded round")
    ck(G.qa_blocking_open(d) == [], "the blocking finding counts as addressed once recorded")

    print("\nF28 - each remaining refusal names its own remedy:")
    rc, bad = qa(d, "resolve", "--id", "nosuchid00", "--because",
                 "a perfectly long and plausible sounding reason string")
    ck(rc != 0, "an id that was never raised in this window is refused")
    ck(bids[0] in bad and aids[0] in bad,
       "...and the refusal LISTS the ids that do exist, so the retry needs no python at all")
    ck("STATUS: BLOCKED" in bad, "...with a machine-readable status line")
    rc, thin = qa(d, "resolve", "--id", bids[0], "--because", "too short")
    ck(rc != 0 and "20 chars" in thin,
       f"a reason under 20 chars is refused AND the threshold is named {ascii(thin[:80])}")
    d_fresh = Path(tempfile.mkdtemp(prefix="cbre_qa_pcfresh_"))
    rc, early = qa(d_fresh, "resolve", "--id", "abc0123456", "--because", WHY)
    ck(rc != 0 and "qa-round record" in early,
       "resolving before any recorded round names `qa-round record` as the fix")

    print("\nrecord never costs a round-trip: idempotent, id-stable, and no silent clear:")
    rc, rec2 = qa(d, "record", "--reviews", str(d / "reviews"))
    ck(rc == 0, f"record re-runs without refusing (rc={rc})")
    ck(printed_ids(rec2, "BLOCKING") == bids,
       "...and reprints the SAME ids, so a handle noted earlier stays valid")
    st = json.loads((d / "qa_state.json").read_text(encoding="utf-8"))
    ck(len(st["rounds"]) == 1 and st.get("schema_version") == 2,
       f"still exactly ONE round, schema 2 {len(st['rounds'])}/{st.get('schema_version')}")
    rc, norv = qa(d, "record")
    ck(rc != 0 and "--reviews" in norv,
       "record without --reviews refuses rather than globbing the cwd into a false clear")

    print("\nstatus answers every question in one command:")
    rc, sta = qa(d, "status")
    ck(rc == 0 and all(k in sta for k in
                       ("REVIEW-PASS:", "BLOCKING:", "ADVISORY-CARRIED:", "BLOCKING-OPEN:")),
       f"all four lines are printed {ascii(sta[:80])}")
    ck("BLOCKING-OPEN: 0" in sta and "ADVISORY-CARRIED: 1" in sta,
       "...with live numbers: the resolved blocking is closed, the advisory still carries")
    ck("ADJUDICATION-OPEN" not in sta, "status reports no adjudication state")

    print("\nF30 - staleness is reported, not inherited and not fatal:")
    src = (HELPERS / "gate_runner.py").read_text(encoding="utf-8")
    fg = (HELPERS / "final_gate.py").read_text(encoding="utf-8")
    ck('cur["enrichment"]' in src, "a recorded round carries its enrichment signature")
    ck(json.loads((d / "qa_state.json").read_text(encoding="utf-8"))["rounds"][-1]
       .get("enrichment") is not None,
       "...and a really-recorded round has the field written, not just the code path")
    ck("enrich_signature" in fg, "final_gate consults it")
    ck("[STALE]" in fg, "...and prints a STALE line")
    ck("stale_note" in fg and "checks.append(False)" not in fg.split("stale_note")[1][:400],
       "...that does NOT flip a passing gate to failing")
    # Check the FUNCTION BODY, not nearby text - enrich_signature is defined next to _qa_run_key.
    _body = src.split("def _qa_run_key", 1)[1].split("\ndef ", 1)[0]
    ck("enrich_signature" not in _body,
       "the window is NOT reset by enrichment (that would wipe a recorded round)")
    ck("_qa_inv_hash" in _body,
       "..._qa_run_key keys on the intake corpus hash")
    # F31 - the key must NOT be path-coupled. It used to include `Path(work).resolve()`, so
    # renaming or moving the project folder changed the key, `_qa_load` treated a byte-identical
    # qa_state.json as "a different corpus" and wiped `rounds`; the next deliver.py then shipped
    # a Gaps Report with NO "Known limitations" section and qa_round_number fell back to 0.
    # Observed live: a project reorganised into the `1. Input`/`2. Work Files`/`3. Output`
    # layout lost twelve reviewed-and-accepted limitations for nothing but a folder rename.
    # Strip the docstring first: it QUOTES `Path(work).resolve()` while explaining the fix,
    # so a naive substring check matches the prose that documents the bug, not the bug.
    _code = _body.split('"""', 2)[-1] if _body.count('"""') >= 2 else _body
    ck("resolve()" not in _code,
       "...and is NOT path-coupled, so moving the work dir cannot wipe a recorded window")
    ck("_qa_run_key_legacy(work)" in src,
       "...while the legacy path-coupled key is still honoured on read, so the fix itself "
       "adopts an existing window instead of wiping it")

    print()
    if fails:
        print(f"QA WINDOW PAPERCUTS TEST: FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("QA WINDOW PAPERCUTS TEST: PASS (no secret in the signature; ids printed and accepted; "
          "the current order stated; every refusal names its remedy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
