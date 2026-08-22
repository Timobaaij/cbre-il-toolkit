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
}

# The kinds whose DEFAULT IS THE DAMAGE, so silence must not resolve them (B49):
#   source_authority - the default ships every phantom extra (the live 41-vs-17 failure)
#   dataset_unit     - the default silently relabels half a mixed dataset, 10.76x out
#   area_unit /      - an unlabelled figure inherits a unit it was never measured in, which
#   rent_unit          is the 10.76x error class this whole skill exists to avoid
BLOCKING_KINDS = {"source_authority", "dataset_unit", "area_unit", "rent_unit"}

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
    return st


def save_state(work, st: dict) -> Path:
    """WRITE ONLY WHEN THE CONTENT DIFFERS - this file is a merge resume input.

    An unconditional write bumps the mtime on every pass, and because clarify_state.json is a
    merge input (so a freshly-answered question cannot be resume-skipped), that made merge ->
    build -> deliver all re-fire on a no-change resume. `ingest_answers` runs on EVERY pass, so
    the churn was guaranteed. Same rule, and the same reason, as run._write_if_changed."""
    p = _state_path(work)
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


def skip_all(work) -> bool:
    """The non-interactive escape: every blocking question is treated as explicitly declined.

    For a headless/cron run with no broker to ask. Deliberately a FILE (or a project.yaml
    flag), never the default - an unattended run must opt in to presuming, and the Gaps Report
    still names every default it took."""
    if (Path(work) / SKIP_ALL_FILE).exists():
        return True
    try:
        import yaml  # optional dependency; absent -> the file is the only escape
        cfg = yaml.safe_load((Path(work).parent / "project.yaml").read_text(
            encoding="utf-8-sig")) or {}
        return bool((cfg.get("clarify") or {}).get("assume_defaults"))
    except Exception:
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
      one-step, always-available exit, and both are recorded as a decision."""
    st = load_state(work)
    asked = set(st.get("asked") or [])
    answered = set(st.get("answers") or {})
    declined = declined_ids(work)
    seen, out = set(), []
    for q in questions:
        i = q.get("id")
        if not i or i in seen:
            continue
        if i in answered or i in declined:
            continue
        if i in asked and not is_blocking(q):
            continue
        seen.add(i)
        out.append(q)
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
