#!/usr/bin/env python3
"""
Stage 7h - fold the pipeline's corrected values back into OUR dataset (DETERMINISTIC).

WHY THIS EXISTS. The client Excel (build_excel.py) reads properties/_dataset.json, which is
built at stage 5 from Kato plus the model's enrichment. Everything the toolkit stage then
establishes - a brochure's warehouse-only area against a gross total, an EPC read off a page,
an office line the Kato listing never carried, a figure corrected by a repair or an
adjudicated value conflict - lands in the toolkit's canonical.json and NOWHERE ELSE. So the
spreadsheet a broker sends a client was the only deliverable still describing the pre-QA
dataset: on a live run its Warehouse column fell back to the gross total on five properties,
its Office column was empty on all of them, and its EPC column read 'tbd' for four
properties whose own brochures state a rating.

The dashboard was right and the spreadsheet beside it was wrong, which is worse than both
being wrong, because nothing on the face of either says which to trust.

WHAT IT DOES. Pairs each canonical property to our record with common.match_canonical_to_our
(the same matcher inject_photos and patch_canonical use, so a pairing failure is refused here
too rather than silently skipped), then copies a FIXED, NARROW set of fields onto
property.json and _dataset.json:

  size.warehouse_sqft / size.office_sqft                <- warehouseArea / officeAreaVal
  (size.sqft, the headline, is LEFT ALONE: see the comment at the assignment)
  spec.epc / spec.breeam                               <- epc / breeam
  curated_description                                  <- description (already ours, re-read
                                                          so a repair to it is not lost)

It NEVER touches rent, agent, tenure or notes: the rent hierarchy is the model's judgement
and the pipeline's own rent fields are thinner than ours (a Kato message quote never reaches
canonical). It never invents: a sentinel on the canonical side leaves our value alone.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json, write_json, match_canonical_to_our

# Every unknown marker either side of the fence writes, including the pipeline's lowercase
# 'tbd', our own 'TBC', and the 'Not stated' a reader emits when a deck prints no value.
SENTINEL = {"", "tbd", "tbc", "n/a", "na", "none", "-", "—", "–",
            "not stated", "not specified", "unknown", "0"}


def real(v):
    """A value a source actually states, as opposed to any side's unknown marker.

    Booleans and 0 are rejected outright rather than stringified: `str(False)` is "false",
    which is in no sentinel set, so a canonical `epc: 0` would otherwise have shipped.
    """
    if v is None or isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v > 0
    return str(v).strip().lower() not in SENTINEL


_NUMS = re.compile(r"\d[\d,]*(?:\.\d+)?")


def num(v, allow_multi=False):
    """A positive number out of 113690, '113,690' or '113,690 sq ft'; else None.

    A string holding MORE THAN ONE number returns None unless `allow_multi`. Taking the
    first was a live defect: canonical's officeArea for Flagstaff 42 read '1,194 sq ft
    (Ground Floor Office); 1,194 sq ft (First Floor Office)', and the first number is half
    the office. A halved area in a client spreadsheet is worse than a blank cell, because
    a blank invites a question and a wrong number does not.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    found = _NUMS.findall(str(v or ""))
    if not found or (len(found) > 1 and not allow_multi):
        return None
    try:
        f = float(found[0].replace(",", ""))
        return f if f > 0 else None
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--canonical", help="defaults to <work>/longlist_work/canonical.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    canon_path = args.canonical or os.path.join(work, "longlist_work", "canonical.json")
    props_dir = os.path.join(work, "properties")

    canon = read_json(canon_path, {}) or {}
    cps = canon.get("properties") or []
    ds = read_json(os.path.join(props_dir, "_dataset.json"), {}) or {}
    records = ds.get("properties") or []
    if not cps or not records:
        raise SystemExit("Need both %s and properties/_dataset.json." % canon_path)

    pairs = match_canonical_to_our(cps, records)
    changes, touched = [], {}
    for cp, our in pairs:
        if our is None:
            continue
        folder = our["folder"]
        size = our.setdefault("size", {})
        spec = our.setdefault("spec", {})

        # SPEC AND TERMS. The rule is one-directional and narrow: the pipeline's value is
        # taken ONLY where ours is an unknown marker. That is what the client spreadsheet
        # actually needed. Its Specification block was written from enrichment.json, so where
        # a reader found no value on a page and wrote "Not stated", the sheet printed those
        # words at a client, and where enrichment simply had no key the cell was blank, while
        # canonical held a real figure the pipeline had adjudicated. Live examples: Total Park
        # Telford and L111 Lincoln shipped "Not stated" for loading and yard against the
        # pipeline's 8 doors and 50 m / 48 m, and four properties shipped an empty Parking
        # cell against 130, 101, 96 and a 52-space description.
        #
        # Where OUR value is real it stays, because ours is often the richer statement: the
        # curated power line for Rotherham 125 carries the unresolved 1,800 versus 810 kVA
        # disagreement, which no single canonical figure could express.
        for ours_key, canon_key in (("clear_height", "clearHeight"), ("power", "electricity"),
                                    ("loading", "loadingDocks"), ("yard", "yardDepth"),
                                    ("parking", "carParking"), ("availability", "status"),
                                    ("floor_loading", "floorLoad")):
            if not real(spec.get(ours_key)) and real(cp.get(canon_key)):
                changes.append((folder, "spec." + ours_key, spec.get(ours_key), cp[canon_key]))
                spec[ours_key] = cp[canon_key]

        # TENURE is the exception to "ours wins": the pipeline's value is read off the deck's
        # own terms line and ours is Kato's one-word summary. A sheet that says "To Let" for a
        # building marketed "TO LET/MAY SELL" tells the client the wrong thing about what is
        # on offer, so the stated wording governs, and `for_sale` is re-derived from it so the
        # workbook's For Sale sheet stops under-reporting.
        # Only the FACT is taken, never the pipeline's wording. Canonical's tenure is the
        # deck's own terms sentence ("The premises are available to let by way of a new lease
        # on terms to be agreed..."), which is right but is a paragraph, and the client
        # workbook's Tenure column is fifteen characters wide and unwrapped. So the sentence
        # is read for whether a sale is on offer and the cell gets the short label.
        ten = cp.get("tenure")
        for_sale_stated = bool(real(ten) and re.search(r"\bsale\b|\bsell\b|freehold|leasehold interest",
                                                       str(ten), re.I))
        if for_sale_stated and not re.search(r"\bsale\b|\bsell\b", str(our.get("tenure") or ""), re.I):
            changes.append((folder, "tenure", our.get("tenure"), "For Sale / To Let"))
            our["tenure"] = "For Sale / To Let"
        if for_sale_stated and not our.get("for_sale"):
            changes.append((folder, "for_sale", our.get("for_sale"), True))
            our["for_sale"] = True

        # COORDINATES. Ours are Kato's, so an email-only option that never had a Kato listing
        # had none at all: ten of twenty-one rows shipped an empty Latitude and Longitude
        # while the dashboard mapped every one of them, because the pipeline geocoded them.
        lat, lng = cp.get("lat"), cp.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            # setdefault is not enough: a materialised record carries coordinates and
            # coordinates.map as an explicit null, so the key exists and holds None.
            if not isinstance(our.get("coordinates"), dict):
                our["coordinates"] = {}
            coords = our["coordinates"]
            if not isinstance(coords.get("map"), dict):
                coords["map"] = {}
            mp = coords["map"]
            if mp.get("lat") is None or mp.get("lng") is None:
                changes.append((folder, "coordinates.map", None, "%.5f, %.5f" % (lat, lng)))
                mp["lat"], mp["lng"] = lat, lng

        wh = num(cp.get("warehouseArea"))
        off = num(cp.get("officeAreaVal")) or num(cp.get("officeArea"))
        if wh:
            if size.get("warehouse_sqft") != wh:
                changes.append((folder, "size.warehouse_sqft", size.get("warehouse_sqft"), wh))
            size["warehouse_sqft"] = wh
        if off:
            if size.get("office_sqft") != off:
                changes.append((folder, "size.office_sqft", size.get("office_sqft"), off))
            size["office_sqft"] = off
        # DELIBERATELY NOT the headline size. warehouse + office is an under-sum on any
        # building with a plant deck, undercroft or operational mezzanine: on a live run it
        # pulled Rugby106 from its marketed 106,645 sq ft to 96,763 by dropping a 9,882 sq ft
        # mezzanine, and IAMP Washington from 124,976 to 124,262. The client compares the
        # marketed total against a 60,000 to 100,000 sq ft brief, so `size.sqft` keeps the
        # figure the source markets and the two component columns sit beside it.

        for ours_key, canon_key in (("epc", "epc"), ("breeam", "breeam")):
            v = cp.get(canon_key)
            if real(v) and spec.get(ours_key) != v:
                changes.append((folder, "spec." + ours_key, spec.get(ours_key), v))
                spec[ours_key] = v

        desc = cp.get("description")
        if real(desc) and our.get("curated_description") != desc:
            changes.append((folder, "curated_description", "(changed)", "(changed)"))
            our["curated_description"] = desc

        touched[folder] = our

    if args.dry_run:
        for f, k, a, b in changes:
            print("  would set %-46s %-24s %s -> %s" % (f[:46], k, a, b))
        print("DRY RUN. %d field(s) across %d propert(y/ies)." % (len(changes), len(touched)))
        return

    # property.json is written FIELD BY FIELD, not by replacing whole subtrees. Assigning
    # rec["size"] = our["size"] wholesale would drop any size or spec key that property.json
    # holds and the dataset record does not, and would write None over an existing
    # curated_description whenever the dataset record had none. Today the two happen to be
    # the same dict object, which makes the wholesale form harmless and the narrow form
    # identical; the narrow form stays correct if that ever stops being true.
    missing = []
    for folder, our in touched.items():
        p = os.path.join(props_dir, folder, "property.json")
        rec = read_json(p, None)
        if rec is None:
            missing.append(folder)
            continue
        for sub in ("size", "spec"):
            src = our.get(sub) or {}
            if src:
                tgt = rec.setdefault(sub, {})
                for k, v in src.items():
                    tgt[k] = v
        for top in ("tenure", "for_sale", "coordinates", "curated_description"):
            if our.get(top) is not None:
                rec[top] = our[top]
        write_json(p, rec)
    write_json(os.path.join(props_dir, "_dataset.json"), ds)
    if missing:
        # Never silent: the dataset has just moved and these property.json files have not,
        # so the two are out of step and the operator has to know which.
        print("  WARNING: no property.json for %d folder(s), so only _dataset.json was "
              "updated for them: %s" % (len(missing), ", ".join(missing[:4])), flush=True)

    for f, k, a, b in changes:
        print("  %-46s %-24s %s -> %s" % (f[:46], k, a, b))
    print("SYNCED %d field(s) across %d propert(y/ies) from %s"
          % (len(changes), len(touched), os.path.basename(canon_path)))
    print("  NEXT: re-run build_excel.py so the client workbook carries them.")


if __name__ == "__main__":
    main()
