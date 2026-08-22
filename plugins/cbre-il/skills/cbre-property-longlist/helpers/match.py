"""match.py - normalisation + conservative cross-source matching.

The match key is normalised City + Developer + Park. Two candidate records are
the SAME property when they come from DIFFERENT sources and their keys are
near-identical. Records from the same brochure are kept distinct (two pages with
the same park name are usually distinct buildings) - EXCEPT a true restatement
of one unit (identical key and identical/absent area, e.g. a summary-table row
plus that unit's detail page), which merges so the coverage gate's duplicate
check cannot block on the skill's own output. Asset (image) matching reuses the
same key.

Cross-source pairs also match by COORDINATE PROXIMITY (<= 300 m, no developer
disagreement, no material size conflict): an unknown city defeats every text
key, so a vision record with the real city never matched its city-less twin -
first-party pins decide it instead.

The ambiguous remainder is pre-filtered to a GREY set an LLM adjudicates. That
pre-filter deliberately does NOT treat a shared city as a signal on its own: a
longlist is usually one town, so the city distinguishes nothing there and made
the grey set quadratic in the skill's most common corpus. See
`_cross_source_grey`. (I9)

The pre-filter reads a record's identifying free text HOLISTICALLY, not field-by-
field. A broker's spreadsheet is human input: the scheme name lands in an "Address"
column as often as in "Park", and the party that owns the shed is written under
whichever header the broker had ("Landlord", "Developer", "Owner") - so requiring
park-to-park and developer-to-developer alignment hid real matches. Each record
contributes ONE bag of identity tokens (every park/address/scheme-ish field) and one
bag of party tokens (developer/landlord-ish fields); the filter looks for overlap
ACROSS the two bags in either direction. Place words (city, region, district,
country) are stripped from both, so the I9 rule - a shared town corroborates
nothing - still holds. See `_grey_bag`. (I12)
"""
from __future__ import annotations

import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normalize as N
try:
    from rapidfuzz import fuzz
except Exception:  # sandbox without rapidfuzz: difflib-backed shim (dedup still gated by coverage)
    from rapidfuzz_shim import fuzz


@lru_cache(maxsize=None)
def _tsr(key_a: str, key_b: str) -> float:
    # cached delegate: the identical (match_key, match_key) string pair recurs across the
    # O(n^2) dedupe / grey_pairs loops (fed twice within one pair_class, then re-fed on every
    # later pair touching the same records) - compute token_set_ratio once per pair (#30).
    return fuzz.token_set_ratio(key_a, key_b)


DEV_ALIASES = {
    "ctpark": "ctp", "ct park": "ctp", "ctp invest": "ctp",
    "panattoni park": "panattoni", "prologis park": "prologis",
    "vgp park": "vgp", "p3 logistic parks": "p3", "wing": "wing",
}
LEGAL = re.compile(r"\b(s\.?r\.?o|a\.?s|k\.?f\.?t|gmbh|spol|ltd|inc|se|nv|bv)\.?\b", re.I)
MATCH_THRESHOLD = 88


def strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


@lru_cache(maxsize=None)
def norm(s) -> str:
    s = strip_diacritics(str(s or "")).lower()
    s = LEGAL.sub("", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_dev(s) -> str:
    n = norm(s)
    for alias, canon in DEV_ALIASES.items():
        if n.startswith(alias):
            return canon
    return n.split(" ")[0] if n else n


def match_key(rec: dict) -> str:
    return f"{norm(rec.get('city'))}|{norm_dev(rec.get('developer'))}|{norm(rec.get('park'))}"


def _area(r):
    """The record's warehouse area as a bare NUMBER, whatever shape the source printed it in.

    `warehouseArea` is a STRING far more often than a float, BY DESIGN. The brochure-
    interpretation contract (reference/interpretation.md) is "write the value the way the
    source prints it": a dimensioned value keeps its unit inside the value, so a brochure
    record routinely carries '425,621 sq ft' or '700,000 SQ FT', not 425621.0. This used to
    test `isinstance(v, (int, float))` and returned None for every one of them, which
    silently disabled EVERY size check resting on it:

      * `_same_source_verdict` fell through to its "no area on either side" escape hatch and
        merged two GENUINELY DIFFERENT units of one multi-unit brochure into one property -
        the exact inverse of the skill's own "dedupe cross-source, NEVER within one brochure"
        guarantee, and it fired on essentially every same-brochure sibling pair, because ALL
        brochure-sourced areas are unit-suffixed strings;
      * `_area_pair` returned (None, None) - "footing unknown, refuse to compare" - for a
        pair a human reads at a glance, so the cross-source size veto and the size-agreement
        tests in `_cross_source_auto` went dark too.

    Delegates to `normalize.normalize_number`, the parser the extractors already share, so a
    comma/space/NBSP thousands group, a European decimal comma and a trailing unit read the
    same here as everywhere else - and a RANGE ('25,000 - 50,000 sq ft') still yields no
    number, because it honestly has none.

    UNITS ARE NOT THIS FUNCTION'S JOB - only the magnitude. Footing lives in each record's
    separate `areaUnit` field and is resolved by `_area_pair`; reading a unit out of the
    value here would silently compare a sq ft figure against a sq m one."""
    return N.normalize_number(r.get("warehouseArea"))


def _area_pair(a, b):
    """The two records' warehouse areas on a COMMON footing, or (None, None) when they
    cannot honestly be compared.

    The size test used to take the raw floats with NO unit attached - and merge does not
    convert units until AFTER dedupe. So a sq ft record and a sq m record of the SAME
    building sit 90.7% apart, tripped the >15% rule, and were classed `forbidden`; since
    `grey_pairs` EXCLUDES forbidden, the pair was never written to match_candidates.json and
    the LLM was never asked. That is the wrong-number path that actually fires. (The
    GIA-vs-net basis gap the item was filed for is typically 5-12%, i.e. UNDER the
    threshold - the weaker half.)

    Python may convert when both units are stated, or REFUSE to compare when the footing is
    unknown. It never decides whether two records are the same property: refusing to compare
    sends the pair to the LLM, which is exactly where that judgement belongs. (B10)"""
    aa, ba = _area(a), _area(b)
    if aa is None or ba is None:
        return None, None
    ua = str(a.get("areaUnit") or "").strip().lower()
    ub = str(b.get("areaUnit") or "").strip().lower()
    if ua == ub:                      # same stated unit, or neither states one
        return aa, ba
    if not ua or not ub:              # one silent side: the footing is UNKNOWN, so a gap
        return None, None             # is not evidence - do not block on it
    if {ua, ub} == {"sq ft", "sq m"}:
        return (aa, ba * (N.SQFT_PER_SQM if ua == "sq ft" else 1.0 / N.SQFT_PER_SQM))
    return None, None                 # an unrecognised unit pairing is not comparable


COORD_MERGE_KM = 0.3  # two pins this close are one site (a park spans ~100-250 m)


def _latlng(r):
    lat, lng = r.get("lat"), r.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) \
            and -90 <= lat <= 90 and -180 <= lng <= 180:
        return float(lat), float(lng)
    return None


def _km(a: tuple, b: tuple) -> float:
    import math
    lat1, lng1 = a
    lat2, lng2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _known_dev(r) -> str:
    """norm_dev, with unknown sentinels ('tbd', '??') treated as ABSENT - an
    unknown developer must never count as a disagreement (or an agreement)."""
    v = r.get("developer")
    return "" if N.looks_unknown(v) else norm_dev(v)


# generic words that carry no identity (every park has them) - a containment match
# must rest on DISTINCTIVE tokens, never on these alone
_GENERIC_PARK = {"park", "unit", "logistics", "industrial", "estate", "business",
                 "centre", "center", "point", "hub", "the", "phase", "scheme",
                 "warehouse", "distribution", "campus", "zone", "road", "lane", "way"}


def _distinctive_tokens(park) -> set:
    """park tokens minus generic words and bare numbers - the identity-bearing core."""
    return {t for t in norm(park).split() if t and t not in _GENERIC_PARK and not t.isdigit()}


def _grey_city_tokens(a: dict, b: dict) -> set:
    """The PAIR's city tokens (union, so the result is order-independent)."""
    return set(norm(a.get("city")).split()) | set(norm(b.get("city")).split())


def _grey_tokens(park, city_tokens: set) -> set:
    """`_distinctive_tokens` for the GREY pre-filter ONLY, with the pair's city tokens
    removed. A town name inside a park string is not identity: the tracker writes
    'EVO 169, Sallow Road, Corby NN17 5JX', so on a single-market longlist - the normal
    corpus for this skill - EVERY record carries the town as a "distinctive" token, and
    an unrelated pair looked corroborated by it. Measured on the Corby run: it was the
    only corroborating signal on 1 of 14 grey pairs, and it was spurious. (I9)

    DELIBERATELY NOT APPLIED IN `_cross_source_auto`'s containment branch, and that
    asymmetry is the safety property, not an oversight. Shrinking a set can only ever ADD
    subset relations: {alpha, corby} vs {alpha, beta} is neither-subset today, but strip
    'corby' and {alpha} <= {alpha, beta} - a NEW auto-merge, in the one tier that merges
    without asking anybody. Here every change can only move a pair grey -> 'no', which is
    the split direction, so the same strip is safe. The eval carries that fixture as a
    positive control.

    Since I12 the caller is `_grey_bag`, which feeds it ANY identifying free text (an
    address, a scheme name, a developer), not only a park, and passes the pair's full PLACE
    token set (city + region + district + country) as `city_tokens`. The parameter names are
    kept for call-site compatibility; the function only tokenises and subtracts."""
    return _distinctive_tokens(park) - city_tokens


# Place fields carry NO identity. The I9 argument for the city generalises to every one of
# them: a longlist is one market, so its records share the region, often the district, and
# always the country - a "shared" place token corroborates nothing and, as a signal, is
# exactly what made the grey set quadratic. `city` comes via `_grey_city_tokens`.
_PLACE_FIELDS_EXTRA = ("region", "district", "country")


def _grey_place_tokens(a: dict, b: dict) -> set:
    """The PAIR's PLACE tokens: `_grey_city_tokens` widened with region / district /
    country, unioned over BOTH records so the result is order-independent. This is the set
    the GREY bags are stripped against. A superset can only SHRINK a bag, i.e. move a pair
    grey -> 'no' - the split direction, which is always the safe one. (I12)"""
    out = set(_grey_city_tokens(a, b))
    for r in (a, b):
        for f in _PLACE_FIELDS_EXTRA:
            v = r.get(f)
            if isinstance(v, str) and v.strip():
                out |= {t for t in norm(v).split() if t}
    return out


# The free text a record is IDENTIFIED by - a scheme / estate / street / building name - in
# WHATEVER field the extractor happened to bind it to. `record_schema.json` is deliberately
# open (`additionalProperties: true`), and a broker's own headers are messier still: the
# scheme name arrives under "Address" as often as under "Park". So this is an OPEN list of
# the names actually in use across the pipeline (merge._IDENTITY_NAME_FIELDS,
# gate_runner.PROV_ADVISE_FIELDS, the canonical schema) plus the obvious camelCase variants.
# Adding a name here can only WIDEN the grey tier - never auto, never forbidden - so extend
# it freely when a corpus shows a new one.
_GREY_IDENT_FIELDS = ("park", "address", "addressLine", "addressLine1", "street",
                      "postcode", "postalCode", "name", "propertyName", "scheme",
                      "schemeName", "estate", "site", "siteName", "building",
                      "buildingName", "unit", "unitName")

# The PARTIES a record names. A party is identity too, but a WEAKER one - a developer builds
# many sheds in one market - so a party token only ever counts INSIDE the same known city
# (see `_cross_source_grey`). `landlord` is here because the roles are routinely written into
# each other's column by hand, and because an asset sale or rebrand leaves the SAME building
# with a different party name on each side: that is a question for the adjudicator, not a
# reason to hide the pair.
_GREY_PARTY_FIELDS = ("developer", "landlord", "owner", "assetManager", "freeholder")

# GREY-ONLY extra stop-words. Once ADDRESS text and PARTY names join the bag, street
# furniture, compass words and corporate boilerplate would manufacture corroboration out of
# nothing: two unrelated sheds on two different roads must not read as a match because both
# addresses say "north", and two different owners must not link through the word
# "management".
#
# DELIBERATELY NOT FOLDED INTO `_GENERIC_PARK`, and that asymmetry is the safety property.
# `_GENERIC_PARK` feeds `_distinctive_tokens`, which `_cross_source_auto`'s containment
# branch reads, and shrinking a token set there can only ADD subset relations - a NEW
# auto-merge, in the one tier that merges without asking anybody. Applied here, a smaller bag
# can only move a pair grey -> 'no', the split direction. (Same argument as `_grey_tokens`.)
_GREY_GENERIC_EXTRA = {
    # street furniture
    "street", "avenue", "close", "crescent", "gardens", "square", "terrace", "row",
    "drive", "court", "place", "boulevard", "parade", "circus", "walk",
    # compass / relative position
    "north", "south", "east", "west", "northern", "southern", "eastern", "western",
    "upper", "lower",
    # corporate boilerplate in a party name
    "group", "holdings", "partners", "partnership", "capital", "management", "managers",
    "investments", "investment", "properties", "property", "developments", "ventures",
    "trust", "fund", "funds", "assets", "asset", "real", "international", "global",
    "european", "europe",
    # generic building/plot words an address or a unit name adds
    "building", "buildings", "site", "sites", "units", "block", "plot", "floor",
    "works", "yard", "premises", "facility",
}

# A short letter-then-digits token: a UK postcode OUTWARD code ('nn17', 'mk45') or a road
# number ('a1', 'm6'). Both are AREA labels, not building identity - an outward code covers a
# whole town, which is the shared-city problem wearing a different hat, and it is exactly how
# address text would re-create the I9 quadratic blowup. The INWARD half ('5jx') starts with a
# digit, does not match, and is kept: it narrows to a handful of addresses and is real
# evidence. 'mk450' (three digits) does not match either - a scheme name survives.
_CODEISH = re.compile(r"^[a-z]{1,2}\d{1,2}[a-z]?$")


def _grey_bag(rec: dict, fields: tuple, place_tokens: set) -> set:
    """One record's DISTINCTIVE tokens gathered from `fields`, stripped of the pair's place
    tokens, the grey-only stop-words, single characters and area-code-shaped tokens.

    This is the whole of the I12 change: the pre-filter compares BAGS, so a token the broker
    typed into "Address" can corroborate a token the brochure printed as its scheme name, and
    a party name written under "Landlord" on one side can corroborate the "Developer" on the
    other. Which FIELD a name lives in is an accident of whoever built the spreadsheet; the
    name itself is the evidence.

    GREY-ONLY by construction: nothing in this function is reachable from `_cross_source_auto`
    or `_cross_source_forbidden`, so it can only ever move a pair 'no' -> grey (more LLM
    adjudication) or grey -> 'no' (an honest split the coverage dedupe gate catches). It can
    never merge anything on its own."""
    out: set = set()
    for f in fields:
        v = rec.get(f)
        if not isinstance(v, str) or not v.strip() or N.looks_unknown(v):
            continue
        out |= _grey_tokens(v, place_tokens)
    return {t for t in out
            if len(t) > 1 and t not in _GREY_GENERIC_EXTRA and not _CODEISH.match(t)}


def _same_source_verdict(a: dict, b: dict) -> bool:
    # Within one source, two pages with the same park name are usually distinct
    # buildings/phases - EXCEPT a true restatement of one unit (a summary-table
    # row plus that unit's detail page, very common in brochures): identical
    # normalised key AND the same area (or no area stated on either). Without
    # this, merge ships two records the coverage gate then hard-blocks as
    # duplicates - a contradiction no re-run can resolve. (Same-source pairs are
    # NEVER shown to the LLM - this is a structural, deterministic decision.)
    if match_key(a) != match_key(b):
        return False
    aa, ba = _area(a), _area(b)
    if aa is None and ba is None:
        # NO COMPARABLE NUMBER ON EITHER SIDE. Merging here is only honest when the area is
        # genuinely UNSTATED on both records. An area that IS stated but does not reduce to
        # one number - a range, '25,000 - 50,000 sq ft' - is not evidence of sameness, and
        # treating it as such is how this branch used to swallow whole multi-unit brochures
        # back when `_area` could not read a unit-suffixed string at all. Default to
        # different when unsure; only an IDENTICAL unparseable string is one unit restated.
        ra, rb = a.get("warehouseArea"), b.get("warehouseArea")
        if N.looks_unknown(ra) and N.looks_unknown(rb):
            return True  # indistinguishable restatement - keeping both adds nothing
        return N.clean_value(ra).casefold() == N.clean_value(rb).casefold()
    if aa and ba and abs(aa - ba) / max(aa, ba) <= 0.01:
        return True  # same unit stated twice (summary row + detail page)
    return False  # different/partial areas = distinct phases, keep both


def _cross_source_forbidden(a: dict, b: dict) -> bool:
    """The single HARD blocker a cross-source pair can NEVER overcome via an LLM 'same'
    verdict: a material size conflict (both warehouse areas present and differing by
    > 15%). This is what guarantees the catastrophic over-merge class is impossible by
    construction. Callers classify _cross_source_auto FIRST, so a pair the deterministic
    matcher already merges confidently is never re-labelled forbidden (backward-compat);
    forbidden therefore only ever applies to pairs the matcher would NOT have merged
    anyway - blocking them is a no-op offline and a hard veto on the LLM.

    A DEVELOPER DISAGREEMENT is NO LONGER a hard block. Landlord and developer are
    distinct fields now (extract_xlsx no longer conflates them), so a 'developer
    disagreement' is a genuine naming/JV/asset-sale signal, not a landlord masquerading
    as a developer. A cross-source dev-disagreement pair therefore falls through to the grey
    pre-filter (~2 km / a shared distinctive identity token / fuzzy 70-88 / a party name
    linking the two records in one city) and the LLM adjudicates it. _cross_source_auto is
    UNCHANGED - its coord-net auto
    path still REQUIRES developer agreement, so a disagreement goes to grey, never auto.

    The size test is FOOTING-AWARE (B10): a mixed-unit pair is converted before comparing,
    and an unknown footing refuses to block. `_cross_source_auto` deliberately keeps the raw
    comparison - it only ever DECLINES to auto-merge on an apparent size gap, which is the
    conservative direction, and a pair it declines now falls through to grey for the LLM
    instead of being vetoed here."""
    aa, ba = _area_pair(a, b)
    if aa and ba and abs(aa - ba) / max(aa, ba) > 0.15:
        return True
    return False


def _cross_source_auto(a: dict, b: dict) -> bool:
    """The deterministic matcher's confident TRUE paths - merged WITHOUT consulting the
    LLM (the easy questions). This is EXACTLY the set of cross-source pairs the matcher
    has always merged, so with `decisions=None` the verdict is byte-identical to before
    the LLM tier existed. Each path is a real same-property pairing it was patched to
    catch."""
    # COORDINATE NET: an unknown city defeats every text key (a vision record
    # carrying the real city never matched its city-less deterministic twin - both
    # shipped as cards). First-party pins are decisive instead: two records within
    # ~300 m, with no developer DISAGREEMENT and no material size conflict, are one
    # property. Distinct phases sharing one pin stay separate via the +/-15% area rule.
    la, lb = _latlng(a), _latlng(b)
    if la and lb and _km(la, lb) <= COORD_MERGE_KM:
        da, db = _known_dev(a), _known_dev(b)
        if not da or not db or da == db:
            ca, cb = _area(a), _area(b)
            if not (ca and cb and abs(ca - cb) / max(ca, cb) > 0.15):
                return True
    pa, pb = norm(a.get("park")), norm(b.get("park"))
    aa, ba = _area(a), _area(b)
    # CONTAINMENT (P0-2): a tracker's full postal park
    # ('Unit 1, Raven Park, Earlstrees Industrial Estate, Corby NN17 4XD') vs a
    # brochure scheme name ('Raven Park') scores ~49 on token_set_ratio and shipped
    # TWO cards for one property. When one park's DISTINCTIVE tokens are a subset of
    # the other's, with same known city, no developer disagreement, and area within
    # 5% (or absent), they are the same property. Distinct 'Alpha Park'/'Beta Park'
    # of one developer have DISJOINT distinctive tokens, so they never merge here.
    if pa and pb:
        da_, db_ = _distinctive_tokens(a.get("park")), _distinctive_tokens(b.get("park"))
        if da_ and db_ and (da_ <= db_ or db_ <= da_):
            ca_, cb_ = norm(a.get("city")), norm(b.get("city"))
            ka_, kb_ = _known_dev(a), _known_dev(b)
            area_ok = not (aa and ba) or abs(aa - ba) / max(aa, ba) <= 0.05
            if (ca_ == cb_ or not ca_ or not cb_) and (not ka_ or not kb_ or ka_ == kb_) and area_ok:
                return True
    # EXACTLY ONE park missing (e.g. a tracker row without a park name vs the
    # brochure record): the fuzzy key cannot decide this (the empty-park key scores
    # ~55, never merging), which shipped TWO cards for one property. Same city, same
    # developer AND near-identical area = the same property; anything less is not auto.
    # (The historical code RETURNED here for the one-park-missing case - it never fell
    # through to the fuzzy tail - so this branch is the only auto path when exactly one
    # park is missing; a False here is a definite non-merge, never the fuzzy tail.)
    if bool(pa) != bool(pb):
        # a SHARED UNKNOWN developer ('tbd'/'??') is neither agreement nor disagreement:
        # require BOTH sides KNOWN and equal, mirroring the coord-net/containment branches,
        # so two 'tbd'-developer records are not silently over-merged (audit S2-8).
        ka_m, kb_m = _known_dev(a), _known_dev(b)
        return (norm(a.get("city")) == norm(b.get("city")) and norm(a.get("city")) != ""
                and bool(ka_m) and bool(kb_m) and ka_m == kb_m
                and bool(aa and ba and abs(aa - ba) / max(aa, ba) <= 0.05))
    # SAME NAME ACROSS SOURCES: the historical fuzzy-key tail. Both parks present-or-
    # absent (the one-missing case returned above), key near-identical (>= 88), and no
    # material size conflict. This is the path that, in the pre-LLM matcher, merged a
    # same-park/same-key pair even across a developer disagreement - kept verbatim here
    # so offline behaviour is unchanged.
    if _tsr(match_key(a), match_key(b)) < MATCH_THRESHOLD:
        return False
    if aa and ba and abs(aa - ba) / max(aa, ba) > 0.15:
        return False
    return True


GREY_LOW = 70   # token-set floor below which a same-name pair is not even plausible
GREY_COORD_KM = 2.0  # two cross-source pins this close are plausibly one site
RECALL_KM = COORD_MERGE_KM  # the auto coord-net radius (a grey pin is wider, see GREY_COORD_KM)


def _cross_source_grey(a: dict, b: dict) -> bool:
    """RECALL pre-filter: a cross-source pair that is NOT forbidden and NOT auto, but is
    plausible enough to ask the LLM about - within ~2 km, OR sharing >= 1 distinctive
    IDENTITY token (any park/address/scheme-ish field on one side against any on the other,
    place words stripped), OR a borderline fuzzy key in [70, 88), OR - inside the same known
    city - a PARTY name (developer/landlord-ish) that links the two records in either
    direction.

    SAME CITY ALONE IS NOT A SIGNAL (I9). A property longlist is by definition usually one
    town or one market, so every record shares the city and it distinguishes nothing - yet
    it was a sufficient disjunct on its own, which made the grey set quadratic in exactly
    the skill's most common corpus. Measured on the Corby run (4 properties, tracker + 4
    brochures, reconstructed): 14 grey pairs, 13 of them resting on the town's name and
    nothing else, 28 LLM judgements, ZERO merges. Under this rule: 1 pair, 2 judgements,
    and the survivor is the one true cross-source match that `auto` misses (its two stated
    areas sit 9.2% apart, over the containment branch's 5% ceiling).

    FIELD NAMES ARE AN ACCIDENT; NAMES ARE THE EVIDENCE (I12). The filter used to insist on
    field-name alignment: park token against park token, and the developer only ever against
    the other side's PARK. Real broker input does not respect that. A tracker's free-text
    "Address" column carries the scheme name ('MPC2 Magna Park Corby, 100 Kettering Road,
    Weldon'); a column headed "Landlord" is bound to `developer`; an asset sale leaves the
    SAME building recorded as one owner on the tracker and its predecessor on the brochure.
    Nearly every row of a live 17-row tracker was the same physical property as one of 15
    brochures - confirmed later by exact warehouse-area matches - and most of those pairs
    were never even generated as candidates, so they shipped as duplicate cards.

    So each record now contributes TWO bags (`_grey_bag`):
      * an IDENTITY bag - every park/address/scheme/street/building-ish field it has;
      * a PARTY bag - every developer/landlord/owner-ish field it has;
    both stripped of the pair's place tokens, grey-only stop-words and area-code-shaped
    tokens. Overlap is then tested ACROSS the bags in BOTH directions.

    WHY IDENTITY OVERLAP IS UN-GATED AND PARTY OVERLAP IS CITY-GATED: a scheme/street name
    discriminates on its own, a party name does not. One developer building in one town is
    still a small subset of pairs; that same developer across a continent is most of them,
    which is the shared-city blowup wearing a different hat. So a party token only counts
    when both records state the SAME known city. The three party forms, all of which are
    needed:

      * BOTH developers known and equal under `norm_dev` (which also resolves the aliases,
        'CTPark' -> 'ctp') - keeps a same-city/same-developer/different-park pair visible
        (Apollo Court vs Mercury House, both Prologis: fuzzy 65.5, disjoint tokens, no
        coords, so it has no other signal);
      * a party token of ONE record appearing in the OTHER's IDENTITY bag, either direction.
        A brochure names the scheme 'Panattoni Park Doncaster' while the tracker carries the
        developer inside a marketing name or address. It rescues the live TEMU pair pinned by
        evals/source_authority_test.py (B48), where the tracker's park reads 'Panattoni
        Doncaster 770, Blyth Road, Harworth' and the brochure's DEVELOPER is Panattoni.
        Without it, a broker's disclosed city correction - made precisely so the two
        records could be compared - would have had no route to make the pair askable;
      * the two PARTY bags sharing a token. This is what catches a landlord written on one
        side against a developer on the other, and a party name that agrees on its
        distinctive word but not on its first ('Tritax' vs 'Tritax Symmetry'), which
        `norm_dev` equality misses.

    A party DISAGREEMENT is still not a signal by itself - two different owner names
    corroborate nothing, and the pair reaches the LLM (if at all) on its identity tokens,
    which is the honest route. That is the asset-sale case: the shared scheme name makes it
    askable, and the adjudicator decides what the differing owner means.

    No form needs an area guard: a pair whose areas differ by more than 15% is already
    `forbidden`, which `pair_class` tests before grey. A CLOSE area match was considered as
    a signal in its own right and rejected - sheds in one market are all similar sizes, so
    on the Corby corpus alone it would have re-admitted most of the pairs this rule removes.
    That is why >15% is a veto here and <15% is not evidence.

    THIS TIER IS THE ONLY ONE THAT MOVES. I9 could only move pairs grey -> 'no'; I12 mostly
    moves them 'no' -> grey (more identity fields, more cross-field forms) and, where the
    place strip widened or a stop-word/area-code token was dropped, grey -> 'no'. NEITHER
    direction can merge anything on its own: `auto` and `forbidden` are untouched, so with
    `decisions=None` - every offline path - the clustering verdict is byte-identical
    (`same_property` returns False for grey-without-a-decision and for 'no' alike). A wider
    grey set costs two LLM judgements per pair and nothing else; a narrower one risks an
    over-SPLIT, never an over-merge, and the coverage dedupe gate catches a wrong split.
    Asserted in evals/grey_prefilter_test.py.

    RESIDUAL, recorded not fixed: a single-developer single-city corpus still fires the
    party disjunct on every pair inside 15% area. Strictly better than firing on every
    pair regardless, and such a pair is worth asking about."""
    la, lb = _latlng(a), _latlng(b)
    if la and lb and _km(la, lb) <= GREY_COORD_KM:
        return True
    place = _grey_place_tokens(a, b)
    ia = _grey_bag(a, _GREY_IDENT_FIELDS, place)
    ib = _grey_bag(b, _GREY_IDENT_FIELDS, place)
    if ia & ib:
        return True
    score = _tsr(match_key(a), match_key(b))
    if GREY_LOW <= score < MATCH_THRESHOLD:
        return True
    ca, cb = norm(a.get("city")), norm(b.get("city"))
    if ca and cb and ca == cb:
        # an unknown developer ('tbd'/'??') is neither agreement nor evidence - `_known_dev`
        # returns "" for it and `_grey_bag` skips it, so every form below is inert on it by
        # construction
        ka, kb = _known_dev(a), _known_dev(b)
        if ka and kb and ka == kb:
            return True
        pa_ = _grey_bag(a, _GREY_PARTY_FIELDS, place)
        pb_ = _grey_bag(b, _GREY_PARTY_FIELDS, place)
        # the alias-canonical form too ('CTPark' -> 'ctp'), which is not a token of the
        # developer string and would otherwise be lost when the bags replaced it
        if (ka and ka in ib) or (kb and kb in ia):
            return True
        if (pa_ & ib) or (pb_ & ia) or (pa_ & pb_):
            return True
    return False


def pair_class(a: dict, b: dict) -> str:
    """Classify a record PAIR into one of four tiers:
      'auto'      - merge deterministically (today's confident TRUE paths)
      'grey'      - cross-source, not forbidden, not auto, but clears the recall
                    pre-filter: the genuinely ambiguous middle the LLM adjudicates.
                    A SHARED CITY ALONE DOES NOT CLEAR IT (I9) - it needs a pin
                    within ~2 km, a shared distinctive IDENTITY token (any
                    park/address/scheme-ish field of one record against any of the
                    other's, place words stripped - I12), a borderline fuzzy key, or
                    a PARTY name (developer/landlord-ish) linking the two records in
                    that city, in either direction
      'forbidden' - a HARD blocker (>15% size conflict / same-source differing area);
                    can NEVER merge, even on an LLM 'same' verdict. A developer
                    disagreement is NOT forbidden - it falls to 'grey' for the LLM.
      'no'        - everything else (definitely distinct, never shown to the LLM)
    Same-source pairs are classified 'auto' (a true restatement) or 'forbidden'
    (distinct phases) - never 'grey', so the LLM is only ever asked about cross-source
    pairs the deterministic gates could not resolve.

    Order matters: AUTO is checked before FORBIDDEN so a pair the deterministic matcher
    already merges confidently keeps merging (backward-compat); FORBIDDEN therefore only
    labels pairs the matcher would NOT have merged - making the blocker a no-op offline
    and a hard veto on an LLM 'same'."""
    if a.get("__meta", {}).get("source_file") == b.get("__meta", {}).get("source_file"):
        return "auto" if _same_source_verdict(a, b) else "forbidden"
    if _cross_source_auto(a, b):
        return "auto"
    if _cross_source_forbidden(a, b):
        return "forbidden"
    if _cross_source_grey(a, b):
        return "grey"
    return "no"


def pair_id(a: dict, b: dict) -> str:
    """A STABLE, ORDER-INDEPENDENT id for a record pair: a sha1 of the two records'
    (match_key + warehouse area), SORTED so pair_id(a, b) == pair_id(b, a). The id
    survives a re-run (it depends only on the records' identity, not their position),
    so a cached LLM verdict in work/match_decisions.json keyed by it is reproducible."""
    import hashlib

    def _sig(r):
        return f"{match_key(r)}|{_area(r)}"
    parts = sorted([_sig(a), _sig(b)])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()[:16]


def same_property(a: dict, b: dict, decisions: dict | None = None) -> bool:
    """Decide whether two records are the same physical property.

    The deterministic tiers are AUTHORITATIVE: a 'forbidden' pair is never merged
    (THE BLOCKER BEATS THE LLM - it returns False before `decisions` is even
    consulted), an 'auto' pair always merges, and a 'no' pair never merges. Only a
    'grey' pair (cross-source, ambiguous) consults `decisions[pair_id]`: 'same' ->
    merge, 'different'/absent -> distinct. With `decisions=None` a grey pair stays
    distinct - which is byte-identical to the historical matcher, because every pair it
    used to merge is now classed 'auto' (a grey pair is by construction NOT auto, so the
    old code returned False for it too)."""
    cls = pair_class(a, b)
    if cls == "auto":
        return True
    if cls == "forbidden":
        return False  # the structural blocker - an LLM 'same' can never override it
    if cls == "grey":
        if decisions:
            v = decisions.get(pair_id(a, b))
            if isinstance(v, dict):
                v = v.get("verdict")
            if v == "same":
                return True
        # 'different', an absent decision, or no decisions file: stay distinct. This is
        # the safe default (an over-split is caught by the coverage dedupe gate; an
        # over-merge silently destroys a property) AND it matches the historical verdict
        # (a grey pair is never 'auto', so the pre-LLM matcher returned False here too).
        return False
    return False  # 'no'


def grey_pairs(records: list[dict]) -> list[dict]:
    """Enumerate the cross-source GREY pairs an LLM should adjudicate. PURE PYTHON
    (no LLM): O(n^2) over records but recall-pre-filtered, returning only pairs whose
    pair_class is 'grey'. Each entry carries a stable order-independent `pair_id` and
    BOTH full records, ready for work/match_candidates.json. Deterministic: a fixed
    iteration order and a content-keyed id mean the same records always yield the same
    pair set and ids.

    The pre-filter is what keeps this small: it is the enumeration that is O(n^2), while
    the LLM cost is O(grey pairs). Before I9 a shared city alone qualified, so a
    single-market longlist put a QUADRATIC number of pairs in front of two LLM passes -
    a 4-property Corby corpus produced 14 pairs / 28 judgements / 0 merges. With the city
    no longer sufficient on its own, that corpus yields 1 - and still yields 1 after I12
    widened WHICH fields the surviving signals may be read from, because the place strip,
    the grey-only stop-words and the area-code filter keep the widening on real names."""
    out: list[dict] = []
    seen: set = set()
    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = records[i], records[j]
            if pair_class(a, b) != "grey":
                continue
            pid = pair_id(a, b)
            if pid in seen:
                continue  # identical-signature records: one representative pair is enough
            seen.add(pid)
            out.append({"pair_id": pid, "a_idx": i, "b_idx": j, "a": a, "b": b})
    return out


def dedupe(records: list[dict], decisions: dict | None = None) -> list[list[dict]]:
    """Group cross-source duplicates; return clusters (each a list to merge). When
    `decisions` is supplied (work/match_decisions.json, {pair_id: 'same'|'different'|
    {verdict: ...}}) it resolves the GREY pairs; the auto/forbidden tiers are unchanged
    and a forbidden pair is never merged regardless of the verdict. `decisions=None`
    (every offline path) is byte-identical to the historical behaviour.

    FORBIDDEN-AWARE (T1): a record may not join a cluster that already contains a member
    it is `forbidden` against. Single-link closure used to ignore this: with a PDF and a
    PPTX of one deck, pages 7/8 were correctly `forbidden` same-source pairs, but the
    cross-format links (an identical printed map pin + <=15% area gap -> `auto`) chained
    pdf7-pptx7 and pptx7-pdf8 into ONE cluster, fusing two distinct schemes and
    manufacturing 11 phantom source disagreements in a delivered ledger. The veto uses
    verdicts pair_class already computes, so a corpus with no forbidden edge is
    byte-identical; the failure direction becomes an over-SPLIT at worst, which the
    coverage dedupe gate catches, where the over-merge was silent."""
    clusters: list[list[dict]] = []
    for rec in records:
        placed = False
        for cl in clusters:
            if any(same_property(rec, other, decisions) for other in cl) \
                    and not any(pair_class(rec, other) == "forbidden" for other in cl):
                cl.append(rec)
                placed = True
                break
        if not placed:
            clusters.append([rec])
    return clusters
