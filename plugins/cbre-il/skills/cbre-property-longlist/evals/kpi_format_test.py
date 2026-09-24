#!/usr/bin/env python3
"""kpi_format_test.py - v46 template polish: the hero warehouse-area KPI and two layout fixes.

  1. build_dashboard._fmt_thousands_k picks the suffix PER END. It used to divide by 1000 and put
     one 'k' after the range, so a 1,000,000 building shipped as "25 - 1000k" and wrapped the
     tile. All-k ranges keep today's exact format ("33.6 - 76k").
  2. .kpi-value is nowrap, so a range reads as one figure.
  3. .field-label wraps instead of ellipsising ("Min Warehouse Area" was cut short at 1440px).
  4. On a card, .cm-count no longer sits on the Compare tick-box (bottom-right); the modal hero
     keeps it bottom-right because its bottom-left holds .image-toggle.

Offline, no deps.  Usage: python evals/kpi_format_test.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C  # noqa: E402
import build_dashboard as BD  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _rule(css: str, selector: str) -> str:
    """Every declaration block whose selector list is exactly `selector`, joined."""
    return " ".join(m.group(1) for m in re.finditer(
        r"(?:^|[}\n])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css))


_JS = r"""
import fs from 'node:fs'; import vm from 'node:vm';
const html = fs.readFileSync(process.argv[2], 'utf8');
const code = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]).join('\n;\n')
  + '\n;\n__capture__({ PROPS, POIS, groupedDistances });\n';
const sink = new Proxy(function () {}, { get: (_t, p) => (p === Symbol.toPrimitive || p === 'toString' || p === 'valueOf') ? () => '' : sink,
  apply: () => sink, construct: () => sink, has: () => true });
const target = { console }; let got = null;
for (const n of Object.getOwnPropertyNames(globalThis)) { if (!(n in target)) { try { target[n] = globalThis[n]; } catch {} } }
target.globalThis = target; target.__capture__ = o => { got = o; };
vm.runInContext(code, vm.createContext(new Proxy(target, { get: (t, p) => (p in t ? t[p] : sink), has: () => true })));
const g = got.groupedDistances(got.PROPS[0]).city;
console.log(JSON.stringify({ names: g.map(x => x.name), km: g.map(x => x.km),
  manchesters: got.POIS.filter(x => x.name === 'Manchester').length,
  leftover: got.POIS.filter(x => x.type === 'city_major').length }));
"""


def _major_city_check() -> None:
    import json
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
    if not Path(node).exists() and not shutil.which("node"):
        ck(False, "node is required to execute the chrome")
        return
    px = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
          "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    city = lambda n, la, lo, t="city": {"name": n, "type": t, "lat": la, "lng": lo, "country": "GB"}
    # Leigh: five 100k+ cities sit nearer than Manchester, which enrich attaches as city_major
    # (and which is ALSO listed as another property's plain nearest city - the same point twice)
    pois = [city("Wigan", 53.545, -2.632), city("Bolton", 53.578, -2.429),
            city("Warrington", 53.390, -2.597), city("St Helens", 53.453, -2.737),
            city("Salford", 53.483, -2.293), city("Manchester", 53.480, -2.242),
            city("Manchester", 53.480, -2.242, "city_major")]
    canon = {"meta": {"client": "Leigh", "units": {"area": "sq ft"},
                      "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "", "lede": "",
                               "footer_copyright": ""}},
             "pois": pois, "regions": {},
             "properties": [{"id": 1, "park": "Leigh", "country": "GB", "city": "Leigh",
                             "developer": "Dev", "status": "Available", "photo": px,
                             "gallery": [px], "lat": 53.50, "lng": -2.52, "areaUnit": "sq ft",
                             "warehouseArea": 100000}]}
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "c.json").write_text(json.dumps(canon), encoding="utf-8")
        BD.build(d / "c.json", d / "b.html")
        (d / "t.mjs").write_text(_JS, encoding="utf-8")
        r = subprocess.run([node, str(d / "t.mjs"), str(d / "b.html")], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        ck(False, f"the chrome executed ({(r.stderr or '').strip()[:200]})")
        return
    res = json.loads(r.stdout.strip().splitlines()[-1])
    ck("Manchester" in res["names"] and len(res["names"]) == 4,
       f"Major cities keeps 4 rows and includes Manchester ({res['names']})")
    ck(res["km"] == sorted(res["km"]), "the group stays in distance order")
    ck(res["manchesters"] == 1, "a city_major copy of a listed city is merged, not drawn twice")
    ck(res["leftover"] == 0, "no POI is left with the unknown type city_major")


def main() -> int:
    f = BD._fmt_thousands_k
    print("== the warehouse-area KPI range ==")
    cases = [
        ((33600, 76000), "33.6 - 76k"),        # today's format, unchanged
        ((20000, 50000), "20 - 50k"),
        ((25000, 1_000_000), "25k - 1.0m"),     # was "25 - 1000k"
        ((1_200_000, 2_500_000), "1.2 - 2.5m"),
        ((999_960, 1_500_000), "1.0 - 1.5m"),   # 999,960 would print as "1000k" -> millions
        ((500, 999_000), "0.5 - 999k"),
    ]
    for (lo, hi), want in cases:
        got = f(lo, hi)
        ck(got == want, f"_fmt_thousands_k({lo}, {hi}) == {want!r} (got {got!r})")
    ck(all("1000k" not in f(lo, hi) for (lo, hi), _ in cases), "no range ever prints 1000k")

    print()
    print("== the template CSS ==")
    tpl = C.load_template()
    css = tpl.split("<style", 1)[-1]
    kv = _rule(css, ".kpi-value")
    ck("white-space:nowrap" in kv.replace(" ", ""), ".kpi-value is white-space:nowrap")
    fl = _rule(css, ".field-label").replace(" ", "")
    ck("white-space:nowrap" not in fl and "text-overflow:ellipsis" not in fl,
       ".field-label no longer truncates with nowrap + ellipsis")
    ck("white-space:normal" in fl, ".field-label wraps (white-space:normal)")
    tb = _rule(css, ".toolbar").replace(" ", "")
    ck("align-items:end" in tb, "the toolbar keeps align-items:end, so a two-line label keeps the controls aligned")
    ct = _rule(css, ".compare-toggle").replace(" ", "")
    ck("bottom:14px" in ct and "right:14px" in ct, "the Compare tick-box is still bottom-right on the card")
    cc = _rule(css, ".card .cm-count").replace(" ", "")
    ck("right:auto" in cc and "left:" in cc,
       "on a CARD the photo counter moves to the left, off the Compare tick-box")
    base = _rule(css, ".cm-count").replace(" ", "")
    ck("right:8px" in base, "the base .cm-count (the modal hero) stays bottom-right, clear of .image-toggle")
    it = _rule(css, ".image-toggle").replace(" ", "")
    ck("left:16px" in it, ".image-toggle still owns the modal hero's bottom-left corner")

    print()
    print("== 15e: the property's own nearest major city is never crowded out ==")
    ck("city_major" in BD.DISPLAY_POI_TYPES, "the builder keeps a city_major POI at the render boundary")
    _major_city_check()

    print()
    if FAILS:
        print(f"KPI FORMAT TEST: FAIL ({len(FAILS)})")
        return 1
    print("KPI FORMAT TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
