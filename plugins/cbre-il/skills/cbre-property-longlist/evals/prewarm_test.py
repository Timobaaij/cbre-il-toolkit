#!/usr/bin/env python3
"""prewarm_test.py - `merge.prewarm_images` must actually RUN, in PARALLEL, and bank its work.

WHY THIS EXISTS (a live regression, 2026-07-30). A `finally` block added to bound the pool's wall
time contained `list(getattr(ex, "_processes", {})).values()` - `list()` of a dict yields its KEYS,
which have no `.values()`. So prewarm raised `AttributeError: 'list' object has no attribute
'values'` on EVERY pass, run.py caught it and printed "image pre-warm skipped", and the parallel
warm-up silently never happened. A live 12-property Cowork run then rasterised and compressed 107
brochure pages SERIALLY inside a ~45s shell ceiling: merge alone needed ~6 resume passes, each one
another shell invocation that re-walked intake and validation.

The battery could not see it because nothing exercised the MULTI-WORKER path - the serial
`workers<=1` branch has no pool, no `finally`, and no private attributes.

So this asserts the things that actually failed:
  * prewarm RETURNS instead of raising (with a real process pool, workers>1)
  * it BANKS work: cache units exist afterwards, and a second call finds them already warm
  * its time budget is respected without destroying in-flight work
  * the serial path still works
  * no `list(...).values()` / `.values()`-on-a-list pattern survives in merge.py

Offline; needs Pillow + a PDF engine. Run: python evals/prewarm_test.py"""
from __future__ import annotations

import io
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as MG  # noqa: E402


def _photo(seed: int, w: int = 1100, h: int = 750) -> bytes:
    from PIL import Image
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (min(255, x // 5 + rnd.randrange(70)),
                        min(255, y // 4 + rnd.randrange(70)), rnd.randrange(190))
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=84)
    return b.getvalue()


def _deck(path: Path, pages: int) -> None:
    import fitz
    doc = fitz.open()
    for p in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((60, 70), f"Unit {p + 1} - Warehouse area: {12000 + p * 900} sq m",
                       fontsize=12)
        pg.insert_image(fitz.Rect(40, 100, 555, 470), stream=_photo(p + 3))
    doc.save(str(path))
    doc.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # the exact defect, as a source-level guard: `list(<dict>).values()` can never work
    msrc = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8")
    import re
    ck(not re.search(r"list\([^)]*\)\.values\(\)", msrc),
       "no `list(...).values()` in merge.py (list() of a dict gives KEYS - the live crash)")
    ck("_processes" not in msrc,
       "no reliance on the pool's private `_processes` attribute (undocumented, version-fragile)")

    try:
        import fitz  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:
        print(f"SKIP prewarm_test: needs fitz + Pillow ({e})")
        return 0

    # ignore_cleanup_errors: prewarm_images deliberately does NOT join its workers (a bounded
    # wait is the whole point, and this suite asserts it below), so on Windows a worker can
    # still hold a Deck*.pdf handle when this block exits -> rmtree raises WinError 32 and the
    # process exits 1 even though every assertion PASSED. That turned the battery flaky and
    # CWD-dependent: a teardown race must never masquerade as a failed eval.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_s:
        td = Path(td_s)
        src = td / "inputs"
        src.mkdir()
        for d in range(3):
            _deck(src / f"Deck{d}.pdf", 4)
        cache = td / ".image_cache"
        recs = [{"__meta": {"source_file": f"Deck{d}.pdf", "source_type": "pdf", "page_no": p}}
                for d in range(3) for p in range(4)]

        # THE REGRESSION: this raised AttributeError on every call
        t0 = time.perf_counter()
        try:
            done, total = MG.prewarm_images(recs, src, cache, 110, seconds=30.0, workers=4)
            raised = None
        except Exception as e:
            done = total = -1
            raised = f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        ck(raised is None, f"prewarm_images does NOT raise with a real pool (workers=4) [{raised}]")
        ck(total > 0, f"it enumerated units to warm ({total})")
        ck(done > 0, f"it COMPLETED units rather than dying or being killed off ({done}/{total})")
        n_cached = len(list(cache.glob("*"))) if cache.exists() else 0
        ck(n_cached > 0, f"it BANKED work to the cache dir ({n_cached} file(s)) - a resumed merge "
                         f"reads these instead of re-rasterising")
        print(f"  [time] {dt:.1f}s for {total} unit(s) across 4 workers")

        # a SECOND call must find them warm (this is what saves the resumed round)
        t0 = time.perf_counter()
        done2, total2 = MG.prewarm_images(recs, src, cache, 110, seconds=30.0, workers=4)
        dt2 = time.perf_counter() - t0
        ck(dt2 < max(dt * 0.6, 0.5),
           f"a warm re-run is much cheaper ({dt2:.2f}s vs {dt:.1f}s) - units are skipped, not redone")

        # the serial path (workers=1) must still work - it is the no-pool fallback
        cache2 = td / ".image_cache2"
        try:
            d1, t1 = MG.prewarm_images(recs, src, cache2, 110, seconds=30.0, workers=1)
            ser = None
        except Exception as e:
            d1 = t1 = -1
            ser = f"{type(e).__name__}: {e}"
        ck(ser is None and d1 > 0, f"the serial (workers=1) path still warms units ({d1}/{t1})")

        # the budget must bound the WAIT without throwing
        cache3 = td / ".image_cache3"
        t0 = time.perf_counter()
        try:
            MG.prewarm_images(recs, src, cache3, 110, seconds=0.4, workers=4)
            budget_ok = True
        except Exception as e:
            budget_ok = False
            print(f"      raised under a tight budget: {type(e).__name__}: {e}")
        dt3 = time.perf_counter() - t0
        ck(budget_ok, "a tight budget does not raise")
        ck(dt3 < 25.0, f"and it returns promptly ({dt3:.1f}s) rather than joining every worker")

        ck(MG.prewarm_images(recs, src, None, 110)[1] == 0,
           "no cache dir -> a clean (0, 0) no-op, never a crash")

    print(f"\n{'OK' if not fails else 'FAIL'} prewarm_test: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
