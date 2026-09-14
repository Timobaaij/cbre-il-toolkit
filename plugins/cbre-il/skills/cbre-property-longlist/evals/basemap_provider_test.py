#!/usr/bin/env python3
"""basemap_provider_test.py - the streets basemap is served by a KEYLESS provider that ALLOWS
this use, at all three map sites, with the details that make keyless tiles actually render.

THE DEFECT, twice over. v40's version of this file pinned the three streets layers to the
OpenStreetMap standard tiles, to escape a provider that had begun baking an "API KEY REQUIRED"
watermark into the imagery it served keylessly. OSM then failed in the same shape, worse. Their
tile usage policy requires a request the Foundation can attribute to a named application, and a
dashboard this template builds cannot supply one: it is opened from a `file://` path, so there
is no usable Referer, and a page cannot set its own User-Agent. The server answers with a 403
whose BODY is an HTML "Access blocked - App is not following the tile usage policy" page, and
Leaflet paints it into the tile grid as a readable wall of text accusing the app of breaking the
rules, in front of the client. Both failures RETURNED SUCCESS at the layer anything automated
can see: no console error, no failed fetch, no blank tile.

So this eval does not test "the tiles look right" - nothing here can. It tests every property
of the three definitions that CAN silently rot, and it extracts them from the file rather than
restating them, so a revert fails here instead of shipping.

WHAT THIS PINS, and why each clause is here rather than left to a reviewer's eye:
  * ZERO tile URLs on either abandoned host, in the template AND in a real built dashboard -
    the built file is the one that ships, so a template-only check would miss a builder that
    re-introduced a URL. The prose may still NAME OpenStreetMap (the v44 comment explains why
    the tiles left), so the assertion is scoped to what `L.tileLayer` is actually asked to load.
  * exactly THREE streets layers on the new host, so a fourth map added later cannot quietly
    ship on a different provider than the other three.
  * the `{z}/{y}/{x}` path order. Esri's REST endpoint takes ROW before COLUMN; the OSM-style
    `{z}/{x}/{y}` it replaces is transposed, and transposing serves tiles of the WRONG PLACE
    rather than an error - the quietest failure in this whole file.
  * NO `subdomains` key and NO `{s}` placeholder. Esri serves from a single host, so the pair
    v40 needed would now request a subdomain that does not resolve.
  * NO `{r}` retina placeholder (no @2x variant is served; a retained {r} 404s every tile on a
    high-DPI screen).
  * ONE byte-identical attribution across the three, crediting Esri alone. Crediting a host
    that no longer serves the imagery is a false claim, and three drifting variants of a credit
    is how the v40 definitions came apart.
  * the SATELLITE layer beside each of the three is untouched, with its v39 attribution intact -
    the change was scoped to the streets basemap, and this is what keeps it scoped.

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

# the two abandoned providers - named ONLY here, as the things that must not be LOADED.
# split so that this file's own mention of them cannot satisfy a naive grep of the repo.
DEAD_HOSTS = ("basemaps." + "cartocdn.com", "tile." + "openstreetmap.org")
DEAD_CREDITS = ("CART" + "O", "OpenStreet" + "Map</a>")

NEW_HOST = "server.arcgisonline.com"
STREETS_PATH = "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
ATTR = "Tiles &copy; Esri. Sources: Esri, HERE, Garmin, USGS, NGA"
SAT_ATTR_V39 = "attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics"

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def tile_layers(text: str) -> list[tuple[str, str]]:
    """(url, options-body) for every L.tileLayer(...) call in the chrome.

    Extracted FROM the file rather than restated, so a revert to a dead host, a transposed
    {z}/{x}/{y}, a re-added `subdomains` or a drifted credit fails here instead of shipping.
    Only calls whose first argument is a STRING LITERAL are visible to this regex, which is
    why v44 writes the Flyover's streets URL out in full rather than as `ESRI + path` like
    the hybrid layers beside it.
    """
    return [(m.group("url"), m.group("opts")) for m in
            re.finditer(r'L\.tileLayer\(\s*(?P<q>["\'])(?P<url>[^"\']+)(?P=q)\s*,\s*'
                        r'\{(?P<opts>[^}]*)\}', text)]


def assert_no_dead_tiles(layers, label):
    """No tile URL points at a provider that has blocked or watermarked us."""
    for host in DEAD_HOSTS:
        bad = [u for u, _ in layers if host in u]
        ck(not bad, f"{label}: no tile URL loads from the abandoned host {host!r} ({len(bad)})")
    for u, o in layers:
        for credit in DEAD_CREDITS:
            ck(credit not in o,
               f"{label}: no attribution still credits {credit!r} ({u[:48]}...)")


def main() -> int:
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")
    layers = tile_layers(tpl)

    print("== neither abandoned provider is LOADED by the template ==")
    assert_no_dead_tiles(layers, "template")

    streets = [(u, o) for u, o in layers if STREETS_PATH in u]
    print()
    print("== the three streets layers ==")
    ck(len(streets) == 3,
       f"exactly three streets layers on the keyless Esri service (found {len(streets)})")
    attrs = []
    for i, (url, opts) in enumerate(streets, 1):
        ck(url.startswith("https://" + NEW_HOST + "/"),
           f"layer {i}: served over https from {NEW_HOST} ({url[:40]}...)")
        ck(url.endswith("/tile/{z}/{y}/{x}"),
           f"layer {i}: Esri's ROW-before-COLUMN path order, not the transposed "
           f"{{z}}/{{x}}/{{y}} ({url[-18:]!r})")
        ck("{s}" not in url, f"layer {i}: the {{s}} subdomain placeholder is dropped")
        ck("{r}" not in url, f"layer {i}: the @2x retina placeholder is dropped")
        ck(not re.search(r"subdomains\s*:", opts),
           f"layer {i}: no subdomains key - Esri serves from one host")
        ck(ATTR in opts, f"layer {i}: the attribution is the agreed Esri string")
        ck("maxZoom" in opts, f"layer {i}: maxZoom is still stated")
        m = re.search(r"""attribution\s*:\s*(["'])(.*?)\1""", opts)
        attrs.append(m.group(2) if m else None)
    ck(len(set(attrs)) == 1 and attrs[0] == ATTR,
       f"one BYTE-IDENTICAL credit across all three, not three variants ({set(attrs)})")
    ck(tpl.count(ATTR) == 3,
       f"the credit appears exactly three times in the template ({tpl.count(ATTR)})")

    print()
    print("== the satellite layer beside each of the three is untouched ==")
    # counted over the whole template, not over `layers`: the Flyover builds its World_Imagery
    # URLs by concatenating a `var ESRI` base, so the literal never appears inside the call.
    ck(tpl.count("World_Imagery/MapServer") == 3,
       f"three World_Imagery layers, exactly as before ({tpl.count('World_Imagery/MapServer')})")
    ck(tpl.count(SAT_ATTR_V39) == 1,
       "the main map's satellite attribution is byte-identical to v39")

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
    assert_no_dead_tiles(tile_layers(built), "built dashboard")
    ck(built.count(STREETS_PATH) == 3,
       f"the built dashboard carries three Esri streets layers ({built.count(STREETS_PATH)})")
    ck(built.count(ATTR) == 3,
       f"and the same three identical credits ({built.count(ATTR)})")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
