#!/usr/bin/env python3
"""extract_email.py - landlord / agent offer emails.

PRIMARY PATH (Outlook MCP, agent-driven): the orchestrator dispatches an isolated
extraction sub-agent that calls the connected Outlook search
(`outlook_email_search`) scoped to the broker's chosen Outlook MAIL FOLDER -
pass `folderName` = inputs.emails.outlook_folder (e.g. "Inbox" or a filed folder
like "Normal CEE"; omit to search all folders), `mailboxOwnerEmail` =
inputs.emails.mailbox for a shared/delegated mailbox - plus a client/subject/date
`query` scope, reads the matching offers via read_resource, and writes a
records.json in the SAME record schema the other extractors emit (see
templates/record_schema.json). Each
record's __meta is:
    {"source_file": "<email subject>", "source_type": "email",
     "locator_base": "email <yyyy-mm-dd>", "date": "<iso date>", "prov": {...}}
Commercials from the NEWEST email win in merge.py (the 'date' field drives this).
Attachments the search surfaces are saved and re-routed through the PPTX/PDF/
image extractors.

FALLBACK PATH (this script): parse a folder of saved .msg / .eml files for teams
without the Outlook MCP connected. Requires `extract_msg` for .msg (lazy import;
pip install extract-msg). .eml uses the stdlib. Bodies are returned as raw text
for the orchestrator's offer-parse step; structured field extraction from prose
is an LLM step, not done here. Attachments are reported by FILENAME only (the
'attachments' field is a list of names): this fallback does NOT yet save or
re-route attachment bytes through the PPTX/PDF/image extractors - full
byte-routing is deferred to the Outlook MCP path above.

CLI:
  python extract_email.py <folder> [--out emails.json]
"""
from __future__ import annotations

import argparse
import email
import json
import sys
from email import policy
from pathlib import Path

import html as _html
import re


def _strip_html(raw: str) -> str:
    """Best-effort HTML -> plain text for an HTML-only email body: drop script/style,
    strip tags, unescape entities, collapse whitespace (audit S1-12)."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def _read_eml(p: Path) -> dict:
    msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    body, html_body = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                body += part.get_content()
            elif ct == "text/html" and not html_body:
                html_body = part.get_content()
        # an HTML-only multipart email (no text/plain part) must not silently lose its
        # offer prose - fall back to the stripped HTML (audit S1-12)
        if not body.strip() and html_body:
            body = _strip_html(html_body)
    else:
        raw = msg.get_content()
        body = _strip_html(raw) if msg.get_content_type() == "text/html" else raw
    return {"subject": str(msg.get("subject", "")), "from": str(msg.get("from", "")),
            "date": str(msg.get("date", "")), "body": body, "attachments":
            [part.get_filename() for part in msg.walk() if part.get_filename()]}


def _read_msg(p: Path) -> dict | None:
    try:
        import extract_msg  # type: ignore
    except Exception:
        return None
    m = extract_msg.Message(str(p))
    return {"subject": m.subject or "", "from": m.sender or "",
            "date": str(m.date or ""), "body": m.body or "",
            "attachments": [getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or ""
                            for a in m.attachments]}


def _iso_date(raw: str) -> str:
    """RFC-2822 / arbitrary email date header -> ISO 'yyyy-mm-dd' ('' if unparseable).
    merge.py's newest-email-wins precedence keys on __meta.date; without this the
    documented precedence silently degraded to file iteration order."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        m = __import__("re").search(r"\d{4}-\d{2}-\d{2}", str(raw or ""))
        return m.group(0) if m else ""


def extract(folder: Path) -> list[dict]:
    out = []
    missing_msg = False
    for p in sorted(folder.iterdir()):
        ext = p.suffix.lower()
        try:  # one corrupt email must not lose the whole folder
            if ext == ".eml":
                d = _read_eml(p)
            elif ext == ".msg":
                d = _read_msg(p)
                if d is None:
                    missing_msg = True
                    continue
            else:
                continue
        except Exception as e:
            out.append({"unreadable": True, "error": str(e),
                        "__meta": {"source_file": p.name, "source_type": "email",
                                   "locator_base": p.name}})
            continue
        if not (str(d.get("subject") or "").strip() or str(d.get("date") or "").strip()
                or str(d.get("from") or "").strip()):
            # the stdlib parser is lenient: junk bytes "parse" into a message whose
            # whole content lands in the body with NO headers. A real exported email
            # always has Subject/Date/From - headerless = an explicit unreadable stub
            out.append({"unreadable": True, "error": "no parseable headers or body",
                        "__meta": {"source_file": p.name, "source_type": "email",
                                   "locator_base": p.name}})
            continue
        iso = _iso_date(d.get("date", ""))
        # __meta.date + the documented "email <yyyy-mm-dd>" locator (the docstring's
        # contract): merge precedence and the ledger both key on these
        d["__meta"] = {"source_file": d.get("subject") or p.name, "source_type": "email",
                       "locator_base": f"email {iso}" if iso else (d.get("subject") or p.name),
                       "date": iso}
        out.append(d)
    if missing_msg:
        print("NOTE: .msg files skipped (pip install extract-msg, or use the Outlook MCP path)",
              file=sys.stderr)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out")
    args = ap.parse_args()
    res = extract(Path(args.folder))
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"OK {len(res)} emails -> {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
