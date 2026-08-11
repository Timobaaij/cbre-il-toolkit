#!/usr/bin/env python3
"""capture_symmetry_test.py - the cheap mechanical signal for UNDER-CAPTURE. (B58)

THE BLIND SPOT. Every data gate checks that POPULATED fields trace to a source. None can know
what the page SAID, so a reader that skips stated rows is invisible: validate-data, coverage,
trace-coverage and prov-containment all went ALL-PASS on a run that had dropped six field
families printed on the page, and merge had already converted each omission into a positive
"absent in all sources" ledger row. It took two Opus reviewers to catch.

THE SIGNAL, which costs nothing. If deck A's records carry `sprinklers` and deck B's carry it on
ZERO records, either B genuinely never states it or B's reader dropped it. That is exactly the
shape of the live failure - Budapest's reader emitted sprinklers/permitting/officeRent, the other
two did not, and the union made their silence into 19 false absence rows per field.

ADVISORY BY DESIGN, and this test pins that too: different agents really do use different
templates, so an asymmetry is a question for the reviewers, never a verdict. A gate that BLOCKED
here would fail every legitimately heterogeneous corpus, which is worse than the defect.

WHAT THIS PINS:
  1. the asymmetric field is NAMED, with the decks that have it and the decks that do not;
  2. a field present on every deck is NOT reported (no noise);
  3. a field absent from every deck is NOT reported (it is a real gap, not an asymmetry);
  4. pipeline-ASSIGNED fields are never reported (a reader is not asked for them);
  5. the gate stays ALL-PASS (advisory), and no-ops below two sources.
Offline. Drives the real gate through its real CLI.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"


def _rec(src, page, **fields):
    return dict(fields, __meta={"source_file": src, "page_no": page,
                                "source_type": "pdf", "locator_base": f"page {page + 1}"})


def _run(work: Path):
    p = subprocess.run([sys.executable, str(GATE), "capture-symmetry", "--work", str(work)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "work"
        (work / "extract").mkdir(parents=True)

        # Deck A states sprinklers + permitting; deck B states neither. Both state park/city.
        # `landPrice` is absent from BOTH (a real gap, not an asymmetry). `id`/`photo` are
        # pipeline-assigned and appear on A only - they must never be reported.
        (work / "extract" / "A_vision.json").write_text(json.dumps([
            _rec("A.pdf", 0, park="Alpha", city="Corby", sprinklers="Yes",
                 permitting="Consented", id=1, photo="data:image/png;base64,AAA"),
            _rec("A.pdf", 1, park="Beta", city="Corby", sprinklers="No",
                 permitting="Detailed"),
        ]), encoding="utf-8")
        (work / "extract" / "B_vision.json").write_text(json.dumps([
            _rec("B.pdf", 0, park="Gamma", city="Bor"),
            _rec("B.pdf", 1, park="Delta", city="Bor"),
        ]), encoding="utf-8")
        # a non-record artefact in the same folder must be ignored, not crash the gate
        (work / "extract" / "SomeTracker_map.json").write_text(
            json.dumps({"input_hash": "abc", "map": {"columns": []}}), encoding="utf-8")

        rc, out = _run(work)

        ck(rc == 0, "the gate is ADVISORY - it returns 0 even with findings")
        ck("STATUS: ALL-PASS" in out, "...and reports ALL-PASS, so it can never block a run")
        ck("`sprinklers`" in out, "the asymmetric field `sprinklers` is named")
        ck("`permitting`" in out, "the asymmetric field `permitting` is named")
        ck("A.pdf" in out and "B.pdf" in out,
           "both the having deck and the missing deck are named, so the reviewer can re-derive")
        ck("`park`" not in out and "`city`" not in out,
           "a field every deck carries is NOT reported (no noise)")
        ck("`landPrice`" not in out,
           "a field NO deck carries is NOT reported - that is a gap, not an asymmetry")
        ck("`id`" not in out and "`photo`" not in out,
           "pipeline-assigned fields are never reported - a reader is not asked for them")

        # single source -> nothing to compare
        solo = Path(td) / "solo"
        (solo / "extract").mkdir(parents=True)
        (solo / "extract" / "A_vision.json").write_text(json.dumps([
            _rec("A.pdf", 0, park="Alpha", sprinklers="Yes"),
        ]), encoding="utf-8")
        rc2, out2 = _run(solo)
        ck(rc2 == 0 and "not applicable" in out2,
           "with a single source the gate no-ops instead of inventing an asymmetry")

        # symmetric corpus -> explicit clean statement, not silence
        sym = Path(td) / "sym"
        (sym / "extract").mkdir(parents=True)
        (sym / "extract" / "A_vision.json").write_text(json.dumps([
            _rec("A.pdf", 0, park="Alpha", sprinklers="Yes")], ), encoding="utf-8")
        (sym / "extract" / "B_vision.json").write_text(json.dumps([
            _rec("B.pdf", 0, park="Gamma", sprinklers="No")], ), encoding="utf-8")
        rc3, out3 = _run(sym)
        ck(rc3 == 0 and "symmetrically" in out3,
           "a symmetric corpus says so explicitly rather than printing nothing")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
