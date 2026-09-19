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
  5 = validate-data blocked (schema/consistency defect - fix inputs/data). Its mapped action
      is "read gate1_scorecard.md, record the correction in work/overrides.json", so it belongs
      to the GATE path only: an INVALID CORRECTION FILE now exits 16 instead, because on that
      path the scorecard does not exist yet and appending to overrides.json would mean adding
      to the very file being rejected.
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
      plausibly the same property - within ~2 km / a shared distinctive IDENTITY token,
      read across ALL the park/address/scheme-ish fields with place words stripped / a
      borderline fuzzy key / a party name linking the two records inside one city; a
      shared city ALONE is never a signal), AND (b) some genuine cross-source VALUE CONFLICTS
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
 14 = the INDEPENDENT QA REVIEW is missing: dispatch ONE isolated sub-agent per rendered
      work/prompts/g-*.md file (each file is that agent's verbatim prompt and names its own
      output path), plus any outstanding email ingestion the handoff names, then re-run.
 15 = a BLOCKING QA FINDING is unresolved: implement each fix, record it with
      `gate_runner.py qa-round resolve --work <work> --id <id> --because "<what changed>"`,
      then re-run. Advisory findings are never fixed - they ship in the Gaps Report.
 16 = a CORRECTION FILE holds INVALID ENTRIES and the run refused to start. Fired at STARTUP,
      before any stage does work, with EVERY fault in work/overrides.json and work/repairs.json
      printed in one pass. The ONE action: read the printed fault list and FIX the NAMED
      entries IN PLACE in the NAMED file (or DELETE a stale one), then re-run the SAME command.
      Do NOT append new entries - the file being rejected is the file to edit - and do NOT read
      gate1_scorecard.md: the gates have not run and it may not exist yet. This is deliberately
      NOT exit 5: 5's mapped action is "read the scorecard, record the correction in
      overrides.json", which on this path means appending to the rejected file, so an
      orchestrator following the contract would loop, adding an entry each round.
      `--allow-invalid-corrections` is the escape hatch: it prints the same faults, IGNORES
      the faulty entries (the behaviour before this check existed) and proceeds - so whatever
      those entries were meant to correct ships UNCORRECTED. It fixes nothing.

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
                [--from <stage>] [--only <stage>[,<stage>...]]
                [--allow-invalid-corrections]

  --from <stage>   put every stage BEFORE it in the ordered vocabulary OUT OF SCOPE, even under
                   --no-resume: each of those stages then reuses its existing output instead of
                   re-deriving it. WHAT IT DOES AND DOES NOT SAVE, because the older wording
                   ("start the pass AT that stage") promised more than the flag delivers: the
                   cut is applied by each stage's OWN skip guard, not by jumping into the run at
                   the named stage, so an out-of-scope stage still runs whatever sits outside
                   that guard. `extract` is the one that matters - its body runs on every pass
                   regardless (the readers dispatch, the photo clustering, the interpretation
                   manifest and the exit-3/9/10 handoffs), and only the per-tracker record
                   derivation consults the cut. So on a WARM work dir `--from` is behaviourally
                   the same as the default resume, and its one measurable saving is under
                   --no-resume, where it stops the earlier stages recomputing output that is
                   already on disk. Its VALUE is that it is honest about REACH rather than
                   fast: `--from repairs` after editing work/repairs.json states, on the record
                   and in the command, that the correction is applied AFTER merge and therefore
                   cannot change merge or enrichment.
  --only <stages>  run ONLY the named stage(s) (comma-separated); every other stage is put out
                   of scope, even under --no-resume, on exactly the terms above - including the
                   `extract` caveat, so `--only build` still pays the extract body.

  Stage vocabulary, in pipeline order (both flags validate against it and name the valid
  spellings on a typo):
      folder scan, extract, master list, merge, enrichment, repairs, projection,
      gates:pre, build, gates:post, deliver, qa
  Both flags REUSE the existing output of a skipped stage rather than re-deriving it, so
  the work dir must already hold it - they are a re-entry shortcut on a warm work dir, not
  a way to run a stage in isolation on a cold one. And neither flag can reach the pre-build
  gates, the post-build gates, the freeze or the QA window: those ALWAYS run, so nothing
  ships unverified however narrow the cut (the guard is asserted, not documented).
  EVERY stage in the vocabulary honours both flags - all eleven, including `repairs` and
  `projection`, which for one wave were validated by the flags but had no skip guard, so
  `--only extract` still applied every repair and mutated canonical.

  --allow-invalid-corrections
                   do NOT refuse to start on an invalid entry in work/overrides.json or
                   work/repairs.json (see exit 16). The faults are still printed in full;
                   the faulty entries are then IGNORED, exactly as they were before the
                   startup check existed, so whatever they were meant to correct ships
                   UNCORRECTED. The escape hatch for a stale entry against a deadline,
                   never a fix.

  Every run writes work/timings.json ({started, total_s, stages:[{stage, seconds, resumed}]})
  from an atexit handler, so a pass that stops at ANY handoff exit still records what it
  spent, and prints one summary line naming the three most expensive stages. The handler
  writes ONLY into a work dir that already exists and never creates one: an instrument must
  not be able to author state, and it could (a deleted work dir was resurrected at exit
  holding one lone timings.json). An in-process caller that invokes main() twice gets one
  artefact per run - the log state is reset at entry and the previous run is flushed first.
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import io
import json
import re
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUIET = True  # DEFAULT (B27); --verbose opts out. Quiet = plain-English step markers
              # only, sub-output swallowed. The failure-safe default: a broker-facing
              # run that forgets a flag stays clean, and the handoff instructions the
              # orchestrator needs print regardless (see _say_orchestrator).
RESUME = False  # set by --resume: skip a stage whose output is already current (gates/freeze never skipped)

# --- THE STAGE VOCABULARY: ONE ordered list, shared by the timing log, --from/--only and the
# re-entry hints. It is deliberately a single module-level constant rather than three private
# lists, because the three features only compose if they agree on the SPELLING and the ORDER:
# a timing log naming "enrich" while --from validates "enrichment" would print a re-entry
# command the operator cannot type, which is worse than printing none. Pipeline order, so
# "strictly before the --from cut" is an index comparison and nothing else. -------------- #
STAGE_ORDER = ("folder scan", "extract", "master list", "merge", "enrichment", "repairs",
               "projection", "gates:pre", "build", "gates:post", "deliver", "qa")
# "master list" sits between extract and merge in the VOCABULARY and physically INSIDE the
# extract stage's code, between the cheap reads (tracker rows, email bodies) and the expensive
# one (a reader agent per brochure deck). That is deliberate and it is the whole point of the
# stage: the user decides scope while the decks are still unread, so the run pays for the decks
# it was asked for. The vocabulary places it after extract because --from "master list" must
# mean "re-open the scope decision and everything after it", not "re-read the trackers".

# Stages that NEVER skip, under any flag. The pre-build gates, the post-build gates, the
# freeze (which lives inside gates:pre, at ALL-PASS) and the QA window are the ONLY things
# standing between a work dir and a client, so a re-entry shortcut that could step over them
# would turn "cheapest valid re-entry" into "cheapest way to ship unverified". `_stage_skipped`
# refuses them structurally and `_assert_stage_control_safe` proves it against the live
# predicate once the flags are parsed - asserted, not trusted to the six call sites.
_NEVER_SKIP = frozenset({"gates:pre", "gates:post", "qa"})

FROM_STAGE = ""                        # set by --from: the stage this pass STARTS at
ONLY_STAGES: frozenset = frozenset()   # set by --only: the ONLY stages this pass runs

# --- PER-STAGE WALL-CLOCK TIMING. There was no timing anywhere in the spine, so every
# performance claim about it (and every "why did that take twenty minutes?") was folklore:
# the only instrument was a human watching step markers scroll. A stage log is cheap
# (one perf_counter read per boundary) and it is the instrument the cache/skip work is
# judged by - you cannot tell whether narrowing a cache key helped without it.
#
# WRITTEN FROM atexit, deliberately. This spine exits at ~16 distinct sys.exit(N) handoff
# points plus every gate block, and the interesting runs are exactly those: a pass that
# spends 90s on merge and then exits 3 for interpretation is the one whose cost the
# operator needs attributed. A write at the end of main() would record only the runs that
# never needed anything - the cheap ones. ------------------------------------------------ #
_STAGE_LOG: list[dict] = []   # [{stage, seconds, resumed:[label]}], newest last, last one open
_RUN_T0 = time.perf_counter()  # monotonic; wall clock is unsafe for a duration (NTP, DST)
_RUN_STARTED_ISO = ""          # stamped at the first _stage() call, so an import records nothing
_TIMINGS_DONE = False          # atexit runs once; a second call must not double-print
# Whether `_register_timings` has ALREADY armed a run in this process. Its only job is to stop
# the FIRST arm from re-basing `_RUN_T0` above.
#
# THE INCIDENT. `_RUN_T0` is stamped at MODULE IMPORT deliberately, and `_write_timings`' own
# docstring is built on that: the total is meant to cover the WHOLE process, and the
# unattributed remainder it names ("start-up Xs") IS the part that happens before any stage
# opens - the helper imports (fitz, Pillow, rapidfuzz), preflight and the PDF-engine probe. All
# of that necessarily precedes `_register_timings`, because the work dir is not resolved until
# after it. The in-process double-entry reset below then reassigned `_RUN_T0` on EVERY call,
# including the first, so the whole of that start-up was silently DEDUCTED from the one number
# the instrument exists to publish. Measured on a real project: 2.43s of real start-up dropped,
# a printed total of 1.3s against 3.77s actual - wrong by ~3x - and the residual was then always
# far below the 0.05s threshold that prints the start-up tail, so the line built to name the
# missing time could never fire at all. Every future optimisation would have been argued off a
# number produced by the instrument minted to end exactly that guesswork.
#
# TWO CHANGES, TWO AUTHORS, ONE VALUE, and nobody owned the second end: the import-time stamp
# and the double-entry reset are each correct alone. This flag is the join.
_TIMINGS_ARMED = False
# The work dir the currently-open log belongs to, so `_register_timings` can FLUSH a previous
# in-process run's log to ITS OWN dir before resetting for the new one. A one-element list
# rather than a str global purely so the flush path needs no extra `global` declaration.
_TIMINGS_LAST_WORK: list = []


def _stage(name: str) -> None:
    """Close the currently open stage (recording its elapsed seconds) and open `name`.

    Names come from STAGE_ORDER; an unknown name is still recorded rather than rejected,
    because a timing log that DROPS a stage is a lie about where the time went, while a
    log carrying an unexpected label is merely untidy. The eval pins the spelling instead.

    Called at the stage boundaries, before the step() marker, so the marker the operator
    reads on screen and the stage the seconds land against are the same thing."""
    global _RUN_STARTED_ISO
    now = time.perf_counter()
    if not _RUN_STARTED_ISO:
        _RUN_STARTED_ISO = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    _close_open_stage(now)
    _STAGE_LOG.append({"stage": str(name), "seconds": 0.0, "resumed": [], "_t0": now})


def _close_open_stage(now: float | None = None) -> None:
    """Stamp the open stage's elapsed seconds. Idempotent - closing a closed stage is a
    no-op, so atexit can close whatever main() left open without knowing which that was."""
    if not _STAGE_LOG:
        return
    cur = _STAGE_LOG[-1]
    t0 = cur.pop("_t0", None)
    if t0 is not None:
        cur["seconds"] = round((time.perf_counter() if now is None else now) - t0, 3)


def _timings_payload() -> dict:
    """The documented shape: {started, total_s, stages:[{stage, seconds, resumed}]}.

    Built by projecting the log onto exactly those three per-stage keys, so the private
    bookkeeping key (`_t0`) can never leak into the artefact an eval or a maintainer reads."""
    return {
        "started": _RUN_STARTED_ISO,
        "total_s": round(time.perf_counter() - _RUN_T0, 3),
        "stages": [{"stage": s["stage"], "seconds": s.get("seconds", 0.0),
                    "resumed": list(s.get("resumed") or [])} for s in _STAGE_LOG],
    }


def _write_timings(work: Path) -> None:
    """atexit handler: close the open stage, write work/timings.json, print ONE summary line.

    PRINTS IN QUIET MODE (the default). Every other technical line in this spine is gated on
    --verbose because a broker must not read jargon, but attributing time is not jargon - it is
    the single thing an operator staring at a slow run needs, and SKILL.md tells the orchestrator
    to run quiet, so `if not QUIET` would hide it exactly when it matters (the same reasoning
    the reader-failure and durable-corrections lines are printed unconditionally).

    WRITES ONLY INTO A DIRECTORY THAT ALREADY EXISTS, and NEVER creates one. An instrument
    must not be able to author state, and this one could: `_common.atomic_write_text` does
    `parent.mkdir(parents=True, exist_ok=True)`, so an unwritable/misspelt --work path had its
    whole tree CONJURED during interpreter shutdown, and - worse - a run that deliberately
    removed its own work dir (a --no-resume clean-out, a teardown, an eval's temp dir) had it
    RESURRECTED at exit holding one lone timings.json. A stray directory that appears after the
    process has already reported its exit code is unattributable: nothing on screen names it,
    and the next pass reads the leftover as a warm work dir. So the directory's existence is a
    PRECONDITION here, not something to satisfy. The summary line still prints either way -
    naming honestly that nothing was recorded - because attributing the time is the point and
    it does not depend on a file landing.

    Best-effort throughout: this runs during interpreter shutdown, after an exit code has
    already been chosen, so a failure here must never change what the run reported."""
    global _TIMINGS_DONE
    if _TIMINGS_DONE:
        return
    _TIMINGS_DONE = True
    try:
        _close_open_stage()
        payload = _timings_payload()
        path = Path(work) / "timings.json"
        # The one guard. `is_dir()` (not `exists()`): a FILE at the work path is equally not
        # somewhere to write an artefact, and both fall through to the honest "not recorded".
        _dir_ok = False
        try:
            _dir_ok = path.parent.is_dir()
        except OSError:
            _dir_ok = False
        if _dir_ok:
            try:
                import _common as _C
                _C.atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=1))
            except Exception:
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            where = f"  ({path})"
        else:
            where = f"  (not recorded - {path.parent} does not exist; nothing was created)"
        top = sorted(payload["stages"], key=lambda s: -float(s.get("seconds") or 0.0))[:3]
        detail = ", ".join(f"{s['stage']} {float(s['seconds']):.1f}s" for s in top) or "no stages ran"
        # NAME THE UNATTRIBUTED REMAINDER. total_s covers the whole process, the stages cover
        # only what ran between the boundaries, and the gap is real: the helper imports (fitz,
        # Pillow, rapidfuzz - pulled in once, deliberately), preflight and the PDF-engine probe
        # all happen before the first stage opens. A summary reading "3.5s total, slowest stage
        # 0.1s" invites the operator to hunt for 3.4 seconds that were never missing, which is
        # exactly the folklore this instrument exists to end. Printed, not stored: the artefact's
        # shape is documented and pinned, and `total_s` minus the stage sum already carries it.
        gap = payload["total_s"] - sum(float(s.get("seconds") or 0.0) for s in payload["stages"])
        tail = f", start-up {gap:.1f}s" if gap >= 0.05 else ""
        step(f"Time: {payload['total_s']:.1f}s total - dearest: {detail}{tail}{where}")
    except Exception:
        pass


def _register_timings(work: Path) -> None:
    """Arm the atexit handler. Called ONCE PER RUN, and only after the work dir is resolved:
    before that there is nowhere to write, and an eval that merely imports run.py must leave no
    timings.json anywhere.

    RESETS THE LOG STATE AT ENTRY, so a second in-process call to the entry point measures
    ITSELF. The four globals (the stage log, the monotonic t0, the ISO start stamp and the
    one-shot flag) were module-level and never reset, so an in-process harness that called
    main() twice produced ONE merged artefact whose `stages` held both runs' boundaries and
    whose `total_s` was counted from MODULE IMPORT - i.e. an instrument that reported a number
    nobody could act on, in the one place (a test harness, a repeated-pass simulation) where
    the numbers are read programmatically. Production calls it once, so this was never wrong
    in the field; it was wrong for whoever tried to measure the field.

    Resetting alone would still LOSE the previous run's artefact (atexit only fires at
    shutdown), so the previous run is FLUSHED first, to its own work dir, before the reset.
    Every in-process run therefore gets its own honest timings.json.

    THE MONOTONIC BASELINE IS THE ONE EXCEPTION and re-bases only from the SECOND arm onwards.
    Production calls this once, and on that call `total_s` must still cover the import-time
    start-up the artefact is documented to include and the summary line is built to name - see
    `_TIMINGS_ARMED` for what re-basing it on the first call actually cost."""
    global _RUN_T0, _RUN_STARTED_ISO, _TIMINGS_DONE, _TIMINGS_ARMED
    if _STAGE_LOG and not _TIMINGS_DONE:
        # a previous in-process run left an unwritten log: close it out where it belongs
        # rather than letting this run's reset swallow it.
        _write_timings(_TIMINGS_LAST_WORK[0] if _TIMINGS_LAST_WORK else work)
    _STAGE_LOG.clear()
    # THE RE-BASE IS FOR RUN #2 ONWARDS ONLY. The first arm in a process MUST keep the
    # import-time baseline: everything this function cannot possibly be called before (the
    # helper imports, preflight, the engine probe) is exactly what `total_s` is documented to
    # cover, and re-basing here deducted all of it. A second in-process call still re-bases,
    # which is the whole reason the reset exists: run #2's total must measure run #2, not the
    # module import plus run #1.
    if _TIMINGS_ARMED:
        _RUN_T0 = time.perf_counter()
    _TIMINGS_ARMED = True
    _RUN_STARTED_ISO = ""
    _TIMINGS_DONE = False
    _TIMINGS_LAST_WORK[:] = [Path(work)]
    atexit.register(_write_timings, Path(work))


# THE THREE-FOLDER PROJECT LAYOUT (the DEFAULT convention; `--project <root>` derives all
# three). A broker opening the project folder must see exactly three numbered folders and
# know instantly which one holds the dashboard - the old shape put the deliverables three
# levels down inside a work dir holding ~40 technical files, and a non-technical user could
# not find the .html. NUMBERED so file explorers sort them in pipeline order.
#   1. Input      - what the broker supplied (brochures, trackers, photos). READ-ONLY here.
#   2. Work Files - every internal pipeline artefact. This IS "the work directory" that
#                   every helper still calls `--work`; nothing about its contents changed.
#   3. Output     - ONLY the four client-facing deliverables (dashboard .html, Gaps Report
#                   .md, Longlist .xlsx, Source Ledger .xlsx). Nothing technical.
# `--folder` / `--work` / `--out-dir` still work as explicit overrides, and a legacy
# invocation with only `--folder`/`--work` keeps delivering to `<work>/deliverables`.
INPUT_DIRNAME = "1. Input"
WORK_DIRNAME = "2. Work Files"
OUTPUT_DIRNAME = "3. Output"
LEGACY_OUTPUT_SUBDIR = "deliverables"   # where a --folder/--work run has always delivered
OUTPUT_POINTER = ".output_dir"           # written in the work dir: where the deliverables went


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
    "CAPTURE EVERY ROW THE PAGE STATES - `fields` is the canonical registry, NOT a limit. Each "
    "entry there carries the field's `type` (and a `format` where the type alone is not enough), "
    "so the SHAPE of a value is stated per field and not repeated here; these rules cover what a "
    "type cannot say, in order of how often they are broken: "
    "(1) A STATED NEGATIVE IS DATA, NEVER AN ABSENCE. 'Not charged', 'No', 'None', 'N/A' are "
    "positive commercial statements - ship them as the value. Only a blank row, or one the "
    "deck marks tbd/TBC/TBA/TBS ('to be confirmed/specified'), is unknown. A printed 'BTS' is "
    "NOT unknown - it means BUILT TO SUIT, a commercial statement (the spec follows the "
    "tenant); ship it VERBATIM as the value. A live deck used 'BTS' and 'tbc' as distinct "
    "values on the same slide, and collapsing BTS to tbd shipped 15 false 'absent in all "
    "sources' claims. Shipping the unknown sentinel for stated data tells the "
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
    "the unit, and do not ADD a unit the page does not print. Where a field's `format` and its "
    "bare `type` seem to disagree, the format wins, and write-it-as-printed wins over both for a "
    "dimensioned quantity. A pure count ('72' loading docks) is correctly bare. If a page states "
    "a magnitude whose unit you genuinely cannot read, return the number, say so in that "
    "field's prov, and the value-format gate will surface it for the broker to settle. "
    "(5) A VALUE IS ONE SCALAR, NEVER a list or a nested object, whatever the field: when the "
    "page states several items for one field (several agents, several sustainability badges), "
    "join them into ONE string yourself, e.g. semicolon-separated. A list or object on an open "
    "field fails validate-data immediately."
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
# (name, rc) for the gates of the CURRENT phase, and the snapshot of the phase write_scorecard
# most recently flushed. The scorecard already lists every blocked gate, but it is a FILE - the
# exit classification needs the names in memory, and `g1` carries only exit codes, so a run red
# on three gate classes could name at most the one its first `if` happened to test. (A5)
_GATE_RESULTS: list[tuple] = []
_GATE_RESULTS_LAST: list[tuple] = []


def qa_reviews_changed(work: Path) -> bool:
    """Have the review FILES changed since the last recorded round? (Phase-3 review B2.)

    THE INCIDENT, WHICH THIS GUARD STILL EXISTS FOR. A record guarded ONLY by
    `qa_round_number == 0` made every post-record review unrecordable: a garbled round-1
    review, re-dispatched per final_gate's own remedy, wrote reviews/round2/*.md that no
    pass ever recorded, and the run exited 0 over an unread blocking finding. The guard is
    therefore a FINGERPRINT of the review files (relpath+size+mtime): record fires on the
    first pass AND whenever the set changed. Stamped only after a successful record.

    WHAT CHANGED UNDER IT, AND WHY THE FINGERPRINT IS STILL THE RIGHT KEY. This used to
    read "`qa-round record` self-opens a new round when the last is recorded, so the driver
    must not re-run it every pass (round inflation)". `record` no longer opens a second
    round at all - a review file that changes after the round is recorded now FOLDS into
    that round as additional findings - so re-running it can no longer inflate anything and
    a round-count-only guard is no longer merely insufficient, it is the wrong question.
    The fingerprint is kept because it is the RIGHT question: it asks "is there anything new
    for `record` to read?", which is what makes a re-dispatched review recordable, and it
    keeps a no-op subprocess off every pass of a loop that runs under a time cap. Note the
    guard is deliberately one-directional: a FALSE fire costs one idempotent record, while a
    miss is the incident above."""
    root = Path(work) / "reviews"
    cur = sorted(f"{q.relative_to(root)}|{q.stat().st_size}|{q.stat().st_mtime_ns}"
                 for q in root.rglob("*.md")) if root.exists() else []
    try:
        prev = json.loads((Path(work) / "qa_reviews_fp.json")
                          .read_text(encoding="utf-8-sig"))
    except Exception:
        prev = None
    return cur != prev


def qa_reviews_stamp(work: Path) -> None:
    """Persist the current review-file fingerprint (after a successful record)."""
    root = Path(work) / "reviews"
    cur = sorted(f"{q.relative_to(root)}|{q.stat().st_size}|{q.stat().st_mtime_ns}"
                 for q in root.rglob("*.md")) if root.exists() else []
    try:
        import _common as C
        C.atomic_write_text(Path(work) / "qa_reviews_fp.json", json.dumps(cur))
    except Exception:
        pass


def apply_photo_confirm_answers(work: Path, pm: dict, resolve=None) -> int:
    """Item 3.4: apply answered photo confirmations to the parsed photo_map - 'yes'
    moves uncertain -> confident, 'no' -> unrelated - BEFORE doubts are rebuilt, so
    the photo lands THIS pass instead of after the end-of-run prompt. `resolve` maps a
    raw property_key (often a park name) to the resolved match key the QUESTION was
    keyed on - without it a raw-vs-resolved mismatch would orphan every answer."""
    import clarify as _CQ
    if not isinstance(pm, dict) or not pm.get("uncertain"):
        return 0
    answers = _CQ.ingest_answers(work)
    if not answers:
        return 0
    moved, keep = 0, []
    for e in pm.get("uncertain") or []:
        br = str((e or {}).get("brochure") or "")
        pk = str((e or {}).get("property_key") or (e or {}).get("key") or "")
        if resolve is not None:
            pk = str(resolve(pk) or pk)
        raw = answers.get(_CQ.qid("photo_confirm", f"{br}|{pk}", "photo")) \
            if br else None
        a = _CQ._norm_answer(raw) if raw is not None else ""
        if a == "yes":
            pm.setdefault("confident", []).append(e)
            moved += 1
        elif a == "no":
            pm.setdefault("unrelated", []).append(e)
            moved += 1
        else:
            keep.append(e)
    if moved:
        pm["uncertain"] = keep
    return moved


_ANSWER_UNSET = object()   # "no expect supplied" - distinct from expect=None, a real value


class AnswerRepairs:
    """THE ONE BRIDGE from an ANSWERED clarification to an ATTRIBUTED correction.

    WHAT IT GENERALISES, AND THE DEFECT THAT MADE IT WORTH GENERALISING. Three answer
    channels need the same six steps - read the broker's hand-file without destroying it,
    synthesise a property-keyed entry carrying `expect`/`set`/`why`/`verified_by`, dedupe it
    on a stable id, write it atomically, refuse LOUDLY when the file cannot be parsed - and
    only two of the three had them. The third, a FIELD-LEVEL reader doubt, asked a precise
    question, recorded the broker's answer, and then wrote it into nothing: the same value had
    to be supplied a SECOND time, by hand, through work/repairs.json. Asking a precise
    question and discarding the answer is worse than not asking, because it spends the
    scarcest thing in this pipeline, which is the broker's attention.

    WHY A REPAIR AND NOT A DIRECT WRITE. This is the design principle, not a detour, and it is
    the reason the field-level channel was left unwired rather than wired badly: AN ANSWER MUST
    NEVER MUTATE DATA SILENTLY. Written straight into the field it would be indistinguishable
    from source data - no Source Ledger row, no Gaps Report line, nothing for a reviewer to
    check. As a repair it lands BEFORE the pre-build gates, so validate-data, arithmetic,
    coverage and trace-coverage judge it exactly as they judge everything else; it writes its
    own ledger row; `expect` makes it self-cancelling if identity moves under it (repairs.py
    reports SUPERSEDED rather than landing a value on the wrong card); and `verified_by` names
    the answer as its source. Disclosed in the same breath as it is made - which is what makes
    wiring it safe, and is why the two older bridges were already this shape.

    SELECTION-ONLY IS THE CALLER'S JOB, deliberately. Each caller validates the answer against
    the options ITS OWN question offered before calling `add`; this class never inspects an
    answer and so can never introduce a value nobody was asked about. (B38)"""

    def __init__(self, work, what: str):
        self.path = Path(work) / "repairs.json"
        self.what = what              # names the answer channel in the refusal message
        self.list: list = []
        self.ok = True
        self.n = 0
        self._refused = False
        # the entries THIS channel composed this pass (never the broker's hand-written ones),
        # so `flush` can put exactly those through repairs.py's validator (D4b)
        self._added: list = []
        # every refusal sentence printed by `add`/`flush`, kept for the caller and the evals
        self.refused: list = []
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, list):
                    self.list = loaded
                else:
                    self.ok = False
            except Exception:
                self.ok = False

    def has(self, rid: str) -> bool:
        """Is this answer already recorded? The id is derived from the QUESTION id, so a
        re-run re-derives the same one and the entry is written exactly once."""
        return any(isinstance(r, dict) and r.get("id") == rid for r in self.list)

    def refuse(self) -> None:
        """The ONE refusal message, printed at most once per channel.

        work/repairs.json is the BROKER'S HAND-FILE. A malformed or non-list file must never
        be replaced - a trailing comma would silently erase their hand-written entries - so
        this refuses to write and SAYS SO, which is the Phase-2 standard: never consume an
        answer while quietly dropping the repair it was given for. The answer stays recorded
        in clarify state, so fixing the file by hand and re-running applies it."""
        if self._refused:
            return
        self._refused = True
        print(f"(orchestrator: work/repairs.json exists but is NOT a valid JSON list - the "
              f"broker's {self.what} answer(s) were NOT applied. Fix that file by hand (it is "
              f"the broker's own file; nothing may overwrite it) and re-run.)")

    def add(self, rid: str, prop: dict, field: str, value, why: str, *,
            verified_by: str = "broker (exit-13 answer)", expect=_ANSWER_UNSET,
            clear: bool = False, source_file: str = "", source_locator: str = "",
            question_id: str = "") -> bool:
        """Append ONE attributed entry. False when nothing was appended.

        A `set` ON A TWIN SOURCE MUST CARRY A NUMBER FOR THE TWIN, OR IT IS NOT WRITTEN (D4).
        On the measured run two office-area doubts offered prose options ('all three office
        lines combined'); the broker picked them, and this method wrote, literally,
        `"set": {"officeArea": "all three office lines combined", "officeAreaVal": null}`:
        a sentence in the field and a null the run's own validator refuses (`set` writes a
        value, it never clears one), so the entry did NOTHING, silently, and the bare numbers
        left behind then raised two MORE blocking questions about a problem the pipeline had
        made itself. The old comment here said a null twin was "the honest form"; that is true
        of an `unset` and false of a `set`, and the mismatch was the bug. So now: when merge's
        own derivation yields no twin for the new value and the card CURRENTLY carries one,
        the entry is refused and a sentence names the question, the property, the field and
        what to supply instead (the reader prompts promise the same contract in the same
        words: on an arithmetic field every option LEADS WITH THE FIGURE AND ITS UNIT as
        printed). When the card carries no twin either, nothing is stranded: the twin key is
        left OUT of `set` and merge's re-derivation after the stage owns it, exactly as it does
        for every other twin-source repair. Nothing here computes a figure: a total the broker
        did not read is not this bridge's to invent.

        `expect` defaults to the property's CURRENT value of `field`, which is what makes the
        entry safe across a re-match: if the value has moved under it, repairs.py reports
        SUPERSEDED instead of writing.

        `clear=True` uses the correction channel's CLEARING verb (`unset`) rather than `set`.
        That is the honest shape for the one answer that says the source states NOTHING:
        writing "tbd" over the field would be indistinguishable from a source that printed
        "tbd", and the ledger row would then claim the repair SET a value when what the broker
        did was WITHDRAW one. repairs.py makes that argument in full under `unset`, and refuses
        a schema-REQUIRED field rather than leaving canonical un-schema-valid - reported, never
        crashed.

        CITING EVIDENCE, AND WHERE IT IS HONEST TO. `source_file`/`source_locator` replace the
        ledger's own columns, and a cited PAGE becomes evidence the prov-containment gate
        checks - so a citation is a claim, not decoration. Cite the FILE when the answer picked
        a value that provably came off it (the excluded-figure bridge cites the excluded
        record's own file; a reader-doubt answer cites the file the doubt was recorded
        against). Do NOT cite a page LOCATOR for a value the answer COMPOSED rather than read:
        the value-format bridge appends a unit to a bare number, so '5000 sq. m' occurs nowhere
        in the source and citing the source page would be a false claim about the very thing
        the citation exists to prove. Absent, the row is stamped repairs.json plus this entry's
        id, which is itself honest - it came through the correction channel."""
        if not self.ok or self.has(rid) or not field:
            return False
        from project_properties import repair_key as _repair_key
        cur = prop.get(field) if expect is _ANSWER_UNSET else expect
        entry = {"id": rid,
                 "property": {"key": _repair_key(prop), "id": prop.get("id")},
                 "expect": {field: cur}}
        # A DERIVED TWIN TRAVELS WITH ITS SOURCE (F24, contract C2). `officeArea` is the source
        # merge derives `officeAreaVal` from, and repairs.py now REFUSES a `set` or `unset` of a
        # source that leaves its twin stranded. So the twin is written in the same entry, and
        # its value is merge's own derivation run on a copy of the property carrying the new
        # value (one owner of the arithmetic; nothing is re-implemented here). A source that no
        # longer yields a twin sets it to null, which repairs.py accepts as the honest form.
        twin = _derived_twin_of(field)
        entry["why"] = why
        entry["verified_by"] = verified_by
        if clear:
            entry["unset"] = [field] + ([twin] if twin else [])
        else:
            entry["set"] = {field: value}
            if twin:
                tv = _derive_twin_value(prop, field, value, twin)
                if tv is not None:
                    entry["set"][twin] = tv
                elif prop.get(twin) is not None:
                    # D4 (a): the new value yields no twin and the card HAS one. Writing the
                    # entry would either null the number (refused by repairs.py, so inert) or
                    # lose it (if the validator ever let it through). Neither is a correction.
                    self._refuse_prose_on_twin(prop, field, value, twin,
                                               question_id or rid, entry)
                    return False
                # else: no twin to strand; the key stays out of `set` (a null there is what
                # repairs.py refuses) and merge re-derives after the stage, as for any
                # twin-source repair
        if source_file:
            entry["source_file"] = str(source_file)
        if source_locator:
            entry["source_locator"] = str(source_locator)
        self.list.append(entry)
        self._added.append(entry)
        self.n += 1
        return True

    def _refuse_prose_on_twin(self, prop: dict, field: str, value, twin: str,
                              question_id: str, entry: dict) -> None:
        """The D4 refusal sentence: loud, once per entry, and it says what to paste instead.

        "Reports success while discarding the correction" is the whole class of defect this
        programme exists to remove, so the sentence names the question id, the card, the field,
        the option that failed and the number it would have cost, quotes the contract the reader
        prompts promise in the same words, and ends with a ready-to-paste work/repairs.json
        entry whose `expect` guard is already filled in and whose value is left for the printed
        figure. The skeleton copies THIS entry (same id, same attribution), so pasting it lands
        the answer under the answer's own provenance rather than as an anonymous hand repair."""
        skel = {"id": entry["id"], "property": entry["property"], "expect": entry["expect"],
                "set": {field: (f"<the printed figure WITH its unit, e.g. '24,230 sq ft "
                                f"(all three office lines combined)'; leave {twin} out, merge "
                                f"derives it>")},
                "why": entry.get("why"), "verified_by": entry.get("verified_by")}
        msg = (f"(orchestrator: the {self.what} answer to {question_id} was NOT applied to "
               f"property {prop.get('id')} '{_prop_label(prop)}' {field}: the chosen option "
               f"{str(value)!r} carries no figure, so {twin} (currently {prop.get(twin)!r}) "
               f"cannot be derived from it and writing the option would have cost the card its "
               f"number. On an arithmetic field every option LEADS WITH THE FIGURE AND ITS UNIT "
               f"as printed: '24,230 sq ft (all three office lines combined)' lands, 'all three "
               f"office lines combined' does not. Nothing was written. To apply what the broker "
               f"meant, paste this into work/repairs.json with the printed figure filled in: "
               f"{json.dumps(skel, ensure_ascii=False)})")
        self.refused.append(msg)
        print(msg)

    def _self_check(self) -> None:
        """D4 (b): before anything is written, every entry THIS channel composed is judged by
        the SAME validator the repairs stage applies to work/repairs.json
        (`repairs.validate_entry`, split out of `load` for exactly this call). An entry that
        would be refused there is refused HERE, removed, and reported with the validator's own
        reason plus the entry, so the operator sees the words the stage would have printed at
        the moment the answer is consumed rather than a pass later. Read-only on repairs.py;
        nothing is re-implemented, which is what keeps the two judgements identical. Inert on
        an older repairs.py without the split (the stage itself still reports INVALID REPAIR
        then, so nothing is silent)."""
        try:
            import repairs as _R
            validate = getattr(_R, "validate_entry", None)
        except Exception:
            validate = None
        if validate is None:
            return
        for e in list(self._added):
            try:
                reasons = list(validate(e) or [])
            except Exception as exc:                # a validator crash is a refusal, not a pass
                reasons = [f"the validator raised {type(exc).__name__}: {exc}"]
            if not reasons:
                continue
            self.list = [r for r in self.list if r is not e]
            self._added.remove(e)
            self.n -= 1
            msg = (f"(orchestrator: a {self.what} answer composed a work/repairs.json entry the "
                   f"repairs stage's own validator would refuse, so it was NOT written: "
                   f"{'; '.join(reasons)}. The answer stays recorded in work/clarify_state.json; "
                   f"to apply it, correct and paste this entry into work/repairs.json: "
                   f"{json.dumps(e, ensure_ascii=False)})")
            self.refused.append(msg)
            print(msg)

    def flush(self) -> int:
        """Write the file, ONCE, atomically. Returns how many entries were added.

        Runs `_self_check` first (D4b): an entry the repairs stage would print `[INVALID
        REPAIR] ... this entry does NOTHING` for is refused before it reaches the broker's
        hand-file, and the count returned is of entries that will actually apply."""
        if not self.n:
            return 0
        if not self.ok:
            self.refuse()
            return 0
        self._self_check()
        if not self.n:
            return 0
        import _common as C
        C.atomic_write_text(self.path,
                            json.dumps(self.list, ensure_ascii=False, indent=2))
        return self.n


def _prop_label(prop: dict) -> str:
    """'park / unit' for a refusal sentence; the unit only when it is a real designator."""
    import normalize as _N                    # local, as everywhere else in this module
    park = str((prop or {}).get("park") or "").strip()
    unit = str((prop or {}).get("unit") or "").strip()
    # v45: the unknown FAMILY, not one spelling - the render sentinel is normalize.BLANK now
    # and a canonical produced before v45 still carries 'tbd'.
    if unit and not _N.looks_unknown(unit):
        return f"{park} / {unit}" if park else unit
    return park or f"id {(prop or {}).get('id')}"


def _derived_twin_of(field: str):
    """The derived field merge computes FROM `field` (merge.DERIVED_TWINS), or None. Inert on an
    older merge.py without the registry, exactly as repairs.py's own guard is."""
    try:
        import merge as _merge
        reg = getattr(_merge, "DERIVED_TWINS", None)
        return reg.get(field) if isinstance(reg, dict) else None
    except Exception:
        return None


def _derive_twin_value(prop: dict, field: str, value, twin: str):
    """The twin's value once `field` holds `value`, by merge's own re-derivation on a COPY of the
    property (contract C2's `rederive_after_repairs`, given the changed-field hint so the twin is
    recomputed unconditionally). None when the new value yields no twin, or when merge cannot
    derive it: null is what repairs.py asks for in that case, and it is honest."""
    try:
        import copy as _copy
        import merge as _merge
        fn = getattr(_merge, "rederive_after_repairs", None)
        if fn is None:
            return None
        p = _copy.deepcopy(prop)
        p[field] = value
        fn([p], changed={str(p.get("id")): {field}})
        return p.get(twin)
    except Exception:
        return None


def _answer_as_field_type(current, text):
    """(ok, value): the broker's chosen option, typed as the FIELD is typed.

    A repair lands BEFORE validate-data, so a string written into a numeric field would
    hard-block the build - the answer has to arrive in the field's own type or not at all.
    Numbers are read with `normalize.normalize_number`, the one reader the whole pipeline
    uses, so '12,500' and '12 500' behave here exactly as they behave everywhere else, and an
    option that does NOT reduce to a number against a numeric field returns ok=False: the
    answer is then DISCLOSED rather than landed, which is the fail-closed direction. Never
    converts a unit and never parses a range - that is the 10.76x class, and an answer is a
    selection, not a calculation. (B38)"""
    s = str(text).strip()
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return True, s
    import normalize as _N
    if _N.is_range(s):
        return False, None
    v = _N.normalize_number(s)
    if v is None:
        return False, None
    return True, (int(v) if float(v).is_integer() else v)


# Unit words a free-text NUMERIC answer may carry after its one number and still land: the
# broker writing '4,500 sqm' has answered 4500, not composed a value. Anything else after the
# number ('thousand', '(the office)', 'or 4500') is refused: a hedge or an alternative is not
# a clean coercion, and this bridge lands values, it does not interpret them.
_FREE_TEXT_UNITS = re.compile(
    r"^(sq\.?\s*m\.?|sqm|m2|m\u00b2|sq\.?\s*ft\.?|sqft|ft2|ft\u00b2|ha|acres?|%|m|units?|"
    r"spaces?|doors?|bays?|floors?|storeys?|years?|months?|weeks?)$", re.I)
_FREE_TEXT_MAX_CHARS = 80


def _free_text_value(current, raw):
    """(ok, value): a FREE-TEXT answer to a field-level doubt, typed as the field is typed, or
    ok=False when it does not coerce CLEANLY and must be disclosed rather than landed.

    F18 relaxed the lander from selection-only. The old guard (the answer must equal one of
    the reader's `options`) was built for provenance, but the provenance already sits in the
    repair's own `verified_by`, which names the broker and the question id; what the guard
    actually did on the measured run was ignore six of six real answers. 'Cleanly' is the
    whole of the new rule, and it is stricter than `_answer_as_field_type` alone because
    `normalize_number` is deliberately lenient ('about 40 thousand' reads 40, '450 or 4500'
    reads 450): against a NUMERIC field the answer must be ONE number, optionally followed by
    a unit word from `_FREE_TEXT_UNITS`, and nothing else - no hedge, no alternative, no
    range. Against a STRING field the answer lands verbatim when it is short and is not a
    question back at us. A bool field never takes free text (the options ARE the values)."""
    s = str(raw or "").strip()
    if not s or "?" in s or isinstance(current, bool):
        return False, None
    if isinstance(current, (int, float)):
        import normalize as _N
        if _N.is_range(s):
            return False, None
        m = re.fullmatch(r"([0-9](?:[0-9,.]|\s(?=[0-9]))*)\s*(.*)", s)
        if not m or (m.group(2) and not _FREE_TEXT_UNITS.match(m.group(2).strip())):
            return False, None
        return _answer_as_field_type(current, m.group(1))
    if len(s) > _FREE_TEXT_MAX_CHARS:
        return False, None
    return True, s


def _doubt_anchor_cards(stamp: dict, by_park: dict) -> list:
    """[(anchor index, shipped card)] for a landable doubt, ONE per resolvable anchor.

    THE ANCHOR IS THE RECORD'S IDENTITY, NEVER THE SUBJECT (F18). `subject` is the reader's
    free-text TOPIC ('office area', 'which region'); anchoring the card on it matched 8 of 8
    landable questions to no park on the measured run. clarify now stamps `anchors`, one
    {park, unit} per record the question stands for (several after F15 coalescing), with the
    scalar `anchor_park`/`anchor_unit` equal to the first. Resolution, per anchor:
      * `norm(park)` against the shipped park names; several cards on one park are
        disambiguated on `unit`. An anchor whose park is '' named no park and is SKIPPED,
        never looked up: '' is not a key.
      * zero or several survivors -> that anchor lands nothing (a correction on the wrong
        card is worse than one that did not land); the other anchors still land.
    A stamp with neither `anchors` nor the scalar pair predates F18: it degrades to the old
    subject match with index None, so a stale work dir keeps working rather than crashing."""
    import match as _M
    anchors = stamp.get("anchors")
    if not (isinstance(anchors, list) and anchors):
        if stamp.get("anchor_park") or stamp.get("anchor_unit"):
            anchors = [{"park": stamp.get("anchor_park"), "unit": stamp.get("anchor_unit")}]
        else:
            cands = by_park.get(_M.norm(stamp.get("subject"))) or []
            return [(None, cands[0])] if len(cands) == 1 else []
    out: list = []
    seen: set = set()
    for i, a in enumerate(anchors):
        park = _M.norm((a or {}).get("park")) if isinstance(a, dict) else ""
        if not park:
            continue
        cands = by_park.get(park) or []
        unit = _M.norm(a.get("unit"))
        if len(cands) > 1 and unit:
            cands = [p for p in cands if _M.norm(p.get("unit")) == unit]
        if len(cands) != 1 or id(cands[0]) in seen:
            continue
        seen.add(id(cands[0]))
        out.append((i, cands[0]))
    return out


def _recorded_only_doubt_answers(work: Path) -> list:
    """Question ids of ANSWERED reader doubts whose own `answer_handling` said the answer would
    be recorded, not applied (the reader named no canonical field, or no candidate values), and
    which clarify therefore never stamped landable. Read off the state, so the spine reports
    exactly what the broker was told at asking time (F18): a card is never announced as
    changing when the question itself said it would not."""
    try:
        import clarify as _CQ
        st = _CQ.load_state(work)
        titles = st.get("titles") or {}
        land = st.get("landable") or {}
        out = []
        for qid, raw in (st.get("answers") or {}).items():
            ah = str((titles.get(qid) or {}).get("answer_handling") or "")
            if ah.startswith("recorded only") and qid not in land and not _CQ.is_decline(raw):
                out.append(str(qid))
        return sorted(out)
    except Exception:
        return []


def _recorded_only_guidance(work: Path, ids: list) -> list:
    """D13: one sentence per record for each ANSWERED reader doubt the run will not land, quoting
    the broker's answer and ending with the paste-ready work/repairs.json entry clarify stored
    beside the question at asking time (`titles[qid].to_apply_by_hand`, built by
    `clarify.agent_doubt_questions` while the raising record was in scope: the record, the
    field, the `expect` guard, the lander's own id and attribution).

    THE ANSWER IS QUOTED IN THE SENTENCE AND NEVER WRITTEN INTO THE ENTRY. Landing a value is
    the lander's job under the lander's guards (selection, type, anchor, expect), and these are
    precisely the questions the lander could not land; copying the answer into `set` here would
    be the lander with the guards removed. The operator types it, as the field is typed, and
    repairs.py judges the result exactly as it judges any hand-written entry. A question asked
    before this run recorded plans (an older work dir) gets a sentence naming the records the
    question covered and what an entry needs, never silence."""
    out: list = []
    try:
        import clarify as _CQ
        st = _CQ.load_state(work)
        titles = st.get("titles") or {}
        answers = st.get("answers") or {}
    except Exception:
        return out
    for qid in ids or []:
        t = titles.get(qid) or {}
        raw = str(answers.get(qid) or "").strip()
        plan = t.get("to_apply_by_hand")
        if not isinstance(plan, dict) or not plan.get("entries"):
            out.append(f"(orchestrator: the broker answered {qid} with {raw!r}; that question was "
                       f"asked before this run recorded a repair plan for it, so to apply the "
                       f"answer write a work/repairs.json entry by hand for "
                       f"{', '.join(t.get('affected') or []) or 'the record(s) the question names'}"
                       f", with `expect` set to the card's current value of the field, a `why`, "
                       f"and `verified_by` naming the broker and {qid}.)")
            continue
        for s in plan.get("entries") or []:
            e = (s or {}).get("entry") or {}
            fld = next(iter(e.get("set") or {}), "<field>")
            out.append(f"(orchestrator: the broker answered {qid} with {raw!r}, which was RECORDED "
                       f"but NOT applied to '{(s or {}).get('record')}' {fld} because "
                       f"{plan.get('reason')}. To apply it, write that answer as a value of the "
                       f"field's own type into `set` of this entry and paste it into "
                       f"work/repairs.json: {json.dumps(e, ensure_ascii=False)})")
    return out


def agent_doubt_repairs(work: Path, cfg: dict, canonical_path: Path) -> int:
    """Item 3.2, second half: an ANSWERED field-level reader doubt LANDS IN THE FIELD.

    THE DEFECT. `clarify.agent_doubt_questions` turns a reading agent's recorded doubt into a
    precise, field-level broker question, `clarify.ingest_answers` records the answer durably,
    and then nothing consumed it. The broker had answered "it is 12,500, the 125,000 is the
    park total" and the card still showed the park total until somebody hand-wrote the same
    value into work/repairs.json. One question, answered, and the answer applied twice by hand
    or not at all.

    HOW IT LANDS, AND WHY EVERY GUARD HERE FAILS CLOSED. The answer becomes ONE attributed
    entry through `AnswerRepairs` (see that class for why a repair rather than a write). Four
    things must all be true, and any one of them missing means the answer is DISCLOSED exactly
    as it is today - never guessed at:
      * THE QUESTION MUST HAVE BEEN ASKED and must name a field. Read from clarify's own
        `landable` stamp, written by `emit`, so an answer to a question this work dir never put
        to anybody writes nothing - the same guard `ingest_answers` applies to answer ids.
      * THE ANSWER MUST BE A SELECTION, OR FREE TEXT THAT COERCES CLEANLY. It matches one of
        the strings the reader itself offered, or it is a NOT_STATED withdrawal, or (F18) it
        is free text `_free_text_value` accepts into the field's own type. Selection-only was
        the B38 provenance argument; the provenance lives in the repair's `verified_by`, which
        names the broker and the question id, and the measured cost of the stricter guard was
        six real answers out of six ignored. What stays refused is anything the lander would
        have to INTERPRET: a hedge, an alternative, a range, a question back.
      * EVERY ANCHOR MUST RESOLVE TO EXACTLY ONE CARD. The doubt was raised against a
        PRE-MERGE record and is applied against the MERGED dataset, where `__meta` is gone by
        construction - so the anchor is the record's own park (and unit) that clarify stamps
        in `anchors`, resolved by `_doubt_anchor_cards`; NEVER the doubt's free-text subject,
        which matched nothing on the measured run. A coalesced question (F15) lands the one
        answer on each of its anchors as its own repair. An anchor resolving to zero or several
        cards lands nothing: a correction on the wrong card is worse than a correction that
        did not land, which is repairs.py's own doctrine.
      * THE FIELD MUST ALREADY CARRY A VALUE. A doubt is by definition about something the
        reader DID read and was torn over, so on the merged property it is populated. If it is
        not, the record the doubt came from did not survive into that field, and writing a
        FIRST value there would be inventing rather than correcting.

    Returns how many repairs were recorded. Called where the excluded-figure bridge is called,
    i.e. after merge and BEFORE the repairs stage, so the answer reaches the card on THIS pass
    rather than costing another round-trip."""
    import clarify as _CQ
    import _common as C
    land = _CQ.landable(work)
    if not land:
        return 0
    answers = _CQ.ingest_answers(work)
    if not answers:
        return 0
    declined = _CQ.declined_ids(work)
    try:
        data = C.load_canonical(Path(canonical_path))
    except Exception:
        return 0
    props = [p for p in (data.get("properties") or []) if isinstance(p, dict)]
    if not props:
        return 0
    import match as _M
    by_park: dict = {}
    for p in props:
        by_park.setdefault(_M.norm(p.get("park")), []).append(p)
    chan = AnswerRepairs(work, "reader-doubt")
    for q_id, stamp in sorted(land.items()):
        if str((stamp or {}).get("kind") or "") != "agent_doubt":
            continue
        field = str(stamp.get("field") or "")
        raw = answers.get(q_id)
        if not field or q_id in declined or raw is None or not str(raw).strip():
            continue
        if _CQ.is_decline(raw):
            continue          # a recorded DECISION to keep the source's own value
        cards = _doubt_anchor_cards(stamp, by_park)
        if not cards:
            continue
        a_norm = _CQ._norm_answer(raw)
        clear = _CQ.is_not_stated(raw)
        picked = {_CQ._norm_answer(o): o
                  for o in (stamp.get("options") or [])}.get(a_norm)
        for i, prop in cards:
            cur = prop.get(field)
            if cur is None:
                continue
            # one repair PER ANCHOR, so the id must vary per anchor; the legacy subject
            # fallback keeps the un-suffixed id it always had (i is None there)
            rid = "ad-" + str(q_id)[:10] + ("" if i is None else "-" + str(i))
            value = None
            shown = picked
            if not clear:
                if picked is not None:
                    _ok, value = _answer_as_field_type(cur, picked)
                else:
                    # free text: lands only when it coerces CLEANLY (see _free_text_value)
                    _ok, value = _free_text_value(cur, raw)
                    shown = str(raw).strip()
                if not _ok:
                    # D13: refused, disclosed, and never SILENTLY. This used to be a bare
                    # `continue`: the answer was consumed and nothing said where it went. The
                    # sentence names the card and field and hands over the entry to paste, with
                    # the value left for the operator (the lander does not interpret answers).
                    from project_properties import repair_key as _rk
                    _skel = {"id": rid,
                             "property": {"key": _rk(prop), "id": prop.get("id")},
                             "expect": {field: cur},
                             "set": {field: (f"<the broker's answer {str(raw).strip()!r} written "
                                             f"as the field is typed ({type(cur).__name__}): one "
                                             f"clean value, no hedge, no range>")},
                             "why": f"broker answered the exit-13 reader-doubt question on {field}",
                             "verified_by": f"broker (exit-13 answer to {q_id})"}
                    print(f"(orchestrator: the reader-doubt answer to {q_id} ({str(raw).strip()!r}) "
                          f"was NOT applied to property {prop.get('id')} '{_prop_label(prop)}' "
                          f"{field}: it does not reduce cleanly to the field's own type "
                          f"({type(cur).__name__}), and the lander never interprets an answer. "
                          f"To apply it, paste this into work/repairs.json with the value written "
                          f"as the field is typed: {json.dumps(_skel, ensure_ascii=False)})")
                    continue
            if not chan.ok:
                chan.refuse()
                break
            chan.add(rid, prop, field, value,
                     ("broker answered the exit-13 reader-doubt question on "
                      + field + ": " + ("the source states no value for it" if clear
                                        else f"the value is '{shown}'")),
                     verified_by=f"broker (exit-13 answer to {q_id})",
                     clear=clear, source_file=str(stamp.get("source_file") or ""),
                     question_id=str(q_id))
    return chan.flush()


def excluded_figure_questions(work: Path, cfg: dict, canonical_path: Path) -> list:
    """Item 3.5: an excluded record whose figure conflicts with the shipped card it
    plausibly IS becomes a NON-BLOCKING broker question ('the card shows X, the
    excluded record states Y - which should it show?'). An answer picking the excluded
    figure is applied as an ATTRIBUTED repairs.json entry (applied by the repairs stage
    this same pass); unanswered ships the disclosed conflict exactly as before.
    Same-unit only - offering a cross-unit repair would be the 10.76x class."""
    import clarify as _CQ
    import _common as C
    if _CQ.clarify_mode(work, cfg) != "interactive":
        return []
    try:
        data = C.load_canonical(Path(canonical_path))
    except Exception:
        return []
    excluded = (data.get("meta", {}) or {}).get("excluded") or []
    if not excluded:
        return []
    by_id = {p.get("id"): p for p in data.get("properties") or []}
    answers = _CQ.ingest_answers(work)
    declined = _CQ.declined_ids(work)
    # ONE attributed-repair channel, shared with value_format_clarify and
    # agent_doubt_repairs - the read-guard, the entry shape, the dedupe, the atomic write and
    # the loud refusal all live in AnswerRepairs now, so the three answer bridges cannot
    # drift apart (they already had: one wrote its refusal before consuming the answer, one
    # after, and the third had none of it because it applied nothing at all).
    chan = AnswerRepairs(work, "excluded-figure")
    pending = []
    for e in excluded:
        ls = (e or {}).get("likely_same_as") or {}
        hl = (e or {}).get("headline") or {}
        ki = ls.get("kept_index")
        prop = by_id.get(ki + 1) if isinstance(ki, int) else None
        exc_v, exc_u = hl.get("warehouseArea"), hl.get("areaUnit")
        if not prop or not isinstance(exc_v, (int, float)):
            continue
        card_v, card_u = prop.get("warehouseArea"), prop.get("areaUnit")
        if not isinstance(card_v, (int, float)) or card_v == exc_v:
            continue
        if exc_u and card_u and exc_u != card_u:
            continue  # cross-unit: disclosure only, never a repair offer
        q_id = _CQ.qid("excluded_figure", f"{e.get('name')}|{prop.get('id')}",
                       "warehouseArea")
        opt_keep = f"keep {card_v:,.0f} (the shipped card's source)"
        opt_use = f"use {exc_v:,.0f} (the excluded record's figure)"
        raw = answers.get(q_id)
        a = _CQ._norm_answer(raw) if raw is not None else ""
        if a == _CQ._norm_answer(opt_use) or a.startswith("use"):
            if not chan.ok:
                # the broker's HAND-FILE is unreadable: refuse LOUDLY (the Phase-2
                # standard) - never consume the answer while silently dropping the repair
                chan.refuse()
                continue
            # CITE THE EXCLUDED RECORD'S OWN FILE, and only when exactly one names it. The
            # figure being written provably came off that file (it IS the excluded record's
            # headline), so the ledger can say where it came from instead of stamping
            # `repairs.json` and leaving a reviewer's next question unanswered. No page
            # locator: the exclusion carries file names, not pages, and a locator we cannot
            # substantiate is worse than none.
            _src = [str(s) for s in ((e or {}).get("source_files") or []) if str(s).strip()]
            chan.add("xf-" + str(q_id)[:10], prop, "warehouseArea", exc_v,
                     (f"broker answered the exit-13 excluded-figure question: "
                      f"the excluded record '{e.get('name')}' states the right figure"),
                     expect=card_v,
                     source_file=(_src[0] if len(_src) == 1 else ""))
            continue
        if a == _CQ._norm_answer(opt_keep) or a.startswith("keep") or q_id in declined:
            continue  # settled: the card keeps its own source's figure
        # an unrecognised answer RE-ASKS with the rejection spelled out - it must never
        # silently read as 'keep' (junk never counts)
        rejected = (f" (Your previous answer '{raw}' matched neither option - answer "
                    f"'keep ...' or 'use ...' exactly, or 'skip'.)") if a else ""
        pending.append({
            "id": q_id, "kind": "excluded_figure", "asked_of": "broker",
            "blocking": False,
            "subject": str(prop.get("park") or prop.get("id")),
            "question": (f"'{e.get('name')}' was excluded by your longlist decision "
                         f"but looks like shipped option '{prop.get('park')}' - the "
                         f"card shows {card_v:,.0f} {card_u or ''} while the excluded "
                         f"record states {exc_v:,.0f} {exc_u or ''}. Which figure "
                         f"should the card show?{rejected}").replace("  ", " "),
            "options": [opt_keep, opt_use],
            "why_it_matters": ("the losing figure stays disclosed in the Gaps Report "
                               "either way"),
            "if_unanswered": ("the card keeps its own source's figure; the conflict "
                              "stays disclosed"),
        })
    chan.flush()
    return pending


def value_format_clarify(work: Path, canonical: Path) -> tuple:
    """Bridge the value-format gate's findings to the broker via clarify (B59 -> exit 13).

    Returns (repairs_written, waivers_written, pending_questions). An ANSWERED unit
    becomes an attributed work/repairs.json entry (property-keyed, applied before the
    gates on the next pass); a DECLINE ('leave as is' / skip / SKIP_ALL) becomes a
    waiver the gate ships-bare-but-notes; anything undecided is emitted as a BLOCKING
    exit-13 question. Idempotent per pass: repairs are keyed vf-<qid>, waivers are a
    set, and clarify's own state machinery owns ask-once/decline semantics."""
    import clarify as _CQ
    import _common as C
    try:
        findings = json.loads((Path(work) / "value_format_findings.json")
                              .read_text(encoding="utf-8-sig"))
    except Exception:
        return 0, 0, []
    qs = _CQ.value_format_questions(findings)
    if not qs:
        return 0, 0, []
    answers = _CQ.ingest_answers(work)
    declined = _CQ.declined_ids(work)
    data = C.load_canonical(Path(canonical))
    by_id = {str(p.get("id")): p for p in data.get("properties") or []}
    wv_path = Path(work) / "value_format_waivers.json"
    # repairs.json is the BROKER'S HAND-FILE, and AnswerRepairs owns that discipline for all
    # three answer bridges: a malformed or non-list file is never replaced (a trailing comma
    # would silently erase their hand-written entries), the refusal is loud, and the answer
    # stays recorded in clarify state so a hand-fix plus a re-run applies it.
    chan = AnswerRepairs(work, "value-format")
    try:
        wv_list = json.loads(wv_path.read_text(encoding="utf-8-sig")) or []
        if not isinstance(wv_list, list):
            wv_list = []
    except Exception:
        wv_list = []
    wv_keys = {(str(w.get("field")), str(w.get("id"))) for w in wv_list
               if isinstance(w, dict)}
    n_wv = 0
    pend_extra = []
    for q in qs:
        fld, pid = str(q.get("field")), str(q.get("property_id"))
        a = answers.get(q["id"])
        a_norm = _CQ._norm_answer(a) if a is not None else ""
        if q["id"] in declined or (a is not None and
                                   (_CQ.is_decline(a)
                                    or a_norm in ("leave as is", "leave it as is"))):
            if (fld, pid) not in wv_keys:
                wv_list.append({"field": fld, "id": q.get("property_id"),
                                "expect_value": q.get("bare_value"),
                                "why": "broker declined (exit-13 value-format question)"})
                wv_keys.add((fld, pid))
                n_wv += 1
            continue
        if a is None or not str(a).strip():
            continue
        # VALIDATE the answer before it touches a client-facing value: one of the
        # question's options (normalised), or something unit-shaped (letter-led,
        # digit-free, short). Anything else is re-asked, never concatenated.
        _opts = {_CQ._norm_answer(o): o for o in (q.get("options") or [])
                 if _CQ._norm_answer(o) not in ("leave as is",)}
        unit = _opts.get(a_norm)
        if unit is None and re.fullmatch(r"[a-z£€$][a-z.,/ %²]{0,11}", a_norm or ""):
            unit = str(a).strip()
        if unit is None:
            qx = dict(q)
            qx["question"] = (str(q.get("question") or "") +
                              f" (Your previous answer '{a}' is neither one of the options "
                              f"nor a plain unit - answer with one of the options, a unit "
                              f"like 'sq. m', or 'leave as is'.)")
            pend_extra.append(qx)
            continue
        prop = by_id.get(pid) or {}
        cur = prop.get(fld)
        # DELIBERATELY UNCITED. The value written here is COMPOSED - the bare number plus the
        # unit the broker named - so '5000 sq. m' occurs nowhere in the source, and citing the
        # source page would be a false claim about exactly the thing a citation exists to
        # prove (see AnswerRepairs.add). The ledger stamps repairs.json + this entry's id,
        # which says truthfully that it arrived through the correction channel.
        chan.add("vf-" + str(q["id"])[:10], prop, fld, f"{cur} {unit}".strip(),
                 (f"broker answered the exit-13 value-format question: "
                  f"'{cur}' is in {unit}"))
    n_rep = chan.flush()
    if n_wv:
        C.atomic_write_text(wv_path, json.dumps(wv_list, ensure_ascii=False, indent=2))
    pend = _CQ.pending(work, qs) + pend_extra
    if pend:
        _CQ.emit(work, pend)
    return n_rep, n_wv, pend


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
    _GATE_RESULTS.append((name, rc))  # (A5) the names the exit classification needs
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
    # SNAPSHOT before clearing, so the exit classification that follows this flush can still
    # name every gate of the phase just written. Clearing without a snapshot is what forced the
    # old exits to guess from exit codes alone. (A5)
    global _GATE_RESULTS_LAST
    _GATE_RESULTS_LAST = list(_GATE_RESULTS)
    _GATE_RESULTS.clear()
    if not QUIET:
        print(f"\n  scorecard -> {path}  (STATUS: {overall})")


def blocked_gate_names() -> list:
    """Every gate of the phase write_scorecard last flushed that BLOCKED, in run order. (A5)"""
    return [str(n) for n, rc in _GATE_RESULTS_LAST if rc != 0]


def load_yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    import yaml
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
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


def _stage_skipped(stage: str) -> bool:
    """Is `stage` OUT OF SCOPE for this pass because of --from / --only? (A2)

    Independent of --resume, and deliberately so: --from/--only are not a faster resume, they
    are the operator saying "this correction cannot reach those stages, do not re-derive them".
    A `--no-resume --from repairs` pass must still honour the cut, or the flag would silently
    do nothing on exactly the run (a forced recompute of the stages that CAN change) where it
    is worth most.

    HARD GUARD, first and structural: the never-skip stages return False before either flag is
    consulted, so no combination of --from/--only can express "skip the gates". This is a
    property of the predicate rather than a rule the six call sites are trusted to remember -
    the call sites are where the last four resume defects in this file lived.

    A stage NOT in STAGE_ORDER (a caller passing "" or a future name) is never skipped: an
    unrecognised stage name must not silently disappear from the pass."""
    if not stage or stage in _NEVER_SKIP or stage not in STAGE_ORDER:
        return False
    if FROM_STAGE in STAGE_ORDER and STAGE_ORDER.index(stage) < STAGE_ORDER.index(FROM_STAGE):
        return True
    return bool(ONLY_STAGES) and stage not in ONLY_STAGES


def _assert_stage_control_safe() -> None:
    """PROVE the hard guard against the live predicate, once, after the flags are parsed.

    Asserting the invariant over the real function (rather than documenting it, or trusting
    `_stage_skipped`'s early return to stay first as the function is edited) is what makes it
    a guard instead of a comment: any future refactor that lets a flag reach the gates, the
    freeze or the QA window fails here, at startup, on every run - not in a client's dashboard."""
    leaks = sorted(s for s in _NEVER_SKIP if _stage_skipped(s))
    assert not leaks, ("stage control must NEVER be able to skip " + ", ".join(leaks)
                       + f" (--from {FROM_STAGE!r}, --only {sorted(ONLY_STAGES)!r})")


def _reentry(channel: str) -> str:
    """ONE line: the CHEAPEST VALID re-entry command for a correction on `channel`. (A26)

    The operator should not have to know which stages a given correction invalidates - that
    is a property of WHERE in the pipeline the channel is applied, which is knowable here and
    nowhere else. Two channels, and the whole difference is stage ordering:

      "repair"   - work/repairs.json is applied by the REPAIRS stage, i.e. AFTER merge and
                   after enrichment, so neither of them can be changed by it. `--from repairs`
                   is therefore valid and skips both - the expensive half of a pass.
      "premerge" - an override, a clarification answer, or a match/field adjudication is
                   consumed BY or BEFORE merge, so a full pass is genuinely required. It is no
                   longer the old full cost: the enrichment stamp now hashes only the fields
                   enrichment consumes, so a correction that moved no spatial field re-merges
                   and then skips enrichment by itself.

    Derived from THIS process's own argv so the line is copy-pasteable rather than a template
    to fill in, with any --from/--only from the current invocation stripped first: a hint that
    compounded a previous cut would name a command that skips MORE than the channel allows,
    which is the one way a re-entry hint can do harm rather than nothing."""
    argv, skip_next = [], False
    for a in list(sys.argv[1:]):
        if skip_next:
            skip_next = False
            continue
        if a in ("--from", "--only"):
            skip_next = True
            continue
        if a.startswith("--from=") or a.startswith("--only="):
            continue
        argv.append(a)
    def _q(s: str) -> str:
        s = str(s)
        return f'"{s}"' if (" " in s and not s.startswith('"')) else s
    exe = _q(sys.argv[0] or "run.py") if sys.argv else "run.py"
    base = " ".join(["python", exe, *[_q(a) for a in argv]])
    if channel == "either":
        # EXITS 5, 6 AND 15 ARE RESOLVABLE THROUGH MORE THAN ONE CHANNEL, so this says so
        # rather than guessing one. Guessing is the way a re-entry hint can do HARM rather
        # than nothing: `--from repairs` puts the folder scan, extract, merge and enrichment
        # out of scope, so it is valid ONLY when the fix is a work/repairs.json entry. An
        # override, a clarification answer, an edited input file or ANY code change is
        # consumed at or before merge, and offering the cut for one of those would skip the
        # very stage the operator just changed - the fix would silently do nothing, which is
        # the same failure the channels themselves keep producing.
        return (f"  Cheapest valid re-entry depends on HOW you fix this: a work/repairs.json "
                f"entry applies AFTER merge, so `{base} --from repairs`; an override, an "
                f"answer, an edited input or any code change is consumed at or before merge, "
                f"so it needs the full pass `{base}` (enrichment skips itself if no location "
                f"moved).")
    if channel == "repair":
        return (f"  Cheapest valid re-entry (a repair applies AFTER merge, so merge and "
                f"enrichment are skipped): {base} --from repairs")
    return (f"  Cheapest valid re-entry (this correction applies before/inside merge, so a "
            f"full pass is required; enrichment skips itself if no location changed): {base}")


def _is_current(out, inputs, stage: str = "", exclude_dir=None) -> bool:
    """--resume guard: True when `out` exists and is at least as new as every input
    that exists, so re-deriving it would reproduce the same bytes. Conservative -
    a missing output, or any input touched after the output, returns False (recompute).
    Deterministic stages only; the gates and the freeze are NEVER routed through this.

    `stage` (A2) names which stage this output belongs to, so --from/--only are implemented
    HERE - in the ONE existing skip predicate - instead of as a second, parallel skip
    mechanism sprinkled through main(). A stage the flags put out of scope reports "current"
    (and is therefore skipped) even when RESUME is false, and its existing output is reused
    as-is. Passing no `stage` keeps a caller's behaviour exactly as it was.

    `exclude_dir` (T1b) is a directory the RECURSIVE walk below must not count, and it exists
    for exactly one layout: a work dir sitting INSIDE the inputs folder, which is the natural
    thing for an operator to do and which intake.discover has excluded from its own walk (by
    the same-named parameter, deliberately mirrored) since T1. This predicate never got the
    same treatment, so every artefact the run itself wrote - canonical.json, the scorecards,
    source_ledger.csv, the per-property views, timings.json - counted as an INPUT newer than
    inventory.json, and the folder scan could therefore never be current: intake re-ran and
    re-discovered on every single pass, forever, on a warm work dir.

    THE ATTRIBUTION, CORRECTED. This is NOT caused by the timing instrument. work/timings.json
    is genuinely the last write of a pass, but the UNCONDITIONAL scorecard write in gates:pre
    (`write_scorecard(work / "gate1_scorecard.md", ...)`) already fired on EVERY pass long
    before any of the current wave landed, and so did the ledger and canonical writes. Reverting
    the timing instrument would have changed nothing. The defect is that a recursive walk over
    an input folder counts the run's own output tree, and the fix belongs here.

    Defaulted to None so every OTHER call site is byte-identical: only the folder scan passes
    it, because only the folder scan takes a directory input that can contain the work dir."""
    if _stage_skipped(stage):
        return True
    if not RESUME:
        return False
    out = Path(out)
    if not out.exists():
        return False
    try:
        out_m = out.stat().st_mtime
    except OSError:
        return False
    # Resolve ONCE, outside the walk: `_under_excluded` is called per descendant, and an
    # unresolvable exclusion must degrade to "exclude nothing" (the old behaviour) rather
    # than to a crash inside a resume predicate.
    _excl = None
    if exclude_dir is not None:
        try:
            _excl = Path(exclude_dir).resolve()
        except OSError:
            _excl = None

    def _under_excluded(p: Path) -> bool:
        if _excl is None:
            return False
        try:
            p.resolve().relative_to(_excl)
            return True
        except (ValueError, OSError):
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
                # ...and now, like discover, it skips `exclude_dir`: the run's own output tree is
                # never its own input, whatever it is named or wherever the operator put it.
                if not _under_excluded(ip):
                    newest_in = max(newest_in, ip.stat().st_mtime)
                for child in ip.rglob("*"):
                    if _under_excluded(child):
                        continue
                    newest_in = max(newest_in, child.stat().st_mtime)
            else:
                newest_in = max(newest_in, ip.stat().st_mtime)
        except OSError:
            return False  # cannot prove currency -> recompute
    return out_m >= newest_in


def _resumed(label: str) -> None:
    """One quiet 'skipped, already up to date' note in verbose mode; silent for brokers.

    ALSO records `label` against the open stage in the timing log (A0). Printing is untouched:
    the note stays verbose-only, because a broker does not need it - but the timing artefact
    does, or a 0.0s stage is indistinguishable from a stage that never ran, which is the one
    question the log exists to answer.

    A LIST of labels, not a boolean, because this function is called at two different
    granularities and always has been: once for a WHOLE stage (`_resumed("merge")`) and once
    PER INPUT FILE (`_resumed("<file> extract")`). Collapsing a 40-tracker extract stage that
    resumed 39 of them to `resumed: true` would throw away the only number that explains why
    the stage cost what it did."""
    if not QUIET:
        print(f"  (resume: {label} already up to date - skipping)")
    if _STAGE_LOG:
        try:
            _STAGE_LOG[-1]["resumed"].append(str(label))
        except Exception:
            pass  # the timing log is an instrument, never a reason for a run to fail


def _sha(path) -> str:
    """sha256 of a file's WHOLE bytes.

    No longer the enrich resume-stamp: that stamp asks a narrower question now (only the
    fields enrichment consumes - see _enrich_input_hash), because a whole-file digest re-ran
    the throttled routing calls for a corrected parking count. Kept as the general
    file-identity helper it always was, and named as such, rather than deleted with a
    docstring that would have quietly misdescribed it."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# The enrich resume stamp's SHAPE version. A stamp written by an older skill copy carries no
# `v`, and its `hash` is a digest of the WHOLE canonical file - a completely different
# question from the one _enrich_input_hash asks. Reading it as current would skip enrichment
# on a canonical whose coordinates had in fact moved, which is unrecoverable-looking (a
# town-centre pin nobody can explain) rather than merely slow. So: no `v`, or the wrong `v`,
# is a MISS, and the run pays one honest re-enrich the first time this lands.
_ENRICH_STAMP_V = 2

# The per-property inputs enrichment actually consumes. DERIVED FROM THE CONSUMING CODE, not
# from intent - the previous comment described what the author believed enrichment read, and it
# was wrong in both directions, which is how `mapLink` came to be missing. What enrich.py
# actually reads off a property today, and where:
#     id                  - every stage's per-property key (res/updates maps, region binds)
#     lat, lng            - the routing (osrm), POI and region point-in-polygon passes, and the
#                           "does this property still need a coordinate?" filter in geocode()
#     city, country       - geocode(): the cache lookup, the bundled gazetteer and the
#                           dominant-country pass.
#     postcode, postalCode
#                         - read INDIRECTLY, and that is the whole reason they were nearly
#                           missed: `_locality_code` delegates to `match._stated_postcode`,
#                           which walks `match._POSTCODE_FIELDS = ("postcode", "postalCode")`,
#                           and its answer is the THIRD segment of the geocode cache key
#                           ('city|country|code'). `geocode()` itself still names no postal
#                           field anywhere, which is exactly how a source-level grep for
#                           `p.get("postcode")` reported both as unread.
#     region, regionCode  - harmonise_regions() / bind_region_codes() and the region figures
#     mapLink             - resolve_map_links(): a first-party maps SHORT link is FOLLOWED and
#                           writes lat/lng plus coordsApprox=False. It is therefore a
#                           first-class enrichment INPUT, and it is a first-class CORRECTION
#                           target too (it is in _COERCE_STR, so an operator can supply the
#                           real pin through the override/repair channels).
# THE INCIDENT `mapLink` RE-OPENED. It was absent from this set, so: a property shipped with a
# town-centre geocode, an operator supplied the author's real pin link as a correction, the
# next default-resume pass computed the SAME hash, no cache was newer than the stamp, and
# enrichment was skipped - the wrong pin shipped, with the correction sitting applied in
# canonical and doing nothing. That is exactly the "town-centre pin nobody can explain" the
# stamp version above was minted to prevent, and exactly what the old whole-file digest caught
# by accident. enrich.py's resolve_map_links docstring records the original incident.
#
# THE POSTAL FIELDS: THE `mapLink` FAILURE MODE, ONCE MORE, ONE INDIRECTION FURTHER OUT.
# The annotation that stood here said `postcode` is read NOWHERE in enrich.py and was kept
# only as a deliberate over-inclusion, because "a LATER change makes locality a geocode-cache
# key". THAT CHANGE HAS SINCE LANDED - `_locality_code` feeds the third segment of the cache
# key today - so the annotation was stale in the one direction that ships wrong data: it told
# the next reader that a postal field cannot matter, while the code had started reading it. And
# `postalCode`, the camelCase spelling `match._POSTCODE_FIELDS` binds beside `postcode`, was
# never listed at all. So two canonicals differing ONLY in `postalCode` hashed IDENTICALLY: the
# locality segment of the cache key moved, the stamp did not, enrichment was falsely skipped
# and the town-centre pin shipped - the same incident `mapLink` caused, with the read hidden
# behind one module hop instead of behind a function name.
#
# BOTH SPELLINGS ARE LISTED, and it must stay that way. `match._POSTCODE_FIELDS` is an OPEN
# list (record_schema.json is open and a broker's own header decides the name) and the FIRST
# STATED one wins there, so hashing only one spelling leaves the other free to move the cache
# key without moving the stamp. Add a spelling to `match._POSTCODE_FIELDS` and it must be added
# here in the same change; evals/stage_control_test.py A1b now FOLLOWS that delegation into
# match.py and fails, naming the field, if it is not.
#
# THE ASYMMETRY THAT MAKES WIDENING FREE, restated because it is what makes this safe: an
# over-inclusive key can only ever cost an HONEST RE-ENRICH (a field moved that enrichment
# happens not to read); an under-inclusive one causes a FALSE SKIP, which ships wrong data
# silently. Widen freely; never narrow without reading enrich.py AND everything it delegates
# to. Nothing else it reads is per-property (the flags are stamped separately as `args`, and
# the caches invalidate by mtime).
#
# NO STAMP VERSION BUMP for the widening: a wider key hashes differently and so re-enriches
# once, which is the honest outcome anyway - `v` exists to reject a stamp that answers a
# DIFFERENT question, and this one still answers the same question, just completely.
_ENRICH_INPUT_FIELDS = ("id", "lat", "lng", "city", "country", "postcode", "postalCode",
                        "region", "regionCode", "mapLink")


def _enrich_input_hash(canonical) -> str:
    """Digest of ONLY what enrichment consumes, per property, in a deterministic order. (A1)

    WHY THIS IS NOT `_sha(canonical)`. The stamp used to hash the whole canonical file, so
    enrichment re-ran whenever ANY byte of it changed - and every correction channel in this
    pipeline changes canonical: a repair, an override, a clarification answer, a translation
    bake, a value-format fix. Correcting a parking count therefore re-ran the full enrichment
    pass, including the THROTTLED routing/POI calls, for a field enrichment cannot read and
    cannot be changed by. On a live run that is minutes of network per typo, and it is the
    reason a batch of small corrections felt like a full rebuild.

    Enrichment cannot be changed by a parking-count correction, so the stamp must not claim it
    can. It hashes the spatial/administrative inputs and the property `id` and nothing else:
    move `lat` and it re-runs; fix `loadingDocks` and it does not. The "a cache file is newer
    than the stamp" invalidator beside the caller is unchanged and still catches the other
    direction (a freshly seeded geocode/POI/region cache, or an answered region label).

    Order is fixed by construction: the FIELDS in _ENRICH_INPUT_FIELDS order, the PROPERTIES
    sorted by their serialised row. Sorting the rows (rather than trusting canonical's array
    order) means a merge that re-orders the same properties does not re-run enrichment either -
    enrichment is per property, so the array order genuinely cannot change its output.

    Returns "" when canonical cannot be read or holds no properties, and the caller treats ""
    as a MISS: a hash we cannot compute must never be able to match a stored one."""
    try:
        data = json.loads(Path(canonical).read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    rows = []
    for p in (data.get("properties") or []) if isinstance(data, dict) else []:
        if isinstance(p, dict):
            rows.append(json.dumps([[f, p.get(f)] for f in _ENRICH_INPUT_FIELDS],
                                   ensure_ascii=False, sort_keys=True, default=str))
    if not rows:
        return ""
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def _tracker_map_key(structs, code: str = "") -> list:
    """The tracker column-map cache key: sheet names + headers + unmapped_headers, plus a
    CODE STAMP over the extractor that produces them. (A21)

    WHAT WENT WRONG. The key was the WHOLE tracker structure, which
    `extract_xlsx.tracker_structure` builds with four DATA-DERIVED members alongside the
    headers: `sample_rows`, `sample_row_numbers`, `populated_columns` and `unsampled_columns`.
    Sample selection is a GREEDY SET COVER over which cells are non-blank, so it legitimately
    picks DIFFERENT rows when the data changes, and `populated_columns` moves the moment a
    column's last value is deleted. The consequence: editing ANY data cell in a
    schema-identical sheet changed the hash, invalidated a SETTLED column map, and re-opened
    the interpretation handoff - an exit 3, a sub-agent dispatch and an operator round-trip,
    for a corrected postcode.

    WHY THE HEADERS ARE THE HONEST KEY. The map is a header -> field binding. It is a statement
    about the SCHEMA of the sheet, and a data cell cannot make that statement wrong.
    `unmapped_headers` stays IN the key deliberately: it is the list of columns the dictionary
    could not place, i.e. the actual question being asked of the sub-agent, so a sheet whose
    dictionary coverage changed IS a different question and should be re-asked. Sheet names
    stay in because a renamed or added sheet is a different sheet.

    THE TRADE-OFF, RECORDED. The blind verifier's magnitude cross-check reads `sample_rows`, so
    a map authored against one sample set may now be REUSED against another. That is accepted:
    the map binds headers to fields, the verifier's diff is advisory and never drives the
    parse, and the alternative is the invalidation loop above. What is lost is a
    re-verification we were only getting by accident; what is gained is that a settled
    interpretation stays settled.

    `code` IS THE CODE STAMP, AND IT CLOSES A PRE-EXISTING HOLE THE NARROWING EXPOSED - it did
    NOT create it. Keeping `unmapped_headers` in the key catches an alias-table change that
    moves a header INTO or OUT OF the unmapped list. It cannot catch an alias-table change that
    RE-POINTS an already-mapped header from one field to another: the sheet names, the headers
    and the unmapped list are then all byte-identical, the key is stable, and a settled
    interpretation map is reused on top of a deterministic dictionary that now disagrees with
    it. That hole was there while the key was the whole structure too; the data-derived members
    were merely churning the key often enough to keep re-asking by accident, and narrowing the
    key removed that incidental cover. So the guard is stated explicitly instead of inherited
    from noise: a digest of the LIVE BYTES of `extract_xlsx.py` (the module that owns both the
    alias dictionary and `tracker_structure`) is folded into the payload, so an edit to the
    dictionary re-opens the mapping question exactly once, deliberately.

    This is the SAME guard every other cached-output stage in this file already carries - merge,
    build and deliver each fold `_code_stamp` into their resume inputs (B42) - and the tracker
    map was the one cached output that carried no code identity at all. `code` is a PARAMETER
    rather than a read inside this function on purpose: the projection stays pure and
    I/O-free, so an eval can pin the code component behaviourally (two different stamps must
    yield two different keys) instead of pinning the text of a file read.

    Module-level rather than nested in main() so an eval can pin it directly - a cache key
    nobody can test is how the wide one survived. `headers` is already in hand (produced at
    extract_xlsx.py's tracker_structure and carried in the entry), so no extra I/O.

    Existing work dirs re-ask ONCE when this lands: the narrowed payload hashes differently
    from the old wide one, so a cached map's `input_hash` echo no longer matches. That is the
    intended one-off cost of correcting the key."""
    key: list = [{"sheet": (s or {}).get("sheet"),
                  "headers": (s or {}).get("headers"),
                  "unmapped_headers": (s or {}).get("unmapped_headers")}
                 for s in (structs or [])]
    # APPENDED, and only when non-empty, so the per-sheet entries keep their exact shape and
    # position: `key[0]` is still the first sheet's schema projection, which is what the
    # existing assertions and any future reader of a cached `input_hash` echo expect.
    if code:
        key.append({"extractor_code": str(code)})
    return key


def _repairs_cleared(rep: dict) -> dict:
    """{property id -> the field names an APPLIED repair CLEARED}, READ OFF THE REPAIR REPORT.

    Read, never inferred. `repairs.apply` stamps `cleared: True` on every change it made by
    REMOVING the key - that is the `unset` verb and the `strike_from_source` verb - so the
    report already knows this precisely, per property, and it distinguishes a clear from a
    same-valued `set` that a resumed pass re-applies. A private opinion here about which
    fields "look cleared" (an absent key? a sentinel value?) would drift from the verb that
    actually cleared them, and a drifting second opinion about one value is the exact shape of
    defect `_coerce_repaired_scalars` below exists to undo.

    Keyed on the property id as a STRING both sides, because that is what the report carries
    (`property_id: p.get("id")`) and canonical ids arrive as ints from some trackers and
    strings from others. Best-effort: a report of any other shape yields {} and the coercion
    then behaves exactly as it did before this parameter existed."""
    out: dict = {}
    for a in ((rep or {}).get("applied") or []):
        if not isinstance(a, dict):
            continue
        gone = {str(f) for f, ch in (a.get("changed") or {}).items()
                if isinstance(ch, dict) and ch.get("cleared")}
        if gone:
            out.setdefault(str(a.get("property_id")), set()).update(gone)
    return out


def _write_decision_trail(work: Path, record_files: list, n_xlsx: int, interpret_trackers: list,
                          n_grey, n_conflicts) -> None:
    """F29: work/decision_trail.json - which DECISION stages had nothing to decide, and why.

    A blind reviewer of a live work dir could not close its audit: no match_decisions.json, no
    match_verify.json, no field_decisions.json, no tracker column maps. Consistent with a
    brochures-only corpus with no trackers and no cross-source merges, in its own words, "but I
    cannot tell 'not applicable' from 'never ran'". Absence is not evidence; this stamp is.

    Each stage entry carries a `status`, a `why` in words, and `evidence` that is RE-COUNTABLE
    from the work dir rather than taken on trust: the record files enumerated, the grey-pair
    and field-conflict counts the enumeration itself produced (None when it never ran, and the
    entry says so), the spreadsheet count from inventory.json, and for every tracker offered
    to the mapping sub-agent whether its map output or .SKIP sentinel exists. Statuses:
      not_applicable         the stage had no input to decide on (the reason names the count);
      ran                    applicable and its output file exists;
      applicable_no_output   applicable but the output is absent: THAT is "never ran", and it
                             is the case a reviewer must be able to see.
    Written every pass (cheap, deterministic), never read by any stage: disclosure only."""
    try:
        import _common as C
        work = Path(work)
        rf = [str(Path(f).name) for f in (record_files or [])]
        n_rf = len(rf)

        def _st(applicable: bool, output: str) -> str:
            if not applicable:
                return "not_applicable"
            return "ran" if (work / output).exists() else "applicable_no_output"

        stages: dict = {}
        cross = n_rf > 1
        stages["match_decisions"] = {
            "status": _st(cross, "match_decisions.json"),
            "why": (f"cross-source pair adjudication needs at least two record files; this run "
                    f"produced {n_rf}" if not cross else
                    f"{n_rf} record files, so pairs were enumerated: {n_grey} grey pair(s)"),
            "evidence": {"record_files": rf, "grey_pairs": n_grey,
                         "output": "match_decisions.json",
                         "output_exists": (work / "match_decisions.json").exists()}}
        verify_app = cross and bool(n_grey)
        stages["match_verify"] = {
            "status": _st(verify_app, "match_verify.json"),
            "why": ("the independent verify pass re-checks GREY pairs only; "
                    + (f"there were {n_grey}" if cross else
                       f"no pairs can exist with {n_rf} record file(s)")),
            "evidence": {"grey_pairs": n_grey, "output": "match_verify.json",
                         "output_exists": (work / "match_verify.json").exists()}}
        conf_app = cross and bool(n_conflicts)
        stages["field_decisions"] = {
            "status": _st(conf_app, "field_decisions.json"),
            "why": ("field adjudication needs a value conflict between records the match "
                    "step put in one cluster; "
                    + (f"the enumeration found {n_conflicts}" if cross else
                       f"none can exist with {n_rf} record file(s)")),
            "evidence": {"field_conflicts": n_conflicts, "output": "field_decisions.json",
                         "output_exists": (work / "field_decisions.json").exists()}}
        maps = []
        for j in interpret_trackers or []:
            try:
                o = _deck_output_path(work, j)
            except Exception:
                o = None
            maps.append({"source_file": str((j or {}).get("source_file") or ""),
                         "kind": str((j or {}).get("kind") or ""),
                         "output": str(o) if o else "",
                         "output_exists": bool(o and Path(o).exists()),
                         "skip_exists": bool(o and Path(str(o) + ".SKIP").exists())})
        if not n_xlsx:
            t_status = "not_applicable"
        elif not maps:
            t_status = "not_applicable"
        elif all(m["output_exists"] or m["skip_exists"] for m in maps):
            t_status = "ran"
        else:
            t_status = "applicable_no_output"
        stages["tracker_maps"] = {
            "status": t_status,
            "why": ("no spreadsheet in inventory.json, so no tracker column map was needed"
                    if not n_xlsx else
                    f"{n_xlsx} spreadsheet(s) in inventory.json; {len(maps)} offered to the "
                    f"mapping sub-agent" + ("" if maps else " (none needed a map: the built-in "
                                            "dictionary bound every column)")),
            "evidence": {"xlsx_in_inventory": n_xlsx, "trackers_offered": maps}}
        C.atomic_write_text(work / "decision_trail.json", json.dumps(
            {"v": 1, "stages": stages}, ensure_ascii=False, indent=2))
        if not QUIET:
            na = [k for k, v in stages.items() if v["status"] == "not_applicable"]
            nr = [k for k, v in stages.items() if v["status"] == "applicable_no_output"]
            print("(decision trail: work/decision_trail.json - not applicable: "
                  + (", ".join(na) or "none") + "; applicable but no output: "
                  + (", ".join(nr) or "none") + ")", file=sys.stderr)
    except Exception as _e:
        print(f"(decision trail not written: {type(_e).__name__}: {_e})", file=sys.stderr)


def _full_view_for_humans(work: Path, folder) -> None:
    """F20: write the FULL per-property view (media included) because a pre-build gate has
    BLOCKED this pass and a human is about to open work/properties/ to see why. The ordinary
    pass writes the data half only (see the projection stage); this is the one place the
    media half is written by the spine, so the 50-second, 80 MB rebuild is paid exactly when
    someone will look at it. Prints one line naming the exact command that produces the same
    view by hand (B5's `rebuild_command`), and never raises: a projection failure must not
    hide the gate verdict it is decorating."""
    try:
        import project_properties as _pp   # not `_proj`: an eval anchors on the stage's import
        _pr = _pp.build(work, source_dir=folder, image_cache=work / ".image_cache",
                        media_view="always")
        print(f"(full per-property view written for review: {_pr['count']} folder(s) under "
              f"work/properties/ incl. media; rebuild by hand with: "
              + _pp.rebuild_command(work, folder, work / ".image_cache") + ")", file=sys.stderr)
    except Exception as _e:
        print(f"(full per-property view skipped: {type(_e).__name__}: {_e})", file=sys.stderr)


def _rederive_after_repairs(canonical, applied: list | None = None, ledger=None,
                            stamp=None) -> list:
    """F24 (run half): re-run merge's post-merge derivations after the repairs stage, and say
    which region-bind inputs a repair moved that nothing downstream re-binds.

    WHY. `officeAreaVal` is declared "derived by merge from officeArea", and repairs run AFTER
    merge. On the measured run the two properties whose office area arrived through a repair
    carried None in the twin: the modal printed a unit-less string and Total GLA silently
    excluded the office. merge owns the derivation (contract C2: `merge.DERIVED_TWINS` and
    `merge.rederive_after_repairs(canonical) -> list[str]`); this only calls it, on the
    in-memory canonical, and writes the file back when it reports having changed anything.
    DEFENSIVE BY DESIGN: the merge half may land after this one, so an older merge.py without
    the function is INERT here (one stderr aside, no exception), never fatal.

    THE REGION BIND IS NOT RE-RUN HERE, AND THE LINE SAYS SO. `enrich.bind_region_codes`
    needs the region statistics dataset and the gaps list that enrichment loads inside its own
    helper process from its own arguments; this process holds neither, and re-binding without
    the conflict disclosure (`harmonise_regions`) would be a bind with its cross-check missing.
    So when a repair changed a field in `_ENRICH_INPUT_FIELDS` (the exact set the enrichment
    stamp hashes), the returned lines NAME the property and field and say the bind is stale
    until enrichment re-runs; the stamp's own hash then misses on the next pass and
    enrichment re-runs by itself, which is the honest route rather than a half re-bind.

    ...AND ONLY WHEN THE BIND IS ACTUALLY STALE (D14). Repairs live in work/repairs.json and
    are RE-APPLIED on every pass, so `applied` is never empty once a bind input has ever been
    repaired: on the measured run five `region` repairs (labels for an already-correct
    `regionCode`) printed "region bind STALE" on every later pass, resumed or full, right
    through to exit 0, with `from` equal to `to` on all five (the value was already in
    canonical). The first version keyed the notice on the FIELD NAME alone. Two facts decide
    it now, both read rather than inferred: did this pass's application MOVE the stored value
    (`_repair_moved`: a re-applied repair whose value is already there is not news), and does
    the enrichment stamp's input hash still match canonical as repaired (`_bind_inputs_stale`:
    when it matches, the bind saw exactly these values). The notice fires only when a value
    moved AND the stamp does not cover it (or there is no stamp to say so). A genuinely moved
    `lat` is still reported, once, and clears on the pass that re-binds it."""
    out: list = []
    try:
        import _common as C
        path = Path(canonical)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("properties"), list):
            return out
        try:
            import merge as _merge
            fn = getattr(_merge, "rederive_after_repairs", None)
        except Exception:
            fn = None
        if fn is None:
            print("(re-derivation after repairs: merge.rederive_after_repairs is not available "
                  "in this merge.py, so derived twins such as officeAreaVal were NOT refreshed - "
                  "the merge half of F24 has not landed.)", file=sys.stderr)
        else:
            before = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
            # the repaired-field hint decides direction for a pair (which side a human touched)
            # and permits a withdrawal; the ledger path gets the twin its provenance row
            _rf = getattr(_merge, "repaired_fields", None)
            changed = _rf({"applied": list(applied or [])}) if callable(_rf) else None
            try:
                lines = fn(data, changed=changed, ledger=ledger) or []
            except TypeError:           # an older signature: positional canonical only
                lines = fn(data) or []
            out.extend(str(x) for x in lines if str(x).strip())
            if json.dumps(data, ensure_ascii=False, sort_keys=True, default=str) != before:
                C.atomic_write_text(path, json.dumps(data, ensure_ascii=False))
        # the region-bind inputs a repair ACTUALLY moved this pass, named rather than left
        # silently stale; a re-applied repair whose value was already in canonical is skipped
        # (D14: that re-fired the notice on every pass of the measured run)
        _bind_in = set(_ENRICH_INPUT_FIELDS) - {"id"}
        _moved: list = []
        for a in applied or []:
            if not isinstance(a, dict):
                continue
            moved = sorted(k for k, ch in (a.get("changed") or {}).items()
                           if k in _bind_in and _repair_moved(ch))
            if moved:
                _moved.append((a, moved))
        if _moved and _bind_inputs_stale(path, stamp):
            for a, moved in _moved:
                out.append(f"region bind STALE for property {a.get('property_id')}: repair "
                           f"'{a.get('id')}' changed {', '.join(moved)}, which the workforce-"
                           f"region bind reads; enrichment re-runs on the next pass (its input "
                           f"hash has moved) and re-binds it then, with the conflict cross-check.")
    except Exception as _e:
        out.append(f"(re-derivation after repairs skipped: {type(_e).__name__}: {_e})")
    return out


def _repair_moved(ch) -> bool:
    """Did ONE applied change (repairs.py's `changed[field]`) actually move the stored value?

    repairs.py records `{"from", "to"}` for every `set` it applies, deliberately including the
    same-value case (its own note: a repair already applied on a prior run reads back as a
    no-op on this one, and the meta.conflicts annotation must still run). That is right for the
    annotation and wrong as a staleness signal, so the distinction is drawn here (D14). A clear
    moved the value when there was one to remove."""
    if not isinstance(ch, dict):
        return False
    if ch.get("cleared"):
        return not ch.get("already_absent") and ch.get("from") is not None
    return ch.get("from") != ch.get("to")


def _bind_inputs_stale(canonical, stamp=None):
    """Does the enrichment stamp FAIL to cover canonical as it stands after repairs?

    The stamp (`work/.enrich.stamp`, written right after enrichment ran) carries
    `_enrich_input_hash` of exactly the fields the region bind reads. When that hash equals the
    hash of the repaired canonical, the bind already saw these values and nothing is stale,
    whatever the repairs report says. True when the stamp is absent or unreadable (nothing can
    vouch for the bind, so a moved input is reported), when its hash differs, or when the
    current hash cannot be computed (a hash we cannot compute must never be able to match)."""
    try:
        sp = Path(stamp) if stamp is not None else Path(canonical).parent / ".enrich.stamp"
        if not sp.exists():
            return True
        prev = json.loads(sp.read_text(encoding="utf-8-sig"))
        cur = _enrich_input_hash(canonical)
        return not (bool(cur) and isinstance(prev, dict) and prev.get("hash") == cur)
    except Exception:
        return True


def _coerce_repaired_scalars(canonical, cleared: dict | None = None) -> int:
    """Re-apply the render-boundary coercion to every property after repairs wrote. (A3a)

    THE ASYMMETRY THIS CLOSES WAS ONE OF STAGE ORDERING, NOT INTENT. An override is applied
    PRE-MERGE, so it passes through `merge.canonicalize` -> `C.fill_render_sentinels`, which is
    the ONLY place a well-meant integer in a string-typed chrome field is coerced
    (`loadingDocks: 12` -> `"12"`). A repair is applied by the repairs stage, i.e. AFTER merge,
    and wrote its value straight into canonical - so the two audited, `verified_by`-attributed,
    ledger-recorded human correction channels disagreed about types, and only the later one
    could hard-fail validate-data with "12 is not of type 'string'". Same coercion, same
    function, now on both paths.

    Reuses `C.fill_render_sentinels` rather than reimplementing the coercion: the coercion set
    is `STRING_FIELDS | REQUIRED_TEXT_SENTINELS | {landPrice, mapLink, reit}`, it is derived
    from the field registry, and a second copy of it here would drift the moment a field is
    added - which is precisely how this asymmetry arose.

    `cleared` IS THE SECOND HALF OF THIS DEFECT, and it is only optional in the signature.
    `fill_render_sentinels` re-fills EVERY chrome-read key with its own honest unknown, which is
    right at the RENDER boundary - build_dashboard and the gates call it on a COPY - and wrong
    here, where it runs on canonical ITSELF. The `unset` verb clears a field by REMOVING the
    key (repairs.py: "CLEARING IS REMOVAL", so the ledger row cannot claim the repair SET a
    value), and this pass then put every removed chrome-read key straight back as the blank
    sentinel. The two
    changes cancelled exactly: `unset` did not work on ANY chrome-read field, while the repair
    reported CLEARED, printed a CLEARED line and wrote a CLEARED Source Ledger row. A withdrawal
    an operator can see confirmed in three places and cannot see happen is worse than one that
    is refused. Two changes, two authors, one value - the coercion landed after the clear, and
    nobody owned the join.

    BOTH BEHAVIOURS NOW SURVIVE, and they do not fight: a wrongly-typed scalar is still coerced
    on every property, and a key an APPLIED clear removed is put back out again afterwards. The
    decision comes from the report (`_repairs_cleared`), never from the shape of the data, and
    it is taken BEFORE the fill - see the note at the loop.

    Idempotent by construction (a sentinel is already unknown-looking, a string is already a
    string), so it is safe on the properties a repair did NOT touch, and cheap: no I/O unless
    the bytes actually change. Returns the number of properties whose bytes moved."""
    try:
        import _common as C
        path = Path(canonical)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        props = data.get("properties") if isinstance(data, dict) else None
        if not isinstance(props, list):
            return 0
        cleared = cleared or {}
        changed = 0
        for p in props:
            if not isinstance(p, dict):
                continue
            before = json.dumps(p, ensure_ascii=False, sort_keys=True, default=str)
            # WHICH KEYS MUST STAY GONE - decided BEFORE the fill, from the REPORT, and only
            # for keys that are absent RIGHT NOW. Both conditions are load-bearing:
            #   * from the report, so a genuinely off-spec key that no verb touched, and a
            #     sentinel a source really stated, are left completely alone;
            #   * absent right now, so a later entry that legitimately `set` the same field
            #     (repairs' own contradiction and supersede rules police that) is never
            #     re-removed, and a resumed pass whose clear already landed behaves the same.
            _stay_gone = {k for k in cleared.get(str(p.get("id")), ()) if k not in p}
            C.fill_render_sentinels(p)
            for k in _stay_gone:
                p.pop(k, None)
            if json.dumps(p, ensure_ascii=False, sort_keys=True, default=str) != before:
                changed += 1
        if changed:
            C.atomic_write_text(path, json.dumps(data, ensure_ascii=False))
        return changed
    except Exception:
        return 0  # a coercion pass must never be the thing that stops a run


def _write_if_changed(path: Path, text: str) -> Path:
    """Write only when content differs, so an unchanged intermediate keeps its mtime.
    Lets --resume see that downstream stages (merge) are still current instead of
    being re-triggered by a byte-identical rewrite. A no-op when content matches."""
    path = Path(path)
    try:
        if path.exists() and path.read_text(encoding="utf-8-sig") == text:
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
            d = json.loads(Path(f).read_text(encoding="utf-8-sig"))
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
    used to throw away a clean PDF parse.

    NOT WIRED INTO THE SPINE AT PRESENT. A 2026-09-19 dead-code audit found no caller:
    the interpretation manifest decides text-versus-raster mode per deck on its own
    evidence, and this probe was never connected to that decision. It is kept, with this
    notice, because normalize.UNKNOWN_FORMS and deliver._is_tbd both document the routing
    it WOULD drive and because the predicate itself is sound; whoever wires it should do
    so at the manifest step and re-run the sentinel parity evals, since every form added
    to the shared unknown set then changes which decks the LLM is asked to re-read. Until
    then, nothing a reader ships as tbd changes vision routing, whatever those two
    comments imply."""
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
                recs = json.loads(f.read_text(encoding="utf-8-sig"))
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


def _repair_screen_fields(work: Path, repairs_path, repairs_mod) -> set:
    """`extra_fields` for the STARTUP repair screen (A4) - the same widening the REAL consumer
    passes, and a screen that goes INERT rather than refusing when it cannot compute one.

    THE INCIDENT. The startup screen called `repairs.load` with NO `extra_fields` at all, while
    the real consumer - `repairs.run` - has for some time called it with every key present on
    any property in canonical. Off-spec keys are a normal and LARGE part of every record (the
    extraction contract emits a stated row with no canonical home under a descriptive key, and
    repairs.py's own comment says exactly that), so a CORRECT, attributed, `verified_by`-signed
    repair on an unmapped tracker column was refused at STARTUP with a message asserting the
    key "is on no property in this dataset" - when it was on all of them. That refusal is exit
    16, and exit 16's documented remedy is "FIX or DELETE it in place". Neither is possible for
    a key that is already right, so an operator following the contract to the letter DELETES a
    verified correction. Two changes, two authors, one value: the widening landed on the
    consumer and nobody owned the screen at the other end.

    WHEN CANONICAL IS ABSENT THE SCREEN MUST NOT REFUSE. On a first pass, or after a
    --no-resume clean-out, there is no canonical yet and this function cannot compute the
    dataset half of the answer AT ALL - and a screen that cannot read canonical must not refuse
    a key it cannot judge, because that is precisely how the original defect did its damage. So
    `extra_fields` becomes every field name the repairs file itself names, which makes exactly
    ONE of `load`'s checks inert - the dataset-membership one - and leaves every other fault
    firing at startup exactly as before: unreadable JSON, a non-list file, a missing `why` or
    `verified_by`, a blank `set`, a field in BOTH `set` and `unset`, a denied field, a required
    field under `unset`, an unknown media slot, a duplicate id, nothing-to-do.

    AND NOTHING IS LOST BY GOING INERT. The repairs STAGE on that same pass calls
    `repairs.run`, which re-screens against the canonical it has just built and reports a
    genuine typo as INVALID there, with `apply` holding every key to the RESOLVED property
    besides. The startup screen buys EARLINESS, not a second opinion; on a cold work dir there
    is no earliness to buy, and buying it with a false refusal costs a correction.

    Best-effort throughout, and it returns a SET in every case: this runs before any stage, so
    an unreadable file must contribute nothing and must never raise - the loader called right
    after reports that file's own fault in the operator's own words."""
    try:
        canonical = json.loads((Path(work) / "canonical.json").read_text(encoding="utf-8-sig"))
        if isinstance(canonical, dict) and canonical.get("properties"):
            # THE SAME EXPRESSION `repairs.run` USES, deliberately and by name: any key on any
            # property widens the screen. Keep the two in step - a divergence here IS the
            # defect above, re-made.
            return {str(k) for p in (canonical.get("properties") or [])
                    if isinstance(p, dict) for k in p}
    except Exception:
        pass
    # No canonical to judge against -> make the membership screen inert (see above) by handing
    # it the names the file itself uses. `_verbs` is repairs.py's OWN one definition of what the
    # verbs are, so this cannot drift from what `load` will actually screen; an entry too
    # malformed to read contributes nothing and is reported by the loader on its own terms.
    names: set = set()
    try:
        raw = json.loads(Path(repairs_path).read_text(encoding="utf-8-sig"))
    except Exception:
        return names
    for _e in raw if isinstance(raw, list) else []:
        if not isinstance(_e, dict):
            continue
        try:
            _sets, _unset, _strike = repairs_mod._verbs(_e)
        except Exception:
            continue
        names |= {str(k) for k in _sets}
    return names


def _force_raster_path(work: Path) -> Path:
    return work / "vision" / "force_raster.json"


def _load_force_raster(work: Path) -> set:
    """Source files an interpretation sub-agent escalated to the raster path. (B65)

    Durable because the escalation request (a `needs_raster` stub) is consumed - deleted - on
    the pass that reads it, so a set derived only from the stubs on disk is empty by the time
    anything downstream needs it."""
    try:
        raw = json.loads(_force_raster_path(work).read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    got = raw.get("decks") if isinstance(raw, dict) else raw
    return {str(x) for x in got} if isinstance(got, list) else set()


def _save_force_raster(work: Path, decks: set) -> None:
    p = _force_raster_path(work)
    try:
        # _common is imported INSIDE functions throughout run.py (so the module imports
        # cleanly on a host missing an optional dep) - do the same here, or this silently
        # no-ops on a NameError, which is exactly what the swallow below would hide.
        import _common as _C
        if not decks:
            p.unlink(missing_ok=True)      # nothing outstanding: leave no stale file behind
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        _C.atomic_write_text(p, json.dumps({"schema_version": 1, "decks": sorted(decks)},
                                           ensure_ascii=False, indent=1))
    except Exception:
        pass


def photo_match_candidates(targets: list, force_raster: set) -> list:
    """The vision targets photo-match may consider. (B65)

    Photo-match asks "this brochure has no extractable text, and I already know these
    properties from another source - which one is it a photo OF?". A deck an interpretation
    sub-agent ESCALATED is not that: the reader read it and reported a property deck with a
    garbled text layer, so the only honest verdict is `unrelated`, and asking spends the
    escalation on the wrong branch. Its siblings are still matched normally."""
    return [t for t in targets if Path(t[0]).name not in (force_raster or set())]


def keep_vision_targets(targets: list, matched: dict, still_vision: set) -> list:
    """Vision targets surviving photo-match, filtered IN PLACE over the original list.

    Order is the point: rebuilding the list from the matcher's own iteration would reorder
    decks that were never offered to it, and the build is required to be byte-deterministic.
    A deck photo-match never saw (`not in matched`) passes through untouched."""
    return [t for t in targets if t[0] not in matched or t[0] in still_vision]


def _deck_outputs_path(work: Path) -> Path:
    return work / "vision" / "deck_outputs.json"


def load_deck_outputs(work: Path) -> dict:
    """The DURABLE source_file -> output map. (B64)

    The manifest carries only the decks pending THIS pass, yet it was also the sole memory of
    where each deck's records live, so `_vision_supersedes` returned False for every completed
    deck the moment the manifest shrank: they were re-prepped, re-listed as pending, and the
    exit-3 diagnosis asserted their outputs did not exist while they sat on disk. SKILL.md
    tells the orchestrator to satisfy those predicates and never guess, so followed literally
    that is a redundant re-dispatch of every finished reader.

    Keyed by _vkey(source_file) so it survives the same case/diacritic drift the rest of the
    interpretation path already tolerates."""
    try:
        raw = json.loads(_deck_outputs_path(work).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    got = raw.get("outputs") if isinstance(raw, dict) else None
    return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}


def save_deck_outputs(work: Path, decks: list) -> None:
    """MERGE this pass's assignments into the durable map. Never drops a key: a deck absent
    from today's manifest is precisely the one whose path must still be findable."""
    known = load_deck_outputs(work)
    merged = dict(known)
    for d in decks or []:
        sf, out = str((d or {}).get("source_file") or ""), str((d or {}).get("output") or "")
        if sf and out:
            merged[_vkey(sf)] = out
    if merged == known:
        return
    try:
        import _common as _C            # imported inside, per the run.py convention
        p = _deck_outputs_path(work)
        p.parent.mkdir(parents=True, exist_ok=True)
        _C.atomic_write_text(p, json.dumps({"schema_version": 1, "outputs": merged},
                                           ensure_ascii=False, indent=1))
    except Exception:
        pass


def assign_deck_outputs(decks: list, known: dict | None = None) -> list:
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

    `known` (B64) is the durable source_file -> output map. A deck that has been assigned a path
    before KEEPS it, because the name derived below depends on which OTHER decks share this
    manifest: the same deck alone in a one-deck manifest and beside a label-twin in a nine-deck
    one derives two different filenames, which would strand the records already written under
    the first. Passing nothing preserves the original pure-function behaviour.
    """
    import hashlib
    known = known or {}
    counts: dict = {}
    for d in decks:
        k = _vkey(_deck_label(d))
        counts[k] = counts.get(k, 0) + 1
    outs = []
    taken = set()
    for d in decks:
        prior = known.get(_vkey(str(d.get("source_file") or "")))
        if prior and prior not in taken:
            d["output"] = prior
            outs.append(prior)
            taken.add(prior)
            continue
        label = _deck_label(d) or "region"
        safe = re.sub(r"[^\w\-. ]+", "_", label).strip(" .") or "region"
        if counts.get(_vkey(_deck_label(d)), 0) > 1 or not _vkey(_deck_label(d)):
            h = hashlib.sha256(str(d.get("source_file", "")).encode("utf-8")).hexdigest()[:8]
            name = f"{safe}__{h}_vision.json"
        else:
            name = f"{safe}_vision.json"
        d["output"] = f"work/extract/{name}"
        outs.append(d["output"])
        taken.add(d["output"])
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
        decks = json.loads(mf.read_text(encoding="utf-8-sig")).get("decks", [])
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
        decks = json.loads(mf.read_text(encoding="utf-8-sig")).get("decks", [])
    except Exception:
        return False
    mine = [d for d in decks if _vkey(str(d.get("source_file", ""))) == _vkey(src_name)]
    if not mine:
        # B64: the manifest holds only what is PENDING, so a deck finished on an earlier pass
        # is simply not in it. Falling straight to False here re-prepped and re-listed every
        # completed deck the moment the manifest shrank, and made the exit-3 diagnosis claim
        # their outputs were missing while they sat on disk. The durable map is the memory.
        prior = load_deck_outputs(work).get(_vkey(src_name))
        return bool(prior and _deck_interpreted(work, {"output": prior}))
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
        st = json.loads(f.read_text(encoding="utf-8-sig"))
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


def _handoff_once(work: Path, code: int, prior: dict, what: str, full: str, tail: str = "") -> str:
    """F4: the LONG handoff prints in full the first time an exit kind fires in a streak; a
    re-fire of the SAME exit prints a two-line reminder plus where the prompts live.

    Measured: the exit-3 handoff is about 2,300 characters and reprinted verbatim on every
    re-fire, so a run that took four passes to satisfy one guard printed it four times and
    the operator stopped reading it, which is exactly when the one line that changed (the
    `[pending]` diagnosis) most needed reading. The streak is `prior["last"] == code`, the same
    reading `_record_exit` makes a moment later, so the two never disagree. What this MUST NOT
    shorten, and does not touch: the `[pending]` lines `_exit_round_trip` prints on a re-fire;
    they are the only thing that says WHY the exit re-fired. `tail` is any text (a setup prefix,
    the prompts sentence) that must accompany both forms."""
    if prior.get("last") != code:
        return full
    return (f"(orchestrator: exit {code} AGAIN - {what} is still pending; the full handoff was "
            f"printed on the first exit {code} of this streak and has not changed.\n"
            f" The agent prompts are under {work / 'prompts'}; the [pending] lines below name "
            f"exactly what the guard still wants.){tail}")


def _exit_round_trip(work: Path, code: int, prior: dict, what: str,
                     diagnosis: list | None = None) -> None:
    """The ONE exit path for every orchestrator round-trip. Records the streak and, once the same
    request has been re-emitted ATTEMPT_WARN times in a row, prints a plain diagnosis before
    exiting - the run is not making progress and something upstream is not converging. This does
    NOT block or change the exit code: the orchestrator may legitimately need several rounds, and
    a wrong bound would be worse than none. It converts a silent livelock into a visible one.

    `diagnosis` (P3: guard self-diagnosis) is the caller's list of EXACT pending predicates -
    one line per item the completion guard still considers unanswered, naming the file/key/id it
    read and why it did not satisfy ("output not written yet: <path>", "pair 'x' has no
    recognised verdict in match_decisions.json"). Always persisted to
    work/pending_diagnosis.json; PRINTED once the same exit repeats (streak >= 2), because at
    that point the orchestrator's answer was not recognised and guessing at the predicate is
    exactly the code-archaeology this parameter exists to remove. A live run spent five exit-3
    round-trips discovering that a stamp/manifest mismatch was the failing predicate - lines
    like these would have named it on pass two."""
    streak = _record_exit(work, code, prior)
    items = [str(d).strip() for d in (diagnosis or []) if str(d).strip()]
    if items:
        try:
            import _common as _C
            _C.atomic_write_text(work / "pending_diagnosis.json", json.dumps(
                {"exit": code, "what": what, "streak": streak, "pending": items},
                ensure_ascii=False, indent=2))
        except Exception:
            pass
    if streak >= 2 and items:
        _say_orchestrator("(orchestrator: the guard's EXACT pending predicates this pass - "
                          "satisfy THESE; it reads nothing else:)")
        for _line in items[:20]:
            _say_orchestrator(f"  [pending] {_line}")
        if len(items) > 20:
            _say_orchestrator(f"  [pending] ... and {len(items) - 20} more - "
                              f"work/pending_diagnosis.json holds the full list.")
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


def _is_unsure(v) -> bool:
    return (isinstance(v, str) and v.strip().lower() == "unsure") or \
        (isinstance(v, dict) and str(v.get("verdict") or v.get("pick") or "")
         .strip().lower() == "unsure")


def _mutate_decisions_file(path: Path, updates: dict) -> None:
    """Set entries in match_decisions.json / field_decisions.json, atomically,
    preserving everything else. A malformed file is replaced by just the updates
    (the guard re-asks anything it cannot read, so nothing is lost silently)."""
    import _common as C
    try:
        cur = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    cur.update(updates)
    C.atomic_write_text(Path(path), json.dumps(cur, ensure_ascii=False, indent=1))


def _rec_brief(r: dict) -> str:
    bits = [str(r.get("park") or r.get("address") or "?")]
    if r.get("city"):
        bits.append(str(r["city"]))
    if r.get("warehouseArea") not in (None, ""):
        bits.append(f"{r['warehouseArea']} {r.get('areaUnit') or ''}".strip())
    src = (r.get("__meta") or {}).get("source_file")
    if src:
        bits.append(f"from {src}")
    return ", ".join(bits)


def unsure_pair_questions(work: Path, cfg: dict, grey: list) -> tuple:
    """Workstream 3 item 3.3 (pairs): 'unsure' is a FIRST-CLASS author verdict.

    The adjudicator used to be FORCED to 'different' when genuinely torn - the broker,
    who knows the market, was never offered the call. Interactive (the standard): each
    unsure pair becomes a BLOCKING exit-13 broker question; the answer is written back
    into match_decisions.json as an attributed verdict (same order-independent pair_id,
    so the re-run merges byte-deterministically). Headless: unsure resolves immediately
    to 'different' (today's safe default - an over-split is caught by the dedupe gate),
    attributed as a disclosed headless resolution. Returns (n_resolved, pending_qs)."""
    import clarify as _CQ
    md = _load_match_decisions(work)
    unsure = [g for g in grey or [] if _is_unsure((md or {}).get(g.get("pair_id")))]
    # a pair ALREADY SETTLED (possibly by the broker's own earlier answer) is never
    # re-opened by a later agent writing 'unsure' - that silently flipped a settled
    # 'same' to the headless default on a probe
    try:
        _settled = json.loads((Path(work) / "match_settled.json")
                              .read_text(encoding="utf-8-sig"))
    except Exception:
        _settled = {}
    unsure = [g for g in unsure if not _pair_answered(_settled, g)]
    if not unsure:
        return 0, []
    mode = _CQ.clarify_mode(work, cfg)
    answers = _CQ.ingest_answers(work)
    declined = _CQ.declined_ids(work)
    OPT_SAME, OPT_DIFF = "same property", "different properties"
    updates, pending = {}, []
    for g in unsure:
        pid = g.get("pair_id")
        q_id = _CQ.qid("match_unsure", str(pid), "match")
        raw = answers.get(q_id)
        a = _CQ._norm_answer(raw) if raw is not None else ""
        rejected = ""
        if a in (OPT_SAME, OPT_DIFF):
            updates[pid] = {"verdict": "same" if a == OPT_SAME else "different",
                            "reason": "broker decided (exit-13 match_unsure answer)"}
            continue
        if mode == "headless" or q_id in declined:
            updates[pid] = {"verdict": "different",
                            "reason": ("author was unsure; resolved to 'different' "
                                       "(headless/declined default, disclosed - an "
                                       "over-split is caught by the dedupe gate)")}
            continue
        if a:
            # an unrecognised answer must RE-ASK with the rejection spelled out, never
            # be swallowed (the repo standard: junk never counts) - swallowing it was a
            # probe-verified adjudicator livelock
            rejected = (f" (Your previous answer '{raw}' was not one of the options - "
                        f"answer with one of them exactly, or 'skip'.)")
        pending.append({
            "id": q_id, "kind": "match_unsure", "asked_of": "broker",
            "blocking": True, "subject": f"pair {pid}",
            "question": (f"Are these the SAME property described twice? "
                         f"(A) {_rec_brief(g.get('a') or {})} vs "
                         f"(B) {_rec_brief(g.get('b') or {})}. The reading agent "
                         f"was genuinely unsure.{rejected}"),
            "options": [OPT_SAME, OPT_DIFF],
            "why_it_matters": ("merged wrongly, one option silently disappears; "
                               "split wrongly, one building ships as two cards"),
            "if_unanswered": "they ship as two separate cards (disclosed)",
        })
    if updates:
        _mutate_decisions_file(work / "match_decisions.json", updates)
    return len(updates), pending


def _conflict_candidate(conflict: dict, label) -> dict:
    """The candidate dict a conflict's label points at, or {}."""
    for k in (conflict or {}).get("candidates") or []:
        if isinstance(k, dict) and str(k.get("label")) == str(label):
            return k
    return {}


def _conflict_default_value(conflict: dict) -> str:
    """The VALUE the precedence default ships, not its 'a'/'b' label.

    A Gaps line reading "the precedence default ('a') ships" is unreadable: the report
    carries no options list to decode the letter, so the broker cannot see what shipped."""
    v = _conflict_candidate(conflict, (conflict or {}).get("default")).get("value")
    return "the source's own value" if v in (None, "") else f"'{v}'"


def _conflict_values(conflict: dict) -> str:
    """'12 m' vs '15 m' - the disagreement itself, in the broker's terms."""
    vals = [str(k.get("value")) for k in (conflict or {}).get("candidates") or []
            if isinstance(k, dict) and k.get("value") not in (None, "")]
    return " vs ".join(f"'{v}'" for v in vals[:4]) or "two differing values"


def _conflict_where(conflict: dict) -> str:
    """Which option the conflict is on, named the way the broker knows it."""
    for k in ("cluster_key", "cluster_anchor"):
        v = str((conflict or {}).get(k) or "").strip()
        if v:
            return v.split("|")[0][:60] or "one option"
    return "one option"


def unsure_pick_questions(work: Path, cfg: dict, conflicts: list, fd) -> tuple:
    """Item 3.3 (value conflicts): an 'unsure' pick becomes a broker question
    (interactive) or keeps the precedence default, disclosed (headless/declined).
    Options are the conflict's own candidate labels with their values - the broker
    can only ever pick among stated values, never introduce one.

    MATERIALITY (B62): only a conflict that can change what the client sees is worth the
    broker's time. `clarify.field_is_material` is the test, and it is deliberately WIDER
    than "the dashboard prints it": it also covers the fields the MATCHER reads for
    identity (park, address, postcode, scheme, region...), because settling one of those
    silently can re-cluster the dataset on a later pass and move the option count. A
    disagreement on an open-captured tracker column, or any other Excel-and-ledger-only
    field, takes the precedence default here and now, recorded as a disclosed decision -
    the losing value still reaches meta.conflicts and the Gaps Report exactly as before.

    This one has to be RESOLVED at the producer rather than filtered in clarify.pending: a
    field_unsure question is `blocking:true`, so dropping it without writing a decision
    would leave field_decisions.json holding 'unsure', field_uncovered would stay True, and
    exit 10 would re-dispatch the adjudicator for ever. Suppression must always leave a
    settled value behind it."""
    import clarify as _CQ
    unsure = [c for c in conflicts or []
              if fd is not None and _is_unsure(fd.get(c.get("conflict_id")))]
    if not unsure:
        return 0, []
    mode = _CQ.clarify_mode(work, cfg)
    answers = _CQ.ingest_answers(work)
    declined = _CQ.declined_ids(work)
    updates, pending, suppressed = {}, [], []
    for c in unsure:
        cid = c.get("conflict_id")
        shown = _CQ.field_is_material(c.get("field"))
        q_id = _CQ.qid("field_unsure", str(cid), str(c.get("field") or ""))
        opts = {f"{k.get('label')}: {k.get('value')}": str(k.get("label"))
                for k in (c.get("candidates") or []) if isinstance(k, dict)}
        a_raw = answers.get(q_id)
        a = _CQ._norm_answer(a_raw) if a_raw is not None else ""
        picked = next((lbl for txt, lbl in opts.items()
                       if _CQ._norm_answer(txt) == a), None)
        # a bare-label answer ("b") or a bare-value answer ("15 m") is unambiguous too -
        # accept it rather than discarding the broker's explicit choice
        if picked is None and a:
            by_label = {_CQ._norm_answer(lbl): lbl for lbl in opts.values()}
            by_value = {_CQ._norm_answer(str(k.get("value"))): str(k.get("label"))
                        for k in (c.get("candidates") or []) if isinstance(k, dict)}
            picked = by_label.get(a) or by_value.get(a)
        if picked:
            updates[cid] = {"pick": picked,
                            "reason": "broker decided (exit-13 field_unsure answer)"}
        elif mode == "headless" or q_id in declined:
            updates[cid] = {"pick": str(c.get("default")),
                            "reason": ("adjudicator was unsure; precedence default kept "
                                       "(headless/declined, disclosed)")}
        elif not shown:
            updates[cid] = {"pick": str(c.get("default")),
                            "reason": (f"adjudicator was unsure; precedence default kept - "
                                       f"`{c.get('field')}` is neither shown on the "
                                       f"dashboard nor read by the matcher, so the answer "
                                       f"could not change what the client sees (disclosed, "
                                       f"not asked)")}
            suppressed.append({
                "id": q_id, "kind": "field_unsure", "materiality": "ledger",
                "subject": f"`{c.get('field')}` on {_conflict_where(c)}",
                "question": (f"Two sources disagree on `{c.get('field')}` "
                             f"({_conflict_values(c)}) and the adjudicator was unsure which "
                             f"is right"),
                "if_unanswered": (f"{_conflict_default_value(c)}, the value the source "
                                  f"precedence prefers; the losing value is listed under "
                                  f"Source conflicts"),
            })
        else:
            # an unrecognised answer RE-ASKS with the rejection spelled out - silently
            # falling back to precedence discarded the broker's explicit choice
            rejected = (f" (Your previous answer '{a_raw}' matched none of the options - "
                        f"answer with one of them exactly, or 'skip'.)") if a else ""
            pending.append({
                "id": q_id, "kind": "field_unsure", "asked_of": "broker",
                "blocking": True, "field": c.get("field"),
                "subject": f"`{c.get('field')}` conflict {cid}",
                "question": (f"Two sources disagree on `{c.get('field')}` and the "
                             f"adjudicator was genuinely unsure which is right. "
                             f"Which value should the card show?{rejected}"),
                "options": list(opts.keys()),
                "why_it_matters": "the losing value is disclosed, the winner ships on the card",
                "if_unanswered": (f"the precedence default "
                                  f"('{c.get('default')}') ships, disclosed"),
            })
    if updates:
        _mutate_decisions_file(work / "field_decisions.json", updates)
    # REPLACE this kind's disclosures rather than appending: a conflict_id is derived from
    # cluster membership and re-keys when clustering settles (a live run saw the set grow
    # 44 -> 78 across two exit-10 rounds), so appending would leave the Gaps Report naming
    # conflicts that no longer exist. Called even when nothing was suppressed this pass, so
    # a round that resolves everything materially clears the stale entries too.
    _CQ.note_suppressed(work, suppressed, replace_kind="field_unsure")
    return len(updates), pending


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
            cur = _index_decisions(json.loads(f.read_text(encoding="utf-8-sig")),
                                   ("pair_id", "id"))
        except Exception:
            cur = None  # malformed/half-written -> treat as absent (re-emit + exit 10)
    keep = Path(work) / "match_settled.json"
    prev = {}
    try:
        prev = json.loads(keep.read_text(encoding="utf-8-sig"))
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


SETUP_QID_SUBJECT = "stage-0 setup"


def setup_pending(cfg: dict, work: Path) -> bool:
    """Has the broker actually ANSWERED the Stage-0 form? (B63)

    THE DEFECT THIS EXISTS FOR. `intake` scaffolds a COMPLETE project.yaml on the first
    pass - client name from --client, `output.language: English`, `inputs.emails.source:
    none`, the enrichment flags - i.e. all five Stage-0 answers, pre-filled with guesses,
    written BEFORE anything tells the orchestrator to ask. (It also writes
    `clarify.mode: interactive`, which is not one of the five and not a guess: asking when
    unsure is fixed by policy.) SKILL.md
    then said to skip the form when "project.yaml already carries the answers". It always
    did. So the correct, compliant behaviour was to never ask the broker anything, and runs
    shipped English dashboards with no email ingestion and car drive-times because nobody
    was ever offered the choice. Verified on a clean probe run, and present in the shipped
    2026-08-24 build.

    So the test is no longer "are there values in the file" but "did a human confirm them":
    one explicit `setup.confirmed` flag that only the orchestrator sets, after the form.

    Declining still works and is still recorded: the headless escapes (work/clarify.SKIP_ALL
    or clarify.assume_defaults) mean "decide sensibly and disclose", which is exactly the
    scaffold's defaults, so they clear this too."""
    import clarify as _CQ
    if _CQ.skip_all(work):
        return False
    c = (cfg or {}).get("clarify") or {}
    if c.get("assume_defaults") is True:
        return False
    s = (cfg or {}).get("setup") or {}
    if isinstance(s, dict) and s.get("confirmed") is True:
        return False
    return True


def setup_handoff_text(work: Path, proj: Path) -> str:
    """The Stage-0 instruction, as an IMPERATIVE and at the FRONT of whatever carries it.

    It used to be one clause at the tail of the exit-3 interpretation paragraph, phrased as
    a question ("FIRST PASS? Present the Stage-0 setup form...") and immediately undercut by
    "no form answer feeds this round" - about 85% of the way through 1,400 characters of
    other instructions. It is now the first thing in the message, and it names the one thing
    that clears it."""
    return (
        "SETUP FIRST (Stage 0): the broker has NOT yet answered the five setup questions - "
        f"`setup.confirmed` is not true in {proj}. Present the ONE consolidated "
        "`mcp__visualize__show_widget` form from reference/setup-form.md VERBATIM (client "
        "name, enrichment extras, openrouteservice key, Outlook emails, dashboard language) "
        "as a single elicitation - never AskUserQuestion, never one question at a "
        "time; if the visualize tool is genuinely unavailable, put all five in ONE plain-text "
        "message instead. Do NOT ask about the ask mode: asking the broker when the run is "
        "unsure is fixed by policy, so `clarify.mode` is neither asked nor written from an "
        "answer. Then write their answers into that project.yaml (`client:`, "
        "`enrichment:`, `enrichment.ors_api_key`, `inputs.emails:`, `output.language`) "
        "AND set `setup.confirmed: true`. Every value already in that file "
        "is a GUESS this scaffold wrote, not an answer - do not read it as one. Nothing but "
        "`setup.confirmed: true` (or work/clarify.SKIP_ALL for a headless run with no "
        "broker to ask, which accepts the defaults as a recorded decision) clears this.")


def setup_prefix(cfg: dict, work: Path, proj: Path, connector: str = "THEN, IN THE SAME "
                 "MESSAGE: ") -> str:
    """The setup instruction as a PREFIX for whatever hand-off is going out anyway.

    Applied at EVERY exit-3 site, not just the interpretation one: a run can reach a vision
    correction round or a region-label round on its first pass, and those exit before the
    standalone setup stop further down. While the form is unanswered, every hand-off leads
    with it, so no ordering of handoffs can produce a pass that never mentions it."""
    if not setup_pending(cfg, work):
        return ""
    return setup_handoff_text(work, proj) + "\n\n" + connector


def _gaps_to_chase(canonical_path, failed_preps, photo_doubts, unreadable_inputs, yield_notes,
                   work=None) -> bool:
    """True when the Gaps Report has substantive content the broker should chase.
    Mirrors EVERY populated section deliver.gaps_report emits - per-property tbd CORE
    fields, enrichment gaps, source conflicts, unmapped tracker columns, unreadable
    inputs and photo-match doubts - so the quiet 'Done' note never steers the broker
    away from a report that has real content (P3-10).

    Including the two clarify sections (B62): an accepted default and a doubt the run
    decided not to stop for are exactly the kind of real content this predicate exists to
    point at, and on a clean run they can be the ONLY content."""
    if failed_preps or photo_doubts or unreadable_inputs or yield_notes:
        return True
    if work is not None:
        try:
            import clarify as _CQ
            _st = _CQ.load_state(work)
            if _st.get("suppressed") or _st.get("answers") or _st.get("declined"):
                return True
        except Exception:
            pass
    try:
        cj = json.loads(Path(canonical_path).read_text(encoding="utf-8-sig"))
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
    _report_media_engine()


def _report_media_engine() -> None:
    """The MEDIA capability line, beside `PDF engine:` and for the same reason - except that the
    media layer needs saying LOUDER, because its failure mode is silent by design.

    "PDF engine: native PyMuPDF - full-fidelity extraction" was true on a run whose placed-image
    geometry was nonetheless dead: the engine was fine, one of the things the media path asks it
    for was not, and every media tier answered the way it answers a source that genuinely holds
    nothing. So the run printed a confident engine line, shipped eleven cards with no site plan,
    and nothing anywhere said a capability was missing. This states each media capability as a
    PROBED fact (images.media_capabilities()), so "the deck has no site plan" and "this host
    cannot see site plans" can never again look identical.

    QUIET when everything is present (one short line, not noise); LOUD in BOTH verbosity modes
    the moment anything media-critical is unavailable, with the consequence spelled out."""
    try:
        import images as IMG
        caps = IMG.media_capabilities()
        missing = [c for c in IMG.MEDIA_CRITICAL_CAPS if not caps.get(c)]
    except Exception as e:
        print(f"media engine: UNKNOWN - the image layer could not be probed ({type(e).__name__}: "
              f"{e}); treat every missing photo/site plan in this run as unexplained.")
        return
    if not missing:
        if not QUIET:
            print(f"media engine: all media capabilities present "
                  f"(geometry via {caps.get('geometry_backend')}) - photos, galleries, page "
                  f"renders and vector site plans are all reachable.")
        return
    _COST = {
        "pillow": "no image can be decoded, cropped or compressed - EVERY card gets the placeholder",
        "renderer": "no page can be rasterised - no page renders for the interpretation agents, "
                    "and no rendered (vector) site plan",
        "geometry": "placed-image boxes are unreadable - the tier-B hero crop and the "
                    "placed-image site-plan tier are dead",
        "drawings": "page.get_drawings() is unavailable - a VECTOR site plan cannot be detected "
                    "at all",
        "text": "no page text - plan titles, site-plan labels and the spec-page guard are all blind",
    }
    print(f"media engine: DEGRADED - {len(missing)} media capability(ies) UNAVAILABLE on this "
          f"host ({', '.join(missing)}); engine {caps.get('engine')}.")
    for c in missing:
        print(f"  - {c}: {_COST.get(c, 'a media tier that needs it degrades to an honest null')}")
    print("  Every media tier degrades to an honest null, so a thin gallery or a missing site "
          "plan in this run may be THIS HOST, not the sources. The `media-harvest` gate repeats "
          "it in the scorecard; do not sign off 'no usable image' without reading it.")


def _say_orchestrator(msg: str) -> None:
    """Print a HANDOFF instruction - the machine-readable product of a terminal exit.

    ALWAYS stdout, in both verbosity modes. These lines used to go to stderr, which
    this project's own environment rule says `mcp__shell` does not surface - and
    SKILL.md makes mcp__shell the spine command, so the one line telling the
    orchestrator what to do next was invisible on the documented path. Diagnostic
    asides ("optional reader X unavailable", "image pre-warm skipped") stay on
    stderr; only the next-action instruction comes through here. (B27)"""
    print(msg)


def _render_dispatch_prompts(work: Path, jobs: list, wipe: bool = True) -> str:
    """P1 (prompts-as-files): render the canonical dispatch prompt per pending job to
    <work>/prompts/ and return the one-line handoff sentence naming them ('' when nothing
    rendered). The prompt CONTENT lives in <skill>/prompts/*.md templates + the reference
    contracts; this only bakes in the job parameters the spine already knows, so the
    orchestrator dispatches file contents VERBATIM instead of paraphrasing the contract -
    the paraphrase being the documented top error surface (the pasted-short field list, the
    derived output filename). BEST-EFFORT BY DESIGN: any failure prints one note and returns
    '', and the run behaves exactly as before this existed."""
    try:
        import prompts_render as _pr
        files = _pr.write_prompts(work, jobs, wipe=wipe)
    except Exception as e:
        print(f"  (prompt rendering unavailable: {e})", file=sys.stderr)
        return ""
    if not files:
        return ""
    return (f" Rendered dispatch prompts: {work / 'prompts'} - ONE FILE PER PENDING JOB; "
            f"dispatch each as an isolated sub-agent whose prompt is that file's contents "
            f"VERBATIM (append run-specific facts only under its 'Run context' heading, "
            f"never edit above it).")


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
    ap.add_argument("--project", default="",
                    help="RECOMMENDED. The project folder. Derives the three-folder layout: "
                         f"inputs = '<root>/{INPUT_DIRNAME}', work dir = "
                         f"'<root>/{WORK_DIRNAME}', deliverables = '<root>/{OUTPUT_DIRNAME}'. "
                         "The three folders are created if missing. --folder/--work/--out-dir "
                         "each override their slot.")
    ap.add_argument("--folder", default="",
                    help="the inputs folder (overrides the --project default). Required when "
                         "--project is not given.")
    ap.add_argument("--work", default="",
                    help="the work directory - every internal pipeline artefact (overrides the "
                         "--project default). Required when --project is not given.")
    ap.add_argument("--out-dir", dest="out_dir", default="",
                    help="where the four client-facing deliverables are written. Defaults to "
                         f"'<project>/{OUTPUT_DIRNAME}' with --project, and to "
                         f"'<work>/{LEGACY_OUTPUT_SUBDIR}' on a legacy --folder/--work run.")
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
    # STAGE CONTROL (A2). Sits beside --resume/--no-resume because it answers the neighbouring
    # question: --resume asks "is this output still current?", these ask "can the correction I
    # just made even REACH this stage?". Independent of --resume by design (see _stage_skipped).
    ap.add_argument("--from", dest="from_stage", default="", metavar="STAGE",
                    help="put every stage BEFORE this one out of scope, even under "
                         "--no-resume: each reuses its existing output instead of re-deriving "
                         "it, so the work dir must already hold it. The cut is applied by each "
                         "stage's own skip guard, so an out-of-scope stage still runs whatever "
                         "sits outside that guard: the extract body (readers, clustering, the "
                         "interpretation manifest, the exit-3/9/10 handoffs) runs on every "
                         "pass and only its per-tracker record derivation is cut. On a warm "
                         "work dir this is therefore behaviourally the same as the default "
                         "resume; the measurable saving is under --no-resume. What it does "
                         "guarantee is REACH: a stage put out of scope cannot be changed by "
                         "this pass. Valid: "
                         + ", ".join(STAGE_ORDER)
                         + ". The pre-build gates, the post-build gates, the freeze and the QA "
                           "window ALWAYS run, whatever is named here.")
    ap.add_argument("--only", dest="only_stages", default="", metavar="STAGES",
                    help="run ONLY these stage(s) (comma-separated); every other stage is put "
                         "out of scope, even under --no-resume, on exactly the same terms as "
                         "--from (including the extract-body caveat). Same vocabulary and the "
                         "same always-run gates.")
    # THE ESCAPE HATCH for the up-front correction-file validation (exit 16). The startup check
    # converts what USED to be a silently-ignored malformed entry into a hard refusal to start,
    # and a new guard with no way past it breaches the rule that new behaviour must default to
    # today's behaviour. So the refusal keeps the default (it is the safe side: an entry that
    # does nothing means the run ships data the operator believes they corrected), and this flag
    # restores the OLD behaviour exactly - each faulty entry is reported, then ignored, and the
    # stages that consume the file carry on as they always did. It exists for the one real case:
    # a large correction file with one stale entry, a deadline, and a broker who needs the
    # dashboard now. It is NOT a fix, so the faults are still printed in full and the run is
    # still told, loudly, that those entries do nothing.
    ap.add_argument("--allow-invalid-corrections", dest="allow_invalid_corrections",
                    action="store_true",
                    help="do NOT refuse to start on an invalid entry in work/overrides.json or "
                         "work/repairs.json (exit 16). Every fault is still printed; the faulty "
                         "entries are then IGNORED, as they were before the startup check "
                         "existed. Use only to ship past a known-stale entry - it corrects "
                         "nothing.")
    return ap


def _resolve_stage_control(args) -> tuple:
    """(from_stage, only_stages) validated against STAGE_ORDER, or a clear exit on a typo.

    A typo must NOT degrade to "run everything" or to "run nothing": both are silent, and a
    silent stage-control flag is exactly the class of defect this file keeps paying for (a
    correction that quietly never applied). So an unrecognised name stops the run before any
    stage does work, and NAMES the valid spellings - the vocabulary has a space in "folder
    scan" and a colon in "gates:pre", so "guessing it" is not reasonable to ask of an operator.

    Exit 2, the code this spine already uses for "I cannot start - the invocation does not tell
    me where/what to run" (see _resolve_layout). It is not a data or gate failure, so it must
    not borrow 5 or 6."""
    valid = ", ".join(STAGE_ORDER)
    frm = str(getattr(args, "from_stage", "") or "").strip()
    only_raw = str(getattr(args, "only_stages", "") or "").strip()
    only = [s.strip() for s in only_raw.split(",") if s.strip()] if only_raw else []
    bad = ([("--from", frm)] if frm and frm not in STAGE_ORDER else []) \
        + [("--only", s) for s in only if s not in STAGE_ORDER]
    if bad:
        for flag, name in bad:
            print(f"I don't know a stage called '{name}' ({flag}).")
        print(f"The stages, in order, are: {valid}.")
        sys.exit(2)
    return frm, frozenset(only)


def _resolve_quiet(args) -> bool:
    """Quiet is the DEFAULT; `--verbose` opts out and WINS over an explicit `--quiet`.

    `--quiet` survives as an accepted no-op rather than being removed: SKILL.md and
    ~35 `_run_spine` calls in extract_test.py still pass it, and deleting the option
    would turn argparse's SystemExit(2) into a wall of reds for the wrong reason. (B27)"""
    return not bool(getattr(args, "verbose", False))


def _resolve_layout(args):
    """(inputs, work, out_dir) from --project and/or the explicit overrides.

    THE ONE PLACE the three-folder convention is decided, so every helper below keeps
    taking the same `--work <path>` it always took - the work dir simply has a
    broker-legible NAME now. Two shapes, both supported for ever:

      --project "<root>"                -> "<root>/1. Input", "<root>/2. Work Files",
                                           "<root>/3. Output"   (the RECOMMENDED default)
      --folder "<in>" --work "<w>"      -> exactly those, delivering to "<w>/deliverables"
                                           (the LEGACY shape - unchanged, never broken)

    Any slot may be overridden explicitly, so a half-migrated project ("--project <root>
    --folder <old inputs dir>") works too. Raises ValueError with a plain-English sentence
    when neither shape is satisfied - never a bare argparse usage dump."""
    proj = str(getattr(args, "project", "") or "").strip()
    fold = str(getattr(args, "folder", "") or "").strip()
    work = str(getattr(args, "work", "") or "").strip()
    outd = str(getattr(args, "out_dir", "") or "").strip()
    root = Path(proj).resolve() if proj else None
    if not proj and not (fold and work):
        raise ValueError(
            "I need to know where the project is. Pass --project \"<project folder>\" (it uses "
            f"'{INPUT_DIRNAME}', '{WORK_DIRNAME}' and '{OUTPUT_DIRNAME}' inside it), or pass "
            "--folder and --work explicitly.")
    inputs = Path(fold).resolve() if fold else (root / INPUT_DIRNAME)
    workd = Path(work).resolve() if work else (root / WORK_DIRNAME)
    if outd:
        out = Path(outd).resolve()
    elif root is not None:
        out = root / OUTPUT_DIRNAME
    else:
        out = workd / LEGACY_OUTPUT_SUBDIR   # legacy shape: exactly where it always was
    return inputs, workd, out


def main() -> None:
    ap = _build_parser()
    args = ap.parse_args()
    global QUIET, RESUME, FROM_STAGE, ONLY_STAGES
    QUIET = _resolve_quiet(args)
    RESUME = args.resume
    # STAGE CONTROL, resolved and PROVED SAFE before any stage can be skipped (A2). The
    # assertion runs on every invocation, including the default one where both flags are
    # empty - a guard that only executes on the unusual path is a guard nobody tests.
    FROM_STAGE, ONLY_STAGES = _resolve_stage_control(args)
    _assert_stage_control_safe()
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

    try:
        folder, work, out_dir = _resolve_layout(args)
    except ValueError as e:
        print(str(e))
        sys.exit(2)
    # The three-folder layout is SET UP here, not by the orchestrator: a `--project` run
    # creates the folders it names so "put your files in 1. Input" is the only instruction
    # a broker ever needs. Creating an empty inputs folder is deliberate - intake then
    # exits 2 with "no readable property sources", which names the folder to fill.
    for _d in (folder, work, out_dir):
        try:
            _d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # an unwritable path is diagnosed by the stage that needs it, in plain English
    extract = work / "extract"
    extract.mkdir(parents=True, exist_ok=True)
    # ARM THE TIMING WRITER. The EARLIEST point at which there is somewhere to write: `work`
    # exists, and no stage has run yet, so every subsequent exit - including the handoff exits,
    # which are the interesting ones - passes through the atexit handler. Registered exactly
    # once, and only here, so importing run.py (an eval, a helper) writes nothing anywhere. (A0)
    _register_timings(work)
    # Where the deliverables went, recorded IN the work dir. The out dir is no longer a fixed
    # `<work>/deliverables`, so anything that needs to find the delivered artefacts from the
    # work dir alone (gate_runner's QA artefact fingerprint) reads this instead of guessing.
    try:
        (work / OUTPUT_POINTER).write_text(str(out_dir), encoding="utf-8")
    except OSError:
        pass
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

    # A4: VALIDATE EVERY CORRECTION FILE UP FRONT, AND REPORT EVERY FAULT IN ONE PASS.
    #
    # An invalid correction used to be discovered only when its own stage ran - overrides at
    # merge, repairs at the repairs stage - and each stage reports only its own file, first
    # fault-set first. So an operator who wrote three type errors across two files paid three
    # full passes to learn about them, one at a time, each pass costing an extract + merge.
    #
    # REPORTING EVERYTHING AT ONCE IS THE POINT, NOT A NICETY. It is what makes BATCHING
    # corrections the default rather than a discipline: if the cost of a fault is one full pass
    # each, the rational operator writes one correction at a time and verifies it, which is the
    # slowest possible way to use both channels. If the cost is one startup, they write the
    # whole batch. That is a behaviour change, not a message change - which is why this block
    # never stops at the first fault and never prefers one file over the other.
    #
    # Reuses the EXISTING loaders, which already return structured error lists and already
    # refuse everything that could produce an incomplete ledger row (merge.load_overrides,
    # repairs.load). No new validation logic here: a second, divergent opinion about what a
    # valid correction is would be worse than the delay it saves.
    import repairs as _repairs_mod   # imported inside main(), as every helper here is
    _corr_faults: list = []       # (file name, one plain fault line)
    _corr_files: set = set()      # which CHANNELS faulted -> which re-entry hint is honest
    for _cf, _chan, _loader in (
            (work / "overrides.json", "premerge",
             lambda p: merge.load_overrides(p, extra_fields=_record_field_names(work))),
            # THE REPAIR SCREEN IS WIDENED THE SAME WAY ITS REAL CONSUMER WIDENS IT. Called
            # bare - as it was - this refused a correct, attributed repair on an off-spec key
            # at STARTUP, with exit 16 and a remedy ("fix or DELETE it in place") that turns
            # the refusal into a deleted correction. `_repair_screen_fields` carries the whole
            # incident and decides what the screen does when canonical does not exist yet.
            (work / "repairs.json", "repair",
             lambda p: _repairs_mod.load(
                 p, extra_fields=_repair_screen_fields(work, p, _repairs_mod)))):
        if not _cf.exists():
            continue  # an absent correction file is the NORMAL state, never a fault
        try:
            _entries, _errs = _loader(_cf)
        except Exception as _ce:
            # both loaders document "NEVER raises", but a correction file is operator-authored
            # and this runs before anything else: an unreadable one must be REPORTED as such,
            # not crash the run with a traceback the operator cannot act on.
            _entries, _errs = [], [f"could not be read at all ({type(_ce).__name__}: {_ce})"]
        for _err in (_errs or []):
            _corr_faults.append((_cf.name, str(_err)))
            _corr_files.add(_chan)
    if _corr_faults:
        _corr_names = ", ".join(sorted({_f for _f, _ in _corr_faults}))
        _bypass = bool(getattr(args, "allow_invalid_corrections", False))
        # ONE header, two truthful halves. The bypass path must not print "fix them together and
        # re-run once" over a run that is about to carry on regardless: an instruction the run
        # itself is ignoring teaches the operator to ignore the next one too.
        print(f"{'Warning' if _bypass else 'I cannot start'}: {len(_corr_faults)} problem(s) in "
              f"your correction file(s). Every one is listed below"
              + (":" if _bypass else " - fix them together and re-run once."))
        for _fn, _why in _corr_faults:
            print(f"  [{_fn}] {_why}")
        if _bypass:
            # THE ESCAPE HATCH (--allow-invalid-corrections). Restores the pre-check behaviour
            # exactly: the faults are named, the faulty entries are ignored, the run proceeds.
            # Printed unconditionally and in the operator's own words, because the whole risk of
            # this flag is that someone passes it once and forgets it is on.
            print(f"Continuing anyway because --allow-invalid-corrections was passed. Those "
                  f"{len(_corr_faults)} entr(y/ies) will be IGNORED, so anything they were "
                  f"meant to correct SHIPS UNCORRECTED. This flag fixes nothing.")
            _say_orchestrator(
                f"(orchestrator: {len(_corr_faults)} invalid correction entr(y/ies) across "
                f"{_corr_names} were BYPASSED by --allow-invalid-corrections - not exit 16. "
                f"They apply nothing. Say so to the broker, and note it in the Gaps Report "
                f"hand-off; drop the flag once the entries are fixed.)")
        else:
            print("Each of those entries does NOTHING until it is fixed, so the run would ship "
                  "data you believe you had corrected. Nothing has been changed.")
            # The cheapest honest re-entry: only when EVERY fault is in the repair channel can
            # the earlier stages be skipped. A faulty override is consumed by merge, so it cannot.
            print(_reentry("repair" if _corr_files == {"repair"} else "premerge"))
            # EXIT 16, NOT 5. Exit 5 has a MAPPED ACTION in SKILL.md, and both halves of it are
            # wrong for this path: it says read gate1_scorecard.md (which does not exist yet -
            # this exit fires at STARTUP, the gates run far later) and record the correction in
            # work/overrides.json - i.e. APPEND to the very file being rejected. An orchestrator
            # following its contract literally appends, re-runs, is refused again, and appends
            # again: an unbounded loop authored by the exit code, with each round adding an
            # entry. A mapped action must be executable from the state the exit actually leaves
            # behind, so this needs a code of its own whose one action is FIX, never APPEND.
            #
            # Routed through _exit_round_trip like every other correction-expecting exit, so a
            # repeated identical handoff is DIAGNOSED rather than looping silently: the streak
            # is recorded, the exact unmet predicates are persisted to
            # work/pending_diagnosis.json and printed from the second round, and past
            # ATTEMPT_WARN the run says plainly that it is stuck. The direct `sys.exit` this
            # replaces had no brake of any kind - which is precisely why the append loop above
            # could run forever without anything on screen saying so.
            _say_orchestrator(
                f"(orchestrator: {len(_corr_faults)} invalid correction entr(y/ies) across "
                f"{_corr_names} - exit 16. Every fault is printed above in ONE pass. FIX the "
                f"named entries IN PLACE in the named file, then re-run the SAME command. Do "
                f"NOT add new entries, and do NOT read gate1_scorecard.md - the gates have not "
                f"run. If a faulty entry is stale, DELETE it. To ship past them knowingly, "
                f"re-run with --allow-invalid-corrections; they then apply nothing.)")
            _exit_round_trip(work, 16, _attempts, "fixing the invalid correction entries",
                             diagnosis=[f"{_fn}: {_why} - this entry is rejected by the loader "
                                        f"and applies nothing; FIX or DELETE it in place"
                                        for _fn, _why in _corr_faults])

    # Stage 0 - intake
    proj = work / "project.yaml"
    _stage("folder scan")
    step("Scanning the folder")
    # work/intake_clusters.json is the orchestrator's LLM-refined filename->region label
    # cache; including it in the resume inputs means WRITING the cache invalidates a stale
    # inventory.json/project.yaml so the next pass re-clusters from the cache (then keeps
    # the confirmed project.yaml). Its absence forces the deterministic regex - unchanged.
    # exclude_dir=work (T1b): `folder` is walked RECURSIVELY here, and a work dir placed inside
    # the inputs folder is the natural layout - so without this every artefact the run wrote
    # (canonical, the scorecards, the ledger, the per-property views) is an input newer than
    # inventory.json and the folder scan can NEVER be current. `intake_clusters.json` is passed
    # as an explicit FILE input and so is still counted: only the directory walk is filtered,
    # which is the whole point - the run's own outputs are excluded, its declared inputs are not.
    # This is the SAME exclusion intake.discover(exclude_dir=...) already applies to its walk;
    # the predicate simply never got it. ONLY this call site passes it.
    if _is_current(work / "inventory.json", [folder, work / "intake_clusters.json"],
                   stage="folder scan", exclude_dir=work) and proj.exists():
        _resumed("folder scan")
    else:
        call(intake, folder, "--out-dir", work, "--client", args.client)
    inv = json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
    # SEAM-3: a cluster label's close-call NOTE (the label agent's one-line reasoning, kept by
    # intake as inventory.json["cluster_label_notes"]) lands in the Gaps Report's "Noted, not
    # put to you" through clarify's suppressed ledger, so the reasoning behind a routing name
    # is disclosed rather than lost. `materiality: ledger` is set on the entry itself, which
    # `clarify.materiality` honours ahead of any kind table, because the note cannot change a
    # card: labels are routing names, never evidence. `replace_kind` re-keys a re-labelled
    # stem instead of leaving its old note beside the new one. No deliver.py change needed.
    _cl_notes = [n for n in (inv.get("cluster_label_notes") or []) if isinstance(n, dict)]
    if _cl_notes:
        try:
            import clarify as _CQn
            _CQn.note_suppressed(work, [{
                "id": _CQn.qid("cluster_label_note",
                               f"{n.get('stem')}|{n.get('region')}|{n.get('country')}", ""),
                "kind": "cluster_label_note", "blocking": False, "materiality": "ledger",
                "subject": f"cluster label '{n.get('region')}'"
                           + (f" ({n.get('country')})" if n.get("country") else ""),
                "question": str(n.get("note") or "").strip(),
                "if_unanswered": "the label is a routing name only; no card field was set from it",
                "source_file": str(n.get("stem") or ""),
            } for n in _cl_notes], why=_CQn.WHY_LEDGER, replace_kind="cluster_label_note")
        except Exception as _e:
            print(f"(cluster-label notes not recorded for the Gaps Report: "
                  f"{type(_e).__name__}: {_e})", file=sys.stderr)
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
                have_sha = json.loads(cache.read_text(encoding="utf-8-sig")).get("_en_sha")
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
                    "keep the {area}/{unit}/{client} placeholders (hero_title_html carries "
                    "{client}, the client name, and a separator in front of it if your "
                    "language wants one), the ONE <em>...</em> pair in hero_title_html, the "
                    "&amp;/&lt;/&gt; HTML entities, any "
                    "leading glyph (e.g. the '●' bullet), and the invariants CBRE / OSRM / "
                    "BREEAM / HGV / PPS / EU27 / REIT / km verbatim. Do NOT translate DATA or the "
                    "unknown sentinel (normalize.BLANK). Add a top-level \"_en_sha\":\"" + want_sha + "\" key, "
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
            _pl = _render_dispatch_prompts(work, [
                ("translate-chrome", None,
                 {"LANGUAGE": lang, "REQUEST_PATH": str(request),
                  "CACHE_PATH": str(cache), "SKIP_PATH": str(skip)})])
            if QUIET:
                print(f"'{lang}' isn't one of the built-in dashboard languages, so I need it "
                      f"translated once. {_stale_quiet}I've written what to translate to "
                      f"{request}.{_pl}")
            else:
                print(f"\nLANGUAGE FALLBACK NEEDED: '{lang}' ({code}) is supported but not "
                      f"bundled{_stale_orch}. Dispatch a translation sub-agent: translate the "
                      f"strings in {request} to {lang}, save the flat {{key:value}} (+ "
                      f"\"_en_sha\":\"{want_sha}\") to {cache}, then re-run the SAME command. "
                      f"(Or `type nul > {skip}` to fall back to English.) Blind-verify it as "
                      f"G-i18n before shipping.{_pl}")
            _exit_round_trip(work, 11, _attempts, "a dashboard-language translation",
                             diagnosis=[
                                 f"chrome translation to '{lang}' ({code}) pending: {cache} is "
                                 + ("STALE (its _en_sha does not match the current English "
                                    "baseline)" if stale else "missing")
                                 + f"; write the flat map with \"_en_sha\":\"{want_sha}\" there, "
                                   f"or drop {skip} to decline"])

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
    _stage("extract")
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
    # raster path.
    #
    # B65 - IT MUST BE PERSISTED. This set used to be derived from the stubs on disk and the
    # stubs were deleted in the same loop, so the escalation survived exactly zero passes.
    # Combined with photo-match (below) taking the escalated deck as a "textless photo of a
    # known property" and correctly returning `unrelated`, the run livelocked: text reader ->
    # stub -> photo-match -> unrelated -> text reader, and the only way out was hand-writing a
    # stub back into work/extract/, a directory the docs correctly call derived and forbid
    # editing. The file is still self-clearing: an entry is dropped the moment that deck's
    # interpretation output exists, so it can never wedge in the other direction either.
    force_raster: set = set(_load_force_raster(work))
    _force_raster_before = set(force_raster)
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

    # SCOPE, DECIDED BY THE USER, APPLIED BEFORE THE EXPENSIVE STEP. An answered master list
    # (work/master_list.json, the "master list" stage below) names the brochure clusters the
    # user struck off. Those decks are never prepped, never rendered and never dispatched to a
    # reader agent - which is the entire economic argument for putting the sheet here rather
    # than after the merge, where the Kapdaa run's source-authority question effectively asked
    # the same thing and asked it once every deck had already been read. Empty on the first
    # pass and on a headless run, so both behave exactly as they did before this existed.
    import master_list as _ML
    _ml_skip_clusters = _ML.excluded_cluster_labels(work)
    for region, cl in inv["clusters"].items():
        if region in _ml_skip_clusters:
            if not QUIET:
                print(f"  ({region}: you marked it No on the master list - its deck(s) are not "
                      f"read; it is named in the Gaps Report)")
            continue
        # ABSENCE, NOT A SENTINEL (F7). This used to mint the two-question-mark placeholder,
        # which then travelled into the deck entry and the reader prompt. Measured on a live run:
        # five of seven readers said, unprompted, that they had to derive the country themselves
        # because they were handed it, and across seven decks that produced three different
        # outcomes plus one broker question. An absent key is unambiguous; a placeholder is a
        # value every downstream reader has to recognise and reason about.
        country = cl.get("country") or ""
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
            _done = _vision_supersedes(work, region, src.name) or has_vision
            if src.name in force_raster and _done:
                # the raster pass has since written real records: the escalation is SATISFIED,
                # so retire it. Without this the persisted set would force a re-read forever.
                force_raster.discard(src.name)
            must_raster = src.name in force_raster
            if not must_raster and _done:
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

    if force_raster != _force_raster_before:
        _save_force_raster(work, force_raster)

    # xlsx: a property tracker contributes records; a questionnaire contributes the
    # client's requirements (size/must-haves) -> canonical.meta.requirements
    requirements: dict = {}
    yield_notes: list[str] = []  # extraction-yield findings (thin parse of a rich sheet)
    link_note_ix: set[int] = set()  # which yield_notes are linked-source lines (B23):
    # they go into the report in full but collapse to a COUNT on stdout. Indices, not a
    # string match, so the report's byte order and content are untouched.
    interpret_trackers: list = []  # tracker sheets OFFERED to the mapping sub-agent (exit 3)

    def _tracker_struct_hash(structs) -> str:
        """sha1[:8] over the deterministically-serialised tracker SCHEMA - sheet names, headers
        and unmapped_headers, and nothing else (see `_tracker_map_key` for what is deliberately
        excluded and why). A re-export with cosmetic byte/mtime changes but the same columns
        hashes the same, so the cached LLM map (and thus the records + ledger) is byte-stable
        on resume."""
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
        # THE TRACKER-MAP CODE STAMP (A21b), computed ONCE for the whole loop rather than per
        # spreadsheet: it is a digest of the same one file every time, and `_code_stamp` writes
        # a marker in the work dir (`_write_if_changed`, so an unchanged closure never churns
        # the mtime). Read back as the VALUE, not used as an mtime input, because the tracker
        # map's key is a hash payload rather than a resume-input list - the same code identity
        # merge/build/deliver already carry, expressed in the shape this cache uses.
        _xl_code = ""
        try:
            _xl_code = _code_stamp(work, "trackermap",
                                   [HERE / "extract_xlsx.py"]).read_text(encoding="utf-8-sig").strip()
        except Exception:
            # A stamp we cannot compute must never silently become "no code component" for a
            # cache that would then look settled: fall back to a literal that CANNOT match a
            # real digest, so the map is re-asked rather than wrongly reused.
            _xl_code = "code-stamp-unavailable"
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
                # SCHEMA alone is a stable cache key, so region/country are empty here.
                slug = re.sub(r"[^A-Za-z0-9]+", "_", str(Path(xl).with_suffix("")))[:40].strip("_") or "file"
                fh = _hl.sha1(str(xl).encode("utf-8")).hexdigest()[:8]
                # NARROWED to the schema (A21): hashing the whole `structs` folded the greedy
                # sample selection into the key, so one edited data cell re-opened a settled
                # column map. `_tracker_map_key` carries the reasoning and the trade-off.
                # PLUS the extractor code stamp (A21b): the schema alone cannot see an alias-table
                # change that RE-POINTS an already-mapped header at a different field - headers,
                # sheets and unmapped list all stay identical while the dictionary underneath the
                # settled map now disagrees with it. A PRE-EXISTING hole the narrowing merely
                # exposed (the data-derived members used to churn the key often enough to re-ask
                # by accident), now guarded explicitly, the same way merge/build/deliver are.
                ihash = _tracker_struct_hash([{"region": "", "country": ""},
                                              _tracker_map_key(structs, code=_xl_code)])
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
                        cached = json.loads(f.read_text(encoding="utf-8-sig"))
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
            if _is_current(out, _xl_inputs, stage="extract"):
                _resumed(f"{Path(xl).name} extract")
            else:
                _extra = []
                if colmap_arg:
                    _extra += ["--colmap", colmap_arg]
                if colmap_verify_arg:
                    _extra += ["--colmap-verify", colmap_verify_arg]
                call(extant["extract_xlsx"], xl_src, *_extra, "--out", out, check=False)
            try:
                payload = json.loads(out.read_text(encoding="utf-8-sig"))
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
                    _flatl = lambda hs: [" ".join(str(h).split()) for h in (hs or [])]
                    _unmapped = _flatl(hr.get("unmapped_headers"))
                    _openh = _flatl(hr.get("open_captured_headers"))
                    _metah = _flatl(hr.get("meta_captured_headers"))
                    _skiph = _flatl(hr.get("skipped_headers"))
                    _parts = [f"{hr.get('mapped_columns')}/{hr.get('populated_columns')} "
                              f"populated columns mapped"]
                    if _openh:
                        _parts.append(f"read as open fields: {', '.join(_openh)}")
                    if _metah:
                        _parts.append("read to record notes (not client-shown): "
                                      + ", ".join(_metah))
                    if _skiph:
                        _parts.append(f"skipped (ordinal/link-text): {', '.join(_skiph)}")
                    if _unmapped:
                        _parts.append(f"NOT READ: {', '.join(_unmapped)}")
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]{tag}: " + "; ".join(_parts))
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
                # a coordinate cell the extractor REFUSED to split (no assignment of the
                # two numbers made a valid pin) - no coordinate shipped for that row, and
                # the refusal is disclosed so the broker can supply the real pin
                if hr.get("coord_unparsed"):
                    _bad = "; ".join(
                        f"{d.get('locator')}: '{' '.join(str(d.get('value')).split())}' "
                        f"under '{' '.join(str(d.get('header')).split())}'"
                        for d in hr.get("coord_unparsed", []))
                    yield_notes.append(
                        f"{Path(xl).name} [{hr.get('sheet')}]: coordinate cell(s) could not "
                        f"be split safely - no pin shipped for those rows; confirm the "
                        f"coordinates ({_bad})")
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
        _prior_unreadable = json.loads((work / "unreadable.json").read_text(encoding="utf-8-sig"))
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
        _unclassified = (json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
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

    # ======================================================================= MASTER LIST ===
    # THE ONE POINT IN THE RUN WHERE THE USER DECIDES SCOPE.
    #
    # Everything above this line is cheap: the tracker rows a dictionary/LLM column map parsed,
    # and the email bodies an agent read. Everything below it is expensive: one reader agent per
    # brochure deck, vision on the raster ones, then matching, merging, enrichment and a build.
    # Before this stage existed the run decided what to build entirely on its own and the broker
    # found out by reading the FINISHED dashboard - the Kapdaa run's defect in one sentence. The
    # one question that does ask a human which source governs the longlist, the exit-13
    # source-authority question, is asked after merging, which is after every deck has already
    # been read and after the run has formed the opinion the question is then phrased in terms
    # of. Both costs are paid here instead, once, on a sheet.
    #
    # It is a STOP, not a question with a default. Interactive is fixed by policy (the ask-mode
    # question has been removed from the setup form), so the sheet is the default path and the
    # only bypass is an explicit headless run, which includes everything and discloses that it
    # did in the Gaps Report.
    #
    # ONE BOUNDARY, AND WHAT ITS SEGMENT COVERS. The stage opens here and closes at `merge`, so
    # the deck preparation and the exit-3 reader dispatch below are timed against "master list"
    # rather than against "extract". That is not a mislabel, it is the honest attribution: the
    # only reason that work costs what it costs is which rows the sheet let through, and the
    # whole argument for this stage is the prep that DOESN'T happen for the rows it stopped.
    # Re-opening "extract" for the second half would give the vocabulary two boundaries for one
    # stage, which is what makes the timing log's segments ambiguous (evals/stage_control_test).
    _stage("master list")
    _ml_auto = {}
    # SCOPE ALREADY SETTLED UPSTREAM (project.yaml `master_list: {mode: external}`).
    #
    # A wrapper skill can own this decision before the spine is ever invoked - kato-longlist does,
    # at its own step 2.5, with its own workbook, and it then generates this project.yaml and this
    # inputs folder FROM the rows that survived. Firing exit 17 there would put a second sheet in
    # front of the same operator, listing the same options they just finished striking off, and
    # nothing on it they have not already decided. A gate that visibly re-asks an answered question
    # is answered "Yes to everything" from the second time onwards, and then it protects nothing on
    # the run where it would have mattered.
    #
    # It DECLINES the stop and does nothing else, deliberately. No master_list.json is written, so
    # no consumer can read one: no derived source authority (the exit-13 question is asked exactly
    # as it was before this stage existed), no `same` seeding into match_decisions.json, no deck
    # skipped. One line in the Gaps Report says where scope was settled, and that is the entire
    # difference from the pre-master-list spine. Absent, misspelt or unparseable means interactive.
    _ml_external = _ML.external_scope(cfg)
    if _ml_external:
        try:
            _ML.write_external(work, _ml_external)
        except OSError:
            pass  # the disclosure is best-effort; declining the stop is not conditional on it
        if not QUIET:
            print(f"  (master list: settled upstream, not asked here - "
                  f"{_ml_external['confirmed_by']})")
    try:
        _ml_by_file: dict = {}
        for _f in sorted(extract.glob("*.json")):
            for _i, _r in enumerate(_load_records(_f)):
                if isinstance(_r, dict) and not _r.get("unreadable"):
                    _ml_by_file.setdefault(
                        str((_r.get("__meta") or {}).get("source_file") or _f.name), []).append(_r)

        def _first_page_text(p) -> str:
            """The deck's FIRST PAGE text, and only that.

            The cheapest evidence that exists before the read: enough for a human to recognise
            a scheme on the sheet, and explicitly not data - nothing derived here reaches a
            card, and the row's own note says so. A PPTX or a textless raster yields '', which
            is correct: the row then shows its filename-derived label and the user judges it on
            that, rather than on a number the run made up from a cover page it could not read.
            """
            try:
                import extract_pdf as _xp
                blocks = _xp.font_grouped_blocks(p) or []
            except Exception:
                return ""
            return "\n".join(str(b.get("text") or "") for b in blocks
                             if int(b.get("page") or 0) == 1)[:4000]

        # The enumeration itself is the only expensive thing here (a first-page text read per
        # deck) and it is also what writes master_candidates_auto.json into the work dir, so an
        # external-scope run skips it outright rather than building a sheet nobody will be shown.
        # `_ml_auto` stays {} and every branch below it is then inert by construction.
        _ml_auto = ({} if _ml_external else
                    _ML.build_auto(work, _ml_by_file, inv.get("clusters") or {}, folder,
                                   _first_page_text, emails=inv.get("emails") or [],
                                   email_attachments=inv.get("email_attachments") or []))
    except Exception as _e:
        # BEST-EFFORT ENUMERATION, DELIBERATE HARD STOP ONLY WHEN IT SUCCEEDS. A crash while
        # inventorying candidates must not wedge a run behind a sheet that cannot be built; the
        # run then behaves exactly as it did before this stage existed and says so.
        print(f"  (master list not built: {_e} - the run continues with every option in scope)",
              file=sys.stderr)
    _ml_rows = (_ml_auto or {}).get("rows") or []
    # --from/--only put the scope decision OUT OF SCOPE: whatever the user already answered
    # stands, and the stop is not re-opened. A re-entry shortcut that re-asked the broker for a
    # decision they had already taken would be a shortcut nobody uses twice.
    if _stage_skipped("master list"):
        _resumed("master list")
        _ml_rows = []
    if _ml_rows:
        _ml_hash = str(_ml_auto.get("input_hash") or "")
        if _ML.is_answered(work, _ml_hash):
            _resumed("master list")
            _ml_state = _ML.load_answers(work)
            if not QUIET:
                _c = _ml_state.get("counts") or {}
                print(f"  (master list: answered - {_c.get('included', '?')} option(s) in, "
                      f"{_c.get('excluded', '?')} out"
                      + (" [headless: everything included]" if _ml_state.get("skipped") else "")
                      + ")")
        else:
            import clarify as _CQ_ML
            if _CQ_ML.clarify_mode(work, cfg) == "headless":
                _ML.write_headless(work, _ml_auto,
                                   "headless run (work/clarify.SKIP_ALL or "
                                   "clarify.assume_defaults) - nobody to put the sheet to, so "
                                   "every option found was included")
                print("NOTE: headless run - the master list was NOT put to anyone and every "
                      f"option found ({len(_ml_rows)}) is in scope. Disclosed in the Gaps "
                      f"Report.")
            else:
                _ml_pl = _render_dispatch_prompts(work, [
                    ("master-list", None,
                     {"AUTO_PATH": str(work / _ML.AUTO_CANDIDATES),
                      "OUTPUT_PATH": str(work / _ML.MODEL_CANDIDATES),
                      "EMAIL_NOTE": (f"{len(inv.get('emails') or [])} .msg/.eml file(s) in "
                                     f"{folder}" if inv.get("emails")
                                     else "no email files in this run - skip that half")})])
                _n_deck = sum(1 for r in _ml_rows if r.get("source_type") == "Brochure")
                _ml_msg = (
                    f"MASTER LIST: {len(_ml_rows)} candidate option(s) found "
                    f"({len(_ml_rows) - _n_deck} from trackers/emails, {_n_deck} brochure "
                    f"cluster(s)). The USER decides which are built, before the decks are read. "
                    f"Do all four, in order: (1) dispatch the rendered master-list prompt to add "
                    f"the email-only rows and adjudicate the duplicate groups -> "
                    f"{work / _ML.MODEL_CANDIDATES}; (2) run "
                    f"`python helpers/master_list_build.py --work \"{work}\"`; (3) give the user "
                    f"{work / _ML.WORKBOOK} and WAIT - they set Include? to Yes or No on every "
                    f"row and write anything the run must know in 'Your Run notes for the AI'. "
                    f"The column ships BLANK and the builder blanks it on every build: do NOT "
                    f"fill it in for them, do NOT infer it from the duplicate groups and do NOT "
                    f"copy the Brochure? column across - a pre-answered sheet passes the "
                    f"read-back with nobody having decided anything; (4) run "
                    f"`python helpers/master_list_read.py --work \"{work}\"` and re-run the same "
                    f"command. The read-back REFUSES (exit 2) on any row that is not Yes or No "
                    f"and names them.{_ml_pl}")
                _ml_msg = _handoff_once(work, 17, _attempts, "master list scope decision",
                                        _ml_msg, tail=_ml_pl)
                if QUIET:
                    print("I have found every option in your files. Before I read the brochures "
                          "I need you to say which ones to build - I will put them in a sheet.")
                    _say_orchestrator(_ml_msg)
                else:
                    print("\n" + _ml_msg)
                _exit_round_trip(
                    work, 17, _attempts, "master list scope decision",
                    diagnosis=[f"work/{_ML.ANSWERS} does not answer the current candidate set "
                               f"(input_hash {_ml_hash}): "
                               + ("it does not exist yet"
                                  if not (work / _ML.ANSWERS).exists() else
                                  f"it answers input_hash "
                                  f"{(_ML.load_answers(work) or {}).get('input_hash')!r}, so an "
                                  f"input has been added or removed since - re-build the "
                                  f"workbook (answers carry forward by Row ID) and re-read it")])
    # =================================================================== end MASTER LIST ===

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
            _sp = setup_prefix(cfg, work, proj, connector="THEN, IN THE SAME MESSAGE, fix "
                               "these transcription errors: ")
            if _sp:
                _say_orchestrator(_sp)
            for e in v_errors:
                _say_orchestrator(f"  [FAIL] {e}" if not QUIET else f"  {e}")
            _exit_round_trip(work, 3, _attempts, "brochure/tracker interpretation",
                             diagnosis=[f"vision record invalid: {e}" for e in v_errors])
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

    # VISUAL AIDS ACCOUNTING. A text-mode deck's agent is asked to pick __meta.plan_page and
    # __meta.image_pages by LOOKING at a per-page render and candidate thumbnails. When those
    # were never produced - a lost image capability, a poisoned cached entry - the agent answered
    # from text alone, correctly returned nothing, and the whole gallery/plan harvest silently
    # collapsed to each property's single anchor page. Nothing recorded that it had happened. So
    # the counts are written down (the media-harvest gate reads this same file back) and a deck
    # that reaches its agent BLIND says so on stdout, in both verbosity modes.
    _aids_all: dict = {}
    for _e in interpret_decks:
        _va = dict(_e.get("visual_aids") or {})
        if _e.get("aids_degraded"):
            _va["degraded"] = _e["aids_degraded"]
        _aids_all[_e.get("source_file") or "?"] = _va
    if _aids_all:
        try:
            (work / "vision").mkdir(parents=True, exist_ok=True)
            (work / "vision" / "visual_aids.json").write_text(
                json.dumps(_aids_all, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except Exception:
            pass
        for _f, _va in sorted(_aids_all.items()):
            if int(_va.get("pages") or 0) > 1 and int(_va.get("renders") or 0) == 0:
                print(f"[SIGNAL] visual aids: {_f} reaches its interpretation agent with ZERO "
                      f"page renders ({_va.get('pages')} page(s), "
                      f"{_va.get('candidates') or 0} candidate thumbnail(s)) - it is being asked "
                      f"to pick __meta.plan_page / __meta.image_pages BLIND, so a null answer "
                      f"from it is not evidence that the deck holds no plan or no photos.")
        if not QUIET:
            _tot_r = sum(int(v.get("renders") or 0) for v in _aids_all.values())
            _tot_c = sum(int(v.get("candidates") or 0) for v in _aids_all.values())
            print(f"(visual aids for {len(_aids_all)} text deck(s): {_tot_r} page render(s), "
                  f"{_tot_c} candidate thumbnail(s) -> {work / 'vision' / 'visual_aids.json'})",
                  file=sys.stderr)

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
    # B65: an escalated deck is not a photo-match candidate - see photo_match_candidates. That
    # routing was one half of the livelock _load_force_raster documents.
    photo_candidates = photo_match_candidates(vision_targets, force_raster)
    if photo_candidates and known_recs:
        import match as _m
        rel_of = {src: src.resolve().relative_to(folder.resolve()).as_posix()
                  if folder.resolve() in src.resolve().parents else src.name
                  for src, _r, _c in photo_candidates}
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
            _pl = _render_dispatch_prompts(work, [
                ("photo-match", None,
                 {"N_BROCHURES": n_b, "N_PROPERTIES": n_p,
                  "MANIFEST_PATH": str(work / "photo_match_manifest.json"),
                  "OUTPUT_PATH": str(work / "photo_map.json")})])
            if QUIET:
                print("Some brochures have no readable text but look like photos of properties "
                      "you already gave me. I need to match each one before I can carry on.")
                _say_orchestrator(
                    f"(orchestrator: dispatch the photo-match sub-agent per "
                    f"{work / 'photo_match_manifest.json'} -> work/photo_map.json, then "
                    f"re-run.{_pl})")
            else:
                print(f"\nPHOTO MATCH NEEDED: dispatch a sub-agent to match {n_b} brochure(s) to "
                      f"{n_p} known propert(y/ies) per {work / 'photo_match_manifest.json'} -> "
                      f"work/photo_map.json, then re-run.{_pl}")
            _exit_round_trip(work, 9, _attempts, "matching brochure photos to properties",
                             diagnosis=[
                                 f"brochure '{_rel}' pending: no confident/uncertain/unrelated "
                                 f"entry covers it in work/photo_map.json"
                                 for _rel in sorted(rel_of.values())])
        # consume the sub-agent's decisions
        try:
            pm = json.loads(photo_map_f.read_text(encoding="utf-8-sig"))
        except Exception:
            pm = {}
        key_by_park = {_m.norm(r.get("park")): _m.match_key(r) for r in known_recs}

        def _resolve_key(k):
            k = k or ""
            return k if "|" in k else key_by_park.get(_m.norm(k), k)

        # answered photo confirmations (workstream 3, item 3.4): applied BEFORE the
        # doubts are rebuilt, so a broker 'yes' pulls the photo in THIS pass. The
        # resolver makes the applied qid match the asked one (the question was keyed on
        # the RESOLVED property key, the raw map entry may carry a park name).
        if apply_photo_confirm_answers(work, pm, _resolve_key):
            import _common as _C34
            _C34.atomic_write_text(photo_map_f,
                                   json.dumps(pm, ensure_ascii=False, indent=1))

        confident = {e.get("brochure"): _resolve_key(e.get("property_key")) for e in pm.get("confident", [])}
        uncertain = {e.get("brochure"): e for e in pm.get("uncertain", [])}
        # DESCRIPTION CACHE: collect the sub-agent's verbatim description picks (from
        # confident/uncertain entries that carry a non-null `description`) keyed by the
        # brochure BASENAME (the same key merge looks up via Path(brel).name) and stamp
        # each with the manifest's text_hash so a stale pick is rejected after a deck edit.
        # merge's deterministic quote-verify is the gate; this is just the cache.
        try:
            _pmm = json.loads((work / "photo_match_manifest.json").read_text(encoding="utf-8-sig"))
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
        still_vision = set()
        for src, region, country in photo_candidates:
            rel = rel_of[src]
            if confident.get(rel):
                photo_overrides[confident[rel]] = rel
            elif rel in uncertain:
                pk = _resolve_key(uncertain[rel].get("property_key"))
                park = next((r.get("park") for r in known_recs if _m.match_key(r) == pk), pk)
                photo_doubts.append({"park": park, "brochure": rel, "key": pk,
                                     "note": uncertain[rel].get("note", "")})
            else:
                still_vision.add(src)                       # unrelated / unmatched -> vision
        vision_targets = keep_vision_targets(vision_targets, rel_of, still_vision)
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
        assign_deck_outputs(decks, load_deck_outputs(work))
        _outs = [d.get("output") for d in decks]
        if len(set(_outs)) != len(_outs):
            raise SystemExit(f"internal error: deck output collision in the manifest: {_outs}")
        # B64: remember every assignment DURABLY. The manifest lists only what is pending, so
        # it cannot also be the map of where a finished deck's records live.
        save_deck_outputs(work, decks)
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
            # TYPED, not bare names (F19). A flat name list is what let six readers write
            # `warehouseAreaSqm` as a raw integer against a string-typed field and two write
            # prose into an object-typed, ORCHESTRATOR-FILLED one - 12 of 12 validate-data
            # failures on a live run, none of them an open-schema case. The registry carries
            # {name, type, fills, format?} and DROPS every orchestrator-only field, so a reader
            # is never handed a key it must not fill. `_reader_field_list()` still returns names
            # (capture_contract_test asserts that); the typing happens here.
            "fields": (extant["interpret_prep"].reader_field_registry(_reader_field_list())
                       if extant.get("interpret_prep") else _reader_field_list()),
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
        # ASCII-SAFE ON PURPOSE (F8). This manifest is read by an AGENT, and the idiomatic
        # `json.load(open(path))` an agent writes uses the platform's DEFAULT text encoding; on a
        # host whose default is not UTF-8 that raises UnicodeDecodeError on the first non-ASCII
        # byte, which was reproduced on a live run. Escaped non-ASCII costs nothing here.
        manifest.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

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
        # P1: render the canonical dispatch prompt per pending job (decks by mode, tracker
        # author + blind-verify jobs) so the orchestrator dispatches file contents verbatim.
        _prompt_jobs = []
        for _d in interpret_decks:
            _o = _deck_output_path(work, _d)
            _prompt_jobs.append((
                "reader-text" if _d.get("mode") == "text" else "reader-raster",
                Path(str(_d.get("output") or _d.get("source_file") or "deck")).stem,
                {"DECK_NAME": str(_d.get("source_file") or ""),
                 "SOURCE_TYPE": str(_d.get("source_type") or ""),
                 "PAGE_COUNT": len(_d.get("pages") or []),
                 # An INSTRUCTION when the manifest states no country, never a placeholder a
                 # reader could copy into the field (F7). The deck entry omits the key entirely
                 # (interpret_prep / vision_prep `country_kv`), so this is the one place the
                 # reader is told what to do about it.
                 "COUNTRY": (str(_d.get("country")) if _d.get("country")
                             else "not stated in this manifest - read it off the deck"),
                 "MANIFEST_PATH": str(manifest),
                 "OUTPUT_PATH": str(_o) if _o else str(_d.get("output") or "")}))
        for _j in interpret_trackers:
            _o = _deck_output_path(work, _j)
            _prompt_jobs.append((
                "tracker-verify" if _j.get("kind") == "tracker_verify" else "tracker-map",
                Path(str(_j.get("output") or "tracker")).stem,
                {"SOURCE_FILE": str(_j.get("source_file") or ""),
                 "MANIFEST_PATH": str(manifest),
                 "OUTPUT_PATH": str(_o) if _o else str(_j.get("output") or "")}))
        # OPTIONAL job (workstream 1 item 1.4): low-confidence filename clusters ride the
        # SAME exit-3 round as a rendered prompt instead of an SKILL.md-prose inline
        # judgement task. Absence of the output keeps the deterministic regex - so this
        # job never blocks and never gets a pending predicate.
        try:
            _inv3 = json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
            _lowc = sorted({str(s)
                            for _cl in (_inv3.get("clusters") or {}).values()
                            if isinstance(_cl, dict) and _cl.get("confidence") == "low"
                            for s in (_cl.get("stems") or [])})
            _cih = str(_inv3.get("cluster_input_hash") or _inv3.get("input_hash") or "")
        except Exception:
            _lowc, _cih = [], ""
        if _lowc and _cih and not (work / "intake_clusters.json").exists():
            _stems = ", ".join(_lowc[:40])
            if len(_lowc) > 40:  # never a silent cap - name the remainder's location
                _stems += (f" (+{len(_lowc) - 40} more low-confidence stems - read the "
                           f"full list from inventory.json's clusters)")
            _prompt_jobs.append(("cluster-labels", None,
                                 {"STEMS": _stems,
                                  "INVENTORY_PATH": str(work / "inventory.json"),
                                  "OUTPUT_PATH": str(work / "intake_clusters.json"),
                                  "CLUSTER_INPUT_HASH": _cih}))
        _pl = _render_dispatch_prompts(work, _prompt_jobs)
        # SETUP RIDES THE FRONT OF THIS MESSAGE (B63). No form answer feeds this round, so
        # bundling costs nothing and saves a round-trip - but it goes FIRST and as an
        # imperative, because as a trailing question it was simply not acted on.
        _setup_first = setup_prefix(cfg, work, proj)
        msg = (_setup_first
               + f"{' and '.join(parts)} need INTERPRETATION. Manifest: {manifest}. Dispatch the "
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
               f"ISO-639-1 code of the language each deck is written in.{_pl}")
        # F4: the ~2,300-character handoff above prints in full ONCE per streak of this exit;
        # a re-fire prints the two-line reminder (setup prefix and prompts sentence kept) and
        # relies on the [pending] lines _exit_round_trip prints in full every time.
        msg = _handoff_once(work, 3, _attempts, "brochure/tracker interpretation", msg,
                            tail=_setup_first + _pl)
        if QUIET:
            print("A few setup questions first, then I'll read your files into the dashboard."
                  if setup_pending(cfg, work) else
                  "Some of your files still need reading into the dashboard - I'll structure "
                  "them before I build.")
            _say_orchestrator(msg)
        else:
            print("\n" + msg)
        # P3: the guard's exact pending predicates - a deck is pending while its own output
        # file does not exist; a tracker while neither its map output nor a .SKIP does.
        _diag = []
        for _d in interpret_decks:
            _o = _deck_output_path(work, _d)
            # B64: state the predicate we ACTUALLY evaluated. This line used to assert the
            # output did not exist without ever looking, so a manifest rebuild printed
            # "does not exist yet" for eight files that were on disk - and SKILL.md tells the
            # orchestrator to satisfy these predicates verbatim and never guess.
            if _o is not None and _o.exists():
                _n = len(_load_records(_o))
                _diag.append(f"deck '{_d.get('source_file')}' ({_d.get('mode')}) pending: its "
                             f"interpretation output exists but carries {_n} record(s): {_o}")
            else:
                _diag.append(f"deck '{_d.get('source_file')}' ({_d.get('mode')}) pending: its "
                             f"interpretation output does not exist yet: {_o}")
        for _j in _author_trackers:
            _o = _deck_output_path(work, _j)
            _diag.append(f"tracker '{_j.get('source_file')}' pending: neither its map output "
                         f"nor a .SKIP sentinel exists at: {_o}")
        _exit_round_trip(work, 3, _attempts, "brochure/tracker interpretation",
                         diagnosis=_diag)

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

    # SETUP IS A FIRST-PASS INVARIANT (B63). Reaching here means no exit-3 round carried the
    # Stage-0 form this pass - an email-only or image-only corpus, or a work dir whose
    # interpretation outputs are all cached or .SKIP-declined. That used to mean the five
    # questions were never printed AT ALL, because the only site that mentioned them was the
    # interpretation hand-off. So it stops here instead, on its own, and the run cannot get
    # to a client-facing dashboard on five guessed answers without either the broker's
    # answers or a recorded decline.
    if setup_pending(cfg, work):
        import clarify as _CQ0
        # THE ONLY TWO THINGS THAT CLEAR THIS are `setup.confirmed: true` (read by
        # setup_pending, above) and an explicit DECLINE. An ordinary answers.json entry
        # deliberately does not: the five answers have to land in project.yaml, where every
        # later stage reads them, and letting a stray answer clear the stop would put back
        # exactly the silent-skip this exists to close.
        _CQ0.ingest_answers(work)
        _setup_qid = _CQ0.qid("setup_form", SETUP_QID_SUBJECT)
        _setup_declined = _setup_qid in _CQ0.declined_ids(work)
        _stray = _CQ0.load_state(work).get("answers", {}).get(_setup_qid)
        _sq = [{
            "id": _setup_qid,
            "kind": "setup_form", "asked_of": "broker", "blocking": True,
            "subject": "Stage-0 setup", "question": setup_handoff_text(work, proj),
            "why_it_matters": ("the client name names every deliverable, the language sets "
                               "every label on the dashboard, and the email scope decides "
                               "which options are on it at all"),
            "if_unanswered": ("nothing is built. Answer 'skip' (or create "
                              "work/clarify.SKIP_ALL) to accept the scaffold's defaults - "
                              "English, no email ingestion, car drive-times - as your "
                              "recorded decision rather than an assumption"),
        }]
        if not _setup_declined:
            _CQ0.emit(work, _sq)
            if QUIET:
                print("Before I build, I need to ask you a few setup questions.")
            _stray_note = (
                f" NOTE: work/answers.json carries '{_stray}' for this question, and that "
                f"does NOT clear it - the six answers have to be written into project.yaml "
                f"with `setup.confirmed: true`, because that is where every later stage "
                f"reads them." if _stray else "")
            _say_orchestrator(
                f"(orchestrator: exit 13 - {setup_handoff_text(work, proj)} The question is "
                f"also written to {work / 'questions.json'}. Re-running alone will NOT clear "
                f"it.{_stray_note})")
            _exit_round_trip(work, 13, _attempts, "Stage-0 setup",
                             diagnosis=[f"`setup.confirmed` is not true in {proj}, and "
                                        f"neither work/{_CQ0.SKIP_ALL_FILE} nor "
                                        f"clarify.assume_defaults declines it"])

    # CROSS-SOURCE MATCH ADJUDICATION (exit 10) - mirrors photo-match (exit 9). The
    # deterministic matcher (match.py) auto-merges the confident pairs and HARD-BLOCKS
    # the impossible ones (a >15% size conflict; a developer disagreement is a GREY pair,
    # never a hard block). What is left - a GREY ZONE of cross-source pairs that are
    # plausibly the same property (within ~2 km / a shared distinctive identity token, read
    # across every park/address/scheme-ish field with place words stripped / a borderline
    # fuzzy key / a party name linking the two records inside one city) - is the
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
    # THE DECK PAGE COUNTS WENT WITH THE PRODUCER THAT READ THEM. `clarify.record_count_questions`
    # was the only consumer of a {deck: n_pages} map here, and it is deleted: page count is not
    # evidence (a six-page brochure for ONE property is the normal case), so it fired on most
    # decks, and a question channel that cries wolf costs a round-trip every time AND trains the
    # orchestrator to skim the questions that are precise. Reading the manifest to build a map
    # nothing consumes would be the same dead weight one level down. The QUESTION it wanted asked
    # is still asked, by the only thing that can tell when to ask it: a reading agent records
    # "does this deck describe one property or two?" in `__meta.doubts`, clarify's own count
    # lexicon recognises it, and it reaches the broker as a material question. (B46)
    #
    # source_authority_questions is NOT asked here either, and that is deliberate (B47). It
    # used to fire at this point on RAW RECORD COUNTS ("the brochures describe 13, the tracker
    # lists 12"), which is a pre-clustering number: a brochure record that merges into a
    # tracker row is not an extra at all. So the broker was asked to arbitrate a discrepancy
    # that the very next stage often dissolves. It now fires AFTER clustering has settled,
    # below, where an "extra" is well defined and the question can NAME the options at stake.
    # THE DATASET DISPLAY UNIT rides the same first batch (B49). It is a property of the whole
    # corpus rather than of one record, so it is derivable here, before matching, and an answer
    # changes every card - which makes this the last moment it can be asked for free.
    _questions = _clarify.unit_questions(_recs_for_q) \
        + _clarify.dataset_unit_questions(_recs_for_q)
    if _clarify.clarify_mode(work, cfg) == "interactive":
        # workstream 3 (the STANDARD mode): photo confirmations at decision time
        # (item 3.4) and the readers' recorded doubts (item 3.2) join this same
        # batched first round - one interruption, never a drip. The ledger-only
        # doubts ride along and are filtered out (and recorded) by clarify.pending,
        # so they reach the Gaps Report without costing a round-trip. (B62)
        _questions += _clarify.photo_confirm_questions(photo_doubts)
        _questions += _clarify.agent_doubt_questions(_recs_for_q)
    else:
        # HEADLESS asks nothing, but a doubt a reader took the trouble to record must
        # still reach the broker somewhere. record_schema.json has always promised
        # "a headless run ships them in the Gaps Report" and nothing implemented it -
        # the same disclosure channel now does. (B62)
        #
        # SPLIT BY MATERIALITY, because the two say different things to a broker. A doubt
        # about which warehouse area is right is NOT "no effect on what the dashboard
        # shows" just because this run was told not to ask: it goes under the heading that
        # says so. Getting this wrong printed the opposite of the truth in a client-facing
        # deliverable, which both blind reviews called out.
        _hd = _clarify.agent_doubt_questions(_recs_for_q)
        _clarify.note_suppressed(work, [q for q in _hd if not _clarify.is_material(q)],
                                 why=_clarify.WHY_LEDGER)
        _clarify.note_suppressed(work, [q for q in _hd if _clarify.is_material(q)],
                                 why=_clarify.WHY_HEADLESS)
    def _ask_and_exit(questions, quiet_intro, reason, extra=""):
        """The ONE emit site - questions are BATCHED here, never dripped.

        Two phases can reach it (unit ambiguities before matching; source authority once
        clustering has settled, which is the earliest moment an 'extra' is even definable),
        but every question still leaves through this single door: one emit, one questions.json,
        one exit 13. Keeping it to one call site is what the batching invariant actually
        protects, and evals/clarify_test.py asserts the count."""
        qf = _clarify.emit(work, questions)
        n_br = sum(1 for q in questions if q.get("asked_of") == "broker")
        # BLOCKING questions do not fall through to a default, so the hand-off must say so -
        # an orchestrator told only "anything unanswered ships as a gap" will reasonably just
        # re-run, and re-running is precisely what does not clear these. (B49)
        _blk = [q for q in questions if _clarify.is_blocking(q)]
        _esc = any(q.get("escalated") for q in _blk)
        _blk_note = ""
        if _blk:
            _blk_note = (
                f" {len(_blk)} of these BLOCK the build: their fall-through default is itself "
                f"the damage (a wrong unit, or a longlist padded with options the client never "
                f"shortlisted), so they come back every pass until they are DECIDED. "
                f"Re-running alone will not clear them: put them to the user in plain "
                f"language, or - only if the user says they have no preference - record an "
                f"explicit decline by answering 'skip'.")
            if _esc:
                _blk_note += (
                    " ALREADY ASKED MORE THAN ONCE: if you have not put these to the user yet, "
                    "do that now rather than re-running; if there is no user to ask (a headless "
                    "run), create work/" + _clarify.SKIP_ALL_FILE + " to accept every default "
                    "as an explicit decision.")
        _pl = ""
        if len(questions) - n_br > 0:  # a prompt only for the agent-answerable questions
            _pl = _render_dispatch_prompts(work, [
                ("clarify", None,
                 {"N_AGENT_QUESTIONS": len(questions) - n_br,
                  "QUESTIONS_PATH": str(qf),
                  "ANSWERS_PATH": str(work / "answers.json")})])
        if QUIET:
            print(quiet_intro)
            _say_orchestrator(
                f"(orchestrator: {len(questions)} clarification(s) needed ({n_br} for the "
                f"user, {len(questions) - n_br} for an isolated sub-agent) per {qf} -> "
                f"{extra}write work/answers.json as {{id: answer}} and re-run. Each question "
                f"is asked ONCE unless it is marked `blocking`: a non-blocking question left "
                f"unanswered ships as the honest gap named in its `if_unanswered`, so answer "
                f"only what you know and never invent one.{_blk_note}{_pl})")
        else:
            print(f"\nCLARIFICATION NEEDED ({len(questions)}): see {qf}. Answer what you can "
                  f"into work/answers.json ({{id: answer}}) and re-run. Non-blocking questions "
                  f"are asked once and then ship as a disclosed gap.{_blk_note}{_pl}")
        # D13: for every question whose answer the run will NOT land, say NOW, per record, what
        # to do with the answer about to be collected: the record, the field and a paste-ready
        # work/repairs.json entry with its `expect` guard filled in. On the measured run five
        # of eight broker answers were recorded and applied to nothing, and the operator had to
        # reverse-engineer the entry from source; the `answer_handling` stamp alone (F18) did
        # not carry the pressure it was meant to. Always stdout, like every handoff line (B27).
        _hl = getattr(_clarify, "handoff_lines", None)
        for _ln in (_hl(questions) if callable(_hl) else []) or []:
            _say_orchestrator(_ln)
        # An ANSWER is a merge input (clarify_state.json, B38), so it is consumed BEFORE the
        # repairs stage and a full pass is required - there is no cheaper valid cut. (A26)
        print(_reentry("premerge"))
        _exit_round_trip(work, 13, _attempts, reason,
                         diagnosis=[
                             f"question '{q.get('id')}' (asked_of: {q.get('asked_of')}) "
                             f"unanswered: no entry for that exact id in work/answers.json"
                             for q in questions])

    _ask = _clarify.pending(work, _questions)
    if _ask:
        _ask_and_exit(_ask,
                      "A few things in your files are ambiguous - I need to confirm them "
                      "before I build, so nothing is guessed.",
                      "clarifying ambiguous source data")

    # F29: how many grey pairs / field conflicts the enumeration found; None = it never ran
    # (fewer than two record files), which work/decision_trail.json then says in words.
    _n_grey = None
    _n_conflicts = None
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
        # THE USER'S OWN DUPLICATE GROUPS PRE-ANSWER THE PAIRS THEY COVER. A group on the master
        # list is the person who owns the deliverable saying "these are one building". Exit 10
        # exists to ask a sub-agent that same question about pairs NOBODY has answered, so
        # re-asking a grouped pair would route the broker's decision back through an
        # intermediary to be re-derived - and a 'different' verdict from that intermediary would
        # silently overrule them. Seeded BEFORE grey_pairs so the verdicts are in place for the
        # coverage predicate in the same pass, keyed with match.pair_id, which is the id the
        # spine itself generates for a pair: any other key would produce a file that looks
        # answered and covers nothing. Never overwrites an existing verdict.
        try:
            import master_list as _ML  # local: this path must not depend on the extract stage
            _ml_seed = _ML.seed_match_decisions(_all_recs, work)
            _ml_have = _load_match_decisions(work) or {}
            _ml_new = {k: v for k, v in _ml_seed.items() if k not in _ml_have}
            if _ml_new:
                _mutate_decisions_file(work / "match_decisions.json", _ml_new)
                if not QUIET:
                    print(f"  ({len(_ml_new)} pair(s) pre-answered 'same' from your master list "
                          f"duplicate groups - exit 10 will not ask about them)")
        except Exception as _e:
            print(f"  (master-list duplicate groups not seeded into match_decisions: {_e})",
                  file=sys.stderr)
        grey = _mm.grey_pairs(_all_recs)
        _n_grey = len(grey or [])
        # AUTO-MERGED PAIRS OFFERED FOR CONFIRMATION (A15). The auto tier merges without
        # asking anybody and nothing enumerated it, so the one failure this module calls
        # invisible AND unrecoverable - a fusion, which no later stage can undo - was the one
        # failure no human ever saw. `match.auto_pairs` surfaces only the auto pairs whose
        # records MATERIALLY DISAGREE on identity (a party, a scheme name, a unit designator
        # or a street; the postal code cannot appear, its veto sends such a pair to
        # `forbidden` before the auto tier can claim it). The restriction is the point: an
        # exit listing every auto pair is noise, and noise gets skimmed.
        #
        # THEY RIDE THE EXIT-10 ROUND-TRIP RATHER THAN OPENING ONE. Deliberate. These pairs
        # are ALREADY merged, so an unanswered one is not a pending decision - it is today's
        # behaviour - and giving them their own blocking exit would make every corpus with one
        # material disagreement pay a round-trip for a merge the matcher was probably right
        # about. Offered in the SAME round as the grey pairs, dropped with them once the pairs
        # round is settled, and only an explicit 'different' verdict ever acts on one
        # (match.same_property).
        auto_confirm = _mm.auto_pairs(_all_recs)
        # the settled match decisions (best-effort): clustering for the value-conflict
        # enumeration uses the SAME match.dedupe(_all_recs, md or None) merge uses, so the
        # two clustering calls AGREE and conflict_ids never drift (the key #4 risk).
        # Merged over work/match_settled.json, so a round-2 agent that empties
        # match_decisions.json cannot destroy a settled verdict and force a third round (B20).
        md = _load_match_decisions(work)
        # UNSURE verdicts (workstream 3, item 3.3): resolve answered/headless ones into
        # match_decisions.json BEFORE clustering (a verdict changes cluster membership);
        # anything still pending becomes a blocking exit-13 broker question below.
        _n_up, _unsure_pair_qs = unsure_pair_questions(work, cfg, grey)
        if _n_up:
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
            # AN ANSWERED MASTER LIST IS THE AUTHORITY, SO THE QUESTION IS NOT ASKED.
            #
            # The source-authority question asks a broker which SOURCE FAMILY decides what
            # belongs on the longlist - a proxy question, asked late, whose answer then removes
            # whole options by file extension. A user who has been through the master list has
            # already answered the real question, option by option, with the option names in
            # front of them, before any of those options cost a reader agent. Asking the proxy
            # afterwards would be asking the same person the same thing twice and letting the
            # cruder answer overrule the finer one. So: master list answered -> keep exactly the
            # options they included and skip the question. Headless / no master list -> the
            # question behaves exactly as it always has.
            import master_list as _ML  # local: see the seeding block above
            _ml_governs = _ML.user_answered(work)
            _extras = {} if _ml_governs else _merge.authority_extras(clusters)
            # THE ARITHMETIC AND WHERE IT COMES FROM (B49). The question used to open on two
            # lists of names, which reads as "you are about to lose 14 options" and drove the
            # answer that doubled the deliverable. Give it the two totals a broker can check
            # against their own shortlist - the roster's row count and what the run actually
            # holds - plus, per deck, how many separate units that deck yielded against how
            # many options the roster lists in the same town. A park-wide availability schedule
            # read as 15 options shows up here as "15 units read, tracker lists 1".
            def _row_key(_r, _f, _i):
                """A tracker record's ROW identity: the sheet!row locator it already carries.

                Counting record objects would double-count if the same rows ever arrived via
                two record files, and "your tracker lists 34 options" for a 17-row sheet
                mis-frames the exact decision being asked about."""
                for _v in (((_r.get("__meta") or {}).get("prov") or {}) or {}).values():
                    _t = str(_v or "").split()[0].strip()
                    if "!" in _t:
                        return f"{_f}|{_t}"
                return f"{_f}|#{_i}"

            _roster_keys, _roster_by_city = set(), {}
            for _f, _rs in _by_src.items():
                if not str(_f).lower().endswith(_clarify.AUTHORITY_FAMILIES["tracker"]):
                    continue
                for _i, _r in enumerate(_rs):
                    _k = _row_key(_r, _f, _i)
                    if _k in _roster_keys:
                        continue
                    _roster_keys.add(_k)
                    _c = str(_r.get("city") or "").strip().lower()
                    if _c:
                        _roster_by_city[_c] = _roster_by_city.get(_c, 0) + 1
            _roster_rows = len(_roster_keys)
            _by_source_rows = []
            for _f, _rs in sorted(_by_src.items()):
                if not str(_f).lower().endswith(_clarify.AUTHORITY_FAMILIES["brochures"]):
                    continue
                _cities = {str(r.get("city") or "").strip().lower() for r in _rs}
                _cities.discard("")
                _by_source_rows.append({
                    "source_file": _f, "records": len(_rs),
                    "roster_options": sum(_roster_by_city.get(c, 0) for c in _cities),
                    "where": ", ".join(sorted({str(r.get("city") or "").strip()
                                               for r in _rs if r.get("city")})),
                })
            _auth_q = _clarify.pending(work, _clarify.source_authority_questions(
                _extras,
                counts={"tracker_rows": _roster_rows, "merged_total": len(clusters)},
                by_source=_by_source_rows)) if _extras else []
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
            # never answered. When the master list governs, the SAME filter merge.main applies
            # runs here instead, for the same reason: two clustering calls that disagree about
            # which options exist produce conflict ids that drift, which is the key risk this
            # whole path is written around.
            if _ml_governs:
                clusters, _ml_out = _ML.apply_to_clusters(clusters, work)
                if _ml_out and not QUIET:
                    print(f"  ({len(_ml_out)} option(s) left out - you marked them No on the "
                          f"master list; each is named in the Gaps Report)")
            else:
                clusters, _ = _merge.apply_source_authority(
                    clusters, _clarify.settled_authority(_answers))
        # The surfaced AUTO pairs join the open-pair set while the pairs round is open: a
        # 'different' verdict on one changes cluster membership exactly as a grey 'same' does,
        # so a conflict adjudicated against it now would be re-keyed and re-asked (the 44 ->
        # 78 growth B20 exists to stop). Only while `grey_uncovered`, because that is the only
        # round in which they are ASKED - treating them as open after the keys are dropped
        # would withhold those conflicts for ever, which is a livelock, not caution.
        conflicts = _merge.conflict_candidates(
            _settled_clusters(clusters, grey + auto_confirm, md, _all_recs)
            if grey_uncovered else clusters)
        _n_conflicts = len(conflicts or [])
        fd = None
        if field_decisions_f.exists():
            try:
                parsed_f = json.loads(field_decisions_f.read_text(encoding="utf-8-sig"))
                fd = _index_decisions(parsed_f, ("conflict_id", "field", "property_id"))
            except Exception:
                fd = None  # malformed/half-written -> treat as absent (re-emit + exit 10)

        def _pick_ok(v):
            if isinstance(v, str):
                return True  # a bare label string is accepted
            if isinstance(v, dict):
                return isinstance(v.get("pick"), str)
            return False
        # UNSURE picks (item 3.3): same treatment for value conflicts, then re-load.
        _n_uf, _unsure_pick_qs = unsure_pick_questions(work, cfg, conflicts, fd)
        if _n_uf and field_decisions_f.exists():
            try:
                parsed_f = json.loads(field_decisions_f.read_text(encoding="utf-8-sig"))
                fd = _index_decisions(parsed_f, ("conflict_id", "field", "property_id"))
            except Exception:
                fd = None
        _unsure_qs = _unsure_pair_qs + _unsure_pick_qs
        if _unsure_qs:
            import clarify as _CQ13
            _pend13 = _CQ13.pending(work, _unsure_qs)
            if _pend13:
                _CQ13.emit(work, _pend13)
                if QUIET:
                    print("Two of your sources might describe the same option, or disagree "
                          "on a value, and the files alone can't settle it - I need your "
                          "call before I merge.")
                _say_orchestrator(
                    f"(orchestrator: {len(_pend13)} unsure-adjudication question(s) for the "
                    f"BROKER (exit 13) - the reading agent was genuinely torn. Put them to "
                    f"the user in ONE plain message from {work / 'questions.json'}, write "
                    f"work/answers.json, re-run. Their answer becomes the recorded verdict; "
                    f"'skip' ships the safe default, disclosed.)")
                # A match/field adjudication decides how records CLUSTER, which is merge's own
                # job, so it applies pre-merge and a full pass is required. (A26)
                print(_reentry("premerge"))
                _exit_round_trip(work, 13, _attempts, "unsure match/value adjudication",
                                 diagnosis=[f"question '{q['id']}' (asked_of: broker) "
                                            f"pending: no answer or decline in "
                                            f"work/answers.json" for q in _pend13])
        # an unsure pick may have JUST resolved (headless/decline path above), so
        # recompute coverage against the mutated files
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
                    "Cross-source ambiguity rides this ONE candidates file (resolve it ALL in one "
                    "round-trip). (1) `pairs` - AMBIGUOUS RECORD MATCHES: the "
                    "deterministic matcher has already auto-merged the confident pairs and "
                    "hard-BLOCKED the impossible ones (a >15% size conflict, or two DIFFERENT "
                    "stated postal codes - neither can ever merge, whatever verdict anyone "
                    "writes), so each pair here genuinely could be one property described twice (e.g. 'Raven "
                    "Park, Corby' vs 'Unit 1, Raven Park, Earlstrees Industrial Estate, Corby QX41 "
                    "8RD' = same) or two distinct ones ('Alpha Park' vs 'Beta Park', same developer "
                    "and city = different). TWO THINGS ABOUT PARTIES, both of which the matcher "
                    "changed and this text used to get wrong. A DEVELOPER DISAGREEMENT IS NOT "
                    "HARD-BLOCKED: landlord and developer are separate fields now, so a differing "
                    "developer is a real naming / joint-venture / asset-sale signal rather than a "
                    "landlord in the wrong column, and such a pair is sent HERE for you to judge "
                    "rather than blocked. And AN ABSENT PARTY IS NOT AGREEMENT: the auto tier "
                    "requires the developer STATED ON BOTH SIDES and equal, so 'neither record "
                    "names one' means there is no party evidence at all - do not read two silences "
                    "as a match. Decide, for EACH pair, by MEANING whether `a` and `b` "
                    "describe the SAME physical property. Write work/match_decisions.json: {\"<pair_id>"
                    "\": {\"verdict\": \"same\"|\"different\"|\"unsure\", \"reason\": \"...\"}, ...} "
                    "covering EVERY pair_id. Lean \"different\" when the evidence is thin (an "
                    "over-split is caught by the dedupe gate); \"unsure\" is for a pair you are "
                    "GENUINELY torn on after real effort - it goes to the broker on an interactive "
                    "run (headless ships 'different', disclosed). Never use it to avoid the work. "
                    "(2) `field_conflicts` - GENUINE "
                    "VALUE DISAGREEMENTS within a merged property: a field where two+ sources state "
                    "DIFFERENT values. The fixed source precedence already chose a `default`; KEEP "
                    "the default unless a candidate is clearly right and the default clearly wrong (a "
                    "typo in a newer email, a mislabelled tracker column, an ask-price vs a "
                    "negotiated rate). NEVER invent a value - pick only among the given candidate "
                    "labels; lean the default when the evidence is thin, and pick \"unsure\" ONLY "
                    "when genuinely torn (it goes to the broker on an interactive run; headless "
                    "keeps the default, disclosed). Write work/field_decisions.json: "
                    "{\"<conflict_id>\": {\"pick\": \"<label>\"|\"unsure\", \"reason\": \"...\"}, ...} covering "
                    "EVERY conflict_id. Python re-verifies each pick against the field's plausibility "
                    "gate and falls back to precedence if it fails. See reference/matching.md. Then "
                    "re-run the same command - it resumes and merges."),
            }
            # (3) CONFIRM THE AUTO MERGES THAT DISAGREE ON IDENTITY. Only added when there ARE
            # any, so a corpus with none produces a byte-identical candidates file. Keyed into
            # the SAME work/match_decisions.json, because `match.same_property` reads one
            # decisions map for every tier - and OMITTING one is safe by construction: no
            # verdict means the merge stands, which is exactly what happens today.
            if auto_confirm:
                _cand["confirm_pairs"] = [
                    {"pair_id": g["pair_id"], "a": g["a"], "b": g["b"],
                     "disagrees_on": g["disagrees_on"]} for g in auto_confirm]
                _cand["confirm_instructions"] = (
                    "(3) `confirm_pairs` - PAIRS THE MATCHER HAS ALREADY MERGED, offered for "
                    "confirmation because the two records MATERIALLY DISAGREE about what they "
                    "are: `disagrees_on` names the class - \"party\" (a developer, landlord, "
                    "owner, asset manager or freeholder), \"name\" (the scheme / estate / site), "
                    "\"unit\" (WHICH building on it - the merge key cannot see this one at all), "
                    "\"street\". These are NOT 'should these merge?' questions: they are ALREADY "
                    "one card, and the other record's fields are already blended into it. A "
                    "fusion is the one matcher error a reader can never see and nothing can "
                    "undo, which is why you are being shown them. Judge each ONE way only: "
                    "write \"different\" into work/match_decisions.json under its `pair_id` if "
                    "the two records describe TWO DIFFERENT physical properties, which splits "
                    "them back into two cards. ANYTHING ELSE - \"same\", \"unsure\", or simply "
                    "leaving the pair out - leaves the merge exactly as the matcher made it, so "
                    "say \"different\" only when you are confident, and never to be safe. Give "
                    "a `reason` naming the evidence either way.")
            if not grey_uncovered:
                # ROUND 2, pairs already settled. Do NOT re-list them: re-emitting costs two
                # sub-agent dispatches for nothing, and a re-dispatched author returning one
                # different verdict would re-key the very conflicts being adjudicated in this
                # same round. Omit the keys entirely rather than send `pairs: []`, which reads
                # to a literal-minded agent as "write an empty decisions file". (B20)
                # `confirm_pairs` is dropped WITH the grey pairs, for the same reason and
                # then one more. Same reason: a settled pair must never be re-asked - two
                # sub-agent dispatches for nothing, and a re-dispatched author returning one
                # different verdict would re-key the very conflicts being adjudicated in this
                # same round (B20). One more: a confirm pair is ALREADY MERGED, so re-offering
                # it every round would keep inviting a 'different' verdict against a merge
                # somebody has already looked at and let stand - an over-split by attrition.
                for _k in ("pairs", "verify_pairs", "output", "verify_output",
                           "verify_instructions", "confirm_pairs", "confirm_instructions"):
                    _cand.pop(_k, None)
                _cand["settled_pairs"] = len(grey) + len(auto_confirm)
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
            # P1: one prompt per pending judgement job. With pairs open the author job covers
            # pairs + the listed conflicts and a SEPARATE blind verify job re-judges the pairs
            # (dispatched concurrently, never shown the author's verdict); with only conflicts
            # left, the conflicts-only prompt forbids touching the settled pair files.
            _pjobs = []
            if grey_uncovered:
                _pjobs.append(("match-adjudicate", None,
                               {"N_PAIRS": n_g, "N_CONFLICTS": len(conflicts),
                                "CANDIDATES_PATH": str(work / "match_candidates.json"),
                                "DECISIONS_PATH": str(work / "match_decisions.json"),
                                "FIELD_DECISIONS_PATH": str(work / "field_decisions.json")}))
                _pjobs.append(("match-verify", None,
                               {"N_PAIRS": n_g,
                                "CANDIDATES_PATH": str(work / "match_candidates.json"),
                                "VERIFY_OUTPUT_PATH": str(work / "match_verify.json")}))
            elif field_uncovered:
                _pjobs.append(("field-conflicts", None,
                               {"N_CONFLICTS": n_c,
                                "CANDIDATES_PATH": str(work / "match_candidates.json"),
                                "FIELD_DECISIONS_PATH": str(work / "field_decisions.json")}))
            _pl = _render_dispatch_prompts(work, _pjobs)
            if QUIET:
                print("Some options look like they might be the same property from different "
                      "sources, or sources disagree on a value; I need to confirm a few before "
                      "continuing.")
                _say_orchestrator(
                    f"(orchestrator: dispatch the match sub-agent for {n_g} pair(s) + {n_c} value "
                    f"conflict(s) per {work / 'match_candidates.json'} -> work/match_decisions.json "
                    f"+ work/field_decisions.json, then re-run.{_pl})")
            else:
                parts = []
                if grey_uncovered:
                    parts.append(f"{n_g} ambiguous cross-source pair(s)")
                if field_uncovered:
                    parts.append(f"{n_c} cross-source value conflict(s)")
                print(f"\nMATCH ADJUDICATION NEEDED: dispatch a sub-agent for {' + '.join(parts)} per "
                      f"{work / 'match_candidates.json'} -> work/match_decisions.json + "
                      f"work/field_decisions.json, then re-run.{_pl}")
            # P3: the exact pending predicates. The unparseable-file lines matter most: a
            # BOM'd or half-written decisions file reads as "absent" to the guard, which is
            # invisible without these.
            _diag = []
            if grey_uncovered:
                if (work / "match_decisions.json").exists() and not md:
                    _diag.append("work/match_decisions.json exists but yielded no recognised "
                                 "verdicts - check it is PLAIN UTF-8 JSON (no BOM) and every "
                                 "pair_id is echoed verbatim")
                _diag += [f"pair '{g.get('pair_id')}' pending: no recognised same/different "
                          f"verdict for that exact id in work/match_decisions.json"
                          for g in grey if not _pair_answered(md, g)]
            if field_uncovered:
                if fd is None and field_decisions_f.exists():
                    _diag.append("work/field_decisions.json exists but is unparseable - check "
                                 "it is PLAIN UTF-8 JSON (no BOM)")
                _diag += [f"conflict '{c.get('conflict_id')}' pending: no recognised pick for "
                          f"that exact id in work/field_decisions.json"
                          for c in conflicts
                          if fd is None or not _pick_ok(fd.get(c["conflict_id"]))]
            # A match/field adjudication is consumed BY merge (it decides the clustering), so a
            # full pass is required - `--from repairs` would skip the stage that reads it. (A26)
            print(_reentry("premerge"))
            _exit_round_trip(work, 10, _attempts, "cross-source match/value adjudication",
                             diagnosis=_diag)

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
                parsed_v = json.loads(match_verify_f.read_text(encoding="utf-8-sig"))
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
        _prev_merge_code = (work / ".code_merge.prev").read_text(encoding="utf-8-sig").strip()
    except Exception:
        _prev_merge_code = ""
    _now_merge_code = _merge_code.read_text(encoding="utf-8-sig").strip()
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

    # THE ANSWERED SCOPE SHEET IS A MERGE INPUT, for exactly the reason the answered
    # clarifications above are one: a user who changes an Include? from Yes to No and re-runs
    # must see that option leave the dashboard, and resume would otherwise skip the one stage
    # that drops it. A headless master_list.json is passed too and is a no-op inside merge
    # (every row is Yes), which keeps the resume predicate honest rather than conditional.
    _ml_f = work / "master_list.json"
    if _ml_f.exists():
        merge_args += ["--master-list", _ml_f]
        merge_inputs.append(_ml_f)

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
    # F29: say which decision stages had NOTHING to decide, and why, before merge runs - a
    # reviewer of a brochures-only work dir must be able to tell "not applicable" from
    # "never ran" without taking either on trust.
    _write_decision_trail(work, record_files, len(inv.get("xlsx") or []), interpret_trackers,
                          _n_grey, _n_conflicts)
    _stage("merge")
    # STAGE CONTROL AS A TRAILING `or` CLAUSE, not a `stage=` argument, at this one site and at
    # the build site below. Reads as "(both outputs are current) OR --from/--only put merge out
    # of scope"; `and` binds tighter than `or`, so the grouping is (A and B) or C. Two things
    # make it the right shape here rather than a keyword on each call: merge is the only stage
    # with TWO outputs, so the cut is one decision about the pair rather than the same argument
    # written twice; and this exact expression is anchored BY TEXT in three existing evals
    # (audit_resume, engine_resume, code_stamp), which use it as the position marker proving the
    # sentinels and code stamps are appended to merge_inputs BEFORE the predicate reads them.
    # Those are real wiring assertions worth keeping green - so the currency question still goes
    # through the one predicate, and only the scope question sits beside it (exactly the split
    # enrichment's own skip boolean uses, for the same reason: no second parallel mechanism).
    if _is_current(canonical, merge_inputs) and _is_current(ledger_csv, merge_inputs) \
            or _stage_skipped("merge"):
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
                        recs += json.loads(Path(rf).read_text(encoding="utf-8-sig"))
                    except Exception:
                        pass
                done, total = merge.prewarm_images(recs, folder, work / ".image_cache",
                                                   _IMG.DEFAULT_BUDGET_KB, seconds=secs)
                if total:
                    # WHY `done < total` IS NO LONGER A PRESCRIPTION TO RE-RUN. merge's
                    # prewarm was changed so that the pages a document has PAST the
                    # per-document cap are counted into `total` and can NEVER be counted into
                    # `done` - deliberately, so `done == total` cannot license a completeness
                    # claim over pages this accelerator never enumerated. That makes
                    # `done < total` a PERMANENT state on any corpus holding a long document,
                    # and this line went on telling the operator to "re-run the same command to
                    # warm the rest" every single time: confirmed identical over three
                    # consecutive passes, an instruction no re-run can ever satisfy. A message
                    # that prescribes an action which cannot work teaches the operator to stop
                    # reading the messages.
                    #
                    # THE SPLIT IS NOT AVAILABLE HERE, so it is not claimed. `prewarm_images`
                    # returns (done, total) and folds the uncounted pages into `total`; the
                    # figure itself is local to the producer. Recomputing it in this process
                    # would mean a second copy of merge's per-document cap arithmetic, i.e. a
                    # new seam of exactly the kind that produced this one. So the two CAUSES
                    # are named, the operator is given the ONE bounded action that can help,
                    # and the test that tells the causes apart is handed over with it.
                    msg = (f"   photo cache: {done}/{total} images ready"
                           + (" - complete" if done >= total else
                              ". Some of the remainder is out of scope by design: a document "
                              "longer than the per-document page cap has its later pages "
                              "counted in the total but never warmed, so this figure never "
                              "reaches complete on such a corpus. Re-run the same command ONCE "
                              "to warm whatever the time budget cut short (raise it with "
                              "CBRE_PREWARM_SECONDS); if the number does not move, the rest is "
                              "those out-of-scope pages and no further pass can close it. "
                              "Nothing here blocks the run - merge harvests anything unwarmed "
                              "itself."))
                    print(msg)
            except Exception as e:
                if not QUIET:
                    print(f"(image pre-warm skipped: {e})", file=sys.stderr)
        call(merge, *merge_args)

    # workstream 3, item 3.5 (interactive): an excluded record's figure conflicting with
    # the shipped card it plausibly IS becomes ONE non-blocking broker question; an
    # answer picking the excluded figure was just written as an attributed repair (the
    # repairs stage applies it before the gates, this same pass on the re-run)
    # workstream 3, item 3.2 (interactive): an ANSWERED field-level reader doubt is written
    # INTO the field, here, as an attributed repair - the repairs stage below applies it on
    # THIS pass. Until now the answer was recorded and consumed by nothing, so the broker had
    # to supply the same value a second time through work/repairs.json by hand.
    _n_ad = agent_doubt_repairs(work, cfg, canonical)
    if _n_ad:
        print(f"({_n_ad} answered reader-doubt question(s) recorded as attributed repair(s) - "
              f"applied before the gates on this pass, each with its own Source Ledger row "
              f"and a line in the Gaps Report.)")
    # F18: say which answers were RECORDED ONLY, exactly as their question's `answer_handling`
    # warned, so nobody is told a card will change when the question itself said it would not.
    _ro = _recorded_only_doubt_answers(work)
    if _ro:
        print(f"({len(_ro)} answered reader-doubt question(s) recorded but NOT applied to a card, "
              f"as each question's `answer_handling` said (the reader named no canonical field, "
              f"no candidate values, or an option that does not lead with a figure): "
              f"{', '.join(_ro[:6])}"
              + (" ..." if len(_ro) > 6 else "")
              + ". The answers are kept in work/clarify_state.json and shown in the Gaps Report; "
              f"a value that must reach a card goes in work/repairs.json, and the lines below "
              f"give each one ready to paste.)")
        # D13: the same plan the ask-time handoff printed, now with the broker's actual answer
        # beside it, so applying it is a paste and not a reverse-engineering exercise
        for _ln in _recorded_only_guidance(work, _ro):
            print(_ln)
    _xf_pend = excluded_figure_questions(work, cfg, canonical)
    if _xf_pend:
        import clarify as _CQ35
        _xf_pend = _CQ35.pending(work, _xf_pend)
        if _xf_pend:
            _CQ35.emit(work, _xf_pend)
            if QUIET:
                print("One of your excluded sources disagrees with a shipped option's "
                      "size - your call which figure the card shows.")
            _say_orchestrator(
                f"(orchestrator: {len(_xf_pend)} excluded-figure question(s) for the "
                f"BROKER (exit 13) in {work / 'questions.json'} - put them to the user "
                f"in ONE plain message, write work/answers.json, re-run. Unanswered "
                f"ships the disclosed conflict as before.)")
            # The answer arrives through the ANSWER channel (clarify_state.json is a merge
            # input), so it applies pre-merge even though it lands as a repair. (A26)
            print(_reentry("premerge"))
            _exit_round_trip(work, 13, _attempts, "excluded-figure confirmation",
                             diagnosis=[f"question '{q['id']}' pending: asked once; "
                                        f"any answer or silence settles it next pass"
                                        for q in _xf_pend])

    # P1-4: re-surface the override OUTCOMES. merge printed them, but call() swallows child stdout
    # under --quiet - and a correction that matched NOTHING is precisely what must not be silent.
    # Read back from the report merge wrote, unconditionally.
    _ov_rep = work / "overrides_report.json"
    if _ov_rep.exists():
        try:
            _rep = json.loads(_ov_rep.read_text(encoding="utf-8-sig")) or {}
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
    # stamp: skip only when the inputs enrichment CONSUMES and the chosen flags exactly match
    # the last completed enrich. If merge changed a spatial field, or the flags changed, the
    # hash won't match and enrich re-runs. This keeps a resumed build byte-stable without
    # assuming enrich is perfectly idempotent offline.
    #
    # The hash is SCOPED to what enrichment reads (A1, see _enrich_input_hash): it used to be
    # a digest of the whole canonical file, so any correction to any field - a parking count, a
    # description, a translated sentence - re-ran the full enrichment pass including the
    # THROTTLED routing calls, for inputs that had not moved. Enrichment cannot be changed by a
    # parking-count correction, and the stamp now says so.
    stamp = work / ".enrich.stamp"
    enr_key = "|".join(sorted(enr_args))
    if enr_args:
        _stage("enrichment")
        step("Adding maps and extras")
        skip_enrich = False
        # ENRICHMENT DOES NOT ROUTE THROUGH `_is_current` (it has no single output file - it
        # mutates canonical in place), so --from/--only must be applied to its OWN skip
        # boolean, by the same predicate, or the one stage the flags most obviously exist to
        # skip would be the one stage that ignored them. (A2)
        if _stage_skipped("enrichment"):
            skip_enrich = True
        elif RESUME and stamp.exists():
            try:
                prev = json.loads(stamp.read_text(encoding="utf-8-sig"))
                _cur_hash = _enrich_input_hash(canonical)
                # A versioned stamp: a stamp from an older skill copy carries no `v` and its
                # `hash` answers a DIFFERENT question (whole-file bytes), so reading it as
                # current would skip enrichment on a canonical whose coordinates had moved.
                # Missing or wrong `v` is a miss. An empty `_cur_hash` (unreadable canonical /
                # no properties) is also a miss - a hash we cannot compute must never match.
                skip_enrich = (int(prev.get("v") or 0) == _ENRICH_STAMP_V
                               and prev.get("args") == enr_key
                               and bool(_cur_hash) and prev.get("hash") == _cur_hash)
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
                stamp.write_text(json.dumps({"v": _ENRICH_STAMP_V, "args": enr_key,
                                             "hash": _enrich_input_hash(canonical)}),
                                 encoding="utf-8")
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
            canon_data = json.loads(canonical.read_text(encoding="utf-8-sig"))
            enr_state = canon_data.get("meta", {}).get("enrichment", {})
        except Exception:
            canon_data, enr_state = {}, {}
        want = []
        # D9: a property with a STATED POSTCODE also has a question for the web round, even when
        # it already carries a coordinate. In Cowork the bundled gazetteer pins every European
        # town, so no property is coordinate-less and this clause used to hand over nothing -
        # which left the postcode request `web_enrich.plan` builds for an approximate pin never
        # asked, and D9 inert in the one environment it was written for. `postcodes_unasked` is
        # enrich.py's count of stated postcodes this pass could not put to a geocoder, in the
        # same shape as `pois_live` / `osrm_done`.
        if "--geocode" in enr_args and (any(
                not isinstance(p.get("lat"), (int, float)) and _filled(p.get("city"))
                for p in canon_data.get("properties", []))
                or enr_state.get("postcodes_unasked")):
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
                                           .read_text(encoding="utf-8-sig")).get("requests", []))
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
            canon_data = json.loads(canonical.read_text(encoding="utf-8-sig"))
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
                    _prev_decks = (json.loads(manifest.read_text(encoding="utf-8-sig"))
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
                # ASCII-SAFE ON PURPOSE (F8). This manifest is read by an agent, not by a human, and
                # the idiomatic `json.load(open(path))` an agent writes uses the platform's
                # DEFAULT text encoding. On a host whose default is not UTF-8 that raises
                # UnicodeDecodeError on the first non-ASCII byte, which was reproduced on a live
                # run. Escaped non-ASCII costs nothing in a machine-to-agent file and removes the
                # failure mode on every platform.
                manifest.write_text(json.dumps(payload, ensure_ascii=True, indent=2),
                                    encoding="utf-8")
                n_rl = len(region_jobs)
                _pl = _render_dispatch_prompts(work, [
                    ("region-labels", None,
                     {"N_LABELS": n_rl, "MANIFEST_PATH": str(manifest),
                      "OUTPUT_PATH": str(work / "extract" / "region_labels.json")})])
                if QUIET:
                    print("A few region labels in your files need matching to the workforce "
                          "dataset before I add the maps and extras.")
                    _say_orchestrator(
                        f"(orchestrator: dispatch the interpretation sub-agent for {n_rl} "
                        f"region label(s) per {manifest} -> work/extract/region_labels.json "
                        f"(reference/interpretation.md 'Region label resolution'), then "
                        f"re-run.{_pl})")
                else:
                    print(f"\nREGION LABEL RESOLUTION NEEDED ({n_rl} label(s)): dispatch the "
                          f"interpretation sub-agent per {manifest} -> "
                          f"work/extract/region_labels.json (reference/interpretation.md "
                          f"'Region label resolution'), then re-run.{_pl}")
                _exit_round_trip(work, 3, _attempts, "region-label resolution",
                                 diagnosis=[
                                     f"region label '{_rj.get('raw_label')}' "
                                     f"({_rj.get('country_cc')}, city {_rj.get('city')}) "
                                     f"pending: no resolution echoing raw_label+country_cc+city "
                                     f"in work/extract/region_labels.json"
                                     for _rj in region_jobs])

    # Stage 3.4 - property-keyed repairs. They run BEFORE the translation stage below, not
    # after it: that stage exits 12 to fetch a translation round, so a repair that introduces
    # prose used to be invisible until the pass AFTER the round, and every repair batch
    # carrying prose cost a whole extra round-trip plus an isolated agent dispatch (three of
    # them on one live run, for values that were already in the target language). The stage
    # requires the FINAL prose by its own docstring, and repairs are part of it.
    def _ledger_append(path, rows) -> None:
        """REPLACE the repair rows in the Source Ledger with `rows`, keeping ledger.COLUMNS order.

        Replace, not append: resume skips merge when nothing upstream changed, so the ledger
        merge wrote survives the next run and a plain append would duplicate every repair row
        on each pass - the ledger is the audit trail, and an audit trail that grows a copy of
        itself per run is worse than none. Dropping the previous `repair` rows first makes this
        idempotent, and a repair that has since been deleted or refused correctly disappears."""
        import csv as _csv
        import ledger as _ledger
        p = Path(path)
        kept = []
        if p.exists():
            with open(p, newline="", encoding="utf-8-sig") as _fh:
                kept = [r for r in _csv.DictReader(_fh)
                        if (r.get("record_type") or "").strip() != "repair"]
        with open(p, "w", newline="", encoding="utf-8") as _fh:
            w = _csv.DictWriter(_fh, fieldnames=_ledger.COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in kept + list(rows):
                w.writerow(r)

    # Repairs run HERE, after the dataset exists and BEFORE the gates, so validate-data,
    # arithmetic, coverage and trace-coverage judge the repaired data exactly as they judge
    # anything else, and the freeze happens over what actually ships. Each applied field
    # writes its own Source Ledger row, so a correction is disclosed in the same breath as
    # it is made. Outcomes are re-surfaced unconditionally: a repair that matched NOTHING is
    # precisely what must never be silent (the override path learned this the hard way).
    #
    # STAGE CONTROL (A2b). `repairs` is a name in STAGE_ORDER, so --from/--only VALIDATE it and
    # the help text promises every unnamed stage is "treated as current and skipped" - but this
    # stage had no skip guard at all, so of eleven vocabulary entries nine honoured the flags and
    # this one silently did not. `--only extract` still applied every repair and MUTATED
    # canonical; `--from build` re-applied the repairs the operator had just asked to skip. A
    # flag that half-works is worse than one that does not exist, because the operator plans
    # around the promise. Same shape as enrichment's own boolean above, and for the same reason:
    # repairs has no single output file to route through `_is_current` (it mutates canonical in
    # place), so the cut has to be applied to its own guard by the same predicate.
    #
    # RE-RUNNING THE APPLICATION IS IDEMPOTENT, which is what makes skipping it safe rather than
    # merely cheap: `repairs.run` re-derives every verdict from work/repairs.json against the
    # current canonical, and `_ledger_append` above DROPS the previous `repair` rows before
    # writing the new set - so applying twice yields one row per applied field, not two.
    # Skipping therefore leaves the previous pass's rows standing (correct: they describe
    # canonical as it stands), and un-skipping restates them exactly.
    #
    # ONE PRE-EXISTING ASYMMETRY, RECORDED HERE BECAUSE THE SKIP MAKES IT EASIER TO MEET, NOT
    # BECAUSE THE SKIP CAUSES IT: the drop-and-rewrite only happens inside `if _n_rep:` below,
    # so a pass in which NO repair applies (every entry has gone stale) does not rewrite the
    # ledger, and the previous pass's `repair` rows survive describing corrections that no
    # longer apply. Left alone deliberately: writing the ledger unconditionally here would
    # touch a file that is itself a resume input, churning its mtime on every pass for the
    # rare all-stale case. The Gaps Report still names each stale entry, so it is disclosed.
    _stage("repairs")
    if _stage_skipped("repairs"):
        _resumed("repairs")
    else:
        try:
            import repairs as _repairs
            _rrep = _repairs.run(work, write=True)
            # COERCE THE REPAIRED SCALARS (A3a). repairs.apply() writes its values straight into
            # canonical, which - because repairs run AFTER merge - bypasses
            # `merge.canonicalize` -> `C.fill_render_sentinels`, the ONLY place a well-meant
            # integer in a string-typed field is turned into a string. The OVERRIDE channel gets
            # that coercion for free simply because it applies pre-merge. Same audited human
            # channel, same `verified_by` attribution, same ledger row, and until now different
            # type rules: the asymmetry was one of stage ordering, not of intent. This closes it
            # with the same function, so the two paths cannot drift again.
            if _rrep.get("applied"):
                # THE CLEARED FIELDS ARE PASSED IN, not re-derived. `fill_render_sentinels`
                # puts every chrome-read key back, so this coercion used to re-fill exactly the
                # keys an applied `unset` had just removed - the verb silently did nothing on
                # any chrome-read field. The report already knows which fields were cleared,
                # so it is asked. See `_coerce_repaired_scalars` / `_repairs_cleared`.
                _n_coerced = _coerce_repaired_scalars(canonical, _repairs_cleared(_rrep))
                if _n_coerced and not QUIET:
                    print(f"({_n_coerced} repaired propert(y/ies) passed back through the render "
                          f"coercion - the same pass the override channel gets pre-merge.)",
                          file=sys.stderr)
            for _line in _repairs.format_report(_rrep):
                print(_line)
            # F24: a repair that moved a field with a DERIVED twin (officeArea -> officeAreaVal)
            # left the twin at merge's pre-repair value; re-derive now, and name any region-bind
            # input a repair moved. See _rederive_after_repairs for why the bind itself is not
            # re-run here. Inert when nothing applied, and inert when merge.py predates C2.
            if _rrep.get("applied"):
                for _line in _rederive_after_repairs(canonical, _rrep.get("applied"),
                                                     ledger=ledger_csv):
                    print(_line)
            _n_rep = len(_rrep.get("applied") or [])
            if _n_rep:
                _lrows = _repairs.ledger_rows(_rrep)
                if _lrows:
                    _ledger_append(work / "source_ledger.csv", _lrows)
                if not QUIET:
                    print(f"({_n_rep} property repair(s) applied - each has a `repair` row in "
                          f"the Source Ledger and a line in the Gaps Report.)", file=sys.stderr)
        except Exception as _e:
            print(f"(repairs skipped: {type(_e).__name__}: {_e})", file=sys.stderr)

    # --- Phase 2: free-text DATA translation to output.language (exit 12; mirrors exit 11) ----
    # Runs AFTER merge/enrich/web-enrich/region-label/REPAIRS have all settled canonical.json
    # (a translation must see the FINAL prose, not a value enrichment, a region-label bind or
    # a property repair might still touch) and BEFORE the pre-build gates score it. Determinism (translate.collect_requests/
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
            _canon_obj = json.loads(Path(canonical).read_text(encoding="utf-8-sig"))
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
        _pl = _render_dispatch_prompts(work, [
            ("translate-data", None,
             {"LANGUAGE": lang, "REQUEST_PATH": str(req), "CACHE_PATH": str(cache_f),
              "SKIP_PATH": str(work / "i18n" / "data_translate.SKIP")})])
        if QUIET:
            print(f"Translating the descriptions to {lang}… (one-time)")
            if _pl:
                _say_orchestrator(f"(orchestrator:{_pl})")
        else:
            print(f"\nDATA TRANSLATION NEEDED -> {lang}. Dispatch an ISOLATED translation sub-agent: "
                  f"translate the `items` in {req} (PROSE only; keep numbers/units/codes/names/dates "
                  f"verbatim), MERGE the returned {{text: translation}} map into "
                  f"{cache_f}, then re-run the SAME command. "
                  f"Blind-verify as G-lang before shipping. (Or `type nul > "
                  f"{work / 'i18n' / 'data_translate.SKIP'}` to ship the data in its source "
                  f"language.){_pl}")
        _exit_round_trip(work, 12, _attempts, "free-text data translation",
                         diagnosis=[
                             f"data translation to '{lang}' pending: items in {req} have no "
                             f"{{text: translation}} entry in {cache_f} (or drop "
                             f"{work / 'i18n' / 'data_translate.SKIP'} to decline)"])

    # Stage 3.5 - the read-only per-property projection. AFTER the translation stage, so the
    # view a human opens shows the prose that actually ships rather than its source language.
    #
    # STAGE CONTROL (A2b), the second of the two vocabulary entries that had no skip guard. It
    # matters less than repairs (the projection is strictly DERIVED and writes nothing any other
    # stage reads, so re-running it cannot change what ships) and it is exactly why it should be
    # skippable: on a media-heavy run it re-renders the considered set for every property, which
    # is the most expensive thing in the pipeline that an operator narrowing to `--only build`
    # cannot possibly want. Nine of eleven stages honoured the flags; this makes it eleven.
    # Own boolean rather than `_is_current`, like repairs and enrichment: the projection's
    # output is a whole directory tree, not one file whose mtime answers the question.
    _stage("projection")
    if _stage_skipped("projection"):
        _resumed("projection")
    else:
        try:
            import project_properties as _proj
            # --source-dir/--image-cache turn on the CONSIDERED SET: per property, every page
            # render and candidate image it had to choose from, plus media_decisions.json, plus a
            # once-per-run _unassigned/ for deck pages no property claimed. Still strictly
            # derived - the projection reads canonical + merge's media_considered.json sidecar
            # and writes nothing either reads.
            # F20: NO MEDIA VIEW ON THE ORDINARY PASS. Measured: the projection was 42.06s of a
            # 50.30s pass (84%) while building the dashboard took 0.15s, and it was rebuilding
            # an 82 MB tree of page renders that nothing downstream reads. B5 measured the two
            # settings: 52.1s / 354 files / 86.2 MB with media, 0.49s / 28 files / 0.17 MB
            # without. The data half (property.json, sources.csv, notes.md, index.json) is
            # still written every pass; the pixels are written by `_full_view_for_humans` ONLY
            # when a pre-build gate has blocked, which is when a human is about to go looking.
            _pr = _proj.build(work, source_dir=folder, image_cache=work / ".image_cache",
                              media_view="never")
            if not QUIET:
                print(f"(per-property view: {_pr['count']} folder(s) under work/properties/ - "
                      f"read-only; corrections go in work/repairs.json"
                      + (f"; {_pr['unassigned']} unclaimed deck page(s) in properties/_unassigned/"
                         if _pr.get("unassigned") else "") + ")", file=sys.stderr)
                print("(media half skipped - written automatically if a pre-build gate blocks; "
                      "to write it now: "
                      + _proj.rebuild_command(work, folder, work / ".image_cache") + ")",
                      file=sys.stderr)
        except Exception as _e:
            print(f"(per-property view skipped: {type(_e).__name__}: {_e})", file=sys.stderr)

    # Stage 4 - pre-build gates (mechanical halves; judgement gates run separately)
    _stage("gates:pre")   # NEVER skipped: _NEVER_SKIP, proved by _assert_stage_control_safe
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
    # B-gate-automation: input-accounting and capture-symmetry are both fully mechanical
    # and deterministic, so the spine runs them itself instead of asking the orchestrator
    # to remember a manual step "alongside the batch". input-accounting can genuinely
    # block (a whole source vanished with nothing recorded); capture-symmetry always
    # returns 0 (it is an advisory cross-source asymmetry report for the G-honesty/G-trace
    # reviewers) - appending its result to g1 is harmless and keeps its notes in the same
    # scorecard file the reviewers already read.
    g1.append(run_gate(gate_runner, "input-accounting", canonical, "--work", work))
    g1.append(run_gate(gate_runner, "capture-symmetry", "--work", work))
    # ...and its twin one layer over: capture-symmetry asks whether a reader skipped FIELDS a
    # page printed, media-harvest asks whether the harvest skipped IMAGES a deck holds. Same
    # idiom, same scorecard - but NOT always 0: its two HARD-FACT signals (a media capability
    # the probe says is unavailable, and a text deck whose interpretation agent got zero page
    # renders) BLOCK, because both mean a whole tier did not run and both are invisible in every
    # other artefact. Its three heuristic signals stay advisory. Both blocks are cleared by an
    # explicit `gate_runner.py ack` key - the gate's message names the exact command.
    g1.append(run_gate(gate_runner, "media-harvest", canonical, "--work", work))
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
    vf_rc = run_gate(gate_runner, "value-format", canonical,
                     "--emit-json", work / "value_format_findings.json",
                     "--waivers", work / "value_format_waivers.json")
    g1.append(vf_rc)
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
    #
    # ONE CLASSIFICATION, NOT THREE SHORT-CIRCUITING `if`s. (A5) Every pre-build gate already
    # runs unconditionally above, and gate1_scorecard.md already lists every blocked one - what
    # was lossy was only the EXIT: three sequential `if` blocks, each of which exits, so a run
    # red on validate-data AND value-format AND coverage reported exactly one of them. The
    # operator fixed that one, re-ran, and met the next - paying a full pass per gate class to
    # discover a list the run already had in hand. So: name EVERY blocked class first, once,
    # then choose the exit code by priority.
    #
    # PRIORITY, and why it is not a merge: validate-data (5) outranks a value-format
    # clarification (13) outranks any other pre-build gate (6), because that is the order in
    # which the orchestrator can ACT - a schema defect makes the clarification question
    # unanswerable, and both make the generic "fix and re-run" useless. The three branches keep
    # their own message content and the 13 path keeps _exit_round_trip (its streak/diagnosis
    # accounting is what stops a clarification livelock).
    #
    # DELIBERATELY NOT merged with the post-build gates below: `sys.exit(6)` BEFORE the build
    # is the shift-left, and folding it into one late classification would restore exactly the
    # wasted build + post-gates + deliver this comment opens by describing.
    if any(rc != 0 for rc in g1):
        _blocked = blocked_gate_names()
        # F20: a human is about to go looking, so NOW write the full per-property view
        # (the media half the ordinary pass skips). Never before this point.
        _full_view_for_humans(work, folder)
        _say_orchestrator(
            f"(orchestrator: {len(_blocked) or sum(1 for rc in g1 if rc != 0)} pre-build gate "
            f"class(es) BLOCKED this pass: {', '.join(_blocked) or 'see the scorecard'}. THAT IS "
            f"THE COMPLETE LIST - every gate ran; the exit code below is the highest-priority "
            f"one, not the only one. Fix them together: {work / 'gate1_scorecard.md'} has the "
            f"specifics for each.)")
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
            # A CORRECTION EXIT WITH NO RE-ENTRY HINT. The helper was called at eight sites and
            # at none of the three commonest correction exits, against an item claiming it is
            # "printed at each correction exit". A schema/consistency defect is fixable through
            # EITHER channel - a wrongly-typed or withdrawn value is a repair, a mis-bound
            # column or a wrong source reading is an override or an input fix - so the hint
            # names both rather than picking one (see _reentry("either")).
            print(_reentry("either"))
            sys.exit(5)
        # B59 -> exit 13: the value-format gate's remedy used to be SKILL.md prose telling
        # the orchestrator to ask the broker - the one documented prose ask. Bridge it:
        # answers become attributed repairs (applied before the gates next pass), declines
        # become waivers the gate notes, anything undecided is a BLOCKING broker question.
        if vf_rc != 0:
            vf_rep, vf_wv, vf_pend = value_format_clarify(work, canonical)
            if vf_pend:
                n_q = len(vf_pend)
                if QUIET:
                    print("One of your files writes a value differently from its siblings - I need "
                          "you to confirm its unit before I can finish.")
                _say_orchestrator(
                    f"(orchestrator: {n_q} value-format clarification(s) needed (exit 13) - the "
                    f"questions are in {work / 'questions.json'}; put the broker questions to the "
                    f"user in ONE plain message, write work/answers.json, re-run. An answer becomes "
                    f"an attributed repair; 'leave as is' ships the bare value disclosed.)")
                print(_reentry("premerge"))  # an ANSWER is consumed by/before merge (A26)
                _exit_round_trip(work, 13, _attempts, "value-format clarification",
                                 diagnosis=[f"question '{q.get('id')}' (asked_of: broker) pending: "
                                            f"no answer or decline for that exact id in "
                                            f"work/answers.json" for q in vf_pend])
            if vf_rep or vf_wv:
                _say_orchestrator(
                    f"(orchestrator: value-format answers recorded - {vf_rep} repair(s) appended to "
                    f"work/repairs.json, {vf_wv} bare value(s) waived by broker decision. Re-run the "
                    f"same command: repairs apply before the gates.)")
                # A REPAIR applies post-merge, so merge and enrichment cannot be changed by it (A26)
                print(_reentry("repair"))
        if QUIET:
            print("A quality check on the data needs sorting before I can finish the dashboard - "
                  "I can't hand it over as it stands.")
            _say_orchestrator(
                f"(orchestrator: {sum(1 for rc in g1 if rc != 0)} pre-build gate(s) BLOCKED (exit 6) - "
                f"see {work / 'gate1_scorecard.md'}, fix, and re-run; resume skips clean stages.)")
        else:
            print(f"\nBLOCKED: {sum(1 for rc in g1 if rc != 0)} pre-build gate(s) red - not building. "
                  f"See {work / 'gate1_scorecard.md'}, fix, and re-run (resume skips clean stages).")
        # THE OTHER MISSING HINT, and the one with the clearest case for being here: exit 6 is
        # where the blocking title-collision gate lands, and that gate's own message names a
        # `work/repairs.json` set as its remedy - the repair channel, whose cheap re-entry is
        # therefore valid and was simply never offered. Exit 6 is the catch-all for every other
        # pre-build gate too, so the channel genuinely depends on which gate is red and on how
        # the operator chooses to fix it; the hint says that instead of guessing.
        print(_reentry("either"))
        sys.exit(6)

    # Stage 5 - build
    _stage("build")
    step("Building the dashboard")
    # SANITISED FOR THE FILENAME ONLY (F14). `deliver` honours `--filename` byte-for-byte on
    # purpose, because run.py looks the delivered file up under that name, so the composing has
    # to be safe HERE. A broker types the client name as free text in the Stage-0 form, and one
    # containing a full stop used to yield a double dot before the extension. The DISPLAYED
    # client name and every ledger row keep the broker's exact text; only the filename is slugged.
    import deliver as _dlv          # lazy, like every other deliver use in this file
    filename = ((cfg.get("output") or {}).get("filename")
                or f"CBRE_Property_Dashboard_{_dlv.safe_slug(args.client)}.html")
    built = work / "built.html"
    # AUTO-INVALIDATE on a code change, because build is CHEAP - a measured ~0.07-0.3 s, so a
    # spurious rebuild costs nothing and a missed one used to be an exit-7 'chrome drift' dead
    # end that no re-run could clear. This is the render closure, verified: anything else cannot
    # change built.html for a fixed canonical. (B42)
    _build_stamp = _code_stamp(work, "build", [
        HERE / "build_dashboard.py", HERE / "i18n.py", HERE / "normalize.py",
        HERE / "_common.py", HERE.parent / "assets" / "dashboard_template.html"])
    # trailing `or` clause for the same two reasons as the merge site above: code_stamp_test
    # anchors on this expression's exact text to prove the build stamp is IN the input list.
    if _is_current(built, [canonical, _build_stamp]) or _stage_skipped("build"):
        _resumed("build")  # built.html already reflects the current canonical
    else:
        call(build_dashboard, canonical, "--out", built)

    # Stage 6 - post-build gates (mechanical; G-visual runs separately via MCP)
    _stage("gates:post")  # NEVER skipped: _NEVER_SKIP, proved by _assert_stage_control_safe
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
    # The client-facing output folder ('3. Output' in the three-folder layout, or the legacy
    # '<work>/deliverables'). Resolved once, at startup, by _resolve_layout.
    deliverables = out_dir
    _stage("deliver")
    # qa_state.json is load-bearing, not decorative: final_gate BLOCKS when the delivered Gaps
    # Report's "Known limitations" is not the LATEST recorded round's carried list. Without it
    # here, a fresh `qa-round record` leaves Stage 7 looking current, --resume (the DEFAULT) skips
    # the re-deliver, and that block can never be cleared through the spine. With it, the stage is
    # stale exactly once: re-delivering bumps the dashboard past qa_state.json, so the next run
    # resume-skips again. No oscillation.
    _deliver_inputs = [built, canonical, ledger_csv,
                       work / "photo_doubts.json", work / "unreadable.json",
                       work / "yield_report.md", work / "qa_state.json",
                       # clarify_state carries the Clarifications and "Noted, not put to
                       # you" sections, and NOTHING else in the deliverables carries them:
                       # __meta.doubts never reaches canonical.json, so a re-extraction that
                       # changes only a reader's doubts leaves canonical byte-identical and
                       # deliver would resume-skip the one file that discloses them. (B62)
                       work / "clarify_state.json",
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
    if _is_current(deliverables / filename, _deliver_inputs, stage="deliver") \
            and _deliver_mod.delivery_complete(deliverables, work):
        _resumed("deliver")
    else:
        call(deliver, "--canonical", canonical, "--html", built,
             "--ledger", ledger_csv, "--out-dir", deliverables, "--slug", args.client,
             "--filename", filename, "--marker-dir", work)

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
    # P1: render the QA-window reviewer prompts (one blind agent per gate; G-enrich only when
    # regions were enriched). The round dir is the FIRST reviews/round<N> that holds no
    # findings yet, matching gates.md's "a round-2 reviewer must write a NEW file".
    _stage("qa")  # NEVER skipped: _NEVER_SKIP, proved by _assert_stage_control_safe
    _rn = 1
    while any((work / "reviews" / f"round{_rn}").glob("*.md")):
        _rn += 1
    _rdir = work / "reviews" / f"round{_rn}"
    _gate_slots = {"WORK": str(work), "REVIEWS_ROUND_DIR": str(_rdir)}
    _gjobs = [("g-honesty", None, dict(_gate_slots)),
              ("g-trace", None, dict(_gate_slots)),
              ("g-images", None, dict(_gate_slots)),
              ("g-visual", None, dict(_gate_slots, HTML_PATH=str(built)))]
    if bool((cfg.get("enrichment") or {}).get("regions") or args.regions):
        _gjobs.append(("g-enrich", None, dict(_gate_slots)))
    _pl_qa = _render_dispatch_prompts(work, _gjobs)
    # -------- QA WINDOW, LOOP-DRIVEN (workstream 1 item 1.2) -------------------
    # The one phase that was ordered by prose runs on exit codes like every other:
    #   exit 14 - independent reviews missing: dispatch work/prompts/g-*.md, re-run
    #   exit 15 - blocking findings unresolved: implement + qa-round resolve, re-run
    #   exit 0  - recorded pass, advisories folded into the Gaps Report, final_gate
    #             green: DONE-DONE. Nothing in this phase is orchestrator-remembered.
    _esrc = ((cfg.get("inputs") or {}).get("emails") or {}).get("source", "none")
    _extra_steps = []
    if _esrc in ("outlook", "folder"):
        _extra_steps.append("the configured email ingestion (Stage 1, prompts/outlook-ingest.md)"
                            " if its records are not already in")

    def _review_file(kind: str) -> str:
        return ("G-" + kind[2:] if kind.startswith("g-") else kind) + ".md"

    _missing = [k for (k, _n2, _s2) in _gjobs
                if not list((work / "reviews").glob(f"round*/{_review_file(k)}"))]
    if _missing:
        if QUIET:
            step("Final checks - independent review")
            print("An independent check of the data runs before handover - one moment.")
        _say_orchestrator(
            f"(orchestrator: independent QA review needed (exit 14). Dispatch ONE isolated "
            f"sub-agent per rendered prompt - {', '.join(sorted(k + '.md' for k in _missing))} "
            f"in {work / 'prompts'} - each file is that agent's VERBATIM instruction and names "
            f"its own output file; dispatch them CONCURRENTLY, then re-run the same command."
            + (f" Also outstanding: {'; '.join(_extra_steps)}." if _extra_steps else "") + ")")
        _exit_round_trip(work, 14, _attempts, "the independent QA review",
                         diagnosis=[f"review '{k}' pending: no reviews/round*/"
                                    f"{_review_file(k)} exists yet" for k in _missing])
    if gate_runner.qa_round_number(work) == 0 or qa_reviews_changed(work):
        # reviews are in - record them. EXACTLY ONE ROUND, EVERY RUN, WITHOUT EXCEPTION:
        # `record` writes into the single round slot and never opens another, and reviews
        # that change after it is recorded fold into that same round as extra findings. So
        # this guard is no longer about round inflation (it cannot happen); it is about not
        # spending a subprocess on a pass with nothing new to read, keyed on a FINGERPRINT
        # of the review files rather than the round count because a round-count-only guard
        # made every post-record review unrecordable - the incident in `qa_reviews_changed`.
        #
        # The two exits below are the rest of the shape, and neither is a second round. Exit
        # 14 (reviews missing) dispatches the reviewers ONCE. Exit 15 is a fix loop WITHIN
        # this round: implement, `qa-round resolve`, re-run - it never re-dispatches a
        # reviewer. Advisory findings are not forced by either: an advisory that is one edit
        # and changes what a reader concludes is worth fixing, and the rest ship disclosed as
        # Known limitations. That call is the operator's and there is no threshold for it.
        rc_rec = call(gate_runner, "qa-round", "record", "--work", work,
                      "--reviews", work / "reviews", check=False)
        if rc_rec == 0:
            qa_reviews_stamp(work)
    _open_findings = gate_runner.qa_blocking_open(work)
    if _open_findings:
        if QUIET:
            print("The independent review found something I must fix before handover.")
        _say_orchestrator(
            f"(orchestrator: {len(_open_findings)} blocking QA finding(s) unresolved "
            f"(exit 15). IMPLEMENT each fix, then record it: `gate_runner.py qa-round "
            f"resolve --work \"{work}\" --id <id> --because \"<what you changed>\"`, then "
            f"re-run the same command. Ids + findings: `gate_runner.py qa-round status "
            f"--work \"{work}\"` (also in {work / 'qa_state.json'}). An ADVISORY finding "
            f"is never fixed - it ships in the Gaps Report's Known limitations.)")
        # THE THIRD MISSING HINT. A blocking QA finding is the most open-ended of the three:
        # the fix can be an attributed repair, an override, a re-read of an input, or a code
        # change - and `--from repairs` would SKIP the stage a code or input fix lands in. So
        # the hint is the both-channels one, deliberately, and the operator picks by what they
        # actually changed rather than by what a message assumed.
        print(_reentry("either"))
        _exit_round_trip(work, 15, _attempts, "the QA improvement pass",
                         diagnosis=[f"blocking finding '{e['id']}' pending: no qa-round "
                                    f"resolve recorded for that exact id"
                                    for e in _open_findings])
    # recorded pass: RE-deliver so the Gaps Report carries the round's advisories as
    # 'Known limitations', then the ship backstop - run inside the loop, so exit 0
    # can only ever mean final_gate went green
    call(deliver, "--canonical", canonical, "--html", built, "--ledger", ledger_csv,
         "--out-dir", deliverables, "--slug", args.client, "--filename", filename,
         "--marker-dir", work)
    import final_gate as _final_gate_mod
    rc_fg = run_gate(_final_gate_mod, "--canonical", canonical, "--html", built,
                     "--deliverables", deliverables, "--reviews", work / "reviews",
                     "--qa-state", work)
    write_scorecard(work / "final_gate_report.md", "Ship gate (final_gate)")
    if rc_fg != 0:
        if QUIET:
            print("A final check refused the handover - it needs sorting before the "
                  "dashboard goes out.")
        _say_orchestrator(
            f"(orchestrator: final_gate BLOCKED (exit 7) - each reason is in "
            f"{work / 'final_gate_report.md'}; fix and re-run the same command.)")
        sys.exit(7)
    _clear_attempts(work)  # done-done: no request is outstanding
    if QUIET:
        step("Done - dashboard ready")
        # P3-10: tell the broker WHERE the deliverable is, and flag the Gaps Report ONLY
        # when there are REAL gaps to chase (not merely because the file always exists);
        # the helper mirrors every section deliver.gaps_report emits.
        print(f"Your dashboard and its files are ready in {deliverables}.")
        if _gaps_to_chase(canonical, failed_preps, photo_doubts, unreadable_inputs,
                          yield_notes, work):
            print("Some details are still missing - see the Gaps Report in that folder "
                  "for what to chase with the landlord or agent.")
    else:
        print(f"\nDONE. Deliverables in {deliverables} - QA round recorded, advisories "
              f"folded into the Gaps Report, final gate green. Nothing left to run.")


if __name__ == "__main__":
    main()
