#!/usr/bin/env python3
"""email_bodies_test.py - every email body is written ONCE to work/email_bodies.md before exit 17,
with repeated paragraphs replaced by a pointer. (2026-09-26 test run, fix 1.6.)

THE COST. The exit-17 master-list agent was told "N .msg/.eml file(s) in <folder>" and opened
every message itself - 16 messages, 98 KB of bodies on the live run - while the spine's own email
index had already parsed every body and thrown it away. A thread also repeats itself: a society
disclaimer and the requirement summary appeared ten times each.

WHAT THIS PINS
  * one section per message, earliest first, headed with file name, sender, date, cleaned
    subject, inputs-relative path, the `source_files` value and the attachments saved;
  * a >= 40-char paragraph seen before (quote markers ignored) becomes [= E<k> ¶<n>] and its
    target is marked ¶<n>; a short line ("Thanks,") is never replaced; a unique paragraph is
    verbatim; the intro tells the agent to read THIS file, never the .msg/.eml;
  * a message no reader could open is listed with the reason, not dropped;
  * build_auto writes the file only when the run has emails, and removes a stale one when not.
Offline; synthetic .eml built with the stdlib.
"""
from __future__ import annotations

import email.message
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import master_list as ML  # noqa: E402

FAILS: list = []
PARA = "¶"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


DISCLAIMER = ("This email and any attachments are confidential and intended solely for the "
              "addressee. If you have received it in error, please delete it and tell us.")
REQUIREMENT = ("Our client requires 55,000 to 65,000 sq ft of logistics space with ten dock "
               "doors within thirty minutes of the port.")
OFFER = "Please see our offer: Riverside Park Unit 4, 62,000 sq ft, 12m clear, available now."


def _eml(path: Path, sender: str, body: str) -> None:
    m = email.message.EmailMessage()
    m["Subject"] = "RE: Requirement - 60,000 sq ft"
    m["From"] = sender
    m["To"] = "agent@example.com"
    m["Date"] = "Mon, 07 Sep 2026 09:00:00 +0100"
    m.set_content(body)
    path.write_bytes(m.as_bytes())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cbre_bodies_") as td:
        inputs, work = Path(td) / "in", Path(td) / "work"
        inputs.mkdir()
        work.mkdir()
        _eml(inputs / "a_first.eml", "Alex Morgan <alex@example-agents.com>",
             f"Hi,\n\n{OFFER}\n\n{REQUIREMENT}\n\n{DISCLAIMER}\n\nThanks,")
        _eml(inputs / "b_second.eml", "Sam Lee <sam@other-agents.com>",
             "Hello,\n\nWe also have Quay Road, 58,000 sq ft, ready Q2 2027 - map "
             "https://maps.example.com/?q=51.5,-0.1\n\n> " + REQUIREMENT.replace(" doors", "\n> doors")
             + f"\n\n{DISCLAIMER}\n\nThanks,")
        _eml(inputs / "c_third.eml", "Jo Park <jo@third-agents.com>",
             f"Nothing suitable at present, sorry.\n\n{DISCLAIMER}\n\nThanks,")
        (inputs / "d_broken.eml").write_bytes(b"\x00\xff not an email")
        emails = ["a_first.eml", "b_second.eml", "c_third.eml", "d_broken.eml"]
        auto = ML.build_auto(work, {}, {}, inputs, lambda p: "", emails=emails,
                             email_attachments=[])
        p = work / ML.EMAIL_BODIES
        ck(p.exists(), "build_auto wrote work/email_bodies.md for a run with emails")
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        print("    ---\n    " + "\n    ".join(text.splitlines()[:14]) + "\n    ---")
        ck("never the .msg/.eml" in text, "the intro sends the agent to THIS file, never the .msg/.eml")
        ck(text.index("## E1 - a_first.eml") < text.index("## E2 - b_second.eml")
           < text.index("## E3 - c_third.eml") if "## E3 - c_third.eml" in text else False,
           "one section per message, earliest first (ties by file name)")
        ck("From: Alex Morgan" in text and "Date: 7 Sep 2026" in text
           and "Subject: Requirement - 60,000 sq ft" in text,
           "each header carries sender, human date and the cleaned subject")
        ck("Path: a_first.eml | source_files value: a_first.eml" in text,
           "...the inputs-relative path and the value for a row's source_files")
        ck(text.count("Attachments saved: none") == 4,
           "...and the attachments saved (every section, the unreadable one included)")
        ck(text.count(DISCLAIMER) == 1, "the shared disclaimer is printed ONCE in full")
        ck(f"{PARA}4 {DISCLAIMER}" in text, "...its first copy is marked as a pointer target")
        ck(text.count(f"[= E1 {PARA}4]") == 2, "...and both later copies point at it")
        ck(f"{PARA}3 {REQUIREMENT}" in text and f"[= E1 {PARA}3]" in text,
           "a QUOTED repeat (> markers, re-wrapped) points at the original paragraph")
        ck(text.count("Thanks,") == 3, "a short line ('Thanks,') is never replaced")
        ck(OFFER in text and "https://maps.example.com/?q=51.5,-0.1" in text,
           "unique paragraphs are verbatim, map links included")
        ck("d_broken.eml" in text and "could not be read" in text,
           "a message no reader could open is listed with the reason, not dropped")
        ck(len(auto.get("emails") or []) == 3, "the Emails-tab index is unchanged (3 readable)")

        w2 = Path(td) / "work2"
        w2.mkdir()
        (w2 / ML.EMAIL_BODIES).write_text("stale", encoding="utf-8")
        ML.build_auto(w2, {}, {}, inputs, lambda p: "", emails=[], email_attachments=[])
        ck(not (w2 / ML.EMAIL_BODIES).exists(), "a run with no emails has no bodies file (stale one removed)")
        ck(ML.write_email_bodies(w2, []) is None, "write_email_bodies returns None for nothing to write")

    print()
    if FAILS:
        print(f"EMAIL BODIES TEST: FAIL ({len(FAILS)})")
        return 1
    print("EMAIL BODIES TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
