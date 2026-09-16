# Research playbook: four workstreams, 60 searches, 15 minutes each

An Occupier Brief is a research product, but it is a **short** one. This file is calibrated to that.

## The budget, and why it is small

**60 WebSearch calls for the entire run.** Four agents, four caps, a small reserve.

| Workstream | Remit | Cap |
|---|---|---|
| **A** | The company and its numbers: financials, ownership, the store estate, the DC footprint | 18 |
| **B** | The trigger event and the people: what is happening now, and who holds the three seats | 16 |
| **C** | Peers and industry: network shape against the closest comparators, and the macro themes that tie to this company | 12 |
| **D** | Regulatory and buildings: only the measures that bear on the actual decision | 8 |
| Reserve | Held by the orchestrator for conflict resolution and the QA round | 6 |
| **Total** | | **60** |

This was 200 across six workstreams. On a live run that produced 241 ledger rows and a
25-minute wall clock per agent to support a 2,300-word brief, which is account-plan machinery on a
pre-meeting document. If the target genuinely warrants that depth, the user wants a full account
plan, not this skill.

**What counts.** One WebSearch call is one unit. A WebFetch of a URL you already hold is free, so
the efficient pattern is one search to find the primary page, then fetch the documents from it.

**When a cap is reached.** Stop. Write what you have, then a `GAPS:` block naming what you could not
establish. Never pad, never infer a figure, never present an estimate as a finding.

**Efficient searching, in order of preference**
1. Go straight to primary: the investor-relations or filings page, the company's own site, the
   regulator's register. One search gets you the page; fetch the rest.
2. Use the company's own words: results statements and releases carry the strategy and the
   programme in the executives' own phrasing, which is exactly what the brief needs.
3. Search for the document, not the topic: "Testco annual report 2025 pdf" beats "Testco financial
   performance".
4. One well-chosen search with a site filter beats three broad ones.

## The sub-agent dispatch contract

Dispatch all four in a single message so they run in parallel. Announce four, send four. Each brief
must carry, verbatim:

- the target company (exact legal entity), the trigger if known, today's date, the geographic focus
- the workstream remit below
- **the search cap**, and: "Stop at your cap. Report `SEARCHES_USED: <n>` as the last line."
- the ledger schema from `evidence-and-ledger.md`
- the output contract:

```
working/research/<X>.md          findings, each with its Claim ID
working/research/<X>.sources.csv one row per claim, ledger schema, no blank required fields
last line of the reply:          SEARCHES_USED: <n>
```

- **Write both files incrementally, not at the end.** Create them after the first two or three
  findings and append as you go. An agent that researches for twenty minutes and then writes has a
  single point of failure: if it stalls before writing, the whole budget is lost. This has actually
  happened on a live run, to two agents out of six.
- **Ledger only what a brief would cite.** Aim for **8 to 12 rows each**, so the merged ledger lands
  at 30 to 50. Do not ledger every fact you pass: the ledger is the audit trail for the brief, not a
  record of your browsing. A 241-row ledger on a 2,000-word brief is a failure of judgement.
- these standing instructions:
  - **UK English. No em or en dashes.**
  - Prefer primary sources. Date every time-sensitive figure. Quote the figure exactly as the
    source states it, in `figure_at_source`, before you restate it in your own words.
  - An estimate is labelled an estimate, with its basis.
  - A gap is a finding. Return `GAPS:` rather than a guess. You will not be judged on volume.
  - Do not write prose for the brief. Return findings and sources; the orchestrator writes.

## Workstream A: the company and its numbers (cap 18)

Real numbers, not adjectives. Latest annual report and accounts, results statements, and for private
companies the filed statutory accounts.

**Name the reporting entity and the financial year end against every figure.** Groups with a
holding-company structure, a renamed parent, or a business-area segment inside a combined report are
the commonest way a brief becomes wrong while every number in it is technically true. Establish
which entity you are citing before you cite anything.

Capture: revenue and growth; the profit measure the company actually publishes, with its scope; net
debt or the disclosed components; forward guidance with its date; **capex, and how much is property**;
**the lease book or rent obligation**, which is the single most useful figure for a property
audience; ownership and control; the store or site count; and the **physical footprint**: number of
DCs, countries, floor areas where disclosed, owned versus leased.

Do not assume tenure. If it is not stated, it is unevidenced, and say so.

## Workstream B: the trigger and the people (cap 16)

Two jobs, and both are conversation-critical.

**The trigger.** Reconstruct, with correct dates, the most recent and most material property or
logistics events: every DC or site announcement, letting, extension or closure in roughly the last
two years, with location, size, developer or contractor, and whether it has actually happened. Any
stated network plan or target. The most recent results statement and what management said in it
about capacity or investment. If there is no dated event and the trigger is structural, say so
plainly.

**The people.** For the **Head of Real Estate or Property**, the **Head of Supply Chain or
Logistics**, and the **CEO**: name the post-holder where findable, with exact title and whether they
sit on the executive committee; find their own dated public words; and find what the company has
committed them to. Check the careers site for open roles in property and supply chain, which is a
cheap and underused signal. **Do not guess a name and do not attribute a view to someone with no
public quote.** Read `stakeholder-agenda.md` before you start.

## Workstream C: peers and industry (cap 12)

**Four to six closest peers from first principles**, not the household names if they are not
comparable, and reject the ones that fail with a one-line reason. For each, at least one comparative
figure, and the comparison that matters is **network shape**: how each serves its estate, and
whether it runs few large nodes or many regional ones. That contrast is usually the brief's spine.

Then the **advisory-competitive read**: which agents or consultancies are visibly in the account, and
the honest CBRE position against them. If a competitor holds the incumbency, the brief concedes it.

Then **two or three macro themes**, each tied to something the company has itself said or done. A
theme with no link to the company's own agenda does not belong in the brief. CBRE Research and CBRE
Econometric Advisors are legitimate sources; attribute them.

## Workstream D: regulatory and buildings (cap 8)

**Three or four measures maximum**, chosen for what bears on the actual decision, not a survey.
Every item ends in a line beginning "Implication:" that says what it does to space, location,
handling, stock or transport.

Pick from what applies: trade and customs; product compliance and traceability; packaging and waste;
labour and transport rules; and, **when the trigger involves building anything**, the buildings layer
that a development decision actually needs: energy performance and its national transposition,
the planning and consent route and its realistic timescale, thresholds that trigger environmental
assessment, grid connection, and any live capital allowance or incentive with a deadline on it.

An incentive with an expiry date is often the sharpest commercial point in the whole brief. Look for
one.

Flag pending items with their status. Do not write a proposal as though it were law.
