---
name: cbre-corporate-pptx
description: >-
  Builds a polished, fully CBRE-branded PowerPoint deck (.pptx) from your content — the right CBRE typography (Financier Display and Calibre), the brand colour palette, and a dense, editorial, story-led layout that looks like a real in-house CBRE deck rather than a generic template. Use it whenever you want a CBRE deck, CBRE slides, a CBRE-branded or client-pitch presentation, an investor deck, advisory report, market overview, or capital-strategy memo, or any time you reference a CBRE template or ask for a polished .pptx in CBRE's house style.
---

# CBRE Corporate Deck Builder

A layout engine that owns every coordinate, and a composition vocabulary rich
enough that you never need one.

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

## Eighteen cells

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

Each device is bounded to its cell and declares a minimum height. Ask for one
in a region too small and the build stops with the specific fix, rather than
drawing something squashed.

## Compose from the point, not from the menu

Work the content first: for each slide, settle the **beat** (the real point or
number it lands) and its **job** in one sentence — status? core message? a shift?
a trade-off? one number? The job picks the shape.

Then write a story spine before rendering. One row per slide:

| # | Point | Job | Tone | Scene (composed unless a preset earns it) |
|---|---|---|---|---|
| 1 | Built, now being sharpened | Summary of threads | light | composed: prose over a 5-item numbered `list` |
| 2 | Phase 2 of 3, executing | State of play | dark | composed: `timeline` row over a prose read |
| 3 | EUR 16.9m run-rate | One number | light | `poster` — *why:* the slide is one number and deliberate space; that is all this preset is |

Most rows should say **composed**. A preset in the last column needs its `why`
written out here, and it carries into the plan as `shape_why`.

The spine is a real artifact, not an in-head sketch — building first is how
decks drift back to one repeated layout. When you are working interactively,
show it to the user before rendering.

**Write in the CBRE voice as you draft.** Read the `cbre-tone-of-voice` skill
(`${CLAUDE_PLUGIN_ROOT}/skills/cbre-tone-of-voice/SKILL.md`, or
`~/.claude/skills/cbre-tone-of-voice/SKILL.md` standalone) and calibrate volume:
investor, board and advisory decks dial the voice **down** (clarity-first,
restrained, still opinionated); market overviews and thought leadership dial it
**up**. Board-grade conventions are in `references/spacing-and-rules.md` §12–13.

## The three audits

They run automatically on `save()` / `compose.render()` and print a report.
Pass `shapes_strict=True` / `geometry_strict=True` to turn findings into errors
(the smoke test does).

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

Pairs only: a slide may be the target of at most one other, so this cannot be
used to wave a whole deck through. The two must genuinely share a skeleton, or
the parallel is invisible to the reader and the audit says so.

### The fourth check is your eyes

The three audits are code, and code cannot see. No assertion catches "this deck
reads as templated" or "slide 6 is a wall of grey". So the last step before
delivery is to **look at the whole deck at once, against a real bar**:

```bash
python scripts/critique/critique.py MyDeck.pptx
```

It tiles your deck into one contact sheet, tiles the gold reference set into
another, and prints the questions to answer. View both images, then fix the
**plan** and re-render. Never adjust a coordinate by hand: that is what the
geometry audit exists to prevent.

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

Density comes from substance. When a slide looks thin the fix is another real
beat — a second stat, a panel, the next point — or balanced space. Deliberate
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

## Escape hatch

For a slide the cell set genuinely cannot cover (a custom chart, a one-off
device), build it from primitives on a `build.blank()` slide and save it into the
same deck. `references/layouts.md` has the recipe signatures,
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
- `references/scene-composition.md` — the scene model and full cell catalogue. **Read first.**
- `references/editorial-archetypes.md` — archetype sketches: job → composition.
- `references/layouts.md` — recipe parameter lists.
- `references/philosophy.md` — design rules from the reference deck.
- `references/spacing-and-rules.md` — spacing, callout heights, board-grade voice.
- `references/brand-guidelines.md` — the official CBRE 2026 v17 spec.
- `references/inspiration/` — the reference deck as PNGs. **View these** for the density and typography to match.
