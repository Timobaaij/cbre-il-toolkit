#!/usr/bin/env python3
"""source_loss_test.py - a source never vanishes, and a good file is never called corrupt. (B15)

Two halves, and the backlog's premise for the first was FALSE: it blamed quiet-by-default
(B27), but the reader-failure warning has been unconditional since 2026-07-30 and is locked
by honesty_test. What was actually missing is the DURABLE record - with no spreadsheet
reader, the tracker loop is skipped and nothing appends the file to unreadable_inputs, so
unreadable.json, the Gaps Report and _gaps_to_chase all omit it while the Plan line still
promises "N tracker(s) -> column mapping".

Second half: _classify_unreadable ran on EVERY deck (not the 0-record path its docstring
claimed) and condemned as "corrupt / unreadable" any non-ImportError open failure without
"password"/"encrypt" in its message - every pdfminer/pdfium failure under the shim tier,
every Windows lock, every unhydrated OneDrive placeholder. That sends the broker to chase
re-sends of perfectly good files. Offline."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import run as RUN  # noqa: E402

SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_loss_"))

    # --- half 2: the classifier must not condemn what it merely could not open ---
    pdf = d / "good.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf but non-empty")

    def _classify_with(exc):
        """Drive the real classifier with a reader that raises `exc`."""
        import builtins
        real = builtins.__import__

        class _Doc:
            def __init__(self, *a, **k):
                raise exc

        class _Fitz:
            @staticmethod
            def open(*a, **k):
                raise exc
        def fake(name, *a, **k):
            if name in ("fitz", "fitz_shim"):
                return _Fitz
            return real(name, *a, **k)
        builtins.__import__ = fake
        try:
            return RUN._classify_unreadable(pdf)
        finally:
            builtins.__import__ = real

    r = _classify_with(OSError("The process cannot access the file because it is being "
                               "used by another process"))
    ck(r is not None, "a Windows file lock is still REPORTED (never a silent drop)")
    ck("corrupt" not in (r or "").lower(),
       f"...but is NOT called corrupt {ascii(str(r))}")

    r = _classify_with(OSError("cloud file provider is not running"))
    ck("corrupt" not in (r or "").lower(),
       f"an unhydrated OneDrive placeholder is not called corrupt {ascii(str(r))}")

    r = _classify_with(RuntimeError("cannot open broken document"))
    ck((r or "").startswith("corrupt"),
       f"a STRUCTURAL reader complaint IS still called corrupt {ascii(str(r))}")

    r = _classify_with(RuntimeError("document is password protected"))
    ck("encrypt" in (r or "").lower() or "password" in (r or "").lower(),
       f"an encrypted file is still classified as such {ascii(str(r))}")

    empty = d / "empty.pdf"
    empty.write_bytes(b"")
    ck("empty" in (RUN._classify_unreadable(empty) or ""), "a 0-byte file is still reported")

    # --- half 1: a reader-lost tracker leaves a DURABLE record -------------------
    i_guard = SRC.find('if not extant["extract_xlsx"]:')
    ck(i_guard != -1, "run.py handles the no-spreadsheet-reader case explicitly")
    seg = SRC[i_guard:i_guard + 1200]
    ck("unreadable_inputs.append" in seg,
       "...by appending every tracker to unreadable_inputs (the durable record)")
    ck("openpyxl" in seg and "the file is fine" in seg,
       "...with an honest ENVIRONMENT cause, not a claim about the file")
    ck(i_guard < SRC.find('if extant["extract_xlsx"]:'),
       "the guard runs before the normal tracker loop")
    # and the durable record must be what the Gaps Report reads
    ck("unreadable_inputs" in SRC[SRC.find("def _gaps_to_chase"):
                                  SRC.find("def _gaps_to_chase") + 600],
       "_gaps_to_chase reads unreadable_inputs, so the loss reaches the broker")

    if fails:
        print(f"\nSOURCE LOSS TEST: FAIL ({len(fails)})")
        return 1
    print("\nSOURCE LOSS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
