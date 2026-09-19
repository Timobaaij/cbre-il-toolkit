#!/usr/bin/env python3
"""email_folder_test.py - an email folder, or a zip of one, is a first-class input.

THE DEFECT. The fallback email path (`extract_email.py`, for teams with no Outlook MCP)
listed an attachment's FILENAME and threw its bytes away, and intake had no zip reader at
all. A brochure that arrived only as an attachment in a .msg folder was therefore invisible
to the whole run, and - this is the part that makes it dangerous rather than merely
incomplete - NO GATE CAUGHT IT. The email body still contributed records, so the .msg
appeared in the Source Ledger, `input-accounting` counted the file as accounted for, and the
scorecard went ALL-PASS over a building that was never in the dashboard.

What is asserted here, all offline, all on synthetic fixtures:
  1. a .zip in the inputs folder is unpacked once into `<name>_unpacked`, and a second pass
     over an unchanged zip is a no-op (mtimes unmoved, status 'current');
  2. a zip member naming a path OUTSIDE the inputs folder is refused (zip-slip) and nothing
     is written there;
  3. an attachment's BYTES land beside the email, under a folder name carrying the email's
     date and subject, and intake then classifies the .pdf as an ordinary brochure;
  4. inline images (a cid: signature logo, and anything under 20 KB) are NOT saved, and are
     recorded as skipped rather than vanishing;
  5. a record citing the attachment carries __meta.from_email and the shipped ledger row's
     locator names the email that carried it;
  6. input-accounting BLOCKS when the attachment folder is deleted between runs, and blocks
     on a legacy inventory that predates attachment extraction.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import extract_email as EM   # noqa: E402
import intake as I           # noqa: E402

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _pdf_bytes(title: str, pad_to: int = 30000) -> bytes:
    """A small but REAL one-page PDF, padded past the 20 KB inline-image floor.

    Padded with a trailing PDF comment rather than junk: the point of the fixture is to be a
    document the size filter must let through, and a file that is only large would not prove
    that the filter passes a genuine brochure.
    """
    content = f"BT /F1 24 Tf 72 700 Td ({title}) Tj ET".encode("latin-1")
    body = b"\n".join([
        b"%PDF-1.4",
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj",
        b"4 0 obj<</Length " + str(len(content)).encode() + b">>stream",
        content,
        b"endstream endobj",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
        b"trailer<</Root 1 0 R/Size 6>>",
    ])
    pad = max(0, pad_to - len(body) - 8)
    return body + b"\n%" + (b"P" * pad) + b"\n%%EOF\n"


# A 68-byte 1x1 PNG. This is the shape of every signature logo and award badge in a broker's
# footer: tiny, and referenced by the HTML body through a Content-ID rather than by name.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


def _eml(subject: str, date_hdr: str, body: str, attachments=()) -> bytes:
    m = EmailMessage()
    m["From"] = "agent@example.com"
    m["To"] = "broker@cbre.com"
    m["Subject"] = subject
    m["Date"] = date_hdr
    m.set_content(body)
    for name, data, subtype, cid in attachments:
        maintype = "application" if subtype == "pdf" else "image"
        if cid:
            m.add_attachment(data, maintype=maintype, subtype=subtype, cid=cid,
                             disposition="inline")
        else:
            m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cbre_emailfolder_"))
    inputs = tmp / "1. Input"
    work = tmp / "2. Work Files"
    inputs.mkdir(parents=True)
    work.mkdir(parents=True)

    brochure = _pdf_bytes("Riverside Park Unit 1")
    offer = _eml("Riverside Park offer", "Mon, 12 May 2025 10:11:00 +0200",
                 "Rent EUR 62 per sq m per year. Brochure attached.",
                 [("Riverside brochure.pdf", brochure, "pdf", None),
                  ("logo.png", _TINY_PNG, "png", "<sig-logo-1>")])
    (inputs / "offer.eml").write_bytes(offer)

    # a zip of TWO emails, the Outlook-export shape
    z2a = _eml("Northgate offer", "Tue, 13 May 2025 09:00:00 +0200", "Northgate, 12,000 sq m.")
    z2b = _eml("Southgate offer", "Wed, 14 May 2025 09:00:00 +0200", "Southgate, 8,000 sq m.")
    zpath = inputs / "broker export.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("Northgate offer.eml", z2a)
        z.writestr("Southgate offer.eml", z2b)

    print("unpack:")
    r1 = I.unpack_archives(inputs)
    ck(len(r1) == 1 and r1[0]["status"] == "unpacked" and r1[0]["members"] == 2,
       f"a zip of two .eml is unpacked once ({r1})")
    unpacked = inputs / "broker export_unpacked"
    ck(unpacked.is_dir() and (unpacked / "Northgate offer.eml").exists(),
       "...into '<zipname>_unpacked' beside the zip, inside the inputs folder")
    before = {p.name: p.stat().st_mtime_ns
              for p in unpacked.iterdir() if p.suffix == ".eml"}
    r2 = I.unpack_archives(inputs)
    ck(len(r2) == 1 and r2[0]["status"] == "current",
       f"a second pass over an UNCHANGED zip reports 'current' ({[x['status'] for x in r2]})")
    after = {p.name: p.stat().st_mtime_ns
             for p in unpacked.iterdir() if p.suffix == ".eml"}
    ck(before == after and before,
       "...and touches nothing: identical mtimes, so the extract cache is not invalidated")

    # zip-slip: a member naming a path outside the inputs folder is refused
    slip = inputs / "hostile.zip"
    with zipfile.ZipFile(slip, "w") as z:
        z.writestr("../../escaped.txt", b"x" * 100)
        z.writestr("fine.txt", b"y" * 100)
    rs = [r for r in I.unpack_archives(inputs) if r["archive"] == "hostile.zip"]
    ck(bool(rs) and rs[0]["skipped_unsafe"] == ["../../escaped.txt"],
       f"a zip-slip member is REFUSED and named ({rs and rs[0].get('skipped_unsafe')})")
    ck(not (tmp.parent / "escaped.txt").exists() and not (tmp / "escaped.txt").exists(),
       "...and nothing was written outside the inputs folder")

    print("attachments:")
    inv = I.discover(inputs, exclude_dir=work)
    att_dirs = [p for p in inputs.iterdir() if p.is_dir() and p.name.endswith("_attachments")]
    ck(len(att_dirs) == 1 and att_dirs[0].name.startswith("2025-05-12_"),
       f"the attachments folder carries the email DATE and subject ({[d.name for d in att_dirs]})")
    ck("Riverside Park offer" in att_dirs[0].name,
       "...so two emails both sending 'brochure.pdf' cannot collide")
    saved = sorted(p.name for p in att_dirs[0].iterdir() if not p.name.startswith("."))
    ck(saved == ["Riverside brochure.pdf"],
       f"the attachment BYTES land on disk, the inline logo does not ({saved})")
    ck((att_dirs[0] / "Riverside brochure.pdf").read_bytes() == brochure,
       "...byte-identical to what was attached")
    ea = inv.get("email_attachments") or []
    inline = [s for e in ea for s in (e.get("skipped_inline") or [])]
    ck(len(inline) == 1 and "logo" in json.dumps(inline).lower(),
       f"the inline signature image is RECORDED as skipped, not silently dropped ({inline})")
    ck(any("20 KB" in str(s.get("why")) or "content-id" in str(s.get("why")) for s in inline),
       "...with the reason stated")

    # THE HARVEST IS IDEMPOTENT TOO, and for the same reason as the unpack: run.py's resume
    # predicate stamps the inputs folder by its NEWEST descendant, so a file rewritten with
    # identical bytes makes intake look stale and every downstream stage recompute forever.
    att_before = {p.name: p.stat().st_mtime_ns for p in att_dirs[0].iterdir()}
    I.discover(inputs, exclude_dir=work)
    att_after = {p.name: p.stat().st_mtime_ns for p in att_dirs[0].iterdir()}
    ck(att_before == att_after and len(att_before) == 2,
       f"a second harvest rewrites NOTHING, sidecar included ({len(att_before)} file(s))")

    pdfs = [f for c in inv["clusters"].values() for f in c.get("pdfs", [])]
    ck(any(f.endswith("Riverside brochure.pdf") for f in pdfs),
       f"intake classifies the saved attachment as an ORDINARY BROCHURE ({pdfs})")
    ck(len(inv["emails"]) == 3,
       f"all three emails are discovered, including the two out of the zip ({inv['emails']})")
    ck(not any(str(u.get("file", "")).endswith(".zip") for u in inv.get("unclassified") or []),
       "a zip is a CONTAINER, not an unclassified input (it can never carry a ledger row)")

    print("provenance:")
    # KEYED ON THE RELATIVE PATH. It used to be the basename, and two emails each attaching
    # "brochure.pdf" then resolved to whichever sidecar the walk read last - a confidently
    # wrong sending email in the shipped ledger. `from_email_for` is the one lookup, and it
    # takes the bare name every extractor actually stamps. (email_attachment_provenance_test
    # is where the collision itself is pinned.)
    idx = EM.from_email_index(inputs)
    fe = EM.from_email_for(idx, "Riverside brochure.pdf")
    ck(isinstance(fe, dict) and set(fe) == {"subject", "date", "file"},
       f"the sidecar gives from_email = subject/date/file ({fe})")
    ck(any(k.endswith("/riverside brochure.pdf") and "2025-05-12" in k for k in idx),
       f"...under a key that is the attachment's path relative to the inputs folder ({list(idx)})")
    ck(bool(fe) and fe["date"] == "2025-05-12" and fe["file"] == "offer.eml"
       and fe["subject"] == "Riverside Park offer",
       "...naming the exact email that carried the bytes")

    # a record citing the attachment, run through merge: __meta.from_email is stamped and the
    # shipped ledger locator names the email as well as the page
    rel_pdf = next(f for f in pdfs if f.endswith("Riverside brochure.pdf"))
    rec = [{"city": "Prague", "country": "CZ", "developer": "CTP", "park": "Riverside Park",
            "region": "Prague", "status": "Existing", "warehouseArea": 12000,
            "areaUnit": "sq m",
            "__meta": {"source_file": Path(rel_pdf).name, "source_type": "pdf",
                       "locator_base": "page 1", "page_no": 0,
                       "prov": {"park": "page 1", "warehouseArea": "page 1"}}}]
    recf = work / "rec.json"
    recf.write_text(json.dumps(rec), encoding="utf-8")
    canon, led = work / "canonical.json", work / "source_ledger.csv"
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(recf),
                        "--source-dir", str(inputs), "--out", str(canon), "--ledger", str(led)],
                       capture_output=True, text=True, errors="replace")
    if p.returncode != 0 or not led.exists():
        ck(False, f"merge.py ran on the attachment record (rc={p.returncode}) "
                  f"{ascii(p.stderr[-400:] or p.stdout[-400:])}")
    else:
        text = led.read_text(encoding="utf-8", errors="replace")
        ck("attachment of email" in text,
           "the ledger LOCATOR names the email (there is no free column for it)")
        ck("Riverside Park offer" in text and "2025-05-12" in text,
           "...with the subject and the date, so the ledger shows the file AND the email")
        ck("Riverside brochure.pdf" in text,
           "...while source_file still cites the ATTACHMENT, which is where the figure is printed")
        hdr = text.splitlines()[0].split(",")
        ck(len(hdr) == 11, f"the ledger still has its eleven fixed columns ({len(hdr)})")

    print("input-accounting:")
    C_ = work / "canonical.json"
    if not C_.exists():
        C_.write_text(json.dumps({"meta": {}, "properties": [{"id": 1, "park": "P"}]}),
                      encoding="utf-8")
    (work / "inventory.json").write_text(json.dumps(inv, ensure_ascii=False), encoding="utf-8")
    # a ledger that accounts for every discovered input, so ONLY the attachment rule can fire
    names = ([Path(f).name for f in pdfs] + [Path(f).name for f in inv["emails"]]
             + [Path(f).name for f in inv["xlsx"]] + [Path(f).name for f in inv["images"]]
             + [str(u.get("file")) for u in inv.get("unclassified") or []])
    rows = ["property_id,record_type,field,value,source_file,source_locator,source_type,"
            "extractor,confidence,conflict_note,verified"]
    rows += [f"1,property,park,P,{n},page 1,pdf,E-pdf,high,," for n in names]
    (work / "source_ledger.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _acc():
        return subprocess.run([sys.executable, str(HELPERS / "gate_runner.py"),
                               "input-accounting", str(C_), "--work", str(work)],
                              capture_output=True, text=True, errors="replace")

    q = _acc()
    ck(q.returncode == 0 and "ALL-PASS" in q.stdout,
       f"a run whose attachments are all present PASSES {ascii(q.stdout[-140:])}")

    # THE CASE THAT USED TO SHIP: the attachment folder is gone, the email's own body records
    # still make the .msg look accounted for, and the scorecard used to go green anyway.
    import shutil
    shutil.rmtree(att_dirs[0])
    q = _acc()
    ck(q.returncode != 0 and "BLOCKED" in q.stdout,
       f"deleting the attachment folder BLOCKS {ascii(q.stdout[-140:])}")
    ck("Riverside brochure.pdf" in q.stdout and "no longer in the inputs folder" in q.stdout,
       "...naming the missing attachment and the reason")

    # a LEGACY inventory: emails discovered, no attachment record at all
    legacy = dict(inv)
    legacy.pop("email_attachments", None)
    legacy.pop("email_attachments_enabled", None)
    (work / "inventory.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    q = _acc()
    ck(q.returncode != 0 and "legacy run" in q.stdout,
       f"a legacy inventory with emails and no attachment record BLOCKS {ascii(q.stdout[-140:])}")

    # the wrapper-skill contract: inputs.emails.source: none means another skill already did
    # this work, so demanding our own copies would block every correct kato-longlist run
    wrapped = dict(inv)
    wrapped["email_attachments_enabled"] = False
    wrapped["email_attachments"] = []
    (work / "inventory.json").write_text(json.dumps(wrapped, ensure_ascii=False), encoding="utf-8")
    q = _acc()
    ck(q.returncode == 0,
       f"'source: none' (the wrapper already extracted them) does NOT block {ascii(q.stdout[-140:])}")

    # ...and intake does not double-read them either
    (work / "project.yaml").write_text(
        "inputs:\n  emails:\n    source: none\n", encoding="utf-8")
    ck(I._emails_source(work) == "none",
       "intake reads inputs.emails.source: none from project.yaml")
    inv2 = I.discover(inputs, exclude_dir=work, email_attachments=False)
    ck(all(not (e.get("saved") or []) for e in inv2.get("email_attachments") or []),
       "...and harvests NOTHING when it is none, so no brochure is written twice")
    ck(inv2.get("email_attachments_enabled") is False,
       "...and says so in the inventory, so the gate knows not to demand the copies")

    os.environ.pop("_", None)
    if FAILS:
        print(f"\nEMAIL FOLDER TEST: FAIL ({len(FAILS)})")
        return 1
    print("\nEMAIL FOLDER TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
