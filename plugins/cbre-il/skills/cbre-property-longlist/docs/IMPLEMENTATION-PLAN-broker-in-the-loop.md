# Implementation plan: make the skill Sonnet-smooth (primary), then broker-in-the-loop

Status: AGREED, not yet implemented. Written 2026-08-23, re-prioritised the same day: the
PRIMARY goal is that Sonnet 5 can drive a full run smoothly, with low effort and low error
rate. Broker-in-the-loop asking and drop disclosure are secondary workstreams. Do NOT start
while any run is in flight (helper edits trip the integrity manifest and halt it).
Implementer: follow the Maintenance rules in SKILL.md - after edits,
`python helpers/make_integrity.py`, then the FULL eval suite `python evals/run_all.py`.

## Goal (one sentence)

A Sonnet orchestrator should never need to remember, retrieve or improvise anything: every
turn's complete instruction is the printed handoff plus one rendered prompt file, so the run
is a mechanical loop from first command to delivery.

## Definition of done (the smoothness bar)

At every turn, the required context is exactly: a ~4k-token orchestrator card + the exit's
printed handoff + the rendered `work/prompts/*.md` file(s). No turn requires recalling a rule
from elsewhere, no phase is ordered by prose, no step depends on the model noticing something
code could have flagged. Verified by a cowork_sim variant that drives the whole pipeline while
reading ONLY those three things.

## Workstream 1 - Sonnet-drivability (PRIMARY - do first)

1.1 **SKILL.md diet: ~24k tokens -> a ~4k orchestrator card.** Keep: the loop, the exit table
    at ONE line per exit ("do what the printed handoff and work/prompts say"), the forbidden
    moves as bare one-line imperatives, the quiet-output rules, the three-folder layout.
    Move out: maintainer material -> docs/MAINTENANCE.md; environment nuance (Cowork vs MCP
    shell, wheel vendoring, offline design) -> reference/environment.md; war stories and
    rationale -> reference/failure-modes.md; sub-agent contract detail -> stays in
    reference/* and the prompt templates only. Principle: a rule that matters at a turn is
    PRINTED at that turn, never memorised from page 12.

1.2 **Loop-drive the QA window.** The exit-0 phase is today the only multi-step phase ordered
    by prose (dispatch reviewers, qa-round record, implement, resolve, deliver, final_gate).
    Give it the same exit-code pattern as everything else (a `--qa` driver or new exits):
    "reviews missing -> dispatch work/prompts/g-*.md", "blocking findings unresolved: <ids>",
    then deliver + final_gate run inside the driver. After this, exit 0 means done-done and
    the whole skill is one loop.

1.3 **Self-contained rendered prompts.** AS BUILT - CALIBRATED, not blanket: the eight
    templates that already carry a complete operating contract (match-adjudicate,
    match-verify, field-conflicts, tracker-map, tracker-verify, region-labels,
    translate-chrome, translate-data) demote their reference to an ANNEX consulted only
    when a case leaves the agent unsure (section hints preserved). The reader templates,
    the four G-* reviewers and outlook-ingest KEEP their mandatory reference read: their
    spec IS the reference (field rules / rubrics / attachment routing), and under-capture
    is this skill's most expensive failure class - dropping that read to save tokens would
    be the pasted-short-field-list mistake at one remove. prompt_render_test pins the
    load-bearing clauses either way.

1.4 **Remove the last inline judgement/probe tasks from the orchestrator.**
    (a) The intake-cluster refinement (read inventory.json, judge low-confidence labels,
    write intake_clusters.json) becomes a rendered prompt job on the exit-3 manifest like
    every other dispatch. (b) run.py detects and prints which web-enrichment tier is
    available instead of asking the model to probe four options.

1.5 **Conformance eval.** Extend cowork_sim: a scripted orchestrator that reads ONLY the
    orchestrator card + printed handoffs + work/prompts must reach delivery on the fixture
    project. This is the regression test for the smoothness bar and blocks any future edit
    that reintroduces a prose-only obligation.

## Workstream 2 - no silent drops (the MPS8 class; also REDUCES model burden)

Rationale for second place: every item moves a thing the model currently must NOTICE into a
thing code DISCLOSES, so it directly cuts orchestrator vigilance load.

SCOPE CORRECTION (2026-08-23, verified in deliver.py): the skill ALREADY discloses
source-authority exclusions at the OPTION level (`meta.excluded` -> the B47 "Options
excluded" Gaps section) and already folds yield_report.md's unmapped-column lines into the
Gaps Report. The MPS8 hole is NARROWER: MPS8 the option SURVIVED (it is one of the 17), so
the option-level disclosure never fired; what vanished was a RECORD for a surviving option,
dropped pre-merge with no field comparison. 2.1/2.2 therefore target record-level drops for
SURVIVING options - do not rebuild what B47 already does.

2.1 **Record-level exclusion disclosure.** AS BUILT (differs from the first draft's
    separate dropped_records.json file, which the B47 discovery made redundant): the
    source-authority filter is the only pre-merge record drop, and its existing
    meta.excluded entries are ENRICHED in apply_source_authority itself - headline
    figures from the dropped cluster (figure + unit from the SAME record) plus a
    likely_same_as linkage to the kept cluster the drop plausibly IS (pair_class
    forbidden-with-identity or grey; same-file pairs never link). Enrichment is
    per-entry best-effort so a linkage error can never cancel the exclusion itself.
2.2 **Gaps Report "Excluded records" section** (deliver.py): one line per dropped record,
    its headline figure vs the shipped card's where a counterpart exists ("MPS8 brochure
    dropped by your longlist decision; it states 230,000 sq ft, the shipped card shows
    356,202").
2.3 **Stricter input-accounting rule (existing gate, no new gate):** zero Source Ledger rows
    AND no dropped_records entry AND not underscore-filed -> BLOCK (exit 6).
2.4 **Forbidden pairs become disclosed conflicts:** when either side ships, write a
    meta.conflicts entry (pairs already computed; conflicts channel already exists). Merge
    behaviour unchanged.
2.5 **Value-format gate asks through clarify.py** instead of SKILL.md prose telling the
    orchestrator to ask - converts the one documented prose ask into a mechanised question
    Sonnet cannot skip. (Belongs here, not in workstream 3: it is a prose-to-code move.)
2.6 **Carry `__meta.open_capture` downstream** (Phase-1 blind-review advisory): merge pops
    `__meta`, so commentary/denied/CJK captures survive only in work/extract records today.
    Fold them into the per-property view's notes.md (and consider ledger rows flagged
    non-shipped) so "read and available to reviewers" is true end to end.
2.7 **`excluded` accounting bucket** (found during design): a legitimate B47 exclusion
    leaves zero ledger rows, so input-accounting BLOCKS it - which is what cornered a live
    orchestrator into filing the brochure into `_originals`, hiding it from inventory
    entirely. A source named in meta.excluded[].source_files becomes an accounted,
    named, non-blocking bucket. This removes the incentive for the silent workaround.

## Workstream 3 - broker-in-the-loop interactive mode (LAST; adds round-trips by design)

3.1 **`clarify.mode: interactive | headless`**, set by a sixth Stage-0 form question.
    Scaffold default interactive; SKIP_ALL / assume_defaults forces headless. Headless stays
    byte-identical to today.
3.2 **Structured doubts channel:** sub-agent outputs gain an optional `__doubts` list;
    run.py harvests each round's doubts into the existing exit-13 batch (asked_of: broker).
    Cap 12 per round, prioritised by shipped-field impact; overflow -> Gaps as today.
3.3 **`unsure` verdicts** for match_decisions/field_decisions in interactive mode -> exit-13
    questions carrying both records; the answer is the cached verdict. Headless: today's
    defaults + a Gaps note.
3.4 **Photo confirmations move to exit 9** (clarify questions at decision time; run.py
    applies the answer to photo_map.json), replacing the end-of-run print.
3.5 **Forbidden pair over a shipped card -> a question** ("tracker says X, brochure says Y -
    what should the card show?"); the answer is applied as an attributed repair; the 2.4
    conflict note stays either way.
3.6 **Quiet-output carve-out:** a batched question round is sanctioned output.
3.7 **Translation-eligibility tuning** (found by the Phase 2 regression):
    `_common.is_translatable_value` sweeps in open-captured short enums ("Yes",
    "Immediate") and even the address, bloating the exit-12 round. Skip yes/no-class
    enums, addresses/postcodes, and identifier-like open fields. Over-broad before open
    capture too (brochureLink display text), wider now.

## Known extractor bug (fix independently, can ship with workstream 2)

**extract_xlsx.py: a combined "Lat Long" header binds to `lng` alone (observed 2026-08-23,
live UK fixture run; header and cells confirmed against the source tracker).** The tracker's column AB is
headed exactly `Lat Long` with pair cells like `52.480401, -0.652005`. The original incident
note said "no lat long alias exists"; that is NOT the gap - COLUMN_MAP's `latlng` field
already carries "latitude, longitude", "lat, long", "lat/long", "coordinates", "lat lng",
"latlong". The real mechanism, traced in `_header_candidates`: scoring is TIER-FIRST
(3 exact, 2 whole-word, 1 fuzzy) with coverage only as a tie-break. "lat long" (space, no
comma) matches no `latlng` alias exactly or whole-word, so `latlng`'s best candidate is
FUZZY (tier 1) - while the bare alias "long" whole-word-matches for `lng` at tier 2 and the
bare "lat" for `lat` at tier 2. Tier 2 beats tier 1 regardless of coverage, and `lng`
(coverage 4/8) beats `lat` (3/8), so the whole column binds to `lng` alone. The pair cell is
then consumed as a single number, taking its FIRST float - the latitude - as the longitude:
every pin lands at ~52 degrees E and the true longitude is dropped silently. The LLM
tracker-mapping agent bound the column correctly and masked this on the run; the
deterministic dictionary path (the offline/no-LLM fallback AND the backfill for columns the
LLM map leaves null) still carries the bug.

Fix, three layers:
1. Aliases: add the space/ampersand forms ("lat long", "lat & long", "long lat",
   "lat lon", "gps") to `latlng`.
2. Structural guard: a header that whole-word-matches BOTH a `lat` and a `lng`/`long` token
   classifies as `latlng`, never as either single field (kills the whole class, not just
   this header).
3. Value guard: a cell routed to the single `lat` or `lng` field whose text matches the
   coordinate-PAIR pattern is split (or refused with a yield-report line), never truncated
   to its first number - this is the layer that made the failure silent.
Eval fixture: header `Lat Long` + cell `52.480401, -0.652005` must yield lat=52.480401,
lng=-0.652005 through the DICTIONARY path (no LLM map), since that is the path that was
wrong.

## Known capture gap: the tracker schema is CLOSED (verified 2026-08-23, the live UK fixture tracker)

The xlsx path can only emit `_CANON_FIELDS` = COLUMN_MAP's 34 keys + lat/lng - for BOTH the
dictionary and the LLM tracker-map (`extract_xlsx.py` ~line 302). Measured on the fixture
tracker: 16 of 31 populated columns map via the dictionary; the LLM map can rescue only
columns bindable to those same 36 fields; the canonical registry downstream has 56 fields
(including `postcode`, unreachable from xlsx); and ~10 columns have no home on any path and
are dropped outright (Address, Postcode, Cross Dock?, 24/7, Total No. Doors, Door Ratio,
Truck Miles to Royal Mail / Evri hubs, Driving Time, Comments, remarks). This contradicts
SKILL.md's own Stage-1 capture rule ("the record schema is OPEN... 'there is no field for X'
is never a reason to omit X"), which today applies only to brochure readers. Disclosure is
yield-report-only (maintainer-facing); the broker-facing Gaps Report never mentions it.

Live consequence (2026-08-23 run): the orchestrator described an option as BTS while the
tracker's unread "Type of build" column plainly said "Second hand" - the contradicting datum
existed in the source but never entered the dataset, so nothing could catch the error.

THE PRINCIPLE (user-set): READ EVERYTHING, DISPLAY SELECTIVELY. Every populated column is
read, ledgered and available to gates/reviewers/the Longlist xlsx; what ships on the CARDS
stays a separate, curated decision. Reading is mandatory; display is editorial.

Fix (belongs with workstream 2 - it is the same "nothing silently dropped" invariant):
1. Open the tracker schema like the brochure schema: a populated column with no canonical fit
   binds (via the LLM map, or a dictionary fallback key derived from the header) to a
   descriptive camelCase key. NEGATIVE vetoes keep applying to canonical fields. Every such
   key is written to canonical.json + the Source Ledger + the Longlist xlsx.
2. Display tier: canonical fields ship on cards as today; novel keys default to the detail
   modal/Longlist xlsx only (NOT the card grid), unless promoted. This is the "not everything
   on the cards" half of the principle.
3. Extend COLUMN_MAP with the common missing homes so they become first-class: address,
   postcode (canonical already), leaseable/lettable area, type of build (new/second-hand/BTS -
   the exact field the mis-description needed), comments/description.
4. Surface any column that STILL could not be read in the broker-facing Gaps Report ("these
   tracker columns were not read: ..."), not only the yield report.
Eval: the fixture tracker's header row - every populated column either maps, binds to a
descriptive key, or appears in the Gaps line; zero silent drops. Plus: buildType="Second hand"
must be present in the record so a BTS mis-claim is contradicted by data.

## Design constraints (non-negotiable)

1. Every ask rides the EXISTING clarify.py channel: batched, ask-once, explicit decline,
   SKIP_ALL. No new ask loops.
2. Every disclosure is written at the site of the decision, in the same function that makes
   it.
3. Rejected alternatives (do not resurrect): excluded records writing full Source Ledger rows;
   relaxing the forbidden-pair merge rule; prose-only "disclose what you exclude" (the MPS8
   incident happened on Opus, with the model asserting a safeguard that did not exist).

## Evals (ship-blocking)

- Workstream 1: the 1.5 conformance sim; prompt_render_test extended for inlined clauses; a
  QA-driver loop test (missing review -> exit; unresolved blocking -> exit naming ids).
- Workstream 2: `drops_accounting_test` (MPS8 fixture: tracker + conflicting brochure, the
  source-authority answer picks the tracker -> MUST yield a drop entry, an Excluded-records
  Gaps line naming both figures, and a meta.conflicts entry; today's behaviour must FAIL);
  `zero_row_input_test`.
- Workstream 3: `clarify_interactive_test` (each new kind -> exactly one batched exit-13
  round; headless byte-identical to today); cowork_sim with a never-answering broker still
  delivers (headless) or reaches a bounded question count (interactive).

## Sequencing

Workstream 1 is the PRIORITY; the implementation ORDER below differs deliberately: the small
verified fixes go first to establish the edit-verify loop cheaply, and the conformance sim is
built BEFORE the SKILL.md restructure it protects. Priority is what we optimise for; order is
what keeps it safe.

## Execution protocol (how to implement without destroying the skill)

### Phase 0 - safety harness (nothing is edited before ALL of these hold)
0.1 Confirm NO run is in flight anywhere (helper edits trip the integrity manifest mid-run).
0.2 `git init` in the skill directory, commit everything as `baseline`, tag it. Not a remote -
    a local rollback point. Every subsequent item is ONE commit.
0.3 Run the FULL eval suite (`python evals/run_all.py`, never --quick) on the untouched
    baseline and SAVE the result. If baseline is not green, stop and report - we must never
    wonder later whether we broke something that was already broken.
0.4 Copy the live project (inputs only) to a scratch regression project. It is the
    real-world fixture: after each phase, run the pipeline on the copy and diff the
    deliverables against the previous phase's. Intentional changes must be explainable
    line-by-line; any unexplained diff is a defect.

### Phase 1 - the two verified extractor fixes (smallest, fully diagnosed, fixture-ready)
The Lat Long misbind (three layers) and the closed-tracker-schema fix ("read everything,
display selectively"). Contained to extract_xlsx.py + evals + a template display-tier check.
These go first because their diagnoses are verified against the real tracker and their evals
are already specified - the cheapest possible rehearsal of the edit-verify loop.

### Phase 2 - workstream 2 (disclosure: dropped_records, Gaps sections, input-accounting
rule, forbidden-pair conflicts, value-format via clarify). One item per commit.

### Phase 3 - workstream 1 (the goal), in THIS internal order:
3.1 FIRST build the conformance sim (item 1.5) against the CURRENT skill - the test exists
    before the refactor it protects.
3.2 QA-window driver (1.2), self-contained prompts (1.3), inline-task removal (1.4) - each
    one commit, each keeping the sim green.
3.3 The SKILL.md diet (1.1) LAST, validated by the sim: if the slimmed card cannot drive the
    sim to delivery, the card is wrong, not the sim.

### Phase 4 - workstream 3 (interactive mode), with the headless byte-identity assertion
(a fixture run in headless mode must produce byte-identical output to baseline) as the first
eval written.

### Standing rules for every phase
- One plan item = one commit; never batch unrelated edits; helper + SKILL.md edits only
  together when genuinely coupled.
- After EVERY commit: `python helpers/make_integrity.py`, then the FULL eval suite. A red
  that cannot be fixed within the item's own scope -> revert the commit and rethink; never
  "fix forward" across items.
- Every behaviour change lands WITH its eval in the same commit (MPS8 fixture, fixture-tracker header
  fixture, zero-row-input, clarify-interactive, headless-identity).
- Author != reviewer, matching the skill's own philosophy: after each phase, a fresh-context
  subagent reviews the phase's full diff against this plan document, blind to the
  implementer's reasoning. Blocking findings are fixed before the next phase starts.
- Template edits (the display tier in Phase 1) follow reference/template-contract.md's
  hand-edit order exactly.
- Keep a dated decision log at docs/CHANGELOG-broker-in-the-loop.md: what changed, why, eval
  evidence. Update THIS plan document when reality diverges from it - the plan must never
  silently rot.
- End of each phase: a regression PROPORTIONATE to the phase's touched stages on the
  fixture copy - extractor-only phases diff the extractor's output on the real tracker;
  phases that change spine behaviour (2 and 3) run the fuller pipeline. Diff explained,
  then tag the commit (`phase-1`, `phase-2`, ...). Each phase is independently shippable;
  stopping after any phase leaves the skill strictly better than baseline.
