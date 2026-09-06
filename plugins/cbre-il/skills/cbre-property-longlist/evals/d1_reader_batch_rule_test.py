#!/usr/bin/env python3
"""d1_reader_batch_rule_test.py - the reader prompts state the one-batch obligation (D1), the
distinct-hero rule (D6) and the actionable-doubt contract (D13/D4), in BOTH templates and in
the contract they point at, and the batch rule is a self-checkable obligation rather than a
permission.

THE DEFECTS, measured on a live 7-deck run.
  D1 (SPEED). The seven reader sub-agents were about 80% of the run's wall-clock and the
     round is gated by the slowest deck (693 s). Page count did not predict duration (a 7-page
     deck took 390 s, a 10-page deck 246 s); the number of separate round trips did, at about
     17 s each. The rule "request every candidates_sheet and render in ONE message" ALREADY
     EXISTED in reader-text.md ground rule 2 and was not followed. Restating it louder is not
     a fix, so this eval pins the DESIGN changes that make it stick: the batch is stated as an
     obligation ("NO IMAGE OPENED BEFORE IT") ahead of the three-call cap rather than as a
     sub-clause exception to it; opening one sheet first is named as the failure; the only
     follow-up is bounded to one message; the agent is given a calibrated expectation it can
     check mid-run in the unit that actually costs time (messages, not tool calls); the
     contract read and the manifest print are batched into one message; and the reader
     reports its message count in its final message so the next run has the measurement this
     one lacked. The raster prompt keeps FIVE per message but now states why (a 180-dpi
     full-page render is several MB; the text-mode aids are 384 to 480 px thumbnails).
  D6 (QUALITY). One 5-page deck yielded two records that both carried page_no 1 / heroRef 0,
     so both cards shipped the same masterplan CGI (four times across two cards, counting each
     card's first gallery slide) while the cover page the reader had assigned to one of them
     carried a real aerial photograph. The images gate blocked it, costing a correction round.
  D13/D4 (CORRECTNESS). Five of eight broker answers to reader doubts never reached a card:
     the doubt declared no canonical field, or no options, so the answer was recorded and
     dropped. Where options WERE supplied they were prose ('all three office lines combined'),
     the broker picked one, and the auto-repair wrote that sentence into officeArea with a
     null officeAreaVal, an entry the run's own validator refuses.

What this pins (on render(), the canonical single-file instruction, and on the split files):
  1. reader-text: the obligation headline, the failure named, one bounded follow-up, the
     obligation stated BEFORE the cap, the D1 citation, the five-message calibration, the
     eighth-message drift trigger, contract + manifest in one message, message count reported;
  2. reader-raster: back-to-back batches of five with the stated size reason, the calibration
     in its own terms (4 + ceil(pages / 5)), contract + manifest in one message;
  3. both: the D6 rule with its honest fallback ("never invent a distinction"), and the
     D13/D4 contract (field AND options; value-led options with the valid/invalid pair; never
     a computed total; the stated consequence);
  4. interpretation.md: the same three rules, so the contract and the reminders agree, and the
     f02 needles the existing batch eval pins are untouched;
  5. the new rules live in the COMMON half (below the split marker), never in a per-deck stub;
  6. no em dash is authored into either rendered prompt;
  7. grounded in the code: a doubt shaped as the new contract says is stamped landable by
     clarify.agent_doubt_questions; one lacking options, or lacking a field, is not.

Run: python evals/d1_reader_batch_rule_test.py"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import prompts_render as PR  # noqa: E402

_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_AUTO = {"SKILL_DIR", "CONTEXT", "FIELD_REGISTRY", "COMMON_POINTER"}

VALID_OPTION = '`"24,230 sq ft (all three office lines combined)"` is valid'
INVALID_OPTION = '`"all three office lines combined"` is refused'


def _render(kind: str) -> str:
    tpl = (PR.TEMPLATE_DIR / f"{kind}.md").read_text(encoding="utf-8")
    return PR.render(kind, {s: f"<{s}>" for s in set(_SLOT_RE.findall(tpl)) if s not in _AUTO})


def _flat(s: str) -> str:
    """Whitespace-normalised, so a needle is not broken by a line wrap."""
    return re.sub(r"\s+", " ", s)


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    text = _render("reader-text")
    raster = _render("reader-raster")
    ftext, fraster = _flat(text), _flat(raster)

    # (1) reader-text: the batch is an obligation the agent can self-check
    check("EVERY VISUAL AID IN ONE MESSAGE, AND NO IMAGE OPENED BEFORE IT" in ftext,
          "reader-text: the batch obligation is the headline of its own rule")
    check("IS the failure" in ftext,
          "reader-text: opening one sheet and choosing the next read from it is named the failure")
    check("One follow-up" in ftext and "a second follow-up is drift" in ftext,
          "reader-text: exactly one follow-up message for ambiguous tiles, a second is drift")
    check(ftext.index("NO IMAGE OPENED BEFORE IT") < ftext.index("Maximum three tool calls per message"),
          "reader-text: the obligation is stated BEFORE the three-call cap, not as its sub-clause")
    check("worded as a permission (D1)" in ftext,
          "reader-text: says the rule failed as a permission and cites D1")
    check("well-run deck is FIVE messages" in ftext,
          "reader-text: a calibrated expectation in messages, the unit that costs time")
    check("pages + sheets + 5" in ftext,
          "reader-text: the tool-call expectation (pages + sheets + 5) so the count is not misread")
    check("eighth message" in ftext,
          "reader-text: a concrete drift trigger the agent can notice mid-run")
    check("Tool-call budget 60 is the hard ceiling" in ftext,
          "reader-text: the 60 budget stays, named as the ceiling a well-run deck never approaches")
    check("the cap costs no round trip" in ftext,
          "reader-text: says why the three-call cap stays (it throttles nothing independent)")
    check("SAME message as your manifest-entry print" in ftext,
          "reader-text: the contract read and the manifest print are one message")
    check("how many MESSAGES you sent" in ftext,
          "reader-text: the final message reports the message count (the missing measurement)")

    # (2) reader-raster: bounded batches with the reason, its own calibration
    check("BACK-TO-BACK BATCHES OF FIVE, NEVER ONE PER MESSAGE" in fraster,
          "reader-raster: the batch obligation is the headline of its own rule")
    check("180-dpi" in fraster and "384 to 480 px" in fraster,
          "reader-raster: states WHY five and not all (full-page render size vs thumbnails)")
    check("IS the failure" in fraster and "(D1)" in fraster,
          "reader-raster: names the one-page loop as the failure and cites D1")
    check("4 + ceil(pages / 5) messages" in fraster,
          "reader-raster: a calibrated expectation in messages, in raster terms")
    check("pages + 5" in fraster, "reader-raster: the tool-call expectation")
    check("SAME message as your manifest-entry print" in fraster,
          "reader-raster: the contract read and the manifest print are one message")
    check("how many MESSAGES you sent" in fraster,
          "reader-raster: the final message reports the message count")

    # (3) both: D6 and D13/D4
    for name, out, flat in (("reader-text", text, ftext), ("reader-raster", raster, fraster)):
        check("DO NOT SHARE A HERO" in flat and "never invent a distinction" in flat
              and "(D6" in flat,
              f"{name}: D6 distinct-hero rule with its honest fallback and citation")
        check("FOR THE ANSWER TO REACH A CARD" in flat and "BOTH `field`" in flat
              and "AND `options`" in flat,
              f"{name}: an actionable doubt needs BOTH field AND options")
        check("LEADS WITH THE FIGURE AND ITS UNIT" in flat,
              f"{name}: options on an arithmetic field lead with the figure and unit")
        check(VALID_OPTION in flat and INVALID_OPTION in flat,
              f"{name}: the valid/invalid option pair from the measured run is shown")
        check("NEVER offer a total you did not read" in flat
              and "Python owns all arithmetic" in flat,
              f"{name}: never a computed total; Python owns all arithmetic")
        check("recorded and DROPPED" in flat and "(D13, D4)" in flat,
              f"{name}: the consequence of non-compliance is stated and cited")
        # (6) no em dash authored (code point spelled as an escape: the house rule forbids
        # authoring the character itself, in evals included)
        check(chr(0x2014) not in flat, f"{name}: no em dash in the rendered prompt")

    # (4) the contract agrees with the reminders, and f02's pinned needles are untouched
    contract = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    fcontract = _flat(contract)
    check("opening NO image before that message" in fcontract,
          "interpretation.md: the batch paragraph forbids opening an image before the batch")
    check("This is an OBLIGATION, not a permission" in fcontract and "(D1)" in contract,
          "interpretation.md: the batch is an obligation, with the measured cost and D1 cited")
    check("in ONE follow-up message, never one at a time" in fcontract,
          "interpretation.md: individual candidate images go in one follow-up message")
    check("MORE THAN ONE record, the records do not share a hero" in fcontract
          and "never invent a distinction" in fcontract and "(D6)" in contract,
          "interpretation.md: the D6 rule in the hero bullet, with the honest fallback")
    check("do not share a `page_no`" in fcontract,
          "interpretation.md: the raster section applies D6 to page_no (no heroRef there)")
    check("LEADS WITH THE FIGURE AND ITS UNIT" in contract
          and "Never offer a total you did not read" in contract,
          "interpretation.md: value-led options and no computed total")
    check(VALID_OPTION in fcontract and INVALID_OPTION in fcontract,
          "interpretation.md: the valid/invalid option pair")
    check('`"set": {"officeArea": "all three office lines combined", "officeAreaVal": null}`'
          in contract,
          "interpretation.md: quotes the refused auto-repair entry so the reason is concrete")
    check("recorded and dropped" in contract and "(D13)" in contract and "(D4)" in contract,
          "interpretation.md: the consequence, citing D13 and D4")
    for needle in ("request EVERY page's sheet and `render` thumbnail in ONE message",
                   "for exactly this batch",
                   "Read `candidates_sheet` once per page rather than opening each"):
        check(needle in contract, f"interpretation.md: f02's pinned needle survives: {needle!r}")

    # (5) the new rules are in the COMMON half, never in a per-deck stub
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "vision").mkdir()
        (work / "vision" / "manifest.json").write_text(
            json.dumps({"decks": [], "fields": [{"name": "park", "type": "string"}]}),
            encoding="utf-8")
        for kind in ("reader-text", "reader-raster"):
            files = PR.write_prompts(work, [(kind, "deck0_ab12cd00_vision", {
                "DECK_NAME": "deck0.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": 5,
                "COUNTRY": "XX", "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
                "OUTPUT_PATH": str(work / "extract" / "deck0_ab12cd00_vision.json")})])
            common = (work / "prompts" / PR.COMMON_DIRNAME / f"{kind}.md").read_text(encoding="utf-8")
            stub = files[0].read_text(encoding="utf-8") if files else ""
            for needle in ("MESSAGE count", "LEADS WITH THE FIGURE AND ITS UNIT",
                           "DO NOT SHARE A HERO"):
                check(needle in common and needle not in stub,
                      f"{kind}: {needle!r} is in the common half, not the per-deck stub")

    # (7) grounded in the code: the shape the contract demands is exactly what lands
    try:
        import clarify as CQ
        recs = [{"park": "Northgate", "unit": "Unit 1", "officeArea": "9,681 sq ft",
                 "__meta": {"source_file": "deck.pdf", "doubts": [
                     {"subject": "office area",
                      "question": "three office lines are printed; which is the office area?",
                      "field": "officeArea",
                      "options": ["24,230 sq ft (all three office lines combined)",
                                  "9,681 sq ft (ground floor office only)"]},
                     {"subject": "office area",
                      "question": "same doubt, no options offered",
                      "field": "officeArea"},
                     {"subject": "office area",
                      "question": "same doubt, no field declared",
                      "options": ["24,230 sq ft", "9,681 sq ft"]},
                 ]}}]
        qs = CQ.agent_doubt_questions(recs)
        by_q = {q["question"]: q for q in qs}
        landed = [q for q in qs if str(q.get("answer_handling", "")).startswith("applied")]
        check(len(landed) == 1 and "which is the office area" in landed[0]["question"],
              "clarify: a doubt with field AND value-led options is the ONLY one stamped applied")
        no_opts = next((q for q in qs if "no options offered" in q["question"]), None)
        no_field = next((q for q in qs if "no field declared" in q["question"]), None)
        check(no_opts is not None
              and not str(no_opts.get("answer_handling", "")).startswith("applied"),
              "clarify: field without options is asked but not landable (answer would be dropped)")
        check(no_field is not None
              and not str(no_field.get("answer_handling", "")).startswith("applied"),
              "clarify: options without a field is asked but not landable")
        check(landed and landed[0].get("options", [""])[0].startswith("24,230 sq ft"),
              "clarify: the value-led option string survives into the question verbatim")
        del by_q
    except Exception as e:  # a mid-edit helpers/clarify.py is another agent's file
        check(False, f"clarify grounding could not run ({e!r}) - is helpers/clarify.py mid-edit?")

    print(f"\n{'PASS' if not fails else 'FAIL'} d1_reader_batch_rule_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
