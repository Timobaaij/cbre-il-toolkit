#!/usr/bin/env python3
"""Toolkit step (site plans via vision): apply the model's chosen site-plan pages to canonical.json.
--decisions is a JSON map {"<property order>": <global page index> | null}. Renders the chosen
page of the property's merged brochure into `plan`; null removes the plan (honest gap).

THE KEYS ARE OURS, THE IDS ARE THE PIPELINE'S, AND THEY ARE NOT THE SAME NUMBERS.
decisions.json is keyed by OUR ordinal, because that is what the operator looked at:
brochure_montages.py names each montage `broch_<order>.png`. This step used to take those
keys and use them DIRECTLY as the pipeline's canonical property ids. The two numbering
schemes coincide only until the pipeline's own de-duplication drops something, which is
precisely the situation common.match_canonical_to_our exists to survive. Past that point
every later decision bound a real, human-selected site plan onto the WRONG property, or
died on a KeyError against a missing dictionary entry, depending only on whether the id
happened to exist. So the map is built once and every key is resolved THROUGH it, and a key
that resolves to nothing is a named error rather than an exception or a mis-binding.
"""
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
    # match_canonical_to_our RAISES unless every pipeline property pairs to EXACTLY ONE source
    # record, and never binds one record to two properties, so this map is complete by
    # construction and there is no partial or ambiguous result to guard against here.
    #
    # WHAT IS STILL WORTH GUARDING is the last step of the chain, which the pairing cannot see:
    # this map is re-keyed by OUR ordinal, so two DISTINCT records carrying the SAME `order`
    # would collapse into one entry and the second would silently take the first's decision -
    # a human-selected site plan on the wrong building, the identical outcome the pairing fix
    # exists to stop, arriving one line later. A duplicate ordinal is a dataset defect rather
    # than a pairing one, so it is named rather than repaired.
    by_order, orderless = {}, []
    for cp, our in match_canonical_to_our(canon["properties"], ds):
        o = our.get("order")
        if o is None:
            orderless.append(cp.get("id"))
            continue
        key = str(int(o))
        if key in by_order:
            sys.exit("ERROR: two different source records both carry order %s (%r and %r), so "
                     "decisions key %r is ambiguous and one property would take the other's "
                     "site plan. Nothing written. Fix the duplicate 'order' in "
                     "properties/_dataset.json and re-run."
                     % (key, by_order[key][1].get("folder"), our.get("folder"), key))
        by_order[key] = (cp, our)
    known_orders = {str(int(p["order"])) for p in ds if p.get("order") is not None}

    changed = 0
    ledger_rows, managed = [], set()
    unresolved, benign = [], []
    for k, g in dec.items():
        try:
            key = str(int(k))
        except (TypeError, ValueError):
            unresolved.append((k, g, "not an integer property ordinal"))
            continue
        hit = by_order.get(key)
        if hit is None:
            # A key that resolves to nothing splits into two cases, and only one is benign:
            #   null choice  -> there is no plan to lose. The row was merged by our own
            #                   multi-broker dedup or dropped by the pipeline's, and the
            #                   surviving row carries its own key. Note it and move on.
            #   a page index -> a real plan a human chose, with nothing to apply it to.
            #                   Dropping that quietly is the exact content loss this routing
            #                   fix exists to stop, so it fails the step.
            why = ("not a property in our dataset at all" if key not in known_orders
                   else "in our dataset, but no pipeline property paired to it "
                        "(merged by our dedup, or dropped by the pipeline's)")
            (benign if g is None else unresolved).append((key, g, why))
            continue
        cp, our = hit
        pid = cp["id"]
        managed.add((str(pid), "plan"))   # a null decision drops any stale plan row too
        if g is None:
            if cp.pop("plan", None) is not None:
                changed += 1
        else:
            uri, src_pdf, page = render_global(work, our["folder"], int(g))
            if uri:
                cp["plan"] = uri; changed += 1
                ledger_rows.append({"property_id": pid, "record_type": "property", "field": "plan",
                    "value": f"site plan (p.{page})", "source_file": src_pdf or "brochure",
                    "source_locator": f"brochure page {page} (vision-selected site plan)",
                    "source_type": "pdf", "extractor": "E-vision", "confidence": "High",
                    "conflict_note": "", "verified": ""})

    if unresolved:
        out = ["ERROR: %d site-plan decision(s) name a page but resolve to no pipeline "
               "property, so a human-selected plan would be silently dropped. Nothing written."
               % len(unresolved)]
        for key, g, why in unresolved:
            out.append("  - decisions key %r -> page %s: %s" % (key, g, why))
        out.append("  Valid keys this run (our ordinal -> pipeline id): "
                   + (", ".join("%s->%s" % (k, v[0]["id"])
                                for k, v in sorted(by_order.items(), key=lambda kv: int(kv[0])))
                      or "(none)"))
        out.append("  Move each page number onto the surviving row's key, then re-run.")
        sys.exit("\n".join(out))

    json.dump(canon, open(canon_path, "w", encoding="utf-8"), ensure_ascii=False)
    upsert_ledger(ledger_path, ledger_rows, managed)
    plans = sum(1 for p in canon["properties"] if p.get("plan"))
    print(f"applied {changed} decisions | site plans: {plans}/{len(canon['properties'])} | {len(ledger_rows)} ledger rows")
    for key, g, why in benign:
        print(f"note: decisions key {key!r} (null choice) applied to nothing - {why}")
    if orderless:
        # No ordinal means no `broch_<order>.png` montage either, so the operator was never
        # shown these and cannot have chosen a page for them. Said out loud all the same: they
        # are properties that CANNOT receive a site plan by this route, which is a gap.
        print("note: %d pipeline propert%s (id %s) paired to a source record with no 'order', "
              "so no decisions key can reach %s - no site plan is applicable."
              % (len(orderless), "y" if len(orderless) == 1 else "ies",
                 ", ".join(str(i) for i in orderless),
                 "it" if len(orderless) == 1 else "them"))

if __name__ == "__main__":
    main()
