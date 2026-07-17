#!/usr/bin/env python3
"""gate_runner.py - mechanical (script) halves of the QA gates.

Subcommands (judgement halves run as isolated reviewer sub-agents, not here):
  PRE-BUILD:
    validate-data   G-schema     : canonical.json valid against the schema + pair-consistency
    self-check      G-selfcheck  : schema field set == tokens/markers the template/build use
    coverage        G-coverage   : every cluster produced records; no dup; core-field fill or explicit tbd
    trace-coverage  G-trace      : every non-sentinel source-able field has a ledger row (source_type != gap)
    images          G-images     : every photo is a valid data URI; lists unmatched assets / placeholders
    enrichment      G-enrichment : regions/POIs/distances sourced+dated, no copied figure, not silently empty
  POST-BUILD:
    validate-html   G-html       : delivered HTML == render(canonical) byte-for-byte; blocks round-trip; chrome sha
    reconcile       G-reconcile  : every id in HTML <-> canonical; KPI strip matches the data
    i18n            G-i18n       : rendered chrome complete (175 keys), no unfilled token, well-formed
                                   LOCALE, no silent EN fallback for an expected-localised language, placeholders intact
  REVIEW WINDOW:
    freeze          (--check)    : snapshot/verify canonical bytes so parallel reviewers all judge the same artefact

Each subcommand prints a scorecard fragment and exits non-zero on a blocking failure.
"""
from __future__ import annotations

import argparse
import json
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

    if errs:
        for e in errs:
            _bad(e)
        print(f"STATUS: BLOCKED ({len(errs)} schema/consistency issues)")
        return 1
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

    # 1. const UI parses and has EXACTLY the EN key set (175) - no missing, no extra.
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
    n_plan = sum(1 for p in data.get("properties", [])
                 if str(p.get("plan", "")).startswith("data:image/"))
    print(f"  [note] site plans attached: {n_plan}/{len(data.get('properties', []))} "
          f"(the modal's Site Plan toggle reads p.plan)")
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
    C.atomic_write_text(side, sha)
    # ALWAYS refresh the photo-stripped reviewer twin to match the bytes just frozen,
    # so a re-freeze after an out-of-band data fix can never leave the DATA reviewers
    # reading a stale canonical_review.json (the wasted duplicate-review-round bug).
    C.emit_review_view(p)
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
    p = sub.add_parser("enrichment"); p.add_argument("canonical")
    p.add_argument("--requested", default="", help="comma-separated layers the broker "
                   "REQUESTED (geocode,pois,osrm,regions) - a requested layer that left "
                   "NO enrichment record means the stage crashed/was skipped (P2-9)")
    p.set_defaults(fn=cmd_enrichment)
    p = sub.add_parser("translation"); p.add_argument("canonical")
    p.add_argument("--work", required=True); p.add_argument("--lang", default="English")
    p.set_defaults(fn=cmd_translation)
    p = sub.add_parser("freeze"); p.add_argument("file")
    p.add_argument("--check", action="store_true", help="verify the file is byte-identical to the freeze snapshot")
    p.set_defaults(fn=cmd_freeze)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
