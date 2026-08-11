#!/usr/bin/env python3
"""perfield_unit_test.py - each area converts on ITS OWN supplier's footing. (B39)

merge branched on ONE merged `areaUnit` and applied it to warehouseArea, plotArea and
officeAreaVal alike. But every field resolves its own precedence contest, so an area can come
from one record while `areaUnit` comes from another - and the number was then scaled by
10.7639 on a unit its own source never stated. Measured: 134,549 sq ft shipped as 1,448,272,
with an EMPTY meta.unitAssumptions and no conflict note - MORE silent than the unit-silent
case the areaUnitAssumed branch was built for.

This suite also records why the two OBVIOUS fixes were rejected, because both were filed and
both are wrong: pinning the label to warehouseArea's supplier, and refusing to merge a
mixed-unit cluster, each relocate the identical 10.76x onto plotArea. The plotArea assertions
below are what catch them.

Drives real merge.main through a subprocess - the oracle is structurally blind here (it
re-renders a FIXED canonical fixture and never executes merge), so this is the only net."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

SQFT_PER_SQM = 10.7639


def _merge(recs, tag):
    d = Path(tempfile.mkdtemp(prefix=f"cbre_pfu_{tag}_"))
    (d / "inputs").mkdir()
    (d / "recs.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"),
                        "--records", str(d / "recs.json"),
                        "--source-dir", str(d / "inputs"),
                        "--out", str(d / "c.json"), "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, errors="replace")
    if not (d / "c.json").exists():
        return None, (p.stdout + p.stderr)[-300:]
    return json.loads((d / "c.json").read_text(encoding="utf-8")), ""


def _r(src, stype="pdf", **kw):
    r = {"park": "Raven Park", "city": "Corby", "country": "GB", "developer": "Prologis",
         "__meta": {"source_file": src, "source_type": stype, "locator_base": "page 1"}}
    r.update(kw)
    return r


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # THE REPRODUCING CLUSTER. Two records of ONE property that cluster together:
    #   - the tracker (higher precedence for area) states 134,549 with NO areaUnit
    #   - the deck states a 40,000 plot in sq m, and IS where areaUnit comes from
    # so the merged label is "sq m" while warehouseArea's own source never said so.
    recs = [
        _r("Tracker.xlsx", "xlsx", warehouseArea=134549),
        _r("Deck.pdf", "pdf", plotArea=40000, areaUnit="sq m"),
    ]
    canon, err = _merge(recs, "mixed")
    ck(canon is not None, f"merge completes on the mixed-footing cluster {ascii(err)}")
    if not canon:
        print(f"\nPERFIELD UNIT TEST: FAIL ({len(fails)})")
        return 1
    p = canon["properties"][0]
    unit = p.get("areaUnit")
    wa, pa = p.get("warehouseArea"), p.get("plotArea")

    # warehouseArea's supplier stated NO unit -> it must NOT be converted
    ck(wa == 134549,
       f"warehouseArea is NOT scaled on a unit its own source never stated (got {wa}, "
       f"want 134549; the bug shipped {round(134549 * SQFT_PER_SQM)})")
    # ...and the silent supplier must be DISCLOSED, which the bug did not do at all
    ua = (canon.get("meta") or {}).get("unitAssumptions") or []
    ck(bool(ua), f"the silent supplier IS recorded in meta.unitAssumptions ({len(ua)})")
    ck(any("id" in a for a in ua), "the assumption carries an id, so it joins by id not by name")

    # plotArea's supplier DID state sq m -> convert only if the dataset unit differs.
    # This is the assertion that kills BOTH filed remedies: each of them leaves plotArea
    # mislabelled at its raw value.
    if unit == "sq ft":
        ck(pa == round(40000 * SQFT_PER_SQM),
           f"plotArea IS converted sq m -> sq ft on its OWN footing (got {pa}, "
           f"want {round(40000 * SQFT_PER_SQM)}; both filed remedies leave 40000)")
    else:
        ck(pa == 40000, f"plotArea keeps its own already-correct sq m value (got {pa})")

    # --- a SINGLE-footing cluster must be byte-identical to today ---------------
    same = [_r("A.pdf", warehouseArea=10000, areaUnit="sq m"),
            _r("B.pdf", plotArea=20000, areaUnit="sq m")]
    c2, err2 = _merge(same, "same")
    ck(c2 is not None, f"merge completes on a single-footing cluster {ascii(err2)}")
    if c2:
        q = c2["properties"][0]
        ck(q.get("areaUnit") == "sq m", "the dataset unit is sq m")
        ck(q.get("warehouseArea") == 10000 and q.get("plotArea") == 20000,
           f"nothing is converted when every footing already matches "
           f"({q.get('warehouseArea')}, {q.get('plotArea')})")
        ck(not (c2.get("meta") or {}).get("unitAssumptions"),
           "and nothing is recorded as assumed (no false disclosure)")

    # --- a genuine cross-unit conversion still happens --------------------------
    cross = [_r("A.pdf", warehouseArea=1000, areaUnit="sq m"),
             _r("B.pdf", warehouseArea=1000, areaUnit="sq m"),
             _r("C.pdf", plotArea=500, areaUnit="sq ft")]
    c3, err3 = _merge(cross, "cross")
    if c3:
        units = {pr.get("areaUnit") for pr in c3["properties"]}
        ck(len(units) == 1, f"one dataset unit label across the pack {ascii(str(units))}")

    # --- WIRING: the footing is recorded at BOTH prov sites --------------------
    MSRC = (HELPERS / "merge.py").read_text(encoding="utf-8", errors="replace")
    ck(MSRC.count('"areaUnitOfSource"') >= 3,
       "the supplier's footing is stashed at both prov sites and read in the conversion")
    code = "\n".join(ln for ln in MSRC.splitlines() if not ln.strip().startswith("#"))
    ck('merged["areaUnit"] != area_unit' not in code,
       "the old single-label conversion branch is gone")

    if fails:
        print(f"\nPERFIELD UNIT TEST: FAIL ({len(fails)})")
        return 1
    print("\nPERFIELD UNIT TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
