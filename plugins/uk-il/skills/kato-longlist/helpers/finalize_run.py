#!/usr/bin/env python3
"""Stage 8 - leave the working directory fit for a non-technical colleague to open.

WHY: a real run was handed over as a directory of ~20 mixed folders with the client dashboard buried
three levels down beside QA montages, staging copies and __pycache__. The person who asked for the
longlist could not tell which file to send to their client. The pipeline's job is not done when the
bytes exist; it is done when the right file is obvious.

WHAT IT DOES
  1. Puts every client-facing output in ONE folder: <work>/OUTPUT/
  2. Writes <work>/START-HERE.md - plain English, no jargon: what to send, what to ignore.
  3. Deletes only genuine junk, from a fixed allowlist. Never touches properties/, emails/,
     longlist_work/, enrichment.json or anything else a re-run or an audit needs.

DELIBERATELY CONSERVATIVE. It moves terminal deliverables (nothing downstream reads them) and deletes
nothing outside JUNK. Working data stays exactly where the other helpers expect it, so running this does
not break a re-run of any earlier stage. Idempotent: run it as often as you like.

Usage:
  python finalize_run.py --config run.yaml
  python finalize_run.py --config run.yaml --dry-run      # show what would happen, change nothing
"""
import argparse
import fnmatch
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config

OUTPUT_DIR = "OUTPUT"

# Client-facing outputs, in the order a human wants to meet them. (glob, friendly description)
DELIVERABLES = [
    ("longlist_work/deliverables/*.html", "The interactive longlist dashboard. Open this in a browser. "
                                          "It is one self-contained file, so it can be emailed as-is."),
    ("longlist_work/deliverables/*.xlsx", "The longlist as a spreadsheet."),
    ("Kato Longlist (Client).xlsx", "The client spreadsheet."),
    ("longlist_work/deliverables/*gaps*", "Gaps Report: what is missing or unconfirmed, and why. "
                                          "Read this before sending anything to a client."),
    ("longlist_work/deliverables/*ledger*", "Source Ledger: every field traced to the source it came "
                                            "from. This is the audit trail."),
    ("longlist_work/deliverables/*.csv", "Supporting data export."),
    ("longlist_work/deliverables/*.md", "Supporting report."),
]

# The ONLY things this script deletes. Anything not matched here is left alone.
JUNK = [
    "**/__pycache__", "**/*.pyc", "**/*.pyo",
    "**/.DS_Store", "**/Thumbs.db",
    "**/*.tmp", "**/~$*",
    "emails/source",           # the old stage 2 unzipped a second copy of the whole export here
]


def iter_junk(work):
    for pattern in JUNK:
        pat = pattern.replace("**/", "")
        for root, dirs, files in os.walk(work):
            # never walk into OUTPUT: what lands there is deliberate
            if os.path.basename(root) == OUTPUT_DIR:
                dirs[:] = []
                continue
            for name in list(dirs):
                if fnmatch.fnmatch(name, pat) or os.path.relpath(os.path.join(root, name), work) \
                        .replace("\\", "/") == pattern:
                    yield os.path.join(root, name)
            for name in files:
                if fnmatch.fnmatch(name, pat):
                    yield os.path.join(root, name)


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def describe(basename):
    """The friendly description for a file, matched on its name alone - so a file already sitting in
    OUTPUT/ from an earlier run is described the same way as one moved there just now."""
    import fnmatch as _fn
    for pattern, description in DELIVERABLES:
        if _fn.fnmatch(basename.lower(), os.path.basename(pattern).lower()):
            return description
    return "Output from this run."


def already_placed(out_dir):
    """Files a previous run already moved into OUTPUT/.

    WITHOUT THIS, running this script twice was destructive: the first run moves the deliverables, so the
    second finds nothing at the source globs, warns that the run produced no deliverables, and rewrites
    START-HERE.md with an empty file list - throwing away the one page a non-technical colleague was
    told to read."""
    if not os.path.isdir(out_dir):
        return []
    out = []
    for name in sorted(os.listdir(out_dir)):
        full = os.path.join(out_dir, name)
        if os.path.isfile(full):
            out.append((name, describe(name), os.path.getsize(full), "already in place"))
    return out


def relocate(work, out_dir, dry_run):
    """Move each client-facing file into OUTPUT/. Falls back to copy where a move is refused (a file
    open in Excel on Windows), because half a delivery is worse than a duplicate."""
    import glob as _glob
    placed = []
    seen = set()
    for pattern, description in DELIVERABLES:
        for src in sorted(_glob.glob(os.path.join(work, pattern))):
            if not os.path.isfile(src):
                continue
            real = os.path.realpath(src)
            if real in seen or os.path.dirname(real) == os.path.realpath(out_dir):
                continue
            seen.add(real)
            dest = os.path.join(out_dir, os.path.basename(src))
            if os.path.exists(dest) and os.path.realpath(dest) != real:
                stem, ext = os.path.splitext(os.path.basename(src))
                dest = os.path.join(out_dir, f"{stem} (newer){ext}")
            if dry_run:
                placed.append((os.path.basename(dest), description, os.path.getsize(src), "would move"))
                continue
            os.makedirs(out_dir, exist_ok=True)
            try:
                shutil.move(src, dest)
                how = "moved"
            except Exception:
                shutil.copy2(src, dest)
                how = "copied (move refused - is it open in another program?)"
            placed.append((os.path.basename(dest), description, os.path.getsize(dest), how))
    return placed


START_HERE = """# Start here

This folder holds a Kato longlist run for **{client}**.

## What to open

Everything meant for a person is in the **`{out}`** folder:

{files}

## What to send a client

Send the dashboard (the `.html` file) and, if they asked for one, the spreadsheet. The dashboard is a
single self-contained file, so it works by email or on a shared drive with nothing else alongside it.

**Read the Gaps Report first.** It lists what could not be confirmed. Anything shown as `tbd` is
genuinely unknown, not an oversight, and should not be presented as fact.

## Everything else in this folder

Working data, kept so the run can be re-checked or re-run. You can ignore all of it:

{working}

Nothing in there needs to be sent anywhere, and deleting it would only mean the run has to start over.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    client = cfg.get("client") or "this requirement"
    out_dir = os.path.join(work, OUTPUT_DIR)

    print(f"Finalising {work}")
    if args.dry_run:
        print("  DRY RUN - nothing will be changed\n")

    existing = already_placed(out_dir)
    moved = relocate(work, out_dir, args.dry_run)
    moved_names = {n for n, _d, _s, _h in moved}
    placed = moved + [e for e in existing if e[0] not in moved_names]
    placed.sort(key=lambda r: [i for i, (pat, _d) in enumerate(DELIVERABLES)
                               if fnmatch.fnmatch(r[0].lower(), os.path.basename(pat).lower())] or [99])
    if placed:
        print(f"  {OUTPUT_DIR}/ ({len(placed)} file(s)):")
        for name, _desc, size, how in placed:
            print(f"    {how:<16} {size/1048576:>7.1f} MB  {name}")
    else:
        print("  WARNING: no client-facing deliverables found. Either the pipeline has not reached "
              "stage 7f yet, or the toolkit wrote them somewhere unexpected - check "
              "longlist_work/deliverables/ before telling anyone the run is done.")

    freed = 0
    removed = 0
    for path in sorted(set(iter_junk(work)), key=len, reverse=True):
        if not os.path.exists(path):
            continue
        size = dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
        if not args.dry_run:
            try:
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            except OSError:
                continue
        freed += size
        removed += 1
        print(f"    {'would remove' if args.dry_run else 'removed'}  "
              f"{os.path.relpath(path, work)}")
    print(f"  junk: {removed} item(s), {freed/1048576:.1f} MB")

    # START-HERE.md is written last, so it describes what is actually there now.
    file_lines = "\n".join(f"- **{name}** - {desc}" for name, desc, _s, _h in placed) or \
        "- _(nothing yet: the run has not produced its deliverables)_"
    leftovers = []
    for entry in sorted(os.listdir(work)):
        if entry in (OUTPUT_DIR, "START-HERE.md") or entry.startswith("."):
            continue
        p = os.path.join(work, entry)
        size = dir_size(p) if os.path.isdir(p) else os.path.getsize(p)
        leftovers.append(f"- `{entry}`{'/' if os.path.isdir(p) else ''} — {size/1048576:.1f} MB")
    text = START_HERE.format(client=client, out=OUTPUT_DIR, files=file_lines,
                             working="\n".join(leftovers) or "- _(nothing)_")
    if not args.dry_run:
        with open(os.path.join(work, "START-HERE.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"  {'would write' if args.dry_run else 'wrote'} START-HERE.md")
    print(f"\nDONE. Point the user at: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
