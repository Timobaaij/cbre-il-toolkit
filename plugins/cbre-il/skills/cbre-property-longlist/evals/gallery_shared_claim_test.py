#!/usr/bin/env python3
"""gallery_shared_claim_test.py - fix 3.20 (2026-09-26 test run).

A deck's three records all had `page_no 0` and `image_pages [0, 1]`. Page 0 was anchored by
three clusters (so owned by nobody) and page 1 was claimed by all three, and the one-owner rule
(`_page_allowed`) made both pages foreign to every one of them: three one-image cards while a
card-quality photograph sat on the page every reader named. A co-claimed, unanchored page is
now SHARED by the co-claimants' CAROUSELS (`_gallery_page_allowed` /
`build_gallery_foreign_pages` / `attach_media(gallery_foreign=)`), never their Site Plan slot.

Pins (synthetic 3-page PDF, a card-quality photo on each page):
  * every one of the three carousels holds the page-1 photo;
  * considered.decks[deck].gallery_shared == [0, 1], and `foreign` is empty for the carousel;
  * a page ANOTHER single record anchors (page 2, anchored by D) is still refused, even when A
    also lists it;
  * the plan-slot foreign set (build_foreign_pages) still holds pages 0 and 1 (Tier 5 unchanged);
  * without gallery_foreign, attach_media behaves exactly as before (page 1 refused).

Run: python evals/gallery_shared_claim_test.py"""
from __future__ import annotations

import io
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

FAILS: list[str] = []


def ck(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _photo(seed, w=900, h=600):
    from PIL import Image
    g = random.Random(seed)
    im = Image.new("RGB", (w, h))
    im.putdata([(((x * 255) // w + g.randrange(96)) % 256,
                 ((y * 255) // h + g.randrange(96)) % 256,
                 (((x + y) * 127) // (w + h) + g.randrange(96)) % 256)
                for y in range(h) for x in range(w)])
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=85)
    return b.getvalue()


def main() -> int:
    try:
        import fitz
        import images as IMG
        import merge as M
    except Exception as e:  # noqa: BLE001
        ck(False, f"setup: {e}")
        return 1
    td = Path(tempfile.mkdtemp(prefix="cbre_gal_shared_"))
    doc = fitz.open()
    for p in range(3):
        pg = doc.new_page(width=595, height=460)
        pg.insert_text((40, 60), f"SECTION {chr(65 + p)}", fontsize=12)
        pg.insert_image(fitz.Rect(40, 90, 540, 420), stream=_photo(200 + p))
    f = td / "Three Unit Scheme.pdf"
    doc.save(str(f))
    doc.close()
    s = str(f)
    IMG.close_doc_cache()

    def rec(park, page, ip):
        return [{"park": park, "city": "Northtown",
                 "__meta": {"source_file": f.name, "source_type": "pdf", "page_no": page,
                            "image_pages": ip}}]

    clusters = [rec("Unit 1", 0, [0, 1]), rec("Unit 2", 0, [0, 1]), rec("Unit 3", 0, [0, 1])]
    fp = M.build_foreign_pages(clusters, td)
    gf = M.build_gallery_foreign_pages(clusters, td)
    ck(all(fp[i].get(s) == {0, 1} for i in range(3)),
       f"the PLAN-slot foreign set still holds pages 0 and 1 for all three ({[sorted(x.get(s, ())) for x in fp]})")
    ck(all(not gf[i].get(s) for i in range(3)), "the CAROUSEL foreign set is empty for the co-claimants")
    p1 = set(IMG.gallery_for_pages(f, [1], 60, td / "c")[0])
    ck(bool(p1), "setup: page 1 carries an admissible photo")
    for i in range(3):
        cons: dict = {}
        out = M.attach_media(json.loads(json.dumps(clusters[i])), td, 60, image_cache=td / "c",
                             foreign_pages=fp[i], considered=cons, gallery_foreign=gf[i])
        d = (cons.get("decks") or {}).get(f.name) or {}
        ck(bool(set(out[5]) & p1), f"Unit {i + 1}: the carousel holds the page-1 photo ({len(out[5])} images)")
        ck(d.get("gallery_shared") == [0, 1] and d.get("foreign") == [],
           f"Unit {i + 1}: considered gallery_shared [0, 1], foreign [] ({d.get('gallery_shared')}, {d.get('foreign')})")
    old = M.attach_media(json.loads(json.dumps(clusters[0])), td, 60, image_cache=td / "c",
                         foreign_pages=fp[0])
    ck(not (set(old[5]) & p1), "without gallery_foreign attach_media is unchanged (page 1 refused)")

    print("== a page another single property anchors is still refused ==")
    cl2 = [rec("Unit 1", 0, [0, 1, 2]), rec("Unit 2", 0, [0, 1]), rec("Unit 4", 2, [2])]
    gf2 = M.build_gallery_foreign_pages(cl2, td)
    ck(2 in (gf2[0].get(s) or set()), "page 2 (anchored by Unit 4) is foreign to Unit 1's carousel")
    ck(not (gf2[2].get(s) or set()), "...and Unit 4 keeps its own anchor page")
    p2 = set(IMG.gallery_for_pages(f, [2], 60, td / "c")[0])
    out = M.attach_media(json.loads(json.dumps(cl2[0])), td, 60, image_cache=td / "c",
                         foreign_pages=M.build_foreign_pages(cl2, td)[0], gallery_foreign=gf2[0])
    ck(bool(p2) and not (set(out[5]) & p2), "Unit 1's carousel never carries Unit 4's page-2 photo")
    ck(M._gallery_page_allowed(0, s, 1, {}, {(s, 1): {0, 1}})
       and not M._page_allowed(0, s, 1, {}, {(s, 1): {0, 1}}),
       "carousel shares / plan slot refuses the same co-claimed page")
    IMG.close_doc_cache()

    print(f"\n{'PASS' if not FAILS else 'FAIL'} gallery_shared_claim_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
