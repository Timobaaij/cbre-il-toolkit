#!/usr/bin/env python3
"""audit_resume_test.py - Cowork-resume convergence for the two loop traps (2026-07-28).

Part A (placeholder audit): page_image_audit must take the SAME persistent disk cache the
pickers use (cache_dir) and thread it into _page_crops, so a resumed merge run (the ~40s
shell-cap kill/re-run cycle) never re-parses a whole deck's geometry uncached per run - the
"infinite re-run trap" _placed_layout's cache exists to prevent. Live failure 2026-07-28:
merge.py:1238 called page_image_audit WITHOUT the cache (the PPTX twin one line up passes it),
so every resumed run redid the full pdfplumber deck parse and threw it away - the merge hang.

Part B (region labels): the exit-3 job emitter's "already asked" set must include DECLINED
resolutions (code=null). _region_labels_cache() rightly drops declines (the bind path must
never bind a null), but run.py used those same keys as cached_keys, so a legitimately
declined label was re-asked on every re-run and exit 3 never converged. The emitter needs
the answered-keys view (_region_labels_answered_keys), a strict superset of the bind cache.

Offline. Run: python evals/audit_resume_test.py"""
from __future__ import annotations
import io
import json
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import enrich  # noqa: E402
import images as IMG  # noqa: E402


def main() -> int:
    try:  # force UTF-8 so the suite also completes on a cp1252 mcp__shell console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---------------- Part A: the placeholder audit uses the persistent image cache ----------------
    print("Part A: page_image_audit resumes from / persists to the disk image cache")
    try:
        import fitz
        from PIL import Image
    except Exception as e:
        ck(False, f"fixtures need fitz+Pillow ({e})")
        return 1

    def _photo_jpeg(seed: int) -> bytes:
        import random
        rnd = random.Random(seed)
        img = Image.new("RGB", (640, 420))
        px = img.load()
        for y in range(420):  # noisy gradient = photo-like, never flat
            for x in range(640):
                px[x, y] = (min(255, x // 3 + rnd.randrange(60)),
                            min(255, y // 2 + rnd.randrange(60)),
                            rnd.randrange(200))
        b = io.BytesIO()
        img.save(b, format="JPEG", quality=85)
        return b.getvalue()

    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        doc = fitz.open()
        for pno in range(3):  # 3 pages, each with a PLACED image -> real geometry entries
            pg = doc.new_page(width=600, height=420)
            pg.insert_image(fitz.Rect(40, 40, 560, 380), stream=_photo_jpeg(pno + 7))
        pdf = td / "Deck.pdf"
        doc.save(str(pdf))
        doc.close()
        cache = td / "image_cache"
        audit_out = td / "placeholder_audit"
        try:
            # the audit accepts the pickers' cache_dir (merge passes image_cache, like the
            # PPTX twin) ...
            seen: dict = {}
            orig_crops = IMG._page_crops

            def _spy(pdf_path, page_index, dpi=150, cache_dir=None):
                seen["cache_dir"] = cache_dir
                return orig_crops(pdf_path, page_index, dpi=dpi, cache_dir=cache_dir)

            IMG._page_crops = _spy
            try:
                files = IMG.page_image_audit(pdf, 0, audit_out, "prop1", cache_dir=cache)
            finally:
                IMG._page_crops = orig_crops
            ck(True, "page_image_audit accepts cache_dir (merge can pass the image cache)")
            ck(seen.get("cache_dir") == cache,
               "cache_dir is threaded into _page_crops (the geometry/render layer)")
            jsons = list(cache.glob("*.json")) + list(cache.glob("*.placed.json"))
            ck(bool(jsons),
               f"per-page geometry persisted to the cache ({len(jsons)} file(s)) - a resumed "
               f"run reads it back instead of re-parsing the deck")
            ck(isinstance(files, list), "audit still returns the written thumbnail paths")
        except TypeError as e:
            ck(False, f"page_image_audit rejects cache_dir ({e}) - the placeholder audit "
                      f"re-parses every deck page uncached on each resumed run")
        finally:
            IMG.close_doc_cache()  # release the fitz handle so Windows can delete the tempdir

    # merge's call site actually passes it (the PDF branch mirrors the PPTX branch);
    # the call may wrap, so read a 3-line window from the call line
    merge_lines = (HELPERS / "merge.py").read_text(encoding="utf-8").splitlines()
    a_call = next(("\n".join(merge_lines[i:i + 3]) for i, ln in enumerate(merge_lines)
                   if "IMG.page_image_audit(" in ln), "")
    ck("cache_dir=image_cache" in a_call,
       "merge.py passes cache_dir=image_cache to page_image_audit (the PDF audit branch)")

    # ---------------- Part B: declined region labels are never re-asked ----------------
    print("Part B: the exit-3 emitter skips ANSWERED labels, resolved AND declined")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        (td / "extract").mkdir(parents=True)
        resolved = {"raw_label": "Guadalajara provincia", "city": "Cabanillas del Campo",
                    "country_cc": "ES", "code": "ES424", "matched_name": "Guadalajara",
                    "confidence": "high", "reason": "same province, ES synonym"}
        declined = {"raw_label": "Zona Centro Logistico", "city": "", "country_cc": "ES",
                    "code": None, "matched_name": None, "confidence": "low",
                    "reason": "no candidate names this area"}
        (td / "extract" / "region_labels.json").write_text(
            json.dumps({"resolutions": [resolved, declined, "not-a-dict"]}),
            encoding="utf-8")
        old_cache_dir = enrich.CACHE_DIR
        enrich.CACHE_DIR = td
        try:
            k_res = enrich._region_label_key("Guadalajara provincia", "ES",
                                             "Cabanillas del Campo")
            k_dec = enrich._region_label_key("Zona Centro Logistico", "ES", "")
            cache = enrich._region_labels_cache()
            ck(set(cache.keys()) == {k_res} and cache[k_res] == "ES424",
               "bind cache is UNCHANGED: code-bearing entries only (a null never binds)")
            try:
                answered = enrich._region_labels_answered_keys()
            except AttributeError:
                answered = None
                ck(False, "_region_labels_answered_keys missing - the emitter has no view "
                          "of declined labels, so a declined label is re-asked forever")
            if answered is not None:
                ck(k_res in answered and k_dec in answered,
                   "answered keys include BOTH the resolved and the DECLINED label")
                ck(set(cache.keys()) <= set(answered),
                   "answered keys are a superset of the bind cache (resume no-op holds)")
                # the emitter's convergence rule itself: with every unresolved label already
                # answered, NO job is re-emitted (exit 3 cannot loop on a decline)
                jobs = [k for k in (k_res, k_dec) if k not in answered]
                ck(jobs == [], "no job re-emitted for an answered (declined) label")
        finally:
            enrich.CACHE_DIR = old_cache_dir

    # run.py's emitter uses the answered-keys view, not the bind cache's keys
    run_src = (HELPERS / "run.py").read_text(encoding="utf-8")
    ck("_region_labels_answered_keys()" in run_src,
       "run.py builds cached_keys from _region_labels_answered_keys (declines skip too)")

    print(f"\n{'OK' if not fails else 'FAIL'} audit_resume_test: "
          f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
