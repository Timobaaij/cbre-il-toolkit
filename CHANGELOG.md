# Changelog

All notable changes to the **CBRE I&L Toolkit** (`cbre-il`) plugin and its
marketplace are recorded here. Versions follow [Semantic Versioning](https://semver.org):
`MAJOR.MINOR.PATCH`. The version in `plugin.json` is the one Claude Code uses to
decide whether an installed plugin is out of date, so it is bumped on every release.

How to update to the latest version is in the [README](./README.md#updating).

## [1.3.0] — 2026-08-17
### Added
- **A seventh skill: `cbre-brochure-downloader`.** Turns the brochure links in a property
  longlist spreadsheet into one zip of correctly named, validated PDFs — the input
  `cbre-property-longlist` expects. It reads the longlist's *hidden* Excel hyperlinks (parsing
  the workbook straight out of its zip container, so no third-party packages are needed), then
  generates a self-contained HTML tool the user opens in Chrome or Edge.

  The browser is doing the downloading for a deliberate reason: the Cowork sandbox has no
  outbound network, and two measured browser facts rule out the obvious designs — most brochure
  hosts send no `Access-Control-Allow-Origin`, so a page cannot `fetch()` these PDFs, and almost
  none send `Content-Disposition: attachment`, so navigation opens the viewer instead of saving.
  The bytes therefore travel internet → top-level browser navigation → Downloads → dragged back
  onto the page → renamed, validated, zipped. The navigation must be top-level (a hidden iframe
  renders invisibly and saves nothing), and there is a test suite guarding that from regressing.

  Each PDF is renamed after its property, every file is checked to be a real PDF, shared links
  are deduplicated, and anything that is not a direct PDF is flagged in a `gaps.md` rather than
  guessed at. Ships with 100 tests (89 pass, 11 skipped) and the shared update notifier, and is
  registered in the plugin and marketplace manifests and the README.

## [1.2.1] — 2026-08-17
### Fixed
- **Property longlist — what ships with the skill is now stated correctly.** The flywheel
  ledger directory `state/` is ignored (it is per user and grows every run), and
  `reference/geocode_cache.json` is no longer ignored: `enrich.py` merges all three
  `reference/*.json` caches into every run as **read-only seeds** (runs write to the work dir),
  so ignoring one of them contradicted both the code and its sibling caches, which were already
  committed. It ships seeded via `helpers/seed_geocode.py`. The keep-list comment now
  enumerates the whole shipped skill, including why `vendor/` sits outside the integrity
  manifest — a truncated wheel must degrade to `fitz_shim`, never hard-fail a run.
### Changed
- **Property longlist — the one dispatch prompt you fill by hand is now named as such.**
  Email ingestion is dispatched at Stage 1 rather than from a spine exit, so `work/prompts/`
  never renders it; SKILL.md now says to copy `prompts/outlook-ingest.md` and fill its slots
  verbatim rather than author a paraphrase, which is the documented top error surface.

## [1.2.0] — 2026-08-17

Dashboard template v35 → **v38**, three new helpers, and the eval suite grows to **107 tests**.

### Added
- **Prompts as files (`prompts/`, `helpers/prompts_render.py`).** The 18 canonical sub-agent
  dispatch prompts (the gates, clarify, the readers, tracker mapping, match adjudication,
  translation, Outlook ingest, region labels) are now files rendered by code rather than text
  the orchestrator hand-writes from its own summary of a reference doc — the class that caused
  the skill's worst documented failures, where a pasted-short field list silently overrode the
  contract. They are covered by the integrity manifest, so a truncated prompt is caught like a
  truncated helper.
- **A per-property view and a repair path (`helpers/project_properties.py`,
  `helpers/repairs.py`, `reference/per-property.md`).** `canonical.json` is one ~11 MB file,
  mostly base64 image data, so the thing a broker or reviewer actually wants — one option, its
  values, its photos, the provenance of each figure — was not readable in it. A read-only
  per-property view now makes it legible, and `repairs.py` adds **property-keyed** corrections
  applied after the merge (distinct from `overrides.json`, which targets a source record such
  as a spreadsheet row or brochure page).
- **A finding-to-gate flywheel (`gate_runner.py flywheel`).** Reviewer findings accumulate in a
  ledger under `state/`, deliberately outside the integrity manifest because it grows per run,
  so a recurring finding can become a permanent gate instead of being re-litigated per client.
- **`KNOWN-DEFECTS.md`** — the defect register from a live 37-property run, each entry now
  shipping a fix and an eval, kept as the evidence those evals exist to protect.
- **26 new evals**, including certification, handoff commands, pending diagnosis, raster
  escalation, strike disclosure, workdir exclusion, BOM tolerance, repair ordering and
  projection, and district/open-field validation.
### Changed
- **Dashboard template v36 → v38** with a matching `chrome_sha256`, and broad updates across
  extraction, enrichment, matching, merge, delivery, the gates, `reference/{gates,interpretation,
  template-contract}.md` and the canonical schema. All 12 language packs stay on an identical
  191-key set. Integrity manifest regenerated: **93 files, 48 helpers** (now including `prompts/`).
### Known issues
Three evals fail for reasons that pre-date this packaging — each fails identically on an
untouched copy of the skill — and none is a data-correctness fault:
- `open_field_scalar_test` (3): `validate_canonical` does not yet reject a list or
  array-of-objects value on an undeclared field, nor name the offending field.
- `repairs_projection_test` (1): a media repair does not resolve its file relative to the work dir.
- `plan_reject_test` (2, carried from 1.1.0): the ack normaliser uses `Path(...).name`, which does
  not strip a Windows `c:\dir\` prefix on POSIX.

94 of the 107 evals pass on a bare Linux box; the other 10 failures are only missing
Pillow/PyMuPDF/openpyxl, which Cowork provides.

## [1.1.0] — 2026-08-11

A large property-longlist release: the dashboard template moves from v25 to **v35**, the
eval suite grows from a handful to **83 tests behind one runner**, and the QA stage becomes
a bounded, propose-then-implement window. It supersedes the withdrawn 1.0.16 (whose bounded-QA
and numguard work is included here).

### Added
- **A clarification channel (`helpers/clarify.py`, exit 13).** When the source is genuinely
  ambiguous, the skill now ASKS — during the run, while the answer can still change the
  deliverable — instead of writing a caveat into a Gaps Report nobody reads. Previously only
  three specific moments could ask (deck reading, photo match, conflict adjudication);
  everything else silently degraded to a flag.
- **A `G-arithmetic` gate.** The chrome's derived `GLA = warehouseArea + officeAreaVal` must
  not exceed the source's own stated total (`meta.statedTotals`), so a derived figure can
  never quietly overstate what the source said.
- **A Chinese dashboard locale (`assets/i18n/zh.json`).** Twelve bundled language packs, all
  sharing an identical 193-key set.
- **One eval runner (`evals/run_all.py`) and ~70 new evals.** SKILL.md used to name four
  evals; there are now 83. New coverage spans arithmetic, honesty, source authority and
  self-conflict, capture contract/symmetry, coordinate provenance, per-card completeness,
  unit disclosure and area basis, atomic delivery, freeze order, resume/livelock behaviour,
  translation end-to-end, and documentation truth (`doctruth_test.py`).
### Changed
- **The QA window: the reviewers PROPOSE, you IMPLEMENT, then DELIVER.** The post-build review
  is hard-bounded in code (`gate_runner.py qa-round`, with `resolve` per blocking finding)
  rather than the old "re-review until zero HIGH/MED" loop that a deliberately memoryless
  reviewer could never terminate. Reviewers judge exactly as before; advisory findings are
  closed by being written into the Gaps Report, not by another round. `final_gate.py` takes
  `--qa-state` and is checked against the delivered report.
- **“tbd is never a number” guards.** The chrome's comparators and predicates can no longer
  treat a `tbd`/`—` sentinel as a numeric value in sorting, filtering or KPIs.
- **Dashboard template v26 → v35**, with a matching `chrome_sha256`, plus broad updates across
  extraction, enrichment, matching, merge, delivery, the gates and every reference document.
### Removed
- **Archived four near-orphaned docs and two dead files**, each now asserted absent by
  `doctruth_test.py`: `reference/memory.md`, `reference/vision-fallback.md` (superseded by
  `interpretation.md` as the single interpretation contract), `templates/ledger_columns.md`,
  `examples/`, `helpers/_ph_const.txt` (a byte-duplicate of `assets/placeholder.uri`) and the
  preserved `assets/dashboard_template.v18.html`.
### Known issue
- `evals/plan_reject_test.py` fails on Linux (2 assertions): the plan-rejection ack normaliser
  uses `Path(...).name`, which does not strip a Windows-style `c:\dir\file.pdf` prefix on
  POSIX, so the test's path-insensitivity assertions do not hold there. Pre-existing and
  unrelated to packaging — it fails identically on an untouched copy of the skill. It is the
  suite's only logic failure: 74 of the 83 evals pass on a bare Linux box, and the remaining 8
  fail only for want of Pillow/PyMuPDF/openpyxl, which Cowork provides.

## [1.0.15] — 2026-07-29
### Fixed
- **Property longlist — two Cowork-resume convergence bugs.** (1) The placeholder-image
  audit now shares the SAME persistent on-disk geometry cache the image pickers use
  (threaded through `_page_crops`), so a resumed merge — the ~40-second shell-cap
  kill/re-run cycle — no longer re-parses a whole deck's page geometry uncached on every
  pass. (2) The region-label prompt loop now treats the ANSWERED keys as the "already
  asked" set (not the bind cache, which drops declined `code=null` entries), so a declined
  label is no longer re-emitted every re-run and the exit-3 handshake actually converges.
  Touches `helpers/enrich.py`, `helpers/images.py`, `helpers/merge.py` and `helpers/run.py`,
  with a new `evals/audit_resume_test.py` covering both traps.

## [1.0.14] — 2026-07-22
### Changed
- **`cbre-il-outreach-angles` — Stage 3.5 abductive synthesis now reasons in structured
  steps.** Rather than leaping from an unresolved tension to a single guess, each bet is
  worked in three steps: (1) enumerate the real-estate move-types a tension admits
  (expand, enter, consolidate, close, exit, relocate, change tenure, in-house vs 3PL) and
  drop responses with no European property consequence; (2) gate by the company's posture
  (additive vs defensive vs mixed) to select which move-type is live — a mixed posture can
  carry two bets; (3) run ONE bounded, bet-specific research pass for soft corroboration,
  then strengthen, drop, or promote the bet (a bet that gains a hard dated trigger becomes
  a ranked angle, not a bet). Every bet is a European move, and the inference fence now
  records the move-type and the posture that selected it. Updates `helpers/final_gate.py`,
  `helpers/render_html.py`, `reference/evidence-and-ledger.md`, `reference/output-template.md`
  and `evals/smoke_test.py`.

## [1.0.13] — 2026-07-21
### Added
- **`cbre-il-outreach-angles` — Stage 3.5 abductive synthesis (“Reading the signals”).**
  A new orchestrator pass reads the FULL merged evidence set (including the low-signal
  and pressure findings the angle logic discards) and asks what un-announced decisions,
  if any, would best explain the whole pattern of signals (up to four; zero allowed,
  never padded). Each hypothesis is fenced — two independent sourced facts, a shown
  reasoning chain, a real-estate consequence, a named public tripwire, a disconfirming
  line and an epistemic label — and lands in a separate, internal `## Reading the signals`
  block that never enters the ranked list or affects developability scoring (“the
  deliverable of a bet is the tripwire, not the guess”). Updates `helpers/final_gate.py`,
  `helpers/render_html.py`, `reference/evidence-and-ledger.md` (the inference fence),
  `reference/output-template.md` and `evals/smoke_test.py`.

## [1.0.12] — 2026-07-21
### Changed
- **Property longlist — Stage-0 setup is now a single `visualize` widget.** The broker
  setup (client name, enrichment extras, openrouteservice key, email scope, language)
  is presented as ONE `visualize` elicitation widget showing all five questions in a
  single box and submitted together, instead of `AskUserQuestion` — never one question
  at a time, with a plain-text single-message fallback when the tool is unavailable.
  Adds `reference/setup-form.md` (the elicitation form and how to render it) and updates
  `SKILL.md` to match.

## [1.0.11] — 2026-07-20
### Added
- **Property longlist — a persistent Compare view (dashboard template v25).** A new
  fourth tab (after Grid, Map and Flyover) compares all properties side-by-side by
  default, honouring the live filters and sort, with per-property deselect chips and
  no cap. It reuses the chrome's existing `compareHTML()` renderer so it can never
  drift from the card tick-box compare popup, which is unchanged. New i18n keys
  (`tab_compare`, `cmp_*`) added to English and all 11 language packs.
### Changed
- **Property longlist — Flyover navigation.** Scrolling no longer moves between
  options; the Flyover shows one property at a time and you navigate with the
  prev/next buttons, arrow keys, the space bar, or a marker click (the scroll-driven
  IntersectionObserver was removed). Template bumped to v25 (matching chrome hash),
  with supporting updates to `helpers/i18n.py`, `helpers/make_template.py`,
  `helpers/merge.py`, `reference/template-contract.md`, `reference/visual-qa.md` and a
  new `evals/compare_test.py`. Integrity manifest regenerated (71 files); preflight,
  smoke and compare tests pass.

## [1.0.10] — 2026-07-20
### Changed
- **Property longlist — independent Site Plan verification.** The detail modal's
  Site Plan slot (`p.plan`) now gets its own visual-QA reviewer check, which the
  mechanical images gate never judged: the reviewer confirms the bound image really
  is THIS property's site plan (rejecting a location/context map, a photo, a spec
  table, a cover/contact page, or a different property's plan) and flags a plan the
  interpreter missed — often one half of a two-page spread. `helpers/gate_runner.py`
  now surfaces the plan-attachment gap (plans attached vs. properties, plus
  near-misses) so it is never a silent pass, with supporting updates to
  `helpers/images.py`, `helpers/merge.py`, `reference/interpretation.md`,
  `reference/visual-qa.md` and `evals/plan_detect_test.py`. Integrity manifest
  regenerated (71 files); preflight and the smoke test pass.

## [1.0.9] — 2026-07-20
### Changed
- **Property longlist — sharper site-plan detection.** A new high-precision text
  signal (`helpers/plan_signal.py` with a curated multilingual title/marker lexicon
  `assets/plan_lexicon.json`) rescues designed site-plan pages that the pixel
  classifier misreads as a photo or map — it matches real plan titles ("SITE PLAN",
  "Lageplan", "plan de masse", and the like) and drawing markers, and deliberately
  ignores spec-sheet vocabulary so it never fires on a spec table. Wired into
  `helpers/images.py` (`_plan_page_eligible`), with supporting updates to
  `helpers/merge.py` and `helpers/deliver.py`, and a new `evals/plan_detect_test.py`.
  Integrity manifest regenerated (71 files, now guarding the lexicon); preflight and
  the smoke test pass.

## [1.0.8] — 2026-07-17
### Added
- **Property longlist — first-party coordinates from map links (`helpers/coords.py`).**
  A shared, pure parser pulls a landlord/agent's OWN Google/Apple/OSM maps link or
  a `lat,lng` pair out of brochures, trackers, Excel cells and email bodies and uses
  it verbatim (via `extract_pdf.backfill_link_coords`) — a first-party pin beats a
  town-centre geocode and works fully offline, so a blocked geocoder no longer
  strands a run. Coordinates are still never model-invented.
- **Property longlist — free-text data translation (`helpers/translate.py`, exit 12).**
  When the dashboard language differs from the source, eligible property *prose*
  (descriptions, status) is translated by an isolated sub-agent while numbers, units,
  codes, dates and proper names stay verbatim; the original is kept in the Source
  Ledger, the pass is cached and resume-safe, and a blind G-lang reviewer confirms it.
  Declinable with a `.SKIP` marker.
### Changed
- **Property longlist — consolidated Stage-0 setup and dashboard template v24.** The
  broker setup is now ONE `AskUserQuestion` form (client name, enrichment extras, the
  openrouteservice HGV key, email scope and language in a single prompt — no
  follow-ups). Dashboard template bumped to v24 (matching chrome hash). Broad updates
  to extraction (`extract_pdf`, `extract_pptx`, `extract_xlsx`), `merge`, `deliver`,
  `gate_runner`, `run`, `i18n`, `make_template`, all 11 language packs and
  `reference/{data-engine,localisation}.md`, plus new evals (coords, boundary, flyover,
  format, xlsx-coords, backfill-coords, off-spec premerge, translate). Integrity
  manifest regenerated (69 files); preflight and the smoke test pass.

## [1.0.7] — 2026-07-10
### Changed
- **Property longlist — dashboard template v21: data-driven detail modal.** A
  property's detail-modal spec rows are now generated client-side by the
  template's `detailHTML()` on card click (rather than baked into the static
  HTML), and the modal gains an "additional details" section (new `sec_additional`
  string added across all 11 bundled languages). Bumps `assets/VERSION` to v21
  with a matching chrome hash and updates `assets/dashboard_template.html`,
  `helpers/make_template.py` and `helpers/i18n.py`. Adds an offline Node-based
  modal-render eval (`evals/modal_render_test.py` + `.mjs`) that executes the real
  `detailHTML()` in `node:vm`, and refreshes `evals/smoke_test.py`. Integrity
  manifest regenerated; smoke test passes (byte-stable chrome).

## [1.0.6] — 2026-07-05
### Changed
- **Property longlist — catch and drop decorative graphics from photo carousels.**
  The interpretation sub-agent can now flag non-building / abstract images (brand
  art, gradient or geometric-pattern backgrounds) via a new optional
  `__meta.exclude_refs` field (`templates/record_schema.json`), so they are dropped
  from a property's carousel; the hero is never touched and genuine site plans and
  location maps are kept. `helpers/contact_sheet.py` gains a `carousel_secondaries`
  montage of every secondary slide, and the **G-images gate now reviews it** — a
  decorative graphic that slips into a carousel reads as a "plan" to the mechanical
  classifier, so only the vision reviewer can catch it. Supporting updates to
  `helpers/images.py`, `helpers/merge.py` and `helpers/vision_validate.py`, guidance
  in `reference/interpretation.md` and `reference/gates.md`, and new coverage in
  `evals/extract_test.py`. Integrity manifest regenerated.

## [1.0.5] — 2026-07-04
### Added
- **Property longlist — nearest-city and nearest-border geo layers.** Two new
  bundled datasets, `assets/cities_major_dataset.json.gz` (European cities of
  ~100k+) and `assets/borders_dataset.json.gz` (a complete OSM border-crossing
  set), with `helpers/build_cities_major_dataset.py` and
  `helpers/build_borders_dataset.py` to regenerate them, so property enrichment
  can place each site against its nearest major city and nearest border crossing.
### Changed
- **Property longlist — broad extraction and pipeline refresh.** Updates across
  extraction (`extract_pdf`, `extract_pptx`, `extract_email`), enrichment
  (`enrich`, `web_enrich`, `images`, `vision_prep`, `vision_validate`), the
  pipeline spine (`run`, `intake`, `merge`, `normalize`, `match`, `ledger`,
  `deliver`, `build_dashboard`, `interpret_prep`, `render_qa`) and the gates
  (`gate_runner`, `final_gate`), plus refreshed evals (`extract_test`,
  `fixture_test`, and a new `atomic_test.py`).
- Regenerated `assets/integrity.json` (now also guards the two new datasets and
  builder helpers — 67 files, LF-normalised); preflight verifies integrity and
  the ownership mark. The update notifier (`helpers/version_check.py`) is
  retained and still wired into SKILL.md.

## [1.0.4] — 2026-07-02
### Changed
- **Update notifier now covers every skill, with clearer, Cowork-first
  instructions.** The best-effort `version_check.py` nudge is wired into all six
  skills (added to `cbre-il-outreach-angles`, `warehouse-network-mapper` and
  `cbre-tone-of-voice`; already present in the other three), so a user on any
  entry point learns when a newer toolkit version is available. Its message is
  rewritten to be actionable: it now spells out the Cowork path (Customize →
  Plugins → CBRE I&L Toolkit → Update) and the reliable remove-and-re-add
  fallback, plus the CLI command. Still best-effort — one anonymous public
  version lookup, silent when current or offline, and it never blocks a run.

## [1.0.3] — 2026-07-02
### Changed
- **`cbre-il-outreach-angles` — tighter scoring and a stricter gate.**
  Developability is now scored to a stated two-sub-factor rubric (scale +
  near-term transaction likelihood) with an **anchor-quality cap**: an item whose
  anchor fact is only an inference (e.g. unconfirmed freehold) is capped at
  Medium, so an unverified premise can no longer lead the sheet on scale alone.
  The ranked list must run in **non-increasing developability-band order** — the
  deterministic gate now FAILs an out-of-order list — and is treated as a ceiling
  of about five to seven, not a target (thin or speculative angles go to the
  watch-list, never padded into a slot). Email hooks must be **pasteable,
  send-ready sentences** (no "reference their capex" instructions), and are
  **hedged on verify-first items** so an unverified fact is posed as a question in
  the soft ask, never asserted. New anchor-integrity rules: a load-bearing figure
  must cite a primary or corroborating source (a data-aggregator-only citation
  raises an advisory WARN), and inferred ownership is framed as an open question,
  never as "owned". Updates `helpers/final_gate.py` and `evals/smoke_test.py`,
  `SKILL.md`, `reference/evidence-and-ledger.md`, and `reference/output-template.md`.

## [1.0.2] — 2026-07-01
### Added
- **New skill: `cbre-il-outreach-angles`.** Turns a target company into a
  ranked **Outreach Opportunities** sheet — about five to seven evidence-backed
  reasons to make contact now, ordered by how developable each opportunity is,
  each labelled for trigger strength (a dated event or a sourced structural
  inefficiency) and readiness (send-now / verify-first), and each shipped with a
  ready-to-send email hook and a call opener. Runs an orchestrated harvest (a
  "now" machine, a pressure machine, and an all-Europe facility-evidence
  fan-out), enforces dated-source evidence integrity and footprint completeness,
  and delivers a self-contained, CBRE-branded HTML file that leads in plain
  English with a jargon buster and tucks each item's evidence behind a
  collapsible toggle. The lightweight prospecting sibling to
  `cbre-il-account-briefing`. Ships `SKILL.md`, `helpers/final_gate.py` (the
  deterministic structural gate) and `helpers/render_html.py` (the renderer),
  `reference/` (evidence-and-ledger, source-playbook, output-template), and
  `evals/smoke_test.py`.
### Changed
- README and the marketplace/plugin descriptions now list the outreach-angles
  capability.

## [1.0.1] — 2026-06-25
### Changed
- **`cbre-il-account-briefing` — sharpened the supply-chain-signature read.**
  Reframed the `supply-chain-signature` slide as supply-chain / network
  intelligence — network shape, capacity (peak-vs-base), inventory positioning,
  make-vs-buy, in-house vs 3PL — explicitly *not* the real-estate angle, which
  stays on the later `challenge-to-real-estate` slide. Made it work for
  manufacturers as well as retailers: added make-vs-buy / vertical-integration
  and production-rhythm dimensions, two archetypes (vertically integrated maker;
  make-to-stock/make-to-order manufacturer), and a worked
  vertically-integrated-maker example. Updates `reference/supply-chain-signatures.md`,
  `reference/synthesis-and-analysis.md`, and `reference/deck-structure.md`.

## [1.0.0] — 2026-06-24
### Changed
- **Renamed the marketplace and plugin identifiers** — marketplace `cbre` →
  `cbre-il-toolkit`, plugin `cbre-il` → `cbre-il-toolkit`. The install token is now
  `cbre-il-toolkit@cbre-il-toolkit`. Re-added the plugin `displayName`
  ("CBRE I&L Toolkit") on the marketplace entry.
  **⚠️ Breaking:** existing installs are keyed to the old `cbre-il@cbre` identity and
  do not migrate — each user must remove the old marketplace and add it again once.
- **`warehouse-network-mapper`** — added Facility scope (warehousing only vs plus
  manufacturing), Depth modes (normal / detail / extra-deep recon-then-deep funnel)
  with the new `helpers/merge_leads.py` lead consolidator, and `tenure`/`status`
  fields; updated `make_geocoder_html.py`. (Skill update that landed after 0.6.2.)

## [0.6.2] — 2026-06-24
### Changed
- **`warehouse-network-mapper` — scope is the whole region, not the company's
  operating footprint.** The skill now always covers every in-scope European
  market, explicitly including the logistics gateway countries (Netherlands,
  Belgium, Germany, Poland) even where the company has no presence, adds an
  import/port-of-entry DC hypothesis, batches non-operating countries, and flags
  the "operating-country trap" — because central EDCs, bonded import warehouses
  and 3PL-shared hubs often sit where the company does not trade and are often the
  largest sites in the network. (SKILL.md methodology; the plain-language
  description is unchanged.)

## [0.6.1] — 2026-06-24
### Changed
- Rewrote the `warehouse-network-mapper` skill description in plain language
  (dropped the internal pipeline jargon, kept the trigger phrasing).
- Updated the README and the marketplace/plugin descriptions to include the new
  warehouse-network-mapping capability.

## [0.6.0] — 2026-06-24
### Added
- **New skill: `warehouse-network-mapper`.** Maps a company's real warehouse and
  distribution network across Europe (or one country) to an auditable Excel —
  country, city, geocoded lat/long, landlord/developer, size (metric or imperial),
  year in use, operator (3PL or occupier-run) and facility type. Runs an
  orchestrated pipeline of parallel research subagents (searching in English and
  the local language), geocodes from real addresses in code (never modelled), and
  measures coverage against the company's own stated network size. Ships `SKILL.md`,
  helpers (`_common`, `dedup`, `geocode`, `make_geocoder_html`, `units`, plus an
  offline `gazetteer.json`), and `reference/source-playbook.md`.

## [0.5.0] — 2026-06-24
### Added
- **Property longlist — ownership / provenance & tamper-evidence.** Adds a
  `NOTICE` file and an authorship mark across the core helpers (visible copyright
  header; `helpers/_common.py` carries `OWNER_MARK` / `OWNER_FINGERPRINT` and a
  zero-width canary). `helpers/preflight.py` now verifies the mark on every run
  (surfaced as a warning, never blocks), and `assets/integrity.json` records the
  SHA-256 of the marked files so tampering is detectable.
### Changed
- Dashboard template bumped to **v20** (`assets/VERSION` + `dashboard_template.html`),
  with supporting updates to `build_dashboard`, `make_template`, `i18n`, `merge`,
  `run`, the smoke test, and `make_integrity`.
- Regenerated `assets/integrity.json` against LF-normalised content (now also
  covers the preserved `helpers/version_check.py` update notifier).

## [0.4.0] — 2026-06-23
### Added
- **Built-in update notifier.** Each runnable skill now runs a tiny
  `version_check.py` at startup that compares the installed plugin version against
  the latest published on `main` and prints a one-line update hint **only if you
  are behind**. It is best-effort by design: a single anonymous public GET, a short
  timeout, no telemetry, silent when current or offline, and it never blocks or
  fails a run. Wired into `cbre-il-account-briefing`, `cbre-property-longlist`, and
  `cbre-corporate-pptx`. This works around Claude Code's unreliable in-place
  marketplace update so users find out when a new version is available.

## [0.3.6] — 2026-06-23
### Added
- **Property longlist — dashboard internationalisation (i18n).** The dashboard
  chrome can now be localised. Ships `helpers/i18n.py`, 11 bundled language packs
  under `assets/i18n/` (cs, de, es, fr, hu, it, nl, pl, pt, ro, sk),
  `evals/i18n_test.py`, and `reference/localisation.md`.
- The canonical schema now accepts `meta.ui_overrides`.
### Changed
- Dashboard template bumped to **v19** (`assets/VERSION`); the prior **v18**
  template is preserved as `dashboard_template.v18.html` so existing projects
  rebuild identically.
- Supporting updates across `build_dashboard`, extract/intake/merge/run/vision
  helpers, eval fixtures, and reference docs.
- Regenerated `assets/integrity.json` against LF-normalised content.

## [0.3.5] — 2026-06-22
### Changed
- **Account briefing — output language is now an open question.** The skill asks
  the user to name any supported Latin-script European language (their free
  choice) rather than offering a company-home-language-vs-English binary, and the
  supported-language guidance is expanded. Updated in `SKILL.md` and
  `templates/variables.yaml`.

## [0.3.4] — 2026-06-22
### Changed
- **Account briefing — deck builder and gate runner overhaul.** Substantial
  updates to `helpers/build_deck.py` and `helpers/gate_runner.py`, plus supporting
  changes to `SKILL.md`, several reference docs, the content-plan schema, and
  `variables.yaml`.
### Removed
- Stopped tracking the regenerated `evals/_smoke_out/` smoke-test output (now
  git-ignored); added a skill-local `.gitignore`.

## Earlier
- **0.3.0 – 0.3.1** — Initial public packaging of the `cbre-il` plugin and the
  `cbre` marketplace (corporate decks, account briefings, property longlist, CBRE
  tone of voice), plus client-compatibility fixes.

[1.3.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.3.0
[1.2.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.2.1
[1.2.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.2.0
[1.1.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.1.0
[1.0.15]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.15
[1.0.14]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.14
[1.0.13]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.13
[1.0.12]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.12
[1.0.11]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.11
[1.0.10]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.10
[1.0.9]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.9
[1.0.8]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.8
[1.0.7]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.7
[1.0.6]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.6
[1.0.5]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.5
[1.0.4]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.4
[1.0.3]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.3
[1.0.2]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.2
[1.0.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.1
[1.0.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.0
[0.6.2]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.6.2
[0.6.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.6.1
[0.6.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.6.0
[0.5.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.5.0
[0.4.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.4.0
[0.3.6]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.3.6
[0.3.5]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.3.5
[0.3.4]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.3.4
