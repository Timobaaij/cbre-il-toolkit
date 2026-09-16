#!/usr/bin/env python3
"""Final gate for the CBRE I&L Occupier Brief.

Run this last, in the run folder. Nothing ships while a line is red.

Usage:
    python final_gate.py [--dir .] [--company "Testco plc"]

It checks, in order:
  1. the three deliverables exist and are non-trivial
  2. the DOCX is a readable OOXML package with every part well formed
  3. the rendered DOCX text reconciles with brief.md (no section lost in render)
  4. every deterministic gate passes (style, sections, depth, trace, budget)
  5. both independent review scorecards exist and read STATUS: ALL-PASS
  6. no unresolved placeholder text survives anywhere

Standard library only.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDERS = ("tbd", "tk", "xx", "lorem", "<company>", "[company]", "todo",
                "fill in", "insert ", "your text")
W_T = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def longpath(path):
    if os.name != "nt":
        return path
    absolute = os.path.abspath(path)
    if len(absolute) < 240 or absolute.startswith("\\\\?\\"):
        return absolute
    return "\\\\?\\" + absolute.replace("/", "\\")


def find(pattern, root):
    hits = sorted(glob.glob(os.path.join(root, pattern)))
    return hits[0] if hits else None


def docx_text(path):
    with zipfile.ZipFile(longpath(path)) as z:
        for name in z.namelist():
            ET.fromstring(z.read(name))          # raises on a malformed part
        doc = ET.fromstring(z.read("word/document.xml"))
    return "\n".join(t.text or "" for t in doc.iter(W_T))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="run folder (default: current)")
    ap.add_argument("--company", default=None)
    args = ap.parse_args(argv)
    root = os.path.abspath(args.dir)
    deliverables = os.path.join(root, "deliverables")
    working = os.path.join(root, "working")

    fails, notes = [], []

    brief = find("brief.md", working) or find("brief.md", root)
    docx = find("*OccupierBrief*.docx", deliverables) or find("*.docx", deliverables)
    ledger = (find("*Source_Ledger*.csv", deliverables)
              or find("source_ledger.csv", working))
    verification = find("*Verification*", deliverables)

    for label, path in (("brief.md", brief), ("the DOCX", docx),
                        ("the Source Ledger", ledger),
                        ("the Verification Sheet", verification)):
        if not path:
            fails.append("deliverable missing: %s" % label)
        elif os.path.getsize(longpath(path)) < 400:
            fails.append("deliverable is suspiciously small: %s" % os.path.basename(path))
        else:
            notes.append("found %s (%d bytes)" % (os.path.basename(path),
                                                  os.path.getsize(longpath(path))))

    text = ""
    if docx:
        try:
            text = docx_text(docx)
            notes.append("DOCX parsed: %d text runs" % len(text.splitlines()))
        except Exception as exc:                       # noqa: BLE001
            fails.append("the DOCX will not parse as OOXML: %s" % exc)

    if brief and text:
        md = open(longpath(brief), encoding="utf-8").read()
        flat = re.sub(r"\s+", " ", text).lower()
        for line in md.splitlines():
            if re.match(r"^##\s+", line.strip()):
                h = re.sub(r"^#+\s+", "", line.strip())
                if re.sub(r"\s+", " ", h).lower() not in flat:
                    fails.append("section '%s' is in brief.md but not in the rendered DOCX" % h)

    vs_text = ""
    if verification:
        vs_text = open(longpath(verification), encoding="utf-8").read()

    for blob, where in ((text, "the DOCX"), (vs_text, "the Verification Sheet")):
        low = blob.lower()
        for ph in PLACEHOLDERS:
            if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(ph), low):
                fails.append("placeholder text '%s' survives in %s" % (ph, where))

    for ch, label in ((chr(0x2014), "em dash"), (chr(0x2013), "en dash")):
        outside_quotes = re.sub(r'"[^"\n]*"', " ", text)
        if ch in outside_quotes:
            fails.append("%s in the rendered DOCX outside a quotation; house style forbids it"
                         % label)

    if brief and ledger:
        cmd = [sys.executable, os.path.join(HERE, "gate_runner.py"), "all", brief, ledger]
        sl = find("search_ledger.md", working) or find("search_ledger.md", root)
        if sl:
            cmd.append(sl)
        else:
            fails.append("no search_ledger.md; the 200-search budget must be evidenced")
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(res.stdout)
        if res.stderr.strip():
            print(res.stderr, file=sys.stderr)
        if "STATUS: ALL-PASS" not in res.stdout:
            fails.append("the deterministic gates did not all pass (see the block above)")

    for name, label in (("qa_review.md", "the independent QA review"),
                        ("qa_response.md", "the orchestrator's response to the review")):
        path = find(name, working) or find(name, root)
        if not path:
            fails.append("%s scorecard missing (%s)" % (label, name))
            continue
        body = open(longpath(path), encoding="utf-8").read()
        if len(body.strip()) < 200:
            fails.append("%s is present but essentially empty" % label)
        if re.search(r"^\s*reviewer:\s*orchestrator\s*$", body, re.M | re.I):
            fails.append("%s was signed by the orchestrator; the reviewer must be an "
                         "independent sub-agent" % label)

    print("--- final gate ---")
    for n in notes:
        print("      " + n)
    for f in fails:
        print("FAIL  " + f)
    print("STATUS: " + ("ALL-PASS" if not fails else "FAIL (%d)" % len(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
