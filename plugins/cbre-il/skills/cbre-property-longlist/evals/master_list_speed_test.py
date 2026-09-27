#!/usr/bin/env python3
"""master_list_speed_test.py - the master-list stage stops paying for work it throws away.
(2026-09-26 test run, fix 2.1.)

THE COST (profiled on the live run). A `--from repairs` pass spent 12.6 s of a 16 s "master list"
segment in build_auto: `font_grouped_blocks` parsed EVERY page of 23 decks to keep page 1
(11.4 s), and the .msg index re-parsed 16 messages - after which the rows were discarded.

WHAT THIS PINS
  (a) font_grouped_blocks(p, max_pages=1) returns exactly the page-1 groups of the full read
      (a real 3-page PDF made with PyMuPDF), and the default still reads every page;
  (b) build_auto(corpus_key=...) caches: an identical second call reads no first page and
      returns an equal payload; a different corpus key, a changed record, a changed deck set,
      or a missing email_bodies.md (when the run has emails) rebuilds; corpus_key="" keeps
      today's always-rebuild behaviour and writes no key.
The run.py wiring (`_ml_skip`, `_first_page_text(max_pages=1)`, passing corpus_key) is IA-7c's
and is pinned there.
"""
from __future__ import annotations

import email.message
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import master_list as ML  # noqa: E402

FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _rec(park, loc, area=10000):
    return {"park": park, "city": "Sometown", "warehouseArea": area,
            "__meta": {"source_file": "Tracker.xlsx", "source_type": "xlsx",
                       "prov": {"park": f"{loc} (tracker)"}}}


def main() -> int:
    print("== (a) font_grouped_blocks(max_pages=1) == the page-1 groups of a full read ==")
    try:
        import extract_pdf as XP
        fitz = XP.fitz
        with tempfile.TemporaryDirectory(prefix="cbre_mlspeed_") as td:
            p = Path(td) / "three pages.pdf"
            doc = fitz.open()
            for i in range(3):
                pg = doc.new_page()
                pg.insert_text((72, 72), f"RIVERSIDE PARK page {i + 1}", fontsize=20)
                pg.insert_text((72, 120), f"Body text line on page {i + 1}", fontsize=10)
            doc.save(str(p))
            doc.close()
            full = XP.font_grouped_blocks(p)
            one = XP.font_grouped_blocks(p, max_pages=1)
            junk = XP.font_grouped_blocks(p, max_pages="junk")
        if not full:
            print("  [PASS] (no text-layout engine here - font_grouped_blocks is [] by contract)")
        else:
            ck(sorted({b["page"] for b in full}) == [1, 2, 3], "the default still reads every page")
            ck(one == [b for b in full if b["page"] == 1] and one,
               f"max_pages=1 is exactly the page-1 groups ({len(one)} group(s))")
            ck(junk == full, "a nonsense limit degrades to the full read")
    except Exception as e:  # noqa: BLE001
        ck(False, f"font_grouped_blocks fixture failed: {type(e).__name__}: {e}")

    print("== (b) the candidate cache ==")
    calls: list = []

    def fpt(q):
        calls.append(Path(str(q)).name)
        return "RIVERSIDE PARK\nSometown AB1 2CD\n12,000 sq m"

    recs = {"Tracker.xlsx": [_rec("Riverside Park", "Sheet1!B5")]}
    clusters = {"Sometown": {"pdfs": ["a.pdf", "b.pdf"]}}
    w = Path(tempfile.mkdtemp(prefix="cbre_mlcache_"))
    p1 = ML.build_auto(w, recs, clusters, w, fpt, corpus_key="k")
    n1 = len(calls)
    ck(n1 == 2 and p1.get("candidates_key"), f"the first call reads each deck ({n1}) and stores a key")
    p2 = ML.build_auto(w, recs, clusters, w, fpt, corpus_key="k")
    ck(len(calls) == n1, f"an identical second call reads NO first page ({len(calls) - n1} read)")
    ck(p2 == p1, "...and returns an equal payload")
    ML.build_auto(w, recs, clusters, w, fpt, corpus_key="k2")
    ck(len(calls) == n1 + 2, "a different corpus key rebuilds")
    n2 = len(calls)
    recs2 = {"Tracker.xlsx": [_rec("Riverside Park", "Sheet1!B5", 11000)]}
    ML.build_auto(w, recs2, clusters, w, fpt, corpus_key="k2")
    ck(len(calls) == n2 + 2, "a changed record rebuilds")
    n3 = len(calls)
    ML.build_auto(w, recs2, {"Sometown": {"pdfs": ["a.pdf"]}, "Other": {"pdfs": ["b.pdf"]}},
                  w, fpt, corpus_key="k2")
    ck(len(calls) == n3 + 2, "a regrouped deck set rebuilds (the cluster label is on the row)")
    n4 = len(calls)
    p0 = ML.build_auto(w, recs2, clusters, w, fpt)
    ML.build_auto(w, recs2, clusters, w, fpt)
    ck(len(calls) == n4 + 4 and "candidates_key" not in p0,
       "corpus_key='' keeps today's behaviour: always rebuilt, no key written")

    print("== (b2) with emails, the cache also needs email_bodies.md ==")
    with tempfile.TemporaryDirectory(prefix="cbre_mlcache2_") as td:
        inputs, work = Path(td) / "in", Path(td) / "work"
        inputs.mkdir()
        work.mkdir()
        m = email.message.EmailMessage()
        m["Subject"], m["From"] = "Offer", "Alex Morgan <alex@example-agents.com>"
        m["Date"] = "Mon, 07 Sep 2026 09:00:00 +0100"
        m.set_content("Riverside Park, 12,000 sq m.")
        (inputs / "offer.eml").write_bytes(m.as_bytes())
        calls.clear()
        ML.build_auto(work, {}, {"S": {"pdfs": ["a.pdf"]}}, inputs, fpt, emails=["offer.eml"],
                      corpus_key="k")
        ML.build_auto(work, {}, {"S": {"pdfs": ["a.pdf"]}}, inputs, fpt, emails=["offer.eml"],
                      corpus_key="k")
        ck(len(calls) == 1 and (work / ML.EMAIL_BODIES).exists(),
           "with the bodies file present the second call is a cache hit")
        (work / ML.EMAIL_BODIES).unlink()
        ML.build_auto(work, {}, {"S": {"pdfs": ["a.pdf"]}}, inputs, fpt, emails=["offer.eml"],
                      corpus_key="k")
        ck(len(calls) == 2 and (work / ML.EMAIL_BODIES).exists(),
           "a missing email_bodies.md rebuilds - and writes it again")
        auto = json.loads((work / ML.AUTO_CANDIDATES).read_text(encoding="utf-8"))
        ck(auto.get("candidates_key") and len(auto.get("emails") or []) == 1,
           "the stored payload carries its key and the email index")

    print()
    if FAILS:
        print(f"MASTER LIST SPEED TEST: FAIL ({len(FAILS)})")
        return 1
    print("MASTER LIST SPEED TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
