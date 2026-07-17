#!/usr/bin/env python3
"""coords.py - shared, PURE map-link / coordinate parser (no I/O, no clock, no randomness).

A brochure/tracker/email author's OWN maps link or a coordinate pair is FIRST-PARTY data: it beats
any geocoder and is available fully offline (a real Spanish run once burned a day on a blocked
geocoder while every page carried maps.google.com/?q=lat,lng links). This module is the single home
for the URL/coordinate grammar; extract_pdf.backfill_link_coords applies it across ALL text inputs
(PDF page text + annotations, Excel cells, PPTX slides, email bodies) so the parsing is written and
tested once. It NEVER invents: an unresolvable short link (goo.gl / maps.app.goo.gl) yields a mapLink
but no coordinate, and every pair is bounds- and precision-checked."""
from __future__ import annotations

import re
from urllib.parse import unquote

# host/scheme signature of a maps link (lifted verbatim from the historical extract_pdf._MAPS_URI)
MAPS_URI = re.compile(
    r"maps\.google|google\.[a-z.]{2,8}/maps|goo\.gl/maps|maps\.app\.goo\.gl|"
    r"openstreetmap\.org|osm\.org|bing\.com/maps|maps\.apple\.com|geo:", re.I)

# destination / single-point keys ONLY. saddr (directions START/origin) and sll (search-viewport
# centre) are NOT the pinned property, so they are never accepted. Order = precedence. (Verbatim
# from the historical extract_pdf._LINK_LL.)
LINK_LL = [
    re.compile(r"[?&](?:q|query|ll|center|daddr|destination)="
               r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})"),
    re.compile(r"@(-?\d{1,2}\.\d{3,}),(-?\d{1,3}\.\d{3,})"),
    re.compile(r"!3d(-?\d{1,2}\.\d{3,})!4d(-?\d{1,3}\.\d{3,})"),
    re.compile(r"/place/(-?\d{1,2}\.\d{3,}),(-?\d{1,3}\.\d{3,})"),
    re.compile(r"\bgeo:(-?\d{1,2}\.\d{3,}),(-?\d{1,3}\.\d{3,})"),
]

# a BARE 'lat, lng' pair in prose or a cell. SAME precision (>=3 decimals) + bounds guards as the
# URL matchers, so a comma-thousands area magnitude ('51,500') or a low-precision ratio ('1.2, 3.4')
# can never false-positive. The negative look-around stops it latching onto the middle of a longer
# number run.
PLAIN_LL = re.compile(r"(?<![\d.])(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})(?![\d.])")

# A bare pair is ONLY trusted when a coordinate CUE sits immediately before it. This is the honesty
# guard for PERIOD-as-thousands locales (ES/DE/…): a size list like '12.500, 18.500 m2' (= 12,500 and
# 18,500 sqm) otherwise satisfies PLAIN_LL and would be misread as an exact pin (lat 12.5, lng 18.5).
# A genuine coordinate in prose/a cell carries a label ('Coordinates:', 'GPS', 'lat/lng'); an area
# list never does. (A LABELLED spreadsheet coordinate COLUMN is handled upstream by extract_xlsx's
# `latlng`/`lat`/`lng` column path, not by this text scan.)
# A cue must be a real coordinate LABEL, not a substring buried in a common word. The short forms
# (lat/lng/lon/gps) are WHOLE-WORD anchored - otherwise 'plataforma'->'lat', 'lateral'->'lat',
# 'colonia'->'lon' would re-admit a period-thousands SIZE pair as a pin (ES/DE, the very locales this
# guards). The long forms are LEADING-anchored prefixes so 'latitude'/'latitud', 'longitude'/'longitud',
# 'coordinate'/'coordenadas'/'coordonnées', 'koordinaten' all still count.
_COORD_CUE = re.compile(r"\b(?:lat|lng|lon|gps)\b|\b(?:latitud|longitud|coord|koordinat)", re.I)
_CUE_WINDOW = 24  # chars of preceding context searched for a cue


def _valid(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180 and (abs(lat) > 0.01 or abs(lng) > 0.01)


def coords_from_url(uri: str) -> tuple[float, float] | None:
    """(lat, lng) from a single maps URL, or None. Only a maps-host URL carrying a parseable,
    in-bounds destination pair resolves; a short/unparseable link returns None (its href still ships
    as a mapLink via coords_and_link_from_text)."""
    if not uri or not MAPS_URI.search(uri):
        return None
    u = unquote(str(uri))
    for rx in LINK_LL:
        m = rx.search(u)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if _valid(lat, lng):
                return (lat, lng)
    return None


def coords_and_link_from_text(text: str) -> tuple[tuple[float, float] | None, str | None]:
    """(coords, mapLink) from a free text blob.

    coords = the first maps URL that carries a parseable lat/lng, else the first CUE-LABELLED bare
    PLAIN_LL pair (an unlabelled bare pair is left a gap - see `_COORD_CUE`). mapLink = the first maps
    URL seen (so a short goo.gl link still ships its href with the coord left an honest gap). Either
    half may be None. Pure - never raises on odd input."""
    s = str(text or "")
    map_link = None
    coords = None
    # first maps URL (token-scan so a trailing ')' / '.' / ',' is not captured into the href)
    for tok in re.split(r"\s+", s):
        t = tok.strip().rstrip(").,;]>\"'")
        if t and MAPS_URI.search(t):
            if map_link is None:
                map_link = t
            c = coords_from_url(t)
            if c:
                coords = c
                break
    if coords is None:
        # a bare pair is trusted ONLY with a coordinate cue in the preceding window (never invent a
        # pin from a period-thousands area list); scan all matches so a later labelled pair still wins.
        for m in PLAIN_LL.finditer(s):
            lat, lng = float(m.group(1)), float(m.group(2))
            if not _valid(lat, lng):
                continue
            if _COORD_CUE.search(s[max(0, m.start() - _CUE_WINDOW):m.start()]):
                coords = (lat, lng)
                break
    return coords, map_link
