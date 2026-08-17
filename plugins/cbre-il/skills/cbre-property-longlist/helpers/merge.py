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
_CERT_SENTINELS = {"", "tbd", "tbc", "—", "-", "??", "n/a", "none", "null"}


def _cert_unknown(v) -> bool:
    return v is None or str(v).strip().lower() in _CERT_SENTINELS


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
    if isinstance(e, str) and not _cert_unknown(e) \
            and _BREEAM_GRADE.search(e) and not _EPC_BAND.match(e.strip()):
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
                    "multi": "all" if str(e.get("multi") or "").lower() == "all" else "one"})
    return out, bad


# The sentinel family for the override `expect` guard ONLY. Deliberately NARROWER than
# normalize.looks_unknown (no market phrases such as "a consultar" - a broker may want the
# guard to notice one), and widened HERE at the caller rather than in the shared set, exactly
# as that function's docstring instructs and as deliver._is_tbd already does.
_EXPECT_ABSENT = frozenset({"", "tbd", "tbc", "—", "-", "n/a", "none", "??"})


def _ov_absent_like(v) -> bool:
    return v is None or str(v).strip().lower() in _EXPECT_ABSENT


def _ov_expect_same(cur, want) -> bool:
    """`expect` equality where BOTH SIDES ABSENT is a match (the twin of repairs._expect_same).

    A field an extractor left unset holds None, while the ledger, the Gaps Report and the card
    all render it `tbd`. Comparing str(None) to 'tbd' made the documented `expect` form refuse
    every such entry as SUPERSEDED, so the guard fired on its own correct premise.
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
            report["applied"].append({
                "id": ov["id"], "where": w, "set": {k: ov["set"][k] for k in old},
                "old": old, "why": ov["why"], "verified_by": ov["verified_by"],
                "locator": at, "partial": stale_field})
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


def dominant_units(records: list[dict]) -> tuple[str, str]:
    """The dataset's unit convention = the units MOST source records state
    (UK/imperial inputs ship imperial, metric inputs ship metric - user rule).
    Defaults: 'sq m' and '€/sq m/yr' when no record states a unit."""
    from collections import Counter
    a = Counter(r.get("areaUnit") for r in records
                if isinstance(r, dict) and r.get("areaUnit"))
    rn = Counter(r.get("rentUnit") for r in records
                 if isinstance(r, dict) and r.get("rentUnit"))
    return (a.most_common(1)[0][0] if a else "sq m",
            rn.most_common(1)[0][0] if rn else "€/sq m/yr")


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
_EPC_GATE_RX = re.compile(r"^(?:target(?:ing|ed)?\s+)?(?:epc\s*)?[A-G]\+?$", re.I)


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
    strikes a field to "tbd": `breeam` passes on CONTAINING a band word (so "Target BREEAM
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
        lo, hi = N.area_band_for(area_unit, field=field)  # plotArea gets the SITE ceiling (T1)
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
        return "pass" if _EPC_GATE_RX.match(s) else "fail"
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
            dropped.append({
                "name": cluster_label(cl),
                "evidenced_by": sorted(fams),
                "source_files": sorted({str((r.get("__meta") or {}).get("source_file") or "")
                                        for r in cl if (r.get("__meta") or {}).get("source_file")}),
                "why": (f"not evidenced by the {fam}, which you set as the guiding source for "
                        f"what belongs on this longlist"),
            })
    if not kept:
        # fail OPEN: an authority that matches nothing is far more likely a mis-detection than
        # a client with zero properties. Ship the union and let the Gaps Report say so.
        return list(clusters or []), []
    return kept, dropped


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
                  variants: dict | None = None) -> tuple[dict, dict, dict]:
    """`variants` is an OPTIONAL out-parameter (I10): pass a dict and it is filled with
    field -> note for every pair that states the same fact in different notation. It is an
    out-param rather than a fourth return value deliberately - the 3-tuple has thirteen call
    sites across the eval battery, and widening it would have been churn and risk for nothing."""
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
        # P1-4 PRECEDENCE PIN. `out[field]`/`prov[field]` are set by the FIRST record in `order`
        # holding a non-unknown value, so overriding a record that LOSES the precedence contest
        # would change nothing visible - a silent no-op that looks exactly like the bug the
        # override was written to fix. Explicit order: broker override > LLM pick > precedence.
        # Compared by id(), never by `in` (dict equality would also pull in an identical sibling).
        # Byte-identical when nothing is locked.
        _locked = [r for r in order
                   if field in set((r.get("__meta") or {}).get("override_locked") or ())]
        if _locked:
            _lids = {id(r) for r in _locked}
            order = _locked + [r for r in order if id(r) not in _lids]
        chosen = None
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
        if field in out and not N.looks_unknown(out[field]) \
                and _pick_gate_verdict(field, out[field], rent_unit) == "fail":
            _bad = out[field]
            out[field] = "tbd"
            _src = (prov.get(field) or {}).get("source_file") or "?"
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
                 plan_rejected: set | None = None
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
    photo_rec/plan_rec is None when the placeholder / no plan was used."""
    photo = plan = None
    photo_rec = plan_rec = None
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
    # GALLERY (cap IMG.GALLERY_MAX, best-first): the photos for the carousel. PAGE-SCOPED
    # per record so a MULTI-PROPERTY deck contributes only THIS property's pages, never a
    # neighbour's. The hero is guaranteed first; extractor-embedded record photos are
    # included; deduped by URI bytes. A render-tier hero that no embedded scan reproduces
    # simply stays as the sole/first entry. The placeholder property gets a 1-item gallery.
    gallery: list[str] = []

    def _g_add(uri):
        if isinstance(uri, str) and uri.startswith("data:image/") and uri not in gallery:
            gallery.append(uri)

    _g_add(photo)
    for r in embedded:
        _g_add(r.get("photo"))
    # PAGES this property may draw carousel photos from: each record's page_no
    # UNION its validated __meta.image_pages (the LLM's "these pages show THIS
    # property" pick), keyed by the resolved source. When NO record carries
    # image_pages this reduces to the page_no-only set -> byte-identical to today.
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
    for src_str, pgs in sorted(pages_by_src.items()):
        # the deterministic anti-leak guard (computed once over ALL clusters)
        # tells us which of these pages are FOREIGN (owned/claimed by another
        # property of the same deck); subtract them before harvesting. None /
        # absent -> no-op, so a cluster's own page_no is never foreign.
        allowed = pgs - (foreign_pages or {}).get(src_str, set())
        if not allowed:
            continue  # every claimed page was foreign: harvest nothing for this deck
            # (gallery_for_pages treats an empty page set as "whole deck" - never that here).
            # A cluster's own page_no is normally its own anchor (not foreign), so this rarely
            # fires; the skip is a DEFENSIVE guard - if a clustering anomaly made two properties
            # anchor the same page it is foreign to both, and this prevents the empty-set
            # whole-deck leak.
        try:
            uris, _total = IMG.gallery_for_pages(Path(src_str), sorted(allowed), budget_kb, image_cache,
                                                 exclude_by_page=excl_by_src.get(src_str))
        except Exception:
            uris = []
        for uri in uris:
            _g_add(uri)
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
    if plan is None:
        _nm_acc: list = []  # near-miss pages (a plan signal that a precision guard rejected)
        for src_str, pgs in sorted(pages_by_src.items()):
            allowed = pgs - (foreign_pages or {}).get(src_str, set())
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
                uri, pno = IMG.best_plan_page_render(Path(src_str), sorted(allowed),
                                                     budget_kb, image_cache, near_miss=_nm)
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
    return photo, plan, photo_rec, plan_rec, tried, gallery[:IMG.GALLERY_MAX]


def prewarm_images(all_records, source_dir, image_cache, budget_kb,
                   seconds: float = 30.0, workers: int | None = None) -> tuple:
    """Warm the image cache merge needs, in PARALLEL and TIME-BOUNDED, so the slow
    raster+compress harvest happens up front across CPUs instead of serially inside merge
    (which then runs as cache hits and finishes in one shell window). Each unit writes its
    own atomic cache, so a budget/kill exit loses at most the unit in flight - a re-run
    continues. Returns (done_units, total_units). Pure accelerator: identical cache bytes,
    so merge output is unchanged."""
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
    for s_str, sfx in decks.items():
        s = Path(s_str)
        try:
            n = (min(len(list(IMG._get_pptx(s).slides)), 80) if sfx == ".pptx"
                 else min(IMG._get_doc(s).page_count, 80))
        except Exception:
            n = 0
        for p in range(n):
            geom_units.append(("gidxpage", s_str, p, budget_kb, cache_str))
            if sfx != ".pptx":       # PPTX has no pdfplumber geometry tier
                geom_units.append(("placedpage", s_str, p, 0, cache_str))
    IMG.close_doc_cache()            # release parent PDF handles before forking workers
    all_units = geom_units + page_units
    total = len(all_units)
    if total == 0:
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

    _run(geom_units)                 # phase 1: page-grained geometry + gallery (no herd)
    _run(page_units)                 # phase 2: heroes (geometry now warm)
    done = sum(1 for u in all_units if IMG._unit_cached(u))
    return (done, total)


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
        disp = p.get("warehouseRent")
        if isinstance(disp, str) and disp.strip() and not N.looks_unknown(disp):
            unit = p.get("rentUnit") or N.rent_unit_of_text(disp)
            num = N.extract_first_number(disp)
            if num is not None and N.MONTHLY_RX.search(disp):
                num = round(num * 12, 2)
            lo, hi = N.rent_unit_band(unit)
            if num is not None and lo <= num <= hi:
                p["warehouseRentVal"] = num
                if unit:
                    p["rentUnit"] = unit
                p["warehouseRent"] = N.rent_display(num, unit)
    # office rent NUMERIC (officeRentVal) for the total-rent split: parse the office
    # rent string in the SAME currency/per-area convention + plausibility band as the
    # warehouse rent (annualising a monthly quote x12). The office DISPLAY string is
    # left untouched; only a clean numeric is extracted. Never invented - absent stays absent.
    if not isinstance(p.get("officeRentVal"), (int, float)):
        odisp = p.get("officeRent")
        if isinstance(odisp, str) and odisp.strip() and not N.looks_unknown(odisp):
            ounit = p.get("rentUnit") or N.rent_unit_of_text(odisp)
            onum = N.extract_first_number(odisp)
            if onum is not None and N.MONTHLY_RX.search(odisp):
                onum = round(onum * 12, 2)
            olo, ohi = N.rent_unit_band(ounit)
            if onum is not None and olo <= onum <= ohi:
                p["officeRentVal"] = onum
    # office area NUMERIC (officeAreaVal) for total GLA: officeArea may be a number or
    # a string ('13576 sq ft'); extract the figure in the record's OWN area unit (the
    # minority-unit conversion in main() then aligns it to the dataset unit, like
    # warehouseArea). A '% of GLA' phrasing is skipped (not an absolute area).
    if not isinstance(p.get("officeAreaVal"), (int, float)):
        oa = p.get("officeArea")
        if isinstance(oa, (int, float)) and not isinstance(oa, bool):
            if oa > 0:
                p["officeAreaVal"] = float(oa)
        elif isinstance(oa, str) and oa.strip() and not N.looks_unknown(oa) and "%" not in oa:
            oan = N.extract_first_number(oa)
            if oan is not None and oan > 0:
                p["officeAreaVal"] = oan
    # expansionParkVal companion
    if "expansionPark" in p and "expansionParkVal" not in p:
        v = N.normalize_number(p["expansionPark"])
        if v is not None and v >= 1000:
            p["expansionParkVal"] = v
    # fill sentinels for every chrome-read key (honest unknowns, never invented)
    return C.fill_render_sentinels(p)


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
    # hero_eyebrow / hero_title_html / hero_lede_fmt and are applied by
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
        "lede": market.get("lede") or "",
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

    def _is_sentinel(v):
        return v is None or str(v).strip().lower() in {"tbd", "—", "", "none", "??"}

    properties, ledger_rows, all_conflicts = [], [], []
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
    plan_near_miss_all: list = []  # per-property near-miss plan pages -> Gaps Report (light Fix 4)
    unit_assumptions: list = []    # areas whose unit the SOURCE never stated -> Gaps Report
    # B58: {property_id: [(field, raw value, unrecognised unit)]}. A figure the dataset cannot
    # express is withdrawn rather than mislabelled, and its gap row must say THAT instead of
    # claiming the source was silent - the false-absence claim both critical reviewers blocked on.
    withheld_units: dict = {}
    stated_totals: dict = {}       # P1-1: id -> the SOURCE's own stated total area (arithmetic gate)
    for i, cl in enumerate(clusters, start=1):
        variants: dict = {}   # I10: same fact, different notation - reported, not adjudicated
        merged, prov, conflicts = merge_cluster(cl, FIELD_DECISIONS or None, variants)
        merged["id"] = i
        merged = canonicalize(merged)
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
        _silent_any = False
        _withheld: list = []   # B58: (field, raw value, its unrecognised unit)
        for fld in ("warehouseArea", "plotArea", "officeAreaVal"):
            if not isinstance(merged.get(fld), (int, float)):
                continue
            _u = (prov.get(fld) or {}).get("areaUnitOfSource")
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
        merged["photo"], plan_uri, photo_rec, plan_rec, tried_pages, gallery = attach_media(
            cl, source_dir, args.image_budget_kb, image_cache=image_cache,
            foreign_pages=foreign_by_cluster[i - 1],
            plan_offlimits=plan_offlimits_by_cluster[i - 1],
            plan_near_miss=_cluster_nm,
            plan_rejected=PLAN_REJECTED)
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
                    # gallery is the whole-deck top photos (best_hero_in_deck's pick is the
                    # first of that ranked set, so the hero stays gallery[0]).
                    try:
                        g_uris, _gt = IMG.gallery_for_deck(bsrc, args.image_budget_kb, image_cache)
                    except Exception:
                        g_uris = []
                    merged["gallery"] = g_uris or [hero]
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
                    override_rows.append({
                        "property_id": i, "record_type": "override", "field": _f,
                        "value": _short(_new) or "tbd",
                        "source_file": _oa["where"]["source_file"],
                        "source_locator": (f"work/overrides.json#{_oa['id']} at {_oa['locator']}"
                                           f" | was: {_short(_oa['old'].get(_f))} -> now: "
                                           f"{_short(_new)} | why: {_oa['why']}"),
                        # non-empty and != "gap": ledger.REQUIRED is satisfied by construction and
                        # trace-coverage still counts the field as traced. An override can never
                        # make a field untraceable, and never launders one into a gap-free field
                        # without leaving this row behind.
                        "source_type": "override", "extractor": "manual",
                        "confidence": "manual",
                        "conflict_note": ("manual correction applied post-extraction; "
                                          "work/extract was NOT edited"),
                        "verified": ("yes" if _oa.get("verified_by") else ""),
                    })
        # ledger rows for every populated field (with conflict note where one occurred)
        for field, pr in prov.items():
            ledger_rows.append({
                "property_id": i, "record_type": "property", "field": field,
                "value": _short(merged.get(field)), "source_file": pr.get("source_file", ""),
                "source_locator": pr.get("locator", ""), "source_type": pr.get("source_type", ""),
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
            if _is_sentinel(val):
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
                        "absent in all sources"),
                    "source_type": "gap",
                    "extractor": "", "confidence": "", "conflict_note": "", "verified": "no",
                })
        for field, note in conflicts.items():
            all_conflicts.append(f"id {i} {field}: {note}")
        for field, note in variants.items():
            all_variants.append(f"id {i} {field}: {note}")

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
    main()
