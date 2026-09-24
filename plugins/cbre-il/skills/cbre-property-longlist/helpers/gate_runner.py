#!/usr/bin/env python3
"""gate_runner.py - mechanical (script) halves of the QA gates.

Subcommands (judgement halves run as isolated reviewer sub-agents, not here):
  PRE-BUILD:
    validate-data   G-schema     : canonical.json valid against the schema + pair-consistency
    self-check      G-selfcheck  : schema field set == tokens/markers the template/build use
    coverage        G-coverage   : no dup (park+city+dev+area); no over-merge (one property whose
                                   contributing records state two different postal codes); per-record
                                   core-field fill or explicit tbd
                                   (it does NOT reconcile inputs to outputs - that is input-accounting)
    input-accounting G-inputs    : every discovered input contributed fields, contributed a photo, was
                                   recorded unreadable, or has no spine consumer - nothing vanishes
    trace-coverage  G-trace      : every non-sentinel source-able field has a ledger row (source_type != gap)
    images          G-images     : every photo is a valid data URI; lists unmatched assets / placeholders
    enrichment      G-enrichment : regions/POIs/distances sourced+dated, no copied figure, not silently empty
  POST-BUILD:
    validate-html   G-html       : delivered HTML == render(canonical) byte-for-byte; blocks round-trip; chrome sha
    reconcile       G-reconcile  : every id in HTML <-> canonical; KPI strip matches the data
    i18n            G-i18n       : rendered chrome complete (the full EN key set), no unfilled token, well-formed
                                   LOCALE, no silent EN fallback for an expected-localised language, placeholders intact
  REVIEW WINDOW:
    freeze          (--check)    : snapshot/verify canonical bytes so parallel reviewers all judge the same artefact

Each subcommand prints a scorecard fragment and exits non-zero on a blocking failure.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C
import build_dashboard
import normalize as N
# the SAME fuzzy scorer match.py and extract_xlsx.py use, so the shadow-key pairing below (D15)
# scores names the way the tracker column-map does; the shim is the documented offline fallback
try:
    from rapidfuzz import fuzz as _fuzz
except Exception:                                   # sandbox without rapidfuzz
    from rapidfuzz_shim import fuzz as _fuzz

# a genuinely long field (e.g. an accumulated conflict_note spanning many
# contributing sources) can exceed Python's defensive default (131072) - this
# is a legitimate long value, not a memory bomb, so every ledger reader below
# must accept it.
csv.field_size_limit(2**31 - 1)


def _ok(msg): print(f"[PASS] {msg}")
def _bad(msg): print(f"[FAIL] {msg}")


def _stated_year(s) -> int | None:
    """The most recent 4-digit year mentioned in an *AsOf string ('2024', 'Q1 2024',
    'March 2023', '2022-12'), or None if none is parseable."""
    yrs = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", str(s or ""))]
    return max(yrs) if yrs else None


def _today():
    """Module-level so tests can pin the clock (the Jan-May rule depends on it)."""
    from datetime import date
    return date.today()


# --------------------------------------------------------------------------- #
def cmd_validate_data(args) -> int:
    data = C.load_canonical(Path(args.canonical))
    errs = C.validate_canonical(data)

    # display/numeric pair-consistency (warehouseRent <-> warehouseRentVal)
    for p in data.get("properties", []):
        rent, val = p.get("warehouseRent"), p.get("warehouseRentVal")
        if isinstance(val, (int, float)) and isinstance(rent, str):
            # parse the FULL first number (separator/decimal aware), not the first digit run:
            # findall[0] misread thousands/ranges ('€1,234' -> '1') and false-flagged (S4-46)
            got = N.extract_first_number(rent)
            if got is not None and abs(got - float(val)) > 0.5:
                errs.append(f"property id={p.get('id')}: warehouseRentVal {val} "
                            f"does not match warehouseRent '{rent}' - warehouseRentVal must be the "
                            f"ANNUAL per-area figure shown in warehouseRent (in its own convention, "
                            f"€/m² or £/sq ft; annualise a monthly quote x12)")

    # unique ids (single-pass Counter, not O(n^2) ids.count per element - #32)
    ids = [p.get("id") for p in data.get("properties", [])]
    if len(ids) != len(set(ids)):
        _id_counts = Counter(ids)
        errs.append(f"duplicate property ids: {[i for i in ids if _id_counts[i] > 1]}")

    # regionCode resolves
    regions = data.get("regions", {})
    for p in data.get("properties", []):
        rc = p.get("regionCode")
        if rc and rc not in regions:
            errs.append(f"property id={p.get('id')}: regionCode '{rc}' not in regions{{}}")

    # DISCLOSE a degraded validator. "schema clean" must not read the same whether it was
    # checked by the real JSON-Schema validator or by the dependency-free structural fallback.
    _deg = C.schema_degraded()
    if errs:
        for e in errs:
            _bad(e)
        print(f"STATUS: BLOCKED ({len(errs)} schema/consistency issues)")
        return 1
    if _deg:
        print(f"  [note] schema checked in DEGRADED mode ({_deg}): required keys + field TYPES "
              f"only, not the full JSON Schema (enum/format/range rules were not applied). "
              f"Install jsonschema for the full floor.")
        _ok(f"structural + type + pair-consistency clean, DEGRADED "
            f"({len(data.get('properties', []))} properties)")
    else:
        _ok(f"schema + pair-consistency clean ({len(data.get('properties', []))} properties)")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
def cmd_self_check(args) -> int:
    """Schema field set vs the tokens/markers the template and builder rely on.
    Guards against silent drift between docs, template and code."""
    issues = []
    template = C.load_template()
    for tok in C.CONFIG_TOKENS:
        if "{{" + tok + "}}" not in template:
            issues.append(f"template missing token {{{{{tok}}}}}")
    for marker in C.DATA_MARKERS.values():
        if marker not in template:
            issues.append(f"template missing data marker {marker}")
    # v19 i18n: the template must carry the injected UI/LOCALE bootstrap (pre-render
    # form: `const UI = {{ui_json}}` + `const LOCALE = "{{locale}}"`), and the i18n
    # table must import with a non-empty EN baseline. Catches future template/table
    # drift at preflight (the maintenance battery runs self-check).
    if "const UI = {{ui_json}}" not in template:
        issues.append("template missing the v19 i18n bootstrap (const UI = {{ui_json}})")
    if "const LOCALE =" not in template:
        issues.append("template missing the v19 i18n locale const (const LOCALE =)")
    try:
        import i18n as _I18N
        if not getattr(_I18N, "EN", None):
            issues.append("i18n.EN is empty (the English chrome baseline must be non-empty)")
        else:
            # KPI-sub format keys are .format()'d by build_dashboard.compute_kpis; a dropped
            # {area}/{unit} placeholder does NOT raise (str.format tolerates unused kwargs) -
            # it silently emits a sub with the value missing. Guard the EN baseline here so
            # the drift is caught PRE-build, not shipped. (#33)
            for _k, _ph in (("kpi_wh_area_sub_fmt", "{area}"), ("kpi_rent_sub_fmt", "{unit}")):
                if _ph not in str(_I18N.EN.get(_k, "")):
                    issues.append(f"i18n.EN['{_k}'] lost its {_ph} placeholder "
                                  f"(compute_kpis .format()s it; a dropped placeholder silently "
                                  f"emits a KPI sub with the value missing)")
    except Exception as e:
        issues.append(f"i18n import failed: {e}")
    # schema loads and is well-formed
    try:
        C.load_json(C.SCHEMA_FILE)
    except Exception as e:
        issues.append(f"schema unreadable: {e}")

    if issues:
        for i in issues:
            _bad(i)
        print("STATUS: BLOCKED")
        return 1
    _ok("template tokens + markers + schema consistent")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
# THE UNKNOWN-VALUE PREDICATE, DELEGATED (F5/F6, SEAM-13). This module carried THREE private
# sentinel sets: `_cov_filled` (four members), `_absent` (seven) and trace-coverage's inner
# `is_sentinel` (six), each a different subset of the family, none carrying `tba`/`tbs`, and
# two of them reading a stated "none" as ABSENCE. The extraction contract says the opposite:
# "Sprinklers: None" is a stated negative, DATA, and it must trace to a source like any other
# value. All three now read `normalize.UNKNOWN_FORMS` through the shared readers, so a form
# added there is seen here the same day and the guard eval sees no literal in this file.
#
# TWO READERS, NOT ONE, because of what KIND of value a site judges. Three family members
# ("na", "nc", "sc") are also assigned ISO alpha-2 country codes, and the v41 consolidation
# measured what blanket delegation does to a code-valued field: `enrich._is_unknown_cc` moved
# False -> True for all three and dropped real countries from the map and the KPI. So a field
# in CODE_FIELDS is judged by `looks_unknown_code` (the same family minus that stated
# exemption) and everything else by `looks_unknown`. Callers pass the field name when they
# have one; a call without it gets the prose reading, which is right for every field this
# module judges except `country`.
CODE_FIELDS = frozenset({"country"})


def _unknown(v, field=None) -> bool:
    """True when `v` is an effective unknown for `field`; the ONE predicate this module uses."""
    return N.looks_unknown_code(v) if field in CODE_FIELDS else N.looks_unknown(v)


def _cov_filled(v, field=None) -> bool:
    """A field counts as populated for coverage: present and not an unknown form.
    Includes negative numbers (western/southern lat/lng), zero, and a stated "none" (a
    negative the source printed is data); only the shared unknown family is empty."""
    return v is not None and not _unknown(v, field)


def _is_land_record(p: dict) -> bool:
    """Land/plot-for-sale option, detected STRUCTURALLY (no language tokens, so it
    holds in any market): no real warehouse area, but a plot area or a land price.
    Such a site has no warehouse rent/specs by nature, so coverage scores it on
    land-appropriate fields instead of failing it for missing warehouse data."""
    has_wh = isinstance(p.get("warehouseArea"), (int, float)) and p["warehouseArea"] > 0
    has_land = (_cov_filled(p.get("plotArea"), "plotArea")
                or _cov_filled(p.get("landPrice"), "landPrice"))
    return (not has_wh) and has_land


WAREHOUSE_CORE = ["warehouseArea", "warehouseRent", "status", "city", "developer", "lat", "lng"]
LAND_CORE = ["plotArea", "landPrice", "city", "lat", "lng"]

# capture-symmetry's materiality set: coverage's own core, minus the two fields enrichment
# ASSIGNS rather than a reader capturing them (lat/lng), so it can never drift from what the
# coverage gate already calls core.
CAPTURE_CORE_FIELDS = frozenset(WAREHOUSE_CORE + LAND_CORE) - {"lat", "lng"}
#: records affected before a non-core asymmetry can be promoted to SIGNAL
SIGNAL_MIN_RECORDS = 5
#: records elsewhere that must ALREADY carry the field before its absence means anything.
#: Without this, "affected" alone promotes the rarest fields: one flyer mentioning
#: `manoeuvringYard` would outrank a core field, because everything else lacks it. A field is
#: only expected of a deck once the corpus has actually established it.
SIGNAL_MIN_PRESENT = 3


def _carrier_attachment_index(work: Path, inv: dict | None = None) -> dict:
    """{carrier .msg/.eml basename (lowercased): [saved attachment basenames]}.

    THE LINK THE ACCOUNTING BUCKETS WERE MISSING. A saved attachment enters the ledger under
    its OWN filename (Broker07.pdf), never its carrier's (Broker07.msg), so an email whose body
    held no quotable property data - it just carried the brochure - looked to the gate like a
    source that contributed nothing at all. Live: 11 of 16 broker emails were called
    "silently vanished" on a run where every brochure was read and shipped.

    Built from the `.from_email.json` sidecars extract_email writes beside each saved
    attachment, not from a work artefact, so the link survives a deleted work dir and a
    resumed run - the same reason from_email_index reads them. The sidecar lists what was
    actually SAVED, which is what makes the credit honest: an attachment that was declared
    and never written is absent here, and its carrier stays unaccounted and keeps blocking.
    """
    if inv is None:
        try:
            inv = json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
        except Exception:
            inv = {}
    idx: dict = {}
    try:
        import extract_email as _EM
        folder = str((inv or {}).get("folder") or "")
        if not folder:
            return idx
        for rel, fe in (_EM.from_email_index(Path(folder)) or {}).items():
            carrier = Path(str((fe or {}).get("file") or "")).name.lower()
            if carrier:
                idx.setdefault(carrier, []).append(str(rel).rsplit("/", 1)[-1])
    except Exception:
        return {}
    return {k: sorted(set(v)) for k, v in idx.items()}


def _accounting_buckets(work: Path, canonical: Path) -> dict:
    """Classify EVERY discovered input into exactly one bucket. (B08)

    Nothing reconciled inputs against outputs: 11 decks and a 12-row tracker could ship 23
    properties or 9 and both were ALL-PASS, and `cmd_coverage`'s docstring claimed "every
    cluster produced records" while only checking duplicates and per-record fill.

    The obvious floor - "every input produced a record or is listed unreadable" - CRIES WOLF
    on a correct run, which is why it is not what this does. There are six honest outcomes,
    not two: a brochure the photo-match step bound CONFIDENTLY contributes a photo and zero
    records BY DESIGN; a deck superseded by a region transcription contributes neither; and
    loose images have no consumer in the spine at all. Only one bucket is a defect.

    The affirmative evidence is the LEDGER's source_file column, not "a record exists":
    the ledger is what every shipped field traces to, so an input that appears there
    demonstrably reached the client.

    ONE INPUT CANNOT PRESENT ITS OWN EVIDENCE: an email whose body held no quotable data but
    whose attachments were read ships under the ATTACHMENTS' filenames, never its own, so it
    fell through to `unaccounted` and blocked a run on which nothing was lost. That is the
    `attachment_carrier` bucket, and it is credited only against the sidecar's saved list -
    see _carried below for why every saved attachment, not merely one, has to be accounted."""
    inv, led_src, unread = {}, set(), {}
    try:
        inv = json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
    except Exception:
        inv = {}
    try:
        import csv as _csv
        with open(Path(canonical).parent / "source_ledger.csv", newline="",
                  encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                v = (row.get("source_file") or "").strip()
                if v:
                    led_src.add(Path(v).name.lower())
    except Exception:
        pass
    try:
        for e in json.loads((work / "unreadable.json").read_text(encoding="utf-8-sig")) or []:
            nm = e[0] if isinstance(e, (list, tuple)) and e else (
                e.get("file") if isinstance(e, dict) else e)
            if nm:
                unread[Path(str(nm)).name.lower()] = (
                    e[1] if isinstance(e, (list, tuple)) and len(e) > 1 else "")
    except Exception:
        pass
    photo_bound = set()
    for f in ("photo_overrides.json", "photo_map.json"):
        try:
            obj = json.loads((work / f).read_text(encoding="utf-8-sig"))
            vals = obj.values() if isinstance(obj, dict) else []
            for v in list(vals) + (list(obj) if isinstance(obj, dict) else []):
                if isinstance(v, str):
                    photo_bound.add(Path(v).name.lower())
        except Exception:
            pass

    NO_CONSUMER = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
    out = {"records": [], "photo": [], "unreadable": [], "no_consumer": [],
           "declared_empty": [], "unaccounted": []}
    files = []
    # B56: `clusters` is a DICT (region -> cluster object) while the siblings are lists, and a
    # cluster stores its decks under `pdfs`/`pptxs` (plus a scalar `pdf`), never `files`. The old
    # loop tested `isinstance(v, list)` and looked only for `files`, so it skipped EVERY brochure:
    # 1 of 12 inputs accounted on a live run, and the BLOCKING `unaccounted` bucket was
    # unreachable for a PDF - the input type most likely to vanish, and the exact case this gate's
    # own docstring says it exists for. A gate that cannot fail is worse than no gate.
    # `unclassified` is the real key intake writes for a file it could not classify (`other` never
    # existed); it is kept below only for forward-compatibility.
    for key in ("clusters", "xlsx", "emails", "images", "unclassified", "other"):
        v = inv.get(key)
        items = list(v.values()) if isinstance(v, dict) else (v if isinstance(v, list) else [])
        for it in items:
            if isinstance(it, str):
                files.append(it)
            elif isinstance(it, dict):
                for _k in ("files", "pdfs", "pptxs", "images"):
                    files += [str(x) for x in (it.get(_k) or []) if x]
                for _k in ("pdf", "pptx", "file"):
                    if isinstance(it.get(_k), str) and it[_k]:
                        files.append(it[_k])
    # sources whose only records the BROKER'S source-authority answer excluded
    # (meta.excluded, the B47 disclosure). A legitimate exclusion leaves ZERO
    # ledger rows, so without this bucket the gate BLOCKED the disclosed decision -
    # which is exactly what cornered a live orchestrator into filing the brochure
    # into _originals, hiding it from inventory (and this gate) entirely. Excluded
    # = accounted AND disclosed, never a block.
    excluded_src = set()
    try:
        for e in (C.load_canonical(Path(canonical)).get("meta", {}) or {}).get(
                "excluded") or []:
            for sf in (e.get("source_files") or []) if isinstance(e, dict) else []:
                if sf:
                    excluded_src.add(Path(str(sf)).name.lower())
    except Exception:
        excluded_src = set()
    # sources whose only rows the USER struck off on the MASTER LIST (work/master_list.json,
    # made binding by master_list_read.py and named one by one in the Gaps Report's "Options
    # excluded by the master list", deliver.py:316). Exactly the same shape as the
    # source-authority bucket above, and it needs the same exemption for the same reason: an
    # excluded option leaves ZERO ledger rows, so without this the gate BLOCKED the user's own
    # disclosed scope decision as "a whole source has silently vanished" - and the only way
    # out of that block is to un-answer the sheet. A file is exempt ONLY when EVERY row it
    # feeds was struck off: a tracker with one No among ten still owes the run its records.
    ml_no, ml_kept = set(), set()
    try:
        for r in (json.loads((work / "master_list.json").read_text(encoding="utf-8-sig")
                             ).get("rows") or []):
            tgt = ml_no if str(r.get("include") or "").strip().lower() == "no" else ml_kept
            for sf in (r.get("source_files") or []):
                if sf:
                    tgt.add(Path(str(sf)).name.lower())
    except Exception:
        ml_no, ml_kept = set(), set()
    ml_no -= ml_kept
    # emails whose ONLY contribution was the brochures stapled to them (see
    # _carrier_attachment_index). Credited only when the attachments really landed.
    carrier_att = _carrier_attachment_index(work, inv)

    def _carried(nm: str) -> bool:
        """True when this .msg/.eml's saved attachments ARE the contribution, in full.

        Two conditions, and the second is the one that keeps the gate strict. (1) at least
        one saved attachment reached the ledger or a photo binding, so something of this
        email demonstrably shipped; (2) EVERY saved attachment is itself accounted for in
        some bucket. Drop (2) and an email carrying two brochures, one of them lost, would
        be waved through on the strength of the other. An email with nothing saved fails
        (1) and stays unaccounted, which is the genuine-loss case this gate exists for.
        """
        saved = carrier_att.get(nm) or []
        if not saved:
            return False
        if not any(s in led_src or s in photo_bound for s in saved):
            return False
        return all(s in led_src or s in photo_bound or s in unread or s in excluded_src
                   or s in ml_no or Path(s).suffix.lower() in NO_CONSUMER
                   for s in saved)

    out["excluded"] = []
    out["master_list_no"] = []
    out["attachment_carrier"] = []
    for rel in sorted(set(files)):
        nm = Path(rel).name.lower()
        if nm in led_src:
            out["records"].append(rel)
        elif nm in excluded_src:
            out["excluded"].append(rel)
        elif nm in ml_no:
            out["master_list_no"].append(rel)
        elif Path(rel).suffix.lower() in (".msg", ".eml") and _carried(nm):
            out["attachment_carrier"].append(rel)
        elif nm in unread:
            out["unreadable"].append(rel)
        elif nm in photo_bound:
            out["photo"].append(rel)
        elif Path(rel).suffix.lower() in NO_CONSUMER:
            out["no_consumer"].append(rel)
        else:
            out["unaccounted"].append(rel)
    return out


# ------------------------------------------------------------------ prov containment (B52)
# Short DISPLAYED values that are read verbatim off a page. Deliberately EXCLUDES developer and
# landlord (legitimately read from cover logos), long prose such as description (verbatim by
# construction, so a token sweep adds nothing), and every numeric field (formatting and unit
# normalisation make token comparison meaningless).
# BLOCKING vs ADVISORY was decided by RUNNING this against a real 12-property dataset, and the
# result changed the design. `region` is prose in body text - it is never cover artwork, and a
# fabricated one is exactly the failure this gate exists for, so it BLOCKS. The others are
# reported but do NOT block, because on real marketing PDFs they produce false positives that a
# strict gate cannot distinguish from fabrication:
#   * `park` is the scheme name, i.e. usually the COVER TITLE - rendered as artwork, or composed
#     across pages ("MPC 2, Magna Park Corby" is anchored to page 1 but assembled from pages 2-5);
#   * a value can be real but anchored to a slightly wrong page.
# A gate that fires on 4 of 12 correct properties would be silenced by agents sprinkling the
# escape-hatch marker everywhere, which is worse than no gate at all.
PROV_BLOCK_FIELDS = frozenset({"region"})
PROV_ADVISE_FIELDS = frozenset({"city", "district", "park", "address", "postcode"})
PROV_CHECK_FIELDS = PROV_BLOCK_FIELDS | PROV_ADVISE_FIELDS
PROV_NOT_IN_TEXT = "not in text layer"      # the agent's DECLARED escape hatch
_PROV_PAGE_RE = re.compile(r"\bpage\s+(\d+)", re.IGNORECASE)
_PROV_TOKEN_RE = re.compile(r"[a-z]{4,}")
_PROV_STRIP_RE = re.compile(r"[^a-z0-9]+")
# F9: a token that may be UTF-8 bytes decoded as cp1252 (the "Ã©" / "â€™" family - the
# commonest mojibake a design tool's broken ToUnicode map produces). Only a token carrying one
# of these three lead bytes is even TRIED; the round trip itself decides, and a genuine
# "château" fails it and is kept as written.
_PROV_MOJIBAKE_RE = re.compile("[\u00c2\u00c3\u00e2]")
#: a `seen_as` claim shorter than this, once flattened, is too short to be evidence either way
PROV_SEEN_AS_MIN = 4
#: the closed reason class of `__meta.not_in_text_layer` (templates/record_schema.json)
PROV_MARKER_REASONS = frozenset({"image", "glyph", "spacing", "composed", "other"})


def _prov_norm(s) -> str:
    """One text, as the gate compares it, applied to BOTH sides (F9): U+FFFD dropped, mojibake
    decoded back, compatibility-folded (a U+FB01 'fi' ligature becomes its two letters),
    diacritics stripped, case-folded, every whitespace run collapsed to one space.

    THE DEFECT, measured on 3 of 7 live decks: one set its display type letter-spaced, so the
    text layer held spaced-out digits and words on every headline value; three rendered a
    currency symbol as the replacement character. Readers transcribed correctly, disclosed the
    divergence in the field's own prov in prose, and still could not satisfy a raw comparison.
    The gate asks "did the reader invent this string", not "did the reader reproduce the
    kerning or the font's broken glyph map", so both sides are normalised the same way before
    they meet. Nothing here can turn a value the page does not carry into one it does: every
    fold maps a garbled spelling onto its clean one, never one word onto another."""
    import unicodedata
    t = str(s or "").replace("\ufffd", "")
    if _PROV_MOJIBAKE_RE.search(t):
        parts = []
        for w in t.split(" "):
            if _PROV_MOJIBAKE_RE.search(w):
                try:
                    w = w.encode("cp1252").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            parts.append(w)
        t = " ".join(parts)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def _prov_tokens(s) -> set:
    """Distinctive lowercase tokens of the NORMALISED value. Short tokens and pure numbers
    collide far too easily to be evidence, so only alphabetic runs of 4+ characters count.
    Normalising first means an accented name yields its whole word as one token rather than
    the fragment after the accent."""
    return set(_PROV_TOKEN_RE.findall(_prov_norm(s)))


def _prov_flat(s) -> str:
    """The normalised text with EVERY separator removed: alphanumerics only.

    Marketing PDFs letter-space their headings, so the extractor legitimately returns
    'UNI T 1 WOR K S O P LI NK' and 'ULTRA BOX'. Comparing word-for-word flagged both as
    fabrications on a real run. Flattening both sides makes 'worksop' and 'ultrabox' match the
    text that genuinely contains them, while a value that is simply NOT in the document still
    fails to appear."""
    return _PROV_STRIP_RE.sub("", _prov_norm(s))


def _prov_markers(work) -> dict:
    """{(source_file.lower(), field): [(record value, marker)]} from the PRE-MERGE records. (F10)

    `__meta.not_in_text_layer` (templates/record_schema.json) is the machine-readable form of
    the prose escape hatch: per field, {reason, note?, seen_as?}. `__meta` never survives
    merge, so it is read here from work/extract/*.json and joined to a ledger row on
    (source_file, field), disambiguated by value on a multi-property deck. A marker whose
    `reason` is missing or outside the schema's closed list is ignored, not honoured."""
    out: dict = {}
    for path in sorted((Path(work) / "extract").glob("*.json")):
        try:
            recs = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(recs, list):
            continue
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            meta = rec.get("__meta") or {}
            marks = meta.get("not_in_text_layer") if isinstance(meta, dict) else None
            if not isinstance(marks, dict) or not marks:
                continue
            src = Path(str(meta.get("source_file") or path.name)).name.lower()
            for field, mk in marks.items():
                if not isinstance(mk, dict) or str(mk.get("reason") or "") not in PROV_MARKER_REASONS:
                    continue
                out.setdefault((src, str(field)), []).append((rec.get(field), mk))
    return out


def _prov_marker_for(markers: dict, src: str, field: str, value):
    """The one marker for (src, field), or None. On a multi-property deck several records may
    mark the same field, so the ledger row's value picks between them; an ambiguity that the
    value cannot settle honours NONE of them, because a marker is an admission about one
    specific reading and guessing which one would make it a bypass."""
    cands = markers.get((src, field)) or []
    if len(cands) == 1:
        return cands[0][1]
    want = _prov_flat(value)
    hit = [mk for rv, mk in cands if _prov_flat(rv) == want]
    return hit[0] if len(hit) == 1 else None


def _prov_page_text(work) -> dict:
    """{(source_file.lower(), 1-based page): text} for TEXT-mode decks only.

    A raster deck has no text layer, so it is omitted and every value citing it is skipped - the
    gate must never form an opinion it has no evidence for."""
    out: dict = {}
    try:
        decks = json.loads((Path(work) / "vision" / "manifest.json")
                           .read_text(encoding="utf-8-sig")).get("decks", [])
    except Exception:
        return out
    for d in decks if isinstance(decks, list) else []:
        if not isinstance(d, dict) or str(d.get("mode", "")).lower() != "text":
            continue
        nm = Path(str(d.get("source_file") or "")).name.lower()
        for pg in (d.get("pages") or []):
            m = _PROV_PAGE_RE.search(str((pg or {}).get("locator") or ""))
            if nm and m:
                out[(nm, int(m.group(1)))] = str((pg or {}).get("text") or "")
    return out


def cmd_prov_containment(args) -> int:
    """A value citing a page must actually OCCUR on that page. (B52)

    Three of eleven interpretation agents shipped the manifest's filename-derived cluster label as
    the property's `region`, each cited to "page 1 (text interpretation)", on decks where the
    string appears nowhere. Nothing mechanical caught it - it surfaced only because an honesty
    reviewer chose to full-text search eleven PDFs by hand. This gate makes that diligence
    unnecessary: it is a pure string-containment check over text the manifest already holds.

    STRICT BY DESIGN: every distinctive token of the value must be present. A partial threshold
    does not work - the Doncaster value scores 4 of 5 tokens against its cited page and would sail
    through at 0.6. Values in PROV_CHECK_FIELDS are read verbatim, so full coverage is the correct
    expectation, and the escape hatch below covers the honest exception.

    FAILS SAFE: a missing or corrupt manifest, a raster deck, a non-page locator, an override row,
    an unknown source file, or a value with no distinctive token all SKIP. Absent evidence is
    never a block.

    TWO ESCAPE HATCHES, one of them checkable (F10). The prose marker (PROV_NOT_IN_TEXT inside
    the locator) skips the row outright, as it always has. The structured marker
    (`__meta.not_in_text_layer` on the pre-merge record, see `_prov_markers`) is consulted only
    when the normalised comparison has already FAILED, and then: with a `seen_as` (the text
    layer's own garbled form of the value) the gate verifies THAT string occurs on the cited
    page, so the disclosure is a weaker but real check rather than a hole; without one the row
    is skipped as disclosed for a stated reason. A `seen_as` that does not occur either is
    reported at the field's own severity, naming the disclosed form.

    LOCATOR-QUOTE MISMATCH (D15), an advisory SIGNAL that needs NO page text. A locator that
    quotes the source ("printed as 'HGV Parking 56'") is the reader's own statement of what
    the page said, and when the figure it quotes is not the figure the row ships, the row
    contradicts itself. On the measured run UNIT 06 shipped UNIT 07's HGV parking (38 where its
    own schedule column prints 56) with a locator that quoted 56 beside the 38; blind reviewers
    found it, this gate did not look. `_locator_quote_mismatches` is that look, and it runs
    BEFORE the page-text check so a raster-only or manifest-less corpus (where nothing else can
    verify a value) still gets it. It is a SIGNAL, never a block: a reader may legitimately
    quote the neighbouring figure for context, and the remedy is a re-read, not a strike."""
    import csv as _csv
    rows, ledger_err = None, None
    try:
        with open(args.ledger, newline="", encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
    except Exception as e:
        ledger_err = e
    quote_sigs = _locator_quote_mismatches(rows) if rows is not None else []
    for q in quote_sigs:
        print(_quote_line(q))
    _qtail = (f"; {len(quote_sigs)} locator-quote SIGNAL(s) above (the locator quotes a figure "
              f"the row does not ship)") if quote_sigs else ""
    pages = _prov_page_text(args.work)
    if not pages:
        _ok("no deck text to verify against (raster-only, tracker-only, or no manifest)" + _qtail)
        print("STATUS: ALL-PASS")
        return 0
    if rows is None:
        _ok(f"ledger unreadable ({ledger_err}) - nothing to verify")
        print("STATUS: ALL-PASS")
        return 0
    markers = _prov_markers(args.work)
    bad, soft, checked = [], [], 0
    disclosed = seen_ok = 0
    for r in rows:
        if (r.get("field") or "").strip() not in PROV_CHECK_FIELDS:
            continue
        loc = r.get("source_locator") or ""
        if PROV_NOT_IN_TEXT in loc.lower():
            continue                    # the agent DECLARED it came from an image
        if (r.get("source_type") or "").strip().lower() == "override" \
                or "manual override" in loc.lower():
            continue                    # an attributed human correction, already disclosed
        m = _PROV_PAGE_RE.search(loc)
        if not m:
            continue                    # not a page citation - nothing to compare against
        key = (Path(r.get("source_file") or "").name.lower(), int(m.group(1)))
        if key not in pages:
            continue                    # raster deck, or a file with no manifest entry
        want = _prov_tokens(r.get("value"))
        if not want:
            continue                    # no distinctive token - no evidence either way
        checked += 1
        flat = _prov_flat(pages[key])
        missing = sorted(t for t in want if t not in flat)
        if not missing:
            continue
        field = (r.get("field") or "").strip()
        mk = _prov_marker_for(markers, key[0], field, r.get("value"))
        if mk is not None:
            disclosed += 1
            seen_as = " ".join(str(mk.get("seen_as") or "").split())
            needle = _prov_flat(seen_as)
            if len(needle) < PROV_SEEN_AS_MIN:
                continue                # disclosed for a stated reason; no checkable claim made
            if needle in flat:
                seen_ok += 1
                continue                # the text layer's own form IS on the page: verified
            (bad if field in PROV_BLOCK_FIELDS else soft).append(
                (r.get("property_id"), field, r.get("value"), loc, [seen_as], "seen_as"))
            continue
        (bad if field in PROV_BLOCK_FIELDS else soft).append(
            (r.get("property_id"), field, r.get("value"), loc, missing, "tokens"))

    def _what(missing, why):
        if why == "seen_as":
            return (f"its __meta.not_in_text_layer marker says the text layer shows it as "
                    f"{missing[0]!r}, and THAT form appears nowhere on that page either")
        return (f"{', '.join(repr(x) for x in missing[:4])} "
                f"appear{'s' if len(missing) == 1 else ''} nowhere on that page")

    for pid, field, val, loc, missing, why in soft:
        print(f"  [note] property={pid} field={field}: {str(val)[:52]!r} is cited to "
              f"{loc[:40]!r} but {_what(missing[:3], why)}. Advisory: a scheme "
              f"name is often cover artwork or composed across pages, so this is a locator to "
              f"tighten, not proof of invention.")
    for pid, field, val, loc, missing, why in bad:
        _bad(f"property={pid} field={field}: value {str(val)[:60]!r} is cited to {loc[:46]!r} "
             f"but {_what(missing, why)}. Either the value is "
             f"not from that source (strike it to 'tbd', or cite the real locator), or it was read "
             f"from an image or a garbled text layer - in which case mark it: "
             f"__meta.not_in_text_layer.{field or '<field>'} = {{reason, seen_as}} on the record "
             f"(seen_as = the text layer's own form, so the gate can verify it), or append "
             f"'{PROV_NOT_IN_TEXT}' to its provenance.")
    if bad:
        print("STATUS: BLOCKED")
        return 1
    tail = (f", {disclosed} disclosed via __meta.not_in_text_layer of which {seen_ok} verified "
            f"by seen_as" if disclosed else "")
    _ok(f"every page-cited value occurs on its cited page ({checked} checked, "
        f"{len(soft)} advisory{tail})" + _qtail)
    print("STATUS: ALL-PASS")
    return 0


# D15: a quoted span in a locator, only when the quote mark is not an apostrophe inside a word
# ("page 3's" must not open a quote). Straight and typographic marks both count; a span is at
# most 200 characters so an unbalanced mark cannot swallow the rest of the locator.
_LOC_QUOTED_RE = re.compile(
    "(?<![A-Za-z0-9])['‘’]([^'‘’]{1,200}?)['‘’](?![A-Za-z0-9])"
    "|(?<![A-Za-z0-9])[\"“”]([^\"“”]{1,200}?)[\"“”](?![A-Za-z0-9])")
# a standalone figure: thousands separators allowed, an optional decimal part, and NOT glued to
# a letter on either side, so "4m", "J17", "NN67ES" and "Q3" contribute nothing
_LOC_NUM_RE = re.compile(r"(?<![A-Za-z0-9.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![A-Za-z0-9])")
# fields whose value is media, a coordinate or an id: a figure inside them is not a stated datum
_LOC_SKIP_FIELDS = frozenset({"photo", "plan", "gallery", "preBaked", "lat", "lng", "id",
                              "coordsApprox", "regionCode", "mapLink", "brochureLink",
                              # v45: a figure inside a URL is part of the URL
                              "videoLink", "websiteLink", "streetViewLink"})


def _figures(text) -> set:
    """The standalone numbers in `text`, as floats ('1,413' -> 1413.0, '9.50' -> 9.5)."""
    out = set()
    for whole, frac in _LOC_NUM_RE.findall(str(text or "")):
        try:
            out.add(float(whole.replace(",", "") + ("." + frac if frac else "")))
        except ValueError:
            continue
    return out


def _locator_quote_mismatches(rows) -> list[tuple]:
    """Ledger rows whose locator QUOTES the source with a figure in it, none of which is a figure
    the row's value carries -> [(property_id, field, value, locator, value figures, quoted
    figures)]. Precise by construction: a row is judged only when BOTH sides state a standalone
    number, and it passes when ANY quoted figure matches ANY figure in the value, so '320 Car
    Parking Spaces (28 EV Charging)' against a quote of the same line passes, a quote of the
    label alone ("'HGV Parking' row") is not judged, and a page reference outside the quotes is
    never counted. Gap rows and media/coordinate fields are skipped."""
    out = []
    for r in rows or []:
        if (r.get("source_type") or "").strip().lower() == "gap":
            continue
        field = (r.get("field") or "").strip()
        if field in _LOC_SKIP_FIELDS:
            continue
        val = str(r.get("value") or "")
        if val.startswith("data:"):
            continue
        have = _figures(val)
        if not have:
            continue
        loc = str(r.get("source_locator") or "")
        quoted = [q for pair in _LOC_QUOTED_RE.findall(loc) for q in pair if q]
        if not quoted:
            continue
        cited = set().union(*(_figures(q) for q in quoted))
        if not cited or have & cited:
            continue
        out.append((r.get("property_id"), field, val, loc, sorted(have), sorted(cited)))
    return out


def _fmt_fig(x: float) -> str:
    return f"{x:g}"


def _quote_line(q: tuple) -> str:
    pid, field, val, loc, have, cited = q
    return (f"  [SIGNAL] property={pid} field={field}: the row ships {val[:60]!r} but its own "
            f"locator quotes the source as {loc[:110]!r} - the figure(s) quoted "
            f"({', '.join(_fmt_fig(x) for x in cited)}) are not the figure(s) shipped "
            f"({', '.join(_fmt_fig(x) for x in have)}). On the measured run this shape was a "
            f"neighbouring unit's schedule column read into the wrong card. Re-read the cited "
            f"row; if the value is right, tighten the locator to quote the text that carries it.")


def _norm_option_name(s) -> str:
    """A cluster label reduced to its words, for comparing two labels for identity."""
    return " ".join(re.findall(r"[a-z0-9]+", str(s or "").lower()))


def _excluded_same_as_shipped(canonical: Path) -> list:
    """Exclusions that are not exclusions: the SAME building as a card that shipped. (B08b)

    `apply_source_authority` drops a cluster the authoritative source family does not evidence,
    and that is correct for a genuine extra - another unit of the same park, a scheme the
    tracker never listed. It is NOT correct when the dropped cluster and a kept one are the
    same option that failed to merge, because then the answer did not remove an option from
    scope; it removed the only page-cited evidence a shipped option had.

    `input-accounting` used to print that case as a clean `[note]`: "a disclosed decision, not
    a silent loss". On a live run it was a silent loss three times over. Three options shipped
    with no specification field, no photo and no site plan traceable to their own brochure,
    while the brochure sat in the inputs folder and the Gaps Report described it as excluded on
    purpose. The pairs were `forbidden` - vetoed on a >15% warehouse-area gap between a
    marketed TOTAL and an accommodation schedule's warehouse-only line - so they were never
    written to match_candidates.json and no adjudicator or verifier ever saw them.

    THE TEST IS DELIBERATELY NARROW, because the same field carries the legitimate case.
    `merge._likely_same_kept` links a dropped cluster to a kept one whenever a forbidden or
    grey pair holds them apart, and on that live run ten of thirteen exclusions carried such a
    link and ten were RIGHT (LLP500 against LLP90, Vantage Park against V60: two units of one
    park, correctly excluded and correctly named as distinct). What separates the three
    failures is that their label and the kept card's label are THE SAME STRING - the same unit
    designator, the same park, the same city. `cluster_label` is already composed from those
    three, so the comparison needs nothing the entry does not already carry, and on that run it
    selects exactly the three and none of the ten.

    Near-threshold size gaps get a NOTE rather than a block: a forbidden link whose two
    headline areas sit between the 15% veto and 35% is the shape of a basis conflict rather
    than two different buildings, and is worth a human glance without crying wolf.
    """
    try:
        meta = (C.load_canonical(Path(canonical)).get("meta") or {})
    except Exception:
        return []
    hits, near = [], []
    for e in (meta.get("excluded") or []):
        if not isinstance(e, dict):
            continue
        link = e.get("likely_same_as") or {}
        if str(link.get("tier") or "").lower() != "forbidden":
            continue
        if _norm_option_name(e.get("name")) and \
                _norm_option_name(e.get("name")) == _norm_option_name(link.get("name")):
            a = _num_or_none((e.get("headline") or {}).get("warehouseArea"))
            b = _num_or_none((link.get("kept_headline") or {}).get("warehouseArea"))
            gap = (f"both are labelled '{link.get('name')}'"
                   + (f"; the two records state {a:,.0f} and {b:,.0f} "
                      f"{(e.get('headline') or {}).get('areaUnit') or ''}".rstrip()
                      + f", a {abs(a - b) / max(a, b) * 100:.1f}% gap"
                      if a and b else ""))
            hits.append((e, gap))
            continue
        a = _num_or_none((e.get("headline") or {}).get("warehouseArea"))
        b = _num_or_none((link.get("kept_headline") or {}).get("warehouseArea"))
        if a and b and 0.15 < abs(a - b) / max(a, b) <= 0.35:
            near.append((e, link, abs(a - b) / max(a, b)))
    for e, link, g in near:
        print(f"  [note] '{str(e.get('name'))[:44]}' was excluded while a forbidden pair held "
              f"it apart from the shipped '{str(link.get('name'))[:44]}', on a {g * 100:.1f}% "
              f"area gap. That is close enough to the 15% veto to be two figures on different "
              f"bases (marketed total vs warehouse-only) rather than two buildings. Not "
              f"blocking - the labels differ - but check it before sending the pack.")
    return hits


def _num_or_none(v):
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except Exception:
        return None


def _email_attachment_faults(work: Path) -> list:
    """Emails whose ATTACHMENTS did not reach the run. Blocking, not a note.

    THE DEFECT THIS EXISTS FOR, and the reason it cannot be an advisory. An offer email
    contributes records from its BODY, so the .msg itself appears in the ledger and every
    bucket above counts it as fully accounted. The brochure stapled to it can therefore be
    absent from the entire run while input-accounting prints ALL-PASS: the one gate whose
    whole job is "nothing discovered at intake vanishes silently" was structurally blind to
    the commonest way a building goes missing, because the carrier file was present and the
    payload was not. A note would not have helped either, since the run that produced the
    note also produced a clean scorecard and shipped.

    Four faults, all of them "the bytes are not where the inventory says they are":
      * a LEGACY inventory - emails discovered, no `email_attachments` record at all. That
        inventory was written before attachments were extracted, so nobody can say whether
        those emails carried brochures. Unknown is not the same as none, and the fix is one
        cheap re-run of intake, so it blocks;
      * an extraction ERROR recorded against a named email (an unwritable path, extract_msg
        not installed for a .msg);
      * declared attachments that are neither saved nor explicitly skipped as inline, which
        is the arithmetic signature of a half-completed save;
      * a saved attachment whose file is GONE from the inputs folder - the folder deleted by
        hand between runs, the classic "I tidied up" case. The inventory still promises it.

    Skipped entirely when `email_attachments_enabled` is false, which is the wrapper-skill
    contract (`inputs.emails.source: none`, kato-longlist): there the attachments were
    extracted by the wrapper's own email step and this skill must not double-read them, so
    demanding its own copies would block every correct wrapper run.
    """
    try:
        inv = json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    emails = inv.get("emails") or []
    if not emails:
        return []
    if inv.get("email_attachments_enabled") is False:
        return []
    ea = inv.get("email_attachments")
    if ea is None:
        return [f"{len(emails)} email(s) were discovered but this inventory.json carries NO "
                f"attachment record at all, so nothing can say whether they carried brochures. "
                f"It predates attachment extraction (a legacy run). Re-run intake against the "
                f"inputs folder and re-run the spine; the emails' own bodies are NOT evidence "
                f"that their attachments reached the dashboard."]
    faults: list = []
    inputs_dir = Path(str(inv.get("folder") or ""))
    for e in ea if isinstance(ea, list) else []:
        if not isinstance(e, dict):
            continue
        nm = str(e.get("email") or "(unnamed email)")
        if e.get("skipped_reason"):
            continue
        if e.get("error"):
            faults.append(f"{nm}: its attachments were NOT extracted - {e['error']}. The body's "
                          f"records make this email look accounted for, which is exactly why "
                          f"this blocks.")
            continue
        declared = e.get("declared")
        accounted = len(e.get("saved") or []) + len(e.get("skipped_inline") or [])
        if isinstance(declared, int) and declared > accounted:
            faults.append(f"{nm}: {declared} attachment(s) on the email, {accounted} accounted "
                          f"for (saved or skipped as inline). {declared - accounted} set of "
                          f"bytes is unexplained.")
        for s in e.get("saved") or []:
            relp = str((s or {}).get("file") or "")
            if not relp:
                continue
            if inputs_dir.is_dir() and not (inputs_dir / relp).exists():
                faults.append(f"{nm}: the saved attachment '{relp}' is no longer in the inputs "
                              f"folder. The inventory promises it and the extractors cited it; "
                              f"restore the folder or re-run intake so the run and the disk "
                              f"agree.")
    return faults


def cmd_input_accounting(args) -> int:
    """Reconcile every discovered INPUT against what actually shipped. (B08)"""
    work = Path(args.work)
    b = _accounting_buckets(work, Path(args.canonical))
    total = sum(len(v) for v in b.values())
    _ok(f"{total} input(s): {len(b['records'])} contributed fields, "
        f"{len(b['photo'])} contributed a photo only, {len(b['unreadable'])} unreadable/skipped, "
        f"{len(b.get('excluded') or [])} excluded by the broker's source-authority answer "
        f"(disclosed in the Gaps Report), "
        f"{len(b.get('master_list_no') or [])} struck off on the master list, "
        f"{len(b.get('attachment_carrier') or [])} contributed only through attachments "
        f"that were read, "
        f"{len(b['no_consumer'])} have no consumer in the spine")
    # the real casing of every discovered file, so a note prints the brochure's name as the
    # broker spelled it; the carrier index is lowercased because matching is case-insensitive.
    _disp = {Path(r).name.lower(): Path(r).name
             for v in b.values() if isinstance(v, list) for r in v}
    _carriers = _carrier_attachment_index(work)
    for rel in b.get("attachment_carrier") or []:
        atts = [_disp.get(a, a) for a in (_carriers.get(Path(rel).name.lower()) or [])]
        print(f"  [note] {rel}: contributed no records of its own; its saved "
              f"attachment{'' if len(atts) == 1 else 's'} {', '.join(atts)} "
              f"{'was read and ships' if len(atts) == 1 else 'were read and ship'}")
    for rel in b.get("master_list_no") or []:
        print(f"  [note] {rel}: every option it carries was answered No on the master list, so "
              f"it was never read - named in the Gaps Report's 'Options excluded by the master "
              f"list' section, so the exclusion is the user's own disclosed decision.")
    for rel in b.get("excluded") or []:
        print(f"  [note] {rel}: its only records were excluded by your source-authority "
              f"answer - named in the Gaps Report's 'Options excluded' section, so the "
              f"exclusion is a disclosed decision, not a silent loss.")
    for rel in b["no_consumer"]:
        print(f"  [note] {rel}: loose image - no spine consumer reads it (extract_image.py "
              f"is not wired in). Not a defect in this run; it is simply not in the dashboard.")
    same_building = _excluded_same_as_shipped(Path(args.canonical))
    for e, why in same_building:
        _bad(f"'{str(e.get('name'))[:48]}': recorded as excluded by the source-authority "
             f"answer, but it is the SAME OPTION as a shipped card ({why}). That is not a "
             f"scope decision. A forbidden pair is never written to match_candidates.json "
             f"and never adjudicated, so the two clusters could not merge whatever anyone "
             f"answered, and the authority answer then dropped the brochure's cluster - "
             f"taking its page-cited fields, its photos and its site plan with it. The usual "
             f"cause is a size conflict between two figures on DIFFERENT BASES: a marketed "
             f"total (offices, plant deck, mezzanine, undercroft included) on one side and "
             f"the accommodation schedule's warehouse-only line on the other. Fix the source "
             f"of the figure - do NOT repair the merged value, which leaves the next run "
             f"reproducing this exactly.")
    email_faults = _email_attachment_faults(work)
    for f in email_faults:
        _bad(f)
    if b["unaccounted"] or same_building or email_faults:
        for rel in b["unaccounted"]:
            _bad(f"{rel}: discovered at intake but contributed NOTHING - no ledger row, no "
                 f"photo binding, and not recorded as unreadable. A whole source has "
                 f"silently vanished.")
        print("STATUS: BLOCKED")
        return 1
    print("STATUS: ALL-PASS")
    return 0


_BARE_NUMBER = re.compile(r"^\s*\d[\d,.\s ]*\s*$")
# A MEASURED value is a magnitude followed by a unit and NOTHING else: '10 m',
# '10,000 sq. m', '5 tons/sq. m', '12 months'. The tail must be letter-LED and digit-FREE,
# which is exactly what separates a unit from a qualifier or a ratio. Getting this boundary
# right is the whole game - too loose and the gate demands a unit on a count. It excludes:
#   'Q1 2028'            -> letter-led, so not a magnitude (a coarser DATE, not a missing unit)
#   '1 per 650 sq. m'    -> digits inside the tail, i.e. a RATIO, not a count
#   'up to 4,216 sq. m'  -> a qualifier, not a bare magnitude
# Both of those tripped a looser first version against real data: loadingDocks counts
# (72, 74, 80) were called out because two decks quoted a dock RATIO instead.
_MEASURED = re.compile(r"^\s*\d[\d,.\s ]*\s*([A-Za-z][A-Za-z.,/\s]*)$")


def _unit_of(s: str):
    """The normalised unit of a measured value, or None if it is not <magnitude><unit>."""
    m = _MEASURED.match(s)
    if not m:
        return None
    return re.sub(r"[.\s]+", "", m.group(1)).lower() or None


def _ledger_sources(ledger_path, canonical: Path) -> dict:
    """{(property_id, field): source_file} from the first non-gap ledger row of each pair, or
    {} when no ledger can be read. (F21)

    Default location: source_ledger.csv BESIDE canonical.json, which is where run.py writes
    it, so the spine needs no new argument to get source-counted votes. A canonical judged on
    its own (an eval, a hand run) has no ledger and falls back to per-record votes; the gate
    says so in a note rather than silently changing its arithmetic."""
    p = Path(ledger_path) if ledger_path else Path(canonical).resolve().parent / "source_ledger.csv"
    out: dict = {}
    try:
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if (r.get("source_type") or "").strip().lower() == "gap":
                    continue
                src = str(r.get("source_file") or "").strip()
                if src:
                    out.setdefault((str(r.get("property_id")), str(r.get("field"))), src)
    except Exception:
        return {}
    return out


def cmd_coord_provenance(args) -> int:
    """A town-centre pin is only honest when the source offers nothing better. (B60)

    THE DEFECT, live: three options showed a village-centre geocode (one showed no pin at all)
    while their own brochure pages carried the author's pin - two printed it as DMS
    (48°29'51.0"N 17°01'39.7"E) and one as a 'click for location' Google Maps link. The
    coordinate LOOKED fine on the map, which is why nobody caught it until the broker opened the
    dashboard and saw a marker in the middle of a village.

    The check: a property whose coordinate is APPROXIMATE (a city centroid, coordsApprox) or
    ABSENT, while its own source page offers a first-party pin - a maps link, or coordinates in
    the page text that the resolver did not take. Blocking, because the fix is free: the pin is
    already in the file.

    A property with an approximate pin and NOTHING in its source is CORRECT and passes silently -
    that is an honest geocode, and eleven of the thirty on that run were exactly that.
    """
    import csv
    import coords as CO
    data = C.load_canonical(Path(args.canonical))
    props = data.get("properties", [])
    # each property's own brochure page text, via the interpretation manifest (already on disk -
    # no PDF re-open) keyed the same way the ledger cites it
    page_text: dict[tuple, str] = {}
    man = Path(args.work) / "vision" / "manifest.json" if args.work else None
    if man and man.exists():
        try:
            for deck in (json.loads(man.read_text(encoding="utf-8-sig")).get("decks") or []):
                for pg in deck.get("pages") or []:
                    page_text[(str(deck.get("source_file")), int(pg.get("page_no", -1)))] = \
                        str(pg.get("text") or "")
        except Exception:
            page_text = {}
    origin: dict[str, tuple] = {}
    if args.ledger and Path(args.ledger).exists():
        with open(args.ledger, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("field") == "park" and row.get("property_id") not in origin:
                    m = re.search(r"(\d+)", row.get("source_locator") or "")
                    origin[row["property_id"]] = (row.get("source_file") or "",
                                                  int(m.group(1)) - 1 if m else -1)
    findings = []
    for p in props:
        has = isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))
        if has and not p.get("coordsApprox"):
            continue                                   # a real pin - nothing to check
        why = []
        link = str(p.get("mapLink") or "")
        if link and CO.MAPS_URI.search(link):
            why.append(f"a first-party map link ({link[:60]})")
        txt = page_text.get(origin.get(str(p.get("id")), ("", -1)), "")
        if txt:
            got, _ = CO.coords_and_link_from_text(txt)
            if got:
                why.append(f"coordinates in its own page text ({got[0]:.5f}, {got[1]:.5f})")
        if why:
            findings.append((p, why, has))
    for p, why, has in findings:
        state = "an APPROXIMATE (town-centre) pin" if has else "NO pin at all"
        _bad(f"id={p.get('id')} '{str(p.get('park'))[:40]}' ships {state} while its source offers "
             + " and ".join(why) +
             ". A first-party pin always beats a geocode - resolve it, or record it in "
             "work/overrides.json with the page cited.")
    if findings:
        print("STATUS: BLOCKED")
        return 1
    approx = sum(1 for p in props if p.get("coordsApprox"))
    _ok(f"every approximate pin is an honest one - no property's own source offers a better "
        f"coordinate ({approx} of {len(props)} geocoded from a city name)")
    print("STATUS: ALL-PASS")
    return 0


def cmd_value_format(args) -> int:
    """A field must be WRITTEN the same way on every property that has it. (B59)

    THE DEFECT, live: `divisibleFrom` shipped '10,000 sq. m' on twelve properties and a bare
    '5000' on the thirteenth. Same field, same dataset, same card grid - one option silently
    quoting a different quantity to a client. No gate saw it: validate-data checks types and
    pair-consistency, arithmetic checks derived totals against a stated total, and neither has
    any opinion about how a value READS. It is the same family as v28 ('tbd sq ft') and v32
    (officeArea shipping as a bare '1200' under a warehouse area reading '45,000 sq m').

    THE SIGNAL is intra-field disagreement, which is why it is nearly noise-free. A bare number
    is only suspicious when SIBLING values of the SAME field carry a unit - so `loadingDocks`
    ('72', '74', '80' - a count, bare on every property) never trips, and `warehouseArea` (a
    number on every property, formatted by the chrome) never trips, while one unformatted
    '5000' among twelve '10,000 sq. m' trips immediately.

    BLOCKING, and deliberately NOT auto-repaired. Appending the dataset's unit to a bare number
    means DECIDING the field is an area, and a wrong guess is the 10.76x class this skill exists
    to prevent - a count or a power rating would be silently relabelled. The fix is attributed
    instead: read the source and record it in work/overrides.json, or, when the source does not
    settle it, ASK THE BROKER (see SKILL.md exit 6).
    """
    data = C.load_canonical(Path(args.canonical))
    props = data.get("properties", [])
    # F21: THE UNIT OF EVIDENCE IS A SOURCE FILE, NOT A RECORD. Live: this gate BLOCKED with
    # "6 properties ship a BARE number while 3 write it as a magnitude + unit". The three were
    # not three sources: they were ONE deck's three unit records, each carrying the same
    # site-wide value byte for byte, so one brochure cast three votes for its own format. When
    # that deck was later collapsed to one record for an unrelated reason the gate passed with
    # no other change, and nothing about the data had improved. How many records a deck
    # contributes is a fact about deck structure, not about formatting consistency, and it
    # cuts both ways: here a spurious block; on a corpus where the odd format belongs to the
    # multi-unit deck, a real one suppressed and the wrong unit named as dominant. So each
    # measured sibling votes ONCE PER SOURCE FILE (ledger-joined on property id + field), and
    # both the evidence threshold and the dominant-unit majority are counted in votes.
    # Distinct VALUES were considered and rejected as the unit: standardised specs ("10 m",
    # "12.5 m") legitimately repeat across independent decks, and collapsing those would
    # suppress the very finding this gate exists for. Without a ledger, each record is its own
    # vote (the old arithmetic) and the note below says so.
    src_of = _ledger_sources(getattr(args, "ledger", ""), Path(args.canonical))
    # broker WAIVERS (exit-13 declines): a (field, id) the broker explicitly chose
    # to ship bare. Filtered out of the blocking findings, still noted - a waived
    # value is a disclosed decision, not a silent pass.
    waived = {}
    wv_path = Path(getattr(args, "waivers", "") or "")
    if getattr(args, "waivers", "") and wv_path.exists():
        try:
            for w in json.loads(wv_path.read_text(encoding="utf-8-sig")) or []:
                if isinstance(w, dict):
                    # expect_value guards a waiver against cluster renumbering: a
                    # stale ordinal id must never waive a DIFFERENT property's value
                    waived[(str(w.get("field")), str(w.get("id")))] = w.get("expect_value")
        except Exception:
            pass
    by_field: dict[str, dict] = {}
    for p in props:
        for k, v in p.items():
            if k in _PIPELINE_ASSIGNED or _absent(v, k):
                continue
            if isinstance(v, (dict, list)):
                continue
            slot = by_field.setdefault(k, {"bare": [], "measured": []})
            if isinstance(v, bool):
                continue
            s = str(v).strip()
            if isinstance(v, (int, float)) or _BARE_NUMBER.match(s):
                _wk = (k, str(p.get("id")))
                if _wk in waived and (waived[_wk] is None or str(waived[_wk]) == s):
                    print(f"  [note] `{k}` id={p.get('id')} ships as a bare '{s}' BY BROKER "
                          f"DECISION (exit-13 decline; disclosed in the Gaps Report)")
                    continue
                if _wk in waived:
                    print(f"  [note] waiver for `{k}` id={p.get('id')} expected "
                          f"'{waived[_wk]}' but the value is now '{s}' - waiver NOT applied "
                          f"(ids can renumber between passes; the question will re-fire)")
                slot["bare"].append((p.get("id"), s))
                continue
            unit = _unit_of(s)
            if unit:
                vote = src_of.get((str(p.get("id")), k)) or f"record:{p.get('id')}"
                slot["measured"].append((p.get("id"), s, unit, vote))
    if not src_of and any(slot["measured"] for slot in by_field.values()):
        print("  [note] no source ledger to join (none beside the canonical, none via --ledger): "
              "measured siblings are counted per RECORD, so a multi-unit deck quoting one "
              "site-wide value casts one vote per unit (F21)")
    findings = []
    for field, slot in sorted(by_field.items()):
        if not slot["bare"]:
            continue                 # consistent field
        votes: dict = {}             # source file -> the unit that source writes
        for _, _, u, vote in slot["measured"]:
            votes.setdefault(vote, u)
        if len(votes) < args.min_siblings:
            continue                 # too little INDEPENDENT evidence to call it
        # a DOMINANT unit is required: a field whose measured sources disagree about their own
        # unit is a different (and worse) problem, and guessing which one the bare value meant
        # would be the invention this gate exists to prevent.
        units = list(votes.values())
        top = max(set(units), key=units.count)
        if units.count(top) * 2 < len(units):
            continue
        findings.append((field, slot["bare"], slot["measured"], top, len(votes)))
    # An OPEN tracker column (not a canonical card field) is ADVISORY, never a block.
    #
    # F5: the rationale WAS that the repair loader rejected any non-canonical `set` key, so a
    # broker's unit answer for an open column could never be applied and blocking would have
    # been an unresolvable loop with the answer swallowed. That is no longer true. The guard
    # now accepts a key the SCHEMA declares OR one the resolved target property already
    # carries, off-spec included ("an off-spec key the property DOES carry is repairable" -
    # repairs.apply), or one another property carries when the entry cites `source_file` +
    # `source_locator`, so an open capture column IS repairable today and a fix exists for
    # anyone who wants one.
    #
    # It stays advisory on the HARM instead, which is the reason that was always the real one:
    # this gate exists because ONE CARD GRID cannot show one field in two formats, and an open
    # column is not on the card grid. It ships in the detail view and the Longlist workbook as
    # the source printed it, where a bare number beside a measured sibling is a faithful
    # rendering of two source cells rather than a presentational contradiction. Note also that
    # the findings list is filtered to canonical fields BEFORE `--emit-json`, so no broker
    # question is ever raised for an open column and there is no answer to swallow either way.
    # The note below keeps the drift visible.
    try:
        _canon = set(C.canonical_property_fields()) | {"lat", "lng"}
    except Exception:
        _canon = set()
    if _canon:
        for field, bare, measured, top, n_src in [f for f in findings if f[0] not in _canon]:
            offenders = ", ".join(f"id={i} '{v}'" for i, v in bare[:6])
            print(f"  [note] `{field}` (an open tracker column, not a card field): "
                  f"{offenders} ship bare while {len(measured)} sibling(s) from {n_src} "
                  f"source(s) carry a unit - advisory only, shown as printed in the source")
        findings = [f for f in findings if f[0] in _canon]
    # machine-readable findings for run.py's clarify bridge (the broker question).
    # Written even when empty so the bridge never reads a stale file.
    if getattr(args, "emit_json", ""):
        def _printed_unit(measured, top):
            for _, s, u, _v in measured:
                if u == top:
                    m = _MEASURED.match(s)
                    if m:
                        return " ".join(m.group(1).split())
            return top
        payload = [{"field": field,
                    "dominant_unit": top,
                    "dominant_printed": _printed_unit(measured, top),
                    "measured_count": len(measured),
                    "measured_sources": n_src,
                    "examples": [s for _, s, _, _v in measured[:3]],
                    "bare": [{"id": i, "value": v} for i, v in bare]}
                   for field, bare, measured, top, n_src in findings]
        try:
            C.atomic_write_text(Path(args.emit_json),
                                json.dumps(payload, ensure_ascii=False, indent=1))
        except Exception as e:
            print(f"  [note] could not write findings json: {e}")
    for field, bare, measured, top, n_src in findings:
        examples = ", ".join(f"'{v}'" for _, v, _, _v in measured[:3])
        offenders = ", ".join(f"id={i} '{v}'" for i, v in bare[:6])
        _bad(f"`{field}`: {len(bare)} property(ies) ship a BARE number while "
             f"{len(measured)} (from {n_src} independent source(s)) write it as a magnitude + "
             f"unit ({top!r}) - {offenders} "
             f"against {examples}. Same field, two formats, on one card grid. Read the source "
             f"for the bare one(s) and record the correctly written value in "
             f"work/overrides.json - do NOT assume the unit is {top!r}; if the source does not "
             f"state it, ASK THE BROKER.")
    if findings:
        print("STATUS: BLOCKED")
        return 1
    _ok(f"every field is written consistently across the properties that carry it "
        f"({len(by_field)} field(s) checked)")
    print("STATUS: ALL-PASS")
    return 0


def cmd_ack(args) -> int:
    """MERGE keys into placeholder_audit_ack.json instead of authoring it whole. (B63)

    The images and arithmetic gates both point at this one file, and the QA window tells the
    orchestrator to dispatch gate fixes CONCURRENTLY - so two agents routinely write it in the
    same minute. Each wrote the whole document, so the second silently dropped the first's key
    and a gate that had been answered re-blocked on the next pass. Nothing in the file's shape
    caused that; the absence of a merge path did.

    Read-modify-write, atomic, list-union, order-stable, de-duplicating. It NEVER removes a key
    or a value: this file records what a reviewer has SEEN and signed off, so subtracting from
    it by accident is the one edit that must be impossible. Removing an entry stays a
    deliberate hand-edit.
    """
    path = Path(args.work) / "placeholder_audit_ack.json"
    cur: dict = {}
    if path.exists():
        try:
            cur = json.loads(path.read_text(encoding="utf-8-sig")) or {}
        except Exception as e:
            print(f"[FAIL] {path.name} is not valid JSON ({type(e).__name__}) - refusing to "
                  f"overwrite it; fix or delete the file first")
            print("STATUS: BLOCKED")
            return 1
    if not isinstance(cur, dict):
        print(f"[FAIL] {path.name} must be a JSON object - refusing to overwrite it")
        print("STATUS: BLOCKED")
        return 1
    added: list = []
    for pair in (args.add or []):
        if "=" not in pair:
            print(f"[FAIL] --add expects key=value[,value...], got {pair!r}")
            print("STATUS: BLOCKED")
            return 1
        key, _, raw = pair.partition("=")
        key = key.strip()
        vals = [v.strip() for v in raw.split(",") if v.strip()]
        if not key or not vals:
            print(f"[FAIL] --add expects a non-empty key and value, got {pair!r}")
            print("STATUS: BLOCKED")
            return 1
        old = cur.get(key)
        merged = list(old) if isinstance(old, list) else ([] if old is None else [old])
        for v in vals:
            if v not in merged:
                merged.append(v)
                added.append(f"{key}={v}")
        cur[key] = merged
    if args.note:
        cur["note"] = (str(cur.get("note") or "") + (" " if cur.get("note") else "")
                       + args.note).strip()
    if args.verified_by:
        cur["verified_by"] = args.verified_by
    C.atomic_write_text(path, json.dumps(cur, ensure_ascii=False, indent=1) + "\n")
    _ok(f"{path.name}: {len(added)} new value(s)"
        + (f" ({', '.join(added)})" if added else " - everything was already recorded")
        + f"; keys now {', '.join(sorted(k for k, v in cur.items() if isinstance(v, list)))}")
    print("STATUS: ALL-PASS")
    return 0


# F17: FORM DISAGREEMENT, capture-symmetry's sibling signal. Two isolated readers wrote two
# different forms of the same country ("UK" and "GB" are the live instance); `normalize.
# country_iso` happened to converge them at merge, so nothing was wrong. But that depends on
# ONE call site and on the alias table holding whichever form each reader chose: a name in
# the deck's own language, or an alias the table lacks, splits a KPI or a filter chip
# silently, with every value individually correct. The signal is cheap and general: for each
# field, group the raw forms by the form the pipeline would normalise them TO, and name any
# field where one normalised value arrives in two or more raw forms. Registered normalisers
# are the ones merge actually applies; every other short, non-numeric value gets a
# whitespace-and-case fold, which is exactly what a filter chip would split on.
_FORM_NORMALISERS = {
    "country": lambda v: N.country_iso(v).upper(),
    "areaUnit": N.area_unit_of,
    "rentUnit": N.rent_unit_of_text,
    "currency": N.currency_of,
}
#: longer than a label is prose, and prose never collides by form
FORM_FOLD_MAX_CHARS = 40


def _form_key(field: str, v):
    """The normalised form of `v` for `field`, or None when the value is not form-comparable
    (a number, a bool, a container, prose, or a value the field's normaliser rejects)."""
    if v is None or isinstance(v, (bool, int, float, dict, list)):
        return None
    s = " ".join(str(v).split())
    if not s or len(s) > FORM_FOLD_MAX_CHARS or _BARE_NUMBER.match(s):
        return None
    fn = _FORM_NORMALISERS.get(field)
    if fn is None:
        return s.casefold()
    try:
        k = fn(s)
    except Exception:
        return None
    return str(k) if k else None


def form_disagreements(records: list) -> list:
    """[{field, normalised, forms: [{form, records, sources}]}] for every field where ONE
    normalised value arrives in two or more raw forms across `records` (pre-merge dicts, each
    with __meta.source_file). Pure; the gate prints and files what this returns."""
    forms: dict = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        src = str((rec.get("__meta") or {}).get("source_file") or "?")
        for k, v in rec.items():
            if k == "__meta" or k in _PIPELINE_ASSIGNED or _absent(v, k):
                continue
            key = _form_key(k, v)
            if key is None:
                continue
            forms.setdefault(k, {}).setdefault(key, {}).setdefault(" ".join(str(v).split()), []).append(src)
    out = []
    for field, groups in sorted(forms.items()):
        for key, raw in sorted(groups.items()):
            if len(raw) < 2:
                continue
            out.append({"field": field, "normalised": key,
                        "via": "normaliser" if field in _FORM_NORMALISERS else "case/spacing fold",
                        "forms": [{"form": f, "records": len(srcs), "sources": sorted(set(srcs))}
                                  for f, srcs in sorted(raw.items(), key=lambda kv: (-len(kv[1]), kv[0]))]})
    return out


def _form_line(f: dict) -> str:
    shown = " and ".join(f"'{x['form']}' ({x['records']} record(s): {', '.join(x['sources'][:3])})"
                         for x in f["forms"][:3])
    if f["via"] == "normaliser":
        tail = ("merge converges these today through its registered normaliser, but a form "
                "outside that table (a name in the deck's own language, an alias it lacks) "
                "would split a KPI or a filter chip silently; confirm the readers mean one "
                "thing and that every form is an alias the pipeline knows")
    else:
        tail = ("they differ only by case or spacing and nothing normalises this field, so the "
                "grid and its filter chips show one value two ways; pick the source's own form "
                "for every record (a work/repairs.json `set`), or leave it disclosed")
    return (f"  [SIGNAL] `{f['field']}` arrives in {len(f['forms'])} FORMS of one value "
            f"({f['normalised']!r}): {shown} - {tail}")


# --- SHADOW KEYS: a non-registry key holding a datum whose canonical sibling ships a gap row (D15)
# capture-symmetry asked ONE question: did a reader skip fields its peers captured? The blind
# reviewers on the measured run found the sibling question it did not ask. The reader of
# `07_Unit-6-Symmetry-Park-Rugby.pdf` put the level-access door COUNTS into a descriptive
# non-registry key, `levelAccessDoors`, while the canonical home for that datum,
# `overheadDoors`, shipped a gap row reading "absent in all sources". So the honesty document
# asserted a FALSE ABSENCE: the datum was captured, under a different name, and the gap row said
# nobody stated it. The struck-value sweep could not see it precisely because the key differs.
#
# THE OPEN SCHEMA IS A FEATURE. "Capture every field the source states" is the Stage-1 rule, and
# a stated value with no canonical home is SUPPOSED to ship under a descriptive camelCase key.
# So the finding is never "a non-registry key exists". It is specifically: a non-registry key
# that is plausibly the SAME DATUM as a canonical field which is reported ABSENT. The pairing
# test is the whole job, and it is deliberately strict, because a loose match produces noise
# that trains operators to ignore the gate, which is worse than the gap.
#
# HOW TWO NAMES ARE JUDGED TO MEAN ONE THING - reused, not reinvented. extract_xlsx.COLUMN_MAP is
# this skill's own declaration of which header spellings mean which field ("level access doors",
# "overhead doors", "drive in doors", "ground level doors" all mean `overheadDoors`), already
# widened with assets/label_ledger.json's multilingual labels, and already carrying per-field
# NEGATIVE vetoes ("ratio|total" must never bind overheadDoors). The open key is humanised
# (camelCase -> words) and matched against that table at the table's own two strictest tiers:
# exact equality, or `fuzz.ratio >= 90`, the fuzzy tier `_header_candidates` uses. Whole-word
# CONTAINMENT (the table's middle tier) is deliberately NOT used here: it is right for a column
# header, where "Motorway" in "Motorway drive time" is the column's subject, and wrong for this
# question, where `motorwayDriveTime` is a drive time and not the junction locator. Known misses
# accepted for that precision: `levelAccessDoors4x5m` (a dimensioned breakdown), `officeAreaSqm`
# (a unit variant) and `totalFloorArea` (see the next paragraph) do not pair. A number-typed
# sibling (warehouseArea, plotArea) additionally requires the open value to carry a number, so a
# prose key cannot pair with an area.
#
# `totalFloorArea` IS AN ACCEPTED MISS AND MUST STAY ONE - do not re-open this. It scores 76.9
# against warehouseArea's nearest aliases ('total area', 'floor area'), under SHADOW_FUZZ_MIN, so
# it does not pair. Closing it by appending "total floor area" to extract_xlsx.COLUMN_MAP's
# warehouseArea aliases was proposed, measured and REFUSED, for two reasons.
#
# (1) MEASURED COLLATERAL. A sweep of 188,442 candidate headers through the real
# `extract_xlsx._header_field` found the alias changes three column bindings, and that one of the
# three binds WRONG: "Total Door Area" moves from unbound (open capture) to `warehouseArea`,
# because warehouseArea's negative veto (extract_xlsx.py:159, `plot|land|office|unit\b|ratio`)
# does not cover "door". A door-area column would silently become the card's warehouse area,
# feeding the size filter, the sort, Total GLA and rent x GLA. The same alias reaches into this
# gate too: `totalDoorArea` newly pairs at 90.3 and `totalFloorArea2` at 94. And the extractor
# gains nothing for that cost - a column header "Total Floor Area" already binds warehouseArea
# through the table's containment tier, which is a tier only this gate declines to use.
#
# (2) THE SEMANTICS ARE WRONG. This is the deeper reason, and it holds wherever the alias is put.
# A printed TOTAL is a first-class, separately-homed datum in this skill: the reader contract
# (prompts/reader-text.md) sends it to `__meta.statedTotalArea` + `statedTotalUnit`, "never a
# total you computed", and `glaVal()` PREFERS `preBaked.statedTotal` over warehouse plus office
# (reference/template-contract.md). Of every area spelling, `totalFloorArea` is the one whose
# NAME asserts most strongly "this is the stated total". Pairing it with `warehouseArea` invites
# a repair that sets warehouseArea to a figure already including the office, which is defect
# P1-1: that shipped once with GLA 11.7 per cent above the source's own stated total and rent
# overstated by GBP 702,108 a year. Nothing would catch the repair, either, because
# `merge.stated_total_for` reads only `__meta.statedTotalArea` - a repairs.json `set` never
# populates statedTotals, so the arithmetic gate skips that property entirely.
#
# SAID HONESTLY: this is a boundary the table ALREADY sits on. Eight plainer spellings do pair
# with warehouseArea today through the existing entries - `totalArea`, `floorArea`, `gia`, `gla`,
# `totalSize`, `size`, `buildingSize`, `areaSqm` (verified by calling `shadow_pairs` against an
# absent `warehouseArea`). Those entries are not being called wrong here. The claim is narrower
# and is only about direction: the table must not be extended FURTHER toward the stated-total
# end of the range, where the open key's own name claims to be the datum merge homes elsewhere.
#
# "SHIPS A GAP ROW" IS READ LITERALLY when it can be: the Source Ledger's `record_type=property`,
# `source_type=gap` row whose locator is the "absent in all sources" claim. A gap row merge wrote
# with a stated reason instead (B58's "stated as N in a unit this dataset cannot express", B63's
# "carries no single number") is an honest withholding, not a false absence, and is not paired.
# A gap row a repair has since superseded is re-typed by merge and drops out on its own. Without
# a ledger the check falls back to canonical's own absence and says so; without a canonical (an
# extract-only work dir) it judges each pre-merge record on its own and says THAT.
#
# SIGNAL, NOT FAIL - the call and its reasons. This gate is advisory (run.py appends its result
# to the scorecard on the stated understanding that it always returns 0, and two evals pin it).
# A false absence is more serious than ordinary under-capture: it is an affirmative wrong claim
# in the one document whose job is honesty, not merely a missing one. But the pairing is still a
# NAME-similarity judgement, however strict, and the remedy needs a human to confirm that the
# two names are one datum before a repair moves a value between them. Blocking a client
# deliverable on a name heuristic, or gating it behind an ack key, teaches operators to ack
# through. So the class is promoted as far as an advisory gate can promote it: EVERY shadow
# finding is a SIGNAL unconditionally (never demoted by SIGNAL_MIN_RECORDS, never capped by
# --max-notes), it prints ABOVE the asymmetry findings, it names both keys and the property so
# one repair closes it, and it lands in the sidecar under its own key.
SHADOW_FUZZ_MIN = 90                      # the fuzzy tier extract_xlsx._header_candidates uses
GAP_ROW_CLAIM = "absent in all sources"   # merge's gap-row locator; the claim this checks
# fields whose gap-row aliases live under ANOTHER key in COLUMN_MAP (the tracker maps a rent
# column to the numeric twin; the chrome-read field that ships the gap row is the display one)
_SHADOW_ALIAS_SOURCE = {"warehouseRent": "warehouseRentVal"}
_SHADOW_CACHE: dict = {}


def _shadow_norm(s) -> str:
    """One spelling for a field name or an alias: diacritics stripped, lower-cased, non-
    alphanumerics to spaces, and the LAST word singularised so 'level access doors' and 'level
    access door' meet. Applied to both sides, so the fold can never create a match one side
    did not earn. Reuses match.strip_diacritics rather than a third copy of it."""
    try:
        import match as _match
        t = _match.strip_diacritics(str(s or ""))
    except Exception:
        t = str(s or "")
    words = re.sub(r"[^a-z0-9]+", " ", t.lower()).split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def _humanise_key(k: str) -> str:
    """`levelAccessDoors` -> 'level access doors'; digits are split off their letters too
    (`levelAccessDoors4x5m` -> 'level access doors 4 x 5 m'), so a dimensioned breakdown
    reads as what it is instead of as one long token."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(k or ""))
    s = re.sub(r"(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])", " ", s)
    return s.lower()


def _shadow_registry() -> dict:
    """{canonical field that ships a gap row: {"aliases": [normalised], "veto": regex|None,
    "numeric": bool}}, memoised.

    Siblings are the fields merge writes an "absent in all sources" row for that a READER could
    have captured: every chrome-read string field plus the identity sentinels and the three
    reader-captured numerics (warehouseArea, plotArea, landPrice); the pipeline-assigned ones
    (`_PIPELINE_ASSIGNED`) are excluded because a reader is not asked for them. Aliases come
    from extract_xlsx.COLUMN_MAP, the humanised field name, and the field's own display label;
    with extract_xlsx unimportable (openpyxl missing) it degrades to the field names plus
    assets/label_ledger.json, and says nothing - a thinner table means fewer pairs, never a
    wrong one."""
    if _SHADOW_CACHE:
        return _SHADOW_CACHE
    siblings = ((set(C.STRING_FIELDS) | set(C.REQUIRED_TEXT_SENTINELS)
                 | {"warehouseArea", "plotArea", "landPrice"}) - _PIPELINE_ASSIGNED)
    col_map, negative = {}, {}
    try:
        import extract_xlsx as _X
        col_map = dict(getattr(_X, "COLUMN_MAP", {}) or {})
        negative = dict(getattr(_X, "NEGATIVE", {}) or {})
    except Exception:
        try:
            led = json.loads((C.ASSETS / "label_ledger.json").read_text(encoding="utf-8"))
            col_map = {f: list((v or {}).get("aliases") or [])
                       for f, v in (led.get("fields") or {}).items() if isinstance(v, dict)}
        except Exception:
            col_map = {}
    numeric: set = set()
    try:
        props = ((json.loads(C.SCHEMA_FILE.read_text(encoding="utf-8-sig")).get("$defs") or {})
                 .get("property") or {}).get("properties") or {}
        for f, spec in props.items():
            t = (spec or {}).get("type")
            if t == "number" or (isinstance(t, list) and "number" in t):
                numeric.add(f)
    except Exception:
        pass
    reg: dict = {}
    for f in sorted(siblings):
        src = _SHADOW_ALIAS_SOURCE.get(f, f)
        names = {_humanise_key(f)} | {str(a) for a in (col_map.get(src) or [])}
        aliases = sorted({_shadow_norm(a) for a in names if _shadow_norm(a)})
        reg[f] = {"aliases": aliases, "veto": negative.get(src), "numeric": f in numeric}
    _SHADOW_CACHE.update(reg)
    return _SHADOW_CACHE


def shadow_pairs(open_key: str, value, absent_fields) -> list[dict]:
    """The canonical fields in `absent_fields` that `open_key` plausibly names, with how the
    match was made. Empty for an unrelated open key, which is the common and correct case."""
    if not isinstance(open_key, str) or not open_key or open_key.startswith("_"):
        return []
    # `_absent` takes ONE argument here by design, not by slip. It delegates to `_unknown(v,
    # field)`, which reads `field` only to pick the CODE reading, and only for CODE_FIELDS - one
    # member, `country`. Measured: `field` changes the answer for exactly three values ("na",
    # "nc", "sc" - normalize.CODE_LIKE_EXEMPT), and only when the field is `country`. `open_key`
    # is by construction NOT a registry field (both callers skip the registry), so passing it
    # could change no answer here, and would assert the very thing this function exists to deny.
    if isinstance(value, (dict, list)) or _absent(value):
        return []
    if isinstance(value, str) and value.startswith("data:"):
        return []
    human = _humanise_key(open_key)
    hk = _shadow_norm(human)
    if not hk:
        return []
    reg = _shadow_registry()
    out = []
    for field in sorted(absent_fields):
        spec = reg.get(field)
        if not spec:
            continue
        if spec["veto"] is not None and spec["veto"].search(human):
            continue
        if spec["numeric"] and N.extract_first_number(str(value)) is None:
            continue
        how = None
        for alias in spec["aliases"]:
            if hk == alias:
                how = f"'{human}' is a known alias of {field}"
                break
            try:
                score = _fuzz.ratio(hk, alias)
            except Exception:
                score = 0
            if score >= SHADOW_FUZZ_MIN:
                how = (f"'{human}' matches the {field} alias '{alias}' at {score:.0f}/100, "
                       f"the tracker column-map's own fuzzy tier")
                break
        if how:
            out.append({"field": field, "how": how})
    return out


def _ledger_gap_index(work: Path):
    """(gap claims {(pid, field)}, property rows {(pid, field): row}) from the Source Ledger,
    or (None, None) when there is no ledger to read - two different answers."""
    path = Path(work) / "source_ledger.csv"
    if not path.exists():
        return None, None
    gaps, rows = set(), {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if (r.get("record_type") or "").strip() != "property":
                    continue
                key = (str(r.get("property_id") or "").strip(), str(r.get("field") or "").strip())
                if (r.get("source_type") or "").strip().lower() == "gap":
                    if (r.get("source_locator") or "").strip().lower() == GAP_ROW_CLAIM:
                        gaps.add(key)
                else:
                    rows.setdefault(key, r)
    except Exception:
        return None, None
    return gaps, rows


def _record_label(rec: dict) -> str:
    for k in ("unit", "park", "city"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip() and not _absent(v, k):
            return v.strip()
    return "record"


def shadow_findings(work: Path, all_recs: list) -> list[dict]:
    """Every (non-registry key, absent canonical sibling) pair worth a repair, property-scoped
    when canonical.json exists and record-scoped otherwise. Pure apart from reading the two
    files; the gate prints and files what this returns."""
    registry = set(C.canonical_property_fields())
    siblings = set(_shadow_registry())
    out: list = []
    cpath = Path(work) / "canonical.json"
    if cpath.exists():
        try:
            props = (C.load_canonical(cpath).get("properties") or [])
        except Exception:
            props = []
        gaps, prow = _ledger_gap_index(work)
        for p in props:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id"))
            absent = {f for f in siblings if _absent(p.get(f), f)}
            if gaps is not None:
                absent = {f for f in absent if (pid, f) in gaps}
            if not absent:
                continue
            for k in sorted(p):
                if k in registry or k == "__meta":
                    continue
                for pair in shadow_pairs(k, p.get(k), absent):
                    row = (prow or {}).get((pid, k)) or {}
                    out.append({"kind": "shadow", "scope": "property", "property_id": pid,
                                "open_key": k, "open_value": str(p.get(k))[:60],
                                "field": pair["field"], "how": pair["how"],
                                "source_file": str(row.get("source_file") or ""),
                                "locator": str(row.get("source_locator") or "")[:120],
                                "ledger": ("gap row" if gaps is not None else "not read"),
                                "core": pair["field"] in CAPTURE_CORE_FIELDS, "signal": True})
        return out
    for rec in all_recs:
        if not isinstance(rec, dict):
            continue
        meta = rec.get("__meta") or {}
        absent = {f for f in siblings if _absent(rec.get(f), f)}
        if not absent:
            continue
        for k in sorted(rec):
            if k in registry or k == "__meta":
                continue
            for pair in shadow_pairs(k, rec.get(k), absent):
                out.append({"kind": "shadow", "scope": "record", "property_id": "",
                            "open_key": k, "open_value": str(rec.get(k))[:60],
                            "field": pair["field"], "how": pair["how"],
                            "source_file": str(meta.get("source_file") or ""),
                            "record": _record_label(rec), "locator": "",
                            "ledger": "pre-merge", "core": pair["field"] in CAPTURE_CORE_FIELDS,
                            "signal": True})
    return out


def _shadow_line(f: dict) -> str:
    where = f.get("source_file") or "?"
    if f.get("locator"):
        where += f", {f['locator']}"
    fix = (f"Repair: work/repairs.json `set` {f['field']} on property "
           f"{f.get('property_id') or '<id>'} to the value the source states (cite the page), and "
           f"`unset` {f['open_key']} if the card should not show it twice; or confirm the two are "
           f"genuinely different data")
    if f.get("scope") == "record":
        return (f"  [SIGNAL] {where} record '{f.get('record', 'record')}': the reader put "
                f"{f['open_value']!r} under the non-registry key `{f['open_key']}` and left its "
                f"canonical home `{f['field']}` empty on the same record - the same datum under a "
                f"different name, so unless another record of this property states `{f['field']}` "
                f"merge will ship a FALSE '{GAP_ROW_CLAIM}' gap row for it ({f['how']}). {fix}")
    claim = (f"ships a gap row ('{GAP_ROW_CLAIM}')" if f.get("ledger") == "gap row"
             else "is empty on the card (no Source Ledger was readable to confirm its gap row)")
    return (f"  [SIGNAL] property {f['property_id']}: the non-registry key `{f['open_key']}` = "
            f"{f['open_value']!r} ({where}) while its canonical home `{f['field']}` {claim} - the "
            f"same datum under a different name, so that gap row is a FALSE absence in the Gaps "
            f"Report and Source Ledger ({f['how']}). {fix}")


def cmd_capture_symmetry(args) -> int:
    """Cross-source field asymmetry - the cheap signal for UNDER-CAPTURE. (B58)

    A reader that skips rows a deck prints is invisible to every other gate: validate-data,
    coverage and trace-coverage all check that POPULATED fields trace to a source, and none
    of them can know what the page said. Merge then converts each omission into a positive
    "absent in all sources" ledger row, so silence becomes a false claim. On one live run
    that shipped ~100 of them and cost two Opus reviewers to find.

    The signal is nearly free: if file A's records carry `sprinklers` and file B's carry it
    on ZERO records, either B's deck genuinely never states it or B's reader dropped it.
    ADVISORY on purpose - different agents really do use different templates, so an
    asymmetry is a question for the reviewers, never a verdict.

    RANKING (B62). Being advisory is not a licence to be unreadable. A corpus of nine decks
    produces ~160 asymmetries, and printed as one flat list ranked by how many sources carry
    the field, the material ones are indistinguishable from the noise: on the run that
    prompted this, `status` (31 records, a core field, and a genuine reader miss on every
    page of a 23-property deck) printed as note 14 of 161 above `... and 136 more`, and it
    took two Opus reviewers to find what this gate had already computed. So each finding now
    carries how many RECORDS it affects, a core field is always a SIGNAL, SIGNAL findings
    print first and uncapped, and the full list is written to work/capture_symmetry.json so
    the capped tail survives.

    SHADOW KEYS (D15), the sibling question. The asymmetry above asks whether a reader SKIPPED
    a field its peers captured. It cannot see a reader that captured the datum under a
    DIFFERENT NAME: on the measured run `levelAccessDoors` held the door counts while the
    canonical `overheadDoors` shipped "absent in all sources", a false absence in the honesty
    document itself, found only by blind human reviewers. `shadow_findings` pairs each
    non-registry key with an ABSENT canonical sibling through the tracker column-map's own
    alias table at its two strictest tiers (see the block above `_shadow_registry` for the
    pairing rules, what is deliberately not matched, and why every such finding is a SIGNAL
    but never a FAIL). Shadow findings print FIRST, uncapped, name both keys and the property,
    and run even on a single-source corpus, because one deck can shadow itself.
    """
    work = Path(args.work)
    by_source: dict[str, dict] = {}
    all_recs: list = []
    for path in sorted((work / "extract").glob("*.json")):
        try:
            recs = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(recs, list):
            continue                      # maps/caches (tracker maps, region labels) are not records
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            meta = rec.get("__meta") or {}
            src = meta.get("source_file") or path.name
            slot = by_source.setdefault(src, {"n": 0, "fields": set()})
            slot["n"] += 1
            all_recs.append(rec if meta.get("source_file") else dict(rec, __meta=dict(meta, source_file=src)))
            for k, v in rec.items():
                if k == "__meta" or k in _PIPELINE_ASSIGNED:
                    continue
                if not _absent(v, k):
                    slot["fields"].add(k)
    # D15: SHADOW KEYS print first of all. A false absence is the most serious thing this gate
    # can find, it needs no second source to exist, and a capped tail must never hide it.
    shadow_sigs = shadow_findings(work, all_recs)
    for f in shadow_sigs:
        print(_shadow_line(f))
    _extra = ((f"; {len(shadow_sigs)} shadow-key SIGNAL(s) above (a non-registry key holding a "
               f"datum whose canonical home ships a gap row)") if shadow_sigs else "")
    # F17: printed FIRST and uncapped, like every SIGNAL here. Two records of ONE source can
    # disagree on form too (a deck read in two halves), so this runs before the source-count
    # gate below and is not subject to it.
    form_sigs = form_disagreements(all_recs)
    for f in form_sigs:
        print(_form_line(f))
    sources = {s: d for s, d in by_source.items() if d["n"]}
    if len(sources) < 2:
        _ok(f"capture symmetry not applicable ({len(sources)} source(s) with records)"
            + (f"; {len(form_sigs)} form disagreement(s) above" if form_sigs else "") + _extra)
        if shadow_sigs:
            _write_capture_sidecar(work, sources, [], [], shadow_sigs)
        print("STATUS: ALL-PASS")
        return 0
    everywhere = sorted(set().union(*(d["fields"] for d in sources.values())))
    findings = []
    for field in everywhere:
        have = sorted(s for s, d in sources.items() if field in d["fields"])
        miss = sorted(s for s, d in sources.items() if field not in d["fields"])
        if have and miss:
            # AFFECTED is the materiality this gate was missing. A field absent from a
            # 23-record deck becomes 23 "absent in all sources" ledger rows; absent from a
            # 1-record flyer it becomes one. Ranked only by len(have), those two printed
            # identically - which is how the one real finding of a live run (status, 31
            # records) sat at note 14 of 161 and was read as noise.
            affected = sum(sources[s]["n"] for s in miss)
            present = sum(sources[s]["n"] for s in have)
            findings.append({"field": field, "have": have, "miss": miss,
                             "affected_records": affected, "present_records": present,
                             "core": field in CAPTURE_CORE_FIELDS})
    if not findings:
        _ok(f"every field is captured symmetrically across {len(sources)} source(s)"
            + (f"; {len(form_sigs)} form disagreement(s) above" if form_sigs else "") + _extra)
        if shadow_sigs:
            _write_capture_sidecar(work, sources, form_sigs, [], shadow_sigs)
        print("STATUS: ALL-PASS")
        return 0
    for f in findings:
        f["signal"] = bool(f["core"] or (f["affected_records"] >= SIGNAL_MIN_RECORDS
                                         and f["present_records"] >= SIGNAL_MIN_PRESENT))
        # weight = min(affected, present): high only when the field is BOTH well established
        # elsewhere and materially missing here, which is what "a reader skipped stated rows"
        # actually looks like. Ranking on affected alone floats the rarest fields to the top.
        f["weight"] = min(f["affected_records"], f["present_records"])
    findings.sort(key=lambda f: (not f["signal"], not f["core"], -f["weight"],
                                 -f["affected_records"], -f["present_records"], f["field"]))
    # the FULL list always lands on disk, so the capped tail is never simply lost
    _write_capture_sidecar(work, sources, form_sigs, findings, shadow_sigs)

    def _line(f, tag):
        return (f"  [{tag}] `{f['field']}` captured from {', '.join(f['have'])} but from NONE "
                f"of {', '.join(f['miss'])} ({f['affected_records']} record(s) there would ship "
                f"an 'absent in all sources' claim) - confirm those deck(s) genuinely do not "
                f"state it, rather than the reader having skipped the row")

    signals = [f for f in findings if f["signal"]]
    rest = [f for f in findings if not f["signal"]]
    for f in signals:                     # UNCAPPED: a signal must never fall off the tail
        print(_line(f, "SIGNAL"))
    shown = rest[: max(0, args.max_notes - len(signals))]
    for f in shown:
        print(_line(f, "note"))
    if len(rest) > len(shown):
        print(f"  [note] ... and {len(rest) - len(shown)} more asymmetric field(s) - the full "
              f"list is in {work / 'capture_symmetry.json'}")
    _ok(f"{len(findings)} cross-source field asymmetry note(s) across {len(sources)} source(s), "
        f"{len(signals)} of them SIGNAL (a core field, or >= {SIGNAL_MIN_RECORDS} records "
        f"affected with >= {SIGNAL_MIN_PRESENT} carrying it elsewhere)"
        + (f", plus {len(form_sigs)} form disagreement SIGNAL(s)" if form_sigs else "")
        + (f", plus {len(shadow_sigs)} shadow-key SIGNAL(s)" if shadow_sigs else "")
        + " - ADVISORY, for the G-honesty/G-trace reviewers to re-derive")
    print("STATUS: ALL-PASS")
    return 0


def _write_capture_sidecar(work: Path, sources: dict, form_sigs: list, findings: list,
                           shadow_sigs: list) -> None:
    """work/capture_symmetry.json - the FULL finding lists, so a capped console tail is never
    simply lost. `shadow_findings` (D15) is a new key beside the existing ones; a reader of the
    old shape sees exactly the fields it saw before. Best-effort, never raises."""
    try:
        (work / "capture_symmetry.json").write_text(
            json.dumps({"sources": {s: d["n"] for s, d in sorted(sources.items())},
                        "signal_min_records": SIGNAL_MIN_RECORDS,
                        "signal_min_present": SIGNAL_MIN_PRESENT,
                        "form_disagreements": form_sigs,
                        "findings": findings,
                        "shadow_findings": shadow_sigs}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass


# --- MEDIA HARVEST ------------------------------------------------------------------------ #
# capture-symmetry's twin, one layer over: that gate asks whether a reader skipped FIELDS a page
# printed; this asks whether the harvest skipped IMAGES a deck holds.
MEDIA_SIGNAL_IMAGES = 6    # a deck holding this many hero-size rasters, all offered to a property
#                            that looked at ONE page, is a shortfall worth naming
MEDIA_SIGNAL_PAGES = 4     # ...or this many pages, same reasoning stated in pages
MEDIA_THIN_GALLERY = 3     # a card carrying this few carousel images is VISIBLY thin


def _media_claims(work: Path) -> tuple[dict, list]:
    """(claims, unassigned) - which deck pages each property actually LOOKED at.

    Primary source is `work/media_considered.json`, merge's own recording of the considered set
    (authoritative: it already has the foreign-page subtraction and the plan-offlimits rules
    applied). It falls back to re-deriving the claim from the extract records' `__meta`
    (`page_no` union the validated `image_pages`) so the gate still answers on a work dir written
    before that sidecar existed, or one where merge did not reach the write. ({}, []) when
    neither is readable - the gate then reports only what it can prove."""
    considered = work / "media_considered.json"
    if considered.exists():
        try:
            obj = json.loads(considered.read_text(encoding="utf-8-sig")) or {}
            props = obj.get("properties") or []
            if isinstance(props, list):
                claims = {}
                for p in props:
                    if isinstance(p, dict) and p.get("id") is not None:
                        claims[str(p["id"])] = p
                return claims, list(obj.get("unassigned") or [])
        except Exception:
            pass
    return {}, []


def cmd_media_harvest(args) -> int:
    """Did the run actually HARVEST the media its sources hold? (media under-harvest)

    MOSTLY ADVISORY, with TWO BLOCKING HARD FACTS - see "WHY MOSTLY ADVISORY" below.

    THE DEFECT THIS EXISTS FOR. Every media tier in `images.py` degrades to an honest `None` or
    `[]` when it cannot answer - which is right, and is exactly why a dead image layer is
    INVISIBLE. On a live 17-property run the placed-image geometry backend was absent, so the
    hero tier-B crop and the WHOLE site-plan geometry tier returned zero on every page of every
    deck; the interpretation agents were handed manifests carrying `render: null` and
    `candidates: []`; and eleven cards shipped with no site plan and a one- or two-image gallery.
    Not one gate could fire, because nothing in the pipeline compared what a source HOLDS with
    what the run TOOK from it. Every artefact of that run is indistinguishable from a run whose
    sources genuinely hold nothing. This gate makes the comparison.

    WHY MOSTLY ADVISORY. Three of the five signals below are HEURISTICS about what a source
    MIGHT hold: a single-page listing in a whole-park donor deck and a one-pager that really
    does have one photo are both legitimate, so blocking on them would fire on almost every
    honest run and train the ack reflex - which is what devalues a sign-off key. The house
    already places this class (under-capture) at advisory-with-SIGNAL - `capture-symmetry` does
    exactly this and routes to the G-honesty/G-images reviewers.

    WHY TWO OF THEM BLOCK. Signals 1 and 4 are not heuristics at all: they are HARD FACTS about
    this run - a capability probe that came back false, and an agent that provably received zero
    renders. Both mean a whole tier of the pipeline did not run, and both are indistinguishable
    in every other artefact from "the sources hold nothing", which is exactly how this class of
    failure shipped silently to a broker. A gate that only whispers about a dead image layer is
    not a gate. They BLOCK (exit 1, STATUS: BLOCKED).

    A legitimately renderer-less environment is still a legitimate run, so both have the house
    remedy - an explicit, recorded sign-off merged into `placeholder_audit_ack.json` by
    `gate_runner.py ack --work <work> --add <key>=<value>`, the same file and command the
    `images` and `arithmetic` gates use. Proceeding stays possible; doing so silently does not.
      * `media_capability_ok=<cap>`         (e.g. `renderer`, or `all`)
      * `blind_interpretation_ok=<deck.pdf>` (or `all`)

    Five things it says out loud:
      1. a media CAPABILITY that is unavailable on this host (a HARD probe - BLOCKING);
      2. a property that looked at ONE page of a deck holding many pages / many hero-size images;
      3. a property with NO site plan whose own deck still has pages it never looked at;
      4. a text-mode deck that shipped ZERO per-page renders to its interpretation agent
         (i.e. that agent was asked to pick `plan_page` while blind - BLOCKING);
      5. deck pages NO property claimed at all.
    (2, 3 and 5 stay ADVISORY - they are ranked hints for the G-images reviewer.)
    """
    import images as IMG
    work = Path(args.work)
    data = C.load_canonical(Path(args.canonical))
    props = data.get("properties") or []
    ph = IMG.placeholder()
    caps = IMG.media_capabilities()
    # the SAME sign-off file the images and arithmetic gates read, merged by `gate_runner ack`
    ack_file = work / "placeholder_audit_ack.json"
    ack: dict = {}
    if ack_file.exists():
        try:
            ack = json.loads(ack_file.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            ack = {}

    def _acked(key: str, value: str) -> bool:
        """True when a reviewer has signed this exact item off (or the whole key with 'all')."""
        vals = ack.get(key)
        vals = vals if isinstance(vals, list) else ([] if vals is None else [vals])
        low = {str(v).strip().lower() for v in vals}
        return "all" in low or str(value).strip().lower() in low

    claims, unassigned = _media_claims(work)
    aids = {}
    try:
        aids = json.loads((work / "vision" / "visual_aids.json").read_text(encoding="utf-8-sig")) or {}
    except Exception:
        aids = {}
    folder = None
    try:
        folder = Path(json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))["folder"])
    except Exception:
        folder = None

    deck_facts: dict = {}

    def _facts(name: str) -> dict:
        """What the named deck HOLDS (pages + hero-size rasters), memoised. {} when the source
        file cannot be located from this work dir - the gate then simply has no signal for it."""
        if name in deck_facts:
            return deck_facts[name]
        f = {}
        if folder is not None:
            for cand in (folder / name, *folder.rglob(name)):
                if cand.exists():
                    f = IMG.deck_media_facts(cand) or {}
                    break
        deck_facts[name] = f
        return f

    findings: list = []

    # (1) CAPABILITY - a hard fact about this host, and the only one of the five that can
    # explain ALL the others at once, so it is reported first and always.
    for cap in IMG.MEDIA_CRITICAL_CAPS:
        if not caps.get(cap):
            findings.append({"kind": "capability", "signal": True, "weight": 10 ** 6,
                             "what": cap,
                             "blocking": not _acked("media_capability_ok", cap),
                             "acked": _acked("media_capability_ok", cap),
                             "text": (f"media capability `{cap}` is UNAVAILABLE on this host "
                                      f"(engine {caps.get('engine')}, geometry backend "
                                      f"{caps.get('geometry_backend')}) - every media tier that "
                                      f"needs it degrades to an honest null, so thin galleries "
                                      f"and missing site plans below may be THIS, not the "
                                      f"sources")})

    # (2)/(3) per property: what it took vs what its decks hold
    for p in props:
        pid = str(p.get("id"))
        label = p.get("park") or p.get("city") or f"#{pid}"
        gal_n = len(p.get("gallery") or [])
        has_plan = isinstance(p.get("plan"), str) and p["plan"].startswith("data:image/")
        placeholder_hero = (p.get("photo") == ph)
        thin = placeholder_hero or (gal_n <= MEDIA_THIN_GALLERY) or not has_plan
        for deck, info in sorted((claims.get(pid, {}).get("decks") or {}).items()):
            looked = sorted({int(x) for x in (info.get("looked") or [])})
            f = _facts(deck)
            pages, imgs = f.get("pages"), f.get("large_images")
            if pages is None:
                continue
            unlooked = [i for i in range(pages) if i not in set(looked)]
            if (len(looked) == 1 and (int(imgs or 0) >= MEDIA_SIGNAL_IMAGES
                                      or pages >= MEDIA_SIGNAL_PAGES)):
                findings.append({
                    "kind": "under-harvest", "signal": bool(thin), "property": label, "id": pid,
                    "deck": deck, "looked": looked, "pages": pages, "large_images": imgs,
                    "gallery": gal_n, "plan": has_plan,
                    "weight": (pages - 1) * 10 + max(0, int(imgs or 0) - gal_n),
                    "text": (f"id={pid} {label}: looked at page {looked[0] + 1} ONLY of "
                             f"`{deck}` ({pages} pages, {imgs} hero-size image(s)) and shipped a "
                             f"{gal_n}-image gallery"
                             + ("" if has_plan else " and NO site plan")
                             + " - confirm the other pages really are another property's / hold "
                               "nothing for this card, rather than never having been read")})
            elif not has_plan and unlooked:
                findings.append({
                    "kind": "no-plan-unlooked", "signal": True, "property": label, "id": pid,
                    "deck": deck, "looked": looked, "pages": pages, "unlooked": unlooked,
                    "gallery": gal_n, "plan": False, "weight": len(unlooked),
                    "text": (f"id={pid} {label}: NO site plan bound, and {len(unlooked)} page(s) "
                             f"of `{deck}` were never looked at (pages "
                             f"{', '.join(str(i + 1) for i in unlooked[:12])}"
                             f"{' ...' if len(unlooked) > 12 else ''}) - a site plan may be "
                             f"sitting on one of them")})

    # (4) an interpretation agent that was asked to pick a plan page while BLIND
    for deck, a in sorted(aids.items()):
        if not isinstance(a, dict) or a.get("mode") != "text":
            continue
        if int(a.get("pages") or 0) > 1 and int(a.get("renders") or 0) == 0:
            findings.append({
                "kind": "no-renders", "signal": True, "deck": deck, "weight": 10 ** 5,
                "blocking": not _acked("blind_interpretation_ok", deck),
                "acked": _acked("blind_interpretation_ok", deck),
                "pages": a.get("pages"), "candidates": a.get("candidates"),
                "text": (f"`{deck}`: the interpretation agent was handed {a.get('pages')} page(s) "
                         f"with ZERO page renders and {a.get('candidates') or 0} candidate "
                         f"thumbnail(s) - it was asked to pick __meta.plan_page / image_pages "
                         f"while BLIND, so a null answer from it means nothing")})

    # (5) pages NO property claimed at all
    for u in unassigned:
        if not isinstance(u, dict):
            continue
        pgs = sorted({int(x) for x in (u.get("pages") or [])})
        if not pgs:
            continue
        findings.append({
            "kind": "orphan-pages", "signal": True, "deck": u.get("file"), "pages": pgs,
            "weight": len(pgs),
            "text": (f"`{u.get('file')}`: {len(pgs)} page(s) that NO property claimed (pages "
                     f"{', '.join(str(i + 1) for i in pgs[:12])}"
                     f"{' ...' if len(pgs) > 12 else ''}) - every image on them is outside the "
                     f"run's reach; work/properties/_unassigned/ holds them for inspection")})

    # `deck_media_facts` opens each deck through IMG's shared doc cache, and the gates run
    # IN-PROCESS inside run.py - a held handle blocks the caller's temp-dir cleanup on Windows.
    # Everything above is already computed, so release them here.
    try:
        IMG.close_doc_cache()
    except Exception:
        pass
    findings.sort(key=lambda f: (not f.get("signal"), -f.get("weight", 0),
                                 str(f.get("kind")), str(f.get("property") or f.get("deck") or "")))
    try:
        work.mkdir(parents=True, exist_ok=True)
        (work / "media_harvest.json").write_text(
            json.dumps({"capabilities": caps,
                        "thresholds": {"images": MEDIA_SIGNAL_IMAGES, "pages": MEDIA_SIGNAL_PAGES,
                                       "thin_gallery": MEDIA_THIN_GALLERY},
                        "decks": deck_facts, "visual_aids": aids,
                        "findings": findings}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass

    signals = [f for f in findings if f.get("signal")]
    rest = [f for f in findings if not f.get("signal")]
    blocking = [f for f in findings if f.get("blocking")]
    for f in signals:                     # UNCAPPED: a signal must never fall off the tail
        print(f"  [{'FAIL' if f.get('blocking') else 'SIGNAL'}] {f['text']}")
    shown = rest[: max(0, args.max_notes - len(signals))]
    for f in shown:
        print(f"  [note] {f['text']}")
    if len(rest) > len(shown):
        print(f"  [note] ... and {len(rest) - len(shown)} more media note(s) - the full list is "
              f"in {work / 'media_harvest.json'}")
    missing = [c for c in IMG.MEDIA_CRITICAL_CAPS if not caps.get(c)]
    _ok(f"media harvest: {len(findings)} finding(s), {len(signals)} SIGNAL; capabilities "
        + (f"DEGRADED (missing: {', '.join(missing)})" if missing else "all present")
        + f" on engine {caps.get('engine')}"
        + (f" - {len(blocking)} BLOCKING" if blocking
           else " - remaining findings ADVISORY, for the G-images reviewer to re-derive"))
    if blocking:
        # EVERY REFUSAL NAMES ITS REMEDY (house rule). Both of these are hard facts, not
        # judgement, so the way past them is an explicit recorded sign-off - never silence.
        for f in blocking:
            if f.get("kind") == "capability":
                print(f"  [FAIL] the media layer is DEGRADED, so a thin gallery or a missing "
                      f"site plan on this run cannot be distinguished from a source that holds "
                      f"nothing. Install the missing dependency and re-run, or - if this "
                      f"environment genuinely cannot render - record the decision: "
                      f"`gate_runner.py ack --work \"{work}\" "
                      f"--add media_capability_ok={f.get('what')}`")
            else:
                print(f"  [FAIL] `{f.get('deck')}` was interpreted BLIND, so its plan_page / "
                      f"image_pages answers prove nothing. Re-run so the page renders are "
                      f"prepared and re-dispatch that deck, or record the decision: "
                      f"`gate_runner.py ack --work \"{work}\" "
                      f"--add blind_interpretation_ok={f.get('deck')}`")
        print("STATUS: BLOCKED")
        return 1
    print("STATUS: ALL-PASS")
    return 0


# fields merge/enrich ASSIGN, so their absence from a reader's record means nothing
_PIPELINE_ASSIGNED = frozenset({
    "id", "photo", "plan", "gallery", "preBaked", "regionCode", "coordsApprox",
    "officeAreaVal", "officeRentVal", "expansionParkVal",
})


def _absent(v, field=None) -> bool:
    """Absence as this module's gates read it: the shared unknown family, nothing private.

    Used by value-format (skip an unknown before judging its format), capture-symmetry (a
    field is CAPTURED only when its value is not an unknown) and the card-title gate (an
    unknown park or unit is no designator). Pass `field` where you have it: `country` is a
    code-valued field, and a bare assigned alpha-2 code is a country there, not an unknown.
    A stated "none" is NOT absent: it is a negative the source printed."""
    return _unknown(v, field)


def _norm_title(s) -> str:
    """A rendered card title AS A READER COMPARES IT: every run of whitespace collapsed to
    one space, trimmed, case-folded.

    A reader cannot tell one space from two, a plain space from a non-breaking space (for a
    str pattern `\\s` matches both), or 'Unit 4' from 'UNIT 4'. Comparing the raw strings
    would let all three of those pass as two distinct titles, which is the very confusion
    this normalisation exists to deny."""
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip().casefold()


def _title_words(s) -> str:
    """The chrome's `tsWords` reducer, character for character: lower-cased, every run of
    NON-alphanumeric characters collapsed to one space, trimmed.

    Stronger than `_norm_title` on purpose, and used for a different question. This one
    decides whether a park string ALREADY CARRIES the unit designator, so it has to see
    'Kestrel Reach, Unit 3' and 'Unit 3' as the same words - punctuation and all - while
    `_norm_title` decides whether two RENDERED titles look the same to a reader, who can see
    a comma perfectly well."""
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _card_title(p: dict) -> str:
    """The heading the chrome draws on a property's card: the park name, plus the unit
    designator when the record states one, and NOT repeated when the park string already
    carries it.

    THIS IS A HAND-MAINTAINED COPY OF `titleStr` IN `assets/dashboard_template.html`, and the
    duplication is deliberate. That function is the single composition site for the card
    heading, the compare-tray chip, the map popup, the map-list row, the modal title and the
    comparison-table column header; this is a second, independent Python statement of the
    same five lines. Importing the renderer instead is not available, and would not be the
    better choice if it were:

      * THERE IS NOTHING TO IMPORT. `titleStr` is a JS function inside the HTML asset and it
        runs in the reader's browser. `build_dashboard.render` only injects the JSON data
        blocks into that asset, so the only way to read a title back out of "the renderer" is
        to build the whole multi-MB document and re-parse it - or to execute JS from a gate.
      * THIS GATE RUNS BEFORE THE BUILD. `coverage` is a pre-build gate and has to block while
        `canonical.json` is still the editable artefact. There is no HTML in existence yet, so
        a check that needed one could only ever report the collision after it had been
        rendered, past the freeze, in the direction where nothing can be edited cheaply.
      * THE DRIFT RISK IS PINNED WHERE IT CAN BE SEEN, which is the honest answer to the cost
        of duplicating. `evals/card_title_collision_test.py` asserts this function's output
        rule by rule AND asserts that `titleStr`'s own rule markers are still in the template,
        so a chrome that changes the composition without changing this copy is a RED eval
        rather than a silent miss. The reverse direction is already guarded: `validate-html`
        re-runs `render(canonical)` and demands byte identity, and VERSION carries the chrome
        SHA.

    THE RULE, MIRRORED EXACTLY:
      * a sentinel park or unit is ABSENCE, so it contributes nothing and adds no separator;
      * no unit -> the park name; no park -> the unit;
      * the designator is dropped when the park's alphanumeric WORDS already contain the
        unit's words as a whole-token run ANYWHERE, not merely at the end. Whole-token, so a
        unit '3' is not found inside a park 'Kestrel Reach 300' - a plain substring test
        would have suppressed a real designator there;
      * otherwise the two are joined by ONE space.

    THE ONE KNOWN DIVERGENCE, AND ITS DIRECTION. `_absent` (this module's sentinel vocabulary,
    shared with the fill checks) also treats 'n/a' as absence; the chrome's `isAbsent` does
    not. Kept rather than forked into a fifth private sentinel list, because the divergence is
    one-directional: treating a value as ABSENT can only SUPPRESS a designator, which can only
    make two titles compare EQUAL, which can only make this gate MORE likely to block. A
    mismatch therefore costs a false refusal that names both ids and the title - diagnosable
    in one line - never a missed collision that ships.

    CORRECT BEFORE AND AFTER `unit` LANDS. A record with no `unit` key at all is titled by its
    park alone, which is what a record whose source names no unit does for ever."""
    name = "" if _absent(p.get("park"), "park") else str(p.get("park")).strip()
    unit = "" if _absent(p.get("unit"), "unit") else str(p.get("unit")).strip()
    if not unit:
        return name
    if not name:
        return unit
    n, u = _title_words(name), _title_words(unit)
    if not u or n == u or f" {u} " in f" {n} ":
        return name
    return f"{name} {unit}"


def cmd_coverage(args) -> int:
    data = C.load_canonical(Path(args.canonical))
    props = data.get("properties", [])
    threshold = args.fill_threshold
    issues = []

    # lat/lng are filled by the OPT-IN --geocode enrichment; when the broker
    # declined it - OR it ran but produced NOTHING (dead sandbox network, cache
    # unseeded: a real Cowork state) - missing coordinates are a configuration/
    # environment outcome, not thin data. Demand them only when geocoding actually
    # delivered at least one coordinate.
    geocoded = bool(((data.get("meta", {}) or {}).get("enrichment", {}) or {}).get("geocode")) \
        and any(isinstance(p.get("lat"), (int, float)) for p in props)
    wh_core = WAREHOUSE_CORE if geocoded else [f for f in WAREHOUSE_CORE if f not in ("lat", "lng")]
    land_core = LAND_CORE if geocoded else [f for f in LAND_CORE if f not in ("lat", "lng")]

    # duplicate = same park+city+developer AND same warehouse area (distinct
    # buildings can legitimately share a park name, e.g. two phases)
    seen = {}
    for p in props:
        key = (str(p.get("park", "")).lower(), str(p.get("city", "")).lower(),
               str(p.get("developer", "")).lower(), p.get("warehouseArea"))
        if key in seen:
            issues.append(f"duplicate property: {key[:3]} (ids {seen[key]} & {p.get('id')})")
        seen[key] = p.get("id")

    # THE OVER-MERGE COUNTERPART to the dedupe check above, and the more dangerous
    # direction of the same error. (A14b)
    #
    # The check above catches an over-SPLIT: one building shipped as two cards. Nothing
    # caught the opposite - two different buildings fused into one card - which this skill's
    # own reference documentation until recently called structurally impossible. It is not:
    # the matcher's auto tier fuses a pair that agrees closely on size and names no
    # contradicting party, and only GREY pairs are ever enumerated for human adjudication, so
    # a fused pair is offered to nobody, appealable by nobody and visible to nothing.
    #
    # ONE OPEN PATH still makes this a live net rather than only a regression guard, and one
    # is what is left of the three this comment used to claim. A12 put the code veto in the
    # matcher and A12b moved it to a SINGLE guard at the TOP of `_cross_source_auto`, ahead of
    # every branch: the one-park-missing branch and the fuzzy-key tail, which used to claim a
    # pair before `pair_class` ever reached the forbidden tier, are therefore both CLOSED -
    # there is no branch left to bypass the veto in, because the function has already
    # returned. WHAT REMAINS IS THE SAME-SOURCE PATH, and it is structural rather than an
    # omission: `pair_class` answers its same-source branch with `_same_source_verdict` and
    # RETURNS before either cross-source tier runs, and that verdict reads only the match key
    # (city|developer|park) and the area. So two rows of ONE file with an identical key, an
    # identical area and two DIFFERENT stated codes still merge as a restatement today, and
    # `evals/overmerge_guard_test.py` pins it as the CURRENT FACT. A fusion across two stated
    # codes therefore still ships, and a gate asking the finished dataset costs nothing where
    # the matcher was right (it cannot fire unless the codes actually disagree) while catching
    # the one path a match-time fix has not been able to reach.
    #
    # An over-split costs a duplicate card. An over-merge costs a BUILDING: one option
    # vanishes from the client's longlist entirely and the survivor is a blend of two
    # properties' figures, every one of them individually sourced and traceable, which is why
    # no provenance gate can see it either.
    #
    # WHY THE POSTAL CODE. It is the one identity signal the matcher's recall pre-filter reads
    # and no merge tier checks, and two DIFFERENT stated codes is a fact rather than a
    # judgement: no threshold, no similarity score, nothing to tune. The codes arrive from
    # merge already normalised, so plain inequality is the whole comparison - no country
    # specific parsing, and deliberately NO prefix or district logic, because "same first
    # half" is a claim about one country's postal geometry that this pipeline is not entitled
    # to make and would silently mean the opposite in the next country.
    #
    # ONLY RECORDS THAT BOTH STATE A CODE are compared. An absent code is no signal, never a
    # disagreement, so a corpus that quotes codes patchily is unaffected and a country whose
    # records carry none at all can never reach the block at all - the loop finds fewer than
    # two stated codes on every property and does nothing. Absent `meta.clusterSources` (an
    # older work directory, or a merge that did not record it) is a silent no-op for the same
    # reason: this gate says what it can prove, and it can prove nothing without the sources.
    #
    # BLOCKING, matching the over-split counterpart and every other finding in this function.
    # Two stated codes cannot both be one building; the harm is a lost option in a client
    # deliverable; and the remedy is nameable, which is what the house rule requires of a
    # refusal - a `strike_from_source` repair unfuses the record that does not belong.
    # ONE READER DECIDES THIS FACT FOR BOTH SIDES. The equality key below is
    # `match._stated_postcode` itself, not a second implementation of it, and that sharing is
    # the guarantee: this gate is the BACKSTOP for `match._postcode_conflict`'s veto - the
    # veto refuses to fuse two records that state conflicting codes, and this asks the
    # finished dataset whether a fusion got through anyway. A backstop that normalises the
    # code differently from the guard it backs is not a backstop. It can fail in BOTH
    # directions, and BOTH were measured on this very block before the reader was shared.
    # Over the 35 drift probes in `evals/report_honesty_struck_test.py` section 6b, 15
    # disagreed. 14 were the FALSE-REFUSAL direction: 'QX41 7ZP' against 'QX417ZP' clears the
    # veto as ONE code (the veto removes all whitespace) and was reported here as TWO, a
    # refusal for a fusion the pipeline had deliberately allowed, whose named remedy would
    # have unfused a correct merge. Differing case, a doubled space, a non-breaking space, an
    # integral float against an int and every unknown-value sentinel all did the same. 1 was
    # the BLIND direction, which is the one that ships a lost building: a numeric 0, which
    # `str(x or "").strip()` read as absence while the veto reads the code '0'. After the
    # share: 0 of 35. That eval drives BOTH sides from ONE list of pairs and asserts the same
    # verdict from each, so a normaliser that drifts again is a RED eval rather than a
    # contradictory pair of guards.
    #
    # THE PURITY INTENT SURVIVES, which is why this is a borrow and not a coupling. The gate
    # still reads NOTHING but `canonical.json`: what it imports is a pure string reader - no
    # state, no IO, no knowledge of any record but the one dict handed to it - and none of the
    # matcher's tiering, thresholds or clustering. `enrich._locality_code` already delegates
    # to the same reader for the same stated reason: a private copy is the copy that drifts,
    # and `normalize.looks_unknown` carries the standing warning about exactly that.
    #
    # LAZY, INSIDE THE ONE CHECK THAT NEEDS IT. `gate_runner` is imported by `final_gate`,
    # `run` and `deliver`, and `import match` costs a measured ~86 ms because it pulls
    # `rapidfuzz` (or the shim); at module scope every importer would pay that for a reader
    # only this block uses. NO CYCLE: `match` imports re, sys, unicodedata, functools,
    # pathlib, `normalize` and rapidfuzz, and nothing that reaches back here.
    #
    # THE FIELD LIST IS SHARED TOO, because the whole ENTRY is handed to the reader rather
    # than one field picked out of it. `_POSTCODE_FIELDS` is deliberately open (a broker's own
    # header names the column), so a name added there is read by the veto and by this gate in
    # the same commit instead of one of them going half-blind.
    #
    # THE PRODUCER DELEGATES TOO, so the chain is closed END TO END and this gate agrees with
    # the veto on every input, not merely on most of them. `merge._stated_postcode` - which is
    # what WRITES these values - was a third private copy that trimmed and upper-cased without
    # removing internal whitespace, read only `postcode`, and stringified with `str()`. Over a
    # 35-pair probe list the two sides disagreed on 9 pairs: 5 closed when this gate borrowed
    # the reader below, and the last 4 were that copy stringifying a float or a bool
    # (str(48215.0) == '48215.0' where the matcher reads 48215; str(True) == 'TRUE' where the
    # matcher reads ABSENCE). Every one of the four made this gate BLOCK a fusion the veto had
    # deliberately allowed, while naming `strike_from_source` - a remedy that would have
    # unfused a correct merge. It could not be repaired here: a rule collapsing a trailing
    # '.0' would itself diverge from the veto on the genuine STRING '48215.0', reintroducing
    # drift in the dimension being fixed. So merge now calls the same reader.
    # `report_honesty_struck_test.py` 6b asserts the AGREEMENT pair by pair, and goes red if
    # any of the three copies is ever reintroduced.
    import match as _M

    cs = (data.get("meta", {}) or {}).get("clusterSources") or {}
    for p in props:
        recs = cs.get(str(p.get("id"))) if isinstance(cs, dict) else None
        # Every shape is checked rather than trusted, at both levels. A gate that raises
        # inside a pre-build check does not fail the run honestly, it aborts it with a
        # traceback and no scorecard fragment - so a malformed key must degrade to "nothing
        # provable here", which is the same answer as a key that is simply absent. The reader
        # is defensive in the same direction and for the same reason: a value that is not a
        # string, a number, or is a sentinel reads as ABSENCE, and absence is never a
        # disagreement, so every malformed entry costs silence rather than a block.
        if not isinstance(recs, list):
            recs = []
        by_code: dict = {}
        for r in recs:
            if not isinstance(r, dict):
                continue
            code = _M._stated_postcode(r)
            if code:
                # THE VERDICT IS THE KEY, THE MESSAGE IS THE SOURCE'S OWN TEXT. Quoting the
                # equality key would print 'QX417ZP' where the file printed 'QX41 7ZP', and a
                # reader sent to that file to fix a code has to find the string it will
                # actually see there. Asking the reader per field is how the right field is
                # identified without a second copy of its skip rules; a drift here can only
                # make the message read oddly, never change whether the gate blocks.
                shown = next((str(r[f]).strip() for f in _M._POSTCODE_FIELDS
                              if _M._stated_postcode({f: r.get(f)}) == code), code)
                by_code.setdefault(code, (str(r.get("file") or "?"), shown))
        if len(by_code) > 1:
            says = " vs ".join(f"{f} states '{s}'" for f, s in by_code.values())
            # THE REMEDY DEPENDS ON WHETHER ONE FILE OR TWO STATED THE CODES, and offering the
            # wrong one is worse than offering none: `strike_from_source` withdraws EVERYTHING
            # a named file gave this property, so on a same-source fusion (two rows of one
            # tracker, the ONE residual path above) it would empty the card rather than split
            # it.
            # Nothing in this pipeline can split one merged property into two after the fact,
            # so the honest instruction there is to fix the record the codes disagree about
            # and re-run - never a verb that would quietly do something else.
            fix = ("Confirm which record is this property and unfuse the others with a "
                   "work/repairs.json `strike_from_source` entry naming each file, then "
                   "re-run; if they really are one address, correct the wrong code at source "
                   "(work/overrides.json)."
                   if len({f for f, _ in by_code.values()}) > 1 else
                   "Both codes come from ONE file, so `strike_from_source` cannot separate "
                   "them - it would withdraw everything that file gave this property. Read "
                   "the file's own rows: if one code is a keying error, correct it in "
                   "work/overrides.json and re-run; if the rows really are two buildings, "
                   "they have to reach the run as two records for the matcher to keep them "
                   "apart.")
            issues.append(
                f"over-merge: property id={p.get('id')} was built from records stating "
                f"{len(by_code)} DIFFERENT postal codes - {says}. Records at different codes "
                f"are records at different addresses, so this one card is carrying more than "
                f"one building and the rest are missing from the longlist entirely. {fix}")

    # TWO SHIPPED CARDS THAT RENDER THE SAME TITLE (A14c). The third member of this family,
    # beside the over-SPLIT dedupe and the over-MERGE code check above: two genuinely
    # DIFFERENT units at one location, both shipped, both drawing an identical card heading.
    #
    # THIS SHAPE HAS SHIPPED, which is why it is a gate and not a note. A delivered run put
    # two cards a reader could not tell apart in front of a broker, and the COMPARISON VIEW -
    # the one place the reader is explicitly asked to choose BETWEEN two options - stood the
    # two identical headings side by side, which is where an indistinguishable pair does the
    # most damage. Neither existing check sees it. The dedupe key demands park, city,
    # developer AND warehouse area all equal, and two different units differ on the area by
    # construction; the code check needs `meta.clusterSources` to state two DISAGREEING
    # postal codes, and two units of one park normally state the same code or none at all.
    #
    # THE DATA FIX ALONE IS NOT THE PROTECTION EITHER, AND NEITHER IS THE `unit` FIELD THAT
    # MAKES THE TWO TITLES DIFFER. A canonical field is only as present as the run that filled
    # it: a designator this month's tracker states and next month's omits collapses both cards
    # back onto one heading, silently, with every field still individually sourced and
    # traceable. So the invariant is asserted about the DELIVERABLE - no two cards share a
    # heading - rather than about any one field being populated.
    #
    # A DATA FIX ALONE DOES NOT PROTECT AGAINST IT. The title is composed out of whatever
    # fields the record happens to carry, so correcting this run's records fixes this run and
    # nothing else: the next run can lose a DIFFERENT field and arrive at the same collision
    # from another direction (a `unit` this month's tracker states and next month's omits, a
    # park string that arrives without its phase suffix). The durable invariant is about the
    # DELIVERABLE - no two cards share a heading - so it belongs where the finished dataset
    # is asked, next to its two siblings.
    #
    # BLOCKING, for the same three reasons as those siblings: two composed strings are equal
    # or they are not (a fact, not a judgement, with no threshold to tune), the harm lands in
    # a client deliverable, and the remedy is nameable - which is what the house rule requires
    # of a refusal.
    #
    # INERT WHEN ONLY ONE PROPERTY SHIPS, by construction: a collision needs a second title to
    # collide with, so a single-property run cannot reach the report at all. It is equally
    # inert on every corpus whose titles differ, which is every correct run.
    by_title: dict = {}
    for p in props:
        title = _card_title(p)
        # AN EMPTY TITLE IS NOT SKIPPED, and that is a correction of the obvious first
        # instinct. `titleStr` returns falsy when a record states neither a park nor a unit,
        # and the card's own `<h3>` and the comparison table's column header interpolate it
        # with NO fallback - so two such records ship two BLANK headings, which is the
        # indistinguishable pair in its purest form rather than an absence of one. It is
        # keyed like any other title (the empty string cannot collide with a real one, since
        # a stated park always normalises to something) and the message says plainly that the
        # heading is blank, so the reader is not sent looking for a title to compare.
        key = _norm_title(title)
        # MEMBERSHIP, not a truthiness test on the stored id: a property whose `id` is None
        # or 0 must still anchor the next collision, and `by_title.get(key)` would read as
        # "not seen yet" for both of them and quietly re-key instead of reporting.
        if key not in by_title:
            by_title[key] = p.get("id")
            continue
        first = by_title[key]
        shown = (f"'{title}'" if title else
                 "EMPTY - neither record states a park name or a unit designator")
        issues.append(
            f"identical card title: properties id={first} and id={p.get('id')} both render "
            f"the same card heading ({shown}), so two different options are indistinguishable "
            f"on the grid and side by side in the comparison view, where the reader is being "
            f"asked to choose between them. Give each card the unit/phase designator its "
            f"source states - a `work/repairs.json` `set` on `unit`, or on `park` - and "
            f"re-run. If the two records are really ONE building quoted twice, re-titling a "
            f"card would only hide that: correct the record at source (work/overrides.json) "
            f"so the matcher fuses them instead.")

    # per-record core fill OR explicit tbd - core set chosen by record kind so a
    # land/plot listing is not failed for lacking warehouse fields it never has
    for p in props:
        land = _is_land_record(p)
        core = land_core if land else wh_core
        filled = sum(1 for f in core if _cov_filled(p.get(f), f))
        frac = filled / len(core)
        if frac < threshold:
            empties = [f for f in core if not _cov_filled(p.get(f), f)]
            kind = " (land/plot)" if land else ""
            issues.append(f"property id={p.get('id')}{kind} core fill {frac:.0%} < {threshold:.0%}; thin: {empties}")

    if issues:
        for i in issues:
            _bad(i)
        print(f"STATUS: BLOCKED ({len(issues)} coverage issues)")
        return 1
    _ok(f"coverage clean ({len(props)} properties, no dups, core fill >= {threshold:.0%})")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
def cmd_validate_html(args) -> int:
    data = C.load_canonical(Path(args.canonical))
    expected, _ = build_dashboard.render(data)
    actual = Path(args.html).read_text(encoding="utf-8-sig")
    issues = []

    if actual != expected:
        # locate first divergence for a useful message
        n = min(len(actual), len(expected))
        i = next((k for k in range(n) if actual[k] != expected[k]), n)
        ctx_a = actual[max(0, i - 40):i + 40]
        ctx_e = expected[max(0, i - 40):i + 40]
        issues.append(f"chrome drift: output != render(canonical) at offset {i}\n"
                      f"   expected: ...{ctx_e!r}...\n   actual:   ...{ctx_a!r}...")

        # three blocks present and JSON round-trippable - only worth checking when the bytes
        # DIVERGE (as a clearer diagnostic). On a byte-identical pass, render() produced these
        # blocks from the loaded canonical, so they are provably present + valid and this
        # multi-MB re-parse is redundant (S6-8). The byte-equality above, and the </script>-count
        # and chrome-SHA guards below, stay UNCONDITIONAL - the byte-identity floor is untouched.
        for name in ("PROPS", "POIS", "REGIONS"):
            m = re.search(rf"const {name} = (.*?);(?:\n|$)", actual, re.DOTALL)
            if not m:
                issues.append(f"data block const {name} not found")
                continue
            try:
                json.loads(m.group(1))
            except Exception as e:
                issues.append(f"const {name} not valid JSON: {e}")

    # injection safety: data is escaped at build, so the delivered file must carry
    # exactly the template's <script> tags - an extra one means a </script> breakout
    if actual.count("</script>") != C.load_template().count("</script>"):
        issues.append("script-tag count != template (possible </script> breakout in source-derived data)")

    # template chrome sha vs VERSION
    import hashlib
    tmpl_sha = hashlib.sha256(C.load_template().encode("utf-8")).hexdigest()
    ver = C.load_version().get("chrome_sha256")
    if not ver:
        issues.append("VERSION carries no chrome_sha256 - the template-edit guard is DISABLED; "
                      "record the chrome hash (make_integrity / version bump) - S6-47")
    elif tmpl_sha != ver:
        issues.append(f"template SHA {tmpl_sha[:12]} != VERSION {ver[:12]} (template edited without re-versioning)")

    if issues:
        for i in issues:
            _bad(i)
        print("STATUS: BLOCKED")
        return 1
    _ok("HTML == render(canonical) byte-for-byte; 3 blocks round-trip; chrome sha matches")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
def cmd_reconcile(args) -> int:
    data = C.load_canonical(Path(args.canonical))
    html = Path(args.html).read_text(encoding="utf-8-sig")
    issues = []

    m = re.search(r"const PROPS = (.*?);(?:\n|$)", html, re.DOTALL)
    html_props = json.loads(m.group(1)) if m else []   # parse const PROPS ONCE (reused below)
    html_ids = {p["id"] for p in html_props}
    canon_ids = {p["id"] for p in data["properties"]}
    if html_ids != canon_ids:
        issues.append(f"id mismatch HTML vs canonical: only-html={html_ids - canon_ids}, "
                      f"only-canon={canon_ids - html_ids}")

    # KPI: properties count appears in the rendered hero. kpi_properties is a pure
    # function of the property list (build_dashboard.compute_kpis -> str(len(props)));
    # compute it directly instead of a SECOND full render() of the (multi-MB) canonical
    # here - validate-html already re-runs the real render(canonical) as the byte-identity
    # floor, so this gate need not repeat it (#24/#34). compute_kpis is the same function
    # render() calls for this token, so the value is byte-identical.
    props = [C.fill_render_sentinels(dict(p)) for p in data["properties"]]
    kpi_props = build_dashboard.compute_kpis(
        props, data.get("regions", {}), (data.get("meta") or {}).get("units"))["kpi_properties"]
    if f'<div class="kpi-value">{kpi_props}</div>' not in html:
        issues.append(f"hero KPI properties ({kpi_props}) not found in HTML")

    # v22 Phase 1 render-boundary: no property may carry a NON-canonical object/array (a leaked
    # provenance/meta map), and no scalar value may be a pipeline locator string.
    canon = C.canonical_property_fields()
    for p in html_props:   # same parsed PROPS list (no second re.search / json.loads)
        for k, v in p.items():
            if isinstance(v, (dict, list)) and k not in canon:
                issues.append(f"property {p.get('id')}: non-canonical object key '{k}' reached PROPS "
                              f"(provenance/meta must be quarantined at merge)")
            elif C.looks_like_locator(v):
                issues.append(f"property {p.get('id')}: field '{k}' shows a provenance-locator "
                              f"string ('{str(v)[:40]}') instead of a value")

    if issues:
        for i in issues:
            _bad(i)
        print("STATUS: BLOCKED")
        return 1
    _ok(f"reconcile clean ({len(canon_ids)} ids match; KPI strip consistent)")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
# G-i18n: the DETERMINISTIC FLOOR of the localisation render-quality gate. The blind
# LLM rubric (reference/gates.md G-i18n) is the live counterpart and runs in Cowork;
# this floor catches the structural failure modes that don't need a reader: a missing
# /extra chrome key, an unfilled {{token}}, a malformed LOCALE, a translation that
# silently collapsed back to English, and a destroyed {area}/{unit} placeholder.

# Invariants that legitimately stay English/verbatim in EVERY language, so a key whose
# EN value is ONE of these (or is empty) is excluded from the silent-fallback "must
# differ from EN" share - translating them would be wrong, not missing.
_I18N_INVARIANT_VALUES = {"%", "tbc", "reit", "pps", "% eu27", "min", ""}


def _parse_const_obj(html: str, name: str):
    """Extract `const <name> = {...};` from built HTML and json.loads it (the build
    emits compact, sorted, <,>-escaped JSON, so it round-trips). None if absent/bad."""
    m = re.search(rf"const {name} = (\{{.*?\}});\n", html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _bcp47_well_formed(tag: str) -> bool:
    """A pragmatic BCP-47 check: language[-script][-region][-variant], e.g. en-GB, de-DE,
    nb-NO, ca-ES. We require at least a 2-3 letter primary subtag; further subtags are
    2-3 letters/digits or a 4-letter script. Good enough to catch a malformed/empty tag
    without pulling a full langtag library into the offline floor."""
    if not isinstance(tag, str) or not tag.strip():
        return False
    parts = tag.strip().split("-")
    if not re.fullmatch(r"[A-Za-z]{2,3}", parts[0]):
        return False
    for p in parts[1:]:
        if not re.fullmatch(r"[A-Za-z]{2,4}|\d{3}|[A-Za-z0-9]{2,8}", p):
            return False
    return True


def cmd_i18n(args) -> int:
    """G-i18n deterministic floor: confirm the rendered chrome is complete, well-formed
    and actually localised for the resolved language. Reads the built HTML + canonical."""
    import i18n as I18N
    issues = []
    html = Path(args.html).read_text(encoding="utf-8-sig")
    data = C.load_canonical(Path(args.canonical))
    meta = data.get("meta", {}) or {}
    language = meta.get("language") or "en"
    code = I18N.normalize_lang(language)
    overrides = meta.get("ui_overrides") if isinstance(meta.get("ui_overrides"), dict) else None

    # 1. const UI parses and has EXACTLY the EN key set - no missing, no extra.
    ui = _parse_const_obj(html, "UI")
    if ui is None:
        issues.append("const UI = {...} block missing or not valid JSON")
    else:
        en_keys = set(I18N.EN)
        ui_keys = set(ui)
        missing = sorted(en_keys - ui_keys)
        extra = sorted(ui_keys - en_keys)
        if missing:
            issues.append(f"const UI is missing {len(missing)} EN key(s): {missing[:8]}")
        if extra:
            issues.append(f"const UI has {len(extra)} key(s) not in EN: {extra[:8]}")

    # 2. No UI value contains an unfilled {{token}} (reuse find_leftover_tokens).
    if ui is not None:
        tok_offenders = sorted(k for k, v in ui.items()
                               if isinstance(v, str) and C.find_leftover_tokens(v))
        if tok_offenders:
            issues.append(f"const UI value(s) carry an unfilled {{{{token}}}}: {tok_offenders[:8]}")

    # 3. const LOCALE is a well-formed BCP-47 tag for the resolved language.
    ml = re.search(r'const LOCALE = "([^"]*)";', html)
    locale = ml.group(1) if ml else None
    if locale is None:
        issues.append("const LOCALE = \"...\"; not found in the built HTML")
    elif not _bcp47_well_formed(locale):
        issues.append(f"const LOCALE {locale!r} is not a well-formed BCP-47 tag")
    else:
        # the locale's primary subtag should match the resolved language code (e.g.
        # 'de-DE' for de). An explicit meta.locale (de-AT) still shares the primary subtag.
        prim = locale.split("-")[0].lower()
        # an EXPLICIT meta.locale is a deliberate regional override whose primary subtag may
        # legitimately differ from the resolved language code (e.g. a fallback BCP-47) - S6-48
        explicit_locale = bool(str(meta.get("locale") or "").strip())
        if prim != code and not explicit_locale:
            issues.append(f"const LOCALE {locale!r} primary subtag {prim!r} != resolved "
                          f"language code {code!r}")

    # 4. Silent-fallback catch: if the resolved language is non-EN AND was EXPECTED to be
    # localised (a bundled language, or meta.ui_overrides present), the UI must DIFFER
    # from EN across a threshold share of the non-invariant keys - a translation that
    # silently collapsed to English is caught here. For an UNSUPPORTED language (correctly
    # rendered in EN) and for EN itself this check is skipped (EN is the right answer).
    expected_localised = code != "en" and (I18N.is_bundled(code) or overrides is not None)
    if ui is not None and expected_localised:
        comparable = [k for k, v in I18N.EN.items()
                      if isinstance(v, str)
                      and str(v).strip().lower() not in _I18N_INVARIANT_VALUES]
        differing = [k for k in comparable if ui.get(k) != I18N.EN.get(k)]
        share = (len(differing) / len(comparable)) if comparable else 0.0
        if share < 0.40:
            issues.append(f"const UI differs from EN in only {share:.0%} of the "
                          f"{len(comparable)} non-invariant keys (< 40%): the '{language}' "
                          f"translation looks like it silently fell back to English")

    # 5. The {area}/{unit} placeholders survive into the resolved UI for the format keys
    # (compute_kpis .format()s them; a translation that dropped them would crash that).
    if ui is not None:
        if "{area}" not in str(ui.get("kpi_wh_area_sub_fmt", "")):
            issues.append("kpi_wh_area_sub_fmt lost its {area} placeholder in the resolved UI")
        if "{unit}" not in str(ui.get("kpi_rent_sub_fmt", "")):
            issues.append("kpi_rent_sub_fmt lost its {unit} placeholder in the resolved UI")
        # v45: the advisory note follows the placeholder. hero_lede_fmt's {count} went with
        # the lede paragraph; hero_title_html's {client} replaced it as the one placeholder a
        # pack can lose without crashing anything. It stays ADVISORY for the reason the old
        # clause was: the two clauses above guard a CRASH (compute_kpis .format()s them),
        # while losing {client} only costs the headline the occupier's name. Blocking would
        # be an UNCLEARABLE exit 7 for a bundled language - cmd_i18n runs POST-build and a
        # bundled pack is a shipped, integrity-tracked asset with no runtime override, so the
        # only "remedy" would be hand-editing it, which SKILL.md forbids. evals/i18n_test.py
        # is the dev-time tripwire that catches a pack losing it.
        if "{client}" not in str(ui.get("hero_title_html", "")):
            print("  [note] hero_title_html lost its {client} placeholder in the resolved UI - "
                  "the headline ships the pack's own wording without the client name; "
                  "fix the pack's hero_title_html when convenient (advisory, not blocking)")

    if issues:
        for i in issues:
            _bad(i)
        print(f"STATUS: BLOCKED ({len(issues)} i18n issue(s); language={language!r}, code={code!r})")
        return 1
    _kind = ("bundled" if I18N.is_bundled(code) and code != "en"
             else "fallback" if overrides is not None
             else "English" if code == "en" else "English (unsupported -> EN)")
    _ok(f"i18n floor clean: const UI complete ({len(ui or {})} keys), LOCALE {locale!r} "
        f"well-formed, no unfilled token, placeholders intact ({_kind} chrome for {language!r})")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
def cmd_trace_coverage(args) -> int:
    """Every non-sentinel, source-able property field must have a ledger row whose
    source_type is not 'gap'. Catches a fabricated value injected with no source."""
    import csv
    data = C.load_canonical(Path(args.canonical))
    traced = set()
    with open(args.ledger, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if (row.get("source_type") or "") != "gap":
                traced.add((str(row.get("property_id")), row.get("field")))

    # fields a real source must back; excludes structural/derived/enriched keys
    # identity fields (developer/city/park/country) must trace to a source too - a
    # fabricated identity is as damaging as a fabricated spec (audit S4-14); a
    # gap-documented unknown (e.g. country '??') is an unknown form, skipped by `_unknown`
    # (the shared family; `country` gets the code reading so a real two-letter country that
    # doubles as a market abbreviation is still traced). A stated "none" is NOT skipped: it
    # is data the source printed, and an unsourced one is exactly the fabrication this gate
    # exists to catch. (SEAM-13)
    check = (set(C.STRING_FIELDS)
             | {"warehouseArea", "warehouseRentVal", "plotArea",
                "developer", "city", "park", "country"})
    issues = []
    for p in data.get("properties", []):
        pid = str(p.get("id"))
        for f in check:
            if f in p and not _unknown(p.get(f), f) and (pid, f) not in traced:
                issues.append(f"property id={pid}: field '{f}'={p.get(f)!r} has NO ledger row "
                              f"(untraceable - possible fabrication)")
    if issues:
        for i in issues[:40]:
            _bad(i)
        print(f"STATUS: BLOCKED ({len(issues)} untraceable fields)")
        return 1
    _ok(f"every populated field traces to a ledger row ({len(data.get('properties', []))} properties)")
    print("STATUS: ALL-PASS")
    return 0


def cmd_images(args) -> int:
    import images as IMG
    data = C.load_canonical(Path(args.canonical))
    ph = IMG.placeholder()
    issues, n_real, n_placeholder = [], 0, 0
    # PLACEHOLDER AUDIT: a placeholder whose source page held candidate images is
    # a BLOCKING state until a reviewer has SEEN the discard pile and signed off
    # (placeholder_audit_ack.json, written by the orchestrator from the G-images
    # verdict). "No usable image" must be a reviewed conclusion, never a silent
    # default - a real run shipped a placeholder while a usable site plan sat in
    # the discard pile and nobody was ever shown it.
    audit = (data.get("meta", {}) or {}).get("placeholderAudit", {}) or {}
    ack_file = Path(args.canonical).resolve().parent / "placeholder_audit_ack.json"
    ack: dict = {}
    if ack_file.exists():
        try:
            ack = json.loads(ack_file.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            pass
    acked = {str(x) for x in ack.get("confirmed", [])}
    for p in data.get("properties", []):
        photo = p.get("photo", "")
        pid = str(p.get("id"))
        if not isinstance(photo, str) or not photo.startswith("data:image/"):
            issues.append(f"property id={p.get('id')}: photo is not a valid data URI")
        elif photo == ph:
            n_placeholder += 1
            ent = audit.get(pid)
            if ent and ent.get("candidates", 0) > 0 and pid not in acked:
                issues.append(
                    f"property id={pid}: hero is a PLACEHOLDER but {ent['candidates']} "
                    f"image candidate(s) from {ent.get('source')} {ent.get('locator')} were "
                    f"discarded - have the G-images reviewer inspect render/placeholder_audit/ "
                    f"(rescue a usable photo/plan, or sign off), then record the verdict in "
                    f"{ack_file.name} {{\"confirmed\": [\"{pid}\", ...]}}")
            elif ent and pid in acked:
                print(f"  [note] property id={pid}: placeholder signed off by review "
                      f"({ent.get('candidates', 0)} discarded candidate(s) inspected)")
        else:
            n_real += 1
        # GALLERY: each carousel entry must be a valid data URI and the hero must be
        # gallery[0] (the carousel relies on it). An ABSENT gallery is fine (the render
        # falls back to [photo]); a PRESENT one must be well-formed.
        gal = p.get("gallery")
        if gal is not None:
            if not isinstance(gal, list) or not gal:
                issues.append(f"property id={pid}: gallery present but not a non-empty list")
            elif any(not (isinstance(u, str) and u.startswith("data:image/")) for u in gal):
                issues.append(f"property id={pid}: gallery has a non-data-URI entry")
            elif isinstance(photo, str) and photo.startswith("data:image/") and gal[0] != photo:
                issues.append(f"property id={pid}: gallery[0] != hero photo (carousel/hero mismatch)")
    # DUPLICATE-HERO check: properties sharing ONE identical hero image is a near-certain
    # harvest failure (a real run shipped cards with the same picture and no gate noticed -
    # "all photos are valid data URIs" was true). The floor is 2 - even a single duplicated
    # PAIR is wrong (the #22/#23 case slipped a >=3 rule); a legitimately shared brochure
    # cover (e.g. two phases of one scheme) is signed off via duplicate_photos_ok.
    import hashlib
    props = data.get("properties", [])
    groups: dict[str, list] = {}
    for p in props:
        uri = p.get("photo", "")
        if isinstance(uri, str) and uri.startswith("data:image/") and uri != ph:
            h = hashlib.sha1(uri.encode("ascii", "ignore")).hexdigest()[:12]
            groups.setdefault(h, []).append(p.get("id"))
    dup_ok = {str(x) for x in ack.get("duplicate_photos_ok", [])}
    dups = [(h, ids) for h, ids in sorted(groups.items()) if len(ids) >= 2 and h not in dup_ok]
    # F22: THE REMEDY MUST BE REACHABLE AT THE MOMENT IT BLOCKS. This gate is PRE-BUILD (exit
    # 5/6) and the G-images reviewer is dispatched at exit 14, AFTER a build this very finding
    # holds up - so "have the G-images reviewer check the contact sheet" named a reader who
    # could not yet exist and an aid the spine renders only after the scorecard. The
    # operator's real options at this moment are fix-or-acknowledge, and the one thing that
    # makes that choice informed is the contact sheet, so the gate renders it HERE, only when
    # the finding fires, and prints the path. The check itself stays pre-build on purpose: a
    # duplicated hero is a data defect the reviewers should judge FIXED, and a fix after the
    # review would need the second review round the one-round rule forbids.
    sheets: list = []
    if dups:
        try:
            import contact_sheet as _CSH
            sheets = _CSH.build_sheets(data, Path(args.canonical).resolve().parent / "render",
                                       5, 30, 480)
        except Exception:
            sheets = []
    look = (f"LOOK at {', '.join(str(s) for s in sheets)} (rendered by this gate, now)" if sheets
            else "LOOK at the page renders under work/vision/ for the properties named (the "
                 "contact sheet could not be rendered here: Pillow missing or the render failed)")
    for h, ids in dups:
        issues.append(
            f"{len(ids)} properties (ids {ids}) share ONE IDENTICAL hero photo (hash {h}) - a "
            f"near-certain harvest failure. The G-images reviewer runs AFTER the build this "
            f"blocks, so nobody else can look now: {look}, then FIX the harvest (bind each card "
            f"its own photo), or, ONLY if the shared image is genuinely each property's cover, "
            f"acknowledge it with `gate_runner.py ack --work <work> --add "
            f"duplicate_photos_ok={h}` (merges into {ack_file.name})")
    # NON-PHOTO HERO check: a card's hero MUST be the page's real photo / aerial / render -
    # never a road MAP, a flat PLAN diagram or a slide screenshot. The independent G-images
    # reviewer FLAGGED exactly this on a real run, but the gate only ADVISED, so the bad
    # heroes shipped. This makes it BLOCK until the hero is a photo OR a reviewer signs it
    # off (the plan/map still live in the gallery + the Site Plan toggle - nothing is lost).
    nonphoto_ok = {str(x) for x in ack.get("nonphoto_hero_ok", [])}
    for p in props:
        pid = str(p.get("id"))
        uri = p.get("photo", "")
        if not (isinstance(uri, str) and uri.startswith("data:image/")) or uri == ph:
            continue  # invalid / placeholder are handled by the checks above
        kind = IMG.classify_data_uri(uri)
        if kind != "photo" and pid not in nonphoto_ok:
            label = {"map": "a road-MAP screenshot", "plan": "a flat PLAN diagram",
                     "text": "a TEXT / slide screenshot",
                     "logo": "a LOGO / solid fill"}.get(kind, kind)
            issues.append(
                f"property id={pid}: hero is {label}, not a real photo/aerial/render - "
                f"rescue the property's actual photo from its deck pages (the plan/map "
                f"stays a gallery + Site Plan entry either way), or, ONLY if it is "
                f"genuinely the best image available, record "
                f"{{\"nonphoto_hero_ok\": [\"{pid}\"]}} in {ack_file.name}")
    # PLACEHOLDER-RATE check (P1-6: IMAGE-SOURCE-AWARE). A high placeholder rate is a
    # harvest FAILURE only when brochures were actually examined for those properties
    # (a placeholderAudit entry == a brochure page was tried). When the run has NO
    # brochure image sources at all - a record/tracker/email-only run, the commonest
    # low-skill input - placeholders are the EXPECTED honest outcome, NOT a failure:
    # note it and SHIP, never block a bare-spreadsheet dashboard. (The per-property
    # audit block above still bites a brochure whose candidates were discarded.)
    brochure_examined = bool(audit)
    high_rate = len(props) >= 4 and n_placeholder / len(props) >= 0.5
    if high_rate and brochure_examined and not ack.get("placeholder_rate_ok"):
        issues.append(
            f"{n_placeholder}/{len(props)} properties show the PLACEHOLDER though brochures "
            f"were examined - a harvest failure until reviewed; have the G-images reviewer "
            f"confirm the sources genuinely carry no usable imagery, then record "
            f"{{\"placeholder_rate_ok\": true}} in {ack_file.name}")
    elif high_rate:
        print(f"  [note] {n_placeholder}/{len(props)} properties show the placeholder - this "
              f"run has no brochure image source for them (record/tracker-only); shipping with "
              f"honest placeholders. Add the matching brochures to enrich the cards with photos.")
    for a in (data.get("meta", {}) or {}).get("unmatchedAssets", []):
        print(f"  [note] unmatched asset: {a}")
    props_all = data.get("properties", [])
    n_props = len(props_all)
    n_plan = sum(1 for p in props_all if str(p.get("plan", "")).startswith("data:image/"))
    pnm = (data.get("meta", {}) or {}).get("planNearMiss", [])
    print(f"  [note] site plans attached: {n_plan}/{n_props} (the modal's Site Plan toggle reads p.plan)")
    if n_props and n_plan < n_props:
        # SURFACE the gap: the images gate reviews the hero/carousel, NOT the plan slot, so a WRONG
        # plan would otherwise pass unseen - the visual-QA reviewer is the independent verify.
        # Printed as [note], not [ATTENTION]: this fires on nearly every run (most properties simply
        # have no plan in their deck) and it sits ABOVE the `if issues:` block, i.e. on a PASSING
        # gate - louder formatting than the real [FAIL] lines made a normal state read as a problem.
        # The old text also told the reviewer to "look for a MISSED plan", an unfalsifiable search
        # with no terminal state; finding candidate pages is the deterministic planNearMiss scan's
        # job (it lands them in the Gaps Report) and never needs a reviewer round.
        near = f" ({len(pnm)} candidate page(s) already surfaced in the Gaps Report)" if pnm else ""
        print(f"  [note] {n_props - n_plan} of {n_props} properties have no site plan bound{near} - "
              f"usually correct (no plan in the deck). The visual-QA reviewer VERIFIES each BOUND "
              f"plan is genuinely that property's site plan; a wrongly-bound one -> clear p.plan.")
    if issues:
        for i in issues:
            _bad(i)
        print(f"STATUS: BLOCKED ({len(issues)} bad images)")
        return 1
    _ok(f"all photos valid data URIs ({n_real} real, {n_placeholder} placeholder)")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
def cmd_freeze(args) -> int:
    """Snapshot/verify an artefact's bytes around the parallel-review window, so
    every concurrently-dispatched reviewer provably judged the SAME frozen bytes
    (and no silent edit slipped in while they ran). Call once to freeze before
    dispatching the reviewers; call with --check after collecting verdicts."""
    import hashlib
    p = Path(args.file)
    side = p.with_suffix(p.suffix + ".frozen.sha256")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    if args.check:
        if not side.exists():
            _bad(f"no freeze record for {p.name} - artefact was not frozen before review")
            print("STATUS: BLOCKED"); return 1
        if side.read_text(encoding="utf-8-sig").strip() != sha:
            _bad(f"{p.name} CHANGED since freeze - parallel reviewers may have judged "
                 f"different bytes, or an edit slipped in during review. Re-freeze and re-review.")
            print("STATUS: BLOCKED"); return 1
        _ok(f"{p.name} byte-identical to freeze ({sha[:12]}) - all reviewers saw the same artefact")
        print("STATUS: ALL-PASS"); return 0
    # TWIN FIRST, MARKER LAST. The marker is the COMMIT POINT: `--check` reads it and
    # nothing else, so anything it vouches for must already be on disk. Writing it first
    # left a window where a death - or, far likelier, a twin that simply could not be
    # written - produced a green `freeze --check` over a STALE canonical_review.json, which
    # is exactly the staleness this refresh exists to prevent. The DATA reviewers read the
    # twin, so they would have judged pre-fix data under a gate certifying the opposite.
    # A review aid that fails silently is worse than a run that stops. (B18)
    if C.emit_review_view(p) is False:
        _bad(f"could not refresh the reviewer twin (canonical_review.json) for {p.name} - "
             f"NOT freezing, because the DATA reviewers would read a stale artefact while "
             f"`freeze --check` reported them byte-identical. Fix the write error and re-run.")
        print("STATUS: BLOCKED"); return 1
    C.atomic_write_text(side, sha)
    _ok(f"froze {p.name} ({sha[:12]}) before parallel review")
    print("STATUS: ALL-PASS"); return 0


# --------------------------------------------------------------------------- #
def cmd_enrichment(args) -> int:
    """Mechanical half of the enrichment gate - the layer that had NO gate and is
    where the audit's defects lived (a region figure copied from a neighbour, a
    figure with no source, an empty POI set so distances never resolve). The
    province-vs-proxy and source-currency judgements are the isolated G-enrich
    reviewer's job; this catches the cheap, certain ones."""
    data = C.load_canonical(Path(args.canonical))
    enr = (data.get("meta", {}) or {}).get("enrichment", {}) or {}
    degraded = bool(enr.get("degraded"))
    requested = [k for k in (getattr(args, "requested", "") or "").split(",") if k]
    stamped = any(enr.get(k) for k in ("geocode", "pois", "osrm", "regions"))
    # P2-9: enrichment was REQUESTED but the stage left NO record at all -> it
    # crashed or was skipped. Keying only on the OUTPUT meta let a degraded-to-null
    # enrichment pass as "nothing requested, ALL-PASS" (a silently un-enriched ship).
    # A genuine no-enrichment run has requested=[] and passes below as before.
    if requested and not stamped:
        _bad(f"enrichment was requested ({', '.join(requested)}) but the stage produced NO "
             f"record - it crashed or was skipped; re-run enrichment (do not ship a "
             f"silently un-enriched dashboard)")
        print("STATUS: BLOCKED (1 enrichment issue)"); return 1
    if not stamped:
        _ok("no enrichment requested - nothing to verify")
        print("STATUS: ALL-PASS"); return 0

    issues, notes = [], []
    regions = data.get("regions", {}) or {}
    if enr.get("regions"):
        if not regions:
            # ALWAYS a hard block - never excused by the offline/degraded flag. The
            # workforce block is a research/dataset matter, not a network one, and a
            # real run shipped an EMPTY workforce block as a soft "DEGRADED" note
            # that nobody saw. Silent partial success is worse than loud failure.
            issues.append("regions enrichment requested but ZERO profiles attached - "
                          "regionCodes did not match any cache/dataset profile (use "
                          "province-level region labels, or fix regions_cache.json)")
        # cross-region duplicate = copy-paste SMELL, advisory only: real regional
        # statistics rounded to one decimal collide routinely (two Czech regions at
        # 3.2% unemployment is normal data), so this must never hard-block - the
        # only way past a block on true data would be falsifying a figure. The
        # isolated G-enrich reviewer verifies the figures against their sources.
        for field in ("unemployment", "gdpPpsEu"):
            seen = {}
            for code, r in regions.items():
                v = r.get(field)
                if isinstance(v, (int, float)):
                    if v in seen:
                        notes.append(f"regions '{seen[v]}' and '{code}' share an identical {field}={v} "
                                     f"- possibly copied from a neighbour, possibly real; "
                                     f"G-enrich must verify both against their cited sources")
                    seen[v] = code
        # every stated figure needs an as-of date + a source; basic units sanity
        for code, r in regions.items():
            if any(isinstance(r.get(f), (int, float)) for f in ("unemployment", "gdpPpsEu")) \
                    and not str(r.get("sources", "")).strip():
                issues.append(f"region '{code}': figures stated but 'sources' is empty")
            for fig, asof in (("unemployment", "unemploymentAsOf"),
                              ("gdpPpsEu", "gdpPpsAsOf")):
                if isinstance(r.get(fig), (int, float)) and not str(r.get(asof, "")).strip():
                    issues.append(f"region '{code}': {fig} stated without {asof}")
            # range = ADVISORY note, not a block: only flag the genuinely absurd for the reviewer
            u = r.get("unemployment")
            if isinstance(u, (int, float)) and not (0 <= u <= 60):
                notes.append(f"region '{code}': unemployment {u} looks off - verify units (% vs fraction)")

        # LABOUR-DATA RECENCY (BLOCKING): unemployment publishes with at most ~1
        # year lag, so the FLOOR is run_year-1 (current year is always better; the
        # bundled Oxford Economics baseline is current-year, and a researcher
        # override must try the current year first). Jan-May exception: the previous
        # year's releases may not be out yet, so run_year-2 is accepted ONLY when the
        # profile carries a recencyNote documenting that the run_year-1 search failed
        # - then it is an advisory note, not a block. (Wages were removed from the
        # workforce snapshot - the dataset supplies the whole snapshot now - so this
        # floor now governs only unemployment.)
        today = _today()
        run_year = today.year
        LABOUR = (("unemployment", "unemploymentAsOf"),)
        for code, r in regions.items():
            note_ok = bool(str(r.get("recencyNote", "")).strip())
            for fig, asof in LABOUR:
                if not isinstance(r.get(fig), (int, float)):
                    continue
                yr = _stated_year(r.get(asof))
                if yr is None:
                    if str(r.get(asof, "")).strip():
                        issues.append(f"region '{code}': {fig} as-of '{r.get(asof)}' has no "
                                      f"parseable year - recency unverifiable")
                    continue  # missing asof entirely is already blocked above
                if yr >= run_year - 1:
                    continue  # current year or year-1: meets the floor
                if yr == run_year - 2 and today.month <= 5 and note_ok:
                    notes.append(f"region '{code}': {fig} is {yr} (year-2), accepted Jan-May "
                                 f"because recencyNote documents the {run_year - 1} search "
                                 f"failed - re-check once the {run_year - 1} release lands")
                else:
                    hint = (f"; Jan-May a {run_year - 2} figure is acceptable ONLY with a "
                            f"recencyNote documenting that the {run_year - 1} search failed"
                            if today.month <= 5 else "")
                    issues.append(f"region '{code}': {fig} as-of {yr} is too old - labour data "
                                  f"floor is {run_year - 1} (current year preferred){hint}")
        # GDP PPS and population keep a softer ADVISORY (regional GDP genuinely
        # publishes ~2 years behind; census data moves slowly): 3+ years -> note.
        for code, r in regions.items():
            for fig, asof in (("gdpPpsEu", "gdpPpsAsOf"), ("population", "populationAsOf")):
                yr = _stated_year(r.get(asof))
                if isinstance(r.get(fig), (int, float)) and yr is not None and yr < run_year - 2:
                    notes.append(f"region '{code}': {fig} is as-of {yr} ({run_year - yr}y old) - "
                                 f"confirm there is no newer release before shipping")

    if enr.get("pois"):
        if not data.get("pois"):
            if degraded:
                notes.append("POIs empty - ENRICHMENT DEGRADED (offline); dashboard resolves distances client-side online")
            else:
                issues.append("pois requested but the POI set is EMPTY - distances will not resolve "
                              "(the empty-POIs bug). Re-run --pois online, or mark enrichment degraded.")
        elif not enr.get("pois_live"):
            # the map shows library STOPGAP markers, not the genuine nearest - that
            # is below the product bar; the web_enrich handoff must be fulfilled
            issues.append("POIs are the library STOPGAP, not the genuine OSM nearest - fulfil "
                          "work/web_requests.json (WebFetch each url -> web_enrich.py ingest -> re-run); "
                          "run.py exit 8 emits it when the sandbox network is dead")
    if enr.get("osrm"):
        located = [p for p in data.get("properties", []) if isinstance(p.get("lat"), (int, float))]
        missing = [p.get("id") for p in located if not (p.get("preBaked", {}) or {}).get("distances")]
        if missing and not degraded:
            notes.append(f"{len(missing)} located properties have no pre-baked drive-times (in-browser fallback)")

    for n in notes:
        print(f"[note] {n}")
    if issues:
        for i in issues:
            _bad(i)
        print(f"STATUS: BLOCKED ({len(issues)} enrichment issues)")
        return 1
    _ok(f"enrichment verified ({len(regions)} regions, {len(data.get('pois', []))} POIs"
        + ("; DEGRADED/offline, flagged" if degraded else "") + ")")
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
def cmd_translation(args) -> int:
    """Mechanical half of the v22 Phase 2 translation gate: BLOCKS the build if the
    translation pass did not fully do its job - a request named a non-eligible field,
    or an eligible free-text field in the built canonical is still untranslated."""
    import translate as TR
    import i18n as I18N
    issues = []
    work = Path(args.work)
    target_code = I18N.normalize_lang(getattr(args, "lang", "English") or "English")
    data = C.load_canonical(Path(args.canonical))
    tdir = work / "i18n"
    import os as _os
    import translate as _TR
    if _os.environ.get(_TR.SKIP_ENV) == "1" or (tdir / "data_translate.SKIP").exists():
        _ok("free-text translation declined (SKIP) - data shipped in source language")
        print("STATUS: ALL-PASS")
        return 0
    # the on-disk cache is the raw {source_text: translation} handoff; rekey it by text_key
    # exactly as run_stage does, so the gate's collect_requests lookup matches the bake.
    cache = TR._hashed_cache(TR._load_cache(tdir / f"data_translations.{target_code}.json"), target_code)
    # (1) the request (if any) must only name eligible fields
    reqp = tdir / "data_translate_request.json"
    if reqp.exists():
        try:
            req = json.loads(reqp.read_text(encoding="utf-8-sig"))
        except Exception:
            req = {}
        for it in (req.get("items") or []):
            if not C.is_translatable_value(it.get("field", ""), it.get("text", "")):
                issues.append(f"translate request names a NON-eligible field: {it.get('field')!r}")
    # (2) every eligible field in the built canonical must be handled (translated or already target)
    remaining = TR.collect_requests(data, target_code, cache)
    if remaining:
        ex = ", ".join(f"{r['property_id']}:{r['field']}" for r in remaining[:5])
        issues.append(f"{len(remaining)} eligible free-text field(s) not translated to the target "
                      f"language (e.g. {ex}) - the translation pass did not complete")
    if issues:
        for i in issues:
            _bad(i)
        print("STATUS: BLOCKED")
        return 1
    _ok("free-text data is translated to the target language (or already in it)")
    print("STATUS: ALL-PASS")
    return 0


def cmd_arithmetic(args) -> int:
    """P1-1: the chrome's DERIVED total area must not exceed the source's OWN stated total.

    THE LIVE DEFECT. A tracker column holding each brochure's TOTAL GIA was mapped into
    `warehouseArea`. The chrome derives `Total GLA = warehouseArea + officeAreaVal` and
    `rent = GLA x rate`, so the office area was added to a figure that already contained it:
    derived GLA 557,232 against the source's own stated 498,723 (11.7% over), and rent overstated
    by up to GBP 702,108/yr - figures that appear in NO source. Two Opus reviewers found it by
    reading pages side by side. Arithmetic finds it for free.

    WHAT THIS GATE DOES NOT DO. It judges nothing. It compares two numbers the LLM already read
    off the same page and reports the arithmetic. WHICH of the two figures is wrong - the tracker
    mapping, the office area, or the stated total - stays an LLM/reviewer judgement. It replicates
    the chrome's OWN formula (quoted from assets/dashboard_template.html `glaVal`) rather than
    re-deriving what the total "should" be:

        function glaVal(p){
          const w = p.warehouseArea;
          if(typeof w !== "number" || !isFinite(w)) return null;
          const o = (typeof p.officeAreaVal === "number" && isFinite(p.officeAreaVal)
                     && p.officeAreaVal > 0) ? p.officeAreaVal : 0;
          return w + o;
        }

    TOLERANCE `max(50 area units, 0.5% of stated)`, and deliberately ASYMMETRIC:
      * OVER-derivation BLOCKS - the derived figure claims space the source does not state.
      * UNDER-derivation is a [note] only - mezzanine, ancillary and plant areas legitimately do
        not sum, and real schedules are imprecise. Measured on the live decks: out by 2 sq ft and
        by ~700 sq ft on ~440,000 (0.159%, three times inside the margin). The actual defect was
        11.7%, about 23x the tolerance.

    IT CANNOT BLOCK A LEGITIMATE RUN. Every property is SKIPPED unless the comparison is sound:
    no stated total recorded; a non-numeric or absent contributor; a sentinel; or a stated total
    whose unit merge could not align (see `merge.stated_total_for`, which refuses an un-converted
    record outright). An ack clears a property that is genuinely fine.
    """
    data = C.load_canonical(Path(args.canonical))
    meta = data.get("meta", {}) or {}
    stated = meta.get("statedTotals") or {}
    ack_file = Path(args.canonical).resolve().parent / "placeholder_audit_ack.json"
    ack: dict = {}
    if ack_file.exists():
        try:
            ack = json.loads(ack_file.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            pass
    acked = {str(x) for x in (ack.get("arithmetic_ok") or [])}

    def _num(v):
        """The chrome's own test: a finite number, and for office also > 0."""
        return v if (isinstance(v, (int, float)) and not isinstance(v, bool)
                     and math.isfinite(v)) else None

    issues, notes, checked = [], [], 0
    for p in data.get("properties", []):
        pid = str(p.get("id"))
        st = stated.get(pid) or {}
        total = _num(st.get("value"))
        if total is None or total <= 0:
            continue                      # no stated total for this property -> nothing to check
        wa = _num(p.get("warehouseArea"))
        if wa is None:
            continue                      # glaVal() returns null here, so there is no derivation
        oa = _num(p.get("officeAreaVal"))
        oa = oa if (oa is not None and oa > 0) else 0     # exactly glaVal()'s guard
        gla = wa + oa
        tol = max(50.0, 0.005 * total)
        checked += 1
        # the unit is a PER-PROPERTY field (merge stamps merged["areaUnit"]); canonical.meta has no
        # areaUnit key, so never read one from there
        u = st.get("unit") or p.get("areaUnit") or ""
        label = (f"property={pid} ({p.get('park') or p.get('city') or '?'}) "
                 f"derived GLA {gla:,.0f} vs stated total {total:,.0f} {u}"
                 f" [{st.get('source_file') or '?'} {st.get('locator') or ''}]".rstrip())
        if gla - total > tol:
            if pid in acked:
                notes.append(f"{label} - OVER by {gla - total:,.0f}, ACKED in "
                             f"placeholder_audit_ack.json (arithmetic_ok)")
                continue
            over_pct = (gla - total) / total * 100.0
            issues.append(
                f"{label} - OVER by {gla - total:,.0f} ({over_pct:.1f}%, tolerance "
                f"{tol:,.0f}). The chrome derives GLA = warehouseArea + officeAreaVal and "
                f"rent = GLA x rate, so this also overstates any total rent. Usually the size "
                f"column was a GROSS total that already INCLUDED the office: fix the datum "
                f"(warehouseArea should be the NET warehouse area), or - if the figures are "
                f"genuinely right - add \"{pid}\" to \"arithmetic_ok\" in "
                f"placeholder_audit_ack.json.")
        elif total - gla > tol:
            notes.append(f"{label} - under by {total - gla:,.0f} (mezzanine / ancillary / plant "
                         f"space is not required to sum; not blocking)")
    for n in notes:
        print(f"[note] {n}")
    if not stated:
        _ok("no source states its own total area - arithmetic check not applicable")
    elif not checked:
        _ok(f"{len(stated)} stated total(s) recorded, none comparable (missing or non-numeric "
            f"contributor) - skipped")
    elif not issues:
        _ok(f"derived GLA agrees with the source's own stated total on {checked} property(ies)")
    for m in issues:
        _bad(m)
    if issues:
        print(f"STATUS: BLOCKED ({len(issues)} arithmetic inconsistency(ies))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


# --------------------------------------------------------------------------- #
# THE QA WINDOW: exactly ONE review round + ONE improvement round, then deliver.
#
# WHY THIS IS MECHANICAL. The old bound was prose ("Bounded loops (~3)") and the visual rubric
# said "re-render and re-review with a fresh reviewer UNTIL ZERO HIGH/MED" - an unbounded loop
# whose exit condition is a subjective verdict, re-earned from scratch by a deliberately
# memoryless reviewer every round. Any fresh reviewer can always find one more debatable layout
# nit, so on a subjective dimension it never terminates. An eager orchestrator cannot argue with
# a counter it did not write; it can always argue with a paragraph.
#
# WHAT THIS DELIBERATELY DOES **NOT** DO. It does not classify findings. Severity on an unseen
# deck, in an unseen language, for a client nobody has met, is a PERCEPTION call and belongs to
# the reviewer - the skill is LLM-driven by design and Python's job is to verify and bind, never
# to judge. So the reviewer labels each finding `blocking:` or `advisory:` ITSELF (rubric in
# reference/gates.md), and this command only COUNTS rounds and REMEMBERS what was said. A
# regex deciding what blocks would move judgement into the shell; that was rejected.
#
# The counter is keyed on `run_key` = the WORK DIR + the intake input hash - never on the
# canonical SHA. Keying on artefact bytes would hand every legitimate data fix a fresh budget
# and quietly restore the infinite loop.
# The QA window is ONE review pass. Reviewers PROPOSE, the orchestrator IMPLEMENTS, then we
# deliver. The old two-round budget with verdict gating produced three ship-blockages on one
# live run that were mechanism failures rather than data problems, while the data work - five
# genuine findings, all fixed - was the small part. Kept: isolated blind reviewers, their own
# blocking/advisory labels, the mechanical gates, the freeze, and the rule that a BLOCKING
# finding cannot ship until the orchestrator records what it changed.
QA_MAX_ROUNDS = 1
# The bullet is OPTIONAL: final_gate's labelled-line check (final_gate.py) accepts a
# dashless `blocking: ...`, and SKILL.md/prompts tell reviewers only "every line
# labelled". The first cut REQUIRED `- `, so a dashless blocking finding was never
# ingested here while final_gate counted it "proposed" - an unaddressed blocking
# finding shipped through an ALL-PASS (Phase-3 blind review, reproduced end-to-end).
# Shape: a bulleted label keeps its colon optional (`- [blocking] x` stays valid);
# a DASHLESS label requires the colon, so a prose line that merely begins with the
# word "blocking" is never ingested as a finding.
_FINDING_RE = re.compile(
    r"^\s*(?:[-*]\s*\[?(?P<l1>blocking|advisory)\]?\s*:?"
    r"|\[?(?P<l2>blocking|advisory)\]?\s*:)\s*(?P<body>.+)$", re.I | re.M)
# The ESTABLISHED finding format (reference/gates.md has mandated `- [HIGH|MED|LOW] property=…`
# for a long time). Accepting it means a reviewer that writes the format it already knows needs
# NO correction and NO re-dispatch - the first cut only accepted the new `blocking:`/`advisory:`
# words, so a compliant-but-old-format review looked "unlabelled" and invited another agent, which
# is precisely the extra-round cost this whole feature exists to remove. HIGH is the reviewer's own
# "this blocks" and MED/LOW its own "this does not"; the mapping uses THEIR judgement, not ours.
_SEVERITY_RE = re.compile(r"^\s*-\s*\[(HIGH|MED|MEDIUM|LOW|ENV)\]\s*(.+)$", re.I | re.M)
_SEVERITY_BUCKET = {"high": "blocking", "med": "advisory", "medium": "advisory",
                    "low": "advisory", "env": "advisory"}


_ROUND_DIR_RE = re.compile(r"^round(\d+)$", re.I)


def review_round_dirs(reviews) -> list:
    """Round-scoped review dirs as (n, path), ascending.

    Reviews live at `reviews/round<N>/<gate>.md`. The round is in the PATH so a
    re-dispatched reviewer always writes a NEW file: previously the path was flat, so
    round 2 could only be produced by OVERWRITING round 1 - which meant the harness
    made an ostensibly independent reviewer read the previous verdict first. Reviewer
    independence is the entire basis of the judgement gates. (B24)

    N is supplied by the orchestrator as a uniqueness token, never derived from
    qa_state.json: the two shipped flows disagree on whether `qa-round open` precedes
    dispatch, so no round number reliably exists at dispatch time."""
    out = []
    try:
        for d in Path(reviews).iterdir():
            m = _ROUND_DIR_RE.match(d.name) if d.is_dir() else None
            if m:
                out.append((int(m.group(1)), d))
    except Exception:
        return []
    return sorted(out)


def review_dir_for(reviews, round_no=None) -> Path:
    """The directory a reader should take THIS round's verdicts from.

    Falls back to the flat root, which stays supported permanently as round 0 - work
    dirs from before the round-scoped layout must keep working."""
    dirs = review_round_dirs(reviews)
    if round_no is not None:
        for n, d in dirs:
            if n == round_no:
                return d
    return dirs[-1][1] if dirs else Path(reviews)


def review_file(reviews, gate: str, round_no=None):
    """The gate's STANDING verdict file: newest round at or below `round_no`, else the
    flat root, else None.

    Searching DOWNWARD matters. Under a scoped re-review only the gates that raised
    blocking findings are re-dispatched, so a clean gate's only verdict may live in
    round1/ - reading just the current round would report it as never reviewed and
    block a shippable pack."""
    for n, d in reversed(review_round_dirs(reviews)):
        if round_no is not None and n > round_no:
            continue
        p = d / f"{gate}.md"
        if p.exists():
            return p
    p = Path(reviews) / f"{gate}.md"
    return p if p.exists() else None


def finding_id(entry: str) -> str:
    """Stable short handle for a recorded finding.

    Keyed on the reviewer's own words (gate prefix included) with whitespace and case
    normalised, so a re-record of the same finding keeps the same id and a `resolve`
    survives it. Findings are otherwise bare prose with no handle at all, which is what
    made "this advisory was actually fixed" unsayable. (B26)"""
    import hashlib
    return hashlib.sha256(" ".join(str(entry).split()).lower().encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------------------- #
# The finding-to-gate FLYWHEEL (P5). The expensive part of every run is the review pass, and
# its findings cluster into recurring CLASSES (the same gate flagging the same field shape on
# project after project). SKILL.md already says a recurring cosmetic finding is a template bug
# to fix once; this generalises that: every recorded finding is appended to a cross-run ledger
# in the SKILL's own state/ dir (per-user, deliberately OUTSIDE the integrity manifest - it
# grows per run), and a class seen in >= 2 distinct runs is surfaced as a CANDIDATE for
# conversion into a mechanical pre-build gate + eval. Reviews then trend toward
# `FINDINGS: none` - reviewers as the safety net, not the primary defect-removal mechanism.
# Everything here is best-effort: the flywheel must never block or corrupt a QA round.
# --------------------------------------------------------------------------- #
_FLYWHEEL_ENV = "CBRE_FLYWHEEL_PATH"  # test override; default lives beside the skill
_FLYWHEEL_FIELD_RE = re.compile(r"\bfield=([A-Za-z0-9_,\- ]+?)(?:\s+issue=|\s*$)")


def _flywheel_path() -> Path:
    import os
    p = os.environ.get(_FLYWHEEL_ENV)
    return Path(p) if p else (Path(__file__).resolve().parent.parent
                              / "state" / "qa_findings.jsonl")


def finding_class(entry: str) -> str:
    """The recurrence key: the gate that raised it + the field it names (or '-'). Coarse on
    purpose - a class is a SHAPE of defect ('G-honesty keeps flagging motorway'), not one
    finding's exact wording, and the gate+field pair is the stable part of the entry format."""
    gate = str(entry).split(":", 1)[0].strip() or "-"
    m = _FLYWHEEL_FIELD_RE.search(str(entry))
    fld = (m.group(1).strip() if m else "") or "-"
    return f"{gate}|{fld}"


def _flywheel_read() -> list[dict]:
    led = _flywheel_path()
    rows: list[dict] = []
    try:
        if led.exists():
            for line in led.read_text(encoding="utf-8-sig").splitlines():
                try:
                    e = json.loads(line)
                    if isinstance(e, dict):
                        rows.append(e)
                except Exception:
                    continue
    except Exception:
        pass
    return rows


def flywheel_append(work: Path, cur: dict) -> list[str]:
    """Append this round's findings to the cross-run ledger; return nudge lines for classes
    that have now been seen in >= 2 DISTINCT runs. Best-effort - never raises.

    A work dir under the system temp dir is SKIPPED (unless the env override is set): those
    are eval/sim rounds, and letting fixture findings into the ledger both pollutes the
    recurrence signal and can fire a spurious nudge inside an eval's asserted stdout.
    run_all.py additionally points every eval at an isolated ledger, so both the suite and
    a hand-run eval stay out of the real state/."""
    try:
        import datetime
        import hashlib
        import os
        import tempfile
        if not os.environ.get(_FLYWHEEL_ENV):
            try:
                Path(work).resolve().relative_to(Path(tempfile.gettempdir()).resolve())
                return []  # an eval/sim round - never ledger fixture findings
            except ValueError:
                pass  # a real project work dir
        run_key = hashlib.sha1(str(Path(work).resolve()).encode("utf-8")).hexdigest()[:12]
        prior: dict = {}
        for e in _flywheel_read():
            prior.setdefault(str(e.get("class")), set()).add(str(e.get("run")))
        rows, nudges, nudged = [], [], set()
        for bucket in ("blocking", "advisory"):
            for entry in cur.get(bucket) or []:
                cls = finding_class(entry)
                rows.append(json.dumps(
                    {"ts": datetime.date.today().isoformat(), "run": run_key,
                     "bucket": bucket, "class": cls, "id": finding_id(entry),
                     "text": " ".join(str(entry).split())[:200]}, ensure_ascii=False))
                other_runs = prior.get(cls, set()) - {run_key}
                if other_runs and cls not in nudged:
                    nudged.add(cls)
                    nudges.append(
                        f"[flywheel] finding class '{cls}' has now recurred across "
                        f"{len(other_runs) + 1} run(s) - a recurring class is a GATE "
                        f"candidate: convert it into a mechanical pre-build check + eval "
                        f"(see SKILL.md 'Maintenance'; `gate_runner.py flywheel` lists all).")
        if rows:
            led = _flywheel_path()
            led.parent.mkdir(parents=True, exist_ok=True)
            with led.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
        return nudges[:5]
    except Exception:
        return []


def cmd_flywheel(args) -> int:
    """Report the cross-run finding classes, most-recurrent first. A class seen in >= 2
    distinct runs is flagged as a candidate for conversion into a mechanical gate + eval."""
    rows = _flywheel_read()
    if not rows:
        print("flywheel ledger empty - no QA rounds recorded yet "
              f"(ledger: {_flywheel_path()})")
        return 0
    agg: dict = {}
    for e in rows:
        cls = str(e.get("class"))
        a = agg.setdefault(cls, {"runs": set(), "n": 0, "last": "", "sample": ""})
        a["runs"].add(str(e.get("run")))
        a["n"] += 1
        if str(e.get("ts") or "") >= a["last"]:
            a["last"] = str(e.get("ts") or "")
            a["sample"] = str(e.get("text") or "")
    order = sorted(agg.items(), key=lambda kv: (-len(kv[1]["runs"]), -kv[1]["n"], kv[0]))
    n_cand = 0
    for cls, a in order:
        tag = "CANDIDATE GATE" if len(a["runs"]) >= 2 else "seen once"
        n_cand += 1 if len(a["runs"]) >= 2 else 0
        print(f"[{tag}] {cls}: {a['n']} finding(s) across {len(a['runs'])} run(s), "
              f"last {a['last']}")
        print(f"    e.g. {a['sample'][:160]}")
    print(f"\n{n_cand} class(es) recur across runs. Each is review money spent twice: "
          f"convert it into a mechanical pre-build gate + an eval, then the reviewers stop "
          f"finding it (SKILL.md 'Maintenance').")
    return 0


def _artefact_fingerprint(work) -> str:
    """Fingerprint of the artefacts a genuine QA fix moves: the merged data, the manual overrides,
    and any built dashboard.

    Recorded on the round and on each `resolve` as an audit breadcrumb - what the artefacts looked
    like when the finding was recorded and when its repair was. It is NO LONGER a gate: `resolve`
    used to be refused unless this had changed since the round was recorded, and because the round's
    fingerprint was stamped after the repairs, that made recording a genuine repair impossible in the
    documented order - a delivered Gaps Report shipped a "Known limitations" line asserting a defect
    the pack no longer had. The guards that carry meaning are the id naming a finding actually raised
    and the written reason."""
    import hashlib
    h = hashlib.sha256()
    w = Path(work)
    for rel in ("canonical.json", "overrides.json"):
        try:
            h.update(hashlib.sha256((w / rel).read_bytes()).digest())
        except Exception:
            h.update(b"\0")
    # The DELIVERED documents count too, not just the dashboard (B49). Several findings each
    # round are about the Gaps Report itself - a truncated note, a stale limitation, a false
    # "absent in all sources" line - and their remedy is a Gaps Report change that moves no
    # canonical byte. With only *.html watched, `resolve` refused those repairs with "nothing
    # changed" while `final_gate` blocked on the still-open adjudication: a genuine repair
    # could not be recorded, and the window could not close. That is precisely the
    # non-termination this bounded window exists to prevent, reached from the other side.
    # Observed live on a 12-property UK run (adjudication 1f3f63dc97).
    #
    # This only ever WIDENS the guard - more artefacts are watched, so nothing that was
    # refused before is now accepted without a real byte change.
    #
    # The out dir is no longer a fixed `<work>/deliverables`: the three-folder project layout
    # delivers to a sibling '3. Output'. run.py records where it went in `<work>/.output_dir`,
    # so this reads that pointer and keeps watching the delivered documents wherever they are.
    # Both legacy locations stay in the list, so an older project is fingerprinted identically.
    _outs = [w, w / "deliverables"]
    try:
        _p = (w / ".output_dir").read_text(encoding="utf-8-sig").strip()
        if _p and Path(_p) not in _outs:
            _outs.append(Path(_p))
    except Exception:
        pass
    for d in _outs:
        try:
            for p in sorted(d.glob("*")):
                if p.suffix.lower() not in (".html", ".md", ".xlsx", ".csv") or not p.is_file():
                    continue
                s = p.stat()
                h.update(f"{p.name}|{s.st_size}|{s.st_mtime_ns}".encode())
        except Exception:
            pass
    return h.hexdigest()[:16]


def _qa_state_path(work: Path) -> Path:
    return Path(work) / "qa_state.json"


def _qa_inv_hash(work: Path) -> str:
    """The intake corpus identity - `inventory.json`'s content-derived `input_hash`."""
    try:
        inv = json.loads((Path(work) / "inventory.json").read_text(encoding="utf-8-sig"))
        return str(inv.get("input_hash") or inv.get("folder") or "")
    except Exception:
        return ""


def _qa_run_key(work: Path) -> str:
    """The CORPUS identity, and ONLY the corpus identity. Deliberately independent of
    canonical.json's bytes AND of where the work dir happens to sit on disk.

    IT USED TO INCLUDE `Path(work).resolve()`, and that made the QA window silently
    PATH-COUPLED: renaming or moving the project folder changed the key, `_qa_load` treated
    a byte-identical qa_state.json as "a different corpus", wiped `rounds`, and the very next
    `deliver.py` shipped a Gaps Report with NO "Known limitations" section at all while
    `qa_round_number` fell back to 0 (disabling PASS-WITH-REMEDIATION). Observed live: a
    project reorganised into the `1. Input` / `2. Work Files` / `3. Output` layout lost twelve
    reviewed-and-accepted limitations from the honesty document, for no reason but a folder
    rename. The path added nothing it was needed for - qa_state.json already lives IN the work
    dir, so it is per-work-dir by construction - while the input hash is exactly the "is this
    the same corpus?" question the window is asking."""
    import hashlib
    return hashlib.sha256(f"corpus|{_qa_inv_hash(work)}".encode()).hexdigest()[:16]


def _qa_run_key_legacy(work: Path) -> str:
    """The pre-fix, path-coupled key. Accepted on READ so an existing window in an
    UNMOVED work dir is adopted (and re-keyed) instead of wiped by the upgrade itself."""
    import hashlib
    return hashlib.sha256(
        f"{Path(work).resolve()}|{_qa_inv_hash(work)}".encode()).hexdigest()[:16]


def enrich_signature(work) -> str:
    """Which enrichment LAYERS shaped this artefact - flags only, never their values. (B60)

    `.enrich.stamp` stores the whole argument string, and that INCLUDES the openrouteservice API
    key. Only `--flag` tokens are kept, so a secret can never enter a signature that is written
    into qa_state.json and echoed back by final_gate. Absent or corrupt stamp -> "" (inert).

    Deliberately NOT folded into `_qa_run_key`. Resetting the window on an enrichment change reads
    well in theory, but on a live work dir it wipes an already-recorded round, drops qa_round to
    zero, disables PASS-WITH-REMEDIATION and re-blocks a pack that was verified and shipped. The
    honest move is to SAY the verdicts predate the change, not to destroy the evidence that they
    were made."""
    try:
        args = json.loads((Path(work) / ".enrich.stamp").read_text(encoding="utf-8-sig")).get("args")
    except Exception:
        return ""
    toks = [t.strip() for t in str(args or "").split("|")]
    return "|".join(sorted(t for t in toks if t.startswith("--")))


def _qa_load(work: Path) -> dict:
    st = {}
    try:
        st = json.loads(_qa_state_path(work).read_text(encoding="utf-8-sig"))
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    key = _qa_run_key(work)
    if st.get("run_key") == _qa_run_key_legacy(work) and st.get("run_key") != key:
        # written before the key stopped including the work dir's path: same corpus, same
        # folder, so ADOPT it and re-key. Wiping here would destroy a recorded round purely
        # because the skill was upgraded.
        st["run_key"] = key
    if st.get("run_key") != key:  # a different corpus in this work dir -> a fresh window
        st = {"schema_version": 2, "run_key": key, "rounds": [], "advisory_carried": []}
    if st.get("schema_version") != 2:
        # A window written by the two-round/verdict-gated design carries an `adjudication` map and a
        # round budget this code no longer understands. Start a fresh window rather than half-read
        # it - the reviewers are re-dispatched anyway, and a misread state could mark a blocking
        # finding addressed when it was not.
        st = {"schema_version": 2, "run_key": key, "rounds": [], "advisory_carried": []}
    st.setdefault("rounds", [])
    st.setdefault("advisory_carried", [])
    return st


def _qa_save(work: Path, st: dict) -> None:
    C.atomic_write_text(_qa_state_path(work), json.dumps(st, ensure_ascii=False, indent=2))


def qa_round_number(work) -> int:
    """Rounds OPENED so far (0 = the QA window has not started). Used by final_gate."""
    try:
        return len(_qa_load(Path(work)).get("rounds") or [])
    except Exception:
        return 0


def qa_carried(work) -> list:
    """Advisory findings still open - they ship in the Gaps Report's "Known limitations".

    ONLY THE LATEST ROUND'S list, never the union across rounds. Each round is judged by a FRESH
    reviewer against the CURRENT artefact, so the newest list is the only one that describes what
    is actually being shipped; an earlier round's advisory note may since have been FIXED.
    Unioning them shipped stale notes as live limitations - caught on a live run, where the Gaps
    Report told the broker "all 12 carry the tracker's GIA gross total" and "nine of twelve carry
    the deck name in region" after the improvement round had corrected 11 areas and struck nine
    regions to tbd. A Known-limitations list that misdescribes the delivered data is worse than no
    list: it is a false statement in the one document whose job is honesty.

    Two things this must NOT do, both of which it used to. It must not read a round that
    is merely OPEN: `rounds[-1]` after a bare `qa-round open` is an empty shell, so every
    limitation silently vanished and final_gate still passed - a resolve-everything path
    that needed no resolve command at all. And it must not report a finding the
    improvement pass actually FIXED: those are struck by `qa-round resolve`, which
    records why and is guarded by an artefact fingerprint. (B26)"""
    try:
        st = _qa_load(Path(work))
    except Exception:
        return []
    recorded = [r for r in (st.get("rounds") or []) if r.get("recorded")]
    if not recorded:
        return []
    last = recorded[-1]
    struck = set((last.get("resolved") or {}).keys())
    out: list = []
    for f in last.get("advisory") or []:
        if finding_id(f) in struck:
            continue
        if f not in out:
            out.append(f)
    return out


def qa_blocking_open(work) -> list:
    """BLOCKING findings the orchestrator has not recorded a resolution for.

    This is the ONE safety property carried over from the old verdict gating, and it is why the
    restructure is not simply "stop checking". A `blocking:` finding is, by the reviewer's own
    rubric, a FALSE CLAIM in the deliverable - a fabricated or untraceable value, a swallowed
    disagreement, a wrong-property photo. Such a thing may not ship merely because the review pass
    is over. What changed is what counts as ADDRESSED: the orchestrator RECORDING what it changed
    (`qa-round resolve`, with a written reason in the audit trail), rather than a second reviewer
    re-blessing it. Advisory findings never appear here - they are carried into the Gaps Report's
    "Known limitations" and ship."""
    try:
        st = _qa_load(Path(work))
    except Exception:
        return []
    rounds = [r for r in (st.get("rounds") or []) if r.get("recorded")]
    if not rounds:
        return []
    struck = {k for r in (st.get("rounds") or []) for k in (r.get("resolved") or {})}
    out = []
    for entry in rounds[-1].get("blocking") or []:
        fid = finding_id(entry)
        if fid in struck:
            continue
        out.append({"id": fid, "finding": entry})
    return out


def qa_resolved_count(work) -> int:
    """Findings raised and FIXED inside the QA window, across all recorded rounds.

    final_gate reads this to distinguish a pack that was remediated from one that was
    clean first try - previously both printed the same plain ALL-PASS. Machine-checkable
    from recorded state, and unreachable by never recording a finding. (B25)"""
    try:
        st = _qa_load(Path(work))
    except Exception:
        return 0
    return sum(len(r.get("resolved") or {}) for r in (st.get("rounds") or []))


def _coalesce_rounds(st: dict) -> list:
    """Fold a window carrying MORE THAN ONE round into the single round this design allows.

    A run records EXACTLY ONE review round: the reviewers are spawned once, the orchestrator
    implements, the pack is delivered. `record` no longer opens a second round - but a work
    dir is a durable thing, and one written by the two-round/verdict-gated design, or by any
    build in which `record` still self-opened, arrives here carrying two or three. Both
    obvious answers are dishonest. CRASHING strands a pack whose window is perfectly
    readable. KEEPING ONLY THE NEWEST round silently drops an unrepaired BLOCKING finding -
    a FALSE CLAIM by the reviewer's own rubric - because a later pass happened not to repeat
    it. So it FOLDS, and each half of the fold is chosen so that nothing is lost and nothing
    is overstated:

      * the ADVISORY list is the LATEST RECORDED round's, verbatim, NEVER the union. That is
        B26's doctrine and it is load-bearing: every round was judged by a fresh reviewer
        against the artefact AS IT THEN WAS, so only the newest list describes what is
        actually being shipped. Unioning them shipped notes the improvement pass had already
        made false, into the one document whose whole job is honesty.
      * every UNRESOLVED blocking finding from the superseded rounds is carried FORWARD into
        the survivor. This is the half that fails toward BLOCKING rather than toward
        shipping, and it is the whole reason not to simply keep the newest round.
      * the `resolved` maps are UNIONED, so a repair already recorded - with its reason and
        its fingerprint - is never re-blocked by the fold itself. Unioned by id, so a finding
        resolved in two rounds counts once: `qa_resolved_count` can therefore report a
        SMALLER number than the pre-fold state did, and that number is the true count of
        distinct repairs.
      * `verdicts` are unioned with the LATER round winning, which is the same
        highest-round-first resolution `review_file` applies to the files.
      * the superseded rounds are moved VERBATIM into `superseded_rounds`, not deleted.
        Nothing reads them; they are there so an operator can see exactly what was folded.

    Returns the lines to PRINT, because a fold nobody is told about is the silent discard
    this function exists not to be."""
    rounds = list(st.get("rounds") or [])
    if len(rounds) <= 1:
        return []
    recorded = [r for r in rounds if r.get("recorded")]
    live = recorded[-1] if recorded else rounds[0]
    resolved: dict = {}
    verdicts: dict = {}
    for r in rounds:                       # ascending, so the later round's verdict wins
        resolved.update(r.get("resolved") or {})
        verdicts.update(r.get("verdicts") or {})
    struck = set(resolved)
    blocking = list(live.get("blocking") or [])
    carried = []
    for r in rounds:
        if r is live:
            continue
        for entry in r.get("blocking") or []:
            if finding_id(entry) in struck or entry in blocking:
                continue
            blocking.append(entry)
            carried.append(entry)
    survivor = dict(live)
    survivor["n"] = 1
    survivor["blocking"] = blocking
    survivor["advisory"] = list(live.get("advisory") or [])
    survivor["verdicts"] = verdicts
    survivor["resolved"] = resolved
    st["rounds"] = [survivor]
    st.setdefault("superseded_rounds", []).extend([r for r in rounds if r is not live])
    out = [f"NOTE: this work dir carried {len(rounds)} QA rounds, which this design does not "
           f"have. Folded into ONE round - nothing discarded:",
           f"  kept round {live.get('n', '?')}'s {len(live.get('advisory') or [])} advisory "
           f"finding(s) as the live list (a fresh reviewer judged the CURRENT artefact)"]
    if carried:
        out.append(f"  carried {len(carried)} UNRESOLVED blocking finding(s) forward from the "
                   f"superseded round(s) - they still block until a repair is recorded")
    out.append(f"  kept {len(resolved)} recorded repair(s); the superseded rounds are "
               f"preserved verbatim under `superseded_rounds` in qa_state.json")
    return out



def cmd_qa_round(args) -> int:
    work = Path(args.work)
    st = _qa_load(work)
    n = len(st["rounds"])

    def _snapshot(round_no: int) -> None:
        """Capture this round's BEFORE, once. (B44)

        Nothing retained a pre-fix canonical: the freeze marker is a bare sha256, and
        canonical_review.json is overwritten by every freeze - so the moment the round-1 fix is
        re-frozen (which `record` explicitly instructs) the twin becomes the AFTER and round 1's
        data is unrecoverable. B18 made that refresh eager on purpose, to kill a stale twin; this
        is the cost of that, paid back. STRIPPED, because an unstripped copy is tens of MB.
        Create-once, so a repeated `open` cannot overwrite the before with the after."""
        snap = work / f"canonical_review.round{round_no}.json"
        if snap.exists():
            return
        try:
            C.emit_review_view(work / "canonical.json", dest=snap)
        except Exception:
            pass

    if args.mode == "status":
        print(f"REVIEW-PASS: {n}")
        last = st["rounds"][-1] if st["rounds"] else {}
        print(f"BLOCKING: {len(last.get('blocking') or [])}")
        print(f"ADVISORY-CARRIED: {len(qa_carried(work))}")
        # BLOCKING-OPEN replaces the old ADJUDICATION-OPEN: with no adjudication round, the
        # question is simply which blocking findings the orchestrator has not yet recorded a
        # repair for. That is what final_gate blocks on.
        open_b = qa_blocking_open(work)
        print(f"BLOCKING-OPEN: {len(open_b)}")
        # F28: THE IDS AND THE FINDINGS, which is what exit 15 sends the operator here for.
        # Its handoff and SKILL.md both say "ids + findings: `qa-round status`", and until now
        # this printed four counts and nothing else. `record` does print the ids, but the SPINE
        # runs `record` itself in quiet mode, so that output never reached anyone; on the live
        # run the only way to close the exit-15 loop was to import gate_runner and call
        # finding_id() by hand on every entry in qa_state.json. Whole findings, untruncated:
        # this is the one place the operator is sent to READ them, and the 110-character cut
        # `record` uses is what sent them to the JSON.
        for e in open_b:
            print(f"  BLOCKING {e['id']}  {e['finding']}")
        struck = {k for r in st["rounds"] for k in (r.get("resolved") or {})}
        for entry in last.get("blocking") or []:
            fid = finding_id(entry)
            if fid in struck:
                print(f"  RESOLVED {fid}  {str(entry)}")
        for entry in qa_carried(work):
            print(f"  ADVISORY {finding_id(entry)}  {str(entry)}")
        if open_b:
            print(f"NEXT: fix each BLOCKING finding above, then `qa-round resolve --work <work> "
                  f"--id <id> --because \"<what you changed>\"` for each, then re-run.")
        return 0

    if args.mode == "resolve":
        # NARROW BY DESIGN, AND THE REASON MOVED. `resolve` is a claim that the finding is
        # now FALSE of the artefact, never "we got round to it". The default for an advisory
        # is still to SHIP DISCLOSED - that is how an advisory is closed - so nothing here
        # invites working the list. What it does allow, and must, is the operator's own
        # judgement call: an advisory that is ONE EDIT and changes what a reader CONCLUDES
        # gets fixed, and a fixed finding has to be strikeable or the delivered Gaps Report
        # asserts a defect the pack no longer has (the B9 failure, in the one document whose
        # job is honesty). This used to be justified as keeping the unbounded ask loop shut;
        # that argument now belongs to a mechanism that no longer exists. The loop needed a
        # SECOND REVIEW ROUND to close over - fix, re-review, find one more - and there is no
        # second round to close over any more: the reviewers are spawned once, the round is
        # recorded once, and re-recording folds into it. There is deliberately NO threshold
        # for "cheap and material"; it is a judgement, it stays with the operator, and the
        # guard that carries the meaning is unchanged: the id must name a finding actually
        # raised in this window, and a >= 20-character reason goes into the audit trail. (B26)
        recorded = [r for r in st["rounds"] if r.get("recorded")]
        if not recorded:
            print("[FAIL] no recorded QA round - run `qa-round record` first")
            print("STATUS: BLOCKED")
            return 1
        cur = recorded[-1]
        fid = (getattr(args, "id", "") or "").strip().lower()
        # BLOCKING findings are resolvable too (B44). Before, only an advisory could be resolved -
        # but the mandatory repair AFTER adjudication is by definition against a BLOCKING finding
        # that came back `not fixed`, and it has to be recordable without a third review. That is
        # what makes "fix it, then ship without check" a decision rather than a hole: the fingerprint
        # guard means it cannot be cleared without actually changing an artefact.
        _pool = list(cur.get("advisory") or []) + list(cur.get("blocking") or [])
        for _r in st["rounds"]:                    # ...including the round the finding was RAISED in
            _pool += list(_r.get("blocking") or [])
        target = next((e for e in _pool if finding_id(e) == fid), None)
        if target is None:
            print(f"[FAIL] no finding with id {ascii(fid)} in this QA window")
            for e in cur.get("advisory") or []:
                print(f"  ADVISORY {finding_id(e)}  {str(e)[:110]}")
            for e in dict.fromkeys(x for r in st["rounds"] for x in (r.get("blocking") or [])):
                print(f"  BLOCKING {finding_id(e)}  {str(e)[:110]}")
            print("STATUS: BLOCKED")
            return 1
        because = " ".join((getattr(args, "because", "") or "").split())
        if len(because) < 20:
            print("[FAIL] --because must state WHY the finding is now false (>= 20 chars). "
                  "A resolve is a claim about the artefact, not a dismissal.")
            print("STATUS: BLOCKED")
            return 1
        # NO ARTEFACT-FRESHNESS GUARD (B9). It used to refuse unless the artefact had moved since
        # THIS round's fingerprint - and the fingerprint was stamped after the repairs, so by the
        # time you knew a finding was addressed the baseline already contained the fix and `resolve`
        # was unreachable in the documented order. The consequence was not cosmetic: a delivered
        # Gaps Report shipped a "Known limitations" line asserting a defect the pack no longer had,
        # contradicting the corrections block in the same document. The remaining guards are the
        # ones that carry meaning: the id must name a finding actually raised in this window, and a
        # >=20-character reason must be written into the audit trail.
        now = _artefact_fingerprint(work)
        cur.setdefault("resolved", {})[fid] = {"finding": target, "because": because,
                                               "fingerprint": now}
        _qa_save(work, st)
        print(f"OK resolved {fid}: {str(target)[:110]}")
        print(f"  because: {because[:200]}")
        print(f"CARRIED: {len(qa_carried(work))}")
        print("NEXT: it is struck from the Gaps Report's 'Known limitations'. Re-run "
              "deliver.py so the delivered report matches the recorded round.")
        return 0

    # mode == "record": read the REVIEWERS' OWN labels out of reviews/*.md.
    # RECORDING NO LONGER OPENS THE NEXT ROUND, and that removal is the point. It used to
    # append a fresh round whenever the last one was already recorded, so a normal run cost
    # one command per round instead of two. The saving was real; what it bought was a
    # mechanism this phase may not have. The required shape is: spawn the independent
    # reviewers ONCE, implement every blocking finding plus any advisory that is cheap and
    # material, deliver. A second review round is never correct. The only thing standing
    # between `record` and one was the arithmetic `len(rounds) < QA_MAX_ROUNDS`, and
    # arithmetic is the wrong kind of guard for a structural rule: raise the constant, or
    # arrive with a window that already holds two rounds, and the second round is back.
    # There is now ONE round slot; `record` writes into it, and a review file that changes
    # after the round is recorded FOLDS into it as additional findings (the reviews read
    # below) instead of opening another.
    if not st["rounds"]:
        st["rounds"].append({"n": 1, "blocking": [], "advisory": [], "verdicts": {}})
    # THE ONE-ROUND INVARIANT, ENFORCED RATHER THAN COUNTED DOWN. QA_MAX_ROUNDS is 1 and is
    # now a CHECKED invariant instead of a budget. An older work dir may legitimately carry
    # two or three rounds, and folding them - honestly, discarding nothing - is what makes a
    # second round impossible without crashing on state somebody's run really produced.
    _folded = _coalesce_rounds(st) if len(st["rounds"]) > QA_MAX_ROUNDS else []
    cur = st["rounds"][0]
    cur["n"] = 1
    _snapshot(1)  # BEFORE, captured once: `record` opens the single round itself
    cur["recorded"] = True
    # "required" was PROSE ONLY: argparse defaults --reviews to "", Path("") is ".", and "." exists
    # - so `qa-round record --work W` with no --reviews globbed the CURRENT DIRECTORY, found no
    # verdicts, and still marked the round recorded. That is a zero-finding round that wipes every
    # carried limitation and prints "no blocking findings ... DELIVER": a silent false clear. (B44)
    if not args.reviews:
        print("[FAIL] --reviews is required for `record` and must name the reviews ROOT directory")
        print("STATUS: BLOCKED")
        return 1
    rroot = Path(args.reviews)
    if not rroot.is_dir():
        print(f"[FAIL] reviews dir not found: {rroot}")
        print("STATUS: BLOCKED")
        return 1
    # EVERY ROUND DIRECTORY, FOLDED INTO THE ONE ROUND. `reviews/round<N>/` is a DISPATCH
    # token, not a review round - `review_round_dirs` says so in its own docstring: N is a
    # uniqueness token the orchestrator supplies, never derived from qa_state.json. A
    # reviewer re-dispatched because its file came back garbled MUST write a new file, or the
    # harness would make an ostensibly independent agent read the previous verdict first
    # (B24), so one review round legitimately spans round1/ AND round2/.
    #
    # THIS IS THE INCIDENT THE DRIVER'S FINGERPRINT GUARD WAS WRITTEN FOR, now closed on
    # this side too. Reading only `review_dir_for(rroot, cur["n"])` meant round1/ was the
    # only directory ever read: a re-dispatched review landed in round2/,
    # `run.qa_reviews_changed` correctly fired, `record` re-ran, read round1/ again, found
    # nothing new and STAMPED - so the findings in round2/ were recordable by no pass and the
    # run could exit over an unread blocking finding. Ascending order, so a re-dispatched
    # gate's verdict WORD wins (the same highest-round-first resolution `review_file` uses)
    # while its FINDINGS are additive: a finding is struck only by an explicit `qa-round
    # resolve`, never by a later dispatch's silence.
    #
    # The flat root stays supported permanently as round 0 for work dirs predating the
    # layout, and ONLY when no round dir exists - reading both would double-count a gate
    # whose verdict sits in each.
    rdirs = [d for _rd_n, d in review_round_dirs(rroot)] or [rroot]
    # final_gate owns the verdict grammar and imports THIS module, so the import must be lazy
    # (module-level would be circular). A missing parser must not lose the findings, only the
    # verdict words, so it degrades to None rather than raising.
    try:
        from final_gate import parse_verdict as _parse_verdict
    except Exception:
        def _parse_verdict(_t):
            return None
    n_b = n_a = n_unlabelled = 0
    for f in [q for d in rdirs for q in sorted(d.glob("*.md"))]:
        txt = f.read_text(encoding="utf-8", errors="replace")
        gate_name = f.stem
        word = _parse_verdict(txt)
        if word:
            cur["verdicts"][gate_name] = word
        seen_bodies: set = set()
        for m in _FINDING_RE.finditer(txt):
            label = (m.group("l1") or m.group("l2")).lower()
            body = m.group("body").strip()
            bucket = "blocking" if label == "blocking" else "advisory"
            entry = f"{gate_name}: {body}"
            seen_bodies.add(body)
            if entry not in cur[bucket]:
                cur[bucket].append(entry)
            n_b, n_a = (n_b + 1, n_a) if bucket == "blocking" else (n_b, n_a + 1)
        # the ESTABLISHED `- [HIGH|MED|LOW]` format counts too: HIGH is the reviewer's own "this
        # blocks", MED/LOW/ENV its own "this does not". Still the REVIEWER's judgement - we read
        # the severity they chose, we do not inspect the issue text. Skipped when the same line
        # already carried an explicit blocking:/advisory: label.
        for m in _SEVERITY_RE.finditer(txt):
            sev, body = m.group(1).lower(), m.group(2).strip()
            if body in seen_bodies:
                continue
            bucket = _SEVERITY_BUCKET.get(sev, "advisory")
            entry = f"{gate_name}: [{sev.upper()}] {body}"
            if entry not in cur[bucket]:
                cur[bucket].append(entry)
            n_b, n_a = (n_b + 1, n_a) if bucket == "blocking" else (n_b, n_a + 1)
    # THE ROUND-TO-ROUND CARRY-FORWARD IS GONE, because the read above SUBSUMES it. It
    # existed for exactly one shape: under a scoped re-review only the gates that raised
    # blocking findings are re-dispatched, so round 2's directory holds nothing for the
    # others, and reading only round 2 silently retired a not-re-dispatched gate's advisories
    # - a change to what ships in Known limitations, disguised as a path fix (B24/B26).
    # Folding EVERY round dir into the one round answers that from the source files instead:
    # a gate that was not re-dispatched still has its round1/ file, so its advisories are
    # RE-INGESTED each pass rather than copied forward from a previous round's list. That is
    # strictly the more honest of the two - the finding is read off the reviewer's own words
    # every time, never inherited - and it is what makes "a changed review file folds into
    # this round" and "there is never a second round" one statement rather than two. A
    # finding the improvement pass made false is still struck the only way it has ever been
    # struck: an explicit `qa-round resolve`, with its reason on the record.
    cur["fingerprint"] = _artefact_fingerprint(work)
    _qa_save(work, st)
    _n = len(st["rounds"])
    for _fold_line in _folded:     # say what the fold did BEFORE the counts it changed
        print(_fold_line)
    print(f"OK recorded {n_b} blocking, {n_a} advisory finding(s) "
          f"(reviews read from {', '.join(d.name for d in rdirs)})")
    # Print each advisory's id: it is the handle `qa-round resolve --id` needs, and an
    # id the orchestrator never saw is an id it cannot misuse.
    # B60: SKILL.md tells the orchestrator to hand the adjudicator "the blocking finding list WITH
    # ITS IDS (printed by `record`)". Only the advisory ids were ever printed, so the ids had to
    # be derived by importing gate_runner and calling finding_id() by hand - a step the docs
    # assume is already done.
    for entry in cur["blocking"]:
        print(f"  BLOCKING {finding_id(entry)}  {str(entry)[:110]}")
    for entry in cur["advisory"]:
        print(f"  ADVISORY {finding_id(entry)}  {str(entry)[:110]}")
    # P5: feed the cross-run flywheel and surface any class that has recurred across runs -
    # the signal that a review finding should become a mechanical gate. Best-effort; a ledger
    # failure never blocks the round.
    for _nudge in flywheel_append(work, cur):
        print(_nudge)
    # B60: which enrichment layers were in force when these verdicts were written. final_gate
    # compares it later and says so if a layer was enabled afterwards.
    cur["enrichment"] = enrich_signature(work)
    _qa_save(work, st)
    print(f"REVIEW-PASS: {_n}")
    print(f"BLOCKING: {len(cur['blocking'])}")
    # tell the orchestrator what to DO, so it never has to reason its way to another command
    if cur["blocking"]:
        print(f"NEXT: IMPLEMENT these {len(cur['blocking'])} blocking finding(s), then record "
              f"each one with `qa-round resolve --id <id> --because \"<what you changed>\"`, "
              f"then DELIVER. There is no second review pass: the reviewers proposed, you "
              f"implement, and final_gate checks that every blocking finding was addressed. "
              f"Do NOT re-dispatch the reviewers - fixing a blocking finding is a loop WITHIN "
              f"this one round, and a second review round is never correct.")
    else:
        print("NEXT: no blocking findings - run final_gate.py --qa-state and DELIVER. Do NOT "
              "re-review a clean gate, and do NOT fix advisory findings (they are carried to the "
              "Gaps Report automatically).")
    # B60: the order is load-bearing. `resolve` compares against the snapshot taken RIGHT NOW, so
    # a fix applied before this command is invisible to it.
    print("ORDER: record -> implement -> resolve -> deliver -> final_gate. `resolve` no longer "
          "requires the artefact to have moved since this command, so fixing before or after "
          "recording both work.")
    return 0


# --------------------------------------------------------------------------- #
def main() -> None:
    # D16: every subcommand here prints finding text verbatim (reviewer findings, ledger values,
    # brochure strings), so on a cp1252 console the first glyph outside the code page turned the
    # findings into a traceback (`qa-round status`, U+2265). Set once, defensively, here.
    C.force_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate-data"); p.add_argument("canonical"); p.set_defaults(fn=cmd_validate_data)
    p = sub.add_parser("self-check"); p.set_defaults(fn=cmd_self_check)
    p = sub.add_parser("coverage"); p.add_argument("canonical")
    p.add_argument("--fill-threshold", type=float, default=0.6); p.set_defaults(fn=cmd_coverage)
    p = sub.add_parser("validate-html"); p.add_argument("html"); p.add_argument("--canonical", required=True)
    p.set_defaults(fn=cmd_validate_html)
    p = sub.add_parser("reconcile"); p.add_argument("html"); p.add_argument("--canonical", required=True)
    p.set_defaults(fn=cmd_reconcile)
    p = sub.add_parser("i18n"); p.add_argument("html"); p.add_argument("--canonical", required=True)
    p.set_defaults(fn=cmd_i18n)
    p = sub.add_parser("trace-coverage"); p.add_argument("canonical"); p.add_argument("--ledger", required=True)
    p.set_defaults(fn=cmd_trace_coverage)
    p = sub.add_parser("images"); p.add_argument("canonical"); p.set_defaults(fn=cmd_images)
    # B08: its OWN subcommand, not a section inside `coverage` - coverage is canonical-only and
    # final_gate runs it without a work dir, so folding this in would force a --work onto it.
    p = sub.add_parser("coord-provenance",
                       help="a town-centre pin while the property's own page carries the "
                            "author's coordinates or map link")
    p.add_argument("canonical")
    p.add_argument("--work", default="")
    p.add_argument("--ledger", default="")
    p.set_defaults(fn=cmd_coord_provenance)
    p = sub.add_parser("value-format",
                       help="a field must be WRITTEN the same way on every property that has it "
                            "(one bare '5000' among twelve '10,000 sq. m')")
    p.add_argument("canonical")
    p.add_argument("--min-siblings", type=int, default=2,
                   help="how many written siblings before a bare value is called out (default 2)")
    p.add_argument("--emit-json", dest="emit_json", default="",
                   help="write machine-readable findings here (run.py's clarify bridge)")
    p.add_argument("--waivers", default="",
                   help="JSON list of {field,id} the broker declined (exit 13) - shipped bare, "
                        "noted, never blocked")
    p.add_argument("--ledger", default="",
                   help="source ledger to join, so measured siblings vote once per SOURCE FILE "
                        "rather than per record (default: source_ledger.csv beside the canonical)")
    p.set_defaults(fn=cmd_value_format)
    p = sub.add_parser("capture-symmetry",
                       help="ADVISORY: fields captured from one source deck but from none of "
                            "another - the cheap signal that a reader skipped stated rows")
    p.add_argument("--work", required=True)
    p.add_argument("--max-notes", type=int, default=25)
    p.set_defaults(fn=cmd_capture_symmetry)
    p = sub.add_parser("media-harvest",
                       help="did the run HARVEST the media its sources hold - BLOCKS on a lost "
                            "media capability or an interpretation agent handed no page renders "
                            "(both hard facts, ack-able); ADVISORY on a property that read one "
                            "page of a whole deck and on orphan deck pages")
    p.add_argument("canonical")
    p.add_argument("--work", required=True)
    p.add_argument("--max-notes", type=int, default=25)
    p.set_defaults(fn=cmd_media_harvest)
    p = sub.add_parser("ack",
                       help="MERGE a key into placeholder_audit_ack.json (the only concurrency-"
                            "safe way to write it - authoring it whole loses a parallel agent's "
                            "key)")
    p.add_argument("--work", required=True)
    p.add_argument("--add", action="append", metavar="KEY=V1[,V2]",
                   help="union these values into KEY (repeatable), e.g. "
                        "--add nonphoto_hero_ok=8,9 --add arithmetic_ok=25")
    p.add_argument("--note", default="", help="append a sentence to the file's `note`")
    p.add_argument("--verified-by", default="", help="set `verified_by`")
    p.set_defaults(fn=cmd_ack)
    p = sub.add_parser("input-accounting",
                       help="every discovered input is accounted for (nothing vanishes)")
    p.add_argument("canonical"); p.add_argument("--work", required=True)
    p.set_defaults(fn=cmd_input_accounting)
    # B52: needs BOTH the work dir (the manifest's page text) and the ledger (the locator each
    # value cites), so like input-accounting it is its own subcommand rather than folded into a
    # canonical-only gate that final_gate runs without a work dir.
    p = sub.add_parser("prov-containment",
                       help="a value citing a page must occur on that page")
    p.add_argument("canonical"); p.add_argument("--work", required=True)
    p.add_argument("--ledger", required=True); p.set_defaults(fn=cmd_prov_containment)
    # P1-1: its OWN subcommand rather than folded into validate-data, so the scorecard line names
    # the arithmetic and the remedy is independent of every schema check.
    p = sub.add_parser("arithmetic", help="derived GLA vs the source's own stated total area")
    p.add_argument("canonical"); p.set_defaults(fn=cmd_arithmetic)
    p = sub.add_parser("enrichment"); p.add_argument("canonical")
    p.add_argument("--requested", default="", help="comma-separated layers the broker "
                   "REQUESTED (geocode,pois,osrm,regions) - a requested layer that left "
                   "NO enrichment record means the stage crashed/was skipped (P2-9)")
    p.set_defaults(fn=cmd_enrichment)
    p = sub.add_parser("translation"); p.add_argument("canonical")
    p.add_argument("--work", required=True); p.add_argument("--lang", default="English")
    p.set_defaults(fn=cmd_translation)
    p = sub.add_parser("qa-round", help="the QA window: reviewers propose, orchestrator implements, "
                                        "deliver")
    p.add_argument("mode", choices=["record", "status", "resolve"])
    p.add_argument("--work", required=True)
    p.add_argument("--reviews", default="", help="reviews dir (required for `record`). "
                   "Round-scoped: reviews/round<N>/<gate>.md, the flat root = round 0")
    p.add_argument("--id", default="", help="`resolve`: the finding id, BLOCKING or ADVISORY, "
                   "as printed by `qa-round status` (and by `record`)")
    p.add_argument("--because", default="", help="`resolve`: why the finding is now FALSE of "
                   "the artefact - for a blocking finding, what you changed (>= 20 chars, "
                   "recorded in qa_state.json)")
    p.set_defaults(fn=cmd_qa_round)
    p = sub.add_parser("freeze"); p.add_argument("file")
    p.add_argument("--check", action="store_true", help="verify the file is byte-identical to the freeze snapshot")
    p.set_defaults(fn=cmd_freeze)

    p = sub.add_parser("flywheel", help="cross-run recurring finding classes -> gate candidates "
                                        "(the finding-to-gate flywheel; P5)")
    p.set_defaults(fn=cmd_flywheel)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
