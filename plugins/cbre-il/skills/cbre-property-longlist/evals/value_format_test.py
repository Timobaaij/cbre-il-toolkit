#!/usr/bin/env python3
"""value_format_test.py - a field is WRITTEN the same way on every property. (B59)

THE DEFECT, from a delivered client dashboard. `divisibleFrom` shipped '10,000 sq. m' on twelve
cards and a bare '5000' on the thirteenth; `clearHeight` shipped '10 m' on twenty-three and a
bare '10' on six. Same field, same grid, two formats - one option quoting a quantity the reader
has to guess the unit of. Nothing caught it: validate-data checks types and pair-consistency,
arithmetic checks a derived total against a stated total, and neither has any opinion about how
a value READS. Same family as v28 ('tbd sq ft') and v32 (officeArea as a bare '1200').

WHY THE SIGNAL IS INTRA-FIELD. A bare number is only suspicious when SIBLING values of the SAME
field are written with a unit. That is what makes the gate quiet enough to be blocking.

THE TWO FALSE POSITIVES THIS PINS, both of which a looser first version actually raised against
the live data - they are the reason the rule is "a magnitude followed by a letter-led, digit-free
unit" rather than "contains a letter":
  * `loadingDocks` - counts (72, 74, 80) beside two decks quoting a dock RATIO ('1 per 650 sq. m').
    A count is correctly bare; demanding a unit here would push an agent to invent one.
  * `earlyAccess` - '2027' beside 'Q1 2028'. That is coarser PRECISION, not a missing unit, and
    "fixing" it would mean inventing a quarter the source never stated.

AND WHAT IT DELIBERATELY DOES NOT DO: auto-repair. Appending the siblings' unit to a bare number
means DECIDING the field is an area; a wrong guess silently relabels a count or a power rating,
which is the 10.76x class. The gate blocks and names the source to read; the fix is an attributed
work/overrides.json entry, or a question to the broker.
Offline.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"


def _canon(props):
    base = {"country": "CZ", "city": "Bor", "developer": "D", "park": "P",
            "areaUnit": "sq m", "rentUnit": "€/sq m/yr"}
    return {"meta": {"client": "Fmt", "units": {"area": "sq m"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def _run(canonical: Path):
    p = subprocess.run([sys.executable, str(GATE), "value-format", str(canonical)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # --- the live defect, reproduced ---
        bad = d / "bad.json"
        bad.write_text(json.dumps(_canon([
            dict(id=1, divisibleFrom="10,000 sq. m", clearHeight="10 m"),
            dict(id=2, divisibleFrom="11,500 sq. m", clearHeight="10 m"),
            dict(id=3, divisibleFrom="5,000 sq. m", clearHeight="12 m"),
            dict(id=4, divisibleFrom="5000", clearHeight="10"),      # <- both offenders
        ])), encoding="utf-8")
        rc, out = _run(bad)
        ck(rc == 1 and "STATUS: BLOCKED" in out,
           "a field written two ways BLOCKS - it cannot reach a client dashboard")
        ck("`divisibleFrom`" in out, "the offending field is named")
        ck("id=4" in out, "the offending PROPERTY is named, so the fix is one lookup")
        ck("'5000'" in out, "the offending value is quoted")
        ck("sqm" in out.replace("sq. m", "sqm").replace("sq m", "sqm"),
           "the siblings' unit is reported so the broker knows what is being asked")
        ck("overrides.json" in out, "the fix route (attributed override) is named")
        ck("ASK THE BROKER" in out, "and asking the broker is named when the source is silent")
        ck("do NOT assume" in out or "not assume" in out.lower(),
           "the gate explicitly refuses to let the orchestrator guess the unit")
        ck("`clearHeight`" in out, "a second inconsistent field is reported in the same pass")

        # --- false positive 1: counts beside a ratio ---
        counts = d / "counts.json"
        counts.write_text(json.dumps(_canon([
            dict(id=1, loadingDocks="72"), dict(id=2, loadingDocks="74"),
            dict(id=3, loadingDocks="80"), dict(id=4, loadingDocks="1 per 650 sq. m"),
            dict(id=5, loadingDocks="1 per 1000 m2"),
        ])), encoding="utf-8")
        rc2, out2 = _run(counts)
        ck(rc2 == 0 and "`loadingDocks`" not in out2,
           "a COUNT beside a RATIO is not flagged - a ratio is not a unit, and a count is "
           "correctly bare")

        # --- false positive 2: coarser precision, not a missing unit ---
        dates = d / "dates.json"
        dates.write_text(json.dumps(_canon([
            dict(id=1, earlyAccess="Q1 2028"), dict(id=2, earlyAccess="Q3 2027"),
            dict(id=3, earlyAccess="2027"), dict(id=4, earlyAccess="2027"),
        ])), encoding="utf-8")
        rc3, out3 = _run(dates)
        ck(rc3 == 0 and "`earlyAccess`" not in out3,
           "'2027' beside 'Q1 2028' is coarser PRECISION, not a missing unit - flagging it "
           "would push an agent to invent a quarter")

        # --- a consistently-bare numeric field is fine (the chrome formats it) ---
        nums = d / "nums.json"
        nums.write_text(json.dumps(_canon([
            dict(id=1, warehouseArea=57600), dict(id=2, warehouseArea=42930),
            dict(id=3, warehouseArea=75000),
        ])), encoding="utf-8")
        rc4, out4 = _run(nums)
        ck(rc4 == 0 and "STATUS: ALL-PASS" in out4,
           "a field that is numeric on EVERY property passes - consistency is the test")

        # --- one written sibling is not enough evidence to call it ---
        thin = d / "thin.json"
        thin.write_text(json.dumps(_canon([
            dict(id=1, someField="10 m"), dict(id=2, someField="5000"),
        ])), encoding="utf-8")
        rc5, out5 = _run(thin)
        ck(rc5 == 0, "a single written sibling is below the evidence threshold (no false alarm)")

        # --- siblings that disagree about their OWN unit are not a guessable fix ---
        mixed = d / "mixed.json"
        mixed.write_text(json.dumps(_canon([
            dict(id=1, someField="10 m"), dict(id=2, someField="10 ft"),
            dict(id=3, someField="10 acres"), dict(id=4, someField="5000"),
        ])), encoding="utf-8")
        rc6, out6 = _run(mixed)
        ck(rc6 == 0,
           "when the written siblings disagree about their own unit the gate stays silent - "
           "there is no dominant form to point at, and naming one would be the guess it bans")

    # The rule must be IN THE SKILL, not in an operator's head - this skill is shared.
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ck("value-format" in skill, "SKILL.md names the gate in the exit-6 row")
    ck("ASK THE BROKER" in skill,
       "SKILL.md tells the orchestrator to ASK when the source does not settle the unit")
    contract = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    ck("WRITE THE VALUE THE WAY THE SOURCE PRINTS IT" in contract,
       "the reader contract carries the format rule")
    ck("A pure COUNT is correctly bare" in contract,
       "...and its boundary, so a reader does not bolt a unit onto a count")
    run_src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    ck('"value-format"' in run_src, "the spine RUNS the gate (not orchestrator-remembered)")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
