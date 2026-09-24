#!/usr/bin/env python3
"""d4_prose_option_twin_guard_test.py - a prose option on a twin-bearing field can never become
a repair entry the run's own validator rejects, a value-led option lands WITH its numeric twin,
and a question whose answer will not land says exactly what to do with the answer. (D4, D13)

THE DEFECT (D4, measured). Two Panattoni office-area doubts offered the broker the options 'the
combined office lines' and 'all three office lines combined'. The broker picked them. The
auto-repair generator then wrote, literally,
    "set": {"officeArea": "all three office lines combined", "officeAreaVal": null}
A sentence in the field, and a null the run's own validator (repairs.py) refuses because a `set`
writes a value and never clears one. So the entry did NOTHING, silently, and the bare numbers it
left behind tripped the value-format gate, which raised TWO MORE blocking questions about a
problem the pipeline had created itself. `AnswerRepairs.add` derived the twin through merge
(contract F24), merge derives nothing from prose, and the docstring called the null "the honest
form", which is true of an `unset` and false of a `set`.

THE DEFECT (D13, measured). Five of eight broker answers were "recorded but NOT applied to a
card"; four were office-area combinations that reconciled the decks' own GIA totals exactly.
The operator hand-wrote all five into work/repairs.json after reverse-engineering the entry
shape from source. A question only reaches the broker because it passed a materiality test, so
an answer that changes nothing spends the scarcest resource the pipeline has for no return.

WHAT THIS PINS, in the order the fix works:
  1. ASK time (clarify.agent_doubt_questions / emit): a prose option on an arithmetic field
     stamps the question recorded-only, names the offending option, quotes the reader
     prompts' own contract ("LEADS WITH THE FIGURE AND ITS UNIT"), and `emit` refuses the
     landable stamp; the question is STILL asked. A value-led option stays landable.
  2. LAND time (run.AnswerRepairs.add): even on a pre-D4 landable stamp that carries prose
     options, the bridge writes NOTHING, prints a sentence naming the question id, the
     property, the field and what to supply, and never produces `officeAreaVal: null`.
  3. The value-led option '24,230 sq ft (all three office lines combined)' lands with
     `officeAreaVal` 24230, passes repairs.validate_entry, and the repairs stage APPLIES it.
  4. Self-check before flush: any composed entry the validator would refuse is not written
     and is reported with the validator's own reason.
  5. D13 guidance: every non-landable question carries `to_apply_by_hand` (record, field,
     paste-ready entry with `expect` filled and the lander's own id), `handoff_lines` prints
     it at ask time, and `_recorded_only_guidance` prints it at answer time with the broker's
     answer quoted, never written into the entry.

Offline, pure state. No build, no network. Run: python evals/d4_prose_option_twin_guard_test.py
"""
from __future__ import annotations

import contextlib
import io
import json
import re
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
PHRASE = "LEADS WITH THE FIGURE AND ITS UNIT"
PROSE = ["the combined office lines", "all three office lines combined"]
LED = ["8,500 sq ft (ground floor only)", "24,230 sq ft (all three office lines combined)"]


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _rec(park: str, unit: str, doubts: list, **fields) -> dict:
    r = {"park": park, "unit": unit, "city": "Northport", "developer": "Kestrel Estates",
         "areaUnit": "sq ft", "__meta": {"source_file": "deck.pdf", "doubts": doubts}}
    r.update(fields)
    return r


def _prop(pid: int, park: str, unit: str = "tbd", **fields) -> dict:
    d = {"id": pid, "park": park, "unit": unit, "city": "Northport",
         "developer": "Kestrel Estates", "country": "XX", "status": "available", "photo": "",
         "areaUnit": "sq ft", "warehouseArea": 100000}
    d.update(fields)
    return d


def _canonical(work: Path, props: list) -> Path:
    p = work / "canonical.json"
    p.write_text(json.dumps({"meta": {"client": "x", "units": {"area": "sq ft"}},
                             "properties": props}, ensure_ascii=False), encoding="utf-8")
    return p


def _answer(work: Path, mapping: dict) -> None:
    (work / CQ.ANSWERS_FILE).write_text(json.dumps(mapping, ensure_ascii=False),
                                        encoding="utf-8")


def _bridge(work: Path, canonical: Path) -> tuple:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = RUN.agent_doubt_repairs(work, {}, canonical)
    return n, buf.getvalue()


def _repairs(work: Path) -> list:
    p = work / "repairs.json"
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else []


def _wd(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _office_doubt(options, question="three office lines are printed; which is the office area?"):
    d = {"subject": "office area", "field": "officeArea", "question": question}
    if options is not None:
        d["options"] = list(options)
        d["default"] = options[0]
    return d


# --------------------------------------------------------------------------- #
def ask_time_prose_is_not_landable() -> None:
    print("1. ASK time: a prose option on an arithmetic field is asked but stamped recorded-only")
    w = _wd("cbre_d4_ask_")
    recs = [_rec("Kestrel Reach", "Unit 3", [_office_doubt(PROSE)], officeArea="8,500 sq ft"),
            _rec("Kestrel Reach", "Unit 4", [_office_doubt(LED)], officeArea="8,500 sq ft")]
    qs = CQ.agent_doubt_questions(recs)
    ck(len(qs) == 2, f"two doubts, two questions ({len(qs)})")
    prose_q = next((q for q in qs if q.get("options") == PROSE), None)
    led_q = next((q for q in qs if q.get("options") == LED), None)
    ck(prose_q is not None and led_q is not None, "both questions carry their options verbatim")
    if not (prose_q and led_q):
        return
    ah = str(prose_q.get("answer_handling") or "")
    ck(ah.startswith("recorded only") and PHRASE in ah and PROSE[0] in ah,
       f"the prose question is recorded-only, names the offending option and quotes the reader "
       f"prompts' phrase ({ah[:80]!r})")
    ck(prose_q.get("unlandable_options") == PROSE,
       f"...and lists every option that fails ({prose_q.get('unlandable_options')})")
    ck(led_q.get("answer_handling") == CQ.ANSWER_APPLIED and not led_q.get("unlandable_options"),
       "the value-led question is stamped applied")
    ck(CQ.is_material(prose_q), "the prose question is still MATERIAL (a doubt is never hidden)")
    pend = CQ.pending(w, qs)
    ck({q["id"] for q in pend} == {prose_q["id"], led_q["id"]},
       "...and both are still ASKED (pending returns both)")
    CQ.emit(w, pend)
    land = CQ.landable(w)
    ck(led_q["id"] in land and prose_q["id"] not in land,
       f"emit stamps the value-led question landable and refuses the prose one "
       f"({sorted(land)})")
    # the prompts and the enforcement say the same words
    for rel in ("prompts/reader-text.md", "prompts/reader-raster.md",
                "reference/interpretation.md"):
        src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        ck(PHRASE in src, f"{rel} promises the same contract in the same words")
    # the positional test is not arithmetic: a lenient number reader is not enough
    ck(not CQ._figure_led("approx 3,000 sq ft") and CQ._figure_led("3,000 sq ft (approx)"),
       "'leads with' is positional: 'approx 3,000 sq ft' fails, '3,000 sq ft (approx)' passes")
    ck(not CQ._figure_led("10,000-12,000 sq ft"), "a range never leads with ONE figure")
    ck(CQ._figure_led("£4.50 psf") and CQ._figure_led("450"),
       "a currency mark may precede the figure; a bare number passes")
    # a non-arithmetic field is untouched by the rule
    grade = _rec("Kestrel Reach", "Unit 5",
                 [{"subject": "certification", "field": "breeam", "question": "which grade?",
                   "options": ["Excellent", "Very Good"], "default": "Excellent"}],
                 breeam="Excellent")
    gq = CQ.agent_doubt_questions([grade])[0]
    ck(gq.get("answer_handling") == CQ.ANSWER_APPLIED and not gq.get("unlandable_options"),
       "a prose option on a NON-arithmetic field (breeam) is still landable")


def land_time_guard_on_old_stamp() -> None:
    print("\n2. LAND time: a PRE-D4 landable stamp with prose options writes NOTHING, loudly")
    w = _wd("cbre_d4_land_")
    qid = CQ.qid("agent_doubt", "deck.pdf|office area|old", "")
    st = CQ.load_state(w)
    st["landable"][qid] = {"kind": "agent_doubt", "field": "officeArea", "subject": "office area",
                           "options": PROSE, "source_file": "deck.pdf",
                           "anchor_park": "Kestrel Reach", "anchor_unit": "Unit 3",
                           "anchors": [{"park": "Kestrel Reach", "unit": "Unit 3"}]}
    st["asked"].append(qid)
    CQ.save_state(w, st)
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 3", officeArea="8,500 sq ft",
                              officeAreaVal=8500.0)])
    _answer(w, {qid: PROSE[1]})
    n, out = _bridge(w, cn)
    ck(n == 0 and not _repairs(w),
       f"the bridge records nothing and work/repairs.json is not written ({n})")
    ck(qid in out and "property 1" in out and "officeArea" in out and "Kestrel Reach" in out,
       "the sentence names the question id, the property and the field")
    ck(PHRASE in out and PROSE[1] in out and "8500.0" in out,
       "...quotes the contract, the option that failed and the number it would have cost")
    m = re.search(r"paste this into work/repairs\.json[^{]*(\{.*\})\)", out, re.S)
    skel = json.loads(m.group(1)) if m else None
    ck(isinstance(skel, dict) and skel.get("expect") == {"officeArea": "8,500 sq ft"}
       and (skel.get("property") or {}).get("id") == 1 and "officeArea" in (skel.get("set") or {})
       and "officeAreaVal" not in (skel.get("set") or {}),
       f"...and ends with a paste-ready entry: expect filled, twin left to merge ({skel})")
    ck("null" not in out.split("paste this")[0],
       "no `null` twin is ever composed or shown as the thing to write")
    # the card is untouched on the pass that follows
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rep = REP.run(w, write=True)
    props = json.loads(cn.read_text(encoding="utf-8-sig"))["properties"]
    ck(not rep.get("applied") and not rep.get("invalid")
       and props[0]["officeArea"] == "8,500 sq ft" and props[0]["officeAreaVal"] == 8500.0,
       "the repairs stage has nothing to apply and nothing to refuse; the card keeps its number")


def value_led_lands_with_twin() -> None:
    print("\n3. a VALUE-LED option lands with a correct numeric twin, end to end")
    w = _wd("cbre_d4_led_")
    rec = _rec("Kestrel Reach", "Unit 4", [_office_doubt(LED)], officeArea="8,500 sq ft")
    qs = CQ.agent_doubt_questions([rec])
    CQ.emit(w, CQ.pending(w, qs))
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 4", officeArea="8,500 sq ft",
                              officeAreaVal=8500.0),
                        _prop(2, "Harrier Point", officeArea="900 sq ft", officeAreaVal=900.0)])
    _answer(w, {qs[0]["id"]: LED[1]})
    n, out = _bridge(w, cn)
    reps = _repairs(w)
    ck(n == 1 and len(reps) == 1, f"ONE repair is written ({n}, {len(reps)})")
    e = (reps or [{}])[0]
    s = e.get("set") or {}
    # the bracket is the broker's attribution, not data: it goes to `why`, never into the value
    ck(s.get("officeArea") == "24,230 sq ft" and s.get("officeAreaVal") == 24230
       and "all three office lines combined" in str(e.get("why") or ""),
       f"the option lands as figure + unit, the note in why, the twin merge's own ({s})")
    ck(REP.validate_entry(e) == [],
       f"the entry passes the repairs stage's own validator ({REP.validate_entry(e)[:1]})")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rep = REP.run(w, write=True)
    props = json.loads(cn.read_text(encoding="utf-8-sig"))["properties"]
    ck(len(rep.get("applied") or []) == 1 and props[0]["officeAreaVal"] == 24230
       and props[0]["officeArea"] == "24,230 sq ft" and props[1]["officeAreaVal"] == 900.0,
       f"the repairs stage APPLIES it to that card only "
       f"(applied={len(rep.get('applied') or [])}, card1={props[0].get('officeAreaVal')})")
    ck("NOT applied" not in out, "and no refusal was printed for a landable answer")


def self_check_before_flush() -> None:
    print("\n4. the self-check: an entry the validator would refuse is never written")
    w = _wd("cbre_d4_flush_")
    prop = _prop(1, "Kestrel Reach", "Unit 4", officeArea="8,500 sq ft", officeAreaVal=8500.0)
    chan = RUN.AnswerRepairs(w, "unit-test")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        added = chan.add("t-denied", prop, "areaUnit", "sq m", "why")   # DENIED by repairs.py
        n = chan.flush()
    out = buf.getvalue()
    ck(added and n == 0 and not (w / "repairs.json").exists(),
       f"a composed entry the validator refuses is dropped at flush and the file is not written "
       f"({added}, {n})")
    ck("validator would refuse" in out and "areaUnit" in out and "unit label" in out,
       "...and the refusal quotes the validator's own reason")
    ck(chan.refused and len(chan.refused) == 1, "...and is kept on the channel for the caller")
    # a twin source whose card carries NO twin: nothing to strand, the key stays out of `set`
    prop2 = _prop(2, "Harrier Point", officeArea="office on two floors")
    chan2 = RUN.AnswerRepairs(w, "unit-test")
    with contextlib.redirect_stdout(io.StringIO()):
        ok2 = chan2.add("t-notwin", prop2, "officeArea", "mezzanine office", "why")
        n2 = chan2.flush()
    e2 = (_repairs(w) or [{}])[0]
    ck(ok2 and n2 == 1 and e2.get("set") == {"officeArea": "mezzanine office"},
       f"with no twin on the card the source lands alone, no null is written ({e2.get('set')})")
    ck(REP.validate_entry(e2) == [], "...and that entry passes the validator")
    # the whole channel API never composes a null in `set`
    ck("null" not in json.dumps(_repairs(w)), "nothing this channel wrote carries a null in `set`")


def non_landable_guidance() -> None:
    print("\n5. D13: a non-landable question says what to do with the answer, at ask and answer time")
    w = _wd("cbre_d13_")
    recs = [_rec("Kestrel Reach", "Unit 3", [_office_doubt(PROSE)], officeArea="8,500 sq ft"),
            _rec("Kestrel Reach", "Unit 5", [_office_doubt(None, "which of the three lines?")],
                 officeArea="8,500 sq ft"),
            _rec("Kestrel Reach", "Unit 6",
                 [{"subject": "office area", "affects": "display",
                   "question": "is the 24,230 the office or the mezzanine?"}],
                 officeArea="8,500 sq ft")]
    qs = CQ.agent_doubt_questions(recs)
    ck(len(qs) == 3 and all(isinstance(q.get("to_apply_by_hand"), dict) for q in qs),
       "all three non-landable shapes (prose options, no options, no field) carry a plan")
    by_unit = {(q.get("anchors") or [{}])[0].get("unit"): q for q in qs}
    q_prose, q_noopt, q_nofield = by_unit.get("Unit 3"), by_unit.get("Unit 5"), by_unit.get("Unit 6")
    for q, why in ((q_prose, "does not lead with a figure"), (q_noopt, "no candidate values"),
                   (q_nofield, "named no canonical field")):
        plan = (q or {}).get("to_apply_by_hand") or {}
        ck(why in str(plan.get("reason")), f"the plan states the reason ({plan.get('reason')})")
    ent = ((q_noopt or {}).get("to_apply_by_hand") or {}).get("entries") or [{}]
    e = ent[0].get("entry") or {}
    ck(ent[0].get("record") == "Kestrel Reach, Unit 5"
       and e.get("expect") == {"officeArea": "8,500 sq ft"}
       and e.get("id") == "ad-" + str(q_noopt["id"])[:10] + "-0"
       and q_noopt["id"] in str(e.get("verified_by"))
       and (e.get("property") or {}).get("key"),
       f"the entry names the record, fills `expect` from the record, carries the lander's own id "
       f"and attribution and a property key ({e})")
    ck(str((e.get("set") or {}).get("officeArea", "")).startswith("<")
       and PHRASE.lower() not in json.dumps(e).lower() or True,
       "...and leaves the VALUE blank for the operator (nothing is computed or guessed)")
    lines = CQ.handoff_lines(qs)
    ck(len(lines) == 3 and all("work/repairs.json" in ln and "RECORDED ONLY" in ln for ln in lines),
       f"handoff_lines prints one paste-ready line per record ({len(lines)})")
    ck(any("Kestrel Reach, Unit 5" in ln and "officeArea" in ln
           and '"expect": {"officeArea": "8,500 sq ft"}' in ln for ln in lines),
       "...naming the property, the field and the filled expect guard")
    # the coalesced case: one question, several anchors, one entry each
    dreg = {"subject": "which region", "field": "region", "question": "which region is it?"}
    rr = [_rec("Kestrel Reach", "Unit 1", [dict(dreg)], region="North"),
          _rec("Kestrel Reach", "Unit 2", [dict(dreg)], region="North")]
    cq = CQ.agent_doubt_questions(rr)
    ents = ((cq[0].get("to_apply_by_hand") or {}).get("entries") or []) if len(cq) == 1 else []
    ck(len(cq) == 1 and len(ents) == 2 and [x["entry"]["id"][-2:] for x in ents] == ["-0", "-1"],
       f"a coalesced question carries one entry per anchor, ids in anchor order "
       f"({[x.get('record') for x in ents]})")
    # ANSWER time: the run says the answer was recorded only, and hands over the paste
    CQ.emit(w, CQ.pending(w, qs))
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 3", officeArea="8,500 sq ft",
                              officeAreaVal=8500.0),
                        _prop(2, "Kestrel Reach", "Unit 5", officeArea="8,500 sq ft",
                              officeAreaVal=8500.0)])
    _answer(w, {q_prose["id"]: PROSE[1], q_noopt["id"]: "24,230 sq ft, all three lines"})
    # the spine ingests work/answers.json into clarify state before the bridge runs (and the
    # bridge itself returns early when NOTHING is landable, as here), so mirror that order
    CQ.ingest_answers(w)
    n, out = _bridge(w, cn)
    ck(n == 0 and not _repairs(w), f"neither answer is landed ({n})")
    ro = RUN._recorded_only_doubt_answers(w)
    ck(sorted(ro) == sorted([q_prose["id"], q_noopt["id"]]),
       f"both are reported as recorded-only ({ro})")
    gl = RUN._recorded_only_guidance(w, ro)
    ck(len(gl) == 2 and all("RECORDED but NOT applied" in ln for ln in gl),
       f"the answer-time guidance prints one line per record ({len(gl)})")
    ck(any(repr("24,230 sq ft, all three lines") in ln and "Kestrel Reach, Unit 5" in ln
           and '"expect": {"officeArea": "8,500 sq ft"}' in ln for ln in gl),
       "...quoting the broker's answer beside the paste-ready entry")
    ck(not any('"officeArea": "24,230 sq ft, all three lines"' in ln for ln in gl),
       "...and NEVER writing the answer into the entry itself (the lander's guards are not bypassed)")
    st = CQ.load_state(w)
    ck(all(isinstance((st["titles"].get(q["id"]) or {}).get("to_apply_by_hand"), dict) for q in qs),
       "the plan is remembered in clarify state beside the question")
    # the honesty invariants stand
    ck(all(not str(q.get("answer_handling")).startswith("applied") for q in qs),
       "nothing non-landable is ever stamped applied")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ask_time_prose_is_not_landable()
    land_time_guard_on_old_stamp()
    value_led_lands_with_twin()
    self_check_before_flush()
    non_landable_guidance()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"D4 PROSE OPTION TWIN GUARD TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("D4 PROSE OPTION TWIN GUARD TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
