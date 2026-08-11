#!/usr/bin/env python3
"""atomic_prep_test.py - a page image is committed whole or not at all. (B16)

Page PNGs are HANDOFF artefacts: the transcription / interpretation sub-agent reads them.
They were written with a direct PIL save, which is not atomic - and a kill mid-encode
leaves a partial file that is NON-EMPTY, so every resume guard in this skill
(`exists() and st_size > 0`, or a bare `exists()`) accepts it and the page is never
re-rendered. That permanence is the defect; whether a truncated PNG renders as a top band
or is rejected outright is decoder-dependent and not worth relying on either way.

Note what is NOT here: `<region>_vision.json`. The backlog filed it alongside the PNGs, but
vision_validate rejects any vision file that is not valid JSON and run.py exits 3 on it, so
a truncated round costs a round-trip, not data. Fixing what is not broken would have added
a write path with no failure to prevent. Offline."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402

WRITERS = {
    "vision_prep.py": "the page rasters the transcription agent reads",
    "interpret_prep.py": "the candidate thumbnails and per-page renders",
    "contact_sheet.py": "the montages the G-images reviewer signs off",
    "images.py": "the placeholder-audit / candidate dumps",
}


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    ck(hasattr(C, "atomic_save_image"), "_common.atomic_save_image exists")
    if not hasattr(C, "atomic_save_image"):
        print(f"\nATOMIC PREP TEST: FAIL ({len(fails)})")
        return 1

    try:
        from PIL import Image
    except Exception:
        print("  [SKIP] Pillow absent - the image writers degrade to no-ops by design")
        print("\nATOMIC PREP TEST: PASS")
        return 0

    d = Path(tempfile.mkdtemp(prefix="cbre_atp_"))
    im = Image.new("RGB", (64, 48), (10, 20, 30))

    # a successful save leaves the target and NO .tmp
    p = d / "page_p0.png"
    C.atomic_save_image(im, p)
    ck(p.exists() and p.stat().st_size > 0, "the image is written")
    ck(not (d / "page_p0.png.tmp").exists(), "no .tmp survives a successful save")
    ck(Image.open(p).size == (64, 48), "and it decodes")

    # a mid-encode failure must leave the ORIGINAL intact and no partial at the final name
    good = p.read_bytes()

    class _Boom:
        def save(self, *a, **k):
            Path(a[0]).write_bytes(b"\x89PNG\r\n\x1a\n partial")   # a NON-EMPTY partial
            raise OSError("disk full mid-encode")

    try:
        C.atomic_save_image(_Boom(), p)
    except OSError:
        pass
    ck(p.read_bytes() == good, "a failed save leaves the previous image byte-identical")
    ck(not p.with_suffix(".png.tmp").exists() or
       p.with_suffix(".png.tmp").read_bytes() != good,
       "the partial is quarantined in .tmp, never at the final name")

    # the crux: a partial is NON-EMPTY, so the size>0 resume guard would have accepted it
    partial = d / "partial.png"
    partial.write_bytes(b"\x89PNG\r\n\x1a\n truncated")
    ck(partial.exists() and partial.stat().st_size > 0,
       "a truncated PNG passes `exists() and st_size > 0` - which is why direct saves "
       "made the damage PERMANENT")

    # WIRING: every page-image writer must go through the helper
    for name, what in WRITERS.items():
        src = (HELPERS / name).read_text(encoding="utf-8", errors="replace")
        direct = [ln.strip() for ln in src.splitlines()
                  if ".save(" in ln and "atomic_save_image" not in ln
                  and "buf" not in ln and "wb.save" not in ln]
        ck(not direct, f"{name}: no direct image save remains ({what}) {ascii(direct[:1])}")
        ck("atomic_save_image" in src, f"{name}: uses atomic_save_image")

    if fails:
        print(f"\nATOMIC PREP TEST: FAIL ({len(fails)})")
        return 1
    print("\nATOMIC PREP TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
