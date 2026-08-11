"""Source authority (B47) + the override/clustering coherence regression (B48).

Two behaviours are locked down here, both of which can SILENTLY change what ships on a
client's longlist:

  B47  The broker's source-authority answer is CONSUMED. Before this, the pipeline asked a
       blocking question ("brochures describe 13, the tracker lists 12 - which is guiding?"),
       recorded the answer, and then ignored it: `clarify.apply_answers` only ever read the
       unit questions, and no exclusion mechanism existed anywhere. A broker answered
       "tracker" and still received the union.

  B48  work/overrides.json reaches the PAIR ENUMERATION, not just the merge. run.py clusters
       a second time to decide which grey pairs to ask about, and it used to read the raw
       extract records while merge.main applied the overrides first. So a correction whose
       whole purpose was to make two records cluster changed the merged output but NOT which
       pairs were asked about: the same building shipped twice under two names, the run
       exited 0, and every gate passed. Observed live on a 12-property UK run.

Run: python evals/source_authority_test.py
"""
import json
import re
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))

import clarify as CQ      # noqa: E402
import match as MM        # noqa: E402
import merge as MG        # noqa: E402

FAILURES = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def rec(source_file, **fields):
    r = {"__meta": {"source_file": source_file,
                    "source_type": Path(source_file).suffix.lstrip(".") or "pdf"}}
    r.update(fields)
    return r


# --------------------------------------------------------------- normalise_authority
print("normalise_authority - a chat answer is free-ish text, not an enum:")
for answer, want in [
    ("tracker", "tracker"), ("the tracker", "tracker"), ("Tracker (Excel)", "tracker"),
    ("excel", "tracker"), ("the spreadsheet", "tracker"),
    ("brochures", "brochures"), ("the brochures", "brochures"), ("PDF decks", "brochures"),
    ("the union of both", "union"), ("both", "union"), ("union", "union"),
    ("", "union"), (None, "union"), ("banana", "union"),
]:
    got = CQ.normalise_authority(answer)
    check(f"{answer!r} -> {want}", got == want, f"got {got!r}")

check("an UNRECOGNISED answer degrades to the union, never to a drop",
      CQ.normalise_authority("who knows") == CQ.AUTHORITY_UNION)
check("settled_authority on an empty answers map is the union",
      CQ.settled_authority({}) == CQ.AUTHORITY_UNION)
check("settled_authority reads the durable AUTHORITY_QID",
      CQ.settled_authority({CQ.AUTHORITY_QID: "tracker"}) == "tracker")

# THE ID BUG: the old id embedded the counts that prompted the question
# (qid("source_authority", f"brochures{a}|tracker{b}")), so the moment clustering merged a
# pair the id changed and the broker's answer was orphaned - which qid()'s own docstring
# forbids ("keyed on the ambiguity itself, NEVER on a value").
check("the authority question id is STABLE (not keyed on the counts that prompted it)",
      CQ.AUTHORITY_QID == CQ.qid("source_authority", "property count"))

# --------------------------------------------------------------- record_family
print("\nrecord_family - keyed on the source SUFFIX, so it generalises to any client:")
check("an .xlsx record is the tracker family",
      CQ.record_family(rec("Warehouse Availability - Temu UK.xlsx")) == "tracker")
check("a .csv record is the tracker family", CQ.record_family(rec("avail.csv")) == "tracker")
check("a .pdf record is the brochures family", CQ.record_family(rec("Stoke 439.pdf")) == "brochures")
check("a .pptx record is the brochures family", CQ.record_family(rec("deck.pptx")) == "brochures")
check("an .msg email belongs to NEITHER family (so it can never be excluded)",
      CQ.record_family(rec("offer.msg")) == "")

# --------------------------------------------------------------- extras + filter
print("\nauthority_extras / apply_source_authority on SETTLED clusters:")
both = [rec("tracker.xlsx", park="Alpha Park", city="Corby", warehouseArea=100000),
        rec("alpha.pdf", park="Alpha Park", city="Corby", warehouseArea=95000)]
trk_only = [rec("tracker.xlsx", park="Beta Park", city="Corby", warehouseArea=200000)]
broc_only = [rec("gamma.pdf", park="Gamma Park", city="Corby", warehouseArea=300000)]
email_only = [rec("offer.msg", park="Delta Park", city="Corby", warehouseArea=400000)]
clusters = [both, trk_only, broc_only, email_only]

extras = MG.authority_extras(clusters)
check("a cluster evidenced by BOTH sources is not an extra",
      not any("Alpha" in n for ns in extras.values() for n in ns))
check("the tracker-only cluster is listed as a tracker extra",
      any("Beta" in n for n in extras.get("tracker", [])), str(extras))
check("the brochure-only cluster is listed as a brochures extra",
      any("Gamma" in n for n in extras.get("brochures", [])), str(extras))
check("extras are NAMED, not counted (the broker must choose knowingly)",
      all(isinstance(n, str) and n.strip() for ns in extras.values() for n in ns))

kept, dropped = MG.apply_source_authority(clusters, "tracker")
names = [d["name"] for d in dropped]
check("authority=tracker keeps the both-source cluster", both in kept)
check("authority=tracker keeps the tracker-only cluster", trk_only in kept)
check("authority=tracker DROPS the brochure-only cluster",
      broc_only not in kept and any("Gamma" in n for n in names), str(names))
check("authority=tracker KEEPS an email-only cluster (excluded only on positive evidence)",
      email_only in kept)
check("every dropped cluster carries a name, its source files and a why",
      all(d.get("name") and d.get("source_files") and d.get("why") for d in dropped))

kept_b, dropped_b = MG.apply_source_authority(clusters, "brochures")
check("authority=brochures DROPS the tracker-only cluster",
      trk_only not in kept_b and any("Beta" in d["name"] for d in dropped_b))
check("authority=brochures keeps the brochure-only cluster", broc_only in kept_b)

for noop in ("union", "", None, "banana"):
    k, d = MG.apply_source_authority(clusters, noop)
    check(f"authority={noop!r} is a NO-OP (unanswered runs stay byte-identical)",
          k == clusters and d == [])

# FAIL OPEN. A mis-detected family must never produce an empty dashboard.
only_brochures = [broc_only, [rec("x.pdf", park="Eps", city="Corby", warehouseArea=1)]]
k, d = MG.apply_source_authority(only_brochures, "tracker")
check("an authority that matches NOTHING keeps everything (fail open, never an empty deck)",
      k == only_brochures and d == [])

# A DISAGREEMENT NEEDS TWO SOURCES. On a single-family corpus every cluster is trivially
# "evidenced by only one family", which is not a discrepancy - there is no second source that
# could have listed it. Asking would stop the broker to arbitrate between one source and
# nothing. Regression: this fired on cowork_sim's 4-deck, no-tracker corpus and left the run
# stuck at an unanswerable exit 13.
print("\nSingle-source corpus - there is nothing to arbitrate:")
brochures_only = [broc_only, [rec("x.pdf", park="Eps Park", city="Corby", warehouseArea=1)]]
check("a brochure-ONLY corpus yields no extras (and so asks nothing)",
      MG.authority_extras(brochures_only) == {}, str(MG.authority_extras(brochures_only)))
check("...and therefore generates no question",
      CQ.source_authority_questions(MG.authority_extras(brochures_only)) == [])
tracker_only_corpus = [trk_only, [rec("t2.xlsx", park="Zeta", city="Corby", warehouseArea=2)]]
check("a tracker-ONLY corpus yields no extras either",
      MG.authority_extras(tracker_only_corpus) == {})
check("a MIXED corpus still reports its genuine extras",
      MG.authority_extras(clusters) != {})

print("\nsource_authority_questions - only when it still matters, and it NAMES the options:")
check("no extras -> no question at all", CQ.source_authority_questions({}) == [])
check("no extras (empty lists) -> no question",
      CQ.source_authority_questions({"tracker": [], "brochures": []}) == [])
q = CQ.source_authority_questions(extras)
check("a real discrepancy asks exactly ONE question", len(q) == 1, str(len(q)))
if q:
    qq = q[0]
    check("the question is put to the BROKER", qq["asked_of"] == "broker")
    check("the question TEXT names the options at stake (not just a count)",
          "Gamma" in qq["question"] and "Beta" in qq["question"], qq["question"])
    check("the machine-readable extras ride along for the orchestrator",
          qq.get("only_in_brochures") and qq.get("only_in_tracker"))
    check("unanswered is documented as shipping the union",
          "union" in qq["if_unanswered"].lower())
    check("the question uses the stable id", qq["id"] == CQ.AUTHORITY_QID)

# --------------------------------------------------------------- B48 regression
print("\nB48 - an override must reach the PAIR ENUMERATION, not just the merge:")
# Two records for ONE building. They cluster only once the city agrees - exactly the live
# TEMU case (tracker said the market 'Doncaster', the brochure said the village 'Harworth').
a = rec("deck.pdf", park="Central A1[M] 785", city="Harworth", developer="Panattoni",
        warehouseArea=734636, clearHeight="18", loadingDocks="100")
a["__meta"]["page_no"] = 2
b = rec("tracker.xlsx", park="Panattoni Doncaster 770, Blyth Road, Harworth", city="Doncaster",
        landlord="Panattoni", warehouseArea=783309.0, clearHeight="18 m", loadingDocks="100")

check("BEFORE the correction the pair is not even a candidate",
      MM.pair_class(a, b) == "no", MM.pair_class(a, b))

with tempfile.TemporaryDirectory() as td:
    ovp = Path(td) / "overrides.json"
    ovp.write_text(json.dumps([{
        "id": "ov-001",
        "where": {"source_file": "deck.pdf", "page_no": 2},
        "set": {"city": "Doncaster"},
        "why": "the brochure names the village, the tracker names the market",
    }]), encoding="utf-8")
    ovs, errs = MG.load_overrides(ovp)
    check("the fixture override parses", len(ovs) == 1 and not errs, str(errs))
    recs = [a, b]
    MG.apply_overrides(recs, ovs)

check("AFTER the correction the pair IS a grey candidate the broker gets asked about",
      MM.pair_class(a, b) == "grey", MM.pair_class(a, b))
check("grey_pairs surfaces it, so the enumeration can emit it",
      any(g["pair_id"] for g in MM.grey_pairs([a, b])))

# Structural guard: the functional check above passes even if run.py never calls
# apply_overrides, because this test applies it by hand. THIS is what catches the real bug -
# that run.py's own enumeration path applies the overrides BEFORE it clusters.
src = (HELPERS / "run.py").read_text(encoding="utf-8")
i_apply = src.find("_merge.apply_overrides(_all_recs")
i_grey = src.find("_mm.grey_pairs(_all_recs)")
i_dedupe = src.find("_mm.dedupe(_all_recs")
check("run.py applies overrides in its enumeration path", i_apply != -1)
check("run.py applies them BEFORE grey_pairs", i_apply != -1 and 0 < i_apply < i_grey,
      f"apply@{i_apply} grey@{i_grey}")
check("run.py applies them BEFORE dedupe", i_apply != -1 and 0 < i_apply < i_dedupe,
      f"apply@{i_apply} dedupe@{i_dedupe}")
check("run.py no longer asks source authority from RAW RECORD COUNTS",
      not re.search(r"source_authority_questions\(\s*\{\s*[\"']brochures[\"']", src))
check("run.py asks it from settled clusters via authority_extras",
      "_merge.authority_extras(clusters)" in src)
check("run.py applies the settled answer to its own clusters too",
      "_merge.apply_source_authority(" in src)

# --------------------------------------------------------------- disclosure
print("\nDisclosure - an exclusion must never be silent:")
gaps = (HELPERS / "deliver.py").read_text(encoding="utf-8")
check("the Gaps Report has an excluded-options section",
      'meta.get("excluded")' in gaps and "Options excluded" in gaps)
check("merge carries the exclusions into canonical meta",
      'meta["excluded"] = EXCLUDED' in (HELPERS / "merge.py").read_text(encoding="utf-8"))

print()
if FAILURES:
    print(f"SOURCE AUTHORITY TEST: FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("SOURCE AUTHORITY TEST: PASS (answer consumed, exclusions disclosed, "
      "overrides reach the pair enumeration)")
