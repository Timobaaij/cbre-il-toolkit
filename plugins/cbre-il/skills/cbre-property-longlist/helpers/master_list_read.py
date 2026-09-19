#!/usr/bin/env python3
"""master_list_read.py - read the user's answers off the MASTER LIST and make them binding.

Turns the edited workbook into work/master_list.json, the file four later steps obey: the deck
reader dispatch (a cluster whose rows are all No is never read), the source-authority decision
(an answered sheet IS the authority, so the exit-13 question is not asked), the match
adjudication (the user's duplicate groups become `same` verdicts, so exit 10 asks only about
pairs nobody grouped) and the Gaps Report (every excluded option is named).

Ported from kato-longlist/helpers/master_list_read.py. Copied rather than imported, for the
reason master_list_build.py's header gives. The materialisation half of the Kato original is
deliberately NOT ported: this skill has no per-property folder to create, an included row's
records already exist or arrive from its deck reader, and a row the user typed in by hand is
recorded and reported rather than invented into a card with no source behind it.

WHAT "BINDING" MEANS HERE
-------------------------
  * Include? = No     the option is not built, and it is NAMED in the Gaps Report. Not a silent
                      drop: a property removed from a client's own longlist must be visible.
  * Include? = Yes    the option is built. If it is a brochure cluster, its deck is read.
  * Your Run notes    free text, carried to the model and to the Gaps Report. Instructions like
                      "take the spec from the brochure, not the email" are acted on by the
                      model, not by this script: it moves the text, it does not interpret it.

YES OR NO, AND NOTHING ELSE
---------------------------
There is no third value and anything that is not Yes or No stops the run (exit 2), "maybe"
included. A deferred answer has to be resolved before the run can start in any case, so
accepting one would not save the round trip: it would move the same decision to a point where
it is taken by whoever is reading a log rather than by the person who owns the deliverable. The
refusal names every offending row, so resolving them is one pass through the sheet.

A ROW THAT VANISHED IS NOT AN ANSWER. A row in the manifest that is not in the workbook was
deleted by the user. That reads like "No", but it is indistinguishable from a botched sort or a
filtered copy saved over the original, so it is reported and treated as excluded rather than
acted on quietly.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import master_list as ML          # noqa: E402
import master_list_build as B     # noqa: E402

from openpyxl import load_workbook  # noqa: E402

YES, NO = ML.YES, ML.NO
_TRUE = {"yes": YES, "y": YES, "include": YES, "true": YES, "1": YES}
_FALSE = {"no": NO, "n": NO, "exclude": NO, "drop": NO, "false": NO, "0": NO}
# Deliberately NOT a value. Mapped only so the refusal can say "maybe is not an answer here"
# rather than the unhelpful "unreadable value 'Maybe'".
#
# It used to spell "tbc" and "tbd" out here as well. That was a PRIVATE COPY of the skill's
# unknown-value family, which the port from kato-longlist carried in with it and which
# evals/f05_no_private_sentinel_sets_test.py exists to refuse: seven such copies had already
# drifted apart once in this codebase, so that "??" was data to one reader and absent to the next.
# A broker typing "n.v.t." or "a consultar" into Include? means exactly what they mean typing
# "TBD", and only the shared predicate knows the whole family, in every language it covers.
_DEFERRED = {"maybe", "m", "?", "unsure", "not sure"}


def _is_deferred(v) -> bool:
    """True for an Include? cell that is a non-answer rather than an unreadable value.

    `normalize.looks_unknown` is the ONE place that owns the unknown family; the literal above
    holds only the words that are hesitation rather than absence ("maybe", "unsure"), which that
    predicate rightly does not claim. An empty cell never reaches here - blank is its own branch
    above, with its own line in the refusal - so delegating is safe even though looks_unknown
    calls "" unknown.
    """
    t = str(v or "").strip().lower()
    if t in _DEFERRED:
        return True
    try:
        import normalize as _N
        return bool(_N.looks_unknown(t))
    except Exception:
        # No shared predicate reachable: fall back to refusing the value as unreadable, which is
        # a worse message but never a wrong outcome - either way the sheet is not accepted.
        return False


def find_workbook(work: Path, explicit=None) -> Path:
    """The workbook, even when the user saved it under another name.

    A user who saved 'Master List (Toby edits).xlsx' and got a run built off the untouched
    original would have no way of telling from the output, so any workbook in the work
    directory that IS a master list (right sheet name, right header cell) counts, and the file
    actually used is printed.
    """
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise SystemExit("No such workbook: %s" % p)
        return p
    direct = Path(work) / B.WORKBOOK
    if direct.exists():
        return direct
    cands = []
    for p in sorted(Path(work).glob("*.xls[xm]")):
        if p.name.startswith("~$"):
            continue
        try:
            wb = load_workbook(p, read_only=True, data_only=True)
            if (B.SHEET in wb.sheetnames
                    and str(wb[B.SHEET].cell(B.HDR_ROW, 1).value or "").strip() == "Rank"):
                cands.append(p)
            wb.close()
        except Exception:
            continue
    if not cands:
        raise SystemExit("No master list workbook found in %s. Run master_list_build.py first."
                         % work)
    if len(cands) > 1:
        cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        print("WARNING: %d master list workbooks here; using the most recently modified. The "
              "others: %s" % (len(cands), "; ".join(p.name for p in cands[1:])), file=sys.stderr)
    return cands[0]


def read_rows(path: Path) -> list:
    wb = load_workbook(path, data_only=True)
    if B.SHEET not in wb.sheetnames:
        raise SystemExit("%s has no '%s' sheet." % (path, B.SHEET))
    ws = wb[B.SHEET]
    hdr = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(B.HDR_ROW, c).value
        if v:
            hdr[str(v).strip()] = c
    header_to_key = {h: k for (h, k, *_r) in B.COLUMNS}
    missing = [h for h in ("Include?", "Property") if h not in hdr]
    if missing:
        raise SystemExit("%s is missing required column(s): %s" % (path, ", ".join(missing)))
    rows = []
    for r in range(B.FIRST_ROW, ws.max_row + 1):
        rec = {}
        for h, c in hdr.items():
            key = header_to_key.get(h)
            if key:
                rec[key] = ws.cell(r, c).value
        rec["_excel_row"] = r
        if not (rec.get("property") or rec.get("row_id") or rec.get("include")):
            continue
        for k, v in list(rec.items()):
            if isinstance(v, str):
                rec[k] = v.strip()
        rows.append(rec)
    wb.close()
    return rows


def norm_include(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return _TRUE.get(s.lower()) or _FALSE.get(s.lower()) or s


def read(work: Path, workbook=None) -> dict:
    work = Path(work)
    path = find_workbook(work, workbook)
    print("Reading %s" % path, flush=True)
    manifest = ML._read_json(work / ML.MANIFEST, {}) or {}
    man_rows = {r.get("row_id"): r for r in (manifest.get("rows") or []) if r.get("row_id")}

    rows = read_rows(path)
    if not rows:
        raise SystemExit("%s has no data rows." % path)

    blank, deferred, unknown = [], [], []
    for r in rows:
        r["include"] = norm_include(r.get("include"))
        rid = str(r.get("row_id") or "").strip()
        r["row_id"] = rid or None
        man = man_rows.get(rid) or {}
        # cluster and source_files come off the MANIFEST, never off the sheet: they are the
        # run's own routing data, they are not shown to the user, and reading them back from a
        # workbook a human has sorted and edited would make a typo in a hidden column able to
        # re-point a decision at somebody else's deck.
        r["cluster"] = man.get("cluster")
        r["source_files"] = man.get("source_files") or []
        label = "row %d  %s" % (r["_excel_row"], r.get("property") or "(no name)")
        if r["include"] == "":
            blank.append(label)
        elif r["include"] in (YES, NO):
            continue
        elif _is_deferred(r["include"]):
            deferred.append("%s  -> %r" % (label, r["include"]))
        else:
            unknown.append("%s  -> %r" % (label, r["include"]))

    if blank or deferred or unknown:
        print("ERROR: the master list is not fully answered, so nothing has been changed.",
              file=sys.stderr)
        for lbl in blank:
            print("  blank Include?      %s" % lbl, file=sys.stderr)
        for lbl in deferred:
            print("  not an answer here  %s" % lbl, file=sys.stderr)
        for lbl in unknown:
            print("  unreadable value    %s" % lbl, file=sys.stderr)
        if deferred:
            print("\n  Every row is Yes or No. A deferred answer has to be resolved before the "
                  "run can\n  start in any case, so it cannot be carried in the sheet: it would "
                  "only move the\n  same decision to a point where a log reader takes it instead "
                  "of the person who\n  owns the deliverable. Put the row(s) above to the user.",
                  file=sys.stderr)
        print("\n  Set every Include? to Yes or No and re-run. Nothing was written.",
              file=sys.stderr)
        sys.exit(2)

    seen = {r["row_id"] for r in rows if r.get("row_id")}
    deleted = [r for rid, r in man_rows.items() if rid not in seen]
    # A deleted row is treated as excluded AND kept in the output, so the Gaps Report can name
    # it and the run's option count still reconciles against the sheet that was built.
    for d in deleted:
        rows.append({"row_id": d.get("row_id"), "property": d.get("property"),
                     "source_type": d.get("source_type"), "include": NO, "run_notes": "",
                     "cluster": d.get("cluster"), "source_files": d.get("source_files") or [],
                     "duplicate_group": d.get("duplicate_group") or "",
                     "deleted_from_workbook": True, "_excel_row": None})

    included = [r for r in rows if r["include"] == YES]
    excluded = [r for r in rows if r["include"] == NO]
    out = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_workbook": Path(path).name,
        # The fingerprint the sheet ANSWERED. The spine re-opens the stop when the current
        # inputs set no longer hashes to this, which is what makes "a new deck re-opens the
        # sheet" a mechanical fact rather than an instruction somebody has to remember.
        "input_hash": manifest.get("input_hash") or "",
        "counts": {"rows": len(rows), "included": len(included), "excluded": len(excluded)},
        "rows": [{k: r.get(k) for k in
                  ("row_id", "rank", "include", "run_notes", "property", "source_type", "source",
                   "cluster", "source_files", "postcode", "duplicate_group", "duplicate_status",
                   "deleted_from_workbook", "_excel_row")} for r in rows],
        "run_notes": {str(r.get("row_id")): r.get("run_notes") for r in included
                      if (r.get("run_notes") or "").strip()},
        "hand_typed": [r.get("property") for r in rows if not r.get("row_id")],
        "deleted_since_build": [{"row_id": r.get("row_id"), "property": r.get("property")}
                                for r in deleted],
    }
    (work / ML.ANSWERS).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print("MASTER LIST READ -> %s" % (work / ML.ANSWERS), flush=True)
    print("  include=%d  exclude=%d  run notes=%d"
          % (len(included), len(excluded), len(out["run_notes"])), flush=True)
    if out["hand_typed"]:
        print("  NOTE: %d row(s) were typed in by hand and have no Row ID. They are recorded, "
              "but nothing is built from a row with no source behind it - give the run the file "
              "or the email that option came from: %s"
              % (len(out["hand_typed"]), "; ".join(str(x) for x in out["hand_typed"][:5])),
              file=sys.stderr)
    if deleted:
        print("  WARNING: %d row(s) from the build are not in the workbook and are treated as "
              "excluded: %s" % (len(deleted),
                                "; ".join(str(r.get("property") or "?") for r in deleted)),
              file=sys.stderr)
    if out["run_notes"]:
        print("  NEXT: read master_list.json run_notes before the readers run - they are "
              "instructions for you, not data.", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="the run's work directory")
    ap.add_argument("--workbook", default=None,
                    help="path to the edited master list (default: found in <work>)")
    args = ap.parse_args()
    read(Path(args.work), args.workbook)


if __name__ == "__main__":
    main()
