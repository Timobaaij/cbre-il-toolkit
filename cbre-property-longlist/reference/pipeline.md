# The pipeline - eight stages

Contract between stages: files on disk. The Orchestrator (you) owns `canonical.json`, runs deterministic scripts, dispatches isolated sub-agents for judgement work, and adjudicates verdicts. `helpers/run.py` runs the deterministic spine (Stages 0-7) in one command; the agentic steps are layered around it.

> **Running a single stage directly:** prefer `run.py` (it wires every stage correctly). If you do call a stage by hand, note the per-script CLI differs: `intake.py <folder> --out-dir <work>` (also accepts `--folder`/`--work` aliases), `merge.py --records … --source-dir <inputs> --out <canonical>`, `enrich.py <canonical> --geocode …`, `gate_runner.py <subcommand> …`, `build_dashboard.py <canonical> --out <html>`, `render_qa.py <html> --out <dir>` (`--out-dir` alias). `--help` on any script lists its flags.

| Stage | Owner | In -> Out | Pass criteria |
|---|---|---|---|
| 0 Intake & config | `intake.py` | folder -> `inventory.json`, `project.yaml` | inputs classified + clustered (regex, then LLM-refined at Stage 0 for ambiguous `confidence:"low"` filenames via the input-hashed `work/intake_clusters.json` cache, then broker-confirmed; absent cache = pure regex); >=1 property source (else halt with a gap note); enrichment confirmed with the broker |
| 1 Extract | isolated sub-agents / scripts | files -> `extract/*.json` (+ ledger rows) | per-field provenance; unknowns are `"tbd"`/`null`; a file with 0 records or a thin parse (assessed PER FILE) -> `vision_prep.py` rasters + `work/vision/manifest.json`, run.py exits 3 BEFORE merge/build -> vision sub-agent writes `extract/<region>_vision.json` (`reference/vision-fallback.md`); truly unreadable -> explicit gap |
| 2 Match & merge | `match.py`, `merge.py` | `extract/*` -> `canonical.json`, `source_ledger.csv` | images bound by city+developer+park; cross-source dedupe (never within one brochure) - auto/forbidden tiers deterministic, the GREY-zone ambiguous pairs adjudicated by an isolated sub-agent (run.py exits 10 -> `work/match_candidates.json` -> `work/match_decisions.json` -> re-run; offline the deterministic matcher is the fallback); precedence applied; stable ids; dual-field pairs consistent |
| 3 Enrich (opt-in) | `enrich.py` (+ research sub-agent) | `canonical.json` -> enriched | only chosen toggles run; figures sourced/dated or left absent; degrade, never fabricate |
| 4 PRE-BUILD GATE (BLOCKING) | scripts + isolated reviewers | -> `gate1_scorecard.md`, `reviews/*` | all mechanical + judgement clear; freeze `canonical.json` at `STATUS: ALL-PASS` |
| 5 Build | `build_dashboard.py` | frozen canonical + template -> `built.html` | three blocks injected; chrome byte-identical; nothing added |
| 6 POST-BUILD GATE (BLOCKING) | scripts + isolated reviewer | `built.html` -> `gate2_scorecard.md`, `render/*`, `reviews/G-visual.md` | HTML valid; reconcile clean; visual render passes |
| 7 Deliver | `deliver.py`, `final_gate.py` | -> 3 deliverables | both scorecards ALL-PASS; ledger exported; every gap on the report; final gate green |

## Parallelism
- Stage 1 fans out one sub-agent per source file or per-city cluster (the reference is organised Bratislava / Budapest / Pilsen).
- Stage 4 and 6 judgement reviewers run as parallel isolated sub-agents, dispatched concurrently (all of a phase's `Agent` calls in one message) against a **frozen** artefact (`gate_runner.py freeze` / `freeze --check`) so every reviewer judges byte-identical bytes. One gate = one agent; parallelism strengthens independence (no verdict exists yet to bias another). See `reference/gates.md` "Reviewer dispatch contract".
- **Plain-chat with no sub-agent dispatch is a labelled DEGRADED mode**: verdict files are still written but independence is weaker; say so plainly.

## Re-runs
Edit, do not rebuild. With updated inputs, re-do only the affected stages and re-inject from `canonical.json`. Every judgement re-run uses a fresh isolated reviewer and is **scoped**: re-freeze, then re-dispatch only the gate(s) that returned red - the full batch re-runs only when properties were added/removed or the fix spans several gates' domains (`reference/gates.md` rule 4). Bounded loops (~3) escalate honestly (strike to the Gaps Report) rather than loosening a criterion.

`run.py` resumes BY DEFAULT (`--no-resume` recomputes everything): it skips any stage whose output is already current (intake, per-file extract, merge, enrich, build) and recomputes only what a changed input invalidates. The gates and the freeze are never skipped, so the mechanical and judgement verification still runs in full on every resumed build. Built for sandboxes with a short shell cap (e.g. Cowork's ~45s) and for the vision re-run: a killed or vision-interrupted run resumes instead of restarting from scratch.

**Agentic handoffs are exit codes; after ANY of them, do the one mapped action then re-run the SAME command (resume continues):** exit 3 = a brochure deck or a tracker needs interpretation; exit 8 = web enrichment (geocode/POIs/drive-times); exit 9 = photo-match (textless brochures that are photos of known properties); exit 10 = cross-source match adjudication (GREY-zone pairs -> `work/match_candidates.json` -> `work/match_decisions.json`, `reference/matching.md`). Each writes its manifest to the work dir, caches the sub-agent's decision keyed by a stable hash, and resumes byte-deterministically. None fires when its work is empty (a pure-brochure run never hits 9/10; a single-source run never hits 10).
