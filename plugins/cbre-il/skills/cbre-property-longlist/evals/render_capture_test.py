#!/usr/bin/env python3
"""G-visual must be able to SEE the page it judges. (B59)

render_qa captured a 1440x1000 viewport with full_page=False, so the reviewer reported - unprompted
- that the card grid and the Leaflet map are cut off at the fold, that map.png was
PIXEL-IDENTICAL to grid.png apart from the tab highlight, and that no Compare or Flyover captures
exist at all. A blocking-capable vision gate that can only ever say "fine above the fold" is the
same class of defect as a gate that cannot fail.

The duplicate detector is the important half: identical bytes across two views is the TELL that a
switchView silently failed, and today that is invisible - the reviewer is handed the grid twice
and told one of them is the map. Pure logic, no browser needed. Offline."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import render_qa as R  # noqa: E402

FAILURES = []


def ck(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


d = Path(tempfile.mkdtemp(prefix="cbre_rq_"))
(d / "grid.png").write_bytes(b"AAA")
(d / "map.png").write_bytes(b"AAA")        # the live symptom: identical to grid
(d / "compare.png").write_bytes(b"BBB")

print("capture_report - identical views are the tell of a failed switch:")
notes = R.capture_report({"grid": d / "grid.png", "map": d / "map.png",
                          "compare": d / "compare.png"})
joined = " | ".join(notes)
ck("identical captures are reported", any("grid" in n and "map" in n for n in notes), joined)
ck("...and the note explains what it MEANS, not just that bytes matched",
   "switch" in joined.lower(), joined)
ck("a genuinely different view is not reported", "compare" not in joined, joined)

(d / "map.png").write_bytes(b"CCC")
ck("all-distinct captures produce no notes",
   R.capture_report({"grid": d / "grid.png", "map": d / "map.png",
                     "compare": d / "compare.png"}) == [])
ck("a missing capture is skipped, never a crash",
   R.capture_report({"grid": d / "grid.png", "ghost": d / "nope.png"}) == [])
ck("an empty mapping is safe", R.capture_report({}) == [])
ck("three identical views report against the first, not each other twice",
   len(R.capture_report({"a": d / "grid.png", "b": d / "grid.png",
                         "c": d / "grid.png"})) == 2)

print("\nWhat render_qa actually asks the browser for:")
src = (ROOT / "helpers" / "render_qa.py").read_text(encoding="utf-8")
for view in ("grid", "map", "compare", "flyover"):
    ck(f"captures the {view} view", f'"{view}"' in src or f"'{view}'" in src)
ck("the scrolling views are captured FULL PAGE (the fold was the whole problem)",
   "full_page=True" in src)
ck("the modal is NOT full page (it is an overlay; full page would shoot the page behind)",
   "full_page=False" in src or "modal.png" in src)
ck("the duplicate detector is wired into the run", "capture_report(" in src)
ck("the summary says which views were captured, so a missing one is visible",
   "views=" in src)

print()
if FAILURES:
    print(f"RENDER CAPTURE TEST: FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("RENDER CAPTURE TEST: PASS (all four views, full page where it matters, duplicates surfaced)")
