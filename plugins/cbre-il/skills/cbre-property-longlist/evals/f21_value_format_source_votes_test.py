#!/usr/bin/env python3
"""f21_value_format_source_votes_test.py - the value-format gate counts SOURCE FILES, not records.

THE DEFECT, live. The gate BLOCKED with "6 properties ship a BARE number while 3 write it as a
magnitude + unit". The three were not three sources: they were ONE deck's three unit records,
each carrying the same site-wide value byte for byte, so one brochure cast three votes for its
own format. When that deck was later collapsed to one record for an unrelated reason the gate
passed with no other change, and nothing about the data had improved. How many records a deck
contributes is a fact about deck structure, not about formatting consistency, and it cuts both
ways: a spurious block here, and on a corpus where the odd format belongs to the multi-unit deck
a real one suppressed, or the wrong unit named as dominant.

THE FIX: each measured sibling votes ONCE PER SOURCE FILE, joined through the ledger on
(property id, field). Both the `--min-siblings` evidence threshold and the dominant-unit majority
are counted in votes. Distinct VALUES were considered and rejected as the unit of evidence:
standardised specs ("10 m", "12.5 m") legitimately repeat across independent decks, and
collapsing those would suppress the very finding this gate exists for. Without a ledger each
record is its own vote (the old arithmetic) and the gate prints a note saying so.

WHAT THIS PINS:
  1. the live shape: one deck, three identical unit records, six bare siblings -> PASS;
  2. two independent sources writing the unit -> still BLOCKS, and the message counts sources;
  3. dominance is by source: one deck's three 'sq ft' records do not outvote two decks' 'sq m';
  4. a multi-unit deck on the BARE side is still called out (every bare record needs a fix);
  5. no ledger -> the old per-record arithmetic, with a note; `--ledger` may name one explicitly;
  6. the emitted findings JSON carries `measured_sources` for the clarify bridge.
Offline; subprocess against the real CLI.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _canon(props):
    base = {"country": "DE", "city": "Beispielstadt", "developer": "Dev", "park": "Park",
            "areaUnit": "sq m", "rentUnit": "EUR/sq m/yr"}
    return {"meta": {"client": "Fmt", "units": {"area": "sq m"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def _write(d: Path, props, sources: dict | None, ledger_name="source_ledger.csv") -> Path:
    """canonical.json in `d`, plus a ledger beside it mapping property id -> source file for
    every field the property carries. `sources` None = no ledger at all."""
    d.mkdir(parents=True, exist_ok=True)
    c = d / "canonical.json"
    c.write_text(json.dumps(_canon(props)), encoding="utf-8")
    if sources is not None:
        with open(d / ledger_name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["property_id", "record_type", "field", "value", "source_file",
                        "source_locator", "source_type", "extractor", "confidence",
                        "conflict_note", "verified"])
            for p in props:
                for f, v in p.items():
                    if f == "id":
                        continue
                    w.writerow([p["id"], "property", f, v, sources[p["id"]], "page 1", "pdf",
                                "E-pdf", "High", "", "no"])
    return c


def run(canonical: Path, *extra) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GATE), "value-format", str(canonical), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)

        print("1. the live shape: one deck, three unit records, one site-wide value")
        props = ([dict(id=i, clearHeight="12.5 m") for i in (1, 2, 3)]           # deck A, 3 units
                 + [dict(id=i, clearHeight="12") for i in (4, 5, 6, 7, 8, 9)])   # six other decks
        src = {1: "A.pdf", 2: "A.pdf", 3: "A.pdf", 4: "B.pdf", 5: "C.pdf", 6: "D.pdf",
               7: "E.pdf", 8: "F.pdf", 9: "G.pdf"}
        rc, out = run(_write(t / "live", props, src))
        ck(rc == 0 and "STATUS: ALL-PASS" in out,
           "three identical unit records from ONE deck are one vote: below the evidence "
           "threshold, so the six bare siblings are NOT blocked on that deck's say-so")
        ck("no source ledger" not in out, "the ledger beside the canonical was found and joined")

        print("2. two independent sources still carry the day")
        src2 = {**src, 3: "H.pdf"}
        rc, out = run(_write(t / "two", props, src2))
        ck(rc == 1 and "STATUS: BLOCKED" in out,
           "the same records with the third measured value from a SECOND deck BLOCK")
        ck("from 2 independent source(s)" in out,
           "...and the message counts sources, not records, so the reader sees the evidence")
        ck("id=4" in out and "id=9" in out, "every bare property is still named")

        print("3. dominance is by source, not by record")
        props3 = ([dict(id=i, divisibleFrom="50,000 sq ft") for i in (1, 2, 3)]   # deck A, 3 units
                  + [dict(id=4, divisibleFrom="4,500 sq m"), dict(id=5, divisibleFrom="5,200 sq m"),
                     dict(id=6, divisibleFrom="4800")])                        # two decks + bare
        src3 = {1: "A.pdf", 2: "A.pdf", 3: "A.pdf", 4: "B.pdf", 5: "C.pdf", 6: "D.pdf"}
        rc, out = run(_write(t / "dom", props3, src3))
        ck(rc == 1 and "('sqm')" in out and "('sqft')" not in out,
           "one deck's three 'sq ft' records do not outvote two decks' 'sq m': the dominant unit named "
           "is the one most SOURCES write (a record count would have named 'sq ft')")

        print("4. a multi-unit deck on the BARE side is still called out")
        props4 = ([dict(id=i, clearHeight="10") for i in (1, 2, 3)]                  # deck A, bare x3
                  + [dict(id=4, clearHeight="10 m"), dict(id=5, clearHeight="12 m")])  # two decks
        src4 = {1: "A.pdf", 2: "A.pdf", 3: "A.pdf", 4: "B.pdf", 5: "C.pdf"}
        rc, out = run(_write(t / "bare", props4, src4))
        ck(rc == 1 and "3 property(ies) ship a BARE number" in out,
           "three bare unit records from one deck are three properties to fix, and are listed")

        print("5. without a ledger the arithmetic is per record, and says so")
        rc, out = run(_write(t / "noledger", props, None))
        ck(rc == 1 and "counted per RECORD" in out,
           "no ledger anywhere: the old per-record count applies and a note names the caveat")
        rc, out = run(_write(t / "named", props, src, ledger_name="elsewhere.csv"),
                      "--ledger", str(t / "named" / "elsewhere.csv"))
        ck(rc == 0 and "counted per RECORD" not in out,
           "`--ledger` names a ledger that is not beside the canonical")

        print("6. the findings JSON carries the source count for the clarify bridge")
        c = _write(t / "json", props, src2)
        rc, out = run(c, "--emit-json", str(t / "json" / "findings.json"))
        payload = json.loads((t / "json" / "findings.json").read_text(encoding="utf-8"))
        ck(len(payload) == 1 and payload[0]["measured_count"] == 3
           and payload[0]["measured_sources"] == 2,
           "measured_count stays the record count (clarify prints it) and measured_sources "
           "is the new vote count")

        print("7. the WHY is in the gate, not only in this eval")
        src_txt = GATE.read_text(encoding="utf-8")
        ck("UNIT OF EVIDENCE IS A SOURCE FILE" in src_txt and "one brochure cast three votes" in src_txt,
           "gate_runner states the live defect and the rule beside the code")
        ck("Distinct VALUES were considered and rejected" in src_txt,
           "...and records why distinct values were not the unit chosen")

    print()
    if FAILS:
        print(f"F21 VALUE-FORMAT SOURCE VOTES TEST: FAIL ({len(FAILS)})")
        return 1
    print("F21 VALUE-FORMAT SOURCE VOTES TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
