#!/usr/bin/env python3
"""f20b_media_view_gated_on_block_test.py - the spine writes the media half of the per-property
view ONLY when a pre-build gate has blocked, and tells the operator how to get it otherwise. (F20)

MEASURED. Projection was 42.06s of a 50.30s pass (84%) while building the dashboard took 0.15s,
rebuilding an 82 MB tree nothing downstream reads. B5 measured the two settings on the same
work dir: 52.1s / 354 files / 86.2 MB with media, 0.49s / 28 files / 0.17 MB without.

WHAT IS PINNED, at the source level (the spine cannot be run offline end to end):
  1. the ordinary projection call passes `media_view="never"`;
  2. `_full_view_for_humans` (media_view="always") is called exactly once, inside the pre-build
     gate BLOCKED branch, before the exit-5/exit-6/exit-13 paths;
  3. the skipped-media line and the review line both use B5's `rebuild_command`, never a
     hand-composed invocation;
and functionally: `_full_view_for_humans` writes the view for a fixture and prints the exact
rebuild command, and never raises on a broken work dir.

Offline. Run: python evals/f20b_media_view_gated_on_block_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import run as RUN  # noqa: E402

FAILS: list = []
RSRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("1. the ordinary pass projects WITHOUT media")
    i = RSRC.find('_stage("projection")')
    j = RSRC.find('_stage("gates:pre")', i)
    proj = RSRC[i:j]
    ck(re.search(r'_proj\.build\([^)]*media_view="never"', proj, re.S) is not None,
       'the projection stage calls build(..., media_view="never")')
    ck("_proj.rebuild_command(" in proj,
       "...and the skipped-media line is composed by project_properties.rebuild_command")
    ck("_full_view_for_humans(" not in proj,
       "...and the full view is NOT written in the projection stage")
    print("\n2. the full view is written exactly where a human is about to look")
    k = RSRC.find("    if any(rc != 0 for rc in g1):")
    m = RSRC.find("_full_view_for_humans(work, folder)", k)
    e5 = RSRC.find("sys.exit(5)", k)
    e6 = RSRC.find("sys.exit(6)", k)
    ck(k != -1 and m != -1 and m < e5 < e6,
       "called inside the pre-build BLOCKED branch, before exit 5 and exit 6")
    body = RSRC[RSRC.find("def _full_view_for_humans("):]
    body = body[:body.find("\ndef ", 10)]
    ck('media_view="always"' in body and "rebuild_command(" in body,
       'the helper builds with media_view="always" and prints rebuild_command')
    calls = [x.start() for x in re.finditer(r"_full_view_for_humans\(work, folder\)", RSRC)]
    ck(len(calls) == 1, f"exactly one call site ({len(calls)})")
    print("\n3. functionally: it writes the view, prints the command, never raises")
    w = Path(tempfile.mkdtemp(prefix="cbre_f20b_"))
    (w / "canonical.json").write_text(json.dumps({
        "meta": {"client": "x"},
        "properties": [{"id": 1, "park": "Kestrel Reach", "city": "Northport", "country": "XX",
                        "status": "available", "photo": ""}]}), encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        RUN._full_view_for_humans(w, None)
    out = err.getvalue()
    ck((w / "properties").exists() and any((w / "properties").rglob("property.json")),
       "the per-property view is written")
    ck("--media-view always" in out and "project_properties.py" in out,
       f"...and the exact rebuild command is printed ({out.strip()[:90]!a})")
    w2 = Path(tempfile.mkdtemp(prefix="cbre_f20b_broken_"))
    (w2 / "canonical.json").write_text("{not json", encoding="utf-8")
    err2 = io.StringIO()
    try:
        with contextlib.redirect_stderr(err2), contextlib.redirect_stdout(io.StringIO()):
            RUN._full_view_for_humans(w2, None)
        raised = False
    except Exception as exc:  # noqa: BLE001
        raised = repr(exc)
    ck(not raised and "skipped" in err2.getvalue(),
       f"a broken work dir is reported, never raised (a projection failure must not hide the "
       f"gate verdict) ({raised})")
    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F20B MEDIA VIEW GATED ON BLOCK TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F20B MEDIA VIEW GATED ON BLOCK TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
