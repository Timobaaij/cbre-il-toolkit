"""Minimal .xlsx reader built on the standard library only.

An .xlsx file is a zip of XML parts, so cell text and hyperlink targets can be read
without openpyxl. That matters here: this runs in the Cowork sandbox, where a vendored
wheel is one more thing that can fail to load.

What it reads:
  - cell text (shared strings incl. rich-text runs, inline strings, cached formula
    results, plain numbers)
  - external hyperlink targets, which is where a longlist keeps its brochure URLs -
    the visible cell text is usually just the word "Brochure"
  - =HYPERLINK("url", "label") formulas, used by some longlists instead of real hyperlinks
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_CELL_REF = re.compile(r"^([A-Za-z]+)(\d+)$")
_HYPERLINK_FORMULA = re.compile(r"""HYPERLINK\s*\(\s*(["'])(.+?)\1""", re.IGNORECASE | re.DOTALL)


class XlsxError(Exception):
    """The workbook could not be read as an xlsx."""


@dataclass
class Sheet:
    """One worksheet: text by (row, col) and hyperlink targets by (row, col).

    Both dicts are keyed by zero-based (row, col). `max_row`/`max_col` are exclusive
    bounds over cells that actually carry text or a link.
    """

    name: str
    text: dict[tuple[int, int], str] = field(default_factory=dict)
    links: dict[tuple[int, int], str] = field(default_factory=dict)

    @property
    def max_row(self) -> int:
        keys = list(self.text) + list(self.links)
        return max((r for r, _ in keys), default=-1) + 1

    @property
    def max_col(self) -> int:
        keys = list(self.text) + list(self.links)
        return max((c for _, c in keys), default=-1) + 1

    def cell(self, row: int, col: int) -> str:
        """Text at zero-based (row, col), or "" if empty."""
        return self.text.get((row, col), "")

    def link(self, row: int, col: int) -> str | None:
        """Hyperlink target at zero-based (row, col), or None."""
        return self.links.get((row, col))

    def row_values(self, row: int) -> list[str]:
        return [self.cell(row, c) for c in range(self.max_col)]


def col_to_index(letters: str) -> int:
    """"A" -> 0, "Z" -> 25, "AA" -> 26."""
    n = 0
    for ch in letters.upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"not a column reference: {letters!r}")
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def index_to_col(index: int) -> str:
    """0 -> "A", 25 -> "Z", 26 -> "AA"."""
    if index < 0:
        raise ValueError("column index must be non-negative")
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def parse_ref(ref: str) -> tuple[int, int]:
    """"Z2" -> (1, 25), zero-based (row, col)."""
    m = _CELL_REF.match(ref.strip().replace("$", ""))
    if not m:
        raise ValueError(f"not a cell reference: {ref!r}")
    return int(m.group(2)) - 1, col_to_index(m.group(1))


def expand_ref(ref: str) -> list[tuple[int, int]]:
    """Expand "Z2" to one cell and "Z2:AA4" to every cell in the rectangle.

    Hyperlinks are sometimes stored against a range rather than a single cell.
    """
    ref = ref.strip()
    if ":" not in ref:
        return [parse_ref(ref)]
    start, end = ref.split(":", 1)
    r1, c1 = parse_ref(start)
    r2, c2 = parse_ref(end)
    rows = range(min(r1, r2), max(r1, r2) + 1)
    cols = range(min(c1, c2), max(c1, c2) + 1)
    return [(r, c) for r in rows for c in cols]


def _local(tag: str) -> str:
    """Strip the namespace from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def _all_text(node: ET.Element) -> str:
    """Concatenate every <t> descendant. Rich text splits a string across <r> runs."""
    return "".join(t.text or "" for t in node.iter(f"{{{NS_MAIN}}}t"))


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return [_all_text(si) for si in root.findall(f"{{{NS_MAIN}}}si")]


def _read_rels(zf: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id -> (target, target_mode) for the given part path."""
    slash = part.rfind("/")
    rels_path = f"{part[:slash]}/_rels/{part[slash + 1:]}.rels" if slash >= 0 else f"_rels/{part}.rels"
    try:
        raw = zf.read(rels_path)
    except KeyError:
        return {}
    root = ET.fromstring(raw)
    out: dict[str, tuple[str, str]] = {}
    for rel in root.findall(f"{{{NS_PKG_REL}}}Relationship"):
        rid = rel.get("Id")
        if rid:
            out[rid] = (rel.get("Target", ""), rel.get("TargetMode", ""))
    return out


def sheet_names(path: str) -> list[str]:
    """Worksheet names in workbook order."""
    with zipfile.ZipFile(path) as zf:
        return [name for name, _ in _sheet_index(zf)]


def _sheet_index(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(sheet name, part path)] in workbook order."""
    try:
        raw = zf.read("xl/workbook.xml")
    except KeyError as exc:
        raise XlsxError("no xl/workbook.xml - not an xlsx file?") from exc

    rels = _read_rels(zf, "xl/workbook.xml")
    root = ET.fromstring(raw)
    out: list[tuple[str, str]] = []
    for i, sheet in enumerate(root.iter(f"{{{NS_MAIN}}}sheet"), start=1):
        name = sheet.get("name") or f"Sheet{i}"
        rid = sheet.get(f"{{{NS_DOC_REL}}}id")
        target = rels.get(rid, ("", ""))[0] if rid else ""
        if target:
            part = target[1:] if target.startswith("/") else f"xl/{target.lstrip('./')}"
        else:
            part = f"xl/worksheets/sheet{i}.xml"
        out.append((name, part))
    return out


def read_sheet(path: str, sheet: str | None = None) -> Sheet:
    """Read one worksheet. `sheet` selects by name; None takes the first.

    Raises XlsxError if the file is not an xlsx or the named sheet is absent.
    """
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise XlsxError(f"cannot open {path}: {exc}") from exc

    with zf:
        index = _sheet_index(zf)
        if not index:
            raise XlsxError("workbook contains no worksheets")

        if sheet is None:
            name, part = index[0]
        else:
            wanted = sheet.strip().lower()
            match = [(n, p) for n, p in index if n.strip().lower() == wanted]
            if not match:
                have = ", ".join(n for n, _ in index)
                raise XlsxError(f"no sheet named {sheet!r}; workbook has: {have}")
            name, part = match[0]

        try:
            raw = zf.read(part)
        except KeyError as exc:
            raise XlsxError(f"worksheet part missing: {part}") from exc

        shared = _read_shared_strings(zf)
        rels = _read_rels(zf, part)
        result = Sheet(name=name)
        _read_cells(ET.fromstring(raw), shared, result)
        _read_hyperlinks(ET.fromstring(raw), rels, result)
        return result


def _read_cells(root: ET.Element, shared: list[str], out: Sheet) -> None:
    for cell in root.iter(f"{{{NS_MAIN}}}c"):
        ref = cell.get("r")
        if not ref:
            continue
        try:
            pos = parse_ref(ref)
        except ValueError:
            continue

        ctype = cell.get("t", "n")
        text = ""

        if ctype == "s":
            v = cell.find(f"{{{NS_MAIN}}}v")
            if v is not None and (v.text or "").strip().isdigit():
                idx = int(v.text.strip())
                if 0 <= idx < len(shared):
                    text = shared[idx]
        elif ctype == "inlineStr":
            is_node = cell.find(f"{{{NS_MAIN}}}is")
            if is_node is not None:
                text = _all_text(is_node)
        else:
            # "str" is a cached formula result; "n"/"b"/"d" carry a literal in <v>.
            v = cell.find(f"{{{NS_MAIN}}}v")
            if v is not None and v.text is not None:
                text = v.text

        text = text.strip()
        if text:
            out.text[pos] = text

        formula = cell.find(f"{{{NS_MAIN}}}f")
        if formula is not None and formula.text:
            m = _HYPERLINK_FORMULA.search(formula.text)
            if m:
                url = m.group(2).strip()
                if url:
                    out.links.setdefault(pos, url)


def _read_hyperlinks(root: ET.Element, rels: dict[str, tuple[str, str]], out: Sheet) -> None:
    for link in root.iter(f"{{{NS_MAIN}}}hyperlink"):
        ref = link.get("ref")
        rid = link.get(f"{{{NS_DOC_REL}}}id")
        if not ref or not rid:
            continue  # internal links (location=) carry no target we can follow
        target, mode = rels.get(rid, ("", ""))
        if not target:
            continue
        if mode and mode.lower() != "external":
            continue
        for pos in expand_ref(ref):
            out.links[pos] = target
