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
without the Outlook MCP connected. .eml uses the stdlib. .msg tries `extract_msg`
first and falls back to helpers/msg_reader.py, a stdlib-only OLE2/CFB reader, so a
.msg folder is a real input in a sandbox with no pip rather than a stack of files
the run names and cannot open. Bodies are returned as raw text for the
orchestrator's offer-parse step; structured field extraction from prose is an LLM
step, not done here.

ATTACHMENTS ARE NOW SAVED AND ROUTED, not merely listed. The old fallback wrote the
attachment FILENAMES into an `attachments` list and threw the bytes away, and the
consequence was the worst kind of loss: silent and self-concealing. A brochure that
arrived only as an attachment in a .msg folder was invisible to the whole run, and no
gate caught it, because the email BODY still contributed records, so `input-accounting`
counted the .msg as accounted for and printed ALL-PASS over a missing building. The
route is deterministic unpacking plus an LLM read of the prose: Python opens the
container and gets the bytes out, the agent reads the offer text. `save_attachments`
writes every real attachment beside its email into
`<yyyy-mm-dd>_<sanitised subject>_attachments/`, so intake's ordinary recursive walk
discovers it on the same run and classifies it exactly as a brochure someone had
dropped in the folder by hand. The date and subject are IN the folder name because two
brokers both send "Brochure.pdf" and a flat attachments folder silently overwrites one
with the other.

INLINE IMAGES ARE EXCLUDED. A broker signature carries five to twenty logos, award
badges and social icons per email, and each one that reaches the folder becomes a
candidate hero photo and a line in the Gaps Report about an image with no consumer.
Two rules, deliberately blunt: an attachment under ATTACH_MIN_BYTES (20 KB) is
dropped, and an attachment that carries a Content-ID but no filename is dropped. The
size rule does the real work (no marketing brochure, floor plan or site photograph is
under 20 KB; every signature logo is), and the Content-ID rule catches the cid: images
an HTML body references by reference rather than by name. Both are recorded in
`skipped_inline` rather than discarded quietly, so a genuine small attachment can be
seen to have been refused and why.

PROVENANCE. Each attachments folder gets a `.from_email.json` sidecar naming the
email that carried the bytes. The leading dot keeps intake's walk out of it (intake
skips dot and underscore paths) while `from_email_index` reads it back, so a record
extracted from the attachment cites `source_file` = the attachment and still carries
`__meta.from_email` = {"subject", "date", "file"}. The Source Ledger's eleven columns
are fixed and there is no free one, so merge.py appends the email to the LOCATOR text:
"page 3 (attachment of email 'Sziget II offer', 2025-05-12)". Both halves of the chain
are then visible in the shipped ledger, which is the point of the ledger.

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


# An attachment smaller than this is a signature logo, an award badge or a social icon,
# not a document. Chosen from real broker mail: marketing PDFs start around 300 KB, the
# thinnest single-page floor plan measured was 74 KB, and no signature asset measured was
# over 12 KB. 20 KB therefore sits in empty space between the two populations rather than
# on top of either. A genuine small attachment is REFUSED here, on purpose, and named in
# `skipped_inline` so the refusal is inspectable rather than a mystery.
ATTACH_MIN_BYTES = 20 * 1024

ATTACH_DIR_SUFFIX = "_attachments"
FROM_EMAIL_SIDECAR = ".from_email.json"

# Windows is the deployment target and its path limit is still 260 characters. An email
# subject routinely runs past 100 characters, and a subject plus an attachment name plus
# the project folder blew that limit on a live Kato run, which aborted the whole stage
# rather than one file. Stems are truncated, extensions never are: truncating the whole
# name cuts ".pdf" off a brochure and leaves a file that exists, is present, and cannot
# be opened by anything.
_SUBJECT_MAXLEN = 48
_STEM_MAXLEN = 60
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]+")


def _strip_html(raw: str) -> str:
    """Best-effort HTML -> plain text for an HTML-only email body: drop script/style,
    strip tags, unescape entities, collapse whitespace (audit S1-12)."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def _sanitise(s: str, maxlen: int = _SUBJECT_MAXLEN) -> str:
    """A folder/file fragment that is legal on Windows and still readable by a human.

    Reply prefixes are kept (an 'RE: ' tells a reader which thread the brochure came
    from), but every character Windows refuses (: * ? " < > | /) collapses to a space.
    The result is stripped of trailing dots and spaces as well, because a Windows
    directory whose name ends in either cannot be created at all and the failure is
    reported as a permission error, which sends the reader hunting in the wrong place.
    """
    t = _UNSAFE.sub(" ", str(s or ""))
    t = re.sub(r"\s+", " ", t).strip(" ._-")
    return t[:maxlen].strip(" ._-")


def _safe_filename(raw: str, fallback: str) -> str:
    """Sanitise an attachment name, truncating the STEM only so the extension survives.

    The extension is taken with a regex rather than os.path.splitext, because splitext
    returns no extension at all for a name like "....pdf" and a brochure that lands
    without its extension is never routed to the PDF extractor: it falls into intake's
    `unclassified` bucket and the run reports a file it could not classify instead of a
    building.
    """
    m = re.search(r"\.([A-Za-z0-9]{1,10})$", raw or "")
    ext = ("." + m.group(1)) if m else ""
    stem = _sanitise(raw[:m.start()] if m else (raw or ""), maxlen=_STEM_MAXLEN)
    return (stem or fallback) + ext


def _unique_path(directory: Path, filename: str) -> Path:
    """Two attachments called Brochure.pdf in ONE email must not overwrite each other.

    Collisions ACROSS emails are handled by the per-email folder name; this is the
    within-one-email case (a broker attaching a unit brochure and a park brochure both
    exported as "Brochure.pdf" from the same CMS), which the folder name cannot separate.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stem, dot, ext = filename.rpartition(".")
    stem, ext = (stem, dot + ext) if dot else (filename, "")
    cand, n = filename, 2
    while (directory / cand).exists():
        cand = f"{stem} ({n}){ext}"
        n += 1
    return directory / cand


def _eml_attachments(msg) -> list[tuple[str, str, bytes]]:
    """[(filename, content_id, bytes)] for every non-body part of a parsed .eml.

    A part counts as an attachment when it names a file, declares
    Content-Disposition: attachment, OR carries a Content-ID. Body parts (text/plain,
    text/html with no disposition and no Content-ID) are excluded here rather than filtered
    later, because a 40 KB HTML body passes the 20 KB size rule and would otherwise land in
    the inputs folder as a .html "brochure" for intake to puzzle over.

    The Content-ID clause is deliberate even though every cid-only part is dropped a moment
    later by the inline rule: a part that never enters this list is never COUNTED either, and
    `declared` is the number input-accounting reconciles against. Filtering the signature
    logos out here would have made a half-failed save arithmetically indistinguishable from a
    clean one, which is the whole failure this work exists to close.
    """
    out: list[tuple[str, str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        fn = part.get_filename()
        disp = (part.get_content_disposition() or "")
        cid = str(part.get("Content-ID") or "").strip()
        if not fn and disp != "attachment" and not cid:
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            data = b""
        out.append((str(fn or ""), cid, bytes(data)))
    return out


def _load_msg_reader():
    """helpers/msg_reader.py, imported by PATH rather than by name.

    A plain `import msg_reader` only works when helpers/ happens to be on sys.path, which is
    true when intake or merge imported us and false when someone runs `python extract_email.py`
    from anywhere else. The whole point of the stdlib reader is that it is always available, so
    resolving it must not depend on how this module was reached.
    """
    import importlib.util
    try:
        import msg_reader as _mr  # type: ignore
        return _mr
    except Exception:
        pass
    here = Path(__file__).resolve().parent / "msg_reader.py"
    if not here.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_cbre_msg_reader", here)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception:
        return None


def _msg_attachments(m) -> list[tuple[str, str, bytes]]:
    """[(filename, content_id, bytes)] from an extract_msg OR msg_reader Message.

    An attachment whose `data` is not bytes is an EMBEDDED MESSAGE (a forwarded offer),
    not a file. It is skipped rather than crashed on: writing `str(<Message object>)` to
    a .msg file produced a 60-byte artefact on a live run that intake then classified as
    an email and extract_msg refused to reopen, which read as a corrupt broker export
    when the broker had sent nothing wrong.
    """
    out: list[tuple[str, str, bytes]] = []
    for a in getattr(m, "attachments", []) or []:
        data = getattr(a, "data", None)
        if not isinstance(data, (bytes, bytearray)) or not data:
            continue
        name = (getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or "")
        # `content_id` is msg_reader's spelling of the same MAPI property (0x3712) that
        # extract_msg calls `cid`. Reading only extract_msg's two spellings would have handed
        # every stdlib-read attachment an empty Content-ID, which quietly disables RULE 1 in
        # save_attachments and puts a broker's signature logos back in the inputs folder as
        # candidate hero photos - on exactly the path that has no extract_msg to fall back on.
        cid = str(getattr(a, "cid", "") or getattr(a, "contentId", "")
                  or getattr(a, "content_id", "") or "")
        out.append((str(name), cid, bytes(data)))
    return out


def save_attachments(email_path: Path, subject: str, iso_date: str,
                     atts: list[tuple[str, str, bytes]]) -> dict:
    """Write an email's real attachments beside it and describe what was written.

    IDEMPOTENT BY CONTENT LENGTH. The spine re-runs constantly (every agentic exit code
    ends in "re-run the SAME command"), so this function runs many times over one folder.
    A target that already exists at the same byte length is left alone, which keeps the
    file's mtime stable. That matters beyond tidiness: run.py's resume guard rewrites
    inventory.json whenever the inputs folder's mtime moves, and an attachment rewritten
    on every pass would have reset the QA window on an untouched corpus, silently
    dropping every carried limitation from the delivered Gaps Report.

    Returns {"dir", "declared", "saved": [...], "skipped_inline": [...], "error"}.
    `declared` is the count BEFORE the inline filter, and it is the number
    `input-accounting` reconciles against, so an extraction that half-failed cannot
    present itself as a clean run with fewer attachments.
    """
    rec: dict = {"email": email_path.name, "subject": subject, "date": iso_date,
                 "declared": len(atts), "saved": [], "skipped_inline": [], "dir": ""}
    if not atts:
        return rec
    stem = _sanitise(subject) or _sanitise(email_path.stem) or "email"
    folder = email_path.parent / f"{iso_date or 'undated'}_{stem}{ATTACH_DIR_SUFFIX}"
    rec["dir"] = folder.name
    for i, (name, cid, data) in enumerate(atts, start=1):
        # RULE 1: a Content-ID with no filename is a cid: image the HTML body references
        # inline. It has no name because nothing was ever meant to open it as a file.
        if cid and not name:
            rec["skipped_inline"].append({"name": f"(cid {cid[:40]})", "bytes": len(data),
                                          "why": "content-id with no filename (inline image)"})
            continue
        # RULE 2: under 20 KB. This is the rule that actually clears the signature block.
        if len(data) < ATTACH_MIN_BYTES:
            rec["skipped_inline"].append({"name": name or f"attachment{i}", "bytes": len(data),
                                          "why": f"under {ATTACH_MIN_BYTES // 1024} KB "
                                                 f"(signature logo / icon, not a document)"})
            continue
        fn = _safe_filename(Path(str(name)).name, fallback=f"attachment{i}")
        existing = folder / fn
        try:
            if existing.exists() and existing.stat().st_size == len(data):
                rec["saved"].append({"file": f"{folder.name}/{existing.name}",
                                     "bytes": len(data), "attachment_name": name})
                continue
            dest = _unique_path(folder, fn)
            dest.write_bytes(data)
        except OSError as e:
            # One unwritable attachment must not lose the other four, and must not be
            # swallowed either: `error` is what makes input-accounting BLOCK.
            rec["error"] = f"{fn}: {e}"
            continue
        rec["saved"].append({"file": f"{folder.name}/{dest.name}", "bytes": len(data),
                             "attachment_name": name})
    if rec["saved"] or rec["skipped_inline"]:
        try:
            (folder).mkdir(parents=True, exist_ok=True)
            payload = {"subject": subject, "date": iso_date, "file": email_path.name,
                       "attachments": [s["file"].split("/", 1)[-1] for s in rec["saved"]],
                       "skipped_inline": rec["skipped_inline"]}
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            side = folder / FROM_EMAIL_SIDECAR
            # Written only when the CONTENT changed. An unconditional write bumps an mtime
            # inside the inputs folder on every harvest, and run.py's resume predicate takes
            # the folder's newest descendant as its currency stamp, so a file rewritten with
            # identical bytes is enough to make a stage look stale and recompute for nothing.
            if not (side.exists() and side.read_text(encoding="utf-8-sig") == text):
                side.write_text(text, encoding="utf-8")
        except OSError as e:
            rec["error"] = f"{FROM_EMAIL_SIDECAR}: {e}"
    return rec


def from_email_index(inputs_dir) -> dict:
    """{attachment path relative to the inputs folder (posix, lowercased):
        {"subject", "date", "file"}}.

    Read from the `.from_email.json` sidecars rather than from any run artefact, so the
    link between a brochure and the email that carried it survives a deleted work dir,
    a resumed run and a hand-run of merge.py.

    KEYED ON THE RELATIVE PATH, NOT THE BASENAME, and that is a bug fix rather than a
    tidy-up. Two brokers both attach "brochure.pdf"; the per-email folder keeps the two
    files apart on disk (it carries the date and the subject), but a basename key collapsed
    them back into one entry and the LAST sidecar the sorted walk happened to read won. The
    result was not a missing attribution, which a reader could notice: it was a confident
    WRONG one. The shipped ledger cited CTP's offer email against Panattoni's brochure, and
    since the whole point of `from_email` is to tell a current offer from a superseded one,
    a wrong email is worse than none. The folder name is already unique, so the path is
    already the identifier; nothing new has to be invented to key on it.

    The sidecar's own stored `attachments` list stays as basenames: the folder holding the
    sidecar IS the rest of the path, so the relative key is reconstructed here from where the
    sidecar sits. That keeps sidecars written by earlier runs readable.
    """
    idx: dict = {}
    root = Path(inputs_dir)
    if not root.is_dir():
        return idx
    try:
        sidecars = sorted(root.rglob(FROM_EMAIL_SIDECAR))
    except OSError:
        return idx
    for side in sidecars:
        try:
            d = json.loads(side.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        fe = {"subject": str(d.get("subject") or ""), "date": str(d.get("date") or ""),
              "file": str(d.get("file") or "")}
        try:
            base = side.parent.relative_to(root).as_posix()
        except ValueError:
            base = ""
        if base in (".", ""):
            base = ""
        for nm in d.get("attachments") or []:
            leaf = Path(str(nm)).name
            idx[(f"{base}/{leaf}" if base else leaf).lower()] = fe
    return idx


def from_email_for(index: dict, source_file) -> dict | None:
    """The email that carried `source_file`, or None when nothing can be said honestly.

    The ONE lookup for the index above, so merge.py and any later consumer read it the same
    way. It has to be a function because the records do not agree with the index about what
    a source is: every extractor stamps `__meta.source_file` as a BARE NAME (extract_pdf.py's
    `_resolve_pdf` says so in as many words), while the index is keyed on the path, which is
    the only thing that distinguishes two emails' "brochure.pdf".

    So: exact relative-path hit first, then a basename search, and a basename that matches
    MORE THAN ONE email is answered with None. That is the honest answer, not a shortfall.
    The alternative - pick one - is what shipped before, and a locator naming the wrong
    broker's email reads as verified provenance while being false. None simply leaves the
    locator as the page citation it already was, which is true.
    """
    if not index or not source_file:
        return None
    s = str(source_file).replace("\\", "/").strip("/").lower()
    hit = index.get(s)
    if hit:
        return hit
    leaf = s.rsplit("/", 1)[-1]
    cands = [v for k, v in index.items() if k.rsplit("/", 1)[-1] == leaf]
    if not cands:
        return None
    # Same basename twice inside ONE email's folder is not an ambiguity: _unique_path already
    # renamed the second copy, and any remaining pair points at the same email anyway.
    distinct = {(c.get("subject"), c.get("date"), c.get("file")) for c in cands}
    return cands[0] if len(distinct) == 1 else None


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
    atts = _eml_attachments(msg)
    return {"subject": str(msg.get("subject", "")), "from": str(msg.get("from", "")),
            "date": str(msg.get("date", "")), "body": body,
            "attachments": [n for n, _c, _d in atts if n],
            "_att_parts": atts}


def _read_msg(p: Path) -> dict | None:
    """Open a .msg with extract_msg if it is installed, else with the stdlib reader.

    TWO READERS, AND THE SECOND ONE IS THE LOAD-BEARING ONE. This used to be `import
    extract_msg` and nothing else, and that package is absent from the sandbox this skill
    actually runs in - no pip, no network, so the import is a permanent ImportError there and
    not a setup step anyone can complete. The failure was quiet in the way that ships: this
    function returned None, the run printed a single NOTE to stderr, and a .msg corpus
    delivered a dashboard with none of its rents, specifications or brochures in it. A .msg
    folder could not be an input at all, which is most of what "a folder of broker emails"
    means on a Windows desktop.

    extract_msg stays FIRST where it exists: it is the better-maintained reader and this
    skill is not trying to win that comparison. helpers/msg_reader.py is a stdlib-only CFB
    reader that gets the same five things out (subject, sender, date, body, attachment
    BYTES), so the fallback path saves brochures exactly like the primary one rather than
    degrading to a body-only read. Only when BOTH refuse the file does this return None, and
    the caller then records it as a fault rather than as a file with no attachments.
    """
    m = None
    try:
        import extract_msg  # type: ignore
        m = extract_msg.Message(str(p))
    except Exception:
        m = None
    if m is None:
        mr = _load_msg_reader()
        if mr is None:
            return None
        try:
            m = mr.Message(str(p))
        except Exception:
            # A corrupt or non-CFB .msg is a READ failure, not a missing reader. Raised so
            # the caller's per-file handler records the real reason against the file name.
            raise
    try:
        atts = _msg_attachments(m)
        return {"subject": m.subject or "", "from": m.sender or "",
                "date": str(m.date or ""), "body": m.body or "",
                # taken from `atts`, not from a second walk of m.attachments: msg_reader
                # rebuilds that list on every property read, and the two walks disagreed
                # about embedded messages (skipped in one, named in the other).
                "attachments": [n for n, _c, _d in atts if n],
                "_att_parts": atts}
    finally:
        # CLOSE THE HANDLE. extract_msg holds the .msg open through an OLE container, and on
        # Windows an open handle is an exclusive lock: intake now opens every email TWICE in a
        # pass (once to harvest attachments, once for the body read) and a leaked handle makes
        # the second open, the dedup hash read and any later tidy-up of the folder fail with
        # WinError 32. That failure reads as a corrupt broker export when nothing is wrong with
        # the file. Not a leak worth deferring: eval suites in this repo already trip over it.
        try:
            m.close()
        except Exception:
            pass


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


def extract(folder: Path, save_attachment_bytes: bool = True) -> list[dict]:
    """Parse every .msg/.eml in `folder` and, unless told not to, save their attachments.

    `save_attachment_bytes=False` exists for ONE caller: a wrapper skill (kato-longlist)
    that already unpacked the export and saved the attachments in its own email step and
    sets `inputs.emails.source: none`. Reading the same attachments twice there would
    write a second copy of every brochure into the inputs folder, and the second copy
    does not merge with the first: it clusters as a separate option and the client sees
    the same building twice on the dashboard.
    """
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
        parts = d.pop("_att_parts", [])
        att_rec = (save_attachments(p, str(d.get("subject") or ""), iso, parts)
                   if save_attachment_bytes else
                   {"email": p.name, "subject": d.get("subject") or "", "date": iso,
                    "declared": 0, "saved": [], "skipped_inline": [], "dir": "",
                    "skipped_reason": "attachments handled by the calling skill "
                                      "(inputs.emails.source: none)"})
        d["attachments_saved"] = att_rec.get("saved") or []
        d["attachments_skipped_inline"] = att_rec.get("skipped_inline") or []
        # __meta.date + the documented "email <yyyy-mm-dd>" locator (the docstring's
        # contract): merge precedence and the ledger both key on these
        d["__meta"] = {"source_file": d.get("subject") or p.name, "source_type": "email",
                       "locator_base": f"email {iso}" if iso else (d.get("subject") or p.name),
                       "date": iso, "attachments_dir": att_rec.get("dir") or ""}
        if att_rec.get("error"):
            d["__meta"]["attachments_error"] = att_rec["error"]
        out.append(d)
    if missing_msg:
        print("NOTE: .msg file(s) skipped - no reader could open them. helpers/msg_reader.py "
              "is the stdlib fallback and needs no install, so check it is present and intact.",
              file=sys.stderr)
    return out


def harvest_folder(folder: Path, save_attachment_bytes: bool = True) -> list[dict]:
    """Save every email's attachments under `folder` (recursively) and report per email.

    Called by intake.py BEFORE it walks the inputs folder, so the attachments are on
    disk in time to be discovered, classified and routed on the SAME run. Doing it any
    later would mean a brochure arriving as an attachment needed two runs to appear, and
    a two-run requirement that nothing prints is indistinguishable from a lost file.

    Bodies are NOT parsed here and no prose is read: that is the LLM's step. This walks
    the containers only.
    """
    recs: list[dict] = []
    if not Path(folder).is_dir():
        return recs
    for p in sorted(Path(folder).rglob("*")):
        if p.suffix.lower() not in (".msg", ".eml") or not p.is_file():
            continue
        rel = p.relative_to(folder).as_posix()
        if any(part.startswith((".", "_")) for part in Path(rel).parts):
            continue  # intake skips these paths, so harvesting them would orphan the bytes
        try:
            d = _read_eml(p) if p.suffix.lower() == ".eml" else _read_msg(p)
        except Exception as e:
            recs.append({"email": rel, "declared": None, "saved": [], "skipped_inline": [],
                         "error": f"unreadable: {e}"})
            continue
        if d is None:
            recs.append({"email": rel, "declared": None, "saved": [], "skipped_inline": [],
                         "error": "neither extract_msg nor the stdlib reader "
                                  "(helpers/msg_reader.py) could open this .msg, so any "
                                  "brochure attached to it is NOT in the run. The stdlib "
                                  "reader needs no install, so this is a missing or damaged "
                                  "helpers/msg_reader.py, not a missing package"})
            continue
        parts = d.get("_att_parts") or []
        if not save_attachment_bytes:
            recs.append({"email": rel, "declared": len(parts), "saved": [],
                         "skipped_inline": [], "dir": "",
                         "skipped_reason": "attachments handled by the calling skill "
                                           "(inputs.emails.source: none)"})
            continue
        r = save_attachments(p, str(d.get("subject") or ""), _iso_date(d.get("date", "")), parts)
        r["email"] = rel
        # store the saved paths RELATIVE TO THE INPUTS FOLDER, which is the frame every
        # other inventory path uses and the frame input-accounting re-checks them in
        base = Path(rel).parent.as_posix()
        for s in r["saved"]:
            s["file"] = f"{base}/{s['file']}" if base and base != "." else s["file"]
        recs.append(r)
    return recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out")
    ap.add_argument("--no-attachments", action="store_true",
                    help="parse bodies only; do NOT save attachment bytes. For a wrapper "
                         "skill that already unpacked the export itself (inputs.emails."
                         "source: none) - saving them twice ships the same building twice.")
    args = ap.parse_args()
    res = extract(Path(args.folder), save_attachment_bytes=not args.no_attachments)
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.dumps(res, ensure_ascii=False, indent=2)
    n_att = sum(len(d.get("attachments_saved") or []) for d in res)
    n_inl = sum(len(d.get("attachments_skipped_inline") or []) for d in res)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"OK {len(res)} emails -> {args.out} "
              f"({n_att} attachment(s) saved, {n_inl} inline image(s) skipped)")
    else:
        print(payload)


if __name__ == "__main__":
    main()
