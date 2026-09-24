#!/usr/bin/env python3
"""repair_verbs_test.py - the repair channel's field gate, its two clearing verbs, and its
right to cite its own evidence. (A6/A7/A18a)

THREE HOLES, one shape: the post-merge correction channel could not reach things that were
plainly wrong on a merged property.

  A6 - THE FIELD GATE ASKED THE WRONG QUESTION. It refused any `set` key outside
  `canonical_property_fields()` with a message about a typo not being allowed to create a
  field. The intent is right, the implementation asked "is this name in the SCHEMA?" rather
  than "does this property already CARRY this name?". But the extraction contract deliberately
  emits a stated row with no canonical home under a descriptive key, so off-spec keys are a
  normal and LARGE part of every record - and a value already on the record, in an off-spec
  key, and wrong, could be corrected by NEITHER channel: the pre-merge one targets a source
  record and cannot address a merged property, and this one refused the key. Beside a matcher
  over-merge that is a hole with no floor. The same widening had already landed on the override
  loader (`extra_fields`, B7); this is the other half of it.

  A7 - THERE WAS NO WAY TO WITHDRAW A VALUE. `set` writes; nothing cleared. The only way to
  express "this figure is not this building's" was to write the sentinel over it, which is
  indistinguishable from a source that stated `tbd` and produces a ledger row claiming the
  repair SET a value. And unfusing two records a matcher wrongly merged had to be spelled as
  nineteen hand-listed field names, when the instruction is "this property carries nothing
  from that file" and the Source Ledger already records enough to execute it.

  A18a - A REPAIR COULD NOT CITE ITS EVIDENCE. Every repair row was stamped `repairs.json`
  with the repair's own id as its locator, so a reviewer reading provenance could tell that a
  correction happened but not where the value came from.

What this pins:
  * schema-OR-RECORD membership: an off-spec key the TARGET carries is repairable and
    clearable; a name on neither is still INVALID for `set`, and so is an off-spec key that
    lives on a DIFFERENT property (the check is per-target, not dataset-wide) unless the entry
    cites `source_file` + `source_locator`, which lets it ADD that key; a typo never passes;
  * every DENIED_FIELDS key is still refused, on `set` and on `unset` alike, and the denial
    message still WINS over the membership one;
  * `unset` REMOVES the key rather than writing a sentinel over it, the ledger row says
    CLEARED in those words, and a chrome-read key still cannot vanish (the render boundary
    re-fills its honest unknown);
  * an `unset` naming a key the RESOLVED property does not carry is `stale`, writes NO ledger
    row, and never appears in the APPLIED bucket. It used to be reported APPLIED with a
    bracketed already-absent tail and a `repair` row for the field, so a misspelling read as a
    successful clear and minted a ledger row for a field on no schema and on no property -
    breaking this module's invariant that a repair row's field already has its own property
    row. A correctly re-applied clear reads as the same no-op, which is accurate, and its
    message is sharpened by the ledger rather than decided by it;
  * a `set` sitting beside an already-satisfied clear STILL applies and still re-writes its
    own ledger row, or resume would leave that value untraceable;
  * a schema-required key can never be cleared, because an absent one hard-blocks
    validate-data and a one-card fix must not cost the whole run - asserted through `load`
    AND through `apply` called directly, because the guard is duplicated on purpose and the
    `apply` copy was the one mutation of eleven that no assertion caught;
  * the schema-required list itself FAILS LOUDLY when it cannot be resolved. It used to
    default to an empty frozenset on any exception, so a schema restructure would have
    disarmed the clear guard silently;
  * `strike_from_source` removes exactly the fields the ledger credits to that file on that
    property and NOTHING else, writes a row per field, matches on basename
    case-insensitively, reports STALE when it matches nothing and INVALID when it had no
    provenance to look at, and protects the structural/media/required fields out loud;
  * a basename naming TWO DIFFERENT files is AMBIGUOUS and strikes nothing. Two files with one
    common name in different folders is an ordinary shape for a folder of property materials
    from several senders, and a basename-only match struck both - deleting correct, sourced
    data and disclosing the deletion against a file that never supplied it. Leading folders
    narrow the match so the operator has a way out, and a path recorded at two different
    depths is still ONE file;
  * both clearing verbs survive re-application, like `set`: on the second run the field is
    already gone, and a guarded entry must not read its own success as drift;
  * `source_file`/`source_locator` reach the ledger row when cited and change nothing at all
    when absent.
Offline; no network, no build.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C                      # noqa: E402
import repairs as R                      # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
DECK = "shared-deck.pdf"          # the file a wrongly merged record came from
TRACKER = "availability.xlsx"     # a second source, whose fields must survive a strike
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def canon():
    """Two properties. `tenure`/`yardDepth`/`sidingAccess` are OFF-SPEC on purpose: they stand
    for the open-ended long tail the extraction contract emits under a descriptive key when a
    stated row has no canonical home."""
    return {"meta": {"client": "T", "units": {"area": "sq m"},
                     "conflicts": ["id 1 warehouseArea: sources disagree, so the card ships "
                                   "tbd until a human confirms"]},
            "pois": [], "regions": {},
            "properties": [
                {"id": 1, "park": "Alpha Park", "city": "Northtown", "developer": "Devco",
                 "country": "ZZ", "warehouseArea": 10000, "areaUnit": "sq m",
                 "status": "Available", "region": "tbd",
                 "tenure": "Leasehold", "yardDepth": "35 m",
                 "photo": PX, "gallery": [PX]},
                {"id": 2, "park": "Beta Park", "city": "Northtown", "developer": "Otherco",
                 "country": "ZZ", "warehouseArea": 20000, "areaUnit": "sq m",
                 "status": "Available", "sidingAccess": "rail served",
                 "photo": PX, "gallery": [PX]},
            ]}


# The Source Ledger IS a merged property's provenance: merge drops the contributing record's
# __meta at the choke point and writes one row per populated field instead. So a strike is
# executed against these rows and nothing else.
LEDGER = [
    {"property_id": "1", "record_type": "property", "field": "warehouseArea", "value": "10000",
     "source_file": DECK, "source_locator": "page 3", "source_type": "pdf"},
    {"property_id": "1", "record_type": "property", "field": "tenure", "value": "Leasehold",
     "source_file": f"work/inputs/{DECK}", "source_locator": "page 4", "source_type": "pdf"},
    {"property_id": "1", "record_type": "property", "field": "photo", "value": "<img>",
     "source_file": DECK, "source_locator": "page 1", "source_type": "pdf"},
    {"property_id": "1", "record_type": "property", "field": "city", "value": "Northtown",
     "source_file": DECK, "source_locator": "page 1", "source_type": "pdf"},
    {"property_id": "1", "record_type": "property", "field": "status", "value": "Available",
     "source_file": TRACKER, "source_locator": "Sheet1!r2", "source_type": "xlsx"},
    {"property_id": "1", "record_type": "property", "field": "yardDepth", "value": "35 m",
     "source_file": TRACKER, "source_locator": "Sheet1!r2", "source_type": "xlsx"},
    {"property_id": "1", "record_type": "property", "field": "region", "value": "tbd",
     "source_file": "(none)", "source_locator": "absent in all sources", "source_type": "gap"},
    {"property_id": "2", "record_type": "property", "field": "sidingAccess",
     "value": "rail served", "source_file": DECK, "source_locator": "page 9",
     "source_type": "pdf"},
]


def entry(**kw):
    e = {"id": "rp-001", "property": {"key": "northtown|devco|alpha park", "id": 1},
         "why": "the tracker line belongs to the neighbouring unit",
         "verified_by": "t@cbre.com"}
    e.update(kw)
    return e


def work_with(items, ledger=LEDGER):
    """A work dir as the spine hands it to the repair stage: canonical, repairs, and the
    ledger merge wrote."""
    w = Path(tempfile.mkdtemp(prefix="cbre_repair_verbs_"))
    (w / "canonical.json").write_text(json.dumps(canon()), encoding="utf-8")
    (w / "repairs.json").write_text(json.dumps(items), encoding="utf-8")
    if ledger is not None:
        with open(w / R.LEDGER_NAME, "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=["property_id", "record_type", "field", "value",
                                                "source_file", "source_locator", "source_type"],
                                lineterminator="\n")
            wr.writeheader()
            wr.writerows(ledger)
    return w


def props_of(w):
    return json.loads((w / "canonical.json").read_text(encoding="utf-8"))["properties"]


#: every module name this eval builds a fixture out of, i.e. every name whose ABSENCE stops the
#: eval before it can assert anything. A full revert of repairs.py removes all of them, and the
#: eval then died with an AttributeError inside `work_with` - a loud failure that told the
#: maintainer nothing about WHAT had gone, which for a revert is the only useful information.
#: Checked first, as assertions, so a revert prints a list instead of a traceback.
_REQUIRED_SURFACE = ("LEDGER_NAME", "REPORT_KEYS", "DENIED_FIELDS", "MEDIA_SLOTS", "CLEARED",
                     "SchemaRequiredUnavailable", "load", "apply", "run", "ledger_rows",
                     "format_report", "read_provenance", "_verbs", "_basename", "_path_parts",
                     "_prov_index", "_strike_targets", "_schema_required_fields")


def surface_ok() -> bool:
    """Assert the module surface this eval depends on, BEFORE building any fixture."""
    missing = [n for n in _REQUIRED_SURFACE if not hasattr(R, n)]
    ck(not missing,
       f"repairs.py still exposes everything this eval is written against - missing: "
       f"{missing or 'nothing'}. A full revert of the module removes the clearing verbs and "
       f"their helpers, and every case below would then fail as a fixture error rather than "
       f"as the contract it is testing.")
    return not missing


def main() -> int:
    canon_fields = set(C.canonical_property_fields())

    print("== the module surface these fixtures are built on ==")
    if not surface_ok():
        print()
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s)) - nothing else could be run")
        return 1

    print()
    print("== A6: the field gate asks schema OR record, not schema alone ==")
    for f in ("tenure", "yardDepth", "sidingAccess"):
        ck(f not in canon_fields,
           f"control: {f!r} is NOT a canonical field, so these cases really do prove the "
           f"new path")

    w = work_with([entry(set={"tenure": "Freehold"})])
    rep = R.run(w)
    ck(len(rep["applied"]) == 1 and not rep["invalid"],
       f"an OFF-SPEC key the target already carries is repairable {rep['invalid']}")
    ck(props_of(w)[0]["tenure"] == "Freehold", "...and the corrected value actually landed")

    w = work_with([entry(set={"breeem": "Excellent"})])
    rep = R.run(w)
    ck(not rep["applied"] and len(rep["invalid"]) == 1,
       "a name on NEITHER the schema nor the record is still INVALID (the anti-typo purpose)")
    ck(any("breeem" in s for s in rep["invalid"]), "...the refusal names the offending key")
    ck(any("typo" in s.lower() for s in rep["invalid"]),
       f"...and still says why {rep['invalid']}")
    ck("breeem" not in props_of(w)[0], "...and no field was conjured")

    w = work_with([entry(set={"sidingAccess": "rail served"})])
    rep = R.run(w)
    ck(not rep["applied"] and len(rep["invalid"]) == 1,
       "an UNCITED off-spec key on ANOTHER property is INVALID - the check is per-target, "
       "not dataset-wide")
    ck(any("sidingAccess" in s and "property 1" in s for s in rep["invalid"]),
       f"...and the message names the key AND the property it is not on {rep['invalid']}")

    # the same guard, reached through apply() directly (the shape the other repair evals use)
    c = canon()
    r = R.apply(c, [entry(set={"yardDepth": "40 m"})])
    ck(len(r["applied"]) == 1 and c["properties"][0]["yardDepth"] == "40 m",
       "apply() alone applies the widened rule - the target property IS the record")
    c = canon()
    r = R.apply(c, [entry(set={"yardDepht": "40 m"})])
    ck(not r["applied"] and len(r["invalid"]) == 1,
       "apply() alone still refuses a typo, so the guard cannot be walked around")

    # a key ANOTHER property carries (only #1 has yardDepth) may be ADDED to #2 when the entry
    # cites where the value is printed; uncited it is still refused, and a typo always is
    beta = {"key": "northtown|otherco|beta park", "id": 2}
    c = canon()
    r = R.apply(c, [entry(property=beta, set={"yardDepth": "30 m"},
                          source_file="beta.pdf", source_locator="page 2")])
    ck(len(r["applied"]) == 1 and not r["invalid"] and c["properties"][1]["yardDepth"] == "30 m",
       f"a key another property carries is ADDED to the target when the entry cites "
       f"source_file + source_locator {r['invalid']}")
    c = canon()
    r = R.apply(c, [entry(property=beta, set={"yardDepth": "30 m"}, source_file="beta.pdf")])
    ck(not r["applied"] and len(r["invalid"]) == 1 and "yardDepth" not in c["properties"][1],
       "...but WITHOUT a source_locator it is refused and nothing is written")
    ck(any("source_locator" in s and "source_file" in s for s in r["invalid"]),
       f"...and the refusal says a source citation would allow it {r['invalid']}")
    c = canon()
    r = R.apply(c, [entry(property=beta, set={"yardDepht": "30 m"},
                          source_file="beta.pdf", source_locator="page 2")])
    ck(not r["applied"] and len(r["invalid"]) == 1 and "yardDepht" not in c["properties"][1],
       "...and a misspelling ('yardDepht') is refused even when cited - no property carries it")

    # load()'s signature: unchanged for existing callers, widened when told what the data holds
    p = w / "repairs.json"
    p.write_text(json.dumps([entry(set={"tenure": "Freehold"})]), encoding="utf-8")
    loaded, errs = R.load(p)
    ck(not loaded and errs, "load() with no extra_fields is byte-for-byte back-compatible")
    loaded, errs = R.load(p, extra_fields={"tenure"})
    ck(len(loaded) == 1 and not errs,
       f"load(extra_fields=...) accepts a field the DATA carries, as the override loader does "
       f"{errs}")
    loaded, errs = R.load(p, extra_fields=())
    ck(not loaded and errs, "an empty extra_fields is the documented default, not a widening")

    print()
    print("== the denied fields are untouched, and their message still wins ==")
    for f in sorted(R.DENIED_FIELDS):
        w = work_with([entry(set={f: "x"})])
        rep = R.run(w)
        ck(not rep["applied"] and len(rep["invalid"]) == 1, f"`set` {f!r} is still refused")
        ck(any("structural or a dataset-wide unit label" in s for s in rep["invalid"]),
           f"...with the DENIAL message, not the membership one ({f})")
        ck(all("not a canonical property field" not in s for s in rep["invalid"]),
           f"...and the membership message never appears ({f})")
        w = work_with([entry(unset=[f])])
        rep = R.run(w)
        ck(not rep["applied"] and any("structural or a dataset-wide unit label" in s
                                      for s in rep["invalid"]),
           f"`unset` {f!r} is refused by the same rule (a new verb is not a new hole)")
        ck(f in props_of(w)[0] or f not in canon(),
           f"...and {f} was not removed from the property")
        c = canon()
        r = R.apply(c, [entry(unset=[f])])
        ck(not r["applied"] and any("structural or a dataset-wide unit label" in s
                                    for s in r["invalid"]),
           f"...refused through apply() too, so a direct caller cannot bypass it ({f})")

    print()
    print("== A7 `unset`: cleared means REMOVED, and the ledger says so ==")
    w = work_with([entry(unset=["tenure"])])
    rep = R.run(w)
    p1 = props_of(w)[0]
    ck(len(rep["applied"]) == 1, f"an `unset` applies {rep['invalid']}")
    ck("tenure" not in p1, "the key is GONE, not overwritten with a sentinel")
    ck(p1.get("warehouseArea") == 10000 and p1.get("yardDepth") == "35 m",
       "...and nothing else on the property moved")
    rows = R.ledger_rows(rep)
    ck(len(rows) == 1 and rows[0]["field"] == "tenure", "one ledger row for the cleared field")
    ck("CLEARED" in rows[0]["conflict_note"],
       f"the row SAYS cleared, in those words {rows[0]['conflict_note'][:60]!r}")
    ck("ABSENT" in rows[0]["conflict_note"] and "not set to a sentinel"
       in rows[0]["conflict_note"],
       "...and states that the key is absent rather than holding the sentinel")
    ck("Leasehold" in rows[0]["conflict_note"], "...and records what was withdrawn")
    ck(str(rows[0]["value"]).strip() != "",
       "the value cell is non-empty - an empty one hard-blocks ledger validate")
    ck(rows[0]["record_type"] == "repair" and rows[0]["verified"] == "t@cbre.com",
       "...and it is still a disclosed, attributed repair row")
    ck(any("CLEARED" in ln for ln in R.format_report(rep)),
       f"the operator report says cleared too {R.format_report(rep)[:1]}")

    # a chrome-read key cannot vanish: the render boundary re-fills its honest unknown
    w = work_with([entry(unset=["region"])])
    rep = R.run(w)
    p1 = props_of(w)[0]
    ck(len(rep["applied"]) == 1 and "region" not in p1,
       "a chrome-read field clears out of canonical")
    ck(C.fill_render_sentinels(dict(p1)).get("region") == C.BLANK,
       "...and the RENDER boundary re-fills its honest sentinel, so the card is never blank")

    # THE REQUIRED-FIELD CLEAR GUARD, THROUGH BOTH DOORS. It is deliberately duplicated in
    # `load` and in `apply`, on the correct grounds that `apply` is called directly and a guard
    # a caller can walk around is not a guard. Only the `load` copy was asserted, so of eleven
    # mutations tested against this file the deletion of the `apply` copy was the one that
    # SURVIVED: with it gone, a schema-required key is popped, canonical is left
    # un-schema-valid, and validate-data hard-blocks the whole build for a one-card change.
    # Both doors are now asserted for every required key, and the direct call is the assertion
    # that kills that mutant.
    _required = sorted(R._schema_required_fields())
    ck(set(_required) == {"city", "country", "developer", "id", "park", "photo", "status"},
       f"the schema declares exactly these seven property keys required, so the cases below "
       f"prove the guard rather than assuming a list {_required}")
    # `id` and `photo` are required AND denied, and the DENIED message deliberately wins for
    # them (a forbidden key is known and refused, not merely required), so the required-field
    # message is asserted on the five that only the schema constrains.
    for f in [k for k in _required if k not in R.DENIED_FIELDS]:
        w = work_with([entry(unset=[f])])
        rep = R.run(w)
        ck(not rep["applied"] and any("REQUIRED by the canonical schema" in s
                                      for s in rep["invalid"]),
           f"a schema-required key ({f}) can never be cleared through run()/load() - it would "
           f"hard-block validate-data")
        ck(f in props_of(w)[0], f"...and {f} is still there")
        # THE SAME CLEAR, STRAIGHT INTO apply(), BYPASSING load() ENTIRELY. This is the
        # assertion whose absence let the `apply` copy of the guard be deleted silently.
        c = canon()
        r = R.apply(c, [entry(unset=[f])], provenance=LEDGER)
        ck(not r["applied"] and any("REQUIRED by the canonical schema" in s
                                    for s in r["invalid"]),
           f"...and refused through apply() called DIRECTLY ({f}), so a caller holding its own "
           f"entries cannot walk around it")
        ck(f in c["properties"][0],
           f"...with the key still on the property after the direct call ({f})")
        ck(not r["stale"] and not r["superseded"],
           f"...and it is INVALID, not quietly bucketed elsewhere ({f})")

    # THE GUARD'S OWN INPUT MUST FAIL LOUDLY. `_schema_required_fields` used to swallow every
    # exception into an EMPTY frozenset, on the argument that repairs run before the gates so a
    # refusal it could not justify would be judged there anyway. That is backwards for this
    # guard specifically: an empty set refuses NOTHING, so renaming `$defs.property`, moving
    # `required`, or shipping an unreadable schema would silently DISARM the one check standing
    # between a one-line clear and the hard block - and the gate it deferred to is the gate
    # that hard-blocks. A guard that turns itself off is worse than no guard, because the
    # operator believes it is on.
    _real_schema, _cache = C.SCHEMA_FILE, R._SCHEMA_REQUIRED_FIELDS
    try:
        C.SCHEMA_FILE = Path(tempfile.mkdtemp(prefix="cbre_no_schema_")) / "gone.json"
        R._SCHEMA_REQUIRED_FIELDS = None
        raised = None
        try:
            R._schema_required_fields()
        except R.SchemaRequiredUnavailable as ex:
            raised = ex
        except Exception as ex:                                  # pragma: no cover
            raised = ex
        ck(isinstance(raised, R.SchemaRequiredUnavailable),
           f"an unreadable schema RAISES SchemaRequiredUnavailable instead of returning an "
           f"empty set that refuses nothing (got {raised!r})")
        _fields, _reason = R._required_fields_or_reason()
        ck(_fields == frozenset() and _reason and "cannot be armed" in _reason,
           f"...and the shared resolver hands the reason back rather than swallowing it "
           f"{_reason!r}")
        c = canon()
        r = R.apply(c, [entry(unset=["tenure"])], provenance=LEDGER)
        ck(not r["applied"] and len(r["invalid"]) == 1 and "tenure" in c["properties"][0],
           f"...so a clear is REFUSED while the guard cannot be armed, and nothing is removed "
           f"{r['invalid']}")
        ck(any("hard-block" in s for s in r["invalid"]),
           f"...naming the cost it is protecting the run from {r['invalid']}")
        r = R.apply(c, [entry(set={"tenure": "Freehold"})], provenance=LEDGER)
        ck(len(r["applied"]) == 1,
           "...while an entry that clears NOTHING is unaffected - the guard only judges clears")
        loaded, errs = R.load(work_with([entry(unset=["tenure"])]) / "repairs.json",
                              extra_fields={"tenure"})
        ck(not loaded and len(errs) == 1 and "guard" in errs[0],
           f"...and load() refuses it the same way, per entry, in the report an operator reads "
           f"{errs}")
        # A RESTRUCTURE is the likelier route than an unreadable file, and it is the one the
        # empty-set fallback hid best: a readable schema whose `$defs.property.required` has
        # moved, been renamed, or been emptied resolves to no required fields at all, which
        # refuses nothing while looking like a working guard.
        _fake = Path(tempfile.mkdtemp(prefix="cbre_moved_schema_")) / "canonical.schema.json"
        for _shape, _why in (
                ({"$defs": {"property": {"required": [], "properties": {}}}},
                 "an EMPTY required array"),
                ({"$defs": {"propertyRecord": {"required": ["city"]}}},
                 "`$defs.property` renamed"),
                ({"properties": {"city": {}}, "required": ["city"]},
                 "`required` hoisted out of `$defs`")):
            _fake.write_text(json.dumps(_shape), encoding="utf-8")
            C.SCHEMA_FILE, R._SCHEMA_REQUIRED_FIELDS = _fake, None
            _raised = None
            try:
                R._schema_required_fields()
            except R.SchemaRequiredUnavailable as ex:
                _raised = ex
            ck(isinstance(_raised, R.SchemaRequiredUnavailable),
               f"a schema restructure ({_why}) fails LOUDLY rather than resolving to a guard "
               f"that refuses nothing (got {_raised!r})")
            R._SCHEMA_REQUIRED_FIELDS = None
            c = canon()
            r = R.apply(c, [entry(unset=["city"])], provenance=LEDGER)
            ck(not r["applied"] and r["invalid"] and c["properties"][0].get("city"),
               f"...and the clear it would have let through is refused ({_why})")
        R._SCHEMA_REQUIRED_FIELDS = None
        C.SCHEMA_FILE = _real_schema
        ck(sorted(R._schema_required_fields()) == _required,
           "...and NEITHER failure is cached, so fixing the schema needs no restart")
    finally:
        C.SCHEMA_FILE, R._SCHEMA_REQUIRED_FIELDS = _real_schema, _cache

    w = work_with([entry(set={"tenure": "Freehold"}, unset=["tenure"])])
    rep = R.run(w)
    ck(not rep["applied"] and any("BOTH `set` and `unset`" in s for s in rep["invalid"]),
       "one entry cannot write and withdraw the same field - fail closed, never guess")

    # A MISSPELLED `unset` IS `stale`, WRITES NO LEDGER ROW, AND IS NOT "APPLIED".
    #
    # A clear cannot CREATE a field, so it must not earn `set`'s INVALID verdict: that would
    # make a working `unset` of an off-spec key refuse itself for good on its second run, when
    # the key it removed is on no property. The previous fix for that removed the CHECK instead
    # of changing the BUCKET, and the result was worse than the problem: `unset: ["tenrue"]`
    # against a property carrying `tenure` was reported APPLIED - which is what an operator
    # triaging the report reads as a success - with the spelling hint buried in a bracketed
    # tail, and it minted a Source Ledger `repair` row for a field that exists on no schema and
    # on no property, breaking the module's own invariant that a repair row's field already has
    # its own property row. `stale` is true of the misspelling and of a correctly re-applied
    # clear alike (nothing happened, on both readings), so both now report it, and neither
    # fabricates a row.
    w = work_with([entry(unset=["tenrue"])])
    rep = R.run(w)
    ck(not rep["applied"] and len(rep["stale"]) == 1 and not rep["invalid"],
       f"an `unset` naming a field the property does not carry is STALE, not APPLIED "
       f"{ {k: len(v) for k, v in rep.items() if v} }")
    ck("already absent" in rep["stale"][0]["reason"],
       f"...with the already-absent wording kept {rep['stale'][0]['reason'][:60]!r}")
    ck("tenrue" in rep["stale"][0]["reason"]
       and "spelling" in rep["stale"][0]["reason"],
       "...naming the key and telling the operator to check the spelling")
    ck(R.ledger_rows(rep) == [],
       f"...and writing NO Source Ledger row - a repair row for a field with no property row "
       f"of its own is a fabrication {R.ledger_rows(rep)}")
    ck(any("STALE REPAIR" in ln and "tenrue" in ln for ln in R.format_report(rep)),
       f"...and the operator report files it under STALE, not among the applied corrections "
       f"{R.format_report(rep)[:1]}")
    ck(props_of(w)[0].get("tenure") == "Leasehold",
       "...and the near-miss field it resembles was NOT touched")

    # THE SAME NO-OP FROM THE OTHER DIRECTION: a clear that really did land, re-applied. The
    # bucket and the (absent) row are decided by the PROPERTY alone, so they are identical to
    # the misspelling above; only the message differs, and it differs because the Source Ledger
    # still credits the property with the field. The ledger is deliberately not allowed to
    # decide the bucket: its `record_type=property` rows survive a full re-merge but the prior
    # clear's own `repair` row does not, so a verdict resting on the repair row would flip
    # between a resumed run and a full one.
    w = work_with([entry(unset=["tenure"])])
    rep1 = R.run(w)
    ck(len(rep1["applied"]) == 1 and len(R.ledger_rows(rep1)) == 1,
       "a real clear applies on the first run and discloses itself")
    rep2 = R.run(w)
    ck(not rep2["applied"] and len(rep2["stale"]) == 1
       and not rep2["invalid"] and not rep2["superseded"],
       f"...and on the second run reads as a STALE no-op, never INVALID and never SUPERSEDED "
       f"{ {k: len(v) for k, v in rep2.items() if v} }")
    ck(R.ledger_rows(rep2) == [], "...writing no second row for a key that is already gone")
    ck("landed on an earlier run" in rep2["stale"][0]["reason"],
       f"...and the message says WHICH no-op it is, because the ledger still credits the "
       f"property with the field {rep2['stale'][0]['reason'][-90:]!r}")

    # AN ENTRY IS NOT ABANDONED BY ITS ALREADY-SATISFIED CLEAR. A repair is re-applied on every
    # run, and resume skips merge, so a `set` that stops re-writing its ledger row leaves its
    # value with no provenance and trace-coverage blocks the build. So the `set` half still
    # lands and still discloses itself while the absent clear is reported stale beside it.
    w = work_with([entry(set={"warehouseArea": 23567}, unset=["tenrue"])])
    rep = R.run(w)
    ck(len(rep["applied"]) == 1 and len(rep["stale"]) == 1,
       f"a `set` beside an already-satisfied clear still applies, and the clear is still "
       f"reported {  {k: len(v) for k, v in rep.items() if v} }")
    ck(props_of(w)[0].get("warehouseArea") == 23567, "...the value landed")
    ck([r["field"] for r in R.ledger_rows(rep)] == ["warehouseArea"],
       f"...and exactly ONE row was written, for the field that actually moved "
       f"{[r['field'] for r in R.ledger_rows(rep)]}")

    # A SCHEMA-DECLARED key that this property simply never carried is the third reading, and
    # it is a no-op too - not a typo, so the message must not tell the operator to check the
    # spelling of a name the schema itself declares.
    w = work_with([entry(unset=["epc"])])
    rep = R.run(w)
    ck(not rep["applied"] and len(rep["stale"]) == 1,
       "an `unset` of a schema-declared key the property lacks is also a STALE no-op")
    ck("the schema declares it" in rep["stale"][0]["reason"]
       and "spelling" not in rep["stale"][0]["reason"],
       f"...and it is NOT reported as a misspelling {rep['stale'][0]['reason'][-80:]!r}")

    w = work_with([entry(unset="tenure")])
    rep = R.run(w)
    ck(not rep["applied"] and any("must be a LIST" in s for s in rep["invalid"]),
       "`unset` must be a list of names (a bare string is a refused entry, not a surprise)")

    w = work_with([entry()])
    rep = R.run(w)
    ck(not rep["applied"] and any("nothing to do" in s for s in rep["invalid"]),
       "an entry with no verb at all is still 'nothing to do'")

    print()
    print("== A7 `strike_from_source`: unfuse by FILE, not by nineteen field names ==")
    w = work_with([entry(strike_from_source=DECK,
                         why="the matcher merged two units; this deck is the other one")])
    rep = R.run(w)
    p1, p2 = props_of(w)
    ck(len(rep["applied"]) == 1, f"the strike applies {rep['invalid']} {rep['stale']}")
    ck(set(rep["applied"][0]["changed"]) == {"warehouseArea", "tenure"},
       f"exactly the fields the ledger credits to that file "
       f"{sorted(rep['applied'][0]['changed'])}")
    ck("warehouseArea" not in p1 and "tenure" not in p1, "...and both are gone")
    ck(p1.get("status") == "Available" and p1.get("yardDepth") == "35 m",
       "the OTHER source's fields survive untouched - a strike is not a reset")
    ck(p1.get("photo") == PX and p1.get("city") == "Northtown",
       "media-owned and schema-required fields are protected, not removed")
    ck(set(rep["applied"][0]["protected"]) == {"photo", "city"},
       f"...and the protection is REPORTED, so half-done unfusing is never silent "
       f"{rep['applied'][0]['protected']}")
    ck(any("NOT struck" in ln and "photo" in ln for ln in R.format_report(rep)),
       "...including in the operator report, with what to use instead")
    ck(p2.get("sidingAccess") == "rail served",
       "the same file on ANOTHER property is left alone - provenance is per property")
    rows = R.ledger_rows(rep)
    ck(len(rows) == 2 and {r["field"] for r in rows} == {"warehouseArea", "tenure"},
       f"one ledger row per struck field {[r['field'] for r in rows]}")
    ck(all("CLEARED" in r["conflict_note"] and DECK in r["conflict_note"] for r in rows),
       "...each saying it was cleared and naming the file it was struck with")

    # basename, case-insensitively - the same rule the override channel uses for where.source_file
    for named in (DECK.upper(), f"some/other/path/{DECK}", f"  {DECK}  "):
        w = work_with([entry(strike_from_source=named)])
        rep = R.run(w)
        ck(len(rep["applied"]) == 1
           and set(rep["applied"][0]["changed"]) == {"warehouseArea", "tenure"},
           f"a strike matches on basename, case-insensitively: {named!r}")

    w = work_with([entry(strike_from_source="never-ingested.pdf")])
    rep = R.run(w)
    ck(not rep["applied"] and len(rep["stale"]) == 1,
       "a file the ledger credits with NO field on this property is STALE, not a silent no-op")
    ck("never-ingested.pdf" in rep["stale"][0]["reason"]
       and R.LEDGER_NAME in rep["stale"][0]["reason"],
       f"...and the reason names the file and where to check it "
       f"{rep['stale'][0]['reason'][:70]!r}")
    ck(props_of(w)[0].get("warehouseArea") == 10000, "...and nothing was removed")

    # WITH NO LEDGER AT ALL. Two things are asserted that were not: the PRECONDITION (that the
    # fixture really did leave the ledger absent, so the INVALID cannot be coming from
    # somewhere else), and the outcome through a guard, because deleting `apply`'s `prov is
    # None` branch makes the module raise an AttributeError on `None` - which killed this eval
    # with a traceback instead of reporting a FAIL naming the guard.
    w = work_with([entry(strike_from_source=DECK)], ledger=None)
    ck(not (w / R.LEDGER_NAME).exists(),
       f"precondition: the fixture left {R.LEDGER_NAME} absent, so the outcome below is "
       f"caused by the missing ledger and nothing else")
    try:
        rep = R.run(w)
        crashed = None
    except Exception as ex:                                      # pragma: no cover
        rep, crashed = {k: [] for k in R.REPORT_KEYS}, ex
    ck(crashed is None,
       f"a strike with no ledger is HANDLED, not an exception - `apply`'s `prov is None` "
       f"branch is what stands between a missing ledger and a crash ({crashed!r})")
    ck(not rep["applied"] and any("Source Ledger" in s for s in rep["invalid"]),
       "with NO ledger to read, a strike is INVALID - 'I could not look' is not 'nothing "
       "came from that file'")
    ck(not rep["stale"], "...and it is NOT reported as stale, which would be a different claim")
    ck(props_of(w)[0].get("warehouseArea") == 10000, "...and nothing was removed")

    print()
    print("== a basename naming TWO DIFFERENT files strikes NOTHING ==")
    # A folder of property materials from several senders routinely holds two files with one
    # common name, so `.../a/deck.pdf` beside `.../b/deck.pdf` is an ordinary shape here, not a
    # contrivance. Matched on basename alone, a strike naming one removed the fields of BOTH -
    # silent deletion of correct, sourced data, with a ledger row crediting the deletion to a
    # file that never supplied it. The override channel's identical targeting clause is no
    # precedent: it narrows further by page, row and sheet, and it SUBSTITUTES rather than
    # DELETES.
    TWIN = [
        {"property_id": "1", "record_type": "property", "field": "warehouseArea",
         "value": "10000", "source_file": "inbox/sender-a/deck.pdf",
         "source_locator": "page 3", "source_type": "pdf"},
        {"property_id": "1", "record_type": "property", "field": "yardDepth", "value": "35 m",
         "source_file": "inbox/sender-b/deck.pdf", "source_locator": "page 2",
         "source_type": "pdf"},
    ]
    w = work_with([entry(strike_from_source="deck.pdf")], ledger=TWIN)
    rep = R.run(w)
    p1 = props_of(w)[0]
    ck(not rep["applied"] and len(rep["ambiguous"]) == 1 and not rep["stale"],
       f"a bare basename matching TWO different paths is AMBIGUOUS "
       f"{ {k: len(v) for k, v in rep.items() if v} }")
    ck(p1.get("warehouseArea") == 10000 and p1.get("yardDepth") == "35 m",
       "...and NEITHER file's fields were removed - the entry applied nothing")
    ck(R.ledger_rows(rep) == [], "...and no ledger row claimed a removal that did not happen")
    _why = rep["ambiguous"][0]["reason"]
    ck("inbox/sender-a/deck.pdf" in _why and "inbox/sender-b/deck.pdf" in _why,
       f"...and the report names the COMPETING paths verbatim, so the operator can paste one "
       f"back {_why[:120]!r}")
    ck("LEADING FOLDERS" in _why, "...and says how to disambiguate")

    # THE WAY OUT: leading folders narrow the match, segment-wise. A full path works and so
    # does any trailing part of one, which is what makes this usable without knowing the whole
    # prefix the extractor happened to record.
    for named, want_field, keep_field in (
            ("inbox/sender-a/deck.pdf", "warehouseArea", "yardDepth"),
            ("sender-a/deck.pdf", "warehouseArea", "yardDepth"),
            ("sender-b/deck.pdf", "yardDepth", "warehouseArea"),
            ("sender-b\\deck.pdf", "yardDepth", "warehouseArea")):
        w = work_with([entry(strike_from_source=named)], ledger=TWIN)
        rep = R.run(w)
        ck(len(rep["applied"]) == 1
           and set(rep["applied"][0]["changed"]) == {want_field},
           f"{named!r} narrows the strike to {want_field} alone "
           f"{sorted(rep['applied'][0]['changed']) if rep['applied'] else rep}")
        ck(keep_field in props_of(w)[0],
           f"...and the OTHER file's field survives ({keep_field})")
        ck(rep["applied"][0]["changed"][want_field].get("struck_from", "").endswith(
               "deck.pdf") and "sender-" in rep["applied"][0]["changed"][want_field]["struck_from"],
           f"...and the disclosure names the RESOLVED ledger path, not the bare basename, so "
           f"the narrowing that made the strike legal survives into the audit trail "
           f"{rep['applied'][0]['changed'][want_field].get('struck_from')!r}")

    # A path recorded at two DEPTHS is ONE file, not two, which is exactly what basename
    # matching exists for and is the shape the main LEDGER above already uses (`shared-deck.pdf`
    # for one field, `work/inputs/shared-deck.pdf` for another). Pinned explicitly so the
    # ambiguity guard can never be tightened into refusing it.
    w = work_with([entry(strike_from_source=DECK)])
    rep = R.run(w)
    ck(len(rep["applied"]) == 1 and not rep["ambiguous"]
       and set(rep["applied"][0]["changed"]) == {"warehouseArea", "tenure"},
       f"one file the ledger records at two depths stays ONE strike target "
       f"{ {k: len(v) for k, v in rep.items() if v} }")

    _named, _competing, _resolved = R._strike_targets(
        R._prov_index(TWIN)["1"], "deck.pdf")
    ck(_named == [] and len(_competing) == 2 and not _resolved,
       f"_strike_targets itself refuses to resolve the ambiguous request {_competing}")
    _named, _competing, _resolved = R._strike_targets(
        R._prov_index(TWIN)["1"], "sender-a/deck.pdf")
    ck(_named == ["warehouseArea"] and not _competing
       and _resolved == "inbox/sender-a/deck.pdf",
       f"...and resolves the narrowed one to exactly one path {_named} {_resolved!r}")
    ck(R._path_parts("  INBOX\\Sender-A\\Deck.PDF ") == ("inbox", "sender-a", "deck.pdf"),
       "a path is compared as lower-cased SEGMENTS, separator-agnostic")
    # SEGMENT-WISE, never `str.endswith`. The lengths have to DIFFER for this to prove
    # anything: `_is_under` requires a PROPER suffix, so an equal-length pair is refused by the
    # length test alone and a string-endswith implementation would pass such a case too.
    ck(not R._is_under(("a", "deck.pdf"), ("x", "extra-a", "deck.pdf")),
       "...so `a/deck.pdf` is never read as a trailing part of `x/extra-a/deck.pdf` (a string "
       "endswith would say it is, and would then treat two different files as one)")
    ck(not R._is_under(("a", "deck.pdf"), ("extra-a", "deck.pdf")),
       "...nor of a same-length path that merely ends in the same characters")
    ck(R._is_under(("deck.pdf",), ("work", "inputs", "deck.pdf")),
       "...while a shallower record of the same file is recognised as the same file")
    # and the same thing where it actually costs data: a folder whose name ENDS with another
    # folder's name must not collapse two files into one strike target.
    NEARMISS = [
        {"property_id": "1", "record_type": "property", "field": "warehouseArea",
         "value": "10000", "source_file": "a/deck.pdf", "source_locator": "page 3",
         "source_type": "pdf"},
        {"property_id": "1", "record_type": "property", "field": "yardDepth", "value": "35 m",
         "source_file": "x/extra-a/deck.pdf", "source_locator": "page 2", "source_type": "pdf"},
    ]
    w = work_with([entry(strike_from_source="deck.pdf")], ledger=NEARMISS)
    rep = R.run(w)
    p1 = props_of(w)[0]
    ck(not rep["applied"] and len(rep["ambiguous"]) == 1,
       f"`a/deck.pdf` and `x/extra-a/deck.pdf` are two DIFFERENT files, so a bare `deck.pdf` "
       f"is AMBIGUOUS { {k: len(v) for k, v in rep.items() if v} }")
    ck(p1.get("warehouseArea") == 10000 and p1.get("yardDepth") == "35 m",
       "...and neither is removed - a folder name that merely ENDS IN another's is not a "
       "deeper record of it, which is why the subsumption test compares whole segments")
    # ...and the narrowing still separates them, on the same near-miss pair
    for _named, _want, _keep in (("a/deck.pdf", "warehouseArea", "yardDepth"),
                                 ("extra-a/deck.pdf", "yardDepth", "warehouseArea")):
        w = work_with([entry(strike_from_source=_named)], ledger=NEARMISS)
        rep = R.run(w)
        ck(len(rep["applied"]) == 1 and set(rep["applied"][0]["changed"]) == {_want},
           f"{_named!r} still resolves to {_want} alone across the near-miss pair "
           f"{sorted(rep['applied'][0]['changed']) if rep['applied'] else rep}")
        ck(_keep in props_of(w)[0], f"...and {_keep} survives")

    # A strike whose fields are ALL protected, sitting beside an already-satisfied clear: the
    # entry has no applied row to carry `protected` on, so the half-done unfusing has to be
    # said in the stale bucket or it is lost. `photo` and `city` are the DECK's protected
    # fields; `tenrue` is the absent clear that stops the early protected-only branch firing.
    PROT = [r for r in LEDGER if r["field"] in ("photo", "city")]
    c = canon()
    r = R.apply(c, [entry(strike_from_source=DECK, unset=["tenrue"])], provenance=PROT)
    ck(not r["applied"] and len(r["stale"]) == 2,
       f"an all-protected strike beside an absent clear reports BOTH no-ops "
       f"{ {k: len(v) for k, v in r.items() if v} }")
    ck(any("structural, media-owned or schema-required" in s["reason"] for s in r["stale"]),
       f"...including WHAT the strike refused to remove, so half-done unfusing is never "
       f"silent {[s['reason'][:50] for s in r['stale']]}")
    ck(c["properties"][0].get("photo") == PX and c["properties"][0].get("city") == "Northtown",
       "...and the protected fields are still on the property")

    c = canon()
    r = R.apply(c, [entry(strike_from_source=TRACKER)], provenance=LEDGER)
    ck(len(r["applied"]) == 1 and set(r["applied"][0]["changed"]) == {"yardDepth"},
       f"apply() takes the ledger rows directly {r['invalid']} "
       f"{[sorted(a['changed']) for a in r['applied']]}")
    ck(r["applied"][0]["protected"] == ["status"] and c["properties"][0]["status"] == "Available",
       "...and the same protection applies through apply(): a required field is kept and named")
    ck("region" in c["properties"][0],
       "a `gap` row attributes nothing, so its field is never struck")

    print()
    print("== both clearing verbs survive re-application, exactly like `set` ==")
    # A guarded `unset` must not read its own success as drift. The two verbs then diverge, on
    # EVIDENCE rather than taste, and both halves are pinned here:
    #   `unset` names a field by hand with nothing backing it, so once the key is gone there is
    #     no property row to attach a repair row to - it reports the no-op and writes nothing;
    #   a STRIKE resolves its fields OUT OF the ledger, so every field it clears provably has a
    #     property row, its row is never a fabrication, and it keeps re-writing it.
    w = work_with([entry(expect={"tenure": "Leasehold"}, unset=["tenure"])])
    ck(len(R.run(w)["applied"]) == 1, "a guarded `unset` applies on the first run")
    rep2 = R.run(w)
    ck(not rep2["superseded"],
       f"...and on the second, when the field is already gone, the `expect` guard does NOT "
       f"fire - its own success is not drift {rep2['superseded']}")
    ck(not rep2["applied"] and len(rep2["stale"]) == 1 and not rep2["invalid"],
       f"...it reports the no-op instead of claiming a second successful clear "
       f"{ {k: len(v) for k, v in rep2.items() if v} }")
    ck(R.ledger_rows(rep2) == [],
       f"...and writes no row for a key that is absent from the property {R.ledger_rows(rep2)}")

    w = work_with([entry(strike_from_source=DECK, expect={"warehouseArea": 10000})])
    ck(len(R.run(w)["applied"]) == 1, "a guarded strike applies on the first run")
    rep2 = R.run(w)
    ck(len(rep2["applied"]) == 1 and not rep2["superseded"] and not rep2["stale"],
       "...and on the second, rather than reporting itself STALE in the Gaps Report")

    w = work_with([entry(expect={"tenure": "Freehold"}, unset=["tenure"])])
    rep = R.run(w)
    ck(not rep["applied"] and len(rep["superseded"]) == 1,
       "real drift still SUPERSEDES a clear - the guard is not loosened by the new verbs")
    ck(props_of(w)[0].get("tenure") == "Leasehold", "...and nothing was removed")

    print()
    print("== a clear must not annotate a merge-time 'ships tbd' note ==")
    w = work_with([entry(unset=["warehouseArea"])])
    rep = R.run(w)
    notes = json.loads((w / "canonical.json").read_text(encoding="utf-8"))["meta"]["conflicts"]
    ck(len(rep["applied"]) == 1 and all("[RESOLVED" not in n for n in notes),
       "a withdrawal makes 'the card ships tbd' TRUE again, so it is left standing")

    print()
    print("== A18a: a repair may cite the evidence it was read from ==")
    w = work_with([entry(set={"warehouseArea": 23567},
                         source_file="unit-brochure.pdf", source_locator="page 6 (spec table)")])
    rep = R.run(w)
    rows = R.ledger_rows(rep)
    ck(len(rows) == 1 and rows[0]["source_file"] == "unit-brochure.pdf",
       f"the cited source_file reaches the ledger column {rows[0]['source_file']!r}")
    ck(rows[0]["source_locator"] == "page 6 (spec table)",
       f"...and so does the cited source_locator {rows[0]['source_locator']!r}")
    ck(rows[0]["record_type"] == "repair" and rows[0]["source_type"] == "repair"
       and rows[0]["extractor"] == "repairs.py",
       "...while the row is still identifiable as a repair (grep ,repair, still finds it)")
    ck(rows[0]["confidence"] == "verified" and rows[0]["verified"] == "t@cbre.com",
       "confidence is unchanged and verified_by still records who stands behind it")
    ck("rp-001" in rows[0]["conflict_note"], "...and the note still names the repair")

    w = work_with([entry(set={"warehouseArea": 23567})])
    rep = R.run(w)
    rows = R.ledger_rows(rep)
    ck(rows[0]["source_file"] == "repairs.json" and rows[0]["source_locator"] == "rp-001",
       "with NO citation, today's values stand unchanged (absent keeps the old behaviour)")

    for bad, why in ((entry(set={"warehouseArea": 1}, source_file="  "), "a blank source_file"),
                     (entry(set={"warehouseArea": 1}, source_locator=""),
                      "a blank source_locator"),
                     (entry(set={"warehouseArea": 1}, source_file=7), "a non-string citation")):
        w = work_with([bad])
        rep = R.run(w)
        ck(not rep["applied"] and rep["invalid"],
           f"refused: {why} - it replaces a ledger column, and an empty cell hard-blocks")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
