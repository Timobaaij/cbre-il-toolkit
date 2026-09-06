#!/usr/bin/env python3
"""clarify_materiality_test.py - the run only STOPS for what the client will see. (B62)

THE RULE, set by the broker on 2026-08-26 after a live interactive run asked too often:
a question is put to the user only when its answer would change

  * a value, photo or label RENDERED on the dashboard (card, detail modal, compare, map), or
  * HOW MANY options ship (the 17-vs-41 class).

Anything else - a doubt that moves a provenance note, a disagreement on an Excel-only column -
is recorded and DISCLOSED in the Gaps Report instead of costing a broker round-trip.

Pinned here, because every one of these is a way the rule could rot:
  1. DISPLAY_FIELDS still matches the template (a renamed/added rendered field must fail HERE,
     not on a live run where it would silently stop asking about something the client sees).
  2. The never-suppress set: units, dataset unit, source authority, value format, unsure
     matches. Their default IS the damage; materiality must never reach them.
  3. Doubt classification: a declaration beats the text; the text heuristic errs to asking.
  4. pending() is the chokepoint - a ledger question leaves no trace in `asked`, is never
     returned twice, and IS recorded for disclosure.
  5. An immaterial field conflict RESOLVES to the precedence default at the producer. If it
     were merely filtered, field_decisions.json would keep 'unsure' and exit 10 would loop
     for ever - the livelock this file exists to prevent.
  6. The Gaps Report actually prints the suppressed ones. Suppression without disclosure is
     the silent presumption the whole skill is built against.
Offline.
"""
import json
import re
import sys
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import clarify as CQ  # noqa: E402
import _common as C  # noqa: E402
import deliver as DEL  # noqa: E402
import run as RUN  # noqa: E402

fails = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


# --------------------------------------------------------------- 1. the display set
# Re-derive it the way it was derived in the first place: every `p.<field>` the template's
# render JS reads, intersected with the canonical schema's property fields. This is the drift
# guard - the constant in clarify.py is a cache of THIS.
tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8",
                                                              errors="replace")
schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(
    encoding="utf-8-sig"))
schema_fields = set(schema["$defs"]["property"]["properties"])
rendered = set(re.findall(r"\bp\.([A-Za-z_][A-Za-z0-9_]*)", tpl)) & schema_fields
ck(rendered == set(CQ.DISPLAY_FIELDS),
   f"DISPLAY_FIELDS matches the template ({len(rendered)} rendered fields)"
   + (f" - drift: {sorted(rendered ^ set(CQ.DISPLAY_FIELDS))}"
      if rendered != set(CQ.DISPLAY_FIELDS) else ""))
ck(CQ.field_is_displayed("warehouseArea") and CQ.field_is_displayed("photo"),
   "a card field is displayed")
ck(not CQ.field_is_displayed("postcode") and not CQ.field_is_displayed("warehouseAreaSqm"),
   "an Excel/ledger-only canonical field is NOT displayed")
ck(not CQ.field_is_displayed("someOpenTrackerColumn") and not CQ.field_is_displayed(""),
   "an open-captured tracker column is NOT displayed (and neither is nothing)")

# --------------------------------------------------------------- 2. never suppressed
NEVER = {
    "area_unit": "display", "rent_unit": "display", "dataset_unit": "display",
    "value_format": "display", "source_authority": "count", "match_unsure": "count",
    "photo_confirm": "display", "excluded_figure": "display",
}
# `record_count` used to sit in this map. Its producer is deleted (a page-count trigger that
# fired on most decks), so there is no kind left to classify - asserted in clarify_test.
for kind, expect in sorted(NEVER.items()):
    q = {"id": "x", "kind": kind}
    ck(CQ.materiality(q) == expect and CQ.is_material(q),
       f"{kind} is always material ({expect})")
# value_format carries a `field`, and must stay material even for a non-displayed one: it
# BLOCKS the build (exit 6) and only a broker answer or decline clears it, so suppressing
# one would wedge the run with no way forward.
ck(CQ.is_material({"kind": "value_format", "field": "postcode"}),
   "value_format is material even on a non-displayed field (it blocks the build)")
ck(CQ.is_material({"kind": "some_future_kind"}),
   "an UNKNOWN kind defaults to material - a new producer keeps today's behaviour")
ck(CQ.is_material({"kind": "agent_doubt", "materiality": "count"})
   and not CQ.is_material({"kind": "agent_doubt", "materiality": "ledger"}),
   "an explicit `materiality` stamp wins")

# --------------------------------------------------------------- 3. field conflicts
ck(CQ.materiality({"kind": "field_unsure", "field": "clearHeight"}) == "display",
   "a conflict on a DISPLAYED field is material")
ck(CQ.materiality({"kind": "field_unsure", "field": "warehouseAreaSqm"}) == "ledger",
   "a conflict on a genuinely ledger-only field is not")

# --------------------------------------------------------------- 4. doubt classification
D = CQ._doubt_materiality
ck(D({"field": "warehouseArea"}, "anything at all") == "display",
   "a DECLARED displayed field beats the text")
ck(D({"field": "warehouseAreaSqm"}, "which figure is right") == "ledger",
   "...and a declared ledger-only field beats the text too")
ck(D({"fields": ["warehouseAreaSqm", "warehouseRent"]}, "") == "display",
   "any one material field in `fields` is enough")
ck(D({"materiality": "ledger"}, "the warehouse area is ambiguous") == "ledger",
   "an explicit declaration beats everything")
ck(D({"affects": "count"}, "the brochure cover tint looks unusual") == "count",
   "`affects` is honoured as well as `materiality` (both are documented to readers)")
# AN UNRECOGNISED FIELD NAME IS NOT A LEDGER FIELD. Both blind reviews found this: a reading
# model writes "area" or "warehouse_area", and demoting on a near-miss hid a doubt about the
# figure on the card. An unknown name means UNDECLARED, so the wording is read instead.
for _bad_name in ("area", "size", "warehouse_area", "WarehouseArea", "gla", "eaves",
                  "rent", "n/a", "unknown", ""):
    ck(D({"field": _bad_name},
         "two printed figures could each be the warehouse area") == "display",
       f"a declared field the pipeline does not know ('{_bad_name}') falls back to the text")
ck(CQ.known_field("warehouseArea") and CQ.known_field("postcode")
   and not CQ.known_field("area") and not CQ.known_field("warehouse_area"),
   "known_field separates 'a real field' from 'not a field name'")
# MATCHER-IDENTITY FIELDS ARE MATERIAL even though the dashboard never prints them: settling
# one silently can re-cluster the dataset and move the option count.
ck(not CQ.field_is_displayed("postcode") and CQ.field_is_material("postcode"),
   "postcode is not displayed but IS material - the matcher reads it for identity")
for _f in ("park", "address", "scheme", "building", "district", "region", "city"):
    ck(CQ.field_is_material(_f), f"`{_f}` is material (matcher identity/place field)")
ck(not CQ.field_is_material("warehouseAreaSqm")
   and not CQ.field_is_material("someOpenTrackerColumn"),
   "a genuinely Excel-only field and an open column stay immaterial")
try:
    import match as _M
    _declared = ({str(f) for f in getattr(_M, "_GREY_IDENT_FIELDS", ())}
                 | {str(f) for f in getattr(_M, "_PLACE_FIELDS_EXTRA", ())})
    ck(_declared <= CQ.match_sensitive_fields(),
       f"every match identity/place field is covered ({len(_declared)} of them)")
except Exception as _e:
    ck(False, f"match.py identity fields readable: {_e}")
ck(D({}, "two printed figures could each be the warehouse area") == "display",
   "text: a doubt about a shown figure is asked")
ck(D({}, "is the clear height 12 m or 12.5 m?") == "display", "text: a spec doubt is asked")
ck(D({}, "does page 4 belong to a different property?") == "count",
   "text: a doubt about WHICH property is asked")
ck(D({}, "I could not tell if these are two separate options or one") == "count",
   "text: a doubt about how many options is asked")
ck(D({}, "the brochure cover tint looks unusual") == "ledger",
   "text: a cosmetic doubt is NOT asked")
ck(D({}, "the source file name has a typo in it") == "ledger",
   "text: a file-hygiene doubt is NOT asked")
ck(D({}, "the page date format is ambiguous (dd/mm or mm/dd)") == "ledger",
   "text: a date-format doubt is NOT asked - no displayed value moves")
ck(D({}, "the cover tint on the warehouse brochure looks unusual") == "ledger",
   "text: a cosmetic doubt is not PROMOTED by a stray building word")
ck(D({}, "the early access date format is ambiguous (Q1 or January)") == "display",
   "...but an ambiguous availability date still is, because the card shows it")
# THE DANGEROUS DIRECTION. Every line below is a doubt a reader would really write about
# something the client sees; both blind reviews found the first, tighter lexicon demoting
# them. A regression here is invisible on a live run, which is why they are pinned.
MUST_ASK = {
    "count": [
        "an ambiguous page binding",
        "Page 5 describes two buildings; I emitted one record for the whole thing.",
        "Page 7 might describe the adjacent scheme rather than this one.",
        "I could not tell if pages 3-5 are one warehouse or a portfolio of three.",
        "It is unclear whether Hall A and Hall B are let together or individually.",
        "pages 3 and 4 look like two schemes to me",
        "the brochure may be for the neighbouring building",
        "could pages 3-5 be a second building?",
        "the deck may cover a second phase not listed elsewhere",
        "pages 7-9 might be a different address",
    ],
    "display": [
        "The prices are quoted in zloty but the header says euros.",
        "The amounts may be in thousands.",
        "The sheet header suggests thousands; I recorded the raw number.",
        "I am not certain the 15,000 refers to the warehouse only or includes the offices.",
        "The mezzanine may or may not be counted in the total.",
        "The aerial on page 1 may show the wrong plot.",
        "The tenant is named on page 2 but the sheet says vacant.",
        "The available date is given as Q1 but elsewhere as immediate.",
        "the tenant name suggests this is already let - not sure it is available",
        "the rent may be monthly rather than annual",
    ],
}
for _want, _texts in sorted(MUST_ASK.items()):
    for _t in _texts:
        ck(D({}, _t) != "ledger", f"MUST ask ({_want}): {_t[:58]}")
# the substance is often in `why_it_matters` / `options`, not in a terse `question`
ck(D({"question": "which one is right?", "why_it_matters": "the rent on the card",
      "options": ["EUR 4.50", "EUR 5.20"]}, "which one is right?") != "ledger",
   "a terse question with the substance in why_it_matters/options is still asked")
ck(D({"question": "is page 6 this one or the next one?",
      "why_it_matters": "how many cards ship"},
     "is page 6 this one or the next one?") != "ledger",
   "...and one whose context names the option count")
# `subject` is NOT read: it is a park name, and reading it would promote every doubt
ck(D({"subject": "Eastgate Park, Unit 4", "question": "the file name has a typo"},
     "the file name has a typo") == "ledger",
   "the park-name subject never promotes a doubt on its own")

# --------------------------------------------------------------- 5. pending() chokepoint
w = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat1_"))
material = {"id": "q_material", "kind": "agent_doubt", "asked_of": "broker",
            "blocking": False, "subject": "Alpha Park", "materiality": "display",
            "question": "which printed warehouse area is right?",
            "if_unanswered": "proceeds with: the larger figure"}
ledger = {"id": "q_ledger", "kind": "agent_doubt", "asked_of": "broker",
          "blocking": False, "subject": "Alpha Park", "materiality": "ledger",
          "question": "the brochure cover tint looks unusual",
          "if_unanswered": "proceeds with: the file as read"}
pend = CQ.pending(w, [material, ledger])
ck([q["id"] for q in pend] == ["q_material"], "pending() returns ONLY the material one")
st = CQ.load_state(w)
ck("q_ledger" in (st.get("suppressed") or {}), "...and RECORDS the ledger one for disclosure")
ck(st["suppressed"]["q_ledger"]["if_unanswered"].startswith("proceeds with"),
   "...with the default that shipped instead")
ck("q_ledger" not in st.get("asked", []),
   "a suppressed question is never marked ASKED - it was not")
ck([q["id"] for q in CQ.pending(w, [material, ledger])] == ["q_material"],
   "suppression is stable across passes (idempotent)")
_m = (w / CQ.STATE_FILE).stat().st_mtime_ns
CQ.pending(w, [material, ledger])
ck((w / CQ.STATE_FILE).stat().st_mtime_ns == _m,
   "...and re-recording an already-known one does NOT churn the state file (resume safety)")
# A BLOCKING question is never suppressed, whatever materiality says: dropping one leaves no
# decision, no escalation count and no way out of the loop.
_blk = {"id": "q_blocking_ledger", "kind": "field_unsure", "blocking": True,
        "field": "someOpenTrackerColumn", "subject": "an open column"}
ck([q["id"] for q in CQ.pending(pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat1b_")),
                                [_blk])] == ["q_blocking_ledger"],
   "a BLOCKING question is asked even when it classifies as ledger (livelock guard)")
# A PRE-EXISTING work dir must not be rewritten just because the new key exists: this file is
# a merge resume input, so one gratuitous write re-fires merge -> build -> deliver.
w1c = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat1c_"))
(w1c / CQ.STATE_FILE).write_text(json.dumps(
    {"asked": [], "answers": {}, "declined": [], "offers": {}, "titles": {}}, indent=2),
    encoding="utf-8")
_m0 = (w1c / CQ.STATE_FILE).stat().st_mtime_ns
CQ.ingest_answers(w1c)
CQ.ingest_answers(w1c)
ck((w1c / CQ.STATE_FILE).stat().st_mtime_ns == _m0
   and "suppressed" not in (w1c / CQ.STATE_FILE).read_text(encoding="utf-8-sig"),
   "an empty `suppressed` is never persisted, so a pre-change work dir does not churn")

# --------------------------------------------------- 5b. the cap DISCLOSES its overflow
# The cap is on ASKING. The first version returned the material overflow to nobody, which
# lost the MOST material doubts on a large corpus while still disclosing cosmetic ones.
recs_many = [{"park": f"P{i}", "city": "Corby",
              "__meta": {"source_file": "deck.pdf",
                         "doubts": [{"subject": f"P{i}",
                                     "question": "which printed warehouse area is right?",
                                     "default": "the larger figure"}]}}
             for i in range(20)]
dq_many = CQ.agent_doubt_questions(recs_many)
ck(len(dq_many) == 20, "every doubt is returned by the producer, capped or not")
ck(sum(1 for q in dq_many if q.get("over_cap")) == 20 - CQ.MAX_DOUBT_QUESTIONS,
   "the material overflow is FLAGGED rather than discarded")
w5b = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat5b_"))
_ask5b = CQ.pending(w5b, dq_many)
_sup5b = CQ.load_state(w5b).get("suppressed") or {}
ck(len(_ask5b) == CQ.MAX_DOUBT_QUESTIONS, f"only {CQ.MAX_DOUBT_QUESTIONS} are asked")
ck(len(_ask5b) + len(_sup5b) == 20,
   "ASKED + DISCLOSED accounts for every doubt - none is silently dropped")
ck(all(e.get("why_not_asked") == CQ.WHY_CAP for e in _sup5b.values()),
   "...and the overflow records WHY it was not asked (the cap, not immateriality)")
ck(all(e.get("materiality") != "ledger" for e in _sup5b.values()),
   "...keeping its true materiality, so the report cannot call it inconsequential")
# past the carry limit the COUNT itself is disclosed rather than the run going quiet
recs_huge = [{"park": f"H{i}", "__meta": {"source_file": "d.pdf", "doubts": [
    {"subject": f"H{i}", "question": f"which printed warehouse area is right on page {i}?"}]}}
    for i in range(CQ.MAX_DOUBT_CARRIED + 5)]
_huge = CQ.agent_doubt_questions(recs_huge)
ck(len(_huge) == CQ.MAX_DOUBT_CARRIED + 1
   and "further reading doubt" in _huge[-1]["question"],
   "past the carry limit the run discloses HOW MANY it did not list - never silence")

# --------------------------------------------------------------- 6. the exit-10 livelock
CONFLICT_SHOWN = {"conflict_id": "cf_shown", "field": "clearHeight",
                  "candidates": [{"label": "a", "value": "12 m"},
                                 {"label": "b", "value": "15 m"}], "default": "a"}
CONFLICT_LEDGER = {"conflict_id": "cf_ledger", "field": "someOpenColumn",
                   "candidates": [{"label": "a", "value": "X"},
                                  {"label": "b", "value": "Y"}], "default": "a"}
w2 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat2_"))
fd = {"cf_shown": {"pick": "unsure"}, "cf_ledger": {"pick": "unsure"}}
n, qs = RUN.unsure_pick_questions(w2, {}, [CONFLICT_SHOWN, CONFLICT_LEDGER], fd)
ck(len(qs) == 1 and qs[0]["field"] == "clearHeight",
   "only the material-field conflict becomes a broker question")
ck(n == 1, "the ledger-only one is RESOLVED, not merely dropped")
out = json.loads((w2 / "field_decisions.json").read_text(encoding="utf-8-sig"))
ck(out["cf_ledger"]["pick"] == "a" and "nor read by the matcher" in out["cf_ledger"]["reason"],
   "...to the precedence default, with the reason recorded")
ck("cf_shown" not in out,
   "the material conflict is left OPEN for the broker, not quietly resolved")
_sup2 = [e for e in (CQ.load_state(w2).get("suppressed") or {}).values()
         if e.get("kind") == "field_unsure"]
ck(len(_sup2) == 1, "the unasked conflict is recorded for the Gaps Report")
ck("'X'" in str(_sup2[0].get("if_unanswered")),
   "...naming the VALUE that shipped, not its 'a'/'b' label (a letter tells a broker nothing)")
# and the settled one never comes back: a second pass sees no 'unsure' left for it
fd2 = json.loads((w2 / "field_decisions.json").read_text(encoding="utf-8-sig"))
n2, qs2 = RUN.unsure_pick_questions(w2, {}, [CONFLICT_LEDGER], fd2)
ck((n2, qs2) == (0, []), "the resolved conflict does not re-open - no exit-10 livelock")
# a re-keyed conflict (clustering settles, ids move) must not leave a stale disclosure
# naming a conflict that no longer exists
CONFLICT_REKEYED = dict(CONFLICT_LEDGER, conflict_id="cf_ledger_v2")
RUN.unsure_pick_questions(w2, {}, [CONFLICT_REKEYED], {"cf_ledger_v2": {"pick": "unsure"}})
_ids2 = [i for i, e in (CQ.load_state(w2).get("suppressed") or {}).items()
         if e.get("kind") == "field_unsure"]
ck(len(_ids2) == 1, "a re-keyed conflict REPLACES its old disclosure, never doubles it")
# a broker answer still beats the suppression branch
w2b = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat2b_"))
_qid_led = CQ.qid("field_unsure", "cf_ledger", "someOpenColumn")
(w2b / "answers.json").write_text(json.dumps({_qid_led: "b"}), encoding="utf-8")
n3, _ = RUN.unsure_pick_questions(w2b, {}, [CONFLICT_LEDGER],
                                  {"cf_ledger": {"pick": "unsure"}})
out3 = json.loads((w2b / "field_decisions.json").read_text(encoding="utf-8-sig"))
ck(n3 == 1 and out3["cf_ledger"]["pick"] == "b" and "broker" in out3["cf_ledger"]["reason"],
   "an answer the broker DID give is honoured even on an immaterial field")

# --------------------------------------------------------------- 7. the disclosure
canonical = {
    "meta": {"client": "Test Client", "hero": {}, "sourceFiles": ["deck.pdf"]},
    "properties": [{"id": 1, "country": "GB", "park": "Alpha Park", "developer": "Dev",
                    "city": "Corby", "status": "Available", "photo": "data:,",
                    "warehouseArea": 10000, "areaUnit": "sq m"}],
    "pois": [], "regions": {},
}
report = DEL.gaps_report(canonical, "test-client", w)
ck("Noted, not put to you" in report,
   "the Gaps Report has a section for what was NOT asked")
ck("cover tint" in report,
   "...and it names the suppressed doubt, so nothing is silently dropped")
ck("the file as read" in report and "proceeds with: proceeds with" not in report,
   "...together with the value that shipped, without the doubled 'proceeds with'")
ck("**Alpha Park**: Alpha Park:" not in report,
   "the subject is not printed twice on one line")
ck("overrides.json" in report.split("## Noted, not put to you")[1].split("\n##")[0],
   "...and the section says HOW to change it, like every other Gaps section")
# THE MISLABEL. A material doubt that was not asked (headless, or past the cap) must NEVER
# be printed under "no effect on what the dashboard shows" - that is a false statement in a
# client-facing document, and it is the one thing that would make suppression dishonest.
w7 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat7_"))
CQ.note_suppressed(w7, [{"id": "q_h1", "kind": "agent_doubt", "materiality": "display",
                         "subject": "Beta Park",
                         "question": "which printed warehouse area is right?",
                         "if_unanswered": "proceeds with: the larger figure"}],
                   why=CQ.WHY_HEADLESS)
CQ.note_suppressed(w7, [{"id": "q_h2", "kind": "agent_doubt", "materiality": "ledger",
                         "subject": "Beta Park", "question": "the cover tint looks odd"}])
rep7 = DEL.gaps_report(canonical, "test-client", w7)
_head_mat = "## Noticed but not asked about"
_head_led = "## Noted, not put to you"
ck(_head_mat in rep7 and _head_led in rep7, "the two disclosure sections are separate")
_sec_mat = rep7.split(_head_mat)[1].split("\n## ")[0]
_sec_led = rep7.split(_head_led)[1].split("\n## ")[0]
ck("warehouse area" in _sec_mat and "warehouse area" not in _sec_led,
   "a MATERIAL unasked doubt sits under 'Noticed but not asked about'")
ck("cover tint" in _sec_led and "cover tint" not in _sec_mat,
   "...and only the genuinely immaterial one sits under 'no effect'")
ck("decide sensibly" in _sec_mat.lower(),
   "...and the material section says WHY it was not asked, in the broker's own terms")
ck("answers.json" in _sec_mat or "overrides.json" in _sec_mat,
   "...and how to act on it")
# an entry that has since been ANSWERED belongs in Clarifications, not here
w7b = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat7b_"))
CQ.emit(w7b, [{"id": "q_dual", "kind": "agent_doubt", "subject": "Gamma Park",
               "question": "which printed warehouse area is right?", "blocking": False}])
(w7b / "answers.json").write_text(json.dumps({"q_dual": "the larger one"}), encoding="utf-8")
CQ.ingest_answers(w7b)
CQ.note_suppressed(w7b, [{"id": "q_dual", "kind": "agent_doubt", "materiality": "display",
                          "subject": "Gamma Park", "question": "which area is right?"}])
rep7b = DEL.gaps_report(canonical, "test-client", w7b)
ck(rep7b.count("Gamma Park") == 1,
   "a doubt that was answered appears ONCE (in Clarifications), never in both sections")

# --------------------------------------------------------------- 8. wiring pins
RSRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")
ck("field_is_material(c.get(\"field\"))" in RSRC,
   "run.py gates value conflicts on the materiality test (not dead wiring)")
ck('work / "clarify_state.json"' in RSRC.split("_deliver_inputs = [")[1][:800],
   "clarify_state.json invalidates DELIVER - it is the only carrier of these two sections")
DSRC = (ROOT / "helpers" / "deliver.py").read_text(encoding="utf-8", errors="replace")
ck("suppressed" in DSRC, "deliver.py reads the suppressed record")
# THE HEADLESS BRANCH, executed rather than grepped: nothing else in the suite runs it.
w8 = pathlib.Path(tempfile.mkdtemp(prefix="cbre_mat8_"))
(w8 / "extract").mkdir(parents=True, exist_ok=True)
_hd = CQ.agent_doubt_questions([
    {"park": "Delta Park", "__meta": {"source_file": "deck.pdf", "doubts": [
        {"subject": "Delta Park", "question": "which printed warehouse area is right?"},
        {"subject": "Delta Park", "question": "the cover tint looks odd"}]}}])
CQ.note_suppressed(w8, [q for q in _hd if not CQ.is_material(q)], why=CQ.WHY_LEDGER)
CQ.note_suppressed(w8, [q for q in _hd if CQ.is_material(q)], why=CQ.WHY_HEADLESS)
_sup8 = CQ.load_state(w8).get("suppressed") or {}
ck(len(_sup8) == 2
   and {e["why_not_asked"] for e in _sup8.values()} == {CQ.WHY_LEDGER, CQ.WHY_HEADLESS},
   "the headless split records each doubt under the right reason")
ck("note_suppressed(work, [q for q in _hd if not _clarify.is_material(q)]" in RSRC
   and "why=_clarify.WHY_HEADLESS" in RSRC,
   "...and run.py's headless branch is wired to do exactly that")
# The drift guard above is a self-consistency check on `p.<field>`. It would NOT catch a
# future `const {postcode} = p` or `p['postcode']`, so assert no such read path exists: if
# one is ever added, this fails and the guard gets extended rather than quietly going blind.
# Scanned over the APP SCRIPT ONLY (from the PROPS injection marker on), because the bundled
# minified Leaflet before it uses `p` as an ordinary local and would drown the signal - the
# same scoping _common.canonical_property_fields uses, and for the same reason.
_app = tpl[tpl.find(C.DATA_MARKERS["PROPS"]):] if C.DATA_MARKERS.get("PROPS") in tpl else tpl
_norm_app = re.sub(r"\s+", "", _app)
ck(not re.search(r"(?:const|let|var)\{[A-Za-z_,]*\}=p[;,).]", _norm_app),
   "the app script never destructures fields off a property (the guard would miss it)")
_brackets = [m for m in re.findall(r"p\[['\"][^'\"]{1,40}['\"]\]", _norm_app)]
ck(not _brackets,
   f"the app script reads no property field by a literal bracket key {_brackets[:3]}")

print("\nCLARIFY MATERIALITY TEST: " + ("FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
