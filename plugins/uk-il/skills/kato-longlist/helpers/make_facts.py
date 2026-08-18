#!/usr/bin/env python3
"""
Stage 3a-prep - emit a compact per-property facts file for the model to enrich from.

Pure field selection (plumbing). Produces emails/_property_facts.json: for each of the
longlisted properties, the identifying info + Kato key_points/amenities/summary AND the
Kato in-app message threads (kato_messages) that the model needs to (a) match broker
rents and (b) curate the headline specs.

CRITICAL: most rents and a lot of enrichment live in the Kato in-app MESSAGES (the broker
threads on each match), NOT only in the Outlook email export. Those messages are frequently
MULTI-OPTION - one broker message lists several buildings with a rent each and is attached to
several property threads - so the model must map each quoted figure to the RIGHT building by
name/size, never blanket-apply a whole message to every property it is attached to. Surfacing
them here is what lets step 4 honour the rent hierarchy (email quote -> Kato-message quote ->
Kato structured -> On application).
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json, write_json

def kato_messages(d):
    """Real broker messages on this property's Kato thread(s), system notes dropped."""
    out = []
    for m in (d.get("messages") or []):
        body = (m.get("body") or m.get("text") or "").strip()
        if not body or "System Note" in body:
            continue
        out.append({"sender": m.get("sender") or m.get("from"),
                    "org": m.get("org") or m.get("organisation"),
                    "created_at": m.get("created_at") or m.get("date"),
                    "body": body})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    props = os.path.join(work, "properties")
    idx = read_json(os.path.join(props, "_index.json"), {}) or {}
    facts = []
    for p in idx.get("properties", []):
        d = read_json(os.path.join(props, p["folder"], "_derived.json"), {}) or {}
        a = d.get("address") or {}
        facts.append({
            "folder": p["folder"], "name": a.get("name"), "full_address": a.get("full"),
            "postcode": a.get("postcode"), "size": (d.get("size") or {}).get("string"),
            "for_sale": d.get("for_sale"),
            "kato_rent": (d.get("rent_kato") or {}).get("string"),
            "key_points": d.get("key_points"), "amenities": d.get("amenities"),
            "summary": d.get("summary"),
            "kato_messages": kato_messages(d),
        })
    out = os.path.join(work, "emails", "_property_facts.json")
    write_json(out, {"count": len(facts), "properties": facts})
    print(f"facts -> {out} (n={len(facts)})", flush=True)

if __name__ == "__main__":
    main()
