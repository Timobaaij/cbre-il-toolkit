#!/usr/bin/env python3
"""attachments_folder_reuse_test.py - an email's attachment folder is found by its OWNER, not by
its name, and a hand-edited sidecar survives. (2026-09-26 test run, fix 2.7.)

THE DEFECT. `_attachments_folder` reused only folders matching the CURRENT naming scheme. A
corpus harvested by an earlier version (folders named from the .msg stem, or spelled with an
underscore where the scheme now writes a space) got a SECOND folder per email and seven brochures
written twice; intake then kept the sorted-first copy. And the sidecar write compared full text,
so reusing a sidecar the broker had annotated (a `manual_fix` key) would have dropped the key.

WHAT THIS PINS
  1. an .eml beside a LEGACY-named folder whose sidecar names it and which holds its PDF:
     intake.discover creates no folder, writes no file (mtime_ns snapshot), keeps `manual_fix`,
     and the inventory's saved path names the legacy folder;
  2. the same PDF stored there under an OLD file name is recognised by its bytes - nothing
     written;
  3. a folder owned by ANOTHER email is never reused;
  4. an owned legacy folder missing the attachment gets it written back INTO it, and the
     sidecar is merged (manual_fix kept, the new name appended), never replaced.
Offline; synthetic .eml with a >= 20 KB PDF attachment (smaller is refused as a logo).
"""
from __future__ import annotations

import email.message
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import intake as I  # noqa: E402
import extract_email as EM  # noqa: E402

FAILS: list = []
PDF = b"%PDF-1.4\n% " + b"r" * 22000 + b"\n%%EOF\n"
SUBJECT = "RE: New Search - Riverside"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _eml(path: Path) -> None:
    m = email.message.EmailMessage()
    m["Subject"] = SUBJECT
    m["From"] = "Alex Morgan <alex@example-agents.com>"
    m["To"] = "agent@example.com"
    m["Date"] = "Mon, 07 Sep 2026 09:00:00 +0100"
    m.set_content("Brochure attached.")
    m.add_attachment(PDF, maintype="application", subtype="pdf", filename="Riverside brochure.pdf")
    path.write_bytes(m.as_bytes())


def _sidecar(folder: Path, owner: str, atts: list, extra: dict | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    d = {"subject": SUBJECT, "date": "2026-09-07", "file": owner, "attachments": atts,
         "skipped_inline": []}
    d.update(extra or {})
    (folder / EM.FROM_EMAIL_SIDECAR).write_text(json.dumps(d, indent=2), encoding="utf-8")


def _snap(root: Path) -> dict:
    out = {}
    for dp, dn, fn in os.walk(root):
        for n in dn:
            out[os.path.join(dp, n)] = "dir"
        for n in fn:
            p = os.path.join(dp, n)
            out[p] = os.stat(p).st_mtime_ns
    return out


def _dirs(root: Path) -> list:
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def main() -> int:
    print("== 1. a legacy-named folder the sidecar says is ours ==")
    with tempfile.TemporaryDirectory(prefix="cbre_reuse1_") as td:
        inputs = Path(td) / "in"
        inputs.mkdir()
        _eml(inputs / "offer.eml")
        legacy = inputs / "2026-09-07_offer_attachments"
        _sidecar(legacy, "offer.eml", ["Riverside brochure.pdf"], {"manual_fix": "approved"})
        (legacy / "Riverside brochure.pdf").write_bytes(PDF)
        before, dirs0 = _snap(inputs), _dirs(inputs)
        inv = I.discover(inputs)
        ck(_dirs(inputs) == dirs0, f"no new folder is created ({_dirs(inputs)})")
        ck(_snap(inputs) == before, "no file is written or touched (mtime_ns unchanged)")
        side = json.loads((legacy / EM.FROM_EMAIL_SIDECAR).read_text(encoding="utf-8"))
        ck(side.get("manual_fix") == "approved", "the hand-added sidecar key survives")
        saved = [s["file"] for e in inv["email_attachments"] for s in e.get("saved") or []]
        ck(saved == ["2026-09-07_offer_attachments/Riverside brochure.pdf"],
           f"the inventory's saved path names the legacy folder ({saved})")

    print("== 2. the same bytes under an OLD file name ==")
    with tempfile.TemporaryDirectory(prefix="cbre_reuse2_") as td:
        inputs = Path(td) / "in"
        inputs.mkdir()
        _eml(inputs / "offer.eml")
        legacy = inputs / "2026-09-07_RE_ New Search - Riverside_attachments"
        _sidecar(legacy, "offer.eml", ["riverside_brochure_v1.pdf"])
        (legacy / "riverside_brochure_v1.pdf").write_bytes(PDF)
        before = _snap(inputs)
        inv = I.discover(inputs)
        ck(_snap(inputs) == before, "recognised by its bytes: nothing written, nothing renamed")
        saved = [s["file"] for e in inv["email_attachments"] for s in e.get("saved") or []]
        ck(saved == [f"{legacy.name}/riverside_brochure_v1.pdf"],
           f"...and the saved path is the existing file ({saved})")

    print("== 3. a folder owned by ANOTHER email is never reused ==")
    with tempfile.TemporaryDirectory(prefix="cbre_reuse3_") as td:
        inputs = Path(td) / "in"
        inputs.mkdir()
        _eml(inputs / "offer.eml")
        theirs = inputs / "2026-09-07_theirs_attachments"
        _sidecar(theirs, "someone else.eml", ["Riverside brochure.pdf"])
        (theirs / "Riverside brochure.pdf").write_bytes(PDF)
        side_before = (theirs / EM.FROM_EMAIL_SIDECAR).read_bytes()
        inv = I.discover(inputs)
        saved = [s["file"] for e in inv["email_attachments"] for s in e.get("saved") or []]
        ck(saved and not saved[0].startswith(theirs.name + "/"),
           f"offer.eml saves into its own folder ({saved})")
        ck((theirs / EM.FROM_EMAIL_SIDECAR).read_bytes() == side_before,
           "...and the other email's sidecar is untouched")

    print("== 4. an owned legacy folder missing the attachment ==")
    with tempfile.TemporaryDirectory(prefix="cbre_reuse4_") as td:
        inputs = Path(td) / "in"
        inputs.mkdir()
        _eml(inputs / "offer.eml")
        legacy = inputs / "2026-09-07_offer_attachments"
        _sidecar(legacy, "offer.eml", ["an older attachment.pdf"], {"manual_fix": "keep me"})
        dirs0 = _dirs(inputs)
        inv = I.discover(inputs)
        ck(_dirs(inputs) == dirs0 and (legacy / "Riverside brochure.pdf").read_bytes() == PDF,
           "the missing attachment is written back INTO the owned legacy folder")
        side = json.loads((legacy / EM.FROM_EMAIL_SIDECAR).read_text(encoding="utf-8"))
        ck(side.get("manual_fix") == "keep me"
           and side.get("attachments") == ["an older attachment.pdf", "Riverside brochure.pdf"],
           f"the sidecar is MERGED: key kept, order kept, new name appended ({side.get('attachments')})")
        before = _snap(inputs)
        I.discover(inputs)
        ck(_snap(inputs) == before, "a second pass writes nothing (idempotent)")

    print()
    if FAILS:
        print(f"ATTACHMENTS FOLDER REUSE TEST: FAIL ({len(FAILS)})")
        return 1
    print("ATTACHMENTS FOLDER REUSE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
