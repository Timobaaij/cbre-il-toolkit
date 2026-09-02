---
name: cbre-property-longlist
description: Build a self-contained, CBRE-branded interactive HTML property LONGLIST DASHBOARD for Industrial & Logistics occupiers from raw market inputs. Ingests a folder of property materials (landlord/agent emails, Excel availability sheets, PPTX and PDF brochures, images) and structures them into ONE portable .html file (a filterable card grid, comparison, a Leaflet map and detail modals) visually identical to the CBRE reference, plus an auditable Source Ledger and a Gaps Report. Every field traces to a source and unknowns show as 'tbd', never invented; generalised per project via project.yaml, reusable across clients. Use whenever the user wants to build a longlist, build the property longlist, create the property dashboard, make the options HTML, a shortlist dashboard, a longlist of options, or turn a folder of brochures/emails into a dashboard. Trigger even when the need is only described (turn this folder of options into the usual dashboard; make the CBRE options page for client X).
---

# CBRE Property Longlist

Turns a folder of heterogeneous property inputs (emails, Excel, PPTX + PDF brochures, images)
into **one self-contained, CBRE-branded interactive HTML longlist dashboard** plus an
auditable Source Ledger, a Gaps Report and a flat Longlist workbook. Reusable across client
projects, defensible by construction.

**How to read this file:** "The loop" is the whole job - run one command, read one exit code,
do the ONE mapped action, re-run. Every turn's complete instruction is the printed handoff
plus the rendered `work/prompts/*.md` files; this card only teaches the loop. Detail lives in
`reference/` and is read when a handoff names it, not up front.

## Run the helpers - do NOT read the inputs yourself (CRITICAL)

This skill works by **RUNNING the deterministic Python helpers through your shell** - never by
you reading the PDFs/spreadsheets and typing what you see. **Your FIRST action is always
`helpers/run.py`.** Brochures ARE structured by reading them, but that reading is done by an
**ISOLATED interpretation sub-agent** that `run.py` dispatches you to (exit 3 + a manifest) -
never by the orchestrator inline: an isolated author + the blind honesty gates preserve
author != reviewer, and the orchestrator reading inputs inline bypasses the gates, the Source
Ledger and the honesty checks (and misreads dense spec tables). The governing rule is the
**Data Honesty Standard** (`reference/evidence-standard.md`): nothing reaches a card that does
not trace to a source file; every unknown is an explicit `"tbd"`, never invented, never
silently dropped. Two design commitments: **independent review** (every judgement check runs
in a fresh-context agent, blind to your view - `reference/gates.md`) and **shift-left** (data
is validated BEFORE the expensive build).

## The project folder - THREE folders, nothing else (set up FIRST)

```
<project folder>/
  1. Input        <- what the broker supplied
  2. Work Files   <- every internal pipeline artefact. THIS is "the work directory" (--work)
  3. Output       <- ONLY the four client-facing deliverables (the .html lives here)
```

Create the three folders, move the user's inputs into `1. Input` (no extra nesting), then:

```
python helpers/run.py --project "<project folder>" --client "<Name>" [--geocode --pois --osrm --regions]
```

`--project` derives all three paths and creates the missing ones. Anything else at the top
level goes into `1. Input/_originals/` or `2. Work Files/_scratch/` (a leading underscore
makes intake skip it - for duplicates and scratch ONLY, never to resolve a data conflict:
excluding an input is the broker's decision, via exit 13). Everywhere below, `work/<x>` means
the work directory; the exit-3 manifest's `work/` prefix is a convention resolved against it.
**Backward compatibility:** `--folder`/`--work` still work; a run given only those delivers to
`<work>/deliverables`. For a NEW project, always use `--project`.

## The loop (this is the whole job)

1. **Run the spine ONCE** (the command above; in Cowork the sandbox shell, on a Windows MCP
   host `mcp__shell__run_command` with absolute paths - `reference/environment.md`). Read its
   `Plan:` line. Integrity is checked automatically (exit 4 = restart the session); call
   `helpers/preflight.py` by hand only if `run.py` fails to start at all.
2. **Read the EXIT CODE, do EXACTLY the one mapped action, re-run the SAME command:**

| exit | meaning | the ONE sanctioned action |
|---|---|---|
| 0 | **DONE-DONE** | nothing. The spine itself recorded the QA round, folded the advisories into the Gaps Report, re-delivered, and `final_gate` went GREEN - tell the broker where the deliverables are |
| 2 | no usable inputs | check the folder / `project.yaml`, fix, re-run |
| 3 | **interpretation** needed | dispatch each rendered `work/prompts/*.md` file VERBATIM as an isolated sub-agent - deck readers (text/raster per the manifest `mode`; write each deck's own `output` path copied verbatim - never derive a filename from the cluster label), tracker map PLUS its SEPARATE blind `tracker_verify` agent (or decline a map with `<output>.SKIP`), optional cluster labels. When the hand-off LEADS with `SETUP FIRST`, present the Stage-0 form in the SAME message as these dispatches and write `setup.confirmed: true` with the answers. (`reference/interpretation.md`) |
| 4 | skill files truncated | restart the session, then re-run |
| 5 | `validate-data` blocked | read `gate1_scorecard.md`; record the correction in **`work/overrides.json`** (below), NEVER by editing `work/extract/` (derived - your edit is discarded) |
| 6 | another pre-build gate blocked | read `gate1_scorecard.md`, fix the named gate, re-run. A DATUM fix goes in `work/overrides.json`. **`value-format`** (a bare `5000` beside `10,000 sq. m`) asks the BROKER ITSELF via blocking exit-13 questions - answers become attributed repairs, "leave as is" ships the bare value disclosed; **Never append the sibling's unit yourself** (the 10.76x class). A sign-off-key gate (`images`, `arithmetic`, `media-harvest`) is acked with `gate_runner.py ack --work <work> --add <key>=<v1,v2>`, NEVER by writing `placeholder_audit_ack.json` yourself (ack merges; hand-writing drops a concurrent agent's key) |
| 7 | a post-build / ship gate blocked | read the gate output (`work/final_gate_report.md` for final_gate), fix, re-run |
| 8 | **web enrichment** needed | the printed handoff carries the four-tier ladder: (1) `mcp__shell` re-run, (2) Playwright data:-URL fetcher, (3) Claude Preview MCP, (4) deliver `web_enrich.html` in the chat - the UNIVERSAL fallback; never an error, never straight-line estimates, never WebFetch to the API hosts (`reference/agentic-steps.md`) |
| 9 | **photo-match** needed | dispatch the rendered photo-match prompt -> `work/photo_map.json` (confident / uncertain / unrelated - never drop a property), re-run |
| 10 | **match adjudication** needed | dispatch the rendered match prompt -> `work/match_decisions.json` + `work/field_decisions.json`, PLUS the SEPARATE blind verifier -> `work/match_verify.json` (`reference/matching.md`) |
| 11 | dashboard-language translation | dispatch the rendered translate-chrome prompt -> `work/i18n/<code>.json` (or `<code>.SKIP` for English). 13 languages are bundled and render instantly (`reference/localisation.md`) |
| 12 | free-text DATA translation | dispatch the rendered translate-data prompt -> merge the map into `work/i18n/data_translations.<code>.json` (or drop `work/i18n/data_translate.SKIP` to decline) |
| 13 | **clarification** needed | read `work/questions.json`. A `setup_form` question means the Stage-0 form has not been answered: present it (`reference/setup-form.md`) and write the answers plus `setup.confirmed: true` into `project.yaml` - an `answers.json` entry does NOT clear that one. `asked_of:"agent"` = dispatch an isolated sub-agent with the named source; `asked_of:"broker"` = put ALL of them to the user in ONE plain message. Write `work/answers.json` `{"<id>": "<answer>"}` (ids verbatim; where `options` is given, one of those exact strings). `blocking:false` is asked ONCE, then ships the honest gap; `blocking:true` comes back every pass until ANSWERED or DECLINED (`"skip"` = the default ships as a disclosed decision; headless: `work/clarify.SKIP_ALL`). **Never answer a blocking broker question from your own context**. Every question here already PASSED the materiality test - it changes a value/photo shown on the dashboard or the number of options - so put it to the user rather than second-guessing whether it matters; what did not pass is in the Gaps Report's "Noted, not put to you" |
| 14 | **independent QA review** needed | dispatch ONE isolated sub-agent per rendered `work/prompts/g-*.md` file (CONCURRENTLY; each file is that agent's VERBATIM prompt and names its own output file), plus any outstanding email ingestion the handoff names -> re-run |
| 15 | **blocking QA finding(s)** unresolved | IMPLEMENT each fix, record it with `gate_runner.py qa-round resolve --work <work> --id <id> --because "<what you changed>"` (ids: `qa-round status`), re-run. Advisory findings are never fixed - they ship in the Gaps Report's Known limitations |

3. **Rendered dispatch prompts (`work/prompts/`).** Every agentic handoff renders the
   canonical prompt per pending job. **Dispatch each file's contents VERBATIM** - a
   hand-written paraphrase is the documented top error surface. You may append run-specific
   FACTS under the file's 'Run context' heading only. A job kind with no rendered prompt is
   the ONE case you author by hand from the reference contract (`prompts/outlook-ingest.md`
   is the one deliberate hand-filled template). The rendered files carry ABSOLUTE output
   paths - never let a sub-agent create a literal `work/` folder at the project root.
4. **Slow / killed / "it timed out"?** That is the ~45s sandbox shell cap, BY DESIGN - just
   re-run the SAME command. **Resume is the DEFAULT**: every pass continues from the work-dir
   cache and makes progress (the `photo cache: X/Y` line tracks the parallel image pre-warm on
   media-heavy runs; several passes are normal). The gates and the freeze are never skipped. A
   changed input invalidates its stage automatically.
5. **Repeat-handoff diagnosis:** when the same exit re-fires, the spine prints `[pending]`
   lines naming the guard's EXACT unmet predicates (persisted to `work/pending_diagnosis.json`)
   - satisfy those lines; never guess at what the guard reads.

**Forbidden moves (each was actually tried in a real run and is WRONG):**
- Do NOT hand-write or edit `canonical.json` / `built.html` - pipeline outputs; the gates
  reject a hand-built one anyway.
- Do NOT monkey-patch, bypass or "simplify" a helper, and do NOT skip image harvesting.
- Do NOT read the source PDFs/sheets and type the data in yourself (the anti-pattern above).
- Do NOT invent or estimate any value - an unknown is `tbd`, never a guess.
- Do NOT answer a blocking exit-13 question yourself, and do NOT try to clear one by
  re-running. Ask the human; a stated "no preference" is recorded as `"skip"`.
- Do NOT paste an abbreviated field list into a sub-agent prompt - a list in the prompt reads
  as the SPECIFICATION and silently overrides the contract (the single highest-cost
  orchestrator mistake on record). The rendered prompt already carries the contract.
- Do NOT accept a reader's "there is no canonical field for X, so I dropped it" - that
  sentence is a **BLOCKING signal, not an accepted limitation**: the schema is OPEN and
  **CAPTURE EVERY FIELD THE SOURCE STATES** is the Stage-1 rule (a stated value with no
  canonical home is emitted under a descriptive camelCase key). On the run that produced this
  rule, ~100 false "absent in all sources" claims shipped.
- Do NOT hand-edit `work/extract/*.json` - DERIVED; corrections go in `work/overrides.json`.

When you feel the urge to improvise: re-run the same command, or read `gate1_scorecard.md`.

## Correcting data

- **A SOURCE RECORD cell** -> **`work/overrides.json`** (a JSON list; re-applied after every
  extraction, so it survives re-runs). Each entry: `where` (source_file + `sheet`+`row` or
  `page_no`; zero matches = **STALE**, several = **AMBIGUOUS** - both apply nothing),
  optional `expect` (mismatch = **SUPERSEDED**, applies nothing), REQUIRED non-empty `why`,
  `verified_by`. It can never create a property or field; **`areaUnit`/`rentUnit` are
  DENIED** (silently relabelling every figure is the 10.76x class - the one sanctioned way a
  unit is set by a human is an exit-13 answer). Every applied correction is DISCLOSED: an
  `override` ledger row, the field's ledger note, and a "Manual corrections applied" Gaps
  line. Full contract + example: `reference/config.md` ("Correcting a datum").
- **A PROPERTY** (wrong precedence pick, missing field, wrong hero) -> **`work/repairs.json`**,
  keyed by the property's repair key + id with an `expect` guard (refuses rather than landing
  on the wrong card); `why` and `verified_by` required; runs BEFORE the gates. The READ-ONLY
  per-property view (`work/properties/<id>-<slug>/` - property.json, media + the
  `media/considered/` discard pile, sources.csv, notes.md with the repair key;
  `_unassigned/` holds deck pages no property claimed) answers "what did this card have to
  choose from". Full contract: `reference/per-property.md`.

## Output discipline - quiet in Cowork

Brokers neither read nor want technical chatter. Show only: (1) the Stage-0 setup form; (2)
ONE short plain-English step marker per stage; (3) anything that genuinely needs the broker -
**a batched exit-13 question round is sanctioned output, never a silence violation** (that IS
the interactive standard mode working); (4) the final hand-off. Suppress everything else - no
tool logs, no scorecards, no tracebacks (surface a failure as ONE plain sentence). Quiet is the DEFAULT (`--verbose` opts out, for
debugging the skill); every `(orchestrator: ...)` handoff prints on stdout in both modes.
This governs the on-screen chat ONLY - the gates, freeze and reviewers all still run and
write their artefacts.

## What this produces (in `3. Output`; a legacy `--folder` run: `<work>/deliverables`)

1. **`CBRE_Property_Dashboard_<Client>.html`** - card grid + carousel, filters, comparison,
   Leaflet map, detail modals; byte-identical chrome to the frozen template
   (`assets/dashboard_template.html`) with exactly three injected data blocks -
   `gate_runner.py validate-html` re-asserts byte-identity (`reference/template-contract.md`).
2. **`<Client>_Source_Ledger.xlsx`** - every field mapped to its source + locator.
3. **`<Client>_Gaps_Report.md`** - every `tbd`, conflict, exclusion and enrichment gap, each
   with how to close it, plus the QA round's "Known limitations".
4. **`<Client>_Longlist.xlsx`** - one property per row, ALL fields in columns (open-captured
   tracker columns included). Source of truth: `canonical.json`
   (`templates/canonical.schema.json`).

## The pipeline in brief (detail: `reference/pipeline.md`)

Intake -> extract (**CAPTURE EVERY FIELD THE SOURCE STATES** - the manifest's `fields` array
is a FLOOR, not a ceiling; xlsx/emails deterministic, decks via exit 3) -> match & merge
(dedupe by city+developer+park, never within one brochure; grey pairs via exit 10; precedence:
newest email wins commercials, brochure wins specs) -> enrich (per flags) -> pre-build gates
(self-check, validate-data, coverage, input-accounting, capture-symmetry, media-harvest,
trace-coverage, prov-containment, images, arithmetic, value-format, coord-provenance,
enrichment, translation, ledger validate - all in `gate1_scorecard.md`; **read
capture-symmetry's `[SIGNAL]` lines and media-harvest's `[SIGNAL]`/`[FAIL]` lines** - they are
the under-capture and media-blind-spot signals no other gate can see; the spine freezes
`canonical.json` automatically at ALL-PASS) -> build (byte-deterministic) -> post-build gates
(validate-html, reconcile, i18n, G-visual via `render_qa.py`; if Playwright is absent it
prints `STATUS: NEEDS-PREVIEW-MCP` - drive G-visual via the Claude Preview MCP, don't skip) ->
QA window (exits 14/15) -> deliver + final_gate (run by the spine). Run
`python helpers/version_check.py` once at the start of a run (a one-line update nudge, never
blocking).

## The broker setup prompt (ONE consolidated form, at Stage 0)

Present **ONE consolidated `visualize` widget** (`mcp__visualize__show_widget`, passing the
elicitation form in **`reference/setup-form.md`** verbatim; call `mcp__visualize__read_me`
with `modules:["elicitation"]` once first) **in the SAME message as the first exit-3
dispatch** - no form answer feeds that round, so serialising them wastes broker think-time.
It asks ALL SIX questions at once - client name (it names every deliverable), extras
(drive-time maps / workforce snapshot / logistics landmarks), an openrouteservice key
(a FIELD IN THIS FORM, never a follow-up; blank = car times, disclosed), Outlook emails
(a named mail folder / all of Outlook / no), dashboard language (English default; 13
bundled including Simplified Chinese; any other European Latin-script language translates
once via exit 11 and is cached), and ask mode ("Ask me when unsure" = `clarify.mode:
interactive`, the STANDARD - judgement calls the files cannot settle become exit-13
questions, but ONLY where the answer changes what the dashboard shows or how many options
ship; everything else is disclosed, not asked - "Decide sensibly" = `headless`,
default-honestly-and-disclose).
**Never `AskUserQuestion`, never one-question-at-a-time.**
Parse the single submission line and persist every answer in `project.yaml` (`client:`,
`enrichment:`, `enrichment.ors_api_key`, `inputs.emails:`, `output.language`,
`clarify.mode` - `reference/config.md`) **AND set `setup.confirmed: true`** so re-runs are
non-interactive. SKIP the widget ONLY when `setup.confirmed` is already true. **Values being
present in `project.yaml` is NOT the test and never was** (B63): intake SCAFFOLDS that file
on the first pass with all six pre-filled - client from `--client`, English, no emails, car
times - so "it already carries the answers" was true on every run and the form was correctly
skipped every time, shipping six guesses the broker never saw. `setup.confirmed` is the only
signal that a human answered. The spine enforces this: while it is false, every hand-off
leads with the form, and a pass with no other hand-off stops at exit 13 for it.
FALLBACK (only if `visualize` is genuinely unavailable): all six in ONE plain-text message.
Email answers map to the Stage-1 `outlook_email_search` sub-agent via
`prompts/outlook-ingest.md` (`reference/agentic-steps.md`).

## The QA window - the reviewers PROPOSE, you IMPLEMENT; the SPINE drives the rest

LOOP-DRIVEN - you never order these steps yourself:

1. **Exit 14** - dispatch ONE fresh blind agent per rendered `work/prompts/g-*.md` file,
   concurrently. Each returns FINDINGS, every line labelled `blocking:` or `advisory:` by the
   reviewer; a reviewer that finds nothing writes `FINDINGS: none`. Re-run.
2. **Exit 15** - the spine ran `qa-round record` itself (Python never classifies a finding)
   and blocking findings are unresolved: **YOU implement each fix** and record it with
   `qa-round resolve --work <work> --id <id> --because "<what you changed>"`. Re-run.
3. **Exit 0** - the spine re-delivered (advisories folded into "Known limitations") and
   `final_gate` went green. Done-done; a red final gate is exit 7 with reasons in
   `work/final_gate_report.md`.

**Prohibitions:** do NOT re-dispatch a reviewer to "confirm the fix" (one review pass; the
repair is recorded, not re-judged). Do NOT fix advisory findings to make them go away (an
advisory is closed by appearing in the Gaps Report; strike one with `qa-round resolve` only
when a blocking fix made it untrue). Do NOT use `--no-reviews` because a finding felt like
friction (it prints `STATUS: DEGRADED`, never ALL-PASS). A recurring cosmetic finding is a
**template** bug - fix it once in `assets/dashboard_template.html` with an eval.

## Environment in one breath

Extraction is native in BOTH environments (Cowork via the bundled `vendor/` PyMuPDF wheel; a
Windows MCP host via system PyMuPDF); every dependency degrades to a bundled shim, a blocked
pip never stops a run, and most data needs NO network (bundled gazetteer, POIs, NUTS-3
workforce dataset) - exit 8 is the one genuinely network-bound step. Which shell, the
direct-executor `mcp__shell` rules, install for teammates, and the Cowork user explainer:
**`reference/environment.md`**. Maintenance (integrity manifest, the eval suite, the
finding-to-gate flywheel, dataset refreshes): **`docs/MAINTENANCE.md`**.

## Reference files

- `reference/evidence-standard.md` - the Data Honesty Standard. **Read first.**
- `reference/pipeline.md` - the eight stages, owners, pass criteria, per-stage CLI.
- `reference/gates.md` - the full gate set + the reviewer dispatch contract.
- `reference/interpretation.md` - exit-3 contracts: deck text/raster, tracker map + blind
  verify, region-label resolution.
- `reference/matching.md` - exit-10 contracts: grey pairs, field conflicts, blind verify.
- `reference/agentic-steps.md` - every agentic step in full (emails, web-enrichment tiers,
  region research, translation, judgement gates).
- `reference/environment.md` - shells, offline design, install, Cowork user explainer.
- `reference/data-engine.md` - per-format extraction, matching tiers, merge precedence.
- `reference/localisation.md` - exits 11/12, bundled languages, G-i18n.
- `reference/setup-form.md` - the verbatim Stage-0 widget + submission parsing.
- `reference/per-property.md` - the per-property view + `work/repairs.json`.
- `reference/config.md` - `project.yaml` schema + `work/overrides.json` + the intake cluster
  cache.
- `reference/template-contract.md` - markers, tokens, byte-stability, versioning.
- `reference/visual-qa.md` - the G-visual render procedure.
- `reference/source-traceability.md` - the field-level Source Ledger contract.
- `reference/failure-modes.md` - the graceful-degradation matrix.
- `docs/MAINTENANCE.md` - for whoever EDITS the skill.

## User preferences (always)

- UK English. No em or en dashes in prose.
- Honesty over completeness: `"tbd"` is first-class, surfaced in the Gaps Report, never
  smoothed over or invented.
- **Source units are KEPT**: imperial inputs ship imperial, metric ship metric; merge
  normalises a mixed dataset to its DOMINANT area unit (arithmetic, prov-noted); currency is
  NEVER converted (FX would be invention). Labels follow `meta.units`.
- The dashboard is byte-identical chrome to the template; only the three data blocks and the
  config tokens change. Edit, do not rebuild: re-runs re-do only the affected stages.
- Reuse the sibling `cbre-corporate-pptx` brand library for CBRE colour/logo needs.
