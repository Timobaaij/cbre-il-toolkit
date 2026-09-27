#!/usr/bin/env python3
"""count_doubt_route_test.py - count-affecting / no-field doubts: close as shipped, else re-read. (3.18)

THE MEASURED FAILURE (2026-09-26 test run). Two doubts about how many options a deck yields
named no canonical field. Each got a paste-a-repair skeleton with `<ONE canonical field>`
placeholders, reprinted EVERY pass - including one the broker answered exactly as shipped. No
repair can carry such an answer: a repair edits a card, it cannot create or remove one.

THE RULE PINNED HERE (clarify side).
  * `_as_shipped_option` finds the option the reader's own default describes (verbatim, or the
    ONE option whose words include every word of the default); never from the broker's text.
  * a count / no-field doubt with options and a known as-shipped option on a brochure deck gets
    `answer_route: reread` (answer_handling ANSWER_REREAD), no `to_apply_by_hand`, and a handoff
    line with no repairs.json JSON; a count doubt that cannot be re-read gets `disclose`.
  * `emit` records as_shipped / answer_route / source_file / options on the title.
  * `answer_is_as_shipped` closes a question kept as shipped - including an OLD title (no
    as_shipped key) through its "proceeds with:" default.
  * `reread_requests` returns only an answer that is another OFFERED option, not declined;
    free text is `reread_unmatched`, never a re-read.
  * unchanged: a field-declared doubt, a ledger doubt, and a no-field display doubt with no
    options keep today's handling.
The reread.json machinery, the prior-output move and the CONTEXT render are run.py's (IA-7b).

Every name is invented. Offline. Run: python evals/count_doubt_route_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402

FAILS: list = []

ONE = "one property (Northgate 360 is one building)"
TWO = "two properties (Units A and B are separate options)"


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _wd(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def _count_rec(src="northgate.pdf", options=(ONE, TWO), default="one property", **over):
    d = {"subject": "Northgate 360",
         "question": "does this deck describe one property or two?",
         "why_it_matters": "it decides how many cards ship"}
    if options is not None:
        d["options"] = list(options)
    if default is not None:
        d["default"] = default
    d.update(over)
    return {"park": "Northgate 360", "unit": "", "city": "Southwold",
            "__meta": {"source_file": src, "doubts": [d]}}


def _answer(w, mapping):
    (w / "answers.json").write_text(json.dumps(mapping), encoding="utf-8")
    CQ.ingest_answers(w)


def as_shipped_matcher() -> None:
    print("1. _as_shipped_option (reader-authored strings only)")
    ck(CQ._as_shipped_option([ONE, TWO], ONE) == ONE, "verbatim default")
    ck(CQ._as_shipped_option([ONE, TWO], "One Property.") == ONE, "normalised equality")
    ck(CQ._as_shipped_option([ONE, TWO], "one property") == ONE, "word-subset of exactly one option")
    ck(CQ._as_shipped_option(["one hall (A)", "one hall (B)"], "one hall") == "",
       "word-subset of two options is ambiguous -> ''")
    ck(CQ._as_shipped_option([ONE, TWO], "") == "", "no default -> ''")
    ck(CQ._as_shipped_option([], "keep one card") == "keep one card", "no options -> the default")


def reread_route() -> None:
    print("2. a count doubt on a brochure deck -> the re-read route")
    q = CQ.agent_doubt_questions([_count_rec()])[0]
    ck(CQ.materiality(q) == "count", "classified count")
    ck(q.get("answer_route") == "reread", f"answer_route reread ({q.get('answer_route')})")
    ck(q.get("as_shipped") == ONE, f"as_shipped resolved from the word-subset default ({q.get('as_shipped')!r})")
    ck(q.get("source_file") == "northgate.pdf", "source_file carried")
    ah = q.get("answer_handling", "")
    ck(ah.startswith("recorded, then applied by RE-READING the deck")
       and "is about how many options this deck yields" in ah and ONE in ah and "'northgate.pdf'" in ah,
       "answer_handling = ANSWER_REREAD with the why, the as-shipped option and the deck")
    ck(not ah.startswith("recorded only"), "does not carry the recorded-only prefix")
    ck("to_apply_by_hand" not in q, "no paste-a-repair skeleton")
    lines = CQ.handoff_lines([q])
    ck(len(lines) == 1 and "RE-READS 'northgate.pdf' once" in lines[0]
       and "No work/repairs.json entry applies" in lines[0] and "{" not in lines[0],
       f"one handoff line, no JSON template ({lines})")
    pq = CQ.agent_doubt_questions([_count_rec(src="northgate.pptx")])[0]
    ck(pq.get("answer_route") == "reread", "a .pptx deck takes the same route")
    nf = CQ.agent_doubt_questions([{"park": "Kite Park", "unit": "", "__meta": {
        "source_file": "kite.pdf", "doubts": [{
            "subject": "hero photo", "question": "which photo shows the building itself?",
            "options": ["the aerial on page 2", "the render on page 5"],
            "default": "the aerial on page 2"}]}}])[0]
    ck(nf.get("answer_route") == "reread" and "names no canonical field" in nf.get("answer_handling", ""),
       "a no-field DISPLAY doubt with options is routed too (why: names no canonical field)")


def emit_titles_and_answers() -> None:
    print("3. emit titles, as-shipped closure, reread_requests")
    w = _wd("cdr_emit_")
    q = CQ.agent_doubt_questions([_count_rec()])[0]
    CQ.emit(w, CQ.pending(w, [q]))
    t = CQ.load_state(w)["titles"][q["id"]]
    ck(t.get("answer_route") == "reread" and t.get("source_file") == "northgate.pdf"
       and t.get("options") == [ONE, TWO] and t.get("as_shipped") == ONE,
       "title carries answer_route, source_file, options, as_shipped")
    ck("to_apply_by_hand" not in t and q["id"] not in CQ.landable(w), "no hand plan, not landable")
    for raw in (ONE, "as is", "keep as shipped", "one property"):
        _answer(w, {q["id"]: raw})
        ck(CQ.answer_is_as_shipped(t, raw) and CQ.reread_requests(w) == [],
           f"answer {raw!r}: as shipped, no re-read")
    _answer(w, {q["id"]: TWO})
    rr = CQ.reread_requests(w)
    ck(len(rr) == 1 and rr[0]["qid"] == q["id"] and rr[0]["answer"] == TWO
       and rr[0]["source_file"] == "northgate.pdf" and len(rr[0]["key"]) == 10
       and "one property or two" in rr[0]["question"],
       f"another option -> one re-read request ({rr})")
    k1 = rr[0]["key"] if rr else ""
    _answer(w, {q["id"]: TWO.upper()})
    rr2 = CQ.reread_requests(w)
    ck(rr2 and rr2[0]["key"] == k1 and rr2[0]["answer"] == TWO,
       "the same option in another case: same key, the reader's own string")
    _answer(w, {q["id"]: "it is two, I think"})
    ck(CQ.reread_requests(w) == [] and [u["qid"] for u in CQ.reread_unmatched(w)] == [q["id"]],
       "free text: no re-read, listed as unmatched")
    _answer(w, {q["id"]: "skip"})
    ck(CQ.reread_requests(w) == [] and CQ.reread_unmatched(w) == [], "a decline: nothing")


def old_state_compat() -> None:
    print("4. an OLD title (asked before this round) never re-reads, and closes as shipped")
    w = _wd("cdr_old_")
    qid = "q_0ldc0unt01"
    st = CQ.load_state(w)
    st["asked"] = [qid]
    st["titles"] = {qid: {"kind": "agent_doubt", "subject": "Northgate 360",
                          "question": "does this deck describe one property or two?",
                          "blocking": False, "if_unanswered": "proceeds with: one property",
                          "answer_handling": CQ.ANSWER_RECORDED_NO_FIELD}}
    CQ.save_state(w, st)
    _answer(w, {qid: "one property"})
    t = CQ.load_state(w)["titles"][qid]
    ck(CQ.answer_is_as_shipped(t, "one property"), "the old default closes via 'proceeds with:'")
    ck(not CQ.answer_is_as_shipped(t, "two properties"), "...another answer does not")
    ck(CQ.reread_requests(w) == [], "no answer_route on the title -> never a re-read")
    ck(not CQ.answer_is_as_shipped({}, "") and not CQ.answer_is_as_shipped(None, "x"),
       "empty / missing title never counts as shipped")


def disclose_and_unchanged() -> None:
    print("5. 'disclose' where a re-read is impossible; everything else unchanged")
    x = CQ.agent_doubt_questions([_count_rec(src="tracker.xlsx")])[0]
    ck(x.get("answer_route") == "disclose" and x.get("answer_handling") == CQ.ANSWER_RECORDED_COUNT,
       "an xlsx-sourced count doubt -> disclose / ANSWER_RECORDED_COUNT")
    ck("to_apply_by_hand" not in x, "...with no skeleton")
    hl = CQ.handoff_lines([x])
    ck(len(hl) == 1 and "RECORDED and disclosed" in hl[0] and "{" not in hl[0], f"one disclose line ({hl})")
    nd = CQ.agent_doubt_questions([_count_rec(default=None)])[0]
    ck(nd.get("answer_route") == "disclose", "a deck count doubt with no default: as-shipped unknown -> disclose")
    no = CQ.agent_doubt_questions([{"park": "Kite Park", "unit": "Unit 6", "__meta": {
        "source_file": "kite.pdf", "doubts": [{
            "subject": "office area", "question": "is the office area the figure on page 3?"}]}}])[0]
    ck("answer_route" not in no and isinstance(no.get("to_apply_by_hand"), dict)
       and no.get("answer_handling") == CQ.ANSWER_RECORDED_NO_FIELD,
       "a no-field display doubt with no options keeps today's skeleton (d4 Unit 6 shape)")
    fd = CQ.agent_doubt_questions([{"park": "Kite Park", "unit": "Unit 2", "__meta": {
        "source_file": "kite.pdf", "doubts": [{
            "subject": "clear height", "question": "10 m or 12 m?", "field": "clearHeight",
            "options": ["10 m", "12 m"], "default": "10 m"}]}}])[0]
    ck("answer_route" not in fd and fd.get("answer_handling") == CQ.ANSWER_APPLIED,
       "a field-declared doubt keeps the applied path")
    lg = CQ.agent_doubt_questions([{"park": "Kite Park", "unit": "", "__meta": {
        "source_file": "kite.pdf", "doubts": [{
            "subject": "cover", "question": "the cover tint looks unusual", "materiality": "ledger",
            "options": ["blue", "green"], "default": "blue"}]}}])[0]
    ck("answer_route" not in lg, "a ledger doubt is never routed")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    as_shipped_matcher()
    reread_route()
    emit_titles_and_answers()
    old_state_compat()
    disclose_and_unchanged()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"COUNT DOUBT ROUTE TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("COUNT DOUBT ROUTE TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
