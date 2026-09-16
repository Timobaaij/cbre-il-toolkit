#!/usr/bin/env python3
"""Self-test for the cbre-il-occupier-brief skill.

    python evals/smoke_test.py

Proves two things, both of which matter:
  1. the worked example passes every gate, so the gates are achievable
  2. a broken brief fails them, so the gates are not decorative

Renders into a temporary directory and cleans up. Standard library only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPERS = os.path.join(SKILL, "helpers")
EXAMPLES = os.path.join(SKILL, "examples")
BRIEF = os.path.join(EXAMPLES, "worked_brief.md")
LEDGER = os.path.join(EXAMPLES, "worked_source_ledger.csv")

results = []


def run(label, args, expect_pass, needle="STATUS:"):
    res = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    out = res.stdout + res.stderr
    status = next((l for l in out.splitlines() if l.startswith("STATUS:")), "(no STATUS line)")
    passed = ("PASS" in status) if expect_pass else ("FAIL" in status)
    results.append((label, passed, status.strip()))
    print("%-34s %-6s %s" % (label, "ok" if passed else "BROKEN", status.strip()))
    return out


def run_contains(label, args, needle, expect=True):
    """For helpers that do not print a STATUS: line, such as node_forecast.py."""
    res = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    out = res.stdout + res.stderr
    found = needle.lower() in out.lower()
    passed = (res.returncode == 0) and (found == expect)
    results.append((label, passed, "exit %d, %r %s" % (res.returncode, needle,
                                                        "found" if found else "absent")))
    print("%-34s %-6s exit %d, %r %s" % (label, "ok" if passed else "BROKEN", res.returncode,
                                          needle, "found" if found else "absent"))
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="ilpb_")
    try:
        gate = os.path.join(HELPERS, "gate_runner.py")
        run("style: worked example", [gate, "style", BRIEF], True)
        run("sections: worked example", [gate, "sections", BRIEF], True)
        run("depth: worked example", [gate, "depth", BRIEF], True)
        run("trace: worked example", [gate, "trace", BRIEF, LEDGER], True)
        run("ledger validate", [os.path.join(HELPERS, "ledger.py"), "validate", LEDGER], True)

        # the render must produce a parseable A4 package
        out_docx = os.path.join(tmp, "Worked_IL_OccupierBrief.docx")
        res = subprocess.run([sys.executable, os.path.join(HELPERS, "render_docx.py"),
                              BRIEF, out_docx], capture_output=True, text=True)
        ok = res.returncode == 0 and os.path.isfile(out_docx)
        if ok:
            import xml.etree.ElementTree as ET
            import zipfile
            with zipfile.ZipFile(out_docx) as z:
                for name in z.namelist():
                    ET.fromstring(z.read(name))
                doc = z.read("word/document.xml").decode()
            ok = 'w:w="11906"' in doc and "006A4D" in doc
        results.append(("render: A4 package parses", ok, "rc=%d" % res.returncode))
        print("%-34s %-6s rc=%d" % ("render: A4 package parses", "ok" if ok else "BROKEN",
                                    res.returncode))

        # negative controls: a brief that breaks house style and structure must fail
        bad = os.path.join(tmp, "bad_brief.md")
        src = open(BRIEF, encoding="utf-8").read()
        broken = src.replace("## What is likely on the mind of the CEO",
                             "## What the CEO thinks")
        broken = broken.replace("distribution centre", "distribution center", 1)
        broken = broken.replace("national distribution", "national %s distribution" % chr(0x2014), 1)
        open(bad, "w", encoding="utf-8", newline="\n").write(broken)
        run("style: broken brief fails", [gate, "style", bad], False)
        run("sections: broken brief fails", [gate, "sections", bad], False)

        thin = os.path.join(tmp, "thin_brief.md")
        head = src.split("## What is driving the business right now")[0]
        open(thin, "w", encoding="utf-8", newline="\n").write(head)
        run("depth: thin brief fails", [gate, "depth", thin], False)

        untraced = os.path.join(tmp, "untraced_brief.md")
        open(untraced, "w", encoding="utf-8", newline="\n").write(
            src.replace("GBP 1.84bn", "GBP 9.99bn"))
        run("trace: untraced figure fails", [gate, "trace", untraced, LEDGER], False)
        # ---------------------------------------------------------------- the forecaster
        # Two demand rows: one young and unserved, one mature and served. The young orphan
        # must come out tier 1, because that is the whole point of the tier rule.
        fc = os.path.join(HELPERS, "node_forecast.py")
        demand = os.path.join(tmp, "demand.csv")
        open(demand, "w", encoding="utf-8").write(
            "market,entry_year,demand_now,lat,lon,km_to_node,cluster,served_by,mode\n"
            "Newland,2025.5,6,10.0,10.0,1200,Newland cluster,,road\n"
            "Oldland,2016.0,200,20.0,20.0,150,Home,HomeNode,road\n"
            "Midland,2023.0,40,11.0,11.0,1300,Newland cluster,,road\n")
        peers = os.path.join(tmp, "peers.csv")
        open(peers, "w", encoding="utf-8").write(
            "peer,demand_points,nodes,note\nAlpha,900,6,x\nBeta,400,2,y\n")
        run_contains("forecast: young orphan is tier 1",
                     [fc, demand, "--peers", peers, "--calibrate"], "tier 1")
        run_contains("forecast: no peers, no timing claim",
                     [fc, demand, "--calibrate"], "NONE SUPPLIED")
        run_contains("forecast: warns when un-back-tested",
                     [fc, demand, "--peers", peers, "--calibrate"], "NO BACK-TEST RUN")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    broken = [r for r in results if not r[1]]
    print()
    print("%d of %d checks behaved as expected" % (len(results) - len(broken), len(results)))
    if broken:
        for label, _, status in broken:
            print("  BROKEN: %s (%s)" % (label, status))
        print("STATUS: FAIL (%d)" % len(broken))
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
