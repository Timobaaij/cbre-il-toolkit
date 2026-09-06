"""match.py - normalisation + conservative cross-source matching.

The match key is normalised City + Developer + Park. Two candidate records are
the SAME property when they come from DIFFERENT sources and their keys are
near-identical. Records from the same brochure are kept distinct (two pages with
the same park name are usually distinct buildings) - EXCEPT a true restatement
of one unit (identical key and identical/absent area, e.g. a summary-table row
plus that unit's detail page), which merges so the coverage gate's duplicate
check cannot block on the skill's own output. Asset (image) matching reuses the
same key.

Cross-source pairs also match by COORDINATE PROXIMITY (<= 300 m, the SAME STATED
developer on both sides, no material size conflict): an unknown city defeats every
text key, so a vision record with the real city never matched its city-less twin -
first-party pins decide it instead. Two developer ABSENCES are not an agreement (nor
is a ONE-SIDED absence), and two differing stated postal codes are two addresses;
all three were once read as "no disagreement" and merged. The code veto is now ONE
guard at the TOP of `_cross_source_auto`, ahead of every branch, so it covers all
four auto paths instead of the two it originally reached. (A12, A12b, A13)

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


# The postal-code fields a record may carry. `record_schema.json` is deliberately open and a
# broker's own header decides the name, so this is an OPEN list: the canonical `postcode`
# plus the camelCase variant the extractors also bind. The FIRST stated one wins, so a
# record carrying both agrees with itself by construction. Extend it when a corpus shows a
# new name - a name added here can only ever BLOCK a merge, never create one.
_POSTCODE_FIELDS = ("postcode", "postalCode")


def _stated_postcode(r) -> str:
    """A record's postal code NORMALISED FOR EQUALITY ONLY, or "" when it states none.

    Whitespace is removed and the remainder upper-cased, so 'QX41 7ZP', 'qx417zp' and
    'QX41 7ZP' (a non-breaking space) are one code, and so are '482 15' and
    '48215'. NOTHING else is touched: a hyphen, a dash or an undivided run of digits is
    part of the code in one national format or another, and dropping any of it would fuse
    two codes the source printed as different.

    EVERY CODE QUOTED IN THIS READER'S DOCSTRINGS IS INVENTED, and the shapes are mixed on
    purpose. The paragraph below refuses country-specific parsing because the skill runs on
    any market - and illustrating that refusal with a REAL national code is exactly how the
    assumption gets read back in by the next maintainer, who sees one format quoted as THE
    example and writes a parser for it. evals/overmerge_guard_test.py keeps the same
    discipline and says so at the top.

    DELIBERATELY NOT PUT THROUGH `_CODEISH`, and that is the whole reason this is its own
    reader rather than a call into the pre-filter's tokeniser. That tokeniser DISCARDS the
    area half of a code ('qx41') on purpose, because an area label covers a whole town and
    corroborates nothing (the I9 argument). Comparing two records on the town-sized half of
    their codes would report two DIFFERENT buildings as agreeing - it would manufacture
    precisely the over-merge this reader exists to veto.

    NO COUNTRY-SPECIFIC PARSING, BY DESIGN. The skill runs on any market, so there is no one
    format to parse against: an outward/inward split is a fact about one country, five digits
    is a fact about several others, and a reader that assumed either would be silently wrong
    everywhere else. Equality of the whole normalised string is the only comparison that
    means the same thing in every format.

    A sentinel ('tbd', 'n/a', '-', ...) is ABSENCE, not a code. `looks_unknown` is the same
    reader `_known_dev` uses, so the module keeps ONE sentinel vocabulary rather than a fifth
    private copy (see the standing warning in `normalize.looks_unknown`).

    A NUMERIC cell is accepted, because a numeric-postal-code country's spreadsheet stores
    the code as a number and the reader hands back 1234 or 1234.0: skipping those would make
    this veto silently inert for that whole class of source, which is the same shape of bug
    as `_area` once returning None for every unit-suffixed string. A non-integral or
    non-finite float is not a postal code and is ignored rather than rounded into one."""
    for f in _POSTCODE_FIELDS:
        v = r.get(f)
        if v is None or isinstance(v, bool):
            continue
        if isinstance(v, float):
            if not v.is_integer():       # also False for inf/nan
                continue
            v = int(v)
        if isinstance(v, int):
            v = str(v)
        if not isinstance(v, str) or not v.strip() or N.looks_unknown(v):
            continue
        return re.sub(r"\s+", "", v).upper()
    return ""


def _postcode_conflict(a: dict, b: dict) -> bool:
    """True when BOTH records state a postal code and the two normalised codes are not equal.

    ABSENCE IS NEVER A DISAGREEMENT. One silent side, or a sentinel on either side, returns
    False. Most records in this skill's corpora state no code at all, and a country whose
    records carry no postal codes must be ENTIRELY unaffected by this veto - a guard that
    fires on missing data would block honest merges in every such market. This is the same
    both-sides-stated discipline `_area_pair` gives the size test and `_known_dev` gives the
    developer, for the same reason: a gap is only evidence when both sides actually spoke.

    A PREFIX RELATIONSHIP IS NOT TREATED AS AGREEMENT, and that is a decision rather than an
    omission. To read 'QX41' against 'QX417ZP' as agreement, the comparison would have to
    know which leading substring of a code is the area label IN THIS COUNTRY - exactly the
    country-specific parsing the reader above refuses to invent. In a format whose code is
    one undivided run of digits, a shared prefix is a coincidence and not containment at all.
    Since no prefix rule can be justified for every format, there is none: plain inequality.

    WHY A TYPO STILL BLOCKS. The case that argues the other way is ONE building quoted twice
    with a keying error - a transposed pair of characters, a dropped digit - which this reads
    as two codes and vetoes, splitting one property into two cards. That is accepted, because
    the two errors are not symmetrical:

      * the wrong SPLIT is VISIBLE, and IN THIS ONE SHAPE it also has a mechanical route
        back. The coverage dedupe gate fires only on two cards that are IDENTICAL on park,
        city, developer AND warehouse area - nothing less - and a typo-split pair is by
        construction exactly that: one building quoted twice, agreeing on every one of the
        four, differing only in the mis-keyed code. So the gate does hard-block it, and the
        repair is a one-character correction to a datum a human can check against the source
        page. DO NOT GENERALISE THAT SENTENCE. Every OTHER pair this veto demotes differs on
        at least one of the four (measured: a coordinate-net pair with 'tbd' locality fields
        against its named twin, and the eval's Alpha Court / Beta House fixture, are both
        non-equal), and the gate is blind to those - what makes the split the safe direction
        there is not a gate but that two similar-looking cards are IN FRONT OF THE READER.
        (Note the route is the gate and the source fix, NOT the adjudicator: this veto lands
        the pair in `forbidden`, and forbidden pairs are never enumerated for the LLM.
        Claiming adjudication as the safety net here would be false comfort.)
      * the wrong MERGE is invisible to the reader and unrecoverable. An auto-merged pair is
        never offered for adjudication - only grey pairs are, via `grey_pairs` - and the two
        properties' fields are already blended into one record with no route back: nothing in
        this pipeline can split a merged property after the fact. It is no longer true that
        NO gate looks for an over-merge: `gate_runner.py coverage` (A14b) blocks a property
        whose contributing records state two DIFFERENT postal codes. That is a narrow net and
        not a verifier - it needs the contributing records to state codes at all, so it is
        entirely inert in a market that quotes none, and it cannot see a fusion of records
        that state the same code or no code. It also asks the FINISHED dataset, so it catches
        a fusion this module let through rather than preventing one.

    Two stated codes that differ is the strongest two-addresses evidence this module has.
    Trading it away for a hypothetical typo would swap the one demotion this module makes
    that a gate can actually catch for an error nothing surfaces to the reader at all."""
    pa, pb = _stated_postcode(a), _stated_postcode(b)
    return bool(pa) and bool(pb) and pa != pb


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
    'EVO 169, Sallow Road, Corby QX41 7ZP', so on a single-market longlist - the normal
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

# A short letter-then-digits token: a postcode OUTWARD code ('qx41', 'qx52') or a road
# number ('x9', 'z4'). Both are AREA labels, not building identity - an outward code covers a
# whole town, which is the shared-city problem wearing a different hat, and it is exactly how
# address text would re-create the I9 quadratic blowup. The INWARD half ('7zp') starts with a
# digit, does not match, and is kept: it narrows to a handful of addresses and is real
# evidence. 'qx520' (three digits) does not match either - a scheme name survives.
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
    adjudication) or grey -> 'no' (a split, which ships as two visible cards). It can never
    merge anything on its own. The coverage dedupe gate is NOT the safety net for the second
    direction and this docstring used to say it was: that gate needs two cards identical in
    park, city, developer and area, which a pair the bag demotes essentially never is."""
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
    """The HARD blockers a cross-source pair can NEVER overcome via an LLM 'same' verdict:
    a material size conflict (both warehouse areas present and differing by > 15%), and a
    POSTAL-CODE DISAGREEMENT (both sides state a code and the two differ). These are what
    keep the catastrophic over-merge class out of the LLM's reach.
    Callers classify _cross_source_auto FIRST, so a pair the deterministic
    matcher already merges confidently is never re-labelled forbidden (backward-compat);
    forbidden therefore only ever applies to pairs the matcher would NOT have merged
    anyway - blocking them is a no-op offline and a hard veto on the LLM.

    A DEVELOPER DISAGREEMENT is NO LONGER a hard block. Landlord and developer are
    distinct fields now (extract_xlsx no longer conflates them), so a 'developer
    disagreement' is a genuine naming/JV/asset-sale signal, not a landlord masquerading
    as a developer. A cross-source dev-disagreement pair therefore falls through to the grey
    pre-filter (~2 km / a shared distinctive identity token / fuzzy 70-88 / a party name
    linking the two records in one city) and the LLM adjudicates it. Its two merging paths
    in `_cross_source_auto` REQUIRE the same developer STATED on both sides (A13), so a
    disagreement goes to grey, never auto.

    THE CODE HALF OF THIS FUNCTION IS NOW A BACKSTOP RATHER THAN THE PRIMARY VETO. Since
    A12b the identical test stands as ONE guard at the top of `_cross_source_auto`, so a
    code-conflicting pair is refused by every auto path before it can be claimed and then
    lands here. Keeping the test in both places is not duplication in the harmful sense: the
    tiers are independent predicates that callers other than `pair_class` do consult on their
    own (evals/grey_prefilter_test.py's `_old_class` calls both directly), so this blocker
    must hold for a pair that arrives here without the auto tier having run at all. The
    duplication that WAS harmful is gone: it was two per-branch call sites inside the auto
    tier, which is how two of the four auto paths came to have none.

    The size test is FOOTING-AWARE (B10): a mixed-unit pair is converted before comparing,
    and an unknown footing refuses to block. `_cross_source_auto` deliberately keeps the raw
    comparison - it only ever DECLINES to auto-merge on an apparent size gap, which is the
    conservative direction, and a pair it declines now falls through to grey for the LLM
    instead of being vetoed here."""
    aa, ba = _area_pair(a, b)
    if aa and ba and abs(aa - ba) / max(aa, ba) > 0.15:
        return True
    # THE SECOND HARD BLOCKER (A12): two DIFFERENT stated postal codes are two addresses.
    # Until this landed, the code was read by the recall pre-filter's identity tokens and
    # NOWHERE ELSE - no auto path and no forbidden path touched it - so two buildings on
    # separate estates a few hundred metres apart, with near-identical floor areas and no
    # contradicting party name, cleared the coordinate net and were FUSED into one record.
    # That is the failure class this module's docstrings call invisible to the READER and
    # unrecoverable (nothing in the pipeline can split a merged property afterwards). It is
    # no longer true that nothing looks for it at all: `gate_runner.py coverage` (A14b) now
    # blocks a property built from records that state two different codes - but only when
    # those records state codes, and only after the fusion has already happened, so it is a
    # net under this function rather than a substitute for it.
    #
    # THE SAME TEST GUARDS `_cross_source_auto`, because `pair_class` tests AUTO BEFORE
    # FORBIDDEN (see its docstring: a pair the deterministic matcher already merges must keep
    # merging, so the blocker is a no-op offline and a veto on the LLM). A blocker added ONLY
    # here would be a no-op for exactly the pairs that reach the auto tier - the pairs that
    # need blocking. It used to be repeated per merging BRANCH over there, two call sites
    # under a standing "IF YOU CHANGE ONE, CHANGE THE OTHER" warning, and the warning was
    # right to be worried: the two branches it reached were not all of them, and the other
    # two auto paths merged across differing codes for as long as that shape stood. A12b
    # replaced them with ONE guard at the top of that function, so the invariant "no auto
    # path can claim a code-conflicting pair" is now structural instead of per-branch.
    if _postcode_conflict(a, b):
        return True
    return False


def _cross_source_auto(a: dict, b: dict) -> bool:
    """The deterministic matcher's confident TRUE paths - merged WITHOUT consulting the
    LLM (the easy questions). Each path is a real same-property pairing it was patched to
    catch.

    NO LONGER "EXACTLY the set of cross-source pairs the matcher has always merged", and
    that sentence used to stand here: A12, A12b and A13 deliberately NARROWED these paths, so
    with `decisions=None` a pair with two differing stated postal codes, or without the
    developer stated on BOTH sides, now splits where it used to merge. The narrowing is
    one-directional (auto -> forbidden or grey, never the reverse), which is the over-SPLIT
    direction. Read the two cost notes below before calling that direction "safe": it is the
    better of two bad outcomes, not a free one.

    THE CODE VETO IS ONE GUARD, AT THE TOP, AHEAD OF EVERY BRANCH (A12b). A12 landed it in
    the coordinate-net and containment branches only, and `pair_class` tests auto BEFORE
    forbidden, so the ONE-PARK-MISSING branch and the FUZZY-KEY TAIL kept merging across two
    DIFFERENT stated codes - a near-identical match_key (same city, same developer, same park
    name) fused two unit codes on one park, and it fused at the CLUSTERING step, not merely
    at the tiering step. That was recorded here as a residual on the grounds that changing
    the fuzzy tail would move pairs offline runs merge. MEASURED TWO WAYS, that was false.
    Instrumenting this function for "auto says yes AND the codes conflict" and running the
    WHOLE eval suite logs exactly TWO pairs, and both are the fixtures written to pin the bug
    - no corpus pair, no clustering test, no downstream assertion. A second, exhaustive sweep
    of the tier's entire discriminator space (park equal / superset / disjoint / absent x city
    x developer stated-absent-differing x area x code absent-equal-differing-sentinel-numeric
    x pin near-far x same- and cross-source: 215,040 pairs) moves 1,760 of them, EVERY one
    with two differing stated codes, and every one claimed pre-fix by the one-park-missing
    branch or the fuzzy tail - never by a branch A12 had already guarded, which is arithmetic
    rather than luck, since those two branches tested the conflict themselves. So the veto now
    sits here, once, where no branch can be added around it - and the two call sites the old
    "IF YOU CHANGE ONE, CHANGE THE OTHER" warning guarded are gone, which removes the hazard
    that warning was describing.

    THE ACCEPTED COST OF THE CODE VETO, IN FULL. A pair this guard rejects lands in
    `forbidden`, and forbidden pairs are NEVER enumerated for adjudication - not even an
    explicit 'same' verdict can recover one, because `same_property` returns False before
    `decisions` is read. So there is no human rescue: the same building quoted with a
    unit-level code on one side and an estate-level code on the other becomes PERMANENTLY
    unmergeable, and it ships as two cards for the life of the project. That risk was already
    accepted on the coord-net and containment branches; this extends it to the other two, and
    it is HIGHER-probability on the fuzzy tail, where a near-identical key is stronger
    same-property evidence than a coordinate pin ever was. It is still the right call, for one
    reason only: an over-split ships two similar-looking cards that a human reader can SEE and
    query, while a fusion is offered to nobody, and until `gate_runner.py coverage` grew its
    A14b code check it was asked about by no gate either. Do not restate that as "the coverage
    dedupe gate catches the split" - see the note in `_postcode_conflict`, which measures why
    that is false for every demoted pair except an exact typo-split.

    THE DEVELOPER RULE IS WIDER THAN "TWO ABSENCES", AND THAT IS DELIBERATE. It was declared
    as "two absent developers no longer count as agreement"; what is implemented, on all
    three branches that read the party, is BOTH STATED AND EQUAL - which also demotes a
    ONE-SIDED absence. That is the more defensible rule (an absence corroborates nothing in
    either quantity) and it is kept. Its measured cost: a record whose locality fields are all
    unknown, pinned ~100 m from its named twin, is the founding incident the coordinate net
    was written for, and it now SPLITS offline. It remains grey, so an adjudicated 'same'
    merges it - but offline, with no decisions file, the deterministic matcher is the whole
    decision and that pair ships as two cards. No gate catches it: the two cards differ on
    park, city and developer, so the coverage dedupe key cannot match them. Pinned in
    evals/extract_test.py (the coord-net section) and evals/overmerge_guard_test.py."""
    # THE POSTAL-CODE VETO, ONCE, AHEAD OF EVERY BRANCH (A12b). Two stated codes that differ
    # are two addresses, and this is the ONLY place in this function that says so - by
    # construction no auto path can be written that bypasses it, because there is nothing to
    # bypass: the function has already returned. It sits here rather than per-branch because
    # per-branch is exactly how the hole existed. A12 put the test in the two branches below
    # and left the one-park-missing branch and the fuzzy tail unguarded; since `pair_class`
    # tests auto BEFORE forbidden, those two paths claimed the pair and the forbidden tier's
    # identical test never ran, so two DIFFERENT stated codes fused into ONE cluster.
    #
    # ABSENCE IS INERT (see `_postcode_conflict`): one silent side, a sentinel, or a market
    # that quotes no codes at all leaves this guard unable to fire, so nothing changes for
    # such a corpus. The cost when it DOES fire is real and is stated in the docstring above:
    # the pair goes to `forbidden`, where no adjudicated 'same' can rescue it.
    if _postcode_conflict(a, b):
        return False
    # COORDINATE NET: an unknown city defeats every text key (a vision record
    # carrying the real city never matched its city-less deterministic twin - both
    # shipped as cards). First-party pins are decisive instead: two records within
    # ~300 m, naming the SAME developer on BOTH sides, with no material size
    # conflict, are one property (the code veto above has already run). Distinct
    # phases sharing one pin stay separate via the +/-15% area rule.
    la, lb = _latlng(a), _latlng(b)
    if la and lb and _km(la, lb) <= COORD_MERGE_KM:
        da, db = _known_dev(a), _known_dev(b)
        # BOTH developers STATED and equal (A13). This read `not da or not db or da == db`,
        # so two ABSENCES - the ordinary shape of a tracker row against a brochure that never
        # names the party - counted as an agreement, and the pair merged on a pin and an area
        # alone. Two absences are not two agreeing developers; they are no evidence. The
        # correct shape already existed in the one-park-missing branch below (audit S2-8) and
        # this is that shape, applied here.
        #
        # `da and db` ALSO DEMOTES A ONE-SIDED ABSENCE, which is wider than A13 was declared
        # and is kept on purpose: one stated party corroborates nothing on its own either. The
        # cost is measured and is THIS branch's founding incident - a record with 'tbd' city,
        # park and developer, pinned ~100 m from its named twin, now SPLITS offline. It stays
        # grey, so an adjudicated 'same' still merges it; offline there is no adjudicator and
        # it ships as two cards.
        #
        # NO POSTAL-CODE DISAGREEMENT is no longer tested here: it is the single guard at the
        # top of this function (A12b), which is what finally closed the two auto paths that
        # never had it. A park spans 100-250 m, but so do two separate estates either side of
        # a boundary - the pin alone cannot tell them apart, and the stated codes are the only
        # field that can.
        #
        # Both tightenings move pairs auto -> forbidden or grey, i.e. towards an over-SPLIT.
        # THAT IS THE BETTER DIRECTION, NOT A COVERED ONE. The coverage dedupe gate fires only
        # on two cards identical in park, city, developer AND area, and a pair demoted here
        # differs on at least one - the measured example above differs on three - so the gate
        # cannot see it. What makes the split preferable is that its two cards are in front of
        # the reader, whereas a fusion is offered to nobody: an auto pair is never enumerated
        # for adjudication, and the only thing that looks for a fusion at all is the coverage
        # gate's A14b code check, which needs the contributing records to state codes.
        if da and db and da == db:
            ca, cb = _area(a), _area(b)
            if not (ca and cb and abs(ca - cb) / max(ca, cb) > 0.15):
                return True
    pa, pb = norm(a.get("park")), norm(b.get("park"))
    aa, ba = _area(a), _area(b)
    # CONTAINMENT (P0-2): a tracker's full postal park
    # ('Unit 1, Kestrel Reach, Halston Industrial Estate, Northport QX41 7ZP') vs a
    # brochure scheme name ('Kestrel Reach') scores ~49 on token_set_ratio and shipped
    # TWO cards for one property. When one park's DISTINCTIVE tokens are a subset of
    # the other's, with same known city, the SAME developer STATED on both sides, and
    # area within 5% (or absent), they are the same property (the code veto at the top
    # of this function has already run). Distinct 'Alpha Park'/'Beta Park' of one
    # developer have DISJOINT distinctive tokens, so they never merge here.
    if pa and pb:
        da_, db_ = _distinctive_tokens(a.get("park")), _distinctive_tokens(b.get("park"))
        if da_ and db_ and (da_ <= db_ or db_ <= da_):
            ca_, cb_ = norm(a.get("city")), norm(b.get("city"))
            ka_, kb_ = _known_dev(a), _known_dev(b)
            # `area_ok` KEEPS the absent-is-acceptable shape on purpose, and the difference
            # from the developer clause below is the point. An area here is a DISCRIMINATOR
            # used only to veto (both stated and >5% apart = distinct phases); an absent
            # figure cannot contradict anything, and demanding one would break the very
            # incident this branch was written for, where the BROCHURE side states a scheme
            # name and NO area. A developer, by contrast, was being read as the branch's
            # party CORROBORATION, so an absence there is a merge on nothing.
            area_ok = not (aa and ba) or abs(aa - ba) / max(aa, ba) <= 0.05
            # BOTH developers STATED and equal (A13), replacing
            # `not ka_ or not kb_ or ka_ == kb_`, which let two ABSENCES pass as agreement -
            # so a pair whose only real evidence was a token subset and a shared city could
            # auto-merge with no party evidence at all. Same shape as the one-park-missing
            # branch below (audit S2-8). `ka_ and kb_` demotes a ONE-SIDED absence too, which
            # is wider than A13 was declared; kept, for the reason given in the docstring, and
            # its cost is that the brochure-names-no-party shape now needs the adjudicator.
            #
            # THE POSTAL-CODE VETO IS NOT REPEATED HERE any more: it is the single guard at
            # the top of this function (A12b). A containment relation is satisfied by a short
            # scheme name sitting inside a LONGER address string, and two neighbouring estates
            # can share both the town and the scheme's first word - the stated codes are then
            # the only field that separates them, which is why this branch was one of the two
            # A12 originally reached.
            #
            # These tightenings move pairs auto -> forbidden or grey: the over-SPLIT
            # direction. A HUMAN can undo it only while the pair is still GREY - a code
            # conflict sends it to `forbidden` instead, where no verdict reaches it. And the
            # coverage dedupe gate does NOT block on it: that gate needs park, city, developer
            # and area all identical, and the demoted pair here differs on the park by
            # construction (containment means one park string CONTAINS the other, so the two
            # strings are not equal). The honest claim is that two cards are visible to the
            # reader and a fusion is not.
            if (ca_ == cb_ or not ca_ or not cb_) and ka_ and kb_ and ka_ == kb_ \
                    and area_ok:
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
        #
        # ONE OF THE TWO PATHS A12 MISSED. This branch had the developer shape right from
        # audit S2-8 and was cited as the model the other two branches were corrected TO -
        # which is precisely why nobody noticed it had no code test. A tracker row with no
        # park name, against a brochure naming the park, agreeing on city, developer and area
        # to within 5%, merged across two DIFFERENT stated codes: the empty-park side is
        # commonly a unit-level tracker row, so the codes disagreeing at unit level is the
        # ordinary case here, not an exotic one. Now vetoed by the guard at the top (A12b).
        ka_m, kb_m = _known_dev(a), _known_dev(b)
        return (norm(a.get("city")) == norm(b.get("city")) and norm(a.get("city")) != ""
                and bool(ka_m) and bool(kb_m) and ka_m == kb_m
                and bool(aa and ba and abs(aa - ba) / max(aa, ba) <= 0.05))
    # SAME NAME ACROSS SOURCES: the historical fuzzy-key tail. Both parks present-or-
    # absent (the one-missing case returned above), key near-identical (>= 88), and no
    # material size conflict. This is the path that, in the pre-LLM matcher, merged a
    # same-park/same-key pair even across a developer disagreement.
    #
    # THE OTHER PATH A12 MISSED, AND THE WORST OF THE FOUR. Its body is still the historical
    # matcher verbatim - but "kept verbatim so offline behaviour is unchanged" is no longer
    # the whole truth, and the sentence that claimed it has been removed: the code guard at
    # the top of this function reaches this tail too (A12b). It had to. A key of
    # city|developer|park scoring >= 88 is the STRONGEST same-property evidence this module
    # computes, so this is where a differing unit code is most likely to be the only thing
    # separating two units of ONE park - two records that agree on the park name, the town and
    # the party, and disagree only on the address that identifies the building. Measured over
    # the whole eval corpus, closing it moves exactly one pair: the fixture written to pin the
    # bug (evals/overmerge_guard_test.py, section 6b, now inverted). The trade is the one in
    # the docstring: this tail's demotions land in `forbidden`, beyond any 'same' verdict.
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
    over-SPLIT, never an over-merge. That is the better risk because a split ships two cards
    the reader can see, NOT because a gate catches it - measured, the coverage dedupe gate
    (identical park + city + developer + area) matches none of the pairs this filter demotes,
    which are by construction pairs whose names did not align. Asserted in
    evals/grey_prefilter_test.py.

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
      'forbidden' - a HARD blocker (>15% size conflict / two differing stated postal
                    codes / same-source differing area); can NEVER merge, even on an
                    LLM 'same' verdict. A developer disagreement is NOT forbidden - it
                    falls to 'grey' for the LLM.
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


# --------------------------------------------------------------------------- #
# A MATERIAL IDENTITY DISAGREEMENT - which AUTO pairs are worth offering to a human.
#
# THE HOLE THIS EXISTS FOR. `grey_pairs` enumerates the ambiguous middle for adjudication and
# nothing enumerates the auto tier, so an auto merge is offered to nobody - the failure this
# module's docstrings call invisible to the reader and unrecoverable, because nothing in the
# pipeline can split a merged property afterwards. The postal-code veto at the top of
# `_cross_source_auto` closed the worst case; it did not close the class. The fuzzy-key tail
# merges on `city|developer|park` scoring >= 88 with no material size gap, and that key CANNOT
# SEE a unit name, a building name or a street - so two units of one park, or one building
# against its neighbour on a shared scheme, still fuse without anyone being asked.
#
# WHY THE SET IS RESTRICTED, AND RESTRICTED HARD. An adjudication exit that lists every auto
# pair is noise, and noise is WORSE than not asking: it costs a round-trip per run and it
# trains the reader to skim the pairs that are precise, which is the same argument that
# deleted clarify's page-count producer. So a pair is offered ONLY when the two records BOTH
# SPEAK in one identity class and DISAGREE in it.
#
# WHAT COUNTS, and each rule is the same rule this module already applies elsewhere:
#   * BOTH SIDES MUST HAVE SPOKEN. A one-sided absence is not a disagreement - the discipline
#     `_postcode_conflict` gives the code, `_area_pair` gives the size and `_known_dev` gives
#     the party, for the reason all three give: a gap is only evidence when both sides spoke.
#     Most records in these corpora state most of these fields nowhere at all.
#   * DISJOINT, NOT UNEQUAL. Agreement is a shared distinctive token, so 'Kestrel Reach'
#     against 'Unit 1, Kestrel Reach, Halston Industrial Estate' AGREES - which it must, since
#     containment is precisely what the auto tier's containment branch merges on. Only a bag
#     with nothing in common is a disagreement: 'Alpha Court' against 'Beta House'.
#   * BY CLASS, NOT BY FIELD, and the classes pool their fields for I12's reason - which field
#     a name lives in is an accident of whoever built the spreadsheet, so a scheme name typed
#     into "Address" corroborates the brochure's "Park". Pooling also keeps precision up: a
#     pair naming the same developer and two different landlords still SHARES a party token,
#     and is not offered.
#   * A NAME IS COMPARED ON ITS DISTINCTIVE TOKENS, A DESIGNATOR ON THE WHOLE THING, and
#     that split is the one non-obvious decision here. A scheme, a party and a street are
#     identified by a distinctive NAME, so `_grey_bag`'s tokens are the right evidence: place
#     words, grey stop-words, single characters and area-code-shaped tokens are stripped (a
#     shared town corroborates nothing - I9/I12; 'qx41' covers a whole town), which also means
#     'Sallow Road' and 'Sallow Rd' still agree. A UNIT is identified by an ENUMERATOR - a
#     generic word plus a number - and `_grey_bag` is STRUCTURALLY BLIND to it: 'Unit 1' and
#     'Unit 7' both reduce to the empty set, because 'unit' is a generic word and a bare digit
#     is dropped. That blindness is exactly the hole the fuzzy tail falls through, since
#     `city|developer|park` cannot see a unit either, so this class is compared on the whole
#     place-stripped designator with its DIGITS KEPT, and a token-SUBSET relation is what
#     counts as agreement ('Unit 1' inside 'Unit 1, Kestrel Reach' agrees; 'Unit 1' against
#     'Unit 10' does not, which plain substring matching would have got wrong).
#
# WHAT IS DELIBERATELY NOT A CLASS:
#   * THE POSTAL CODE. Two differing stated codes send the pair to `forbidden` via the single
#     guard at the top of `_cross_source_auto`, so such a pair is never 'auto' and can never
#     reach here. Listing it would be dead code AND would read as though the veto were one
#     opinion among several, which it is not.
#   * THE AREA. The auto tier's own branches already veto a material size gap (>15%, or >5% on
#     the containment and one-park-missing branches), so anything that survives to 'auto'
#     agrees on size within the tier's own tolerance. Re-testing it would surface pairs the
#     matcher has already judged on exactly that evidence.
#   * CITY / REGION / DISTRICT / COUNTRY. A place carries no identity (I9), a longlist is one
#     market, and an unknown city is the founding case the coordinate net exists for.
_IDENT_CLASSES = (
    # the PARTIES - a developer, landlord, owner, asset manager or freeholder
    ("party", _GREY_PARTY_FIELDS),
    # the SCHEME the property is sold as
    ("name", ("park", "name", "propertyName", "scheme", "schemeName", "estate",
              "site", "siteName")),
    # the STREET it stands on
    ("street", ("address", "addressLine", "addressLine1", "street")),
)
# WHICH BUILDING on the scheme - compared as a DESIGNATOR, not as a name (see above). This is
# the class `city|developer|park` is blind to, and therefore the one that lets the fuzzy tail
# fuse two units of one park into a single card while the other unit drops off the longlist.
_IDENT_DESIGNATOR_FIELDS = ("unit", "unitName", "building", "buildingName")


def _designators(rec: dict, fields: tuple, place_tokens: set) -> list:
    """Each STATED designator in `fields` as a place-stripped token set, DIGITS KEPT.

    A sentinel is absence, the same reader (`normalize.looks_unknown`) the rest of this module
    uses, so 'tbd' is silence rather than a value that disagrees with everything."""
    out = []
    for f in fields:
        v = rec.get(f)
        if v is None or isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            v = f"{v:g}" if isinstance(v, float) else str(v)
        if not isinstance(v, str) or not v.strip() or N.looks_unknown(v):
            continue
        toks = {t for t in norm(v).split() if t} - place_tokens
        if toks:
            out.append(toks)
    return out


def _designators_disagree(a_vals: list, b_vals: list) -> bool:
    """True when both sides state a designator and NO pair of them is in a subset relation.

    Subset rather than equality, so a designator quoted inside a longer address string still
    agrees - which it must, since that is the ordinary tracker-row-against-brochure shape the
    auto tier's containment branch merges on."""
    if not a_vals or not b_vals:
        return False               # a one-sided absence is never a disagreement
    for x in a_vals:
        for y in b_vals:
            if x <= y or y <= x:
                return False
    return True


def _ident_bag(rec: dict, fields: tuple, place_tokens: set) -> set:
    """One record's DISTINCTIVE identity tokens over `fields` - the same reduction
    `_grey_bag` performs, built from the same constants and DELIBERATELY NOT by calling it.

    WHY NOT JUST CALL `_grey_bag`. Its caller set is a load-bearing invariant, asserted by
    call graph in evals/grey_prefilter_test.py: the place-stripped tokeniser must stay
    unreachable from the deterministic tiers, because SHRINKING a token set can only ADD
    subset relations, and inside `_cross_source_auto`'s containment branch that means a NEW
    auto-merge in the one tier that merges without asking anybody (the argument is spelled out
    in `_grey_tokens`). Reaching into it from here would widen that whitelist and make the
    guard weaker than the invariant it protects - for a reader whose own direction of travel is
    the opposite one: this function can only ever OFFER an already-merged pair for
    confirmation, and only an explicit 'different' verdict acts on it, so it can only split.
    So it reads `_GENERIC_PARK`-stripped tokens (`_distinctive_tokens`), subtracts the pair's
    place tokens, and applies the identical three filters over the identical constants.
    THE TWO ARE PINNED MECHANICALLY, not by comment: the auto-pair eval asserts this returns
    exactly `_grey_bag`'s set over a fixture of real-shaped values, so a change to one that is
    not made to the other fails a test rather than drifting quietly."""
    out: set = set()
    for f in fields:
        v = rec.get(f)
        if not isinstance(v, str) or not v.strip() or N.looks_unknown(v):
            continue
        out |= _distinctive_tokens(v) - place_tokens
    return {t for t in out
            if len(t) > 1 and t not in _GREY_GENERIC_EXTRA and not _CODEISH.match(t)}


def identity_disagreements(a: dict, b: dict) -> list:
    """The identity CLASSES on which both records speak and do not agree, ascending by name.

    Empty for the ordinary pair, which is the point: this is the filter that keeps an
    auto-pair confirmation exit worth reading. See the block above for what counts and why."""
    place = _grey_place_tokens(a, b)
    out = []
    for label, fields in _IDENT_CLASSES:
        ba = _ident_bag(a, fields, place)
        bb = _ident_bag(b, fields, place)
        if ba and bb and not (ba & bb):
            out.append(label)
    if _designators_disagree(_designators(a, _IDENT_DESIGNATOR_FIELDS, place),
                             _designators(b, _IDENT_DESIGNATOR_FIELDS, place)):
        out.append("unit")
    return sorted(out)


def same_property(a: dict, b: dict, decisions: dict | None = None) -> bool:
    """Decide whether two records are the same physical property.

    The deterministic tiers are AUTHORITATIVE IN ONE DIRECTION EACH, and that asymmetry is
    the contract. A 'forbidden' pair is never merged (THE BLOCKER BEATS THE LLM - it returns
    False before `decisions` is even consulted) and a 'no' pair never merges. An 'auto' pair
    merges UNLESS a recorded verdict says the two are DIFFERENT. Only a 'grey' pair
    (cross-source, ambiguous) can be merged BY a verdict: 'same' -> merge,
    'different'/absent -> distinct. With `decisions=None` every tier behaves exactly as the
    historical matcher did - a grey pair stays distinct (every pair the old code merged is
    now classed 'auto', and a grey pair is by construction not auto), and an auto pair
    merges.

    WHY 'AUTO' IS NO LONGER ABSOLUTE, and it is a documented contract that changed, not a
    loosened guard. "The auto tier is authoritative" was safe only while nobody could see an
    auto pair - and that was the defect: `grey_pairs` enumerated the ambiguous middle and
    NOTHING enumerated the auto tier, so an auto merge was offered to no human, while the
    fuzzy-key tail merges on `city|developer|park` and cannot see a unit name, a building name
    or a street. Two units of one park fused into one card, the other unit dropped off the
    longlist, and no gate looked (`gate_runner.py coverage`'s A14b code check needs the
    contributing records to state postal codes, and it asks the finished dataset). So
    `auto_pairs` now surfaces the auto pairs that MATERIALLY DISAGREE on identity, and this
    branch is what makes surfacing worth anything: without it a recorded 'different' verdict
    would be read, filed and ignored.

    THE DOWNGRADE IS DELIBERATELY ONE-WAY AND EXPLICIT-ONLY. It fires on the word 'different'
    and nothing else: an absent verdict, a missing decisions file, 'same', 'unsure' or any
    junk all leave the pair merged, which is today's behaviour to the byte. It can therefore
    only ever produce an over-SPLIT - two similar-looking cards in front of the reader, who
    can see and query them - never a new fusion. And it does not touch 'forbidden': a
    structural blocker still beats every verdict, in both directions."""
    cls = pair_class(a, b)
    if cls == "auto":
        # THE AUTO DOWNGRADE. Read the verdict the same way the grey branch does (a bare
        # string or the {"verdict": ...} shape), and act on 'different' ONLY.
        if decisions:
            v = decisions.get(pair_id(a, b))
            if isinstance(v, dict):
                v = v.get("verdict")
            if v == "different":
                return False
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
        # the safer default - an over-split ships two cards the reader can see and query,
        # an over-merge blends two properties into one and drops the other from the
        # longlist - AND it matches the historical verdict (a grey pair is never 'auto',
        # so the pre-LLM matcher returned False here too). NOT because the coverage dedupe
        # gate catches the split, which this comment used to claim: that gate needs two
        # cards identical in park, city, developer and area, and a grey pair that fell to
        # 'different' is usually not that.
        return False
    return False  # 'no'


def _enumerate_pairs(records: list[dict], tier: str, annotate=None) -> list[dict]:
    """The shared O(n^2) pair walk behind `grey_pairs` and `auto_pairs`.

    ONE walk, deliberately, rather than two loops that happen to look alike: the iteration
    order, the `pair_id` keying and the identical-signature dedupe below are what make the
    emitted pair set REPRODUCIBLE across runs, and a cached verdict in
    work/match_decisions.json is keyed on it. Two copies of that discipline would drift, and
    the symptom of drift is a settled pair being re-asked under a new id.

    `annotate(a, b)` is the tier's own materiality filter: None keeps the pair with no extra
    keys (the grey tier offers every pair it finds), a falsy return DROPS it, and anything else
    is merged into the emitted entry."""
    out: list[dict] = []
    seen: set = set()
    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = records[i], records[j]
            if pair_class(a, b) != tier:
                continue
            extra = None
            if annotate is not None:
                extra = annotate(a, b)
                if not extra:
                    continue
            pid = pair_id(a, b)
            if pid in seen:
                continue  # identical-signature records: one representative pair is enough
            seen.add(pid)
            entry = {"pair_id": pid, "a_idx": i, "b_idx": j, "a": a, "b": b}
            if extra:
                entry.update(extra)
            out.append(entry)
    return out


def auto_pairs(records: list[dict]) -> list[dict]:
    """Enumerate the AUTO-MERGED pairs worth OFFERING for human confirmation.

    Beside `grey_pairs`, on the same walk, and with one difference that is the whole design:
    these pairs are ALREADY MERGED. The grey tier asks "should these become one card?"; this
    asks "these have BECOME one card, and they disagree about who or what they are - was that
    right?". Only an explicit 'different' verdict changes anything (`same_property`), so a
    silent or absent answer leaves today's behaviour exactly as it was - the direction is
    one-way, auto -> split, which is the visible failure rather than the invisible one.

    RESTRICTED TO A MATERIAL IDENTITY DISAGREEMENT by `identity_disagreements`, and the
    restriction is not tuning: an exit that lists every auto pair is noise, noise gets skimmed,
    and a skimmed adjudication exit is worse than never asking. Each entry carries
    `disagrees_on` - the class names - so the reviewer is told WHAT the two records contradict
    each other about instead of being handed two records and asked to spot it.

    Deterministic and pure Python, exactly like `grey_pairs`: no LLM, a fixed iteration order,
    a content-keyed `pair_id`, so the same records always yield the same set and the same ids."""
    return _enumerate_pairs(
        records, "auto",
        annotate=lambda a, b: ({"auto": True, "disagrees_on": _dis}
                               if (_dis := identity_disagreements(a, b)) else None))


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
    the grey-only stop-words and the area-code filter keep the widening on real names.

    NO MATERIALITY FILTER HERE, unlike `auto_pairs`: a grey pair is by definition one the
    deterministic tiers could NOT resolve, so every one of them is a real question. The
    filtering that keeps this set small is the recall pre-filter, upstream."""
    return _enumerate_pairs(records, "grey")


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
    byte-identical; the failure direction becomes an over-SPLIT at worst - two cards a
    reader can see - where the fusion it replaced put 11 false disagreements into a
    delivered ledger and dropped a scheme. The coverage dedupe gate is not what catches
    the split (it needs park, city, developer and area all identical, which two chained
    deck pages are not); the reader is."""
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
