#!/usr/bin/env python3
"""plan_reader_declined_test.py - fix 3.9 (2026-09-26 test run).

The Tier-5 site-plan detector (`images.best_plan_page_render`) bound a legal/terms page into the
Site Plan slot through the VISUAL route alone (the pixel classifier said 'plan' at white 0.46; no
title, no scale marker, no drawing labels), on a deck whose reader had looked at every page render
and written `plan_page: null`. Only a reviewer caught it. A narrow guard: when the caller says the
reader declined, a page eligible by pixels ALONE is a near-miss, not a bind.

Pins:
  * reader_declined=False binds the pixels-only page (today's behaviour);
  * reader_declined=True returns (None, None) with the near-miss reason;
  * the same page carrying "SITE PLAN" + "Scale 1:500" binds even when declined;
  * the verdict cache key is unchanged for default callers (a declined call does not reuse it);
  * `merge._reader_declined_plan` truth table: key absent -> False; image_pages [] -> False;
    plan_page 3 -> False; an int planRef -> False; null + [0, 2] -> True; another deck -> False;
  * attach_media passes reader_declined=True ONLY in the declined case (default calls unchanged).

Run: python evals/plan_reader_declined_test.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import images as IMG  # noqa: E402
import merge as M  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    from PIL import Image
    td = Path(tempfile.mkdtemp(prefix="cbre_plan_decl_"))
    deck = td / "Terms Deck.pdf"
    deck.write_bytes(b"%PDF-1.4\n% synthetic stand-in; every reader of it is monkeypatched\n")
    crop = Image.new("RGB", (800, 600), (255, 255, 255))
    for x in range(100, 700, 40):
        for y in range(100, 500):
            crop.putpixel((x, y), (0, 0, 0))
    TEXT = {"text": "Information contained herein is believed correct. Legal costs: each party "
                    "bears its own. Rateable value on application. Terms: new lease."}
    saved = {k: getattr(IMG, k) for k in ("_rendered_plan_crop", "_page_plaintext",
                                          "_page_has_dominant_photo", "page_vector_art")}
    try:
        IMG._rendered_plan_crop = lambda *a, **k: (crop, {"white": 0.5}, "plan")
        IMG._page_plaintext = lambda *a, **k: TEXT["text"]
        IMG._page_has_dominant_photo = lambda *a, **k: False
        IMG.page_vector_art = lambda *a, **k: {}

        nm0: list = []
        uri, pno = IMG.best_plan_page_render(deck, [2], 60, td / "c0", near_miss=nm0)
        ck(bool(uri) and pno == 2, "reader_declined=False: the pixels-only page binds (today's behaviour)")
        nm1: list = []
        uri, pno = IMG.best_plan_page_render(deck, [2], 60, td / "c0", near_miss=nm1,
                                             reader_declined=True)
        ck(uri is None and pno is None, "reader_declined=True: nothing binds")
        ck(any(e.get("page") == 2 and "pixels alone" in e.get("why", "") for e in nm1),
           f"...and the page is a near-miss with the reason ({nm1})")
        nm2: list = []
        uri, pno = IMG.best_plan_page_render(deck, [2], 60, td / "c0", near_miss=nm2)
        ck(bool(uri) and pno == 2, "a default call after a declined one still gets its own cached bind")

        TEXT["text"] = "SITE PLAN\nScale 1:500 @ A3\nNorth"
        uri, pno = IMG.best_plan_page_render(deck, [3], 60, td / "c1", near_miss=[],
                                             reader_declined=True)
        ck(bool(uri) and pno == 3, "a titled page with a scale marker binds even when declined")
    finally:
        for k, v in saved.items():
            setattr(IMG, k, v)

    print("== merge._reader_declined_plan truth table ==")
    src = td / "deck.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    other = td / "other.pdf"
    other.write_bytes(b"%PDF-1.4\n")

    def cl(**meta):
        m = {"source_file": "deck.pdf", "source_type": "pdf", "page_no": 0}
        m.update(meta)
        return [{"park": "P", "__meta": m}]

    s = str(M._resolve_source(td, "deck.pdf"))
    ck(M._reader_declined_plan(cl(image_pages=[0, 2]), s, td) is False, "plan_page key absent -> False")
    ck(M._reader_declined_plan(cl(plan_page=None, image_pages=[]), s, td) is False, "image_pages [] -> False")
    ck(M._reader_declined_plan(cl(plan_page=3, image_pages=[0, 2]), s, td) is False, "plan_page 3 -> False")
    ck(M._reader_declined_plan(cl(plan_page=None, image_pages=[0, 2], planRef=1), s, td) is False,
       "an int planRef -> False")
    ck(M._reader_declined_plan(cl(plan_page=None, image_pages=[0, 2]), s, td) is True,
       "plan_page null + image_pages [0, 2] -> True")
    ck(M._reader_declined_plan(cl(plan_page=None, image_pages=[0, 2]),
                               str(M._resolve_source(td, "other.pdf")), td) is False,
       "records of another deck -> False")
    mixed = cl(plan_page=None, image_pages=[0, 2]) + cl(image_pages=[1])
    ck(M._reader_declined_plan(mixed, s, td) is False, "one record without the key -> False")

    print("== attach_media passes it only when declined ==")
    calls: list = []
    real = M.IMG.best_plan_page_render
    try:
        def fake(*a, **k):
            calls.append(dict(k))
            return (None, None)
        M.IMG.best_plan_page_render = fake
        M.attach_media(cl(plan_page=None, image_pages=[0, 2]), td, 60, image_cache=td / "c2")
        M.attach_media(cl(image_pages=[0, 2]), td, 60, image_cache=td / "c2")
    finally:
        M.IMG.best_plan_page_render = real
    ck(len(calls) == 2 and calls[0].get("reader_declined") is True
       and "reader_declined" not in calls[1],
       f"declined -> reader_declined=True; default -> no new kwarg ({calls})")

    print(f"\n{'PASS' if not FAILS else 'FAIL'} plan_reader_declined_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
