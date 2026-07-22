# Evidence and the ledger (read first)

This file is the governing rule in full, the two artefacts the pipeline writes (the internal **evidence file** and the broker-facing **Source Ledger**), how recency is graded against the run date, the re-retrieval and paywall protocol, the peer-pattern grounding rule, the anti-hallucination standard, and the reviewer's gate checklist.

## The one rule that governs everything

Nothing reaches the sheet that has not been checked against a real, retrievable, **dated** source. Every figure, date, facility count and named fact is reproduced as found, never estimated, rounded, recalled from training, or invented by the model. Any figure that cannot be sourced is omitted or marked as an assumption. This rule outranks every other instruction in this skill. When in doubt, leave the claim out.

A fact without a timestamp cannot be graded, so the harvest captures the date with every finding.

## Absence is a gap, never evidence

"Not found in my searches" is a gap to chase, never evidence that something does not exist. Conflating the two is how a thin harvest becomes a confident wrong claim, so:
- **Search-emptiness is always a gap.** Record it as a gap (`gap:` with what you looked for and where), never as a finding.
- **No opportunity may rest on a not-found.** A thesis that depends on "they appear to have no X" is killed unless the absence is **positively sourced**, meaning a source affirmatively states the non-existence (for example the company says logistics is centralised in one site). A `served-from` or single-central-DC claim must cite that positive source. Such a positively-sourced single-hub model is also exactly what powers a legitimate structural trigger.
- **The deterministic gate** FAILs search-emptiness language on the sheet ("found no", "could not find", "no evidence of", and the like), so the deliverable cannot narrate a search failure as a fact.

## Freshness grades, computed against the run date

Anchor everything to the run date set at Stage 0. Compute the age of each finding explicitly (run date minus publication or event date) rather than eyeballing it. Freshness no longer gates whether an opportunity reaches the list (ranking is on developability); it sets the **readiness label** the item carries.

- **Live.** Published within roughly the last two quarters (about six months), or an event whose clock is still running. A live, dated trigger earns an item the **send-now** readiness label; it does not gate whether the item reaches the list, because ranking is on developability and a strong opportunity with an ageing or structural trigger still ranks (carrying a **verify-first** label instead). A forward-dated forcing function (a bond maturity in nine months, a lease break next year, a compliance deadline) is graded on the **nearness of its clock**, not on when it was announced. A new executive is live while inside their decision window (roughly the first six months).
- **Ageing.** Six to twelve months old. An ageing trigger does not bar the opportunity; it earns a **verify-first** label. Before it is flagged, it gets the **recency-refresh micro-pass** (below): a fresher source regrades it live, otherwise it stays ageing and its Source Ledger row records a `refresh:` outcome token.
- **Background.** Older than twelve months, undated, or an ongoing trend with no dated forcing function and no sourced structural anchor. Not a usable trigger on its own; it goes to the watch-list unless independently reconfirmed. A **structural** trigger is NOT background: it rests on current, separately sourced facts whose tension is the hook (see the structural-hook fence in `output-template.md`), and it ranks on the strength of the opportunity, not on a press date.

**The recency-refresh micro-pass (before any ageing trigger is flagged or labelled).** The deepest primary sources (results, lease deals, appointments) are often the oldest, and for a quiet or private company the leading-indicator agents come up thin, so the engine systematically lands on ageing anchors. Rather than label them blind, run **one targeted query for a newer confirmation** (a current-year update, a "still true now" check) before finalising the grade. If a fresher source is found, the trigger is **live** (and the item can be send-now). If not, it stays **ageing** (verify-first) and its Source Ledger row carries an outcome token so the omission is explicit, not silent: `refresh: confirmed-ageing` (refreshed, no newer source found, still ageing) or `refresh: none` (nothing was refreshable for this trigger type). It is one query per ageing anchor, bounded. The deterministic gate FAILs any ageing-graded ledger row that lacks a `refresh:` token, so the micro-pass cannot be silently skipped.

## The two-axis score (developability and trigger strength)

Every opportunity is scored on two independent axes, and the list is ranked on the first.

- **Developability (the ranking axis).** This is scored, not vibed. Score it on two sub-factors the author must STATE on the Developability line, then combine into a band:
  - **Scale of the I&L transaction.** High = multi-site, a portfolio sale-and-leaseback, or a defined multi-building disposal or expansion mandate. Medium = a single significant site, or one transaction type. Low = a single small unit, prospective, or a hypothesis to test.
  - **Near-term transaction likelihood (next ~4 quarters).** Raised by a named decision-owner PLUS a live, dated workstream; lowered when the opportunity is contingent, the timing is unknown, or no owner is identified.
  Combine the two into a band (High / Medium / Low) and name BOTH sub-factors on the Developability line, so the rank is auditable rather than a vibe. When the two sub-factors disagree, the lower one caps the band unless a named owner and a live dated workstream justify rounding up.
  - **Anchor-quality cap (this resolves the order-versus-honesty tension).** The band is also gated by the F/I/A tag of the item's ANCHOR fact, meaning the single fact that makes the opportunity transactable (for a sale-and-leaseback, that the company OWNS the plants; for an expansion, that the capex is committed). If that anchor is `[INFERENCE]` or `[ASSUMPTION]` (for example an unconfirmed freehold), the item may NOT occupy the top (High) band: cap it at Medium until the anchor is a sourced `[FACT]`. An unverified premise therefore cannot lead the sheet on scale alone. The reviewer confirms the anchor's tag and applies the cap.
- **Trigger strength.** How dated and defensible the hook is. **Event-driven** is a dated forcing function with a clock; **Structural** is a sourced, company-specific inefficiency or tension with no single clock. Both are valid; trigger strength is a shown label and a tie-breaker within a developability band, never a gate.

**Ranking is non-increasing by band.** The single list runs High, then Medium, then Low, highest developability first; within a band, break ties by trigger strength (Event-driven above Structural), anchor quality (a sourced `[FACT]` anchor above an inferred one), and reachability. The deterministic gate FAILs a list whose developability bands are out of order, so the rubric actually reproduces the ordering rather than leaving it to the author's optimism.

The **structural-hook fence** (so trend fluff cannot return): a structural trigger must rest on **two company-specific, separately sourced facts whose tension is the hook**, both tagged `[FACT]`, with the inefficiency itself tagged `[INFERENCE]`. A single sourced fact plus a generalisation is a trend, not a structural hook, and is killed. A generic external trend with no company-specific sourced anchor never reaches the list; it goes to the watch-list.

## The inference fence (Stage 3.5 abductive bets)

The ranked list kills unsourced hypotheses, which is correct for client-facing angles. Stage 3.5 adds a separate, **quarantined inference block** that reasons abductively to the best explanation of the whole signal set, to surface an un-announced move (a new node, a relocation, a consolidation, a tenure change) while it is still invisible as a fact but its MOTIVE is already legible from facts in the evidence file. It is an internal thinking aid, never client-facing copy, and it runs at the orchestrator level on the FULL merged evidence set, including the low-signal "office-only" and pressure findings the per-agent and per-country logic otherwise discards (the motive is usually legible from the low-signal and pressure findings read together, not from either alone). Its generator is **unresolved tensions**: any cost, duty, capacity, risk or growth pressure in the evidence that has no current real-estate resolution is a candidate motive.

**Reason in two steps; do not leap to one answer.** A given tension almost always admits several responses, and which one is live is decided by the company's posture, not by the pressure alone.
- **Step 1, enumerate the move-types.** For each tension, list the real-estate responses it could resolve into, from a fixed menu: expand capacity; enter a new country; consolidate or merge duplicate sites; close a facility; exit a country; relocate; change tenure (sale-and-leaseback, or buy-versus-lease); swing between in-house and 3PL. Responses with NO European property consequence (re-source offshore, absorb the cost, insource without a building, or a move on another continent) are noted and then dropped, because they are not bets.
- **Step 2, gate by posture.** Read the company's posture from the evidence and let it SELECT which move-type is live. An additive posture (growing, acquisitive, cash-generative, adding range, capex-up) resolves a pressure by adding, entering and expanding; a defensive posture (distressed, shrinking, deleveraging, cost-cutting, margin-squeezed) resolves the SAME pressure by consolidating, closing, exiting or releasing tenure. Posture is itself the evidence that biases a tension toward one move-type over its opposite, so it must be named and cited. A mixed posture makes two move-types live at once, and the same facts should then carry TWO bets of different types (for example a post-merger consolidation bet AND a new-market entry bet), not one collapsed guess.

Only after the move-type is fixed does location come into play, and **every bet is a European move**; a nearshoring or new-node bet lands in a low-cost European country, never another continent. The output is therefore "what kind of move, gated by posture, and if additive then roughly where in Europe", each with its tripwire and its kill line. It will not always name the city, and that is honest.

**Deepen and decide (Step 3, bounded, still inference).** Once the move-type is chosen, each surviving candidate gets ONE targeted, bounded research pass that seeks more SOFT corroboration around that specific move (the tripwire's source classes plus context: an existing presence, hiring, incentive availability, a peer move, management commentary, developer activity). It is NOT a hunt for the confirming filing, and every fact it finds is written to the evidence file under normal hygiene (real source, native language, absence is a gap, Europe only). Each candidate then resolves one of three ways: **strengthen** (new independent sourced facts converge, so raise confidence and sharpen the shape, adding the facts to the bet's grounding); **drop** (a disconfirming signal appears, or it still cannot reach two independent sourced facts, so it is binned, never shipped at a lower confidence to keep it alive); or **promote** (a HARD, dated trigger has surfaced, so the move is no longer a bet, it leaves the block and becomes a ranked-angle candidate under the now-test and the developability rubric). If the pass surfaces nothing new and the bet already meets the two-fact floor with nothing disconfirming, it ships UNCHANGED at its existing (Low) confidence: what matters is that the pass was run, not that it necessarily firmed anything up, and a bet is never padded with weak corroboration to look firmer. A shipped bet's confidence reflects this deepen pass, and a bet never carries a hard dated trigger, that being by definition a ranked angle, not a bet.

A bet is not a sourced trigger and never enters the ranked list, but it is held to its own discipline so the block does not become a fantasy generator. A bet ships only with ALL of:
1. **Two-fact grounding.** At least two INDEPENDENT sourced facts already in the evidence file, cited by id. One fact plus a generalisation is killed, exactly as for a structural trigger; model knowledge not in the evidence is killed. An absence used as a grounding leg must be a sourced coverage finding (`EVIDENCE-ABSENT` after a real native-language search), never a bare not-found, and the move it implies stays `[INFERENCE]`.
2. **A written reasoning chain**, not an assertion: the logic joining the facts to the inferred move is shown so a reader can follow and challenge it.
3. **A European real-estate consequence:** the inferred move implies a building, a site, a network change or a tenure decision IN EUROPE. A pure strategy guess with no property consequence, or one whose property consequence sits on another continent, is out of scope for a bet.
4. **A named public tripwire:** the single most likely public signal that would confirm the bet, mapped to a source class the harvest already watches (an investment-incentive or zone register, a planning or permit portal, a company or statutory-registry filing, clustered hiring, developer or contractor PR).
5. **A disconfirming line:** the evidence or event that would kill the bet, stated plainly, so the pass cannot indulge motivated reasoning.
6. **Epistemic labelling:** the bet is tagged `[INFERENCE]` or `[ASSUMPTION]`; the facts under it keep their `[FACT]` tags.
7. **A stated move-type and posture (the two-step reasoning made visible).** The bet names its move-type from the menu above and the posture read (additive / defensive / mixed, from cited facts) that makes THAT move-type live rather than its opposite. A bet that leaps to one response without showing the posture that selects it, or that names a move-type not on the menu, is killed.

**Hard cap of four; zero is a valid outcome** (fewer, sharper bets beat a speculative list). Quarantine: a bet never merges into `## Angles`, is never scored for developability, never given a Readiness label, never counted toward the ranked ceiling, and never appears in the at-a-glance table; it is exempt from the send-now and structural-fence gate checks because it is explicitly not a sourced trigger. The value of a bet is not the guess, it is the **tripwire** that tells the broker what to watch; most bets sit at Low confidence, which is correct, not a weakness.

## The evidence file (internal working artefact)

Each harvest agent **returns** its findings as a prefixed block (A/B/C); the **orchestrator is the only writer** of this file. It merges the three returned blocks into one markdown table or JSON-lines file, one row per finding, deduping near-identical claims and resolving conflicts (filing beats press). The author and reviewer read from this single file; nothing else is the source of truth. The agent prefix in `id` (`A1`, `B3`, `C2`) exists precisely so three independently-numbered blocks concatenate without collision. Context-isolated subagents cannot co-write a shared file, so they never touch it; they hand structured text back and the orchestrator does the single write. Fields:

| field | meaning |
| --- | --- |
| `id` | short id, agent-prefixed, e.g. `A1`, `B3`, `C2` |
| `agent` | A, B or C |
| `claim` | the finding in one line |
| `value_as_found` | the verbatim figure/quote/date, in its source language, never rounded or converted |
| `source_title` | page or document title |
| `source_url` | retrievable URL (or registry reference) |
| `source_type` | primary filing / IR / earnings transcript / company press / trade press / job board / planning portal / rating agency / registry / rumour |
| `publication_date` | ISO `YYYY-MM-DD` of publication, or the event/forcing-function date |
| `access_date` | ISO `YYYY-MM-DD` the agent retrieved it |
| `recency_grade` | live / ageing / background, computed against the run date |
| `fia_tag` | FACT / INFERENCE / ASSUMPTION |
| `notes` | conflicts, corroboration, or why a gap |

Synthetic example rows (illustrative only):

```
| id | agent | claim | value_as_found | source_title | source_url | source_type | publication_date | access_date | recency_grade | fia_tag | notes |
| A1 | A | New CSCO appointed | "appointed Chief Supply Chain Officer effective 1 May 2026" | Co. newsroom | https://example.com/pr | company press | 2026-05-01 | 2026-06-25 | live | FACT | corroborated on LinkedIn |
| A2 | A | DC manager role, market with no current site | "Distribution Centre Manager, Venlo" | LinkedIn Jobs | https://example.com/job | job board | 2026-06-10 | 2026-06-25 | live | FACT | no known site in Venlo |
| B1 | B | Automation named in Q&A | "we are accelerating automation capex" (analyst Q&A) | FY25 earnings transcript | https://example.com/tx | earnings transcript | 2026-05-20 | 2026-06-25 | live | FACT | prepared remarks did not mention it |
```

## The Source Ledger (deliverable, ships with the sheet)

The broker-facing subset of the evidence file: every claim that actually appears on the sheet, so any line can be defended in the call or the email. One row per cited claim, grouped by item. Fields: `angle_ref` (the ranked item number or watch-list), `claim_as_stated` (as written on the sheet), `value_as_found` (verbatim), `source_title`, `source_url`, `date` (publication or event), `access_date`, `recency_grade`, `fia_tag`. Deliver it alongside the sheet (a short markdown table is fine).

## Re-retrieval and paywall protocol (reviewer, Stage 5)

Facility counts, floor areas and financial figures are the highest-risk hallucination fields and precisely the homework-done facts that detonate credibility if wrong. They are **retrieved, never recalled**. But re-fetching is not free, and the rate-limited portals the harvest already hit are the ones the reviewer would hit again, so re-retrieval is **scoped, not exhaustive**.

**Re-retrieve only the load-bearing numbers:** the trigger (the dated event, or the dated facts behind a structural tension) of every kept item, plus any anchor figure an opener leans on (a facility count, an area, a financial value). Background and colour numbers are not re-fetched. **Hard cap: about five reviewer fetches per sheet.** If the load-bearing set exceeds the cap, re-fetch the trigger dates first.

For each load-bearing number the reviewer re-opens the `source_url`:
- **Resolves and matches** -> confirmed.
- **Resolves but differs** -> correct the sheet to the source value and note the change.
- **Does not resolve (404, moved, cannot reach)** -> strike the number. The item stands without it or falls.
- **Paywalled original** -> retain only if a free source corroborates the same figure; otherwise strike or demote the item.
- **Rate-limited or unreachable within budget** -> mark the figure `unverified`. An `unverified` figure is never presented as confirmed; an item carrying one cannot be labelled **send-now** (it is verify-first at best), and **if it is the item's anchor trigger and cannot be resolved at all, the item is demoted to the watch-list, not shipped.** A sheet must not present an unverified forcing function as live.

## Counts and footprint figures (no undercounting)

A facility or site count is a load-bearing number with a failure mode beyond fabrication: **incompleteness**. Reporting one warehouse for a company that runs four destroys credibility exactly as a fabricated figure would, and it is the easy mistake because the first source you hit rarely lists them all.
- **Never report a count from a single source.** Corroborate against at least two independent sources (see the footprint-completeness procedure in `source-playbook.md`), or state it as a floor: "at least N sites identified", with the named sites listed.
- **Enumerate, do not just total.** The Source Ledger carries the named sites behind any count, so the broker can see what the number rests on and the reviewer can re-check it.
- **A discrepancy is a signal, not a rounding choice.** If one source says one site and another implies four, do not take the lower number; resolve it by searching deeper. The disagreement often points to a recent opening or a 3PL-run site, which may itself be the live trigger (or the basis of a structural one).
- **Footprint completeness is all-Europe coverage, carried as a token.** Checking that the sites you listed are real is not the same as checking you searched everywhere a facility could be. The control is **coverage of every country in the active European set** (the all-Europe facility-evidence fan-out in `source-playbook.md`), NEVER the company's sales geography and NEVER a company-stated DC total (that total is only a corroborating cross-check inside positive countries). Emit a `## European footprint coverage map` (one row per country in the set: `EVIDENCE-POSITIVE` with source, `EVIDENCE-ABSENT` after a real native-language search, or `INCONCLUSIVE`) into the evidence file and the Source Ledger, then a status line: `RECONCILIATION: RECONCILED` only when every country resolves to positive-with-source or absent-after-a-real-native-language-search with zero `INCONCLUSIVE`, otherwise `RECONCILIATION: UNRESOLVED GAP`. `UNRESOLVED GAP` is the normal state for a large occupier and is **non-blocking for shipping opportunities**: it blocks only saturation or complete-network LANGUAGE on the sheet, never the ranked list. An empty search is never a "no facility" finding, and a residual is never back-filled with legacy or assumed sites.

## The chase list (clear before authoring)

A harvest agent often **locates** a high-value source it does not fully open: a filing flagged "pull if possible", an event noted as "announced on a date, verify", a pointer to a document it did not fetch. Left there, the freshest, most decision-relevant evidence is found and then silently dropped. To stop that, the orchestrator keeps a **chase list** and clears it before the author pass.

- The orchestrator writes a `## Chase list` block in the evidence file. Every returned finding carrying `pull if possible`, `verify`, or a `pointer not opened` flag becomes one chase item, one line each.
- **Each chase item must be resolved before authoring**, with one of exactly two outcomes:
  - **resolved** -> the source was opened or fetched and its dated value written into the evidence file as a normal finding row; mark the chase line `resolved` and reference the new row id.
  - **gap** -> it genuinely could not be retrieved within budget; mark the chase line `gap:` with the reason. A logged gap is honest and allowed; an unresolved pointer is not.
- **No unopened pointer may survive into the author pass.** When the chase list is clear, no line still reads `pull if possible` or `pointer not opened`; every line reads `resolved` or `gap:`. The deterministic gate enforces this when handed the evidence file (see below).
- For a private or PE-backed target, the **parent-group consolidated filing is a required chase item** (see the private branch in `source-playbook.md`), because for these firms it is frequently the freshest primary live financial source and is exactly the pointer that gets dropped.

The gate (`helpers/final_gate.py`) can be run with `--evidence <evidence.md>`; it **FAILs** if the evidence file still contains an unresolved chase token (a `pull if possible` or `pointer not opened` line not yet marked `resolved` or `gap:`). This makes the chase-clear a blocking, mechanical precondition, not a described intention.

## Degraded mode (retrieval fails mid-run)

If web retrieval becomes unavailable or unusable partway through (rate limits, blocked tools, dead portals), do not paper over it. Mark every claim that could not be retrieved or re-retrieved as `unverified`, demote any item whose anchor is unverified, and if the live, verified evidence no longer supports a single opportunity, return the sheet as "do not call / could not verify" with the watch-list. Never backfill a missing source from memory to keep an item alive. (The Stage 0 capability precondition stops a run that has no retrieval at all; this rule covers a run that loses it midway.)

## Peer-pattern grounding rule

The opener's peer pattern is the product's differentiator and its single biggest hallucination risk, because the evidence rule above guards figures and dated facts but a *pattern* is a generalisation. It applies equally to the email hook and the call opener. A peer pattern asserted in an opener must be either:
- **(a) grounded** in at least one cited real example in the evidence file, or
- **(b) framed explicitly as CBRE's observed experience or a hypothesis to test** ("in our experience", "we often see", "worth testing whether"), never as a fabricated statistic.

An invented quantified pattern ("most omnichannel retailers consolidate to three DCs within eighteen months of a new CSCO") is a hallucination and is struck, exactly like an invented figure.

## Reviewer gate checklist (Stage 5)

The isolated reviewer confirms each of these and returns a verdict per item (PASS, FIX, or KILL), plus an overall sheet verdict that may be "do not call":

1. Every cited source resolves and every date is current; ageing evidence is flagged (verify-first), background is not presented as live.
2. Every **load-bearing** number (the trigger and any anchor figure) has been independently re-retrieved per the scoped protocol above; any unverified anchor has demoted its item or forced a verify-first label.
2b. **Source quality of the anchor.** A load-bearing anchor figure or fact cites a **primary source** (company filing, IR, RNS, results release, statutory register) OR carries a **second corroborating ledger row** for the same claim. A figure cited only to a data aggregator (finance.yahoo.com, investing.com, marketscreener, simplywall.st, and the like) is fixed to a primary source or demoted; a senior operator will not respect a Yahoo-sourced net-debt figure, and aggregators also 404 and then trip the re-retrieval strike rule. The gate raises an advisory WARN when a ledger row cites a known aggregator host, as a prompt to corroborate.
3. Fact, inference and assumption are correctly labelled; no inference is stated as fact.
4. Every item has a valid trigger: either a dated forcing function (**Event-driven**) or a **properly fenced Structural** inefficiency (two company-specific, separately sourced `[FACT]`s and the inferred tension `[INFERENCE]` between them). KILL any item resting on a generic undated trend with no company-specific sourced anchor; send a real-but-not-yet-developable signal to the watch-list.
5. Each opener (email hook and call opener) leads with a peer pattern or a non-obvious constraint, not a fact the company obviously already knows about itself. KILL any opener whose only content is "your capex is up X". The peer pattern obeys the grounding rule above.
5b. The **email hook is a pasteable draft**, three sentences the broker could send verbatim, not a description of what to write ("reference their capex" is a FAIL; "Saw your February guidance to more than double growth capex into the ConvaFoam and Esteem lines" is a pass). On a **Verify-first** item, the first line is built ONLY from `[FACT]`s and the unverified fact appears in the soft ask phrased as a QUESTION, never asserted as true; KILL a Verify-first hook that states an `[INFERENCE]` as fact.
6. Each item clears the specificity bar: a concrete trigger (a date or two sourced structural facts) and a concrete building or network consequence, not a generality.
7. The stakeholder concern is tied to evidence and remit, and labelled as an inference.
8. Nothing contradicts the broker's known context.
9. Any site or facility count is corroborated by at least two independent sources or stated as a floor with the sites enumerated; no single-source count is presented as definitive. If the count looks thin for a company of this size, send it back for a deeper footprint sweep rather than shipping it.
10. No item rests on an unsourced absence. Search-emptiness is a gap; a non-existence claim must be positively sourced. KILL any item whose thesis depends on a not-found.
11. The European coverage map covers every country in the active set; each is `EVIDENCE-POSITIVE` (with source) or `EVIDENCE-ABSENT` after a real native-language search (spot-check that the verbatim local-language queries actually ran); any `INCONCLUSIVE` is a counted gap, not a pass.
12. Right-angle / attribution: each item's trigger belongs to THIS legal entity (not a namesake, not a 3PL's spec build) and actually implies the claimed real-estate consequence. KILL true-but-mis-attributed items.
13. Two-axis discipline, scored to the rubric. The list is ranked by **developability**, not freshness: a high-developability item with a weak or structural trigger is not demoted for lacking a date. Confirm the **developability band follows the rubric** above: both sub-factors (scale and near-term likelihood) are STATED on the Developability line, and the **anchor-quality cap** is applied, meaning an item whose anchor fact is `[INFERENCE]`/`[ASSUMPTION]` (for example an unconfirmed freehold) is capped at Medium and cannot lead the sheet on scale alone. Confirm the list is in **non-increasing band order** (High, then Medium, then Low). Check the **readiness** label is correct (send-now only when the trigger is dated/live, its Trigger line carries a `[FACT]`, and the load-bearing facts re-retrieve; otherwise verify-first naming the one fact to confirm) and that a **Structural** trigger really rests on two separately-sourced `[FACT]`s plus the inferred tension on its Trigger line. A sourced-but-not-yet-developable signal goes to the watch-list; KILL is reserved for the unsound (generic trend, unsourced not-found, mis-attribution). The list may be empty, but the watch-list and the dated event that would activate each line still ship.
13b. **Inferred ownership is not framed as owned.** When an item's anchor is an *unconfirmed* ownership (a freehold inferred, not sourced, as in "the buyer may be a group vehicle"), its title and its at-a-glance line state the OPEN QUESTION ("confirm ownership, then a sale-and-leaseback"), never assert "the owned warehouse". Such an item cannot be Send-now, and if the balance of sourced evidence actually points AWAY from ownership (for example a build-to-suit that was sold to a third-party investor), the reviewer demotes or watch-lists it rather than letting a probable dead end hold a ranked slot. The body may still explore the hypothesis; the headline may not presume it.
14. **Inference block (Stage 3.5, if present).** Each bet cites at least two independent `[FACT]`s from the evidence file, shows its reasoning chain, names its **move-type** (from the menu) and the **posture** (additive / defensive / mixed, from cited facts) that selects it, implies a **European** real-estate move, and names a real public tripwire and a disconfirming line, tagged `[INFERENCE]`/`[ASSUMPTION]`. KILL any bet resting on a single fact, on model knowledge not in the evidence, without a disconfirming line, whose property consequence is outside Europe or absent, or that leaps to one response without showing the posture that selects it. Where a tension admits two posture-consistent move-types (for example consolidation AND entry), confirm BOTH are carried as separate bets rather than collapsed into one. Confirm each shipped bet went through the bounded **deepen pass** (the pass was RUN; a null result is a valid outcome and a bet is never padded with weak corroboration to look firmer; its confidence reflects only what actually firmed up), that NO bet carries a hard dated trigger (such a move is promoted to a ranked angle, never hidden here), and that dropped or promoted candidates are not left lingering in the block. Confirm the block is NOT merged into the ranked list, its bets carry no developability or readiness label and are not in the at-a-glance table, it is marked internal (not client-facing), and there are at most four bets (zero is fine).

## Completeness falsification pass (Stage 5, second cheap reviewer job)

The checklist above verifies that what is on the sheet is TRUE. This pass verifies that the set is COMPLETE, and it is a distinct discipline: its only job is to FALSIFY completeness, not to confirm accuracy. It is cheap and it always runs, even when every item already passes. It works from the reconciliation block already in the evidence file rather than re-running the harvest; any fetch it needs counts against the same scoped re-retrieval budget above. The reviewer:

1. **Reconciles against all-Europe coverage.** Confirms the European coverage map covers every country in the active set, each resolved to `EVIDENCE-POSITIVE` (with source) or `EVIDENCE-ABSENT` after a real native-language search; any `INCONCLUSIVE` country is an `UNRESOLVED GAP`, not a pass. A company-stated DC total is only a cross-check, never the control.
2. **Names the obvious absence off the coverage map.** Names any country, or facility type such as production, that a company of this size and model plausibly operates but where the map is absent or inconclusive, and returns it as a gap to chase. This gives the pass teeth without a stated total, because it is anchored on geographic coverage rather than a number the company chose to publish. A facility surfaced in a non-sales country is an opportunity (a structural new-market or nearshoring hook), not a completeness table row.
3. **Kills inference from absence.** KILLs any item whose thesis rests on a not-found that is not positively sourced; "no site found" is a gap, not a finding.
4. **Sanity-checks against scale.** A multi-country network of many stores almost never runs from a single DC; a wide mismatch between footprint scale (store or country count) and DCs found forces a deeper sweep before anything ships (and a confirmed single-hub model at scale is itself a strong structural opportunity).
5. **Blocks closure language while a gap is open.** If any reconciliation status is `UNRESOLVED GAP`, the reviewer KILLs any claim of saturation, a complete network or a full footprint, and ensures the carried status line on the sheet or ledger reads `RECONCILIATION: UNRESOLVED GAP` so the deterministic gate also blocks it. Closure language may ship only when the reconciliation reads `RECONCILED`.

HARD STOP: if any item rests on a figure or event the reviewer cannot resolve to a real source, that item is killed, not softened.

## Bounded loop (no endless re-review)

The reviewer never edits the item in place; it returns verdicts and the orchestrator fixes and re-runs with a fresh reviewer. The loop is bounded so a stubborn reviewer cannot spin:

- **At most one fix-and-recheck cycle per item.** A FIX verdict earns the item exactly one repair, then a single recheck by a fresh reviewer.
- **Still failing after its fix -> KILL.** An item that does not clear on the recheck is dropped, not repaired again. It may move to the watch-list if its trigger is real but not yet usable.
- **Never loosen a criterion to force a pass.** If the only way to pass an item is to relax the trigger fence, the evidence rule, the attribution check or the peer-pattern rule, it does not pass: send it to the watch-list if it is sourced-but-not-yet-developable, KILL it if it is unsound. Fear manufactured certainty, not a weak date on a real opportunity.
- **The loop is additive, not only subtractive.** After pruning, if not every angle family was walked and logged, run ONE more generation pass over unused evidence and unwalked families. New sourced, developable opportunities join the ranked list in developability order (never padded to a number); sourced-but-not-yet-developable signals go to the watch-list. Keep the one-fix-then-KILL discipline.
- **Record the re-run count** in the run notes. If the ranked list ends empty, return "do not call yet" but still ship the watch-list and the dated event that would activate each line; a zero-item run is never an empty page.
