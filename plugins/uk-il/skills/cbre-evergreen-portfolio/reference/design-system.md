# Design system: CBRE, as this skill uses it

Read this before writing any scene, panel or chart, and again before QA. Every
rule here can be checked, either by eye on a screenshot or by
`scripts/qa_audit.js` (the check that catches it is named in brackets).

The CBRE world is **pinned**: Financier Display, Calibre, Space Mono, the
greens, the 2px radius. Do not "improve" the brand. Spend creativity on
composition, the visual form of each claim, and motion. Never spend it on new
colours or fonts.

---

## 0. Five principles behind every rule

1. **The number is the design.** Every view has one thing that reads first:
   the headline claim, then its evidence. Squint at the screenshot. If you can't
   name the first, second and third things you see, the hierarchy has failed.
2. **Figure against ground, never tint.** Emphasis comes from inverting figure
   and ground: a dark mark on a light field, or the accent on a dark field.
   It never comes from a paler shade of the same thing. On light grounds the
   emphasis colour is CBRE green. On dark grounds it is the accent green.
3. **Restraint is the brand.** Use one accent per view. Colours are roles, not
   decoration. A shape that carries no data and no state is deleted.
4. **Honest at every size.** Scales don't move, bars start at zero,
   denominators are printed, and a gap is shown as a gap. A chart that
   misleads for one frame of an animation is misleading.
5. **Built, not assembled.** Scrollbars, selection, focus rings, carets,
   numerals, empty states and the 390px layout all carry the design. These are
   the cheapest signals of craft, and the ones generated pages skip most often.

---

## 1. Grounds

| Ground | Hex | Use it for |
|---|---|---|
| `dark` | `#012A2D` | Opening, closing, default dark scene, body behind the storyline |
| `deep` | `#003F2D` | CBRE green. Single-building or "one decisive fact" scenes, drawer header, app bar |
| `midnight` | `#032842` | A third dark tone for variety (capability, cold chain, risk) |
| `light` | `#FFFFFF` | Evidence scenes with dense charts or tables; the appendix |
| `soft` | `#F5F7F7` | Dashboard page ground only (white `#FFFFFF` panels sit on it) |

- In the storyline, **sections never paint their own background.** A scene
  declares `mode`/`ground`, and the single fixed ground pane cross-fades
  (620ms) when the scene owns the middle 20% of the viewport. The view root is
  `isolation: isolate`. Without it the fixed pane (z-index −2) paints *under*
  the view's own background, and every light scene shows dark-green type on
  dark green. [contrast, groundMismatch]
- There is **one** light ground in the storyline. Two near-whites next to each
  other look like a mistake, not alternation.
- A plain section that must own the ground (the appendix, a closing table) uses
  `GroundSection`. Otherwise it inherits the previous scene's dark mode and
  the app bar's contrast collapses on white. [contrast]
- Alternate grounds **with purpose**: dark for statements and hero numerals,
  light for evidence that needs reading. Don't alternate mechanically every scene.

## 2. Colour tokens and verified pairs

| Token | Hex | Role |
|---|---|---|
| `--cbre-green` / `--ink` | `#003F2D` | Headline and strong text on light; emphasis mark on light (`--hot`) |
| `--accent` | `#17E88F` | Emphasis on dark (`--hot`), CTA fill, active tab, focus ring on dark |
| `--on-dark` | `#FFFFFF` | Headlines and bold figures on dark |
| `--on-dark-2` | `#C0D4CB` | Body copy on dark |
| `--on-dark-3` | `#80BBAD` | Labels, provenance, asides on dark |
| `--body` | `#435254` | Body copy on light |
| `--muted` | `#5C6B66` | Labels, notes, provenance on light (provenance may use `#41504B`) |
| `--sage` | `#538184` | Neutral marks (unemphasised bars); large text only on white |
| `--celadon` / `--celadon-tint` | `#80BBAD` / `#C0D4CB` | Secondary marks, key swatches |
| `--wash` / `--wash-2` | `#E6EAEA` / `#CBD0CC` | Receding tiles, track fills, bar backgrounds |
| `--warm` | `#D2785A` | Warning **fill** (lapsed, below target). Not a text colour |
| `--warm-text` | `#E59A7E` | Warning text on dark grounds |
| `--warm-ink` | `#A8523A` | Warning text on light grounds, reset buttons, drawer notes |
| `--plum` | `#885073` | Categorical slot 2 only (§3b). No longer a data-gap colour: gaps are the hatch or a hollow ring |
| `--line` / `--line-soft` | `#CAD1D3` / `#E3E8E7` | Rules and table dividers on light |
| `--grid-dark` / `--grid-light` | `rgba(255,255,255,.38)` / `rgba(0,63,45,.30)` | Chart gridlines. Fainter ones vanish on a projector |
| `--hair-dark` / `--hair-light` | `rgba(255,255,255,.26)` / `rgba(0,63,45,.22)` | Hairlines, key borders |

**Measured text contrast** (WCAG AA: 4.5:1 body, 3:1 for ≥24px or ≥18.66px bold):

| Text token | on dark | on deep | on midnight | on white | on soft |
|---|---|---|---|---|---|
| white | 15.3 | 12.0 | 15.2 | — | — |
| `#C0D4CB` on-dark-2 | 9.9 | 7.7 | 9.8 | 1.6 ✗ | 1.4 ✗ |
| `#80BBAD` on-dark-3 | 7.0 | 5.5 | 7.0 | 2.2 ✗ | 2.0 ✗ |
| `#17E88F` accent | 9.5 | 7.4 | 9.4 | 1.6 ✗ | 1.5 ✗ |
| `#E59A7E` warm-text | 6.8 | 5.3 | 6.7 | 2.3 ✗ | 2.1 ✗ |
| `#D2785A` warm (fill) | 4.8 | 3.8 ✗ | 4.7 | 3.2 ✗ | 3.0 ✗ |
| white @ .62–.80 opacity | 6.7–10.2 | 5.6–8.2 | 6.6–10.1 | — | — |
| `#003F2D` ink | — | — | — | 12.0 | 11.2 |
| `#435254` body | — | — | — | 8.2 | 7.6 |
| `#5C6B66` muted | 2.7 ✗ | 2.1 ✗ | 2.7 ✗ | 5.6 | 5.2 |
| `#A8523A` warm-ink | 2.9 ✗ | 2.3 ✗ | 2.8 ✗ | 5.3 | 5.0 |
| `#538184` sage | 3.5 | 2.8 ✗ | 3.5 | 4.3 (large only) | 4.0 (large only) |

Rules the table implies:
- `--hot` resolves per ground: accent on dark, CBRE green on light. Accent on
  white is 1.6:1 and fails even as a graphic (WCAG 1.4.11 needs 3:1).
- Coral as text is `--warm-text` on dark and `--warm-ink` on light, never
  `--warm`. `--warm` at 10px on deep is 3.8:1 and fails. [contrast]
- **No opacity to make text secondary.** Step down a token instead. Dropping
  provenance to .72 opacity put it under AA on both grounds. On the dark grounds
  white at .62 or above still passes; nothing translucent passes on light.
- Text over a mark (a treemap tile, a stacked bar segment) is checked against
  **the mark**, not the page. White on `--hot` green passes (12:1). White on
  pale sage (1.7:1) and hard-coded white on a wash tile (1.1:1) both shipped
  once. [contrast, which measures the SVG shape under SVG text]
- Everything that changes colour with the ground transitions on the **same
  620ms curve** as the ground. Text that hard-swaps spends that window at
  1–2:1.
- Dashboard light panels: muted on `--wash` is 4.6:1. That is the floor, so
  don't put muted text on anything darker than wash.

## 3. Colour roles: semantic states and categories (FINAL — shared by storyline and dashboard)

Two kinds of colour, and they never share a hue within one chart:

- **Semantic** colours mean a *state* (emphasis, risk, passed, owned, not
  recorded…) and mean the same thing in every chart, in both views.
- **Categorical** colours only tell groups apart (operating companies,
  occupiers, funds…). They carry no meaning of their own.

**The rule:** one chart never uses the same hue for a category and a state.
Colour an operating company with the coral a map also uses for its "expiry
passed" ring, and an undated unit reads as a lapsed one. The
categorical slots below are therefore built from the brand colours that are
*not* semantic. If a chart needs both (group colour + a state), draw the state
as **form**: a ring, a dashed outline, a hatch or a label, never as a second
fill hue that could be a group.

### 3a. Semantic palette

| State | Token | Light ground | Dark grounds | Notes |
|---|---|---|---|---|
| Emphasis (the one highlighted mark) | `--hot` / `--sem-hot` | `#003F2D` | `#17E88F` | One per chart. Accent on white is 1.6:1: never |
| Neutral mark (unemphasised) | `--sem-neutral` (= `--sage`) | `#538184` | `#538184` | 2.8:1 on deep: add a stroke there |
| Context / receding | `--sem-context` | `#E6EAEA` | `rgba(255,255,255,.14)` | Tiles and tracks behind the data |
| Passed / lapsed / expired | `--sem-passed` | `#A8523A` | `#E59A7E` | Also the text colour for the state |
| Risk: due ≤2 years, below a standard | `--sem-risk` (= `--warm`) | `#D2785A` | `#D2785A` | A fill; as text use `--warm-ink` / `--warm-text` |
| Watch: due in 2–5 years | `--sem-watch` | `#E0A33C` | `#E0A33C` | 2.2:1 on white: outline or label it on light |
| Secure: >5 years, compliant | `--sem-secure` | `#3F7F66` | `#5E9C88` | |
| Owned (freehold, no lease event) | `--sem-owned` | `#435254` | `#CBCDCB` | Neutral dark: owned sits outside the urgency scale |
| Not recorded / undated (areas) | `--not-rec` + `--not-rec-hatch` | `#CBD0CC` hatched `#9AA8A2` | same | 45°, 6–7px pitch. Last or set apart, counted, never merged into a real category or a year |
| Not recorded / undated (dots, rings) | `--sem-unknown` | `#5C6B66` | `#E6EAEA` | A HOLLOW ring (no fill): hollow = unknown. On dark it is a neutral near-white: it was `#80BBAD`, which is categorical slot 4 and ΔE 10 from secure `#5E9C88`, so an unknown ring read as a secure lease (now ΔE 30). Owned `#CBCDCB` is near it but always FILLED |
| Not started (signed, not yet running) | `--sem-unknown`, dashed | `#5C6B66` | `#E6EAEA` | Dashed outline. Never counted as running (WAULT, unexpired) |

Lease-urgency ramp (dashboard map and table, storyline expiry charts):
passed `#A8523A` → ≤2y `#D2785A` → 2–5y `#E0A33C` → >5y `#3F7F66`; owned
`#435254`; undated = hatch or hollow ring; not started = dashed ring. Always
print a word or a date beside the colour. Never red/green as the only difference.

### 3b. Categorical palette (groups, largest first)

| Slot | Token | Light ground | Dark grounds | On white | Edge on light (`--oc-n-edge`) |
|---|---|---|---|---|---|
| 1 | `--oc-1` | `#032842` midnight | `#6E97C7` | 15.2 | none |
| 2 | `--oc-2` | `#885073` plum | `#B27CA0` | 6.1 | none |
| 3 | `--oc-3` | `#DBD99A` wheat | `#DBD99A` | **1.5** | `rgba(0,0,0,.30)` |
| 4 | `--oc-4` | `#80BBAD` celadon | `#80BBAD` | **2.2** | `rgba(0,0,0,.30)` |
| 5 | `--oc-5` | `#778F9C` midnight tint | `#778F9C` | 3.4 | none |
| 6 | `--oc-6` | `#C0D4CB` celadon tint | `#C0D4CB` | **1.6** | `rgba(0,0,0,.30)` |
| 7 | `--oc-7` | `#7F8480` cement | `#7F8480` | 3.8 | none |
| 8 | `--oc-8` | `#96B3B6` sage tint | `#96B3B6` | **2.2** | `rgba(0,0,0,.30)` |
| Other | `--oc-other` | `#E6EAEA` | `#A3B3AE` | **1.2** | `rgba(0,0,0,.30)` |

- Every slot is ≥3:1 on all three dark grounds (lowest: cement 3.2:1 on deep).
  On light grounds slots 3, 4, 6, 8 and Other are under 3:1 and **must** carry
  their edge (`stroke: var(--oc-n-edge)`, 1–1.5px) or a direct label.
  `Story.palette.assignEdges(keys)` / `edge(i)` return the right stroke; on
  dark grounds the edge tokens resolve to `transparent`.
- Slots 1–4 are well separated (ΔE ≥ 36). **From slot 5 on the hues sit close
  to each other and to the neutral sage**: above four groups every mark needs
  a direct label or a key, and above eight the tail folds into "Other (n)".
  Don't add hues, and don't reuse the semantic ones to stretch the list.
- Order is by size: slot 1 goes to the largest group, so the strongest
  colour carries the most floorspace. Keep a group's slot fixed across every
  scene and panel (assign once, from the whole portfolio).
- Semantic hues that are **never** categories: `#003F2D`, `#17E88F`,
  `#538184`, `#D2785A`, `#A8523A`, `#E0A33C`, `#3F7F66`, `#435254`, the hatch
  greys.

### 3c. EPC bands (light grounds)

| Band | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| Fill | `#23604A` | `#3F7F66` | `#80BBAD`* | `#E0A33C`* | `#D2785A` | `#A8523A` | `#A8523A` |
| Token | `--epc-a` | `--epc-b` | `--epc-c` | `--epc-d` | `--epc-e` | `--epc-f` | `--epc-g` |

\* under 3:1 on white: outline (`--oc-edge`) or label. F and G share a fill
(both below the legal minimum E); the letter is always printed. No EPC =
the not-recorded hatch. On dark grounds A–B use `#5E9C88`, F–G `#E59A7E`
(the tokens swap). Group bands by the question: "B or better" = `--sem-secure`,
"below B" = `--sem-risk`, "none on record" = hatch.

### 3d. Sequential ramp

(quality, bands): `#80BBAD → #5E9C88 → #3F7F66 → #23604A → #003F2D`.
White text needs `#3F7F66` or darker (4.7:1+). Use ink text on the two
lighter steps.

### 3e. Forms, and the key swatch for each

A state shown next to group colours is a FORM, and the same form is used on the
map, in a bar or segment, and in the key. Every storyline chart takes a `form`
prop (Constellation, GroupBars rows, EpcStack segments, ExpiryTimeline's
not-started segments); your own charts use `Story.charts.formProps`.

| Form | Meaning | Mark (map dot / bar or segment) | Key swatch (`BandKey kind`) |
|---|---|---|---|
| fill | a real value, a group, a running lease | filled disc (white rim on dark) / filled bar | `fill` square · `dot` round |
| outline | undated, not recorded, unknown (dots), unrated | ring: no fill, 1.75px stroke in `--sem-unknown` / hollow bar | `ring` round · `outline` square |
| dash | not started (signed, not yet running) | dashed ring (3 / 2.4) / dashed hollow bar (4 / 3) | `dash` round · `dashbox` square |
| hatch | not recorded (areas) | — / 45° hatch, `--not-rec` + `--not-rec-hatch` | `hatch` |
| line | a reference line, a rule, a leader | — / a stroke | `line` · `dashline` |

- **Outlines are strokes, never a fill in the ground colour.** A run faked a
  hollow dot with a ground-coloured fill; on white paper it printed as a solid
  disc and the encoding was lost.
- Key swatches are real borders (not box-shadows) and carry
  `print-color-adjust: exact`, so a key prints its colours with Chrome's
  "Background graphics" off (the default).

## 4. Type

**Faces** (inlined once by `assemble.py`. Space Mono is TTF and must be
declared `format('truetype')`, or it silently falls back to Courier):

| Face | Weights | Only for |
|---|---|---|
| Financier Display | 400 (600 exists; almost never needed) | Headlines, hero numerals, the closing, the instruction line, dashboard section heads, drawer title, KPI values |
| Calibre | 400 / 500 / 600 / 700 | Paragraphs, UI text, table text, chart category names, place labels |
| Space Mono | 400 / 700 | Labels, provenance, axis and value numbers, chips, table figures, counts. It marks **data, measurement and source**. Never paragraphs, never headlines, never decoration |

**Scale** (the engine's values. New roles must slot into this ladder, not
invent one):

| Role | Face | Size | Line | Tracking | Colour dark / light |
|---|---|---|---|---|---|
| Opening statement | Financier | clamp(40px, 6.4vw, 108px) | 1.0 | −0.045em → −0.014em | white, `em` in accent / ink |
| Scene headline | Financier | clamp(30px, 3.6vw, 58px) | 1.06 | −0.030em → −0.014em | white / ink |
| Closing | Financier | clamp(34px, 5vw, 84px) | 1.06 | −0.036em | white. Always under 0.9× the opening (at 390px: 34 vs 40) [openingNotLargest] |
| Instruction (the one action) | Financier | clamp(26px, 2.6vw, 40px) | 1.18 | −0.02em | accent |
| Hero numeral | Financier | clamp(52px, 7.4vw, 120px) | 0.92 | −0.042em, margin-left −0.06em | accent / CBRE green |
| Evidence paragraph | Calibre | clamp(17px, 1.4vw, 21px) | 1.52 | 0 | on-dark-2 / body; `b` at 500 in white / ink |
| Aside | Calibre | 17px | 1.52 | 0 | on-dark-3 / muted |
| Hero caption | Calibre | clamp(14px, 1.2vw, 17px) | 1.55 | 0 | on-dark-2 / body |
| Provenance | Space Mono | 10px, uppercase (figures and units lowercase) | 1.5 | +0.10em | on-dark-3 / `#41504B` |
| Chart label (category) | Space Mono | 10px, uppercase (figures and units lowercase) | 1 | +0.14em | on-dark-3 / muted |
| Chart number (axis, value) | Space Mono | 10–11px, **never uppercase** | 1 | +0.04em | on-dark-2 / body; value in white / ink |
| Chart note (annotation) | Space Mono | 11px | 1.1 | +0.02em | on-dark-2 / body |
| Dashboard h1 | Financier | clamp(54px, 6.4vw, 104px) | 0.95 | −0.038em | ink, second line sage (large only) |
| Dashboard h2 / panel h3 / finding | Financier | clamp(30px, 3.2vw, 44px) / 24px / 23px | 1.04–1.16 | −0.028 / −0.02em | ink |
| KPI value | Financier | 44px (hero tile clamp 56–76px) | 1 | −0.028em | accent on dark band |
| Dashboard body / notes | Calibre | 13–15px | 1.5–1.6 | 0 | body / muted |

Rules:
- **Tracking scales inversely with size.** Large display type tightens and small
  mono labels loosen. A constant em value across a 3× size range crowds the
  small end and loosens the large. The engine steps the opening and headline
  tracking by viewport width (media queries: −0.014em at 390, −0.027/−0.018em
  at 1024, −0.039/−0.027em at 1536, −0.045/−0.030em from 1740/1660). Never
  write it as `em × vw` (`clamp(-.03em, -.0018em * 1vw, …)`): multiplying two
  lengths is invalid CSS, the declaration is dropped and the text renders at
  `normal` — which is what shipped until a run measured it. [tracking.cjs]
- **Figures and units stay lowercase inside uppercase mono** (provenance,
  chart labels, table heads, drawer labels): "9 LEASES · 1.84m sq ft", never
  "1.84M SQ FT". The storyline kit wraps them in `.fig` itself; in your own
  uppercase markup use `figs()` or `<span class="fig">`.
- **Numerals:** `font-variant-numeric: tabular-nums lining-nums` wherever
  numbers line up or animate (tables, axes, KPIs, counters). Units in mono stay
  lowercase ("2.10m", "sq ft"). "1.5M" beside "2.10m" reads as two units.
- **Fixed decimals within a set.** "0.4m" beside "0.44m" reads as a data error,
  so format millions of sq ft to 2dp everywhere in one chart.
- **Measure:** paragraphs 551px (wide variant 760px), set in **px, not ch.** A ch
  measure resolves against each element's own font size, so one token gave two
  column widths. Headlines max 17ch (wide 24ch), `text-wrap: balance`.
  Paragraphs `text-wrap: pretty`.
- **The opening must be decisively larger than every headline after it**, and
  the closing lands harder than an ordinary headline. That ratio makes the rest
  read as consequence.
- **Rendered text floor: 10px, including SVG, at ANY width.** SVG font sizes
  are in viewBox units: rendered size = declared size × (rendered width ÷
  viewBox width). An 880-unit viewBox in a 575px column turned 10 into 6.5px,
  a 1080-unit chart in a 700px column into 7px, and at 390px wide into 3px. The
  engine's charts measure their box and, below their design width, lay
  themselves out at one unit per pixel; under 520px they also re-arrange for a
  phone (fewer ticks, labels above bars). Do the same in your own charts.
  Never just scale a wide chart down. [smallText]
- No eyebrow or kicker label above a headline. The headline carries its own
  weight. (The engine keeps an `.eyebrow` class for legacy only. Don't use it.)
- `font-display: block`. A Georgia flash before Financier lands looks broken
  on a projector.

## 5. Space, grid and layout

- **Width:** storyline max 1360px, gutter `clamp(20px, 6.5vw, 64px)`. Dashboard
  max 1520px, gutter 32px (18px at ≤860px).
- **Spacing scale:** 4 8 12 16 24 32 48 64 96. Groups are tight and separations
  are generous. Leave more space above a heading than below it.
- **Scene padding:** `min(13vh, 120px)` plus the 56px bar at the top. On screens
  ≤820px tall, `min(7vh, 44px)`. A scene centred in a bare 100svh sits 28px low
  and collides with the wordmark.
- **Two columns** (`.two`): `minmax(0,.92fr) minmax(0,1fr)`, gap
  `clamp(32px, 5vw, 90px)`, collapsing at ≤980px. Relate the columns by a
  shared cap-line (`align-items: start`) whenever one side is much taller.
  Centring a short text column against a tall SVG opened 300–450px voids.
- **DOM order is mobile reading order.** Put the claim before the visual in the
  DOM, even if the desktop layout puts the visual on the left.
- **Specificity trap:** put desktop multi-column rules inside
  `@media (min-width: …)`. A three-class desktop selector outranked the
  one-class mobile override and kept a two-column layout at 390px, which
  letterboxed a map to 133px.
- **Radius** 2px everywhere. **Shadows** only where something floats: the
  drawer and popups (`0 4px 12px / 0 24px 60px` green-tinted), and the stuck
  filter bar (a soft 1px/8px). No cards inside cards, and no card grid as page
  structure.
- **The 12-column hairline overlay** is a faint texture on the storyline
  ground. It must not show through a chart's plot area, where it reads as
  x-gridlines that don't match the data. Give plot areas an opaque backing, or
  keep the overlay out of them.
- **Fixed bar clearance:** nothing may sit under the 56px app bar, and that
  includes fixed layers such as a drawer (`top: var(--bar-h)`, not `top: 0`). [underBar]

## 6. Motion

| Token | Value | Used for |
|---|---|---|
| `--d-reveal` | 520ms, `cubic-bezier(.2,0,.2,1)` | the one text entrance per block |
| `--d-ground` | 620ms, same curve | ground cross-fade and every mode-dependent colour |
| `--d-count` | 1400ms / scroll-linked, `cubic-bezier(.16,1,.3,1)` | hero numeral counter |
| dashboard | 120ms (hover), 180ms (state), 220ms drawer `cubic-bezier(0,0,.25,1)` | UI feedback |

**What may move**
- A text block arrives **once**: fade plus an 18px rise as soon as any part of it
  is 40px above the viewport's bottom edge (a "35% visible" rule left tall blocks
  blank on a phone). Its end state is the default, and `initial` applies only
  when motion is allowed. With JavaScript off or reduced motion on, the page is
  complete.
- A chart outside a live pin is **finished by the time it is fully in view**; it
  may only grow while it is entering. Inside a pin it builds with the reader's
  scroll, labels riding the marks.
- Marks grow **from their baseline** (bars scale from the axis, cells fill,
  dots scale in). Emphasis lifts: the key item takes `--hot` as the pin
  progresses and the rest recede, floored at an opacity that keeps their labels
  at 3:1 or better.
- The ground cross-fades. The map zooms **as one transform** (all nodes
  together).
- A hero counter runs from 62% of the final value to the final value, linked to
  scroll, and is final once it is on screen. It never counts from 0, which
  reads as a gimmick. The page TEXT is always the final value (the animated
  digits are drawn by CSS and hidden from assistive tech): a counter whose DOM
  held 62% of the figure was read wrongly by screen readers and crawlers.
- **Print** shows every scene finished, whatever was scrolled (the print
  contract, storyline-engine.md §8).
- Stagger ≤ 22–45ms per item. Cap the total delay at about 0.5s.

**What never moves**
- **Scales:** axes, gridlines and tick labels. No parallax on anything that
  encodes value. Gridlines drifting ±3% with scroll made the tallest bar read
  as the next gridline up. [scaleDrift]
- **A value label apart from its mark.** Drive the label from the same motion
  value as its bar. Placed at the final height while the bar grows, it floats
  free for the whole scroll. [labelDrift]
- Body text after it has arrived. No scroll-jacking, no snap, no bounce or
  elastic, no infinite loops.

**Reduced motion:** every scene renders in its finished state, including bars
at full height and cells filled. An ungated opacity motion value renders a chart
blank in any non-scroll context: reduced motion, print, a screenshot. JS
`scrollIntoView({behavior:'smooth'})` must check the media query, because CSS
cannot reach it. [rmHidden, hiddenText]

**Performance:** animate transform and opacity only. Never animate layout
properties. Pinned progress comes from the wrapper's scroll progress, never
from the sticky child (which reads 0 for the whole pin).

## 7. Charts

**Pick the form from the question:**

| Question | Form |
|---|---|
| When do decisions fall due? | Columns by year, weighted by floorspace, one year lifted |
| Who controls the estate? | Treemap or ranked bars (leased only), top holders emphasised |
| What share meets a threshold? | One 100% stacked bar with the gap hatched |
| Price against time | Scatter (deal year × £ psf), bubble area = size, weighted-average rule |
| Where, and how clustered | Map / constellation, circle area = floorspace |
| How complete is the record? | Unit grid, one cell per unit, bands per field |
| Ranking of a few categories | Horizontal bars with direct labels, sorted |

Rules:
- **Gridlines:** 3–5 horizontal lines, in `--grid-*`, on the **same scale** as
  the marks. The top line is at or above the maximum (round up to a nice step).
  Bars always start at zero. No vertical gridlines on bar charts.
- **Axis labels:** mono, ≥10px rendered, units given once ("m sq ft", "£ per
  sq ft"), sparse year ticks (every 4–5 years) on the axis.
- **Direct labels beat legends.** Use a legend only for maps and for more than
  ~5 series. Put it next to the first chart that uses the encoding, not a scene
  later.
- **Value labels:** on or directly beside the mark, bound to its motion, fixed
  decimals. Label above a threshold if the chart is dense, but never leave a
  key item unlabelled.
- **Annotation:** the leader line starts **on** the mark and is computed in
  the same coordinate system as the bars (one leader used a different scale
  and floated 38px above). Use an elbow, at least 16px. Notes are set in
  `c-note`. [floatingLeader]
- **Collisions:** labels never overlap each other or the marks they don't
  describe. When a label is enlarged or moved, re-check its neighbours; a
  bigger average-line label ran into a data point. Move the label to the clear
  end of the line. [overlapText, labelMark]
- **Tiles:** every tile that matters carries a label. Use two lines when the
  tile height is over 42 units, one line when it is over 26. Truncate with the
  face's average advance (Calibre ≈ 0.47em) and keep the full name in
  `<title>`. A key landlord was once left as an unlabelled green block.
  [unlabelledTile, truncated]
- **Emphasis:** one element per chart takes `--hot`, and everything else is
  sage or wash. Text ON the emphasis mark is `--on-hot` (white on CBRE green,
  ink on the accent — white on the accent is 1.6:1).
- **Categories vs states (§3):** group colours come from the categorical slots
  only; a state shown alongside them is a ring, a dashed outline, a hatch or a
  label, never another fill that could be a group.
- **Time axes use calendar years** for lease events. Buckets relative to the
  as-at date ("0–1 years") split a cliff that straddles New Year into two
  columns and hide it.
- **The scale covers everything drawn**, including a detached "undated" block:
  the top gridline is at or above the tallest mark.
- **Gaps:** "not recorded" is hatched, detached and counted. It is never a zero,
  and never plotted at a placeholder date (1950-01-01 is EverGreen's null).
  [placeholderDate]
- **Pinned charts that can change aspect** (bars, treemaps) take their height
  from `useFitHeight`. Width, and so type size, never changes.
- **Accessible name:** `role="img"` plus an `aria-label` **computed from the
  data** (largest item, highlighted item, the denominator). Hard-coded
  alt text drifts: one named a minimum rent and year that the data did not
  hold. [a11yName, badTokenHidden]
- **Never:** 3D, drop shadows on marks, gradients in bars, dual axes, donut or
  pie for more than 5 parts or for time, rainbow scales, a chart whose data a
  sentence would carry better.

## 8. Maps

- **Overview basemap = vector land** (`engine/land.json`): UK `#FFFFFF`, context
  land `#F2F5F4`, sea `#DAE3E0`, coast `#A3B3AE`. Raster basemaps bring baked-in
  foreign labels, can't take CBRE type, sit over markers and blur at
  fractional zoom.
- Street tiles only from z9, their labels only from z11 (at z10 the provider's
  UK label tiles are empty), and our own labels step aside at that point. If
  tiles fail, show the offline note as a separate block under the map.
- **Place labels:** a curated tiered list, Calibre 11.5–12.5px with a white
  halo, placed by collision search (8 directions × 2–3 distances). Never on
  another town's point, never over a marker, never cut by the frame (4px inset,
  18px clear above the attribution). A leader appears only when a label is
  pushed ≥34px out. A 10px leader reads as a dash ("Town name —"). [labelMark, clipped]
- **Markers:** circle **area** ∝ floorspace (`r = 5 + 17·√(size/max)`), white
  2px stroke, largest painted first so small ones stay clickable. Filtered-out
  units dim to grey at 0.3 and stay visible (a part-of-whole view needs the
  whole).
- **Fit bounds after layout settles** (ResizeObserver), and stop refitting once
  the reader moves the map. A fit taken before the legend column filled left
  the map a quarter-zoom out and upscaled the tiles.
- **Storyline constellation:** the same nodes recur across scenes and move
  only by transform. Their persistence carries the narrative. Use a cos(lat)
  equirectangular projection at UK scale.

## 9. House details (components)

- **App bar:** 56px `#003F2D`, "CBRE" in Calibre 700 at 0.14em, view switch in
  mono 10px. Active tab accent on green. Nothing hides under it.
- **CTA:** accent block, green text, mono 11px uppercase at 0.16em, padding
  17×26px, radius 2px, trailing →, hover `translateX(3px)`. One per view.
- **Focus:** a 2px outline (accent on dark, CBRE green on light), offset 2px.
  Use an outline, not a box-shadow, because `overflow: hidden` ancestors clip a
  shadow away. Programmatic focus targets (`tabindex="-1"` headings focused on
  a view switch) show no ring. [progFocusRing]
- **Selection, caret, scrollbar:** accent selection with green text; themed
  scrollbar (sage thumb on dark, celadon on light).
- **Provenance line** under every claim-bearing visual: `EverGreen export ·
  <export date> · 31 of 44 units`, in mono 10px uppercase. It is what stops a
  hero numeral being a vanity metric.
- **Rows drawer** under a claim: `<details>` whose summary reads "Label — n
  units", with the rows in mono 11.5px, scrolling after 230px.
- **Null tokens:** `n/r` = not recorded (mono, muted, dashed pill in tables),
  and `—` = not applicable (a freehold has no landlord). Use one spelling
  everywhere, with no `text-transform` on it ("N/R" crept in once).
- **Targets** at least 24×24px, and 44px on touch layouts. Grow the hit
  area, not the mark (the scene rail keeps a 2px tick inside a 24px button).
  [smallTarget]

## 10. Imagery and icons

- No photography, stock, AI imagery or illustration. The data is the image.
- No emoji. No Unicode glyphs standing in for icons: prefer a word ("group
  landlord") to "⌂". Typographic arrows (→) in a CTA are fine.
- If an icon is unavoidable, draw it as inline SVG: a 1.5px stroke,
  `currentColor`, 16 or 20px, one family throughout.
- A diagram is drawn from data or not at all.

## 11. Anti-patterns (generated-page tells). Reject on sight

| Tell | Instead |
|---|---|
| Gradient text, gradient buttons, gradient bars | Solid tokens; emphasis by weight, size or figure/ground |
| Glassmorphism, backdrop blur, glows, neon edges | Opaque grounds; shadows only on floating layers |
| Emoji or glyph icons | Words, or authored SVG |
| Card soup: a grid of same-size icon + heading + text cards | Composition by hierarchy and proximity; a table or a list |
| Everything centred | Left-aligned text on a grid; centre only a single statement |
| Hero-metric template (big number, small label, three stat tiles) with no denominator | One hero numeral per scene, with its unit, caption and provenance |
| "Overview", "Key insights", "Portfolio summary" headlines | A sentence with a number and a consequence (storyline-craft.md) |
| Eyebrow or kicker above every heading; section numbers as decoration | Let the headline speak; number only a list the reader refers to |
| Lorem-style filler ("robust", "diverse", "strategic", "leveraging") | The specific fact: building, landlord, year, sq ft |
| Rainbow palette, a new hue per chart | The categorical order in §3; one emphasis per view |
| Chart junk: 3D, shadows, heavy borders, gridlines on every axis, legends for two series | §7 |
| Scroll reveal on every element, fade-up for its own sake, parallax | One reveal per block; motion only where it carries meaning (§6) |
| Tiny grey labels to "look refined" | 10px rendered floor, tokens that pass AA |
| Monospace used as a "techy" costume on prose | Mono only for data, measurement, provenance |
| Rounded pill buttons, large radii, soft blobs | 2px radius |
| Decorative stats that no chart or table supports | Only ledger figures, each with its denominator |
| Averages presented alone | The distribution behind them (the cliff, the tail) |
| A dashboard that is the storyline again, or a storyline that is a dashboard | Storyline argues, dashboard lets the reader explore |
| "0" for unknown, 1950 on a timeline, NaN in a tooltip | n/r, hatched gaps, computed labels that survive empty filters |

## 12. Author self-check before handing to QA

1. Assemble, open, and run `scripts/qa_audit.js` at 1536×730 and 390×844 on at
   least your new scenes and panels. Fix every P1.
2. Every text token on every ground you used is in the §2 table and passes.
3. Every chart: scales still, labels bound, ≥10px rendered at 390px,
   computed `aria-label`, provenance line with denominator.
4. Every scene and panel renders complete with reduced motion.
5. Nothing under the app bar, in any view, drawer included.
6. No hard-coded figure in copy, labels or tooltips that the data can compute.
   Numbers in headlines written as words are ledger values too.
7. No hue is both a category and a state in any one chart; pale categorical
   slots on light grounds carry their edge (§3).
8. Print to PDF from a fresh load that never scrolled: every chart finished,
   labels on marks legible, no blank page (storyline-engine.md §8).
9. Every figure is rounded half-up on its decimal value (`F.fixed`, `F.msf`):
   1,005,000 sq ft is 1.01m, never 1.00m.
10. Every state shown beside group colours is a FORM (§3e) drawn as a real
    stroke or hatch, and its key swatch has the same form; on paper a ring is
    still a ring.
11. No "SQ FT", "M" or "KM" in an uppercase line: figures and units are lowercase
    (§4).
