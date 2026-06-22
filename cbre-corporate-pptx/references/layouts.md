# Layout reference — `build.py`

Every layout function returns the created slide and adds it to the deck. All accept `tone="dark"` (default) or `tone="light"` unless noted.

Module path: `scripts/build.py` inside the skill folder.

Portable import (works in both Claude Code on Windows and Claude.ai's Linux sandbox):
```python
import sys
from pathlib import Path
for _p in (
    Path("scripts"),
    Path.home() / ".claude/skills/cbre-corporate-pptx/scripts",
    Path(r"C:/Users/TBaaij/.claude/skills/cbre-corporate-pptx/scripts"),
):
    if _p.exists():
        sys.path.insert(0, str(_p.resolve()))
        break
import build
deck = build.new_deck()
```

---

## Opening / closing slides

### `cover(deck, **kwargs)`
Hero cover with eyebrow tag, accent bar, giant serif title, subtitle, themes preview band, presenter block.

| arg | type | description |
|---|---|---|
| `title` | str | Deck title. Auto-sizes 56–110pt based on length. |
| `subtitle` | str? | One-sentence pitch, sits under title at 18pt. |
| `presenter` | str? | "Name | Role" line. |
| `org` | str? | Org affiliation line. |
| `date` | str? | "MAY 2026" — uppercase mono in top-right. |
| `eyebrow_text` | str? | Top-left tag, e.g. "CLIENT PITCH \| NIO MANUFACTURING". |
| `themes` | list[str]? | **3–4 short labels.** Renders as numbered preview band in the middle-bottom. Critical for density. |
| `tone` | str | "dark" (default) or "light". |

### `contents(deck, **kwargs)`
Numbered table of contents — giant serif "Contents" word on left, mint vertical accent, numbered list on right.

- `items` (list[str], required) — 4–8 section titles
- `title` (str, default "Contents") — override the headline word
- `eyebrow_text`, `tone`

### `section_divider(deck, **kwargs)`
Section opener: giant outline numeral, serif title, lead, two-column "in this section" list.

- `number` (int or str, required) — e.g. `1` → "01"; or `"A"`
- `title` (str, required)
- `lead` (str?, **strongly recommended**) — 1–2 sentence section synopsis
- `items` (list[str]?, **strongly recommended**) — 3–6 short labels rendered in a numbered 2-col grid
- `eyebrow_text`, `tone`

### `thank_you(deck, **kwargs)`
Closing slide. Giant serif "Thank you." + optional contact blocks.

- `title` (default "Thank you.")
- `subtitle` (e.g. "Questions and next steps.")
- `contacts` (list[dict]) — each: `{"name", "title", "email", "phone"}`
- `tone`

---

## Content slides

### `value_prop_intro(deck, **kwargs)`
Serif headline + subtitle + right-side stat column + 4 decimal-numbered cards along the bottom. Workhorse value-proposition slide.

- `eyebrow_text`, `title`, `subtitle`
- `stats` (list[(value, label)]) — 2–4 stats stacked on the right
- `cards` (list[(num, title, body)]) — exactly 4 cards along the bottom
- `tone`

### `case_study(deck, **kwargs)`
Dense case-study slide replicating the CATL reference. 4 decimal cards (left) + comparison table (right) + KPI strip + mint callout.

- `eyebrow_text`, `title`, `intro`
- `framework_title`, `framework` — list of `(num, label, body)`, exactly 4 items
- `table_headers`, `table_rows`
- `stat_strip_title`, `stats` — list of `(value, label)`
- `callout_title`, `callout_body`, `callout_tag`
- `tone`

### `worksheet_table(deck, **kwargs)`
Light-bg financial worksheet — assumptions list (left) + line-item table (right) + 3 hero KPIs at the bottom.

- `eyebrow_text`, `title`, `intro`
- `assumptions` (list[(label, value)])
- `table_headers`, `table_rows`
- `kpi_strip_items` (list[(value, label)])
- `footnote` (str?)
- `tone` (default "light")

### `framework_roman(deck, **kwargs)`
6 roman-numeral cards in a 3×2 grid with a coloured top stripe per card. Good for service capabilities, process steps, advisory streams.

- `eyebrow_text`, `title`, `intro` (optional), `side_callout` (optional right-side paragraph with mint vertical bar)
- `items` (list[(title, [bullets])]) — exactly 6
- `accent` — `"cycle"` (alternates gold→mint→blue across columns, matches reference debt-finance slide), `"gold"`, `"mint"`, `"blue"` (uniform across all cards), or an explicit `RGBColor`
- `tone`

### `comparison_table(deck, **kwargs)`
Multi-section comparison table with mint-headed columns and a coloured summary row at the bottom.

- `eyebrow_text`, `title`
- `columns` (list[str]) — first column is the row label, then 2–5 option columns
- `sections` (list[(section_label, [[row1_cols], [row2_cols], …])])
- `footer_label` (str), `footer_values` (list[str]) — summary band
- `tone` (works best on light)

### `decision_matrix(deck, **kwargs)`
Three-column "favours A | decision gate | favours B" matrix with a green callout below.

- `eyebrow_text`, `title`
- `left_label`, `gate_label`, `right_label` — column headers
- `rows` (list[(left_text, gate_label, right_text)]) — gate column is the mint-filled centre
- `callout_title`, `callout_body`
- `tone`

### `why_two_col(deck, **kwargs)`
Left column = numbered driver list with bold headers; right column = 4 mint card grid.

- `eyebrow_text`, `title`, `intro`
- `drivers_label`, `drivers` (list[(num, title, body)])
- `right_eyebrow`, `cards` (list[(title, when_label, body)]) — exactly 4
- `tone`

### `stat_hero(deck, **kwargs)`
One blockbuster number. Giant serif headline + giant numeric stat (180–220pt) + supporting paragraph.

- `eyebrow_text`, `title`
- `stat` (str) — the big number
- `label` (str) — supporting sentence next to or under the stat
- `footnote` (str?)
- `tone`

### `stat_strip(deck, **kwargs)`
3–5 KPIs in a row + bottom coverage band. Use for "platform scale" / "our capabilities" slides.

- `eyebrow_text`, `title`, `subtitle`
- `stats` (list[(value, label)]) — 3–5
- `coverage` (list[(label, detail)]) — **4–6 pairs; fills the bottom third.**
- `body_text` (str?, fallback if no `coverage`)
- `tone`

### `statement(deck, **kwargs)`
Pull-quote / big-idea slide. Editorial accent + dramatic serif quote + optional support paragraph + 3–4 bottom pillars.

- `text` (str, required) — the quote. Auto-sizes 36–54pt based on length.
- `eyebrow_text`, `attribution`
- `support_label`, `support` — supporting paragraph below the quote
- `pillars` (list[(label, detail)]) — **3–4 pairs; fills the bottom band.**
- `tone`

---

## Primitives (low-level)

Use only when none of the high-level layouts fit. See `build.py` source for full signatures.

- `blank(deck, tone)` — empty branded slide
- `eyebrow(slide, text, ...)` — top-left tag with leading rule
- `serif_title(slide, text, x, y, w, h, size, ...)` — Financier Display headline
- `body(slide, text, x, y, w, h, ...)` — Calibre Light paragraph; accepts list[str] for multi-line
- `subhead(slide, text, ...)` — semibold sub-heading
- `roman_card(slide, n, x, y, w, h, title, body_lines, ...)` — single roman-numeral card
- `decimal_card(slide, n, x, y, w, h, title, body_text, ...)` — single decimal-numbered card
- `kpi_block(slide, x, y, w, h, value, label, ...)` — single stat block
- `kpi_strip(slide, items, x, y, w, h, ...)` — horizontal KPI strip
- `table(slide, headers, rows, x, y, w, h, ...)` — mint-headed table
- `callout(slide, title, body_text, x, y, w, h, ...)` — green callout box (use `predict_callout_h` to size `h`)
- `predict_callout_h(body_text, w, *, title_region_h=0.62, bottom_pad=0.20, safety_margin=1.10)` — returns the minimum `h` a callout needs to contain `body_text` without the body overflowing the bg rect. Call **before** drawing the callout so callers can coordinate `h` with the rest of the slide layout.

## Flow / CardFlow API

- `Flow(slide, *, x, y, w, tone)` — vertical-stack cursor. Methods auto-register with the slide's resolve plan:
  - `.eyebrow(text, *, accent, underline_w)` — eyebrow + rule (advances 0.40", not registered)
  - `.title(text, *, size, color, line_spacing, font, register=True)` — serif headline
  - `.body(text, *, size, color, line_spacing, font, register=True)` — Calibre paragraph / list[str]
  - `.subhead(text, *, size, color, line_spacing, register=True)` — sans semibold subhead
  - `.gap(h)` — advance cursor by `h` inches
  - `.gap_to(y)` — jump cursor to absolute `y`
  - `.rule(*, color, width_pt, width_in)` — horizontal divider
  - `.reserve_bottom(h)` — return `y` for content `h` tall to bottom-align at safe-bottom
  - `.attach_dependent(shape)` / `.attach_dependents(shapes)` — mark non-Flow shapes as dependents
  - `with .absorb_below():` — context manager; every shape drawn during the block becomes a dependent
  - `.attach_all_below(slide=None)` — one-line retrofit; scans `slide.shapes` for everything drawn after Flow's last element and attaches
  - `.append(draw_fn, *, height)` — custom element; **not auto-registered** (use `attach_dependent` after if needed)
- `CardFlow(slide, *, x, y, w, h, top_pad, bottom_pad, left_inset, right_inset, tone, bg_hint)` — bounded vertical stack inside a card rectangle:
  - `.text(text, *, size, font, color, ..., register=True)` — auto-registered with `card_id=id(self)`; resolve raises `CardOverflowError` if cumulative content exceeds `card_h − bottom_pad`
  - `.gap(h)` / `.headroom()`

---

## Coordinate system

- Canvas: **13.33" × 7.50"** (16:9).
- Standard margins: 0.55" left/right, 0.40" top, 0.30" footer reserve.
- All `x`, `y`, `w`, `h` values are in inches (python-pptx Inches).

## Constants exported by `build.py`

- `SLIDE_W = 13.33`, `SLIDE_H = 7.50`
- `COLORS` — dict of `RGBColor` instances. See `philosophy.md` for the palette.
- `FONTS` — dict mapping role to font family name.

## Helper scripts

- `to_png.ps1` — exports a `.pptx` to PNGs at 1600×900 (under the 2000px image-tool limit).
- `to_pdf.ps1` — exports a `.pptx` to a single PDF.
