#!/usr/bin/env python3
"""preflight.py - verify the skill copied/mounted INTACT before anything runs.

Sandboxed runtimes (e.g. Cowork) copy the skill into the execution environment
each session. A partial / lazily-synced mount can deliver a TRUNCATED helper,
which would otherwise blow up later as an opaque mid-file SyntaxError. This checks
that every file recorded in assets/integrity.json is present and not shorter than
recorded, and that every helper *.py parses. On any problem it prints ONE plain
sentence a non-technical user can act on, and exits non-zero.

    python helpers/preflight.py        # run this FIRST (see SKILL.md "Step 0")

Kept deliberately small and dependency-free so it is itself unlikely to truncate.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAIN = "The skill files didn't load correctly. Please restart the session and try again."


def _content_valid(f: Path) -> bool:
    """Cheap content sanity by file type: a .py must parse, a .json must load, an
    .html must end with its closing tag. Used to tell a TRUNCATED file (blocks,
    restart fixes it) from an EDITED one with a stale manifest (advisory only -
    restarting can never fix that, so it must never trigger the restart message)."""
    try:
        if f.suffix == ".py":
            ast.parse(f.read_text(encoding="utf-8"))
            return True
        if f.suffix == ".json":
            json.loads(f.read_text(encoding="utf-8"))
            return True
        if f.suffix in (".html", ".htm"):
            return f.read_bytes()[-2048:].decode("utf-8", "ignore").rstrip().lower().endswith("</html>")
        return True  # no cheap validity test for other types (e.g. VERSION)
    except Exception:
        return False


def problems(notes: list[str] | None = None) -> list[str]:
    """Return a list of integrity problems ([] == healthy). Hard signals only:
    missing, empty, or content that fails its type's sanity check (truncation).
    A size that merely DIFFERS from the manifest while the content is still valid
    is a stale manifest (an edited file), reported to `notes` if given - it must
    never block, because 'restart the session' cannot fix a stale manifest."""
    out: list[str] = []
    man_path = ROOT / "assets" / "integrity.json"
    manifest = {}
    if man_path.exists():
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except Exception:
            out.append("assets/integrity.json unreadable/truncated")
    for rel, meta in manifest.items():
        f = ROOT / rel
        if not f.exists():
            out.append(f"{rel}: missing")
            continue
        size = f.stat().st_size
        if size == 0:
            out.append(f"{rel}: empty")
        elif size != int(meta.get("size", 0)):
            if not _content_valid(f):
                out.append(f"{rel}: truncated ({size} vs {meta['size']} bytes recorded, content invalid)")
            elif notes is not None:
                notes.append(f"{rel}: differs from the integrity manifest but is valid - "
                             f"if you edited it, re-run helpers/make_integrity.py")
    # parse every helper present - catches a mid-statement truncation even if the
    # manifest is absent or stale (zero false-alarms: an edited file still parses)
    for f in sorted((ROOT / "helpers").glob("*.py")):
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except Exception as e:
            out.append(f"helpers/{f.name}: does not parse ({type(e).__name__})")
    # de-dup, preserve order
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq


def main() -> int:
    notes: list[str] = []
    probs = problems(notes)
    if probs:
        print(PLAIN)
        print("(technical detail: " + "; ".join(probs[:12]) + ")", file=sys.stderr)
        return 2
    n = len(list((ROOT / "helpers").glob("*.py")))
    print(f"OK skill integrity verified ({n} helpers)")
    for nmsg in notes[:12]:  # advisory only - a stale manifest must not block a run
        print(f"(note: {nmsg})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
