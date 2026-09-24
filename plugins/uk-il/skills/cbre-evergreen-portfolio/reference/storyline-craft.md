# Storyline craft: an Apple-grade scroll story, in CBRE's voice

The storyline is an **argument**, not a tour of the data. A property director or
CFO scrolls it once, in three to five minutes, often on a meeting-room screen.
They should leave with the **spine** (one sentence), the two or three facts
that prove it, and the **first move**.

"Apple-grade" means one idea per screen, very large confident type, a lot of
silence around it, motion that reveals the structure of the data, and nothing
on screen that isn't pulling weight. "CBRE" means the greens and the three
faces (design-system.md), the voice (clear, bold, connected), and evidence and
provenance on every screen.

The analysis (what is true, what matters) comes from the brief and
the ledger (insight-playbook.md). This file is about how to **tell** it.

---

## 1. The scene grammar: one claim per scene

Every scene makes exactly one claim and is built from four parts, in this order:

1. **Headline**: one sentence carrying a number (or a named thing) and a
   consequence. Scene headline size, at most three lines at 1440px.
2. **Evidence paragraph**: 40–80 words. Carries the denominators, names the
   specific building, landlord, year and sq ft, and ends on the consequence or
   the lever. Bold (weight 500) the one to three figures the reader should
   remember, and nothing else.
3. **One visual that proves the headline.** A reader who skips the paragraph
   should still *see* the claim. If the visual needs the paragraph to make
   sense, it is the wrong visual.
4. **Provenance line**: `EverGreen export · <date> · <denominator>`. The
   denominator says which units the visual covers ("the 23 leased units with
   a recorded expiry").

Optional extras: an **aside** (one sentence, the caveat or the "so what", at the
aside step), and a **Rows drawer** (the units behind the claim, one click away,
so the claim is auditable in place).

**Layouts that work**

| Layout | When |
|---|---|
| Statement: headline only, huge, lots of ground | the turn in the argument; the closing |
| Two-column: text left, visual right (or the reverse for variety) | a map, a constellation, a grid; anything squarish |
| Full-width evidence: headline + paragraph on top, a wide chart below | time series, treemaps, anything wide |
| Hero numeral: one number as the image, caption, provenance | one decisive building or quantity |
| Pinned sequence: static text, and a visual that evolves with scroll | a transformation the reader must watch (§5) |

Each scene also gets a **rail label**: two or three words naming the chapter
("Four landlords", "The cliff year", "What we don't know"). It is not the headline.

## 2. Headlines for an occupier client

**The test:** would this sentence work alone as the title of a board-pack page,
and could it be said of any other client? If it could, rewrite it.

Rules:
- **A sentence, not a label.** Its subject is the client's estate or the
  client's decision.
- **A number and a consequence.** Two beats work well: the fact, then what it
  means. "Four landlords hold half of what you rent. That is four
  conversations, and four counterparties' risk."
- **Plain English.** "Years left on the leases", not WAULT. "Agreed with the
  existing landlord" before you say "regear". No OMRR, BTS or GIA in a headline.
- **The occupier's point of view.** A landlord's legal obligation is written as
  the occupier's **leverage** ("the upgrade belongs in the renewal").
- **Numbers:** use words for small round numbers in headlines ("Nine
  buildings…"), digits in paragraphs. Don't claim more precision than the
  point needs: "just over seven years" or "7.4 years", not "6.83 years" in a
  headline. A word-number is still a ledger figure. Derive it; never type it.
- **Rounding words are claims too:** "about" means within ±2 points, "nearly"
  means just below, "well over half" means above 55%, "most" means over 50% of
  the stated base.
- **Regulation keeps its status word:** "is set to need", not "must have"
  (uk-rules.md).
- **Never:** Overview, Key insights, Summary, At a glance, Snapshot, Deep dive,
  Introduction, Analysis, Findings, "A closer look at…", label-colon headlines
  ("Expiries: the picture"), rhetorical questions, exclamation marks. Avoid
  robust, diverse, strategic, holistic, landscape, journey, unlock, "leverage"
  as a verb, and "key" as an adjective.

**Rewrites** (illustrative numbers):

| Weak | Strong |
|---|---|
| Lease expiry profile | A third of the floorspace falls due in the next four years. |
| Landlord overview | Four landlords control half of what you rent. |
| EPC coverage | Most of the leased estate has no EPC on record, so no one can say it will pass. |
| Rent analysis | Your oldest deals are your cheapest, and their reviews are coming. |
| Portfolio snapshot | Forty-four buildings, nine million square feet, and a quarter of it on one road. |
| Data quality | We can price 40% of the floorspace. The rest is a question, not a zero. |

## 3. Evidence paragraphs

- Every aggregate carries its base: "rent is recorded on **23 of 51** units".
- Name the specific: the building and town, the landlord, the year. Specific
  beats general every time.
- One caveat at most, and put it in the aside rather than hedging every clause.
- End on the consequence or the lever ("Run it as one negotiation.").
- Every figure is computed at run time from `Story.units` exactly as its ledger
  row says, or is a ledger constant with the ledger id in a comment. Named
  examples are **looked up** (`units.find(...)`), never transcribed. Prose that
  can't drift from the export is the only prose that survives QA.

## 4. Pacing and ground

- **8–12 scenes**, roughly 20–25 viewports of scroll in total. Rhythm: statement
  → evidence → evidence → a turn → evidence → hero → the gap → the action.
- **Grounds:** open dark, and make the first evidence scene light. After that
  alternate **by content**: dark for statements and hero numerals, light for
  anything that needs reading (dense charts, grids, tables). Use deep for a
  single decisive fact and midnight once or twice for a change of register.
  At most two consecutive scenes share a ground, unless they are one argument
  in two steps.
- **Pinned scenes:** two to four per storyline, and **never more than two in a
  row**. Put a static scene between long pins so the reader gets to scroll
  freely again.
- **Silence is a material.** A scene with a headline and nothing else is allowed
  once, at the turn. It makes the next scene land.

## 5. When to pin, and how

**Pin** when the visual changes *meaning* as the reader scrolls: a zoom into a
cluster, bars rising and then one year lifting, a grid filling in passes that
refuse to finish, a treemap whose tail recedes so the top holders stand out.
**Don't pin** a static chart, a statement, a table, or anything that can't fit
1280×600 under the bar even at its minimum height.

Mechanics (engine `PinnedScene`, `useFitHeight`):
- 3–4 viewports of scroll. The text (headline, paragraph) is **static** at the
  top of the stage. Only the visual evolves.
- Map progress to phases: start building at about 0.05, finish the main build
  by about 0.6, bring in emphasis between 0.55 and 0.9, and **hold the finished
  state for the last 10–15%** so the reader has time to read it.
- Charts that can change aspect take their height from `useFitHeight` (min and
  max heights). Width, and so type size, never changes. `align-items: safe
  center` means that if something must overflow, it overflows at the foot and
  never pushes the headline under the app bar.
- At ≤820px pins become ordinary stacked scenes, so **the finished state must
  make sense on its own.** Reduced motion shows the finished state too.
- Fit is tested at 1536×730, 1366×768 and 1280×600, at three progress points
  (qa-visual.md).

## 6. Hero numerals

- At most one per scene and two per storyline. Use one only when **the size of
  the number is itself the point**: the largest building, the cliff year's
  floorspace, the count of unrated leases. Never "44 units" for its own sake.
- Put the unit beneath as a mono label, not hung off the baseline like a metric
  card. Add an accent bar, then a caption (what, where, which company,
  landlord, the consequence), then provenance ("1 of 44 units").
- The counter runs from 62% to 100%, linked to scroll. Reduced motion shows the
  final value.

## 7. Opening and closing

**Opening** (first viewport, readable at 1440×900 without scrolling):
- The **spine** in one sentence at opening size. The tension clause is in `em`
  (accent).
- The sub-line gives the estate in one line (units, sq ft, operating
  companies, owned count), followed by provenance "N of N units".
- The visual is the whole estate (map or constellation) **with its key**. The
  reader must not meet an encoded chart a scene before its legend.

**Closing:**
- Closing size, and it lands harder than the opening: "The next three years
  decide what this estate costs."
- One paragraph that joins the two or three threads into one plan: "These are
  not separate problems. They are one negotiation."
- **One instruction** in Financier and accent, naming the first move ("Start
  with the two leases at X Park."). Then one supporting line of numbers.
- The CTA "Open the portfolio dashboard →" calls `Story.setView('dash')`.
- After the closing come the appendix (every unit, `n/r` and `—` explained,
  sorted by size) and a footer that says how every figure was computed and
  what was *not* extrapolated.

## 8. Honesty rules (QA fails the build on these)

- Every aggregate states its denominator, and every visual's provenance says
  what it covers.
- **"Not recorded" is a finding.** If gaps are material, give them a scene
  (coverage grid, "questions we can answer for you"). Never fill them, and
  never show them as zero.
- **Never extrapolate a subset** (a rent roll, an EPC share) to the estate.
  Say "on the N units that record it".
- A past expiry date means holding over, an unrecorded regear or a vacated
  unit, **not** "an expired lease" (uk-rules.md §2).
- Landlord concentration uses **leased units only**. EverGreen leaves landlord
  values on owned freeholds, and including them once overstated concentration
  and contradicted the page's own table. Say "leased units only"
  in the provenance.
- Regulatory statements come only from uk-rules.md, **with their status**.
  Stating an outdated MEES deadline as law is the canonical failure.
- Placeholder dates (1950-01-01, 1905-06-01) are nulls. They never reach a
  timeline, an axis or a sentence.
- Duplicate unit names are disambiguated wherever units are listed (name plus
  town, or unit ID).
- The storyline and the dashboard must say the same thing about the same fact:
  same number, same denominator, same wording of status.

## 9. Motion direction for scenes

- One **authored moment** per scene: the one move that shows the claim (a year
  lifts, a cluster zooms, the tail recedes, cells fill in three passes and stop
  short). Everything else holds still. More moves make a scene louder, not
  better.
- Text blocks arrive once (a Reveal per block, never per line).
- Colour change **is** the emphasis. Motion supports it and never decorates.
- Scales and gridlines never move. Value labels ride on their marks.
- New motion ideas are welcome if they pass three tests. Removing the motion
  would lose meaning. The end state is complete without it. It works at 390px
  unpinned.

## 10. Scene-idea bank: beyond the reference

The reference storyline used these: the estate as a constellation with a
company key, floorspace by operating company, a regional cluster zoom, owned
against leased, a landlord treemap, an expiry timeline with one year lifted, a
data-coverage grid, a capability map, an EPC stacked bar, and a single-building
hero with a rent scatter. **Do not default to that set.** Choose what this
portfolio's spine needs, and invent. For each idea below: the claim it makes,
the form, the fields it needs (canonical names), whether to pin it, and the trap.

| # | Idea | Claim shape | Form | Needs | Pin? | Trap |
|---|---|---|---|---|---|---|
| 1 | The next 24 months | "Nine decisions fall due before the next budget cycle." | Month strip from as-at date; ticks for expiries, breaks and reviews, sized by sq ft; a now-line | `expiry`, `breakDate`, `rentReview`, `size` | yes: the window slides | Break **notice** dates are not in the data. Say "notice depends on the lease" |
| 2 | Bundle the negotiations | "Three leases, one landlord, three years: run them as one." | Landlord (leased only) × year matrix, dots sized by sq ft, rows with ≥2 events in 3 years lifted | `landlord`, `owned`, `expiryYear`, `size` | yes: rows light up | Freeholds excluded. Intra-group landlords shown separately |
| 3 | Hardest to replace fall due first | "Your least replaceable sites have the shortest leases." | Scatter: years to expiry × capability count, bubble = sq ft, the top-left quadrant named | spec flags (`coldStore`, `eaves`, `dockDoors`, `yard`, `power`, `rail`) + `yearsToExpiry` | optional | Flags are sparse. Plot only units with flags recorded and print that count |
| 4 | The reversion ladder | "Every £1 psf on your three oldest deals is £1.6m a year." | Horizontal bars from each passing rent to the most recent rent in the same portfolio, sorted by £ pa sensitivity | `rent`, `dealYear`, `size` | no | It is arithmetic on the client's own rents, not a market forecast. Recorded rents only |
| 5 | The freehold as capital | "Twelve buildings you own outright: 2.1m sq ft with no renewal date." | Map or ranked bars of owned units by size and age | `owned`, `size`, `quality`/`pcYear`, `region` | no | No valuations. Sale-and-leaseback is "an option to consider", never advice |
| 6 | One landlord owns the park | "At X Park one landlord controls your whole presence." | Small multiples per multi-unit park, units coloured by landlord | `park`, `landlord`, `size` | no | Only parks with ≥2 units. Say how many units have `park` recorded |
| 7 | The average hides the cliff | "The average lease has seven years. Half the floorspace has under three." | Strip or beeswarm of years to expiry (dot area = sq ft) with the average line | `yearsToExpiry`, `size`, `expired` | yes: the mean line lands, then the mass | Lapsed and undated leases shown apart, not dropped silently |
| 8 | Old sheds, short leases | "A million sq ft is pre-2010 stock on leases ending by 2030: relocate or invest." | Quality stack by floorspace, crossed with expiry window | `quality`, `pcYear`, `size`, `expiryYear` | optional | `quality` wording varies by export. Map it in data-notes first |
| 9 | Stale records on live decisions | "Five of the leases ending soonest haven't been updated in two years." | Timeline of `updated` per unit, coloured by whether an event falls in the next 3 years | `updated`, `updatedBy`, `expiry` | no | A statement about the record, not about the building |
| 10 | Fitness for throughput | "Four large sites have half the doors per sq ft of the rest." | Dot plot of sq ft per dock door, portfolio median as the reference | `doorRatio`, `dockDoors`, `size` | no | The median is the client's own, not a market benchmark. Print coverage |
| 11 | One road carries the estate | "A quarter of the floorspace sits on one motorway." | Corridor ribbons (M1, M6…), length ∝ sq ft, units as ticks | `corridor`, `size` | yes: corridors draw in turn | `corridor` is free text. Normalise before counting |
| 12 | Which businesses own, which rent | "The two largest companies sit almost entirely on short leases." | Stacked bars per operating company: owned, leased, regeared, by sq ft | `group`, `owned`, `tenure`, `size` | no | Fewer than 3 companies? Fold this into another scene |
| 13 | Holding over | "Four expiry dates have already passed. Each is a lease to confirm." | List or timeline of past expiries with years since, and landlord | `expiry`, `expired`, `landlord` | no | uk-rules.md §2: never "expired leases" |
| 14 | MEES meets the lease | "Four sub-B buildings have leases ending before 2031: the upgrade belongs in those renewals." | One line per in-scope unit: lease end marker against the 2031 line, coloured by band | `epc`, `expiry`, `size`, `region`, `owned` | yes: the 2031 line arrives | Scope first (leased, England/Wales, >1,000 m²). "Set to", not "must" |
| 15 | The rent roll we can see | "£12m a year is recorded. The rest of the estate has no rent on file." | Two-part bar: priced £ pa against unpriced sq ft (hatched) | `rent`, `size` | no | Never gross up. The hatched part is sq ft, not £ |
| 16 | Dependence on the largest | "The five largest buildings are 40% of everything." | Pareto: units sorted by size, cumulative line, the top n labelled | `size`, `name`, `town` | optional | Label the largest by name (disambiguate duplicates) |
| 17 | Network redundancy | "Three of your four largest sites are within 30 miles of each other." | Map with radius rings around the largest sites, computed distance | `lat`, `lng`, `size` | yes: rings grow | Straight-line distance only. No drive times (not in data) |
| 18 | Breaks as leverage | "Two breaks in the next three years are worth a conversation before they're a decision." | Breaks on a timeline with landlord and sq ft | `breakDate`, `landlord`, `size` | no | Conditions and notice periods are lease-specific. Say so |
| 19 | Where each business sits | "Each operating company has its own map, and they barely overlap." | Small-multiple mini-maps, one per company (≤8) | `group`, `lat`, `lng`, `size` | no | Keep the same projection and scale across the multiples |
| 20 | The gap list is a work plan | "Eleven fields, forty-four buildings: here is what we will find out for you." | Field × unit matrix, recorded against not, sorted by floorspace, with a CTA to CBRE | `completeness` + field fill rates | yes: fills in passes | Tone: commercial offer, not blame |

**Building a NEW scene.** Declare these in the brief before building. The claim.
What each visual element encodes. The one move. The finished state (the
reduced-motion render). Its minimum and maximum height, whether it is pinned.
Its 390px form. A computed `aria-label`. Build it from the kit (`Scene`,
`PinnedScene`, `Reveal`, `Prov`, `Rows`, `useFitHeight`) and the chart
conventions in design-system.md §7, to the same finish as the library.
Then run `scripts/qa_audit.js` on it at 1536×730 and 390×844 before handing
over.

## 11. Common storyline failures

- A scene that describes ("The estate is spread across eight regions") instead
  of claiming.
- Two claims in one scene. Split it, or cut the weaker one.
- A visual that repeats the paragraph as a chart without adding shape (a bar
  chart of three numbers already in the sentence).
- Every scene pinned, or every scene with the same reveal.
- An encoded chart whose key arrives later.
- A light scene painted on the dark ground (stacking context), or text that
  hard-swaps colour before the ground finishes fading.
- A closing that summarises instead of instructing, with no single first move.
- Hand-typed numbers in headlines that drift from the data after a re-run.
