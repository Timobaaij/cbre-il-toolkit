#!/usr/bin/env python3
"""statedtotal_card_test.py - the SOURCE'S OWN printed total area reaches the card, and it
reaches it on exactly the arithmetic gate's terms.

THE DEFECT. `merge` has always lifted each source's own printed total area into
`canonical.meta.statedTotals` (keyed by property id), and the arithmetic gate was its ONLY
consumer: the figure reached neither the builder nor the template. Meanwhile the card's area
figure is DERIVED - the chrome sums components (`glaVal` = warehouseArea + officeAreaVal) - and
a derivation reads BELOW the source's own printed total whenever real space sits inside that
total and in no summed field: mezzanine, ancillary, plant. The client therefore saw a smaller
building than the brochure states, with nothing on the page to say so.

WHAT THIS PINS, in order of what would rot first:
  * ONE TOLERANCE. The card and the gate must share the EXPRESSION, not merely the intent, or a
    card can flag a difference the gate calls noise - or, far worse, stay silent about one the
    gate blocks on. The expression is extracted from BOTH source files and compared, so editing
    either alone fails here. A quotation is only honest if something checks it.
  * IT IS NOT A TOP-LEVEL PROPERTY FIELD. `extract_xlsx` records why (a top-level scalar is
    client-facing record surface and would print raw), so the figure rides on the
    pipeline-assigned `preBaked` container. Pinned from three directions: absent from the
    schema's property properties, absent from `canonical_property_fields()`, and absent from
    every reader's field list.
  * SHOWN ONLY ON DISAGREEMENT. Agreement inside the tolerance renders nothing at all, so a
    card that carries the line is a card where the difference is real.
  * THE CANONICAL IS NOT MUTATED. render() works on shallow copies, so `preBaked` must be
    rebuilt rather than written through - otherwise the second render (validate-html's
    byte-identity re-run) would be operating on a different object than the first.

Offline. Drives a real build; needs node for the executed half.
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
import _common as C  # noqa: E402
import build_dashboard as BD  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

# the tolerance expression, as a literal, so BOTH files are compared against the SAME needle
TOL_EXPR = "max(50.0, 0.005 * total)"

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _canon(props, stated):
    base = {"country": "GB", "developer": "Dev", "city": "Corby", "status": "Available",
            "photo": PX, "gallery": [PX], "lat": 52.49, "lng": -0.69, "areaUnit": "sq ft",
            "rentUnit": "\u00a3/sq ft/yr", "warehouseRent": "\u00a39.50 / sq ft / year",
            "warehouseRentVal": 9.5}
    return {"meta": {"client": "StatedTotal",
                     "units": {"area": "sq ft", "rent": "\u00a3/sq ft/yr"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""},
                     "statedTotals": stated},
            "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def main() -> int:
    print("== ONE tolerance, shared with the arithmetic gate ==")
    gate_src = (HELPERS / "gate_runner.py").read_text(encoding="utf-8")
    bd_src = (HELPERS / "build_dashboard.py").read_text(encoding="utf-8")
    ck(f"tol = {TOL_EXPR}" in gate_src,
       f"gate_runner.py still computes its tolerance as `{TOL_EXPR}`")
    ck(f"return {TOL_EXPR}" in bd_src,
       f"build_dashboard.stated_total_tolerance() returns the SAME expression `{TOL_EXPR}`")
    # one EXECUTABLE copy: the expression also appears in stated_total_tolerance()'s docstring,
    # where it is quoted on purpose, so the invariant to pin is that the attach never states a
    # threshold of its OWN and always goes through the one function.
    _attach = bd_src.split("def _attach_stated_totals", 1)[-1].split(chr(10) + "def ", 1)[0]
    ck("stated_total_tolerance(total)" in _attach,
       "_attach_stated_totals() goes THROUGH that one function")
    ck("max(50" not in _attach,
       "...and states no threshold of its own - one expression, in one place")
    # and it behaves that way, not merely reads that way
    for total, expect in ((1000.0, 50.0), (10000.0, 50.0), (20000.0, 100.0), (45649.0, 228.245)):
        got = BD.stated_total_tolerance(total)
        ck(abs(got - expect) < 1e-9,
           f"stated_total_tolerance({total:,.0f}) == {expect} (got {got})")

    print()
    print("== it is NOT a top-level property field ==")
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    pprops = schema["$defs"]["property"]["properties"]
    ck("statedTotal" not in pprops,
       "the schema declares no top-level `statedTotal` (extract_xlsx records why)")
    ck("statedTotalArea" not in pprops, "nor the extractor's own `statedTotalArea` name")
    ck("statedTotal" in (pprops["preBaked"].get("properties") or {}),
       "it is documented as a `preBaked` sub-key - the pipeline-assigned render container")
    C._CANON_PROPERTY_FIELDS = None
    ck("statedTotal" not in C.canonical_property_fields(),
       "`statedTotal` is NOT a canonical property field name")
    ck("preBaked" in C.canonical_property_fields(),
       "...while its container is, so the render-boundary object gate passes")
    import run as R  # noqa: E402  (heavy; imported late)
    ck("statedTotal" not in R._reader_field_list(),
       "no reader is ever asked to fill it (preBaked is pipeline-assigned)")

    print()
    print("== the builder attaches it only where the two figures DISAGREE ==")
    # derived GLA = warehouseArea + officeAreaVal, exactly glaVal()
    props = [
        # 40,000 + 2,000 = 42,000 derived vs 45,649 printed -> 3,649 out, tolerance 228 -> SHOW
        dict(id=1, park="Disagrees", warehouseArea=40000, officeArea="2000",
             officeAreaVal=2000),
        # 30,000 derived vs 30,010 printed -> 10 out, tolerance 150 -> hide
        dict(id=2, park="Agrees", warehouseArea=30000),
        # no stated total at all -> nothing to surface
        dict(id=3, park="Unstated", warehouseArea=20000),
        # a stated total with NO numeric contributor -> glaVal() returns null, so no comparison
        dict(id=4, park="NoArea"),
    ]
    stated = {"1": {"value": 45649, "unit": "sq ft", "source_file": "t.xlsx", "locator": "S!r2"},
              "2": {"value": 30010, "unit": "sq ft", "source_file": "t.xlsx", "locator": "S!r3"},
              "4": {"value": 12345, "unit": "sq ft", "source_file": "t.xlsx", "locator": "S!r5"}}
    canon = _canon(props, stated)
    rendered = [C.fill_render_sentinels(dict(p)) for p in canon["properties"]]
    BD._attach_stated_totals(rendered, canon["meta"])
    got = {p["id"]: (p.get("preBaked") or {}).get("statedTotal") for p in rendered}
    ck(got[1] == {"value": 45649, "unit": "sq ft"},
       f"the disagreeing property carries the printed total {got[1]}")
    ck(got[2] is None, "the agreeing property carries nothing (inside the tolerance)")
    ck(got[3] is None, "a property with no stated total carries nothing")
    ck(got[4] is None, "a stated total with no derivable GLA is skipped, exactly as the gate does")

    print()
    print("== the canonical object itself is untouched ==")
    ck(all("preBaked" not in p for p in canon["properties"]),
       "no property in the canonical grew a preBaked key (the copy is rebuilt, not written through)")
    # an existing preBaked must survive rather than be replaced
    p5 = C.fill_render_sentinels({"id": 5, "warehouseArea": 40000,
                                 "preBaked": {"distances": {"Port": 1}}})
    BD._attach_stated_totals([p5], {"statedTotals": {"5": {"value": 45649, "unit": "sq ft"}}})
    ck(p5["preBaked"].get("distances") == {"Port": 1},
       "an existing preBaked.distances survives the attach")
    ck(p5["preBaked"].get("statedTotal", {}).get("value") == 45649,
       "...alongside the new statedTotal")

    print()
    print("== a real build, and the card ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps(canon), encoding="utf-8")
        BD.build(cp, hp)
        built = hp.read_text(encoding="utf-8")
        ck(built.count('"statedTotal"') == 1,
           f"exactly one property in PROPS carries a statedTotal ({built.count(chr(34) + 'statedTotal' + chr(34))})")
        ck("function statedTotalHTML(p)" in built,
           "the built chrome defines statedTotalHTML()")
        ck('T("row_total_gla")' in built.split("function statedTotalHTML(p)", 1)[1][:400],
           "it labels the figure with the EXISTING row_total_gla key - no new i18n prose")
        ck(re.search(r'class="spec-v">\$\{areaStr\(p\.warehouseArea\)\}\$\{statedTotalHTML\(p\)\}',
                     built) is not None,
           "the card renders it beside the derived warehouse figure, in the same spec tile")
        ck(".spec-total{" in built, "the sub-line has its own CSS rule (shaped as .rent-mo)")

        # byte-stability: render() must be a pure function of the canonical
        again, _ = BD.render(C.load_canonical(cp))
        ck(again == built,
           "re-rendering the same canonical is byte-identical (validate-html's floor)")

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
            ck(r.returncode == 0, "the EXECUTED card assertions pass (see above)")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
