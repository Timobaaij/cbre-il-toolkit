#!/usr/bin/env python3
"""excluded_conflict_disclosure_test.py - a suppressed conflicting record is DISCLOSED.

The silent-conflict class (live run): a tracker and a brochure described the same
plot with a >15% size gap, so the forbidden tier kept them from clustering; the
broker's source-authority answer then dropped the brochure's cluster. The option-
level B47 disclosure never fired (the option SURVIVED via the tracker), so the
brochure's figure vanished: no card, no conflict note, no ledger row, no Gaps line.

Pinned here: apply_source_authority carries each dropped cluster's own headline
figures, links it (via match.pair_class, forbidden/grey) to the kept cluster it
plausibly IS, and the Gaps Report prints the two figures side by side. Offline.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
import match  # noqa: E402
import merge  # noqa: E402
import deliver  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


tracker_rec = {"park": "Alpha Park South", "city": "Lutterworth",
               "warehouseArea": 356202, "areaUnit": "sq ft",
               "__meta": {"source_file": "tracker.xlsx", "source_type": "xlsx"}}
brochure_rec = {"park": "Alpha Park South", "city": "Lutterworth",
                "warehouseArea": 230000, "areaUnit": "sq ft",
                "__meta": {"source_file": "brochure.pdf", "source_type": "pdf"}}

# precondition: the size gap makes this pair FORBIDDEN (never merged)
check("pair-forbidden", match.pair_class(tracker_rec, brochure_rec) == "forbidden")
clusters = match.dedupe([tracker_rec, brochure_rec])
check("two-clusters", len(clusters) == 2)

kept, dropped = merge.apply_source_authority(clusters, "tracker")
check("kept-one", len(kept) == 1 and kept[0][0] is tracker_rec)
check("dropped-one", len(dropped) == 1)
e = dropped[0]

# the dropped entry carries its OWN figure and the linkage to the shipped card
check("headline-area", (e.get("headline") or {}).get("warehouseArea") == 230000)
ls = e.get("likely_same_as") or {}
check("linked", "Alpha Park South" in str(ls.get("name")))
check("linked-tier", ls.get("tier") == "forbidden")
check("linked-kept-area", (ls.get("kept_headline") or {}).get("warehouseArea") == 356202)

# and the Gaps Report prints the two figures side by side
canonical = {"meta": {"excluded": dropped, "units": {}}, "properties": [
    {"id": "p1", "park": "Alpha Park South", "city": "Lutterworth",
     "warehouseArea": 356202, "areaUnit": "sq ft"}]}
report = deliver.gaps_report(canonical, "TestClient")
check("gaps-line", "LOOKS LIKE SHIPPED OPTION" in report)
check("gaps-mine", "230,000 sq ft" in report)
check("gaps-theirs", "356,202 sq ft" in report)
check("gaps-why", "size conflict" in report)

# an excluded cluster with NO plausible kept twin stays a plain option line
lone = {"park": "Zeta Logistics Hub", "city": "Aberdeen",
        "warehouseArea": 12000, "areaUnit": "sq m",
        "__meta": {"source_file": "lone.pdf", "source_type": "pdf"}}
kept2, dropped2 = merge.apply_source_authority(match.dedupe([tracker_rec, lone]), "tracker")
check("lone-dropped", len(dropped2) == 1)
check("lone-unlinked", "likely_same_as" not in dropped2[0])

# BOTH-SHIPPED forbidden pair (union mode): the pair the LLM never sees and the
# dedupe gate cannot compare gets ONE Source-conflicts line with both figures
lines = merge.shipped_forbidden_conflicts(clusters)
check("shipped-conflict", len(lines) == 1)
check("shipped-figures", "230,000 sq ft" in lines[0] and "356,202 sq ft" in lines[0])
check("shipped-wording", "SAME building" in lines[0])

# unrelated clusters produce NO conflict line (identity is required, not just size)
check("no-unrelated-conflict",
      merge.shipped_forbidden_conflicts(match.dedupe([tracker_rec, lone])) == [])

# a same-file forbidden pair (two units of one scheme) is distinct BY DESIGN - no line
u1 = {"park": "Alpha Park South", "city": "Lutterworth", "warehouseArea": 100000,
      "areaUnit": "sq ft", "__meta": {"source_file": "park_deck.pdf", "source_type": "pdf"}}
u2 = {"park": "Alpha Park South", "city": "Lutterworth", "warehouseArea": 200000,
      "areaUnit": "sq ft", "__meta": {"source_file": "park_deck.pdf", "source_type": "pdf"}}
check("no-samefile-conflict",
      merge.shipped_forbidden_conflicts(match.dedupe([u1, u2])) == [])

# headline pairs figure + unit from the SAME record: a sibling's unit must never
# label another record's magnitude (a possible 10.76x mislabel in the very line
# meant to settle the figure)
hl = merge._cluster_headline([{"warehouseArea": 230000},
                              {"areaUnit": "sq m", "city": "Corby"}])
check("headline-same-record-unit", hl.get("warehouseArea") == 230000
      and "areaUnit" not in hl)

# _likely_same_kept never links across the SAME source file (two units of one
# scheme are distinct by design)
check("no-samefile-link",
      merge._likely_same_kept([u1], [[u2]]) is None)

print("EXCLUDED CONFLICT DISCLOSURE TEST: PASS")
