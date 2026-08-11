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
is guarding that. Offline, no network."""
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
    ck("union" in sa[0]["if_unanswered"].lower(),
       "unanswered is documented as shipping the union, so it can never wedge a run")
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
       "the hand-off tells the answerer the question will not be repeated")
    ck("Never invent an answer" in payload["instructions"],
       "...and forbids inventing one to clear the list")

    # answer THREE, skip two - the hard case
    (d / Q.ANSWERS_FILE).write_text(json.dumps({
        allq[0]["id"]: "sq ft", allq[1]["id"]: "GBP/sq ft/yr", allq[3]["id"]: "tracker",
    }), encoding="utf-8")
    ans = Q.ingest_answers(d)
    ck(len(ans) == 3, f"the three answers are recorded ({len(ans)})")
    ck(ans[allq[0]["id"]] == "sq ft", "and are readable by id")
    ck(Q.pending(d, allq) == [],
       "converges: NOTHING is pending after one round - not even the two skipped")

    # re-running the producers must not resurrect anything
    ck(Q.pending(d, Q.unit_questions([silent_area, silent_rent]) + rc + sa) == [],
       "converges: re-deriving the same questions asks nothing again")

    # ...and that holds when NOTHING was answered
    d2 = Path(tempfile.mkdtemp(prefix="cbre_clr2_"))
    Q.emit(d2, Q.pending(d2, allq))
    ck(Q.pending(d2, allq) == [],
       "converges: a broker who answers NOTHING is never asked twice")
    ck(Q.ingest_answers(d2) == {}, "no answers recorded, no crash, no guess")

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
    ck("read_text(encoding=\"utf-8\") == body" in (HELPERS / "clarify.py").read_text(
        encoding="utf-8", errors="replace"),
       "save_state is write-if-changed")

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
    ck("merge_inputs.append(_cs)" in RUN_SRC,
       "clarify_state.json is a merge INPUT, so a fresh answer cannot be resume-skipped")

    if fails:
        print(f"\nCLARIFY TEST: FAIL ({len(fails)})")
        return 1
    print("\nCLARIFY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
