# Spacing, layout and content rules (learnings from the EMBLA Horizon deck)

This document captures the rules and traps that the EMBLA Horizon Phase 0 build
exposed in the skill. Read this **before building any new deck** — almost every
rule here was learned the hard way (broken renders, board-grade QA feedback,
client style violations) and codifies the fix.

The rules are listed in priority order: things that make the deck fail to open
or render correctly first, then visual quality, then content style.

> **Canonical visual brand source:** `references/brand-guidelines.md` (official CBRE 2026 v17 — palette, typography, logo, grid, Line of Sight). It governs colour/type/logo; this file governs spacing, measurement, and content style on top of it. (Verbal tone of voice lives in the separate `cbre-tone-of-voice` skill — see §12.)

---

## 1. Callout height — use `predict_callout_h` to size correctly

`callout()` internally lays out the body at `y + 0.62` (after a 0.62" title
region) with **0.20" bottom padding** below the body to the bg rect. If `h`
is too small for the body text, the body shape overflows the bg rect and
the user sees text rendered on the slide bg below the visible green/off-
white callout band (because `SHAPE_TO_FIT_TEXT` only kicks in on click,
not on file open — see §20 below).

**Always use `predict_callout_h(body_text, w=...)` to size the callout
based on the body content**, BEFORE drawing other content (like a table)
that has to fit above:

```python
cal_body = "Stellantis booked EUR 25.4 billion of ..."
cal_h = max(1.05, build.predict_callout_h(cal_body, w=PAGE_W))
cal_y = SAFE_BOT - cal_h
content_bot = cal_y - 0.20          # table now sizes against this

build.table(s, ..., y=content_top, h=content_bot - content_top, ...)
build.callout(s, body_text=cal_body, x=PAGE_X, y=cal_y,
              w=PAGE_W, h=cal_h, ...)
```

Why not auto-grow inside `callout()`? Growing upward collides with content
above (e.g. a table sized against `cal_y - margin` becomes too tall).
Growing downward crosses the slide's footer / wordmark band. Only the
caller knows which trade-off is acceptable.

**Layout constants** (see `_CALLOUT_TITLE_REGION_H` / `_CALLOUT_BOTTOM_PAD`
in build.py):

| Region | Inches |
|---|---|
| Title region (top to body's top) | 0.62 |
| Body bottom padding (body bottom to bg rect bottom) | 0.20 |
| Minimum `h` (so the body box is ≥0.18" — single line at 10pt) | 1.00 |

If `h ≤ 0.82`, the inner body shape gets a negative height and **PowerPoint
will refuse to open the .pptx file** (cryptic COM error -2147023504). The
`predict_callout_h` helper always returns a safe minimum.

The bg rect and accent bar are registered as `linked_height_shapes` of the
body — after resolve trims the body to its actual rendered height, the bg
rect and bar absorb the same delta, so the visual padding stays at exactly
0.20" regardless of how much over the predictor was.

---

## 2. Use `Flow` for the top stack — always

The instinct is to hard-code y/h for eyebrow, title, body. **Don't.** That
produces dead air below short titles and overflow below long ones.

`Flow` advances the cursor by the **measured** height of each element, so
spacing stays content-driven:

```python
f = Flow(s, x=PAGE_X, y=EYEBROW_Y, w=PAGE_W, tone=tone)
f.eyebrow("01 · CONTEXT", accent="gold")
f.gap(GAP_EYEBROW_TITLE)
f.title("What EMBLA asked CBRE to assess", size=32, color=COLORS["ink"])
f.gap(GAP_TITLE_BODY)
f.body("The European hub is set for…", size=12.5, color=COLORS["ink"])
f.gap(GAP_BODY_CONTENT)
# f.y is now exactly below the body + 0.32"
# … place tables / cards / KPI strips at f.y …
```

After the body block, use `f.y` to anchor whatever comes next. Never type a
y coordinate above f.y in the same column once Flow is running.

---

## 3. Standardised vertical gaps

`measure_text()` returns the text height **including ascender/descender padding
on the font**, and the surrounding text frame adds another ~0.05–0.10" of
internal padding. So Flow's `gap()` values are *additional* on top of that
hidden padding — they need to be smaller than instinct suggests.

The values that produced clean rhythm across the EMBLA deck:

```python
GAP_EYEBROW_TITLE = 0.12   # eyebrow → title
GAP_TITLE_BODY    = 0.18   # title → body or vbar paragraph
GAP_BODY_CONTENT  = 0.32   # body → KPI strip / table / card row
```

Apply these as constants on every slide so the rhythm reads consistently. If
you go to 0.40+ between title and body you'll get visible dead air. If you go
below 0.10 the title and body kiss.

---

## 4. Safe-bottom: content ends well above the wordmark

The painted wordmark "CBRE" sits at approximately `y = 6.92 → 7.37` (bottom
right), and the "Confidential & Proprietary" line at `y = 7.15 → 7.37` (bottom
left). Any full-width content (callouts, tables, footnotes) that extends below
`y ≈ 6.85` will visually clash with the footer.

```python
SAFE_BOT = 6.85   # bottom edge of the last content block
```

For full-width callouts: `callout_y = SAFE_BOT - callout_h`.
For footnotes: `foot_y = SAFE_BOT - foot_h` (with `foot_h ≈ 0.22`).

For slides with footnote **and** callout stacked at the bottom, anchor the
callout first, then put the footnote above it with a 0.15" gap:

```python
callout_h = 0.95
callout_y = SAFE_BOT - callout_h
foot_h    = 0.22
foot_y    = callout_y - foot_h - 0.15
table_h   = foot_y - f.y - 0.15
```

---

## 5. Native slide background (now the default)

**As of the render-and-measure rebuild, `blank()` and every recipe use a
native slide background — no overlay rect.** Internally:

```python
def _paint_bg_native(slide, tone):
    rgb = COLORS["page_dark"] if tone == "dark" else COLORS["page_light"]
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb
```

The previous overlay-rect approach (`_paint_bg`) painted a full-bleed
`MSO_SHAPE.RECTANGLE` over the slide. That polluted the shape tree:
editors could accidentally select / move / delete the background, and
any shape with a "background"-coloured (transparent) fill actually
showed the rect's colour rather than the slide's true bg.

`_paint_bg` is retained only as a `DeprecationWarning` shim for any
user-side scripts that imported it directly; it forwards to the
native function. New code should never reference `_paint_bg`.

**Split-tone slides** (dark top / light bottom, e.g. `value_prop_intro`)
still use a single overlay rect — but only for the bottom band. The
slide bg itself is the top tone (native), and the rect overlays just
the bottom half. One overlay, not two.

Verifying: open a freshly-built `.pptx` in PowerPoint. Click an empty
area — you should select the slide itself, not a rectangle. Selection
Pane (Home → Select) should show no full-bleed `Rectangle`.

---

## 6. Card heights: content-sized vs back-solved

There are two valid patterns for a card row. Decide upfront which one fits.

**Pattern A — content-sized** (good when the cards' content is short):

```python
card_h = 2.30   # fixed
card_w = (PAGE_W - 0.20) / 3
x = PAGE_X
for i, item in enumerate(items):
    roman_card(s, i+1, x=x, y=f.y, w=card_w, h=card_h, …)
    x += card_w + 0.10
```

Cards bottom-align at `f.y + 2.30`. Anything below is intentional whitespace.

**Pattern B — back-solved to fill the safe-area** (good for dense content
trios that need to bottom-align with a footer band):

```python
foot_h     = 0.22
foot_y     = SAFE_BOT - foot_h
cards_top  = f.y
card_h     = foot_y - cards_top - 0.20   # 0.20" clearance to footnote
```

All three cards get the same `card_h`, so they bottom-align as a trio even if
one has more bullets than the others. The longer card fills its box; the
shorter ones show intentional whitespace at the bottom of their interior. This
is the right pattern for the option-deepdive (Pros / Cons / Best for) trio.

**Anti-pattern**: setting `card_h = SAFE_BOT - f.y - 0.05` without a footnote
reservation — cards stretch all the way to the wordmark band, leaving a
gigantic empty band inside each short card. Use Pattern A in that case.

---

## 7. Card internal padding

Both `roman_card` and `decimal_card` position content with the following
internal offsets (measured from the card's top-left):

- Top accent rule at y = 0
- Numeral / decimal label at y ≈ 0.08–0.10"
- Title at y ≈ 0.52"
- Body text starts at y ≈ 1.18", with `h = card_h − 1.28`

Two consequences:

- **A card with `h < 1.50` has almost no body area.** Bullets get crammed.
- **Cards have asymmetric padding by default** — ~0.18" top, ~0.10–0.40"
  bottom (depending on how much the body fills). If you set card_h far larger
  than the body needs, the bottom padding visibly exceeds the top — looks
  sloppy. Match card_h to the content, or accept the asymmetry as intentional
  whitespace.

For 4-bullet roman cards at body size 8.5: `card_h ≈ 2.30`.
For 5-bullet roman cards: `card_h ≈ 2.60`.
For decimal cards with a 3–4 line paragraph: `card_h ≈ 2.50–2.85`.

---

## 8. Inter-card gaps

- Horizontal gap between adjacent cards in a row: **0.10" minimum, 0.20"
  preferred** for readability on a 12.2" page width.
- Vertical gap between rows in a 2×N grid: **0.30"** (not 0.16" — that reads
  as tighter than the horizontal gap and breaks the grid). Vertical gaps need
  to be larger than horizontal because the eye reads cards top-to-bottom and
  the rules + numerals add visual weight at the top of each card.

```python
inter_col_gap = 0.20
inter_row_gap = 0.30
card_w = (PAGE_W - 2 * inter_col_gap) / 3
card_h = (cards_bottom - cards_top - inter_row_gap) / 2
```

---

## 9. vbar wraps the body — not just the body box

When framing a lead paragraph with a mint `_vbar()` in the gutter, extend the
bar `±0.05"` beyond the measured body height so it visually brackets the
paragraph rather than cropping at x-height / descender:

```python
body_y = f.y
sub = Flow(s, x=PAGE_X + 0.30, y=body_y, w=PAGE_W - 0.30, tone=tone)
h_body = sub.body(text, size=12, color=…)
_vbar(s, x=PAGE_X, y=body_y - 0.05, h=h_body + 0.10,
      color=COLORS["mint"], width_in=0.05)
f.gap_to(sub.y + GAP_BODY_CONTENT)
```

The sub-flow indents the paragraph 0.30" to the right of the bar (in the
gutter) and `f.gap_to(sub.y + …)` resyncs the main cursor.

---

## 10. Em dashes are a client style switch — handle separator punctuation case-by-case

Some clients **ban em dashes** (`—`). The skill should not assume they're
available. When stripped, the right replacement depends on context — a bulk
sed swap to `;` will break grammar.

Rules of thumb:

- **Subordinate clause that explains the noun before it** (`Hub: Acquisition
  Model Options`) → use **colon** `:`
- **Two independent clauses bridged by an em dash** (`The answer is sensitive
  — a 150bps shift in WACC moves NPV by ~€2m`) → use **period** `.` and start
  a new sentence (`The answer is sensitive. A 150bps shift in WACC moves NPV
  by ~€2m.`) or a **semicolon** if the second clause continues the thought
- **Parenthetical insertion** (`the trade-offs — financial, strategic and
  operational — ahead of …`) → use **commas** or restructure to a prepositional
  phrase (`the trade-offs across financial, strategic and operational
  dimensions ahead of …`)
- **"Not applicable" cells in tables** → use **en dash** `–` (U+2013), never
  em dash `—` (U+2014)
- **Legend or label separator** (`H: Strong fit`) → use **colon** or `·`

Don't bulk-replace `—` with `;` without re-reading. Semicolons require two
independent clauses on each side and will read wrong in 30% of em-dash uses.

---

## 11. Acronym expansion convention

Board audiences mix finance, governance, operations, legal — most are not
real-estate fluent. Acronyms common in I&L should be expanded on **first use**
in body copy:

- **PIZ** → "Polish Investment Zone (PIZ)"
- **NNN** → "triple-net (NNN)"
- **PAC** → "practical completion (PAC)"
- **LDs** → "liquidated damages (LDs)"
- **TDC** → "total development cost (TDC)"
- **RET** → "Polish real-estate tax"
- **HICP** → "Eurozone inflation (HICP)"
- **CIT** → "corporation tax"
- **SOP** → "start of production"
- **SPV** → "development vehicle (SPV)"
- **GC** → "general contractor"

KPI labels and table cells can use the abbreviation alone once it's been
established. But don't let an unexpanded acronym be the **first appearance**
in body copy.

---

## 12. Tone: outward-facing voice, not CBRE-internal

> **Canonical voice reference:** the full CBRE tone-of-voice system (Clear / Bold / Connected, the seven writing principles, the dial-up/dial-down volume control, and the *Attributes in Action* approach menu) lives in the `cbre-tone-of-voice` skill — `${CLAUDE_PLUGIN_ROOT}/skills/cbre-tone-of-voice/SKILL.md` (or `~/.claude/skills/cbre-tone-of-voice/SKILL.md` as a standalone skill). Read it at the content-lock stage. The rules in §12–13 below are the **board-grade, dialed-down specifics** that layer on top of it for investor/advisory decks.

The deck is CBRE talking *to* the board, not CBRE narrating its own process.

| Avoid (internal voice) | Prefer (outward voice) |
|---|---|
| "Our remit is to…" | "CBRE was asked to…" |
| "We sensitise NPV across…" | "We modelled NPV across…" |
| "EMBLA WACC withheld from CBRE pre-NDA" | "EMBLA's WACC was not shared with CBRE for Phase 0" |
| "The verdict flips at 10.13%" | "The BTO vs Lease answer flips at 10.13%" |
| "Captured in the NPV" | "Already reflected in the NPV" |

"Verdict" especially is a model-translated word; prefer "answer", "result",
"finding". "Thesis" is also overused.

---

## 13. Bullet density: write full thoughts, not labels

Telegraphic one-liners read as analyst placeholders. Board-grade bullets
carry information.

| Avoid (label) | Prefer (substantive) |
|---|---|
| "Lowest day-1 commitment" | "Lowest day-one capital outlay of any option (~€3.5m, including landlord-recovered adaptation)" |
| "Fast" | "Operational within 6–9 months — the only path that lands well before SOP" |
| "No residual" | "No residual value at year 20 — every rent payment is a sunk cost" |
| "Spec compromises" | "Spec compromises ripple into headcount, HSE and operational efficiency" |

Rule: every bullet should pass the "so what?" test. If a reader asks "so
what?" and there's no answer in the bullet, expand it.

For Pros / Cons / Best-for trios: **4–5 bullets per card** is the sweet spot.
Fewer reads sparse; more crams.

---

## 14. H/M/L scoring tables

The custom H/M/L pattern (used on the strategic and operational comparison
slides) uses:

- Pill width: 0.55"
- Pill height: 0.32"
- Pill centred horizontally and vertically in the cell
- Cell row height: ≥ 0.40" so the pill sits with ~0.04" of padding above and
  below

```python
pill_w, pill_h = 0.55, 0.32
px = x + (w - pill_w) / 2
py = y + (h - pill_h) / 2
_rect(slide, px, py, pill_w, pill_h, fill=fill)
```

Colours:
- H (strong) → `COLORS["mint"]` with `COLORS["green"]` text
- M (partial) → `COLORS["gold"]` with `COLORS["green"]` text
- L (weak) → `COLORS["rule_light"]` (light) / `COLORS["rule_dark"]` (dark)
  with muted text colour (`ink_2` / `mint_pale`)

Always pair the scoring table with a legend strip below it:

```python
_hml_legend(s, y=legend_y, tone=tone)   # H: Strong / M: Partial / L: Weak
```

---

## 15. Tables: row height and footnote placement

- 9.5–10.5pt body text → minimum 0.32" row height, 0.35–0.40" comfortable.
- First column left-aligned and bold; subsequent columns aligned per content
  (right for numbers, left for text).
- Footnotes referenced by `¹` `²` (superscript) directly in the cell text;
  the corresponding note text sits at the safe-bottom in 8.5pt italic.

```python
_text(s, "¹ Differences <€0.2m within model precision.  ²Footnote 2 text.",
      x=PAGE_X, y=foot_y, w=PAGE_W, h=foot_h,
      font=FONTS["sans_l"], size=8.5,
      color=COLORS["ink_2"] if tone == "light" else COLORS["mint_pale"],
      italic=True)
```

---

## 16. Reusable shared scaffolds

For deck sections that repeat (e.g. an option deep-dive with KPI strip + Pros
/ Cons / Best for cards + footnote), factor into a `_helper(...)` function:

```python
def _option_deepdive(deck, *, eyebrow_text, title_text, lead, kpi_items,
                      pros, cons, best_for, footnote, tone, color_ink):
    s = blank(deck, tone=tone)
    f = Flow(s, x=PAGE_X, y=EYEBROW_Y, w=PAGE_W, tone=tone)
    f.eyebrow(eyebrow_text, accent="gold")
    f.gap(GAP_EYEBROW_TITLE)
    f.title(title_text, size=30, color=color_ink)
    f.gap(GAP_TITLE_BODY)
    f.body(lead, size=12, color=…)
    f.gap(GAP_BODY_CONTENT)
    # … KPI strip, cards, footnote …
```

Then call it per option:

```python
def s07_existing(deck):
    _option_deepdive(deck, eyebrow_text="03 · OPTIONS · A", …)
```

Benefit: rhythm is locked across the three deep-dive slides — same gaps, same
card heights, same footnote position. If the user changes content length on
one, the others stay in sync.

---

## 17. Card cramming: floating card_h with fixed inner offsets

Building a grid where `card_h` floats to fill the available area but inner
content uses **fixed y-offsets** is a silent cramming pattern. The cards
"fit" mathematically — every offset is below `card_h` — but the bottom
padding compresses to a hair, and the slide reads as squashed.

This happened on Stellantis Part 2 slide 7. Six ranked cards in a 4.82"
column gave `card_h = 0.753"`. The inner layout (title + body + approach
text) bottomed out at `y_off = 0.72"`, leaving **0.03" of bottom clearance**.
Visually that's zero. The top of the next card sat almost flush against
the bottom text of the previous one.

```python
# Wrong — bottom_pad silently collapses:
card_h = (avail - gaps) / n      # floats freely
# … fixed inner offsets that nearly equal card_h:
_text(s, body,     y=ry + 0.40, h=0.20)
_text(s, approach, y=ry + 0.56, h=0.20)   # ends at ry + 0.72
# card_h might be 0.755 — gap of 0.03 reads as crammed.
```

**Use `grid_card_geometry()` to guard against this:**

```python
inner_h = 0.74  # sum of inner offsets + last element height
card_h = build.grid_card_geometry(
    available_h=content_bot - content_top,
    n_items=6, row_gap=0.06,
    inner_content_h=inner_h, bottom_pad=0.12,
    name="opportunity grid",
)
# Raises AssertionError if 6 cards can't honour 0.12" bottom padding.
```

When it raises, the fix is structural, not cosmetic: reduce `n_items`,
free space above the grid (shorter title, drop the intro body), restructure
to a 2-column grid, or split across two slides. **Do not** silently drop
`bottom_pad` below 0.10" to make the assertion pass — that's the original
cramming bug wearing a number.

### Four layers of cramming defence

These are stacked so you can't accidentally repeat the slide 7 bug, no
matter how you reach for the layout:

1. **`grid_card_geometry()`** — when you back-solve `card_h` from
   available area / N items. Raises before any shape is drawn if the
   maths would leave less than `bottom_pad` below the inner content.
2. **`min_h_for_roman_card()` / `min_h_for_decimal_card()`** — pre-flight
   sizing helpers. Pass `n_bullets` (or `body_text + w`) and get the
   minimum `card_h` you should pass in. Useful when you want to *change*
   the grid (drop a card, switch columns) rather than catching the error
   after laying out.
3. **`roman_card()` / `decimal_card()` self-checks** — both primitives
   now raise `CardOverflowError` *before* drawing anything if the `h`
   you pass is below their content's `min_h_for_*` value. This catches
   accidental cramming even when you forgot to compute geometry up
   front.
4. **`CardFlow`** — the bounded equivalent of `Flow` for custom card
   interiors (the slide 7 ranked-card pattern, where you draw the card
   yourself and stack title + body + approach inside). Every `text()`
   and `gap()` call is cursor-checked against `card_h - bottom_pad`.
   Use this in preference to manual `y_offset` arithmetic on every
   custom card layout.

```python
# Pattern: custom card with title + body + approach, cramming-proof.
_rect(s, cx, cy, cw, ch, fill=COLORS["off_white"])
_vbar(s, cx, cy, ch, color=accent, width_in=0.06)
# Numeral and tag pill at fixed positions — they don't depend on flow…
_text(s, str(n), x=cx + 0.18, y=cy + 0.10, w=0.5, h=0.6, ...)
# …but the title/body/approach stack uses CardFlow:
c = CardFlow(s, x=cx, y=cy, w=cw, h=ch,
             left_inset=0.78, right_inset=tag_w + 0.30,
             top_pad=0.16, bottom_pad=0.16, tone="light")
c.text(title, size=10.5, font="sans_sb", color=COLORS["green"], bold=True)
c.gap(0.06)
c.text(body_text, size=9, font="sans_l", color=COLORS["ink_2"])
c.gap(0.06)
c.text("Approach: " + approach, size=9, font="sans_sb",
       italic=True, color=COLORS["mint_dark"])
# Any text() that pushes the cursor past cy + ch - 0.16 raises
# CardOverflowError with a structural-fix message.
```

The rule of thumb: **never type a literal `y = ry + N` for inner card
content if `N` was hand-tuned to fit a back-solved card height**. Use
CardFlow instead. Hand-tuned offsets and floating heights are the
ingredient that produced the original 0.03" bottom margin.

---

## 17.6 Render-and-measure resolve pass

`build.save(deck, path)` now runs a **render-and-measure correction
pass** by default on Windows. After the deck is written as a draft, each
slide is exported to PNG via PowerPoint COM, every text shape registered
via `Flow` / `CardFlow` is pixel-walked for its actual rendered height,
and dependents are shifted by the delta. The deck re-saves with corrected
positions.

What this fixes:

- The predictor (`measure_text`) is conservative. A short serif title at
  22pt + 12.20" wide can be reserved as a 2-line box but render on 1 line,
  leaving ~0.35" of dead air below. Stacked Flow elements compound to
  ~0.50". Resolve closes the gap exactly.
- A `CardFlow.text()` element whose content actually wraps to one more
  line than `measure_text` predicted used to silently overflow the card
  rectangle. Resolve now catches the post-render overshoot and raises
  `CardOverflowError` with the four legitimate fixes.

How to opt out:

```python
build.save(deck, path, resolve=False)   # for fast iteration loops
```

Always run resolve before delivery — `resolve=True` or the default
auto-detect. On Linux, resolve is unavailable (LibreOffice substitutes
fonts; measurements would be misleading) and `resolve=None` skips it
automatically.

**Registration.** `Flow.title()`, `Flow.body()`, `Flow.subhead()`, and
`CardFlow.text()` register automatically. For non-Flow shapes drawn at
`f.y` (e.g. a table, KPI strip, callout), call `f.attach_dependent(shape)`
after drawing so it picks up the cumulative Flow correction.

**Recipes are not registered.** `framework_roman`, `case_study`,
`why_two_col`, etc., don't use Flow internally — their text shapes are
invisible to resolve. They keep their predictor-driven dead space and
will silently overflow on wrapping content. If you need correctness
guarantees, build from primitives with Flow / CardFlow.

---

## 18. measure_text behaviour to know

**`measure_text` is now a first-draft seed, not the authority.** On
Windows builds, the resolve pass (§17.6) corrects whatever drift the
predictor has by pixel-walking the actual PowerPoint render. The notes
below describe its precision as a seed.

`measure_text(text, size, w, font, line_spacing)` returns the rendered height
of `text` wrapped to width `w`, **including font ascender/descender padding**.
This is typically ~6% larger than the raw `size × line_count × line_spacing`
calculation (was 10% before the 2026-05-19 Stellantis recalibration — the
old value was over-padding by ~0.04" per element, compounding into visible
dead space on stacked Flow layouts).

**Calibration history.** Pre-2026-05-19 the serif factor (`_CHAR_W_FACTORS`)
was 0.50, which over-predicted Financier Display character width by ~16%.
A 95-char title at 22pt in a 12.20" frame was reserved as a 2-line box but
PowerPoint rendered it on 1 line, leaving ~0.35" of dead space inside the
title block. The factor is now 0.43 (sans_l 0.43, sans 0.45, sans_sb 0.47).
`Flow.title()` and `Flow.body()` now render with `autofit=True` so even if
the predictor over-shoots, the visible shape collapses to the real text
height — the cursor advance is conservative but the box itself is honest.

Useful for back-of-envelope:

- 11pt Calibre body, line_spacing 1.30, ~80 chars per inch at full page width
- Single line of body ≈ 0.20"
- 3-line wrapped body ≈ 0.55"
- 28pt serif title, single line ≈ 0.55"
- 32pt serif title, single line ≈ 0.65"
- 44pt cover title, two lines ≈ 1.65"

When in doubt, call `measure_text()` empirically before laying out the rest of
the slide. This is what `Flow.title()` and `Flow.body()` do internally.

---

## 19. Render to PowerPoint COM, not LibreOffice, when on Windows

LibreOffice's headless export substitutes Financier Display / Calibre with
generic serif / sans, so line breaks shift, kerning is wrong, and what you
see is not what the user sees in PowerPoint. On Windows, always render via
the PowerPoint COM script (`scripts/to_png.ps1` or equivalent).

When COM fails to open a freshly-built file, the cause is almost always
**section 1** of this document (callout h too small). Open the build script
and check every `callout(…, h=…)` value.

---

## TL;DR cheat sheet

```python
# Canvas constants — put these at the top of every build script
PAGE_X     = 0.55
PAGE_W     = 12.20
EYEBROW_Y  = 0.50
SAFE_BOT   = 6.85

GAP_EYEBROW_TITLE = 0.12
GAP_TITLE_BODY    = 0.18
GAP_BODY_CONTENT  = 0.32

# Every slide starts the same way
def sN_whatever(deck):
    s = blank(deck, tone="dark")                   # native bg, not overlay
    f = Flow(s, x=PAGE_X, y=EYEBROW_Y, w=PAGE_W, tone="dark")
    f.eyebrow("0X · SECTION", accent="gold")
    f.gap(GAP_EYEBROW_TITLE)
    f.title("…", size=30, color=COLORS["white"])
    f.gap(GAP_TITLE_BODY)
    f.body("…", size=12, color=COLORS["white"])
    f.gap(GAP_BODY_CONTENT)
    # … place content at f.y …
    # … callouts/footnotes anchored to SAFE_BOT, h ≥ 0.90 …
```

Get those right and 80% of the spacing problems never happen.
