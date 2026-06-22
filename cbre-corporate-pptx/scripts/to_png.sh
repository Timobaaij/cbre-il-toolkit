#!/usr/bin/env bash
# Render each slide of a .pptx to PNG via a LibreOffice PDF intermediate.
# Output files: OUTDIR/01.png, OUTDIR/02.png, ...
# Usage: bash scripts/to_png.sh INPUT.pptx [OUTPUT_DIR] [DPI]
set -euo pipefail

IN="${1:?usage: to_png.sh INPUT.pptx [OUTPUT_DIR] [DPI]}"
OUTDIR="${2:-slide_imgs}"
DPI="${3:-150}"   # 150 -> ~1600px wide at 16:9. Keep <=200 to stay under image-tool limits.

mkdir -p "$OUTDIR"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

# Step 1: pptx -> pdf via LibreOffice
if command -v soffice >/dev/null 2>&1; then
    BIN=soffice
elif command -v libreoffice >/dev/null 2>&1; then
    BIN=libreoffice
else
    echo "error: neither 'soffice' nor 'libreoffice' is installed" >&2
    exit 1
fi
"$BIN" --headless --convert-to pdf --outdir "$TMPDIR" "$IN" >/dev/null

BASE="$(basename "$IN" .pptx)"
PDF="$TMPDIR/$BASE.pdf"

# Step 2: pdf -> per-page png via pdftoppm
if ! command -v pdftoppm >/dev/null 2>&1; then
    echo "error: 'pdftoppm' is not installed (try: apt-get install poppler-utils)" >&2
    exit 1
fi

# pdftoppm -png writes <prefix>-1.png, <prefix>-2.png, ...
pdftoppm -r "$DPI" -png "$PDF" "$TMPDIR/slide"

# Rename to zero-padded 01.png style in OUTDIR
i=1
for f in "$TMPDIR"/slide-*.png; do
    [ -e "$f" ] || continue
    printf -v NAME "%02d.png" "$i"
    mv "$f" "$OUTDIR/$NAME"
    i=$((i+1))
done

echo "Exported $((i-1)) slides to $OUTDIR"
