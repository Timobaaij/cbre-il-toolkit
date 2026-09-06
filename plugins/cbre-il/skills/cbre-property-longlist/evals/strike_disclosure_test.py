#!/usr/bin/env python3
"""strike_disclosure_test.py - the T1 never-strike-stated-data contract.

Pins the four mechanisms that once struck CORRECT printed values to tbd (each with a
ledger row calling the source implausible):
(1) a RANGE is ungated - "10-12 m" / "EUR 114-126" judge as "none", never "fail"
    (extract_first_number still refuses ranges for ARITHMETIC - that contract is unchanged);
(2) plotArea uses the SITE ceiling (a 630,000 / 772,000 sq m park plot passes; a building
    that size still fails; a 12M sq m plot garble still fails);
(3) the strike note names the PARSE, never accuses the source, and points at repairs.json;
(4) a value that KEEPS its printed unit is banded IN THAT PRINTED UNIT - area_band_for had
    no acres or ha branch, so a printed "50 acres" / "12.8 ha" plot met the sq m floor of
    300, failed, and was reported as a field no source provided.
Plus the BTS half: the reader contract (run.py field_rules + interpretation.md) now says a
printed BTS is DATA, and no Python sentinel list swallows "bts".

Run: python evals/strike_disclosure_test.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import merge  # noqa: E402
import normalize as N  # noqa: E402
import run as R  # noqa: E402


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    # (1) ranges: ungated in the verdict, still range-refusing in arithmetic
    check(N.extract_first_number("10-12 m") is None,
          "extract_first_number still refuses ranges for arithmetic (unchanged)")
    check(merge._pick_gate_verdict("clearHeight", "10-12 m") == "none",
          "a clear-height RANGE judges 'none', never 'fail'")
    check(merge._pick_gate_verdict("officeRent", "€ 114-126 per sq. m. per annum") == "none",
          "an office-rent RANGE judges 'none', never 'fail'")
    check(merge._pick_gate_verdict("loadingDocks", "10-12") == "none",
          "a count RANGE judges 'none', never 'fail'")
    check(merge._pick_gate_verdict("clearHeight", "10 m") == "pass",
          "a plain in-band height still passes")
    check(merge._pick_gate_verdict("warehouseRentVal", 63) == "pass",
          "a plain in-band rent still passes")
    check(merge._pick_gate_verdict("clearHeight", "garble") == "fail",
          "a non-numeric non-range still fails (garble protection intact)")

    # (2) plotArea site ceiling; building ceiling intact; garble still caught
    check(merge._pick_gate_verdict("plotArea", 630000, None, "sq m") == "pass",
          "a 630,000 sq m PLOT passes (63 ha site is routine)")
    check(merge._pick_gate_verdict("plotArea", 772000, None, "sq m") == "pass",
          "a 772,000 sq m PLOT passes")
    check(merge._pick_gate_verdict("warehouseArea", 630000, None, "sq m") == "fail",
          "a 630,000 sq m BUILDING still fails (building ceiling intact)")
    check(merge._pick_gate_verdict("plotArea", 12_000_000, None, "sq m") == "fail",
          "a 12M sq m plot still fails (garble ceiling intact)")
    check(N.area_band_for("sq m") == (N.AREA_SQM_MIN, N.AREA_SQM_MAX),
          "area_band_for without a field is unchanged (back-compat)")
    check(N.area_band_for("sq ft", field="plotArea")[1] == N.PLOT_SQFT_MAX,
          "the sq ft plot ceiling rides the same field switch")
    check(N.PLOT_SQFT_MAX >= N.PLOT_SQM_MAX * 10.764,
          "the sq ft plot ceiling never straddles the sq m one")

    # (3) the strike note: names the parse, points at repairs.json, never accuses the source
    src = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8")
    check("falls outside the {field} " in src and "work/repairs.json" in src,
          "the strike note names the parse and the repairs.json recovery path")
    check("fails the {field} plausibility gate, so the field is" not in src,
          "the old source-accusing strike wording is gone")

    # (4) MECHANISM (2) IN THE OTHER UNITS. merge treats a string area that prints its own unit
    # as a supported shape and renders it verbatim, deriving the unit from INSIDE the string via
    # area_unit_of - which returns "acres" or "ha". area_band_for had no branch for either, so
    # both fell through to the sq m band: a printed "50 acres" or "12.8 ha" plot was measured
    # against a floor of 300, FAILED, and was struck to the unknown sentinel with a ledger row
    # telling the reader the source's own printed figure looked implausible, after which the
    # honesty report counted the field as one no source had provided. Same false absence as (2),
    # one band branch further down. A band that strikes a correct printed figure and then reports
    # it ABSENT is worse than no band: it turns a present, sourced value into a confident false
    # absence. Pinned HERE because this file already claims the never-strike-stated-data
    # contract, so this was a hole inside a claim already made.

    # (4a) the acres/ha bands are DIVIDED out of the sq ft / sq m pairs, never typed, so they
    #      cannot drift from them - and EXACTLY, so no value can straddle a boundary: `x` acres
    #      passes iff `x * SQFT_PER_ACRE` sq ft passes. acres ride the imperial pair and ha the
    #      metric one, matching the conversion each takes at parse.
    for _u, _fac, _base in (("acres", N.SQFT_PER_ACRE, (N.AREA_SQFT_MIN, N.AREA_SQFT_MAX)),
                            ("ha", N.SQM_PER_HA, (N.AREA_SQM_MIN, N.AREA_SQM_MAX))):
        _lo, _hi = N.area_band_for(_u)
        check((_lo * _fac, _hi * _fac) == _base,
              f"the {_u} band is its own system's band / {_fac:g} EXACTLY (derived from the "
              f"constant, so it cannot drift from it and cannot straddle it)")
        check(N.area_band_for(_u, field="plotArea")[1] > N.area_band_for(_u)[1],
              f"the {_u} PLOT ceiling stays wider than the {_u} building ceiling (T1 in {_u})")

    # (4b) a plot printed in ACRES is never struck, from a small urban plot to a very large park
    #      site (2,400 acres is ~971 ha; the band section calls 60-180 ha routine).
    for _v in ("0.4 acres", "1.2 acres", "5.2 acres", "12.8 acres",
               "50 acres", "250 acres", "800 acres", "2,400 acres"):
        check(merge._pick_gate_verdict("plotArea", _v) == "pass",
              f"a plot printed {_v!r} is NOT struck (it judged 'fail' against the sq m floor 300)")

    # (4c) the same in HECTARES, small urban plot to very large park site.
    for _v in ("0.15 ha", "0.5 hectares", "2.4 ha", "12.8 ha",
               "60 ha", "180 ha", "385 ha", "950 ha"):
        check(merge._pick_gate_verdict("plotArea", _v) == "pass",
              f"a plot printed {_v!r} is NOT struck (it judged 'fail' against the sq m floor 300)")

    # (4d) the band still does its job, and WHERE each half bites is the point. merge unions the
    #      unit's band with the unit-unknown band (`min(lo, lo0), max(hi, hi0)`, deliberately:
    #      knowing the unit may only WIDEN it), so at the GATE the acres/ha FLOOR bites while the
    #      CEILING is raised to that field's sq m ceiling. That union is also why adding these
    #      branches cannot newly strike anything - for acres/ha it only lowers the effective
    #      floor - and it is why a mislabelled sq-ft-sized figure is caught on a BUILDING field
    #      (600,000 sq m ceiling) but not on a plot (10M). The tight ceiling is enforced by the
    #      band itself, which extract_xlsx/vision_validate consult with no union, so both halves
    #      are pinned rather than assumed.
    for _fld, _v in (("plotArea", "0.01 acres"), ("plotArea", "0.01 ha"),
                     ("plotArea", "43,560,000 acres"), ("plotArea", "12,000,000 ha"),
                     ("warehouseArea", "700,000 acres"), ("warehouseArea", "1,000,000 ha")):
        check(merge._pick_gate_verdict(_fld, _v) == "fail",
              f"a unit error / parse garble {_v!r} on {_fld} is STILL struck (the band was "
              f"widened for real units, not removed)")
    for _u, _bad in (("acres", 700_000), ("ha", 600_000)):
        _lo, _hi = N.area_band_for(_u, field="plotArea")
        check(not (_lo <= _bad <= _hi),
              f"{_bad:,} {_u} is outside the plotArea {_u} band ({_lo:.4g}-{_hi:.6g}) - the "
              f"ceiling does bite wherever area_band_for is read without merge's widening union")

    # (4e) the MIXED shape "N acres (M ha)", decided DELIBERATELY: it must PASS. The figure is
    #      correct and doubly stated, so striking it is exactly the false absence this contract
    #      forbids. But it does not survive on the band's merit, and that is worth recording:
    #      extract_first_number reads "31.629" as a thousands-grouped 31629.0 (three digits after
    #      the dot, more than three in total - the "108.900" -> 108900 rule normalize needs
    #      elsewhere). 31,629 acres is 128 sq km and is genuinely out of band; only merge's
    #      never-narrow union keeps it alive. Both halves are pinned, so if the misparse is ever
    #      fixed the value passes on its own merits and nothing here breaks, and if the union is
    #      ever removed this fails LOUDLY instead of a correct printed plot going missing.
    check(N.extract_first_number("31.629 acres (12.8 ha)") == 31629.0,
          "the mixed shape's leading figure still misparses as 31,629 (the thousands rule) - "
          "recorded here, never relied on")
    check(N.area_unit_of("31.629 acres (12.8 ha)") == "acres",
          "the mixed shape bands on the FIRST unit printed (acres), not the parenthetical")
    check(merge._pick_gate_verdict("plotArea", "31.629 acres (12.8 ha)") == "pass",
          "the mixed 'N acres (M ha)' shape is NOT struck: a correct, doubly-stated figure")
    check(merge._pick_gate_verdict("plotArea", "12.8 ha") == "pass",
          "...nor is its parenthetical half quoted on its own ('12.8 ha')")
    _lo, _hi = N.area_band_for("acres", field="plotArea")
    check(_lo <= 31.629 <= _hi,
          "...and the TRUE printed figure (31.629 acres) is comfortably in band, so a correct "
          "band is not what that shape is at risk from")
    check(not (_lo <= 31629.0 <= _hi),
          "...while the MISPARSED 31,629 acres is out of band: it survives ONLY on merge's "
          "never-narrow union, so removing that union must fail HERE, not ship a false absence")

    # (4f) an unknown or absent unit is unchanged, PRECISELY - and the substring test that used to
    #      decide it is now tightened. `"ft" in str(unit)` read "draft"/"left" as square feet and
    #      MISSED the real spellings "square feet"/"psf"; copying that looseness as `"ha" in unit`
    #      would have read a "gross hall area" column as HECTARES and struck a 40,000 sq m shed
    #      against a 60 ha ceiling - the same bug in a new place. area_unit_of matches acres and
    #      ha on word boundaries, so it is the canonicaliser now; a lone "ft" keeps a fallback
    #      whose scope is exactly a STANDALONE imperial token.
    for _u in (None, "", "bananas", "GIA", "draft", "gross hall area"):
        check(N.area_band_for(_u) == (N.AREA_SQM_MIN, N.AREA_SQM_MAX)
              and N.area_band_for(_u, field="plotArea") == (N.AREA_SQM_MIN, N.PLOT_SQM_MAX),
              f"an unknown/absent unit {_u!r} keeps today's sq m band exactly (no loose match)")
    for _u in ("sq ft", "SQ FT", "square feet", "psf", "ft"):
        check(N.area_band_for(_u) == (N.AREA_SQFT_MIN, N.AREA_SQFT_MAX),
              f"{_u!r} resolves to the sq ft band (the tightening never narrowed a real unit)")

    # (4g) WHAT THE BARE-"ft" FALLBACK DOES AND DOES NOT PRESERVE, pinned in both directions,
    #      because the comment beside it in normalize.py twice claimed a false universal: "no
    #      string that got the sq ft band under the substring test may lose it here". Strings
    #      DO lose it, and (4f) above already asserted one of them ("draft"). Every word with
    #      `ft` buried inside it was widened to the IMPERIAL band by `"ft" in str(unit)` and
    #      now correctly gets the METRIC one - none of them is a unit, so none should ever have
    #      had the imperial band, and the metric band is this function's documented answer for
    #      an unrecognised unit. The class is unbounded, not a list; these are the fourteen
    #      confirmed by execution and they are pinned so the true statement stays true.
    _LOST = ("draft", "left", "loft", "shaft", "aft", "after", "crafted", "fifty",
             "rafters", "soft", "shift", "gift", "lift", "oft")
    for _u in _LOST:
        check("ft" in _u and N.area_band_for(_u) == (N.AREA_SQM_MIN, N.AREA_SQM_MAX),
              f"{_u!r} carries `ft` as a SUBSTRING only, so it loses the imperial band the old "
              f"substring test gave it - correctly, and by design")
    #      What is actually preserved: any string carrying a STANDALONE imperial token, which
    #      is the only class the fallback was ever needed for (a bare column suffix). A
    #      NARROWER band is the direction that strikes data, so this half must never regress.
    for _u in ("ft", "FT", "ft/yr", "area ft", "ft.", "gross ft", "ft ", " ft"):
        check(N.area_band_for(_u) == (N.AREA_SQFT_MIN, N.AREA_SQFT_MAX),
              f"{_u!r} carries a standalone `ft` token, so the fallback keeps its imperial "
              f"band (this is the class the fallback exists for)")
    #      and the substring test's OTHER half, which the tightening FIXES rather than
    #      preserves: "square feet" and "psf" carry no literal `ft` at all, so `"ft" in unit`
    #      MISSED two of the commonest real spellings while widening `draft`. Both are resolved
    #      by area_unit_of now, which is the point - the canonicaliser knows the unit, the
    #      substring never did.
    for _u in ("square feet", "psf"):
        check("ft" not in _u.lower()
              and N.area_band_for(_u) == (N.AREA_SQFT_MIN, N.AREA_SQFT_MAX),
              f"{_u!r} contains no literal `ft`, so the old substring test MISSED it; "
              f"area_unit_of resolves it to the sq ft band")
    for _u in ("sq. ft.", "ft2", "ft²", "SQFT"):
        check(N.area_band_for(_u) == (N.AREA_SQFT_MIN, N.AREA_SQFT_MAX),
              f"{_u!r} resolves through area_unit_of, so it never depends on the fallback")
    check(merge._pick_gate_verdict("plotArea", 630000, None, "sq m") == "pass"
          and merge._pick_gate_verdict("warehouseArea", 630000, None, "sq m") == "fail",
          "mechanism (2)'s sq m verdicts are untouched by the new unit branches")

    # (4h) THE ADVISORY ARM OF THE SAME BAND. vision_validate read `area_band_for` without the
    #      `field` argument, so it judged a PLOT against the BUILDING ceiling - the T1
    #      false-absence class one layer down. It is a printed WARNING and never a strike, so
    #      the cost is reviewer time and the band's credibility rather than data, but a band
    #      that tells a reviewer to doubt a figure the page plainly prints is a band nobody
    #      reads. Driven through `validate()` rather than asserted on the source, so the fix
    #      cannot be satisfied by a comment. `field` only ever widens the CEILING and never
    #      touches the floor, so this can be pinned without loosening the garble catch below.
    import tempfile as _tf
    import vision_validate as VV  # noqa: E402

    def _vision_warnings(records, unit="sq m"):
        w = Path(_tf.mkdtemp(prefix="cbre_vision_band_"))
        (w / "vision").mkdir()
        (w / "extract").mkdir()
        (w / "vision" / "manifest.json").write_text(json.dumps(
            {"decks": [{"cluster_label": "Zone", "source_file": "deck.pdf",
                        "pages": [{"page_no": 0}]}]}), encoding="utf-8")
        (w / "extract" / "Zone_vision.json").write_text(json.dumps(
            [dict(r, areaUnit=unit, __meta={"page_no": 0, "source_file": "deck.pdf"})
             for r in records]), encoding="utf-8")
        errs, warns = VV.validate(w)
        return errs, [x for x in warns if "plausibility band" in x]

    for _unit, _v, _fld in (("sq m", 630_000, "plotArea"), ("sq m", 772_000, "plotArea"),
                            ("sq ft", 8_000_000, "plotArea")):
        _e, _w = _vision_warnings([{"park": "P", _fld: _v}], unit=_unit)
        check(not _w,
              f"vision_validate does NOT warn about a {_v:,} {_unit} PLOT - the site ceiling "
              f"rides the `field` argument here too {_w}")
    _e, _w = _vision_warnings([{"park": "P", "warehouseArea": 630_000}])
    check(len(_w) == 1 and "warehouseArea" in _w[0],
          f"...while a 630,000 sq m BUILDING still draws the advisory (the building ceiling is "
          f"untouched) {_w}")
    _e, _w = _vision_warnings([{"park": "P", "plotArea": 12_000_000}])
    check(len(_w) == 1 and "plotArea" in _w[0],
          f"...and a 12M sq m plot garble is still caught by the PLOT ceiling {_w}")

    # BTS is data: contract text pinned in both places, and no sentinel swallows it
    check("BUILT TO SUIT" in R._FIELD_RULES and "tbd/TBC/BTS/TBS" not in R._FIELD_RULES,
          "run.py field_rules: BTS is data, no longer an unknown sentinel")
    interp = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    check("`BTS` is NOT unknown" in interp,
          "interpretation.md carries the BTS-is-data rule")
    check(not N.looks_unknown("BTS") and N.sentinel("BTS") == "BTS",
          "no Python sentinel swallows a printed 'BTS'")

    print(f"\n{'PASS' if not fails else 'FAIL'} strike_disclosure_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
