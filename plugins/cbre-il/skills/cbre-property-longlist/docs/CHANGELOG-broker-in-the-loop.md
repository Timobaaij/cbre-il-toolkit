# Changelog - broker-in-the-loop implementation

Decision log for the work specified in IMPLEMENTATION-PLAN-broker-in-the-loop.md.
One entry per commit; eval evidence named per phase. Dates are 2026-08-23 unless said.

## Phase 0 - safety harness
- git repo initialised in the skill folder; tag `baseline` (bf626a4). `.gitignore`
  excludes `__pycache__/`, `*.pyc` and the (since-removed) `.regression/`.
- Full eval suite on untouched baseline: PASS=110 FAIL=0
  (`docs/eval-runs/baseline_evals.txt` - the eval logs' current home).
- Regression fixture: the live project's 16 inputs were copied into a gitignored
  `.regression/` INSIDE the skill folder (first placed under AppData, where the
  sandboxed shell and python disagreed on the path - overlay redirection). Git history
  stayed clean, BUT THIS WAS STILL WRONG - the skill ships as a folder copy, so the
  client data shipped with it. See "Correction (2026-08-24)" at the end: all client
  data deleted, guard eval added.

## Phase 1 - verified extractor fixes
- commit e432fbe: combined 'Lat Long' header misbind, three layers (aliases,
  both-tokens structural guard, pair-split value guard). Eval
  latlong_combined_test.py. Suite: PASS=111 FAIL=0
  (`docs/eval-runs/phase1_commit1_evals.txt`).
- commit 61d2fd9: open capture in extract_xlsx - read everything, display
  selectively. New first-class homes (address, postcode, buildType,
  description); unbound populated columns become top-level scalars or
  __meta.open_capture (commentary/denied/CJK-only); ordinals + link-text stubs
  are the only named skips; unmapped_headers redefined as NOT READ AT ALL (must
  be empty); run.py yield line names each bucket. extract_test's old assertion
  ("names every unmapped column") updated to the new contract - that check
  failing was the intended behaviour change, verified before editing the eval.
  New eval open_capture_xlsx_test.py.
- commit 0360276: Longlist workbook appends dynamic open columns
  (deterministic: sorted key set, mechanical header prettify; media/derived/
  internal keys denied). Eval longlist_open_columns_test.py.
- DESIGN DECISION (user challenged, resolved): the dynamic columns stay
  deterministic; the LLM keeps its existing seat (the exit-3 tracker map, which
  can bind any column to a canonical field). LLM-named keys would break
  byte-identical rebuilds for cosmetic gain. Optional future item: let the
  tracker-map job also propose semantic names for CJK-only headers,
  input-hash cached.
- Real-tracker verification (fixture, extractor only): 17/31 columns mapped,
  10 open fields, 2 record notes, 2 named skips, 0 unread; combined coordinate
  column splits correctly.
- Process note: deliver.py was edited while the commit-2a suite was still
  running; harmless this time (the one FAIL was the intended extract_test
  contract change) but a rule violation - later phases hold edits until the
  running suite finishes.

## Phase 1 blind review (fresh-context agent, diff vs plan) - 4 blocking, 3 advisory
All four blocking findings verified by the reviewer with reproductions; fixed in one
review-fix commit, each pinned by an extended eval:
1. Longlist duplicate column: merge stamps `warehouseRent` on every property and the
   open-column tail re-shipped it beside "Warehouse rent (annual)". Fixed: deny-listed;
   eval fixture now carries the string.
2. Value guard blind to 1-2-decimal pairs (the strict free-text regex requires 3+): a
   misbound "51.5, -0.12" still truncated. Fixed: coord-BOUND columns get a loose pair
   regex (comma never followed by a digit, so a European decimal comma is not a false
   pair) and every unresolvable coordinate cell is a DISCLOSED refusal
   (header_report.coord_unparsed -> yield -> Gaps), never a silent drop.
3. 'Long Lat' (lng-first) headers shipped swapped coords (a Gulf-of-Guinea pin for a UK
   site): group1 was always lat. Fixed: header token order decides assignment; magnitude
   (|v| > 90 can only be longitude) disambiguates otherwise; unresolvable -> refusal.
4. A populated column with an EMPTY header was invisible to every bucket. Fixed: read to
   __meta.open_capture labelled by column letter; buckets also now require actual data
   (a headed empty column is no longer reported as "read").
Advisories: commentary regex extended to the skill's tracker languages (NL/DE/PL/FR/ES/
PT/IT/CS/SK/HU/DA/SV/FI + CJK); seeded region/country protected from open-key collision;
"__meta.open_capture has no downstream consumer" deferred to plan item 2.6.

## Phase 2 - no silent drops
- commit 9ebe187 (items 2.1/2.2): record-level disclosure for source-authority
  exclusions. apply_source_authority carries each dropped cluster's headline figures and
  links it (pair_class + an IDENTITY requirement - the bare size test fires for any
  unrelated pair, caught by the eval's negative case) to the kept cluster it plausibly
  IS; the Gaps 'Options excluded' section prints the two figures side by side.
  Eval excluded_conflict_disclosure_test.py.
- commit f2ab910 (items 2.3/2.7): 'excluded' input-accounting bucket. A B47 exclusion
  left zero ledger rows so the gate BLOCKED the disclosed decision - the incentive that
  cornered a live orchestrator into hiding the brochure in _originals. Now accounted,
  named, non-blocking. input_accounting_test extended.
- item 2.4: shipped_forbidden_conflicts - both-shipped cross-source forbidden pairs WITH
  identity write one meta.conflicts line with both figures (the LLM never sees a
  forbidden pair; nothing else compares them). Same-file pairs excluded by design (two
  units of one scheme). Eval cases in excluded_conflict_disclosure_test.py.
- item 2.6: __meta.open_capture now survives merge (canonical.meta.openCapture, by
  property id) and prints in the per-property notes.md as "Read but not shown on the
  card". Eval open_capture_view_test.py.
- item 2.5: the value-format gate's remedy is MECHANISED. The gate emits machine-readable
  findings (--emit-json) and honours broker waivers (--waivers); clarify gains the
  blocking value_format kind; run.py's bridge (value_format_clarify) turns an answer
  into an attributed work/repairs.json entry, a decline ('leave as is'/skip/SKIP_ALL)
  into a waiver the gate notes, and anything undecided into a blocking exit-13 question.
  SKILL.md's exit-6 row updated: the one documented prose ask is gone.
  Eval value_format_clarify_test.py (gate -> question -> repair -> waiver, end to end).
- Caught by the suite (12 FAILs, one root cause each): the shipped-forbidden-conflicts
  hook was placed before all_conflicts is initialised in merge main (UnboundLocalError,
  9 evals cascaded) - moved to the init site; and value_format_test pinned the old
  "ASK THE BROKER" SKILL.md prose - re-pinned to the new mechanised contract ("the gate
  asks the broker ITSELF via exit 13" + the unchanged no-guessing ban).

## Phase 2 regression (tracker-only end-to-end spine on the fixture, dictionary path)
- Ran run.py --project on a tracker-only fixture, LLM map declined via .SKIP: spine
  reached exit 0; 17 properties; every coordinate valid (the combined Lat Long column
  splits correctly on all rows - no 52-degrees-E pins); buildType/crossDock/postcode
  17/17; meta.openCapture on all 17 (the sample is literally the BTS-that-never-occupied
  Comments cell: readable, not client-shown); Longlist ships 57 columns incl. the open
  tail; the Gaps Report prints the bucketed yield line; all mechanical gates ALL-PASS.
- PRE-EXISTING blocker found and fixed: a formula-computed rent cell hands openpyxl
  float noise (102.257192986233), validate-data demands warehouseRentVal match its own
  rounded display, and the dictionary path BLOCKED on every formula-valued tracker (the
  LLM map masked it on live runs). Fix: the annual rent rounds to 2 decimals at
  extraction, exactly like the monthly x12 path always has. Eval
  formula_rent_rounding_test.py. Nothing in the phase diff touches rent parsing, so
  this was latent at baseline.
- OBSERVED INTERACTION (logged, not fixed): exit-12 translation eligibility sweeps in
  open-captured short enums ("Yes", "Immediate") and even the address - over-broad
  before open capture too (brochureLink display text), wider now. Tuning item for
  workstream 3: is_translatable_value should skip yes/no-class enums, addresses and
  identifier-like open fields.

## Phase 2 blind review (fresh-context agent, diff vs plan) - 3 blocking, 6 advisory
All fixed in one review-fix commit (the plan-doc divergence included), each pinned by an
extended eval:
1. The bridge could destroy the broker's hand-file: a malformed repairs.json was
   silently replaced, a dict-shaped one crashed the run. Fixed: never write unless the
   existing file parses as a list; loud handoff note otherwise; the answer stays in
   clarify state.
2. Any non-decline answer was concatenated into a client-facing value ("5000 Leave as
   is." shipped and the gate then passed). Fixed: declines normalised like is_decline;
   answers must be an option (normalised) or unit-shaped (letter-led, digit-free, <=12
   chars); anything else is re-asked with the rejection spelled out.
3. Open tracker columns deadlocked the gate (repairs reject non-canonical keys, so a
   broker answer could never apply -> unresolvable exit-6 loop). Fixed: non-canonical
   fields are ADVISORY notes, never blocks - the value ships as printed.
Advisories, all fixed: headline figure + unit now come from the SAME record;
_likely_same_kept never links same-file pairs; exclusion enrichment is per-entry
best-effort (an error can never cancel the exclusion disclosure); waivers carry
expect_value and a stale one is refused (ids renumber between passes); the
label-pair dedupe that collapsed distinct multi-unit conflicts is gone; plan item 2.1
rewritten to the as-built design (meta.excluded enrichment, not dropped_records.json).

## Phase 3 - Sonnet-drivability (workstream 1)
- item 1.5 FIRST (test before the refactor it protects): conformance_sim_test.py - drives
  the REAL run.py through the FULL lifecycle as an orchestrator that knows only the slim
  card's exit table; every action comes from a printed handoff or a file a handoff names.
  Passed against the pre-driver skill on first run (2 rounds + handoff-embedded QA
  commands), proving the current handoff surface already met the no-recall bar.
- item 1.2: the QA WINDOW IS LOOP-DRIVEN. run.py's exit-0 tail replaced: exit 14 =
  reviews missing (dispatch work/prompts/g-*.md, with pending diagnosis per missing
  file); exit 15 = blocking findings unresolved (qa-round resolve, ids in the
  diagnosis); then the spine itself re-runs deliver (folding advisories) and final_gate
  (via run_gate -> work/final_gate_report.md, so quiet mode cannot swallow the reasons;
  a red final gate is exit 7 naming that file). Exit 0 now means DONE-DONE. `qa-round
  record` runs once (guarded by qa_round_number==0 - record self-opens a new round when
  the last is recorded, so re-running it every pass would inflate rounds). SKILL.md's
  exit table gained rows 14/15, row 0 rewritten, "The QA window" section rewritten to
  the loop. cowork_sim's Responder gained exit_14 (FINDINGS: none per rendered prompt);
  conformance_sim updated and got SIMPLER (no command parsing left - the point of the
  change): lifecycle is now 3 -> 14 -> 0.
- Process slip (again): the post-3.1 suite was launched before the 1.2 edits began and
  became tainted mid-run; its green result was discarded and the suite re-run after the
  edits settled.
- item 1.4a: the intake cluster refinement rides exit 3 as an OPTIONAL rendered job
  (prompts/cluster-labels.md, input_hash baked verbatim; absence keeps the deterministic
  regex, so it never blocks). 1.4b needed no code - the exit-8 handoff already carries the
  full tier ladder inline.
- item 1.3 (calibrated): eight self-contained templates demote their reference to an ANNEX
  (consult when unsure, section hints preserved); readers, G-* reviewers and outlook-ingest
  KEEP the mandatory read - their spec IS the reference and under-capture is the most
  expensive failure class.
- item 1.1, the SKILL.md DIET: 94.4 KB (~24k tokens) -> 20.7 KB (~5.3k tokens). The card
  keeps: the loop + full exit table (0-15), forbidden moves as one-liners (pinned phrases
  intact), the three-folder layout, overrides/repairs compacts, quiet discipline, the
  deliverables, an 11-line pipeline summary naming every gate, the setup-form contract, the
  loop-driven QA window, a reference index and user preferences. Moved VERBATIM:
  environment/install/Cowork-explainer -> reference/environment.md; the full agentic-steps
  detail (emails, web-enrichment tiers, region research, translation, judgement gates) ->
  reference/agentic-steps.md; maintenance -> docs/MAINTENANCE.md. Frontmatter untouched.
  Verified: conformance sim green against the slim card (3 -> 14 -> 0), full suite 118 PASS
  with every eval pin intact on the first run. (Correction, post-review: environment and
  maintenance moved verbatim; agentic-steps is a faithful CONDENSATION - the Phase 3 blind
  review compared line-by-line and found no rule lost.)

## Phase 3 blind review (fresh-context agent, diff vs plan) - 3 blocking, 5 advisory
All fixed, each pinned or synced:
1. `qa-round record`'s finding regex required a `- ` bullet while final_gate accepts the
   dashless form: a dashless `blocking:` line was counted "proposed" but never ingested -
   an unaddressed blocking finding shipped through ALL-PASS (reproduced end-to-end by the
   reviewer). Fixed: bulleted labels keep the optional colon (brackets stay valid); a
   DASHLESS label requires the colon so prose starting with "blocking" is never a finding.
2. The record guard was round-count-only, making every post-record review unrecordable
   (garbled round-1 -> re-dispatch -> round-2 file never read -> exit 0 over an unread
   blocking finding). Fixed: a fingerprint of the review files (relpath+size+mtime,
   work/qa_reviews_fp.json, stamped only after a successful record) re-fires record on any
   new or changed review. Both pinned by qa_review_ingest_test.py.
3. The overrides contract lost three clauses in the diet ("multi":"all", 1-based Excel
   rows, basename case-insensitive) and SKILL.md pointed at a config.md section that did
   not exist. Fixed: the FULL contract restored into reference/config.md ("Correcting a
   datum"); SKILL.md pointer corrected.
Advisories, all fixed: gates.md + pipeline.md synced to the loop-driven QA window (they
still described the prose-ordered flow and the removed exit-0 command handoff);
agentic-steps.md's stale verdict-word sentence replaced with the findings-file contract;
the lost "never a literal work/ folder at the project root" caveat restored to SKILL.md;
the pre-warm knobs documented in reference/environment.md; the cluster-labels STEMS cap
now names the remainder instead of truncating silently; the changelog's "verbatim" claim
corrected (above).

## Phase 4 - broker-in-the-loop (workstream 3; INTERACTIVE IS THE STANDARD, user-set)
- 3.1 `clarify.mode`: interactive is the DEFAULT (clarify_mode(); headless via
  clarify.mode: headless / assume_defaults / SKIP_ALL - headless behaviour unchanged).
  Scaffolded into project.yaml; a SIXTH Stage-0 form question ("Ask me when unsure" /
  "Decide sensibly") sets it; setup-form.md + SKILL.md updated (five -> six; the sample
  submission line's client name genericised in passing).
- 3.3 'unsure' is a FIRST-CLASS adjudicator verdict for grey pairs AND value-conflict
  picks: interactive -> a BLOCKING exit-13 broker question (both records/candidates
  named); the answer is written back into match_decisions.json / field_decisions.json
  as an attributed verdict before clustering; headless/declined -> today's safe default
  ('different' / keep precedence), attributed and disclosed. Contracts updated
  (match-adjudicate.md + the manifest instructions; the blind verify stays binary).
- 3.4 photo confirmations at DECISION time: uncertain pairings become non-blocking
  broker questions in the same batched first round; a 'yes' moves the entry to
  confident BEFORE doubts are rebuilt (the photo lands this pass); the end-of-run
  prompt remains the fallback.
- 3.2 structured doubts: readers may record `__meta.doubts` ({subject, question,
  options?, default?, why_it_matters?}) instead of silently picking; interactive runs
  batch them (cap 12/round, shipped-field impact first) into the same first exit-13
  round; answers are DISCLOSED via the Clarifications section, never silently applied.
  Reader templates + record_schema.json updated.
- 3.5 excluded-figure questions: an excluded record conflicting with the shipped card
  it plausibly IS becomes ONE non-blocking question post-merge ("keep X / use Y");
  picking the excluded figure writes an attributed repairs.json entry (same-unit only -
  a cross-unit repair offer would be the 10.76x class); unanswered ships the Phase-2
  disclosure unchanged. kept_index carried on likely_same_as (the kept cluster's
  position IS its property id minus 1).
- 3.6 quiet carve-out: a batched exit-13 round is sanctioned output (SKILL.md).
- 3.7 translation eligibility, AS-BUILT (narrower than planned): address/postcode/
  brochureLink joined IDENTIFIER_FIELDS. A shape rule excluding single ASCII words was
  tried and REJECTED by the suite - translate_shape_test pins single-word FOREIGN
  statuses ("Ja", "Si") as must-translate, and a foreign word on the card is worse than
  a redundant (cached, returns-unchanged) round for an English "Yes".
- All pinned by evals/interactive_mode_test.py (mode resolution, unsure both kinds
  end-to-end incl. broker answers, photo yes/no application, doubt capping/ordering,
  excluded-figure question -> repair, eligibility).

## Phase 4 blind review (fresh-context agent, convergence-focused) - 4 blocking, 7 advisory
The blockings were all answer-handling holes in the new question kinds - the exact
ask-loop class the reviewer was briefed to hunt, every one probe-verified. All fixed:
1. match_unsure: an unrecognised answer ("yes they are the same") was swallowed - never
   re-asked, no verdict written, probe-verified adjudicator livelock. Now RE-ASKED with
   the rejection spelled out (the Phase-2 value-format standard).
2. field_unsure: a paraphrase answer ("15 m" instead of "b: 15 m") silently discarded the
   broker's explicit choice. Now: bare-label and bare-value answers are ACCEPTED
   (unambiguous); anything else re-asks.
3. excluded_figure: any unrecognised answer silently read as KEEP. Now re-asks; lenient
   keep/use prefixes accepted.
4. excluded_figure: a malformed hand-edited repairs.json silently dropped a 'use' repair.
   Now refuses LOUDLY without consuming the answer (the hand-file is never overwritten).
Advisories fixed: photo answers bound to (brochure, PROPERTY) - one 'yes' endorsed the
brochure for every candidate and auto-applied to later re-pairings; a settled pair
(possibly the broker's own earlier answer) is never re-opened by a later 'unsure';
agent-doubt qids deduped before the cap; config.md documents clarify.mode + six
questions; matching.md/interpretation.md/agentic-steps.md synced to first-class unsure +
__meta.doubts; wiring pins added to interactive_mode_test (a main() revert now fails the
eval) + junk-answer/settled/hand-file cases; cowork_sim gained an exit_13 responder
(SKIP_ALL, with a re-ask-after-decline livelock check).
ACCEPTED (documented, not changed): merge emits kept_index on likely_same_as
unconditionally, so a headless canonical.json gains one meta key vs phase-3 output when
an excluded cluster links to a kept one - behaviour, gates, and every deliverable are
unchanged (deliver reads named keys); plan item 3.1's "byte-identical" is amended to
"behaviour-identical (canonical meta may gain keys)".

## Correction (2026-08-24): client data was INSIDE the skill folder - removed
The Phase-0 regression fixture (the live project's 16 inputs, ~100 MB) and a tracker-only
test-run project sat under a gitignored `.regression/` INSIDE the skill folder. Git history
was verified clean (no client file ever committed), but the reasoning was wrong anyway:
teammates install the skill by COPYING THE FOLDER, so gitignore protects nothing they
receive, and the skill had silently grown to 156 MB carrying a client's brochures. All
client data deleted from the tree (the originals live in the user's own project folder);
the eval-evidence logs (pure PASS lists, verified free of client strings) moved to
docs/eval-runs/. Guard added: evals/no_client_data_test.py fails on any property-input
file type or project folder anywhere in the tree, so this class cannot recur silently.
Rule recorded in docs/MAINTENANCE.md; ship copies exclude .git (git archive).

## B62 (2026-08-26): MATERIALITY - the run only stops for what the client will see
Broker feedback after living with interactive mode: it asked too often, and stopping the
run is the expensive part. The rule they set is narrow and testable - ask ONLY when the
answer would change (a) a value, photo or label RENDERED on the dashboard, or (b) HOW MANY
options ship. A doubt that moves nothing but a provenance note, a Source Ledger cell or an
Excel-only column is not worth an interruption.

- `clarify.DISPLAY_FIELDS` - the 52 canonical fields the template actually renders, derived
  from `p.<field>` in assets/dashboard_template.html intersected with the canonical schema.
  Held as a literal (clarify stays pure) and drift-pinned by the new eval, which re-derives
  it from the template and fails on any mismatch. NOT displayed: postcode, district,
  warehouseAreaSqm, expansionParkVal and every open-captured tracker column.
- `clarify.materiality(q)` -> "count" | "display" | "ledger", with `KIND_MATERIALITY`
  per kind and a per-question `materiality` stamp overriding it. An unknown kind, or one
  that cannot be classified, is MATERIAL: the failure direction is asking too much.
- NEVER suppressed: area_unit, rent_unit, dataset_unit, source_authority, value_format,
  match_unsure. For those the default is itself the damage. value_format additionally
  BLOCKS the build, so suppressing one would wedge the run with no way out.
- `clarify.pending()` is the chokepoint (every producer already passed through it): a
  ledger-only question never leaves it, and `note_suppressed` records id/kind/subject/
  question/default in `clarify_state.suppressed`.
- ONE producer-side exception, and the reason is a livelock: an immaterial `field_unsure`
  is RESOLVED to the precedence default inside `run.unsure_pick_questions`. Merely
  filtering it would leave field_decisions.json holding 'unsure', so field_uncovered would
  stay True and exit 10 would re-dispatch the adjudicator for ever. Suppression must always
  leave a settled value behind it.
- Reader doubts (`__meta.doubts`) gain an optional `field`/`fields`/`materiality`
  declaration, which beats the free-text classifier; the per-round cap now applies to the
  MATERIAL ones only, so a cosmetic doubt no longer consumes a broker slot.
- DISCLOSURE, which is what makes suppression honest: deliver.py prints "Noted, not put to
  you (no effect on what the dashboard shows)" in the Gaps Report, naming each unasked
  question and the value that shipped instead. This also fixes a pre-existing hole -
  record_schema.json has always promised that a HEADLESS run ships reader doubts in the
  Gaps Report, and nothing implemented it; run.py now records them in headless too.
- Eval: `evals/clarify_materiality_test.py` (47 checks: template drift, the never-suppress
  set, declaration-beats-text, the pending chokepoint + resume-safety, the exit-10 livelock
  case, and the Gaps disclosure). interactive_mode_test's doubt block updated to the new
  contract (material-first, cap on the material ones) - the behaviour change was verified
  before the eval was edited.
- Docs: evidence-standard rule 4 (the doctrine), SKILL.md exit-13 row + setup-form Q6,
  config.md, failure-modes.md, interpretation.md, both reader prompts, record_schema.json.

### B62 blind review (2 fresh-context Opus reviewers, correctness + data-honesty)
Both reviewed the same uncommitted diff blind, and independently found the same two worst
defects. 5 blocking, 9 advisory; every one below was fixed, and each fix landed with its eval.

BLOCKING
1. A declared `field` that was not an EXACT canonical key demoted the doubt to ledger and
   never read the text - so the very declaration the new reader prompts ask for ("area",
   "warehouse_area", "gla") HID a doubt about the figure on the card. `known_field()` now
   separates "a real field" from "not a field name": an unrecognised name means UNDECLARED
   and the wording is read instead. Pinned over 10 near-miss names.
2. Headless runs recorded MATERIAL doubts and deliver printed them under "no effect on what
   the dashboard shows" - the opposite of what the run concluded, in a client-facing
   document. `note_suppressed` now records WHY it was not asked (ledger / over the cap /
   headless) and the Gaps Report splits into two headings: "Noticed but not asked about
   (worth a look)" for anything that could have moved the dashboard, and "Noted, not put to
   you" only for what could not.
3. Material doubts past the per-round cap were returned to nobody: not asked, not recorded,
   and nothing else in the tree reads `__meta.doubts`. On 20 properties with one area doubt
   each, 8 vanished while the cosmetic ones were disclosed. The cap is now on ASKING: the
   overflow is flagged `over_cap`, disclosed, and asked+disclosed == total is pinned. Past
   MAX_DOUBT_CARRIED the COUNT itself is disclosed rather than the run going quiet.
4. The text classifier demoted ~28 realistic doubts a reader would actually write (currency
   vs header, "may be in thousands", the aerial showing the wrong plot, "tenant named but
   sheet says vacant", every paraphrase of "one property or two", and the reader prompt's
   OWN worked example "an ambiguous page binding"). The lexicons are much broader, they are
   read over question + `why_it_matters` + `options` (not `subject` - it is a park name and
   would promote everything), and an explicit cosmetic/hygiene signal now demotes a doubt
   that a stray building word would otherwise promote. 20 must-ask cases pinned.
5. `prompts/match-adjudicate.md` and `reference/matching.md` still told the adjudicator its
   `unsure` pick reaches a human. On a non-material field it no longer does. Both updated.

ADVISORY (all fixed)
6. `pending()` could drop a BLOCKING ledger question with no decision written - unreachable
   today, but the invariant was asserted in three docstrings and enforced nowhere. A
   blocking question is now never suppressed, whatever its materiality.
7. Matcher-identity fields (postcode, park, address, scheme, region, district...) are NOT
   rendered but DO decide whether two records are one card, so settling one silently can
   move the option count. `field_is_material` = displayed OR match-sensitive, read from
   `match.py` so the two cannot drift.
8. The Gaps line named the candidate LABEL ('a'), which the report gives a broker no way to
   decode. It now names the value, the two values in conflict, and the option.
9. `clarify_state.json` was a merge input but not a DELIVER input, and `__meta.doubts` never
   reaches canonical.json - so a re-extraction changing only doubts could resume-skip the
   one file that discloses them. Added to `_deliver_inputs`.
10. `_gaps_to_chase` ignored both clarify sections, so a clean run whose only real content
    was a suppressed doubt printed a bare "DONE." and never pointed at the report.
11. Suppressions were append-only, and a `field_unsure` id re-keys when clustering settles
    (a live run saw 44 -> 78 conflicts across two rounds), so the report could name a
    conflict that no longer existed. `note_suppressed(..., replace_kind=)` replaces that
    kind's entries each pass; an entry since answered is printed in Clarifications only.
12. An empty `suppressed` key is no longer persisted: `load_state` setdefaults it and
    `ingest_answers` saves every pass, which would have rewritten every pre-existing work
    dir's state once and re-fired merge -> build -> deliver for a key holding nothing.
13. Broker-facing wording: doubled subject ("**P0**: P0: ..."), "What shipped instead:
    proceeds with:" stutter, sentences running together, no source file, and no "how to
    change it" line - every other Gaps section carries one. Fixed; both sections now name
    `work/answers.json` / `work/overrides.json`.
14. `split_material` was dead wiring (defined, never called) - removed.
15. Eval gaps closed: the vacuous `"cf_ledger" not in json.dumps({})` check (it would have
    passed even if the material conflict HAD been silently resolved), the source-grep stand
    -ins, the entirely unexercised headless branch, the overflow accounting, the
    declared-unknown-field demotion, and 20 must-ask text cases. The drift guard now also
    asserts the template has no destructuring or literal bracket read of a property field,
    scanned over the app script only - without that it was blind to a future `p['postcode']`.
    47 checks -> 119.

NOT CHANGED, deliberately: `value_format` stays material by kind with no field test. It
BLOCKS the build at exit 6 and only a broker answer or an explicit decline clears it, so
suppressing one would wedge the run; its own gate already demotes non-canonical open columns
to advisory before any question is produced. Both reviewers independently confirmed this is
the right call and that no other blocking gate has a question as its only remedy.

## B63 (2026-08-26): the Stage-0 form was never asked, and the cause was an instruction
Reported live: a run on a colleague's up-to-date install asked nothing at the opening. It was
not the model and not a version drift. Two defects, both reproduced on a clean probe run.

1. THE SCAFFOLD LOOKED LIKE CONSENT. `intake.scaffold_yaml` writes a COMPLETE project.yaml on
   the first pass: client name from `--client`, `output.language: English`,
   `inputs.emails.source: none`, the enrichment flags, `clarify.mode: interactive`. That is
   all six Stage-0 answers, pre-filled with guesses, written BEFORE anything tells the
   orchestrator to ask. SKILL.md said to "SKIP the widget only when project.yaml already
   carries the answers" - which was true on every run from the first pass onward. Skipping the
   form was therefore the COMPLIANT reading, and runs shipped English dashboards with no email
   ingestion and car drive-times to brokers who were never offered the choice.
   Fix: `setup.confirmed` (intake writes false; only the orchestrator sets true) is now the
   test, and `run.setup_pending` reads it. Presence of values proves nothing and the scaffold
   header, SKILL.md, reference/setup-form.md and reference/config.md all say so.
2. THE INSTRUCTION EXISTED IN ONE PLACE, AND IT WAS A TRAILING QUESTION. The only site that
   mentioned the form was the exit-3 interpretation hand-off, ~85% of the way through a
   1,400-character paragraph, as "FIRST PASS? Present the Stage-0 setup form... - no form
   answer feeds this round", which reads as optional. A corpus with no decks and no tracker to
   map (email-only, image-only, or a work dir whose interpretation is cached or .SKIP-declined)
   never printed it AT ALL.
   Fix: `run.setup_prefix` LEADS every exit-3 hand-off with an imperative while the form is
   unanswered (still the same message, so no round-trip is added), and a pass with no other
   hand-off stops on its own at exit 13 with a blocking `setup_form` question in
   work/questions.json. The broker-facing quiet line now says "A few setup questions first".
   Ordering: the stop sits AFTER the no-usable-inputs exit, so an empty folder is reported as
   such rather than after six questions.

Also fixed here, found while tracing it: `clarify.skip_all` read project.yaml from
`work.parent`, but run.py resolves it as `work / "project.yaml"` (intake writes it there). So
`clarify.assume_defaults: true` in the real file was DEAD WIRING and the SKIP_ALL sentinel was
the only working headless escape, while reference/failure-modes.md documented both. It now
reads the work dir first and the parent second.

Clearing the gate, and nothing else does: `setup.confirmed: true` in project.yaml, an explicit
decline ("skip"), or work/clarify.SKIP_ALL / clarify.assume_defaults for a headless run - each
a recorded decision. An ordinary answers.json entry deliberately does NOT clear it (the six
answers have to land in project.yaml, where every later stage reads them) and the hand-off
says so when it sees one.

Eval: `evals/setup_gate_test.py` (37 checks: the scaffold is not consent, every escape,
the prefix wording and its absence once confirmed, the exit-3 site count as a tripwire for a
future site added without the prefix, the stop's ordering against the no-inputs exit, the
question's kind/blocking/materiality, the answers.json-does-not-clear-it rule, and the three
docs). conformance_sim_test and cowork_sim both still pass unchanged, which is the real
proof: a scripted orchestrator that knows nothing but the exit table clears the new stop with
the exit-13 rule it already had.
