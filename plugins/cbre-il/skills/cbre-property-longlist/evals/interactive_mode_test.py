#!/usr/bin/env python3
"""interactive_mode_test.py - broker-in-the-loop is the STANDARD mode (workstream 3).

Pinned here:
  1. clarify_mode: interactive is the default; headless via clarify.mode, per
     assume_defaults, or the SKIP_ALL sentinel.
  2. 'unsure' match verdicts (item 3.3): interactive -> a BLOCKING broker question;
     the broker's answer becomes the recorded verdict; headless -> 'different',
     attributed and disclosed. Same for value-conflict picks (default kept).
  3. translation eligibility (item 3.7): single-word enums, addresses, postcodes and
     link stubs never reach the exit-12 round; real prose still does.
Offline.
"""
import json
import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
import clarify as CQ  # noqa: E402
import _common as C  # noqa: E402
import run as RUN  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


# 1) mode resolution: interactive is the STANDARD
w = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mode_"))
check("default-interactive", CQ.clarify_mode(w, {}) == "interactive")
check("cfg-headless", CQ.clarify_mode(w, {"clarify": {"mode": "headless"}}) == "headless")
check("assume-defaults", CQ.clarify_mode(w, {"clarify": {"assume_defaults": True}}) == "headless")
(w / CQ.SKIP_ALL_FILE).touch()
check("skipall-headless", CQ.clarify_mode(w, {}) == "headless")

GREY = [{"pair_id": "abc123", "a": {"park": "Alpha Park", "city": "Corby",
                                    "warehouseArea": 356202, "areaUnit": "sq ft",
                                    "__meta": {"source_file": "tracker.xlsx"}},
         "b": {"park": "Alpha Park South", "city": "Corby",
               "warehouseArea": 230000, "areaUnit": "sq ft",
               "__meta": {"source_file": "brochure.pdf"}}}]

# 2a) interactive: unsure -> ONE blocking broker question, nothing written yet
w2 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_uns_"))
(w2 / "match_decisions.json").write_text(
    json.dumps({"abc123": {"verdict": "unsure", "reason": "genuinely torn"}}),
    encoding="utf-8")
n, qs = RUN.unsure_pair_questions(w2, {}, GREY)
check("interactive-question", n == 0 and len(qs) == 1 and qs[0]["blocking"] is True
      and qs[0]["asked_of"] == "broker")
check("question-names-both", "Alpha Park" in qs[0]["question"]
      and "brochure.pdf" in qs[0]["question"])

# 2b) the broker's answer becomes the recorded verdict
(w2 / "answers.json").write_text(json.dumps({qs[0]["id"]: "same property"}),
                                 encoding="utf-8")
n, qs = RUN.unsure_pair_questions(w2, {}, GREY)
md = json.loads((w2 / "match_decisions.json").read_text(encoding="utf-8-sig"))
check("answer-recorded", n == 1 and not qs and md["abc123"]["verdict"] == "same"
      and "broker" in md["abc123"]["reason"])

# 2c) headless: unsure -> 'different', attributed, no questions
w3 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_unh_"))
(w3 / "match_decisions.json").write_text(
    json.dumps({"abc123": "unsure"}), encoding="utf-8")
n, qs = RUN.unsure_pair_questions(w3, {"clarify": {"mode": "headless"}}, GREY)
md = json.loads((w3 / "match_decisions.json").read_text(encoding="utf-8-sig"))
check("headless-different", n == 1 and not qs
      and md["abc123"]["verdict"] == "different"
      and "disclosed" in md["abc123"]["reason"])

# 2d) value-conflict unsure: headless keeps the precedence default
w4 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_unf_"))
conflicts = [{"conflict_id": "cf9", "field": "clearHeight", "default": "a",
              "candidates": [{"label": "a", "value": "12 m"},
                             {"label": "b", "value": "15 m"}]}]
fd = {"cf9": {"pick": "unsure"}}
(w4 / "field_decisions.json").write_text(json.dumps(fd), encoding="utf-8")
n, qs = RUN.unsure_pick_questions(w4, {"clarify": {"mode": "headless"}}, conflicts, fd)
out = json.loads((w4 / "field_decisions.json").read_text(encoding="utf-8-sig"))
check("pick-default-kept", n == 1 and not qs and out["cf9"]["pick"] == "a")

# 2e) interactive pick question offers the candidates; the answer maps to the label
w5 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_unfi_"))
(w5 / "field_decisions.json").write_text(json.dumps(fd), encoding="utf-8")
n, qs = RUN.unsure_pick_questions(w5, {}, conflicts, fd)
check("pick-question", n == 0 and len(qs) == 1 and "b: 15 m" in qs[0]["options"])
(w5 / "answers.json").write_text(json.dumps({qs[0]["id"]: "b: 15 m"}), encoding="utf-8")
n, qs = RUN.unsure_pick_questions(w5, {}, conflicts, fd)
out = json.loads((w5 / "field_decisions.json").read_text(encoding="utf-8-sig"))
check("pick-answer-recorded", n == 1 and not qs and out["cf9"]["pick"] == "b")

# 4) photo confirmations at decision time (item 3.4)
doubts = [{"park": "Alpha Park", "brochure": "photos/alpha.pdf", "key": "k1",
           "note": "name matches, no address"}]
pq = CQ.photo_confirm_questions(doubts)
check("photo-q", len(pq) == 1 and pq[0]["blocking"] is False
      and pq[0]["options"] == ["yes", "no"] and "alpha.pdf" in pq[0]["question"])
w6 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_pc_"))
(w6 / "answers.json").write_text(json.dumps({pq[0]["id"]: "yes"}), encoding="utf-8")
pm = {"confident": [], "uncertain": [dict(doubts[0], property_key="k1")], "unrelated": []}
pm["uncertain"][0]["brochure"] = "photos/alpha.pdf"
n = RUN.apply_photo_confirm_answers(w6, pm)
check("photo-yes-moves", n == 1 and len(pm["confident"]) == 1 and not pm["uncertain"])
w7 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_pcn_"))
(w7 / "answers.json").write_text(json.dumps({pq[0]["id"]: "no"}), encoding="utf-8")
pm2 = {"confident": [], "uncertain": [{"brochure": "photos/alpha.pdf",
                                       "property_key": "k1"}], "unrelated": []}
check("photo-no-moves", RUN.apply_photo_confirm_answers(w7, pm2) == 1
      and len(pm2["unrelated"]) == 1)
# an answer for THIS property never endorses the brochure for a DIFFERENT one
pm3 = {"confident": [], "uncertain": [{"brochure": "photos/alpha.pdf",
                                       "property_key": "k2-other"}], "unrelated": []}
check("photo-bound-to-property", RUN.apply_photo_confirm_answers(w7, pm3) == 0
      and len(pm3["uncertain"]) == 1)

# 5) reader doubts (item 3.2): material-first, capped, non-blocking. Only a doubt that
#    changes what the dashboard SHOWS is asked (B62) - the rest are carried for the Gaps
#    Report. Full materiality coverage lives in clarify_materiality_test.py.
recs = [{"park": f"P{i}", "city": "Corby",
         "__meta": {"source_file": "deck.pdf",
                    "doubts": [{"subject": f"P{i}",
                                "question": ("two printed AREA figures could each be the "
                                             "warehouse area" if i < 3 else
                                             "the brochure cover tint looks unusual"),
                                "default": "the larger figure"}]}}
        for i in range(15)]
dq = CQ.agent_doubt_questions(recs)
ask = [q for q in dq if CQ.is_material(q)]
check("doubts-material-only-asked", len(ask) == 3)
check("doubts-material-first", dq[:3] == ask)
check("doubts-core-first", "area" in dq[0]["question"].lower())
check("doubts-ledger-carried", len(dq) == 15
      and all(q["materiality"] == "ledger" for q in dq[3:]))
check("doubts-nonblocking", all(q["blocking"] is False and q["asked_of"] == "broker"
                                for q in dq))
# the cap applies to the MATERIAL ones - a ledger doubt never consumes a broker slot
recs_all_material = [{"park": f"Q{i}", "city": "Corby",
                      "__meta": {"source_file": "deck.pdf",
                                 "doubts": [{"subject": f"Q{i}",
                                             "question": "which printed warehouse area is "
                                                         "the right one?"}]}}
                     for i in range(15)]
_all_mat = CQ.agent_doubt_questions(recs_all_material)
check("doubts-capped", len([q for q in _all_mat if not q.get("over_cap")])
      == CQ.MAX_DOUBT_QUESTIONS == 12)
# the cap is on ASKING, not on knowing: the overflow is flagged and disclosed, never lost
check("doubts-overflow-carried", len(_all_mat) == 15
      and sum(1 for q in _all_mat if q.get("over_cap")) == 3)

# 6) excluded-figure questions (item 3.5)
w8 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_xf_"))
canonical = {"meta": {"excluded": [{
    "name": "Alpha Park South, Lutterworth",
    "headline": {"warehouseArea": 230000, "areaUnit": "sq ft"},
    "likely_same_as": {"name": "Alpha Park South, Lutterworth", "tier": "forbidden",
                       "kept_index": 0,
                       "kept_headline": {"warehouseArea": 356202, "areaUnit": "sq ft"}}}]},
    "properties": [{"id": 1, "park": "Alpha Park South", "city": "Lutterworth",
                    "warehouseArea": 356202, "areaUnit": "sq ft"}]}
(w8 / "canonical.json").write_text(json.dumps(canonical), encoding="utf-8")
xq = RUN.excluded_figure_questions(w8, {}, w8 / "canonical.json")
check("xf-question", len(xq) == 1 and xq[0]["blocking"] is False
      and "230,000" in xq[0]["question"] and "356,202" in xq[0]["question"])
# headless: no questions at all
check("xf-headless-silent",
      RUN.excluded_figure_questions(w8, {"clarify": {"mode": "headless"}},
                                    w8 / "canonical.json") == [])
# the broker picks the excluded figure -> an attributed repair appears
use_opt = next(o for o in xq[0]["options"] if o.startswith("use"))
(w8 / "answers.json").write_text(json.dumps({xq[0]["id"]: use_opt}), encoding="utf-8")
xq2 = RUN.excluded_figure_questions(w8, {}, w8 / "canonical.json")
reps = json.loads((w8 / "repairs.json").read_text(encoding="utf-8-sig"))
check("xf-repair", not xq2 and reps[0]["set"] == {"warehouseArea": 230000}
      and "broker" in reps[0]["verified_by"])

# 3) translation eligibility tuning (FIELD-based only - translate_shape_test pins
#    single-word foreign statuses like "Ja"/"Si" as must-translate, so no shape rule)
check("address-ineligible",
      not C.is_translatable_value("address", "Calle de la Industria 5, Nave 3"))
check("postcode-ineligible", not C.is_translatable_value("postcode", "NN17 3JG"))
check("linkstub-ineligible", not C.is_translatable_value("brochureLink", "Brochure"))
check("foreign-status-still-eligible", C.is_translatable_value("status", "Ja"))
check("prose-still-eligible", C.is_translatable_value(
    "description", "Nave logistica moderna con muelles de carga y patio amplio"))

# 7) WIRING pins: the helpers above are only live if main() actually calls them -
#    a revert of the wiring must fail here, not on a live run
src = (pathlib.Path(RUN.__file__)).read_text(encoding="utf-8", errors="replace")
check("wire-mode-gate", 'clarify_mode(work, cfg) == "interactive"' in src)
check("wire-photo-apply", "apply_photo_confirm_answers(work, pm, _resolve_key)" in src)
check("wire-photo-qs", "photo_confirm_questions(" in src
      and "agent_doubt_questions(" in src)
check("wire-unsure-pairs", "unsure_pair_questions(work, cfg, grey)" in src)
check("wire-unsure-picks", "unsure_pick_questions(work, cfg, conflicts, fd)" in src)
check("wire-excluded", "excluded_figure_questions(work, cfg, canonical)" in src)
check("wire-kept-index", '"kept_index"' in
      (pathlib.Path(RUN.__file__).parent / "merge.py").read_text(encoding="utf-8",
                                                                 errors="replace"))

# 8) junk answers are RE-ASKED with the rejection spelled out, never swallowed
#    (the Phase-4 blind review's probe-verified livelock class)
w9 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_junk_"))
(w9 / "match_decisions.json").write_text(json.dumps({"abc123": "unsure"}),
                                         encoding="utf-8")
qj = RUN.unsure_pair_questions(w9, {}, GREY)[1]
(w9 / "answers.json").write_text(
    json.dumps({qj[0]["id"]: "yes they are the same"}), encoding="utf-8")
n, qs = RUN.unsure_pair_questions(w9, {}, GREY)
check("junk-reasked", n == 0 and len(qs) == 1
      and "was not one of the options" in qs[0]["question"])
md9 = json.loads((w9 / "match_decisions.json").read_text(encoding="utf-8-sig"))
check("junk-not-written", md9["abc123"] == "unsure")

# a paraphrase VALUE answer for a pick is accepted (unambiguous), not discarded
w10 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_para_"))
(w10 / "field_decisions.json").write_text(json.dumps(fd), encoding="utf-8")
qp = RUN.unsure_pick_questions(w10, {}, conflicts, fd)[1]
(w10 / "answers.json").write_text(json.dumps({qp[0]["id"]: "15 m"}), encoding="utf-8")
n, qs = RUN.unsure_pick_questions(w10, {}, conflicts, fd)
outp = json.loads((w10 / "field_decisions.json").read_text(encoding="utf-8-sig"))
check("paraphrase-pick-accepted", n == 1 and not qs and outp["cf9"]["pick"] == "b")

# 9) a SETTLED pair is never re-opened by a later 'unsure'
w11 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_settled_"))
(w11 / "match_decisions.json").write_text(json.dumps({"abc123": "unsure"}),
                                          encoding="utf-8")
(w11 / "match_settled.json").write_text(
    json.dumps({"abc123": {"verdict": "same", "reason": "broker decided earlier"}}),
    encoding="utf-8")
n, qs = RUN.unsure_pair_questions(w11, {"clarify": {"mode": "headless"}}, GREY)
check("settled-not-reopened", n == 0 and not qs)

# 10) excluded-figure junk answers re-ask; a malformed hand-file refuses LOUDLY
w12 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_xfj_"))
(w12 / "canonical.json").write_text(json.dumps(canonical), encoding="utf-8")
xqj = RUN.excluded_figure_questions(w12, {}, w12 / "canonical.json")
(w12 / "answers.json").write_text(
    json.dumps({xqj[0]["id"]: "the excluded one please"}), encoding="utf-8")
xq2 = RUN.excluded_figure_questions(w12, {}, w12 / "canonical.json")
check("xf-junk-reasked", len(xq2) == 1 and "matched neither option" in xq2[0]["question"])
(w12 / "repairs.json").write_text('[{"id": "hand-001",},]', encoding="utf-8")  # not JSON
(w12 / "answers.json").write_text(
    json.dumps({xqj[0]["id"]: next(o for o in xqj[0]["options"] if o.startswith("use"))}),
    encoding="utf-8")
xq3 = RUN.excluded_figure_questions(w12, {}, w12 / "canonical.json")
check("xf-handfile-preserved",
      (w12 / "repairs.json").read_text(encoding="utf-8") == '[{"id": "hand-001",},]')

print("INTERACTIVE MODE TEST: PASS")
