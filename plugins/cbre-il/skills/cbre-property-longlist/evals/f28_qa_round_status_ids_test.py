#!/usr/bin/env python3
"""f28_qa_round_status_ids_test.py - `qa-round status` prints the ids exit 15 sends you to it for.

THE DEFECT. Exit 15's handoff and SKILL.md both say: fix each blocking finding, record it with
`qa-round resolve --id <id>`, and "ids + findings: `qa-round status`". `status` printed FOUR
COUNTS and no ids. The ids existed and `record` printed them, but the SPINE runs `record` itself
in quiet mode, so that output never reached anyone; on the live run the only way to close the
exit-15 loop was to import gate_runner and call finding_id() by hand on every entry in
qa_state.json. The `--help` text was wrong the same way: it described `--id` as "the ADVISORY
finding id" and `--because` as "why the blocking fix made this ADVISORY false", for a command the
exit-15 loop uses on BLOCKING findings.

WHAT THIS PINS: the whole exit-15 loop closes on `status` output alone, through the real CLI.
  1. `status` prints `BLOCKING <id>  <finding>` for every OPEN blocking finding, untruncated;
  2. the id it prints is the one `resolve --id` accepts;
  3. after a resolve, the struck finding prints as RESOLVED and BLOCKING-OPEN drops by one;
  4. carried advisories print as `ADVISORY <id>  <finding>`;
  5. the four counts are still there, in the same order, for anything already parsing them;
  6. `--help` no longer calls the id an advisory id.
Offline; subprocess against the real CLI so quiet-mode plumbing cannot hide the output.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"
sys.path.insert(0, str(ROOT / "helpers"))
import gate_runner as GR  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def cli(*args) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GATE), "qa-round", *[str(a) for a in args]],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


LONG = ("property=4 field=warehouseArea issue=the card ships the deck's gross internal area as "
        "the warehouse area while the same page states a smaller net figure for the warehouse "
        "element alone, so the headline area overstates the lettable warehouse by the office "
        "and plant components the source itemises separately")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "work"
        w.mkdir()
        (w / "inventory.json").write_text(json.dumps({"folder": "x", "input_hash": "f28"}),
                                          encoding="utf-8")
        rv = Path(td) / "reviews" / "round1"
        rv.mkdir(parents=True)
        (rv / "G-honesty.md").write_text(
            "VERDICT: red\n"
            f"- blocking: {LONG}\n"
            "- blocking: property=2 field=photo issue=hero is the neighbouring unit's render\n"
            "- advisory: property=7 field=motorway issue=junction distance rounded to the mile\n",
            encoding="utf-8")

        print("1. record (as the spine does, output discarded), then status")
        rc, _ = cli("record", "--work", w, "--reviews", rv.parent)
        ck(rc == 0, "record succeeds")
        rc, out = cli("status", "--work", w)
        ck(rc == 0, "status exits 0")
        lines = out.splitlines()
        ck([l.split(":")[0] for l in lines[:4]]
           == ["REVIEW-PASS", "BLOCKING", "ADVISORY-CARRIED", "BLOCKING-OPEN"],
           "the four counts still lead, in the same order (existing readers keep working)")
        ck("BLOCKING-OPEN: 2" in out, "two blocking findings are open")
        st = json.loads((w / "qa_state.json").read_text(encoding="utf-8"))
        blocking = st["rounds"][0]["blocking"]
        ids = {GR.finding_id(e): e for e in blocking}
        printed = dict(re.findall(r"^  BLOCKING ([0-9a-f]{10})  (.+)$", out, re.M))
        ck(set(printed) == set(ids),
           f"status prints a `BLOCKING <id>  <finding>` line per open finding ({len(printed)} of "
           f"{len(ids)}), with the id finding_id() would derive")
        long_id = GR.finding_id(f"G-honesty: {LONG}")
        ck(printed.get(long_id, "").endswith(LONG[-60:]),
           "the finding is printed WHOLE, not cut at 110 characters like `record` does - status "
           "is where the operator is sent to READ it")
        adv = re.findall(r"^  ADVISORY ([0-9a-f]{10})  (.+)$", out, re.M)
        ck(len(adv) == 1 and "motorway" in adv[0][1]
           and adv[0][0] == GR.finding_id(st["rounds"][0]["advisory"][0]),
           "the carried advisory prints as `ADVISORY <id>  <finding>` with its resolvable id")
        ck("NEXT:" in out and "resolve" in out,
           "with open blocking findings it says what to do next")

        print("2. the loop closes on status output alone")
        rc, rout = cli("resolve", "--work", w, "--id", long_id, "--because",
                       "re-read the page and set warehouseArea to the stated net warehouse figure")
        ck(rc == 0 and f"OK resolved {long_id}" in rout,
           "the id copied from `status` is the id `resolve` accepts")
        rc, out2 = cli("status", "--work", w)
        ck("BLOCKING-OPEN: 1" in out2, "BLOCKING-OPEN drops to 1")
        ck(f"  RESOLVED {long_id}  " in out2 and f"  BLOCKING {long_id}  " not in out2,
           "the struck finding prints as RESOLVED, not as BLOCKING")
        other = next(i for i in ids if i != long_id)
        ck(f"  BLOCKING {other}  " in out2, "the still-open finding stays BLOCKING")
        rc, _ = cli("resolve", "--work", w, "--id", other, "--because",
                    "re-bound the hero to the property's own cover photo from page 1")
        rc, out3 = cli("status", "--work", w)
        ck("BLOCKING-OPEN: 0" in out3 and "NEXT:" not in out3,
           "with nothing open there is no NEXT nag; the counts and RESOLVED lines remain")

        print("3. --help describes the flags for the loop that actually uses them")
        rc, h = cli("--help")
        ck("advisory finding id" not in h.lower(),
           "`--id` is no longer described as 'the advisory finding id'")
        ck("this advisory false" not in h.lower(),
           "`--because` is no longer 'why the blocking fix made this advisory FALSE'")
        ck("BLOCKING or ADVISORY" in h and "qa-round status" in h,
           "`--id` says: a BLOCKING or ADVISORY id, as printed by `qa-round status`")

        print("4. the docs and the runtime agree on where the ids are")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        ck("`qa-round status`" in skill and "resolve" in skill,
           "SKILL.md still sends the operator to `qa-round status` for the ids (now true)")

    print()
    if FAILS:
        print(f"F28 QA-ROUND STATUS IDS TEST: FAIL ({len(FAILS)})")
        return 1
    print("F28 QA-ROUND STATUS IDS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
