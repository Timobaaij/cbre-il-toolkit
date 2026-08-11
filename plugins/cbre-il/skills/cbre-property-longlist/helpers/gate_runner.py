#!/usr/bin/env python3
"""gate_runner.py - mechanical (script) halves of the QA gates.

Subcommands (judgement halves run as isolated reviewer sub-agents, not here):
  PRE-BUILD:
    validate-data   G-schema     : canonical.json valid against the schema + pair-consistency
    self-check      G-selfcheck  : schema field set == tokens/markers the template/build use
    coverage        G-coverage   : no dup (park+city+dev+area); per-record core-field fill or explicit tbd
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
def _cov_filled(v) -> bool:
    """A field counts as populated for coverage: present and not a sentinel.
    Includes negative numbers (western/southern lat/lng) and zero - only
    'tbd'/'—'/''/None are empty. Matches the original populated-field test."""
    return v is not None and str(v).strip().lower() not in {"tbd", "—", "none", ""}


def _is_land_record(p: dict) -> bool:
    """Land/plot-for-sale option, detected STRUCTURALLY (no language tokens, so it
    holds in any market): no real warehouse area, but a plot area or a land price.
    Such a site has no warehouse rent/specs by nature, so coverage scores it on
    land-appropriate fields instead of failing it for missing warehouse data."""
    has_wh = isinstance(p.get("warehouseArea"), (int, float)) and p["warehouseArea"] > 0
    has_land = _cov_filled(p.get("plotArea")) or _cov_filled(p.get("landPrice"))
    return (not has_wh) and has_land


WAREHOUSE_CORE = ["warehouseArea", "warehouseRent", "status", "city", "developer", "lat", "lng"]
LAND_CORE = ["plotArea", "landPrice", "city", "lat", "lng"]


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
    demonstrably reached the client."""
    inv, led_src, unread = {}, set(), {}
    try:
        inv = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
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
        for e in json.loads((work / "unreadable.json").read_text(encoding="utf-8")) or []:
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
            obj = json.loads((work / f).read_text(encoding="utf-8"))
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
    for rel in sorted(set(files)):
        nm = Path(rel).name.lower()
        if nm in led_src:
            out["records"].append(rel)
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
_PROV_TOKEN_RE = re.compile(r"[A-Za-z]{4,}")
_PROV_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _prov_tokens(s) -> set:
    """Distinctive lowercase tokens. Short tokens and pure numbers collide far too easily to be
    evidence, so only alphabetic runs of 4+ characters count."""
    return {t.lower() for t in _PROV_TOKEN_RE.findall(str(s or ""))}


def _prov_flat(s) -> str:
    """Lowercase, alphanumerics only - EVERY separator removed.

    Marketing PDFs letter-space their headings, so the extractor legitimately returns
    'UNI T 1 WOR K S O P LI NK' and 'ULTRA BOX'. Comparing word-for-word flagged both as
    fabrications on a real run. Flattening both sides makes 'worksop' and 'ultrabox' match the
    text that genuinely contains them, while a value that is simply NOT in the document still
    fails to appear."""
    return _PROV_STRIP_RE.sub("", str(s or "").lower())


def _prov_page_text(work) -> dict:
    """{(source_file.lower(), 1-based page): text} for TEXT-mode decks only.

    A raster deck has no text layer, so it is omitted and every value citing it is skipped - the
    gate must never form an opinion it has no evidence for."""
    out: dict = {}
    try:
        decks = json.loads((Path(work) / "vision" / "manifest.json")
                           .read_text(encoding="utf-8")).get("decks", [])
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
    never a block."""
    import csv as _csv
    pages = _prov_page_text(args.work)
    if not pages:
        _ok("no deck text to verify against (raster-only, tracker-only, or no manifest)")
        print("STATUS: ALL-PASS")
        return 0
    try:
        with open(args.ledger, newline="", encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
    except Exception as e:
        _ok(f"ledger unreadable ({e}) - nothing to verify")
        print("STATUS: ALL-PASS")
        return 0
    bad, soft, checked = [], [], 0
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
        if missing:
            field = (r.get("field") or "").strip()
            (bad if field in PROV_BLOCK_FIELDS else soft).append(
                (r.get("property_id"), field, r.get("value"), loc, missing))
    for pid, field, val, loc, missing in soft:
        print(f"  [note] property={pid} field={field}: {str(val)[:52]!r} is cited to "
              f"{loc[:40]!r} but {', '.join(repr(x) for x in missing[:3])} "
              f"appear{'s' if len(missing) == 1 else ''} nowhere on that page. Advisory: a scheme "
              f"name is often cover artwork or composed across pages, so this is a locator to "
              f"tighten, not proof of invention.")
    for pid, field, val, loc, missing in bad:
        _bad(f"property={pid} field={field}: value {str(val)[:60]!r} is cited to {loc[:46]!r} "
             f"but {', '.join(repr(x) for x in missing[:4])} "
             f"appear{'s' if len(missing) == 1 else ''} nowhere on that page. Either the value is "
             f"not from that source (strike it to 'tbd', or cite the real locator), or it was read "
             f"from an image - in which case append '{PROV_NOT_IN_TEXT}' to its provenance.")
    if bad:
        print("STATUS: BLOCKED")
        return 1
    _ok(f"every page-cited value occurs on its cited page ({checked} checked, "
        f"{len(soft)} advisory)")
    print("STATUS: ALL-PASS")
    return 0


def cmd_input_accounting(args) -> int:
    """Reconcile every discovered INPUT against what actually shipped. (B08)"""
    work = Path(args.work)
    b = _accounting_buckets(work, Path(args.canonical))
    total = sum(len(v) for v in b.values())
    _ok(f"{total} input(s): {len(b['records'])} contributed fields, "
        f"{len(b['photo'])} contributed a photo only, {len(b['unreadable'])} unreadable/skipped, "
        f"{len(b['no_consumer'])} have no consumer in the spine")
    for rel in b["no_consumer"]:
        print(f"  [note] {rel}: loose image - no spine consumer reads it (extract_image.py "
              f"is not wired in). Not a defect in this run; it is simply not in the dashboard.")
    if b["unaccounted"]:
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
            for deck in (json.loads(man.read_text(encoding="utf-8")).get("decks") or []):
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
    by_field: dict[str, dict] = {}
    for p in props:
        for k, v in p.items():
            if k in _PIPELINE_ASSIGNED or _absent(v):
                continue
            if isinstance(v, (dict, list)):
                continue
            slot = by_field.setdefault(k, {"bare": [], "measured": []})
            if isinstance(v, bool):
                continue
            s = str(v).strip()
            if isinstance(v, (int, float)) or _BARE_NUMBER.match(s):
                slot["bare"].append((p.get("id"), s))
                continue
            unit = _unit_of(s)
            if unit:
                slot["measured"].append((p.get("id"), s, unit))
    findings = []
    for field, slot in sorted(by_field.items()):
        if not slot["bare"] or len(slot["measured"]) < args.min_siblings:
            continue                 # consistent field, or too little evidence to call it
        # a DOMINANT unit is required: a field whose measured values disagree about their own
        # unit is a different (and worse) problem, and guessing which one the bare value meant
        # would be the invention this gate exists to prevent.
        units = [u for _, _, u in slot["measured"]]
        top = max(set(units), key=units.count)
        if units.count(top) * 2 < len(units):
            continue
        findings.append((field, slot["bare"], slot["measured"], top))
    for field, bare, measured, top in findings:
        examples = ", ".join(f"'{v}'" for _, v, _ in measured[:3])
        offenders = ", ".join(f"id={i} '{v}'" for i, v in bare[:6])
        _bad(f"`{field}`: {len(bare)} property(ies) ship a BARE number while "
             f"{len(measured)} write it as a magnitude + unit ({top!r}) - {offenders} "
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
    """
    work = Path(args.work)
    by_source: dict[str, dict] = {}
    for path in sorted((work / "extract").glob("*.json")):
        try:
            recs = json.loads(path.read_text(encoding="utf-8"))
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
            for k, v in rec.items():
                if k == "__meta" or k in _PIPELINE_ASSIGNED:
                    continue
                if not _absent(v):
                    slot["fields"].add(k)
    sources = {s: d for s, d in by_source.items() if d["n"]}
    if len(sources) < 2:
        _ok(f"capture symmetry not applicable ({len(sources)} source(s) with records)")
        print("STATUS: ALL-PASS")
        return 0
    everywhere = sorted(set().union(*(d["fields"] for d in sources.values())))
    findings = []
    for field in everywhere:
        have = sorted(s for s, d in sources.items() if field in d["fields"])
        miss = sorted(s for s, d in sources.items() if field not in d["fields"])
        if have and miss:
            findings.append((len(have), field, have, miss))
    if not findings:
        _ok(f"every field is captured symmetrically across {len(sources)} source(s)")
        print("STATUS: ALL-PASS")
        return 0
    findings.sort(key=lambda t: (-t[0], t[1]))
    shown = findings[: args.max_notes]
    for _, field, have, miss in shown:
        print(f"  [note] `{field}` captured from {', '.join(have)} but from NONE of "
              f"{', '.join(miss)} - confirm those deck(s) genuinely do not state it, "
              f"rather than the reader having skipped the row")
    if len(findings) > len(shown):
        print(f"  [note] ... and {len(findings) - len(shown)} more asymmetric field(s)")
    _ok(f"{len(findings)} cross-source field asymmetry note(s) across {len(sources)} "
        f"source(s) - ADVISORY, for the G-honesty/G-trace reviewers to re-derive")
    print("STATUS: ALL-PASS")
    return 0


# fields merge/enrich ASSIGN, so their absence from a reader's record means nothing
_PIPELINE_ASSIGNED = frozenset({
    "id", "photo", "plan", "gallery", "preBaked", "regionCode", "coordsApprox",
    "officeAreaVal", "officeRentVal", "expansionParkVal",
})


def _absent(v) -> bool:
    if v is None:
        return True
    return str(v).strip().lower() in ("", "tbd", "tbc", "—", "-", "??", "n/a")


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

    # per-record core fill OR explicit tbd - core set chosen by record kind so a
    # land/plot listing is not failed for lacking warehouse fields it never has
    for p in props:
        land = _is_land_record(p)
        core = land_core if land else wh_core
        filled = sum(1 for f in core if _cov_filled(p.get(f)))
        frac = filled / len(core)
        if frac < threshold:
            empties = [f for f in core if not _cov_filled(p.get(f))]
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
    actual = Path(args.html).read_text(encoding="utf-8")
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
    html = Path(args.html).read_text(encoding="utf-8")
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
    html = Path(args.html).read_text(encoding="utf-8")
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
        # hero_lede_fmt's {count} is deliberately an ADVISORY NOTE, not an issue. The two
        # clauses above guard a CRASH (compute_kpis .format()s them); losing {count} only
        # costs the lede its property count, and build_dashboard._hero_copy already
        # self-heals to the EN string. Blocking here would be an UNCLEARABLE exit 7 for a
        # bundled language: cmd_i18n runs POST-build, and a bundled pack is a shipped,
        # integrity-tracked asset with no runtime override - the only "remedy" would be
        # hand-editing it, which SKILL.md forbids. evals/i18n_test.py is the dev-time
        # tripwire that catches a pack losing it.
        if "{count}" not in str(ui.get("hero_lede_fmt", "")):
            print("  [note] hero_lede_fmt lost its {count} placeholder in the resolved UI - "
                  "the lede falls back to the English default so it still states the count; "
                  "fix the pack's hero_lede_fmt when convenient (advisory, not blocking)")

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

    def is_sentinel(v):
        return v is None or str(v).strip().lower() in {"tbd", "—", "", "none", "??", "?"}

    # fields a real source must back; excludes structural/derived/enriched keys
    # identity fields (developer/city/park/country) must trace to a source too - a
    # fabricated identity is as damaging as a fabricated spec (audit S4-14); a
    # gap-documented unknown (e.g. country '??') is a sentinel, skipped above.
    check = (set(C.STRING_FIELDS)
             | {"warehouseArea", "warehouseRentVal", "plotArea",
                "developer", "city", "park", "country"})
    issues = []
    for p in data.get("properties", []):
        pid = str(p.get("id"))
        for f in check:
            if f in p and not is_sentinel(p.get(f)) and (pid, f) not in traced:
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
            ack = json.loads(ack_file.read_text(encoding="utf-8")) or {}
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
    for h, ids in sorted(groups.items()):
        if len(ids) >= 2 and h not in dup_ok:
            issues.append(
                f"{len(ids)} properties (ids {ids}) share ONE IDENTICAL hero photo "
                f"(hash {h}) - a near-certain harvest failure; have the G-images "
                f"reviewer check the contact sheet, fix the harvest (or, only if "
                f"genuinely correct, record {{\"duplicate_photos_ok\": [\"{h}\"]}} "
                f"in {ack_file.name})")
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
        if side.read_text(encoding="utf-8").strip() != sha:
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
            req = json.loads(reqp.read_text(encoding="utf-8"))
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
            ack = json.loads(ack_file.read_text(encoding="utf-8")) or {}
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
_FINDING_RE = re.compile(r"^\s*-\s*\[?(blocking|advisory)\]?\s*:?\s*(.+)$", re.I | re.M)
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
# `- <id>: fixed | not fixed | made worse [- note]` - the adjudicator's per-finding verdict. (B44)
_ADJ_RE = re.compile(
    r"^\s*[-*]?\s*\**\s*(q?[0-9a-f]{8,12})\**\s*[:=]\s*\**\s*"
    r"(fixed|not\s+fixed|made\s+worse|unfixed|broken)\**\s*(?:[-–:]\s*(.*))?$",
    re.I | re.M)


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


_DIFF_MEDIA_KEYS = ("photo", "plan", "gallery", "images")
_DIFF_SUMMARISE = ("preBaked", "distances", "enrichment", "pois", "regions")


def _diff_short(v) -> str:
    """A value rendered for a human, short. Media is reduced to an identity, never a payload."""
    import hashlib
    if isinstance(v, str):
        if v.startswith("data:"):
            return f"<image {hashlib.sha256(v.encode()).hexdigest()[:8]}>"
        return v if len(v) <= 90 else v[:87] + "..."
    if isinstance(v, (int, float, bool)) or v is None:
        return str(v)
    return f"<{type(v).__name__} of {len(v)}>" if isinstance(v, (list, dict)) else str(v)[:90]


def canonical_data_diff(before_path, after_path, max_lines: int = 200) -> list:
    """A FIELD-LEVEL diff of two canonical snapshots: which property, which field, old -> new.

    This is what the adjudicator is given so it can check BLAST RADIUS - whether the round-1 fix
    also moved something it should not have. A blind reviewer cannot check that, because it does
    not know what changed; that is the whole reason the adjudication pass carries context.

    DELIBERATELY STDLIB-ONLY: json + hashlib, no subprocess, no git, no import of any helper.
    That is the mechanical guarantee that it can only ever show a DATA diff - never a code diff,
    and never the author's rationale (`because` lives in qa_state.json and is not read here).
    The adjudicator judges the DELIVERABLE, not the edit.

    Media is excluded twice over, because one layer is not enough: a key denylist
    (photo/plan/gallery/images report an identity change only) AND a value backstop that does not
    depend on the key list at all (any string starting `data:`). A 12-property canonical is
    99.56% base64 by weight, so a diff that leaked one URI would be useless.

    Derived blobs are SUMMARISED rather than enumerated - a re-enrich moves ~24 POI distances per
    property, and 18 separate lines about it would bury the one line that matters. (B44)"""
    import json as _json

    def _load(p):
        try:
            d = _json.loads(Path(p).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    a, b = _load(before_path), _load(after_path)
    if not a:
        return ["(no before-snapshot for this round - nothing to diff)"]
    ap = {str(p.get("id")): p for p in (a.get("properties") or []) if isinstance(p, dict)}
    bp = {str(p.get("id")): p for p in (b.get("properties") or []) if isinstance(p, dict)}
    out: list = []
    for gone in sorted(set(ap) - set(bp)):
        out.append(f"property {gone} ({_diff_short(ap[gone].get('park'))}): REMOVED")
    for new in sorted(set(bp) - set(ap)):
        out.append(f"property {new} ({_diff_short(bp[new].get('park'))}): ADDED")
    for pid in sorted(set(ap) & set(bp), key=lambda s: (len(s), s)):
        pa, pb, rows = ap[pid], bp[pid], []
        for k in sorted(set(pa) | set(pb)):
            if k == "__meta":
                continue
            va, vb = pa.get(k), pb.get(k)
            if va == vb:
                continue
            if k in _DIFF_MEDIA_KEYS:
                rows.append(f"    {k}: image/media changed")
                continue
            if any(t in k for t in _DIFF_SUMMARISE) and isinstance(va, (dict, list)):
                n = 0
                if isinstance(va, dict) and isinstance(vb, dict):
                    n = sum(1 for kk in set(va) | set(vb) if va.get(kk) != vb.get(kk))
                rows.append(f"    {k}: derived block changed"
                            + (f" ({n} value(s))" if n else ""))
                continue
            rows.append(f"    {k}: {_diff_short(va)}  ->  {_diff_short(vb)}")
        if rows:
            out.append(f"property {pid} ({_diff_short(pb.get('park'))}):")
            out += rows
    ma, mb = a.get("meta") or {}, b.get("meta") or {}
    for k in sorted(set(ma) | set(mb)):
        if ma.get(k) != mb.get(k):
            if any(t in k for t in _DIFF_SUMMARISE) or isinstance(ma.get(k), (dict, list)):
                out.append(f"meta.{k}: changed")
            else:
                out.append(f"meta.{k}: {_diff_short(ma.get(k))}  ->  {_diff_short(mb.get(k))}")
    if not out:
        return ["(no data changed between the two snapshots)"]
    if len(out) > max_lines:
        # NEVER silently truncate - a capped list that reads as complete is the failure this
        # project has a standing lesson about.
        out = out[:max_lines] + [f"... {len(out) - max_lines} further change line(s) not shown "
                                 f"(cap {max_lines}); the artefacts themselves are authoritative"]
    return out


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
    for d in (w, w / "deliverables"):
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


def _qa_run_key(work: Path) -> str:
    """WORK DIR + the intake input hash. Deliberately independent of canonical.json's bytes."""
    import hashlib
    inv_h = ""
    try:
        inv = json.loads((Path(work) / "inventory.json").read_text(encoding="utf-8"))
        inv_h = str(inv.get("input_hash") or inv.get("folder") or "")
    except Exception:
        pass
    return hashlib.sha256(f"{Path(work).resolve()}|{inv_h}".encode()).hexdigest()[:16]


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
        args = json.loads((Path(work) / ".enrich.stamp").read_text(encoding="utf-8")).get("args")
    except Exception:
        return ""
    toks = [t.strip() for t in str(args or "").split("|")]
    return "|".join(sorted(t for t in toks if t.startswith("--")))


def _qa_load(work: Path) -> dict:
    st = {}
    try:
        st = json.loads(_qa_state_path(work).read_text(encoding="utf-8"))
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    key = _qa_run_key(work)
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
        print(f"BLOCKING-OPEN: {len(qa_blocking_open(work))}")
        return 0

    if args.mode == "resolve":
        # NARROW BY DESIGN. `resolve` says "the blocking fix made this advisory FALSE",
        # never "we got round to it". SKILL.md's doctrine stands: an advisory is closed by
        # being written into the Gaps Report, not by being fixed. Relaxing that hands an
        # eager orchestrator permission to work the advisory list, which buys back the
        # unbounded loop the QA window exists to close. Two guards keep it narrow: a real
        # reason, and proof that an artefact actually moved. (B26)
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
    # SELF-OPENING: `record` opens the next round itself when the previous one was already
    # recorded, so a normal run needs ONE command per round instead of two. (Every extra
    # mandatory shell command is paid on every run, in an environment with a ~40s cap.)
    if not st["rounds"]:
        st["rounds"].append({"n": 1, "blocking": [], "advisory": [], "verdicts": {}})
    elif st["rounds"][-1].get("recorded") and len(st["rounds"]) < QA_MAX_ROUNDS:
        st["rounds"].append({"n": len(st["rounds"]) + 1, "blocking": [], "advisory": [],
                             "verdicts": {}})
    cur = st["rounds"][-1]
    prev = st["rounds"][-2] if len(st["rounds"]) > 1 else None
    _snapshot(cur.get("n") or len(st["rounds"]))  # BEFORE, when record self-opened the round
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
    # Round-scoped: read THIS round's own directory (reviews/round<N>/), falling back to
    # the flat root as round 0 for work dirs predating the layout. (B24)
    rdir = review_dir_for(rroot, cur.get("n"))
    # final_gate owns the verdict grammar and imports THIS module, so the import must be lazy
    # (module-level would be circular). A missing parser must not lose the findings, only the
    # verdict words, so it degrades to None rather than raising.
    try:
        from final_gate import parse_verdict as _parse_verdict
    except Exception:
        def _parse_verdict(_t):
            return None
    n_b = n_a = n_unlabelled = 0
    for f in sorted(rdir.glob("*.md")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        gate_name = f.stem
        word = _parse_verdict(txt)
        if word:
            cur["verdicts"][gate_name] = word
        seen_bodies: set = set()
        for m in _FINDING_RE.finditer(txt):
            label, body = m.group(1).lower(), m.group(2).strip()
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
    # CARRY FORWARD. Under a scoped re-review only the gates that raised blocking
    # findings are re-dispatched, so round 2's directory holds nothing for the others.
    # Reading only this round would silently retire a not-re-dispatched gate's
    # advisories - a change to what ships in Known limitations, disguised as a path fix.
    # Resolved findings are NOT carried forward: they were fixed, on the record. (B24/B26)
    if prev:
        seen_gates = {f.stem for f in rdir.glob("*.md")}
        struck = set((prev.get("resolved") or {}).keys())
        for entry in prev.get("advisory") or []:
            gate = str(entry).split(":", 1)[0].strip()
            if gate in seen_gates or finding_id(entry) in struck:
                continue
            if entry not in cur["advisory"]:
                cur["advisory"].append(entry)
                n_a += 1
    cur["fingerprint"] = _artefact_fingerprint(work)
    _qa_save(work, st)
    _n = len(st["rounds"])
    print(f"OK recorded {n_b} blocking, {n_a} advisory finding(s) "
          f"(reviews read from {rdir.name})")
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
              f"implement, and final_gate checks that every blocking finding was addressed.")
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
    p.set_defaults(fn=cmd_value_format)
    p = sub.add_parser("capture-symmetry",
                       help="ADVISORY: fields captured from one source deck but from none of "
                            "another - the cheap signal that a reader skipped stated rows")
    p.add_argument("--work", required=True)
    p.add_argument("--max-notes", type=int, default=25)
    p.set_defaults(fn=cmd_capture_symmetry)
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
    p.add_argument("--id", default="", help="`resolve`: the advisory finding id printed "
                   "by `record`")
    p.add_argument("--because", default="", help="`resolve`: why the blocking fix made "
                   "this advisory FALSE (>= 20 chars, recorded in qa_state.json)")
    p.set_defaults(fn=cmd_qa_round)
    p = sub.add_parser("freeze"); p.add_argument("file")
    p.add_argument("--check", action="store_true", help="verify the file is byte-identical to the freeze snapshot")
    p.set_defaults(fn=cmd_freeze)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
