#!/usr/bin/env python3
"""clarify.py - ambiguity becomes a QUESTION, asked during the run, answered once.

THE PRINCIPLE. When the skill cannot know something, the honest move is to ASK - at the
moment the answer can still change the deliverable - not to write a caveat into a Gaps
Report nobody reads. The skill already does this three times: exit 3 (a deck needs reading),
exit 9 (is this the right photo?), exit 10 (are these the same property / which value wins).
Those are the only three things it would ask about; everything else degraded to a flag. This
is the general channel.

THE BOUND, AND IT IS THE WHOLE DESIGN. This project's dominant failure mode is the unbounded
ask loop - the QA window is capped at one review plus one improvement round because "keep
asking until it is clean" never terminated, and `_exit_round_trip` exists because round-trips
silently repeated forever. So a new asking channel MUST converge by construction:

    ASK ONCE, THEN SHIP HONESTLY.

Every question is asked exactly once per work dir. A question that comes back answered is
recorded durably and never re-asked. A question that comes back UNANSWERED is also never
re-asked - it falls through to the honest disclosed gap, which is today's behaviour. So the
run can always finish, and no sequence of skipped answers can wedge it. `asked` is recorded
BEFORE the answers are read, so even a broker who answers nothing sees each question once.

Questions are BATCHED: one file, one round-trip, all questions together, exactly as exit 10
carries pairs and value conflicts in a single hand-off. N ambiguities cost one interruption,
not N.

WHO ANSWERS. `asked_of` is `"agent"` when the answer is a reading/perception call an isolated
sub-agent can make from the source (how many properties are on this page?), and `"broker"`
when it is a decision no amount of reading can settle (what unit does this unlabelled column
use? which source is authoritative?). Python only ever ASKS - it never answers, and it never
guesses when an answer does not come.

BLOCKING, AND WHY IT NOW EXISTS (B49). The bound above - ask once, then ship the default - is
too weak for the questions where THE DEFAULT IS THE DAMAGE. A live 17-option run shipped 41
cards because the source-authority question fell through to its documented default, "the union
of both": the run finished, every gate went green, and 24 options the client never shortlisted
reached a client-facing dashboard. The caveat was written and, exactly as this module's opening
paragraph predicts, nobody read it. Presuming is not honest merely because the presumption is
disclosed.

So a question now carries `blocking`. A NON-blocking question keeps the original contract
(asked once; unanswered ships the disclosed gap). A BLOCKING question is re-offered every pass
until it is either ANSWERED or EXPLICITLY DECLINED - the run cannot proceed on an assumption
about it.

That is still bounded, and the shape of the bound is what makes it safe: the escape is EXPLICIT
rather than implicit-on-silence. Three ways out, each a RECORDED DECISION rather than a
shrug -
  - answer it;
  - decline it (`"skip"`, `"you decide"`, any DECLINE_TOKEN as the whole answer), which ships
    the stated default and is disclosed in the Gaps Report as a decision, not as a gap;
  - `work/clarify.SKIP_ALL` (or `project.yaml clarify.assume_defaults: true`) - the
    non-interactive escape for a headless/cron run with no broker to ask.
`offers` counts how many times each blocking question has been put; after ESCALATE_AFTER passes
the hand-off text spells out the decline path, so an orchestrator that keeps re-running without
either asking the broker or recording a decline is told in the exit text how to end it. What it
never does is auto-presume: silence is the one thing that no longer resolves a blocking
question.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

QUESTIONS_FILE = "questions.json"
STATE_FILE = "clarify_state.json"
ANSWERS_FILE = "answers.json"
SKIP_ALL_FILE = "clarify.SKIP_ALL"

# every question kind, and who can answer it
KINDS = {
    "area_unit": "broker",        # a numeric area whose source states no unit
    "rent_unit": "broker",        # a rent whose source states no currency / per-area
    "record_count": "agent",      # a deck that may hold more properties than were emitted
    "source_authority": "broker",  # two sources disagree on HOW MANY properties exist
    "dataset_unit": "broker",     # the corpus states BOTH sq ft and sq m - which is displayed
    "value_format": "broker",     # one bare number among unit-carrying siblings (gate B59)
    # workstream 3 (interactive standard mode) kinds:
    "match_unsure": "broker",     # the adjudicator was genuinely torn on a grey pair
    "field_unsure": "broker",     # ...or on a value-conflict pick
    "photo_confirm": "broker",    # an uncertain brochure->property photo pairing
    "agent_doubt": "broker",      # a reader's recorded doubt (__meta.doubts)
    "excluded_figure": "broker",  # an excluded record's figure conflicts with a shipped card
    "setup_form": "broker",       # the Stage-0 six-question form has not been answered (B63)
}

# The kinds whose DEFAULT IS THE DAMAGE, so silence must not resolve them (B49):
#   source_authority - the default ships every phantom extra (the live 41-vs-17 failure)
#   dataset_unit     - the default silently relabels half a mixed dataset, 10.76x out
#   area_unit /      - an unlabelled figure inherits a unit it was never measured in, which
#   rent_unit          is the 10.76x error class this whole skill exists to avoid
#   value_format     - appending the siblings' unit to a bare number is DECIDING the field
#                      is an area; a wrong guess silently relabels a count or a power rating
#   setup_form       - the scaffold's six guessed answers ARE the damage: they shipped
#                      English dashboards with no email ingestion to brokers who were never
#                      offered the choice (B63)
BLOCKING_KINDS = {"source_authority", "dataset_unit", "area_unit", "rent_unit",
                  "value_format", "setup_form"}

# --------------------------------------------------------------------------- #
# MATERIALITY - does the ANSWER change what the CLIENT SEES? (B62)
#
# THE BROKER'S RULE, set 2026-08-26 after a live interactive run stopped too often: ASK
# ONLY WHEN THE ANSWER CHANGES THE DASHBOARD. Exactly two things qualify:
#   "display" - it changes a value, photo or label RENDERED on a card, in the detail
#               modal, in the compare table or on the map;
#   "count"   - it changes HOW MANY options ship (the 17-vs-41 class).
# Everything else is "ledger": a doubt that moves only a provenance note, a Source Ledger
# cell or an Excel-only column. A ledger question is NOT put to the broker. Stopping a run
# for one buys nothing a client can see, and the cost is real - each round is an
# interruption, and a channel that asks about trivia trains the reader to skim the
# questions that are precise (the same reasoning that keeps record_count unwired).
#
# WHAT SUPPRESSION IS NOT. It is not silence and it is not a guess. An unasked question
# ships its OWN STATED DEFAULT - the value the source already gave - and is recorded in
# `clarify_state.suppressed`, which deliver.py prints in the Gaps Report under "Noted, not
# put to you". That is precisely what a headless run has always done with these, so the
# Data Honesty Standard is untouched: nothing is invented, nothing is dropped, and the
# broker can still see every doubt the run had. What changes is only WHERE it is shown.
#
# THE SAFE DIRECTION IS TO ASK. An unrecognised kind, or a question whose materiality
# cannot be read, defaults to material - so a producer added later keeps today's behaviour
# until someone classifies it deliberately.

# The canonical fields the dashboard template actually RENDERS (card, detail modal, compare
# table, map popup). Derived from assets/dashboard_template.html - every `p.<field>` its
# render JS reads - intersected with templates/canonical.schema.json's property fields.
# Held as a literal because clarify must stay a pure module (no 800 KB template read on the
# question path) and PINNED by evals/clarify_materiality_test.py, which re-derives it from
# the template and fails on any drift.
# DELIBERATELY ABSENT: `postcode`, `district`, `warehouseAreaSqm`, `expansionParkVal` - real
# fields that ship in the Longlist workbook and the Source Ledger but appear nowhere on the
# dashboard - and every open-captured tracker column, which by definition has no card slot.
DISPLAY_FIELDS = frozenset({
    "areaUnit", "breeam", "brochureLink", "carParking", "city", "clearHeight",
    "coordsApprox", "country", "description", "developer", "districtProfile",
    "divisibleFrom", "earlyAccess", "electricity", "epc", "expansionBuilding",
    "expansionPark", "floorLoad", "gallery", "id", "incentives", "landPrice", "landlord",
    "lat", "leaseTerm", "lng", "loadingDocks", "mapLink", "motorway", "officeArea",
    "officeAreaVal", "officeRent", "officeRentVal", "overheadDoors", "park", "permitting",
    "photo", "plan", "plotArea", "preBaked", "region", "regionCode", "reit", "rentFree",
    "rentUnit", "serviceCharge", "sprinklers", "status", "truckParking", "warehouseArea",
    "warehouseRent", "warehouseRentVal",
})

# Per-kind materiality. A producer may override it per question by stamping `materiality`.
#   value_format is ALWAYS material and deliberately not field-tested: its gate already
#   scopes blocking findings to canonical card fields, it BLOCKS the build (exit 6), and
#   the only ways out are a broker answer or a broker decline - so suppressing one would
#   wedge the run with no path forward, which is worse than one question.
#   agent_doubt starts at "ledger" and is promoted per doubt by _doubt_materiality: a free-
#   text doubt is only worth a round-trip when it names something the client will see.
KIND_MATERIALITY = {
    "source_authority": "count",     # which source decides what belongs (17 vs 41)
    "record_count": "count",         # a deck that may hold more properties than it emitted
    "match_unsure": "count",         # merged or split = one card or two
    "dataset_unit": "display",       # relabels every area on the grid
    "area_unit": "display",          # the figure on the card
    "rent_unit": "display",          # the rent on the card
    "value_format": "display",       # see above - never suppressed
    "photo_confirm": "display",      # the hero image IS the card
    "excluded_figure": "display",    # which figure the card shows
    "field_unsure": "display",       # only DISPLAYED-field conflicts ever become a question
    "agent_doubt": "ledger",         # promoted per doubt when it names a shown field/count
    "setup_form": "display",         # the language relabels the whole dashboard, and the
                                     # email scope changes which options are on it (B63)
}
MATERIALITIES = ("count", "display", "ledger")


def field_is_displayed(field) -> bool:
    """Is this canonical field rendered anywhere on the dashboard? Open-captured tracker
    columns and Excel-only fields answer False - that is the whole point."""
    return str(field or "").strip() in DISPLAY_FIELDS


def _phrase_rx(phrases) -> "re.Pattern":
    """One word-boundary alternation over a phrase list. Boundaries matter: a bare `in`
    test would match 'id' inside 'candidate' and mark half the doubts material."""
    alts = sorted({str(p).strip().lower() for p in phrases if str(p).strip()},
                  key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(a) for a in alts) + r")(?!\w)")


def _split_camel(field: str) -> str:
    """'warehouseArea' -> 'warehouse area'; a trailing 'val' (a derived numeric twin of a
    displayed field) is dropped so 'office rent val' reads as the broker would say it."""
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", str(field or "")).lower().split()
    if len(words) > 1 and words[-1] == "val":
        words = words[:-1]
    return " ".join(words)


# CLUSTERING IS ALSO THE CLIENT'S VIEW. A field the dashboard never prints can still change
# HOW MANY cards ship, because the matcher reads it to decide whether two records are one
# property: `match._GREY_IDENT_FIELDS` (park, address, postcode, scheme, building, unit...)
# and `match._PLACE_FIELDS_EXTRA` (region, district, country) feed the grey-tier identity and
# place bags. Settling `postcode` silently is therefore NOT free - it can move the option
# count on the next pass, which rule 4 calls material. Read from `match` so the two cannot
# drift apart, with a literal fallback so an import failure cannot make this MORE permissive.
_MATCH_FIELDS_FALLBACK = frozenset({
    "park", "address", "addressLine", "addressLine1", "street", "postcode", "postalCode",
    "name", "propertyName", "scheme", "schemeName", "estate", "site", "siteName",
    "building", "buildingName", "unit", "unitName", "region", "district", "country",
    "city", "developer", "landlord",
})
_MATCH_FIELDS_CACHE = None


def match_sensitive_fields() -> frozenset:
    """Fields the MATCHER reads to decide identity, so a silent pick can move the count."""
    global _MATCH_FIELDS_CACHE
    if _MATCH_FIELDS_CACHE is None:
        got = set(_MATCH_FIELDS_FALLBACK)
        try:
            import match as _M
            for attr in ("_GREY_IDENT_FIELDS", "_PLACE_FIELDS_EXTRA", "_PARTY_FIELDS"):
                got |= {str(f) for f in (getattr(_M, attr, ()) or ())}
        except Exception:
            pass
        _MATCH_FIELDS_CACHE = frozenset(got)
    return _MATCH_FIELDS_CACHE


def field_is_material(field) -> bool:
    """Could settling this field change what the client sees - either because the dashboard
    RENDERS it, or because the MATCHER reads it and could re-cluster on it?"""
    f = str(field or "").strip()
    return bool(f) and (f in DISPLAY_FIELDS or f in match_sensitive_fields())


def known_field(field) -> bool:
    """Is this the name of a field the pipeline actually knows?

    Used to decide whether a reader's `field` DECLARATION can be trusted. It must not be a
    membership test against DISPLAY_FIELDS alone: that returns False both for "a real field
    that is not rendered" and for "not a field name at all", and treating the second as the
    first is how a declared "area" or "warehouse_area" silently demoted a doubt about the
    figure on the card. An unrecognised name means UNDECLARED, so the text is read instead."""
    f = str(field or "").strip()
    if not f:
        return False
    if f in DISPLAY_FIELDS or f in match_sensitive_fields():
        return True
    try:
        return f in C.canonical_property_fields()
    except Exception:
        return False


# The words a reading agent actually uses when its doubt is about something the client will
# SEE. Part of it is derived from DISPLAY_FIELDS so the lexicon cannot silently fall behind
# the template; the rest is the plain-English vocabulary of a brochure ("eaves", "thousands",
# "vacant") that no field name carries. GENEROUS ON PURPOSE - two blind reviews found the
# first, tighter version demoting real doubts about currency, thousands separators, hero
# photos and whether a hall was let, all of which a client sees.
_EXTRA_DISPLAY_TOKENS = (
    # magnitude and units
    "area", "areas", "size", "sizes", "sq m", "sqm", "sq ft", "sqft", "m2", "square metre",
    "square metres", "square meter", "square meters", "square foot", "square feet",
    "hectare", "hectares", "acre", "acres", "gla", "figure", "figures", "number",
    "thousand", "thousands", "million", "millions", "decimal", "magnitude",
    # money
    "rent", "rents", "rental", "price", "prices", "pricing", "quote", "quoted", "quoting",
    "currency", "eur", "euro", "euros", "gbp", "pound", "pounds", "sterling", "pln",
    "zloty", "czk", "koruna", "forint", "monthly", "yearly", "annual", "annually",
    "per year", "per month", "headline",
    # the building itself
    "warehouse", "warehouses", "building", "buildings", "hall", "halls", "office",
    "offices", "mezzanine", "plot", "plots", "yard", "unit", "units", "height", "eaves",
    "haunch", "clearance", "dock", "docks", "door", "doors", "ramp", "sprinkler",
    "sprinklered", "loading", "parking", "power", "mva", "kva", "amps", "electricity",
    "specification", "specifications", "spec", "certification", "rating", "grade",
    # commercial state
    "tenant", "tenanted", "vacant", "occupied", "available", "availability", "let",
    "lease", "leased", "completion", "handover", "practical completion", "ready",
    "incentive", "incentives", "term", "terms",
    # what the card LOOKS like
    "photo", "photos", "photograph", "image", "images", "picture", "shot", "render",
    "aerial", "asset", "site plan", "floorplan", "floor plan", "elevation",
    # where it is
    "map", "coordinate", "coordinates", "latitude", "longitude", "location", "address",
    "estate", "junction", "distance", "drive time",
)
# "date" and "cover" are deliberately NOT here. The one displayed date (`earlyAccess`) is
# reached by its own split phrase "early access" plus "completion"/"handover"/"available",
# and a bare "date" promoted every doubt about a FILE's date format; "cover" would promote
# the canonical cosmetic example ("the brochure cover tint looks unusual").

# ...and the words it uses when the doubt is about HOW MANY options exist. Both reviews
# found the first version, restricted to fixed phrases, missing every paraphrase of "is this
# one property or two", so the paraphrases are enumerated here.
_COUNT_TOKENS = (
    "how many", "number of properties", "number of options", "more than one property",
    "more than one", "same property", "same building", "same site", "same option",
    "same scheme", "same listing", "one property", "two properties", "two options",
    "two buildings", "two schemes", "two records", "two listings", "or two", "or three",
    "second building", "second phase", "second scheme", "another building",
    "another scheme", "separate property", "separate properties", "separate record",
    "separate records", "separate option", "separate options", "separate listing",
    "separate listings", "different property", "different properties", "different scheme",
    "different address", "different asset", "another property", "adjacent", "adjoining",
    "neighbouring", "neighboring", "next door", "belongs to", "belong to", "portfolio of",
    "let together", "individually", "one listing", "one record", "page binding",
    "which property", "wrong property", "wrong plot", "split into", "duplicate",
    "duplicated", "phase",
)
# The doubt classes that genuinely change NOTHING a client sees: cosmetics, file hygiene,
# notation. These OVERRIDE the display lexicon, because an explicitly cosmetic doubt should
# not be promoted by a stray building word ("the cover tint on the warehouse brochure looks
# unusual"). They do NOT override the count lexicon: how many options ship is the
# highest-stakes class and no cosmetic phrasing should be able to bury it.
# "date format" is deliberately absent: an ambiguous availability date DOES move a card, and
# a page's date notation reaches "ledger" anyway by matching nothing at all.
_LEDGER_TOKENS = (
    "tint", "colour", "color", "font", "typeface", "layout", "margin", "logo", "watermark",
    "typo", "spelling", "file name", "filename", "encoding", "mojibake", "garbled",
    "header row", "footer", "page number", "metadata", "capitalisation", "capitalization",
    "punctuation", "language of the file", "translation",
)
_DISPLAY_RX = _phrase_rx({_split_camel(f) for f in DISPLAY_FIELDS} | set(_EXTRA_DISPLAY_TOKENS))
_COUNT_RX = _phrase_rx(_COUNT_TOKENS)
_LEDGER_RX = _phrase_rx(_LEDGER_TOKENS)


def _doubt_context(doubt: dict) -> str:
    """`why_it_matters` + `options`, which is where a reader legitimately puts the substance
    when the `question` itself is terse ("which one is right?").

    `subject` is deliberately EXCLUDED: it is nearly always a park or city name, and names
    like "Eastgate Park" or "Unit 4, Riverside" carry lexicon words ("park", "unit"), so
    reading it would promote every doubt ever recorded and the filter would do nothing."""
    d = doubt if isinstance(doubt, dict) else {}
    bits = [str(d.get("why_it_matters") or "")]
    opts = d.get("options")
    if isinstance(opts, (list, tuple)):
        bits += [str(o) for o in opts[:6]]
    return " ".join(b for b in bits if b)


def _doubt_materiality(doubt: dict, text: str = "") -> str:
    """Classify ONE reader doubt. A declaration beats a guess, always.

    Order: an explicit `materiality`/`affects` wins; then a declared `field`/`fields`, but
    ONLY where the name is one the pipeline knows (`known_field`) - an unrecognised name is
    treated as no declaration at all and the text is read instead, because "area" and
    "warehouse_area" are near-misses a reading model writes and demoting on them would hide
    a doubt about the figure on the card.

    Then the free text (question + `why_it_matters` + `options`). That half is a HEURISTIC
    and is treated as one: a doubt is demoted only on positive cosmetic/hygiene evidence, or
    when nothing in it names anything the client could see. Both directions are bounded - a
    false promotion costs one line in an already-batched round, and a false demotion ships
    the source's own value and is printed in the Gaps Report, where the broker can still act
    on it. A reader that wants certainty declares the field."""
    d = doubt if isinstance(doubt, dict) else {}
    m = str(d.get("materiality") or d.get("affects") or "").strip().lower()
    if m in MATERIALITIES:
        return m
    fields = list(d.get("fields") or []) if isinstance(d.get("fields"), (list, tuple)) else []
    if d.get("field"):
        fields.append(d.get("field"))
    declared = [f for f in fields if known_field(f)]
    if declared:
        return "display" if any(field_is_material(f) for f in declared) else "ledger"
    t = (str(text or "") + " " + _doubt_context(d)).lower()
    if _COUNT_RX.search(t):
        return "count"
    if _LEDGER_RX.search(t):
        return "ledger"
    if _DISPLAY_RX.search(t):
        return "display"
    return "ledger"


def materiality(q) -> str:
    """'count' | 'display' | 'ledger' for one question. An unknown KIND -> 'display' (ask)."""
    if not isinstance(q, dict):
        return "display"
    m = str(q.get("materiality") or "").strip().lower()
    if m in MATERIALITIES:
        return m
    kind = str(q.get("kind") or "")
    if kind == "field_unsure" and q.get("field") is not None:
        return "display" if field_is_material(q.get("field")) else "ledger"
    return KIND_MATERIALITY.get(kind, "display")


def is_material(q) -> bool:
    """Would the answer change a figure, a photo or the option count on the dashboard?"""
    return materiality(q) != "ledger"


WHY_LEDGER = "ledger"        # the answer cannot change anything the client sees
WHY_CAP = "over the cap"     # material, but past the per-round question cap
WHY_HEADLESS = "headless"    # material, but this run was told to decide rather than ask


def note_suppressed(work, questions: list, why: str = WHY_LEDGER,
                    replace_kind: str = "") -> int:
    """Record a question that was NOT put to the broker, so the GAPS REPORT discloses it.

    This is the half that keeps suppression honest, and `why` is what keeps the disclosure
    honest: the report must not tell a broker that a doubt about a warehouse area has "no
    effect on what the dashboard shows" merely because nobody asked them about it. Three
    reasons, and deliver.py prints them under two DIFFERENT headings:
      WHY_LEDGER   - immaterial: it genuinely cannot change the dashboard.
      WHY_CAP      - material, but more doubts arrived than one round can carry.
      WHY_HEADLESS - material, but this run was set to decide sensibly and disclose.
    Nothing here answers anything: the source's own value ships either way.

    Recorded ONCE per id (the file is a merge resume input, so re-writing it every pass
    would re-fire merge -> build -> deliver for nothing). `replace_kind` drops the existing
    entries of one kind first, for a producer whose ids are re-keyed by later clustering
    (field_unsure ids move when a cluster settles, and a stale entry would have the report
    naming a conflict that no longer exists)."""
    st = load_state(work)
    sup = st.setdefault("suppressed", {})
    before = json.dumps(sup, sort_keys=True)
    if replace_kind:
        for i in [k for k, v in sup.items()
                  if str((v or {}).get("kind") or "") == str(replace_kind)]:
            sup.pop(i, None)
    n = 0
    for q in questions or []:
        i = (q or {}).get("id")
        if not i or i in sup:
            continue
        sup[str(i)] = {
            "kind": str(q.get("kind") or ""),
            "subject": str(q.get("subject") or ""),
            "question": str(q.get("question") or "")[:400],
            "materiality": materiality(q),
            "why_not_asked": str(why or WHY_LEDGER),
            "source_file": str(q.get("source_file") or ""),
            "if_unanswered": str(q.get("if_unanswered") or "")[:300],
        }
        n += 1
    if json.dumps(sup, sort_keys=True) != before:
        save_state(work, st)
    return n


# An answer meaning "I am not going to answer this - proceed on the stated default, and record
# that I chose to." Matched against the WHOLE answer, case- and punctuation-insensitively, so a
# real answer that merely contains one of these words ("skip the brochures") is never misread as
# a decline. Being explicit is the entire point: this is a decision, not silence.
DECLINE_TOKENS = {
    "skip", "skipped", "skip it", "skip this", "decline", "declined", "default", "defaults",
    "the default", "accept the default", "use the default", "you decide", "your call",
    "no answer", "no preference", "dont know", "don't know", "do not know", "unknown",
    "unsure", "no idea", "whatever you think", "proceed", "n/a", "na",
}
ESCALATE_AFTER = 2   # blocking offers before the hand-off text spells out the decline path


def qid(kind: str, subject: str, field: str = "") -> str:
    """A stable id for a question: same ambiguity -> same id, across runs and machines.

    Keyed on the ambiguity itself (kind + subject + field), NEVER on a value - a question
    about an unlabelled column must keep its id when the column's numbers change, or the
    answer is orphaned and the broker is asked twice. Same reasoning as B09's conflict_id."""
    raw = f"{kind}|{str(subject).strip().lower()}|{str(field).strip().lower()}"
    return "q_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _state_path(work) -> Path:
    return Path(work) / STATE_FILE


def load_state(work) -> dict:
    """{"asked": [ids], "answers": {id: answer}}. Tolerant: a malformed file degrades to
    empty rather than crashing a run, but then nothing is treated as already-asked, so the
    worst case is asking once more - never a wrong answer."""
    st = {}
    try:
        st = json.loads(_state_path(work).read_text(encoding="utf-8-sig"))
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    st.setdefault("asked", [])
    st.setdefault("answers", {})
    st.setdefault("declined", [])   # blocking questions the answerer explicitly waved through
    st.setdefault("offers", {})     # id -> how many times it has been PUT (blocking escalation)
    st.setdefault("titles", {})     # id -> {kind, subject, question} for the Gaps disclosure
    st.setdefault("suppressed", {})  # id -> ledger-only question, NOT asked but DISCLOSED
    if not isinstance(st["asked"], list):
        st["asked"] = []
    if not isinstance(st["answers"], dict):
        st["answers"] = {}
    if not isinstance(st["declined"], list):
        st["declined"] = []
    if not isinstance(st["offers"], dict):
        st["offers"] = {}
    if not isinstance(st["titles"], dict):
        st["titles"] = {}
    if not isinstance(st["suppressed"], dict):
        st["suppressed"] = {}
    return st


def save_state(work, st: dict) -> Path:
    """WRITE ONLY WHEN THE CONTENT DIFFERS - this file is a merge resume input.

    An unconditional write bumps the mtime on every pass, and because clarify_state.json is a
    merge input (so a freshly-answered question cannot be resume-skipped), that made merge ->
    build -> deliver all re-fire on a no-change resume. `ingest_answers` runs on EVERY pass, so
    the churn was guaranteed. Same rule, and the same reason, as run._write_if_changed."""
    p = _state_path(work)
    # An EMPTY `suppressed` is not written. load_state setdefaults the key, and ingest_answers
    # saves on every pass, so persisting it would rewrite every pre-existing work dir's state
    # exactly once - and because this file is a merge input, that one rewrite re-fires
    # merge -> build -> deliver on an already-delivered project for a key holding nothing.
    if isinstance(st.get("suppressed"), dict) and not st["suppressed"]:
        st = {k: v for k, v in st.items() if k != "suppressed"}
    body = json.dumps(st, ensure_ascii=False, indent=2)
    try:
        if p.exists() and p.read_text(encoding="utf-8-sig") == body:
            return p
    except OSError:
        pass
    return C.atomic_write_text(p, body)


def _norm_answer(v) -> str:
    """Lowercased, stripped of surrounding punctuation - for DECLINE matching only."""
    return str(v or "").strip().strip(".!?,;:'\"()[]").strip().lower()


def is_decline(v) -> bool:
    """Is this answer an EXPLICIT 'proceed on the default'?

    Matched on the WHOLE answer, never as a substring: 'skip' declines, but 'skip the
    brochures' is a real instruction and must not be swallowed as one. A decline is a recorded
    decision - it unblocks the run and is disclosed as a choice, not as an unread gap."""
    return _norm_answer(v) in DECLINE_TOKENS


def clarify_mode(work, cfg: dict | None = None) -> str:
    """'interactive' | 'headless' - how eagerly this run asks the broker.

    INTERACTIVE IS THE STANDARD MODE (user-set, 2026-08-24): a judgement the pipeline
    cannot settle that affects what a card shows is PUT TO THE BROKER during the run -
    an unsure match verdict, a forbidden-pair figure conflict, an uncertain photo, a
    sub-agent's recorded doubt. HEADLESS keeps the original contract (default honestly
    + disclose in the Gaps Report) and is selected by `project.yaml clarify.mode:
    headless`, `clarify.assume_defaults: true`, or the SKIP_ALL sentinel - so a
    cron/eval run never blocks on a human. The pre-existing question kinds behave
    identically in both modes; the mode only gates the interactive-era kinds."""
    if skip_all(work):
        return "headless"
    c = (cfg or {}).get("clarify") or {}
    if c.get("assume_defaults") is True:
        return "headless"
    m = str(c.get("mode") or "").strip().lower()
    return "headless" if m == "headless" else "interactive"


def skip_all(work) -> bool:
    """The non-interactive escape: every blocking question is treated as explicitly declined.

    For a headless/cron run with no broker to ask. Deliberately a FILE (or a project.yaml
    flag), never the default - an unattended run must opt in to presuming, and the Gaps Report
    still names every default it took."""
    if (Path(work) / SKIP_ALL_FILE).exists():
        return True
    # PROJECT.YAML LIVES IN THE WORK DIR. run.py resolves it as `work / "project.yaml"`
    # (run.py "Stage 0 - intake") and intake writes the scaffold there. This function read
    # `work.parent` only, so `clarify.assume_defaults: true` in the real file was DEAD - the
    # sentinel was the only working headless escape, while failure-modes.md documented both.
    # The parent is still tried second, for a hand-placed file beside a legacy work dir.
    try:
        import yaml  # optional dependency; absent -> the file is the only escape
    except Exception:
        return False
    for _p in (Path(work) / "project.yaml", Path(work).parent / "project.yaml"):
        try:
            cfg = yaml.safe_load(_p.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            continue
        if bool((cfg.get("clarify") or {}).get("assume_defaults")):
            return True
    return False


def ingest_answers(work) -> dict:
    """Fold work/answers.json into the durable state and return every answer known so far.

    The reply file is the ONE non-deterministic input here (a broker or a sub-agent writes
    it), so its shape is validated the way translate._load_cache validates its cache: the
    documented flat {id: answer} map, plus the two envelope shapes an agent naturally
    returns. An unrecognised id is IGNORED, never applied to a different question."""
    st = load_state(work)
    raw = None
    p = Path(work) / ANSWERS_FILE
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            raw = None
    flat: dict = {}
    if isinstance(raw, dict):
        inner = raw.get("answers")
        flat = inner if isinstance(inner, dict) else raw
    elif isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("id"):
                v = row.get("answer", row.get("value"))
                if v is not None:
                    flat[str(row["id"])] = v
    known = set(st["asked"])
    for k, v in (flat or {}).items():
        k = str(k).strip()
        if not k or v in (None, ""):
            continue
        if known and k not in known:
            continue  # an id we never asked -> ignore, never mis-apply
        if is_decline(v):
            # An EXPLICIT decline. Recorded as a decision so the question stops blocking, but
            # deliberately NOT stored as an answer: apply_answers must never receive "skip" as
            # if it were a unit, and the Gaps Report reports it as an accepted default.
            if k not in st["declined"]:
                st["declined"].append(k)
            st["answers"].pop(k, None)
            continue
        st["answers"][k] = v
        if k in st["declined"]:
            st["declined"].remove(k)   # a real answer supersedes an earlier decline
    save_state(work, st)
    return dict(st["answers"])


def declined_ids(work) -> set:
    """Every question explicitly waved through, including all of them under SKIP_ALL."""
    st = load_state(work)
    if skip_all(work):
        return set(st.get("asked") or []) | set(st.get("declined") or [])
    return set(st.get("declined") or [])


def is_blocking(q) -> bool:
    """Explicit `blocking` if the producer set one, else the kind's default (B49)."""
    if isinstance(q, dict) and "blocking" in q:
        return bool(q.get("blocking"))
    return bool(isinstance(q, dict) and q.get("kind") in BLOCKING_KINDS)


def pending(work, questions: list) -> list:
    """The questions still outstanding.

    TWO CONTRACTS, and the difference is the whole of B49:

      NON-BLOCKING - excluded once ASKED, answered or not. That is the original bound: ask
      once, then ship the disclosed gap. A broker who answers nothing is never asked twice.

      BLOCKING - excluded only once ANSWERED or explicitly DECLINED. Silence keeps it
      outstanding, because for these kinds the fall-through default IS the damage (the live
      41-vs-17 run). It still cannot loop forever: `is_decline` and `skip_all` are both a
      one-step, always-available exit, and both are recorded as a decision.

    AND ONE FILTER, applied last (B62): a LEDGER-ONLY question never leaves this function.
    This is the door nearly every producer's output passes through, which is why the
    materiality rule lives here rather than in five separate producers. Two exceptions,
    both deliberate: `run.unsure_pick_questions` must RESOLVE an immaterial conflict to its
    default at the producer (a dropped blocking question would leave field_decisions.json
    holding 'unsure' and exit 10 would never converge), and `run.value_format_clarify`
    appends a re-ask AFTER this call, which is safe only because value_format is material
    by kind. Suppressed questions are recorded (note_suppressed) so the Gaps Report
    discloses them; they are never answered, and the source's own value ships.

    A BLOCKING question is never suppressed here, whatever its materiality says. Nothing in
    the tree currently produces a blocking ledger question, but the invariant that
    suppression always leaves a settled value behind it is asserted in three docstrings and
    was enforced in none - so it is enforced here, where dropping one would strand it with
    no decision, no escalation count and no way out."""
    st = load_state(work)
    asked = set(st.get("asked") or [])
    answered = set(st.get("answers") or {})
    declined = declined_ids(work)
    seen, out, ledger = set(), [], []
    for q in questions:
        i = q.get("id")
        if not i or i in seen:
            continue
        if i in answered or i in declined:
            continue
        if i in asked and not is_blocking(q):
            continue
        seen.add(i)
        if is_blocking(q) or (is_material(q) and not q.get("over_cap")):
            out.append(q)
        else:
            ledger.append(q)
    for _why in (WHY_LEDGER, WHY_CAP):
        _batch = [q for q in ledger
                  if (WHY_CAP if q.get("over_cap") else WHY_LEDGER) == _why]
        if _batch:
            note_suppressed(work, _batch, why=_why)
    return out


def emit(work, questions: list) -> Path:
    """Write the batched hand-off and mark every question ASKED.

    Marking happens HERE, not when an answer arrives, so a skipped NON-blocking question is
    never re-asked. That is what makes the channel converge. A BLOCKING question is marked too
    (the telemetry is unchanged) but `pending` no longer reads `asked` for it - it reads
    answered/declined, so it comes back until it is decided (B49). Each pass increments its
    `offers` count and, past ESCALATE_AFTER, stamps `escalated` so the hand-off text can spell
    out the decline path rather than repeating itself identically."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    st0 = load_state(work)
    _offers = st0.get("offers") or {}
    for q in questions:
        if not (isinstance(q, dict) and q.get("id")):
            continue
        if is_blocking(q):
            n = int(_offers.get(q["id"], 0)) + 1
            q["blocking"] = True
            q["times_asked"] = n
            if n > ESCALATE_AFTER:
                q["escalated"] = True
        else:
            q.setdefault("blocking", False)
    payload = {
        "schema_version": 1,
        "output": f"work/{ANSWERS_FILE}",
        "instructions": (
            "These are ambiguities the pipeline cannot resolve by reading harder - each one "
            "would otherwise ship as a silent assumption or an unread caveat. Answer them in "
            "ONE file and re-run the same command.\n"
            "Write work/" + ANSWERS_FILE + " as {\"<id>\": \"<answer>\", ...} using each "
            "question's `id` VERBATIM and, where `options` is given, one of those exact "
            "strings.\n"
            "`asked_of` says who can answer: \"agent\" = a reading/perception call, so "
            "dispatch an ISOLATED sub-agent with the named source (never answer it from the "
            "orchestrator's own context); \"broker\" = a decision no reading can settle, so "
            "put it to the user in plain language, together, in one message.\n"
            "ANSWER ONLY WHAT YOU KNOW. Never invent an answer to clear the list - a wrong unit is "
            "a 10.76x error on a client's card, and an unanswered question is merely a disclosed one.\n"
            "TWO SORTS OF QUESTION, and `blocking` says which:\n"
            "  blocking:false - asked exactly ONCE. Unanswered it ships as the honest gap named in "
            "its `if_unanswered`, and the run proceeds.\n"
            "  blocking:true  - the run STOPS here until this is DECIDED, because the fall-through "
            "default is itself the damage (a wrong unit; or a longlist padded with options the client "
            "never shortlisted). It comes back every pass until it is decided, so do NOT just re-run: "
            "either put it to the broker and record their answer, or - if they genuinely have no "
            "preference - record an explicit decline by answering \"skip\", which ships the stated "
            "default AS A DECISION and is disclosed as one in the Gaps Report. A headless run with no "
            "broker to ask can create work/clarify.SKIP_ALL to decline all of them at once.\n"
            "NEVER answer a blocking BROKER question from your own context to clear the exit - that "
            "is exactly the presumption these questions exist to prevent. Ask the human; record a "
            "decline in their name only when they have said they have no preference."),
        "questions": questions,
    }
    out = work / QUESTIONS_FILE
    C.atomic_write_text(out, json.dumps(payload, ensure_ascii=False, indent=2))
    st = load_state(work)
    for q in questions:
        if not q.get("id"):
            continue
        if q["id"] not in st["asked"]:
            st["asked"].append(q["id"])
        if is_blocking(q):
            st["offers"][q["id"]] = int(q.get("times_asked") or 0)
        # Remember enough to DISCLOSE the decision later. questions.json only ever holds the
        # LAST batch, so without this an answer or a decline from an earlier batch could not be
        # named in the Gaps Report - and a default nobody can see is the silent presumption
        # again, one level up.
        st["titles"][q["id"]] = {
            "kind": str(q.get("kind") or ""),
            "subject": str(q.get("subject") or ""),
            "question": str(q.get("question") or "")[:400],
            "blocking": bool(is_blocking(q)),
            "if_unanswered": str(q.get("if_unanswered") or "")[:300],
        }
    save_state(work, st)
    return out


_AREA_UNITS = ("sq m", "sq ft")


def apply_answers(records: list, answers: dict) -> int:
    """Apply broker/agent ANSWERS to the records, before the dataset unit vote. Returns the
    number applied.

    WHY THIS IS NOT AN OVERRIDE, and why the override deny-list stays exactly as it is.
    `merge` refuses to let `work/overrides.json` set `areaUnit`/`rentUnit`, because an
    override is applied before the unit vote and a blind correction to the one record that
    tips it would silently relabel every figure in the dataset - the 10.76x class. That rule
    is about SILENCE. An answer here is the opposite: the pipeline asked a specific question
    about a specific source, someone answered it, and the answer is recorded with
    attribution. A broker saying "that column is sq ft" is a SOURCE STATEMENT, exactly like a
    deck printing it - so it fills the unit the same way the interpreter would, and then joins
    the vote as a KNOWN unit rather than an assumed one.

    Selection-only: an answer may only pick one of the options the question offered. It can
    never introduce a value nobody was asked about, and it never converts a number. (B38)"""
    if not answers:
        return 0
    n = 0
    for r in records or []:
        if not isinstance(r, dict):
            continue
        src = str((r.get("__meta") or {}).get("source_file") or "")
        subj = _subject(r)
        key = src or subj
        a = answers.get(qid("area_unit", key, "areaUnit"))
        if (a in _AREA_UNITS and not r.get("areaUnit")
                and any(isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)
                        for f in ("warehouseArea", "plotArea"))):
            r["areaUnit"] = a
            m = r.setdefault("__meta", {})
            m.setdefault("prov", {})["areaUnit"] = (
                f"{m.get('locator_base', '')} (unit CONFIRMED by the broker in answer to a "
                f"clarification question - the source itself states none)").strip()
            n += 1
        ru = answers.get(qid("rent_unit", key, "rentUnit"))
        if (isinstance(ru, str) and ru.count("/") >= 2 and not r.get("rentUnit")
                and isinstance(r.get("warehouseRentVal"), (int, float))):
            r["rentUnit"] = ru
            m = r.setdefault("__meta", {})
            m.setdefault("prov", {})["rentUnit"] = (
                f"{m.get('locator_base', '')} (rent unit CONFIRMED by the broker in answer to "
                f"a clarification question - the source itself states none)").strip()
            r.pop("rentUnitAssumed", None)   # it is no longer an assumption; it was answered
            n += 1
    return n


# --------------------------------------------------------------------------- #
# PRODUCERS. Each returns questions for one ambiguity class. Pure detection - no
# judgement, no guessing, and nothing here ever writes a value.
# --------------------------------------------------------------------------- #

def _subject(rec: dict) -> str:
    m = rec.get("__meta") or {}
    return str(rec.get("park") or rec.get("city") or m.get("source_file") or "?")


def unit_questions(records: list) -> list:
    """A numeric area or rent whose SOURCE stated no unit. (B38)

    The interpretation contract already requires the LLM to read the unit off the deck and
    forbids inferring it from the country - so reaching here means the source genuinely does
    not say. Nothing downstream can recover it: an unlabelled area inherits the dataset's
    dominant unit UNCONVERTED, which is a 10.76x error on the card. That is worth one
    question."""
    out = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        m = r.get("__meta") or {}
        src = str(m.get("source_file") or "")
        subj = _subject(r)
        if any(isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)
               for f in ("warehouseArea", "plotArea")) and not r.get("areaUnit"):
            area = next((r[f] for f in ("warehouseArea", "plotArea")
                         if isinstance(r.get(f), (int, float))), None)
            out.append({
                "id": qid("area_unit", src or subj, "areaUnit"),
                "kind": "area_unit", "asked_of": KINDS["area_unit"],
                "subject": subj, "source_file": src,
                "question": (f"{subj}: the source gives an area of {area:g} but never states "
                             f"whether that is sq m or sq ft. Which is it?"),
                "options": ["sq m", "sq ft"],
                "why_it_matters": ("sq m and sq ft differ by 10.76x. With no answer the "
                                   "figure keeps the dataset's dominant unit label and is "
                                   "NOT converted, so it can be wrong by that factor."),
                "if_unanswered": ("the area ships labelled with the dataset's dominant unit "
                                  "and is listed under 'Area units assumed' in the Gaps "
                                  "Report"),
            })
        # The unit may be stated in the DISPLAY STRING rather than in rentUnit - an interpreter
        # writing "€50.4 / sq m / year" has stated both currency and basis, and merge.canonicalize
        # recovers exactly that. Asking about it would be a false positive, and a question channel
        # that cries wolf is worse than no channel: it costs a round-trip and trains the
        # orchestrator to skim.
        _rent_txt_unit = None
        _disp = r.get("warehouseRent")
        if isinstance(_disp, str) and _disp.strip():
            try:
                import normalize as _N
                _rent_txt_unit = _N.rent_unit_of_text(_disp)
            except Exception:
                _rent_txt_unit = None
        if (isinstance(r.get("warehouseRentVal"), (int, float))
                and not r.get("rentUnit") and not _rent_txt_unit):
            out.append({
                "id": qid("rent_unit", src or subj, "rentUnit"),
                "kind": "rent_unit", "asked_of": KINDS["rent_unit"],
                "subject": subj, "source_file": src,
                "question": (f"{subj}: the source quotes a rent of "
                             f"{r['warehouseRentVal']:g} but states no currency and no "
                             f"per-area basis. What is the full unit?"),
                "options": ["GBP/sq ft/yr", "EUR/sq m/yr", "EUR/sq ft/yr", "GBP/sq m/yr",
                            "PLN/sq m/yr", "CZK/sq m/yr"],
                "why_it_matters": ("currency is never converted downstream (FX would be "
                                   "invention), so a wrong currency is wrong permanently."),
                "if_unanswered": ("the rent ships as the bare number marked 'unit not "
                                  "stated' - honest, but not comparable in the rent range"),
            })
    return out


def value_format_questions(findings: list) -> list:
    """The value-format gate's findings (one bare number among unit-carrying
    siblings) as BLOCKING broker questions. The gate refuses to guess - appending
    the siblings' unit means DECIDING the field is an area, and a wrong guess is
    the 10.76x class - and the remedy used to be SKILL.md prose telling the
    orchestrator to ask, the one documented prose ask and exactly the kind a
    mid-tier orchestrator drops. run.py bridges an answer into an attributed
    repairs.json entry; a decline ('leave as is' / skip) ships the bare value as
    a disclosed decision via the gate's waivers file."""
    out = []
    for f in findings or []:
        field = str(f.get("field") or "")
        printed = str(f.get("dominant_printed") or f.get("dominant_unit") or "")
        ex = ", ".join(f"'{s}'" for s in (f.get("examples") or [])[:3])
        for b in f.get("bare") or []:
            pid, val = b.get("id"), str(b.get("value"))
            out.append({
                "id": qid("value_format", f"{field}|{pid}", field),
                "kind": "value_format", "asked_of": KINDS["value_format"],
                "blocking": True,
                "subject": f"property id {pid}",
                "field": field, "property_id": pid, "bare_value": val,
                "question": (f"Property id {pid}: `{field}` reads as a bare '{val}' while "
                             f"{f.get('measured_count')} other propert(y/ies) write it with "
                             f"a unit (e.g. {ex}). What unit is '{val}' in?"),
                "options": [printed, "leave as is"],
                "why_it_matters": ("appending the siblings' unit without asking would "
                                   "silently decide what this figure measures - a count or "
                                   "a power rating relabelled as an area is the 10.76x "
                                   "error class"),
                "if_unanswered": (f"'{val}' ships bare beside unit-carrying siblings, "
                                  f"disclosed as a broker decision"),
            })
    return out


def photo_confirm_questions(doubts: list) -> list:
    """Item 3.4: an UNCERTAIN photo-brochure pairing is confirmed at DECISION time, not
    after the dashboard is built (asking 'is this the right photo?' post-build was the
    worst possible timing). Non-blocking: unanswered keeps the honest placeholder and
    the end-of-run prompt, exactly today's behaviour."""
    from pathlib import Path as _P
    out = []
    for d in doubts or []:
        br, park = str(d.get("brochure") or ""), str(d.get("park") or "?")
        if not br:
            continue
        out.append({
            # keyed on (brochure, property) - a qid on the brochure alone let one 'yes'
            # endorse it for EVERY uncertain candidate property, and auto-applied to a
            # later photo_map pairing the brochure with a DIFFERENT property
            "id": qid("photo_confirm", f"{br}|{d.get('key') or ''}", "photo"),
            "kind": "photo_confirm", "asked_of": KINDS["photo_confirm"],
            "blocking": False, "subject": park, "brochure": br,
            "question": (f"Is '{_P(br).name}' a photo of {park}?"
                         + (f" (match note: {d['note']})" if d.get("note") else "")),
            "options": ["yes", "no"],
            "why_it_matters": "a yes pulls the photo onto the card this pass",
            "if_unanswered": ("the card keeps its placeholder and the prompt repeats "
                              "at the end of the run"),
        })
    return out


MAX_DOUBT_QUESTIONS = 12   # material doubts PUT to the broker in one round
MAX_DOUBT_CARRIED = 200    # doubts carried at all, asked or merely disclosed


def agent_doubt_questions(records: list) -> list:
    """Item 3.2: a reading agent's RECORDED doubt (`__meta.doubts`: {subject, question,
    field?/fields?, materiality?, options?, default?, why_it_matters?}) becomes a
    non-blocking broker question in the same batched first round.

    MATERIALITY IS THE GATE (B62). Only a doubt that names something the client will SEE
    - a displayed field, or how many options exist - is worth stopping a run for. Every
    other doubt is stamped 'ledger', which `pending` filters out and records, and it
    ships in the Gaps Report under "Noted, not put to you" with its stated default. This
    is where the volume was: a reader's doubt about a date format or a page's tint cost a
    round-trip and changed nothing on the dashboard.

    A reader may DECLARE the classification (`field`/`fields`, or `materiality`) and that
    always beats the free-text reading.

    THE CAP IS ON ASKING, NOT ON KNOWING. Only MAX_DOUBT_QUESTIONS material doubts are put
    to the broker in one round, but the overflow is not dropped: it is stamped `over_cap`
    and returned, so `pending` records it for the Gaps Report instead of asking about it.
    The first version of this capped the material list and returned the rest to nobody -
    which lost the MOST material doubts on a big corpus (20 properties with one area doubt
    each lost 8 of them) while still disclosing the cosmetic ones, and both blind reviews
    caught it. Nothing else in the tree reads `__meta.doubts`, so a doubt that leaves here
    unrecorded is gone for good.

    The broker's answer is DISCLOSED via the Clarifications section; acting on it (an
    override/repair) stays an attributed human step - a doubt answer never mutates data
    silently."""
    qs = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        m = r.get("__meta") or {}
        subj_default = _subject(r)
        for d in (m.get("doubts") or []):
            if not isinstance(d, dict) or not str(d.get("question") or "").strip():
                continue
            subject = str(d.get("subject") or subj_default)
            q = {
                "id": qid("agent_doubt",
                          f"{m.get('source_file', '')}|{subject}|"
                          f"{str(d['question'])[:60]}", ""),
                "kind": "agent_doubt", "asked_of": KINDS["agent_doubt"],
                "blocking": False, "subject": subject,
                "question": f"{subject}: {str(d['question']).strip()}",
                "why_it_matters": str(d.get("why_it_matters")
                                      or "the reading agent recorded this as a genuine doubt"),
                "if_unanswered": (f"proceeds with: {d['default']}" if d.get("default")
                                  else "the doubt ships in the Gaps Report"),
                # classified from the DOUBT (a declared field/materiality) plus its own
                # text, not from the wrapper - the reader knows what it was torn about
                "materiality": _doubt_materiality(d, str(d["question"])),
            }
            if isinstance(d.get("options"), list) and d.get("options"):
                q["options"] = [str(o) for o in d["options"]][:6]
            qs.append(q)
    # dedupe by qid FIRST (two records sharing source_file+subject+question produce one
    # question, not two slots of the cap), then MATERIAL doubts first.
    seen_ids, deduped = set(), []
    for q in qs:
        if q["id"] in seen_ids:
            continue
        seen_ids.add(q["id"])
        deduped.append(q)
    mat = [q for q in deduped if is_material(q)]
    for q in mat[MAX_DOUBT_QUESTIONS:]:
        q["over_cap"] = True     # material, but disclosed rather than asked this round
    rest = [q for q in deduped if not is_material(q)]
    # everything travels: `pending` asks the first MAX_DOUBT_QUESTIONS and records the rest
    # for the Gaps Report, so a doubt costs the broker nothing and is lost to nobody
    out = (mat + rest)[:MAX_DOUBT_CARRIED]
    if len(mat) + len(rest) > MAX_DOUBT_CARRIED:
        # NO SILENT TRUNCATION. A corpus with this many recorded doubts is pathological, but
        # the count itself is then the finding, and it says so in the Gaps Report.
        n_more = len(mat) + len(rest) - MAX_DOUBT_CARRIED
        out.append({
            "id": qid("agent_doubt", "overflow", "count"),
            "kind": "agent_doubt", "asked_of": KINDS["agent_doubt"],
            "blocking": False, "materiality": "ledger", "over_cap": True,
            "subject": "reader doubts",
            "question": (f"{n_more} further reading doubt(s) were recorded across the "
                         f"sources and are not listed individually here"),
            "if_unanswered": ("each of those kept the source's own value; the full set is "
                              "in the extraction records under work/extract/ "
                              "(`__meta.doubts`)"),
        })
    return out


DATASET_UNIT_QID = qid("dataset_unit", "dataset area unit")
_MIXED_MIN_SHARE = 0.15   # the minority unit must be a real share, not one stray record
_MIXED_MIN_RECORDS = 2


def dataset_unit_questions(records: list) -> list:
    """The corpus states BOTH sq ft and sq m, and something must pick which the cards show.

    `merge.dominant_units` decides this by silent majority vote and the whole grid is then
    labelled in the winner, with every minority figure converted into it. That is a
    presumption of exactly the kind this channel exists to replace: on a genuinely mixed
    corpus (a UK tracker beside metric decks, or the reverse) the vote can be 20-15 and the
    broker never learns a choice was made for them.

    Deliberately narrow, because a channel that cries wolf trains the orchestrator to skim the
    questions that are precise. It fires ONLY when both units are genuinely present - each
    stated by at least _MIXED_MIN_RECORDS records, with the minority at least
    _MIXED_MIN_SHARE of the stated total. A unanimous corpus (the common case, and every
    single-country run) asks nothing."""
    from collections import Counter
    c = Counter(str(r.get("areaUnit")).strip().lower() for r in (records or [])
                if isinstance(r, dict) and r.get("areaUnit"))
    ft = c.get("sq ft", 0) + c.get("sqft", 0) + c.get("sf", 0)
    sm = c.get("sq m", 0) + c.get("sqm", 0) + c.get("m2", 0) + c.get("m\u00b2", 0)
    tot = ft + sm
    if not tot or min(ft, sm) < _MIXED_MIN_RECORDS or min(ft, sm) / tot < _MIXED_MIN_SHARE:
        return []
    lead = "sq ft" if ft >= sm else "sq m"
    return [{
        "id": DATASET_UNIT_QID,
        "kind": "dataset_unit", "asked_of": KINDS["dataset_unit"],
        "blocking": True,
        "subject": "dataset area unit",
        "question": (f"Your sources are mixed: {ft} record(s) give areas in sq ft and {sm} in "
                     f"sq m. Which unit should the dashboard show? Areas are converted to the "
                     f"one you pick (rents keep their own currency - that is never converted)."),
        "options": ["sq ft", "sq m"],
        "counts": {"sq ft": ft, "sq m": sm},
        "why_it_matters": ("the two differ by 10.76x. With no answer the majority unit wins a "
                          "silent vote and every minority figure is converted into it - "
                          "correct arithmetic, but a display convention the broker never chose "
                          "and may not want in front of this client."),
        "if_unanswered": (f"nothing is built. Answer 'skip' to accept the majority vote "
                          f"('{lead}'), which is then recorded as your decision rather than an "
                          f"assumption"),
    }]


def record_count_questions(deck_pages: dict, records_by_source: dict) -> list:
    """A deck that may hold more properties than it produced records. NOT WIRED - see below.

    ⚠ PAGE COUNT IS THE WRONG SIGNAL and this producer is deliberately not called by run.py.
    A six-page brochure describing ONE property is the *normal* case, so any
    `pages >= k * records` threshold fires on most decks. That matters more than it looks:
    every question here costs a real exit-13 round-trip, and a channel that cries wolf trains
    the orchestrator to skim it - which destroys the value of the questions that ARE precise.
    Measured on the eval fixtures, the 2x threshold fired on a legitimate 2-page/2-record deck
    and blocked the spine.

    The honest signal is semantic - several distinct scheme/unit names in the deck text against
    one emitted record - and that is a perception call Python cannot make. Kept here, unwired,
    because the QUESTION is right and only the trigger is wrong; filed as B46. (B38/B46)"""
    out = []
    for src, n_pages in sorted((deck_pages or {}).items()):
        n_rec = len(records_by_source.get(src) or [])
        if n_pages >= 3 and n_rec and n_pages >= 2 * n_rec:
            out.append({
                "id": qid("record_count", src),
                "kind": "record_count", "asked_of": KINDS["record_count"],
                "subject": src, "source_file": src,
                "question": (f"{src}: {n_pages} pages were read but only {n_rec} propert"
                             f"{'y' if n_rec == 1 else 'ies'} emitted. Does this deck "
                             f"describe more than {n_rec}? If a page shows SEVERAL "
                             f"properties they must be separate records."),
                "why_it_matters": ("a property collapsed into a neighbour's record is a "
                                   "missing option on the longlist, and nothing else "
                                   "detects it."),
                "if_unanswered": (f"the deck ships as {n_rec} propert"
                                  f"{'y' if n_rec == 1 else 'ies'}"),
            })
    return out


# ---------------------------------------------------------------- SOURCE AUTHORITY
# WHICH source decides what BELONGS on the longlist. Keyed on the source-file SUFFIX, which
# every record already carries in __meta.source_file, so this generalises to any client and
# any file naming without a per-project list. A record whose suffix is in neither family (an
# email, a loose image) belongs to no family and is therefore never used to EXCLUDE anything.
AUTHORITY_FAMILIES = {
    "tracker":   (".xlsx", ".xlsm", ".xls", ".csv", ".tsv"),
    "brochures": (".pdf", ".pptx", ".ppt"),
}
AUTHORITY_UNION = "union"          # ship everything found (the historical behaviour)
# The ONE durable id for this question. Deliberately NOT keyed on the counts that prompted it:
# an id carrying "brochures13|tracker12" changes the moment clustering merges a pair, which
# orphans the broker's answer and asks them again - exactly what qid()'s own docstring forbids
# ("keyed on the ambiguity itself, NEVER on a value").
AUTHORITY_QID = qid("source_authority", "property count")


def record_family(rec: dict) -> str:
    """'tracker' | 'brochures' | '' for ONE record, from its source file suffix."""
    src = str((rec.get("__meta") or {}).get("source_file") or "").lower()
    for fam, suffixes in AUTHORITY_FAMILIES.items():
        if src.endswith(suffixes):
            return fam
    return ""


def normalise_authority(answer) -> str:
    """Map a broker's answer onto 'tracker' | 'brochures' | 'union'.

    Tolerant by design: the answer arrives as free-ish text from a chat form, so 'tracker',
    'the tracker', 'Tracker (Excel)' and 'excel' must all land on the same branch. Anything
    unrecognised degrades to 'union' - ship everything - because the failure mode of guessing
    wrong here is DROPPING a client's property, which is never an acceptable default."""
    a = str(answer or "").strip().lower()
    if not a:
        return AUTHORITY_UNION
    if "union" in a or "both" in a:
        return AUTHORITY_UNION
    # substring match, so "the tracker", "tracker/excel" and "spreadsheet" all resolve
    if any(w in a for w in ("tracker", "excel", "spreadsheet", "xlsx", "availability")):
        return "tracker"
    if any(w in a for w in ("brochure", "deck", "pdf", "pptx", "marketing")):
        return "brochures"
    return AUTHORITY_UNION


def settled_authority(answers: dict) -> str:
    """The broker's settled source-authority choice, or 'union' when unanswered."""
    if not isinstance(answers, dict):
        return AUTHORITY_UNION
    return normalise_authority(answers.get(AUTHORITY_QID))


def source_authority_questions(extras: dict, counts=None, by_source=None) -> list:
    """Clustering has SETTLED and the two sources still disagree about what belongs.

    `extras` maps family -> [display names of the properties ONLY that family evidences], as
    computed from the final clusters (never from raw record counts: a brochure record that
    merges into a tracker row is not an extra, and asking about it wastes a round-trip and
    the broker's trust). Python cannot decide which source is guiding - that is a judgement
    about the client's own shortlist - so the broker answers, and the question NAMES the
    properties at stake so the choice can be made knowingly."""
    out = []
    if not isinstance(extras, dict):
        return out

    def _names(key):
        # DEFENSIVE: this signature changed from raw counts ({"brochures": 14}) to named
        # extras. A stale caller passing an int must get no question, never a TypeError that
        # takes the whole clarify batch down with it.
        v = extras.get(key)
        return [str(n) for n in v if str(n).strip()] if isinstance(v, (list, tuple, set)) else []

    only_b = _names("brochures")
    only_t = _names("tracker")
    if not (only_b or only_t):
        return out

    def _name_list(names: list) -> str:
        shown = names[:6]
        tail = f" (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
        return ", ".join(f"'{n}'" for n in shown) + tail

    bits = []
    if only_b:
        bits.append(f"{len(only_b)} evidenced ONLY by the brochures: {_name_list(only_b)}")
    if only_t:
        bits.append(f"{len(only_t)} evidenced ONLY by the tracker: {_name_list(only_t)}")

    # LEAD WITH THE ARITHMETIC (B49). The old text opened on two lists of names, which buries
    # the one number a broker can check against their own shortlist in a second. That framing
    # is not neutral: on the live failure it presented two 14-item lists, and any reasonable
    # reader concluded that dropping either would lose 14 options - so the answer that doubled
    # the deliverable was the only comfortable one. "17 in your tracker, 41 after the
    # brochures" is a question anybody can answer correctly.
    counts = counts if isinstance(counts, dict) else {}
    n_roster = counts.get("tracker_rows")
    n_total = counts.get("merged_total")
    head = ""
    opt_t, opt_u = "the tracker", "the union of both"
    if isinstance(n_roster, int) and isinstance(n_total, int) and n_total != n_roster:
        head = (f"Your tracker lists {n_roster} option(s), but after reading the brochures "
                f"this longlist has {n_total}. ")
        opt_t = f"the tracker's {n_roster}"
        opt_u = f"all {n_total} (the union of both)"

    # WHERE the divergence comes from, per source file. A deck that yielded 15 units while the
    # tracker lists 1 option in that town is the signature of a park-wide availability schedule
    # read as 15 separate options - the exact shape of the live failure - and naming the deck
    # turns an abstract count into something the broker can settle from memory.
    lines = []
    for row in (by_source or []):
        if not isinstance(row, dict):
            continue
        f, n_rec = str(row.get("source_file") or ""), row.get("records")
        n_ros, where = row.get("roster_options"), str(row.get("where") or "").strip()
        if not f or not isinstance(n_rec, int) or not isinstance(n_ros, int) or n_rec <= n_ros:
            continue
        lines.append(f"{f}: {n_rec} separate units read, but your tracker lists {n_ros} "
                     f"option(s)" + (f" in {where}" if where else ""))

    q = {
        "id": AUTHORITY_QID,
        "kind": "source_authority", "asked_of": KINDS["source_authority"],
        "blocking": True,
        "subject": "property count",
        "question": (head + "Some options are evidenced by only ONE of your sources - "
                     + "; ".join(bits) + ". Which source decides what belongs on this "
                     "longlist?"),
        "options": [opt_t, "the brochures", opt_u],
        "only_in_brochures": only_b,
        "only_in_tracker": only_t,
        "why_it_matters": ("this decides whether those options are MISSING from the longlist or "
                           "are EXTRAS the client never shortlisted. A brochure usually "
                           "advertises every unit on its park, and those neighbours are real "
                           "buildings but not necessarily options on this brief - shipping "
                           "them pads a client-facing longlist. Everything excluded is named "
                           "in the Gaps Report, never dropped silently."),
        "if_unanswered": ("nothing is built. This one BLOCKS because its old default - ship "
                          "the union - is what put 24 unrequested options on a client "
                          "dashboard. Answer 'skip' to take the union deliberately, and it is "
                          "recorded as your decision rather than an assumption"),
    }
    if lines:
        q["where_they_come_from"] = lines
        q["question"] += (" The divergence is concentrated here - " + "; ".join(lines[:4])
                          + (f" (+{len(lines) - 4} more)" if len(lines) > 4 else "") + ".")
    out.append(q)
    return out
