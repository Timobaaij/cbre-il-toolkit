#!/usr/bin/env python3
"""percard_completeness_test.py - PER-PROPERTY completeness across every surface. (B58, v33)

THE RULE the broker asked for, in one line: for each property individually, show every variable
that has a value for THAT property, and render no row for a variable it lacks. If option A has 10
filled variables and option B has 15, A shows 10 rows and B shows 15. Never a page of tbd.

WHERE IT WAS ALREADY TRUE. The detail modal has been per-property since v21 (curated rows omit
when absent) + v22 (a catch-all that auto-shows any remaining real scalar, including field names
in no schema at all).

WHERE IT WAS FALSE, and this is what v33 fixes:
  * FLYOVER rendered a HARDCODED 9-row spec list, so a field the modal displayed - sprinklers,
    permitting, rent-free, divisible-from, expansion, office rent, or any brand-new key - was
    invisible on every slide, for every property.
  * COMPARE's row list is hand-written, so a field the DATASET carries but nobody wrote a row for
    never appeared at all. `landPrice`, `incentives`, `reit` and `epc` were all in that position,
    as is any new scalar an interpretation record introduces (meta.newFields).

WHAT THIS PINS. The modal and compare assertions EXECUTE the real chrome in node:vm (the .mjs
sibling), so they test behaviour, not prose. The Flyover assertion is structural - `slideHtml`
lives inside the view's IIFE and is not reachable from the sandbox - so it extracts the catch-all
FROM the built template and pins its clauses, in the style of landoption_test: a revert to the
fixed list fails, and so does dropping any of the DENY_FIELDS / LOCATOR_RE / absent guards that
stop it leaking a locator string or a neighbour's photo key into the panel.
Offline. Drives a real build.
"""
from __future__ import annotations
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
import build_dashboard  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _canon(props):
    meta = {"client": "PerCard", "units": {"area": "sq m"},
            "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "", "lede": "",
                     "footer_copyright": ""}}
    base = {"country": "CZ", "developer": "D", "city": "Bor", "status": "Available",
            "photo": PX, "gallery": [PX], "lat": 49.75, "lng": 12.77, "areaUnit": "sq m",
            "rentUnit": "€/sq m/yr"}
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
        cp.write_text(json.dumps(_canon([
            # RICH: canonical extras + two keys that exist in NO schema (the v22/v33 path)
            dict(id=1, park="Rich Park", warehouseArea=50000, warehouseRent="€60 / sq m / year",
                 warehouseRentVal=60, sprinklers="Yes", permitting="Consented",
                 landPrice="Not charged", incentives="6 months fit-out",
                 yardRent="€10,000 per annum", railSiding="Yes"),
            # LEAN: the same base, none of the extras
            dict(id=2, park="Lean Park", warehouseArea=30000, warehouseRent="€55 / sq m / year",
                 warehouseRentVal=55),
        ])), encoding="utf-8")
        build_dashboard.build(cp, hp)
        built = hp.read_text(encoding="utf-8")

        # ---------- Flyover: structural pin (slideHtml is closed over inside the view IIFE) ----------
        m = re.search(r'function slideHtml\(p, i\)\s*\{(.*?)\n  \}', built, re.S)
        ck(bool(m), "the built chrome still defines the Flyover slideHtml()")
        body = m.group(1) if m else ""
        ck("DENY_FIELDS" in body,
           "flyover: the catch-all is present and reuses the modal's DENY_FIELDS")
        ck("autoLabel" in body,
           "flyover: it labels unknown keys through the shared autoLabel, not a second convention")
        ck("Object.keys(p)" in body,
           "flyover: it iterates the PROPERTY's own keys - the per-property rule, not a fixed list")
        ck("LOCATOR_RE" in body,
           "flyover: a page/source locator string can never render as a value")
        ck("foCurated" in body,
           "flyover: the curated rows are registered, so no field renders twice")
        ck(body.index("DENY_FIELDS") < body.index("driveHighlights"),
           "flyover: the catch-all runs with the spec rows, before the drive-time block")

        # ---------- Modal + Compare: real execution ----------
        node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
        mjs = Path(__file__).with_suffix(".mjs")
        if not Path(node).exists() and not shutil.which("node"):
            ck(False, "node is required to execute the chrome (install node or add it to PATH)")
        else:
            p = subprocess.run([node, str(mjs), str(hp)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            print((p.stdout or "").rstrip())
            if p.returncode != 0:
                print((p.stderr or "").rstrip())
            ck(p.returncode == 0, "the executed modal + compare assertions pass (see above)")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
