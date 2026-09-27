#!/usr/bin/env python3
"""alias_promotion_test.py - fix 3.5a, merge side (2026-09-26 test run).

Readers stored stated values under EXACT synonyms of blank canonical fields (`levelAccessDoors`
beside an "absent in all sources" overheadDoors; `availableFrom` beside an absent earlyAccess),
and seven hand repairs moved them. `merge._promote_aliases` now moves such a value into its home
BEFORE clustering, using `_common.promotable_alias` - the same predicate the capture-symmetry
gate's strict tier uses.

Pins:
  1. unit: levelAccessDoors "4" + no overheadDoors -> overheadDoors "4", key gone, prov ends
     "(alias key levelAccessDoors)", key not in new_fields, alias_promoted records the move;
  2. a stated overheadDoors is never overwritten (alias key kept, still a new field);
  3. every ALIAS_PROMOTION_REFUSED name (camelCased) and the unsplit door total `loadingDoors`
     never promote; a count with no digit and a 'let agreed' date never promote;
  4. two alias keys for one field: the first in sorted order fills it, the other stays open;
  5. wiring order: a promoted epcRating holding a BREEAM grade is still re-filed by
     _route_certifications; a dedicated availableFrom beats timing fished out of status;
  6. fail-safe: a raising predicate leaves the record untouched and prints one line;
  7. invariant (restricted to fields the gate judges, per IA-4): every strict alias of a
     gate-checked field pairs in gate_runner.shadow_pairs;
  8. a real `merge.py --records` run: the card ships overheadDoors, not levelAccessDoors; the
     ledger row's locator carries "(alias key levelAccessDoors)"; canonical meta.aliasPromotions
     lists it; meta.newFields does not;
  9. repairs compat end-to-end: an rp-007-shaped hand repair against that canonical APPLIES
     (not superseded) and its unset says merge promoted the key.

Run: python evals/alias_promotion_test.py"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

import _common as C  # noqa: E402
import gate_runner as G  # noqa: E402
import match  # noqa: E402
import merge  # noqa: E402
import repairs as R  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def camel(phrase: str) -> str:
    w = re.sub(r"[^A-Za-z0-9 ]", " ", phrase).split()
    return w[0].lower() + "".join(x[:1].upper() + x[1:] for x in w[1:]) if w else ""


def rec(**kw):
    r = {"park": "Alpha Park", "city": "Northtown", "country": "ZZ", "developer": "Devco",
         "warehouseArea": 50000, "areaUnit": "sq m",
         "__meta": {"source_file": "deck.pdf", "source_type": "pdf", "locator_base": "page 1",
                    "prov": {}}}
    r.update(kw)
    return r


def prep(r):
    merge._normalise_offspec(r)
    merge._promote_aliases(r)
    merge._route_certifications(r)
    merge._route_availability(r)
    return r


def main() -> int:
    print("== 1. the measured shape promotes ==")
    r = rec(levelAccessDoors="4")
    r["__meta"]["prov"]["levelAccessDoors"] = "page 3 (spec table)"
    prep(r)
    m = r["__meta"]
    ck(r.get("overheadDoors") == "4" and "levelAccessDoors" not in r,
       "levelAccessDoors '4' -> overheadDoors '4', open key gone")
    ck(str(m["prov"].get("overheadDoors", "")).endswith("(alias key levelAccessDoors)")
       and m["prov"]["overheadDoors"].startswith("page 3"),
       f"prov moves with the value and names the alias ({m['prov'].get('overheadDoors')!r})")
    ck("levelAccessDoors" not in (m.get("new_fields") or []), "the key left __meta.new_fields")
    ck(m.get("alias_promoted") == [{"from": "levelAccessDoors", "to": "overheadDoors"}],
       f"__meta.alias_promoted records the move ({m.get('alias_promoted')})")
    r2 = rec(availableFrom="Q3 2026")
    prep(r2)
    ck(r2.get("earlyAccess") == "Q3 2026" and "availableFrom" not in r2
       and r2["__meta"]["prov"]["earlyAccess"] == "page 1 (alias key availableFrom)",
       "availableFrom -> earlyAccess, locator falls back to locator_base")

    print("== 2. a stated canonical value is never overwritten ==")
    r = rec(overheadDoors="2", levelAccessDoors="4")
    prep(r)
    ck(r.get("overheadDoors") == "2" and r.get("levelAccessDoors") == "4"
       and "levelAccessDoors" in (r["__meta"].get("new_fields") or [])
       and not r["__meta"].get("alias_promoted"),
       "stated overheadDoors kept; the alias stays an open (disclosed) key")
    r = rec(overheadDoors="None", levelAccessDoors="4")
    prep(r)
    ck(r.get("overheadDoors") == "None" and r.get("levelAccessDoors") == "4",
       "a stated 'None' is data: not overwritten")
    r = rec(overheadDoors="tbd", levelAccessDoors="4")
    prep(r)
    ck(r.get("overheadDoors") == "4", "a sentinel canonical slot IS filled")

    print("== 3. refusals ==")
    for field, names in C.ALIAS_PROMOTION_REFUSED.items():
        for n in names:
            k = camel(n)
            r = rec(**{k: "4 units 2026"})
            if k in C.canonical_property_fields():
                continue
            prep(r)
            ck(r.get(k) == "4 units 2026" and not r["__meta"].get("alias_promoted"),
               f"refused name {k!r} never promotes")
    for k, v, why in (("loadingDoors", "6", "an unsplit door total"),
                      ("levelAccessDoors", "yes", "a count with no digit"),
                      ("availableFrom", "Let agreed May 2026", "a taken date"),
                      ("levelAccessDoors", "tbd", "a sentinel"),
                      ("levelAccessDoors", True, "a bool"),
                      ("_levelAccessDoors", "4", "a private key")):
        r = rec(**{k: v})
        prep(r)
        ck(r.get(k) == v and not r["__meta"].get("alias_promoted")
           and not (r.get("overheadDoors") or r.get("loadingDocks") or r.get("earlyAccess")),
           f"{k}={v!r}: no promotion ({why})")

    print("== 4. one slot never takes two values ==")
    r = rec(levelAccessDoors="4", driveInDoors="6")
    prep(r)
    ck(r.get("overheadDoors") == "6" and r.get("levelAccessDoors") == "4"
       and "driveInDoors" not in r,
       "the first alias in sorted order (driveInDoors) fills it; levelAccessDoors stays open")

    print("== 5. wiring order ==")
    r = rec(epcRating="Excellent")
    prep(r)
    ck(r.get("breeam") == "Excellent" and not r.get("epc"),
       f"a promoted epcRating holding a BREEAM grade is re-filed to breeam ({r.get('breeam')!r})")
    r = rec(availableFrom="Q1 2027", status="Available from Q4 2026")
    prep(r)
    ck(r.get("earlyAccess") == "Q1 2027", "a dedicated availableFrom beats timing in status")
    src = (HELPERS / "merge.py").read_text(encoding="utf-8")
    i = [src.find(s) for s in ("        _normalise_offspec(_r)\n", "        _promote_aliases(_r)",
                               "        _route_certifications(_r)", "        _route_availability(_r)")]
    ck(all(x > 0 for x in i) and i == sorted(i),
       "main wires _normalise_offspec -> _promote_aliases -> _route_certifications -> _route_availability")

    print("== 6. fail-safe ==")
    orig = C.promotable_alias
    try:
        def boom(*_a, **_k):
            raise RuntimeError("synthetic")
        C.promotable_alias = boom
        r = rec(levelAccessDoors="4")
        before = json.dumps(r, sort_keys=True)
        buf = io.StringIO()
        with redirect_stderr(buf):
            merge._promote_aliases(r)
        ck(json.dumps(r, sort_keys=True) == before and "alias promotion skipped" in buf.getvalue(),
           "a raising predicate leaves the record untouched, with one stderr line")
    finally:
        C.promotable_alias = orig

    print("== 7. the gate table is a superset (fields the gate judges) ==")
    reg = G._shadow_registry()
    unpaired = [(f, a) for f, ph in C.ALIAS_PROMOTIONS.items() if f in reg for a in ph
                if not any(p["field"] == f for p in G.shadow_pairs(camel(a), "4 units 2026", {f}))]
    ck(not unpaired, f"every strict alias of a gate-judged field pairs ({unpaired or 'all'})")

    print("== 8. a real merge.py run ==")
    d = Path(tempfile.mkdtemp(prefix="cbre_alias_promo_"))
    (d / "inputs").mkdir()
    recs = [rec(levelAccessDoors="4")]
    recs[0]["__meta"]["prov"]["levelAccessDoors"] = "page 3 (spec table)"
    (d / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    ok = (d / "c.json").exists()
    ck(ok, "merge completes" + ("" if ok else f": {ascii((p.stdout + p.stderr)[-300:])}"))
    if ok:
        canon = json.loads((d / "c.json").read_text(encoding="utf-8"))
        q = canon["properties"][0]
        ck(q.get("overheadDoors") not in (None, "") and "levelAccessDoors" not in q,
           f"the card ships overheadDoors ({q.get('overheadDoors')!r}), not the alias")
        rows = list(csv.DictReader(open(d / "l.csv", encoding="utf-8-sig", newline="")))
        od = [x for x in rows if x.get("field") == "overheadDoors" and x.get("record_type") == "property"]
        ck(bool(od) and "(alias key levelAccessDoors)" in od[0].get("source_locator", ""),
           f"the ledger row's locator carries the alias ({od[0].get('source_locator') if od else None!r})")
        ck(not any(x.get("field") == "overheadDoors" and x.get("source_type") == "gap" for x in rows),
           "no 'absent in all sources' gap row for overheadDoors")
        ap = (canon.get("meta") or {}).get("aliasPromotions")
        ck(ap == [{"id": q["id"], "field": "overheadDoors", "aliasKey": "levelAccessDoors"}],
           f"canonical meta.aliasPromotions lists it ({ap})")
        ck(not any(e.get("key") == "levelAccessDoors"
                   for e in (canon.get("meta") or {}).get("newFields") or []),
           "meta.newFields does not list the promoted key")

        print("== 9. repairs compat end-to-end ==")
        rp = {"id": "rp-007", "property": {"key": match.match_key(q), "id": q["id"]},
              "expect": {"overheadDoors": "tbd"}, "set": {"overheadDoors": "4"},
              "unset": ["levelAccessDoors"], "why": "spec page states 4 level access doors",
              "verified_by": "analyst", "source_file": "deck.pdf", "source_locator": "page 3"}
        c2 = json.loads(json.dumps(canon))
        rep = R.apply(c2, [rp], provenance=[x for x in rows if x.get("record_type") == "property"])
        ck(len(rep["applied"]) == 1 and not rep["superseded"],
           f"an rp-007-shaped hand repair still APPLIES after the re-merge "
           f"(applied {len(rep['applied'])}, superseded {len(rep['superseded'])})")
        st = " ".join(str(s.get("reason", "")) for s in rep.get("stale") or [])
        ck("promoted into overheadDoors by merge's strict alias step" in st,
           "its unset reports the promotion, not 'check the spelling'")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} alias_promotion_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
