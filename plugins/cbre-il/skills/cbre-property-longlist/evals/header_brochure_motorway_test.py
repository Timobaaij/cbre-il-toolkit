#!/usr/bin/env python3
"""v37: the hero heading, the dropped Developers KPI, the brochure link, and a
card-sized motorway locator.

Four broker-asked changes, pinned so a revert fails here rather than on a client run:

  1. the hero heading reads "Logistics ...", capitalised;
  2. the Developers / Major landlords KPI tile is gone - tile, token, computation and
     i18n keys, with nothing orphaned;
  3. a property that states a brochure URL gets a View brochure link in its modal, and a
     tracker column carrying those URLs binds to `brochureLink`;
  4. a prose motorway description is condensed to a locator that fits a card, using only
     tokens the source itself states.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C          # noqa: E402
import i18n as I18N          # noqa: E402
import normalize as N        # noqa: E402
import extract_xlsx as X     # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    t = C.load_template()
    print("== hero heading ==")
    ck(I18N.EN["hero_title_html"].startswith("Logistics "),
       "the EN hero heading is capitalised")
    ck("logistics <em>" not in I18N.EN["hero_title_html"],
       "the lower-case form is gone")

    print()
    print("== Developers KPI removed ==")
    ck("kpi_developers" not in t, "the tile is gone from the template")
    ck("kpi_developers" not in C.CONFIG_TOKENS, "the config token is gone")
    ck(not any(k.startswith("kpi_developers") for k in I18N.EN),
       "its i18n keys are gone from EN")
    for p in sorted((ROOT / "assets" / "i18n").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        ck(not any(k.startswith("kpi_developers") for k in d),
           f"...and from the {p.stem} pack")
    bd = (ROOT / "helpers" / "build_dashboard.py").read_text(encoding="utf-8")
    ck("kpi_developers" not in bd, "build_dashboard no longer computes it")
    ck("kpi_properties" in t and "kpi_regions" in t and "kpi_rent" in t,
       "the other KPI tiles are untouched")

    print()
    print("== brochure link ==")
    sch = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    props = sch["$defs"]["property"]["properties"] if "$defs" in sch else {}
    ck("brochureLink" in props, "the schema declares brochureLink")
    ck("brochureLink" in C.canonical_property_fields(),
       "brochureLink is a canonical property field")
    ck("p.brochureLink" in t, "the modal reads p.brochureLink")
    ck('T("modal_open_brochure")' in t, "it renders through an i18n label, not hardcoded prose")
    ck("modal_open_brochure" in I18N.EN, "the label exists in EN")
    for p in sorted((ROOT / "assets" / "i18n").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        ck("modal_open_brochure" in d, f"...and in the {p.stem} pack")
    aliases = [a.lower() for a in X.HEADER_ALIASES.get("brochureLink", [])] \
        if hasattr(X, "HEADER_ALIASES") else []
    if not aliases:
        src = (ROOT / "helpers" / "extract_xlsx.py").read_text(encoding="utf-8")
        m = re.search(r'"brochureLink":\s*\[(.*?)\]', src, re.S)
        aliases = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    ck("online brochure link" in aliases and "brochure" in aliases,
       "a tracker's brochure column binds to brochureLink")

    print()
    print("== motorway locator ==")
    ck(N.MOTORWAY_MAX == 40, "the limit is 40 characters")
    CASES = [
        ("Junction 18/18A M5 2 miles to the south; Junction 1 M49 4.5 miles to the north; "
         "M4/M5 interchange 10 miles to the north", "M5 J18/18A 2 miles; M49 J1 4.5 miles"),
        ("Adjacent to J19 M5 Portbury Docks; accessed just off J19 of the M5 motorway. "
         "The M49 (via J18/18a, M5) the link to South Wales is approximately 3 miles to "
         "the North", "M5 J19 adjacent; M49 3 miles"),
        # B-motorway-fix: a SINGLE clause (no ';'/'.' separator) naming three roads and two
        # distances. The road/junction pair found is M1 J19; the correct distance is the one
        # printed right beside it (28 miles), not the first distance in the sentence (11 miles,
        # which belongs to the A14 mention). A live run shipped "M1 J19 11 miles" here - a
        # fabricated-looking 17-mile error - before distance selection became proximity-aware.
        ("Evo Corby has immediate access to the A43, is only 11 miles to the A14, and 28 "
         "miles from Junction 19 of the M1.", "M1 J19 28 miles"),
    ]
    for src, want in CASES:
        got, cut = N.short_motorway(src)
        ck(got == want and cut, f"{len(src)} chars -> {got!r}")
    for short in ("M4, J17", "Junction 17, M4", "M4 Junction 15 - 5 miles / 8 mins",
                  "M5/M49 junctions 18/18a"):
        got, cut = N.short_motorway(short)
        ck(got == short and not cut, f"already short, untouched: {short!r}")
    long_prose = ("Situated in a prime location with excellent connectivity to the "
                  "national motorway network and the ports beyond")
    got, cut = N.short_motorway(long_prose)
    ck(cut and len(got) <= N.MOTORWAY_MAX,
       f"unparseable prose is cut at a word boundary ({got!r})")
    ck(all(tok in long_prose for tok in got.split()),
       "...and every surviving token came from the source")
    mg = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8")
    ck("N.short_motorway(p[\"motorway\"])" in mg,
       "merge.canonicalize applies it, so every source path gets it")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
