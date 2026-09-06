#!/usr/bin/env python3
"""stage_control_test.py - the STAGE-CONTROL + CACHE-KEY contract (2026-09-03).

Five things landed together, and they only work as a set: none of them is safe unless the
others hold. This eval pins the joins, unit-level, offline.

  A0c THE INSTRUMENT OVERWROTE ITS OWN BASELINE. `_RUN_T0` is stamped at MODULE IMPORT, which
      is the whole point - the helper imports, preflight and the engine probe all happen before
      the work dir is resolved, so they can only ever be inside `total_s`, never inside a
      stage, and `_write_timings`' "start-up Xs" tail exists to name exactly that gap. But
      `_register_timings` re-based `_RUN_T0` on EVERY call, including the first, and deducted
      the lot: 2.43s of real start-up dropped, 1.3s printed against 3.77s actual, and the
      residual then always under the 0.05s print threshold, so the line built to name the
      missing time could never fire. Pinned in both directions, and the first one against a
      REAL process, because nothing in-process can see the import-time baseline: total_s on
      disk must EXCEED the stage sum, the tail must be on screen, arm #1 must not move
      `_RUN_T0`, and arm #2 still must (that reset is what makes an in-process second run
      measure itself).

  A0  work/timings.json is the instrument the other four are judged by. It is worthless if
      its stage names drift from the vocabulary --from/--only validate against: a log naming
      "enrich" while the flag wants "enrichment" prints a re-entry command nobody can type.
      So the SHAPE and the SPELLING are both pinned, and `resumed` is pinned as a LIST -
      _resumed() is called per whole stage AND per input file, and collapsing a 40-tracker
      extract that resumed 39 to a boolean discards the only number that explains the cost.
      A0b: the artefact's CENTRAL claim - "a pass that stops at ANY handoff exit still records
      what it spent" - was pinned only by calling the payload builder in-process and matching a
      literal in the source. That proves nothing about a real exit. It now DRIVES A PROCESS to
      a non-zero exit and reads the file off disk. And the handler must never CREATE the
      directory it writes into: given a deleted work dir it used to resurrect the tree at
      interpreter shutdown, holding one lone timings.json that nothing on screen accounted for.

  A1  the enrich resume stamp hashed the WHOLE canonical file, so every correction channel
      (a repair, an override, an answer, a translation) re-ran the throttled routing calls
      for fields enrichment cannot read. Pinned both ways: a non-spatial change must NOT move
      the hash, and `lat` MUST.
      A1c THE GUARD THAT WAS SUPPOSED TO PREVENT A1b COULD NOT SEE THE READ. A1b's scan is a
      regex for a LITERAL `p.get("x")` / p["x"] on a property, so it only ever saw reads
      enrich.py performs ITSELF - and it duly reported BOTH `postcode` and `postalCode` as read
      nowhere. They are read, one module hop out: `_locality_code` delegates to
      `match._stated_postcode`, which walks `match._POSTCODE_FIELDS`, and the answer is the
      THIRD segment of the geocode cache key. `postalCode` was therefore absent from the resume
      key, two canonicals differing only in it hashed identically, enrichment was falsely
      skipped and a town-centre pin shipped - the `mapLink` incident again, hidden behind a
      delegation instead of behind a function name. The scan now FOLLOWS the delegation (AST,
      not regex: which match.py helpers enrich.py calls, and which module-level field-name
      tuples those helpers reach), so a field enrichment reads through a helper cannot escape
      the key either.

      A1b: THE DIRECTION WAS PINNED, THE SUFFICIENCY WAS NOT - and sufficiency is the entire
      risk. Both lists here were transcriptions of the field-set constant, so the eval could
      only ever agree with whatever the constant said; `mapLink` was in neither list and sailed
      through, and it IS an enrichment input (a short maps link is followed and writes
      lat/lng). The consequence in the field: an operator supplies the real pin as a
      correction, the hash does not move, enrichment is skipped and the town-centre pin ships.
      So the hashed set is now compared against what enrich.py ACTUALLY reads, scanned from its
      source, and any divergence in either direction FAILS - a future input added to enrichment
      cannot silently escape the key.

  A2  --from/--only skip stages regardless of --resume, which is the point - and is also
      exactly why the gates must be unreachable by them. Pinned against the LIVE predicate,
      over every flag combination that could name them, not against a comment.
      A2b: nine of the eleven vocabulary entries honoured the flags. `repairs` and `projection`
      had no skip guard at all, so `--only extract` still applied every repair and MUTATED
      canonical, and `--from build` re-applied the repairs the operator had asked to skip -
      against a help text promising every other stage is treated as current. Pinned by DERIVING
      the requirement: every skippable stage in STAGE_ORDER must consult the predicate inside
      its own segment of main(), so a stage added to the vocabulary without a guard fails here.
      A2c: AND THAT PIN COULD NOT FAIL. Both A2b groups asserted only that a SOURCE SUBSTRING
      (`if _stage_skipped("repairs"):`) appears somewhere in run.py. A reviewer changed the
      guard's `else:` to `if True:` - so the repairs stage always ran, mutating canonical on a
      pass the operator had scoped away - and this eval stayed fully green with zero failing
      assertions, leaving the remediated guard completely unprotected. Both groups are now
      BEHAVIOURAL: the guard is located STRUCTURALLY in main()'s AST (the statement
      immediately after the stage boundary, testing `_stage_skipped("<name>")`, with a
      non-empty `else`), nothing after it may reach the stage's worker, and the guard is then
      EXECUTED both ways with the worker module replaced by a recorder - skipped must not call
      it, not-skipped must.

  A21 the tracker column-map cache was keyed on the whole tracker structure, which carries
      greedily-sampled DATA rows - so editing one data cell in a schema-identical sheet
      invalidated a settled column map and re-opened the interpretation handoff (an exit 3,
      a sub-agent, an operator round-trip, for a corrected postcode). Pinned: stable across a
      data-cell edit, sensitive to a header edit.
      A21b: and now sensitive to the EXTRACTOR CODE. `unmapped_headers` catches an alias-table
      change that moves a header in or out of the unmapped list, never one that RE-POINTS an
      already-mapped header at a different field: sheets, headers and unmapped list are then
      identical, the key is stable, and a settled map is reused over a dictionary that now
      disagrees. A pre-existing hole the narrowing exposed rather than created.

  A4  a correction file's faults are reported ALL AT ONCE at startup. That is a behaviour
      change, not a message change: at one full pass per fault the rational operator writes
      one correction at a time, which is the slowest possible way to use the channel. Pinned
      with a file carrying three DISTINCT faults - all three must appear in one pass.
      A4b: it must exit 16, not 5. Exit 5's mapped action in SKILL.md is "read
      gate1_scorecard.md, record the correction in work/overrides.json" - a scorecard that does
      not exist yet on a first pass, and an instruction to APPEND to the very file being
      rejected. An orchestrator following the contract appended, re-ran, was refused, appended
      again, with no brake because the path called sys.exit directly. Pinned by RUNNING it.

  T1b the resume predicate's recursive directory walk counted the run's own output tree, so a
      work dir placed INSIDE the inputs folder made the folder scan permanently un-current.
      intake.discover has excluded it since T1; the predicate never got the same parameter.
      (workdir_exclusion_test covers the intake half and only that half - it imports intake and
      never touches the predicate, so the predicate half is pinned here.)

Offline except for a handful of deliberate subprocess runs. Run:
python evals/stage_control_test.py"""
from __future__ import annotations

import ast
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C     # noqa: E402
import repairs as REP   # noqa: E402
import run as R         # noqa: E402

# The FROZEN vocabulary, restated here on purpose: an eval that imported the constant it is
# checking would pass on any rename, including a rename that breaks every operator's muscle
# memory and every re-entry hint already printed into a work dir's logs.
FROZEN = ["folder scan", "extract", "merge", "enrichment", "repairs", "projection",
          "gates:pre", "build", "gates:post", "deliver", "qa"]
NEVER_SKIP = ["gates:pre", "gates:post", "qa"]


def _canonical(props) -> dict:
    return {"meta": {}, "properties": props, "pois": [], "regions": []}


def _prop(pid, **kw) -> dict:
    # `mapLink` is present on the BASE property deliberately (A1b): it is an enrichment input
    # (resolve_map_links follows a short maps link and writes lat/lng), it is a first-class
    # correction target, and it was missing from both of A1's lists - so a base property
    # without one could not have caught that.
    p = {"id": pid, "lat": 52.0 + pid, "lng": 5.0 + pid, "city": f"City{pid}",
         "country": "NL", "postcode": f"{1000 + pid} AA", "region": f"Region{pid}",
         "regionCode": f"NL{pid}", "park": f"Park {pid}", "developer": "Dev",
         "status": "Available", "photo": "", "loadingDocks": "12",
         "mapLink": f"https://maps.app.goo.gl/prop{pid}"}
    p.update(kw)
    return p


def _project(root: Path, corrections: dict | None = None) -> tuple:
    """A minimal --project layout: (root, work). `corrections` maps a correction filename to
    its JSON payload, written into the work dir where the startup check reads it."""
    (root / "1. Input").mkdir(parents=True, exist_ok=True)
    work = root / "2. Work Files"
    work.mkdir(parents=True, exist_ok=True)
    for name, payload in (corrections or {}).items():
        (work / name).write_text(json.dumps(payload), encoding="utf-8")
    return root, work


def _spine(root: Path, *extra, timeout=300):
    """Run the real spine against `root` and return the CompletedProcess. Used where the claim
    under test is about a PROCESS (an exit code, a file on disk) rather than about a helper."""
    return subprocess.run([sys.executable, str(HELPERS / "run.py"), "--project", str(root),
                           *extra], capture_output=True, text=True, timeout=timeout)


def main() -> int:
    try:  # force UTF-8 so the suite also completes on a cp1252 mcp__shell console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    run_src = (HELPERS / "run.py").read_text(encoding="utf-8")

    # ================= A0: the timing artefact's shape and vocabulary ==================
    print("\nA0: work/timings.json - documented shape, vocabulary-clean stage names")
    ck(list(R.STAGE_ORDER) == FROZEN,
       f"STAGE_ORDER is the frozen vocabulary, in order ({', '.join(R.STAGE_ORDER)})")

    R._STAGE_LOG.clear()
    R._stage("folder scan")
    R._resumed("folder scan")
    R._stage("extract")
    R._resumed("a.xlsx extract")      # per-INPUT-FILE label
    R._resumed("b.xlsx extract")      # ...twice, which is why `resumed` is a list
    R._stage("merge")
    R._close_open_stage()
    payload = R._timings_payload()

    ck(set(payload) == {"started", "total_s", "stages"},
       f"top level is exactly {{started, total_s, stages}} (got {sorted(payload)})")
    ck(isinstance(payload["total_s"], float),
       f"total_s is a float ({payload['total_s']})")
    ck(bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(payload["started"]))),
       f"started is iso8601 ({payload['started']})")
    ck(all(set(s) == {"stage", "seconds", "resumed"} for s in payload["stages"]),
       "every stage entry is exactly {stage, seconds, resumed} - no private bookkeeping key "
       "leaks into the artefact")
    _names = [s["stage"] for s in payload["stages"]]
    ck(all(n in FROZEN for n in _names),
       f"every recorded stage name is from the frozen vocabulary ({_names})")
    ck(all(isinstance(s["resumed"], list) for s in payload["stages"]),
       "`resumed` is a LIST of labels, not a boolean")
    _ex = [s for s in payload["stages"] if s["stage"] == "extract"][0]
    ck(_ex["resumed"] == ["a.xlsx extract", "b.xlsx extract"],
       f"both per-file resume labels land on the open stage ({_ex['resumed']})")
    ck(all(isinstance(s["seconds"], float) and s["seconds"] >= 0 for s in payload["stages"]),
       "every stage carries a non-negative float `seconds` (a closed stage, not an open one)")

    # The stage boundaries actually exist in the spine, at every name in the vocabulary. A
    # timing log that silently omits a stage is a lie about where the time went, so this is
    # checked against the SOURCE, not just the helper.
    _missing = [s for s in FROZEN if f'_stage("{s}")' not in run_src]
    ck(not _missing, f"run.py opens every stage in the vocabulary (missing: {_missing})")
    ck("atexit.register(_write_timings" in run_src,
       "timings.json is written from an atexit handler, so a run that stops at ANY handoff "
       "exit still records what it spent")
    _reg = run_src.find("_register_timings(work)")
    _first_stage = min((run_src.find(f'_stage("{s}")') for s in FROZEN
                        if run_src.find(f'_stage("{s}")') > 0), default=-1)
    ck(_reg > 0 and _first_stage > _reg,
       "the handler is armed once the work dir is resolved and BEFORE the first stage opens")
    # It must print in QUIET mode - attributing time is what the operator needs, and SKILL.md
    # tells the orchestrator to run quiet. Checked against the CODE only: the docstring
    # explains the reasoning and necessarily quotes the very construct being forbidden.
    _wt = run_src[run_src.find("def _write_timings"):]
    _wt = _wt[:_wt.find("\ndef _register_timings")]
    _wt_body = _wt[_wt.find('"""', _wt.find('"""') + 3) + 3:]   # after the docstring
    ck("QUIET" not in _wt_body and 'step(f"Time:' in _wt_body,
       "the summary line is NOT gated on --verbose (it prints in quiet, the default)")
    ck("sorted(" in _wt_body and "[:3]" in _wt_body,
       "the summary names the three most expensive stages, not just a total")
    ck("timings.json" in _wt_body and "{path}" in _wt_body,
       "and it names the path the artefact was written to")

    # ---- A0b: the artefact's CENTRAL claim, driven through a REAL PROCESS ----------------
    # Everything above calls the payload builder in-process, and the two lines before this
    # match literals in the source. Neither can fail if the atexit handler never fires, never
    # writes, or writes somewhere else - which is the entire claim ("a pass that stops at ANY
    # handoff exit still records what it spent"). So: run the spine, make it exit NON-ZERO, and
    # read the file off disk. An empty inputs folder exits 2 after the folder scan and the
    # extract stage have both opened, which is exactly the shape worth checking - a handoff
    # exit mid-pipeline, not a clean finish.
    print("\nA0b: a real process that exits non-zero leaves the artefact on disk")
    with tempfile.TemporaryDirectory() as td_s:
        _root, _work = _project(Path(td_s))
        _rc0 = _spine(_root)
        _tf = _work / "timings.json"
        ck(_rc0.returncode != 0,
           f"the pass ended at a handoff exit, not a clean finish (exit {_rc0.returncode})")
        ck(_tf.exists(), f"work/timings.json exists after that non-zero exit ({_tf})")
        _disk = json.loads(_tf.read_text(encoding="utf-8-sig")) if _tf.exists() else {}
        ck(set(_disk) == {"started", "total_s", "stages"},
           f"the file on disk carries the documented top level (got {sorted(_disk)})")
        ck(isinstance(_disk.get("total_s"), float) and _disk["total_s"] >= 0,
           f"total_s on disk is a non-negative float ({_disk.get('total_s')})")
        ck(bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(_disk.get("started")))),
           f"started on disk is iso8601 ({_disk.get('started')!r})")
        _dn = [s.get("stage") for s in (_disk.get("stages") or [])]
        ck(bool(_dn) and all(n in FROZEN for n in _dn),
           f"the stages that actually ran are recorded, all from the vocabulary ({_dn})")
        ck(all(set(s) == {"stage", "seconds", "resumed"} and isinstance(s["resumed"], list)
               for s in (_disk.get("stages") or [])),
           "and every entry on disk has the same three keys, `resumed` still a list")
        ck("Time:" in (_rc0.stdout or ""),
           "the summary line reaches stdout on a quiet (default) run")
        # ---- A0c: THE TOTAL STILL COVERS THE START-UP IT IS DOCUMENTED TO COVER ----------
        # `_RUN_T0` is stamped at module import deliberately: the helper imports, preflight and
        # the PDF-engine probe all happen before the work dir is resolved, so they can only be
        # inside `total_s` and never inside a stage - which is exactly what the "start-up Xs"
        # tail is for. `_register_timings` then re-based `_RUN_T0` on EVERY call, including the
        # first, and silently deducted all of it: 2.43s of real start-up dropped on a measured
        # project, 1.3s printed against 3.77s actual (~3x), and the residual then always under
        # the 0.05s threshold that prints the tail, so the ONE line built to name the missing
        # time could never fire. Checked HERE, against the real process, because nothing
        # in-process can observe the import-time baseline at all.
        _ssum = sum(float(s.get("seconds") or 0.0) for s in (_disk.get("stages") or []))
        ck(float(_disk.get("total_s") or 0.0) > _ssum,
           f"total_s on disk ({_disk.get('total_s')}) EXCEEDS the sum of the stages "
           f"({_ssum:.3f}) - the import-time baseline survives the arm, so the helper imports, "
           f"preflight and the engine probe are still inside the documented total")
        ck("start-up" in (_rc0.stdout or ""),
           "and the unattributed start-up remainder is NAMED on screen (re-based, the residual "
           "was always under the print threshold and this line could never fire)")

    # ---- A0b: the handler NEVER CREATES the directory it writes into ---------------------
    # Confirmed defect: `_common.atomic_write_text` does parent.mkdir(parents=True), so an
    # unwritable/misspelt --work path had its whole tree conjured during interpreter shutdown,
    # and a run that deliberately removed its own work dir had it RESURRECTED holding one lone
    # timings.json - state authored after the process had already reported its exit code, which
    # the next pass then reads as a warm work dir. Called directly, because the point is what
    # the handler does with a path that is not there.
    with tempfile.TemporaryDirectory() as td_s:
        _gone = Path(td_s) / "deleted-work-dir" / "deeper"
        _saved_done = R._TIMINGS_DONE
        try:
            R._TIMINGS_DONE = False
            R._write_timings(_gone)          # must not raise, must not create
            ck(not _gone.exists(),
               f"a missing work dir is NOT created by the exit handler ({_gone})")
            ck(not (Path(td_s) / "deleted-work-dir").exists(),
               "and no part of the tree above it is created either")
            # a work path that is a FILE, not a directory: equally not somewhere to write an
            # artefact, and it must not be clobbered or turned into a directory either.
            _file_work = Path(td_s) / "not-a-dir.txt"
            _file_work.write_text("someone else's file", encoding="utf-8")
            R._TIMINGS_DONE = False
            R._write_timings(_file_work)
            ck(_file_work.is_file()
               and _file_work.read_text(encoding="utf-8") == "someone else's file",
               "a work path that is a FILE is left exactly as it was - not replaced by a "
               "directory, not written through, not raised")
        finally:
            R._TIMINGS_DONE = _saved_done

    # ---- A0b: the log state is reset per run, so an in-process second call measures ITSELF
    # The four globals were never reset, so a harness calling the entry point twice produced ONE
    # merged artefact timed from MODULE IMPORT. Production calls it once; this was wrong for
    # whoever tried to measure it. The previous run is FLUSHED to its own dir first, so
    # resetting does not simply lose it.
    with tempfile.TemporaryDirectory() as td_s:
        _prev = Path(td_s) / "prev"
        _prev.mkdir()
        _saved_armed = R._TIMINGS_ARMED
        # A0c, THE OTHER HALF: ARM #1 MUST NOT RE-BASE THE MONOTONIC BASELINE. Production arms
        # exactly once, so this is the call that decides whether `total_s` is a number anybody
        # can act on. Checked from a clean flag and with no stage log open, so nothing is
        # flushed and only the baseline is under test.
        R._STAGE_LOG.clear()
        R._TIMINGS_DONE = False
        R._TIMINGS_ARMED = False
        _t0_import = R._RUN_T0
        R._register_timings(_prev)
        ck(R._RUN_T0 == _t0_import,
           "the FIRST _register_timings call in a process PRESERVES the import-time baseline "
           "(re-basing it deducted the whole of the real start-up from total_s)")
        ck(R._TIMINGS_ARMED is True,
           "...and records that the process is armed, so the reset is available to run #2")
        # ...and the SECOND arm still resets, which is the entire reason the reset exists.
        R._STAGE_LOG.clear()
        R._TIMINGS_DONE = False
        R._TIMINGS_LAST_WORK[:] = [_prev]
        R._stage("merge")                       # a previous in-process run, still open
        R._register_timings(Path(td_s))         # ...a second run arms itself
        ck(R._RUN_T0 != _t0_import,
           "the SECOND arm DOES re-base, so an in-process second run measures ITSELF rather "
           "than the module import plus run #1")
        ck((_prev / "timings.json").exists(),
           "the previous in-process run's log is FLUSHED to its own work dir before the reset")
        ck(R._STAGE_LOG == [] and R._TIMINGS_DONE is False,
           f"the stage log and the one-shot flag are reset at entry ({R._STAGE_LOG})")
        R._stage("build")
        R._close_open_stage()
        _p2 = R._timings_payload()
        ck([s["stage"] for s in _p2["stages"]] == ["build"],
           f"the second run's artefact holds ONLY its own stages ({_p2['stages']})")
        ck(_p2["total_s"] < 60,
           f"...and its total_s is timed from ITS start, not from module import ({_p2['total_s']})")
        # disarm the handler this test armed, so the eval's own shutdown writes nothing
        R._TIMINGS_DONE = True
        R._STAGE_LOG.clear()
        R._TIMINGS_ARMED = _saved_armed

    # ================= A1: the enrichment stamp is scoped to what enrichment reads ==========
    print("\nA1: the enrich resume stamp hashes ONLY what enrichment consumes")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        f = td / "canonical.json"
        base = _canonical([_prop(1), _prop(2)])
        f.write_text(json.dumps(base), encoding="utf-8")
        h_base = R._enrich_input_hash(f)
        ck(bool(h_base), "a readable canonical yields a hash")

        # a correction confined to a NON-SPATIAL field: enrichment cannot read it, cannot be
        # changed by it, and so must not re-run for it. This is the whole item.
        for _fld, _val in (("loadingDocks", "13"), ("clearHeight", "12 m"),
                           ("description", "A rewritten paragraph."),
                           ("warehouseRent", "55.00")):
            c = copy.deepcopy(base)
            c["properties"][0][_fld] = _val
            f.write_text(json.dumps(c), encoding="utf-8")
            ck(R._enrich_input_hash(f) == h_base,
               f"a change confined to `{_fld}` does NOT move the stamp hash "
               f"(no re-run of the throttled routing calls)")

        # ...and every field it DOES read must move it. THIS LIST ALONE IS NOT ENOUGH: it is a
        # transcription of the constant, so it pins the stamp's DIRECTION and can never pin its
        # SUFFICIENCY. A1b below is what pins sufficiency; `mapLink` is here because it is the
        # specific input that fell through both lists and shipped a wrong pin.
        for _fld, _val in (("lat", 40.1), ("lng", -3.7), ("city", "Elsewhere"),
                           ("country", "BE"), ("postcode", "9999 ZZ"),
                           ("postalCode", "8888 YY"),
                           ("region", "Other"), ("regionCode", "BE9"), ("id", 99),
                           ("mapLink", "https://maps.app.goo.gl/OTHER")):
            c = copy.deepcopy(base)
            c["properties"][0][_fld] = _val
            f.write_text(json.dumps(c), encoding="utf-8")
            ck(R._enrich_input_hash(f) != h_base,
               f"a change to `{_fld}` DOES move the stamp hash (enrichment re-runs)")
        # The whole incident, stated as one case: two canonicals differing ONLY in `mapLink`.
        # An operator supplies the author's real pin through a correction channel; if this
        # passes, the next default-resume pass skips enrichment and the town-centre pin ships.
        _c_a = copy.deepcopy(base)
        _c_a["properties"][0]["mapLink"] = "https://maps.app.goo.gl/AAAA"
        _c_b = copy.deepcopy(_c_a)
        _c_b["properties"][0]["mapLink"] = "https://maps.app.goo.gl/BBBB"
        f.write_text(json.dumps(_c_a), encoding="utf-8")
        _h_a = R._enrich_input_hash(f)
        f.write_text(json.dumps(_c_b), encoding="utf-8")
        _h_b = R._enrich_input_hash(f)
        ck(bool(_h_a) and _h_a != _h_b,
           f"two canonicals differing ONLY in `mapLink` hash differently "
           f"({_h_a[:12]} vs {_h_b[:12]}) - the corrected pin re-runs enrichment")
        # ...AND THE SAME INCIDENT FOR `postalCode`, which is the one that shipped it AGAIN.
        # It was absent from the hashed set while enrichment read it INDIRECTLY (through
        # `_locality_code` -> `match._stated_postcode` -> `match._POSTCODE_FIELDS`, whose
        # answer is the third segment of the geocode cache key). So the cache key moved, the
        # stamp did not, enrichment was skipped, and the town-centre pin shipped once more.
        _c_p = copy.deepcopy(base)
        _c_p["properties"][0]["postalCode"] = "1111 AA"
        _c_q = copy.deepcopy(_c_p)
        _c_q["properties"][0]["postalCode"] = "2222 BB"
        f.write_text(json.dumps(_c_p), encoding="utf-8")
        _h_p = R._enrich_input_hash(f)
        f.write_text(json.dumps(_c_q), encoding="utf-8")
        _h_q = R._enrich_input_hash(f)
        ck(bool(_h_p) and _h_p != _h_q,
           f"two canonicals differing ONLY in `postalCode` hash differently "
           f"({_h_p[:12]} vs {_h_q[:12]}) - the locality segment of the geocode cache key "
           f"cannot move without the stamp moving")

        # property ORDER is not an input: enrichment is per property, so a re-ordering merge
        # must not re-run it either.
        c = copy.deepcopy(base)
        c["properties"].reverse()
        f.write_text(json.dumps(c), encoding="utf-8")
        ck(R._enrich_input_hash(f) == h_base,
           "re-ordering the same properties does NOT move the hash (deterministic order)")

        # an unreadable / empty canonical must be a MISS, never an accidental match
        (td / "broken.json").write_text("{ not json", encoding="utf-8")
        ck(R._enrich_input_hash(td / "broken.json") == "",
           "an unreadable canonical hashes to '' - a hash we cannot compute must never match")
        (td / "empty.json").write_text(json.dumps(_canonical([])), encoding="utf-8")
        ck(R._enrich_input_hash(td / "empty.json") == "",
           "a canonical with no properties hashes to '' (a miss, not a free skip)")

    # ---- A1b: THE HASHED SET vs WHAT enrich.py ACTUALLY READS ---------------------------
    # The two loops above are transcriptions of `_ENRICH_INPUT_FIELDS`, so they agree with the
    # constant by construction and cannot notice an input the constant is MISSING. That is the
    # only failure mode that matters: an over-inclusive key costs one honest re-enrich, an
    # under-inclusive one causes a FALSE SKIP and ships wrong data silently. So the set is
    # compared against a source-level scan of enrich.py for per-property field reads. It is a
    # regex, not a type analysis, and it is deliberately LOUD rather than clever: anything the
    # scan finds that is neither hashed nor in the annotated not-an-input list FAILS, and so
    # does anything hashed that the scan cannot find and that is not annotated as deliberately
    # over-included. A future author adding a per-property read to enrichment must then either
    # hash it or say here, on the record, why it is not an input.
    print("\nA1b: the hashed set is checked against what enrich.py actually reads")
    _enr_src = (HELPERS / "enrich.py").read_text(encoding="utf-8")
    _direct = set(re.findall(r"""\bp(?:\.get\(\s*|\[\s*)['"]([A-Za-z_]\w*)['"]""", _enr_src))

    # ---- A1c: FOLLOW THE DELEGATION, or the scan cannot see the reads that matter ---------
    # The regex above is a LITERAL `p.get("x")` / p["x"] scan, so it only ever sees reads
    # enrich.py performs ITSELF - and it reported BOTH postal spellings as read nowhere, which
    # is precisely how `postalCode` escaped the resume key and shipped a town-centre pin.
    # Enrichment reads them one module hop out: `_locality_code` delegates to
    # `match._stated_postcode`, which walks `match._POSTCODE_FIELDS = ("postcode",
    # "postalCode")` and hands back the THIRD segment of the geocode cache key.
    #
    # RESOLVED STRUCTURALLY, NOT WITH A SECOND REGEX, because the guard that failed here failed
    # by being textual: parse both modules, ask which match.py helpers enrich.py actually calls
    # (an attribute access on whatever name it binds the module to), follow those helpers
    # through match.py's own internal calls, and treat every MODULE-LEVEL tuple/list of string
    # literals such a helper names as a set of per-property FIELD NAMES it reads. That is the
    # shape `_POSTCODE_FIELDS` has and the shape this codebase uses for every open field list.
    # A helper reached this way that names a tuple of something else surfaces below as an
    # unaccounted-for field and FAILS, naming it - loud, and in the direction that costs one
    # honest re-enrich rather than a silent false skip.
    _mat_src = (HELPERS / "match.py").read_text(encoding="utf-8")
    _enr_ast, _mat_ast = ast.parse(_enr_src), ast.parse(_mat_src)
    _mat_consts: dict = {}
    for _nd in _mat_ast.body:
        if isinstance(_nd, ast.Assign) and isinstance(_nd.value, (ast.Tuple, ast.List)):
            _lits = [e.value for e in _nd.value.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if _lits and len(_lits) == len(_nd.value.elts):
                for _tg in _nd.targets:
                    if isinstance(_tg, ast.Name):
                        _mat_consts[_tg.id] = tuple(_lits)
    _mat_funcs = {_nd.name: _nd for _nd in ast.walk(_mat_ast)
                  if isinstance(_nd, (ast.FunctionDef, ast.AsyncFunctionDef))}
    _mat_alias = {a.asname or a.name for _nd in ast.walk(_enr_ast)
                  if isinstance(_nd, ast.Import) for a in _nd.names if a.name == "match"}
    _queue = sorted({_nd.attr for _nd in ast.walk(_enr_ast)
                     if isinstance(_nd, ast.Attribute) and isinstance(_nd.value, ast.Name)
                     and _nd.value.id in _mat_alias})
    ck(bool(_mat_alias) and bool(_queue),
       f"enrich.py's delegation into match.py is VISIBLE to the scan (module bound as "
       f"{sorted(_mat_alias)}, helpers called: {_queue}) - if this ever reads empty the scan "
       f"has gone blind again and every indirect input is unprotected")
    _indirect: dict = {}
    _walked: set = set()
    while _queue:
        _fn = _queue.pop()
        if _fn in _walked or _fn not in _mat_funcs:
            continue
        _walked.add(_fn)
        for _nd in ast.walk(_mat_funcs[_fn]):
            if not isinstance(_nd, ast.Name):
                continue
            if _nd.id in _mat_consts:
                for _f in _mat_consts[_nd.id]:
                    _indirect.setdefault(_f, set()).add(f"match.{_fn} -> match.{_nd.id}")
            elif _nd.id in _mat_funcs:
                _queue.append(_nd.id)
    _paths = {k: sorted(v) for k, v in sorted(_indirect.items())}
    print(f"    delegated reads resolved: {_paths}")
    ck("postcode" in _indirect and "postalCode" in _indirect,
       f"BOTH postal spellings resolve THROUGH the delegation ({sorted(_indirect)}) - the read "
       f"the literal scan could not see, and the reason `postalCode` escaped the resume key")
    _read = _direct | set(_indirect)
    # Found by the scan, but NOT a per-property enrichment INPUT. Each needs a reason, and the
    # reason has to be checkable by the next reader, or this list becomes the place divergence
    # hides.
    _not_an_input = {
        "coordsApprox": "WRITTEN by geocode()/resolve_map_links (p['coordsApprox'] = ...), "
                        "never read as an input",
        "type": "read off an assets/poi_library.json POI entry in the city-centroid "
                "comprehension, not off a property",
        "name": "read in the POI-library comprehension (a POI's name, not a property field) "
                "and, since D9/D10, in geocode()'s `_name(p)` label - see `park` for why a "
                "label is not an input",
        "park": "read ONLY by geocode()'s `_name(p)`, which composes the human-readable label "
                "in the D10 displacement line, the keeps-stated-coordinate NOTE and the D9 "
                "Gaps Report disclosure (each of which also carries id= and the postcode). "
                "It never reaches a lookup, a cache key or a coordinate, so a changed park "
                "name cannot change what enrichment computes; hashing it would re-run the "
                "throttled POI/routing network calls for a label. The one cost accepted: a "
                "park renamed by a repair keeps the OLD label in the geocode disclosure "
                "lines until the next pass that re-runs enrichment (the id= beside it IS "
                "hashed, so the property stays identifiable). Checkable by grepping "
                "enrich.py for `_name(` - if it ever feeds anything else, move it to "
                "_ENRICH_INPUT_FIELDS",
    }
    # Hashed but NOT found by the scan: deliberate over-inclusion, which is always safe.
    # DELIBERATELY EMPTY. It used to carry `postcode` with the reason "a LATER change makes
    # locality a geocode-cache key" - that change has landed, so the entry was excusing a
    # GENUINE input as an over-inclusion, which is the annotation that let `postalCode` be
    # dropped entirely. An over-inclusion is still always safe; it just has to be a real one.
    _over_included: dict = {}
    _hashed = set(R._ENRICH_INPUT_FIELDS)
    _escaped = sorted(_read - _hashed - set(_not_an_input))
    ck(not _escaped,
       f"every per-property field enrich.py reads - DIRECTLY or through a match.py helper - is "
       f"either HASHED or annotated as not an input. Unaccounted for: "
       f"{ {f: _paths.get(f) or 'direct read' for f in _escaped} }. REMEDY: add it to "
       f"_ENRICH_INPUT_FIELDS in run.py (an over-inclusive key costs one honest re-enrich; an "
       f"under-inclusive one causes a FALSE SKIP and ships wrong data silently), or, if it is "
       f"genuinely not a per-property input, add it to _not_an_input above with the reason")
    _phantom = sorted(_hashed - _read - set(_over_included))
    ck(not _phantom,
       f"every hashed field is one enrich.py actually reads, or is annotated as deliberately "
       f"over-included - unexplained: {_phantom}")
    ck("mapLink" in _read and "mapLink" in _hashed,
       "`mapLink` is read by enrich.py AND hashed (the input that escaped both lists: "
       "resolve_map_links follows a short maps link and writes lat/lng + coordsApprox)")
    ck({"postcode", "postalCode"} <= _hashed,
       f"BOTH postal spellings in `match._POSTCODE_FIELDS` are hashed ({sorted(_hashed)}). "
       f"That list is OPEN - a broker's own header decides the name and the FIRST stated one "
       f"wins - so hashing one spelling leaves the other free to move the geocode cache key "
       f"without moving the stamp")
    ck(set(_indirect) <= _hashed,
       f"and EVERY field resolved through the delegation is hashed - unhashed: "
       f"{sorted(set(_indirect) - _hashed)} (add it to _ENRICH_INPUT_FIELDS in run.py)")
    _fld_cmt = run_src[max(0, run_src.find("_ENRICH_INPUT_FIELDS = ") - 4200):
                       run_src.find("_ENRICH_INPUT_FIELDS = ")]
    ck("resolve_map_links" in _fld_cmt and "_POSTCODE_FIELDS" in _fld_cmt
       and "_locality_code" in _fld_cmt,
       "the field-set comment names the CONSUMING code (not intent) for both the direct input "
       "that escaped it and the DELEGATED one - `_locality_code` and `match._POSTCODE_FIELDS` "
       "by name, so the next reader can find the read the source-level grep cannot")
    ck("later change" not in _fld_cmt,
       "...and the stale 'a LATER change makes locality a geocode-cache key' annotation is "
       "gone: that change HAS landed, so the note was telling the next reader a postal field "
       "cannot matter while the code had already started reading it")

    ck("_ENRICH_STAMP_V" in run_src and '"v": _ENRICH_STAMP_V' in run_src,
       "the stamp is written in a VERSIONED shape")
    ck('int(prev.get("v") or 0) == _ENRICH_STAMP_V' in run_src,
       "a missing or wrong `v` is a MISS, so an old whole-file stamp cannot be misread as current")
    ck('bool(_cur_hash) and prev.get("hash") == _cur_hash' in run_src,
       "an empty computed hash can never equal a stored one")
    # the existing 'a cache file is newer than the stamp' invalidator must survive untouched
    for _cache in ("poi_osm_cache.json", "osrm_cache.json", "geocode_cache.json",
                   "regions_cache.json", "extract/region_labels.json"):
        ck(f'"{_cache}"' in run_src,
           f"the newer-cache invalidator still lists {_cache} (the exit-3/exit-8 handoffs)")

    # ================= A2: --from / --only, and what they can NEVER reach =================
    print("\nA2: --from / --only skip stages independently of --resume, and never the gates")
    _saved = (R.RESUME, R.FROM_STAGE, R.ONLY_STAGES)
    try:
        # --from: everything strictly before the cut is skipped, the cut and after are not
        R.RESUME, R.FROM_STAGE, R.ONLY_STAGES = False, "repairs", frozenset()
        R._assert_stage_control_safe()
        _before = [s for s in FROZEN[:FROZEN.index("repairs")]]
        ck(all(R._stage_skipped(s) for s in _before),
           f"--from repairs skips every earlier stage ({', '.join(_before)})")
        ck(not any(R._stage_skipped(s) for s in FROZEN[FROZEN.index("repairs"):]),
           "--from repairs skips nothing at or after the cut")
        ck(R._is_current("does-not-exist.json", [], stage="merge") is True,
           "the cut is honoured through _is_current even under --no-resume (the one skip "
           "predicate, not a second parallel mechanism)")
        ck(R._is_current("does-not-exist.json", [], stage="repairs") is False,
           "and a stage at/after the cut is still judged on its inputs alone")
        ck(R._is_current("does-not-exist.json", [], stage="") is False,
           "a caller passing no stage keeps its old behaviour exactly")

        # --only: everything not named is skipped
        R.FROM_STAGE, R.ONLY_STAGES = "", frozenset({"build"})
        R._assert_stage_control_safe()
        ck(all(R._stage_skipped(s) for s in FROZEN
               if s not in ("build",) + tuple(NEVER_SKIP)),
           "--only build skips every other skippable stage")
        ck(not R._stage_skipped("build"), "--only build does not skip build")

        # A2b: THE TWO STAGES THAT IGNORED THE FLAGS, by the two flag settings that expose
        # them. `--only extract` is the narrowest useful cut and it was the worst case: repairs
        # still ran, applied every entry in work/repairs.json and MUTATED canonical, on a pass
        # the operator had scoped to extraction alone. `--from build` is the other half: a
        # correction already applied, the operator asking not to re-apply it, and repairs
        # re-applying anyway.
        R.FROM_STAGE, R.ONLY_STAGES = "", frozenset({"extract"})
        R._assert_stage_control_safe()
        for _s in ("repairs", "projection"):
            ck(R._stage_skipped(_s),
               f"--only extract skips `{_s}` (it used to run, and repairs MUTATES canonical)")
        ck(not R._stage_skipped("extract"), "--only extract does not skip extract")
        R.FROM_STAGE, R.ONLY_STAGES = "build", frozenset()
        R._assert_stage_control_safe()
        for _s in ("repairs", "projection"):
            ck(R._stage_skipped(_s),
               f"--from build skips `{_s}` (it is strictly before the cut)")
        ck(not R._stage_skipped("build") and not R._stage_skipped("deliver"),
           "--from build skips nothing at or after the cut")

        # THE HARD GUARD, over every flag combination that could name a protected stage.
        _leaks = []
        for _frm in [""] + FROZEN:
            for _only in [frozenset()] + [frozenset({s}) for s in FROZEN] + \
                    [frozenset({"build", "deliver"}), frozenset(FROZEN)]:
                R.FROM_STAGE, R.ONLY_STAGES = _frm, _only
                for _p in NEVER_SKIP:
                    if R._stage_skipped(_p) or R._is_current("nope", [], stage=_p) is not False:
                        _leaks.append((_frm, sorted(_only), _p))
                try:
                    R._assert_stage_control_safe()
                except AssertionError as e:
                    _leaks.append((_frm, sorted(_only), f"assert: {e}"))
        ck(not _leaks,
           f"across {(len(FROZEN) + 1) * (len(FROZEN) + 3)} flag combinations, NO combination "
           f"skips gates:pre, gates:post or qa (leaks: {_leaks[:3]})")

        # ...and the freeze. It is not a stage name - it lives INSIDE gates:pre, at ALL-PASS -
        # so what protects it is that gates:pre always runs and the freeze is unconditional
        # within it. Pinned structurally, because there is no flag to test against.
        _g1 = run_src.find('_stage("gates:pre")')
        _frz = run_src.find('call(gate_runner, "freeze", canonical')
        _build = run_src.find('_stage("build")')
        ck(0 < _g1 < _frz < _build,
           "the freeze sits INSIDE the always-run gates:pre stage, before build - so no flag "
           "can reach it without skipping a stage that cannot be skipped")
        _seg = run_src[_g1:_frz]
        ck("_is_current" not in _seg and "_stage_skipped" not in _seg,
           "nothing between gates:pre opening and the freeze consults a skip predicate")
    finally:
        R.RESUME, R.FROM_STAGE, R.ONLY_STAGES = _saved

    # A2b: EVERY SKIPPABLE STAGE IN THE VOCABULARY MUST CONSULT THE PREDICATE, and the
    # requirement is DERIVED from STAGE_ORDER rather than listed - which is the whole point.
    # Three stages (enrichment, repairs, projection) have no single output file to route
    # through `_is_current` (enrichment mutates canonical in place, repairs likewise, the
    # projection writes a directory tree), so each needs its own guard, and two of them simply
    # never got one: `--only extract` still applied every repair and mutated canonical while
    # the help text promised the stage was "treated as current and skipped". A hand-written
    # list here would have had exactly the same blind spot as the code. So: for each skippable
    # stage, take the source SEGMENT between its `_stage(...)` boundary and the next one, and
    # require the cut to be applied somewhere inside it. Add a twelfth stage to the vocabulary
    # without a guard and this fails, naming it.
    _bounds = sorted(((run_src.find(f'_stage("{s}")'), s) for s in FROZEN
                      if run_src.find(f'_stage("{s}")') > 0))
    _dupes = [s for s in FROZEN if run_src.count(f'_stage("{s}")') != 1]
    ck(len(_bounds) == len(FROZEN) and not _dupes,
       f"every stage in the vocabulary has EXACTLY ONE boundary in main() ({len(_bounds)}; "
       f"not exactly once: {_dupes}) - a second boundary would make the segment scan below "
       f"read the wrong span of source and could hide an ungated stage")
    ck([s for _, s in _bounds] == FROZEN,
       f"the boundaries appear in main() in vocabulary order ({[s for _, s in _bounds]})")
    _ungated = []
    for _ix, (_at, _name) in enumerate(_bounds):
        if _name in NEVER_SKIP:
            continue
        _end = _bounds[_ix + 1][0] if _ix + 1 < len(_bounds) else len(run_src)
        _seg_s = run_src[_at:_end]
        if f'_stage_skipped("{_name}")' not in _seg_s and f'stage="{_name}"' not in _seg_s:
            _ungated.append(_name)
    ck(not _ungated,
       f"every skippable stage applies the cut inside its own segment of main() - ungated: "
       f"{_ungated} (the flags VALIDATE all eleven names, so a stage with no guard is a "
       f"promise the help text does not keep)")
    # ---- A2c: THE TWO REMEDIATED GUARDS, PROVED BEHAVIOURALLY ---------------------------
    # What stood here was `ck('if _stage_skipped("repairs"):' in run_src, ...)` for each of the
    # two stages - a SUBSTRING, which cannot see control flow. A reviewer changed the repairs
    # guard's `else:` to `if True:`, so the stage ran on every pass and mutated canonical on a
    # pass the operator had scoped away, and this eval stayed FULLY GREEN with zero failing
    # assertions. The guard the remediation added was therefore completely unprotected, which
    # is the same failure shape as the code it was pinning: a change at one end, nobody at the
    # other.
    #
    # SO THE GUARD IS LOCATED STRUCTURALLY AND THEN EXECUTED.
    #   structurally - in main()'s AST the statement IMMEDIATELY AFTER the `_stage("<name>")`
    #                  boundary must be an `if` testing `_stage_skipped("<name>")`, it must
    #                  HAVE an else, and nothing between it and the next stage boundary may
    #                  call the stage's worker. `else:` -> `if True:` fails two of those three.
    #   behaviourally - that `if` is unparsed and exec'd against run.py's OWN globals with the
    #                  worker module swapped for a recorder, once with the cut set and once
    #                  without. Skipped must not call the worker; NOT skipped must - and it is
    #                  that second direction that stops the whole harness passing vacuously
    #                  when it never reaches the call (the stage bodies swallow exceptions, so
    #                  a harness that cannot run them would otherwise look green).
    print("\nA2c: the repairs and projection cuts, executed rather than grepped")
    _main_ast = next((n for n in ast.walk(ast.parse(run_src))
                      if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    ck(_main_ast is not None, "run.py's main() is locatable in the AST")

    def _stage_opened(st) -> str:
        """The stage a `_stage("x")` statement opens, or "" for any other statement."""
        v = getattr(st, "value", None)
        if isinstance(st, ast.Expr) and isinstance(v, ast.Call) \
                and isinstance(v.func, ast.Name) and v.func.id == "_stage" \
                and len(v.args) == 1 and isinstance(v.args[0], ast.Constant):
            return str(v.args[0].value)
        return ""

    def _guard_and_rest(name):
        """(the statement right after `name`'s boundary, the statements after THAT up to the
        next boundary). The split is the whole point: the guard, and its siblings."""
        body = _main_ast.body if _main_ast else []
        for i, st in enumerate(body):
            if _stage_opened(st) != name:
                continue
            rest = []
            for st2 in body[i + 2:]:
                if _stage_opened(st2):
                    break
                rest.append(st2)
            return (body[i + 1] if i + 1 < len(body) else None), rest
        return None, []

    class _Recorder:
        """Stands in for the worker MODULE the stage imports, and records what was called."""

        def __init__(self, attr, ret):
            self.calls, self._attr, self._ret = [], attr, ret

        def __getattr__(self, k):
            if k.startswith("__"):
                raise AttributeError(k)

            def _f(*a, **kw):
                self.calls.append(k)
                return self._ret if k == self._attr else []
            return _f

    for _name, _mod, _attr, _ret in (
            ("repairs", "repairs", "run",
             {"applied": [], "stale": [], "ambiguous": [], "superseded": [], "invalid": []}),
            ("projection", "project_properties", "build", {"count": 0, "unassigned": 0})):
        _guard, _rest = _guard_and_rest(_name)
        ck(isinstance(_guard, ast.If) and isinstance(_guard.test, ast.Call)
           and isinstance(_guard.test.func, ast.Name)
           and _guard.test.func.id == "_stage_skipped"
           and [a.value for a in _guard.test.args if isinstance(a, ast.Constant)] == [_name],
           f"`{_name}`: the statement right after its stage boundary IS "
           f"`if _stage_skipped(\"{_name}\"):`")
        ck(isinstance(_guard, ast.If) and bool(_guard.orelse),
           f"`{_name}`: and that `if` HAS an else, so the stage's work is the ALTERNATIVE to "
           f"being skipped rather than a sibling of it (`else:` -> `if True:` fails here)")
        _rest_src = "\n".join(ast.unparse(s) for s in _rest)
        ck(f".{_attr}(" not in _rest_src,
           f"`{_name}`: nothing between the guard and the next stage boundary calls "
           f"`.{_attr}(`, so ALL of the stage's work is inside the guard ({len(_rest)} "
           f"sibling statement(s) checked)")
        if not isinstance(_guard, ast.If):
            continue
        with tempfile.TemporaryDirectory() as td_s:
            _wk = Path(td_s)
            _code = compile(ast.unparse(_guard), f"<{_name}-guard>", "exec")
            _seen = {}
            for _skip in (True, False):
                _rec = _Recorder(_attr, _ret)
                _ns = dict(vars(R))          # run.py's real globals, so the body resolves
                _ns.update({"work": _wk, "canonical": _wk / "canonical.json", "folder": _wk,
                            "QUIET": True, "_resumed": lambda *a, **k: None,
                            "_stage_skipped": (lambda *a, **k: _skip)})
                _had = sys.modules.get(_mod)
                sys.modules[_mod] = _rec     # `import <mod> as _x` binds this recorder
                try:
                    exec(_code, _ns)
                finally:
                    if _had is None:
                        sys.modules.pop(_mod, None)
                    else:
                        sys.modules[_mod] = _had
                _seen[_skip] = list(_rec.calls)
            ck(_attr not in _seen[True],
               f"`{_name}`: with the cut SET, executing the stage's own guard does NOT call "
               f"{_mod}.{_attr} (calls: {_seen[True]})")
            ck(_attr in _seen[False],
               f"`{_name}`: and with the cut CLEAR it DOES (calls: {_seen[False]}) - the "
               f"direction that stops the check above passing vacuously")
    # enrichment has no single output file, so it cannot route through _is_current - its own
    # boolean must be gated by the SAME predicate or the flags would skip everything but the
    # one stage they are most often used to skip.
    ck('if _stage_skipped("enrichment"):' in run_src,
       "enrichment's own skip boolean is gated by _stage_skipped (it bypasses _is_current)")
    # EVERY _is_current call site passes a stage name. Balanced-paren scan rather than a
    # line regex: two of the six sites wrap onto a second line, and a line regex reports them
    # as unstaged (a false red) or, worse, would let a genuinely unstaged multi-line site pass.
    def _call_args(src, needle):
        out = []
        i = src.find(needle)
        while i >= 0:
            j, depth = i + len(needle) - 1, 0
            while j < len(src):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(src[i + len(needle):j])
            i = src.find(needle, j)
        return out

    _sites = [a for a in _call_args(run_src, "_is_current(")
              if not a.startswith("out, inputs")]  # skip the def line
    ck(len(_sites) == 6, f"there are still exactly 6 _is_current call sites ({len(_sites)})")
    # Every site is under stage control, by ONE of two shapes, and each shape is deliberate:
    #   stage="..."             - the normal shape (intake, per-file extract, deliver)
    #   or _stage_skipped(...)  - merge and build, whose _is_current call is an expression other
    #                             evals anchor ON, so the cut is applied beside the call rather
    #                             than by threading a keyword through it.
    _staged = [s for s in _sites if "stage=" in s]
    ck(len(_staged) == 3,
       f"3 sites carry stage= (folder scan, extract, deliver) - got {len(_staged)}")
    for _st in ("folder scan", "extract", "deliver"):
        ck(any(f'stage="{_st}"' in s for s in _sites),
           f'the {_st} site passes stage="{_st}"')
    # The merge and build sites take the cut as a trailing `or _stage_skipped("<stage>")`.
    # Checked by looking at the SITE's own expression and the text immediately after it, not by
    # pinning the whole multi-line statement byte-for-byte: what matters is that the cut is
    # applied at the site, not how the line happens to wrap today.
    for _marker, _stage_name in (("_is_current(canonical, merge_inputs", "merge"),
                                 ("_is_current(built, [canonical", "build")):
        _at = run_src.find(_marker)
        _tail = run_src[_at:_at + 300] if _at > 0 else ""
        ck(_at > 0 and f'_stage_skipped("{_stage_name}")' in _tail,
           f"the {_stage_name} site (its _is_current expression is anchored by other evals) "
           f'applies the cut as a neighbouring `or _stage_skipped("{_stage_name}")`')
    _unctrl = [" ".join(s.split())[:70] for s in _sites
               if "stage=" not in s and "merge_inputs" not in s
               and "_build_stamp" not in s]
    ck(not _unctrl, f"no _is_current site is outside stage control ({_unctrl})")
    # NO ASSERTION HERE PINNING OTHER EVALS' SOURCE ANCHORS. There used to be one, requiring
    # three literal substrings to survive in run.py because audit_resume_test /
    # engine_resume_test, code_stamp_test and deliver_atomic_test each locate a position in the
    # source by matching them. That is backwards: it turned three other evals' incidental
    # implementation detail into a permanent contract enforced from HERE, so a future author
    # normalising the merge and build call sites (exactly the tidy-up the two shapes above
    # invite) would be failed by a file that has no opinion about it. An eval must pin the
    # BEHAVIOUR it is about, and this one is about stage control.
    #
    # FOR THE NEXT AUTHOR, since the brittleness is real and simply moves rather than
    # disappearing: these three evals match run.py source text to find their anchor, and will
    # need updating if the merge / build / deliver resume expressions are reshaped -
    #   evals/audit_resume_test.py + evals/engine_resume_test.py  ("if _is_current(canonical,
    #                                                              merge_inputs)")
    #   evals/code_stamp_test.py     ("_is_current(built, [canonical, _build_stamp])")
    #   evals/deliver_atomic_test.py ("_is_current(deliverables / filename")
    # Update them there, in the eval that depends on the anchor, rather than freezing run.py
    # from a file that does not.
    # a typo must stop the run and name the valid spellings, never silently run/skip everything
    _rc = subprocess.run([sys.executable, str(HELPERS / "run.py"), "--project", ".",
                          "--from", "repair"], capture_output=True, text=True, timeout=180)
    _out = (_rc.stdout or "") + (_rc.stderr or "")
    ck(_rc.returncode != 0 and "repair" in _out and "folder scan" in _out and "qa" in _out,
       f"a --from typo exits non-zero ({_rc.returncode}) and lists the valid stage names")
    _rc2 = subprocess.run([sys.executable, str(HELPERS / "run.py"), "--project", ".",
                           "--only", "merge,nonsense"], capture_output=True, text=True, timeout=180)
    _out2 = (_rc2.stdout or "") + (_rc2.stderr or "")
    ck(_rc2.returncode != 0 and "nonsense" in _out2,
       f"a --only typo does the same, naming the offending entry ({_rc2.returncode})")
    _doc_open = run_src.find('"""')
    _doc = run_src[_doc_open:run_src.find('"""', _doc_open + 3)]
    _cli = _doc[_doc.find("\nCLI:"):]
    for _flag in ("--from", "--only", "--allow-invalid-corrections"):
        ck(_flag in _cli, f"{_flag} is documented in the module docstring's CLI block")
    ck("folder scan" in _cli and "gates:pre" in _cli,
       "the CLI block spells out the stage vocabulary (it has a space and a colon in it)")
    # SKILL.md is the orchestrator's contract, and --from/--only were reachable from the CLI
    # while being documented NOWHERE in it: the spine prints `--from repairs` at every
    # correction exit, so an orchestrator was being handed a flag its own instructions did not
    # define. Checked behaviourally-adjacent: the flags, the vocabulary and the always-run
    # promise all have to be present, not just the flag names.
    _skill = (HELPERS.parent / "SKILL.md").read_text(encoding="utf-8")
    for _flag in ("--from", "--only", "--allow-invalid-corrections"):
        ck(_flag in _skill, f"SKILL.md documents {_flag}")
    ck("folder scan" in _skill and "gates:pre" in _skill,
       "SKILL.md spells out the stage vocabulary, so a --from value can be typed correctly")
    ck("warm" in _skill.lower(),
       "...and records that both flags REUSE a skipped stage's output, so they need a warm "
       "work dir rather than being a way to run one stage on a cold one")

    # ================= A21: the column-map cache is keyed on the SCHEMA ====================
    print("\nA21: the tracker column-map cache key survives a data edit, moves on a header edit")
    # tracker_structure's real shape, including the four data-derived members that used to be
    # folded into the key.
    def _struct(headers, rows, unmapped):
        return [{"sheet": "Availability", "headers": list(headers),
                 "sample_rows": [list(r) for r in rows],
                 "sample_row_numbers": list(range(2, 2 + len(rows))),
                 "populated_columns": len(headers),
                 "unmapped_headers": list(unmapped)}]

    _h = ["Property", "Town", "Size (sq m)", "Docks"]
    _base = _struct(_h, [["Park A", "Town A", "10000", "12"]], ["Docks"])
    # the same schema, different DATA - and a DIFFERENT greedy sample selection, which is what
    # actually happened: change a cell and the set-cover picks other rows and row numbers.
    _data_edit = _struct(_h, [["Park A", "Town A", "10500", "12"],
                              ["Park B", "Town B", "8000", "6"]], ["Docks"])
    _data_edit[0]["sample_row_numbers"] = [7, 19]
    _data_edit[0]["populated_columns"] = 4
    _hdr_edit = _struct(_h[:3] + ["Dock doors"], [["Park A", "Town A", "10000", "12"]],
                        ["Dock doors"])
    _unmapped_edit = _struct(_h, [["Park A", "Town A", "10000", "12"]], [])
    _sheet_edit = _struct(_h, [["Park A", "Town A", "10000", "12"]], ["Docks"])
    _sheet_edit[0]["sheet"] = "Availability 2026"

    key = R._tracker_map_key if hasattr(R, "_tracker_map_key") else None
    ck(key is not None, "run.py exposes the narrowed key projection (_tracker_map_key)")
    if key is not None:
        def _k(s):
            return json.dumps(key(s), ensure_ascii=False, sort_keys=True)
        ck(_k(_base) == _k(_data_edit),
           "editing data cells (and the sample rows/row numbers/populated count that follow) "
           "leaves the key UNCHANGED - a settled column map stays settled")
        ck(_k(_base) != _k(_hdr_edit),
           "renaming a HEADER changes the key (the map is a header->field binding)")
        ck(_k(_base) != _k(_unmapped_edit),
           "a change in unmapped_headers changes the key - it is what focuses the "
           "interpretation job, so a different question must be re-asked")
        ck(_k(_base) != _k(_sheet_edit),
           "renaming a SHEET changes the key")
        _keys = set(key(_base)[0])
        ck(_keys == {"sheet", "headers", "unmapped_headers"},
           f"the key carries exactly sheet + headers + unmapped_headers (got {sorted(_keys)})")
        for _excluded in ("sample_rows", "sample_row_numbers", "populated_columns",
                          "unsampled_columns"):
            ck(_excluded not in _keys, f"{_excluded} is NOT in the key (it is data-derived)")

        # ---- A21b: the EXTRACTOR CODE is part of the key -----------------------------
        # The schema half cannot see an alias-table change that RE-POINTS an already-mapped
        # header at a different field: the sheets, the headers and the unmapped list are all
        # byte-identical, so the key was stable and a settled map was reused over a dictionary
        # that now disagreed with it. That hole predates the narrowing - the data-derived
        # members were churning the key often enough to re-ask by accident, and removing them
        # removed the accident. Behavioural, not a source match: two different stamps must
        # produce two different keys over the SAME schema.
        ck(_k(_base) != json.dumps(key(_base, code="aaaaaaaaaaaaaaaa"),
                                   ensure_ascii=False, sort_keys=True),
           "a code stamp CHANGES the key (an edited extract_xlsx.py re-asks the mapping)")
        ck(json.dumps(key(_base, code="aaaaaaaaaaaaaaaa"), sort_keys=True)
           != json.dumps(key(_base, code="bbbbbbbbbbbbbbbb"), sort_keys=True),
           "and two DIFFERENT stamps give two different keys over an identical schema - the "
           "re-pointed-alias case the headers alone cannot see")
        ck(json.dumps(key(_base, code="aaaaaaaaaaaaaaaa"), sort_keys=True)
           == json.dumps(key(_base, code="aaaaaaaaaaaaaaaa"), sort_keys=True),
           "the same stamp gives the same key (a settled map stays settled while the code does)")
        ck(key(_base, code="x")[0] == key(_base)[0],
           "the per-sheet entries keep their exact shape and POSITION - key[0] is still the "
           "first sheet's schema projection, so a cached input_hash echo reads the same way")
        ck(len(key(_base, code="x")) == len(key(_base)) + 1
           and key(_base, code="x")[-1] == {"extractor_code": "x"},
           "the stamp is APPENDED as its own member, not folded into a sheet entry")
    # the computation site uses it (a helper nobody calls fixes nothing) and passes the LIVE
    # stamp over extract_xlsx.py - the module that owns both the alias dictionary and
    # tracker_structure, which is exactly the closure whose change must re-open the question.
    _ih = run_src.find("ihash = _tracker_struct_hash")
    ck(_ih > 0 and "_tracker_map_key(structs, code=" in run_src[_ih:_ih + 400],
       "the ihash computation site hashes the narrowed key PLUS a code stamp, not the whole "
       "structure")
    ck('_code_stamp(work, "trackermap"' in run_src
       and 'HERE / "extract_xlsx.py"' in run_src,
       "the stamp is a _code_stamp over extract_xlsx.py - the same mechanism merge, build and "
       "deliver already use, which the tracker map was the one cached output to lack")
    # and it must be computed ONCE for the loop, not per spreadsheet: it digests the same file
    # every time, and _code_stamp writes a marker in the work dir.
    ck(run_src.count('_code_stamp(work, "trackermap"') == 1,
       "the tracker code stamp is computed at exactly one site (once per run, not per sheet)")
    _cs_at = run_src.find('_code_stamp(work, "trackermap"')
    ck(0 < _cs_at < run_src.find('for xl in inv.get("xlsx", []):'),
       "...and it is hoisted OUT of the per-spreadsheet loop")
    ck(_ih > 0 and "_tracker_struct_hash([{\"region\"" in run_src[_ih:_ih + 400],
       "and the rest of the key (the empty region/country pair) is untouched, so only the "
       "sample-derived members left the payload")
    # `headers` is already in hand, so no extra I/O was introduced
    _xsrc = (HELPERS / "extract_xlsx.py").read_text(encoding="utf-8")
    ck('"headers": headers,' in _xsrc,
       "extract_xlsx.tracker_structure already carries `headers` (no extra read added)")

    # ================= A4: every correction fault, in ONE pass ============================
    print("\nA4: a correction file with three distinct faults reports all three in one pass")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        # THREE DISTINCT fault classes in ONE file, deliberately: a loader that stopped at the
        # first would report one, and a loader that reported "3 problems" without naming them
        # would still cost the operator three passes to find them.
        (td / "repairs.json").write_text(json.dumps([
            {"id": "r-1", "why": "", "verified_by": "broker email",
             "property": {"key": "park-a"}, "set": {"loadingDocks": "12"}},          # no `why`
            {"id": "r-2", "why": "corrected from the brochure", "verified_by": "b",
             "property": {"key": "park-b"}, "set": {"breeem": "Excellent"}},         # typo'd field
            {"id": "r-3", "why": "corrected from the brochure", "verified_by": "b",
             "property": {"key": "park-c"}, "set": {}},                              # nothing to do
        ]), encoding="utf-8")
        _entries, _errs = REP.load(td / "repairs.json")
        ck(len(_errs) == 3,
           f"the EXISTING loader returns all three faults in one call ({len(_errs)}: no new "
           f"validation logic was written)")
        _joined = " | ".join(_errs)
        ck("r-1" in _joined and "r-2" in _joined and "r-3" in _joined,
           f"each fault names its own entry id ({_joined[:180]})")
        ck(not _entries, "and no faulty entry is silently treated as applicable")
        # tolerate an absent file, and a syntactically broken one, without raising
        ck(REP.load(td / "not_there.json") == ([], []),
           "an ABSENT correction file is the normal state, not a fault")
        (td / "bad.json").write_text("{ not json at all", encoding="utf-8")
        _e2, _r2 = REP.load(td / "bad.json")
        ck(_e2 == [] and len(_r2) == 1,
           "an unreadable correction file is REPORTED, not raised")

    # the startup block: both files, every fault, one exit, before any stage runs
    _blk = run_src.find("A4: VALIDATE EVERY CORRECTION FILE UP FRONT")
    ck(_blk > 0, "run.py has the startup correction-validation block")
    _seg = run_src[_blk:run_src.find("# Stage 0 - intake", _blk)]
    ck("merge.load_overrides" in _seg and "_repairs_mod.load(" in _seg,
       "it calls the EXISTING loaders for BOTH channels (overrides + repairs)")
    # ---- THE REPAIR SCREEN WAS NARROWER THAN ITS OWN CONSUMER --------------------------
    # `repairs.run` calls `load` with `extra_fields` = every key on any property in canonical,
    # because off-spec keys are a normal and LARGE part of every record. The startup screen
    # called the same loader BARE, so a correct, attributed repair on an unmapped tracker
    # column was refused at startup with a message asserting the key "is on no property in this
    # dataset" - when it was on all of them. That refusal is exit 16, whose documented remedy is
    # "FIX or DELETE it in place", so an operator following the contract deletes a verified
    # correction. Two changes, two authors, one value, and nobody owned the screen end.
    ck("extra_fields=_repair_screen_fields(" in _seg,
       "the REPAIR loader is widened by the same `extra_fields` its real consumer passes")
    ck("if not _cf.exists():" in _seg and "continue" in _seg,
       "an absent correction file is tolerated")
    ck("except Exception as _ce" in _seg,
       "a loader that raises is reported as an unreadable correction file, never a crash")
    ck("for _fn, _why in _corr_faults:" in _seg,
       "EVERY fault is printed - the loop does not stop at the first")
    ck("batch" in _seg.lower() and "discipline" in _seg.lower(),
       "the comment records that reporting everything at once is the POINT (it is what makes "
       "batching corrections the default rather than a discipline)")
    _stage_at = min((run_src.find(f'_stage("{s}")') for s in FROZEN
                     if run_src.find(f'_stage("{s}")') > 0), default=-1)
    ck(0 < _blk < _stage_at, "the check runs BEFORE the first stage does any work")
    ck("sys.exit(5)" not in _seg,
       "the block no longer exits 5 - exit 5's mapped action (read gate1_scorecard.md, record "
       "the correction in overrides.json) is unexecutable here and self-referential")
    ck("_exit_round_trip(work, 16, _attempts" in _seg,
       "it goes through the round-trip helper, so a repeated identical handoff is DIAGNOSED "
       "(streak, pending predicates, the not-converging line) instead of looping silently")

    # ---- A4c: THE STARTUP SCREEN MUST NOT REFUSE AN OFF-SPEC KEY IT CAN SEE, AND MUST NOT
    # ---- REFUSE ONE IT CANNOT JUDGE ------------------------------------------------------
    print("\nA4c: the startup repair screen agrees with its own consumer about off-spec keys")
    _off = "trackerOnlyColumn"      # an unmapped tracker column: no schema home, on the data
    _off_repair = [{"id": "r-off", "why": "the tracker states 4 EV bays",
                    "verified_by": "broker email 2026-08-01",
                    "property": {"key": "Park 1"}, "set": {_off: "4"}}]
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        (td / "canonical.json").write_text(
            json.dumps(_canonical([_prop(1, **{_off: "2"})])), encoding="utf-8")
        (td / "repairs.json").write_text(json.dumps(_off_repair), encoding="utf-8")
        # what the REAL consumer (repairs.run) computes, and what the screen now computes
        _consumer = {k for p in (json.loads((td / "canonical.json")
                                            .read_text(encoding="utf-8-sig"))["properties"])
                     for k in p}
        _screen = R._repair_screen_fields(td, td / "repairs.json", REP)
        ck(_screen == _consumer,
           f"with canonical present the screen's `extra_fields` EQUALS the consumer's "
           f"({len(_screen)} names, off-spec key included: {_off in _screen})")
        _e_ok, _bad_ok = REP.load(td / "repairs.json", extra_fields=_screen)
        ck(len(_e_ok) == 1 and not _bad_ok,
           f"so a correct, attributed repair on the off-spec key is ACCEPTED, not refused "
           f"({_bad_ok})")
        # and the screen still WORKS: the same entry against a canonical without that key
        (td / "canonical.json").write_text(
            json.dumps(_canonical([_prop(1)])), encoding="utf-8")
        _e_no, _bad_no = REP.load(td / "repairs.json",
                                  extra_fields=R._repair_screen_fields(td, td / "repairs.json",
                                                                       REP))
        ck(not _e_no and len(_bad_no) == 1 and _off in _bad_no[0],
           f"a key on NO property and NO schema is still refused, by name ({_bad_no})")
        # CANONICAL ABSENT: the screen cannot judge the dataset half at all, so it must not
        # refuse. Every OTHER fault must still fire, or "inert" would mean "disarmed".
        (td / "canonical.json").unlink()
        _screen_cold = R._repair_screen_fields(td, td / "repairs.json", REP)
        ck(_screen_cold == {_off},
           f"with NO canonical the screen widens to the names the FILE itself uses "
           f"({sorted(_screen_cold)}) - a screen that cannot read canonical must not refuse a "
           f"key it cannot judge (exit 16's remedy is fix-or-DELETE)")
        _e_cold, _bad_cold = REP.load(td / "repairs.json", extra_fields=_screen_cold)
        ck(len(_e_cold) == 1 and not _bad_cold,
           f"...so a first pass does not refuse the entry ({_bad_cold}); the repairs STAGE "
           f"re-screens it against the canonical it has just built")
        (td / "repairs.json").write_text(json.dumps(
            [{"id": "r-1", "why": "", "verified_by": "b", "property": {"key": "Park 1"},
              "set": {_off: "4"}},
             {"id": "r-2", "why": "w", "verified_by": "b", "property": {"key": "Park 1"},
              "set": {}},
             {"id": "r-3", "why": "w", "verified_by": "b", "property": {"key": "Park 1"},
              "set": {_off: "4"}, "unset": [_off]}]), encoding="utf-8")
        _e_f, _bad_f = REP.load(td / "repairs.json",
                                extra_fields=R._repair_screen_fields(td, td / "repairs.json",
                                                                     REP))
        ck(len(_bad_f) == 3 and not _e_f,
           f"and INERT is not DISARMED - a missing `why`, a nothing-to-do entry and a field in "
           f"both `set` and `unset` all still fault on a cold work dir ({len(_bad_f)}/3)")

    # ---- A4b: EXIT 16, PROVEN BY RUNNING IT ---------------------------------------------
    # The source assertions above cannot tell whether the code actually reaches the process's
    # exit status, and this is the one item where the exit code IS the contract: SKILL.md maps
    # each code to exactly one action, and the wrong code sends the orchestrator to the wrong
    # one. Exit 5 told it to read gate1_scorecard.md (not written yet - this fires at startup)
    # and to record the correction in work/overrides.json, i.e. to APPEND to the file being
    # rejected: append, re-run, refused, append. So: a real work dir, real faulty entries, a
    # real process.
    print("\nA4b: an invalid correction file exits 16 (not 5), with the FIX-not-APPEND handoff")
    _bad_repairs = [
        {"id": "r-1", "why": "", "verified_by": "broker email",
         "property": {"key": "park-a"}, "set": {"loadingDocks": "12"}},       # no `why`
        {"id": "r-2", "why": "corrected from the brochure", "verified_by": "b",
         "property": {"key": "park-b"}, "set": {}},                           # nothing to do
    ]
    with tempfile.TemporaryDirectory() as td_s:
        _root, _work = _project(Path(td_s), {"repairs.json": _bad_repairs})
        _r16 = _spine(_root)
        _o16 = (_r16.stdout or "") + (_r16.stderr or "")
        ck(_r16.returncode == 16,
           f"the run refuses to start and exits 16 (got {_r16.returncode})")
        ck("r-1" in _o16 and "r-2" in _o16,
           "both faults are named in ONE pass, each by its own entry id")
        ck("gate1_scorecard" in _o16.lower() and "not read" in _o16.lower()
           or "do NOT read gate1_scorecard.md" in _o16,
           "the handoff says explicitly NOT to read gate1_scorecard.md (the gates have not run)")
        ck("Do NOT add new entries" in _o16 or "do NOT add new entries" in _o16,
           "...and NOT to append - FIX the named entries in place, the append loop closed")
        ck("FIX the named entries IN PLACE" in _o16,
           "the ONE mapped action is stated in the handoff the orchestrator reads")
        # the round trip is real: the streak file and the pending predicates are on disk
        _att = json.loads((_work / "attempts.json").read_text(encoding="utf-8-sig"))
        ck(_att.get("last") == 16 and int(_att.get("streak") or 0) >= 1,
           f"the streak is recorded against code 16, so a repeat is diagnosable ({_att})")
        _pd = json.loads((_work / "pending_diagnosis.json").read_text(encoding="utf-8-sig"))
        ck(_pd.get("exit") == 16 and len(_pd.get("pending") or []) == 2,
           f"both unmet predicates are persisted for the repeat-handoff diagnosis ({_pd})")
        ck(all("FIX or DELETE it in place" in p for p in (_pd.get("pending") or [])),
           "each predicate names the remedy, so round two does not have to guess")
        # nothing was changed: the refusal is at startup, before any stage
        ck(not (_work / "canonical.json").exists() and not (_work / "inventory.json").exists(),
           "no stage ran - nothing to undo, exactly as the message claims")
        # A SECOND identical handoff must be DIAGNOSED, not silently repeated. This is what the
        # direct sys.exit could not do at all, and it is the brake on the append loop.
        _r16b = _spine(_root)
        _o16b = (_r16b.stdout or "") + (_r16b.stderr or "")
        _att2 = json.loads((_work / "attempts.json").read_text(encoding="utf-8-sig"))
        ck(_r16b.returncode == 16 and int(_att2.get("streak") or 0) == 2,
           f"an unchanged re-run exits 16 again and the streak advances ({_att2})")
        ck("[pending]" in _o16b,
           "and from the second round the EXACT unmet predicates are printed, not just repeated")

    # THE ESCAPE HATCH. The check turns a previously-ignored malformed entry into a hard refusal
    # to start, which is new behaviour as the default - so there has to be a way past it, or the
    # guard can strand a run with one stale entry and a deadline. --allow-invalid-corrections
    # restores the OLD behaviour exactly: name every fault, ignore the faulty entries, carry on.
    with tempfile.TemporaryDirectory() as td_s:
        _root, _work = _project(Path(td_s), {"repairs.json": _bad_repairs})
        _rby = _spine(_root, "--allow-invalid-corrections")
        _oby = (_rby.stdout or "") + (_rby.stderr or "")
        ck(_rby.returncode != 16,
           f"--allow-invalid-corrections is NOT refused with exit 16 (got {_rby.returncode})")
        ck("r-1" in _oby and "r-2" in _oby,
           "every fault is still printed in full - the flag suppresses the refusal, not the news")
        ck("IGNORED" in _oby and "UNCORRECTED" in _oby,
           "and it says plainly that those entries apply nothing, so the data ships uncorrected")
        ck((_work / "inventory.json").exists(),
           "the run genuinely proceeds past the check (the folder scan ran)")
        ck("--allow-invalid-corrections" in _oby,
           "the bypass names itself in the output, so it cannot be left on unnoticed")

    # ================= A3a / A3b: the repair-path coercion asymmetry ======================
    print("\nA3a/A3b: the repair path gets the coercion the override path already had")
    with tempfile.TemporaryDirectory() as td_s:
        f = Path(td_s) / "canonical.json"
        c = _canonical([_prop(1, loadingDocks=12, clearHeight=10.5)])
        f.write_text(json.dumps(c), encoding="utf-8")
        R._coerce_repaired_scalars(f)
        back = json.loads(f.read_text(encoding="utf-8"))["properties"][0]
        ck(back["loadingDocks"] == "12" and back["clearHeight"] == "10.5",
           f"an integer/float repaired into a string-typed field is coerced "
           f"({back['loadingDocks']!r}, {back['clearHeight']!r}) - the same pass the override "
           f"channel gets pre-merge, via the same C.fill_render_sentinels")
        ck(R._coerce_repaired_scalars(f) == 0,
           "and the pass is idempotent, so it is safe on properties no repair touched")
    ck("C.fill_render_sentinels(p)" in run_src,
       "run.py REUSES _common.fill_render_sentinels rather than reimplementing the coercion")

    # ---- A3c: THE COERCION RE-FILLED THE KEY `unset` HAD JUST REMOVED --------------------
    # Two correct changes, cancelling. `unset` clears a field by REMOVING the key - repairs.py
    # says "CLEARING IS REMOVAL", because writing a sentinel over it would make the ledger row
    # claim the repair SET a value. `fill_render_sentinels` re-fills EVERY chrome-read key with
    # its honest unknown, which is right at the RENDER boundary (build_dashboard and the gates
    # call it on a COPY) and wrong in the coercion pass above, which runs on canonical ITSELF.
    # So `unset` did not work on ANY chrome-read field, while the repair reported CLEARED,
    # printed a CLEARED line and wrote a CLEARED Source Ledger row: a withdrawal the operator
    # could see confirmed in three places and could not see happen.
    print("\nA3c: a field an applied `unset` cleared stays cleared through the coercion")
    with tempfile.TemporaryDirectory() as td_s:
        f = Path(td_s) / "canonical.json"
        _pu = _prop(1, clearHeight=10.5)
        _pu.pop("loadingDocks", None)      # exactly what an applied `unset` leaves behind
        f.write_text(json.dumps(_canonical([_pu])), encoding="utf-8")
        # the report's OWN shape, as repairs.apply writes it - `cleared: True` per change
        _rep_u = {"applied": [{"id": "r-u", "property_id": 1, "key": "Park 1", "media": {},
                               "changed": {"loadingDocks": {"from": "12", "to": "(cleared)",
                                                            "cleared": True}}}]}
        _cl = R._repairs_cleared(_rep_u)
        ck(_cl == {"1": {"loadingDocks"}},
           f"the cleared fields are READ off the report, per property, never inferred from the "
           f"shape of the data ({_cl})")
        R._coerce_repaired_scalars(f, _cl)
        _back = json.loads(f.read_text(encoding="utf-8"))["properties"][0]
        ck("loadingDocks" not in _back,
           f"a chrome-read key an applied `unset` REMOVED is still absent after the coercion "
           f"pass (got {_back.get('loadingDocks', '<absent>')!r})")
        ck(_back.get("clearHeight") == "10.5",
           f"...and the wrongly-typed scalar beside it is STILL coerced "
           f"({_back.get('clearHeight')!r}) - both behaviours survive, which is the whole item")
        # THE CONTROL, so the assertion above cannot pass for the wrong reason: called WITHOUT
        # the report - i.e. exactly as the call site used to call it - the key comes back.
        f.write_text(json.dumps(_canonical([_pu])), encoding="utf-8")
        R._coerce_repaired_scalars(f)
        ck(json.loads(f.read_text(encoding="utf-8"))["properties"][0].get("loadingDocks")
           == "tbd",
           "control: with no report the fill puts it back as `tbd` - correct at the render "
           "boundary, and the defect on canonical")
        # and the new parameter must not reach a field nothing cleared
        f.write_text(json.dumps(_canonical([_prop(2, loadingDocks=12)])), encoding="utf-8")
        R._coerce_repaired_scalars(f, {"2": {"someOtherField"}})
        ck(json.loads(f.read_text(encoding="utf-8"))["properties"][0].get("loadingDocks")
           == "12",
           "a property whose cleared set names a DIFFERENT field is coerced exactly as before")
        # a `set` that legitimately re-wrote the same field on a later entry is left alone:
        # the re-removal is conditioned on the key being absent RIGHT NOW, not on the report
        # alone, so the two verbs cannot fight over one value.
        f.write_text(json.dumps(_canonical([_prop(3, loadingDocks="9")])), encoding="utf-8")
        R._coerce_repaired_scalars(f, {"3": {"loadingDocks"}})
        ck(json.loads(f.read_text(encoding="utf-8"))["properties"][0].get("loadingDocks")
           == "9",
           "a field named as cleared but PRESENT again (a later `set`) keeps its value - the "
           "re-removal only ever restores a removal that is already there")
    ck("_repairs_cleared(_rrep)" in run_src,
       "and the repairs stage passes the report's own cleared set into the coercion, rather "
       "than the coercion guessing which fields were withdrawn")

    # the degraded structural check is no longer a route around the schema
    _sfs = set(C._string_fields_struct())
    ck({"country", "park", "developer", "city", "status", "photo"} <= _sfs,
       "the degraded string-type floor still covers the original six (widened, never narrowed)")
    ck(set(C.STRING_FIELDS) <= _sfs,
       f"...and now covers every STRING_FIELDS entry ({len(_sfs)} fields)")
    _errs = C._structural_errors(_canonical([_prop(1, loadingDocks=12, description=["a"])]))
    ck(any("loadingDocks" in e for e in _errs) and any("description" in e for e in _errs),
       f"a wrongly-typed value in a NON-required string field is now caught on a "
       f"jsonschema-less host ({len(_errs)} error(s))")
    # ...and the widened floor is built ONCE, not once per property. `_structural_errors` calls
    # it inside its per-property loop, so a set union of two field lists plus a sort ran for
    # every property on the degraded path - the path a jsonschema-less host takes for EVERY
    # validate-data call. Identity, not equality: an equal-but-fresh tuple each call is exactly
    # the defect.
    ck(C._string_fields_struct() is C._string_fields_struct(),
       "the degraded string-field set is memoised at module level (the same object each call, "
       "not rebuilt per property inside _structural_errors)")
    ck(C._string_fields_struct() == tuple(sorted(set(C.STRING_FIELDS)
                                                 | set(C.REQUIRED_TEXT_SENTINELS) | {"photo"})),
       "...and the memoised value is still the full union, so nothing was narrowed to cache it")

    # ================= T1b: the resume predicate excludes the work dir ====================
    # A work dir INSIDE the inputs folder is the natural layout, and intake.discover has
    # excluded it from its own recursive walk since T1. The resume predicate never got the same
    # parameter, so every artefact the run wrote - canonical, the scorecards, the ledger, the
    # per-property views, timings.json - counted as an input NEWER than inventory.json and the
    # folder scan could never be current: intake re-ran and re-discovered on every pass.
    #
    # THE ATTRIBUTION, ON THE RECORD: this is not the timing instrument's doing. timings.json is
    # genuinely the last write of a pass, but the UNCONDITIONAL gate1_scorecard.md write in
    # gates:pre already fired every pass long before, and so did the canonical and ledger
    # writes - reverting the instrument would have changed nothing.
    #
    # workdir_exclusion_test covers the INTAKE half and only that: it imports intake and never
    # touches the predicate, which is why the predicate half is pinned here.
    print("\nT1b: a work dir inside the inputs folder no longer blocks the folder scan")
    _saved_resume = R.RESUME
    try:
        R.RESUME = True
        with tempfile.TemporaryDirectory() as td_s:
            _inputs = Path(td_s) / "1. Input"
            _inputs.mkdir()
            _wd = _inputs / "work"          # the work dir, INSIDE the inputs folder
            _wd.mkdir()
            _src = _inputs / "options.pdf"
            _src.write_text("x", encoding="utf-8")
            _inv = _wd / "inventory.json"
            _inv.write_text("{}", encoding="utf-8")
            _views = _wd / "properties" / "p1"
            _views.mkdir(parents=True)
            _art = _views / "sources.csv"    # a nested work artefact, written after the scan
            _art.write_text("x", encoding="utf-8")
            # explicit mtimes: the real input is oldest, the inventory next, the run's own
            # outputs newest - i.e. the state a work dir is in the moment a pass finishes.
            _now = time.time()
            for _p, _age in ((_inputs, 300), (_src, 300), (_inv, 200),
                             (_wd, 100), (_views, 100), (_art, 100)):
                os.utime(_p, (_now - _age, _now - _age))
            ck(R._is_current(_inv, [_inputs]) is False,
               "without the exclusion the folder scan is NEVER current - the run's own outputs "
               "are read as inputs newer than the inventory (the defect)")
            ck(R._is_current(_inv, [_inputs], exclude_dir=_wd) is True,
               "with exclude_dir=<work> it resumes: the run's own output tree is not its input")
            # the exclusion must not blind the predicate to a REAL change
            os.utime(_src, (_now - 50, _now - 50))
            ck(R._is_current(_inv, [_inputs], exclude_dir=_wd) is False,
               "a genuinely edited INPUT still invalidates the scan - the exclusion narrows the "
               "walk, it does not switch the predicate off")
            # an unresolvable exclusion degrades to the old behaviour rather than crashing
            os.utime(_src, (_now - 300, _now - 300))
            ck(R._is_current(_inv, [_inputs], exclude_dir=None) is False,
               "exclude_dir=None is the DEFAULT and byte-identical to the old behaviour, so "
               "every other call site is unchanged")
            # a file input that happens to LIVE in the work dir is still an input: only the
            # directory walk is filtered. intake_clusters.json is exactly this case.
            _clusters = _wd / "intake_clusters.json"
            _clusters.write_text("{}", encoding="utf-8")
            os.utime(_clusters, (_now - 50, _now - 50))
            ck(R._is_current(_inv, [_inputs, _clusters], exclude_dir=_wd) is False,
               "an explicitly DECLARED file input inside the work dir still counts (writing "
               "intake_clusters.json must re-cluster) - only the walk is filtered")
    finally:
        R.RESUME = _saved_resume
    # exactly one call site passes it, and it is the folder scan: every other site stays
    # byte-identical, which is the whole reason the parameter is defaulted.
    ck(run_src.count("exclude_dir=work)") == 1,
       f"exactly one _is_current call site passes exclude_dir "
       f"({run_src.count('exclude_dir=work)')})")
    _fs_at = run_src.find('_is_current(work / "inventory.json"')
    ck(0 < _fs_at and "exclude_dir=work" in run_src[_fs_at:_fs_at + 300],
       "and it is the folder-scan site (the only one taking a directory input that can "
       "contain the work dir)")
    ck("exclude_dir" in (HELPERS / "intake.py").read_text(encoding="utf-8"),
       "the parameter name MIRRORS intake.discover(exclude_dir=...), so the two walks that "
       "must agree about what is an input are spelled the same")

    # ================= A5 / A26: one pass per exit, and the cheapest re-entry =============
    print("\nA5/A26: every blocked gate class named in one pass; the re-entry hint is derived")
    ck("def blocked_gate_names(" in run_src and "_GATE_RESULTS_LAST" in run_src,
       "the gate names survive write_scorecard's clear, so the exit can name every blocked one")
    # ...and it is genuinely callable with nothing recorded, returning an empty LIST rather than
    # raising or returning None: the exit path calls it unconditionally, so a run with no
    # blocked gate must get "nothing blocked", not a crash on the way to reporting success.
    ck(R.blocked_gate_names() == [],
       f"blocked_gate_names() on a fresh module is an empty list ({R.blocked_gate_names()!r})")
    _cls = run_src.find("ONE CLASSIFICATION, NOT THREE SHORT-CIRCUITING")
    ck(_cls > 0, "the pre-build exits are one classification over the results list")
    # BOUNDED BY THE NEXT STAGE BOUNDARY, not by a character count. A fixed 4200-char window
    # silently stopped covering the exit-13 assertion the moment the block grew (the re-entry
    # hints landing at exits 5 and 6), which is the same class of stale-by-construction guard
    # this eval keeps finding in the code.
    _seg = run_src[_cls:run_src.find('_stage("build")', _cls)]
    ck(len(_seg) > 1000, f"the classification block is bounded by the build boundary "
                         f"({len(_seg)} chars), not by a character count that goes stale")
    ck("_blocked = blocked_gate_names()" in _seg and "THAT IS\n" in _seg + "\n" or
       "THAT IS" in _seg,
       "it names EVERY blocked class before choosing an exit code")
    for _code in ("sys.exit(5)", "sys.exit(6)"):
        ck(_code in _seg, f"the {_code} branch is preserved")
    ck("_exit_round_trip(work, 13, _attempts, \"value-format clarification\"" in _seg,
       "the exit-13 path keeps _exit_round_trip (its streak/diagnosis accounting)")
    _post = run_src.find('_stage("gates:post")')
    ck(0 < _seg.find("sys.exit(6)") + _cls < _post,
       "exit 6 still fires BEFORE the build - the shift-left is not merged with the "
       "post-build gates")

    # the re-entry hint: repair -> --from repairs; anything pre-merge -> a full pass
    _sv = sys.argv
    try:
        sys.argv = ["helpers/run.py", "--project", "C:/A Project", "--geocode",
                    "--from", "merge"]
        _rep_hint = R._reentry("repair")
        _pre_hint = R._reentry("premerge")
    finally:
        sys.argv = _sv
    print(f"    repair   -> {_rep_hint.strip()}")
    print(f"    premerge -> {_pre_hint.strip()}")
    ck(_rep_hint.rstrip().endswith("--from repairs"),
       "a repair-channel correction is offered `--from repairs` (it applies post-merge)")
    ck("--from merge" not in _rep_hint and "--from merge" not in _pre_hint,
       "a --from/--only already on the command line is STRIPPED, so the hint cannot compound "
       "a previous cut into one that skips more than the channel allows")
    ck('"C:/A Project"' in _rep_hint and "--geocode" in _rep_hint,
       "the hint reuses this invocation's own arguments (copy-pasteable, quoted)")
    ck("--from" not in _pre_hint and "full pass" in _pre_hint,
       "a pre-merge correction (override / answer / adjudication) is told a full pass is "
       "required, with no cut offered")
    ck("enrichment" in _pre_hint,
       "...and that enrichment now skips itself when no location moved (the A1 stamp)")
    ck(_rep_hint.count("\n") == 0 and _pre_hint.count("\n") == 0,
       "each hint is ONE line")
    # ---- A26b: THE THREE COMMONEST CORRECTION EXITS HAD NO HINT AT ALL -------------------
    # The helper was called at eight sites and at NONE of exit 5 (validate-data), exit 6 (every
    # other pre-build gate) or exit 15 (a blocking QA finding) - against an item whose claim is
    # that it is "printed at each correction exit". Exit 6 is where the blocking title-collision
    # gate lands, and that gate's own message names a `work/repairs.json` set as the remedy, so
    # the cheap re-entry was valid and simply never offered.
    #
    # ALL THREE CAN BE RESOLVED THROUGH MORE THAN ONE CHANNEL, so they get the both-channels
    # line rather than a guess. Guessing is the one way a re-entry hint does HARM instead of
    # nothing: `--from repairs` puts extract, merge and enrichment out of scope, so offering it
    # for a fix that lands in an input file or in code would skip the very stage that changed.
    try:
        sys.argv = ["helpers/run.py", "--project", "C:/A Project"]
        _either = R._reentry("either")
    finally:
        sys.argv = _sv
    print(f"    either   -> {_either.strip()[:150]}...")
    ck(_either.count("\n") == 0, "the both-channels hint is ONE line too")
    ck("--from repairs" in _either and "repairs.json" in _either,
       "it offers the repair cut, named against the file that earns it")
    ck("full pass" in _either and "code change" in _either,
       "...and says plainly that an override, an answer, an edited input or a code change "
       "needs the full pass instead - the hint must not skip the stage the fix landed in")
    # it is wired at the exits that ask for a correction
    _n_hints = run_src.count('print(_reentry("')
    ck(_n_hints >= 8, f"the hint is printed at {_n_hints} correction-expecting exits")
    for _what in ('"unsure match/value adjudication"', '"cross-source match/value adjudication"',
                  '"excluded-figure confirmation"', '"value-format clarification"'):
        _at = run_src.find(_what)
        ck(_at > 0 and "_reentry(" in run_src[max(0, _at - 700):_at],
           f"the exit for {_what} prints a re-entry hint")
    # ...INCLUDING the three that had none. Anchored on the exit STATEMENT (indentation and
    # all, so a `sys.exit(6)` quoted in a comment cannot be mistaken for the exit itself) and
    # searched BACKWARDS, so the hint has to be on the path that reaches it, not merely nearby.
    for _exit, _label in (("\n            sys.exit(5)", "validate-data (exit 5)"),
                          ("\n        sys.exit(6)", "every other pre-build gate (exit 6)"),
                          ("\n        _exit_round_trip(work, 15, _attempts",
                           "a blocking QA finding (exit 15)")):
        ck(run_src.count(_exit) == 1,
           f"{_label}: its exit statement is anchorable exactly once "
           f"({run_src.count(_exit)} match(es))")
        _at = run_src.find(_exit)
        ck(_at > 0 and 'print(_reentry("either"))' in run_src[max(0, _at - 900):_at],
           f"the correction exit for {_label} prints the both-channels re-entry hint")

    # ---- A2d: THE `--from` / `--only` HELP TEXT NO LONGER OVERSTATES ITS REACH -----------
    # It promised "every stage BEFORE it is treated as current and skipped". The extract
    # stage's BODY runs unconditionally - the readers dispatch, the photo clustering, the
    # interpretation manifest and the exit-3/9/10 handoffs - and only its per-tracker record
    # derivation consults the cut, so on a warm work dir `--from` is behaviourally identical to
    # the default resume and its only real saving is under --no-resume. The GATING IS
    # DELIBERATELY UNCHANGED (those handoffs have to keep firing); the CLAIM is what was wrong.
    #
    # CHECKED AGAINST THE RENDERED --help, not the source, for two reasons: it is the text an
    # operator actually reads, and argparse help is built from adjacent string literals, so a
    # source scan cannot see a phrase that happens to straddle two of them - which is its own
    # small version of this whole class of defect.
    print("\nA2d: the --from / --only help text states what the flags actually do")
    _help = subprocess.run([sys.executable, str(HELPERS / "run.py"), "--help"],
                           capture_output=True, text=True, timeout=180)
    _ht = (_help.stdout or "") + (_help.stderr or "")
    ck(_help.returncode == 0 and "--from" in _ht, f"--help renders (exit {_help.returncode})")
    # the docstring's own CLI block, whose wording the change manifest quotes
    _cli = run_src[run_src.find("  --from <stage>"):run_src.find("  Stage vocabulary")]

    def _flat(s: str) -> str:
        """Whitespace-collapsed, lower-cased. Both texts WRAP - argparse rewraps at render
        time and the docstring is hand-wrapped - so any phrase check on the raw string is a
        coin toss on where the line broke. Flattening is the only honest way to ask whether a
        CLAIM is present."""
        return re.sub(r"\s+", " ", s).lower()

    for _where, _txt in (("the rendered --help", _flat(_ht)),
                         ("the module docstring CLI block", _flat(_cli))):
        ck("treated as current and skipped" not in _txt,
           f"{_where}: the stale 'treated as current and skipped' promise is gone")
        ck("out of scope" in _txt,
           f"{_where}: it says what the flag DOES - it puts stages out of scope")
        ck("per-tracker record" in _txt and "extract" in _txt,
           f"{_where}: and names the extract-body caveat, which is why the promise was wrong")
        ck("warm work dir" in _txt and "--no-resume" in _txt,
           f"{_where}: including that a warm work dir makes it equivalent to plain resume, so "
           f"the measurable saving is under --no-resume")

    print(f"\n{'FAIL' if fails else 'OK'} stage_control_test: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
