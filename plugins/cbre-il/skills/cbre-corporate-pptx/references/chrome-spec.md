# Chrome spec — the part that never varies

Measured from a signed-off CBRE proposal, in inches on the 13.33 x 7.50 canvas.

Everything on this page is **invariant**. It is the letterhead, not the design.
Reproduce it identically on every content slide; there is no creative decision
here and varying it just makes slides look inconsistent. The composer already
draws it for you via `_chrome()` — this file exists so the numbers are written
down, and so a hand-built slide can match a composed one exactly.

Contrast with the scene *below* the chrome, which should be composed fresh for
every slide. See the skeleton-discipline section in `SKILL.md`.

## The frame

| Element | x | y | w | h | Type |
|---|---|---|---|---|---|
| Eyebrow text | 0.55 | 0.50 | 8.00 | 0.18 | Calibre Semibold 10pt, uppercase, letter-spaced 1.5 |
| Eyebrow rule (under variant) | 0.55 | 0.94 | 1.65 | 0.02 | Primary accent |
| Headline | 0.55 | 1.00 | 12.23 | 0.51 | Financier Display, title case, >= 20pt |
| Lead (optional, one line) | 0.55 | 1.50 | 12.23 | 0.24 | Calibre Light ~11pt |
| Content top | 0.55 | **2.00** | 12.23 | — | Scene starts here |
| Closing strap rule (optional) | 0.55 | ~6.30 | 12.23 | 0.02 | Rule above a final one-line read |
| Footer | 0.55 | bottom band | — | — | "Confidential & Proprietary \| (c) YEAR CBRE, Inc." |
| Page number | right | bottom band | — | — | Small, right-aligned |

Content width is **12.23** with **0.55** margins either side; the right edge
lands at 12.78. Safe bottom is `build.ED_SAFE_BOT`.

## Two eyebrow variants, both correct

1. **Rule under** — eyebrow text at x=0.55, a 1.65" accent rule directly beneath
   at y=0.94. The default, and what `build.eyebrow()` draws.
2. **Rule left** — a short accent rule at x=0.55 (about 1.15" x 0.04") with the
   eyebrow text starting after it, around x=1.95, on the same baseline.

Pick one **per deck** and hold it. Mixing them across slides in one deck is the
inconsistency this spec exists to prevent.

## Column pitches

All derived from `width = (12.23 - gap * (n - 1)) / n`, which is exactly what
the composer computes. Written out so hand-built slides match:

| Columns | Cell w | Gap | x positions |
|---|---|---|---|
| 2 | 5.92 | 0.40 | 0.55, 6.87 |
| 3 | 3.81 | 0.40 | 0.55, 4.76, 8.97 |
| 5 | 2.21 | 0.295 | 0.55, 3.06, 5.56, 8.07, 10.58 |

A five-up KPI row sits slightly tighter in the reference (w=2.13, pitch 2.52);
either reads correctly, so prefer the composer's computed value and stay
consistent within a slide.

## Accent

Tone-conditional, and applied for you by `compose._accent(tone)` and
`build.eyebrow(...)`:

- **Dark ground** -> Wheat gold `#D8D898`
- **White ground** -> Accent Green `#17E88F`

Celadon mint `#80B8A8` is the secondary accent on either ground. Do not
hard-code an accent colour; take it from the helper so the rule holds.
