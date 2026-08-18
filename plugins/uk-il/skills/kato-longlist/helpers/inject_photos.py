#!/usr/bin/env python3
"""Toolkit step: inject our downloaded Kato photos into the toolkit canonical.json (photo hero +
gallery), compressed for embedding. Matches each canonical property back to our own dataset
entry by (coordinates, size) via common.match_canonical_to_our - NOT by list position, which
breaks the moment the toolkit's own dedup drops a duplicate listing partway through."""
import os, io, re, sys, json, glob, base64, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json, upsert_ledger
from PIL import Image, ImageOps

GALLERY_MAX = 10

def datauri(path, maxpx, q):
    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode != "RGB":
        im = im.convert("RGB")
    if max(im.size) > maxpx:
        s = maxpx / float(max(im.size)); im = im.resize((int(im.size[0]*s), int(im.size[1]*s)), Image.LANCZOS)
    for qq in (q, q-10, q-20):
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=qq, optimize=True)
        if buf.tell() <= 420*1024:
            break
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--canonical", default=None)
    ap.add_argument("--ledger", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config); work = cfg["work_dir"]
    canon_path = args.canonical or os.path.join(work, "longlist_work", "canonical.json")
    ledger_path = args.ledger or os.path.join(work, "longlist_work", "source_ledger.csv")
    ds = (read_json(os.path.join(work, "properties", "_dataset.json"), {}) or {}).get("properties", [])
    canon = json.load(open(canon_path, encoding="utf-8"))
    from common import match_canonical_to_our
    pairs = match_canonical_to_our(canon["properties"], ds)
    done = 0
    ledger_rows, managed = [], set()
    # Filenames that are frequently NOT a real building photo (an annotated site/aerial
    # graphic reused identically across every sibling unit on a shared park, or a Street
    # View screenshot that is sometimes a broken "no imagery here" capture) - deprioritise
    # them for the HERO slot rather than drop them, so they still ship in the gallery for
    # context (never silently discarding a real asset) but never become an identical hero
    # across multiple properties or a broken-looking lead image.
    DEPRIORITISE_HERO = re.compile(r"aerial.*marked|marked.*aerial", re.I)
    # A "Street View.jpg" is a Kato-generated screenshot, not a photograph - it duplicates
    # the streetviewUrl link patch_canonical.py already injects into the modal, and at least
    # one instance shipped as a Google "Sorry, we have no imagery here" broken capture
    # (flagged by the G-images reviewer). Excluded outright rather than just deprioritised.
    EXCLUDE = re.compile(r"street\s*view", re.I)

    def _hero_order(paths):
        kept = [p for p in paths if not EXCLUDE.search(os.path.basename(p))]
        return sorted(kept, key=lambda p: (1 if DEPRIORITISE_HERO.search(os.path.basename(p)) else 0, p))

    for cp, our in pairs:
        idir = os.path.join(work, "properties", our["folder"], "media", "images")
        imgs = _hero_order(set(glob.glob(os.path.join(idir, "*.jp*g")) + glob.glob(os.path.join(idir, "*.png"))))
        pid = cp.get("id")
        # Manage photo+gallery for every property so the toolkit's stale "no usable photo (placeholder)"
        # gap row is dropped whether or not we have real photos (an honest placeholder still ships,
        # but the FALSE "gap" attribution must not remain once we own this property's imagery).
        managed.update({(str(pid), "photo"), (str(pid), "gallery")})
        if imgs:
            # The hero IS the carousel's first frame, so encode imgs[0] ONCE and reuse those exact
            # bytes for gallery[0]. Encoding it twice at different settings (1100/q76 vs 1000/q72)
            # produced two different data URIs for the same photograph, which the toolkit's images
            # gate reads as "gallery[0] != hero photo (carousel/hero mismatch)" and BLOCKS on for
            # every property. The hero keeps its higher-quality encoding; only imgs[1:] use the
            # lighter gallery settings.
            hero = datauri(imgs[0], 1100, 76)
            cp["photo"] = hero
            cp["gallery"] = [hero] + [datauri(f, 1000, 72) for f in imgs[1:GALLERY_MAX]]
            done += 1
            names = [os.path.basename(f) for f in imgs[:GALLERY_MAX]]
            ledger_rows.append({"property_id": pid, "record_type": "property", "field": "photo",
                "value": f"hero photo ({names[0]})", "source_file": names[0],
                "source_locator": "Kato listing photo (hero)", "source_type": "image",
                "extractor": "E-kato-media", "confidence": "High", "conflict_note": "", "verified": ""})
            ledger_rows.append({"property_id": pid, "record_type": "property", "field": "gallery",
                "value": f"{len(names)} photos", "source_file": "Kato listing",
                "source_locator": ("Kato listing photos: " + ", ".join(names))[:480],
                "source_type": "image", "extractor": "E-kato-media", "confidence": "High",
                "conflict_note": "", "verified": ""})
    json.dump(canon, open(canon_path, "w", encoding="utf-8"), ensure_ascii=False)
    upsert_ledger(ledger_path, ledger_rows, managed)
    print(f"photos injected: {done}/{len(pairs)} | canonical {round(os.path.getsize(canon_path)/1e6,1)} MB"
          f" | {len(ledger_rows)} ledger rows")

if __name__ == "__main__":
    main()
