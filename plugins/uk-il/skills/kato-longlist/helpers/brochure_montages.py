#!/usr/bin/env python3
"""Toolkit step (site plans via vision): render each property's real Kato brochure pages into one
labelled montage per property, for the model to LOOK at and pick the genuine site-plan page.
Page labels are the 0-based GLOBAL page index across the property's merged brochure PDFs -
that is the index bind_site_plans.py expects."""
import os, io, sys, json, glob, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json
from PIL import Image, ImageDraw, ImageFont
import fitz

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--ids", default="all", help="'all' or comma list of property orders")
    args = ap.parse_args()
    cfg = load_config(args.config); work = cfg["work_dir"]
    out = args.out or os.path.join(work, "longlist_work", "plan_qa"); os.makedirs(out, exist_ok=True)
    ds = (read_json(os.path.join(work, "properties", "_dataset.json"), {}) or {}).get("properties", [])
    want = None if args.ids == "all" else {int(x) for x in args.ids.split(",")}
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    for our in ds:
        if want is not None and our["order"] not in want:
            continue
        pdfs = sorted(glob.glob(os.path.join(work, "properties", our["folder"], "media", "*.pdf")))
        pages = []
        for pdf in pdfs:
            d = fitz.open(pdf)
            for i in range(d.page_count):
                pix = d[i].get_pixmap(matrix=fitz.Matrix(1.1, 1.1), alpha=False)
                pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            d.close()
        if not pages:
            continue
        cols = min(4, len(pages)); rows = math.ceil(len(pages)/cols); cell, lab, pad = 360, 26, 6
        cw, ch = cell, cell+lab
        canvas = Image.new("RGB", (cols*(cw+pad)+pad, rows*(ch+pad)+pad), (250, 250, 250))
        dr = ImageDraw.Draw(canvas)
        for j, im in enumerate(pages):
            r, c = divmod(j, cols); x = pad+c*(cw+pad); y = pad+r*(ch+pad)
            t = im.copy(); t.thumbnail((cw, cell))
            canvas.paste(t, (x+(cw-t.width)//2, y+lab+(cell-t.height)//2))
            dr.rectangle([x, y, x+cw, y+ch], outline=(150, 150, 150))
            dr.text((x+4, y+3), f"page {j}", fill=(200, 0, 0), font=font)
        canvas.save(os.path.join(out, f"broch_{our['order']:02d}.png"))
        print(f"#{our['order']:02d} {(our['address'].get('name') or our['folder'])[:34]}: {len(pages)} pages")
    print("montages ->", out)

if __name__ == "__main__":
    main()
