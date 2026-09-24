# Dashboard craft: five seconds to understand, five minutes to explore

The storyline **argues**. The dashboard lets the reader **check and explore**:
find "my building", answer a board question, verify a number they just read.
The visitor is operating a tool, so scanability, consistency and familiar
controls outrank expression. The brand lives in the details (design-system.md),
not in decoration.

**The five-second test.** Show someone the first viewport for five seconds. They
should be able to say whose estate it is, how big it is, the one tension in it,
and where to click next. If they can't, fix the lede or the KPI labels before
anything else.

---

## 1. Page order and hierarchy

Default order (change it when the brief's spine demands, e.g. a
compliance-led portfolio puts the EPC panel before rent):

1. **Title band:** h1 client name with the estate as its second line (sage,
   large only). Then a **lede**, one or two sentences with bolded figures that
   state the tension. Then a meta line: source and date, record and field
   count, "landlord and tenant fields unverified at source" if so.
2. **KPI band** (dark ground), 4–6 tiles.
3. **Sticky filter bar** with the live readout.
4. **Map** with legend, size key and region list.
5. **Time:** lease events.
6. **Panels:** the 2–3 questions that matter for this client (rent, control,
   compliance, capability…).
7. **Five findings**, each with an action.
8. **Every unit:** the table.
9. **Footer:** method, denominators, what was not extrapolated.

- One h1. Each section gets an h2 with a note beside it, aligned on the
  **baseline**. Box-bottom alignment left the note 13–19px off the heading.
- Every panel answers **one question**, and its h3 names that question in plain
  words ("When the leases move", "Who controls the estate"). Under it: a
  one-sentence sub (how to read it), the chart, then a **basis line**
  (denominator, what is excluded, how to interact).
- Leave more space above a section than inside it. Use hairlines between
  bands, not boxes around everything. No cards inside cards.

## 2. KPIs

- **4–6 tiles.** The first is the scale of the estate and is visibly larger.
  Each tile has a value (Financier), a unit (small), a label (mono caps) and a
  **note with the basis** ("22 live leases with a date · 5.1m sq ft").
- Each KPI must change a decision. Good ones: leased share, years to expiry
  (label it "to expiry" and give the basis), floorspace with an event in the
  next five years, landlord concentration (**leased only**), and a data-risk
  tile (lapsed or undated leases). Vanity ones are unit count alone, "regions:
  8" and anything the reader can't act on.
- A **flag tile** (coral value, warm rule on top) is a button. It opens the
  first affected unit in the drawer.
- KPIs **recompute with the filters.** When a filter empties the base, show
  "—" and the reason ("no dated leases in view"). Never `NaN`, never "0%" for
  "undefined".
- Formats are fixed and match the storyline: m sq ft to 2dp, whole
  percentages, years to 1dp.
- This band is the only place the big-number pattern is allowed. Even here
  every number carries its denominator, with no sparklines or rings as
  decoration.

## 3. Filters

- The bar sticks under the app bar. It holds operating-company chips (swatch
  and count), a landlord select (**leased only**, "All landlords (n)"), region,
  tenure, "Clear all" (shown only while a filter is on), and a live readout:
  "Showing **n** of **N** units · sq ft · % of portfolio" (`aria-live="polite"`).
  Compute N from the data. Never type it.
- Filters combine with AND. A landlord filter excludes freeholds, even where
  EverGreen left a landlord name on them.
- Everything responds to filters except the fixed findings, and the findings'
  section note says so.
- Lists and legends **rebase** on the filtered set, but their bars scale
  against the **unfiltered** maximum, so a filtered view reads as a share of
  the portfolio. (A legend reading the unfiltered data once stayed frozen at the
  full total while the list beside it showed the filtered one.)
- **Sticky offsets:** the table header sticks below the filter bar, whose height
  is measured at run time (it wraps). Write that CSS variable **on the view root
  the scoped stylesheet reads from**, not on `<html>`. A scoped `:root` becomes
  `#view-dash` and re-declares the variable, so the header pins behind the bar.
  Don't let the bar's own `min-height` read the variable either. That
  ResizeObserver loop grew a bar to 1,300px.
- **Mobile:** a wrapping filter bar must not stay stuck. Collapse it to a
  "Filters (2)" button with a panel, or unstick it below 860px. A stuck bar
  over 30% of the viewport is a defect. [stickyTooTall]
- Touch targets are 44px under 860px.

## 4. Map

Follow design-system.md §8. Dashboard specifics:
- A mode toggle (company / tenure / lease event) recolours the markers. The
  legend title and rows follow the mode, and in company mode the legend
  doubles as a filter (click a company to isolate it).
- Size key (three circles, labelled ≥10px) and a region list with bars.
- Popup: name, town · postcode, four key facts, then a "Full record" button
  that opens the drawer.
- Scroll-wheel zoom is off (the page scroll wins). Zoom buttons and double-click
  still work.
- Filtered-out units dim, they don't vanish. Hovering a table row highlights
  its marker.
- The map's keyboard path is the table: markers are not focusable, so every
  map action must also exist from a row.

## 5. Chart panels

- Every panel responds to filters, and its basis line re-states the
  denominator for the current selection ("Rent is recorded on 5 of 12 units in
  view"). Never hard-code counts in text the filters change. An "other
  landlords" tooltip once carried a typed count that was wrong, and a basis
  line kept citing the unfiltered freehold count under a filter.
- Not recorded is hatched, detached and counted.
- Clicks do something the reader expects: a landlord bar filters to that
  landlord, an expiry bucket opens its largest unit. Only clickable things get
  `cursor: pointer`, and each has a keyboard route (the table, or focusable
  marks with `role="button"`). [clickNoKeyboard]
- **Rendered type floor 10px.** Three 470-unit viewBoxes in a three-column
  grid render 10px labels at 8.6–9.2px on 1440–1536px screens. Either use
  two columns until each column is at least as wide as its viewBox, or size
  the viewBox to the real column. Below 860px, re-lay out the chart (fewer
  ticks, horizontal bars, larger declared type). Never just scale it down: an
  1,200-unit chart at 390px renders labels at 3px. [smallText]
- Same formats as the storyline. The two views must agree on every shared
  fact.

## 6. Findings → actions

- **Exactly five.** Each has a short number, a headline (a sentence with a
  number), a body (evidence with bolded figures, denominators and named units)
  and an **action** (a verb, and who or when: "Commission EPCs for the nine
  largest unrated units before the Q3 renewals").
- Findings are fixed, so they don't respond to filters, and the section note
  says so. Their figures must match the storyline word for word.
- Five columns at ≥1400px, two below, one on mobile, with no orphaned fifth
  item. Action lines are warm-ink with a hanging rule, so wrapped text sits
  under the first word.

## 7. The table

- One row per unit. Headers are buttons with `aria-sort`. Default sort is size,
  descending. **Nulls sort last in both directions.**
- Columns: unit (name, then town · postcode in mono), company (dot), region,
  size (inline bar plus number), tenure (pill), landlord ("—" for owned), lease
  expiry (urgency dot plus date, "freehold", or `n/r`), rent £/sq ft (`n/r`),
  EPC (pill; dashed `n/r`).
- Numbers are right-aligned, in mono with tabular numerals.
- Rows are focusable (`tabindex="0"`). Enter or Space opens the drawer, arrow
  keys move between rows, and the selected row stays marked while its drawer is
  open (`aria-selected="true"` set explicitly: `toggleAttribute` sets an empty
  string, which never matches).
- **Duplicate names are disambiguated** in the first column (unit ID or
  address), not left for the reader to guess. [dupLabel]
- At narrow widths the table scrolls inside its own container (never the page),
  keeping a readable first column.

## 8. The unit drawer

- It opens from a row, a marker popup, the flag KPI or a chart click. Focus
  moves to the close button, Escape and the scrim close it, and focus returns
  to where it came from. It is an `aria-modal` dialog.
- **It starts below the app bar** (`top: var(--bar-h)`). A drawer at `top: 0`
  puts its close button and title under the 56px bar. [underBar]
- The header is deep green: location (mono, accent), title (Financier 32px),
  address. Then a 2×2 hero (size, rent, expiry or "Freehold", site acres, with
  `n/r` where missing). Then notes in warm-ink on a warm tint: "The recorded
  expiry has passed: confirm status" and "No lease expiry recorded: CBRE to
  request the lease". Then sections: Identity, Tenure and lease, Operational
  fit (spec values plus yes/no flags), Compliance (EPC, and a MEES note in
  uk-rules.md's status words), Record provenance (ID, last updated, agents,
  completeness), and a closing line listing what is **not recorded**.
- Show a row only when its value is recorded. The gaps are listed once at the
  end, not as a column of `n/r`.
- Labels are ≥10px (the hero's mono captions must not drop to 9.5px). On
  mobile the drawer is full width, with the close button reachable.

## 9. Empty and sparse states

- Test the filters that leave 0, 1 and 2 units, and the sparsest single unit in
  the drawer (the QA driver does this).
- Every chart has a minimum-data rule and a sentence for when it isn't met ("Not
  enough recorded rents in this selection"), at ≥10px, in the panel's own frame.
  Never an empty axis, never a lone dot pretending to be a trend.
- Thin data is stated as the message: "Rent is recorded on 1 of 4 units in view."
- Never divide by an empty base. Show "—" with the reason.
- A zero-count legend or region row may dim, but use the muted **token**
  (5.6:1) and "—" rather than opacity 0.42, which drops the text to 2.4:1.
  [contrastDimmed]
- The table's empty state is one row with the reason and a "Clear all" button.

## 10. Mobile (390px)

- No horizontal page scroll. [hScroll]
- The filter bar collapses (§3). KPIs go 2-up with the hero tile still largest.
  Panels go 1-up. Charts are re-laid out, not scaled (§5). The map is about
  460px tall with its legend below. The drawer is full screen with its close
  button below the app bar.
- Pills, chips and selects are at least 44px tall. Links inside prose are
  exempt.

## 11. CSV export

- The button lives in the app bar and shows only in the dashboard view. It
  exports the **filtered, sorted** set.
- Columns have human names with units ("Size sq ft", "Rent per sq ft",
  "Eaves m") and include the Building ID and coordinates for traceability.
- Nulls are **empty cells**: never 0, never "n/r". Dates are ISO. Prepend a
  UTF-8 BOM so Excel reads £ and accents. Name the file
  `<Client>_Portfolio_<n>_units.csv`.

## 12. Alternative panels: replace or add when the client needs them

| Panel | Use when | Data | Interaction |
|---|---|---|---|
| Lease Gantt: one bar per lease from start to expiry, break and review ticks, a now-line | Events are the story | `leaseStart`, `expiry`, `breakDate`, `rentReview` | Click a bar to open the drawer. Sort by expiry |
| Landlord × year heatmap (bundle finder) | Several landlords hold several leases | `landlord`, `expiryYear`, `size` (leased only) | Click a cell to filter |
| Data completeness matrix (fields × units, by floorspace) | Gaps drive the advice | fill rates, `completeness` | Click a field to list its missing units |
| MEES exposure: in-scope units by band × lease end before/after 2031 | Compliance matters | `epc`, `expiry`, `size`, `region`, `owned` | Click a band to filter |
| Capability: spec-flag coverage and the hard-to-replace list | Specialist estate (cold, rail, power) | spec flags, `size`, `expiry` | Click a flag to filter |
| Next 24 months: action list with date, unit, landlord, event | The client wants a work plan | `expiry`, `breakDate`, `rentReview` | Row opens the drawer |
| Rent sensitivity: "+£x psf" slider → annual change on the units in view | Reviews or renewals loom | `rent`, `size` (recorded only) | Slider. States its base in the result |
| Park / cluster panel: parks with ≥2 units and their landlord mix | Campus concentration | `park`, `landlord`, `size` | Click a park to filter |
| Company small multiples: tenure and events per operating company | A multi-company group | `group`, `owned`, `expiry`, `size` | Click a company to filter |
| Freeholds: owned units by size, age and region | Capital is part of the story | `owned`, `size`, `pcYear`, `region` | Row opens the drawer |

A new panel must: answer one question named in its h3, carry a basis line,
respond to filters (or say it doesn't), have an empty state, offer a keyboard
path, render ≥10px at every viewport, use system colours only, and stay fast
at about 500 units.

## 13. Dashboard anti-patterns

- Tabs inside the dashboard, or a modal for anything the drawer can do.
- A chart that silently ignores the filters.
- Legends or basis lines frozen at unfiltered totals.
- Hard-coded counts in readouts, tooltips or notes ("of 44 units" typed into
  the template) instead of computed ones.
- Hover-only information with no click or keyboard route.
- Colour-only status with no word or date beside it.
- The same insight as the storyline, restated as a chart dump with no
  question per panel.
