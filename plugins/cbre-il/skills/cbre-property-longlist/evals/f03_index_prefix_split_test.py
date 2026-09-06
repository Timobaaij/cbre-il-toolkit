#!/usr/bin/env python3
"""f03_index_prefix_split_test.py - numbered broker exports split without the agent. (F3)

THE LIVE FAILURE. A corpus of seven brochures named `<index><sep><name>` ("01_Riverside_Park",
"02-Harbour-Gate") had NO region delimiter, so infer_cluster's spaced-dash splitter fell
through to the whole-stem fallback for every one of them: 7 of 7 stems were low-confidence,
and the "optional" cluster-label sub-agent job took the entire corpus and cost a full agent
round trip. The agent's own diagnosis was the shape itself. A leading numeric index is one of
the most common ways a broker exports a numbered set, so for that whole family of corpora the
optional job was not optional.

Pinned here, against a representative stem set (all names invented):
  A. every shape the regex handled BEFORE still resolves to the same label, high confidence;
  B. the index-prefixed shapes now resolve WITHOUT the agent, and the index is stripped
     first so a remainder with a spaced dash or a known-city tail is judged as before;
  C. what genuinely cannot be split stays LOW and goes to the agent - the fix deletes
     unnecessary work, it does not guess: a 4-digit run is a year, "12-14 Station Road"
     is an address range, a digit + space is a house number;
  D. the measured before/after: the agent fraction on this set falls from 12/21 to 6/21.
This is a routing/scaffold label only; nothing here reaches a card. Offline.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import intake as IN  # noqa: E402

fails: list[str] = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


KNOWN = {"westford": "XX"}  # one invented known city so the known-tail rule is exercised


def split(stem: str):
    region, country, conf = IN.infer_cluster(stem + ".pdf", KNOWN)
    return region, conf


# ---------------------------------------------------------------- A. no regression
for stem, want in (("Options - Northgate", "Northgate"),
                   ("New stock - Northgate", "Northgate"),
                   ("Portfolio Options - Westford - FINAL", "Westford"),
                   ("Options - St. Aldern", "St. Aldern"),
                   ("Northgate - FINAL", "Northgate"),
                   ("Options-Westford", "Westford"),
                   ("Options - Northgate - v2", "Northgate")):
    r, c = split(stem)
    ck((r, c) == (want, "high"), f"A: {stem!r} -> {want!r} high, as before (got {r!r} {c})")

# ---------------------------------------------------------------- B. numbered exports
for stem, want in (("01_Riverside_Park", "Riverside Park"),
                   ("02-Harbour-Gate-Estate", "Harbour Gate Estate"),
                   ("3_Millbrook Distribution Centre", "Millbrook Distribution Centre"),
                   ("05_Unit_7_Kingsway_v2", "Unit 7 Kingsway"),
                   ("06-Northfield_Logistics-Hub", "Northfield Logistics-Hub"),
                   ("08_CTPark_Brookvale-South", "CTPark Brookvale-South"),
                   ("07 - Riverside_Park", "Riverside_Park")):
    r, c = split(stem)
    ck((r, c) == (want, "high"), f"B: {stem!r} -> {want!r} high (got {r!r} {c})")
# the index is stripped FIRST, so the remainder is judged exactly as an un-numbered stem
ck(split("04_Options - Westford") == ("Westford", "high"),
   "B: index + spaced dash -> the spaced-dash split still wins")
ck(split("007_Options-Westford") == ("Westford", "high"),
   "B: index + known-city tail -> the known-tail rule still wins over the word-separated name")
ck(split("09_Options_Westford") == ("Westford", "high"),
   "B: the known-tail rule now reads an underscore tail too")
# the word separator is whichever character does the separating; a name that already
# uses spaces keeps its hyphens (a hyphenated park is ONE park, the S6 rule)
ck(split("08_CTPark_Brookvale-South")[0] == "CTPark Brookvale-South",
   "B: underscores separate words, the hyphen inside the name is kept")
ck(split("02-Harbour-Gate-Estate")[0] == "Harbour Gate Estate",
   "B: with no underscores and no spaces the hyphens ARE the word separators")
# a stripped label is a real cluster key in discover(), grouping two numbered decks of one
# estate, and country resolves from the label exactly as for any other label
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "01_Riverside_Park.pdf").write_bytes(b"a")
    (root / "02_Riverside_Park.pptx").write_bytes(b"b")
    (root / "03_Options-Fenwick.pdf").write_bytes(b"c")
    inv = IN.discover(root)
cl = inv["clusters"]
ck(cl.get("Riverside Park", {}).get("pdfs") == ["01_Riverside_Park.pdf"]
   and cl.get("Riverside Park", {}).get("pptxs") == ["02_Riverside_Park.pptx"]
   and cl["Riverside Park"].get("confidence") == "high",
   "B: two numbered decks of one estate cluster under ONE stripped label, high confidence")
ck(sorted(cl["Riverside Park"]["stems"]) == ["01_Riverside_Park", "02_Riverside_Park"],
   "B: the cluster still carries the RAW stems (the label cache keys on them)")
ck("Options Fenwick" in cl and cl["Options Fenwick"]["confidence"] == "high",
   "B: an indexed stem whose remainder has an UNKNOWN unspaced tail is still a name, not the agent's")

# ---------------------------------------------------------------- C. still the agent's
for stem in ("Brochure", "Availability Schedule", "Options-Fenwick",
             "Greyfield Brookvale-South", "12-14 Station Road", "2024_Availability",
             "2 Riverside Road", "01_", "01-"):
    r, c = split(stem)
    ck((r, c) == (stem, "low"), f"C: {stem!r} stays LOW with the whole stem as label (got {r!r} {c})")
ck(IN._INDEX.match("12-14 Station Road") is None,
   "C: an address RANGE is not an index (the remainder must start with a letter)")
ck(IN._INDEX.match("2024_Availability") is None, "C: a 4-digit run is a year, not an index")
ck(IN._INDEX.match("2 Riverside Road") is None, "C: digit + space is a house number, not an index")

# ---------------------------------------------------------------- D. the measurement
SET = [("Options - Northgate", "A"), ("New stock - Northgate", "A"),
       ("Portfolio Options - Westford - FINAL", "A"), ("Options - St. Aldern", "A"),
       ("Northgate - FINAL", "A"), ("Options-Westford", "A"), ("Options - Northgate - v2", "A"),
       ("01_Riverside_Park", "B"), ("02-Harbour-Gate-Estate", "B"),
       ("3_Millbrook Distribution Centre", "B"), ("04_Options - Westford", "B"),
       ("05_Unit_7_Kingsway_v2", "B"), ("06-Northfield_Logistics-Hub", "B"),
       ("007_Options-Westford", "B"), ("08_CTPark_Brookvale-South", "B"),
       ("Brochure", "C"), ("Availability Schedule", "C"), ("Options-Fenwick", "C"),
       ("Greyfield Brookvale-South", "C"), ("12-14 Station Road", "C"), ("2024_Availability", "C")]
low = sum(1 for s, _g in SET if split(s)[1] == "low")
ck(low == 6, f"D: {low}/{len(SET)} of the representative set still needs the agent (was 12/21 "
             f"before F3; the 6 are exactly group C)")
ck(all(split(s)[1] == "low" for s, g in SET if g == "C")
   and all(split(s)[1] == "high" for s, g in SET if g != "C"),
   "D: every remaining low is a genuinely unsplittable stem, and nothing splittable is low")

print("\nF03 INDEX PREFIX SPLIT TEST: " + ("FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
