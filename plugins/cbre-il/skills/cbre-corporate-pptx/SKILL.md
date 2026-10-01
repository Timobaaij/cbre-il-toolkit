---
name: cbre-corporate-pptx
description: >-
  Builds or edits a polished, fully CBRE-branded PowerPoint deck (.pptx) — the right CBRE typography (Financier Display and Calibre), the brand colour palette, and a clean, story-led layout where each slide is designed around the point it makes, not poured into a template. Plans the storyline first, decides what each slide must show, then builds it, including bespoke diagrams. Also refines existing decks in place. Use it whenever you want a CBRE deck, CBRE slides, a CBRE-branded or client-pitch presentation, an investor deck, advisory report, market overview, or capital-strategy memo, or any time you reference a CBRE template or ask for a polished .pptx in CBRE's house style.
---

# CBRE Corporate Deck Builder

A layout engine that owns every coordinate, and a composition vocabulary rich
enough that you rarely need one.

## Three rules above everything else

1. **Story, then picture, then build.** Settle what the deck argues before you
   touch a slide. For each slide, decide what the reader must *see* to get the
   point. Only then choose how to build it. Never start from a layout.
2. **The slide follows the story.** No cell, skeleton or audit outranks the
   argument. If the story needs three slides that look alike, or a picture no
   cell draws, the story wins.
3. **Use creativity.** The best slide in a deck is often one no catalogue
   contains: two routes on a map, a cost line that crosses another, dots that
   cluster. Draw it (see "Bespoke diagrams").

Everything below serves those three rules. Where a mechanic seems to conflict
with them, the rules win and the mechanic is the bug.

**The division of labour is the whole design.** You decide what each slide says
and what *shape* says it best. The composer resolves that into rectangles: it
partitions the safe CBRE grid, sizes text up to fill each region, and draws the
brand chrome. You never write an `x`. Because the engine owns geometry, you are
free to be adventurous with composition — the failure modes that make people
timid (overlapping boxes, text bleeding off a card, a squashed grid) are not
reachable from here.

Three audits run on every save and tell you the truth about what you built:
tone balance, skeleton variety, and geometry soundness.

**Read `references/scene-composition.md` before composing.** It carries the
scene model and the full cell catalogue.

## The build path

**Toolkit update check (run once, first).** Run `python scripts/version_check.py`. It prints a one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published (otherwise it is silent); it does nothing but a single public version lookup, never blocks the build, and is safe to ignore.

```python
import sys
from pathlib import Path
for _p in (Path("scripts"), Path.home() / ".claude/skills/cbre-corporate-pptx/scripts"):
    if _p.exists():
        sys.path.insert(0, str(_p.resolve())); break
import build, compose

plan = {
  "deck_meta": {"eyebrow": "CBRE | ADVISORY"},
  "slides": [
    {"kind": "cover", "title": "...", "subtitle": "...", "date": "JUNE 2026"},

    # A skeleton carves the slide up; the cells say what it means.
    {"kind": "scene", "tone": "dark", "shape": "rail", "eyebrow": "01 | CONTEXT",
     "headline": "One argument, evidence stacked beside it",
     "cells": [
       {"kind": "prose", "label": "THE READ", "text": "..."},
       {"kind": "stat", "value": "46%", "label": "..."},
       {"kind": "stat", "value": "17",  "label": "..."}]},

    # Or lay the rows out yourself when the shape is bespoke.
    {"kind": "scene", "tone": "light", "eyebrow": "02 | THE SHIFT",
     "headline": "From build-up to impact",
     "scene": [
       {"weight": 1.4, "cells": [{"kind": "from_to", "from": "Build-up", "to": "Impact"}]},
       {"weight": 1.0, "cells": [{"kind": "prose", "text": "..."},
                                 {"kind": "prose", "text": "..."}]}]},

    {"kind": "closing", "title": "Thank you."},
  ],
}
compose.render(plan, "MyDeck.pptx")
```

Then **look at it** (see "Judge the deck", below). That step is part of the
build, not an optional extra.

## Six skeletons

A skeleton decides how a slide is *carved up*. It never decides what the slide
says, which is why it does not constrain the argument the way a slide template
does. Give it a flat `cells` list.

| `shape` | The carve | Reach for it when |
|---|---|---|
| `bands` | Full-width rows, one per cell | A single tall device, or a plain stack |
| `rail` | Full-height left column beside an independent stack | A claim on the left, its evidence on the right |
| `hero` | One dominant cell over a supporting strip | One idea, then what follows from it |
| `mosaic` | Two cells per row | Parallel evidence that invites comparison |
| `ledger` | Narrow read left, wide evidence right | A short interpretation against a table or ladder |
| `poster` | One cell taking most of the slide, a quiet strip beneath | A blockbuster number or a statement |

Omit `shape` and pass an explicit `scene` (rows of cells) when you want a shape
none of these give you.

### Nesting

Any cell can be `{"kind": "split", "scene": [...]}` — a scene inside a cell.
That is how asymmetric composition happens: quadrants, L-shapes, a rail whose
right side has its own internal rhythm. A partition of a partition is still a
partition, so nesting costs nothing in safety. Four levels deep is the limit,
and you will hit a legibility wall long before that.

## Nineteen cells

The vocabulary each region draws from. Full fields in
`references/scene-composition.md`.

**Text and evidence** — `prose` (carries the argument), `list`, `table`,
`quote`, `heading`, `callout`, `panel`, `rule`, `image`, `chips`, `card`.

**Numbers** — `stat`. Pass `"scale": "hero"` for the one-blockbuster-number
slide; it lifts the size cap so a lone figure can genuinely dominate.

**Editorial devices** — the shapes that make a deck look composed rather than
filled in:

| Cell | Says |
|---|---|
| `from_to` | A shift from X to Y (the destination is emphasised) |
| `timeline` | Where we are in a sequence, with a "we are here" marker |
| `tiers` | What is primary versus secondary |
| `directions` | Strengthened / refocused / deprioritised |
| `bars` | Categorisation by weight or intensity |
| `sightline` | The signature CBRE rule device (max one per slide) |
| `draw` | Any picture the others cannot draw: your own diagram, bounded to the cell |

Each device is bounded to its cell and declares a minimum height. Ask for one
in a region too small and the build stops with the specific fix, rather than
drawing something squashed.

## Step 1: plan the story

Before any slide exists, answer four questions in writing:

| Question | Why it matters |
|---|---|
| Who reads this, and what must they decide or believe afterwards? | Sets the ending. Every slide moves the reader towards it. |
| What is the one-sentence through-line? | If it does not fit in a sentence, the deck has no spine yet. |
| What does the reader already know, and what do they doubt? | Decides where the deck starts and which slides carry proof. |
| What is the ask, or the next step? | A deck without one ends on a shrug. |

Then draft the **headline sequence**: one full-sentence headline per slide,
read top to bottom with nothing else. This is the ghost deck. If the
headlines alone do not tell the story in order, no layout will rescue it.
Fix the sequence first: reorder, merge, cut. Each headline should answer the
question the previous one raised.

When a deck runs past roughly eight slides, give the reader a way to keep
their place: a roadmap slide early on, and a small tracker or numbered eyebrow
on the slides that follow it. Use it only when it helps; a short deck does not
need one.

## Step 2: decide what each slide must show

For each headline, ask: **what must the reader see to grasp this point in
five seconds?** Name the picture before naming any cell.

| If the point is... | The picture is usually... |
|---|---|
| A trade-off between two forces | Two things pulling apart: two routes, two lines, two weights |
| A distance, reach or catchment | A simple map or schematic of dots and lines |
| A sequence or dependency | A track, a timeline, steps that hand over to each other |
| A shift | From X to Y, with the destination emphasised |
| A choice between options | The options side by side, with the deciding criterion obvious |
| One number | The number, large, with space around it |
| A list of what we heard, or open questions | Short, parallel statements, the same shape every time |

The table is a prompt, not a lookup. If the point has a shape of its own, draw
that shape.

Write it into a **story spine** before building. One row per slide:

| # | Headline (the point) | Reader question it answers | Picture | Build | Tone |
|---|---|---|---|---|---|
| 2 | Prime rents have outpaced the wider market for three years | Is this market still worth entering? | Two lines that pull apart over time | composed: a `draw` line pair over a one-line read | light |
| 4–6 | One slide per shortlisted site: where it wins, where it falls short | How do the sites compare? | The same layout on each, so the reader compares like with like | composed, `parallel_group: "sites"` | light |
| 8 | Selling now releases EUR 40m before the market softens | Why sell this year? | One number with space | `poster`, *why:* one number and nothing else | dark |

The spine is a real artifact, not an in-head sketch — building first is how
decks drift back to one repeated layout. When working interactively, show the
headline sequence and the spine to the user and agree them before rendering.

## Step 3: build each slide from its picture

Now choose how to draw what the spine says. In order of preference:

1. **A composed scene** of rows and cells, when the cells can draw the picture.
2. **A bespoke diagram** (`draw` cell), when the picture is something no cell
   draws. This is a first-class path, not a fallback.
3. **A named skeleton**, only when the slide is genuinely conventional, with a
   `shape_why`.

A preset in the Build column needs its `why` written out, and it carries into
the plan as `shape_why`.

## Bespoke diagrams

When the picture is a map, a network, a cost curve, a footprint or any other
shape the cells do not draw, use a `draw` cell. You write a small function that
draws with the `build` primitives inside the rect it is handed; the composer
places that rect on the grid and checks afterwards that nothing escaped it.

```python
def two_routes(s, x, y, w, h, tone):
    ink = build.COLORS["white"] if tone == "dark" else build.COLORS["green"]
    # place dots and lines as fractions of w and h, never as fixed inches
    ...

{"kind": "draw", "name": "two_routes", "fn": two_routes, "min_h": 2.0, "span": 1.2}
```

Rules for a good diagram:

- Draw relative to `x, y, w, h`. Fixed coordinates break when the cell moves.
- Use brand colours only, and the tone-conditional accent (`compose._accent(tone)`).
- Keep it schematic. A diagram explains one mechanism; it is not a data dump.
  Label directly on the drawing rather than adding a legend.
- If the diagram goes off its rect, the build stops with `DiagramOutOfBounds`.
  Fix the drawing, or give the row more weight.
- If the same diagram recurs across decks, promote it to a `c_<kind>` cell in
  `compose.py` and document it, rather than copying the function around.

**Write in the CBRE voice as you draft.** Read the `cbre-tone-of-voice` skill
(`${CLAUDE_PLUGIN_ROOT}/skills/cbre-tone-of-voice/SKILL.md`, or
`~/.claude/skills/cbre-tone-of-voice/SKILL.md` standalone) and calibrate volume:
investor, board and advisory decks dial the voice **down** (clarity-first,
restrained, still opinionated); market overviews and thought leadership dial it
**up**. Board-grade conventions are in `references/spacing-and-rules.md` §12–13.

**Client-facing decks.** Let the brief set the story shape. A follow-up after
a meeting, a tender response, a market update and a recommendation each need a
different structure. Never reuse the last deck's structure by default.

- Open with the client's situation in their terms before CBRE's offer.
- Word a judgement as a judgement. Never present something the client only
  raised as an option as if it were fact.
- By default, name the client company but not the individuals, unless the
  deck needs them (for example a stakeholder map).

## The three audits

They run automatically on `save()` / `compose.render()` and print a report.
Pass `shapes_strict=True` / `geometry_strict=True` to turn findings into errors
(the smoke test does).

**Geometry is a rule; tone and shape are guides.** `audit_geometry` protects
the file: text off the canvas or colliding is always wrong. `audit_tones` and
`audit_scene_shapes` protect against drift into a template, which is a real
risk, but they cannot read the story. When one warns, ask whether the story
needs what you built. If it does, keep it and say why in the plan
(`shape_why`, `parallel_group`, or a note to the user). Never add a slide,
change a tone or vary a layout only to quiet an audit.

| Audit | Enforces | Fails when |
|---|---|---|
| `audit_tones` | Dark/light rhythm | Outside a 40–60% dark band (target 50/50) |
| `audit_scene_shapes` | Layout variety **and** composition discipline | Consecutive slides share a skeleton; one shape used more than twice; named skeletons exceed a third of the deck; a `shape` has no `shape_why`, or two share the same one; fewer than 70% distinct skeletons |
| `audit_geometry` | Layout soundness | Text bleeds off canvas, runs into the wordmark band, or collides with other text |

`audit_scene_shapes` is the one that keeps decks interesting. Variety used to be
a request; it is now a check, and checks are what hold.

### Skeletons are the exception, not the menu

**Compose the scene the argument wants. That is the default and it should be
what most slides do.** A scene is rows and cells; nesting a `split` cell gives
you asymmetry, rails and L-shapes, and the geometry audit means you cannot break
the file by trying. There is no safety reason to reach for a preset.

The six named skeletons (`bands`, `rail`, `hero`, `mosaic`, `ledger`, `poster`)
exist so a genuinely conventional slide does not have to be rebuilt from
scratch. They are **not a catalogue to pick from**, and the audit enforces that:

- At most **one scene in three** may use a named `shape`.
- Any scene that does must carry **`shape_why`** — a sentence saying why that
  shape beats a scene composed for this point. Two slides may not give the same
  reason; a reason that fits two slides justified neither.
- At least **70% of scenes** must have distinct skeletons.

If a slide's point has a shape of its own — and most do — build it. Inventing a
composition the cell set has never produced before is the expected outcome, not
a risk. When you cannot say in one specific sentence why a preset is better than
what you would compose, that is the answer: compose it.

### Deliberate parallelism is not repetition

Two slides that walk two comparable routes *should* look alike, so the reader
can compare them side by side. Declare it and the audit records it as
intentional instead of flagging it:

```python
{"kind": "scene", "parallel_to": 5, "scene": [...]}   # slide 6 mirrors slide 5
```

`parallel_to` is for pairs. For a **series** of three or more (three options,
four markets, the open questions a client raised) give every member the same
`parallel_group` name:

```python
{"kind": "scene", "parallel_group": "questions", "scene": [...]}   # slides 3, 4, 5
```

Members must genuinely share a skeleton, or the series is invisible to the
reader and the audit says so. Past five slides a series reads as a template
and the audit warns.

### The fourth check is your eyes

The three audits are code, and code cannot see. No assertion catches "this deck
reads as templated" or "slide 6 is a wall of grey". So the last step before
delivery is to **look at the whole deck at once, against a real bar**:

```bash
python scripts/critique/critique.py MyDeck.pptx
```

It tiles your deck into one contact sheet, tiles the gold reference set into
another, and prints the questions to answer. Answer the story questions first,
because they are the ones code cannot check:

- Read only the headlines, in order. Do they tell the whole story?
- Does each slide show its point, or only state it?
- Is there a slide where the picture fights the point, or where text is doing
  a job a diagram would do better?
- Does any slide look the way it does only because a cell or audit pushed it
  there? View both images, then fix the
**plan** and re-render. When building, never adjust a coordinate by hand: that
is what the geometry audit exists to prevent. (A deck already edited by hand is
different; see "Editing an existing deck".)

The gold set lives in `scripts/critique/gold/` and is deliberately **not** in
`references/`. It is a yardstick read at critique time and nowhere else. Do not
read it while composing: a finished slide shown to the author becomes a template
to copy, and copying is the failure this whole system is built to prevent.

`audit_geometry` reads the heights in the file, and autofit boxes only carry
their *true* height after the resolve pass. So its verdict is exact on Windows
(where resolve runs) and indicative on Linux.

## Judge the deck

Rendering to PNG has always existed here for measurement. Use it for judgement
too — no assertion catches "this reads as templated" or "slide 6 is a wall of
grey", and a model looking at the whole deck at once catches both.

```bash
python scripts/contact_sheet.py MyDeck.pptx --cols 4
```

One image, every slide, numbered, under the inline image limit. **Look at it
before delivering.** What you find revises the *plan* — change the shape, split
the slide, write more — and you re-render. It never means nudging a coordinate.

On Windows the sheet comes from real PowerPoint with the licensed CBRE fonts and
is true to file. On Linux it comes from LibreOffice, which substitutes fonts:
judge composition and density only, and say that a PowerPoint pass is required
before delivery.

## Density, and the confidence to leave space

Clean beats full. A slide carries one point; white space and alignment are what
make that point land. Cut words before adding shapes: if a line wraps to a
stray word, shorten the sentence rather than the font or the margin.

Density comes from substance. When a slide looks genuinely thin the fix is
another real beat — a second stat, a panel, the next point — or balanced space. Deliberate
emptiness beneath a hero stat reads as confidence; the same stat with a coverage
band crammed under it to fill the space reads as nervousness. When a tall device
needs room, drop the `lead` rather than squeezing.

Optional fields (`subtitle`, `lead`, `pillars`, `themes`, `items`, a closing
`callout`) are opt-in. Attach one when the slide has a real second beat. A
"CBRE VIEW" strap on every slide is what templated looks like.

Let slides end at different heights. Bottoming out at a common y reads as a
template; different depths read as composed.

## Brand DNA

Full visual spec: `references/brand-guidelines.md` (official CBRE 2026 v17).
Exact chrome measurements (the invariant frame every slide shares):
`references/chrome-spec.md`.

- **Tone rhythm.** Dark `#012A2C` and light white alternate across the deck,
  landing on an even **50/50** split (40–60% band before `audit_tones` warns).
  Split-tone counts as dark. The house pattern: dark carries the cover, section
  dividers, statement moments and the close; **white carries the content slides
  that do the work.** `COLORS["cbre_green"]` (`#003F2D`) is available for a
  corporate-primary look.
- **Hierarchy.** Eyebrow (small uppercase sans, primary accent, thin rule
  under) → serif headline → optional intro → content. Editorial print, not a
  template.
- **Accents are tone-conditional.** The primary accent depends on the ground it
  sits on, because neither colour reads on the other:
  - **On dark** → Wheat gold `#D8D898`.
  - **On white** → Accent Green `#17E88F`.

  This is the corporate-template rule and it is not a preference. It is applied
  automatically by `compose._accent(tone)` and by `build.eyebrow(...)`, so you
  get it for free unless you hard-code a colour; don't. Celadon mint `#80B8A8`
  stays the **secondary** accent on either ground (card stripes, table header
  bands, vertical bars beside an intro). `build.CHART_COLORS` is charts only.
- **Type.** Financier Display for headlines and stat values, ≥ 20 pt, title case
  (`serif_title` enforces both). Calibre Light / Semibold for body, eyebrows and
  table headers. Space Mono for date stamps. Only weights installed on standard
  CBRE Windows exist — "Financier Display" and "Calibre Semibold", not
  "Financier Display Light" or "Calibre Bold"; fallbacks are Times and Tahoma.
- **Brand anchors.** Every slide gets the official logo artwork and the
  confidential footer automatically. The wordmark is artwork, never typed — if
  it is missing from `scripts/assets/` the build warns and falls back to type,
  which is not brand-compliant. See `assets/README.md`.
- **Line of Sight.** `line_of_sight(...)` or the `sightline` cell. Horizontal is
  breadth, vertical is depth; one per layout. `brand-guidelines.md` §5.
- Every shape is drawn from scratch on a blank slide. PowerPoint master layouts
  are not used.

## Canvas

13.333 × 7.5 in (16:9). Safe area ~0.55 in left/right, ~0.45 in top, ~0.32 in
bottom (chrome lives in the bottom strip). All primitive `x`/`y`/`w`/`h` are
inches. `build.ED_X`, `ED_W`, `ED_SAFE_BOT` give the editorial content box.

## Text sizing

**The box grows to fit the text; the font is never shrunk.** The library always
uses `SHAPE_TO_FIT_TEXT` and clamps every size to a 9 pt floor. PowerPoint's
"shrink text on overflow" (`TEXT_TO_FIT_SHAPE` / `normAutoFit`) is not exposed —
`shrink=True` raises `TypeError`, so prior knowledge from other pptx libraries
will not transfer. When something does not fit, restructure: drop a row, split
the slide, choose a denser shape.

Bullets are real PowerPoint bullets — `body(..., bullets=True)` or
`apply_real_bullets(shape)`. A typed `•` has no hanging indent, so wrapped lines
collapse under the glyph; `body()` raises if it sees one.

Four helpers, by situation:

| Helper | For |
|---|---|
| `Flow.title()` / `.body()` / `.eyebrow()` | A free-flowing top-of-slide stack. Auto-registers for resolve. |
| `CardFlow(...).text()` | Inside a card you drew yourself. Cursor-checked; raises `CardOverflowError` rather than cramming. |
| `container_text(...)` | A single element inside a fixed container (table cell, callout body). |
| `_text(...)` | Anything bespoke. |

If you have drawn a `_rect` and are about to hand-place a title at `cy + 0.10`
and a body at `cy + 0.36`, use `CardFlow` instead — that offset pattern is what
silently collapses bottom padding to nothing.

## Editing an existing deck

Most decks are refined after the first build: the user edits in PowerPoint,
the client gives feedback, a second version is needed. Once a deck has been
touched by hand, rebuilding it from the plan would throw that work away. Edit
it in place instead. In this mode, and only in this mode, adjusting a
position directly is allowed.

| Step | How |
|---|---|
| Back up first | Copy the current file to an `Archive` folder beside it, with a dated or labelled name, before any change. |
| Work on a copy | Copy the deck to a local temp path, edit that, render it, check it. |
| Find shapes by their text | Shape names repeat and change when users edit. Match on the text a shape holds, and stop if the match is missing or ambiguous. |
| Replace text cleanly | Set the first run and remove the others, so no fragment of the old sentence survives. Remove extra paragraphs too. |
| Respect the user's edits | Before a script touches a slide, compare it with what you last saved. If the user changed it, keep their version and apply only your change. |
| Keep sibling decks aligned | When a short and a long version share slides, make every change to both, and list any deliberate difference. |
| Save safely | Before copying back, check the delivery file has not changed since you read it (compare hashes). After copying, re-read it and confirm the change is there. On OneDrive, ask the user to close the deck first; AutoSave can overwrite a scripted save. |
| Look at it | Render the changed slides and view them before reporting. |

Still apply the three rules. A change that makes a slide state its point
without showing it, or crams it, is a regression even if the text is better.

## Escape hatch

A bespoke picture inside a normal slide is a `draw` cell, not this. Use the
escape hatch only when the whole slide must break the scene model (a
full-bleed map, a custom chart that needs the full canvas): build it from
primitives on a `build.blank()` slide and save it into the same deck. `references/layouts.md` has the recipe signatures,
`references/editorial-archetypes.md` the archetype sketches. Both are raw
material — reaching for a whole-slide recipe when a scene would do is how decks
end up looking alike, and `audit_scene_shapes` will notice.

One hard constraint out here: a shape with `w <= 0` or `h <= 0` makes PowerPoint
reject the entire file as corrupt. `_assert_pos_dims` catches it at build time.
The usual cause is a back-solved width (`w = panel - sibling - gap`) going
negative — put variable-width siblings in a fixed column.

## Rendering

| Environment | Pipeline | Fidelity |
|---|---|---|
| Windows | `to_png.ps1` / `to_pdf.ps1` (PowerPoint COM) | True to file, real CBRE fonts. Prefer this. |
| Linux sandbox | `soffice --headless` + `pdftoppm` | Fonts substituted; composition check only. |

```powershell
powershell -ExecutionPolicy Bypass -File scripts/to_png.ps1 -In MyDeck.pptx -OutDir slide_imgs
```

Keep review images ≤ 2000 px wide. PowerPoint must not have the same file open
interactively — it will fight for the COM handle.

**On Windows, build to a local temp path, verify, then copy to the OneDrive
delivery path.** Rendering straight from a synced folder can open a stale cached
copy and show pre-edit content. If a preview contradicts an edit you know you
made, suspect this first.

`build.save()` also inherits the org sensitivity label and bakes fit-to-text, so
decks open labelled and correctly fitted. `resolve=False` skips the
render-and-measure pass for fast iteration; run a full save before delivery.

## Files

- `scripts/compose.py` — the scene composer: skeletons, cells, nesting, shape audit. **The default build path.**
- `scripts/build.py` — the visual system: primitives, recipes, palette, fonts, the resolve/label/bake save pass, the three audits.
- `scripts/contact_sheet.py` — render the deck and tile it into one reviewable image.
- `scripts/_smoke_compose.py` — exercises every cell and skeleton under strict audits. Run it after changing either module.
- `scripts/_smoke_story.py` — exercises the `draw` cell (including its bounds check) and `parallel_group`.
- `references/scene-composition.md` — the scene model and full cell catalogue. **Read first.**
- `references/editorial-archetypes.md` — archetype sketches: job → composition.
- `references/layouts.md` — recipe parameter lists.
- `references/philosophy.md` — design rules from the reference deck.
- `references/spacing-and-rules.md` — spacing, callout heights, board-grade voice.
- `references/brand-guidelines.md` — the official CBRE 2026 v17 spec.
- `references/inspiration/` — the reference deck as PNGs. **View these** for the density and typography to match.
