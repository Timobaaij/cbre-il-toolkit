#!/usr/bin/env python3
"""repairs.py - PROPERTY-KEYED corrections, applied after the merge.

WHY THIS EXISTS, given `overrides.json` already corrects data.

`overrides.json` targets a SOURCE RECORD - a spreadsheet row, a brochure page - and is
applied during extraction, before anything is matched or merged. That is the right shape
for "this cell was mis-transcribed". It is the wrong shape for the other half of the work,
which only becomes visible AFTER the merge: a value that survived precedence but is wrong
for the property, a field the property lacks entirely, a plausibility gate that struck a
figure the source plainly states, a hero photo bound to the wrong building.

Every repair of that kind in a live run had to be expressed as a source-record override,
which meant finding which of several records supplied the value, and re-running the whole
spine to see the effect. Worse, a per-property fix has a dataset-wide blast radius: a
corrected area re-derives the cluster anchors, which re-keys settled conflict decisions and
triggers a fresh adjudication round for one changed pair. That cost is what this module
removes. A repair names the PROPERTY, is applied once the properties exist, and touches
nothing else.

WHAT IT IS NOT. It is not a way to write into `canonical.json` by hand. Repairs are declared
in one auditable, re-applied file; they run BEFORE the pre-build gates, so validate-data,
arithmetic, coverage and trace-coverage all judge the repaired dataset exactly as they judge
any other; and every applied field writes its own Source Ledger row. A repair is therefore
disclosed in the same breath as it is made, never laundered into looking like source data.

The projection under `work/properties/` is READ-ONLY and is not the input here. Two writable
representations of the same dataset is a drift bug waiting to happen; the projection is a
view, this file is the edit.

THE VERBS. `set` writes a value. Two more, both strictly ADDITIVE - an entry that uses neither
behaves exactly as it did before they existed:
  * `unset`: a list of field names to CLEAR. Cleared means the key is REMOVED from the
    property, NOT overwritten with a sentinel. Writing "tbd" over a field would be
    indistinguishable from a source that stated "tbd", and the ledger row would then say the
    repair SET a value when what the operator did was withdraw one. Removal is unambiguous and
    it is also the honest state: the property is back to what it looks like when no source ever
    stated the field, and `_common.fill_render_sentinels` re-fills every chrome-read key with
    its own honest unknown at the RENDER boundary (on a copy - see build_dashboard/gate_runner),
    so nothing the template reads can vanish while a genuinely off-spec key genuinely goes.
    A field the SCHEMA lists as required is refused instead: popping one leaves canonical
    un-schema-valid and validate-data hard-blocks the build, so a one-card correction would
    cost the whole run. Its honest unknown is a sentinel VALUE, which is `set`'s job.
    A NAME THE RESOLVED PROPERTY DOES NOT CARRY CLEARS NOTHING AND IS REPORTED `stale`. It used
    to be reported APPLIED, with a bracketed already-absent tail and a Source Ledger row for the
    field - so `unset: ["oddKeyy"]` against a property carrying `oddKey` read as a successful
    clear to anyone triaging the report, and minted a `repair` row for a field that exists on no
    schema and on no property. Both are audit-integrity failures: this module's own invariant is
    that a repair row's field already has its own property row, and the APPLIED bucket means a
    value moved. `stale` is true of both readings - a correctly re-applied clear whose key is
    already gone, and a misspelling - so both now read as the no-op they are, in a bucket an
    operator scans, and neither writes a row. The Source Ledger is consulted only to say WHICH
    reading it is in the message: its `record_type=property` rows survive a full re-merge (the
    sources still state the field) whereas the prior clear's own `repair` row does not, so a
    verdict resting on the repair row would flip between a resumed run and a full one. The
    message is therefore sharpened by the ledger; the bucket and the (absent) row are decided by
    the property alone, and are the same answer either way.
  * `strike_from_source`: ONE source filename. Removes every field on the target whose
    merge-time provenance names that file. Nineteen hand-listed field names is the wrong shape
    of instruction for unfusing two records a matcher wrongly merged: the instruction is "this
    property carries nothing from that file", and the Source Ledger already records enough to
    execute it deterministically (merge drops the record's `__meta` at the choke point, so the
    ledger IS the merged property's provenance). Matched on basename, case-insensitively, the
    same rule the override channel applies to `where.source_file`. Zero fields matched is a
    STALE entry, never a silent no-op. Because the strike resolves its fields OUT OF the ledger,
    every field it clears provably has a property row, so it re-writes its disclosure row on
    every run even once the field is gone - the asymmetry with `unset` above is evidence, not
    taste.
    AN AMBIGUOUS FILENAME STRIKES NOTHING. The basename is still the match key, but a basename
    alone is no longer allowed to be the whole answer: a folder of property materials from
    several senders routinely holds two files with one common name, and matching a bare
    `deck.pdf` against a ledger crediting `inbox/a/deck.pdf` with one field and
    `inbox/b/deck.pdf` with another struck BOTH - silently deleting correct, sourced data and
    writing a row that credited the deletion to a file which never supplied it. The override
    channel's identical targeting clause is not a precedent for keeping that: it can be narrowed
    further by page, row and sheet, and it SUBSTITUTES rather than DELETES. So when two or more
    genuinely different ledger paths share the requested basename the entry is AMBIGUOUS and
    applies nothing, naming the competing paths verbatim; the operator disambiguates by
    re-stating `strike_from_source` with enough LEADING FOLDERS to pick one out (a full path
    works, and so does any trailing part of one, matched segment-wise). Two paths where one is a
    trailing part of the other are the SAME file recorded at different depths, which is the case
    basename matching exists for, and stay one target.

CITING EVIDENCE. `source_file` and `source_locator` are optional top-level keys that replace
the ledger columns of the same name. Every repair row used to be stamped `repairs.json` with
the repair's own id as its locator, so provenance could tell a reviewer that a correction
happened but not where the value came from - which is the reviewer's next question and the one
the Source Ledger exists to answer. Present, they win; absent, today's values stand unchanged.
The override channel takes the same two keys with the same semantics, so one habit works on
both. Note that a cited page is then EVIDENCE the prov-containment gate can check, so cite the
page the value actually occurs on.

GUARDS, all failing CLOSED - an entry that cannot be resolved with certainty applies NOTHING
and is reported, because a repair landing on the wrong card is worse than a repair that did
not land:
  * `property.key` must match a property's match_key. `property.id` is a second confirmation.
    Given both, they are INTERSECTED: a key several properties share (every multi-unit park
    shares one) is disambiguated by the id, while an id outside the key's matches is a real
    disagreement -> AMBIGUOUS.
  * zero matches -> STALE. More than one, with nothing to disambiguate -> AMBIGUOUS.
  * `expect` is compared against the property's CURRENT values; any mismatch -> SUPERSEDED.
    This is what makes the entry safe across a re-match: if identity moved under it, the
    guard fires instead of the value. Absence is one bucket for this comparison: a field a
    gate struck holds None but reads as the blank sentinel everywhere a human looks, so
    `expect: {"f": "tbd"}` matches it (see `_expect_same`) - and still does after v45 changed
    the sentinel, because 'tbd' remains a recognised unknown FORM even though it is no longer
    the one written.
  * a denied field -> INVALID. `id`/`photo`/`gallery`/`plan`/`preBaked` are structural or
    media (media has its own key); `areaUnit`/`rentUnit` are denied for the same reason
    overrides deny them - they relabel every figure at once, which is the 10.76x error class.
  * a field that is the SOURCE of a DERIVED twin (`merge.DERIVED_TWINS`, e.g. `officeArea` ->
    `officeAreaVal`) is INVALID to `set` or `unset` unless the same entry also sets (or, for a
    clear, unsets) the twin, and the message names the twin. Same doctrine as `areaUnit`: a
    field that cannot change safely in isolation. Refused LOUDLY rather than half-landed,
    because a repair that lands on the card and silently not on the figure summed from it is
    the wrong-card hazard one level up. Inert when merge exposes no registry.
  * a `set` value that will not SURVIVE the normalisers that run AFTER repairs is INVALID
    (D12). Merge re-derives every property once the repairs stage has written
    (`merge.rederive_after_repairs` -> `_rederive_property`), and two of its steps rewrite a
    field ONTO ITSELF: `motorway` is condensed to a card-sized locator by
    `normalize.short_motorway` (anything over `MOTORWAY_MAX` characters), `country` is coerced
    to its ISO code by `normalize.country_iso`; run.py then re-runs the render-boundary
    coercion (`_common.fill_render_sentinels`) over canonical too. On the measured run four
    repairs restored motorway lists merge had truncated, all four exceeded the limit, all four
    were condensed straight back to the value they were correcting, and this module reported
    every one of them APPLIED with a full before-and-after: no STALE, no SUPERSEDED, no note.
    An operator trusting the report would have shipped a Source Ledger row asserting a value
    the delivered pack does not contain; the live operator caught it only by re-reading
    canonical by hand and withdrew the four entries. The card-fit behaviour itself is right
    and is untouched here. What this guard adds is the honest verdict: the value is run
    through the same normalisers BEFORE anything is written (`survives_downstream`), and an
    entry whose value would come back different is refused with the limit named, the form it
    would have become shown, and the two ways out stated (a value that already fits, or the
    condensed form written deliberately). The registry of post-repair normalisers is
    `POST_REPAIR_NORMALISERS`, one line per field, so the next one is an addition there and
    not a rediscovery of this defect. INVALID rather than superseded because the verdict is a
    property of the entry's own value and holds on every run; a form-only type coercion
    (`loadingDocks: 12` -> "12") reads back as the same value and is NOT refused.
  * a `set` key must be one the SCHEMA declares OR one the RESOLVED TARGET property
    already carries; a name on NEITHER -> INVALID. An `unset` key is held to the RESOLVED
    property in the same breath, but its failure is `stale` rather than INVALID: a clear cannot
    conjure a field, so the honest report of one that finds nothing is "this changed nothing",
    not "this entry is malformed" - and INVALID would make a correctly re-applied clear refuse
    itself for good on its second run. The check was schema membership alone, which
    read as an anti-typo guard but behaved as "you may only correct a field the template knows
    about". The extraction contract deliberately emits a stated row with no canonical home
    under a descriptive key, so off-spec keys are a normal and LARGE part of every record - and
    a value already on the record, in an off-spec key, and wrong, could be corrected by
    neither channel: the pre-merge one cannot address a merged property, and this one refused
    the key. Beside a matcher over-merge that is a hole with no floor. Widened to schema OR
    record, which is what the message always claimed; a name on neither still cannot conjure a
    field, which is the whole point of the guard and is untouched. Mirrors the same widening on
    the override loader (its `extra_fields`, B7), and `load` takes the same parameter.
  * `why` and `verified_by` are REQUIRED and non-empty; both ship in the ledger.

VALIDATING ENTRIES ALREADY IN HAND. `load(path)` reads the file and delegates every per-entry
check to `validate_entries(entries, extra_fields)`; `validate_entry(entry)` is the one-entry
form. Both are module-level so the answer-to-repair bridges in run.py can screen an entry they
are ABOUT to write with the same rules that will judge it here - the generator once emitted
entries its own validator then refused (D4), which is a broker's answer recorded and dropped.

CLI (offline, used by run.py and by hand):
  python repairs.py apply --work <dir>          apply to <work>/canonical.json in place
  python repairs.py check --work <dir>          report only, change nothing
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402
import normalize as _N  # noqa: E402

try:
    import match as _match
except Exception:                                    # pragma: no cover - offline shim
    _match = None

# DERIVED TWINS (F24c). Several shipped values are DERIVED by merge from another field and
# nothing downstream re-derives them, so a repair to the source alone leaves the twin stale:
# on a live pack every property whose office area came through merge carried a matching
# `officeAreaVal`, the two whose office area came from a repair carried None, and their
# modals printed a unit-less string while the Total GLA silently excluded the office. Every
# mechanical gate was green. The registry is merge's (`merge.DERIVED_TWINS`, source -> twin);
# it is resolved LAZILY and DEFENSIVELY because merge is a heavy import and the registry may
# not exist yet in an older merge: with no registry the guard is inert, and
# `derived_twins_source()` says so rather than pretending. Set the module-level override to a
# dict to pin the registry (the evals do); None means "ask merge".
DERIVED_TWINS: dict | None = None
_TWINS_CACHE: tuple[dict, str] | None = None


def _derived_twins() -> tuple[dict, str]:
    """(source -> derived field, where it came from). Never raises; an absent registry is {}."""
    global _TWINS_CACHE
    if DERIVED_TWINS is not None:
        return dict(DERIVED_TWINS), "override"
    if _TWINS_CACHE is None:
        try:
            import merge as _merge
            reg = getattr(_merge, "DERIVED_TWINS", None)
            _TWINS_CACHE = (dict(reg), "merge") if isinstance(reg, dict) else ({}, "absent")
        except Exception:                            # pragma: no cover - merge not importable
            _TWINS_CACHE = ({}, "absent")
    return _TWINS_CACHE


def derived_twins_source() -> str:
    """'merge', 'override', or 'absent' (guard inert because no registry could be found)."""
    return _derived_twins()[1]


def _rederive_available() -> bool:
    """True when merge can refresh a derived twin after the repairs stage.

    Read live rather than cached: the two halves of this fix were built separately and an
    installation may carry one without the other, which is exactly the state that made a
    one-field rent repair impossible. Any import or attribute failure answers False, so the
    guard falls back to REFUSING, which is the safe direction: a stale twin is a wrong number
    on a client card."""
    try:
        import merge as _MG
        return callable(getattr(_MG, "rederive_after_repairs", None))
    except Exception:
        return False


def _stranded_twins(sets: dict, unset: list) -> list[str]:
    """Reasons an entry would strand a derived twin; empty when it is safe.

    A `set` of a source field must `set` its twin in the same entry. An `unset` of a source
    must `unset` the twin too, or `set` it (to null is the natural form for a nullable
    numeric): clearing the human-read string while the derived number stays populated is the
    same hazard in reverse, the Total GLA keeps counting an office the modal now calls tbd.
    Setting the TWIN alone is deliberately not refused here: it is a direct correction of the
    derived value, not a stranding, and whether re-derivation may overwrite it is merge's
    contract (see merge.rederive_after_repairs), not this guard's.
    """
    # SCOPED TO THE CASE THIS WAS WRITTEN FOR: an installation where nothing refreshes the twin.
    # The defect is real - a live pack shipped two properties whose `officeAreaVal` was None
    # because the office area came from a repair, so their modals printed a unit-less string and
    # their Total GLA silently dropped the office. But `merge.rederive_after_repairs` now exists
    # and refreshes exactly these twins after the repairs stage, and refusing as well made the
    # MOST ORDINARY correction there is impossible: `warehouseRent` and `warehouseRentVal` are
    # registered as a twin pair in BOTH directions, so a one-field rent repair was rejected
    # outright and a long-standing eval went red. Two halves of one fix, each defensible alone
    # and wrong together, because neither author could see the other's half.
    #
    # So when merge CAN re-derive, a twin-source repair is allowed: asking an operator to
    # hand-write a number the pipeline computes is how a wrong number gets typed. When it
    # cannot, the refusal stands and now says so accurately instead of claiming that nothing
    # re-derives.
    if _rederive_available():
        return []
    twins, _ = _derived_twins()
    out = []
    for f in sorted(twins):
        twin = twins[f]
        if f in sets and twin not in sets:
            out.append(f"`{f}` is the SOURCE of the DERIVED field `{twin}`, which merge computes "
                       f"from it, and THIS INSTALLATION'S merge exposes no "
                       f"`rederive_after_repairs`, so nothing will refresh it. Setting `{f}` "
                       f"alone leaves `{twin}` stale (the card and every figure summed from it "
                       f"would disagree), so this entry must ALSO `set` `{twin}`")
        elif f in unset and twin not in unset and twin not in sets:
            out.append(f"`{f}` is the SOURCE of the DERIVED field `{twin}`, which merge computes "
                       f"from it, and THIS INSTALLATION'S merge exposes no "
                       f"`rederive_after_repairs`. Clearing `{f}` alone leaves `{twin}` populated "
                       f"from a value the card no longer shows, so this entry must ALSO `unset` "
                       f"`{twin}` (or `set` it to null)")
    return out

# structural, media-owned, or dataset-wide unit labels: never settable by a repair
DENIED_FIELDS = frozenset({
    "id", "photo", "gallery", "plan", "preBaked",
    "areaUnit", "rentUnit",
})
MEDIA_SLOTS = ("hero", "plan")
REPORT_KEYS = ("applied", "stale", "ambiguous", "superseded", "invalid")
LEDGER_NAME = "source_ledger.csv"
# the ledger rows that are a merged property's own provenance (see `read_provenance`)
LEDGER_PROV_RECORD_TYPE = "property"
# What a CLEAR reports as its new value. NOT None: deliver.py renders `from` -> `to` verbatim
# into the client-facing Gaps Report and "-> None" is not a sentence anyone can read. NOT
# "tbd" either: the whole point of the verb is that the field was WITHDRAWN, not set to the
# sentinel, and a report row that cannot tell those apart is the ambiguity this replaces.
CLEARED = "(cleared)"

_SCHEMA_REQUIRED_FIELDS = None


class SchemaRequiredUnavailable(RuntimeError):
    """The canonical schema's required-property list could not be resolved, so the guard that
    refuses a clear of a required field cannot be armed. Its own class, not a bare Exception,
    so the two call sites can catch exactly this and nothing else - a JSON error inside a
    repair entry must never be laundered through the same handler."""


def _schema_required_fields() -> frozenset:
    """The property keys the canonical schema lists as REQUIRED. Read from the schema, never
    hand-listed, so a schema edit cannot leave this stale.

    A required key may not be CLEARED: an absent one leaves canonical un-schema-valid and
    validate-data hard-blocks, which turns a one-card correction into a dead run.

    RAISES rather than defaulting. It used to swallow every exception into an EMPTY frozenset,
    on the argument that repairs run before the gates so an unjustifiable refusal is judged
    there anyway. That argument is backwards for this particular guard: an empty set refuses
    NOTHING, so renaming `$defs.property`, moving `required`, or shipping an unreadable schema
    would silently DISARM the one check standing between a one-line clear and a hard-blocked
    run - and the gate it defers to is the very gate that hard-blocks. A guard that quietly
    turns itself off is worse than no guard, because the operator believes it is on. An empty
    `required` array counts as unresolved for the same reason: this schema has always declared
    some, so none is a restructure, not a decision. Neither failure is cached, so fixing the
    schema needs no restart."""
    global _SCHEMA_REQUIRED_FIELDS
    if _SCHEMA_REQUIRED_FIELDS is None:
        try:
            schema = json.loads(Path(C.SCHEMA_FILE).read_text(encoding="utf-8-sig"))
            req = ((schema.get("$defs") or {}).get("property") or {}).get("required") or []
            got = frozenset(str(k) for k in req)
        except Exception as e:
            raise SchemaRequiredUnavailable(
                f"the canonical schema could not be read ({type(e).__name__}: {e}), so the "
                f"guard that refuses a clear of a SCHEMA-REQUIRED field cannot be armed - "
                f"applied NOTHING rather than clear a key that would hard-block validate-data "
                f"for the whole run. Fix {Path(C.SCHEMA_FILE).name} and re-run") from e
        if not got:
            raise SchemaRequiredUnavailable(
                f"{Path(C.SCHEMA_FILE).name} declares no required property fields at "
                f"$defs.property.required, so the guard that refuses a clear of a "
                f"SCHEMA-REQUIRED field would refuse nothing - applied NOTHING rather than run "
                f"a disarmed guard. Check whether that path was renamed or moved")
        _SCHEMA_REQUIRED_FIELDS = got
    return _SCHEMA_REQUIRED_FIELDS


def _required_fields_or_reason() -> tuple[frozenset, str | None]:
    """(the schema's required property keys, or a refusal message when they cannot be resolved).

    ONE definition, used by `load`'s screen and by `apply`'s, so the two can never disagree
    about what is required, and so neither can turn a resolver failure into an empty set on its
    own. Both callers convert the message into a per-ENTRY refusal rather than letting it
    propagate: the entry that asked for a clear is the one that must fail, out loud, in the
    report an operator actually reads - a raise here would be swallowed by run.py's
    stage-level handler into one line of stderr and would also refuse entries that clear
    nothing."""
    try:
        return _schema_required_fields(), None
    except SchemaRequiredUnavailable as e:
        return frozenset(), str(e)


def _path_parts(v) -> tuple:
    """A source path as lower-cased path SEGMENTS, separator-agnostic.

    The ledger records whatever path the reader that wrote the row happened to hold: a bare
    filename from one extractor, a work-dir-relative path from another, backslashes from a
    third. Segments are the only unit on which a comparison can treat those as one file
    WITHOUT also treating `inbox/a/deck.pdf` and `inbox/b/deck.pdf` as one - and conflating
    those two is what silently deleted correct, sourced data. Never `str.endswith`: that would
    read `a/deck.pdf` as part of `extra-a/deck.pdf`."""
    s = str(v or "").strip().lower().replace("\\", "/")
    return tuple(seg for seg in s.split("/") if seg and seg not in (".", ".."))


def _basename(v) -> str:
    """Filename identity for a strike: basename, lower-cased. The SAME rule the override
    channel applies to `where.source_file` (`_ov_record_matches`), so a work-dir path and a
    bare filename can never decide whether a correction applies.

    It is still the MATCH KEY and nothing about that changed. What changed is that it is no
    longer the whole answer: see `_strike_targets`, which requires the matched basename to
    resolve to ONE file before a deletion is allowed to proceed."""
    parts = _path_parts(v)
    return parts[-1] if parts else ""


def _is_under(inner: tuple, outer: tuple) -> bool:
    """True when `inner` is a PROPER segment-suffix of `outer`, i.e. the two ledger paths are
    the same file recorded at different depths (`deck.pdf` under `work/inputs/deck.pdf`). That
    is exactly the unification basename matching exists for and the shape the repair evals
    already pin, so it stays ONE target; it is also the one residual risk knowingly accepted
    here, because a nested duplicate directory (`a/deck.pdf` beside `dup/a/deck.pdf`) is
    indistinguishable from it without reading the disk, which this module never does."""
    return 0 < len(inner) < len(outer) and outer[-len(inner):] == inner


def _verbs(e: dict) -> tuple[dict, list, str]:
    """(set, unset, strike filename) as `apply` needs them. One definition, used by `load`'s
    validation and by `apply`, so the two can never disagree about what an entry asked for."""
    sets = e.get("set") if isinstance(e.get("set"), dict) else {}
    unset = [str(k).strip() for k in (e.get("unset") or []) if str(k or "").strip()]
    return dict(sets or {}), unset, str(e.get("strike_from_source") or "").strip()


def read_provenance(path) -> list | None:
    """A merged property's per-field provenance, read back from the Source Ledger.

    A merged property does not carry any: merge strips the contributing record's `__meta` at
    the choke point that keeps working flags off a client card, and writes one ledger row per
    populated field instead. So the ledger IS the provenance of record, and it is the only
    thing that can answer "which fields on this property came from that file" - the question
    `strike_from_source` is.

    Only `record_type=property` rows count: those are merge's own attribution of a SHIPPED
    value to a file. A `gap` row attributes nothing (its source_file is literally "(none)"),
    an `offspec` row describes a structure that was quarantined and never reached the
    property, and a `repair`/`override` row is a disclosed correction whose field already has
    its own property row - striking off one of those would let a correction delete itself.

    -> None when there is no ledger to read. "I could not look" and "that file contributed
    nothing" are different answers and must never print the same one."""
    p = Path(str(path or ""))
    if not str(path) or not p.exists():
        return None
    try:
        # an accumulated conflict_note legitimately exceeds Python's defensive default, exactly
        # as ledger.py records - a long value, not a memory bomb
        csv.field_size_limit(2 ** 31 - 1)
    except Exception:
        pass
    try:
        with open(p, newline="", encoding="utf-8-sig") as fh:
            return [r for r in csv.DictReader(fh)
                    if (r.get("record_type") or "").strip() == LEDGER_PROV_RECORD_TYPE
                    and (r.get("source_type") or "").strip().lower() != "gap"]
    except Exception:
        return None


def _prov_index(rows) -> dict:
    """-> {property_id: {field: {path segments: the path AS THE LEDGER WROTE IT}}}.

    The FULL path is kept now, not the basename it used to collapse to. A basename-only index
    cannot tell two same-named files apart, and a folder of property materials from several
    senders holding two files with one common name is an ordinary shape for this pipeline - so
    a strike naming one of them removed the other's fields too, silently, and disclosed the
    removal against the wrong file. The path as written is carried alongside the segments so an
    AMBIGUOUS report can quote the competing paths verbatim, which is what the operator pastes
    back into `strike_from_source` to disambiguate."""
    idx: dict = {}
    for r in rows or []:
        pid = str(r.get("property_id") or "").strip()
        fld = str(r.get("field") or "").strip()
        raw = str(r.get("source_file") or "").strip()
        parts = _path_parts(raw)
        if not pid or not fld or not parts or parts[-1] == "(none)":
            continue
        idx.setdefault(pid, {}).setdefault(fld, {}).setdefault(parts, raw)
    return idx


def _strike_targets(fields: dict, request) -> tuple[list, list, str]:
    """Resolve ONE `strike_from_source` filename against ONE property's ledger paths.

    -> (fields to strike, competing paths, the resolved path). A `competing` list is returned
    ONLY when the request cannot be pinned to a single file, and then the caller must apply
    NOTHING: this verb DELETES, so an unresolved target is a silent data loss, not a
    near-miss. Empty everything means the file credits this property with no field at all,
    which is the pre-existing STALE outcome and is unchanged.

    Three steps, in this order and for these reasons:
      1. CANDIDATES ARE THE BASENAME MATCHES - today's rule, byte for byte, so a work-dir path
         in the ledger and a bare filename in the entry still name the same file and every
         single-file run behaves exactly as it did.
      2. A REQUEST CARRYING FOLDERS NARROWS THEM, segment-wise from the right. This is what
         gives the operator a way out of an ambiguity: `a/deck.pdf` picks `inbox/a/deck.pdf`
         out of its `inbox/b/deck.pdf` sibling without having to know the full prefix. A
         narrowing that matches nothing falls BACK to the basename candidates, because a
         work-dir path the entry supplies need not resemble the path the extractor recorded
         (`some/where/deck.pdf` against a ledger holding `deck.pdf`), and that shape works
         today - newly sending it STALE would be its own regression.
      3. WHAT SURVIVES MUST BE ONE FILE. A candidate that is a proper segment-suffix of another
         candidate is the same file at a shallower depth and is dropped; anything left over is a
         genuinely different file. More than one -> the caller reports AMBIGUOUS.
    The struck fields are then every field credited to ANY surviving-or-subsumed candidate, so a
    property whose ledger records one file as both `deck.pdf` and `work/inputs/deck.pdf` still
    loses both fields, which is the whole point of matching on basename in the first place.
    """
    want = _path_parts(request)
    base = want[-1] if want else ""
    if not base:
        return [], [], ""
    cands: dict = {}
    for paths in (fields or {}).values():
        for parts, disp in paths.items():
            if parts[-1] == base:
                cands.setdefault(parts, disp)
    if not cands:
        return [], [], ""
    if len(want) > 1:
        narrowed = {p: d for p, d in cands.items()
                    if len(p) >= len(want) and p[-len(want):] == want}
        if narrowed:
            cands = narrowed
    # the MAXIMAL candidates under `_is_under`. A strict partial order on a finite non-empty
    # set always has one, so this is never empty.
    competing = {p: d for p, d in cands.items()
                 if not any(_is_under(p, q) for q in cands if q != p)}
    if len(competing) > 1:
        return [], sorted(competing.values()), ""
    named = sorted(f for f, paths in (fields or {}).items()
                   if any(p in cands for p in paths))
    return named, [], next(iter(competing.values()))


def _mk(rec: dict) -> str:
    if _match is not None:
        try:
            return _match.match_key(rec)
        except Exception:
            pass
    return "|".join(str(rec.get(k, "") or "").strip().lower()
                    for k in ("city", "developer", "park"))


def _image_uri(src: Path, slot: str):
    """Compress a supplied image the SAME way the pipeline compresses every other one, so a
    repaired hero is indistinguishable in weight and encoding from a harvested one. Returns
    None when the file is not a decodable image - reported, never silently skipped."""
    try:
        import images as IMG
    except Exception:
        return None
    try:
        img = IMG._open(src.read_bytes())
        if img is None:
            return None
        edge = IMG.PLAN_MAX_EDGE if slot == "plan" else IMG.HERO_MAX_EDGE
        return IMG.to_data_uri(IMG.compress(img, edge, IMG.DEFAULT_BUDGET_KB))
    except Exception:
        return None


def _same(a, b) -> bool:
    """Value equality that survives the int/float and whitespace noise of hand-written JSON."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return str(a).strip() == str(b).strip()


# The absence family for the `expect` guard ONLY (SEAM-13). It DELEGATES to
# normalize.UNKNOWN_FORMS - there is no private literal here any more - but reads a NARROWER
# slice of it, stated as a rule rather than a second list: a SENTINEL TOKEN (empty, pure
# punctuation, or an abbreviation of at most three letters: tbd, tbc, tba, tbs, ??, n/a, poa,
# the dash) is absence; a market PHRASE ("a consultar", "auf anfrage", "to be confirmed") is a
# broker's stated words and still trips the guard, exactly as before (expect_sentinel_test
# pins it). Two further consequences of delegating, both deliberate:
#   * a stated `none`/`None` is DATA, not absence (contract C5, the extraction contract names
#     it as a stated negative). The old literal carried it as absence, so `expect: {"f":
#     "tbd"}` against a field holding "none" used to MATCH and now SUPERSEDES, and `expect:
#     {"f": "none"}` against a struck field (None) used to match and now supersedes too. Both
#     are right: the card shows "none" for the first and "tbd" for the second, and the guard
#     compares against what the operator reads.
#   * the bare assigned alpha-2 codes normalize exempts for CODE fields (`CODE_LIKE_EXEMPT`:
#     na, nc, sc) are excluded here as well, because this guard cannot tell a country field
#     from a rent field and the old literal never carried them, so nothing regresses.
# Measured on three live canonicals (56 properties, 3,719 scalar values): zero values move.
def _expect_sentinel_token(t: str) -> bool:
    """True for a normalised form that is a placeholder token rather than a phrase."""
    core = t.replace(".", "").replace("/", "")
    return t == "" or not any(ch.isalpha() for ch in t) or len(core) <= 3


def _absent_like(v) -> bool:
    if v is None:
        return True
    if not _N.looks_unknown(v):
        return False
    t = str(v).strip().lower().rstrip(".")
    return _expect_sentinel_token(t) and t not in _N.CODE_LIKE_EXEMPT


# the family this guard actually reads, derived from the master for introspection and evals
_EXPECT_ABSENT = frozenset(f for f in _N.UNKNOWN_FORMS if _absent_like(f))


def _expect_same(cur, want) -> bool:
    """Equality for the `expect` guard, where BOTH SIDES ABSENT counts as a match.

    A field a plausibility gate struck holds None, but every surface a human reads - the card,
    the Source Ledger, the Gaps Report, work/properties/<id>/notes.md - displays it as `tbd`.
    So `expect: {"warehouseArea": "tbd"}`, which is the value the docs invite you to write,
    could never match and every such entry returned SUPERSEDED. One live run lost a batch of
    17 repairs and a full re-run to exactly that. `_same` itself is untouched, so this widening
    reaches the guard and nothing else.
    """
    return _same(cur, want) or (_absent_like(cur) and _absent_like(want))


# --- POST-REPAIR NORMALISERS (D12) ----------------------------------------------------------
# The normalisers a repaired value passes through AFTER this module has written it, keyed by the
# field they act on. `merge._rederive_property` runs after the repairs stage and applies each of
# these to the field ON ITSELF; a value they change is a value the pack will never carry as the
# operator wrote it. `_rederive_property` guards `country` with `not looks_unknown_code` and
# `motorway` with `isinstance(str) and strip()`, and the wrappers below mirror those guards so
# this prediction and merge's rewrite cannot disagree on an edge.
#
# ONE LINE PER FIELD, deliberately. The four discarded motorway repairs on the measured run were
# not found by any gate; they were found by an operator re-reading canonical by hand. The next
# post-repair normaliser merge grows must be an ADDITION here, not a second hunt for the same
# false-success report. Each value is (callable, operator-facing description of the stage).
#
# KNOWN, NOT REGISTERED: the rent pair. `_rederive_property` regenerates `warehouseRent` from a
# repaired `warehouseRentVal` (and re-parses the numeric from a repaired display string) through
# `normalize.rent_display`, which needs the property's `rentUnit` and the twin's value - it is
# a property-level derivation, not a field-on-itself normaliser, and merge's contract states it
# owns that pair (see `_stranded_twins`). A display string an operator writes in a non-canonical
# form ("£9.50 psf") therefore ships regenerated ("£9.5 / sq ft / year"); the FIGURE survives,
# and the report's `to` shows the operator's spelling. Recorded here so it is a known gap.
POST_REPAIR_NORMALISERS: dict = {
    "motorway": (
        lambda v: _N.short_motorway(v)[0] if isinstance(v, str) and v.strip() else v,
        f"merge's card-fit condensing of `motorway` (normalize.short_motorway, "
        f"{_N.MOTORWAY_MAX}-character limit)"),
    "country": (
        lambda v: (_N.country_iso(v) if isinstance(v, str) and v.strip()
                   and not _N.looks_unknown_code(v) else v),
        "merge's ISO alpha-2 normalisation of `country` (normalize.country_iso)"),
}
RENDER_COERCION_STAGE = ("the render-boundary sentinel and type coercion "
                         "(_common.fill_render_sentinels, which run.py re-runs over canonical "
                         "after the repairs stage)")


def _render_boundary_form(field: str, value):
    """What `_common.fill_render_sentinels` leaves in `field` after a repair wrote `value`.

    run.py's `_coerce_repaired_scalars` re-runs that function over canonical ITSELF once the
    repairs stage has written (A3a), so a repaired value meets it exactly as an override does
    pre-merge. Two of its effects matter here: a value that reads as an unknown form in a
    chrome-read field is replaced by the field's sentinel ("to be confirmed" -> BLANK), and a
    numeric in a string-typed field is coerced to text (12 -> "12"). The first is a value the
    operator wrote and the card will not show; the second reads back as the same value under
    `_same` and is benign. Computed on a scratch dict so nothing here touches the property."""
    scratch = {field: value}
    try:
        C.fill_render_sentinels(scratch)
    except Exception:
        return value
    return scratch.get(field, value)


def downstream_form(field: str, value) -> tuple[object, list[str]]:
    """(the value as it will stand in canonical once every post-repair stage has run, the
    operator-facing names of the stages that CHANGED it). An empty list means it survives
    byte-for-byte or as the same value in another type."""
    after, stages = value, []
    reg = POST_REPAIR_NORMALISERS.get(field)
    if reg is not None:
        try:
            nxt = reg[0](after)
        except Exception:
            nxt = after
        if nxt is not None and not _same(nxt, after):
            stages.append(reg[1])
            after = nxt
    nxt = _render_boundary_form(field, after)
    if not _same(nxt, after):
        stages.append(RENDER_COERCION_STAGE)
        after = nxt
    return after, stages


def survives_downstream(field: str, value) -> tuple[bool, object, str | None]:
    """Will a `set` of `value` into `field` still be there, as written, once merge and run.py
    have re-normalised the property? -> (survives, the value that will actually stand, a
    refusal reason in operator language when it does not).

    Survival is judged the way this module judges everything else: `_same` (so an integer
    coerced to its own digits survives) or both sides absent-like (a sentinel written as one
    unknown token and re-filled as another is still the honest unknown, and `set: {"status":
    "tbd"}` is the documented way to write one). Anything else is a value the report would
    claim and the pack would not carry, which is the D12 defect exactly."""
    after, stages = downstream_form(field, value)
    if _same(after, value) or (_absent_like(value) and _absent_like(after)):
        return True, after, None
    shown = " ".join(str(value).split()) if isinstance(value, str) else value
    if field == "motorway" and isinstance(value, str):
        return False, after, (
            f"`motorway` = {shown!r} is {len(shown)} characters and the card-fit limit for this "
            f"field is {_N.MOTORWAY_MAX}: merge's re-derivation (normalize.short_motorway) would "
            f"condense it to {after!r} the moment this repair landed, so the value as written "
            f"can never reach canonical.json or the delivered pack. Either supply a value that "
            f"already fits ({_N.MOTORWAY_MAX} characters or fewer), or accept the condensed form "
            f"by writing {after!r} yourself; the full sentence belongs in the Source Ledger, "
            f"which this entry's `source_locator` can carry. Applied NOTHING, so the report and "
            f"the ledger never assert a value the pack does not contain")
    hint = ""
    if isinstance(value, str) and _N.looks_unknown(value):
        hint = (" (it reads as an UNKNOWN form: to withdraw the field use `unset`; to state the "
                "honest unknown write the sentinel itself)")
    return False, after, (
        f"`{field}` = {shown!r} would not survive as written: {'; '.join(stages)} would turn it "
        f"into {after!r} after this repair landed, so the pack would carry {after!r} while this "
        f"report and the Source Ledger row claimed {shown!r}{hint}. Write {after!r} if that is "
        f"what you mean, or a value those stages leave alone. Applied NOTHING")


def _doomed_sets(sets: dict) -> list[str]:
    """Refusal reasons for every `set` value that would not survive downstream; [] when all do."""
    out = []
    for k in sorted(sets):
        ok, _, why = survives_downstream(k, sets[k])
        if not ok and why:
            out.append(why)
    return out


def load(path, extra_fields=()) -> tuple[list, list]:
    """Parse repairs.json -> (entries, invalid_reasons). NEVER raises.

    `extra_fields` widens the field-name screen exactly as it widens the override loader's
    (B7): a name the schema does not declare but the DATA carries is a real field, and an
    audited, attributed, ledger-recorded human correction must be able to reach it. It
    defaults to empty, so every existing caller keeps today's behaviour to the letter.

    This is the DATASET-WIDE half of the check only. The contract is "the schema, or the key
    the RESOLVED TARGET already carries", and a target only exists after `_resolve`, so the
    precise half lives in `apply`. Keeping a screen here still earns its place: an obvious
    typo is named before anything is resolved, and because `schema | dataset` is a superset of
    `schema | one property`, this screen can never refuse a key `apply` would have accepted.
    """
    p = Path(str(path or ""))
    if not str(path) or not p.exists():
        return [], []
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return [], [f"{p.name} is not valid JSON ({type(e).__name__}) - NO repair was applied"]
    if not isinstance(raw, list):
        return [], [f"{p.name} must be a JSON LIST of repair entries - NO repair was applied"]
    return validate_entries(raw, extra_fields=extra_fields)


def validate_entry(entry, extra_fields=()) -> list[str]:
    """The reasons `load` would refuse ONE entry; [] means it passes the file-level screen.

    For a caller holding an entry it is about to WRITE (run.py's answer-to-repair bridges),
    so an entry the repairs stage will refuse is refused before it is written and the broker's
    answer is not recorded into nothing (D4/D13). Same rules, same messages, same code path as
    `load`; the only check this cannot make is the duplicate-id one, which is a property of the
    file, not of the entry."""
    return validate_entries([entry], extra_fields=extra_fields)[1]


def validate_entries(raw, extra_fields=()) -> tuple[list, list]:
    """The per-entry validation behind `load`, on entries already in hand -> (entries that
    pass, refusal reasons). NEVER raises; a non-list is one refusal.

    Split out of `load` (D12) so the SAME validator that judges work/repairs.json is callable
    on an entry before it reaches the file. `load` is now a file reader plus this; nothing about
    what passes or fails, or the wording of a refusal, moved."""
    if not isinstance(raw, list):
        return [], ["repair entries must be a JSON LIST - NO repair was applied"]
    canon = set(C.canonical_property_fields())
    out, bad, seen = [], [], set()
    for n, e in enumerate(raw, start=1):
        tag = f"entry #{n}"
        if not isinstance(e, dict):
            bad.append(f"{tag} is not an object")
            continue
        rid = str(e.get("id") or "").strip()
        tag = f"repair {rid}" if rid else tag
        if not rid:
            bad.append(f"{tag}: no `id`")
            continue
        if rid in seen:
            bad.append(f"{tag}: duplicate id")
            continue
        seen.add(rid)
        if not str(e.get("why") or "").strip():
            bad.append(f"{tag}: `why` is required and non-empty (it ships in the Source Ledger)")
            continue
        if not str(e.get("verified_by") or "").strip():
            bad.append(f"{tag}: `verified_by` is required (it ships in the Source Ledger)")
            continue
        prop = e.get("property")
        if not isinstance(prop, dict) or not (prop.get("key") or prop.get("id") is not None):
            bad.append(f"{tag}: `property` needs a `key` and/or an `id`")
            continue
        sets = e.get("set") or {}
        media = e.get("media") or {}
        if not isinstance(sets, dict) or not isinstance(media, dict):
            bad.append(f"{tag}: `set`/`media` must be objects")
            continue
        raw_unset = e.get("unset") or []
        if not isinstance(raw_unset, list) \
                or any(not isinstance(k, str) or not k.strip() for k in raw_unset):
            bad.append(f"{tag}: `unset` must be a LIST of field names to clear "
                       f"(use `set` to write a value)")
            continue
        raw_strike = e.get("strike_from_source")
        if raw_strike is not None and not (isinstance(raw_strike, str) and raw_strike.strip()):
            bad.append(f"{tag}: `strike_from_source` must be ONE source filename - the "
                       f"instruction is 'this property carries nothing from that file', and a "
                       f"file it cannot name is a file it cannot unfuse")
            continue
        # A18a: optional, but a citation that is present and empty is not a citation. It
        # REPLACES a Source Ledger column, and an empty ledger cell hard-blocks the build.
        cite_bad = sorted(k for k in ("source_file", "source_locator")
                          if k in e and not (isinstance(e[k], str) and e[k].strip()))
        if cite_bad:
            bad.append(f"{tag}: {', '.join(cite_bad)} is optional, but when present it must be "
                       f"a non-empty string - it replaces a Source Ledger column, and an empty "
                       f"ledger cell hard-blocks the build")
            continue
        _, unset, strike = _verbs(e)
        if not sets and not media and not unset and not strike:
            bad.append(f"{tag}: nothing to do - give a `set`, an `unset`, a "
                       f"`strike_from_source` and/or a `media`")
            continue
        contradictory = sorted(set(sets) & set(unset))
        if contradictory:
            bad.append(f"{tag}: {', '.join(contradictory)} is in BOTH `set` and `unset` - one "
                       f"entry cannot write and withdraw the same field, and guessing which "
                       f"the operator meant is exactly what this module never does")
            continue
        # DENIED first, so its message still wins over the membership one below: a broker who
        # tried to relabel every figure at once needs to be told THAT, not that the key is
        # unknown (it is not - it is known and forbidden).
        denied = sorted((set(sets) | set(unset)) & DENIED_FIELDS)
        if denied:
            bad.append(f"{tag}: {', '.join(denied)} is structural or a dataset-wide unit label "
                       f"and can never be repaired - correct the figures themselves")
            continue
        # DERIVED TWINS next, for the same reason DENIED is first: the field is known and the
        # entry is refused for what it OMITS, and the operator needs the twin's name, not a
        # membership complaint. Re-checked in `apply` because `apply` is called directly.
        stranded = _stranded_twins(sets, unset)
        if stranded:
            bad.append(f"{tag}: {'; '.join(stranded)} - applied NOTHING")
            continue
        # The schema's required list is resolved through `_required_fields_or_reason`, which
        # cannot hand back a silently empty set: an unreadable or restructured schema refuses
        # the entry here instead of disarming the guard and letting the clear through to
        # hard-block validate-data. Only consulted when the entry actually clears something,
        # so a schema problem never refuses an entry the guard has no business judging.
        if unset:
            req_fields, req_err = _required_fields_or_reason()
            if req_err:
                bad.append(f"{tag}: {req_err}")
                continue
            required = sorted(set(unset) & req_fields)
            if required:
                bad.append(f"{tag}: {', '.join(required)} is REQUIRED by the canonical schema "
                           f"and can never be CLEARED - an absent required key hard-blocks "
                           f"validate-data, so the whole run would pay for one card. Its honest "
                           f"unknown is a sentinel VALUE: write it with `set`")
                continue
        # THE MEMBERSHIP SCREEN IS `set` ONLY *HERE*, and that is a statement about WHERE the
        # question can be answered, not about `unset` being exempt from it. This screen is
        # dataset-wide (`schema | every key on any property`), and it has exactly one outcome
        # available to it: INVALID. Neither fits a clear. A dataset-wide set cannot tell a
        # misspelling from a clear that already landed - after the first run the off-spec key it
        # removed is on no property either - and INVALID is the wrong verdict for both, since a
        # clear cannot CREATE a field: it would turn a correct correction into a permanent
        # refusal on its second run, which is the regression that produced the previous
        # carve-out. So `unset` is screened in `apply`, against the RESOLVED property, which can
        # answer "does this card carry the key" precisely, and its failure lands in `stale`.
        # What the previous carve-out got wrong was not moving the check - it was removing it:
        # an absent key was reported APPLIED and given a Source Ledger row. See `apply`.
        known = set(canon) | {str(k) for k in (extra_fields or ())}
        unknown = sorted({k for k in sets if k not in known})
        if unknown:
            bad.append(f"{tag}: {', '.join(unknown)} is not a canonical property field and is "
                       f"on no property in this dataset "
                       f"(a typo cannot be allowed to create one)")
            continue
        blank = sorted(k for k, v in sets.items()
                       if v is None or (isinstance(v, str) and not v.strip()))
        if blank:
            bad.append(f"{tag}: {', '.join(blank)} is blank - `set` writes a value, it never "
                       f"clears one; `unset` is the verb that withdraws a field (an empty "
                       f"ledger cell hard-blocks the build)")
            continue
        # SURVIVAL (D12): a value the post-repair normalisers would rewrite is refused HERE,
        # before it reaches `apply`, with the limit named and the form it would become shown.
        # Re-checked in `apply` for the same reason DENIED and the twins are: `apply` is
        # called directly. It runs after `blank` because a blank cannot be judged, and after
        # the membership screen because a name that is not a field has no normaliser.
        doomed = _doomed_sets(sets)
        if doomed:
            bad.append(f"{tag}: {'; '.join(doomed)}")
            continue
        bad_slot = sorted(k for k in media if k not in MEDIA_SLOTS)
        if bad_slot:
            bad.append(f"{tag}: media slot(s) {', '.join(bad_slot)} unknown "
                       f"(expected {', '.join(MEDIA_SLOTS)})")
            continue
        out.append(e)
    return out, bad


def _resolve(props: list, prop_ref: dict) -> tuple[int | None, str | None]:
    """-> (index, failure_kind). failure_kind in {'stale','ambiguous'} when index is None."""
    want_key = str(prop_ref.get("key") or "").strip().lower()
    want_id = prop_ref.get("id")
    by_key = [i for i, p in enumerate(props) if want_key and _mk(p).lower() == want_key]
    by_id = [i for i, p in enumerate(props)
             if want_id is not None and str(p.get("id")) == str(want_id)]
    if want_key and want_id is not None:
        if not by_key and not by_id:
            return None, "stale"
        if by_key and by_id:
            # INTERSECT, never compare first hits. A match key is city|developer|park, so any
            # two properties in one park share it - `by_key=[5,6,7]` beside `by_id=[6]` is a
            # shared key the id RESOLVES, not a disagreement, and reading it as one made the
            # documented "give both" form fail closed on every multi-unit park. An id inside
            # the key's matches disambiguates; an id OUTSIDE them is a genuine key/id conflict
            # and still fails closed.
            both = [i for i in by_key if i in by_id]
            if not both:
                return None, "ambiguous"
            hits = both
        else:
            hits = by_key or by_id
    else:
        hits = by_key or by_id
    if not hits:
        return None, "stale"
    if len(hits) > 1:
        return None, "ambiguous"
    return hits[0], None


def apply(canonical: dict, entries: list, base_dir: Path | None = None,
          provenance: list | None = None) -> dict:
    """Apply in place. Returns a report dict with the five REPORT_KEYS.

    `provenance` is the Source Ledger's `record_type=property` rows - the only surviving record
    of which file gave a merged property which field, and therefore what `strike_from_source`
    executes against. Pass the rows, or pass `base_dir` and they are read from
    <base_dir>/source_ledger.csv. With NEITHER available a strike is INVALID rather than a
    quiet no-op, for the reason `read_provenance` states: not being able to look is not the
    same answer as the file having contributed nothing."""
    rep = {k: [] for k in REPORT_KEYS}
    props = canonical.get("properties") or []
    canon = set(C.canonical_property_fields())
    prov_rows = provenance if provenance is not None else (
        read_provenance(Path(base_dir) / LEDGER_NAME) if base_dir is not None else None)
    prov = _prov_index(prov_rows) if prov_rows is not None else None
    # every key ANY property carried before this batch: the same dataset-wide set `run` hands
    # `load` as `extra_fields`, frozen here so one entry's new key cannot license the next
    ds_keys = {k for q in props if isinstance(q, dict) for k in q}
    for e in entries:
        rid = e["id"]
        idx, fail = _resolve(props, e["property"])
        if idx is None:
            rep[fail].append({
                "id": rid,
                "reason": (f"`property` matched {'no' if fail == 'stale' else 'more than one'} "
                           f"property - applied NOTHING. Check the key against "
                           f"work/properties/ (the projection names every property's key)."),
            })
            continue
        p = props[idx]
        pid = p.get("id")
        exp = e.get("expect") or {}
        sets, unset, strike = _verbs(e)

        # THE FIELD GATE, here rather than in `load` because the contract needs the RESOLVED
        # target: a name is acceptable if the SCHEMA declares it OR this property already
        # carries it, off-spec included. `load` can only screen the dataset. It is re-checked
        # here even for the parts `load` already screened, because `apply` is called directly
        # (by the evals, and by anything that has its own entries in hand) and a guard a caller
        # can walk around is not a guard. DENIED runs FIRST so its message still wins: a
        # forbidden key is known and refused, not unknown.
        touched = sorted(set(sets) | set(unset))
        denied = [k for k in touched if k in DENIED_FIELDS]
        if denied:
            rep["invalid"].append(
                f"repair {rid}: {', '.join(denied)} is structural or a dataset-wide unit label "
                f"and can never be repaired - correct the figures themselves")
            continue
        # DERIVED TWINS (F24c): refused whole, before anything is resolved or written, so the
        # entry lands on BOTH fields or on neither. INVALID because, like DENIED, the entry is
        # malformed until the operator adds the twin, and stays malformed on every run.
        stranded = _stranded_twins(sets, unset)
        if stranded:
            rep["invalid"].append(f"repair {rid}: {'; '.join(stranded)} - applied NOTHING")
            continue
        # The schema's required list is resolved ONCE per entry and BEFORE anything is written,
        # because BOTH clearing verbs need it: `unset` to refuse a required key outright, the
        # strike to protect one by skipping it. Resolved through `_required_fields_or_reason`,
        # which can never hand back a silently empty set - an unreadable or restructured schema
        # refuses the entry rather than disarming the guard, and it refuses it HERE, in the
        # report an operator reads, rather than by raising into run.py's stage handler.
        req_fields, req_err = frozenset(), None
        if unset or strike:
            req_fields, req_err = _required_fields_or_reason()
        if req_err:
            rep["invalid"].append(f"repair {rid}: {req_err}")
            continue
        # THIS COPY IS DELIBERATE AND IS MUTATION-TESTED (see repair_verbs_test). `load` screens
        # the same thing, but `apply` is called directly - by the evals, and by anything holding
        # its own entries - and a guard a caller can walk around is not a guard. Deleting it
        # lets a schema-required key be popped, which leaves canonical un-schema-valid and
        # hard-blocks the data gate for the whole run.
        required = [k for k in unset if k in req_fields]
        if required:
            rep["invalid"].append(
                f"repair {rid}: {', '.join(required)} is REQUIRED by the canonical schema and "
                f"can never be CLEARED - an absent required key hard-blocks validate-data. Its "
                f"honest unknown is a sentinel VALUE: write it with `set`")
            continue
        # `set` only in THIS check, because its verdict is INVALID and a clear must never earn
        # that: the `unset` half of the same contract is enforced a few lines below, against
        # this same resolved property, and reports `stale`. See `load` for why the dataset-wide
        # screen cannot carry it. One widening: a key ANOTHER property already carries may be
        # added here when the entry cites where the value is printed (`source_file` AND
        # `source_locator`) - plotAreaHa on #1 when #15 carries it is a read, not a typo, and a
        # typo is still refused because no property carries the misspelling.
        cited = bool(str(e.get("source_file") or "").strip()
                     and str(e.get("source_locator") or "").strip())
        unknown = [k for k in sets if k not in canon and k not in p
                   and not (k in ds_keys and cited)]
        if unknown:
            rep["invalid"].append(
                f"repair {rid}: {', '.join(unknown)} is not a canonical property field and "
                f"property {pid} does not carry it either (a typo cannot be allowed to create "
                f"one). An off-spec key the property DOES carry is repairable, and so is one "
                f"another property already carries when the entry cites its source "
                f"(`source_file` + `source_locator`).")
            continue
        # SURVIVAL (D12): refused whole, BEFORE anything is written and before `expect` is
        # consulted, so an entry carrying a value merge would condense straight back lands on
        # no field rather than half. This is the check that turns "APPLIED 'M1 J17 8 miles;
        # M6 J2 12 miles; A5 3 miles; M45 J1 6 miles'" followed by a silent condense into an
        # INVALID that names the 40-character limit and shows the condensed form. INVALID,
        # like DENIED and the twins, because the verdict is a property of the entry's own value
        # and holds on every run until the operator changes it. Neither outcome is laundered:
        # the value is not written and then reported unwritten, and no condensed version is
        # written while the report claims the operator's value landed.
        doomed = _doomed_sets(sets)
        if doomed:
            rep["invalid"].append(f"repair {rid}: {'; '.join(doomed)}")
            continue

        # STRIKE: resolve the filename to the fields the ledger credits it with on THIS
        # property. Done before the `expect` guard so a strike can be guarded like any other
        # verb, and before anything is written so the entry still applies all-or-nothing.
        struck: list = []
        protected: list = []
        struck_from = ""
        if strike:
            if prov is None:
                rep["invalid"].append(
                    f"repair {rid}: `strike_from_source` needs the Source Ledger to know which "
                    f"fields on property {pid} came from {Path(strike).name} and none was "
                    f"readable - applied NOTHING rather than guess at nothing.")
                continue
            named, competing, struck_from = _strike_targets(prov.get(str(pid)) or {}, strike)
            if competing:
                # THE FILENAME NAMES MORE THAN ONE FILE, so nothing is removed. This verb
                # DELETES: resolving it by picking a winner would silently drop correct, sourced
                # data off the card and then disclose the removal against a file that never
                # supplied it - a ledger row that is worse than no row, because it reads as
                # audit. The override channel's identical targeting clause is no defence for
                # doing otherwise: it narrows further by page/row/sheet and it SUBSTITUTES.
                rep["ambiguous"].append({
                    "id": rid,
                    "reason": (f"`strike_from_source` named {Path(strike).name!r}, and the "
                               f"Source Ledger credits property {pid} with fields from "
                               f"{len(competing)} DIFFERENT files of that name "
                               f"({', '.join(repr(c) for c in competing)}) - applied NOTHING, "
                               f"because a strike DELETES and this entry cannot say which of "
                               f"them to delete. Re-state `strike_from_source` with enough "
                               f"LEADING FOLDERS to pick one out (any trailing part of a path "
                               f"works, matched a folder at a time)."),
                })
                continue
            if not named:
                rep["stale"].append({
                    "id": rid,
                    "reason": (f"`strike_from_source` named {Path(strike).name!r}, which the "
                               f"Source Ledger credits with NO field on property {pid} - "
                               f"applied NOTHING. Check the filename against "
                               f"{LEDGER_NAME} (a strike matches on basename, "
                               f"case-insensitively; leading folders only ever NARROW that "
                               f"match, so a path the ledger does not carry matches nothing)."),
                })
                continue
            # DENIED and schema-required fields are respected by SKIPPING, not by refusing the
            # whole entry: the deck that supplied a wrong spec usually supplied the hero and the
            # identity fields too, so refusing outright would make the verb unusable for the
            # exact case it exists for. Neither is silent - the operator has to know the hero
            # still comes from that file (replace it with `media`) and the identity fields still
            # do (re-state them with `set`), or the unfusing is only half done.
            protected = [f for f in named
                         if f in DENIED_FIELDS or f in req_fields]
            # NOT filtered by "still present on the property": a strike is re-applied on every
            # run, and on the second pass the field it removed is already gone. Dropping it
            # here would make a WORKING strike report STALE ("matched NOTHING - fix or delete")
            # in the client-facing Gaps Report on every run after the first, and would drop the
            # ledger row that discloses the removal. The pop below is idempotent by nature.
            struck = [f for f in named if f not in protected]
            if not struck and not sets and not unset and not (e.get("media") or {}):
                rep["stale"].append({
                    "id": rid,
                    "reason": (f"`strike_from_source` named {Path(strike).name!r}, and every "
                               f"field it credits on property {pid} is structural, media-owned "
                               f"or schema-required ({', '.join(protected) or 'none'}) - "
                               f"applied NOTHING. Replace a hero with `media`; re-state an "
                               f"identity field with `set`."),
                })
                continue

        # A repair is RE-APPLIED on every run, so after the first pass the field already holds
        # the target and a naive `expect` check would call its own success a supersede. That is
        # not hypothetical: resume skips merge when nothing upstream changed, so the second run
        # of any guarded repair would refuse, leave the value in place with no fresh ledger row,
        # and trace-coverage would then block it as untraceable. A field that already equals
        # what this entry sets is therefore ALREADY APPLIED, not drift; anything else still
        # supersedes. The same reasoning covers a field this entry CLEARS: on the second run it
        # is already absent, which reads as absence to `expect` - its own success, so a guarded
        # `unset`/`strike` must not supersede itself either.
        clears = set(unset) | set(struck)
        wrong = [k for k, v in exp.items()
                 if not _expect_same(p.get(k), v)
                 and not (k in sets and _same(p.get(k), sets[k]))
                 and not (k in clears and _absent_like(p.get(k)))]
        if wrong:
            rep["superseded"].append({
                "id": rid,
                "reason": (f"`expect` said {', '.join(f'{k}=={exp[k]!r}' for k in wrong)} but the "
                           f"property now holds "
                           f"{', '.join(f'{k}=={p.get(k)!r}' for k in wrong)} - applied NOTHING. "
                           f"The dataset moved under this entry; re-check it against the source."),
            })
            continue

        # `unset` MEMBERSHIP, at the RESOLVED property: a key this card does not carry clears
        # NOTHING, writes NO Source Ledger row, and is reported `stale`.
        #
        # It used to be reported APPLIED with an already-absent flag, on the argument that a
        # re-application and a misspelling are indistinguishable on the property so both should
        # be disclosed as a no-op. The premise is right; the bucket and the row were not.
        # APPLIED means a value moved, so `unset: ["oddKeyy"]` against a property carrying
        # `oddKey` read as a successful clear to anyone triaging the report, with the spelling
        # hint in a bracketed tail; and it minted a `repair` row for a field on no schema and on
        # no property, breaking this module's own invariant that a repair row's field already has
        # its own property row. `stale` is accurate for BOTH readings - nothing happened - and it
        # is a bucket the operator scans rather than skims.
        #
        # THE SOURCE LEDGER SHARPENS THE MESSAGE AND DECIDES NOTHING. Its `record_type=property`
        # rows say whether this property ever really carried the key, which separates a landed
        # clear from a typo; they also survive a full re-merge, because the sources still state
        # the field. The prior CLEAR's own `repair` row would be a stronger signal still and is
        # deliberately not used: run.py replaces every repair row each run and merge rewrites the
        # ledger outright, so a verdict resting on it would flip between a resumed run and a full
        # one - a guard whose answer depends on which stages were skipped is worse than none.
        # So the bucket and the absent row follow from the property alone and are stable.
        #
        # A STRIKE IS EXEMPT, on evidence rather than taste: it resolves its fields OUT OF the
        # ledger, so every field it clears provably has a property row, its disclosure row is
        # never a fabrication, and it must keep re-writing that row on later runs when the field
        # it removed is already gone (see the note above `struck`).
        absent = [k for k in unset if k not in p and k not in struck]
        if absent:
            prov_fields = (prov or {}).get(str(pid)) or {}
            notes = []
            for k in absent:
                if k in prov_fields:
                    notes.append(f"{k!r} is already absent and the Source Ledger still credits "
                                 f"property {pid} with it, so this clear landed on an earlier "
                                 f"run - a correct entry, doing nothing")
                elif k in canon:
                    notes.append(f"{k!r} is already absent: the schema declares it, but no "
                                 f"source ever gave property {pid} one, so there is nothing to "
                                 f"withdraw")
                else:
                    notes.append(f"{k!r} is already absent, is on NO schema, and has no Source "
                                 f"Ledger row on property {pid} - check the spelling against "
                                 f"work/properties/ (a clear cannot create a field, so this is "
                                 f"a no-op, not a malformed entry)")
            rep["stale"].append({
                "id": rid,
                "reason": (f"`unset` asked to clear {', '.join(absent)} on property {pid}, which "
                           f"carries {'none of them' if len(absent) > 1 else 'no such key'} - "
                           f"CLEARED nothing and wrote NO {LEDGER_NAME} row. "
                           + "; ".join(notes) + "."),
            })
            # The REST of the entry still runs. A `set` beside an already-satisfied clear must
            # be re-applied and must re-write its own ledger row on every run, or resume (which
            # skips merge) leaves that value with no provenance and trace-coverage blocks it as
            # untraceable. So an entry can legitimately appear in `applied` AND in `stale`, and
            # `format_report` prints both lines; `applied` is only appended to below when
            # something actually changed.
            clears -= set(absent)
        changed = {}
        for k, v in sets.items():
            changed[k] = {"from": p.get(k), "to": v}
            p[k] = v
        # CLEARING IS REMOVAL. Writing the sentinel over the field would be indistinguishable
        # from a source that stated "tbd", and the ledger row would then claim the repair SET a
        # value when what the operator did was withdraw one. Removal says exactly what
        # happened: the property is back to the state of a field no source ever stated, and
        # `_common.fill_render_sentinels` re-fills every chrome-read key with its own honest
        # unknown at the RENDER boundary (on a copy, in build_dashboard and the gates), so
        # nothing the template reads can vanish while a genuinely off-spec key genuinely goes.
        # Idempotent on purpose - see the strike note above.
        for k in sorted(clears):
            ch = {"from": p.get(k), "to": CLEARED, "cleared": True}
            if k in struck:
                # the RESOLVED ledger path, not the operator's shorthand. A strike may now be
                # narrowed by leading folders to pick one of two same-named files apart, and a
                # disclosure row that dropped that narrowing back to a bare basename would put
                # the ambiguity this verb just refused to guess at straight back into the audit
                # trail. `_strike_targets` already proved this path is the only match.
                ch["struck_from"] = struck_from or Path(strike).name
            # Only a STRIKE can reach this branch now: an `unset` naming a key the property
            # does not carry is reported `stale` above and never gets here. For a strike the
            # state has ONE reading and no hedging is needed - the ledger credits the file with
            # the field, so an absent one means this strike already removed it on an earlier
            # run - and its row is still written, because the field's own property row is what
            # the strike matched on in the first place.
            if k not in p:
                ch["already_absent"] = True
            p.pop(k, None)
            changed[k] = ch
        # A merge-time plausibility-gate strike writes a permanent-sounding
        # `meta.conflicts` sentence ("... so the card ships tbd ...") BEFORE this repair
        # ever runs. Once the repair restores a real value that sentence is simply false,
        # and it ships verbatim into the Gaps Report alongside the (correct) repair note -
        # a live run shipped three such contradictions to the client. Annotate the stale
        # sentence in place (never delete - the strike's own reasoning is still real audit
        # history) rather than leave a false claim standing next to its own correction.
        # NOTE: do not skip on ch["from"] == ch["to"] here - resume/caching means a repair
        # already applied on a PRIOR run reads back as a same-value no-op on this run, but
        # merge.py's meta.conflicts is a leftover from the ORIGINAL (pre-repair) merge pass
        # and never regenerates on a resumed run, so the stale note can easily still be sitting
        # unannotated even when this run's `changed` looks like a no-op.
        conflicts = (canonical.get("meta") or {}).get("conflicts")
        if isinstance(conflicts, list):
            for field, ch in changed.items():
                # A CLEAR never annotates a stale note. "... so the card ships tbd" is not
                # falsified by a withdrawal, it is made TRUE again, and a "kept 'Y'" note about
                # a value now removed is answered by the repair's own cleared row - marking it
                # [RESOLVED ... the card now ships ...] would put a claim about a shipped value
                # next to a field that no longer ships one.
                # v45: the family, not one spelling - the render sentinel is now
                # normalize.BLANK and a pre-v45 canonical still carries 'tbd'.
                if ch.get("cleared") or ch["to"] is None or _N.looks_unknown(ch["to"]):
                    continue  # nothing to correct the note WITH - the field is still unknown
                prefix = f"id {pid} {field}:"
                # Two stale-note shapes precede this repair: a plausibility-band STRIKE
                # ("... so the card ships tbd ...") and a cross-source VALUE-CONFLICT note
                # ("discarded 'X' from <source> (kept 'Y')") where this repair overrides the
                # precedence winner Y that the note itself still asserts as current. Both are
                # stale the instant the repair lands and both must be annotated, not just the
                # first - a "kept 'Y'" note about a value this repair just replaced is exactly
                # as false to a broker as a "ships tbd" note about a value now restored.
                kept_marker = f"kept '{ch['from']}')" if ch["from"] is not None else None
                for i, note in enumerate(conflicts):
                    if not isinstance(note, str) or not note.startswith(prefix) \
                            or "[RESOLVED" in note:
                        continue
                    if "ships tbd" in note:
                        conflicts[i] = (f"{note} [RESOLVED by repair {rid}: the card now ships "
                                        f"{ch['to']!r}, not tbd - see \"Manual corrections "
                                        f"applied (property-level repairs)\" below.]")
                    elif kept_marker and kept_marker in note:
                        conflicts[i] = (f"{note} [RESOLVED by repair {rid}: the card now ships "
                                        f"{ch['to']!r}, not {ch['from']!r} - see \"Manual "
                                        f"corrections applied (property-level repairs)\" below.]")
        media = {}
        for slot, rel in (e.get("media") or {}).items():
            src = Path(rel)
            if base_dir is not None and not src.is_absolute():
                src = Path(base_dir) / rel
            if not src.exists():
                rep["invalid"].append(f"repair {rid}: media file not found: {src}")
                continue
            uri = _image_uri(src, slot)
            if uri is None:
                rep["invalid"].append(f"repair {rid}: {src.name} could not be decoded as an image")
                continue
            if slot == "hero":
                # the hero IS gallery[0] (v12), so both move together or the carousel
                # would open on the photo this repair was written to replace
                gal = [g for g in (p.get("gallery") or []) if g != p.get("photo")]
                p["photo"] = uri
                p["gallery"] = [uri] + gal
            else:
                p[slot] = uri
            media[slot] = src.name
        # APPLIED means something moved. An entry whose only work was an already-absent `unset`
        # produces no `changed` and no `media`, and it has already been reported `stale` above,
        # so appending it here would put an empty success row in the bucket an operator reads
        # as "these corrections landed" - the misreport this remediation exists to remove. A
        # `protected` list is not work either: it records what the strike deliberately did NOT
        # do, and it is carried on the applied row only when there is an applied row to carry.
        if protected and not changed and not media:
            # An all-protected strike sitting beside an already-absent `unset` is the one route
            # to here: the early protected-only branch does not fire (the entry HAD an `unset`)
            # and there is now no applied row to carry `protected` on. Half-done unfusing that
            # nobody is told about is the failure that list exists to prevent, so it is said
            # here instead of being dropped on the floor.
            rep["stale"].append({
                "id": rid,
                "reason": (f"`strike_from_source` named {Path(strike).name!r}, and every field "
                           f"it credits on property {pid} is structural, media-owned or "
                           f"schema-required ({', '.join(protected)}) - struck NOTHING. Replace "
                           f"a hero with `media`; re-state an identity field with `set`."),
            })
        if changed or media:
            rep["applied"].append({
                "id": rid, "property_id": p.get("id"), "key": _mk(p),
                "changed": changed, "media": media,
                "why": e.get("why", ""), "verified_by": e.get("verified_by", ""),
                # A18a: the entry's own citation, carried through to `ledger_rows`. Empty when
                # the entry cites nothing, which keeps today's ledger values in place.
                "source_file": str(e.get("source_file") or "").strip(),
                "source_locator": str(e.get("source_locator") or "").strip(),
                # what a strike deliberately did NOT remove, so half-done unfusing is never
                # silent
                "protected": protected,
            })
    return rep


def ledger_rows(rep: dict) -> list[dict]:
    """One Source Ledger row per repaired field, so the change is disclosed, not laundered."""
    rows = []
    for a in rep.get("applied", []):
        # A18a: the entry's own citation wins, its absence keeps what this module always
        # wrote. A value a human read on a document page was attributed to the CORRECTION
        # FILE, with the repair id as its locator, so provenance could say that a correction
        # happened but not where the value came from - the reviewer's next question, and the
        # one the Source Ledger exists to answer. `verified_by` still records WHO stands
        # behind it, so the citation adds evidence without removing accountability.
        cite_file = a.get("source_file") or "repairs.json"
        cite_locator = a.get("source_locator") or a["id"]
        for field, ch in (a.get("changed") or {}).items():
            cleared = bool(ch.get("cleared"))
            if cleared:
                # The row must say CLEARED, in those words. `value` is the sentinel a reader
                # sees for the now-absent field, matching merge's own convention for one, so a
                # value-vs-card cross-check still agrees; the note is what stops that sentinel
                # being read as "the repair set the string tbd". ("tbd" also carries no
                # 4-character token, so a cited page is not checked against a withdrawal by
                # the prov-containment gate.)
                note = (f"property-keyed repair {a['id']} CLEARED this field"
                        + (f", with everything else from {ch['struck_from']}"
                           if ch.get("struck_from") else "")
                        + f": {a.get('why', '')} (was {ch['from']!r}). The key is now ABSENT, "
                          f"not set to a sentinel; a chrome-read field falls back to its "
                          f"honest unknown at the render boundary."
                        + (" It was already absent when this run applied the entry, which for a "
                           "strike has one reading only: an earlier run removed it, and this "
                           "row re-states the withdrawal so it does not become an "
                           "unexplained absence. (A hand-named `unset` of an absent key is "
                           "reported `stale` and writes no row at all - a repair row for a "
                           "field with no property row of its own would be a fabrication.)"
                           if ch.get("already_absent") else ""))
            else:
                note = (f"property-keyed repair {a['id']}: {a.get('why','')} "
                        f"(was {ch['from']!r})")
            rows.append({
                "property_id": a.get("property_id"), "record_type": "repair", "field": field,
                "value": ("tbd" if cleared else ch["to"]), "source_file": cite_file,
                "source_locator": cite_locator,
                "source_type": "repair", "extractor": "repairs.py",
                "confidence": "verified",
                "conflict_note": note,
                "verified": a.get("verified_by", ""),
            })
    return rows


def format_report(rep: dict) -> list[str]:
    """Operator-facing lines, in the same voice as the override outcomes run.py prints."""
    out = []
    for a in rep.get("applied", []):
        for f, ch in (a.get("changed") or {}).items():
            if ch.get("cleared"):
                out.append(f"  - {a['id']}: property {a.get('property_id')} {f}: CLEARED, was "
                           f"{ch['from']!r}"
                           + (f" (struck with everything from {ch['struck_from']})"
                              if ch.get("struck_from") else "")
                           + (" [already absent: an earlier run's strike removed it]"
                              if ch.get("already_absent") else "")
                           + f"  ({a.get('why','')})")
                continue
            out.append(f"  - {a['id']}: property {a.get('property_id')} {f}: "
                       f"{ch['from']!r} -> {ch['to']!r}  ({a.get('why','')})")
        for slot, path in (a.get("media") or {}).items():
            out.append(f"  - {a['id']}: property {a.get('property_id')} {slot} image <- "
                       f"{Path(path).name}  ({a.get('why','')})")
        if a.get("protected"):
            # a half-done unfusing that nobody is told about is the failure this line prevents
            out.append(f"  - {a['id']}: property {a.get('property_id')} NOT struck: "
                       f"{', '.join(a['protected'])} - structural, media-owned or "
                       f"schema-required. Replace a hero with `media`; re-state an identity "
                       f"field with `set`.")
    for key, tag in (("stale", "STALE REPAIR"), ("ambiguous", "AMBIGUOUS REPAIR"),
                     ("superseded", "SUPERSEDED REPAIR")):
        for s in rep.get(key, []):
            out.append(f"[{tag}] {s['id']} {s['reason']}")
    for s in rep.get("invalid", []):
        out.append(f"[INVALID REPAIR] {s} - this entry does NOTHING until it is fixed.")
    return out


def run(work: Path, write: bool = True) -> dict:
    work = Path(work)
    cpath = work / "canonical.json"
    canonical = json.loads(cpath.read_text(encoding="utf-8-sig")) if cpath.exists() else {}
    # Canonical is read BEFORE the entries so the loader can be told what the data actually
    # carries. Off-spec keys are a normal and large part of every record (the extraction
    # contract emits a stated row with no canonical home under a descriptive key), so a
    # schema-only screen refused to correct a wrong value that was already on the record - the
    # asymmetry the override channel's `extra_fields` had already fixed on its side. This is
    # the dataset-wide screen; `apply` then holds each key to the RESOLVED property.
    extra = {k for p in (canonical.get("properties") or []) if isinstance(p, dict) for k in p}
    entries, invalid = load(work / "repairs.json", extra_fields=extra)
    rep = apply(canonical, entries, base_dir=work) if entries else {k: [] for k in REPORT_KEYS}
    rep["invalid"] = list(rep.get("invalid", [])) + list(invalid)
    if write and rep["applied"]:
        C.atomic_write_text(cpath, json.dumps(canonical, ensure_ascii=False)) \
            if hasattr(C, "atomic_write_text") else \
            cpath.write_text(json.dumps(canonical, ensure_ascii=False), encoding="utf-8")
    (work / "repairs_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    return rep


def main() -> int:
    # D16: the report below prints repaired values verbatim, and a repaired value can carry
    # any glyph a brochure does; a cp1252 console must not turn that into a traceback.
    C.force_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("apply", "check"))
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    rep = run(Path(a.work), write=(a.cmd == "apply"))
    for line in format_report(rep):
        print(line)
    n = len(rep["applied"])
    bad = sum(len(rep[k]) for k in ("stale", "ambiguous", "superseded", "invalid"))
    print(f"OK {n} repair(s) applied, {bad} not applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
