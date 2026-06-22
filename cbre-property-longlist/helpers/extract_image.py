#!/usr/bin/env python3
"""extract_image.py - turn standalone, property-named images into bindable assets.

Filenames are expected to encode the property (city / developer / park), e.g.
"Panattoni_Pilsen_West_III.jpg" or "Soskut - WING.png". The parsed tokens let
match.py bind each image to the right property record; the image is compressed
to a data URI ready for the 'photo' (or 'plan') field. HEIC supported.

Tokenisation splits the filename stem on separators (space, _, -, ., en/em
dashes) and drops pure-digit / single-char fragments; the surviving tokens are
the fuzzy match hints `match.py` binds against city / developer / park.

CLI:
  python extract_image.py <folder> [--out assets.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import images as IMG

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
PLAN_HINT = re.compile(r"\b(plan|floor|layout|site)\b", re.I)


def parse_tokens(stem: str) -> list[str]:
    parts = re.split(r"[ _\-–—\.]+", stem)
    return [p for p in parts if p and not p.isdigit() and len(p) > 1]


def extract(folder: Path, budget_kb: int = IMG.DEFAULT_BUDGET_KB) -> list[dict]:
    assets = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in EXTS:
            continue
        try:
            img = IMG._open(p.read_bytes())
            if img is None:  # undecodable - an explicit stub, never a silent drop:
                # the broker's photo must surface in the Gaps Report, not vanish.
                # Tailor the hint to the extension so a non-HEIC failure is not
                # handed misleading 'install pillow-heif' advice.
                if p.suffix.lower() in {".heic", ".heif"}:
                    err = "undecodable HEIC/HEIF image (missing codec - pip install pillow-heif)"
                else:
                    err = "undecodable image (corrupt or unsupported encoding)"
                assets.append({"kind": "unreadable", "tokens": parse_tokens(p.stem),
                               "error": err,
                               "__meta": {"source_file": p.name, "source_type": "image"}})
                continue
            kind = "plan" if PLAN_HINT.search(p.stem) else "photo"
            edge = IMG.PLAN_MAX_EDGE if kind == "plan" else IMG.HERO_MAX_EDGE
            assets.append({
                "kind": kind,
                "tokens": parse_tokens(p.stem),
                "data_uri": IMG.to_data_uri(IMG.compress(img, edge, budget_kb)),
                "__meta": {"source_file": p.name, "source_type": "image",
                           "locator_base": "file"},
            })
        except Exception as e:
            assets.append({"kind": "unreadable", "tokens": parse_tokens(p.stem),
                           "error": str(e),
                           "__meta": {"source_file": p.name, "source_type": "image"}})
    return assets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out")
    args = ap.parse_args()
    res = extract(Path(args.folder))
    summary = [{k: v for k, v in a.items() if k != "data_uri"} for a in res]
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print(f"OK {len(res)} image assets -> {args.out}")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
