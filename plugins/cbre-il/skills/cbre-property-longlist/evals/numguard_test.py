#!/usr/bin/env python3
"""numguard_test.py - runner for numguard_test.mjs (v26 'tbd is never a number' guards).

Executes the TEMPLATE'S OWN comparators and predicates in node against a dataset holding an
unpriced and an unmeasured property. Mirrors the format_test.py / modal_render_test.py pattern:
the .py locates the template + node, the .mjs does the JS execution.

Skips (exit 0) when node is unavailable, like its siblings - the Python-side guards are covered
by build_dashboard's own tests.

Run: python evals/numguard_test.py"""
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
        print("SKIP numguard_test: node not available (JS guards untested on this host)")
        return 0
    tpl = ROOT / "assets" / "dashboard_template.html"
    if not tpl.exists():
        print("FAIL numguard_test: template missing")
        return 1
    print("v26 numeric guards (the template's OWN sort/filter/highlight code):")
    pr = subprocess.run([node, str(Path(__file__).with_suffix(".mjs")), str(tpl)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(pr.stdout or "")
    if pr.returncode != 0:
        sys.stdout.write(pr.stderr or "")
    return pr.returncode


if __name__ == "__main__":
    sys.exit(main())
