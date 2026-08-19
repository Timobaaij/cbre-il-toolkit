#!/usr/bin/env python3
"""Read Outlook .msg files (text + attachments) using ONLY the Python standard library.

WHY THIS EXISTS: stage 2 used to `import extract_msg`, which does not exist in the Claude Cowork
sandbox. That sandbox has no pip and no network, so it cannot be installed there - and the failure was
quiet: the import sat inside a per-file try/except, so every message was recorded as an error while the
script still printed "DONE. parsed=N" and exited 0. Broker rents and every email attachment silently
vanished from the run.

WHY NOT VENDOR extract_msg: it needs 10 packages (~1 MB of wheels, 3.9 MB unpacked) that CBRE IT would
have to review, and its current release cannot be bundled offline at all because one dependency
(red-black-tree-mod) publishes no wheel, only an sdist - unbuildable with no pip and no compiler. A .msg
is an OLE2/CFB container and the skill needs five things from it (subject, sender, date, body,
attachments), so ~400 lines of our own beats a dependency tree we cannot install where it matters.

WHAT IT IS: a minimal CFB reader plus the MAPI property lookups those five things need. Deliberately
NOT a general .msg library.

SURFACE: intentionally mirrors the part of extract_msg's API that emails_parse.py used
(`Message(path)`, `.subject`, `.sender`, `.date`, `.body`, `.attachments[].longFilename`,
`.shortFilename`, `.data`, `.close()`), so stage 2 reads the same either way and extract_msg can still
be used as a cross-check where it happens to be installed.

Self-test (proves it works in a sandbox, no pip, no network):
    python msg_reader.py --selftest <folder of .msg files or an Emails.zip>
"""
import datetime
import html as _html
import os
import re
import struct
import sys
import zipfile

# ----------------------------------------------------------------- CFB container

CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF

TYPE_STORAGE = 1
TYPE_STREAM = 2
TYPE_ROOT = 5


class MsgError(Exception):
    """A .msg that cannot be read at all (not a CFB, truncated, corrupt chain)."""


class _Entry:
    __slots__ = ("name", "kind", "left", "right", "child", "start", "size", "index")

    def __init__(self, name, kind, left, right, child, start, size, index):
        self.name, self.kind = name, kind
        self.left, self.right, self.child = left, right, child
        self.start, self.size, self.index = start, size, index


class CompoundFile:
    """Reads the OLE2/Compound File Binary container a .msg is stored in.

    Only what a .msg needs: the FAT and mini-FAT sector chains, and the directory tree. No writing, no
    locking, no property-set parsing.
    """

    def __init__(self, data):
        if len(data) < 512 or data[:8] != CFB_SIGNATURE:
            raise MsgError("not an OLE2/CFB file (bad signature) - is it really a .msg?")
        self.data = data

        (sector_shift, mini_sector_shift) = struct.unpack_from("<HH", data, 0x1E)
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_sector_shift
        if self.sector_size not in (512, 4096):
            raise MsgError(f"unsupported sector size {self.sector_size}")

        num_fat_sectors = struct.unpack_from("<I", data, 0x2C)[0]
        self.first_dir_sector = struct.unpack_from("<I", data, 0x30)[0]
        self.mini_cutoff = struct.unpack_from("<I", data, 0x38)[0] or 4096
        first_minifat = struct.unpack_from("<I", data, 0x3C)[0]
        num_minifat = struct.unpack_from("<I", data, 0x40)[0]
        first_difat = struct.unpack_from("<I", data, 0x44)[0]
        num_difat = struct.unpack_from("<I", data, 0x48)[0]

        self.fat = self._read_fat(num_fat_sectors, first_difat, num_difat)
        self.minifat = self._read_chain_as_uint32(first_minifat, num_minifat)
        self.entries = self._read_directory()
        self.mini_stream = self._read_mini_stream()

    # -- sector plumbing

    def _sector_offset(self, sector):
        # The 512-byte header counts as sector -1, so data sectors start one sector in. This holds for
        # 4096-byte sectors too: the remainder of the first sector is simply unused.
        return (sector + 1) * self.sector_size

    def _read_sector(self, sector):
        off = self._sector_offset(sector)
        chunk = self.data[off:off + self.sector_size]
        if len(chunk) < self.sector_size:
            # A truncated final sector is common in the wild; pad rather than refuse the whole file.
            chunk = chunk + b"\x00" * (self.sector_size - len(chunk))
        return chunk

    def _read_fat(self, num_fat_sectors, first_difat, num_difat):
        """The FAT's own sector numbers live in the header's 109-entry DIFAT, then in a DIFAT chain."""
        fat_sectors = list(struct.unpack_from("<109I", self.data, 0x4C))
        sector = first_difat
        per = self.sector_size // 4
        seen = set()
        while sector not in (ENDOFCHAIN, FREESECT) and num_difat > 0:
            if sector in seen:
                raise MsgError("DIFAT chain loops")
            seen.add(sector)
            block = self._read_sector(sector)
            vals = struct.unpack_from(f"<{per}I", block, 0)
            fat_sectors.extend(vals[:-1])
            sector = vals[-1]
            num_difat -= 1

        fat = []
        for s in fat_sectors[:num_fat_sectors] if num_fat_sectors else fat_sectors:
            if s in (ENDOFCHAIN, FREESECT):
                continue
            fat.extend(struct.unpack_from(f"<{per}I", self._read_sector(s), 0))
        if not fat:
            raise MsgError("empty FAT")
        return fat

    def _chain(self, start):
        """Sector numbers following `start`, guarding against the loops corrupt files contain."""
        out, seen, s = [], set(), start
        while s not in (ENDOFCHAIN, FREESECT):
            if s in seen or s >= len(self.fat):
                break
            seen.add(s)
            out.append(s)
            s = self.fat[s]
        return out

    def _read_chain_as_uint32(self, start, count_sectors):
        if start in (ENDOFCHAIN, FREESECT) or not count_sectors:
            return []
        per = self.sector_size // 4
        vals = []
        for s in self._chain(start):
            vals.extend(struct.unpack_from(f"<{per}I", self._read_sector(s), 0))
        return vals

    def _read_directory(self):
        raw = b"".join(self._read_sector(s) for s in self._chain(self.first_dir_sector))
        entries = []
        for i in range(len(raw) // 128):
            rec = raw[i * 128:(i + 1) * 128]
            name_len = struct.unpack_from("<H", rec, 0x40)[0]
            name = rec[:max(0, min(64, name_len - 2))].decode("utf-16-le", "replace")
            kind = rec[0x42]
            left, right, child = struct.unpack_from("<III", rec, 0x44)
            start = struct.unpack_from("<I", rec, 0x74)[0]
            size = struct.unpack_from("<Q", rec, 0x78)[0]
            if self.sector_size == 512:
                size &= 0xFFFFFFFF          # v3 files leave the high half undefined
            entries.append(_Entry(name, kind, left, right, child, start, size, i))
        if not entries or entries[0].kind != TYPE_ROOT:
            raise MsgError("no root directory entry")
        return entries

    def _read_mini_stream(self):
        root = self.entries[0]
        if root.start in (ENDOFCHAIN, FREESECT) or not root.size:
            return b""
        blob = b"".join(self._read_sector(s) for s in self._chain(root.start))
        return blob[:root.size]

    # -- public reads

    def children(self, entry):
        """Direct children of a storage. The directory is a red-black tree, so walk child then
        left/right; an explicit stack keeps deep trees off Python's recursion limit."""
        out = []
        if entry.child in (ENDOFCHAIN, FREESECT) or entry.child >= len(self.entries):
            return out
        stack, seen = [entry.child], set()
        while stack:
            i = stack.pop()
            if i in (ENDOFCHAIN, FREESECT) or i >= len(self.entries) or i in seen:
                continue
            seen.add(i)
            e = self.entries[i]
            out.append(e)
            stack.append(e.left)
            stack.append(e.right)
        return out

    def read_stream(self, entry):
        if entry.kind != TYPE_STREAM or not entry.size:
            return b""
        if entry.size < self.mini_cutoff:
            per = self.mini_sector_size
            out, seen, s = [], set(), entry.start
            while s not in (ENDOFCHAIN, FREESECT):
                if s in seen or s >= len(self.minifat):
                    break
                seen.add(s)
                out.append(self.mini_stream[s * per:(s + 1) * per])
                s = self.minifat[s]
            return b"".join(out)[:entry.size]
        return b"".join(self._read_sector(s) for s in self._chain(entry.start))[:entry.size]


# ----------------------------------------------------------------- MAPI decoding

PT_UNICODE = 0x001F
PT_STRING8 = 0x001E
PT_BINARY = 0x0102
PT_OBJECT = 0x000D
PT_LONG = 0x0003
PT_SYSTIME = 0x0040

# Property ids this reader looks for. Everything else in the file is ignored on purpose.
P_SUBJECT = 0x0037
P_NORMALIZED_SUBJECT = 0x0E1D
P_BODY = 0x1000
P_BODY_HTML = 0x1013
P_RTF_COMPRESSED = 0x1009
P_SENDER_NAME = 0x0C1A
P_SENDER_EMAIL = 0x0C1F
P_SENT_REPRESENTING_NAME = 0x0042
P_SENT_REPRESENTING_EMAIL = 0x0065
P_SMTP_ADDRESS = 0x39FE
P_DISPLAY_TO = 0x0E04
P_DISPLAY_CC = 0x0E03
P_CLIENT_SUBMIT_TIME = 0x0039
P_DELIVERY_TIME = 0x0E06
P_TRANSPORT_HEADERS = 0x007D
P_INTERNET_CPID = 0x3FDE
P_MESSAGE_CODEPAGE = 0x3FFD
P_ATTACH_DATA = 0x3701
P_ATTACH_LONG_FILENAME = 0x3707
P_ATTACH_FILENAME = 0x3704
P_ATTACH_EXTENSION = 0x3703
P_ATTACH_MIME_TAG = 0x370E
P_ATTACH_CONTENT_ID = 0x3712
P_ATTACH_METHOD = 0x3705
P_DISPLAY_NAME = 0x3001

ATTACH_BY_VALUE = 1
ATTACH_EMBEDDED_MSG = 5

SUBSTG_RE = re.compile(r"^__substg1\.0_([0-9A-Fa-f]{4})([0-9A-Fa-f]{4})$")
ATTACH_DIR_RE = re.compile(r"^__attach_version1\.0_#?([0-9A-Fa-f]+)$", re.I)

# Windows codepage -> Python codec, for the 8-bit (PT_STRING8) case. Anything unlisted falls back to
# cp1252, which is what Outlook writes on a Western European machine.
CODEPAGES = {
    65001: "utf-8", 1200: "utf-16-le", 1252: "cp1252", 1250: "cp1250", 1251: "cp1251",
    1253: "cp1253", 1254: "cp1254", 1255: "cp1255", 1256: "cp1256", 1257: "cp1257", 1258: "cp1258",
    28591: "iso-8859-1", 28592: "iso-8859-2", 28605: "iso-8859-15", 20127: "ascii", 874: "cp874",
    932: "cp932", 936: "gbk", 949: "cp949", 950: "cp950", 437: "cp437", 850: "cp850",
}

FILETIME_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(value):
    """FILETIME (100ns ticks since 1601-01-01 UTC) -> aware datetime, or None if implausible."""
    if not value:
        return None
    try:
        dt = FILETIME_EPOCH + datetime.timedelta(microseconds=value // 10)
    except (OverflowError, OSError, ValueError):
        return None
    return dt if 1980 < dt.year < 2100 else None


class Attachment:
    """One attachment. `longFilename`/`shortFilename`/`data` are named for extract_msg compatibility,
    so stage 2 does not care which reader produced it."""

    def __init__(self, longFilename=None, shortFilename=None, data=None, mimetype=None,
                 content_id=None, embedded_message=None):
        self.longFilename = longFilename
        self.shortFilename = shortFilename
        self.data = data
        self.mimetype = mimetype
        self.content_id = content_id
        self.embedded_message = embedded_message      # a Message when this attachment IS an email

    @property
    def filename(self):
        return self.longFilename or self.shortFilename

    def __repr__(self):
        n = len(self.data) if isinstance(self.data, (bytes, bytearray)) else 0
        return f"<Attachment {self.filename!r} {n} bytes>"


class Message:
    """One Outlook message: text and attachments, decoded from the CFB streams.

    Accepts a path, raw bytes, or (internally) an already-open storage, which is how an embedded
    message attachment is read without writing anything to disk.
    """

    def __init__(self, path_or_bytes=None, _cfb=None, _entry=None, _depth=0):
        self._depth = _depth
        self.path = None
        if _cfb is not None:
            self._cfb, self._root = _cfb, _entry
        else:
            if isinstance(path_or_bytes, (bytes, bytearray)):
                data = bytes(path_or_bytes)
            else:
                self.path = path_or_bytes
                with open(path_or_bytes, "rb") as fh:
                    data = fh.read()
            self._cfb = CompoundFile(data)
            self._root = self._cfb.entries[0]

        kids = self._cfb.children(self._root)
        self._streams = {}          # (propid, proptype) -> bytes
        self._storages = {}         # name -> entry
        for e in kids:
            if e.kind == TYPE_STREAM:
                m = SUBSTG_RE.match(e.name)
                if m:
                    self._streams[(int(m.group(1), 16), int(m.group(2), 16))] = self._cfb.read_stream(e)
                elif e.name.startswith("__properties_version1.0"):
                    self._props_raw = self._cfb.read_stream(e)
            elif e.kind == TYPE_STORAGE:
                self._storages[e.name] = e
        if not hasattr(self, "_props_raw"):
            self._props_raw = b""

        self._fixed = self._parse_fixed_properties(self._props_raw, is_top_level=(_cfb is None))
        self._codepage = self._pick_codepage()

    # -- property access

    @staticmethod
    def _parse_fixed_properties(raw, is_top_level):
        """The __properties stream holds fixed-width values as 16-byte entries after a header that is
        32 bytes for a top-level message and 8 for an embedded one/attachment."""
        out = {}
        if not raw:
            return out
        start = 32 if is_top_level else 8
        for off in range(start, len(raw) - 15, 16):
            tag, _flags = struct.unpack_from("<II", raw, off)
            value = raw[off + 8:off + 16]
            out[(tag >> 16) & 0xFFFF, tag & 0xFFFF] = value
        return out

    def _pick_codepage(self):
        for pid in (P_INTERNET_CPID, P_MESSAGE_CODEPAGE):
            v = self._fixed.get((pid, PT_LONG))
            if v:
                cp = struct.unpack_from("<i", v, 0)[0]
                if cp in CODEPAGES:
                    return CODEPAGES[cp]
        return "cp1252"

    def _str(self, propid):
        """A string property, Unicode stream preferred over the 8-bit one."""
        raw = self._streams.get((propid, PT_UNICODE))
        if raw is not None:
            return raw.decode("utf-16-le", "replace")
        raw = self._streams.get((propid, PT_STRING8))
        if raw is not None:
            return raw.decode(self._codepage, "replace")
        return None

    def _bin(self, propid):
        return self._streams.get((propid, PT_BINARY))

    def _time(self, propid):
        v = self._fixed.get((propid, PT_SYSTIME))
        return _filetime(struct.unpack_from("<Q", v, 0)[0]) if v else None

    def _long(self, propid):
        v = self._fixed.get((propid, PT_LONG))
        return struct.unpack_from("<i", v, 0)[0] if v else None

    # -- the five things the skill needs

    @property
    def subject(self):
        return self._str(P_SUBJECT) or self._str(P_NORMALIZED_SUBJECT) or ""

    @property
    def sender(self):
        """"Name <email>" where both are known, matching how extract_msg presents it closely enough
        for the model to read."""
        name = self._str(P_SENDER_NAME) or self._str(P_SENT_REPRESENTING_NAME) or ""
        email = (self._str(P_SMTP_ADDRESS) or self._str(P_SENT_REPRESENTING_EMAIL)
                 or self._str(P_SENDER_EMAIL) or "")
        name, email = name.strip(), email.strip()
        if name and email and email.lower() not in name.lower():
            return f"{name} <{email}>"
        return name or email

    @property
    def to(self):
        return self._str(P_DISPLAY_TO) or ""

    @property
    def cc(self):
        return self._str(P_DISPLAY_CC) or ""

    @property
    def date(self):
        """The send time, preferring the original `Date:` header over the stored FILETIME.

        Both describe the same instant, but MAPI keeps FILETIME in UTC while the header carries the
        sender's own offset. A broker email that reads 16:41 +0100 in Outlook should read 16:41 here
        too, or comparing "who quoted what, when" across a thread quietly shifts by an hour."""
        hdrs = self._str(P_TRANSPORT_HEADERS)
        if hdrs:
            m = re.search(r"^Date:\s*(.+)$", hdrs, re.I | re.M)
            if m:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(m.group(1).strip())
                    if dt and 1980 < dt.year < 2100:
                        return dt
                except Exception:
                    pass                    # malformed header: fall through to the stored time
        return self._time(P_CLIENT_SUBMIT_TIME) or self._time(P_DELIVERY_TIME)

    @property
    def html(self):
        raw = self._bin(P_BODY_HTML)
        if raw:
            return raw.decode(self._codepage, "replace")
        return self._str(P_BODY_HTML)

    @property
    def body(self):
        """Plain text, falling back through HTML then compressed RTF.

        Order matters: PR_BODY is what Outlook wrote as text and needs no reconstruction. Only when a
        message is HTML- or RTF-only (common from some agency CRMs) is anything converted, because
        every conversion loses something."""
        text = self._str(P_BODY)
        if text and text.strip():
            return text
        h = self.html
        if h and h.strip():
            return html_to_text(h)
        rtf = self._bin(P_RTF_COMPRESSED)
        if rtf:
            try:
                plain_rtf = decompress_rtf(rtf)
            except MsgError:
                return ""
            inner = de_encapsulate_html(plain_rtf)
            return html_to_text(inner) if inner else rtf_to_text(plain_rtf)
        return ""

    @property
    def attachments(self):
        """Every attachment, in Outlook's own order.

        An attachment that IS an email (attach method 5) is returned with `embedded_message` set and a
        `.msg` filename, and its bytes are None because it lives inside this container rather than as a
        standalone file. emails_parse.py recurses into those so their text and their own attachments
        reach the model too - the rents the skill is after are regularly one reply deep."""
        out = []
        for name in sorted(self._storages, key=lambda n: n.lower()):
            m = ATTACH_DIR_RE.match(name)
            if not m:
                continue
            sub = Message(_cfb=self._cfb, _entry=self._storages[name], _depth=self._depth + 1)
            long_fn = sub._str(P_ATTACH_LONG_FILENAME)
            short_fn = sub._str(P_ATTACH_FILENAME)
            method = sub._long(P_ATTACH_METHOD)
            mime = sub._str(P_ATTACH_MIME_TAG)
            cid = sub._str(P_ATTACH_CONTENT_ID)

            embedded = None
            data = sub._bin(P_ATTACH_DATA)
            if data is None and self._depth < 8:
                # method 5: the attachment is a whole message, stored as a storage not a stream.
                for cand in sub._storages:
                    if cand.startswith("__substg1.0_3701"):
                        embedded = Message(_cfb=self._cfb, _entry=sub._storages[cand],
                                           _depth=self._depth + 1)
                        break
            if embedded is not None and not (long_fn or short_fn):
                stem = (embedded.subject or sub._str(P_DISPLAY_NAME) or "embedded message").strip()
                long_fn = f"{stem[:120]}.msg"
            if embedded is None and data is None:
                continue                      # method 2/4 (link-only): nothing to extract, skip quietly
            if method == ATTACH_EMBEDDED_MSG and embedded is None and data is None:
                continue
            out.append(Attachment(longFilename=long_fn, shortFilename=short_fn, data=data,
                                  mimetype=mime, content_id=cid, embedded_message=embedded))
        return out

    def close(self):
        """Present for extract_msg compatibility. Nothing is held open: the file is read once into
        memory, because a 17 MB .msg is far cheaper to hold than to seek repeatedly."""
        self._streams = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ----------------------------------------------------------------- RTF + HTML fallbacks

LZFU_MAGIC_COMPRESSED = 0x75465A4C      # 'LZFu'
LZFU_MAGIC_UNCOMPRESSED = 0x414C454D    # 'MELA'

# The 207-byte dictionary every LZFu stream starts from. Fixed by the format; not a guess.
LZFU_PREBUF = (
    b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman \\fswiss \\fmodern "
    b"\\fscript \\fdecor MS Sans SerifSymbolArialTimes New RomanCourier{\\colortbl\\red0\\green0"
    b"\\blue0\r\n\\par \\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx"
)


def decompress_rtf(data):
    """LZFu (MS-OXRTFCP) -> raw RTF bytes."""
    if len(data) < 16:
        raise MsgError("RTF stream too short")
    comp_size, raw_size, magic, _crc = struct.unpack_from("<IIII", data, 0)
    if magic == LZFU_MAGIC_UNCOMPRESSED:
        return data[16:16 + raw_size]
    if magic != LZFU_MAGIC_COMPRESSED:
        raise MsgError(f"unknown RTF compression magic 0x{magic:08x}")

    src = data[16:4 + comp_size] if comp_size + 4 <= len(data) else data[16:]
    dict_buf = bytearray(4096)
    dict_buf[:len(LZFU_PREBUF)] = LZFU_PREBUF
    wp = len(LZFU_PREBUF)
    out = bytearray()
    i = 0
    while i < len(src) and len(out) < raw_size:
        control = src[i]
        i += 1
        for bit in range(8):
            if i >= len(src) or len(out) >= raw_size:
                break
            if not (control >> bit) & 1:
                b = src[i]
                i += 1
                out.append(b)
                dict_buf[wp % 4096] = b
                wp += 1
            else:
                if i + 1 >= len(src):
                    i = len(src)
                    break
                b1, b2 = src[i], src[i + 1]
                i += 2
                offset = (b1 << 4) | (b2 >> 4)
                length = (b2 & 0x0F) + 2
                if offset == wp % 4096:
                    return bytes(out)                  # documented end-of-stream marker
                for k in range(length):
                    ch = dict_buf[(offset + k) % 4096]
                    out.append(ch)
                    dict_buf[wp % 4096] = ch
                    wp += 1
    return bytes(out)


def de_encapsulate_html(rtf_bytes):
    """Pull the original HTML back out of an RTF wrapper Outlook made from it (\\fromhtml1).

    `\\htmlrtf` / `\\htmlrtf0` bracket the parts RTF added and HTML never had, so those runs are
    dropped. Returns None when the RTF is not encapsulated HTML at all."""
    try:
        s = rtf_bytes.decode("cp1252", "replace")
    except Exception:
        return None
    if "\\fromhtml1" not in s.lower():
        return None

    out = []
    i, n = 0, len(s)
    suppress = False
    while i < n:
        c = s[i]
        if c == "\\":
            m = re.match(r"\\\*?([a-zA-Z]+)(-?\d+)? ?", s[i:])
            if m:
                word, arg = m.group(1), m.group(2)
                if word == "htmlrtf":
                    suppress = (arg != "0")
                elif word in ("par", "line") and not suppress:
                    out.append("\n")
                elif word == "tab" and not suppress:
                    out.append("\t")
                elif word in ("htmltag", "mhtmltag"):
                    pass
                i += m.end()
                continue
            m = re.match(r"\\'([0-9a-fA-F]{2})", s[i:])
            if m:
                if not suppress:
                    out.append(bytes([int(m.group(1), 16)]).decode("cp1252", "replace"))
                i += m.end()
                continue
            if i + 1 < n:
                if not suppress:
                    out.append(s[i + 1])
                i += 2
                continue
            i += 1
        elif c in "{}":
            i += 1
        else:
            if not suppress:
                out.append(c)
            i += 1
    return "".join(out)


def rtf_to_text(rtf_bytes):
    """Last resort: strip RTF to something readable. Not a renderer - the goal is that a broker's rent
    figure survives, not that formatting does."""
    try:
        s = rtf_bytes.decode("cp1252", "replace")
    except Exception:
        return ""
    s = re.sub(r"\{\\\*?\\(?:fonttbl|colortbl|stylesheet|info|pict|object|themedata|"
               r"colorschememapping|latentstyles|datastore|xmlnstbl)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
               " ", s, flags=re.I | re.S)
    s = re.sub(r"\\'([0-9a-fA-F]{2})",
               lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), s)
    s = re.sub(r"\\u(-?\d+)\s?\??",
               lambda m: chr(int(m.group(1)) % 65536) if m.group(1).isdigit() or m.group(1).lstrip('-').isdigit() else "", s)
    s = re.sub(r"\\(?:par|line)\b ?", "\n", s)
    s = re.sub(r"\\tab\b ?", "\t", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    return _tidy(s)


BLOCK_TAGS = r"p|div|br|tr|li|h[1-6]|table|thead|tbody|blockquote|section|article|ul|ol|pre"


def html_to_text(html_str):
    """Enough HTML-to-text for a broker email: kill script/style, turn blocks into newlines, unescape
    entities. Keeps figures and units intact, which is all stage 4 needs to read a rent from."""
    if not html_str:
        return ""
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", html_str)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(rf"(?i)<\s*/?\s*(?:{BLOCK_TAGS})\b[^>]*>", "\n", s)
    s = re.sub(r"(?i)<\s*td\b[^>]*>", "\t", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = _html.unescape(s)
    return _tidy(s)


def _tidy(s):
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{3,}", "  ", s)
    return s.strip()


# ----------------------------------------------------------------- self-test

def _selftest(target):
    """Prove in the target environment that .msg reading works, with no pip and no network.

    Exists because the sandbox this is written for is the one place it cannot be tested from a
    developer machine. Run it there and the answer takes five seconds.
    """
    import tempfile

    print("msg_reader self-test")
    print(f"  python      : {sys.version.split()[0]}")
    print(f"  platform    : {sys.platform}")
    third_party = sorted(
        m for m in sys.modules
        if not m.startswith("_") and "." not in m
        and m not in sys.builtin_module_names
        and getattr(sys.modules[m], "__file__", None)
        and "site-packages" in (sys.modules[m].__file__ or "")
    )
    print(f"  3rd-party modules loaded: {third_party or 'none (stdlib only)'}")

    tmp = None
    if os.path.isfile(target) and target.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="msgselftest")
        with zipfile.ZipFile(target) as z:
            z.extractall(tmp)
        root = tmp
    else:
        root = target
    files = sorted(os.path.join(r, f) for r, _, fs in os.walk(root)
                   for f in fs if f.lower().endswith(".msg"))
    if not files:
        print(f"  FAIL: no .msg files under {target}")
        return 1

    ok = bad = 0
    total_chars = total_atts = total_att_bytes = 0
    for p in files:
        try:
            m = Message(p)
            body = m.body or ""
            atts = m.attachments
            n_bytes = sum(len(a.data) for a in atts if isinstance(a.data, (bytes, bytearray)))
            nested = sum(1 for a in atts if a.embedded_message is not None)
            total_chars += len(body)
            total_atts += len(atts)
            total_att_bytes += n_bytes
            if not (m.subject or body):
                raise MsgError("no subject and no body - decoded nothing")
            ok += 1
            print(f"  OK   {os.path.basename(p)[:44]:44} body={len(body):>6}  att={len(atts):>2}"
                  f"  embedded={nested}  {n_bytes/1024:>8.0f} KB")
            m.close()
        except Exception as e:
            bad += 1
            print(f"  FAIL {os.path.basename(p)[:44]:44} {type(e).__name__}: {e}")

    print(f"\n  parsed {ok}/{len(files)}   text {total_chars:,} chars   "
          f"attachments {total_atts} ({total_att_bytes/1048576:.1f} MB)")
    if tmp:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("  RESULT:", "PASS" if bad == 0 and ok else "FAIL")
    return 0 if (bad == 0 and ok) else 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        raise SystemExit(_selftest(sys.argv[2]))
    print(__doc__.strip())
    print("\nUsage: python msg_reader.py --selftest <folder of .msg files | Emails.zip>")
    raise SystemExit(2)
