#!/usr/bin/env python3
"""no_client_data_test.py - the SKILL FOLDER ships whole; client data must never be in it.

THE INCIDENT (2026-08-24): a regression fixture - a live client project's 16 input
files, ~100 MB - was placed under `.regression/` inside the skill folder during an
implementation project. It was gitignored, so "client data never enters the repo" was
true - and irrelevant: teammates install the skill by COPYING THE FOLDER, so everything
on disk ships, and the skill ballooned to 156 MB carrying a client's brochures. Nothing
is client-specific in this skill and nothing may be: fixtures are synthetic (cowork_sim
builds its own corpus in a temp dir) or live OUTSIDE the skill folder.

Pinned here: the skill tree contains NO property-input file types anywhere, no project
folders, and no `.regression` payload. Fast + offline.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED_SUFFIXES = {".pdf", ".xlsx", ".xls", ".csv", ".pptx", ".msg", ".eml",
                   ".jpg", ".jpeg", ".heic"}
# every allowed exception is NAMED, so a new one is a deliberate decision
ALLOWED = set()
BANNED_DIR_NAMES = {".regression", "1. Input", "2. Work Files", "3. Output"}
SKIP_DIRS = {".git", "__pycache__"}


def main() -> int:
    fails = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_dir() and p.name in BANNED_DIR_NAMES:
            fails.append(f"project/run directory inside the skill: {rel}")
        if p.is_file() and p.suffix.lower() in BANNED_SUFFIXES \
                and str(rel).replace("\\", "/") not in ALLOWED:
            fails.append(f"property-input file type inside the skill: {rel}")
    for f in fails:
        print(f"  [FAIL] {f}")
    if fails:
        print(f"\nNO CLIENT DATA TEST: FAIL ({len(fails)}) - the skill folder ships "
              f"WHOLE to teammates; client inputs and run artefacts live OUTSIDE it "
              f"(gitignore does not protect a folder copy)")
        return 1
    print("NO CLIENT DATA TEST: PASS (no input-type files, no project dirs in the tree)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
