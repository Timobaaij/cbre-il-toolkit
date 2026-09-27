#!/usr/bin/env python3
"""email_locator_test.py - an email record's locator names the MESSAGE, and one unreadable .msg
no longer blanks a whole directory's Emails tab. (2026-09-26 test run, fix 3.11.)

THE DEFECT. extract_email stamped `__meta.source_file = <subject>` and `locator_base =
"email <date>"`. A thread yields "RE: X" several times on one morning, so three messages shared
one source and one locator, and input-accounting (which credits a ledger row by the source_file
BASENAME) could never credit the .msg a value came from. Separately, master_list.email_index
paired parsed records to files by POSITION and gave up when the counts differed - which they do
whenever one .msg no reader can open returns no stub - so every message in that directory
vanished from the Emails tab.

WHAT THIS PINS
  * two .eml sharing subject AND date, different senders: distinct locators, each naming the
    date, the sender and the file; source_file is the file name; the subject is kept;
  * an unreadable stub carries email_file too;
  * email_index keeps every readable message when one .msg returns nothing at all.
Offline; synthetic .eml; the .msg reader is monkeypatched (no .msg bytes are parsed).
"""
from __future__ import annotations

import email.message
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import extract_email as EM  # noqa: E402
import master_list as ML  # noqa: E402

FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _eml(path: Path, sender: str) -> None:
    m = email.message.EmailMessage()
    m["Subject"] = "RE: your requirement"
    m["From"] = sender
    m["To"] = "agent@example.com"
    m["Date"] = "Mon, 07 Sep 2026 09:00:00 +0100"
    m.set_content("Unit 4 is still available.")
    path.write_bytes(m.as_bytes())


def main() -> int:
    print("== two messages, one subject, one date ==")
    with tempfile.TemporaryDirectory(prefix="cbre_loc_") as td:
        d = Path(td)
        _eml(d / "reply one.eml", '"Morgan, Alex" <alex@example-agents.com>')
        _eml(d / "reply two.eml", "sam@other-agents.com")
        (d / "junk.eml").write_bytes(b"\x00\xff")
        out = EM.extract(d, save_attachment_bytes=False)
    good = [r for r in out if not r.get("unreadable")]
    locs = [r["__meta"]["locator_base"] for r in good]
    print(f"    locators: {locs}")
    ck(len(good) == 2 and len(set(locs)) == 2, "the two messages get DISTINCT locators")
    ck(all(l.startswith("email 2026-09-07 from ") for l in locs),
       "each locator names the date and the sender")
    ck("(reply one.eml)" in locs[0] and "Morgan, Alex" in locs[0]
       and "(reply two.eml)" in locs[1] and "sam@other-agents.com" in locs[1],
       "...display name when there is one, the address otherwise, and the file")
    ck([r["__meta"]["source_file"] for r in good] == ["reply one.eml", "reply two.eml"]
       and all(r["__meta"].get("email_file") == r["__meta"]["source_file"] for r in good),
       "source_file (and email_file) is the message's file name")
    ck(all(r["__meta"].get("subject") == "RE: your requirement" for r in good),
       "the subject is kept in __meta.subject")
    bad = [r for r in out if r.get("unreadable")]
    ck(len(bad) == 1 and bad[0]["__meta"].get("email_file") == "junk.eml",
       "an unreadable stub carries email_file too")

    print("== one .msg no reader can open does not blank the directory ==")
    real = EM._read_msg

    def fake(p):
        if p.name == "unopenable.msg":
            return None  # both .msg readers refused it: no stub at all
        return {"subject": "Offer - Quay Road", "from": "Jo Park <jo@third-agents.com>",
                "date": "2026-09-08 10:00:00", "body": "Quay Road, 58,000 sq ft.",
                "attachments": [], "_att_parts": []}

    try:
        EM._read_msg = fake
        with tempfile.TemporaryDirectory(prefix="cbre_loc2_") as td:
            d = Path(td)
            (d / "unopenable.msg").write_bytes(b"not a cfb file")
            (d / "quay.msg").write_bytes(b"not a cfb file either")
            _eml(d / "reply one.eml", "Alex Morgan <alex@example-agents.com>")
            bodies: list = []
            idx = ML.email_index(d, ["unopenable.msg", "quay.msg", "reply one.eml"], [],
                                 bodies=bodies)
    finally:
        EM._read_msg = real
    names = sorted(e["file_name"] for e in idx)
    ck(names == ["quay.msg", "reply one.eml"],
       f"every readable message is still indexed ({names})")
    q = next((e for e in idx if e["file_name"] == "quay.msg"), {})
    ck(q.get("sender") == "Jo Park" and q.get("date") == "8 Sep 2026",
       "...paired with ITS OWN record (sender and date are quay.msg's)")
    ck(any(b.get("unreadable") and b.get("file_name") == "unopenable.msg" for b in bodies),
       "the unopenable message is reported to the bodies file, not silently lost")

    print()
    if FAILS:
        print(f"EMAIL LOCATOR TEST: FAIL ({len(FAILS)})")
        return 1
    print("EMAIL LOCATOR TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
