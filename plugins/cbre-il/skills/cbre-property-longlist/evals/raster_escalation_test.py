#!/usr/bin/env python3
"""raster_escalation_test.py - the needs_raster escalation must survive its own consumption. (B65)

A text deck whose text layer is garbled gets a `needs_raster` stub from its reader. run.py
strips that stub - correctly, it is a request and not a record - but the set it derived from
the stubs was a LOCAL, and the stubs were deleted in the same loop, so the escalation survived
exactly zero passes. Meanwhile the escalated deck was still handed to photo-match, which
matches TEXTLESS brochures against properties already known from another source; the reader
had already read that deck and reported a property deck with a bad text layer, so the only
honest verdict there is `unrelated`, and the escalation was spent on the wrong branch.

The two together livelock: text reader -> stub -> photo-match -> unrelated -> text reader,
and the only escape on a live run was hand-writing a stub back into work/extract/, a directory
the docs correctly call derived and forbid editing.

What this pins:
  * the escalation is DURABLE - it outlives the pass that consumes the stub;
  * it is SELF-CLEARING - retired the moment that deck's records exist, so it cannot wedge in
    the other direction by forcing a re-read forever;
  * an escalated deck is never offered to photo-match, while its siblings still are;
  * the surviving vision-target ORDER is unchanged, so the build stays byte-deterministic.
Offline; no network, no build.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import run as RUN                        # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    print("raster_escalation_test - an escalation that survives being consumed")

    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        ck(RUN._load_force_raster(w) == set(), "no file -> nothing escalated (a clean run)")

        RUN._save_force_raster(w, {"Dossier.pdf"})
        ck(RUN._load_force_raster(w) == {"Dossier.pdf"},
           "the escalation is written and read back - it OUTLIVES the stub it came from")
        ck((w / "vision" / "force_raster.json").exists(), "and it lives in the work dir")

        RUN._save_force_raster(w, {"Dossier.pdf", "Other.pdf"})
        ck(RUN._load_force_raster(w) == {"Dossier.pdf", "Other.pdf"}, "a second deck joins")

        RUN._save_force_raster(w, set())
        ck(RUN._load_force_raster(w) == set()
           and not (w / "vision" / "force_raster.json").exists(),
           "cleared to empty leaves no stale file behind")

        (w / "vision").mkdir(parents=True, exist_ok=True)
        (w / "vision" / "force_raster.json").write_text("{ not json", encoding="utf-8")
        ck(RUN._load_force_raster(w) == set(),
           "a corrupt file degrades to 'nothing escalated', never a crash")

    # the photo-match exclusion and the surviving-target filter, through run.py's own helpers
    targets = [(Path("/in/Alpha.pdf"), "Alpha", "ES"),
               (Path("/in/Dossier.pdf"), "Dossier", "ES"),
               (Path("/in/Beta.pdf"), "Beta", "ES")]
    cands = RUN.photo_match_candidates(targets, {"Dossier.pdf"})
    ck([Path(t[0]).name for t in cands] == ["Alpha.pdf", "Beta.pdf"],
       "an escalated deck is NOT offered to photo-match; its siblings still are")
    ck(RUN.photo_match_candidates(targets, set()) == targets,
       "with nothing escalated every target is a candidate, exactly as before")

    rel_of = {t[0]: Path(t[0]).name for t in cands}   # what the matcher was shown
    still_vision = {cands[0][0]}                      # Alpha unmatched, Beta confidently matched
    survivors = RUN.keep_vision_targets(targets, rel_of, still_vision)
    ck([Path(t[0]).name for t in survivors] == ["Alpha.pdf", "Dossier.pdf"],
       "the escalated deck passes through to the vision path, in the ORIGINAL order")
    ck([Path(t[0]).name for t in RUN.keep_vision_targets(targets, {}, set())]
       == ["Alpha.pdf", "Dossier.pdf", "Beta.pdf"],
       "and a run where photo-match never fired keeps every target, in order")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
