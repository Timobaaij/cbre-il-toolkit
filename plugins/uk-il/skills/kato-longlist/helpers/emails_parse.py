#!/usr/bin/env python3
"""
Stage 2 - parse the broker email export (DETERMINISTIC PARSING ONLY).

Unzips Emails.zip (or reads a folder) of Outlook .msg files and turns each into clean,
model-readable text + saved attachments. It does NOT try to match rents to properties or
guess anything - that judgement is done by the model/subagent in Stage 3, because deciding
which broker quote (if any) belongs to which longlisted building is a fuzzy call, not a regex.

Outputs (under work_dir/emails):
  emails.json      [{idx, file, subject, from, date, body, body_top, attachments:[...]}]
  emails.md        the same, concatenated as readable markdown for the model to scan
  attachments/NN/  saved attachments (image attachments resized to <=max_px)
"""
import os, sys, re, json, glob, zipfile, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, write_json, sanitize, ensure_image_limits

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

def parse_msg(path, att_dir, max_px):
    import extract_msg
    m = extract_msg.Message(path)
    subj = re.sub(r"\s+", " ", (m.subject or "")).strip()
    sender = re.sub(r"\s+", " ", (m.sender or "")).strip()
    date = str(m.date or "")
    body = clean(m.body or "")
    atts = []
    for i, a in enumerate(m.attachments or []):
        fn = sanitize(a.longFilename or a.shortFilename or f"att{i}") or f"att{i}"
        try:
            data = a.data
        except Exception:
            data = None
        if not data:
            continue
        os.makedirs(att_dir, exist_ok=True)
        dest = os.path.join(att_dir, fn)
        with open(dest, "wb") as f:
            f.write(data)
        if os.path.splitext(fn)[1].lower() in IMG_EXT:
            ensure_image_limits(dest, max_px)
        atts.append(fn)
    m.close()
    return {"subject": subj, "from": sender, "date": date, "body": body,
            "body_top": top_only(body), "attachments": atts}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]; max_px = cfg["image_max_px"]
    out = os.path.join(work, "emails")
    os.makedirs(out, exist_ok=True)

    src = os.path.join(work, cfg["emails_zip"])
    if src.lower().endswith(".zip") and os.path.exists(src):
        with zipfile.ZipFile(src) as z:
            z.extractall(os.path.join(out, "source"))
        msgs = glob.glob(os.path.join(out, "source", "**", "*.msg"), recursive=True)
    elif os.path.isdir(src):
        msgs = glob.glob(os.path.join(src, "**", "*.msg"), recursive=True)
    else:
        msgs = glob.glob(os.path.join(work, "**", "*.msg"), recursive=True)
    msgs = sorted(set(msgs))
    print(f"Parsing {len(msgs)} .msg files ...", flush=True)

    emails, md = [], ["# Broker emails (parsed)\n"]
    for i, f in enumerate(msgs, 1):
        att_dir = os.path.join(out, "attachments", f"{i:02d}")
        try:
            e = parse_msg(f, att_dir, max_px)
        except Exception as ex:
            emails.append({"idx": i, "file": os.path.basename(f), "error": str(ex)}); continue
        e["idx"] = i; e["file"] = os.path.basename(f)
        emails.append(e)
        md.append(f"\n\n## [{i:02d}] {e['subject']}\n**From:** {e['from']}  **Date:** {e['date']}  "
                  f"**Attachments:** {', '.join(e['attachments']) or 'none'}\n\n{e['body_top']}\n")
    write_json(os.path.join(out, "emails.json"), {"count": len(emails), "emails": emails})
    with open(os.path.join(out, "emails.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print(f"DONE. parsed={len(emails)} -> {out}\\emails.json (+ emails.md for the model)", flush=True)

if __name__ == "__main__":
    main()
