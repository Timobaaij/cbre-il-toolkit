#!/usr/bin/env python3
"""match_footing_test.py - the size veto never fires on an unknown footing. (B10)

match._area returned the raw warehouseArea float with no unit, and merge does not convert
units until AFTER dedupe. So a sq ft record and a sq m record of the SAME building are
90.7% apart, tripped the >15% hard block, and were classed `forbidden` - and grey_pairs
EXCLUDES forbidden, so the pair was never written to match_candidates.json and the LLM was
never asked. A hard veto that the adjudicator cannot even see is the worst shape available.

The backlog filed this as basis-blindness (GIA gross vs net). That is real but weaker: a
pure GIA-vs-net gap is 5-12%, i.e. UNDER the threshold. Unit-blindness is what fires.

Python converts when both units are stated and REFUSES to compare when the footing is
unknown; it never decides sameness - refusing sends the pair to the LLM, which is where
that judgement belongs. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import match as M  # noqa: E402


def _r(src, area=None, unit=None, park="Raven Park", city="Corby", dev="Prologis"):
    r = {"park": park, "city": city, "developer": dev, "country": "GB",
         "__meta": {"source_file": src, "source_type": "pdf"}}
    if area is not None:
        r["warehouseArea"] = area
    if unit:
        r["areaUnit"] = unit
    return r


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # 12,000 sq m == 129,167 sq ft - the SAME building described twice
    sqm = _r("deck.pdf", 12000, "sq m")
    sqft = _r("tracker.xlsx", 129167, "sq ft")

    aa, ba = M._area_pair(sqm, sqft)
    ck(aa is not None and abs(aa - ba) / max(aa, ba) < 0.02,
       f"a mixed-unit pair converts to within 2% {ascii(str((aa, ba)))}")
    ck(M.pair_class(sqm, sqft) != "forbidden",
       f"...so it is NOT forbidden ({M.pair_class(sqm, sqft)})")
    ck(M.pair_class(sqm, sqft) in ("auto", "grey"),
       "...and it reaches the matcher's decidable tiers")
    ck(any(g for g in M.grey_pairs([sqm, sqft])) or M.pair_class(sqm, sqft) == "auto",
       "the LLM can actually see it (grey_pairs, or already auto-merged)")
    # I9 named the signal: a shared city is no longer sufficient on its own, so record
    # WHICH signal keeps this pair visible - the shared distinctive park token 'raven'
    # (and a fuzzy key of 100). Pinning the carrier means a future pre-filter change that
    # would re-hide this pair fails HERE, where the reason is written down.
    _ct = M._grey_city_tokens(sqm, sqft)
    ck("raven" in (M._grey_tokens(sqm["park"], _ct) & M._grey_tokens(sqft["park"], _ct)),
       "...kept visible by the shared park token 'raven', not by the shared city (I9)")

    # a GENUINE same-unit conflict must still hard-block
    big = _r("a.pdf", 50000, "sq m")
    small = _r("b.pdf", 12000, "sq m")
    ck(M.pair_class(big, small) == "forbidden",
       f"a real >15% same-unit conflict is STILL forbidden ({M.pair_class(big, small)})")

    # unit-silent on one side: the footing is unknown, so a gap is not evidence
    silent = _r("c.pdf", 129167)                       # no areaUnit
    ck(M._area_pair(sqm, silent) == (None, None),
       "one silent side -> not comparable")
    ck(M.pair_class(sqm, silent) != "forbidden",
       "...so an unknown footing never hard-blocks")

    # both silent: today's behaviour, unchanged
    s1, s2 = _r("d.pdf", 12000), _r("e.pdf", 50000)
    ck(M._area_pair(s1, s2) == (12000, 50000), "both silent -> compared as before")
    ck(M.pair_class(s1, s2) == "forbidden",
       "...and a >15% gap between two silent records still blocks (no behaviour change)")

    # same unit stated on both: unchanged
    ck(M._area_pair(_r("f.pdf", 100, "sq ft"), _r("g.pdf", 110, "sq ft")) == (100, 110),
       "same stated unit -> compared directly")

    # an unrecognised unit pairing must refuse rather than guess
    ck(M._area_pair(_r("h.pdf", 5, "acres"), _r("i.pdf", 12000, "sq m")) == (None, None),
       "an unrecognised unit pairing is not comparable")

    # a missing area on either side is still simply not a conflict
    ck(M._area_pair(_r("j.pdf"), sqft) == (None, None), "a missing area is not comparable")

    if fails:
        print(f"\nMATCH FOOTING TEST: FAIL ({len(fails)})")
        return 1
    print("\nMATCH FOOTING TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
