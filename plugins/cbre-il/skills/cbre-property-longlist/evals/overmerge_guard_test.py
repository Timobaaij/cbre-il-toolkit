#!/usr/bin/env python3
"""overmerge_guard_test.py - the AUTO-TIER over-merge guards. (A12, A12b, A13)

An auto-merged pair is the one verdict in this skill that NOBODY can appeal. Only GREY
pairs are enumerated for adjudication (`grey_pairs`), so an auto-tier mistake fuses two
properties into one blended record and offers it to no one: the survivor is a blend of two
buildings' figures, each individually sourced and traceable, and the other building is gone
from the longlist.

TWO CLAIMS THIS FILE USED TO MAKE ARE FALSE AND ARE CORRECTED HERE.

  * "the coverage dedupe gate blocks over-SPLITS, so a demotion is recoverable". That gate
    fires ONLY on two cards IDENTICAL in park, city, developer AND warehouse area. Every
    fixture below that gets demoted differs on at least one of the four BY CONSTRUCTION
    (Alpha Court vs Beta House; 'Unit 3, Kestrel Reach, ...' vs 'Kestrel Reach'; 120000 vs
    121500), so the gate cannot see a single one of them. The gate route is real for exactly
    one shape - a typo-split, where one building is quoted twice and agrees on all four -
    and nowhere else. What actually makes the split the better error is that two
    similar-looking cards are IN FRONT OF THE READER while a fusion is shown to nobody.
  * "no gate anywhere looks for an over-merge". `gate_runner.py coverage` (A14b) now blocks
    a property whose contributing records state two DIFFERENT postal codes. It is a narrow
    net, not a verifier: it needs those records to state codes at all, so it is inert in a
    market that quotes none, it cannot see a fusion of records that agree on the code or
    state none, and it asks the FINISHED dataset - it catches a fusion rather than
    preventing one.

The holes this file pins:

  A12 - a POSTAL CODE was read by the recall pre-filter's identity tokens and NOWHERE ELSE.
        No auto path and no forbidden path touched it, so two buildings on separate estates
        a few hundred metres apart, with near-identical floor areas and no contradicting
        party name, cleared the coordinate net and merged. Two DIFFERING STATED codes are
        now a hard blocker in BOTH tiers.
  A12b - A12 reached only TWO of the four auto paths (coord net, containment). Because
        `pair_class` tests auto BEFORE forbidden, the ONE-PARK-MISSING branch and the
        FUZZY-KEY TAIL claimed their pairs first and the forbidden tier's identical test
        never ran, so those two paths FUSED across differing codes - at the clustering step,
        not merely the tiering step. Sections 6b and 7 pinned that as a current fact; they
        now assert the opposite. The veto is ONE guard at the TOP of `_cross_source_auto`,
        so the property is structural: there is no branch to bypass it in.
  A13 - `_known_dev` returns "" for an unknown developer, and two auto branches read
        `not da or not db or da == db`, so two ABSENCES passed as an agreement. Two records
        that name no party at all are not two agreeing parties; they are no evidence. Both
        branches now require the developer STATED on both sides and equal, which is the
        shape the one-park-missing branch already used (audit S2-8). Note the implemented
        rule is WIDER than the declared one: both-stated-and-equal also demotes a ONE-SIDED
        absence (section 4 pins it), which is kept deliberately.

THE COST OF THE CODE VETO IS NOT ZERO, AND SECTION 1 PINS IT. A pair the veto rejects lands
in `forbidden`, and a forbidden pair can never be merged by ANY verdict - `same_property`
returns False before `decisions` is read. So one building quoted with a unit-level code on
one side and an estate-level code on the other is PERMANENTLY unmergeable and ships as two
cards. Accepted, for the reader-visibility reason above, and recorded so it is a decision.

THE TIER ORDER IS THE TRAP THIS FILE EXISTS TO GUARD. `pair_class` tests
`_cross_source_auto` BEFORE `_cross_source_forbidden`, deliberately (a pair the
deterministic matcher already merges must keep merging). A veto added ONLY to the forbidden
tier is therefore a NO-OP for exactly the pairs that reach the auto tier - the pairs that
need blocking. Section 7 asserts the veto inside the auto tier itself, and that it is a
SINGLE top-of-function guard rather than a per-branch repetition, so neither regression
can come back green.

Every fixture PINS THE CARRYING SIGNAL as a positive control: each auto path is isolated so
that no OTHER auto path can rescue the pair and make the assertion vacuous. The fuzzy-key
tail in particular scores 100 on any pair whose match_key token set is a subset of the
other's, which would quietly defeat a careless fixture.

Names, codes and formats here are invented and deliberately mixed (a letters-and-digits
code, an all-digit code, a digits-then-letters code) - the guard must hold for ANY country's
format and stay inert where a country's records carry no codes at all, which section 5
asserts by disabling the reader and re-deriving every verdict.

Offline, pure, no network, no work dir. Run: python evals/overmerge_guard_test.py"""
from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import match as M  # noqa: E402

CITY = "Northport"
DEV = "Ardent Estates"


def r(src, park, city=CITY, dev=None, area=None, unit="sq ft",
      lat=None, lng=None, **extra):
    """One record. `dev=None` means the source NAMED NO PARTY - the ordinary shape of a
    brochure that never prints the developer, and the case A13 is about."""
    rec = {"park": park, "city": city, "developer": dev, "areaUnit": unit,
           "__meta": {"source_file": src}}
    if area is not None:
        rec["warehouseArea"] = area
    if lat is not None:
        rec["lat"], rec["lng"] = lat, lng
    rec.update(extra)
    return rec


# ---- the coordinate-net fixture -------------------------------------------------------
# Two pins ~130 m apart (inside COORD_MERGE_KM) with near-identical areas: exactly the
# "one park spans 100-250 m" shape the coord net was written for - and exactly the shape
# two separate estates either side of a boundary also have. The parks are DISJOINT on
# their distinctive tokens and the fuzzy key sits below MATCH_THRESHOLD, so the coord net
# is the ONLY auto path either record can reach (asserted in section 0).
LAT_A, LNG_A = 52.41000, -1.28000
LAT_B, LNG_B = 52.41100, -1.28060


def coord_pair(pc_a=None, pc_b=None, dev_a=None, dev_b=None):
    a = r("tracker.xlsx", "Alpha Court", dev=dev_a, area=120000,
          lat=LAT_A, lng=LNG_A, **({"postcode": pc_a} if pc_a is not None else {}))
    b = r("brochure.pdf", "Beta House", dev=dev_b, area=121500,
          lat=LAT_B, lng=LNG_B, **({"postcode": pc_b} if pc_b is not None else {}))
    return a, b


# ---- the containment fixture ----------------------------------------------------------
# The P0-2 shape: a tracker's full postal string against a brochure's bare scheme name.
# The brochure's distinctive tokens are a SUBSET of the tracker's, the cities agree, and
# the areas are within 5% - so containment is the only auto path (the fuzzy key scores far
# below the threshold because the city|developer|park key glues a different token onto each
# side; asserted in section 0).
BROCHURE_PARK = "Kestrel Reach"
TRACKER_PARK = "Unit 3, Kestrel Reach, Halston Industrial Estate"


def contain_pair(pc_a=None, pc_b=None, dev_a=None, dev_b=None):
    a = r("tracker.xlsx", TRACKER_PARK, dev=dev_a, area=98000,
          **({"postcode": pc_a} if pc_a is not None else {}))
    b = r("brochure.pdf", BROCHURE_PARK, dev=dev_b, area=99500,
          **({"postcode": pc_b} if pc_b is not None else {}))
    return a, b


def main() -> int:
    fails: list[str] = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---- 0. the fixtures reproduce the intended shape ------------------------------
    # If any of these drift, every assertion below is vacuous: the pair would be reaching
    # auto (or failing to) through some path other than the one under test.
    print("the fixtures isolate ONE auto path each:")
    ca, cb = coord_pair(dev_a=DEV, dev_b=DEV)
    ck(M._km(M._latlng(ca), M._latlng(cb)) <= M.COORD_MERGE_KM,
       f"coord fixture: the two pins are inside the net "
       f"({M._km(M._latlng(ca), M._latlng(cb)) * 1000:.0f} m)")
    ck(not (M._distinctive_tokens(ca["park"]) & M._distinctive_tokens(cb["park"])),
       "coord fixture: the parks share NO distinctive token, so containment cannot fire")
    ck(M._tsr(M.match_key(ca), M.match_key(cb)) < M.MATCH_THRESHOLD,
       f"coord fixture: the fuzzy key is below {M.MATCH_THRESHOLD}, so the tail cannot "
       f"rescue it ({M._tsr(M.match_key(ca), M.match_key(cb)):.1f})")
    ck(bool(M.norm(ca["park"])) and bool(M.norm(cb["park"])),
       "coord fixture: both parks are present, so the one-park-missing branch is skipped")
    ta, tb = contain_pair(dev_a=DEV, dev_b=DEV)
    tta, ttb = M._distinctive_tokens(ta["park"]), M._distinctive_tokens(tb["park"])
    ck(ttb < tta, f"containment fixture: the brochure tokens are a strict subset {sorted(ttb)}")
    ck(M._tsr(M.match_key(ta), M.match_key(tb)) < M.MATCH_THRESHOLD,
       f"containment fixture: the fuzzy key is below {M.MATCH_THRESHOLD} too "
       f"({M._tsr(M.match_key(ta), M.match_key(tb)):.1f})")
    ck(M._area_pair(ta, tb)[0] is not None
       and abs(98000 - 99500) / 99500 <= 0.05, "containment fixture: areas within 5%")

    # ---- 1. A12: two DIFFERENT stated codes never auto-merge ------------------------
    print("\nA12 - a postal-code disagreement vetoes the merge:")
    # The headline shape from the incident: close pins, near-identical areas, no party
    # named on either side, two different codes. Pinned FIRST as the prompt's case, then
    # decomposed, because with A13 also in force this pair has TWO reasons to be blocked
    # and a single assertion would not say which guard is carrying it.
    a, b = coord_pair("AB12 3CD", "AB12 4EF")
    ck(M.pair_class(a, b) != "auto",
       f"differing codes + near-identical areas + close pins + NO developer -> not auto "
       f"({M.pair_class(a, b)})")
    # A12 ALONE, with A13 satisfied: the developer agrees on both sides, so the ONLY thing
    # separating these two records is the stated code. This is the assertion that fails if
    # the veto is ever removed from the auto branch and left only in the forbidden tier.
    a, b = coord_pair("AB12 3CD", "AB12 4EF", DEV, DEV)
    ck(M.pair_class(a, b) == "forbidden",
       f"...and with the SAME developer stated on both sides it is still blocked, on the "
       f"code alone ({M.pair_class(a, b)})")
    ck(not M.same_property(a, b, {M.pair_id(a, b): "same"}),
       "...a hard blocker, so even an LLM 'same' verdict cannot merge it")
    ck(M._postcode_conflict(a, b) and M._postcode_conflict(b, a),
       "...and the conflict is order-independent")
    # the containment branch needs its own assertion - it is a SEPARATE call site
    ta, tb = contain_pair("AB12 3CD", "AB12 4EF", DEV, DEV)
    ck(M.pair_class(ta, tb) == "forbidden",
       f"the containment branch is vetoed by the code too ({M.pair_class(ta, tb)})")
    # format-agnostic: the same veto on an all-digit and a digits-then-letters code
    for pa, pb in (("12345", "54321"), ("1234 AB", "5678 CD"), ("100-0001", "150-0002")):
        a, b = coord_pair(pa, pb, DEV, DEV)
        ck(M.pair_class(a, b) == "forbidden",
           f"...in a format with no outward/inward split either ({pa} vs {pb})")
    # a numeric cell (the reader hands back a number for an all-digit code) still compares
    a, b = coord_pair(12345, 54321.0, DEV, DEV)
    ck(M.pair_class(a, b) == "forbidden",
       "...and a code stored as a NUMBER is still a code (an int against a float)")
    # the camelCase field name is read as well as the canonical one
    a, b = coord_pair(dev_a=DEV, dev_b=DEV)
    a, b = dict(a, postalCode="AB12 3CD"), dict(b, postalCode="AB12 4EF")
    ck(M.pair_class(a, b) == "forbidden", "...under `postalCode` as well as `postcode`")

    # ---- 2. A12 must NOT rest on the area-code half of a code -----------------------
    # `_CODEISH` strips the AREA half ('ab12') for the grey bag, because an area label
    # covers a whole town. Reusing that stripper here would compare two records on the
    # town-sized half of their codes and report two different buildings as AGREEING - the
    # exact over-merge the veto exists to stop. These two codes share their area half.
    print("\n...and it compares the FULL code, not the area half:")
    ck(M._stated_postcode({"postcode": "AB12 3CD"})
       != M._stated_postcode({"postcode": "AB12 4EF"}),
       "two codes sharing an area half are still two codes")
    ck(M._stated_postcode({"postcode": "ab12 3cd"})
       == M._stated_postcode({"postcode": "AB123CD"}) == "AB123CD",
       "case and internal spacing do not make two codes out of one")
    ck(M._postcode_conflict({"postcode": "AB12"}, {"postcode": "AB123CD"}),
       "a PREFIX is not agreement - no country-specific parsing is attempted")

    # ---- 3. equal and absent codes must not break legitimate merging -----------------
    print("\nequal codes still merge; an absent code is inert:")
    a, b = coord_pair("AB12 3CD", "AB12 3CD", DEV, DEV)
    ck(M.pair_class(a, b) == "auto",
       f"the SAME pair with EQUAL codes still auto-merges ({M.pair_class(a, b)})")
    a, b = coord_pair("ab12  3cd", "AB123CD", DEV, DEV)
    ck(M.pair_class(a, b) == "auto",
       "...and the same code written two ways is still one code")
    ta, tb = contain_pair("AB12 3CD", "AB12 3CD", DEV, DEV)
    ck(M.pair_class(ta, tb) == "auto", "...the containment branch too")
    # ABSENCE IS NOT A DISAGREEMENT: the tier is whatever it was before A12 fired
    base = M.pair_class(*coord_pair(None, None, DEV, DEV))
    ck(base == "auto", f"the baseline pair, no codes stated at all, is auto ({base})")
    ck(M.pair_class(*coord_pair("AB12 3CD", None, DEV, DEV)) == base,
       "one side states a code, the other is silent -> the tier is UNCHANGED")
    ck(M.pair_class(*coord_pair(None, "AB12 4EF", DEV, DEV)) == base,
       "...and the same in the other direction")
    for sentinel in ("tbd", "TBC", "n/a", "-", "", "   "):
        ck(M.pair_class(*coord_pair("AB12 3CD", sentinel, DEV, DEV)) == base,
           f"...a sentinel is ABSENCE, not a differing code ({sentinel!r})")
    ck(M.pair_class(*coord_pair("AB12 3CD", 1234.5, DEV, DEV)) == base,
       "...and a non-integral number is not a code at all")

    # ---- 4. A13: two absent developers are not agreeing developers -------------------
    print("\nA13 - two absences are not an agreement:")
    a, b = coord_pair(dev_a=None, dev_b=None)
    ck(M._known_dev(a) == M._known_dev(b) == "",
       "the fixture really does state NO developer on either side")
    ck(M.pair_class(a, b) != "auto",
       f"coord net: no developer on either side is no longer auto ({M.pair_class(a, b)})")
    ta, tb = contain_pair(dev_a=None, dev_b=None)
    ck(M.pair_class(ta, tb) != "auto",
       f"containment: no developer on either side is no longer auto "
       f"({M.pair_class(ta, tb)})")
    # an UNKNOWN SENTINEL is an absence too - that is `_known_dev`'s whole job
    ck(M.pair_class(*coord_pair(dev_a="tbd", dev_b="tbd")) != "auto",
       "...a shared 'tbd' developer is not an agreement either")
    ck(M.pair_class(*coord_pair(dev_a=DEV, dev_b=None)) != "auto",
       "...nor is one side stated and the other silent")
    ck(M.pair_class(*contain_pair(dev_a=None, dev_b=DEV)) != "auto",
       "...in either branch, in either direction")
    # ...and the legitimate merge is untouched
    ck(M.pair_class(*coord_pair(dev_a=DEV, dev_b=DEV)) == "auto",
       "two PRESENT matching developers still auto-merge on the coord net")
    ck(M.pair_class(*contain_pair(dev_a=DEV, dev_b=DEV)) == "auto",
       "...and on containment")
    ck(M.pair_class(*coord_pair(dev_a="Ardent Estates Ltd", dev_b="ardent")) == "auto",
       "...through `norm_dev`, so a legal suffix or a case difference is still agreement")
    ck(M.pair_class(*coord_pair(dev_a=DEV, dev_b="Harrowgate Capital")) != "auto",
       "a genuine developer DISAGREEMENT is still not auto (unchanged)")
    # THE DIRECTION OF THE FAILURE, stated as a test: a demoted pair lands in a tier that
    # never merges silently. NOT "recoverable" - that word stood here and was wrong. This
    # pair lands in GREY, so an adjudicated 'same' recovers it; a pair demoted by the CODE
    # veto lands in FORBIDDEN, where nothing recovers it (section 1 pins that). And no gate
    # sees either split: Alpha Court / Beta House differ on park AND area, so the coverage
    # dedupe key cannot match them - asserted below rather than asserted in prose.
    dem = M.pair_class(*coord_pair(dev_a=None, dev_b=None))
    ck(dem in ("grey", "forbidden", "no"),
       f"a demoted pair moves towards the over-SPLIT direction ({dem})")
    ck(dem == "grey", f"...specifically GREY here, so the adjudicator can still merge it ({dem})")
    da_, db_ = coord_pair(dev_a=None, dev_b=None)
    ck(M.same_property(da_, db_, {M.pair_id(da_, db_): "same"}),
       "...and it does: an adjudicated 'same' merges an A13-demoted pair")

    # THE FIX-2 MEASUREMENT, as a test rather than a comment: the coverage dedupe gate keys
    # on park+city+developer+warehouseArea and cannot see ANY of these splits.
    def _cov_key(rec):
        return (str(rec.get("park", "")).lower(), str(rec.get("city", "")).lower(),
                str(rec.get("developer", "")).lower(), rec.get("warehouseArea"))

    for label, x, y in (("the coord fixture", *coord_pair(dev_a=None, dev_b=None)),
                        ("the containment fixture", *contain_pair(dev_a=None, dev_b=None)),
                        ("the code fixture", *coord_pair("AB12 3CD", "AB12 4EF", DEV, DEV))):
        ck(_cov_key(x) != _cov_key(y),
           f"the coverage dedupe gate is BLIND to the split in {label} "
           f"(its key differs, so it cannot fire)")
    # ...and the ONE shape it does catch, so the claim is narrowed rather than deleted: a
    # typo-split is one building quoted twice, identical on all four key fields.
    typo_a = r("tracker.xlsx", "Kestrel Reach", dev=DEV, area=120000, postcode="AB12 3CD")
    typo_b = r("brochure.pdf", "Kestrel Reach", dev=DEV, area=120000, postcode="AB12 3DC")
    ck(_cov_key(typo_a) == _cov_key(typo_b),
       "a TYPO-split IS gate-visible: identical park+city+developer+area, one keying error")
    ck(M.pair_class(typo_a, typo_b) == "forbidden",
       "...and it is still vetoed - the accepted cost, with the gate as its only route back")

    # ---- 5. a corpus with NO postal codes anywhere is entirely unaffected ------------
    # The guard must be inert in a market whose records simply do not carry codes. Proved
    # by DISABLING the reader and re-deriving every verdict, which is stronger than
    # asserting a list of expected tiers: it shows A12 contributes nothing at all here.
    print("\na corpus that states no codes at all is byte-identical:")
    corpus = [
        r("tracker.xlsx", "Alpha Court", dev=DEV, area=120000, lat=LAT_A, lng=LNG_A),
        r("brochure.pdf", "Beta House", dev=DEV, area=121500, lat=LAT_B, lng=LNG_B),
        r("tracker.xlsx", TRACKER_PARK, dev=DEV, area=98000),
        r("brochure.pdf", BROCHURE_PARK, dev=DEV, area=99500),
        r("other.pdf", "Alpha Court", dev=None, area=120000),
        r("other.pdf", "Alpha Court", dev=None, area=400000),
    ]
    ck(not any(M._stated_postcode(x) for x in corpus),
       "the fixture states no postal code on any record")
    ck(not any(M._postcode_conflict(x, y) for x, y in itertools.combinations(corpus, 2)),
       "...so no pair in it can report a code conflict")
    before = [M.pair_class(x, y) for x, y in itertools.combinations(corpus, 2)]
    clusters_before = M.dedupe(corpus)
    _real = M._stated_postcode
    try:
        M._stated_postcode = lambda _r: ""          # A12 fully disabled
        after = [M.pair_class(x, y) for x, y in itertools.combinations(corpus, 2)]
        clusters_after = M.dedupe(corpus)
    finally:
        M._stated_postcode = _real
    ck(before == after,
       f"every tier verdict is identical with the code reader disabled ({before})")
    ck(clusters_before == clusters_after, "...and so is the clustering")

    # ---- 6. the paths A12/A13 must NOT have touched ----------------------------------
    print("\nunchanged: the size veto and the same-source verdict:")
    # the footing-aware size veto (B10)
    big = r("a.pdf", "Alpha Court", dev=DEV, area=50000, unit="sq m")
    small = r("b.pdf", "Alpha Court", dev=DEV, area=12000, unit="sq m")
    ck(M.pair_class(big, small) == "forbidden",
       f"a >15% same-unit conflict is still forbidden ({M.pair_class(big, small)})")
    sqm = r("a.pdf", "Alpha Court", dev=DEV, area=12000, unit="sq m")
    sqft = r("b.xlsx", "Alpha Court", dev=DEV, area=129167, unit="sq ft")
    ck(M.pair_class(sqm, sqft) != "forbidden",
       f"a mixed-unit pair of ONE building is still converted, not vetoed "
       f"({M.pair_class(sqm, sqft)})")
    silent = r("c.pdf", "Alpha Court", dev=DEV, area=129167, unit="")
    ck(M._area_pair(sqm, silent) == (None, None) and M.pair_class(sqm, silent) != "forbidden",
       "an unknown footing still refuses to block")
    # a size conflict and a code conflict are INDEPENDENT blockers, not one guard
    ck(M.pair_class(dict(big, postcode="AB12 3CD"), dict(small, postcode="AB12 3CD"))
       == "forbidden", "an EQUAL code does not rescue a >15% size conflict")
    # the same-source path returns before the cross-source tiers are consulted
    ss1 = r("deck.pdf", "Alpha Court", dev=DEV, area=120000)
    ss2 = r("deck.pdf", "Alpha Court", dev=DEV, area=120000)
    ck(M.pair_class(ss1, ss2) == "auto",
       "a same-source restatement (identical key, identical area) still merges")
    ck(M.pair_class(ss1, r("deck.pdf", "Alpha Court", dev=DEV, area=400000)) == "forbidden",
       "...and two same-source records with differing areas are still forbidden")
    ck(M.pair_class(r("deck.pdf", "Alpha Court", dev=None, area=120000),
                    r("deck.pdf", "Alpha Court", dev=None, area=120000)) == "auto",
       "...unaffected by A13: a same-source restatement never consults the developer")
    # RESIDUAL, recorded not fixed: A12 is scoped to CROSS-SOURCE pairs, because the
    # same-source branch returns from `pair_class` before either cross-source tier runs.
    # Two rows of ONE file with an identical key, an identical area and two different codes
    # therefore still restate-merge. Pinned as the CURRENT FACT, not as a desirable one:
    # the same-source restatement rule exists to stop the skill shipping records its own
    # coverage gate then hard-blocks as duplicates, so tightening it is a separate change
    # with its own blast radius. Recorded here so it is a decision and not a discovery.
    ck(M.pair_class(dict(ss1, postcode="AB12 3CD"), dict(ss2, postcode="AB12 4EF")) == "auto",
       "RESIDUAL: a SAME-SOURCE restatement is not code-vetoed (A12 is cross-source only)")

    # ---- 6b. A12b: the two auto paths A12 MISSED, now closed -------------------------
    # THESE TWO ASSERTIONS ARE INVERTED, NOT NEW, AND THE INVERSION IS THE POINT. They used
    # to assert `== "auto"` - the bypass PINNED AS A CURRENT FACT, so the hole showed up in
    # eval output instead of only in a comment, with a note that a later wave closing it
    # should flip these lines and say so. This is that wave, so they are flipped and kept:
    # an inverted pin is what stops the bypass returning, where deleting them would leave
    # the fuzzy tail unpinned in exactly the direction that regressed once already.
    #
    # The recorded reason for leaving the hole open was blast radius - "the tail is the
    # historical matcher kept verbatim; changing it moves pairs that every offline run
    # merges today". MEASURED, that was false: instrumenting `_cross_source_auto` for
    # "auto says yes AND the codes conflict" over all 128 evals logs exactly TWO pairs, and
    # they are these two fixtures. Nothing else in the corpus moves.
    print("\nA12b - the two auto paths A12 did NOT guard, now closed:")
    same_key_a = r("tracker.xlsx", "Kestrel Reach", dev=DEV, area=120000, postcode="AB12 3CD")
    same_key_b = r("brochure.pdf", "Kestrel Reach", dev=DEV, area=121000, postcode="AB12 4EF")
    ck(M._tsr(M.match_key(same_key_a), M.match_key(same_key_b)) >= M.MATCH_THRESHOLD,
       "the fuzzy tail's fixture really does have a near-identical key")
    ck(M.pair_class(same_key_a, same_key_b) == "forbidden",
       f"the FUZZY-KEY TAIL no longer merges across two differing stated codes "
       f"({M.pair_class(same_key_a, same_key_b)})")
    # it FUSED, not merely mis-tiered - so the clustering result is pinned too
    ck(len(M.dedupe([same_key_a, same_key_b])) == 2,
       "...and the pair no longer collapses into ONE cluster (it used to)")
    ck(not M.same_property(same_key_a, same_key_b,
                           {M.pair_id(same_key_a, same_key_b): "same"}),
       "...the accepted cost: forbidden, so not even an adjudicated 'same' recovers it")
    nopark_a = r("tracker.xlsx", "", dev=DEV, area=120000, postcode="AB12 3CD")
    nopark_b = r("brochure.pdf", "Kestrel Reach", dev=DEV, area=121000, postcode="AB12 4EF")
    ck(M.pair_class(nopark_a, nopark_b) == "forbidden",
       f"the ONE-PARK-MISSING branch does not either ({M.pair_class(nopark_a, nopark_b)})")
    ck(len(M.dedupe([nopark_a, nopark_b])) == 2,
       "...and it too stays two clusters")
    # THE POSITIVE CONTROLS FOR THE CLOSURE. A veto at the top of the function could just as
    # easily have broken every legitimate merge on those two paths, so each is re-asserted
    # with the codes EQUAL and with the codes ABSENT - the two states that must stay inert.
    for label, pc_a, pc_b in (("EQUAL", "AB12 3CD", "AB12 3CD"), ("ABSENT", None, None),
                              ("one side SILENT", "AB12 3CD", None)):
        kw_a = {"postcode": pc_a} if pc_a is not None else {}
        kw_b = {"postcode": pc_b} if pc_b is not None else {}
        ck(M.pair_class(r("tracker.xlsx", "Kestrel Reach", dev=DEV, area=120000, **kw_a),
                        r("brochure.pdf", "Kestrel Reach", dev=DEV, area=121000, **kw_b))
           == "auto", f"...the fuzzy tail still auto-merges with codes {label}")
        ck(M.pair_class(r("tracker.xlsx", "", dev=DEV, area=120000, **kw_a),
                        r("brochure.pdf", "Kestrel Reach", dev=DEV, area=121000, **kw_b))
           == "auto", f"...and so does the one-park-missing branch with codes {label}")

    # ---- 7. the veto lives in BOTH tiers, and the guard cannot be half-removed -------
    # The regression this file is really here to prevent. `pair_class` tests auto BEFORE
    # forbidden, so a veto present only in `_cross_source_forbidden` is invisible to every
    # pair the auto tier claims. Asserted against the SOURCE, because a future edit that
    # deletes one of the two call sites would otherwise fail somewhere far from the cause.
    print("\nthe veto is present in both tiers (the tier-order trap):")
    src = (ROOT / "helpers" / "match.py").read_text(encoding="utf-8")

    def _body(fn: str) -> str:
        i = src.find("\ndef " + fn + "(")
        j = src.find("\ndef ", i + 1)
        return src[i:j if j != -1 else len(src)] if i != -1 else ""

    for tier in ("_cross_source_auto", "_cross_source_forbidden"):
        body = _body(tier)
        ck(bool(body) and "_postcode_conflict(" in body,
           f"{tier} tests the postal-code conflict itself")
    # ONE GUARD, AT THE TOP - the assertion this replaces demanded TWO call sites, one per
    # merging branch, under the source comment's own "IF YOU CHANGE ONE, CHANGE THE OTHER"
    # warning. That shape was the defect: two of the four auto paths had no call site at all,
    # and a fifth path added later would have had none either. A single top-of-function guard
    # cannot be bypassed by a branch, so the invariant is now structural and this asserts the
    # structure: exactly one call, and it precedes every `return True` in the function.
    auto_body = _body("_cross_source_auto")
    ck(auto_body.count("_postcode_conflict(") == 1,
       f"the auto tier calls it EXACTLY ONCE, so there is no second site to fall out of sync "
       f"({auto_body.count('_postcode_conflict(')})")
    ck(bool(re.search(r"\n    if _postcode_conflict\(a, b\):\n\s+return False\b", auto_body)),
       "...as a top-level guard in the function body that RETURNS FALSE")
    ck(0 < auto_body.find("_postcode_conflict(") < auto_body.find("return True"),
       "...ahead of every merging branch, so no auto path can reach a merge around it")
    # and the same holds against the EXECUTABLE code, not the changelog in the comments
    auto_code = "\n".join(l for l in auto_body.splitlines()
                          if not l.lstrip().startswith("#"))
    ck(auto_code.count("_postcode_conflict(") == 1,
       "...counted over executable lines only, so a comment cannot satisfy this")
    # A13 asserted against the CODE and not the prose: the comments in that function quote
    # the old permissive expression on purpose (this codebase records what a guard replaced),
    # so a scan of the raw body would match its own changelog. Full-line comments are
    # dropped first, then the retired shape must be gone from what actually executes.
    code = "\n".join(l for l in _body("_cross_source_auto").splitlines()
                     if not l.lstrip().startswith("#"))
    for retired in ("not da or not db", "not ka_ or not kb_"):
        ck(retired not in code,
           f"_cross_source_auto no longer EXECUTES `{retired} ...` "
           f"(two absent developers read as an agreement)")
    ck("if da and db and da == db" in code and "and ka_ and kb_ and ka_ == kb_" in code,
       "...both branches now require the developer STATED on both sides and equal")

    print(f"\nOVERMERGE GUARD TEST: {'PASS' if not fails else f'FAIL ({len(fails)})'}")
    for f in fails:
        print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
