#!/usr/bin/env python3
"""repair_contract_hint_test.py - the repairs.json contract printed INTO the exit-6 / exit-15
handoffs is the contract the validator enforces. (2026-09-26 test run, fix 1.7)

WHY THIS EXISTS. The shape of a repairs.json entry lived only in repairs.py's docstring,
`validate_entries` and reference/per-property.md, so an orchestrator handed "fix and re-run"
had to go and read them first (the real run wrote 65 entries). `repairs.contract_hint()` now
prints the shape, the required keys, the clear verb, the derived-twin rule and the denied
fields. It is derived LIVE from the module's own registries, and this pins that:
  * the lines name property / expect / set / unset / why / verified_by;
  * every derived-twin pair and every DENIED field is named, from the live registries;
  * the twin rule follows `_rederive_available()` (True -> "re-derives", False -> "MUST");
  * CONTRACT_EXAMPLE, placeholders filled with concrete values, passes `validate_entries`
    with no refusal, so the printed shape can never be one the validator refuses;
  * the text carries no "dispatch" wording (the exit-15 handoff pins its absence nearby);
  * a failure inside the hint returns [] rather than raising into a handoff.
The run.py call sites (`_say_repair_contract` at exit 6 and exit 15) are pinned in the last
section, added by the run.py owner. Offline; synthetic.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    print("== the hint names the entry's keys ==")
    lines = R.contract_hint()
    txt = "\n".join(lines)
    ck(bool(lines) and all(isinstance(ln, str) for ln in lines), f"{len(lines)} line(s) returned")
    for k in ("property", "expect", "set", "unset", "why", "verified_by", "strike_from_source",
              "media", "source_file", "source_locator"):
        ck(k in txt, f"names `{k}`")
    ck("JSON LIST" in txt, "says the file is a JSON LIST")
    ck("dispatch" not in txt.lower(), "carries no 'dispatch' wording")
    ck(not any("dry-run" in ln for ln in lines), "no dry-run line when no work dir is given")
    w = R.contract_hint("some/work dir")
    ck(any("dry-run" in ln and "repairs.py" in ln and "check --work" in ln
           and "some" in ln for ln in w), "a work dir adds the `repairs.py check` dry-run line")

    print()
    print("== twins and denied fields come from the LIVE registries ==")
    twins, src = R._derived_twins()
    ck(bool(twins), f"a twin registry is visible (source: {src})")
    for f, t in twins.items():
        ck(f in txt and t in txt, f"twin pair {f} -> {t} is named")
    for d in sorted(R.DENIED_FIELDS):
        ck(d in txt, f"denied field `{d}` is named")

    orig = R._rederive_available
    try:
        R._rederive_available = lambda: False
        no = "\n".join(R.contract_hint())
        R._rederive_available = lambda: True
        yes = "\n".join(R.contract_hint())
    finally:
        R._rederive_available = orig
    ck("MUST" in no and "cannot re-derive" in no,
       "no re-derivation on the installation -> the twin line says MUST set the twin too")
    ck("re-derives" in yes and "MUST" not in yes,
       "re-derivation available -> the twin line says the source alone is enough")

    saved = R.DERIVED_TWINS
    try:
        R.DERIVED_TWINS = {"aa": "bb", "bb": "aa", "cc": "dd"}
        t2 = "\n".join(R.contract_hint())
    finally:
        R.DERIVED_TWINS = saved
    ck("aa<->bb" in t2 and "cc->dd" in t2 and t2.count("aa<->bb") == 1,
       "a pair registered both ways prints once as a<->b, a one-way pair as a->b")

    print()
    print("== the printed example passes the validator it describes ==")
    ex = copy.deepcopy(R.CONTRACT_EXAMPLE)
    ck(json.dumps(R.CONTRACT_EXAMPLE, ensure_ascii=False) in txt,
       "the first line carries CONTRACT_EXAMPLE verbatim")
    ex["property"]["key"] = "northtown|devco|alpha park"
    ex["expect"] = {"warehouseArea": 10000}
    ex["set"] = {"warehouseArea": 12000}
    ex["why"] = "the brochure's accommodation table states 12,000"
    ex["verified_by"] = "analyst"
    ex["source_file"] = "brochure.pdf"
    ex["source_locator"] = "page 3"
    ok, bad = R.validate_entries([ex], extra_fields={"warehouseArea"})
    ck(len(ok) == 1 and not bad, f"concrete CONTRACT_EXAMPLE validates cleanly (refusals: {bad})")
    ck(set(R.CONTRACT_EXAMPLE) >= {"id", "property", "why", "verified_by"},
       "the example carries every REQUIRED key")

    print()
    print("== it never raises into a handoff ==")
    saved_df = R.DENIED_FIELDS
    try:
        R.DENIED_FIELDS = None           # sorted(None) raises inside the hint
        broken = R.contract_hint()
    finally:
        R.DENIED_FIELDS = saved_df
    ck(broken == [], "an internal failure returns [] (the handoff prints what it printed before)")

    print()
    print("== run.py prints it at exit 6 and exit 15 (the run.py owner's pins) ==")
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    d = src.find("\ndef _say_repair_contract(")
    dbody = src[d:src.find("\ndef ", d + 5)] if d != -1 else ""
    ck("contract_hint(work)" in dbody and "_say_orchestrator(ln)" in dbody
       and "except Exception" in dbody,
       "run._say_repair_contract prints contract_hint(work) through _say_orchestrator, fail-safe")
    i6 = src.find("if any(rc != 0 for rc in g1):")
    j6 = src.find("\n        sys.exit(6)", i6)
    seg6 = src[i6:j6] if 0 < i6 < j6 else ""
    ck("_say_repair_contract(work)" in seg6,
       "exit 6: the call sits inside the pre-build BLOCKED branch, before sys.exit(6)")
    ck(seg6.find("_say_repair_contract(work)") > seg6.find("pre-build gate(s) red - not building"),
       "exit 6: after the QUIET/verbose BLOCKED message")
    ck('print(_reentry("either"))' in src[j6 - 900:j6],
       "exit 6: the re-entry hint still sits within 900 chars of sys.exit(6)")
    i15 = src.find("blocking QA finding(s) unresolved")
    j15 = src.find("_exit_round_trip(work, 15", i15)
    seg15 = src[i15:j15] if 0 < i15 < j15 else ""
    ck("_say_repair_contract(work)" in seg15,
       "exit 15: the call sits between the handoff and the exit-15 round trip")
    ck("dispatch" not in src[i15:i15 + 1200].lower(),
       "exit 15: still no 'dispatch' wording within 1200 chars of the handoff")
    import run as RUN                    # noqa: E402
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        RUN._say_repair_contract(Path("w"))
    ck("JSON LIST" in buf.getvalue() and "dry-run" in buf.getvalue(),
       "calling it prints the contract lines on stdout, dry-run line included")
    saved_ch = R.contract_hint
    try:
        def _raise(*a, **k):
            raise RuntimeError("boom")
        R.contract_hint = _raise
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            RUN._say_repair_contract(Path("w"))
    finally:
        R.contract_hint = saved_ch
    ck(buf2.getvalue() == "", "a raising contract_hint prints nothing and does not raise")

    print()
    if FAILS:
        print(f"REPAIR CONTRACT HINT TEST: FAIL ({len(FAILS)})")
        return 1
    print("REPAIR CONTRACT HINT TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
