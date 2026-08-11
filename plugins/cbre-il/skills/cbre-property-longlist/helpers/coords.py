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
    if coords is None:
        coords = dms_from_text(s)
    return coords, map_link


# B60: DMS (degrees/minutes/seconds) is the OTHER way a brochure prints a first-party pin, and
# it needs NO cue guard - the degree/minute/second punctuation plus a hemisphere letter is
# unambiguous, so it can never collide with a period-thousands area list the way a bare decimal
# pair can. Converting is EXACT arithmetic (deg + min/60 + sec/3600), the same class as
# acres x43,560 or a monthly rent x12 that this pipeline already does in Python.
# It exists because a live run shipped two town-centre geocodes while the pages printed
# 48°29'51.0"N 17°01'39.7"E and 47°58'23.0"N 17°42'10.3"E: the reader was told lat/lng are
# NUMBERS and that converting itself would emit a value absent from the source, so it honestly
# dropped them. Reader transcribes, Python converts - the rule the rest of the skill already runs on.
# Tolerant of the mangling a PDF text layer applies (the pair is routinely split across lines, and
# the seconds mark arrives as ", ” or ''), but it still REQUIRES degree+minute marks and a
# hemisphere letter on BOTH halves, so prose like "a 48 m x 17 m unit" can never match.
_DMS_HALF = (r"(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′´]\s*"
             r"(\d{1,2}(?:[.,]\d+)?)?\s*(?:\"|”|″|'')?\s*([NSEW])")
_DMS_PAIR = re.compile(_DMS_HALF + r"[\s,;/]*" + _DMS_HALF, re.I | re.S)


def _dms_to_deg(d: str, m: str, s: str | None, hemi: str) -> float:
    val = float(d) + float(m) / 60.0 + (float(str(s).replace(",", ".")) / 3600.0 if s else 0.0)
    return -val if hemi.upper() in ("S", "W") else val


def dms_from_text(text: str):
    """(lat, lng) from the first well-formed DMS pair in a text blob, else None.

    Order is taken from the HEMISPHERE letters, not position, so 'E... N...' parses correctly.
    A pair naming two latitudes or two longitudes is rejected rather than guessed. Pure."""
    m = _DMS_PAIR.search(str(text or "").replace(" ", " "))
    if not m:
        return None
    a = (m.group(1), m.group(2), m.group(3), m.group(4))
    b = (m.group(5), m.group(6), m.group(7), m.group(8))
    halves = {}
    for d, mi, se, hemi in (a, b):
        axis = "lat" if hemi.upper() in ("N", "S") else "lng"
        if axis in halves:                    # two of the same axis - not a coordinate pair
            return None
        halves[axis] = _dms_to_deg(d, mi, se, hemi)
    if "lat" not in halves or "lng" not in halves:
        return None
    lat, lng = halves["lat"], halves["lng"]
    return (lat, lng) if _valid(lat, lng) else None


# B60: a maps SHORT link (maps.app.goo.gl, goo.gl/maps, bit.ly...) carries no coordinates - it
# has to be followed. `coords_from_url` returns None for one by design, and until now nothing
# ever resolved it, so a first-party pin shipped as a bare href while the card showed a
# town-centre geocode. The fetch is injected, so this module stays pure and offline-safe.
SHORT_MAPS = re.compile(r"^https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|g\.co/kgs|bit\.ly)/", re.I)
# ORDER MATTERS. `@lat,lng,zoom` is the map VIEWPORT CENTRE, not the pin - on a real link it sat
# ~190 m off the site - so the destination forms are tried FIRST and `@` is the last resort.
_RESOLVED_LL = [
    re.compile(r"/maps/search/(-?\d+\.\d+),\s*\+?\s*(-?\d+\.\d+)"),
    re.compile(r"[?&]q=(-?\d+\.\d+),\s*\+?\s*(-?\d+\.\d+)"),
    re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)"),
    re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)"),
]


def coords_from_resolved(final_url: str, body: str = ""):
    """(lat, lng) from a FOLLOWED short link's final URL (+ optional body), else None.

    A `/maps/place/<DMS>/@...` result prefers the DMS in the place path over the `@` viewport,
    because the DMS IS the pin. Pure - give it whatever the fetcher returned."""
    hay = unquote(str(final_url or ""))
    place = re.search(r"/maps/place/([^/@?]+)", hay)
    if place:
        got = dms_from_text(place.group(1).replace("+", " "))
        if got:
            return got
    for rx in _RESOLVED_LL:
        m = rx.search(hay)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if _valid(lat, lng):
                return (lat, lng)
    if body:
        for rx in _RESOLVED_LL[:3]:
            m = rx.search(unquote(str(body)))
            if m:
                lat, lng = float(m.group(1)), float(m.group(2))
                if _valid(lat, lng):
                    return (lat, lng)
    return None
