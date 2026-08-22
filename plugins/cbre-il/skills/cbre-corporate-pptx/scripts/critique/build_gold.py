"""Build the gold reference deck from fictional content, and install it.

The critique step needs a real bar to judge against, and that bar has to ship
with the skill - which means it cannot be a client deck. So the reference is
generated here from a fictional occupier ("Meridian Components"), using the
composer itself. Two things fall out of that: the gold set is redistributable,
and regenerating it is a genuine end-to-end test of the library.

    python scripts/critique/build_gold.py

Every scene below is composed from its point rather than taken off the shelf,
except one that names why a preset is the right call - which is exactly the
discipline the shape audit enforces, demonstrated rather than described.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
for _p in (_SCRIPTS, Path.home() / ".claude/skills/cbre-corporate-pptx/scripts"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
        break

import compose          # noqa: E402
import contact_sheet    # noqa: E402

GOLD_DIR = _HERE / "gold"

# Slide -> the standard that slide is in the set to demonstrate. Index is
# 1-based and matches the rendered deck.
DEMONSTRATES = {
    2: ("white-two-option-split",
        "Two parallel options in prose, then a three-part test band. Restraint: "
        "a third of the slide is deliberately air."),
    3: ("white-stage-track",
        "A five-stage process track with a closing strap. Dense without being "
        "crammed."),
    4: ("white-prose-panel-kpis",
        "Asymmetric split: prose against a dark value panel, five-up KPI row "
        "beneath."),
    5: ("dark-shift",
        "A from-to on dark. The destination is emphasised; the origin is muted."),
    7: ("white-evidence-table",
        "Tabular evidence where the last column is an analytical read, not a "
        "restatement of the row."),
    8: ("dark-statement",
        "What dark is for: one sentence that carries the argument."),
    9: ("white-hero-stat",
        "One number with space around it. The only slide here that took a "
        "preset, and it says why."),
}


PLAN = {
    "deck_meta": {"eyebrow": "CBRE | ADVISORY"},
    "slides": [
        {"kind": "cover", "tone": "dark",
         "eyebrow": "REFERENCE SET | COMPOSITION STANDARD",
         "title": "Meridian Components",
         "subtitle": "A fictional occupier, used to set the visual bar.",
         "date": "AUGUST 2026",
         "themes": ["The choice", "The process", "The evidence", "The answer"]},

        # 2 - two options in prose, then a test band
        {"kind": "scene", "tone": "light",
         "eyebrow": "OCCUPIER OPTIONS | LEIPZIG",
         "headline": "Two Routes to the Leipzig Site",
         "scene": [
             {"weight": 1.0, "cells": [
                 {"kind": "prose", "label": "OPTION 01  |  FREEHOLD",
                  "text": "Meridian buys the building and holds it on its own "
                          "balance sheet. It controls the asset outright, with "
                          "no landlord and no lease term, but the capital stays "
                          "tied up in property and Meridian carries the "
                          "residual value risk."},
                 {"kind": "prose", "label": "OPTION 02  |  LEASE",
                  "text": "An investor owns the building and Meridian takes a "
                          "long lease. The capital is released into the "
                          "operating business, and the obligation is a rent "
                          "line rather than an asset on the balance sheet."}]},
             {"weight": 0.75, "cells": [
                 {"kind": "prose", "label": "THE FINANCIAL TEST",
                  "text": "Ownership only pays where the building's overall "
                          "yield sits below the cost of capital."},
                 {"kind": "prose", "label": "THE OPERATIONAL TEST",
                  "text": "How would a lease change day-to-day control over "
                          "alterations and capital spend on the site?"},
                 {"kind": "prose", "label": "THE STRATEGIC TEST",
                  "text": "Would owning this building give Meridian an "
                          "advantage a long lease could not deliver?"}]}]},

        # 3 - process track
        {"kind": "scene", "tone": "light",
         "eyebrow": "ACQUISITION SUPPORT | LEIPZIG",
         "headline": "Five Stages From Opinion of Price to Completion",
         "scene": [
             {"weight": 1.0, "cells": [
                 {"kind": "timeline", "phases": [
                     ["01", "ESTABLISH VALUE", "Opinion of price, benchmarked "
                      "against comparable assets.", True],
                     ["02", "TEST ALTERNATIVES", "Screen other buildings and "
                      "price a build-to-suit.", True],
                     ["03", "NEGOTIATE", "Agree strategy and red lines, then "
                      "issue the offer.", False],
                     ["04", "DILIGENCE", "Brief and coordinate advisers; track "
                      "every finding to closure.", False],
                     ["05", "COMPLETE", "Manage the signing timetable and hand "
                      "over the record.", False]]}]},
             {"weight": 0.32, "cells": [
                 {"kind": "callout", "title": "THROUGHOUT",
                  "text": "CBRE runs the process end to end, holds the "
                          "timetable and gives Meridian one point of "
                          "accountability."}]}]},

        # 4 - asymmetric prose + panel, KPI row beneath
        {"kind": "scene", "tone": "light",
         "eyebrow": "OPINION OF PRICE | LEIPZIG",
         "headline": "A 2023 Build Valued at EUR 8.5m to 9.8m",
         "lead": "Our view on the market value of the production and warehouse "
                 "building Meridian is considering.",
         "scene": [
             {"weight": 1.0, "cells": [
                 {"kind": "prose", "label": "THE PROPERTY", "span": 1.5,
                  "text": "The property sits in an established production and "
                          "service area on a regular, fully developed plot with "
                          "good road access. The site cannot be extended, but "
                          "the adjacent undeveloped plot offers room to grow. "
                          "The location is one of the region's main warehousing "
                          "hubs, and the motorway link supports occupier "
                          "demand."},
                 {"kind": "panel", "title": "INDICATIVE MARKET VALUE",
                  "items": [{"label": "MINIMUM PRICE", "value": "EUR 8,500,000"},
                            {"label": "AVERAGE PRICE", "value": "EUR 9,000,000"},
                            {"label": "MAXIMUM PRICE", "value": "EUR 9,800,000"}]}]},
             {"weight": 0.5, "cells": [
                 {"kind": "stat", "value": "15,288", "label": "sqm total usable area"},
                 {"kind": "stat", "value": "7,038", "label": "sqm production space"},
                 {"kind": "stat", "value": "5,887", "label": "sqm warehouse space"},
                 {"kind": "stat", "value": "2,363", "label": "sqm office and ancillary"},
                 {"kind": "stat", "value": "19,850", "label": "sqm land plot"}]}]},

        # 5 - the shift, on dark
        {"kind": "scene", "tone": "dark",
         "eyebrow": "THE SHIFT | CAPITAL STRATEGY",
         "headline": "From Holding Property to Funding Operations",
         "scene": [
             {"weight": 1.0, "cells": [
                 {"kind": "from_to", "from_word": "Capital in bricks",
                  "to_word": "Capital in the business",
                  "from_sub": "value tied to an asset Meridian does not trade",
                  "to_sub": "released into capacity, tooling and headcount"}]},
             {"weight": 0.6, "cells": [
                 {"kind": "prose",
                  "text": "The building is not the point. Meridian makes "
                          "components, and every euro sitting in freehold is a "
                          "euro not making them. The question is whether "
                          "ownership earns its place against that alternative."}]}]},

        {"kind": "section", "tone": "dark", "number": 2,
         "title": "The evidence",
         "lead": "What the numbers say once both routes are priced on the same "
                 "terms.",
         "items": ["Cost of occupation", "Where it flips", "The answer"]},

        # 7 - evidence table
        {"kind": "scene", "tone": "light",
         "eyebrow": "COST OF OCCUPATION | TEN-YEAR VIEW",
         "headline": "Both Routes Priced on the Same Terms",
         "scene": [
             {"weight": 1.0, "cells": [
                 {"kind": "table",
                  "headers": ["", "FREEHOLD", "LEASE", "WHAT IT MEANS"],
                  "rows": [
                      ["Day-one cash", "(8.6m)", "(0.2m)", "Ownership asks for the price today"],
                      ["Annual cost", "(0.31m)", "(0.92m)", "Rent is the visible cost of leasing"],
                      ["Exit value", "6.1m", "nil", "Discounted, a distant recovery"],
                      ["NPV of occupying", "(7.9m)", "(7.4m)", "Least negative wins; leasing is ahead"],
                      ["Cost per sqm/month", "EUR 5.74", "EUR 5.37", "The figure that reads against rent"]]}]},
             {"weight": 0.3, "cells": [
                 {"kind": "callout", "title": "READ IT THIS WAY",
                  "text": "Every figure is a cost, so all of them are negative "
                          "and the least negative option wins."}]}]},

        # 8 - statement on dark
        {"kind": "scene", "tone": "dark",
         "eyebrow": "THE ARGUMENT",
         "headline": "Owning Only Wins Below a 6.3% Cost of Capital",
         "scene": [
             {"weight": 1.0, "cells": [
                 {"kind": "quote",
                  "text": "Every rate above 6.3% favours leasing, and Meridian's "
                          "own disclosed cost of capital sits well above it.",
                  "attrib": "CBRE cost of occupation model"}]},
             {"weight": 0.55, "cells": [
                 {"kind": "prose", "label": "WHAT THIS DOES NOT PRICE",
                  "text": "Control of the asset, room to expand on the adjacent "
                          "plot, and the lease liability that lands on the "
                          "balance sheet. None are in the NPV, and all three "
                          "belong in the decision."}]}]},

        # 9 - one number; the single justified preset
        {"kind": "scene", "tone": "light",
         "eyebrow": "THE ANSWER",
         "headline": "The Gap Between the Two Routes",
         "shape": "poster",
         "shape_why": "The slide is one number and the space around it. The "
                      "poster shape exists for exactly that and adding rows "
                      "would only dilute it.",
         "cells": [
             {"kind": "stat", "value": "EUR 0.5m",
              "label": "present-value advantage to leasing over ten years"}]},

        {"kind": "closing", "tone": "dark", "title": "Thank you.",
         "subtitle": "Questions and next steps."},
    ],
}


def main():
    out = Path(tempfile.mkdtemp(prefix="gold_")) / "GoldReference.pptx"
    print("building the reference deck...")
    compose.render(PLAN, str(out), audit=True, shapes_strict=True,
                   geometry_strict=True)

    print("\nrendering slides...")
    tmp = Path(tempfile.mkdtemp(prefix="gold_png_"))
    pngs, backend = contact_sheet.render_slides(out, tmp)
    print(f"  {len(pngs)} slides, backend={backend}")

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    for old in GOLD_DIR.glob("*.png"):
        old.unlink()

    kept = []
    for i, png in enumerate(pngs, start=1):
        if i not in DEMONSTRATES:
            continue
        name, _ = DEMONSTRATES[i]
        dst = GOLD_DIR / f"{name}.png"
        shutil.copy2(png, dst)
        kept.append(dst)
        print(f"  slide {i:02d} -> {dst.name}")

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(out.parent, ignore_errors=True)
    print(f"\ninstalled {len(kept)} reference slides in {GOLD_DIR}")
    if backend == "libreoffice":
        print("  [warn] rendered via LibreOffice, so the CBRE fonts are "
              "substituted. Regenerate on Windows before trusting this as a "
              "typography reference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
