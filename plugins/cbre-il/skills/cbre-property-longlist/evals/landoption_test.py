#!/usr/bin/env python3
"""landoption_test.py - runner for landoption_test.mjs (v31 'a land/plot option is never hidden
at rest').

Executes the TEMPLATE'S OWN size-filter branch in node against a dataset holding a land/plot
option (plotArea + landPrice, no warehouseArea) alongside real warehouses, and asserts it is
visible at the slider's resting position - the position every broker sees on first load - while
still dropping out once the slider is actively raised.

Mirrors the numguard_test.py / format_test.py pattern: the .py locates the template + node, the
.mjs does the JS execution. Skips (exit 0) when node is unavailable, like its siblings.

Run: python evals/landoption_test.py"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    node = shutil.which("node")
    if not node:
        print("SKIP landoption_test: node not available (JS guards untested on this host)")
        return 0
    tpl = ROOT / "assets" / "dashboard_template.html"
    if not tpl.exists():
        print("FAIL landoption_test: template missing")
        return 1
    print("v31 land/plot option visibility (the template's OWN size-filter branch):")
    pr = subprocess.run([node, str(Path(__file__).with_suffix(".mjs")), str(tpl)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(pr.stdout or "")
    if pr.returncode != 0:
        sys.stdout.write(pr.stderr or "")
    return pr.returncode


if __name__ == "__main__":
    sys.exit(main())
