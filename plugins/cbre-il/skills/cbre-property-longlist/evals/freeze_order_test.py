#!/usr/bin/env python3
"""freeze_order_test.py - the freeze marker is the COMMIT POINT, written last. (B18)

cmd_freeze wrote the marker BEFORE regenerating the photo-stripped reviewer twin, so a
death in between left `freeze --check` green over a STALE canonical_review.json - precisely
the staleness the comment above it claims to prevent. The DATA reviewers read that twin, so
they would have judged pre-fix data while the gate certified they saw the frozen bytes.

Two corrections to the filed remedy, both asserted here:
  - the marker write was ALREADY atomic (_common.atomic_write_text), so that half was
    redundant; what was missing was the ORDER;
  - a kill is not even the likeliest failure. emit_review_view swallowed every exception and
    returned None, so a twin that could not be written (full disk, permissions) let
    cmd_freeze print STATUS: ALL-PASS over an un-refreshed twin. Reordering alone does NOT
    close that, so the refresh now reports success and a failure BLOCKS the freeze.

Blocking is the deliberate choice: a review aid that silently fails is worse than a run that
stops, because the run ships a wrongly-reviewed dataset. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import gate_runner as GR  # noqa: E402

GR_SRC = (HELPERS / "gate_runner.py").read_text(encoding="utf-8", errors="replace")
C_SRC = (HELPERS / "_common.py").read_text(encoding="utf-8", errors="replace")


class _Args:
    def __init__(self, file, check=False):
        self.file = str(file)
        self.check = check


def _canon(tag):
    return {"meta": {"client": tag},
            "properties": [{"id": 1, "park": tag, "photo": "data:image/png;base64,AAAA"}]}


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_frz_"))
    canon = d / "canonical.json"
    twin = d / "canonical_review.json"
    marker = canon.with_suffix(canon.suffix + ".frozen.sha256")

    # a normal freeze writes both, and the twin is refreshed
    canon.write_text(json.dumps(_canon("v1")), encoding="utf-8")
    rc = GR.cmd_freeze(_Args(canon))
    ck(rc == 0, "a normal freeze succeeds")
    ck(marker.exists() and twin.exists(), "both the marker and the twin exist")
    ck("v1" in twin.read_text(encoding="utf-8"), "the twin holds the frozen content")
    ck("data:image/png" not in twin.read_text(encoding="utf-8"),
       "the twin is still photo-stripped")

    # ORDER: the marker must not predate the twin it vouches for
    ck(marker.stat().st_mtime_ns >= twin.stat().st_mtime_ns,
       "the marker is written AFTER the twin (it is the commit point)")

    # a re-freeze after an out-of-band edit refreshes the twin
    canon.write_text(json.dumps(_canon("v2")), encoding="utf-8")
    GR.cmd_freeze(_Args(canon))
    ck("v2" in twin.read_text(encoding="utf-8"), "a re-freeze refreshes the twin")
    ck(GR.cmd_freeze(_Args(canon, check=True)) == 0, "--check passes over the fresh freeze")

    # THE LIKELIER FAILURE: the twin cannot be written. It must BLOCK, and must not leave a
    # marker certifying a stale twin.
    ck(hasattr(C, "emit_review_view"), "_common.emit_review_view exists")
    _real = C.emit_review_view
    marker.unlink(missing_ok=True)
    canon.write_text(json.dumps(_canon("v3")), encoding="utf-8")
    try:
        C.emit_review_view = lambda *a, **k: False   # simulate a write failure
        GR.emit_review_view = C.emit_review_view if hasattr(GR, "emit_review_view") else None
        rc = GR.cmd_freeze(_Args(canon))
    finally:
        C.emit_review_view = _real
    ck(rc != 0, "a failed twin refresh BLOCKS the freeze")
    ck(not marker.exists(),
       "and leaves NO marker - a green --check over a stale twin is impossible")

    # the contract must say so too, or the code and its own comment disagree
    ck("must never block a freeze" not in C_SRC,
       "_common no longer claims the review aid can never block a freeze")
    ck("return True" in C_SRC and "def emit_review_view" in C_SRC,
       "emit_review_view reports success instead of swallowing everything")

    # ORDER, at the source level: the twin call must precede the marker write
    seg = GR_SRC[GR_SRC.find("def cmd_freeze"):]
    seg = seg[:seg.find("def cmd_enrichment")]
    i_twin, i_marker = seg.find("emit_review_view("), seg.find("atomic_write_text(side")
    ck(-1 < i_twin < i_marker, "cmd_freeze emits the twin BEFORE writing the marker")

    if fails:
        print(f"\nFREEZE ORDER TEST: FAIL ({len(fails)})")
        return 1
    print("\nFREEZE ORDER TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
