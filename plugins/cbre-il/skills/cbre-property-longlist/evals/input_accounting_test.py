#!/usr/bin/env python3
"""input_accounting_test.py - nothing discovered at intake vanishes silently. (B08)

There was no input->output reconciliation anywhere: 11 decks and a 12-row tracker could
ship 23 properties or 9 and both were ALL-PASS. cmd_coverage's docstring advertised "every
cluster produced records" while only checking duplicates and per-record fill.

The backlog's remedy - "every input produced a record or is listed unreadable" - would CRY
WOLF on a correct run, and that is the interesting half of this test. There are six honest
outcomes, not two:
  contributed fields / contributed a photo only / recorded unreadable / no consumer in the
  spine (a loose image) / declared-but-empty / unaccounted.
Only the last is a defect. A gate that reds a correct run gets switched off, so the
must-not-fire cases are asserted as hard as the must-fire one. Offline."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import gate_runner as GR  # noqa: E402


def _work(files, ledger_names, unreadable=(), photo=()):
    d = Path(tempfile.mkdtemp(prefix="cbre_acc_"))
    (d / "inventory.json").write_text(json.dumps({
        "clusters": [{"files": [f for f in files if f.endswith((".pdf", ".pptx"))]}],
        "xlsx": [f for f in files if f.endswith((".xlsx", ".csv"))],
        "images": [f for f in files if f.endswith((".jpg", ".png"))],
    }), encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps(
        {"meta": {"client": "A"}, "properties": [{"id": 1, "park": "P"}]}), encoding="utf-8")
    rows = ["property_id,field,value,source_file,source_locator"]
    rows += [f"1,park,P,{n},page 1" for n in ledger_names]
    (d / "source_ledger.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (d / "unreadable.json").write_text(json.dumps([[u, "corrupt"] for u in unreadable]),
                                       encoding="utf-8")
    if photo:
        (d / "photo_overrides.json").write_text(
            json.dumps({p: p for p in photo}), encoding="utf-8")
    return d


def _run(d):
    return subprocess.run(
        [sys.executable, str(HELPERS / "gate_runner.py"), "input-accounting",
         str(d / "canonical.json"), "--work", str(d)],
        capture_output=True, text=True, errors="replace")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # --- MUST NOT FIRE on correct runs -----------------------------------------
    d = _work(["a.pdf", "b.pdf", "t.xlsx"], ["a.pdf", "b.pdf", "t.xlsx"])
    p = _run(d)
    ck(p.returncode == 0 and "ALL-PASS" in p.stdout,
       f"a fully-contributing corpus passes {ascii(p.stdout[-70:])}")

    # a loose image has NO consumer in the spine - it must not red the run
    d = _work(["a.pdf", "site.jpg"], ["a.pdf"])
    p = _run(d)
    ck(p.returncode == 0, "a stray loose image does NOT red a correct run")
    ck("no consumer" in p.stdout,
       "...but IS named, so the gap is honest rather than hidden")

    # a brochure bound CONFIDENTLY as a photo contributes zero records BY DESIGN
    d = _work(["a.pdf", "photos.pdf"], ["a.pdf"], photo=["photos.pdf"])
    p = _run(d)
    ck(p.returncode == 0, "a photo-only brochure does NOT red the run")
    ck("contributed a photo only" in p.stdout, "...and is counted in its own bucket")

    # an unreadable input is accounted for by being recorded
    d = _work(["a.pdf", "broken.pdf"], ["a.pdf"], unreadable=["broken.pdf"])
    p = _run(d)
    ck(p.returncode == 0, "a RECORDED unreadable input does not red the run")

    # --- MUST FIRE: a source that vanished with nothing recorded ---------------
    d = _work(["a.pdf", "ghost.pdf"], ["a.pdf"])
    p = _run(d)
    ck(p.returncode != 0 and "BLOCKED" in p.stdout,
       f"a deck that contributed NOTHING blocks {ascii(p.stdout[-70:])}")
    ck("ghost.pdf" in p.stdout, "...and is named")
    ck("silently vanished" in p.stdout, "...with the consequence spelled out")

    # a tracker lost to a missing reader is recorded by B15, so it lands in `unreadable`
    d = _work(["t.xlsx"], [], unreadable=["t.xlsx"])
    p = _run(d)
    ck(p.returncode == 0,
       "a reader-lost tracker is accounted for (B15 records it) rather than vanishing")

    # the false docstring claim is gone
    gsrc = (HELPERS / "gate_runner.py").read_text(encoding="utf-8", errors="replace")
    head = gsrc[:gsrc.find("def ")]
    ck("every cluster produced records" not in head,
       "cmd_coverage no longer advertises a reconciliation it never did")
    ck("input-accounting" in head, "the new gate is documented in the module header")
    gates = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8", errors="replace")
    ck("G-inputs" in gates, "reference/gates.md lists the gate")

    # B56: `clusters` is a DICT (region -> cluster object), not a list, so the old
    # `isinstance(v, list)` test skipped EVERY brochure. Measured on a live 12-input run: ONE
    # input accounted. The `unaccounted` bucket - the one that BLOCKS - was unreachable for a
    # PDF, which is the input type most likely to vanish and the exact case this gate exists for.
    import csv as _csv
    d = Path(tempfile.mkdtemp(prefix="cbre_acc_dict_"))
    (d / "inventory.json").write_text(json.dumps({
        "clusters": {
            "Alpha": {"region": "Alpha", "pdfs": ["Alpha.pdf"], "pptxs": [], "pdf": "Alpha.pdf"},
            "Beta": {"region": "Beta", "pdfs": ["Beta.pdf"], "pptxs": ["Beta.pptx"]},
        },
        "xlsx": ["tracker.xlsx"], "emails": [], "images": [],
        "unclassified": ["notes.txt"],
    }), encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps({"meta": {}, "properties": []}),
                                      encoding="utf-8")

    def _ledger(names):
        with open(d / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(["property_id", "field", "value", "source_file", "source_locator",
                        "source_type"])
            for nm in names:
                w.writerow(["1", "park", "P", nm, "page 1", "pdf"])

    _ledger(["Alpha.pdf", "Beta.pdf", "Beta.pptx", "tracker.xlsx", "notes.txt"])
    b = GR._accounting_buckets(d, d / "canonical.json")
    total = sum(len(v) for v in b.values())
    ck(total == 5, f"a DICT-shaped clusters inventory accounts every input (got {total} of 5)")
    ck(len(b["records"]) == 5, "...all five reached the ledger, so all five are 'records'")
    ck("notes.txt" in b["records"],
       "...including an `unclassified` file (the key is not 'other', which never existed)")
    ck("Alpha.pdf" in b["records"] and "Beta.pptx" in b["records"],
       "...and both a scalar `pdf` and a `pptxs` list entry are seen")

    _ledger(["tracker.xlsx"])   # the brochures now contributed NOTHING
    b2 = GR._accounting_buckets(d, d / "canonical.json")
    ck("Alpha.pdf" in b2["unaccounted"] and "Beta.pdf" in b2["unaccounted"],
       "a brochure that contributed NOTHING is now UNACCOUNTED (it used to be invisible)")

    if fails:
        print(f"\nINPUT ACCOUNTING TEST: FAIL ({len(fails)})")
        return 1
    print("\nINPUT ACCOUNTING TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
