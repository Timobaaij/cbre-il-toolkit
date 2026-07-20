#!/usr/bin/env python3
"""plan_signal.py - a small, HIGH-PRECISION site-plan TEXT signal (2026-07-17; marker gate 2026-07-20).

Three roles, all feeding images._plan_page_eligible:
  * plan_title_score(text): RESCUE a designed site-plan page the pixel classifier mis-reads as
    photo/map (a full-bleed colour-background plan whose page carries a "SITE PLAN"/"Lageplan"/
    "plan de masse"/... TITLE). Only real plan-TITLE phrases score - NEVER amenity words
    (dock/yard/parking/clear height), which are SPEC-sheet vocabulary that would fire on the spec
    page. Matching is accent- and case-INSENSITIVE via normalize._norm_city, applied symmetrically
    to the lexicon and the page text (plan titles are often UPPERCASE/accented).
  * has_drawing_marker(text): GATE that title-rescue on the kind=='map' path. A photographic AERIAL
    or a genuine LOCATION/overview map is often titled "Site Plan"/"Lageplan" and classifies 'map'
    (pale palette) - but only a to-scale DRAWING sheet carries a "scale 1:500" / "drawing no" marker,
    so a titled 'map' page binds ONLY when a marker is also present (2nd-review wrong-bind fix). The
    kind=='plan' visual path is unaffected (it needs no marker).
  * looks_like_spec_page(text): DISQUALIFY a property SPEC/availability page (>=2 own-line spec
    labels) from ever binding the plan slot, via the authoritative extract_pdf label matcher.

ADDITIVE-ONLY: a page with no extractable text (a vector plan whose labels are drawn strokes, or a
raster deck) scores 0 / False and falls through to the pure-visual detector unchanged - text never
rescues nor blocks such a page on its own. Degrades to a no-op if the lexicon is missing/corrupt."""
from __future__ import annotations

import json
import re
from pathlib import Path

import normalize as _N

_LEX_PATH = Path(__file__).resolve().parent.parent / "assets" / "plan_lexicon.json"

# apostrophe variants (straight + typographic) are STRIPPED before folding, symmetrically on the
# lexicon and the page text, so a typeset French title ("plan d'implantation" with a curly U+2019)
# matches the lexicon's straight-apostrophe form (normalize._norm_city would otherwise drop the curly
# glyph on the text side only, breaking the match).
_APOS = {ord(c): None for c in "'’ʼ‘`"}


def _fold(s) -> str:
    return _N._norm_city(str(s or "").translate(_APOS))


def _word_present(folded: str, token: str) -> bool:
    """Whole-'word' presence of a folded token in the folded text: the token must not sit inside a
    longer ALPHABETIC run, so 'site plan' does NOT match 'site planning' / 'the estate plans to move'
    (the substring-match false-positive the review flagged). Internal spaces/punctuation are fine; the
    boundary test is on letters at the two ends only."""
    if not token:
        return False
    n = len(token)
    start = 0
    while True:
        i = folded.find(token, start)
        if i < 0:
            return False
        before = folded[i - 1] if i > 0 else " "
        after = folded[i + n] if i + n < len(folded) else " "
        if not before.isalpha() and not after.isalpha():
            return True
        start = i + 1


def _load():
    try:
        d = json.loads(_LEX_PATH.read_text(encoding="utf-8"))
        titles = [t for t in d.get("plan_titles", []) if isinstance(t, str)]
        markers = [m for m in d.get("drawing_markers", []) if isinstance(m, str)]
    except Exception:
        titles, markers = [], []  # missing/corrupt lexicon -> a silent no-op (score 0), never a crash
    return ([f for f in (_fold(t) for t in titles) if f],
            [f for f in (_fold(m) for m in markers) if f])


_TITLES, _MARKERS = _load()


# A to-scale DRAWING scale ratio ("scale 1:500", "Maßstab 1:2 500") = a site/plot/floor-plan sheet.
# TWO guards, both from adversarial review:
#   * MAGNITUDE (round-3): the denominator must be SMALL (50..2500). A LARGE denominator ("1:25 000",
#     "1:50000") is a LOCATION / topographic map, which a real site plan never uses. Parsed WITH
#     optional grouped thousands so "1:25,000"/"1:25 000" read as 25000 (not 25); a plain run is
#     capped at 4 digits with a no-trailing-digit boundary so "1:25000" (no separator) is not 2500.
#   * SCALE CUE (round-4): the ratio must be introduced by a scale-cue WORD. A bare "1:N" is
#     ambiguous - a unit/phase enumeration colon ("Unit 1: 500 sq m"), a clock/drive time ("1:50") or
#     a dilution ("1:250") all fold to the same "1:N" shape and would otherwise fire the gate (the
#     round-4 wrong-bind: a titled aerial carrying a unit schedule bound as the site plan). A real
#     to-scale sheet labels its scale with a cue; requiring it kills those collisions.
# The cue list is MULTILINGUAL, so the ratio path stays language-independent ("Maßstab 1:500",
# "échelle 1:500" fire without any English word). Cues match on already-folded text (lowercased,
# de-accented, ß->ss), so store them folded.
_PLAN_SCALE_MIN = 50      # 1:50  (a detailed floor / plot plan) ..
_PLAN_SCALE_MAX = 2500    # .. 1:2500 (a site / block plan); a larger denominator is a locator map
_SCALE_CUES = ("scale", "massstab", "masstab", "echelle", "escala", "schaal", "skala", "scala",
               "meritko", "mierka", "leptek", "scara", "mittakaava", "malestokk", "malestok")
# a scale-cue word, then <=3 folded separators (space / ':' / '=' / '.' / '-'), then a bounded 1:N
# ratio. (normalize._norm_city collapses whitespace to single spaces, so the separator window is small.)
# leading (?<![\w-]): the cue must be its OWN word, not the tail of a compound ("largescale",
# "large-scale", "full-scale") - those are adjectives, not a scale LABEL. Trailing \b: not a prefix
# ("escalate", "schaalbaar"). Both boundaries learned from the round-4 self-probe.
# TIGHT ratio (no space after the colon: '1:500', not '1: 500') - round-6 structural hardening: a real
# drawing scale is written tight in every language, while the IT/RO false-friend enumeration is spaced
# ('Scala 1: 500 posti' = staircase 1: then a value). Requiring tightness closes the WHOLE spaced-
# enumeration class (count nouns, bare numbers, any trailing token), where the area-unit guard below is
# only a denylist. (A space BEFORE the colon is tolerated for '1 :500'.)
_RATIO_RE = re.compile(
    r"(?<![\w-])(?:" + "|".join(_SCALE_CUES) + r")\b[\s.:=\-]{0,3}1\s?:0*(\d{1,3}(?:[ .,]\d{3})+|\d{1,4})(?!\d)"
)
# an AREA unit immediately after the number means "cue 1: N unit" is an ENUMERATION, not a scale:
# IT 'scala' and RO 'scara' are BOTH the scale word AND the stair/entrance label, so "Scala 1: 500 mq"
# = staircase 1, 500 m2 (a block/area schedule), NOT a 1:500 drawing scale (round-5 false-friend fix).
# A genuine scale ratio is dimensionless and never carries a trailing area unit. (m2 covers 'm²' -
# normalize._norm_city NFKD-folds the superscript to '2'.)
_AREA_AFTER = re.compile(r"\s{0,2}(?:mq|mp|m2|qm|sqm|sq m|sq ft|sqft|ha)\b")


def _scale_ratio_marker(folded: str) -> bool:
    """True iff the folded text carries a CUED to-scale drawing RATIO - a scale-cue word
    ('scale'/'Maßstab'/'échelle'/...) immediately before '1:N' with _PLAN_SCALE_MIN <= N <=
    _PLAN_SCALE_MAX AND no area unit immediately after. The cue requirement stops a bare enumeration
    colon ('Unit 1: 500'), a clock/drive time ('1:50') or a dilution ('1:250') - which fold to the
    same '1:N' - from reading as a drawing scale; the area-unit guard stops the IT/RO false-friend
    enumeration ('Scala 1: 500 mq' = staircase 1); the magnitude bound stops a locator/topographic
    scale ('scale 1:25000')."""
    for m in _RATIO_RE.finditer(folded):
        digits = "".join(ch for ch in m.group(1) if ch.isdigit())
        if not (digits and _PLAN_SCALE_MIN <= int(digits) <= _PLAN_SCALE_MAX):
            continue
        if _AREA_AFTER.match(folded, m.end()):
            continue  # "<cue> 1: N <area>" is a numbered-element area schedule, not a drawing scale
        return True
    return False


def _markers_present(folded: str) -> bool:
    """Whole-word presence of ANY drawing-sheet marker in already-folded text: EITHER a
    magnitude-bounded to-scale RATIO (language-independent) OR an English drawing-sheet PHRASE
    ('drawing no', 'sheet no', 'not to scale', ...) a locator map does not carry. Shared by
    plan_title_score (the ranking boost) and has_drawing_marker (the map-rescue gate) so the two
    can never disagree about what counts as a marker."""
    if not folded:
        return False
    return _scale_ratio_marker(folded) or any(_word_present(folded, m) for m in _MARKERS)


def has_drawing_marker(text) -> bool:
    """True IFF the page text carries a to-scale DRAWING marker ('scale 1:500', 'drawing no', 'not to
    scale', ...). Distinguishes a real to-scale site-PLAN sheet (which carries one) from a
    photographic AERIAL or a location/overview MAP (which do not, even when titled "Site Plan"):
    images._plan_page_eligible requires it before rescuing a titled kind=='map' page. Whole-word,
    accent/case/apostrophe-insensitive (folded); False on empty text or a missing/corrupt lexicon."""
    return _markers_present(_fold(text))


def plan_title_score(text) -> float:
    """>=1.0 IFF a real plan TITLE is present (each distinct title token = 1.0). Drawing-sheet markers
    ('scale 1:500', 'drawing no') add a CAPPED 0.5 TOTAL - so markers ALONE (a floor-plan / elevation
    sheet's scale bar) can NEVER reach the 1.0 rescue floor; they only boost RANKING once a title is
    present. Whole-word matching; accent-, case- and apostrophe-insensitive (folded both sides). 0.0
    on empty / no-title text."""
    folded = _fold(text)
    if not folded:
        return 0.0
    title_hits = sum(1 for t in _TITLES if _word_present(folded, t))
    return 1.0 * title_hits + (0.5 if _markers_present(folded) else 0.0)


def looks_like_spec_page(text) -> bool:
    """True when the page reads as a property SPEC / availability page (>=2 own-line spec labels via
    the authoritative extract_pdf label matcher) - such a page is NEVER a site plan, so it must not
    bind the plan slot even when the relaxed visual gate would otherwise accept it. Lazy import
    avoids a load-time cycle; degrades to False on any error / empty text."""
    if not str(text or "").strip():
        return False
    try:
        import extract_pdf as _XP
        return len(_XP._find_labels(str(text))) >= 2
    except Exception:
        return False
