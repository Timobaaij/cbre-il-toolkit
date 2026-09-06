#!/usr/bin/env python3
"""d14_region_bind_stale_clears_test.py - the "region bind STALE" notice fires when the bind is
actually stale, and clears when it is not. (D14)

THE DEFECT (measured). Five `region` repairs (labels for an already-correct `regionCode`)
printed "region bind STALE for property N ... enrichment re-runs on the next pass" on EVERY
later pass, resumed or full, right through to exit 0: a "done" run still printed five
stale-data warnings, indistinguishable from real ones. The mechanism: repairs live in
work/repairs.json and are RE-APPLIED every pass, repairs.py records `changed[field]` for every
`set` it applies INCLUDING the same-value case (its meta.conflicts annotation needs that), and
the notice keyed on the field NAME alone. On the measured work dir all 25 applied entries read
`from == to`.

THE HONEST TEST, pinned here: a notice needs BOTH a value that actually MOVED on this pass
(`run._repair_moved`) and an enrichment stamp that does not cover canonical as repaired
(`run._bind_inputs_stale`: the stamp's `_enrich_input_hash` differs, or there is no stamp to
vouch for the bind). A genuinely moved `lat` is still reported, once, and a re-applied repair
is not news.

Offline. Run: python evals/d14_region_bind_stale_clears_test.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as REP  # noqa: E402
import run as RUN  # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _work(props: list) -> tuple:
    w = Path(tempfile.mkdtemp(prefix="cbre_d14_"))
    cn = w / "canonical.json"
    cn.write_text(json.dumps({"meta": {"client": "x"}, "properties": props}), encoding="utf-8")
    return w, cn


def _stamp(w: Path, cn: Path, hash_=None) -> None:
    (w / ".enrich.stamp").write_text(json.dumps(
        {"v": 2, "args": "--regions", "hash": hash_ or RUN._enrich_input_hash(cn)}),
        encoding="utf-8")


def _stale(lines: list) -> list:
    return [ln for ln in lines if "STALE" in ln]


def _applied(pid, rid, field, frm, to) -> list:
    return [{"id": rid, "property_id": pid, "changed": {field: {"from": frm, "to": to}}}]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("d14_region_bind_stale_clears_test - the STALE notice is conditional on real staleness")
    ck(hasattr(RUN, "_repair_moved") and hasattr(RUN, "_bind_inputs_stale"),
       "run.py exposes the two tests the notice now rests on")
    if FAILS:
        print("STATUS: BLOCKED")
        return 1

    prop = {"id": 2, "park": "P", "city": "C", "developer": "D", "country": "GB",
            "lat": 52.488696, "lng": -0.647646, "region": "North Northamptonshire",
            "regionCode": "UKF25", "status": "available", "photo": ""}

    print("\n1. the measured shape: a re-applied label repair, value already in canonical")
    w, cn = _work([dict(prop)])
    _stamp(w, cn)
    lines = RUN._rederive_after_repairs(cn, _applied(2, "rp-011", "region",
                                                     "North Northamptonshire",
                                                     "North Northamptonshire"))
    ck(not _stale(lines), f"from == to and the stamp covers canonical: NO stale line ({lines})")
    lines = RUN._rederive_after_repairs(cn, _applied(2, "rp-011", "region",
                                                     "North Northamptonshire",
                                                     "North Northamptonshire"), stamp=w / "none")
    ck(not _stale(lines), "from == to with NO stamp at all: still no stale line (nothing moved)")

    print("\n2. a moved value the stamp already covers is not stale either")
    lines = RUN._rederive_after_repairs(cn, _applied(2, "rp-011", "region", "tbd",
                                                     "North Northamptonshire"))
    ck(not _stale(lines), "the stamp's hash equals canonical as repaired: the bind saw these values")

    print("\n3. a moved value the stamp does NOT cover is stale, once, and named")
    _stamp(w, cn, hash_="0" * 64)
    lines = RUN._rederive_after_repairs(cn, _applied(2, "r-lat", "lat", 51.0, 52.488696))
    st = _stale(lines)
    ck(len(st) == 1 and "property 2" in st[0] and "r-lat" in st[0] and "lat" in st[0],
       f"one line names property, repair id and field ({st[:1]})")
    (w / ".enrich.stamp").unlink()
    lines = RUN._rederive_after_repairs(cn, _applied(2, "r-lat", "lat", 51.0, 52.488696))
    ck(len(_stale(lines)) == 1, "with no stamp to vouch for the bind, a moved input is reported")
    lines = RUN._rederive_after_repairs(cn, _applied(2, "r-docks", "loadingDocks", 1, 2))
    ck(not _stale(lines), "a moved field the bind does not read raises nothing")

    print("\n4. _repair_moved reads repairs.py's change record honestly")
    ck(RUN._repair_moved({"from": 1, "to": 2}) and not RUN._repair_moved({"from": 1, "to": 1}),
       "a set that moved the value counts; a same-value re-application does not")
    ck(not RUN._repair_moved({"from": 25000.0, "to": 25000}),
       "int/float noise is not a move")
    ck(RUN._repair_moved({"from": "x", "to": REP.CLEARED, "cleared": True})
       and not RUN._repair_moved({"from": None, "to": REP.CLEARED, "cleared": True,
                                  "already_absent": True}),
       "a clear counts only when there was a value to remove")
    ck(not RUN._repair_moved(None) and not RUN._repair_moved("junk"),
       "a malformed record is not a move")

    print("\n5. through the REAL repairs stage: the second pass of the same repair is quiet")
    w, cn = _work([dict(prop, region="tbd")])
    (w / "repairs.json").write_text(json.dumps([{
        "id": "rp-011", "property": {"key": "c|d|p", "id": 2}, "expect": {"region": "tbd"},
        "set": {"region": "North Northamptonshire"},
        "why": "the deck states it", "verified_by": "t@cbre.com"}]), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        rep1 = REP.run(w, write=True)
    # pass 1: the value moved and nothing has bound it yet -> reported
    lines1 = RUN._rederive_after_repairs(cn, rep1.get("applied"))
    ck(len(rep1.get("applied") or []) == 1 and len(_stale(lines1)) == 1,
       f"pass 1 moves the label with no stamp: ONE stale line ({_stale(lines1)[:1]})")
    # enrichment then runs and stamps canonical as it stands (the label included)
    _stamp(w, cn)
    with contextlib.redirect_stdout(io.StringIO()):
        rep2 = REP.run(w, write=True)
    ch = ((rep2.get("applied") or [{}])[0].get("changed") or {}).get("region") or {}
    ck(len(rep2.get("applied") or []) == 1 and ch.get("from") == ch.get("to"),
       f"pass 2 re-applies the same repair and repairs.py records from == to ({ch})")
    lines2 = RUN._rederive_after_repairs(cn, rep2.get("applied"))
    ck(not _stale(lines2), "...and the notice has CLEARED (this is what never happened on the "
                            "measured run)")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        print(f"D14 REGION BIND STALE CLEARS TEST: FAIL ({len(FAILS)})")
        return 1
    print("STATUS: ALL-PASS")
    print("D14 REGION BIND STALE CLEARS TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
