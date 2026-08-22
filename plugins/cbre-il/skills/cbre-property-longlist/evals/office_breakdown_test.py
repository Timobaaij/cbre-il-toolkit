#!/usr/bin/env python3
"""office_breakdown_test.py - v39: a MULTI-COMPONENT officeArea reads as a bold summary line
over a real bulleted breakdown, and every other shape is untouched.

THE DEFECT, from a live broker review. `officeArea` is the ONE area canonical stores as a STRING
(`officeAreaVal` is its numeric twin - see v32 / areaunit_test), and for a property with several
non-warehouse components it arrives as a single run-on sentence:

    "45,649 sq ft total non-warehouse area (offices, 2 levels 28,804; 2nd floor meeting room
     1,711; transport office 1 7,492; transport office 2 7,427; gatehouse 215)"

which rendered as one unbroken paragraph in the detail modal. It now renders as a bold summary
line over a real `<ul>/<li>` list.

WHAT THIS PINS, and why each half exists:
  * the FOUR shapes live datasets actually carry - a leading summary plus a parenthesised
    `;`-separated breakdown; a bare `;` list with no summary; a `;` list whose items own their
    trailing qualifier; and the plain/`tbd` cases that are the overwhelming majority;
  * REAL MARKUP, not escaped text. `row()` interpolates its value raw, so a `<ul>` is a list.
    This is the assertion the whole fix stands on, and it is executed, not read;
  * NO SECOND UNIT. A unit is appended only to a fragment with no letter of its own, so
    "Main Office 15,213 sq ft" is left alone - this codebase has a documented history of exactly
    that class of error (v28's "tbd sq ft", the 10.76x area-unit family);
  * NO INVENTED AREA. "transport office 2" is a NAME ending in an index, not a 2 sq ft room, so
    a 1-2 digit tail never becomes an area;
  * BYTE-IDENTITY on every plain shape: `officeAreaHTML(p) === officeAreaStr(p)` whenever the
    string carries no letter, so a bare number, an absent value and `tbd` render exactly as they
    did before v39 and the numeric twin can never be overridden;
  * COMPARE STAYS FLATTENED - a five-item list in one matrix cell sets the row height for every
    column and destroys the side-by-side scan (v37's `short_motorway` reasoning). That is a
    deliberate design split, so it is pinned rather than left to drift.

The behavioural half EXECUTES the real chrome in node:vm (the .mjs sibling); the structural half
pins the two call sites and the list CSS in the built file. Drives a REAL build. Offline.
"""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C          # noqa: E402
import build_dashboard       # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

SHAPE_A = ("45,649 sq ft total non-warehouse area (offices, 2 levels 28,804; "
           "2nd floor meeting room 1,711; transport office 1 7,492; "
           "transport office 2 7,427; gatehouse 215)")


def _canon():
    meta = {"client": "OfficeCo", "units": {"area": "sq ft"},
            "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "", "lede": "",
                     "footer_copyright": ""}}
    base = {"country": "GB", "developer": "D", "city": "Corby", "status": "Existing",
            "photo": PX, "gallery": [PX], "lat": 52.4, "lng": -0.7, "areaUnit": "sq ft",
            "motorway": "A14 2 min", "warehouseArea": 400000}
    props = [
        # A: leading summary clause + a parenthesised, ;-separated breakdown
        dict(id=1, park="Shape A", officeArea=SHAPE_A, officeAreaVal=45649),
        # B: a ;-list with NO summary, every item stating its own unit
        dict(id=2, park="Shape B", officeAreaVal=19482,
             officeArea="Main Office 15,213 sq ft; Hub Office 3,975 sq ft; Gatehouse 294 sq ft"),
        # C: a ;-list whose items carry their OWN trailing parenthesised qualifier
        dict(id=3, park="Shape C", officeAreaVal=30078,
             officeArea="14,486 sq ft (ground floor); 15,592 sq ft (first floor)"),
        # D: the majority shapes - a bare number, a value already carrying its unit, tbd, absent
        dict(id=4, park="Plain Number", officeArea="24230", officeAreaVal=24230),
        dict(id=5, park="Plain Unit", officeArea="8,547 sq ft", officeAreaVal=8547),
        dict(id=6, park="Tbd Park", officeArea="tbd"),
        dict(id=7, park="No Office Park"),
        # a component NAME that ends in an index, beside an area-bearing sibling
        dict(id=8, park="Index Name",
             officeArea="Office block A 12,000; Transport office 2"),
        # a summary clause that is itself a bare number
        dict(id=9, park="Bare Summary",
             officeArea="24,230 (offices 20,000; gatehouse 4,230)", officeAreaVal=24230),
    ]
    return {"meta": meta, "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def main() -> int:
    fails = []

    def ck(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps(_canon()), encoding="utf-8")
        build_dashboard.build(cp, hp)
        built = hp.read_text(encoding="utf-8")

        print("== structural: the call sites and the list CSS ==")
        ck("function officeAreaHTML(" in built,
           "the built chrome defines officeAreaHTML - the display-only breakdown renderer")
        ck("row(T('row_office_area'), officeAreaHTML(p)" in built,
           "the MODAL row renders the breakdown")
        ck("[T('row_office_area'), p=>officeAreaStr(p)" in built,
           "COMPARE deliberately keeps the flattened officeAreaStr (a matrix cell, not a list)")
        ck(".oa-breakdown{" in built and "list-style:disc" in built,
           "the list CSS is declared explicitly rather than left to the UA default")

        # the display change must not touch the arithmetic: officeAreaVal is what the sums read
        _gla = built.split("function glaVal(")[1][:300]
        ck("p.officeAreaVal" in _gla and "officeAreaHTML" not in _gla,
           "glaVal still sums the NUMERIC twin and never consults the display renderer")
        _tot = built.split("function totalAnnualRent(")[1][:600]
        ck("p.officeAreaVal" in _tot and "officeAreaHTML" not in _tot,
           "totalAnnualRent likewise - this is a display-only change")
        ck(built.count("officeAreaHTML(p))") == 1,
           "exactly ONE call site renders the breakdown (the modal row)")

        print()
        print("== the version bump the template contract requires ==")
        ver = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8")
        label = ver.splitlines()[0].strip()
        num = int(re.sub(r"\D", "", label) or 0)
        # >= rather than == v39: a literal re-breaks on the next unrelated bump (areaunit_test's
        # own recorded lesson, which a literal "v28" cost once already).
        ck(num >= 39, f"assets/VERSION is >= v39 {ascii(label)}")
        ck(hashlib.sha256(C.load_template().encode("utf-8")).hexdigest() in ver,
           "VERSION carries the CRLF-normalised TEXT hash of the edited template")

        print()
        print("== behavioural: the real chrome, executed ==")
        node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
        if not shutil.which("node") and not Path(node).exists():
            ck(False, "node is required to execute the chrome (install node or add it to PATH)")
        else:
            mjs = Path(__file__).with_suffix(".mjs")
            p = subprocess.run([node, str(mjs), str(hp)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            print((p.stdout or "").rstrip())
            if p.returncode != 0:
                print((p.stderr or "").rstrip())
            ck(p.returncode == 0, "the executed breakdown assertions pass (see above)")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
