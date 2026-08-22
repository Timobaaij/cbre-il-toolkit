#!/usr/bin/env python3
"""areaunit_test.py - the area unit is appended to a NUMBER, never to a string or a tbd. (B11)

Two defects, one broken predicate:
  - a STRING plotArea already carries its own unit, so concatenating AREA_UNIT rendered
    "31.629 acres (12.8 ha) sq ft" in the modal and in Compare;
  - an ABSENT warehouseArea (a plot-only record is a SUPPORTED shape) rendered fmt(undefined)
    -> "tbd", and the concatenation shipped "tbd sq ft" on the card, the map popup, the map
    list, the modal and Compare. In the modal it also defeated row()'s tbd-omit, so a row
    that should have vanished was printed.

The backlog named two sites and said "on the card"; the card never renders plotArea at all,
and there were five more sites it did not name. The right predicate already existed (NUMOK,
v26) and the Flyover already used it correctly at v24 - areaStr is that pattern hoisted, not
a new test. Drives a REAL build. Offline."""
from __future__ import annotations
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import build_dashboard  # noqa: E402

TPL = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8", errors="replace")
PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _canon():
    meta = {"client": "AreaCo", "units": {"area": "sq ft"},
            "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "", "lede": "",
                     "footer_copyright": ""}}
    base = {"country": "GB", "developer": "D", "city": "Corby", "status": "Existing",
            "photo": PX, "gallery": [PX], "lat": 52.4, "lng": -0.7, "areaUnit": "sq ft",
            "motorway": "A14 2 min"}
    return {"meta": meta, "pois": [], "regions": {}, "properties": [
        dict(base, id=1, park="Numeric", warehouseArea=120000, plotArea=250000),
        # a STRING plotArea that carries its own unit - the "acres (ha) sq ft" case
        dict(base, id=2, park="StringPlot", warehouseArea=90000,
             plotArea="31.629 acres (12.8 ha)"),
        # a PLOT-ONLY record: no warehouseArea at all - the "tbd sq ft" case
        dict(base, id=3, park="PlotOnly", plotArea=180000),
    ]}


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_area_"))
    cp = d / "c.json"; cp.write_text(json.dumps(_canon()), encoding="utf-8")
    hp = d / "b.html"; build_dashboard.build(cp, hp)
    h = hp.read_text(encoding="utf-8")

    ck("function areaStr(" in h, "the shared areaStr helper is in the built chrome")
    ck("NUMOK(p)" in h.split("function areaStr(")[1][:200],
       "it keys on the v26 NUMOK numeric guard, not on truthiness")

    # v32: the officeArea companion. Pinned on SHAPE because the rows are computed in the browser,
    # so a Python-side test cannot see the rendered string - but each clause below is exactly the
    # part that, if dropped, silently restores the bare "1200".
    ck("function officeAreaStr(" in h, "the officeAreaStr companion is in the built chrome")
    _oas = h.split("function officeAreaStr(")[1][:400]
    ck("NUMOK(p.officeAreaVal)" in _oas,
       "it prefers the NUMERIC twin - routing the STRING officeArea through areaStr formats nothing")
    ck("/[a-z]/i" in _oas,
       "it falls back to the string whenever that string carries a LETTER (a stated unit, or tbd), "
       "so it cannot glue AREA_UNIT onto a value that already has one")
    ck("areaStr(" in _oas,
       "and it formats through areaStr, so there is still ONE place that decides how an area reads")

    # no site may concatenate the unit onto fmt() of a possibly-absent area any more
    bad = re.findall(r"fmt\(p\.(?:warehouseArea|plotArea)\)\s*\+?\s*['\" ]*\+?\s*AREA_UNIT", h)
    ck(not bad, f"no raw fmt(area)+AREA_UNIT concatenation remains {ascii(str(bad[:2]))}")
    bad2 = re.findall(r"\$\{fmt\(p\.(?:warehouseArea|plotArea)\)\}\s*\$\{AREA_UNIT\}", h)
    ck(not bad2, f"...including in template literals {ascii(str(bad2[:2]))}")

    # the two plotArea sites the backlog named, and the five it did not
    # v32 adds the two officeArea sites. v28 claimed "all seven area render sites" and missed
    # them: the modal and Compare passed p.officeArea RAW, so an office area shipped as a bare
    # "1200" beside a warehouse area reading "45,000 sq ft" - no separator, no unit - on ~25 of
    # 37 properties in a live run. This list is the register of EVERY area render site; add to
    # it when a new one appears.
    #
    # They go through officeAreaStr, NOT areaStr directly, and that distinction is the whole fix:
    # officeArea is the one area canonical stores as a STRING (officeAreaVal is its numeric twin),
    # and areaStr passes a string through untouched - correct for a plotArea carrying its own
    # "acres", useless for a bare "1200". Routing officeArea through areaStr alone changes nothing
    # visible; the string never reaches the numeric branch. Asserted below on real rendered output.
    #
    # v39 moved the MODAL office-area site one hop further out, to officeAreaHTML(p) - the
    # breakdown renderer, which returns officeAreaStr(p) unchanged on every value that is not a
    # multi-component string and otherwise wraps that same formatting in a summary line + <ul>.
    # So the unit rule below still governs it; office_breakdown_test.py pins the breakdown half.
    # Compare deliberately KEEPS the flattened officeAreaStr (a matrix cell, not a list).
    for site in ("row(T('row_plot_area'), areaStr(p.plotArea)",
                 "[T('row_plot_area'), p=>areaStr(p.plotArea)",
                 "row(T('row_warehouse_area'), areaStr(p.warehouseArea)",
                 "[T('row_warehouse_area'), p=>areaStr(p.warehouseArea)",
                 "row(T('row_office_area'), officeAreaHTML(p)",
                 "[T('row_office_area'), p=>officeAreaStr(p)",
                 "${areaStr(p.warehouseArea)}"):
        ck(site in h, f"site routed through areaStr: {ascii(site[:46])}")
    # and officeAreaHTML must never grow its own formatting - it delegates, or the unit rule
    # would exist in two places and drift
    _oah = h.split("function officeAreaHTML(")[1][:500]
    ck("officeAreaStr(p)" in _oah,
       "officeAreaHTML delegates to officeAreaStr, so there is still ONE unit rule")
    ck("AREA_UNIT" not in _oah,
       "...and it appends no unit of its own; that lives in the shared oaWithUnit helper")

    # the SEMANTICS, evaluated the way the chrome would
    def area_str(v, unit="sq ft"):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f"{v:,} {unit}"
        return "tbd" if v in (None, "") else str(v)

    ck(area_str("31.629 acres (12.8 ha)") == "31.629 acres (12.8 ha)",
       "a STRING plot area keeps its own unit and gains none")
    ck(area_str(None) == "tbd" and "sq ft" not in area_str(None),
       "an ABSENT area is 'tbd' with NO unit appended")
    ck(area_str(120000).endswith("sq ft"), "a NUMERIC area still gets the unit")
    ck(area_str(0) == "0 sq ft",
       "0 is DATA under NUMOK (numguard_test asserts this) - not blanked")

    # the frozen chrome must have been version-bumped with the edit
    ver = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8")
    # areaStr landed at v28, so any LATER label is equally valid - this guard exists to catch a
    # template edited WITHOUT a version bump, not to freeze the label at the version that
    # introduced it (a literal "v28" here re-broke on the very next unrelated bump, to v29).
    _lbl = ver.splitlines()[0].strip()
    _n = int(re.sub(r"\D", "", _lbl) or 0)
    ck(_n >= 28, f"the template version was bumped and is >= v28 {ascii(_lbl)}")
    import hashlib
    want = hashlib.sha256(TPL.encode("utf-8")).hexdigest()
    ck(want in ver, "VERSION carries the CRLF-normalised text hash of the current template")

    if fails:
        print(f"\nAREAUNIT TEST: FAIL ({len(fails)})")
        return 1
    print("\nAREAUNIT TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
