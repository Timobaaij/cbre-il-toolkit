#!/usr/bin/env python3
"""qa_reviewer_scope_test.py - G-trace and G-honesty review DIFFERENT claims. (1.4, and the
reference/gates.md sentences of the 2026-09-26 gate fixes)

THE COST, 2026-09-26 test run. Both data reviewers owned "is this gap row true?": g-trace.md called a
false "absent in all sources" row "a blocking trace failure" and g-honesty.md listed INVENTION and
UNDER-CAPTURE. Both keyword-swept every deck's gap rows and filed the same findings (overheadDoors on
four ids, a stale note, an area, an epc) - two Opus reviews of the same page and two resolves each.
The split is now by CLAIM POLARITY and nothing is dropped:
  * G-trace owns POSITIVE claims (every populated value and non-gap ledger row, INVENTION included,
    locator precision, computed values, decision re-derivation);
  * G-honesty owns NEGATIVE claims and DISCLOSURE (gap rows, sentinels, report lines, attributions)
    and is the ONLY reviewer of under-capture.
Pinned here: both prompts carry their scope block and an OUT OF SCOPE line, the old overlapping
sentence is gone, both still render with every slot filled, gates.md rows say the same, the two
phrases capture_contract_test pins survive, and the gates.md sentences for the other gate fixes
(value-format, capture-symmetry strict alias, blank title, arithmetic basis, --batch, pointer
dispatch, model tiers) are present. Offline. Run: python evals/qa_reviewer_scope_test.py"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import prompts_render as PR  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _row(md: str, gate: str) -> str:
    return next((ln for ln in md.splitlines() if ln.startswith(f"| {gate} |")), "")


def main() -> int:
    tr = (ROOT / "prompts" / "g-trace.md").read_text(encoding="utf-8")
    ho = (ROOT / "prompts" / "g-honesty.md").read_text(encoding="utf-8")
    gates = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8")

    print("1. the two prompts split by claim polarity")
    ck("POSITIVE claims" in tr and "OUT OF SCOPE" in tr,
       "g-trace.md carries its POSITIVE-claims scope and an OUT OF SCOPE line")
    ck(not re.search(r"absent in all sources.{0,120}blocking trace failure", tr, re.S),
       "g-trace.md no longer claims false gap rows as 'a blocking trace failure'")
    ck("INVENTION" in tr and "DECISION-CORRECTNESS" in tr and "match_verify.json" in tr,
       "...and keeps INVENTION and the decision re-derivation list")
    ck("NEGATIVE claims" in ho and "ONLY reviewer" in ho and "OUT OF SCOPE" in ho,
       "g-honesty.md carries its NEGATIVE-claims scope, 'ONLY reviewer' of under-capture, OUT OF SCOPE")
    ck("doubt" in ho and "capture-symmetry" in ho and "[FAIL]" in ho,
       "...and starts from the capture-symmetry SIGNAL/FAIL lines, doubt-option figures included")
    ck("INVENTION: a value on a card" not in ho,
       "g-honesty.md no longer co-owns INVENTION (G-trace owns it)")
    for kind, txt in (("g-trace", tr), ("g-honesty", ho)):
        ck("openpyxl.load_workbook" in txt and "never by grepping" in txt,
           f"{kind}.md keeps the decoding-reader line (f25 pin)")
        try:
            out = PR.render(kind, {"SKILL_DIR": "/s", "WORK": "/w", "REVIEWS_ROUND_DIR": "/w/r1",
                                   "CONTEXT": "(none)"})
            ck("{{" not in out, f"{kind}.md still renders with no unfilled slot")
        except Exception as e:
            ck(False, f"{kind}.md renders ({type(e).__name__}: {e})")

    print("\n2. gates.md says the same")
    rt, rh = _row(gates, "G-trace"), _row(gates, "G-honesty")
    ck("POSITIVE claims only" in rt and "INVENTION" in rt and "G-honesty's" in rt,
       "G-trace row: POSITIVE claims only, owns INVENTION, gap rows are G-honesty's")
    ck("confidently-wrong" in rt and "confidently-wrong" not in rh,
       "the confidently-wrong-decision sentence moved to the G-trace row")
    ck("sole owner of the under-capture sweep" in rh and "no invented number" not in rh,
       "G-honesty row: sole owner of the under-capture sweep; invention is G-trace's")
    ck("UNDER-CAPTURE IS THE MIRROR IMAGE OF FABRICATION AND RANKS THE SAME" in rh
       and "capture-symmetry" in rh, "...keeping the two phrases capture_contract_test pins")

    print("\n3. the other 2026-09-26 gate sentences")
    vf, cs = _row(gates, "G-value-format"), _row(gates, "G-capture-symmetry")
    ck("COUNT_FIELDS" in vf and "officeAreaVal" in vf and "No cascade" in vf,
       "a G-value-format row with the three exemptions and the no-cascade rule")
    ck("strict_alias_ok" in cs and "ALIAS_PROMOTIONS" in cs and "doubt-option" in cs,
       "a G-capture-symmetry row: advisory, the strict-alias block + its ack, the doubt signal")
    ck("BLANK" in _row(gates, "G-coverage") and "blocks on its own" in gates,
       "G-coverage row and the A14c paragraph: a blank title blocks on its own")
    ck("warehouse_is_total" in _row(gates, "G-arithmetic") and "arithmetic_ok" in _row(gates, "G-arithmetic"),
       "G-arithmetic row: the warehouse_is_total broker question; arithmetic_ok stays the hand ack")
    ck("--batch <file.json>" in gates and "--id <id> --because" in gates,
       "rule 4 names the batch form beside the single form")
    ck("The pointer form (SKILL.md step 3) satisfies this" in gates, "rule 2 sanctions the pointer form")
    ck("ONLY where the host lets you pick" in gates and "| strongest available |" in gates,
       "the sub-agent model-tier note and table")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
