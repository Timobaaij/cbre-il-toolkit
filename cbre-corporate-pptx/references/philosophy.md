# Visual philosophy — distilled from "CBRE - Slides I like"

> **Canonical visual brand source:** `references/brand-guidelines.md` (official CBRE 2026 v17). This file is the editorial *look* layer — the "Slides I like" house style — which sits **on top of** the official brand. Where this file states a palette token or type rule, the brand doc is the authority; the two are reconciled (the editorial palette is ~90% the official secondary palette). Read the brand doc when you need official colour names, the logo rules, or the Line of Sight device.

This skill is **inspired by**, not a clone of, the reference deck. The goal is for every slide to *feel* like it came from the same hand — same palette, same typography, same accent rhythm — while being free to choose whatever layout best serves the slide's purpose.

> **The default build method is story-led scene composition** (`scripts/compose.py`; method and cell catalogue in `references/scene-composition.md`): you declare what each slide must say and the composer makes the layout, dense by construction, never poured into a recipe. This file is the *look* layer that every scene cell renders with; read it for palette, type rhythm and accent discipline, and apply it to the scenes you compose.

## Palette (sampled from the actual PDF render)

| Token | Hex | Use |
|---|---|---|
| `green` | `#012A2C` | Primary dark bg — teal-shifted near-black, NOT the corporate `#003F2D` |
| `green_2` | `#103838` | Lifted card surface on dark bg |
| `green_3` | `#184440` | Callout / row-alt surface |
| `green_4` | `#003828` | Darker callout fill on dark bg |
| `mint` | `#80B8A8` | Cooler mint — numerals, card stripes, header bands, vertical bars |
| `mint_dark` | `#538F86` | Body / accents on light bg |
| `mint_pale` | `#C0D0C8` | Pale mint surfaces |
| `gold` | `#D8D898` | **Pale wheat / cream** — primary accent. NOT orange-gold |
| `blue` | `#3878A0` | Steel-blue accent for card stripe cycling |
| `white` | `#FFFFFF` | Headlines + body on dark |
| `ink` | `#0C1C1E` | Body on light |
| `page_light` | `#FFFFFF` | Pure white for light slides + split-tone bottoms |

**The "gold" of the reference deck is a pale wheat**, not the brand-guide warm gold. Use `gold` for: eyebrows on dark, eyebrow underlines, hero stat numerals, key-term row labels in matrices, callout titles, "When:" labels, attribution lines.

## Typography rhythm

- **Headlines: Financier Display** serif. 28–110pt range. White on dark, deep-green on light.
- **Body / labels: Calibre Light** sans. 9–14pt. Letter spacing default.
- **Eyebrows: Calibre Semibold uppercase**, 10pt, letter-spacing 1.5–2.0, cream/gold on dark, ink on light.
- **Stat numerals: Financier Display** serif (regular weight — there is no "Light" variant on standard CBRE Windows; `FONTS["serif_l"]` is an alias to regular), gold on dark / deep-green on light. Hero stats 180pt+, inline stats 32–44pt.
- **Mono (Space Mono)** only for date stamps, never for body.
- Roman & decimal section numerals (`I` / `II` / `01` / `02`) are **serif**, matching the card's accent color.

## Accent rhythm

### Eyebrow pattern
- Uppercase tag at top-left
- **Thin underline rule directly below the text** (cream on dark, ink on light)
- ~1.65" wide rule, sits 0.36" below the text top
- Optional secondary eyebrow on the same slide can use mint as a contrast accent (e.g., right-side "MOST COMMON FUNDING STRATEGIES AT A GLANCE")

### Section / sub-section headers in body
- Sans-serif bold uppercase, cream/gold color
- ~1.20" wide cream underline below

### Card top-stripe
- 0.045" tall band at the very top of every framed card
- Color: cycle `gold` → `mint` → `midnight` across columns (debt-finance style) OR single uniform color. (`blue` `#3878A0` is off-brand and retained only for back-compat — prefer `midnight` `#032842`.)
- Roman / decimal numeral inside the card matches the stripe color

### Vertical bars
- 0.022" wide mint bar to the **left** of intro paragraphs (replaces a leading dash or quote mark)
- Same bar pattern on the left edge of callout boxes
- Cream/gold vertical bar can be used in contents/section dividers as the column divider

### Table header band
- Filled mint (`#80B8A8`) rectangle across the header row
- Dark green text on the mint band
- For decision-matrix–style three-column comparisons: left header = mint, middle gate = mint_dark, right header = gold

## Layout philosophy — purpose first, not template

Each layout in `build.py` is a *starting point*. The function selects sensible defaults for that slide's job, but every primitive (`eyebrow`, `serif_title`, `body`, `roman_card`, `kpi_strip`, `callout`, `_rect`, `_vbar`) is available for custom layouts that step outside the predefined patterns. Use `blank(deck, tone)` to start with just bg + footer.

The visual ingredients (palette, typography, eyebrow style, mint vertical bars, gold serif stats, mint card stripes, filled mint table headers, vertical-bar callouts) stay constant. The arrangement is free.

## Density discipline (still ≤ 30% whitespace)

- Empty real estate is the enemy. Every slide that has a serif headline must also carry: a stat strip, intro paragraph, card grid, table, callout, or pillars row.
- Title alone is never the slide. Cover slides take a `themes` band. Section dividers take a `lead` + `items` list. Statement slides take `support` + `pillars`.
- The bottom 30% of the canvas must do work — a coverage band, pillars, KPIs, or a callout.

## Dark / light rhythm

- Dark teal-green is primary. ~9/15 slides dark in a typical deck.
- Light slides break the rhythm — usually worksheet tables, comparison tables, stat strips. ~5–6/15.
- **Split-tone is a first-class option**: dark top half (eyebrow + title + stats) flipping to light bottom half (cards / detail grid). See `value_prop_intro`.

## The "no" list

- No decorative bullet circles / squares typed into the text. For a real bullet list, call `body(..., bullets=True)` (or `apply_real_bullets`) so wrapped lines hang correctly — never type a `•`/`▪`/`◦` glyph (`body()` raises if you do; see SKILL.md STOP rule 3). Inside `roman_card`/`decimal_card` the house style is a leading `–` dash marker (mint), which the card primitives add for you — the en dash is not a faked bullet.
- No drop shadows or gradients anywhere.
- No icons or logos other than the CBRE wordmark (bottom-right).
- No emojis.
- No bright lime (`#17E88F`) — the reference deck barely uses it. Cream/wheat gold is the bright accent.
- No orange-gold (`#CBA258`) — the reference deck uses pale wheat (`#D8D898`).
- `#012A2C` is the **default** background (= official Dark Green). Official CBRE Green `#003F2D` is now available as `COLORS["cbre_green"]` for a corporate-primary look — use it deliberately, not as the default dark bg.
