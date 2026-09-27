#!/usr/bin/env python3
"""clarify_spine_wiring_test.py - run.py's half of the exit-13 fixes 3.2b, 3.2c, 3.18, 3.10b, 3.7b.

THE MEASURED FAILURES (2026-09-26 test run), run.py side. clarify.py now asks better questions
(IA-2's evals pin that); these are the answers LANDING:
  * 3.2b - ten per-floor office doubts; the natural answer "add them" was not an option, so five
    sums were hand-written as repairs. Python now offers the sum; picking it must land the SUM's
    value text (not the option string), name every part in `why`, and cite no page.
  * 3.2c - the same combinable question asked once per card, four about a figure merge already
    showed. One policy answer must fan out per card (attributed to the policy AND the card), a
    card already showing the value gets no no-op repair, a direct per-card answer wins, a
    decline changes nothing; a doubt closed because merge's sum was PREDICTED to show is
    re-opened (once) when the shipped card shows something else.
  * 3.18 - two "one property or two?" answers reprinted a paste-a-repair template every pass,
    one answered exactly as shipped. An as-shipped answer is now silent; another option
    re-reads the deck ONCE (reread.json, the prior output MOVED to _prior_reads, the decision
    in that reader prompt's Run context), is marked done when the new output exists and never
    re-fires; re-answering as shipped first restores the prior output; free text schedules
    nothing; an old title prints one line and no JSON.
  * 3.10b - the not-available question is asked (interactive), disclosed (headless), and the
    conflict path applies the same exclusion filter merge.main does, so conflict ids agree.
  * 3.7b - the arithmetic basis was decided in chat. The gate's `warehouse_is_total` finding is
    now a BLOCKING broker question: derive -> an `ab-` repair (Python's subtraction, no page
    cited), keep/skip -> a figure-guarded waiver the gate honours, changed figures -> the
    question re-fires, and a value-format + arithmetic double failure is ONE questions.json.

Every name is invented. Offline. Run: python evals/clarify_spine_wiring_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import clarify as CQ  # noqa: E402
import normalize as N  # noqa: E402
import prompts_render as PR  # noqa: E402
import run as RUN  # noqa: E402

GATE = HELPERS / "gate_runner.py"
RSRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")
FAILS: list = []

PARTS = ["3,080 sq ft (GF)", "6,155 sq ft (FF)", "1,620 sq ft (SF)"]
COMB = "10,855 sq ft (3 printed lines combined)"
ONE = "one property (Northgate 360 is one building)"
TWO = "two properties (Units A and B are separate options)"
_AUTO = {"SKILL_DIR", "CONTEXT", "FIELD_REGISTRY", "COMMON_POINTER",
         "READER_CONTRACT", "READER_CONTRACT_BODY"}


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _wd(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    _quiet.out = buf.getvalue()
    return r


def _answer(w, mapping):
    (w / CQ.ANSWERS_FILE).write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    CQ.ingest_answers(w)


def _canonical(w, props, meta=None):
    # Written ATOMICALLY (tmp + os.replace), exactly as merge/enrich write canonical.json.
    # `_common.load_canonical` caches on (mtime_ns, size, inode); an in-place rewrite with a
    # same-length value inside one coarse mtime tick kept the inode and served the previous
    # content, which made the recheck section flaky on a fast machine (2026-09-27 release run).
    p = w / "canonical.json"
    tmp = w / "canonical.json.tmp"
    tmp.write_text(json.dumps({"meta": meta or {"client": "x"}, "pois": [], "regions": {},
                               "properties": props}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _prop(pid, park, unit="Unit 1", **f):
    d = {"id": pid, "park": park, "unit": unit, "city": "Eastmere", "developer": "D",
         "country": "ZZ", "status": "Available", "photo": "", "areaUnit": "sq ft",
         "warehouseArea": 150000}
    d.update(f)
    return d


def _repairs(w):
    p = w / "repairs.json"
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else []


def _card(park, parts, src=None, extra=None):
    d = {"subject": "office area", "question": "three office lines, no total; which is it?",
         "field": "officeArea", "options": list(parts), "default": parts[0], "combinable": True}
    r = {"park": park, "unit": "Unit 1", "city": "Eastmere", "areaUnit": "sq ft",
         "warehouseArea": 150000,
         "__meta": {"source_file": src or (park.lower().replace(" ", "_") + ".pdf"),
                    "doubts": [d]}}
    r.update(extra or {})
    return r


def _park_of(q):
    return ((q.get("anchors") or [{}])[0] or {}).get("park")


# --------------------------------------------------------------------------- #
def combined_option_lands() -> None:
    print("1. 3.2b: the broker picks Python's sum -> the sum's value text lands")
    w = _wd("sw_comb_")
    qs = CQ.agent_doubt_questions([_card("Alder Point", PARTS)])
    q = qs[0]
    ck(COMB in (q.get("options") or []), "the synthesised option is on the question")
    CQ.emit(w, CQ.pending(w, qs))
    cn = _canonical(w, [_prop(1, "Alder Point", officeArea="3,080 sq ft", officeAreaVal=3080)])
    _answer(w, {q["id"]: COMB})
    n = _quiet(RUN.agent_doubt_repairs, w, {}, cn)
    reps = _repairs(w)
    e = reps[0] if reps else {}
    ck(n == 1 and e.get("set") == {"officeArea": "10,855 sq ft", "officeAreaVal": 10855},
       f"set {{officeArea: '10,855 sq ft', officeAreaVal: 10855}} ({e.get('set')})")
    why = str(e.get("why") or "")
    ck("Python's sum of the 3 printed lines" in why and all(p in why for p in PARTS)
       and "the source prints no combined figure" in why,
       f"the `why` names Python's sum and every part ({why[:120]}...)")
    ck("source_locator" not in e and e.get("source_file") == "alder_point.pdf",
       "cites the deck FILE and no page locator (the value is composed, not printed)")
    ck(e.get("verified_by") == f"broker (exit-13 answer to {q['id']})",
       f"verified_by names the question ({e.get('verified_by')})")
    ck(e.get("expect") == {"officeArea": "3,080 sq ft"}, "the expect guard is the card's value")
    ck(_quiet(RUN.agent_doubt_repairs, w, {}, cn) == 0 and len(_repairs(w)) == 1,
       "a second pass writes nothing (the id dedupes)")
    # a reader's own option still lands exactly as before
    w2 = _wd("sw_comb2_")
    CQ.emit(w2, CQ.pending(w2, qs))
    cn2 = _canonical(w2, [_prop(1, "Alder Point", officeArea="3,080 sq ft", officeAreaVal=3080)])
    _answer(w2, {q["id"]: PARTS[1]})
    _quiet(RUN.agent_doubt_repairs, w2, {}, cn2)
    e2 = (_repairs(w2) or [{}])[0]
    ck((e2.get("set") or {}).get("officeArea") == "6,155 sq ft"
       and "Python's sum" not in str(e2.get("why")),
       f"a reader option lands as before ({e2.get('set')})")
    # a comma-decimal (locale) sum lands VERBATIM, so normalize reads it back exactly
    lp = ["1.234,5 m²", "2.000,25 m²"]
    lq = CQ.agent_doubt_questions([_card("Linde Hof", lp, extra={"areaUnit": "sq m"})])
    c = (lq[0].get("combinable") if lq else None) or {}
    if c:
        w3 = _wd("sw_comb3_")
        CQ.emit(w3, CQ.pending(w3, lq))
        cn3 = _canonical(w3, [_prop(1, "Linde Hof", officeArea="1.234,5 m²",
                                    officeAreaVal=1234.5, areaUnit="sq m")])
        _answer(w3, {lq[0]["id"]: c["option"]})
        _quiet(RUN.agent_doubt_repairs, w3, {}, cn3)
        e3 = (_repairs(w3) or [{}])[0]
        v3 = (e3.get("set") or {}).get("officeArea")
        ck(v3 == c.get("value_text") and N.normalize_number(v3) == c.get("sum"),
           f"locale sum lands verbatim and reads back as {c.get('sum')} ({v3!r}; "
           f"{_quiet.out.strip()[:160]})")
    else:
        ck(False, "the locale parts synthesise a combined option (clarify)")
    ck(RUN._same_card_value("10,855 sq ft", "10,855 sq ft")
       and not RUN._same_card_value("10,855 sq ft", "10,855 sq m")
       and not RUN._same_card_value("3,080 sq ft", "10,855 sq ft")
       and RUN._same_card_value(10855, 10855.0) and not RUN._same_card_value("6155", "6,155 sq ft"),
       "_same_card_value: equal number AND the same stated unit")


# --------------------------------------------------------------------------- #
A = _card("Alder Point", PARTS)
B = _card("Birch Row", ["2,000 sq ft (GF)", "2,500 sq ft (FF)"])
C_ = _card("Cedar Gate", ["1,100 sq ft (hub 1)", "900 sq ft (hub 2)"])
# merge's own F11 office sum equals Python's sum here: the printed lines are fields too
S = _card("Sorrel Yard", ["4,000 sq ft (GF)", "1,000 sq ft (FF)"],
          extra={"officeGroundFloor": "4,000 sq ft", "officeFirstFloor": "1,000 sq ft"})
PROPS_ABC = [_prop(1, "Alder Point", officeArea="6,155 sq ft", officeAreaVal=6155),
             _prop(2, "Birch Row", officeArea="2,000 sq ft", officeAreaVal=2000),
             _prop(3, "Cedar Gate", officeArea="1,100 sq ft", officeAreaVal=1100)]


def _policy_dir(prefix, recs, props):
    w = _wd(prefix)
    qs = CQ.agent_doubt_questions(recs)
    out, _settled = CQ.group_combinable(w, qs)
    out = CQ.apply_doubt_cap(out)
    pol = [x for x in out if x.get("kind") == "combine_policy"]
    CQ.emit(w, CQ.pending(w, out))
    return w, _canonical(w, props), (pol[0]["id"] if pol else ""), {_park_of(q): q["id"] for q in qs}


def policy_fanout() -> None:
    print("\n2. 3.2c: one policy answer, fanned out per card by the lander")
    w, cn, P, mid = _policy_dir("sw_pc_", [A, B, C_], PROPS_ABC)
    ck(bool(P), "the three cards were grouped into ONE policy question")
    _answer(w, {P: CQ.POLICY_COMBINE})
    n = _quiet(RUN.agent_doubt_repairs, w, {}, cn)
    reps = {r["property"]["id"]: r for r in _repairs(w)}
    ck(n == 3 and (reps.get(1, {}).get("set") or {}).get("officeArea") == "10,855 sq ft"
       and (reps.get(2, {}).get("set") or {}).get("officeArea") == "4,500 sq ft"
       and (reps.get(3, {}).get("set") or {}).get("officeArea") == "2,000 sq ft",
       f"COMBINE: three repairs, each card its own sum ({[r.get('set') for r in reps.values()]})")
    ck(all(reps.get(i, {}).get("verified_by") ==
           f"broker (exit-13 policy answer to {P}, applied to {mid[park]})"
           for i, park in ((1, "Alder Point"), (2, "Birch Row"), (3, "Cedar Gate"))),
       "verified_by names the policy question AND the member")
    ck(all(str(r.get("why") or "").startswith(
        f"broker answered the exit-13 policy question {P} ('{CQ.POLICY_COMBINE}') for every card "
        f"whose officeArea is printed as several lines: ") for r in reps.values()),
       "the `why` opens with the policy answer")
    ck(_quiet(RUN.agent_doubt_repairs, w, {}, cn) == 0, "a second pass writes nothing")

    w, cn, P, mid = _policy_dir("sw_pf_", [A, B, C_], PROPS_ABC)
    _answer(w, {P: CQ.POLICY_FIRST})
    n = _quiet(RUN.agent_doubt_repairs, w, {}, cn)
    reps = _repairs(w)
    ck(n == 1 and len(reps) == 1 and reps[0]["property"]["id"] == 1
       and reps[0]["set"].get("officeArea") == "3,080 sq ft",
       f"FIRST: the first printed line lands where the card showed another; the two cards "
       f"already showing their first line get NO no-op repair ({[r.get('set') for r in reps]})")

    w, cn, P, mid = _policy_dir("sw_pu_", [A, B, C_], PROPS_ABC)
    _answer(w, {P: CQ.POLICY_UNSTATED})
    _quiet(RUN.agent_doubt_repairs, w, {}, cn)
    reps = _repairs(w)
    ck(len(reps) == 3 and all(r.get("unset") == ["officeArea", "officeAreaVal"] and "set" not in r
                              for r in reps),
       f"UNSTATED: every card's officeArea and its twin are CLEARED ({[r.get('unset') for r in reps]})")
    ck(all("the broker chose to leave it unstated" in str(r.get("why")) for r in reps),
       "...with a `why` that says the broker chose it (not 'the source states no value')")

    for ans, label in (("skip", "a declined policy"), (CQ.POLICY_PER_CARD, "'ask me per card'"),
                       ("hmm, not sure about the first one", "an unrecognised answer")):
        w, cn, P, mid = _policy_dir("sw_pd_", [A, B, C_], PROPS_ABC)
        _answer(w, {P: ans})
        ck(_quiet(RUN.agent_doubt_repairs, w, {}, cn) == 0 and not _repairs(w),
           f"{label}: no repairs, every card keeps what shipped")

    w, cn, P, mid = _policy_dir("sw_pw_", [A, B, C_], PROPS_ABC)
    _answer(w, {P: CQ.POLICY_COMBINE, mid["Alder Point"]: PARTS[0]})
    _quiet(RUN.agent_doubt_repairs, w, {}, cn)
    reps = {r["property"]["id"]: r for r in _repairs(w)}
    ck((reps.get(1, {}).get("set") or {}).get("officeArea") == "3,080 sq ft"
       and reps.get(1, {}).get("verified_by") == f"broker (exit-13 answer to {mid['Alder Point']})"
       and (reps.get(2, {}).get("set") or {}).get("officeArea") == "4,500 sq ft",
       "a DIRECT per-card answer wins for that card; the policy covers the rest")

    # a merge-settled card inside the policy: 'combine' writes no no-op repair on it
    w, cn, P, mid = _policy_dir("sw_ps_", [A, S],
                                [_prop(1, "Alder Point", officeArea="6,155 sq ft", officeAreaVal=6155),
                                 _prop(4, "Sorrel Yard", officeArea="5,000 sq ft", officeAreaVal=5000)])
    ck(bool(P), "a settled card joins an unsettled one in ONE policy question")
    _answer(w, {P: CQ.POLICY_COMBINE})
    _quiet(RUN.agent_doubt_repairs, w, {}, cn)
    reps = _repairs(w)
    ck([r["property"]["id"] for r in reps] == [1],
       f"COMBINE lands on the unsettled card only; the card already showing merge's sum gets no "
       f"no-op repair ({[r['property']['id'] for r in reps]})")


def settled_recheck() -> None:
    print("\n3. 3.2c: a doubt merge was PREDICTED to settle is re-opened when the card disagrees")
    w = _wd("sw_rc_")
    qs = CQ.agent_doubt_questions([S])
    out, settled = CQ.group_combinable(w, qs)
    ck(out == [] and len(settled) == 1, "a lone card merge settles is closed without asking")
    CQ.note_suppressed(w, settled, why=CQ.WHY_MERGED)
    sid = settled[0]["id"] if settled else ""
    same = _canonical(w, [_prop(4, "Sorrel Yard", officeArea="5,000 sq ft", officeAreaVal=5000)])
    ck(_quiet(RUN.merge_settled_recheck, w, same) == []
       and sid in (CQ.load_state(w).get("suppressed") or {}),
       "the card shows merge's sum: nothing re-opened, the entry stays")
    diff = _canonical(w, [_prop(4, "Sorrel Yard", officeArea="7,500 sq ft", officeAreaVal=7500)])
    rq = _quiet(RUN.merge_settled_recheck, w, diff)
    ck(len(rq) == 1 and rq[0].get("id") == sid and rq[0].get("field") == "officeArea"
       and sid not in (CQ.load_state(w).get("suppressed") or {}),
       "the card shows another figure: its per-card question is returned, the entry removed")
    pend = CQ.pending(w, rq)
    ck([q["id"] for q in pend] == [sid], "...and it passes clarify.pending (it was never asked)")
    CQ.emit(w, pend)
    ck(sid in CQ.landable(w) and (CQ.landable(w)[sid].get("combinable") or {}).get("option"),
       "emitted, it is landable with the combined option")
    ck(_quiet(RUN.merge_settled_recheck, w, diff) == [], "re-opened at most once")
    wn = _wd("sw_rc0_")
    CQ.note_suppressed(wn, CQ.group_combinable(wn, CQ.agent_doubt_questions([S]))[1],
                       why=CQ.WHY_MERGED)
    ck(_quiet(RUN.merge_settled_recheck, wn, _canonical(wn, [_prop(4, "Sorrel Yard")])) == [],
       "a card with NO value is not re-opened (the lander could not land an answer there)")
    r_err = _quiet(RUN.merge_settled_recheck, wn, wn / "missing.json")
    ck(r_err == [] and "merge-settled recheck skipped" in _quiet.out,
       "an unreadable canonical: [] and one printed line")


def spine_pins_3_2c_3_10b() -> None:
    print("\n4. spine wiring: grouping, cap, settled disclosure, not-available, post-merge door")
    i = RSRC.find("_adg, _ad_settled = _clarify.group_combinable(work, _ad0)")
    j = RSRC.find("_adg = _clarify.apply_doubt_cap(_adg)", i)
    k = RSRC.find("_clarify.note_suppressed(work, _ad_settled, why=_clarify.WHY_MERGED)", j)
    q = RSRC.find("_questions += _ad", k)
    ck(0 < i < j < k < q, "interactive: agent_doubt_questions -> group_combinable -> "
                          "apply_doubt_cap -> note_suppressed(WHY_MERGED) -> the batch")
    ck("_questions += _clarify.not_available_questions(_recs_for_q)" in RSRC,
       "interactive: the not-available questions join the first batch")
    h = RSRC.find("_clarify.note_suppressed(work, _clarify.not_available_questions(_recs_for_q),")
    ck(h > 0 and "why=_clarify.WHY_HEADLESS" in RSRC[h:h + 200],
       "headless: they are disclosed as not asked (WHY_HEADLESS)")
    a = RSRC.find("clusters, _ = _merge.apply_source_authority(")
    b = RSRC.find("_merge.apply_not_available(clusters", a)
    c = RSRC.find("conflicts = _merge.conflict_candidates(", a)
    ck(0 < a < b < c, "conflict path: apply_not_available( after the authority/master-list "
                      "filter and before the conflicts are enumerated (ids match merge.main)")
    x = RSRC.find("_xf_pend = excluded_figure_questions(work, cfg, canonical)")
    y = RSRC.find("merge_settled_recheck(work, canonical)", x)
    z = RSRC.find("_CQ35.emit(work, _xf_pend)", y)
    e = RSRC.find('_exit_round_trip(work, 13, _attempts, "excluded-figure confirmation"', z)
    ck(0 < x < y < z < e, "post-merge: the recheck rides the existing exit-13 door (one emit)")
    ck(RSRC.count("clarify.emit(") <= 1, "still at most ONE `clarify.emit(` site (clarify_test pin)")


# --------------------------------------------------------------------------- #
def _count_rec(src="northgate.pdf"):
    d = {"subject": "Northgate 360", "question": "does this deck describe one property or two?",
         "why_it_matters": "it decides how many cards ship", "options": [ONE, TWO],
         "default": "one property"}
    return {"park": "Northgate 360", "unit": "", "city": "Southwold",
            "__meta": {"source_file": src, "doubts": [d]}}


def _reread_dir(prefix):
    w = _wd(prefix)
    q = CQ.agent_doubt_questions([_count_rec()])[0]
    CQ.emit(w, CQ.pending(w, [q]))
    (w / "vision").mkdir(parents=True, exist_ok=True)
    (w / "vision" / "deck_outputs.json").write_text(json.dumps(
        {"schema_version": 1,
         "outputs": {RUN._vkey("northgate.pdf"): "work/extract/northgate_vision.json"}}),
        encoding="utf-8")
    (w / "extract").mkdir(parents=True, exist_ok=True)
    out = w / "extract" / "northgate_vision.json"
    out.write_text(json.dumps([{"park": "Northgate 360",
                                "__meta": {"source_file": "northgate.pdf"}}]), encoding="utf-8")
    return w, q, out


def reread_machinery() -> None:
    print("\n5. 3.18: an answer asking for a re-read re-reads the deck ONCE, with the decision")
    w, q, out = _reread_dir("sw_rr_")
    k = RUN._vkey("northgate.pdf")
    _answer(w, {q["id"]: ONE})
    decks = _quiet(RUN._plan_rereads, w)
    ck(decks == {} and not RUN._reread_path(w).exists(),
       "an AS-SHIPPED answer schedules nothing and writes no reread.json")
    ck(RUN._apply_reread(w, "northgate.pdf", decks) == (False, None) and out.exists(),
       "...and the deck's output is untouched")
    ck(RUN._recorded_only_doubt_answers(w) == [],
       "...and it is not reported 'recorded only' (no template, every pass)")
    _answer(w, {q["id"]: TWO})
    decks = _quiet(RUN._plan_rereads, w)
    e = dict(decks.get(k) or {})
    key = (CQ.reread_requests(w) or [{}])[0].get("key")
    ck(e.get("qid") == q["id"] and e.get("answer") == TWO and e.get("key") == key
       and e.get("done") is False and not e.get("started"),
       f"another option: reread.json registers the deck with clarify's key ({e})")
    force, ctx = _quiet(RUN._apply_reread, w, "northgate.pdf", decks)
    prior = w / "extract" / "_prior_reads" / f"northgate_vision.{key}.json"
    ck(force and not out.exists() and prior.exists(),
       "the output is MOVED to work/extract/_prior_reads/ (never deleted) and the deck forced")
    ck(not list((w / "extract").glob("*_vision.json")),
       "...so the non-recursive `*_vision.json` glob no longer loads it")
    ent = json.loads(RUN._reread_path(w).read_text(encoding="utf-8"))["decks"][k]
    ck(ent.get("started") is True and ent.get("done") is False
       and ent.get("prior") == f"extract/_prior_reads/northgate_vision.{key}.json"
       and ent.get("output") == "work/extract/northgate_vision.json",
       f"the entry records the move work-dir-relative ({ent.get('prior')})")
    ck(bool(ctx) and q["id"] in ctx and TWO in ctx and "BROKER DECISION for this deck" in ctx
       and f"work/extract/_prior_reads/northgate_vision.{key}.json" in ctx
       and "NOT your input" in ctx,
       "the Run context names the question, the answer and where the prior output went")
    tpl = (PR.TEMPLATE_DIR / "reader-text.md").read_text(encoding="utf-8")
    slots = {s: f"<{s}>" for s in set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", tpl)) if s not in _AUTO}
    slots["CONTEXT"] = RUN._reread_slot(ctx)
    txt = PR.render("reader-text", slots)
    at, split = txt.find("BROKER DECISION for this deck"), txt.find("COMMON-SPLIT")
    ck(at > 0 and q["id"] in txt and (split == -1 or at < split),
       "prompts_render puts the decision in the reader-text PER-DECK Run context")
    decks = _quiet(RUN._plan_rereads, w)
    f2, c2 = _quiet(RUN._apply_reread, w, "northgate.pdf", decks)
    ck(f2 and bool(c2) and len(list((w / "extract" / "_prior_reads").glob("*.json"))) == 1,
       "not dispatched yet: still forced next pass, nothing moved twice")
    out.write_text(json.dumps([{"park": "Northgate 360", "unit": "Unit A"},
                               {"park": "Northgate 360", "unit": "Unit B"}]), encoding="utf-8")
    decks = _quiet(RUN._plan_rereads, w)
    f3, c3 = _quiet(RUN._apply_reread, w, "northgate.pdf", decks)
    ent = json.loads(RUN._reread_path(w).read_text(encoding="utf-8"))["decks"][k]
    ck(not f3 and c3 is None and ent.get("done") is True, "the new output exists: marked DONE")
    decks = _quiet(RUN._plan_rereads, w)
    f4, _ = _quiet(RUN._apply_reread, w, "northgate.pdf", decks)
    ck(not f4 and out.exists() and len(list((w / "extract" / "_prior_reads").glob("*.json"))) == 1,
       "...and it never re-fires")
    import deliver as D
    ck(D._reread_status(w).get(q["id"]) == "done", "deliver reads the same file: 'done'")

    print("   re-answering as shipped BEFORE the re-read runs restores the prior output")
    w, q, out = _reread_dir("sw_rr2_")
    before = out.read_text(encoding="utf-8")
    _answer(w, {q["id"]: TWO})
    _quiet(RUN._apply_reread, w, "northgate.pdf", _quiet(RUN._plan_rereads, w))
    ck(not out.exists(), "moved aside")
    _answer(w, {q["id"]: "as shipped"})
    decks = _quiet(RUN._plan_rereads, w)
    ck(decks == {} and out.exists() and out.read_text(encoding="utf-8") == before
       and not RUN._reread_path(w).exists() and "withdrawn" in _quiet.out,
       "restored byte-for-byte, the entry dropped, one line printed")

    print("   free text schedules nothing; an old or xlsx title never re-reads")
    w, q, out = _reread_dir("sw_rr3_")
    _answer(w, {q["id"]: "it is two, I think"})
    decks = _quiet(RUN._plan_rereads, w)
    ck(decks == {} and out.exists() and "is not one of its options" in _quiet.out
       and q["id"] in _quiet.out, "free text: no re-read, one line asking for an option")
    wx = _wd("sw_rrx_")
    qx = CQ.agent_doubt_questions([_count_rec(src="tracker.xlsx")])[0]
    CQ.emit(wx, CQ.pending(wx, [qx]))
    _answer(wx, {qx["id"]: TWO})
    ck(qx.get("answer_route") == "disclose" and _quiet(RUN._plan_rereads, wx) == {}
       and RUN._recorded_only_doubt_answers(wx) == [],
       "an xlsx count doubt is disclosed: no re-read, no recorded-only template")

    wo = _wd("sw_rro_")
    qid = "q_0ldc0unt01"
    st = CQ.load_state(wo)
    st["asked"] = [qid]
    st["titles"] = {qid: {"kind": "agent_doubt", "subject": "Northgate 360",
                          "question": "does this deck describe one property or two?",
                          "blocking": False, "if_unanswered": "proceeds with: one property",
                          "answer_handling": CQ.ANSWER_RECORDED_NO_FIELD,
                          "to_apply_by_hand": {"reason": "the reader named no canonical field",
                                               "entries": [{"record": "Northgate 360", "entry": {
                                                   "id": "ad-q_0ldc0unt-0",
                                                   "set": {"<ONE canonical field>": "<value>"}}}]}}}
    CQ.save_state(wo, st)
    _answer(wo, {qid: "one property"})
    ck(RUN._recorded_only_doubt_answers(wo) == [],
       "old title answered as its own default: closes as shipped (the Stafford case)")
    _answer(wo, {qid: "two properties, A and B"})
    ro = RUN._recorded_only_doubt_answers(wo)
    gl = RUN._recorded_only_guidance(wo, ro)
    ck(ro == [qid] and len(gl) == 1 and "re-read that deck" in gl[0] and "{" not in gl[0]
       and "<ONE canonical field>" not in gl[0],
       f"old count title with another answer: ONE line, no JSON template ({gl[:1]})")
    ck(_quiet(RUN._plan_rereads, wo) == {}, "...and it is never re-read (no answer_route)")
    st = CQ.load_state(wo)
    st["titles"][qid]["question"] = "is the 24,230 the office or the mezzanine?"
    st["titles"][qid]["subject"] = "office area"
    CQ.save_state(wo, st)
    gl2 = RUN._recorded_only_guidance(wo, [qid])
    ck(len(gl2) == 1 and "{" not in gl2[0] and qid in gl2[0]
       and "write a work/repairs.json entry for that field by hand for the record the "
           "question names" in gl2[0]
       and "`expect` set to the card's current value" in gl2[0],
       "a no-field DISPLAY title gets the same ONE line, which also says what a hand repair "
       "needs - no placeholder-field JSON (the title cannot tell count from display)")
    # the plan-bearing FIELD-declared doubts are untouched (d4 pins their paste-ready entries)
    st = CQ.load_state(wo)
    st["titles"][qid]["answer_handling"] = CQ.ANSWER_RECORDED_NO_OPTIONS.format(field="officeArea")
    st["titles"][qid]["to_apply_by_hand"]["entries"][0]["entry"]["set"] = {"officeArea": "<v>"}
    CQ.save_state(wo, st)
    gl3 = RUN._recorded_only_guidance(wo, [qid])
    ck(len(gl3) == 1 and "RECORDED but NOT applied" in gl3[0] and '"officeArea"' in gl3[0],
       "a field-declared recorded-only doubt still gets its paste-ready entry")

    print("   spine pins")
    lp = RSRC.find("_rereads = _plan_rereads(work)")
    la = RSRC.find("_rr_force, _rr_text = _apply_reread(work, src.name, _rereads)", lp)
    ld = RSRC.find("_done = (_vision_supersedes(work, region, src.name) or has_vision) "
                   "and not _rr_force", la)
    ck(0 < lp < la < ld, "the deck loop plans once, then checks each deck BEFORE it is judged done")
    ck('_slots["CONTEXT"] = _reread_slot(_rrc)' in RSRC,
       "the re-read deck's prompt job carries the CONTEXT slot")
    lr = RSRC.find("for _ln in _reread_lines:")
    ck(0 < lr < RSRC.find("_exit_round_trip(work, 3, _attempts", lr),
       "the exit-3 handoff prints one line per re-read deck")


# --------------------------------------------------------------------------- #
def _ab_canon(w, wa, oa, total, extra=()):
    p = {"id": 14, "park": "Quarry Fields", "unit": "Building 2", "city": "Northport",
         "developer": "D", "country": "ZZ", "status": "Available", "areaUnit": "sq ft",
         "warehouseArea": wa, "officeAreaVal": oa}
    meta = {"client": "T", "statedTotals": {"14": {"value": total, "unit": "sq ft",
                                                   "source_file": "quarry_fields.pdf",
                                                   "locator": "page 3 schedule"}}}
    return _canonical(w, [p, *extra], meta)


def _gate(w, cn, kind="arithmetic"):
    fj = "arithmetic_findings.json" if kind == "arithmetic" else "value_format_findings.json"
    wv = "arithmetic_waivers.json" if kind == "arithmetic" else "value_format_waivers.json"
    p = subprocess.run([sys.executable, str(GATE), kind, str(cn), "--emit-json", str(w / fj),
                        "--waivers", str(w / wv)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _ab_asked(prefix, wa=214000, oa=12500, total=214000):
    w = _wd(prefix)
    cn = _ab_canon(w, wa, oa, total)
    rc, _ = _gate(w, cn)
    res = _quiet(RUN.arithmetic_basis_clarify, w, cn)
    return w, cn, rc, res


def arithmetic_basis_bridge() -> None:
    print("\n6. 3.7b: the printed total read as the warehouse area is a broker question")
    w = _wd("sw_ab0_")
    cn = _ab_canon(w, 214000, 12500, 214000)
    rc, _ = _gate(w, cn)
    n_rep, n_wv, pend = _quiet(RUN.arithmetic_basis_clarify, w, cn, emit=False)
    ck(rc == 1 and n_rep == 0 and n_wv == 0 and len(pend) == 1 and pend[0].get("blocking") is True
       and pend[0].get("options") == [CQ.AB_KEEP, CQ.AB_DERIVE],
       f"the gate blocks and the bridge returns ONE blocking question (rc {rc}, {len(pend)})")
    ck(not (w / "questions.json").exists(), "emit=False writes no questions.json")
    qid = pend[0]["id"] if pend else ""

    w, cn, rc, (n_rep, n_wv, pend) = _ab_asked("sw_abd_")
    ck((w / "questions.json").exists() and len(pend) == 1, "emit=True asks it")
    _answer(w, {qid: CQ.AB_DERIVE})
    n_rep, n_wv, pend = _quiet(RUN.arithmetic_basis_clarify, w, cn)
    reps = _repairs(w)
    e = reps[0] if reps else {}
    ck(n_rep == 1 and not pend and str(e.get("id", "")).startswith("ab-")
       and e.get("set") == {"warehouseArea": 201500} and e.get("expect") == {"warehouseArea": 214000},
       f"DERIVE: one `ab-` repair, warehouseArea = 214,000 - 12,500 = 201,500 ({e.get('set')})")
    ck(e.get("verified_by") == f"broker (exit-13 answer to {qid})" and "source_locator" not in e
       and e.get("source_file") == "quarry_fields.pdf",
       "verified_by names the question; the file is cited, no page (Python composed the value)")
    ck("minus printed office 12,500 = 201,500 sq ft" in str(e.get("why"))
       and "derived by Python" in str(e.get("why")), "the `why` shows the subtraction")
    try:
        import repairs as REP
        vr = REP.validate_entry(e) if hasattr(REP, "validate_entry") else []
    except Exception as ex:
        vr = [str(ex)]
    ck(not vr, f"the repairs stage's own validator accepts it ({vr})")
    fixed = _wd("sw_abd2_")
    rc2, out2 = _gate(fixed, _ab_canon(fixed, 201500, 12500, 214000))
    ck(rc2 == 0, f"...and the gate passes on the derived figure (rc {rc2})")
    ck(_quiet(RUN.arithmetic_basis_clarify, w, cn)[0] == 0 and len(_repairs(w)) == 1,
       "a second pass writes nothing more")

    w, cn, rc, _ = _ab_asked("sw_abk_")
    _answer(w, {qid: CQ.AB_KEEP})
    n_rep, n_wv, pend = _quiet(RUN.arithmetic_basis_clarify, w, cn)
    wv = json.loads((w / "arithmetic_waivers.json").read_text(encoding="utf-8"))
    ck(n_wv == 1 and not pend and not _repairs(w) and wv[0].get("id") == 14
       and wv[0].get("question_id") == qid
       and wv[0].get("expect") == {"warehouseArea": 214000, "officeAreaVal": 12500,
                                   "statedTotal": 214000},
       f"KEEP: a waiver carrying the three figures and the question id ({wv})")
    rc, out = _gate(w, cn)
    ck(rc == 0 and "KEPT BY BROKER DECISION" in out and qid in out,
       f"...which the gate honours with a disclosed note (rc {rc})")
    cn_moved = _ab_canon(w, 215000, 12500, 215000)
    rc, out = _gate(w, cn_moved)
    ck(rc == 1 and "waiver NOT applied" in out, "the figures change: the stale waiver is refused")
    n_rep, n_wv, pend = _quiet(RUN.arithmetic_basis_clarify, w, cn_moved)
    ck(len(pend) == 1 and pend[0]["id"].startswith(qid + "-") and pend[0]["id"] != qid
       and "Asked again" in pend[0].get("question", "") and "214,000" in pend[0].get("question", ""),
       f"...and the question RE-FIRES under a figures-keyed id, naming the old figures "
       f"({pend[0]['id'] if pend else None})")
    _answer(w, {pend[0]["id"]: CQ.AB_KEEP} if pend else {})
    n_rep, n_wv, pend2 = _quiet(RUN.arithmetic_basis_clarify, w, cn_moved)
    rc, out = _gate(w, cn_moved)
    ck(n_wv == 1 and not pend2 and rc == 0, f"re-decided for the new figures: passes (rc {rc})")

    w, cn, rc, _ = _ab_asked("sw_abs_")
    _answer(w, {qid: "skip"})
    n_rep, n_wv, pend = _quiet(RUN.arithmetic_basis_clarify, w, cn)
    wv = json.loads((w / "arithmetic_waivers.json").read_text(encoding="utf-8"))
    ck(n_wv == 1 and not pend and "declined" in wv[0].get("why", "") and _gate(w, cn)[0] == 0,
       "SKIP: an explicit decline keeps the printed total, as a waiver, and the gate passes")

    w, cn, rc, _ = _ab_asked("sw_abj_")
    _answer(w, {qid: "maybe the other figure"})
    n_rep, n_wv, pend = _quiet(RUN.arithmetic_basis_clarify, w, cn)
    ck(n_rep == 0 and n_wv == 0 and len(pend) == 1
       and "matched neither option" in pend[0].get("question", ""),
       "an unrecognised answer is RE-ASKED with the rejection, never guessed")

    w = _wd("sw_abo_")
    cn = _ab_canon(w, 230000, 12500, 214000)
    rc, _ = _gate(w, cn)
    ck(rc == 1 and _quiet(RUN.arithmetic_basis_clarify, w, cn) == (0, 0, []),
       "an 'other' over-derivation asks nothing (the gate's exit-6 remedy stands)")
    ck(_quiet(RUN.arithmetic_basis_clarify, _wd("sw_abn_"), cn) == (0, 0, []),
       "no findings file: (0, 0, []) - today's behaviour")

    print("   a value-format AND arithmetic double failure is ONE questions.json")
    w = _wd("sw_ab2_")
    vf_props = [{"id": i, "park": f"Park {i}", "city": "Corby", "divisibleFrom": "10,000 sq. m"}
                for i in range(1, 4)]
    vf_props.append({"id": 4, "park": "Park 4", "city": "Corby", "divisibleFrom": "5000"})
    cn = _ab_canon(w, 214000, 12500, 214000, extra=vf_props)
    rv, _ = _gate(w, cn, "value-format")
    ra, _ = _gate(w, cn, "arithmetic")
    vf = _quiet(RUN.value_format_clarify, w, cn, emit=False)
    ar = _quiet(RUN.arithmetic_basis_clarify, w, cn, emit=False)
    ck(rv == 1 and ra == 1 and vf[2] and ar[2] and not (w / "questions.json").exists(),
       "both bridges return their questions without emitting")
    CQ.emit(w, list(vf[2]) + list(ar[2]))
    qj = json.loads((w / "questions.json").read_text(encoding="utf-8"))
    ck({q.get("kind") for q in qj.get("questions") or []} == {"value_format", "arithmetic_basis"},
       "one emit, one questions.json holding both kinds")

    print("   spine pins")
    g = RSRC.find('ar_rc = run_gate(gate_runner, "arithmetic", canonical,')
    ck(g > 0 and '"--emit-json", work / "arithmetic_findings.json"' in RSRC[g:g + 200]
       and '"--waivers", work / "arithmetic_waivers.json"' in RSRC[g:g + 250]
       and "g1.append(ar_rc)" in RSRC[g:g + 300],
       "the arithmetic gate runs with --emit-json / --waivers and still counts in g1")
    br = RSRC.find("if vf_rc != 0 or ar_rc != 0:")
    ex = RSRC.find('_exit_round_trip(work, 13, _attempts, "value-format clarification"', br)
    seg = RSRC[br:ex]
    ck(0 < br < ex and "value_format_clarify(work, canonical, emit=False)" in seg
       and "arithmetic_basis_clarify(work, canonical, emit=False)" in seg
       and seg.count(".emit(work, _g13)") == 1,
       "both bridges run with emit=False and their questions leave in ONE emit before exit 13")
    ck('print(_reentry("repair"))' in RSRC[ex:ex + 1800] and "ar_rep or ar_wv" in RSRC[ex:ex + 1800],
       "recorded repairs / waivers get the repair re-entry line")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    combined_option_lands()
    policy_fanout()
    settled_recheck()
    spine_pins_3_2c_3_10b()
    reread_machinery()
    arithmetic_basis_bridge()
    print()
    if FAILS:
        print(f"CLARIFY SPINE WIRING TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("CLARIFY SPINE WIRING TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
