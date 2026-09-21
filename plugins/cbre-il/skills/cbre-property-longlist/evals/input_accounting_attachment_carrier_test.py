#!/usr/bin/env python3
"""input_accounting_attachment_carrier_test.py - an email whose only contribution was its
attachments is accounted for, not called a vanished source. (B08)

THE LIVE FAILURE. A corpus of 16 broker emails plus 22 brochures came back with eleven
copies of "[FAIL] Broker07.msg: discovered at intake but contributed NOTHING ... A whole
source has silently vanished" on a run where nothing was lost. Each of those emails carried
brochure attachments, intake saved them into `<date>_<subject>_attachments/`, every brochure
was read and shipped, and the body simply held no quotable property data. A saved attachment
enters the ledger under its OWN filename, never its carrier's, so the .msg fell through every
bucket to the one that blocks.

The fix must not cost the gate its teeth, so the must-fire cases are asserted as hard as the
must-not-fire ones. Four cases:
  1. the carrier whose one saved attachment reached the ledger  -> PASS, named in a note;
  2. a carrier that DECLARED an attachment nothing ever saved   -> BLOCKS, old wording;
  3. a carrier with no attachments and no ledger rows           -> BLOCKS (the real loss);
  4. a carrier whose saved set is one read brochure plus a loose signature image -> PASS.
Offline; no network, no build."""
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

CARRIER = "Broker07.msg"
ATT_DIR = "2026-09-03_SmartParc SEGRO Derby_attachments"
BROCHURE = "SmartParc SEGRO Derby Unit1 Brochure.pdf"
SIGNATURE = "image003.png"
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _work(declared=0, saved=(), sidecar_atts=None, ledger=()):
    """A work dir plus a real inputs folder: the carrier .msg, its attachments folder, and
    the `.from_email.json` sidecar extract_email writes beside them. Written by hand rather
    than by running intake, so the fixture pins the on-disk contract the gate reads."""
    d = Path(tempfile.mkdtemp(prefix="cbre_carrier_"))
    inputs = d / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / CARRIER).write_bytes(b"(a .msg stub)")
    folder = inputs / ATT_DIR
    rel_saved = []
    if saved or sidecar_atts is not None:
        folder.mkdir(parents=True, exist_ok=True)
    for s in saved:
        (folder / s).write_bytes(b"%PDF-1.4 stub")
        rel_saved.append(f"{ATT_DIR}/{s}")
    if sidecar_atts is not None:
        (folder / ".from_email.json").write_text(json.dumps(
            {"subject": "SmartParc SEGRO Derby", "date": "2026-09-03", "file": CARRIER,
             "attachments": list(sidecar_atts), "skipped_inline": []}), encoding="utf-8")
    (d / "inventory.json").write_text(json.dumps({
        "folder": str(inputs),
        "emails": [CARRIER],
        "clusters": [{"files": [f"{ATT_DIR}/{s}" for s in saved
                                if s.lower().endswith((".pdf", ".pptx"))]}],
        "images": [f"{ATT_DIR}/{s}" for s in saved
                   if s.lower().endswith((".png", ".jpg", ".jpeg"))],
        "email_attachments": [{"email": CARRIER, "declared": declared,
                               "saved": [{"file": r} for r in rel_saved],
                               "skipped_inline": []}],
    }), encoding="utf-8")
    (d / "canonical.json").write_text(json.dumps(
        {"meta": {"client": "A"}, "properties": [{"id": 1, "park": "P"}]}), encoding="utf-8")
    rows = ["property_id,field,value,source_file,source_locator"]
    rows += [f"1,park,P,{n},page 1" for n in ledger]
    (d / "source_ledger.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (d / "unreadable.json").write_text("[]", encoding="utf-8")
    return d


def _run(d):
    return subprocess.run(
        [sys.executable, str(HELPERS / "gate_runner.py"), "input-accounting",
         str(d / "canonical.json"), "--work", str(d)],
        capture_output=True, text=True, errors="replace")


def main() -> int:
    # --- 1. the live case: the body said nothing, the brochure shipped ----------
    d1 = _work(declared=1, saved=[BROCHURE], sidecar_atts=[BROCHURE], ledger=[BROCHURE])
    p = _run(d1)
    ck(p.returncode == 0 and "ALL-PASS" in p.stdout,
       f"a carrier whose saved brochure was read does NOT red the run {ascii(p.stdout[-90:])}")
    ck("contributed only through attachments that were read" in p.stdout,
       "...and is counted in its own bucket on the [PASS] line")
    ck(CARRIER in p.stdout and BROCHURE in p.stdout and "contributed no records of its own"
       in p.stdout,
       "...with a note naming the attachment that stood in for it, so the credit is visible")
    b1 = GR._accounting_buckets(d1, d1 / "canonical.json")
    ck(CARRIER in b1.get("attachment_carrier", []) and not b1["unaccounted"],
       "...and lands in `attachment_carrier`, not `unaccounted`")

    # --- 2. MUST FIRE: an attachment was declared and nothing ever saved it -----
    d2 = _work(declared=1, saved=[], sidecar_atts=None, ledger=[])
    p = _run(d2)
    ck(p.returncode != 0 and "BLOCKED" in p.stdout,
       f"a carrier whose declared attachment never reached the run BLOCKS "
       f"{ascii(p.stdout[-90:])}")
    ck("silently vanished" in p.stdout and CARRIER in p.stdout,
       "...named, with the existing consequence spelled out")

    # --- 3. MUST FIRE: no attachments, no records. Nothing stood in for it ------
    d3 = _work(declared=0, saved=[], sidecar_atts=None, ledger=[])
    p = _run(d3)
    ck(p.returncode != 0 and "silently vanished" in p.stdout,
       f"an email with no attachments and no ledger rows still BLOCKS "
       f"{ascii(p.stdout[-90:])}")

    # --- 4. a read brochure plus the sender's signature image -------------------
    # The 6 KB logo is saved beside the brochure on plenty of real emails. It has no consumer
    # in the spine, so demanding a ledger row for it would re-block the case fixed above.
    d4 = _work(declared=2, saved=[BROCHURE, SIGNATURE], sidecar_atts=[BROCHURE, SIGNATURE],
               ledger=[BROCHURE])
    p = _run(d4)
    ck(p.returncode == 0 and "ALL-PASS" in p.stdout,
       f"a loose signature image among the saved attachments does not red the carrier "
       f"{ascii(p.stdout[-90:])}")
    b4 = GR._accounting_buckets(d4, d4 / "canonical.json")
    ck(CARRIER in b4.get("attachment_carrier", []),
       "...the carrier is still credited")
    ck(SIGNATURE in [Path(x).name for x in b4["no_consumer"]],
       "...and the image is accounted as `no_consumer`, in its own right")

    if FAILS:
        print(f"\nINPUT ACCOUNTING ATTACHMENT CARRIER TEST: FAIL ({len(FAILS)})")
        return 1
    print("\nINPUT ACCOUNTING ATTACHMENT CARRIER TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
