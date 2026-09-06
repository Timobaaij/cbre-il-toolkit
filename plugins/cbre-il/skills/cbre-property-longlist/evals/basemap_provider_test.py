#!/usr/bin/env python3
"""basemap_provider_test.py - the streets basemap is served by a KEYLESS provider, at all three
map sites, with the three details that make keyless tiles actually render.

THE DEFECT. The chrome's three streets layers (the main map, the modal mini-map and the Flyover)
all pointed at a third-party tile host that now bakes an "API KEY REQUIRED" watermark INTO the
imagery it serves on its keyless endpoint. That text therefore reached the reader inside real map
tiles on every dashboard this template builds, and nothing detected it: the requests still
succeed, so there is no console error, no failed fetch and no blank tile to notice. Only a human
looking at the picture would see it, and by then the file is with the client.

WHAT THIS PINS, and why each clause is here rather than left to a reviewer's eye:
  * ZERO references to the old provider, in the template AND in a real built dashboard - the
    built file is the one that ships, and a template-only check would miss a builder that
    re-introduced a URL.
  * exactly THREE streets layers on the new host, so a fourth map added later cannot quietly
    ship on a different provider than the other three.
  * `subdomains` STATED on all three, with THREE hosts. Standard tiles come from a/b/c; the old
    definitions used four (one request in four would 404) and the Flyover's carried no
    `subdomains` key at all, which is exactly how the three drifted apart in the first place.
  * NO `{r}` retina placeholder. The standard tile server serves no @2x variant, so a retained
    {r} would 404 every tile on a high-DPI screen - the same class of silent breakage, louder.
  * the attribution names the new provider and no longer credits the old one (a false credit is
    a claim about who served the imagery).
  * the SATELLITE layer beside each of the three is untouched - the change was scoped to the
    streets basemap, and this is the assertion that keeps it scoped.

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

# the provider that bakes the watermark - named ONLY here, as the thing that must not appear
OLD_HOST = "basemaps." + "cartocdn.com"
OLD_CREDIT = "CART" + "O"
NEW_HOST = "tile.openstreetmap.org"

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def tile_layers(text: str) -> list[tuple[str, str]]:
    """(url, options-body) for every L.tileLayer(...) call in the chrome.

    Extracted FROM the file rather than restated, so a revert to the old host, a dropped
    `subdomains` key or a re-added {r} fails here instead of shipping.
    """
    return [(m.group("url"), m.group("opts")) for m in
            re.finditer(r'L\.tileLayer\(\s*(?P<q>["\'])(?P<url>[^"\']+)(?P=q)\s*,\s*'
                        r'\{(?P<opts>[^}]*)\}', text)]


def main() -> int:
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")

    print("== the old provider is gone from the template ==")
    ck(tpl.count(OLD_HOST) == 0,
       f"no reference to the watermarking tile host remains ({tpl.count(OLD_HOST)} found)")
    ck(tpl.count(OLD_CREDIT) == 0,
       f"no attribution still credits it ({tpl.count(OLD_CREDIT)} found)")

    layers = tile_layers(tpl)
    streets = [(u, o) for u, o in layers if NEW_HOST in u]
    print()
    print("== the three streets layers ==")
    ck(len(streets) == 3,
       f"exactly three streets layers are on the keyless host (found {len(streets)})")
    for i, (url, opts) in enumerate(streets, 1):
        ck("{r}" not in url,
           f"layer {i}: the @2x retina placeholder is dropped from {url!r}")
        sub = re.search(r"""subdomains\s*:\s*["']([a-z]+)["']""", opts)
        ck(bool(sub), f"layer {i}: subdomains is stated explicitly, not left to a default")
        ck(bool(sub) and sub.group(1) == "abc",
           f"layer {i}: three subdomains a/b/c (got {sub.group(1) if sub else None!r})")
        ck("OpenStreetMap" in opts, f"layer {i}: the attribution names the new provider")
        ck(OLD_CREDIT not in opts, f"layer {i}: the attribution no longer credits the old one")
        ck("maxZoom" in opts, f"layer {i}: maxZoom is still stated")

    print()
    print("== the satellite layer beside each of the three is untouched ==")
    # counted over the whole template, not over `layers`: the Flyover builds its Esri URLs by
    # concatenating a `var ESRI` base, so the literal never appears inside the tileLayer call.
    ck(tpl.count("arcgisonline.com") == 3,
       f"the three Esri host references are all still present ({tpl.count('arcgisonline.com')})")
    ck(tpl.count("World_Imagery/MapServer") == 3,
       f"three World_Imagery layers, exactly as before ({tpl.count('World_Imagery/MapServer')})")
    ck(tpl.count('attribution: \'Tiles &copy; Esri, Maxar, Earthstar Geographics') == 1,
       "the main map's Esri attribution is byte-identical to v39")

    print()
    print("== a BUILT dashboard carries the same guarantee ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps({
            "meta": {"client": "Basemap", "units": {"area": "sq m"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "pois": [], "regions": {},
            "properties": [{"id": 1, "country": "CZ", "park": "P", "developer": "D",
                            "city": "Bor", "status": "Available", "photo": PX,
                            "gallery": [PX], "lat": 49.75, "lng": 12.77,
                            "areaUnit": "sq m", "warehouseArea": 10000}],
        }), encoding="utf-8")
        build_dashboard.build(cp, hp)
        built = hp.read_text(encoding="utf-8")
    ck(built.count(OLD_HOST) == 0, "the built dashboard references the old tile host ZERO times")
    ck(built.count(OLD_CREDIT) == 0, "the built dashboard credits the old provider ZERO times")
    ck(built.count(NEW_HOST) == 3,
       f"the built dashboard carries three new tile layers (found {built.count(NEW_HOST)})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
