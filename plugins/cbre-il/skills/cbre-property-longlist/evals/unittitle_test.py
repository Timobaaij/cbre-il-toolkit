#!/usr/bin/env python3
"""unittitle_test.py - a card TITLE identifies ONE option, not one park.

THE DEFECT. There was no canonical `unit` field: the schema declared 56 property keys and none
of them named the unit / phase / block a source prints for an option within its park. Every
title and label site interpolated `p.park` ALONE, so two genuinely different units on one park
rendered as two identical-looking cards - in the grid, the map popup, the map list, the modal,
the Flyover slide and tooltip, and in BOTH sets of comparison chips, which is the exact moment
the broker is being asked to choose between them.

THE FIX HAS TWO HALVES, and this eval pins both.
  (a) `unit` is a canonical string field, carried end to end: declared in the schema, on the
      chrome string-field list (so an unfilled one is the honest sentinel and a bare numeric is
      coerced rather than hard-failing), bound from a spreadsheet column, read from a document
      label table, and named in the reader contract so an extraction agent captures it.
  (b) ONE helper composes the title - `titleStr(p)` - and every title site calls it. The sites
      reachable from a node sandbox are EXECUTED (the .mjs sibling); the four that are closed
      over inside a view IIFE, or need a live DOM, are pinned STRUCTURALLY against the built
      template, which is the same split percard_completeness_test uses for `slideHtml`.

The three behaviours that make it safe rather than merely present are pinned by execution:
an ABSENT unit renders today's title byte-for-byte (no trailing separator, no word for
unknown); a park name that already carries the designator does not repeat it; and a unit that
merely looks like a substring of the park name is NOT falsely suppressed.

Offline. Drives a real build; needs node for the executed half.
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
import _common as C  # noqa: E402
import build_dashboard  # noqa: E402
import extract_pdf as XP  # noqa: E402
import extract_xlsx as XL  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _canon(props):
    base = {"country": "GB", "developer": "Dev", "city": "Corby", "status": "Available",
            "photo": PX, "gallery": [PX], "lat": 52.49, "lng": -0.69, "areaUnit": "sq ft",
            "rentUnit": "\u00a3/sq ft/yr", "warehouseRent": "\u00a39.50 / sq ft / year",
            "warehouseRentVal": 9.5}
    return {"meta": {"client": "UnitTitle", "units": {"area": "sq ft",
                                                      "rent": "\u00a3/sq ft/yr"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def main() -> int:
    print("== (a) `unit` is a canonical field, declared and typed ==")
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    props = schema["$defs"]["property"]["properties"]
    ck("unit" in props, "canonical.schema.json declares a top-level `unit` property")
    ck(props.get("unit", {}).get("type") == "string",
       f"`unit` is type string, got {props.get('unit', {}).get('type')!r}")
    _desc = (props.get("unit", {}).get("description") or "")
    ck("as printed" in _desc or "PRINTS" in _desc or "prints" in _desc,
       "the schema tells a reader to keep the source's own printed designator")

    C._CANON_PROPERTY_FIELDS = None          # force a fresh scan (module-level cache)
    C._STRING_FIELDS_STRUCT = None           # the memoised degraded-path type set
    ck("unit" in C.canonical_property_fields(), "`unit` is a live canonical field")
    ck("unit" in C.STRING_FIELDS, "`unit` is on the chrome string-field list")
    ck("unit" in C._string_fields_struct(),
       "...so the degraded (jsonschema-less) path type-checks it too")
    ck("unit" in C._COERCE_STR,
       "...and a tracker's bare numeric designator is coerced to a string, not a schema failure")
    ck(C.fill_render_sentinels({"unit": None}).get("unit") == C.BLANK,
       "an unstated unit becomes the honest blank sentinel, never an invented value")
    ck(C.fill_render_sentinels({"unit": 3}).get("unit") == "3",
       "a bare numeric designator is coerced to '3'")

    print()
    print("== (a) the spreadsheet column alias table ==")
    ck("unit" in XL.COLUMN_MAP, "extract_xlsx.COLUMN_MAP binds a `unit` column")
    ck(XL._header_field("Unit") == "unit", "'Unit' binds to unit")
    ck(XL._header_field("Unit Number") == "unit", "'Unit Number' binds to unit")
    ck(XL._header_field("Phase") == "unit", "'Phase' binds to unit (a phase IS a designator)")
    ck(XL._header_field("Unit Name") == "park",
       "'Unit Name' still binds to PARK - a pre-existing alias, deliberately not moved")
    for hdr in ("Size Unit", "Unit Size", "Unit Type", "Number of units"):
        ck(XL._header_field(hdr) != "unit",
           f"{hdr!r} is vetoed - it measures/classifies, it does not designate")
    ck("unit" in XL.NEGATIVE, "a NEGATIVE veto guards the short `unit` alias")

    print()
    print("== (a) the document field table ==")
    _unit_labels = [p for p, f, k in XP.LABELS if f == "unit"]
    ck(bool(_unit_labels), f"extract_pdf.LABELS reads a unit designator {_unit_labels}")
    ck(all(k == "text" for p, f, k in XP.LABELS if f == "unit"),
       "every unit label is kind 'text' (the designator is printed, never parsed as a number)")
    ck("Unit" not in _unit_labels,
       "a BARE 'Unit' label is deliberately absent - it would claim marketing prose "
       "('Unit sizes from ...') straight into the card title, with no NEGATIVE table to veto it")

    print()
    print("== (a) the reader contract names it ==")
    interp = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    ck("`unit`" in interp, "reference/interpretation.md names the `unit` field")
    ck("unit, warehouseArea" in interp or " unit," in interp,
       "...and `unit` appears in the reader-fillable field registry copy")
    ck("designator" in interp.lower(),
       "...and explains that it is the option's own printed designator")
    import run as R  # noqa: E402  (imported late: it is heavy)
    ck("unit" in R._reader_field_list(),
       "the exit-3 manifest's live `fields` list now offers `unit` to every reader")

    print()
    print("== (b) ONE helper, and every title site calls it ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps(_canon([
            # two genuinely different UNITS on one park
            dict(id=1, park="Kestrel Reach", unit="Unit 3", warehouseArea=40000),
            dict(id=2, park="Kestrel Reach", unit="Unit 4", warehouseArea=30000),
            # the park name already ENDS with the designator
            dict(id=3, park="Kestrel Reach Unit 5", unit="Unit 5", warehouseArea=25000),
            # no unit at all -> today's title, byte-for-byte
            dict(id=4, park="Solo Park", warehouseArea=20000),
            # a unit that only LOOKS like a substring of the park name
            dict(id=5, park="Harrier Court 300", unit="3", warehouseArea=15000),
        ])), encoding="utf-8")
        build_dashboard.build(cp, hp)
        built = hp.read_text(encoding="utf-8")

        ck("function titleStr(p)" in built, "the built chrome defines the single titleStr(p)")
        ck(built.count("function titleStr(p)") == 1,
           "exactly ONE definition - a second would be a second point of truth")

        # the sites a node sandbox cannot reach: closed over in a view IIFE, or DOM-bound
        STRUCTURAL = [
            (r'class="tray-chip">\$\{titleStr\(p\)\}', "the compare TRAY chip"),
            (r'class="mli-title">\$\{titleStr\(p\)\}', "the map list item title"),
            (r"""'<div class="fo-name">' \+ esc\(titleStr\(p\)""", "the Flyover slide name"),
            (r'm\.bindTooltip\(\(i \+ 1\) \+ "\. " \+ \(titleStr\(p\)',
             "the Flyover map tooltip"),
            (r"function label\(p\) \{ return titleStr\(p\)", "the Compare VIEW chip label"),
        ]
        for rx, what in STRUCTURAL:
            ck(bool(re.search(rx, built)), f"{what} composes its text through titleStr()")
        # and no title site was left interpolating the bare park name
        ck(not re.search(r'class="card-title">\$\{p\.park\}', built),
           "no title site still interpolates p.park alone (card)")
        ck(not re.search(r'class="modal-title">\$\{p\.park\}', built),
           "no title site still interpolates p.park alone (modal)")
        ck("[p.park, p.unit, p.developer" in built,
           "the search haystack carries `unit`, so a designator shown on the card is findable")

        node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
        mjs = Path(__file__).with_suffix(".mjs")
        if not Path(node).exists() and not shutil.which("node"):
            ck(False, "node is required to execute the chrome (install node or add it to PATH)")
        else:
            print()
            r = subprocess.run([node, str(mjs), str(hp)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            print((r.stdout or "").rstrip())
            if r.returncode != 0:
                print((r.stderr or "").rstrip())
            ck(r.returncode == 0, "the EXECUTED title assertions pass (see above)")

    print()
    print("== the version, the hash chain and the changelog ==")
    label = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    ck(int(re.sub(r"\D", "", label) or 0) >= 40,
       f"assets/VERSION was bumped at/after the unique-title change (v40) {ascii(label)}")
    expected = hashlib.sha256(C.load_template().encode("utf-8")).hexdigest()
    recorded = C.load_version().get("chrome_sha256", "")
    ck(recorded == expected,
       f"VERSION's chrome_sha256 is the newline-normalised TEXT hash of the live template "
       f"(recorded {recorded[:12]}, computed {expected[:12]})")
    changelog = (ROOT / "reference" / "template-contract.md").read_text(encoding="utf-8")
    ck("**v40**" in changelog, "reference/template-contract.md has a v40 entry")
    _v40 = changelog.split("**v40**", 1)[-1] if "**v40**" in changelog else ""
    # one needle per template change, so a v40 entry that documents three of the four fails
    for needle in ("tile.openstreetmap.org", "titleStr", "statedTotal", "plan-mode"):
        ck(needle in _v40, f"the v40 entry names {needle}")
    # PINNED TO assets/VERSION, not to a literal. This used to assert the line read "v40", which
    # made the check rot the moment the template was bumped: it went red on v42 while the
    # document was CORRECT and up to date, which is the worst failure a pin can have because the
    # obvious way to clear it is to edit the document back to something false. What the check is
    # actually for is that the contract document does not go STALE against the template it
    # documents, so it now compares the two directly and reports both when they differ.
    doc_v = changelog.split("The current template is", 1)[-1][:24]
    ck(f"**{label}**" in doc_v,
       f"the contract's own current-version line agrees with assets/VERSION "
       f"(VERSION says {ascii(label)}, the document says {ascii(doc_v.strip()[:12])})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
