# Design system

Inherited wholesale from the CBRE longlist dashboard
(`CBRE_Property_Dashboard_Normal.html`) so a tour app and a longlist read as
one family. **Do not introduce a new colour, font or radius.** If a change is
genuinely needed, change `assets/tour_template.html` so every future tour
inherits it, and say so in the handover.

## Tokens

```
--cbre-green  #003F2D   bands, buttons, serif headings
--dark-green  #012A2D   KPI band, footer, tab bar
--accent      #17E88F   left card border, KPI numbers, active pill, em text
--sage        #538184   section titles, travel pins
--celadon     #80BBAD   meal pins
--celadon-tint#C0D4CB   ghost button hover, dev chip border
--dark-grey   #435254   body copy
--light-grey  #CAD1D3   hairlines, footer text
--bg-soft     #F5F7F7   page background, empty states
--muted       #6E7C77   labels, secondary copy
--radius      2px       everything. The system is sharp-cornered.
```

Type ladder:

```
--font-display  Financier Display  headings, KPI numbers, card titles
--font-body     Calibre            all body copy
--font-mono     Space Mono         eyebrows, labels, times, chips, footer
```

The **mono-eyebrow** is the signature move: uppercase, `letter-spacing:.14em`
to `.18em`, 9.5-11px, muted or sage. Any label, time, tag, or KPI caption is
Space Mono. Any heading or number-as-headline is Financier Display. Body prose
is Calibre in `--dark-grey`, never green.

Font files live in `assets/fonts/` and are base64-embedded at build time.
Space Mono is a **TTF** declared `format('truetype')`; the others are woff2.
Getting that hint wrong makes some browsers silently fall back to Courier.

## Component motifs

| motif | rule |
|---|---|
| **Card** | white, 1px `--line` border, **4px left border** coloured by stop kind, 2px radius |
| **Left border colour** | view `--accent`, travel `--sage`, meal `--celadon`, meet `--dark-green` |
| **Hero** | full-bleed `--cbre-green`, white Financier headline, accent `em`, then a 56x4px accent bar (`.los`) |
| **KPI band** | full-bleed `--dark-green`, mono label, big accent Financier number, muted sub |
| **Button** | green fill, white text, 2px radius, 600 weight. Ghost = white fill, green text, green border |
| **Chip** | 2px radius, mono, uppercase, 10px. `.dev` tinted, `.attend` solid green, `.tbc` sage, `.off` dashed |
| **Section title** | mono sage uppercase, preceded by a 16x2px accent bar |
| **Spec row** | label left mono muted, value right, dotted bottom hairline |
| **Footer** | full-bleed `--dark-green`, mono `--light-grey`, hidden when empty |

## Layout

Three regimes, and they are genuinely different layouts:

```
< 720px     single column. Bottom tab bar (fixed). Day order: head, map, timeline.
720-1023    same column, capped at 820px, roomier.
>= 1024px   full-bleed bands with inner content capped at 1400px.
            Hero is static, not sticky. Tab bar becomes an inline control row.
            Day becomes two columns: timeline left, sticky map right.
```

The day view emits three siblings inside `.daygrid`:

```html
<div class="daygrid">
  <div class="dayhead-slot">...</div>
  <aside class="mapcol">...</aside>
  <div class="stopcol">...</div>
</div>
```

Phone stacks them with flex column, so the map sits between the heading and
the timeline. Desktop drops them into named grid areas with the map spanning
both rows and `position:sticky`.

## Traps that have already bitten

- **`width:100%` on capped inner wrappers is load-bearing.** `.main` is a flex
  item of `.app`; auto cross-axis margins switch off `align-self:stretch`, so
  without `width:100%` the column collapses to fit-content and sits visibly
  inset from the full-bleed green bands.
- **The tab bar must live in the flow before `.main`.** It is lifted to the
  bottom of the screen by `position:fixed` on phones. If it sits after the
  footer in the DOM it renders *below the footer* the moment it becomes
  static on desktop.
- **Never `var L` in the runtime.** Leaflet owns that global; shadowing it
  disables every map with no error.
- **Leaflet caches container size at construction.** Fitting bounds against a
  zero-size map silently yields max zoom and a blank tile. Always
  `invalidateSize()` then fit, deferred by two animation frames.
- **A sticky map under a sticky header overlaps.** The desktop header is
  deliberately `position:static`.
- **A centred desktop dialog eats clicks while invisible.** The sheet needs
  `pointer-events:none` when closed, because unlike the phone bottom sheet it
  is not translated off-screen.
- **Never write a build placeholder as literal text** in `tour_runtime.js` or
  its comments; it survives injection and trips the unfilled-placeholder
  check.

## Deliberate omissions

- No satellite or topographic basemap. The tour needs roads and town names.
- No CARTO tiles: the free tier now needs an API key and watermarks the map.
- No property photos. They are what made the dashboard 16 MB; a tour app is
  used on mobile data on a bus.
- No compare tray, no filter toolbar, no drive-time isochrones. Those belong
  to the longlist dashboard. This artefact answers "where are we going next".
