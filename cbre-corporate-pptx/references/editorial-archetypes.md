# Editorial-bold archetype catalogue

The house style: **every content slide gets a composition that matches its
rhetorical job.** This file is the **inspiration catalogue** — the
job→composition mapping with a copy-paste code sketch per archetype. It is
*not* a fixed menu of slide types, and the recipe functions in `build.py`
aren't either; treat both as starting points and compose bespoke from
primitives + editorial helpers when the content asks for it (it usually does).
Work the gated workflow from SKILL.md (lock content → plan every slide's
composition in the plan table → coherence-check the plan → build), and come
here in the plan stage for the mapping and sketches.

The cardinal rule: **no two consecutive content slides should share a
skeleton.** If you've built "eyebrow → title → card-row → callout" twice in a
row, the second one is wrong — give it a different archetype below.

All sketches assume:

```python
import build
from build import COLORS, FONTS
deck = build.new_deck()
```

and use the editorial helpers (defined in `build.py`, section "Editorial-bold
composition helpers") plus the `ED_*` constants (`ED_X`, `ED_W`,
`ED_EYEBROW_Y`, `ED_SAFE_BOT`).

---

## Job → archetype quick map

| The slide's job | Archetype | Helper |
|---|---|---|
| State of play / "where we are in the journey" | Phase timeline | `phase_timeline` |
| The one thing to remember / core message | Statement / pull-quote | `statement` recipe |
| "Shift from X to Y", "moving from build to impact" | From → to transition | `from_to` |
| Up vs down: strengthened / refocused / deprioritised | Directional ladder | `directional_ladder` |
| Primary vs secondary, what comes first | Tier ladder | `tier_ladder` |
| Required inputs / contributions / a structured list | Numbered editorial rows | `num_row` |
| …plus a set of named entities (countries, teams) | List + chip side panel | `num_row` + `chip` |
| Categorisation by intensity / size / weight | Intensity bars panel | `intensity_bars` |
| One blockbuster number | Stat hero | `stat_hero` recipe |
| The payoff across 3 dimensions | Hero + outcome strip | `arrow` + `_text` |
| Summary of many threads | Asymmetric statement + list, or dense grid | `editorial_header`+`num_row`, or `roman_card` grid |
| Cover / closing | Recipes | `cover`, `thank_you` |

Tone rhythm: a 12-slide deck should land ~7 dark / 5 light. Alternate; never
run three of the same tone back-to-back. `build.save` audits this.

Callouts: when a slide ends in a takeaway band, size it with
`build.predict_callout_h(body, w=ED_W)` and bottom-anchor at
`ED_SAFE_BOT - cal_h`. Don't echo the callout title in its body
("Objective:" under a title "OBJECTIVE"). Closing straps are opt-in — not
every slide needs one.

---

## 1. Phase timeline — "where we are in the journey"

Use when the slide reports progress through stages and you want to show the
*current* one. Drop the header intro so the track has room.

```python
s = build.blank(deck, tone="dark")
build.editorial_header(s, eyebrow_text="03  |  IMPLEMENTATION STATUS",
                       title="On track, and entering execution", tone="dark",
                       intro="Most initiatives are operational; focus is "
                             "shifting from build to delivery.")
build.phase_timeline(s, [
    ("01", "BUILD",    "Platform, model and tools established.", True),
    ("02", "ROLL-OUT", "Initiatives operational across countries.", True),
    ("03", "EXECUTE",  "Commercial impact and client-facing work.", False),
], y=4.0, tone="dark")
# Optional closing callout (bottom-anchored) — see callout note above.
```

`done=True` → mint node; the current phase (`done=False`) → larger gold node
with a "WE ARE HERE" tag. 3–5 phases read best.

---

## 2. Statement / pull-quote — the core message

Use for the single most important sentence in the deck. Almost always its own
slide, dark. The `statement` recipe already nails it.

```python
build.statement(deck,
    eyebrow_text="05  |  CORE MESSAGE",
    text="A clear shift toward the activities that win and grow business.",
    support_label="THE IMPLICATION",
    support="The strategy is increasingly focused on direct commercial impact.",
    pillars=[("Thought leadership", "Lead with market insight."),
             ("Senior engagement", "Dialogue with key leaders."),
             ("Sharper pitches", "Differentiated by supply-chain expertise."),
             ("Brokerage support", "Backing occupier and landlord teams.")],
    tone="dark")
```

Pillars and support are opt-in. A bare eyebrow + giant headline is a finished
slide.

---

## 3. From → to transition — "shift from X to Y"

Use when the message is a change of state. The TO panel is filled/emphasised
(the destination is the point); FROM is muted/outlined.

```python
s = build.blank(deck, tone="light")
cy = build.editorial_header(s, eyebrow_text="08  |  DATA & TECHNOLOGY",
        title="From build-up to impact and usability", tone="light",
        intro="Emphasis shifts from creating capability to making it useful.")
build.from_to(s, from_word="Build-up", to_word="Impact & usability",
              from_sub="capability created",
              to_sub="genuinely useful and commercially relevant",
              y=cy + 0.05, tone="light")
# Then two supporting points beneath + an optional objective callout.
```

---

## 4. Directional ladder — strengthened / refocused / deprioritised

Use for three (or more) categories that differ by *direction*. Colour +
arrow carry the semantics: mint/up = strengthened, gold/right = lateral,
blue/down = deprioritised. Drop the header intro.

```python
s = build.blank(deck, tone="dark")
build.editorial_header(s, eyebrow_text="11  |  KEY REFINEMENTS",
                       title="Strengthened, refocused, deprioritised",
                       tone="dark", title_size=32)
build.directional_ladder(s, [
    ("up",    "Strengthened",  COLORS["mint"], ["Thought leadership", "Client engagement", "Pitch quality"], None),
    ("right", "Refocused",     COLORS["gold"], ["Focus Client Programme", "Data strategy"], None),
    ("down",  "Deprioritised", COLORS["blue"], ["Consulting build-out", "Sector scaling"], "TEMPORARY"),
], y=2.4, tone="dark")
```

Items render as chips; rows fill from `y` to `ED_SAFE_BOT`. Keep items to
2–3 per row so chips stay readable.

---

## 5. Tier ladder — primary vs secondary

Use when the message is *what comes first*. The emphasised tier is filled
with a mint bar; lower tiers are outlined and muted.

```python
s = build.blank(deck, tone="light")
build.editorial_header(s, eyebrow_text="06  |  SERVICE OFFERING",
                       title="Continued development, at an adjusted priority",
                       tone="light")
build.tier_ladder(s, [
    {"label": "01 · PRIMARY FOCUS", "title": "Commercial execution",
     "note": "Everything now serves direct commercial impact.",
     "emphasis": True, "height": 1.55},
    {"label": "02 · SECONDARY, FOR NOW", "title": "Continued capability build-up",
     "items": ["Sector solutions", "European consulting capability"],
     "note": "Leverage existing capabilities; scale in a second phase.",
     "emphasis": False, "height": 1.85},
], y=2.7, tone="light")
```

---

## 6. Numbered editorial rows — required inputs / structured list

Use for "here are the N things". Also the right half of an asymmetric
summary slide (left = serif statement + mint vbar; right = the rows).

```python
s = build.blank(deck, tone="light")
build.eyebrow(s, "02  |  EXECUTIVE SUMMARY", tone="light", x=0.55, y=0.50)
# Left rail: serif statement + framed intro
build.serif_title(s, "Built, and now being sharpened",
                  x=0.55, y=1.15, w=3.55, h=2.0, size=30, tone="light")
build._vbar(s, x=0.55, y=3.55, h=2.45, color=COLORS["mint_dark"], width_in=0.05)
build.body(s, "Most of the strategy is operational; priorities are being reset.",
           x=0.83, y=3.52, w=3.27, h=2.4, size=12, tone="light",
           color=COLORS["ink_2"], line_spacing=1.42)
# Right: numbered rows with thin rules between
rx, rw = 4.65, build.SLIDE_W - 0.55 - 4.65
rows = [("Roll-out on track", "Most initiatives operational."),
        ("Priorities reset", "Driven by learnings, market shifts and AI."),
        ("Focus Clients refined", "Reduced, prioritised, grouped by intensity."),
        ("Commercial emphasis up", "Thought leadership and senior engagement."),
        ("Build-up continues", "Sector solutions and consulting, lower priority.")]
top, rh = 1.15, (build.ED_SAFE_BOT - 1.15) / len(rows)
for i, (t, d) in enumerate(rows):
    ry = top + i * rh
    if i:
        build._line(s, rx, ry, rx + rw, ry, color=COLORS["rule_light"], width_pt=0.75)
    build.num_row(s, i + 1, t, d, x=rx, y=ry + 0.16, w=rw, tone="light")
```

---

## 7. List + chip side panel — a list plus named entities

Use when a structured list is accompanied by a set of named things
(countries, teams, products). Left = `num_row` list; right = a panel of
`chip`s. Bottom = optional priority callout (fold any "outstanding" note
into the callout, not the panel, so the panel can't overflow).

```python
s = build.blank(deck, tone="dark")
cy = build.editorial_header(s, eyebrow_text="09  |  KNOWLEDGE DATABASE",
                            title="Strengthening the content base", tone="dark")
# left list via num_row (as above) ...
# right panel:
px, pw = 7.75, build.SLIDE_W - 0.55 - 7.75
panel_bot = build.ED_SAFE_BOT - 1.20            # leaves room for callout
build._rect(s, px, cy, pw, panel_bot - cy, fill=COLORS["green_2"])
build._rect(s, px, cy, pw, 0.05, fill=COLORS["gold"])
chy, chh = cy + 0.72, 0.44
for c in ["France", "United Kingdom", "Germany", "Netherlands", "Spain"]:
    build.chip(s, c, x=px + 0.32, y=chy, w=pw - 0.64, h=chh, tone="dark")
    chy += chh + 0.14
```

Size chips so the last one clears `panel_bot`; if 5 won't fit with an intro,
drop the header intro (`intro=None`).

---

## 8. Intensity bars panel — categorisation by weight

Use to show tiering visually (decreasing-width bars). Often the left half of
a slide whose right half is `num_row`s. Labels live in a fixed right column,
so they never collapse to negative width.

```python
build.intensity_bars(s, [
    ("HIGH INTENSITY",   "Top priority clients", COLORS["mint"],      1.00),
    ("MEDIUM INTENSITY", "Active management",     COLORS["mint_dark"], 0.72),
    ("LIGHT TOUCH",      "Selective engagement",  COLORS["rule_light"], 0.46),
], x=0.55, y=cy + 1.35, w=4.70, tone="light")
```

---

## 9. Stat hero / hero + outcome strip

One blockbuster number → `build.stat_hero(...)`. The payoff across a few
dimensions → a band of `arrow`s + words:

```python
band_y = cy + 1.70
build._rect(s, 0.55, band_y, build.ED_W, build.ED_SAFE_BOT - band_y,
            fill=COLORS["off_white"])
outcomes = ["Productivity", "Speed", "Quality"]
col_w = (build.ED_W - 0.8) / len(outcomes)
for i, o in enumerate(outcomes):
    ox = 0.95 + i * col_w
    build.arrow(s, "up", x=ox, y=band_y + 0.83, w=0.42, h=0.62, color=COLORS["mint"])
    build._text(s, o, x=ox + 0.65, y=band_y + 0.78, w=col_w - 0.9, h=0.40,
                font=FONTS["serif"], size=22, color=COLORS["green"])
    build._text(s, "improved", x=ox + 0.65, y=band_y + 1.24, w=col_w - 0.9,
                h=0.28, font=FONTS["sans_l"], size=11, color=COLORS["ink_2"])
```

---

## 10. Dense grid — the *one* place a card grid earns its keep

A 3×2 `roman_card` grid is the right call for an **executive summary** that
genuinely has six parallel threads — but it should appear at most once per
deck, not as the default for every list. Use `min_h_for_roman_card` to size
it and let the cards bottom-align as a grid. See the four-layer cramming
defence in `spacing-and-rules.md` §17.

---

## Anti-patterns

- The same skeleton on consecutive slides. Vary it.
- A bottom callout on every slide ("CBRE VIEW" / "OBJECTIVE" / "IMPLICATION").
  Reads as templated; attach only when a slide has one takeaway to underline.
- Echoing a callout's title in its body.
- Stretching cards to fill height when content is short — that creates voids
  *inside* the cards. Content-size the cards and let whitespace fall at the
  slide's bottom edge (intentional margin) instead.
- Back-solved widths that can go negative (`w = panel - sibling - gap`) — they
  corrupt the file. Use a fixed column for variable-width siblings.
