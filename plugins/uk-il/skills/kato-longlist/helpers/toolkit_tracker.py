#!/usr/bin/env python3
"""Toolkit step 1 (deterministic): write what the cbre-property-longlist pipeline consumes.

Into the folder the pipeline SCANS (`--inputs`): one availability tracker xlsx, plus EVERY
longlist property's own source documents.
Into the folder the pipeline READS ITS CONFIG FROM (`--toolkit-work`): the generated
project.yaml (all enrichment on, ORS key baked, emails none).

WHY THE SOURCE DOCUMENTS ARE HERE NOW
-------------------------------------
This step used to place the tracker and nothing else, on the stated rationale that the data
build stays fast because the wrapper injects imagery itself and pulls plans via vision.
That rationale is withdrawn. A fast build of unevidenced data is not a saving.

Placing no source documents was a deliberate decision resting on an assumption nobody wrote
down: that the upstream system carries structured data for every property on the longlist.
The moment a longlist contains a property whose only real source is a document, the
assumption is false and the pipeline has nothing to read for that property. It dispatches
zero document readers for it, and every specification field on its card comes from a
spreadsheet THIS HELPER generated, with no page-cited evidence behind any value. Nothing
fails. Every gate passes. The run is confidently and silently wrong, which is strictly
worse than a run that is late.

So the documents ship, and this step REFUSES to write a corpus in which any longlist row
has no machine-readable source at all (see --allow-unevidenced-rows).

WHAT THE FILENAMES DO, AND WHAT THEY DO NOT DO
----------------------------------------------
Each copied document is named `NN <original stem> - <label>.<ext>`, and the trailing
` - <label>` is load-bearing. `intake.infer_cluster` takes the CLUSTER as the last
spaced-dash segment of the stem, and the cluster is what decides how documents are GROUPED
into reader decks and which output slot each deck gets. One label per property therefore
means one property's documents are read together and are never lumped in with another
property's.

It is routing, and ONLY routing. The pipeline is explicit that the cluster label is not
evidence: interpret_prep tags every deck `cluster_label_is_routing_only`, and a gate blocks
any reader that ships the label as a property's region. Nothing in the matcher reads a
filename. What actually ties a document to its tracker row is what the two of them STATE:
the scheme name, the party names, the postal code and the floor area with its unit. The
filename cannot fix a document that states none of those, and this helper does not pretend
otherwise - it only guarantees the document is THERE to be read, and reaches the right deck.

WHY project.yaml IS NOT IN THE SCANNED FOLDER
---------------------------------------------
Its extension matches none of the pipeline's accepted input types (intake classifies
.pdf/.pptx, .xlsx/.xlsm/.csv, the image types and .msg/.eml; everything else is
`unclassified`), so a copy sitting in the scanned folder was folded into the unreadable set
and shipped in the CLIENT-FACING Gaps Report under "Unreadable / skipped input files",
carrying trailing advice to re-save or unlock it that is meaningless for a file we generated
ourselves. The pipeline ignored that copy in any case: it reads `<work>/project.yaml` and
scaffolds its own there when absent. So we write it where it is actually read, and the
pipeline's own intake then merges its cluster map into it rather than overwriting it.
"""
import os, sys, re, json, shutil, hashlib, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_config, read_json, dedupe_props, display_name, sanitize,
                    MARKET_COUNTRY_ISO, MARKET_COUNTRY_NAME)
from openpyxl import Workbook

# display_name now lives in common.py, because the canonical<->dataset pairing needs the
# same composed string on both sides (see common.match_canonical_to_our). Re-exported here
# so anything importing it from this module keeps working.
__all__ = ["display_name", "HEADERS", "cluster_label", "main"]

# WHICH EXTENSIONS ARE COPIED, AND WHY THE REST ARE NOT.
#
# .pdf / .pptx        THE BROCHURE READERS. These are what intake clusters per property and
#                     what the PDF / PPTX / interpretation readers read WITH A PAGE
#                     CITATION, so they are what turns a specification field from "our own
#                     generated spreadsheet said so" into evidence. Both formats, never just
#                     PDF: a PPTX brochure is handled by a reader of its own, and skipping it
#                     would drop a property's only source on a corpus that happens to be
#                     PowerPoint.
# .xlsx/.xlsm/.csv    ACCEPTED BY THE PIPELINE, NOT COPIED BY DEFAULT. Every spreadsheet in
#                     the scanned folder is a SEPARATE TRACKER: the pipeline loops over each
#                     one and opens its own column-map adjudication (exit 3) per file, and
#                     merges its rows in as further properties. N per-property sheets
#                     therefore cost N extra operator round-trips and can invent rows. Opt in
#                     with --include-sheets when a property's only source is a sheet; either
#                     way such rows are NAMED in the report below, so the choice is informed
#                     rather than silent.
# image types         NOT COPIED. inject_photos.py owns this run's imagery and injects it
#                     straight into canonical.json; an image in the scanned folder competes
#                     for the same hero slot and can also be read as an image-only deck.
# .msg / .eml         NOT COPIED. The wrapper's own email pipeline already reads the broker
#                     export into the enrichment step, and the generated config sets
#                     inputs.emails.source: none. A copy here would double-count the same
#                     text under a second extractor and attribute it twice in the ledger.
DOC_EXTS = (".pdf", ".pptx")
SHEET_EXTS = (".xlsx", ".xlsm", ".csv")
NEVER_COPY_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".msg", ".eml")

# Mirrors intake's own noise list. A cluster label that IS one of these tokens gets popped by
# infer_cluster, and the property would silently inherit the previous filename segment as its
# cluster - so a label that matches is replaced with a structural one instead.
_NOISE_LABEL = re.compile(r"^(?:final|draft|copy|copy\s*\(\d+\)|updated?|latest|new|clean|"
                          r"shared|issued|v\d+|rev\.?\s*\d+|r\d+|\d{6,8}|\(\d+\))$", re.I)
# Any SPACED dash inside a label would be read by infer_cluster as a separator and cut the
# label in half, so two properties could collapse into one cluster. Collapsed to a comma.
# The three dash code points mirror intake's own separator class exactly (hyphen, U+2013,
# U+2014); written as escapes so the source file carries no long-dash character of its own.
_SPACED_DASH = re.compile("\\s+[-\u2013\u2014]\\s+")

HEADERS = ["Property", "Address", "City", "Region", "Country", "Postcode", "Coordinates (lat,lng)",
           "GLA (sq ft)", "Tenure", "Availability", "Warehouse rent (GBP/sq ft/yr)", "Rent basis",
           "Service charge (GBP/sq ft)", "Rates payable (GBP/yr)", "Clear height", "Power",
           "Loading doors", "Yard depth", "Car parking", "Floor loading", "EPC", "BREEAM",
           "Agent", "Description"]


def cluster_label(p):
    """The trailing ' - <label>' of every document filename written for property p.

    Built to survive the pipeline's own filename rules rather than to look tidy:
      * it goes LAST, because infer_cluster takes the last spaced-dash segment;
      * it carries no spaced dash of its own, or it would be cut in half. Sanitising first
        and collapsing second matters: sanitize() turns a path-illegal character into a
        bare '-', which between two spaces would become a brand-new separator;
      * it is not a noise token, or infer_cluster would pop it;
      * it carries the composed display title AND the postal code, because the title alone
        is not distinguishing: two properties in one town share a town and differ by code.
    """
    a = p.get("address") or {}
    label = " ".join(x for x in [(display_name(p) or "").strip(),
                                 (a.get("postcode") or "").strip()] if x)
    label = sanitize(label, maxlen=90)
    label = _SPACED_DASH.sub(", ", label).strip().strip("-").strip()
    if not label or _NOISE_LABEL.match(label):
        label = "Property %02d" % int(p.get("order") or 0)
    return label


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def source_folders(p):
    """Every folder whose documents evidence this ROW: the row's own, plus any folder
    dedupe_props merged into it. A merged sibling can hold the only brochure there is while
    the surviving row was chosen for having the fuller description (see common.dedupe_props)."""
    out = [p.get("folder")] + list(p.get("_dedupe_folders") or [])
    seen, keep = set(), []
    for f in out:
        if f and f not in seen:
            seen.add(f)
            keep.append(f)
    return keep


def copy_sources(work, inputs, props, wanted):
    """Copy each row's source documents into the scanned folder under a per-row cluster label.

    Returns (per_row, copied, by_policy). per_row maps a row's order to a list of
    (filename, is_first_copy_of_these_bytes, duplicate_of) - the flag matters because the
    pipeline de-duplicates its inputs BY CONTENT and keeps only the first in sorted order, so
    a second, byte-identical copy of another row's document is discovered and then skipped,
    and does not evidence this row. Rows are walked in ordinal order so that "first in
    sorted order" is decided the same way here as it is there (our names are ordinal-first).

    `duplicate_of` is the name of the copy that SURVIVES that de-duplication (None on a first
    copy), and it is carried out of here for one reason: the refusal below has to tell an
    operator which file to go and look at. It named the row's own copy instead, which is the
    file the pipeline THREW AWAY - so the message sent the reader to a file whose contents
    were never the problem, to work out for themselves which other row had claimed the bytes.
    The answer was already sitting in the seen-hash map at the moment of the skip."""
    per_row, copied, by_policy = {}, [], []
    seen_sha, used_names = {}, set()
    for p in sorted(props, key=lambda x: int(x.get("order") or 0)):
        order = int(p.get("order") or 0)
        label = cluster_label(p)
        kept = []
        for folder in source_folders(p):
            mdir = os.path.join(work, "properties", folder, "media")
            if not os.path.isdir(mdir):
                continue
            for nm in sorted(os.listdir(mdir)):
                src = os.path.join(mdir, nm)
                if not os.path.isfile(src):
                    continue
                stem, ext = os.path.splitext(nm)
                ext = ext.lower()
                if ext not in wanted:
                    if ext in SHEET_EXTS or ext in NEVER_COPY_EXTS:
                        by_policy.append((order, nm))
                    continue
                base = "%02d %s" % (order, sanitize(stem, maxlen=70))
                dest = "%s - %s%s" % (base, label, ext)
                n = 2
                while dest.lower() in used_names:
                    dest = "%s (%d) - %s%s" % (base, n, label, ext)
                    n += 1
                used_names.add(dest.lower())
                shutil.copy2(src, os.path.join(inputs, dest))
                sha = sha256_file(src)
                winner = seen_sha.setdefault(sha, dest)
                first = winner == dest
                kept.append((dest, first, None if first else winner))
                copied.append(dest)
        per_row[order] = kept
    return per_row, copied, by_policy


def project_yaml(client, ors, inputs):
    """The pipeline's own config. `inputs.folder` is informational only - the layout comes
    from the --folder/--work flags the spine is invoked with, never from this file."""
    return f'''client:
  name: "{client}"
  confidential: true
market:
  title_html: "Industrial &amp; Logistics <em>options</em>."
  eyebrow: ""
  region_label: ""
  countries: ["{MARKET_COUNTRY_ISO}"]
  lede: ""
output:
  filename: ""
  compiled_date: ""
  language: "English"
inputs:
  folder: "{inputs.replace(chr(92), '/')}"
  emails:
    source: none
enrichment:
  geocode: true
  pois: true
  osrm: true
  regions: true
  osrm_endpoint: "https://router.project-osrm.org"
  ors_api_key: "{ors}"
qa:
  fill_threshold: 0.6
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--inputs", default=None, help="pipeline inputs dir (default: <work>/longlist_inputs)")
    ap.add_argument("--toolkit-work", default=None,
                    help="the pipeline's WORK dir, where project.yaml is read from "
                         "(default: <work>/longlist_work)")
    ap.add_argument("--include-sheets", action="store_true",
                    help="also copy per-property .xlsx/.xlsm/.csv sources. Each one becomes a "
                         "SEPARATE tracker for the pipeline: one extra column-map round-trip "
                         "per file, and its rows merge in as further properties.")
    ap.add_argument("--allow-unevidenced-rows", action="store_true",
                    help="write the tracker even though some rows have no machine-readable "
                         "source. Records them in kato_unevidenced_rows.json next to project.yaml.")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    inputs = args.inputs or os.path.join(work, "longlist_inputs")
    tk_work = args.toolkit_work or os.path.join(work, "longlist_work")
    os.makedirs(inputs, exist_ok=True)
    os.makedirs(tk_work, exist_ok=True)
    ds = read_json(os.path.join(work, "properties", "_dataset.json"), {}) or {}
    props_all = ds.get("properties", [])
    props = dedupe_props(props_all)
    n_dupes = len(props_all) - len(props)

    wanted = DOC_EXTS + (SHEET_EXTS if args.include_sheets else ())
    per_row, copied, by_policy = copy_sources(work, inputs, props, wanted)

    # THE INVARIANT. Every row the tracker ships must have at least one machine-readable
    # source in the scanned folder that SURVIVES the pipeline's content de-duplication.
    # Phrased as "this row has no readable source document", which is a fact about the file
    # system, and deliberately NOT as "this row has no upstream match": the dataset is built
    # exclusively from matched upstream records, so an unmatched row is not representable and
    # there is no field to test. A check written against a field that cannot be false is not
    # a check.
    unevidenced = []
    for p in props:
        order = int(p.get("order") or 0)
        files = per_row.get(order) or []
        if any(first for _n, first, _d in files):
            continue
        # Name the SURVIVING copy first: that is the file the pipeline will actually read, so
        # it is the one an operator has to open to see which row took these bytes. This row's
        # own copy is named second, in brackets, because it is the file they will otherwise
        # search the folder for - and it is the one that gets skipped.
        dupes = [(d or "(unknown)", n) for n, first, d in files if not first]
        if dupes:
            why = ("its only source document(s) are byte-identical to another row's and the "
                   "pipeline extracts identical bytes once, so the surviving copy evidences "
                   "that row, not this one: %s"
                   % ", ".join("%s (this row's skipped copy: %s)" % (d, n)
                               for d, n in dupes[:3]))
        else:
            sheets = [n for o, n in by_policy if o == order
                      and os.path.splitext(n)[1].lower() in SHEET_EXTS]
            if sheets and not args.include_sheets:
                why = ("its only source(s) are spreadsheets (%s), not copied by default - "
                       "pass --include-sheets" % ", ".join(sheets[:3]))
            else:
                why = "no readable source document exists for it in any of its folders"
        unevidenced.append((order, display_name(p), why))

    if unevidenced:
        head = ("%d of %d longlist row(s) would ship with NO machine-readable source in %s. "
                "Every specification field on those cards would come from the tracker this "
                "helper generates, with no page-cited evidence behind any value, and no gate "
                "downstream can tell the difference."
                % (len(unevidenced), len(props), inputs))
        body = ["  - row %02d  %s\n      %s" % (o, nm, why) for o, nm, why in unevidenced]
        if not args.allow_unevidenced_rows:
            # REFUSE, rather than warn. The entire defect class being fixed here is "nothing
            # fails and the run is silently wrong"; a warning printed into a long stdout that
            # an orchestrator skims re-creates exactly that class. Refusing also refuses
            # cheaply: the documents are already copied, so the retry is one flag away. The
            # tracker is NOT written, so the pipeline cannot be run on a corpus with no rows
            # at all - it stops at intake with its own named gap rather than half-building.
            print("ERROR: " + head, file=sys.stderr)
            for ln in body:
                print(ln, file=sys.stderr)
            print("\n  Either add the missing source document(s) to the property folder(s) and "
                  "re-run,\n  or re-run with --allow-unevidenced-rows to ship anyway and have "
                  "the affected\n  rows recorded in %s.\n  Tracker and project.yaml NOT written."
                  % os.path.join(tk_work, "kato_unevidenced_rows.json"), file=sys.stderr)
            sys.exit(2)
        print("WARNING (--allow-unevidenced-rows): " + head)
        for ln in body:
            print(ln)
        with open(os.path.join(tk_work, "kato_unevidenced_rows.json"), "w", encoding="utf-8") as fh:
            json.dump({"note": "Longlist rows shipped with no machine-readable source document "
                               "in the pipeline's scanned inputs folder. Every specification "
                               "field on these cards traces only to the generated tracker.",
                       "inputs_folder": inputs,
                       "rows": [{"order": o, "property": nm, "reason": w}
                                for o, nm, w in unevidenced]}, fh, indent=2, ensure_ascii=False)

    wb = Workbook(); ws = wb.active; ws.title = "Availability"; ws.append(HEADERS)
    for p in props:
        a = p.get("address") or {}; sp = p.get("spec") or {}; og = p.get("outgoings") or {}
        r = p.get("rent") or {}; ags = p.get("agents") or []
        mp = (p.get("coordinates") or {}).get("map") or {}
        coord = f"{mp.get('lat')},{mp.get('lng')}" if mp.get("lat") is not None else ""
        agent = "; ".join(x for x in [p.get("agent_organisation"),
                                      (ags[0]["name"] if ags and ags[0].get("name") else None)] if x)
        rent = r.get("value") if r.get("value") is not None else (
            "tbd" if (r.get("text") or "").lower().startswith("on application") else (r.get("text") or "tbd"))
        ws.append([display_name(p), ", ".join(x for x in [a.get("line1"), a.get("line2")] if x),
                   a.get("town"), p.get("area") or a.get("town"), MARKET_COUNTRY_NAME,
                   a.get("postcode"), coord,
                   (p.get("size") or {}).get("sqft"), p.get("tenure"), sp.get("availability"),
                   rent, r.get("basis"), og.get("service_charge"), og.get("rates_payable"),
                   sp.get("clear_height"), sp.get("power"), sp.get("loading"), sp.get("yard"),
                   sp.get("parking"), sp.get("floor_loading"), sp.get("epc"), sp.get("breeam"),
                   agent, p.get("summary")])
    wb.save(os.path.join(inputs, "Kato Longlist - Availability Schedule.xlsx"))

    client = cfg.get("client") or ds.get("client") or "Kato Longlist"
    ors = cfg.get("ors_api_key") or ""
    with open(os.path.join(tk_work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write(project_yaml(client, ors, inputs))

    evidenced = sum(1 for p in props
                    if any(f for _n, f, _d in (per_row.get(int(p.get("order") or 0)) or [])))
    print(f"tracker -> {inputs} ({len(props)} rows, {n_dupes} multi-broker duplicate(s) merged) "
          f"| project.yaml -> {tk_work} | client={client!r} | ors_key={'set' if ors else 'MISSING'}")
    print(f"source documents -> {inputs}: {len(copied)} file(s) copied, "
          f"{evidenced}/{len(props)} row(s) carry a readable source"
          + (f" | {len(by_policy)} per-property file(s) left out by policy "
             f"(images/emails/sheets)" if by_policy else ""))
    if copied:
        # Say this ONCE, here, because it is a direct consequence of shipping the documents
        # and it surprises an operator who has only ever seen the column-map exit: with a
        # tracker AND documents there is now more than one record source, so the pipeline's
        # cross-source match adjudication becomes reachable and WILL pause the run for any
        # pair it cannot resolve on its own. That is correct behaviour, not a fault.
        print("note: the corpus now holds more than one record source, so the pipeline's "
              "cross-source match adjudication can pause the run (see SKILL.md step 7b). "
              "A document stating a DIFFERENT postal code from its tracker row can never be "
              "merged with it and will ship as a separate card - check the exit's candidate "
              "list rather than approving it blind.")


if __name__ == "__main__":
    main()
