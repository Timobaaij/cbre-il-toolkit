#!/usr/bin/env python3
"""f32_rent_basis_test.py - a Total rent figure always says what area it was computed on. (SEAM-16)

WHAT WAS WRONG. v41 (F26) made every "Total GLA" label read the source's own stated total when
one was surfaced, which was right: a deck's printed total routinely includes a gatehouse, a plant
room or a hub office that the two summed fields do not hold. But totalAnnualRent() still
multiplies the rate by the SUMMED warehouse + office, so the modal could print a Total GLA of
45,649 a few rows above a Total annual rent computed on 42,000, and a reader dividing one by the
other got a rate no source quoted, with nothing on the page to explain the gap. Every rent in the
run that exposed it was unknown, so nothing was visibly wrong; this is contract-driven.

THE RESOLUTION, and what it is not. The rent STAYS on the summed lettable area (pricing a stated
total that includes space nobody pays warehouse rent on would overstate, and this is money). What
changed is that the figure now carries its BASIS beside it: an area x rate formula (split into two
terms when a separate office rate applies) as a .rent-basis sub-line under the annual figure in
the modal and in the compare matrix. It is a formula of numbers and units rather than a sentence,
so no i18n key was added. It prints the COMPONENTS, "(40,000 + 2,000) sq ft x rate", not their
sum: the reader can match each term to the Warehouse area and Office area rows directly above and
see which fields were priced, and the summed figure itself still appears nowhere on the page,
which is what f26_gla_single_derivation_test pins for the GLA label. An unknown office area is
simply absent from the formula, which IS the disclosure; an unknown rent still omits the row,
exactly as before. No money figure changed.

THE INVARIANT THIS PINS (the shape A1 used for the GLA twin): rentBasis() is the ONE place the
inputs are qualified, and it has exactly TWO consumers, the multiplication (totalAnnualRent) and
the printed basis (rentBasisStr), so the two cannot drift apart; and every Total rent render site
reaches the page through totalRentHTML(), the only caller of totalRentStr(), so a figure cannot be
printed without its basis by a later edit that calls the string helper directly.

Offline. Needs node to execute the chrome (as f26_gla_single_derivation_test does).
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
import build_dashboard as BD  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _canon():
    base = {"country": "GB", "developer": "Dev", "city": "Sometown", "status": "Available",
            "photo": PX, "gallery": [PX], "lat": 52.49, "lng": -0.69, "areaUnit": "sq ft",
            "rentUnit": "\u00a3/sq ft/yr", "warehouseRent": "\u00a39.50 / sq ft / year",
            "warehouseRentVal": 9.5}
    props = [
        # 40,000 + 2,000 = 42,000 summed vs 45,649 printed -> the GLA row reads the stated total,
        # the rent is computed on 42,000, and the basis line must SAY 42,000
        dict(id=1, park="Disagrees", warehouseArea=40000, officeArea="2000", officeAreaVal=2000),
        # a separate office rate -> two terms, each area at its own rate
        dict(id=2, park="Split", warehouseArea=30000, officeArea="1000", officeAreaVal=1000,
             officeRent="\u00a312.00 / sq ft / year", officeRentVal=12.0),
        # office area unknown -> the warehouse area ALONE is the basis, and the formula shows it
        dict(id=3, park="OfficeUnknown", warehouseArea=20000, officeArea="tbd"),
        # rent unknown -> no total, no basis, no row (tbd is first-class, never smoothed over)
        dict(id=4, park="RentUnknown", warehouseArea=20000, warehouseRent="tbd", warehouseRentVal=None),
    ]
    stated = {"1": {"value": 45649, "unit": "sq ft", "source_file": "t.xlsx", "locator": "S!r2"}}
    out = []
    for p in props:
        d = dict(base, **p)
        if d.get("warehouseRentVal") is None:
            d.pop("warehouseRentVal", None)
        out.append(d)
    return {"meta": {"client": "RentBasis",
                     "units": {"area": "sq ft", "rent": "\u00a3/sq ft/yr"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""},
                     "statedTotals": stated},
            "pois": [], "regions": {},
            "properties": out}


def main() -> int:
    tpl = C.load_template()

    print("== structure: ONE qualification of the inputs, TWO consumers (the money and its printed basis) ==")
    ck("function rentBasis(p){" in tpl, "rentBasis() exists")
    n_rb = tpl.count("rentBasis(p)")
    ck(n_rb == 3,
       f"rentBasis(p) occurs exactly 3 times: its definition, totalAnnualRent() and rentBasisStr() ({n_rb})")
    tar = tpl.split("function totalAnnualRent(p){", 1)[-1].split("\n}", 1)[0]
    ck("const b = rentBasis(p);" in tar, "totalAnnualRent() takes its inputs FROM rentBasis()...")
    ck("p.warehouseRentVal" not in tar and "p.officeAreaVal" not in tar and "p.officeRentVal" not in tar,
       "...and qualifies none of them itself (no second copy of the guards)")
    ck("(wa + oa) * wr" in tar and "wa * wr + oa * or" in tar,
       "the multiplication is still summed warehouse + office, split per rate when an office rate exists")
    ck("glaVal(" not in tar and "statedTotal(" not in tar,
       "money is never re-derived from the stated total (v41's rule, kept)")
    rbs = tpl.split("function rentBasisStr(p){", 1)[-1].split("\n}", 1)[0]
    ck("const b = rentBasis(p);" in rbs and "if(b.split)" in rbs
       and "term(fmt(b.wa), b.wr)" in rbs and "term(fmt(b.oa), b.or)" in rbs
       and '"(" + fmt(b.wa) + " + " + fmt(b.oa) + ")"' in rbs,
       "rentBasisStr() prints exactly the components totalAnnualRent() multiplies, on the same split test")
    ck("b.wa + b.oa" not in rbs, "the basis prints the components, never their sum (the GLA label owns no summed figure)")
    after = tpl.split("function totalAnnualRent(", 1)[-1][:600]
    ck("function rentBasis(p){" in after and "p.officeAreaVal" in after,
       "rentBasis() is declared directly after totalAnnualRent() (hoisted; two older evals read the guards there)")

    print()
    print("== structure: every Total rent render site reaches the page through totalRentHTML() ==")
    ck("function totalRentHTML(p, monthly){" in tpl, "totalRentHTML() exists")
    n_str = tpl.count("totalRentStr(p")
    ck(n_str == 2,
       f"totalRentStr(p...) occurs exactly twice: its definition and totalRentHTML()'s call ({n_str})")
    ck(re.search(r"totalRentStr\(p,\s*(false|true)\)", tpl) is None,
       "no render site calls totalRentStr() directly (a figure cannot ship without its basis)")
    annual_lines = [ln for ln in tpl.splitlines() if "row_total_annual_rent" in ln and "T(" in ln]
    ck(len(annual_lines) == 2 and all("totalRentHTML(p,false)" in ln for ln in annual_lines),
       f"the Total annual rent label is rendered on exactly two surfaces (modal, compare), both via totalRentHTML(p,false) ({len(annual_lines)})")
    monthly_lines = [ln for ln in tpl.splitlines() if "row_total_monthly_rent" in ln and "T(" in ln]
    ck(len(monthly_lines) == 2 and all("totalRentHTML(p,true)" in ln for ln in monthly_lines),
       f"the Total monthly rent label likewise, via totalRentHTML(p,true) ({len(monthly_lines)})")
    ck(tpl.count('<small class="rent-basis">') == 1 and ".rent-basis{" in tpl,
       "the .rent-basis sub-line is emitted from ONE place and has a CSS rule")
    trh = tpl.split("function totalRentHTML(p, monthly){", 1)[-1].split("\n}", 1)[0]
    ck("monthly ? null : rentBasisStr(p)" in trh,
       "the basis rides on the ANNUAL figure; the monthly figure (annual / 12 by its label) carries none")

    print()
    print("== no new i18n key: the basis is numbers and units, not authored prose ==")
    ck(re.search(r"""T\(["']rent_basis["']\)""", tpl) is None and "rent_basis" not in json.dumps(
        __import__("i18n").EN), "no rent_basis i18n key exists or is referenced")

    print()
    print("== the version bump and the hash chain the template contract requires ==")
    label = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    ck(int(re.sub(r"\D", "", label) or 0) >= 42, f"assets/VERSION is at/after v42 ({label})")
    expected = hashlib.sha256(tpl.encode("utf-8")).hexdigest()
    recorded = C.load_version().get("chrome_sha256", "")
    ck(recorded == expected,
       f"VERSION's chrome_sha256 is the live template's text hash (recorded {recorded[:12]}, computed {expected[:12]})")

    print()
    print("== a real build, executed ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps(_canon()), encoding="utf-8")
        BD.build(cp, hp)
        built = hp.read_text(encoding="utf-8")
        again, _ = BD.render(C.load_canonical(cp))
        ck(again == built, "re-rendering the same canonical is byte-identical (validate-html's floor)")
        node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
        mjs = Path(__file__).with_suffix(".mjs")
        if not Path(node).exists() and not shutil.which("node"):
            ck(False, "node is required to execute the chrome (install node or add it to PATH)")
        else:
            r = subprocess.run([node, str(mjs), str(hp)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            print((r.stdout or "").rstrip())
            if r.returncode != 0:
                print((r.stderr or "").rstrip())
            ck(r.returncode == 0, "the EXECUTED basis assertions pass (see above)")

    print()
    if FAILS:
        print(f"F32 RENT BASIS TEST: FAIL ({len(FAILS)})")
        return 1
    print("F32 RENT BASIS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
