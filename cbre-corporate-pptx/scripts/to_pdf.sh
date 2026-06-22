#!/usr/bin/env bash
# Render a .pptx to PDF using LibreOffice headless.
# Usage: bash scripts/to_pdf.sh INPUT.pptx [OUTPUT_DIR]
set -euo pipefail

IN="${1:?usage: to_pdf.sh INPUT.pptx [OUTPUT_DIR]}"
OUTDIR="${2:-.}"

mkdir -p "$OUTDIR"

# soffice on Debian/Ubuntu, libreoffice elsewhere
if command -v soffice >/dev/null 2>&1; then
    BIN=soffice
elif command -v libreoffice >/dev/null 2>&1; then
    BIN=libreoffice
else
    echo "error: neither 'soffice' nor 'libreoffice' is installed" >&2
    exit 1
fi

"$BIN" --headless --convert-to pdf --outdir "$OUTDIR" "$IN" >/dev/null

BASE="$(basename "$IN" .pptx)"
echo "DONE: $OUTDIR/$BASE.pdf"
