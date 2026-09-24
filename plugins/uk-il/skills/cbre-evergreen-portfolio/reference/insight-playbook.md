# Insight playbook: occupier portfolios

The reader is the client's property director, CFO or COO. They know their
business better than we do. They do not know what their property data says when
you put it all together. The report earns its place when they learn something they
can **act on**, and can trust every number.

This is a set of lenses and recipes, **not a template to fill in**. Every portfolio
has its own two or three things that matter. Find them, lead with them, and cut
the rest.

## What "outstanding" means

An insight must pass all five tests:
1. **New:** the property director would not have said it unprompted.
   ("You have 52 units" fails. "Five landlords hold 61% of what you lease, and
   three of them have leases ending before 2030" passes.)
2. **Consequential:** it changes risk, cost, control or options, and the copy
   says which.
3. **Actionable:** it ends in something a named person could start on Monday.
4. **Traceable:** every figure is in the ledger with its computation and
   denominator.
5. **Robust:** it survives "what else could explain this?", especially data gaps
   masquerading as facts.

**Specific beats general.** Name the building, the landlord, the year, the square
footage. Combining dimensions is where insight lives. A single-column statistic
is description. Two or three columns crossed is analysis.

## Lenses

Use the ones this portfolio needs. Each lists what to look for, the data it needs,
and where it usually hides.

**1. Shape.** Where the floorspace really is. Clusters (towns, parks, corridors),
concentration in the largest buildings (the top 5 as a % of floorspace),
operating-company split, single points of failure. *Needs:* size, geography,
group. *Hides in:* the largest buildings dominating every total. Say it.

**2. Control.** Who holds the power in each relationship. Owned vs leased share.
Landlord concentration (leased only). Intra-group landlords. Institutional vs
private landlords. Landlords who appear on several of the client's leases
(portfolio negotiating leverage). *Needs:* status, landlord.

**3. Time.** When decisions are forced. Expiries and breaks by year, **weighted
by floorspace**. Cliff years. WAULT, and why the average hides the cliff.
Recorded expiries already passed (holding over?). Leases with no expiry recorded.
Leases that have **not started** yet (they are future commitments, not running
leases: never in WAULT). Events clustered by landlord (one negotiation instead of
three). Events inside a stated window from the as-at date (these are projects
now). *Needs:* expiry, break, start, as-at date, `leaseState`. *Vocabulary:*
use the ledger's Definitions block exactly: running, not started, recorded
expiry passed, undated. Every window is explicit ("by end-2028", "within 24
months of 15 Sep 2026"). If the mapper warns that lease dates look templated,
the time lens must say the dates need checking against the leases before any
programme is built on them.

**4. Cost.** What occupancy costs, *only where recorded*. Passing rent against
the year the deal was struck: a rent set years ago was priced in a different
market, and the next review or renewal resets it. **The export cannot say in
which direction**, so show the *exposure*, not a forecast. The spread by region
or company. Sensitivity from the client's own numbers ("every £1 psf on a
600,000 sq ft building is £0.6m a year"; "every £1 psf on the 11 leases due is
£2.9m a year"). This is arithmetic on recorded floorspace, so it is allowed even
when no rent is recorded. *Needs:* rent, deal year (the mapper falls back to
`Deal quarter`), size. *Honesty:* never gross a partial rent roll up to the
portfolio. When rent is recorded on only a handful of units, the gap itself is
the finding: say it, and move the cost argument to exposure.

**5. Capability.** Which sites are hard to replace. Temperature control, eaves,
dock doors, yard, power, rail, 360° circulation, age and quality. Crossed with
time: a hard-to-replace site with a near-term event is a board-level risk.
*Needs:* spec flags (often sparse). Say how many carry the flag.
*A working test (state it in the ledger if you use it):* a site is hard to
replace when it meets two or more of:
- the **largest quartile**: rank ≤ ceil(n/4) of all units by floorspace;
- eaves ≥ 15 m;
- cold storage = Yes;
- **rail-connected**: "Connection to building" counts; "Connection to park" is a
  separate, weaker point, reported as such but not counted;
- cross-docked;
- yard ≥ 50 m;
- more than 50 km from the client's nearest other site. "Other sites" are the
  ones the client occupies today (running, passed, undated or owned). A lease not
  yet started is not a site yet, so mention it separately ("a second site 127 km
  away starts in 2031").

Add a criterion (dock doors, power) only if you state it and its threshold in the
ledger. Unknown values fail a test and are reported as "not recorded", so the
list is a minimum. Name the criteria in the copy ("one of the three tallest, and
120 km from any other site"), never just "strategic".
*Distance method:* great-circle (haversine) km between unit coordinates. The
nearest other client site gives isolation. Sites **within 10 km (inclusive)** of
each other form a cluster. Distances are straight-line: say "km apart", not
"drive time".
*Landlord concentration base:* third-party leased floorspace in **every lease
state except owned** (running, not started, passed, undated), because a landlord
holds the client's leases whatever their state. State the base. If the share
changes materially on running leases only, say both.

**6. Compliance and ESG.** MEES exposure (uk-rules.md §1: scope first), EPC
coverage, BREEAM. EV and solar columns that are empty or read "No" on every row
are a **data-confidence** finding ("not recorded in a usable way"), never evidence
that the buildings have none. Crossed with time: sub-B buildings whose lease
ends before 2031 are where the upgrade can be negotiated into the renewal.

**7. Data confidence.** What the portfolio cannot yet answer, and what that
costs. Field coverage by floorspace. The fields that would unlock the biggest
decisions. Turn gaps into a work plan: CBRE can close them, and that is
commercial value, stated plainly.

**8. Action.** Each finding ends in a verb: commission, bundle, open talks,
serve, verify, collect. Say who and when where the data supports it.

## Cross-dimension recipes (starting points for invention)

- Landlord × expiry window → "run these three leases as one negotiation".
- Capability flag × expiry → "your hardest sites to replace fall due first".
- EPC band × expiry before 2031 × MEES scope → "the upgrade belongs in this renewal".
- Deal year × rent × size → the single biggest reversion exposure.
- Cluster × landlord → a park where one landlord controls your whole presence.
- Operating company × tenure → which businesses sit on freeholds and which on short leases.
- Region × data completeness → where the record is weakest, and whether that matches where the risk is.
- Age/quality × size → large second-hand stock that needs capex or relocation thinking.
- Owned freeholds × location → capital locked in sites that could be sale-and-leaseback candidates.
  Flag as an option to consider, never as a recommendation. No valuations.
- Records last updated × lease events → stale records on live decisions.

Invent beyond these. If the data holds something unusual (a rail-connected
cluster, an estate that is 90% one landlord, a single building carrying a third
of the floorspace), that is the story.

## Choosing the spine

The storyline needs one argument, not a tour of lenses. Typical spines:
- **"Concentrated and time-bound"**: shape → control → time → action (a cliff year).
- **"Strong position, thin evidence"**: shape → data confidence → what we can and can't say → action.
- **"Hidden leverage"**: control → time → compliance → negotiation plan.
- **"Capability at risk"**: capability → time → what replacement would take.
Pick the one the data supports. The first scene states the whole argument in one
sentence. The last scene hands the reader to the dashboard to explore.

## Anti-patterns (reject on sight)

- Description without consequence ("The portfolio is geographically diverse").
- Averages that hide distribution (a WAULT without the cliff behind it).
- Extrapolating a subset (rent roll, EPC share) to the whole estate.
- Market claims the export cannot support (rental growth, yields, "prime").
- Regulatory claims beyond uk-rules.md, or stated more firmly than their status.
- Twenty findings. The dashboard carries **five**. The storyline has 8–12 scenes.
- Hedging every sentence. State what is recorded, plainly, and what is not.
- Our jargon in client copy (WAULT without "average years to expiry", "OMRR",
  "BTS") unless it is defined in place.
