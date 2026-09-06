#!/usr/bin/env python3
"""f08_ascii_handoff_test.py - agent-facing JSON is written ASCII-only, so the idiomatic
`json.load(open(path))` never raises on a host whose default encoding is not UTF-8. (F8)

THE DEFECT. The manifest was written with ensure_ascii=False and legitimately carried non-ASCII
bytes (page text). On Windows (cp1252) an agent told to "load the JSON in a small script" wrote
the obvious `json.load(open(path))`, hit UnicodeDecodeError, burned tool calls and risked
concluding the file was unreadable. Reproduced on a live run. The skill's own helpers are clean
(utf-8-sig everywhere); the failure is purely agent-facing, so it is fixed at the WRITER: a
machine-to-agent file loses nothing by escaping, and json.loads restores the identical strings.

WHAT THIS PINS (the files this module owns; run.py's manifest writer is reported, not tested):
  1. both schema files an agent is pointed at (`record_schema_path` in the manifest; the canonical
     schema in the gate rubric) are pure ASCII and decode identically under cp1252 and utf-8;
  2. interpret_prep's CLI prints its deck entry ASCII-only even when the deck's page text is not;
  3. the typed field registry serialises ASCII-only.
Builds ONE single-page PDF with PyMuPDF; skips check 2 with a note when no renderer is present.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

FAILS = []


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    print("== 1. the two schema files ==")
    for rel in ("templates/record_schema.json", "templates/canonical.schema.json"):
        b = (ROOT / rel).read_bytes()
        ck(b.isascii(), f"{rel} is pure ASCII (non-ASCII bytes: {sum(1 for x in b if x > 127)})")
        try:
            same = json.loads(b.decode("cp1252")) == json.loads(b.decode("utf-8"))
        except Exception as e:  # a cp1252 decode error IS the defect
            same = False
            print(f"       ({type(e).__name__}: {e})")
        ck(same, f"{rel} parses to the same object under cp1252 and utf-8 (the naive json.load path)")
        s = b.decode("utf-8")
        ck("\\u20ac" in s or "\\u00a3" in s, f"{rel} still carries its currency examples, escaped rather than dropped")

    print("== 2. interpret_prep CLI output ==")
    try:
        import fitz  # noqa: F401
        have_fitz = True
    except Exception:
        have_fitz = False
    if not have_fitz:
        print("  skip  no PyMuPDF here - cannot build the fixture deck (the source guard below still runs)")
    else:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            deck = out / "fixture.pdf"
            doc = fitz.open()
            page = doc.new_page()
            # enough text to route to TEXT mode, with a non-ASCII run a cp1252 host would trip on
            body = ("Example Park\nGröße 12.500 m²\nUnit 7\nClear height 12 m\n" * 4)
            page.insert_text((72, 72), body, fontsize=10, fontname="helv")
            doc.save(str(deck))
            doc.close()
            r = subprocess.run([sys.executable, str(HELPERS / "interpret_prep.py"), str(deck),
                                "--region", "R", "--country", "GB", "--out-dir", str(out / "vision")],
                               capture_output=True, timeout=300)
            ck(r.returncode == 0, f"interpret_prep CLI ran (rc={r.returncode}) {r.stderr[-200:]!r}")
            ck(r.stdout.isascii(), f"CLI stdout is pure ASCII ({sum(1 for x in r.stdout if x > 127)} non-ASCII bytes)")
            ck(b"\\u00f6" in r.stdout or b"\\u00df" in r.stdout,
               "the non-ASCII page text is present as \\u escapes, not dropped")
            head = r.stdout.decode("ascii", "replace")
            ck("OK mode=text" in head, "the fixture routed to text mode, so the escaped text is the page text")
    src = (HELPERS / "interpret_prep.py").read_text(encoding="utf-8")
    ck("print(json.dumps(ent, ensure_ascii=True" in src,
       "the CLI print is ensure_ascii=True in source (a revert is visible)")

    print("== 3. the typed registry ==")
    import interpret_prep as IP  # noqa: E402
    import _common as C  # noqa: E402
    reg = IP.reader_field_registry(sorted(C.canonical_property_fields()), include_orchestrator=True)
    ck(json.dumps(reg).isascii(), "the full typed registry (every hint included) serialises ASCII-only")

    print("STATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
