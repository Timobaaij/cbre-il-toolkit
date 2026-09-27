#!/usr/bin/env python3
"""gallery_claimed_only_test.py - fix 3.8 (2026-09-26 test run).

On a deck shared by several properties, `merge.gallery_reach_pages` gave every claimant the
pages NO record claimed as "park-level". A two-unit deck whose reader assigned pages to each
record (image_pages) and deliberately left its "indicative images" page out still shipped that
page on one unit's card. When the reader of a multi-record deck made EXPLICIT claims (at least
one non-empty image_pages), an unclaimed page is now a deliberate exclusion: the reach is each
record's own named plan_page only.

Pins (synthetic 6-page PDF, one card-quality photo per page):
  * A: page_no 0, image_pages [0,1], plan_page 4; B: page_no 3, image_pages [3]:
    pages 2 and 5 are in NO reach, park_level is empty, page 4 is in A's reach only, and
    scope_out / attach_media's `considered` say gallery_scope "claimed_only";
  * A's carousel never carries the page-5 photo;
  * the same deck with image_pages [] on both records keeps today's park-level reach (page 5
    reaches both, scope "reach");
  * a single-record deck is unchanged (its whole unclaimed set is in reach).

Run: python evals/gallery_claimed_only_test.py"""
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


def deck(td: Path, n: int, name: str) -> Path:
    import fitz
    doc = fitz.open()
    for p in range(n):
        pg = doc.new_page(width=595, height=460)
        pg.insert_text((40, 60), f"SECTION {chr(65 + p)} OVERVIEW", fontsize=12)
        pg.insert_image(fitz.Rect(40, 90, 540, 420), stream=_photo(100 + p))
    f = td / name
    doc.save(str(f))
    doc.close()
    return f


def rec(f, park, area, page, image_pages=None, plan_page="absent"):
    m = {"source_file": f.name, "source_type": "pdf", "page_no": page}
    if image_pages is not None:
        m["image_pages"] = image_pages
    if plan_page != "absent":
        m["plan_page"] = plan_page
    return {"park": park, "city": "Northtown", "warehouseArea": area, "__meta": m}


def main() -> int:
    try:
        import fitz  # noqa: F401
        import images as IMG
        import merge as M
    except Exception as e:  # noqa: BLE001
        ck(False, f"setup: {e}")
        return 1
    td = Path(tempfile.mkdtemp(prefix="cbre_gal_claimed_"))
    f = deck(td, 6, "Shared Two Unit Deck.pdf")
    s = str(f)
    IMG.close_doc_cache()

    print("== explicit claims: claimed pages only ==")
    A = [rec(f, "Alpha Building", 250000, 0, [0, 1], plan_page=4)]
    B = [rec(f, "Beta Building", 180000, 3, [3])]
    pl, scope = [], []
    gr = M.gallery_reach_pages([A, B], td, park_level=pl, scope_out=scope)
    rA, rB = gr[0].get(s, set()), gr[1].get(s, set())
    ck(5 not in rA | rB and 2 not in rA | rB,
       f"unclaimed pages 2 and 5 reach NO carousel (A={sorted(rA)}, B={sorted(rB)})")
    ck(rA == {4} and rB == set(), "page 4 (A's named plan_page) is in A's reach only")
    ck(not any(x.get(s) for x in pl), f"park_level is empty ({pl})")
    ck(scope == [{s: "claimed_only"}, {s: "claimed_only"}], f"scope_out marks the deck claimed_only ({scope})")
    fp = M.build_foreign_pages([A, B], td)
    gf = M.build_gallery_foreign_pages([A, B], td)
    po = M.plan_offlimits_pages([A, B], td)
    cons: dict = {}
    out = M.attach_media(json.loads(json.dumps(A)), td, 60, image_cache=td / "c1",
                         foreign_pages=fp[0], plan_offlimits=po[0], considered=cons,
                         gallery_reach=gr[0], gallery_foreign=gf[0], gallery_scope=scope[0])
    d = (cons.get("decks") or {}).get(f.name) or {}
    ck(d.get("gallery_scope") == "claimed_only", f"considered records gallery_scope claimed_only ({d.get('gallery_scope')})")
    p5 = set(IMG.gallery_for_pages(f, [5], 60, td / "c1")[0])
    ck(bool(p5) and not (set(out[5]) & p5), "A's carousel never carries the page-5 photo")

    print("== image_pages [] on both: today's park-level reach ==")
    A0 = [rec(f, "Alpha Building", 250000, 0, [], plan_page=4)]
    B0 = [rec(f, "Beta Building", 180000, 3, [])]
    pl0, scope0 = [], []
    gr0 = M.gallery_reach_pages([A0, B0], td, park_level=pl0, scope_out=scope0)
    ck(5 in gr0[0].get(s, set()) and 5 in gr0[1].get(s, set()),
       f"page 5 reaches both (A={sorted(gr0[0].get(s, set()))}, B={sorted(gr0[1].get(s, set()))})")
    ck(5 in pl0[0].get(s, set()), "...as park-level, disclosed")
    ck(scope0 == [{}, {}], "no claimed_only scope when no record carries a non-empty image_pages")
    cons0: dict = {}
    M.attach_media(json.loads(json.dumps(A0)), td, 60, image_cache=td / "c1", considered=cons0,
                   gallery_reach=gr0[0], gallery_scope=scope0[0])
    ck(((cons0.get("decks") or {}).get(f.name) or {}).get("gallery_scope") == "reach",
       "considered records gallery_scope 'reach' for today's behaviour")
    cons1: dict = {}
    M.attach_media(json.loads(json.dumps(A0)), td, 60, image_cache=td / "c1", considered=cons1,
                   gallery_reach=gr0[0])
    ck("gallery_scope" not in (((cons1.get("decks") or {}).get(f.name)) or {}),
       "a caller passing no gallery_scope gets today's considered record (no new key)")

    print("== a single-record deck is unchanged ==")
    g1 = deck(td, 3, "Single Unit Deck.pdf")
    IMG.close_doc_cache()
    solo = [{"park": "Gamma", "city": "Northtown",
             "__meta": {"source_file": g1.name, "source_type": "pdf", "page_no": 0, "image_pages": [0]}}]
    sc1: list = []
    r1 = M.gallery_reach_pages([solo], td, scope_out=sc1)[0].get(str(g1), set())
    ck(r1 == {1, 2} and sc1 == [{}], f"sole claimant keeps its whole unclaimed set ({sorted(r1)})")
    IMG.close_doc_cache()

    print(f"\n{'PASS' if not FAILS else 'FAIL'} gallery_claimed_only_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
