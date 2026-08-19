#!/usr/bin/env python3
"""
Stage 2 - parse the broker email export (DETERMINISTIC PARSING ONLY).

Reads the broker export (a zip of Outlook .msg files, or a folder of them) and turns each message into
clean, model-readable text plus its saved attachments. It does NOT try to match rents to properties or
guess anything - that judgement is done by the model/subagent in Stage 3/4, because deciding which
broker quote (if any) belongs to which longlisted building is a fuzzy call, not a regex.

NO THIRD-PARTY DEPENDENCY. Parsing is done by msg_reader.py (this skill, standard library only), so
stage 2 works in the Claude Cowork sandbox, which has no pip and no network. It used to
`import extract_msg` and fail there - silently, because the import sat inside the per-file try/except:
every message was recorded as an error while this script still printed "DONE. parsed=N" and exited 0,
so a whole broker export could vanish from a run without anyone noticing. Now the counts are honest and
a total failure is loud.

Outputs (under work_dir/emails):
  emails.json      [{idx, file, subject, from, to, cc, date, body, body_top, attachments:[...]}]
  emails.md        the same, concatenated as readable markdown for the model to scan
  attachments/NN/  saved attachments (images resized if PIL is available)
  attachments/NN/inline/   signature logos and other inline images, kept apart so the real
                           documents in NN/ are obvious at a glance
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, write_json, sanitize, ensure_image_limits
import msg_reader

IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp")
# marks where a reply/quoted-requirement chain starts - everything after is boilerplate noise
REPLY_MARKERS = re.compile(
    r"(^\s*From:\s|^\s*Sent:\s|^\s*On .*wrote:\s*$|Looking for 30,000 to 50,000|"
    r"Please send all options|-{6,}|_{6,}|\bStatus:\s*Longlist\b)", re.I | re.M)


def clean(body):
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def top_only(body):
    """The new content above the first reply/quoted-requirement marker."""
    m = REPLY_MARKERS.search(body)
    return body[:m.start()].strip() if m else body


def safe_filename(raw, mimetype=None, fallback="attachment", maxlen=80):
    """A filename that is safe on Windows AND still opens by double-click.

    Truncation happens on the STEM ONLY. Truncating the whole name would cut ".pdf" off any brochure
    with a long name and leave a file Windows cannot open - the attachment would be extracted, present,
    and useless. Length matters because these names come from email subjects and the full path still
    dies at 260 characters on Windows.
    """
    # The extension is taken with a regex rather than os.path.splitext, and cleaned by hand rather than
    # with sanitize(). Two traps sit here, both of which produce a file that exists and cannot be
    # opened: sanitize() strips leading dots, which turns "Brochure.pdf" into "Brochurepdf"; and
    # splitext returns no extension at all for a name like "....pdf".
    m = re.search(r"\.([A-Za-z0-9]{1,10})$", raw or "")
    ext = m.group(1) if m else ""
    stem = raw[:m.start()] if m else (raw or "")
    if not ext and mimetype and "/" in mimetype:
        ext = re.sub(r"[^A-Za-z0-9]", "", mimetype.split("/")[-1].split(";")[0])[:6]
    ext = f".{ext}" if ext else ""
    stem = sanitize(stem, maxlen=max(8, maxlen - len(ext))) or fallback
    return stem + ext


def unique_path(directory, filename):
    """Two brochures called Brochure.pdf in one email must not overwrite each other."""
    os.makedirs(directory, exist_ok=True)
    stem, ext = os.path.splitext(filename)
    candidate, n = filename, 2
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return os.path.join(directory, candidate)


def save_attachments(msg, att_dir, max_px, depth=0, prefix=""):
    """Write every attachment to disk and describe it.

    Inline images (a content-id, no real filename, or an image referenced by the HTML body) are the
    broker's signature logos. They are kept, because occasionally a site plan arrives inline, but they
    go in an `inline/` subfolder so a human opening NN/ sees brochures rather than 20 logos.

    An attachment that IS an email is recursed into: its text is returned for appending to the parent
    body and its own attachments are saved alongside. Broker rents are regularly one reply deep, so
    stopping at the outer message loses them.
    """
    saved, nested_text = [], []
    for i, a in enumerate(msg.attachments):
        if a.embedded_message is not None and depth < 4:
            sub = a.embedded_message
            sub_saved, sub_text = save_attachments(sub, att_dir, max_px, depth + 1,
                                                   prefix=f"{prefix}embedded-{i + 1}-")
            saved.extend(sub_saved)
            header = (f"\n\n----- attached email: {sub.subject or '(no subject)'} "
                      f"| from {sub.sender or 'unknown'} | {sub.date or 'no date'} -----\n")
            nested_text.append(header + clean(sub.body or "") + "\n" + "\n".join(sub_text))
            continue

        data = a.data
        if not isinstance(data, (bytes, bytearray)) or not data:
            continue
        raw_name = a.longFilename or a.shortFilename or f"attachment{i + 1}"
        name = safe_filename(prefix + os.path.basename(str(raw_name)), a.mimetype,
                             fallback=f"attachment{i + 1}")

        is_inline = bool(a.content_id) and os.path.splitext(name)[1].lower() in IMG_EXT
        target_dir = os.path.join(att_dir, "inline") if is_inline else att_dir
        dest = unique_path(target_dir, name)
        with open(dest, "wb") as fh:
            fh.write(data)

        if os.path.splitext(dest)[1].lower() in IMG_EXT:
            try:
                ensure_image_limits(dest, max_px)
            except ImportError:
                pass          # no PIL in this sandbox: keep the original bytes rather than failing
            except Exception:
                pass          # a corrupt image is still worth keeping as-is
        saved.append({"file": os.path.relpath(dest, att_dir).replace("\\", "/"),
                      "bytes": len(data), "mime": a.mimetype or None, "inline": is_inline})
    return saved, nested_text


def parse_one(path, att_dir, max_px):
    m = msg_reader.Message(path)
    try:
        subj = re.sub(r"\s+", " ", (m.subject or "")).strip()
        sender = re.sub(r"\s+", " ", (m.sender or "")).strip()
        date = m.date.isoformat() if m.date else ""
        body = clean(m.body or "")
        atts, nested = save_attachments(m, att_dir, max_px)
        if nested:
            body = (body + "\n" + "\n".join(nested)).strip()
        return {"subject": subj, "from": sender, "to": (m.to or "").strip(),
                "cc": (m.cc or "").strip(), "date": date, "body": body,
                "body_top": top_only(body), "attachments": atts}
    finally:
        m.close()


def find_source(work, configured):
    """Locate the export, and say plainly which file was used.

    WHY THIS IS NOT JUST `work/<emails_zip>`: a colleague's export is called whatever Outlook or their
    own habit named it - mail.zip, Emails (1).zip, broker emails.zip. When the configured name did not
    match, this used to fall back to globbing for loose .msg files, find none inside the unopened zip,
    print "Parsing 0 .msg files ... DONE. parsed=0" and exit 0. The emails were simply absent from the
    run and nothing said so. So: try the configured name, then any zip that actually contains .msg
    files, then loose .msg files - and always report the choice.
    """
    named = os.path.join(work, configured or "")
    if configured and os.path.isfile(named) and named.lower().endswith(".zip"):
        return named, f"configured emails_zip: {configured}"
    if configured and os.path.isdir(named):
        return named, f"configured emails_zip (folder): {configured}"

    candidates = []
    for z in sorted(glob.glob(os.path.join(work, "*.zip"))):
        try:
            with zipfile.ZipFile(z) as zf:
                n = sum(1 for e in zf.namelist() if e.lower().endswith(".msg"))
            if n:
                candidates.append((n, z))
        except zipfile.BadZipFile:
            continue
    if candidates:
        candidates.sort(reverse=True)
        n, z = candidates[0]
        why = f"found {os.path.basename(z)} ({n} .msg inside)"
        if configured:
            why += f" - NOTE: run.yaml says emails_zip: {configured}, which is not here"
        return z, why

    loose = glob.glob(os.path.join(work, "**", "*.msg"), recursive=True)
    if loose:
        return work, f"{len(loose)} loose .msg file(s) under the working directory"
    return None, "no zip containing .msg files and no loose .msg files found"


def collect_msgs(source, staging):
    """.msg paths to parse. A zip is extracted into `staging` (a temp dir outside the working
    directory) with short, sanitised names: broker subjects run to 116 characters and the raw
    extractall used to blow past the Windows 260-character path limit and abort the whole stage. The
    staging copy is deleted afterwards, so the working directory never keeps a second copy of a
    55 MB export."""
    if os.path.isfile(source) and source.lower().endswith(".zip"):
        out = []
        with zipfile.ZipFile(source) as z:
            for i, entry in enumerate(e for e in z.namelist() if e.lower().endswith(".msg")):
                short = sanitize(os.path.basename(entry), maxlen=60) or f"message{i + 1}.msg"
                if not short.lower().endswith(".msg"):
                    short += ".msg"
                dest = unique_path(staging, short)
                with z.open(entry) as src, open(dest, "wb") as fh:
                    shutil.copyfileobj(src, fh)
                out.append(dest)
        return sorted(out)
    return sorted(glob.glob(os.path.join(source, "**", "*.msg"), recursive=True))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--keep-staging", action="store_true",
                    help="keep the extracted .msg copies (debugging only; they are duplicates)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    max_px = cfg["image_max_px"]
    out = os.path.join(work, "emails")
    os.makedirs(out, exist_ok=True)

    source, why = find_source(work, cfg.get("emails_zip"))
    print(f"Email source: {why}", flush=True)
    if not source:
        print("\n  NOTHING TO PARSE. No broker emails were found, so no rent or spec can come from "
              "them.\n  Put the export (a zip of Outlook .msg files) in the working directory, or set "
              "emails_zip in run.yaml to its exact filename, and re-run.\n  The pipeline can continue "
              "without it: stage 3 needs only properties/, and the Kato in-app threads carry most "
              "rents. Record the gap in the Gaps Report.", flush=True)
        write_json(os.path.join(out, "emails.json"), {"count": 0, "parsed": 0, "failed": 0,
                                                      "source": None, "emails": []})
        with open(os.path.join(out, "emails.md"), "w", encoding="utf-8") as fh:
            fh.write("# Broker emails\n\nNo broker email export was found for this run.\n")
        return 0

    staging = tempfile.mkdtemp(prefix="kato_msg_")
    try:
        msgs = collect_msgs(source, staging)
        print(f"Parsing {len(msgs)} .msg files ...", flush=True)

        emails, md, failures = [], ["# Broker emails (parsed)\n"], []
        for i, f in enumerate(msgs, 1):
            att_dir = os.path.join(out, "attachments", f"{i:02d}")
            try:
                e = parse_one(f, att_dir, max_px)
            except Exception as ex:
                failures.append((os.path.basename(f), f"{type(ex).__name__}: {ex}"))
                emails.append({"idx": i, "file": os.path.basename(f), "error": str(ex)})
                continue
            e["idx"] = i
            e["file"] = os.path.basename(f)
            emails.append(e)
            att_desc = ", ".join(f"{a['file']} ({a['bytes'] // 1024} KB)"
                                 for a in e["attachments"] if not a["inline"]) or "none"
            n_inline = sum(1 for a in e["attachments"] if a["inline"])
            md.append(f"\n\n## [{i:02d}] {e['subject']}\n"
                      f"**From:** {e['from']}  **Date:** {e['date']}\n"
                      f"**Attachments:** {att_desc}"
                      + (f"  _(+{n_inline} inline image(s) in attachments/{i:02d}/inline/)_" if n_inline else "")
                      + f"\n\n{e['body_top']}\n")

        parsed = sum(1 for e in emails if "error" not in e)
        n_att = sum(len(e.get("attachments", [])) for e in emails)
        att_bytes = sum(a["bytes"] for e in emails for a in e.get("attachments", []))

        write_json(os.path.join(out, "emails.json"),
                   {"count": len(emails), "parsed": parsed, "failed": len(failures),
                    "source": os.path.basename(source), "emails": emails})
        with open(os.path.join(out, "emails.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(md))

        print(f"DONE. parsed={parsed}/{len(msgs)}  failed={len(failures)}  "
              f"attachments={n_att} ({att_bytes / 1048576:.1f} MB)", flush=True)
        print(f"  text -> {os.path.join(out, 'emails.md')}", flush=True)
        print(f"  data -> {os.path.join(out, 'emails.json')}", flush=True)
        if n_att:
            print(f"  files-> {os.path.join(out, 'attachments')}", flush=True)

        if failures:
            print(f"\n  {len(failures)} FILE(S) FAILED TO PARSE - their content is NOT in emails.md, "
                  f"so any rent quoted only there is missing. Record this in the Gaps Report:", flush=True)
            for name, err in failures[:20]:
                print(f"    - {name}: {err}", flush=True)
        if msgs and parsed == 0:
            print("\n  STAGE 2 FAILED: not one message could be parsed, so there is NO email content "
                  "for stage 4.\n  Continue with stage 3 (it needs only properties/), take rents from "
                  "the Kato in-app threads, and say plainly in the Gaps Report that the broker export "
                  "could not be read.", flush=True)
            return 1
        return 0
    finally:
        if args.keep_staging:
            print(f"  staging kept: {staging}", flush=True)
        else:
            shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
