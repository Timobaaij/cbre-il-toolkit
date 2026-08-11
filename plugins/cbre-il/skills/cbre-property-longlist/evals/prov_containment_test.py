#!/usr/bin/env python3
"""prov-containment: a value citing a page must occur on that page. (B52)

Three of eleven interpretation agents shipped the manifest's FILENAME-derived cluster label as
the property's `region`, each cited to "page 1 (text interpretation)", on decks where the string
appears nowhere. Nothing mechanical caught it - it surfaced only because an honesty reviewer
chose to full-text search eleven PDFs by hand. This gate makes that diligence unnecessary.

A gate that BLOCKS must be strict WITHOUT being wrong, so every skip is asserted individually
here: the skips are the contract, not an implementation detail. Offline."""
from __future__ import annotations
import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import gate_runner as G  # noqa: E402

FAILURES = []


def ck(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


PAGE1 = "A NEW LOGISTICS FACILITY 494,750 SQ FT CAMPBELTOWN ROAD, MERSEYSIDE, CH41 9HP"
PAGE4 = "Located in the prime East Midlands logistics UK market"


def build(rows, mode="text"):
    """A work dir with a one-deck manifest (two pages) and a ledger of `rows`.
    rows: (field, value, source_file, source_locator, source_type)."""
    d = Path(tempfile.mkdtemp(prefix="cbre_prov_"))
    (d / "vision").mkdir()
    (d / "vision" / "manifest.json").write_text(json.dumps({"decks": [{
        "source_file": "deck.pdf", "mode": mode,
        "pages": [{"locator": "page 1", "text": PAGE1},
                  {"locator": "page 4", "text": PAGE4}]}]}), encoding="utf-8")
    with open(d / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["property_id", "record_type", "field", "value", "source_file",
                    "source_locator", "source_type", "extractor", "confidence",
                    "conflict_note", "verified"])
        for f, v, sf, sl, st in rows:
            w.writerow(["1", "property", f, v, sf, sl, st, "E-pdf", "High", "", "no"])
    (d / "canonical.json").write_text(json.dumps(
        {"meta": {}, "properties": [{"id": 1}], "pois": [], "regions": {}}), encoding="utf-8")
    return d


def run(d):
    class A:
        canonical = str(d / "canonical.json")
        work = str(d)
        ledger = str(d / "source_ledger.csv")
    return G.cmd_prov_containment(A())


print("The three real fabrications must BLOCK (they are all `region`):")
for val in ("Arc Royal, Campbeltown Road, Birkenhead",
            "MPC2 Magna Park Corby, 100 Kettering Road, Weldon",
            "Panattoni Doncaster 770, Blyth Road, Harworth"):
    ck(f"BLOCKS {val[:34]!r}",
       run(build([("region", val, "deck.pdf", "page 1 (text interpretation)", "pdf")])) == 1)

print("\nA genuinely page-sourced value passes:")
ck("PASSES a value printed verbatim on its cited page",
   run(build([("region", "East Midlands", "deck.pdf",
               "page 4 (text interpretation)", "pdf")])) == 0)
ck("PASSES a single-token value present on the page",
   run(build([("city", "Merseyside", "deck.pdf", "page 1 (text interpretation)", "pdf")])) == 0)
ck("PASSES when only SHORT/numeric tokens differ (they are not evidence)",
   run(build([("postcode", "CH41 9HP", "deck.pdf",
               "page 1 (text interpretation)", "pdf")])) == 0)

# THE LIVE-RUN LESSON. Marketing PDFs letter-space their headings, so the extractor legitimately
# returns "UNI T 1 WOR K S O P LI NK" and "ULTRA BOX". Comparing word-for-word flagged BOTH as
# fabrications on a real 12-property dataset. Flattening both sides to alphanumerics is what makes
# the gate usable rather than a wolf-crier.
print("\nLetter-spaced PDF text must not read as a fabrication:")
SPACED = "AVAI LABLE NOW UNI T 1 WOR K S O P LI NK , AV E LING WAY, WOR KSOP S8 1 8 AE"
d = build([("city", "Worksop", "deck.pdf", "page 1 (text interpretation)", "pdf")])
_m = json.loads((d / "vision" / "manifest.json").read_text(encoding="utf-8"))
_m["decks"][0]["pages"][0]["text"] = SPACED
(d / "vision" / "manifest.json").write_text(json.dumps(_m), encoding="utf-8")
ck("'Worksop' matches 'WOR K S O P' after flattening", run(d) == 0)
d = build([("park", "UltraBox", "deck.pdf", "page 1 (text interpretation)", "pdf")])
_m = json.loads((d / "vision" / "manifest.json").read_text(encoding="utf-8"))
_m["decks"][0]["pages"][0]["text"] = "ULTRA BOX PURFLEET | RM19 1TT TO LET"
(d / "vision" / "manifest.json").write_text(json.dumps(_m), encoding="utf-8")
ck("'UltraBox' matches 'ULTRA BOX' after flattening", run(d) == 0)

print("\nThe ADVISORY tier reports without blocking:")
ck("a `park` composed across pages is a NOTE, not a block",
   run(build([("park", "MPC 2, Magna Park Corby", "deck.pdf",
               "page 1 (text interpretation)", "pdf")])) == 0)
ck("a `city` anchored to the wrong page is a NOTE, not a block",
   run(build([("city", "Nowhereton", "deck.pdf", "page 1 (text interpretation)", "pdf")])) == 0)
ck("but the SAME miss on `region` still blocks",
   run(build([("region", "Nowhereton", "deck.pdf", "page 1 (text interpretation)", "pdf")])) == 1)

print("\nEvery skip is deliberate:")
ck("SKIPS a non-page locator (an xlsx cell has no page text)",
   run(build([("region", "Nowhere Land", "deck.pdf", "Longlist!r3", "xlsx")])) == 0)
ck("SKIPS a manual override row (an attributed human correction)",
   run(build([("region", "Nowhere Land", "deck.pdf",
               "page 1 (manual override ov-003: struck by QA)", "override")])) == 0)
ck("SKIPS a raster deck (no text layer to form an opinion from)",
   run(build([("region", "Nowhere Land", "deck.pdf",
               "page 1 (vision transcription)", "pdf")], mode="raster")) == 0)
ck("SKIPS a value with no distinctive token",
   run(build([("region", "12 A", "deck.pdf", "page 1 (text interpretation)", "pdf")])) == 0)
ck("SKIPS a field outside the targeted set (developer/landlord come from logos)",
   run(build([("developer", "Tungsten Properties", "deck.pdf",
               "page 1 (text interpretation)", "pdf")])) == 0)
ck("SKIPS a field carrying the declared escape-hatch marker",
   run(build([("region", "Nowhere Land", "deck.pdf",
               f"page 1 (text interpretation; {G.PROV_NOT_IN_TEXT}: cover logo)", "pdf")])) == 0)
ck("SKIPS a source_file with no deck in the manifest",
   run(build([("region", "Nowhere Land", "other.pdf",
               "page 1 (text interpretation)", "pdf")])) == 0)
ck("SKIPS a page number the deck does not have",
   run(build([("region", "Nowhere Land", "deck.pdf",
               "page 9 (text interpretation)", "pdf")])) == 0)

print("\nFail safe - absent evidence is never a block:")
d = build([("region", "Nowhere Land", "deck.pdf", "page 1 (text interpretation)", "pdf")])
(d / "vision" / "manifest.json").unlink()
ck("a MISSING manifest is ALL-PASS, not a block", run(d) == 0)
d = build([("region", "Nowhere Land", "deck.pdf", "page 1 (text interpretation)", "pdf")])
(d / "vision" / "manifest.json").write_text("not json", encoding="utf-8")
ck("a CORRUPT manifest is ALL-PASS, not a block", run(d) == 0)
d = build([("region", "Nowhere Land", "deck.pdf", "page 1 (text interpretation)", "pdf")])
(d / "source_ledger.csv").unlink()
ck("a MISSING ledger is ALL-PASS, not a block", run(d) == 0)

print("\nOne bad row among good ones still blocks (no averaging away a fabrication):")
ck("BLOCKS a mixed ledger when the bad row is a region",
   run(build([("region", "East Midlands", "deck.pdf", "page 4 (text interpretation)", "pdf"),
              ("city", "Merseyside", "deck.pdf", "page 1 (text interpretation)", "pdf"),
              ("region", "Invented Shire", "deck.pdf",
               "page 1 (text interpretation)", "pdf")])) == 1)

print("\nContract surface other code and the docs rely on:")
ck("only `region` BLOCKS - decided by running this against a real dataset",
   G.PROV_BLOCK_FIELDS == frozenset({"region"}), str(sorted(G.PROV_BLOCK_FIELDS)))
ck("the rest are advisory",
   G.PROV_ADVISE_FIELDS == frozenset({"city", "district", "park", "address", "postcode"}),
   str(sorted(G.PROV_ADVISE_FIELDS)))
ck("PROV_CHECK_FIELDS is their union",
   G.PROV_CHECK_FIELDS == (G.PROV_BLOCK_FIELDS | G.PROV_ADVISE_FIELDS))
ck("the escape-hatch marker is the documented string",
   G.PROV_NOT_IN_TEXT == "not in text layer")
ck("the contract tells agents about the marker",
   G.PROV_NOT_IN_TEXT in (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8"))
ck("the contract tells agents the cluster label is not evidence",
   "cluster_label` is NOT evidence" in
   (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8"))

print()
if FAILURES:
    print(f"PROV CONTAINMENT TEST: FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("PROV CONTAINMENT TEST: PASS (page-cited values verified; every skip deliberate)")
