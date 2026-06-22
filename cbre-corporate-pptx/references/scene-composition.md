# Scene composition - the story-led way to build any CBRE deck

This is the default way this skill builds decks. **The storyline drives the layout, not the other way round.** You do not pick a recipe and pour content into it. You work out what the deck must *say*, break it into a narrative, and compose each slide from what *that slide* needs to land. The composer (`scripts/compose.py`) then lays your scene on the safe CBRE grid and sizes every cell's text up to fill its space, so slides are dense by construction. Slide count and shape flex with the story; two decks should look different, and two slides should rarely look the same.

It is the same engine the `cbre-il-account-briefing` skill uses, generalised for any deck. It sits on top of `build.py` (the CBRE visual system), so the brand chrome, palette, typography, render pipeline, sensitivity-label inherit and autofit bake all come for free.

## The governing spirit (read twice; it governs everything)

- **Story-led, not template-led.** Treat every input as a narrative to be told. Decide the through-line first, then compose each slide from what it must say. Never scan a menu of recipes and try to fit the story into one.
- **Narrative-led always.** A deck proves a small number of points in an order a reader can follow: set the context, make the shift or the argument, show the evidence, say what it means. Every slide earns its place in that line.
- **Explain, do not tabulate.** Prose carries the argument; tables, stats and cards are the evidence behind it. If you are tempted to put a sentence in a table cell, it belongs in a `prose` cell.
- **Density from substance, never from tricks.** Fill a slide with *more real, relevant content* when it helps, never with spacing, ballooned fonts or padding. Leftover space is a signal to write more or to add a genuine second beat, not to stretch what is there. Equally, deliberate emptiness around a confident hero stat is a feature, not a hole to fill.
- **No lazy repetition.** A given scene layout should appear at most twice, ideally once. If three slides in a row are "prose then a row of cards", two of them are wrong. Recompose them as a stat strip, a quote, a table, a from-to of chips, a panel-plus-prose split.
- **Readable, not a billboard.** Text sizes up to a readable cap to fill its cell; it never goes tiny and never becomes a giant to fill space.
- **Be creative.** The cells are a palette, not a checklist. Compose the slide the argument wants. The grid only stops overlaps and off-canvas; it is not a template.
- **House rules.** UK English; no em or en dashes anywhere (the composer sweeps them); lead with the point; the box grows to fit the text, the font never shrinks; 9pt floor.

## The model

A deck is an ordered list of **slides**. Each slide has a `kind`:

- `cover` - the polished cover (giant serif title, optional eyebrow, date, and a themes preview band). Delegates to `build.cover`.
- `section` - a chapter divider (giant numeral, serif title, optional lead and "in this section" list). Delegates to `build.section_divider`.
- `scene` - **the workhorse**: a freely composed slide. The composer draws the CBRE chrome (eyebrow, fit-to-text serif headline, one-line lead, footer, wordmark) and then lays out your scene.
- `closing` - the closing slide with optional contact cards. Delegates to `build.thank_you`.

A `scene` is an ordered list of **rows**. Each row has a `weight` (its relative vertical share of the body, default 1) and a list of **cells**. Each cell has a `kind`, an optional `span` (its relative horizontal share of the row, default 1), and the content fields for that kind. Rows stack top to bottom and fill the body; cells split a row left to right.

### The cell catalogue

| Cell | What it is | Key fields |
|---|---|---|
| `prose` | A full explanatory paragraph. The workhorse that carries the argument. | `text`; optional bold lead `label` (e.g. "THE SHIFT"); `max_size` |
| `stat` | A hero value over a caption. Put two to five `stat` cells in one row to make a KPI strip. | `value`, `label` |
| `list` | A numbered or bulleted list of points. | `items` of {`title`, `text`}; `numbered` (bool) |
| `table` | Tabular evidence; the last column reads as the analytical "so what". | `headers`, `rows`; optional `aligns`, `font_size` |
| `panel` | A dark accent side box (a lens / at-a-glance). | `title` + `items` of {`label`, `value`}, or `text` |
| `quote` | A pull quote. | `text`, `attrib` |
| `heading` | A small section label inside the body. | `text`; `size`, `uppercase` |
| `rule` | A thin accent divider line. | (none) |
| `callout` | The CBRE expert-note box. | `title`, `text`; optional `tag` |
| `chips` | A row of rounded pills (tags, countries, status) that wrap. | `items` of strings (or {`text`}) |
| `card` | One numbered card; a row of `card` cells makes a card grid. | `style` ("roman"\|"decimal"), `n`, `title`, `text` or `items`, `accent`, `subtitle` |
| `image` | A picture fit within the cell, centred. | `path`; `alt` |

`cover`/`section`/`closing` carry their own fields (see the worked example and the `build.cover`/`section_divider`/`thank_you` signatures).

## How to compose a deck (the method)

1. **Lock the story first.** From the brief, work out the through-line: the few points the deck must prove and the order to prove them. Write the deck as a list of slides, each with its one-line *point* (the real thing it lands) and its *job* (context, the shift, the evidence, the so-what, the ask). The job decides the shape.
2. **Compose each slide's scene from its point.** Choose the rows and cells that say it best. A shift is a `from_to` of prose or chips; a state of play is a stat strip; an argument is prose plus a panel; evidence is a table or a card grid; a single number is one big `stat` with deliberate space around it; a voice is a `quote`. Vary the shape slide to slide.
3. **Set the tone rhythm.** Alternate dark and light across the deck (roughly 50-70% dark; never three of the same in a row). `cover`/`section`/`closing` default dark; set each scene's `tone`.
4. **Fill with substance, not tricks.** If a slide looks thin, add the real next beat (another stat, a panel, a second prose block) or leave the space balanced. Never pad, shrink, or repeat a layout to fill.
5. **Render.** `compose.render(plan, "Deck.pptx")`. On Windows it runs the resolve pass, inherits the org sensitivity label, and bakes fit-to-text so the deck opens correct with no manual step.

## Per deliverable (the story shapes differ)

- **Client pitch / advisory report:** lead with the client's situation in prose, then the shift or the recommendation, then the evidence (tables, stats, a case panel), then the ask. Dial the voice down (clarity-first).
- **Investor / board deck:** the answer up front (a BLUF-style scene: a thesis headline plus a panel of what is true / what it means / what is open), then the financial story (a multi-year `table` plus a `stat` strip), then the plan. Restrained voice.
- **Market overview / thought leadership:** a strong thesis, forces as prose or a card grid, the data as stat strips and tables, a point of view in a `quote` or `callout`. Dial the voice up (proclamations, maxims).
- **Capital-strategy memo:** the decision framed in prose, the options as a `table` or `tier` of cards, the numbers as a stat strip, the recommendation in a `callout`.

The cells are the same; the *story* decides which scenes exist and how long each chapter runs. Do not force a deck into a chapter it does not have.

## Density and fill rules (enforced by the renderer, upheld by you)

- Prose cells size up to a readable cap (~16pt) and floor near 12.5pt; thin prose in a tall cell means write more, not balloon the font.
- A row of `stat` cells reads as a KPI strip; each hero value is width-capped so a long value never wraps to a stray line.
- Panels and cards stack their content from the top; a too-tall box is a signal to give the row less weight or add content, not to spread.
- Tables: keep the last column an analytical read, not a restatement; cap rows so they do not overrun (roughly 8 network, 7 stakeholder, 6 driver, 5 competitor).
- An empty scene degrades to a clean placeholder callout, never a bare header.

## The palette underneath (and the escape hatch)

Each cell renders with the `build` primitives and helpers (`editorial_header`, `body`, `serif_title`, `table`, `callout`, `chip`, `roman_card`, `decimal_card`, ...). Those primitives, the editorial-bold helpers (`from_to`, `phase_timeline`, `tier_ladder`, `num_row`, `line_of_sight`, ...) and the ~14 recipe functions remain available and are documented in `editorial-archetypes.md`, `layouts.md` and `SKILL.md`. They are the **palette the scenes draw from and the escape hatch** when a slide genuinely needs a bespoke composition the cell set does not cover (a custom chart, the signature Line of Sight device, a one-off split). Reach for them inside a hand-built slide; do not treat them as a menu of slide types the story must fit. If a beat recurs enough to deserve a first-class cell, add a `c_<kind>` to `compose.py` (and document it here) rather than improvising per deck.

## Worked example

```python
import compose

plan = {
  "deck_meta": {"eyebrow": "CBRE | ADVISORY"},
  "slides": [
    {"kind": "cover", "tone": "dark", "eyebrow": "CBRE | ADVISORY",
     "title": "A story-led scene deck", "subtitle": "Composed, not poured into recipes",
     "date": "JUNE 2026", "themes": ["Context", "The shift", "Evidence", "What it means"]},

    {"kind": "scene", "tone": "dark", "eyebrow": "01 | CONTEXT",
     "headline": "The market is consolidating into fewer, larger nodes",
     "lead": "Demand is migrating, not growing.", "footer": "Source: illustrative.",
     "scene": [
       {"weight": 1.3, "cells": [{"kind": "prose", "label": "THE SHIFT",
         "text": "Occupiers are concentrating volume into a smaller number of larger, "
                 "better-connected sites and releasing surplus space at the edges, so the "
                 "market is reshaping rather than expanding."}]},
       {"weight": 0.8, "cells": [
         {"kind": "stat", "value": "46%", "label": "of new leases in Tier-2 corridors"},
         {"kind": "stat", "value": "17", "label": "BTS projects in advanced planning"},
         {"kind": "stat", "value": "EUR 1.40", "label": "energy premium per sqm vs 2022"}]}]},

    {"kind": "scene", "tone": "light", "eyebrow": "02 | PRIORITIES",
     "headline": "Where to focus first",
     "scene": [
       {"weight": 0.4, "cells": [{"kind": "chips", "items": ["Poland", "Germany", "Iberia", "Nordics"]}]},
       {"weight": 1.3, "cells": [
         {"kind": "card", "style": "decimal", "n": 1, "title": "Release", "text": "Dispose of surplus edge sites."},
         {"kind": "card", "style": "decimal", "n": 2, "title": "Reuse", "text": "Retrofit retained sites for energy."},
         {"kind": "card", "style": "decimal", "n": 3, "title": "Redesign", "text": "Plan the combined network."}]}]},

    {"kind": "section", "tone": "dark", "number": 2, "title": "What it means",
     "lead": "From context to action.", "items": ["Release", "Reuse", "Redesign"]},

    {"kind": "closing", "tone": "dark", "title": "Thank you.",
     "contacts": [{"name": "A. Advisor", "title": "Director, I&L", "email": "a.advisor@cbre.com"}]},
  ],
}

compose.render(plan, "Deck.pptx")   # CLI: python scripts/compose.py plan.json Deck.pptx
```

A self-contained smoke test that exercises every slide and cell kind is in `scripts/_smoke_compose.py`.
