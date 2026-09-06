#!/usr/bin/env python3
"""adjudicate_auto_pairs_test.py - an AUTO merge that disagrees about its own identity is
offered for confirmation, and an explicit 'different' verdict splits it.

THE HOLE. `match.grey_pairs` enumerates the ambiguous middle for adjudication and NOTHING
enumerated the auto tier, so an auto merge was offered to nobody. That is the failure this
module's own docstrings call invisible to the reader AND unrecoverable: nothing in the
pipeline can split a merged property afterwards, the coverage dedupe gate needs two cards
identical on park, city, developer and area, and `gate_runner.py coverage`'s A14b code check
needs the contributing records to state postal codes and asks the FINISHED dataset. The
postal-code veto at the top of `_cross_source_auto` closed the worst case; it did not close
the class. The near-identical-key fuzzy tail merges on `city|developer|park` scoring >= 88 and
that key CANNOT SEE a unit name, a building name or a street - so two units of one park fused
into one card while the other unit dropped off the longlist.

THREE THINGS HAD TO BE TRUE TOGETHER, and each is worthless without the others:
  1. SURFACING - `match.auto_pairs` enumerates them, `run.py` emits them under
     `confirm_pairs` and drops them in round two so a settled pair is never re-asked;
  2. A RESTRICTED SET - only pairs where an identity field MATERIALLY disagrees. Without the
     restriction the adjudication exit becomes noise, noise gets skimmed, and a skimmed exit
     is worse than not asking at all;
  3. A CONSUMER - `same_property` ignored recorded decisions entirely for an auto pair, so
     surfacing alone changed NOTHING. An explicit 'different' verdict now downgrades it.

AND THE DIRECTION IS ONE-WAY, which is what makes the changed contract safe: only the exact
verdict 'different' splits an auto pair. An absent verdict, no decisions file, 'same',
'unsure' or junk all leave the merge as the matcher made it, so offline behaviour is
unchanged. The result can only ever be an over-SPLIT - two similar-looking cards in front of
a reader who can see and query them - never a new fusion.

Offline, pure Python. No build, no network. Run: python evals/adjudicate_auto_pairs_test.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import match as M  # noqa: E402

FAILS: list = []
RSRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")
MDOC = (ROOT / "reference" / "matching.md").read_text(encoding="utf-8", errors="replace")
STEPS = (ROOT / "reference" / "agentic-steps.md").read_text(encoding="utf-8", errors="replace")

# EVERY POSTAL CODE HERE IS INVENTED, and the shapes are mixed on purpose - the same
# discipline `_stated_postcode` and evals/overmerge_guard_test.py state at the top. A real
# national code quoted as THE example is how a country-specific assumption gets read back in.
BASE = dict(city="Northport", developer="Kestrel Estates", park="Kestrel Reach",
            warehouseArea=12000, areaUnit="sq m")


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def r(src: str, **kw) -> dict:
    d = {"__meta": {"source_file": src}}
    d.update(BASE)
    d.update(kw)
    return d


# --------------------------------------------------------------------------- #
def surfaced_only_when_material() -> None:
    print("1. an auto pair is surfaced ONLY when an identity field materially disagrees")
    a = r("tracker.xlsx", unit="Unit 1")
    b = r("brochure.pdf", unit="Unit 7", warehouseArea=12100)
    ck(M.pair_class(a, b) == "auto",
       f"the fixture pair really IS auto (the fuzzy tail claims it) ({M.pair_class(a, b)})")
    ck(M.identity_disagreements(a, b) == ["unit"],
       f"...and it disagrees on the UNIT designator ({M.identity_disagreements(a, b)})")
    got = M.auto_pairs([a, b])
    ck(len(got) == 1, f"so it is SURFACED ({len(got)})")
    ck(got and got[0]["disagrees_on"] == ["unit"],
       "the entry names WHAT they contradict each other about, so the reviewer is told rather "
       "than asked to spot it")
    ck(got and got[0]["auto"] is True,
       "...and is flagged as an already-merged pair, not a merge candidate")
    ck(got and sorted(got[0]) == sorted(["pair_id", "a_idx", "b_idx", "a", "b", "auto",
                                         "disagrees_on"]),
       f"...in the same shape grey_pairs emits, plus the two auto-only keys "
       f"({sorted(got[0]) if got else []})")

    # THE OTHER HALF, and the one that keeps the exit worth reading
    c = r("brochure2.pdf", unit="Unit 1", warehouseArea=12050)
    ck(M.pair_class(a, c) == "auto" and M.identity_disagreements(a, c) == [],
       "an auto pair that AGREES on identity has no disagreement")
    ck(M.auto_pairs([a, c]) == [],
       "...and is NOT surfaced - an exit listing every auto pair is noise, and noise is worse "
       "than not asking")

    print("\n2. what counts as MATERIAL, class by class")
    # party: no party name in common
    p1 = r("t.xlsx", developer="Kestrel Estates", park="Kestrel Reach")
    p2 = r("b.pdf", developer="Falcon Developments", park="Kestrel Reach")
    ck("party" in M.identity_disagreements(p1, p2),
       f"two developers with no token in common DISAGREE ({M.identity_disagreements(p1, p2)})")
    ck(M.identity_disagreements(p1, r("b.pdf", developer="Kestrel Estates Limited",
                                      park="Kestrel Reach")) == [],
       "...while a legal-suffix variant of the same name AGREES")
    # party is POOLED across the party fields (I12: which field a name sits in is an accident)
    ck(M.identity_disagreements(
        r("t.xlsx", developer="Kestrel Estates", landlord="Kestrel Estates"),
        r("b.pdf", developer="Kestrel Estates", landlord="Falcon Trust")) == [],
       "a pair naming the same developer and two different landlords still SHARES a party "
       "token, so it is not surfaced - pooling keeps precision up")
    # name: no distinctive scheme token in common
    ck("name" in M.identity_disagreements(r("t.xlsx", park="Alpha Court"),
                                          r("b.pdf", park="Beta House")),
       "two schemes with disjoint distinctive tokens DISAGREE")
    ck(M.identity_disagreements(
        r("t.xlsx", park="Unit 1, Kestrel Reach, Halston Industrial Estate"),
        r("b.pdf", park="Kestrel Reach")) == [],
       "...while a scheme name CONTAINED in a longer address string AGREES - which it must, "
       "since containment is exactly what the auto tier's containment branch merges on")
    # unit: a DESIGNATOR, compared whole, digits kept
    ck(M.identity_disagreements(a, r("b.pdf", unit="Unit 10")) == ["unit"],
       "'Unit 1' against 'Unit 10' DISAGREES - a plain substring test would have got this "
       "wrong, so the comparison is token-subset")
    ck(M.identity_disagreements(a, r("b.pdf", unit="Unit 1, Kestrel Reach")) == [],
       "...and a designator quoted inside a longer string AGREES")
    ck(M._ident_bag(a, ("unit",), set()) == set(),
       "the DISTINCTIVE-token bag is structurally BLIND to 'Unit 1' ('unit' is generic, a bare "
       "digit is dropped), which is exactly why the unit class needs its own comparison")
    # street
    ck("street" in M.identity_disagreements(r("t.xlsx", street="Sallow Road"),
                                            r("b.pdf", street="Harrier Way")),
       "two different streets DISAGREE")
    ck(M.identity_disagreements(r("t.xlsx", street="Sallow Road"),
                                r("b.pdf", street="Sallow Rd")) == [],
       "...while an abbreviation of the same street AGREES (the stop-word strip does that)")

    print("\n3. a ONE-SIDED absence is never a disagreement")
    for label, kw_a, kw_b in (("developer", {"landlord": "Falcon Trust"}, {}),
                              ("unit", {"unit": "Unit 1"}, {}),
                              ("street", {"street": "Sallow Road"}, {})):
        ck(M.identity_disagreements(r("t.xlsx", **kw_a), r("b.pdf", **kw_b)) == [],
           f"one side silent on {label} -> no disagreement (a gap is only evidence when both "
           f"sides spoke)")
    ck(M.identity_disagreements(r("t.xlsx", unit="tbd"), r("b.pdf", unit="Unit 7")) == [],
       "a SENTINEL is absence, not a value that disagrees with everything")

    print("\n4. the two classes deliberately NOT tested here")
    # the postal code: its veto means such a pair is never 'auto' at all
    q1 = r("t.xlsx", postcode="QX41 7ZP")
    q2 = r("b.pdf", postcode="QX52 3BH")
    ck(M.pair_class(q1, q2) == "forbidden",
       f"two DIFFERENT stated codes make the pair forbidden, not auto "
       f"({M.pair_class(q1, q2)})")
    ck(M.auto_pairs([q1, q2]) == [],
       "...so a code conflict can never appear in the surfaced set - the veto owns that case, "
       "and re-listing it would read as though the veto were optional")
    ck("postcode" not in str(M._IDENT_CLASSES) and "postalCode" not in str(M._IDENT_CLASSES),
       "the code is not one of the identity classes")
    # the area: every auto branch already vetoes a material size gap
    ck(M.pair_class(r("t.xlsx", warehouseArea=12000),
                    r("b.pdf", warehouseArea=30000)) == "forbidden",
       "a >15% size gap is forbidden, so anything reaching 'auto' already agrees on size "
       "within the tier's own tolerance")
    ck("warehouseArea" not in str(M._IDENT_CLASSES),
       "...so the area is not an identity class either")
    # place fields carry no identity (I9/I12)
    for f in ("city", "region", "district", "country"):
        ck(f not in str(M._IDENT_CLASSES), f"{f} is not an identity class (a place carries no "
                                           f"identity - I9)")


def the_bag_is_pinned() -> None:
    print("\n5. the identity bag is PINNED to the grey filter's, not merely similar")
    # `_ident_bag` deliberately does NOT call `_grey_bag`: that function's caller set is a
    # load-bearing invariant (evals/grey_prefilter_test.py asserts it by call graph - the
    # place-stripped tokeniser must stay unreachable from the deterministic tiers, because
    # SHRINKING a token set can only ADD subset relations and inside the auto tier that means
    # a NEW auto-merge). So it reads the same CONSTANTS, and the two are held identical here.
    recs = [r("t.xlsx", park="Unit 1, Kestrel Reach, Halston Industrial Estate",
              street="Sallow Road", developer="Kestrel Estates Holdings"),
            r("b.pdf", park="Kestrel Reach", street="Harrier Way North",
              landlord="Falcon Group", postcode="QX41 7ZP"),
            r("c.pdf", park="tbd", developer="", scheme="Alpha Court Business Park")]
    place = M._grey_place_tokens(recs[0], recs[1])
    same = all(M._ident_bag(rec, fields, place) == M._grey_bag(rec, fields, place)
               for rec in recs
               for fields in (M._GREY_IDENT_FIELDS, M._GREY_PARTY_FIELDS)
               + tuple(f for _l, f in M._IDENT_CLASSES))
    ck(same, "_ident_bag returns exactly _grey_bag's set over real-shaped values, so the two "
             "cannot drift while looking alike")
    src = (HELPERS / "match.py").read_text(encoding="utf-8")
    i = src.find("def identity_disagreements(")
    j = src.find("\ndef ", i + 1)
    ck("_grey_bag(" not in src[i:j],
       "...and it does NOT call _grey_bag, which would widen a whitelist that is stricter "
       "than the invariant it guards")


def the_consumer() -> None:
    print("\n6. THE LOAD-BEARING PART: an explicit 'different' verdict downgrades an auto pair")
    a = r("tracker.xlsx", unit="Unit 1")
    b = r("brochure.pdf", unit="Unit 7", warehouseArea=12100)
    pid = M.pair_id(a, b)
    ck(M.same_property(a, b) is True,
       "with no decisions at all the auto pair merges - today's behaviour, unchanged")
    ck(M.same_property(a, b, {}) is True, "an empty decisions map merges it too")
    ck(M.same_property(a, b, {pid: {"verdict": "different", "reason": "two units"}}) is False,
       "an explicit 'different' SPLITS it - without this, surfacing changed nothing at all")
    ck(M.same_property(a, b, {pid: "different"}) is False,
       "...and the bare-string verdict shape works, exactly as it does for a grey pair")
    for v in ("same", "unsure", "maybe", "", None, 0, ["different"], {"verdict": "nope"}):
        ck(M.same_property(a, b, {pid: v}) is True,
           f"...while {ascii(str(v))} leaves the merge alone - ONLY 'different' acts")
    ck(M.same_property(a, b, {"someotherpair": "different"}) is True,
       "a 'different' against ANOTHER pair id does not touch this one")

    print("\n7. it reaches CLUSTERING, and only in the split direction")
    recs = [a, b]
    ck([len(cl) for cl in M.dedupe(recs)] == [2],
       f"offline the two records are ONE cluster ({[len(cl) for cl in M.dedupe(recs)]})")
    ck([len(cl) for cl in M.dedupe(recs, {pid: "different"})] == [1, 1],
       f"a recorded 'different' splits the cluster in two "
       f"({[len(cl) for cl in M.dedupe(recs, {pid: 'different'})]})")
    ck(M.dedupe(recs) == M.dedupe(recs, None),
       "dedupe(records) == dedupe(records, None) - the offline path is untouched")

    print("\n8. a structural blocker still beats every verdict, in BOTH directions")
    f1 = r("t.xlsx", postcode="QX41 7ZP")
    f2 = r("b.pdf", postcode="QX52 3BH")
    fpid = M.pair_id(f1, f2)
    ck(M.same_property(f1, f2, {fpid: "same"}) is False,
       "a forbidden pair does NOT merge on 'same' (unchanged - the blocker beats the LLM)")
    ck(M.same_property(f1, f2, {fpid: "different"}) is False,
       "...and 'different' on a forbidden pair is simply redundant")
    g1 = r("t.xlsx", park="Alpha Court", warehouseArea=12000, lat=52.0, lng=-0.7)
    g2 = r("b.pdf", park="Beta House", warehouseArea=12000, lat=52.02, lng=-0.72,
           developer="")
    if M.pair_class(g1, g2) == "grey":
        gpid = M.pair_id(g1, g2)
        ck(M.same_property(g1, g2, {gpid: "different"}) is False
           and M.same_property(g1, g2, {gpid: "same"}) is True,
           "a GREY pair still merges on 'same' and splits on 'different' - only the grey tier "
           "can be merged BY a verdict")
    else:
        ck(True, f"(grey fixture classified {M.pair_class(g1, g2)}; the grey branch is pinned "
                 f"in qa/grey evals)")


def the_payload() -> None:
    print("\n9. run.py emits it, and drops it in round two")
    ck("auto_confirm = _mm.auto_pairs(_all_recs)" in RSRC,
       "run.py enumerates the auto pairs beside the grey ones")
    ck('_cand["confirm_pairs"]' in RSRC,
       "...and emits them under a NEW key in the adjudication payload")
    ck('"disagrees_on": g["disagrees_on"]' in RSRC,
       "...carrying the disagreement classes through to the reviewer")
    ck("if auto_confirm:" in RSRC,
       "...only when there ARE any, so a corpus with none produces a byte-identical file")
    i = RSRC.find('for _k in ("pairs", "verify_pairs"')
    drop = RSRC[i:i + 300] if i != -1 else ""
    ck("confirm_pairs" in drop and "confirm_instructions" in drop,
       f"the round-two key-drop list drops BOTH confirm keys, so a settled pair is never "
       f"re-asked {ascii(drop[:110])}")
    ck("_settled_clusters(clusters, grey + auto_confirm, md, _all_recs)" in RSRC,
       "an unanswered surfaced auto pair also withholds its cluster's value conflicts while "
       "the pairs round is open - its verdict would re-key them (B20)")
    ck("settled_pairs\"] = len(grey) + len(auto_confirm)" in RSRC,
       "...and round two reports both as settled")

    print("\n10. the adjudicator prompt text no longer says false things")
    ck("hard-BLOCKED the impossible ones (developer disagreement" not in RSRC,
       "the claim that a developer disagreement is HARD-BLOCKED is gone - it has been false "
       "since landlord and developer became separate fields")
    # matched in two halves: the literal is wrapped across source lines
    ck("A DEVELOPER DISAGREEMENT IS NOT " in RSRC
       and "HARD-BLOCKED: landlord and developer are separate fields now" in RSRC,
       "...and the prompt now says so explicitly, because such a pair is sent TO the reviewer")
    ck("AN ABSENT PARTY IS NOT AGREEMENT" in RSRC,
       "...and that two absent parties are not an agreement (the auto tier requires the "
       "developer STATED on both sides and equal)")
    ck("two DIFFERENT stated \"" not in RSRC and "postal codes" in RSRC,
       "...and it names what IS hard-blocked: a >15% size conflict or two differing codes")
    i = RSRC.find('_cand["confirm_instructions"]')
    ci = RSRC[i:i + 2200] if i != -1 else ""
    ck("ALREADY MERGED" in ci,
       "the confirm instructions say the pairs are already merged, not merge candidates")
    ck("leaving the pair out" in ci and "leaves the merge exactly as the matcher made it" in ci,
       "...that omission is SAFE, so an ignored key can never change behaviour")
    ck("never to be safe" in ci,
       "...and that 'different' is for confidence, never for caution")


def the_docs() -> None:
    print("\n11. the documented contract moved with the code")
    ck("confirm_pairs" in MDOC, "matching.md documents `confirm_pairs`")
    ck("NO LONGER AUTHORITATIVE IN BOTH DIRECTIONS" in MDOC,
       "...and says plainly that the auto tier's contract CHANGED")
    ck("These are the only pairs in `match_candidates.json`" not in MDOC,
       "...and no longer claims the grey pairs are the only pairs in the candidates file")
    for cls in ("party", "name", "unit", "street"):
        ck(f"`{cls}`" in MDOC, f"matching.md names the `{cls}` disagreement class")
    ck("one-way and explicit-only" in MDOC,
       "...and that only the exact verdict 'different' acts, so offline is unchanged")
    ck("confirm_pairs" in STEPS and "authoritative in one" in STEPS,
       "agentic-steps.md carries the same changed contract")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    surfaced_only_when_material()
    the_bag_is_pinned()
    the_consumer()
    the_payload()
    the_docs()
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"ADJUDICATE AUTO PAIRS TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ADJUDICATE AUTO PAIRS TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
