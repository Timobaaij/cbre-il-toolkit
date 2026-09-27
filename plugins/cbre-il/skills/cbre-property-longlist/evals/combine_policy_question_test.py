#!/usr/bin/env python3
"""combine_policy_question_test.py - ONE policy question per field, fanned out per card. (3.2c)

THE MEASURED FAILURE (2026-09-26 test run). The same combinable office question was asked ten
times, once per card; four of the ten were about a figure merge's own office sum already showed,
and one card was silently contradicted (merge summed two of three lines, the broker meant all).

THE RULE PINNED HERE (clarify side). Over NEVER-ASKED combinable doubts only:
  * two or more cards on one field -> ONE `combine_policy` question P (id keyed on the field, so
    stable across record order and passes), members removed from the list, merge-settled cards
    INCLUDED with an "already shows" line;
  * `emit` stamps each member landable with `via_policy`, records `titles[P].members`, and does
    NOT add the members to `asked`;
  * a lone card whose sum merge already shows is closed without asking (`settled`), and
    `note_suppressed` keeps its expected value and a re-open payload;
  * P asked-unanswered / answered / declined removes the members it LISTED; a card it did not
    list stays per card; "ask me per card" brings every member back as its own question;
  * `policy_mode` maps an answer, junk is "per_card" (ask, never guess);
    `policy_member_answer` derives each card's answer from the policy answer;
  * an already-asked doubt is never regrouped (the in-flight guard);
  * `apply_doubt_cap` makes P cost ONE slot.
The lander fan-out, the post-merge recheck, deliver's lines and merge's storey fix are the run.py
/ merge / deliver halves (IA-7b, IA-6) and are pinned by their own evals.

Every name is invented. Offline. Run: python evals/combine_policy_question_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _wd(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def _card(park, parts, src=None, extra=None, question="three office lines, no total; which is it?"):
    d = {"subject": "office area", "question": question, "field": "officeArea",
         "options": list(parts), "default": parts[0], "combinable": True}
    r = {"park": park, "unit": "Unit 1", "city": "Eastmere", "areaUnit": "sq ft",
         "warehouseArea": 150000,
         "__meta": {"source_file": src or (park.lower().replace(" ", "_") + ".pdf"), "doubts": [d]}}
    r.update(extra or {})
    return r


A = _card("Alder Point", ["3,080 sq ft (GF)", "6,155 sq ft (FF)", "1,620 sq ft (SF)"])
B = _card("Birch Row", ["2,000 sq ft (GF)", "2,500 sq ft (FF)"])
C_ = _card("Cedar Gate", ["1,100 sq ft (hub 1)", "900 sq ft (hub 2)"])
# merge's own F11 sum equals Python's sum on this one: the raw lines are fields too (rule 3.6)
S = _card("Sorrel Yard", ["4,000 sq ft (GF)", "1,000 sq ft (FF)"],
          extra={"officeGroundFloor": "4,000 sq ft", "officeFirstFloor": "1,000 sq ft"})


def _answer(w, mapping):
    (w / "answers.json").write_text(json.dumps(mapping), encoding="utf-8")
    CQ.ingest_answers(w)


def _grouped(w, recs):
    qs = CQ.agent_doubt_questions(recs)
    out, settled = CQ.group_combinable(w, qs)
    return qs, CQ.apply_doubt_cap(out), settled


def one_policy_question() -> None:
    print("1. three unasked combinable officeArea doubts -> ONE policy question")
    w = _wd("cp_one_")
    qs, out, settled = _grouped(w, [A, B, C_])
    pol = [q for q in out if q.get("kind") == "combine_policy"]
    ck(len(pol) == 1 and len(out) == 1, f"one P and nothing else ({[q.get('kind') for q in out]})")
    P = pol[0] if pol else {}
    ck(P.get("id") == CQ.policy_qid("officeArea"), "P's id is policy_qid(field)")
    ck(P.get("options") == list(CQ.POLICY_OPTIONS), "P offers the four fixed policy options")
    ck("field" not in P and P.get("policy_field") == "officeArea",
       "P has NO `field` (no landable stamp for P itself), only `policy_field`")
    ck(not P.get("blocking") and CQ.materiality(P) == "display" and CQ.is_material(P),
       "non-blocking, display-material")
    ck(len(P.get("members") or []) == 3 and {m["id"] for m in P["members"]} == {q["id"] for q in qs},
       "P lists all three members")
    ck(all(m.get("answer_handling") == CQ.ANSWER_APPLIED and m.get("combinable") for m in P["members"]),
       "each member carries its combinable block and ANSWER_APPLIED")
    txt = P.get("question", "")
    ck(txt.startswith("3 cards print their office area as several separate lines")
       and "Alder Point, Unit 1: 3,080 sq ft (GF) + 6,155 sq ft (FF) + 1,620 sq ft (SF) = "
           "10,855 sq ft combined; first line 3,080 sq ft (GF)" in txt
       and "'ask me per card' asks about each separately" in txt,
       "question text: count, per-card line, closing sentence")
    ck(P.get("if_unanswered") == CQ.POLICY_IF_UNANSWERED, "fixed if_unanswered")
    ck(settled == [], "nothing settled by merge here")
    # stable id: record order, and a second pass in a fresh dir
    _, out2, _ = _grouped(_wd("cp_one2_"), [C_, A, B])
    ck([q["id"] for q in out2] == [P.get("id")], "same P id when the records arrive reordered")


def emit_and_state() -> None:
    print("2. emit: members stamped landable with via_policy, NOT asked")
    w = _wd("cp_emit_")
    qs, out, _ = _grouped(w, [A, B, C_])
    P = out[0]
    pend = CQ.pending(w, out)
    ck([q["id"] for q in pend] == [P["id"]], "P is pending")
    CQ.emit(w, pend)
    st = CQ.load_state(w)
    mids = [q["id"] for q in qs]
    ck(P["id"] in st["asked"] and not any(m in st["asked"] for m in mids),
       "P is asked; no member is")
    land = st.get("landable") or {}
    ck(P["id"] not in land, "no landable stamp for P")
    ok = all((land.get(m) or {}).get("via_policy") == P["id"]
             and (land.get(m) or {}).get("kind") == "agent_doubt"
             and (land.get(m) or {}).get("field") == "officeArea"
             and ((land.get(m) or {}).get("combinable") or {}).get("option")
             for m in mids)
    ck(ok, "every member: landable agent_doubt stamp with field, combinable and via_policy")
    ck((st["titles"].get(P["id"]) or {}).get("members") == [m["id"] for m in P["members"]],
       "titles[P].members lists the member ids")
    ck(all((st["titles"].get(m) or {}).get("via_policy") == P["id"] for m in mids),
       "titles[member].via_policy")
    # next pass, P asked and unanswered: members leave, P is not rebuilt, a NEW card stays per card
    D = _card("Dogwood Lane", ["500 sq ft (GF)", "700 sq ft (FF)"])
    qs2 = CQ.agent_doubt_questions([A, B, C_, D])
    out2, _ = CQ.group_combinable(w, qs2)
    ids2 = [q["id"] for q in out2]
    ck(len(out2) == 1 and out2[0].get("kind") == "agent_doubt" and out2[0].get("anchor_park") == "Dogwood Lane",
       f"P asked: listed members leave, the late card stays its own question ({ids2})")
    return w, P, qs


def answers() -> None:
    print("3. answering P: fan-out answers are DERIVED per card")
    w, P, qs = emit_and_state()
    land = CQ.landable(w)
    stamp = land[qs[0]["id"]]
    ck(CQ.policy_member_answer(stamp, CQ.POLICY_COMBINE) == "10,855 sq ft (3 printed lines combined)",
       "combine -> the stamp's synthesised option")
    ck(CQ.policy_member_answer(stamp, CQ.POLICY_FIRST) == "3,080 sq ft (GF)", "first -> options[0]")
    un = CQ.policy_member_answer(stamp, CQ.POLICY_UNSTATED)
    ck(un == "not stated" and CQ.is_not_stated(un), "unstated -> 'not stated' (a clearing token)")
    ck(CQ.policy_member_answer(stamp, CQ.POLICY_PER_CARD) is None
       and CQ.policy_member_answer(stamp, "skip") is None, "per card / decline -> None")
    _answer(w, {P["id"]: CQ.POLICY_COMBINE})
    out, _ = CQ.group_combinable(w, CQ.agent_doubt_questions([A, B, C_]))
    ck(out == [], "P answered 'combine': every listed member is resolved by the fan-out")
    # per card: every member comes back as its own question
    _answer(w, {P["id"]: CQ.POLICY_PER_CARD})
    out, _ = CQ.group_combinable(w, CQ.agent_doubt_questions([A, B, C_]))
    ck(len(out) == 3 and all(q.get("kind") == "agent_doubt" and q.get("combinable") for q in out),
       f"'ask me per card': three per-card questions, each with its sum option ({len(out)})")
    # junk is per card too
    _answer(w, {P["id"]: "hmm, depends on the building"})
    out, _ = CQ.group_combinable(w, CQ.agent_doubt_questions([A, B, C_]))
    ck(len(out) == 3, "junk answer -> per card (asks, never guesses)")
    # a decline keeps every card as shipped: members resolved, nothing asked
    _answer(w, {P["id"]: "skip"})
    ck(P["id"] in CQ.declined_ids(w), "skip is recorded as a decline")
    out, _ = CQ.group_combinable(w, CQ.agent_doubt_questions([A, B, C_]))
    ck(out == [], "declined P: members resolved to their defaults, nothing re-asked")
    # a DIRECT per-card answer to a member id is read (members are not in `asked`)
    mid = qs[1]["id"]
    _answer(w, {mid: "2,000 sq ft (GF)", "q_neverasked": "x"})
    st = CQ.load_state(w)
    ck(st["answers"].get(mid) == "2,000 sq ft (GF)" and "q_neverasked" not in st["answers"],
       "a member id's direct answer is ingested; an id nobody was asked is still ignored")


def modes() -> None:
    print("4. policy_mode")
    cases = {
        CQ.POLICY_COMBINE: "combine", CQ.POLICY_FIRST: "first", CQ.POLICY_UNSTATED: "unstated",
        CQ.POLICY_PER_CARD: "per_card", "Combine them": "combine", "sum": "combine",
        "use the first line": "first", "first": "first", "leave it blank": "unstated",
        "not stated": "unstated", "skip": "decline", "you decide": "decline",
        "leave as is": "decline", "don't combine them": "per_card",
        "combine except Birch Row": "per_card", "": "per_card", None: "per_card",
        "whatever the tracker says": "per_card",
    }
    for raw, want in cases.items():
        got = CQ.policy_mode(raw)
        ck(got == want, f"policy_mode({raw!r}) == {want!r} ({got!r})")


def merge_settled() -> None:
    print("5. merge-settled cards")
    w = _wd("cp_settled_")
    qs, out, settled = _grouped(w, [S])
    ck(out == [] and [q["id"] for q in settled] == [qs[0]["id"]],
       "a lone card whose sum merge already shows is closed without asking")
    CQ.note_suppressed(w, settled, why=CQ.WHY_MERGED)
    sup = (CQ.load_state(w).get("suppressed") or {}).get(qs[0]["id"]) or {}
    ck(sup.get("why_not_asked") == CQ.WHY_MERGED, "suppressed with why 'settled by merge'")
    ck(sup.get("expected") == {"value": 5000, "unit": "sq ft"}, f"expected value kept ({sup.get('expected')})")
    ck(sup.get("anchors") == [{"park": "Sorrel Yard", "unit": "Unit 1"}], "anchors kept")
    pl = sup.get("question_payload") or {}
    ck(pl.get("id") == qs[0]["id"] and (pl.get("combinable") or {}).get("sum") == 5000
       and "over_cap" not in pl, "the per-card question is kept as a re-open payload")
    # grouped with an unsettled card: the settled one is INCLUDED, with the suffix
    w2 = _wd("cp_settled2_")
    _, out2, settled2 = _grouped(w2, [S, B])
    ck(len(out2) == 1 and out2[0].get("kind") == "combine_policy" and settled2 == [],
       "settled + unsettled -> ONE P covering both, nothing auto-closed")
    txt = out2[0].get("question", "") if out2 else ""
    ck("Sorrel Yard, Unit 1: 4,000 sq ft (GF) + 1,000 sq ft (FF) = 5,000 sq ft combined; first line "
       "4,000 sq ft (GF) - already shows the combined figure, computed by the pipeline" in txt,
       "the settled card's line says it already shows the sum")
    mem = {m["anchor_park"]: m for m in (out2[0].get("members") or [])} if out2 else {}
    ck(mem.get("Sorrel Yard", {}).get("settled_by_merge") is True
       and mem.get("Birch Row", {}).get("settled_by_merge") is False, "members carry settled_by_merge")
    # a DIFFERENT merge sum is named, and the answer decides
    q1 = dict(CQ.agent_doubt_questions([A])[0])
    q1["merge_expect"] = {"status": "computed", "value": 4700, "unit": "sq ft",
                          "components": ["hubOffice1", "hubOffice2"]}
    q2 = CQ.agent_doubt_questions([B])[0]
    P = CQ._policy_question("officeArea", [q1, q2])
    ck("- the pipeline combines only 2 of these lines (4,700 sq ft); this answer decides" in P["question"],
       "a partial merge sum is named with its line count")
    ck(not CQ._merge_settles(q1) and CQ._merge_settles(qs[0]), "_merge_settles truth")


def in_flight_guard() -> None:
    print("6. an ALREADY-ASKED doubt is never regrouped")
    w = _wd("cp_inflight_")
    qs = CQ.agent_doubt_questions([A, B, C_])
    CQ.emit(w, CQ.pending(w, qs))            # the pre-change behaviour: three per-card questions
    st = CQ.load_state(w)
    ck(all(q["id"] in st["asked"] for q in qs), "three per-card questions asked (old shape)")
    out, settled = CQ.group_combinable(w, CQ.agent_doubt_questions([A, B, C_]))
    ck(len(out) == 3 and all(q.get("kind") == "agent_doubt" for q in out) and settled == [],
       "nothing grouped, nothing settled: the list is returned as it came")
    ck(CQ.pending(w, out) == [], "...and pending asks none of them again")
    ck(CQ.policy_qid("officeArea") not in CQ.load_state(w)["asked"], "no policy question was created")


def cap_and_failsafe() -> None:
    print("7. apply_doubt_cap: P costs one slot; group_combinable fails safe")
    others = []
    for i in range(12):
        others.append({"park": f"Other {i}", "unit": "", "__meta": {"source_file": f"o{i}.pdf", "doubts": [
            {"subject": "clear height", "question": f"eaves {i}: 10 m or 12 m?", "field": "clearHeight",
             "options": ["10 m", "12 m"], "default": "10 m"}]}})
    qs = CQ.agent_doubt_questions(others + [A, B, C_])
    ck(sum(1 for q in qs if q.get("over_cap")) == 3, "before grouping: 15 material doubts, 3 over the cap")
    w = _wd("cp_cap_")
    out, _ = CQ.group_combinable(w, qs)
    out = CQ.apply_doubt_cap(out)
    ck(len(out) == 13 and sum(1 for q in out if q.get("over_cap")) == 1,
       f"after grouping: 13 material questions, 1 over the cap ({sum(1 for q in out if q.get('over_cap'))})")
    again = CQ.apply_doubt_cap(out)
    ck(sum(1 for q in again if q.get("over_cap")) == 1, "apply_doubt_cap is idempotent")
    bad = [{"id": "q_x", "kind": "agent_doubt", "field": "officeArea", "combinable": {"option": "x"},
            "materiality": "display"}]
    res, st = CQ.group_combinable(object(), bad)   # an unusable work dir: load_state must not crash it
    ck(isinstance(res, list) and st == [], "a bad work dir / odd question never raises")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    one_policy_question()
    answers()
    modes()
    merge_settled()
    in_flight_guard()
    cap_and_failsafe()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"COMBINE POLICY QUESTION TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("COMBINE POLICY QUESTION TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
