#!/usr/bin/env python3
"""arithmetic_basis_gate_test.py - the arithmetic gate hands a BASIS decision to the broker. (3.7b)

THE MEASURED FAILURE (2026-09-26 test run). Two decks printed one whole-building total and no
warehouse-only line; the total was read as `warehouseArea` and the stated office was added on top,
so the dashboard's total area over-counted by the office. `gate_runner.py arithmetic` blocked with a
prose remedy, the decision was taken in chat, and two hand repairs recorded it with no question id.

THE GATE SIDE PINNED HERE (clarify's question is pinned by arithmetic_basis_question_test.py):
  1. every over-derivation carries a `shape`; warehouseArea == the stated total with an office
     present is `warehouse_is_total`, and `--emit-json` writes it in the shape clarify consumes
     (and clarify turns it into one BLOCKING question when that function exists);
  2. a broker decision to KEEP the printed total (a waiver whose `expect` matches the figures)
     turns the block into a "KEPT BY BROKER DECISION" note - from `--waivers`, or from
     arithmetic_waivers.json beside the canonical when no flag is given (a hand run honours it);
  3. a waiver whose figures moved is NOT applied and says so ("the question will re-fire");
  4. every other shape blocks exactly as before and is never framed as a basis question;
  5. the DERIVED basis (total minus office) passes; `--emit-json` is written even when empty;
     an unreadable waivers file is a note, never a crash or a silent waiver; `arithmetic_ok` still
     acks.
Every name is invented. Offline. Run: python evals/arithmetic_basis_gate_test.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"
FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _canon(wa, oa, total, pid=14):
    p = {"id": pid, "park": "Quarry Fields", "unit": "Building 2", "city": "Northport",
         "developer": "D", "country": "ZZ", "status": "Available", "areaUnit": "sq ft",
         "warehouseArea": wa}
    if oa is not None:
        p["officeAreaVal"] = oa
    meta = {"client": "T"}
    if total is not None:
        meta["statedTotals"] = {str(pid): {"value": total, "unit": "sq ft",
                                           "source_file": "quarry_fields.pdf",
                                           "locator": "page 3 schedule"}}
    return {"meta": meta, "pois": [], "regions": {}, "properties": [p]}


def _run(canon, *extra, waivers_beside=None, ack=None):
    d = Path(tempfile.mkdtemp(prefix="cbre_ab_"))
    c = d / "canonical.json"
    c.write_text(json.dumps(canon), encoding="utf-8")
    if waivers_beside is not None:
        (d / "arithmetic_waivers.json").write_text(
            waivers_beside if isinstance(waivers_beside, str) else json.dumps(waivers_beside),
            encoding="utf-8")
    if ack is not None:
        (d / "placeholder_audit_ack.json").write_text(json.dumps(ack), encoding="utf-8")
    fj = d / "arithmetic_findings.json"
    args = [a.replace("<D>", str(d)) for a in extra]
    p = subprocess.run([sys.executable, str(GATE), "arithmetic", str(c), "--emit-json", str(fj),
                        *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    found = json.loads(fj.read_text(encoding="utf-8-sig")) if fj.exists() else None
    return p.returncode, out, found, d


def _waiver(wa=214000, oa=12500, total=214000, pid=14):
    return [{"id": pid, "expect": {"warehouseArea": wa, "officeAreaVal": oa, "statedTotal": total},
             "question_id": "q_arith_abc", "why": "broker chose to keep the printed total"}]


def main() -> int:
    print("1. the printed total read as the warehouse area is classified and emitted")
    rc, out, found, _ = _run(_canon(214000, 12500, 214000))
    ck(rc == 1 and "STATUS: BLOCKED" in out, f"it still blocks until decided (rc {rc})")
    ck("the run asks the broker which basis to use (exit 13)" in out,
       "...and the FAIL says the run asks the broker")
    f0 = (found or [{}])[0]
    want = {"id", "park", "unit", "warehouseArea", "officeAreaVal", "stated_total", "area_unit",
            "source_file", "locator", "over_by", "shape"}
    ck(isinstance(found, list) and len(found) == 1 and want <= set(f0)
       and f0.get("shape") == "warehouse_is_total" and f0.get("stated_total") == 214000
       and f0.get("officeAreaVal") == 12500 and f0.get("over_by") == 12500,
       f"--emit-json writes ONE warehouse_is_total finding with every key clarify reads ({f0})")
    try:
        sys.path.insert(0, str(ROOT / "helpers"))
        import clarify as CQ  # noqa: E402
        fn = getattr(CQ, "arithmetic_basis_questions", None)
    except Exception:
        fn = None
    if fn is not None:
        qs = fn(found or [])
        ck(len(qs) == 1 and qs[0].get("blocking") is True,
           f"...which clarify turns into ONE blocking broker question ({len(qs)})")
    else:
        print("  [note] clarify.arithmetic_basis_questions not present - bridge half not checked")

    print("\n2. a KEEP decision whose figures match is honoured")
    d_w = Path(tempfile.mkdtemp(prefix="cbre_abw_"))
    wv = d_w / "w.json"
    wv.write_text(json.dumps(_waiver()), encoding="utf-8")
    rc, out, found, _ = _run(_canon(214000, 12500, 214000), "--waivers", str(wv))
    ck(rc == 0 and "KEPT BY BROKER DECISION" in out and "q_arith_abc" in out,
       f"--waivers: ALL-PASS with the broker-decision note naming the question (rc {rc})")
    ck(found == [], "...and nothing is emitted, so the question does not re-fire")
    rc, out, _, _ = _run(_canon(214000, 12500, 214000), waivers_beside=_waiver())
    ck(rc == 0 and "KEPT BY BROKER DECISION" in out,
       f"no flag: arithmetic_waivers.json BESIDE the canonical is honoured (a hand run) (rc {rc})")

    print("\n3. a waiver never outlives its figures")
    rc, out, found, _ = _run(_canon(215000, 12500, 215000), waivers_beside=_waiver())
    ck(rc == 1 and "waiver NOT applied (figures changed; the question will re-fire)" in out,
       f"changed figures: BLOCKED, and the stale waiver is named (rc {rc})")
    ck(bool(found) and found[0].get("shape") == "warehouse_is_total",
       "...and the finding is emitted again for the bridge")

    print("\n4. every other over-derivation is unchanged")
    rc, out, found, _ = _run(_canon(230000, 12500, 214000))
    ck(rc == 1 and "exit 13" not in out and "arithmetic_ok" in out,
       f"warehouseArea ABOVE the stated total: blocks with the old remedy, no broker framing (rc {rc})")
    ck(bool(found) and found[0].get("shape") == "other", "...emitted with shape 'other'")
    rc, out, found, _ = _run(_canon(214000, None, 200000))
    ck(rc == 1 and bool(found) and found[0].get("shape") == "other",
       f"no office at all (nothing to double-count): shape 'other' (rc {rc})")

    print("\n5. the rest of the contract")
    rc, out, found, _ = _run(_canon(201500, 12500, 214000))
    ck(rc == 0 and found == [], f"the DERIVED basis (total minus office) passes, emits [] (rc {rc})")
    rc, out, found, _ = _run(_canon(214000, 12500, None))
    ck(rc == 0 and found == [], f"no stated total: not applicable, and --emit-json still writes [] (rc {rc})")
    rc, out, found, _ = _run(_canon(214000, 12500, 214000), waivers_beside="{not json")
    ck(rc == 1 and "could not be read" in out and "Traceback" not in out,
       f"an unreadable waivers file is a note and the block stands (rc {rc})")
    rc, out, _, _ = _run(_canon(214000, 12500, 214000), ack={"arithmetic_ok": ["14"]})
    ck(rc == 0 and "ACKED" in out, f"`arithmetic_ok` still acks the property by hand (rc {rc})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
