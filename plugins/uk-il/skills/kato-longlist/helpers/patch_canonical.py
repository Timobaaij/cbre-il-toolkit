#!/usr/bin/env python3
"""Toolkit step (Kato data patch): inject the DATA fields the toolkit's tracker->canonical path
cannot carry (or CORRUPTS) into the toolkit canonical.json, straight from our per-property
property.json, AND write matching Source Ledger rows so every injected field traces to a source
(the toolkit's trace-coverage gate BLOCKS an untraced displayed field as possible fabrication).

Runs AFTER inject_photos.py (photos/gallery already in) and BEFORE build_dashboard.py.
Matches each canonical property back to our own dataset entry by POSTAL CODE, with
coordinates as a tiebreak only - NOT by 'canonical id == dataset order' (that only holds
until the pipeline's own dedup drops the first duplicate listing) and no longer by floor
area, which the pipeline is free to restate. See common.match_canonical_to_our, which
RAISES rather than returning a short list, so this step cannot patch a subset of the
dashboard and leave the remainder holding whatever the pipeline happened to capture - and
which also raises rather than binding ONE source record to two properties, so it cannot write
one building's description, landlord, EPC and links onto another building's card. Every
field below is exactly the kind that goes missing when it does: the curated description,
the landlord, the EPC and all four outbound links. Only sets the keys below; everything
else is preserved.

Why this exists: the toolkit's field dictionary has ONE green-cert slot ('breeam') into which it
folds EPC ("breeam": [..., "epc rating", "epc"]), and no tracker path to description/links. So:
  - EPC, curated description, brochure/video/website/street-view are DROPPED -> we inject them.
  - 'breeam' is CORRUPTED: the toolkit's dictionary backfills the EPC column into breeam wherever a
    real BREEAM rating is absent, so 13/34 shipped an EPC letter ("A+", "C", "EPC exempt") as a fake
    BREEAM rating. We OVERWRITE breeam from our correct property.json value, and a validity guard
    (only Pass/Good/Very Good/Excellent/Outstanding survive) makes an EPC value masquerading as
    BREEAM impossible even if the source data is wrong again.
  - 'country' arrives as the unknown sentinel '??' on every card, and REPAIRING IT IS THE SAME
    SHAPE OF JOB as breeam. It is not the pipeline misbehaving: the reader deck's country comes
    from intake.infer_cluster looking the CLUSTER LABEL up in the POI library's city->country
    index, our labels are per-property routing strings ('<title> <postcode>'), that index is a
    CEE-seeded convenience holding four UK cities, so every label misses and the deck is handed
    '??'. The reader's own contract then says "`region`/`country` = the manifest's values for
    that deck", so it writes '??' into the record - and '??' is NOT in the pipeline's
    looks_unknown() set, so merge treats it as a stated value. A brochure outranks a tracker for
    `country` (SPEC_RANK pdf 0 < xlsx 2, and `country` is not TRACKER_AUTHORITATIVE), so '??'
    BEATS the country name our own tracker states, and the pipeline offers the pair for
    broker adjudication as a genuine cross-source conflict. What ships is a required field
    reading '??' in every detail modal (patch_template's P13 renders `${p.country}` and a
    `flag ${p.country.toLowerCase()}` class, so the flag disappears too), a hero KPI strip
    counting ZERO countries, and one Gaps Report line per property for a value we have always
    known. Repaired here rather than at the label, because no label can fix it: the lookup is
    against a city index we do not own and must not seed, and a label that IS a bare town name
    would collapse two properties in one town into ONE routing cluster - the very defect
    cluster_label() carries the postal code to avoid. ONLY the sentinel is overwritten; a real
    two-letter code the pipeline read off a page is EVIDENCE and is left alone (and reported).

LLM does the judgement (the curated description is authored in enrichment step 4); this script only
MOVES bytes and RECORDS provenance. 'developer' is intentionally NOT populated.
"""
import os, re, sys, csv, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_config, read_json, match_canonical_to_our,
                    MARKET_COUNTRY_ISO, MARKET_COUNTRY_NAME)

LEDGER_HEADER = ["property_id", "record_type", "field", "value", "source_file", "source_locator",
                 "source_type", "extractor", "confidence", "conflict_note", "verified"]
KATO = "agency.kato.app (Kato listing)"
LEDGER_META = {
    "description":   ("Kato listing: summary / description / location_text", "derived",
                      "Kato-Longlist:patch_canonical",
                      "curated 3-4 sentence description of the property's own Kato marketing text"),
    "landlord":      ("Kato listing: landlord", "kato", "Kato-Longlist:kato_fetch", ""),
    "epc":           ("Kato listing: key points / EPC", "kato", "Kato-Longlist:enrichment", ""),
    "breeam":        ("Kato listing: key points / BREEAM", "kato", "Kato-Longlist:enrichment",
                      "overwrites toolkit value: only a valid BREEAM rating survives (EPC never shown as BREEAM)"),
    "brochureUrl":   ("Kato listing: documents", "kato", "Kato-Longlist:kato_fetch", ""),
    "videoUrl":      ("Kato listing: videos", "kato", "Kato-Longlist:kato_fetch", ""),
    "websiteUrl":    ("Kato listing: website", "kato", "Kato-Longlist:kato_fetch", ""),
    "streetviewUrl": ("derived from geocoded coordinates (Google Street View)", "derived",
                      "Kato-Longlist:patch_canonical", ""),
    "country":       ("Kato requirement market: %s (the country our tracker states on every "
                      "row)" % MARKET_COUNTRY_NAME, "derived", "Kato-Longlist:toolkit_tracker",
                      "replaces the pipeline's unknown-country sentinel, which its reader deck "
                      "inherits from a cluster label the city->country index cannot resolve"),
}
# BREEAM ratings only; an EPC letter (A+/A/B/C) or "EPC exempt ..." is NOT a BREEAM rating.
VALID_BREEAM = {"pass", "good", "very good", "excellent", "outstanding"}
# An ISO-3166 alpha-2 code, which is the ONLY thing canonical.schema.json's 2-3 char `country`
# is meant to hold. Anything else there ('??', 'tbd', '', a spelled-out name that slipped the
# pipeline's own country_iso) is a sentinel or a formatting failure, never evidence.
VALID_CC = re.compile(r"^[A-Za-z]{2}$")


def breeam_core(v):
    return re.sub(r"\(.*?\)", "", str(v or "")).strip().lower()


def street_view_url(sv):
    if not isinstance(sv, dict):
        return None
    pano, lat, lng, heading = sv.get("pano"), sv.get("lat"), sv.get("lng"), sv.get("heading")
    if pano:
        u = f"https://www.google.com/maps/@?api=1&map_action=pano&pano={pano}"
        if heading is not None:
            u += f"&heading={int(round(heading))}"
        return u
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
    return None


def upsert_ledger(ledger_path, new_rows, managed):
    """Drop every existing row for a (property_id, field) this run MANAGES (so a re-run never
    duplicates and a now-invalid value's stale row is removed), keep all others, then append ours."""
    kept = []
    if os.path.exists(ledger_path):
        with open(ledger_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (str(row.get("property_id")), row.get("field")) not in managed:
                    kept.append(row)
    with open(ledger_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        w.writeheader()
        for row in kept:
            w.writerow({k: row.get(k, "") for k in LEDGER_HEADER})
        for row in new_rows:
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--canonical", default=None)
    ap.add_argument("--ledger", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    canon_path = args.canonical or os.path.join(work, "longlist_work", "canonical.json")
    ledger_path = args.ledger or os.path.join(work, "longlist_work", "source_ledger.csv")

    ds = (read_json(os.path.join(work, "properties", "_dataset.json"), {}) or {}).get("properties", [])

    canon = json.load(open(canon_path, encoding="utf-8"))
    bak = canon_path + ".prepatch_backup.json"
    if not os.path.exists(bak):
        json.dump(canon, open(bak, "w", encoding="utf-8"), ensure_ascii=False)

    counts = {k: 0 for k in LEDGER_META}
    ledger_rows, managed = [], set()
    foreign = []   # properties the pipeline gave a REAL country that is not this market's

    def ledger(pid, field, val):
        loc, stype, extractor, note = LEDGER_META[field]
        ledger_rows.append({
            "property_id": pid, "record_type": "property", "field": field, "value": val,
            "source_file": KATO, "source_locator": loc, "source_type": stype,
            "extractor": extractor, "confidence": "High", "conflict_note": note, "verified": "",
        })

    for cp, our in match_canonical_to_our(canon.get("properties", []), ds):
        pid = str(cp.get("id"))
        media = our.get("media") or {}
        links = our.get("links") or {}
        spec = our.get("spec") or {}
        # additive fields: set only when present, leave canonical alone otherwise
        additive = {
            "description":   (our.get("curated_description") or "").strip() or None,
            "landlord":      our.get("landlord"),
            "brochureUrl":   media.get("brochure_url"),
            "videoUrl":      media.get("video_url"),
            "websiteUrl":    links.get("website"),
            "streetviewUrl": street_view_url((our.get("coordinates") or {}).get("street_view")),
            "epc":           spec.get("epc"),
        }
        for field, val in additive.items():
            managed.add((pid, field))
            if val:
                cp[field] = val
                counts[field] += 1
                ledger(pid, field, val)
        # breeam: OVERWRITE the toolkit's (EPC-corrupted) value; only a real rating survives.
        managed.add((pid, "breeam"))
        raw_br = spec.get("breeam")
        good_br = raw_br if (raw_br and breeam_core(raw_br) in VALID_BREEAM) else None
        cp["breeam"] = good_br or "tbd"
        if good_br:
            counts["breeam"] += 1
            ledger(pid, "breeam", good_br)
        # country: repair the sentinel, never overrule a real code. A two-letter code the
        # pipeline read off a page is page-cited evidence and outranks a constant of this
        # skill, so it is kept and REPORTED - loudly, because a non-UK property on a Kato
        # longlist means either the corpus picked up a foreign document or the reader shipped
        # its routing label, and both are worth an operator's eyes rather than a silent
        # overwrite that would hide whichever it is.
        cur_cc = str(cp.get("country") or "").strip()
        if VALID_CC.match(cur_cc) and cur_cc.upper() != MARKET_COUNTRY_ISO:
            foreign.append((pid, cur_cc.upper(), cp.get("park")))
        else:
            managed.add((pid, "country"))
            cp["country"] = MARKET_COUNTRY_ISO
            counts["country"] += 1
            ledger(pid, "country", MARKET_COUNTRY_ISO)

    json.dump(canon, open(canon_path, "w", encoding="utf-8"), ensure_ascii=False)
    upsert_ledger(ledger_path, ledger_rows, managed)
    print("patched canonical:", " ".join(f"{k}={v}" for k, v in counts.items()),
          f"| {round(os.path.getsize(canon_path)/1e6, 1)} MB | {len(ledger_rows)} ledger rows")
    for pid, cc, park in foreign:
        print(f"WARNING: pipeline id {pid} ({park!r}) states country {cc!r}, not "
              f"{MARKET_COUNTRY_ISO!r} - left as the pipeline read it, NOT repaired. Check the "
              f"card: a Kato requirement is a {MARKET_COUNTRY_NAME} market, so this is either a "
              f"foreign document in the corpus or a reader shipping its routing label.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
