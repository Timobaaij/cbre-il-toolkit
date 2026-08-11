#!/usr/bin/env python3
"""contact_sheet.py - one labelled montage of every property photo.

The image gate used to ping-pong across rounds because each reviewer sampled a
different handful of properties. This tiles ALL N photos into one (paginated)
PNG with an id / park / city caption per cell, so a single isolated reviewer
judges every property at once - spotting floor-plans-as-hero, placeholders and
wrong-property images in one exhaustive pass instead of several sampled rounds.

A near-solid cell (low pixel variance) is auto-tagged PLACEHOLDER so the
reviewer can see missing imagery instantly. Output: <out-dir>/contact_sheet_N.png.

CLI:
  python contact_sheet.py <canonical.json> --out-dir <render dir> [--cols 5]
                          [--per-sheet 30] [--thumb 480]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:  # Cowork without Pillow: try a bundled Pillow wheel (NO-OP unless it
    # matches this interpreter); else the contact-sheet montage (a PIL-only G-images aid)
    # degrades to a no-op rather than crashing the spine. `from __future__ import annotations`
    # keeps the Image.Image hints lazy, so rebinding is safe.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _vendor_wheels as _vw
        _vw.ensure("PIL", "pillow")
        from PIL import Image, ImageDraw, ImageFont
        _HAS_PIL = True
    except Exception:
        Image = ImageDraw = ImageFont = None  # type: ignore[assignment]
        _HAS_PIL = False

CAPTION_H = 34
PAD = 8
BG = (245, 244, 239)        # off-white
CELL_BG = (255, 255, 255)
CBRE_GREEN = (0, 63, 45)
LINE = (210, 210, 200)


def _atomic_save(im, path, **kw):
    """tmp + os.replace, so a kill mid-encode never leaves a partial sheet at the final
    name where a resume guard would accept it.

    _common is imported INSIDE the call so the Pillow-absent degrade path above stays
    dependency-free. There is deliberately NO direct-save fallback: that would put the
    non-atomic write back, which is the whole defect. Every caller already wraps this in a
    try/except that skips the sheet, so a failure degrades to a missing montage - visible -
    rather than a partial one that looks complete. (B16)"""
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parent))
    import _common as _C
    return _C.atomic_save_image(im, path, "PNG", **kw)


MONTAGE_MAX_EDGE = 1400   # stay under the vision resize threshold (~1568px long edge):
# above it the API downscales the whole canvas, which WOULD shrink the tiles and cost the
# agent detail. Below it, a tile is byte-for-byte the thumbnail it would have opened alone.
MONTAGE_CAPTION_H = 26


def tile_native(cells: list, out_path, cols: int = 3, tile_px: int = 384) -> list:
    """Tile already-written thumbnails into as few sheets as fit, at NATIVE size. (B19)

    One tool call instead of one per image. This is a pure co-location: each tile is pasted
    unscaled (PIL's thumbnail never upscales, so a `tile_px`-capped thumbnail arrives at its
    own size) and the canvas is capped at MONTAGE_MAX_EDGE, so the agent sees exactly the
    pixels it would have seen opening each file - merely side by side. Anything that shrank
    a tile would be a perception regression dressed as a speed-up.

    Every cell is tiled, in the order given, captioned with its `index`. Python must never
    drop or reorder one: which candidate is the hero is the LLM's judgement, and a silently
    missing tile would make it Python's. A cell whose image will not decode is the one
    exception - it is skipped rather than aborting the page, exactly as the per-candidate
    thumbnail writer already does - and it remains openable on its own.

    Returns the list of written sheet paths ([] when there is nothing to tile), paginating
    when one canvas would exceed the cap."""
    if not _HAS_PIL or not cells:
        return []
    loaded = []
    for c in cells:
        try:
            im = Image.open(str(c.get("image"))).convert("RGB")
            im.load()
        except Exception:
            continue  # undecodable - skip it, never abort the page
        loaded.append((c.get("index"), im))
    if not loaded:
        return []
    cell_w = min(tile_px, max(im.width for _, im in loaded))
    cell_h = min(tile_px, max(im.height for _, im in loaded))
    cols = max(1, min(cols, len(loaded)))
    step_w, step_h = cell_w + PAD, cell_h + MONTAGE_CAPTION_H + PAD
    # how many rows fit under the cap; at least one, or a single tall tile would loop
    max_rows = max(1, (MONTAGE_MAX_EDGE - PAD) // step_h)
    while cols > 1 and PAD + cols * step_w > MONTAGE_MAX_EDGE:
        cols -= 1
    per_sheet = max(1, cols * max_rows)
    out_path = Path(out_path)
    written = []
    for s in range(0, len(loaded), per_sheet):
        chunk = loaded[s:s + per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        W = PAD + min(cols, len(chunk)) * step_w
        H = PAD + rows * step_h
        sheet = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(sheet)
        font = _font(15)
        for k, (idx, im) in enumerate(chunk):
            r, c = divmod(k, cols)
            x, y = PAD + c * step_w, PAD + r * step_h
            draw.rectangle([x, y, x + cell_w, y + cell_h + MONTAGE_CAPTION_H],
                           fill=CELL_BG, outline=LINE)
            # centre the NATIVE image in its cell; never resize it
            ox = x + max(0, (cell_w - im.width) // 2)
            oy = y + max(0, (cell_h - im.height) // 2)
            sheet.paste(im, (ox, oy))
            draw.text((x + 6, y + cell_h + 4), f"index {idx}", font=font, fill=CBRE_GREEN)
        p = (out_path if len(loaded) <= per_sheet
             else out_path.with_name(f"{out_path.stem}_{s // per_sheet + 1}{out_path.suffix}"))
        try:
            _atomic_save(sheet, p)
        except Exception:
            continue
        written.append(str(Path(p).resolve()))
    return written


def _font(size=13):
    for name in ("arial.ttf", "DejaVuSans.ttf", "Calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _decode(data_uri: str) -> Image.Image | None:
    try:
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception:
        return None


def _is_solid(img: Image.Image) -> bool:
    """True if the image is near-uniform (a placeholder), via a downsampled std-dev."""
    small = img.resize((16, 16))
    px = list(small.getdata())
    n = len(px)
    means = [sum(c[i] for c in px) / n for i in range(3)]
    var = sum((c[i] - means[i]) ** 2 for c in px for i in range(3)) / (n * 3)
    return var < 40.0  # ~ <6 grey-levels spread = effectively flat


def build_sheets(canonical: dict, out_dir: Path, cols: int, per_sheet: int, thumb: int) -> list[Path]:
    if not _HAS_PIL:
        return []  # no Pillow: no montage; the G-images reviewer degrades (placeholders surfaced elsewhere)
    props = canonical.get("properties", [])
    out_dir.mkdir(parents=True, exist_ok=True)
    th_w, th_h = thumb, int(thumb * 9 / 16)
    cell_w, cell_h = th_w + 2 * PAD, th_h + CAPTION_H + 2 * PAD
    font, font_sm = _font(13), _font(11)
    paths: list[Path] = []

    pages = [props[i:i + per_sheet] for i in range(0, len(props), per_sheet)] or [[]]
    for pno, page in enumerate(pages, start=1):
        rows = (len(page) + cols - 1) // cols or 1
        sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), BG)
        d = ImageDraw.Draw(sheet)
        for idx, p in enumerate(page):
            cx, cy = (idx % cols) * cell_w, (idx // cols) * cell_h
            d.rectangle([cx + 2, cy + 2, cx + cell_w - 2, cy + cell_h - 2], fill=CELL_BG, outline=LINE)
            photo = p.get("photo", "")
            img = _decode(photo) if isinstance(photo, str) and photo.startswith("data:") else None
            tag = ""
            if img is None:
                d.rectangle([cx + PAD, cy + PAD, cx + PAD + th_w, cy + PAD + th_h], fill=CBRE_GREEN)
                tag = " [NO IMAGE]"
            else:
                if _is_solid(img):
                    tag = " [PLACEHOLDER]"
                img.thumbnail((th_w, th_h))
                ox = cx + PAD + (th_w - img.width) // 2
                oy = cy + PAD + (th_h - img.height) // 2
                sheet.paste(img, (ox, oy))
            park = str(p.get("park", "?"))[:30]
            cap1 = f"#{p.get('id')} {park}{tag}"
            cap2 = f"{p.get('city','?')} ({p.get('country','?')}) - {p.get('developer','?')[:22]}"
            ty = cy + PAD + th_h + 3
            d.text((cx + PAD, ty), cap1, fill=CBRE_GREEN, font=font)
            d.text((cx + PAD, ty + 16), cap2, fill=(90, 100, 96), font=font_sm)
        out = out_dir / (f"contact_sheet_{pno}.png" if len(pages) > 1 else "contact_sheet.png")
        _atomic_save(sheet, out, optimize=True)
        paths.append(out)
    return paths


def build_placeholder_audit(canonical: dict, out_dir: Path, cols: int = 4) -> Path | None:
    """One montage of every DISCARDED image candidate behind each placeholder hero
    (meta.placeholderAudit, dumped by merge). The G-images reviewer must look at
    this and either rescue a usable photo/plan or sign off that none exists - the
    images gate blocks until that sign-off. Never let 'no usable image' be an
    unreviewed assumption."""
    if not _HAS_PIL:
        return None  # no Pillow: no audit montage
    audit = (canonical.get("meta", {}) or {}).get("placeholderAudit", {}) or {}
    cells = []
    for pid, ent in sorted(audit.items(), key=lambda kv: kv[0]):
        for f in ent.get("files", []):
            cells.append((pid, ent, Path(f)))
    if not cells:
        return None
    th = 300
    cell_w, cell_h = th + 2 * PAD, int(th * 0.75) + CAPTION_H + 2 * PAD
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), BG)
    d = ImageDraw.Draw(sheet)
    font, font_sm = _font(13), _font(11)
    for idx, (pid, ent, f) in enumerate(cells):
        cx, cy = (idx % cols) * cell_w, (idx // cols) * cell_h
        d.rectangle([cx + 2, cy + 2, cx + cell_w - 2, cy + cell_h - 2],
                    fill=CELL_BG, outline=(200, 120, 60))  # amber frame = needs review
        try:
            img = Image.open(f).convert("RGB")
            img.thumbnail((th, int(th * 0.75)))
            sheet.paste(img, (cx + PAD, cy + PAD))
        except Exception:
            d.text((cx + PAD, cy + PAD), "(unreadable)", fill=(120, 0, 0), font=font)
        d.text((cx + PAD, cy + PAD + int(th * 0.75) + 3),
               f"#{pid} DISCARDED: {f.stem[-40:]}", fill=CBRE_GREEN, font=font)
        d.text((cx + PAD, cy + PAD + int(th * 0.75) + 19),
               f"{ent.get('source','?')} {ent.get('locator','')} - usable photo/plan?",
               fill=(150, 80, 20), font=font_sm)
    out = out_dir / "placeholder_audit.png"
    _atomic_save(sheet, out, optimize=True)
    return out


def build_gallery_sheet(canonical: dict, out_dir: Path, cols: int = 5, thumb: int = 300) -> Path | None:
    """One montage of every SECONDARY carousel image (gallery[1:]) across all properties, so the
    G-images reviewer inspects the CAROUSEL, not only heroes. A decorative/abstract graphic that
    slipped into a carousel classifies as a 'plan' - indistinguishable from a real site plan to the
    Python classifier, so ONLY a vision reviewer can catch it. The fix for a flagged slide is
    __meta.exclude_refs (the interpreter drops that candidate) or a gallery_nonphoto_ok sign-off.
    Heroes already live in the main contact sheet, so only gallery[1:] is tiled; None when there
    are no secondaries."""
    if not _HAS_PIL:
        return None
    cells = []  # (pid, park, slot_label, uri)
    for p in canonical.get("properties", []):
        gal = p.get("gallery")
        if not isinstance(gal, list) or len(gal) < 2:
            continue
        for k, uri in enumerate(gal[1:], start=2):  # slot 1 = hero (main sheet); label secondaries from 2
            if isinstance(uri, str) and uri.startswith("data:"):
                cells.append((p.get("id"), str(p.get("park", "?"))[:28], k, uri))
    if not cells:
        return None
    th = thumb
    cell_w, cell_h = th + 2 * PAD, int(th * 0.75) + CAPTION_H + 2 * PAD
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), BG)
    d = ImageDraw.Draw(sheet)
    font, font_sm = _font(13), _font(11)
    for idx, (pid, park, slot, uri) in enumerate(cells):
        cx, cy = (idx % cols) * cell_w, (idx // cols) * cell_h
        d.rectangle([cx + 2, cy + 2, cx + cell_w - 2, cy + cell_h - 2],
                    fill=CELL_BG, outline=(200, 120, 60))  # amber frame = inspect
        img = _decode(uri)
        if img is not None:
            img.thumbnail((th, int(th * 0.75)))
            sheet.paste(img, (cx + PAD, cy + PAD))
        else:
            d.text((cx + PAD, cy + PAD), "(unreadable)", fill=(120, 0, 0), font=font)
        d.text((cx + PAD, cy + PAD + int(th * 0.75) + 3),
               f"#{pid} carousel slide {slot}: {park}", fill=CBRE_GREEN, font=font)
        d.text((cx + PAD, cy + PAD + int(th * 0.75) + 19),
               "real building photo? or decorative/abstract to exclude?", fill=(150, 80, 20), font=font_sm)
    out = out_dir / "carousel_secondaries.png"
    _atomic_save(sheet, out, optimize=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("canonical")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--per-sheet", type=int, default=30)
    ap.add_argument("--thumb", type=int, default=480)  # 480 (was 300): low-res tiles caused
    # false "this is a logo" calls + a stale read, costing the image gate extra review loops
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(Path(args.canonical).read_text(encoding="utf-8"))
    paths = build_sheets(data, Path(args.out_dir), args.cols, args.per_sheet, args.thumb)
    n = len(data.get("properties", []))
    print(f"OK contact sheet: {n} properties over {len(paths)} image(s) -> "
          + ", ".join(str(p) for p in paths))
    audit_sheet = build_placeholder_audit(data, Path(args.out_dir))
    if audit_sheet:
        print(f"PLACEHOLDER AUDIT: discarded candidates need review -> {audit_sheet}")
        print("The G-images reviewer must rescue a usable photo/plan or sign off each one; "
              "the images gate blocks until placeholder_audit_ack.json records the verdict.")
    gallery_sheet = build_gallery_sheet(data, Path(args.out_dir))
    if gallery_sheet:
        print(f"CAROUSEL SECONDARIES: inspect for decorative/non-building slides -> {gallery_sheet}")
        print("Flag any decorative/abstract or non-building carousel image (it classifies as a "
              "'plan' - only vision catches it); the fix is __meta.exclude_refs (the interpreter "
              "drops that candidate on re-run). A genuine site plan / aerial in the carousel is fine.")
    print("Hand these PNG(s) to the isolated G-images reviewer for a single exhaustive pass.")


if __name__ == "__main__":
    main()
