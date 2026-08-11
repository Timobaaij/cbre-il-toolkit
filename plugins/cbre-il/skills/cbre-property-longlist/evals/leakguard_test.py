#!/usr/bin/env python3
"""leakguard_test.py - no internal working flag ever reaches a client card. (B05)

The v21 modal renders EVERY key a property carries, including names in no schema. So
`areaUnitAssumed`, written as a top-level property scalar by merge, shipped a raw
untranslated row "Area Unit Assumed: true" to a broker's client. `extract_xlsx` writes an
identical top-level `rentUnitAssumed` that leaks exactly the same way - and the tracker
path is the COMMON trigger, so fixing one name and not the other leaves the leak live.

Three assertions, and the third is the one that matters long-term:
  1. the sweep moves every internal flag under __meta (which merge drops one line later);
  2. WIRING - merge calls it at the single choke point, immediately before the property is
     appended (this project has twice shipped a correct function with dead wiring);
  3. NO key matching the *Assumed / *Suspect shape survives on a canonical property, so a
     THIRD instance of this class cannot ship quietly.
The audit trail must not be lost with the flag: canonical.meta.unitAssumptions is what the
Gaps Report reads, and it is asserted here too. Offline."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import merge as M  # noqa: E402

SRC = (HELPERS / "merge.py").read_text(encoding="utf-8", errors="replace")
FLAGISH = re.compile(r"(Assumed|Suspect|OutOfBand|Unreliable)$")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    ck(hasattr(M, "strip_internal_flags"), "merge.strip_internal_flags exists")
    ck(hasattr(M, "_INTERNAL_FLAGS"), "merge._INTERNAL_FLAGS exists")
    if not (hasattr(M, "strip_internal_flags") and hasattr(M, "_INTERNAL_FLAGS")):
        print(f"\nLEAKGUARD TEST: FAIL ({len(fails)})")
        return 1

    for name in ("areaUnitAssumed", "rentUnitAssumed"):
        ck(name in M._INTERNAL_FLAGS, f"{name} is registered as internal")

    # 1. the sweep
    merged = {"park": "Gamma", "warehouseArea": 12500, "areaUnitAssumed": True,
              "rentUnitAssumed": True, "__meta": {"source_file": "g.pdf"}}
    M.strip_internal_flags(merged)
    ck("areaUnitAssumed" not in merged and "rentUnitAssumed" not in merged,
       "both flags leave the property top level")
    ck(merged["__meta"].get("areaUnitAssumed") is True
       and merged["__meta"].get("rentUnitAssumed") is True,
       "both are preserved under __meta (which merge pops one line later)")
    ck(merged["park"] == "Gamma" and merged["warehouseArea"] == 12500,
       "real fields are untouched")
    m2 = {"park": "Clean"}
    M.strip_internal_flags(m2)
    ck(m2 == {"park": "Clean"},
       "a property with no flags is left byte-identical (no empty __meta scaffolding)")

    # 2. WIRING at the single choke point
    i_strip = SRC.find("strip_internal_flags(merged)")
    i_pop = SRC.find('merged.pop("__meta", None)')
    i_app = SRC.find("properties.append(merged)")
    ck(i_strip != -1, "merge calls strip_internal_flags(merged)")
    ck(-1 < i_strip < i_pop < i_app,
       "it runs BEFORE the __meta pop, which runs before the append")
    ck(SRC.count("properties.append(merged)") == 1,
       "there is exactly ONE append, so the choke point really is one")

    # 3. the standing shape guard, over a real end-to-end canonical
    import json
    import subprocess
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="cbre_leak_"))
    recs = [
        {"park": "Alpha", "city": "Corby", "country": "GB", "developer": "D",
         "warehouseArea": 120000, "areaUnit": "sq ft",
         "__meta": {"source_file": "a.pdf", "source_type": "pdf", "locator_base": "page 1"}},
        {"park": "Beta", "city": "Corby", "country": "GB", "developer": "D",
         "warehouseArea": 95000, "areaUnit": "sq ft",
         "__meta": {"source_file": "b.pdf", "source_type": "pdf", "locator_base": "page 1"}},
        # states a numeric area but NO unit -> this is the record that sets areaUnitAssumed
        {"park": "Gamma", "city": "Corby", "country": "GB", "developer": "D",
         "warehouseArea": 12500,
         "__meta": {"source_file": "c.pdf", "source_type": "pdf", "locator_base": "page 1"}},
        # as extract_xlsx writes it, on the SOURCE record
        {"park": "Delta", "city": "Corby", "country": "GB", "developer": "D",
         "warehouseArea": 40000, "areaUnit": "sq ft", "warehouseRentVal": 8.5,
         "rentUnitAssumed": True,
         "__meta": {"source_file": "d.xlsx", "source_type": "xlsx", "locator_base": "row 2"}},
    ]
    (d / "recs.json").write_text(json.dumps(recs), encoding="utf-8")
    (d / "inputs").mkdir()
    out, led = d / "canonical.json", d / "ledger.csv"
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"),
                        "--records", str(d / "recs.json"),
                        "--source-dir", str(d / "inputs"),
                        "--out", str(out), "--ledger", str(led)],
                       capture_output=True, text=True, errors="replace")
    if not out.exists():
        ck(False, f"merge produced no canonical {ascii((p.stdout + p.stderr)[-200:])}")
    else:
        canon = json.loads(out.read_text(encoding="utf-8"))
        props = canon.get("properties") or []
        ck(len(props) == 4, f"four properties merged ({len(props)})")
        bad = sorted({k for pr in props for k in pr if FLAGISH.search(k)})
        ck(not bad, f"NO canonical property key matches the internal-flag shape {ascii(bad)}")
        ua = (canon.get("meta") or {}).get("unitAssumptions") or []
        ck(any(a.get("field") == "areaUnit" for a in ua),
           f"meta.unitAssumptions still records the assumption ({len(ua)}) - the audit "
           f"trail was not traded away with the flag")
        ck(any("Gamma" in str(a.get("property")) for a in ua),
           "and names the property, so the Gaps Report can chase the source")

    if fails:
        print(f"\nLEAKGUARD TEST: FAIL ({len(fails)})")
        return 1
    print("\nLEAKGUARD TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
