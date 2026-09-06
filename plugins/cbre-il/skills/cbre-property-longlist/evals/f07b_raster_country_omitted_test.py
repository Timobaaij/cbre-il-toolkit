#!/usr/bin/env python3
"""f07b_raster_country_omitted_test.py - a RASTER deck entry OMITS `country` when it is unknown,
instead of handing the reader the `??` sentinel. (F7 raster half, SEAM-9)

THE DEFECT. A2 closed the text path (interpret_prep._country_kv), but run.py calls
vision_prep.prepare DIRECTLY for a raster deck, bypassing that router, and vision_prep wrote the
caller's `country` verbatim at all three of its return sites. So after the text fix a raster deck
still carried `"country": "??"`. Measured on a live run: five of seven readers said, unprompted,
that the manifest gave `??` and derived the country themselves; across seven decks that produced
three different outcomes (two spellings and one absence) and cost a broker question.

WHAT THIS PINS (vision_prep):
  1. country_kv() maps the sentinel, empty and None to an ABSENT key (not null), keeps a code, and
     keeps a two-letter code that happens to spell a member of the shared unknown family (the
     reason it does not delegate to normalize.looks_unknown);
  2. interpret_prep._country_kv is a thin alias of it, so the rule has ONE implementation;
  3. every return site of prepare() applies it: the PDF / generic site, the PPTX no-renderer site
     and the PPTX rendered-PDF site, exercised behaviourally with an unknown and a known country;
  4. the resume path cannot serve a stale sentinel: vision_prep's stamp keys the page PNGs only
     (size, mtime, dpi) and carries no entry, and a fresh call after a warm stamp still omits it;
  5. the verbatim passthrough literal is gone from the source, so a revert is visible.
Offline; renders one blank page when PyMuPDF is present, otherwise the guarded except path still
returns an entry, so the assertions hold on a renderer-less host too.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import vision_prep as VP  # noqa: E402
import interpret_prep as IP  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


TABLE = (("??", None), ("?", None), ("", None), (None, None), ("  ", None),
         ("GB", "GB"), (" pl ", "pl"), ("NA", "NA"), ("nc", "nc"))


def _blank_pdf(path: Path) -> bool:
    """One blank page, so the PDF branch has a real document to walk. False when the fitz in use
    cannot author one (the shim) - the caller then relies on the generic-suffix site instead."""
    try:
        doc = VP.fitz.open()
        doc.new_page()
        doc.save(str(path))
        doc.close()
        return path.exists() and path.stat().st_size > 0
    except Exception:
        return False


def main() -> int:
    print("== 1. the rule itself ==")
    for given, expect in TABLE:
        kv = VP.country_kv(given)
        if expect is None:
            ck(kv == {}, f"country_kv({given!r}) -> {{}} (absent key, not null)")
        else:
            ck(kv == {"country": expect}, f"country_kv({given!r}) -> {{'country': {expect!r}}} (a code is kept, stripped)")
    ck(all(IP._country_kv(g) == VP.country_kv(g) for g, _ in TABLE),
       "interpret_prep._country_kv agrees with vision_prep.country_kv on every probe (one implementation)")

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)

        print("== 2. generic / PDF return site ==")
        other = out / "deck.bin"
        other.write_bytes(b"not a brochure")
        e = VP.prepare(other, "RegionLabel", "??", out, force=True)
        ck("country" not in e and e.get("pages") == [] and e.get("region") == "RegionLabel",
           "an unknown-suffix source returns an entry with NO country key and the rest intact")
        ck("country" in VP.prepare(other, "RegionLabel", "DE", out, force=True), "a known country is kept on that site")
        pdf = out / "deck.pdf"
        if _blank_pdf(pdf):
            e = VP.prepare(pdf, "RegionLabel", "??", out, force=True)
            ck("country" not in e and len(e.get("pages") or []) == 1,
               "a real one-page PDF rasterised with an unknown country carries no country key")
            e2 = VP.prepare(pdf, "RegionLabel", "FR", out, force=True)
            ck(e2.get("country") == "FR", "the same PDF with a known country carries it")
            print("== 4. resume: a warm stamp cannot re-serve a sentinel ==")
            stamp = json.loads((out / "deck.stamp.json").read_text(encoding="utf-8"))
            ck(set(stamp) == {"size", "mtime_ns", "dpi"} and "entry" not in stamp,
               f"vision_prep's stamp keys the PNGs only (got keys {sorted(stamp)}); no entry is cached, so no "
               "sentinel can be served from cache")
            e3 = VP.prepare(pdf, "RegionLabel", "??", out, force=True)
            ck("country" not in e3 and e3.get("pages") and e3["pages"][0].get("image") == e["pages"][0].get("image"),
               "a resumed call (PNG reused) rebuilds the entry fresh and still omits the unknown country")
        else:
            print("  note  this fitz cannot author a PDF; the PDF site is covered by the source pin below")

        print("== 3. PPTX return sites ==")
        pptx = out / "deck.pptx"
        pptx.write_bytes(b"not a real pptx, and that is the point")
        orig = VP.IMG.soffice_pdf
        try:
            VP.IMG.soffice_pdf = lambda p, o: None          # no LibreOffice tier
            e = VP.prepare(pptx, "RegionLabel", "??", out, force=True)
            ck("country" not in e and "note" in e, "the no-renderer PPTX site omits the unknown country")
            ck(VP.prepare(pptx, "RegionLabel", "NL", out, force=True).get("country") == "NL",
               "the no-renderer PPTX site keeps a known country")
            if pdf.exists():
                VP.IMG.soffice_pdf = lambda p, o: pdf       # rendered-PDF tier, fed our blank page
                e = VP.prepare(pptx, "RegionLabel", "?", out, force=True)
                ck("country" not in e and len(e.get("pages") or []) == 1,
                   "the rendered-PDF PPTX site omits the unknown country")
                ck(VP.prepare(pptx, "RegionLabel", "ES", out, force=True).get("country") == "ES",
                   "the rendered-PDF PPTX site keeps a known country")
        finally:
            VP.IMG.soffice_pdf = orig

    print("== 5. the passthrough literal is gone ==")
    src = (HELPERS / "vision_prep.py").read_text(encoding="utf-8")
    ck('"country": country' not in src, "no verbatim `\"country\": country` passthrough remains in vision_prep.py")
    ck(src.count("**country_kv(country)") == 3, "all three return sites spread country_kv (a fourth site must too)")
    ck("def country_kv" in src and "return VP.country_kv" in (HELPERS / "interpret_prep.py").read_text(encoding="utf-8"),
       "the rule is defined in vision_prep (the module run.py calls directly) and interpret_prep delegates to it")

    print("STATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
