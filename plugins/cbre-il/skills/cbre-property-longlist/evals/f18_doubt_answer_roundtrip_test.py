#!/usr/bin/env python3
"""f18_doubt_answer_roundtrip_test.py - a reader doubt shaped the way a REAL reader writes it,
asked, answered, and the answer ACTUALLY APPLIED to the card.

THE DEFECT (F18, measured on a live run). The broker was asked 12 reader-doubt questions and
answered all 12; six answers differed from the printed default and all six were ignored,
repairs_report.json saying "applied": []. Two of the lander's four conjunctive guards could
never pass against a real reader's output:
  * it resolved the card with by_park[norm(stamp["subject"])], but `subject` is the reader's
    free-text TOPIC ("office area", "which region"), never a park name: 8 of 8 landable
    questions matched no park;
  * it required the answer to equal one of the doubt's `options`, but `options` is optional in
    the reader contract and 6 of 8 doubts carried `options: []`, so nothing could match.

WHY IT WAS NEVER CAUGHT. The existing eval (clarify_answer_lands_test.py) gave every fixture a
`subject` that HAPPENED to equal the park name, so the broken anchor resolved by accident. This
eval is the round trip with the fixtures a reader really produces: a prose subject that names
no park, a record whose identity lives in `park`/`unit`, a coalesced multi-record question
(F15) with one answer, and a free-text answer with no `options` match. It asserts the repair is
written, attributed, and then APPLIED by the repairs stage.

PRE-CHANGE RESULT: run against the pre-change helpers (set LONGLIST_HELPERS to another
helpers/ dir) checks 1-4 FAIL, which is the point: this eval reproduces the live defect.

Offline, pure state. No build, no network. Run: python evals/f18_doubt_answer_roundtrip_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = Path(os.environ.get("LONGLIST_HELPERS") or (ROOT / "helpers")).resolve()
sys.path.insert(0, str(HELPERS))
import clarify as CQ  # noqa: E402
import repairs as REP  # noqa: E402
import run as RUN  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _rec(park: str, unit: str, src: str, doubts: list, **fields) -> dict:
    r = {"park": park, "unit": unit, "city": "Northport", "developer": "Kestrel Estates",
         "__meta": {"source_file": src, "doubts": doubts}}
    r.update(fields)
    return r


def _prop(pid: int, park: str, unit: str = "tbd", **fields) -> dict:
    d = {"id": pid, "park": park, "unit": unit, "city": "Northport",
         "developer": "Kestrel Estates", "country": "XX", "status": "available", "photo": ""}
    d.update(fields)
    return d


def _canonical(work: Path, props: list) -> Path:
    p = work / "canonical.json"
    p.write_text(json.dumps({"meta": {"client": "x"}, "properties": props},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _ask(work: Path, recs: list) -> list:
    qs = CQ.agent_doubt_questions(recs)
    CQ.emit(work, CQ.pending(work, qs))
    return qs


def _answer(work: Path, mapping: dict) -> None:
    (work / CQ.ANSWERS_FILE).write_text(json.dumps(mapping, ensure_ascii=False),
                                        encoding="utf-8")


def _bridge(work: Path, canonical: Path) -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return RUN.agent_doubt_repairs(work, {}, canonical)


def _repairs(work: Path) -> list:
    p = work / "repairs.json"
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else []


def _apply(work: Path, canonical: Path) -> tuple:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = REP.run(work, write=True)
    return out, json.loads(canonical.read_text(encoding="utf-8-sig"))["properties"]


def _wd(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# --------------------------------------------------------------------------- #
def prose_subject_lands() -> None:
    print("1. a doubt whose SUBJECT is a topic, not a park, still lands on its own card")
    w = _wd("cbre_rt_prose_")
    rec = _rec("Kestrel Reach", "Unit 3", "deck.pdf",
               [{"subject": "office area", "field": "officeArea",
                 "question": "the page prints 450 and 4500; which is the office?",
                 "options": ["450", "4500"], "default": "4500"}],
               officeArea=4500)
    qs = _ask(w, [rec])
    ck(qs and qs[0].get("subject") == "office area",
       f"the fixture keeps the reader's prose subject ({qs[0].get('subject') if qs else None})")
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 3", officeArea=4500),
                        _prop(2, "Harrier Point", officeArea=900)])
    _answer(w, {qs[0]["id"]: "450"})
    n = _bridge(w, cn)
    reps = _repairs(w)
    ck(n == 1 and len(reps) == 1, f"ONE repair is written ({n}, {len(reps)})")
    e = (reps or [{}])[0]
    _set = e.get("set") or {}
    ck(_set.get("officeArea") == 450 and (e.get("property") or {}).get("id") == 1,
       f"...against the RIGHT card, resolved from the record's park, not from the subject "
       f"({_set}, id={ (e.get('property') or {}).get('id') })")
    # officeArea is the SOURCE of the derived officeAreaVal (merge.DERIVED_TWINS, F24), and
    # repairs.py refuses a set of a source that strands its twin - so the entry carries both
    ck("officeAreaVal" in _set,
       f"...and carries the derived twin in the same entry, or repairs.py would refuse it "
       f"({sorted(_set)})")
    out, props = _apply(w, cn)
    ck(len(out.get("applied") or []) == 1 and props[0].get("officeArea") == 450
       and props[1].get("officeArea") == 900,
       f"...and the repairs stage APPLIES it to that card only "
       f"(applied={len(out.get('applied') or [])}, card1={props[0].get('officeArea')}, "
       f"card2={props[1].get('officeArea')})")


def coalesced_lands_on_each() -> None:
    print("\n2. a COALESCED question (F15: several records, one answer) lands on EVERY anchor")
    w = _wd("cbre_rt_coal_")
    d = {"subject": "which region", "field": "region",
         "question": "the deck names two regions for this park; which is it?",
         "options": ["North", "South"], "default": "North"}
    recs = [_rec("Kestrel Reach", "Unit 1", "deck.pdf", [dict(d)], region="North"),
            _rec("Kestrel Reach", "Unit 2", "deck.pdf", [dict(d)], region="North"),
            _rec("Kestrel Reach", "Unit 3", "deck.pdf", [dict(d)], region="North")]
    qs = _ask(w, recs)
    ck(len(qs) == 1 and len(qs[0].get("anchors") or []) == 3,
       f"three records collapse to ONE question standing for three anchors "
       f"({len(qs)} question(s), {len(qs[0].get('anchors') or []) if qs else 0} anchors)")
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 1", region="North"),
                        _prop(2, "Kestrel Reach", "Unit 2", region="North"),
                        _prop(3, "Kestrel Reach", "Unit 3", region="North"),
                        _prop(4, "Harrier Point", region="North")])
    _answer(w, {qs[0]["id"]: "South"})
    n = _bridge(w, cn)
    reps = _repairs(w)
    ids = sorted((r.get("property") or {}).get("id") for r in reps)
    ck(n == 3 and ids == [1, 2, 3],
       f"three repairs, one per anchor, on the three units of that park ({n}, ids={ids})")
    ck(len({r.get("id") for r in reps}) == 3,
       f"...each with its OWN repair id, so none dedupes another away "
       f"({sorted(r.get('id') for r in reps)})")
    out, props = _apply(w, cn)
    got = [p.get("region") for p in props]
    ck(len(out.get("applied") or []) == 3 and got == ["South", "South", "South", "North"],
       f"...and the repairs stage applies all three, leaving the other park alone ({got})")
    # a re-run derives the same ids and writes nothing new
    n2 = _bridge(w, cn)
    ck(n2 == 0 and len(_repairs(w)) == 3,
       f"a second pass re-derives the same ids and appends nothing ({n2})")


def unit_disambiguates() -> None:
    print("\n3. several cards on ONE park: the anchor's UNIT picks the card; no unit, no landing")
    w = _wd("cbre_rt_unit_")
    d = {"subject": "warehouse area", "field": "warehouseArea",
         "question": "12,500 or 125,000?", "options": ["12500", "125000"], "default": "125000"}
    rec = _rec("Kestrel Reach", "Unit 2", "deck.pdf", [dict(d)], warehouseArea=125000)
    qs = _ask(w, [rec])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 1", warehouseArea=40000),
                        _prop(2, "Kestrel Reach", "Unit 2", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12500"})
    n = _bridge(w, cn)
    e = (_repairs(w) or [{}])[0]
    ck(n == 1 and (e.get("property") or {}).get("id") == 2,
       f"the unit disambiguates: the repair lands on Unit 2 alone "
       f"(id={(e.get('property') or {}).get('id')})")
    # same park, but the record named no unit and two cards share the park -> nothing
    w = _wd("cbre_rt_nounit_")
    rec0 = _rec("Kestrel Reach", "", "deck.pdf", [dict(d)], warehouseArea=125000)
    qs = _ask(w, [rec0])
    cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 1", warehouseArea=125000),
                        _prop(2, "Kestrel Reach", "Unit 2", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12500"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "with no unit to disambiguate, two cards on the park -> nothing lands (fail closed)")
    # a record that named NO park: '' must never be looked up as a key
    w = _wd("cbre_rt_nopark_")
    recn = _rec("", "", "deck.pdf", [dict(d)], warehouseArea=125000)
    qs = _ask(w, [recn])
    cn = _canonical(w, [_prop(1, "", "", warehouseArea=125000)])
    _answer(w, {qs[0]["id"]: "12500"})
    ck(_bridge(w, cn) == 0 and not _repairs(w),
       "an anchor whose park is '' is skipped, never used as a key, even when a card's park "
       "is '' too")


def free_text_lands_when_clean() -> None:
    print("\n4. a FREE-TEXT answer that coerces cleanly lands; one that needs interpreting does not")
    d = {"subject": "office area", "field": "officeArea",
         "question": "450 or 4500?", "options": ["450", "4500"], "default": "4500"}
    for ans, want in (("4,500 sqm", 4500), ("about 4500", None), ("450 or 4500", None),
                      ("is it 450?", None)):
        w = _wd("cbre_rt_free_")
        rec = _rec("Kestrel Reach", "Unit 3", "deck.pdf", [dict(d)], officeArea=450)
        qs = _ask(w, [rec])
        cn = _canonical(w, [_prop(1, "Kestrel Reach", "Unit 3", officeArea=450)])
        _answer(w, {qs[0]["id"]: ans})
        n = _bridge(w, cn)
        got = ((_repairs(w) or [{}])[0].get("set") or {}).get("officeArea")
        if want is None:
            ck(n == 0 and got is None, f"{ans!r} is NOT landed (it would need interpreting)")
        else:
            ck(n == 1 and got == want, f"{ans!r} lands as {want} ({got})")


def stale_stamp_degrades() -> None:
    print("\n5. a PRE-F18 stamp (no anchors, no anchor_park) degrades to the subject match")
    w = _wd("cbre_rt_stale_")
    qid = CQ.qid("agent_doubt", "deck.pdf|Kestrel Reach|old", "")
    st = CQ.load_state(w)
    st.setdefault("landable", {})[qid] = {
        "kind": "agent_doubt", "field": "warehouseArea", "subject": "Kestrel Reach",
        "options": ["12500", "125000"], "source_file": "deck.pdf"}
    if qid not in st["asked"]:
        st["asked"].append(qid)
    CQ.save_state(w, st)
    cn = _canonical(w, [_prop(1, "Kestrel Reach", warehouseArea=125000)])
    _answer(w, {qid: "12500"})
    try:
        n = _bridge(w, cn)
        crashed = False
    except Exception as exc:  # noqa: BLE001
        n, crashed = 0, repr(exc)
    ck(not crashed, f"the old stamp shape does not crash the lander ({crashed})")
    reps = _repairs(w)
    ck(n in (0, 1) and (not reps or reps[0].get("id") == "ad-" + qid[:10]),
       f"...and when it lands it keeps the un-suffixed legacy repair id "
       f"({[r.get('id') for r in reps]})")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"helpers under test: {HELPERS}")
    prose_subject_lands()
    coalesced_lands_on_each()
    unit_disambiguates()
    free_text_lands_when_clean()
    stale_stamp_degrades()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F18 DOUBT ANSWER ROUND-TRIP TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F18 DOUBT ANSWER ROUND-TRIP TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
