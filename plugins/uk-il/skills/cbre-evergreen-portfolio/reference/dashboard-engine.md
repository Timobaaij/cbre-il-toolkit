# Dashboard engine — author's reference

The Dashboard view of every report is `engine/dashboard.html` (the core) configured by
**`report/dash.js`**, a classic script you write per run. You never edit the core. You describe
the dashboard to it through one global, **`window.DASH`**. This page is everything you need to
write `dash.js`. `examples/dashboard-example.js` is a complete worked one: read it next.

The engine is a quality floor, not a layout. Drop, reorder, rename, replace or invent panels.
What you get for free is the house style, honest handling of missing data, filters that every
panel obeys, the unit drawer, the map, the table and CSV export.

---

## 1. How dash.js runs

```
core definitions  ->  your dash.js  ->  (user opens the Dashboard tab)  ->  __initDashboard()
                      DASH.set(...)                                          builds the page
                      DASH.panel(...)                                        renders every panel
```

- **dash.js only declares.** `DASH.set()` and `DASH.panel()` record configuration; nothing is
  drawn until the view opens. Any value may be a **function**. It is called at render time, so
  it always sees resolved data.
- It runs **inside its own function scope**, so your top-level `const`s can never collide with the
  core's. You can still use `DASH` and `DASH.api` at top level.
- A **runtime error** in dash.js, or in any copy function or panel, is caught. It is logged once to
  the console and to `DASH.errors`, and the dashboard carries on (a broken panel shows
  "Unavailable"). A **syntax error** kills the whole dashboard: run `node --check` on your
  dash.js before assembling.
- Plain classic JS. No imports, no build step, no network.
- **Filters are never persisted.** Every load (and a return from the back-forward cache) starts
  unfiltered. Don't store filter state yourself.

### Two kinds of rows

| Receives ALL units (static)          | Receives the VISIBLE units (live, re-run on every filter) |
|--------------------------------------|-----------------------------------------------------------|
| `title.*`, `footer.*`, `findings`, panels with `live:false`, every `when(all)` | metrics, every panel's `title`/`sub`/`basis`, `render()` |

Write copy as functions of `rows`, so it stays true under every filter and never carries a
typed-in number.

### The lease state (read this before you count anything)

Every unit has one lease state, the vocabulary every view shares (`evergreen_units.py`):

| state | meaning | counts as running? |
|---|---|---|
| `running` | started and not yet at its recorded end | yes: WAULT, "unexpired", expiry years |
| `not started` | signed, starts after the as-at date | **never**: set apart, dashed outline |
| `passed` | the RECORDED expiry is before the as-at date | no: "recorded expiry passed" (holding over, regeared but not updated, or vacated), never "lapsed" or "expired lease" |
| `undated` | leased, no expiry recorded | no: "no expiry recorded", hatched |
| `owned` | recorded as owner-occupied | no lease event |

Read it with **`api.state(r)`** (or `api.running(r)`). The engine takes it from the canonical
`leaseState` field, derives it with the same rule when an older units.json lacks it, and freezes
it BEFORE dash.js runs. So if your dash.js overwrites `r.leaseState` with display words, the
engine still counts correctly; don't expect doing that to change what it counts. `r.expired`
means `passed`; `r.yearsToExpiry` is null for a passed lease (use `r.yearsSinceExpiry`);
`r.contractedOut` is true, false or null (not recorded).

---

## 2. Minimal dash.js

```js
DASH.set({});
```

That alone gives:
- a title band from `meta.client` / `meta.sector`, with a computed lede and source line;
- up to six KPIs, each chosen only if this export can support it;
- filters for every dimension with at least two values;
- the default panels: map, lease expiry, rent, landlords, quality and EPC, and the unit table;
- a CSV export.

There are no findings, because findings are analysis and analysis is yours.

A typical real one:

```js
const client = api => api.meta.clientShort || api.meta.client;
DASH.set({
  title: {
    h1: (rows, api) => api.meta.client,
    h1Light: "UK logistics estate",
    lede: (rows, api) => { const m = api.summary(rows);
      return api.Word(rows.length) + " units and <b>" + api.msf(m.tot) + " sq ft</b>; <b>" +
        api.pctS(m.leasedSf, m.tot) + "%</b> of it is leased."; }
  },
  metrics: ["floorspace", "leased", "wault", "expiring", "landlordTop", "lapsed"],
  panels: ["map", "expiry", "landlords", "quality", "findings", "table"],   // rent dropped
  copy: { landlords: { sub: (rows, api) => "Who controls the space " + client(api) + " rents." } },
  findings: [ (rows, api) => { /* compute; return {h, b, a} or null */ } ]
});
```

---

## 3. `DASH.set(config)`

Deep-merged, so you may call it several times. Every key is optional.

| key | type | default | notes |
|---|---|---|---|
| `title.h1` | str/fn | `meta.client` | Display serif. Plain text. |
| `title.h1Light` | str/fn | `meta.sector` | Second line in sage. `""` removes it. |
| `title.eyebrow` | str/fn | **none** | Legacy only: design-system.md says no eyebrow above a headline. Off unless you set it; don't. |
| `title.lede` | html/fn | computed | 21px paragraph; `<b>` for the numbers. |
| `title.meta` | array/fn | source · N records · `meta.caveat` | Small print under the lede. |
| `group` | object | see §3.1 | The occupier/operating-company dimension. |
| `metrics` | array | adaptive | Stock ids or custom tiles (§5). |
| `filters` | array | `["group","landlord","region","tenure"]` | §6. |
| `panels` | array of ids | `["map","expiry","rent","landlords","quality","findings","table"]` | Page order (§4). |
| `copy.<panelId>` | `{title, sub, basis, empty}` | panel defaults | Override any panel's copy; `empty:"hide"` hides it instead of showing its empty state. |
| `copy.expiry.mode` | `"auto"` / `"bands"` / `"years"` | `"auto"` | §4.2. |
| `findings` | `{title, note, items}` or array | none | §4.6. |
| `map` | `{modes, mode, places, regions}` | §4.1 | |
| `table.columns` | array | stock set | §4.7. |
| `labels` | object | §3.2 | **Every word the engine prints outside panel copy** (lease states, "Not recorded", the unit noun, flags, the intra-group phrases, drawer row labels). Change a word here, never by rewriting the page after it renders. |
| `drawer` | `{rows, notes, hero, note, mees, title, subtitle, completeness, sections}` | none | §4.8: hide, relabel or add drawer rows. `completeness:true` opts in to "Field completeness" (off by default). |
| `popup` | `{rows, title, sub}` | none | §4.1: the map popup, a model like the drawer. |
| `css` | string | none | Page CSS; `&` = the dashboard view (`#view-dash`). Use it to style anything outside your own panel, the stock table included (§7). |
| `mees` | object | `{target:"B", year:2031, sqft:10764, m2:"1,000 m²", floor:"E", source:"government interim response, June 2026"}` | Used by the quality panel, the EPC metric and the drawer. Change it if policy moves. |
| `footer` | `{left, right}` html/fn | computed | |
| `csv` | `{name, columns, extra, format, row}` | stock columns | §4.10. |
| `emptyPanels` | `"show"` / `"hide"` | `"show"` | What a panel with no data does across the page. |

### 3.1 group — the occupier dimension

```js
group: { field:"group",              // any unit field; each row gets r._g = its value or "Not recorded"
         full:"groupFull",           // the long name shown in the drawer
         label:"Operating company",  // legend title, drawer label
         short:"Company",            // filter label, map toggle, table column
         plural:"operating companies",
         order:["Name A"],           // pin some first; the rest follow by floorspace
         colours:{"Name A":"#032842"} } // pin only for house colours
```

- **Colours** come from design-system.md §3b, the palette the storyline uses. Groups take the slots
  in floorspace order, largest first, assigned once from the whole portfolio, so a company has the
  same colour in every panel and in both views: `#032842 #885073 #DBD99A #80BBAD #778F9C #C0D4CB
  #7F8480 #96B3B6`. Beyond eight groups the tail folds into **Other** (`#E6EAEA`, one legend row
  "Other (n)", each still filterable by name). "Not recorded" is neutral grey. Slots 3, 4, 6 and 8
  and Other are under 3:1 on white and carry the edge `rgba(0,0,0,.30)` automatically.
- **Fewer than two groups** switches the dimension off (`api.group.enabled === false`). The group
  filter, map mode, table column and every "Company" / "Operating company" label disappear, and
  marks use the neutral `#538184`. This is the single-occupier case.
- **More than eight groups** turns the chip row into a select.
- **Intra-group words follow the dimension.** With it on, a lease whose landlord is the client's
  own company reads "Group landlords" / "(group company)". With it off (one occupier) there is no
  "group" anywhere on the page: the same lease reads "`<client>` itself" / "(the client)", from
  `meta.clientShort` or `meta.client` (§3.2).

### 3.2 labels — the page's words

The defaults are in one place in the engine (`labelDefaults()`), and the ones below are the whole
list. `DASH.set({labels:{…}})` is deep-merged, so you name only what you change. Every label is
**plain text** (the engine escapes it) or a function `(v, r, api) => text`. Tokens: `{v}` the value
passed in, `{client}` / `{Client}` the client's short name, `{unit}` / `{units}` / `{Unit}` /
`{Units}` the record noun. Read one with `api.label("state.passed")`; `api.labels` is the
resolved map.

| key | default | where it prints |
|---|---|---|
| `unit`, `units` | "unit", "units" | every count of records: readout, tiles, bases, empty states, table title, drawer notes, CSV name (`api.plural(n, "unit")`, `"leased unit"` and `"let unit"` follow it) |
| `notRecorded` | "Not recorded" | a missing value named as a category (legends, bars, `api.NR`, `api.by()` keys) |
| `state.running` / `state["not started"]` / `state.passed` / `state.undated` / `state.owned` | "Running" / "Not yet started" / "Recorded expiry passed" / "No expiry recorded" / "Owned" | the lease-state words: map lease-event legend, popup, KPI labels, expiry key, CSV "Lease state", `api.stateLabel()` |
| `band.soon` / `band.mid` / `band.long` | "Within 2 years" / "2–5 years" / "Over 5 years" | running leases on the map's lease-event mode |
| `bucket.passed` / `bucket.notStarted` / `bucket.undated` | "Recorded\nexpiry passed" / "Not yet\nstarted" / "Not recorded" | the set-apart expiry columns (`\n` = second line) |
| `quality` | "Recorded as {v}" | the drawer's Quality row: the grade as recorded, not a finding about today |
| `completeness` | "Field completeness" | the drawer row, when `drawer.completeness:true` |
| `flags.coldStore` … `flags.vmu` | "Cold storage", "Cross-docked", "360° HGV circulation", "Gatehouse", "Truckwash", "HGV refuelling", "VMU" | the drawer's operational flags (case kept: "HGV", "VMU") |
| `flagNo` | "{v}: no" | a flag recorded as absent ("Cross-docked: no"); `""` leaves the negatives out |
| `sections.identity` / `lease` / `leaseOwned` / `ops` / `compliance` / `provenance` | "Identity" / "Tenure and lease" / "Tenure" / "Operational fit" / "Compliance and ESG" / "Record provenance" | drawer section titles |
| `rows.<key>` | none | relabel any stock drawer row by its key (§4.8), e.g. `rows:{expiry:"Lease end"}` |
| `missing` | "Not recorded in the source: {v}." | the drawer's gap line |
| `popupButton` | "Full record" | the map popup's button |
| `noMatch`, `clearAll` | "No {units} match these filters.", "Clear all" | the table's empty row, the map note |
| `client` | `meta.clientShort` ‖ `meta.client` ‖ "the client" | `{client}` in every label |
| `intraSet` | on: "Group landlords"; off: "{Client} itself" | the landlord chart's intra bar, the landlord filter option |
| `intraTag` | on: "group company"; off: "the client" | after a landlord name: table, popup, drawer ("Acme Ltd (the client)") |
| `intraWho` | on: "a group company"; off: "{client} itself" | sentences: the landlords basis, the undated-lease note |
| `intraExcluded` | on: "group landlords excluded"; off: "leases from {client} itself excluded" | the `landlordTop` note |
| `intraCsv` | on: "Landlord is a group company"; off: "Landlord is {client} itself" | the CSV column header |

"on" / "off" = the group dimension (§3.1). A report's own value wins in both cases.

**Text or HTML.** Short strings the API takes are **text**, escaped for you: every label, a
metric's `label` and `note`, `api.empty(el, message, head)`. Where you need markup there, pass
`{html:"…"}`. Panel copy (`sub`, `basis`), findings, the lede, the footer and drawer row values
and notes are **HTML**: escape data in them with `api.esc`.

---

## 4. Panels

The page is a sequence of bands. A `layout:"full"` panel gets its own band, with an h2 and a note
on the right. Consecutive `layout:"block"` panels share a band in rows of up to three (4 → 2+2,
5 → 3+2). Blocks have an h3 and a sub, and a lone block sits in a single, narrower column.
`tone:"white"` gives a white band with rules, like the findings. Every panel has an optional
**basis** line under it: the small print that states denominators.

A panel's `when(all)` decides its fate once, on all units:
- `true`: render normally;
- `false`: skip it entirely (nothing meaningful and nothing missing);
- `"a sentence"`: keep the heading and show an honest dashed "Not recorded" box with that
  sentence (the data should exist but does not).

A live empty state (a filter leaves nothing in view) is drawn inside the panel. Layout never
jumps.

### 4.1 `map` (full) — where the estate is
Leaflet on the vector land from `engine/land.json`, offline. Circle **area** is floorspace. The
colour-mode toggle offers Company, Tenure and Lease event, and the legend beside it shows
floorspace by mode value. Clicking a company isolates it. Under the legend sit a size key (three
round sizes drawn at true marker diameter) and a clickable region list. Esri street tiles appear
only from zoom 9, and their labels from zoom 11. Below that, CBRE place labels are placed
collision-free. A town whose own point sits under a unit circle is hidden at that zoom.
- **Lease event** colours running leases on the urgency ramp (§9): passed `#A8523A`, ≤2 yrs
  `#D2785A`, 2–5 yrs `#E0A33C`, >5 yrs `#3F7F66`, owned `#435254`. "No expiry recorded" is a
  **hollow ring** and "Not yet started" a **dashed ring**, never a fill that could be a company.
- Needs `lat`/`lng`. Units without them are left off and the note says how many. With no
  coordinates at all it shows an empty state. A single site gets a fixed regional zoom.
- `map.modes`: `["group","tenure","event", {id, label, title, key:r=>value, order:[...],
  colours:{v:hex}, forms:{v:"hollow"|"dashed"}}]`. Modes with one value are dropped, and the toggle
  hides when only one mode is left.
- `map.places`: extra `[name, lat, lng, tier]` labels (tier 3 shows from zoom 8).
- `map.regions:false` hides the region list (it also hides itself below two regions).
- **The popup** is a model like the drawer. Rows are `[{key, label, value (html)}]` with keys
  `floorspace, group, tenure, landlord, state, expiry`. `state` prints the lease-state word
  (`labels.state`: "Running", "Recorded expiry passed", "Not yet started", "No expiry recorded"),
  and `expiry` the recorded date, never a bare "(passed)". An intra landlord carries
  `labels.intraTag`, so with one occupier it never says "(group)".
  ```js
  popup: {
    rows:  (r, rows, api) => rows.filter(x => x.key !== "tenure")
             .concat([{key: "eaves", label: "Eaves", value: api.has(r.eaves) ? r.eaves + " m" : api.UNK}]),
    title: (r, api) => r.short,                        // text
    sub:   (r, api) => [r.town, r.postcode].filter(Boolean).join(" · ")   // text
  }
  ```

### 4.2 `expiry` (full) — when the leases move
Leased floorspace by the year the recorded lease ends, with a key above. Clicking a column opens
its largest unit. When labels can't fit their column (a phone, or many buckets) it relays out as
rows.
- **Colour.** With the group dimension on, running columns stack by company and every state is
  form (dashed, hatched, its label). With it **off**, nothing is a company colour: running columns
  are the neutral mark and the passed column is `--sem-passed` `#A8523A`, named in the key.
- **One unit per chart.** The axis, the value labels and the basis line share one unit: millions,
  with decimals from the step (0.25m steps read "0.25m, 0.50m"), or exact sq ft when the scale is
  under 100,000 sq ft. `DASH.stock.expiry.scale(rows)` returns that formatter for a clone.
- **Year columns hold running leases only.** "Recorded expiry passed" is its own column; "Not yet
  started" is set apart with a dashed outline; "Not recorded" (no expiry) is detached and hatched.
  The column words are `labels.bucket.*`, and the key's words `labels.state.*`.
- **Two modes.** `bands`: Y–Y+1, Y+2–Y+4, Y+5–Y+9, Y+10+ (Y = the as-at year). `years`: one
  column per calendar year to Y+5, then the rest. The default `auto` takes `years` when a cliff
  straddles a band boundary: two adjacent years in different bands holding a quarter of the running
  floorspace between them (each at least 8%). Banding would split that cliff across two columns.
  Force either with `copy.expiry.mode`.
- Needs `expiry` on leased units. With no leases at all it is skipped; with leases but no dates it
  shows an empty state.

### 4.3 `rent` (block) — rent against deal year
Achieved £/sq ft against deal year, with circles sized by floorspace and a dashed
floorspace-weighted average line in body ink (an average is not a state). The average's label
takes a slot that touches no circle. The basis gives the coverage ("recorded on 12 of 40…") and
the weighted average of the recorded rates. **There is no rent roll**: achieved rent × size grosses
a partial record up into a figure EverGreen does not hold. The only sum a report may print is of
the recorded `rentPa`, captioned with its unit count.
- Needs `rent` and `dealYear`. With no rent anywhere it shows an empty state. With fewer than two
  plottable points in view it shows a live empty state.

### 4.4 `landlords` (block) — landlord exposure
**Third-party landlords only**: leased units, and never an intra-group landlord (`landlordIntra`:
the client itself or a group company is not exposure). Shown in order:
1. The top ten third-party landlords by floorspace; the top holders (the KPI's `n`, default 6)
   are emphasised in `--hot` and the rest are neutral.
2. "N other landlords", in the receding context colour (not the not-recorded hatch).
3. The intra-group leases, shown apart as `labels.intraSet`: "Group landlords", or
   "`<Client>` itself" when the group dimension is off.
4. "Not recorded", hatched.

Clicking a bar filters by that landlord. The basis prints totals in m sq ft to 2 dp (`msfT`:
exact only under 100,000 sq ft), never a raw sq ft sum.
- Skipped with no leases; empty state if no leased unit records a landlord.
- A clone may call `DASH.stock.landlords.agg(rows)` (third-party + NR) and
  `DASH.stock.landlords.intra(rows)` (the intra-group total).

### 4.5 `quality` (block) — asset quality and EPC
Two 100% stacks. The first is asset quality on all units: EverGreen's three grades are shortened
to Pre-2010, Post-2010 and New Grade A (the §3d ramp), and other values are shown as recorded.
The second is EPC A–G (the §3c colours) on **let units in England and Wales**, with "Not
recorded" hatched. The copy follows uk-rules.md §1, with two tests that are never merged:
- the **EPC E minimum is in force** for every let building in England and Wales, of any size;
- **from 2031**, let buildings over 1,000 m² **are set to need EPC B where cost-effective: a
  government target, not yet law**.

The basis states both scope counts. No EPC is "unrated, not failing". Units in Scotland or
Northern Ireland are named as outside these rules.

### 4.6 `findings` (full, white, static)
Your analysis. It is skipped when there are none, and the title counts them ("Five things the
spreadsheet does not tell you"). Up to five sit in one row, and more wrap evenly.

```js
findings: { title: "…", note: "…", items: [
  { h: "Headline", b: "Body, <b>numbers bold</b>.", a: "The action." },   // strings or fns(all, api)
  (rows, api) => pattern ? {h, b, a} : null                           // null drops it
]}
```
Findings do **not** respond to filters. The default note says so; keep that promise if you
rewrite it.

### 4.7 `table` (full) — every unit
A sortable table. Rows open the drawer, hovering a row rings its map marker, and nulls always sort
last. The header is sticky under the (measured) filter bar. The box only scrolls sideways when the
table is **measured** not to fit, so the header stays sticky whenever it can; no CSS override is
needed for wide tables.
- Stock columns are `short, group, region, size, tenure, landlord, expiry, rent, epc`. An owned
  unit's expiry reads "owned", and an intra-group landlord carries `labels.intraTag` ("(group
  company)", or "(the client)" with one occupier). Expiry dots show the lease state: urgency fill,
  or dashed / hollow form. EPC is a pill with the letter and a colour swatch.
- **Styling it.** A panel's `css` reaches only that panel. To style the stock table, register the
  CSS on the table itself (`DASH.panel(Object.assign({}, DASH.stock.table, {css:"…"}))`) or put
  it in page-level `DASH.set({css})`, where `&` is the whole dashboard view.
- **Print.** The table is laid out at the page width, columns size to their content, and cells
  wrap at spaces only: a figure or a word is never split, and text cells hyphenate only where a
  column cannot hold a word.
- By default a column with no values anywhere is dropped.
- Add columns: `{k:"eaves", t:"Eaves", num:true, unit:"m"}`, or
  `{k, t, get:(r, api)=>html|null, sortKey:r=>value}`. A bare field name also works.

### 4.8 The drawer (not a panel)
Opens from the map, the table, charts and flagged metrics: `api.openDrawer(r)`. It holds the full
record: lease notes, MEES note, operational flags, provenance and a "not recorded" list. It is
built from a **model** you can change, so there is never a reason to patch its HTML:

```js
drawer: {
  // rows: [{sec, key, label, value (html), cls?, after?}]
  //   sec = identity | lease | ops | compliance | provenance | any other title (a new section)
  rows: (r, rows, api) => rows
    .filter(x => x.key !== "quality")                                 // hide one
    .map(x => x.key === "review" ? Object.assign({}, x, {label: "Rent review"}) : x)   // relabel
    .concat([{sec: "lease", key: "perPound", after: "rent", label: "Each £1 per sq ft",
              value: api.sf(r.size) + " a year"}]),                   // add, placed after "rent"
  notes: (r, notes, api) => notes,      // [{key, html}]: passed | notStarted | undated | ownedThirdParty | report
  hero:  (r, cells, api) => cells,      // 4 cells [{key, value, caption}]: size | rent | expiry or tenure | site
  note:  (r, api) => r.myNote ? api.esc(r.myNote) : null,   // the "report" note (below)
  mees:  (r, text, api) => text,        // the MEES sentence (text), or null to drop it
  title: (r, api) => r.short,           // text
  subtitle: (r, api) => "…",            // text; default below
  completeness: true,                   // opt in to "Field completeness" (off by default)
  sections: [{ title: "Report flags", rows: (r, api) => [["Label", value|null], …] }]   // legacy form
}
```
A plain relabel needs no hook: `labels.rows.<key>` (§3.2), e.g. `labels:{rows:{expiry:"Lease end"}}`.

Row keys:
- **identity:** `group`, `town`, `postcode`, `region`, `corridor`, `park`, `setting`, `quality`,
  `provenance`, `pcYear`.
- **lease:** `tenure`, `landlord`, `landlordOnRecord`, `developer`, `leaseStart`, `term`,
  `expiry`, `unexpired`, `break`, `review`, `reviewType`, `contractedOut`, `rent`, `rentPa`,
  `dealDate`, `incentive`.
- **ops:** `eaves`, `yard`, `dockDoors`, `levelDoors`, `totalDoors`, `doorRatio`, `floorLoad`,
  `power`, `office`, `siteCover`, `trailers`, `carSpaces`, `rail`. **compliance:** `epc`, `breeam`.
- **provenance:** `id`, `updated`, `agentDisposal`, `agentAcq`, and `completeness` (only with
  `drawer.completeness:true`).

Rows with a null value are omitted, never printed as "null".

**`{after: key}`.** The row moves to just after that key. If this unit has no value for a
**stock** key, the row goes where that key would have been. If the drawer has no such key at all
(a typo, or a report row missing on this unit), the row stays at the end of its section and the
console warns once.

**The `report` note** is exactly what `drawer.note(r, api)` returns (HTML, so escape data). No
unit field feeds it by default; `evergreen_units.py` writes none. A report that keeps its own
per-building wording in units.json (a `dataNote` field, say) returns it from `drawer.note`.

What the stock drawer already does, so your dash.js doesn't have to:
- "Rent per annum" is EverGreen's **recorded** `rentPa` only, never rate × size.
- "Unexpired" appears only on a running lease; a not-started lease reads "Lease starts".
- Dates read as recorded: "Recorded expiry" (hero caption "recorded expiry", "recorded expiry,
  passed" or "recorded expiry, not started"), "Recorded expiry (passed)", "Recorded break
  (passed)", "Last recorded review".
- Passed expiry: "holding over, regeared but not updated, or vacated".
- **MEES note:** nation-aware. Certainty follows the rule: the EPC E minimum is in force and is
  the landlord's obligation; the 2031 B target "is set to" apply, where cost-effective, and no
  obligation word is attached to it.
- **Quality** reads as recorded: "Recorded as New Grade A" (`labels.quality`).
- **Flags** print as recorded: a yes is a chip ("Cross-docked"), a no reads "Cross-docked: no"
  (`labels.flagNo`; `""` leaves negatives out). Acronyms keep their case.
- **Site cover** is a whole percentage, rounded half up ("40%", never "40.0%"); site acres use one
  decimal only where it says something ("12", "12.4").
- **Practical completion** reads as a month ("June 2022") when `pcDate` is recorded, else the year.
- **The subtitle never repeats the title.** It is the full address when that says more than
  `short`. Otherwise it is the park, town and postcode, each only if the title does not already
  hold it.
- An undated lease with an intra-group landlord says to confirm with the client (not "request
  the lease from the landlord"), in `labels.intraWho` words.
- An owned unit that names a third-party landlord reads "Recorded as owned (title to confirm)",
  with the landlord on record; never "Freehold — owned by …".
- "Field completeness" is **off** unless you opt in: the score counts lease fields an owned
  building cannot have.
- The body carries no event handlers.

### 4.9 Opt-in stock panels
List these in `panels` to use them.

| id | layout | shows |
|---|---|---|
| `regions` | block | Floorspace by region (hbars, click filters, scaled to the whole portfolio). |
| `coverage` | block | "What the export records": share of units with each key field (`copy.coverage.fields` = `[[label, field, leasedOnly]]`). A lease field with no leased unit in view says "no base", never "0 of 0". |
| `events` | block | The next lease events: expiries, breaks and reviews of running leases, and starts of leases not yet running, in the next `copy.events.years` (default 3), soonest first, up to `copy.events.max` (default 8). `DASH.stock.events.list(rows)` returns `[{r, d, kind}]`. |

### 4.10 CSV
The stock columns are:
`id, name, town, postcode, region, corridor, park, group, tenure, leaseState, landlord,
landlordIntra, landlordOnRecord, size, siteAcres, quality, leaseStart, leaseTerm, expiry,
breakDate, rentReview, rent, rentPa, dealDate, contractedOut, epc, breeam, eaves, yard,
dockDoors, power, coldStore, lat, lng`.

An owned unit's `landlord` is blank; the name EverGreen leaves there goes to "Landlord named on an
owned record (confirm title)". `leaseState` prints the page's words (`labels.state`),
`landlordIntra`'s header is `labels.intraCsv` ("Landlord is a group company", or "Landlord is
`<client>` itself" with one occupier), and `name`'s header is `{Unit}`. A stock column you also add
in `extra` prints twice; rename it through `columns` or `format` instead.

```js
csv: {
  name: "Client_Portfolio",                            // file name stem
  columns: ["id", "name", "size", "leaseState", ["First break or expiry", "nearestEvent"]],
  extra:   [["Report flag", r => r.flag ? "Yes" : null]],   // appended
  format:  { size: v => v && Math.round(v), "Lease expiry": v => v ? v.slice(0, 7) : v },   // by id or header
  row:     (r, api) => r.flag ? r : null                     // transform a row, or null to skip it
}
```
`api.csvColumns()` lists the resolved columns.

### 4.11 Extending a stock panel
Clone it and change only what you need; the clone keeps the stock scale, click, relayout and copy:

```js
DASH.panel(Object.assign({}, DASH.stock.expiry, {
  id: "expiry",                                   // same id = replace the stock panel
  buckets() { return DASH.stock.expiry.buckets.call(this).filter(b => b.key !== "ns"); }
}));
```
- `DASH.stock.expiry`: `buckets()` returns `[{label, key, t(r), gap?, hatch?, form?}]`,
  `mode()` returns "bands" or "years", and `scale(rows)` returns the chart's value formatter
  (the one unit its axis, labels and basis share).
- `DASH.stock.landlords`: `agg(rows)` and `intra(rows)`.
- `DASH.stock.events`: `list(rows)` and `years()`.
- `DASH.stock.coverage.fields()`.

---

## 5. Metrics (the dark KPI band)

Stock ids:
- `floorspace`, `units`, `leased`, `owned`.
- `wault`: **running leases only**; its note says how many not-started leases are excluded.
- `expiring` (`{id:"expiring", years:5}`): running leases ending in the window.
- `landlordTop` (`{id:"landlordTop", n:6}`): **third-party** leased floorspace; intra-group
  leases are excluded and the note says so (`labels.intraExcluded`). The label counts with the one
  plural rule: "Five landlords hold", and "Largest landlord holds" for `n:1` or when no more than
  `n` landlords exist (never "One landlords hold").
- `lapsed`: "Recorded expiry passed", a flagged tile that opens the largest.
- `rent`: the weighted average, with its coverage.
- `epc`: the share of let units in England and Wales at the MEES target or better.

Override any label or note: `{id:"wault", label:"…", note:rows=>"…"}`.

Custom tile:
```js
{ label: "Cold store", unit: "units",
  value: (rows, api) => rows.filter(r => r.coldStore === true).length,   // or [v, unit] or {v, u}
  note:  (rows, api) => "recorded on " + rows.filter(r => r.coldStore !== null).length + " of " + rows.length,
  flag: true, onClick: (rows, api) => /* a unit to open */ }
```
- **Every tile carries its denominator in `note`.** A null or NaN value prints "—".
- `label` and `note` are **text** (escaped); return `{html:"…"}` for markup, as with `api.empty`.
- Tiles print a small selection in exact sq ft (`api.msfT`: "7,831", not "0.01m"), and a share
  that is not exact never as "0%" or "100%" (`api.pctS`: "<1", ">99").
- Listed ids always show (as "—" if the export can't support them). With no `metrics` given, the
  engine picks up to six from `floorspace, leased|owned, wault, expiring, landlordTop, lapsed,
  rent, epc`, keeping only those this export can support.
- Up to six tiles sit in one row, seven and eight wrap to two rows, and the first tile is the hero.

## 6. Filters

The stock filters:
- `"group"`: chips, or a select above eight groups.
- `"landlord"`: third-party landlords of leased units, plus one intra-group option when any exist
  (`labels.intraSet`: "Group landlords", or "`<Client>` itself" with one occupier).
- `"region"`.
- `"tenure"`: "Owned" or "Leased".

You can add two kinds of your own:
- `{field:"corridor", label:"Corridor", all:"All corridors"}`: a select over a field's values;
- `{id:"cold", label:"Cold store", test: r => r.coldStore === true}`: an on/off chip.

A filter appears only if its dimension has two or more values (a toggle only if it splits the
units). Every panel, metric, map marker, legend and the readout obey all filters.
`api.setFilter(id, value)`, `api.toggleGroup(name)` and `api.reset()` drive them from your own
panels. Filters are never persisted across a load.

---

## 7. `DASH.panel(spec)` — a new panel

```js
DASH.panel({
  id: "cold",                 // unique; reusing a stock id REPLACES that stock panel
  after: "quality",           // or before: "findings"; ignored if you list the id in panels:[…]
  layout: "block",            // "block" (a third of a row) | "full" (own band)
  tone: "plain",              // "plain" | "white"
  live: true,                 // false: render once with all units (like findings)
  title: "Where the cold chain sits",       // str | fn(rows, api)
  sub: "Cold storage recorded, by floorspace.",
  basis: (rows, api) => rows.filter(r => r.coldStore === true).length + " of " + rows.length +
                        " units record a cold store.",
  when: all => all.some(r => r.coldStore === true) || "Cold storage is not recorded on any unit.",
  css: "& .note{color:var(--muted)}",       // optional; & = this panel's root, scoped for you
  init(el, api) { /* once, optional */ },
  render(el, rows, api) {                   // every filter change and width change
    const g = api.by(rows.filter(r => r.coldStore === true), r => r._g);
    if (!g.length) return api.empty(el, "No cold store in this selection.", "Nothing in view");
    api.hbars(el, g.map(x => ({ label: x.k, value: x.sf, colour: api.colourOf(x.k), key: x.k })),
              { onClick: it => api.setFilter("group", it.key) });
  }
});
```
`render` must fill `el` completely each time (`innerHTML = …`). It is re-run when its column
changes width, so charts relay out rather than scale.

**`css`.** A panel's CSS is scoped to that panel: `&` in a **selector** becomes
`#view-dash [data-panel="<id>"]`. An `&` inside a quoted string, a comment or a declaration value
(`content:"A&B"`, `url(a&b.png)`) is left alone, and at-rule preludes (`@media print{…}`) are kept.
A selector without `&` is not scoped, so always start with `&`. It cannot reach outside the panel:
for the stock table or anything else on the page, use `DASH.set({css})`, where `&` is
`#view-dash`.

## 8. `api` — the helper kit (also `DASH.api`)

**Data**
- `all` (every normalised unit), `rows` (visible now), `meta`, `asAt` (ISO), `today` (Date),
  `year` (as-at year), `NR` (`labels.notRecorded`, "Not recorded"), `filters` (snapshot).
- `label(path, v?, r?)` → a resolved label as text (`api.label("state.passed")`); `labels` is the
  resolved map (§3.2).
- `group` (`{field, label, short, plural, order, colours, enabled, folded}`), `map` (the Leaflet
  map, after init).
- **Lease state:** `state(r)`, `running(r)`, `stateLabel(s)`.
- `summary(rows)` returns `{tot, rows, own, ownSf, leased, leasedSf, running, runningSf, wault,
  passed, passedSf, notStarted, notStartedSf, soon, soonSf, tp, tpSf, intra, intraSf, topK, top1,
  k, nll, noExp, noExpSf, sizeless}`. `live`/`liveSf` and `lapsed`/`lapsedSf` are kept as aliases.
- `sum(rows, field|fn)` (null-safe), `by(rows, field|fn)` (`[{k, rows, n, sf}]` by floorspace,
  nulls as "Not recorded"), `size(r)`, `leased(rows)`, `thirdParty(rows)` (leased, landlord
  recorded, not intra-group).

**Format**
- `sf(v)` → "250,000" (null → null).
- `msf(v)` → "1.50m" / "0.40m" / "<0.01m" / "0": millions at a **fixed 2 dp**, the storyline's
  format, one unit everywhere.
- `msfT(v)`: exact sq ft below 100,000, for tiles and sentences (a basis total uses it too).
- `chartFmt(top)`: the value format for a chart whose scale runs to `top`: `msf`, or exact sq ft
  under 100,000 (the kit's default, so the labels match the axis).
- `pct(a,b)` (number) and `pctS(a,b)` (text, with "<1" and ">99").
- `money(v)` → "£6.50"; `dmy(iso)` → "01 Mar 2030"; `longDate(iso)` → "1 March 2030";
  `monthYear(iso)`; `my(iso)` → "Mar 2030"; `myy(iso)` → "Mar-30".
- `word(n)` / `Word(n)` ("twenty-five"), `andList([...])`.
- **One plural rule:** `noun(n, "lease")` → "lease" / "leases" (also verb pairs: `noun(n, "has",
  "have")`); `plural(n, "lease")` → "3 leases"; `pluralWord(n, "landlord")` → "One landlord",
  "Five landlords". `"unit"`, `"leased unit"` and `"let unit"` follow `labels.unit`/`units`.
- `llShort(name)`: drops Ltd/Plc and fixes ALL-CAPS; for labels only.
- `esc(s)`: **escape every data value you put in HTML.**
- `has(v)`, `UNK` (the n/r token).

**Colour** (one table: `api.theme`, mirroring design-system.md §3)
- `theme.categorical`, `theme.sem.{hot, neutral, context, passed, risk, watch, secure, owned,
  unknown, notRec, notRecHatch}`, `theme.epc`, `theme.ramp`; `C` holds the same tokens by name.
- `palette`, `hatch` (`url(#dash-hatch)`, the not-recorded fill), `colourOf(groupName)`,
  `groupColour(r)`.
- `eventBand(r)` / `eventColour(band)` / `eventForm(band)`; `epcColour(letter)`, `epcPill(letter)`,
  `stateDot(r)`.
- `onColour(hex)` (white or ink, whichever contrasts more), `contrast(a, b)`, `edge(hex)` (the
  `rgba(0,0,0,.30)` edge for a fill under 3:1, else null).
- `key(items)`: HTML for a key above a chart; items are `[{label, colour?, form?:
  "hatch"|"dashed"|"hollow"}]`.

**Regulation**
- `mees()`, `inEW(r)`, `nation(r)` ("Scotland", "Northern Ireland" or null), `meesNote(r)` (the
  drawer's sentence).

**Interaction**
- `openDrawer(r)`, `setFilter(id, v)`, `toggleGroup(name)`, `reset()`, `refresh()`.
- `keyable(node, fn, name)` makes any element you draw a keyboard button.
- `csvColumns()`.

**Chart kit:** the stock panels are drawn with these, so yours match.

| call | draws |
|---|---|
| `hbars(el, items, o)` | Labelled horizontal bars; the label column is measured from the text. `items:[{label, value, colour?, hot?, hatch?, muted?, inert?, text?, title?, full?, key?}]`; `o:{design:470, format, max, labelWidth, valueWidth, onClick(item), label}`. Bars are neutral unless `colour` or `hot`; `hatch` is only for "not recorded". |
| `columns(el, buckets, o)` | Stacked columns, with detached buckets for set-apart states. `buckets:[{label ("\n" for a 2nd line), sub?, segments:[{value, colour?, title?, fill?, stroke?, dash?, hatch?}], hatch?, gap?, style?:{fill, stroke, dash}, title?}]`; `o:{design:1200, H:290, format, axis, rows (true forces the row layout), key, onClick(bucket), label}`. The scale runs to a gridline at or above the maximum; an empty bucket prints no value. |
| `scatter(el, points, o)` | Sized circles plus a dashed reference line. `points:[{x, y, size?, r?, colour?, title?}]`; `o:{design:470, H:290, xLabel, yFormat, xFormat, ref:{y, label}, minPoints:2, emptyText, onClick(p)}` |
| `stack(el, stacks, o)` | 100% stacked bars. `stacks:[{title, items:[{label, value, colour?, hatch?, title?}]}]` |
| `empty(el, message, head)` | The dashed honest empty state. `message` and `head` are **text** (escaped), like a metric note; pass `{html:"…"}` for markup. |
| `width(el, design)` | The width to lay a chart out at (see §9). |
| `svg(W, H, inner, ariaLabel)`, `ticks(max, n)` → `{step, ticks, top}`, `niceStep(raw)`, `axisFmt(max, step)` | Primitives for your own SVG. |

---

## 9. Making a new panel look native

**Type.** The SVG classes are already styled:
- `.ax` (10px mono axis, muted), `.ax-b` (10px mono label, body);
- `.val` (11px mono value, ink), `.val-d` (10px mono secondary, muted);
- `.gl` (gridline), `.bl` (baseline, sage), `.bar` (hover fade), `.clk` (pointer).

In HTML use the page's own classes:
- `.basis`, `.unk`, `.dot` (with `.hollow` / `.dashed`), `.ck` (a key);
- `.pill` + `.p-own/.p-lease/.p-regear/.p-epc/.p-none`;
- `.ev-list/.ev-row` (compact clickable list);
- `.mini` (a small table: plain `<table>` is safe inside panels).

The fonts are `var(--font-display)` (Financier Display), `var(--font-body)` (Calibre) and
`var(--font-mono)` (Space Mono). Numbers are mono or tabular.

**Size.** The floor is **10px rendered**, at every viewport, for every text run, chart or HTML
(chip counts, captions and the map attribution included).
- Lay SVG out at `W = api.width(el, design)` and draw in those units (the viewBox equals the real
  width). A chart is never scaled down, so type never renders below its declared size, and never
  scaled up more than 1.25x.
- Blocks design at 470 and full bands at 1200. On a phone you get ~354px, so check that your labels
  still fit, or switch layout the way `columns()` does.
- `hbars()` measures its label column rather than truncating; a name that must be cut keeps its
  full text as a tooltip.

**Numbers.** One unit per chart, shared by its axis, its value labels and its basis line.
- Floorspace axes are in millions (`axisFmt`). The decimal count is the fewest that print every
  step exactly (0.25m steps read "0.25m, 0.50m, 0.75m", never "0.3m, 0.5m, 0.8m"), and is the same
  across the axis: never "0.5m, 1m", never "400k" next to "0.47m".
- A scale under 100,000 sq ft, or one whose step would need three decimals, reads in exact sq ft,
  on the axis and the labels alike (the kit's default `format` is `chartFmt(top)`).
- Values otherwise use `msf` (2 dp), and basis totals `msfT`.

**Colour: design-system.md §3, never your own hex.**
- **Categorical** (groups): `api.colourOf(name)`. Never draw a group in a semantic hue.
- **Semantic** (states, the same meaning in every chart and both views):
  - emphasis `--hot` `#003F2D` (one per chart);
  - neutral `#538184`, context `#E6EAEA`;
  - passed `#A8523A`;
  - risk ≤2 yrs `#D2785A`, watch 2–5 yrs `#E0A33C` (outline it on light), secure >5 yrs
    `#3F7F66`;
  - owned `#435254`;
  - unknown `#5C6B66`: a hollow ring = no expiry, a dashed ring = not started;
  - not recorded (areas) = the hatch (`#CBD0CC` with `#9AA8A2`).
- **The rule:** one chart never uses the same hue for a category and a state. A state drawn beside
  group colours is **form** (hollow or dashed ring, dashed outline, hatch, label).
- **EPC:** A `#23604A`, B `#3F7F66`, C `#80BBAD`, D `#E0A33C`, E `#D2785A`, F/G `#A8523A`. The
  letter is always printed; no EPC = hatch; "B or better" = secure, "below B" = risk.
- **Pale marks** (under 3:1 on white: categorical 3, 4, 6, 8, Other; watch; EPC C and D) carry
  `api.edge(fill)`. The kit and the map do this for you; do it for marks you draw
  (`stroke="${api.edge(fill) || 'none'}"`).

**Text contrast.** WCAG AA against what is actually behind the text: 4.5:1 below 24px (or 18.66px
bold), 3:1 above.

| token | on page bg #F5F7F7 | on white | use |
|---|---|---|---|
| ink/green #003F2D | 11.2 | 12.0 | headings, values |
| body #435254 | 7.6 | 8.2 | text |
| muted #5C6B66 | 5.2 | 5.6 | secondary text; the lightest colour allowed for 10px type |
| warm-ink #A8523A | 5.0 | 5.3 | alert text, actions |
| sage #538184 | 4.0 | 4.3 | large text only |
| accent #17E88F, celadon #80BBAD | 1.5 / 2.0 | 1.6 / 2.2 | **never text** on light ground |

Text on a coloured mark: use `api.onColour(fill)` and print it only if `api.contrast(ink, fill)
>= 4.5`, otherwise put the label beside the mark (`stack()` does this).

**A dimmed state** (a row with nothing in view) uses the `muted` token, never opacity: at .42
opacity a name fell to 2.4:1. The legend and region lists use `.lg-row.dim`.

**Focus** is an outline (`:focus-visible { outline: 2px solid … }`, white on dark grounds), never a
box-shadow: shadows are clipped by overflow and dropped in forced-colours mode.

**Behaviour.**
- Clicking a mark should either open the unit (`api.openDrawer`) or filter (`api.setFilter`);
  never dead-end.
- Every clickable mark needs a **keyboard route**. The kit's `onClick` makes each item one tab
  stop (Enter/Space fire it) with a hit area of at least 24px, and switches the chart's
  `role="img"` to `role="group"`. For marks you draw yourself, call `api.keyable(node, fn, name)`.
- Give every mark a `<title>` with its value and unit count, and every `<svg>` an `aria-label`
  that states the data (the kit derives one if you pass none).
- A panel with nothing to show calls `api.empty`.
- State the denominator in `basis`, e.g. "recorded on 12 of 40 units in view"; never a typed-in
  figure.

## 10. Data rules and pitfalls

These come from the code comments and three end-to-end runs; each was a real defect.

1. **0 means unknown.** EverGreen writes 0 for unknown numbers and 1950-01-01 / 1905-06-01 for
   unknown dates. The engine nulls them again as a second line of defence. Never sum a null as
   zero, never average over units that lack the field, and always print the denominator.
   "n/r" = not recorded; "—" = not applicable (an owned unit's landlord).
2. **Count lease events by lease state** (§1). A not-started lease is never running; a passed
   expiry is "recorded expiry passed" (holding over, regeared but not updated, or vacated).
3. **Landlord views are third-party and leased-only.** EverGreen leaves landlord names on units the
   client owns; counting them overstated concentration by several million sq ft. An intra-group
   landlord is not exposure. Use `api.thirdParty(rows)`.
4. **An owned unit is not a proven freehold.** Say "owned"; where the record names a third-party
   landlord, title needs confirming.
5. **No gross-ups.** Never multiply a rate by a size into a rent roll; print only recorded `rentPa`,
   captioned with its count.
6. **MEES is England and Wales only**, with two scopes and the status words of uk-rules.md §1
   ("is" only for law in force). If policy moves, set `mees`.
7. **Rebase on the filtered set.** A legend or total read from `api.all` inside `render` froze at
   the portfolio figure while the filtered panel beside it moved. Draw from `rows`; scale bars
   against the unfiltered maximum only when you *want* "share of the portfolio" (and say so).
8. **Findings are static.** They get all units, so say "these do not respond to the filters".
9. **No typed-in figures in copy.** Compute every number, name and date from the rows; a
   pattern that is absent returns `null`. The same dash.js must be safe on any export.
10. **Escape data.** Copy strings are HTML: wrap unit fields in `api.esc()`.
11. **Don't patch the engine's HTML.** Use the drawer model hooks (§4.8), the CSV hooks (§4.10) and
    panel clones (§4.11). Patches break silently when the markup changes.
12. **Selectors and ids.** The page also holds the storyline. Query inside your `el`, never
    `document.getElementById`, and never give an element a bare id. SVG `url(#id)` references are
    document-wide, so use `api.hatch` rather than defining your own pattern ids.
13. **Do not fight the layout.** `main > section` bands, the sticky filter bar and the table header
    are measured at run time. A panel that reads `--filter-h` to size itself recreates a
    ResizeObserver loop that once grew the bar to 1,300px.
14. **Width, not viewBox tricks.** A fixed 470-unit viewBox in a 356px column rendered 10px labels
    at 8px; a fixed 1200-unit one on a phone rendered them at 3px. Use `api.width()`.
15. **Sticky and overflow.** `overflow-x:auto` on an ancestor turns it into a scroll container and
    breaks `position:sticky` against the viewport. Don't wrap panels in scrollers except the
    table's own (which scrolls only when measured too wide).
16. **Map.** The container is isolated (Leaflet's z-index 400–1000 panes used to paint over the
    sticky bar and the app bar). Refit only until the reader moves the map. Street tiles need a
    connection and appear from z9; the portfolio map itself is offline. Place labels avoid
    markers, other labels, other towns' points, the controls and the frame edge.
17. **Drawer.** It sits below the 56px app bar, and its close button is 40px.
18. **The null token** is one style everywhere (`.pill.p-none` / `api.UNK`); `text-transform`
    once rendered it "N/R".
19. **Mobile (390px).** No horizontal page scroll; the filter bar is not sticky; touch targets are
    at least 24px (44px for chips and selects); the table scrolls inside its box; `columns()`
    switches to rows.
20. **EverGreen quirks:**
    - placeholder landlords such as "Not Applicable" (`evergreen_units.py` nulls them);
    - region casing such as "Yorkshire And North East";
    - two records at one address (the mapper disambiguates `short`, and the engine shows `short`
      exactly as given);
    - deal dates of 1950 (null).

    Report them; don't silently "fix" them in copy.
21. **Every figure is derived.** Counts in tooltips, notes, readouts and aria-labels are computed,
    and panel copy counts the rows in view.
22. **Print.** The dashboard prints as ink on white (the KPI band and footer included) in one column,
    with no fixed or sticky bars. On `beforeprint` and the print media query, every chart is re-laid
    out at the A4 content width (688px), so `api.width()` returns 688 and chart text prints at
    10.5px or more. The map is replaced by a printed note, and the table fits the page: columns
    size to their content, cells wrap at spaces only (no figure or word is split), text cells
    hyphenate only where needed, and pills print as plain text. A custom panel that uses
    `api.width()` and the kit prints correctly with no extra work; one with its own fixed widths
    should check it.
23. **Never rewrite the page after it renders.** A MutationObserver that swaps engine sentences
    ("The obligation is the landlord's", "no cross-docked", a subtitle) breaks silently when the
    engine's words change, and it fights every re-render. Every word is a label (§3.2), every
    drawer and popup part is a model with hooks (§4.1, §4.8), and every panel's copy is in `copy`.
24. **One plural rule.** `api.noun` / `api.plural` / `api.pluralWord`, never `n + " landlords"` or
    `Word(n) + " … hold"` ("One landlords hold").
25. **No "group" with one occupier.** When the group dimension is off, say the client ("Acme
    itself", "the client"); `labels.intra*` do it for the stock text, so use them in yours.

---

## 11. Migrating an existing dash.js

Reports written against the earlier engine still assemble and run. Their DOM patches simply stop
matching once the engine does the job itself. Remove what the engine now does:

| if your dash.js… | now |
|---|---|
| regex- or DOM-patches the drawer (Rent per annum, Unexpired, Next review / Break, the passed-expiry note, the MEES note, "request the lease", "Freehold — owned by") | delete the patch; the stock drawer does it (§4.8). For anything else use `drawer.rows` / `notes` / `hero`. |
| derives `isRunning` / `isPassed` from `expired`, `expiry` and `leaseNotStarted` | use `api.state(r)` / `api.running(r)` |
| re-registers the expiry panel only to rename "Lapsed" / "Not recorded" or to split a cliff by year | drop the clone; the stock panel says "Recorded expiry passed" and goes to calendar years itself (`copy.expiry.mode` to force) |
| restyles the landlord tail away from the hatch, or filters out intra-group landlords | drop it; the stock panel does both |
| moves an owned unit's landlord to another field for the CSV | drop it; the stock CSV blanks it and adds "Landlord named on an owned record" |
| adds CSS to keep a wide table's header sticky | drop it; the table measures itself |
| rewrites the readout's "0% of portfolio", or hides town labels under unit circles | drop it; the engine prints "<1%" and hides covered towns |
| sets `title.eyebrow` | remove it (design-system.md: no eyebrow) |
| pins colours from the old palette (`#17E88F`, `#538184`, `#D2785A`… as a company) | remove the pin, or use design-system.md §3b slots |
| rewrites engine text after render (a MutationObserver on the drawer body, a regex on the MEES sentence, the flag words, the subtitle) | delete it: the MEES note now puts the obligation on the minimum in force only; flags read "Cross-docked: no" (`labels.flagNo`); the subtitle never repeats the title (`drawer.subtitle` to change it) |
| filters out the `completeness` or `quality` drawer rows | `completeness` is off by default; quality reads "Recorded as …" (`labels.quality`, or keep the filter) |
| overrides `siteCover` to fix its rounding | drop it: whole percent, rounded half up |
| relabels drawer rows only ("Recorded expiry", "Recorded lease start") | `labels.rows` (§3.2); "Recorded expiry" is now the default |
| re-registers the expiry panel for step-true tick decimals, a sq ft scale for a small chart, or a neutral / lease-state colouring with one occupier | drop the clone unless it adds meaning of its own; the stock panel does all three |
| writes its own "(tenure to confirm)" / "group company" wording for an intra landlord in the popup, CSV or bars | set `labels.intraTag` / `intraSet` / `intraWho` / `intraCsv` once |
| re-registers the table only to carry print CSS | the engine's print table wraps at spaces now; keep only what is yours (dropped columns), or move it to `DASH.set({css})` |
