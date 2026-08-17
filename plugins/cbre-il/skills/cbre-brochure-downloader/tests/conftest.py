"""Fixtures that build minimal xlsx files in-process.

Writing the XML by hand keeps the tests dependency-free and lets each one isolate a
single storage quirk (rich-text runs, inline strings, cached formulas, ranged links).
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

SHEET = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
           xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheetData>{rows}</sheetData>{hyperlinks}
</worksheet>"""


def build_xlsx(
    path: Path,
    rows: str,
    shared: list[str] | None = None,
    hyperlinks: list[tuple[str, str]] | None = None,
    sheet_name: str = "Sheet1",
    shared_raw: str | None = None,
) -> Path:
    """Assemble an xlsx from raw sheetData XML.

    `hyperlinks` is [(ref, url)]; each becomes a relationship plus a <hyperlink> entry.
    `shared_raw` supplies the <si> entries verbatim, for testing rich-text runs.
    """
    hl_xml = ""
    rels_xml = WORKBOOK_RELS
    sheet_rels = None

    if hyperlinks:
        entries = "".join(
            f'<hyperlink ref="{ref}" r:id="rIdH{i}"/>' for i, (ref, _) in enumerate(hyperlinks, 1)
        )
        hl_xml = f"<hyperlinks>{entries}</hyperlinks>"
        rel_entries = "".join(
            f'<Relationship Id="rIdH{i}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{url}" TargetMode="External"/>'
            for i, (_, url) in enumerate(hyperlinks, 1)
        )
        sheet_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rel_entries}</Relationships>"
        )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("xl/workbook.xml", WORKBOOK.format(sheet_name=sheet_name))
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", SHEET.format(rows=rows, hyperlinks=hl_xml))
        if sheet_rels:
            zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels)
        if shared_raw is not None:
            zf.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"{shared_raw}</sst>",
            )
        elif shared is not None:
            # Excel stores markup-bearing text escaped; the fixture must too, or the
            # part we hand the reader is not well-formed XML.
            items = "".join(f"<si><t>{escape(s)}</t></si>" for s in shared)
            zf.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                f'count="{len(shared)}" uniqueCount="{len(shared)}">{items}</sst>',
            )
    return path


REAL_LONGLIST = Path(
    r"C:\Users\TBaaij\AppData\Local\Temp\Warehouse Availability - Temu UK (6).xlsx"
)


@pytest.fixture
def real_longlist() -> Path:
    """The reference Temu UK longlist, skipped if it is not on this machine."""
    if not REAL_LONGLIST.exists():
        pytest.skip(f"reference longlist not present: {REAL_LONGLIST}")
    return REAL_LONGLIST
