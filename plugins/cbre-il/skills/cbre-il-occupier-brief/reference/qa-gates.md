# The QA round: one independent review, then the orchestrator fixes and ships

**One round. No re-review.** This skill produces a short pre-meeting brief, not a regulatory
filing, and the review budget has to match. An earlier version of this file ran two gates with
fresh reviewers on every re-run; on a live run that produced four review cycles on a
1,500-word document, which is the wrong trade. The rule now:

1. Scripts run first. They are instant and they catch what a script can catch.
2. **One** independent reviewer reads the draft and the ledger and returns findings.
3. **The orchestrator implements the findings**, all of them, and records what it did.
4. The final gate runs and the brief ships.

There is no second reviewer and no re-review. If the reviewer returns something the orchestrator
judges wrong, it says so in the delivery note with its reasoning rather than commissioning another
opinion.

## Why one round is enough here

The author still does not mark its own homework: the reviewer is a separate sub-agent with fresh
context that did not write the draft. What has gone is the loop, not the independence.

A single round works because the deterministic checks carry most of the load. Bullet counts,
section order, word count, UK English, dashes, untraced figures and ledger integrity are all
mechanical, so the reviewer spends its judgement only on what a script cannot see: whether the read
is right, whether the counter-case is conceded, and whether a persona bullet is worth the reader's
time.

## Step 1: the deterministic checks

Run these in the run folder and **fix everything they raise before dispatching the reviewer.** A
reviewer that spends its attention counting bullets is wasted.

```bash
python helpers/gate_runner.py all working/brief.md working/source_ledger.csv working/search_ledger.md
python helpers/ledger.py validate working/source_ledger.csv
```

That covers style (UK English, no em or en dashes), sections (all required sections present, the
three persona sections in the right order and place), depth (word count, bullet counts, table rows,
persona evidence labels) and trace (every figure in the brief maps to a ledger row; coverage the
other way is reported, not required, because the ledger is the corpus behind the brief).

## Step 2: the one review

Dispatch a single sub-agent. It reads from disk, never edits, and returns findings with severities.

> You are the independent reviewer for a CBRE Industrial & Logistics Occupier Brief on `<COMPANY>`,
> trigger `<TRIGGER>`, before a meeting with `<WHO>`. You did not write it. Read `working/brief.md`
> and `working/source_ledger.csv`, and do not edit either. This is the only review this brief gets,
> so cover the whole document rather than the first defect you find.
>
> Judge it as the person who has to walk into the meeting holding it. For every finding, cite the
> section and quote the line, and classify it HIGH (would embarrass the team, or is unsupported by
> the ledger), MEDIUM (weakens the brief), or LOW (polish). Rank them so the most important is
> first, because the orchestrator works down the list.
>
> Write your findings to `working/qa_review.md`, ending in a single `STATUS:` line. UK English, no
> em or en dashes, and sign with your own agent label.
>
> If the brief carries a node forecast, read `reference/node-forecaster.md` and the model appendix
> before judging it, and check the arithmetic direction rather than only the prose: a forecast that
> ranks on current demand instead of forward demand reaches the wrong cluster while every sentence
> in it reads well.

Criteria, in priority order:

| # | Criterion |
|---|---|
| 1 | **Nothing unsupported.** Every figure, name, title, date and site traces to the ledger. Any invented or inferred number presented as fact is HIGH |
| 2 | **No over-claiming.** A figure stated more confidently than its source supports, a pending policy written as settled, an estimate presented as fact, an absence finding written as a disclosure |
| 3 | **No mind-reading.** No persona bullet attributes a motive or feeling to a named person, and every inference is labelled |
| 4 | **The 30-second version stands alone.** Somebody who reads only it can hold the conversation |
| 5 | **Basis is stated**: adjusted versus reported, which entity, which financial year, sq ft versus sq m, constant versus actual currency |
| 6 | **The counter-case is conceded.** The IS / IS NOT table concedes something real, and the wedge acknowledges the honest objection, including any incumbent adviser |
| 7 | **Staleness is flagged.** Anything that will have moved by the meeting is marked |
| 8 | **It earns its length.** Leads with the so-what, no adjective where a number belongs, nothing padding it, and the persona sections are specific enough that the post-holder would recognise their own agenda |
| 9 | **The question we cannot answer**: the obvious thing the client will ask that the brief leaves the team unable to handle |
| 10 | **The node forecast is labelled, calibrated and falsifiable.** If the brief carries a **Where the next node probably goes** section: it is marked as CBRE analysis and an inference, its growth rate is calibrated from the subject's own history rather than asserted, its trigger names the peers it came from, it states a measured back-test error in km, it predicts a zone rather than a town, and it carries a falsifier and three leading indicators. A forecast with no error bar is a view, and a view presented as a model is a HIGH finding |

## Step 3: the orchestrator implements

Work down the list. For each finding, either fix it or record why it is not a defect. Write both
into `working/qa_response.md`: the finding, what changed, and the file and line. That file is the
audit trail, and it replaces the re-review.

Two rules on implementing:

- **Fix every severity, not just the HIGHs.** On a live run the orchestrator fixed only HIGHs on
  three successive passes, so the unfixed MEDIUMs were re-graded upward each time and the same pack
  failed three reviews. Clearing the whole list once is faster than clearing the top of it three
  times.
- **A disagreement is allowed, once, in writing.** If a finding is wrong, say so in
  `qa_response.md` with the evidence, and say it again in the delivery note so the user sees it.
  Do not commission a second opinion.

## Step 4: the final gate, then ship

```bash
python helpers/final_gate.py --dir .
```

It re-runs the deterministic checks, reconciles the rendered DOCX text against `brief.md` so nothing
was lost in the render, checks for surviving placeholder text, and confirms the deliverables exist.
It also requires `working/qa_review.md` and `working/qa_response.md` to be present, which is how it
knows the round actually happened.

## What the user sees at delivery

Name, in two or three lines: the reviewer's HIGH findings and what was done about them, anything the
orchestrator disagreed with, and the top items on the Verification Sheet. The user should never have
to open the working folder to learn that something was contested.
