#!/usr/bin/env python3
"""qa_resolve_batch_test.py - `qa-round resolve --batch` resolves several findings in ONE call. (2.8)

THE COST, 2026-09-26 test run. The QA window's findings were resolved one `resolve --id <id>
--because ...` call at a time - a tool round-trip per finding for a step that is pure record-keeping.
`--batch <file.json>` takes a list of {"id", "because"} and applies the SAME guards to every entry
before anything is written. Pinned here, against the real CLI:
  1. two valid entries: both resolved in one call, and `status` shows BLOCKING-OPEN 0;
  2. ALL-OR-NOTHING: an unknown id, a short reason, a duplicate id, a non-list, invalid JSON - each
     is rc 1 and leaves qa_state.json BYTE-IDENTICAL (a half-applied batch cannot exist);
  3. `--id` together with `--batch` is refused;
  4. the single `--id <id> --because` path is unchanged, and the status NEXT line names both forms;
  5. `mode` still has exactly the three choices (batch is a FLAG, qa_round_test pins the modes).
Offline, invented findings. Run: python evals/qa_resolve_batch_test.py"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
GRP = str(HELPERS / "gate_runner.py")
sys.path.insert(0, str(HELPERS))
import gate_runner as G  # noqa: E402

B1 = ("- blocking: property=3 field=breeam issue=Harrier Point ships an impossible BREEAM grade "
      "action=strike it to the sentinel")
B2 = ("- blocking: property=5 field=overheadDoors issue=the deck states 4 level access doors but "
      "the card ships a gap action=set overheadDoors from page 4")
ADV = ("- advisory: property=- field=region issue=two granularities across the dataset "
       "action=normalise to one level")
WHY1 = "struck breeam to the sentinel and added a gap row citing the empty source cell"
WHY2 = "set overheadDoors to 4 via repairs.json citing page 4 of the deck"
FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def qa(work, *args):
    r = subprocess.run([sys.executable, GRP, "qa-round", *args, "--work", str(work)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ids_of(out, kind):
    out_ids = []
    for ln in out.splitlines():
        tok = ln.strip().split()
        if len(tok) >= 2 and tok[0] == kind:
            out_ids.append(tok[1])
    return out_ids


def fresh():
    d = Path(tempfile.mkdtemp(prefix="cbre_qa_batch_"))
    rv = d / "reviews" / "round1"
    rv.mkdir(parents=True)
    (rv / "G-honesty.md").write_text(B1 + "\n" + ADV + "\n", encoding="utf-8")
    (rv / "G-trace.md").write_text(B2 + "\n", encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}), encoding="utf-8")
    rc, rec = qa(d, "record", "--reviews", str(d / "reviews"))
    return d, rc, rec


def batch_file(d, obj, raw=None):
    f = d / f"batch_{len(list(d.glob('batch_*.json')))}.json"
    f.write_text(raw if raw is not None else json.dumps(obj), encoding="utf-8")
    return f


def main() -> int:
    print("1. two valid entries resolve in one call")
    d, rc, rec = fresh()
    bids = ids_of(rec, "BLOCKING")
    ck(rc == 0 and len(bids) == 2, f"fixture: two blocking findings recorded ({bids})")
    rc, st = qa(d, "status")
    ck("--batch <file.json>" in st and "--id <id> --because" in st,
       "the status NEXT line names the single form AND the batch form")
    f = batch_file(d, [{"id": bids[0], "because": WHY1}, {"id": bids[1], "because": WHY2}])
    rc, out = qa(d, "resolve", "--batch", str(f))
    ck(rc == 0 and out.count("OK resolved ") == 2 and out.count("CARRIED:") == 1,
       f"rc 0, one OK line per entry, one CARRIED/NEXT tail (rc {rc})")
    rc, st = qa(d, "status")
    ck("BLOCKING-OPEN: 0" in st, "status then shows BLOCKING-OPEN 0")
    res = (json.loads((d / "qa_state.json").read_text(encoding="utf-8"))["rounds"][-1]
           .get("resolved") or {})
    ck(set(res) == set(bids) and res[bids[0]]["because"] == WHY1
       and res[bids[0]]["fingerprint"] == res[bids[1]]["fingerprint"],
       "both reasons are recorded verbatim, under one artefact fingerprint")

    print("\n2. all-or-nothing: a bad batch writes NOTHING")
    for label, obj, raw in (
            ("one unknown id", [{"id": "bogus123", "because": WHY1}], None),
            ("a short reason beside a good entry", "GOOD+SHORT", None),
            ("a duplicate id", "DUP", None),
            ("not a list", {"id": "x", "because": WHY1}, None),
            ("an empty list", [], None),
            ("invalid JSON", None, "[{not json")):
        d2, _, rec2 = fresh()
        b2 = ids_of(rec2, "BLOCKING")
        if obj == "GOOD+SHORT":
            obj = [{"id": b2[0], "because": WHY1}, {"id": b2[1], "because": "fixed"}]
        elif obj == "DUP":
            obj = [{"id": b2[0], "because": WHY1}, {"id": b2[0], "because": WHY2}]
        before = (d2 / "qa_state.json").read_bytes()
        f2 = batch_file(d2, obj, raw)
        rc, out = qa(d2, "resolve", "--batch", str(f2))
        after = (d2 / "qa_state.json").read_bytes()
        ck(rc == 1 and "STATUS: BLOCKED" in out and before == after and "OK resolved" not in out,
           f"{label}: rc {rc}, qa_state.json byte-identical, nothing resolved")
        if label == "a short reason beside a good entry":
            ck("entry 2" in out and ">= 20" in out, "...naming the faulty entry and the rule")

    print("\n3. --id together with --batch is refused")
    d3, _, rec3 = fresh()
    b3 = ids_of(rec3, "BLOCKING")
    f3 = batch_file(d3, [{"id": b3[0], "because": WHY1}])
    before = (d3 / "qa_state.json").read_bytes()
    rc, out = qa(d3, "resolve", "--batch", str(f3), "--id", b3[1], "--because", WHY2)
    ck(rc == 1 and "--id OR --batch" in out and (d3 / "qa_state.json").read_bytes() == before,
       f"rc {rc}, refused, nothing written")

    print("\n4. the single --id path is unchanged")
    rc, out = qa(d3, "resolve", "--id", b3[0], "--because", WHY1)
    ck(rc == 0 and out.startswith(f"OK resolved {b3[0]}:") and "CARRIED:" in out,
       f"`resolve --id <id> --because` still resolves one finding (rc {rc})")
    rc, out = qa(d3, "resolve", "--id", b3[1], "--because", "too short")
    ck(rc == 1 and "--because must state WHY the finding is now false (>= 20 chars)" in out,
       "...and still refuses a thin reason with the same words")

    print("\n5. batch is a flag, not a mode")
    src = Path(GRP).read_text(encoding="utf-8")
    ck('choices=["record", "status", "resolve"]' in src, "qa-round keeps exactly three modes")
    ck(callable(getattr(G, "_qa_find", None)) and callable(getattr(G, "_qa_check_because", None)),
       "the shared guards are one function each (_qa_find, _qa_check_because)")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
