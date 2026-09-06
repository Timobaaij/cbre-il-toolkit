#!/usr/bin/env python3
"""f09_prov_norm_test.py - prov-containment compares a NORMALISED form on BOTH sides, and the
loosening that buys is measured here, probe by probe.

THE DEFECT, measured on 3 of 7 live decks. One deck set its display type letter-spaced, so the
text layer held spaced-out digits and words on every headline value; three decks rendered a
currency symbol as U+FFFD. Readers transcribed correctly, disclosed the divergence in the field's
own `prov` in prose, and still could not satisfy a raw comparison. Not a corpus quirk:
letter-spaced display type is standard in property marketing and a broken ToUnicode map is
common in PDFs from design tools.

THE FIX: `_prov_norm` is applied to the value AND the page before they meet: U+FFFD dropped,
cp1252-of-UTF-8 mojibake decoded back (per token, round-trip-checked, so a genuine 'château'
survives), NFKD compatibility folding (a U+FB01 ligature becomes 'fi'), diacritics stripped,
case-folded, whitespace collapsed. The gate asks "did the reader invent this string", not "did
the reader reproduce the kerning or the font's glyph map".

THE LOOSENING, STATED. Against the pre-change comparison (kept verbatim below as OLD), a probe
table of value/page pairs is run through both. This eval asserts the exact set of probes whose
verdict MOVED, and that every move is a garbled spelling now matching its clean form. Nothing
that names a different word moves: 'North Valley' still does not match 'South Valley', a
truncated page does not match a longer value, a fabricated region still fails. The one move a
reader could argue with is diacritic-insensitivity ('Ponte' now matches a page reading
'Pônte'); that is the same fold that lets an accented name on the page match its unaccented
transcription, and it is deliberate.
Offline.
"""
from __future__ import annotations

import csv
import io
import contextlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import gate_runner as G  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


# ---- the PRE-CHANGE comparison, verbatim, so the loosening is measured against it -------
_OLD_TOKEN = re.compile(r"[A-Za-z]{4,}")
_OLD_STRIP = re.compile(r"[^a-z0-9]+")


def old_verdict(value, page):
    want = {t.lower() for t in _OLD_TOKEN.findall(str(value))}
    if not want:
        return None
    flat = _OLD_STRIP.sub("", str(page).lower())
    return all(t in flat for t in want)


def new_verdict(value, page):
    want = G._prov_tokens(value)
    if not want:
        return None
    flat = G._prov_flat(page)
    return all(t in flat for t in want)


# (value, page text, must match, note). Invented places only.
PROBES = [
    ("Westbrook Link", "UNI T 1 WES T B R O O K LI NK", True, "letter-spaced page (already handled)"),
    ("Northgate", "North gate", True, "one stray space on the page (already handled)"),
    ("Fairfield Business Park", "FAIRﬁELD BUSINESS PARK", True, "fi LIGATURE on the page"),
    ("Saint-Eloi", "SAINT-ÉLOI", True, "accent on the page, none in the value"),
    ("Saint-Éloi", "Saint-Eloi", True, "accent in the value, none on the page"),
    ("São Marco Logistics", "SÃ£o Marco Logistics", True, "MOJIBAKE on the page"),
    ("Château Park", "Château Park", True, "a genuine circumflex survives the mojibake probe"),
    ("North Valley", "�North Valley�", True, "replacement characters around the value"),
    ("Ponte Est", "Pônte Est", True, "diacritic-insensitive: a stray accent on the page"),
    ("Kestrel Reach Park", "A NEW LOGISTICS FACILITY RIVERSIDE ROAD", False, "a fabricated region"),
    ("North Valley", "South Valley logistics market", False, "a DIFFERENT word must not match"),
    ("Harborfield", "Harborfiel", False, "a truncated page must not match a longer value"),
    ("Nuovo Polo", "Nuovo Polo Logistico", True, "value inside a longer page run"),
    ("Ford Park", "Stanford Park", True, "PRE-EXISTING looseness: substring match, both sides"),
    ("Stanford", "Stanford", True, "identity"),
]
EXPECT_MOVED = {"Fairfield Business Park", "Saint-Eloi", "Ponte Est"}


def main() -> int:
    print("1. the probe table: old verdict, new verdict, expected")
    moved, old_wrong, new_wrong = set(), [], []
    for value, page, want, note in PROBES:
        o, n = old_verdict(value, page), new_verdict(value, page)
        if o != n:
            moved.add(value)
        if o is not None and o != want:
            old_wrong.append(value)
        if n is not None and n != want:
            new_wrong.append(value)
        # ascii() rather than !r: these probes are DELIBERATELY non-ASCII (a ligature, an
        # accented page, mojibake), and a console whose default encoding is not UTF-8 raises
        # UnicodeEncodeError on the print itself, which killed the whole suite runner rather
        # than failing one eval. That is the same class of defect as F8 one level out, so the
        # eval that proves the fix should not reproduce it in its own output.
        print(f"     {'MOVED' if o != n else '     '} old={o!s:5} new={n!s:5} want={want!s:5}  "
              f"{ascii(value)} vs {ascii(page)}  ({note})")
    ck(not new_wrong, f"every probe gets the wanted verdict after the change (wrong: {new_wrong})")
    ck(moved == EXPECT_MOVED,
       f"exactly {len(EXPECT_MOVED)} of {len(PROBES)} probes move, all of them garbled-spelling "
       f"cases now matching their clean form: {sorted(moved)}")
    ck(set(old_wrong) == EXPECT_MOVED,
       "every probe the OLD comparison got wrong (the ligature, the accented page, the stray "
       "accent) was a false REJECTION of a correct transcription, which is the live defect; the "
       "old comparison never wrongly ACCEPTED anything, and neither does the new one")
    ck(not any(v in moved for v, _, want, _ in PROBES if not want),
       "no probe that must NOT match moved: a different word, a truncated page and a fabricated "
       "region still fail")

    print("2. the normaliser itself")
    ck(G._prov_norm("SÃ£o  Marco") == "sao marco", "mojibake decoded, then diacritics stripped, whitespace collapsed")
    ck(G._prov_norm("Château") == "chateau", "a genuine circumflex is kept through the mojibake probe, then stripped as a diacritic")
    ck(G._prov_norm("FAIRﬁELD") == "fairfield", "NFKD expands the fi ligature")
    ck(G._prov_norm("�12.50 per sq ft") == "12.50 per sq ft", "U+FFFD is dropped, digits survive")
    ck(G._prov_norm("1 2 , 5 0 0") == "1 2 , 5 0 0" and G._prov_flat("1 2 , 5 0 0") == "12500",
       "letter-spaced digits: the normalised form keeps the spaces, the FLAT form is the clean number")
    ck(G._prov_flat("12,500 sq ft") == G._prov_flat("1 2 , 5 0 0  S Q  F T"),
       "so a spaced-out number and its clean form are the same flat string (what seen_as compares)")
    ck(G._prov_tokens("Saint-Éloi, Vallée") == {"saint", "eloi", "vallee"},
       "tokens are taken from the normalised value, so the accented word is one whole token")
    ck(G._prov_tokens("A1 M1 J19") == set(), "no 4-letter alphabetic run: no tokens, no evidence")

    print("3. end to end: a clean transcription of a ligatured page passes the real gate")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "vision").mkdir()
        (d / "vision" / "manifest.json").write_text(json.dumps({"decks": [{
            "source_file": "deck.pdf", "mode": "text",
            "pages": [{"locator": "page 2", "text": "LOCATED IN THE FAIRﬁELD CITY REGION, SÃ£o Marco Business Park"}]}]}),
            encoding="utf-8")
        with open(d / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["property_id", "record_type", "field", "value", "source_file",
                        "source_locator", "source_type", "extractor", "confidence", "conflict_note", "verified"])
            w.writerow(["1", "property", "region", "Fairfield City Region", "deck.pdf", "page 2 (text interpretation)", "pdf", "E", "High", "", "no"])
            w.writerow(["1", "property", "park", "São Marco Business Park", "deck.pdf", "page 2 (text interpretation)", "pdf", "E", "High", "", "no"])
            w.writerow(["2", "property", "region", "South Valley", "deck.pdf", "page 2 (text interpretation)", "pdf", "E", "High", "", "no"])
        (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": [{"id": 1}, {"id": 2}], "pois": [], "regions": {}}), encoding="utf-8")

        class A:
            canonical = str(d / "canonical.json"); work = str(d); ledger = str(d / "source_ledger.csv")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = G.cmd_prov_containment(A())
        out = buf.getvalue()
        ck(rc == 1, "the gate still BLOCKS: property 2's region is not on the page")
        ck("property=2 field=region" in out and "property=1" not in out,
           "...and ONLY that one: the ligatured region and the mojibake park both verify clean")
        ck(old_verdict("Fairfield City Region", "LOCATED IN THE FAIRﬁELD CITY REGION") is False,
           "(the OLD comparison would have blocked property 1's correct region too)")

    print()
    if FAILS:
        print(f"F09 PROV NORM TEST: FAIL ({len(FAILS)})")
        return 1
    print("F09 PROV NORM TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
