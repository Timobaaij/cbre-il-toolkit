#!/usr/bin/env python3
# © 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""merge.py - Stage 2. Combine candidate records into the canonical dataset.

Reads one or more extractor record files, dedupes cross-source duplicates
(match.py), merges each cluster by field-class source precedence, assigns stable
ids, attaches a compressed base64 hero image per property (a PPTX slide picture
if one was extracted, else a brochure PDF-page raster, else a placeholder),
seeds POIs from the library, and writes canonical.json plus a field-level
source_ledger.csv.

Precedence:
  commercial fields (rent/terms/incentives/land): newest email > excel > brochure
  physical specs / geo / everything else:          brochure (pdf>pptx) > excel > email

CLI:
  python merge.py --records a.json b.json --source-dir <folder> \
                  --project-yaml project.yaml --out canonical.json [--ledger ledger.csv]
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C
import match
import normalize as N
import images as IMG
import extract_pdf as XP  # best_description_in_deck for the photo-match path
import i18n as I18N        # Phase 2: EN key whitelist for the --ui-overrides bake

COMMERCIAL = {"warehouseRent", "warehouseRentVal", "officeRent", "serviceCharge",
              "leaseTerm", "rentFree", "incentives", "landPrice"}

# lower rank = preferred
SPEC_RANK = {"pdf": 0, "pptx": 1, "xlsx": 2, "msg": 3, "email": 3, "image": 4, "web": 5}
COMM_RANK = {"email": 0, "msg": 0, "xlsx": 1, "pdf": 2, "pptx": 3, "image": 4, "web": 5}
# IMAGE-source preference (distinct from field precedence): a slide picture (PPTX)
# is higher-res than a PDF-page raster, so it outranks pdf here - the inverse of
# SPEC_RANK. PDF stays the preferred FIELD source.
IMG_RANK = {"pptx": 0, "image": 1, "pdf": 2, "web": 3, "xlsx": 4, "email": 5, "msg": 5}

# A20: the most pages of ONE deck `prewarm_images` enumerates geometry/gallery units for. A
# guard against a 400-page portfolio document burning the whole budget on pages no property will
# ever claim, not a statement about how long a brochure can be. It was an unnamed literal `80`
# written twice inside the enumeration, where nothing said it was a cap at all: the count it
# produced was then reported as the corpus TOTAL, so a longer deck's later pages were silently
# outside the figure the caller printed as completeness. Named here so the cap is visible, is one
# number, and can be read by the code that has to report what it did NOT look at.
PREWARM_MAX_DECK_PAGES = 80

# a seeded library POI farther than this from EVERY property is not this dataset's
# region (we never surface a 'nearest' POI beyond ~this range anyway), so it is
# dropped. Region-neutral: pure distance, no place names or country adjacency.
SEED_MAX_KM = 800


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _st(rec):  # source type
    return rec.get("__meta", {}).get("source_type", "pdf")


def _date(rec):
    return rec.get("__meta", {}).get("date", "")


def _normalise_offspec(rec: dict) -> dict:
    """Move off-spec STRUCTURES out of the record's top level into __meta.offspec BEFORE
    clustering, so they can never become a displayed field: (a) a dict/list whose key is
    NOT a canonical field (a stray provenance/meta map), or (b) a scalar whose value is a
    pipeline locator string. Genuine scalar attributes (canonical AND brand-new) and
    canonical container objects (gallery/preBaked/districtProfile) are KEPT so auto-show is
    preserved. Deterministic; a clean record is unchanged."""
    canon = C.canonical_property_fields()
    meta = rec.setdefault("__meta", {})
    for k in [k for k in rec if k != "__meta"]:
        v = rec[k]
        if (isinstance(v, (dict, list)) and k not in canon) or C.looks_like_locator(v):
            meta.setdefault("offspec", {})[k] = v
            del rec[k]
    # B7: a brand-new SCALAR is deliberately KEPT (v22 auto-show) - but it is no longer kept
    # SILENTLY. `postcode` shipped on half the properties of a live run while the Gaps Report's
    # off-spec section read "None.", because that section only ever covered quarantined
    # structures. A section asserting "None" while a non-schema key reaches the client is a false
    # statement in the honesty document. Recorded here, rendered by deliver.py; the value itself
    # ships exactly as before.
    for k in rec:
        if k == "__meta" or k in canon:
            continue
        if isinstance(rec[k], (dict, list)):
            continue                       # a surviving container is canonical by definition above
        nf = meta.setdefault("new_fields", [])
        if k not in nf:
            nf.append(k)
    return rec


# BREEAM vs EPC (B5). Two DIFFERENT certificates on different scales: BREEAM grades
# sustainability design (Pass / Good / Very Good / Excellent / Outstanding), an EPC grades
# energy efficiency on a letter band (A+ / A / B). Neither substitutes for the other, and
# "BREEAM A+" is not a rating that exists.
_BREEAM_GRADE = re.compile(r"\b(?:pass|good|very\s+good|excellent|outstanding|unclassified)\b", re.I)
_EPC_BAND = re.compile(r"^(?:target\s+)?(?:epc\s*)?[A-G]\+?$", re.I)
_EPC_TOKEN = re.compile(r"\bepc\b[\s:.\-]*", re.I)


def _cert_unknown(v) -> bool:
    """Is a certification slot (breeam / epc) free, i.e. holding no stated value? (SEAM-13)

    Delegates to the shared family, `normalize.looks_unknown`, with the VALUE reading. A
    certification is prose ("Very Good", "A+", "Target A"), not a code, so the two-letter
    exemption `looks_unknown_code` carries for country codes has no counterpart here: a bare
    "na" in a BREEAM cell is "not applicable", which is exactly an unknown.

    What moved when the private set went. "tba", "TBS", "?", "na", "poa" and the market
    phrases now read as EMPTY (they are the reader prompts' own unknown markers, and the
    private set missed them, so a slot holding "TBA" refused a re-filed grade). A stated
    "none"/"None" now reads as OCCUPIED: the extraction contract names it a stated negative
    (this building has no BREEAM rating), and `_route_certifications` must not overwrite it
    with a value that arrived in the wrong field; the misfiled value goes to __meta.offspec
    instead, where it is audited rather than lost. "null" is never written by a reader
    (run.py's import-failure fallback only), so its exit changes nothing measurable."""
    return N.looks_unknown(v)


def _route_certifications(rec: dict) -> dict:
    """Re-file a certification that landed in the wrong field, BEFORE clustering. (B5)

    The extractor dictionary no longer treats `epc` as a breeam alias and the interpretation
    contract names the distinction, so nothing SHOULD arrive misfiled. This is the backstop
    that makes the fix retroactive: a warm work dir, a cached interpretation record, or any
    future source that conflates the two self-corrects instead of shipping an impossible grade
    to a client card. It is why the fix needs no re-interpretation round.

    Deterministic and conservative:
      * `breeam` holding a letter BAND (and no BREEAM word) is not a BREEAM grade. It moves to
        `epc` when `epc` is free; when `epc` is already taken it goes to `__meta.offspec`
        (preserved for audit, surfaced in the Gaps Report's off-spec section, never displayed)
        and `breeam` becomes an honest gap. It is never left where it is.
      * `epc` holding a BREEAM WORD is the mirror case and moves the other way.
      * The provenance key moves WITH the value, so the Source Ledger row follows the field
        and the re-route is stated in its locator rather than laundered.
      * A redundant leading "EPC" token is dropped from the value, because the field label
        already says EPC ("EPC A+" would otherwise render as "EPC: EPC A+"). "Target" is kept.
      * A clean record is returned unchanged.
    """
    meta = rec.setdefault("__meta", {})
    prov = meta.get("prov") if isinstance(meta.get("prov"), dict) else None

    def _move(src: str, dst: str, value: str, why: str) -> None:
        rec.pop(src, None)
        if _cert_unknown(rec.get(dst)):
            rec[dst] = value
            if prov and src in prov:
                prov[dst] = f"{prov.pop(src)} (re-filed from {src}: {why})"
        else:
            meta.setdefault("offspec", {})[f"{src}_misfiled"] = value
            if prov and src in prov:
                prov.pop(src)

    b = rec.get("breeam")
    if isinstance(b, str) and not _cert_unknown(b) \
            and _EPC_BAND.match(b.strip()) and not _BREEAM_GRADE.search(b):
        _move("breeam", "epc", _EPC_TOKEN.sub("", b).strip(),
              "an EPC letter band is not a BREEAM grade")

    e = rec.get("epc")
    # D15 follow-up. The "is there an EPC rating here?" question is answered by `_EPC_GATE_RX`,
    # which matches a rating TOKEN anywhere in the string. This branch used the whole-string
    # `_EPC_BAND` instead, so the router and the plausibility gate disagreed about the same
    # value: a composite stating BOTH ("EPC A. BREEAM Excellent.") failed the anchored band,
    # satisfied the BREEAM search, and was re-filed WHOLESALE - which deleted a stated EPC
    # rating from `epc` and shipped a string reading "EPC A" under BREEAM. Moving a value OUT
    # of `epc` is only safe when it carries no rating of its own, so the token search is the
    # right test here too. The branch above keeps `_EPC_BAND`: it moves a value INTO `epc`,
    # where only a clean band belongs, never a composite sentence.
    if isinstance(e, str) and not _cert_unknown(e) \
            and _BREEAM_GRADE.search(e) and not _EPC_GATE_RX.search(e):
        _move("epc", "breeam", e.strip(), "a BREEAM grade is not an EPC band")
    return rec


# ---------------------------------------------------------------------------- #
# DURABLE MANUAL CORRECTIONS (P1-4)
#
# THE BUG. The only sanctioned remedy for a flagged datum was "edit the records in work/extract/".
# Those files are DERIVED: anything that invalidates extraction regenerates them and silently
# discards the correction. Live symptom - a corrected tracker cell reverted TWICE, two properties
# stopped clustering, the property count went 12 -> 13 with no message at all, and the only visible
# effect was a coverage gate failing on a thin record several steps later.
#
# Overrides live OUTSIDE the derived artefacts (work/overrides.json) and are re-applied on EVERY
# run, so a correction survives re-extraction by construction.
#
# WHAT THIS DOES NOT DO. It never judges whether a correction is right, never invents one, and
# never guesses a target: zero matches or an ambiguous match applies NOTHING and reports. Python
# verifies the target exists (0 / 1 / N) and prepares the evidence; the human authors the value and
# the required `why`.
_OV_ROW_RX = re.compile(r"^\s*(?P<sheet>.+?)!r(?P<row>\d+)")

# An override may never inject structure, media or an identity. These are NOT ordinary fields.
_OV_FORBIDDEN = frozenset({"id", "__meta", "hero", "gallery", "plan", "preBaked", "photo",
                           "districtProfile", "regionCode"})
# areaUnit / rentUnit are DENIED outright (owner decision). A unit flip is the 10.76x error class:
# it is applied BEFORE dominant_units, so correcting the one record that tips the vote silently
# relabels EVERY figure in the dataset, and nothing downstream catches it - the area magnitude
# cross-check is blind across the whole realistic warehouse range.
_OV_DENIED_UNITS = frozenset({"areaUnit", "rentUnit"})


def load_overrides(path, extra_fields=()) -> tuple[list[dict], list[str]]:
    """Parse + validate work/overrides.json. Returns (entries, invalid_reasons). NEVER raises.

    Refuses at LOAD time anything that could produce an incomplete ledger row - an empty `why`,
    an empty `where.source_file`, an empty/blank `set` value - because `ledger.REQUIRED` includes
    source_locator and source_type, and an empty required column hard-blocks the build at exit 6.
    That is exactly the trap the translation bake fell into on a live run.

    `extra_fields` (B7) widens "an existing field" to include field names actually PRESENT ON THE
    RECORDS, not just those the schema/template declare. Callers pass the loaded records' key set.

    WHY. `_normalise_offspec` deliberately KEEPS a brand-new scalar attribute from an interpretation
    record (v22 Phase 1 auto-show), so an isolated LLM could introduce a field that this audited,
    `verified_by`-attributed, ledger-recorded human path was forbidden to use - the exact inversion
    of where latitude belongs. Live symptom: an override setting `epc` was refused while the property
    beside it displayed an `epc` an LLM had introduced.

    The protection that matters is UNCHANGED: a typo (`breeem`) is on no record and in no schema, so
    it still matches nothing and is still refused. Only a field the dataset genuinely has becomes
    reachable. Default `()` keeps every existing caller's behaviour byte-identical."""
    p = str(path or "").strip()
    if not p:
        return [], []
    f = Path(p)
    if not f.exists():
        return [], []
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return [], [f"{f.name} is not valid JSON ({type(e).__name__}) - NO override was applied"]
    if not isinstance(raw, list):
        return [], [f"{f.name} must be a JSON LIST of override entries - NO override was applied"]
    # B7: "an existing field" = what the schema/template declare, UNION what the records actually
    # carry. A typo is in neither, so it is still refused.
    declared = C.canonical_property_fields()
    on_records = {str(k) for k in (extra_fields or ()) if str(k) and k != "__meta"}
    canon = declared | on_records
    out: list[dict] = []
    bad: list[str] = []
    seen_ids: set = set()
    for n, e in enumerate(raw, start=1):
        tag = f"entry #{n}"
        if not isinstance(e, dict):
            bad.append(f"{tag} is not an object")
            continue
        oid = str(e.get("id") or "").strip()
        tag = f"override {oid}" if oid else tag
        if not oid:
            bad.append(f"{tag}: missing a non-empty \"id\"")
            continue
        if oid in seen_ids:
            bad.append(f"{tag}: duplicate id - ids must be unique")
            continue
        where = e.get("where")
        if not isinstance(where, dict) or not str(where.get("source_file") or "").strip():
            bad.append(f"{tag}: \"where.source_file\" is required and must be non-empty")
            continue
        unknown = [k for k in where if k not in ("source_file", "sheet", "row", "page_no")]
        if unknown:
            bad.append(f"{tag}: unrecognised \"where\" key(s) {unknown} - refused rather than "
                       f"matched partially (a typo must never widen the match)")
            continue
        sets = e.get("set")
        if not isinstance(sets, dict) or not sets:
            bad.append(f"{tag}: \"set\" is required and must name at least one field")
            continue
        if not str(e.get("why") or "").strip():
            bad.append(f"{tag}: a non-empty \"why\" is required - it ships in the Source Ledger "
                       f"and the Gaps Report")
            continue
        # A18b CITING THE EVIDENCE. `source_file` / `source_locator` are OPTIONAL TOP-LEVEL keys
        # (not inside `where`, whose allowlist above deliberately refuses anything it does not
        # know) that replace the ledger columns of the same name. The ledger row used to stamp
        # `where.source_file`, which is the TARGETING clause: the file+row this entry MATCHES ON.
        # That is not a citation. A figure read off a brochure page and corrected through the
        # tracker row that carries it was therefore attributed to the tracker, so provenance said
        # a correction happened but not where the value came from - the reviewer's next question,
        # and the one the Source Ledger exists to answer. `why` stays REQUIRED: a citation says
        # where the value is, never why the old one was wrong.
        #
        # Same two key names and the same semantics as the repair channel (`repairs.py`), so one
        # habit works on both. Present, they win; absent, today's row is byte-identical.
        cite_bad = sorted(k for k in ("source_file", "source_locator")
                          if k in e and not (isinstance(e[k], str) and e[k].strip()))
        if cite_bad:
            bad.append(f"{tag}: {', '.join(cite_bad)} is optional, but when present it must be "
                       f"a non-empty string - it replaces a Source Ledger column, and an empty "
                       f"ledger cell hard-blocks the build")
            continue
        clean: dict = {}
        for fld, val in sets.items():
            if fld in _OV_DENIED_UNITS:
                bad.append(f"{tag}: setting {fld!r} is DENIED - it is applied before the dataset "
                           f"unit vote, so it can silently relabel every figure (the 10.76x "
                           f"class). Correct the AREA/RENT figures themselves instead.")
                continue
            if fld in _OV_FORBIDDEN:
                bad.append(f"{tag}: {fld!r} is structural/derived and can never be overridden")
                continue
            if fld not in canon:
                # Say WHAT was checked, so a broker can tell a typo from a field this corpus
                # genuinely does not have. The old wording named only "canonical", which was
                # misleading once a field could exist on a record without being declared.
                bad.append(f"{tag}: {fld!r} is not a property field of this dataset - it is "
                           f"declared in no schema and present on no record, so an override "
                           f"would be INVENTING it. An override may only correct a field that "
                           f"already exists. Check the spelling against the Source Ledger's "
                           f"`field` column.")
                continue
            if isinstance(val, (dict, list)):
                bad.append(f"{tag}: {fld!r} must be a scalar, not {type(val).__name__}")
                continue
            if val is None or not str(val).strip():
                bad.append(f"{tag}: {fld!r} is empty - write the literal \"tbd\" if the correction "
                           f"is that the value is unknown")
                continue
            clean[fld] = val
        if not clean:
            continue                      # every field was refused; reasons already recorded
        seen_ids.add(oid)
        exp = e.get("expect") if isinstance(e.get("expect"), dict) else {}
        out.append({"id": oid, "where": dict(where), "set": clean, "expect": exp,
                    "why": str(e["why"]).strip(),
                    "verified_by": str(e.get("verified_by") or "").strip(),
                    # A18b: always present (possibly ""), exactly like `verified_by` above - the
                    # applier decides whether an EMPTY citation is worth carrying into the report.
                    "source_file": str(e.get("source_file") or "").strip(),
                    "source_locator": str(e.get("source_locator") or "").strip(),
                    "multi": "all" if str(e.get("multi") or "").lower() == "all" else "one"})
    return out, bad


def _ov_absent_like(v) -> bool:
    """Absence as the override `expect` guard reads it: repairs' rule, so the twins agree. (SEAM-13)

    The two human correction channels (overrides.json pre-merge, repairs.json post-merge) carried
    two private copies of one literal for this guard, and the plan's own lesson is that two
    copies of one value drift. There is now ONE implementation, `repairs._absent_like`, and this
    is a call to it, not a re-statement. What that rule says, so a reader of this file need not
    open the other: the shared family `normalize.UNKNOWN_FORMS` is the master; a placeholder
    TOKEN in it (empty, pure punctuation, or an abbreviation of at most three letters: tbd, tbc,
    tba, tbs, ??, n/a, poa, the dash) is absence; a market PHRASE ("a consultar", "auf anfrage")
    is a broker's stated words and still trips the guard, which expect_sentinel_test pins; the
    bare alpha-2 codes normalize exempts for code fields (na, nc, sc) are not absence either.

    A stated "none"/"None" is DATA (contract C5). Two `expect` outcomes MOVE here as a result,
    both deliberate and both mirrored in repairs: `expect: tbd` against a record holding "none"
    now SUPERSEDES (the card shows "none"), and `expect: none` against a struck field (None) now
    supersedes (the card shows the blank sentinel). Two WIDEN: `expect: TBA` and `expect: ??` against a struck
    field now match. Imported inside the function so merge's import graph does not change."""
    import repairs as _RP
    return _RP._absent_like(v)


def _ov_expect_same(cur, want) -> bool:
    """`expect` equality where BOTH SIDES ABSENT is a match (the twin of repairs._expect_same).

    A field an extractor left unset holds None, while the ledger, the Gaps Report and the card
    all render it as an unknown (the card's word for that is normalize.BLANK since v45; the
    ledger and the report still say 'tbd'). Comparing str(None) to a sentinel spelling made the
    documented `expect` form refuse every such entry as SUPERSEDED, so the guard fired on its
    own correct premise.
    """
    if isinstance(cur, (int, float)) and not isinstance(cur, bool):
        try:
            return float(cur) == float(str(want).strip())
        except (TypeError, ValueError):
            pass
    if str(cur) == str(want):
        return True
    return _ov_absent_like(cur) and _ov_absent_like(want)


def _ov_record_matches(rec: dict, where: dict) -> bool:
    """Every key PRESENT in `where` must match (AND); absent keys are not constraints.

    The LIST INDEX is deliberately NOT a predicate: re-extraction can drop, add or reorder
    records, and an index-keyed override would then silently correct the WRONG property - which is
    the very failure class this fix exists to prevent. Row identity comes from __meta.prov values,
    which carry "<Sheet>!r<N>" verbatim (1-based SPREADSHEET rows, as a human reads them in Excel).
    """
    m = rec.get("__meta") or {}
    want_file = str(where.get("source_file") or "").strip().lower()
    # basename + case-insensitive: a work-dir path vs a bare filename must not decide whether a
    # correction applies
    if Path(str(m.get("source_file") or "")).name.strip().lower() != Path(want_file).name:
        return False
    if where.get("page_no") is not None:
        if m.get("page_no") != where.get("page_no"):
            return False
    if where.get("row") is not None:
        want_row, want_sheet = int(where["row"]), str(where.get("sheet") or "").strip()
        hit = False
        for loc in (m.get("prov") or {}).values():
            mm = _OV_ROW_RX.match(str(loc))
            if not mm or int(mm.group("row")) != want_row:
                continue
            if want_sheet and mm.group("sheet").strip() != want_sheet:
                continue
            hit = True
            break
        if not hit:
            return False
    elif where.get("sheet"):
        if str(m.get("locator_base") or "").strip() != str(where["sheet"]).strip():
            return False
    return True


def apply_overrides(all_records: list[dict], overrides: list[dict]) -> dict:
    """Apply each override to the PRE-MERGE records. Returns a report; mutates matched records.

    NEVER creates a record. There is no append/insert/extend on `all_records` anywhere in this
    function - zero matches is a report entry, not a synthesised property.
    """
    report: dict = {"applied": [], "stale": [], "ambiguous": [], "superseded": [], "invalid": []}
    for ov in overrides:
        hits = [r for r in all_records if _ov_record_matches(r, ov["where"])]
        w = ov["where"]
        at = (f"{w.get('sheet') or ''}!r{w['row']}" if w.get("row") is not None
              else (f"page_no {w['page_no']}" if w.get("page_no") is not None else "the whole file"))
        if not hits:
            report["stale"].append({
                "id": ov["id"], "where": w, "set": ov["set"], "why": ov["why"],
                "reason": (f"matched NOTHING: no record from '{w['source_file']}' at {at}. The "
                           f"correction was NOT applied. Fix `where` or delete the entry from "
                           f"work/overrides.json.")})
            continue
        if len(hits) > 1 and ov["multi"] != "all":
            report["ambiguous"].append({
                "id": ov["id"], "where": w, "set": ov["set"], "why": ov["why"],
                "reason": (f"matched {len(hits)} records from '{w['source_file']}' at {at} - "
                           f"applied NOTHING (fails closed). Narrow `where` with a sheet+row or "
                           f"page_no, or set \"multi\": \"all\" if every match really should "
                           f"change.")})
            continue
        for rec in hits:
            old: dict = {}
            stale_field = False
            for fld, new in ov["set"].items():
                cur = rec.get(fld)
                if fld in ov["expect"] and not _ov_expect_same(cur, ov["expect"][fld]):
                    report["superseded"].append({
                        "id": ov["id"], "where": w, "set": {fld: new}, "why": ov["why"],
                        "reason": (f"`expect` said {fld} == {ov['expect'][fld]!r} but the record "
                                   f"now holds {cur!r} - applied NOTHING for that field. A row was "
                                   f"probably inserted upstream, so this entry may now point at a "
                                   f"DIFFERENT property. Re-check it against the source.")})
                    stale_field = True
                    continue
                old[fld] = cur
                rec[fld] = N.clean_value(new) if isinstance(new, str) else new
                m = rec.setdefault("__meta", {})
                base = str((m.get("prov") or {}).get(fld) or m.get("locator_base") or "")
                m.setdefault("prov", {})[fld] = (
                    f"{base} (manual override {ov['id']}: {ov['why']})".strip())
                # pin it through precedence, and stamp the record so the ledger emitter can find
                # it after clustering. Stamped on the RECORD (not keyed on id()) so it survives
                # any copy a future refactor introduces.
                lock = set(m.get("override_locked") or ())
                lock.add(fld)
                m["override_locked"] = sorted(lock)
                ids = list(m.get("override_ids") or [])
                if ov["id"] not in ids:
                    ids.append(ov["id"])
                m["override_ids"] = ids
            if not old:
                continue
            # re-quarantine: the value went through the same render boundary as any extracted one
            _normalise_offspec(rec)
            _applied = {
                "id": ov["id"], "where": w, "set": {k: ov["set"][k] for k in old},
                "old": old, "why": ov["why"], "verified_by": ov["verified_by"],
                "locator": at, "partial": stale_field}
            # A18b: the citation rides the APPLIED entry, because the ledger emitter runs after
            # clustering and reads this report, not the entry file. CONDITIONAL, like every other
            # optional key in this module: an entry that cites nothing produces the same
            # overrides_report.json and the same canonical.meta.overrides bytes as today.
            # `.get`, not `[...]`: apply_overrides is called directly with hand-built entries by
            # the eval battery, and a citation it never mentions must not be a KeyError.
            for _ck in ("source_file", "source_locator"):
                if str(ov.get(_ck) or "").strip():
                    _applied[_ck] = str(ov[_ck]).strip()
            report["applied"].append(_applied)
    return report


def _report_overrides(report: dict, out_path: Path) -> None:
    """Print every non-applied outcome UNCONDITIONALLY and persist the report for run.py.

    merge has no --quiet of its own, but run.py's call() swallows child stdout under --quiet - so
    the file is what lets run.py re-surface these lines to the orchestrator.
    """
    for a in report.get("applied", []):
        print(f"[OVERRIDE] {a['id']} applied to {a['where']['source_file']} {a['locator']}: "
              + ", ".join(f"{k}: {a['old'].get(k)!r} -> {v!r}" for k, v in a["set"].items()))
    for key, tag in (("stale", "STALE OVERRIDE"), ("ambiguous", "AMBIGUOUS OVERRIDE"),
                     ("superseded", "SUPERSEDED OVERRIDE")):
        for s in report.get(key, []):
            print(f"[{tag}] {s['id']} {s['reason']}")
    for iv in report.get("invalid", []):
        print(f"[INVALID OVERRIDE] {iv} - this entry does NOTHING until it is fixed.")
    try:
        if any(report.get(k) for k in ("applied", "stale", "ambiguous", "superseded", "invalid")):
            C.atomic_write_text(out_path, json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        pass  # the report is evidence, never a reason to fail the merge


_FILE_UNRELIABLE: dict[str, bool] = {}


def compute_file_quality(records: list[dict]) -> dict[str, bool]:
    """Mark each BROCHURE source file (pdf/pptx) whose records MOSTLY parsed
    poorly - the same probe run.py routes files to vision with. Records from
    such a file lose every field-precedence contest to a cleaner twin:
    'PDF preferred for fields' holds only while the PDF parse is actually
    reliable (a print-export PDF with a flattened text layer used to outrank
    its clean PPTX twin on the static rank alone). Non-brochure sources
    (xlsx/email) keep their ranks - their records are legitimately sparse."""
    by_file: dict[str, list] = {}
    for r in records:
        meta = r.get("__meta", {}) or {}
        if meta.get("source_type") in ("pdf", "pptx"):
            by_file.setdefault(meta.get("source_file", ""), []).append(r)
    _FILE_UNRELIABLE.clear()
    for f, recs in by_file.items():
        poor = sum(1 for r in recs if C.record_is_poor(r))
        _FILE_UNRELIABLE[f] = bool(recs) and poor / len(recs) > 0.5
    return _FILE_UNRELIABLE


def _unreliable(r) -> bool:
    return _FILE_UNRELIABLE.get((r.get("__meta", {}) or {}).get("source_file", ""), False)


def stated_total_for(cluster: list, merged: dict, area_unit: str) -> dict | None:
    """P1-1: the source's OWN stated total area for this property, aligned to the dataset unit.

    OPTIONAL by design. A record carries `__meta.statedTotalArea` only when its source PRINTS a
    total (a GIA/GEA/GLA-qualified tracker size, or a schedule whose TOTAL line the interpreter
    copied). A deck without one yields None and the arithmetic gate skips that property entirely.

    Returns None - never a guess - whenever the comparison would not be sound:
      * no record in the cluster carries a numeric stated total;
      * the unit is unknown or unrecognised, OR the record's area unit was ASSUMED rather than
        stated (merge does NOT convert in that case, so the figures are not commensurable and a
        comparison would be the 10.76x unit-flip class the skill exists to prevent).

    The conversion reuses `N.SQFT_PER_SQM` with the SAME factor expression as the per-record area
    alignment below, so the stated total can never be scaled differently from the fields it is
    compared against.
    """
    best = None
    for r in cluster:
        m = r.get("__meta", {}) or {}
        v = m.get("statedTotalArea")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
            continue
        unit = str(m.get("statedTotalUnit") or r.get("areaUnit") or "").strip()
        if unit not in ("sq ft", "sq m"):
            continue          # unknown unit -> not comparable, and we do NOT infer one
        best = {"value": float(v), "unit": unit,
                "source_file": m.get("source_file", ""),
                "locator": m.get("statedTotalLocator") or m.get("locator_base", "")}
        break
    if best is None:
        return None
    if merged.get("areaUnitAssumed"):
        # the record never stated its unit, so its areas were labelled but NOT converted
        return None
    if best["unit"] != area_unit:
        f = N.SQFT_PER_SQM if area_unit == "sq ft" else 1.0 / N.SQFT_PER_SQM
        best["value"] = round(best["value"] * f)
        best["locator"] = f"{best['locator']} (converted {best['unit']} -> {area_unit})".strip()
        best["unit"] = area_unit
    # the fields the chrome's glaVal() actually sums - quoted, not re-derived
    best["contributors"] = ["warehouseArea", "officeAreaVal"]
    return best


# ---------------------------------------------------------------------------- #
# F11: an OFFICE TOTAL the source never printed, computed from the components it did.
#
# Measured on a live run: 3 of 7 decks itemise office space across several schedule lines
# (ground floor, first floor, hub office, pod office) and print NO single office total. Every
# reader correctly refused to add them, citing the contract's own rule that Python owns all
# arithmetic; each shipped every line under its own key so nothing was lost, and raised a doubt.
# No Python step then did the sum they deferred, so `officeArea` shipped `tbd`, the modal's Total
# GLA silently excluded the office, and four of the run's twelve broker questions were this one
# missing addition. This is that step.
#
# WHAT COUNTS AS A COMPONENT is derived from the record, not from a list of names: the reader
# named the lines it found, so the rule reads the NAMES. A key is an office component when
#   * its camelCase tokens carry "office"/"offices" but are not the total's own family (a stem of
#     bare "office" after unit/area markers are removed is `officeArea`, `officeAreaSqm`,
#     `officeAreaUnit`... the TOTAL and its twins, never a component);
#   * its value parses as a single positive area (`_area_text_value`: no range, no unknown) and
#     is not a rent, a percentage or a count: a currency sign, a "per"/"/" basis or "%" excludes
#     it, and so does any token naming a non-area quantity (rent, rate, height, parking, epc...);
#   * its unit is knowable: printed in the value, carried in the key (`...Sqm`), or stated at
#     record level (`areaUnit`). A component whose unit cannot be known is never summed.
# A gatehouse is NOT an office. On the live corpus the broker's answers were "stated total minus
# warehouse", which folds the gatehouse in; f26 records that inflating an office figure to make a
# total agree was refused once already, and the Total GLA reconciliation is the stated total's
# job (F26), not this field's. The gatehouse is where the reconciliation below expects it.
#
# WHAT STOPS IT INFLATING A FIGURE, each a refusal that leaves `officeArea` an honest gap:
#   * a stated total anywhere in the office family wins outright (in any unit);
#   * fewer than two components is not a sum, it is a guess about which line is "the office";
#   * a stem that is a token-prefix of another stem (a "hubOffice" beside "hubOfficeGroundFloor")
#     is a subtotal sitting next to its own parts, so the set is AMBIGUOUS and nothing is summed;
#   * a stem stated in two units (`hubOffice` in sq ft and `hubOfficeAreaSqm`) is ONE line, and
#     only its reading in the target unit counts;
#   * a sum at or above the warehouse figure is the unit-flip error class and is refused.
# The sum is provenance-noted as a COMPUTED SUM naming every component and its printed value,
# the way the dominant-unit conversion notes itself, and it is RECONCILED where the source
# printed a total: warehouse + office sum against the deck's own figure, with any residual
# explained by the other stated non-warehouse lines (the gatehouse) or, failing that, DISCLOSED
# as a doubt. On the live corpus the residual was exactly the gatehouse on every itemised deck.
_OFFICE_UNIT_MARKERS = frozenset({"area", "areas", "sq", "sqm", "sqft", "m", "m2", "ft", "ft2",
                                  "val", "unit", "gia", "gla", "nia", "space", "accommodation"})
# tokens that name a quantity which is not an area, even when the key says "office"
_OFFICE_NON_AREA = frozenset({"rent", "rental", "rate", "price", "cost", "charge", "fee", "psf",
                              "epc", "breeam", "rating", "desc", "description", "count", "number",
                              "floors", "storeys", "storey", "height", "parking", "spaces",
                              "percent", "percentage", "ratio", "fitout", "spec", "specification",
                              "occupier", "tenant", "use"})
_RENT_SHAPE_RX = re.compile(r"[£€$]|/|\b(?:per|pa|p\.a\.|pax|eur|gbp|usd|chf|pln|czk)\b", re.I)
_CAMEL_RX = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _key_tokens(key: str) -> list[str]:
    return [t.lower() for t in _CAMEL_RX.findall(str(key or ""))]


def _key_unit(tokens: list[str]) -> str | None:
    """The area unit a KEY NAME carries ('officeAreaSqm' -> 'sq m'), or None."""
    joined = " ".join(tokens)
    if "sqm" in tokens or "m2" in tokens or " sq m" in f" {joined}":
        return "sq m"
    if "sqft" in tokens or "ft2" in tokens or " sq ft" in f" {joined}":
        return "sq ft"
    return None


def _is_office_total_key(tokens: list[str]) -> bool:
    stem = [t for t in tokens if t not in _OFFICE_UNIT_MARKERS]
    return stem in (["office"], ["offices"])


def _area_candidate(key: str, value, record_unit: str | None):
    """(magnitude, unit or None, tokens) when `value` is a single stated AREA, else None."""
    if isinstance(value, bool) or isinstance(value, (dict, list)) or value is None:
        return None
    tokens = _key_tokens(key)
    if any(t in _OFFICE_NON_AREA for t in tokens):
        return None
    if isinstance(value, (int, float)):
        if value <= 0 or not any(t in _OFFICE_UNIT_MARKERS for t in tokens):
            return None          # a bare number under a key that never says "area": not an area
        return (float(value), _key_unit(tokens) or record_unit, tokens)
    text = str(value)
    if "%" in text or _RENT_SHAPE_RX.search(text):
        return None
    parsed = _area_text_value(text)
    if parsed is None:
        return None
    mag, text_unit = parsed
    if text_unit is None and not any(t in _OFFICE_UNIT_MARKERS for t in tokens):
        return None          # no unit in the value and no area marker in the key: not an area
    return (mag, text_unit or _key_unit(tokens) or record_unit, tokens)


def _record_area_unit(merged: dict) -> str | None:
    u = merged.get("areaUnit")
    if isinstance(u, str) and u.strip():
        return N.area_unit_of(u) or (u.strip().lower() if u.strip().lower() in ("sq ft", "sq m") else None)
    return None


def derive_office_sum(cluster: list, merged: dict, prov: dict) -> dict | None:
    """Fill `officeArea` from the office components the source itemised, when it printed no total.

    Runs on the MERGED record, before `canonicalize` (which derives `officeAreaVal` from it) and
    before the dominant-unit alignment (which converts `officeAreaVal` on its provenance's own
    `areaUnitOfSource`, set here). Returns the audit entry it wrote, or None when nothing was
    summed; `entry["status"]` is "computed" or "refused" with a `why`, so the caller can disclose
    a refusal that is a genuine ambiguity. Never overwrites a stated value. See the block comment
    above for the component rule and every refusal."""
    if not isinstance(merged, dict):
        return None
    cur = merged.get("officeArea")
    if cur is not None and not N.looks_unknown(cur):
        return None                       # a stated total wins, always
    if isinstance(merged.get("officeAreaVal"), (int, float)) and not isinstance(merged.get("officeAreaVal"), bool):
        return None
    record_unit = _record_area_unit(merged)
    stems: dict = {}                      # stem -> [(key, magnitude, unit)]
    for k, v in merged.items():
        if k == "__meta":
            continue
        toks = _key_tokens(k)
        if not any(t in ("office", "offices") for t in toks):
            continue
        if _is_office_total_key(toks):
            if _area_candidate(k, v, record_unit) is not None:
                return None               # a total stated under another spelling or unit wins too
            continue
        cand = _area_candidate(k, v, record_unit)
        if cand is None:
            continue
        mag, unit, toks = cand
        stem = tuple(t for t in toks if t not in _OFFICE_UNIT_MARKERS)
        stems.setdefault(stem, []).append((k, mag, unit))
    if not stems:
        return None
    names = sorted(k for lines in stems.values() for k, _, _ in lines)
    if len(stems) < 2:
        return {"status": "refused", "why": "one office line is not a sum", "components": names}
    for a in stems:
        for b in stems:
            if a != b and len(a) < len(b) and b[:len(a)] == a:
                return {"status": "refused",
                        "why": (f"'{stems[a][0][0]}' reads as a subtotal of "
                                f"'{stems[b][0][0]}' (one key's name is a prefix of the other's), "
                                f"so the itemised lines may overlap; not summed"),
                        "components": names}
    # the target unit: the record's own, else the unit most of the lines state
    from collections import Counter
    known = Counter(u for lines in stems.values() for _, _, u in lines if u)
    target = record_unit or (known.most_common(1)[0][0] if known else None)
    if target not in ("sq ft", "sq m"):
        return {"status": "refused", "why": "no knowable unit for the itemised office lines",
                "components": names}
    parts: list = []                      # (key, magnitude in target, printed value, note)
    for stem, lines in stems.items():
        same = [ln for ln in lines if ln[2] == target]
        if same:
            k, mag, _ = same[0]
            parts.append((k, mag, merged.get(k), ""))
            continue
        other = [ln for ln in lines if ln[2]]
        if not other:
            return {"status": "refused", "why": f"'{lines[0][0]}' states no unit; not summed",
                    "components": names}
        k, mag, u = other[0]
        f = N.area_factor(u, target)
        if f is None:
            return {"status": "refused",
                    "why": f"'{k}' is in a unit ({u}) this dataset cannot express",
                    "components": names}
        parts.append((k, round(mag * f), merged.get(k), f" converted at {f:g} {target} per {u}"))
    total = sum(p[1] for p in parts)
    if total <= 0:
        return None
    wh = merged.get("warehouseArea")
    wh_mag = None
    if isinstance(wh, (int, float)) and not isinstance(wh, bool):
        wh_mag = float(wh)
    elif isinstance(wh, str):
        _p = _area_text_value(wh)
        wh_mag = _p[0] if _p and (_p[1] in (None, target)) else None
    if wh_mag is not None and total >= wh_mag:
        return {"status": "refused",
                "why": (f"the office lines sum to {total:,.0f} {target}, at or above the "
                        f"{wh_mag:,.0f} warehouse figure: a unit mismatch, not an office"),
                "components": [p[0] for p in parts]}
    listing = " + ".join(f"{k} ({v}{note})" for k, _, v, note in parts)
    files = sorted({(prov.get(k) or {}).get("source_file", "") for k, _, _, _ in parts} - {""})
    first = prov.get(parts[0][0]) or {}
    value = int(total) if float(total).is_integer() else round(total, 2)
    merged["officeArea"] = value
    prov["officeArea"] = {
        "source_file": files[0] if len(files) == 1 else (first.get("source_file", "") or ""),
        "source_type": first.get("source_type", ""),
        "locator": (f"COMPUTED SUM of {len(parts)} stated office lines: {listing} = "
                    f"{value:,} {target}; the source printed no single office total"
                    + (f"; lines read from {', '.join(files)}" if len(files) > 1 else "")),
        "areaUnitOfSource": target,
    }
    entry = {"status": "computed", "value": value, "unit": target,
             "components": [{"key": k, "value": v} for k, _, v, _ in parts]}
    # RECONCILE against the deck's own printed total, when it printed one. Not a gate: a note
    # in the audit entry, and a doubt on the conflicts channel only when the residual is not
    # accounted for by lines the source itself states.
    stated = None
    for r in cluster or []:
        m = (r.get("__meta") or {}) if isinstance(r, dict) else {}
        sv = m.get("statedTotalArea")
        if isinstance(sv, bool) or not isinstance(sv, (int, float)) or not sv > 0:
            continue
        su = str(m.get("statedTotalUnit") or r.get("areaUnit") or "").strip()
        su = N.area_unit_of(su) or (su.lower() if su.lower() in ("sq ft", "sq m") else None)
        if su is None:
            continue
        stated = float(sv) if su == target else round(float(sv) * N.area_factor(su, target))
        break
    if stated is not None and wh_mag is not None:
        residual = round(stated - wh_mag - total)
        entry["statedTotal"] = stated
        entry["residual"] = residual
        if abs(residual) < 1:
            entry["reconciles"] = "warehouse + office sum equals the stated total exactly"
        else:
            summed = {p[0] for p in parts} | {"officeArea", "officeAreaVal", "warehouseArea", "plotArea"}
            others: list = []
            for k, v in merged.items():
                if k in summed or k == "__meta" or _is_office_total_key(_key_tokens(k)):
                    continue
                c = _area_candidate(k, v, record_unit)
                if c and c[1] == target and 0 < c[0] < stated:
                    others.append((k, round(c[0])))
            hit = _subset_summing_to(others[:12], residual)
            if hit is not None:
                entry["reconciles"] = (f"warehouse + office sum + {' + '.join(hit)} equals the "
                                       f"stated total exactly")
            else:
                entry["reconciles"] = (f"does NOT reconcile: stated total {stated:,.0f} minus "
                                       f"warehouse {wh_mag:,.0f} minus the office sum "
                                       f"{total:,.0f} leaves {residual:,} {target} unexplained")
    return entry


def _subset_summing_to(items: list, want: int) -> list | None:
    """The FIRST subset of `items` ([(name, int)]) whose values sum to `want`, by name; None
    when no subset does. Bounded by the caller (at most 12 items -> 4,096 subsets)."""
    if want <= 0:
        return None
    n = len(items)
    for mask in range(1, 1 << n):
        chosen = [items[j] for j in range(n) if mask >> j & 1]
        if sum(v for _, v in chosen) == want:
            return [k for k, _ in chosen]
    return None


_INTERNAL_FLAGS = ("areaUnitAssumed", "rentUnitAssumed")


def strip_internal_flags(merged: dict) -> dict:
    """Move merge's own working flags off the property, immediately before it ships. (B05)

    The v21 modal renders EVERY key a property carries, including names in no schema - so a
    bare `areaUnitAssumed` shipped a raw untranslated row "Area Unit Assumed: true" onto a
    broker's client card. `extract_xlsx` sets `rentUnitAssumed` on the SOURCE record, which
    merge copies up, so it leaked the same way; the tracker path is the common trigger, and
    fixing one name without the other leaves the defect live.

    These are internal state, not data: `stated_total_for` reads areaUnitAssumed earlier in
    the merge to refuse an unconverted stated total. The AUDITABLE copy is
    `canonical.meta.unitAssumptions`, which is what the Gaps Report reads - so nothing is
    lost by dropping the per-property flag. They are parked under `__meta`, which the caller
    pops on the next line.

    Any future internal flag goes in `_INTERNAL_FLAGS`, NEVER on the record top level."""
    for f in _INTERNAL_FLAGS:
        if f in merged:
            merged.setdefault("__meta", {})[f] = merged.pop(f)
    return merged


def dominant_country(records: list[dict]) -> str:
    """The ISO alpha-2 country MOST source records state ("" when none does). Names are
    normalised through `N.country_iso` first, so a manifest's "United Kingdom" and a tracker's
    "GB" count as one vote; the unknown family is skipped with the CODE reading. (D11)"""
    from collections import Counter
    c = Counter(N.country_iso(r.get("country")) for r in records
                if isinstance(r, dict) and r.get("country")
                and not N.looks_unknown_code(r.get("country")))
    return c.most_common(1)[0][0] if c else ""


def rent_unit_stated(records: list[dict]) -> bool:
    """Does ANY source record state a `rentUnit`? False is the D11 fallback condition."""
    return any(isinstance(r, dict) and r.get("rentUnit") for r in records)


def rent_unit_default(records: list[dict], area_unit: str) -> tuple[str, dict]:
    """(the rent unit this dataset FALLS BACK TO, the auditable assumption entry). (D11)

    Used only when `rent_unit_stated` is False. The unit comes from `N.default_rent_unit` on the
    dominant AREA unit and the dominant country, and the entry is shaped like the per-property
    area entries `main()` already appends to `unit_assumptions` (`field`, `assumed`, `why`,
    `property`), with `id` set to the string "dataset" because this is ONE assumption about the
    whole longlist's display basis, not about a property's figure. deliver.py reads the same list
    for the workbook's assumed-unit column by property id, so a non-integer id can never relabel
    a row there, and `gaps_report` prints this entry under its own heading."""
    cc = dominant_country(records)
    unit = N.default_rent_unit(area_unit, cc)
    entry = {
        "id": "dataset",
        "property": "(whole longlist)",
        "field": "rentUnit",
        "assumed": unit,
        "why": (f"no source states a rent unit; the rent basis shown on the hero KPI and the "
                f"card footers was derived from the dominant area unit ({area_unit}) and the "
                f"dominant country ({cc or 'not stated'}). It is a display convention, not a "
                f"quoted figure: no rent number was relabelled with it"),
    }
    return unit, entry


def dominant_units(records: list[dict]) -> tuple[str, str]:
    """The dataset's unit convention = the units MOST source records state
    (UK/imperial inputs ship imperial, metric inputs ship metric - user rule).

    Defaults when NO record states a unit: 'sq m' for the area, and for the rent the
    market-derived `rent_unit_default` (D11) rather than a fixed string. The rent fallback used
    to be a hardcoded "€/sq m/yr" whatever the country and whatever area unit this very function
    had just resolved, so a 100% GB / 100% sq ft corpus that quoted no rents shipped a euro per
    sq m basis on its hero KPI. Callers that need to know WHETHER the rent unit was assumed use
    `rent_unit_stated` and record the `rent_unit_default` entry; the tuple shape here is kept
    for the callers and evals that unpack it."""
    from collections import Counter
    a = Counter(r.get("areaUnit") for r in records
                if isinstance(r, dict) and r.get("areaUnit"))
    rn = Counter(r.get("rentUnit") for r in records
                 if isinstance(r, dict) and r.get("rentUnit"))
    area_unit = a.most_common(1)[0][0] if a else "sq m"
    rent_unit = rn.most_common(1)[0][0] if rn else rent_unit_default(records, area_unit)[0]
    return (area_unit, rent_unit)


# structured spec fields a RICH building tracker (>=8 mapped columns,
# __meta.tracker_rich) is more authoritative on than a marketing brochure:
# curated internal data beats brochure prose for measured values. Naming and
# narrative (park, city, developer, description) stay brochure-first.
TRACKER_AUTHORITATIVE = {
    "warehouseArea", "plotArea", "officeArea", "clearHeight", "floorLoad",
    "loadingDocks", "overheadDoors", "electricity", "truckParking", "carParking",
    "breeam", "lat", "lng", "status", "earlyAccess", "areaUnit",
}


def _is_rich(r) -> bool:
    return bool(r.get("__meta", {}).get("tracker_rich"))


# ----- cross-source VALUE-conflict adjudication (#4) ----------------------- #
# A genuine conflict is a field where >= 2 cluster records hold DIFFERENT
# non-unknown values. The fixed precedence above is the DEFAULT winner; an
# isolated sub-agent may OVERRIDE it with one of the given candidate values, but
# ONLY when the picked value passes the field's deterministic plausibility gate.
# The decision is cached (work/field_decisions.json) keyed by a stable,
# order-independent conflict_id, so merge reads it offline and never calls an LLM
# live (byte-identical resume). Mirrors the match grey-pair / pair_id contract.

# fields whose override is gate-VERIFIED before it is honoured. A field absent
# from this map falls back to precedence on any pick (it can still be annotated).
_RENT_GATE_FIELDS = {"warehouseRent", "warehouseRentVal", "officeRent"}
_AREA_GATE_FIELDS = {"warehouseArea", "plotArea", "officeArea", "officeAreaVal"}


# I10. Two sources stating the SAME fact in different notation is not a disagreement. Both conflict
# sites used to compare with raw string identity, so "12.5 m" vs "12.5" and "1000 KVA" vs "1 MVA" were
# reported as source conflicts - ~24 of 34 on one live run. Each cost an LLM adjudication AND diluted
# the Gaps Report's "Source conflicts" section, which is the one list a broker acts on: padding it
# with notation trains them to skim past the material entries beside it. Equivalence here must be
# PROVEN; anything unrecognised stays a conflict, because a false "same" would SWALLOW a real
# disagreement, which is a Data Honesty Standard failure of the same class as a fabricated value.
_UNIT_FAMILY = {
    "kva": ("power", 1.0), "kv a": ("power", 1.0), "mva": ("power", 1000.0),
    "sq ft": ("area", 1.0), "sqft": ("area", 1.0), "sf": ("area", 1.0),
    "sq m": ("area", 10.7639104), "sqm": ("area", 10.7639104),
    "m2": ("area", 10.7639104), "m²": ("area", 10.7639104),
    "m": ("len", 1.0), "metre": ("len", 1.0), "metres": ("len", 1.0),
    "meter": ("len", 1.0), "meters": ("len", 1.0),
    "kn/sq m": ("load", 1.0), "kn/m2": ("load", 1.0), "kn/m²": ("load", 1.0),
    "kn": ("load", 1.0), "kn/sqm": ("load", 1.0),
}
_NUM_UNIT_RX = re.compile(r"^\s*([-+]?[\d,]*\.?\d+)\s*(.*?)\s*$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
_ENUM_EQ_FIELDS = {"status", "breeam", "epc"}
_ENUM_STRIP_RX = re.compile(
    r"\bfor\s+immediate\s+occupation\b|\bupon\s+completion\b"
    r"|\b(?:target(?:ing|ed)?|breeam|epc|now|immediately)\b", re.I)


def _num_unit(v):
    """(scaled_number, family, scale) or None. A bare number yields family None - a wildcard that
    matches any family, so "12.5 m" == 12.5. An UNRECOGNISED unit suffix returns None, because an
    unknown unit is not proof of anything."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return (float(v), None, 1.0)
    m = _NUM_UNIT_RX.match(str(v))
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    tail = re.sub(r"[\s.]+$", "", m.group(2)).strip().lower()
    if not tail:
        return (num, None, 1.0)
    fam = _UNIT_FAMILY.get(tail)
    if fam is None:
        return None
    return (num * fam[1], fam[0], fam[1])


# The area fields the canonical schema types as a NUMBER and nothing else - `warehouseArea`
# is {"type": "number"} and `officeAreaVal` is {"type": ["number","null"]} - so a STRING in
# either one is a hard validate-data failure, not a formatting preference.
#
# `plotArea` is DELIBERATELY ABSENT. The schema types it ["number","string","null"] and a
# string plot area carrying its own notation ("31.629 acres (12.8 ha)") is a SUPPORTED shape
# the chrome renders verbatim - areaunit_test pins exactly that value. Coercing it would throw
# away the parenthetical the source printed in order to fix a failure it does not have.
_NUMERIC_ONLY_AREA_FIELDS = ("warehouseArea", "officeAreaVal")


def _area_text_value(v):
    """(magnitude, the unit the TEXT itself states or None) for a human-formatted area string,
    or None when the text holds no single usable number.

    Brochure-interpretation records store an area the way the page PRINTS it
    (reference/interpretation.md: "a dimensioned value keeps its unit inside the value"), so
    `warehouseArea` arrives as '436,000 sq ft' / '700,000 SQ FT' far more often than as
    436000.0. `match._area` hit the identical problem one layer up and fixed it with the same
    parser; this is that fix at the merge boundary, where the SCHEMA requires the number.

    normalize_number + area_unit_of, NOT `_num_unit`. `_num_unit` answers a different question
    ("are these two values the same fact?"), so it SCALES its result into sq ft and returns
    None for any unit outside its comparison table (acres, ha) or for a suffix carrying extra
    words ('436,000 sq ft GIA'). The caller needs the magnitude in the SOURCE's own unit plus
    that unit's canonical name - which is precisely the pair `N.area_factor` is keyed on.

    None - never a fabricated figure - on: an unknown sentinel ('tbd'), a RANGE ('25,000 -
    50,000 sq ft' honestly has no single value), a non-positive figure, and anything
    unparseable. The caller must then drop the field, not invent a number for it."""
    if v is None or isinstance(v, bool) or isinstance(v, (int, float)):
        return None
    s = str(v).strip()
    if not s or N.looks_unknown(s):
        return None
    num = N.normalize_number(s)   # the shared parser: comma/NBSP thousands, EU decimals, ranges -> None
    if num is None or num <= 0:
        return None
    return (float(num), N.area_unit_of(s))


def _as_month(v):
    """(year, month) at MONTH precision, or None - so an ISO date and 'April 2026' compare."""
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", s)
    if m and m.group(1).lower() in _MONTHS:
        return (int(m.group(2)), _MONTHS[m.group(1).lower()])
    return None


def _enum_token(v):
    return re.sub(r"[^a-z0-9]+", " ", _ENUM_STRIP_RX.sub(" ", str(v)).lower()).strip()


def _values_equivalent(field: str, a, b) -> bool:
    """Do these two values denote the SAME fact? Proof required; the default is False."""
    if a is None or b is None:
        return False
    sa, sb = str(a).strip(), str(b).strip()
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    na, nb = _num_unit(a), _num_unit(b)
    if na and nb:
        fa, fb = na[1], nb[1]
        if fa is None or fb is None or fa == fb:
            hi = max(abs(na[0]), abs(nb[0]))
            # 0.1% absorbs a source's own rounding (12,220 sq m vs 131,536 sq ft) while keeping a
            # real 0.27% area disagreement visible.
            return abs(na[0] - nb[0]) <= max(1e-9, hi * 0.001)
        return False
    ma, mb = _as_month(a), _as_month(b)
    if ma and mb:
        return ma == mb
    if field in _ENUM_EQ_FIELDS:
        ta, tb = _enum_token(a), _enum_token(b)
        if ta and tb and ta == tb:
            return True
    if field == "park":
        lo, hi = sorted((sa.lower(), sb.lower()), key=len)
        if lo and re.search(r"(?:^|\W)" + re.escape(lo) + r"(?:\W|$)", hi):
            return True
    return False


_ENUM_GATE_FIELDS = {"breeam", "epc"}
_COUNT_GATE_FIELDS = {"loadingDocks", "overheadDoors", "truckParking", "carParking"}
_FEET_RX = re.compile(r"\b(?:ft|feet|foot)\b|'", re.I)
# D15: the EPC gate matches a rating TOKEN inside the string, not the whole string.
#
# THE DEFECT. This band used to be anchored `^...$`, so it accepted a bare "A+" and "Target EPC
# A" and nothing else. A deck that states its EPC three times in plain prose ("The building will
# achieve an EPC rating of A. Targeting EPC A on completion.") failed it, and because a firing
# gate STRIKES the field, both units from that deck shipped `epc: tbd` with a note calling the
# SOURCE implausible, while the same band passed a bare "A+" on three other properties in the
# same run. It was rejecting the surrounding words, not the rating. `_pick_gate_verdict`'s own
# design note says the sibling `breeam` gate passes on CONTAINING a band word; this brings epc
# to that one convention instead of a third.
#
# WHY NOT A NAIVE SUBSTRING. A bare letter A to G is inside most English words, and a standalone
# "a" is the indefinite article ("EPC assessment shows a modern building" must FAIL: it states
# no rating). So the token is anchored on a word that identifies it as a rating - EPC, energy
# performance (certificate), rating, rated, band, target(ed/ing) - followed by at most a few
# whitelisted filler words (rating, of, is, will, be, to, achieve, certificate, minimum...), then
# an UPPER-CASE letter A-G with an optional "+", not followed by a letter or digit. The letter is
# case-sensitive on purpose ((?-i:...) inside a re.I pattern): "rating of A" is a rating,
# "rating of a modern unit" is prose. A letter FOLLOWED by "rated"/"rating" ("A+ rated") is the
# one post-anchored form. The whole-string bare band is kept as the first alternative, so every
# value that passed before passes now.
#
# D15 follow-up: a real EPC prints a SCORE AND a BAND, so the filler chain must survive a number.
# The filler chain above accepts only WORDS, so a numeric asset rating between the anchor word and
# the band broke it. Measured before this fix, every one of "EPC 85 (B)", "EPC 85 B", "EPC: 82 (B)",
# "EPC rating 85 (B)", "Energy Performance Certificate: 85 (B)" and "Energy Performance Asset
# Rating: 85 (D)" returned "fail" - and a firing gate STRIKES the field - while the same certificate
# written the other way round, "EPC B (85)" or "EPC score 85, band B", passed. The two orderings are
# the same datum off the same certificate, so this deleted a stated rating from a client card purely
# on word order. Branch (a) `[^\w.\n]+\d{1,3}[^\w.\n]{0,3}` admits that score; branch (b) is
# character-for-character the previous expression (`\W+`), which makes the new language a strict
# SUPERSET - nothing that passed before can start failing.
#
# WHY THE TWO-SIDED FULL-STOP AND NEWLINE GUARD, and why not to "simplify" branch (a). The score
# run cannot cross a "." or a newline on EITHER side. The simpler shape that only guards the
# score-to-band side, `\W+(?:\d{1,3}[^\w.\n]{0,3})?(?-i:[A-G])\+?`, was tried and REJECTED: its
# mandatory leading `\W+` still matches a full stop and a newline, so an ADDRESS stapled onto a
# heading passes as a rating - "EPC. 12 A Smith Street, Corby", "EPC\n12A Smith Street" and
# "EPC rating.\n12 A Smith Street" would all have been read as an EPC band A. All three must fail,
# and the eval pins them. `\d{1,3}` is deliberate too: EPC asset ratings run 0 to about 150 plus,
# and a fourth digit would admit a YEAR, so "EPC 2023 A" stays a fail.
#
# THIS EXPRESSION HAS A SECOND CONSUMER. `_route_certifications` (see its D15 follow-up note above)
# uses `_EPC_GATE_RX.search` to decide whether a value sitting in `epc` carries a rating of its own
# before moving it to `breeam`. Widening the gate therefore widens that routing decision as well -
# correctly, here: measured before this fix, `{"epc": "BREEAM Excellent. EPC 85 (B)."}` re-filed
# WHOLESALE, leaving epc empty and shipping a string reading "EPC 85 (B)" under BREEAM. Any future
# edit to this pattern must be judged against BOTH consumers, not the gate alone.
_EPC_GATE_RX = re.compile(
    r"^(?:target(?:ing|ed)?\s+)?(?:epc\s*)?[A-G]\+?$"
    r"|\b(?:epc|energy\s+performance(?:\s+certificate)?|rating|rated|band|target(?:ing|ed)?)\b"
    r"(?:\W+(?:epc|rating|band|grade|certificate|of|is|will|be|to|the|a|an|achieve[sd]?|"
    r"achieving|minimum|min|expected|anticipated|target(?:ing|ed)?))*"
    r"(?:[^\w.\n]+\d{1,3}[^\w.\n]{0,3}|\W+)(?-i:[A-G])\+?(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])(?-i:[A-G])\+?\s+(?:rated|rating)\b",
    re.I)


def _pick_gate_verdict(field: str, value, rent_unit: str | None = None,
                       area_unit: str | None = None) -> str:
    """Does this value pass its field's deterministic plausibility check? (B3)

    Returns "pass", "fail", or "none" - and the THREE states are the whole point. The predecessor
    returned a bool whose final line was `return False  # no defined gate -> precedence stands`, so
    "there is no gate for this field" and "this value failed its gate" were indistinguishable. Two
    consequences, both live:

      * an adjudicated override on ANY field outside rents/areas/lat-lng was discarded
        unconditionally, and the discard was narrated to the broker as a plausibility failure by a
        gate that does not exist ("failed breeam plausibility gate"). One run adjudicated 34
        conflicts across two rounds; only a rent, an area or a coordinate could ever have moved.
      * where a gate DID exist, a failing candidate caused the precedence winner to be reinstated -
        so the gate could protect the default but never catch it. An impossible BREEAM "A+" reached
        a client card that way.

    The enum/count/height gates below are deliberately conservative, because a gate that fires now
    strikes a field to the blank sentinel: `breeam` passes on CONTAINING a band word (so "Target BREEAM
    Excellent" and "Excellent (targeted)" are fine and only a non-band fails), and an eaves height
    stated in FEET returns "none" rather than being judged against a metre band.

    A RANGE is UNGATED (T1). extract_first_number deliberately returns None for "10-12 m" /
    "EUR 114-126" (a range has no single value for arithmetic), and every numeric branch below
    turns that None into "fail" - so a live run struck a printed clear height and two printed
    office-rent ranges to tbd, each with a note calling the SOURCE implausible. A stated range
    is stated data: it ships verbatim on display fields (the reader contract already routes the
    governing END of a range into the *Val fields), so a range judges as "none", never "fail"."""
    if isinstance(value, str) and field not in ("lat", "lng") and N.is_range(value):
        return "none"   # a stated range is data the band cannot judge - never strike it
    if field in _RENT_GATE_FIELDS:
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else N.extract_first_number(str(value))
        if num is None:
            return "fail"
        unit = rent_unit or (N.rent_unit_of_text(str(value)) if isinstance(value, str) else None)
        lo, hi = N.rent_unit_band(unit)
        return "pass" if lo <= num <= hi else "fail"
    if field in _AREA_GATE_FIELDS:
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else N.extract_first_number(str(value))
        if num is None or num <= 0:
            return "fail"
        # B63: judge the figure on ITS OWN FOOTING - the unit the VALUE itself prints (a
        # brochure record keeps the unit inside the value by contract, so this branch routinely
        # sees '700,000 SQ FT'), else the unit the caller supplies. Both used to be ignored:
        # with no `area_unit` passed, every area fell through to `area_band_for(None)`, the sq m
        # band, and an ordinary 700,000 sq ft shed was struck against a 600,000 SQ M ceiling
        # with a note telling the broker the source looked implausible.
        #
        # KNOWING THE UNIT MAY ONLY WIDEN THIS BAND, NEVER NARROW IT - hence the union with the
        # unit-unknown band below, and it is load-bearing, not defensive. `area_band_for` raises
        # the FLOOR as well as the ceiling (sq m 300 -> sq ft 3,000), so passing the unit
        # straight through would have struck a perfectly ordinary 1,200 sq ft `officeArea` -
        # this gate covers offices and plots, not just sheds, and 3,000 is a WAREHOUSE garble
        # floor that was never calibrated for them. A gate that fires STRIKES the field to tbd,
        # so new information about a value must never be able to make it less acceptable than
        # it was while the unit was unknown. The ceiling half is what recovers the sq ft sheds.
        _own = N.area_unit_of(value) if isinstance(value, str) else None
        lo, hi = N.area_band_for(_own or area_unit, field=field)  # plotArea: SITE ceiling (T1)
        _lo0, _hi0 = N.area_band_for(None, field=field)           # the unit-unknown band
        lo, hi = min(lo, _lo0), max(hi, _hi0)
        return "pass" if lo <= num <= hi else "fail"
    if field in ("lat", "lng"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "fail"
        ok = (-90 <= value <= 90) if field == "lat" else (-180 <= value <= 180)
        return "pass" if ok else "fail"
    if field in _ENUM_GATE_FIELDS:
        s = str(value).strip()
        if field == "breeam":
            return "pass" if _BREEAM_GRADE.search(s) else "fail"
        return "pass" if _EPC_GATE_RX.search(s) else "fail"   # D15: a token anywhere
    if field in _COUNT_GATE_FIELDS:
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else N.extract_first_number(str(value))
        if num is None or num < 0 or num > 2000 or float(num) != int(num):
            return "fail"
        return "pass"
    if field == "clearHeight":
        if _FEET_RX.search(str(value)):
            return "none"   # an imperial height must never be judged against a metre band
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else N.extract_first_number(str(value))
        return "pass" if (num is not None and 3 <= num <= 30) else "fail"
    return "none"


def _pick_passes_gate(field: str, value, rent_unit: str | None,
                      area_unit: str | None = None) -> bool:
    """Back-compatible boolean wrapper over _pick_gate_verdict (True only on an explicit "pass")."""
    return _pick_gate_verdict(field, value, rent_unit, area_unit) == "pass"


# A15: the media/prose slots whose provenance is EXPECTED to name a file outside the cluster, so
# a foreign file there is not evidence of anything. `photo`/`plan`/`gallery` are bound by the
# media harvest, which deliberately reaches park-level and otherwise-unclaimed pages of decks that
# contributed no text record, and by the photo-match path whose whole premise is a brochure
# matched to a property that has no record from it. `description` rides that same photo-match
# path: when a matched brochure supplies the hero it also supplies the deck's description prose,
# so on every photo-matched property its file is outside the cluster BY CONSTRUCTION. All four
# already have their own audit trail (media_considered, placeholderAudit) and their own gate.
_FUSION_EXEMPT_FIELDS = frozenset({"photo", "plan", "gallery", "description"})


def _fusion_disclosures(cluster: list[dict], prov: dict) -> list[tuple[str, str]]:
    """[(field, foreign file)] for every merged field whose provenance names a file that
    contributed NO record to this cluster. Sorted by field; empty for a contained property. (A15)

    THE INCIDENT. A matcher wrongly fused two separate buildings into one property. The evidence
    was in the pack the whole time - fields on one card citing a deck that describes the other
    building - and TWO independent human reviewers each found it the same way, by reading
    provenance line by line. The pack itself said nothing, because every ledger row was
    individually correct: row-by-row correctness is exactly what hides a fusion. So the
    containment claim gets stated ONCE, out loud, on the card's own conflict channel.

    FALSE POSITIVES ARE THE DESIGN PROBLEM. A disclosure that fires on every property is noise,
    gets skipped, and takes the real one down with it. Enumerated and excluded:
      * `_FUSION_EXEMPT_FIELDS` - the media and prose slots above, legitimately foreign by design.
      * a GAP/placeholder prov (source_file "(none)"): it attributes nothing, so there is no
        foreign file to name.
      * an empty source_file: nothing to name, and the ledger's own gates already cover it.
      * DERIVED companions need NO exclusion, and that is recorded here so nobody adds one: a
        derived value COPIES its basis field's prov entry, so it names the basis's file, which is
        in the cluster whenever the basis is.
      * PIPELINE-ASSIGNED fields likewise: a value merge synthesises without a source (regionCode,
        the area re-notations) gets no prov entry at all, so it is never even considered.
      * ENRICHMENT-assigned fields likewise: enrichment is a LATER stage operating on canonical,
        so nothing it assigns exists while this runs.

    Matched on BASENAME, case-insensitively - the same rule the override and repair channels apply
    to a cited file, so a work-dir path can never be what decides whether a card looks fused.

    WHAT THIS IS TODAY, said plainly: an INVARIANT. Every prov entry merge_cluster writes is taken
    from a record of the cluster it was given, so no ordinary record path can trip this, which is
    precisely why it costs nothing and cannot cry wolf. It is armed for the paths that CAN break
    containment - a matcher change, a media or repair path that starts attributing a field, a
    record whose stated source and stated provenance disagree - and it is proven against a
    synthetic prov in the eval rather than assumed."""
    own = {Path(str((r.get("__meta") or {}).get("source_file") or "")).name.lower()
           for r in (cluster or [])}
    own.discard("")
    out: list[tuple[str, str]] = []
    for field in sorted(prov or {}):
        if field in _FUSION_EXEMPT_FIELDS:
            continue
        f = Path(str((prov.get(field) or {}).get("source_file") or "")).name
        if not f or f == "(none)" or f.lower() in own:
            continue
        out.append((field, f))
    return out


def _stated_postcode(rec: dict) -> str:
    """One record's OWN stated postal code, NORMALISED FOR EQUALITY, or "" when it states
    none. (A14a)

    DELEGATED to `match._stated_postcode`, not normalised here. That reader is already this
    skill's ONE answer to "what code does this record state", and the values THIS function
    writes into `meta.clusterSources` are read back by the coverage gate's over-merge check
    and compared for disagreement against the very veto that reader implements. Producer and
    consumer of one comparison must therefore judge a code the same way, by construction.

    THE INCIDENT, because a private copy here looked harmless and was not. This function used
    to trim and upper-case and nothing else, read only `postcode`, and stringify whatever it
    found with `str()`. Measured against the veto over a 35-pair probe list, the two sides
    returned a different verdict on 9 pairs; 5 were closed when the GATE borrowed this reader,
    and the 4 that survived were all this copy: `str(48215.0)` gave '48215.0' where the reader
    gives '48215', and `str(True)` gave 'TRUE' where the reader reads a bool as ABSENCE. In
    every one of the four the gate BLOCKED a fusion the veto had deliberately allowed, and the
    block names `strike_from_source`, so following its remedy would have unfused a CORRECT
    merge. A numeric-postal-code market whose spreadsheet stores the code as a number is the
    ordinary way to hit it. The one honest fix was for the producer to delegate too, and that
    is what this is: the whitespace, case, sentinel, numeric and field-name families are now
    closed end to end.

    What the shared reader does, so a reader here does not have to go and look: whitespace
    REMOVED and the remainder upper-cased; nothing else touched, and no country-specific
    parsing, because an outward/inward split is a fact about one country and an undivided run
    of digits about several others; a sentinel read as absence through the shared
    `looks_unknown`; an integral number accepted as the code it is; a bool, a non-integral
    float and a non-finite float ignored rather than rounded into one. It reads every name in
    `match._POSTCODE_FIELDS`, which is deliberately open, so a column name added there is read
    by the veto and by this producer in the same commit instead of one going half-blind.

    Absence stays the ordinary case and is never an error: `postcode` is not a declared
    canonical field on every corpus (B7 keeps a brand-new scalar and auto-shows it), and a
    market that quotes no codes at all leaves this "" everywhere, which makes the whole
    over-merge check inert rather than degraded."""
    return match._stated_postcode(rec)


def _override_locked(rec: dict, field: str) -> bool:
    """Has a REVIEWED HUMAN CORRECTION pinned this field on this record?

    Reads the `__meta.override_locked` stamp `apply_overrides` writes, and nothing else. One
    predicate for all three readers (the precedence pin, the count tiebreak and the plausibility
    strike) so they cannot drift apart about what "locked" means: a lock the pin honours but the
    band ignores is exactly how a correction came to be applied and then struck in the same run.
    Tolerant of a missing/None `__meta` - a synthesised record in an eval has neither."""
    return field in set(((rec.get("__meta") or {}).get("override_locked")) or ())


def cluster_anchor(cluster: list) -> str:
    """A stable, order-independent identity for a CLUSTER, built from WHICH RECORDS are in
    it - never from their values.

    `match_key(cluster[0])` was neither: it depended on record-file order, and it moved
    whenever the winning record's park/city text moved. Anchoring on the member records'
    (source_file, locator) means a corrected VALUE leaves the anchor untouched, which is
    exactly the property conflict_id needs. (B09)

    B6: the per-record key deliberately EXCLUDES `page_no`, and every other presentational
    `__meta` binding (`heroRef`, `plan_page`, `image_pages`, `exclude_refs`). `page_no` is not
    record identity - the interpretation contract defines it as the page carrying this
    property's HERO PHOTO, which is routinely NOT the page its text came from. Including it
    meant an image-only repair re-keyed every conflict_id for that property: on live runs a
    Raven Park hero rebind re-keyed 9 settled value decisions and a Rockingham 161 rebind
    re-keyed 2, each costing a fresh exit-10 round and an LLM dispatch to re-derive answers
    whose candidate values, sources, locators and defaults were byte-identical. The repairs
    that trigger it are exactly the ones the G-images gate asks for, so the two mechanisms
    fought each other.

    Dropping it cannot create a collision: two options described on the SAME page of one deck
    share `locator_base` AND `page_no` (the contract binds both to that page), so their keys
    were already identical. The only pairs `page_no` separated were a single record whose text
    page and hero page diverge - one property, not two. `evals/anchor_stability_test.py` proves
    both halves rather than asserting them."""
    import hashlib
    ids = []
    for r in cluster or []:
        m = (r.get("__meta") or {})
        ids.append(f"{m.get('source_file', '')}#{m.get('locator_base', '')}")
    return hashlib.sha1(chr(0).join(sorted(ids)).encode("utf-8")).hexdigest()[:16]


def candidates_sig(values: list) -> str:
    """A short signature of the disagreeing VALUE SET. Recorded alongside a conflict so a
    changed candidate set is auditable - it is deliberately NOT part of conflict_id. (B09)"""
    import hashlib
    return hashlib.sha1(chr(0).join(sorted(str(v) for v in values))
                        .encode("utf-8")).hexdigest()[:12]


def conflict_id(cluster_key: str, field: str, values: list | None = None) -> str:
    """A STABLE, ORDER-INDEPENDENT id for a value conflict: sha1 of the cluster ANCHOR and
    the field.

    The value set used to be part of the hash, and that was the defect: CORRECTING one of
    the disagreeing values re-minted the conflict's own id, so the adjudication the broker
    had already given was orphaned. And because the QA improvement round's remedy is
    `work/overrides.json` - which merge applies BEFORE clustering but run.py's enumeration
    never applies at all - the two sides computed different ids and merge SILENTLY DROPPED
    every adjudicated pick for that property, with no Gaps line. Not a re-ask loop: a
    silent loss.

    There is exactly ONE conflict per (cluster, field) by construction, so dropping the
    values cannot collide two live conflicts. `values` is still accepted (callers pass it)
    but only feeds `candidates_sig`, which is recorded separately so a changed candidate set
    stays visible without moving the handle. (B09)"""
    import hashlib
    return hashlib.sha1(f"{cluster_key}|{field}".encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- gross vs net area (B55)
# extract_xlsx ALREADY derives the net warehouse figure when an office column sits in the SAME
# tracker row (`warehouseArea = GIA - office`). It cannot when the office figure lives in the
# BROCHURE, because that is a different record and only comparable after clustering. Merge is the
# only place holding both halves, and it used to do nothing with them: it saw two numbers for one
# field and raised a value conflict. 11 of 48 on a live run, every one resolved the same way by a
# sub-agent, and INCONSISTENTLY across rounds - a mechanical question asked of a judge.
GROSS_AWARE_FIELDS = frozenset({"warehouseArea"})


def is_gross_area(rec) -> bool:
    """Is this record's `warehouseArea` the source's GROSS whole-building figure?

    True when it equals the record's own `__meta.statedTotalArea`. extract_xlsx sets that only for
    a GIA/GEA/GLA-qualified size, and leaves it EQUAL to warehouseArea only when it could not
    subtract an office area - so the office is still inside the number. No heuristic: this is a
    structural fact the extractor itself recorded."""
    if not isinstance(rec, dict):
        return False
    m = rec.get("__meta") or {}
    st, wa = m.get("statedTotalArea"), rec.get("warehouseArea")
    if isinstance(st, bool) or isinstance(wa, bool):
        return False
    if not isinstance(st, (int, float)) or not isinstance(wa, (int, float)):
        return False
    return float(st) == float(wa)


def _gross_split(cluster, field) -> tuple:
    """(non_gross, gross) for a cluster holding BOTH kinds, else ([], []).

    Returning ([], []) is what keeps this safe. A tracker-only property has no net alternative, so
    it KEEPS its gross figure rather than losing its only area - dropping a client's sole area
    figure would be far worse than carrying a slightly gross one. Two gross or two net candidates
    fall through to the existing precedence untouched."""
    if field not in GROSS_AWARE_FIELDS:
        return ([], [])
    have = [r for r in (cluster or [])
            if isinstance(r, dict) and isinstance(r.get(field), (int, float))
            and not isinstance(r.get(field), bool)]
    gross = [r for r in have if is_gross_area(r)]
    non_gross = [r for r in have if not is_gross_area(r)]
    if not gross or not non_gross:
        return ([], [])
    return (non_gross, gross)


def _ordered_for_field(field, cluster, comm_order, spec_order, tracker_order, has_rich):
    """The precedence order merge_cluster applies for one field (single source of
    truth so conflict_candidates and merge_cluster agree on the default winner)."""
    if field in COMMERCIAL:
        base = comm_order
    elif has_rich and field in TRACKER_AUTHORITATIVE:
        base = tracker_order
    else:
        base = spec_order
    # B55: a GROSS whole-building figure loses to an explicit net one, whatever the source
    # precedence would otherwise say. The gross number CONTAINS the office area, so using it as
    # `warehouseArea` double-counts the moment the chrome adds officeArea back to derive GLA -
    # the 498,723 + 58,509 defect class. Applied here so both callers inherit it and cannot drift.
    non_gross, _gross = _gross_split(cluster, field)
    if non_gross:
        rank = {id(r): 0 for r in non_gross}
        return sorted(base, key=lambda r: rank.get(id(r), 1))
    return base


def collect_source_languages(records: list) -> dict:
    """{iso_code: count} of the languages the interpretation agents DECLARED. (B54)

    The agent is reading the deck anyway, so declaring its language costs nothing - and it lets
    run.py skip an entire translation round when the source already matches the dashboard
    language. A 12-property English run with an English dashboard previously queued 53 items for
    an English-to-English translation: a full agent dispatch plus a shell round-trip, on the most
    common configuration there is.

    Python only COUNTS here; the model judges what language the deck is in."""
    out: dict = {}
    for r in records or []:
        v = (r.get("__meta") or {}).get("source_lang") if isinstance(r, dict) else None
        if isinstance(v, str) and v.strip():
            k = v.strip().lower()
            out[k] = out.get(k, 0) + 1
    return out


def cluster_label(cluster: list[dict]) -> str:
    """A human-readable name for one cluster, for a broker-facing question or Gaps line."""
    for r in cluster or []:
        for f in ("park", "name", "address", "city"):
            v = r.get(f)
            if isinstance(v, str) and v.strip() and not N.looks_unknown(v):
                city = r.get("city")
                if f != "city" and isinstance(city, str) and city.strip() \
                        and not N.looks_unknown(city) and city.strip().lower() not in v.lower():
                    return f"{v.strip()}, {city.strip()}"
                return v.strip()
    return "(unnamed option)"


def cluster_families(cluster: list[dict]) -> set:
    """The set of source families ('tracker'/'brochures') evidencing one cluster."""
    import clarify as _CQ
    return {f for f in (_CQ.record_family(r) for r in cluster or []) if f}


def authority_extras(clusters: list[list[dict]]) -> dict:
    """family -> [cluster labels evidenced ONLY by that family].

    Computed from SETTLED clusters, so a brochure record that merged into a tracker row is
    correctly NOT an extra. This is the input to the broker's source-authority question and
    the exact set `apply_source_authority` would drop."""
    # A DISAGREEMENT NEEDS TWO SOURCES. On a single-family corpus - a pure brochure run, or a
    # tracker-only run - every cluster is trivially "evidenced by only one family", which is
    # not a discrepancy at all: there is no second source that could have listed it. Asking
    # then would stop a broker mid-run to arbitrate between one source and nothing, and the
    # only honest answer would re-select everything. Return no extras, so no question fires
    # and the filter is a no-op. (Caught by evals/cowork_sim.py on a 4-deck, no-tracker corpus.)
    present = set()
    for cl in clusters or []:
        present |= cluster_families(cl)
    if len(present) < 2:
        return {}
    out = {"tracker": [], "brochures": []}
    for cl in clusters or []:
        fams = cluster_families(cl)
        if len(fams) == 1:
            fam = next(iter(fams))
            if fam in out:
                out[fam].append(cluster_label(cl))
    return {k: v for k, v in out.items() if v}


def _cluster_headline(cluster: list[dict]) -> dict:
    """A cluster's own headline figures, for the Gaps disclosure of an excluded
    record - the broker must see WHAT was excluded, not just that something was.
    A figure and its unit come from the SAME record: a sibling's unit must never
    label another record's magnitude (that would be a possible 10.76x mislabel
    inside the very line meant to settle the figure)."""
    h = {}
    for r in cluster or []:
        v = r.get("warehouseArea")
        if "warehouseArea" not in h and v not in (None, "") and not N.looks_unknown(v):
            h["warehouseArea"] = v
            u = r.get("areaUnit")
            if u and not N.looks_unknown(u):
                h["areaUnit"] = u
        rv = r.get("warehouseRent")
        if "warehouseRent" not in h and rv not in (None, "") and not N.looks_unknown(rv):
            h["warehouseRent"] = rv
            ru = r.get("rentUnit")
            if ru and not N.looks_unknown(ru):
                h["rentUnit"] = ru
        c = r.get("city")
        if "city" not in h and c not in (None, "") and not N.looks_unknown(c):
            h["city"] = c
    return h


def _forbidden_identity(a: dict, b: dict) -> bool:
    """Does a FORBIDDEN pair also share IDENTITY (it would have matched were it not
    for the size conflict)? The bare size test fires for any cross-source pair, so
    forbidden alone means nothing; with identity it means 'plausibly one building,
    two conflicting descriptions'."""
    return (match.match_key(a) == match.match_key(b)
            or match._cross_source_grey(a, b))


def shipped_forbidden_conflicts(clusters: list[list[dict]]) -> list[str]:
    """Both-shipped forbidden pairs WITH identity: two cards that are plausibly one
    building, kept apart by the >15% size rule, BOTH shipping. The LLM never saw
    the pair (forbidden is a hard veto), the dedupe gate sees two distinct keys,
    and nothing else compares the figures - this is the channel that names it.
    Cross-source only: a same-file forbidden pair is two units of one scheme,
    distinct phases BY DESIGN, and flagging every multi-unit deck would be noise."""
    def _fmt(h: dict) -> str:
        v = h.get("warehouseArea")
        if v is None:
            return "size unstated"
        s = f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
        return f"{s} {h.get('areaUnit') or ''}".strip()

    out = []
    for i, ca in enumerate(clusters or []):
        for cb in clusters[i + 1:]:
            hit = False
            for a in ca:
                for b in cb:
                    if (a.get("__meta") or {}).get("source_file") == \
                            (b.get("__meta") or {}).get("source_file"):
                        continue
                    if match.pair_class(a, b) == "forbidden" \
                            and _forbidden_identity(a, b):
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                continue
            # one line per CLUSTER PAIR, never deduped by label: two clusters of one
            # multi-unit park share a label, and collapsing them hid distinct conflicts
            la, lb = cluster_label(ca), cluster_label(cb)
            out.append(f"'{la}' and '{lb}' are plausibly the SAME building described "
                       f"twice (shared identity, but a >15% size conflict kept them "
                       f"from merging: {_fmt(_cluster_headline(ca))} vs "
                       f"{_fmt(_cluster_headline(cb))}); both ship as separate cards - "
                       f"confirm with the agent that they are genuinely distinct")
    return out


def _likely_same_kept(dropped_cluster: list[dict], kept: list[list[dict]]):
    """The kept cluster this dropped one plausibly IS - a forbidden/grey pair kept
    them from clustering, so the 'excluded option' is really a CONFLICTING RECORD
    for a shipped card. Without this linkage a suppressed figure for a shipped
    property reads as a distinct option disappearing, and the conflict (230,000 vs
    356,202 for the same plot, on a live run) surfaces nowhere. Deterministic:
    first forbidden match wins; a grey match is kept only if no forbidden exists."""
    best = None
    for _ki, kcl in enumerate(kept or []):
        for dr in dropped_cluster or []:
            for kr in kcl or []:
                # same-file pairs are distinct BY DESIGN (two units of one scheme) -
                # never assert "plausibly one building" across them
                if (dr.get("__meta") or {}).get("source_file") == \
                        (kr.get("__meta") or {}).get("source_file"):
                    continue
                tier = match.pair_class(dr, kr)
                # 'forbidden' fires on the SIZE test alone, for any cross-source
                # pair - as a linkage signal it needs IDENTITY too: the pair must
                # be one that would have matched (equal keys, or the grey identity
                # pre-filter) were it not for the size conflict.
                if tier == "forbidden":
                    if not _forbidden_identity(dr, kr):
                        continue
                elif tier != "grey":
                    continue
                # kept_index = the kept cluster's position, which IS its eventual
                # property id minus 1 (ids are assigned by enumerating this same
                # list) - the exit-13 excluded-figure question keys on it
                cand = {"name": cluster_label(kcl), "tier": tier,
                        "kept_index": _ki,
                        "kept_headline": _cluster_headline(kcl)}
                if tier == "forbidden":
                    return cand
                best = best or cand
    return best


def apply_source_authority(clusters: list[list[dict]], authority: str) -> tuple:
    """Split settled clusters into (kept, dropped) per the broker's source-authority answer.

    A cluster is KEPT when at least one of its records comes from the authoritative family.
    `authority` of 'union' (or anything unrecognised, or absent) keeps everything, so a run
    without an answer is byte-identical to the historical behaviour.

    THREE deliberate safety properties, because this is the only code in the skill that can
    remove a client's property from their own longlist:
      * A cluster evidenced by NEITHER family (an email-only or image-only option) is always
        KEPT - the filter only ever excludes on positive evidence of the other family.
      * If the filter would empty the dataset, NOTHING is dropped. That means a mis-detected
        source family degrades to the union rather than shipping an empty dashboard.
      * `dropped` is returned, never discarded: every exclusion is named in the Gaps Report.
    """
    import clarify as _CQ
    fam = str(authority or "").strip().lower()
    if fam not in _CQ.AUTHORITY_FAMILIES:
        return list(clusters or []), []
    kept, dropped = [], []
    for cl in clusters or []:
        fams = cluster_families(cl)
        # keep on positive evidence, or when no family evidences it at all (email/image-only)
        if fam in fams or not fams:
            kept.append(cl)
        else:
            dropped.append(({
                "name": cluster_label(cl),
                "evidenced_by": sorted(fams),
                "source_files": sorted({str((r.get("__meta") or {}).get("source_file") or "")
                                        for r in cl if (r.get("__meta") or {}).get("source_file")}),
                "why": (f"not evidenced by the {fam}, which you set as the guiding source for "
                        f"what belongs on this longlist"),
            }, cl))
    if not kept:
        # fail OPEN: an authority that matches nothing is far more likely a mis-detection than
        # a client with zero properties. Ship the union and let the Gaps Report say so.
        return list(clusters or []), []
    # RECORD-LEVEL DISCLOSURE: carry each dropped cluster's own headline figures,
    # and - when a forbidden/grey pair links it to a KEPT cluster - name the shipped
    # card it plausibly IS, so the Gaps Report prints the actual figure conflict
    # instead of a bare option name.
    entries = []
    for entry, dcl in dropped:
        # the enrichment must NEVER cancel the exclusion itself: a failure here,
        # inside the caller's authority try/except, would silently ship the union
        # the broker excluded. Per-entry, best-effort, error disclosed on the entry.
        try:
            hl = _cluster_headline(dcl)
            if hl:
                entry["headline"] = hl
            link = _likely_same_kept(dcl, kept)
            if link:
                entry["likely_same_as"] = link
        except Exception as e:
            entry["headline_error"] = f"{type(e).__name__}: {e}"
        entries.append(entry)
    return kept, entries


def conflict_candidates(clusters: list[list[dict]]) -> list[dict]:
    """Enumerate EVERY genuine cross-source value conflict across the clusters,
    PURE PYTHON (no LLM). A conflict = a field where >= 2 records in one cluster
    hold DIFFERENT non-unknown values (the exact looks_unknown test merge_cluster
    uses). Deterministic: clusters in order, sorted(fields), a content-keyed id.
    Returns one dict per conflict with the candidate values + their source meta +
    the precedence-winner `default` label, ready for work/match_candidates.json's
    `field_conflicts` array. Typically 0-3 per run (like grey pairs)."""
    out: list[dict] = []
    for cl in clusters:
        if len(cl) < 2:
            continue  # a <=1-record cluster can hold no value conflict (needs >=2 disagreeing records) - #44
        comm_order = sorted(cl, key=lambda r: (COMM_RANK.get(_st(r), 9), _unreliable(r), -_datekey(r)))
        spec_order = sorted(cl, key=lambda r: (_unreliable(r), SPEC_RANK.get(_st(r), 9)))
        tracker_order = sorted(cl, key=lambda r: (not _is_rich(r), _unreliable(r),
                                                  SPEC_RANK.get(_st(r), 9)))
        has_rich = any(_is_rich(r) for r in cl)
        merged_key = match.match_key(cl[0]) if cl else ""
        fields = set()
        for r in cl:
            fields.update(k for k in r if k != "__meta")
        for field in sorted(fields):
            # B55: a gross-vs-net area disagreement is settled by the deterministic basis rule in
            # _ordered_for_field, not by a sub-agent. Enumerating it asked a model to re-derive
            # the same mechanical answer once per property (11 times on a live run) and let two
            # rounds answer it differently. merge_cluster still records the discarded gross figure
            # in meta.conflicts, so nothing is hidden - only the pointless adjudication is gone.
            if _gross_split(cl, field)[0]:
                continue
            order = _ordered_for_field(field, cl, comm_order, spec_order, tracker_order, has_rich)
            cands: list[dict] = []
            seen_vals: list = []   # raw values (a list value is unhashable)
            for r in order:
                if field not in r:
                    continue
                v = r[field]
                if N.looks_unknown(v) and field not in ("landPrice", "reit"):
                    continue
                # I10: the same value from two records is not a disagreement - and neither is the
                # SAME FACT in different notation ("1000 KVA" vs "1 MVA"). Suppressing the variant
                # here is what stops it being offered for adjudication; merge_cluster records it in
                # its `variants` out-param so it still reaches the broker.
                if any(_values_equivalent(field, v, sv) for sv in seen_vals):
                    continue
                seen_vals.append(v)
                meta = r.get("__meta", {})
                st = meta.get("source_type", "")
                cands.append({
                    "label": chr(ord("a") + len(cands)),
                    "value": v,
                    "source_type": st,
                    "date": meta.get("date", ""),
                    "locator": meta.get("prov", {}).get(field, meta.get("locator_base", "")),
                    "source_file": meta.get("source_file", ""),
                    "prov_tag": ("vision transcription" if "vision" in str(
                        meta.get("prov", {}).get(field, "")).lower()
                        else "text interpretation" if "interpretation" in str(
                        meta.get("prov", {}).get(field, "")).lower()
                        else st),
                    "precedence_rank": len(cands),
                })
            if len(cands) < 2:
                continue  # not a genuine conflict (one or zero distinct non-unknown values)
            values = [c["value"] for c in cands]
            out.append({
                # anchored on WHICH RECORDS are in the cluster, not on cl[0]'s match_key and
                # not on the values - so a corrected value keeps the same handle (B09)
                "conflict_id": conflict_id(cluster_anchor(cl), field, values),
                "cluster_key": merged_key,
                "cluster_anchor": cluster_anchor(cl),
                "candidates_sig": candidates_sig(values),
                "field": field,
                "candidates": cands,
                "default": cands[0]["label"],  # the precedence winner (order[0])
            })
    return out


_QUALIFIER_RX = re.compile(r"\btarget(?:ing|ed)?\b", re.I)
# certification-like fields where dropping a "Target"/"Targeting"/"Targeted" hedge is not
# mere notation - it silently converts an ASPIRATION on a not-yet-certified building into a
# claim of an ACHIEVED fact. Scoped narrowly (NOT all of _ENUM_EQ_FIELDS): `status` legitimately
# drops "now"/"immediately" as pure notation with no achieved-vs-aspirational ambiguity.
_QUALIFIER_PREFER_FIELDS = {"breeam", "epc"}


def _more_qualified(field: str, a, b) -> bool:
    """True if `b` states a Target/Targeting/Targeted hedge that `a` lacks, for a field where
    dropping that hedge overclaims a not-yet-achieved fact. Callers only reach this once `a`
    and `b` are ALREADY known equivalent (_values_equivalent) - same underlying grade,
    different notation - so this never decides whether two values conflict, only which of two
    equivalent spellings is safe to show."""
    if field not in _QUALIFIER_PREFER_FIELDS:
        return False
    return bool(_QUALIFIER_RX.search(str(b))) and not _QUALIFIER_RX.search(str(a))


def merge_cluster(cluster: list[dict], decisions: dict | None = None,
                  variants: dict | None = None,
                  struck: list | None = None) -> tuple[dict, dict, dict]:
    """`variants` is an OPTIONAL out-parameter (I10): pass a dict and it is filled with
    field -> note for every pair that states the same fact in different notation. It is an
    out-param rather than a fourth return value deliberately - the 3-tuple has thirteen call
    sites across the eval battery, and widening it would have been churn and risk for nothing.

    `struck` is an OPTIONAL out-parameter of the same kind: pass a list and it is appended with
    {field, value, source_file, locator} for every field the plausibility band STRIKES to the
    unknown sentinel, `value` being the figure as its source printed it. The caller stamps the
    property id on each entry (this function has no id) and ships them as canonical.meta.struck,
    which is what lets the honesty report show WHAT was withdrawn beside the conflict line
    explaining why, instead of asking the reader to reconstruct it from work/extract.

    DELIBERATELY NOT COLLECTED here: the both-values-rejected strike in the LLM-pick branch. Two
    values are withdrawn there, so no single `value` could describe it honestly, and its own
    conflict line already quotes both verbatim. `struck` stays a one-value-per-entry artefact."""
    out: dict = {}
    prov: dict = {}
    conflicts: dict = {}  # field -> "discarded <val> from <file> (kept <winner>)"
    # newest email wins among commercials (rank 0, date desc); brochure wins for
    # specs - but an UNRELIABLE brochure (mostly-poor parse) loses to any cleaner
    # source, so a garbled PDF cannot outrank its clean PPTX twin on rank alone;
    # and a RICH tracker leads the structured spec fields + coordinates
    comm_order = sorted(cluster, key=lambda r: (COMM_RANK.get(_st(r), 9), _unreliable(r), -_datekey(r)))
    spec_order = sorted(cluster, key=lambda r: (_unreliable(r), SPEC_RANK.get(_st(r), 9)))
    tracker_order = sorted(cluster, key=lambda r: (not _is_rich(r), _unreliable(r),
                                                   SPEC_RANK.get(_st(r), 9)))
    has_rich = any(_is_rich(r) for r in cluster)
    cluster_key = match.match_key(cluster[0]) if cluster else ""
    # The conflict handle anchors on WHICH RECORDS are in the cluster, never on cluster[0]'s
    # match_key (order-dependent, and it moves when a value is corrected). conflict_candidates
    # computes the identical anchor - if these two ever diverge, every adjudicated pick is
    # silently dropped, which is precisely the bug. (B09)
    _anchor = cluster_anchor(cluster)
    # rent-unit hint for the per-field plausibility gate (the cluster's stated unit,
    # else the €/sq m default) - so a £/sq ft override is judged against its own band.
    rent_unit = next((r.get("rentUnit") for r in cluster if r.get("rentUnit")), None)

    fields = set()
    for r in cluster:
        fields.update(k for k in r if k != "__meta")

    for field in sorted(fields):  # sorted -> deterministic output bytes
        order = _ordered_for_field(field, cluster, comm_order, spec_order, tracker_order, has_rich)
        # A10 COUNT-FIELD BAND TIEBREAK. For a COUNT field the plausibility band runs BEFORE
        # source rank: among the records holding a non-unknown value, those whose value does not
        # FAIL the band lead, and the inherited precedence order stands inside each group. A
        # STABLE partition, so a field whose candidates all agree with the band keeps today's
        # order byte-for-byte; records holding nothing for this field are skipped by the loop
        # below either way, so where they land cannot matter.
        #
        # WHY. Source rank alone decided two halves of ONE defect. A brochure outranks a tracker
        # for a spec field, so a prose sentence ("dock and level access loading available") won
        # `loadingDocks` over a clean numeric count sitting in another record of the SAME cluster,
        # and the value-format gate then flagged the very prose the merge had just chosen. When
        # that prose went on to FAIL the band, the strike below set the field to the unknown
        # sentinel and the numeric sibling never fell through - so the card shipped tbd with the
        # answer already in the pack. Preferring a candidate the band accepts settles both ends.
        #
        # SCOPE. `_COUNT_GATE_FIELDS` is the EXISTING count vocabulary (the same set
        # `_pick_gate_verdict` bands as counts) and is reused here deliberately: there is no
        # unified field-type registry at the precedence point, and inventing one is out of scope
        # for this change. Nothing outside that set is reordered, so no other field moves.
        #
        # A LOCKED value counts as banded whatever the band says: a reviewed correction is exempt
        # from the strike (A9), so it must not be demoted by the band here either - otherwise
        # this tiebreak would quietly undo the P1-4 pin two lines below.
        if field in _COUNT_GATE_FIELDS:
            _ok = [r for r in order
                   if field in r and not N.looks_unknown(r[field])
                   and (_override_locked(r, field)
                        or _pick_gate_verdict(field, r[field]) != "fail")]
            if _ok:
                _okids = {id(r) for r in _ok}   # id(), never `in`: see the pin's note below
                order = _ok + [r for r in order if id(r) not in _okids]
        # P1-4 PRECEDENCE PIN. `out[field]`/`prov[field]` are set by the FIRST record in `order`
        # holding a non-unknown value, so overriding a record that LOSES the precedence contest
        # would change nothing visible - a silent no-op that looks exactly like the bug the
        # override was written to fix. Explicit order: broker override > LLM pick > precedence.
        # Compared by id(), never by `in` (dict equality would also pull in an identical sibling).
        # Byte-identical when nothing is locked.
        _locked = [r for r in order if _override_locked(r, field)]
        if _locked:
            _lids = {id(r) for r in _locked}
            order = _locked + [r for r in order if id(r) not in _lids]
        chosen = None
        # A9: WHICH RECORD supplied the value now in `out[field]`. Tracked because the
        # plausibility strike at the foot of this loop has to ask whether a REVIEWED CORRECTION
        # supplied it, and `_locked` alone cannot answer that: a locked record leads the order but
        # need not hold a value for this field, and the qualifier and LLM-pick branches below can
        # move the winner to a different record after the first one is chosen.
        _chosen_rec = None
        # candidate records that hold a distinct non-unknown value, in precedence
        # order (used both for the discard note and the override lookup)
        cand_recs: list[dict] = []
        seen_vals: list = []   # raw values (a list value is unhashable)
        def _prov_of(rec, meta_):
            return {
                "source_file": meta_.get("source_file", ""),
                "source_type": meta_.get("source_type", ""),
                "locator": meta_.get("prov", {}).get(field, meta_.get("locator_base", "")),
                # THE FOOTING OF THIS FIELD'S OWN SUPPLIER (B39). Every field resolves its
                # own precedence contest, so an area can come from one record while
                # `areaUnit` comes from another - and one dataset-wide label was then
                # applied to all of them, scaling a figure by 10.7639 on a unit its own
                # source never stated. `prov` is local to main() and never serialised into
                # canonical, so recording it here cannot move a rendered byte.
                # B58: a FIELD may state its own unit - a site area in acres inside a sq ft
                # brochure is the normal UK shape. Prefer it; fall back to the record-level
                # areaUnit. Without this the figure had nowhere to go, and two agents on one
                # run split between dropping it and converting it themselves.
                "areaUnitOfSource": (rec.get(f"{field}Unit") or rec.get("areaUnit") or None),
            }
        for r in order:
            if field not in r:
                continue
            v = r[field]
            if N.looks_unknown(v) and field not in ("landPrice", "reit"):
                continue
            meta = r.get("__meta", {})
            if chosen is None:
                chosen = v
                out[field] = v
                prov[field] = _prov_of(r, meta)
                _chosen_rec = r
            elif str(v) != str(chosen) and _values_equivalent(field, v, chosen):
                # I10: the same fact in different notation. NOT a conflict - but recorded, because
                # nothing may be silently dropped. It ships in its own Gaps Report section.
                # The `str(v) != str(chosen)` guard matters: an IDENTICAL value from a second record
                # was always a silent no-op and must stay one, not become a "variant" note.
                if variants is not None and field not in variants:
                    variants[field] = (
                        f"'{v}' from {meta.get('source_file','?')} states the same value as "
                        f"'{chosen}' in different notation - no action needed")
                # B-target-qualifier: for a certificate field (breeam/epc), a "Target"/
                # "Targeting"/"Targeted" hedge is not mere notation once dropped - it is the
                # difference between an aspiration and an achieved fact. When two equivalent
                # notations disagree ONLY on that hedge, the MORE CAUTIOUS one always ships,
                # regardless of source precedence - never the reverse (_more_qualified is
                # directional: it only ever upgrades, never downgrades, an already-hedged
                # `chosen`). This never fires for a genuine conflict - that goes through the
                # `elif str(v) != str(chosen):` branch below instead, untouched.
                if _more_qualified(field, chosen, v):
                    chosen = v
                    out[field] = v
                    prov[field] = _prov_of(r, meta)
                    _chosen_rec = r
            elif str(v) != str(chosen):
                # a different non-unknown value lost the precedence contest - record it
                # B55: when the GROSS basis rule is what demoted it, say so. "discarded X (kept
                # Y)" is true but leaves a broker guessing why two sources disagree by exactly
                # the office area; this names the reason and confirms the figure is not lost.
                if _gross_split(cluster, field)[0] and is_gross_area(r):
                    conflicts[field] = (
                        f"discarded the GROSS whole-building '{v}' from "
                        f"{meta.get('source_file','?')} (kept the warehouse-only '{chosen}'): the "
                        f"gross figure already contains the office area, so using it here would "
                        f"double-count once GLA is derived. It is retained as the stated total.")
                elif field in _COUNT_GATE_FIELDS \
                        and _pick_gate_verdict(field, v) == "fail" \
                        and _pick_gate_verdict(field, chosen) != "fail":
                    # A10: the BAND is why this candidate lost, not source rank - and saying so is
                    # the disclosure. A bare "discarded X (kept Y)" reads as an ordinary precedence
                    # loss, leaving the reader unable to tell that a HIGHER-ranked source was
                    # passed over on purpose. Same shape as the B55 gross-basis note above: name
                    # the rule, then confirm the discarded text is not lost.
                    conflicts[field] = (
                        f"discarded '{v}' from {meta.get('source_file','?')} (kept '{chosen}'): "
                        f"it holds no plausible {field} count, so a candidate that does was "
                        f"preferred over source precedence rather than shipping this one and "
                        f"striking it. The discarded text is retained in the extract.")
                else:
                    conflicts[field] = (f"discarded '{v}' from {meta.get('source_file','?')} "
                                        f"(kept '{chosen}')")
            # I10: a value EQUIVALENT to one already collected is not a second candidate, so it
            # never makes this field a "genuine conflict" and never costs an adjudication.
            if not any(_values_equivalent(field, v, sv) for sv in seen_vals):
                seen_vals.append(v)
                cand_recs.append(r)
        # LLM VALUE-CONFLICT OVERRIDE (#4): a GENUINE conflict (>= 2 distinct non-
        # unknown values) may carry a cached sub-agent pick keyed by an order-
        # independent conflict_id. The precedence winner (chosen) is the DEFAULT; the
        # pick OVERRIDES it ONLY when (a) it selects one of the given candidate values
        # AND (b) that value PASSES the field's deterministic plausibility gate. A
        # pick that fails the gate, names no candidate, or selects the default is
        # ignored and precedence stands. SELECTION-ONLY: never a free/invented value.
        # `not _locked`: an LLM pick must never un-pick a HUMAN correction (P1-4).
        if decisions and len(cand_recs) >= 2 and not _locked:
            values = [c[field] for c in cand_recs]
            cid = conflict_id(_anchor, field, values)
            verdict = decisions.get(cid)
            if isinstance(verdict, dict):
                pick = verdict.get("pick")
                reason = verdict.get("reason", "")
            else:
                pick, reason = (verdict, "") if isinstance(verdict, str) else (None, "")
            # labels are assigned a,b,c,... in precedence order, matching conflict_candidates
            labels = [chr(ord("a") + i) for i in range(len(cand_recs))]
            if pick in labels and pick != labels[0]:  # a non-default candidate pick
                picked = cand_recs[labels.index(pick)]
                pv = picked[field]
                _verdict = _pick_gate_verdict(field, pv, rent_unit, picked.get("areaUnit"))
                if _verdict in ("pass", "none"):
                    out[field] = pv
                    pmeta = picked.get("__meta", {})
                    prov[field] = {
                        "source_file": pmeta.get("source_file", ""),
                        "source_type": pmeta.get("source_type", ""),
                        "locator": pmeta.get("prov", {}).get(field, pmeta.get("locator_base", "")),
                        # the OVERRIDE's own footing - an LLM pick changes which record
                        # supplied the number, so it must change the unit it is scaled on (B39)
                        "areaUnitOfSource": picked.get("areaUnit") or None,
                    }
                    _chosen_rec = picked   # A9: the winner moved, so the strike's question moves
                    # B3: an UNGATED field's selection is now HONOURED and labelled, not silently
                    # dropped. The adjudicator only ever selects among values that already exist in
                    # the sources, so honouring it cannot invent data - whereas discarding it made
                    # the whole adjudication round decorative for every non-numeric field.
                    _tag = ("" if _verdict == "pass"
                            else " [unverified: no deterministic gate is defined for this field, so "
                                 "the selection is honoured but not machine-checked]")
                    conflicts[field] = (f"LLM override -> '{pv}' from "
                                        f"{pmeta.get('source_file','?')} (precedence default was "
                                        f"'{chosen}'){_tag}"
                                        f"{f': {reason}' if reason else ''}")
                else:
                    # B3: the pick failed a REAL gate. Keep the default only if the default passes
                    # that same gate. The predecessor always reinstated the default, so the gate
                    # could protect it but never catch it - if neither value is plausible the honest
                    # outcome is a struck field, not an unverified one.
                    if _pick_gate_verdict(field, chosen, rent_unit) == "pass":
                        conflicts[field] = (
                            f"LLM pick '{pv}' rejected: it fails the {field} plausibility gate. "
                            f"Kept the precedence default '{chosen}', which passes that same gate."
                            + (f" {conflicts.get(field, '')}" if conflicts.get(field) else ""))
                    else:
                        out[field] = "tbd"
                        conflicts[field] = (
                            f"BOTH values rejected for {field}: the LLM pick '{pv}' and the "
                            f"precedence default '{chosen}' each fail the {field} plausibility "
                            f"gate, so the field is struck to tbd rather than shipping an "
                            f"unverified value. Confirm the real value with the agent.")
        # B3: gate the PRECEDENCE WINNER as well. The gate used to run ONLY on an LLM override, so
        # it could protect the default but never catch it - which is how an impossible BREEAM 'A+'
        # shipped from a single source, with no conflict and no override involved at all. Only
        # fields with an explicit gate are affected ("none" is a no-op), and an already-unknown
        # value is left alone so this cannot clobber the notes written above.
        # B63: on ITS OWN SUPPLIER'S FOOTING. This call omitted `area_unit`, so every area band
        # fell through to `area_band_for(None)` - the sq m band, ceiling 600,000 - no matter what
        # unit the dataset or the record was in. On a live UK (sq ft) run that struck three
        # perfectly ordinary big-box sheds the tracker plainly states (659,428 / 783,309 /
        # 1,000,000 sq ft) to 'tbd', each with a note telling the broker to check whether the
        # source really prints it. `areaUnitOfSource` was recorded on this field's own prov entry
        # a few lines above and is the very value the alignment step in main() converts on, so
        # the gate that STRIKES a figure can no longer disagree with the step that scales it.
        # STRICTLY NON-REGRESSIVE, but NOT because area_band_for is monotonic - it is not; the
        # sq ft band raises the FLOOR from 300 to 3,000 as well as the ceiling. The gate itself
        # unions the unit-aware band with the unit-unknown one for exactly that reason, so no
        # value that passes today can start failing here.
        # (`_pick_gate_verdict` ignores this argument for every non-area field.)
        if field in out and not N.looks_unknown(out[field]) \
                and _pick_gate_verdict(field, out[field], rent_unit,
                                       (prov.get(field) or {}).get("areaUnitOfSource")) == "fail":
            _bad = out[field]
            # basename, matching every other citation in this module (a record's source_file is a
            # bare filename by contract, but a work-dir path must never decide how it reads)
            _srcf = Path(str((prov.get(field) or {}).get("source_file") or "")).name
            _src = _srcf or "?"
            if _chosen_rec is not None and _override_locked(_chosen_rec, field):
                # A9 OVERRIDE-LOCKED FIELDS ARE EXEMPT FROM THE BAND. A band exists to catch a
                # PARSE; an override is a reviewed human conclusion about what the evidence says,
                # already pinned to the front of precedence by P1-4 a few dozen lines above. The
                # strike ran regardless of that lock, so a correction could be reported as APPLIED
                # and then struck to the unknown sentinel in the same run - leaving the pack
                # asserting, of one field, both that no source provides it AND that an override
                # set it. Two contradictory statements about one datum is worse than either.
                #
                # EXEMPT, NOT SILENT: the value ships as the reviewer recorded it, and the
                # exemption is disclosed in the same channel a strike would have used, so a reader
                # meeting an out-of-band figure can see it was allowed through deliberately and by
                # whom. Nothing else is exempt - an UNLOCKED field, on this record or any other,
                # is still banded and still struck below.
                _oids = ", ".join(str(x) for x in
                                  ((_chosen_rec.get("__meta") or {}).get("override_ids") or []))
                conflicts[field] = (
                    f"the {field} plausibility band was NOT applied to '{_bad}' (from {_src}): a "
                    f"reviewed correction"
                    + (f" (override {_oids})" if _oids else "")
                    + f" supplied this value, and the band exists to catch a parse, not to "
                      f"re-judge a human conclusion. The value ships as recorded. Disclosed here "
                      f"because it sits outside the band a parsed figure would have to meet, so "
                      f"it is worth re-reading the correction against its evidence."
                    + (f" {conflicts[field]}" if conflicts.get(field) else ""))
            else:
                out[field] = "tbd"
                # T1 wording: the note must never accuse the SOURCE of implausibility - on a live
                # run this exact note shipped against values the source plainly printed (struck by
                # a parse/band defect, since fixed). It names the PARSED value, the gate, and the
                # two honest next steps; the extract still holds the original for the broker.
                conflicts[field] = (
                    f"the parsed value '{_bad}' (from {_src}) falls outside the {field} "
                    f"plausibility band, so the card ships tbd rather than a figure that may be a "
                    f"parse or unit error. Check the source page: if it genuinely prints this "
                    f"value, restore it via work/repairs.json; otherwise confirm the real value "
                    f"with the agent."
                    + (f" {conflicts[field]}" if conflicts.get(field) else ""))
            # A15/honesty: the STRUCK originals, one entry per struck field per property, so the
            # honesty report can show WHAT was withdrawn beside its conflict line instead of the
            # reader having to reconstruct it from the extract. Collected on the cluster here and
            # projected onto the property id by the caller (merge_cluster has no id).
            if struck is not None and out[field] != _bad:
                struck.append({"field": field, "value": _bad, "source_file": _srcf,
                               "locator": str((prov.get(field) or {}).get("locator") or "")})
    # SOURCE-INTERNAL disagreements. Everything above detects a conflict BETWEEN records, so a
    # source that contradicts ITSELF was invisible to the whole conflict machinery: one brochure
    # page whose schedule totals 180 docks while its own spec block says 170, another whose
    # schedule totals 50,843 m2 under a headline of 53,564 m2. The extractor SAW both figures and
    # could only mention the loser in prose inside its prov locator, so conflict_note stayed
    # empty, meta.conflicts never carried it, and the Gaps Report told the broker there was
    # nothing to settle. An extractor may now declare `__meta.source_conflicts = {field: note}`
    # and it lands in the same channel as every other conflict: the ledger's conflict_note and
    # the Gaps Report's "Source conflicts" section.
    # A cross-source note WINS the slot (it explains which record was discarded, which the broker
    # needs first) and the source-internal one is appended after it, so nothing is lost either way.
    # The note is printed VERBATIM with only its file appended - no prefix is imposed. The same
    # channel has to carry two shapes honestly: "the schedule says 180 docks, the spec block says
    # 170" and "the deck quotes a rent RANGE of 3.50-3.75 per month, the card ships the low end" -
    # and a hardcoded "disagrees with itself" would misdescribe the second. The extractor writes a
    # complete sentence; the pipeline decides only WHERE it appears.
    for r in cluster:
        for field, note in ((r.get("__meta") or {}).get("source_conflicts") or {}).items():
            note = str(note).strip()
            if not note or field not in out:
                continue
            src = ((r.get("__meta") or {}).get("source_file")) or "?"
            line = f"{note} [{src}]"
            conflicts[field] = f"{conflicts[field]} {line}" if conflicts.get(field) else line
    return out, prov, conflicts


def _datekey(rec) -> float:
    d = _date(rec)
    try:
        return _dt.datetime.fromisoformat(d).timestamp()
    except Exception:
        pass
    try:  # RFC-2822 ("Mon, 12 May 2025 10:11:00 +0200") - raw email headers
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(d).timestamp()
    except Exception:
        return 0.0


_SRC_RESOLVE: dict[str, Path | None] = {}


def _resolve_source(source_dir: Path, name: str) -> Path | None:
    """A record's source_file is a bare filename, but inputs may live in subfolders
    (intake scans recursively) - resolve directly, then by recursive name search.
    Memoised here; the SEARCH lives in _common.resolve_by_name so merge,
    vision_validate and extract_pdf cannot disagree about which file a name means.
    Without this, a subfolder brochure's hero image silently degraded to the placeholder."""
    if not name:
        return None
    # keyed on (dir, name): the memo used to key on the NAME alone, so a second source_dir
    # in the same process was served the first one's hit (B13)
    key = (str(source_dir), str(name))
    if key in _SRC_RESOLVE:
        return _SRC_RESOLVE[key]
    _SRC_RESOLVE[key] = C.resolve_by_name(source_dir, name)
    return _SRC_RESOLVE[key]


def _meta_image_pages(meta: dict) -> list[int]:
    """The validated 0-based image_pages of a record's __meta: ints >= 0 only.
    A non-list, or any non-int / negative entry, is silently dropped (the
    validator surfaces those; merge must never crash on a malformed value).
    Absence -> [] so pages_by_src reduces to page_no-only (byte-identical)."""
    ip = meta.get("image_pages")
    if not isinstance(ip, list):
        return []
    return [p for p in ip if isinstance(p, int) and not isinstance(p, bool) and p >= 0]


def _cluster_pages_by_src(cluster: list[dict], source_dir: Path) -> dict[str, set]:
    """The deck pages this cluster lays claim to, keyed by resolved source path:
    each pdf/pptx record's page_no UNION its validated __meta.image_pages. Mirrors
    the union attach_media builds, so the guard and the harvester see the SAME set."""
    out: dict[str, set] = {}
    for r in cluster:
        m = r.get("__meta", {})
        if m.get("source_type") in ("pdf", "pptx") and isinstance(m.get("page_no"), int):
            s = _resolve_source(source_dir, m.get("source_file", ""))
            if s:
                slot = out.setdefault(str(s), set())
                slot.add(m["page_no"])
                slot.update(_meta_image_pages(m))
    return out


_PAGE_UNCLAIMED = object()  # sentinel: a (src,page) anchored by zero or >1 clusters - owned by nobody


def _deck_ownership(clusters: list[list[dict]], source_dir: Path):
    """Shared post-merge ownership over the deck pages (the unique-claimant guard's input).
    Returns (pages_per_cluster, anchor_owner, claims):
    - pages_per_cluster[i][src] = cluster i's claimed pages (page_no U image_pages).
    - anchor_owner[(src, p)] = the cluster whose record page_no == p; _PAGE_UNCLAIMED when
      zero or MORE THAN ONE cluster anchors there (a clustering anomaly -> un-owned).
    - claims[(src, p)] = the set of cluster indices whose (page_no U image_pages) include p."""
    pages_per_cluster = [_cluster_pages_by_src(cl, source_dir) for cl in clusters]
    anchor_owner: dict[tuple, object] = {}
    for i, cl in enumerate(clusters):
        for r in cl:
            m = r.get("__meta", {})
            if m.get("source_type") in ("pdf", "pptx") and isinstance(m.get("page_no"), int):
                s = _resolve_source(source_dir, m.get("source_file", ""))
                if not s:
                    continue
                key = (str(s), m["page_no"])
                if key not in anchor_owner:
                    anchor_owner[key] = i
                elif anchor_owner[key] != i:
                    anchor_owner[key] = _PAGE_UNCLAIMED  # >1 distinct cluster anchors here
    claims: dict[tuple, set] = {}
    for i, pbs in enumerate(pages_per_cluster):
        for s, pgs in pbs.items():
            for p in pgs:
                claims.setdefault((s, p), set()).add(i)
    return pages_per_cluster, anchor_owner, claims


def _page_allowed(i: int, s: str, p: int, anchor_owner: dict, claims: dict) -> bool:
    """A page p of deck s is ALLOWED for cluster i iff cluster i anchors it, OR it is
    anchored by nobody AND cluster i is its SOLE claimant; otherwise another property owns
    it (foreign)."""
    owner = anchor_owner.get((s, p), _PAGE_UNCLAIMED)
    return (owner == i) or (owner is _PAGE_UNCLAIMED and claims.get((s, p)) == {i})


def build_foreign_pages(clusters: list[list[dict]], source_dir: Path) -> list[dict[str, set]]:
    """UNIQUE-CLAIMANT GUARD (pure Python, deterministic over the post-merge clusters).
    Python ENFORCES that every deck page feeds AT MOST ONE property's carousel, so no
    brochure topology can cross-contaminate even if the LLM over-claims image_pages.

    Returns a list parallel to `clusters`: foreign[i][src] = the set of cluster i's OWN
    claimed pages that are FOREIGN to it (owned/claimed by another property) and must be
    subtracted before harvesting. The gallery + the deterministic plan fallback subtract it
    from the cluster's own pages. (The plan_page HINT may name ANY page, not just the
    cluster's own, so it uses the BROADER `plan_offlimits_pages` instead.)

    Backward-compat: with NO image_pages anywhere, each cluster's claimed pages are its
    own page_no(s) - distinct per property in a correctly-clustered deck - so claims[p]
    is a singleton on each cluster's own page and foreign[i] is empty everywhere. A
    cluster's own page_no is never foreign -> byte-identical harvest set."""
    pages_per_cluster, anchor_owner, claims = _deck_ownership(clusters, source_dir)
    foreign: list[dict[str, set]] = []
    for i, pbs in enumerate(pages_per_cluster):
        fmap: dict[str, set] = {}
        for s, pgs in pbs.items():
            bad = {p for p in pgs if not _page_allowed(i, s, p, anchor_owner, claims)}
            if bad:
                fmap[s] = bad
        foreign.append(fmap)
    return foreign


def plan_offlimits_pages(clusters: list[list[dict]], source_dir: Path) -> list[dict[str, set]]:
    """Per cluster, EVERY page of the decks it touches that is OWNED BY ANOTHER property -
    the off-limits set for the plan_page HINT. Unlike the gallery/fallback (which only
    subtract from a cluster's OWN claimed pages), an LLM plan_page may name ANY page, so the
    guard needs the full other-owned set to reject a neighbour's page. Same allow-rule as
    `build_foreign_pages`; broader page coverage (all pages any cluster claims/anchors on
    that src). A single-property deck yields an empty set (no other owner)."""
    pages_per_cluster, anchor_owner, claims = _deck_ownership(clusters, source_dir)
    pages_on_src: dict[str, set] = {}
    for (s, p) in claims:
        pages_on_src.setdefault(s, set()).add(p)
    for (s, p) in anchor_owner:
        pages_on_src.setdefault(s, set()).add(p)
    out: list[dict[str, set]] = []
    for i, pbs in enumerate(pages_per_cluster):
        omap: dict[str, set] = {}
        for s in pbs:  # only the sources this cluster actually touches
            bad = {p for p in pages_on_src.get(s, set())
                   if not _page_allowed(i, s, p, anchor_owner, claims)}
            if bad:
                omap[s] = bad
        out.append(omap)
    return out


# --- PLAN-SLOT REACH over the pages NOBODY claimed ---------------------------------------- #
# The deterministic site-plan tier scans a property's OWN claimed pages (page_no U image_pages)
# minus the foreign ones. On a run where `image_pages` never came back - the reader had no page
# renders to look at, which is the whole defect this work exists to fix - that set is the single
# anchor page, so on a 13-page brochure the tier looks at ONE page and the site plan two pages
# later is out of reach. Measured on the 17-property corpus: the detector finds a real site plan
# on 15 of 16 decks when handed the deck, and bound 5, purely because of scope.
#
# The pages at issue are the ones NO property claims and NO property anchors. Reaching them is a
# recall question, and it is answered WITHOUT weakening ownership:
#   * SOLE-CLAIMANT deck - only one property draws on it at all, so `plan_offlimits` is empty by
#     construction and no page of that deck can be a neighbour's. The scope restriction protects
#     nothing there; it is pure recall loss. Every unclaimed page comes into reach.
#   * MULTI-CLAIMANT deck - a page could belong to either property, so a page comes into reach
#     ONLY when the page's own TYPOGRAPHY settles it: the property's distinguishing name token
#     appears at a font size at least PLAN_REACH_SIZE_RATIO times larger than any OTHER
#     claimant's token on that page. A brochure spread for unit B mentions unit A in a small
#     context label; the headline is the subject. Anything less decisive stays out of reach and
#     is disclosed, because a wrong image in the trace-less Site Plan slot is worse than none -
#     and an identical-duplicate bind across two units of one deck has happened on this corpus.
# THIS function is the PLAN SLOT's reach. The CAROUSEL has its own - `gallery_reach_pages`,
# below - built on the same `_deck_ownership` / `_page_allowed` base but with a recall-tuned
# attribution rule, because the two slots carry different risk. Relying on `__meta.image_pages`
# for the carousel was tried and MEASURED WRONG: the reader returned it for 4 of 17 properties,
# so the other 13 carousels could see a single page of a whole brochure.
PLAN_REACH_AREA_MIN = 1000      # below this a figure is a door count, not an area
_AREA_NUM_RE = re.compile(r"\d[\d,. ]*")
# The property fields that carry its own SIZE, i.e. the figures a brochure spread prints in the
# unit's schedule of accommodation. Strings are parsed for their leading number ('39,541 sq m').
_IDENTITY_AREA_FIELDS = ("warehouseArea", "warehouseAreaSqM", "warehouseAreaSqm",
                         "plotArea", "plotAreaSqM", "officeAreaVal", "officeAreaSqM")


def _page_figures(text: str) -> set:
    """Every integer >= PLAN_REACH_AREA_MIN printed on a page, thousands separators tolerated."""
    out: set = set()
    for m in _AREA_NUM_RE.finditer(str(text or "")):
        raw = m.group(0).replace(",", "").replace(" ", "").rstrip(".")
        if raw.isdigit():
            v = int(raw)
            if v >= PLAN_REACH_AREA_MIN:
                out.add(v)
    return out


def _identity_figures(cluster: list[dict]) -> set:
    """A merged property's own AREA figures - the numbers its unit's schedule prints."""
    out: set = set()
    for r in cluster:
        for fld in _IDENTITY_AREA_FIELDS:
            v = r.get(fld)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if v >= PLAN_REACH_AREA_MIN:
                    out.add(int(v))
            elif isinstance(v, str):
                out |= _page_figures(v)
    return out


# The non-warehouse area fields a brochure adds to the warehouse figure to print its headline
# TOTAL GIA. Used ONLY by _identity_figures_wide (the carousel), never by the plan slot.
_IDENTITY_OFFICE_FIELDS = ("officeAreaVal", "officeAreaSqM", "officeAreaSqm",
                           "gatehouseArea", "gatehouseAreaSqM")
GALLERY_FIGURE_TOL = 0.005   # 0.5% - a brochure headlines '338,000 sq ft' for a 338,308 unit


def _identity_figures_wide(cluster: list[dict]) -> set:
    """`_identity_figures` PLUS the TOTAL a brochure actually headlines - warehouse area plus
    each non-warehouse component, in the same unit.

    Why the carousel needs this and the plan slot does not. A record stores the schedule
    BROKEN DOWN (warehouseArea 318,826 + office 19,482); the brochure's title page and site
    overview print the TOTAL (338,308), and that total is the only figure on those pages. So
    `_identity_figures` alone reports 'this page names no unit I recognise' for a property's
    OWN title spread - measured on this corpus: the two best photographs in a deck (1173x729
    and 1173x488) sat on pages that print only the total.

    Kept SEPARATE from `_identity_figures` on purpose: that set feeds `plan_reach_pages`, where
    a single wrong bind puts a neighbour's drawing in a trace-less slot. Widening the identity
    set widens what a plan may reach, so the plan slot keeps the narrow, measured set and stays
    byte-identical; the carousel - which shows several photos a broker can eyeball - takes the
    recall."""
    base = _identity_figures(cluster)
    out = set(base)
    for r in cluster:
        for wfld in ("warehouseArea", "warehouseAreaSqM", "warehouseAreaSqm"):
            wv = _leading_figure(r.get(wfld))
            if wv is None:
                continue
            for ofld in _IDENTITY_OFFICE_FIELDS:
                ov = _leading_figure(r.get(ofld))
                if ov is None:
                    continue
                tot = wv + ov
                if tot >= PLAN_REACH_AREA_MIN:
                    out.add(int(tot))
    return out


def _leading_figure(v) -> int | None:
    """The leading integer of an area value ('19,482 sq ft total ...' -> 19482), or None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if v > 0 else None
    if isinstance(v, str):
        m = _AREA_NUM_RE.search(v)
        if m:
            raw = m.group(0).replace(",", "").replace(" ", "").rstrip(".")
            if raw.isdigit() and int(raw) > 0:
                return int(raw)
    return None


GALLERY_SCALE_BAND = 10.0   # a rival unit's size is within an order of magnitude of this one's


def _names_another_scheme(page_figs: set, own: set) -> bool:
    """Does this page print a figure that could be ANOTHER UNIT'S size?

    The carousel's neutrality test (a sole-claimant deck's unclaimed page that attributes
    itself to nobody is in reach) needs 'attributes itself to another scheme', and
    `_page_figures` is far too blunt for that on its own: it returns every integer >= 1000 on
    the page, which on real brochure pages means YEARS ('ambitions to 2030'), MONEY ('saving up
    to GBP 55,000 pa'), head counts ('2,500 international customers'), phone numbers and even
    ROAD numbers (A1065 -> 1065). Measured: those alone pushed two pages of genuine building
    photography out of reach on this corpus.

    A figure can only be a rival unit's schedule if it is of the same ORDER as this unit's own
    size, so the test is scale-banded around the property's largest own figure. Anything outside
    that band cannot be a comparable unit's area and is therefore not evidence of another
    scheme. A page printing a genuinely comparable area - a second unit on the same park - still
    reads as another scheme's and stays out, which is the case that matters."""
    if not page_figs:
        return False
    if not own:
        return True          # nothing to scale against: treat any figure as foreign evidence
    anchor = max(own)
    lo, hi = anchor / GALLERY_SCALE_BAND, anchor * GALLERY_SCALE_BAND
    return any(lo <= f <= hi for f in page_figs)


# The identity STRINGS a property is known by. Only ever used to compute what DISTINGUISHES two
# claimants of one deck from each other, so a shared word ("panattoni", "park", the city) can
# never survive the set difference and cannot accidentally attribute a page.
_IDENTITY_NAME_FIELDS = ("park", "name", "unit", "building", "scheme", "address", "postcode")
_TOKEN_RE = re.compile(r"[0-9a-z]+")
_NAME_TOKEN_MIN = 3        # 'mk450' discriminates; '6' does not, and would match any folio


def _page_tokens(text: str) -> set:
    """The page's lowercased alphanumeric tokens, >= _NAME_TOKEN_MIN characters."""
    return {t for t in _TOKEN_RE.findall(str(text or "").lower()) if len(t) >= _NAME_TOKEN_MIN}


def _cluster_name_tokens(cluster: list[dict]) -> set:
    """Every token of a property's identity strings."""
    out: set = set()
    for r in cluster:
        for fld in _IDENTITY_NAME_FIELDS:
            v = r.get(fld)
            if isinstance(v, str) and v.strip():
                out |= _page_tokens(v)
    return out


def _distinct_name_tokens(clusters: list[list[dict]], owners) -> dict:
    """{claimant index: the tokens of its name that NO OTHER claimant of this deck shares}.

    This is the NAME half of "whose page is this", and it exists because the figure half is
    blind to the commonest shape of a shared-deck spread: a page headed with one unit's name and
    a photograph, carrying no schedule table at all. Computing it as a set DIFFERENCE is what
    makes it safe without a dictionary of stop-words - "panattoni", "park", "milton", "keynes"
    and the city appear in both claimants' names and vanish; "mk450" and "mk345" survive.
    Claimants with no distinguishing token are dropped, so the caller can tell whether names
    discriminate on this deck at all."""
    toks = {i: _cluster_name_tokens(clusters[i]) for i in owners}
    out = {}
    for i in owners:
        others = set().union(*(toks[j] for j in owners if j != i)) if len(owners) > 1 else set()
        d = toks[i] - others
        if d:
            out[i] = d
    return out


def _figs_hit(page_figs: set, own: set, tol: float = GALLERY_FIGURE_TOL) -> set:
    """The subset of `own` a page prints, tolerating the ROUNDING a brochure headline uses
    ('391,000 sq ft' beside a schedule that totals 391,077). Exact equality is included by
    construction (a zero difference is inside any tolerance). Used by the carousel reach only;
    the plan slot keeps its exact `&` intersection."""
    if not page_figs or not own:
        return set()
    hits = set()
    for o in own:
        for f in page_figs:
            if abs(f - o) <= tol * max(abs(f), abs(o)):
                hits.add(o)
                break
    return hits


def _page_owner_by_figures(src: str, page: int, distinct: dict) -> object:
    """Which claimant of a MULTI-property deck this page belongs to, or None when the page does
    not settle it - in which case the page stays out of every property's reach.

    The evidence is the page's own SCHEDULE OF ACCOMMODATION. An industrial brochure spread
    prints the unit's warehouse / office / plot areas beside its drawing, and those figures are
    as specific as an identifier: `distinct` holds, per claimant, the area figures NO other
    claimant of this deck shares. A page qualifies for claimant i only when it prints at least
    one of i's figures and NOT ONE of anybody else's - so a park overview listing both units'
    totals, a page printing nothing, and any page that mixes the two are all refused.

    A TYPOGRAPHIC rule was tried first (whose name is printed biggest) and MEASURED WRONG on the
    corpus this was built against: on the MK345 spread the giant "MK345" title is vector outline
    art, so in the TEXT layer the only readable "MK" names print at 12.9pt for MK345 and 17.6pt
    for a small "MK450" context label - i.e. the rule would have bound BOTH units the same
    masterplan, which is precisely the identical-duplicate wrong-bind this corpus has produced
    before. Figures are read off the schedule the drawing is captioned with, not off a heading
    that may not be text at all."""
    if not isinstance(page, int):
        return None
    figs = _page_figures(IMG._page_plaintext(Path(src), page))
    if not figs:
        return None
    hits = {i: (figs & d) for i, d in distinct.items()}
    named = [i for i, h in hits.items() if h]
    if len(named) != 1:
        return None                       # nobody, or more than one -> the page does not say
    return named[0]


def plan_reach_pages(clusters: list[list[dict]], source_dir: Path) -> list[dict[str, set]]:
    """Per cluster, the EXTRA pages it may consider for the PLAN SLOT ONLY: pages of a deck it
    touches that NO cluster claims and NO cluster anchors, gated as described above. Parallel to
    `clusters`, same shape as `build_foreign_pages`. Never raises; an unreadable deck simply
    contributes nothing."""
    pages_per_cluster, anchor_owner, claims = _deck_ownership(clusters, source_dir)
    touched: dict[str, set] = {}             # deck -> the clusters that draw on it
    for i, pbs in enumerate(pages_per_cluster):
        for s in pbs:
            touched.setdefault(s, set()).add(i)
    out: list[dict[str, set]] = [dict() for _ in clusters]
    for s, owners in sorted(touched.items()):
        try:
            n = int((IMG.deck_media_facts(Path(s)) or {}).get("pages") or 0)
        except Exception:
            n = 0
        if n <= 0:
            continue
        spoken = {p for (ss, p) in claims if ss == s} | {p for (ss, p) in anchor_owner if ss == s}
        unclaimed = {p for p in range(n) if p not in spoken}
        if not unclaimed:
            continue
        figs = {i: _identity_figures(clusters[i]) for i in owners}
        if len(owners) == 1:
            i = next(iter(owners))
            own = figs[i]
            if not own:
                # NO figures known for this property: there is no other claimant to harm and
                # nothing better to go on, so the whole unclaimed set is in reach.
                out[i][s] = set(unclaimed)
                continue
            mine = {p for p in unclaimed if _page_figures(IMG._page_plaintext(Path(s), p)) & own}
            # ...and when the deck states this property's figures NOWHERE, it is a whole-park
            # DONOR deck that never identifies a page as this unit's: reach NOTHING. Measured -
            # on a 16-page park brochure covering seven other schemes, the widest-reaching
            # unclaimed page is a masterplan of a DIFFERENT part of the park, and binding it
            # put a neighbouring scheme's site plan on this card. Every other deck of that
            # corpus prints the property's own schedule on exactly its own spread, so this
            # costs nothing real and refuses precisely the case that was wrong.
            out[i][s] = mine
            continue
        # MULTI-CLAIMANT: the page must name its owner in its own SCHEDULE, unambiguously.
        distinct = {i: (f - set().union(*(figs[j] for j in owners if j != i)))
                    for i, f in figs.items()}
        distinct = {i: f for i, f in distinct.items() if f}
        if len(distinct) < 2:
            continue                          # nothing tells these claimants apart by figure
        for p in sorted(unclaimed):
            owner = _page_owner_by_figures(s, p, distinct)
            if owner is not None:
                out[owner].setdefault(s, set()).add(p)
    try:
        IMG.close_doc_cache()
    except Exception:
        pass
    return out


# --- CAROUSEL REACH over the pages NOBODY claimed ----------------------------------------- #
# The carousel had the SAME scope bug the plan slot had, and worse: its pages were the
# cluster's `page_no` UNION the reader's `__meta.image_pages`, and on this corpus the reader
# returned `image_pages` for only 4 of 17 properties. For the other 13 the carousel could see
# exactly ONE page of a 5-16 page brochure. Measured consequences: a 7-page deck whose pages 1
# and 2 hold 26 card-quality photographs shipped a ONE-image card; a 5-page deck shipped four
# 323x215 thumbnails off its anchor page while a 1173x729 photograph sat one page away, never
# CONSIDERED - not rejected, never looked at.
#
# The reach is built on the SAME ownership machinery as the plan slot (`_deck_ownership` /
# `_page_allowed`): a page any other property claims or anchors can never enter a carousel, so
# a shared two-unit deck and a whole-park donor deck are guarded exactly as before. It differs
# from `plan_reach_pages` in two deliberate ways, because the two slots carry different risk -
# the plan slot binds ONE drawing whose wrongness is invisible to the reader, while the
# carousel shows photographs the broker can sanity-check at a glance:
#   1. IDENTITY FIGURES ARE WIDENED (`_identity_figures_wide` + a 0.5% rounding tolerance),
#      because a property's own title spread prints the headline TOTAL, not the schedule
#      breakdown the record stores. See that function.
#   2a. ON A MULTI-CLAIMANT DECK A PAGE THAT NAMES NO CLAIMANT AT ALL IS PARK-LEVEL, and goes to
#      EVERY claimant of that deck. Approved by the broker: every claimant of a shared deck is
#      on this card grid, so the only subject an unattributable page can have is the thing they
#      share - their park. Attribution reads NAMES as well as figures now (see
#      _distinct_name_tokens), so a spread headed with one unit's name still goes to that unit
#      alone, a spread naming both still goes to neither, and a page printing a THIRD scheme's
#      unit-scale figure is still refused: an identifiable neighbour's building never reaches a
#      card. This does NOT extend to a whole-park DONOR deck (see the guard below) - there the
#      other schemes have no card at all, so "names no claimant" means "we cannot tell whose".
#   2b. ON A SOLE-CLAIMANT DECK A PAGE THAT NAMES NO OTHER SCHEME IS NEUTRAL, so it is in reach.
#      Nothing on such a page attributes it elsewhere; refusing it costs real photographs (a
#      deck's 'indicative internal CGI' spread carries no figures at all, and a sustainability
#      spread carries only a target year). 'Names another scheme' is scale-banded rather than
#      "prints any integer >= 1000" - see _names_another_scheme.
#      The plan slot refuses it, correctly - an unattributed masterplan page is precisely the
#      wrong-bind case it was burned by.
# The DONOR-DECK guard is kept and made explicit: if the deck states this property's figures on
# NO page at all, it is a whole-park brochure that never identifies a page as this unit's, and
# the reach is EMPTY - rule 2 included. MULTI-CLAIMANT decks are unchanged in kind: a page must
# still be settled decisively by one claimant's distinct figures.
def gallery_reach_pages(clusters: list[list[dict]], source_dir: Path,
                        park_level: list | None = None) -> list[dict[str, set]]:
    """Per cluster, the EXTRA pages it may draw CAROUSEL photos from: pages of a deck it
    touches that NO cluster claims and NO cluster anchors, gated as described above. Parallel
    to `clusters`, same shape as `build_foreign_pages` / `plan_reach_pages`. Never raises; an
    unreadable deck simply contributes nothing.

    `park_level` (optional, OUT): a list parallel to `clusters`, FILLED with the subset of each
    cluster's reach admitted under the SHARED-PARK rule ({src: {pages}}). Pure disclosure - the
    return value is unaffected and nothing reads it back - so `media_decisions.json` can tell an
    auditor which carousel pages are park-level (and therefore appear on a sibling card too)
    rather than unit-specific."""
    if park_level is not None:
        park_level[:] = [dict() for _ in clusters]
    pages_per_cluster, anchor_owner, claims = _deck_ownership(clusters, source_dir)
    touched: dict[str, set] = {}             # deck -> the clusters that draw on it
    for i, pbs in enumerate(pages_per_cluster):
        for s in pbs:
            touched.setdefault(s, set()).add(i)
    out: list[dict[str, set]] = [dict() for _ in clusters]
    for s, owners in sorted(touched.items()):
        try:
            n = int((IMG.deck_media_facts(Path(s)) or {}).get("pages") or 0)
        except Exception:
            n = 0
        if n <= 0:
            continue
        spoken = {p for (ss, p) in claims if ss == s} | {p for (ss, p) in anchor_owner if ss == s}
        unclaimed = {p for p in range(n) if p not in spoken}
        if not unclaimed:
            continue
        figs = {i: _identity_figures_wide(clusters[i]) for i in owners}
        page_figs = {p: _page_figures(IMG._page_plaintext(Path(s), p)) for p in range(n)}
        if len(owners) == 1:
            i = next(iter(owners))
            own = figs[i]
            if not own:
                # NO figures known for this property: there is no other claimant to harm and
                # nothing better to go on, so the whole unclaimed set is in reach.
                out[i][s] = set(unclaimed)
                continue
            # DONOR-DECK guard, evaluated over the WHOLE deck (strictly more evidence than the
            # unclaimed pages alone): a deck that never prints this unit's figures anywhere is
            # a whole-park brochure marketing other schemes - reach nothing.
            if not any(_figs_hit(page_figs.get(p) or set(), own) for p in range(n)):
                continue
            out[i][s] = {p for p in unclaimed
                         if _figs_hit(page_figs.get(p) or set(), own)   # names me
                         or not _names_another_scheme(page_figs.get(p) or set(), own)}
            continue
        # MULTI-CLAIMANT. Two questions per page, in this order: WHO does the page name, and -
        # when it names nobody - is it PARK-LEVEL imagery the claimants genuinely share?
        distinct = {i: (f - set().union(*(figs[j] for j in owners if j != i)))
                    for i, f in figs.items()}
        distinct = {i: f for i, f in distinct.items() if f}
        names = _distinct_name_tokens(clusters, owners)
        # Claimants that NOTHING tells apart (same figures, no distinguishing name token - three
        # identical units of one scheme in one brochure) used to reach NOTHING: the branch bailed
        # here and every sibling card went thin. The broker's call is the opposite: units of one
        # park in one brochure MAY share photographs, and nobody should go out of their way to
        # divide them. With `distinct` and `names` both empty no page can be attributed, so every
        # unclaimed page falls to the PARK-LEVEL branch below and reaches all of them, still
        # under the third-scheme guard.
        all_own = set().union(*(figs[i] for i in owners)) if owners else set()
        anchors = [max(figs[i]) for i in owners if figs[i]]
        for p in sorted(unclaimed):
            pf = page_figs.get(p) or set()
            toks = _page_tokens(IMG._page_plaintext(Path(s), p))
            # ATTRIBUTION, now reading NAMES as well as figures. A spread headed with the unit's
            # own name but no schedule table was previously invisible to this branch.
            named = {i for i, d in distinct.items() if _figs_hit(pf, d)}
            named |= {i for i, t in names.items() if t & toks}
            if named:
                # A page naming ONE claimant is that claimant's. A page naming SEVERAL used to be
                # refused for all of them ("not park-level, not theirs"), which starved exactly
                # the shared spread a multi-unit brochure leads with: the schedule of Units 1-3
                # beside the aerial. Sibling cards may share it; it goes to every claimant named.
                for i in named:
                    out[i].setdefault(s, set()).add(p)
                continue
            # PARK-LEVEL: the page names no claimant at all. On a shared deck EVERY claimant is
            # on this card grid, so the subject such a page can depict is the thing they share -
            # the park itself (an aerial, the entrance, landscaping, an amenity spread). The
            # broker's call is that this belongs on both cards rather than being wasted.
            # THE ONE THING THAT STILL REFUSES IT is evidence of a THIRD scheme: a printed figure
            # that is unit-scale for some claimant yet matches NO claimant's own schedule reads
            # as somebody else's unit ("Unit 3 - 200,000 sq ft"), and an identifiable neighbour's
            # building must never reach a card. (The floors - photo kind, 640x400, detail - still
            # apply downstream, so a park page's decorative wash is refused like any other.)
            if any(any(a / GALLERY_SCALE_BAND <= f <= a * GALLERY_SCALE_BAND for a in anchors)
                   and not _figs_hit({f}, all_own)
                   for f in pf):
                continue
            for i in owners:
                out[i].setdefault(s, set()).add(p)
                if park_level is not None:
                    park_level[i].setdefault(s, set()).add(p)
    try:
        IMG.close_doc_cache()
    except Exception:
        pass
    return out


def _plan_reject_norm(source_file, page_no=None) -> tuple[str, str]:
    """The two ack forms a plan rejection may take, normalised: a bare '<file>' (reject
    EVERY plan from that file) and '<file>#<1-based page>' (reject just that page).

    Keyed on (file, page) rather than on a property/cluster key ON PURPOSE: whether a page
    IS a site plan is a fact about the PAGE, so the answer stays valid when clustering,
    ids or areas change. A cluster-keyed ack would be orphaned by the next data edit -
    the same defect that orphans conflict_id (BACKLOG.md item B09)."""
    nm = Path(str(source_file or "")).name.strip().lower()
    if isinstance(page_no, int) and not isinstance(page_no, bool) and page_no >= 0:
        return nm, f"{nm}#{page_no + 1}"
    return nm, nm


def _plan_is_rejected(rejected, source_file, page_no=None) -> bool:
    """True when the visual-QA reviewer rejected this (file, page) as a site plan."""
    if not rejected:
        return False
    bare, keyed = _plan_reject_norm(source_file, page_no)
    return bare in rejected or keyed in rejected


def load_plan_rejected(path) -> set:
    """Read `plan_rejected` out of the visual-QA ack file into a normalised key set.

    Accepts '<file>', '<file>#<1-based page>', or {"source_file": ..., "page": <1-based>}.
    Best-effort like every other decision file: a missing/corrupt ack NEVER blocks a merge,
    it just means nothing is rejected."""
    out: set = set()
    try:
        p = Path(path)
        if not p.exists():
            return out
        loaded = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return out
    if not isinstance(loaded, dict):
        return out
    for entry in (loaded.get("plan_rejected") or []):
        try:
            if isinstance(entry, dict):
                nm = Path(str(entry.get("source_file") or "")).name.strip().lower()
                pg = entry.get("page")
                if not nm:
                    continue
                # the ack states a 1-BASED page (what the reviewer and the ledger see)
                out.add(f"{nm}#{int(pg)}" if isinstance(pg, (int, float)) else nm)
            elif isinstance(entry, str) and entry.strip():
                s = entry.strip().lower()
                if "#" in s:
                    f, _, pg = s.rpartition("#")
                    out.add(f"{Path(f).name.strip()}#{pg.strip()}")
                else:
                    out.add(Path(s).name.strip())
        except Exception:
            continue
    return out


def attach_media(cluster: list[dict], source_dir: Path, budget_kb: int,
                 image_cache: Path | None = None,
                 foreign_pages: dict[str, set] | None = None,
                 plan_offlimits: dict[str, set] | None = None,
                 plan_near_miss: list | None = None,
                 plan_rejected: set | None = None,
                 considered: dict | None = None,
                 plan_reach: dict[str, set] | None = None,
                 gallery_reach: dict[str, set] | None = None,
                 gallery_park_level: dict[str, set] | None = None
                 ) -> tuple[str, str | None, dict | None, dict | None, list, list]:
    """(photo_uri, plan_uri, photo_rec, plan_rec, tried_pages, gallery) for a merged property.

    Photo precedence (honours 'PPTX is the preferred IMAGE source'): a picture an
    extractor already embedded on a record first, else the source page's hero
    via the engine-agnostic ladder - PDF pages AND PPTX slides both harvest
    (slide records, e.g. vision transcriptions of a deck, used to silently
    degrade to the placeholder because only the PDF branch existed). The SITE
    PLAN comes from a record-level
    'plan' data URI (orchestrator-bound standalone file) first, else the page's
    plan picker. Combination rules per the broker's brief: photo found -> photo
    is the hero and the plan fills the plan slot (or stays absent); plan-only
    page -> the plan IS the hero AND the plan slot; neither -> placeholder.
    photo_rec/plan_rec is None when the placeholder / no plan was used.

    `considered` (optional, OUT): when a dict is passed it is FILLED with this cluster's whole
    media consideration set - per deck the pages it claimed, the foreign pages the anti-leak
    guard subtracted, the plan-offlimits and plan-rejected pages, plus the chosen hero/plan
    provenance, the gallery size and the near-miss list. PURE RECORDING: not one branch above
    reads it, so `canonical.json` and `built.html` bytes are identical whether it is passed or
    not (an eval pins that). It exists because "why does this card have one photo and no site
    plan" was previously unanswerable without re-running the merge under a debugger."""
    photo = plan = None
    photo_rec = plan_rec = None
    # An EXPLICIT hero pick (an interpretation sub-agent's __meta.heroRef) is never silently
    # replaced by the carousel's hero floor: the LLM proposes and the G-images gate DISPOSES,
    # and auto-repairing the pick here would take that verification away from the reviewer.
    # The floor still applies to every DETERMINISTICALLY bound hero, which is where the
    # 323x215-thumbnail-as-hero failure came from.
    hero_pinned = False
    tried: list[tuple] = []  # (source path, page/slide no, kind) - the placeholder audit trail
    embedded = [r for r in cluster
                if isinstance(r.get("photo"), str) and r["photo"].startswith("data:image/")]
    if embedded:
        embedded.sort(key=lambda r: IMG_RANK.get(_st(r), 9))
        photo, photo_rec = embedded[0]["photo"], embedded[0]
    # A REJECTED plan never binds, in ANY tier (the reviewer's judgement is durable across
    # rebuilds). Guarding all four tiers matters: clearing p.plan in canonical only survived
    # while merge happened to resume-skip, so the next extract edit re-bound the same wrong
    # image - observed re-binding three times in one session.
    bound_plans = [r for r in cluster
                   if isinstance(r.get("plan"), str) and r["plan"].startswith("data:image/")
                   and not _plan_is_rejected(plan_rejected,
                                             r.get("__meta", {}).get("source_file"),
                                             r.get("__meta", {}).get("page_no"))]
    if bound_plans:
        bound_plans.sort(key=lambda r: IMG_RANK.get(_st(r), 9))  # source-quality order, like the hero
        plan, plan_rec = bound_plans[0]["plan"], bound_plans[0]
    for r in cluster:
        if photo is not None and plan is not None:
            break
        meta = r.get("__meta", {})
        if meta.get("source_type") in ("pdf", "pptx") and isinstance(meta.get("page_no"), int):
            src = _resolve_source(source_dir, meta["source_file"])
            if not src:
                continue
            # route by the RESOLVED file's suffix, not the record's tag - a
            # vision agent's source_type slip must not send a .pdf to python-pptx
            kind = "pptx" if src.suffix.lower() == ".pptx" else "pdf"
            page_no = meta["page_no"]
            tried.append((src, page_no, kind))
            # LLM-PICKS-THE-HERO: when the interpretation sub-agent chose a heroRef (an int
            # index into this page's candidates_for_page list), bind THAT image - the
            # classifier + the G-images gate VERIFY it (a non-photo pick is blocked for
            # sign-off). heroRef None/absent falls through to the deterministic ladder below,
            # so a no-LLM / no-ref run still works. Same for planRef -> the plan slot. An
            # extractor-embedded record photo (set above) still wins first; a bound standalone
            # plan still wins the plan slot first - both are checked via `photo is None` /
            # `plan is None`. A null heroRef = 'no real photo on this page' STILL falls through
            # to the deterministic path; if that yields a non-photo the gate blocks it.
            href = meta.get("heroRef")
            pref = meta.get("planRef")
            if photo is None and isinstance(href, int):
                try:
                    h = IMG.embedded_by_index(src, page_no, href, budget_kb,
                                              cache_dir=image_cache)
                except Exception:
                    h = None
                if h:
                    photo, photo_rec = h, r
                    hero_pinned = True   # an EXPLICIT pick: never silently replaced below
                    # stash the locator so the caller's prov['photo'] reflects the LLM pick
                    meta.setdefault("prov", {})["photo"] = \
                        f"page {page_no + 1} (hero chosen by interpretation)"
            if (plan is None and isinstance(pref, int)
                    and not _plan_is_rejected(plan_rejected, src.name, page_no)):
                try:
                    pp = IMG.embedded_by_index(src, page_no, pref, budget_kb,
                                               cache_dir=image_cache)
                except Exception:
                    pp = None
                if pp:
                    plan, plan_rec = pp, r
                    meta.setdefault("prov", {})["plan"] = \
                        f"page {page_no + 1} (site plan chosen by interpretation)"
            # LLM-PICKS-THE-PLAN-PAGE: a SITE PLAN that is VECTOR line-art rendered into the
            # page (not an embedded raster) - planRef cannot reach it (pulled as an image it
            # goes solid black). The sub-agent names the page in __meta.plan_page (it sees a
            # per-page render thumbnail); merge RENDERS that page, ink-crops it and binds it
            # to the PLAN SLOT ONLY (a vector plan is never the card hero). Lenient verify
            # (bind unless an obvious photo / near-blank). Only when the plan slot is empty.
            ppage = meta.get("plan_page")
            # PER-PROPERTY SCOPE: a plan_page that the unique-claimant guard assigned to
            # ANOTHER property of this multi-property deck is OFF-LIMITS and must NOT bind - so
            # an erroneous or over-claimed plan_page can never pull a NEIGHBOUR'S vector plan
            # into this card. The HINT may name ANY page (not just this cluster's own claimed
            # pages), so it uses the BROAD plan_offlimits set, not the narrow foreign_pages.
            _plan_off = (plan_offlimits or {}).get(str(src), set())
            if (plan is None and isinstance(ppage, int) and not isinstance(ppage, bool)
                    and ppage >= 0 and ppage not in _plan_off
                    and not _plan_is_rejected(plan_rejected, src.name, ppage)):
                try:
                    rp = IMG.page_render_plan(src, ppage, budget_kb, cache_dir=image_cache)
                except Exception:
                    rp = None
                # TRUST the interpreter's visual pick: bind unless an INDEPENDENT LLM verify judged it
                # NOT a site plan (Phase 2, consulted below). No pixel-classifier veto here.
                if rp:
                    plan, plan_rec = rp, r
                    meta.setdefault("prov", {})["plan"] = \
                        f"page {ppage + 1} (site plan page render chosen by interpretation)"
            # DETERMINISTIC FALLBACK (heroRef None/absent or the bind failed): the existing
            # classifier-ranked ladder. Only runs when a slot is still empty.
            if photo is None or plan is None:
                try:  # an out-of-range page_no (vision-agent arithmetic) must
                    # degrade gracefully, never crash the merge
                    if kind == "pptx":
                        h, p = IMG.slide_hero_and_plan(src, page_no, budget_kb,
                                                       cache_dir=image_cache)
                    else:
                        h, p = IMG.page_hero_and_plan(src, page_no, budget_kb,
                                                      cache_dir=image_cache)
                except Exception:
                    continue
                if photo is None and h:
                    photo, photo_rec = h, r
                # Tier 5 (the deterministic classifier) is the tier that bound an INTERIOR
                # PHOTO as a site plan on a live run. The rejection is honoured here too;
                # the PHOTO is deliberately never affected - only the plan slot.
                if (plan is None and p
                        and not _plan_is_rejected(plan_rejected, src.name, page_no)):
                    plan, plan_rec = p, r
    if photo is None:
        photo, photo_rec = IMG.placeholder(), None
    # GALLERY (cap IMG.GALLERY_MAX, best-first): the photos for the carousel, gathered as a
    # CANDIDATE list here and composed into the final gallery by _compose_gallery below (which
    # also enforces the gallery[0] == hero invariant the images gate asserts).
    #
    # Candidate order IS the carousel's quality order, in two tiers:
    #   1. the property's OWN claimed pages (page_no U validated __meta.image_pages), best-first
    #      within the tier by the deck index's ranking;
    #   2. its CAROUSEL REACH (see gallery_reach_pages) - pages of the same deck that no other
    #      property claims or anchors and that the deck itself attributes to this property.
    # Claimed-before-reach means a property with enough of its own pages never draws on the
    # reach at all; only a card that would otherwise be thin reaches further.
    #
    # PAGE-SCOPED per record throughout, so a MULTI-PROPERTY deck contributes only THIS
    # property's pages, never a neighbour's. Deduped by URI bytes.
    cand: list[str] = []

    def _c_add(uri):
        if isinstance(uri, str) and uri.startswith("data:image/") and uri not in cand:
            cand.append(uri)

    for r in embedded:
        _c_add(r.get("photo"))
    # PAGES this property may draw carousel photos from: each record's page_no
    # UNION its validated __meta.image_pages (the LLM's "these pages show THIS
    # property" pick), keyed by the resolved source.
    # the SAME union the anti-leak guard computes (shared helper), so the harvester and
    # the guard can never diverge and leak a neighbouring property's page (audit S2-26).
    pages_by_src = _cluster_pages_by_src(cluster, source_dir)
    # per-source exclude map: the interpreter's __meta.exclude_refs (0-based page -> the candidate
    # indices it judged DECORATIVE / non-building via vision), unioned across this cluster's records
    # for each source. Absent/empty -> no exclusion, byte-identical to today. Honoured by SIG in
    # IMG.gallery_for_pages (never touches the hero, which is added separately above). (exclude_refs)
    excl_by_src: dict = {}
    for r in cluster:
        m = r.get("__meta", {}) or {}
        er = m.get("exclude_refs")
        if not isinstance(er, dict) or not er:
            continue
        s = _resolve_source(source_dir, m.get("source_file", ""))
        if not s:
            continue
        d = excl_by_src.setdefault(str(s), {})
        for pg, refs in er.items():
            try:
                p = int(pg)
            except (TypeError, ValueError):
                continue
            if isinstance(refs, list):
                d.setdefault(p, set()).update(
                    x for x in refs if isinstance(x, int) and not isinstance(x, bool) and x >= 0)
    def _harvest(src_str, allowed):
        if not allowed:
            return
        try:
            uris, _total = IMG.gallery_for_pages(Path(src_str), sorted(allowed), budget_kb,
                                                 image_cache,
                                                 exclude_by_page=excl_by_src.get(src_str))
        except Exception:
            uris = []
        for uri in uris:
            _c_add(uri)

    gallery_reach_used: dict[str, set] = {}
    park_level_used: dict[str, set] = {}   # DISCLOSURE ONLY - the shared-park subset of the reach
    for src_str, pgs in sorted(pages_by_src.items()):
        # TIER 1 - the property's OWN claimed pages. The deterministic anti-leak guard
        # (computed once over ALL clusters) tells us which of these pages are FOREIGN
        # (owned/claimed by another property of the same deck); subtract them before
        # harvesting. None / absent -> no-op, so a cluster's own page_no is never foreign.
        # An EMPTY allowed set harvests nothing rather than falling through to the whole
        # deck (gallery_for_pages treats an empty page set as "whole deck" - never that
        # here). A cluster's own page_no is normally its own anchor (not foreign), so that
        # is a DEFENSIVE guard - if a clustering anomaly made two properties anchor the
        # same page it is foreign to both, and this prevents the empty-set whole-deck leak.
        _harvest(src_str, pgs - (foreign_pages or {}).get(src_str, set()))
    for src_str in sorted(pages_by_src):
        # TIER 2 - the CAROUSEL REACH: pages of this deck that NO property claims and NO
        # property anchors, admitted only where the deck itself attributes them to this
        # property (gallery_reach_pages). Subtracted by the SAME two guards as the claimed
        # pages, and by `plan_offlimits` too: unlike the claimed-page set (where the two are
        # disjoint by construction) this set is drawn from the whole deck, so the guard can
        # genuinely fire. Never a substitute for tier 1 - it only fills the slots tier 1 left.
        reach = ((gallery_reach or {}).get(src_str, set())
                 - (plan_offlimits or {}).get(src_str, set())
                 - (foreign_pages or {}).get(src_str, set()))
        if reach:
            gallery_reach_used[src_str] = set(reach)
            pl = (gallery_park_level or {}).get(src_str, set()) & reach
            if pl:
                park_level_used[src_str] = set(pl)
        _harvest(src_str, reach)
    # DETERMINISTIC RENDERED-PLAN FALLBACK (no plan_page hint, or the hint missed): scan the
    # property's OWN pages - the SAME per-property allowed set the gallery uses (pages_by_src
    # minus foreign_pages) so a neighbour's plan page can never bind on a multi-property deck -
    # render+classify each and bind the most plan-like (CONSERVATIVE: classify 'plan' AND a
    # balanced white fraction, never a photo/map/blank). Plan slot ONLY (never the hero). Runs
    # only when the plan slot is still empty; a no-plan property keeps an honest None (today's
    # behaviour). Cached per (source, page, budget) -> byte-deterministic resume.
    #
    # WHY THIS SUBTRACTS ONLY foreign_pages, AND NOT plan_offlimits - the asymmetry with Tier 3
    # is deliberate and closed, not an oversight. It was filed as a leak (B40) and is not one.
    # Both sets are projections of the SAME `_page_allowed` rule over the same ownership tuple
    # and differ only in DOMAIN: this loop iterates the cluster's OWN claimed pages, so
    # subtracting foreign_pages already leaves exactly the pages that SATISFY _page_allowed,
    # while plan_offlimits contains only pages that FAIL it. The two are therefore disjoint
    # here by construction and Tier 5 cannot bind a neighbour's page. Tier 3 needs the broader
    # set because an LLM plan_page HINT may name ANY page, not just this cluster's own.
    # Adding `allowed -= plan_offlimits` here is a provable no-op - and worse than useless: a
    # guard that can never fire implies the sets differ in that direction, which is how B40 got
    # filed in the first place.
    _nm_acc: list = []  # near-miss pages (a plan signal that a precision guard rejected)
    if plan is None:
        for src_str, pgs in sorted(pages_by_src.items()):
            allowed = pgs - (foreign_pages or {}).get(src_str, set())
            # PLAN-SLOT REACH (see plan_reach_pages): the pages of this deck that NO property
            # claims and NO property anchors, admitted only under the sole-claimant rule or a
            # decisive typographic name match. Unioned HERE and nowhere else - it is the plan
            # slot only, never the hero and never the carousel. Subtracted afterwards by the
            # SAME two guards as the claimed pages, and `plan_offlimits` is subtracted too:
            # unlike the claimed-page set (where the two are disjoint by construction, see the
            # note above) this set is drawn from the whole deck, so the guard can genuinely fire.
            allowed = allowed | ((plan_reach or {}).get(src_str, set())
                                 - (plan_offlimits or {}).get(src_str, set())
                                 - (foreign_pages or {}).get(src_str, set()))
            # A page the visual-QA reviewer REJECTED as a site plan must not be re-bound here
            # either. This was the one plan path of five with no ack check - and it is the tier
            # the incident report blames for binding an interior warehouse photo into the Site
            # Plan slot, so "reject it" failed to stick in exactly the place it was needed.
            # Filtering `allowed` rather than testing the result means the scan moves on to the
            # next-best page instead of giving up on the deck. (B04)
            if plan_rejected:
                allowed = {p for p in allowed
                           if not _plan_is_rejected(plan_rejected, Path(src_str).name, p)}
            if not allowed:
                continue
            _nm: list = []
            try:
                # the property's OWN schedule figures, so a park deck carrying a masterplan per
                # unit binds THIS unit's, not a neighbouring unit's (see images._plan_rank)
                uri, pno = IMG.best_plan_page_render(Path(src_str), sorted(allowed),
                                                     budget_kb, image_cache, near_miss=_nm,
                                                     own_figures=_identity_figures(cluster))
            except Exception:
                uri, pno = None, None
            for _e in _nm:
                _e["file"] = Path(src_str).name
                _nm_acc.append(_e)
            if uri:
                plan = uri
                plan_rec = next((r for r in cluster
                                 if _resolve_source(source_dir,
                                                    (r.get("__meta", {}) or {}).get("source_file", ""))
                                 and str(_resolve_source(source_dir,
                                                         r["__meta"]["source_file"])) == src_str), None)
                if plan_rec is not None:
                    plan_rec.get("__meta", {}).setdefault("prov", {})["plan"] = \
                        (f"page {pno + 1} (site plan page render, detected)"
                         if isinstance(pno, int) else "site plan page render (detected)")
                break
        if plan is None and plan_near_miss is not None and _nm_acc:
            plan_near_miss.extend(_nm_acc)
    photo, gallery, promoted = _compose_gallery(photo, cand, hero_pinned=hero_pinned)
    if promoted:
        # The bound hero failed the carousel's own floors (a 323x215 thumbnail off an anchor
        # page whose deck holds a 1173x729 photograph two pages away) and a better image was
        # promoted in its place. Re-point the provenance at the record that actually supplies
        # it, so the ledger keeps naming the right deck.
        new_rec, new_page = _locate_uri(cluster, source_dir, promoted, budget_kb, image_cache)
        if new_rec is not None:
            photo_rec = new_rec
            if isinstance(new_page, int):
                new_rec.get("__meta", {}).setdefault("prov", {})["photo"] = \
                    f"page {new_page + 1} (carousel-quality photo, promoted from the deck)"
    if considered is not None:
        _record_considered(considered, source_dir, pages_by_src, foreign_pages, plan_offlimits,
                           plan_rejected, photo, photo_rec, plan, plan_rec, gallery, _nm_acc,
                           excl_by_src, plan_reach, gallery_reach_used, promoted,
                           park_level_used)
    return photo, plan, photo_rec, plan_rec, tried, gallery


def _compose_gallery(photo, candidates, max_n: int = None, hero_pinned: bool = False) -> tuple:
    """(hero, gallery, promoted_uri) from the bound hero + the ordered candidate list.

    Three jobs, all of which have to happen in ONE place or they contradict each other:
      * the carousel carries only CARD-QUALITY PHOTOGRAPHS - every candidate must clear
        IMG.gallery_admissible (decorative graphics, plans/maps that duplicate the Site Plan
        slot, and thumbnail-scale rasters are dropped);
      * `gallery[0] == hero` - the invariant the images gate asserts and the template's
        carousel relies on;
      * THE HERO IS HELD TO THE SAME FLOORS. A DETERMINISTICALLY bound hero that fails them is
        REPLACED by the best admissible candidate rather than dragging a thumbnail onto the
        card and into the carousel. (The G-images gate already blocks a non-PHOTO hero; it has
        no view of RESOLUTION, which is how four 323x215 images shipped on a client card.)
        `hero_pinned` exempts an EXPLICIT pick - an interpretation sub-agent's heroRef - from
        the replacement: that pick exists to be VERIFIED by the blind G-images reviewer, and
        auto-repairing it here would quietly remove the thing the reviewer is there to catch.
    A property with no admissible candidate at all keeps its bound hero and a 1-item gallery -
    a card never loses its only image, and the placeholder path is untouched."""
    if max_n is None:
        max_n = IMG.GALLERY_MAX
    hero_ok = (isinstance(photo, str) and photo.startswith("data:image/")
               and (hero_pinned or IMG.uri_gallery_admissible(photo)))
    ok = [u for u in candidates if u == photo or IMG.uri_gallery_admissible(u)]
    promoted = None
    if not hero_ok:
        better = next((u for u in ok if u != photo), None)
        if better is not None:
            promoted = better
            photo = better
    gallery = [photo] + [u for u in ok if u != photo]
    if not hero_ok and promoted is None:
        gallery = [photo]          # nothing admissible anywhere: keep the honest single image
    return photo, gallery[:max_n], promoted


def _locate_uri(cluster, source_dir, uri, budget_kb, image_cache):
    """(record, 0-based page) that supplies `uri`, by looking it up in each of the cluster's
    deck indexes. Only ever called on the rare hero-promotion path. (None, None) when the URI
    came from somewhere with no page (an extractor-embedded record photo is matched directly)."""
    for r in cluster:
        if r.get("photo") == uri:
            return r, (r.get("__meta", {}) or {}).get("page_no")
    for r in cluster:
        m = r.get("__meta", {}) or {}
        if m.get("source_type") not in ("pdf", "pptx"):
            continue
        s = _resolve_source(source_dir, m.get("source_file", ""))
        if not s:
            continue
        try:
            idx = IMG._deck_photo_index(Path(s), budget_kb, image_cache)
        except Exception:
            continue
        for e in idx:
            if e.get("uri") == uri:
                return r, e.get("page")
    return None, None


def _slot_prov(rec: dict | None, slot: str) -> dict | None:
    """Where a bound hero/plan came FROM, as {source_file, page, locator} - read off the record
    merge actually bound, so the recording cannot drift from the binding."""
    if not isinstance(rec, dict):
        return None
    meta = rec.get("__meta", {}) or {}
    return {"source_file": meta.get("source_file"),
            "page": meta.get("page_no"),
            "locator": (meta.get("prov", {}) or {}).get(slot)}


def _record_considered(out: dict, source_dir, pages_by_src, foreign_pages, plan_offlimits,
                       plan_rejected, photo, photo_rec, plan, plan_rec, gallery, near_miss,
                       excl_by_src, plan_reach=None, gallery_reach=None, promoted=None,
                       park_level=None) -> None:
    """Fill `out` with ONE cluster's media consideration set. PURE RECORDING - no caller branch
    reads it, so it cannot change a single byte of the dataset.

    The question it answers is the one no artefact could answer before: for THIS property, which
    deck pages were in reach, which were taken away by which rule, what was bound, and what was
    never looked at. Every set here is the SAME object the harvest itself used (`pages_by_src`,
    `foreign_pages`, `plan_offlimits`, `plan_rejected`, `exclude_refs`), never a re-derivation,
    so the record cannot disagree with what happened."""
    decks: dict = {}
    for src_str, pgs in sorted((pages_by_src or {}).items()):
        name = Path(src_str).name
        claimed = sorted(int(p) for p in pgs)
        foreign = sorted(int(p) for p in ((foreign_pages or {}).get(src_str, set()) & set(pgs)))
        offl = sorted(int(p) for p in (plan_offlimits or {}).get(src_str, set()))
        rej = sorted(p for p in claimed
                     if _plan_is_rejected(plan_rejected, name, p))
        excl = {str(k): sorted(v) for k, v in sorted((excl_by_src or {}).get(src_str, {}).items())}
        # pages nobody claimed that the PLAN SLOT could additionally reach (plan_reach_pages)
        reach = sorted(int(p) for p in ((plan_reach or {}).get(src_str, set())
                                        - set(offl) - set(foreign)))
        # pages nobody claimed that the CAROUSEL could additionally reach (gallery_reach_pages),
        # already net of the same two guards where it was applied
        greach = sorted(int(p) for p in (gallery_reach or {}).get(src_str, set()))
        # ...and the subset of those admitted because the page names NO claimant of a SHARED
        # deck, i.e. park-level imagery this property's sibling card carries too. Disclosure:
        # an auditor can see at a glance which carousel pages are park-level, not unit-specific.
        plevel = sorted(int(p) for p in (park_level or {}).get(src_str, set()))
        decks[name] = {
            "path": src_str,
            "claimed": claimed,
            "foreign": foreign,
            # what the harvest could ACTUALLY read: the claim minus the anti-leak subtraction,
            # plus the plan-slot reach and the carousel reach over the pages no property claimed
            "looked": sorted(set(p for p in claimed if p not in set(foreign))
                             | set(reach) | set(greach)),
            "claimed_looked": [p for p in claimed if p not in set(foreign)],
            "plan_reach": reach,
            "gallery_reach": greach,
            "park_level_reach": plevel,
            "plan_offlimits": offl,
            "plan_rejected": rej,
            "exclude_refs": excl,
        }
    out.update({
        "decks": decks,
        "hero": {"bound": bool(photo_rec is not None),
                 "placeholder": bool(photo_rec is None),
                 "from": _slot_prov(photo_rec, "photo"),
                 # the bound hero failed the carousel floors and a better image took its place
                 "promoted": bool(promoted)},
        "plan": {"bound": bool(plan), "from": _slot_prov(plan_rec, "plan")},
        "gallery": len(gallery or []),
        "near_miss": list(near_miss or []),
    })


def prewarm_images(all_records, source_dir, image_cache, budget_kb,
                   seconds: float = 30.0, workers: int | None = None,
                   max_rounds: int = 4) -> tuple:
    """Warm the image cache merge needs, in PARALLEL and TIME-BOUNDED, so the slow
    raster+compress harvest happens up front across CPUs instead of serially inside merge
    (which then runs as cache hits and finishes in one shell window). Each unit writes its
    own atomic cache, so a budget/kill exit loses at most the unit in flight - a re-run
    continues. Returns (done_units, total_units). Pure accelerator: identical cache bytes,
    so merge output is unchanged.

    A20 ONE PASS SHOULD FINISH THE CORPUS. The two unit phases used to run exactly once, so any
    unit left uncached by that single pass made the function report a partial count and hand the
    operator another pass to run - a whole extra shell round-trip that re-walks intake and
    validation, for work the remaining budget could often have completed. They now repeat until
    `done == total` or a round banks nothing, which is also what lets a unit that a round's own
    tally missed (prewarm deliberately does not JOIN its workers, so an in-flight unit can land
    its atomic cache moments after the round returns) be counted rather than re-run.

    `max_rounds` BOUNDS THAT LOOP so a permanently failing unit - a corrupt page, a converter that
    never succeeds - cannot spin: it can never be counted done, and without a cap "repeat until
    done" is "repeat forever". Keyword with a default, because run.py owns the call site.

    THE WALL-CLOCK DEADLINE IS UNCHANGED AND IS STILL THE SAFETY VALVE. It is computed ONCE, for
    the whole call, so looping cannot spend a second more than `seconds` allows: once the budget is
    gone every `_run` returns immediately, the round banks nothing, and the no-progress break ends
    the loop on the spot. The rounds are for converging INSIDE the budget, never for extending it,
    and the operator still raises the budget with exactly the same knobs as before
    (CBRE_PREWARM_SECONDS -> the caller's `seconds`, CBRE_IMAGE_WORKERS -> `workers`)."""
    import os
    import time
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures import TimeoutError as _FTimeout
    if image_cache is None:
        return (0, 0)
    cache_str = str(image_cache)
    decks: dict = {}                 # resolved deck path -> suffix
    page_units: list = []            # per-record hero/slidehero specs
    for r in all_records:
        m = r.get("__meta", {})
        if m.get("source_type") in ("pdf", "pptx") and isinstance(m.get("page_no"), int):
            s = _resolve_source(source_dir, m.get("source_file", ""))
            if not s:
                continue
            decks.setdefault(str(s), s.suffix.lower())
            kind = "slidehero" if s.suffix.lower() == ".pptx" else "hero"
            page_units.append((kind, str(s), m["page_no"], budget_kb, cache_str))
    geom_units: list = []            # per-(deck,page) gallery + geometry (the whole-deck scans)
    # A20: the pages a deck has that this prewarm deliberately does NOT enumerate. They are
    # counted into `total` but never into `done`, so a deck longer than the cap can never report
    # as complete. The alternative - counting only the capped pages - made `total` a statement
    # about how much this function chose to look at, and `done == total` then licensed the
    # caller's "complete" message for a corpus whose later pages had never been examined at all.
    # An accelerator may skip work; a completeness figure may not misreport what it skipped.
    uncounted = 0
    for s_str, sfx in decks.items():
        s = Path(s_str)
        try:
            pages = (len(list(IMG._get_pptx(s).slides)) if sfx == ".pptx"
                     else IMG._get_doc(s).page_count)
        except Exception:
            pages = 0
        n = min(pages, PREWARM_MAX_DECK_PAGES)
        per_page = 1 if sfx == ".pptx" else 2   # gidxpage, plus placedpage for a PDF
        uncounted += max(0, pages - n) * per_page
        for p in range(n):
            geom_units.append(("gidxpage", s_str, p, budget_kb, cache_str))
            if sfx != ".pptx":       # PPTX has no pdfplumber geometry tier
                geom_units.append(("placedpage", s_str, p, 0, cache_str))
    IMG.close_doc_cache()            # release parent PDF handles before forking workers
    all_units = geom_units + page_units
    total = len(all_units) + uncounted
    if not all_units:                # nothing to warm at all (the historic `total == 0` case)
        return (0, 0)
    if workers is None:
        env = 0
        try:
            env = int(os.environ.get("CBRE_IMAGE_WORKERS") or 0)
        except ValueError:
            env = 0
        workers = env or min(os.cpu_count() or 1, 8)
    workers = max(1, workers)
    deadline = time.monotonic() + max(1.0, seconds)

    def _prebatch_geometry(specs):
        # SERIAL/fallback only: warm each deck's pdfplumber GEOMETRY with ONE deck-wide open
        # (via _placed_layout) instead of one open per placedpage unit (and per hero unit that
        # reads geometry). _placed_layout writes each page's .placedpage.json exactly as
        # _placed_page would, so the per-unit calls then all hit the cache -> byte-identical
        # caches, merge output unchanged. The parallel path cannot share a handle across
        # processes, so this is scoped to the serial branches only. (#20)
        seen: set = set()
        for spec in specs:
            if spec[0] == "placedpage" and spec[1] not in seen:
                seen.add(spec[1])
                if time.monotonic() > deadline:
                    return
                try:
                    IMG._placed_layout(Path(spec[1]), spec[4])
                except Exception:
                    pass

    def _run(units):
        todo = [u for u in units if not IMG._unit_cached(u)]
        if not todo or time.monotonic() > deadline:
            return
        if workers <= 1:             # serial, no process pool (workers=1 opt-out / test path)
            _prebatch_geometry(todo)  # #20: one deck-wide geometry open, not one per page
            for u in todo:
                if time.monotonic() > deadline:
                    break
                IMG._prewarm_unit(u)
            return
        pool_ok = True
        # THE BUDGET MUST BOUND WALL TIME. Two leaks made `seconds` advisory only:
        #   (1) as_completed(futs) with NO timeout only yields when a future COMPLETES, so the
        #       deadline below was never TESTED while every in-flight unit was slow; and
        #   (2) `break` left the `with` block, whose __exit__ calls shutdown(wait=True) and
        #       JOINS every still-running worker (the wait=False/cancel_futures call only ever
        #       cancelled units that had not started).
        # Measured with the old idiom: a 2.0s budget took 12.2s. Worst case was far uglier - a
        # `slidehero` unit shells out to soffice with timeout=180 and no cross-worker locking, so
        # N workers each convert the SAME pptx; the shell cap then killed the run before merge
        # was ever reached, and the converted PDF only lands on success, so the next round
        # started from zero. Now: an explicit try/finally that NEVER joins, plus a best-effort
        # terminate so a runaway converter cannot hold the process at interpreter exit either.
        ex = None
        try:
            ex = ProcessPoolExecutor(max_workers=workers)
            futs = [ex.submit(IMG._prewarm_unit, u) for u in todo]
            try:
                for f in as_completed(futs, timeout=max(0.1, deadline - time.monotonic())):
                    try:
                        f.result()
                    except Exception:
                        pool_ok = False  # a broken pool (restricted spawn/fork) -> serial-fill
                    if time.monotonic() > deadline:
                        break
            except _FTimeout:
                pass  # budget spent with units still in flight - exactly what the bound is for
        except Exception:
            pool_ok = False
        finally:
            if ex is not None:
                # STOP WAITING, but do NOT kill and do NOT join.
                #   * `wait=False, cancel_futures=True` cancels units that have NOT started and
                #     returns control immediately - that is what bounds the parent's wall time.
                #   * We deliberately do NOT terminate the in-flight workers. Prewarm is a pure
                #     accelerator whose units each write their OWN atomic cache file, so a unit
                #     allowed to finish BANKS work that merge would otherwise redo serially inside
                #     its own smaller window. Terminating them threw that work away, which made
                #     merge slower, made it miss the shell cap, and turned every miss into another
                #     kill/resume round - i.e. MORE bash, the opposite of the intent.
                #   * We also do not JOIN (the original bug): the parent proceeds to merge now.
                try:
                    ex.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
        if not pool_ok:              # no usable process pool -> finish serially in-process
            _prebatch_geometry(todo)  # #20: one deck-wide geometry open, not one per page
            for u in todo:
                if time.monotonic() > deadline:
                    break
                if not IMG._unit_cached(u):
                    IMG._prewarm_unit(u)

    # A20: repeat the two phases until the corpus is warm or a round banks nothing. The phase
    # ORDER is load-bearing and unchanged inside every round - geometry first so the hero units
    # read it warm instead of each re-deriving it (#20).
    #
    # The break on NO PROGRESS is what makes `max_rounds` a ceiling rather than a schedule: a
    # unit that cannot succeed (a corrupt page, a converter that always fails) leaves `done`
    # exactly where it was and the loop stops immediately, and so does a spent budget, because
    # every `_run` then returns at its own deadline check. So the common cases cost ONE extra
    # tally, not another pass over the corpus: round two's `todo` is empty and `_run` returns
    # without submitting anything.
    done = 0
    for _round in range(max(1, max_rounds)):
        _run(geom_units)             # phase 1: page-grained geometry + gallery (no herd)
        _run(page_units)             # phase 2: heroes (geometry now warm)
        _before, done = done, sum(1 for u in all_units if IMG._unit_cached(u))
        if done >= total or done <= _before:
            break
    return (done, total)


# THE POST-MERGE DERIVATIONS canonicalize() performs, one function each, so the repairs stage can
# re-run exactly the same rule (`rederive_after_repairs`, below) instead of carrying a second
# copy of it. Each returns the derived value or None; the caller decides whether to write it.
def _rent_pair_from_display(p: dict):
    """(annual numeric, unit) parsed from the warehouseRent DISPLAY string, annualising a monthly
    quote x12, accepted only inside its own convention's plausibility band; None when the text
    is absent, an unknown, or implausible. The unit is `rentUnit` when set, else the text's."""
    disp = p.get("warehouseRent")
    if not (isinstance(disp, str) and disp.strip() and not N.looks_unknown(disp)):
        return None
    unit = p.get("rentUnit") or N.rent_unit_of_text(disp)
    num = N.extract_first_number(disp)
    if num is not None and N.MONTHLY_RX.search(disp):
        num = round(num * 12, 2)
    lo, hi = N.rent_unit_band(unit)
    if num is None or not (lo <= num <= hi):
        return None
    return (num, unit)


def _office_rent_val_from(p: dict):
    """officeRentVal from the officeRent display string: same convention, band and x12 rule as
    the warehouse rent. None when absent, unknown or implausible."""
    odisp = p.get("officeRent")
    if not (isinstance(odisp, str) and odisp.strip() and not N.looks_unknown(odisp)):
        return None
    ounit = p.get("rentUnit") or N.rent_unit_of_text(odisp)
    onum = N.extract_first_number(odisp)
    if onum is not None and N.MONTHLY_RX.search(odisp):
        onum = round(onum * 12, 2)
    olo, ohi = N.rent_unit_band(ounit)
    if onum is None or not (olo <= onum <= ohi):
        return None
    return onum


# D5: every AREA MENTION in an officeArea string - a number and the unit printed beside it, if
# any. The number alternation accepts a thousands group split by a comma, a point or a single
# space ("9,681", "1.413", "12 500") but NOT an arbitrary run of spaced digits, so the two
# figures in "transport office 1 7,492" stay two figures (normalize_number, built for ONE
# number, would read them as 17,492). The unit alternation is the area vocabulary of
# normalize._SQFT_RX / _SQM_RX minus "psf", which is a RENT unit and never an office area.
_OFFICE_MENTION_RX = re.compile(
    r"(?P<num>\d{1,3}(?:[.,\u00a0\u202f ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
    r"\s*(?P<unit>sq\.?\s*ft\b|sqft\b|ft2\b|ft²|square\s+f[eo]+t\b"
    r"|sq\.?\s*m\b|sqm\b|m2\b|m²|square\s+met\w*)?", re.I)
# a bare number below this beside a unit-bearing figure is a floor count, a level, a room index
# ("over 2 floors", "transport office 2"), never an office area
_OFFICE_BARE_MIN = 100


def _office_area_parse(oa, record_unit: str | None = None) -> dict | None:
    """What `officeArea` says, read carefully enough to be trusted with arithmetic. (D5)

    Returns None when the text holds nothing an officeAreaVal could be (absent, an unknown, a
    '% of GLA' share, a RANGE, no figure at all), else a dict:
        {"value": float, "unit": the unit printed beside the CHOSEN figure or None,
         "note": how the figure was chosen when that needed saying, or None}
    or, when the string holds several figures and no single one is identifiably the total:
        {"value": None, "unit": None, "refused": True, "why": ..., "figures": [...]}

    THE DEFECT. The predecessor took the FIRST number of any non-unknown string. Where a reader
    shipped several stated office lines in one string that produced, on a live run:
        "899 sq m / 9,681 sq ft ground floor office; 880 sq m / 9,469 sq ft first floor; ..."
            -> 899.0, on a sq ft dashboard: a 27x understatement AND a sq m figure taken as sq ft;
        "11,829 sq ft (GF Offices); 11,807 sq ft (FF Offices)" -> 11,829 (the total is 26,208).
    The value-format gate did not fire (899 is not "bare"; its string carries units), the
    arithmetic gate did not fire (a too-SMALL office cannot inflate the GLA), and it reached the
    client pack, where a human reviewer found it. The same first-number read also mis-footed the
    dual-unit restatement "1,413 sq m / 15,213 sq ft": it returned 1,413 while `area_unit_of`
    on the whole string said sq ft, so the sq m figure shipped unconverted as sq ft.

    THE RULES, and why each stops where it does:
      1. ONE unit-bearing figure, or one figure and nothing else: it is the value, in its own
         unit. "2,500 sq ft", "1,413 sq m", "24230", "2,500 sq ft over 2 floors" - the common
         case is byte-identical to before. A bare number under `_OFFICE_BARE_MIN` beside a
         unit-bearing figure is a floor count or an index, not an area, and is ignored.
      2. A SINGLE figure RESTATED in two units ("1,413 sq m / 15,213 sq ft", "9,681 sq ft (899
         sq m)"): one mention per unit and the two agree within 1% (brochures round each side
         independently). The figure printed in the RECORD's own unit is taken, so no conversion
         is needed and the wrong-unit twin can never be picked; with no record unit the first
         is taken in its own unit and the alignment step converts it. The choice is noted.
      3. A LEADING TOTAL followed by its own breakdown ("24,230 (offices 20,000; gatehouse
         4,230)", "45,649 sq ft total non-warehouse area (offices ... 28,804; ... 1,711; ...)"):
         the first figure EQUALS the sum of the later figures in the same unit (or all bare),
         within 0.5% or one unit. That arithmetic identity is the only evidence that the first
         figure is the total rather than a part, and it is checked, never assumed. Noted.
      4. Anything else with several figures is REFUSED: a semicolon list of floors, a string
         restating each of three lines in two units, a total that does not reconcile with its
         parts. No figure is taken, none is invented, and the clauses are NOT summed - a sum
         assumes the clauses are disjoint parts of one total, and the Novus string above
         restates the SAME area in two units, so summing it would have been catastrophically
         wrong. The refusal names every figure so the operator can state the total by repair.
    The gate on a RANGE (T1) and on a '%' share is unchanged: neither has a single value."""
    if isinstance(oa, (int, float)) and not isinstance(oa, bool):
        return {"value": float(oa), "unit": None, "note": None} if oa > 0 else None
    if not (isinstance(oa, str) and oa.strip() and not N.looks_unknown(oa) and "%" not in oa):
        return None
    if N.is_range(oa):
        return None
    mentions: list = []          # (value, unit-or-None, printed)
    for m in _OFFICE_MENTION_RX.finditer(oa):
        val = N.normalize_number(m.group("num"))
        if val is None or val <= 0:
            continue
        u = N.area_unit_of(m.group("unit")) if m.group("unit") else None
        mentions.append((float(val), u, m.group(0).strip()))
    if not mentions:
        return None
    unit_bearing = [x for x in mentions if x[1]]
    bare = [x for x in mentions if not x[1]]
    rec_u = str(record_unit or "").strip().lower() or None

    def _close(a: float, b: float, tol: float) -> bool:
        return abs(a - b) <= max(1.0, tol * max(abs(a), abs(b)))

    if not unit_bearing:
        if len(bare) == 1:
            return {"value": bare[0][0], "unit": None, "note": None}
        if _close(bare[0][0], sum(x[0] for x in bare[1:]), 0.005):
            return {"value": bare[0][0], "unit": None,
                    "note": (f"the leading figure {bare[0][2]} is the total: the "
                             f"{len(bare) - 1} figures after it sum to it exactly")}
        return {"value": None, "unit": None, "refused": True,
                "figures": [x[2] for x in mentions],
                "why": (f"the text holds {len(mentions)} figures and none is identifiably the "
                        f"total (the first is not the sum of the rest)")}
    big_bare = [x for x in bare if x[0] >= _OFFICE_BARE_MIN]
    if len(unit_bearing) == 1 and not big_bare:
        v, u, _ = unit_bearing[0]
        return {"value": v, "unit": u, "note": None}
    units = {x[1] for x in unit_bearing}
    # rule 2: one figure restated in two units
    if len(units) == 2 and len(unit_bearing) == 2 and not big_bare:
        (v1, u1, p1), (v2, u2, p2) = unit_bearing
        f = N.area_factor(u1, u2)
        if f is not None and _close(v1 * f, v2, 0.01):
            pick = next((x for x in unit_bearing if x[1] == rec_u), unit_bearing[0])
            return {"value": pick[0], "unit": pick[1],
                    "note": (f"one figure restated in two units ({p1} / {p2}); the "
                             f"{pick[1]} figure was taken"
                             + ("" if pick[1] == rec_u else
                                " (the record states no area unit, so the first was taken "
                                "in its own unit)"))}
    # rule 3: a leading total whose later figures (same unit, or bare) sum to it
    lead = mentions[0]
    if lead[1] is not None:
        rest = mentions[1:]
        # a small bare number after the total is an index or a floor count, not a part
        parts = [x for x in rest if x[1] or x[0] >= _OFFICE_BARE_MIN]
        if len(parts) >= 2 and all(x[1] in (None, lead[1]) for x in parts) \
                and _close(lead[0], sum(x[0] for x in parts), 0.005):
            return {"value": lead[0], "unit": lead[1],
                    "note": (f"the leading figure {lead[2]} is the total: the {len(parts)} "
                             f"figures after it sum to it exactly")}
    return {"value": None, "unit": None, "refused": True,
            "figures": [x[2] for x in mentions],
            "why": (f"the text holds {len(mentions)} figures"
                    + (f" in {len(units)} units" if len(units) > 1 else "")
                    + " and none is identifiably the total: it was not summed (the clauses "
                      "may restate one area or overlap) and no single figure was taken")}


def _office_area_val_from(p: dict):
    """officeAreaVal from officeArea, in the TEXT'S OWN unit: a positive number as a float, or
    the ONE figure `_office_area_parse` can stand behind. None when the text is absent, an
    unknown, a '% of GLA' phrasing, a range - or several figures with no identifiable total
    (D5: the field then ships absent and main() discloses the refusal; see `_office_area_parse`
    for the rules). The record's own `areaUnit` is passed so a figure restated in two units is
    taken in the unit the dataset already uses."""
    r = _office_area_parse(p.get("officeArea"), _record_area_unit(p))
    if r is None or r.get("value") is None:
        return None
    return r["value"]


def _expansion_park_val_from(p: dict):
    """expansionParkVal from expansionPark: a number of at least 1,000 (below that the text is a
    phase count or a phrase, not an area). None otherwise."""
    if p.get("expansionPark") is None:
        return None
    v = N.normalize_number(p["expansionPark"])
    return v if v is not None and v >= 1000 else None


def canonicalize(p: dict) -> dict:
    # country: schema caps it at 2-3 chars, so a spelled-out name from an agent
    # ("Spain", "España") is a FORMATTING issue merge owns - never a gate failure
    # (37 validate-data blocks in one real run came from exactly this)
    if p.get("country") and not N.looks_unknown(p.get("country")):
        p["country"] = N.country_iso(p["country"])
    # motorway: agents write a paragraph ("Junction 18/18A M5 2 miles to the south;
    # Junction 1 M49 4.5 miles to the north; M4/M5 interchange 10 miles to the north").
    # The card meta line and the compare cell have room for a locator, not a sentence, so
    # it is condensed to its road/junction/distance triples. Every token in the result is
    # verbatim from the source and the full sentence stays in the Source Ledger.
    if isinstance(p.get("motorway"), str):
        p["motorway"] = N.short_motorway(p["motorway"])[0]
    # rent: merge OWNS the display/numeric pair. When the numeric exists, the
    # display is ALWAYS regenerated from it (an agent-written "3,75 €/m²/mes"
    # string must not block the pair-consistency gate); when only a display
    # string exists, derive the numeric from it (annualising a monthly quote x12)
    # if it lands in its OWN convention's plausibility band - else keep the
    # honest text alone. Source units are KEPT: a '£8.50 psf' quote ships as
    # £/sq ft/yr (rentUnit), never converted to €/m² (FX would be invention).
    val = p.get("warehouseRentVal")
    if isinstance(val, (int, float)):
        # Recover the unit from the EXISTING display string when `rentUnit` is absent. An
        # agent-written "60 EUR/m2/año" states the currency and the basis - just not in the
        # field the renderer reads - and since rent_display no longer invents a default
        # (B06), regenerating straight from a missing rentUnit would DISCARD a unit the
        # source actually gave and render "60 (unit not stated)". The unit is only unknown
        # when neither field carries it. This mirrors the else-branch below, which has
        # always parsed the display text.
        _u = p.get("rentUnit")
        if not _u:
            _d = p.get("warehouseRent")
            if isinstance(_d, str) and _d.strip() and not N.looks_unknown(_d):
                _u = N.rent_unit_of_text(_d)
                if _u:
                    p["rentUnit"] = _u
        p["warehouseRent"] = N.rent_display(val, _u)
    else:
        _pair = _rent_pair_from_display(p)
        if _pair is not None:
            num, unit = _pair
            p["warehouseRentVal"] = num
            if unit:
                p["rentUnit"] = unit
            p["warehouseRent"] = N.rent_display(num, unit)
    # office rent NUMERIC (officeRentVal) for the total-rent split: parse the office
    # rent string in the SAME currency/per-area convention + plausibility band as the
    # warehouse rent (annualising a monthly quote x12). The office DISPLAY string is
    # left untouched; only a clean numeric is extracted. Never invented - absent stays absent.
    if not isinstance(p.get("officeRentVal"), (int, float)):
        onum = _office_rent_val_from(p)
        if onum is not None:
            p["officeRentVal"] = onum
    # office area NUMERIC (officeAreaVal) for total GLA: officeArea may be a number or
    # a string ('13576 sq ft'); extract the figure in the record's OWN area unit (the
    # minority-unit conversion in main() then aligns it to the dataset unit, like
    # warehouseArea). A '% of GLA' phrasing is skipped (not an absolute area).
    if not isinstance(p.get("officeAreaVal"), (int, float)):
        oan = _office_area_val_from(p)
        if oan is not None:
            p["officeAreaVal"] = oan
    # expansionParkVal companion
    if "expansionPark" in p and "expansionParkVal" not in p:
        v = _expansion_park_val_from(p)
        if v is not None:
            p["expansionParkVal"] = v
    # fill sentinels for every chrome-read key (honest unknowns, never invented)
    return C.fill_render_sentinels(p)


# ---------------------------------------------------------------------------- #
# C2 / F24: DERIVED TWINS, and re-derivation after the repairs stage.
#
# THE DEFECT, measured. `repairs` runs at stage 5, AFTER merge and AFTER enrichment, and writes
# straight into canonical. Several shipped values are DERIVED here at merge from a sibling field,
# and nothing re-derived them: a repair to the sibling left the derived value exactly as merge had
# computed it from the OLD sibling, or absent when the sibling had been absent. On one live run,
# every property whose office area came through merge carried a matching `officeAreaVal`; the
# two whose office area came from a repair carried None, so their modals printed a raw unit-less
# string and their Total GLA silently excluded the office. Every mechanical gate was green. The
# operator's workaround was a hand-written second repair per property setting the twin itself.
# Three blind reviewers filed this as three separate blocking findings.
#
# THE REGISTRY. Source field -> the field canonicalize() derives from it. This is the full set of
# post-merge derivations in this file that a repair can change the input of:
#   officeArea      -> officeAreaVal    (`_office_area_val_from`; then unit-aligned in main())
#   officeRent      -> officeRentVal    (`_office_rent_val_from`)
#   expansionPark   -> expansionParkVal (`_expansion_park_val_from`)
#   warehouseRentVal -> warehouseRent   (display regenerated from the numeric, `N.rent_display`)
#   warehouseRent   -> warehouseRentVal (numeric parsed from the display, `_rent_pair_from_display`)
# The rent pair is listed in BOTH directions because canonicalize() derives whichever side is
# missing, so a repair to either side strands the other. `rederive_after_repairs` treats the two
# as one consistency pair (see there). Two in-place normalisations of a field onto itself are
# re-run too but cannot be expressed as twins: `country` -> ISO code and `motorway` -> its
# condensed locator form. NOT re-run, deliberately: `regionCode` (merge derives a raw label only
# when regions are on; enrich then HARMONISES it against the workforce profiles, and a raw label
# re-derived after enrich would match no profile and block validate-data), `preBaked.statedTotal`
# (read from the source records' __meta, which a repair cannot touch), and
# `fill_render_sentinels` (run.py's `_coerce_repaired_scalars` already re-runs it).
# repairs.py reads this map to refuse an entry that repairs a source field without its twin
# unless the caller re-derives; run.py calls `rederive_after_repairs` right after the stage.
DERIVED_TWINS = {
    "officeArea": "officeAreaVal",
    "officeRent": "officeRentVal",
    "expansionPark": "expansionParkVal",
    "warehouseRentVal": "warehouseRent",
    "warehouseRent": "warehouseRentVal",
}
# A derived numeric within this of its recomputation is the SAME figure: a source's own rounding
# (a brochure printing both 1,413 sq m and 15,213 sq ft) must not make an untouched property
# "re-derive" on every pass. Same tolerance as GALLERY_FIGURE_TOL, for the same reason.
_TWIN_TOL = 0.005


def repaired_fields(report) -> dict:
    """{property id (STRING) -> the field names an APPLIED repair CHANGED}, read off the repairs
    report exactly as run.py's `_repairs_cleared` reads the cleared ones. Read, never inferred:
    it is what lets `rederive_after_repairs` know WHICH side of a pair a human touched. Any
    other shape yields {} and the re-derivation falls back to its consistency rules."""
    out: dict = {}
    for a in ((report or {}).get("applied") or []) if isinstance(report, dict) else []:
        if not isinstance(a, dict):
            continue
        names = {str(f) for f in (a.get("changed") or {}).keys()}
        if names:
            out.setdefault(str(a.get("property_id")), set()).update(names)
    return out


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _close(a, b) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(0.5, _TWIN_TOL * max(abs(a), abs(b)))


def _rederive_property(p: dict, changed: set | None) -> list[tuple[str, str]]:
    """Re-derive one property in place. Returns (derived field, what happened) pairs.

    `changed` is the set of fields a repair changed on THIS property, or None when the caller
    has no report. With it, a twin whose source was repaired is recomputed unconditionally
    (and withdrawn when the source no longer yields one). Without it, the rules are those a
    pass over UNTOUCHED properties must satisfy: fill a missing twin, refresh one that disagrees
    with its source beyond `_TWIN_TOL`, and never withdraw (a tracker can supply `officeAreaVal`
    with no `officeArea` beside it, and that is not staleness)."""
    done: list = []
    forced = changed or set()
    unit = _record_area_unit(p)

    def one_way(src: str, dst: str, derive) -> None:
        exp = derive(p)
        cur = _num(p.get(dst))
        if src == "officeArea" and exp is not None and isinstance(p.get("officeArea"), str):
            # the text's own unit vs the dataset's: merge aligns officeAreaVal to the dataset
            # unit on the source's footing, so this must too, or a repair typed as "1,413 sq m"
            # into a sq ft dataset would ship un-converted.
            # D5: the unit is the one printed beside the figure that was TAKEN, read from the
            # same parse that chose it. `area_unit_of` on the WHOLE string prefers sq ft, so on
            # "899 sq m (9,681 sq ft)" in a sq m dataset it would have called the chosen 899 a
            # sq ft figure and divided it by 10.76.
            _pr = _office_area_parse(p["officeArea"], unit)
            tu = (_pr or {}).get("unit") or None
            if tu and unit and tu != unit:
                f = N.area_factor(tu, unit)
                if f is None:
                    exp = None
                else:
                    exp = float(round(exp * f))
        if exp is None:
            if cur is not None and src in forced:
                p.pop(dst, None)
                done.append((dst, f"withdrawn: {src} was repaired and no longer yields a value"))
            return
        if cur is None or src in forced or not _close(exp, cur):
            if cur is not None and _close(exp, cur):
                return
            p[dst] = exp
            done.append((dst, f"{'set' if cur is None else 'refreshed from ' + repr(cur)} to "
                              f"{exp:g} (derived from {src} = {p.get(src)!r})"))

    one_way("officeArea", "officeAreaVal", _office_area_val_from)
    one_way("officeRent", "officeRentVal", _office_rent_val_from)
    one_way("expansionPark", "expansionParkVal", _expansion_park_val_from)

    # THE RENT PAIR is bidirectional, so direction has to come from the report. With it, the
    # repaired side is the source. Without it, a missing side is filled from the other, and two
    # present sides that disagree are REPORTED, never touched: canonicalize() would let the
    # numeric win, which is exactly the rule that would clobber a display-only repair.
    val = _num(p.get("warehouseRentVal"))
    disp = p.get("warehouseRent")
    disp_ok = isinstance(disp, str) and bool(disp.strip()) and not N.looks_unknown(disp)
    val_rep = "warehouseRentVal" in forced and "warehouseRent" not in forced
    disp_rep = "warehouseRent" in forced and "warehouseRentVal" not in forced
    if val_rep or (val is not None and not disp_ok and not disp_rep):
        if val is not None:
            new = N.rent_display(val, p.get("rentUnit"))
            if new != disp:
                p["warehouseRent"] = new
                done.append(("warehouseRent", f"regenerated as {new!r} from warehouseRentVal = {val:g}"))
        elif val_rep and disp_ok:
            p["warehouseRent"] = "tbd"
            done.append(("warehouseRent", "withdrawn: warehouseRentVal was repaired to nothing"))
    elif disp_rep or (disp_ok and val is None):
        pair = _rent_pair_from_display(p)
        if pair is not None:
            num, u = pair
            if not _close(num, val):
                p["warehouseRentVal"] = num
                if u:
                    p["rentUnit"] = u
                p["warehouseRent"] = N.rent_display(num, u)
                done.append(("warehouseRentVal", f"set to {num:g} (parsed from warehouseRent = {disp!r})"))
        elif disp_rep and val is not None:
            p["warehouseRentVal"] = None
            done.append(("warehouseRentVal", f"withdrawn: the repaired warehouseRent {disp!r} "
                                             f"carries no plausible figure"))
    elif changed is None and val is not None and disp_ok:
        pair = _rent_pair_from_display(p)
        if pair is not None and not _close(pair[0], val):
            done.append(("warehouseRent", f"INCONSISTENT with warehouseRentVal ({disp!r} reads as "
                                          f"{pair[0]:g}, the numeric is {val:g}); left alone: pass "
                                          f"the repairs report so the repaired side is known"))

    # in-place normalisations canonicalize() applies to a field ON ITSELF; both idempotent
    c = p.get("country")
    if isinstance(c, str) and c.strip() and not N.looks_unknown_code(c):
        iso = N.country_iso(c)
        if iso and iso != c:
            p["country"] = iso
            done.append(("country", f"normalised {c!r} -> {iso!r}"))
    m = p.get("motorway")
    if isinstance(m, str) and m.strip():
        short = N.short_motorway(m)[0]
        if short and short != m:
            p["motorway"] = short
            done.append(("motorway", f"condensed {m!r} -> {short!r}"))
    return done


def _load_props(canonical):
    """(document-or-None, properties list, path-or-None) for a path, a document dict, a bare
    property list or a single property dict."""
    if isinstance(canonical, (str, Path)):
        path = Path(canonical)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data, (data.get("properties") if isinstance(data, dict) else data) or [], path
    if isinstance(canonical, dict) and isinstance(canonical.get("properties"), list):
        return canonical, canonical["properties"], None
    if isinstance(canonical, list):
        return None, canonical, None
    if isinstance(canonical, dict):
        return None, [canonical], None
    return None, [], None


def rederive_after_repairs(canonical, changed: dict | None = None, ledger=None) -> list[str]:
    """Re-run every post-merge derivation whose input a repair may have changed.
    Returns human-readable lines naming what it re-derived, for the run log.

    `canonical` is the canonical document (a dict with `properties`), or a path to it (then the
    file is rewritten only when a byte moves, like run.py's `_coerce_repaired_scalars`), or a
    bare property list. `changed` is `repaired_fields(report)`; pass it whenever the report is
    to hand, because it is what decides direction for the rent pair and permits a withdrawal.
    Without it every rule is the conservative one (see `_rederive_property`).

    `ledger`, when given the Source Ledger path, does the two things the ledger needs after a
    repair: a provenance row for each twin re-derived here (copied from the twin's basis row and
    marked "derived from <basis>", the way merge attributes a derived companion at merge time,
    so the ledger has a row for `officeAreaVal` after a repair exactly as it does after a merge),
    and `retract_superseded_gap_rows`. Both idempotent across passes."""
    data, props, path = _load_props(canonical)
    lines: list = []
    derived_rows: list = []
    dirty = False
    for p in props:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id"))
        before = json.dumps(p, ensure_ascii=False, sort_keys=True, default=str)
        hint = (set(changed.get(pid) or ()) if isinstance(changed, dict) else None)
        for fld, what in _rederive_property(p, hint):
            lines.append(f"  - property {pid} {fld}: {what}")
            if fld in DERIVED_TWINS.values() and not what.startswith("INCONSISTENT"):
                derived_rows.append((pid, fld, p.get(fld)))
        if json.dumps(p, ensure_ascii=False, sort_keys=True, default=str) != before:
            dirty = True
    if dirty and path is not None:
        C.atomic_write_text(path, json.dumps(data, ensure_ascii=False))
    if ledger is not None:
        lines.extend(_ledger_after_rederive(Path(ledger), derived_rows))
    return lines


# ledger rows this module writes AFTER repairs carry this record_type, so a re-run replaces them
# (as run.py's `_ledger_append` replaces `repair` rows) instead of stacking a copy per pass
DERIVED_RECORD_TYPE = "derived"
SUPERSEDED_RECORD_TYPE = "superseded"


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    csv.field_size_limit(2 ** 31 - 1)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _write_ledger(path: Path, rows: list[dict]) -> None:
    """Rewrite the ledger in ledger.COLUMNS order, atomically, the way main() writes it."""
    import io
    import ledger as _ledger
    sio = io.StringIO()
    w = csv.DictWriter(sio, fieldnames=_ledger.COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    C.atomic_write_text(path, sio.getvalue())   # atomic + LF, exactly as main() writes it


def _ledger_after_rederive(path: Path, derived: list) -> list[str]:
    rows = _read_ledger(path)
    if not rows:
        return []
    lines: list = []
    if derived:
        keys = {(pid, fld) for pid, fld, _ in derived}
        rows = [r for r in rows
                if not ((r.get("record_type") or "").strip() == DERIVED_RECORD_TYPE
                        and (str(r.get("property_id")), r.get("field")) in keys)]
        for pid, fld, value in derived:
            basis = next((s for s, d in DERIVED_TWINS.items() if d == fld), None)
            if value is None:
                continue          # a withdrawal leaves no value to attribute; the removal is in the run log
            src_row = None
            if basis:
                cands = [r for r in rows if str(r.get("property_id")) == pid and r.get("field") == basis
                         and (r.get("source_type") or "").strip().lower() != "gap"]
                src_row = cands[-1] if cands else None   # the LATEST non-gap row is the live one
            rows.append({
                "property_id": pid, "record_type": DERIVED_RECORD_TYPE, "field": fld,
                "value": _short(value),
                "source_file": (src_row or {}).get("source_file") or "(derived)",
                "source_locator": ((f"{(src_row or {}).get('source_locator', '')} " if src_row else "")
                                   + f"(derived from {basis} after repairs)").strip(),
                "source_type": (src_row or {}).get("source_type") or "derived",
                "extractor": "merge.rederive_after_repairs",
                "confidence": (src_row or {}).get("confidence", ""),
                "conflict_note": "", "verified": (src_row or {}).get("verified", ""),
            })
            lines.append(f"  - ledger: property {pid} {fld}: provenance row written (derived from {basis})")
    lines.extend(retract_superseded_gap_rows(rows))
    _write_ledger(path, rows)
    return lines


def retract_superseded_gap_rows(ledger) -> list[str]:
    """Mark every gap row a later row SUPERSEDES; restore one whose superseder is gone. (F24)

    THE DEFECT. Merge writes a gap row ("value=tbd, absent in all sources, verified=no") for
    every chrome-read field no source stated. Repairs run later and append a row carrying the
    value with full provenance, and nothing touched the gap row, so the Source Ledger, whose
    whole purpose is to be authoritative, carried TWO rows for every repaired field and
    contradicted the dashboard on each of them. Measured on a live ledger: 5 of 5 repaired gap
    fields.

    MARKED, NOT DELETED, for three reasons. (1) The ledger is a client deliverable and reviewers
    re-derive from it: a row that vanishes between two runs is a silent edit to an audit trail,
    while a row that says SUPERSEDED and names its superseder is a visible, explicable one. (2)
    Resume skips merge when nothing upstream changed, so the ledger merge wrote is the only copy;
    a repair later deleted or refused would then leave the field with NO row at all, and
    G-honesty requires a gap row behind every sentinel. Marking is reversible: this function
    RESTORES a marked row whose superseder is gone, so the ledger always states the current
    truth. (3) It is a pure function of the ledger itself, so it is idempotent and needs no
    report: superseded iff a non-gap row exists for the same (property_id, field).

    What changes on a marked row: `record_type` (the column the xlsx shows and `_ledger_append`
    keys on) becomes "superseded", and `conflict_note` names the superseding row. `source_type`
    stays "gap" and `value` stays the sentinel, on purpose: every consumer that must ignore a gap
    row (trace-coverage, repairs.read_provenance, the source-count votes) already filters on
    `source_type == "gap"`, so a marked row is invisible to them exactly as it was before, and
    the row still records what merge knew at merge time.

    `ledger` is a path (read, marked, rewritten only when a row moved) or a list of rows (marked
    in place). Returns run-log lines."""
    path = Path(ledger) if isinstance(ledger, (str, Path)) else None
    rows = _read_ledger(path) if path is not None else list(ledger or [])
    live: dict = {}
    for r in rows:
        if (r.get("source_type") or "").strip().lower() != "gap":
            live[(str(r.get("property_id")), str(r.get("field")))] = r
    lines: list = []
    moved = False
    for r in rows:
        if (r.get("source_type") or "").strip().lower() != "gap":
            continue
        key = (str(r.get("property_id")), str(r.get("field")))
        sup = live.get(key)
        rt = (r.get("record_type") or "").strip()
        if sup is not None:
            note = (f"SUPERSEDED: written at merge, when no source stated this value; a later "
                    f"{(sup.get('record_type') or 'property')} row ({sup.get('source_file', '')}: "
                    f"{sup.get('source_locator', '')}) supplies {_short(sup.get('value'), 40)!r} with "
                    f"full provenance. Kept so the retraction is visible; NOT the live value.")
            if rt != SUPERSEDED_RECORD_TYPE or r.get("conflict_note") != note:
                r["record_type"] = SUPERSEDED_RECORD_TYPE
                r["conflict_note"] = note
                moved = True
                lines.append(f"  - ledger: property {key[0]} {key[1]}: gap row marked superseded by "
                             f"the {(sup.get('record_type') or 'property')} row")
        elif rt == SUPERSEDED_RECORD_TYPE:
            r["record_type"] = "property"
            if str(r.get("conflict_note") or "").startswith("SUPERSEDED:"):
                r["conflict_note"] = ""
            moved = True
            lines.append(f"  - ledger: property {key[0]} {key[1]}: gap row RESTORED, its superseding "
                         f"row is gone")
    if moved and path is not None:
        _write_ledger(path, rows)
    return lines


def load_hero(project_yaml: Path | None, properties: list[dict], default_date: str = "") -> dict:
    cfg = _load_yaml(project_yaml)
    client = (cfg.get("client") or {}).get("name") or "Client"
    market = cfg.get("market") or {}
    out = cfg.get("output") or {}
    region_label = market.get("region_label") or ""
    # compiled date: project.yaml wins; else the inputs' date (deterministic per
    # input set); wall-clock today only as the last resort
    compiled = out.get("compiled_date") or default_date or _dt.date.today().isoformat()
    # HERO COPY: carry ONLY what the broker authored. The eyebrow / headline / lede
    # DEFAULTS are no longer English literals here - they live in i18n.py as
    # hero_eyebrow / hero_title_html (v45 removed hero_lede_fmt) and are applied by
    # build_dashboard._hero_copy in the dashboard's own language. Two consequences,
    # both deliberate:
    #   * a BLANK value stays blank through merge and picks up the LOCALISED default at
    #     render time, so the largest text on the page is no longer English-only (it was
    #     English in all 12 supported languages);
    #   * a NON-BLANK value ships VERBATIM. The old composition
    #     (`eyebrow if "shortlist" in eyebrow.lower() else f"Property Shortlist · {eyebrow}"`)
    #     is GONE: that test was an ASCII substring probe, so a non-Latin eyebrow could
    #     never satisfy it and was force-prefixed with English. A broker who wants the
    #     prefix now writes the whole eyebrow.
    hero = {
        "topbar_meta": (f"{region_label} · {compiled}".strip(" ·")) or compiled,
        "eyebrow": market.get("eyebrow") or "",
        "title_html": market.get("title_html") or "",
        "footer_copyright": f"© {compiled[:4]} CBRE · {client} shortlist compiled {compiled}",
    }
    return hero


def _ws_norm(s) -> str:
    """Whitespace-normalise for the deterministic quote-verify (collapse runs,
    strip), so a copy-paste with reflowed spacing still matches the text layer."""
    return " ".join(str(s or "").split())


def _deck_text_hash(blocks) -> str:
    """Stable short hash of a deck's concatenated font_grouped_blocks text. The
    sub-agent's cached pick is accepted ONLY if this matches the stored text_hash,
    so editing the source deck invalidates a stale pick rather than reusing it."""
    import hashlib
    joined = "\n".join(b.get("text", "") for b in blocks)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _verified_photo_description(bsrc, entry):
    """Return (description, page_no_0based) from a sub-agent description pick ONLY
    if it passes the deterministic gate; else None. Gate: (a) the stored text_hash
    matches the deck's CURRENT font_grouped_blocks text (no stale pick after an
    edit) AND (b) the description_source_quote, whitespace-normalised, OCCURS
    verbatim in the cited page's text layer. A fabricated description physically
    cannot pass, so it can never reach canonical.json - the heuristic is the
    fallback at the call site."""
    if not isinstance(entry, dict):
        return None
    desc = entry.get("description")
    quote = entry.get("quote")
    if not desc or not quote:
        return None
    try:
        blocks = XP.font_grouped_blocks(bsrc)
    except Exception:
        return None
    if not blocks:
        return None  # raster/shim deck: no text layer to verify against -> heuristic
    want_hash = entry.get("text_hash")
    if want_hash and want_hash != _deck_text_hash(blocks):
        return None  # the deck changed since the pick was made -> reject (re-pick / heuristic)
    page = entry.get("page")
    nq = _ws_norm(quote)
    if not nq:
        return None
    # the quote must occur in the cited page's text (if a page is given), else any page
    if isinstance(page, int):
        page_text = " ".join(b.get("text", "") for b in blocks if b.get("page") == page)
        if nq in _ws_norm(page_text):
            return N.clean_value(str(desc)), max(page - 1, 0)
        return None
    whole = " ".join(b.get("text", "") for b in blocks)
    if nq in _ws_norm(whole):
        return N.clean_value(str(desc)), 0
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", nargs="+", required=True)
    ap.add_argument("--master-list", default="",
                    help="work/master_list.json - the user's answered scope sheet. Clusters "
                         "whose every record belongs to a row they marked No are dropped here "
                         "and named in the Gaps Report. Absent = every option is in scope.")
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--project-yaml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ledger")
    ap.add_argument("--language", default="", help="dashboard chrome language (Stage-0 Q3) "
                    "-> meta.language; the builder resolves it to the i18n table at render "
                    "time (per-key English fallback). Blank -> English.")
    ap.add_argument("--locale", default="", help="optional explicit BCP-47 locale "
                    "-> meta.locale (e.g. de-AT); blank -> the language's default region.")
    ap.add_argument("--ui-overrides", dest="ui_overrides", default="", help="Phase-2 FALLBACK "
                    "chrome translation cache (work/i18n/<code>.json) for a SUPPORTED-but-not-"
                    "bundled language. When it loads + is a non-empty dict, its EN-keyed entries "
                    "are baked into meta.ui_overrides (a leading _en_sha / any _* meta key and "
                    "any non-EN/DATA key are dropped) so render() reproduces the fallback from "
                    "canonical alone. Blank/absent/invalid -> meta.ui_overrides is NOT set "
                    "(byte-identical to the bundled/EN path).")
    ap.add_argument("--requirements", help="JSON file of client questionnaire requirements -> meta.requirements")
    ap.add_argument("--image-budget-kb", type=int, default=IMG.DEFAULT_BUDGET_KB)
    ap.add_argument("--image-cache", help="dir for the persistent hero-image cache "
                    "(re-runs reuse identical bytes instead of re-rastering/compressing)")
    ap.add_argument("--photo-map", help="JSON {match_key: brochure_relpath} of confident "
                    "sub-agent photo matches: a 0-record brochure's deck hero fills that "
                    "property's placeholder (P0-1)")
    ap.add_argument("--photo-descriptions", help="JSON {brochure_name: {description, page, "
                    "quote, text_hash}} of the photo-match sub-agent's per-brochure description "
                    "pick (verbatim deck prose). Accepted ONLY when the text_hash matches the "
                    "deck's current text AND the quote occurs verbatim in the cited page - a "
                    "deterministic gate so a hallucinated description can never enter a record. "
                    "Absent/empty/malformed/unverified -> best_description_in_deck is the offline "
                    "fallback (byte-identical to today).")
    ap.add_argument("--match-decisions", help="JSON {pair_id: 'same'|'different'|{verdict,reason}} "
                    "of the cross-source match sub-agent's grey-zone verdicts (run.py exit 10). "
                    "Resolves ONLY the ambiguous pairs; the deterministic auto/forbidden tiers are "
                    "unchanged and a forbidden pair never merges even on 'same'. Absent -> the "
                    "deterministic matcher is the offline fallback (byte-identical to today).")
    ap.add_argument("--field-decisions", help="JSON {conflict_id: {pick: '<label>', reason: '...'}} "
                    "of the cross-source VALUE-conflict sub-agent's picks (run.py exit 10, same "
                    "candidates file as --match-decisions). The fixed precedence is the DEFAULT; a "
                    "pick OVERRIDES it ONLY when it selects a given candidate value that PASSES the "
                    "field's plausibility gate (rent band / area > 0 / coord bounds) - a failing or "
                    "absent pick keeps precedence. Absent -> precedence is the offline fallback "
                    "(byte-identical to today).")
    ap.add_argument("--plan-rejected", dest="plan_rejected", default="",
                    help="visual-QA ack file (work/placeholder_audit_ack.json). Its "
                         "`plan_rejected` list names site plans the reviewer rejected, as "
                         "'<file>#<1-based page>' (or a bare '<file>', or "
                         "{source_file, page}); merge then binds NO plan from that page in "
                         "any tier and emits no plan ledger row for it.")
    ap.add_argument("--match-conflicts", help="JSON [str, ...] of ADVISORY grey-match disagreement "
                    "lines (the blind match verifier disagreed with the matching pass; run.py "
                    "computes them in pure Python). Folded verbatim into meta.conflicts -> the Gaps "
                    "'Source conflicts' section. Does NOT change clustering (the matching pass's "
                    "verdict already drove --match-decisions). Absent / empty -> no extra line "
                    "(byte-identical to today).")
    ap.add_argument("--answers", default="", help="the WORK DIR holding clarify_state.json - "
                    "answers to the clarification questions run.py asked (exit 13). A unit "
                    "confirmed by the broker is a SOURCE STATEMENT and fills areaUnit/rentUnit "
                    "with provenance; unlike --overrides it is allowed to, because it was asked "
                    "for and is attributed, not a blind correction. (B38)")
    ap.add_argument("--overrides", default="", help="JSON list of DURABLE manual corrections "
                    "(work/overrides.json). Applied to the pre-merge records AFTER extraction and "
                    "BEFORE clustering on every run, so a correction SURVIVES re-extraction "
                    "instead of being discarded with the derived work/extract records. Each entry "
                    "targets an EXISTING record by (source_file [, sheet+row | page_no]) and sets "
                    "an EXISTING canonical field: it can never create a property, a record or a "
                    "new field, and areaUnit/rentUnit are DENIED. Every applied correction emits "
                    "an explicit `override` ledger row (source_type='override') and lands in "
                    "meta.overrides -> the Gaps Report; an entry matching ZERO records, or "
                    "ambiguously MANY, applies NOTHING and is reported as stale/ambiguous on "
                    "stdout, in <work>/overrides_report.json and in the Gaps Report. "
                    "Absent / empty / malformed -> byte-identical to today.")
    args = ap.parse_args()

    all_records = []
    for f in args.records:
        all_records.extend(json.loads(Path(f).read_text(encoding="utf-8-sig")))

    # EMAIL ATTACHMENTS: cite the FILE, carry the EMAIL. A brochure that arrived stapled to an
    # offer email is extracted exactly like any other deck, so its records cite the attachment
    # and its page - which is right, because that is where the figure is printed, and a reader
    # checking the ledger must be able to open the cited file at the cited page. But the
    # attachment on its own is a filename with no history: the broker cannot tell who sent it,
    # when, or which thread it settles, and on a corpus where two agents both offered the same
    # park that is the difference between a current offer and a superseded one. So every record
    # from an attachment also carries __meta.from_email = {subject, date, file}, read from the
    # `.from_email.json` sidecar extract_email wrote beside the bytes. The sidecar is the source
    # of truth rather than a run artefact, so the link survives a deleted work dir and a
    # hand-run of this script.
    #
    # The index is keyed on the attachment's path relative to the inputs folder, and the
    # lookup lives in extract_email.from_email_for rather than here. Both halves matter: a
    # basename key made two emails that each attached "brochure.pdf" resolve to whichever
    # sidecar was read last, so one of the two got a confidently WRONG sending email in its
    # ledger locator. from_email_for resolves the bare name the extractors stamp, and returns
    # nothing at all when the name is genuinely ambiguous.
    _from_email, _EM = {}, None
    try:
        import extract_email as _EM   # noqa: F811
        _from_email = _EM.from_email_index(Path(args.source_dir))
    except Exception:
        _from_email, _EM = {}, None   # no sidecars, or no attachments: byte-identical to before

    def _fe_for(_source_file):
        if not _from_email or _EM is None:
            return None
        try:
            return _EM.from_email_for(_from_email, _source_file)
        except Exception:
            return None

    if _from_email:
        for _r in all_records:
            if not isinstance(_r, dict):
                continue
            _m = _r.get("__meta")
            if not isinstance(_m, dict):
                continue
            _fe = _fe_for(_m.get("source_file"))
            if _fe:
                _m["from_email"] = dict(_fe)

    for _r in all_records:            # v22 Phase 1: quarantine off-spec structures pre-merge
        _normalise_offspec(_r)
        _route_certifications(_r)     # B5: an EPC never ships as a BREEAM grade

    # DURABLE MANUAL CORRECTIONS (P1-4). Applied HERE - after extraction + _normalise_offspec and
    # BEFORE compute_file_quality / dominant_units / match.dedupe - because all three consume the
    # corrected values: dedupe is what makes a corrected city or park RE-JOIN the right cluster
    # (the live 12 -> 13 symptom), dominant_units is what counts a corrected figure, and
    # compute_file_quality is what ranks the source. Applying merely "before dedupe" would miss
    # the latter two.
    # B7: hand the guard the field names the records actually carry, so an override can reach any
    # field this dataset genuinely has - not only the ones a schema anticipated.
    _rec_fields = {k for r in all_records if isinstance(r, dict) for k in r if k != "__meta"}
    OVERRIDES, OV_INVALID = load_overrides(getattr(args, "overrides", "") or "",
                                           extra_fields=_rec_fields)
    OV_REPORT = apply_overrides(all_records, OVERRIDES)
    OV_REPORT["invalid"] = OV_INVALID
    _report_overrides(OV_REPORT, Path(args.out).resolve().parent / "overrides_report.json")

    # ANSWERED CLARIFICATIONS (B38). Same position and the same reasoning as the overrides
    # above - dominant_units and dedupe both consume a unit, so an answer has to land before
    # them. Distinct channel deliberately: `overrides.json` may never set areaUnit/rentUnit
    # (a blind correction to the record that tips the vote silently relabels the dataset),
    # whereas this is an ANSWER to a question the pipeline asked about a named source, carrying
    # its own provenance. Asked, answered, attributed - the opposite of silent.
    if getattr(args, "answers", ""):
        try:
            import clarify as _CQ
            _n_ans = _CQ.apply_answers(
                all_records, (_CQ.load_state(Path(args.answers)).get("answers") or {}))
            if _n_ans:
                print(f"  ({_n_ans} clarification answer(s) applied - each has a `prov` entry "
                      f"naming it as a confirmed unit, not a source reading)")
        except Exception as e:
            print(f"  (clarification answers not applied: {e})", file=sys.stderr)

    compute_file_quality(all_records)  # demote mostly-poor brochures in precedence
    area_unit, rent_unit = dominant_units(all_records)
    # AN ANSWERED DISPLAY UNIT BEATS THE VOTE (B49). dominant_units is a silent majority
    # count, which is the right DEFAULT but the wrong thing to do quietly on a genuinely mixed
    # corpus: a 20-15 split converts 15 figures by 10.76x on a convention nobody chose.
    # clarify.dataset_unit_questions asks in that case, and the broker's answer lands here.
    # Selection-only, exactly like clarify.apply_answers: the answer may only be one of the two
    # units offered, so it can never introduce a unit nobody was asked about. Unanswered (or
    # explicitly declined) leaves the vote untouched, so a run without an answer is
    # byte-identical to before.
    if getattr(args, "answers", ""):
        try:
            import clarify as _CQ
            _du = (_CQ.load_state(Path(args.answers)).get("answers") or {}).get(
                _CQ.DATASET_UNIT_QID)
            _du = str(_du or "").strip().lower()
            if _du in ("sq ft", "sq m") and _du != area_unit:
                print(f"  (dataset area unit set to '{_du}' by the broker's answer, not by the "
                      f"majority vote which said '{area_unit}')")
                area_unit = _du
        except Exception as e:
            print(f"  (answered dataset unit not applied: {e})", file=sys.stderr)
    # D11: THE RENT BASIS IS AN ASSUMPTION WHEN NO SOURCE STATES ONE, AND IT IS SAID SO.
    # dominant_units already falls back to the market-derived default, but it is recomputed HERE
    # because the broker's answer above may have moved `area_unit`, and a rent basis derived from
    # the vote's area unit would then disagree with the grid it labels. The entry lands in
    # `meta.unitAssumptions` (appended once the list exists, below) so the Gaps Report carries it
    # exactly as it carries an assumed area unit - on the measured run the operator had to write
    # that disclosure by hand. Printed as well, because a default that is only visible in a report
    # read after the dashboard shipped is the silence this codebase treats as the bug.
    _rent_assumption = None
    if not rent_unit_stated(all_records):
        rent_unit, _rent_assumption = rent_unit_default(all_records, area_unit)
        print(f"  (no source states a rent unit: the rent basis '{rent_unit}' is ASSUMED from the "
              f"dominant area unit and country, and is disclosed in the Gaps Report; no rent "
              f"figure is relabelled with it)")
    MATCH_DECISIONS = {}  # pair_id -> 'same'|'different'|{verdict,reason} (grey-zone sub-agent)
    if args.match_decisions and Path(args.match_decisions).exists():
        try:
            loaded = json.loads(Path(args.match_decisions).read_text(encoding="utf-8-sig"))
            MATCH_DECISIONS = loaded if isinstance(loaded, dict) else {}
        except Exception:
            MATCH_DECISIONS = {}  # best-effort, exactly like PHOTO_MAP - a bad file -> deterministic
    # First-party map-link pins (bug #D): fill lat/lng + mapLink from each brochure page's
    # 'click for location' maps hyperlink BEFORE clustering/geocode. The author's own pin is
    # better than any geocoder and fully offline; this recovers the coords the current
    # interpretation record source does not carry (the harvest used to live only in the
    # deprecated extract_pdf own-line path). Deterministic (pure function of the PDFs) -> resume-safe.
    if getattr(args, "source_dir", None):
        XP.backfill_link_coords(all_records, Path(args.source_dir))
    clusters = match.dedupe(all_records, MATCH_DECISIONS or None)
    # SOURCE AUTHORITY (B47). The broker was asked - once clustering had SETTLED - which source
    # decides what BELONGS on the longlist, and their answer is applied HERE, on the settled
    # clusters, so an option evidenced only by the non-guiding source is excluded rather than
    # shipped as a phantom extra. Unanswered / 'union' keeps every cluster, so a run without
    # an answer is byte-identical to before. Everything excluded is carried into meta and
    # named in the Gaps Report - this must never be a silent drop.
    EXCLUDED = []
    if getattr(args, "answers", ""):
        try:
            import clarify as _CQ
            _auth = _CQ.settled_authority(
                _CQ.load_state(Path(args.answers)).get("answers") or {})
            clusters, EXCLUDED = apply_source_authority(clusters, _auth)
            if EXCLUDED:
                print(f"  ({len(EXCLUDED)} option(s) excluded - you set the {_auth} as the "
                      f"guiding source; each is named in the Gaps Report)")
        except Exception as e:
            print(f"  (source authority not applied: {e})", file=sys.stderr)
    # THE MASTER LIST, APPLIED THE SAME WAY AND FOR A STRONGER REASON. The authority answer
    # above is a proxy - a source family - and it is asked after everything has been read. The
    # master list is the user naming the options themselves, before the decks were read. Its
    # exclusions are applied here, on the settled clusters, so a row they struck off cannot
    # reach a card through a second source that also mentions it. `apply_to_clusters` keeps a
    # cluster unless EVERY record in it maps to an excluded row, and fails open if the filter
    # would empty the dataset: an empty dashboard is never the right reading of a sheet
    # somebody filled in. Nothing is dropped silently - deliver.py names each one.
    if str(getattr(args, "master_list", "") or "").strip():
        try:
            import master_list as _ML
            _ml_answers = _ML._read_json(Path(args.master_list), {}) or {}
            clusters, _ml_dropped = _ML.apply_to_clusters(clusters, _ml_answers)
            if _ml_dropped:
                print(f"  ({len(_ml_dropped)} option(s) left out - you marked them No on the "
                      f"master list; each is named in the Gaps Report)")
        except Exception as e:
            print(f"  (master list not applied: {e})", file=sys.stderr)
    FIELD_DECISIONS = {}  # conflict_id -> {pick, reason} (cross-source value-conflict sub-agent)
    if args.field_decisions and Path(args.field_decisions).exists():
        try:
            loaded = json.loads(Path(args.field_decisions).read_text(encoding="utf-8-sig"))
            FIELD_DECISIONS = loaded if isinstance(loaded, dict) else {}
        except Exception:
            FIELD_DECISIONS = {}  # best-effort, exactly like MATCH_DECISIONS - a bad file -> precedence
    source_dir = Path(args.source_dir)
    # Site plans the visual-QA reviewer REJECTED (`plan_rejected` in the ack file). Loaded
    # here so every rebuild honours it - the remedy "clear p.plan in canonical.json" only
    # held while merge resume-skipped, which made it non-terminating.
    PLAN_REJECTED = load_plan_rejected(args.plan_rejected) if args.plan_rejected else set()
    if PLAN_REJECTED:
        print(f"[merge] site plan(s) rejected at visual QA, not binding: "
              f"{sorted(PLAN_REJECTED)}")
    PHOTO_MAP = {}  # match_key -> brochure relpath (confident photo matches from the sub-agent)
    if args.photo_map and Path(args.photo_map).exists():
        try:
            PHOTO_MAP = json.loads(Path(args.photo_map).read_text(encoding="utf-8-sig")) or {}
        except Exception:
            PHOTO_MAP = {}
    PHOTO_DESCRIPTIONS = {}  # brochure name -> {description, page, quote, text_hash} (sub-agent pick)
    if args.photo_descriptions and Path(args.photo_descriptions).exists():
        try:
            loaded = json.loads(Path(args.photo_descriptions).read_text(encoding="utf-8-sig"))
            PHOTO_DESCRIPTIONS = loaded if isinstance(loaded, dict) else {}
        except Exception:
            PHOTO_DESCRIPTIONS = {}  # best-effort, exactly like PHOTO_MAP - a bad file -> heuristic
    # persistent hero-image cache: DEFAULT next to the canonical, so a manual
    # `python helpers/merge.py` call (no --image-cache flag) still checkpoints
    # per page and survives a capped/killed shell exactly like a run.py call
    image_cache = (Path(args.image_cache) if args.image_cache
                   else Path(args.out).resolve().parent / ".image_cache")
    try:
        image_cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        image_cache = None  # unwritable cache dir must never break the merge

    def _is_sentinel(v, field=None):
        # The shared family, nothing private (SEAM-13). Four sites read this: the regionCode
        # derivation, the derived-companion provenance, the brochure description backfill and
        # the gap rows. A stated "none" is DATA at all four (a source that prints "None" for a
        # spec has spoken; it gets a provenance row, not a gap row), and the markers the old
        # five-member set lacked ("tbc", "n/a", "tba", "-", "?") are absences at all four, so a
        # description reading "tbc" is now backfilled from the deck instead of shipping. The
        # gap rows pass `field` so `country` gets the CODE reading: a bare assigned alpha-2
        # code that doubles as a market abbreviation is a country, not a gap.
        if field == "country":
            return N.looks_unknown_code(v)
        return N.looks_unknown(v)

    properties, ledger_rows, all_conflicts = [], [], []
    # Both-shipped forbidden-with-identity pairs: two cards plausibly ONE building,
    # kept apart by the >15% size rule and BOTH shipping. Disclosed in the Gaps
    # 'Source conflicts' section - the LLM never sees a forbidden pair and the
    # dedupe gate sees two distinct keys, so nothing else compares their figures.
    all_conflicts.extend(shipped_forbidden_conflicts(clusters))
    all_variants: list = []   # I10: meta.notationVariants - same value, stated differently
    override_rows: list = []   # P1-4: explicit `override` ledger rows, appended after the loop
                               # so the property rows keep their existing order and bytes
    meta_offspec = []   # v22 Phase 1: off-spec keys quarantined pre-merge (-> Gaps Report)
    meta_newfields = []  # B7: brand-new scalar keys KEPT and auto-shown (-> Gaps Report)
    placeholder_audit: dict = {}  # prop id -> discarded image candidates (audited, never silent)
    regions_on = bool(((_load_yaml(args.project_yaml) or {}).get("enrichment") or {}).get("regions"))
    # UNIQUE-CLAIMANT GUARD: precompute, once over ALL clusters, the per-deck pages each
    # property may NOT draw carousel photos from (a neighbour's anchor/uniquely-claimed
    # pages). attach_media subtracts its own foreign set before harvesting. With no
    # image_pages anywhere this is empty everywhere -> byte-identical to today.
    foreign_by_cluster = build_foreign_pages(clusters, source_dir)
    # the BROADER per-deck other-owned set for the plan_page HINT (which may name any page,
    # not just the cluster's own) - so an LLM plan_page can never bind a neighbour's plan.
    plan_offlimits_by_cluster = plan_offlimits_pages(clusters, source_dir)
    # PLAN-SLOT REACH over the pages no property claimed (plan_reach_pages). Computed here
    # beside its two siblings so all three ownership projections come from one place.
    plan_reach_by_cluster = plan_reach_pages(clusters, source_dir)
    # CAROUSEL REACH over the same unclaimed pages (gallery_reach_pages) - the same ownership
    # base, its own recall-tuned attribution. Fourth and last projection, same place.
    gallery_park_level: list = []
    gallery_reach_by_cluster = gallery_reach_pages(clusters, source_dir,
                                                   park_level=gallery_park_level)
    plan_near_miss_all: list = []  # per-property near-miss plan pages -> Gaps Report (light Fix 4)
    # THE CONSIDERED SET (per PROPERTY, not per brochure). One entry per merged property
    # recording every deck page that was in reach, every rule that took one away, what bound and
    # what was never looked at. Written to work/media_considered.json; read by
    # `gate_runner media-harvest` and projected to openable files by project_properties.py.
    # Pure recording - see attach_media's `considered` parameter.
    media_considered: list = []
    unit_assumptions: list = []    # areas whose unit the SOURCE never stated -> Gaps Report
    if _rent_assumption:           # D11: the dataset-level rent basis, when no source stated one
        unit_assumptions.append(_rent_assumption)
    # D5: {property_id: the refusal text} for an officeArea string holding SEVERAL figures, from
    # which no single officeAreaVal could honestly be taken. The field ships ABSENT and the
    # refusal is said on stdout, on the conflicts channel and in a gap ledger row - a first-number
    # parse shipped 899 (a sq m figure) as the sq ft office area on a live run and nothing saw it.
    office_val_refused: dict = {}
    # B58: {property_id: [(field, raw value, unrecognised unit)]}. A figure the dataset cannot
    # express is withdrawn rather than mislabelled, and its gap row must say THAT instead of
    # claiming the source was silent - the false-absence claim both critical reviewers blocked on.
    withheld_units: dict = {}
    # B63: {property_id: [(field, the raw text)]}. The twin of withheld_units for a
    # schema-NUMERIC area whose merged value held no single number at all (a 'tbd' struck by
    # the plausibility gate, a stated RANGE, an unparseable text). The field ships ABSENT -
    # text cannot go in a `number` and a figure must never be invented - so its gap row has to
    # say what was dropped rather than assert the sources were silent about it.
    unparseable_areas: dict = {}
    stated_totals: dict = {}       # P1-1: id -> the SOURCE's own stated total area (arithmetic gate)
    computed_sums: dict = {}       # F11: id -> the office-sum audit entry (computed or refused)
    open_capture_by_id: dict = {}  # id -> the extractor's __meta.open_capture entries (commentary/
    #                                denied/CJK columns): READ but never client-shown; __meta is
    #                                popped at merge, so this is how they reach the per-property view
    all_struck: list = []          # A9/honesty: {id, field, value, source_file, locator} per strike
    cluster_sources: dict = {}     # A14a: id (STRING) -> the records that built this property
    for i, cl in enumerate(clusters, start=1):
        variants: dict = {}   # I10: same fact, different notation - reported, not adjudicated
        _struck: list = []    # this cluster's band strikes, id-stamped a few lines below
        merged, prov, conflicts = merge_cluster(cl, FIELD_DECISIONS or None, variants, _struck)
        merged["id"] = i
        # The property id exists only HERE, so this is where a per-cluster artefact gets stamped
        # with it. Key SHAPE is deliberate and matches the existing per-property projections
        # below: `struck` carries an INT id (it sits beside the properties, which key on an int
        # `id`), while the dict projections key on a STRING (openCapture/placeholderAudit already
        # do, because JSON object keys are strings and a round-trip must not change them).
        for _s in _struck:
            all_struck.append({"id": i, "field": _s["field"], "value": _s["value"],
                               "source_file": _s["source_file"], "locator": _s["locator"]})
        # A14a WHICH SOURCES BUILT THIS PROPERTY, and what postcode each of them stated.
        # Captured HERE, inside the loop that still holds both the cluster's records and the
        # assigned id, and necessarily BEFORE the `merged.pop("__meta")` choke point below.
        #
        # WHY THE POSTCODE RIDES ALONG. The over-merge gate has to ask whether two records the
        # matcher fused state DIFFERENT postcodes - two buildings, one card. Recording each
        # contributing record's own stated postcode here makes that a pure function of
        # canonical.json, so the gate never has to import the matcher, re-cluster, or re-read the
        # inputs to answer it. A gate that re-derives clustering to check clustering can only
        # ever agree with itself.
        cluster_sources[str(i)] = [
            {"file": Path(str((r.get("__meta") or {}).get("source_file") or "")).name,
             "postcode": _stated_postcode(r)} for r in cl]
        _oc = [dict(e, source_file=(r.get("__meta") or {}).get("source_file", ""))
               for r in cl
               for e in ((r.get("__meta") or {}).get("open_capture") or [])
               if isinstance(e, dict)]
        if _oc:
            open_capture_by_id[str(i)] = _oc
        # F11: an office total the source never printed, summed from the lines it did. BEFORE
        # canonicalize, which derives officeAreaVal from officeArea, and before the unit
        # alignment, which converts officeAreaVal on the areaUnitOfSource this stamps. A stated
        # total is never touched; every refusal leaves the field an honest gap and the ambiguous
        # ones (overlapping lines, an unknowable unit) are said on the conflicts channel, where
        # the Gaps Report already reads.
        _os = derive_office_sum(cl, merged, prov)
        if _os:
            computed_sums[str(i)] = _os
            if _os.get("status") == "computed" and str(_os.get("reconciles", "")).startswith("does NOT"):
                all_conflicts.append(f"id {i} officeArea: computed from itemised office lines, but "
                                     f"{_os['reconciles']}. Read the schedule of accommodation "
                                     f"before this figure goes to the client.")
            elif _os.get("status") == "refused" and "not a sum" not in str(_os.get("why", "")):
                all_conflicts.append(f"id {i} officeArea: the source itemises office space "
                                     f"({', '.join(_os.get('components') or [])}) but prints no "
                                     f"total, and the lines were NOT summed: {_os['why']}.")
        merged = canonicalize(merged)
        # D5: THE OFFICE FIGURE, WHEN CANONICALIZE COULD NOT TAKE ONE. `_office_area_parse` reads
        # the officeArea string canonicalize just derived from; when it REFUSED (several figures,
        # no identifiable total) the twin is absent and that absence has to be visible - a
        # first-number parse used to ship 899 (a sq m figure) as the sq ft office on a live run
        # and nothing saw it. Three surfaces: stdout now, the conflicts channel the Gaps Report
        # prints, and a gap ledger row a few lines below that says WHY rather than "absent in
        # all sources". When it DID take a figure but had to choose (a dual-unit restatement, a
        # leading total confirmed by its parts) the choice is stamped onto the derived prov entry
        # below, together with the unit printed beside the CHOSEN figure - which is the footing
        # the alignment step converts on. That footing used to be inherited from the record's
        # `areaUnit`, so "1,413 sq m" on a sq ft record shipped 1,413 unconverted as sq ft.
        _oa_parse = _office_area_parse(merged.get("officeArea"), _record_area_unit(merged))
        if _oa_parse and _oa_parse.get("refused"):
            _figs = ", ".join(_oa_parse.get("figures") or [])
            office_val_refused[i] = (f"{_oa_parse['why']}; figures: {_figs}. Total GLA "
                                     f"therefore counts the warehouse alone until the office "
                                     f"total is stated (repairs.json: officeAreaVal, with "
                                     f"officeArea) or read from the source")
            all_conflicts.append(f"id {i} officeAreaVal: NOT derived from officeArea - "
                                 f"{office_val_refused[i]}.")
            print(f"  (id {i} {merged.get('park') or merged.get('city') or '?'}: officeAreaVal "
                  f"NOT derived - {_oa_parse['why']}; the office is excluded from Total GLA and "
                  f"the gap is disclosed. State the total via repairs.json if it is known.)")
        # regionCode auto-derivation: the workforce block keys on regionCode, but no
        # extractor sets it - a real run shipped an EMPTY workforce block because
        # nothing ever bound properties to profiles. When the regions extra is on,
        # derive it from the region label (the Oxford Economics dataset then matches
        # it by NUTS code or unique province name; validate-data blocks LOUDLY if a
        # code matches no profile). Only when regions are requested - otherwise the
        # regionCode-resolves check would block runs that never wanted workforce data.
        if regions_on and not merged.get("regionCode") and not _is_sentinel(merged.get("region")):
            merged["regionCode"] = N.clean_value(merged["region"])
        # provenance for DERIVED companions: a value canonicalize() synthesises from a
        # sourced field (the rent display from warehouseRentVal, the numeric from
        # expansionPark) inherits that field's source. Without this, trace-coverage
        # flags the derived value as "untraceable - possible fabrication" on EVERY
        # run whose rent arrived numeric-only (xlsx trackers, vision records) - an
        # unresolvable gate loop, since re-running merge reproduces the same state.
        for derived, basis in (("warehouseRent", "warehouseRentVal"),
                               ("warehouseRentVal", "warehouseRent"),  # numeric derived from a display string
                               ("officeRentVal", "officeRent"),        # office rent numeric for the total-rent split
                               ("officeAreaVal", "officeArea"),        # office area numeric for total GLA
                               ("expansionParkVal", "expansionPark")):
            if derived not in prov and basis in prov and not _is_sentinel(merged.get(derived)):
                src = dict(prov[basis])
                src["locator"] = (f"{src.get('locator', '')} (derived from {basis})").strip()
                if derived == "officeAreaVal" and _oa_parse and _oa_parse.get("value") is not None:
                    # D5: the footing is the unit printed beside the figure that was TAKEN, not
                    # the record-level areaUnit the basis prov inherited from merge_cluster. A
                    # text that states its unit is the most specific evidence there is (the
                    # same rule B63 applies to a printed warehouseArea a few lines below), and
                    # without it a metric office line on an imperial record was never converted.
                    if _oa_parse.get("unit"):
                        src["areaUnitOfSource"] = _oa_parse["unit"]
                    if _oa_parse.get("note"):
                        src["locator"] = f"{src['locator']} ({_oa_parse['note']})"
                prov[derived] = src
        # DATASET UNIT CONVENTION: the dominant area unit wins; a minority-unit
        # record converts ARITHMETICALLY (prov-noted). Currency is never touched
        # (FX would be invention) - a lone €/m² rent in a £/sq ft dataset keeps
        # its own honest unit and simply sits out the hero rent range.
        # PER-FIELD CONVERSION, EACH ON ITS OWN SUPPLIER'S FOOTING (B39).
        #
        # This used to branch on ONE merged `areaUnit` and apply it to all three fields. But
        # every field resolves its own precedence contest, so `warehouseArea` can come from one
        # record while `areaUnit` comes from another - and the number was then scaled by
        # 10.7639 on a unit its own source never stated. Measured: 134,549 sq ft shipped as
        # 1,448,272, with an EMPTY meta.unitAssumptions and no conflict note, i.e. more silent
        # than the unit-silent case below that this machinery was built for.
        #
        # Both remedies the backlog proposed were measured and are WRONG - each relocates the
        # identical error onto plotArea (a 40,000 sq m plot shipping as 40,000 "sq ft" against a
        # true 430,556): pinning the label to warehouseArea's supplier fixes one field by
        # mislabelling the others, and refusing to merge a mixed-unit cluster does the same AND
        # destroys the legitimate merge B10 exists to enable. The ordering was never the
        # problem; applying ONE label to values from DIFFERENT records was.
        #
        # A field whose own supplier stated NO unit is still never converted and still records
        # the assumption - inferring it would be the invention the skill forbids.
        #
        # A schema-NUMERIC area that arrived as a formatted STRING is PARSED HERE, before the
        # isinstance test, so the conversion below runs on it like any other number (B63).
        # The test used to be the whole story: a brochure record stores '436,000 sq ft' by
        # design, `merged[fld]` was therefore not an int/float, the loop `continue`d, and the
        # raw string sailed into canonical.json - where `warehouseArea` is typed `number`.
        # One live run: 17+ properties failing validate-data with "'436,000 sq ft' is not of
        # type 'number'", and value-format flagging the SAME field for shipping a bare 387259
        # on one card beside '160,725 sq ft' on the next. Only the properties whose area came
        # from a tracker (already numeric) were ever right.
        _silent_any = False
        _withheld: list = []   # B58: (field, raw value, its unrecognised unit)
        _unparseable: list = []   # B63: (field, raw text) - a numeric area that held no number
        for fld in ("warehouseArea", "plotArea", "officeAreaVal"):
            _stated = None     # the unit the VALUE's own text printed, when it printed one
            if fld in _NUMERIC_ONLY_AREA_FIELDS and isinstance(merged.get(fld), str):
                _parsed = _area_text_value(merged[fld])
                if _parsed is None:
                    # 'tbd' (this field's only route to one is merge_cluster's plausibility
                    # STRIKE), a range, or an unparseable text. The schema types this field as
                    # a number, so text cannot ship in it and a number must not be invented:
                    # the field goes ABSENT, exactly as it does when no source stated it. The
                    # gap ledger row below then says what was dropped instead of claiming the
                    # sources were silent, and any strike note is already in `conflicts`.
                    _unparseable.append((fld, merged[fld]))
                    merged.pop(fld, None)
                    prov.pop(fld, None)
                    continue
                _printed = merged[fld]
                merged[fld], _stated = _parsed
                if fld in prov:
                    # merge is re-notating what the page printed, and every other transformation
                    # in this loop records itself - so this one does too, or the ledger would
                    # show a bare 436000 against a page that prints '436,000 sq ft'.
                    prov[fld]["locator"] = (f"{prov[fld].get('locator', '')} "
                                            f"(printed as '{_printed}')").strip()
                    # the unit printed NEXT TO THE NUMBER is the most specific evidence there
                    # is - more specific than `<field>Unit`, and far more than the record-level
                    # `areaUnit` a brochure record routinely does not carry at all. Only ever
                    # reached for a value that WAS a string, so no already-numeric field can
                    # have its footing moved by this.
                    if _stated:
                        prov[fld]["areaUnitOfSource"] = _stated
            if not isinstance(merged.get(fld), (int, float)):
                continue
            _u = _stated or (prov.get(fld) or {}).get("areaUnitOfSource")
            if not _u:
                _silent_any = True
                if fld in prov:
                    prov[fld]["locator"] = (f"{prov[fld].get('locator', '')} "
                                            f"(unit not stated in source; {area_unit} assumed)").strip()
            elif _u != area_unit:
                # B58: general over sq ft / sq m / acres / ha, not just the metric-imperial pair.
                # An UNRECOGNISED unit yields None: the figure is then neither converted nor kept
                # under a unit it is not in - it is WITHDRAWN and disclosed in its gap row,
                # because shipping it would mislabel it and dropping it silently would repeat the
                # false "absent in all sources" this change exists to fix.
                f = N.area_factor(_u, area_unit)
                if f is None:
                    _withheld.append((fld, merged[fld], _u))
                    merged.pop(fld, None)
                    prov.pop(fld, None)
                    continue
                _raw = merged[fld]
                merged[fld] = round(merged[fld] * f)
                if fld in prov:
                    prov[fld]["locator"] = (
                        f"{prov[fld].get('locator', '')} "
                        f"(stated as {_raw:g} {_u}; converted at {f:g} "
                        f"{area_unit} per {_u})").strip()
        if _withheld:
            withheld_units[i] = list(_withheld)
        if _unparseable:
            unparseable_areas[i] = list(_unparseable)
        if _silent_any:
            # ANY area field with a silent supplier flags the property, so stated_total_for's
            # refusal stays exactly as conservative as before.
            merged["areaUnitAssumed"] = True
            unit_assumptions.append({
                "id": i,   # join by ID, never by park name (B38)
                "property": merged.get("park") or merged.get("city") or f"#{i}",
                "field": "areaUnit", "assumed": area_unit,
                "why": ("the source stated a numeric area but no unit; the dataset's dominant "
                        "unit was assumed and the figure was NOT converted"),
            })
        merged["areaUnit"] = area_unit
        # P1-1: lift the source's own stated total (if any) into meta, NOT onto the property -
        # a new top-level scalar would render in the v21 modal on the client's card. Placed AFTER
        # the unit alignment above so it is compared against fields in the same unit, and after
        # `areaUnitAssumed` is set so the helper can refuse an un-converted record.
        _st = stated_total_for(cl, merged, area_unit)
        if _st:
            stated_totals[str(i)] = _st
        _cluster_nm: list = []
        _cluster_considered: dict = {}
        merged["photo"], plan_uri, photo_rec, plan_rec, tried_pages, gallery = attach_media(
            cl, source_dir, args.image_budget_kb, image_cache=image_cache,
            foreign_pages=foreign_by_cluster[i - 1],
            plan_offlimits=plan_offlimits_by_cluster[i - 1],
            plan_near_miss=_cluster_nm,
            plan_rejected=PLAN_REJECTED,
            considered=_cluster_considered,
            plan_reach=plan_reach_by_cluster[i - 1],
            gallery_reach=gallery_reach_by_cluster[i - 1],
            gallery_park_level=(gallery_park_level[i - 1] if gallery_park_level else None))
        if _cluster_considered:
            _cluster_considered["id"] = i
            _cluster_considered["property"] = (merged.get("park") or merged.get("city")
                                               or f"#{i}")
            _cluster_considered["city"] = merged.get("city", "")
            media_considered.append(_cluster_considered)
        if not plan_uri and _cluster_nm:  # a page LOOKED plan-ish but no plan bound -> surface it
            plan_near_miss_all.append({"property": merged.get("park") or merged.get("city") or "?",
                                       "city": merged.get("city", ""), "pages": _cluster_nm})
        merged["gallery"] = gallery  # carousel photos (hero first); always >= [photo]
        # PHOTO MATCH OVERRIDE (P0-1): a 0-record brochure the sub-agent CONFIDENTLY
        # matched to this property supplies the hero, scanned across the whole deck
        # (cheap embedded-image tier). Fills the placeholder; never overrides a photo
        # the property's own cluster already produced.
        matched_hero = False
        if photo_rec is None and PHOTO_MAP:
            brel = PHOTO_MAP.get(match.match_key(merged))
            if brel:
                bsrc = _resolve_source(source_dir, Path(brel).name)
                hero = IMG.best_hero_in_deck(bsrc, args.image_budget_kb, image_cache) if bsrc else None
                if hero:
                    merged["photo"] = hero
                    # the matched brochure IS this property (single-property deck), so the
                    # carousel candidates are the whole deck's card-quality photos. Composed
                    # by the SAME rule as the page-scoped path: the hero leads, the hero is
                    # held to the carousel's floors, and a hero that fails them is replaced.
                    try:
                        g_uris, _gt = IMG.gallery_for_deck(bsrc, args.image_budget_kb, image_cache)
                    except Exception:
                        g_uris = []
                    merged["photo"], merged["gallery"], _promo = _compose_gallery(hero, g_uris)
                    hero = merged["photo"]
                    prov["photo"] = {"source_file": Path(brel).name,
                                     "source_type": (Path(brel).suffix.lstrip(".") or "pdf"),
                                     "locator": "deck photo (brochure matched to this property)"}
                    matched_hero = True
                # also harvest the brochure's DESCRIPTION prose: the deck had no spec
                # record, so parse_property_page never captured it - same confident
                # brochure->property link as the photo. PREFER the photo-match sub-agent's
                # LLM verbatim pick (handles multi-paragraph / novel-market decks the
                # EN-keyword heuristic misses), but ONLY when it passes the deterministic
                # quote-verify gate (the quote occurs verbatim in the cited page + the
                # deck text is unchanged); otherwise fall through to best_description_in_deck
                # UNCHANGED. Verbatim from the deck; a tbd stays tbd when none is usable.
                if bsrc and _is_sentinel(merged.get("description")):
                    dtext, dpno, dtag = None, None, "brochure description"
                    entry = PHOTO_DESCRIPTIONS.get(Path(brel).name) if PHOTO_DESCRIPTIONS else None
                    if entry:
                        v = _verified_photo_description(bsrc, entry)
                        if v:
                            dtext, dpno = v
                            dtag = "brochure description, text interpretation"
                    if dtext is None:  # no pick, or the gate rejected it -> deterministic fallback
                        try:
                            dtext, dpno = XP.best_description_in_deck(bsrc)
                        except Exception:
                            dtext, dpno = None, None
                    if dtext:
                        merged["description"] = dtext
                        prov["description"] = {
                            "source_file": Path(brel).name,
                            "source_type": (Path(brel).suffix.lstrip(".") or "pdf"),
                            "locator": f"page {(dpno or 0) + 1} ({dtag})"}
        if matched_hero:
            pass  # prov["photo"] already set from the matched brochure
        elif photo_rec is None:  # placeholder: an honest, COMPLETE gap row (an empty
            # source_file/type would fail ledger validate - now a scorecard gate)
            prov["photo"] = {"source_file": "(none)", "source_type": "gap",
                             "locator": "no usable photo in any source (placeholder shown)"}
            # PLACEHOLDER AUDIT: a placeholder is never a silent default - dump
            # every image candidate from the pages we examined so the G-images
            # reviewer can SEE the discard pile and sign off (or rescue a usable
            # photo/plan). The images gate BLOCKS until that sign-off exists.
            if tried_pages:
                audit_dir = Path(args.out).resolve().parent / "render" / "placeholder_audit"
                files: list[str] = []
                for srcf, pno, kind in tried_pages:
                    try:
                        if kind == "pptx":
                            files += IMG.slide_image_audit(
                                srcf, pno, audit_dir, f"prop{i}", cache_dir=image_cache)
                        else:
                            files += IMG.page_image_audit(srcf, pno, audit_dir, f"prop{i}",
                                                          cache_dir=image_cache)
                    except Exception:
                        pass
                unit = "slide" if tried_pages[0][2] == "pptx" else "page"
                placeholder_audit[str(i)] = {
                    "source": tried_pages[0][0].name,
                    "locator": f"{unit} {tried_pages[0][1] + 1}",
                    "candidates": len(files), "files": files,
                }
        else:
            photo_src = photo_rec.get("__meta", {})
            prov["photo"] = {"source_file": photo_src.get("source_file", ""),
                             "source_type": photo_src.get("source_type", ""),
                             "locator": (photo_src.get("prov", {}).get("photo")
                                         or photo_src.get("locator_base", ""))}
        if plan_uri:  # the modal's Site Plan toggle reads p.plan
            merged["plan"] = plan_uri
            plan_src = (plan_rec or {}).get("__meta", {})
            pno = plan_src.get("page_no")
            prov["plan"] = {"source_file": plan_src.get("source_file", ""),
                            "source_type": plan_src.get("source_type", ""),
                            "locator": (plan_src.get("prov", {}).get("plan")
                                        or (f"page {pno + 1} (site plan)" if isinstance(pno, int)
                                            else plan_src.get("locator_base", "")))}
        # THE CHOKE POINT: internal working flags must never reach a client card (B05).
        # This is the one place a property is appended, so it is the one place the sweep
        # has to happen - and it must stay immediately above the pop that drops __meta.
        strip_internal_flags(merged)
        merged.pop("__meta", None)
        properties.append(merged)
        # v22 Phase 1: audit every quarantined off-spec key (never silently dropped)
        for _r in cl:
            for _k, _v in (_r.get("__meta", {}).get("offspec", {}) or {}).items():
                ledger_rows.append({
                    "property_id": i, "record_type": "offspec", "field": _k,
                    "value": _short(_v), "source_file": _r.get("__meta", {}).get("source_file", ""),
                    "source_locator": "", "source_type": _r.get("__meta", {}).get("source_type", ""),
                    "extractor": "boundary", "confidence": "",
                    "conflict_note": "off-spec structure (provenance/meta) quarantined - not a displayable value",
                    "verified": "",
                })
                meta_offspec.append({"property_id": i, "key": _k, "value": _short(_v)})
            # B7: brand-new SCALAR keys are KEPT and auto-shown, so they must be DISCLOSED. Without
            # this, a non-schema field (live: `postcode` on half the properties) shipped while the
            # Gaps Report's off-spec section read "None." - that section only ever covered
            # quarantined structures.
            for _k in (_r.get("__meta", {}).get("new_fields") or []):
                if _k in merged:
                    meta_newfields.append({"property_id": i, "key": _k,
                                           "source_file": _r.get("__meta", {}).get("source_file", "")})
        # P1-4: one EXPLICIT correction row per applied override, emitted HERE and not at load
        # time because property_id only exists after clustering. This is the auditable artefact:
        # `grep ,override, source_ledger.csv` lists every manual touch in one command, and the
        # Source Ledger xlsx shows it in the record_type column, so a correction is DISCLOSED as a
        # correction instead of being laundered into what looks like an extracted row. (The field's
        # own property row is already correct for free - the applier rewrote the record's prov
        # string, so its locator ends with "(manual override ...)".)
        for _r in cl:
            _rm = _r.get("__meta") or {}
            for _oid in (_rm.get("override_ids") or []):
                _oa = next((a for a in OV_REPORT.get("applied", []) if a["id"] == _oid), None)
                if not _oa:
                    continue
                for _f, _new in _oa["set"].items():
                    # A18b: an override may CITE THE EVIDENCE A HUMAN ACTUALLY READ. The two
                    # columns below defaulted to `where.source_file` plus this entry's own
                    # targeting clause - which names the file+row the correction MATCHES ON, not
                    # the page the value was read from. A figure taken off a brochure page and
                    # corrected through the tracker row that carries it was therefore attributed
                    # to the tracker. When the entry cites its own evidence, the citation wins and
                    # the was/now/why audit trail moves into the conflict_note column, which is
                    # the honest split: `source_locator` answers "where is this value", the note
                    # answers "what changed and why". Absent, both columns are byte-identical to
                    # today. A cited page is EVIDENCE the prov-containment gate can then check, so
                    # cite the page the value actually occurs on.
                    _cite_f = str(_oa.get("source_file") or "").strip()
                    _cite_l = str(_oa.get("source_locator") or "").strip()
                    _trail = (f"work/overrides.json#{_oa['id']} at {_oa['locator']}"
                              f" | was: {_short(_oa['old'].get(_f))} -> now: "
                              f"{_short(_new)} | why: {_oa['why']}")
                    override_rows.append({
                        "property_id": i, "record_type": "override", "field": _f,
                        "value": _short(_new) or "tbd",
                        "source_file": _cite_f or _oa["where"]["source_file"],
                        "source_locator": _cite_l or _trail,
                        # non-empty and != "gap": ledger.REQUIRED is satisfied by construction and
                        # trace-coverage still counts the field as traced. An override can never
                        # make a field untraceable, and never launders one into a gap-free field
                        # without leaving this row behind.
                        "source_type": "override", "extractor": "manual",
                        "confidence": "manual",
                        # A18b: NOTHING IS SILENTLY DROPPED. When a cited locator displaces the
                        # was/now/why trail out of `source_locator`, the trail moves HERE rather
                        # than being lost - the honest split being that source_locator says where
                        # the value IS and this column says what changed and why. The repair
                        # channel already carries its id, why and old value in this same column,
                        # so citing evidence leaves the two channels the same shape instead of
                        # making them diverge. Byte-identical when nothing is cited.
                        "conflict_note": ("manual correction applied post-extraction; "
                                          "work/extract was NOT edited"
                                          + (f". {_trail}" if _cite_l else "")),
                        "verified": ("yes" if _oa.get("verified_by") else ""),
                    })
        # ledger rows for every populated field (with conflict note where one occurred)
        for field, pr in prov.items():
            # THE EMAIL GOES IN THE LOCATOR, because the ledger has no free column. Its eleven
            # columns are fixed and validated (ledger.py COLUMNS/REQUIRED, and the exported
            # xlsx hard-codes a width per column letter), so adding a twelfth to carry the
            # sending email would break the export and every consumer that reads by position.
            # `source_locator` is already the free-text "where exactly is this value" column,
            # and "page 3 (attachment of email 'Sziget II offer', 2025-05-12)" answers that
            # question MORE completely than "page 3" does, rather than smuggling a different
            # fact into it. Appended, never substituted: the page citation stays first so the
            # locator still opens at the page a checker needs.
            _loc = str(pr.get("locator", "") or "")
            _fe = _fe_for(pr.get("source_file"))
            if _fe:
                _subj = str(_fe.get("subject") or "") or "(no subject)"
                _from = ("attachment of email " + repr(_subj)
                         + (f", {_fe['date']}" if _fe.get("date") else ""))
                _loc = f"{_loc} ({_from})".strip() if _loc else _from
            ledger_rows.append({
                "property_id": i, "record_type": "property", "field": field,
                "value": _short(merged.get(field)), "source_file": pr.get("source_file", ""),
                "source_locator": _loc, "source_type": pr.get("source_type", ""),
                "extractor": f"E-{pr.get('source_type','')}", "confidence": _confidence(pr),
                "conflict_note": conflicts.get(field, ""), "verified": "",
            })
        # a ledger row for every chrome-read field left as a sentinel (the positive
        # record that the value was genuinely absent - checked by G-honesty). Covers
        # the identity fields too (developer/city/park/country/reit/mapLink/...): a
        # sentinel without its row is a gap G-honesty cannot verify.
        for field in (C.STRING_FIELDS + list(C.REQUIRED_TEXT_SENTINELS)
                      + ["landPrice", "warehouseArea", "lat", "lng",
                         "plotArea", "reit", "mapLink", "expansionParkVal"]):
            if field in prov:
                continue
            val = merged.get(field)
            if _is_sentinel(val, field):
                ledger_rows.append({
                    "property_id": i, "record_type": "property", "field": field,
                    # an empty-string sentinel (mapLink) still needs a non-empty
                    # ledger value, or the row fails ledger validate
                    "value": (str(val).strip() if val is not None and str(val).strip() else "tbd"),
                    "source_file": "(none)",
                    # B58: a gap row may NEVER claim a source is silent about a value the source
                    # in fact states. When the figure was withdrawn because its unit is one this
                    # dataset cannot express, say exactly that.
                    "source_locator": next(
                        (f"stated as {w[1]:g} {w[2]} in the source, in a unit this dataset "
                         f"cannot express; not converted"
                         for w in withheld_units.get(i, []) if w[0] == field),
                        # B63: the same rule for a value that held no NUMBER (a struck 'tbd', a
                        # stated range). This field is typed `number`, so the text cannot ship
                        # in it - but the row must not then claim the sources never spoke.
                        next((f"the merged value was '{_short(u[1], 40)}', which carries no "
                              f"single number this field can hold; not shipped, not invented"
                              for u in unparseable_areas.get(i, []) if u[0] == field),
                             "absent in all sources")),
                    "source_type": "gap",
                    "extractor": "", "confidence": "", "conflict_note": "", "verified": "no",
                })
        # D5: a gap row for an officeAreaVal that was REFUSED, and only then. officeAreaVal is
        # not in the sentinel sweep above (an absent office is the common case and needs no
        # row), but a twin that is absent BECAUSE the text held several figures must leave a
        # trace the operator and the honesty report can see, and that trace may never read
        # "absent in all sources" when the source printed three office lines.
        if i in office_val_refused and "officeAreaVal" not in prov \
                and _is_sentinel(merged.get("officeAreaVal")):
            ledger_rows.append({
                "property_id": i, "record_type": "property", "field": "officeAreaVal",
                "value": "tbd", "source_file": "(none)",
                "source_locator": f"NOT derived from officeArea: {office_val_refused[i]}",
                "source_type": "gap",
                "extractor": "", "confidence": "", "conflict_note": "", "verified": "no",
            })
        for field, note in conflicts.items():
            all_conflicts.append(f"id {i} {field}: {note}")
        for field, note in variants.items():
            all_variants.append(f"id {i} {field}: {note}")
        # A15: a fusion must DISCLOSE ITSELF. See `_fusion_disclosures` for the rule and for
        # every exclusion behind it. Emitted in the existing "id N field: note" format, on the
        # same channel the Gaps Report already reads, so a reader meeting the card meets this too.
        for _ffield, _ffile in _fusion_disclosures(cl, prov):
            all_conflicts.append(
                f"id {i} {_ffield}: this value was read from {_ffile}, a file that contributed no "
                f"record to this property, so it is not one of the sources that built this card. "
                f"Either the value belongs to a DIFFERENT property (two options merged into one "
                f"is the failure this discloses) or this property's own record from that file was "
                f"lost on the way here. Read the cited page against the identity fields on this "
                f"card before the pack goes out.")

    # SEMANTIC VERIFIER (grey-match): fold the blind verifier's ADVISORY disagreement lines
    # into meta.conflicts so the Gaps 'Source conflicts' section surfaces them. These do NOT
    # affect clustering (the matching pass's verdict already drove --match-decisions); they
    # are appended LAST so the field-conflict order above is byte-stable. Best-effort - a bad
    # file is treated as absent (no advisory, never a crash), exactly like --match-decisions.
    if args.match_conflicts and Path(args.match_conflicts).exists():
        try:
            mv_lines = json.loads(Path(args.match_conflicts).read_text(encoding="utf-8-sig"))
            if isinstance(mv_lines, list):
                all_conflicts.extend(str(s) for s in mv_lines if str(s).strip())
        except Exception:
            pass

    IMG.close_doc_cache()  # release the per-brochure PDF handles opened during photo harvest

    # Seed POIs from the library ONLY where they are plausibly near this dataset,
    # so a non-CEE run never inherits the CEE library's POIs. Region-neutral test:
    # keep a library POI within SEED_MAX_KM of any located property; if no property
    # has coordinates yet, fall back to country-code membership; otherwise seed
    # none and let --pois (live OSM) / the dashboard's client-side discovery supply
    # the genuine nearest POIs. Cross-border POIs (e.g. a German port serving a
    # Czech site) survive because the test is distance, not same-country.
    pois = []
    poi_lib = C.ASSETS / "poi_library.json"
    if poi_lib.exists():
        lib = json.loads(poi_lib.read_text(encoding="utf-8-sig"))
        lib_pois = (lib.get("pois", lib) if isinstance(lib, dict) else lib) or []
        located = [p for p in properties
                   if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))]
        countries = {str(p.get("country", "")).upper() for p in properties if p.get("country")}
        if located:
            pois = [q for q in lib_pois
                    if isinstance(q.get("lat"), (int, float)) and isinstance(q.get("lng"), (int, float))
                    and min(_haversine_km(p["lat"], p["lng"], q["lat"], q["lng"]) for p in located) <= SEED_MAX_KM]
        else:
            pois = [q for q in lib_pois if str(q.get("country", "")).upper() in countries]
        if len(pois) != len(lib_pois):
            print(f"   POI seed: kept {len(pois)}/{len(lib_pois)} library POIs near this dataset "
                  f"(out-of-region dropped; live --pois / client-side discovery supply the rest)")

    # generatedAt derives from the INPUTS, not wall-clock now(): same inputs ->
    # byte-identical canonical.json, so the enrich resume stamp, freeze diffs and
    # "same inputs -> identical built.html" all actually hold. Prefer the SOURCE
    # files' mtimes (stable even when --no-resume rewrites the record files);
    # fall back to the record files when no source file is resolvable.
    src_files = [_resolve_source(source_dir, r.get("__meta", {}).get("source_file", ""))
                 for r in all_records]
    newest_in = max((f.stat().st_mtime for f in src_files if f is not None), default=0.0) \
        or max((Path(f).stat().st_mtime for f in args.records if Path(f).exists()),
               default=0.0)
    # round to DATE (not seconds): the HTML hero/footer show this same input-date at
    # DATE granularity (load_hero `compiled`/`default_date` below), and generatedAt
    # is never rendered with a time component - nothing reads it as a datetime. A
    # bare-second stamp made canonical.json byte-unstable across environments whose
    # input mtimes differ by seconds (re-download / unzip / checkout of identical
    # content); a date collapses that jitter to the day, matching the only place the
    # date is shown. HTML and ledger bytes are unaffected (neither reads generatedAt).
    generated_date = _dt.datetime.fromtimestamp(newest_in).date().isoformat() if newest_in else ""
    meta = {
        "client": ((_load_yaml(args.project_yaml) or {}).get("client") or {}).get("name", "Client"),
        "generatedAt": generated_date,
        "templateVersion": C.load_version().get("label", ""),
        "hero": load_hero(Path(args.project_yaml) if args.project_yaml else None, properties,
                          default_date=generated_date),
        "sourceFiles": sorted({r.get("__meta", {}).get("source_file", "?") for r in all_records}),
        "conflicts": all_conflicts,
        "notationVariants": all_variants,
        "placeholderAudit": placeholder_audit,
        # the dataset's unit convention (source units KEPT) - the builder formats
        # the hero KPI strip and its sub-labels from this
        "units": {"area": area_unit, "rent": rent_unit},
        # dashboard chrome language (Stage-0 Q3). OPTIONAL + default-safe: absent ->
        # "English" -> en. The builder resolves it to the i18n table at render time
        # (per-key English fallback); DATA is never translated.
        "language": (args.language or "English"),
    }
    if meta_offspec:
        meta["offspec"] = meta_offspec
    # A9: the ORIGINAL figure behind every band strike, so the honesty report can print what was
    # withdrawn beside the conflict line saying why. CONDITIONAL, mirroring meta["offspec"]: a run
    # where the band strikes nothing is byte-identical to before this change.
    if all_struck:
        meta["struck"] = all_struck
    # A14a: the contributing sources per property, with each one's stated postcode. NOT
    # conditional, unlike the keys around it - every run has clusters, so an absent key would mean
    # "this merge predates the change", which is precisely the ambiguity the over-merge gate must
    # not have to guess at. A gate that cannot tell "no disagreement" from "no data" either passes
    # a fused pack or blocks every older one.
    meta["clusterSources"] = cluster_sources
    # B7: conditional, mirroring meta["offspec"] - a run with no new fields must be
    # byte-identical to before this change.
    if meta_newfields:
        meta["newFields"] = meta_newfields
    if plan_near_miss_all:
        meta["planNearMiss"] = plan_near_miss_all
    if unit_assumptions:  # an ASSUMED unit is an honest gap, never a silent stamp
        meta["unitAssumptions"] = unit_assumptions
    if stated_totals:  # P1-1: input to `gate_runner arithmetic`; absent when no source states one
        meta["statedTotals"] = stated_totals
    if computed_sums:  # F11: CONDITIONAL like every optional meta key; a run with no itemised
        meta["computedSums"] = computed_sums   # office lines stays byte-identical
    if open_capture_by_id:  # read-but-not-shown captures, for the per-property view
        meta["openCapture"] = open_capture_by_id
    # B47: options EXCLUDED by the broker's source-authority answer. CONDITIONAL, exactly like
    # meta["overrides"] above, so a run without an authority answer stays byte-identical. A
    # property removed from a client's own longlist must be visible, so this rides into the
    # Gaps Report rather than vanishing between two runs with different answers.
    if EXCLUDED:
        meta["excluded"] = EXCLUDED
    # B54: the languages the interpretation agents declared. CONDITIONAL, like every other
    # optional meta key above, so a run where nothing declares one stays byte-identical.
    _src_langs = collect_source_languages(all_records)
    if _src_langs:
        meta["sourceLanguages"] = _src_langs
    # P1-4: CONDITIONAL, mirroring meta["offspec"]/["unitAssumptions"] - an overrides-free run must
    # stay byte-identical to today, which is what fixture_test/smoke_test guard.
    if any(OV_REPORT.get(k) for k in ("applied", "stale", "ambiguous", "superseded", "invalid")):
        meta["overrides"] = {k: OV_REPORT[k] for k in
                             ("applied", "stale", "ambiguous", "superseded", "invalid")
                             if OV_REPORT.get(k)}
    ledger_rows += override_rows
    # an explicit BCP-47 locale (e.g. de-AT) overrides the language's default region
    if str(getattr(args, "locale", "") or "").strip():
        meta["locale"] = args.locale.strip()
    # Phase 2 (fallback): bake the translate-once cache into meta.ui_overrides so the
    # fallback chrome rides canonical and render()/validate-html reproduce it byte-for-
    # byte. ONLY keys that exist in i18n.EN are kept - a leading _en_sha (or any _* meta
    # key) and any stray/DATA key are dropped, never injected; CHROME only, never data.
    # Optional + default-safe: blank/absent/unloadable/empty -> the key is NOT set, so
    # the bundled/EN path is byte-identical to Phase 1.
    _ui_ov_path = str(getattr(args, "ui_overrides", "") or "").strip()
    if _ui_ov_path:
        _loaded = I18N.load_fallback_cache(_ui_ov_path)
        if isinstance(_loaded, dict) and _loaded:
            _baked = {k: v for k, v in _loaded.items() if k in I18N.EN}
            if _baked:
                meta["ui_overrides"] = _baked
    # carry the client's questionnaire requirements through, if any (the orchestrator
    # uses them for the size-slider default and hard-requirement flags). Not injected
    # into the HTML - meta is audit/orchestrator data, so this never affects the chrome.
    if args.requirements and Path(args.requirements).exists():
        try:
            reqs = json.loads(Path(args.requirements).read_text(encoding="utf-8-sig"))
            if reqs:
                meta["requirements"] = reqs
        except Exception:
            pass

    canonical = {
        "meta": meta,
        "properties": properties,
        "pois": pois,
        "regions": {},
    }

    # ATOMIC write: a shell-cap kill mid-write (routine in Cowork's ~45s cap) must
    # never leave a truncated canonical that --resume then treats as current
    out_path = Path(args.out)
    C.atomic_write_text(out_path, json.dumps(canonical, ensure_ascii=False, indent=2))
    print(f"OK canonical -> {args.out}  ({len(properties)} properties, {len(pois)} POIs)")

    # THE CONSIDERED SET -> work/media_considered.json. Written AFTER canonical, and never read
    # back by anything that produces canonical, so it is provably derived: the dataset is already
    # on disk and byte-final by the time this runs.
    #
    # `unassigned` is the bucket that had no name before: deck pages NO property claimed. Those
    # pages are outside the whole run's reach - no gallery, no plan tier, no audit ever looked at
    # them - and on a multi-property or donor deck that is exactly where a missed site plan
    # hides. Computing it needs the deck's PAGE COUNT, which is metadata (no decode).
    try:
        _claimed_by_deck: dict = {}
        for _c in media_considered:
            for _nm2, _d in (_c.get("decks") or {}).items():
                _claimed_by_deck.setdefault(_nm2, {"path": _d.get("path"), "pages": set()})
                _claimed_by_deck[_nm2]["pages"].update(_d.get("claimed") or [])
        _unassigned = []
        for _nm2, _d in sorted(_claimed_by_deck.items()):
            _facts = IMG.deck_media_facts(Path(_d["path"])) if _d.get("path") else {}
            _n = _facts.get("pages")
            if not _n:
                continue
            _miss = [i for i in range(int(_n)) if i not in _d["pages"]]
            if _miss:
                _unassigned.append({"file": _nm2, "path": _d["path"], "pages": _miss,
                                    "deck_pages": int(_n),
                                    "large_images": _facts.get("large_images")})
        C.atomic_write_text(
            out_path.resolve().parent / "media_considered.json",
            json.dumps({"schema_version": 1,
                        "generatedAt": generated_date,
                        "capabilities": IMG.media_capabilities(),
                        "properties": media_considered,
                        "unassigned": _unassigned}, ensure_ascii=False, indent=2))
    except Exception as _e:
        print(f"(media considered-set sidecar skipped: {type(_e).__name__}: {_e})")
    finally:
        # `deck_media_facts` opens each deck through IMG's shared doc cache. Release the handles:
        # on Windows a held handle blocks an in-process caller's temp-dir cleanup, and this runs
        # after canonical is already on disk, so there is nothing left for merge to read.
        try:
            IMG.close_doc_cache()
        except Exception:
            pass

    if args.ledger:
        import io as _io
        buf = _io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(ledger_rows[0].keys()) if ledger_rows else
                           ["property_id", "field", "value"], lineterminator="\n")
        w.writeheader()
        w.writerows(ledger_rows)
        C.atomic_write_text(Path(args.ledger), buf.getvalue())  # atomic + LF, like canonical (review #2)
        print(f"OK ledger -> {args.ledger}  ({len(ledger_rows)} rows)")


def _confidence(pr: dict) -> str:
    """Ledger confidence from the row's real source. An LLM read is Medium: a brochure
    'text interpretation' OR a 'vision transcription' (both produced by the isolated
    interpretation sub-agent), as is an image/web read (source-traceability.md - a
    less-certain source, and a G-honesty spot-check priority). High is reserved for a
    DETERMINISTIC structured extract (a tracker cell, an email field). Derived values
    inherit via the locator (which carries the basis locator)."""
    loc = str(pr.get("locator", "")).lower()
    if ("vision" in loc or "interpretation" in loc
            or pr.get("source_type") in ("image", "web")):
        return "Medium"
    return "High"


def _short(v, n=60):
    s = str(v)
    return s[:n] + ("…" if len(s) > n else "")


def _load_yaml(path):
    if not path or not Path(path).exists():
        return {}
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {}


if __name__ == "__main__":
    C.force_utf8_stdout()   # D16: a non-ASCII value in printed output must not
    #                        crash the print on a cp1252 Windows console
    main()
