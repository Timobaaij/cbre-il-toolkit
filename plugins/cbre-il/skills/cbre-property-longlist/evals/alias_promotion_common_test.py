#!/usr/bin/env python3
"""alias_promotion_common_test.py - the ONE strict alias table and its helpers in `_common`. (3.5a,
3.3, 3.17 part 4; 2026-09-26 test run)

THE DEFECT. Readers held stated values under descriptive keys (`levelAccessDoors`, `availableFrom`)
while the canonical homes (`overheadDoors`, `earlyAccess`) shipped "absent in all sources"; seven hand
repairs moved them. The only alias knowledge was capture-symmetry's shadow registry - deliberately
LOOSE for tracker headers ('asset manager' -> landlord, 'practical completion' -> earlyAccess) and
therefore unsafe to act on. `_common` now carries ONE curated table of EXACT synonyms that merge
promotes on and the gate treats as strict, plus a pinned list of names that must NEVER promote.

Pinned here (pure, no merge): the table's shape and normal form; `alias_norm` is the gate's own fold;
`promotable_alias` accepts the measured shapes and refuses every unsafe one (refused names, a
door total, a count with no digit, a 'let agreed' date, sentinels, locators, data URIs, non-scalars,
'_' keys); the two tables are disjoint; every strict alias of a field the gate judges pairs through
`gate_runner.shadow_pairs` (so the gate table is a superset of merge's); `normalize.AVAIL_TAKEN_RX`
is merge's taken-words regex; `COUNT_FIELDS` is the four count fields; and the 3.17 render guard maps
the pre-v45 'tbd' spelling to the one BLANK on ANY key while leaving a source's own 'n/a' alone.
Offline. Run: python evals/alias_promotion_common_test.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C        # noqa: E402
import gate_runner as G    # noqa: E402
import normalize as N      # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def camel(phrase: str) -> str:
    w = phrase.split()
    return w[0] + "".join(x[:1].upper() + x[1:] for x in w[1:])


def main() -> int:
    print("1. the tables")
    ck(C.COUNT_FIELDS == frozenset({"loadingDocks", "overheadDoors", "truckParking", "carParking"}),
       "COUNT_FIELDS is the four count fields (one constant)")
    ck(isinstance(C.ALIAS_PROMOTIONS, dict) and all(isinstance(v, tuple) and v for v in C.ALIAS_PROMOTIONS.values()),
       "ALIAS_PROMOTIONS is {canonical field: tuple of phrases}")
    bad_form = [(f, a) for f, ph in C.ALIAS_PROMOTIONS.items() for a in ph if C.alias_norm(a) != a]
    ck(not bad_form, f"every phrase is already in alias_norm form ({bad_form or 'all'})")
    prom = {C.alias_norm(a) for ph in C.ALIAS_PROMOTIONS.values() for a in ph}
    refu = {C.alias_norm(a) for ph in C.ALIAS_PROMOTION_REFUSED.values() for a in ph}
    ck(not (prom & refu), f"the promote and refuse tables are disjoint ({sorted(prom & refu)})")
    ck(set(C.ALIAS_PROMOTIONS) <= set(C.canonical_property_fields()),
       "every promotion target is a canonical property field")

    print("\n2. alias_norm is the gate's own fold")
    sample = ["levelAccessDoors", "LevelAccessDoors4x5m", "availableFrom", "epcRating", "zipCode",
              "hgvParkingSpaces", "dockDoors", "déjàVu", "carParkSpaces", "", "x", "Doors"]
    diff = [k for k in sample if C.alias_norm(k) != G._shadow_norm(G._humanise_key(k))]
    ck(not diff, f"alias_norm(k) == gate _shadow_norm(_humanise_key(k)) on every sample ({diff or 'all'})")
    ck(C.alias_norm(None) == "" and C.alias_norm(12) == "12", "a non-string key folds without raising")

    print("\n3. promotable_alias - the measured shapes promote")
    for key, val, want in (("levelAccessDoors", "4", "overheadDoors"),
                           ("groundLevelDoors", 2, "overheadDoors"),
                           ("dockLevelDoors", "12", "loadingDocks"),
                           ("availableFrom", "Q2 2027", "earlyAccess"),
                           ("postalCode", "NN1 1AA", "postcode"),
                           ("epcRating", "A+", "epc"),
                           ("carParkingSpaces", 72, "carParking"),
                           ("hgvParking", "40 spaces", "truckParking"),
                           ("clearInternalHeight", "12 m", "clearHeight")):
        ck(C.promotable_alias(key, val) == want, f"{key}={val!r} -> {want}")

    print("\n4. promotable_alias - every unsafe shape refuses")
    for f, names in C.ALIAS_PROMOTION_REFUSED.items():
        for a in names:
            k = camel(a)
            ck(C.promotable_alias(k, "4 units 2026") is None, f"refused name `{k}` never promotes")
    for key, val, why in (("loadingDoors", "6", "an UNSPLIT door total is neither door field"),
                          ("doors", "6", "a bare 'doors' total"),
                          ("levelAccessDoors", "yes", "a count with no digit"),
                          ("levelAccessDoors", "None", "a stated 'None' carries no count"),
                          ("availableFrom", "Let agreed May 2026", "a TAKEN date"),
                          ("availableFrom", "Sold 2025", "a TAKEN date"),
                          ("levelAccessDoors", "tbd", "a sentinel"),
                          ("levelAccessDoors", "page 4", "a locator string"),
                          ("levelAccessDoors", "data:image/png;base64,AAAA", "a data URI"),
                          ("levelAccessDoors", True, "a bool"),
                          ("levelAccessDoors", {"n": 4}, "a dict"),
                          ("levelAccessDoors", None, "None"),
                          ("_levelAccessDoors", "4", "a '_' key"),
                          ("motorwayDriveTime", "25 minutes", "an unrelated key"),
                          (None, "4", "a non-str key")):
        ck(C.promotable_alias(key, val) is None, f"{key}={val!r}: refused ({why})")

    print("\n5. the gate table is a superset of merge's")
    reg = G._shadow_registry()
    unpaired = [(f, a) for f, ph in C.ALIAS_PROMOTIONS.items() if f in reg for a in ph
                if not any(p["field"] == f for p in G.shadow_pairs(camel(a), "4 units 2026", {f}))]
    ck(not unpaired, f"every strict alias of a gate-judged field pairs in shadow_pairs ({unpaired or 'all'})")
    tab = G._strict_alias_table()
    ck(tab.get("overheadDoors") and "level access door" in tab["overheadDoors"],
       "the gate reads the same table as its strict tier")

    print("\n6. normalize.AVAIL_TAKEN_RX is merge's taken-words regex")
    try:
        import merge as M  # noqa: E402
        mr = getattr(M, "_AVAIL_TAKEN_RX", None)
        ck(mr is not None and mr.pattern == N.AVAIL_TAKEN_RX.pattern and mr.flags == N.AVAIL_TAKEN_RX.flags,
           "same pattern and flags (merge aliases it or carries the identical copy)")
    except Exception as e:
        ck(False, f"merge importable to compare ({type(e).__name__}: {e})")
    ck(bool(N.AVAIL_TAKEN_RX.search("UNDER OFFER")) and not N.AVAIL_TAKEN_RX.search("Available Q3"),
       "case-insensitive, and silent on an access date")

    print("\n7. the render guard (3.17 part 4)")
    p = C.fill_render_sentinels({"id": 7, "epc": "tbd", "gatehouse": " TBD ", "yardDepth": "n/a",
                                 "__meta": {"x": "tbd"}, "loadingDocks": 4})
    ck(p["epc"] == N.BLANK and p["gatehouse"] == N.BLANK,
       f"'tbd' on ANY key renders as the one BLANK ({p['epc']!r}, {p['gatehouse']!r})")
    ck(p["yardDepth"] == "n/a", "a source's own 'n/a' on an open key stays verbatim")
    ck(p["id"] == 7 and p["__meta"] == {"x": "tbd"} and p["loadingDocks"] == "4",
       "id and __meta untouched; the numeric coercion still runs")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
