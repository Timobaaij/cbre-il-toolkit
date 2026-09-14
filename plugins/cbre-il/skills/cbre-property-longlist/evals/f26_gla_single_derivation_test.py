#!/usr/bin/env python3
"""f26_gla_single_derivation_test.py - one "Total GLA" label, ONE derivation, on every surface. (F26)

WHAT WAS WRONG. The card printed the source's own stated total (preBaked.statedTotal) as a
qualifier, while the detail modal and the compare matrix computed warehouse + office under the
SAME "Total GLA" label. Wherever a deck's total includes space the two summed fields do not hold
(a gatehouse, a hub office, a plant room) the two disagreed: on a live run, four of nine
properties, by 16,845 / 10,692 / 5,000 / 4,269 sq ft. A blind reviewer confirmed against the
bound site plans' schedules of accommodation that the CARD figure (the stated total) is right.

THE FIX, and what it is not. glaVal() adopts the stated total when the builder surfaced one and
falls back to warehouse + office otherwise; glaUnit() carries the matching unit; the card, the
modal row and the compare cell all read those two. NO DATA CHANGED: an earlier attempt to make
the numbers agree by inflating an office area was refused because it would misstate a printed
figure, and totalAnnualRent() still multiplies the summed areas (a rate applied to a total the
source did not price would print a rent no source stated).

Offline. Needs node to execute the chrome (as statedtotal_card_test does).
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
        # 40,000 + 2,000 = 42,000 summed vs 45,649 printed -> the stated total is surfaced
        dict(id=1, park="Disagrees", warehouseArea=40000, officeArea="2000", officeAreaVal=2000),
        # 30,000 summed vs 30,010 printed -> inside the gate's tolerance, nothing surfaced
        dict(id=2, park="Agrees", warehouseArea=30000),
        # no stated total at all
        dict(id=3, park="Unstated", warehouseArea=20000),
    ]
    stated = {"1": {"value": 45649, "unit": "sq ft", "source_file": "t.xlsx", "locator": "S!r2"},
              "2": {"value": 30010, "unit": "sq ft", "source_file": "t.xlsx", "locator": "S!r3"}}
    return {"meta": {"client": "SingleDerivation",
                     "units": {"area": "sq ft", "rent": "\u00a3/sq ft/yr"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""},
                     "statedTotals": stated},
            "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def main() -> int:
    tpl = C.load_template()

    print("== structure: one reader of the stated total, and three surfaces reading glaVal/glaUnit ==")
    ck(tpl.count("p.preBaked.statedTotal") == 1,
       f"exactly ONE expression in the chrome reads p.preBaked.statedTotal ({tpl.count('p.preBaked.statedTotal')})")
    ck("function statedTotal(p){" in tpl and "function glaUnit(p){" in tpl,
       "statedTotal() and glaUnit() exist")
    gv = tpl.split("function glaVal(p){", 1)[-1][:400]
    ck("const st = statedTotal(p);" in gv and "if(st) return st.value;" in gv,
       "glaVal() adopts the stated total first...")
    ck("p.officeAreaVal" in gv and "return w + o;" in gv,
       "...and falls back to warehouse + office (the arithmetic gate's derivation)")
    # v45: the null branch prints BLANK, the chrome's one absence token, where it used to
    # print a long dash of its own. The derivation and the unit are byte-identical to v41.
    ck("function glaStr(p){ const g = glaVal(p); return g == null ? BLANK : fmt(g) + \" \" + glaUnit(p); }" in tpl,
       "glaStr() prints glaVal() in glaUnit(), and BLANK when there is neither")
    sth = tpl.split("function statedTotalHTML(p){", 1)[-1][:300]
    ck("${fmt(glaVal(p))} ${glaUnit(p)}" in sth,
       "the CARD qualifier prints glaVal()/glaUnit(): the same call as the modal row")
    ck("row(T('row_total_gla'), glaStr(p))," in tpl, "the MODAL row prints glaStr()")
    ck("[T('row_total_gla'), p=>glaStr(p), 'warehouseArea']," in tpl, "the COMPARE cell prints glaStr()")
    n_label = len(re.findall(r"""T\(["']row_total_gla["']\)""", tpl))
    ck(n_label == 3,
       f"the label is RENDERED on exactly three surfaces (card qualifier, modal, compare); found {n_label}")
    tar = tpl.split("function totalAnnualRent(p){", 1)[-1][:700]
    ck("glaVal(" not in tar and "(wa + oa) * wr" in tar,
       "totalAnnualRent() does NOT read glaVal(): money is never re-derived from a stated total")

    print()
    print("== the builder's attach still compares against the FALLBACK derivation ==")
    props = [C.fill_render_sentinels(dict(p)) for p in _canon()["properties"]]
    BD._attach_stated_totals(props, _canon()["meta"])
    got = {p["id"]: (p.get("preBaked") or {}).get("statedTotal") for p in props}
    ck(got[1] == {"value": 45649, "unit": "sq ft"}, f"the disagreeing property carries the stated total {got[1]}")
    ck(got[2] is None and got[3] is None, "inside-tolerance and unstated carry nothing")

    print()
    print("== the version bump and the hash chain the template contract requires ==")
    label = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    ck(int(re.sub(r"\D", "", label) or 0) >= 41, f"assets/VERSION is at/after v41 ({label})")
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
            ck(r.returncode == 0, "the EXECUTED cross-surface assertions pass (see above)")

    print()
    if FAILS:
        print(f"F26 GLA SINGLE DERIVATION TEST: FAIL ({len(FAILS)})")
        return 1
    print("F26 GLA SINGLE DERIVATION TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
