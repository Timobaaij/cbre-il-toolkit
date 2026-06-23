---
name: cbre-corporate-pptx
description: >-
  Builds a polished, fully CBRE-branded PowerPoint deck (.pptx) from your content — the right CBRE typography (Financier Display and Calibre), the brand colour palette, and a dense, editorial, story-led layout that looks like a real in-house CBRE deck rather than a generic template. Use it whenever you want a CBRE deck, CBRE slides, a CBRE-branded or client-pitch presentation, an investor deck, advisory report, market overview, or capital-strategy memo, or any time you reference a CBRE template or ask for a polished .pptx in CBRE's house style.
---

# CBRE Corporate Deck Builder

The CBRE visual system (`scripts/build.py`) plus a **story-led scene composer** (`scripts/compose.py`) on top of it. The composer is the default way to build: **the storyline drives the layout, not a recipe.** You declare what each slide must say (a deck of slides, each a `scene` of rows and cells) and the composer lays it on the safe CBRE grid and sizes every cell up to fill, so slides are dense and narrative-led by construction. The `build` primitives, editorial helpers and recipes underneath are the palette each cell draws from, and the escape hatch for bespoke slides, not a menu of slide types to pour content into. **Read `references/scene-composition.md` first.**

## 🛑 STOP — read this before writing any slide code

Three non-negotiable rules. If you violate any, the library will raise an error and the deck will not build.

1. **No `shrink=True`. No `mode="shrink"`. No `TEXT_TO_FIT_SHAPE`. No `normAutoFit`.**
   These mechanisms do not exist in this skill. The library *always* uses `SHAPE_TO_FIT_TEXT` (`spAutoFit`) — the **box grows to fit the text**, the font never shrinks. The `shrink` parameter has been removed from `_text()`, `body()`, `serif_title()`, and `container_text()`. Passing it raises `TypeError`.

2. **Minimum font size is 9 pt. Always. Every text box, every helper, every slide.**
   The library clamps `size = max(size, 9)` inside `_text()`. There are no exceptions for footers, footnotes, captions, or fine print.

3. **Real bullets only — never fake ones.** For any bullet list, pass `bullets=True` to `body()` (or call `apply_real_bullets(shape)`). That sets real PowerPoint bullets (`a:buChar`) with a hanging indent, so wrapped lines align under the text rather than collapsing back under the glyph. **Never type a bullet glyph (`•`, `‣`, `▪`) into the run text to fake a list** — `body()` raises `ValueError` if it sees a leading bullet glyph.

If the content doesn't fit a card or container, **the fix is to grow the container or trim the copy** — drop a row, split into two slides, switch to a denser composition. Do not search for a way to shrink the font. There isn't one.

Other Python presentation libraries expose `shrink=True` / `TEXT_TO_FIT_SHAPE`. This one **deliberately does not**. If your prior knowledge tells you `body(slide, text, ..., shrink=True)` is the right way to handle a tight card — it is not. That code will raise a `TypeError` here.

## ⚠ Rendering caveat — read this before you trust any preview

There are **two rendering pipelines** in this skill and they are not equivalent:

| Environment | Pipeline | Fidelity |
|---|---|---|
| **Claude Code on Windows** | `scripts/to_png.ps1` / `to_pdf.ps1` — drives **real PowerPoint via COM automation** | True-to-file. Uses the actual CBRE-installed Financier Display, Calibre, Space Mono. Line breaks, kerning, and shape positions match what the user sees when they open the .pptx in PowerPoint. **Prefer this when available.** |
| **Claude.ai Linux sandbox** | `scripts/to_pdf.sh` / `to_png.sh` — uses **LibreOffice headless** | Approximate. LibreOffice does not have the CBRE-licensed fonts and silently substitutes them. Line breaks shift, weights look wrong, positions are nominal. Useful as a composition sanity check, not as final art. |

**When you're on Windows** (path looks like `C:\Users\…\.claude\…`), always use the PowerShell rendering scripts. They open the deck in the user's PowerPoint instance, export each slide as PNG, then close. The output is exactly what the user will see.

**When you're in the Linux sandbox**, the LibreOffice render is the only option. Tell the user: a final pass in PowerPoint is mandatory before delivery — line breaks and exact positions will shift on their machine because of font substitution.

Either way, prefer composition QA over pixel QA: confirm the slide is structurally right (hierarchy, alternation of tones, no overflowing tables) rather than tuning to the pixel against a render that may not match the user's view.

## The default workflow — content-first, plan-then-build (editorial-bold)

**The storyline drives the layout, not a recipe.** Build every deck story-led, exactly as the `cbre-il-account-briefing` skill does: decide what the deck must say, break it into a narrative, compose each slide from what that slide needs to land, and let the composer fill it. The single biggest failure mode of a deck builder is stamping one safe layout (eyebrow, serif title, a row of cards, a callout) onto eight slides in a row; story-led scene composition is the cure. The discipline is a **gated method**: lock the words, plan the story spine and each slide's scene shape as a written artifact, coherence-check it, then render. **Do not render until the per-slide story spine is complete and checked.** Work all four stages below on *every* deck, and read `references/scene-composition.md` (the scene model and the cell catalogue) before composing.

The spirit (it governs everything): story-led, not template-led · narrative-led always · explain in prose, tabulate only the evidence · density from substance, never from spacing or ballooned fonts (leftover space means write more, or leave it balanced, never pad) · no lazy repetition (a scene shape appears at most twice, ideally once) · readable, not a billboard · be creative.

**Stage 1 — Draft & lock the content FIRST.** Before any layout or code, author the actual words, data, and argument from the source (brief, docx, notes). Break the deck into slides; for each, settle its **content beat** (the real point/number it makes) *and* one sentence naming its **rhetorical job**: status? core message? a shift from X to Y? a ranking or trade-off? required inputs? one number? The job determines the shape. Output of this stage: the deck as a list of slides, each with a locked beat and job. Lock this before thinking about composition — layout serves finished content, never the reverse.

> **Write in the CBRE voice as you draft — don't bolt it on later.** Before writing slide copy, read the canonical CBRE tone-of-voice reference — the `cbre-tone-of-voice` skill bundled alongside this one in the plugin (`${CLAUDE_PLUGIN_ROOT}/skills/cbre-tone-of-voice/SKILL.md`), or `~/.claude/skills/cbre-tone-of-voice/SKILL.md` if it's installed as a standalone skill. Apply its seven writing principles to every headline and bullet, and **calibrate volume to the deliverable**: investor/board/advisory/capital-strategy decks **dial the voice down** (clarity-first, restrained, still active and opinionated); market overviews and thought-leadership decks **dial it up** (proclamations, maxims, intensified word choice). The board-grade conventions in `references/spacing-and-rules.md` §12–13 layer on top of that reference for the dialed-down case.

**Stage 2 — Compose each slide's SCENE from its point.** For each slide, compose the scene (an ordered set of rows and cells, per `references/scene-composition.md`) that says its point best: a shift is a from-to of prose or chips; a state of play is a stat strip; an argument is prose plus a panel; evidence is a table or a card grid; one number is a single big `stat`; a voice is a `quote`; a takeaway is a `callout`. The cells are a palette, not a menu of slide types, so **vary the scene shape slide to slide**. The `build` recipes and editorial helpers are raw material a cell or a bespoke slide draws from, not the unit of work. Record each slide's scene shape in the story-spine table below, an **explicit written artifact**, not an in-head sketch.

**Stage 3 — Coherence-check the plan as a whole, before building.** Read the planned sequence end to end and revise the *plan* (not built slides) until: tones alternate (the dark/light rhythm below); **no two consecutive content slides share a skeleton**; no recipe is over-used; rhythm and variety hold. If three slides in a row are "header + cards + callout", two are wrong — re-plan them as a timeline, a statement, a from→to, a ladder. Run the one-line checklist under the template.

**Stage 4 — Only THEN render,** from the locked content and checked spine. Declare the deck as a plan (a list of slides, each a `scene` of rows and cells) and call `compose.render(plan, "Deck.pptx")` (or `python scripts/compose.py plan.json Deck.pptx`). The composer draws the CBRE chrome and sizes every cell up to fill, so density is automatic; your job is to give each slide enough real substance to fill it honestly. **Drop to the `build` primitives and editorial helpers (on a `build.blank()` slide, saved into the same deck) only for a bespoke slide the cell set genuinely cannot cover** (a custom chart, the Line of Sight device, a one-off split). Don't bend content to fit a recipe; compose the scene the argument wants.

**Checkpoint (both run modes).** When you're building interactively, surface the story spine (or a concise version) to the user before rendering. In an autonomous run, completing the spine table and self-running the coherence checklist satisfies the gate. Either way: **no rendering before the story spine is complete and checked.**

### The story-spine artifact — fill before rendering

One row per slide. The last column is load-bearing: it forces the scene shape from the point, never from a recipe.

| # | Point (the actual thing it lands) | Job | Tone | Scene shape (rows x cells) |
|---|---|---|---|---|
| 1 | Built, now being sharpened (5 threads) | Summary of many threads | light | prose (the summary) over a 5-item numbered `list` |
| 2 | We are in phase 2 of 3 (roll-out done, executing) | State of play | dark | a `chips` row (the phases) over a prose read |
| 3 | One number: EUR 16.9m run-rate | One blockbuster number | light | a single `stat`, space left beneath |

**Coherence checklist (revise the spine, not built slides):** tone mix lands ~50-70% dark and never 3 same-tone in a row · no two consecutive scenes share a shape · no scene shape used more than once unless the content truly demands it · thin slides get real content or balanced space, never padding · a tall scene drops its `lead` to clear the safe bottom.

**Default to restraint *within* a bold composition.** Editorial-bold is about *variety and intent*, not clutter. A statement slide with an eyebrow, a headline, and a quiet two-line support paragraph is a finished output. A stat hero with deliberate emptiness beneath it reads more confidently than the same stat with a coverage band crammed under it to "fill" space. When a tall archetype (timeline, ladder, from→to) needs vertical room, **drop the intro paragraph** rather than squeezing — `editorial_header(..., intro=None)`. Optional recipe args (`subtitle`, `pillars`, `coverage`, `themes`, `lead`, `items`, …) are opt-in — attach them only when the content has a real second beat.

**Closing straps are opt-in.** `case_study`, `decision_matrix`, `framework_roman`, and `value_prop_intro` no longer bundle a bottom callout by default. When every slide in a deck ends with a "CBRE VIEW" / "LESSON FOR X" strap, the deck reads as templated. Attach a callout only when the slide has a single takeaway to underline.

The brand DNA the deck must hold to (full visual spec: `references/brand-guidelines.md` — official CBRE 2026 v17):
- **Tone rhythm.** Mix dark (`#012A2C` teal-green, = official Dark Green) and light (white) backgrounds across the deck. A 15-slide deck should land roughly 8–10 dark, 5–7 light. Split-tone slides (dark top / light bottom) count as dark. Official **CBRE Green `#003F2D`** (`COLORS["cbre_green"]`) is available for a corporate-primary look but is not the default background.
- **Hierarchy.** Eyebrow (small uppercase sans, gold or mint, with a thin rule under it) → serif headline → optional intro paragraph → content blocks. Reads like editorial print, not a slide template.
- **Accent discipline.** Cream/wheat **gold** (`#D8D898`, = official **Wheat**) is primary — eyebrows, hero stat numerals, callout titles, "When:" labels, key-term row labels. **Mint** (`#80B8A8`, = official **Celadon**) is secondary — Roman/decimal numerals, card top stripes, table header bands, vertical bars beside intro paragraphs. Use `bright_green` / `accent_green` (`#17E88F`, official **Accent Green**) sparingly — single accent moments only. The data-viz palette (`build.CHART_COLORS`) is for charts/graphs only.
- **Whitespace is intentional, not residual.** Deliberate emptiness beneath a hero stat works. Don't fill space because it's there — fill it when the content earns it.
- **Brand anchors.** Every `blank()` slide already gets the official **CBRE logo artwork** bottom-right (from `scripts/assets/` — white on dark, colour on light) and the confidential copyright footer bottom-left. Don't re-add them, and **never type the wordmark yourself** (brand rule). If artwork is missing the build falls back to a typed wordmark and warns once — add the files to `assets/` (see `assets/README.md`).
- **Line of Sight.** CBRE's signature rule device — `line_of_sight(...)`. Horizontal = breadth, vertical = depth; brand weights and minimum lengths are enforced, and it is **at most one per layout**. See `brand-guidelines.md` §5.
- **Fonts.** Serif **Financier Display** for headlines and stat values — **≥ 20 pt, title case, never all caps** (`serif_title` enforces this: sub-20 raises, all-caps warns). Sans **Calibre** (`Light` / `Semibold`) for body, eyebrows, table headers — sentence case (all-caps only for eyebrows / hero moments). Mono **Space Mono** for date stamps. Don't reference weights not installed on standard CBRE Windows (no "Financier Display Light", no "Calibre Bold"); fallbacks are Times (serif) / Tahoma (sans).
- **No template inheritance.** Don't try to use PowerPoint master layouts. Every shape is drawn from scratch on a blank slide.
- **No vertical-rhythm lockstep.** Don't try to make every content slide bottom out at the same y-coordinate. Slides ending at different heights read as more confident and less template-driven — let the content set the bottom edge.

## How to start a deck

**Toolkit update check (run once, first).** Run `python scripts/version_check.py`. It prints a one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published (otherwise it is silent); it does nothing but a single public version lookup, never blocks the build, and is safe to ignore.

This skill works in **both Claude Code (Windows) and Claude.ai (Linux sandbox)**. The import snippet probes the local `scripts/` folder first, then falls back to the Windows install path.

```python
import sys
from pathlib import Path

for _p in (
    Path("scripts"),
    Path.home() / ".claude/skills/cbre-corporate-pptx/scripts",
):
    if _p.exists():
        sys.path.insert(0, str(_p.resolve()))
        break
import build, compose

# DEFAULT: story-led scene composition. Declare what each slide says; the composer makes the layout.
plan = {
    "deck_meta": {"eyebrow": "CBRE | ADVISORY"},
    "slides": [
        {"kind": "cover", "title": "...", "subtitle": "...", "date": "JUNE 2026"},
        {"kind": "scene", "tone": "dark", "eyebrow": "01 | CONTEXT", "headline": "...", "lead": "...",
         "scene": [
            {"weight": 1.3, "cells": [{"kind": "prose", "label": "THE SHIFT", "text": "..."}]},
            {"weight": 0.8, "cells": [{"kind": "stat", "value": "46%", "label": "..."},
                                      {"kind": "stat", "value": "17", "label": "..."}]}]},
        {"kind": "closing", "title": "Thank you."},
    ],
}
compose.render(plan, "MyDeck.pptx")   # resolve + sensitivity-label inherit + autofit bake on Windows

# ESCAPE HATCH: a bespoke slide the cell set can't cover, hand-built and saved into the SAME deck.
# deck = build.new_deck(); s = build.blank(deck, tone="dark"); ...custom primitives...; build.save(deck, "MyDeck.pptx")
```

## Render-and-measure resolve pass

**`build.save(deck, path)` now runs a render-and-measure correction pass by default on Windows.** This closes the gap between the Python-side text-height predictor (`measure_text`) and what PowerPoint actually renders.

How it works:

1. `save()` writes a draft `.pptx` to disk.
2. For each slide, PowerPoint COM exports it to a 1600×900 PNG.
3. Every text shape registered via `Flow` / `CardFlow` / `callout` (or `_register_resolve_element` for manual primitives) is pixel-walked in the PNG to measure its **actual rendered height**.
4. Where actual ≠ predicted by ≥ 0.008", the shape's `.height` is set to the measured value, any `linked_height_shapes` (parent container rect, accent bar) absorb the same delta, and every dependent shape is shifted by the delta. Deltas compound — later elements in a Flow shift by the sum of all prior deltas.
5. The deck re-saves with corrected positions; the draft + PNG temp files are cleaned up. **If resolve raises (e.g. `CardOverflowError`), the draft .pptx and slide PNGs are preserved** so you can inspect the failing slide.

What this fixes: the conservative bias in `measure_text` (especially Financier Display titles, which over-predict by ~10–15%) used to compound across stacked Flow elements into ~0.50" of invisible dead air. Resolve removes it entirely. Plus PowerPoint's `SHAPE_TO_FIT_TEXT` autofit only triggers on click in PowerPoint — so without resolve, the saved file has textboxes at their (often wrong) declared height. Resolve writes correct heights into the XML so the file is honest on first open.

Controls on `save()`:

```python
build.save(deck, path, resolve=None)   # default — auto-detect Windows + COM
build.save(deck, path, resolve=True)   # force; RuntimeError if COM unavailable
build.save(deck, path, resolve=False)  # skip — for fast iteration loops
```

When iterating quickly, pass `resolve=False` to skip the ~1s/slide PNG render. Always run with `resolve=True` (or default) before delivery.

**Sensitivity label + autofit bake (default on).** `save()` also inherits the org sensitivity label (`scripts/assets/sensitivity_label.xml`) and bakes fit-to-text into every box, so **every** deck this library produces — via `compose.render`, the il-briefing builder, or a bespoke `build.new_deck()` + `build.save()` — opens labelled (no labelling prompt) and already fitted, with no manual "fit shape to text" step. Labelling is a cheap file-level write that runs on every save (no PowerPoint); the bake runs on Windows when the resolve pass runs and the file is labelled (an unlabelled file is uneditable under a mandatory-labelling policy). `resolve=False` keeps fast loops label-only (no COM). Opt out with `build.save(deck, path, label_from=False, bake=False)`.

### Three retrofit helpers on `Flow`

`Flow.title()`, `Flow.body()`, `Flow.subhead()`, and `CardFlow.text()` auto-register their text shapes. For **non-Flow shapes** drawn at `f.y` (tables, KPI strips, callouts, hand-laid columns), pick one:

| Helper | When to use | Pattern |
|---|---|---|
| `f.attach_dependent(shape)` / `f.attach_dependents(shapes)` | New code, you have explicit shape handles | `f.attach_dependent(table_shape)` after drawing |
| `with f.absorb_below():` | New code, you're drawing a block | Wrap the draw calls in the context manager — every new shape on the slide during the block becomes a Flow dependent |
| `f.attach_all_below(s)` | Retrofitting existing build scripts | One line at the end of the slide function — scans `slide.shapes` for everything drawn after Flow's last element and attaches it. No re-indenting required. |

**Convention for new build scripts:** use `with f.absorb_below():` blocks. For retrofitting existing code, `f.attach_all_below(s)` at the end of each slide function is the lowest-friction option.

### Container helpers with bg rect + child text

For helpers that draw both a background rectangle and a child text shape (`callout`, custom card layouts), use `predict_callout_h` (or the equivalent predictor) **before** drawing to size the container based on its content:

```python
cal_body = "Long callout body ..."
cal_h = max(1.05, build.predict_callout_h(cal_body, w=PAGE_W))
cal_y = SAFE_BOT - cal_h         # bottom-anchor
content_bot = cal_y - 0.20       # table above sizes against this

build.callout(s, body_text=cal_body, x=PAGE_X, y=cal_y,
              w=PAGE_W, h=cal_h, ...)
```

The `callout` primitive registers its body shape with `linked_height_shapes = [bg_rect, accent_bar]` so when resolve trims the body to actual rendered height, the bg rect and bar resize in sync — no body-text-overflows-bg-rect bug.

**Recipes are not registered.** `framework_roman`, `value_prop_intro`, etc. don't use Flow internally. They'll continue to show predictor-driven dead space and silently overflow on wrapping content. (`case_study` and `decision_matrix` now use `predict_callout_h` for their internal callouts.) If you need correctness guarantees, build from primitives with `Flow` / `CardFlow` rather than calling a recipe.

**CardFlow overflow catches reality.** When a `CardFlow.text(...)` element actually renders taller than predicted and the cumulative card content would push past `card_h − bottom_pad`, resolve raises `CardOverflowError` with the four legitimate fixes (reduce items, trim copy, multi-column, split slides).

`build.save` automatically runs a dark/light tone audit and prints a warning if the mix is outside 50–70% dark. Pass `audit=False` to suppress. You can also call `build.audit_tones(deck)` at any point during construction to spot-check.

## Canvas

- **Slide size:** 13.333 × 7.5 inches (16:9).
- **Safe area:** ~0.55" left/right margin, ~0.45" top, ~0.32" bottom (the wordmark + footer band live in the bottom strip).
- **Units:** all primitive positioning args (`x`, `y`, `w`, `h`) are in **inches**.

## Visual primitives — your main API

Every primitive takes the slide as its first arg, then `x`, `y`, `w`, `h` in inches, then keyword styling args. All accept `tone="dark"` or `tone="light"` and pick brand-correct colours automatically.

| Primitive | What it draws | Key kwargs |
|---|---|---|
| `blank(deck, tone)` | New slide with painted bg, footer, and CBRE wordmark. Returns the slide. | `tone` |
| `eyebrow(slide, text)` | Small uppercase sans tag with thin gold/mint rule below. Positioned in the top-left of the safe area by default. | `tone`, `x`, `y`, `accent="gold"\|"mint"`, `underline_w` |
| `serif_title(slide, text, x, y, w, h)` | Large Financier Display headline. Box autofits to text (grows vertically as needed). | `size`, `color`, `tone`, `line_spacing` |
| `subhead(slide, text, x, y, w, h)` | Mint/green sans subhead — section labels, "what we'll cover", etc. | `size`, `color`, `tone` |
| `body(slide, text, x, y, w, h)` | Paragraph or bullet list (pass a `List[str]` for multi-line). Light Calibre. Box autofits to text. | `size`, `color`, `tone`, `line_spacing` |
| `roman_card(slide, n, x, y, w, h, title, body_lines)` | Card with Roman numeral (I, II, III), top accent stripe, title, dash-bullet body. | `accent="mint"\|"gold"\|"blue"\|RGBColor`, `subtitle`, `tone` |
| `decimal_card(slide, n, x, y, w, h, title, body_text)` | Card with `01`-style numbering, top horizontal accent rule, title + body. | `accent_color`, `tone` |
| `kpi_block(slide, x, y, w, h, value, label)` | One big serif stat over a small sans label. | `value_color`, `size`, `tone` |
| `kpi_strip(slide, items, x, y, w)` | Row of 2–5 KPIs separated by thin mint dividers. `items=[(value, label), ...]`. | `title`, `h`, `value_size`, `tone` |
| `table(slide, headers, rows, x, y, w, h)` | Mint-headed comparison table with optional coloured footer summary row. | `first_col_emphasis`, `footer_row`, `footer_fill`, `col_aligns`, `font_size`, `tone` |
| `callout(slide, title, body_text, x, y, w, h)` | "CBRE view" / "Lesson for X" box with left mint bar, gold uppercase title, optional outline tag pill on the right. **Title region 0.62"; body bottom padding 0.20".** Always size `h` via `predict_callout_h(body_text, w=...)` so the body doesn't overflow the bg rect. | `tag`, `accent`, `tone` |
| `predict_callout_h(body_text, w)` | Returns the minimum `h` a callout needs to contain `body_text` without the body overflowing the bg rect. Call BEFORE drawing the callout (and any content above it that has to fit). Returns `0.62 + measure_text(body) * 1.10 + 0.20`. | `title_region_h`, `bottom_pad`, `safety_margin` |

Low-level shape helpers (also available, prefixed with `_` but exported): `_rect`, `_text`, `_line`, `_vbar`, `_hbar`, `_dotted_line`, plus `container_text` and `assert_within`. Use these when a primitive doesn't fit — e.g. drawing a thin gold rule between two stat strips, or a tinted band behind a row of cards.

### Text sizing — pick the right tool for the job

There are **four** text helpers and they handle overflow differently. Getting this wrong is the single most common visual bug in this skill — text silently bleeding past a card edge or crammed against the bottom.

| Helper | When to use | Overflow behaviour |
|---|---|---|
| `Flow.title()` / `Flow.body()` / `Flow.eyebrow()` | **Free-flowing top-of-slide stack** (eyebrow → headline → intro). | Cursor advances by `measure_text(...)`. Title/body render with `autofit=True` so the *visible* box collapses to the rendered text even if the predictor over-shoots one line. **Prefer this for everything above the first card/table.** |
| `CardFlow(slide, x, y, w, h, top_pad, bottom_pad).text(...)` | **Inside a card you draw yourself** (rect first, then stack title + body + CTA inside). | Cursor is clamped to `[top_pad, h - bottom_pad]`. Every `.text()` and `.gap()` raises `CardOverflowError` if it would push past the bottom limit — eliminating the silent cramming where fixed `y = ry + 0.40` offsets collide with a thin floating card. Use `.text(..., extra_right_inset=tag_w)` when a single element (e.g. the top-row name) must clear a top-right tag pill. |
| `container_text(slide, text, x, y, w, h, ...)` | Text **inside a fixed-size container** — table cell, callout body, KPI strip caption, panel sub-text — when CardFlow is overkill (single element, no stacking). | Defaults to `mode="autofit"`: the box grows downward to fit the text. If it overflows the container, **increase the container height or reduce copy length** — never shrink the font. Pass `mode="fit"` for short known-fitting text (single words, hero numerals). |
| `_text(slide, text, x, y, w, h, ...)` | **Anything else** — bespoke labels, eyebrow tags drawn outside Flow, hero stat numerals with hand-tuned positions. | Always `SHAPE_TO_FIT_TEXT`: the **box grows** to fit the text. Font is never shrunk. |

**Rule of thumb for card interiors:** if you've drawn a `_rect(...)` for a card and you're about to type `y = cy + 0.10` for a title, `y = cy + 0.36` for a body, `y = cy + 0.62` for a CTA — **stop**. That's the cramming pattern. Use `CardFlow` instead. The fixed-offset pattern silently collapses bottom padding to 0.02–0.04" whenever the card height is back-solved from a grid; CardFlow refuses to draw and raises with a structural fix list.

**Font size floor: 9 pt minimum, always.** No text in any slide may be rendered smaller than 9 pt. If content doesn't fit, increase the card/container size or reduce copy length.

**Rule of thumb:** if you've just drawn a `_rect(...)` and you're about to put text inside it, use `container_text(...)`, not `_text(...)`. If the text overflows visually, widen or tall the container — do not pass a smaller `size`.

Example:

```python
# Card geometry
cx, cy, cw, ch = 0.55, 4.20, 4.0, 1.20   # ch tall enough for the content
_rect(s, cx, cy, cw, ch, fill=build.COLORS["off_white"])
_rect(s, cx, cy, cw, 0.045, fill=build.COLORS["mint"])

# Hero numeral — short, known-fitting → fit mode
container_text(s, "€16.9m", x=cx + 0.20, y=cy + 0.32, w=cw - 0.4, h=0.45,
               font=build.FONTS["serif"], size=22, color=build.COLORS["mint"],
               bold=True, mode="fit")

# Sub-caption — variable length → autofit mode (default; box grows if needed)
container_text(s, "€19m gross less Polish tax + sale costs",
               x=cx + 0.20, y=cy + 0.78, w=cw - 0.4, h=0.22,
               font=build.FONTS["sans_l"], size=9,
               color=build.COLORS["white"])
```

### Auto-sizing parameters on `_text`

Two modes are available:

- `autofit=True` (default) → MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT (`spAutoFit`). Box grows to fit the text. Font size is enforced ≥ 9 pt.
- `fit=True` → MSO_AUTO_SIZE.NONE. No auto-sizing at all. Use only for short, visually validated text (hero numerals, status pills).

PowerPoint's TEXT_TO_FIT_SHAPE / `normAutoFit` ("shrink text on overflow") is intentionally **not exposed**. There is no `shrink` parameter. If a layout overflows, restructure (drop a row, split slides, denser composition) — never reach for font-shrink.

### Card highlighting — `accent_fill` parameter

`roman_card` and `decimal_card` accept `accent_fill=RGBColor(...)`. When set, the card surface is painted that colour instead of the default `green_2` / `off_white`. Use it to differentiate one card in a grid:

```python
build.roman_card(s, 3, ..., title="Copilot", body_lines=[...],
                 accent_fill=build.COLORS["green_3"])
```

One swap, no stacked accents. Don't reach for tag pills or extra stripes to highlight — flip the fill.

### Card cramming — the four-layer defence

The single most common silent-visual bug in this skill is **cramming**: a card whose height was back-solved from a grid (e.g. `card_h = (avail - gaps) / n`) and whose inner content uses fixed y-offsets that happen to land within 0.02–0.05" of the bottom edge. The numbers "fit", every existing assertion passes, but the slide reads as squashed — the rendered body text kisses the next card's top stripe.

Four guards now make this pattern fail loudly at build time rather than silently in the deck:

1. **`build.grid_card_geometry(available_h, n_items, row_gap, inner_content_h, bottom_pad=0.10, name=...)`** — call this when back-solving a card height from a grid. Returns `card_h`, or raises `AssertionError` with the four allowed structural fixes if `bottom_pad` would collapse.
2. **`build.min_h_for_roman_card(n_bullets, subtitle=False)` / `build.min_h_for_decimal_card(body_text, w=...)`** — pre-flight sizing helpers. Use these to size a grid up front (e.g. pick `n_items` so each card hits the minimum).
3. **`roman_card` / `decimal_card` self-checks** — both primitives now call `_assert_card_room()` on entry and raise `CardOverflowError` if `h` is below the content's minimum, even when the caller forgot to compute geometry up front.
4. **`build.CardFlow`** — the bounded equivalent of `Flow` for custom card interiors (see the text-helpers table above). Every `.text()` / `.gap()` is cursor-checked against `card_h - bottom_pad`. Use this any time you're building a card by hand instead of via `roman_card` / `decimal_card`.

All four error messages name the **same four legitimate fixes**: reduce items, free space above the grid, restructure to multi-column, or split slides. Do **not** silence by lowering `bottom_pad` below ~0.10" — that path is explicitly disallowed in the message because it is the original bug wearing a number.

Full pattern catalogue and the canonical CardFlow recipe: `references/spacing-and-rules.md` §17.

Palette and font dicts: `build.COLORS["gold"]`, `build.COLORS["mint"]`, `build.COLORS["green"]`, `build.FONTS["serif"]`, etc. See the top of `build.py` for the full set.

## Free composition — worked example

A custom 2-column "context + framework" slide, built from primitives:

```python
s = build.blank(deck, tone="dark")

build.eyebrow(s, "MARKET CONTEXT | Q2 2026", accent="gold")
build.serif_title(s, "Three forces reshaping European logistics demand",
                  x=0.55, y=0.95, w=8.0, h=1.5, size=38)

# Left column: intro paragraph with mint vertical bar
build._vbar(s, x=0.55, y=2.70, h=2.4, color=build.COLORS["mint"], width_in=0.05)
build.body(s,
    "Onshoring, e-commerce normalisation, and ESG-driven site requirements "
    "are converging. Together they push occupiers toward Tier-2 corridors "
    "with grid headroom and rail intermodality.",
    x=0.80, y=2.70, w=5.4, h=2.4, size=12)

# Right column: 3 stacked decimal cards
for i, (title, body_text) in enumerate([
    ("Onshoring tailwind",
     "EU industrial policy is funnelling capex toward CEE and Iberia."),
    ("E-commerce normalisation",
     "Parcel volumes settling 18-22% above 2019 — durable, not peak."),
    ("ESG site filters",
     "Grid capacity now ranks above land cost in 6 of 10 occupier RFPs."),
]):
    y = 2.70 + i * 1.55
    build.decimal_card(s, i+1, x=6.80, y=y, w=5.95, h=1.40,
                       title=title, body_text=body_text)

# Bottom anchor: a small stat strip
build.kpi_strip(s, [
    ("46%", "of new EU leases > 20,000 sqm now in Tier-2 corridors"),
    ("EUR 1.40", "blended energy premium per sqm vs. 2022"),
    ("17", "BTS projects > 50,000 sqm in advanced planning"),
], x=0.55, y=5.55, w=12.2, h=1.10)
```

That's a slide with no recipe behind it — just primitives composed to fit the argument. Reach for that pattern first.

## Editorial-bold composition helpers

These are the tested building blocks for the editorial-bold house style (Stage 4 — build — of the default workflow). They render true-to-file and bake in the geometry so you don't re-derive it each time. **Full catalogue with a worked code sketch per archetype: `references/editorial-archetypes.md` — read it when planning a deck.**

| Helper | Archetype it builds | Signature (keyword args) |
|---|---|---|
| `editorial_header(slide, ...)` | Eyebrow → serif title → optional intro. Returns the content-start y. | `eyebrow_text, title, tone, intro=None, title_size=30, accent="gold"` |
| `num_row(slide, n, title, detail, ...)` | One numbered editorial row (serif numeral + bold title + detail). Stack several with `_line` rules between for an asymmetric "left statement / right list" or "required inputs" slide. | `x, y, w, tone, accent=None` |
| `phase_timeline(slide, phases, ...)` | Horizontal stage track; `done=True`→mint node, current→gold node + "WE ARE HERE" tag. For "where we are" status slides. | `phases=[(num,label,desc,done)], y=4.0, tone` |
| `from_to(slide, ...)` | FROM (muted) → mint arrow → TO (emphasised) transition. For "shift from X to Y". | `from_word, to_word, from_sub=None, to_sub=None, y, tone` |
| `tier_ladder(slide, tiers, ...)` | Stacked priority tiers, top emphasised. For "primary vs secondary". | `tiers=[{label,title,note,items,emphasis,height}], y, tone` |
| `directional_ladder(slide, rows, ...)` | Up / sideways / down rows with arrows + chips. For "strengthened / refocused / deprioritised". | `rows=[(direction,label,accent,items,subtag)], y, tone` |
| `intensity_bars(slide, tiers, ...)` | Decreasing-width bars inside a panel; visualises tiering. Labels in a fixed column (never negative-width). | `tiers=[(label,sub,fill,frac)], x, y, w, tone` |
| `chip(slide, text, ...)` | Rounded pill (country/tag/status). Pass `line=` on light bg. | `x, y, w, h, fill, text_color, line=None, tone` |
| `arrow(slide, direction, ...)` | Solid arrow. Colour semantics: mint=forward, gold=lateral, blue=down. | `direction="right"\|"up"\|"down"\|"left", x, y, w, h, color` |
| `line_of_sight(slide, ...)` | The signature CBRE rule device (horizontal=breadth, vertical=depth). Brand weights + min-lengths enforced; **max 1 per slide** (warns, or raises with `strict=True`). | `orientation, x, y, length, weight_px=5, color, tone, form, strict` |

Constants: `build.ED_X` (left margin), `build.ED_W` (content width), `build.ED_EYEBROW_Y`, `build.ED_SAFE_BOT`. Tall archetypes (timeline, ladders, from→to) usually want `editorial_header(..., intro=None)` so they clear `ED_SAFE_BOT`.

## Reference recipe layouts (the palette + the bespoke escape hatch)

These are pre-built compositions. In the default scene workflow they are **raw material, not slide types**: a scene cell renders with these primitives and helpers under the hood, and you call a recipe directly only for a bespoke slide the cell set cannot cover (Stage 4's escape hatch). They are inspiration for how primitives go together, never a menu the story must fit. Don't push content into a recipe just because it exists.

- `cover(title, subtitle, presenter, org, date, eyebrow_text, themes)` — hero cover with eyebrow, giant serif headline, 4-theme preview band.
- `contents(items)` — giant serif word on left, gold numbered list on right.
- `section_divider(number, title, lead, items)` — giant numeral, serif title, lead sentence, two-column "in this section" list.
- `thank_you(title, subtitle, contacts)` — closing with up to 3 contact blocks.
- `value_prop_intro(eyebrow_text, title, subtitle, stats, cards)` — split-tone (dark top with 3 stats / light bottom with 4 mint-stripe cards).
- `case_study(eyebrow_text, title, intro, framework, table_headers, table_rows, stats, *, callout_title=None, callout_body=None, callout_tag=None)` — dense case-study layout. The closing callout is opt-in: omit `callout_title` / `callout_body` for a clean stat-strip finish.
- `worksheet_table(eyebrow_text, title, intro, assumptions, table_headers, table_rows, kpi_strip_items)` — light-bg financial worksheet.
- `framework_roman(eyebrow_text, title, items, accent)` — 6 Roman-numeral cards in a 3×2 grid.
- `comparison_table(eyebrow_text, title, columns, sections, footer_label, footer_values)` — multi-section comparison with summary footer.
- `decision_matrix(eyebrow_text, title, left_label, gate_label, right_label, rows, callout_title, callout_body)` — 3-column matrix with gate column.
- `why_two_col(eyebrow_text, title, intro, drivers_label, drivers, right_eyebrow, cards)` — drivers list left, 4 cards right.
- `stat_hero(eyebrow_text, title, stat, label, footnote)` — one blockbuster stat.
- `stat_strip(eyebrow_text, title, subtitle, stats, coverage, body_text)` — 3–5 KPIs + coverage band.
- `statement(text, attribution, eyebrow_text, support_label, support, pillars)` — pull-quote with optional support paragraph and 3–4 bottom pillars.

Full parameter lists for every recipe: `references/layouts.md`. Design rules extracted from the reference deck: `references/philosophy.md`. **Spacing rules, the callout-height bug, and content/voice conventions learned across past builds: `references/spacing-and-rules.md` — read this before any new deck.**

## Composition check — before you save

Walk the slide back from the .pptx viewport in your head and ask two questions:

1. **Is every block earning its place?** If a coverage band, callout, or secondary eyebrow is there to "fill space" rather than to deliver content, remove it. Sparseness around a confident hero stat is a feature, not a bug.
2. **Does the hierarchy read at a glance?** Eyebrow → headline → content → (optional) closing strap. If the eye doesn't know where to land first, the slide has too many blocks competing — subtract before adding.

If the slide is overflowing, **don't use `TEXT_TO_FIT_SHAPE` (PowerPoint's "shrink text on overflow")**. That mode makes fonts unreadably small and the box still overflows — it is not a fix. The correct responses are: (a) drop a row / column, (b) split into two slides, or (c) switch to a denser composition pattern.

The library always uses `SHAPE_TO_FIT_TEXT` (`spAutoFit`) — the **box grows to fit the text**, font size never shrinks. Minimum font size is 9 pt. If a box growing pushes past the slide edge or a container boundary, that is a signal to restructure the content, not to swap auto-size modes. If it's sparse and you're tempted to add another block — ask whether the content actually has a second beat. If not, leave the whitespace.

**Highlight cards by swapping their fill, not by stacking accents.** `roman_card` and `decimal_card` accept an `accent_fill=RGBColor(...)` parameter. Use it to differentiate one card in a row (e.g. a "MY PICK" card in a 4-card grid) — one parameter is cleaner than a manual rebuild with extra stripes, bars, and tag pills.

## Render to PNG / PDF for review

**Prefer the PowerPoint-COM pipeline when available.** It opens the deck in the user's real PowerPoint, uses the actual CBRE-licensed fonts, and exports true-to-file PNGs. The LibreOffice fallback substitutes fonts and shifts line breaks — use it only when COM isn't reachable.

**First choice — Claude Code on Windows (PowerPoint COM, true-to-file):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/to_png.ps1 -In MyDeck.pptx -OutDir slide_imgs
powershell -ExecutionPolicy Bypass -File scripts/to_pdf.ps1 -In MyDeck.pptx
```

Caveats: PowerPoint must not be open interactively on the same .pptx (it'll fight for the COM handle). Each slide takes ~1–2 s because PowerPoint actually loads the file.

**Fallback — Claude.ai Linux sandbox (LibreOffice, approximate):**
```bash
soffice --headless --convert-to pdf MyDeck.pptx
soffice --headless --convert-to pdf --outdir slide_imgs MyDeck.pptx && pdftoppm -r 150 -png slide_imgs/MyDeck.pdf slide_imgs/slide   # writes slide-1.png, slide-2.png, ...
```

When you fall back to LibreOffice, treat the render as a composition sanity check only — confirm structure and hierarchy, don't tune to the pixel. Tell the user a final pass in PowerPoint is mandatory before delivery.

Keep PNG output ≤2000 px wide so it stays under the multimodal image limit when reviewing slides inline.

## Files in this skill

- `scripts/compose.py` — **the story-led scene composer (the default build path).** Declares a deck as slides / scenes / rows / cells and renders it via `build`. See `references/scene-composition.md`.
- `scripts/build.py` — the CBRE visual system: primitives + recipes + palette + fonts + the render / label / autofit-bake save pass.
- Rendering for review: in Cowork run LibreOffice directly (`soffice --headless --convert-to pdf` then `pdftoppm`); see "Render to PNG / PDF for review". The Windows PowerPoint-COM wrapper scripts (`*.ps1`) and the `*.sh` wrappers are omitted from this Cowork build because the skill uploader rejects executable script files.
- `references/scene-composition.md` — **the story-led method and the scene model (slide kinds, the cell catalogue, density rules, worked example). Read first.**
- `references/editorial-archetypes.md` — the editorial-bold archetype catalogue (the palette a scene cell or a bespoke slide draws from): job → composition, with a worked code sketch per archetype.
- `references/layouts.md` — parameter lists for recipe functions.
- `references/philosophy.md` — design rules extracted from the "CBRE - Slides I like" reference deck.
- `references/spacing-and-rules.md` — spacing/margin/content rules learned across past builds (callout-height bug, native slide background, Flow API patterns, em-dash handling, board-grade voice). Read before any new deck.
- `references/brand-guidelines.md` — **the official CBRE 2026 v17 visual brand spec** (palette + name mapping, typography rules, logo rules, grid, Line of Sight). The canonical visual source; read alongside `philosophy.md`.
- `references/brand-source-2026.md` — full extracted text of the brand PDF (provenance).
- `scripts/assets/` — official CBRE logo artwork (white + colour versions). Drop the supplied files here; see `assets/README.md`.
- `references/inspiration/` — the visual reference deck, rendered slide-by-slide as PNGs (`page-01.png` … `page-09.png`, 9 slides). **View these images directly** to see the editorial layout, typography and density to emulate.

## What NOT to do

- **Don't pour the story into recipes.** Story-led scene composition is the default (declare scenes via `compose.py`); reach for a recipe only as the bespoke escape hatch. Compose each slide from its point, not from a layout menu. See `references/scene-composition.md`.
- **Don't stamp the same composition on every content slide.** Eyebrow → title → card-row → callout, eight times, is the default failure. Run the gated workflow: lock content, plan a matching scene shape for every slide in the spine table, coherence-check the sequence (no two consecutive slides share a shape), then render.
- Don't pick a recipe before you've planned the slide. Lock the content, then plan its composition in the plan table — from the content, treating recipes as inspiration — and build from primitives unless a recipe is a genuine exact-fit.
- **Don't write build code before the plan is complete and coherence-checked.** The plan is a real deliverable (the per-slide table), not an in-head sketch. Building first is how decks drift back to one repeated template.
- **Don't draw a shape with a back-solved width/height that can go ≤ 0.** A `_text`/`_rect`/autoshape with `w<=0` or `h<=0` makes PowerPoint reject the *entire* file as "corrupted and unreadable" (HRESULT 0x80070570) on open — even though python-pptx saves it fine. `_assert_pos_dims` now raises at build time to catch it. The usual cause is `w = panel_w - sibling_w - gap` going negative when the sibling is at its max; put variable-width siblings in a *fixed* column, not the leftover space. (Zero-height connectors from `_line` are fine.)
- **On Windows, don't build into the OneDrive-synced project folder and immediately render** — `to_png.ps1` can open a *stale cached copy* and show pre-edit content, wasting a review cycle. Build the deck to a **local temp path** (`%TEMP%\name.pptx`), render and verify from there, then copy the verified file to the OneDrive delivery path as the last step. `build.save(deck, path)` writes wherever you point it. If a preview ever contradicts an edit you know you made, suspect this before debugging code.
- Don't shrink fonts to fit. Switch composition or split slides.
- **Don't fake bullet lists.** Never type a bullet glyph (`•`, `‣`, `▪`, `◦`) into the text to simulate a list — a typed glyph has no hanging indent, so wrapped lines collapse back under the glyph instead of aligning under the text. Use `body(..., bullets=True)` or `apply_real_bullets(shape)` for real PowerPoint bullets. `body()` raises `ValueError` if it sees a typed bullet glyph.
- Don't put every slide on a dark background. Alternate tones — the audit will warn you if you drift.
- Don't attach a closing callout / "CBRE VIEW" / "LESSON FOR X" strap to every slide. It reads as templated. Only when the slide has a single takeaway to underline.
- Don't fill whitespace because it's there. Whitespace beneath a hero stat or beside a section numeral is intentional. Add content only when the slide has more to say.
- Don't align every content slide to bottom out at the same y. Different slides ending at different depths is a feature.
- Don't trust the LibreOffice PNG preview as final art — fonts and line breaks will shift in PowerPoint. (PowerPoint-COM PNGs on Windows are true-to-file and can be trusted.) When you only have the LibreOffice render, tell the user a final pass in PowerPoint is required.
- Don't render at >2000 px when reviewing slides in-conversation — exceeds the multimodal image limit.
- Don't reference unavailable fonts ("Financier Display Light", "Calibre Bold"). Use "Financier Display" + "Calibre Semibold"; fallbacks are Times / Tahoma. Don't set Financier Display below 20 pt or in all caps — it's headlines only, title case (`serif_title` raises on <20 pt, warns on all-caps); use Calibre for anything smaller.
- **Don't type the CBRE wordmark.** It must be the official artwork in `scripts/assets/` (2026 brand rule: "do not type the logo"). The typed fallback is non-compliant — supply `cbre-logo-white.(emf|png)` + `cbre-logo-green.(emf|png)`.
- Don't use more than one Line of Sight per slide, set type on top of it, or let it bleed off the layout (`line_of_sight` guards the count).
- Don't re-add the CBRE wordmark or footer — `blank()` already paints them.
