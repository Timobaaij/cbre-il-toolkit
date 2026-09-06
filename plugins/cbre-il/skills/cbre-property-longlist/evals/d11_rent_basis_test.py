#!/usr/bin/env python3
"""d11_rent_basis_test.py - a dataset that states no rent unit never inherits a euro-per-sq-m basis. (D11)

THE DEFECT. `merge.dominant_units` resolved the dataset's AREA unit from the source records, then
on the very next line fell back to a FIXED "€/sq m/yr" whenever no record stated a `rentUnit`,
whatever the country and whatever area unit it had just resolved. On the measured client run a
100% GB, 100% sq ft brochure corpus in which no deck quoted a rent shipped "per sq m / year" in
the hero HEADLINE RENT KPI and "tbd / SQ M / YR" in all nine card footers, in euros, on a UK
sq ft longlist. No number was misstated (every rent was tbd) but the stated BASIS was wrong, and
it was uncorrectable: `rentUnit` is denied in both correction channels and project.yaml has no
key for it, so the operator shipped it and disclosed it by hand.

WHERE THIS SITS. `evals/f32_rent_basis_test.py` pins the CHROME half of the rent story: that a
Total annual rent figure prints the area x rate formula it was computed on. It builds its
fixture with `rentUnit` STATED on every property, so it never exercises the fallback and cannot
catch this defect. This eval pins the DATA half: the dataset-level `meta.units.rent` string the
chrome labels the KPI and footers with, in the one case where no source states it.

WHAT THIS PINS, and how each check would trip on the old behaviour:
  1. `normalize.default_rent_unit` follows the dominant AREA unit for the per-area basis and the
     dominant COUNTRY for the currency: GB + sq ft -> "£/sq ft/yr". The old code had no such
     function; the equivalent assertion on `dominant_units` asserts the exact string, so the old
     constant "€/sq m/yr" fails it.
  2. A eurozone + sq m corpus is UNCHANGED ("€/sq m/yr"), and so is a CEE one (PL quotes
     industrial rents in EUR): the fix must not have moved the runs it was right for.
  3. A corpus where a source DOES state a rent unit uses the stated one, and `meta.unitAssumptions`
     carries NO `rentUnit` entry: a default that fires over a stated value is a new defect.
  4. The fallback is DISCLOSED, not applied silently: driving the real `merge.main` on the exact
     measured shape (GB, sq ft, no rent, no rent unit) must leave an entry in
     `canonical.meta.unitAssumptions` with `field: "rentUnit"`, a non-integer id (deliver.py joins
     the per-property assumed-unit column by integer property id, so "dataset" can never relabel
     a row), and the sentence on stdout. The old code appended nothing and printed nothing.
  5. The default is never stamped on a PROPERTY's own `rentUnit` (B06 territory): a default basis
     for the labels is a convention, a default currency on a number would be invention.

Offline. Pure-function checks plus the real merge.main via subprocess (as unit_disclosure_test does).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import merge  # noqa: E402
import normalize as N  # noqa: E402

FAILS: list[str] = []

# the strings the chrome and rent_unit_band already read; the OLD fixed fallback is the euro one
GBP_SQFT = "£/sq ft/yr"
EUR_SQM = "€/sq m/yr"
USD_SQFT = "$/sq ft/yr"
EUR_SQFT = "€/sq ft/yr"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _r(src, park, country, area_unit, **kw):
    r = {"park": park, "city": "Corby", "country": country, "developer": "Dev",
         "warehouseArea": kw.pop("warehouseArea", 120000), "areaUnit": area_unit,
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": "page 1"}}
    r.update(kw)
    return r


def _run_merge(recs: list[dict], tag: str):
    """Drive the real merge.main offline; returns (canonical dict or None, stdout+stderr)."""
    d = Path(tempfile.mkdtemp(prefix=f"cbre_d11_{tag}_"))
    (d / "inputs").mkdir()
    (d / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (p.stderr or "")
    if not (d / "c.json").exists():
        return None, out
    return json.loads((d / "c.json").read_text(encoding="utf-8")), out


def _rent_assumptions(canon: dict) -> list[dict]:
    ua = ((canon or {}).get("meta") or {}).get("unitAssumptions") or []
    return [a for a in ua if isinstance(a, dict) and a.get("field") == "rentUnit"]


def main() -> int:
    print("== 1. the pure default follows the AREA unit and the COUNTRY, never a constant ==")
    ck(N.default_rent_unit("sq ft", "GB") == GBP_SQFT,
       f"GB + sq ft -> {GBP_SQFT} (got {ascii(N.default_rent_unit('sq ft', 'GB'))})")
    ck(N.default_rent_unit("sq ft", "United Kingdom") == GBP_SQFT,
       "a country NAME is normalised to its ISO code before the currency lookup")
    ck(N.default_rent_unit("sq ft", "US") == USD_SQFT, f"US + sq ft -> {USD_SQFT}")
    ck(N.default_rent_unit("sq ft", "IE") == EUR_SQFT,
       f"IE + sq ft -> {EUR_SQFT} (euro currency, imperial basis: the two axes are independent)")
    ck(N.default_rent_unit("sq m", "DE") == EUR_SQM, f"DE + sq m -> {EUR_SQM} (eurozone unchanged)")
    ck(N.default_rent_unit("sq m", "PL") == EUR_SQM,
       f"PL + sq m -> {EUR_SQM} (CEE quotes industrial rents in EUR; the old constant was right here)")
    ck(N.default_rent_unit(None, None) == EUR_SQM,
       f"no area unit and no country -> {EUR_SQM} (the historic convention when there is no evidence)")
    ck(N.default_rent_unit("sq m", "GB") == "£/sq m/yr",
       "GB + sq m -> pounds per sq m: the currency and the per-area basis are decided separately")

    print()
    print("== 2. dominant_units on the measured corpus shape (100% GB, 100% sq ft, no rent unit) ==")
    gb = [_r(f"Deck{i}.pdf", f"Park {i}", "GB", "sq ft") for i in range(1, 10)]
    au, ru = merge.dominant_units(gb)
    ck(au == "sq ft", f"the dominant area unit is sq ft ({ascii(au)})")
    ck(ru != EUR_SQM, f"the rent fallback is NOT the old fixed euro-per-sq-m string ({ascii(ru)})")
    ck(ru == GBP_SQFT, f"...it is {GBP_SQFT} ({ascii(ru)})")
    ck(merge.rent_unit_stated(gb) is False, "rent_unit_stated is False when no record states one")
    ck(merge.dominant_country(gb) == "GB", "dominant_country resolves GB")

    mixed_names = [_r("A.pdf", "A", "United Kingdom", "sq ft"), _r("B.pdf", "B", "GB", "sq ft"),
                   _r("C.pdf", "C", "DE", "sq ft")]
    ck(merge.dominant_country(mixed_names) == "GB",
       "'United Kingdom' and 'GB' are ONE vote (2 v 1), so the name form cannot split the majority")

    eu = [_r(f"Deck{i}.pdf", f"Park {i}", "DE", "sq m") for i in range(1, 4)]
    au2, ru2 = merge.dominant_units(eu)
    ck((au2, ru2) == ("sq m", EUR_SQM),
       f"a eurozone sq m corpus is unchanged: ({ascii(au2)}, {ascii(ru2)})")

    stated = [_r("Deck1.pdf", "Park 1", "GB", "sq ft", rentUnit=GBP_SQFT),
              _r("Deck2.pdf", "Park 2", "GB", "sq ft")]
    ck(merge.rent_unit_stated(stated) is True, "ONE stated rentUnit is enough to make it stated")
    ck(merge.dominant_units(stated)[1] == GBP_SQFT, "...and dominant_units returns the stated one")
    # a stated unit that DISAGREES with what the default would have chosen must still win
    odd = [_r("Deck1.pdf", "Park 1", "GB", "sq ft", rentUnit=EUR_SQM)]
    ck(merge.dominant_units(odd)[1] == EUR_SQM,
       "a stated unit beats the market default even when they disagree (the source is the evidence)")

    print()
    print("== 3. the assumption entry is shaped for the Gaps Report and cannot collide with a property ==")
    unit, entry = merge.rent_unit_default(gb, "sq ft")
    ck(unit == GBP_SQFT, f"rent_unit_default returns the unit ({ascii(unit)})")
    ck(entry.get("field") == "rentUnit", "the entry names field rentUnit")
    ck(entry.get("assumed") == GBP_SQFT, "the entry's assumed value is the unit adopted")
    ck(entry.get("id") == "dataset" and not isinstance(entry.get("id"), int),
       f"the id is the string 'dataset', never an integer property id ({ascii(str(entry.get('id')))})")
    why = str(entry.get("why", ""))
    ck("sq ft" in why and "GB" in why,
       "the why names the area unit and the country the default was derived from")
    ck("no rent number was relabelled" in why or "no rent" in why.lower(),
       "the why says no rent figure was relabelled with it (a label convention, not a value)")

    print()
    print("== 4. the real merge on the measured shape: disclosed in meta, said on stdout ==")
    canon, out = _run_merge(gb, "gb")
    ck(canon is not None, f"merge completes on the GB corpus {ascii(out[-200:]) if canon is None else ''}")
    if canon is not None:
        units = (canon.get("meta") or {}).get("units") or {}
        ck(units.get("area") == "sq ft", f"meta.units.area is sq ft ({ascii(str(units.get('area')))})")
        ck(units.get("rent") != EUR_SQM,
           f"meta.units.rent is NOT the old euro-per-sq-m constant ({ascii(str(units.get('rent')))})")
        ck(units.get("rent") == GBP_SQFT, f"meta.units.rent is {GBP_SQFT}")
        ra = _rent_assumptions(canon)
        ck(len(ra) == 1, f"exactly ONE rentUnit entry in meta.unitAssumptions ({len(ra)})")
        if ra:
            ck(ra[0].get("assumed") == units.get("rent"),
               "the disclosed assumption is the unit the KPI and footers will show")
            ck(ra[0].get("id") == "dataset", "the disclosed entry carries the 'dataset' id")
        ck("ASSUMED" in out and "rent unit" in out,
           "stdout says the rent basis was ASSUMED (silence is the bug)")
        ck(not any(q.get("rentUnit") for q in canon.get("properties") or []),
           "no PROPERTY had the default stamped on its own rentUnit (a unit-silent rent stays unit-silent)")

    print()
    print("== 5. the real merge, eurozone: unchanged unit, still disclosed as an assumption ==")
    canon_eu, out_eu = _run_merge(eu, "eu")
    ck(canon_eu is not None, "merge completes on the DE corpus")
    if canon_eu is not None:
        ck(((canon_eu.get("meta") or {}).get("units") or {}).get("rent") == EUR_SQM,
           f"meta.units.rent stays {EUR_SQM} for a eurozone sq m corpus (no regression)")
        ck(len(_rent_assumptions(canon_eu)) == 1,
           "...and it is STILL disclosed: a default is an assumption whichever market it lands in")

    print()
    print("== 6. the real merge, a STATED rent unit: used, and NOT recorded as an assumption ==")
    canon_st, out_st = _run_merge(stated, "stated")
    ck(canon_st is not None, "merge completes on the stated corpus")
    if canon_st is not None:
        ck(((canon_st.get("meta") or {}).get("units") or {}).get("rent") == GBP_SQFT,
           "meta.units.rent is the stated unit")
        ck(len(_rent_assumptions(canon_st)) == 0,
           "meta.unitAssumptions carries NO rentUnit entry when a source stated one")
        ck("rent basis" not in out_st or "ASSUMED" not in out_st,
           "stdout does not claim the rent basis was assumed")

    print()
    if FAILS:
        print(f"D11 RENT BASIS TEST: FAIL ({len(FAILS)})")
        return 1
    print("D11 RENT BASIS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
