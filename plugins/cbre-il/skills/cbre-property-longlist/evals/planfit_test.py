#!/usr/bin/env python3
"""planfit_test.py - a SITE PLAN is shown whole; the photo hero is still cropped to fill.

THE DEFECT. The modal's plan view reuses the hero <img> inside `.modal-hero`, a fixed 16/7
frame whose rule sets `object-fit:cover`. That is right for a photograph - a hero should fill
its frame - and destructive for a site plan, because a plan is the ONE image whose EDGES carry
the information: yard depths, the plot boundary, dimension lines, the access road. A cover fit
crops away exactly those. Until now only the lightbox ever showed the plan whole, which means
the reader had to know to click it.

WHAT THIS PINS:
  * the PHOTO hero still uses `object-fit:cover`, unchanged. This is half the point: the fix
    must not quietly letterbox every photograph as well.
  * the plan mode uses `object-fit:contain` with a neutral letterbox ground, so a white plan
    sheet still reads as a sheet instead of bleeding into the page.
  * the class is toggled at the ONE existing swap point - `bindImageToggle`'s `show()`, the
    function that already assigns `img.src` for both modes - so the two can never disagree
    about which mode is displayed.
  * it is a TOGGLE, not an add. The same element carries both modes as the reader switches back
    and forth, so an add-only call would leave the photo letterboxed after one visit to the plan.
  * the frame itself is unchanged (still a fixed aspect ratio), because the fix is the FIT, not
    the geometry.

Structural by necessity: the toggle lives on a DOM element inside an event handler, so there is
no function to execute in a sandbox. The rules are extracted FROM the built template rather than
restated, so a revert to a cover fit or to an add-only call fails here.

Offline. Drives a real build.
"""
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

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps({
            "meta": {"client": "PlanFit", "units": {"area": "sq m"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "pois": [], "regions": {},
            "properties": [{"id": 1, "country": "CZ", "park": "Plan Park", "developer": "D",
                            "city": "Bor", "status": "Available", "photo": PX,
                            "gallery": [PX], "plan": PX, "lat": 49.75, "lng": 12.77,
                            "areaUnit": "sq m", "warehouseArea": 10000}],
        }), encoding="utf-8")
        build_dashboard.build(cp, hp)
        built = hp.read_text(encoding="utf-8")

    print("== the PHOTO hero is untouched ==")
    ck(".modal-hero img{width:100%;height:100%;object-fit:cover}" in built,
       "the hero image rule still crops a photograph to fill its frame (object-fit:cover)")
    ck(re.search(r"\.modal-hero\{[^}]*aspect-ratio:16/7", built) is not None,
       "the frame is still a fixed 16/7 - the fix is the FIT, not the geometry")

    print()
    print("== the PLAN mode is contained, on a neutral letterbox ==")
    ck(".modal-hero.plan-mode img{object-fit:contain}" in built,
       "the plan view uses object-fit:contain, so no edge is cropped away")
    m = re.search(r"\.modal-hero\.plan-mode\{([^}]*)\}", built)
    ck(bool(m), "the plan mode sets its own letterbox ground")
    ck(bool(m) and "background:" in m.group(1),
       f"...an explicit background {m.group(1) if m else None!r}")

    print()
    print("== toggled at the ONE existing swap point ==")
    swap = re.search(r"function bindImageToggle\(p\)\{(.*?)\n\}", built, re.S)
    ck(bool(swap), "the built chrome still defines bindImageToggle()")
    body = swap.group(1) if swap else ""
    show = re.search(r"function show\(\)\{(.*?)\n  \}", body, re.S)
    ck(bool(show), "...and its show() - the function that already assigns img.src per mode")
    sbody = show.group(1) if show else ""
    ck("classList.toggle('plan-mode'" in sbody,
       "the class is set inside show(), beside the img.src assignment it must agree with")
    ck("mode === 'plan'" in sbody, "...driven by the SAME mode variable that picks the image")
    ck("classList.add('plan-mode'" not in built,
       "it is a TOGGLE, never an add - switching back to the photo must restore the cover fit")
    ck("closest('.modal-hero')" in body,
       "the frame is resolved from the image, so the markup owns the relationship")

    print()
    print("== the toggle button that reaches it is still gated on a real plan ==")
    ck("""${p.plan ? `<div class="image-toggle">""" in built,
       "the Photo/Plan switch renders only when the property HAS a plan (v7)")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
