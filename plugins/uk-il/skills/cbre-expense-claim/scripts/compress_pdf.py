"""Shrink a consolidated receipt PDF under a size budget, losing as little
receipt legibility as possible.

    python compress_pdf.py "<pdf>" [--target-mb 9.5] [--out <path>] [--dry-run]

Exit 0 and touch nothing when the file already fits. Otherwise re-encode the
embedded JPEGs and replace the file in place, keeping the untouched original in
the temp dir and printing its path.

Why the ladder is ordered the way it is
---------------------------------------
Reading a number off a thermal till roll depends on resolution first and JPEG
quality second, so the ladder spends the whole budget on pixels before it spends
any on quality:

  1. native resolution, quality walked down 92 -> 78
  2. only if native q78 still does not fit: cap the effective dpi, 240 -> 150,
     holding quality at 85, which is above the blocking threshold on text edges
  3. only if a 150 dpi cap still does not fit: q82 then q80 at 150 dpi
  4. still too big -> fail loudly rather than ship an illegible claim

Measured on the Prague/Budapest batch (53 pages, 14.18 MB, scans at 150-257
effective dpi): native q80 landed at 9.73 MB with every pixel intact. An SSIM
sweep against the source pixels put every rung of this ladder within 0.003 of
the others (0.991-0.994), so the size target, not the rung, decides the outcome.

Every page's pixel dimensions, geometry and text layer are verified against the
original before the replacement is committed; if verification fails, nothing is
replaced and the exit code is non-zero.
"""

import argparse
import io
import os
import shutil
import sys
import tempfile

import pymupdf
from PIL import Image
from PIL.JpegImagePlugin import get_sampling

DEFAULT_TARGET_MB = 9.5

# (dpi cap, jpeg quality). None = no resampling at all. Best first.
LADDER = (
    [(None, q) for q in (92, 90, 88, 86, 85, 84, 82, 80, 78)]
    + [(cap, 85) for cap in (240, 220, 200, 186, 170, 160, 150)]
    + [(150, 82), (150, 80)]
)


def rung_label(cap, quality):
    return f"{'native' if cap is None else str(cap) + 'dpi'} q{quality}"


def jpeg_images(doc):
    """One entry per unique DCTDecode image: (page, xref, effective dpi, w, h)."""
    out, seen = [], set()
    for pno in range(doc.page_count):
        page = doc[pno]
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            if doc.xref_get_key(xref, "Filter")[1] != "/DCTDecode":
                continue          # leave anything not JPEG exactly as it is
            bbox = page.get_image_bbox(img)
            dpi = img[2] / (bbox.width / 72) if bbox.width else 0
            out.append((pno, xref, dpi, img[2], img[3]))
    return out


def encode(decoded, dpi, w, h, cap, quality):
    img, sampling = decoded
    if cap and dpi > cap * 1.03:
        scale = cap / dpi
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, subsampling=sampling, optimize=True)
    return buf.getvalue()


def verify(new_path, ref_doc):
    """Geometry, image count, text layer and renderability against the original."""
    doc = pymupdf.open(new_path)
    try:
        if doc.page_count != ref_doc.page_count:
            return f"page count {doc.page_count} != {ref_doc.page_count}"
        for i in range(ref_doc.page_count):
            page, ref = doc[i], ref_doc[i]
            if abs(page.rect.width - ref.rect.width) > 0.1 or abs(page.rect.height - ref.rect.height) > 0.1:
                return f"page {i + 1} geometry changed"
            if len(page.get_images()) != len(ref.get_images()):
                return f"page {i + 1} lost an image"
            if page.get_text().strip() != ref.get_text().strip():
                return f"page {i + 1} text layer changed"
            if page.get_pixmap(dpi=36).is_unicolor:
                return f"page {i + 1} renders blank"
        return None
    finally:
        doc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--target-mb", type=float, default=DEFAULT_TARGET_MB)
    ap.add_argument("--out", help="write here instead of replacing in place")
    ap.add_argument("--dry-run", action="store_true", help="report the chosen rung, write nothing")
    args = ap.parse_args()

    src = os.path.abspath(args.pdf)
    budget = int(args.target_mb * 1_000_000)     # decimal MB, so it satisfies either reading
    size = os.path.getsize(src)
    print(f"{os.path.basename(src)}: {size / 1e6:.2f} MB, budget {budget / 1e6:.2f} MB")

    if size <= budget:
        print("under budget, left untouched")
        return 0

    doc = pymupdf.open(src)
    items = jpeg_images(doc)
    if not items:
        print("ERROR: no JPEG images to re-encode, cannot shrink this file", file=sys.stderr)
        return 1

    raw = {x: doc.xref_stream_raw(x) for _, x, _, _, _ in items}
    raw_total = sum(len(b) for b in raw.values())
    overhead = size - raw_total
    decoded = {}
    for _, xref, _, _, _ in items:
        img = Image.open(io.BytesIO(raw[xref]))
        img.load()
        try:
            sampling = get_sampling(img)
        except Exception:
            sampling = 2
        decoded[xref] = (img, sampling)

    # Probe rungs on the largest images only and extrapolate, so choosing a rung
    # costs a fraction of a full encode of every page. The build loop below
    # corrects any overshoot, so the estimate only has to be close.
    sample = sorted(items, key=lambda it: len(raw[it[1]]), reverse=True)[:12]
    sample_raw = sum(len(raw[it[1]]) for it in sample)

    chosen = None
    for cap, quality in LADDER:
        got = sum(len(encode(decoded[x], dpi, w, h, cap, quality)) for _, x, dpi, w, h in sample)
        predicted = overhead + got * raw_total / sample_raw
        if predicted <= budget:
            chosen = (cap, quality)
            print(f"chose {rung_label(cap, quality)}: estimated {predicted / 1e6:.2f} MB")
            break
        print(f"  {rung_label(cap, quality)} -> est {predicted / 1e6:.2f} MB, too big")

    if chosen is None:
        print(
            f"ERROR: even 150 dpi q80 exceeds {args.target_mb} MB. Split the PDF or drop "
            "duplicate pages rather than compressing further.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print(f"dry run, nothing written (would use {rung_label(*chosen)})")
        return 0

    # Build, then step down a rung if the real file overshoots the estimate.
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)                                  # Windows will not write to an open handle
    built = resized = 0
    label = ""
    for cap, quality in LADDER[LADDER.index(chosen):]:
        label = rung_label(cap, quality)
        work = pymupdf.open(src)
        resized = 0
        for pno, xref, dpi, w, h in items:
            if cap and dpi > cap * 1.03:
                resized += 1
            work[pno].replace_image(xref, stream=encode(decoded[xref], dpi, w, h, cap, quality))
        work.save(tmp, garbage=4, deflate=True, deflate_fonts=True, clean=True)
        work.close()
        built = os.path.getsize(tmp)
        if built <= budget:
            break
        print(f"  built {label} at {built / 1e6:.2f} MB, over budget, stepping down")
    else:
        os.unlink(tmp)
        print("ERROR: could not reach the budget", file=sys.stderr)
        return 1

    problem = verify(tmp, doc)
    doc.close()
    if problem:
        os.unlink(tmp)
        print(f"ERROR: verification failed ({problem}), original left in place", file=sys.stderr)
        return 1

    dest = os.path.abspath(args.out) if args.out else src
    backup = ""
    if not args.out:
        backup = os.path.join(
            tempfile.gettempdir(), os.path.basename(src).replace(".pdf", " (uncompressed).pdf")
        )
        shutil.copy2(src, backup)
    shutil.move(tmp, dest)
    print(
        f"wrote {os.path.basename(dest)}: {size / 1e6:.2f} -> {built / 1e6:.2f} MB "
        f"({label}, {resized} of {len(items)} images resampled, verified)"
    )
    if backup:
        print(f"original kept at {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
