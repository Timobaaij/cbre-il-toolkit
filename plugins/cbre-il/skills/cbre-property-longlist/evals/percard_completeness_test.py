#!/usr/bin/env python3
"""percard_completeness_test.py - PER-PROPERTY completeness over the CURATED row set.

THE RULE, in one line: for each property individually, show every CURATED variable that has a
value for THAT property, and render no row for one it lacks. If option A has 10 filled curated
variables and option B has 15, A shows 10 rows and B shows 15. Never a page of tbd.

The row set itself is FIXED and hand-authored - the modal's three sections, Compare's row list
and the Flyover's spec block. A variable no curated row owns renders nowhere, however real its
value; it still reaches the broker through the Source Ledger and the Longlist workbook. That is
the second half of what this pins, because it is the half that silently rots: a chrome that
derives rows from a property's own key set will show whatever an interpretation record happened
to invent, under a machine-made label, in an order nobody chose.

WHAT THIS PINS. The modal and compare assertions EXECUTE the real chrome in node:vm (the .mjs
sibling), so they test behaviour, not prose. The Flyover assertion is structural - `slideHtml`
lives inside the view's IIFE and is not reachable from the sandbox - so it extracts the spec
block FROM the built template and pins both halves: each curated row is guarded so it omits when
absent, and no row is derived from the property's own keys.
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
        ck("Object.keys(p)" not in body,
           "flyover: no row is derived from the property's own key set")
        ck(not any(t in body for t in ("DENY_FIELDS", "autoLabel", "LOCATOR_RE", "foCurated")),
           "flyover: none of the auto-attribute machinery is reachable from the slide")
        ck(body.count("isTbd(p.") >= 6,
           "flyover: every curated spec row is guarded, so it omits when the property lacks it")
        ck("specRow(T(" in body,
           "flyover: rows carry an i18n label, never a machine-derived one")
        ck("certStr(p)" in body,
           "flyover: the curated Certification row is present")

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
