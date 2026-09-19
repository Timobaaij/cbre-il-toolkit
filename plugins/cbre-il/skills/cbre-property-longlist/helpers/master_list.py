#!/usr/bin/env python3
"""master_list.py - the spine side of the MASTER LIST: enumerate every candidate option the
run has found so far, key each one durably, and read the user's answer back for the four
places that obey it.

WHY THIS STAGE EXISTS AT ALL
----------------------------
On the Kapdaa run the broker learned what the run had decided to build by reading the FINISHED
dashboard. Everything before that point decided scope on its own: the tracker contributed one
row per line whether or not the line was a live option, a brochure that happened to be in the
folder became a card, an option named only in an email body reached the deliverable only if a
later agent happened to write a record for it, and the one question that asks a human which
source governs the longlist - the exit-13 source-authority question - is asked AFTER matching
and merging have settled, which is after every brochure has already been read by its own vision
agent. That ordering has two costs and they are different costs:

  * MONEY AND TIME. One reader agent per deck, vision on the raster ones, is the most expensive
    step in the pipeline, and it ran on decks the broker would have struck off in two seconds.
  * TRUST. By the time the authority question arrives, the run has already formed an opinion
    about what exists, and the question is phrased in terms of that opinion ("these 14 are only
    in the brochures"). A broker answering it is editing the run's conclusion rather than
    setting the run's scope.

So the inventory is put in front of the user FIRST, in one sheet, and only the rows they mark
Yes are built. The sheet is the single source of truth for scope from that point on.

WHERE IT SITS, AND WHY NOT SOMEWHERE CHEAPER
--------------------------------------------
After the cheap reads (tracker rows, email bodies), before the deck readers. Earlier is
cheaper and useless: before anything is read the run knows filenames and nothing else, and a
sheet of filenames is not a decision a broker can take. Later is cleaner and too late: after
match and merge every brochure has already been read, which is precisely the cost this exists
to avoid paying on rows nobody wanted.

The price of the middle position is that option identity is NOT final when the sheet is built:
two rows on it can be one building. That is why the sheet carries duplicate groups (the model's
adjudication, with a blunt postcode sweep behind it) rather than pretending the rows are
distinct, and why the user's groups are written back into work/match_decisions.json as `same`
verdicts instead of being thrown away - the pairs the user already grouped are not asked again
at exit 10.

WHAT LIVES HERE AND WHAT LIVES IN THE TWO PORTED SCRIPTS
--------------------------------------------------------
This module is the SPINE's half: it enumerates candidate rows from the records already on disk
plus the brochure clusters intake found, keys them, runs the postcode sweep, and reads the
answered sheet back for the four consumers (deck dispatch, source authority, match seeding, the
Gaps Report). `master_list_build.py` turns the candidates into the workbook and
`master_list_read.py` turns the answered workbook into work/master_list.json; both are ported
from kato-longlist, which has run this pattern in anger, and both are standalone CLIs because
the user's answer arrives between them.

ROW IDENTITY IS THE WHOLE CONTRACT. Every answer is keyed on a Row ID that must survive a
re-run, a re-sort of the sheet and a second email export. A tracker row is keyed on its source
file plus the sheet!cell locator the extractor already recorded in `__meta.prov`; an email row
the same way on its message; a brochure row on its cluster's file set. None of those depend on
position in a list, so a user who sorts the sheet by size loses nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

AUTO_CANDIDATES = "master_candidates_auto.json"   # written by the spine
MODEL_CANDIDATES = "master_candidates.json"       # written by the orchestrator (judgement)
WORKBOOK = "Master List.xlsx"
MANIFEST = "master_list_manifest.json"
ANSWERS = "master_list.json"                      # written by master_list_read.py
EXTERNAL = "master_list_external.json"            # the disclosure a wrapper-owned scope leaves

# ------------------------------------------------------------------ scope owned upstream

def external_scope(cfg: dict | None) -> dict | None:
    """`master_list: {mode: external, confirmed_by: "..."}` from project.yaml, or None.

    WHAT IT IS FOR. A wrapper skill can already own the scope decision. kato-longlist does: it
    builds its OWN master list at its step 2.5, puts that workbook to the operator, reads it back,
    and only then generates this skill's project.yaml and inputs folder from the rows that
    survived. The spine's exit-17 stop would then put a SECOND sheet in front of the same person,
    listing the same options they had just finished striking off, with no new information on it.
    A gate that asks a question the user has visibly already answered does not get answered
    carefully the second time; it gets answered "Yes to everything" for the rest of its life, and
    then it protects nothing on the run where it mattered.

    WHAT IT DELIBERATELY DOES NOT DO. It declines the stop and NOTHING else. It is not an answer,
    so `master_list.json` is not written and none of the four consumers can read one: the source
    authority is not derived from it (the exit-13 question is asked exactly as it was before this
    stage existed), no `same` verdicts are seeded into `match_decisions.json`, and no deck is
    skipped. The run is byte-identical to the pre-master-list spine apart from one line in the
    Gaps Report saying where scope was settled. Anything more would mean a wrapper's config key
    silently suppressing a question this skill asks on its own evidence.

    ABSENT MEANS INTERACTIVE. A missing key, an unparseable one, a misspelt mode - all of them
    leave the stop in place. The failure of a scope gate must be that it fires when it need not,
    never that a typo in a config file turns it off.
    """
    ml = (cfg or {}).get("master_list")
    if not isinstance(ml, dict):
        return None
    if str(ml.get("mode") or "").strip().lower() != "external":
        return None
    by = str(ml.get("confirmed_by") or "").strip()
    return {"mode": "external",
            "confirmed_by": by or "(not stated in project.yaml master_list.confirmed_by)"}


def write_external(work: Path, scope: dict, n_candidates=None) -> dict:
    """Record the declined stop under its OWN filename, never as an answer.

    A separate file rather than a flag inside `master_list.json` because the four consumers all
    read `master_list.json` and one of them - the source authority - acts on its mere presence.
    A shared file would need every one of them to remember to check a mode field, and the first
    one that forgot would hand a wrapper's config key the power to delete options from a client's
    longlist. There is nothing to remember if the file they read does not exist.
    """
    payload = {"mode": "external", "confirmed_by": str(scope.get("confirmed_by") or ""),
               "candidates_seen": n_candidates}
    Path(work, EXTERNAL).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return payload


YES, NO = "Yes", "No"

# Source-file suffixes that make a record an EMAIL record rather than a tracker row. Kept here
# rather than imported from clarify.AUTHORITY_FAMILIES because that mapping deliberately has no
# email family (an email may never EXCLUDE anything under the authority answer), while this one
# has to label an email row on the sheet so the user can see where the option came from.
EMAIL_EXTS = (".msg", ".eml")
TRACKER_EXTS = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")
DECK_EXTS = (".pdf", ".pptx", ".ppt")


# --------------------------------------------------------------------------- small helpers

def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def norm_postcode(v) -> str:
    """Whitespace- and case-insensitive postcode key for the blunt sweep.

    Deliberately NOT a country-aware parser. The sweep's whole job is to be cruder than the
    model's adjudication and catch what the model missed, and a parser that rejected 'DE74 2DF'
    because it is not the Dutch shape would silently stop catching duplicates on exactly the
    corpora this skill is used on. An empty string is never a key: a blank postcode is absence
    of evidence and grouping on it would put every unlocated row in one meaningless group.
    """
    s = re.sub(r"[^A-Za-z0-9]+", "", str(v or "")).upper()
    return s if len(s) >= 4 else ""


def _locator(rec: dict) -> str:
    """The first provenance locator the record carries ('Sheet1!B14', 'p3', ...), or ''.

    This is the record's own statement of WHERE it came from inside its file, written by the
    extractor, so it is stable across re-extractions of an unchanged file. It is what makes a
    tracker row's id survive a re-run: the alternative, the record's index in the parsed list,
    moves the moment a row is inserted above it, which would silently re-ask the user about
    every row below the insertion.
    """
    prov = ((rec.get("__meta") or {}).get("prov") or {})
    if isinstance(prov, dict):
        for v in prov.values():
            tok = str(v or "").split()[0].strip() if str(v or "").strip() else ""
            if "!" in tok or re.match(r"^p\d+$", tok):
                return tok
    return ""


def source_file(rec: dict) -> str:
    return str((rec.get("__meta") or {}).get("source_file") or "")


def record_row_id(rec: dict) -> str:
    """The Row ID for a tracker or email record: `<family>:<source file>|<locator or digest>`.

    NOT POSITIONAL, and that is load-bearing rather than tidy. The id is computed in two places
    that see the records in DIFFERENT orders - the candidate enumeration walks one record file at
    a time, while the match seeding and the exclusion filter walk every record in the run
    concatenated - so an id containing a list index would agree in one of them and silently
    disagree in the other. The failure that produces is the worst kind available here: the sheet
    would look answered, the ids would not resolve, and the user's No would quietly do nothing.

    A record's own provenance locator ('Sheet1!B14') is the first choice, because the extractor
    writes it and it survives a re-extraction of an unchanged file. A record with no locator
    falls back to a digest of its own values, which is order-independent for the same reason and
    changes only when the record itself changes - and a changed record set re-opens the sheet
    anyway, with every still-matching answer carried forward by Row ID.
    """
    src = Path(source_file(rec)).name
    # `source_type` is consulted as well as the extension because an EMAIL record does not carry
    # a filename in `source_file`: extract_email stamps the SUBJECT there ("RE: Packington Hill"),
    # which ends in none of EMAIL_EXTS. Keying on the extension alone therefore filed every email
    # record under the tracker family, and the row on the sheet said "Source file" where the user
    # needed to read "Email" before deciding whether a one-line mention in prose is a real option.
    meta_type = str((rec.get("__meta") or {}).get("source_type") or "").strip().lower()
    fam = "email" if (src.lower().endswith(EMAIL_EXTS) or meta_type == "email") else "row"
    loc = _locator(rec)
    if not loc:
        payload = json.dumps({k: v for k, v in sorted(rec.items()) if k != "__meta"},
                             ensure_ascii=False, default=str)
        loc = "h" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"{fam}:{src}|{loc}"


def email_row_id(rel_path) -> str:
    """The Row ID for one EMAIL MESSAGE: `email:<basename>|<digest of its path in the folder>`.

    Keyed on the message's path inside the inputs folder rather than on its subject or its
    position. Two brokers send "RE: your requirement" on the same morning and the subjects
    collide; the per-email folder keeps the files apart, so the path is the only thing here that
    separates them - the same reasoning that re-keyed `extract_email.from_email_index` on the
    relative path in item 3, and the same failure if it is ignored: two messages sharing one row,
    one broker's No silently striking the other broker's option.
    """
    rel = Path(str(rel_path)).as_posix().lower()
    h = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"email:{Path(rel).name}|{h}"


def cluster_row_id(label: str, files) -> str:
    """The Row ID for one brochure cluster: its label plus a digest of its file set.

    The digest is in the id on purpose. A cluster is the unit the deck reader is dispatched on,
    so if a second brochure joins the cluster the thing the user said Yes to is not the thing
    the run would now read, and the row must be re-offered rather than inherit an answer given
    about a different document set.
    """
    names = sorted(Path(str(f)).name for f in (files or []))
    h = hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(label or "deck")).strip("_")[:40] or "deck"
    return f"deck:{slug}|{h}"


def _num(v):
    if v in (None, "", "tbd"):
        return None
    try:
        return float(str(v).replace(",", "").replace(" ", ""))
    except Exception:
        return None


# ------------------------------------------------------------------- candidate enumeration

def _record_rows(records_by_file: dict) -> list:
    """One candidate row per tracker / email record already on disk.

    Deliberately permissive about missing fields, for the same reason the Kato port is: an
    option first named in one line of an email ('we also have Packington Hill, 140k, Q2 2027')
    has no coordinates and no agent, and refusing it here would push exactly the options this
    step exists to surface back out of the inventory. Blanks ship as blanks; the row still
    carries a Yes/No decision.
    """
    rows = []
    for src, recs in sorted(records_by_file.items()):
        base = Path(src).name
        low = base.lower()
        if low.endswith(DECK_EXTS):
            continue  # a deck's records belong to its cluster row, not to a row of their own
        for r in recs:
            if not isinstance(r, dict) or r.get("unreadable"):
                continue
            # Per record, not per file: an email record's `source_file` is its SUBJECT, so the
            # file-level extension test alone labelled it "Source file". See record_row_id.
            meta_type = str((r.get("__meta") or {}).get("source_type") or "").strip().lower()
            src_type = ("Email" if (low.endswith(EMAIL_EXTS) or meta_type == "email")
                        else "Tracker" if low.endswith(TRACKER_EXTS) else "Source file")
            name = (r.get("park") or r.get("address") or r.get("city") or "").strip()
            if not name:
                # A row with no name at all cannot be judged by a human, and inventing one
                # ("Option 7") would put a decision in front of the user that they cannot take.
                # It is counted in `unnamed` on the candidates file instead, so the count on the
                # sheet's footer and the count of records the run holds can be reconciled.
                continue
            loc = _locator(r)
            rows.append({
                "row_id": record_row_id(r),
                "property": name,
                "source_type": src_type,
                "source": f"{base}{(' ' + loc) if loc else ''}",
                "source_files": [base],
                "record_locator": loc,
                "address": str(r.get("address") or ""),
                "postcode": str(r.get("postcode") or ""),
                "city": str(r.get("city") or ""),
                "lat": _num(r.get("lat")),
                "lon": _num(r.get("lng")),
                "size_from": _num(r.get("warehouseArea")),
                "size_to": _num(r.get("warehouseArea")),
                "size_unit": str(r.get("areaUnit") or ""),
                "rent": str(r.get("warehouseRent") or ""),
                "availability": str(r.get("status") or ""),
                "agent": str(r.get("landlord") or r.get("developer") or ""),
                "files": [],
                "brochure": NO,
                "brochure_detail": "No document held for this row - it is source text only",
                "notes": "",
            })
    return rows


def _email_rows(folder: Path, emails, taken: set, email_attachments=None) -> list:
    """One candidate row per EMAIL MESSAGE on disk, read deterministically by the spine.

    WHY THIS IS NOT LEFT TO THE SUB-AGENT. The first cut of this stage enumerated tracker records
    and brochure clusters and nothing else, and left the email-only options to the exit-17 prompt:
    the model reads the bodies and adds rows. That was written before item 3 landed, when the
    emails genuinely were an agent step. They are not any more - `intake` opens every .msg/.eml in
    the folder (and inside any zip) to harvest its attachments, so by the time this stage runs the
    messages have already been parsed once by deterministic code. Leaving the rows to the model
    meant the ONE input class that can hold an option nobody else listed was the one class whose
    presence on the scope sheet depended on a sub-agent remembering to do an optional step. An
    option that never reaches the sheet is not struck off by anybody; it just is not built, and
    nothing in the run says so.

    So every message gets a row here, whether or not the model adds a finer one. The row is the
    MESSAGE, not an adjudicated option: one email can name three buildings, and splitting prose
    into options is judgement, which is what the prompt still asks the model for. The row's name
    is the subject and its note says so, so a user reading the sheet knows they are deciding
    whether the message's contents are in scope, not ticking off one shed.

    `taken` holds the source keys already covered by a record row, so a corpus where an agent HAS
    written per-option email records does not get both those rows and a coarse row for the same
    message - the finer rows win and this adds nothing.

    Attachments are never re-saved: `save_attachment_bytes=False`. intake already wrote them
    beside their email before classification, and a second write does not merge with the first,
    it clusters as its own option and the client sees the same building on two cards
    (`extract_email.extract` says the same thing for the same reason).
    """
    rows: list = []
    if not emails:
        return rows
    try:
        import extract_email as EM
    except Exception:
        # The enumeration is best-effort by contract: a run that cannot import the email reader
        # must still put its tracker rows and its decks to the user rather than wedge.
        return rows
    # extract() walks ONE directory and does not recurse, so it is called once per directory that
    # actually holds an email. The alternative - pointing it at the inputs root - would silently
    # miss every message that arrived inside a zip, which intake unpacks into a subfolder, and a
    # zipped export is the commonest shape a broker's email dump takes.
    # WHAT EACH MESSAGE BROUGHT WITH IT comes from the INVENTORY, not from the re-read above.
    # The re-read passes save_attachment_bytes=False (it must: intake already wrote those bytes,
    # and a second write clusters as a second option), and that path returns an empty `saved`
    # list by construction. Reading the row's attachments off the parse would therefore have
    # printed "no attachments" beside an email that shipped a brochure - a statement on the
    # user's scope sheet that is not merely absent but wrong. intake's own `email_attachments`
    # record is the one place that knows what was written.
    _att_by_email: dict = {}
    for _e in (email_attachments or []):
        if not isinstance(_e, dict):
            continue
        _k = Path(str(_e.get("email") or "")).as_posix().lower()
        if _k:
            _att_by_email[_k] = [str(s.get("file") or "") if isinstance(s, dict) else str(s)
                                 for s in (_e.get("saved") or [])]
    dirs = sorted({Path(str(rel)).parent.as_posix() for rel in emails})
    seen_ids = set()
    for d in dirs:
        sub = Path(folder) / d if d not in ("", ".") else Path(folder)
        if not sub.is_dir():
            continue
        try:
            recs = EM.extract(sub, save_attachment_bytes=False) or []
        except Exception:
            continue
        # extract() reports the subject in __meta.source_file and not the filename it came from,
        # so the messages are re-paired with the directory listing in the same sorted order the
        # reader used. Both sides sort the same directory, so the pairing is positional only
        # across a list neither side reorders.
        files = [p for p in sorted(sub.iterdir())
                 if p.is_file() and p.suffix.lower() in EMAIL_EXTS]
        if len(files) != len(recs):
            # A corrupt message is dropped by neither side (extract writes an `unreadable` stub),
            # but if the counts ever diverge the pairing is a guess, and a guessed provenance on
            # a scope sheet is worse than a missing row. Say nothing rather than mislabel.
            continue
        for p, r in zip(files, recs):
            if not isinstance(r, dict) or r.get("unreadable"):
                continue
            rel = (Path(d) / p.name).as_posix() if d not in ("", ".") else p.name
            subject = str(r.get("subject") or "").strip()
            keys = {p.name.lower(), subject.lower()} - {""}
            if keys & taken:
                continue
            rid = email_row_id(rel)
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            atts = [a for a in _att_by_email.get(rel.lower(), []) if a]
            # source_files carries BOTH spellings on purpose: the attachment-era records stamp
            # __meta.source_file as the email's FILENAME, while extract_email's own body records
            # stamp it as the SUBJECT. The exclusion filter matches records to rows on that field,
            # so a row that listed only one of the two would accept the user's No and then fail
            # to remove half of what the No was about.
            src_files = [p.name] + ([subject] if subject else [])
            rows.append({
                "row_id": rid,
                "property": subject or p.name,
                "source_type": "Email",
                "source": f"{rel}{(' - ' + str(r.get('date') or '')) if r.get('date') else ''}",
                "source_files": src_files,
                "email_file": rel,
                "record_locator": "",
                "address": "", "postcode": "", "city": "",
                "lat": None, "lon": None,
                "size_from": None, "size_to": None, "size_unit": "",
                "rent": "", "availability": "",
                "agent": str(r.get("from") or ""),
                "files": atts,
                "brochure": NO,
                "brochure_detail": (
                    "No - the message body only"
                    + (" (%d attachment(s) were saved and are judged on their own row(s): %s)"
                       % (len(atts), "; ".join(Path(a).name for a in atts[:4])) if atts else "")),
                "notes": ("One row for the WHOLE MESSAGE, enumerated by the spine from the file "
                          "on disk. If this email names several buildings, the master-list "
                          "sub-agent splits it into one row per option; until it does, a No here "
                          "strikes off everything the message contributed."),
            })
    return rows


def _cluster_rows(clusters: dict, folder: Path, first_page_text) -> list:
    """One candidate row per BROCHURE CLUSTER - the unit a reader agent is dispatched on.

    Per cluster, not per file, because the cluster is what the run would read as one option and
    what the user is therefore being asked about. Name, postcode and size come from the cluster
    label plus the first page's text, which is the cheapest evidence that exists before the
    expensive read: it is enough to recognise a scheme, and it is explicitly NOT treated as data
    anywhere else - nothing from this row reaches a card. If the user includes the row, the
    reader agent reads the deck properly and its record overwrites all of this.
    """
    rows = []
    for label, cl in sorted((clusters or {}).items()):
        files = [*(cl.get("pdfs") or ([cl["pdf"]] if cl.get("pdf") else [])),
                 *(cl.get("pptxs") or ([cl["pptx"]] if cl.get("pptx") else []))]
        if not files:
            continue
        names = [Path(str(f)).name for f in files]
        head = ""
        try:
            head = first_page_text(folder / files[0]) or ""
        except Exception:
            head = ""
        pc = ""
        m = re.search(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}|\d{4}\s?[A-Z]{2}|\d{5})\b",
                      head.upper())
        if m:
            pc = m.group(1)
        size = None
        ms = re.search(r"([\d][\d,\.]{3,})\s*(?:sq\s*\.?\s*(?:ft|m)|m2|m²|sqft|sqm)",
                       head, re.I)
        if ms:
            size = _num(ms.group(1))
        rows.append({
            "row_id": cluster_row_id(label, files),
            "property": str(label),
            "source_type": "Brochure",
            "source": "; ".join(names),
            "source_files": names,
            "cluster": str(label),
            "address": "",
            "postcode": pc,
            "city": str(cl.get("region") or ""),
            "lat": None, "lon": None,
            "size_from": size, "size_to": size,
            "size_unit": "",
            "rent": "", "availability": "",
            "agent": "",
            "files": names,
            "brochure": YES,
            "brochure_detail": "Yes - %d deck(s) on disk: %s" % (len(names), "; ".join(names)),
            "notes": ("Name, postcode and size on this row are read off the filename and the "
                      "deck's FIRST PAGE only - a cheap look, not the read. Include the row and "
                      "the deck is read properly."),
        })
    return rows


def _gnum(gid) -> int:
    m = re.search(r"(\d+)$", str(gid) or "")
    return int(m.group(1)) if m else 0


def apply_duplicates(rows: list, model_groups: dict | None = None) -> dict:
    """Group rows that may be the same building: the model's groups first, then a blunt sweep.

    The model's groups WIN where they exist - it has read the emails and can tell a phase of a
    scheme from a re-listing of it. The sweep then runs on postal code alone over what is left
    and is deliberately crude. It over-groups (one big park shares a postcode across genuinely
    separate units) and it SAYS SO in the status text, because the two errors are not
    symmetrical: a group the user glances at and dismisses costs a second, and a duplicate
    nobody caught puts the same building on the client's dashboard twice.

    Rows with no usable postcode are never swept. An empty string is not evidence of anything,
    and grouping on it would hand the user one meaningless group of every unlocated row.
    """
    by_id = {r["row_id"]: r for r in rows}
    meta, n = {}, 0
    for gid, g in sorted((model_groups or {}).items()):
        members = [by_id[m] for m in (g.get("members") or []) if m in by_id]
        if len(members) < 2:
            continue
        n = max(n, _gnum(gid))
        status = g.get("status") or "Flagged by the model as the same option"
        meta[gid] = {"origin": "model", "status": status,
                     "members": [r["row_id"] for r in members]}
        for r in members:
            r["duplicate_group"] = gid
            r["duplicate_status"] = status
            r["duplicate_note"] = g.get("note") or ""

    buckets: dict = {}
    for r in rows:
        if r.get("duplicate_group"):
            continue
        pc = norm_postcode(r.get("postcode"))
        if pc:
            buckets.setdefault(pc, []).append(r)
    for pc, group in sorted(buckets.items()):
        if len(group) < 2:
            continue
        n += 1
        gid = "D%d" % n
        sizes = {r.get("size_to") or r.get("size_from") for r in group}
        same_size = len(sizes) == 1 and None not in sizes
        status = ("SAME BUILDING? same postcode and floor area (auto)" if same_size
                  else "Same postcode, sizes differ (auto)")
        note = ("Automatic check on postal code %s only, not adjudicated: %s. %s"
                % (pc, "; ".join(r["property"] for r in group),
                   "Identical floor area, so most likely one option listed more than once."
                   if same_size else
                   "Could be separate units on one park, or one option quoted at two sizes."))
        meta[gid] = {"origin": "auto", "status": status,
                     "members": [r["row_id"] for r in group]}
        for r in group:
            r["duplicate_group"] = gid
            r["duplicate_status"] = status
            r["duplicate_note"] = note
    for r in rows:
        r.setdefault("duplicate_group", "")
        r.setdefault("duplicate_status", "")
        r.setdefault("duplicate_note", "")
    return meta


def fingerprint(rows: list) -> str:
    """A digest of the ROW IDENTITY SET, and nothing else.

    This is the resume predicate for the whole stage: an answered sheet is honoured for as long
    as the set of things there were to answer about has not changed, and a new deck or a new
    email changes it, which re-opens the exit with every still-matching answer carried forward
    by Row ID. Deliberately NOT a digest of the row VALUES: re-reading the same tracker can
    produce a cosmetically different size string, and re-asking a broker forty questions because
    a number gained a decimal place is how a gate gets disabled by the people it protects.
    """
    ids = sorted(str(r.get("row_id") or "") for r in rows or [])
    return hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:16]


def build_auto(work: Path, records_by_file: dict, clusters: dict, folder: Path,
               first_page_text, emails=None, email_attachments=None) -> dict:
    """Write work/master_candidates_auto.json - the spine's half of the candidate set.

    Four routes in, all deterministic: tracker records, email records an agent has already
    written, one row per email MESSAGE still on disk that no record row covers, and one row per
    brochure CLUSTER - which is where an attachment that arrived stapled to a .msg ends up,
    because intake saves it beside its email and classifies it in the same pass, exactly like a
    brochure dropped in the folder by hand.

    `emails` is the inventory's email list (paths relative to the inputs folder). It defaults to
    None so a caller that predates the email route gets the old behaviour rather than a TypeError.
    """
    rec_rows = _record_rows(records_by_file)
    taken = {str(s).lower() for r in rec_rows for s in (r.get("source_files") or [])
             if r.get("source_type") == "Email"}
    rows = (rec_rows
            + _email_rows(folder, emails, taken, email_attachments)
            + _cluster_rows(clusters, folder, first_page_text))
    groups = apply_duplicates(rows)
    payload = {
        "rows": rows,
        "duplicate_groups": groups,
        "input_hash": fingerprint(rows),
        "counts": {"rows": len(rows),
                   "from_records": sum(1 for r in rows if r["source_type"] != "Brochure"),
                   "from_emails": sum(1 for r in rows if r["source_type"] == "Email"),
                   "from_brochures": sum(1 for r in rows if r["source_type"] == "Brochure")},
    }
    p = Path(work) / AUTO_CANDIDATES
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


# --------------------------------------------------------------------- reading the answer

def load_answers(work: Path) -> dict:
    return _read_json(Path(work) / ANSWERS, {}) or {}


def is_answered(work: Path, current_hash: str = "") -> bool:
    """True when a master_list.json on disk settles THIS inputs set.

    Two ways it is not settled: there is no file, or the file answers a different set of rows
    (a deck or an email arrived after it was answered). The second case re-opens the stop; the
    builder then carries every still-matching answer forward by Row ID, so re-opening costs the
    user the new rows and nothing else.
    """
    ml = load_answers(work)
    if not ml or not (ml.get("rows") or ml.get("skipped")):
        return False
    if current_hash and str(ml.get("input_hash") or "") != str(current_hash):
        return False
    return True


def user_answered(work: Path) -> bool:
    """True only for a sheet a PERSON filled in.

    The headless bypass writes the same file with `skipped: true`, and that file must not be
    read as a scope decision: it includes everything by default, so treating it as the source
    authority would mean a cron run silently declares itself authoritative and suppresses the
    exit-13 question that would otherwise have been asked on the next interactive pass.
    """
    ml = load_answers(work)
    return bool(ml) and not ml.get("skipped") and bool(ml.get("rows"))


def _rows_of(ml: dict) -> list:
    return [r for r in (ml.get("rows") or []) if isinstance(r, dict)]


def excluded_cluster_labels(work: Path) -> set:
    """Cluster labels whose rows are ALL No - the decks the reader dispatch must skip.

    'All No' rather than 'any No' because a cluster carries exactly one row today, and an
    any-No rule would become a silent data-loss bug the moment that stops being true.
    """
    ml = load_answers(work)
    if not ml or ml.get("skipped"):
        return set()
    by_cluster: dict = {}
    for r in _rows_of(ml):
        cl = str(r.get("cluster") or "")
        if cl:
            by_cluster.setdefault(cl, []).append(str(r.get("include") or ""))
    return {cl for cl, answers in by_cluster.items()
            if answers and all(a == NO for a in answers)}


def excluded_rows(work: Path) -> list:
    ml = load_answers(work)
    if not ml or ml.get("skipped"):
        return []
    return [r for r in _rows_of(ml) if str(r.get("include") or "") == NO]


def _excluded_keys(ml: dict) -> tuple:
    """(record ids, deck filenames) the user excluded, as two lookup sets."""
    rec_ids, deck_files = set(), set()
    for r in _rows_of(ml):
        if str(r.get("include") or "") != NO:
            continue
        rid = str(r.get("row_id") or "")
        if rid.startswith("deck:"):
            deck_files |= {str(f).lower() for f in (r.get("source_files") or [])}
        elif rid:
            rec_ids.add(rid)
    return rec_ids, deck_files


def record_excluded(rec: dict, rec_ids: set, deck_files: set) -> bool:
    src = Path(source_file(rec)).name.lower()
    if src and src in deck_files:
        return True
    return record_row_id(rec) in rec_ids


def apply_to_clusters(clusters: list, work_or_answers) -> tuple:
    """Split settled match clusters into (kept, dropped) per the answered master list.

    The same three safety properties as `merge.apply_source_authority`, for the same reason -
    this is the only other code in the skill that can remove a property from a client's own
    longlist:

      * a cluster NO record of which maps to an excluded row is always kept;
      * a cluster is dropped only when EVERY record in it maps to a row the user marked No,
        so a deck that turned out to describe an included option keeps that option alive;
      * if the filter would empty the dataset nothing is dropped, because an empty dashboard is
        never the right reading of a sheet somebody filled in.

    `dropped` is returned, never discarded: deliver.py names each one in the Gaps Report.
    """
    ml = (work_or_answers if isinstance(work_or_answers, dict)
          else load_answers(work_or_answers))
    if not ml or ml.get("skipped"):
        return list(clusters or []), []
    rec_ids, deck_files = _excluded_keys(ml)
    if not rec_ids and not deck_files:
        return list(clusters or []), []
    kept, dropped = [], []
    for cl in clusters or []:
        recs = list(cl or [])
        hits = [record_excluded(r, rec_ids, deck_files) for r in recs]
        if recs and all(hits):
            dropped.append(cl)
        else:
            kept.append(cl)
    if not kept:
        return list(clusters or []), []
    return kept, dropped


def seed_match_decisions(records: list, work: Path) -> dict:
    """The user's duplicate groups, expressed as `same` verdicts keyed the way exit 10 keys them.

    A group on the sheet is a human saying 'these rows are one building'. Exit 10 exists to ask
    a sub-agent that same question about pairs nobody has answered, so a group the user already
    settled must not come back as a question - it would be asking the person who owns the
    deliverable to re-confirm their own decision through an intermediary.

    Keyed with `match.pair_id`, which is the id the spine itself would generate for the pair:
    an order-independent sha1 of the two records' (match_key + area). Writing any other key
    would produce a file that looks answered and covers nothing.

    Rows map to records the same way the exclusion filter maps them, so the two can never
    disagree about which record a row is. A group whose rows resolve to fewer than two records
    yields nothing - typically a group over two decks that have not been read yet, which is
    correct: those pairs cannot exist until their records do, and this runs again next pass.
    """
    import match as _m
    ml = load_answers(work)
    if not ml or ml.get("skipped"):
        return {}
    by_group: dict = {}
    for r in _rows_of(ml):
        g = str(r.get("duplicate_group") or "").strip()
        if g and str(r.get("include") or "") in (YES, NO):
            by_group.setdefault(g, []).append(r)
    if not by_group:
        return {}
    # row_id -> [records], built once over the whole record set
    members: dict = {}
    for rec in (records or []):
        if not isinstance(rec, dict):
            continue
        src = Path(source_file(rec)).name.lower()
        rid = record_row_id(rec)
        members.setdefault(rid, []).append(rec)
        members.setdefault(f"file:{src}", []).append(rec)
    out = {}
    for gid, rows in sorted(by_group.items()):
        recs: list = []
        for r in rows:
            rid = str(r.get("row_id") or "")
            if rid.startswith("deck:"):
                for f in (r.get("source_files") or []):
                    recs += members.get(f"file:{str(f).lower()}", [])
            else:
                recs += members.get(rid, [])
        # de-duplicate by identity, keep order
        seen, uniq = set(), []
        for rec in recs:
            if id(rec) not in seen:
                seen.add(id(rec))
                uniq.append(rec)
        for a_i in range(len(uniq)):
            for b_i in range(a_i + 1, len(uniq)):
                a, b = uniq[a_i], uniq[b_i]
                if _m.match_key(a) == _m.match_key(b) and a is b:
                    continue
                out[_m.pair_id(a, b)] = {
                    "verdict": "same",
                    "reason": (f"the broker grouped these on the master list as duplicate "
                               f"group {gid} - their decision, not an adjudication"),
                }
    return out


def write_headless(work: Path, auto: dict, reason: str) -> dict:
    """Include EVERYTHING, disclosed, for a run that has nobody to ask.

    A cron or SKIP_ALL run cannot stop for a sheet, and refusing to run would be worse than
    including everything: the run's honest behaviour without a master list is exactly what it
    did before this stage existed. What must never happen is that the bypass looks like an
    answer, so `skipped: true` rides on the file, `user_answered` returns False for it (the
    source-authority question is therefore still asked on the next interactive pass) and
    deliver.py prints the disclosure in the Gaps Report.
    """
    payload = {
        "skipped": True,
        "reason": reason,
        "input_hash": str((auto or {}).get("input_hash") or ""),
        "counts": {"rows": len((auto or {}).get("rows") or []),
                   "included": len((auto or {}).get("rows") or []), "excluded": 0},
        "rows": [{"row_id": r.get("row_id"), "property": r.get("property"),
                  "include": YES, "run_notes": "", "cluster": r.get("cluster"),
                  "source_files": r.get("source_files") or [],
                  "duplicate_group": r.get("duplicate_group") or ""}
                 for r in ((auto or {}).get("rows") or [])],
    }
    Path(work, ANSWERS).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return payload
