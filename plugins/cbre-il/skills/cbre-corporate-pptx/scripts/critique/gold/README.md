# Gold reference — a yardstick, not a source

Finished CBRE slides that hit the standard. They exist for **one purpose**: so a
rendered deck can be judged against a real bar before it is delivered.

## The rule

**Do not read these while composing a deck.**

They are an input to the *critique* step and to nothing else. A finished slide
shown to the author becomes a template to copy, and copying is the failure this
whole system is built to prevent. The same slide shown to the critic is a
standard to meet. Same file, opposite effect; the only difference is which step
is looking at it.

That is why they live under `scripts/critique/` and not under `references/`.
`references/` is read during planning. This folder is not.

## How to use them

After rendering, before delivery:

```bash
python scripts/critique/critique.py MyDeck.pptx
```

It tiles your deck and this reference set into two comparable sheets and prints
the questions. Look at both, then fix the **plan** and re-render. Never nudge a
coordinate: that is the composer's job, and hand-placement is exactly what the
geometry audit exists to prevent.

## What each one demonstrates

| File | The standard it sets |
|---|---|
| `white-two-option-split.png` | Two parallel options in prose, then a three-part test band. A third of the slide is deliberately air. |
| `white-stage-track.png` | A five-stage process track with a closing strap. Dense without being crammed. |
| `white-prose-panel-kpis.png` | Asymmetric split: prose against a dark value panel, five-up KPI row beneath. |
| `dark-shift.png` | A from-to on dark. The destination is emphasised, the origin muted. |
| `white-evidence-table.png` | Tabular evidence whose last column is an analytical read, not a restatement of the row. |
| `dark-statement.png` | What dark is for: one sentence carrying the argument. |
| `white-hero-stat.png` | One number with space around it. The only slide here that took a preset, and it says why. |

Note the accent in each: wheat gold on the dark grounds, Accent Green on the
white ones. That rule is visible across the set and is worth checking your own
deck against.

## Provenance

**Generated, not client work.** The whole set is built by
`scripts/critique/build_gold.py` from a fictional occupier ("Meridian
Components"), using this library. It carries no client-identifying content and
is safe to ship with the skill.

Regenerate any time — it is also a genuine end-to-end test of the composer, the
three audits and the render pipeline:

```bash
python scripts/critique/build_gold.py
```

Do that on Windows where possible. The PowerPoint COM path uses the real CBRE
fonts; the LibreOffice fallback substitutes them, which makes the set useless as
a typography reference even though the composition still reads.

Files beginning with `_` are generated output (the tiled sheet) and are skipped
when the sheet is rebuilt.
