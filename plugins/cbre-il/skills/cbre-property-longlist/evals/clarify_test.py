#!/usr/bin/env python3
"""clarify_test.py - ambiguity is asked once, mid-run, and the channel always converges.

The feature is "ask instead of writing a caveat nobody reads". The RISK is that a new asking
channel becomes this skill's fourth unbounded loop - the QA window is capped at one review
plus one improvement round for exactly that reason, and _exit_round_trip exists because
round-trips silently repeated forever. So the convergence property is tested harder than the
feature:

    ASK ONCE, THEN SHIP HONESTLY.

`asked` is recorded when the question is EMITTED, not when an answer arrives, so no sequence
of skipped answers can make the run ask twice. Every assertion below that starts "converges"
is guarding that.

B49 SPLITS THAT CONTRACT IN TWO, and both halves are tested here. For the kinds where the
fall-through default is itself the damage - which source defines the longlist, which unit a
mixed dataset displays, an unlabelled area or rent - silence must NOT settle the question: a
live run shipped 41 cards for a 17-option brief because the authority question fell through to
its documented "union" default with every gate green. Those kinds are `blocking` and come back
until DECIDED. The convergence property is therefore now per-kind:

    non-blocking -> asked once, then ships the disclosed gap   (unchanged)
    blocking     -> re-offered until answered or DECLINED      (bounded by an explicit escape)

The blocking half is still not an unbounded loop, and the assertions below prove it: an
explicit decline and work/clarify.SKIP_ALL both end it in one step, and neither is reachable by
accident. Offline, no network."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import clarify as Q  # noqa: E402

RUN_SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def _rec(park, src, **kw):
    r = {"park": park, "city": "Corby", "country": "GB",
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": "page 1"}}
    r.update(kw)
    return r


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_clr_"))

    # --- producers: only genuine ambiguity becomes a question -------------------
    silent_area = _rec("Gamma", "c.pdf", warehouseArea=12500)
    stated = _rec("Alpha", "a.pdf", warehouseArea=120000, areaUnit="sq ft")
    silent_rent = _rec("Delta", "d.xlsx", warehouseRentVal=7.25)
    qs = Q.unit_questions([silent_area, stated, silent_rent])
    ck(len(qs) == 2, f"one question per genuine ambiguity, none for a stated unit ({len(qs)})")
    ck({q["kind"] for q in qs} == {"area_unit", "rent_unit"}, "both unit kinds are produced")
    ck(all(q["asked_of"] == "broker" for q in qs),
       "a unit nobody wrote down is a BROKER question - no reading can settle it")
    ck(all(q.get("options") and q.get("if_unanswered") for q in qs),
       "each question offers concrete options AND states what happens with no answer")
    ck(not Q.unit_questions([stated]), "a fully-stated record asks nothing")

    # a perception call goes to the AGENT, not the broker
    rc = Q.record_count_questions({"deck.pdf": 8}, {"deck.pdf": [silent_area]})
    ck(len(rc) == 1 and rc[0]["asked_of"] == "agent",
       "an 8-page deck yielding 1 property is an AGENT perception question")
    ck(not Q.record_count_questions({"deck.pdf": 4}, {"deck.pdf": [1, 2, 3]}),
       "a proportionate deck asks nothing (no crying wolf)")

    # SOURCE AUTHORITY (B47). This takes NAMED EXTRAS computed from settled clusters, not raw
    # record counts. The old counts form asked before clustering, so a brochure record that
    # merged into a tracker row still read as an "extra" - the broker was pulled in to
    # arbitrate a discrepancy the next stage often dissolved.
    sa = Q.source_authority_questions({"brochures": ["Gamma Park, Corby"],
                                       "tracker": ["Beta Park, Corby"]})
    ck(len(sa) == 1 and sa[0]["asked_of"] == "broker",
       "a genuine single-source-only option is a BROKER source-authority question")
    ck("Gamma Park, Corby" in sa[0]["question"] and "Beta Park, Corby" in sa[0]["question"],
       "...and it NAMES the options at stake so the broker can actually decide")
    ck(sa[0].get("only_in_brochures") == ["Gamma Park, Corby"]
       and sa[0].get("only_in_tracker") == ["Beta Park, Corby"],
       "...and carries them machine-readably for the orchestrator to relay")
    ck(sa[0].get("blocking") is True,
       "the authority question BLOCKS - its old 'union' default shipped 41 cards for a "
       "17-option brief (B49)")
    ck("nothing is built" in sa[0]["if_unanswered"].lower(),
       "...so 'unanswered' no longer means 'ship the union', it means the run stops")
    ck("skip" in sa[0]["if_unanswered"].lower(),
       "...and the escape (an explicit decline) is stated in the question itself")

    # THE FRAMING IS PART OF THE FIX. The old text opened on two lists of names, which reads as
    # "you are about to lose 14 options" and drove the answer that doubled the deliverable. The
    # totals a broker can check against their own shortlist must come FIRST.
    sa_c = Q.source_authority_questions(
        {"brochures": ["Magna Park South, Lutterworth"], "tracker": ["Stoke"]},
        counts={"tracker_rows": 17, "merged_total": 41},
        by_source=[{"source_file": "10_MPS8.pdf", "records": 15, "roster_options": 1,
                    "where": "Lutterworth"}])
    ck(sa_c[0]["question"].startswith("Your tracker lists 17 option(s), but"),
       "the question LEADS with the arithmetic (17 vs 41), not with two lists of names")
    ck("10_MPS8.pdf: 15 separate units read" in sa_c[0]["question"],
       "...and names the deck the divergence comes from (a park schedule read as 15 options)")
    ck(any("15 separate units" in ln for ln in sa_c[0].get("where_they_come_from") or []),
       "...machine-readably too, for the orchestrator to relay")
    ck([Q.normalise_authority(o) for o in sa_c[0]["options"]]
       == ["tracker", "brochures", "union"],
       "the count-labelled options still normalise onto the three families")
    ck(Q.source_authority_questions({"brochures": ["X"], "tracker": ["Y"]}),
       "the extras-only call still works (counts/by_source are optional)")

    # DATASET DISPLAY UNIT - the mixed sq ft / sq m corpus (B49)
    du = Q.dataset_unit_questions([{"areaUnit": "sq ft"}] * 20 + [{"areaUnit": "sq m"}] * 15)
    ck(len(du) == 1 and du[0]["asked_of"] == "broker" and du[0]["blocking"] is True,
       "a genuinely mixed corpus asks ONE blocking broker question about the display unit")
    ck(du[0]["options"] == ["sq ft", "sq m"], "...offering exactly the two units in play")
    ck(not Q.dataset_unit_questions([{"areaUnit": "sq ft"}] * 30),
       "a unanimous corpus asks NOTHING (no crying wolf)")
    ck(not Q.dataset_unit_questions([{"areaUnit": "sq ft"}] * 30 + [{"areaUnit": "sq m"}]),
       "...and one stray minority record is not a mixed corpus either")
    ck(not Q.dataset_unit_questions([]), "no records, no question")
    ck(not Q.source_authority_questions({}), "no extras asks nothing")
    ck(not Q.source_authority_questions({"brochures": [], "tracker": []}),
       "empty extras ask nothing")
    # a stale caller passing the OLD counts shape must degrade, not crash the clarify batch
    ck(not Q.source_authority_questions({"brochures": 14, "tracker": 12}),
       "the superseded counts shape returns no question rather than raising")

    # the answer must be CONSUMED, not just recorded - the whole point of B47
    ck(Q.settled_authority({}) == Q.AUTHORITY_UNION, "unanswered resolves to the union")
    ck(Q.settled_authority({Q.AUTHORITY_QID: "tracker"}) == "tracker",
       "an answered authority resolves to that family")
    ck(Q.AUTHORITY_QID == Q.qid("source_authority", "property count"),
       "the authority id is stable, not keyed on the counts that prompted it")

    # --- stable ids -------------------------------------------------------------
    id1 = Q.qid("area_unit", "c.pdf", "areaUnit")
    ck(id1 == Q.qid("area_unit", "C.PDF", "areaunit"), "ids are case-stable")
    ck(id1 != Q.qid("rent_unit", "c.pdf", "rentUnit"), "different kinds get different ids")
    moved = _rec("Gamma", "c.pdf", warehouseArea=99999)   # the VALUE changed
    ck(Q.unit_questions([moved])[0]["id"] == Q.unit_questions([silent_area])[0]["id"],
       "the id survives a changed VALUE (or the answer is orphaned and we ask twice)")

    # --- CONVERGENCE ------------------------------------------------------------
    allq = qs + rc + sa            # 2 unit + 1 record_count + 1 source_authority
    ck(len(Q.pending(d, allq)) == 4, f"round 1: every question is pending ({len(allq)})")
    Q.emit(d, Q.pending(d, allq))
    ck((d / Q.QUESTIONS_FILE).exists(), "one batched hand-off file is written")
    payload = json.loads((d / Q.QUESTIONS_FILE).read_text(encoding="utf-8"))
    ck(len(payload["questions"]) == 4, "ALL questions ride ONE round-trip, not one each")
    ck("asked exactly ONCE" in payload["instructions"],
       "the hand-off tells the answerer a non-blocking question will not be repeated")
    ck("the run STOPS here" in payload["instructions"],
       "...and that a blocking one stops the build until it is decided")
    ck("do not just re-run" in payload["instructions"].lower(),
       "...and that re-running is NOT how a blocking question gets cleared")
    ck("NEVER answer a blocking BROKER question from your own context"
       in payload["instructions"],
       "...and forbids the orchestrator answering it itself to clear the exit")
    ck("Never invent an answer" in payload["instructions"],
       "...and forbids inventing one to clear the list")

    # answer ALL FOUR - the clean case
    (d / Q.ANSWERS_FILE).write_text(json.dumps({
        allq[0]["id"]: "sq ft", allq[1]["id"]: "GBP/sq ft/yr", allq[3]["id"]: "tracker",
    }), encoding="utf-8")
    ans = Q.ingest_answers(d)
    ck(len(ans) == 3, f"the three answers are recorded ({len(ans)})")
    ck(ans[allq[0]["id"]] == "sq ft", "and are readable by id")
    ck([q["kind"] for q in Q.pending(d, allq)] == [],
       "converges: every question decided -> nothing pending")

    # re-running the producers must not resurrect anything
    ck(Q.pending(d, Q.unit_questions([silent_area, silent_rent]) + rc + sa) == [],
       "converges: re-deriving the same DECIDED questions asks nothing again")

    # ...and when NOTHING is answered, the two contracts diverge - the whole of B49
    d2 = Path(tempfile.mkdtemp(prefix="cbre_clr2_"))
    Q.emit(d2, Q.pending(d2, allq))
    still = {q["kind"] for q in Q.pending(d2, allq)}
    ck("record_count" not in still,
       "converges: a NON-blocking question is never asked twice (the original bound holds)")
    ck(still == {"area_unit", "rent_unit", "source_authority"},
       f"...but every BLOCKING question comes back until it is decided ({sorted(still)})")
    ck(Q.ingest_answers(d2) == {}, "no answers recorded, no crash, no guess")

    # BOUNDED: an explicit decline ends it in ONE step, and is recorded as a DECISION
    Q.emit(d2, Q.pending(d2, allq))
    (d2 / Q.ANSWERS_FILE).write_text(json.dumps(
        {q["id"]: "skip" for q in allq}), encoding="utf-8")
    Q.ingest_answers(d2)
    ck(Q.pending(d2, allq) == [], "a decline clears every blocking question - never a livelock")
    ck(Q.load_state(d2)["answers"] == {},
       "...and a decline is NOT stored as an answer (apply_answers must never see 'skip')")
    ck(len(Q.declined_ids(d2)) == len(allq), "...it is recorded as an explicit decline")
    ck(Q.is_decline("skip") and Q.is_decline("You decide.") and Q.is_decline("no preference"),
       "the decline vocabulary covers how a broker actually says it")
    ck(not Q.is_decline("skip the brochures") and not Q.is_decline("tracker"),
       "...but a real answer CONTAINING a decline word is never swallowed as one")

    # BOUNDED, second escape: the headless run with nobody to ask
    d2b = Path(tempfile.mkdtemp(prefix="cbre_clr2b_"))
    Q.emit(d2b, Q.pending(d2b, allq))
    ck(Q.pending(d2b, allq), "blocking questions outstanding before the headless escape")
    (d2b / Q.SKIP_ALL_FILE).write_text("", encoding="utf-8")
    ck(Q.pending(d2b, allq) == [], "work/clarify.SKIP_ALL declines every one at once")

    # ESCALATION: repeated offers change the TEXT, so an orchestrator that keeps re-running is
    # told how to end it rather than seeing the identical message forever
    d2c = Path(tempfile.mkdtemp(prefix="cbre_clr2c_"))
    for _ in range(Q.ESCALATE_AFTER + 1):
        Q.emit(d2c, Q.pending(d2c, allq))
    esc = json.loads((d2c / Q.QUESTIONS_FILE).read_text(encoding="utf-8"))["questions"]
    ck(any(q.get("escalated") for q in esc),
       f"a blocking question escalates after {Q.ESCALATE_AFTER} unanswered offers")
    ck(all(q.get("times_asked", 0) >= 1 for q in esc if q.get("blocking")),
       "...and each carries how many times it has been put")

    # a bogus id must never be applied to a real question
    (d2 / Q.ANSWERS_FILE).write_text(json.dumps({"q_deadbeef": "sq m"}), encoding="utf-8")
    ck(Q.ingest_answers(d2) == {}, "an id we never asked is IGNORED, never mis-applied")

    # tolerant reply shapes (an agent will not always write the flat map)
    d3 = Path(tempfile.mkdtemp(prefix="cbre_clr3_"))
    Q.emit(d3, Q.pending(d3, allq))
    (d3 / Q.ANSWERS_FILE).write_text(json.dumps(
        {"answers": {allq[0]["id"]: "sq m"}}), encoding="utf-8")
    ck(Q.ingest_answers(d3).get(allq[0]["id"]) == "sq m", "an enveloped reply is accepted")
    d4 = Path(tempfile.mkdtemp(prefix="cbre_clr4_"))
    Q.emit(d4, Q.pending(d4, allq))
    (d4 / Q.ANSWERS_FILE).write_text(json.dumps(
        [{"id": allq[0]["id"], "answer": "sq m"}]), encoding="utf-8")
    ck(Q.ingest_answers(d4).get(allq[0]["id"]) == "sq m", "a list reply is accepted")
    d5 = Path(tempfile.mkdtemp(prefix="cbre_clr5_"))
    (d5 / Q.ANSWERS_FILE).write_text("not json at all", encoding="utf-8")
    ck(Q.ingest_answers(d5) == {}, "a malformed reply degrades to nothing, never crashes")

    # --- WIRING: exit 13, batched, through the livelock backstop ---------------
    ck("import clarify" in RUN_SRC or "clarify as" in RUN_SRC, "run.py imports clarify")
    ck("_exit_round_trip(work, 13" in RUN_SRC,
       "exit 13 goes through the round-trip backstop, like every other hand-off")
    ck(RUN_SRC.count("clarify.emit(") <= 1,
       "there is at most ONE emit site - questions are batched, never dripped")

    # RESUME SAFETY: clarify_state.json is a MERGE INPUT, so a byte-identical rewrite must not
    # bump its mtime - ingest_answers runs on every pass, and an unconditional write made
    # merge -> build -> deliver all re-fire on a no-change resume.
    d9 = Path(tempfile.mkdtemp(prefix="cbre_clr9_"))
    Q.emit(d9, Q.pending(d9, allq))
    _m = (d9 / Q.STATE_FILE).stat().st_mtime_ns
    Q.ingest_answers(d9)
    Q.ingest_answers(d9)
    ck((d9 / Q.STATE_FILE).stat().st_mtime_ns == _m,
       "an unchanged clarify_state.json keeps its mtime (no resume churn)")
    ck("read_text(encoding=\"utf-8-sig\") == body" in (HELPERS / "clarify.py").read_text(
        encoding="utf-8", errors="replace"),
       "save_state is write-if-changed")  # reads are BOM-tolerant since T1 (utf-8-sig)

    # THE ANSWERS MUST TAKE EFFECT. Ingesting them and never applying them is the exact
    # "correct function, dead wiring" failure this project has shipped three times.
    ck(hasattr(Q, "apply_answers"), "clarify.apply_answers exists")
    recs = [_rec("Gamma", "c.pdf", warehouseArea=12500),
            _rec("Delta", "d.xlsx", warehouseRentVal=7.25)]
    aid = Q.qid("area_unit", "c.pdf", "areaUnit")
    rid = Q.qid("rent_unit", "d.xlsx", "rentUnit")
    n = Q.apply_answers(recs, {aid: "sq ft", rid: "GBP/sq ft/yr"})
    ck(n == 2, f"both answers are applied ({n})")
    ck(recs[0]["areaUnit"] == "sq ft", "the answered AREA unit lands on the record")
    ck(recs[1]["rentUnit"] == "GBP/sq ft/yr", "the answered RENT unit lands on the record")
    ck("CONFIRMED by the broker" in recs[0]["__meta"]["prov"]["areaUnit"],
       "...with provenance saying it was ANSWERED, not read off the source")
    # selection-only: an answer may not invent a value nobody was offered
    r2 = [_rec("Gamma", "c.pdf", warehouseArea=12500)]
    ck(Q.apply_answers(r2, {aid: "hectares"}) == 0 and "areaUnit" not in r2[0],
       "an answer outside the offered options is REFUSED, never applied")
    # an answer must not overwrite a unit the SOURCE actually stated
    r3 = [_rec("Alpha", "c.pdf", warehouseArea=120000, areaUnit="sq m")]
    ck(Q.apply_answers(r3, {aid: "sq ft"}) == 0 and r3[0]["areaUnit"] == "sq m",
       "a unit the source DID state is never overwritten by an answer")

    # WIRING: merge consumes them, before the unit vote, and a new answer re-fires merge
    MSRC = (HELPERS / "merge.py").read_text(encoding="utf-8", errors="replace")
    ck('"--answers"' in MSRC, "merge accepts --answers")
    ck("apply_answers(" in MSRC, "merge APPLIES them")
    # the CALL SITE, not the def - "dominant_units(" first matches its own definition
    i_ans = MSRC.find("apply_answers(")
    i_vote = MSRC.find("area_unit, rent_unit = dominant_units(")
    ck(-1 < i_ans < i_vote,
       "answers are applied BEFORE the dataset unit vote (else the answer cannot count)")
    ck('merge_args += ["--answers", work]' in RUN_SRC, "run.py passes the work dir to merge")
    # B49 wiring: the new questions are produced, fed the counts, and CONSUMED
    ck("dataset_unit_questions(" in RUN_SRC, "run.py asks the dataset-unit question")
    ck("DATASET_UNIT_QID" in MSRC,
       "merge CONSUMES the answered dataset unit (else the answer is dead wiring)")
    i_du = MSRC.find("DATASET_UNIT_QID")
    ck(-1 < i_vote < i_du,
       "...applied AFTER the vote, so an answer OVERRIDES the silent majority")
    ck('counts={"tracker_rows"' in RUN_SRC,
       "run.py feeds the authority question the roster/merged totals (the 17-vs-41 arithmetic)")
    ck("roster_options" in RUN_SRC,
       "...and the per-deck breakdown that names where the divergence comes from")
    ck("is_blocking(" in RUN_SRC, "run.py's hand-off distinguishes blocking questions")
    DSRC = (HELPERS / "deliver.py").read_text(encoding="utf-8", errors="replace")
    ck("Clarifications (what the run asked" in DSRC,
       "an accepted default is DISCLOSED in the Gaps Report - a decision, not a silence")
    ck("merge_inputs.append(_cs)" in RUN_SRC,
       "clarify_state.json is a merge INPUT, so a fresh answer cannot be resume-skipped")

    if fails:
        print(f"\nCLARIFY TEST: FAIL ({len(fails)})")
        return 1
    print("\nCLARIFY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
