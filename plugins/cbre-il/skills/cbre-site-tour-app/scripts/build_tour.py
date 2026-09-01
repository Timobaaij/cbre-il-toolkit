#!/usr/bin/env python3
"""
Build a self-contained CBRE site-tour web app from a tour.json.

    python build_tour.py tour.json -o "Tour.html"

Everything lands in ONE .html file: CBRE brand fonts base64-embedded, all CSS
and JS inline, no network calls at runtime. Google Maps links are external by
design (they open the Maps app); the page itself needs no connection.

Exit codes
    0  built
    2  input/validation error (message on stderr, nothing written)
"""

import argparse
import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
FONT_DIR = os.path.join(ASSETS, "fonts")

# family -> (css name, [(file, weight)]), mime chosen per real container
FONTS = [
    ("Calibre", "woff2", "font/woff2", [
        ("Calibre-400.woff2", 400),
        ("Calibre-500.woff2", 500),
        ("Calibre-600.woff2", 600),
        ("Calibre-700.woff2", 700),
    ]),
    ("Financier Display", "woff2", "font/woff2", [
        ("FinancierDisplay-400.woff2", 400),
        ("FinancierDisplay-600.woff2", 600),
    ]),
    # Space Mono ships as TTF in the CBRE reference dashboard. Declaring the
    # true container matters: a wrong format() hint makes some browsers skip
    # the face entirely and fall back to Courier.
    ("Space Mono", "truetype", "font/ttf", [
        ("SpaceMono-400.ttf", 400),
        ("SpaceMono-700.ttf", 700),
    ]),
]


def die(msg):
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(2)


def read_vendor(name):
    path = os.path.join(ASSETS, "vendor", name)
    if not os.path.exists(path):
        die("missing vendor asset: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def build_fonts(embed=True):
    """Return the @font-face CSS block."""
    if not embed:
        return ("/* Brand fonts not embedded: falling back to system stacks.\n"
                "   Output will NOT be visually correct CBRE. */")
    out = []
    for family, fmt, mime, files in FONTS:
        for fname, weight in files:
            path = os.path.join(FONT_DIR, fname)
            if not os.path.exists(path):
                die("missing font asset: %s" % path)
            with open(path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("ascii")
            out.append(
                "@font-face{font-family:'%s';src:url(data:%s;base64,%s) format('%s');"
                "font-weight:%d;font-style:normal;font-display:block}"
                % (family, mime, b64, fmt, weight)
            )
    return "\n".join(out)


# ------------------------------------------------------------------ validate
KINDS = {"view", "travel", "meal", "meet"}


def validate(tour):
    """Structural checks. Returns a list of warnings; fatals raise via die()."""
    warn = []

    if not isinstance(tour, dict):
        die("tour.json must be a JSON object")

    meta = tour.get("meta") or {}
    if not meta.get("title"):
        die("meta.title is required")

    days = tour.get("days") or []
    props = tour.get("properties") or []
    markets = tour.get("markets") or {}

    if not days:
        die("days[] is empty: there is no tour to render")

    ids = [p.get("id") for p in props]
    dupes = set(x for x in ids if ids.count(x) > 1)
    if dupes:
        die("duplicate property ids: %s" % ", ".join(sorted(str(d) for d in dupes)))
    if any(not i for i in ids):
        die("every property needs an id")

    idset = set(ids)

    for p in props:
        if p.get("market") and p["market"] not in markets:
            warn.append("property %s references unknown market '%s'" % (p["id"], p["market"]))
        has_lat = p.get("lat") is not None
        has_lng = p.get("lng") is not None
        if has_lat != has_lng:
            die("property %s has only one of lat/lng" % p["id"])
        if has_lat:
            try:
                lat, lng = float(p["lat"]), float(p["lng"])
            except (TypeError, ValueError):
                die("property %s has non-numeric lat/lng" % p["id"])
            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                die("property %s coordinates out of range: %s, %s" % (p["id"], lat, lng))
        if not (has_lat or p.get("mapsUrl") or p.get("query") or p.get("city")):
            warn.append("property %s has no coordinates, maps link, query or city: "
                        "its Maps button will be hidden" % p["id"])
        for key in ("facts", "terms"):
            for f in p.get(key) or []:
                if not isinstance(f, (list, tuple)) or len(f) != 2:
                    die("property %s has a malformed %s entry (need [label, value]): %r"
                        % (p["id"], key, f))

    seen_days = set()
    for d in days:
        if d.get("date"):
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d["date"])):
                die("day %s has a non ISO date '%s' (want YYYY-MM-DD)"
                    % (d.get("n", "?"), d["date"]))
            if d["date"] in seen_days:
                warn.append("two days share the date %s" % d["date"])
            seen_days.add(d["date"])
        else:
            warn.append("day %s has no date: countdown and 'today' "
                        "highlighting will not work" % d.get("n", "?"))
        stops = d.get("stops") or []
        if not stops:
            warn.append("day %s has no stops" % d.get("n", "?"))
        for s in stops:
            if s.get("kind") and s["kind"] not in KINDS:
                warn.append("stop '%s' has unknown kind '%s' (known: %s)"
                            % (s.get("name", "?"), s["kind"], ", ".join(sorted(KINDS))))
            for key in ("prop", "also"):
                if s.get(key) and s[key] not in idset:
                    die("stop '%s' references unknown property id '%s'"
                        % (s.get("name", "?"), s[key]))
            if not s.get("name") and not s.get("prop"):
                die("a stop on day %s has neither a name nor a prop" % d.get("n", "?"))

        # Every day is meant to open on a map. A day with nothing placeable
        # renders with no map at all, which is a data gap, not a design choice.
        placeable = 0
        for s in stops:
            p = next((x for x in props if x.get("id") == s.get("prop")), None)
            if s.get("lat") is not None or (p and p.get("lat") is not None):
                placeable += 1
        if stops and placeable == 0:
            warn.append("day %s has no stop with coordinates: it will render "
                        "without a map" % d.get("n", "?"))
        elif stops and placeable < len(stops):
            warn.append("day %s: %d of %d stops have no coordinates and will be "
                        "missing from the map" % (d.get("n", "?"), len(stops) - placeable, len(stops)))

    # A property flagged tour:true that no stop visits is usually a data slip.
    visited = set()
    for d in days:
        for s in d.get("stops") or []:
            for key in ("prop", "also"):
                if s.get(key):
                    visited.add(s[key])
    for p in props:
        if p.get("tour") and p["id"] not in visited:
            warn.append("property %s is flagged tour:true but no stop visits it" % p["id"])

    return warn


# --------------------------------------------------------------------- build
def inject(template, key, value):
    token = "__%s__" % key
    if token not in template:
        die("template is missing the %s placeholder" % token)
    return template.replace(token, value)


def main():
    ap = argparse.ArgumentParser(description="Build a CBRE site-tour web app.")
    ap.add_argument("tour_json")
    ap.add_argument("-o", "--out", default="Tour.html")
    ap.add_argument("--no-fonts", action="store_true",
                    help="skip base64 brand fonts (smaller, off-brand)")
    ap.add_argument("--no-map", action="store_true",
                    help="omit embedded Leaflet (~165 KB smaller, no day maps)")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors")
    args = ap.parse_args()

    if not os.path.exists(args.tour_json):
        die("no such file: %s" % args.tour_json)

    with open(args.tour_json, "r", encoding="utf-8") as fh:
        try:
            tour = json.load(fh)
        except ValueError as e:
            die("tour.json is not valid JSON: %s" % e)

    warn = validate(tour)
    for w in warn:
        sys.stderr.write("WARN: %s\n" % w)
    if warn and args.strict:
        die("%d warning(s) with --strict" % len(warn))

    tpl_path = os.path.join(ASSETS, "tour_template.html")
    rt_path = os.path.join(ASSETS, "tour_runtime.js")
    for p in (tpl_path, rt_path):
        if not os.path.exists(p):
            die("missing asset: %s" % p)

    with open(tpl_path, "r", encoding="utf-8") as fh:
        tpl = fh.read()
    with open(rt_path, "r", encoding="utf-8") as fh:
        runtime = fh.read()

    meta = tour.get("meta") or {}

    # JSON embedded in a <script> block: the only sequence that can break out
    # is a literal </script (case-insensitive). Escaping the slash keeps the
    # JSON byte-identical once parsed.
    data = json.dumps(tour, ensure_ascii=False, separators=(",", ":"))
    data = re.sub(r"</(script)", r"<\\/\1", data, flags=re.I)

    if "</script" in runtime.lower():
        die("tour_runtime.js contains a literal </script and cannot be inlined")

    title = meta.get("documentTitle") or meta.get("title") or "Site tour"
    if meta.get("dateRange") and not meta.get("documentTitle"):
        title = "%s · %s" % (title, meta["dateRange"])

    # Leaflet is embedded, not linked, so the file stays one portable artefact.
    # Its TILES are the only runtime network dependency; the runtime says so
    # on screen when they fail rather than showing a silent grey box.
    if args.no_map:
        leaflet_css = "/* Leaflet omitted (--no-map): day maps disabled. */"
        leaflet_js = "/* Leaflet omitted (--no-map). */"
    else:
        leaflet_css = read_vendor("leaflet.css")
        leaflet_js = read_vendor("leaflet.js")
        if "</script" in leaflet_js.lower():
            die("vendor/leaflet.js contains a literal </script and cannot be inlined")

    html = tpl
    html = inject(html, "LEAFLET_CSS", leaflet_css)
    html = inject(html, "LEAFLET_JS", leaflet_js)
    html = inject(html, "FONTS", build_fonts(embed=not args.no_fonts))
    html = inject(html, "DATA", data)
    html = inject(html, "RUNTIME", runtime)
    html = inject(html, "TITLE", esc_attr(title))
    html = inject(html, "APPTITLE", esc_attr(meta.get("appTitle") or meta.get("title") or "Tour"))
    html = inject(html, "WORDMARK", esc_attr(meta.get("wordmark") or "CBRE"))
    html = inject(html, "LANG", esc_attr(meta.get("lang") or "en"))

    left = re.findall(r"__[A-Z_]+__", html)
    if left:
        die("unfilled placeholders remain: %s" % ", ".join(sorted(set(left))))

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        fh.write(html)

    kb = os.path.getsize(args.out) / 1024.0
    n_stops = sum(len(d.get("stops") or []) for d in tour.get("days") or [])
    sys.stdout.write(
        "built %s\n  %.0f KB · %d day(s) · %d stop(s) · %d propert(ies) · %d warning(s)\n"
        % (args.out, kb, len(tour.get("days") or []), n_stops,
           len(tour.get("properties") or []), len(warn))
    )
    return 0


def esc_attr(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


if __name__ == "__main__":
    sys.exit(main())
