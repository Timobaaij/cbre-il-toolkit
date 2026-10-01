"""Smoke test for the story-first additions: the `draw` cell and
`parallel_group`. Run from the scripts folder: python _smoke_story.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build
import compose


def two_routes(s, x, y, w, h, tone):
    """Two origins, one destination: the shape of an inbound-versus-outbound
    trade-off. Drawn only inside the rect it is given."""
    ink = build.COLORS["white"] if tone == "dark" else build.COLORS["green"]
    dot = 0.16
    pts = {"A": (x + 0.10 * w, y + 0.75 * h), "B": (x + 0.10 * w, y + 0.20 * h),
           "C": (x + 0.85 * w, y + 0.45 * h)}
    for k, (px, py) in pts.items():
        build._rect(s, px - dot / 2, py - dot / 2, dot, dot, fill=ink)
        build._text(s, k, x=px + 0.12, y=py - 0.14, w=0.40, h=0.28, size=11, color=ink)


def plan(series_skeleton):
    q = lambda n: {"kind": "scene", "tone": "light", "parallel_group": "questions",
                   "eyebrow": f"0{n} | QUESTION", "headline": f"Question {n} framed",
                   "scene": series_skeleton}
    return {"deck_meta": {"eyebrow": "CBRE | TEST"}, "slides": [
        {"kind": "cover", "title": "Story first", "subtitle": "Smoke", "date": "OCTOBER 2026"},
        q(1), q(2), q(3),
        {"kind": "scene", "tone": "dark", "eyebrow": "04 | THE PICTURE",
         "headline": "The picture the point needs",
         "scene": [{"weight": 1.0, "cells": [
             {"kind": "prose", "span": 0.8, "text": "One origin is closer to supply, the other to customers."},
             {"kind": "draw", "name": "two_routes", "fn": two_routes, "min_h": 2.0, "span": 1.2}]}]},
        {"kind": "closing", "title": "Thank you."},
    ]}


SERIES = [{"weight": 1.0, "cells": [{"kind": "prose", "text": "What we heard."},
                                    {"kind": "prose", "text": "What it means."}]}]

r = compose.audit_scene_shapes(plan(SERIES), verbose=True)
assert r["ok"], r["warnings"]
assert len(r["groups"]) == 3

broken = plan(SERIES)
broken["slides"][3]["scene"] = [{"weight": 1.0, "cells": [{"kind": "quote", "text": "x"}]}]
r2 = compose.audit_scene_shapes(broken, verbose=False)
assert any("does not share one skeleton" in w for w in r2["warnings"])

def escapes(s, x, y, w, h, tone):
    build._rect(s, x + w - 0.1, y, 1.0, 0.3, fill=build.COLORS["green"])

bad = plan(SERIES)
bad["slides"][4]["scene"][0]["cells"][1]["fn"] = escapes
try:
    compose.render(bad, str(Path(tempfile.mkdtemp()) / "bad.pptx"), resolve=False,
                   label_and_bake=False, audit=False)
    raise SystemExit("out-of-bounds diagram was not caught")
except compose.DiagramOutOfBounds as e:
    print("[ok] caught:", str(e)[:70])

out = Path(tempfile.mkdtemp()) / "story.pptx"
compose.render(plan(SERIES), str(out), resolve=False, label_and_bake=False,
               shapes_strict=True)
print("[ok] rendered", out)

