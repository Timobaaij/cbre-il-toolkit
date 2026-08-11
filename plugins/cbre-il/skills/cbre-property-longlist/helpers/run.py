#!/usr/bin/env python3
# © 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""run.py - the deterministic pipeline spine (Stages 0-7) in one command.

Drives the scriptable path end-to-end for the common brochure case:
  intake -> extract (pdf preferred for fields, pptx for images) -> merge ->
  enrich (per project.yaml/flags) -> pre-build gates -> build -> post-build
  gates -> deliver.

The AGENTIC steps stay with the orchestrator (Claude) per SKILL.md and are NOT
run here: Outlook-MCP email extraction, region research, vision transcription of
image/vector-only decks, and the judgement gates (G-honesty / G-trace / G-images
/ G-visual isolated reviewers). Run those around this spine. This script is safe
to re-run; it is the reproducible core.

Exit codes (distinct per failure class - an orchestrator branching on them must
never misdiagnose):
  0 = built and delivered, all mechanical gates ALL-PASS
  2 = no readable property sources at all
  3 = a brochure deck OR a tracker OR an unresolvable region label needs
      INTERPRETATION (manifest in work/vision/). For a brochure deck dispatch the
      text/vision sub-agent per the manifest's per-deck `mode`; for a tracker `jobs`
      entry dispatch the tracker-mapping sub-agent (it returns a column->field MAP,
      not records; Python parses the numbers); for a `region_labels` entry dispatch
      the region-label sub-agent (it returns one KNOWN dataset NUTS code from the
      job's candidate list, or null, into work/extract/region_labels.json - never a
      record, never an invented code; bind_region_codes re-verifies it and the
      point-in-polygon bind still wins when coords exist) - see
      reference/interpretation.md, then re-run the SAME command (--resume is the
      default, so the re-run continues instead of restarting). A tracker is OFFERED
      a richer LLM mapping: the dictionary already extracted it, so writing a .SKIP
      sentinel beside the job's output keeps the dictionary and lets the re-run
      proceed. ALSO used on a mixed run: nothing is built until the interpreted
      records are in, so the first build is never a throwaway.
  4 = skill copy failed preflight (restart the session)
  5 = validate-data blocked (schema/consistency defect - fix inputs/data)
  6 = another pre-build gate blocked (see gate1_scorecard.md; not built)
  7 = a post-build gate blocked (see gate2_scorecard.md; not delivered)
  8 = web enrichment needed: geocodes/POIs/drive-times were requested, the
      sandbox network is dead and the caches are cold. It is ALWAYS the Cowork
      sandbox; PROBE which tools are present and use the FIRST available:
      (1) mcp__shell (native, has outbound network - NOT Windows-only, may be in
      Cowork): re-run this command THROUGH it so the helpers hit the live APIs and
      bake the caches directly, no page, no browser; (2) the Playwright MCP via the
      data: URL fetcher (browser_navigate to each request's data_url, read back with
      browser_evaluate(filename=save_as) into work/web_fetched/<save_as>); (3) the
      Claude Preview MCP serving the FULL fetcher PAGE work/web_enrich.html via the
      .claude/launch.json this exit writes, reading the seeds object straight from
      the page; (4) deliver web_enrich.html in the chat for the operator to run in
      their own browser (the universal fallback). Either way save web_seeds.json
      into the work dir, then helpers/web_enrich.py ingest + re-run. (WebFetch
      CANNOT reach the Nominatim/Overpass/OSRM/ORS API hosts - it is not a path;
      work/web_requests.json is the request list, each with a ready data_url.)
      Genuine nearest POIs + real drive times then bake in fully offline (a
      preloaded list is a stopgap, never the product).
  9 = photo match needed: brochures yielded no text but the run already holds the
      property data from another source (a tracker/emails/other decks), so each
      brochure is likely a PHOTO for a known property, not a new property. Dispatch
      an isolated sub-agent to match by MEANING (work/photo_match_manifest.json ->
      work/photo_map.json: confident / uncertain / unrelated), then re-run. Confident
      matches attach the brochure's photo; uncertain ones show a placeholder and are
      surfaced for the broker to confirm; unrelated go to the vision path. With no
      other records (a pure brochure run) this never fires - the vision path runs.
 10 = cross-source adjudication needed (TWO kinds, one round-trip): after the
      deterministic matcher has auto-merged the confident pairs and hard-BLOCKED the
      impossible ones (a >15% size conflict; a developer disagreement is a GREY pair
      the sub-agent adjudicates, never a hard block), (a) some GREY-ZONE
      cross-source MATCH pairs may remain (cross-source, not forbidden, not auto, but
      plausibly the same property - same city / within ~2 km / a shared distinctive park
      token / a borderline fuzzy key), AND (b) some genuine cross-source VALUE CONFLICTS
      may remain (a field where two+ sources state different non-unknown values within one
      merged property). The spine writes BOTH to work/match_candidates.json (the `pairs`
      and `field_conflicts` arrays) and exits 10. Dispatch an isolated sub-agent to decide,
      by MEANING: each pair SAME/different (-> work/match_decisions.json), and each value
      conflict's pick among the candidates (-> work/field_decisions.json; KEEP the
      precedence `default` unless a candidate is clearly right). See reference/matching.md,
      then re-run. The match verdict resolves ONLY the grey pairs (the auto/forbidden tiers
      are unchanged; a forbidden pair never merges even on 'same'); the value pick OVERRIDES
      the fixed precedence ONLY when it selects a candidate value that passes the field's
      plausibility gate (else precedence stands). With no grey pairs AND no value conflicts
      (the common case) this never fires; offline (no decisions files) the deterministic
      matcher + the fixed precedence are the fallbacks.
 11 = dashboard-language FALLBACK needed: the chosen language is a SUPPORTED European
      Latin-script language that is NOT one of the bundled 13, and there is no valid
      work-dir translation cache yet. The spine writes a request manifest
      work/i18n/<code>_request.json ({code, language, locale, en_sha, instructions,
      strings: every EN chrome string}) and exits 11. Dispatch an ISOLATED translation
      sub-agent: translate every value to <language>, keep the JSON keys + the
      {area}/{unit} placeholders + the &amp;/glyph/CBRE/OSRM/BREEAM/etc. invariants, add
      "_en_sha":"<en_sha>", save the flat {key:value} to work/i18n/<code>.json, then re-run
      the SAME command (the cache is baked into canonical.meta.ui_overrides by merge and
      reproduced byte-for-byte by render/validate-html). Blind-verify it as G-i18n before
      shipping. Decline with `type nul > work/i18n/<code>.SKIP` to fall back to English. An
      UNSUPPORTED language (an unsupported script such as Greek, or nonsense) never fires
      this - it renders English. Simplified Chinese (zh) is BUNDLED, so it never fires here.
 12 = free-text DATA translation needed: property free-text (description/status/prose
      attributes) does not yet match output.language. The spine writes
      work/i18n/data_translate_request.json ({items: [{property_id, field, text}]}) and
      exits 12. Dispatch an ISOLATED translation sub-agent over ONLY that request (PROSE
      only - numbers, units, codes, dates and proper names stay verbatim), MERGE its
      {text: translation} map into work/i18n/data_translations.<code>.json, then re-run
      the SAME command (the deterministic bake writes only eligible fields; the Source
      Ledger keeps the verbatim original). Blind-verify as G-lang. Decline by dropping
      work/i18n/data_translate.SKIP. Cached + resume-safe: once baked it never re-fires.
 13 = CLARIFICATION needed - a source is genuinely ambiguous (a unit-silent area or
      rent, a brochure-vs-tracker record-count mismatch). The spine writes
      work/questions.json and exits 13. Route each question by asked_of: "agent" =
      dispatch an ISOLATED sub-agent with the named source (never answer from the
      orchestrator's own context); "broker" = put ALL broker questions to the user in
      ONE plain-language message. Write work/answers.json as {"<id>": "<answer>"} (ids
      verbatim; where options is given, one of those exact strings), then re-run. Every
      question is asked ONCE: answer what is actually known, leave the rest, and the run
      proceeds with the honest gap named in each question's if_unanswered - never invent
      an answer to clear the list.

Each stage runs IN-PROCESS: the helper modules are imported once and their
main() is called directly, rather than spawning a fresh `python` subprocess per
stage. The heavy libraries (PyMuPDF, Pillow, rapidfuzz) are therefore imported a
single time instead of ~14 times, removing a few seconds of fixed start-up
overhead with no change to behaviour or output. Every stage is wrapped so one
stage's crash is reported and the run continues, exactly as the old subprocess
spine did (a non-zero gate stops the run at its stage boundary - see exit codes).

Resume is the DEFAULT (--no-resume recomputes everything): a stage whose output
already exists and is newer than its inputs is skipped (intake, per-file extract,
merge, enrich, build) - the gates and the freeze ALWAYS re-run, so nothing ships
unverified. Built for sandboxes with a short shell cap (e.g. Cowork's ~45s) and
for the vision re-run: a killed or vision-interrupted run continues from where
it stopped instead of re-extracting and re-embedding every base64 photo.

CLI:
  python run.py --folder <inputs> --work <work-dir> [--client Normal]
                [--geocode] [--pois] [--osrm] [--regions] [--no-pptx] [--no-resume]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUIET = True  # DEFAULT (B27); --verbose opts out. Quiet = plain-English step markers
              # only, sub-output swallowed. The failure-safe default: a broker-facing
              # run that forgets a flag stays clean, and the handoff instructions the
              # orchestrator needs print regardless (see _say_orchestrator).
RESUME = False  # set by --resume: skip a stage whose output is already current (gates/freeze never skipped)


# B58: fields the pipeline ASSIGNS, so a reader must never be asked for them. Everything
# else in _common.canonical_property_fields() is a reader-fillable field and ships in the
# exit-3 manifest's `fields` list. `warehouseRentVal` deliberately STAYS on the reader list
# (the contract requires the numeric annual rate); the other *Val twins are derived.
_PIPELINE_ASSIGNED_FIELDS = frozenset({
    "id", "photo", "plan", "gallery", "preBaked", "regionCode", "coordsApprox",
    "officeAreaVal", "officeRentVal", "expansionParkVal",
})


# B58: the three rules that make `fields` a FLOOR, not a ceiling. A module constant, not an
# inline literal, so evals/capture_contract_test.py can assert the assembled string (an
# implicitly-concatenated literal is unsearchable in source - which is how the first version
# of that eval failed).
_FIELD_RULES = (
    "CAPTURE EVERY ROW THE PAGE STATES - `fields` is the canonical registry, NOT a limit. "
    "Three rules, in order of how often they are broken: "
    "(1) A STATED NEGATIVE IS DATA, NEVER AN ABSENCE. 'Not charged', 'No', 'None', 'N/A' are "
    "positive commercial statements - ship them as the value. Only a blank row, or one the "
    "deck marks tbd/TBC/BTS/TBS, is unknown. Shipping the unknown sentinel instead tells the "
    "broker to go and ask an agent a question the deck already answered. "
    "(2) THE SCHEMA IS OPEN (`additionalProperties: true`). If a stated row has no obvious "
    "home in `fields`, DO NOT DROP IT - emit it under a descriptive camelCase key of your own "
    "(e.g. yardRent, railSiding). The dashboard auto-shows any real scalar attribute and the "
    "Gaps Report discloses it via meta.newFields. "
    "(3) 'There is no field for X' is never a reason to omit X. If you are about to write that "
    "sentence in your report, emit the field instead. "
    "(4) WRITE A VALUE THE WAY THE SOURCE PRINTS IT. A dimensioned value carries its unit in "
    "the value itself - '10,000 sq. m', not '5000'; '10 m', not '10' - because the dashboard "
    "shows most fields verbatim and a bare magnitude beside a written sibling quotes a "
    "different quantity to the client. Copy the printed form; do not normalise, round or strip "
    "the unit, and do not ADD a unit the page does not print. A pure count ('72' loading docks) "
    "is correctly bare - the rule is about dimensioned quantities. If a page states a magnitude "
    "whose unit you genuinely cannot read, return the number, say so in that field's prov, and "
    "the value-format gate will surface it for the broker to settle."
)


def _reader_field_list() -> list:
    """The canonical fields an interpretation sub-agent may fill, sorted for determinism.

    Generated from the registry rather than restated, so the handoff can never drift from
    what merge/the dashboard actually carry - the drift is exactly what made three readers
    drop stated rows on a live run.
    """
    try:
        import _common as C
        fields = set(C.canonical_property_fields())
    except Exception:                      # registry unavailable -> say so, never guess
        return []
    return sorted(fields - _PIPELINE_ASSIGNED_FIELDS)


class _Buf(io.StringIO):
    """stdout capture that tolerates helpers calling sys.stdout.reconfigure()."""
    def reconfigure(self, *a, **k):
        return None


def step(msg: str) -> None:
    """The ONLY on-screen line per stage in quiet mode (plain English, no jargon).
    ASCII marker so it never crashes a cp1252 console."""
    print(f"- {msg}")


def call(module, *cmd, check=True) -> int:
    """Run a helper module's main() in-process (no subprocess, no re-import).

    Mirrors the old sh(): in quiet mode it swallows the helper's stdout/stderr and
    surfaces only a one-line failure; otherwise it echoes the call and lets output
    through. The call is wrapped so one stage's crash cannot kill the run (the old
    per-subprocess isolation), and sys.argv is saved/restored so the argparse-based
    helper mains run unchanged."""
    argv = [getattr(module, "__name__", "helper"), *[str(c) for c in cmd]]

    def _invoke() -> int:
        saved = sys.argv
        sys.argv = argv
        try:
            module.main()
            return 0
        except SystemExit as e:  # argparse / explicit sys.exit() inside the helper
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        finally:
            sys.argv = saved

    if QUIET:
        buf = _Buf()
        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                rc = _invoke()
        except Exception as e:  # crash isolation
            buf.write(f"\n{type(e).__name__}: {e}")
            rc = 1
        if rc != 0 and check:
            # surface a failure as ONE short line - and in quiet/broker mode NEVER echo the
            # captured tail: it can be an exception class name + an absolute path
            # (FileNotFoundError ... C:\\Users\\...). The orchestrator still has the full
            # captured output on stderr / in the scorecard; the broker gets a neutral line.
            print("  (this step could not be completed - a file could not be read)")
        return rc

    print(f"\n$ {module.__name__} {' '.join(argv[1:])}")
    try:
        rc = _invoke()
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    if check and rc != 0:
        print(f"step failed (exit {rc})")
    return rc


_GATE_LOG: list[str] = []  # scorecard fragments accumulated for the current gate phase


def run_gate(module, *cmd) -> int:
    """Run a gate's mechanical half, ALWAYS capturing its scorecard fragment to
    _GATE_LOG so it can be flushed to gate{1,2}_scorecard.md (the freeze/ship
    signal that gates.md and pipeline.md tell the orchestrator to read) - even in
    --quiet, where the on-screen output is swallowed. Returns the gate exit code."""
    name = str(cmd[0]) if cmd else getattr(module, "__name__", "gate")
    buf = _Buf()
    saved = sys.argv
    sys.argv = [getattr(module, "__name__", "helper"), *[str(c) for c in cmd]]
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            module.main()
        rc = 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # crash isolation - a gate crash is a BLOCK, not a stop
        buf.write(f"\n{type(e).__name__}: {e}")
        rc = 1
    finally:
        sys.argv = saved
    text = buf.getvalue().rstrip()
    _GATE_LOG.append(f"### {getattr(module, '__name__', 'gate')} {name}  ->  "
                     f"{'ALL-PASS' if rc == 0 else 'BLOCKED'} (exit {rc})\n"
                     + (text or "(no output)"))
    if not QUIET:
        print(f"\n$ {module.__name__} {name}")
        print(text)
    elif rc != 0:
        # quiet/broker mode: NO scorecard jargon on-screen. The orchestrator gets the
        # technical detail on stderr + in gate{1,2}_scorecard.md; the final exit prints
        # the one plain sentence the broker needs.
        tail = (text.strip().splitlines() or [""])[-1]
        print(f"[gate {name} exit {rc}] {tail[:160]}", file=sys.stderr)
    return rc


def write_scorecard(path: Path, title: str) -> None:
    """Flush the accumulated gate fragments to a scorecard file and clear the log.
    The first line after the title is the machine-read STATUS the orchestrator and
    final-gate adjudication key on (see reference/gates.md, reference/pipeline.md)."""
    blocked = sum(1 for f in _GATE_LOG if "->  BLOCKED" in f)
    overall = "BLOCKED" if blocked else "ALL-PASS"
    header = f"# {title}\n\nSTATUS: {overall}" + (f" ({blocked} gate(s) blocked)\n" if blocked else "\n")
    body = "\n\n".join(_GATE_LOG)
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    _GATE_LOG.clear()
    if not QUIET:
        print(f"\n  scorecard -> {path}  (STATUS: {overall})")


def load_yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    import yaml
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        # a hand-edited / malformed project.yaml must NEVER crash the run with a
        # traceback (the scaffold itself is now always valid via safe_dump); degrade
        # to safe defaults and say so in one plain sentence
        print(f"NOTE: couldn't read project.yaml ({str(e).splitlines()[0][:120]}); using "
              f"safe defaults - fix or delete that file and re-run to apply your settings.",
              file=sys.stderr)
        return {}


def _stamp_source_relpath(records, rel: str) -> int:
    """Stamp `__meta.source_relpath` on records whose source relpath the caller KNOWS.

    Every extractor writes `source_file` as a bare BASENAME - deliberately, because an
    extractor is root-blind - so two same-named inputs in different subfolders are
    indistinguishable downstream. `resolve_by_name` made the choice between them deterministic
    (B13); this makes it unambiguous. run.py is the right place to do it because it is the only
    layer that holds both the record file and the inventory relpath that produced it.

    ADDITIVE (B43 phase 1): `source_file` is untouched, nothing reads `source_relpath` yet, and
    `_common.source_key()` falls back to the basename - so this pass changes no output byte.
    That is intentional: the stamp is proven to EXIST before anything depends on it, which is
    this project's 'test the PATH, not the function' lesson applied in advance instead of after
    a fourth dead-wiring incident. Phases 2-4 (which consumers opt in) are B45."""
    n = 0
    rel = str(rel or "").replace("\\", "/")
    if not rel:
        return 0
    for r in records or []:
        if isinstance(r, dict):
            r.setdefault("__meta", {})["source_relpath"] = rel
            n += 1
    return n


def _code_stamp(work, name: str, paths) -> Path:
    """Record a digest of the LIVE BYTES of the helpers a stage depends on. (B42)

    No resume predicate carried any code identity, so editing a helper left every work dir
    resuming past the stage that helper feeds. The obvious stamps are both wrong:
    `assets/VERSION` is the TEMPLATE version and does not move for a `merge.py` edit, and
    `sha256(integrity.json)` only moves when a human remembers to run `make_integrity.py` -
    and preflight merely notes a stale manifest to stderr, which `mcp__shell` does not surface.
    Live bytes cannot go stale.

    Takes PATHS rather than module names so an eval can point it at temp copies - that is what
    makes it testable, and testability is the whole difference between this and a stamp nobody
    can prove works. `_write_if_changed`, so an unchanged closure does not churn the mtime and
    re-fire the stage on every run."""
    h = hashlib.sha256()
    for p in sorted(str(x) for x in paths):
        try:
            h.update(Path(p).read_bytes())
        except Exception:
            h.update(b"\0")
    return _write_if_changed(Path(work) / f".code_{name}", h.hexdigest()[:16])


def _engine_stamp(work: Path) -> Path:
    """Record the ACTIVE image engine in the work dir and return the stamp path.

    `_is_current` compares mtimes of INPUT FILES, so it is blind to the environment that
    produced an output - which made the engine tag inside the image cache keys INERT on the
    real path: the documented degraded-then-native workflow resume-skipped merge entirely,
    never consulted the image cache, and served the poisoned negative while printing
    "native PyMuPDF". Turning the engine into a FILE is what lets the existing predicate see
    it, with no change to _is_current itself.

    `_write_if_changed`, so an unchanged engine does not churn the mtime and re-fire merge
    on every run; a changed one bumps it exactly once and everything downstream recomputes.
    Existing work dirs therefore recompute ONCE when this lands, which is intended. (B17)"""
    try:
        import images as _IMG
        tag = _IMG._engine_tag()
    except Exception:
        tag = "unknown"
    return _write_if_changed(Path(work) / ".engine_stamp", tag)


def _is_current(out, inputs) -> bool:
    """--resume guard: True when `out` exists and is at least as new as every input
    that exists, so re-deriving it would reproduce the same bytes. Conservative -
    a missing output, or any input touched after the output, returns False (recompute).
    Deterministic stages only; the gates and the freeze are NEVER routed through this."""
    if not RESUME:
        return False
    out = Path(out)
    if not out.exists():
        return False
    try:
        out_m = out.stat().st_mtime
    except OSError:
        return False
    newest_in = 0.0
    for i in inputs:
        ip = Path(i)
        if not ip.exists():
            continue
        try:
            if ip.is_dir():
                # a directory input's currency is its NEWEST descendant (recursive): st_mtime
                # on the dir NODE alone misses an in-place edit of a file AND any change inside
                # a subfolder (child mtimes do not bubble up), so intake would be wrongly skipped
                # after such an edit. rglob catches every nested input; intake.discover already
                # walks recursively, so the stamp now matches what discovery actually reads. (#27)
                newest_in = max(newest_in, ip.stat().st_mtime)
                for child in ip.rglob("*"):
                    newest_in = max(newest_in, child.stat().st_mtime)
            else:
                newest_in = max(newest_in, ip.stat().st_mtime)
        except OSError:
            return False  # cannot prove currency -> recompute
    return out_m >= newest_in


def _resumed(label: str) -> None:
    """One quiet 'skipped, already up to date' note in verbose mode; silent for brokers."""
    if not QUIET:
        print(f"  (resume: {label} already up to date - skipping)")


def _sha(path) -> str:
    """sha256 of a file's bytes (for the enrich resume-stamp)."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_if_changed(path: Path, text: str) -> Path:
    """Write only when content differs, so an unchanged intermediate keeps its mtime.
    Lets --resume see that downstream stages (merge) are still current instead of
    being re-triggered by a byte-identical rewrite. A no-op when content matches."""
    path = Path(path)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return path


# --- parse-quality assessment: route a deck to vision when it parsed POORLY, not
# only when it produced 0 records. Signals are structural/numeric, so the decision
# is language-, client- and layout-neutral; conservative (>50% poor) so a clean
# deck is never re-visioned. ---------------------------------------------------- #
_SENTINELS = {"", "tbd", "tbc", "—", "none", "n/a", "na", "null"}


def _filled(v) -> bool:
    """Filled = not an unknown. Uses normalize.looks_unknown (the multilingual list -
    'a consultar', 'auf anfrage', ...) so unknown-stuffed multilingual records do not
    look healthy and dodge the vision probe; falls back to the small set if the
    helper isn't importable."""
    try:
        import normalize as _N
        return not _N.looks_unknown(v)
    except Exception:
        return v is not None and str(v).strip().lower() not in _SENTINELS


def _core_fill(rec: dict) -> float:
    """Fraction of CORE fields present - shared logic in _common.core_fill (merge's
    file-quality demotion uses the SAME probe, so routing and precedence agree)."""
    try:
        import _common as C
        return C.core_fill(rec)
    except Exception:
        has_size = _filled(rec.get("warehouseArea")) or _filled(rec.get("plotArea"))
        has_price = (_filled(rec.get("warehouseRent")) or _filled(rec.get("warehouseRentVal"))
                     or _filled(rec.get("landPrice")))
        core = [_filled(rec.get("city")), _filled(rec.get("developer")), has_size,
                has_price, _filled(rec.get("status"))]
        return sum(1 for c in core if c) / len(core)


def _is_poor(rec: dict) -> bool:
    """A record whose deterministic parse looks unreliable - shared logic in
    _common.record_is_poor (see _core_fill note)."""
    try:
        import _common as C
        return C.record_is_poor(rec)
    except Exception:
        if _core_fill(rec) < 0.4:
            return True
        if " option " in str(rec.get("park", "")).lower() and not _filled(rec.get("city")):
            return True
        rv = rec.get("warehouseRentVal")
        if isinstance(rv, (int, float)) and not (1.5 <= rv <= 500):
            return True
        return False


_RECFILE_CACHE: dict[str, list] = {}  # record files are multi-MB (base64 heroes) - parse each ONCE


def _load_records(f) -> list:
    key = str(f)
    if key not in _RECFILE_CACHE:
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            _RECFILE_CACHE[key] = d if isinstance(d, list) else []
        except Exception:
            _RECFILE_CACHE[key] = []
    return _RECFILE_CACHE[key]


def _deck_is_low_quality(files) -> bool:
    """True when MOST of a deck's records parsed poorly - the parser read the pages
    but could not extract usable data (a table/narrative layout it was not built
    for). Such a deck is routed to vision instead of shipping stubs. Conservative
    (>50% poor) so a clean spec-sheet deck is never re-visioned. Assessed PER
    SOURCE FILE by the caller - pooling a region's PDF with its messier PPTX twin
    used to throw away a clean PDF parse."""
    recs = []
    for f in files:
        recs += [r for r in _load_records(f) if isinstance(r, dict)]
    if not recs:
        return False
    poor = sum(1 for r in recs if _is_poor(r))
    return poor / len(recs) > 0.5


def _vkey(s: str) -> str:
    """Case-/diacritic-/SEPARATOR-insensitive comparison key, so a sub-agent's sanitised
    filename still matches its region: `East_Midlands_vision.json` == region `East Midlands`.

    Drops every non-alphanumeric SEPARATOR (space, `_`, `-`, `.`, `,`, `/`) but KEEPS letters
    that are not ASCII (`ł`, `ø`, `ß`), because those carry meaning - a blunt `[^a-z0-9]` strip
    would silently turn 'Łódź' into 'odz' and could collide with an unrelated region.

    Why separators matter: intake derives region labels from the filename segment after ' - ',
    so multi-word regions are routine, and folding ONLY spaces left the commonest sanitisation
    of all - space -> '_' or '-' - unmatched. `East_Midlands_vision.json` was then never
    recognised as an answer, the deck was re-prepped and re-emitted, the sub-agent wrote the
    same filename again, and exit 3 never converged (a deck job has no `.SKIP` escape). The
    records WERE loaded, so the run held the data and still could not pass the gate.

    NOT a transliterator: 'Cataluña' and 'Catalunya' do NOT match (ñ -> n is a diacritic fold,
    ñ -> ny is a language rule). That was true before this fold widened too; the old docstring
    claimed otherwise."""
    import unicodedata
    folded = "".join(c for c in unicodedata.normalize("NFKD", str(s))
                     if not unicodedata.combining(c)).casefold()
    return "".join(c for c in folded if c.isalnum())


def _lang_skip(canonical_obj: dict, target_code: str) -> bool:
    """Is the DATA already in the dashboard's language? (B54)

    True ONLY when at least one record declared a source language and EVERY declared code equals
    the target. Anything else - a mixed corpus, a different language, or no declaration at all -
    returns False and the exit-12 round fires exactly as it does today.

    Records that declare nothing (tracker rows, which have no interpretation agent) are assumed
    to share the declared deck language. That assumption is DISCLOSED in the SKIP note and the
    Gaps Report rather than made silently, so a broker whose tracker is in a different language
    from the brochures can see it and re-run."""
    tgt = str(target_code or "").strip().lower()
    if not tgt:
        return False
    langs = ((canonical_obj or {}).get("meta") or {}).get("sourceLanguages")
    if not isinstance(langs, dict) or not langs:
        return False
    return {str(k).strip().lower() for k in langs} == {tgt}


def _deck_label(d: dict) -> str:
    """A manifest deck's routing label, new key first. (B51)

    It is emitted as `cluster_label` because it is derived from the input FILENAME and is NOT
    evidence - three of eleven interpretation agents copied it into the record as the property's
    `region` and cited it to the deck's own page, on decks where the string appears nowhere.
    Renaming the key is what makes that copy impossible; `region` is the legacy name and is still
    READ so a warm work dir holding an older manifest keeps resuming instead of being forced
    through a fresh interpretation round."""
    if not isinstance(d, dict):
        return ""
    return str(d.get("cluster_label") or d.get("region") or "")


def _record_field_names(work: Path) -> set:
    """Field names the already-extracted records carry, for the override guard's "does this field
    exist?" test. (B7)

    The startup announcement runs BEFORE extraction, so on a first pass this is empty and the guard
    falls back to the schema/template set - which is correct, since there are no records for an
    override to correct yet. On any resumed run the extract dir is populated and this makes the
    startup check agree with merge's own, so a broker never sees an `[INVALID OVERRIDE]` warning for
    an entry merge will happily apply. Best-effort by design: a missing or malformed file
    contributes nothing and never raises."""
    out: set = set()
    try:
        for f in sorted((work / "extract").glob("*.json")):
            try:
                recs = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(recs, dict):
                recs = recs.get("records") or []
            for r in recs if isinstance(recs, list) else []:
                if isinstance(r, dict):
                    out |= {str(k) for k in r if k != "__meta"}
    except Exception:
        return out
    return out


def assign_deck_outputs(decks: list) -> list:
    """One UNIQUE `work/extract/*_vision.json` output path per deck, written onto each deck entry
    in place and returned in order. (B2)

    The output used to be DERIVED by the sub-agent as `<cluster_label>_vision.json`, while SKILL.md
    tells the orchestrator to collapse ambiguous filename clusters onto a city label before
    confirming project.yaml. Do both - the documented workflow - and four Corby brochures share one
    path: four concurrently dispatched agents write the same file and three decks vanish with no
    error, no gate and no gap line.

    The path is now EXPLICIT (the pattern the tracker `jobs` already use) and, when a label is
    shared, disambiguated by a stable hash of the SOURCE FILE - so it is deterministic and
    order-independent, and a collision cannot be expressed. A label used by exactly one deck keeps
    its clean readable filename, so the common case is unchanged.
    """
    import hashlib
    counts: dict = {}
    for d in decks:
        k = _vkey(_deck_label(d))
        counts[k] = counts.get(k, 0) + 1
    outs = []
    for d in decks:
        label = _deck_label(d) or "region"
        safe = re.sub(r"[^\w\-. ]+", "_", label).strip(" .") or "region"
        if counts.get(_vkey(_deck_label(d)), 0) > 1 or not _vkey(_deck_label(d)):
            h = hashlib.sha256(str(d.get("source_file", "")).encode("utf-8")).hexdigest()[:8]
            name = f"{safe}__{h}_vision.json"
        else:
            name = f"{safe}_vision.json"
        d["output"] = f"work/extract/{name}"
        outs.append(d["output"])
    return outs


def _deck_output_path(work: Path, deck: dict):
    """The deck's OWN interpretation output file, or None when the manifest predates B2 and carries
    no `output` (the caller then falls back to the legacy `<region>_vision.json` name match)."""
    o = str((deck or {}).get("output") or "").strip()
    if not o:
        return None
    p = Path(o)
    if p.is_absolute():
        return p
    parts = p.parts
    if parts and parts[0] == "work":
        parts = parts[1:]          # the manifest writes work-dir-relative paths
    return work.joinpath(*parts) if parts else None


def _deck_interpreted(work: Path, deck: dict) -> bool:
    """Has THIS deck been interpreted? Keyed to its own output file, so a sibling deck sharing the
    cluster label can never be mistaken for it (B2)."""
    p = _deck_output_path(work, deck)
    return bool(p and p.exists())


def _manifest_has_outputs(work: Path) -> bool:
    """Does the work dir's manifest carry per-deck `output` paths? (B2)

    When it does, interpretation completion is decided PER FILE and the old REGION-level guard is
    switched off - that guard is the other half of the same bug: with four decks sharing one cluster
    label, a single interpreted deck marked the whole region done and its three siblings were
    skipped, so their records never arrived. When it does not (a warm work dir written before this
    change, or no manifest at all on a first pass), the region-level fallback runs verbatim."""
    mf = work / "vision" / "manifest.json"
    if not mf.exists():
        return False
    try:
        decks = json.loads(mf.read_text(encoding="utf-8")).get("decks", [])
    except Exception:
        return False
    return any((d or {}).get("output") for d in decks)


def _vision_supersedes(work: Path, region: str, src_name: str) -> bool:
    """True when this region's vision transcription exists AND this very file was
    rasterised into the vision manifest - its deterministic records are then
    superseded OUTRIGHT, independent of parse quality. Supersede used to require
    a poor/0-record parse, so a garbled-but-filled twin shipped NEXT TO its own
    vision transcription and the longlist doubled (a real run: 71 cards from ~35
    properties). A twin that was never rasterised keeps its records, so a clean
    PDF in a mixed region stays safe.

    B2: keyed to the SOURCE FILE via the deck's own `output`, which is what supersession has always
    MEANT ("this very file was rasterised"). The old filename match asked whether SOME file named
    after this region existed, so two decks sharing a cluster label were indistinguishable. The
    legacy `_vkey` name match is retained for a warm work dir whose manifest carries no `output`."""
    mf = work / "vision" / "manifest.json"
    if not mf.exists():
        return False
    try:
        decks = json.loads(mf.read_text(encoding="utf-8")).get("decks", [])
    except Exception:
        return False
    mine = [d for d in decks if _vkey(str(d.get("source_file", ""))) == _vkey(src_name)]
    if not mine:
        return False
    # PREFERRED: this file's own interpretation output exists.
    if any(d.get("output") for d in mine):
        return any(_deck_interpreted(work, d) for d in mine if d.get("output"))
    # LEGACY manifest (no `output`): fall back to the region-name match, verbatim.
    rk = _vkey(region)
    extract = work / "extract"
    if not any(_vkey(f.name[:-len("_vision.json")]) == rk
               for f in extract.glob("*_vision.json")):
        return False
    return any(_vkey(_deck_label(d)) == rk for d in mine)


def _classify_unreadable(src: Path):
    """A TYPED reason ('empty file' / 'encrypted...' / 'corrupt...') when a file cannot
    be opened at all, else None (a valid-but-unparsed file -> vision). Cheap; only
    called on the 0-record path so it never double-parses a good file. P1-1: an
    unreadable input must be an honest, surfaced gap, never a silent drop."""
    try:
        if src.stat().st_size == 0:
            return "empty file (0 bytes)"
    except OSError:
        return "missing / unreadable"
    ext = src.suffix.lower()
    try:
        if ext == ".pdf":
            try:
                import fitz
            except Exception:
                try:
                    import fitz_shim as fitz
                except Exception:
                    # NO PDF BACKEND AT ALL. Returning a reason here would blame the FILE:
                    # every brochure was reported "corrupt / unreadable - re-save or unlock it",
                    # sending the broker to chase re-sends of perfectly good decks. "I cannot
                    # read PDFs here" is an ENVIRONMENT fact; None routes the deck to the
                    # interpretation/vision path instead of condemning it.
                    return None
            d = fitz.open(str(src))
            enc = getattr(d, "needs_pass", False) or getattr(d, "is_encrypted", False)
            pc = d.page_count
            d.close()
            if enc:
                return "encrypted / password-protected"
            return None if pc > 0 else "corrupt PDF (no pages)"
        if ext in (".xlsx", ".xlsm"):
            try:
                from openpyxl import load_workbook
            except Exception:
                return None  # no reader here - an ENVIRONMENT fact, not a broken file
            load_workbook(src, read_only=True).close()
            return None
    except ImportError:
        # a missing DEPENDENCY must never be reported as a corrupt FILE (it sends the broker to
        # chase a re-send of a file that is perfectly fine); the reader-failure warning above
        # already tells them this environment cannot read that type
        return None
    except Exception as e:
        m = str(e).lower()
        if "password" in m or "encrypt" in m:
            return "encrypted / password-protected"
        # DO NOT CONDEMN A FILE THIS CODE MERELY COULD NOT OPEN. "corrupt / unreadable" is a
        # claim about the FILE, and it sends the broker to chase a re-send. But this branch
        # also catches every environment failure that is not an ImportError: a pdfminer /
        # pdfium decode failure under the fitz_shim tier, a Windows file lock, an unhydrated
        # OneDrive placeholder. Only say "corrupt" where the evidence supports it - a real
        # structural complaint from the reader - and otherwise report honestly that we could
        # not open it here, which routes the deck to interpretation instead of the bin. (B15)
        # Precise phrases only. A loose token is worse than none here: "not a" matches inside
        # "canNOT Access the file", so a Windows lock was condemned as a corrupt document.
        _structural = ("cannot open", "no objects found", "damaged", "broken xref",
                       "xref", "startxref", "eof marker", "not a pdf", "not a zip",
                       "file is not a", "syntax error", "corrupt")
        if any(t in m for t in _structural):
            return "corrupt / unreadable"
        return f"could not be opened in this environment ({str(e).splitlines()[0][:70]})"
    return None


ATTEMPT_WARN = 4  # consecutive re-emissions of the SAME exit code before we say it is stuck


def _bump_attempts(work: Path) -> dict:
    """Read (and increment) the per-work-dir invocation counter used by the round-trip backstop.
    Returns the prior state: {"n": total invocations, "last": last non-zero exit, "streak": how
    many consecutive times that same code was emitted}. Best-effort - a cache failure must never
    break a run, so every error degrades to an empty state."""
    f = work / "attempts.json"
    try:
        st = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(st, dict):
            st = {}
    except Exception:
        st = {}
    st["n"] = int(st.get("n") or 0) + 1
    _write_attempts(work, st)
    return st


def _write_attempts(work: Path, st: dict) -> None:
    # _common is imported INSIDE functions throughout run.py (so the module imports cleanly on a
    # host missing an optional dep) - do the same here, or this silently no-ops on a NameError.
    try:
        import _common as _C
        _C.atomic_write_text(work / "attempts.json", json.dumps(st, ensure_ascii=False))
    except Exception:
        pass


def _clear_attempts(work: Path) -> None:
    """A run that reached the end clears the streak, so a LATER round-trip (a gate sign-off, a
    re-run after a data fix) starts from zero instead of inheriting a stale count."""
    _write_attempts(work, {"n": 0})


def _record_exit(work: Path, code: int, prior: dict) -> int:
    """Record a non-zero exit and return the consecutive streak for that code."""
    streak = (int(prior.get("streak") or 0) + 1) if prior.get("last") == code else 1
    _write_attempts(work, {"n": int(prior.get("n") or 1), "last": code, "streak": streak})
    return streak


def _exit_round_trip(work: Path, code: int, prior: dict, what: str) -> None:
    """The ONE exit path for every orchestrator round-trip. Records the streak and, once the same
    request has been re-emitted ATTEMPT_WARN times in a row, prints a plain diagnosis before
    exiting - the run is not making progress and something upstream is not converging. This does
    NOT block or change the exit code: the orchestrator may legitimately need several rounds, and
    a wrong bound would be worse than none. It converts a silent livelock into a visible one."""
    streak = _record_exit(work, code, prior)
    if streak >= ATTEMPT_WARN:
        msg = (f"This step has now been asked for {streak} times in a row without the run moving "
               f"on ({what}). Something in that answer is not being recognised - stop re-running "
               f"and check it rather than trying again.")
        print(msg if QUIET else f"\nNOT CONVERGING: {msg}")
        # The livelock diagnosis is a HANDOFF instruction, not an aside: it is the one
        # line telling the orchestrator to stop looping. It must survive the default
        # (quiet) mode and reach stdout, or the guard warns nobody. (B27)
        _say_orchestrator(
            f"(orchestrator: exit {code} re-emitted {streak}x consecutively. The last answer did "
            f"not satisfy the guard - inspect what was written vs what is read (a key/filename "
            f"normalisation mismatch, an id not echoed, a declined answer the guard cannot see, "
            f"or a sentinel written to the wrong path). Do NOT loop again; diagnose. "
            f"work/attempts.json holds the streak.)")
    sys.exit(code)


def _pair_answered(md, g) -> bool:
    """Is this grey pair covered by a RECOGNISED verdict? Both accepted shapes, and junk
    never counts - an unrecognised answer must re-ask, not silently pass."""
    if not isinstance(md, dict):
        return False
    v = md.get(g.get("pair_id"))
    return (v in ("same", "different")
            or (isinstance(v, dict) and v.get("verdict") in ("same", "different")))


def _settled_clusters(clusters: list, grey: list, md, all_recs: list) -> list:
    """The clusters whose membership NO outstanding pair answer can change. (B20)

    Exit 10 used to suppress EVERY value conflict while any grey pair was open, which
    guaranteed a second round-trip whenever a run had both kinds of ambiguity. It cannot
    simply stop doing that: a grey verdict changes cluster membership, which changes both
    which conflicts exist and their `conflict_id` (derived from `cluster_key`), so a
    conflict adjudicated against unfinished clustering is orphaned and re-asked. A live
    12-property run saw the set grow 44 -> 78 across two rounds for exactly that reason.

    But a cluster is PROVABLY final when none of its own members appears in an unanswered
    pair. Dedupe only ever ADDS links, so such a cluster cannot shrink; and for an outside
    record to join it there would have to be a pair between that record and one of these
    members - which would be auto (already applied), forbidden (never applies) or an
    unanswered grey (excluded by the test). Checking every member, not just the pair
    endpoints, is what makes it transitive: a clustermate of an open pair taints the whole
    cluster.

    Conflicts from these clusters carry exactly the ids the settled clustering will
    produce, so the answers stay valid and the second round shrinks - often to nothing."""
    if not grey:
        return list(clusters)
    open_ids: set = set()
    for g in grey:
        if _pair_answered(md, g):
            continue
        for k in ("a_idx", "b_idx"):
            i = g.get(k)
            if isinstance(i, int) and 0 <= i < len(all_recs):
                open_ids.add(id(all_recs[i]))
        for k in ("a", "b"):  # tolerate a pair carrying only the records
            if isinstance(g.get(k), dict):
                open_ids.add(id(g[k]))
    if not open_ids:
        return list(clusters)
    return [cl for cl in clusters if not any(id(r) in open_ids for r in cl)]


def _load_match_decisions(work: Path):
    """Read work/match_decisions.json MERGED over a durable settled copy. (B20)

    Round 2 no longer re-lists the pairs it already settled, and its instructions say not
    to touch this file - but an instruction is not a guard. A literal-minded sub-agent that
    writes `{}` here would erase round 1's verdicts and re-open the matching round, which
    is precisely the third round the change exists to prevent. So every recognised verdict
    is mirrored into work/match_settled.json, and a later read is layered on top of it: a
    genuine NEW answer still wins, an empty file loses nothing."""
    cur = None
    f = Path(work) / "match_decisions.json"
    if f.exists():
        try:
            cur = _index_decisions(json.loads(f.read_text(encoding="utf-8")),
                                   ("pair_id", "id"))
        except Exception:
            cur = None  # malformed/half-written -> treat as absent (re-emit + exit 10)
    keep = Path(work) / "match_settled.json"
    prev = {}
    try:
        prev = json.loads(keep.read_text(encoding="utf-8"))
        if not isinstance(prev, dict):
            prev = {}
    except Exception:
        prev = {}
    if cur is None and not prev:
        return None
    merged = {**prev, **(cur or {})}
    good = {k: v for k, v in merged.items()
            if _pair_answered(merged, {"pair_id": k})}
    if good and good != prev:
        # _common is imported INSIDE functions throughout run.py (so the module imports
        # cleanly on a host missing an optional dep) - do the same here.
        try:
            import _common as _C
            _C.atomic_write_text(keep, json.dumps(good, ensure_ascii=False, indent=2))
        except Exception:
            pass
    return merged or None


def _index_decisions(parsed, id_keys: tuple) -> dict | None:
    """TOLERANT read of a sub-agent decisions file: accept the documented flat
    `{"<id>": {...}}` map OR a LIST of entries carrying their own id
    (`{"decisions": [{"pair_id": ..., "verdict": ...}, ...]}`), and return the flat map either
    way. None when nothing usable is present.

    Why this is tolerant rather than strict: the coverage guards below test `md.get(pair_id)`, so
    a list-shaped answer yielded None for EVERY id, the same request was re-emitted, and exit 10
    looped forever - and exits 8/9/10 have no `.SKIP` escape, so there was no way out. The
    list shape is not a malformed answer; it is the shape a model naturally reaches for (the
    skill's own `evals/cowork_sim.py` emits it, which is how this was caught), and it carries
    exactly the same information. The pipeline is LLM-driven by design: a guard must be WIDER
    than the set of legitimate answers, never narrower. Nothing here interprets a VERDICT - the
    callers still validate every value - this only finds where the answers live.

    `id_keys` are tried in order for each entry, so one helper serves both files
    (`pair_id` for match decisions, `conflict_id`/`field` for field decisions)."""
    if not isinstance(parsed, (dict, list)):
        return None
    if isinstance(parsed, dict):
        # a flat map already? (any value that is not itself a list of entries)
        lists = [v for v in parsed.values() if isinstance(v, list)]
        if not lists:
            return parsed
        # a wrapper such as {"decisions": [...]} / {"resolutions": [...]} / {"picks": [...]}
        entries: list = []
        for v in lists:
            entries.extend(v)
        flat = {k: v for k, v in parsed.items() if not isinstance(v, list)}
    else:
        entries, flat = list(parsed), {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        for k in id_keys:
            if isinstance(e.get(k), (str, int)) and not isinstance(e.get(k), bool):
                flat.setdefault(str(e[k]), e)
                break
    return flat or None


def _gaps_to_chase(canonical_path, failed_preps, photo_doubts, unreadable_inputs, yield_notes) -> bool:
    """True when the Gaps Report has substantive content the broker should chase.
    Mirrors EVERY populated section deliver.gaps_report emits - per-property tbd CORE
    fields, enrichment gaps, source conflicts, unmapped tracker columns, unreadable
    inputs and photo-match doubts - so the quiet 'Done' note never steers the broker
    away from a report that has real content (P3-10)."""
    if failed_preps or photo_doubts or unreadable_inputs or yield_notes:
        return True
    try:
        cj = json.loads(Path(canonical_path).read_text(encoding="utf-8"))
    except Exception:
        return False
    meta = cj.get("meta", {})
    if meta.get("enrichmentGaps") or meta.get("conflicts"):
        return True
    import deliver as _deliver
    return any(_deliver._is_tbd(p.get(f))
               for p in cj.get("properties", []) for f in _deliver.CORE)


def _report_pdf_engine() -> None:
    """Load + report the active PDF engine BEFORE any extraction, so the run's native-first
    intent is visible and verifiable: prefer system PyMuPDF, else the bundled vendor/ wheel,
    and ONLY then the pdfplumber shim (which loses page rendering and needlessly pushes decks
    to the vision path). Calling ensure() here also unpacks the wheel up front instead of
    lazily on the first PDF open - i.e. the wheel is used first, vision only as a last resort."""
    status, vw = "missing", None
    try:
        import _vendor_wheels as vw
        status = vw.ensure("fitz", "pymupdf")  # 'system'|'vendored'|'missing'; NO-OP if already present
    except Exception as e:
        status, vw = "missing", None
    if status in ("system", "vendored"):
        try:
            import fitz
            ver = getattr(fitz, "__version__", getattr(fitz, "VersionBind", "?"))
        except Exception:
            ver = "?"
        src = "system install" if status == "system" else "bundled vendor/ wheel"
        print(f"PDF engine: native PyMuPDF {ver} ({src}) - full-fidelity extraction.")
    else:
        try:
            import fitz_shim
            tier = getattr(fitz_shim, "ENGINE", "shim")
        except Exception:
            tier = "shim"
        why = getattr(vw, "_LAST_ERROR", "") if vw else ""
        print("PDF engine: fitz_shim fallback ({}) - native PyMuPDF unavailable, so extraction "
              "is degraded and more decks may route to vision.".format(tier)
              + (f" [{why}]" if why else ""))
        if not QUIET:
            print("(orchestrator: the bundled vendor/ PyMuPDF wheel did NOT load"
                  + (f" - {why}" if why else "")
                  + "; use the native engine before resorting to the vision pass.)", file=sys.stderr)


def _say_orchestrator(msg: str) -> None:
    """Print a HANDOFF instruction - the machine-readable product of a terminal exit.

    ALWAYS stdout, in both verbosity modes. These lines used to go to stderr, which
    this project's own environment rule says `mcp__shell` does not surface - and
    SKILL.md makes mcp__shell the spine command, so the one line telling the
    orchestrator what to do next was invisible on the documented path. Diagnostic
    asides ("optional reader X unavailable", "image pre-warm skipped") stay on
    stderr; only the next-action instruction comes through here. (B27)"""
    print(msg)


def _yield_stdout_lines(notes, link_ix, report_path) -> list[str]:
    """The `[yield]` block's stdout.

    Judgement-bearing notes (thin parse of a rich sheet, rent_unit_assumed,
    area_unit_suspect, area_out_of_band, semantic_disagreements) print VERBATIM - a
    thin parse of a 75-column tracker must be LOUD. Linked-source notes collapse to a
    count: in a real run they are 24+ full URLs printed immediately above the report
    that already lists every one of them in full. (B23)"""
    out = [f"  [yield] {n[:200]}" for i, n in enumerate(notes) if i not in link_ix]
    if link_ix:
        out.append(f"  [yield] {len(link_ix)} linked source(s) in cells "
                   f"(not embedded; fetch separately)")
    out.append(f"  (full list -> {report_path})")
    return out


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--client", default="Client")
    ap.add_argument("--no-pptx", action="store_true", help="skip pptx (use pdf only)")
    ap.add_argument("--geocode", action="store_true")
    ap.add_argument("--pois", action="store_true")
    ap.add_argument("--osrm", action="store_true")
    ap.add_argument("--regions", action="store_true")
    ap.add_argument("--language", default="",
                    help="dashboard chrome language (Stage-0 Q3). Overrides project.yaml "
                         "output.language; blank = use project.yaml (default English).")
    ap.add_argument("--verbose", action="store_true",
                    help="developer mode: print every step's sub-output. Quiet is the "
                         "DEFAULT; this opts out of it.")
    ap.add_argument("--quiet", action="store_true",
                    help="(NO-OP, kept for compatibility) quiet is the default - pass "
                         "--verbose to opt out.")
    ap.add_argument("--resume", dest="resume", action="store_true", default=True,
                    help="(DEFAULT) skip stages whose output is already current "
                         "(intake/extract/merge/enrich/build); gates and the freeze always re-run. "
                         "Built for short-shell-cap sandboxes (Cowork) and the vision re-run.")
    ap.add_argument("--no-resume", dest="resume", action="store_false",
                    help="recompute every stage from scratch")
    return ap


def _resolve_quiet(args) -> bool:
    """Quiet is the DEFAULT; `--verbose` opts out and WINS over an explicit `--quiet`.

    `--quiet` survives as an accepted no-op rather than being removed: SKILL.md and
    ~35 `_run_spine` calls in extract_test.py still pass it, and deleting the option
    would turn argparse's SystemExit(2) into a wall of reds for the wrong reason. (B27)"""
    return not bool(getattr(args, "verbose", False))


def main() -> None:
    ap = _build_parser()
    args = ap.parse_args()
    global QUIET, RESUME
    QUIET = _resolve_quiet(args)
    RESUME = args.resume
    try:  # never let a non-UTF-8 console crash a broker-facing run
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    sys.path.insert(0, str(HERE))

    # PREFLIGHT: stop with ONE plain sentence if the skill copy is incomplete (a
    # flaky/partial sandbox mount can deliver truncated helpers) rather than dying
    # later on an opaque mid-file SyntaxError. See helpers/preflight.py + SKILL.md.
    try:
        import preflight
        _probs = preflight.problems()
    except Exception:
        _probs = []  # preflight itself unavailable -> don't block; rely on the imports below
    if _probs:
        print("The skill files didn't load correctly. Please restart the session and try again.")
        if not QUIET:
            print("(technical detail: " + "; ".join(_probs[:12]) + ")", file=sys.stderr)
        sys.exit(4)  # distinct from "no sources" (2) - a different fix for the orchestrator

    # Import the helper modules ONCE (here, not at module load, so run.py still
    # imports cleanly on a machine missing an optional reader). The heavy deps
    # (fitz/Pillow/rapidfuzz, pulled in by merge) are loaded a single time and
    # reused by every stage below.
    import build_dashboard
    import contact_sheet
    import deliver
    import enrich
    import gate_runner
    import i18n as I18N        # Phase 2: SUPPORTED/needs_fallback + the exit-11 fallback step
    import intake
    import ledger
    import merge
    import translate
    import web_enrich
    # Pillow has NO shim (unlike PyMuPDF->fitz_shim / rapidfuzz->rapidfuzz_shim): if it is
    # absent, images.py degrades the WHOLE hero pipeline to the placeholder. Say so loudly -
    # it materially changes the deliverable (every photo becomes a placeholder) - so the
    # broker is never surprised by a grey grid. Fires ONLY when Pillow is genuinely missing;
    # the normal (Pillow-present) run prints nothing here.
    import images
    if not getattr(images, "_HAS_PIL", True):
        print("Note: the image library (Pillow) is not available here, so every option will "
              "show a placeholder instead of a photo. The data, map and filters are unaffected.")
        if not QUIET:
            print("(orchestrator: images._HAS_PIL is False - heroes degrade to the placeholder "
                  "asset; the placeholder-rate gate is image-source-aware so the run still ships.)",
                  file=sys.stderr)
    _report_pdf_engine()  # native PyMuPDF (system or bundled wheel) first; shim/vision last
    extant = {}
    reader_failures: list = []
    for name in ("extract_pdf", "extract_pptx", "extract_xlsx", "vision_prep", "interpret_prep"):
        try:
            extant[name] = __import__(name)
        except Exception as e:  # optional reader / missing dep -> degrade, do not crash
            extant[name] = None
            reader_failures.append((name, f"{type(e).__name__}: {e}"))
    if reader_failures:
        # PRINT UNCONDITIONALLY. This was `if not QUIET`, and SKILL.md tells the orchestrator to
        # run the spine with --quiet - so with openpyxl missing, the Excel availability tracker
        # (typically the RICHEST source: specs, rents and areas for every property) was skipped
        # with NOT ONE WORD anywhere: no records, no unreadable.json entry, no note. Losing a
        # whole source is a data-loss event, not verbose chatter.
        _kinds = {"extract_xlsx": "Excel/CSV trackers", "extract_pdf": "PDF brochures",
                  "extract_pptx": "PowerPoint brochures", "vision_prep": "image-only decks",
                  "interpret_prep": "brochure interpretation"}
        _lost = ", ".join(_kinds.get(n, n) for n, _ in reader_failures)
        print(f"WARNING: I cannot read {_lost} in this environment - any such file in your folder "
              f"will be SKIPPED, not merely unparsed. The rest of the run continues.")
        for _n, _err in reader_failures:
            print(f"(optional reader {_n} unavailable: {_err})", file=sys.stderr)

    folder = Path(args.folder).resolve()
    work = Path(args.work).resolve()
    extract = work / "extract"
    extract.mkdir(parents=True, exist_ok=True)
    # ROUND-TRIP BACKSTOP. Every non-zero exit is a request to the orchestrator, and NOTHING in
    # the skill bounded how many times the same request could be re-emitted - so any guard that
    # is narrower than the set of legitimate answers degrades into a SILENT infinite loop rather
    # than a visible failure. Five such guards were found and fixed; this exists so the sixth is
    # DIAGNOSED instead of burning a broker's afternoon. It counts consecutive re-emissions of
    # the SAME exit code and, past the threshold, says plainly what is stuck and what to do -
    # it never blocks a run that is making progress (any different exit code, or exit 0,
    # clears the counter).
    _attempts = _bump_attempts(work)
    # POINT enrich's module-level cache dir at the WORK dir for the WHOLE process. It defaults
    # to the READ-ONLY skill dir (enrich.CACHE_DIR = SEED_DIR = <skill>/reference) and was only
    # ever re-pointed INSIDE enrich.main() via --cache-dir. Any code path that reads an enrich
    # cache WITHOUT enrich having run in this process therefore read <skill>/reference/... -
    # a path that never exists. That silently broke the exit-3 region-label convergence guard
    # on the RESUME path: with enrichment resume-skipped, `_region_labels_answered_keys()`
    # returned an empty set, so an already-answered (esp. DECLINED) label was re-asked and the
    # run oscillated forever - the very loop the answered-keys view was added to close. Setting
    # it here is a no-op for the enrich-ran path (enrich.main() assigns the same value).
    enrich.CACHE_DIR = work

    # DURABLE MANUAL CORRECTIONS (P1-4): list them at STARTUP so a stale one cannot rot unnoticed.
    # PRINTED UNCONDITIONALLY, like the reader-failure lines above: SKILL.md tells the orchestrator
    # to run the spine with --quiet, so `if not QUIET` would hide this exactly when it matters. A
    # correction that has silently stopped applying is a DATA-LOSS event, not verbose chatter.
    # --quiet governs only the explanatory footnote. This is the earliest point at which `work` is
    # resolved and before any stage can exit, so it is announced even on a run that dies at intake.
    _ov_path = work / "overrides.json"
    if _ov_path.exists():
        _ovs, _ov_errs = merge.load_overrides(_ov_path,
                                              extra_fields=_record_field_names(work))
        print(f"Manual corrections active ({len(_ovs)} in {_ov_path.name}) - re-applied to the "
              f"freshly extracted data every run:")
        for _o in _ovs:
            _w = _o["where"]
            _at = (f"{_w.get('sheet') or ''}!r{_w['row']}" if _w.get("row") is not None
                   else (f"page_no {_w['page_no']}" if _w.get("page_no") is not None
                         else "the whole file"))
            print(f"  - {_o['id']}: {_w['source_file']} {_at} -> "
                  + ", ".join(f"{k} = {v!r}" for k, v in _o["set"].items())
                  + (" [expect ok]" if _o.get("expect") else " [no `expect` guard]")
                  + f"  ({_o.get('why', '')})")
        for _e in _ov_errs:
            print(f"  [INVALID OVERRIDE] {_e} - this entry does NOTHING until it is fixed.")
        if not QUIET:
            print("(an override matching no record is reported as STALE right after the merge "
                  "step and in the Gaps Report. work/extract is DERIVED - never hand-edit it; "
                  "a hand-edit is discarded the next time extraction re-runs.)", file=sys.stderr)

    # Stage 0 - intake
    proj = work / "project.yaml"
    step("Scanning the folder")
    # work/intake_clusters.json is the orchestrator's LLM-refined filename->region label
    # cache; including it in the resume inputs means WRITING the cache invalidates a stale
    # inventory.json/project.yaml so the next pass re-clusters from the cache (then keeps
    # the confirmed project.yaml). Its absence forces the deterministic regex - unchanged.
    if _is_current(work / "inventory.json", [folder, work / "intake_clusters.json"]) and proj.exists():
        _resumed("folder scan")
    else:
        call(intake, folder, "--out-dir", work, "--client", args.client)
    inv = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
    # INTAKE-001: surface byte-identical duplicate inputs intake skipped (extracted once,
    # not twice) - honest + quiet-aware, never a silent drop. (.get for an old inventory.)
    _dups = inv.get("skipped_duplicates") or []
    if _dups:
        _dmsg = "; ".join(f"{d['file']} (identical to {d['duplicate_of']})" for d in _dups)
        print((f"Note: skipped {len(_dups)} duplicate file(s) - exact copies of inputs I "
               f"already have: {_dmsg}") if QUIET
              else f"NOTE: skipped {len(_dups)} byte-identical duplicate input(s): {_dmsg}")
    cfg = load_yaml(proj)
    enr = cfg.get("enrichment", {})
    # dashboard chrome language (Stage-0 Q3): the --language flag overrides project.yaml
    # output.language; blank in both -> English. project.yaml is already a merge input,
    # so a changed language invalidates the cached merge (the resume predicate re-fires).
    lang = args.language or (cfg.get("output", {}) or {}).get("language", "English")

    # --- Phase 2: non-bundled-language FALLBACK (exit 11; mirrors exit 3/9/10) -------
    # Runs on EVERY invocation, BEFORE the expensive merge/enrich, so it fails fast. A
    # language OUTSIDE the bundled 13 but still SUPPORTED (any European Latin-script
    # language) is translated ONCE in Cowork, cached in the work dir, then baked into
    # canonical.meta.ui_overrides by merge (--ui-overrides) so render()/validate-html
    # reproduce it byte-for-byte from canonical. Graceful: an UNSUPPORTED language (an
    # unsupported script / nonsense) -> EN (no request, a printed note); a .SKIP decline -> EN; a
    # missing/corrupt cache -> re-request (or EN once declined) - never a crash.
    ui_overrides_cache = None  # set to the cache Path when a valid fallback cache exists
    code = I18N.normalize_lang(lang)
    if I18N.needs_fallback(lang):
        i18n_dir = work / "i18n"
        cache = i18n_dir / f"{code}.json"
        skip = i18n_dir / f"{code}.SKIP"
        request = i18n_dir / f"{code}_request.json"
        want_sha = I18N.en_sha()
        have = I18N.load_fallback_cache(cache) if cache.exists() else None
        have_sha = None
        if cache.exists():
            try:
                have_sha = json.loads(cache.read_text(encoding="utf-8")).get("_en_sha")
            except Exception:
                have_sha = None
        if skip.exists():
            # the orchestrator declined the translate round -> render in English. Honest
            # note so the broker is never surprised by an English dashboard for a non-EN ask.
            print((f"Note: '{lang}' is a supported language but isn't bundled, and a translation "
                   f"was declined (work/i18n/{code}.SKIP) - the dashboard will be in English.")
                  if QUIET else
                  f"NOTE: fallback declined for '{lang}' ({code}.SKIP present) -> English chrome.")
        elif have is not None and have_sha == want_sha:
            # a valid, current cache exists -> thread it into the merge bake (below)
            ui_overrides_cache = cache
        else:
            # no valid/current cache -> write the request manifest, instruct, and exit 11.
            # A stale cache (EN changed -> have_sha != want_sha) is re-requested the same way.
            i18n_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "code": code,
                "language": lang,
                "locale": I18N.locale_for(lang),
                "en_sha": want_sha,
                "instructions": (
                    f"Translate EVERY value in `strings` to {lang}. Keep the JSON KEYS exactly; "
                    "keep the {area}/{unit}/{count} placeholders (hero_lede_fmt carries "
                    "{count}), the ONE <em>...</em> pair in hero_title_html, the "
                    "&amp;/&lt;/&gt; HTML entities, any "
                    "leading glyph (e.g. the '●' bullet), and the invariants CBRE / OSRM / "
                    "BREEAM / HGV / PPS / EU27 / REIT / km verbatim. Do NOT translate DATA or the "
                    "'tbd'/'—' sentinel. Add a top-level \"_en_sha\":\"" + want_sha + "\" key, "
                    f"write the flat {{key: value}} (+ _en_sha) to work/i18n/{code}.json, then re-run "
                    "the SAME command. (Or `type nul > work/i18n/" + code + ".SKIP` to fall back to "
                    "English.) Blind-verify it as G-i18n (an ISOLATED reviewer, not the translator) "
                    "before shipping."
                ),
                "cache_path": str(cache),
                "skip_path": str(skip),
                "strings": I18N.EN,
            }
            request.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            stale = cache.exists() and have_sha != want_sha
            _stale_quiet = "(The English baseline changed, so the old translation is stale.) " if stale else ""
            _stale_orch = " and the cache is STALE (EN changed)" if stale else ""
            if QUIET:
                print(f"'{lang}' isn't one of the built-in dashboard languages, so I need it "
                      f"translated once. {_stale_quiet}I've written what to translate to {request}.")
            else:
                print(f"\nLANGUAGE FALLBACK NEEDED: '{lang}' ({code}) is supported but not "
                      f"bundled{_stale_orch}. Dispatch a translation sub-agent: translate the "
                      f"strings in {request} to {lang}, save the flat {{key:value}} (+ "
                      f"\"_en_sha\":\"{want_sha}\") to {cache}, then re-run the SAME command. "
                      f"(Or `type nul > {skip}` to fall back to English.) Blind-verify it as "
                      f"G-i18n before shipping.")
            _exit_round_trip(work, 11, _attempts, "a dashboard-language translation")

    # PREFLIGHT ROADMAP: a deterministic plan from what intake ACTUALLY found, so the
    # orchestrator starts knowing what is there and which handoffs to expect (which exit
    # codes may fire) - not guessing. Counts are facts; the handoffs are the conditional
    # branches of the loop documented in SKILL.md "Driving the run".
    try:
        _cl = inv.get("clusters") or {}
        _npdf = sum(len(c.get("pdfs") or []) for c in _cl.values())
        _nppt = sum(len(c.get("pptxs") or []) for c in _cl.values())
        _nx, _nem, _nim = len(inv.get("xlsx") or []), len(inv.get("emails") or []), len(inv.get("images") or [])
        _reqs = [n for n, on in (("geocode", args.geocode), ("pois", args.pois),
                                 ("osrm", args.osrm), ("regions", args.regions)) if on or enr.get(n)]
        _expect = []
        if _npdf or _nppt:
            _expect.append("brochure decks -> interpretation (exit 3: text or raster per the manifest mode); "
                           "textless brochures with known records -> photo-match (exit 9)")
        if _nx:
            _expect.append("tracker(s) -> column mapping (exit 3: an isolated sub-agent maps the "
                           "header, or a .SKIP keeps the dictionary)")
        # cross-source matching only has grey pairs when >1 property source can describe
        # the same property (a tracker + brochures, emails + a tracker, etc.)
        _n_src_kinds = sum(1 for k in (_npdf or _nppt, _nx, _nem, _nim) if k)
        if _n_src_kinds > 1:
            _expect.append("ambiguous cross-source pairs -> match adjudication (exit 10: an isolated "
                           "sub-agent confirms same/different per work/match_candidates.json)")
        if {"geocode", "pois", "osrm"} & set(_reqs):
            _expect.append("coordinates/drive-times -> web enrichment (exit 8) when the shell is offline")
        print(f"Plan: {_npdf} PDF + {_nppt} PPTX brochure(s) across {len(_cl)} region(s), "
              f"{_nx} tracker(s), {_nem} email(s), {_nim} image(s)"
              + (f"; enrichment: {', '.join(_reqs)}" if _reqs else "; no enrichment requested") + ".")
        if _expect:
            print("  Expect: " + "; ".join(_expect)
                  + ". After ANY handoff, re-run the SAME command (resume continues).")
    except Exception:
        pass  # the roadmap is advisory - never let it break a run

    # Stage 1 - extract. Brochure decks (PDF/PPTX) are no longer parsed for FIELDS by
    # the label-dictionary parser (a losing battle for the heterogeneous long tail);
    # an isolated INTERPRETATION sub-agent structures them instead, reading the
    # deck's extracted TEXT when it has one (cheap + accurate) and the page rasters
    # only when the text layer is garbled/absent. xlsx trackers and emails stay on
    # their deterministic, reliable extractors below. extract_pdf is retained (its
    # _find_labels is a text-quality signal, and pdf_cases still unit-tests it) but
    # is no longer the brochure record source.
    step("Reading the brochures")
    record_files = []
    # (brochure, region, country) decks to send to the interpretation sub-agent
    # (text or raster, decided per deck by interpret_prep). Named vision_targets so
    # the photo-match step + manifest writer downstream are unchanged.
    vision_targets = []
    unreadable_inputs = []  # (filename, typed reason) - surfaced honestly, never silently dropped

    def _count(f):
        return len(_load_records(f))

    # NEEDS-RASTER ESCALATION (consume it BEFORE vision_done / vision_validate): a text
    # deck the interpretation sub-agent found garbled/unusable writes a stub record
    # {__meta:{source_file, needs_raster:true}} into <region>_vision.json
    # (reference/interpretation.md). That stub is NOT a record - it is a request to
    # re-prep the deck in RASTER mode. Strip it here (so it can never wedge
    # has_vision/_vision_supersedes/vision_validate at exit 3) and force its deck onto the
    # raster path on THIS pass. Ephemeral - re-derived from the CURRENT stubs each run, so
    # once the deck is rasterised + re-interpreted into real records nothing escalates.
    force_raster: set = set()
    for vf in sorted(extract.glob("*_vision.json")):
        recs = _load_records(vf) or []
        flagged = [r for r in recs if isinstance(r, dict)
                   and (r.get("__meta") or {}).get("needs_raster")]
        if not flagged:
            continue
        for r in flagged:
            sf = (r.get("__meta") or {}).get("source_file")
            if sf:
                force_raster.add(sf)
        keep = [r for r in recs if r not in flagged]
        try:  # keep any REAL records in a mixed file; delete a pure escalation request
            if keep:
                vf.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
            else:
                vf.unlink()
            _RECFILE_CACHE.pop(str(vf), None)  # we just mutated the file on disk - drop the
            #                                    stale parse (_load_records populated it above)
        except Exception:
            pass

    # prior vision transcriptions, matched case-/diacritic-INSENSITIVELY (module
    # _vkey): a vision sub-agent that normalised the filename ('Cataluña' ->
    # 'Catalunya_vision.json') must still supersede its region, or the region is
    # re-routed to vision forever
    vision_done = {_vkey(f.name[:-len("_vision.json")]) for f in extract.glob("*_vision.json")}
    # B2: with a per-deck `output` manifest, completion is decided PER FILE by _vision_supersedes
    # and the region-level guard below is disabled - it is the other half of the collapsed-label
    # bug (one interpreted deck marking its three siblings done, so their records never arrived).
    _per_deck_outputs = _manifest_has_outputs(work)

    def _slug(rel) -> str:
        """Distinct extract-output name per brochure (subfolder-aware), so a region
        with several PDFs writes several record files instead of one clobbered slot."""
        base = str(Path(rel).with_suffix(""))
        return re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")[:60] or "file"

    def _ext_out(rel, suffix):
        """Bounded + content-hashed extract path: a very long brochure name no longer
        overflows MAX_PATH (silently dropping the file), and the 8-char hash makes the
        40-char slug truncation collision-proof. Deterministic: same input, same name."""
        import hashlib
        h = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:8]
        return extract / f"{_slug(rel)[:40]}_{h}_{suffix}.json"

    for region, cl in inv["clusters"].items():
        country = cl.get("country") or "??"
        # this region's records are already in place (interpreted on a prior pass). LEGACY ONLY:
        # with per-deck outputs this is False and each file is judged on its own (B2).
        has_vision = (not _per_deck_outputs) and (_vkey(region) in vision_done)
        # cluster brochures are LISTS (every file kept); the singular keys are the
        # legacy one-slot layout, still honoured for an old work dir's inventory
        pdfs = cl.get("pdfs") or ([cl["pdf"]] if cl.get("pdf") else [])
        pptxs = (cl.get("pptxs") or ([cl["pptx"]] if cl.get("pptx") else [])) \
            if not args.no_pptx else []
        # EVERY brochure deck (PDF + PPTX) goes to the interpretation sub-agent - the
        # deterministic label parser is no longer the brochure record source. A deck
        # whose region already has interpreted records (this re-run, or a prior one)
        # is left to the supersede logic below; an encrypted/corrupt/empty file is an
        # honest GAP, never an interpretation target.
        for rel in [*pdfs, *pptxs]:
            src = folder / rel
            # a deck the sub-agent escalated to raster (needs_raster) must be re-prepped,
            # NOT treated as already-done by the region-level supersede/has_vision guard
            must_raster = src.name in force_raster
            if not must_raster and (_vision_supersedes(work, region, src.name) or has_vision):
                if not QUIET:
                    print(f"  ({src.name}: this region's records are already interpreted - "
                          f"its brochure is superseded by the transcription)")
                continue
            bad = _classify_unreadable(src)
            if bad:
                unreadable_inputs.append((src.name, bad))
                if not QUIET:
                    print(f"  ({src.name}: {bad} - skipped; logged to the Gaps Report)")
                continue
            vision_targets.append((src, region, country))
            if not QUIET:
                print(f"  ({src.name}: sending it to the interpretation sub-agent)")

    # xlsx: a property tracker contributes records; a questionnaire contributes the
    # client's requirements (size/must-haves) -> canonical.meta.requirements
    requirements: dict = {}
    yield_notes: list[str] = []  # extraction-yield findings (thin parse of a rich sheet)
    link_note_ix: set[int] = set()  # which yield_notes are linked-source lines (B23):
    # they go into the report in full but collapse to a COUNT on stdout. Indices, not a
    # string match, so the report's byte order and content are untouched.
    interpret_trackers: list = []  # tracker sheets OFFERED to the mapping sub-agent (exit 3)

    def _tracker_struct_hash(structs) -> str:
        """sha1[:8] over the deterministically-serialised tracker STRUCTURE (headers +
        sample rows + region + country) - the bytes handed to the mapping sub-agent. A
        re-export with cosmetic byte/mtime changes but the same columns hashes the same,
        so the cached LLM map (and thus the records + ledger) is byte-stable on resume."""
        import hashlib
        payload = json.dumps(structs, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]

    if not extant["extract_xlsx"]:
        # A WHOLE SOURCE MUST NEVER VANISH WITHOUT A RECORD. With no spreadsheet reader the
        # loop below is skipped entirely and nothing appended these files to
        # unreadable_inputs - so unreadable.json, the Gaps Report and _gaps_to_chase all
        # omitted them, while the Plan line still promised "N tracker(s) -> column mapping"
        # and the exit-2 message told the broker to add trackers they had already supplied.
        # The reader-failure warning above is printed, but a console line is not a durable
        # record. (B15)
        for _xl in inv.get("xlsx", []):
            unreadable_inputs.append(
                (Path(_xl).name,
                 "no spreadsheet reader available in this environment (openpyxl missing) - "
                 "the file is fine; the run could not open it here"))
    if extant["extract_xlsx"]:
        for xl in inv.get("xlsx", []):
            out = extract / f"{_slug(xl)}_xlsx.json"
            xl_src = folder / xl
            # TRACKER MAPPING (LLM judges the column->field decision, the dictionary stays
            # the fallback/veto/cross-check): compute the structure hash, look for a cached
            # map at work/extract/<slug>_<hash8>_map.json. A present+matching map is fed via
            # --colmap; a *.SKIP sentinel (orchestrator's explicit 'use the dictionary')
            # lets the run PROCEED on the dictionary; otherwise the tracker is OFFERED to the
            # mapping sub-agent (manifest + exit 3) while the dictionary STILL extracts now,
            # so a no-LLM / offline full-spine run is never bricked.
            colmap_arg = None
            colmap_verify_arg = None  # the second, blind map (semantic verifier), diff-only
            try:
                structs = extant["extract_xlsx"].tracker_structure(xl_src)
            except Exception:
                structs = []
            if structs:
                import hashlib as _hl
                # a tracker carries no region/country from intake (it spans regions); the
                # STRUCTURE alone is a stable cache key, so region/country are empty here.
                slug = re.sub(r"[^A-Za-z0-9]+", "_", str(Path(xl).with_suffix("")))[:40].strip("_") or "file"
                fh = _hl.sha1(str(xl).encode("utf-8")).hexdigest()[:8]
                ihash = _tracker_struct_hash([{"region": "", "country": ""}, structs])
                map_f = extract / f"{slug}_{fh}_map.json"
                # BOTH .SKIP spellings count as a decline. The manifest instruction says "an
                # empty file at the output path with a .SKIP suffix", and the output path ends
                # in `_map.json` - so an orchestrator following the wording literally writes
                # `_map.json.SKIP`, while only `_map.SKIP` was ever read. The decline was then
                # invisible, the tracker job was re-emitted every round, and exit 3 never
                # converged (reproduced: 25 rounds, zero state change). Accept either.
                skip_f = extract / f"{slug}_{fh}_map.SKIP"
                skip_alt = extract / f"{slug}_{fh}_map.json.SKIP"
                # the SEMANTIC VERIFIER's second, blind map (reference/interpretation.md
                # "Verification pass"): a SEPARATE fresh agent re-derives the SAME map from
                # the SAME sheets and writes mapcheck_f. Keyed by the SAME input_hash as the
                # primary map, so it is resume-stable and asked once. It NEVER drives the
                # parse - run.py only diffs it against map_f (advisory). A `_mapcheck.SKIP`
                # sentinel declines the verify pass (an offline / no-LLM run, or a broker who
                # does not want the second pass) so it never forces a perpetual exit 3.
                mapcheck_f = extract / f"{slug}_{fh}_mapcheck.json"
                mapcheck_skip_f = extract / f"{slug}_{fh}_mapcheck.SKIP"
                mapcheck_skip_alt = extract / f"{slug}_{fh}_mapcheck.json.SKIP"

                def _hash_ok(f: Path) -> bool:
                    """A usable map: reject only a PRESENT-but-MISMATCHED input_hash.
                    Requiring the echo outright rejected a map the parser would happily use -
                    `extract_xlsx._load_colmap` documents that it accepts "the cache wrapper OR
                    a bare map" - so a sub-agent that omitted the 8-hex echo (or returned a
                    bare `{"columns": [...]}`) had its job re-emitted forever, with the only
                    escape being a hand-written .SKIP. The file is already invalidated BY PATH
                    (`<slug>_<filehash>_map.json`) and mtime-tracked, so a missing echo is a
                    formatting slip, not a staleness signal."""
                    try:
                        cached = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        return False       # malformed/half-written -> re-ask
                    if not isinstance(cached, dict):
                        return False
                    got = cached.get("input_hash")
                    if got is None:
                        return bool(cached.get("map") or cached.get("columns"))
                    return got == ihash
                map_ok = _hash_ok(map_f) if map_f.exists() else False
                mapcheck_ok = _hash_ok(mapcheck_f) if mapcheck_f.exists() else False
                declined = skip_f.exists() or skip_alt.exists()
                declined_v = mapcheck_skip_f.exists() or mapcheck_skip_alt.exists()
                if map_ok:
                    colmap_arg = map_f
                elif not declined:
                    interpret_trackers.append({
                        "kind": "tracker", "source_file": Path(xl).name,
                        "source_type": Path(xl).suffix.lstrip(".").lower() or "xlsx",
                        "region": "", "country": "",
                        "input_hash": ihash,
                        "output": f"work/extract/{slug}_{fh}_map.json",
                        "sheets": structs,
                    })
                # Emit the verify job CONCURRENTLY (same manifest, one exit-3 batch) so the
                # orchestrator dispatches author + verifier as two fresh, independent agents
                # in ONE round-trip - each gets ONLY the raw sheets, never the other's answer
                # (blind/independent). Gate it so it can NEVER loop: offer it only while the
                # PRIMARY map is in play (a present LLM map OR an author job being offered -
                # i.e. NOT .SKIP-declined to the dictionary), the mapcheck is not yet present/
                # valid, AND the verify pass is not itself .SKIP-declined. A dictionary-only
                # (.SKIP) tracker has no author LLM map to diff, so no verify is offered.
                primary_in_play = map_ok or not declined
                if (primary_in_play and not mapcheck_ok and not mapcheck_f.exists()
                        and not declined_v):
                    interpret_trackers.append({
                        "kind": "tracker_verify", "source_file": Path(xl).name,
                        "source_type": Path(xl).suffix.lstrip(".").lower() or "xlsx",
                        "region": "", "country": "",
                        "input_hash": ihash,
                        "output": f"work/extract/{slug}_{fh}_mapcheck.json",
                        "sheets": structs,
                    })
                if mapcheck_ok:
                    colmap_verify_arg = mapcheck_f
            # the cache map changes the parse, so a present map must invalidate a stale
            # dictionary-parsed output (resume keys on inputs; add the map as an input).
            # The verify map is ADVISORY (diff only) but a changed verify map can change a
            # semantic_disagreement yield line, so it is an input too (resume-stable).
            _xl_inputs = ([xl_src] + ([colmap_arg] if colmap_arg else [])
                          + ([colmap_verify_arg] if colmap_verify_arg else []))
            if _is_current(out, _xl_inputs):
                _resumed(f"{Path(xl).name} extract")
            else:
                _extra = []
                if colmap_arg:
                    _extra += ["--colmap", colmap_arg]
                if colmap_verify_arg:
                    _extra += ["--colmap-verify", colmap_verify_arg]
                call(extant["extract_xlsx"], xl_src, *_extra, "--out", out, check=False)
            try:
                payload = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                payload = None
            recs = payload.get("records") if isinstance(payload, dict) else None
            if recs:
                ra = extract / f"{_slug(xl)}_xlsx_records.json"
                _stamp_source_relpath(recs, xl)
                _write_if_changed(ra, json.dumps(recs, ensure_ascii=False))
                record_files.append(ra)
            reqs = payload.get("requirements") if isinstance(payload, dict) else None
            if reqs:
                requirements.update(reqs)
            # EXTRACTION-YIELD check: a field-rich sheet that yields a thin parse must
            # be LOUD (a real 75-column tracker once mapped ~7 columns and the whole run
            # degraded silently). A 'suspected_tracker' note means headers were not
            # recognised at all (e.g. a continental sheet) - surface it the same way.
            for hr in (payload.get("header_report") or []) if isinstance(payload, dict) else []:
                if hr.get("suspected_tracker") or hr.get("mapped_columns", 0) < hr.get("populated_columns", 0):
                    tag = " (headers not recognised - looks like a tracker)" if hr.get("suspected_tracker") else ""
                    # FLATTEN each header for the SAME reason as the semantic_disagreements
                    # note below: a spreadsheet header legitimately contains a newline
                    # ("Leaseable area\n(sq ft)" is real in this tracker), the note is emitted
                    # as ONE markdown list item, and the raw newline ended the bullet - so the
                    # broker read "unmapped: No., Postcode, Leaseable area" and the remaining
                    # NINE names were silently dropped. That also made the line contradict
                    # itself (it announced 11 unmapped, then named 3), which reads as a broken
                    # report rather than a truncated one. (QA round 2, adjudication 1f3f63dc97.)
                    _unmapped = [" ".join(str(h).split())
                                 for h in (hr.get("unmapped_headers") or [])]
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]{tag}: "
                        f"{hr.get('mapped_columns')}/{hr.get('populated_columns')} populated "
                        f"columns mapped; unmapped: {', '.join(_unmapped)}")
                # a rent column with NO currency/unit in the header or cells ships on the
                # house default (EUR/sq m/yr) - surface it so the broker confirms the real
                # convention (a bare UK GBP/sq ft figure must never pass as EUR/sq m silently)
                if hr.get("rent_unit_assumed"):
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]: rent column states no "
                        f"currency or unit - shipped on the EUR/sq m/yr default (ASSUMED); "
                        f"confirm the real convention with the landlord/agent before sending")
                # an area whose magnitude does not match its stated unit (a 'sq m' value in
                # the sq-ft range, or vice versa) - the value is KEPT, NOT auto-converted;
                # surface it so the broker confirms the real unit before sending
                if hr.get("area_unit_suspect"):
                    _bad = "; ".join(f"{(d.get('park') or '?')} = {d.get('value')} {d.get('unit')}"
                                     for d in hr.get("area_unit_suspect", []))
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]: area unit looks wrong (a value "
                        f"sits in the sq-ft range under a sq m header / vice versa) - flagged "
                        f"for review, NOT auto-converted; confirm the real unit before sending "
                        f"({_bad})")
                # an area outside its plausibility band (a likely parse-garble / 10x error) -
                # the value is KEPT (never dropped or coerced to tbd), surfaced for review
                if hr.get("area_out_of_band"):
                    _bad = "; ".join(f"{(d.get('park') or '?')} = {d.get('value')} {d.get('unit')}"
                                     for d in hr.get("area_out_of_band", []))
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]: area value outside the "
                        f"plausibility band - kept for broker review (likely a unit/parse "
                        f"error), confirm before sending ({_bad})")
                # SEMANTIC VERIFIER: two independent column-mapping passes DISAGREED on a
                # field/basis. ADVISORY - the dashboard used the FIRST (primary) map; surface
                # the disagreement so the broker confirms the correct basis/column with the
                # landlord/agent before sending. NEVER auto-rejects the primary map.
                if hr.get("semantic_disagreements"):
                    # FLATTEN every interpolated value. A spreadsheet header legitimately
                    # contains a newline ("Total Size\n(sq ft)" is normal in a tracker), and
                    # this note is emitted as ONE markdown list item: the raw newline ended
                    # the bullet mid-sentence, so the broker read "col 4 'Total Size " and
                    # nothing else - losing both what the two passes actually read AND every
                    # later disagreement in the same line (col 22 'Landlord' never reached
                    # them at all). Collapsing whitespace keeps the note on one line and is
                    # lossless for the reader. (QA round 1, G-honesty/G-trace blocking.)
                    def _flat(v):
                        return " ".join(str(v).split()) if v is not None else v

                    def _one(d):
                        col = (f"col {d.get('index')}"
                               + (f" '{_flat(d.get('header'))}'" if d.get("header") else ""))
                        return (f"{col} [{_flat(d.get('key'))}]: "
                                f"pass 1 read {_flat(d.get('pass1'))!r}, "
                                f"pass 2 read {_flat(d.get('pass2'))!r}")
                    _dis = "; ".join(_one(d) for d in hr.get("semantic_disagreements", []))
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]: two independent column-mapping "
                        f"passes DISAGREE - {_dis}; confirm the correct basis/column with the "
                        f"landlord/agent before sending (the dashboard used pass 1).")
            # P2-3: brochure URLs/hyperlinks in cells can't be fetched in-sandbox but
            # must be surfaced, not silently lost - list them for the orchestrator/broker
            for ls in (payload.get("linked_sources") or []) if isinstance(payload, dict) else []:
                link_note_ix.add(len(yield_notes))  # tagged so stdout can count them (B23)
                yield_notes.append(f"{Path(xl).name} linked source (not embedded; fetch "
                                   f"separately) at {ls.get('locator')}: {ls.get('target')}")
            # honesty: a spreadsheet that opened to NOTHING usable may be unreadable
            if not (isinstance(payload, dict) and (recs or reqs or payload.get("header_report") or payload.get("linked_sources"))):
                bad = _classify_unreadable(xl_src)
                if bad:
                    unreadable_inputs.append((Path(xl).name, bad))
                    if not QUIET:
                        print(f"  ({Path(xl).name}: {bad} - skipped; logged to the Gaps Report)")
    if yield_notes:
        yr = work / "yield_report.md"
        # _write_if_changed: a Gaps sidecar the Stage-7 deliver guard keys on - a byte-identical
        # rewrite must NOT bump its mtime (else deliver never resumes-skips), but a real change
        # DOES, so the Gaps Report re-delivers. (#25)
        _write_if_changed(yr, "# Extraction yield - unmapped tracker columns\n\n"
                          "Columns the spreadsheet extractor did not map (per sheet). If one of\n"
                          "these should feed the dashboard, extend extract_xlsx.COLUMN_MAP.\n\n"
                          + "\n".join(f"- {n}" for n in yield_notes) + "\n")
        if not QUIET:
            for _ln in _yield_stdout_lines(yield_notes, link_note_ix, yr):
                print(_ln)

    # UNREADABLE INPUTS (P1-1): write the typed list (always - empty clears a stale
    # marker) and ALWAYS surface a plain summary. Extraction precedes EVERY terminal
    # exit (0/3/8), so this guarantees a corrupt/encrypted/empty file is never a
    # silent drop; deliver.py also folds it into the Gaps Report.
    # First CAPTURE any prior prep-failure gaps before this always-write clobbers them:
    # on a mixed run the exit-0 re-run skips an un-preppable deck via the region-level
    # has_vision guard, so it is NOT re-derived this pass; the prep fold below carries it
    # forward so it never silently drops from the delivered Gaps Report.
    try:
        _prior_unreadable = json.loads((work / "unreadable.json").read_text(encoding="utf-8"))
        if not isinstance(_prior_unreadable, list):
            _prior_unreadable = []
    except Exception:
        _prior_unreadable = []
    # UNSUPPORTED-TYPE inputs join the unreadable set, so they reach unreadable.json, the Gaps
    # Report and the operator note by the SAME route as a corrupt file. They are a different
    # failure (the file is fine; the pipeline has no reader for it), so they carry their own
    # reason naming the supported types and the LLM route - a .txt/.json of property data is
    # best pasted into an email/tracker, which the interpretation path already reads.
    try:
        _unclassified = (json.loads((work / "inventory.json").read_text(encoding="utf-8"))
                         .get("unclassified") or [])
    except Exception:
        _unclassified = []
    for _u in _unclassified:
        _f = _u.get("file") if isinstance(_u, dict) else str(_u)
        _e = (_u.get("ext") if isinstance(_u, dict) else "") or "(no extension)"
        if _f and not any(_f == f for f, _ in unreadable_inputs):
            unreadable_inputs.append((_f, f"unsupported file type {_e} - not read. This pipeline "
                                          f"reads PDF/PPTX brochures, Excel/CSV trackers, "
                                          f".msg/.eml emails and images. If it holds property "
                                          f"data, paste it into an email or a tracker sheet and "
                                          f"re-run"))
    try:
        # _write_if_changed: an unchanged unreadable-set keeps its mtime so Stage-7 deliver can
        # resume-skip; a genuinely new/cleared unreadable input bumps it -> Gaps re-delivers. (#25)
        _write_if_changed(work / "unreadable.json",
            json.dumps([{"file": f, "reason": r} for f, r in unreadable_inputs],
                       ensure_ascii=False))
    except OSError:
        pass
    if unreadable_inputs:
        _summary = "; ".join(f"{f} ({r})" for f, r in unreadable_inputs)
        if QUIET:
            print(f"Note: I couldn't open {len(unreadable_inputs)} of your file(s) and skipped "
                  f"them - they're listed in the Gaps Report: {_summary}")
        else:
            print(f"NOTE: {len(unreadable_inputs)} input file(s) unreadable, skipped "
                  f"(in the Gaps Report): {_summary}")

    # fold in any vision-transcribed records from a prior pass (orchestrator output) -
    # but VALIDATE them first: for a scanned/designed deck, vision IS the entire
    # extraction, and its failure classes (page mis-binding, un-annualised monthly
    # rents, collapsed multi-property pages, invented coordinates) are caught
    # structurally here, not trusted to the model
    vision_files = sorted(extract.glob("*_vision.json"))
    if vision_files:
        import vision_validate
        v_errors, v_warnings = vision_validate.validate(work, source_dir=folder)
        if v_warnings:
            notes_file = work / "vision" / "validation_notes.md"
            notes_file.parent.mkdir(parents=True, exist_ok=True)
            notes_file.write_text("# Vision transcription warnings (for G-honesty/G-trace)\n\n"
                                  + "\n".join(f"- {w}" for w in v_warnings) + "\n",
                                  encoding="utf-8")
            if not QUIET:
                for w in v_warnings:
                    print(f"  [vision warn] {w}")
        if v_errors:
            print("Some transcribed pages need a correction before I can continue." if QUIET
                  else "\nVISION TRANSCRIPTION INVALID - fix these records and re-run "
                       "(same exit-3 contract as the manifest):")
            for e in v_errors:
                _say_orchestrator(f"  [FAIL] {e}" if not QUIET else f"  {e}")
            _exit_round_trip(work, 3, _attempts, "brochure/tracker interpretation")
    for vf in vision_files:
        if vf not in record_files:
            record_files.append(vf)
    n_records = sum(_count(f) for f in record_files)

    # INTERPRETATION PREP: decide each brochure deck's mode (text vs raster) up front
    # so the manifest carries the text payload for born-digital decks and the page
    # rasters only for the garbled/scanned ones. Splitting here keeps the photo-match
    # step's "no extractable text" semantics intact - only RASTER decks (textless) can
    # be photos of a known property; a text-rich deck is always interpreted from text.
    interpret_decks = []  # manifest entries already prepped (text decks + prepped rasters)
    failed_preps: list = []
    raster_targets = []   # (src, region, country) decks that need the raster path
    if extant.get("interpret_prep") and vision_targets:
        for s, region, country in vision_targets:
            if Path(s).name in force_raster:
                # the sub-agent found this text deck garbled -> force the raster path
                # (do NOT let interpret_prep route it back to text on its text layer)
                raster_targets.append((s, region, country))
                continue
            try:
                ent = extant["interpret_prep"].prepare(s, region, country, work / "vision",
                                                        force=True, resume=RESUME)
            except Exception as e:
                failed_preps.append(Path(s).name)
                if not QUIET:
                    print(f"(interpretation prep failed for {Path(s).name}: {e})")
                continue
            if ent.get("mode") == "text" and ent.get("pages"):
                interpret_decks.append(ent)
            else:
                # raster mode (or a text deck with no readable pages) -> the page-image
                # path; let photo-match consider it (it has no usable text)
                raster_targets.append((s, region, country))
    elif vision_targets:
        raster_targets = list(vision_targets)
    # downstream (photo-match + the raster prep loop) operate on the textless decks
    vision_targets = raster_targets

    # PHOTO MATCH (P0-1) - GENERIC, format/source agnostic. A 0-record brochure in a run
    # that ALSO has property records from ANOTHER source (a tracker, emails, other decks)
    # is usually the PHOTO for one of those properties, not a new property needing a full
    # vision transcription. The pairing is NOT guessed with rules (filenames are wild) -
    # an isolated sub-agent matches by MEANING. The spine only emits a manifest + exit 9
    # when a match is needed and none exists, then consumes the sub-agent's photo_map.json.
    # With NO other records (a pure brochure run) this whole step is skipped and the
    # normal vision path runs - so it never assumes a tracker is present.
    photo_overrides: dict = {}   # match_key -> brochure rel (confident: attach the deck hero)
    photo_doubts: list = []      # uncertain pairs -> surfaced as yes/no prompts at the end
    photo_map_f = work / "photo_map.json"
    known_recs = [r for f in record_files for r in _load_records(f)
                  if isinstance(r, dict) and not r.get("unreadable")
                  and (r.get("park") or r.get("warehouseArea") or r.get("lat") is not None)]
    if vision_targets and known_recs:
        import match as _m
        rel_of = {src: src.resolve().relative_to(folder.resolve()).as_posix()
                  if folder.resolve() in src.resolve().parents else src.name
                  for src, _r, _c in vision_targets}
        if not photo_map_f.exists():
            props, seen = [], set()
            for r in known_recs:
                k = _m.match_key(r)
                if k in seen:
                    continue
                seen.add(k)
                props.append({"key": k, "park": r.get("park"), "city": r.get("city"),
                              "developer": r.get("developer")})
            # DESCRIPTION HINT: most exit-9 decks are textless rasters (empty
            # text_blocks, no pick possible there - moot), but the minority that DO
            # carry a text layer get a real description pick. Hand the sub-agent each
            # brochure's font-size-grouped text (boilerplate NOT pre-filtered - the
            # LLM judges) + what the deterministic fallback would pick + a short text
            # hash (so merge can reject a stale pick after a deck edit). brochures /
            # properties stay byte-stable so the filename-matching contract is unchanged.
            import extract_pdf as _xp
            import hashlib as _hl
            brochure_text = []
            for _src, _rel in sorted(rel_of.items(), key=lambda kv: kv[1]):
                try:
                    _blocks = _xp.font_grouped_blocks(_src)
                except Exception:
                    _blocks = []
                try:
                    _hd, _hp = _xp.best_description_in_deck(_src)
                except Exception:
                    _hd, _hp = None, None
                _joined = "\n".join(b.get("text", "") for b in _blocks)
                brochure_text.append({
                    "brochure": _rel,
                    "text_blocks": _blocks,
                    "heuristic_description": _hd,
                    "text_hash": _hl.sha1(_joined.encode("utf-8")).hexdigest()[:16],
                })
            (work / "photo_match_manifest.json").write_text(json.dumps({
                "brochures": sorted(rel_of.values()),
                "properties": props,
                "brochure_text": brochure_text,
                "output": "work/photo_map.json",
                "instructions": (
                    "These brochures yielded no extractable text, but the run already holds the "
                    "property data from another source. Decide, for EACH brochure, which property "
                    "(if any) it depicts - by MEANING, like a human reading the filename against the "
                    "property names/addresses, NEVER by rigid rules. Write work/photo_map.json: "
                    "{\"confident\":[{\"brochure\":<name>,\"property_key\":<key>}], "
                    "\"uncertain\":[{\"brochure\":<name>,\"property_key\":<key>,\"note\":<why unsure>}], "
                    "\"unrelated\":[<name>,...]}. confident = sure (its photo is attached to that "
                    "property); uncertain = a plausible but unconfirmed pairing (placeholder + the "
                    "broker is asked to confirm); unrelated = a genuinely DIFFERENT property, or no "
                    "match (it goes to the vision transcription path - never lose a property). "
                    "property_key is the opaque 'key' from this manifest. "
                    "DESCRIPTION (optional, only for a confident/uncertain match whose `brochure_text` "
                    "entry has non-empty `text_blocks`): also return the property DESCRIPTION - copy the "
                    "actual descriptive prose VERBATIM from text_blocks into `description`, set "
                    "`description_page` to its 1-based page, and `description_source_quote` to the first "
                    "~80 characters copied EXACTLY (the verifier's needle). NEVER the legal/"
                    "misrepresentation footer, an ALL-CAPS callout, a drive-time/spec table or an icon "
                    "caption; if no usable description prose exists, set description to null - absent "
                    "stays absent, never synthesise (null falls back to the deterministic heuristic). "
                    "Then re-run the same command."),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            n_b, n_p = len(rel_of), len(props)
            if QUIET:
                print("Some brochures have no readable text but look like photos of properties "
                      "you already gave me. I need to match each one before I can carry on.")
                _say_orchestrator(
                    f"(orchestrator: dispatch the photo-match sub-agent per "
                    f"{work / 'photo_match_manifest.json'} -> work/photo_map.json, then re-run.)")
            else:
                print(f"\nPHOTO MATCH NEEDED: dispatch a sub-agent to match {n_b} brochure(s) to "
                      f"{n_p} known propert(y/ies) per {work / 'photo_match_manifest.json'} -> "
                      f"work/photo_map.json, then re-run.")
            _exit_round_trip(work, 9, _attempts, "matching brochure photos to properties")
        # consume the sub-agent's decisions
        try:
            pm = json.loads(photo_map_f.read_text(encoding="utf-8"))
        except Exception:
            pm = {}
        key_by_park = {_m.norm(r.get("park")): _m.match_key(r) for r in known_recs}

        def _resolve_key(k):
            k = k or ""
            return k if "|" in k else key_by_park.get(_m.norm(k), k)

        confident = {e.get("brochure"): _resolve_key(e.get("property_key")) for e in pm.get("confident", [])}
        uncertain = {e.get("brochure"): e for e in pm.get("uncertain", [])}
        # DESCRIPTION CACHE: collect the sub-agent's verbatim description picks (from
        # confident/uncertain entries that carry a non-null `description`) keyed by the
        # brochure BASENAME (the same key merge looks up via Path(brel).name) and stamp
        # each with the manifest's text_hash so a stale pick is rejected after a deck edit.
        # merge's deterministic quote-verify is the gate; this is just the cache.
        try:
            _pmm = json.loads((work / "photo_match_manifest.json").read_text(encoding="utf-8"))
        except Exception:
            _pmm = {}
        _hash_by_name = {Path(b.get("brochure", "")).name: b.get("text_hash")
                         for b in _pmm.get("brochure_text", []) if isinstance(b, dict)}
        brochure_descriptions: dict = {}
        for e in (pm.get("confident", []) + pm.get("uncertain", [])):
            if not isinstance(e, dict):
                continue
            d = e.get("description")
            if not d:
                continue
            nm = Path(e.get("brochure", "")).name
            if not nm:
                continue
            brochure_descriptions[nm] = {
                "description": d,
                "page": e.get("description_page"),
                "quote": e.get("description_source_quote"),
                "text_hash": _hash_by_name.get(nm),
            }
        new_targets = []
        for src, region, country in vision_targets:
            rel = rel_of[src]
            if confident.get(rel):
                photo_overrides[confident[rel]] = rel
            elif rel in uncertain:
                pk = _resolve_key(uncertain[rel].get("property_key"))
                park = next((r.get("park") for r in known_recs if _m.match_key(r) == pk), pk)
                photo_doubts.append({"park": park, "brochure": rel, "key": pk,
                                     "note": uncertain[rel].get("note", "")})
            else:
                new_targets.append((src, region, country))  # unrelated / unmatched -> vision
        vision_targets = new_targets
        if photo_overrides:
            (work / "photo_overrides.json").write_text(json.dumps(photo_overrides, ensure_ascii=False), encoding="utf-8")
        if brochure_descriptions:
            (work / "photo_descriptions.json").write_text(
                json.dumps(brochure_descriptions, ensure_ascii=False), encoding="utf-8")
        # _write_if_changed: a Gaps sidecar the Stage-7 deliver guard keys on (#25)
        _write_if_changed(work / "photo_doubts.json", json.dumps(photo_doubts, ensure_ascii=False))

    # INTERPRETATION MANIFEST (deterministic prep): the text decks are already prepped
    # (interpret_decks); rasterise the textless decks (vision_prep, reused unchanged)
    # and write ONE manifest carrying every deck's `mode` for the orchestrator's
    # interpretation sub-agent (reference/interpretation.md). Interpretation is the
    # agentic step, not done here - this only prepares text/rasters + the manifest.
    interpret_decks = list(interpret_decks)  # text decks prepped above; rasters appended below
    manifest = work / "vision" / "manifest.json"

    def _write_manifest(decks) -> None:
        (work / "vision").mkdir(parents=True, exist_ok=True)
        # B2: give every deck its OWN unique output path before the manifest is written, and assert
        # uniqueness. Two decks sharing a cluster label used to derive the same
        # `<label>_vision.json`, so four concurrent agents wrote one file and three decks were lost
        # silently. Fail loudly here rather than ever emit a colliding manifest.
        assign_deck_outputs(decks)
        _outs = [d.get("output") for d in decks]
        if len(set(_outs)) != len(_outs):
            raise SystemExit(f"internal error: deck output collision in the manifest: {_outs}")
        payload = {
            "decks": decks,
            "record_schema": "templates/record_schema.json",
            # B58 per-property completeness: the reader is HANDED the field registry.
            # Before this, the exit-3 handoff named no field set at all: the contract's list
            # ends in an ellipsis, record_schema.json names 17 of 53 with
            # additionalProperties:true, and "the same names the deterministic extractors
            # emit" does not cover sprinklers/permitting/divisibleFrom/rentFree/expansion*.
            # Three of three readers on one live run concluded "no canonical field exists"
            # and DROPPED rows printed on the page; merge then recorded each omission as a
            # positive "absent in all sources" ledger row, i.e. ~100 false claims telling the
            # broker to chase an agent for data already in the deck. Generated from _common
            # so it can never drift from the pipeline (evals/capture_contract_test.py).
            "fields": _reader_field_list(),
            "field_rules": _FIELD_RULES,
            # B22: the two contract files are READ, not inlined. Inlining them would be a
            # token wash - there is ONE manifest, not one per deck, so every sub-agent reads
            # the same bytes either way - and it would create a THIRD copy of a contract that
            # has already drifted. What was actually broken is that the pointer was a bare
            # relative path with undefined cardinality, so these give an absolute path and
            # state the count. `record_schema` above keeps its exact literal:
            # it is part of the manifest contract (reference/interpretation.md).
            "contract": str((HERE.parent / "reference" / "interpretation.md").resolve()),
            "record_schema_path": str((HERE.parent / "templates" / "record_schema.json").resolve()),
            "contract_reads": ("Read `contract` and `record_schema_path` ONCE for this whole "
                               "round, before dispatching - not once per deck. They are the "
                               "same bytes for every deck in this manifest."),
            "output_pattern": ("EACH DECK CARRIES ITS OWN `output` PATH - write that path VERBATIM "
                               "(a JSON array of records), exactly as the tracker `jobs` do. Do NOT "
                               "derive a filename from the cluster label: two decks can share a "
                               "label, and deriving the name made them overwrite each other. "
                               "`work/extract/<region>_vision.json` is the legacy shape only."),
            "instructions": ("Dispatch an isolated INTERPRETATION sub-agent (reference/interpretation.md). Each "
                             "deck carries a `mode`: for mode='text', read the page `text` and structure the "
                             "property into a record per the record schema; for mode='raster', read each page "
                             "image instead. For every record set __meta.source_type = the brochure type "
                             "(pdf/pptx), __meta.source_file = source_file, __meta.page_no = the page's `page_no` "
                             "value COPIED VERBATIM (it is 0-based; NEVER derive it from a PNG filename, whose _pN "
                             "suffix is 1-based - off-by-one binds the hero photo to the NEIGHBOURING property), and "
                             "__meta.prov[field] = '<locator> (text interpretation)' for text decks / "
                             "'<locator> (vision transcription)' for raster decks. Each text page also lists "
                             "`candidates`: its embedded images, each with an `index` and a thumbnail `image` path, "
                             "AND `candidates_sheet`: the SAME candidates tiled into one image, each captioned with "
                             "its `index`. **Read `candidates_sheet` ONCE per page instead of opening each "
                             "`candidates[].image`** - the tiles are the identical thumbnails at their native size, "
                             "so nothing is lost, and it is one tool call instead of N. Open an individual "
                             "`candidates[].image` only when a tile is genuinely ambiguous. When a page has no sheet "
                             "(one candidate, or none), use `candidates[].image`. If you do need several images on "
                             "one page, request them in a SINGLE message. "
                             "LOOK at them. For each property record set __meta.heroRef = the `index` of the genuine "
                             "marketing HERO (a real photo, aerial or render), or null if NONE of the candidates is a "
                             "real photo - a road MAP, a location screenshot, a floor/site PLAN, an icon or a logo is "
                             "NEVER the hero. Set __meta.planRef = the `index` of the SITE PLAN if present, else null. "
                             "When unsure, prefer a photo/aerial/render as the hero and leave a map/plan as planRef. "
                             "Rents are ANNUAL (x12 a monthly "
                             "quote). **WHENEVER YOU RETURN A NUMERIC AREA, ALSO RETURN `areaUnit` "
                             "('sq m' or 'sq ft') AS THE SOURCE STATES IT** - read it off the deck (the column "
                             "header, the figure's own suffix, the spec table's unit row); do NOT infer it from the "
                             "country and do NOT convert the number. Nothing downstream can recover a missing unit: "
                             "an unlabelled metric area silently inherits the dataset's dominant unit, which is a "
                             "10.76x error on the client's card. If the deck genuinely never states a unit, return "
                             "the area and OMIT areaUnit - it is then recorded as an assumption in the Gaps Report "
                             "rather than passed off as known. Same rule for `rentUnit` (e.g. 'GBP/sq ft/yr') "
                             "whenever you return a rent. "
                             "Unreadable/absent field -> 'tbd'/null, never invented; if a text deck is "
                             "garbled/unusable, set \"needs_raster\": true on it so it escalates to raster on re-run. "
                             "Save per region (region EXACTLY as in this manifest), then re-run run.py with the "
                             "same arguments - it resumes and folds them in."),
        }
        # TRACKER jobs ride the SAME manifest + exit 3 (no new exit code). A `jobs`
        # entry is a tracker the mapping sub-agent should MAP - it returns a column->field
        # MAP (never records, never a cell value); Python parses the numbers. The brochure
        # `decks` array is UNCHANGED so the interpretation contract is byte-stable.
        if interpret_trackers:
            payload["jobs"] = interpret_trackers
            payload["tracker_instructions"] = (
                "Each `jobs` entry is a property TRACKER (xlsx/csv) whose column->field "
                "mapping the dictionary could not fully resolve. Dispatch an isolated "
                "tracker-interpretation sub-agent (reference/interpretation.md 'Tracker mode'). "
                "Given ONLY the job's `sheets` (raw `headers` in column order + `sample_rows`), "
                "return a MAP - NEVER records, NEVER a transcribed cell value. "
                "`sample_rows` are CHOSEN, not the first N: they are selected so that every "
                "populated column shows at least one real value (`sample_row_numbers` gives "
                "their 1-based sheet rows). So a blank cell in the sample means that column is "
                "blank in the chosen rows, NOT that the column is empty - and if a sheet lists "
                "`unsampled_columns`, those are populated columns no sampled row could cover: "
                "map them from the header alone or return null, but do not read their blankness "
                "as evidence. "
                "Write the job's `output` file: {\"input_hash\": <copied verbatim from the job>, "
                "\"schema_version\": 1, \"map\": {\"columns\": [{\"index\": N, \"field\": "
                "\"warehouseArea\"|...|null, \"basis\"?: GIA|GEA|GLA|warehouse, \"areaUnit\"?: "
                "\"sq ft\"|\"sq m\"|acres|ha, \"currency\"?: GBP|EUR, \"perArea\"?: \"sq ft\"|"
                "\"sq m\", \"period\"?: annual|monthly, \"role\"?: \"size_basis\"}], \"notes\": "
                "\"...\"}}. Map each column to AT MOST one canonical field (the names "
                "extract_xlsx emits: park/developer/city/country/region/warehouseArea/plotArea/"
                "officeArea/warehouseRentVal/serviceCharge/landPrice/leaseTerm/incentives/status/"
                "earlyAccess/clearHeight/floorLoad/loadingDocks/overheadDoors/electricity/"
                "truckParking/carParking/breeam/motorway/lat/lng/latlng); set field:null for "
                "non-property columns or any column you are unsure of (Python falls back to the "
                "dictionary for it). KEEP the source's own units - only NAME currency/perArea/"
                "period so Python applies x12 / GIA-office faithfully; never convert. A column "
                "whose header is a derived/penalty figure ('Rent free (months)', 'Size Unit') "
                "is vetoed automatically. Then re-run run.py - it resumes and parses the "
                "tracker through your map. `input_hash` is preferred but OPTIONAL: a map "
                "without it is still accepted (the file is keyed by path), so a missing echo "
                "never re-asks. To DECLINE the LLM map and keep the dictionary, create an "
                "empty file at the job's `output` path with `.json` REPLACED by `.SKIP` "
                "(e.g. `..._map.SKIP`); appending `.SKIP` to the full filename "
                "(`..._map.json.SKIP`) is accepted too.")
            # SEMANTIC VERIFIER: a `kind:"tracker_verify"` job is an INDEPENDENT, BLIND
            # re-derivation of the SAME map - dispatch a SEPARATE fresh agent (NOT the one
            # that did the matching `kind:"tracker"` job), give it ONLY this job's `sheets`,
            # and NEVER show it the first map. Both jobs ride this ONE manifest so the
            # orchestrator dispatches them CONCURRENTLY (one exit-3 batch) per gates.md
            # parallel dispatch. run.py diffs the two maps in pure Python; any field/basis
            # disagreement is ADVISORY (surfaced in the Gaps Report, the primary map still
            # drives the parse - it is never rejected).
            if any(j.get("kind") == "tracker_verify" for j in interpret_trackers):
                payload["tracker_verify_instructions"] = (
                    "Each `jobs` entry with kind:'tracker_verify' is an INDEPENDENT SECOND PASS "
                    "over the SAME tracker as the matching kind:'tracker' job (same source_file + "
                    "input_hash). Dispatch a SEPARATE, fresh isolated sub-agent - it must NOT be "
                    "the agent that produced the first map and must NEVER be shown that map. Give "
                    "it ONLY this job's `sheets` (raw `headers` + `sample_rows`) and the SAME "
                    "'Tracker mode' contract, and have it re-derive the column->field MAP from the "
                    "headers AND the sample VALUES independently (cross-check each unit against the "
                    "value magnitude - e.g. a 172,867 value under a 'sq m' header is almost "
                    "certainly sq ft). Write the job's `output` (the *_mapcheck.json path) in the "
                    "SAME map schema as the first pass. run.py compares the two maps and surfaces "
                    "any disagreement to the broker (advisory); the first map still drives the "
                    "parse. Then re-run run.py - it resumes and folds the diff in.")
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if interpret_decks:
        _write_manifest(interpret_decks)  # text decks present even before raster prep
    if extant.get("vision_prep"):
        for s, region, country in vision_targets:
            try:
                ent = extant["vision_prep"].prepare(s, region, country, work / "vision", force=True)
                if ent.get("pages"):
                    ent["mode"] = "raster"
                    interpret_decks.append(ent)
                    _write_manifest(interpret_decks)  # incremental: a shell-cap kill keeps progress
                else:
                    failed_preps.append(Path(s).name)
            except Exception as e:
                failed_preps.append(Path(s).name)
                if not QUIET:
                    print(f"(raster prep failed for {Path(s).name}: {e})")
    elif vision_targets:
        failed_preps += [Path(s).name for s, _r, _c in vision_targets]
    # A deck that opened but could be neither text-interpreted NOR rasterised (e.g. a
    # vector/textless PPTX with no python-pptx AND no LibreOffice) is a GENUINE gap, not a
    # silent drop (P1-1): fold it into the unreadable list with a typed reason. ALSO carry
    # forward a prep-failure gap a PRIOR pass recorded - on a mixed run the exit-0 re-run
    # skips an un-preppable deck via the region-level has_vision guard, so it is NOT
    # re-derived here and would otherwise vanish from the delivered Gaps Report. Carry
    # forward ONLY prep-failure reasons (brochure-loop failures re-derive every pass) and
    # ONLY for files STILL in the inventory; then re-persist unreadable.json.
    _prep_reason = ("opened but could not be read as text or rasterised "
                    "(needs LibreOffice / python-pptx, or the deck is damaged)")
    _brochure_names = {Path(p).name for cl in inv["clusters"].values()
                       for p in ((cl.get("pdfs") or []) + (cl.get("pptxs") or [])
                                 + ([cl["pdf"]] if cl.get("pdf") else [])
                                 + ([cl["pptx"]] if cl.get("pptx") else []))}
    _seen_un = {f for f, _r in unreadable_inputs}
    _added = False
    for nm in failed_preps:
        if nm not in _seen_un:
            unreadable_inputs.append((nm, _prep_reason)); _seen_un.add(nm); _added = True
    for e in _prior_unreadable:  # carry forward prior PREP-failure gaps for current inputs
        f, r = (e.get("file"), e.get("reason")) if isinstance(e, dict) else (None, None)
        if f and f not in _seen_un and f in _brochure_names and "rasteris" in str(r):
            unreadable_inputs.append((f, r)); _seen_un.add(f); _added = True
    if _added:
        try:
            _write_if_changed(work / "unreadable.json",
                json.dumps([{"file": f, "reason": r} for f, r in unreadable_inputs],
                           ensure_ascii=False))
        except OSError:
            pass
    # The SEMANTIC VERIFIER's kind:"tracker_verify" jobs are ADVISORY and must NEVER be on
    # the critical path - a pending verify job (with the author map already resolved) must
    # NOT block the build. So the exit-3 GATE fires only on BLOCKING author work (brochure
    # decks + author kind:"tracker" jobs); the verify jobs still ride the SAME manifest (for
    # concurrent dispatch when author work is also pending), but if ONLY verify jobs remain
    # the spine PROCEEDS and the diff is simply absent (degraded-advisory, never a block).
    _author_trackers = [j for j in interpret_trackers if j.get("kind") != "tracker_verify"]
    if interpret_decks or interpret_trackers:
        _write_manifest(interpret_decks)  # always (re)write so the verify jobs are offered
    if interpret_decks or _author_trackers:
        n_pages = sum(len(d["pages"]) for d in interpret_decks)
        n_text = sum(1 for d in interpret_decks if d.get("mode") == "text")
        n_rast = len(interpret_decks) - n_text
        # ONE-PASS DISCIPLINE: stop BEFORE merge/gates/build even on a mixed run.
        # Building now would produce a dashboard that is guaranteed stale the moment
        # the interpreted records land - the old NOTE-and-continue path wasted a full
        # build + post-build gates + any dispatched reviews. Good files' records are
        # cached, so the re-run (resume is the default) starts at merge. Trackers are
        # OFFERED a richer LLM mapping the same way; the dictionary already extracted
        # them, so a .SKIP sentinel (or an LLM map) lets the re-run proceed.
        kinds = []
        if n_text:
            kinds.append(f"{n_text} from text")
        if n_rast:
            kinds.append(f"{n_rast} from page images")
        parts = []
        if interpret_decks:
            parts.append(f"{len(interpret_decks)} brochure deck(s) ({', '.join(kinds)}; "
                         f"{n_pages} page(s))")
        if _author_trackers:
            parts.append(f"{len(_author_trackers)} tracker(s) to map")
        msg = (f"{' and '.join(parts)} need INTERPRETATION. Manifest: {manifest}. Dispatch the "
               f"interpretation sub-agent (reference/interpretation.md) - structure brochure "
               f"decks into EACH DECK'S OWN `output` path (copy it verbatim from the deck entry - "
               f"never derive a filename from the cluster label, which two decks can share) and "
               f"write each tracker job's "
               f"column->field MAP to its `output` (or a .SKIP sentinel to keep the dictionary), "
               f"then re-run the same command - extracted regions + cached maps are reused, "
               f"nothing is redone. The manifest's `cluster_label` is a FILENAME-derived routing "
               f"name, NEVER evidence - do not copy it into `region` or any other field, and set "
               f"`region` only from text you can point at on a page. A value read from an IMAGE "
               f"rather than the text layer must carry `not in text layer` in its prov (the "
               f"prov-containment gate checks page-cited values). Set `__meta.source_lang` to the "
               f"ISO-639-1 code of the language each deck is written in. FIRST PASS? Present the "
               f"Stage-0 setup form in the SAME message as this dispatch - no form answer feeds "
               f"this round.")
        if QUIET:
            print("Some of your files still need reading into the dashboard - I'll structure "
                  "them before I build.")
            _say_orchestrator(msg)
        else:
            print("\n" + msg)
        _exit_round_trip(work, 3, _attempts, "brochure/tracker interpretation")

    if n_records == 0:
        if failed_preps:
            print(("Some files could not be read at all - they may be corrupt or password-protected: "
                   if QUIET else "\nUnreadable (and not rasterisable) input file(s): ")
                  + ", ".join(failed_preps[:8]))
        else:
            print("No usable inputs found to read - add PDF/PPTX brochures, Excel/CSV trackers, "
                  "emails (.msg/.eml) or images, then run again." if QUIET
                  else "\nNo property sources extracted. Stopping (Stage 0 gap).")
        # NAME the files we could not use. Exiting with "no readable property sources" while the
        # broker's actual data file sits unmentioned in the folder is the worst version of this
        # failure: it reads as "your files were considered and were empty" when they were never
        # opened. This is the live break a .json + photos handover hit.
        if _unclassified:
            _names = ", ".join(str(u.get("file", u)) for u in _unclassified[:8])
            print(f"I could not read {len(_unclassified)} file(s) because this pipeline has no "
                  f"reader for that type: {_names}. It reads PDF/PPTX brochures, Excel/CSV "
                  f"trackers, .msg/.eml emails and images. If one of those holds the property "
                  f"data, paste it into an email or a tracker sheet and run again.")
        sys.exit(2)

    # CROSS-SOURCE MATCH ADJUDICATION (exit 10) - mirrors photo-match (exit 9). The
    # deterministic matcher (match.py) auto-merges the confident pairs and HARD-BLOCKS
    # the impossible ones (developer disagreement / >15% size conflict). What is left -
    # a GREY ZONE of cross-source pairs that are plausibly the same property (same city /
    # within ~2 km / a shared distinctive park token / a borderline fuzzy key) - is the
    # genuinely ambiguous middle an isolated sub-agent resolves by MEANING. This runs
    # AFTER every record source is final (vision folded, trackers mapped) and BEFORE
    # merge, so the merge consumes a settled decision. The grey set is computed in pure
    # Python (no LLM); the SUB-AGENT only reads work/match_candidates.json and writes
    # work/match_decisions.json. The verdict is CACHED there, keyed by an order-
    # independent pair_id, so a re-run resumes byte-deterministically. With no grey pairs
    # (the common case - a pure-brochure or single-source run) this never fires; offline
    # (no decisions file) merge falls back to the deterministic token-set matcher.
    # ------------------------------------------------------------------ CLARIFY (exit 13)
    # AMBIGUITY IS A QUESTION, ASKED NOW - not a caveat in a Gaps Report nobody reads. This
    # runs BEFORE matching and merging, because that is the last moment an answer can still
    # change the deliverable: a unit answer changes the size comparison, which changes
    # clustering, which changes what ships.
    #
    # ASK ONCE, THEN SHIP HONESTLY. clarify.pending() excludes anything already ASKED (marked
    # at emit time, not on reply), so a broker who answers nothing is never asked twice and
    # the run always finishes. That bound is the entire reason this channel is safe to add to
    # a skill whose dominant failure mode has been the unbounded ask loop. (B38)
    import clarify as _clarify
    _answers = _clarify.ingest_answers(work)
    _recs_for_q = [r for f in record_files for r in _load_records(f) if isinstance(r, dict)]
    _by_src: dict = {}
    for _r in _recs_for_q:
        _by_src.setdefault(str((_r.get("__meta") or {}).get("source_file") or ""), []).append(_r)
    _deck_pages = {}
    try:
        for _d in json.loads((manifest).read_text(encoding="utf-8")).get("decks", []):
            _deck_pages[str(_d.get("source_file") or "")] = len(_d.get("pages") or [])
    except Exception:
        _deck_pages = {}
    # record_count_questions is deliberately NOT wired: page count is the wrong signal (a
    # 6-page brochure for ONE property is normal), so it fired on most decks - and a question
    # channel that cries wolf costs a round-trip each time and trains the orchestrator to skim
    # the ones that are precise. See clarify.record_count_questions / B46.
    #
    # source_authority_questions is NOT asked here either, and that is deliberate (B47). It
    # used to fire at this point on RAW RECORD COUNTS ("the brochures describe 13, the tracker
    # lists 12"), which is a pre-clustering number: a brochure record that merges into a
    # tracker row is not an extra at all. So the broker was asked to arbitrate a discrepancy
    # that the very next stage often dissolves. It now fires AFTER clustering has settled,
    # below, where an "extra" is well defined and the question can NAME the options at stake.
    _questions = _clarify.unit_questions(_recs_for_q)
    def _ask_and_exit(questions, quiet_intro, reason, extra=""):
        """The ONE emit site - questions are BATCHED here, never dripped.

        Two phases can reach it (unit ambiguities before matching; source authority once
        clustering has settled, which is the earliest moment an 'extra' is even definable),
        but every question still leaves through this single door: one emit, one questions.json,
        one exit 13. Keeping it to one call site is what the batching invariant actually
        protects, and evals/clarify_test.py asserts the count."""
        qf = _clarify.emit(work, questions)
        n_br = sum(1 for q in questions if q.get("asked_of") == "broker")
        if QUIET:
            print(quiet_intro)
            _say_orchestrator(
                f"(orchestrator: {len(questions)} clarification(s) needed ({n_br} for the "
                f"user, {len(questions) - n_br} for an isolated sub-agent) per {qf} -> "
                f"{extra}write work/answers.json as {{id: answer}} and re-run. Each question "
                f"is asked ONCE: anything unanswered ships as the honest gap named in its "
                f"`if_unanswered`, so answer only what you know and never invent one.)")
        else:
            print(f"\nCLARIFICATION NEEDED ({len(questions)}): see {qf}. Answer what you can "
                  f"into work/answers.json ({{id: answer}}) and re-run. Asked once only - "
                  f"anything unanswered ships as a disclosed gap.")
        _exit_round_trip(work, 13, _attempts, reason)

    _ask = _clarify.pending(work, _questions)
    if _ask:
        _ask_and_exit(_ask,
                      "A few things in your files are ambiguous - I need to confirm them "
                      "before I build, so nothing is guessed.",
                      "clarifying ambiguous source data")

    match_decisions_f = work / "match_decisions.json"
    field_decisions_f = work / "field_decisions.json"
    if len(record_files) > 1:  # cross-source pairs need >= 2 record files
        import match as _mm
        import merge as _merge
        _all_recs = [r for f in record_files for r in _load_records(f) if isinstance(r, dict)]
        # APPLY THE MANUAL CORRECTIONS FIRST (B48). merge.main applies work/overrides.json
        # BEFORE its own match.dedupe (merge.py ~1607, "before compute_file_quality /
        # dominant_units / match.dedupe - because all three consume it"). This enumeration path
        # is a SECOND clustering call, and it used to read the raw extract records, so the two
        # calls saw DIFFERENT data whenever an override touched a field the matcher keys on
        # (city, park, developer, an area). The consequence was silent and severe: the override
        # changed the merged output but NOT which pairs were asked about, so a correction whose
        # whole purpose was to make two records cluster left them split, the same building
        # shipped twice under two names, and the run exited 0 with every gate green. Observed
        # live: 9 grey pairs with the correction applied vs the 8 this path emitted without it.
        # The comment below about the two clustering calls agreeing is only TRUE with this.
        try:
            _ovs_e, _ = _merge.load_overrides(
                work / "overrides.json",
                extra_fields={k for r in _all_recs if isinstance(r, dict)
                              for k in r if k != "__meta"})
            if _ovs_e:
                _merge.apply_overrides(_all_recs, _ovs_e)
        except Exception as _e:      # best-effort, exactly like merge's own override load
            print(f"  (overrides not applied to the pair enumeration: {_e})", file=sys.stderr)
        # Quarantine off-spec STRUCTURES pre-enumeration, exactly as merge.main does at load
        # (~line 1041): without this, a stray non-canonical object (a leaked provenance/meta map)
        # would surface as a spurious 'field conflict' to the field-decision sub-agent, and a
        # locator-shaped scalar could skew a grey pair. No-op for canonical records / ledger / Gaps.
        for _r in _all_recs:
            _merge._normalise_offspec(_r)
        grey = _mm.grey_pairs(_all_recs)
        # the settled match decisions (best-effort): clustering for the value-conflict
        # enumeration uses the SAME match.dedupe(_all_recs, md or None) merge uses, so the
        # two clustering calls AGREE and conflict_ids never drift (the key #4 risk).
        # Merged over work/match_settled.json, so a round-2 agent that empties
        # match_decisions.json cannot destroy a settled verdict and force a third round (B20).
        md = _load_match_decisions(work)
        # GREY-PAIR coverage: the decisions file must COVER every current grey pair with a
        # recognised verdict; an uncovered pair (inputs changed) or a bad shape re-emits +
        # exits 10 - never a silent guess.
        # ONE predicate, shared with _settled_clusters - if the two ever disagreed, a pair
        # could be "answered" for the conflict pull-forward and "uncovered" for the exit.
        grey_uncovered = bool(grey) and not all(_pair_answered(md, g) for g in grey)
        # CROSS-SOURCE VALUE CONFLICTS (#4): build clusters with the settled match
        # decisions (the SAME call merge makes) and enumerate every genuine field conflict
        # (pure Python). Each carries an order-independent conflict_id; the field-decisions
        # file must cover every current id with a recognised pick. Uncovered -> re-emit +
        # exit 10 (same resume-safety as the grey path). The fixed precedence is the
        # DEFAULT, so this never fires for a single-source / pure-brochure run, nor when no
        # field genuinely disagrees.
        # mirror merge.main ordering (compute_file_quality BEFORE dedupe/conflict enumeration):
        # the file-quality demotion decides the conflict candidate labels + precedence default,
        # so omitting it made the a/b/c labels map to different values than merge applies (S2-1).
        _merge.compute_file_quality(_all_recs)
        clusters = _mm.dedupe(_all_recs, md or None)
        # ONLY enumerate value conflicts once CLUSTERING IS SETTLED. Each conflict_id is derived
        # from its `cluster_key`, so a grey pair resolved later changes the key and ORPHANS every
        # answer given against the old one - the adjudication is silently discarded and re-asked.
        # A live 12-property run saw the set grow 44 -> 78 across two exit-10 rounds for exactly
        # this reason: the first 44 were adjudicated against clustering that had not finished
        # deciding which records were one property. That is wasted sub-agent time (and wasted
        # broker minutes) by construction, not bad luck. With pairs outstanding we ask for the
        # PAIRS ONLY; the conflict set is then enumerated once, against final clusters.
        # ...but a cluster no OUTSTANDING pair can touch is already final, so its conflicts
        # carry the ids the settled clustering will produce and can be adjudicated NOW. With
        # every pair answered this is simply every cluster; in the common case where the open
        # pairs touch only a corner of the dataset it collapses the run to ONE exit 10. (B20)
        # SOURCE AUTHORITY (B47) - asked HERE, not before matching, because only now is an
        # "extra" well defined: a cluster evidenced by exactly ONE source family after
        # clustering has settled. Gated on `not grey_uncovered` so it is never asked while a
        # pair is still outstanding - resolving that pair may dissolve the discrepancy
        # entirely, and a question the next stage makes moot costs a round-trip and trains the
        # broker to skim the ones that matter. Asked ONCE (clarify.pending), and unanswered
        # still ships the union, so this can never wedge a run.
        if not grey_uncovered:
            _extras = _merge.authority_extras(clusters)
            _auth_q = _clarify.pending(work, _clarify.source_authority_questions(_extras)) \
                if _extras else []
            if _auth_q:
                _ask_and_exit(_auth_q,
                              "Your sources disagree about which options belong on this "
                              "longlist - I need you to pick before I build.",
                              "confirming which source governs the longlist",
                              extra="put it to the broker in plain language, NAMING the "
                                    "options listed in `only_in_brochures` / "
                                    "`only_in_tracker`, then ")
            # Apply the settled answer to THIS path's clusters too, so the conflict ids
            # enumerated here match the ones merge.main will produce from its own filtered
            # clusters. Unanswered / 'union' is a no-op, so nothing changes for a run that
            # never answered.
            clusters, _ = _merge.apply_source_authority(
                clusters, _clarify.settled_authority(_answers))
        conflicts = _merge.conflict_candidates(
            _settled_clusters(clusters, grey, md, _all_recs) if grey_uncovered else clusters)
        fd = None
        if field_decisions_f.exists():
            try:
                parsed_f = json.loads(field_decisions_f.read_text(encoding="utf-8"))
                fd = _index_decisions(parsed_f, ("conflict_id", "field", "property_id"))
            except Exception:
                fd = None  # malformed/half-written -> treat as absent (re-emit + exit 10)

        def _pick_ok(v):
            if isinstance(v, str):
                return True  # a bare label string is accepted
            if isinstance(v, dict):
                return isinstance(v.get("pick"), str)
            return False
        field_uncovered = bool(conflicts) and not (fd is not None and all(
            _pick_ok(fd.get(c["conflict_id"])) for c in conflicts))
        if grey_uncovered or field_uncovered:
            _cand = {
                "pairs": [{"pair_id": g["pair_id"], "a": g["a"], "b": g["b"]} for g in grey],
                "output": "work/match_decisions.json",
                # SEMANTIC VERIFIER: a SECOND, blind re-judgement of the SAME grey pairs. The
                # verify agent gets the SAME two records (NEVER the author's verdict) and writes
                # work/match_verify.json in the SAME schema as match_decisions.json. run.py diffs
                # the two verdicts in pure Python; a disagreement is ADVISORY (-> meta.conflicts
                # -> the Gaps 'Source conflicts' section). The author verdict STILL drives
                # clustering - the verifier never flips it.
                "verify_pairs": [{"pair_id": g["pair_id"], "a": g["a"], "b": g["b"]} for g in grey],
                "verify_output": "work/match_verify.json",
                "field_conflicts": conflicts,
                "field_output": "work/field_decisions.json",
                "verify_instructions": (
                    "`verify_pairs` is an INDEPENDENT SECOND PASS over the SAME grey `pairs`. "
                    "Dispatch a SEPARATE fresh isolated sub-agent (NOT the one resolving `pairs`, "
                    "and NEVER shown its verdicts). Give it ONLY the two full records of each "
                    "verify pair and the SAME 'How to judge' contract (reference/matching.md): "
                    "decide for EACH pair, by MEANING, whether `a` and `b` are the SAME physical "
                    "property, defaulting to 'different' when unsure. Write work/match_verify.json "
                    "in the SAME schema as match_decisions.json: {\"<pair_id>\": {\"verdict\": "
                    "\"same\"|\"different\", \"reason\": \"...\"}, ...} covering EVERY verify pair_id. "
                    "run.py compares the two passes; a disagreement is surfaced to the broker "
                    "(advisory) - the first pass's verdict still drives the merge. Dispatch this "
                    "CONCURRENTLY with the `pairs`/`field_conflicts` agents (one round-trip)."),
                "instructions": (
                    "Two kinds of cross-source ambiguity ride this ONE candidates file (resolve "
                    "BOTH in one round-trip). (1) `pairs` - AMBIGUOUS RECORD MATCHES: the "
                    "deterministic matcher has already auto-merged the confident pairs and "
                    "hard-BLOCKED the impossible ones (developer disagreement, >15% size conflict), "
                    "so each pair here genuinely could be one property described twice (e.g. 'Raven "
                    "Park, Corby' vs 'Unit 1, Raven Park, Earlstrees Industrial Estate, Corby NN17 "
                    "4XD' = same) or two distinct ones ('Alpha Park' vs 'Beta Park', same developer "
                    "and city = different). Decide, for EACH pair, by MEANING whether `a` and `b` "
                    "describe the SAME physical property. Write work/match_decisions.json: {\"<pair_id>"
                    "\": {\"verdict\": \"same\"|\"different\", \"reason\": \"...\"}, ...} covering EVERY "
                    "pair_id; default \"different\" when unsure. (2) `field_conflicts` - GENUINE "
                    "VALUE DISAGREEMENTS within a merged property: a field where two+ sources state "
                    "DIFFERENT values. The fixed source precedence already chose a `default`; KEEP "
                    "the default unless a candidate is clearly right and the default clearly wrong (a "
                    "typo in a newer email, a mislabelled tracker column, an ask-price vs a "
                    "negotiated rate). NEVER invent a value - pick only among the given candidate "
                    "labels; when unsure, pick the default. Write work/field_decisions.json: "
                    "{\"<conflict_id>\": {\"pick\": \"<label>\", \"reason\": \"...\"}, ...} covering "
                    "EVERY conflict_id. Python re-verifies each pick against the field's plausibility "
                    "gate and falls back to precedence if it fails. See reference/matching.md. Then "
                    "re-run the same command - it resumes and merges."),
            }
            if not grey_uncovered:
                # ROUND 2, pairs already settled. Do NOT re-list them: re-emitting costs two
                # sub-agent dispatches for nothing, and a re-dispatched author returning one
                # different verdict would re-key the very conflicts being adjudicated in this
                # same round. Omit the keys entirely rather than send `pairs: []`, which reads
                # to a literal-minded agent as "write an empty decisions file". (B20)
                for _k in ("pairs", "verify_pairs", "output", "verify_output",
                           "verify_instructions"):
                    _cand.pop(_k, None)
                _cand["settled_pairs"] = len(grey)
                _cand["instructions"] = (
                    "`field_conflicts` ONLY this round. The ambiguous record matches were "
                    "resolved in an earlier round and are deliberately NOT re-listed. **Do "
                    "NOT create, empty, rewrite or delete work/match_decisions.json or "
                    "work/match_verify.json** - the settled verdicts live there, and "
                    "re-writing them re-opens the matching round. Dispatch ONE sub-agent for "
                    "the value conflicts below. A `field_conflict` is a GENUINE VALUE "
                    "DISAGREEMENT within a merged property: a field where two+ sources state "
                    "DIFFERENT values. The fixed source precedence already chose a `default`; "
                    "KEEP the default unless a candidate is clearly right and the default "
                    "clearly wrong (a typo in a newer email, a mislabelled tracker column, an "
                    "ask-price vs a negotiated rate). NEVER invent a value - pick only among "
                    "the given candidate labels; when unsure, pick the default. Write "
                    "work/field_decisions.json: {\"<conflict_id>\": {\"pick\": \"<label>\", "
                    "\"reason\": \"...\"}, ...} covering EVERY conflict_id. Python re-verifies "
                    "each pick against the field's plausibility gate and falls back to "
                    "precedence if it fails. See reference/matching.md. Then re-run the same "
                    "command - it resumes and merges.")
            (work / "match_candidates.json").write_text(
                json.dumps(_cand, ensure_ascii=False, indent=2), encoding="utf-8")
            n_g = len(grey) if grey_uncovered else 0
            n_c = len(conflicts) if field_uncovered else 0
            if QUIET:
                print("Some options look like they might be the same property from different "
                      "sources, or sources disagree on a value; I need to confirm a few before "
                      "continuing.")
                _say_orchestrator(
                    f"(orchestrator: dispatch the match sub-agent for {n_g} pair(s) + {n_c} value "
                    f"conflict(s) per {work / 'match_candidates.json'} -> work/match_decisions.json "
                    f"+ work/field_decisions.json, then re-run.)")
            else:
                parts = []
                if grey_uncovered:
                    parts.append(f"{n_g} ambiguous cross-source pair(s)")
                if field_uncovered:
                    parts.append(f"{n_c} cross-source value conflict(s)")
                print(f"\nMATCH ADJUDICATION NEEDED: dispatch a sub-agent for {' + '.join(parts)} per "
                      f"{work / 'match_candidates.json'} -> work/match_decisions.json + "
                      f"work/field_decisions.json, then re-run.")
            _exit_round_trip(work, 10, _attempts, "cross-source match/value adjudication")

        # SEMANTIC VERIFIER (grey-match): every current grey pair is COVERED by the author
        # decisions (we did not exit 10). If the second, blind verifier pass is present,
        # DIFF its verdict against the author's per pair in pure Python. A disagreement is
        # ADVISORY - written to work/match_verify_conflicts.json and folded into merge's
        # meta.conflicts -> the Gaps 'Source conflicts' section as a 'match disagreement'
        # line. The AUTHOR verdict still drives clustering (md, above); the verifier never
        # flips it. Recomputed from the cached files on every resume (no live re-dispatch),
        # so built.html stays byte-identical given identical inputs. Absent verify file ->
        # empty diff -> no conflict line -> byte-identical to today (offline-fallback).
        match_verify_f = work / "match_verify.json"
        match_conflicts_f = work / "match_verify_conflicts.json"
        mv_lines: list[str] = []
        if grey and match_verify_f.exists():
            mv = None
            try:
                parsed_v = json.loads(match_verify_f.read_text(encoding="utf-8"))
                if isinstance(parsed_v, dict):
                    mv = parsed_v
            except Exception:
                mv = None  # malformed/half-written -> treat as absent (no advisory, no crash)

            def _verdict(obj, pid):
                v = (obj or {}).get(pid)
                if isinstance(v, dict):
                    v = v.get("verdict")
                return v if v in ("same", "different") else None
            for g in sorted(grey, key=lambda x: x["pair_id"]):  # sorted -> byte-stable
                av = _verdict(md, g["pair_id"])
                vv = _verdict(mv, g["pair_id"])
                if av is not None and vv is not None and av != vv:
                    _ak = _mm.match_key(g["a"]); _bk = _mm.match_key(g["b"])
                    mv_lines.append(
                        f"match disagreement (broker to resolve): pair '{_ak}' vs '{_bk}' - "
                        f"the matching pass judged '{av}', an independent blind verifier judged "
                        f"'{vv}'; the merge used the matching pass. Confirm before sending.")
        # ALWAYS (re)write so a removed/cleared verify file clears a stale advisory; an empty
        # list is a valid, byte-stable state. merge folds it into meta.conflicts via the arg.
        _write_if_changed(match_conflicts_f, json.dumps(mv_lines, ensure_ascii=False))

    # Stage 2 - merge
    canonical = work / "canonical.json"
    ledger_csv = work / "source_ledger.csv"
    merge_args = ["--records", *record_files, "--source-dir", folder,
                  "--project-yaml", proj, "--out", canonical, "--ledger", ledger_csv,
                  # dashboard chrome language (Stage-0 Q3) -> meta.language; the builder
                  # resolves it to the i18n table at render time (per-key EN fallback)
                  "--language", lang,
                  # persistent hero cache: a re-run reuses identical image bytes
                  # instead of re-rastering + re-compressing every brochure page
                  "--image-cache", work / ".image_cache"]
    merge_inputs = [*record_files, proj]
    # LANGUAGE as a merge resume key: the resolved `lang` is passed to merge_args, but on a
    # --resume run the --language FLAG can override project.yaml WITHOUT changing proj's
    # bytes - so without this the merge would resume a STALE-language build. Thread the
    # resolved language through a tiny work-dir file (mirrors requirements.json /
    # field_decisions.json): a changed value bumps its mtime via _write_if_changed ->
    # merge is no longer current -> re-fires -> canonical changes -> build re-runs. The
    # project.yaml output.language path still invalidates too (proj is already an input).
    lang_file = work / ".language"
    _write_if_changed(lang_file, lang)
    merge_inputs.append(lang_file)
    # Phase 2 (fallback): a valid translate-once cache for a non-bundled language -> bake
    # it into canonical.meta.ui_overrides via merge (--ui-overrides), AND add the cache to
    # merge_inputs so a CHANGED translation re-fires merge (-> canonical changes -> build
    # re-runs) - mirrors the .language / requirements.json resume threading above. Absent
    # (bundled/EN, or the exit-11 path already returned) -> not passed -> Phase-1 path.
    if ui_overrides_cache is not None and Path(ui_overrides_cache).exists():
        merge_args += ["--ui-overrides", ui_overrides_cache]
        merge_inputs.append(ui_overrides_cache)
    if requirements:  # carry the questionnaire's requirements into canonical.meta
        req_file = work / "requirements.json"
        _write_if_changed(req_file, json.dumps(requirements, ensure_ascii=False, indent=2))
        merge_args += ["--requirements", req_file]
        merge_inputs.append(req_file)
    po_file = work / "photo_overrides.json"
    if photo_overrides and po_file.exists():  # confident brochure->property photo matches
        merge_args += ["--photo-map", po_file]
        merge_inputs.append(po_file)
    pd_file = work / "photo_descriptions.json"
    if pd_file.exists():  # photo-match sub-agent's per-brochure description picks (quote-verified in merge)
        merge_args += ["--photo-descriptions", pd_file]
        merge_inputs.append(pd_file)  # a changed pick re-merges (resume predicate)
    if match_decisions_f.exists():  # grey-zone cross-source match verdicts (exit-10 sub-agent)
        merge_args += ["--match-decisions", match_decisions_f]
        merge_inputs.append(match_decisions_f)  # a changed decision re-merges (resume predicate)
    if field_decisions_f.exists():  # cross-source VALUE-conflict picks (same exit-10 sub-agent)
        merge_args += ["--field-decisions", field_decisions_f]
        merge_inputs.append(field_decisions_f)  # a changed pick re-merges (resume predicate)
    # SEMANTIC VERIFIER (grey-match): advisory disagreement lines (author verdict vs the
    # blind verifier's) computed in pure Python above; merge folds them into meta.conflicts
    # -> the Gaps 'Source conflicts' section. Absent (single-source / no grey pairs) -> not
    # passed -> byte-identical to today. A changed advisory re-merges (resume predicate).
    match_conflicts_arg = work / "match_verify_conflicts.json"
    if match_conflicts_arg.exists():
        merge_args += ["--match-conflicts", match_conflicts_arg]
        merge_inputs.append(match_conflicts_arg)
    # VISUAL-QA ACK: `plan_rejected` names site plans the reviewer rejected. Passed so a
    # rejection is DURABLE - merge binds no plan from that page in any tier and emits no
    # plan ledger row for it. Added to merge_inputs so recording a rejection re-fires merge
    # (the resume predicate), which is what makes the remedy terminate: previously the only
    # remedy was clearing p.plan in canonical, which the next merge silently undid.
    # DURABLE MANUAL CORRECTIONS (P1-4): work/overrides.json is re-applied by merge AFTER
    # extraction on every run, so a correction survives re-extraction instead of being discarded
    # with the derived work/extract records. In merge_inputs so EDITING one re-fires merge ->
    # canonical changes -> the build re-runs (same predicate as --field-decisions/--plan-rejected).
    overrides_f = work / "overrides.json"
    if overrides_f.exists():
        merge_args += ["--overrides", overrides_f]
        merge_inputs.append(overrides_f)
    # ...and a CONTENT sentinel so DELETING overrides.json also invalidates. _is_current is
    # mtime-based over a list of EXISTING inputs (it `continue`s past a missing one), so a removed
    # file simply drops out of the list and a resumed canonical would keep a correction the broker
    # just RETRACTED. _write_if_changed only writes when the content differs, so a byte-identical
    # rewrite does not churn the mtime and does not re-fire merge.
    _ov_sha = _write_if_changed(
        work / ".overrides_sha",
        hashlib.sha256(overrides_f.read_bytes()).hexdigest() if overrides_f.exists() else "")
    merge_inputs.append(_ov_sha)

    # THE PRODUCING ENVIRONMENT IS AN INPUT. merge harvests decoded pixels, so a change of
    # PDF engine changes what it can extract - and without this the native re-run after a
    # degraded pass resume-skipped merge and served the shim's cached "no usable photo". (B17)
    _eng_stamp = _engine_stamp(work)
    merge_inputs.append(_eng_stamp)

    # MERGE IS WARN-ONLY, DELIBERATELY NOT A RESUME INPUT. (B42)
    #
    # merge is the one expensive stage: with a cold .image_cache, attach_media is a 40-90 s
    # photo harvest inside a ~45 s shell window - i.e. adding this to merge_inputs would
    # manufacture the exact kill/resume spiral that cost 2.5 h on a live run. And it would buy
    # almost nothing, because images.py's cache key carries no code component, so merge would
    # re-run and re-derive BYTE-IDENTICAL images. (What actually invalidates a harvest change is
    # bumping the `v3|` cache-key prefix in images.py - a human decision, recorded there.)
    #
    # So Python prepares the evidence and the human judges whether the re-harvest is worth it.
    # The hole stops being SILENT, which was the actual defect, at zero re-fire cost.
    _merge_code = _code_stamp(work, "merge", [
        HERE / "merge.py", HERE / "match.py", HERE / "images.py", HERE / "normalize.py"])
    try:
        _prev_merge_code = (work / ".code_merge.prev").read_text(encoding="utf-8").strip()
    except Exception:
        _prev_merge_code = ""
    _now_merge_code = _merge_code.read_text(encoding="utf-8").strip()
    if _prev_merge_code and _prev_merge_code != _now_merge_code:
        _say_orchestrator(
            "(orchestrator: this work dir was organised by a DIFFERENT version of the skill's "
            "merge/match/images code. Resume is deliberately NOT invalidated - a cold-cache "
            "re-harvest is 40-90s and would risk a capped-shell loop. If the change affects "
            "how records merge or photos are chosen, re-run once with --no-resume.)")
    _write_if_changed(work / ".code_merge.prev", _now_merge_code)

    # ANSWERED CLARIFICATIONS are a merge input, or a freshly-answered question would sit in
    # the work dir while resume skipped the very stage that consumes it. (B38)
    _cs = work / "clarify_state.json"
    if _cs.exists():
        merge_args += ["--answers", work]
        merge_inputs.append(_cs)

    plan_ack_f = work / "placeholder_audit_ack.json"
    if plan_ack_f.exists():
        merge_args += ["--plan-rejected", plan_ack_f]
        merge_inputs.append(plan_ack_f)
    # P2-10: merge runs attach_media, which can sit silent for 40-90s harvesting brochure
    # photos, so a capped run looks hung. Fold ONE clause into the single step marker, but
    # ONLY when there is real harvest work (brochures or images present) - a tracker- or
    # email-only merge is fast and must not claim to be "fetching photos". The branch
    # reuses the SAME resume predicate as the merge call below, so the marker can never
    # disagree with what actually happens.
    _has_media = bool(inv.get("clusters")) or bool(inv.get("images"))
    if _is_current(canonical, merge_inputs) and _is_current(ledger_csv, merge_inputs):
        step("Organising the options")
        _resumed("merge")  # canonical + ledger already reflect every current record file
    else:
        if _has_media and (work / ".image_cache").exists():
            step("Organising the options - resuming")
        elif _has_media:
            step("Organising the options - fetching photos")
        else:
            step("Organising the options")
        # PRE-WARM the image cache in PARALLEL, up front, before merge: the slow
        # raster+compress harvest is the merge bottleneck (it can sit silent for 40-90s
        # and overrun the ~40s sandbox shell cap). Doing it across CPUs - bounded by a
        # soft budget, each unit cached atomically so it resumes - means merge then runs
        # as cache hits and finishes inside the window. Identical cache bytes -> merge
        # output is unchanged. Best-effort: any failure just falls back to merge harvesting.
        if _has_media:
            try:
                import os as _os
                import images as _IMG
                secs = float(_os.environ.get("CBRE_PREWARM_SECONDS") or 30)
                recs = []
                for rf in record_files:
                    try:
                        recs += json.loads(Path(rf).read_text(encoding="utf-8"))
                    except Exception:
                        pass
                done, total = merge.prewarm_images(recs, folder, work / ".image_cache",
                                                   _IMG.DEFAULT_BUDGET_KB, seconds=secs)
                if total:
                    msg = (f"   photo cache: {done}/{total} images ready"
                           + (" - complete" if done >= total
                              else " (re-run the same command to warm the rest)"))
                    print(msg)
            except Exception as e:
                if not QUIET:
                    print(f"(image pre-warm skipped: {e})", file=sys.stderr)
        call(merge, *merge_args)

    # P1-4: re-surface the override OUTCOMES. merge printed them, but call() swallows child stdout
    # under --quiet - and a correction that matched NOTHING is precisely what must not be silent.
    # Read back from the report merge wrote, unconditionally.
    _ov_rep = work / "overrides_report.json"
    if _ov_rep.exists():
        try:
            _rep = json.loads(_ov_rep.read_text(encoding="utf-8")) or {}
        except Exception:
            _rep = {}
        for _k, _tag in (("stale", "STALE OVERRIDE"), ("ambiguous", "AMBIGUOUS OVERRIDE"),
                         ("superseded", "SUPERSEDED OVERRIDE")):
            for _s in (_rep.get(_k) or []):
                print(f"[{_tag}] {_s.get('id')} {_s.get('reason', '')}")
        for _iv in (_rep.get("invalid") or []):
            print(f"[INVALID OVERRIDE] {_iv} - this entry does NOTHING until it is fixed.")
        _n_ok = len(_rep.get("applied") or [])
        if _n_ok and not QUIET:
            print(f"({_n_ok} manual correction(s) applied - each has an `override` row in the "
                  f"Source Ledger and a line in the Gaps Report.)", file=sys.stderr)

    # Stage 3 - enrichment (flags override project.yaml; default to project.yaml)
    enr_args = []
    requested_layers = []  # for the enrichment gate (P2-9): a requested-but-absent layer blocks
    for name, flag in (("geocode", args.geocode), ("pois", args.pois),
                       ("osrm", args.osrm), ("regions", args.regions)):
        if flag or enr.get(name):
            enr_args.append(f"--{name}")
            requested_layers.append(name)
    # openrouteservice key -> TRUCKING (driving-hgv) drive times. Per-project
    # (project.yaml) or per-user (env var) - NEVER baked into the shared skill.
    import os
    ors_key = str(enr.get("ors_api_key") or os.environ.get("ORS_API_KEY", "")).strip()
    if "--osrm" in enr_args and ors_key:
        enr_args += ["--ors-key", ors_key]
    # enrich mutates canonical IN PLACE, so on --resume it is gated by a content-hash
    # stamp: skip only when the canonical bytes AND the chosen flags exactly match the
    # last completed enrich. If merge re-ran (canonical changed) or the flags changed,
    # the hash won't match and enrich re-runs. This keeps a resumed build byte-stable
    # without assuming enrich is perfectly idempotent offline.
    stamp = work / ".enrich.stamp"
    enr_key = "|".join(sorted(enr_args))
    if enr_args:
        step("Adding maps and extras")
        skip_enrich = False
        if RESUME and stamp.exists():
            try:
                prev = json.loads(stamp.read_text(encoding="utf-8"))
                skip_enrich = (prev.get("args") == enr_key and prev.get("hash") == _sha(canonical))
                # a cache seeded AFTER the last enrich (web_enrich ingest, seed_geocode,
                # a fresh regions_cache, the interpretation sub-agent's region_labels.json)
                # must re-run enrichment - that is the whole point of the handoff. Without
                # region_labels.json here, the exit-3 region-label round-trip would loop:
                # the sub-agent writes the resolution but bind_region_codes is never re-run.
                if skip_enrich:
                    s_m = stamp.stat().st_mtime
                    for c in ("poi_osm_cache.json", "osrm_cache.json",
                              "geocode_cache.json", "regions_cache.json",
                              "extract/region_labels.json"):
                        cf = work / c
                        if cf.exists() and cf.stat().st_mtime > s_m:
                            skip_enrich = False
                            break
            except Exception:
                skip_enrich = False
        if skip_enrich:
            _resumed("enrichment")
        else:
            # --cache-dir = the work dir explicitly (enrich's default is the canonical's
            # folder; being explicit keeps the geocode/POI/region caches in a stable,
            # reused location across --resume runs - warm cache, no repeated network).
            # --ledger so every enrichment-filled field (lat/lng/country, drive-times,
            # region figures) gets a trace row - the audit artefact must never
            # contradict the deliverable.
            call(enrich, canonical, *enr_args, "--cache-dir", work,
                 "--ledger", ledger_csv, check=False)
            try:
                stamp.write_text(json.dumps({"args": enr_key, "hash": _sha(canonical)}), encoding="utf-8")
            except Exception:
                pass
    elif stamp.exists():
        try:
            stamp.unlink()  # enrichment turned off -> drop the stale stamp
        except Exception:
            pass

    # WEB-ENRICHMENT HANDOFF (exit 8): the broker asked for POIs/drive-times but the
    # sandbox network is dead and the caches are cold. A library stand-in is NOT the
    # product (the value is the GENUINE nearest per property), so emit the exact
    # Overpass/OSRM requests for the orchestrator's WebFetch and stop BEFORE the
    # gates/build - exactly like the vision manifest. After `web_enrich.py ingest`,
    # the re-run attaches genuine data from the warm caches fully offline.
    if enr_args:
        try:
            canon_data = json.loads(canonical.read_text(encoding="utf-8"))
            enr_state = canon_data.get("meta", {}).get("enrichment", {})
        except Exception:
            canon_data, enr_state = {}, {}
        want = []
        if "--geocode" in enr_args and any(
                not isinstance(p.get("lat"), (int, float)) and _filled(p.get("city"))
                for p in canon_data.get("properties", [])):
            want.append("--geocode")  # cities the dead-network geocoder could not place
        if "--pois" in enr_args and not enr_state.get("pois_live"):
            want.append("--pois")
        if "--osrm" in enr_args and not enr_state.get("osrm_done") and enr_state.get("pois_live"):
            want.append("--osrm")  # drive times need the discovered POIs first
        if want:
            if "--osrm" in want and ors_key:
                want += ["--ors-key", ors_key]  # trucking matrix requests, not car OSRM
            rc = call(web_enrich, "plan", canonical, "--work", work, *want, check=False)
            if rc == 0:  # fetchable requests were emitted
                n_req = 0
                try:
                    n_req = len(json.loads((work / "web_requests.json")
                                           .read_text(encoding="utf-8")).get("requests", []))
                except Exception:
                    pass
                page = work / "web_enrich.html"
                # Write a .claude/launch.json serving the work dir for the Claude Preview MCP
                # tier (tier 3 of the probe order): the Preview MCP launches the server in the
                # namespace its own browser CAN reach - unlike a server hand-started from the
                # sandbox shell, which lives in a different network namespace so the browser
                # cannot route to its 127.0.0.1 (the real "server/renderer unreachable" dead-end,
                # NOT a missing renderer). Used only if mcp__shell (tier 1, direct run) and the
                # Playwright data: URL fetcher (tier 2) are both absent. Mirrors render_qa.py's
                # G-visual launch.json. Guarded: a write failure must never turn an enrichment
                # handoff into a crash - the chat handoff (tier 4) works fine without it.
                try:
                    launch = {"version": "0.0.1", "configurations": [{
                        "name": "longlist-preview", "runtimeExecutable": "python",
                        "runtimeArgs": ["-m", "http.server", "8799",
                                        "--directory", str(work.resolve())],
                        "port": 8799}]}
                    cl = work.resolve() / ".claude"; cl.mkdir(exist_ok=True)
                    (cl / "launch.json").write_text(json.dumps(launch, indent=2), encoding="utf-8")
                except Exception:
                    pass
                if QUIET:
                    # A neutral step marker only. It is ALWAYS the Cowork sandbox; the
                    # orchestrator PROBES which tools are present and uses the FIRST available -
                    # (1) mcp__shell (direct re-run, no page), (2) the Playwright data: URL
                    # fetcher, (3) the Claude Preview MCP via the launch.json above; only if none
                    # is present or the fetch is blocked does it DELIVER the page in the chat with
                    # its own one-liner (org users never see the work folder; seeds come back the
                    # same way).
                    print("Adding maps and extras")
                    _say_orchestrator(
                        f"(orchestrator: web enrichment needed ({n_req} request(s)). PROBE tools, "
                        f"use the FIRST present: (1) mcp__shell - re-run this command THROUGH it "
                        f"(direct live fetch, no page); (2) Playwright - data: URL fetcher per "
                        f"request in {work}/web_requests.json (navigate request['data_url'], read "
                        f"back with browser_evaluate filename=save_as); (3) Claude Preview MCP - "
                        f"preview_start 'longlist-preview' -> click #go -> read the seeds object "
                        f"from {page}. If none or the fetch is blocked, ATTACH {page} in the chat; "
                        f"when the user drops web_seeds.json back, save it to {work}, run "
                        f"web_enrich.py ingest --work {work}, re-run. WebFetch CANNOT reach these "
                        f"API hosts - it is not a path.)")
                else:
                    print(f"\nWEB ENRICHMENT NEEDED ({n_req} request(s)). It is ALWAYS the Cowork "
                          f"sandbox; PROBE which tools are present and use the FIRST available: "
                          f"(1) mcp__shell (native, has network) - re-run this command THROUGH it; "
                          f"the helpers hit the live APIs and bake the caches directly, no page. "
                          f"(2) the Playwright MCP - the data: URL fetcher: per request in "
                          f"{work}/web_requests.json, navigate request['data_url'] and read back "
                          f"with browser_evaluate(filename=save_as) into {work}/web_fetched/. "
                          f"(3) the Claude Preview MCP - preview_start 'longlist-preview', click "
                          f"#go, read the seeds object from {page}. (4) ELSE deliver {page} to the "
                          f"user IN THE CHAT; they open it in a browser (any network that reaches "
                          f"OSM), 'Fetch all', and drop web_seeds.json back - save it to {work}. "
                          f"Then `python helpers/web_enrich.py ingest --work {work}` and re-run "
                          f"this command - it resumes and bakes the GENUINE nearest POIs + real "
                          f"drive times. (WebFetch cannot reach these API hosts; it is not a "
                          f"fallback.)")
                _exit_round_trip(work, 8, _attempts, "web enrichment (geocodes/POIs/drive times)")

    # REGION-LABEL RESOLUTION (exit 3, rides the SAME interpretation manifest - no new exit
    # code). After enrich has bound every region it can DETERMINISTICALLY (coords -> exact
    # point-in-polygon, then a resolving label/code, then the city), a fuzzy/typo'd/new-
    # language label that matches NEITHER the dataset name_index/aliases NOR a city is left
    # unbound (and PIP could not override it because the property has no coords). That lexical
    # miss - and ONLY that miss - is offered to the isolated interpretation sub-agent as a
    # CLOSED-SET classification: given the raw label + city + country + a candidate list drawn
    # from the dataset's own NUTS names, return one candidate code or null (never an invented
    # code). The pick is cached in work/extract/region_labels.json; enrich's bind_region_codes
    # re-verifies it via _dataset_region before binding, the coords->PIP bind still wins for
    # any property that later gains coordinates, and the difflib gap stays the fallback when
    # the model returns null. The deterministic dictionary (_dataset_region) is the verifier;
    # this never fires offline (no cache file -> pure deterministic fallback, byte-identical).
    if "regions" in requested_layers:
        try:
            canon_data = json.loads(canonical.read_text(encoding="utf-8"))
        except Exception:
            canon_data = {}
        ds = enrich._regions_dataset()
        unresolved_labels = enrich.unresolved_region_labels(canon_data, ds) if ds else []
        if unresolved_labels:
            rl_out = work / "extract" / "region_labels.json"
            rl_out.parent.mkdir(parents=True, exist_ok=True)
            # ANSWERED keys, not the bind cache's: _region_labels_cache() drops declined
            # (code=null) entries - correct for binding, but as the "already asked" set it
            # re-emitted a declined label's job every re-run and exit 3 never converged.
            cached_keys = enrich._region_labels_answered_keys()
            # scope the candidate list to the country prefixes already present in the project
            # (fork rec B): cross-country false binds become impossible; fall back to the full
            # list only for a single-property project with no known country anywhere.
            project_ccs = {enrich._property_country_cc(p)
                           for p in canon_data.get("properties", [])} - {""}
            region_jobs = []
            for raw_label, city, cc in unresolved_labels:
                key = enrich._region_label_key(raw_label, cc, city)
                if key in cached_keys:
                    continue  # already resolved (or declined) - resume no-op, no job
                ccs = [cc] if cc else sorted(project_ccs)
                region_jobs.append({
                    "key": key, "raw_label": raw_label, "city": city, "country_cc": cc,
                    "candidates": enrich.region_label_candidates(ds, ccs)})
            if region_jobs:
                (work / "vision").mkdir(parents=True, exist_ok=True)
                # PRESERVE THE DECKS. This rewrites the shared interpretation manifest, and
                # writing `decks: []` did not merely blank a field: vision_validate builds its
                # deck index from it, so from the first region-label exit-3 onward EVERY
                # deck-gated check - page_no and image_pages and plan_page and exclude_refs
                # range, the source_file cross-check, the twin-text reconciliation and the
                # page-coverage warning - silently no-opped for the life of the work dir.
                # No diagnostic fired either, because `{"decks": []}` is valid JSON so the
                # "manifest unreadable" warning never triggered. (B14)
                _prev_decks = []
                try:
                    _prev_decks = (json.loads(manifest.read_text(encoding="utf-8"))
                                   .get("decks") or [])
                except Exception:
                    _prev_decks = []
                payload = {
                    "decks": _prev_decks,
                    "region_labels": region_jobs,
                    "output": "work/extract/region_labels.json",
                    "region_label_instructions": (
                        "Each `region_labels` entry is a property REGION LABEL the bundled "
                        "dataset and the curated aliases could NOT resolve to a NUTS code, and "
                        "which has no coordinates (so the authoritative point-in-polygon bind "
                        "cannot fix it). Dispatch an isolated interpretation sub-agent "
                        "(reference/interpretation.md 'Region label resolution'). Given ONLY the "
                        "job's `raw_label`, `city`, `country_cc` and `candidates` (a CLOSED list "
                        "of {code, name, country} from the dataset's own NUTS names, scoped to the "
                        "country), map the label to the ONE candidate `code` that names the same "
                        "province/region (a typo, a renamed area, a new-language synonym -> pick "
                        "it), or `null` when no candidate is a confident match. NEVER invent a "
                        "code outside `candidates`; NEVER return workforce figures; null over a "
                        "guess (a null falls back to the self-documenting difflib gap). Write "
                        "work/extract/region_labels.json: {\"resolutions\": [{\"raw_label\": "
                        "\"<echoed>\", \"city\": \"<echoed>\", \"country_cc\": \"<echoed>\", "
                        "\"code\": \"ES424\"|null, \"matched_name\": \"Guadalajara\"|null, "
                        "\"confidence\": \"high|medium|low\", \"reason\": \"one line\"}]} with one "
                        "entry per job (the cache key is rebuilt from raw_label+country_cc+city). "
                        "Python re-verifies every returned code via the dataset before binding "
                        "and the point-in-polygon bind still wins when coords exist. Then re-run "
                        "run.py - it resumes and binds the verified codes."),
                }
                manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                n_rl = len(region_jobs)
                if QUIET:
                    print("A few region labels in your files need matching to the workforce "
                          "dataset before I add the maps and extras.")
                    _say_orchestrator(
                        f"(orchestrator: dispatch the interpretation sub-agent for {n_rl} "
                        f"region label(s) per {manifest} -> work/extract/region_labels.json "
                        f"(reference/interpretation.md 'Region label resolution'), then "
                        f"re-run.)")
                else:
                    print(f"\nREGION LABEL RESOLUTION NEEDED ({n_rl} label(s)): dispatch the "
                          f"interpretation sub-agent per {manifest} -> "
                          f"work/extract/region_labels.json (reference/interpretation.md "
                          f"'Region label resolution'), then re-run.")
                _exit_round_trip(work, 3, _attempts, "region-label resolution")

    # --- Phase 2: free-text DATA translation to output.language (exit 12; mirrors exit 11) ----
    # Runs AFTER merge/enrich/web-enrich/region-label have all settled canonical.json (a
    # translation must see the FINAL prose, not a value enrichment/region-label might still
    # touch) and BEFORE the pre-build gates score it. Determinism (translate.collect_requests/
    # bake) decides WHAT needs translating and applies a cached round; the LLM (an isolated
    # sub-agent, never this process) does the actual translation. Never sys.exit inside
    # translate.py itself - run.py owns the exit code, exactly like every other stage here.
    _t_rc = translate.run_stage(work, canonical, ledger_csv, lang, quiet=QUIET)
    if _t_rc == 12:
        import i18n as _i18n
        _tcode = _i18n.normalize_lang(lang)
        # B54: the data is already in the dashboard's language, so there is nothing to translate.
        # Drop the SKIP sentinel (the documented decline, which the translation gate reads as an
        # acknowledged one) and carry on rather than spending an agent dispatch plus a shell
        # round-trip mapping English onto English. The note records WHY, so the decline is
        # disclosed rather than silent.
        try:
            _canon_obj = json.loads(Path(canonical).read_text(encoding="utf-8"))
        except Exception:
            _canon_obj = {}
        if _lang_skip(_canon_obj, _tcode):
            _skip_note = (f"Free-text translation skipped: every source deck declares "
                          f"'{_tcode}', which matches the dashboard language. Records that "
                          f"declare no language (tracker rows) are assumed to share it.")
            _skip_f = work / "i18n" / "data_translate.SKIP"
            _skip_f.parent.mkdir(parents=True, exist_ok=True)
            _write_if_changed(_skip_f, _skip_note)
            if not QUIET:
                print(f"\nDATA TRANSLATION SKIPPED -> {lang}: {_skip_note}")
            _t_rc = None
    if _t_rc == 12:
        req = work / "i18n" / "data_translate_request.json"
        cache_f = work / "i18n" / f"data_translations.{_tcode}.json"
        if QUIET:
            print(f"Translating the descriptions to {lang}… (one-time)")
        else:
            print(f"\nDATA TRANSLATION NEEDED -> {lang}. Dispatch an ISOLATED translation sub-agent: "
                  f"translate the `items` in {req} (PROSE only; keep numbers/units/codes/names/dates "
                  f"verbatim), MERGE the returned {{text: translation}} map into "
                  f"{cache_f}, then re-run the SAME command. "
                  f"Blind-verify as G-lang before shipping. (Or `type nul > "
                  f"{work / 'i18n' / 'data_translate.SKIP'}` to ship the data in its source language.)")
        _exit_round_trip(work, 12, _attempts, "free-text data translation")

    # Stage 4 - pre-build gates (mechanical halves; judgement gates run separately)
    step("Checking the data") if QUIET else print("\n=== PRE-BUILD GATES (mechanical) ===")
    g1 = [run_gate(gate_runner, "self-check")]
    vd = run_gate(gate_runner, "validate-data", canonical)
    g1.append(vd)
    # honour the broker's qa.fill_threshold from project.yaml (else the gate default)
    cov_args = ["coverage", canonical]
    fill_thr = (cfg.get("qa") or {}).get("fill_threshold")
    if fill_thr is not None:
        cov_args += ["--fill-threshold", fill_thr]
    g1.append(run_gate(gate_runner, *cov_args))
    g1.append(run_gate(gate_runner, "trace-coverage", canonical, "--ledger", ledger_csv))
    # B52: a value citing "page N" must actually occur on that page. Sits beside trace-coverage
    # because it is the same question one level deeper - trace-coverage asks whether a field HAS
    # a locator, this asks whether the locator is TRUE.
    g1.append(run_gate(gate_runner, "prov-containment", canonical,
                       "--work", work, "--ledger", ledger_csv))
    g1.append(run_gate(gate_runner, "images", canonical))
    # P1-1: pre-build, so an over-derived GLA (and the rent computed from it) is caught before a
    # dashboard is ever built. Inert on any dataset whose sources state no total of their own.
    g1.append(run_gate(gate_runner, "arithmetic", canonical))
    # B59: a field must be WRITTEN the same way on every property that carries it. Sits beside
    # arithmetic because both police how a NUMBER reaches the client - arithmetic checks the
    # magnitude, this checks that the magnitude is legible. Live defect: divisibleFrom shipped
    # '10,000 sq. m' on twelve cards and a bare '5000' on the thirteenth.
    g1.append(run_gate(gate_runner, "value-format", canonical))
    # B60: a town-centre pin while the property's OWN page carries the author's coordinates or a
    # maps link. Runs post-enrich because it judges the FINAL coordinate, not the extracted one.
    g1.append(run_gate(gate_runner, "coord-provenance", canonical,
                       "--work", work, "--ledger", ledger_csv))
    g1.append(run_gate(gate_runner, "enrichment", canonical,
                       *(["--requested", ",".join(requested_layers)] if requested_layers else [])))
    g1.append(run_gate(gate_runner, "translation", canonical, "--work", work, "--lang", lang))
    # the ledger validator is a pre-build gate like the others (source-traceability.md:
    # an incomplete row blocks) - it belongs IN the scorecard, not as a side note
    g1.append(run_gate(ledger, "validate", ledger_csv))
    # persist the mechanical scorecard the orchestrator reads before the review
    # window. Judgement verdicts live separately in reviews/*.md.
    write_scorecard(work / "gate1_scorecard.md", "Pre-build gate scorecard (mechanical)")
    # exhaustive image aid for the isolated G-images reviewer: one montage of every
    # property photo (labelled, placeholders auto-tagged) -> a single pass, not rounds
    call(contact_sheet, canonical, "--out-dir", work / "render", check=False)
    # FREEZE AUTOMATION (gates.md "Reviewer dispatch contract"): at ALL-PASS, snapshot
    # canonical.json so the parallel judgement reviewers (and final_gate freeze --check)
    # have their byte-identity proof WITHOUT the orchestrator remembering a manual step.
    # On a blocked scorecard, drop any stale snapshot so nothing can key on bytes that
    # predate the failure.
    frozen_side = canonical.with_suffix(canonical.suffix + ".frozen.sha256")
    if all(rc == 0 for rc in g1):
        # freeze ALSO regenerates the photo-stripped canonical_review.json twin the
        # isolated DATA reviewers (G-honesty/G-trace/G-enrich) read - one emission
        # point (the freeze), so the twin can never go stale relative to the frozen
        # bytes, and a manual re-freeze after an out-of-band data fix refreshes it too.
        call(gate_runner, "freeze", canonical, check=False)
    elif frozen_side.exists():
        try:
            frozen_side.unlink()
        except Exception:
            pass
    # SHIFT-LEFT, fully: NO pre-build gate may be red when the expensive build runs -
    # building on a blocked scorecard wasted a build + post-gates + deliver and told
    # the broker "Done" over a known-bad dataset.
    if vd != 0:
        if QUIET:
            print("The information in your files has a problem I can't build over - I need to "
                  "check the inputs with you before going further.")
            _say_orchestrator(
                f"(orchestrator: validate-data BLOCKED (exit 5) - see {work / 'gate1_scorecard.md'}; "
                f"fix the inputs/data and re-run.)")
        else:
            print("\nBLOCKED: validate-data failed (schema/consistency defect). Not building - "
                  "fix the inputs/data and re-run (gate1_scorecard.md has the specifics).")
        sys.exit(5)
    if any(rc != 0 for rc in g1):
        if QUIET:
            print("A quality check on the data needs sorting before I can finish the dashboard - "
                  "I can't hand it over as it stands.")
            _say_orchestrator(
                f"(orchestrator: {sum(1 for rc in g1 if rc != 0)} pre-build gate(s) BLOCKED (exit 6) - "
                f"see {work / 'gate1_scorecard.md'}, fix, and re-run; resume skips clean stages.)")
        else:
            print(f"\nBLOCKED: {sum(1 for rc in g1 if rc != 0)} pre-build gate(s) red - not building. "
                  f"See {work / 'gate1_scorecard.md'}, fix, and re-run (resume skips clean stages).")
        sys.exit(6)

    # Stage 5 - build
    step("Building the dashboard")
    filename = (cfg.get("output") or {}).get("filename") or f"CBRE_Property_Dashboard_{args.client}.html"
    built = work / "built.html"
    # AUTO-INVALIDATE on a code change, because build is CHEAP - a measured ~0.07-0.3 s, so a
    # spurious rebuild costs nothing and a missed one used to be an exit-7 'chrome drift' dead
    # end that no re-run could clear. This is the render closure, verified: anything else cannot
    # change built.html for a fixed canonical. (B42)
    _build_stamp = _code_stamp(work, "build", [
        HERE / "build_dashboard.py", HERE / "i18n.py", HERE / "normalize.py",
        HERE / "_common.py", HERE.parent / "assets" / "dashboard_template.html"])
    if _is_current(built, [canonical, _build_stamp]):
        _resumed("build")  # built.html already reflects the current canonical
    else:
        call(build_dashboard, canonical, "--out", built)

    # Stage 6 - post-build gates (mechanical; G-visual runs separately via MCP)
    step("Final checks") if QUIET else print("\n=== POST-BUILD GATES ===")
    g2 = [run_gate(gate_runner, "validate-html", built, "--canonical", canonical),
          run_gate(gate_runner, "reconcile", built, "--canonical", canonical),
          # G-i18n deterministic floor: the rendered chrome is complete + actually
          # localised for the resolved language (no silent EN fallback, no unfilled
          # token, well-formed LOCALE, placeholders intact). The blind LLM G-i18n
          # rubric is its live Cowork counterpart (reference/gates.md).
          run_gate(gate_runner, "i18n", built, "--canonical", canonical)]
    write_scorecard(work / "gate2_scorecard.md", "Post-build gate scorecard (mechanical)")
    if any(rc != 0 for rc in g2):
        # a red post-build gate means the built file is wrong - never deliver it
        if QUIET:
            print("A final check on the built dashboard flagged a problem, so I'm not handing "
                  "this version over.")
            _say_orchestrator(
                f"(orchestrator: post-build gate BLOCKED (exit 7) - not delivering; "
                f"see {work / 'gate2_scorecard.md'}.)")
        else:
            print(f"\nBLOCKED: post-build gate red - not delivering. See {work / 'gate2_scorecard.md'}.")
        sys.exit(7)

    # Stage 7 - deliver. Resume guard (mirrors Stage 5): skip only when the primary
    # deliverable (the dashboard at its CURRENT flag-derived filename) is already newer
    # than every input deliver reads - built.html, canonical (language/flags are baked into
    # it by merge), the ledger csv, and the Gaps sidecars. A changed canonical/built/ledger,
    # or a new output filename (a flag change), fails the check and re-delivers. --no-resume
    # => _is_current is always False => unchanged behaviour for the byte-identity battery. (#25)
    deliverables = work / "deliverables"
    # qa_state.json is load-bearing, not decorative: final_gate BLOCKS when the delivered Gaps
    # Report's "Known limitations" is not the LATEST recorded round's carried list. Without it
    # here, a fresh `qa-round record` leaves Stage 7 looking current, --resume (the DEFAULT) skips
    # the re-deliver, and that block can never be cleared through the spine. With it, the stage is
    # stale exactly once: re-delivering bumps the dashboard past qa_state.json, so the next run
    # resume-skips again. No oscillation.
    _deliver_inputs = [built, canonical, ledger_csv,
                       work / "photo_doubts.json", work / "unreadable.json",
                       work / "yield_report.md", work / "qa_state.json",
                       # deliver is seconds, so auto-invalidating on a code change is free (B42)
                       _code_stamp(work, "deliver", [
                           HERE / "deliver.py", HERE / "ledger.py", HERE / "normalize.py",
                           HERE / "_common.py"])]
    # Two conditions, and BOTH are load-bearing (B01). `_is_current` answers "are the inputs
    # unchanged?"; `delivery_complete` answers "did the last delivery actually FINISH?".
    # Keying on the dashboard alone answered neither: it is written FIRST, so it went current
    # the instant step 1 committed and a kill in steps 2-4 resume-skipped forever - shipping
    # a v2 dashboard beside v1 sidecars, or leaving three artefacts that final_gate then
    # failed with no way through the spine.
    import deliver as _deliver_mod  # imported inside main(), as every helper here is
    if _is_current(deliverables / filename, _deliver_inputs) \
            and _deliver_mod.delivery_complete(deliverables):
        _resumed("deliver")
    else:
        call(deliver, "--canonical", canonical, "--html", built,
             "--ledger", ledger_csv, "--out-dir", deliverables, "--slug", args.client,
             "--filename", filename)

    # PHOTO-MATCH DOUBTS (P0-1): an uncertain brochure<->property pairing ships as a
    # PLACEHOLDER and is surfaced here as an actionable yes/no prompt - the broker
    # confirms and the photo is pulled in immediately (the orchestrator moves that
    # entry from 'uncertain' to 'confident' in work/photo_map.json and re-runs).
    if photo_doubts:
        print("\nPlaceholders (uncertain photo match - confirm to pull the picture in immediately):")
        for d in photo_doubts:
            print(f"  {d['park']}  -->  Is this {d['brochure']}? If yes, I'll extract its photo now.")
        _say_orchestrator(
            "(orchestrator: on a 'yes', move that brochure from \"uncertain\" to \"confident\" in "
            "work/photo_map.json and re-run; on a 'no', leave it as \"unrelated\".)")
    if QUIET:
        step("Done - dashboard ready")
        # P3-10: tell the broker WHERE the deliverable is, and flag the Gaps Report ONLY
        # when there are REAL gaps to chase (not merely because the file always exists).
        # Reuse deliver.py's own CORE + _is_tbd so this matches the Gaps Report exactly.
        _clear_attempts(work)  # the spine got through: no request is outstanding
        print(f"Your dashboard and its files are ready in {deliverables}.")
        # flag the Gaps Report ONLY when it has real content to chase (not merely
        # because the file always exists); the helper mirrors every section
        # deliver.gaps_report emits, so the note matches the report exactly.
        if _gaps_to_chase(canonical, failed_preps, photo_doubts, unreadable_inputs, yield_notes):
            print("Some details are still missing - see the Gaps Report in that folder "
                  "for what to chase with the landlord or agent.")
        # P3-7: the 'Remaining agentic steps' reminder below is after this quiet return,
        # so it would be suppressed. Mirror the exit-8 stderr precedent: emit an
        # orchestrator-phrased reminder (final_gate.py is the backstop). STDOUT: it is a
        # handoff instruction, and stderr is invisible through mcp__shell. (B27)
        _say_orchestrator(
              "(orchestrator: spine done - run the remaining AGENTIC steps per SKILL.md "
              "(emails/region research as configured, then the isolated G-honesty / G-trace / "
              "G-images / G-visual reviewers). The QA window is ONE review pass: the reviewers "
              "PROPOSE findings, you IMPLEMENT them, then deliver. Dispatch the gate batch "
              f"concurrently -> `gate_runner.py qa-round record --work {work} --reviews "
              f"{work}\\reviews` -> implement each `blocking:` finding and record it with "
              "`qa-round resolve --id <id> --because \"<what you changed>\"` -> deliver -> "
              f"`final_gate.py ... --qa-state {work}`. Advisory findings are CARRIED to the Gaps "
              "Report's 'Known limitations', not fixed and not re-reviewed. There is no second "
              "review pass and no adjudication round. final_gate.py is the ship backstop - it "
              "blocks while any blocking finding has no recorded repair; do not declare done to "
              "the broker until it passes.)")
        return
    print(f"\nDONE. Deliverables in {deliverables}")
    esrc = ((cfg.get("inputs") or {}).get("emails") or {}).get("source", "none")
    if esrc == "outlook":
        email_step = "Outlook email extraction (outlook_email_search sub-agent)"
    elif esrc == "folder":
        efolder = ((cfg.get("inputs") or {}).get("emails") or {}).get("folder", "")
        email_step = f"email extraction from the folder '{efolder}' (extract_email.py + offer-extraction), re-run merge"
    else:
        email_step = None
    regions_on = bool((cfg.get("enrichment") or {}).get("regions") or args.regions)
    reviewer_step = ("the isolated G-honesty / G-trace / G-images"
                     + (" / G-enrich" if regions_on else "")
                     + " / G-visual reviewers")  # G-enrich is REQUIRED by final_gate when regions ran
    steps = [s for s in (email_step, "region research" if regions_on else None, reviewer_step) if s]
    print("Remaining agentic steps (see SKILL.md): " + "; ".join(steps) + ".")


if __name__ == "__main__":
    main()
