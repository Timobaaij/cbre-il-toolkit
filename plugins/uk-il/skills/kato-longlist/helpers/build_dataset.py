#!/usr/bin/env python3
"""
Stage 3b - assemble the comprehensive per-property dataset (DETERMINISTIC PLUMBING ONLY).

This does NO matching and NO extraction. The judgement (which broker quote is the rent, what
the headline specs are) is done by the model/subagent in Stage 3a and handed over in
enrichment.json. This script just merges that with the Kato structured data + media on disk.

enrichment.json shape (keyed by property folder):
  { "overrides": { "<folder>": {
        "rent": {"psf": 25.0|null, "text": "£25.00 psf (guiding)", "basis": "...",
                 "source": "Jonathan Hay, Grant Mills Wood (email 31)"} | null,
        "spec": {"clear_height": "...", "power": "...", "loading": "...", "yard": "...",
                 "parking": "...", "epc": "...", "breeam": "...", "availability": "..."},
        "outgoings": {"service_charge": "...", "rates_payable": "...", "total_pa": "..."} | null,
        "notes": "..." } } }

Rent hierarchy applied here: model broker quote -> Kato structured -> "On application".
Writes properties/<folder>/property.json, properties/_dataset.json, properties/_gaps.json.
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json, write_json
import yaml

SQM = 0.09290304

def kato_rent(d):
    rk = d.get("rent_kato") or {}
    if rk.get("from"):
        return {"value": float(rk["from"]), "text": f"£{float(rk['from']):.2f} psf",
                "basis": "Kato structured", "source": "Kato structured", "provenance": "Kato structured field"}
    s = (rk.get("string") or "").strip()
    if s and s.lower() not in ("- non-quoting", "non-quoting", "rent on application", "roa", "-", "poa", ""):
        return {"value": None, "text": s, "basis": "Kato structured", "source": "Kato structured",
                "provenance": "Kato structured field"}
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--enrichment", default=None, help="path to model enrichment.json (default: work/enrichment.json)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    props_dir = os.path.join(work, "properties")
    index = read_json(os.path.join(props_dir, "_index.json"), {}) or {}

    enr_path = args.enrichment or os.path.join(work, "enrichment.json")
    enr = read_json(enr_path, {}) or {}
    overrides = enr.get("overrides", enr) if isinstance(enr, dict) else {}

    dataset, gaps = [], []
    for p in index.get("properties", []):
        folder = p["folder"]; pdir = os.path.join(props_dir, folder)
        d = read_json(os.path.join(pdir, "_derived.json"), {}) or {}
        ov = overrides.get(folder) or {}

        # rent hierarchy: model broker quote -> Kato structured -> On application
        rent = None
        ovr = ov.get("rent")
        if ovr and (ovr.get("psf") is not None or ovr.get("text")):
            rent = {"value": ovr.get("psf"),
                    "text": ovr.get("text") or (f"£{ovr['psf']:.2f} psf" if ovr.get("psf") is not None else None),
                    "basis": ovr.get("basis"), "source": ovr.get("source"),
                    "provenance": "broker quote (email / Kato message)"}
        if rent is None:
            rent = kato_rent(d) or {"value": None, "text": "On application", "basis": None,
                                    "source": None, "provenance": "no quote found"}

        sqft = (d.get("size") or {}).get("to") or (d.get("size") or {}).get("from")
        media_dir = os.path.join(pdir, "media")
        docs = [f for f in sorted(os.listdir(media_dir))] if os.path.isdir(media_dir) else []
        docs = [f for f in docs if os.path.isfile(os.path.join(media_dir, f))]
        img_dir = os.path.join(media_dir, "images")
        images = sorted(os.listdir(img_dir)) if os.path.isdir(img_dir) else []

        spec = ov.get("spec") or {}
        outg = ov.get("outgoings") or {}
        rec = {
            "order": p["order"], "match_id": p["match_id"], "folder": folder,
            "status": d.get("status"), "tenure": d.get("tenure"), "for_sale": d.get("for_sale"), "to_let": d.get("to_let"),
            "address": d.get("address"), "postcode": (d.get("address") or {}).get("postcode"),
            "area": d.get("area"), "coordinates": d.get("coordinates"),
            "size": {"sqft": sqft, "sqm": round(sqft * SQM, 1) if sqft else None, "string": (d.get("size") or {}).get("string")},
            "rent": rent, "price": d.get("price"),
            "outgoings": {"service_charge": outg.get("service_charge") or d.get("service_charge"),
                          "rates_payable": outg.get("rates_payable") or d.get("rates_payable"),
                          "estate_charge": outg.get("estate_charge") or d.get("estate_charge"),
                          "total_pa": outg.get("total_pa") or d.get("total_pa"),
                          "source": outg.get("source")},
            "spec": {k: spec.get(k) for k in ("clear_height", "power", "loading", "yard", "parking",
                                              "floor_loading", "epc", "breeam", "availability")},
            "agents": d.get("agents"), "agent_organisation": d.get("agent_organisation"),
            "landlord": ("; ".join(d.get("landlord_companies") or []) or ("Confidential" if d.get("landlord_confidential") else None)),
            "key_points": d.get("key_points"), "amenities": d.get("amenities"),
            "summary": d.get("summary"), "description": d.get("description"), "location_text": d.get("location_text"),
            # curated_description: a 3-4 sentence dashboard description the MODEL authors during
            # enrichment (step 4) from summary + description + location_text; Python only carries it.
            # This is what patch_canonical.py injects into canonical.description so cards show prose.
            "curated_description": ov.get("description"),
            "transport": {"tube": d.get("tube"), "train": d.get("train")},
            "media": {
                "documents": docs, "images_count": len(images), "images": images,
                "document_urls": [x.get("url") for x in (d.get("documents") or []) if x.get("url")],
                "brochure_url": next((x.get("url") for x in (d.get("documents") or []) if x.get("url")), None),
                "image_urls": [x.get("url") for x in (d.get("images") or []) if x.get("url")],
                "lead_image_url": next((x.get("url") for x in (d.get("images") or []) if x.get("url")), None),
                "videos": d.get("videos"),
                "video_url": next((v.get("url") for v in (d.get("videos") or []) if v.get("url")), None),
            },
            "links": {"website": d.get("website"),
                      "kato_listing": f"https://agency.kato.app/#/requirements/{index.get('requirement_id')}/manage/shortlist/{p['match_id']}?table_tab=longlist"},
            "messages": d.get("messages"),
            "notes": ov.get("notes"),
            "_provenance": {"rent": rent.get("provenance"), "rent_source": rent.get("source"),
                            "specs": "model from key_points/emails" if spec else "not set", "core": "Kato API"},
        }
        write_json(os.path.join(pdir, "property.json"), rec)
        dataset.append(rec)
        g = {"folder": folder}
        if rec["rent"]["text"] == "On application":
            g["rent"] = "none"
        missing = [k for k in ("clear_height", "power") if not rec["spec"].get(k)]
        if missing:
            g["specs_missing"] = missing
        if len(g) > 1:
            gaps.append(g)

    write_json(os.path.join(props_dir, "_dataset.json"),
               {"requirement_id": index.get("requirement_id"), "count": len(dataset), "properties": dataset})
    write_json(os.path.join(props_dir, "_gaps.json"), {"gaps": gaps})
    broker = sum(1 for r in dataset if r["rent"]["provenance"].startswith("broker"))
    withrent = sum(1 for r in dataset if r["rent"]["text"] != "On application")
    print(f"DONE. properties={len(dataset)} rent_populated={withrent} broker_quoted={broker} gaps={len(gaps)}", flush=True)

if __name__ == "__main__":
    main()
