#!/usr/bin/env python3
"""d15_shadow_key_test.py - a datum captured under another name is not a false absence. (D15)

THE DEFECT, from the measured client run. The reader of one brochure put the level-access door
COUNTS into a descriptive non-registry key, `levelAccessDoors`, while the canonical home for
that datum, `overheadDoors`, shipped in the Gaps Report and Source Ledger as "absent in all
sources". So the honesty document asserted a FALSE ABSENCE: the datum WAS captured, under a
different name, and the struck-value sweep could not see it precisely because the key name
differs. A blind human reviewer found it; no gate did.

THE OPEN SCHEMA IS A FEATURE, and this eval defends it as hard as it defends the catch.
"Capture every field the source states" is the Stage-1 rule, and a stated value with no
canonical home is SUPPOSED to ship under a descriptive camelCase key. A gate that fires on
ordinary open-schema keys trains operators to ignore it, which is worse than the gap it
catches. So the silence cases below are several, not one.

WHAT THIS PINS, against `gate_runner.shadow_findings` / `shadow_pairs` and the CLI gate:
  1. a non-registry key that plausibly names a canonical field reported ABSENT produces ONE
     finding that names BOTH keys and the property, and the printed line carries all three;
  2. several ordinary open-schema keys, on a property where EVERY canonical sibling is absent
     with a gap row, produce NO finding at all (the noise guard);
  3. a non-registry key whose canonical sibling is POPULATED produces no finding;
  4. a gap row written with a stated reason (an honest withholding, not "absent in all
     sources") is not paired, so the check reads the ledger's claim literally;
  5. the CLASSIFICATION the implementation actually chose: every shadow finding is a SIGNAL,
     never a FAIL; the gate stays advisory (exit 0, STATUS: ALL-PASS), prints the finding
     FIRST and uncapped even under --max-notes 0, and files it in work/capture_symmetry.json
     under `shadow_findings`;
  6. the record-scoped fallback for an extract-only work dir (no canonical.json) still fires.

HOW A REGRESSION TRIPS IT. The old gate had no shadow-key question at all: `shadow_findings`
did not exist, no [SIGNAL] line named `levelAccessDoors` beside `overheadDoors`, and the sidecar
had no `shadow_findings` key. Checks 1, 5 and 6 fail against that. A fix that loosened the
pairing to whole-word containment or a lower fuzzy floor fails check 2.

Offline. Drives the module functions directly and the CLI gate once via subprocess; no build.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C                      # noqa: E402
import gate_runner as G                  # noqa: E402

GATE = ROOT / "helpers" / "gate_runner.py"
DECK = "07_Unit-6-Symmetry-Park-Rugby.pdf"
FAILS = []

# the pair from the measured run
OPEN_KEY, HOME = "levelAccessDoors", "overheadDoors"
# ordinary open-schema keys a reader is SUPPOSED to emit: every one must stay silent, even on
# a property whose every canonical sibling is absent with a gap row. `motorwayDriveTime` is the
# case the implementation names as deliberately NOT paired with `motorway` (a drive time is not
# the junction locator).
ORDINARY = {
    "motorwayDriveTime": "25 minutes to the M1",
    "solarPvCapacity": "250 kWp roof-mounted array",
    "rackingIncluded": "yes, narrow-aisle racking in situ",
    "nearestRailFreightTerminal": "DIRFT 8 miles",
    "serviceChargeEstimate": "0.45 psf",
    "yardSurface": "concrete",
    "planningUseClass": "B8 with ancillary B2",
    "occupierIncentives": "12 months rent free on a 10 year term",
}
LEDGER_COLS = ["property_id", "record_type", "field", "value", "source_file",
               "source_locator", "source_type"]


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _prop(pid, **fields):
    base = {"id": pid, "park": f"Park {pid}", "city": "Rugby", "developer": "Devco",
            "country": "GB", "status": "Available"}
    base.update(fields)
    return base


def _gap(pid, field, locator=G.GAP_ROW_CLAIM):
    return {"property_id": str(pid), "record_type": "property", "field": field,
            "value": "tbd", "source_file": "(none)", "source_locator": locator,
            "source_type": "gap"}


def _row(pid, field, value, locator="page 2"):
    return {"property_id": str(pid), "record_type": "property", "field": field,
            "value": str(value), "source_file": DECK, "source_locator": locator,
            "source_type": "pdf"}


def _work(props, ledger, extract=None):
    w = Path(tempfile.mkdtemp(prefix="cbre_d15_")) / "work"
    (w / "extract").mkdir(parents=True)
    if props is not None:
        (w / "canonical.json").write_text(
            json.dumps({"meta": {"client": "T"}, "pois": [], "regions": {},
                        "properties": props}), encoding="utf-8")
    if ledger is not None:
        with open(w / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=LEDGER_COLS, lineterminator="\n")
            wr.writeheader()
            wr.writerows(ledger)
    for name, recs in (extract or {}).items():
        (w / "extract" / name).write_text(json.dumps(recs), encoding="utf-8")
    return w


def _gaps_for_all_siblings(pid, prop, siblings):
    """One "absent in all sources" gap row for every canonical sibling the property lacks: the
    hardest possible noise test, because every sibling is a candidate pair."""
    return [_gap(pid, f) for f in sorted(siblings) if f not in prop]


def main() -> int:
    print("== the module surface this eval is written against ==")
    missing = [n for n in ("shadow_findings", "shadow_pairs", "_shadow_registry",
                           "GAP_ROW_CLAIM", "_shadow_line") if not hasattr(G, n)]
    ck(not missing, f"gate_runner exposes the shadow-key surface (missing: {missing or 'none'})")
    if missing:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s)) - nothing else could be run")
        return 1
    registry = set(C.canonical_property_fields())
    siblings = set(G._shadow_registry())
    ck(OPEN_KEY not in registry, f"control: `{OPEN_KEY}` really is a non-registry key")
    ck(HOME in registry and HOME in siblings,
       f"control: `{HOME}` is canonical and is a field that ships a gap row")
    off = sorted(k for k in ORDINARY if k in registry)
    ck(not off, f"control: every ordinary key is non-registry (canonical: {off})")

    print()
    print("== 1. the shadow key pairs with its ABSENT canonical home ==")
    # property 1: the measured shape. `levelAccessDoors` populated, `overheadDoors` gap row.
    # property 2: the noise test, every sibling absent with a gap row, ordinary keys only.
    # property 3: the datum captured under BOTH names, sibling populated.
    p1 = _prop(1, **{OPEN_KEY: "4"})
    p2 = _prop(2, **ORDINARY)
    p3 = _prop(3, **{OPEN_KEY: "4", HOME: 4})
    ledger = ([_row(1, OPEN_KEY, "4", "page 2"), _gap(1, HOME)]
              + _gaps_for_all_siblings(2, p2, siblings)
              + [_row(3, OPEN_KEY, "4"), _row(3, HOME, 4)]
              + [_row(2, k, v) for k, v in ORDINARY.items()])
    w = _work([p1, p2, p3], ledger)
    found = G.shadow_findings(w, [])
    on1 = [f for f in found if f.get("property_id") == "1"]
    ck(len(on1) == 1, f"property 1 produces exactly one finding ({len(on1)})")
    f1 = on1[0] if on1 else {}
    ck(f1.get("open_key") == OPEN_KEY and f1.get("field") == HOME,
       f"...naming BOTH keys: open `{f1.get('open_key')}`, home `{f1.get('field')}`")
    ck(f1.get("property_id") == "1" and f1.get("scope") == "property",
       "...and the property, property-scoped because canonical.json exists")
    ck(f1.get("ledger") == "gap row",
       f"...and it read the ledger's gap row literally rather than inferring absence "
       f"({f1.get('ledger')})")
    ck(f1.get("source_file") == DECK and "page 2" in f1.get("locator", ""),
       "...and it cites where the shadow value came from, so one repair can close it")
    ck(f1.get("signal") is True, "...and it is classified SIGNAL")
    line = G._shadow_line(f1) if f1 else ""
    ck(line.startswith("  [SIGNAL]") and OPEN_KEY in line and HOME in line
       and "property 1" in line,
       "the printed line is a [SIGNAL] naming both keys and the property")
    ck("FALSE" in line and G.GAP_ROW_CLAIM in line,
       "...and says in plain words that the gap row is a FALSE absence")
    ck("repairs.json" in line and "`set` " + HOME in line,
       "...and tells the operator which repair closes it")

    print()
    print("== 2. ordinary open-schema keys stay SILENT (the noise guard) ==")
    on2 = [f for f in found if f.get("property_id") == "2"]
    ck(not on2,
       f"property 2, every canonical sibling absent with a gap row and {len(ORDINARY)} "
       f"ordinary open keys, produces NO finding {[(f['open_key'], f['field']) for f in on2]}")
    # each key on its own, against the WHOLE sibling table, so a future loosening of the
    # pairing is caught key by key rather than as one opaque count
    for k, v in ORDINARY.items():
        pairs = G.shadow_pairs(k, v, siblings)
        ck(not pairs, f"`{k}` = {v!r} pairs with nothing "
                      f"{[(p['field'], p['how']) for p in pairs]}")
    # the implementation's own documented precision trade-offs: containment is NOT a tier
    ck(not G.shadow_pairs("motorwayDriveTime", "25 minutes", {"motorway"}),
       "`motorwayDriveTime` does not pair with `motorway` by containment (a drive time is not "
       "the junction locator)")
    # a number-typed sibling needs a number in the open value. `siteArea` IS an alias of
    # `plotArea`, so the prose case is silenced by the numeric guard alone, and the numeric
    # case proves the alias is live (the guard, not a missing alias, is what kept it quiet).
    ck(G._shadow_registry().get("plotArea", {}).get("numeric") is True,
       "control: plotArea is a number-typed sibling")
    ck(not G.shadow_pairs("siteArea", "generous, fully fenced and gated", {"plotArea"}),
       "a prose value under `siteArea` cannot pair with the number-typed `plotArea`")
    ck(any(p["field"] == "plotArea" for p in G.shadow_pairs("siteArea", "12 acres", {"plotArea"})),
       "...while `siteArea` = '12 acres' does pair, so the alias path is live and the pairing "
       "is not tuned to the one key name from the measured run")
    ck(any(p["field"] == HOME for p in G.shadow_pairs("groundLevelDoors", "four", {HOME})),
       f"a second spelling of the same datum (`groundLevelDoors`) also pairs with `{HOME}`")
    ck(not G.shadow_pairs("_debugKey", "4", siblings),
       "an underscore-prefixed housekeeping key is skipped")
    ck(not G.shadow_pairs(OPEN_KEY, "tbd", siblings),
       "an open key holding an unknown form has nothing to shadow")
    ck(not G.shadow_pairs(OPEN_KEY, {"north": 2, "south": 2}, siblings),
       "a structured (dict) value is not paired")

    print()
    print("== 3. a POPULATED canonical sibling means no finding ==")
    on3 = [f for f in found if f.get("property_id") == "3"]
    ck(not on3,
       f"property 3 carries `{OPEN_KEY}` AND `{HOME}`: nothing is a false absence "
       f"{[(f['open_key'], f['field']) for f in on3]}")
    ck(len(found) == 1, f"the whole three-property dataset yields exactly ONE finding "
                        f"({len(found)})")

    print()
    print("== 4. an honest withholding is not a false absence ==")
    p4 = _prop(4, **{OPEN_KEY: "2"})
    w4 = _work([p4], [_row(4, OPEN_KEY, "2"),
                      _gap(4, HOME, "stated as a range this dataset cannot express")])
    ck(not G.shadow_findings(w4, []),
       "a gap row whose locator states a REASON (not 'absent in all sources') is not paired")
    # the same property WITHOUT a ledger falls back to canonical's own absence, and says so
    w5 = _work([p4], None)
    f5 = G.shadow_findings(w5, [])
    ck(len(f5) == 1 and f5[0].get("ledger") == "not read",
       f"without a ledger the pair is still found, and the finding SAYS the ledger was not "
       f"read ({[f.get('ledger') for f in f5]})")
    ck("no Source Ledger was readable" in G._shadow_line(f5[0]) if f5 else False,
       "...and the printed line qualifies the claim accordingly")

    print()
    print("== 5. the real classification: SIGNAL, advisory, first, uncapped, filed ==")
    # the CLI end to end on the measured shape, with an extract dir so the gate has records,
    # and --max-notes 0 so a capped tail cannot be what saved the finding
    rec = dict(p1, __meta={"source_file": DECK, "page_no": 1, "source_type": "pdf"})
    w6 = _work([p1, p2, p3], ledger, extract={"07_vision.json": [rec]})
    r = subprocess.run([sys.executable, str(GATE), "capture-symmetry", "--work", str(w6),
                        "--max-notes", "0"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    ck(r.returncode == 0 and "STATUS: ALL-PASS" in out,
       f"the gate stays ADVISORY: exit {r.returncode}, "
       f"{'ALL-PASS' if 'STATUS: ALL-PASS' in out else 'not ALL-PASS'}")
    sig = [ln for ln in out.splitlines() if "[SIGNAL]" in ln and OPEN_KEY in ln and HOME in ln]
    ck(len(sig) == 1, f"exactly one [SIGNAL] line names `{OPEN_KEY}` and `{HOME}` ({len(sig)})")
    ck(not any("[FAIL]" in ln and (OPEN_KEY in ln or HOME in ln) for ln in out.splitlines()),
       "...and it is never printed as a [FAIL]: the implementation chose SIGNAL, deliberately")
    ck(not any(k in ln for ln in out.splitlines() if "[SIGNAL]" in ln for k in ORDINARY),
       "no ordinary open key appears in any SIGNAL line")
    ranked = [ln for ln in out.splitlines()
              if "[SIGNAL]" in ln or "[note]" in ln or "[PASS]" in ln]
    ck(bool(ranked) and OPEN_KEY in ranked[0],
       "the shadow finding prints FIRST, above everything else the gate says")
    ck("shadow-key SIGNAL" in out, "the summary line counts it as a shadow-key SIGNAL")
    side = w6 / "capture_symmetry.json"
    ck(side.exists(), "work/capture_symmetry.json is written")
    if side.exists():
        sj = json.loads(side.read_text(encoding="utf-8"))
        sf = sj.get("shadow_findings")
        ck(isinstance(sf, list) and len(sf) == 1 and sf[0].get("open_key") == OPEN_KEY
           and sf[0].get("field") == HOME and sf[0].get("property_id") == "1",
           "...with the finding under its own `shadow_findings` key, naming both keys and "
           "the property")
        ck("findings" in sj and "form_disagreements" in sj,
           "...beside the keys the sidecar carried before (old readers see what they saw)")

    print()
    print("== 6. the record-scoped fallback on an extract-only work dir ==")
    rec_a = {"park": "Unit 6", "city": "Rugby", OPEN_KEY: "4",
             "__meta": {"source_file": DECK, "page_no": 1}}
    rec_b = {"park": "Unit 7", "city": "Rugby", OPEN_KEY: "4", HOME: 4,
             "__meta": {"source_file": DECK, "page_no": 2}}
    rec_c = dict({"park": "Unit 8", "city": "Rugby"}, **ORDINARY,
                 __meta={"source_file": DECK, "page_no": 3})
    w7 = _work(None, None, extract={"07_vision.json": [rec_a, rec_b, rec_c]})
    f7 = G.shadow_findings(w7, [rec_a, rec_b, rec_c])
    ck(len(f7) == 1 and f7[0].get("scope") == "record" and f7[0].get("record") == "Unit 6",
       f"one record-scoped finding, on the record that shadows itself "
       f"({[(f.get('record'), f.get('open_key'), f.get('field')) for f in f7]})")
    ck(bool(f7) and f7[0].get("open_key") == OPEN_KEY and f7[0].get("field") == HOME
       and f7[0].get("source_file") == DECK,
       "...naming both keys and the source file")
    ck(bool(f7) and "[SIGNAL]" in G._shadow_line(f7[0]) and "Unit 6" in G._shadow_line(f7[0]),
       "...printed as a SIGNAL that names the record")
    r7 = subprocess.run([sys.executable, str(GATE), "capture-symmetry", "--work", str(w7)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out7 = (r7.stdout or "") + (r7.stderr or "")
    ck(r7.returncode == 0 and "[SIGNAL]" in out7 and OPEN_KEY in out7,
       "the CLI fires on a single-source, extract-only work dir (one deck can shadow itself)")

    print()
    print("== 7. stated availability timing is not a false absence of earlyAccess ==")
    # The same defect class one field over: readers file "Available now" under `status` or
    # `availability`, and `earlyAccess` (the displayed delivery date) shipped as a gap.
    import merge as M                    # noqa: E402
    ra = {"status": "Fully Refurbished, Available Now",
          "__meta": {"locator_base": "page 1", "prov": {"status": "page 3"}}}
    M._route_availability(ra)
    ck(ra.get("earlyAccess") == "Available Now" and ra.get("status") == "Fully Refurbished, Available Now",
       f"status timing is COPIED to earlyAccess, status kept ({ra.get('earlyAccess')!r})")
    pv = ra["__meta"]["prov"].get("earlyAccess", "")
    ck(pv.startswith("page 3") and "status" in pv and "timing" in pv,
       f"...with the source field's locator and a timing-wording note ({pv!r})")
    rb = M._route_availability({"availability": "Available from Q4 2026", "earlyAccess": "TBC"})
    ck(rb.get("earlyAccess") == "Available from Q4 2026",
       f"an `availability` phrase fills a sentinel earlyAccess ({rb.get('earlyAccess')!r})")
    for s in ("available in part or as a whole", "Available to sublease or assign",
              "Available", "Coming Soon"):
        r_ = M._route_availability({"status": s, "availability": s})
        ck(M.N.looks_unknown(r_.get("earlyAccess")),
           f"{s!r} states no timing: earlyAccess stays a gap ({r_.get('earlyAccess')!r})")
    rc = M._route_availability({"status": "Available Now", "earlyAccess": "Q1 2027"})
    ck(rc.get("earlyAccess") == "Q1 2027", "an existing earlyAccess is never overwritten")
    # end to end: the router is wired at the pre-merge call site, so the property ships it
    d = Path(tempfile.mkdtemp(prefix="cbre_d15_avail_"))
    (d / "inputs").mkdir()
    (d / "r.json").write_text(json.dumps([
        {"park": "Refurb Park", "city": "Corby", "country": "GB", "developer": "Dev",
         "warehouseArea": 100000, "areaUnit": "sq ft", "status": "Fully Refurbished, Available Now",
         "__meta": {"source_file": "Refurb.pdf", "source_type": "pdf", "locator_base": "page 1"}}]),
        encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "helpers" / "merge.py"), "--records", str(d / "r.json"),
                    "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                    "--ledger", str(d / "l.csv")], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    props = (json.loads((d / "c.json").read_text(encoding="utf-8")).get("properties") or []
             if (d / "c.json").exists() else [])
    ck(len(props) == 1 and props[0].get("earlyAccess") == "Available Now",
       f"the real merge ships earlyAccess 'Available Now' "
       f"({[p.get('earlyAccess') for p in props]})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        for f in FAILS:
            print("   -", f)
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
