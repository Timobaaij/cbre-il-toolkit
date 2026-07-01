# Source playbook (Stage 1 harvest)

This is the *how* behind the harvest. Each agent reads its own section, runs the queries, and **returns** every finding as a prefixed block with a date and a URL; the orchestrator writes the single evidence file (schema and merge rule in `evidence-and-ledger.md`). The single most important habit: **find the leading indicator before the annual report**, because by the time a footprint shift is in the annual report it is common knowledge and an opener built on common knowledge does not signal homework.

## Harvest hygiene (all agents)

- **Retrieval is mandatory.** Every finding must come from a live search or fetch. If the tools are unavailable, or a query returns nothing retrievable, return that as an explicit gap. Never fill a finding from training memory; an unsourced "fact" is the one failure mode this whole skill exists to prevent.
- **Search natively and across countries, never English-only.** Run every query in English AND in the native language of each country in scope, and search each country of interest separately, not just once at group level. Local-language sources (national job boards, planning and permit portals, statutory registries, regional and trade press) carry the signal earlier and in more detail than English coverage, so an English-only sweep systematically misses the very leading indicators this skill prizes. Use the local term: a distribution-centre or warehouse role is `Lager` / `Distributionszentrum` / `Logistikzentrum` (DE), `magazijn` / `distributiecentrum` (NL/BE), `entrepôt` / `plateforme logistique` (FR); supply chain hires, planning filings and permits have their own native terms (see the geography-specific portals below). The native-language pass is mandatory for any country of interest, not a nice-to-have.
- **Confirm the entity first.** Resolve the exact legal entity and its operating brands before searching, so the harvest does not drift onto a namesake or a listed parent when the operating company is a subsidiary. Report ticker, registration number and home country at the top of your returned block.
- **Capture the date with every finding.** A finding with no date cannot be graded and is therefore unusable as a live trigger. If a page has no visible date, record the access date and grade it no better than ageing.
- **Reproduce values as found.** Verbatim figures and quotes in their source language. Never round, convert or paraphrase a number into the evidence file.
- **Record gaps explicitly.** "No planning applications found in [market] as of [access date]" is recorded as a gap (what you looked for, where, and when), which protects the sheet from a false negative being read as an absence of activity.
- **Absence is a gap, never a finding.** A recorded gap means "I have not found X yet", which is honest. It must never silently become "X does not exist". You may assert non-existence only when a source positively states it (for example the company says it runs a single central DC); an empty search is never that source, and no angle may rest on a not-found.
- **Conflict resolution.** Company filing beats company press; company press beats trade press; trade press beats rumour. When two sources disagree, record both and the conflict.

## Harvest depth (go deep, stop at saturation)

The output is lightweight; the research is not. Do not stop after the first two or three hits. Run each source class until differently-angled queries stop surfacing anything new (saturation), not after a fixed count. Stopping rules differ by agent, and the old "stop at two or three triggers" early-exit for A and B is retired because it was the mechanical root of footprint-only angles:

- **Trigger discovery (Agents A and B).** Breadth-first and family-wide: before stopping, run at least one query per non-footprint trigger class you own (see "Angle families" for the menu: lease events, sale-and-leaseback, M&A duplicate-site, 3PL contract clocks, leadership, financial/refinancing/covenant/PE hold, nearshoring of production, new-market hiring). Do NOT stop at the first two or three hits, and do NOT stop the moment you have a footprint signal. Stop a given class once differently-angled queries return nothing new.
- **Footprint (Agent C).** Runs the all-Europe facility-evidence fan-out below: Phase 1 covers every country in the active set, Phase 2 saturates only the evidence-positive ones. Never an early-exit, group-level, English-only sweep.

As a floor, expect **well over a dozen searches** across the A/B harvest, plus the per-country fan-out. If a source class is paywalled (see below), spend one attempt then move on rather than burning effort on a wall. The reviewer's scoped re-retrieval (in `evidence-and-ledger.md`) is on top of this.

**Paywalled sources** (FT, Bloomberg, Mergermarket, EGi, CoStar, some registries) may be cited only if a free source corroborates the same fact, or if the headline/snippet itself carries the datable fact. Do not assert a paywalled figure you could not actually read.

---

## Agent A, the now machine (leading indicators)

Highest-value agent. These are decisions made internally and not yet packaged for investors.

**Job postings** (the single highest-value signal: a role in a market where the company has no current facility is a footprint decision in flight).
- Sources: company careers page; LinkedIn Jobs; Indeed (country domains); Google with `site:` and role terms; aggregator boards by country (NL: Indeed.nl, Nationale Vacaturebank; BE: VDAB, StepStone.be; DE: StepStone.de, Bundesagentur für Arbeit, Indeed.de; FR: APEC, France Travail, HelloWork; UK: Indeed.co.uk, LinkedIn).
- Query templates: `"[company]" (distribution centre OR fulfilment OR warehouse) manager [country]`; `"[company]" "network planning" OR "supply chain director" OR "head of logistics"`; `"[company]" automation OR robotics engineer site:linkedin.com/jobs`; `"[company]" careers [city where they have no known site]`.
- Read for: location (especially a new market), seniority, and clustering (five roles in one city is a site opening).

**Executive appointments** (a new senior leader's first hundred days is the best moment to be in the room).
- Sources: company newsroom / IR; LinkedIn (recent "started a new position"); trade press (The Loadstar, Logistics Manager, Supply Chain Movement, Lebensmittel Zeitung for DE retail, Supply Chain Magazine FR); appointment columns.
- Query templates: `"[company]" appoints OR names "chief supply chain officer" OR CSCO OR "director of logistics" OR "head of property" 2025..2026`; `"[name]" "[company]" linkedin`.
- Read for: function (supply chain, logistics, property, CFO), and how recent (compute weeks-since against the run date).

**Planning and permit filings** (a real estate event physically in motion, often 6 to 12 months ahead of investor language). Geography-specific:
- **UK:** local authority planning portals; the Planning Inspectorate (appeals); `"[company]" OR [developer] planning application warehouse [town]`; gov.uk; LPA weekly lists.
- **NL:** ruimtelijkeplannen.nl; omgevingsloket; officielebekendmakingen.nl (gemeente/provincie bekendmakingen); `"[company]" omgevingsvergunning OR bestemmingsplan distributiecentrum`.
- **BE (Flanders):** omgevingsloket Vlaanderen; provincial publications; `"[company]" omgevingsvergunning magazijn`.
- **DE:** municipal Bauleitplanung / Bebauungsplan notices; regional Amtsblatt; `"[company]" Logistikzentrum Bauantrag OR Bebauungsplan`.
- **FR:** Géoportail de l'urbanisme; enquête publique notices; the ICPE registry (georisques.gouv.fr) for large warehouses, which is a strong dated signal; `"[company]" entrepôt permis de construire OR ICPE`.
- Read for: applicant (sometimes a developer or 3PL acting for the occupier), size, location, decision date.

**Just-closed M&A** (the integration window is a live network-rationalisation trigger).
- Sources: company press; regulator merger pages (UK CMA, EU Commission competition); trade press; deal databases (snippet-level if paywalled).
- Query templates: `"[company]" acquires OR completes acquisition OR merger 2025..2026`; `"[company]" CMA OR European Commission merger`.

**Refinancing and bond maturities** (a near-dated balance-sheet clock).
- Sources: company filings; rating-agency press (Moody's, S&P, Fitch press releases are often free); bond prospectuses; for private companies, registered charges (see private branch).
- Query templates: `"[company]" bond maturity OR refinancing OR notes due 2026..2028`; `"[company]" Moody's OR S&P rating`.

**3PL contract clocks** (a multi-year logistics contract signed years ago is now due for tender).
- Sources: trade press (The Loadstar, Logistics Manager); 3PL provider press; public-sector tenders on TED (ted.europa.eu) where the buyer is public.
- Query templates: `"[company]" logistics contract OR 3PL OR "awarded to" [provider]`; look for a contract signed ~3 to 5 years before the run date.

**Opening / closure programmes in motion.**
- Sources: local news; trade press; company press; works-council / union notices in DE/FR (a closure consultation is a hard dated event).
- Query templates: `"[company]" opens OR closes OR consolidates distribution centre [year]`.

---

## Agent B, the pressure machine

### Listed company

The pressure that forces real estate decisions surfaces in the **analyst Q&A**, not the prepared remarks.
- Sources: company IR (results PDF, results presentation, **earnings-call transcript**); transcript hosts (Seeking Alpha, Motley Fool, company webcast replay); regulatory news (UK RNS, EU transparency notifications, US 8-K/13D).
- What to pull: capex direction and any automation/network language **in the Q&A**; working-capital and inventory commentary; margin pressure; restructuring or cost-programme announcements; activist or major-holder disclosures.
- Query templates: `"[company]" earnings call transcript Q[1-4] [year]`; `"[company]" capex guidance OR working capital OR inventory`; `"[company]" activist OR stake OR "transparency notification"`.
- Read for: the gap between what management chose to say and what analysts pushed on. The push is the pressure.

### Private company (see the private branch below for the full reroute)

There is no Q&A. Agent B instead reads statutory filings, registered charges and ownership clocks.

---

## Agent C, the footprint machine: the all-Europe facility-evidence fan-out

The single biggest cause of wrong warehouse research was scoping the search to where the company sells. **A company can run a warehouse OR a manufacturing plant in a country where it has no stores and makes no sales, so sales geography NEVER scopes this search.** Agent C is not one agent; it is a two-phase fan-out across a fixed European country set.

**Phase 1: one cheap (Haiku) agent per country, evidence-or-not.** Dispatch one agent per country in the active set (below). Each has ONE bounded job: establish whether there is EVIDENCE of any company facility in that country (distribution centre, warehouse, fulfilment centre, cross-dock, OR manufacturing/production plant), searching in English AND the country's local language(s). Each returns a structured per-country report (schema below). Cheap tier, a fixed small query budget per country, dispatched in waves of roughly eight to ten to respect rate limits. This is deliberately heavier than one search agent; do not collapse it back to a single group-level English sweep.

**Country set (fixed, NEVER derived from sales footprint).**
- **Full (opt-in): EU/EEA + UK + Switzerland (~32).** EU-27 (AT, BE, BG, HR, CY, CZ, DK, EE, FI, FR, DE, GR, HU, IE, IT, LV, LT, LU, MT, NL, PL, PT, RO, SK, SI, ES, SE) plus Norway, Iceland, Liechtenstein, the United Kingdom and Switzerland.
- **Lite (default, quick triage): the principal I&L markets** DE, NL, BE, FR, UK, IE, PL, CZ, AT, IT, ES, SE, DK, CH, **plus the target's country of registration or HQ if not already listed.** Run the full set when the user asks, or whenever the target is a manufacturer or pan-European operator whose production may sit outside the core markets.
- A per-country language map makes the fan-out mechanical: BE Dutch + French; CH German + French + Italian; FI Finnish + Swedish; IE English; LU French + German; otherwise the country's own language plus English.

**Per-country query set (fixed, English + local, ~4 to 6 searches each).**
- company + local facility terms: DE `Lager` / `Distributionszentrum` / `Logistikzentrum` / `Werk` / `Produktionswerk`; NL `distributiecentrum` / `magazijn` / `fabriek` / `productielocatie`; FR `entrepôt` / `plateforme logistique` / `usine` / `site de production`; IT `magazzino` / `centro di distribuzione` / `stabilimento`; ES `almacén` / `centro logístico` / `fábrica`; PL `magazyn` / `centrum dystrybucyjne` / `fabryka`; and each country's own equivalents.
- the national `our locations` / `Standorte` / `vestigingen` / `implantations` page.
- the national planning/permit or register term (DE `Bauantrag`, NL `omgevingsvergunning` / ruimtelijkeplannen.nl, FR `permis de construire` / ICPE georisques.gouv.fr, UK LPA portals).
- a national job-board probe (a cluster of site-based roles is facility evidence).
- an automation-vendor + country probe (AutoStore, Dematic, Knapp, TGW, Exotec; vendor PR often predates the occupier's own).

**Per-country evidence report (returned to the orchestrator, the sole evidence-file writer).**

| field | meaning |
| --- | --- |
| `country` | the country |
| `verdict` | `EVIDENCE-POSITIVE` / `EVIDENCE-ABSENT` / `INCONCLUSIVE` |
| `facility_types` | DC / warehouse / fulfilment / cross-dock / plant, where positive |
| `named_sites` | named site(s) and town(s), where positive |
| `best_source` | URL + date of the strongest evidence |
| `languages_searched` | the languages actually queried |
| `queries_run` | the verbatim queries, so the reviewer can spot-check |
| `note` | one line |

`EVIDENCE-ABSENT` is allowed ONLY after a real native-language search actually ran (a local-language query is logged and the query floor is met); it means "searched properly, nothing surfaced", which is still a GAP for angle purposes and NEVER a positive "no facility exists" claim. If the native-language search did not really run, the verdict is `INCONCLUSIVE`, not absent.

**Phase 2: deep enumeration ONLY in evidence-positive countries.** For each `EVIDENCE-POSITIVE` country, dispatch a Sonnet-tier deep agent (group a few small ones) running the full footprint enumeration: saturate sites, sizes, clear height, tenure and age, the planning pipeline, 3PL-operated sites, automation commitments, and any dated ESG/EPC exposure on existing buildings. Triangulate across the company's own pages, the annual/sustainability report, planning filings, national property databases, trade and local press, job postings by location, and 3PL-run sites. `INCONCLUSIVE` countries get one Sonnet retry, then a logged, counted gap. Most cost lands here, on the handful of positive countries, not on a deep run per country.

**What feeds the angles.** The coverage map is research scaffolding: it lives in the evidence file and the Source Ledger, never as sheet content. A facility found in a non-sales country is surfaced as an ANGLE (nearshoring, a new served-from hub, a post-M&A duplicate site), not as a completeness table. Channel-mix, automation, inventory and ESG signals from deep research feed the relevant angle families (see "Angle families").

**Footprint reconciliation, re-based on all-Europe coverage.** The control is no longer a company-stated DC total or the sales-country list (both retired); it is **coverage of every country in the active set.** Emit a `## European footprint coverage map` (one row per country in the set, using the per-country report schema) into the evidence file and Source Ledger, then a final status line:
- `RECONCILIATION: RECONCILED` only when EVERY country in the active set is `EVIDENCE-POSITIVE` (with source) or `EVIDENCE-ABSENT` (after a real native-language search), with zero `INCONCLUSIVE`.
- `RECONCILIATION: UNRESOLVED GAP` otherwise.

A company-stated DC total is demoted to a corroborating cross-check inside positive countries, never the control. `UNRESOLVED GAP` is the **normal, expected** state for a large occupier and is **non-blocking for shipping angles**: it blocks only saturation or complete-network LANGUAGE on the sheet, never the shipping of the ranked opportunities built on the positive findings. It keeps teeth through the `INCONCLUSIVE` retry-then-gap rule and the reviewer's spot-check that the verbatim local-language queries actually ran. (Note: "saturation" as a harvest habit is internal; the sheet may claim a complete European footprint only when the map reads `RECONCILED`, which will be rare.)

---

## Angle families (walk every one before pruning)

Real estate angles are not only "they are opening a warehouse". The author walks EVERY family below before pruning and, for each, either records a candidate anchored to a real dated fact (an **event-driven** trigger) OR to a **sourced structural tension** (a **structural** trigger: two company-specific, separately sourced facts whose tension is the hook, for example rapid growth in one country set against distribution still run from a distant hub) in the evidence file, OR logs an explicit `no-signal` line for that family. When a family points at a structural hook, harvest and record BOTH sourced facts (the two that create the tension), because a single fact plus a generalisation is a trend, not a structural trigger, and will be killed. Never fabricate a candidate to fill a family; the no-signal log is how a thin run is caught. The twelve families, each with its trigger signature and native query seeds:

1. **Lease event / break clause** - a lease expiry, break, over-rented or under-rented estate, dilapidations. Seeds: land registry / title, `Mietvertrag` / `huurcontract` / `bail commercial`, sale-and-leaseback press.
2. **Sale-and-leaseback / capital release** - owned-property monetisation, balance-sheet de-risking. Seeds: `sale and leaseback` / `cession-bail` / `Sale-and-lease-back`, owned-vs-leased disclosures.
3. **M&A integration / duplicate-site rationalisation** - post-deal network overlap, TSA exit clocks. Seeds: merger filings, `integration` / `Zusammenlegung`, network-consolidation press.
4. **Automation and grid power** - MHE/ASRS commitments, clear-height / floor-load / grid-power constraints, a tenure shift toward longer leases or ownership. Seeds: automation-vendor PR, `Automatisierung` / `automatisering`, grid-connection notices.
5. **Network redesign / cost-to-serve** - consolidation, regionalisation, service-level driven re-siting. Seeds: results commentary, `network optimisation`, 3PL RFP press.
6. **Nearshoring / reshoring of PRODUCTION** - manufacturing-plant moves, not only distribution. Seeds: `reshoring` / `Verlagerung` / `relocalisation`, plant opening/closure and works-council notices.
7. **3PL contract clock** - a multi-year contract approaching tender, an insourcing/outsourcing swing. Seeds: logistics-contract press, a contract signed ~3 to 5 years before the run date.
8. **ESG / EPC / CSRD on existing sheds** - a dated compliance regime biting an existing building (see the ESG gate).
9. **Leadership change in a real-estate-relevant remit** - a new CSCO / COO / CFO / Head of Property inside a decision window.
10. **Financial distress or expansion capital** - refinancing, covenants, a PE hold-clock, rating actions, fresh capital to deploy.
11. **Manufacturing-plant / production-site event** - a plant opening, closure, expansion or relocation distinct from distribution.
12. **New-market footprint entry** - a DC, fulfilment or cross-dock in a market the company is entering, often visible first as Phase-1 facility evidence in a non-sales country.

Ownership: Agent A primarily harvests families 1, 3, 6, 7, 9, 12; Agent B families 2, 3, 10; the Agent C all-Europe fan-out feeds families 4, 5, 8, 11, 12. The author runs the four-link chain once per applicable family, then ranks a broad field by developability into the single ranked list rather than proposing only one or two.

## The public vs private company branch

Set at Stage 0. It changes which sources exist and how the harvest is weighted.

**Listed company.** Use the agents as written; Agent B's Q&A is live and high-value.

**Private company (family-owned, founder-owned, PE-backed, mutual or cooperative).** There is no analyst Q&A, no capex guidance, usually no activist disclosure. Reroute:
- **Agent B pivots to statutory filings and ownership clocks:**
  - **UK:** Companies House (free) for annual accounts, and the **charges register** (a newly registered charge or satisfaction is a financing/refinancing signal).
  - **DE:** Bundesanzeiger / Unternehmensregister for Jahresabschluss.
  - **NL:** KvK (deponering jaarrekening; extracts are paid).
  - **BE:** Nationale Bank van België balanscentrale (annual accounts, free).
  - **FR:** Infogreffe / data.inpi.fr for accounts, BODACC for legal notices (free).
  - **Nordics:** national business registers (often free filings).
  - **Parent-group consolidated accounts (REQUIRED chase item, not optional).** When the target is a subsidiary of a larger holding or group, the only real financials are often the **parent group's consolidated filing**, and a freshly filed set is frequently the single freshest primary live financial source in the whole run. Resolve the parent or top holding entity at scope lock, and **pulling its most recent consolidated filing is a required step, not a "pull if possible"**: fetch it and write the dated figures into the evidence file, or, if it genuinely cannot be retrieved, log it as an explicit gap. It becomes a chase item the orchestrator must clear before authoring.
  - **PE ownership:** identify the sponsor and the **hold clock**. A typical private-equity hold is roughly four to six years; a fund approaching the end of its hold is a live disposal/refinancing/exit pressure. Also look for add-on acquisitions (a buy-and-build creates duplicate-site rationalisation).
  - **Credit / charges:** registered mortgages and debentures, trade-credit ratings, supplier reports.
- **Agents A and C carry more weight.** For a private company, hiring, planning filings, openings/closures and trade press are often the *only* live windows, so spend more of the budget there.
- **Source priority reorders** to: leading indicators (1) -> statutory filings and registered charges and PE hold clock (2) -> operating-model and trade-press footprint signals (3) -> background (4).
- **Be honest about thinness, but refresh before you give up.** Private companies legitimately produce fewer live triggers, so the leading-indicator agents often come up thin and the strongest evidence is an older primary source (a results filing, a lease deal, an appointment). Before you flag such a trigger as ageing or demote it, run the **recency-refresh micro-pass**: one targeted query for a newer confirmation (a current-year update, a "still true now" check). A fresher confirmation makes it live; if none exists it stays ageing with its outcome token recorded (see the micro-pass in `evidence-and-ledger.md`). Only after that, if the windows are genuinely closed, is it a "do not call yet" with a watch-list, not a manufactured angle.

---

## Source priority (the weighting that beats every other broker's reading)

Weight evidence in this order. The ordering is the resonance fix.

1. **Live leading indicators (highest weight).** Job posting in a market with no current facility; new senior supply chain or property hire inside their decision window; planning or permit filing physically in motion.
2. **Pressure from the latest results, Q&A over prepared remarks** (listed); statutory filings, charges and the PE hold clock (private).
3. **Operating-model and footprint inputs, and the real estate translation.** Channel shift, automation commitments, inventory policy, 3PL activity, and dated ESG triggers that bite a building.
4. **Lagging and background (lowest, mostly watch-list).** Generic strategy narrative, decarbonisation pledges with no dated bite, "expansion" as a standing trend.

Bias the harvest toward what they are quietly doing that you can be early on.

## The ESG gate

ESG is not banned, it is gated by the same forcing-function test as everything else. A generic decarbonisation or net-zero pledge is **background** and is demoted automatically; it never reaches the page as an angle. ESG becomes a live angle only when it has a **dated compliance trigger that meets a physical-building consequence**:
- an energy-performance regulation that makes the existing sheds non-compliant by a known date (for example UK MEES minimum EPC ratings, or equivalent national energy rules);
- a CSRD reporting obligation biting this reporting cycle;
- a customer-mandated emissions requirement forcing a building or fleet change;
- a green-financing covenant tied to building performance.

Told that way, the rare ESG angle that survives is real, and the 2030 platitude never appears.
