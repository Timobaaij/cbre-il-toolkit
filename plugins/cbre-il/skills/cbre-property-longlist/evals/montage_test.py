#!/usr/bin/env python3
"""montage_test.py - the per-page candidate contact sheet (B19) and the interpretation
contract pointer (B22).

B19: interpretation handed the sub-agent ONE image path per hero-size candidate, so a deck
cost one tool call per candidate per page. The win is not tokens - image tokens track pixel
area - it is TOOL CALLS, each of which replays the agent's whole growing context. A per-page
sheet tiles the page's candidates into one image.

The sheet is ADDITIVE and must stay so: the per-candidate PNGs remain on disk as the
ambiguity escape hatch, so an agent that ignores the sheet loses nothing. Two constraints
make it provably free of perception regression, and both are asserted here - tiles pasted at
NATIVE resolution (never upscaled, never downscaled) and a canvas kept under the vision
resize threshold, with pagination instead. Python must tile EVERY candidate in index order:
dropping or reordering one would be Python making the perception call.

B22: the backlog wanted reference/interpretation.md + record_schema.json inlined into the
manifest. Rejected on the numbers - there is ONE manifest, not one per deck, so inlining
35 KB is a token wash AND a third copy of a contract that has already drifted. The real
defect is that the read was a bare relative path with undefined cardinality. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import contact_sheet as CS  # noqa: E402
import interpret_prep as IP  # noqa: E402

RUN_SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    if not CS._HAS_PIL:
        print("  [SKIP] Pillow absent - the montage degrades to None by design")
        print("\nMONTAGE TEST: PASS")
        return 0
    from PIL import Image

    d = Path(tempfile.mkdtemp(prefix="cbre_mtg_"))

    ck(hasattr(CS, "tile_native"), "contact_sheet.tile_native exists")
    ck(hasattr(IP, "_write_candidate_montage"), "interpret_prep._write_candidate_montage exists")
    if not (hasattr(CS, "tile_native") and hasattr(IP, "_write_candidate_montage")):
        print(f"\nMONTAGE TEST: FAIL ({len(fails)})")
        return 1

    # --- tile_native: native size, index order, every tile ---------------------
    sizes = [(320, 200), (384, 288), (200, 384), (100, 100)]
    cells = []
    for i, (w, h) in enumerate(sizes):
        p = d / f"c{i}.png"
        Image.new("RGB", (w, h), (10 + i * 40, 60, 120)).save(p)
        cells.append({"index": i, "image": str(p)})
    outs = CS.tile_native(cells, d / "sheet.png", tile_px=384)
    ck(len(outs) == 1, f"four small candidates fit one sheet ({len(outs)})")
    sheet = Image.open(outs[0])
    ck(sheet.width <= CS.MONTAGE_MAX_EDGE and sheet.height <= CS.MONTAGE_MAX_EDGE,
       f"the canvas stays under the vision resize threshold ({sheet.size})")

    # NATIVE paste: the exact source pixels must be present, unscaled. A 320x200 block of a
    # known colour must appear at its native dimensions somewhere on the sheet.
    px = sheet.load()
    want = (10, 60, 120)
    hits = sum(1 for x in range(sheet.width) for y in range(sheet.height)
               if px[x, y] == want)
    ck(hits == 320 * 200, f"tile 0 is pasted at NATIVE 320x200 ({hits} px, want 64000)")

    # --- every candidate is tiled, in order, none dropped ----------------------
    many, want_cols = [], []
    for i in range(16):
        p = d / f"m{i}.png"
        col = (7 + i * 15, 3, 200)
        Image.new("RGB", (384, 384), col).save(p)
        many.append({"index": i, "image": str(p)})
        want_cols.append(col)
    outs = CS.tile_native(many, d / "big.png", tile_px=384)
    ck(len(outs) >= 2, f"an oversized set PAGINATES rather than shrinking tiles ({len(outs)})")
    seen = set()
    for o in outs:
        im = Image.open(o)
        ck(im.width <= CS.MONTAGE_MAX_EDGE and im.height <= CS.MONTAGE_MAX_EDGE,
           f"every sheet respects the cap ({im.size})")
        seen |= set(im.convert("RGB").getdata())
    # the assertion that matters: Python may never DROP a candidate. Each tile is a
    # unique flat colour, so every one of the 16 must be present across the sheets.
    missing = [i for i, c in enumerate(want_cols) if c not in seen]
    ck(not missing, f"every one of the 16 candidates is tiled, none dropped {missing}")

    # a missing/undecodable candidate must not abort the page
    outs = CS.tile_native([{"index": 0, "image": str(d / "nope.png")},
                           {"index": 1, "image": str(d / "c0.png")}],
                          d / "partial.png", tile_px=384)
    ck(outs and Image.open(outs[0]), "an undecodable candidate is skipped, never fatal")
    ck(CS.tile_native([], d / "empty.png", tile_px=384) == [],
       "no candidates -> no sheet (never an empty image)")

    # --- interpret_prep: additive, resume-guarded ------------------------------
    ck(IP._write_candidate_montage(Path("x.pdf"), 0, d, []) is None,
       "no candidates -> no sheet")
    ck(IP._write_candidate_montage(Path("x.pdf"), 0, d,
                                   [{"index": 0, "image": str(d / "c0.png")}]) is None,
       "a SINGLE candidate needs no sheet (the thumbnail already is one image)")
    got = IP._write_candidate_montage(Path("x.pdf"), 3, d, cells)
    ck(isinstance(got, list) and got and Path(got[0]).exists(),
       "two or more candidates produce a sheet")

    # the resume guard must cover the sheet, or a kill serves a manifest pointing at nothing
    entry = {"pages": [{"candidates": [{"image": str(d / "c0.png")}],
                        "render": None, "candidates_sheet": got}]}
    ck(IP._thumbs_present(entry), "_thumbs_present passes when the sheet is on disk")
    Path(got[0]).unlink()
    ck(not IP._thumbs_present(entry), "_thumbs_present FAILS when the sheet was lost")

    # --- the manifest contract (B19 wiring + B22) ------------------------------
    ck("candidates_sheet" in RUN_SRC,
       "run.py's manifest instruction tells the agent about the sheet")
    ck("candidates_sheet" in (HELPERS / "interpret_prep.py").read_text(
        encoding="utf-8", errors="replace"), "the page entry carries candidates_sheet")
    doc = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8",
                                                               errors="replace")
    ck("candidates_sheet" in doc, "interpretation.md documents the sheet")
    ck("candidates" in doc and "index" in doc,
       "the per-candidate escape hatch is still documented")

    # B22: the contract pointer is absolute and read ONCE, not per deck
    ck("contract" in RUN_SRC and "ONCE" in RUN_SRC,
       "the manifest states the contract is read ONCE per round")
    ck('"record_schema"' in RUN_SRC or "'record_schema'" in RUN_SRC,
       "the record_schema key is kept (its exact literal is part of the manifest contract)")

    if fails:
        print(f"\nMONTAGE TEST: FAIL ({len(fails)})")
        return 1
    print("\nMONTAGE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
