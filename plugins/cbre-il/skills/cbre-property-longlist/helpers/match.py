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
    v = r.get("warehouseArea")
    return float(v) if isinstance(v, (int, float)) else None


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
        return True  # indistinguishable restatement - keeping both adds nothing
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
    as a developer. A cross-source dev-disagreement pair therefore falls through to
    _cross_source_grey (same city / ~2 km / shared distinctive park token / fuzzy 70-88)
    and the LLM adjudicates it. _cross_source_auto is UNCHANGED - its coord-net auto
    path still REQUIRES developer agreement, so a disagreement goes to grey, never auto."""
    aa, ba = _area(a), _area(b)
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
    """RECALL pre-filter: a cross-source pair that is NOT forbidden and NOT auto, but
    is plausible enough to ask the LLM about - same normalised city, OR within ~2 km,
    OR sharing >= 1 distinctive park token, OR a borderline fuzzy key in [70, 88).
    The union of the signals match.py already trusts, capped to plausible pairs, so the
    grey set stays a handful (typically 0-5) rather than an O(n^2) LLM call."""
    ca, cb = norm(a.get("city")), norm(b.get("city"))
    if ca and cb and ca == cb:
        return True
    la, lb = _latlng(a), _latlng(b)
    if la and lb and _km(la, lb) <= GREY_COORD_KM:
        return True
    da_, db_ = _distinctive_tokens(a.get("park")), _distinctive_tokens(b.get("park"))
    if da_ and db_ and (da_ & db_):
        return True
    score = _tsr(match_key(a), match_key(b))
    if GREY_LOW <= score < MATCH_THRESHOLD:
        return True
    return False


def pair_class(a: dict, b: dict) -> str:
    """Classify a record PAIR into one of four tiers:
      'auto'      - merge deterministically (today's confident TRUE paths)
      'grey'      - cross-source, not forbidden, not auto, but clears the recall
                    pre-filter: the genuinely ambiguous middle the LLM adjudicates
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
    pair set and ids. Typical longlists yield 0-5 grey pairs (often 0)."""
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
    (every offline path) is byte-identical to the historical behaviour."""
    clusters: list[list[dict]] = []
    for rec in records:
        placed = False
        for cl in clusters:
            if any(same_property(rec, other, decisions) for other in cl):
                cl.append(rec)
                placed = True
                break
        if not placed:
            clusters.append([rec])
    return clusters
