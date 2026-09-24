#!/usr/bin/env python3
"""clarify_answer_lands_test.py - an ANSWERED field-level clarification changes the FIELD.

THE DEFECT. `clarify.agent_doubt_questions` turns a reading agent's recorded doubt into a
precise, field-level broker question ("is the warehouse area 12,500 or 125,000?"),
`clarify.ingest_answers` records the answer durably, and then NOTHING consumed it. The broker
answered, the card still showed the other figure, and the same value had to be supplied a
SECOND time by hand through work/repairs.json. Asking a precise question and discarding the
answer is worse than not asking: it spends the scarcest thing in this pipeline, which is the
broker's attention.

THE PRINCIPLE THAT KEPT IT UNWIRED IS WHAT MAKES WIRING IT SAFE, and it is asserted here
rather than described: an answer NEVER mutates data silently. It arrives as an ATTRIBUTED
correction - one work/repairs.json entry carrying `expect`, `set` (or the clearing verb),
`why` and a `verified_by` that names the answer as its source - applied before the pre-build
gates, with its own Source Ledger row and its own line in the Gaps Report. So the value is
disclosed in the same breath as it is applied, exactly as the two older answer bridges
(excluded-figure, value-format) already do it. Those three now share ONE helper,
`run.AnswerRepairs`, which is also asserted.

WHAT MUST FAIL CLOSED, all of it pinned below, because every one of these is a route to a
correction landing on the wrong card or inventing a value nobody was asked about:
  * a question that names no field                     -> disclosed, nothing written
  * a question this work dir never ASKED               -> nothing written
  * free text that does NOT coerce cleanly into the field -> nothing written; free text that
    DOES ('12,500 sqm' against a numeric field) lands, since F18 (the old selection-only
    guard, B38, ignored six real answers out of six on the measured run)
  * a decline, or SKIP_ALL                             -> nothing written (a recorded decision)
  * a subject matching zero or several shipped cards   -> nothing written
  * a field the merged property does not carry         -> nothing written
  * an option that will not reduce to the field's type -> nothing written
  * an AREA answer in a different area unit from the field's -> nothing written (while one in
    the field's unit lands as figure + unit, its bracketed explanation going to `why`)
  * an unreadable work/repairs.json (the broker's own hand-file) -> refused LOUDLY, never
    consumed-and-dropped

Offline, pure state. No build, no network. Run: python evals/clarify_answer_lands_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import clarify as CQ  # noqa: E402
import repairs as REP  # noqa: E402
import run as RUN  # noqa: E402

FAILS: list = []
RSRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")

AREA_Q = "is the warehouse area 12,500 or 125,000? The page prints both."
GRADE_Q = "the certification cell reads two things - which is the building's?"


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _rec(park: str, src: str, doubt: dict, **fields) -> dict:
    r = {"park": park, "city": "Northport", "developer": "Kestrel Estates",
         "__meta": {"source_file": src, "doubts": [doubt]}}
    r.update(fields)
    return r


def _canonical(work: Path, props: list) -> Path:
    p = work / "canonical.json"
    p.write_text(json.dumps({"meta": {"client": "x"}, "properties": props},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _prop(pid: int, park: str, **fields) -> dict:
    d = {"id": pid, "park": park, "city": "Northport", "developer": "Kestrel Estates",
         "country": "XX", "status": "available", "photo": ""}
    d.update(fields)
    return d


def _ask(work: Path, recs: list) -> list:
    """Produce the doubt questions and EMIT them, which is what makes them landable."""
    qs = CQ.agent_doubt_questions(recs)
    CQ.emit(work, CQ.pending(work, qs))
    return qs


def _answer(work: Path, mapping: dict) -> None:
    (work / CQ.ANSWERS_FILE).write_text(json.dumps(mapping, ensure_ascii=False),
                                        encoding="utf-8")


def _bridge(work: Path, canonical: Path) -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = RUN.agent_doubt_repairs(work, {}, canonical)
    _bridge.out = buf.getvalue()
    return n


def _repairs(work: Path) -> list:
    p = work / "repairs.json"
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else []


def _wd(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    return d


# --------------------------------------------------------------------------- #
def the_stamps() -> None:
    print("1. a doubt is stamped landable only when it DECLARES exactly one known field")
    one = _rec("Kestrel Reach", "a.pdf",
               {"question": AREA_Q, "field": "warehouseArea",
                "options": ["12500", "125000"]}, warehouseArea=125000)
    q = CQ.agent_doubt_questions([one])[0]
    ck(q.get("field") == "warehouseArea", f"the declared field is stamped ({q.get('field')})")
    ck(q.get("source_file") == "a.pdf", "so is the file the doubt was recorded against")
    ck(q.get("options") == ["12500", "125000"], "so are the offered options")
    ck(CQ.is_material(q), "and a doubt about a displayed figure is material, so it is ASKED")

    two = _rec("Kestrel Reach", "a.pdf",
               {"question": AREA_Q, "fields": ["warehouseArea", "plotArea"],
                "options": ["12500", "125000"]}, warehouseArea=125000)
    ck("field" not in CQ.agent_doubt_questions([two])[0],
       "TWO declared fields is ambiguous - not stamped, so it is asked and disclosed only")
    near = _rec("Kestrel Reach", "a.pdf",
                {"question": AREA_Q, "field": "warehouse_area",
                 "options": ["12500", "125000"]}, warehouseArea=125000)
    ck("field" not in CQ.agent_doubt_questions([near])[0],
       "an UNRECOGNISED field name ('warehouse_area') is not stamped - a reading model's "
       "near-miss must never aim a correction")
    free = _rec("Kestrel Reach", "a.pdf",
                {"question": AREA_Q, "options": ["12500", "125000"]}, warehouseArea=125000)
    ck("field" not in CQ.agent_doubt_questions([free])[0],
       "a free-text doubt naming NO field is not stamped - the materiality heuristic may read "
       "prose to decide whether to ASK, but nothing writes a value on a lexicon hit")

    print("\n2. the stamp is remembered durably, and only for a question actually PUT")
    w = _wd("cbre_land_stamp_")
    ck(CQ.landable(w) == {}, "nothing is landable before anything is asked")
    _ask(w, [one])
    land = CQ.landable(w)
    ck(len(land) == 1 and list(land.values())[0]["field"] == "warehouseArea",
       f"emit records the stamp in clarify_state.json ({land})")
    ck(list(land.values())[0]["kind"] == "agent_doubt", "...with its kind, so the bridge scopes")
    # the no-churn rule the `suppressed` key already had, now generalised
    w2 = _wd("cbre_land_churn_")
    (w2 / CQ.STATE_FILE).write_text(json.dumps(
        {"asked": [], "answers": {}, "declined": [], "offers": {}, "titles": {}}, indent=2),
        encoding="utf-8")
    m0 = (w2 / CQ.STATE_FILE).stat().st_mtime_ns
    CQ.ingest_answers(w2)
    CQ.ingest_answers(w2)
    ck((w2 / CQ.STATE_FILE).stat().st_mtime_ns == m0
       and "landable" not in (w2 / CQ.STATE_FILE).read_text(encoding="utf-8-sig"),
       "an EMPTY `landable` is never persisted - clarify_state.json is a merge resume input, "
       "so one gratuitous write re-fires merge -> build -> deliver")


def the_answer_lands() -> None:
    print("\n3. THE POINT: an answered field-level question CHANGES THE FIELD")
    w = _wd("cbre_land_ok_")
    rec = _rec("Kestrel Reach", "a.pdf",
               {"question": AREA_Q, "field": "warehouseArea",
                "options": ["12500", "125000"]}, warehouseArea=125000)
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000, areaUnit="sq m")])
    _answer(w, {qs[0]["id"]: "12500"})
    n = _bridge(w, cn)
    ck(n == 1, f"the bridge records ONE repair ({n})")
    reps = _repairs(w)
    ck(len(reps) == 1, f"work/repairs.json holds it ({len(reps)})")
    e = reps[0] if reps else {}
    ck(e.get("set", {}).get("warehouseArea") == 12500,
       f"...and it SETS the answered value, typed as the field is typed "
       f"({e.get('set')})")
    ck(e.get("expect", {}).get("warehouseArea") == 125000,
       "...guarded by `expect` on the value it is replacing, so it self-cancels if identity "
       "moved under it")
    ck(e.get("property", {}).get("key") and e.get("property", {}).get("id") == 1,
       f"...aimed by property key AND id ({e.get('property')})")
    ck("broker answered" in str(e.get("why", "")) and "warehouseArea" in str(e.get("why", "")),
       f"...with a `why` naming the question it came from ({str(e.get('why'))[:70]})")
    ck(qs[0]["id"] in str(e.get("verified_by", "")),
       f"...and a `verified_by` naming the ANSWER as its source ({e.get('verified_by')})")
    ck(e.get("source_file") == "a.pdf",
       "...citing the file the doubt was recorded against")
    ck("source_locator" not in e,
       "...but NOT a page locator: a broker DECISION among values read from a file does not "
       "establish that the final string sits at one exact spot, and a cited page is evidence "
       "the prov-containment gate checks")

    # NOT A SILENT MUTATION: the repair channel applies it, and it is the channel that
    # discloses. Driven through the real repairs module, end to end.
    out = REP.run(w, write=True)
    applied = out.get("applied") or []
    ck(len(applied) == 1, f"repairs.py APPLIES it ({len(applied)}) {ascii(str(out)[:120])}")
    got = json.loads(cn.read_text(encoding="utf-8-sig"))["properties"][0]
    ck(got.get("warehouseArea") == 12500,
       f"THE FIELD IS CHANGED, in canonical.json ({got.get('warehouseArea')})")
    rows = REP.ledger_rows(out)
    ck(any(str(r.get("field")) == "warehouseArea" for r in rows),
       "...and it writes its own Source Ledger row, so it is disclosed as a correction rather "
       "than laundered into looking like source data")

    print("\n4. idempotent, and it does not re-ask")
    n2 = _bridge(w, cn)
    ck(n2 == 0 and len(_repairs(w)) == 1,
       f"a second pass writes nothing new - the id is derived from the question id ({n2})")
    ck(CQ.pending(w, CQ.agent_doubt_questions([rec])) == [],
       "and the answered question is not pending again")


def the_clearing_verb() -> None:
    print("\n5. 'the source states nothing' uses the CLEARING verb, not a sentinel")
    w = _wd("cbre_land_clear_")
    rec = _rec("Harrier Point", "b.pdf",
               {"question": GRADE_Q, "field": "breeam", "options": ["Very Good", "Excellent"]},
               breeam="Excellent")
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Harrier Point", breeam="Excellent")])
    _answer(w, {qs[0]["id"]: "not stated"})
    ck(CQ.is_not_stated("not stated") and not CQ.is_decline("not stated"),
       "'not stated' is a real ANSWER, not a decline (the two vocabularies are disjoint)")
    ck(not CQ.is_not_stated("none of the halls are let"),
       "...and is matched on the WHOLE answer, so a real sentence is never misread as one")
    n = _bridge(w, cn)
    e = (_repairs(w) or [{}])[0]
    ck(n == 1 and e.get("unset") == ["breeam"],
       f"it becomes an `unset`, which WITHDRAWS the value ({e.get('unset')})")
    ck("set" not in e,
       "...and never a `set` to 'tbd': that would be indistinguishable from a source printing "
       "'tbd', and the ledger row would claim the repair SET a value")
    out = REP.run(w, write=True)
    got = json.loads(cn.read_text(encoding="utf-8-sig"))["properties"][0]
    ck("breeam" not in got and len(out.get("applied") or []) == 1,
       f"the key is REMOVED from the property ({sorted(got)[:6]})")


def fails_closed() -> None:
    print("\n6. every route to a wrong or invented value FAILS CLOSED")
    # (a) an answer that is not one of the offered options
    w = _wd("cbre_land_junk_")
    rec = _rec("Kestrel Reach", "a.pdf",
               {"question": AREA_Q, "field": "warehouseArea",
                "options": ["12500", "125000"]}, warehouseArea=125000)
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "about 40 thousand"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "free text that does NOT coerce cleanly ('about 40 thousand': a hedge and a word the "
       "field cannot take) is disclosed, not landed - the lander never INTERPRETS an answer")
    # (a2) ...but free text that DOES coerce cleanly lands (F18). The pre-F18 rule was
    # selection-only on a provenance argument (B38); the provenance is in the repair's own
    # `verified_by`, and the measured cost of the stricter guard was six of six real answers
    # ignored while the broker was told they would reach the card.
    w = _wd("cbre_land_free_")
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12,500 sqm"})
    e = (_repairs(w) or [{}])[0] if _bridge(w, cn) else {}
    ck(e.get("set") == {"warehouseArea": 12500},
       f"free text that coerces CLEANLY (one number plus a unit word) LANDS in the field's own "
       f"type ({e.get('set')})")
    ck("12,500 sqm" in str(e.get("why")) and "broker" in str(e.get("verified_by")),
       "...attributed to the broker and the question id, quoting the answer as given")
    w = _wd("cbre_land_alt_")
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12500 or 125000"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "an ALTERNATIVE ('12500 or 125000') is not a clean coercion even though normalize_number "
       "would read its first figure - refused, never half-read")
    # (b) a doubt with NO options can be asked, never landed
    w = _wd("cbre_land_noopt_")
    rec_no = _rec("Kestrel Reach", "a.pdf",
                  {"question": AREA_Q, "field": "warehouseArea"}, warehouseArea=125000)
    qs = _ask(w, [rec_no])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12500"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "a doubt that offered no options is disclosed, not landed - deliberate pressure on the "
       "reader to state the candidates it was torn between")
    # (c) a decline
    w = _wd("cbre_land_decline_")
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "skip"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "an explicit decline writes nothing - it is a recorded decision to keep the source's "
       "own value")
    # (d) SKIP_ALL, the headless escape
    w = _wd("cbre_land_skipall_")
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12500"})
    (w / CQ.SKIP_ALL_FILE).write_text("", encoding="utf-8")
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "under clarify.SKIP_ALL every asked question is declined, so nothing lands")
    # (e) an answer to a question this work dir never asked
    w = _wd("cbre_land_unasked_")
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {CQ.qid("agent_doubt", "made|up|question", ""): "12500"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "an id nobody was ever asked writes nothing - the guard `ingest_answers` applies to "
       "answer ids, applied to the landing too")
    # (f) the subject resolves to zero, or to several, shipped cards
    w = _wd("cbre_land_ambig_")
    qs = _ask(w, [rec])
    _answer(w, {qs[0]["id"]: "12500"})
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000),
                        _prop(2, "Kestrel Reach", warehouseArea=125000)])
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "TWO cards share the subject -> nothing lands: a correction on the wrong card is worse "
       "than one that did not land")
    cn = _canonical(w, [_prop(1, "Harrier Point", warehouseArea=125000)])
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "...and a subject matching NO shipped card lands nothing either")
    # (g) the field is not on the merged property
    w = _wd("cbre_land_absent_")
    qs = _ask(w, [rec])
    _answer(w, {qs[0]["id"]: "12500"})
    cn = _canonical(w, [_prop(1, "Kestrel Reach")])
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "the merged property carries no value for the field -> nothing lands: writing a FIRST "
       "value there would be inventing, not correcting")
    # (h) an option that will not reduce to the field's own type
    w = _wd("cbre_land_type_")
    rec_t = _rec("Kestrel Reach", "a.pdf",
                 {"question": AREA_Q, "field": "warehouseArea",
                  "options": ["about half", "125000"]}, warehouseArea=125000)
    qs = _ask(w, [rec_t])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "about half"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "an option that does not reduce to a number, against a NUMERIC field, lands nothing - "
       "a string there would hard-block validate-data")
    ok, v = RUN._answer_as_field_type(125000, "12,500")
    ck(ok and v == 12500,
       f"...while '12,500' reads as 12500 through normalize's one number reader ({v})")
    ok2, _ = RUN._answer_as_field_type(125000, "25,000 - 50,000")
    ck(not ok2, "...and a RANGE is refused rather than half-read")
    ok3, v3 = RUN._answer_as_field_type("Excellent", "Very Good")
    ck(ok3 and v3 == "Very Good", "a string field takes the option verbatim")
    # (i) the broker's hand-file is unreadable
    w = _wd("cbre_land_handfile_")
    qs = _ask(w, [rec])
    _answer(w, {qs[0]["id"]: "12500"})
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    (w / "repairs.json").write_text("[{\"id\": \"mine\",,}", encoding="utf-8")
    n = _bridge(w, cn)
    ck(n == 0, f"an unparseable work/repairs.json applies nothing ({n})")
    ck("NOT a valid JSON list" in _bridge.out and "reader-doubt" in _bridge.out,
       f"...and REFUSES LOUDLY, naming the channel - never consumed-and-dropped "
       f"{ascii(_bridge.out[:80])}")
    ck((w / "repairs.json").read_text(encoding="utf-8-sig") == "[{\"id\": \"mine\",,}",
       "...and the broker's own file is left byte-identical (a rewrite would erase their "
       "hand-written entries)")


def area_answers() -> None:
    print("\n6b. an AREA answer lands as figure + unit; its bracketed explanation goes to `why`")
    office_q = "the office area: is it the ground floor only, or all the office lines?"
    long_ans = ("45,434 sq ft (all office lines combined: ground floor, first floor and the "
                "mezzanine offices)")
    # (a) free text on a TEXT area field, longer than the 80-char free-text limit
    w = _wd("cbre_land_area_long_")
    rec = _rec("Kestrel Reach", "a.pdf",
               {"question": office_q, "field": "officeArea",
                "options": ["40,000 sq ft", "45,434 sq ft"]}, officeArea="40,000 sq ft")
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", officeArea="40,000 sq ft",
                              officeAreaVal=40000, areaUnit="sq ft")])
    _answer(w, {qs[0]["id"]: long_ans})
    n = _bridge(w, cn)
    e = (_repairs(w) or [{}])[0]
    ck(len(long_ans) > 80 and n == 1 and e.get("set", {}).get("officeArea") == "45,434 sq ft",
       f"a {len(long_ans)}-char answer on a text area field lands as '45,434 sq ft' "
       f"({e.get('set')})")
    ck("all office lines combined" in str(e.get("why")),
       f"...and the broker's note is preserved in `why` ({str(e.get('why'))[-70:]})")
    out = REP.run(w, write=True)
    got = json.loads(cn.read_text(encoding="utf-8-sig"))["properties"][0]
    ck(len(out.get("applied") or []) == 1 and got.get("officeArea") == "45,434 sq ft",
       f"...and repairs.py applies it ({got.get('officeArea')}, officeAreaVal "
       f"{got.get('officeAreaVal')})")
    # (b) free text with a trailing bracket on a NUMBER area field
    w = _wd("cbre_land_area_num_")
    rec_n = _rec("Kestrel Reach", "a.pdf",
                 {"question": AREA_Q, "field": "warehouseArea",
                  "options": ["12500", "125000"]}, warehouseArea=125000)
    qs = _ask(w, [rec_n])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000, areaUnit="sq ft")])
    _answer(w, {qs[0]["id"]: "113,690 sq ft (the schedule total, excluding the canopy)"})
    e = (_repairs(w) or [{}])[0] if _bridge(w, cn) else {}
    ck(e.get("set") == {"warehouseArea": 113690},
       f"'113,690 sq ft (...)' on a number field lands as 113690 ({e.get('set')})")
    # (c) a SHORT bracketed answer, free text and offered option alike, keeps no bracket
    for label, opts, ans in (
            ("free text", ["8,000 sq ft", "9,037 sq ft"],
             "9,037 sq ft (all four office lines combined)"),
            ("an offered option", ["8,000 sq ft", "9,037 sq ft (all four office lines combined)"],
             "9,037 sq ft (all four office lines combined)")):
        w = _wd("cbre_land_area_short_")
        rec_s = _rec("Kestrel Reach", "a.pdf",
                     {"question": office_q, "field": "officeArea", "options": opts},
                     officeArea="8,000 sq ft")
        qs = _ask(w, [rec_s])
        cn = _canonical(w, [_prop(1, "Kestrel Reach", officeArea="8,000 sq ft",
                                  areaUnit="sq ft")])
        _answer(w, {qs[0]["id"]: ans})
        e = (_repairs(w) or [{}])[0] if _bridge(w, cn) else {}
        v = e.get("set", {}).get("officeArea")
        ck(v == "9,037 sq ft" and "four office lines" in str(e.get("why")),
           f"{label}: a short bracketed answer lands WITHOUT the bracket in the value ({v}), "
           f"the note in `why`")
    # (d) a DIFFERENT area unit from the field's is refused, never converted
    w = _wd("cbre_land_area_unit_")
    qs = _ask(w, [rec_n])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000, areaUnit="sq ft")])
    _answer(w, {qs[0]["id"]: "10,562 sq m (the GIA)"})
    ck(_bridge(w, cn) == 0 and not _repairs(w) and "never converts a unit" in _bridge.out,
       f"'10,562 sq m' against a sq ft field is refused and disclosed, not converted "
       f"{ascii(_bridge.out[:90])}")


def one_helper() -> None:
    print("\n7. ONE attributed-repair helper, shared by all three answer bridges")
    ck(hasattr(RUN, "AnswerRepairs"), "run.AnswerRepairs exists")
    for fn in ("excluded_figure_questions", "value_format_clarify", "agent_doubt_repairs"):
        i = RSRC.find(f"def {fn}(")
        j = RSRC.find("\ndef ", i + 1)
        body = RSRC[i:j if j != -1 else len(RSRC)]
        ck("AnswerRepairs(" in body, f"{fn} synthesises its repair through AnswerRepairs")
        ck("rep_list.append" not in body and "atomic_write_text(rp_path" not in body,
           f"...and no longer hand-rolls the entry or the write ({fn})")
    ck(RSRC.count("AnswerRepairs(work") == 3,
       f"exactly three channels open it ({RSRC.count('AnswerRepairs(work')})")
    # the bridge is WIRED into the spine, at the point where the repairs stage still runs this
    # pass - a helper nothing calls is the defect this change exists to remove, one level up
    ck("agent_doubt_repairs(work, cfg, canonical)" in RSRC,
       "run.py's spine CALLS the bridge (an uncalled bridge is the same defect again)")
    _i = RSRC.find("agent_doubt_repairs(work, cfg, canonical)")
    ck(_i != -1 and RSRC.find('_stage("repairs")') > _i,
       "...before the repairs stage, so the answer reaches the card on THIS pass rather than "
       "costing another round-trip")
    # the entry shape the two older bridges established, now the helper's contract
    w = _wd("cbre_land_shape_")
    chan = RUN.AnswerRepairs(w, "unit-test")
    prop = _prop(1, "Kestrel Reach", warehouseArea=125000)
    ck(chan.add("t-1", prop, "warehouseArea", 12500, "because reasons",
                verified_by="broker (exit-13 answer)") is True,
       "add() appends an entry")
    ck(chan.add("t-1", prop, "warehouseArea", 999, "dup", ) is False,
       "...and refuses a duplicate id, so a re-run writes it once")
    ck(chan.flush() == 1 and len(_repairs(w)) == 1, "flush() writes once, atomically")
    e = _repairs(w)[0]
    ck(sorted(e) == sorted(["id", "property", "expect", "set", "why", "verified_by"]),
       f"the entry carries exactly expect / set / why / verified_by (+ id, property) "
       f"({sorted(e)})")


def record_count_is_gone() -> None:
    print("\n8. the question kind nothing could act on is DELETED, not left dead")
    ck(not hasattr(CQ, "record_count_questions"),
       "clarify.record_count_questions is gone")
    ck("record_count" not in CQ.KINDS and "record_count" not in CQ.KIND_MATERIALITY,
       "...and so are its KINDS / KIND_MATERIALITY entries")
    ck("record_count_questions(" not in RSRC and "deliberately NOT wired" not in RSRC,
       "...and run.py neither calls it nor carries a comment explaining why it is unwired "
       "(the deleted producer's epitaph is allowed; an invitation to re-wire it is not)")
    ck("_deck_pages" not in RSRC,
       "...and the {deck: page count} map that existed only to feed it is gone too")
    # the capability it wanted is still there, wired, with the trigger that works
    q = CQ.agent_doubt_questions([_rec(
        "Kestrel Reach", "a.pdf",
        {"question": "does this deck describe one property or two? page 4 names another unit"},
        warehouseArea=12500)])[0]
    ck(CQ.materiality(q) == "count" and CQ.is_material(q),
       f"a reader's own 'one property or two?' doubt classifies COUNT - the highest-stakes "
       f"class, never suppressed ({CQ.materiality(q)})")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    the_stamps()
    the_answer_lands()
    the_clearing_verb()
    fails_closed()
    area_answers()
    one_helper()
    record_count_is_gone()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"CLARIFY ANSWER LANDS TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("CLARIFY ANSWER LANDS TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
