#!/usr/bin/env python3
"""extract_pdf.py - extract candidate property records from a CBRE brochure PDF.

Brochure layout (verified against the Normal CEE set):
  * page 1 is a numbered Table Of Contents -> ordered property names + count
  * pages 2..N each describe ONE property as a label -> value sequence
    (City, Owner/developer, Warehouse Area, Warehouse [rent], ...), plus a
    "lat, lng" line and a prose DESCRIPTION block.

Parsing is label-anchored: we locate every known label (allowing it to wrap
across lines) and take the text between one label and the next as its value.
If a deck has NO own-line labels on any page (an inline "Label value" layout,
e.g. "Clear height 10.50 m" / "Ciudad: Madrid"), the extractor falls back to
same-line label/value parsing; only image/vector-only decks then need the vision
fallback. The own-line path is unchanged when any own-line labels exist, so
spec-sheet decks extract byte-identically.
Deterministic; PDF text is cleaner than PPTX run-splitting, so this is the
preferred FIELD source (images come from the PPTX / a page raster).

CLI:
  python extract_pdf.py <file.pdf> --region Pilsen --country CZ [--out records.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import fitz  # PyMuPDF
except Exception:  # sandbox without PyMuPDF: pypdfium2/pdfplumber shim (same 9-call surface)
    import fitz_shim as fitz
try:
    fitz.TOOLS.mupdf_display_errors(False)  # silence MuPDF C-level warnings (broker quiet mode)
except Exception:
    pass
import normalize as N
import coords as _CO

# canonical label phrase -> (field, kind). kind: text | num | rent | passthru
LABELS = [
    ("City", "city", "text"),
    ("Property Status", "status", "text"),
    ("Permitting status and timeline", "permitting", "text"),
    ("Permitting status & timeline", "permitting", "text"),
    ("Early Access Date", "earlyAccess", "text"),
    ("Early access", "earlyAccess", "text"),
    ("Owner/developer", "developer", "text"),
    ("Owner / developer", "developer", "text"),
    ("Developer", "developer", "text"),
    ("Plot Area", "plotArea", "num"),
    ("Warehouse Area", "warehouseArea", "num"),
    ("Divisible from", "divisibleFrom", "text"),
    ("Office Area", "officeArea", "text"),
    ("Expansion in building", "expansionBuilding", "text"),
    ("Expansion in park", "expansionPark", "text"),
    ("Expansion Possible?", "expansionPark", "text"),
    ("Expansion possible", "expansionPark", "text"),
    ("Clear height", "clearHeight", "text"),
    ("Floor load", "floorLoad", "text"),
    ("Sprinklers", "sprinklers", "text"),
    ("Loading docks", "loadingDocks", "text"),
    ("Overhead doors", "overheadDoors", "text"),
    ("Electricity", "electricity", "text"),
    ("BREEAM", "breeam", "text"),
    ("Truck parking", "truckParking", "text"),
    ("Car parking", "carParking", "text"),
    ("Lease Term", "leaseTerm", "text"),
    ("Warehouse", "warehouseRent", "rent"),
    ("Office", "officeRent", "rent"),
    ("Service charge", "serviceCharge", "text"),
    ("Rent Free", "rentFree", "text"),
    ("Rent free", "rentFree", "text"),
    ("Another Incentives", "incentives", "text"),
    ("Other Incentives", "incentives", "text"),
    ("Incentives", "incentives", "text"),
    ("Land price", "landPrice", "text"),
]


def _load_ledger_labels() -> list:
    """Append multilingual label aliases from assets/label_ledger.json (if present)
    to the English baseline above, so the parser reads ES/FR/DE/IT/NL/PT/PL decks
    too. English stays the baseline; a missing or broken ledger is a silent no-op."""
    out = []
    try:
        led = json.loads((Path(__file__).resolve().parent.parent / "assets" / "label_ledger.json")
                         .read_text(encoding="utf-8"))
        for field, spec in (led.get("fields") or {}).items():
            kind = spec.get("kind", "text")
            for alias in spec.get("aliases", []):
                out.append((alias, field, kind))
    except Exception:
        pass
    return out


# merge ledger aliases into LABELS, de-duplicating on (phrase, field)
_seen = set()
LABELS = [x for x in (LABELS + _load_ledger_labels())
          if not ((x[0], x[1]) in _seen or _seen.add((x[0], x[1])))]

# many EU markets quote rent per MONTH; annualise (x12) to the dashboard's
# "/ sq m / year" basis - the conversion is recorded in the ledger, never hidden.
# The monthly regex + the EUR/m²/yr plausibility band live in normalize.py (shared
# with merge, which normalises agent-written rent strings the same way).
MONTHLY_RX = N.MONTHLY_RX

# a value is only a RENT when it shows a currency or a per-area unit; a bare big
# number (e.g. a size caught by the short ambiguous "Warehouse" label) is NOT a
# rent. Without this gate, "Warehouse\n39 471 sq m" became a €39,471/m² rent and
# routed whole readable decks to the vision fallback.
RENT_CONTEXT = re.compile(
    r"€|\beur(?:os?)?\b|\bczk\b|\bhuf\b|\bpln\b|\bron\b|\bgbp\b|£"
    r"|/\s*(?:m2|m²|sq\.?\s?m\.?|sqm)\b"
    r"|\bpsf\b|(?:/|per)\s*sq\.?\s?ft\b", re.IGNORECASE)


def _parse_rent(raw: str):
    """(display, annual_value, conversion_note, unit) for a rent-kind value, or
    (None, None, '', None) when the value is not a rent at all (no currency/unit
    context and no plausible figure). The SOURCE convention is kept: '£8.50 psf'
    ships as £/sq ft/yr with the band for that convention, continental quotes
    stay €/m²/yr (monthly x12, recorded). A numeric outside its band is refused -
    the display text is kept, the number is not (honest text beats a confidently
    wrong figure). unit is None when nothing was stated (caller's € default)."""
    has_ctx = bool(RENT_CONTEXT.search(raw))
    em = re.search(r"[€£]\s*(" + _NUMTOK + r"+)", raw)
    # a RANGE ("€55 - 60") has no single headline value - the currency-symbol path
    # bypassed normalize's own range guard and shipped one end as a confident number
    # (audit S1-9); keep the honest text, ship no number.
    if N.is_range(re.sub(r"\([^)]*\)", " ", raw)):
        num = None  # a range in the rent FIGURE ('€55-60'); a date span in parens is stripped first
    else:
        num = N.normalize_number(em.group(1)) if em else N.extract_first_number(raw)
    unit = N.rent_unit_of_text(raw)
    monthly = num is not None and bool(MONTHLY_RX.search(raw))
    orig = num
    if monthly and num is not None:
        num = round(num * 12, 2)
    lo, hi = N.rent_unit_band(unit)
    if num is not None and not (lo <= num <= hi):
        num = None  # implausible in its own convention - never ship the number
    if num is None and not has_ctx:
        return None, None, "", None  # not a rent (a size/prose line under a rent label)
    display = N.rent_display(num, unit) if num is not None else N.clean_value(raw)
    note = f" ({orig:g}/mo x12)" if (monthly and num is not None) else ""
    return display, num, note, unit


def _rent_unit_assumed(raw: str, num) -> bool:
    """True when a rent number is shipped but the source stated NEITHER a currency
    NOR a per-area unit - the displayed EUR / sq m is then a house DEFAULT, not the
    source. Mirrors extract_xlsx: ship the number but flag it ASSUMED for the Gaps
    Report; never silently invent the currency/unit (audit S1-10)."""
    return num is not None and not RENT_CONTEXT.search(raw)


# one digit/thousands-separator char: digits, '.'/',', and the Unicode spaces
# PyMuPDF emits for EU grouping (NBSP, thin/narrow/figure/hair space + ASCII).
# Mirrors normalize._SPACES so "39<NBSP>471" is captured whole, not split into
# 39 / 471 (which would both fail the >=1000 area filter and drop the size).
_NUMTOK = r"[\d\u00a0\u2009\u202f\u2007\u200a .,]"

# a SINGLE area number: either space-grouped EU thousands ("25 000", "1 234 567") or
# a plain / dot / comma number ("40000", "12.500", "131,536"). Unlike the old greedy
# _NUMTOK run, this does NOT cross a comma-space list separator, so "Unit 5, 25 000"
# no longer glues into a fabricated 525000 (audit S1-1).
_AREA_NUM = re.compile(r"\d{1,3}(?:[\u00a0\u2009\u202f\u2007\u200a ]\d{3})+|\d+(?:[.,]\d+)*")

LATLNG = re.compile(r"(-?\d{1,2}\.\d{3,}),\s*(-?\d{1,3}\.\d{3,})")  # -? = western/southern (ES/PT/FR/UK) coords
PROSE = re.compile(r"(?:(?<=\n)|^)([A-Z][a-z]+\b.{140,})", re.DOTALL)


def _find_latlng(text: str):
    """First PLAUSIBLE coordinate pair, or None. Guards the bare numeric pattern:
    values must be in range, and the line must not be an area/size list - Spanish
    dot-thousand unit lists ('naves de 12.500, 8.750 y 6.200 m2') match the raw
    regex and would otherwise pin the property on another continent."""
    for m in LATLNG.finditer(text):
        lat, lng = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        ls = text.rfind("\n", 0, m.start()) + 1
        le = text.find("\n", m.end())
        line = text[ls:le if le != -1 else len(text)]
        # a size/area list ('naves de 12.500, 8.750 ... m2', 'Superficies: 12.500, 8.750') is
        # NOT coordinates - reject on a size UNIT or a size KEYWORD on the line. A bare plausible
        # coordinate pair with neither is accepted (it degrades to geocode if wrong, never a
        # fabricated pin); the trusted first-party pin is the brochure map-link, harvested in
        # merge. A genuine 3-decimal coordinate (~110 m) must NOT be rejected (audit S1-11 + review).
        if re.search(r"sq\.?\s?m|sqm|m2|m²|\bha\b|\bm\b|superfic|\bnaves?\b|surface|"
                     r"\bplot\b|\bsize\b|\bárea\b|\barea\b|dispon", line, re.IGNORECASE):
            continue  # a size list, not coordinates
        return lat, lng
    return None


def _apply_num(rec: dict, prov: dict, field: str, raw: str, locator: str) -> None:
    """Area-kind value handling shared by the own-line and inline paths.

    * A RANGE has no single numeric (normalize.py contract): plotArea may carry the
      honest text (schema allows a string); a warehouseArea range goes to
      divisibleFrom as text - warehouseArea is schema-NUMERIC, so writing the range
      string (or silently taking the maximum) would either fail validate-data or
      fabricate a size.
    * Otherwise take the FIRST plausible (>=1000) number, not the largest - 'the
      largest' turned '39 471 sq m (expandable to 80 000)' into 80000.
    """
    if N.is_range(raw):
        txt = N.clean_value(raw)
        if field == "plotArea":
            rec[field] = txt
            prov[field] = locator
        elif not rec.get("divisibleFrom"):
            rec["divisibleFrom"] = txt
            prov["divisibleFrom"] = f"{locator} (range)"
        return
    taken = False
    for m in _AREA_NUM.finditer(raw):
        c = N.normalize_number(m.group(0))
        if c is None or c < 1000:
            continue
        rec[field] = c
        prov[field] = locator
        # the unit token NEAREST AFTER the matched number decides the convention
        # ("131,536 sq ft (12,220 sq m)" tags sq ft; the reverse order tags sq m);
        # source units are KEPT - merge normalises to the dataset's dominant unit
        unit = N.area_unit_of(raw[m.end():m.end() + 14])
        if unit in ("sq ft", "sq m"):
            rec.setdefault("areaUnit", unit)
        taken = True
        break
    if not taken and not N.looks_unknown(raw) and field == "plotArea":
        rec[field] = N.sentinel(raw, field=field)  # string is schema-legal here
        prov[field] = locator
    # warehouseArea with no parseable number stays unset - honest gap, never a string


def _label_regex(phrase: str) -> str:
    # internal whitespace flexes across line wraps; label sits on its own line
    body = r"\s+".join(re.escape(w) for w in phrase.split())
    return rf"(?:(?<=\n)|^)[ \t]*{body}[ \t]*(?=\n)"


def _inline_label_regex(phrase: str) -> str:
    # INLINE form: label and value on the SAME line ("Clear height 10.50 m",
    # "Ciudad: Madrid", "- Altura libre: 11,50"). An optional leading bullet/marker
    # is consumed (-, *, •, ·, ▪, …) so bulleted spec lines match in any language. A
    # delimiter (separator and/or whitespace) is REQUIRED after the label, so a label
    # cannot match as the prefix of a longer word ("City" in "Cityscape"); matching
    # stays case-sensitive so lowercase prose ("city centre") is ignored.
    body = r"\s+".join(re.escape(w) for w in phrase.split())
    return rf"(?:(?<=\n)|^)[ \t]*(?:[-*•·▪◦‣►–—][ \t]*)?{body}(?:[ \t]*(?P<sep>[:=\-–—])[ \t]*|[ \t]+)(\S[^\n]*?)[ \t]*(?=\n|$)"


# longest phrases first so "Warehouse Area" wins over "Warehouse"
_ORDERED = sorted(LABELS, key=lambda x: -len(x[0]))
_COMPILED = [(re.compile(_label_regex(p)), f, k) for p, f, k in _ORDERED]
_INLINE = [(re.compile(_inline_label_regex(p)), f, k) for p, f, k in _ORDERED]


def parse_toc(page_text: str) -> list[str]:
    names, lines = [], [l.strip() for l in page_text.splitlines()]
    i = 0
    while i < len(lines):
        if re.fullmatch(r"\d+\.", lines[i]) and i + 1 < len(lines) and lines[i + 1]:
            names.append(lines[i + 1])
            i += 2
        else:
            i += 1
    return names


def _find_labels(text: str):
    hits = []
    for rx, field, kind in _COMPILED:
        for m in rx.finditer(text):
            hits.append((m.start(), m.end(), field, kind))
    # resolve overlaps: prefer the match that starts earliest, longest label
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    chosen, last_end = [], -1
    for s, e, field, kind in hits:
        if s >= last_end:
            chosen.append((s, e, field, kind))
            last_end = e
    return chosen


def _find_inline_labels(text: str):
    """Same-line 'Label value' matches, longest-label-first, de-overlapped. Used
    only when own-line parsing finds <2 labels (inline decks), so own-line
    spec-sheet decks are never affected."""
    hits = []
    for rx, field, kind in _INLINE:
        for m in rx.finditer(text):
            hits.append((m.start(), m.end(), field, kind, m.group(2),
                         bool(m.group("sep"))))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    chosen, last_end = [], -1
    for h in hits:
        if h[0] >= last_end:
            chosen.append(h)
            last_end = h[1]
    return chosen


def _apply_inline_labels(text: str, rec: dict, prov: dict, page_no: int) -> None:
    """Populate rec/prov from inline 'Label value' lines (any own-line value
    already present wins). Mirrors the own-line kind handling: num -> largest
    plausible number, rent -> euro/first number with monthly->annual conversion,
    else cleaned text. Kind-aware acceptance keeps a stray prose line from becoming
    a bogus numeric/rent field."""
    for s, e, field, kind, raw, has_sep in _find_inline_labels(text):
        if field in rec:
            continue  # first value wins, consistent with the own-line path
        raw = (raw or "").strip()
        if not raw or N.looks_unknown(raw):
            continue
        loc = f"page {page_no} (inline)"
        if kind == "num":
            _apply_num(rec, prov, field, raw, loc)
            continue
        if kind == "rent":
            display, num, note, runit = _parse_rent(raw)
            if display is None:
                continue  # a prose/size line caught by a rent label, not a rent value
            if field == "warehouseRent":
                rec["warehouseRent"] = display
                rec["warehouseRentVal"] = num
                if runit:
                    rec["rentUnit"] = runit
                prov["warehouseRentVal"] = loc + note
            elif field == "officeRent":
                rec["officeRent"] = display
            else:
                rec[field] = N.clean_value(raw)
        else:
            # a BARE-SPACE delimited text match on a prose line ("City centre is
            # 5 km away") is sentence text, not a labelled value - accept only
            # short values when there was no explicit :/=/- separator
            if not has_sep and (len(raw) > 40 or len(raw.split()) > 4):
                continue
            rec[field] = N.sentinel(raw, field=field)
        prov[field] = loc


def _has_core(rec: dict) -> bool:
    """A parsed record is a usable property only if it carries at least one CORE
    field - city, developer, warehouse area/rent, OR (for a land/plot listing) plot
    area / land price. A page that yielded only peripheral specs (clear height,
    docks) is NOT a property; dropping it lets the deck fall through to the vision
    fallback instead of shipping a coreless stub. Field-based - so language-, client-
    and layout-neutral - and covers both built-warehouse and land-for-sale records."""
    return any(not N.looks_unknown(rec.get(f))
               for f in ("city", "developer", "warehouseArea", "warehouseRent",
                         "plotArea", "landPrice"))


def parse_property_page(text: str, park, region: str, country: str,
                        source_file: str, page_no: int) -> dict:
    rec: dict = {"region": region, "country": country}
    prov: dict = {"region": "cluster", "country": "cluster"}

    # strip the page footer ("<page no>\n<park name>" at the very end) so it does
    # not bleed into the last field's value (TOC brochures repeat the name there)
    if park:
        text = re.sub(r"\n\s*\d+\s*\n\s*" + re.escape(park) + r"\s*$", "\n", text)

    ll = _find_latlng(text)
    if ll:
        rec["lat"], rec["lng"] = ll
        prov["lat"] = prov["lng"] = f"page {page_no}"

    hits = _find_labels(text)
    description = ""
    for idx, (s, e, field, kind) in enumerate(hits):
        nxt = hits[idx + 1][0] if idx + 1 < len(hits) else len(text)
        raw = text[e:nxt].strip()

        # rescue a prose block that bled into this value -> description
        pm = PROSE.search(raw)
        if pm and ". " in pm.group(1):
            prose = N.clean_value(pm.group(1))
            if len(prose) > len(description):
                description = prose
            raw = raw[:pm.start()].strip()

        if not raw:
            continue
        if field in rec:
            continue  # first value wins - with the rent context gate, a non-rent
            # "Warehouse <size>" hit is skipped entirely, so the true rent still lands

        if kind == "num":
            _apply_num(rec, prov, field, raw, f"page {page_no}")
            continue
        if kind == "rent":
            display, num, note, runit = _parse_rent(raw)
            if display is None:
                continue  # not a rent value (no currency/unit and no plausible figure)
            if field == "warehouseRent":
                rec["warehouseRent"] = display
                rec["warehouseRentVal"] = num
                if runit:
                    rec["rentUnit"] = runit
                prov["warehouseRentVal"] = f"page {page_no}" + note
            elif field == "officeRent":
                rec["officeRent"] = display
            else:
                rec[field] = N.clean_value(raw)
        else:
            rec[field] = N.sentinel(raw, field=field)
        prov[field] = f"page {page_no}"

    # INLINE fallback: this page uses same-line "Label value" layout (own-line
    # parse found <2 labels). Fill from inline matches; own-line values already set
    # always win. Own-line decks never reach this branch -> byte-identical to before.
    if len(hits) < 2:
        _apply_inline_labels(text, rec, prov, page_no)
        if not description:
            pm = PROSE.search(text)
            if pm and ". " in pm.group(1):
                description = N.clean_value(pm.group(1))

    if description:
        rec["description"] = description
        prov["description"] = f"page {page_no}"

    # motorway is usually in prose ("next to the D5 motorway"), not a label
    if "motorway" not in rec and description:
        mm = re.search(r"\b([A-Z]\d{1,2})\b(?=[^.]{0,30}(?:motorway|highway|expressway|exit))",
                       description) or re.search(
                       r"(?:motorway|highway|expressway)[^.]{0,30}?\b([A-Z]\d{1,2})\b", description)
        if mm:
            rec["motorway"] = mm.group(1)
            prov["motorway"] = f"page {page_no} (description)"

    # park name: from TOC if given, else synthesise developer + city (matches the
    # reference's "WING Sosket" style)
    if park:
        rec["park"], prov["park"] = park, "toc"
    else:
        dev = N.clean_value(rec.get("developer", "")) if not N.looks_unknown(rec.get("developer")) else ""
        city = rec.get("city", "") if not N.looks_unknown(rec.get("city")) else ""
        rec["park"] = (f"{dev} {city}".strip() or f"{region} option {page_no + 1}")
        prov["park"] = "developer+city"

    rec["__meta"] = {"source_file": source_file, "source_type": "pdf",
                     "locator_base": f"page {page_no}", "prov": prov,
                     "page_no": page_no}
    return rec


# exact coordinates from a 'click for location' maps hyperlink on the page -
# FIRST-PARTY data (the brochure author pinned the site), better than any
# geocoder and available fully offline. A real Spanish run burned a day on a
# blocked geocoder while every page carried maps.google.com/?q=lat,lng links.
# The map-link / coordinate grammar now lives in the shared `coords` module (one home, applied
# across ALL text inputs by backfill_link_coords). Re-exported here under the historical names so
# every `import extract_pdf as P` consumer (evals, vision_prep, extract_pptx) keeps working unchanged.
_MAPS_URI = _CO.MAPS_URI
_LINK_LL = _CO.LINK_LL


def _page_link_coords(page) -> tuple[tuple[float, float] | None, str | None]:
    """Return (coords, uri) from the page's maps hyperlinks: coords from the first
    link whose URL carries a parseable lat,lng (with that link's uri), else
    (None, first maps uri) so the link itself still ships as mapLink."""
    try:
        links = page.get_links()
    except Exception:
        return None, None
    from urllib.parse import unquote
    first_uri = None
    for lk in links:
        uri = str(lk.get("uri") or "")
        if not uri or not _MAPS_URI.search(uri):
            continue
        if first_uri is None:
            first_uri = uri
        u = unquote(uri)
        for rx in _LINK_LL:
            m = rx.search(u)
            if m:
                lat, lng = float(m.group(1)), float(m.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180 and (abs(lat) > 0.01 or abs(lng) > 0.01):
                    return (lat, lng), uri
    return None, first_uri


def _apply_link_coords(doc, pno: int, rec: dict) -> None:
    """Fill lat/lng AND the first-party mapLink from the page's maps hyperlink.
    The link is the brochure author's own pin - it ships as the property's
    'Open in Google Maps' target instead of an empty href."""
    if "lat" in rec and rec.get("mapLink"):
        return
    ll, uri = _page_link_coords(doc[pno])
    prov = rec.get("__meta", {}).get("prov", {})
    if ll and "lat" not in rec:
        rec["lat"], rec["lng"] = ll
        prov["lat"] = prov["lng"] = f"page {pno + 1} (map link)"
    if uri and not rec.get("mapLink"):
        rec["mapLink"] = uri
        prov["mapLink"] = f"page {pno + 1} (map link)"


def _resolve_pdf(source_dir, name):
    """Locate a record's source PDF under source_dir (source_file is a bare name; inputs may
    sit in subfolders). Returns a Path or None."""
    from pathlib import Path
    base = Path(str(name)).name
    if not base:
        return None
    root = Path(source_dir)
    direct = root / base
    if direct.exists():
        return direct
    try:
        matches = sorted(root.rglob(base))   # deterministic regardless of filesystem walk order
        if matches:
            return matches[0]
    except Exception:
        pass
    return None


def backfill_link_coords(records, source_dir):
    """Fill lat/lng + mapLink from a FIRST-PARTY map link across ALL text inputs - the source
    author's OWN pin (better than any geocoder, fully offline). Three passes:
      A  stashed __meta.map_candidates (a list of raw strings) - Excel cells + email bodies; the
         key is DELETED after resolving so it is never persisted to canonical.json;
      B  PDF re-open (fitz) - the page's 'click for location' hyperlink ANNOTATIONS, then a scan of
         the visible page TEXT for a maps URL / plain lat,lng;
      C  PPTX re-open (python-pptx) - the slide's text + its shape/run hyperlink addresses.
    Precedence is UNCHANGED: a record already carrying a NUMERIC coord AND a mapLink is left
    untouched, and the resolver runs pre-geocode so a first-party pin always beats the town centre.
    It NEVER invents - a link with no parseable lat/lng still ships its URL as mapLink and the coord
    stays a gap (a short goo.gl link needs a network resolve). Degrades to a no-op for a pass whose
    engine (fitz / python-pptx) or source file is absent."""

    def _num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def _done(r):
        return _num(r.get("lat")) and r.get("mapLink")

    def _apply(r, coords, uri, loc):
        prov = r.setdefault("__meta", {}).setdefault("prov", {})
        if coords and not _num(r.get("lat")):
            r["lat"], r["lng"] = coords[0], coords[1]
            prov["lat"] = prov["lng"] = f"{loc} ({'map link' if uri else 'coordinates'})"
        if uri and not r.get("mapLink"):
            r["mapLink"] = uri
            prov["mapLink"] = f"{loc} (map link)"

    # Pass A: stashed candidates (deterministic; no re-open). Runs for EVERY source type; the
    # candidate key is consumed and removed so it can never bloat or reach canonical.json.
    for r in records:
        m = r.get("__meta") or {}
        cands = m.get("map_candidates")
        if cands and not _done(r):
            loc = m.get("locator_base") or m.get("source_file") or "source"
            for cand in cands:
                c, ml = _CO.coords_and_link_from_text(cand)
                _apply(r, c, ml, loc)
                if _done(r):
                    break
        if isinstance(m, dict) and "map_candidates" in m:
            del m["map_candidates"]

    # group the still-missing records by source for the re-open passes
    by_pdf: dict = {}
    by_pptx: dict = {}
    for r in records:
        if _done(r):
            continue
        m = r.get("__meta") or {}
        pno, sf, st = m.get("page_no"), m.get("source_file"), m.get("source_type")
        if not (isinstance(pno, int) and sf):
            continue
        if st == "pdf":
            by_pdf.setdefault(str(sf), []).append((pno, r))
        elif st == "pptx":
            by_pptx.setdefault(str(sf), []).append((pno, r))

    # Pass B: PDF re-open (annotations, then visible page text)
    if by_pdf:
        try:
            import fitz  # noqa: F401
            for sf, items in by_pdf.items():
                path = _resolve_pdf(source_dir, sf)
                if not path:
                    continue
                try:
                    doc = fitz.open(str(path))
                except Exception:
                    continue
                try:
                    for pno, r in items:
                        if not (0 <= pno < doc.page_count):
                            continue
                        ll, uri = _page_link_coords(doc[pno])            # hyperlink annotations
                        if ll is None or uri is None:                    # fall back to visible text
                            try:
                                tc, tl = _CO.coords_and_link_from_text(doc[pno].get_text())
                            except Exception:
                                tc, tl = None, None
                            ll = ll or tc
                            uri = uri or tl
                        _apply(r, ll, uri, f"page {pno + 1}")
                finally:
                    doc.close()
        except Exception:
            pass

    # Pass C: PPTX re-open (slide text + hyperlink addresses). Lazy import of extract_pptx avoids
    # the extract_pptx -> extract_pdf module cycle at load time.
    if by_pptx:
        try:
            from pptx import Presentation
            import extract_pptx as PPTX
            for sf, items in by_pptx.items():
                path = _resolve_pdf(source_dir, sf)  # bare-name resolver (any extension)
                if not path:
                    continue
                try:
                    slides = list(Presentation(str(path)).slides)
                except Exception:
                    continue
                for pno, r in items:
                    if not (0 <= pno < len(slides)):
                        continue
                    try:
                        blob = PPTX.slide_text(slides[pno]) + "\n" + "\n".join(
                            PPTX.slide_link_targets(slides[pno]))
                    except Exception:
                        continue
                    c, ml = _CO.coords_and_link_from_text(blob)
                    _apply(r, c, ml, f"slide {pno + 1}")
        except Exception:
            pass

    return records


def _is_toc_page(text: str, toc_names: list[str]) -> bool:
    # a TOC page lists >=2 numbered names AND carries few property labels itself
    # (language-agnostic: count recognised labels, not English strings)
    return len(toc_names) >= 2 and len(_find_labels(text)) < 2


# --- brochure DESCRIPTION harvest -------------------------------------------
# A design-led marketing brochure yields no spec RECORD (its data is in graphics /
# a separate tracker), so its description prose was never captured even though the
# text layer carries it. best_description_in_deck pulls the property's description
# straight from the deck: group each page's lines by FONT SIZE (the body paragraph
# separates cleanly from big ALL-CAPS callouts, drive-time tables and the legal
# footer), keep the most descriptive prose block, anchored at the scheme identity
# ("EVO Corby 169 is ...", "Raven Park, Corby, is ..."). Verbatim from the brochure -
# never synthesised; absent stays absent. Used by merge on the photo-match link.
_DESC_GOOD = re.compile(
    r"\b(located|situated|location|comprises?|offers?|prominent|established|prime|"
    r"development|warehouse|logistics|distribution|industrial|unit|scheme|access|"
    r"connectivity|motorway|strategically|position(?:ed)?|accommodation|central|"
    r"specification|sustainab|BREEAM|delivers?|providing|benefit|reach|hub|catchment|transport)\b", re.I)
_DESC_BAD = re.compile(
    r"misrepresentation|every care has been taken|measurements|\bapproximate\b|"
    r"\bVAT\b|legal costs|anti-money|money laundering|subject to contract|"
    r"satisfy themselves|expressly excluded|repairing and insuring|"
    r"please contact|all parties|business rates|particulars are set out|to be agreed", re.I)
_DESC_ANCHOR = re.compile(
    r"\b[A-Z][A-Za-z'’&]+(?: [A-Za-z0-9][\w'’&.,/()-]*){0,4}? "
    r"(?:is|are|comprises?|offers?|provides?|sits|occupies|forms|delivers?|features?|boasts|has|will)\b")


def _desc_clean(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("\r", " ")).strip()


def _desc_anchor(txt: str) -> str:
    m = _DESC_ANCHOR.search(txt[:200])  # the scheme identity is near the start
    return txt[m.start():].strip() if m else txt


def _desc_cap(txt: str, n: int = 600) -> str:
    mm = re.search(r"^.*[.!?](?=\s|$)", txt[:n + 220], re.DOTALL)  # end on a whole sentence
    if mm and len(mm.group(0)) >= 120:
        txt = mm.group(0).strip()
    if len(txt) > n:
        cut = txt.rfind(". ", 0, n)
        txt = (txt[:cut + 1] if cut > 200 else txt[:n]).strip()
    return txt


def font_grouped_blocks(path) -> list:
    """Read-only font-size grouping of a deck's text layer: a flat list of
    {page (1-based), size (rounded pt), text} groups, page order then in-page
    size insertion order. This is the EXACT grouping best_description_in_deck
    scores over, factored out so the heuristic and the LLM manifest hint share
    ONE code path (the body paragraph separates cleanly from big ALL-CAPS
    callouts, drive-time tables and the legal footer). Boilerplate is NOT
    pre-filtered here (the LLM judges; the heuristic filters downstream).
    Returns [] wherever the text-layout ('dict') engine is unavailable (e.g.
    the pdfplumber shim) - so a raster/textless deck honestly emits no blocks."""
    try:
        doc = fitz.open(path)
    except Exception:
        return []
    out: list = []
    try:
        for pno in range(doc.page_count):
            try:
                blocks = doc.load_page(pno).get_text("dict").get("blocks", [])
            except Exception:
                continue
            runs: dict = {}
            for blk in blocks:
                for ln in blk.get("lines", []):
                    spans = ln.get("spans", [])
                    txt = "".join(s.get("text", "") for s in spans).strip()
                    if not txt:
                        continue
                    size = round(max((s.get("size", 0) for s in spans), default=0))
                    runs.setdefault(size, []).append(txt)
            for size, lines in runs.items():
                out.append({"page": pno + 1, "size": size, "text": " ".join(lines)})
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return out


def best_description_in_deck(path) -> tuple:
    """(description, page_no) of the deck's best property-description paragraph, or
    (None, None). Degrades to (None, None) wherever the text-layout ('dict') engine is
    unavailable (e.g. the pdfplumber shim) - an honest absence, never invented.
    Scores the font_grouped_blocks groups; page_no is 0-based (the locator adds +1)."""
    best = None
    for grp in font_grouped_blocks(path):
        pno = grp["page"] - 1  # font_grouped_blocks is 1-based; best keeps the legacy 0-based page
        txt = _desc_anchor(_desc_clean(grp["text"]))
        if len(txt) < 120 or txt.count(". ") < 1 or _DESC_BAD.search(txt):
            continue
        words = txt.split()
        if sum(1 for w in words if w[:1].islower()) / max(len(words), 1) < 0.5:
            continue
        score = len(txt) + (300 if _DESC_GOOD.search(txt) else 0) + max(0, 10 - pno) * 25
        if best is None or score > best[0]:
            best = (score, pno, _desc_cap(txt))
    if best:
        return N.clean_value(best[2]), best[1]
    return None, None


def extract(path: Path, region: str, country: str) -> list[dict]:
    try:  # an encrypted / corrupt / 0-byte PDF must NEVER emit a raw traceback - return
        # no records; run.py classifies the file and surfaces it in the Gaps Report
        doc = fitz.open(path)
    except Exception:
        return []

    def _page_text(pno: int) -> str:
        try:  # one damaged page object must not kill the whole deck
            return doc[pno].get_text()
        except Exception:
            return ""

    page0 = _page_text(0)
    toc_names = parse_toc(page0)
    has_toc = _is_toc_page(page0, toc_names)
    start = 1 if has_toc else 0

    pages = [(pno, _page_text(pno)) for pno in range(start, doc.page_count)]
    pages = [(pno, t) for pno, t in pages if t.strip()]

    # OWN-LINE path (spec-sheet decks): a property page carries >=2 own-line labels
    # in ANY language.
    own = [(pno, t) for pno, t in pages if len(_find_labels(t)) >= 2]
    if own:
        records = []
        # TOC entry k -> the k-th PROPERTY page (positional), NOT page start+k: one
        # text-less divider page would otherwise shift every later park name by one,
        # breaking dedupe keys and G-trace locators for the rest of the deck.
        for k, (pno, text) in enumerate(own):
            park = toc_names[k] if (has_toc and k < len(toc_names)) else None
            rec = parse_property_page(text, park, region, country, Path(path).name, pno)
            # P2-2: a coreless own-line record (e.g. a column-order garble under the
            # pdfplumber shim that mis-binds 'city: Clear height') must FALL to vision,
            # never ship a junk card - mirrors the inline path's guard. A TOC-named
            # entry is kept (the name IS its core identity).
            if _has_core(rec) or (has_toc and k < len(toc_names)):
                _apply_link_coords(doc, pno, rec)
                records.append(rec)
        doc.close()
        return records

    # INLINE fallback (only when NO page has own-line labels - e.g. an inline
    # "Label value" deck): parse same-line pairs. A page with <2 inline labels
    # (e.g. image-only) yields nothing and needs the vision fallback (gap upstream).
    records = []
    for pno, text in pages:
        if len(_find_inline_labels(text)) >= 2:
            rec = parse_property_page(text, None, region, country, Path(path).name, pno)
            if _has_core(rec):  # else it is a coreless spec-only page -> vision fallback
                _apply_link_coords(doc, pno, rec)
                records.append(rec)
    doc.close()
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--region", required=True)
    ap.add_argument("--country", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    recs = extract(Path(args.pdf), args.region, args.country)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.out:
        Path(args.out).write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK {len(recs)} records -> {args.out}")
    else:
        print(json.dumps(recs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
