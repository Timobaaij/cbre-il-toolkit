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
    """True if a value is an explicit/effective unknown (multilingual)."""
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

_SQFT_RX = re.compile(r"sq\.?\s*ft|sqft|\bft2\b|ft²|square\s+f[eo]+t|\bpsf\b", re.I)
_SQM_RX = re.compile(r"sq\.?\s*m\b|sqm|\bm2\b|m²|square\s+met", re.I)
_ACRE_RX = re.compile(r"\bacres?\b", re.I)
_HA_RX = re.compile(r"\bha\b|hectare", re.I)
_GBP_RX = re.compile(r"£|\bgbp\b", re.I)
_EUR_RX = re.compile(r"€|\beur\b(?!o\w)", re.I)


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


def area_band_for(unit: str | None) -> tuple[float, float]:
    """Plausibility band for a stored AREA magnitude in the given unit (the twin of
    rent_band_for). sq ft (and acres, which are stored as sq ft) -> (3,000, 6,500,000);
    sq m (and ha, stored as sq m) and any unknown/None unit -> (300, 600,000). A coarse,
    deliberately WIDE backstop: it catches only a gross unit error or a parse-garble, never
    a legitimate big logistics campus or a small urban unit. NEVER auto-converts."""
    if unit and "ft" in str(unit):
        return AREA_SQFT_MIN, AREA_SQFT_MAX
    return AREA_SQM_MIN, AREA_SQM_MAX


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
    rent_display(8.5, '£/sq ft/yr') -> '£8.5 / sq ft / year'; default €/sq m."""
    cur, per = "€", "sq m"
    if unit:
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
