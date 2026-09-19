#!/usr/bin/env python3
"""email_attachment_provenance_test.py - the three follow-ups to the email-folder input.

THREE DEFECTS, all of them the quiet kind: the run keeps going and the output looks finished.

  1. A .msg could only be opened through `extract_msg`, a pip package that is not in the
     sandbox this skill runs in and cannot be installed there (no pip, no network). The .msg
     path therefore returned None, printed one NOTE to stderr, and delivered a dashboard with
     none of that corpus's rents, specifications or brochures. Asserted here against a .msg
     built byte by byte in the test, with `extract_msg` FORCED unavailable, so the assertion
     is about the stdlib reader and nothing else.

  2. `from_email_index` was keyed on the attachment BASENAME. Two brokers both attach
     "brochure.pdf"; the per-email folder keeps the files apart on disk, but the basename key
     collapsed them and the last sidecar read won. That is not a missing attribution, it is a
     confidently wrong one printed in the shipped Source Ledger - and since from_email exists
     to tell a live offer from a superseded one, wrong is worse than absent.

  3. `skipped_inline` (attachments refused as signature logos) was recorded in inventory.json
     and surfaced nowhere a human reads, so a genuinely thin floor plan was dropped in
     silence.
"""
from __future__ import annotations
import json
import struct
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

FAILS: list = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _pdf_bytes(title: str, pad_to: int = 30000) -> bytes:
    """A real one-page PDF padded past the 20 KB inline-image floor, so the size rule must
    let it through rather than the test proving only that big files survive."""
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
    return body + b"\n%" + (b"P" * max(0, pad_to - len(body) - 8)) + b"\n%%EOF\n"


_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


# --------------------------------------------------------------- a .msg, built here
#
# WHY BUILD ONE. A .msg fixture cannot be committed as a binary blob and cannot be produced by
# the stdlib, so the choice was between writing the container and not testing the path that
# this whole item exists to fix. The container is written: ~70 lines of OLE2/CFB, which is a
# fixed, published layout and not a guess.
#
# The mini-stream is sidestepped on purpose by declaring a mini-sector CUTOFF of 1, so every
# stream lives in ordinary 512-byte sectors. Real Outlook writes small streams into the mini
# FAT and msg_reader reads both; exercising the plain path keeps the FIXTURE simple while the
# thing under test (the MAPI property lookups and the attachment streams) is identical.

_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
_FATSECT = 0xFFFFFFFD
_SEC = 512


def _dir_entry(name: str, kind: int, left=_FREESECT, right=_FREESECT, child=_FREESECT,
               start=_ENDOFCHAIN, size=0) -> bytes:
    rec = bytearray(128)
    nb = name.encode("utf-16-le") + b"\x00\x00"
    rec[0:len(nb)] = nb
    struct.pack_into("<H", rec, 0x40, len(nb))
    rec[0x42] = kind
    rec[0x43] = 1                                    # colour flag: black
    struct.pack_into("<III", rec, 0x44, left, right, child)
    struct.pack_into("<I", rec, 0x74, start)
    struct.pack_into("<Q", rec, 0x78, size)
    return bytes(rec)


def _build_msg(subject: str, body: str, date_hdr: str, attachments) -> bytes:
    """A minimal but genuine .msg. `attachments` = [(long_filename, content_id, bytes)]."""
    # every stream this file will hold, as (directory name, payload)
    streams: list[tuple[str, bytes]] = [
        ("__substg1.0_0037001F", subject.encode("utf-16-le")),          # PR_SUBJECT
        ("__substg1.0_1000001F", body.encode("utf-16-le")),             # PR_BODY
        ("__substg1.0_007D001F", f"Date: {date_hdr}\r\n".encode("utf-16-le")),
        ("__substg1.0_0C1A001F", "Agent Example".encode("utf-16-le")),  # PR_SENDER_NAME
    ]
    n_root_streams = len(streams)
    attach_children: list[list[int]] = []
    for name, cid, data in attachments:
        kids = []
        if name:
            kids.append(len(streams))
            streams.append(("__substg1.0_3707001F", name.encode("utf-16-le")))
        if cid:
            kids.append(len(streams))
            streams.append(("__substg1.0_3712001F", cid.encode("utf-16-le")))
        kids.append(len(streams))
        streams.append(("__substg1.0_37010102", data))                  # PR_ATTACH_DATA_BIN
        attach_children.append(kids)

    # sector 0 = FAT, sector 1..n = directory, then one chain per stream
    dir_entries: list[bytes] = []
    payload = bytearray()
    starts: list[int] = []
    sizes: list[int] = []
    # directory length is known only once the entry count is: root + streams + one storage
    # per attachment. Two passes would be tidier; the count is arithmetic, so compute it.
    n_entries = 1 + len(streams) + len(attachments)
    dir_sectors = max(1, -(-n_entries * 128 // _SEC))
    next_sector = 1 + dir_sectors
    for _nm, data in streams:
        n = max(1, -(-len(data) // _SEC))
        starts.append(next_sector if data else _ENDOFCHAIN)
        sizes.append(len(data))
        payload += data + b"\x00" * (n * _SEC - len(data))
        next_sector += n

    # directory: entry 0 is the root, then the root's own streams, then each attachment
    # storage, then that storage's streams. Siblings are chained through `right`, which is
    # all msg_reader.children() needs (it walks child, then left and right, unordered).
    first_child = 1
    root_kids = list(range(1, 1 + n_root_streams))
    attach_idx = [1 + len(streams) + i for i in range(len(attachments))]
    root_chain = root_kids + attach_idx
    entries: list[bytes | None] = [None] * n_entries

    def _right_of(chain, i):
        return chain[i + 1] if i + 1 < len(chain) else _FREESECT

    entries[0] = _dir_entry("Root Entry", 5, child=(first_child if root_chain else _FREESECT))
    for i, idx in enumerate(root_kids):
        entries[idx] = _dir_entry(streams[idx - 1][0], 2, right=_right_of(root_chain, i),
                                  start=starts[idx - 1], size=sizes[idx - 1])
    for a, idx in enumerate(attach_idx):
        kids = attach_children[a]
        entries[idx] = _dir_entry(f"__attach_version1.0_#{a:08X}", 1,
                                  right=_right_of(root_chain, len(root_kids) + a),
                                  child=(kids[0] + 1) if kids else _FREESECT)
        for j, k in enumerate(kids):
            nxt = (kids[j + 1] + 1) if j + 1 < len(kids) else _FREESECT
            entries[k + 1] = _dir_entry(streams[k][0], 2, right=nxt,
                                        start=starts[k], size=sizes[k])
    dir_entries = [e if e is not None else _dir_entry("", 0) for e in entries]
    dir_blob = b"".join(dir_entries)
    dir_blob += b"\xff" * (dir_sectors * _SEC - len(dir_blob))

    total_sectors = next_sector
    fat = [_FREESECT] * (_SEC // 4)
    fat[0] = _FATSECT
    for s in range(1, 1 + dir_sectors):
        fat[s] = s + 1 if s + 1 < 1 + dir_sectors else _ENDOFCHAIN
    for i, _d in enumerate(streams):
        if starts[i] == _ENDOFCHAIN:
            continue
        n = max(1, -(-sizes[i] // _SEC))
        for k in range(n):
            s = starts[i] + k
            fat[s] = (s + 1) if k + 1 < n else _ENDOFCHAIN
    assert total_sectors <= len(fat), "fixture outgrew a single FAT sector"

    hdr = bytearray(_SEC)
    hdr[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", hdr, 0x18, 0x003E, 0x0003)      # minor / major version
    struct.pack_into("<H", hdr, 0x1C, 0xFFFE)               # little-endian
    struct.pack_into("<HH", hdr, 0x1E, 9, 6)                # 512-byte / 64-byte sectors
    struct.pack_into("<I", hdr, 0x2C, 1)                    # one FAT sector
    struct.pack_into("<I", hdr, 0x30, 1)                    # first directory sector
    struct.pack_into("<I", hdr, 0x38, 1)                    # mini cutoff: nothing is mini
    struct.pack_into("<I", hdr, 0x3C, _ENDOFCHAIN)          # no mini FAT
    struct.pack_into("<I", hdr, 0x40, 0)
    struct.pack_into("<I", hdr, 0x44, _ENDOFCHAIN)          # no DIFAT chain
    struct.pack_into("<I", hdr, 0x48, 0)
    struct.pack_into("<I", hdr, 0x4C, 0)                    # DIFAT[0] -> sector 0
    for i in range(1, 109):
        struct.pack_into("<I", hdr, 0x4C + 4 * i, _FREESECT)
    fat_blob = b"".join(struct.pack("<I", v) for v in fat)
    return bytes(hdr) + fat_blob + dir_blob + bytes(payload)


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
    # FORCE the sandbox condition before extract_email is imported: a sys.modules entry of
    # None makes `import extract_msg` raise ImportError even on a machine that has it, so
    # what follows tests the stdlib reader on every machine rather than only on the one that
    # happens to lack the package.
    sys.modules["extract_msg"] = None       # type: ignore[assignment]
    import extract_email as EM              # noqa: E402
    import intake as I                      # noqa: E402
    import deliver as D                     # noqa: E402

    tmp = Path(tempfile.mkdtemp(prefix="cbre_emailprov_"))
    inputs = tmp / "1. Input"
    work = tmp / "2. Work Files"
    inputs.mkdir(parents=True)
    work.mkdir(parents=True)

    print(".msg without extract_msg:")
    ck(EM._load_msg_reader() is not None,
       "helpers/msg_reader.py loads by path, whatever put extract_email on sys.path")
    msg_pdf = _pdf_bytes("Danube Logistics Park")
    msg_bytes = _build_msg(
        "Danube Park offer", "Rent EUR 58 per sq m per year. Brochure attached.",
        "Thu, 15 May 2025 08:30:00 +0200",
        [("Danube brochure.pdf", "", msg_pdf),
         ("", "<sig-logo-7>", _TINY_PNG)])
    (inputs / "danube.msg").write_bytes(msg_bytes)

    d = EM._read_msg(inputs / "danube.msg")
    ck(isinstance(d, dict) and d.get("subject") == "Danube Park offer",
       f"a .msg is READ with no extract_msg installed (subject={d and d.get('subject')!r})")
    ck(bool(d) and "58" in str(d.get("body")),
       "...its body text comes out, so the offer prose reaches the model")
    ck(bool(d) and EM._iso_date(str(d.get("date"))) == "2025-05-15",
       f"...and its date parses, which is what newest-email-wins keys on "
       f"({d and EM._iso_date(str(d.get('date')))})")
    parts = (d or {}).get("_att_parts") or []
    ck(len(parts) == 2 and any(n == "Danube brochure.pdf" for n, _c, _b in parts),
       f"...attachment BYTES come out of the stdlib path, not just names ({[p[0] for p in parts]})")
    ck(any(b == msg_pdf for _n, _c, b in parts),
       "...byte-identical to what was attached")
    ck(any(c and not n for n, c, _b in parts),
       "...and the Content-ID survives, so the inline rule can still refuse a signature logo")

    print("two emails, one filename:")
    broch_a = _pdf_bytes("Northgate Unit 3")
    broch_b = _pdf_bytes("Southgate Unit 7", pad_to=34000)
    (inputs / "north.eml").write_bytes(
        _eml("Northgate offer", "Tue, 13 May 2025 09:00:00 +0200",
             "Northgate, 12,000 sq m.", [("brochure.pdf", broch_a, "pdf", None)]))
    (inputs / "south.eml").write_bytes(
        _eml("Southgate offer", "Wed, 14 May 2025 09:00:00 +0200",
             "Southgate, 8,000 sq m.", [("brochure.pdf", broch_b, "pdf", None)]))

    inv = I.discover(inputs, exclude_dir=work)
    (work / "inventory.json").write_text(json.dumps(inv, ensure_ascii=False), encoding="utf-8")
    idx = EM.from_email_index(inputs)
    broch_keys = sorted(k for k in idx if k.endswith("/brochure.pdf"))
    ck(len(broch_keys) == 2,
       f"both 'brochure.pdf' attachments are in the index, under DISTINCT keys ({broch_keys})")
    ck(all("/" in k for k in broch_keys),
       "...keyed on the path relative to the inputs folder, not the basename")
    subs = {idx[k]["subject"] for k in broch_keys}
    ck(subs == {"Northgate offer", "Southgate offer"},
       f"...each one naming its OWN email, which the basename key could not do ({subs})")

    north_key = next(k for k in broch_keys if "northgate" in k)
    south_key = next(k for k in broch_keys if "southgate" in k)
    ck(EM.from_email_for(idx, north_key)["subject"] == "Northgate offer"
       and EM.from_email_for(idx, south_key)["subject"] == "Southgate offer",
       "from_email_for resolves each relative path to the right email")
    ck(EM.from_email_for(idx, north_key.replace("/", "\\"))["date"] == "2025-05-13",
       "...and accepts a Windows-separated path, which is what a caller on this platform has")
    ck(EM.from_email_for(idx, "brochure.pdf") is None,
       "a BARE ambiguous name resolves to NOTHING rather than to the last sidecar read")
    ck(EM.from_email_for(idx, "Danube brochure.pdf") is not None
       and EM.from_email_for(idx, "Danube brochure.pdf")["subject"] == "Danube Park offer",
       "...while an unambiguous bare name still resolves, so the .msg case is unaffected")

    print("merge reads it the same way:")
    rec = [{"city": "Prague", "country": "CZ", "developer": "CTP", "park": "Northgate",
            "region": "Prague", "status": "Existing", "warehouseArea": 12000,
            "areaUnit": "sq m",
            "__meta": {"source_file": north_key, "source_type": "pdf",
                       "locator_base": "page 1", "page_no": 0,
                       "prov": {"park": "page 1", "warehouseArea": "page 1"}}}]
    recf = work / "rec.json"
    recf.write_text(json.dumps(rec), encoding="utf-8")
    canon, led = work / "canonical.json", work / "source_ledger.csv"
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(recf),
                        "--source-dir", str(inputs), "--out", str(canon), "--ledger", str(led)],
                       capture_output=True, text=True, errors="replace")
    if p.returncode != 0 or not led.exists():
        ck(False, f"merge.py ran (rc={p.returncode}) "
                  f"{ascii(p.stderr[-400:] or p.stdout[-400:])}")
    else:
        text = led.read_text(encoding="utf-8", errors="replace")
        ck("Northgate offer" in text,
           "the ledger locator names the email that actually carried THIS brochure")
        ck("Southgate offer" not in text,
           "...and not the other email with the identically named attachment, which is the bug")

    print("skipped attachments are surfaced:")
    (inputs / "thin.eml").write_bytes(
        _eml("Riverside site plan", "Fri, 16 May 2025 09:00:00 +0200",
             "Site plan attached.",
             [("site plan.png", _TINY_PNG * 20, "png", None),
              ("", _TINY_PNG, "png", "<sig-logo-9>")]))
    inv2 = I.discover(inputs, exclude_dir=work)
    (work / "inventory.json").write_text(json.dumps(inv2, ensure_ascii=False), encoding="utf-8")
    sect = D._email_attachments_skipped(work)
    blob = "\n".join(sect)
    ck(bool(sect) and sect[0].startswith("## Email attachments not read"),
       "the Gaps Report gains an 'Email attachments not read' section")
    ck("site plan.png" in blob and "Riverside site plan" in blob,
       f"...naming the refused file AND the email subject ({blob[:160]!r})")
    ck("KB" in blob and ("20 KB" in blob or "content-id" in blob),
       "...with its size and the rule that refused it, so a real plan is visible not lost")

    gaps = D.gaps_report(json.loads(canon.read_text(encoding="utf-8-sig"))
                         if canon.exists() else {"properties": [], "meta": {}},
                         "test", work_dir=work)
    ck("## Email attachments not read" in gaps and "site plan.png" in gaps,
       "...and the section is actually IN the delivered Gaps Report, not only in the helper")

    ck(not D._email_attachments_skipped(tmp / "nope"),
       "a missing inventory yields no section rather than costing the whole report")

    if FAILS:
        print(f"\nEMAIL ATTACHMENT PROVENANCE TEST: FAIL ({len(FAILS)})")
        return 1
    print("\nEMAIL ATTACHMENT PROVENANCE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
