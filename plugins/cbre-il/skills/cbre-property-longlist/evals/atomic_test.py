#!/usr/bin/env python3
"""atomic_test.py - the durable-write contract (Phase 1 of the 2026-07 audit).

Every durable/resume-gating artefact (project.yaml, inventory.json, built.html,
the deliverables, the freeze side-file, canonical_review.json) is written via the
house write-tmp-then-os.replace idiom, so a kill mid-write (routine at Cowork's
~45s cap) can NEVER leave a truncated file that --resume then treats as current.

This locks the shared helper _common.atomic_write_text:
  * writes exact bytes with LF only (no CRLF translation on Windows) -> the built
    HTML is byte-identical cross-platform (audit S6-1)
  * commits via os.replace, so a failure at commit leaves the ORIGINAL intact
    (audit S0-1/S0-2/S5-1/S7-1/S4-3 - never truncate a confirmed file)
  * leaves no stray .tmp on success

Run: python evals/atomic_test.py     (exit 0 on success, 1 on any failure)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    d = Path(tempfile.mkdtemp(prefix="cbre_atomic_"))

    # 1. exact bytes, LF only (no CRLF translation, even on Windows)
    p = d / "a.txt"
    C.atomic_write_text(p, "x\ny\n")
    check(p.read_bytes() == b"x\ny\n", "atomic_write_text writes LF only (no CRLF translation)")

    # 2. overwrites an existing file
    C.atomic_write_text(p, "new\n")
    check(p.read_bytes() == b"new\n", "atomic_write_text overwrites an existing file")

    # 3. no stray .tmp remains after a successful write
    check(not p.with_suffix(p.suffix + ".tmp").exists(), "no .tmp left after a successful write")

    # 4. ATOMIC: a failure at commit (os.replace) leaves the ORIGINAL intact
    orig = d / "o.txt"
    C.atomic_write_text(orig, "ORIGINAL\n")
    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated crash at commit")

    os.replace = boom
    try:
        try:
            C.atomic_write_text(orig, "NEWDATA-must-not-land\n")
        except OSError:
            pass
        check(orig.read_bytes() == b"ORIGINAL\n",
              "original file survives a crash at commit (never truncated)")
    finally:
        os.replace = real_replace

    # 5. atomic_write_bytes: exact bytes + atomic commit
    b = d / "b.bin"
    C.atomic_write_bytes(b, b"\x00\x01\x02BIN")
    check(b.read_bytes() == b"\x00\x01\x02BIN", "atomic_write_bytes writes exact bytes")

    if FAILS:
        print(f"\nATOMIC TEST: FAIL ({len(FAILS)})")
        return 1
    print("\nATOMIC TEST: PASS (LF-only, atomic commit, original survives a mid-write crash)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
