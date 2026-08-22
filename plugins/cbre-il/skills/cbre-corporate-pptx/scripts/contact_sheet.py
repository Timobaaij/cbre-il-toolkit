"""Tile a rendered deck into ONE image so the whole deck can be judged at once.

Why this exists
---------------
The library already renders slides to PNG, but only ever used that to correct
text-box heights. Nothing ever *looked* at the result. No assertion can catch
"this deck reads as templated" or "slide 6 is a wall of grey" - but seeing nine
slides side by side catches both instantly.

So: render, tile, look. The critique revises the PLAN and re-renders. It never
nudges a coordinate - that stays the composer's job.

Usage
-----
    python scripts/contact_sheet.py MyDeck.pptx                  # -> MyDeck.contact.png
    python scripts/contact_sheet.py MyDeck.pptx -o sheet.png --cols 4

    import contact_sheet
    path = contact_sheet.build("MyDeck.pptx")     # returns the sheet path

Rendering backend is picked automatically:
  Windows + PowerPoint  -> to_png.ps1 (true-to-file, real CBRE fonts)
  otherwise             -> LibreOffice + pdftoppm (fonts substituted!)

On the LibreOffice path the sheet is a COMPOSITION check only. Line breaks and
weights will shift on the user's machine, so never judge typography from it.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

# The multimodal image limit is 2000px; stay under it so the sheet can be
# viewed inline without being downscaled into illegibility.
MAX_SHEET_W = 1960
PAD = 10
LABEL_H = 22
BG = (24, 26, 33)
LABEL_FG = (235, 236, 242)
BORDER = (72, 76, 94)


def _render_windows(pptx: Path, out_dir: Path) -> list[Path]:
    ps1 = HERE / "to_png.ps1"
    if not ps1.exists():
        return []
    try:
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
             "-In", str(pptx), "-OutDir", str(out_dir), "-Width", "1600",
             "-Height", "900"],
            check=True, capture_output=True, timeout=600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return []
    return sorted(out_dir.glob("*.png"))


def _render_libreoffice(pptx: Path, out_dir: Path) -> list[Path]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return []
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                        "--outdir", str(out_dir), str(pptx)],
                       check=True, capture_output=True, timeout=600)
        pdf = next(iter(out_dir.glob("*.pdf")), None)
        if pdf is None or not shutil.which("pdftoppm"):
            return []
        subprocess.run(["pdftoppm", "-r", "110", "-png", str(pdf),
                        str(out_dir / "slide")],
                       check=True, capture_output=True, timeout=600)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return []
    return sorted(out_dir.glob("slide-*.png"))


def render_slides(pptx, out_dir=None):
    """Render every slide to PNG. Returns (paths, backend_name)."""
    pptx = Path(pptx).resolve()
    out_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="cs_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        pngs = _render_windows(pptx, out_dir)
        if pngs:
            return pngs, "powerpoint"
    pngs = _render_libreoffice(pptx, out_dir)
    if pngs:
        return pngs, "libreoffice"
    raise RuntimeError(
        "Could not render the deck: PowerPoint COM is unavailable and "
        "LibreOffice (soffice + pdftoppm) is not on PATH. Install one, or "
        "review the .pptx directly."
    )


def tile(pngs, out_path, *, cols=3, labels=None):
    """Tile any list of slide PNGs into one labelled contact sheet.

    Shared by `build()` (a rendered deck) and the critique step (the gold
    reference set), so both sheets are sized and labelled identically and can
    be compared honestly side by side.

    `labels` may be a list of strings, one per image; it defaults to slide
    numbers. Returns the sheet path.
    """
    pngs = [Path(p) for p in pngs]
    if not pngs:
        raise ValueError("tile() needs at least one image")
    out_path = Path(out_path)
    n = len(pngs)
    cols = max(1, min(int(cols), n))
    rows = (n + cols - 1) // cols

    # Size each thumbnail so the whole sheet lands under the image limit.
    cell_w = (MAX_SHEET_W - PAD * (cols + 1)) // cols
    with Image.open(pngs[0]) as probe:
        aspect = probe.height / probe.width
    cell_h = int(cell_w * aspect)

    sheet_w = PAD + cols * (cell_w + PAD)
    sheet_h = PAD + rows * (cell_h + LABEL_H + PAD)
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)

    for i, png in enumerate(pngs):
        r, c = divmod(i, cols)
        x = PAD + c * (cell_w + PAD)
        y = PAD + r * (cell_h + LABEL_H + PAD)
        text = labels[i] if labels else f"{i + 1:02d}"
        draw.text((x + 2, y + 4), text, fill=LABEL_FG)
        with Image.open(png) as im:
            im = im.convert("RGB").resize((cell_w, cell_h), Image.LANCZOS)
            sheet.paste(im, (x, y + LABEL_H))
        draw.rectangle(
            [x, y + LABEL_H, x + cell_w - 1, y + LABEL_H + cell_h - 1],
            outline=BORDER, width=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, optimize=True)
    print(f"[contact sheet] {n} images, {cols}x{rows} -> {out_path} "
          f"({sheet_w}x{sheet_h}px)")
    return out_path


def build(pptx, out_path=None, *, cols=3, keep_slides=False):
    """Render `pptx` and tile every slide into one labelled contact sheet.

    Returns the sheet path. Print the backend note it emits: on LibreOffice the
    sheet is a composition check only, never a typography check.
    """
    pptx = Path(pptx).resolve()
    out_path = Path(out_path) if out_path else pptx.with_suffix(".contact.png")
    tmp = Path(tempfile.mkdtemp(prefix="contact_"))
    try:
        pngs, backend = render_slides(pptx, tmp)
        n = len(pngs)
        tile(pngs, out_path, cols=cols, labels=None)
        print(f"  backend={backend}")
        if backend == "libreoffice":
            print("  [warn] LibreOffice substitutes the CBRE fonts. Judge "
                  "composition and density only, never line breaks or "
                  "typography. A pass in PowerPoint is mandatory before "
                  "delivery.")
        if keep_slides:
            print(f"  slide PNGs kept in {tmp}")
        return out_path
    finally:
        if not keep_slides:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(
        description="Tile a rendered deck into one contact sheet for review.")
    p.add_argument("pptx", help="deck to render")
    p.add_argument("-o", "--out", default=None, help="sheet path")
    p.add_argument("--cols", type=int, default=3, help="columns (default 3)")
    p.add_argument("--keep-slides", action="store_true",
                   help="keep the per-slide PNGs")
    a = p.parse_args()
    try:
        build(a.pptx, a.out, cols=a.cols, keep_slides=a.keep_slides)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
