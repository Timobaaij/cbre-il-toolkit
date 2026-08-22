#!/usr/bin/env python3
"""media_harvest_test.py - the MEDIA UNDER-HARVEST fix, end to end (2026-08-20).

The defect this suite pins: every media tier degrades to an honest `None`/`[]` when it cannot
answer, so a run whose image layer is dead is INDISTINGUISHABLE, in every artefact it writes,
from a run whose sources hold no images. Four parts:

  A  VECTOR site-plan detection - a full-page vector masterplan on a colour background (the shape
     the pixel classifier reads as 'photo' and the white-balance band rejects) binds the plan slot
     with NO LLM nomination, while an equally vector-dense LOCATION MAP on the same background
     does NOT. The discriminator is site-plan drawing FURNITURE, not vector density.
  B  media_capabilities() / deck_media_facts() - the hard probe and the cheap "what does this deck
     HOLD" arithmetic the gate needs.
  C  the `media-harvest` gate - the under-harvest, blind-agent and orphan-page SIGNALS fire, and
     it is always ALL-PASS (advisory).
  D  the per-property CONSIDERED SET - attach_media's recording is pure (byte-identical media with
     and without it), and the projection is derived (canonical.json bytes untouched) while
     producing media/considered/, media_decisions.json and properties/_unassigned/.

Offline; no network, no LLM. Run: python evals/media_harvest_test.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


# --------------------------------------------------------------------------------------- #
# Fixture deck
# --------------------------------------------------------------------------------------- #
# The furniture vocabulary is what a site LAYOUT writes on itself. Six distinct tokens, so the
# page clears PLAN_FURNITURE_SPEC_MIN too - a real masterplan sheet legitimately also carries
# enough own-line labels to read as a spec page, and the point of the test is the VECTOR route,
# not the spec gate's exact verdict on a synthetic page.
_FURNITURE_TEXT = ("SERVICE YARD    50 m yard depth\n"
                   "42 dock doors    4 level access doors\n"
                   "120 car parking spaces    36 HGV parking\n"
                   "GATEHOUSE    SITE BOUNDARY")
# A location map's labels: place names and road numbers. Just as much ink, none of it furniture.
_MAP_TEXT = ("M1    A14    A45\nNORTHAMPTON    RUGBY    DAVENTRY\n"
             "Birmingham 45 miles    London 78 miles")


def _paint_background(pg, fitz, colour=(0.05, 0.22, 0.16)):
    """A full-bleed dark colour ground - the thing that makes a designed plan classify 'photo'
    and fall outside the plan white-balance band, i.e. the reason the two pre-existing routes
    cannot see a real masterplan at all."""
    pg.draw_rect(pg.rect, color=colour, fill=colour, width=0)


def _paint_vector_body(pg, fitz, seed=0):
    """~900 primitive path items spread over the page - a full-page vector DRAWING body."""
    import random
    rnd = random.Random(seed)
    w, h = pg.rect.width, pg.rect.height
    for i in range(300):
        x = 20 + (i % 30) * (w - 40) / 30.0
        y = 20 + (i // 30) * (h - 40) / 10.0
        pg.draw_rect(fitz.Rect(x, y, x + 14, y + 10), color=(1, 1, 1), width=0.6)
    for i in range(600):
        x0 = rnd.uniform(10, w - 10)
        y0 = rnd.uniform(10, h - 10)
        pg.draw_line(fitz.Point(x0, y0), fitz.Point(x0 + rnd.uniform(-40, 40),
                                                    y0 + rnd.uniform(-40, 40)),
                     color=(1, 1, 1), width=0.5)


def _build_deck(td: Path):
    """A 4-page deck:
        0  cover: colour ground, a title, almost no vector content
        1  MASTERPLAN: colour ground + full-page vector body + site-plan FURNITURE labels
        2  LOCATION MAP: same colour ground + the same vector body, place-name labels only
        3  colour ground + a title only (a divider) - never a plan by any route
    """
    import fitz
    doc = fitz.open()
    p0 = doc.new_page(width=595, height=420)
    _paint_background(p0, fitz)
    p0.insert_text((60, 200), "CAMPUS 450", fontsize=40, color=(1, 1, 1))
    p1 = doc.new_page(width=595, height=420)
    _paint_background(p1, fitz)
    _paint_vector_body(p1, fitz, seed=1)
    p1.insert_text((40, 30), _FURNITURE_TEXT.replace("\n", "    "), fontsize=8, color=(1, 1, 1))
    for i, line in enumerate(_FURNITURE_TEXT.split("\n")):
        p1.insert_text((40, 380 + i * 9), line, fontsize=7, color=(1, 1, 1))
    p2 = doc.new_page(width=595, height=420)
    _paint_background(p2, fitz)
    _paint_vector_body(p2, fitz, seed=2)
    for i, line in enumerate(_MAP_TEXT.split("\n")):
        p2.insert_text((40, 380 + i * 9), line, fontsize=7, color=(1, 1, 1))
    p3 = doc.new_page(width=595, height=420)
    _paint_background(p3, fitz)
    p3.insert_text((60, 200), "GET IN TOUCH", fontsize=30, color=(1, 1, 1))
    f = td / "Vector Deck.pdf"
    doc.save(str(f))
    doc.close()
    return f


# --------------------------------------------------------------------------------------- #
# A - vector site-plan detection
# --------------------------------------------------------------------------------------- #
def part_a(td: Path) -> None:
    import images as IMG
    import plan_signal as PS
    try:
        import fitz  # noqa: F401
    except Exception as e:
        ck(False, f"A: fitz unavailable ({e})")
        return
    f = _build_deck(td)
    IMG.close_doc_cache()
    BUD = IMG.DEFAULT_BUDGET_KB

    ck(PS.plan_furniture_score(_FURNITURE_TEXT) >= IMG.PLAN_FURNITURE_SPEC_MIN,
       "A: a masterplan's own labels score site-plan FURNITURE")
    ck(PS.plan_furniture_score(_MAP_TEXT) == 0,
       "A: a location map's place names and road numbers score ZERO furniture")
    ck(PS.plan_furniture_score("") == 0 and PS.plan_furniture_score(None) == 0,
       "A: empty text scores 0 furniture (additive-only, never a rescue on its own)")

    vec_plan = IMG.page_vector_art(f, 1, td / "vc")
    vec_map = IMG.page_vector_art(f, 2, td / "vc")
    vec_cover = IMG.page_vector_art(f, 0, td / "vc")
    ck(IMG._vector_body(vec_plan), f"A: the masterplan page has a full-page VECTOR BODY {vec_plan}")
    ck(IMG._vector_body(vec_map), f"A: the location map is JUST as vector-dense {vec_map}")
    ck(not IMG._vector_body(vec_cover),
       f"A: a cover with a colour ground and a title is NOT a vector body {vec_cover}")
    ck(IMG.page_vector_art(f, 99, td / "vc") == {},
       "A: an out-of-range page yields {} (honest silence, never a crash)")

    # THE HEADLINE: a vector masterplan binds with NO LLM nomination, over the whole deck.
    nm: list = []
    uri, pno = IMG.best_plan_page_render(f, [0, 1, 2, 3], BUD, cache_dir=td / "p1", near_miss=nm)
    ck(isinstance(uri, str) and uri.startswith("data:image/") and pno == 1,
       f"A: the VECTOR masterplan binds the plan slot with NO LLM nomination (page={pno})")

    # ...and the location map alone does NOT, even though it is equally vector-dense.
    nm2: list = []
    uri2, pno2 = IMG.best_plan_page_render(f, [2], BUD, cache_dir=td / "p2", near_miss=nm2)
    ck(uri2 is None and pno2 is None,
       f"A: an equally vector-dense LOCATION MAP does NOT bind (page={pno2})")
    ck(any("no site-plan labels" in (e.get("why") or "") for e in nm2),
       "A: the unlabelled vector page is DISCLOSED as a near-miss, not silently dropped")

    # The cover and the divider never bind.
    for pg in (0, 3):
        u, _p = IMG.best_plan_page_render(f, [pg], BUD, cache_dir=td / f"p{pg}x")
        ck(u is None, f"A: page {pg} (cover/divider, no vector body) does not bind")

    # RANKING: furniture outranks balance, which is the live wrong-bind this fixed (a regional
    # drive-time map out-balanced the real masterplan and would have won the slot).
    E = IMG._plan_page_eligible
    ok_map, _ = E("plan", {"white": 0.57}, False, 0.0, False, False)
    ok_plan, _ = E("plan", {"white": 0.37}, False, 0.0, False, False)
    ck(ok_map and ok_plan, "A: both a light map page and a masterplan can be ELIGIBLE (kind=plan)")
    # The measured live wrong-bind: a regional DRIVE-TIME MAP classified 'plan' with the best
    # balance on the deck (0.980) while the real unit site plan classified 'map' (0.774) and
    # carried 15 furniture labels. Ranked classifier-first the map won the Site Plan slot.
    rank_map = IMG._plan_rank("plan", False, False, 4.0 * 0.57 * 0.43)
    rank_plan = IMG._plan_rank("map", True, False, 4.0 * 0.26 * 0.74)
    ck(rank_plan > rank_map,
       "A: the FURNITURE-corroborated site plan outranks a better-balanced page the pixel "
       "classifier called 'plan' (the live drive-time-map wrong-bind)")
    ck(IMG._plan_rank("plan", True, False, 0.5) > IMG._plan_rank("map", True, False, 0.9),
       "A: with furniture equal, the classifier verdict still decides")
    ck(IMG._plan_rank("plan", True, True, 0.5) > IMG._plan_rank("plan", True, False, 0.9),
       "A: with furniture and kind equal, a plan TITLE still decides")

    # The vector route can never fire without the engine, and never on text alone.
    ck(not E("photo", {"white": 0.03}, False, 0.0, False, False, vector={}, furniture=9)[0],
       "A: no vector body -> the furniture count is ignored entirely (no text-only rescue)")
    ck(not E("photo", {"white": 0.03}, False, 0.0, False, False,
             vector={"items": 5000, "cells": 0.9, "span": 0.9}, furniture=0)[0],
       "A: a vector body with NO furniture never binds (a location map is vector-dense too)")
    ck(E("photo", {"white": 0.03}, True, 0.0, False, False,
         vector={"items": 5000, "cells": 0.9, "span": 0.9}, furniture=9)[0] is True,
       "A: a photo-dominated page CAN still bind via the vector route (a plan drawn over an "
       "aerial) - the route is corroborated, not blind")
    IMG.close_doc_cache()
    return f


# --------------------------------------------------------------------------------------- #
# B - capabilities + deck facts
# --------------------------------------------------------------------------------------- #
def part_b(deck: Path) -> None:
    import images as IMG
    caps = IMG.media_capabilities()
    ck(isinstance(caps, dict) and set(IMG.MEDIA_CRITICAL_CAPS) <= set(caps),
       "B: media_capabilities() reports every media-critical capability")
    ck(all(isinstance(caps[c], bool) for c in IMG.MEDIA_CRITICAL_CAPS),
       "B: every capability is a hard True/False, never a version guess")
    ck(caps is not IMG.media_capabilities() or True, "B: memoised (returns a copy)")
    c2 = IMG.media_capabilities()
    c2["pillow"] = "tampered"
    ck(IMG.media_capabilities().get("pillow") != "tampered",
       "B: the caller gets a COPY - a mutated result cannot poison the probe")
    facts = IMG.deck_media_facts(deck)
    ck(facts.get("pages") == 4, f"B: deck_media_facts counts pages ({facts})")
    ck(IMG.deck_media_facts(deck.parent / "nope.pdf") == {},
       "B: a missing deck yields {} (honest absence, never a crash)")


# --------------------------------------------------------------------------------------- #
# C - the media-harvest gate
# --------------------------------------------------------------------------------------- #
def _run_gate(work: Path, canonical: Path):
    r = subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"), "media-harvest",
                        str(canonical), "--work", str(work)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def part_c(td: Path, deck: Path) -> None:
    work = td / "work"
    (work / "vision").mkdir(parents=True, exist_ok=True)
    canonical = work / "canonical.json"
    canonical.write_text(json.dumps({
        "meta": {"client": "T"},
        "properties": [
            {"id": 1, "park": "Under Harvested", "city": "Corby",
             "photo": "data:image/jpeg;base64,AAAA", "gallery": ["data:image/jpeg;base64,AAAA"]},
        ]}), encoding="utf-8")
    (work / "inventory.json").write_text(json.dumps({"folder": str(deck.parent)}), encoding="utf-8")
    (work / "media_considered.json").write_text(json.dumps({
        "schema_version": 1,
        "properties": [{"id": 1, "property": "Under Harvested",
                        "decks": {deck.name: {"path": str(deck), "claimed": [0], "looked": [0],
                                              "foreign": [], "plan_offlimits": [],
                                              "plan_rejected": [], "exclude_refs": {}}},
                        "hero": {"bound": True, "placeholder": False, "from": None},
                        "plan": {"bound": False, "from": None},
                        "gallery": 1, "near_miss": []}],
        "unassigned": [{"file": deck.name, "path": str(deck), "pages": [1, 2, 3],
                        "deck_pages": 4, "large_images": 0}]}), encoding="utf-8")
    (work / "vision" / "visual_aids.json").write_text(json.dumps({
        deck.name: {"pages": 4, "renders": 0, "candidates": 0, "sheets": 0, "mode": "text"}}),
        encoding="utf-8")

    rc, out = _run_gate(work, canonical)
    # THE BLIND-AGENT SIGNAL NOW BLOCKS. It is a hard fact - that agent provably received zero
    # renders - and a null `plan_page` from it is indistinguishable from "this deck has no site
    # plan", which is exactly how this failure class reached a broker in silence.
    ck(rc == 1 and "STATUS: BLOCKED" in out,
       "C: a text deck interpreted with ZERO page renders BLOCKS (hard fact, not a heuristic)")
    ck("BLIND" in out and deck.name in out,
       "C: a text deck that reached its agent with ZERO renders raises the blind-agent signal")
    ck("blind_interpretation_ok" in out and "gate_runner.py ack" in out,
       "C: the block NAMES its remedy - the exact ack command (house rule)")
    ck("[SIGNAL]" in out and "looked at page 1 ONLY" in out,
       "C: a property that read ONE page of a 4-page deck raises the under-harvest SIGNAL")
    ck("NO site plan" in out, "C: the missing site plan is named in that signal")
    ck("NO property claimed" in out,
       "C: deck pages no property claimed raise the orphan-pages SIGNAL")

    # ...and the recorded sign-off clears it, WITHOUT silencing the advisory signals.
    r_ack = subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"), "ack",
                            "--work", str(work),
                            "--add", f"blind_interpretation_ok={deck.name}"],
                           capture_output=True, text=True)
    ck(r_ack.returncode == 0, "C: `gate_runner.py ack` records the blind-interpretation sign-off")
    rc_a, out_a = _run_gate(work, canonical)
    ck(rc_a == 0 and "STATUS: ALL-PASS" in out_a,
       "C: the recorded ack clears the block - a deliberate decision, never silence")
    ck("looked at page 1 ONLY" in out_a and "NO property claimed" in out_a,
       "C: the ack clears the BLOCK only - the advisory signals still print")

    # THE CAPABILITY PROBE, the other hard fact. Forced in-process (this host has every
    # capability, which is the point - the block must be reachable on a healthy host too).
    import argparse as _ap
    import contextlib as _cl
    import io as _sio
    import images as _IMG
    import gate_runner as _GR
    _real = _IMG.media_capabilities
    try:
        _IMG.media_capabilities = lambda: {**_real(), "renderer": False,
                                           "engine": "test", "geometry_backend": "test"}
        buf = _sio.StringIO()
        ns = _ap.Namespace(canonical=str(canonical), work=str(work), max_notes=25)
        with _cl.redirect_stdout(buf):
            rc_c = _GR.cmd_media_harvest(ns)
        cap_out = buf.getvalue()
        ck(rc_c == 1 and "STATUS: BLOCKED" in cap_out,
           "C: a media CAPABILITY the probe says is unavailable BLOCKS")
        ck("media_capability_ok=renderer" in cap_out,
           "C: the capability block names the exact ack key and value")
        # signed off -> proceeds, and the finding is still recorded on disk for the auditor
        _GR.cmd_ack(_ap.Namespace(work=str(work), add=["media_capability_ok=renderer"],
                                  note=None, verified_by=None))
        buf2 = _sio.StringIO()
        with _cl.redirect_stdout(buf2):
            rc_d = _GR.cmd_media_harvest(ns)
        ck(rc_d == 0 and "STATUS: ALL-PASS" in buf2.getvalue(),
           "C: media_capability_ok clears the capability block")
        mhc = json.loads((work / "media_harvest.json").read_text(encoding="utf-8"))
        ck(any(f.get("kind") == "capability" and f.get("acked") for f in mhc["findings"]),
           "C: an acked capability is still RECORDED on disk, flagged as signed off")
    finally:
        _IMG.media_capabilities = _real
    mh = json.loads((work / "media_harvest.json").read_text(encoding="utf-8"))
    ck(len(mh.get("findings") or []) >= 3 and "capabilities" in mh,
       "C: the full ranked list + the capability probe always land on disk")
    ck(all(f.get("text") for f in mh["findings"]),
       "C: every finding carries a readable sentence, not just a code")

    # A well-harvested property raises nothing.
    canonical2 = work / "canonical2.json"
    canonical2.write_text(json.dumps({
        "meta": {}, "properties": [
            {"id": 1, "park": "Fully Harvested", "city": "Corby",
             "photo": "data:image/jpeg;base64,AAAA",
             "plan": "data:image/jpeg;base64,BBBB",
             "gallery": ["data:image/jpeg;base64,AAAA"] * 6}]}), encoding="utf-8")
    (work / "media_considered.json").write_text(json.dumps({
        "schema_version": 1,
        "properties": [{"id": 1, "property": "Fully Harvested",
                        "decks": {deck.name: {"path": str(deck), "claimed": [0, 1, 2, 3],
                                              "looked": [0, 1, 2, 3], "foreign": [],
                                              "plan_offlimits": [], "plan_rejected": [],
                                              "exclude_refs": {}}},
                        "hero": {"bound": True, "placeholder": False, "from": None},
                        "plan": {"bound": True, "from": None},
                        "gallery": 6, "near_miss": []}],
        "unassigned": []}), encoding="utf-8")
    (work / "vision" / "visual_aids.json").write_text(json.dumps({
        deck.name: {"pages": 4, "renders": 4, "candidates": 9, "sheets": 2, "mode": "text"}}),
        encoding="utf-8")
    rc2, out2 = _run_gate(work, canonical2)
    ck(rc2 == 0 and "[SIGNAL]" not in out2,
       "C: a fully-harvested property with a plan and a full gallery raises NOTHING (no crying wolf)")


# --------------------------------------------------------------------------------------- #
# D - the considered set: pure recording + a derived projection
# --------------------------------------------------------------------------------------- #
def part_d(td: Path, deck: Path) -> None:
    import images as IMG
    import merge as M
    import project_properties as PP

    rec = {"park": "Vector Park", "city": "Crick",
           "__meta": {"source_file": deck.name, "source_type": "pdf", "page_no": 1,
                      "image_pages": [1, 2]}}
    BUD = 60
    a = M.attach_media([json.loads(json.dumps(rec))], deck.parent, BUD, image_cache=td / "mc")
    cons: dict = {}
    b = M.attach_media([json.loads(json.dumps(rec))], deck.parent, BUD, image_cache=td / "mc",
                       considered=cons)
    ck(a[0] == b[0] and a[1] == b[1] and a[5] == b[5],
       "D: attach_media(considered=...) is PURE - hero, plan and gallery are byte-identical")
    ck(cons.get("decks", {}).get(deck.name, {}).get("looked") == [1, 2],
       f"D: the considered set records the pages this property actually looked at ({cons.get('decks')})")
    ck("hero" in cons and "plan" in cons and "gallery" in cons and "near_miss" in cons,
       "D: it records the chosen hero/plan provenance, the gallery size and the near-miss list")

    # --- the projection is DERIVED: canonical bytes must not move ---
    work = td / "projwork"
    work.mkdir(parents=True, exist_ok=True)
    canonical = work / "canonical.json"
    canonical.write_text(json.dumps({
        "meta": {}, "properties": [{"id": 1, "park": "Vector Park", "city": "Crick",
                                    "photo": b[0], "plan": b[1], "gallery": b[5]}]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    before = canonical.read_bytes()
    cons_out = dict(cons)
    cons_out["id"] = 1
    cons_out["property"] = "Vector Park"
    (work / "media_considered.json").write_text(json.dumps({
        "schema_version": 1, "properties": [cons_out],
        "unassigned": [{"file": deck.name, "path": str(deck), "pages": [0, 3], "deck_pages": 4}]},
        ensure_ascii=False), encoding="utf-8")

    res = PP.build(work, source_dir=deck.parent, image_cache=td / "mc")
    ck(canonical.read_bytes() == before,
       "D: the projection NEVER alters canonical.json (read-only/derived, pinned)")
    pdir = next(iter(sorted((work / "properties").glob("01-*"))))
    cdir = pdir / "media" / "considered"
    names = sorted(p.name for p in cdir.glob("*")) if cdir.exists() else []
    ck(any(n.startswith("p1-render") for n in names),
       f"D: media/considered/ holds a numbered page render per considered page ({names[:6]})")
    ck((pdir / "media_decisions.json").exists(), "D: media_decisions.json is written beside it")
    dec = json.loads((pdir / "media_decisions.json").read_text(encoding="utf-8"))
    ck(dec["decks"][deck.name]["looked_at"] == [1, 2],
       "D: the decisions file states which pages were looked at")
    ck("chosen" in dec and "rejected_plan_pages" in dec,
       "D: chosen vs rejected are both stated")
    ua = work / "properties" / "_unassigned"
    ck(ua.exists() and (ua / "index.json").exists() and (ua / "README.md").exists(),
       "D: properties/_unassigned/ is produced ONCE per run for pages nobody claimed")
    ck(res.get("unassigned") == 2, f"D: the unclaimed page count is reported ({res})")
    ck(any(p.name.startswith("p0-render") for p in ua.rglob("*")),
       "D: the unclaimed pages are rendered to openable files too")

    # rebuild is idempotent and still derived
    before2 = canonical.read_bytes()
    PP.build(work, source_dir=deck.parent, image_cache=td / "mc")
    ck(canonical.read_bytes() == before2, "D: a second projection is still byte-neutral")

    # no sidecar -> exactly the pre-feature behaviour
    work2 = td / "projwork2"
    work2.mkdir(parents=True, exist_ok=True)
    (work2 / "canonical.json").write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")
    r2 = PP.build(work2, source_dir=deck.parent)
    p2 = next(iter(sorted((work2 / "properties").glob("01-*"))))
    ck(not (p2 / "media" / "considered").exists() and not (p2 / "media_decisions.json").exists(),
       "D: with no media_considered.json the projection is EXACTLY what it was before")
    ck(r2.get("unassigned") == 0 and not (work2 / "properties" / "_unassigned").exists(),
       "D: ...and no _unassigned/ folder is invented")
    IMG.close_doc_cache()


# --------------------------------------------------------------------------------------- #
# E - PLAN-SLOT REACH over the pages nobody claimed
# --------------------------------------------------------------------------------------- #
def _two_property_deck(td: Path):
    """A 6-page deck for TWO properties - the shape that makes ownership hard:
        0  UNIT A anchor (its own page)
        1  UNIT A masterplan spread - vector body, furniture, and A's OWN schedule figures
        2  UNIT B anchor
        3  UNIT B masterplan spread - vector body, furniture, and B's OWN schedule figures
        4  a park OVERVIEW printing BOTH units' figures (it must reach neither)
        5  a divider printing no figures at all (it must reach neither)
    """
    import fitz
    doc = fitz.open()

    def _sched(pg, wh, sqm):
        for i, line in enumerate((f"Warehouse {wh:,} sq ft   {sqm:,} sq m",
                                  "42 dock doors    4 level access doors",
                                  "55 m yard depth    120 car parking spaces",
                                  "GATEHOUSE    SITE BOUNDARY")):
            pg.insert_text((40, 380 + i * 9), line, fontsize=7, color=(1, 1, 1))

    # p6 ("THIRD") is APPENDED so pages 0-5 keep their indices for every existing assertion.
    # It is the case the park-level relaxation must still refuse: a page naming neither
    # claimant, but printing a unit-scale figure that is NEITHER of theirs - somebody else's
    # building.
    specs = [("A", None), ("A", (425621, 39541)), ("B", None), ("B", (326684, 30350)),
             ("BOTH", None), ("NONE", None), ("THIRD", None)]
    for n, (tag, sched) in enumerate(specs):
        pg = doc.new_page(width=595, height=420)
        _paint_background(pg, fitz)
        if sched:
            _paint_vector_body(pg, fitz, seed=n)
            _sched(pg, *sched)
        elif tag == "BOTH":
            pg.insert_text((40, 200), "Two units of 425,621 sq ft and 326,684 sq ft",
                           fontsize=12, color=(1, 1, 1))
        elif tag == "NONE":
            pg.insert_text((40, 200), "GET IN TOUCH", fontsize=20, color=(1, 1, 1))
        elif tag == "THIRD":
            pg.insert_text((40, 200), "Also available: 210,000 sq ft", fontsize=12,
                           color=(1, 1, 1))
        else:
            pg.insert_text((40, 200), f"UNIT {tag}", fontsize=30, color=(1, 1, 1))
    f = td / "Two Unit Deck.pdf"
    doc.save(str(f))
    doc.close()
    return f


def part_e(td: Path, single_deck: Path) -> None:
    import images as IMG
    import merge as M
    f = _two_property_deck(td)
    IMG.close_doc_cache()

    def rec(src, page, **fields):
        r = {"__meta": {"source_file": Path(src).name, "source_type": "pdf", "page_no": page}}
        r.update(fields)
        return r

    clA = [rec(f, 0, park="Unit A", warehouseArea=425621, warehouseAreaSqM="39,541 sq m")]
    clB = [rec(f, 2, park="Unit B", warehouseArea=326684, warehouseAreaSqM="30,350 sq m")]
    reach = M.plan_reach_pages([clA, clB], f.parent)
    rA = sorted(reach[0].get(str(f), set()))
    rB = sorted(reach[1].get(str(f), set()))
    ck(rA == [1], f"E: multi-claimant deck - unit A reaches ONLY the page printing A's schedule ({rA})")
    ck(rB == [3], f"E: multi-claimant deck - unit B reaches ONLY its own ({rB})")
    ck(4 not in rA and 4 not in rB,
       "E: a park OVERVIEW printing BOTH units' figures reaches NEITHER (the page does not say)")
    ck(5 not in rA and 5 not in rB, "E: a page printing no figures at all reaches NEITHER")
    ck(2 not in rA and 0 not in rB,
       "E: the reach NEVER includes a page another property anchors")

    # A PARK DECK CARRIES A MASTERPLAN PER UNIT. Handed BOTH spreads, the ranking must pick the
    # one printing THIS property's own schedule figures - the other is a NEIGHBOURING UNIT's
    # plan, a wrong bind in a trace-less slot. (Measured live: the wrong unit's masterplan was
    # winning on a plan title.)
    figsA = {425621, 39541}
    figsB = {326684, 30350}
    _, pA = IMG.best_plan_page_render(f, [1, 3], 60, cache_dir=td / "eR", own_figures=figsA)
    _, pB = IMG.best_plan_page_render(f, [1, 3], 60, cache_dir=td / "eR", own_figures=figsB)
    ck(pA == 1 and pB == 3,
       f"E: with two unit masterplans on one deck, each property binds ITS OWN (A={pA}, B={pB})")
    ck(pA != pB, "E: the two units never bind the identical image (the duplicate-bind failure)")
    ck(IMG._plan_rank("map", False, False, 0.1, True) > IMG._plan_rank("plan", True, True, 0.9),
       "E: the property's OWN figures outrank every other plan signal")
    ck(IMG._plan_rank("plan", True, True, 0.9) == IMG._plan_rank("plan", True, True, 0.9, False),
       "E: with no figures known the component is inert - today's ranking exactly")

    # SOLE claimant with NO figures known: no other property can own any page of that deck and
    # nothing better is available, so every page nobody claimed is in reach.
    clS = [rec(single_deck, 0, park="Solo")]
    rS = sorted(M.plan_reach_pages([clS], single_deck.parent)[0].get(str(single_deck), set()))
    ck(rS == [1, 2, 3], f"E: sole-claimant deck, no figures - every unclaimed page is in reach ({rS})")

    # SOLE claimant WITH figures: only the pages that print them - its own spread.
    clF = [rec(f, 0, park="Unit A", warehouseArea=425621, warehouseAreaSqM="39,541 sq m")]
    rF = sorted(M.plan_reach_pages([clF], f.parent)[0].get(str(f), set()))
    ck(rF == [1, 4], f"E: sole claimant WITH figures - only pages printing them are in reach ({rF})")

    # ...and a DONOR deck that states this property's figures NOWHERE reaches NOTHING. (Measured:
    # a whole-park brochure covering seven other schemes put a NEIGHBOURING scheme's masterplan
    # on the card, because every page was 'unclaimed' and none of them was this unit's.)
    clD = [rec(f, 0, park="Absent Unit", warehouseArea=999111, warehouseAreaSqM="92,821 sq m")]
    rD = sorted(M.plan_reach_pages([clD], f.parent)[0].get(str(f), set()))
    ck(rD == [], f"E: a DONOR deck that never states this property's size reaches NOTHING ({rD})")

    # ...and that reach BINDS the vector masterplan a one-page claim could never see.
    BUD = 60
    _p_no = M.attach_media([json.loads(json.dumps(clS[0]))], single_deck.parent, BUD,
                           image_cache=td / "e1")[1]
    _p_yes = M.attach_media([json.loads(json.dumps(clS[0]))], single_deck.parent, BUD,
                            image_cache=td / "e1",
                            plan_reach={str(single_deck): {1, 2, 3}})[1]
    ck(_p_no is None and isinstance(_p_yes, str),
       "E: the plan-slot reach BINDS a masterplan a one-page claim could never see")

    # PLAN SLOT ONLY: the hero and the carousel must be byte-identical with and without it.
    a = M.attach_media([json.loads(json.dumps(clS[0]))], single_deck.parent, BUD,
                       image_cache=td / "e2")
    b = M.attach_media([json.loads(json.dumps(clS[0]))], single_deck.parent, BUD,
                       image_cache=td / "e2", plan_reach={str(single_deck): {1, 2, 3}})
    ck(a[0] == b[0] and a[5] == b[5],
       "E: the reach touches the PLAN SLOT only - hero and gallery are unchanged")

    # every precision guard still applies to the wider set
    rej = M.attach_media([json.loads(json.dumps(clS[0]))], single_deck.parent, BUD,
                         image_cache=td / "e3",
                         plan_reach={str(single_deck): {1, 2, 3}},
                         plan_rejected={f"{single_deck.name.lower()}#2"})[1]
    ck(rej is None, "E: a visual-QA REJECTED page is still refused through the wider reach")
    off = M.attach_media([json.loads(json.dumps(clS[0]))], single_deck.parent, BUD,
                         image_cache=td / "e4",
                         plan_reach={str(single_deck): {1, 2, 3}},
                         plan_offlimits={str(single_deck): {1, 2, 3}})[1]
    ck(off is None, "E: a page another property owns is still refused through the wider reach")
    IMG.close_doc_cache()


# --------------------------------------------------------------------------------------- #
# F - interpret_prep: the resume guard is no longer VACUOUS
# --------------------------------------------------------------------------------------- #
def part_f(td: Path, deck: Path) -> None:
    import interpret_prep as IP
    out = td / "prep"
    ent = IP.prepare(deck, "R", "GB", out, resume=False)
    aids = ent.get("visual_aids") or {}
    ck(ent.get("mode") == "text", "F: the fixture deck routes to the cheap TEXT path")
    ck(aids.get("renders") == aids.get("pages") and aids.get("pages") == 4,
       f"F: every page reaches the agent with a render ({aids})")
    # This fixture deck is PURE VECTOR - it holds no embedded raster at all - so the honest
    # admission is "no candidate thumbnail", and NOT "no page render". That distinction is the
    # whole point of the key: it separates a source that has nothing from a host that saw nothing.
    _deg = " ".join(ent.get("aids_degraded") or [])
    ck("RENDER" not in _deg, f"F: a deck that renders fine is NOT flagged blind ({_deg[:60]})")
    ck("candidate image thumbnail" in _deg,
       "F: a deck with no embedded raster SAYS so on the entry (an honest admission)")
    ck(IP._entry_aids_intact(ent, deck), "F: a healthy entry is reused on resume")

    # THE POISONED ENTRY: pages listed, nothing to look at. It passed the old guard VACUOUSLY
    # (every one of zero files exists), so it was served for ever and the agents read blind.
    poisoned = {"mode": "text", "pages": [{"page_no": i, "render": None, "candidates": [],
                                           "candidates_sheet": None} for i in range(4)]}
    ck(not IP._entry_aids_intact(poisoned, deck),
       "F: a zero-aid entry is REJECTED while the host can render (the vacuous-pass fix)")
    ck(IP._entry_aids_intact(poisoned, td / "does-not-exist.pdf"),
       "F: ...but accepted when nothing here CAN render - an honest, re-attempted absence")
    key = json.loads((out / f"{deck.stem}.interpret.stamp.json").read_text(encoding="utf-8"))["key"]
    ck(IP.PREP_SCHEMA >= 3 and key.get("schema") == IP.PREP_SCHEMA,
       "F: the stamp key carries PREP_SCHEMA, so a bytes-identical deck re-preps on a bump")

    degraded = dict(ent)
    degraded["pages"] = [dict(p, render=None, candidates=[], candidates_sheet=None)
                         for p in ent["pages"]]
    va = IP._visual_aids(degraded)
    ck(va["renders"] == 0 and va["candidates"] == 0 and va["pages"] == 4,
       "F: _visual_aids counts what actually reaches the agent")


# --------------------------------------------------------------------------------------- #
# G - the CAROUSEL: breadth, the decorative floor, the resolution floor
# --------------------------------------------------------------------------------------- #
# Three defects that shipped together on a live 17-property run, all in the gallery path:
#   (a) BREADTH - the carousel's page scope was the record's page_no U __meta.image_pages, and
#       the reader returned image_pages for 4 of 17 properties. The other 13 could see ONE page
#       of a 5-16 page brochure: a deck whose pages 1-2 hold 26 card-quality photographs shipped
#       a ONE-image card, and a deck with a 1173x729 photograph on page 1 shipped four 323x215
#       thumbnails off page 3 because pages 0 and 1 were never CONSIDERED.
#   (b) NO QUALITY FLOOR - a flat decorative background graphic shipped as a photo. It cleared
#       the only test there was (`kind != 'photo' and score < MODEST_PHOTO`), and smooth gradient
#       art classifies as 'photo' anyway.
#   (c) NO RESOLUTION FLOOR - the carousel used the HERO floor (320x200), so 323x215 thumbnails
#       shipped on a client-facing card.
# The fixture reproduces all three in one deck, and the assertions pin each floor to the ONE
# signal that catches it (each rejected image clears every OTHER admission test, so a floor
# silently going missing fails here rather than passing for the wrong reason).
def _tex_photo(seed: int, w: int, h: int):
    """A TEXTURED gradient - a real photograph's signature: continuous tone (classify_image
    'photo') AND fine detail everywhere (detail_score well over MIN_GALLERY_DETAIL)."""
    import random
    from PIL import Image
    g = random.Random(seed)
    im = Image.new("RGB", (w, h))
    im.putdata([(((x * 255) // w + g.randrange(96)) % 256,
                 ((y * 255) // h + g.randrange(96)) % 256,
                 (((x + y) * 127) // (w + h) + g.randrange(96)) % 256)
                for y in range(h) for x in range(w)])
    return im


def _flat_decor(w: int, h: int):
    """A SMOOTH gradient - marketing decoration. Continuous tone, highly colourful (so it
    scores far above MODEST_PHOTO and classify_image calls it 'photo'), and no detail at all."""
    from PIL import Image
    im = Image.new("RGB", (w, h))
    im.putdata([((x * 200) // w + 40, (y * 180) // h + 60, 200 - ((x + y) * 90) // (w + h))
                for y in range(h) for x in range(w)])
    return im


def _jpeg(im) -> bytes:
    import io as _io
    b = _io.BytesIO()
    im.save(b, format="JPEG", quality=85)
    return b.getvalue()


def _carousel_deck(td: Path):
    """A 4-page single-property brochure for 'Unit G, 250,000 sq ft':
      p0  the ANCHOR page the reader returned - a 323x215 thumbnail + a decorative graphic
      p1  unclaimed, prints THIS unit's figure - a card-quality photo
      p2  unclaimed, prints NO figure at all      - a card-quality photo
      p3  unclaimed, prints ANOTHER unit's figure - a card-quality photo that must NOT be reached
    """
    try:
        import fitz
    except Exception:
        return None
    doc = fitz.open()
    spec = [("UNIT G    250,000 sq ft    AVAILABLE NOW",
             [(_tex_photo(1, 323, 215), fitz.Rect(40, 90, 240, 220)),
              (_flat_decor(1000, 650), fitz.Rect(260, 90, 560, 290))]),
            ("250,000 sq ft    Indicative computer-generated image",
             [(_tex_photo(2, 900, 600), fitz.Rect(40, 90, 540, 420))]),
            ("DESIGNED TO PERFORM",
             [(_tex_photo(3, 880, 580), fitz.Rect(40, 90, 540, 420))]),
            ("UNIT H    410,000 sq ft    LET",
             [(_tex_photo(4, 820, 540), fitz.Rect(40, 90, 540, 420))])]
    for text, imgs in spec:
        pg = doc.new_page(width=595, height=460)
        pg.insert_text((40, 60), text, fontsize=12)
        for im, rect in imgs:
            pg.insert_image(rect, stream=_jpeg(im))
    f = td / "Unit G Carousel Deck.pdf"
    doc.save(str(f))
    doc.close()
    return f


def part_g(td: Path) -> None:
    import images as IMG
    import merge as M
    f = _carousel_deck(td)
    if f is None:
        ck(False, "G: setup failed (no fitz)")
        return
    IMG.close_doc_cache()
    BUD = 60

    # --- the three floors, each pinned to the ONE signal that catches it ------------------ #
    from PIL import Image as _I
    import io as _io
    def _rt(im):                       # round-trip through JPEG, as the harvest sees it
        return _I.open(_io.BytesIO(_jpeg(im)))
    thumb, decor, good = _rt(_tex_photo(1, 323, 215)), _rt(_flat_decor(1000, 650)), _rt(_tex_photo(2, 900, 600))
    ck(IMG.classify_image(decor) == "photo" and IMG.photographic_score(decor) >= IMG.MODEST_PHOTO,
       "G-b: the decorative graphic passes BOTH pre-existing tests (kind 'photo' AND >= MODEST_PHOTO)")
    ck(IMG.detail_score(decor) < IMG.MIN_GALLERY_DETAIL <= IMG.detail_score(good),
       "G-b: only detail_score separates flat decoration from a real photograph")
    ck(IMG.photographic_score(thumb) >= IMG.MODEST_PHOTO and IMG.classify_image(thumb) == "photo"
       and thumb.size[0] >= IMG.MIN_HERO_W and thumb.size[1] >= IMG.MIN_HERO_H,
       "G-c: the 323x215 thumbnail clears the HERO floor and every quality test")
    ck(thumb.size[0] < IMG.MIN_GALLERY_W or thumb.size[1] < IMG.MIN_GALLERY_H,
       "G-c: ...and is refused by the CAROUSEL's own resolution floor")
    ck(not IMG.gallery_admissible({"kind": "photo", "w": 900, "h": 600}),
       "G: an entry with no detail measurement (an older cache) is refused - fail-closed")
    ck(not IMG.gallery_admissible({"kind": "plan", "w": 900, "h": 600, "detail": 9.0}),
       "G: a plan/map never enters the PHOTO carousel (it has its own Site Plan slot)")

    def rec(page, **kw):
        r = {"park": "Unit G", "city": "Town", "warehouseArea": 250000,
             "__meta": {"source_file": f.name, "source_type": "pdf", "page_no": page}}
        r["__meta"].update(kw.pop("meta", {}))
        r.update(kw)
        return r

    cl = [rec(0)]
    reach = M.gallery_reach_pages([cl], f.parent)[0].get(str(f), set())
    ck(sorted(reach) == [1, 2],
       f"G-a: carousel reach = the unclaimed pages this deck attributes to THIS unit ({sorted(reach)})")
    ck(3 not in reach,
       "G-a: a page printing ANOTHER unit's figures is never in reach (no neighbour's photo)")
    ck(2 not in M.plan_reach_pages([cl], f.parent)[0].get(str(f), set()),
       "G-a: the figure-less page is carousel-only - the PLAN slot still refuses it")

    # (a) BREADTH: without the reach the card sees one page and ships one image; with it, real
    #     photographs from the pages it owns but never claimed.
    narrow = M.attach_media([json.loads(json.dumps(cl[0]))], f.parent, BUD, image_cache=td / "g1")
    wide = M.attach_media([json.loads(json.dumps(cl[0]))], f.parent, BUD, image_cache=td / "g1",
                          gallery_reach={str(f): set(reach)})
    ck(len(narrow[5]) == 1,
       f"G-a: anchor-page-only scope ships a ONE-image carousel ({len(narrow[5])})")
    ck(len(wide[5]) >= 2,
       f"G-a: the carousel reach ships the deck's real photographs ({len(wide[5])})")
    ck(len(wide[5]) <= IMG.GALLERY_MAX, "G: the carousel is still capped at GALLERY_MAX")

    # (b)+(c): neither the decorative graphic nor the thumbnail is anywhere in the carousel.
    def _dims(uri):
        raw = __import__("base64").b64decode(uri.split("base64,", 1)[1])
        return _I.open(_io.BytesIO(raw)).size
    dims = [_dims(u) for u in wide[5]]
    ck(all(w >= IMG.MIN_GALLERY_W and h >= IMG.MIN_GALLERY_H for w, h in dims),
       f"G-c: every shipped carousel image clears the resolution floor ({dims})")
    ck(all(IMG.uri_gallery_admissible(u) for u in wide[5]),
       "G-b: every shipped carousel image is a real photograph (no decorative graphic)")

    # (c) THE HERO IS HELD TO THE SAME FLOORS. The anchor page holds only a thumbnail and a
    #     graphic, so the deterministic hero fails them and the best carousel image replaces it.
    ck(narrow[0] != wide[0] and IMG.uri_gallery_admissible(wide[0]),
       "G-c: a sub-resolution deterministic hero is REPLACED by a card-quality photograph")
    ck(wide[5][0] == wide[0], "G: gallery[0] == hero (the invariant the images gate asserts)")

    # ...but an EXPLICIT interpretation pick is never silently repaired - it exists to be
    # verified by the blind G-images reviewer.
    pinned = M.attach_media([rec(0, meta={"heroRef": 0})], f.parent, BUD, image_cache=td / "g1",
                            gallery_reach={str(f): set(reach)})
    ck(pinned[0] != wide[0] and pinned[5][0] == pinned[0],
       "G: an LLM heroRef pick is NOT auto-replaced (the gate verifies it), and still leads")

    # ...and with nothing admissible anywhere the card keeps its honest single image.
    lone = M.attach_media([json.loads(json.dumps(cl[0]))], f.parent, BUD, image_cache=td / "g1",
                          gallery_reach={str(f): set()})
    ck(len(lone[5]) == 1 and lone[5][0] == lone[0],
       "G: no admissible candidate anywhere -> the bound hero and a 1-item carousel, never empty")

    # OWNERSHIP on a genuinely shared deck: the carousel reach obeys the same rule as the plan
    # slot - each unit reaches only the page its own schedule identifies, a page printing BOTH
    # or NEITHER reaches nobody, and a page another property anchors is never in reach.
    two = _two_property_deck(td)
    IMG.close_doc_cache()

    def rec2(page, **fields):
        r = {"__meta": {"source_file": two.name, "source_type": "pdf", "page_no": page}}
        r.update(fields)
        return r

    clA = [rec2(0, park="Unit A", warehouseArea=425621, warehouseAreaSqM="39,541 sq m")]
    clB = [rec2(2, park="Unit B", warehouseArea=326684, warehouseAreaSqM="30,350 sq m")]
    pl: list = []
    gr = M.gallery_reach_pages([clA, clB], two.parent, park_level=pl)
    gA = sorted(gr[0].get(str(two), set()))
    gB = sorted(gr[1].get(str(two), set()))
    plA = sorted(pl[0].get(str(two), set()))
    plB = sorted(pl[1].get(str(two), set()))
    # PARK-LEVEL IMAGERY ON A SHARED DECK (broker-approved). Page 5 names no claimant at all -
    # it is the park's own page, and both cards may show it. Everything that protected a
    # neighbour's building still holds: page 1 is A's spread, page 3 is B's, page 4 names BOTH
    # and reaches neither, and page 6 prints a size that is neither claimant's.
    ck(gA == [1, 5] and gB == [3, 5],
       f"G: shared deck - own spread PLUS the park-level page, and nothing else (A={gA}, B={gB})")
    ck(plA == [5] and plB == [5],
       f"G: the park-level pages are DISCLOSED separately per property (A={plA}, B={plB})")
    ck(4 not in gA + gB,
       "G: on a shared deck a page naming BOTH units reaches NEITHER carousel")
    ck(6 not in gA + gB,
       "G: a page printing a THIRD scheme's unit-scale size is still refused (no neighbour's "
       "building, which is the protection that had to survive)")
    ck(1 not in gB and 3 not in gA,
       "G: a page attributable to a SPECIFIC other unit is still that unit's alone")
    ck(2 not in gA and 0 not in gB,
       "G: a page another property anchors is never in a carousel's reach")
    ck(not any(pl[i].get(str(two), set()) & {1, 3, 4, 6} for i in (0, 1)),
       "G: nothing attributable is ever mislabelled park-level")
    # NAME-based attribution: a spread headed with one unit's name and NO schedule table used to
    # be invisible to this branch (figures only), so it fell to nobody.
    clN = [rec2(0, park="Alpha Point", warehouseArea=425621, warehouseAreaSqM="39,541 sq m")]
    clM = [rec2(2, park="Beta Point", warehouseArea=326684, warehouseAreaSqM="30,350 sq m")]
    names = M._distinct_name_tokens([clN, clM], {0, 1})
    ck(names.get(0) == {"alpha"} and names.get(1) == {"beta"},
       f"G: distinguishing name tokens are the SET DIFFERENCE - the shared word drops ({names})")
    clD = [rec2(0, park="Absent Unit", warehouseArea=999111, warehouseAreaSqM="92,821 sq m")]
    ck(M.gallery_reach_pages([clD], two.parent)[0].get(str(two), set()) == set(),
       "G: a DONOR deck that never states this property's size reaches NOTHING for the carousel "
       "- the park-level relaxation is for SHARED decks only, where every claimant is on the "
       "grid; on a donor deck 'names no claimant' means 'we cannot tell whose'")
    IMG.close_doc_cache()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    with tempfile.TemporaryDirectory() as _td:
        td = Path(_td)
        print("A - vector site-plan detection")
        deck = part_a(td)
        if deck is None:
            print("\nMEDIA HARVEST TEST: FAIL (no fitz)")
            return 1
        print("B - capabilities + deck facts")
        part_b(deck)
        print("C - the media-harvest gate")
        part_c(td, deck)
        print("D - the considered set")
        part_d(td, deck)
        print("E - the plan-slot reach")
        part_e(td, deck)
        print("F - interpret_prep resume guard")
        part_f(td, deck)
        print("G - the carousel: breadth, decorative floor, resolution floor")
        part_g(td)
    if FAILS:
        print(f"\nMEDIA HARVEST TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nMEDIA HARVEST TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
