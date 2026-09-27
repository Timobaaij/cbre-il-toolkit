#!/usr/bin/env python3
"""input_accounting_reasons_test.py - an excluded input is named with the decision actually taken.

(fix 3.10b, 2026-09-26) A source can now leave the longlist for two broker-decided reasons: the
source-authority answer (B47, entries with no `excluded_by`) and a building the source marks as
let / sold that the broker chose to exclude (`meta.excluded[].excluded_by == "not_available"`). The
input-accounting note used to say "excluded by your source-authority answer" for every exclusion,
which misattributes the second kind. Pinned here:
  1. a not_available exclusion is credited (non-blocking) and its note names the let/sold decision
     and the Gaps Report heading it lands under, NOT the source-authority answer;
  2. a legacy entry with no `excluded_by` keeps the source-authority wording exactly;
  3. an unknown future reason is named verbatim rather than guessed;
  4. `_excluded_reasons` is not a bucket (the input total is unchanged);
  5. (fix 3.24) inputs intake could not open because the path is too long are named in ONE
     non-blocking [SIGNAL] line with the remedy; a malformed entry never crashes the gate.
Offline, invented names. Run: python evals/input_accounting_reasons_test.py"""
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

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _work(excluded, extra_inv=None):
    d = Path(tempfile.mkdtemp(prefix="cbre_accr_"))
    inv = {"clusters": [{"files": ["a.pdf", "let_deck.pdf", "auth_deck.pdf", "odd_deck.pdf"]}]}
    inv.update(extra_inv or {})
    (d / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps(
        {"meta": {"client": "A", "excluded": excluded},
         "properties": [{"id": 1, "park": "P"}]}), encoding="utf-8")
    (d / "source_ledger.csv").write_text(
        "property_id,field,value,source_file,source_locator\n1,park,P,a.pdf,page 1\n",
        encoding="utf-8")
    (d / "unreadable.json").write_text("[]", encoding="utf-8")
    return d


def _run(d):
    p = subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"), "input-accounting",
                        str(d / "canonical.json"), "--work", str(d)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _line(out, name):
    return next((ln for ln in out.splitlines() if name in ln and "[note]" in ln), "")


def main() -> int:
    excluded = [
        {"name": "Let Unit", "source_files": ["let_deck.pdf"], "excluded_by": "not_available",
         "why": "the source marks it 'Let' and you chose to exclude it (question q_na_1)"},
        {"name": "Auth Park", "source_files": ["auth_deck.pdf"], "why": "not evidenced"},
        {"name": "Odd Park", "source_files": ["odd_deck.pdf"], "excluded_by": "future_reason"},
    ]
    d = _work(excluded)
    rc, out = _run(d)
    print("1-3. one note per excluded input, each naming its own decision")
    ck(rc == 0 and "STATUS: ALL-PASS" in out, f"three disclosed exclusions do not block (rc {rc})")
    let = _line(out, "let_deck.pdf")
    ck("no longer available" in let and "let / sold" in let and "source-authority" not in let,
       f"not_available: the let/sold decision is named, not the source-authority answer ({let[:90]!r})")
    auth = _line(out, "auth_deck.pdf")
    ck("excluded by your source-authority answer" in auth,
       "a legacy entry (no excluded_by) keeps the source-authority wording")
    odd = _line(out, "odd_deck.pdf")
    ck("recorded reason: future_reason" in odd, "an unknown reason is named verbatim, never guessed")

    print("\n4. the reasons map is not a bucket")
    b = GR._accounting_buckets(d, d / "canonical.json")
    ck(sorted(b.get("excluded") or []) == ["auth_deck.pdf", "let_deck.pdf", "odd_deck.pdf"]
       and "reasons" not in b, "all three are in the `excluded` bucket and no extra bucket exists")
    ck(GR._excluded_reasons(d / "canonical.json") == {
        "let_deck.pdf": "not_available", "auth_deck.pdf": "source_authority",
        "odd_deck.pdf": "future_reason"}, "_excluded_reasons maps each file to its reason")
    ck(GR._excluded_reasons(d / "missing.json") == {}, "a missing canonical reads as no reasons")

    print("\n5. (3.24) inputs lost to an over-long path are named, never blocking")
    d2 = _work(excluded, {"unreadable_long_paths": [
        "Deep/Folder/Very long brochure name.pdf", {"path": "Deep/Other/second.pdf"}, 7]})
    rc, out = _run(d2)
    sig = [ln for ln in out.splitlines() if "[SIGNAL]" in ln and "longer than Windows allows" in ln]
    ck(rc == 0 and len(sig) == 1 and "3 input(s)" in sig[0] and "second.pdf" in sig[0]
       and "shorter path" in sig[0], f"one [SIGNAL] line with the count, names and remedy (rc {rc})")
    d3 = _work(excluded, {"unreadable_long_paths": "not-a-list"})
    rc, out = _run(d3)
    ck(rc == 0 and "Traceback" not in out and "longer than Windows" not in out,
       "a malformed value is ignored (today's output), never a crash")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
