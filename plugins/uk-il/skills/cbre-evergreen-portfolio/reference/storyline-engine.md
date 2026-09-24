# Storyline engine — author's reference

`report/story.js` is a **classic script** (no build, no imports) that composes the
scroll storyline from `window.Story`. The engine (`engine/story-runtime.js` +
`engine/story.css`, `Story.version` 1.1.0) is prebuilt: React 18, framer-motion 11
(LazyMotion `domMax`), htm. Start from `examples/storyline-example.js` (eleven scenes,
every value derived) and `examples/new-scene-example.js` (a chart invented from
primitives — and the worked example of the print contract, §8).

The engine is a quality floor, not a mould: drop, reorder, rewrite or invent scenes.
What it must never contain is a typed-in fact: every number, name and ranking is
computed from `Story.units` / `Story.meta` at run time. Colours follow
`reference/design-system.md` §3 (semantic states vs categories).

---

## 1. Load order, globals and your own CSS

```
window.STORY_DATA = { units, meta }    // units.json + meta.json
engine/story-runtime.js                // defines window.Story (frozen)
report/story.js                        // YOUR script — calls Story.mount(App) once
dashboard IIFE, then app-shell JS      // defines window.__setView AFTER story.js ran
```
- Inside `#view-story` the page holds only `<div id="root"></div>`. `Story.Shell`
  renders everything else (ground pane, grid overlay, rail, main, footer).
- `Story.setView('dash')` looks `window.__setView` up **at click time**. Never call
  `window.__setView` at load.
- Wrap story.js in `(function () { 'use strict'; … })()`. Top-level `const` in a
  classic script is global and can collide.
- `story.css` is scoped under `#view-story` by the assembler (`cssscope.scope_css`):
  every selector is prefixed with `#view-story`, and `:root` / `html` / `body` at the head
  of a selector **become** `#view-story` — so `body[data-mode="light"] .x` means "the
  storyline in light mode". Fonts are injected once by the assembler (Calibre, Financier
  Display, Space Mono).

**Adding CSS from story.js.** The assembler scopes `story.css` at build time; it cannot
see CSS your script adds at run time. A plain `<style>` you append is **global**: `svg{…}`
or `.note{…}` would restyle the dashboard too. Use **`Story.css(text, id)`**: it parses the
text with the browser's own CSS parser and scopes it exactly like the assembler (prefix
`#view-story`; `:root`/`html`/`body` → `#view-story`; `@media`/`@supports`/`@container`/
`@layer` scoped inside; `@font-face`/`@keyframes`/`@page` left global; selectors that
already start with `#view-story` untouched). Calling it again with the same `id` replaces
the block. `Story.scopeCss(text)` returns the scoped text without injecting it.
```js
Story.css(`
  .mine{max-width:40ch}
  body[data-mode="dark"] .mine{color:var(--on-dark-2)}   /* the storyline's dark mode */
  @media print{ .mine{break-inside:avoid} }
`, 'my-scene-css')
```
Prefer tokens (`var(--ink)`, `var(--sem-risk)` …) over hex so both modes and print work.

---

## 2. htm in five minutes (and the traps)

`Story.html` is `htm` bound to `React.createElement` (with `<>` mapped to Fragment).

```js
const { html } = Story
html`<div className="two" style=${{ marginTop: 44 }}>
  <${Scene} id="s1" mode="dark">…<//>          // component: interpolate it, close with <//>
  <${Reveal} delay=${0.08}><p>…</p><//>
  <${m.circle} cx=${x} cy=${y} r=${4} />       // motion components are VALUES too
  ${rows.map(r => html`<li key=${r.id}>${r.name}</li>`)}
  ${cond ? html`<b>yes</b>` : ''}
  <input disabled onChange=${e => set(e.target.value)} ...${extraProps} />
</div>`
```

| Trap | Do this |
|---|---|
| `<m.circle>` / `<Scene>` as bare tags become unknown DOM tags | `<${m.circle}>…<//>`, `<${Scene}>…<//>` |
| `class=`, `stroke-width=` | `className=`, camelCase SVG attrs: `strokeWidth`, `textAnchor`, `fillOpacity`, `strokeDasharray`, `vectorEffect` |
| `style="margin-top:4px"` | `style=${{ marginTop: 4 }}` (numbers are px); CSS variables work: `style=${{ '--r': r + 'px' }}` |
| HTML entities (`&rsquo;` `&mdash;` `&middot;` `&sup2;` `&nbsp;`) render **literally** | type the Unicode: ’ — · ² £ → “ ”; a non-breaking space is `${' '}` |
| Whitespace containing a newline at a join between text and `${…}` or a tag is **dropped**: `run by\n  ${n} companies` renders `run by8 companies`; `one\n <b>two</b>` renders `onetwo` | keep such joins on one line; break lines only between plain words; or insert `${' '}` |
| Several root elements return an **array** | wrap in `<>…<//>` (always, for PinnedScene children) |
| Arrays from `.map` | every item needs `key=${…}` |
| `${n && html`…`}` with `n = 0` renders "0" | `${n ? html`…` : ''}` |
| `<!-- -->` comments | stripped; fine. JS comments go outside the template |
| Functions as children (PinnedScene, ScrollProgress) | `${({ progress }) => html`…`}` / `${p => html`…`}` |

Nested template literals inside `${}` are fine. Mixed attribute values work:
`className="scene-h ${wide ? 'wide' : ''}"`.

---

## 3. The API — `window.Story`

### Top level
| Export | What |
|---|---|
| `React`, `ReactDOM.createRoot`, `h`, `Fragment` | React itself; `h` = createElement (with `''`→Fragment) |
| `html` | htm tagged template |
| `hooks` | `useState useEffect useLayoutEffect useMemo useRef useCallback useId useContext useReducer` |
| `motion` | `m motion AnimatePresence LazyMotion domMax MotionConfig useScroll useTransform useSpring useMotionValue useMotionValueEvent useMotionTemplate useReducedMotion useInView animate` |
| `kit`, `charts`, `geo`, `fmt`, `data`, `palette` | below |
| `units`, `meta` | getters over `window.STORY_DATA` (also on `Story.data`) |
| `mount(App, el?)` | renders `<StrictMode><ErrorBoundary><LazyMotion features={domMax}><App/>` into `#root`. A render error shows a plain notice and logs `[Story] …` instead of a blank page |
| `setView(v)` | `'dash'`/`'story'` via `window.__setView` (lazy), else sets the hash |
| `css(text, id?)`, `scopeCss(text)` | scoped CSS from story.js (§1) |
| `version` | `'1.1.0'` |

Use `m.*` (not `motion.*`) inside the story: the tree is under LazyMotion.

### `Story.kit`
| Component / hook | Props | Use |
|---|---|---|
| `Shell` | `scenes=[{id,label}]`, `footer` (rendered after `</main>`), `rail=true`, children = scenes | Root of every story: `#ground`, `#grid-overlay`, the rail, scene registration |
| `Scene` | `id`, `mode`, `ground?`, `className` (`'lead'` for the opening), `style` | A ≥100svh statement |
| `PinnedScene` | `id`, `mode`, `ground?`, `viewports=3`, `steps=1`, children = `({progress, step}) => node` | Tall wrapper + sticky one-viewport stage (§6) |
| `GroundSection` | `id`, `mode='light'`, `className`, `style` | A plain `<section>` that still owns the ground |
| `Reveal` | `as='div'`, `delay`, `y=18`, `className`, `style` | The one entrance: fade + 18px rise, once, as soon as any part of the block is more than 40px above the viewport's bottom edge. `.mv`, so it prints; finished under reduced motion |
| `Counter` | `to`, `from=0.62` (or `false`: no count), `format=fmt`, `className` | Hero numeral. **The DOM text is always the final value** (visually hidden), so screen readers, page-text dumps and crawls read the true number; the animated copy is drawn from `data-live` by CSS and is `aria-hidden`. Counts while the number enters and is final once 70% of it is on screen. Safe inline in a sentence (spaces kept). Prints `data-final` |
| `SvgCounter` | `to`, `from`, `format`, `progress`, + any `<text>` props | The same inside a chart: a live `<text>` on screen, a finished one in print. `progress` follows the chart rule on the counter's own position (§7 rule 0) |
| `HeroStat` | `value`, `unit`, `format`, `from=0.62`, children = caption | `.hero-num` Counter + `.hero-unit` + accent bar + `.hero-cap`. Figures and units in `unit` stay lowercase ("sq ft across 9 leases") |
| `Prov` | children, `bare`, `wide`, `style`, `className` | `"<source> · <exportDate> · children"` — every hero figure and chart gets one, with its denominator. Uppercase mono, **but figures and units stay lowercase**: "9 LEASES · 1.84m sq ft · 7 km" (see `figs`) |
| `Rows` | `label`, `rows`, `value(r)`, `name(r)`, `noun=['unit','units']` | `<details>` drawer listing the rows behind a claim |
| `BandKey` | `items=[{label, colour, edge?, kind? \| form?, round?}]`, `className` | Flat legend, mode-aware on every ground. One swatch per FORM in design-system §3, drawn with real borders so it prints as it shows: `kind` `'fill'` (default, square) · `'dot'` (round fill) · `'outline'` (hollow square) · `'ring'` (hollow circle: undated/unknown) · `'dashbox'` (dashed square) · `'dash'` (dashed circle: not started) · `'hatch'` (not recorded) · `'line'` / `'dashline'` (a rule). Or give the MARK's `form` (`'fill'\|'outline'\|'dash'\|'hatch'`) and the matching swatch is chosen: square for bars and segments, round with `round:true` (map dots). `edge`: the outline pale palette slots need on light grounds |
| `Swatch` | `kind`, `colour`, `edge`, `className='bk-sw'` | One key swatch, for a legend of your own (`SWATCH_KINDS` lists the kinds) |
| `figs(text, tag='span')` | | Wraps every figure-with-unit ("1.84m sq ft", "£4.94", "7 km", "29%", a bare "sq ft") in `.fig`, which is never uppercased. Walks strings and plain elements; `tag='tspan'` inside SVG `<text>`. The kit applies it to Prov, HeroStat, Rows, BandKey, table heads and chart labels; call it in uppercase text of your own, or write `<span className="fig">` |
| `ScrollProgress` | `offset=['start end','end end']`, `finishAt=0.7`, children = `p => node` | Progress for something of your own outside a pin (kit charts: pass `progress=${true}`) |
| `Appendix` / `UnitTable` / `UNIT_COLUMNS` | `units`, `title?`, `note?`, `columns?`, `sort?`, `keepConstant=false` | Full unit table; `value` null → "n/r", `na(u)` → "—"; repeated first-column names get their ID. **A column whose value is the same for every unit is dropped** and stated once under the table ("Same for every unit, so not repeated as a column: Company Example Occupier Ltd · EPC not recorded"). The first column always stays; a column with `keep: true` stays; `keepConstant` keeps them all. `constantColumns(units, columns)` returns what would be dropped |
| `CTA`, `DashLink`, `Credits` | | View-switch links; the footer (pass as `Shell footer`) |
| `useChartProgress(ref, progress, finishAt=0.7)` | `ref` on the chart's own box | → the MotionValue to draw with (§7 rule 0). Use it in every chart you build |
| `usePinned(ref)` | | → true while inside a live sticky `.pin-stage` (false on phones ≤820px and in print) |
| `useFitHeight(ref, W, baseH, minH)` | | → viewBox height for a pinned, aspect-flexible chart (§6) |
| `useWidth(ref)`, `COMPACT_PX` (520) | | → the box's rendered width (measured before first paint); the text-floor and phone switches (§9). While printing it returns `PRINT_WIDTH` (§8) |
| `usePrinting()`, `PRINT_WIDTH` (516), `PRINT_LAYOUT_W` (655) | | → true while the page is being printed or exported to PDF (the engine re-renders synchronously on `beforeprint` and on `matchMedia('print')`). The two widths are what `useWidth` and the kit charts lay out at for A4 (§8) |
| `useGround`, `useRegister`, `GROUNDS`, `isLight`, `provSource` | | Build your own scene container |

### `Story.charts`
Every chart is prop-driven. **`progress`** (the one motion prop): omit → rendered finished;
`true` → grows as it scrolls into view and is finished once 70% of it has entered; a
PinnedScene's MotionValue → followed only while the stage is really pinned, and treated
like `true` everywhere else (a static scene, a pin degraded on a phone).

| Chart | Data props | Other props | Use when / not |
|---|---|---|---|
| `Constellation` | `units` (lat/lng-less skipped) | `colour` (css or `u=>css`), **`form`** (`'fill'\|'ring'\|'dash'` or `u=>form`), `focus(u)` (others ghosted), `view='uk'\|'zoom'`, `zoomOn(u)`, `zoom=2.25`, `height='70svh'`, `radius(u,max)`, `title(u)`, `ariaLabel`, `progress` (drives the zoom, live pin only) | Any spatial claim; dark grounds. Skip under ~10 placed units. `form` draws the design system's hollow ring (undated / unknown) and dashed ring (not started) as REAL strokes with no fill, so they print as rings — give them `colour` `var(--sem-unknown)`. Never fake a ring with a ground-coloured fill (it printed as a solid disc). The map sits on a `.knock` backing. **Limit:** one unit of its viewBox is ~1.4 km, so buildings a few km apart (a park, a junction cluster) sit on top of each other even zoomed — see "Maps" below. Unpinned / reduced motion: the finished zoom, clipped; print: the whole map |
| `CompanyKey` | `items=[{key,label?,n,colour,edge?,form?}]` | | Key for a colour-coded map; `form:'ring'\|'dash'` for a state drawn hollow on it |
| `GroupBars` | `rows=[{key,label?,n,sf,colour,edge?,form?}]` | `value(g)`, `sub(g)`, `labelWidth=168`, `max`, `stroke` (css or `g=>css`; default `g.edge`), `strokeWidth=1`, `ariaLabel`, `progress` | Ranked share by group, 2–10 rows. A row that is a STATE, not a group (not started, not recorded), takes `form: 'dash' \| 'outline' \| 'hatch'` |
| `LandlordTree` | `rows=[{key,n,sf}]` largest first | `highlight` (count or `(n,i)=>bool`), `names` (`{key: label}` or `key=>label`), `label` (fn), `baseH=470`, `minH=170`, `title(n)`, `ariaLabel`, `progress` | Concentration across many holders. Names are shown **as given** (legal suffix stripped only). Text on emphasis tiles is `--on-hot` (white on green / ink on the accent). A tile that can't hold its name across or upright gets a **number** and the name goes in a numbered key under the chart; a holder under 1.2% of the floorspace is numbered, under 0.4% unlabelled (its `<title>` still names it). In a live pin the choice is made on the `minH` layout, so labels don't come and go as the stage resizes |
| `ExpiryTimeline` | `years=[{year,sf,n,rows}]` (calendar years) | `undated={sf,n,label?}` (detached hatched block, same scale), **`notStarted`** (`expiryByYear(units).notStarted`, or `[{year,sf,n}]`: a DASHED segment in `--sem-unknown` on top of each year's bar), `highlightYear`, `from`, `to`, `step`, `labelMin`, `xTicks`, `note(row)`, `maxNotes=6`, `baseH=400`, `minH=220`, `ariaLabel`, `progress` | Floorspace by expiry year. Build the data with `Story.data.expiryByYear(units)` → `{years, undated, notStarted: {sf, n, rows, years}}` (running leases, **calendar** years — buckets relative to the as-at date split a late-2027/early-2028 cliff). Not-started leases are never in the running figure: a value label shows the running sq ft, set above the whole column; key them `{form:'dash', colour: palette.semantic.unknown}`. The top gridline is always at or above the tallest column, undated and dashed segments included |
| `CoverageGrid` | `units` | `bands=[{label,test(u),colour}]` (`COVERAGE_BANDS`), `flag` (`COVERAGE_FLAG`: expiry passed, by leaseState), `cols=10`, `sort`, `title(u)`, `ariaLabel`, `progress` | Data completeness, one cell per unit |
| `EpcStack` (= `StackBar`) | `segments=[{label,n,colour,form?,edge?}]` (`hatch:true` = `form:'hatch'`) | **`format`** `'count'` (default, "B or better · 12") \| `'sqft'` ("0.48m sq ft": m sq ft 2 dp for every segment when any is ≥100,000, else exact) \| `'pct'` ("29%" of the bar's own total) \| `(n, seg, total) => string`; **`labels`** `'key'` (default) \| `'inline'`; `form` per segment `'fill'\|'outline'\|'dash'\|'hatch'` ("not started" dashed, "unrated" outline); `noun=['unit','units']`, `barH=62`, `ariaLabel`, `progress` | One part-of-whole bar that totals its OWN segments. **Where the labels go is the `labels` prop, never a surprise:** `'key'` puts a key under the bar (segment order, each segment's own swatch), the same on every screen and in print; `'inline'` centres each label under its segment only when EVERY label fits at the rendered width, otherwise ALL go to the key (never some of each); the root says which ran (`data-labels`). Figures and units are never uppercased |
| `RentScatter` | `rows` | `x(r)=dealYear`, `y(r)=rent`, `size(r)`, `maxSize`, `colour`, `average`, `avgLabel`, `avgLabelAt`, `yMax`, `yTicks`, `xTicks`, `yFormat`, `title`, `ariaLabel`, `progress` | Value vs time, area by size. Skip under ~8 plottable rows |
| `squarify`, `niceStep`, `expiryByYear` | | | Helpers for your own charts |
| `formProps(form, colour, {pid, edge, sw})`, `FORM_SW` (1.75) | | | The kit's one painter for FORMS: spread it on your own `rect`/`circle` (`fill:none` + a non-scaling stroke for outline/dash, `url(#pid)` for hatch) so your marks match the kit's and print as outlines |

Built into every chart, nothing to configure:
- **Text floor.** Rendered text ≥10px at ANY column width: below the width at which its
  smallest label would drop under 10px, each chart lays itself out at one viewBox unit per
  pixel; under `COMPACT_PX` it also switches to its phone arrangement.
- **Grid knock-out.** Each chart box is `.knock` (painted with the live ground), so the
  12-column overlay never reads as gridlines through a plot. Each chart root is `svg.chart`.
- **Collisions.** ExpiryTimeline drops a value label that would collide with another,
  with the highlight notes, or with a taller neighbouring column it overhangs, and puts
  the notes on the side with room above the bars;
  LandlordTree names or numbers every important tile; EpcStack uses a key unless you ask for
  `labels="inline"` and every label fits.
- **Forms.** Every mark that can show a state takes `form` and is drawn by one painter
  (`formProps`), so hollow, dashed and hatched read the same on the map, in a bar, in a
  segment and in the key, on screen and on paper.
- **Pivots.** Every growing mark scales about a pivot given in user units from the live
  geometry, so a chart that re-lays out (a pin shrinking it, a resize) never grows from a
  stale point (§7 rule 10).
- **Print** (§8). Every animated element is `.mv`, finished geometry in the attributes.

### `Story.fmt`
Every number formatter rounds **half-up (away from zero) on the decimal value**, never the
binary float: `(1.005).toFixed(2)` is "1.00", so 1,005,000 sq ft would print as "1.00m"
instead of "1.01m". **Never call `toFixed` on data — use `fixed()`.**
`fmt(n)` "12,480" · `msf(v)` "0.48m" (fixed 2dp) · `pct(a,b)` integer, 0 if b=0 ·
`gbp(v,dp=2)` "£4.94" · `round(x,dp)` · `fixed(x,dp)` "7.4" · `about(x, step, format)`
"about 15m" / "nearly 60%" / "just over 1.40m" (qualifier from the rounding: about <1%,
nearly = rounded up, just over / over = rounded down) · `dmy` "05 Mar 2027" (tables) · `my`
"Mar 2027" · `dShort` "5 Mar 2027" · `dLong` · `year(iso)` · `MONTHS` · `plural` · `count` ·
`llShort(name, {tidyCaps})` strips Ltd/Limited/Plc/LLP and keeps the name as given
(`tidyCaps:true` title-cases an all-caps name — only where you know the source shouts) ·
`words(31)` "thirty-one" · `Words` · `cap` · `magnitude(n)` "twelve million" · `fraction(p)`
"three quarters" · `share(a,b)` "just under a third" · `the(region)` · `list(xs)`.
All tolerate null (return '' or null — dates — so you can fall back to "n/r").

### `Story.data`
**Naming the client:** `meta.client` in full (credits, the opening's first mention),
`meta.clientShort || meta.client` in running prose — the same fields the dashboard uses.
The kit never prints a client name itself (provenance is the source and the date); every
client word in a story comes from `meta`, never typed in.
`units`, `meta` · `sum(rows, f='size')` · `groupBy(rows, f, {sort:'sf'|'n'|false})` →
`[{key, rows, n, sf}]` · `sortBy` · `wavg(rows, f, w='size')` · `uniq` · `maxBy`/`minBy` ·
`has` · `asAt()` · `SQFT_PER_SQM`.
**Lease state** — one vocabulary for every view (`u.leaseState`, written by the mapper):
`'running'` · `'not started'` (signed, starts after the as-at date: **never running**, so
never in WAULT or an "unexpired" figure) · `'passed'` (`yearsToExpiry` is null; use
`yearsSinceExpiry`) · `'undated'` · `'owned'`.
`leaseStateOf(u)` (reads the field, derives it for older files) · `isRunning(u)` ·
`byLeaseState(rows, state)` · `expiryByYear(units)` → `{years, undated, notStarted}`
(`notStarted.years`: the not-started leases by their recorded expiry year, for
ExpiryTimeline's dashed segments — never added to `years`).
Classify leases with these, never with `expired`/`expiry` tests of your own.

### `Story.geo`
`UK_PATH`, `VIEW` {w:661.8,h:1000}, `PROJ`, `projectUnit(lat,lng)` (the projection that drew
the outline — always use it) · `radiusFor(sf, maxSf, k=26)` · `placeable(u)` · `km(a,b)`.

### `Story.palette`  (design-system.md §3 is the source of truth)
- **Categorical** (groups, largest first; no meaning): `slot(i)` → `'var(--oc-n)'` (9+ →
  `var(--oc-other)`); `assign(keys)` → `{key: slot}`; **`edge(i)` / `assignEdges(keys)`** →
  the outline token (pale slots 3, 4, 6, 8 and Other need it on light grounds; it resolves
  to transparent on dark); `light` / `dark` hex lists; `colour(i, mode)`.
- **Semantic** (a state, same meaning everywhere): `palette.semantic.hot | neutral | context |
  passed | risk | watch | secure | owned | unknown | notRec | notRecHatch` (CSS variables);
  `palette.semanticHex.light|dark`. `palette.epc.A … G` (EPC band fills). `unknown` is
  `#5C6B66` on light and a neutral near-white `#E6EAEA` on dark (it was `#80BBAD`: slot 4's
  own celadon and too close to `secure` `#5E9C88`); it is always drawn HOLLOW, `owned`
  always filled.
- **Forms** (`palette.forms`): `'fill' | 'outline' | 'dash' | 'hatch'` — the `form` prop of
  Constellation (`'ring'` = outline), GroupBars rows, EpcStack segments and
  ExpiryTimeline's `notStarted`; `palette.keyKind(form, round)` → the BandKey swatch.
- **Rule:** one chart never uses the same hue for a category and a state. Show a state
  next to group colours as FORM — a ring, a dashed outline, a hatch, a label.

---

## 4. Scene grammar

```js
function App() {
  return html`
    <${Shell} scenes=${PLAN} footer=${FOOTER}>
      ${PLAN.map(s => html`<${s.view} key=${s.id} id=${s.id} />`)}
      <${Appendix} units=${U} note=${NOTE} />
    <//>`
}
Story.mount(App)
```
- **PLAN**: `[{id, label, use, view}]` — `use` is the scene's premise test; filter on it and
  the rail follows.
- **One idea per scene.** Headline = the finding as a sentence with its number; the paragraph
  gives the evidence and denominators; a `Prov` line; one chart; a `Rows` drawer.
- **Layout**: `.two` = text column + chart column (stacks ≤980px; `.two.top`; `.two.flip`
  when the media column comes first on desktop). **`.pin-two`** = the pinned two-column
  layout (text beside a chart inside a `PinnedScene`; §6). `Scene className="lead"` for the
  opening; `.wide` for full-width charts; `closing` + `instruct` + `CTA` to end.
- **Headline precision**: 1 dp ("6.8 years"), whole numbers for counts and sq ft.
- **Appendix + Credits** always: every figure reproducible from the table.
- Copy classes: `scene-h(.wide) scene-sub(.wide|.aside) opening closing instruct prov hero-num
  hero-unit hero-cap accent-bar cta bandkey ckey rows two pin-two lead`. Chart classes:
  `c-lab c-lab-lg c-val c-num c-note c-hot c-grid`; utility: `chart` (chart root), `knock`,
  `mv`, `mv-r`, `onmark`, `onmark-dark`, `onmark-light`, `screen-only`, `print-only`, `sr`.

## 5. Grounds and modes

| mode | ground | text mode | notes |
|---|---|---|---|
| `dark` | #012A2D | dark | default; opening and closing |
| `deep` | #003F2D (CBRE green) | dark | owned / hero-number scenes |
| `midnight` | #032842 | dark | a third dark for alternation |
| `light` | #FFFFFF | light | charts with fine detail |
| `soft` | #FFFFFF | light | alias of light |

One fixed `#ground` pane sits behind everything. Two shared observers — the middle 20%
band of the viewport and the midline itself — call one pick: the scene under the viewport
midline (else the one overlapping the band most; nested → the innermost) sets
`--ground-now` and `data-mode` on `#view-story`. (Per-scene "last to enter wins" left a
short dark scene in light mode on phones; the band alone missed the midline crossing an
edge while both scenes still touched the band, so a light scene kept the dark mode for
~70px of scroll.) The view root's own background is the live ground too. A scene
container of your own gets all of this through `useGround`. `data-mode`
drives the copy colours, `--hot` (accent on dark, CBRE green on light) and **`--on-hot`**
(the text that sits ON an emphasis mark: ink on the accent, white on CBRE green), the
palette's dark steps, the semantic dark steps, chart classes, the overlay, the rail.
Text tokens that pass AA: on dark `--on-dark` #FFF, `--on-dark-2` #C0D4CB, `--on-dark-3`
#80BBAD; on light `--ink` #003F2D, `--body` #435254, `--muted` #5C6B66. Fill-only: `--accent`
on light, `--sage`, `--celadon`, `--warm`, the palette.

## 6. PinnedScene, progress, useFitHeight, `.pin-two`

- `viewports` = wrapper height ×100svh (3–4 typical). `progress` runs 0→1 over the wrapper
  (never read it from the sticky child). Give each mark its own window; reach the finished
  state by ~0.9.
- The stage is one viewport tall under the 56px bar and clips. Aspect-flexible charts (bars,
  treemaps) use `const H = useFitHeight(boxRef, W, baseH, minH)`, `boxRef` on the chart's own
  box. It measures the room the chart really has: **stacked** (chart under the text) —
  everything else in the pin counts; **side by side** (`.two`, `.pin-two`, any row where the
  chart's column has a level neighbour) — only what shares the chart's OWN column, plus what
  sits above/below that row. Anything else inside the chart's box (a numbered key, a legend)
  comes out of the SVG's share. Unpinned (phones, print) it keeps `baseH`.
- **`.pin-two`**: `<div className="pin-two"><div>headline, paragraph, Prov</div><${Chart}/></div>`.
  Sized so a headline plus a **40–80-word paragraph** and a provenance line fit a
  1280×600 stage (smaller headline and paragraph steps under 760px tall); stacks ≤980px.
- Must fit 1536×730, 1366×768 and 1280×600 (`qa_run.cjs`: pinOverflow, underBar).
- ≤820px: pins become stacked scenes; every chart on `useChartProgress` switches to its own
  entry progress automatically.

## 7. Motion rules

0. **A static chart must be finished once it is fully in view.** Anything not inside a live
   sticky pin may grow only while it is still entering the viewport. Drive it from its own
   box (`useChartProgress`, or `progress=${true}` on a kit chart), never a section's
   progress. Numbers obey the same rule (`Counter`, `SvgCounter`).
1. **The end state is the default**: `initial` only when motion is allowed; scroll-linked
   styles gated by `reduced`.
2. `const reduced = useReducedMotion()` in every animated component.
3. **What never moves:** axes, gridlines, tick labels, reference lines, the "now" rule, the
   ground.
4. **Labels ride their mark** (same motion value), and sit at their FINISHED position with
   motion as an offset (§8).
5. **One component per animated item**; never hooks in a loop over data.
6. Transform and opacity only. 7. `Reveal` once, 520ms; counters from 62%; stagger ≤22ms.
8. `scrollIntoView` uses `behavior:'auto'` under reduced motion. 9. High-frequency updates
   write the DOM, not state.
10. **Pivots are px strings from the live geometry**, in the chart's user units:
    `style=${{ scaleY: s, originX: `${x}px`, originY: `${baseline}px` }}`. framer-motion
    resolves a NUMERIC origin (`originY: 1`, `originX: 0.5`) against a box it measures
    once, at mount, and re-measures only when that element's own x/y/width/height/r props
    change — never for a `<g>` whose children moved. A pinned chart that `useFitHeight`
    later shortened (or any resize) then grew its marks from the old point: at 1280×600 a
    run's stacked quarters slid off their axis. A string passes straight through and
    follows every re-render. (`transform-box: fill-box` with `'50%'` origins also works;
    px from the scale you drew with is exact and needs no CSS.)

## 8. THE PRINT CONTRACT — read before drawing any chart

Clients print or save as PDF, usually without scrolling to half the charts. The engine
prints every scene **finished**, whatever was or wasn't scrolled, in pure CSS (no animation
frame runs between `beforeprint` and the print snapshot, and a PDF export need not fire
`beforeprint`). CSS can only do that for elements that follow this contract. Two real
custom scenes printed wrong — a highlight bar missing, brackets and labels missing, rings
missing — because they didn't.

**Checklist for EVERY new chart or animated element:**
1. **`className="mv"` on everything that animates** (every `m.*` element, every group you
   fade). Print sets `.mv{transform:none; opacity:1}`.
2. **Finished geometry in the attributes; motion only as a delta.** x, y, width, height, r,
   d are the finished values; `style` MotionValues only add `scale`/`x`/`y`/`opacity` on top.
   A label at `y=0` moved by an absolute `y` MotionValue prints at the top of the chart:
   put the final y in the attribute and animate the offset (`dy = h * (1 - s)`).
3. **Something that FINISHES moved or dimmed says so**: `'--mv-t': 'translateX(40px)'`;
   dimmed = `style=${{ '--mv-o': .4 }}` **and** a class containing `ghost`
   (`className="mv ghost"`) — QA reads any other translucent `.mv` in print as half-built.
   A layer that exists only DURING the build (a sweep, a cover) is **`.screen-only`**, not
   `.mv`. A plain `.mv` would print it at full strength. Don't finish colour-coded marks
   dimmed — a dimmed category reads as another category.
4. **A circle whose `r` animates** from 0: `className="mv mv-r"` + `style=${{ '--r': r + 'px' }}`.
4b. **Rings and outlines are strokes.** A hollow mark is `fill:none` plus a stroke in its
   colour (`formProps`, or the kit's `form` props) — never a fill in the ground colour,
   which prints as a solid disc on white paper. Key swatches are real borders and print
   their colour (`print-color-adjust: exact` on `.bk-sw`/`.ck-sw` only).
5. **Labels on marks.** Paper is white: print re-points the ground TOKENS to their light
   values, so labels that sit on the ground print ink automatically (no `!important` fills).
   A label that sits ON a mark opts out: **`.onmark`** keeps its screen colours (its fill
   reads a ground token but was chosen for the mark), **`.onmark-dark`** prints white (on a
   dark mark), **`.onmark-light`** prints ink (on a light mark). Text on an emphasis mark
   uses `fill: var(--on-hot)` and needs nothing.
6. **Counters.** HTML: `Counter` (prints `data-final`; QA checks the element's text). SVG:
   `SvgCounter` (its host `<g>` carries `data-svg-final` — never put `data-final` on an SVG
   element: QA reads `innerText`, which SVG lacks, and flags it). A text you update yourself
   needs a `.screen-only` live copy and a `.print-only` final copy.
7. **Build-only layers** (covers a sweep removes, cursors): `.screen-only` (never printed).
8. Pinned scenes print as stacked scenes and each scene stays on one page; nothing to do.
9. **Print re-lays-out every chart for A4.** The content width is about 688px, so a chart
   laid out for a 1100px column would print its labels at 7px. While printing
   (`usePrinting()` true) the kit charts lay out at `PRINT_LAYOUT_W` (655 units: 10-unit
   labels print at ≥10.5px, 8pt), and **`useWidth(ref)` returns `PRINT_WIDTH` (516)**, so a
   chart of your own that follows §9 step 3 (one unit per pixel below its design width,
   compact under `COMPACT_PX`) takes its narrow layout and prints at about 1.33×. A chart
   with a fixed viewBox width gets none of this and prints small: always size from
   `useWidth`. `useFitHeight` returns `baseH` and `usePinned` false while printing. The
   appendix table prints at 7.5pt with columns sized by their longest word: text wraps
   only between words and figures never break (a fixed layout split "rec|orded"); an
   appendix of 11 or more columns prints on landscape pages (`@page wide`), the rest of
   the report stays portrait. Columns constant across every unit are already dropped.
   `--accent` prints as CBRE green (accent text is 1.6:1 on paper); anything else you
   colour for the screen, check on white.
10. **Verify**: the harness's `print.cjs` (DOM under print emulation + a real `page.pdf()`),
   `qa_run.cjs --story` (its print pass checks text size and legibility), or print to PDF
   from a fresh load that never scrolled.

`examples/new-scene-example.js` applies every item: `.mv` deltas, a build-only sweep
(`.screen-only`), a frame that fades in, an `.onmark-dark` label on an ink tab, an
`SvgCounter`.

## 9. Building a new chart or scene (see `examples/new-scene-example.js`)

1. Derive the rows once, at the top of story.js; classify leases with `leaseStateOf`.
2. `<div ref=${box} className="knock"><svg className="chart" viewBox=… role="img"
   aria-label=${computed}>` — a `<title>` per mark.
3. **Text floor, at any width**: `const w = useWidth(box)`. At or above your design width
   draw in the design viewBox; below it draw at **one unit per pixel** (`W = w`), so declared
   sizes are rendered sizes (a fixed 1080 box in a 700px column printed 7px labels); under
   `COMPACT_PX` re-arrange for a phone. Scaling a wide chart down is never a phone layout.
4. Colour: categories → `palette.slot(i)` + `palette.edge(i)`; states → `palette.semantic.*`;
   emphasis once, `--hot`. Chart classes (`c-lab`, `c-num`, `c-grid`…) for text on the ground.
5. `const p = useChartProgress(box, progress)`; every mark's window ends by 1.
6. Per-item components; labels bound to their mark; no moving scales; §8 checklist.
7. Collisions: estimate widths (Calibre ≈0.47em, Space Mono 0.6em + tracking); move, wrap,
   number or drop — never overlap.
8. Wrap in `Scene`/`PinnedScene` + `Reveal` + `Prov`; pinned and aspect-flexible → `useFitHeight`.

### Maps
`Constellation` is a UK-scale overview: at ~1.4 km per viewBox unit it cannot separate
buildings a few km apart (four units on one park become one blob, even at the 2.25× zoom).
When the claim is about a cluster, draw a **zoomed inset**: a second SVG whose projection is
fitted to the cluster's bounding box (`projectUnit` → rescale to the inset's viewBox, pad
10%), with a locator box on the overview. Or a **custom hub map**: nodes placed by
`km(a,b)` from a hub on a radial or a strip, labelled directly. Never nudge real
coordinates to separate dots.

## 10. Pitfalls checklist (each was a real defect)

- [ ] Contrast on what is actually behind the text, both modes (4.5:1 body, 3:1 large). No
      opacity on text; dimming layers floor at a value that keeps labels ≥3:1.
- [ ] `--warm` is a fill; warm text uses `--warm-text`. Accent on light is 1.6:1 → `--hot`.
- [ ] White text on the accent (1.6:1 on dark grounds) → `--on-hot`.
- [ ] A group coloured with a semantic hue (coral = passed) → categorical slots only.
- [ ] Pale palette slots on light grounds without their edge → `palette.edge(i)`.
- [ ] Names re-cased ("LXI REIT" → "LXI Reit") → names as given; `names` prop to relabel.
- [ ] A narrow tile truncated to a stub → upright, or numbered with a key.
- [ ] `toFixed` on data rounded a half-way size down (1,005,000 sq ft as 1.00m) → `F.fixed` / `F.msf`.
- [ ] A counter's page text held 62% of the value → `Counter` (final value is the DOM text).
- [ ] A static chart mid-growth while fully on screen → `useChartProgress` / `progress=${true}`.
- [ ] A 520–880px column dropped chart text under 10px → one unit per pixel below design width.
- [ ] `.two svg` resized icons inside charts → phone rules target `svg.chart` roots only.
- [ ] A two-column pin shrank its chart to the minimum → `useFitHeight` measures the column.
- [ ] Relative-year buckets split a cliff → `expiryByYear` (calendar years).
- [ ] A top gridline below the tallest bar → the scale includes every block drawn.
- [ ] Not-started leases counted as running (WAULT) → `isRunning` / `leaseState`.
- [ ] Print: labels on marks forced to body ink (1.47:1 on green) → token remap + `.onmark*`.
- [ ] Print: marks, brackets and rings missing → the §8 checklist.
- [ ] Print: a fixed-width custom chart printed 7px labels on A4 → size from `useWidth` (§8.9).
- [ ] Print: accent-coloured text (a bracket label) at 1.6:1 on paper → `--hot`, or rely on
      the print remap of `--accent`.
- [ ] A hue picked by slot number (`var(--oc-5)` meant plum; the slots were reordered and
      it became a pale grey-blue label at 3.4:1) → slots only for ranked categories, via
      `palette.slot(i)`; a state (not started) is `palette.semantic.*` plus FORM (a dashed
      outline, `BandKey kind:'dash'`); text is never a palette slot you haven't checked.
- [ ] A short dark scene kept the light mode on a phone → scene containers use `useGround`.
- [ ] A hollow "unknown" dot faked with a ground-coloured fill printed as a solid disc →
      `Constellation form`, `formProps` (real strokes, `fill:none`).
- [ ] "Unknown" read as "secure" on dark (celadon beside green) → `--sem-unknown` is a
      neutral near-white on dark, always hollow.
- [ ] Headline tracking written as `clamp(-.03em, -.0018em * 1vw, …)` is invalid CSS
      (em × vw): the declaration is dropped and the text renders at `normal` → lengths
      only; the engine steps its tracking by media query.
- [ ] A numeric `originX/originY` on a group that later re-laid out grew marks off their
      axis → px strings from the live scale (§7 rule 10).
- [ ] "1.84M SQ FT" in an uppercase mono line → the kit keeps figures lowercase (`figs`);
      in your own uppercase text use `figs()` or `<span className="fig">`.
- [ ] A single occupier's Company column repeated one name in every row → UnitTable drops
      constant columns and states them once.
- [ ] A Number object with a custom `toString` to make EpcStack print sq ft → `format`.
- [ ] A runtime `<style>` restyled the dashboard → `Story.css`.
- [ ] Map dots a few km apart merged → inset or hub map.
- [ ] Hooks inside `.map`; typed alt text; 0 for unknown; landlord concentration from all
      units instead of leased; appendix outside a GroundSection; mode on `<body>`;
      `overflow-x:hidden` on a sticky ancestor; `ch` measures; non-unique pattern ids;
      footer inside `<main>`; htm entities and newline joins.

## 11. Testing

Assemble, then audit the real file (scoped CSS, 56px bar, isolation, script order):
```
python scripts/assemble.py report/ -o out/Client_Portfolio.html
node scripts/qa_run.cjs out/Client_Portfolio.html --story        # or --quick
```
If you drive a browser through the Playwright MCP, note that it **blocks `file://` URLs**:
serve the folder over a local HTTP server (`reference/qa-visual.md`). Requirements: zero
console errors; AA contrast in both modes (only the rail's clipped screen-reader label
excepted); pinned scenes fit 1536×730 / 1366×768 / 1280×600; every scene finished under
reduced motion; every chart outside a live pin finished the moment it is fully in view and
every counter at its final value; chart text ≥10px at every width; no horizontal scroll at
390px; under print (from a fresh load that never scrolled) every mark, Reveal and counter
finished, every pin stacked, no blank page, labels on marks legible, the inactive view not
printed.
