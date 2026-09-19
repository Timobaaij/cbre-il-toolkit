#!/usr/bin/env python3
"""master_list_build.py - build the MASTER LIST workbook: one row per candidate option this run
has found, for the user to accept or reject before the expensive half of the run starts.

Ported from kato-longlist/helpers/master_list_build.py, which has run this pattern on live
requirements. Copied rather than imported: a skill is a self-contained unit that a colleague can
copy to another machine, and a cross-skill import is a dependency nobody declares and everybody
breaks. The two copies are allowed to diverge, and they already have - this one has no Kato
index to read, its rows come from the spine's own candidates file, and its brochure column
states a fact about a cluster of decks rather than about a listing's document links.

WHAT THIS SCRIPT DECIDES, AND WHAT IT REFUSES TO DECIDE
-------------------------------------------------------
It MOVES BYTES. It reads work/master_candidates_auto.json (written by the spine: one row per
tracker record, per email record and per brochure cluster, with the blunt postcode sweep
already applied), merges work/master_candidates.json over it if the orchestrator wrote one (its
judged duplicate groups, its email-only rows, its rank), and writes the workbook.

It does NOT decide what a duplicate means, which email mention is a real option, or what order
the rows go in. Those are judgements. Run it with no model candidates file and you get the
spine's mechanical inventory alone, which is usable but blunter, and it says so on stdout.

RE-RUNNING IS SAFE, AND IS THE NORMAL CASE. A second email export lands, or three more
brochures; the sheet is rebuilt and every Include? and Run note already in it is carried forward
by the hidden Row ID before the rewrite. That is the whole reason the Row ID exists: the user is
free to sort, filter and re-rank the sheet, so row POSITION is not an identity. `--fresh`
discards the carried answers deliberately.

THE RED BROCHURE? COLUMN. A row with no machine-readable document is the one thing on this sheet
that costs the run something later: every specification field on its card would come from source
text with no page-cited evidence behind it, which is exactly what the evidence gates refuse. So
anything that is not a flat Yes is painted red with bold black text, as REAL conditional
formatting on the Brochure? cell alone rather than a static fill, so it still reads correctly
after the user sorts, filters or re-ranks the sheet.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import master_list as ML  # noqa: E402

from openpyxl import Workbook, load_workbook                      # noqa: E402
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation      # noqa: E402
from openpyxl.formatting.rule import FormulaRule                  # noqa: E402
from openpyxl.utils import get_column_letter                      # noqa: E402

WORKBOOK = ML.WORKBOOK
MANIFEST = ML.MANIFEST
SHEET = "Master list"
SHEET_DUPES = "Duplicate check"

# CBRE chrome, so the sheet a colleague opens is the one they have seen before. Green header
# band, amber for a row that overlaps another row, pale yellow for the two columns the user is
# being asked to fill in.
GREEN = "FF003F2D"
AMBER = "FFFFF2CC"
ASKED = "FFFFFFCC"
BAND = "FFF5F7F6"
NODOC = "FFFF8080"
FACE = "Arial"

HDR_ROW = 4
FIRST_ROW = 5
MIN_ROWS = 40          # spare rows below the data keep the validated Include? dropdown usable

INCLUDE_VALUES = ("Yes", "No")

# (header, key, width, number format, wrap)
COLUMNS = [
    ("Rank",                      "rank",             6,    "0",      False),
    ("Include?",                  "include",          11,   None,     False),
    ("Your Run notes for the AI", "run_notes",        26.3, None,     True),
    ("Property",                  "property",         34,   None,     True),
    ("Source type",               "source_type",      13,   None,     False),
    ("Source",                    "source",           46,   None,     True),
    ("Duplicate group",           "duplicate_group",  11,   None,     False),
    ("Duplicate status",          "duplicate_status", 26,   None,     True),
    ("Brochure?",                 "brochure",         12,   None,     False),
    ("Brochure detail",           "brochure_detail",  46,   None,     True),
    ("Address",                   "address",          34,   None,     True),
    ("Postcode",                  "postcode",         11,   None,     False),
    ("Town / city",               "city",             18,   None,     False),
    ("Size from",                 "size_from",        13,   "#,##0",  False),
    ("Size to",                   "size_to",          13,   "#,##0",  False),
    ("Size unit",                 "size_unit",        10,   None,     False),
    ("Quoting rent",              "rent",             20,   None,     True),
    ("Availability",              "availability",     22,   None,     True),
    ("Landlord / developer",      "agent",            30,   None,     True),
    ("Duplicate note",            "duplicate_note",   60,   None,     True),
    ("Notes from the source",     "notes",            70,   None,     True),
    # Hidden, and load-bearing. The user may sort, filter and re-rank freely, so row position is
    # not an identity. The Row ID travels with the row through any sort and is what
    # master_list_read.py keys every answer back onto. A row typed in by hand has no Row ID,
    # which is exactly how the read-back recognises one.
    ("Row ID",                    "row_id",           24,   None,     False),
]
KEYS = [c[1] for c in COLUMNS]
IDX = {k: i + 1 for i, (_h, k, *_r) in enumerate(COLUMNS)}
HIDDEN = {"row_id"}


# ------------------------------------------------------------------------------ candidates

def merge_candidates(auto: dict, model: dict) -> tuple:
    """Spine rows, plus the orchestrator's extra rows, with the orchestrator's groups on top.

    The model may add rows the spine cannot see (an option named only in the prose of an email
    whose body no extractor turned into a record) and may adjudicate duplicates the postcode
    sweep cannot (two spellings of one scheme in two different towns' postcodes). It may NOT
    delete a spine row: an inventory that quietly omits a candidate is worse than no inventory,
    because it looks complete. A model row whose id collides with a spine row is dropped with a
    warning for the same reason - the spine row is the one that maps back to real records.
    """
    rows = [dict(r) for r in (auto.get("rows") or [])]
    have = {r.get("row_id") for r in rows}
    added = 0
    for i, r in enumerate(model.get("rows") or [], 1):
        if not isinstance(r, dict) or not str(r.get("property") or "").strip():
            print("  WARNING: model candidate row %d has no 'property' name, skipped" % i,
                  file=sys.stderr)
            continue
        rid = str(r.get("row_id") or "cand:%02d" % i)
        if rid in have:
            print("  WARNING: model candidate row %r duplicates a spine row id - the spine row "
                  "is kept (it maps back to real records)" % rid, file=sys.stderr)
            continue
        have.add(rid)
        row = {"row_id": rid, "property": str(r.get("property")).strip(),
               "source_type": r.get("source_type") or "Email",
               "source": r.get("source") or "", "source_files": r.get("source_files") or [],
               "address": r.get("address") or "", "postcode": r.get("postcode") or "",
               "city": r.get("city") or "", "lat": r.get("lat"), "lon": r.get("lon"),
               "size_from": r.get("size_from"),
               "size_to": r.get("size_to") if r.get("size_to") is not None else r.get("size_from"),
               "size_unit": r.get("size_unit") or "", "rent": r.get("rent") or "",
               "availability": r.get("availability") or "", "agent": r.get("agent") or "",
               "files": r.get("files") or [], "notes": r.get("notes") or ""}
        row["brochure"] = r.get("brochure") or (ML.YES if row["files"] else ML.NO)
        row["brochure_detail"] = r.get("brochure_detail") or (
            "Yes - %d file(s) named: %s" % (len(row["files"]), "; ".join(row["files"]))
            if row["files"] else "No document held for this row - it is source text only")
        rows.append(row)
        added += 1
    # The groups are recomputed over the COMBINED set, model groups first, sweep behind them.
    # Recomputed rather than reused from the auto file because a model row can join a sweep
    # group, and a sheet whose amber rows disagree with its Duplicate check tab is a sheet
    # nobody trusts twice.
    for r in rows:
        r.pop("duplicate_group", None)
        r.pop("duplicate_status", None)
        r.pop("duplicate_note", None)
    meta = ML.apply_duplicates(rows, model.get("duplicate_groups") or {})
    return rows, meta, added


def apply_rank(rows: list, model: dict) -> None:
    """Order the sheet: the model's explicit order first, then everything it did not rank.

    Unranked rows keep a stable, predictable order (source type, then name) because a sheet
    whose rows move on every rebuild is a sheet whose answers cannot be trusted.
    """
    order = [str(x) for x in (model.get("rank") or [])]
    pos = {rid: i for i, rid in enumerate(order)}
    big = len(pos) + 1
    rows.sort(key=lambda r: (pos.get(r["row_id"], big),
                             str(r.get("source_type") or ""),
                             str(r.get("property") or "").lower()))
    for i, r in enumerate(rows, 1):
        r["rank"] = i


def carry_forward(path, rows) -> tuple:
    """Preserve the user's existing answers across a rebuild, keyed on Row ID.

    A rebuild happens for a real reason - a second email export landed, the user dropped in
    three more brochures - and it must not cost them the forty decisions they already made.
    Answers match on the hidden Row ID first, because that is an identity and survives any sort.
    A row the user TYPED IN has no Row ID, so those fall back to property name plus postcode;
    the fallback is only ever consulted for a prior row that carried no Row ID, so it can never
    override an identity match.
    """
    path = Path(path)
    if not path.exists():
        return 0, {}
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as e:
        print("  WARNING: could not read the existing workbook to carry answers forward (%s)" % e,
              file=sys.stderr)
        return 0, {}
    if SHEET not in wb.sheetnames:
        return 0, {}
    ws = wb[SHEET]
    hdr = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(HDR_ROW, c).value
        if v:
            hdr[str(v).strip()] = c
    if not all(h in hdr for h in ("Row ID", "Include?", "Your Run notes for the AI")):
        return 0, {}

    def nk(name, pc):
        import re as _re
        return (_re.sub(r"\s+", " ", str(name or "").strip().lower()),
                _re.sub(r"\s+", "", str(pc or "").strip().lower()))

    prior, by_name, manual = {}, {}, {}
    for r in range(FIRST_ROW, ws.max_row + 1):
        rid = ws.cell(r, hdr["Row ID"]).value
        inc = ws.cell(r, hdr["Include?"]).value
        note = ws.cell(r, hdr["Your Run notes for the AI"]).value
        name = ws.cell(r, hdr["Property"]).value if "Property" in hdr else None
        pc = ws.cell(r, hdr["Postcode"]).value if "Postcode" in hdr else None
        if not rid and not (inc or note):
            continue
        if not rid:
            manual[r] = {"Property": name, "Postcode": pc, "Include?": inc}
            if name and (inc or note):
                by_name[nk(name, pc)] = (inc, note)
            continue
        if inc or note:
            prior[str(rid).strip()] = (inc, note)
    kept, matched = 0, set()
    for row in rows:
        got = prior.get(row["row_id"])
        if got is None:
            key = nk(row.get("property"), row.get("postcode"))
            got = by_name.get(key)
            if got is not None:
                matched.add(key)
        if got:
            row["include"] = got[0] or ""
            row["run_notes"] = got[1] or ""
            kept += 1
    for r, rec in list(manual.items()):
        if nk(rec.get("Property"), rec.get("Postcode")) in matched:
            del manual[r]
    return kept, manual


# ------------------------------------------------------------------------------ the workbook

def _hdr_cell(ws, r, c, text):
    cell = ws.cell(r, c, text)
    cell.font = Font(name=FACE, sz=9, bold=True, color="FFFFFFFF")
    cell.fill = PatternFill("solid", fgColor=GREEN)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    return cell


def _flag_missing_documents(ws, last_data_row) -> None:
    """Red fill and bold black on every Brochure? cell that is not a flat Yes.

    The rule lives on the Brochure? COLUMN AND NOWHERE ELSE. This is a pre-delivery flag for the
    person scanning the sheet for rows with no document, so it belongs on the one cell that
    states the answer; spreading it across the neighbouring columns makes the sheet noisier
    without telling the reader anything more. Blank is excluded from the rule so the spare rows
    below the data, which carry the Include? dropdown and no property, are not painted red.
    """
    if last_data_row < FIRST_ROW:
        return
    broch = get_column_letter(IDX["brochure"])
    rng = "%s%d:%s%d" % (broch, FIRST_ROW, broch, last_data_row)
    rule = FormulaRule(
        formula=['AND($%s%d<>"",$%s%d<>"Yes")' % (broch, FIRST_ROW, broch, FIRST_ROW)],
        fill=PatternFill("solid", start_color=NODOC, end_color=NODOC),
        font=Font(name=FACE, sz=9, bold=True, color="FF000000"),
        stopIfTrue=False)
    ws.conditional_formatting.add(rng, rule)


def write_master(rows, title, note, footnotes) -> Workbook:
    thin = Side(style="thin", color="FFD9D9D9")
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.sheet_view.showGridLines = False

    t = ws.cell(1, 1, title)
    t.font = Font(name=FACE, sz=14, bold=True, color=GREEN)
    ws.row_dimensions[1].height = 18
    ws.cell(2, 1, note).font = Font(name=FACE, sz=9)

    for i, (h, key, w, _f, _wrap) in enumerate(COLUMNS, 1):
        _hdr_cell(ws, HDR_ROW, i, h)
        ws.column_dimensions[get_column_letter(i)].width = w
        if key in HIDDEN:
            ws.column_dimensions[get_column_letter(i)].hidden = True
    ws.row_dimensions[HDR_ROW].height = 33.95

    band = False
    for j, row in enumerate(rows):
        r = FIRST_ROW + j
        ws.row_dimensions[r].height = 45.95
        dup = bool(row.get("duplicate_group"))
        if not dup:
            band = not band
        base = AMBER if dup else (BAND if band else None)
        for i, (_h, key, _w, fmt, wrap) in enumerate(COLUMNS, 1):
            v = row.get(key)
            cell = ws.cell(r, i, v if v not in ("",) else None)
            cell.font = Font(name=FACE, sz=9)
            cell.border = Border(bottom=thin)
            if fmt:
                cell.number_format = fmt
            cell.alignment = Alignment(vertical="top", wrap_text=bool(wrap))
            fill = ASKED if key in ("include", "run_notes") else base
            if fill:
                cell.fill = PatternFill("solid", fgColor=fill)

    last = FIRST_ROW + max(len(rows), MIN_ROWS) - 1
    for r in range(FIRST_ROW + len(rows), last + 1):
        ws.row_dimensions[r].height = 45.95
        for key in ("include", "run_notes"):
            c = ws.cell(r, IDX[key])
            c.font = Font(name=FACE, sz=9)
            c.fill = PatternFill("solid", fgColor=ASKED)
            c.border = Border(bottom=thin)
            c.alignment = Alignment(vertical="top", wrap_text=(key == "run_notes"))

    _flag_missing_documents(ws, FIRST_ROW + len(rows) - 1)

    dv = DataValidation(type="list", formula1='"%s"' % ",".join(INCLUDE_VALUES),
                        allow_blank=True, showDropDown=False)
    dv.prompt = "Choose Yes or No"
    dv.promptTitle = "Include this option in the run?"
    ws.add_data_validation(dv)
    col = get_column_letter(IDX["include"])
    dv.add("%s%d:%s%d" % (col, FIRST_ROW, col, last))

    ws.auto_filter.ref = "A%d:%s%d" % (HDR_ROW, get_column_letter(len(COLUMNS)), last)
    ws.freeze_panes = "D%d" % FIRST_ROW

    r = last + 2
    for line in footnotes:
        c = ws.cell(r, 1, line)
        c.font = Font(name=FACE, sz=8, color="FF666666")
        r += 1
    return wb


def write_dupes(wb, rows):
    """The tab row 2 points at: every flagged group, its members side by side, nothing else.

    Separate from the master list because the decision it supports is a COMPARISON between two
    rows, and on a twenty-two column sheet sorted by rank those two rows are rarely adjacent.
    Read-only: the answer still goes in the Include? column on the master list, so there is
    exactly one place a decision lives.
    """
    ws = wb.create_sheet(SHEET_DUPES)
    ws.sheet_view.showGridLines = False
    groups = {}
    for r in rows:
        if r.get("duplicate_group"):
            groups.setdefault(r["duplicate_group"], []).append(r)

    ws.cell(1, 1, "Duplicate check").font = Font(name=FACE, sz=14, bold=True, color=GREEN)
    ws.cell(2, 1, "Each block below is one set of rows that may be the same option. Decide which "
                  "one to keep, then set Include? on the Master list tab. Nothing on this tab is "
                  "read by the run.").font = Font(name=FACE, sz=9)
    cols = [("Rank", "rank", 8), ("Property", "property", 40), ("Source type", "source_type", 14),
            ("Postcode", "postcode", 12), ("Size to", "size_to", 14),
            ("Quoting rent", "rent", 20), ("Landlord / developer", "agent", 30),
            ("Brochure detail", "brochure_detail", 46), ("Duplicate note", "duplicate_note", 70)]
    for i, (_h, _k, w) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    if not groups:
        ws.cell(4, 1, "No overlapping rows found.").font = Font(name=FACE, sz=9)
        return ws

    r = 4
    for gid in sorted(groups, key=ML._gnum):
        members = sorted(groups[gid], key=lambda x: x.get("rank") or 0)
        head = ws.cell(r, 1, "%s - %s" % (gid, members[0].get("duplicate_status") or
                                          "possible duplicate"))
        head.font = Font(name=FACE, sz=10, bold=True, color=GREEN)
        r += 1
        for i, (h, _k, _w) in enumerate(cols, 1):
            _hdr_cell(ws, r, i, h)
        r += 1
        for m in members:
            for i, (_h, k, _w) in enumerate(cols, 1):
                v = m.get(k)
                c = ws.cell(r, i, v if v not in ("",) else None)
                c.font = Font(name=FACE, sz=9)
                c.fill = PatternFill("solid", fgColor=AMBER)
                c.alignment = Alignment(vertical="top",
                                        wrap_text=(k in ("property", "brochure_detail",
                                                         "duplicate_note", "agent")))
            ws.row_dimensions[r].height = 40
            r += 1
        r += 1
    return ws


# ------------------------------------------------------------------------------------- main

def build(work: Path, out: Path | None = None, fresh: bool = False) -> dict:
    work = Path(work)
    out = Path(out) if out else work / WORKBOOK
    auto = ML._read_json(work / ML.AUTO_CANDIDATES, {}) or {}
    if not auto.get("rows"):
        raise SystemExit("No %s in %s - run the spine first; it writes the candidate rows."
                         % (ML.AUTO_CANDIDATES, work))
    model_path = work / ML.MODEL_CANDIDATES
    model = ML._read_json(model_path, {}) or {}
    if not model_path.exists():
        print("NOTE: no %s, so this inventory is the spine's mechanical one: every row it could\n"
              "  derive from a record or a brochure cluster, grouped on postal code alone. An\n"
              "  option named only in the PROSE of an email, and any duplicate the postcode sweep\n"
              "  cannot see, is missing from it. Write the candidates file and re-run if you have\n"
              "  read the emails." % ML.MODEL_CANDIDATES, file=sys.stderr)

    rows, dup_meta, added = merge_candidates(auto, model)
    apply_rank(rows, model)
    for r in rows:
        r.setdefault("include", "")
        r.setdefault("run_notes", "")
    kept, manual = (0, {}) if fresh else carry_forward(out, rows)

    n_deck = sum(1 for r in rows if r.get("source_type") == "Brochure")
    title = model.get("title") or "Master list - every option this run has found so far"
    note = ("Set Include? to Yes or No on EVERY row, and put any instruction for the run in "
            "'Your Run notes for the AI'. Amber rows overlap with another row - see the "
            "Duplicate check tab. Nothing is built until this sheet is answered.")
    foot = [
        "Rank is a sort order only. Re-sort, filter or re-rank freely: the run reads your "
        "answers by a hidden row id, not by position.",
        "Sources: %d row(s) from trackers and emails, %d brochure deck(s), %d row(s) the "
        "reading agent added. Built %s."
        % (len(rows) - n_deck - added, n_deck, added,
           datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
        "Red, bold Brochure? cells are rows with no machine-readable document. Include one and "
        "its card's specification comes from source text with no page citation behind it, so "
        "either chase the brochure or expect the row in the Gaps Report. Only a flat 'Yes' is "
        "left unformatted.",
        "A brochure row's name, postcode and size are read off the filename and the deck's first "
        "page only. The deck is READ properly if you include it.",
        "Nothing here is sent to a client. It decides what the run builds.",
    ]
    wb = write_master(rows, title, note, foot)
    write_dupes(wb, rows)
    try:
        wb.save(out)
    except PermissionError:
        raise SystemExit("Cannot write %s - it is open in Excel. Close it and re-run." % out)

    manifest = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                "workbook": os.path.basename(out),
                "input_hash": auto.get("input_hash") or ML.fingerprint(rows),
                "duplicate_groups": dup_meta,
                "rows": [{k: r.get(k) for k in
                          ("row_id", "rank", "property", "source_type", "source", "cluster",
                           "source_files", "postcode", "duplicate_group", "duplicate_status",
                           "files")} for r in rows]}
    (work / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")

    dups = len({r["duplicate_group"] for r in rows if r.get("duplicate_group")})
    print("MASTER LIST -> %s" % out, flush=True)
    print("  rows=%d (records=%d, brochure decks=%d, added by the reading agent=%d)  "
          "duplicate groups=%d" % (len(rows), len(rows) - n_deck - added, n_deck, added, dups),
          flush=True)
    if kept:
        print("  carried forward %d existing answer(s) by Row ID" % kept, flush=True)
    if manual:
        print("  NOTE: %d hand-typed row(s) in the previous workbook had no Row ID and were NOT "
              "carried forward. Re-add them: %s"
              % (len(manual), "; ".join(str(v.get("Property") or "?") for v in manual.values())),
              file=sys.stderr)
    print("  NEXT: the user fills in Include? and Run notes, then run master_list_read.py.",
          flush=True)
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="the run's work directory")
    ap.add_argument("--out", default=None, help="output workbook (default: <work>/%s)" % WORKBOOK)
    ap.add_argument("--fresh", action="store_true",
                    help="discard any Include?/Run notes already in the workbook instead of "
                         "carrying them forward by Row ID")
    args = ap.parse_args()
    build(Path(args.work), Path(args.out) if args.out else None, fresh=args.fresh)


if __name__ == "__main__":
    main()
