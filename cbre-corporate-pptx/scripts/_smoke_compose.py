"""Smoke test for the scene composer: exercise every slide kind and cell kind,
build with no PowerPoint (resolve + label + bake off) so it runs anywhere.
Run: python scripts/_smoke_compose.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compose  # noqa: E402

out = HERE / "_smoke_out" / "ComposeSmoke.pptx"
out.parent.mkdir(exist_ok=True)

plan = {
    "deck_meta": {"eyebrow": "CBRE | SMOKE TEST"},
    "slides": [
        {"kind": "cover", "tone": "dark", "eyebrow": "CBRE | ADVISORY",
         "title": "A story-led scene deck", "subtitle": "Composed, not poured into recipes",
         "date": "JUNE 2026", "themes": ["Context", "The shift", "Evidence", "What it means"]},

        # prose + a 3-stat KPI row
        {"kind": "scene", "tone": "dark", "eyebrow": "01 | CONTEXT",
         "headline": "The market is consolidating into fewer, larger nodes", "lead": "Demand is migrating, not growing.",
         "footer": "Source: illustrative.",
         "scene": [
            {"weight": 1.3, "cells": [{"kind": "prose", "label": "THE SHIFT",
              "text": "Occupiers are concentrating volume into a smaller number of larger, better-connected sites, releasing surplus space at the edges. The result is a market that is reshaping rather than expanding, with the action in transfer and reuse rather than new build."}]},
            {"weight": 0.8, "cells": [
              {"kind": "stat", "value": "46%", "label": "of new leases in Tier-2 corridors"},
              {"kind": "stat", "value": "17", "label": "BTS projects in advanced planning"},
              {"kind": "stat", "value": "EUR 1.40", "label": "energy premium per sqm vs 2022"}]}]},

        # list + panel
        {"kind": "scene", "tone": "light", "eyebrow": "02 | OPERATING MODEL",
         "headline": "Make in-house, move through third parties",
         "scene": [
            {"weight": 1.0, "cells": [
              {"kind": "list", "numbered": True, "items": [
                {"title": "Make", "text": "Regulated in-house manufacturing across a largely owned estate."},
                {"title": "Move", "text": "Distribution outsourced to 3PLs who hold the occupier leases."},
                {"title": "Rebalance", "text": "The network is rebalanced region by region as volumes shift."}]},
              {"kind": "panel", "title": "THE LENS", "items": [
                {"label": "Tenure", "value": "Owned core; small lease book"},
                {"label": "Governance", "value": "Reports to the CFO; lean EMEA team"}]}]}]},

        # table
        {"kind": "scene", "tone": "light", "eyebrow": "03 | NETWORK",
         "headline": "A compact European network", "lead": "Two currents: reshoring and contraction.",
         "scene": [
            {"weight": 1.0, "cells": [
              {"kind": "table", "headers": ["Region", "Site", "Use", "Read"],
               "aligns": ["left", "left", "left", "left"],
               "rows": [["NL", "Best", "Imaging", "Flagship, sticky"],
                        ["DE", "Hamburg", "Tubes", "Centre of excellence"],
                        ["US", "Reedsville", "Ultrasound", "Reshoring"]]}]}]},

        # quote + callout
        {"kind": "scene", "tone": "dark", "eyebrow": "04 | VOICE",
         "headline": "What leadership says",
         "scene": [
            {"weight": 1.2, "cells": [{"kind": "quote",
              "text": "We are consolidating to fewer, larger, better-connected nodes.", "attrib": "CFO, FY2025 call"}]},
            {"weight": 0.9, "cells": [{"kind": "callout", "title": "CBRE VIEW",
              "text": "The opportunity is integration readiness and surplus release, not a speculative expansion pitch.", "tag": "PRIORITY"}]}]},

        # chips + card row + image placeholder
        {"kind": "scene", "tone": "light", "eyebrow": "05 | PRIORITIES",
         "headline": "Where to focus first",
         "scene": [
            {"weight": 0.4, "cells": [{"kind": "chips", "items": ["Poland", "Germany", "Iberia", "Nordics", "CEE", "France"]}]},
            {"weight": 1.3, "cells": [
              {"kind": "card", "style": "decimal", "n": 1, "title": "Release", "text": "Dispose of surplus edge sites."},
              {"kind": "card", "style": "decimal", "n": 2, "title": "Reuse", "text": "Retrofit retained sites for energy."},
              {"kind": "card", "style": "decimal", "n": 3, "title": "Redesign", "text": "Plan the combined network."}]},
            {"weight": 0.9, "cells": [{"kind": "image", "path": "does_not_exist.png", "alt": "network map placeholder"}]}]},

        {"kind": "section", "tone": "dark", "number": 2, "title": "What it means",
         "lead": "From context to action.", "items": ["Release", "Reuse", "Redesign"]},

        {"kind": "closing", "tone": "dark", "title": "Thank you.",
         "contacts": [{"name": "A. Advisor", "title": "Director, I&L", "email": "a.advisor@cbre.com"}]},
    ],
}

print("composing (no PowerPoint: resolve + label + bake off)...")
compose.render(plan, str(out), resolve=False, label_and_bake=False, audit=False)
from pptx import Presentation  # noqa: E402
n = len(Presentation(str(out)).slides)
print(f"OK: composed {n} slides -> {out}")
assert n == 8, f"expected 8 slides, got {n}"
print("PASS")
