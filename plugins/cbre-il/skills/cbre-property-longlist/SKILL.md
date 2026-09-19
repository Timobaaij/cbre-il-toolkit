---
name: cbre-property-longlist
description: Build a self-contained, CBRE-branded interactive HTML property LONGLIST DASHBOARD for Industrial & Logistics occupiers from raw market inputs. Ingests a folder of property materials (landlord/agent emails, Excel availability sheets, PPTX and PDF brochures, images) and structures them into ONE portable .html file (a filterable card grid, comparison, a Leaflet map and detail modals) visually identical to the CBRE reference, plus an auditable Source Ledger and a Gaps Report. Every field traces to a source and unknowns show as 'tbd', never invented; generalised per project via project.yaml, reusable across clients. Use whenever the user wants to build a longlist, build the property longlist, create the property dashboard, make the options HTML, a shortlist dashboard, a longlist of options, or turn a folder of brochures/emails into a dashboard. Trigger even when the need is only described (turn this folder of options into the usual dashboard; make the CBRE options page for client X).
---

# CBRE Property Longlist

Turns a folder of heterogeneous property inputs (emails, Excel, PPTX + PDF brochures, images)
into **one self-contained, CBRE-branded interactive HTML longlist dashboard** plus an
auditable Source Ledger, a Gaps Report and a flat Longlist workbook. Reusable across client
projects, defensible by construction.

**A saved email folder and a zip are first-class inputs.** A `.zip` is unpacked once into
`<zipname>_unpacked` beside itself (idempotently, one level of nesting, never outside the
inputs folder), and a `.msg`/`.eml` has its attachments saved beside it under
`<yyyy-mm-dd>_<subject>_attachments/` before anything is classified, so a brochure that
arrived stapled to an offer email is clustered and read on the SAME run, exactly like a file
the broker dropped in the folder by hand. Inline images (signature logos, `cid:` images,
anything under 20 KB) are excluded. Reading the PROSE stays an LLM step: Python opens the
container, the agent reads the offer.

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

`--project` derives all three paths and creates the missing ones. **Move the zip and the email
folder in as they are** - do not unpack them by hand and do not pull the attachments out.
Intake unpacks each `.zip` into `<zipname>_unpacked/` and writes each email's attachments into
`<yyyy-mm-dd>_<subject>_attachments/`, both INSIDE `1. Input`, and both are idempotent, so
re-running changes nothing and the unpacked files keep their mtimes (which is what lets the
resumed run skip the decks it already read). Unpacking by hand loses the `.from_email.json`
sidecar, and with it the ledger's record of which email carried which brochure. Anything else at the top
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
| 15 | **blocking QA finding(s)** unresolved | IMPLEMENT each fix, record it with `gate_runner.py qa-round resolve --work <work> --id <id> --because "<what you changed>"` (ids: `qa-round status`), re-run. This is a fix loop INSIDE the one review round - **never re-dispatch a reviewer**. Advisory findings ship disclosed in the Gaps Report's Known limitations; fix one only when it is one edit AND changes what a reader concludes, and `resolve` it if you do |
| 16 | **invalid correction entr(y/ies)** - the run refused to START | read the printed fault list (EVERY fault in `work/overrides.json` and `work/repairs.json`, all in one pass) and **FIX the NAMED entries IN PLACE** in the file each fault names - or **DELETE** one that is stale - then re-run the SAME command. **Do NOT append a new entry**: the file being rejected IS the file to edit, so appending re-runs into the same refusal with one more entry each round. **Do NOT read `gate1_scorecard.md`** - this fires at startup, the gates have not run, and on a first pass it does not exist. Nothing has been changed, so there is nothing to undo. To ship past a known-stale entry knowingly, re-run with `--allow-invalid-corrections`: the same faults print, the faulty entries are IGNORED, and whatever they were meant to correct ships UNCORRECTED - tell the broker if you use it |

| 17 | **master list** - the user has not said what to build | the run has inventoried every candidate option and stops BEFORE reading a single brochure. Do all four, in order: (1) dispatch the rendered `work/prompts/master-list.md` VERBATIM -> `work/master_candidates.json` (the email-only rows, named after the property, and the judged SAME-BUILDING groups; a message is never a row and never a group member - every email is on the workbook's Emails tab); (2) `python helpers/master_list_build.py --work "<work>"`; (3) give the user `<work>/Master List.xlsx` and **WAIT** - they set **Include?** to **Yes or No** on every row and write anything the run must know in **Your Run notes for the AI**. **Never fill that column in for them, never infer it from the duplicate groups, never copy the Brochure? column across, never proceed on a partly answered sheet** - the column ships blank and the builder blanks it on every build, because a pre-answered sheet passes the read-back with nobody having decided anything. This is the only point in the run where the user decides scope; (4) `python helpers/master_list_read.py --work "<work>"` (it REFUSES, exit 2, on any row that is not Yes or No, and names them) and re-run the same command (`reference/master-list.md`) |

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
5. **Narrowing a re-run: `--from` and `--only`** (both optional; neither is needed on the
   normal loop, because resume already skips what is current). They answer a different question
   from `--resume`: not "is this output still current?" but "can the correction I just made even
   REACH this stage?". Stage vocabulary, in pipeline order - `folder scan`, `extract`,
   `master list`, `merge`,
   `enrichment`, `repairs`, `projection`, `gates:pre`, `build`, `gates:post`, `deliver`, `qa`
   (a typo stops the run and lists the valid spellings; note the space and the colon).
   - `--from <stage>` puts every stage BEFORE it OUT OF SCOPE, **even under `--no-resume`**:
     each of those reuses its existing output instead of re-deriving it. **What it guarantees
     is REACH, not speed** - a stage put out of scope cannot be CHANGED by that pass. The cut
     is applied by each stage's OWN skip guard rather than by jumping into the run, so an
     out-of-scope stage still runs whatever sits outside that guard, and `extract` is the one
     that matters: its BODY runs on every pass regardless (the readers dispatch, the photo
     clustering, the interpretation manifest and the exit-3/9/10 handoffs), and only its
     per-tracker record derivation consults the cut. So on a warm work dir `--from` is
     behaviourally the SAME as the default resume, and its one measurable saving is under
     `--no-resume`. Use it to STATE reach, never to go faster: `--from repairs` after a
     `work/repairs.json` edit says, in the command itself, that the correction is applied
     AFTER merge and therefore cannot change merge or enrichment. The spine PRINTS the valid
     re-entry at every correction-expecting exit - prefer the printed line over composing your
     own, and note that at exits 5, 6 and 15 it names BOTH channels, because the cut is valid
     only when your fix is a repairs entry (an override, an answer, an edited input or any
     code change is consumed at or before merge, so it needs the full pass).
   - `--only <stage>[,<stage>...]` runs ONLY those stages; every other stage is put out of
     scope, even under `--no-resume`, on exactly the terms above - including the extract-body
     caveat, so `--only build` still pays the extract body.
   - Both **REUSE** a skipped stage's existing output rather than re-deriving it, so the work
     dir must already hold it: they are a re-entry shortcut on a WARM work dir, never a way to
     run one stage on a cold one. On a first pass, pass neither.
   - Neither can reach the **pre-build gates, the post-build gates, the freeze or the QA
     window** - those ALWAYS run, however narrow the cut, so nothing ships unverified.
6. **Repeat-handoff diagnosis:** when the same exit re-fires, the spine prints `[pending]`
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
- **EXPECT this one: two UNNAMED units at ONE location need a hand-authored correction before
  they can ship.** Two records for different buildings on the same site, neither stating a
  unit designator, are kept APART by the matcher (an absent party name on both sides, and a
  one-sided absence, are both out of the auto tier) and then COLLIDE at the blocking
  card-title gate, because with no `unit` the two cards compose the same heading. That is BOTH
  guards working correctly: a fusion is the one matcher error a reader can never see, and the
  gate refuses to ship two cards a reader cannot tell apart. But it is a real operator cost
  and an ordinary corpus of that shape pays it, so expect it rather than discovering it: the
  run blocks at exit 6 naming the collision, and you then set `unit` per card in
  `work/repairs.json` (the gate's own message names the entry) **from what the source actually
  says** - never a designator you invented to clear the gate. Recoverable and correctly
  diagnosed; not something to re-run past.

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

Plus ONE internal artefact the user answers rather than receives: **`<work>/Master List.xlsx`**
(exit 17, `reference/master-list.md`). Every candidate option found in the inputs, one per row,
put to the user BEFORE the brochures are read; they mark each **Yes** or **No**, and only the Yes
rows are built. It is not a deliverable and nothing on it is sent to a client - it decides what
the run builds, and the options struck off it are named in the Gaps Report.

## The pipeline in brief (detail: `reference/pipeline.md`)

Intake -> extract (**CAPTURE EVERY FIELD THE SOURCE STATES** - the manifest's `fields` array
is a FLOOR, not a ceiling; xlsx/emails deterministic, decks via exit 3) -> **master list**
(exit 17: every candidate option on one sheet, the user marks each Yes or No, and ONLY the Yes
rows reach the deck readers - the sheet sits between the cheap reads and the expensive ones on
purpose, `reference/master-list.md`) -> match & merge
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
It asks ALL FIVE questions at once - client name (it names every deliverable), extras
(drive-time maps / workforce snapshot / logistics landmarks), an openrouteservice key
(a FIELD IN THIS FORM, never a follow-up; blank = car times, disclosed), Outlook emails
(a named mail folder / all of Outlook / no), and dashboard language (English default; 13
bundled including Simplified Chinese; any other European Latin-script language translates
once via exit 11 and is cached).
**ASKING WHEN UNSURE IS FIXED, NOT ASKED.** `clarify.mode: interactive` is policy: a
judgement call the files cannot settle becomes an exit-13 question, but ONLY where the
answer changes what the dashboard shows or how many options ship; everything else is
disclosed in the Gaps Report, not asked. There used to be a sixth pill offering
"Decide sensibly" (`headless`) instead; it was removed on 2026-09-19 because the answer
that saves the broker a prompt is the same answer that ships them a guess, and that is not
a trade worth putting in a form. The headless path survives ONLY as an explicit escape for
a run with no human in it: `work/clarify.SKIP_ALL` or `clarify.assume_defaults: true`.
**Never `AskUserQuestion`, never one-question-at-a-time.**
Parse the single submission line and persist every answer in `project.yaml` (`client:`,
`enrichment:`, `enrichment.ors_api_key`, `inputs.emails:`, `output.language` -
`reference/config.md`; `clarify.mode` is NOT among them) **AND set `setup.confirmed: true`**
so re-runs are non-interactive. SKIP the widget ONLY when `setup.confirmed` is already true.
**Values being present in `project.yaml` is NOT the test and never was** (B63): intake
SCAFFOLDS that file on the first pass with all five pre-filled - client from `--client`,
English, no emails, car times - so "it already carries the answers" was true on every run
and the form was correctly skipped every time, shipping five guesses the broker never saw.
`setup.confirmed` is the only signal that a human answered. The spine enforces this: while
it is false, every hand-off leads with the form, and a pass with no other hand-off stops at
exit 13 for it.
FALLBACK (only if `visualize` is genuinely unavailable): all five in ONE plain-text message.
Email answers map to the Stage-1 `outlook_email_search` sub-agent via
`prompts/outlook-ingest.md` (`reference/agentic-steps.md`).

## The QA window - the reviewers PROPOSE, you IMPLEMENT; the SPINE drives the rest

**THE SHAPE, ON EVERY RUN WITHOUT EXCEPTION: spawn the independent review agents ONCE ->
implement every blocking finding, plus any advisory that is cheap and material -> deliver.
A SECOND REVIEW ROUND IS NEVER CORRECT.** There is no mechanism for one either: the spine
records exactly one round, and a review file that changes after that round is recorded folds
INTO it as additional findings rather than opening another.

LOOP-DRIVEN - you never order these steps yourself:

1. **Exit 14** - dispatch ONE fresh blind agent per rendered `work/prompts/g-*.md` file,
   concurrently. Each returns FINDINGS, every line labelled `blocking:` or `advisory:` by the
   reviewer; a reviewer that finds nothing writes `FINDINGS: none`. Re-run. **This is the one
   dispatch of the run.**
2. **Exit 15** - the spine ran `qa-round record` itself (Python never classifies a finding)
   and blocking findings are unresolved: **YOU implement each fix** and record it with
   `qa-round resolve --work <work> --id <id> --because "<what you changed>"`. Re-run. This is
   a fix loop INSIDE that one round; it never re-dispatches a reviewer.
3. **Exit 0** - the spine re-delivered (advisories folded into "Known limitations") and
   `final_gate` went green. Done-done; a red final gate is exit 7 with reasons in
   `work/final_gate_report.md`.

**Which advisories to fix is YOUR judgement, and there is deliberately NO threshold for it.**
An advisory that is ONE EDIT and changes what a reader CONCLUDES gets fixed - and then
`qa-round resolve` it, or the Gaps Report asserts a defect the pack no longer has. Everything
else ships DISCLOSED under "Known limitations", which is how an advisory is closed. Never work
the advisory list for its own sake, and never fix one merely to make it go away.

**Prohibitions:** do NOT re-dispatch a reviewer, for any reason - not to confirm a fix, not
because the round read thin, not after implementing the findings (one review pass; the repair
is recorded, not re-judged). Do NOT use `--no-reviews` because a finding felt like friction
(it prints `STATUS: DEGRADED`, never ALL-PASS). A recurring cosmetic finding is a
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
