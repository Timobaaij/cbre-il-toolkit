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

WHAT THE MASTER LIST DOES TO THIS STEP
--------------------------------------
If master_list.json exists (stage 2.5), it decides WHICH properties exist from here on.
This is the one place the user's include/exclude bites, and it is here rather than in each
later stage because every later stage already reads _dataset.json and nothing else: filter
once and the tracker, the photo injection, the canonical patch, the client Excel and the
dashboard all inherit it, with no second list to keep in step.

Three consequences worth stating, because each of them is a decision rather than plumbing:

  * An EXCLUDED row is dropped from the dataset, but if the user rejected it inside a
    duplicate group its FOLDER is handed to the surviving row as a _dedupe_folders sibling.
    The rejected listing is often the one carrying the only brochure, and the survivor would
    otherwise ship with no page-cited evidence behind a single specification field.
  * The user's run notes are carried onto each record as `run_notes`. They are INSTRUCTIONS
    ("split this unit into three cards", "run but without rent") and this script does not
    interpret them: it moves the text so the model reads it at enrichment and the Gaps
    Report can state what was asked for. It DOES, however, refuse to build until every note
    has been answered in writing. See below.

THE RUN-NOTE GATE
-----------------
Carrying an instruction is not the same as following one, and until this gate existed the
difference was invisible. Nothing in Python reads what a note SAYS, so "split this unit into
three cards" happened only because the model chose to act on it, and nothing afterwards
checked that three cards existed. On a forty-row run with six notes, a skipped note produced
a complete-looking deliverable with no error anywhere: exactly the silent-wrong-answer shape
this repository keeps having to guard against.

So every property carrying a run note must have a `run_note_done` block in enrichment.json:

    "overrides": {"05 - Derby 167 - DE24 9FU": {
        "run_note_done": {"note": "Split unit in 3 cards",
                          "status": "done",
                          "action": "Created three records, one per unit on the masterplan, "
                                    "sized 55/56/56k sq ft from page 4 of the brochure."},
        "rent": ..., "spec": ...}}

`note` is the user's own text, quoted back. It is the part that makes this a check rather
than a checkbox: an acknowledgement written against a DIFFERENT note is an acknowledgement
written before the user last changed their mind, and it is rejected. `status` is one of
`done`, `partial` or `not_possible`, and the last two are legitimate answers that SHIP, with
the note and the reason carried into the Gaps Report so the user reads it there rather than
discovering it in the dashboard. `action` must be a sentence somebody can check, not a tick.

The refusal happens before anything is written, so a rejected run leaves no half-built
dataset. `--allow-unacknowledged-notes` overrides it and records every unanswered note as a
gap instead, for the case where a note genuinely needs no action at this stage.
  * Every record is stamped `_master_adjudicated`, which switches OFF the automatic merge in
    common.dedupe_props. Once a person has looked at the duplicate groups and answered, an
    automatic merge on postal code and floor area can only overrule them.

With no master_list.json nothing below changes and the old behaviour stands.
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
    # "tbd" et al are placeholders, not rents. They reach here from a property materialised
    # off the master list, where an unstated rent is written as the workbook's own "tbd"
    # filler. Treated as a value they ship the literal word "tbd" onto the card, labelled as
    # a Kato structured field, which is both wrong and reads as a broken deliverable rather
    # than as the absent quote it is. The correct answer is the "On application" fallback.
    if s and s.lower() not in ("- non-quoting", "non-quoting", "rent on application", "roa",
                               "-", "poa", "", "tbd", "n/a", "na", "not stated", "none"):
        return {"value": None, "text": s, "basis": "Kato structured", "source": "Kato structured",
                "provenance": "Kato structured field"}
    return None

ACK_STATUS = ("done", "partial", "not_possible")
# An action has to be a sentence a reader can check against the deliverable. Ten characters
# is not a quality bar and is not meant as one: it is the shortest string that cannot be a
# tick, a full stop or a "yes", which are the three things a gate like this actually attracts.
MIN_ACTION = 10


def _norm_note(v):
    return " ".join(str(v or "").split()).casefold()


def check_run_notes(run_notes, overrides):
    """Every run note answered in writing, or say which are not and why it matters.

    Returns (problems, acknowledged). Deliberately returns rather than exits: the caller
    refuses before writing anything, which is the whole point of running this first.
    """
    problems, acked = [], []
    for folder, note in sorted(run_notes.items()):
        ack = (overrides.get(folder) or {}).get("run_note_done")
        if not isinstance(ack, dict):
            problems.append((folder, note, "no run_note_done block in enrichment.json"))
            continue
        quoted = ack.get("note")
        if not _norm_note(quoted):
            problems.append((folder, note, "run_note_done.note is empty, so nothing shows WHICH "
                                           "instruction was acted on"))
            continue
        if _norm_note(quoted) != _norm_note(note):
            problems.append((folder, note, "run_note_done.note quotes a different instruction "
                                           "(%r), so the acknowledgement predates the note now on "
                                           "the master list" % quoted))
            continue
        status = str(ack.get("status") or "").strip().lower()
        if status not in ACK_STATUS:
            problems.append((folder, note, "run_note_done.status is %r, must be one of %s"
                             % (ack.get("status"), " / ".join(ACK_STATUS))))
            continue
        action = str(ack.get("action") or "").strip()
        if len(action) < MIN_ACTION:
            problems.append((folder, note, "run_note_done.action is empty or too short to check "
                                           "(%r): state what you actually did" % ack.get("action")))
            continue
        acked.append((folder, note, status, action))
    return problems, acked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--enrichment", default=None, help="path to model enrichment.json (default: work/enrichment.json)")
    ap.add_argument("--master-list", default=None,
                    help="stage 2.5 decisions (default: work/master_list.json). Absent means no "
                         "include/exclude filtering and the pre-2.5 behaviour.")
    ap.add_argument("--allow-unacknowledged-notes", action="store_true",
                    help="build even though some of the user's run notes have no run_note_done "
                         "block in enrichment.json. Each one is recorded as a gap instead.")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    props_dir = os.path.join(work, "properties")
    index = read_json(os.path.join(props_dir, "_index.json"), {}) or {}

    enr_path = args.enrichment or os.path.join(work, "enrichment.json")
    enr = read_json(enr_path, {}) or {}
    overrides = enr.get("overrides", enr) if isinstance(enr, dict) else {}

    # Stage 2.5's answers. Absent on a run that skipped the master list, in which case every
    # set below is empty and the loop behaves exactly as it did before.
    ml_path = args.master_list or os.path.join(work, "master_list.json")
    ml = read_json(ml_path, {}) or {}
    excluded = set(ml.get("excluded_folders") or [])
    merge_map = ml.get("merge_map") or {}          # excluded folder -> surviving folder
    merge_detail = ml.get("merge_detail") or {}
    run_notes = ml.get("run_notes") or {}
    adjudicated = bool(ml)
    # Invert once: surviving folder -> the folders merged into it.
    siblings = {}
    for src, dst in merge_map.items():
        if dst:
            siblings.setdefault(dst, []).append(src)

    # BEFORE anything is written, so a refusal leaves no half-built dataset behind.
    note_problems, note_acked = check_run_notes(run_notes, overrides)
    note_gaps = {}
    if note_problems:
        head = ("%d of %d run note(s) the user wrote on the master list have not been answered "
                "in enrichment.json. Nothing in this pipeline reads what a note SAYS, so an "
                "unanswered note produces a complete-looking deliverable with the instruction "
                "silently dropped." % (len(note_problems), len(run_notes)))
        body = ["  - %s\n      note: %s\n      %s" % (f, n, why) for f, n, why in note_problems]
        if not args.allow_unacknowledged_notes:
            print("ERROR: " + head, file=sys.stderr)
            for ln in body:
                print(ln, file=sys.stderr)
            print("\n  Add a run_note_done block to each override (note / status / action) and "
                  "re-run,\n  or re-run with --allow-unacknowledged-notes to build anyway and have "
                  "each one\n  recorded in properties/_gaps.json. Nothing was written.",
                  file=sys.stderr)
            sys.exit(2)
        print("WARNING (--allow-unacknowledged-notes): " + head)
        for ln in body:
            print(ln)
        for f, n, why in note_problems:
            note_gaps[f] = {"run_note": n, "run_note_status": "unanswered", "run_note_detail": why}
    # partial and not_possible are legitimate answers, and they SHIP. They belong in the Gaps
    # Report so the user meets them there rather than in the finished dashboard.
    for f, n, status, action in note_acked:
        if status != "done":
            note_gaps[f] = {"run_note": n, "run_note_status": status, "run_note_detail": action}

    dataset, gaps, dropped = [], [], []
    for p in index.get("properties", []):
        folder = p["folder"]; pdir = os.path.join(props_dir, folder)
        if folder in excluded:
            dropped.append((folder, "merged into %s" % merge_map[folder] if merge_map.get(folder)
                            else "excluded on the master list"))
            continue
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
            # A property materialised from the master list has no Kato match, so there is no
            # listing to link to. None, not a URL with "None" in it: a link that 404s reads as
            # a broken deliverable, where an absent link reads as what it is.
            "links": {"website": d.get("website"),
                      "kato_listing": (f"https://agency.kato.app/#/requirements/{index.get('requirement_id')}/manage/shortlist/{p['match_id']}?table_tab=longlist"
                                       if p.get("match_id") else None)},
            "messages": d.get("messages"),
            "notes": ov.get("notes"),
            "_provenance": {"rent": rent.get("provenance"), "rent_source": rent.get("source"),
                            "specs": "model from key_points/emails" if spec else "not set",
                            "core": "Kato API" if p.get("match_id") else
                                    "master list (%s)" % (p.get("source_type") or "user supplied")},
        }
        if adjudicated:
            # Switches off the automatic merge in common.dedupe_props for this whole dataset.
            rec["_master_adjudicated"] = True
            rec["run_notes"] = run_notes.get(folder) or None
            # The audit trail for the gate above: what the user asked and what was done about
            # it, on the record itself, so the Source Ledger and any later run can both see it.
            rec["run_note_done"] = ov.get("run_note_done") if run_notes.get(folder) else None
            sib = siblings.get(folder) or []
            if sib:
                # Same underscore contract as dedupe_props: internal audit keys, never a
                # client-facing field, so the merged listing's broker detail cannot leak into
                # copy that must carry no attribution.
                rec["_dedupe_folders"] = sorted(set((rec.get("_dedupe_folders") or []) + sib))
                who = "; ".join("%s (%s)" % (s, (merge_detail.get(s) or {}).get("property") or "?")
                                for s in sorted(sib))
                rec["_dedupe_note"] = ("Same unit rejected on the master list under another "
                                       "listing and merged here: %s." % who)
        write_json(os.path.join(pdir, "property.json"), rec)
        dataset.append(rec)
        g = {"folder": folder}
        if rec["rent"]["text"] == "On application":
            g["rent"] = "none"
        missing = [k for k in ("clear_height", "power") if not rec["spec"].get(k)]
        if missing:
            g["specs_missing"] = missing
        # An unanswered, partly answered or impossible run note is a gap in the deliverable
        # the user asked for, not an internal detail, so it goes where the Gaps Report reads.
        g.update(note_gaps.get(folder) or {})
        if len(g) > 1:
            gaps.append(g)

    write_json(os.path.join(props_dir, "_dataset.json"),
               {"requirement_id": index.get("requirement_id"), "count": len(dataset), "properties": dataset})
    write_json(os.path.join(props_dir, "_gaps.json"), {"gaps": gaps})
    broker = sum(1 for r in dataset if r["rent"]["provenance"].startswith("broker"))
    withrent = sum(1 for r in dataset if r["rent"]["text"] != "On application")
    print(f"DONE. properties={len(dataset)} rent_populated={withrent} broker_quoted={broker} gaps={len(gaps)}", flush=True)
    if adjudicated:
        notes_n = sum(1 for r in dataset if r.get("run_notes"))
        print("  master list: %d dropped, %d run note(s) to honour at enrichment"
              % (len(dropped), notes_n), flush=True)
        for folder, why in dropped:
            print("    - %s (%s)" % (folder, why), flush=True)
        if notes_n:
            status_by = {f: s for f, _n, s, _a in note_acked}
            for r in dataset:
                if r.get("run_notes"):
                    print("    note  [%s] %s: %s"
                          % (status_by.get(r["folder"], "UNANSWERED"), r["folder"], r["run_notes"]),
                          flush=True)

if __name__ == "__main__":
    main()
