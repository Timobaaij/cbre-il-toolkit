"""normalize.py - number / unit / text normalization shared by the extractors.

Brochures use European formatting (space or NBSP thousands, comma decimals):
  "39 471"  -> 39471      "62,4"  -> 62.4      "130,8" -> 130.8
  "50 000"  -> 50000      "1 234,5" -> 1234.5  "108,900" (US thousands) -> 108900
Ranges keep a display string and expose no single numeric.
"""
from __future__ import annotations

import re

_SPACES = [" ", " ", " ", " ", " ", " "]


def _strip_spaces(s: str) -> str:
    for sp in _SPACES:
        s = s.replace(sp, "")
    return s


# letters NFKD does NOT ASCII-fold (distinct letters, not base+diacritic) - folded
# explicitly so a gazetteer key built from one spelling matches a query in another
_CITY_FOLD = str.maketrans({"ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "Đ": "d",
                            "ß": "ss", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe",
                            "þ": "th", "Þ": "th", "ð": "d", "Ð": "d", "ı": "i"})


def _norm_city(s) -> str:
    """Normalise a city name for offline gazetteer matching: fold the letters NFKD misses
    (Ł, ø, đ, ß, æ ...), strip the remaining diacritics, lowercase, collapse whitespace.
    Used IDENTICALLY by build_cities_dataset.py (building the keys) and enrich._gazetteer_lookup
    (querying them), so a build-time key always matches a run-time lookup."""
    import unicodedata
    s = str(s or "").translate(_CITY_FOLD)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return " ".join(s.split())


def normalize_number(raw) -> float | None:
    """Parse one European/US formatted number to float. None if not parseable."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    m = re.search(r"-?\d[\d    .,]*\d|\d", s)
    if not m:
        return None
    # a range ("10-12", "5 to 7") has no single value - expose no number
    if is_range(s):
        return None
    tok = _strip_spaces(m.group(0))
    has_dot, has_comma = "." in tok, "," in tok
    try:
        if has_dot and has_comma:
            # European "1.234,5" -> dot thousands, comma decimal
            tok = tok.replace(".", "").replace(",", ".")
        elif has_comma:
            frac = tok.split(",")[-1]
            tok = tok.replace(",", ".") if len(frac) <= 2 else tok.replace(",", "")
        elif has_dot:
            if tok.count(".") > 1:
                tok = tok.replace(".", "")  # "1.234.567" multi-group EU thousands
            else:
                frac = tok.split(".")[-1]
                if len(frac) == 3 and len(tok.replace(".", "")) > 3:
                    tok = tok.replace(".", "")  # "108.900" thousands
        return float(tok)
    except ValueError:
        return None


def extract_first_number(s: str) -> float | None:
    return normalize_number(s)


def is_range(s: str) -> bool:
    return bool(re.search(r"\d\s*(?:[-–—]|to)\s*\d", str(s)))


def clean_value(s: str) -> str:
    """Collapse internal whitespace/newlines in an extracted value."""
    return re.sub(r"\s+", " ", str(s)).strip()


def looks_unknown(s) -> bool:
    """True if a value is an explicit/effective unknown (multilingual).

    FOUR "unknown" SETS EXIST IN THIS SKILL AND THEY DO NOT ALL AGREE. Recorded here deliberately,
    once, so nobody patches a FIFTH copy:

      1. this function (~30 forms, and it has `"?"` but NOT `"??"`)
      2. `deliver._is_tbd` = `looks_unknown(v) or str(v).strip() == "??"` (the Gaps Report)
      3. `_common.is_translatable_value`'s inline set - HAS `"??"`
      4. the template's JS `isAbsent` - HAS `"??"`

    Only 3 and 4 agree. **Do NOT widen THIS set to reconcile them.** It has ~24 call sites and feeds
    `_common.core_fill` -> `record_is_poor` -> **run.py's vision-routing probe**, so adding a form
    here changes WHICH INPUT FILES THE LLM IS ASKED TO READ - a judgement-surface change disguised
    as a sentinel tidy-up. That is why P1-3 widened `deliver._is_tbd` LOCALLY instead. If a caller
    needs a broader set, widen it at that caller, exactly as `deliver._is_tbd` does.
    """
    if s is None:
        return True
    t = str(s).strip().lower().rstrip(".")
    return t in {
        "", "tbd", "tbc", "—", "-", "n/a", "na", "n.a", "poa", "to be confirmed", "?",
        "a consultar", "consultar", "a convenir", "segun proyecto", "según proyecto", "sc",  # ES
        "a consulter", "à consulter", "nous consulter", "sur demande", "nc", "n.c",          # FR
        "auf anfrage", "k.a", "keine angabe",                                                 # DE
        "su richiesta", "da definire", "in trattativa",                                       # IT
        "op aanvraag", "n.v.t", "nvt",                                                         # NL
        "sob consulta",                                                                        # PT
        "do uzgodnienia", "do negocjacji",                                                     # PL
    }


def sentinel(s, field=None):
    """Map an unknown to the canonical sentinel. landPrice uses '—'; reit None; else 'tbd'."""
    if not looks_unknown(s):
        return clean_value(s)
    if field == "landPrice":
        return "—"
    if field == "reit":
        return None
    return "tbd"


# --- rent normalisation (shared by extract_pdf and merge) ---------------------- #
# Monthly markers as a REGEX tolerating the typeset-with-spaces forms brochures
# actually use ("€4.20 / sq m / month", "€4,20 / m2 / mes"); a missed marker ships
# a rent 12x too low. Plausibility band = EUR/m²/year.
MONTHLY_RX = re.compile(
    r"/\s*(?:month|monat|mese|maand|mies\w*|mês|mois|mes|mo)\b"
    r"|\bper\s+month\b|\bp\.\s?m\b|monatlich|mensile|mensual|mensuel|miesięcznie",
    re.IGNORECASE)
RENT_MIN, RENT_MAX = 1.5, 500.0

# --- area plausibility band + sq-ft-vs-sq-m magnitude cross-check ---------------- #
# The area twin of rent_band_for/rent_unit_band. DELIBERATELY WIDE: a band exists to
# catch a 10x unit error or a parse-garble (a stray digit / a run-together 9-digit
# cell / an eaten decimal), NOT to police real estate. A 300,000 sq m / 3.2M sq ft
# mega-campus AND a 350 sq m last-mile unit both pass. The sq ft band is the sq m band
# x ~10.764 (SQFT_PER_SQM) so a value converted between conventions never straddles the
# boundary. acres are converted to sq ft at parse, then the sq ft band applies; ha are
# converted to sq m, then the sq m band applies. NO clear-height band anywhere (real
# warehouse clear heights legitimately exceed 24 m). All constants are module-level
# next to RENT_MIN/MAX for one-line calibration tuning.
AREA_SQM_MIN, AREA_SQM_MAX = 300, 600_000
AREA_SQFT_MIN, AREA_SQFT_MAX = 3_000, 6_500_000
# PLOT (site) areas get their OWN ceiling (T1): a logistics PARK site of 60-180 ha
# (600,000-1,800,000 sq m) is routine - Euro Valley prints a 180 ha site, VGP Chorvatsky Grob
# a 950,000 sq m one - and the BUILDING ceiling above struck two correct printed plot areas
# (630,000 and 772,000 sq m) to tbd on a live run, each with a ledger row calling the source
# implausible. 10,000,000 sq m (1,000 ha) still catches the garble/unit-error class the band
# exists for; the sq ft twin is rounded ABOVE 10M x 10.764 so a converted value never
# straddles the boundary. The MIN stays the building MIN (a tiny plot is the same garble
# signal either way).
PLOT_SQM_MAX = 10_000_000
PLOT_SQFT_MAX = 110_000_000
# the unit-magnitude cross-check thresholds, set ABOVE/BELOW realistic warehouse mass
# so a normal sq m sheet (5k-50k) and a normal sq ft sheet (10k-500k) never trip:
AREA_SQM_SQFT_SUSPECT = 60_000   # a 'sq m' value above this is almost certainly sq ft
AREA_SQFT_SQM_SUSPECT = 4_000    # a 'sq ft' value below this is almost certainly sq m


# --- unit conventions ------------------------------------------------------------ #
# The SOURCE convention is KEPT (user rule): UK/imperial inputs (sq ft, £/sq ft/yr,
# acres) ship imperial; metric inputs ship metric. Units are never silently mixed -
# merge normalises a dataset to its DOMINANT area unit with the conversion recorded
# in provenance, and currency is NEVER converted (FX would be invention).
SQFT_PER_SQM = 10.7639
SQFT_PER_ACRE = 43560.0
SQM_PER_HA = 10000.0

# B58: every recognised area unit expressed in SQ FT, so any pair converts by one division.
# Crossing systems reuses SQFT_PER_SQM, so a field converted from acres can never be scaled on a
# different basis from one converted from sq m.
_AREA_IN_SQFT = {
    "sq ft": 1.0,
    "sq m": SQFT_PER_SQM,
    "acres": SQFT_PER_ACRE,
    "ha": SQM_PER_HA * SQFT_PER_SQM,
}


def area_factor(src, dst):
    """Multiply a figure in `src` units by this to get `dst`, or None if either is unrecognised.

    None is load-bearing: the caller must then NOT convert and NOT keep the figure under a unit it
    is not in. A guessed factor is precisely the 10.76x class of error this module exists to
    prevent, and an unknown unit is the one case where guessing is tempting."""
    a = _AREA_IN_SQFT.get(str(src or "").strip().lower())
    b = _AREA_IN_SQFT.get(str(dst or "").strip().lower())
    if not a or not b:
        return None
    return a / b

_SQFT_RX = re.compile(r"sq\.?\s*ft|sqft|\bft2\b|ft²|square\s+f[eo]+t|\bpsf\b", re.I)
_SQM_RX = re.compile(r"sq\.?\s*m\b|sqm|\bm2\b|m²|square\s+met", re.I)
_ACRE_RX = re.compile(r"\bacres?\b", re.I)
_HA_RX = re.compile(r"\bha\b|hectare", re.I)
_GBP_RX = re.compile(r"£|\bgbp\b", re.I)
_EUR_RX = re.compile(r"€|\beuros?\b|\beur\b", re.I)


def area_unit_of(text) -> str | None:
    """'sq ft' / 'sq m' / 'acres' / 'ha' when the text states one, else None."""
    t = str(text or "")
    if _SQFT_RX.search(t):
        return "sq ft"
    if _SQM_RX.search(t):
        return "sq m"
    if _ACRE_RX.search(t):
        return "acres"
    if _HA_RX.search(t):
        return "ha"
    return None


def currency_of(text) -> str | None:
    """'£' or '€' when the text states one, else None."""
    t = str(text or "")
    if _GBP_RX.search(t):
        return "£"
    if _EUR_RX.search(t):
        return "€"
    return None


def rent_band_for(per_area: str | None) -> tuple[float, float]:
    """Plausibility band for an ANNUAL headline rent in the given per-area
    convention. Per m² (default): 1.5-500. Per sq ft (UK industrial quoting,
    typically £4-30 psf): 0.5-60."""
    if per_area and "ft" in str(per_area):
        return 0.5, 60.0
    return RENT_MIN, RENT_MAX


def rent_unit_band(unit: str | None) -> tuple[float, float]:
    """rent_band_for, taking a 'cur/per/yr' unit string (e.g. '£/sq ft/yr')."""
    return rent_band_for(str(unit or "").split("/")[1] if unit and "/" in str(unit) else None)


def area_band_for(unit: str | None, field: str | None = None) -> tuple[float, float]:
    """Plausibility band for a stored AREA magnitude in the given unit (the twin of
    rent_band_for). sq ft (and acres, which are stored as sq ft) -> (3,000, 6,500,000);
    sq m (and ha, stored as sq m) and any unknown/None unit -> (300, 600,000). A coarse,
    deliberately WIDE backstop: it catches only a gross unit error or a parse-garble, never
    a legitimate big logistics campus or a small urban unit. NEVER auto-converts.

    `field` widens the CEILING for `plotArea` (T1): a SITE is not a building, and park
    sites of 60-180 ha are routine, so plots use PLOT_SQM_MAX / PLOT_SQFT_MAX instead of
    the building ceiling that struck two correct printed plot areas on a live run."""
    if unit and "ft" in str(unit):
        return AREA_SQFT_MIN, (PLOT_SQFT_MAX if field == "plotArea" else AREA_SQFT_MAX)
    return AREA_SQM_MIN, (PLOT_SQM_MAX if field == "plotArea" else AREA_SQM_MAX)


def area_magnitude_mismatch(value, unit: str | None) -> str | None:
    """The PRECISE sq-ft-vs-sq-m cross-check (the magnitude twin of the rent unit smell).
    Returns a one-line English note when the stored unit and the value's magnitude
    disagree by the ~10.764x conversion gap; else None. NEVER converts - the value is
    KEPT and the note is surfaced for the broker to confirm. Fires only OUTSIDE the
    overlap region (a value plausible in both units is never flagged):
      unit=='sq m' and value > 60,000  -> the value is in the sq-ft range
      unit=='sq ft' and value < 4,000  -> the value is in the sq-m range"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    u = str(unit or "")
    if u == "sq m" and value > AREA_SQM_SQFT_SUSPECT:
        return (f"unit stated sq m but {value:g} is in the sq-ft range (x{SQFT_PER_SQM:g}); "
                f"confirm with the landlord/agent - NOT auto-converted")
    if u == "sq ft" and value < AREA_SQFT_SQM_SUSPECT:
        return (f"unit stated sq ft but {value:g} is in the sq-m range (/{SQFT_PER_SQM:g}); "
                f"confirm with the landlord/agent - NOT auto-converted")
    return None


def rent_display(val: float, unit: str | None = None) -> str:
    """Canonical display string for an annual headline rent IN ITS OWN convention:
    rent_display(8.5, '£/sq ft/yr') -> '£8.5 / sq ft / year'.

    With NO unit, it no longer invents one. It used to default to EUR/sq m, so a UK deck
    quoting a bare `Rent: 7.25` shipped the card '€7.25 / sq m / year' - a specific claim
    about currency AND basis that no source made, and one a broker cannot tell from a
    sourced figure. Currency in particular is unrecoverable downstream: merge refuses to
    convert it because FX would be invention, so a wrong currency is wrong for good.

    The NUMBER is real and is kept - it is the unit that is unknown, so the honest render
    states exactly that. `tbd` would discard a datum the source did give us. (B06)"""
    if not unit:
        return f"{val:g} (unit not stated)"
    cur, per = "€", "sq m"
    parts = str(unit).split("/")
    if len(parts) >= 2:
        cur, per = parts[0] or cur, parts[1] or per
    return f"{cur}{val:g} / {per} / year"


def rent_unit_str(currency: str | None, per_area: str | None) -> str:
    """'cur/per/yr' unit string; unstated parts default to the €/sq m convention."""
    return f"{currency or '€'}/{per_area or 'sq m'}/yr"


def rent_unit_of_text(text) -> str | None:
    """Infer 'cur/per/yr' from a free-text rent quote when it states a currency
    or per-area unit ('£8.50 psf' -> '£/sq ft/yr'); None when neither is stated
    (the caller keeps its €/sq m default). A psf quote without a symbol defaults
    to £ - per-sq-ft quoting is the UK/IE convention."""
    cur, per = currency_of(text), area_unit_of(text)
    if cur is None and per is None:
        return None
    if cur is None and per == "sq ft":
        cur = "£"
    return rent_unit_str(cur, per if per in ("sq ft", "sq m") else None)


def header_value_suffix(header) -> str:
    """The unit a tracker column header states in parentheses, as a display
    suffix for a bare numeric value: 'Eaves (m)' -> ' m' (so the cell '15'
    ships as '15 m'). Currency-bearing parentheses ('(£ per sq ft)') return ''
    - rent columns carry their unit in rentUnit, not a string suffix."""
    m = re.search(r"\(([^)]{1,14})\)", str(header or ""))
    if not m:
        return ""
    content = m.group(1).strip()
    if not content or currency_of(content) or re.search(r"\d", content):
        return ""
    return f" {content}"


# --- country normalisation ------------------------------------------------------ #
# canonical.schema.json caps `country` at 2-3 chars, so a spelled-out name
# ("Spain", "España") written by an extraction/vision agent hard-fails
# validate-data. Formatting is merge's job, not a gate failure: map names (EN +
# native + common variants) to ISO-3166 alpha-2. Lookup is diacritic-insensitive.
_COUNTRY_ISO = {
    "spain": "ES", "espana": "ES", "espagne": "ES", "spanien": "ES",
    "portugal": "PT",
    "france": "FR", "francia": "FR", "frankreich": "FR",
    "germany": "DE", "deutschland": "DE", "alemania": "DE", "allemagne": "DE",
    "italy": "IT", "italia": "IT", "italie": "IT", "italien": "IT",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "nederland": "NL",
    "belgium": "BE", "belgique": "BE", "belgie": "BE", "belgien": "BE",
    "luxembourg": "LU", "luxemburg": "LU",
    "austria": "AT", "osterreich": "AT",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH", "svizzera": "CH",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "ireland": "IE", "eire": "IE",
    "poland": "PL", "polska": "PL", "polen": "PL",
    "czech republic": "CZ", "czechia": "CZ", "cesko": "CZ", "ceska republika": "CZ",
    "slovakia": "SK", "slovensko": "SK",
    "hungary": "HU", "magyarorszag": "HU", "ungarn": "HU",
    "romania": "RO",
    "bulgaria": "BG",
    "croatia": "HR", "hrvatska": "HR",
    "slovenia": "SI", "slovenija": "SI",
    "serbia": "RS", "srbija": "RS",
    "greece": "GR", "hellas": "GR",
    "denmark": "DK", "danmark": "DK",
    "sweden": "SE", "sverige": "SE",
    "norway": "NO", "norge": "NO",
    "finland": "FI", "suomi": "FI",
    "estonia": "EE", "eesti": "EE",
    "latvia": "LV", "latvija": "LV",
    "lithuania": "LT", "lietuva": "LT",
    "turkey": "TR", "turkiye": "TR",
    "ukraine": "UA", "ukraina": "UA",
    "morocco": "MA", "maroc": "MA", "marruecos": "MA",
    "united states": "US", "usa": "US",
    # remaining European coverage (continental + UK&I) - the genericity bar is
    # Europe-wide; these were unresolved >3-char names that hard-failed validate-data
    "iceland": "IS", "island": "IS",
    "cyprus": "CY", "kypros": "CY", "kibris": "CY", "κυπρος": "CY",
    "malta": "MT",
    "liechtenstein": "LI",
    "albania": "AL", "shqiperia": "AL",
    "north macedonia": "MK", "macedonia": "MK", "severna makedonija": "MK", "makedonija": "MK",
    "bosnia and herzegovina": "BA", "bosnia": "BA", "bosna i hercegovina": "BA",
    "montenegro": "ME", "crna gora": "ME",
    "kosovo": "XK", "kosova": "XK",
    "moldova": "MD",
    "belarus": "BY",
    "andorra": "AD",
    "monaco": "MC",
    "san marino": "SM",
    "ελλαδα": "GR",  # Greek-script Greece (a Latin 'ellada' will not catch the native spelling)
}


def country_iso(v) -> str:
    """Best-effort ISO-3166 alpha-2: valid 2-letter codes pass through uppercased,
    known names map, anything else returns unchanged (the gate then surfaces it)."""
    import unicodedata
    s = clean_value(v or "")
    if not s:
        return s
    if len(s) == 2 and s.isalpha():
        # UK and EL are common non-ISO 2-letter codes (UK->GB, EL=NUTS Greece->GR)
        return {"UK": "GB", "EL": "GR"}.get(s.upper(), s.upper())
    key = "".join(c for c in unicodedata.normalize("NFKD", s)
                  if not unicodedata.combining(c)).lower().strip(" .")
    return _COUNTRY_ISO.get(key, s)


# ---------------------------------------------------------------------------
# motorway: a card-sized locator, not a paragraph
# ---------------------------------------------------------------------------
MOTORWAY_MAX = 40

_MW_ROAD = r"(?:M\d+(?:/M\d+)?|A\d+(?:\(M\))?)"
_MW_JCT = r"(?:J|Jct|Junction)\s*(\d+[A-Za-z]?(?:\s*/\s*\d*[A-Za-z]?)?)"
# "Junction 18/18A M5" | "junction 17 of the M4" | "J19 M5" | "M4, J17" | "M4 Junction 15"
_MW_PAIRS = (
    re.compile(_MW_JCT + r"\s*(?:of\s+the\s+)?(" + _MW_ROAD + r")", re.I),
    re.compile(r"(" + _MW_ROAD + r")\s*[, ]\s*" + _MW_JCT, re.I),
)
_MW_DIST = re.compile(r"(\d+(?:\.\d+)?)\s*(miles?|mi|km)\b", re.I)
_MW_ADJACENT = re.compile(r"\badjacent\b", re.I)


def _nearest_match(pattern, text, anchor):
    """Return the `pattern` match in `text` whose span sits closest to `anchor` (a
    (start, end) char span), preferring the leftmost on a tie. `None` if `pattern` has
    no match at all. `anchor=None` falls back to the first match (today's behaviour),
    used when no road/junction span was found to anchor against.

    Why this exists: a clause naming more than one road ("...11 miles to the A14, and
    28 miles from Junction 19 of the M1") has more than one distance too, and the FIRST
    one in the clause is not necessarily the one printed next to the road that was
    actually matched. Anchoring to the matched span picks the distance the source
    itself associates with that road, not merely whichever comes first."""
    if anchor is None:
        return pattern.search(text)
    a_start, a_end = anchor
    best, best_gap = None, None
    for m in pattern.finditer(text):
        if m.end() <= a_start:
            gap = a_start - m.end()
        elif m.start() >= a_end:
            gap = m.start() - a_end
        else:
            gap = 0
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, m
    return best


def short_motorway(text, limit: int = MOTORWAY_MAX):
    """Condense a prose motorway description into a locator that fits a card.

    Returns (value, shortened). A value already within `limit` is returned untouched, so
    the common "M4, J17" case is a no-op and nothing is rewritten for the sake of it.

    Longer values are prose an agent wrote for a brochure, e.g. "Junction 18/18A M5 2 miles
    to the south; Junction 1 M49 4.5 miles to the north; M4/M5 interchange 10 miles to the
    north". Those read as a paragraph on a card and push the meta line onto three rows. The
    ROAD + JUNCTION + DISTANCE triples are what a broker actually scans, so they are pulled
    out in the order the source states them, reformatted as "M5 J18/18A 2 miles", and joined
    with "; " while they fit. Nothing is invented: every road, junction and distance in the
    output appears verbatim in the input, and if no pair can be parsed the text is cut at a
    word boundary instead, which is honest rather than clever.

    Distance selection is PROXIMITY-AWARE: when a clause mentions more than one distance
    figure, the one nearest the matched road/junction wins, not merely the first one in the
    clause - see `_nearest_match`. A clause with only one distance is unaffected (nearest and
    first are the same match), so every previously-pinned case is unchanged.

    The full sentence is never lost - it stays in the Source Ledger against this field.
    """
    if not isinstance(text, str):
        return text, False
    s = " ".join(text.split())
    if len(s) <= limit:
        return s, False

    seen, items = set(), []
    for clause in re.split(r"\s*[;.]\s+", s):
        if not clause.strip():
            continue
        road = jct = anchor = None
        for rx in _MW_PAIRS:
            m = rx.search(clause)
            if not m:
                continue
            g = m.groups()
            road, jct = (g[1], g[0]) if rx is _MW_PAIRS[0] else (g[0], g[1])
            anchor = m.span()
            break
        if road is None:
            m = re.search(_MW_ROAD, clause, re.I)
            road = m.group(0) if m else None
            anchor = m.span() if m else None
        if not road:
            continue
        part = road.upper()
        if jct:
            part += " J" + re.sub(r"\s*", "", jct).upper()
        md = _nearest_match(_MW_DIST, clause, anchor)
        if md:
            part += f" {md.group(1)} {md.group(2).lower()}"
        elif _MW_ADJACENT.search(clause):
            part += " adjacent"
        key = part.split()[0] + (jct or "")
        if key in seen:
            continue
        seen.add(key)
        items.append(part)

    if items:
        out = items[0]
        for nxt in items[1:]:
            if len(out) + 2 + len(nxt) > limit:
                break
            out += "; " + nxt
        if len(out) <= limit:
            return out, True

    cut = s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or s[:limit]).strip(), True
