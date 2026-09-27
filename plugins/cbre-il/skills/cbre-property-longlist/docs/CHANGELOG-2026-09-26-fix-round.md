# Changelog - 2026-09-26 fix round

One orchestrated run (22 brochure decks and 16 emails; mid-tier readers, strongest-tier
reviewers; exit 0) produced a list of token, speed and integrity fixes. This round implements
all of them, plus two found while planning (3.24, 3.25). Fix IDs match that list. The
dashboard template is unchanged (v47), so there is no VERSION re-pin.

Rules the round kept: generic (any client, country, language, unit system, currency, input
mix); additive keys only; every new path fails safe to the old behaviour with one printed
line; the Data Honesty Standard binds (Python owns arithmetic, every drop is disclosed).

## Tokens

| ID | What changed | Main files | Evals |
|---|---|---|---|
| 1.1 | Each reader gets a condensed contract for its mode, rendered from `reader-contract` blocks in `reference/interpretation.md`. It no longer reads the 69 KB file plus the schema: about 8 k tokens and one tool call saved per text deck | interpretation.md, prompts_render.py, prompts/reader-text.md, prompts/reader-raster.md | reader_contract_render_test, f01_reader_common_split_test |
| 1.2 | Per-deck contact sheets (`render_sheets`, `candidate_sheets`) under a pixel budget; per-page renders stay available | contact_sheet.py, interpret_prep.py (`PREP_SCHEMA` 4) | deck_sheets_test, montage_test |
| 1.3 | The cluster-label job runs only when `inputs.cluster_labels: agent`; stems are rendered into the prompt, so it never opens inventory.json | prompts/cluster-labels.md, intake.py, run.py, config.md | cluster_labels_optin_test |
| 1.4 | G-trace owns POSITIVE claims (populated values, invention); G-honesty owns NEGATIVE claims and disclosure, and is the sole under-capture owner | prompts/g-trace.md, prompts/g-honesty.md, gates.md | qa_reviewer_scope_test |
| 1.5 | A stray top-level `prov` is hoisted at load (logged in `work/vision/structural_fixes.json`). A still-refused output gets `prompts/reader-repair--<name>.md`, a bounded fix to RESUME the reader with. The record shape is one explicit JSON block | vision_validate.py, run.py, prompts/reader-repair.md | prov_hoist_test |
| 1.6 | Email bodies are extracted once into `work/email_bodies.md`, with repeated quoted paragraphs de-duplicated; the master-list agent reads that file, never the .msg/.eml | master_list.py, prompts/master-list.md | email_bodies_test |
| 1.7 | Exits 6 and 15 print the `work/repairs.json` entry shape. SKILL.md's forbidden moves became a table (every rule and pinned phrase kept verbatim) | repairs.py (`contract_hint`), run.py, SKILL.md | repair_contract_hint_test, skill_forbidden_moves_test |
| 1.8 | A sanctioned POINTER dispatch ("Your complete instructions are the verbatim contents of <path>...") beside paste | SKILL.md step 3 and exit rows, gates.md rule 2 | skill_dispatch_form_test, qa_reviewer_scope_test |
| 1.9 | The exit-15 advisory sentence matches SKILL.md: fix one only when it is one edit and changes what a reader concludes | run.py | handoff_commands_test |
| 1.10 | Per-pass noise: compact repairs report, no reprint of an unchanged block (`work/print_digests.json`), recorded-only answers in `work/recorded_only_repairs.md` | repairs.py, run.py | output_noise_test |
| 1.11 | The manifest's `contract_reads` line addresses the readers; the orchestrator need not read the contract to dispatch | run.py, SKILL.md exit 3 | montage_test |
| model tiers | Advisory per-kind sub-agent model tiers, only where the host lets you pick | gates.md, SKILL.md step 3 | qa_reviewer_scope_test, skill_dispatch_form_test |

## Speed

| ID | What changed | Main files | Evals |
|---|---|---|---|
| 2.1 | The master-list candidate build is cached against the corpus and never rebuilt by a pass that puts the stage out of scope (`--from merge` or later); first-page text reads one page | master_list.py, extract_pdf.py, run.py | master_list_speed_test, master_list_runpy_wiring_test |
| 2.2 | The per-property media half is reused while its inputs are unchanged (`--rebuild-media` forces it) and is written in full before the QA reviewers are sent | project_properties.py, run.py | media_view_incremental_test, f20b_media_view_gated_on_block_test |
| 2.3 | value-format asks in one pass: a value composed by an earlier answer casts no vote | gate_runner.py | value_format_single_pass_test |
| 2.4 | A host cap on tool calls per message (`CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE`, else `CLAUDE_MAX_PARALLEL_TOOLS`) is stated in every rendered Run context | prompts_render.py, reader templates | deck_sheets_test |
| 2.6 | Vision prep is timed as its own timing-only entry (`vision prep`, not a `--from` stage) | run.py | vision_prep_timing_test, stage_control_test |
| 2.7 | The email-attachment folder is idempotent across naming schemes; no user file is deleted | extract_email.py | attachments_folder_reuse_test |
| 2.8 | `qa-round resolve --batch <file.json>` resolves several findings at once, all or nothing | gate_runner.py, SKILL.md, gates.md | qa_resolve_batch_test |

## Integrity

| ID | What changed | Main files | Evals |
|---|---|---|---|
| 3.1 | A cluster label never fuses two files; master-list rows are per deck FILE (an answered per-cluster sheet is migrated once, backup `master_list.pre_split.json`); `work/intake_clusters.SKIP` rolls labels back | intake.py, master_list.py, master_list_build.py, run.py, vision_validate.py | cluster_label_nomerge_test, master_list_per_file_test, vision_output_lookup_test |
| 3.2 | A reader marks a multi-line figure `combinable`; Python offers the sum as an option; ONE `combine_policy` question per field fans out to every card; a doubt merge already settled is closed and listed under "Settled without asking"; merge counts a storey-named key with an area unit | interpretation.md, clarify.py, run.py, merge.py, deliver.py | combinable_doubt_option_test, combine_policy_question_test, combine_policy_deliver_test |
| 3.3 | value-format exempts counts (`_common.COUNT_FIELDS`) and a bare area whose own source states its unit; merge formats a bare integral office area with that unit | gate_runner.py, _common.py, merge.py, repairs.py | value_format_single_pass_test, office_area_shape_test, repairs_merge_compat_test |
| 3.5 | Strict alias promotion in merge (`_common.ALIAS_PROMOTIONS`; `loadingDoors` never promotes; `meta.aliasPromotions`); a surviving strict-alias false absence BLOCKS capture-symmetry (ack `strict_alias_ok=<pid>:<key>`); reader door guidance | _common.py, merge.py, gate_runner.py, repairs.py, canonical.schema.json | alias_promotion_common_test, alias_promotion_test, d15_shadow_key_test, repairs_merge_compat_test |
| 3.6 | A figure only in a doubt's options is a capture-symmetry SIGNAL; a blank card title blocks coverage (the gate's title rule now mirrors the template's, displayName first) | gate_runner.py, interpretation.md | doubt_option_capture_test, card_title_collision_test |
| 3.7 | A lone printed total ships as printed with `statedTotalArea`; the "total read as warehouse area" shape is a blocking `arithmetic_basis` question (derive = attributed repair, keep = waiver in `work/arithmetic_waivers.json`) | interpretation.md, gate_runner.py, clarify.py, run.py | reader_rules_p1_test, arithmetic_basis_question_test, arithmetic_basis_gate_test |
| 3.8 | A multi-record deck whose records claim pages harvests only those pages | merge.py | gallery_claimed_only_test |
| 3.9 | A page the reader declined as a plan never binds as the Site Plan on pixels alone | images.py, merge.py | plan_reader_declined_test, plan_reject_test |
| 3.10 | A reader flags a let/sold building (`__meta.not_an_option`); a `not_available` broker question; an exclusion lands in `meta.excluded` (`excluded_by: "not_available"`) with its own Gaps Report heading | interpretation.md, record_schema.json, clarify.py, merge.py, deliver.py, gate_runner.py, run.py | not_available_exclusion_test, not_available_merge_deliver_test, input_accounting_reasons_test |
| 3.11 | An email record's `source_file` is the email file; its locator names date, sender and file | extract_email.py, master_list.py | email_locator_test, extract_test |
| 3.12 | A conflict note left stale by a repair gets a catch-all SUPERSEDED annotation | repairs.py | conflict_note_catchall_test |
| 3.15 | A ledger value row a repair replaced is marked `SUPERSEDED BY REPAIR:` and restored if the repair goes | merge.py, repairs.py, run.py | ledger_value_superseded_test, read_provenance_superseded_test, f24a_rederive_after_repairs_test |
| 3.16 | No plausible-duplicate note when both postal codes and both towns are stated and differ | merge.py | plausible_duplicate_postcode_test |
| 3.17 | A struck value ships the BLANK sentinel (`TBC`), with its own wording when it held no figure; a render guard maps an exact `tbd` | merge.py, deliver.py, _common.py | strike_sentinel_wording_test, d15_epc_token_test |
| 3.18 | A count-affecting doubt answered as shipped closes with no change; another option re-reads that ONE deck once (prior output MOVED to `work/extract/_prior_reads/`, decision in its Run context, `work/vision/reread.json`); a reader must copy a count doubt's `default` verbatim from `options` | interpretation.md, clarify.py, run.py, deliver.py | count_doubt_route_test, count_doubt_deliver_test, reader_rules_p1_test |
| 3.19 | File names built from client names are sanitised | intake.py | f14_filename_sanitise_test |
| 3.20 | A page several records claim and none anchors is shared by their carousels, never a Site Plan slot | merge.py, interpretation.md, vision_validate.py | gallery_shared_claim_test, imagepages_tier_test |
| 3.21 / 3.22 | Candidate tiles carry `masked` / `visible_fraction` / `off_page`; pages count photos below the hero floor | images.py, interpret_prep.py, vision_validate.py | candidate_facts_test |
| 3.23 | The master-list agent names a row as the email names it; inferences go in notes | prompts/master-list.md | prompt_render_test |
| 3.24 | Windows inputs whose path is too long to open are warned once per pass and listed in `inventory.unreadable_long_paths` | intake.py, gate_runner.py | long_path_intake_test, input_accounting_reasons_test |
| 3.25 | Duplicate-group seeding skips two records of one multi-record deck | master_list.py | seed_match_same_file_test |

## Upgrading an in-flight work dir

- Nothing already asked is re-asked: grouping and re-reads consider only never-asked doubts,
  and a question stamped before this round never triggers a re-read.
- Unread decks re-prepare once (`PREP_SCHEMA` 4). Read decks are untouched.
- An answered per-cluster master list is migrated to per-file rows once, not re-asked.
- Merge-side changes (3.2c storey rule, 3.3c, 3.5, 3.8, 3.9, 3.10b, 3.16, 3.17, 3.20) reach an
  existing canonical only after a re-merge (`--no-resume`). Deliver, ledger-retraction and
  render-guard changes apply on the next pass.
- The first per-property media build after the round is a full rebuild (the code fingerprint
  changed); later passes reuse it.

New work-dir artefacts: `email_bodies.md`, `print_digests.json`, `recorded_only_repairs.md`,
`vision/structural_fixes.json`, `vision/reread.json`, `extract/_prior_reads/`,
`arithmetic_findings.json`, `arithmetic_waivers.json`, `master_list.pre_split.json`, the
optional `intake_clusters.SKIP` sentinel. New keys: `__meta.not_an_option`, doubt
`combinable`, `meta.aliasPromotions`, `meta.excluded[].excluded_by`,
`inventory.cluster_label_rejected` / `cluster_cache_sha` / `unreadable_long_paths`, the ack key
`strict_alias_ok`. New env: `CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE`.
