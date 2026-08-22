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

        # --- skeletons: a flat cell list carved up by a named geometry ------
        # rail: a full-height left column beside a stack. The asymmetric shape
        # the rows-only model could not express.
        {"kind": "scene", "tone": "dark", "shape": "rail", "eyebrow": "04 | RAIL",
         "headline": "One argument, evidence stacked beside it",
         "cells": [
            {"kind": "prose", "label": "THE READ",
             "text": "A rail puts the argument on the left at full height and lets the evidence stack independently on the right, so the two read as claim and support rather than as two unrelated bands."},
            {"kind": "stat", "value": "46%", "label": "of new leases in Tier-2 corridors"},
            {"kind": "stat", "value": "17", "label": "BTS projects in advanced planning"}]},

        # hero: one dominant cell over a supporting strip
        {"kind": "scene", "tone": "light", "shape": "hero", "eyebrow": "05 | THE SHIFT",
         "headline": "From build-up to impact",
         "cells": [
            {"kind": "from_to", "from": "Build-up", "to": "Impact and usability",
             "from_sub": "capability created", "to_sub": "commercially relevant"},
            {"kind": "prose", "text": "Emphasis moves from creating capability to making it useful."},
            {"kind": "prose", "text": "The same teams, pointed at outcomes rather than platform work."}]},

        # bands: a single tall device
        {"kind": "scene", "tone": "dark", "shape": "bands", "eyebrow": "06 | STATUS",
         "headline": "On track, and entering execution",
         "cells": [
            {"kind": "timeline", "phases": [
                {"n": "01", "label": "BUILD", "text": "Platform and tooling established.", "done": True},
                {"n": "02", "label": "ROLL-OUT", "text": "Operational across markets.", "done": True},
                {"n": "03", "label": "EXECUTE", "text": "Commercial impact and client work.", "done": False}]}]},

        # ledger: a narrow read against wide evidence
        {"kind": "scene", "tone": "light", "shape": "ledger", "eyebrow": "07 | PRIORITY",
         "headline": "Where to focus first",
         "cells": [
            {"kind": "prose", "text": "Priority here is a decision about sequence, not about importance."},
            {"kind": "tiers", "tiers": [
                {"label": "01 - PRIMARY FOCUS", "title": "Commercial execution",
                 "note": "Everything now serves direct commercial impact.", "emphasis": True},
                {"label": "02 - SECONDARY, FOR NOW", "title": "Capability build-out",
                 "note": "Leverage what exists; scale in a second phase."}]}]},

        # mosaic: two devices side by side
        {"kind": "scene", "tone": "dark", "shape": "mosaic", "eyebrow": "08 | REFINEMENTS",
         "headline": "Strengthened, refocused, deprioritised",
         "cells": [
            {"kind": "directions", "rows": [
                {"direction": "up", "label": "Strengthened",
                 "items": ["Thought leadership", "Client engagement"]},
                {"direction": "down", "label": "Deprioritised",
                 "items": ["Sector scaling"], "subtag": "TEMPORARY"}]},
            {"kind": "bars", "tiers": [
                {"label": "HIGH", "sub": "Top priority", "frac": 1.0},
                {"label": "MEDIUM", "sub": "Active management", "frac": 0.72},
                {"label": "LIGHT", "sub": "Selective", "frac": 0.46}]}]},

        # poster: one blockbuster number, space left beneath
        {"kind": "scene", "tone": "light", "shape": "poster", "eyebrow": "09 | THE NUMBER",
         "headline": "One number that carries the case",
         "cells": [
            {"kind": "stat", "value": "EUR 16.9m", "label": "annual run-rate", "scale": "hero"},
            {"kind": "prose", "text": "Achieved without additional headcount."}]},

        # explicit nesting: a split cell inside a row
        {"kind": "scene", "tone": "dark", "eyebrow": "10 | NESTED",
         "headline": "A quadrant built by nesting",
         "scene": [
            {"weight": 1.0, "cells": [
                {"kind": "quote", "span": 0.9,
                 "text": "Compose the slide the argument wants.", "attrib": "House rule"},
                {"kind": "split", "span": 1.1, "scene": [
                    {"weight": 1.0, "cells": [{"kind": "heading", "text": "What changed"}]},
                    {"weight": 2.0, "cells": [
                        {"kind": "prose", "text": "Nesting is a partition of a partition, so asymmetry costs nothing in safety."},
                        {"kind": "chips", "items": ["rail", "hero", "ledger", "mosaic"]}]}]}]}]},

        {"kind": "section", "tone": "dark", "number": 2, "title": "What it means",
         "lead": "From context to action.", "items": ["Release", "Reuse", "Redesign"]},

        {"kind": "closing", "tone": "dark", "title": "Thank you.",
         "contacts": [{"name": "A. Advisor", "title": "Director, I&L", "email": "a.advisor@cbre.com"}]},
    ],
}

print("composing (no PowerPoint: resolve + label + bake off)...")
# This file is a COVERAGE harness: it must exercise every skeleton and every
# cell kind in one deck, so the editorial-discipline checks (rationing, the
# shape_why requirement, the novelty floor) cannot apply to it - a real deck
# would never use all six skeletons. Structural checks still run strict:
# repeated skeletons and any geometry problem (canvas bleed, text past the
# safe bottom, text-on-text collision) fail the test rather than printing a
# warning nobody reads.
audit_scene_shapes_result = compose.audit_scene_shapes(
    plan, verbose=True, strict=True, discipline=False)
compose.render(plan, str(out), resolve=False, label_and_bake=False,
               audit=False, geometry_strict=True)
from pptx import Presentation  # noqa: E402
n = len(Presentation(str(out)).slides)
print(f"OK: composed {n} slides -> {out}")
assert n == 15, f"expected 15 slides, got {n}"

# Every cell kind the composer advertises must actually be reachable.
missing = compose.CELL_KINDS - set(compose.CELL) - {"split"}
assert not missing, f"cell kinds declared but not registered: {missing}"
print(f"PASS: {n} slides, {len(compose.CELL)} cell kinds, "
      f"{len(compose.SKELETONS)} skeletons, strict audits clean")
