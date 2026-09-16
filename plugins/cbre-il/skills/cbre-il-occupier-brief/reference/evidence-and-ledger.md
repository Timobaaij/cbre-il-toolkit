# Evidence standard and the Source Ledger

The governing rule: **nothing reaches the brief that has not been checked against a real,
retrievable source.** The Source Ledger is the proof. It exists because three weeks after the
meeting somebody will ask where a number came from, and "the research said so" is not an answer.

## The ledger schema

One row per material claim. Scaffold it with `python helpers/ledger.py init working/source_ledger.csv`.

| Column | Rule |
|---|---|
| `claim_id` | `C001` upwards, unique. Assigned by `ledger.py merge`. |
| `section` | The brief section the claim lands in. |
| `claim` | **The clause as it appears in the brief, verbatim.** This is what makes tracing mechanical. |
| `figure_at_source` | The number or quote exactly as the source states it, including its own units and basis. |
| `source_title` | Document title and page or section, not just a domain. |
| `publisher` | Who published it. |
| `source_url` | A retrievable http(s) URL. A paywalled URL is acceptable; an unretrievable one is not. |
| `tier` | 1 to 6, below. |
| `publication_date` | `YYYY-MM-DD`, or `YYYY-MM`, or a bare `YYYY` where the source carries no finer date. Undated trade press and supplier case studies are common: record the coarsest true date rather than inventing precision, and say in the brief where a figure is only as good as its year. |
| `retrieved_date` | `YYYY-MM-DD`. |
| `sourcing` | `public` or `proprietary`. |
| `confidence` | `high`, `medium` or `low`. |
| `verify_before_use` | `yes` or `no`. Low confidence is always `yes`. |
| `notes` | Corroborating source, the basis of an estimate, or the conflict you resolved. |

## The six tiers

| Tier | What | Use |
|---|---|---|
| 1 | Company filings and statutory disclosure: annual report, interims, RNS, 10-K, 20-F, Companies House | The gold standard. Financials should come from here. |
| 2 | Company direct communications: results presentations, earnings-call transcripts, press releases, the company's own site | Strategy and intent, in their own words. |
| 3 | Government, regulator and statutory bodies: VOA, planning portals, ONS, Eurostat, SEC, port and airport authorities, CMA | Facts of record. |
| 4 | Established trade and financial press with named reporting | Good for events and colour. Corroborate figures. |
| 5 | Research houses and consultancies, including CBRE Research and CBRE Econometric Advisors | Market context. Attribute by name. |
| 6 | Aggregators, company-profile databases, unattributed posts, AI summaries | Lowest. A pointer to a real source, never the source. |

**How big the ledger should be.** **30 to 50 rows.** One row per material claim that reaches the
brief, not one per fact anybody read. A 2,000-word brief cites perhaps forty figures; a 241-row
ledger, which a live run produced, is a failure of judgement that costs merge time, validation time
and review time for no gain. If a claim will not appear in the brief, it belongs in the research
file, not the ledger.

**Hard rules.**
- Every figure in **At a glance** and every financial or footprint number must be tier 1 to 3, or
  tier 4 and above with a second corroborating source named in `notes`. `ledger.py validate`
  enforces this.
- At least half the ledger must be tier 1 to 3. Below that, the brief is leaning on secondary
  reporting and G1 should say so.
- A full brief traces **at least 15 distinct sources**. Fewer means a workstream was skipped. More than about 50 rows means the ledger has become a browsing record.
- A tier-6 source is never the only source for anything that goes in the brief.

## Confidence bands

| Band | Test |
|---|---|
| `high` | Tier 1 to 3, current, unambiguous, and it does not move week to week. |
| `medium` | Tier 4 or 5, or a tier 1 to 3 figure that is dated, restated, or on a different basis than the brief uses. |
| `low` | Single-sourced, an estimate, a derived figure, or something that could change before the meeting. Always `verify_before_use: yes`. |

Anything `low`, plus anything that moves (guidance, net debt, a live industrial dispute, a deal
close, a lease date, a planning decision), goes on the **Verification Sheet** with a named action.

## Conflicts

Resolve, then record the resolution in `notes`. The order of precedence:

1. The company's own filing beats the company's own presentation.
2. The company's own presentation beats the press.
3. A regulator's record beats a company's description of that record.
4. A dated figure beats an undated one.
5. If two credible sources genuinely disagree and it matters, put **both** in the brief with their
   sources. A brief that shows the disagreement is stronger than one that picks silently.

Watch the basis, not just the number: adjusted versus reported EBITDA, calendar versus financial
year, constant versus actual currency, gross versus net internal area, sq ft versus sq m, pallet
positions versus racking locations. A basis mismatch is the commonest way a brief becomes wrong
while every number in it is technically true.

## Gaps

A gap is a finding. Write it as one.

- In the research files: a `GAPS:` block naming what could not be established and why.
- In the brief: either omit the section, or state the gap in a sentence. "The company has not
  disclosed its total warehouse area; the 11 sites named in the FY25 report are listed below" is a
  useful sentence. An invented total is a fireable one.
- Never fill a gap with a plausible number, a sector average presented as the company's, or an
  adjective standing in for a figure.

## Proprietary versus public

If a claim rests on CBRE internal intelligence rather than published sourcing, mark it
`sourcing: proprietary`, attribute it in the brief ("CBRE internal availability data", "CBRE
Research", "the local agency team"), and keep it separate from public-source claims so the team
knows which confidence to speak with. Never present proprietary intelligence as published fact, and
never put anything client-confidential from another account into a brief.
