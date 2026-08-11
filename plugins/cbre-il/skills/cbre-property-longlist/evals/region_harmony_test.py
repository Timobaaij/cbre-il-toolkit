#!/usr/bin/env python3
"""region_harmony_test.py - `region` reports ONE administrative level. (I11)

`region` was decided per property by source precedence, and nothing ever asked whether the
resulting SET was coherent. On the 2026-08-03 Corby run two properties took the county from
their brochure ('Northamptonshire') and two took the wider region from the tracker ('East
Midlands'), because their brochures named none. Each value was correct and correctly
sourced; the set was not, because Northamptonshire is INSIDE the East Midlands - so the
client Excel's Region column presented a parent and its child as siblings for four units
three miles apart in one town.

`harmonise_regions` resolves it from the bind `bind_region_codes` has already made by exact
point-in-polygon on the property's own coordinates. What this file pins, in order:

  1. mixed levels collapse to the bound NUTS-3 name;
  2. a COHERENT dataset is byte-identical - the no-op gate, so this can never quietly
     restate a region every source agreed on;
  3. only a PROVEN location may be the source: a code that merely RESOLVES (the broad
     alias 'East Midlands' -> the UKF aggregate) is refused, because resolving a label is
     not proving a location;
  4. a property that cannot be bound keeps its stated label and is disclosed;
  5. every change is traceable - meta.regionHarmonised, a ledger row carrying the stated
     value, and a Gaps line;
  6. idempotent, and `regionCode` is never touched.

The live corpus is exercised for real: the four delivered Corby coordinates are run through
the bundled NUTS-3 polygons, so this fails if the geo asset or the bind ever stops putting
them in one area. Offline (bundled assets only), no network, no work dir."""
from __future__ import annotations
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import enrich as E  # noqa: E402

# The four properties as delivered on 2026-08-03: coordinates from the tracker's
# 'Latitude, Longitude' column, regions as source precedence left them.
CORBY = [
    {"id": 1, "park": "EVO Corby 169", "city": "Corby", "region": "Northamptonshire",
     "lat": 52.50304981, "lng": -0.650581854},
    {"id": 2, "park": "Rockingham 161", "city": "Corby", "region": "Northamptonshire",
     "lat": 52.50479792, "lng": -0.698356033},
    {"id": 3, "park": "Saxon 132", "city": "Corby", "region": "East Midlands",
     "lat": 52.46850533, "lng": -0.737056454},
    {"id": 4, "park": "Raven Park", "city": "Corby", "region": "East Midlands",
     "lat": 52.5113515746894, "lng": -0.7051011759664334},
]


def canon(props):
    return {"properties": copy.deepcopy(props), "meta": {"client": "T", "hero": {}}}


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    ds = E._regions_dataset()
    if not ds:
        print("  [FAIL] the bundled regions dataset did not load")
        return 1

    # ---- 0. the live corpus really does bind to ONE area ----------------------------
    print("the real Corby coordinates, through the bundled NUTS-3 polygons:")
    c = canon(CORBY)
    E.bind_region_codes(c, ds)
    codes = {p.get("regionCode") for p in c["properties"]}
    ck(codes == {"UKF25"},
       f"all four bind to one NUTS-3 area by point-in-polygon (got {sorted(codes)})")
    ck((ds["regions"].get("UKF25") or {}).get("name") == "North Northamptonshire",
       "...named 'North Northamptonshire' in the dataset")
    ck(len({p["region"] for p in c["properties"]}) == 2,
       "...while the STATED labels are still two different levels at this point")

    # ---- 1. the repair ---------------------------------------------------------------
    print("\nharmonisation:")
    gaps, updates = [], []
    codes_at_bind = [p.get("regionCode") for p in c["properties"]]
    n = E.harmonise_regions(c, ds, gaps, updates)
    # captured BEFORE the call that actually changes things: asserting this after a
    # second (no-op) call would pass even if harmonisation clobbered the code.
    ck([p.get("regionCode") for p in c["properties"]] == codes_at_bind == ["UKF25"] * 4,
       "the LABEL is harmonised and regionCode is left exactly as the bind set it")
    # ALL FOUR change, not just the 2/2 minority - and that is the rule, not an accident.
    # The authority is the bind, and the bind yields ONE name ('North Northamptonshire',
    # the current unitary authority). It differs from BOTH stated labels, so aligning to it
    # necessarily moves every property. Harmonising only the minority would mean picking a
    # winner between two sourced labels, which is the majority vote this design rejected:
    # a tie at 2/2, and no parent/child test in the bundled data that could break it.
    ck(n == 4, f"every property is aligned to the bind, not just the minority (got {n})")
    ck({p["region"] for p in c["properties"]} == {"North Northamptonshire"},
       "every property now reports the same region")
    ck(len(gaps) == 1 and "more than one administrative level" in gaps[0],
       "one Gaps line, naming the defect")
    ck("Northamptonshire" in gaps[0] and "East Midlands" in gaps[0]
       and "North Northamptonshire" in gaps[0],
       "...naming both stated levels AND the bound name")
    ck("Source Ledger" in gaps[0],
       "...and saying where the stated values are preserved")

    # ---- 2. disclosure --------------------------------------------------------------
    print("\ndisclosure:")
    rh = c["meta"].get("regionHarmonised")
    ck(isinstance(rh, list) and len(rh) == 4, "meta.regionHarmonised records each change")
    ck(all({"id", "stated", "bound", "code"} <= set(e) for e in rh),
       "...with id, stated, bound and code on every entry")
    ck({e["stated"] for e in rh} == {"Northamptonshire", "East Midlands"}
       and {e["bound"] for e in rh} == {"North Northamptonshire"}
       and {e["id"] for e in rh} == {1, 2, 3, 4},
       "...stated -> bound is recorded truthfully, per property id")
    ck(len(updates) == 4 and all(u["field"] == "region" for u in updates),
       "one ledger row per change")
    ck({("Northamptonshire" if "East Midlands" not in u["conflict_note"] else "East Midlands")
        for u in updates} == {"Northamptonshire", "East Midlands"}
       and all(u["conflict_note"].startswith("harmonised") for u in updates),
       "...each carrying the value ITS OWN source stated, not a single blanket note")
    ck(all(u["extractor"] == "enrich" and u["source_type"] == "web" for u in updates),
       "...attributed to enrichment, not to a client source file")
    ck(all("UKF25" in u["source_file"] for u in updates),
       "...citing the bound NUTS-3 code")
    ck(all(str(u["source_locator"]).startswith("NUTS-3 area containing") for u in updates),
       "...and the locator states it was decided by the property's own coordinates")
    ck(json.dumps(c["meta"]["regionHarmonised"]) and True,
       "meta.regionHarmonised is JSON-serialisable (it ships in canonical.json)")

    # ---- 3. THE NO-OP GATE: a coherent dataset is untouched -------------------------
    print("\na coherent dataset is a provable no-op:")
    for label in ("Northamptonshire", "East Midlands", "North Northamptonshire"):
        c2 = canon([dict(p, region=label) for p in CORBY])
        E.bind_region_codes(c2, ds)
        before = json.dumps(c2, sort_keys=True)
        g2, u2 = [], []
        n2 = E.harmonise_regions(c2, ds, g2, u2)
        ck(n2 == 0 and json.dumps(c2, sort_keys=True) == before and not g2 and not u2,
           f"all four already saying {label!r} -> byte-identical, no gap, no ledger row")
    c3 = canon([dict(p, region="") for p in CORBY])
    E.bind_region_codes(c3, ds)
    ck(E.harmonise_regions(c3, ds, [], []) == 0,
       "no stated region anywhere -> nothing to harmonise")

    # ---- 4. a blank region is a gap, not a level -----------------------------------
    print("\nblanks and sentinels:")
    mixed = [dict(CORBY[0]), dict(CORBY[1]), dict(CORBY[2], region=""),
             dict(CORBY[3], region="tbd")]
    c4 = canon(mixed)
    E.bind_region_codes(c4, ds)
    g4, u4 = [], []
    E.harmonise_regions(c4, ds, g4, u4)
    ck(c4["properties"][2]["region"] == "" and c4["properties"][3]["region"] == "tbd",
       "a blank and a 'tbd' are left alone (a gap is not an administrative level)")
    ck(not g4 and not u4,
       "...and with only ONE real level stated, nothing is harmonised at all")
    # the same thing with the gate genuinely OPEN: two real levels present, so the rewrite
    # loop runs - and must still step over the blank and the sentinel. (The fixture above
    # cannot show this: it early-returns, so it passed even when the skip was removed.)
    mixed2 = [dict(CORBY[0]), dict(CORBY[1], region="East Midlands"),
              dict(CORBY[2], region=""), dict(CORBY[3], region="tbd")]
    c4b = canon(mixed2)
    E.bind_region_codes(c4b, ds)
    g4b, u4b = [], []
    n4b = E.harmonise_regions(c4b, ds, g4b, u4b)
    ck(n4b == 2 and {e["id"] for e in c4b["meta"]["regionHarmonised"]} == {1, 2},
       f"with the gate open, only the two properties that STATED a level change (got {n4b})")
    ck(c4b["properties"][2]["region"] == "" and c4b["properties"][3]["region"] == "tbd",
       "...the blank and the 'tbd' are still untouched, though both bind to UKF25")
    ck(E._stated_region({"region": "tbd"}) == ""
       and E._stated_region({"region": "??"}) == ""
       and E._stated_region({"region": " Kent "}) == "Kent",
       "_stated_region treats sentinels as absent and trims a real label")

    # ---- 4b. a genuinely MULTI-REGION longlist is not an incoherence ----------------
    # More than one distinct label is the TRIGGER for inspection, not the finding. A
    # longlist spanning two real regions has two labels and is perfectly coherent, so
    # nothing may be rewritten and - just as important - nothing may be REPORTED. A gap
    # line here would be a false claim in the honesty document.
    print("\na legitimately multi-region longlist:")
    multi = [{"id": 1, "city": "Corby", "region": "North Northamptonshire",
              "lat": 52.50304981, "lng": -0.650581854},
             {"id": 2, "city": "Doncaster",
              "region": "Barnsley, Doncaster and Rotherham",
              "lat": 53.5228, "lng": -1.1285}]
    c4c = canon(multi)
    E.bind_region_codes(c4c, ds)
    ck([p["regionCode"] for p in c4c["properties"]] == ["UKF25", "UKE31"],
       "the two properties bind to two DIFFERENT NUTS-3 areas")
    before4c = json.dumps(c4c, sort_keys=True)
    g4c, u4c = [], []
    n4c = E.harmonise_regions(c4c, ds, g4c, u4c)
    ck(n4c == 0 and json.dumps(c4c, sort_keys=True) == before4c,
       "...each label already matches its OWN bind, so nothing is rewritten")
    ck(not g4c and not u4c and "regionHarmonised" not in c4c["meta"],
       "...and nothing is reported: two labels is not evidence of a defect")

    # ---- 5. only a PROVEN location may be the source -------------------------------
    print("\na resolvable label is not a proven location:")
    # No coordinates at all: merge.py derives regionCode from the LABEL, so these codes are
    # the literal strings. 'East Midlands' RESOLVES via _dataset_region (the UKF aggregate)
    # but is not a key in ds['regions'], so it must NOT be used to rewrite anybody.
    noco = [{"id": 1, "city": "Corby", "region": "Northamptonshire",
             "regionCode": "Northamptonshire"},
            {"id": 2, "city": "Corby", "region": "East Midlands",
             "regionCode": "East Midlands"}]
    c5 = canon(noco)
    g5, u5 = [], []
    n5 = E.harmonise_regions(c5, ds, g5, u5)
    ck(E._dataset_region(ds, "East Midlands") is not None,
       "'East Midlands' does resolve (the curated UKF alias)")
    ck("East Midlands" not in ds["regions"],
       "...but it is NOT a NUTS-3 province key")
    ck(n5 == 0 and [p["region"] for p in c5["properties"]]
       == ["Northamptonshire", "East Midlands"],
       "-> nothing is rewritten from a merely-resolvable code")
    ck(not u5, "...and no ledger row claims a bind that never happened")
    # The fixture above is not enough on its own: 'East Midlands' resolves to an aggregate
    # NAMED 'East Midlands', so accepting a resolvable code would be a no-op there and the
    # assertion passed even with the guard removed. This one resolves to a DIFFERENT name
    # ('Greater London' -> the UKI aggregate, displayed 'London'), so a dropped guard shows.
    ck((E._dataset_region(ds, "Greater London") or {}).get("name") == "London",
       "'Greater London' resolves to an aggregate displayed under a DIFFERENT name")
    alias = [{"id": 1, "city": "London", "region": "Greater London",
              "regionCode": "Greater London"},
             {"id": 2, "city": "Corby", "region": "East Midlands",
              "regionCode": "East Midlands"}]
    c5b = canon(alias)
    u5b: list = []
    n5b = E.harmonise_regions(c5b, ds, [], u5b)
    ck(n5b == 0 and c5b["properties"][0]["region"] == "Greater London" and not u5b,
       "-> a code that resolves to a differently-named aggregate still rewrites nobody")

    # ---- 6. an unbindable property keeps its label, and is disclosed ---------------
    print("\npartial binds:")
    part = [dict(CORBY[0]), dict(CORBY[1]),
            {"id": 3, "city": "Kettering", "region": "East Midlands"},   # no coords
            dict(CORBY[3])]
    c6 = canon(part)
    E.bind_region_codes(c6, ds)
    g6, u6 = [], []
    n6 = E.harmonise_regions(c6, ds, g6, u6)
    ck(n6 == 3, f"the three bindable properties are aligned to the bind (got {n6})")
    ck(c6["properties"][2]["region"] == "East Midlands",
       "the unbindable property keeps the label its source stated")
    ck(len(g6) == 1 and "could not be bound" in g6[0] and "1 property" in g6[0],
       "...and the Gaps line says so, with a count")

    # ---- 7. idempotence, and regionCode is never touched ---------------------------
    print("\nidempotence:")
    codes_before = [p.get("regionCode") for p in c["properties"]]
    g7, u7 = [], []
    n7 = E.harmonise_regions(c, ds, g7, u7)
    ck(n7 == 0 and not g7 and not u7,
       "a second call on the harmonised dataset changes nothing and says nothing")
    ck([p.get("regionCode") for p in c["properties"]] == codes_before,
       "regionCode is never modified by harmonisation (the workforce bind is untouched)")
    ck(E.harmonise_regions(canon(CORBY), None, [], []) == 0,
       "no dataset -> no-op (never crash a run over a missing asset)")

    # ---- 8. the call site is inside the --regions branch, after the bind ----------
    print("\nwiring:")
    src = (ROOT / "helpers" / "enrich.py").read_text(encoding="utf-8")
    i_branch = src.find("if args.regions:")
    i_bind = src.find("bind_region_codes(canonical", i_branch)
    # searched from the BRANCH, not from the bind: searching from i_bind would make a call
    # placed BEFORE the bind invisible, which is the exact ordering bug this pins.
    i_harm = src.find("harmonise_regions(canonical", i_branch)
    i_merge = src.find("merge_regions(canonical", i_branch)
    ck(i_branch != -1 and i_bind != -1 and i_harm != -1,
       "enrich calls harmonise_regions inside the --regions branch")
    ck(i_bind < i_harm < i_merge,
       "...AFTER bind_region_codes (nothing to work from before) and before the profile match")
    calls = [m.start() for m in re.finditer(r"(?<!def )harmonise_regions\(canonical", src)]
    ck(len(calls) == 1 and calls[0] == i_harm,
       f"...exactly once, so no earlier call can shadow the ordering (found {len(calls)})")
    ck("--ledger" in src and "updates" in src[i_harm:i_harm + 200],
       "...and passes the ledger updates list, so every change gets a trace row")

    if fails:
        print(f"\nREGION HARMONY TEST: FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nREGION HARMONY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
