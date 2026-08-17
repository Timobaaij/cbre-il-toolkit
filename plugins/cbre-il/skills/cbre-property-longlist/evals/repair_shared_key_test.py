#!/usr/bin/env python3
"""repair_shared_key_test.py - a shared match key must not defeat a correct `id`. (B61)

A match key is city|developer|park, so every multi-unit park produces several properties with
the SAME key - three units in Pol. Ind. Ciudad del Transporte, two plots in Pol. Ind. Urban II.
The repair contract tells you to give `key` AND `id`, but `_resolve` compared only the FIRST
hit of each (`by_key[0] != by_id[0]`), so `by_key=[5,6,7]` beside `by_id=[6]` read as a
key/id disagreement and the entry applied NOTHING. On a live run three repairs returned
AMBIGUOUS and two sub-agents independently worked out that the fix was to drop the very field
the documentation says always to supply.

What this pins:
  * an id INSIDE the key's matches disambiguates a shared key and resolves;
  * an id OUTSIDE them is a genuine conflict and still fails closed as AMBIGUOUS;
  * a shared key with NO id is still AMBIGUOUS - the id is what disambiguates, not luck;
  * id-only and key-only entries are unchanged;
  * the repair lands on the id's property and on NOTHING else.
Offline; no network, no build.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


SHARED = "marchamalo|tbd|pol ind ciudad del transporte"


def canon():
    """Three units in ONE park (so they share a match key) plus an unrelated property."""
    def unit(i, area):
        # developer is the honest sentinel, as merge writes it when no source names one -
        # which is exactly the corpus that produces shared keys in the first place
        return {"id": i, "park": "Pol. Ind. Ciudad del Transporte", "city": "Marchamalo",
                "developer": "tbd", "country": "ES", "warehouseArea": area,
                "areaUnit": "sq m", "status": "Available", "photo": "x", "gallery": ["x"]}
    return {"meta": {"client": "T", "units": {"area": "sq m"}}, "pois": [], "regions": {},
            "properties": [unit(5, 10000), unit(6, 20000), unit(7, 30000),
                           {"id": 9, "park": "Alpha Park", "city": "Bor", "developer": "CTP",
                            "country": "CZ", "warehouseArea": 40000, "areaUnit": "sq m",
                            "status": "Available", "photo": "x", "gallery": ["x"]}]}


def entry(prop):
    return [{"id": "rp-001", "property": prop, "set": {"status": "Upcoming construction"},
             "why": "page 5 prints 'Proxima construccion'", "verified_by": "t@cbre.com"}]


def main() -> int:
    print("repair_shared_key_test - the id disambiguates a key several properties share")

    ck(R._mk(canon()["properties"][0]) == SHARED,
       f"three units in one park really do share the key {SHARED!r}")

    c = canon()
    r = R.apply(c, entry({"key": SHARED, "id": 6}))
    ck(len(r["applied"]) == 1 and not r["ambiguous"],
       "key+id, key shared by three: the id disambiguates and the repair APPLIES")
    got = {p["id"]: p["status"] for p in c["properties"]}
    ck(got[6] == "Upcoming construction",
       "it landed on the id's property")
    ck(got[5] == "Available" and got[7] == "Available" and got[9] == "Available",
       "and on NOTHING else - the two key-twins and the unrelated property are untouched")

    c = canon()
    r = R.apply(c, entry({"key": SHARED, "id": 9}))
    ck(not r["applied"] and len(r["ambiguous"]) == 1,
       "key+id naming DIFFERENT properties is still a conflict - AMBIGUOUS, fail closed")
    ck(all(p["status"] == "Available" for p in c["properties"]),
       "and nothing was written")

    c = canon()
    r = R.apply(c, entry({"key": SHARED}))
    ck(not r["applied"] and len(r["ambiguous"]) == 1,
       "a shared key with NO id stays AMBIGUOUS - the id is what resolves it")

    c = canon()
    r = R.apply(c, entry({"id": 7}))
    ck(len(r["applied"]) == 1 and c["properties"][2]["status"] == "Upcoming construction",
       "id alone still resolves uniquely (unchanged)")

    c = canon()
    r = R.apply(c, entry({"key": "bor|ctp|alpha park", "id": 9}))
    ck(len(r["applied"]) == 1 and c["properties"][3]["status"] == "Upcoming construction",
       "a unique key + its own id is unchanged")

    c = canon()
    r = R.apply(c, entry({"key": "nowhere|none|no such park", "id": None}))
    ck(not r["applied"] and len(r["stale"]) == 1, "a key matching nothing is still STALE")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
