"""_common.py - shared utilities for the cbre-property-longlist skill.

Portable path resolution (works on Windows under Claude Code and on Linux
sandboxes), template/version loading, canonical-dataset loading, and optional
JSON-Schema validation. No third-party imports are required at import time;
jsonschema is used only if present.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normalize as _N  # noqa: E402  (helpers/ is on path by the line above)

# Skill root = the directory that contains helpers/ assets/ templates/ ...
SKILL_ROOT = Path(__file__).resolve().parent.parent

ASSETS = SKILL_ROOT / "assets"
TEMPLATES = SKILL_ROOT / "templates"
TEMPLATE_HTML = ASSETS / "dashboard_template.html"
VERSION_FILE = ASSETS / "VERSION"
SCHEMA_FILE = TEMPLATES / "canonical.schema.json"


# --- Atomic durable writes ---------------------------------------------------
# Every durable/resume-gating artefact goes through these: write to a sibling
# .tmp then os.replace onto the target, so a kill mid-write (routine at Cowork's
# ~45s cap) can NEVER leave a truncated file that --resume then treats as current.
# Text is LF-only (newline="\n") so the built HTML is byte-identical across
# platforms (no Windows CRLF translation) - the determinism contract.
def atomic_write_text(path, text: str, *, encoding: str = "utf-8", newline: str = "\n"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding=encoding, newline=newline) as fh:
        fh.write(text)
    os.replace(tmp, p)
    return p


def atomic_write_bytes(path, data: bytes):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, p)
    return p


def source_key(meta) -> str:
    """The identity of a record's source: its intake RELPATH when known, else its basename.

    Every producer writes `__meta.source_file` as a bare BASENAME, so two same-named inputs in
    different subfolders are structurally indistinguishable - `resolve_by_name` below made the
    choice between them deterministic (B13), which is not the same as correct. `source_relpath`
    is the unambiguous identity; this accessor is how a decision site opts in to it.

    ADDITIVE BY DESIGN (B43 phase 1). `source_file` is frozen forever as the documented ledger
    contract - it is a client-visible column that legitimately holds an email subject - and
    nothing existing changes value, so no durable artefact keyed on a basename breaks:
    `overrides.json` matching, the `plan_rejected` acks and the PHOTO_MAP-derived ledger rows
    all keep working. Callers migrate one at a time, and until they do this returns exactly
    what they read before."""
    m = meta or {}
    return str(m.get("source_relpath") or m.get("source_file") or "")


def resolve_candidates(source_dir, name) -> list:
    """Every input file under `source_dir` whose BASENAME is `name`, deterministically
    ordered: a root-level file first, then the rest by POSIX relpath.

    One resolver, because there were three and all three were wrong differently (B13):
    two took an UNSORTED first `rglob` hit, so which physical deck got rasterised depended
    on filesystem walk order; the third sorted PATH OBJECTS (case-folded on Windows,
    case-sensitive on POSIX, i.e. not portable) and passed the basename as a GLOB PATTERN,
    so a client file literally named `Unit [1].pdf` resolved to None.

    Matching is by NAME EQUALITY, never a glob, so metacharacters in a client filename are
    just characters. Sorting is on the relpath STRING so two machines agree.

    Deliberately NOT memoised here: callers keep their own caches (merge._SRC_RESOLVE, which
    the evals clear between fixtures), and a hidden second memo would make those clears
    silently ineffective."""
    if not source_dir or not name:
        return []
    root = Path(source_dir)
    base = Path(str(name)).name
    if not base:
        return []
    direct = root / base
    out = [direct] if direct.is_file() else []
    try:
        if root.exists():
            rest = [p for p in root.rglob("*")
                    if p.is_file() and p.name == base and p != direct]

            def _rel(p):
                try:
                    return p.relative_to(root).as_posix()
                except Exception:
                    return p.as_posix()
            out += sorted(rest, key=_rel)
    except Exception:
        pass
    return out


def resolve_by_name(source_dir, name):
    """The single winning path for a basename, or None. See resolve_candidates. (B13)"""
    c = resolve_candidates(source_dir, name)
    return c[0] if c else None


def basename_collisions(source_dir) -> dict:
    """{basename: [relpaths]} for every basename carried by MORE THAN ONE input file.

    Records reference their source by bare basename, so a collision means one property
    wears another's photos - and because page ownership keys on the RESOLVED path, both
    properties can silently lose their gallery instead. Choosing deterministically (above)
    makes that reproducible, not correct, so the collision itself has to be surfaced. It is
    a NOTE, never a refusal: `Site A/photos.pdf` + `Site B/photos.pdf` is a legitimate
    folder shape and rejecting it would hard-code an assumption about the input. (B13)"""
    root = Path(source_dir)
    seen: dict = {}
    try:
        for p in sorted(root.rglob("*"), key=lambda q: q.as_posix()):
            if not p.is_file() or p.name.startswith("~$"):
                continue
            rel = p.relative_to(root)
            if any(part.startswith((".", "_")) for part in rel.parts):
                continue
            seen.setdefault(p.name, []).append(rel.as_posix())
    except Exception:
        return {}
    return {k: v for k, v in seen.items() if len(v) > 1}


def atomic_save_image(im, path, fmt: str = "PNG", **kw):
    """Encode a PIL image to a sibling .tmp, then os.replace onto the target.

    A page image is a HANDOFF artefact - the transcription/interpretation sub-agent reads
    it - and a direct save is not atomic: a kill mid-encode leaves a partial file that is
    non-empty, so every resume guard here (`exists() and st_size > 0`, or a bare
    `exists()`) ACCEPTS it and the page is never re-rendered. The damage is therefore
    permanent, which is the part that matters; whether a truncated PNG renders as a top
    band or is rejected outright depends on the decoder and is not worth relying on either
    way. Same tmp+replace contract as atomic_write_text/_bytes. (B16)"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    im.save(str(tmp), fmt, **kw)
    os.replace(tmp, p)
    return p

# --- Ownership / provenance mark (see NOTICE) --------------------------------
# Authored by Timo Baaij. OWNER_NOTICE is the human copyright line (carries the ©
# glyph - keep it OUT of any console print on cp1252 hosts). OWNER_MARK is the ASCII,
# machine-checkable mark that preflight.py verifies on every run; OWNER_FINGERPRINT is
# a distinctive forensic token; OWNER_CANARY is a zero-width-encoded provenance canary
# (escape sequences here, so the file has no invisible bytes; the runtime value is
# invisible when rendered and survives copy-paste). Altering/removing any of these is
# DETECTED: the marked files are hashed into assets/integrity.json and preflight flags
# drift. (Honest limit: detectable, not unremovable - see NOTICE.)
OWNER_NOTICE = "© 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved."
OWNER_MARK = "cbre-property-longlist::owner=timo.baaij@cbre.com::2026"
OWNER_FINGERPRINT = "tb-cpl-7f3a9e2c"
OWNER_CANARY = "\u200b\u200c\u200b\u200c\u200c\u200b\u200c\u200b"  # ZW provenance canary (escape sequences -> no invisible bytes in source)

DATA_MARKERS = {
    "PROPS": "/* @@INJECT:PROPS@@ */",
    "POIS": "/* @@INJECT:POIS@@ */",
    "REGIONS": "/* @@INJECT:REGIONS@@ */",
}

# every {{token}} the template expects build_dashboard.py to fill
# v19 externalises chrome strings into an injected JSON block ({{ui_json}}) + a
# BCP-47 {{locale}}; the template's app <script> reads `const UI = {{ui_json}}` and
# `const LOCALE = "{{locale}}"`, then localises chrome at render via data-i18n*/T().
CONFIG_TOKENS = [
    "topbar_meta", "eyebrow", "title_html", "lede", "footer_copyright", "doc_title",
    "kpi_properties", "kpi_countries", "kpi_regions",     "kpi_wh_area", "kpi_rent", "kpi_countries_sub", "kpi_regions_sub",
    "kpi_wh_area_sub", "kpi_rent_sub", "dist_mode", "ui_json", "locale",
]


def load_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


_TEMPLATE_CACHE: str | None = None


def load_template() -> str:
    # Module-level singleton: the 728 KB template is read by build_dashboard.render
    # AND gate_runner validate-html (which also hashes it), several times per run.
    # The file is immutable within a run (make_template.py is a separate maintenance
    # invocation), so cache the parse. Identical bytes every call -> determinism and
    # the byte-stable-chrome guarantee are unaffected.
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        if not TEMPLATE_HTML.exists():
            raise FileNotFoundError(
                f"template missing: {TEMPLATE_HTML}\n"
                "Run helpers/make_template.py against a reference dashboard first."
            )
        _TEMPLATE_CACHE = load_text(TEMPLATE_HTML)
    return _TEMPLATE_CACHE


def load_version() -> dict:
    """Returns {'label': str, 'chrome_sha256': str}."""
    out = {"label": "", "chrome_sha256": ""}
    if not VERSION_FILE.exists():
        return out
    for i, line in enumerate(load_text(VERSION_FILE).splitlines()):
        line = line.strip()
        if i == 0 and "=" not in line:
            out["label"] = line
        elif line.startswith("chrome_sha256="):
            out["chrome_sha256"] = line.split("=", 1)[1].strip()
    return out


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# In-process parse-cache for canonical.json. run.py drives merge -> enrich -> the pre-build
# gate battery -> build -> post-build gates -> deliver ALL IN ONE PROCESS (the in-process
# spine), so load_canonical is called ~8-9x on the SAME canonical bytes per run - a multi-MB
# base64 re-parse each time. Keyed on (resolved path, mtime_ns, size): merge/enrich write
# canonical via an atomic os.replace (bumping mtime), so a changed canonical MISSES the cache
# and re-parses (no stale read). EVERY return is a fresh copy.deepcopy, so a caller mutating
# its result can never poison the cache or another caller (mutation isolation). deepcopy of
# this base64-heavy dict is ~40x cheaper than json.loads - it shares the immutable strings,
# copying only the container nodes (measured 0.15 ms vs 6 ms on a 5 MB canonical). (#22/#35)
_CANON_CACHE: dict = {}


def load_canonical(path: Path) -> dict:
    p = Path(path)
    try:
        st = p.stat()
        # Invalidation signature. st_ino is the DECISIVE member: the skill only ever writes
        # canonical via an atomic tmp+os.replace (merge/enrich), which mints a NEW underlying
        # file - so st_ino changes EVEN when a same-size rewrite lands within the same coarse
        # mtime tick (Windows st_mtime_ns resolution is ~1-2 ms, so mtime+size alone could
        # otherwise serve a stale hit). mtime_ns+size cover an in-place edit; ino covers the
        # atomic-replace case. (st_ino is 0 on filesystems that lack it -> degrades to
        # mtime+size, never worse than the old un-cached read.) (#22/#35)
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        key = str(p.resolve())
        hit = _CANON_CACHE.get(key)
        if hit is not None and hit[0] == sig:
            return copy.deepcopy(hit[1])
        parsed = load_json(p)
        _CANON_CACHE[key] = (sig, parsed)
        return copy.deepcopy(parsed)
    except OSError:
        return load_json(p)  # stat failure -> uncached passthrough (never worse than before)


def emit_review_view(canonical_path, dest=None) -> bool:
    """Write a photo-stripped twin of canonical.json (canonical_review.json, beside
    it) for the JUDGEMENT reviewers (G-honesty / G-trace / G-enrich): the base64
    heroes are ~99% of the multi-MB file and burn the reviewer's context for no
    benefit (they review DATA, not pixels - the contact sheet is the image aid), so
    each data: URI is replaced with a short marker. canonical.json stays
    authoritative; this is a read aid only (gates.md points the data reviewers here).

    It is regenerated by EVERY freeze - run.py's auto-freeze AND a standalone
    `gate_runner.py freeze` - so a re-review after an out-of-band data fix can never
    read a stale twin (the duplicate-review-round bug).

    `dest` writes the twin somewhere ELSE instead of beside the canonical, which is how a
    per-round SNAPSHOT is taken (B44). It matters that the snapshot reuses this function: the
    stripper below is the only photo-stripping code in the skill, and a second copy would
    drift. It also matters that the snapshot is STRIPPED - measured, a 12-property canonical is
    9.3 MB of which 99.56% is `data:` URIs, and the stripped twin is 43 KB. Keeping one
    unstripped copy per round would put tens of MB into every work dir.

    Never RAISES, but it does REPORT: returns True on success, False when the twin could
    not be refreshed. It used to swallow every failure and return None, which let
    cmd_freeze certify a freeze over an un-refreshed twin - the DATA reviewers then judged
    pre-fix data while the gate said they had seen the frozen bytes. A review aid that
    fails silently is worse than a run that stops, so the caller now BLOCKS on False. (B18)"""
    try:
        p = Path(canonical_path)
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return False

    def _strip(v):
        return (f"<image stripped: {len(v)} chars - see canonical.json>"
                if isinstance(v, str) and v.startswith("data:") else v)

    for prop in d.get("properties", []):
        for k in ("photo", "plan"):
            if prop.get(k):
                prop[k] = _strip(prop[k])
        for k in ("images", "gallery"):
            if isinstance(prop.get(k), list):
                prop[k] = [_strip(x) for x in prop[k]]
    try:
        atomic_write_text(Path(dest) if dest else (p.parent / "canonical_review.json"),
                          json.dumps(d, ensure_ascii=False, indent=2))
    except Exception:
        return False
    return True


_SCHEMA_DEGRADED: list = []  # set when the full validator could not run (read by the gate)


def schema_degraded(reason: str | None = None) -> str:
    """Record / report that schema validation ran DEGRADED (structural-only).

    The fallback must be VISIBLE. It was silent, so a gate printed
    "[PASS] schema + pair-consistency clean" on a dataset a real validator would have rejected,
    and nothing anywhere said the type floor had been lowered. Called with a reason to record;
    called with none to read the current state ("" == the full validator ran)."""
    if reason:
        if reason not in _SCHEMA_DEGRADED:
            _SCHEMA_DEGRADED.append(reason)
        return reason
    return _SCHEMA_DEGRADED[0] if _SCHEMA_DEGRADED else ""


#: numeric fields whose TYPE the degraded checker still enforces. Presence alone was not enough:
#: with jsonschema absent (an explicitly supported offline state) `validate-data` accepted
#: `warehouseArea: "not a number"`, `lat: "52N"` and `status: 5` and printed
#: "[PASS] schema + pair-consistency clean" - a crash-to-pass, and the only one in the audit.
#: `final_gate` does not re-run validate-data on the reviewed path, so post-build there was no
#: type floor at all. A sentinel string ('tbd'/'??') is NOT an error - it is the honest unknown.
_NUMERIC_FIELDS = ("id", "lat", "lng", "warehouseArea", "plotArea", "officeAreaVal",
                   "warehouseRentVal", "officeRentVal", "expansionParkVal")
_STRING_FIELDS_STRUCT = ("country", "park", "developer", "city", "status", "photo")


def _structural_errors(data: dict) -> list[str]:
    """Dependency-free structural check, used when jsonschema is missing or too
    old to build a validator. Mirrors the schema's required keys so the degraded
    verdict matches the real one instead of the pipeline crashing.

    Also TYPE-checks the numeric and string fields, because a presence-only check made the
    degraded path a crash-to-pass: it is the ONLY floor on those types when jsonschema is
    unavailable, and a string where a number belongs breaks sorting, filtering, the KPI strip
    and the rent/area arithmetic downstream."""
    errors: list[str] = []
    for key in ("meta", "properties", "pois", "regions"):
        if key not in data:
            errors.append(f"missing top-level key: {key}")
    props = data.get("properties")
    if isinstance(props, list):
        for p in props:
            if not isinstance(p, dict):
                errors.append(f"properties entry is {type(p).__name__}, not an object")
                continue
            pid = p.get("id", "?")
            for req in ("id", "country", "park", "developer", "city", "status", "photo"):
                if req not in p:
                    errors.append(f"property id={pid} missing required field: {req}")
            for f in _NUMERIC_FIELDS:
                v = p.get(f)
                if v is None or f not in p:
                    continue
                if _N.looks_unknown(v):
                    continue  # 'tbd'/'??' is the honest unknown, not a type error
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    errors.append(f"property id={pid} field {f} must be a number, "
                                  f"got {type(v).__name__} ({str(v)[:24]!r})")
            for f in _STRING_FIELDS_STRUCT:
                v = p.get(f)
                if f in p and v is not None and not isinstance(v, str):
                    errors.append(f"property id={pid} field {f} must be a string, "
                                  f"got {type(v).__name__} ({str(v)[:24]!r})")
    return errors


def _best_validator():
    """(ValidatorClass, jsonschema_module) for the newest draft this jsonschema
    build supports, or (None, module) if none is usable / (None, None) if the
    library is absent. The Draft20xx classes only exist on jsonschema >= 4; older
    builds (e.g. the 3.2.0 shipped in some sandboxes) only have Draft7/Draft4."""
    try:
        import jsonschema  # type: ignore
    except Exception:
        return None, None
    for name in ("Draft202012Validator", "Draft201909Validator",
                 "Draft7Validator", "Draft4Validator"):
        v = getattr(jsonschema, name, None)
        if v is not None:
            return v, jsonschema
    return None, jsonschema


def validate_canonical(data: dict) -> list[str]:
    """Return a list of human-readable schema errors ([] == valid).

    Version-tolerant: builds the newest Draft validator the installed jsonschema
    supports. On pre-4.x builds whose resolver doubles the schema's $id base URI
    (raising RefResolutionError even though the schema has no external $refs), it
    validates a copy with $id/$schema stripped. If jsonschema is absent, too old,
    or anything in validator construction/iteration fails, it degrades to a
    minimal structural check rather than crashing the gate (the failure mode that
    hard-stopped real runs on jsonschema 3.2.0)."""
    Validator, js = _best_validator()
    if Validator is None:
        schema_degraded(reason=("jsonschema is not available" if js is None
                                else "no usable jsonschema validator class"))
        return _structural_errors(data)
    try:
        schema = load_json(SCHEMA_FILE)
        # query the version without touching jsonschema.__version__ (deprecated on
        # 4.x, absent on some builds); importlib.metadata works back to 3.2.0.
        raw = ""
        try:
            from importlib.metadata import version as _pkg_version
            raw = _pkg_version("jsonschema")
        except Exception:
            raw = str(getattr(js, "__version__", "") or "")
        ver = tuple(int(x) for x in raw.split(".")[:2] if x.isdigit())
        if not ver or ver < (4, 0):
            # self-contained schema: drop identity keys so the legacy RefResolver
            # cannot build a doubled base URI and raise RefResolutionError.
            schema = {k: v for k, v in schema.items() if k not in ("$id", "$schema")}
        validator = Validator(schema)
        errors: list[str] = []
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            loc = "/".join(str(x) for x in err.path) or "(root)"
            errors.append(f"{loc}: {err.message}")
        return errors
    except Exception as e:
        schema_degraded(reason=f"{type(e).__name__} while validating")
        return _structural_errors(data)


def find_leftover_tokens(text: str) -> list[str]:
    return sorted(set(re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", text)))


# Every string field the dashboard render JS reads (some via .replace etc.), so a
# missing key crashes the render. The canonical rule is "never drop a key the chrome
# reads - emit the sentinel". Used by BOTH merge.canonicalize() and build_dashboard
# (the latter as a self-protecting defence for any hand-authored canonical).
STRING_FIELDS = [
    "permitting", "earlyAccess", "leaseTerm", "rentFree", "incentives",
    "divisibleFrom", "officeArea", "expansionBuilding", "expansionPark",
    "clearHeight", "floorLoad", "sprinklers", "loadingDocks", "overheadDoors",
    "electricity", "truckParking", "carParking", "warehouseRent", "officeRent",
    "serviceCharge", "breeam", "motorway", "region", "status", "description",
    # landlord is OPTIONAL (a DISTINCT party from developer, not schema-required): an
    # unknown landlord is the honest 'tbd' sentinel, and FIELD_PRESENT hides the modal
    # /compare landlord row dataset-wide when no input ever carried one.
    "landlord",
]


# schema-REQUIRED property fields (canonical.schema.json $defs.property.required,
# minus id/photo which merge always sets). Filled with an honest sentinel when
# unknown so a property missing one degrades to 'tbd'/'??' instead of HARD-failing
# validate-data with "'<field>' is a required property". Coverage still counts
# these as unfilled (it tests for non-'tbd'), so a thin record is still surfaced -
# the sentinel only prevents the schema crash, it never masks a gap.
REQUIRED_TEXT_SENTINELS = {"developer": "tbd", "city": "tbd", "park": "tbd",
                           "status": "tbd", "country": "??"}

# chrome fields the schema types as string; an honest numeric value from ANY
# extractor (e.g. loadingDocks: 12 from a tracker/vision record) is coerced to a
# clean string so it satisfies the schema instead of hard-failing validate-data.
_COERCE_STR = set(STRING_FIELDS) | set(REQUIRED_TEXT_SENTINELS) | {"landPrice", "mapLink", "reit"}

# --- render-boundary helpers (Phase 1) --------------------------------------
_CANON_PROPERTY_FIELDS = None


def canonical_property_fields() -> frozenset:
    """Property field names the SCHEMA declares ($defs.property.properties) UNION every
    p.<field> the template reads. Used to protect canonical CONTAINER objects
    (gallery/preBaked/districtProfile) at the merge boundary and by the render-boundary gate.
    NOT a display allowlist for scalars: any real scalar attribute still auto-shows."""
    global _CANON_PROPERTY_FIELDS
    if _CANON_PROPERTY_FIELDS is None:
        try:
            schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8-sig"))
            keys = set((((schema.get("$defs") or {}).get("property") or {})
                        .get("properties") or {}).keys())
        except Exception:
            keys = set()
        # scan the APP script only (everything from the PROPS injection marker onward) so a
        # bundled vendor library BEFORE it (minified Leaflet, whose `p.prototype` etc. would
        # otherwise leak noise like "prototype" into the set) can never pollute the contract.
        tpl = load_template()
        marker = DATA_MARKERS.get("PROPS", "")
        idx = tpl.find(marker) if marker else -1
        app = tpl[idx:] if idx != -1 else tpl
        keys |= set(re.findall(r"\bp\.([A-Za-z_]\w*)", app))
        _CANON_PROPERTY_FIELDS = frozenset(keys)
    return _CANON_PROPERTY_FIELDS


# a pipeline provenance-locator string is the WHOLE value "page N (...)" / "slide N (...)" /
# a bare "page N" / "slide N" (extract_pdf prov). Anchored end-to-end + conservative so real
# prose that merely mentions a page is never mistaken for a locator.
_LOCATOR_RE = re.compile(r"^\s*(?:page|slide)\s+\d+\s*(?:\(.*\))?\s*$", re.IGNORECASE)


def looks_like_locator(v) -> bool:
    """True for a pipeline provenance-locator string (a page/source reference), never a
    real displayable value. Deterministic."""
    return isinstance(v, str) and bool(_LOCATOR_RE.match(v.strip()))


# --- translation eligibility (Phase 2) --------------------------------------
# Fields that are identifiers / proper names / structural / figure-carrying -> NEVER sent to the
# translator. Everything else that holds prose IS eligible (the LLM makes the final prose-vs-name
# call; these exclusions just keep obvious non-prose out). NOT a positive prose list, so a brand-
# new prose attribute is eligible automatically.
IDENTIFIER_FIELDS = frozenset({
    "id", "country", "developer", "park", "city", "landlord", "motorway", "region", "regionCode",
    "lat", "lng", "coordsApprox", "breeam", "rentUnit", "areaUnit", "mapLink", "photo", "gallery",
    "plan", "preBaked", "district", "districtProfile", "reit",
    "warehouseRentVal", "officeRentVal", "officeAreaVal", "expansionParkVal",
    # rent/price/area strings are figure+unit+currency -> kept verbatim (source convention)
    "warehouseRent", "officeRent", "serviceCharge", "landPrice", "plotArea", "warehouseArea",
    "officeArea", "divisibleFrom", "earlyAccess",
})
# B53: the unit class admits DIGITS, so "50 kN/m2" and "2.4 MVA" read as figure+unit rather than
# prose. A space inside the tail still fails the match, so "2 storey office" stays translatable.
_TR_NUMUNIT_RE = re.compile(r"^[\s\d.,]+(?:\s?[a-zA-Z0-9%²³/.\-]{0,8})?$")  # "12", "12 m", "50 kN/m2"
# B53: one optional space-separated group, so a two-part alphanumeric code is caught - "DN11 8DB",
# "MK16 0QE", "1234 AB". Without it the internal space made every UK postcode look like prose and
# it was queued for translation.
_TR_CODE_RE = re.compile(r"^[A-Za-z]{0,4}[\-\s]?[\d][\w.\-/]*(?:\s[\w.\-/]+)?$")
# B53: a bare grade ("A", "A+", "B2"). UPPER-CASE only, and deliberately so - a lower-case one- or
# two-letter value is a real word ("No", "Ja", "Si") that MUST stay translatable.
_TR_GRADE_RE = re.compile(r"^[A-Z][+\-]?\d{0,2}$")
_TR_DATE_RE = re.compile(r"^\d{4}([-/.]\d{1,2}){0,2}$|^Q[1-4]\s*\d{4}$", re.IGNORECASE)
_TR_URL_RE = re.compile(r"^(https?://|www\.|mailto:)", re.IGNORECASE)
_TR_CURRENCY_RE = re.compile(r"[€£$¥]|/\s*(yr|mo|year|month|sq\s?m|sq\s?ft|m²)", re.IGNORECASE)


def is_translatable_value(field: str, v) -> bool:
    """Deterministic eligibility: True only for a free-text PROSE string worth translating.
    Excludes identifier/name/figure fields, and values that are numbers, number+unit, codes,
    dates, URLs, currency/rate strings, locators, or sentinels. The LLM still makes the final
    prose-vs-proper-noun judgement on what passes; these rules only keep obvious non-prose out."""
    if not isinstance(v, str):
        return False
    if field in IDENTIFIER_FIELDS:
        return False
    s = v.strip()
    if not s or s.lower() in {"tbd", "tbc", "—", "-", "??", "n/a", "none"}:
        return False
    if looks_like_locator(s):
        return False
    # A multi-word PHRASE is prose even if it embeds a figure/price/URL (e.g. a description
    # that mentions "€60/sqm") -> eligible. The figure/code/date/currency/URL exclusions apply
    # ONLY to SHORT atomic values (a value that IS a rate/code/date, not prose containing one),
    # so a real description is never silently withheld from translation.
    if len(s.split()) <= 3:
        if (_TR_URL_RE.match(s) or _TR_DATE_RE.match(s) or _TR_CODE_RE.match(s)
                or _TR_GRADE_RE.match(s)
                or _TR_CURRENCY_RE.search(s) or _TR_NUMUNIT_RE.match(s)):
            return False
    return True


def _as_text(v):
    """Format a numeric value as a clean string for a string-typed chrome field
    ('12', '11.5'); pass anything else through unchanged."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:g}"
    return v


def core_fill(rec: dict) -> float:
    """Fraction of a candidate record's CORE fields present: city, developer,
    size (warehouse OR plot), price (rent OR land price), status. Shared by the
    run.py vision-routing probe and merge's file-quality demotion so the two
    can never drift apart."""
    def filled(v):
        return not _N.looks_unknown(v)
    has_size = filled(rec.get("warehouseArea")) or filled(rec.get("plotArea"))
    has_price = (filled(rec.get("warehouseRent")) or filled(rec.get("warehouseRentVal"))
                 or filled(rec.get("landPrice")))
    core = [filled(rec.get("city")), filled(rec.get("developer")), has_size,
            has_price, filled(rec.get("status"))]
    return sum(1 for c in core if c) / len(core)


def record_is_poor(rec: dict) -> bool:
    """A record whose deterministic parse looks unreliable: too few core fields,
    a synthesised 'option N' name with no real city, or an implausible rent (a
    misparse like €1 or €216000/m²/yr). Structural/numeric only - no language
    or region tokens."""
    if core_fill(rec) < 0.4:
        return True
    if " option " in str(rec.get("park", "")).lower() and _N.looks_unknown(rec.get("city")):
        return True
    rv = rec.get("warehouseRentVal")
    if isinstance(rv, (int, float)):
        lo, hi = _N.rent_unit_band(rec.get("rentUnit"))
        if not (lo <= rv <= hi):
            return True
    return False


def fill_render_sentinels(p: dict) -> dict:
    """Fill every chrome-read key with its sentinel (honest unknown, never invented)."""
    for f in STRING_FIELDS:
        if _N.looks_unknown(p.get(f)):
            p[f] = "tbd"
    for f, sentinel in REQUIRED_TEXT_SENTINELS.items():
        if _N.looks_unknown(p.get(f)):
            p[f] = sentinel
    if _N.looks_unknown(p.get("landPrice")):
        p["landPrice"] = "—"
    if "reit" not in p:
        p["reit"] = None
    if _N.looks_unknown(p.get("mapLink")):
        p["mapLink"] = ""
    if "warehouseRentVal" not in p:
        p["warehouseRentVal"] = None
    # coerce honest numerics in string-typed fields (loadingDocks: 12 -> "12") so a
    # well-meant integer can't hard-fail the schema; number-typed fields are untouched
    for f in _COERCE_STR:
        v = p.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            p[f] = _as_text(v)
    return p
