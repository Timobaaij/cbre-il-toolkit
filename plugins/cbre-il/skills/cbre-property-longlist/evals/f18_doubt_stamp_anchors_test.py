#!/usr/bin/env python3
"""f18_doubt_stamp_anchors_test.py - a doubt's answer can FIND its card, or says it cannot. (F18)

THE MEASURED FAILURE. On the live run the broker was asked twelve questions and answered all
twelve; six answers differed from the printed default and all six were ignored
(`repairs_report.json` said `"applied": []`). Two of the lander's four guards could never pass:
  1. THE ANCHOR. The lander resolved the card with `by_park[norm(stamp["subject"])]`, but
     `subject` is the human-readable TOPIC the interpretation contract asks the reader for
     ("office area", "property region", "which office area belongs to this unit"). Eight of
     eight landable subjects matched no park. One field carried two incompatible meanings.
  2. THE SELECTION. An answer had to match one of the doubt's `options`, but `options` is
     optional in the reader contract and six of eight landable doubts carried `options: []`,
     so the match was always None and no typed answer could ever land.

The clarify half, pinned here (the lander that READS these keys is run.py's, another owner's):
  * the `landable` stamp carries the raising RECORD'S own identity, `anchor_park` and
    `anchor_unit`, verbatim, plus `anchors` (the list form); `subject` is left exactly as
    written and is never repurposed;
  * a doubt that declares a `field` but offers no `options` is still ASKED (dropping it would
    hide a doubt the reader recorded) but is NOT stamped landable, and the question says so in
    `answer_handling`, so nobody is asked as if the answer will reach the card when it cannot;
  * an old work dir's stamp (no anchor keys) is returned unchanged, so a lander falling back
    to `subject` degrades rather than crashes.

The doubts below are shaped the way a real reader writes them: prose subject and all. Every
name is invented. Offline, pure state. Run: python evals/f18_doubt_stamp_anchors_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import clarify as CQ  # noqa: E402
import match as M  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _rec(park, unit, src, doubt, **fields):
    r = {"park": park, "city": "Northport", "developer": "Kestrel Estates",
         "__meta": {"source_file": src, "doubts": [doubt]}}
    if unit is not None:
        r["unit"] = unit
    r.update(fields)
    return r


def _wd(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


# A doubt AS A READER WRITES IT: the subject is a topic, not a park name.
OFFICE_DOUBT = {"subject": "office area",
                "question": "the page prints 450 and 4,500 for the office; which is this unit's?",
                "field": "officeArea", "options": ["450", "4500"], "default": "4500",
                "why_it_matters": "the smaller figure is a single floor, the larger the whole block"}


def the_anchor_is_the_record() -> None:
    print("1. the stamp carries the RECORD'S identity; the subject stays the reader's topic")
    rec = _rec("Kestrel Reach", "Unit 3", "deck.pdf", OFFICE_DOUBT, officeArea=4500)
    q = CQ.agent_doubt_questions([rec])[0]
    ck(q.get("subject") == "office area",
       f"the subject is left exactly as the reader wrote it ({q.get('subject')!r})")
    ck(q.get("anchor_park") == "Kestrel Reach" and q.get("anchor_unit") == "Unit 3",
       f"the question carries the record's own park and unit, verbatim "
       f"({q.get('anchor_park')!r}, {q.get('anchor_unit')!r})")
    ck(q.get("anchors") == [{"park": "Kestrel Reach", "unit": "Unit 3"}],
       f"...and the list form, one entry for the one record ({q.get('anchors')})")
    ck(q.get("field") == "officeArea" and q.get("options") == ["450", "4500"],
       "the field and the offered options are stamped as before")
    ck(q.get("answer_handling") == CQ.ANSWER_APPLIED,
       "with options present the question says the answer will be APPLIED")
    ck("[record: Kestrel Reach, Unit 3]" in q.get("question", ""),
       f"the broker-facing text names the record, because a prose subject alone does not "
       f"({q.get('question')!r})")

    w = _wd("cbre_f18_stamp_")
    CQ.emit(w, CQ.pending(w, [q]))
    land = CQ.landable(w)
    ck(len(land) == 1, f"the question is stamped landable ({len(land)})")
    stamp = list(land.values())[0] if land else {}
    ck(stamp.get("anchor_park") == "Kestrel Reach" and stamp.get("anchor_unit") == "Unit 3",
       f"THE STAMP carries anchor_park and anchor_unit ({stamp.get('anchor_park')!r}, "
       f"{stamp.get('anchor_unit')!r})")
    ck(stamp.get("anchors") == [{"park": "Kestrel Reach", "unit": "Unit 3"}],
       f"...and `anchors`, equal to the scalar pair for a single record ({stamp.get('anchors')})")
    ck(stamp.get("subject") == "office area", "...and the subject, unchanged")
    for k in ("kind", "field", "subject", "options", "source_file"):
        ck(k in stamp, f"...and still carries the pre-change key `{k}`")

    # THE DEFECT, REPRODUCED AGAINST THE LANDER'S OWN LOOKUP: the merged dataset is keyed by
    # park, the subject is a topic, so the old anchor finds nothing and the new one finds the card.
    props = [{"id": 1, "park": "Kestrel Reach", "unit": "Unit 3", "officeArea": 4500}]
    by_park = {}
    for p in props:
        by_park.setdefault(M.norm(p.get("park")), []).append(p)
    ck(M.norm(stamp.get("subject")) not in by_park,
       "the OLD anchor (norm(subject) against park names) matches NOTHING for a real reader's "
       "subject - the measured eight-of-eight failure")
    ck(len(by_park.get(M.norm(stamp.get("anchor_park")), [])) == 1,
       "the NEW anchor (norm(anchor_park)) resolves the one card")


def no_options_is_asked_not_promised() -> None:
    print("\n2. a field with NO options is still ASKED, never stamped landable, and says so")
    bare = dict(OFFICE_DOUBT)
    bare.pop("options")
    rec = _rec("Kestrel Reach", "Unit 3", "deck.pdf", bare, officeArea=4500)
    qs = CQ.agent_doubt_questions([rec])
    ck(len(qs) == 1, "the doubt is not dropped")
    q = qs[0]
    ck(CQ.is_material(q), "...and a doubt about a displayed field is still material, so it is asked")
    ck(q.get("field") == "officeArea",
       "the declared field stays on the question (it is true, and the orchestrator can see it)")
    ah = str(q.get("answer_handling") or "")
    ck(ah.startswith("recorded only") and "officeArea" in ah and "options" in ah,
       f"answer_handling says RECORDED ONLY and names the missing options ({ah[:90]!r})")
    ck("SHOULD HAVE STATED THE CANDIDATES" in ah,
       "...and tells the reader what it should have supplied - the pressure lands on the reader, "
       "not the broker")
    w = _wd("cbre_f18_noopt_")
    asked = CQ.pending(w, [q])
    ck([x["id"] for x in asked] == [q["id"]], "pending() still puts it to the broker")
    CQ.emit(w, asked)
    st = CQ.load_state(w)
    ck(q["id"] in st.get("asked", []), "emit marks it ASKED like any other question")
    ck(CQ.landable(w) == {},
       "...but writes NO landable stamp: a stamp without options is a promise the lander "
       "cannot keep")
    ck(str((st.get("titles") or {}).get(q["id"], {}).get("answer_handling", "")).startswith(
        "recorded only"),
       "the durable title carries the same signal, so the Gaps Report can say the answer was "
       "recorded and not applied")

    print("\n3. the refusal lives in emit itself, so a hand-built question cannot bypass it")
    w = _wd("cbre_f18_hand_")
    CQ.emit(w, [{"id": "q_hand_noopt", "kind": "agent_doubt", "field": "officeArea",
                 "subject": "office area", "question": "which?", "blocking": False}])
    ck(CQ.landable(w) == {}, "field without options -> no stamp, whoever built the question")
    CQ.emit(w, [{"id": "q_hand_empty", "kind": "agent_doubt", "field": "officeArea",
                 "options": [], "subject": "office area", "question": "which?",
                 "blocking": False}])
    ck(CQ.landable(w) == {}, "`options: []` (the measured shape) is the same as none")
    src = (HELPERS / "clarify.py").read_text(encoding="utf-8", errors="replace")
    ck('if q.get("field") and q.get("options"):' in src,
       "the guard is the conjunction, pinned in source")


def degrades_never_crashes() -> None:
    print("\n4. shapes the lander must degrade on, not crash on")
    # (a) a hand-built question with field and options but no anchors: stamp without anchor
    # keys, which is the OLD shape, so the lander's subject fallback stays reachable
    w = _wd("cbre_f18_noanchor_")
    CQ.emit(w, [{"id": "q_old_shape", "kind": "agent_doubt", "field": "officeArea",
                 "options": ["450", "4500"], "subject": "Kestrel Reach", "question": "which?",
                 "blocking": False}])
    s = CQ.landable(w).get("q_old_shape") or {}
    ck(s.get("field") == "officeArea" and "anchor_park" not in s and "anchors" not in s,
       f"no anchors on the question -> no anchor keys on the stamp (absent, not empty) "
       f"({sorted(s)})")
    # (b) an OLD work dir whose stamp predates the anchor keys is returned as-is
    w = _wd("cbre_f18_oldwd_")
    (w / CQ.STATE_FILE).write_text(json.dumps({
        "asked": ["q_legacy"], "answers": {}, "declined": [], "offers": {}, "titles": {},
        "landable": {"q_legacy": {"kind": "agent_doubt", "field": "officeArea",
                                  "subject": "Kestrel Reach", "options": ["450", "4500"],
                                  "source_file": "deck.pdf"}}}, indent=2), encoding="utf-8")
    old = CQ.landable(w).get("q_legacy") or {}
    ck(old.get("subject") == "Kestrel Reach" and "anchor_park" not in old,
       "a pre-change stamp is read back unchanged: the lander falls back to `subject` for it")
    # (c) a record that names NO park: the anchor is present but empty, which the lander must
    # read as absent
    rec = _rec("", None, "deck.pdf", OFFICE_DOUBT, officeArea=4500)
    q = CQ.agent_doubt_questions([rec])[0]
    ck(q.get("anchor_park") == "" and q.get("anchor_unit") == "",
       "a record naming no park carries an EMPTY anchor, never an invented one")
    w = _wd("cbre_f18_nopark_")
    CQ.emit(w, CQ.pending(w, [q]))
    s = list(CQ.landable(w).values())[0] if CQ.landable(w) else {}
    ck(s.get("anchor_park") == "" and s.get("anchors") == [{"park": "", "unit": ""}],
       f"...and so does its stamp ({s.get('anchors')})")
    # (d) a record with a park but no unit
    rec = _rec("Harrier Point", None, "deck.pdf", OFFICE_DOUBT, officeArea=4500)
    q = CQ.agent_doubt_questions([rec])[0]
    ck(q.get("anchor_park") == "Harrier Point" and q.get("anchor_unit") == "",
       "no unit -> anchor_unit is '' as the contract says")
    # (e) other kinds that carry field+options keep their pre-change stamp, no anchor keys
    w = _wd("cbre_f18_otherkind_")
    CQ.emit(w, [{"id": "q_vf", "kind": "value_format", "field": "clearHeight",
                 "options": ["12 m", "leave as is"], "subject": "property id 3",
                 "question": "what unit?", "blocking": True}])
    s = CQ.landable(w).get("q_vf") or {}
    ck(s.get("kind") == "value_format" and "anchor_park" not in s,
       "a value_format question is stamped as before, with no anchor keys")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    the_anchor_is_the_record()
    no_options_is_asked_not_promised()
    degrades_never_crashes()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F18 DOUBT STAMP ANCHORS TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F18 DOUBT STAMP ANCHORS TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
