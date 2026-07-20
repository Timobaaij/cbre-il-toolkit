#!/usr/bin/env python3
"""plan_detect_test.py - site-plan DETECTION precision+recall corpus (2026-07-17).

Part A (this file, unit): the high-precision plan-title text signal (plan_signal) - a real plan TITLE
scores >=1.0; spec/amenity vocabulary and empty text do NOT; a spec page is recognised as such.
Part B (added in Task 2): synthetic fitz pages driving best_plan_page_render / page_render_plan for the
POSITIVE (vector plan; plan+hero-logo; colour-bg titled plan), NEGATIVE (photo-dominant; photo+caption;
spec; location-map; blank) and Tier-3 (hinted map/spec/photo must NOT bind) cases.
Offline. Run: python evals/plan_detect_test.py"""
from __future__ import annotations
import sys
from pathlib import Path
HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import plan_signal as PS  # noqa: E402

PLAN_TITLE_MIN = 1.0  # the threshold images._plan_page_eligible applies for the title-rescue


def main() -> int:
    try:  # the fixtures print multilingual plan titles (e.g. RO 'ț' U+021B) that a native-Windows
        sys.stdout.reconfigure(encoding="utf-8")  # cp1252 console (mcp__shell) cannot encode - force
    except Exception:                              # UTF-8 so the suite runs to completion there too,
        pass                                       # not only under a PYTHONUTF8=1 shell.
    fails = []
    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # --- plan_title_score: real TITLES (any language, any case/accent) score >= the rescue floor ---
    ck(PS.plan_title_score("SITE PLAN") >= PLAN_TITLE_MIN, "EN 'SITE PLAN' scores >= title floor")
    ck(PS.plan_title_score("Site Layout") >= PLAN_TITLE_MIN, "EN 'Site Layout' scores >= floor")
    ck(PS.plan_title_score("Masterplan") >= PLAN_TITLE_MIN, "EN 'Masterplan' scores >= floor")
    ck(PS.plan_title_score("Lageplan") >= PLAN_TITLE_MIN, "DE 'Lageplan' scores >= floor")
    ck(PS.plan_title_score("Plan de masse") >= PLAN_TITLE_MIN, "FR 'Plan de masse' scores >= floor")
    ck(PS.plan_title_score("Plano de implantación") >= PLAN_TITLE_MIN, "ES accented title scores >= floor")
    ck(PS.plan_title_score("PLANIMETRIA GENERALE") >= PLAN_TITLE_MIN, "IT uppercase title scores >= floor")
    ck(PS.plan_title_score("Situatieplan") >= PLAN_TITLE_MIN, "NL 'Situatieplan' scores >= floor")

    # --- amenity / spec vocabulary must NOT reach the title floor (it is the false-positive trap) ---
    ck(PS.plan_title_score("40 dock doors, 200 car parking spaces, 12 m clear height") < PLAN_TITLE_MIN,
       "amenity/spec words do NOT reach the title floor")
    ck(PS.plan_title_score("Warehouse availability schedule Q1") < PLAN_TITLE_MIN,
       "generic availability prose does NOT reach the floor")
    ck(PS.plan_title_score("") == 0.0 and PS.plan_title_score(None) == 0.0,
       "empty/None text scores 0 (additive-only; no rescue of a no-text page)")
    # review fixes: word boundaries (no substring), apostrophe fold, marker cap
    ck(PS.plan_title_score("our site planning application is progressing") < PLAN_TITLE_MIN,
       "word-boundary: 'site planning' does NOT match the 'site plan' title token")
    ck(PS.plan_title_score("the master planning team relocated") < PLAN_TITLE_MIN,
       "word-boundary: 'master planning' does NOT match 'master plan'")
    ck(PS.plan_title_score("Plan d’implantation du site") >= PLAN_TITLE_MIN,
       "apostrophe fold: a curly-apostrophe French title still matches the straight-apostrophe lexicon")
    ck(PS.plan_title_score("Scale 1:500    Drawing No 12    Rev A") < PLAN_TITLE_MIN,
       "marker-cap: drawing markers ALONE (no title) never reach the 1.0 rescue floor")
    ck(PS.plan_title_score("SITE PLAN    Scale 1:500") >= PLAN_TITLE_MIN + 0.4,
       "a title + a marker outscores a bare title (ranking boost)")

    # --- has_drawing_marker: a to-scale DRAWING sheet carries EITHER a CUED scale ratio (a scale-cue
    #     word 'scale'/'Maßstab'/'échelle'/... immediately before '1:N', N a SMALL denominator) OR an
    #     English drawing-sheet phrase ('drawing no'/'sheet no'/'not to scale'). A photographic aerial,
    #     a location map, a unit schedule or a connectivity map titled "Site Plan" does NOT. Two guards,
    #     both from adversarial review: MAGNITUDE (round-3) rejects a locator scale 'scale 1:25000';
    #     the CUE requirement (round-4) rejects a bare '1:N' that is really an enumeration colon
    #     ('Unit 1: 500 sq m'), a clock/drive time ('1:50') or a dilution ('1:250'). The cue list is
    #     multilingual, so the ratio path stays language-independent. ---
    ck(PS.has_drawing_marker("Scale 1:500"), "marker: cued site-plan ratio 'Scale 1:500' is a drawing marker")
    ck(PS.has_drawing_marker("Maßstab 1:500"), "marker: a cued ratio needs no ENGLISH word ('Maßstab 1:500')")
    ck(PS.has_drawing_marker("Échelle 1:500"), "marker: a cued ratio in another language ('Échelle 1:500')")
    ck(PS.has_drawing_marker("Skala 1:1250"), "marker: a cued large-site ratio 'Skala 1:1250' is a drawing marker")
    ck(PS.has_drawing_marker("Site Plan   Drawing No. 12   Rev A"), "marker: 'Drawing No' is a drawing marker")
    ck(PS.has_drawing_marker("SITE PLAN   NOT TO SCALE"), "marker: 'not to scale' is a drawing marker")
    ck(not PS.has_drawing_marker("Site Plan\nUnit 1  Unit 2  Dock  Yard"),
       "marker: a plain plan title (no scale/drawing-no) carries NO drawing marker")
    ck(not PS.has_drawing_marker("Übersichtskarte Scale 1:25000"),
       "marker: a LOCATOR scale 'Scale 1:25000' is NOT a drawing marker (magnitude bound - round-3)")
    ck(not PS.has_drawing_marker("Scale 1:50 000"),
       "marker: a cued space-thousands locator '1:50 000' is NOT a marker (parsed 50000, not 50)")
    ck(not PS.has_drawing_marker("Standortplan Scale 1:25,000"),
       "marker: a cued grouped-thousands locator '1:25,000' is NOT a marker (parsed 25000, not 25)")
    ck(not PS.has_drawing_marker("1:500"),
       "marker: a BARE '1:500' with no scale cue is NOT a drawing marker (round-4 cue requirement)")
    ck(not PS.has_drawing_marker("Unit 1: 500 sq m   Unit 2: 750 sq m   Phase 1: 2,000 sq m"),
       "marker: a unit/phase enumeration colon ('Unit 1: 500') is NOT a scale ratio (round-4 wrong-bind fix)")
    ck(not PS.has_drawing_marker("drive time 1:50 to the port"),
       "marker: a clock/drive time '1:50' is NOT a drawing marker (round-4)")
    ck(not PS.has_drawing_marker("dilution 1:250"),
       "marker: a dilution/odds '1:250' with no scale cue is NOT a drawing marker (round-4)")
    ck(not PS.has_drawing_marker("largescale 1:500 development"),
       "marker: a cue as a SUBSTRING ('largescale') is NOT a scale cue (whole-word boundary both sides)")
    ck(not PS.has_drawing_marker("a large-scale 1:500 scheme"),
       "marker: a cue as a hyphen-COMPOUND tail ('large-scale') is NOT a scale cue")
    # round-5 false-friend fix: IT 'scala' / RO 'scara' are the scale word AND the stair/entrance
    # enumeration label; a genuine scale ratio is never followed by an AREA unit, an enumeration is.
    ck(PS.has_drawing_marker("scala 1:500"),
       "marker: a real IT scale 'scala 1:500' (no trailing area) IS a marker (recall kept)")
    ck(PS.has_drawing_marker("Scară 1:200"),
       "marker: a real RO scale 'Scară 1:200' (no trailing area) IS a marker (recall kept)")
    ck(not PS.has_drawing_marker("Scala 1: 500 mq   Scala 2: 750 mq   Scala 3: 1.200 mq"),
       "marker: an IT stair AREA schedule 'Scala 1: 500 mq' (scala=staircase) is NOT a scale (area-unit follows)")
    ck(not PS.has_drawing_marker("Scara 1: 500 mp"),
       "marker: a RO block AREA schedule 'Scara 1: 500 mp' (scara=entrance) is NOT a scale (round-5)")
    ck(not PS.has_drawing_marker("Scale 1:500 sq m"),
       "marker: even a real cue is rejected when an area unit follows the ratio ('1:500 sq m' is not a scale)")
    # round-6 structural hardening: a real drawing scale is written TIGHT ('scala 1:500'); the IT/RO
    # stair/entrance enumeration is SPACED ('Scala 1: 500 ...' = 'staircase 1:' then a value). Requiring
    # a tight ratio closes the whole spaced-enumeration class (count nouns, bare numbers, unlisted
    # units), not just the area-unit denylist.
    ck(not PS.has_drawing_marker("Scala 1: 500 posti auto   Scala 2: 480 posti"),
       "marker: an IT stair COUNT schedule 'Scala 1: 500 posti' (spaced) is NOT a scale (tight-ratio rule)")
    ck(not PS.has_drawing_marker("Scara 1: 500 locuri"),
       "marker: a RO COUNT schedule 'Scara 1: 500 locuri' (spaced) is NOT a scale")
    ck(not PS.has_drawing_marker("Scala 1: 500"),
       "marker: a bare spaced 'Scala 1: 500' (staircase index) is NOT a scale (a real IT scale is tight)")
    ck(PS.has_drawing_marker("Scale: 1:1250"),
       "marker: a cue-colon then a TIGHT ratio 'Scale: 1:1250' still fires (the cue separator is not the ratio colon)")
    ck(not PS.has_drawing_marker("mix ratio 1:5 by volume"),
       "marker: a non-scale small ratio '1:5' is NOT a drawing marker (below the plan-scale floor)")
    ck(not PS.has_drawing_marker("") and not PS.has_drawing_marker(None),
       "marker: empty/None text has no drawing marker")

    # --- lexicon curation (2nd-review fix #2): clearly-LOCATION / overview titles and low-precision
    #     floor-plan / false-friend titles are EXCLUDED from the rescue vocabulary; genuine to-scale
    #     LAYOUT titles stay. A location map titled with its own correct name must not read as a site
    #     plan even before the marker gate. ---
    for loc in ("Standortplan", "Übersichtsplan", "Plan de situation", "Plano de situación",
                "Plan de încadrare", "Situatietekening", "Estate plan", "Plattegrond",
                "Planimetria", "Plan du site"):
        ck(PS.plan_title_score(loc) < PLAN_TITLE_MIN,
           f"lexicon: location/low-precision title {loc!r} is NOT a rescue title")
    for lay in ("Site plan", "Site layout", "Masterplan", "Lageplan", "Plan de masse",
                "Plan d'implantation", "Plano de emplazamiento", "Plan sytuacyjny",
                "Planimetria generale", "Planta de implantação", "Plan de situație"):
        ck(PS.plan_title_score(lay) >= PLAN_TITLE_MIN,
           f"lexicon: genuine layout title {lay!r} still scores >= floor")

    # --- looks_like_spec_page: a page of own-line spec labels IS a spec page; a plan heading is NOT ---
    spec = "City\nMadrid\nWarehouse Area\n50,000 sq m\nClear Height\n12 m\nStatus\nExisting"
    ck(PS.looks_like_spec_page(spec), "a >=2-label spec page is recognised (negative gate)")
    ck(not PS.looks_like_spec_page("SITE PLAN\nUnit 1  Unit 2  Dock  Yard"),
       "a plan page (title + scattered drawing words, no own-line labels) is NOT a spec page")
    ck(not PS.looks_like_spec_page(""), "empty text is not a spec page")

    _eligible_cases(ck)
    _render_tier_cases(ck)

    if fails:
        print(f"\nPLAN DETECT TEST: FAIL ({len(fails)})")
        return 1
    print("\nPLAN DETECT TEST: PASS")
    return 0


def _eligible_cases(ck) -> None:
    """The unified _plan_page_eligible predicate, deterministic (no rendering): the photo-dominance
    guard + spec-page negative gate + title-rescue + visual path + the 'a continuous-tone render is a
    photo, never a plan' rule."""
    import images as IMG
    E = IMG._plan_page_eligible
    def ok(kind, white, has_photo, title, spec, marker=False):
        return E(kind, {"white": white}, has_photo, title, spec, marker)[0]
    def titled(kind, white, has_photo, title, spec, marker=False):
        return E(kind, {"white": white}, has_photo, title, spec, marker)[1]
    # NEGATIVE gates win over everything
    ck(not ok("plan", 0.5, False, 1.0, True, True), "eligible: a SPEC page never binds (spec gate)")
    ck(not ok("plan", 0.5, True, 1.0, False, True), "eligible: a page a real PHOTO dominates never binds")
    ck(not ok("photo", 0.5, False, 1.0, False, True), "eligible: a continuous-tone 'photo' render never binds (even titled+marker)")
    # VISUAL path (today's signature): kind=='plan' binds on the drawing signature ALONE, no title/
    # marker needed (a vector plan often has no extractable text at all).
    ck(ok("plan", 0.5, False, 0.0, False, False), "eligible: kind=='plan' in the white band binds (visual, no marker)")
    ck(not ok("plan", 0.95, False, 0.0, False, False), "eligible: kind=='plan' out of the white band does NOT bind")
    # TITLE-RESCUE for a mis-classified 'map' GRAPHIC now ALSO requires a to-scale DRAWING MARKER
    # (2nd-review fix #1): a real designed site plan carries "scale 1:500"/"drawing no"; a
    # photographic AERIAL or a genuine LOCATION MAP titled "Site Plan" does not -> it must NOT bind.
    ck(ok("map", 0.5, False, 1.0, False, True),
       "eligible: a titled 'map' WITH a drawing marker IS rescued (EVO to-scale colour plan)")
    ck(not ok("map", 0.5, False, 1.0, False, False),
       "eligible: a titled 'map' WITHOUT a drawing marker does NOT bind (aerial / location-map wrong-bind fix)")
    ck(titled("map", 0.5, False, 1.0, False, True), "eligible: the rescued page is still flagged 'titled'")
    ck(titled("map", 0.5, False, 1.0, False, False), "eligible: 'titled' is independent of the marker gate")
    ck(not ok("text", 0.5, False, 1.0, False, True), "eligible: a titled 'text' divider is NOT rescued (even with a marker)")
    ck(not ok("logo", 0.5, False, 1.0, False, True), "eligible: a titled 'logo' brand-divider is NOT rescued (even with a marker)")
    ck(not ok("map", 0.5, False, 0.0, False, True), "eligible: an untitled 'map' (location map) does NOT bind (marker alone can't rescue)")
    ck(not ok("map", 0.95, False, 1.0, False, True), "eligible: a titled 'map' + marker but near-white (out of band) does NOT bind")


def _render_tier_cases(ck) -> None:
    """Integration on synthetic fitz pages of the TWO render tiers (2026-07-20 redesign):
      * Tier 3 (page_render_plan, the LIVE LLM-hint path) TRUSTS the interpreter's visual pick - it
        binds ANY non-blank hinted page. There is NO pixel-classifier / white-band / marker veto here
        (that veto attached 0/4 real plans on the live Corby decks); a wrong pick is caught by the
        independent LLM verify, and the ONLY screen is a near-BLANK page.
      * Tier 5 (best_plan_page_render, the no-LLM OFFLINE fallback) stays CONSERVATIVE (classify 'plan'
        in a balanced-white band; a photo / blank never binds) - with no LLM there is no pick to trust
        and no verify to backstop."""
    import images as IMG
    try:
        import fitz
    except Exception as e:
        ck(False, f"render-tier: fitz unavailable ({e})"); return
    import io as _io, random, tempfile
    from PIL import Image

    def _vector_plan_page(pg):
        pg.draw_rect(fitz.Rect(60, 50, 540, 380), color=(0.1, 0.1, 0.1), width=3)
        pg.draw_rect(fitz.Rect(90, 80, 300, 350), color=(0.1, 0.1, 0.1), fill=(0.45, 0.65, 0.85), width=2)
        pg.draw_rect(fitz.Rect(320, 80, 510, 220), color=(0.1, 0.1, 0.1), fill=(0.6, 0.8, 0.55), width=2)
        pg.draw_rect(fitz.Rect(320, 240, 510, 350), color=(0.1, 0.1, 0.1), fill=(0.85, 0.8, 0.55), width=2)
        for x in range(110, 290, 30):
            pg.draw_line(fitz.Point(x, 90), fitz.Point(x, 340), color=(0.2, 0.2, 0.2), width=1)

    def _photo_jpeg(seed=7, w=800, h=450) -> bytes:
        rnd = random.Random(seed)
        img = Image.new("RGB", (64, 36))
        img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(64 * 36)])
        img = img.resize((w, h))
        b = _io.BytesIO(); img.save(b, format="JPEG", quality=85); return b.getvalue()

    def _flat_logo_png(w=340, h=210) -> bytes:
        rnd = random.Random(3)
        img = Image.new("RGB", (w, h), (20, 110, 120))  # near-solid teal = low photographic_score
        px = img.load()
        for _ in range(60):  # a few specks so it is a valid non-degenerate image
            px[rnd.randrange(w), rnd.randrange(h)] = (240, 240, 240)
        b = _io.BytesIO(); img.save(b, format="PNG"); return b.getvalue()

    BUD = IMG.DEFAULT_BUDGET_KB
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        doc = fitz.open()
        p0 = doc.new_page(width=600, height=420); _vector_plan_page(p0)                       # 0 clean vector plan
        p1 = doc.new_page(width=600, height=420); _vector_plan_page(p1)                        # 1 vector plan + hero logo
        p1.insert_image(fitz.Rect(60, 50, 400, 260), stream=_flat_logo_png())
        p2 = doc.new_page(width=600, height=420); p2.insert_image(fitz.Rect(40, 40, 560, 400), stream=_photo_jpeg(9))  # 2 photo page
        p3 = doc.new_page(width=600, height=420)                                                   # 3 photo captioned "SITE PLAN"
        p3.insert_image(fitz.Rect(40, 40, 560, 380), stream=_photo_jpeg(13)); p3.insert_text((50, 405), "SITE PLAN", fontsize=10)
        p4 = doc.new_page(width=600, height=420)                                                   # 4 'SITE PLAN' text page (no drawing)
        p4.insert_text((120, 190), "SITE PLAN", fontsize=54)
        p5 = doc.new_page(width=600, height=420)                                                   # 5 fully blank page (no content)
        f = td / "Deck.pdf"; doc.save(str(f)); doc.close()
        IMG.close_doc_cache()

        # --- Tier 5 (best_plan_page_render): the conservative no-LLM OFFLINE fallback (classifier) ---
        u0, _ = IMG.best_plan_page_render(f, [0], BUD, cache_dir=td / "a")
        ck(isinstance(u0, str) and u0.startswith("data:image/"), "tier5: a clean VECTOR plan binds (offline fallback)")
        u1, _ = IMG.best_plan_page_render(f, [1], BUD, cache_dir=td / "b")
        ck(isinstance(u1, str) and u1.startswith("data:image/"), "tier5: a plan page carrying a hero-size LOGO binds")
        u2, _ = IMG.best_plan_page_render(f, [2], BUD, cache_dir=td / "c")
        ck(u2 is None, "tier5: a real PHOTO page never binds")
        nm3 = []
        u3, _ = IMG.best_plan_page_render(f, [3], BUD, cache_dir=td / "g", near_miss=nm3)
        ck(u3 is None, "tier5: a photo page titled 'SITE PLAN' does NOT bind (photo dominates)")
        ck(any("photo" in e.get("why", "") for e in nm3), "tier5: the photo-dominated page is recorded as a near-miss")

        # --- Tier 3 (page_render_plan): the LIVE path TRUSTS the interpreter's visual pick ---
        ck(isinstance(IMG.page_render_plan(f, 0, BUD, cache_dir=td / "d"), str),
           "tier3: a plan_page hint at a real plan page binds")
        ck(isinstance(IMG.page_render_plan(f, 2, BUD, cache_dir=td / "e"), str),
           "tier3: a hint at a PHOTO-looking page BINDS - the live path trusts the pick; a wrong pick is "
           "caught by the independent LLM verify, not a pixel classifier (the 0/4 live-run fix)")
        ck(isinstance(IMG.page_render_plan(f, 4, BUD, cache_dir=td / "i"), str),
           "tier3: a hint at a full-bleed / text-heavy page BINDS too (no white-band / marker veto)")
        ck(IMG.page_render_plan(f, 5, BUD, cache_dir=td / "z") is None,
           "tier3: a BLANK hinted page does NOT bind (the only live-tier screen)")
        IMG.close_doc_cache()
        IMG.close_doc_cache()


if __name__ == "__main__":
    sys.exit(main())
