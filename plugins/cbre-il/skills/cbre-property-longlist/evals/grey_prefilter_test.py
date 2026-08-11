#!/usr/bin/env python3
"""grey_prefilter_test.py - a shared CITY is not a grey signal on its own. (I9)

`_cross_source_grey` was a four-way OR whose first disjunct was "same normalised city".
A property longlist is by definition usually ONE town, so that disjunct fired on every
cross-source pair in the skill's most common corpus and the grey set went quadratic - and
every grey pair costs TWO LLM judgements (adjudicate, then a blind re-judge).

MEASURED on the Corby run, reconstructed here as `corby_corpus()` from the real tracker
and the delivered Source Ledger: 14 grey pairs, 28 judgements, ZERO merges. Twelve of the
fourteen had `same-city` as their ONLY signal; a thirteenth was corroborated solely by the
token `corby`, because the town name sits inside the tracker's park strings. One pair had a
real signal.

The rule now: within ~2 km, OR a shared distinctive park token with the pair's city tokens
excluded, OR a fuzzy key in [70, 88), OR same city AND the same KNOWN developer. The
developer keeps a city-paired disjunct because it DISCRIMINATES in a single-market corpus
and the city does not.

The safety argument this file pins, in order of importance:
  1. the change only ever moves pairs grey -> 'no', so offline clustering is unchanged;
  2. the city-token strip did NOT leak into `_cross_source_auto`'s containment branch,
     where shrinking a token set can CREATE a subset relation and thus a new auto-merge;
  3. the accepted cost - a demoted pair can no longer be merged by an LLM 'same' - is
     stated as a test rather than left implicit.
Offline, pure, no network, no work dir."""
from __future__ import annotations
import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import match as M  # noqa: E402

TRK = "Building_Data_12_06_2026.xlsx"


def r(src, park, city="Corby", dev=None, area=None, unit="sq ft", lat=None, lng=None):
    rec = {"park": park, "city": city, "developer": dev, "areaUnit": unit,
           "__meta": {"source_file": src}}
    if area is not None:
        rec["warehouseArea"] = area
    if lat is not None:
        rec["lat"], rec["lng"] = lat, lng
    return rec


def corby_corpus() -> list[dict]:
    """The 2026-08-03 Corby run: 4 tracker rows (Marketing Name -> park, the
    'Latitude, Longitude' column split, Developer, Size sq ft GIA) + the 4 brochure
    records as the delivered Source Ledger records them. NOT ONE DECK STATED
    COORDINATES, which is why the coordinate net cannot help any cross-source pair
    here - the single most important property of this fixture."""
    return [
        r(TRK, "EVO 169, Sallow Road, Corby NN17 5JX", dev="", area=172867,
          lat=52.50304981, lng=-0.650581854),
        r(TRK, "Rockingham 161, Earlstree 160, Earlstrees Industrial Estate", dev="",
          area=161415, lat=52.50479792, lng=-0.698356033),
        r(TRK, "Saxon 132", dev="", area=131536, lat=52.46850533, lng=-0.737056454),
        r(TRK, "Unit 1, Raven Park, Earlstrees Industrial Estate, Corby, NN17 4XD",
          dev="Canmoor", area=177750, lat=52.5113515746894, lng=-0.7051011759664334),
        r("Evo-corby-169-brochure.pdf", "EVO Corby 169", dev="EVO Industrial", area=156840),
        r("Earlstree 160 Corby.pdf", "Rockingham 161"),
        r("lba-saxon132-brochure-nov25-1.pdf", "Saxon 132", area=124746),
        r("Raven Park_Brochure_V8.1.pdf", "Raven Park", dev="Canmoor"),
    ]


def _old_grey(a: dict, b: dict) -> bool:
    """The PRE-I9 disjunction, verbatim, so the fixture's 14 -> 1 drop is measured against
    the real former rule rather than asserted from a comment."""
    ca, cb = M.norm(a.get("city")), M.norm(b.get("city"))
    if ca and cb and ca == cb:
        return True
    la, lb = M._latlng(a), M._latlng(b)
    if la and lb and M._km(la, lb) <= M.GREY_COORD_KM:
        return True
    da, db = M._distinctive_tokens(a.get("park")), M._distinctive_tokens(b.get("park"))
    if da and db and (da & db):
        return True
    return M.GREY_LOW <= M._tsr(M.match_key(a), M.match_key(b)) < M.MATCH_THRESHOLD


def _old_class(a: dict, b: dict) -> str:
    """pair_class with the OLD grey filter substituted - every other tier untouched."""
    if a.get("__meta", {}).get("source_file") == b.get("__meta", {}).get("source_file"):
        return "auto" if M._same_source_verdict(a, b) else "forbidden"
    if M._cross_source_auto(a, b):
        return "auto"
    if M._cross_source_forbidden(a, b):
        return "forbidden"
    return "grey" if _old_grey(a, b) else "no"


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---- 1. the headline: a shared city, and nothing else, is no longer enough --------
    print("the city alone:")
    a = r("a.pdf", "Apollo Court", dev="Prologis", area=50000)
    b = r("b.xlsx", "Mercury House", dev="Panattoni", area=52000)
    ck(M.norm(a["city"]) == M.norm(b["city"]) == "corby", "the fixture does share a city")
    ck(not (M._distinctive_tokens(a["park"]) & M._distinctive_tokens(b["park"])),
       "...with no shared park token")
    ck(M._tsr(M.match_key(a), M.match_key(b)) < M.GREY_LOW,
       f"...a fuzzy key below the {M.GREY_LOW} floor "
       f"({M._tsr(M.match_key(a), M.match_key(b)):.1f})")
    ck(M._latlng(a) is None and M._latlng(b) is None, "...and no coordinates on either side")
    ck(M.pair_class(a, b) == "no", f"-> 'no', not 'grey' ({M.pair_class(a, b)})")
    ck(_old_class(a, b) == "grey", "...and it WAS 'grey' under the old rule (the change is real)")

    # ---- 2. each surviving signal, in isolation --------------------------------------
    print("\neach signal still qualifies on its own:")
    # (i) coordinates within GREY_COORD_KM, cities absent so nothing else can fire
    ca = r("a.pdf", "Apollo Court", city="", area=50000, lat=52.5000, lng=-0.6500)
    cb = r("b.xlsx", "Mercury House", city="", area=52000, lat=52.5050, lng=-0.6520)
    ck(M._km(M._latlng(ca), M._latlng(cb)) <= M.GREY_COORD_KM
       and M.pair_class(ca, cb) == "grey", "coordinates within ~2 km -> grey")
    # (ii) a shared DISTINCTIVE park token that is not the town
    ta = r("a.pdf", "Raven Park", city="Corby", area=50000)
    tb = r("b.xlsx", "Unit 1, Raven Park, Earlstrees Industrial Estate, Corby NN17 4XD",
           city="Corby", area=90000)   # >15% apart so `auto` cannot claim it first
    ck(M.pair_class(ta, tb) == "forbidden" or "raven" in (
        M._grey_tokens(ta["park"], M._grey_city_tokens(ta, tb))
        & M._grey_tokens(tb["park"], M._grey_city_tokens(ta, tb))),
       "a real park token ('raven') survives the city strip")
    ta2 = r("a.pdf", "Raven Park", city="Corby", area=50000)
    tb2 = r("b.xlsx", "Raven Point, Corby", city="Corby", area=48000)
    ck(M.pair_class(ta2, tb2) in ("auto", "grey"),
       "...and a token-sharing pair reaches a decidable tier")
    # (iii) the borderline fuzzy band
    fa = r("a.pdf", "Raven Park", city="Corby", dev="Prologis", area=50000)
    fb = r("b.xlsx", "Raven Park", city="Corby", dev="Panattoni", area=50000)
    sc = M._tsr(M.match_key(fa), M.match_key(fb))
    ck(M.GREY_LOW <= sc < M.MATCH_THRESHOLD and M.pair_class(fa, fb) == "grey",
       f"a fuzzy key in [{M.GREY_LOW}, {M.MATCH_THRESHOLD}) -> grey ({sc:.1f})")
    # (iv) same city + the same KNOWN developer - the disjunct that keeps MATCH-a alive
    da = r("a.pdf", "Apollo Court", city="Corby", dev="Prologis", area=50000)
    db = r("b.xlsx", "Mercury House", city="Corby", dev="Prologis", area=52000)
    ck(M._tsr(M.match_key(da), M.match_key(db)) < M.GREY_LOW
       and not (M._distinctive_tokens(da["park"]) & M._distinctive_tokens(db["park"]))
       and M.pair_class(da, db) == "grey",
       "same city + same KNOWN developer -> grey (its only signal)")
    # an UNKNOWN developer is neither agreement nor evidence. BOTH sides carry the SAME
    # sentinel on purpose: an earlier version of this fixture used 'tbd' vs '??', which
    # norm_dev maps to different strings, so it passed even with the _known_dev guard
    # removed. Mutation testing caught that; the sentinel must be identical to have teeth.
    for sent in ("tbd", "??", "—"):
        ua = r("a.pdf", "Apollo Court", city="Corby", dev=sent, area=50000)
        ub = r("b.xlsx", "Mercury House", city="Corby", dev=sent, area=52000)
        ck(M._known_dev(ua) == "" and M.pair_class(ua, ub) == "no",
           f"...but two records both claiming developer {sent!r} corroborate nothing")
    # (v) the second form: one record's developer NAME inside the other's park string.
    #     This is the live TEMU shape (B48) - the tracker carries the developer in its
    #     marketing name/address, the brochure carries it in `developer`.
    na = r("deck.pdf", "Central A1[M] 785", city="Doncaster", dev="Panattoni", area=734636)
    nb = r("tracker.xlsx", "Panattoni Doncaster 770, Blyth Road, Harworth",
           city="Doncaster", area=783309)
    ck(M._known_dev(nb) == "", "the tracker side states no developer at all")
    ck(M._known_dev(na) in M._grey_tokens(nb["park"], M._grey_city_tokens(na, nb)),
       "...but its PARK carries the other side's developer name")
    ck(M.pair_class(na, nb) == "grey", f"-> grey ({M.pair_class(na, nb)})")
    #     and it is CITY-GATED: the same pair in two different towns is not askable
    nb2 = dict(nb, city="Harworth")
    ck(M.pair_class(na, nb2) == "no",
       "...while the same pair in two different towns stays 'no' (the form is city-gated)")

    # ---- 3. the city-token strip ------------------------------------------------------
    print("\nthe town's own name is not identity:")
    sa = r(TRK, "EVO 169, Sallow Road, Corby NN17 5JX", city="Corby", area=177750)
    sb = r("raven.pdf", "Raven Park Corby", city="Corby", area=169250)
    ct = M._grey_city_tokens(sa, sb)
    ck("corby" in (M._distinctive_tokens(sa["park"]) & M._distinctive_tokens(sb["park"])),
       "the two parks DO share the token 'corby' before the strip")
    ck(not (M._grey_tokens(sa["park"], ct) & M._grey_tokens(sb["park"], ct)),
       "...and share nothing after it")
    ck(M.pair_class(sa, sb) == "no", "-> 'no' (the spurious corroboration is gone)")
    # the order-independence fixture must have DIFFERING cities: with both sides 'Corby'
    # the assertion held even when the union was mutated to read only `a`'s city. (Caught
    # by mutation testing - a vacuous assertion is worse than none, it reads as covered.)
    oa = r("a.pdf", "Alpha Corby", city="Corby", area=50000)
    ob = r("b.xlsx", "Alpha Beta", city="", area=50000)
    ck(M._grey_city_tokens(oa, ob) == M._grey_city_tokens(ob, oa) == {"corby"},
       "the city-token set is order-independent (a union of both sides, not just a's)")
    ml = r("a.pdf", "Alpha Keynes", city="Milton Keynes", area=50000)
    mr = r("b.xlsx", "Beta Milton", city="Milton Keynes", area=52000)
    ck(M._grey_city_tokens(ml, mr) == {"milton", "keynes"}
       and M.pair_class(ml, mr) == "no",
       "a MULTI-WORD city strips every one of its tokens")

    # ---- 4. THE POSITIVE CONTROL: the strip must not reach the auto tier -------------
    # Shrinking a token set can only ADD subset relations, and `_cross_source_auto`'s
    # containment branch merges on a subset WITHOUT asking anybody. This fixture is not
    # auto today; it WOULD be if the strip leaked there. The absent city on one side keeps
    # the key tokens un-nested so the fuzzy tail cannot reach 88 and confound the control.
    print("\npositive control - the strip is confined to the grey filter:")
    pa = r("a.pdf", "Alpha Corby", city="Corby", dev="Prologis", area=50000)
    pb = r("b.xlsx", "Alpha Beta", city="", dev="Prologis", area=50000)
    t_a, t_b = M._distinctive_tokens(pa["park"]), M._distinctive_tokens(pb["park"])
    pct = M._grey_city_tokens(pa, pb)
    s_a, s_b = M._grey_tokens(pa["park"], pct), M._grey_tokens(pb["park"], pct)
    ck(not (t_a <= t_b or t_b <= t_a), "unstripped: neither token set contains the other")
    ck(s_a <= s_b, "stripped: one WOULD contain the other (so the control has teeth)")
    ck(M._tsr(M.match_key(pa), M.match_key(pb)) < M.MATCH_THRESHOLD,
       "the fuzzy tail cannot claim this pair either")
    ck(M._cross_source_auto(pa, pb) is False,
       "-> _cross_source_auto is STILL False: the containment branch did not inherit the strip")
    src = (ROOT / "helpers" / "match.py").read_text(encoding="utf-8")

    def _callers(fn: str) -> set:
        out = set()
        for m in re.finditer(re.escape(fn + "("), src):
            head = src.rfind("\ndef ", 0, m.start())
            out.add(src[head + 5:src.find("(", head + 5)])
        return out
    ck(_callers("_grey_tokens") <= {"_grey_tokens", "_cross_source_grey"},
       f"_grey_tokens is called ONLY from the grey filter ({sorted(_callers('_grey_tokens'))})")
    ck("_cross_source_auto" in _callers("_distinctive_tokens"),
       "_cross_source_auto still uses the UNSTRIPPED _distinctive_tokens")

    # ---- 5. offline clustering is unchanged by construction --------------------------
    print("\noffline behaviour is byte-identical:")
    recs = corby_corpus()
    ck(M.dedupe(recs) == M.dedupe(recs, None),
       "dedupe(records) == dedupe(records, None)")
    old_clusters = _old_dedupe(recs)
    ck(M.dedupe(recs) == old_clusters,
       "clustering with decisions=None is identical to the OLD rule's clustering")
    demoted = [(a, b) for a, b in itertools.combinations(recs, 2)
               if _old_class(a, b) == "grey" and M.pair_class(a, b) == "no"]
    ck(len(demoted) == 13, f"13 pairs moved grey -> 'no' on this corpus (got {len(demoted)})")
    ck(all(M.pair_class(a, b) != "auto" for a, b in itertools.combinations(recs, 2)
           if _old_class(a, b) != "auto"),
       "no pair was PROMOTED to auto (the change is one-directional)")
    ck(all(_old_class(a, b) == M.pair_class(a, b)
           for a, b in itertools.combinations(recs, 2)
           if _old_class(a, b) in ("auto", "forbidden")),
       "every auto/forbidden verdict on this corpus is unchanged")

    # ---- 6. the measured effect, and WHICH pair survives -----------------------------
    print("\nthe Corby corpus:")
    old_grey = [(a, b) for a, b in itertools.combinations(recs, 2)
                if _old_class(a, b) == "grey"]
    new = M.grey_pairs(recs)
    ck(len(old_grey) == 14, f"the old rule produced 14 grey pairs (got {len(old_grey)})")
    city_only = [(a, b) for a, b in old_grey
                 if not M._latlng(a) or not M._latlng(b)
                 if not (M._distinctive_tokens(a["park"]) & M._distinctive_tokens(b["park"]))
                 and not M.GREY_LOW <= M._tsr(M.match_key(a), M.match_key(b)) < M.MATCH_THRESHOLD]
    ck(len(city_only) == 12,
       f"12 of them had the shared city as their ONLY signal (got {len(city_only)})")
    ck(len(new) == 1, f"the new rule produces exactly 1 grey pair (got {len(new)})")
    surv = new[0]
    srcs = {surv["a"]["__meta"]["source_file"], surv["b"]["__meta"]["source_file"]}
    ck(srcs == {TRK, "Evo-corby-169-brochure.pdf"},
       f"...and it is the EVO tracker<->brochure pair - the one TRUE match (got {sorted(srcs)})")
    ck("evo" in (M._grey_tokens(surv["a"]["park"], M._grey_city_tokens(surv["a"], surv["b"]))
                 & M._grey_tokens(surv["b"]["park"], M._grey_city_tokens(surv["a"], surv["b"]))),
       "...kept by a REAL token ('evo'), not by the town")
    ck(M._cross_source_auto(surv["a"], surv["b"]) is False,
       "...and `auto` genuinely cannot claim it (its stated areas sit >5% apart)")

    # ---- 7. the accepted cost, stated as a test --------------------------------------
    print("\nthe accepted trade:")
    da2, db2 = demoted[0]
    pid = M.pair_id(da2, db2)
    ck(not M.same_property(da2, db2, {pid: "same"}),
       "a DEMOTED pair can no longer be merged by an LLM 'same' (over-split, never over-merge)")
    ck(not any(g["pair_id"] == pid for g in new),
       "...and it is not written to match_candidates.json, so the LLM is never asked")
    print("      ^ deliberate: the coverage dedupe gate catches a wrong split; an over-merge "
          "silently destroys a property")

    # ---- 8. the properties the grey tier already had must still hold -----------------
    print("\nunchanged invariants:")
    gp2 = M.grey_pairs(list(reversed(recs)))
    ck({g["pair_id"] for g in new} == {g["pair_id"] for g in gp2},
       "grey_pairs is order-independent")
    ck(M.pair_id(surv["a"], surv["b"]) == M.pair_id(surv["b"], surv["a"]),
       "pair_id is order-independent")
    big = r("a.pdf", "Raven Park", city="Corby", dev="Prologis", area=50000, unit="sq m")
    small = r("b.pdf", "Raven Park", city="Corby", dev="Prologis", area=12000, unit="sq m")
    ck(M.pair_class(big, small) == "forbidden",
       "a >15% same-unit size conflict is STILL forbidden (the hard blocker is untouched)")
    sqm = r("deck.pdf", "Raven Park", city="Corby", dev="Prologis", area=12000, unit="sq m")
    sqft = r("tracker.xlsx", "Raven Park", city="Corby", dev="Prologis", area=129167, unit="sq ft")
    ck(M.pair_class(sqm, sqft) in ("auto", "grey"),
       "a mixed-unit pair of the SAME building still reaches a decidable tier (B10 holds)")
    same_src = r("d.pdf", "Raven Park", city="Corby", area=50000)
    same_src2 = r("d.pdf", "Raven Park", city="Corby", area=50000)
    ck(M.pair_class(same_src, same_src2) == "auto",
       "a same-source restatement is still 'auto', never grey")

    if fails:
        print(f"\nGREY PREFILTER TEST: FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nGREY PREFILTER TEST: PASS")
    return 0


def _old_dedupe(records: list[dict]) -> list[list[dict]]:
    """`dedupe` under the OLD grey filter, decisions=None - the baseline for the
    'offline clustering is unchanged' claim."""
    def same(a, b):
        cls = _old_class(a, b)
        return cls == "auto"
    clusters: list[list[dict]] = []
    for rec in records:
        for cl in clusters:
            if any(same(rec, other) for other in cl):
                cl.append(rec)
                break
        else:
            clusters.append([rec])
    return clusters


if __name__ == "__main__":
    sys.exit(main())
