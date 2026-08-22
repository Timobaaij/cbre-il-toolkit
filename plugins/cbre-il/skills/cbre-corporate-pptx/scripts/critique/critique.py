"""Judge a rendered deck against the gold reference.

The library has always been able to render slides to PNG, and only ever used
that to correct text-box heights. Nothing ever *looked* at the result. No
assertion can catch "this deck reads as templated" or "slide 6 is a wall of
grey"; seeing the whole deck at once catches both immediately.

This is the last step before delivery:

    python scripts/critique/critique.py MyDeck.pptx

or

    import critique
    deck_sheet, gold_sheet = critique.compare("MyDeck.pptx")

Then LOOK at both images and answer the questions it prints. Fix the **plan**
and re-render. Never nudge a coordinate - hand-placement is exactly what the
geometry audit exists to prevent.

Note on the gold set: it is a yardstick, never a source. It is read here, at
critique time, and nowhere else. A finished slide shown to the author becomes a
template to copy; the same slide shown to the critic is a standard to meet.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
GOLD_DIR = _HERE / "gold"

for _p in (_HERE.parent, Path.home() / ".claude/skills/cbre-corporate-pptx/scripts"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break

import contact_sheet  # noqa: E402


QUESTIONS = """
Look at both sheets side by side, then answer honestly:

  1. HIERARCHY   Does every slide read eyebrow -> rule -> serif headline ->
                 one line of lead -> content? Or does the eye land nowhere?
  2. RESTRAINT   The gold slides leave a lot of white space and never fill it
                 for the sake of filling it. Is yours as calm, or is it padded?
  3. VARIETY     Across the deck: has each slide been composed from its own
                 point, or is one layout wearing different words? The shape
                 audit catches exact repeats; only your eye catches near ones.
  4. TONE        Does dark carry the cover, dividers and statement moments, and
                 white carry the content slides that do the work?
  5. ACCENT      Wheat gold on dark, Accent Green on white. Anything off-rule
                 will look muddy rather than wrong, so check it deliberately.
  6. THE BAR     Would this sit in the same deck as the gold slides without
                 looking generated?

Anything that fails goes back to the PLAN. Re-render. Do not adjust coordinates.
"""


def gold_sheet(out_path=None, *, cols: int = 3):
    """Tile the gold reference slides into one sheet."""
    # Leading underscore marks generated output (the sheet itself lands here),
    # so it never gets swept back into the next sheet.
    pngs = sorted(p for p in GOLD_DIR.glob("*.png")
                  if not p.name.startswith("_"))
    if not pngs:
        raise FileNotFoundError(
            f"no gold reference images in {GOLD_DIR}. See its README.")
    out_path = Path(out_path) if out_path else GOLD_DIR / "_gold.contact.png"
    labels = [p.stem.replace("-", " ") for p in pngs]
    return contact_sheet.tile(pngs, out_path, cols=cols, labels=labels)


def compare(pptx, *, cols: int = 3):
    """Build the deck's contact sheet and the gold sheet, print the questions.

    Returns (deck_sheet_path, gold) where `gold` is a sheet path if the tiler
    is available, otherwise the list of individual gold images.
    """
    deck = contact_sheet.build(pptx, cols=cols)
    try:
        gold = gold_sheet(cols=cols)
    except FileNotFoundError as exc:
        print(f"[critique] {exc}")
        gold = []
    print(f"\n[critique] deck sheet : {deck}")
    if isinstance(gold, list):
        print("[critique] gold       : %d reference slides in %s"
              % (len(gold), GOLD_DIR))
    else:
        print(f"[critique] gold sheet : {gold}")
    print(QUESTIONS)
    return deck, gold


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    compare(sys.argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
