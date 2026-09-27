#!/usr/bin/env python3
"""reader_data_pages_rule_test - the reader completeness rule (2026-09-26 A/B test).

On the 2026-09-26 A/B re-read of two real decks with the condensed contract (fix 1.1) and the
per-deck contact sheets (fix 1.2), both readers produced correct figures but dropped whole pages
of facts the earlier readers had captured. No contract rule had been lost; the pages simply read
as marketing. The fix is a load-bearing reminder in BOTH reader templates: EVERY page is a data
page whatever its topic, and a final no-cost SWEEP of every page adds any stated fact that is in
no field yet.

The rule must stay TOPIC-FREE (2026-09-27 review): the first wording named five page topics taken
from that run's misses, and a list in a prompt reads as the specification - a page about a topic
it did not name (leisure, security, power, planning, flood risk...) would have read as optional.
Examples may appear only as illustrations, explicitly "never a limit".

Pins: both templates carry the topic-free rule and the sweep; the examples are marked as
illustrations; the old topic-list headline is gone; the rule sits in the common half (identical
for every deck); both rendered prompts carry it exactly once.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "helpers"))
import prompts_render as PR  # noqa: E402

FAILS = 0
RULE = "EVERY PAGE IS A DATA PAGE, whatever its topic"


def ck(cond, msg):
    global FAILS
    print(("[PASS] " if cond else "[FAIL] ") + msg)
    if not cond:
        FAILS += 1


for kind in ("reader-text", "reader-raster"):
    tpl = (HERE / "prompts" / f"{kind}.md").read_text(encoding="utf-8")
    flat = " ".join(tpl.split())
    ck(RULE in flat, f"{kind}: template states the topic-free rule ({RULE!r})")
    ck("never a limit" in flat, f"{kind}: examples are marked as illustrations, never a limit")
    ck("SWEEP every page" in flat, f"{kind}: template asks for the final completeness sweep")
    ck("ARE DATA PAGES" not in flat,
       f"{kind}: the old topic-list headline ('... PAGES ARE DATA PAGES') is gone")
    split = tpl.split("COMMON-SPLIT", 1)
    if len(split) == 2:
        ck(RULE not in " ".join(split[0].split()) and RULE in " ".join(split[1].split()),
           f"{kind}: the rule sits in the COMMON half (same for every deck), not the per-deck head")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "prompts").mkdir()
        slots = {"DECK_NAME": "deck.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": "3",
                 "COUNTRY": "not stated", "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
                 "OUTPUT_PATH": str(work / "extract" / "deck_vision.json")}
        try:
            text = PR.render(kind, slots)
        except Exception as e:  # noqa: BLE001
            text = ""
            ck(False, f"{kind}: render raised {type(e).__name__}: {e}")
        ck(" ".join(text.split()).count(RULE) == 1,
           f"{kind}: the rendered prompt carries the rule exactly once")

print(f"\nREADER DATA PAGES RULE TEST: {'PASS' if not FAILS else 'FAIL'}"
      + (f" ({FAILS})" if FAILS else ""))
sys.exit(1 if FAILS else 0)
