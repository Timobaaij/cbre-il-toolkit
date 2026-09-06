#!/usr/bin/env python3
"""f24b_derived_twin_repair_test.py - a repair may not strand a derived twin. (F24c)

`repairs` runs at stage 5, AFTER merge and AFTER enrichment, and several shipped values are
DERIVED upstream with nothing re-deriving them afterwards. `officeAreaVal` is the measured
case: its schema description says it is derived by merge from `officeArea`. On a live pack
every property whose office area came through merge carried a matching float; the two whose
office area came from a repair carried None. Those two modals printed the office area as a
raw unit-less string and their Total GLA silently equalled the warehouse area with the office
excluded. Every mechanical gate was green. A correction that lands on the card and not on the
figure summed from it is the wrong-card hazard one level up.

THE REFUSAL IS SCOPED, AND THIS EVAL WAS REWRITTEN WHEN IT BECAME SO. It first refused every
twin-source repair unconditionally. That was correct in isolation and wrong in combination: a
concurrently built change registered `warehouseRent` and `warehouseRentVal` as a twin pair in
BOTH directions, so the most ordinary correction there is - fixing a rent - became impossible,
and a long-standing eval went red. Asking an operator to hand-write a number the pipeline
computes is itself how a wrong number gets typed.

So the guard now asks whether anything WILL refresh the twin. `merge.rederive_after_repairs`
does, for exactly these fields, immediately after the repairs stage; where it is present a
twin-source repair is allowed, and where it is absent (an installation carrying one half of the
fix) the refusal stands and says so accurately rather than claiming that nothing re-derives.
Both branches are pinned below, because a guard that is only ever exercised in one state is a
guard nobody knows the shape of.

What this pins (the registry is pinned to {"officeArea": "officeAreaVal"} so the eval is
meaningful whether or not merge exports `DERIVED_TWINS` yet):
  * `set` of a source field WITHOUT its twin is INVALID, names the twin in its message, and
    writes NOTHING - the property is byte-identical afterwards;
  * `set` of source AND twin in the same entry is APPLIED and both values land;
  * `set` of the twin alone is NOT refused: it is a direct correction of the derived value,
    not a stranding (whether re-derivation may overwrite it is merge's contract);
  * `unset` of a source field alone is INVALID too (the reverse hazard: the derived number
    keeps counting an office the card now calls tbd); `unset` of both, or `unset` of the
    source with the twin `set` to null, is APPLIED;
  * the DENIED message still wins over the twin message, as it wins over membership;
  * the `expect` guard still works on a correctly twinned entry;
  * the guard is checked in `load` (dataset-wide) AND in `apply` (called directly), and it is
    INERT with an empty registry rather than crashing or refusing everything;
  * the live registry is resolved from merge when merge exports one; when it does not yet,
    the eval prints a NOTE (the guard is then inert on a live run) rather than failing a file
    this eval does not own.
Offline; no network, no build.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

FAILS = []
SRC, TWIN = "officeArea", "officeAreaVal"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def canon(**over):
    p = {"id": 1, "park": "Alpha Park", "city": "Bor", "developer": "CTP", "country": "CZ",
         "areaUnit": "sq m", "status": "Available", "photo": "x", "gallery": ["x"],
         "warehouseArea": 20000, SRC: "1,200 sq m", TWIN: 1200.0}
    p.update(over)
    return {"meta": {"client": "T", "units": {"area": "sq m"}}, "pois": [], "regions": {},
            "properties": [p]}


def entry(sets=None, unset=None, expect=None, rid="rp-001"):
    e = {"id": rid, "property": {"key": "bor|ctp|alpha park", "id": 1},
         "why": "the deck states it on page 1", "verified_by": "t@cbre.com"}
    if sets is not None:
        e["set"] = sets
    if unset is not None:
        e["unset"] = unset
    if expect is not None:
        e["expect"] = expect
    return e


def main() -> int:
    print("f24b_derived_twin_repair_test - a repair to a source field must carry its twin")
    if not hasattr(R, "_stranded_twins"):
        ck(False, "repairs exposes the derived-twin guard (`_stranded_twins`)")
        print("STATUS: BLOCKED (1 failure(s))")
        return 1
    R.DERIVED_TWINS = {SRC: TWIN}          # pin, so the eval does not depend on merge

    # --- BRANCH A: nothing will re-derive, so the refusal stands ----------------------- #
    # Forced rather than mocked away: this is the state of an installation that carries the
    # repairs half of the fix without the merge half, and it is the only state in which
    # refusing is the right answer.
    _real_avail = R._rederive_available
    R._rederive_available = lambda: False
    try:
        c = canon()
        before = copy.deepcopy(c)
        r = R.apply(c, [entry(sets={SRC: "1,500 sq m"})])
        ck(not r["applied"] and len(r["invalid"]) == 1,
           "with no re-derivation available, set of the SOURCE alone is INVALID (applied nothing)")
        ck(r["invalid"] and TWIN in r["invalid"][0] and SRC in r["invalid"][0],
           f"the refusal names both the field and its twin: {r['invalid'][:1]}")
        ck(c == before, "the property is byte-identical after the refusal")
        ck(r["invalid"] and "rederive_after_repairs" in r["invalid"][0],
           "and it says WHY it refused - naming the missing capability, not asserting that "
           "nothing re-derives, which stopped being true")

        c = canon()
        before = copy.deepcopy(c)
        r = R.apply(c, [entry(unset=[SRC])])
        ck(not r["applied"] and len(r["invalid"]) == 1 and TWIN in r["invalid"][0],
           f"the reverse hazard is refused too: unset of the SOURCE alone is INVALID and names "
           f"the twin: {r['invalid'][:1]}")
        ck(c == before, "nothing was cleared by the refused unset")
    finally:
        R._rederive_available = _real_avail

    # --- BRANCH B: merge WILL re-derive, so the ordinary repair is allowed -------------- #
    ck(R._rederive_available() is True,
       "this installation's merge exposes rederive_after_repairs, so the scoped guard is off")
    c = canon()
    r = R.apply(c, [entry(sets={SRC: "1,500 sq m"})])
    ck(len(r["applied"]) == 1 and not r["invalid"],
       "a one-field repair of a twin SOURCE is APPLIED when merge will refresh the twin: this "
       "is the rent repair the unconditional refusal made impossible")
    ck(c["properties"][0][SRC] == "1,500 sq m", "and the corrected value landed")

    # --- set: source + twin in the same entry lands both ------------------------------- #
    c = canon()
    r = R.apply(c, [entry(sets={SRC: "1,500 sq m", TWIN: 1500.0})])
    p = c["properties"][0]
    ck(len(r["applied"]) == 1 and not r["invalid"], "set of source AND twin is APPLIED")
    ck(p[SRC] == "1,500 sq m" and p[TWIN] == 1500.0, "both values landed")

    # --- set: twin alone is a direct correction, not a stranding ----------------------- #
    c = canon()
    r = R.apply(c, [entry(sets={TWIN: 1250.0})])
    ck(len(r["applied"]) == 1 and not r["invalid"] and c["properties"][0][TWIN] == 1250.0,
       "set of the TWIN alone is not refused (a direct correction of the derived value)")

    # --- unset: both, or source + null twin, is applied in either branch ---------------- #
    c = canon()
    r = R.apply(c, [entry(unset=[SRC, TWIN])])
    p = c["properties"][0]
    ck(len(r["applied"]) == 1 and SRC not in p and TWIN not in p,
       "unset of source AND twin is APPLIED and both keys are removed")

    c = canon()
    r = R.apply(c, [entry(unset=[SRC], sets={TWIN: None})])
    p = c["properties"][0]
    ck(len(r["applied"]) == 1 and SRC not in p and TWIN in p and p[TWIN] is None,
       "unset of the source with the twin `set` to null is APPLIED")

    # --- DENIED still wins over the twin message --------------------------------------- #
    c = canon()
    r = R.apply(c, [entry(sets={SRC: "1,500 sq m", "areaUnit": "sq ft"})])
    ck(len(r["invalid"]) == 1 and "unit label" in r["invalid"][0] and TWIN not in r["invalid"][0],
       "a denied field in the same entry is reported as DENIED, and that message wins")

    # --- the expect guard still works on a twinned entry ------------------------------- #
    c = canon()
    r = R.apply(c, [entry(sets={SRC: "1,500 sq m", TWIN: 1500.0}, expect={SRC: "1,200 sq m"})])
    ck(len(r["applied"]) == 1, "a guarded, twinned entry whose expect holds applies")
    c = canon()
    r = R.apply(c, [entry(sets={SRC: "1,500 sq m", TWIN: 1500.0}, expect={SRC: "900 sq m"})])
    ck(len(r["superseded"]) == 1 and not r["applied"],
       "a guarded, twinned entry whose expect has drifted still SUPERSEDES")

    # --- load(): the dataset-wide screen applies the SAME scoped rule ------------------- #
    # Both branches again, because `load` and `apply` carry the guard separately (the file's
    # own duplicated-guard doctrine) and a scope that reached only one of them would be a
    # divergence of exactly the kind this remediation exists to remove.
    def _load_ids(av):
        real = R._rederive_available
        R._rederive_available = lambda: av
        try:
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "repairs.json"
                f.write_text(json.dumps([
                    entry(sets={SRC: "1,500 sq m"}, rid="rp-lone"),
                    entry(sets={SRC: "1,500 sq m", TWIN: 1500.0}, rid="rp-pair"),
                    entry(unset=[SRC], rid="rp-clear")]), encoding="utf-8")
                entries, bad = R.load(f)
                return [e["id"] for e in entries], bad
        finally:
            R._rederive_available = real

    ids, bad = _load_ids(False)
    ck(ids == ["rp-pair"], f"with no re-derivation, load keeps only the twinned entry: {ids}")
    ck(len(bad) == 2 and all(TWIN in x for x in bad),
       f"and refuses the lone set AND the lone unset, naming the twin: {bad}")

    ids, bad = _load_ids(True)
    ck(ids == ["rp-lone", "rp-pair", "rp-clear"] and not bad,
       f"with merge re-deriving, load keeps all three: the scope reaches `load` and `apply` "
       f"alike, so the two cannot disagree about what is valid: {ids}")

    # --- inert with an empty registry -------------------------------------------------- #
    R.DERIVED_TWINS = {}
    c = canon()
    r = R.apply(c, [entry(sets={SRC: "1,500 sq m"})])
    ck(len(r["applied"]) == 1 and not r["invalid"],
       "with an EMPTY registry the guard is inert: the lone set applies as before")

    # --- the live registry: merge's when merge exports one ----------------------------- #
    R.DERIVED_TWINS = None
    R._TWINS_CACHE = None
    src = R.derived_twins_source()
    try:
        import merge as M                # noqa: E402
        live = getattr(M, "DERIVED_TWINS", None)
    except Exception:
        live = None
    if isinstance(live, dict):
        ck(src == "merge" and R._derived_twins()[0] == dict(live),
           f"the live registry is merge.DERIVED_TWINS ({sorted(live)})")
        ck(SRC in live and live[SRC] == TWIN,
           "merge's registry carries the measured twin (officeArea -> officeAreaVal)")
    else:
        print(f"  [NOTE] merge does not export DERIVED_TWINS yet; live source is {src!r} and "
              f"the guard is INERT on a live run until it does (contract C2, agent B2a)")
        ck(src == "absent", "an absent registry is reported as 'absent', not faked")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
