#!/usr/bin/env python3
"""expect_sentinel_test.py - `expect` must be able to say "this field is unknown". (B61)

Both correction paths invite you to guard an entry with `expect`, and both compared the
current value to the expected one as strings. A field a plausibility gate struck holds
`None`, but every surface a human reads - the card, the Source Ledger, the Gaps Report,
work/properties/<id>/notes.md - renders it `tbd`. So the guard could never match the value
the documentation tells you to write, and a live run lost a batch of 17 repairs plus a full
re-run to `expect said warehouseArea=='tbd' but the property now holds warehouseArea==None`.

What this pins:
  * absence is ONE bucket for the guard: None/''/tbd/tbc/-/n/a/none/?? all match each other,
    in repairs.json and in overrides.json alike;
  * the guard still FIRES on real drift - a field that now holds a different STATED value
    supersedes exactly as before, which is the whole point of having it;
  * a market phrase ("A consultar") is NOT absence here: normalize.looks_unknown carries it,
    but this set is deliberately narrower so the guard can still notice one;
  * `_same` itself is unchanged, so nothing outside the guard moved.
Offline; no network, no build.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402
import merge as M                        # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def canon(**over):
    p = {"id": 1, "park": "Alpha Park", "city": "Bor", "developer": "CTP", "country": "CZ",
         "areaUnit": "sq m", "status": "Available", "photo": "x", "gallery": ["x"]}
    p.update(over)
    return {"meta": {"client": "T", "units": {"area": "sq m"}}, "pois": [], "regions": {},
            "properties": [p]}


def rep(expect, sets=None):
    return [{"id": "rp-001", "property": {"key": "bor|ctp|alpha park", "id": 1},
             "expect": expect, "set": sets or {"warehouseArea": 62818},
             "why": "the deck states it on page 1", "verified_by": "t@cbre.com"}]


def main() -> int:
    print("expect_sentinel_test - the absence bucket for the `expect` guard")

    # --- repairs.json --------------------------------------------------------------- #
    for want, cur, label in (("tbd", None, "expect 'tbd' vs a struck field holding None"),
                             (None, "tbd", "expect null vs a field holding the sentinel"),
                             ("tbd", "", "expect 'tbd' vs an empty string"),
                             ("—", None, "expect the em-dash sentinel vs None")):
        c = canon(warehouseArea=cur) if cur is not None else canon()
        if cur is None:
            c["properties"][0].pop("warehouseArea", None)
        r = R.apply(c, rep({"warehouseArea": want}))
        ck(len(r["applied"]) == 1 and not r["superseded"], f"repair applies: {label}")
        ck(c["properties"][0].get("warehouseArea") == 62818,
           f"the value actually landed: {label}")

    c = canon(warehouseArea=41000)
    r = R.apply(c, rep({"warehouseArea": "tbd"}))
    ck(not r["applied"] and len(r["superseded"]) == 1,
       "real drift still SUPERSEDES - a field holding a stated figure is not absence")
    ck(c["properties"][0]["warehouseArea"] == 41000, "and the drifted value is untouched")

    c = canon(warehouseRent="A consultar")
    r = R.apply(c, [{"id": "rp-002", "property": {"id": 1}, "expect": {"warehouseRent": "tbd"},
                     "set": {"warehouseRent": "EUR 45 / sq m / yr"},
                     "why": "the agent confirmed", "verified_by": "t@cbre.com"}])
    ck(not r["applied"] and len(r["superseded"]) == 1,
       "a stated market phrase is NOT absence here - the guard still fires on 'A consultar'")

    ck(R._same(None, "tbd") is False,
       "_same is UNCHANGED - the widening reaches the guard and nothing else")

    # --- overrides.json ------------------------------------------------------------- #
    ck(M._ov_expect_same(None, "tbd") and M._ov_expect_same("", None),
       "overrides: absence matches absence")
    ck(M._ov_expect_same(21759, "21759") and M._ov_expect_same(21759.0, 21759),
       "overrides: int/float/string forms of one number still match")
    ck(not M._ov_expect_same("Corby", "Northamptonshire"),
       "overrides: two different stated values still supersede")
    ck(not M._ov_expect_same("a consultar", "tbd"),
       "overrides: a market phrase is not absence either")

    # an override's `expect` guards the fields it SETS (the shape SKILL.md documents), so the
    # end-to-end cases below guard `city` while setting it
    def ov(expect):
        return [{"id": "ov-001", "where": {"source_file": "t.xlsx", "page_no": 3},
                 "expect": expect, "set": {"city": "Corby"},
                 "why": "the county sat in the city column", "verified_by": "t@cbre.com",
                 "multi": "one"}]

    recs = [{"city": None, "__meta": {"source_file": "t.xlsx", "page_no": 3}}]
    r = M.apply_overrides(recs, ov({"city": "tbd"}))
    ck(len(r["applied"]) == 1 and not r["superseded"] and recs[0]["city"] == "Corby",
       "overrides end-to-end: `expect` calling an unset field 'tbd' applies")

    recs = [{"city": "Northamptonshire", "__meta": {"source_file": "t.xlsx", "page_no": 3}}]
    r = M.apply_overrides(recs, ov({"city": "tbd"}))
    ck(not r["applied"] and len(r["superseded"]) == 1
       and recs[0]["city"] == "Northamptonshire",
       "overrides end-to-end: a field that now holds a stated value still supersedes")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
