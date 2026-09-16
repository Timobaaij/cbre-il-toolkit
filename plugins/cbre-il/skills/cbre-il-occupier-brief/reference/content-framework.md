# Content framework: what the brief says, in what order

Read this at Stage 4, with `fact_base.md` and the ledger open. Write to `working/brief.md` using the
markdown contract in `docx-contract.md`.

**Read `examples/worked_brief.md` first.** It is the standard to write to: a full brief that passes
every gate, with its matching ledger and verification sheet. The company is synthetic and every
figure in it is invented, so take the shape and the register from it, never a fact.

## Depth standard

**1,800 to 3,600 words of prose**, tables excluded. `gate_runner.py depth` warns outside that band
and fails below 1,400 or above 4,200. A brief with no forecast section should land near the bottom of
the band; one carrying the forecast and a full QA round lands near the top. The band was raised when the node forecast joined the
contract. It is not a licence to pad: an honest qualification earns its words, a restated figure
that is already in a table does not. Every analytical section carries real, sourced substance. If
the draft feels light, the fix is more research, not more adjectives; if it feels long, the fix is
cutting the sentences that do not change what somebody says in the meeting.

## The voice

Write as a senior CBRE Industrial & Logistics strategist briefing colleagues who may not have supply
chain backgrounds. A smart colleague in a corridor before the meeting: accessible, concrete,
confident. Explain the jargon you use, or do not use it.

- **Quantify everything.** "GBP 4.2bn revenue growing 6.1 per cent, 2.1x net debt to EBITDA, 11 DCs
  going to seven by 2028" beats "a large, consolidating distributor". An adjective where the
  research should have produced a figure is the signature of a weak brief.
- **Lead with the so-what.** Every bullet's first clause is the point; the evidence follows.
- **Business problem, network role, then building.** In that order, every time. This is the honest
  answer to a competitor claiming to be the only integrated firm: CBRE does not arrive louder, it
  arrives in the right sequence, and can then model the network, analyse the labour, test
  automation readiness, execute the transaction and finance it under one roof.
- **Name the capability, not the intent.** "We can model that" is weak. "SC Navigator can model the
  keep, consolidate and exit map with a customs overlay" is a reason to take the meeting. The I&L
  capability set to name where relevant: SC Navigator and AIMMS network modelling; Labour and
  Location Analytics; the CBRE and FORTNA automation-readiness partnership (clear height, power,
  floor flatness, throughput envelope); Capital Markets, sale-and-leaseback and dispositions;
  Occupier Agency as the execution layer; Project Management and fit-out; Valuation and Advisory;
  Business Rates; Lease Advisory; and Sustainability and net-zero advisory.
- **Intellectual honesty.** The IS / IS NOT framing and any stay-versus-go table must concede the
  real counter-argument, written with the same conviction as the case for. Credible limitations
  build trust; generic hedging does not.

## UK English, specifically

House style, enforced by `gate_runner.py style`:

- UK spellings: organisation, analyse, centre, labour, programme, favourable, fulfilment, modelling,
  utilisation, optimise, prioritise, enquiry, tyre, metre. Verbatim quotes and proper nouns keep
  their own spelling: the Global Logistics Center stays a Center.
- **No em dashes and no en dashes anywhere.** Use a colon, a semicolon, a comma, brackets or a full
  stop. For ranges use "to" ("2026 to 2028") or a hyphen in a compound.
- Dates as `14 May 2026`. Never 5/14/26.
- Currency with the symbol and the scale: `GBP 4.2bn` or `£4.2bn`, `EUR 1.1bn`. State the FX date if
  you converted anything.
- Areas in sq ft, with sq m in brackets where the source is metric: `620,000 sq ft (57,600 sq m)`.
- "per cent" in prose, `%` in tables.
- Thousands separated with commas. Decimals with a full stop.
- Single quotes only inside a quotation; double quotes for the talking points.

## The sections, in order

Use `## Section Title`. Include the sections the material supports; omit a thin one rather than
padding it, but the sections marked **required** are required, and `gate_runner.py sections` fails
without them.

### 1. The 30-second version (required)
One or two dense narrative paragraphs. The most important section in the document: what the company
is with the headline financials, the trigger event with its date, and the one-sentence reason CBRE
should walk in now. Written to be read aloud in a corridor. If somebody reads only this, they can
still hold the conversation.

### 2. \<Company\> IS / IS NOT (required)
A two-column table that resets the framing the room is likely to walk in with. Header cells read
`<Company> IS` and `<Company> IS NOT`. Three to five rows. Each row corrects a specific, plausible
misread, not a straw man. The IS NOT column is where the honesty lives.

### 3. At a glance (required)
A two-column key and value table, **10 or more sourced rows**: headquarters, ticker or ownership,
leadership, financial year end, revenue and growth, EBITDA and margin, net debt and leverage,
guidance, segments, footprint (countries, sites, sq ft, owned versus leased), key customers or
channels, closest peers. Rows only, no header row. Every value is a figure with a source in the
ledger, or it does not belong here.

### 4. What is driving the business right now (required)
Four to six bullets, each a **bold lead-in** plus one or two sentences. The company's live
priorities: integration, cost-out, automation, sourcing shift, channel mix, service promise.
Grounded in what the company has said and committed to, with dates.

### 5. The industry backdrop (required)
Three to four bullets on the macro themes that line up with the company's own agenda. Each theme
tied to something the company has said or done. No free-floating sector commentary.

### 5b. Where the next node probably goes (required where the occupier's network is growing)
The forecast. Full method in `node-forecaster.md`; do not write this section from intuition, and do
not write it at all without running `helpers/node_forecast.py`.

Two or three ranked clusters with their tier, because growth-enabling beats cost-reducing and the
room will otherwise point at the biggest number and ask why it is not first. Then the landing
**zone** rather than a town, the size and tenure template taken from how the occupier solved its
last cluster, the window from the trigger and the lead time, the falsifier, and three leading
indicators with where to look. Carry the back-test error bar in the text and label the section an
inference. Omit it, and say why, when the occupier has too little history to calibrate against.

### 6. The regulatory and legislative read (required)
A short framing line, then three or more bullets from workstream D covering what is in force and
what is pending. **Every bullet ends in a footprint or real-estate implication.** Pending items
carry their status and likely direction, not false certainty. This is analysis, not policy colour.

### 7, 8, 9. The three persona sections (required)
`## What is likely on the mind of the Head of Real Estate`, then `## What is likely on the mind of
the Head of Supply Chain`, then `## What is likely on the mind of the CEO`. **Exactly three bullets
each**, in that order, placed after the regulatory read and before the CBRE wedge. Full rules in
`stakeholder-agenda.md`. This is the bridge from what is true about the company to what the person
across the table is actually carrying into the room.

### 10. Why this matters to CBRE (required)
The wedge. A short framing sentence, then three to four bullets, each naming a concrete opportunity
and the I&L capability that serves it, in the business-problem-first sequence. Where it sharpens the
positioning, name the client's footprint archetype and the matching entry: a network in
consolidation is entered with a model, not with available space.

### 11. Pocket talking points (required)
Five to seven quotable one-liners, each in double quotes, that a team member can say verbatim.
Specific, credible, and free of generic real-estate language. A line that could be said to any
company is a wasted line.

### 12. Questions to open the discovery session (required)
Four to five open questions, each ending in a question mark, that advance the pursuit and close a
real intelligence gap. Not filler, and not questions the research already answered.

### 13. Sources (required)
A narrative source list keyed to the ledger, plus the standard caveat: figures as reported;
management estimates subject to revision.

### 14. The FOOTER line (required)
`FOOTER: Prepared <Month Year>. Confidential: internal CBRE material. Verify time-sensitive figures
before any client-facing use.`

## Variants

Same DNA, same styling, same persona sections. Adjust the sections, never the look.

- **Stay versus go on a specific asset**: add a decision matrix table (a multi-column table renders
  with a green header and tinted rows) and keep the persona sections, which is where a stay-versus-go
  conversation is actually won or lost.
- **Sector read anchored to one account**: the drivers section becomes the governors of the sector
  shift, and the industry backdrop carries more weight. The persona sections stay.
