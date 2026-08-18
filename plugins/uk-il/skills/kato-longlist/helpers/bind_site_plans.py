#!/usr/bin/env python3
"""Toolkit step (site plans via vision): apply the model's chosen site-plan pages to canonical.json.
--decisions is a JSON map {"<property order>": <global page index> | null}. Renders the chosen
page of the property's merged brochure into `plan`; null removes the plan (honest gap)."""
import os, io, sys, json, glob, base64, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json, upsert_ledger, match_canonical_to_our
from PIL import Image
import fitz

def render_global(work, folder, gidx):
    """Return (data_uri, source_pdf_basename, local_page_1based) for the chosen global page."""
    off = 0
    for pdf in sorted(glob.glob(os.path.join(work, "properties", folder, "media", "*.pdf"))):
        d = fitz.open(pdf)
        if off <= gidx < off + d.page_count:
            local = gidx - off
            pix = d[local].get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples); d.close()
            if max(img.size) > 1500:
                s = 1500/float(max(img.size)); img = img.resize((int(img.size[0]*s), int(img.size[1]*s)), Image.LANCZOS)
            for q in (80, 70, 60, 50):
                buf = io.BytesIO(); img.save(buf, "JPEG", quality=q, optimize=True)
                if buf.tell() <= 430*1024:
                    break
            return ("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                    os.path.basename(pdf), local + 1)
        off += d.page_count; d.close()
    return None, None, None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--canonical", default=None)
    ap.add_argument("--ledger", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config); work = cfg["work_dir"]
    canon_path = args.canonical or os.path.join(work, "longlist_work", "canonical.json")
    ledger_path = args.ledger or os.path.join(work, "longlist_work", "source_ledger.csv")
    dec = json.load(open(args.decisions, encoding="utf-8"))
    ds = (read_json(os.path.join(work, "properties", "_dataset.json"), {}) or {}).get("properties", [])
    canon = json.load(open(canon_path, encoding="utf-8"))
    id2ds = {cp["id"]: our for cp, our in match_canonical_to_our(canon["properties"], ds)}
    byid = {p["id"]: p for p in canon["properties"]}
    changed = 0
    ledger_rows, managed = [], set()
    for k, g in dec.items():
        pid = int(k)
        managed.add((str(pid), "plan"))   # a null decision drops any stale plan row too
        if g is None:
            if byid[pid].pop("plan", None) is not None:
                changed += 1
        else:
            uri, src_pdf, page = render_global(work, id2ds[pid]["folder"], int(g))
            if uri:
                byid[pid]["plan"] = uri; changed += 1
                ledger_rows.append({"property_id": pid, "record_type": "property", "field": "plan",
                    "value": f"site plan (p.{page})", "source_file": src_pdf or "brochure",
                    "source_locator": f"brochure page {page} (vision-selected site plan)",
                    "source_type": "pdf", "extractor": "E-vision", "confidence": "High",
                    "conflict_note": "", "verified": ""})
    json.dump(canon, open(canon_path, "w", encoding="utf-8"), ensure_ascii=False)
    upsert_ledger(ledger_path, ledger_rows, managed)
    plans = sum(1 for p in canon["properties"] if p.get("plan"))
    print(f"applied {changed} decisions | site plans: {plans}/{len(canon['properties'])} | {len(ledger_rows)} ledger rows")

if __name__ == "__main__":
    main()
