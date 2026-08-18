#!/usr/bin/env python3
"""Toolkit QA step: build labelled montages of every bound SITE PLAN and every HERO photo from
canonical.json, for the model to vision-verify (each plan is a real plan; the right photo is on
the right property)."""
import os, io, sys, json, base64, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config
from PIL import Image, ImageDraw, ImageFont

def load(uri):
    return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).convert("RGB")

def montage(items, cell, cols, path):
    rows = math.ceil(len(items)/cols); pad, lab = 8, 22; cw, ch = cell, cell+lab
    canvas = Image.new("RGB", (cols*(cw+pad)+pad, rows*(ch+pad)+pad), (245, 245, 245))
    dr = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
    for i, (label, im) in enumerate(items):
        r, c = divmod(i, cols); x = pad+c*(cw+pad); y = pad+r*(ch+pad)
        t = im.copy(); t.thumbnail((cw, cell))
        canvas.paste(t, (x+(cw-t.width)//2, y+lab+(cell-t.height)//2))
        dr.rectangle([x, y, x+cw, y+ch], outline=(180, 180, 180)); dr.text((x+3, y+3), label[:42], fill=(0, 0, 0), font=font)
    canvas.save(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--canonical", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config); work = cfg["work_dir"]
    canon = json.load(open(args.canonical or os.path.join(work, "longlist_work", "canonical.json"), encoding="utf-8"))
    out = args.out or os.path.join(work, "longlist_work", "plan_qa"); os.makedirs(out, exist_ok=True)
    props = sorted(canon["properties"], key=lambda p: p.get("id", 0))
    plans = [(f'#{p["id"]} {p.get("park","")}', load(p["plan"])) for p in props if p.get("plan")]
    for k in range(0, len(plans), 6):
        montage(plans[k:k+6], 500, 3, os.path.join(out, f"plans_qa_{k//6+1}.png"))
    heroes = [(f'#{p["id"]} {p.get("park","")}', load(p["photo"])) for p in props if p.get("photo")]
    for k in range(0, len(heroes), 12):
        montage(heroes[k:k+12], 300, 4, os.path.join(out, f"heroes_qa_{k//12+1}.png"))
    noplan = [f'#{p["id"]} {p.get("park","")}' for p in props if not p.get("plan")]
    print(f"plans bound {len(plans)} -> {math.ceil(len(plans)/6)} montages | heroes {len(heroes)} -> {math.ceil(len(heroes)/12)}")
    print("no plan (verify honest):", noplan)

if __name__ == "__main__":
    main()
