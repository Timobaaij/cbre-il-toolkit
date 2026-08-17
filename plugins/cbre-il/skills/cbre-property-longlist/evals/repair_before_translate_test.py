#!/usr/bin/env python3
"""repair_before_translate_test.py - repairs must settle canonical BEFORE translation. (B66)

The free-text translation stage exits 12 to fetch a round from an isolated sub-agent, and it
sits before the pre-build gates because - by its own docstring - it must see the FINAL prose.
Property repairs also write prose, and they ran AFTER it. So on any pass where translation was
pending, repairs never ran at all; a repair that introduced prose was invisible until the pass
after the round; and every repair batch carrying prose cost a whole extra round-trip plus an
agent dispatch. A live run paid three of them, for values that were already English.

What this pins, structurally (the stages are inside one 3,000-line function, so ordering is
the testable contract rather than a return value):
  * repairs are applied BEFORE translate.run_stage, so one pass sees both;
  * the repair LEDGER writer is defined before it is called, which is what moving the block
    could most easily break;
  * the per-property projection stays AFTER translation, so the view a human opens shows the
    prose that ships rather than its source language;
  * the gates still run after all of it, so nothing skips validation;
  * repairs.run itself is unchanged and idempotent - the reorder must not have altered what a
    repair DOES, only when it happens.
Offline; no network, no build.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

SRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def at(needle: str) -> int:
    i = SRC.find(needle)
    if i < 0:
        raise AssertionError(f"anchor vanished from run.py: {needle!r}")
    return i


def main() -> int:
    print("repair_before_translate_test - one pass, not two")

    i_ledger = at("def _ledger_append(")
    i_repair = at("_rrep = _repairs.run(work, write=True)")
    i_call = at("_ledger_append(work / \"source_ledger.csv\", _lrows)")
    i_trans = at("_t_rc = translate.run_stage(")
    i_proj = at("import project_properties as _proj")
    i_gates = at("step(\"Checking the data\")")

    ck(i_repair < i_trans,
       "repairs are applied BEFORE the translation stage - the whole point of the reorder")
    ck(i_ledger < i_call,
       "the repair ledger writer is defined before it is called (what the move could break)")
    ck(i_trans < i_proj,
       "the per-property projection stays AFTER translation, so it shows the shipped prose")
    ck(i_repair < i_gates and i_trans < i_gates,
       "and both still run before the pre-build gates - nothing skips validation")

    exit12 = at("_exit_round_trip(work, 12,")
    ck(i_repair < exit12,
       "repairs precede the exit-12 handoff, so a repair-introduced value joins THAT round "
       "instead of forcing another one")

    # repairs.run is unchanged: same result, and idempotent across passes
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        (w / "canonical.json").write_text(json.dumps({
            "meta": {"client": "T", "units": {"area": "sq m"}}, "pois": [], "regions": {},
            "properties": [{"id": 1, "park": "Alpha Park", "city": "Bor", "developer": "CTP",
                            "country": "CZ", "warehouseArea": 10000, "areaUnit": "sq m",
                            "status": "tbd", "photo": "x", "gallery": ["x"]}]}),
            encoding="utf-8")
        (w / "repairs.json").write_text(json.dumps([{
            "id": "rp-001", "property": {"key": "bor|ctp|alpha park", "id": 1},
            "expect": {"status": "tbd"}, "set": {"status": "Upcoming construction"},
            "why": "page 5 prints 'Proxima construccion'", "verified_by": "t@cbre.com"}]),
            encoding="utf-8")
        r1 = R.run(w, write=True)
        ck(len(r1["applied"]) == 1, "a repair still applies exactly as before the reorder")
        after = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
        ck(after["properties"][0]["status"] == "Upcoming construction", "and its value landed")
        r2 = R.run(w, write=True)
        ck(len(r2["applied"]) == 1 and not r2["superseded"],
           "and it is idempotent - a re-applied repair is not mistaken for drift")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
