---
name: warehouse-network-mapper
description: Maps a company's warehouse and distribution network across Europe, or a single country, and exports an auditable Excel with one row per facility — country, city, geocoded coordinates, landlord/developer, floor area (metric or imperial), year in use, operator (a 3PL or run by the occupier) and facility type. Every location is geocoded from a real address rather than guessed, and coverage is checked against the company's own stated network size so the gaps are honest. Use this when someone wants to map a company's warehouse or logistics network, find all of its distribution centres (DCs), build a warehouse list or a DC network map, or names a company and a country or region and wants its facilities located. It also applies to looser asks like "find their European footprint" or "build the warehouse Excel for company X".
---

# Warehouse Network Mapper

Produce an Excel that maps a company's real warehouse and distribution footprint across a chosen scope (most often Europe, sometimes a single country), where every facility traces to a source, coordinates are geocoded from a real address rather than guessed, and the network's completeness is measured against the company's own stated figures rather than claimed.

## Runtime environment (read this first)

This skill is built to run in Cowork, a sandbox with **no outbound internet from helper code**. That single fact shapes two stages:

- **Web research (Stages 1 and 3)** happens through the assistant's own web search and fetch, not through the Python helpers. The helpers never call the network.
- **Geocoding (Stage 4)** therefore cannot call a live geocoder from code. It runs offline against a bundled city gazetteer, and for street-level precision it generates a small `geocode.html` that the **user** opens in their own browser (which does have internet) and hands back a `coordinates.json`. Coordinates are still produced by a real geocoder, never by a model. See Stage 4.

The Python helpers are pure standard library, so they run in the sandbox with no `pip install`.

## Why this is a pipeline, not a single prompt

A single model turn asked to "find all of company X's warehouses in Europe" does four incompatible jobs at once: profile the company, search across many countries and languages, judge which hits are real facilities, and produce coordinates and sizes it does not have. The result looks complete and is not. The two failure modes are specific and predictable:

- **Invented data.** Asked for lat/long, a model returns confident coordinates that are wrong. Asked for size, it returns a plausible round number with no source. For a network map that feeds a model or a client conversation, fabricated cells are worse than honest gaps.
- **False completeness.** With no anchor, the model returns the handful of well-known sites and stops. Half the network is run by 3PLs under their own name and never appears in a search for the occupier.

The stages below split those jobs apart, give each a bounded scope and the right model, and wrap the whole thing in two disciplines that the single-shot version cannot have: an **independent anchor** for completeness, and **geocoding in code** so coordinates are never modelled.

## The one reframe that matters: anchor, do not chase "all"

"Find every warehouse" is unfalsifiable. You can never prove the list is exhaustive, so an agent rewarded for thoroughness will either pad the list or declare it complete prematurely. Do not optimise for "all". Optimise for **measured coverage against an anchor**:

1. In Stage 1, hunt the company's own stated network size, both overall and **per country/region where stated**. Annual reports, ESG/CSR reports, investor presentations and "our network" pages routinely state a number ("X distribution centres", "Y million sqm of logistics space", "Z fulfilment centres across N countries"). Those numbers are the anchor.
2. Map as deeply as the source playbook allows.
3. In Stage 5, reconcile the mapped count against the anchor and **state the gap honestly**: "company states 9 European DCs, this map locates 7, 2 unaccounted for". A map that names its own gap is stronger and more useful than one that silently claims to be exhaustive.

If no anchor figure exists, say so, and report coverage confidence from the breadth of source types that converged instead.

## Stage 0: Intake and scope lock

Lock these before dispatching anything. They flow through every downstream stage and must not drift.

- **Company.** Plus every legal entity, brand, fascia and former name. A retailer trades under fascia that differ from the parent; search must cover all of them.
- **Scope.** The list of countries. Europe-wide is the common case; a single country is allowed. Do not silently expand or narrow it.
- **Units.** Ask the user to choose **metric (sqm)** or **imperial (sq ft)** before the run. This is the unit the Size column and the size floor are expressed in, and the unit `units.py` converts every sourced figure into. Default metric. Always confirm, because the audience (UK vs Continental) usually has a strong preference and converting after the fact loses the raw basis.
- **Size floor.** Default **5,000 sqm (about 54,000 sq ft)**. Below this you drown in parcel depots, store stockrooms and last-mile lockers. State it in the chosen unit; confirm or override with the user.
- **Facility whitelist.** Default: national DC (NDC), regional DC (RDC), European DC (EDC), fulfilment centre, cold/chilled/frozen store, cross-dock, returns/reverse logistics, parts/spares. Excludes retail stockrooms, offices and pure last-mile micro-sites unless the user asks for them. Tune the whitelist to the client (a grocer needs cold-store granularity; an apparel brand needs returns).
- **Auditable extras.** The Source Ledger and Coverage/Gaps sheets default ON, matching house style. The user may switch them off.

State the locked scope (company, countries, units, floor, whitelist) back to the user in one line before proceeding. If any of these is genuinely ambiguous, ask once; otherwise proceed on the defaults and state the assumption inline.

## Stage 1: Profile and anchor (Opus, with web search)

Build the profile the research subagents need so they do not each reinvent it, and find the completeness anchor.

Produce:

- **Identity set.** Legal entities, brands/fascia, former names, ticker if listed.
- **Known 3PL partners.** Search for the company's logistics providers explicitly (DHL, Kuehne+Nagel, GXO, DSV, ID Logistics, FM Logistic, Wincanton, Rhenus, DB Schenker, CEVA, Geodis, and any named in the company's own filings). Half the network may sit under these names. This list is handed to every research subagent.
- **Anchor figure(s).** The company's own stated count of DCs / fulfilment centres / logistics sqm / countries served, with source, **overall and per country/region wherever stated**. A per-country anchor turns the Coverage sheet from one weak global ratio into a real gate per market. If none exists, record that.
- **Footprint priors.** Where the company is known to be heavy or light, to inform batching density.

## Stage 2: Batch and dispatch (Opus)

Partition the scope into research batches and write one brief per batch.

- **Batch by research load, not a flat count.** At most three countries per subagent is the ceiling, not the unit. A high-density country (the company's home market, or one with many sites) gets its own agent. Several low-presence countries share one. Aim to balance expected work across agents.
- **Write a self-contained brief per batch** using the dispatch template below, pre-filled with the identity set, the 3PL partner list, the per-country anchor (if any), and the per-country source playbook entries for the countries in that batch.
- Spawn all research subagents in parallel.

## Stage 3: Parallel deep research (Sonnet subagents, web search, in parallel)

Each subagent receives the brief and returns a strict structured record set. The full subagent instruction is the **Research subagent dispatch brief** below; do not paraphrase it loosely, dispatch it. The non-negotiables it enforces:

- Search every term in **English and the local language(s)**. The local warehouse vocabulary and high-value sources are in `reference/source-playbook.md`.
- **Run the source playbook** as a quantified contract, not a vibe. Per country, cover **at least four of the six source types** below, and the **planning/permit portal is mandatory wherever one exists** (it is the richest source for size, developer and build year). A "search pass" is one full sweep of the query battery for one source type in both languages.
- **Cross-search the 3PL partners and hunt the announcement genre.** For each provider, search the contract-win announcement directly ("[provider] opens warehouse for [company]") in both languages and read the provider's customer case studies, not only "[company] + [provider]". Half the network may sit under provider names or live only in trade press.
- **Stop condition tied to coverage**, not effort: keep searching a country until two consecutive passes surface no new facility AND the four-source-type floor is met. If the agent stops earlier, it must state why in the per-country coverage note.
- **Never output coordinates.** The agent collects the fullest address it can; geocoding happens in Stage 4. Size figures come only from sources, captured verbatim in `size_as_stated` with a `size_basis`; everything unknown is "tbd". Each record carries a `last_confirmed` year.

## Stage 4: Geocode (code and the user's browser, never the model)

Coordinates come from real geocoding, in two layers, neither of which is a model:

1. **Offline baseline, in the sandbox.** Run the geocoder against the bundled city gazetteer:
   ```
   python helpers/geocode.py --in records.json --out records_geocoded.json
   ```
   Every record with a known city gets a city-centroid coordinate (precision "city"); anything with no resolvable city is left "tbd". This always works, with no internet.

2. **Street-level upgrade, in the user's browser (optional but recommended).** The sandbox cannot call a live geocoder, so generate the browser tool and hand it to the user:
   ```
   python helpers/make_geocoder_html.py --in records_geocoded.json --out geocode.html
   ```
   The user opens `geocode.html` in their own browser, clicks "Geocode all" (it queries OpenStreetMap Nominatim client-side, one address per second per Nominatim's policy), and downloads `coordinates.json`. Merge it back, upgrading city pins to street/rooftop where resolved:
   ```
   python helpers/geocode.py --in records_geocoded.json --merge-coords coordinates.json --out records_geocoded.json
   ```

Record the geocoding precision per record (rooftop / street / city / tbd) so the user knows which pins are exact and which are approximate. A model never fills a coordinate; an address that resolves nowhere stays "tbd".

## Stage 5: Normalise sizes, merge, dedup, reconcile (code-assisted, then Opus)

Assemble the canonical record set from all subagent returns, in this order so each step has what it needs:

1. **Normalise sizes to the chosen unit.** Sources state size in sq ft, m2, hectares, acres or pallet positions. Convert every figure to a canonical sqm and a display value in the user's unit, keeping the raw string for audit:
   ```
   python helpers/units.py --in records_merged.json --out records_sized.json --units metric   # or imperial
   ```
   Pallet-position-only figures are never back-converted to an area; they stay "tbd" with a note.
2. **Dedup by location, then address.** Run the clusterer on the geocoded, sized records:
   ```
   python helpers/dedup.py --in records_sized.json --out records_deduped.json --review merge_review.json
   ```
   It matches the same building reached via two routes (a 3PL site appearing under both the 3PL name and the occupier name) on **coordinate proximity (within 150 m of street/rooftop pins) and on normalised address/postcode**, which catches duplicates that a name match or a raw address-string match misses. City-centroid pins are excluded from the proximity rule so two different sites in one city do not falsely merge.
3. **Resolve conflicts by source rank (Opus).** The clusterer never averages or silently picks; each merged site carries a `_conflicts` block listing the rival values. For each, prefer the higher-tier source (company filing or planning document over trade press over a listing over a job posting), write the chosen value, and note the conflict in comments. Never average a size; that is invention.
4. **Reconcile against the anchor.** Compare the mapped count to the Stage 1 anchor, overall and per country, and write the coverage statement. Flag countries where coverage confidence is low.
5. **Refresh the unit columns** if the conflict resolution changed any size: re-run `units.py` on the resolved file so `size_out` matches the final `size_sqm`.

## Stage 6: Independent QA (Sonnet subagent, blind)

Dispatch a blind verification subagent using the **QA subagent dispatch brief** below. It receives only the record set and the rubric, never the orchestrator's conclusions. It re-fetches a sample of cited sources and confirms the site, operator and size match what the source actually says.

**A FAIL verdict is a hard block.** If the QA returns FAIL, do not build the Excel. Run the recommended full check, fix or downgrade the offending records, and re-run QA until it passes. A FAIL that ships is the failure this stage exists to prevent.

## Stage 7: Build the Excel (code, xlsx skill)

Use your xlsx skill to build the workbook (in Cowork, the `anthropic-skills:xlsx` skill; on the public-skills container, read `/mnt/skills/public/xlsx/SKILL.md` first). Three sheets by default:

1. **Network** (the main sheet, schema below).
2. **Source Ledger.** One row per (site, field, source): site, field, value, source URL, source tier, date accessed. This is what makes the deliverable auditable.
3. **Coverage and Gaps.** The anchor figure (overall and per country), the mapped count, the gap, per-country coverage confidence, and a list of fields that are "tbd" so the user sees the holes at a glance.

**Optional map handoff.** Every record is geocoded, so the same deduped record set can feed the CBRE longlist/dashboard skill (`cbre-property-longlist`) to render the Leaflet "DC network map" the brief promises, in house style, with no extra modelling. Offer this when the user wants a visual, not just the spreadsheet.

## Output schema (the Network sheet)

Use these columns in this order. The first columns are the user's spec; the ones marked **(audit)** are required by house style and may be removed only on explicit request, at the cost of the audit trail.

| Column | Notes |
|---|---|
| Country | |
| City | |
| Lat | Geocoded in code. "tbd" if no resolvable address. |
| Long | Geocoded in code. |
| Geocode precision **(audit)** | rooftop / street / city / tbd. So a pin's exactness is never ambiguous. |
| Address **(audit)** | Fullest address found. Needed for geocoding and verification. |
| Site name / scheme | Building or scheme name where known. |
| Landlord / developer | Owner, developer or institutional landlord. "tbd" if unknown. |
| Size | In the chosen unit (sqm or sq ft). Sourced figure only. "tbd" if unknown. Never a guess. |
| Size (as stated) **(audit)** | The raw sourced figure and unit, verbatim, before conversion. So a number is never naked or silently re-unitised. |
| Size basis **(audit)** | stated / estimated / tbd. |
| In use since (year) | Often sparse. "tbd" where unknown, never inferred. |
| Last confirmed (year) **(audit)** | The year of the most recent source confirming the site still operates. Surfaces stale announcements as a filterable column, not buried prose. |
| Operated by | 3PL name, or "occupier-operated". "tbd" if unknown. |
| Used for | Facility type from the whitelist: NDC, RDC, EDC, fulfilment, cold store, cross-dock, returns, parts. |
| Confidence **(audit)** | H / M / L per record, reflecting source strength and corroboration. |
| Source ref **(audit)** | Short key linking to the Source Ledger rows. Full URLs live there. |
| Comments | Conflicts, caveats, the route the site was found by, anything the model would otherwise want to bury in another field. |

Expect uneven fill. Country, city, facility type and at least one source should be present on every record. Landlord, exact size, year and operator will be partial; that is the honest state of public data, and the Gaps sheet surfaces it rather than hiding it.

---

## Research subagent dispatch brief

Dispatch this to each Stage 3 Sonnet subagent, pre-filled with the batch's countries, the identity set, the 3PL list, the per-country anchor, and the relevant `reference/source-playbook.md` entries.

> You are mapping the warehouse and distribution footprint of **[COMPANY and all brands/entities]** in **[these one to three countries]**. Your job is to locate every qualifying facility and return it as structured data, with sources. Do not write prose around it.
>
> **What counts.** A facility of at least **[SIZE FLOOR in the chosen unit]** of one of these types: **[FACILITY WHITELIST]**. Ignore retail stockrooms, offices and last-mile micro-sites unless told otherwise.
>
> **Search in both languages.** Run every search in English and in **[local language(s)]**. Use the local warehouse vocabulary and the high-value source types in the playbook section you have been given. A term-only translation is not enough; search the local sources themselves.
>
> **Source-type floor, per country.** Cover **at least four of these six source types**, and the planning/permit portal is **mandatory wherever one exists**: (1) the company's own disclosures (annual/ESG report, "our network" page, careers site), (2) planning and permit portals, (3) the commercial register, (4) logistics and supply-chain trade press, (5) commercial property listings, (6) local news. Job postings are a useful *signal* that a site exists but are never the sole source for a size or a landlord. State in each country's coverage note which source types you actually reached.
>
> **Cross-search the 3PL partners, and hunt the announcement genre.** The company's known logistics providers are **[3PL LIST]**. A large share of the network is run by third parties and appears under the *provider's* name, or only in the press, never under the occupier's. Run both search directions, in English and the local language, and search every plausible provider, not only the ones already known:
> - **The contract-win announcement.** Providers press-release their wins and trade press republishes them, so search the *event* with verbs, not just the two company names: "[provider] opens / launches / new warehouse / new DC / to operate / awarded / wins contract / go-live / fulfilment for [company]", plus the reverse "[company] appoints / selects / outsources to / partners with [provider]" and "[company] distribution centre operated by". A search for "Kuehne+Nagel opens warehouse for [company]" surfaces the site, its location and often its size from a single release, where "[company] + Kuehne+Nagel" returns nothing useful.
> - **The provider's customer case studies.** Providers publish reference stories on their own sites ("customer stories", "case studies", "references") that name the client and frequently the exact site, size and function. High value and under-searched.
> When an announcement names a site, the operator field is the provider and the occupier is [company]; that site belongs in the map. Date the announcement and set `last_confirmed` to the year of your most recent confirming source; for anything more than two or three years old find a recent source confirming it still operates, and say so in comments if you cannot. The announcement gives you the operator and location but rarely the building's owner, so do not record the provider as the landlord unless a source says it owns the building; the landlord still comes from the property and planning angle.
>
> **Depth and stop condition.** Keep searching each country until two consecutive search passes surface no new facility AND you have met the four-source-type floor. Do not stop because you have found "enough". If you do stop early, say why in that country's coverage note. Laziness here is the failure mode this whole exercise exists to prevent: a short, tidy list is the wrong answer if the network is larger.
>
> **Honesty rules, non-negotiable.**
> - Do **not** output coordinates. Collect the fullest address you can; the orchestrator geocodes. Returning a lat/long is a defect.
> - Size figures come only from a source. Put the exact sourced text in `size_as_stated` (for example "452,000 sq ft" or "42.000 m2") and tag `size_basis` stated or estimated. Do not convert units yourself; the orchestrator does that in code to the user's chosen unit. Anything you do not have is **"tbd"**. Never write a plausible number.
> - Every record carries its source URL(s), a source tier, a confidence (H/M/L), and a `last_confirmed` year.
>
> **Return format.** One structured record per facility with these fields: country, city, full_address, site_name, landlord_or_developer, size_as_stated, size_basis (stated/estimated/tbd), in_use_since, last_confirmed, operator (3PL name or "occupier-operated"), facility_type, confidence (H/M/L), sources (list of {url, tier}), comments. Leave lat, long and size_sqm out; the orchestrator fills them. Plus, per country, a short **coverage note**: the company's stated count for this country if any, how many sites you located, which source types you reached, and your honest confidence that you have the whole country (and why).

## QA subagent dispatch brief

Dispatch this to the Stage 6 verification subagent. Give it only the record set and this rubric. Do not give it the orchestrator's conclusions or an expected answer.

> You are verifying a warehouse network map, blind. You have the record set and nothing else. Take a random sample of **at least 20 percent** of records (minimum five). For each, open the cited source(s) and confirm that the source actually supports the claim: the facility exists, it is operated by who the record says, the size matches the `size_as_stated`, the year matches.
>
> **Distinguish two different failures.** (a) The source does not support the claim, or contradicts it: that is a real failure, count it. (b) The source URL is dead or unreachable: before counting it, try the Wayback Machine (web.archive.org) for an archived copy, and try one corroborating search for the same fact. Only if neither recovers it is it a failure, and label it "unverifiable (link rot)" separately from "contradicted", because link rot is not fabrication.
>
> Report each sampled record as pass or fail with the evidence. If **any** sampled record is contradicted, say so loudly and recommend a full check of every record, because a contradiction signals systematic fabrication upstream. End with VERDICT: PASS or VERDICT: FAIL.

---

## Common failure modes to watch for

- **The invented coordinate.** Any lat/long that did not come from the gazetteer or the browser geocoder. Disqualifying.
- **The naked or re-unitised size.** A figure with no source, or a converted number with the raw `size_as_stated` thrown away. Keep the raw text; convert only in code.
- **The missing 3PL sites.** If the map has only occupier-named buildings and the company uses 3PLs, the network is half-mapped. Re-run the announcement search ("[provider] opens warehouse for [company]") and the provider case studies, not just "[company] + [provider]".
- **The stale announcement taken as current.** A 2018 "[provider] to operate a DC for [company]" is evidence the site once existed, not that it runs today. Date every announcement, set `last_confirmed`, corroborate older ones against a recent source, and flag in comments where you cannot confirm it is still live.
- **The premature stop.** A country "covered" in two minutes with three sites when the company is large there. The stop condition is two empty passes plus the four-source-type floor, not "enough".
- **The silent average.** Two sources disagree on size and the model splits the difference. Pick the higher-tier source and note the conflict; never average.
- **The padded list.** Inventing sites to match the anchor. The right move when the map is below the anchor is to state the gap, not to fill it with fiction.
- **False completeness.** Declaring the network "fully mapped". The deliverable reports coverage against the anchor; it does not claim exhaustiveness.

## Honest expectations on yield

Some companies disclose richly and use few 3PLs, and the map comes back near-complete with good fill on size and landlord. Others disclose little and outsource heavily, and the map is partial with many "tbd" cells on year and operator. The skill is honest about which case it is in rather than producing the same confident-looking table every time. A 70 percent map that names its own 30 percent gap is the deliverable; a 100 percent-looking table that is half fiction is not.

## User preferences (always)

- UK English throughout. No em dashes or en dashes in prose.
- Honesty over completeness. "tbd" is first-class, surfaced in the Gaps sheet, never smoothed over or invented.
- Coordinates are geocoded in code (offline gazetteer) or by the user's browser geocoder, never produced by a model.
- The user picks metric or imperial at intake; sizes are converted to that unit in code, the raw figure is kept in Size (as stated), conflicts are resolved by source rank, never averaged.
- Every site carries a Last confirmed year so stale announcements are visible at a glance.
- Edit, do not rebuild. On a re-run for one country or one fix, re-do only the affected stage and re-inject into the workbook rather than regenerating the whole map.
- Full, readable cells. Comments are sentences, not data dumps.

## Reference files and helpers

- `reference/source-playbook.md` (read first for research) per-country local warehouse vocabulary, the high-value source types to search, and the major 3PLs operating in each market. This is the concrete content that turns "go deep" into actual depth. Hand the relevant country sections to each research subagent.
- `helpers/geocode.py` offline gazetteer geocoding plus `--merge-coords` to overlay browser-geocoded coordinates. Never modelled.
- `helpers/make_geocoder_html.py` generates `geocode.html`, the browser tool the user runs to produce `coordinates.json` at street/rooftop precision.
- `helpers/gazetteer.json` offline city-centroid coordinates for European logistics cities; extend per project rather than letting a model invent a coordinate.
- `helpers/units.py` converts every sourced size to the user's chosen unit (metric/imperial), keeping a canonical sqm and the raw stated figure.
- `helpers/dedup.py` clusters duplicate records by coordinate proximity and normalised address, flagging source conflicts for resolution rather than guessing.
- `helpers/_common.py` shared utilities (JSON IO, haversine, address/postcode normalisation).
