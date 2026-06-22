# CBRE Visual Brand Guidelines — operational reference

The distilled, build-facing visual brand system, from **CBRE Guidelines 2026 (v17)**. This is the canonical *visual* source for this skill (the sibling of the canonical *verbal* source, the `cbre-tone-of-voice` skill). `scripts/build.py` is the **implementation**; this file is the **spec** it answers to. Design-philosophy prose lives in `philosophy.md`; spacing/measurement rules in `spacing-and-rules.md`.

- Full extracted source text (provenance): `references/brand-source-2026.md`.
- Source PDF: `C:\Users\TBaaij\OneDrive - CBRE, Inc\Documents\cbre_guidelines_visual_v17_2026.pdf` (144pp). Assets/templates: `brand.cbre.com`; questions: `CBREbrand@cbre.com`.

> **The skill's relationship to the brand.** This skill's look was tuned to an editorial reference deck ("CBRE – Slides I like"), and its palette turns out to be ~90% aligned with the official secondary palette. The default look is preserved on purpose. The official colours/names are layered in *additively* (see the mapping table), the type rules are enforced, the wordmark uses official artwork, and the Line of Sight device is available. Use official **CBRE Green `#003F2D`** when you want the corporate-primary look; the editorial dark teal `#012A2C` (= official Dark Green) remains the default background.

---

## 1. Colour

### Primary
| Name | Hex | RGB | Role |
|---|---|---|---|
| CBRE Green | `#003F2D` | 0/63/45 | Main brand + logo colour. Dominant but **not** on every surface. |
| Dark Green | `#012A2D` | 1/42/45 | Deep background. (Skill default bg is `#012A2C` — identical.) |
| Midnight | `#032842` | 3/40/66 | Primary deep accent / alt background. |
| Dark Grey | `#435254` | 67/82/84 | **Body copy** colour on light. |
| Light Grey | `#CAD1D3` | 202/209/211 | Light neutral, contrast-safe. |

### Secondary
| Name | Hex | RGB | Role |
|---|---|---|---|
| Accent Green | `#17E88F` | 23/232/143 | Vivid digital accent — **small amounts only**. |
| Sage | `#538184` | 83/129/132 | Muted secondary. |
| Celadon | `#80BBAD` | 128/187/173 | Soft mint-green secondary. |
| Wheat | `#DBD99A` | 219/217/154 | Pale cream — the deck's "gold". |
| Cement | `#7F8480` | 127/132/128 | Warm grey. |

### Approved tints
Midnight `#778F9C` · Sage `#96B3B6` · Celadon `#C0D4CB` · Wheat `#EFECD2` · Cement `#CBCDCB` · Accent Green 50% `#45EDA5`. Any *other* tint must meet WCAG contrast.

### Data-visualisation — **charts & graphs only**
Celadon `#80BBAD` · Dark Grey `#435254` · Accent Green `#17E88F` · Wheat `#DBD99A` · Data Orange `#D2785A` · Data Purple `#885073` · Data Light Purple `#A388BF` · Data Blue `#1F3765` · Data Light Blue `#3E7CA6` · Light Grey `#CAD1D3`. **Negative Red `#AD2A2A` only to mark a negative value.** Do not use these colours outside charts. In code: `build.CHART_COLORS` (list) + `COLORS["negative_red"]`.

### Skill name ↔ brand name ↔ code (the mapping that keeps the look on-brand)
| Skill term / `COLORS` key | Official brand colour | Hex |
|---|---|---|
| `gold` | Wheat | `#D8D898` ≈ `#DBD99A` |
| `mint` | Celadon | `#80B8A8` ≈ `#80BBAD` |
| `mint_dark` | Sage | `#538F86` ≈ `#538184` |
| `bright_green` / `accent_green` | Accent Green | `#17E88F` (exact) |
| `ink_2` / `dark_grey` | Dark Grey | `#435254` (exact) |
| `charcoal` / `cement` | Cement | `#7F8481` ≈ `#7F8480` |
| `green` / `dark_green` | Dark Green | `#012A2C` ≈ `#012A2D` |
| `cbre_green` | CBRE Green | `#003F2D` (available; not default bg) |
| `midnight` | Midnight | `#032842` |
| `blue` | *off-brand* (not a 2026 colour) | `#3878A0` — retained for back-compat; prefer `midnight` |

### Accent discipline & usage
- **CBRE Green** dominates the brand but should not be "overwhelmingly present everywhere."
- **Accent Green** is for small, vivid accent moments only — never large fills.
- In this skill: **Wheat/`gold`** is the primary accent (eyebrows, hero numerals, callout titles, key-term labels); **Celadon/`mint`** is secondary (numerals, card stripes, table headers, vbars); **Accent Green/`bright_green`** is sparing.
- **Accessibility** — AAA pairings: CBRE Green/Midnight/Dark Green on white; Accent Green on CBRE Green. AA-large only: Sage, Cement, Midnight-Tint, Dark Grey on white (large text, not body).
- Always RGB for digital; CMYK (GRACoL) for print. Use exact values, not eyedropper.

---

## 2. Typography

Fonts: **Financier Display** (serif), **Calibre** (sans), **Space Mono** (mono detail), **Barlow Condensed** (dense charts only). CJK: **Noto Serif/Sans**. Fallbacks when brand fonts are absent: **Times → Financier**, **Tahoma → Calibre** (PowerPoint substitutes automatically; don't hard-swap in code). Code: `build.FONTS`.

| Typeface | Use | Hard rules |
|---|---|---|
| **Financier Display** | Headlines + stat numerals only | **≥ 20 pt**, **title case**, **never all caps**. If you want serif < 20 pt, use Calibre instead. |
| **Calibre** | Body, labels, eyebrows, subheads, CTAs | **Sentence case** (no forced title case); all caps allowed only for short hero moments / eyebrows. Body often Dark Grey. |
| **Space Mono** | Detail (dates, locations) | All caps, **≤ 5 words**, sparingly, **do not alter letter spacing**. Accent Green on dark for emphasis. |
| **Barlow Condensed** | Charts/graphs when too tight for Calibre | Never headlines or body. |

**Leading / tracking** (brand): Financier 100% leading (95% above 100 pt, tracking −5); Calibre headlines 95%; **Calibre body 120%**. The skill keeps body line-spacing `1.30` and serif `1.05` to preserve the established look — treat the brand figures as the target if you ever want exact alignment.

In code: `serif_title()` enforces the Financier floor (`FINANCIER_MIN_PT = 20`) — sub-20 raises, all-caps warns. Eyebrows are Calibre Semibold uppercase (a sanctioned all-caps use). Mono is used only for date stamps.

---

## 3. Logo

The wordmark must be the **official artwork — never typed** ("do not type the logo yourself"). Versions: **colour** (CBRE Green, on light/neutral), **white/reverse** (on dark), **black** (B&W output only).

- **Choose the version with maximum contrast.** Practical rule used by the skill: **white on dark tone, colour on light tone.** (The guide also lists exact per-background pairings; consult the source PDF's logo-background page for edge cases.)
- **Clear space:** ≥ the logo's own height, free of other elements.
- **Minimum size:** print ≥ 1 in / 25 mm wide; digital — always prominent and legible.
- **Placement:** lower-right or upper-right preferred (text on the left); centre only if it is the sole asset.
- **Never:** create lockups with business-unit names, recolour, distort, add graphics, place on busy/low-contrast backgrounds, use the old green logo, or type it.

In code: drop artwork in `scripts/assets/` (`cbre-logo-white.(emf|png)`, `cbre-logo-green.(emf|png)` — see `assets/README.md`). `_paint_footer` places it bottom-right via `_logo()`; if absent it falls back to a typed wordmark and warns once (not brand-compliant — supply the files).

---

## 4. Layout & grid

- **12-column grid** (divides into halves/thirds/quarters/sixths).
- **Margins:** horizontal layouts ~**1/32 of page width** (≈ 0.42" on a 13.333" slide); the skill's 0.55" safe margin is slightly more generous (fine — margins are minimums). **Gutters** ≈ 1/100 of width.
- **Logo width:** ≈ 10% of page width on horizontal layouts (~1.3"); the skill uses ~1.05", which stays "prominent."
- Begin type within a grid column; anchor at least one element to a margin; avoid floating text mid-column.
- **Whitespace** is a deliberate brand element (hierarchy, breathing room). *Note:* this skill's editorial house style runs denser on purpose (`philosophy.md` ≤30% whitespace). Both are valid dials — let the content decide; don't pad to fill.

---

## 5. Line of Sight — the signature graphic device

A single rule expressing **"We See More"**: **horizontal = breadth**, **vertical = depth**. Modern, bold, used with restraint.

- **Weights (px == pt):** 1, 2, 5, 10, 20, 50, 100, 200. On a slide use **1–20**; thicker is for large-format.
- **Minimum length per weight (px):** 1→100, 2→100, 5→100, 10→200, 20→200, 50→300, 100→400, 200→600. Too short reads as a dash/button.
- **At most ONE per layout** — overuse looks frenetic and off-brand.
- **Never:** bleed off the layout, sit on top of type, or be too short.
- **Forms:** *standalone* (reinforces the idea), *type-connector* (bridges type — leave a gap; type begins/ends at the line; common weights 2/5/10/20), *border* (frames a photo/info, ≥2 equal sides), *photography-connector* and *portal* (picture-in-picture) — the last two need imagery and are **documented but not built** here.
- **Colour:** distinctive/high-contrast — Accent Green on dark (sparingly), CBRE Green / Dark Grey on light.

In code: `line_of_sight(slide, *, orientation, x, y, length, weight_px=5, color=None, tone, form="standalone", strict=False)`. It validates the weight, enforces the per-weight minimum length, and enforces one-per-slide (warns, or raises with `strict=True`). `save()` reports usage via `audit_line_of_sight()`.

---

## 6. Out of scope (documented, not built)
Photography art-direction (the "We See More" scale categories: Aerial / Building / Thriving Spaces / Detail), portraits, headshots, the focus-filter effect, colour-glaze backgrounds, and a native charting engine. The data-viz palette is provided as constants only; Line-of-Sight portal/photography-connector forms need imagery and are deferred.
