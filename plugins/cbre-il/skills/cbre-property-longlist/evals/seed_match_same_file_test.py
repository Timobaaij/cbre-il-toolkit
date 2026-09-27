#!/usr/bin/env python3
"""seed_match_same_file_test.py - a duplicate group never seeds `same` between two units of ONE
multi-record deck. (2026-09-26 test run, fix 3.25.)

THE DEFECT. `seed_match_decisions` turns each master-list duplicate group into `same` verdicts
for every pair of records the group's rows map to. A deck row maps to EVERY record read from its
file, so a group holding a four-unit park brochure seeded `same` between its own units - four
separate options merged on the strength of a verdict nobody gave.

WHAT THIS PINS
  * a group of (a four-unit deck row, a tracker row): NO pair between two of the deck's units;
  * the deck-unit -> tracker pairs the broker's group does express are still seeded;
  * two tracker rows from ONE file that the broker grouped by hand are still seeded - each was
    named by its own row, so the guard does not swallow a real decision.
Offline; match.pair_id is the key, exactly as the spine mints it.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import master_list as ML  # noqa: E402
import match as MATCH  # noqa: E402

FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _rec(src, park, area, loc=None, st="pdf"):
    m = {"source_file": src, "source_type": st}
    if loc:
        m["prov"] = {"park": f"{loc} (tracker)"}
    return {"park": park, "city": "Sometown", "warehouseArea": area, "areaUnit": "sq m",
            "__meta": m}


def main() -> int:
    deck = "Harbour Park units 1-4.pdf"
    units = [_rec(deck, f"Harbour Park Unit {n}", n * 5000) for n in (1, 2, 3, 4)]
    # The tracker lines deliberately differ from every deck unit in name AND area: pair_id keys
    # on (match_key + area), and an exact twin would make a unit pair and a unit-tracker pair
    # the SAME id, which says nothing about the guard.
    trk = [_rec("Tracker.xlsx", "Harbour Pk 2 (tracker)", 10250, "Sheet1!B5", "xlsx"),
           _rec("Tracker.xlsx", "Harbour Pk U2", 10300, "Sheet1!B9", "xlsx"),
           _rec("Tracker.xlsx", "Quay Road", 7000, "Sheet1!B11", "xlsx")]
    work = Path(tempfile.mkdtemp(prefix="cbre_seed_"))
    rows = [
        {"row_id": ML.deck_row_id(deck), "include": "Yes", "source_files": [deck],
         "duplicate_group": "D1"},
        {"row_id": ML.record_row_id(trk[0]), "include": "Yes", "source_files": ["Tracker.xlsx"],
         "duplicate_group": "D1"},
        {"row_id": ML.record_row_id(trk[1]), "include": "Yes", "source_files": ["Tracker.xlsx"],
         "duplicate_group": "D2"},
    ]
    # D2 = the two tracker lines the broker says are one building; the first tracker line is
    # therefore in D1 (with the deck) AND named again for D2 through a second row below.
    rows.append({"row_id": ML.record_row_id(trk[0]), "include": "Yes",
                 "source_files": ["Tracker.xlsx"], "duplicate_group": "D2"})
    (work / ML.ANSWERS).write_text(json.dumps({"input_hash": "x", "rows": rows}),
                                   encoding="utf-8")
    seed = ML.seed_match_decisions(units + trk, work)
    unit_pairs = {MATCH.pair_id(a, b) for i, a in enumerate(units) for b in units[i + 1:]}
    ck(not (unit_pairs & set(seed)),
       f"no `same` between two units of one deck ({len(unit_pairs & set(seed))} seeded)")
    ck(all(MATCH.pair_id(u, trk[0]) in seed for u in units),
       "the deck-to-tracker pairs the group expresses are still seeded")
    ck(MATCH.pair_id(trk[0], trk[1]) in seed,
       "two tracker lines of ONE file grouped by the broker are still seeded (their decision)")
    ck(MATCH.pair_id(trk[0], trk[2]) not in seed and MATCH.pair_id(trk[1], trk[2]) not in seed,
       "an ungrouped line contributes nothing")
    ck(all(v.get("verdict") == "same" and "master list" in v.get("reason", "")
           for v in seed.values()), "every seeded verdict is `same`, attributed to the broker")

    print()
    if FAILS:
        print(f"SEED SAME-FILE TEST: FAIL ({len(FAILS)})")
        return 1
    print("SEED SAME-FILE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
