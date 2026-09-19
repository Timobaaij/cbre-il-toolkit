---
name: cbre-il-occupier-brief
description: "Produce a CBRE Industrial & Logistics OCCUPIER BRIEF: a short, dense, internal pre-meeting dossier that makes a CBRE I&L pursuit or broker team fluent on a target company before they walk in. Ships a CBRE-branded A4 DOCX, a Source Ledger where every figure traces to a retrievable source, and a Verification Sheet. Written in UK English. Use whenever the user asks to run an occupier brief, build an occupier or pursuit intelligence brief, prep the team or get them match fit on a target company or account before a meeting, wants a broker briefing or account intelligence brief, or hands over source material on a company and asks why it matters to CBRE. Trigger even when the need is only described (prep me for the Tesco meeting; who are we meeting and why should they care). For a ranked list of reasons to call them use cbre-il-outreach-angles; for a property use cbre-property-longlist."
---

# CBRE I&L Occupier Brief

An **Occupier Brief** is internal enablement: a leave-behind for the CBRE Industrial &
Logistics team, never a client deliverable. Its job is to make the room fluent enough to hold a
credible, forward-looking conversation and to steer it towards the network question. The governing
move in every section: **lead with the client's business problem, not with a building.**

**The bar.** A finished brief is a research product. It quantifies the financials, names and
compares peers, ties the regulatory backdrop to a specific footprint decision, and reads as though
written by someone who has covered the company for years. Thinness is a research failure, never an
acceptable outcome, and never fixed with adjectives.

**Not this skill.** A deck-length account plan is a `cbre-corporate-pptx` deck built on this
brief's own research. A property or scheme is `cbre-property-longlist` or a site brief. A sizing
study is `dc-sizing`. A reason-to-call sheet is `cbre-il-outreach-angles`. If that is what the user
wants, hand over.

## The five rules that are not negotiable

1. **Research before drafting.** The value is the intelligence, not the template. Do not open the drafting reference until the research is merged and the ledger validates.
2. **The search budget is 60 WebSearch calls for the whole run**, and the whole run should take
   well under an hour. Allocated per workstream below and enforced by `helpers/gate_runner.py
   budget`. When a workstream hits its cap it stops and reports the gap honestly. A target that
   genuinely needs deeper work needs a full account plan, not a bigger budget here.
3. **One independent QA round, then ship.** The draft gets exactly one review, by a sub-agent
   that did not write it. The orchestrator implements every finding and records what it did. There
   is no second reviewer and no re-review: this is a short pre-meeting brief, not a filing.
4. **Every material figure traces to a retrievable source** in the Source Ledger, with the figure as
   the source states it and a publication date. `gate_runner.py trace` fails on an untraced number.
5. **UK English, no em or en dashes, ever.** Use a colon, a comma, brackets or a full stop. Verbatim
   quotes keep their own spelling and punctuation. `gate_runner.py style` enforces both.

## What it produces

In `deliverables/`, relative to the run folder (never a hardcoded absolute path):

| Artefact | File |
|---|---|
| The brief | `<Company>_IL_OccupierBrief.docx` (A4, CBRE-branded, 1,800 to 3,600 words) |
| The audit trail | `<Company>_Source_Ledger.csv` plus `.xlsx` if openpyxl is present |
| What to confirm first | `<Company>_Verification_Sheet.md`: every time-sensitive or low-confidence claim, with an action |
| The forecast's audit trail, where a forecast ships | `<Company>_Node_Forecast_Model.md`: the calibrations, the sensitivities, the back-test error and the input files, so somebody can re-run or disagree with it |

Working files stay in `working/`. Set the run folder to a **shallow path** on Windows: a deep scratch
folder can push a path past 260 characters. The helpers carry a long-path guard, but Word and Excel
do not.

## The pipeline

**Toolkit update check (run once, first).** Run `python helpers/version_check.py`. It prints a
one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published (otherwise
it is silent); it does nothing but a single public version lookup, never blocks the run, and is
safe to ignore.

Detail lives in the reference files. Read the one for the stage you are in, not all of them.

| Stage | Owner | Output |
|---|---|---|
| 0 Scope | this thread | `working/variables.yaml`: target, trigger event, meeting context, who CBRE is meeting, the angle |
| 1 Research fan-out | **four parallel sub-agents, A to D** | `working/research/<X>.md` + `<X>.sources.csv` + a `SEARCHES_USED:` count each |
| 2 Merge and synthesise | this thread | `helpers/ledger.py merge` into `working/source_ledger.csv`, then a **one-page** `working/fact_base.md`: the spine, the conflicts and the gaps, not a second brief |
| 3 Draft | this thread | `working/brief.md` to the markdown contract, and the node forecast via `helpers/node_forecast.py` |
| 4 **The QA round** | scripts, then **one independent reviewer** | `working/qa_review.md`, then `working/qa_response.md` saying what the orchestrator did about each finding |
| 5 Render | this thread | `helpers/render_docx.py`, `helpers/ledger.py xlsx`, the Verification Sheet |
| 6 Final gate and deliver | scripts | `helpers/final_gate.py`, then `SendUserFile` |

### Stage 1: the fan-out and the budget

Dispatch all four as real parallel sub-agents in one message. Each gets its cap, the target, the
trigger if known, and the reporting contract in `reference/research-playbook.md`. Announce four,
send four.

| Workstream | Remit | Cap |
|---|---|---|
| A | The company and its numbers: financials, ownership, store estate, DC footprint | 18 |
| B | The trigger event and the people who hold the three seats | 16 |
| C | Peers on network shape, the advisory-competitive read, and the macro themes that tie back | 12 |
| D | Regulatory and buildings: only what bears on the decision | 8 |
| Reserve | Held by this thread for conflict resolution and the QA round | 6 |
| **Total** | | **60** |

Each agent writes its files **incrementally** and ledgers **8 to 12 rows**, so the merged ledger
lands at 30 to 50. The ledger is the audit trail for the brief, not a record of the research.

WebSearch calls count against the cap. Fetching a URL you already hold does not, so prefer a fetch
of a primary source over another search. Log every tally in `working/search_ledger.md` as
`| A | 34 |` lines; the budget gate reads that file.

### The QA round

Run the deterministic checks first and fix everything they raise, so the reviewer spends its
judgement on the read rather than on counting bullets. Then dispatch **one** reviewer that did not
write the draft. It returns ranked findings; the orchestrator implements all of them and records
each disposition in `working/qa_response.md`. If a finding is wrong, say so there with the evidence
and repeat it in the delivery note. **No second reviewer, no re-review.** Full method in
`reference/qa-gates.md`.

Deterministic checks, run in the run folder:

```bash
python helpers/gate_runner.py all working/brief.md working/source_ledger.csv working/search_ledger.md
```

## Reference files

| File | Read it when |
|---|---|
| `reference/research-playbook.md` | Stage 1: the six remits, the sub-agent dispatch contract, source hierarchy, the budget discipline |
| `reference/evidence-and-ledger.md` | Any time you touch the ledger: schema, the six tiers, confidence bands, conflict and gap protocol |
| `reference/content-framework.md` | Stage 3: the section-by-section contract, depth rules, the voice, UK English specifics |
| `reference/node-forecaster.md` | Stage 3, the **Where the next node probably goes** section: the method, the three calibrations, the mandatory back-test, the leading indicators and the failure modes |
| `reference/stakeholder-agenda.md` | Stage 3, the three persona sections: how to evidence them without mind-reading |
| `reference/qa-gates.md` | Stage 4: the deterministic checks, the single reviewer's dispatch prompt and criteria, and how the orchestrator records what it implemented |
| `reference/docx-contract.md` | Stage 5: the markdown contract the renderer parses, and the styling it applies |
| `templates/` | `brief.template.md`, `variables.yaml`, `search_ledger.md`, `verification_sheet.md` |
| `examples/` | The standard to write to: `worked_brief.md` with its matching `worked_source_ledger.csv` and `worked_verification_sheet.md`. A **synthetic** company; every figure is invented, so never reuse one as fact. It passes every gate, which is what makes it the reference. |

## The node forecast

An Occupier Brief on a company whose network is growing carries a ranked, falsifiable forecast of
where the next distribution node goes, built with `helpers/node_forecast.py` and the method in
`reference/node-forecaster.md`. It is the one section the occupier cannot get anywhere else, and the
easiest in the document to fake, so three rules hold:

1. **Every constant is calibrated or labelled.** Growth rates come from the occupier's own past
   market entries, the trigger from a named peer set. The tool refuses to make a timing claim
   without one.
2. **It ships with a back-test error bar** against a node the occupier has already taken, and names
   the error in km. No error bar, no forecast: call it a view instead.
3. **It predicts a zone and a window, never a town and a date**, and it is labelled an inference in
   the text.

Skip the section, and say why, when the occupier has fewer than about four past market entries and
no usable peer set. Two data points support a conversation, not a forecast.

`gate_runner.py sections` does not yet require this section: adding it means updating
`examples/worked_brief.md` first or the smoke test breaks. Until then it is enforced by this file and
by the reviewer, not by a script.

If a helper misbehaves, `python evals/smoke_test.py` runs the gates against the worked example and
against deliberately broken copies, and says which direction is failing.

## Output naming

`<Company>_IL_OccupierBrief.docx`, `<Company>_Source_Ledger.csv`, `<Company>_Verification_Sheet.md`.
Spaces become underscores; drop the legal suffix unless it disambiguates.
