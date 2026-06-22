---
name: cbre-il-account-briefing
description: Produce a dense CBRE Industrial & Logistics (I&L) ACCOUNT BRIEF on a target company that preps a real conversation. A C-suite-credible brief covering who the company is and what drives it (strategy, business model, multi-year financials, competitive position, challenges), how the supply chain works, how those challenges translate into real estate, property set-up, stakeholders, and movements. Runs an eight-stage pipeline with independent, shift-left QA and ships three artefacts (a CBRE-branded deck, a Source Ledger, and a Meeting Brief), every claim traced to a real source. Use whenever the user asks to run the account plan or one click account plan on a company, wants a CBRE I&L briefing, target pack, account brief, or executive brief on a retailer, manufacturer, distributor, e-commerce, or omnichannel business, or is prepping to meet a target head of supply chain, logistics, property, or real estate. Trigger even when the user only describes the need (prep me for X, build a target brief on X).
---

# CBRE I&L Account Briefing

This skill turns a target company into a **dense intelligence account brief** that preps a CBRE Industrial & Logistics lead for a conversation. It answers, with evidence: where the company stands, the strategy and where they are heading, how the supply chain actually works, the biggest challenges and how they translate into real estate, the current property set-up, stakeholders, and the latest movements. It is an intelligence brief, **not a sales pitch and not a speculative forecast.** A defensible quantitative forecast is an optional module, off by default.

This is a **methodology with hard, independent gates**, not a loose checklist and not a script you can shortcut. The single governing rule is the **Evidence Standard**: nothing reaches a slide that has not been checked against a real, retrievable source. Read `reference/evidence-standard.md` first.

Two design commitments make this world-class and are non-negotiable:
- **Independent review (separation of author and reviewer).** Every QA check that is a *judgement about work the orchestrator authored* runs in an isolated sub-agent with fresh context. The orchestrator runs only deterministic scripts and adjudicates verdicts; it never self-certifies a judgement review of its own plan.
- **Shift-left sense-checking.** The story and the substance are reviewed *before any slide is built*: first the narrative outline (G0), then the full content plan (G4). "This says nothing / the read is wrong" is caught for the price of a paragraph, not a rebuild.

## What this produces

Three deliverables, every time, in `deliverables/`:
1. **The CBRE-branded deck** (`<Company>_IL_Briefing.pptx`) - a **narrative-led** business-intelligence brief built via `cbre-corporate-pptx` that **explains the company's story in prose** so the reader understands it: who the company is and what is happening to it (strategy, the financial story, the major transactions told as dedicated prose-led scenes, the competitive position), then how the supply chain works, then what it means for real estate. **Composed from the story**, so the chapters and slide count flex with the company; tables are evidence behind the narrative, never the way to make a point. It always carries the **answer contract** (`reference/deck-structure.md`): the executive read up front, the company profile, strategy and financial story, the big movers, the company-specific supply-chain signature, the operating model and network, the real-estate translation and set-up, stakeholders, the opportunity intersection and what to probe, plus three mandatory persona slides ("what is on the mind of the CEO / CSCO / Head of Real Estate") placed at their act capstones as the conversation-prep payoff, no matter the company. The contract is a content floor checked as content, never a template: slide count and layout stay composed from the story. Dense by construction (prose fills the story slides, every table carries an analytical-read column, every scene leads with its so-what). Method in `reference/deck-structure.md`.
2. **The Source Ledger** (`<Company>_Source_Ledger.xlsx`) - every material claim mapped to a Claim ID, slide, claim, source URL, tier (1-6), exact figure/quote at source, publication and retrieved dates, confidence band and the test that set it, and verified yes/no.
3. **The Meeting Brief** (`<Company>_Meeting_Brief.md`) - the conversation-prep sheet: what to probe (intel gaps as opening questions), what to be ready for (likely objections), and every struck or unverified item, each with an action.

## Set the variables first

Collect these before running; validate them in Stage 0 and write `variables.yaml` (scaffold in `templates/variables.yaml`).
**Required:** company name (exact legal entity); today's date; company type (RETAILER / MANUFACTURER / B2B DISTRIBUTOR / E-COMMERCE / OMNICHANNEL / OTHER); geographic focus.
**Output language** (ask at the start, default English): the language the deck and Meeting Brief are written in. **Ask this as an OPEN question, not a binary**: "Which language should the brief be written in? Default English; any Latin-script European language is supported." Let the user name ANY supported language. **Do NOT reduce the choice to the company's home language vs English** - that is the mistake to avoid: a Dutch company's brief may be wanted in English, German, French or any supported language, and the language is the user's free choice, unrelated to where the company is based. Default to English only if the user has no preference. Supported set is **any Latin-script European language** - English, German, French, Dutch, Spanish, Italian, Portuguese, Polish, Czech, Slovak, Danish, Swedish, Norwegian, Finnish, and other Latin-script European languages (e.g. Hungarian, Romanian, Croatian, Slovenian, the Baltic languages); for a less common one, confirm glyph coverage with a quick render test before the full run. If a non-Latin-script language is requested (Cyrillic, Greek, CJK, Arabic/Hebrew), **stop and say it is not yet supported** (the fonts and the layout engine are Latin-only). Sources are read in whatever language they are in; only the AUTHORED text is written in the chosen language, and sourced figures/quotes stay verbatim in their own language.
**Strongly recommended:** trigger for interest; known stakeholders; existing CBRE relationship; meeting context (who and when, to order the Meeting Brief).

## The pipeline - eight stages, shift-left, independently reviewed

The contract between stages is the same: findings pass **with source records attached**, written to files on disk. The Orchestrator (this thread) owns the single Source Ledger, dispatches the independent reviewers, adjudicates their verdicts, and assembles the deliverables. Full detail in `reference/agent-architecture.md` and `reference/gates.md`.

### Stage 0 - Orchestrator
Validate variables (including `language`: ask it as an OPEN question - any Latin-script European language, the user's free choice, NOT a company-local-vs-English binary; confirm it is Latin-script, else stop and say so; default English only if the user has no preference; carry it into `content_plan.json` `deck_meta.language` so the renderer localises its chrome and the reviewers judge in-language); build the research plan; dispatch the five research agents; hold and merge the Source Ledger; run Synthesis & Analysis; write the narrative outline; assemble the content plan; dispatch the pre-build reviewers and fix every defect; run the Build; dispatch the post-build reviewers; run the Final Gate; assemble the deliverables.

### Stage 1 - Research agents (five, parallel)
Dispatch R1-R5 as real parallel sub-agents, each with its own context window and a single slice (`reference/research-question-bank.md`). Each fetches the company IR page first and returns a structured findings file plus a source record for every claim (`templates/findings_schema.md`). An agent that cannot find something returns an explicit gap, never a guess. Agents emit `*.sources.csv`; the Orchestrator merges with `helpers/ledger.py merge`.

### Stage 2 - Synthesis & Analysis (this thread)
Deduplicate, resolve conflicts (company filing beats news), build the single `fact_base.md`, and write the **analytical reads** the brief needs, company-first: the company-and-strategic-profile read and the financial-trajectory read, then strategy-to-space, how-the-supply-chain-works, challenge-to-real-estate, and the competitive read. See `reference/synthesis-and-analysis.md`. The forecast decision tree is an optional module there, off by default.

### Stage 2.5 - Narrative outline + G0 (this thread + independent review)
Write `narrative_outline.md`: the deck thesis, the meeting's intelligence questions, the chapter breakdown, and each slide's one-sentence thesis and intended layout carrying Claim IDs. The outline **composes the deck from the story**: which events become dedicated prose-led scenes, how many slides each chapter earns, where prose explains versus where a table is the right evidence. Author the prose in the CBRE voice from the first draft, not as a later pass: read `reference/content-and-tone.md` (which routes to the canonical `cbre-tone-of-voice` reference and explains how the dialed-down intelligence-brief register applies) before writing theses. Dispatch **G0**, an isolated reviewer that judges storyline quality and whether the structure fits the story, returning GREEN/AMBER/RED. Fix AMBER/RED before writing the content plan. This is the cheapest save in the pipeline.

### Stage 3 - Content plan (this thread)
Produce `content_plan.json` to `reference/content-plan-spec.md`: slide by slide, the layout composed from the content (scenes of rows and cells), every prose paragraph, stat, list, table and panel tied to ledger Claim IDs, and each slide or cell tagged with the answer-contract ids it lands (`answers`) so `gate_runner.py spine` can confirm the contract is covered. Then run the **depth / coverage pass**: `helpers/gate_runner.py coverage intermediate/content_plan.json intermediate/source_ledger.csv` lists every validated claim the plan does not yet cite, grouped by agent; review them cluster by cluster and either work them into a slide, add a slide, or record why they are left out (duplication or not relevant enough) in `coverage_log.md`. Coverage is a judgement call, but sourced material is never dropped silently. No slide layout repeats more than twice (the persona family is the one deliberate exception). The ledger `slide` column is derived from the plan (the `slide_no` of the first slide citing each claim), never hand-entered: `qa1` back-fills it, or run `ledger.py backfill-slides` explicitly; the canonical ledger is `intermediate/source_ledger.csv`.

### Stage 4 - PRE-BUILD GATE (G1-G4) - BLOCKING
Run the **full mechanical pre-check sequence** in-thread, in order, fixing each before the next: `helpers/gate_runner.py validate-plan` (schema) -> `self-check` (schema/renderer drift) -> `helpers/build_deck.py --dry-run` (every slide resolves, none sparse) -> `gate_runner.py envelope` (plan-time fit backstop: hard-blocks a headline/lead that fills the slide or a cover title too long for the band, and prints a non-blocking advisory for dense scenes to check against G7; catches off-Windows fit defects before any render) -> `gate_runner.py personas` (the three mandatory persona slides are present) -> `spine` (the answer contract: every required answer carried by a substantive slide) -> `qa1` (source integrity; back-fills the ledger `slide` column from the plan first) -> `qa2` (evidence & honesty) -> `density`. The full list and rationale are in `reference/gates.md` §Mechanical pre-checks; do not stop at qa1/qa2/density. The judgement halves then run as **isolated reviewers**: G1b source verification, G2 evidence & honesty, and **G4 the content-substance review** (a senior-strategist read of the whole plan that scores correctness, insight density, the "so what", flow, completeness and honesty, and blocks on any HIGH). Nothing is built until `gate1_scorecard.md` is `STATUS: ALL-PASS`. See `reference/gates.md`.

### Stage 5 - Build (this thread)
Build the deck from the **frozen** plan with `helpers/build_deck.py`. Render only what the plan contains; add no claim. The builder sweeps em/en dashes before saving and writes two side files next to the `.pptx`: `build_report.json` and **`deck_text.txt`** (the rendered text, one line per paragraph/table cell) - the input the post-build text gates and the Final Gate need.

### Stage 6 - POST-BUILD GATE (G5-G8) - BLOCKING
Reconciliation and the dash checks run as scripts **against `deck_text.txt`** (`gate_runner.py reconcile <plan> deck_text.txt <ledger>` and `qa4 deck_text.txt`; if the deck was edited by hand, regenerate it with `build_deck.py --dump-text <pptx> deck_text.txt`); the density check runs on the plan. The judgement checks run as **isolated reviewers**: G6b editorial (reads `deck_text.txt`), **G7 visual-render QA** (renders every slide to PNG and inspects layout and whitespace; `reference/visual-qa.md`), and **G8 red-team** (over-claiming and omission only). Fix and re-run, with a fresh reviewer each time, until `gate2_scorecard.md` is `STATUS: ALL-PASS`.

### Stage 7 - Deliver (this thread)
Export the Source Ledger to `.xlsx`; write the Meeting Brief, ordered by meeting context; run `helpers/final_gate.py`. Do not declare done while any line is red.

## How the gates stay honest

`helpers/ledger.py` rejects incomplete source rows. The two scorecards list every check, its status, the claim/slide it lands on, and a written justification for every strike or deviation, ending in a single machine-read `STATUS:` line that `final_gate.py` keys on. Judgement reviewers are isolated and never edit the artefact; re-runs use a fresh reviewer; loops are bounded and escalate honestly rather than loosening a criterion. The re-run count is recorded.

## Reference files
- `reference/evidence-standard.md` - the governing rule, confidence rubric, verification gate, data-gap and conflict protocols. **Read first.**
- `reference/agent-architecture.md` - stages, R1-R5 remits, the independent-reviewer dispatch contracts, the fresh-context-on-re-run rule, the model/effort table.
- `reference/research-question-bank.md` - the question slices (strategy, supply-chain operating model, challenges, recent movements, current set-up, competitive).
- `reference/synthesis-and-analysis.md` - dedupe, conflicts, the fact base, the analytical reads, and the optional forecast module.
- `reference/gates.md` - the full G0-G9 gate set, owners, pass criteria, independence and re-run rules.
- `reference/content-plan-spec.md` + `templates/content_plan.schema.json` - the scene content-plan structure (rows and cells) and the analytical-read / depth rules.
- `reference/deck-structure.md` - the story-led scene method (slide kinds and cell kinds), the answer contract (the mandatory answers and the `answers` tag), the persona act-capstone placement, and the two insight rules.
- `reference/supply-chain-signatures.md` - the company-specific supply-chain signature: the dimensions, the archetype library, and how it sets the I&L approach.
- `reference/visual-qa.md` - the G7 rendered-PNG review.
- `reference/content-and-tone.md` - full sentences, no em/en dashes, lead with the "so what", UK English, the senior-strategist voice, and the density rules.
- `reference/deliverables-and-ledger.md` + `reference/final-gate.md` - the three deliverables, ledger schema, Meeting Brief spec, and the Final Gate.
- `reference/opportunity-classification.md` - the OPTIONAL forecast/opportunity module (off by default).

## User preferences (always)
- Write in the chosen output language (`deck_meta.language`, default English; UK English when English). Sourced figures/quotes stay verbatim in their source language. No em or en dashes anywhere, in any language.
- Honesty over rhetoric: struck claims, intel gaps, thin sources and incumbents (e.g. an incumbent facilities-management provider) are reported straight, never smoothed over.
- Lead with the "so what". Every slide is dense and carries an I&L inference, not a fact dump.
- It is an intelligence brief, not a pitch: no generic recommendations; any CBRE-relevance angle is tied to a specific, sourced fact.
- Edit, do not rebuild: when re-running with updated inputs, re-do only the affected stages and rebuild from the content plan.
