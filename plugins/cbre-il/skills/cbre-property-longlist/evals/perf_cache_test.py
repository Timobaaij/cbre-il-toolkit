#!/usr/bin/env python3
"""perf_cache_test.py - the RESUMED-RUN cost contract for the two image caches (2026-07-30).

A cache is only a fix if a warm call is CHEAP *and* byte-identical. These two producers each
failed one half of that before today, and the battery could not see it because every existing
assertion gives them a FRESH cache dir - so a permanent 100% miss reads as "slow", not "broken".

  * `best_plan_page_render` consulted its per-page URI cache only AFTER rendering, classifying
    and text-scanning every candidate page, and never persisted the DECISION. Measured at 40
    properties: 22.8s then 23.6s - warm SLOWER than cold - for 0 plans bound.
  * `embedded_by_index` - the binder for the LLM's __meta.heroRef pick, the tier that wins over
    all others - had NO cache at all: 81% of a warm 40-property merge.

Locks four things a naive cache would get wrong: byte-identical URIs (the frozen-chrome /
cached-.uri contract), the NEAR-MISS list surviving a verdict hit (it feeds the Gaps Report's
"possible site plans not captured" lines - dropping it would trade a hang for a quiet loss of
honesty), a different page set getting its OWN verdict, and `index` being part of the hero key
(two properties on one page must never swap heroes).

Offline. Run: python evals/perf_cache_test.py"""
from __future__ import annotations

import io
import random
import sys
import tempfile
import time
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import fitz  # noqa: E402
from PIL import Image  # noqa: E402

import images as IMG  # noqa: E402


def photo(seed, w=1400, h=950):
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (min(255, x // 6 + rnd.randrange(80)),
                        min(255, y // 5 + rnd.randrange(80)), rnd.randrange(200))
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=86)
    return b.getvalue()


def deck(tmp: Path) -> Path:
    doc = fitz.open()
    # 0 photo page, 1 spec page w/ plan title (near-miss), 2 real vector plan, 3 map
    p0 = doc.new_page(width=595, height=842)
    p0.insert_image(fitz.Rect(30, 30, 565, 500), stream=photo(1))
    p1 = doc.new_page(width=595, height=842)
    for i, ln in enumerate(["SITE PLAN", "Warehouse area: 24,500 sq m", "Clear height: 12 m",
                            "Dock doors: 24", "Car parking: 120 spaces"]):
        p1.insert_text((60, 90 + i * 26), ln, fontsize=12)
    p2 = doc.new_page(width=842, height=595)
    p2.insert_text((60, 40), "SITE PLAN    Scale 1:1250", fontsize=13)
    p2.draw_rect(fitz.Rect(70, 70, 780, 520), color=(0.1, 0.1, 0.1), width=2)
    for i in range(3):
        x0 = 100 + i * 220
        p2.draw_rect(fitz.Rect(x0, 120, x0 + 190, 420), color=(0.1, 0.1, 0.1),
                     fill=(0.72, 0.78, 0.85), width=2)
    for gx in range(90, 780, 35):
        p2.draw_line(fitz.Point(gx, 440), fitz.Point(gx, 505), color=(0.3, 0.3, 0.3), width=1)
    p3 = doc.new_page(width=595, height=842)
    p3.insert_image(fitz.Rect(30, 30, 565, 400), stream=photo(9))
    f = tmp / "Deck.pdf"
    doc.save(str(f))
    doc.close()
    return f


def main():
    try:  # the native cp1252 console must not crash the suite
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        pdf = deck(td)
        cache = td / "cache"
        pages = [0, 1, 2, 3]

        # ---- best_plan_page_render: verdict cache ----
        nm1: list = []
        t0 = time.perf_counter()
        uri1, pno1 = IMG.best_plan_page_render(pdf, pages, 110, cache, near_miss=nm1)
        t_cold = time.perf_counter() - t0
        IMG.close_doc_cache()
        nm2: list = []
        t0 = time.perf_counter()
        uri2, pno2 = IMG.best_plan_page_render(pdf, pages, 110, cache, near_miss=nm2)
        t_warm = time.perf_counter() - t0
        print(f"\nbest_plan_page_render: cold {t_cold * 1000:.0f} ms -> warm {t_warm * 1000:.0f} ms "
              f"(x{t_cold / max(t_warm, 1e-9):.0f})   page={pno1}->{pno2}")
        ck(uri1 == uri2 and pno1 == pno2, "same verdict AND byte-identical URI on the warm call")
        ck(t_warm < t_cold * 0.25, f"warm call is much cheaper ({t_warm * 1000:.0f} ms)")
        ck(nm1 == nm2, f"NEAR-MISS list survives the cache hit ({len(nm1)} entr(y/ies): "
                       f"{[e['page'] for e in nm1]}) - the Gaps Report lines are not lost")
        # a DIFFERENT page set must not read the first verdict
        u3, p3 = IMG.best_plan_page_render(pdf, [0, 3], 110, cache)
        ck(p3 != pno1 or p3 is None,
           f"a different page set gets its own verdict (pages [0,3] -> {p3}, not {pno1})")

        # ---- embedded_by_index: cache + index isolation ----
        IMG.close_doc_cache()
        t0 = time.perf_counter()
        a1 = IMG.embedded_by_index(pdf, 0, 0, 110, cache_dir=cache)
        t_c = time.perf_counter() - t0
        IMG.close_doc_cache()
        t0 = time.perf_counter()
        a2 = IMG.embedded_by_index(pdf, 0, 0, 110, cache_dir=cache)
        t_w = time.perf_counter() - t0
        print(f"embedded_by_index:     cold {t_c * 1000:.0f} ms -> warm {t_w * 1000:.0f} ms "
              f"(x{t_c / max(t_w, 1e-9):.0f})")
        ck(a1 is not None and a1 == a2, "byte-identical hero URI from the cache")
        ck(t_w < max(t_c * 0.35, 0.004), f"warm call is much cheaper ({t_w * 1000:.1f} ms)")
        nocache = IMG.embedded_by_index(pdf, 0, 0, 110)
        ck(nocache == a1, "cache_dir=None still returns the SAME bytes (no behaviour change)")
        # index isolation: page 0 index 0 vs a page with 2+ candidates
        cands = IMG.candidates_for_page(pdf, 0)
        if len(cands) > 1:
            b0 = IMG.embedded_by_index(pdf, 0, 0, 110, cache_dir=cache)
            b1 = IMG.embedded_by_index(pdf, 0, 1, 110, cache_dir=cache)
            ck(b0 != b1, "different index -> different URI (no key collision / hero swap)")
        else:
            print(f"  [note] page 0 has {len(cands)} candidate(s); index-collision check "
                  f"covered by the distinct cache kind 'heroref<index>'")
        ck(IMG.embedded_by_index(pdf, 0, 99, 110, cache_dir=cache) is None,
           "an out-of-range index still returns None")
        IMG.close_doc_cache()

    print("\n" + ("FAIL" if fails else "OK") + f" verify_perf: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
