"""Tests for the stdlib xlsx reader."""

from __future__ import annotations

import pytest

from conftest import build_xlsx
from helpers import xlsx_links as X


class TestRefs:
    def test_col_to_index(self):
        assert X.col_to_index("A") == 0
        assert X.col_to_index("Z") == 25
        assert X.col_to_index("AA") == 26
        assert X.col_to_index("AC") == 28

    def test_index_to_col_round_trips(self):
        for i in (0, 25, 26, 28, 51, 52, 701, 702):
            assert X.col_to_index(X.index_to_col(i)) == i

    def test_parse_ref(self):
        assert X.parse_ref("Z2") == (1, 25)
        assert X.parse_ref("$AA$10") == (9, 26)

    def test_parse_ref_rejects_junk(self):
        with pytest.raises(ValueError):
            X.parse_ref("hello")

    def test_expand_single_and_range(self):
        assert X.expand_ref("B3") == [(2, 1)]
        assert X.expand_ref("A1:B2") == [(0, 0), (0, 1), (1, 0), (1, 1)]

    def test_expand_handles_reversed_range(self):
        assert X.expand_ref("B2:A1") == [(0, 0), (0, 1), (1, 0), (1, 1)]


class TestCellText:
    def test_shared_string(self, tmp_path):
        p = build_xlsx(
            tmp_path / "s.xlsx",
            rows='<row r="1"><c r="A1" t="s"><v>0</v></c></row>',
            shared=["Brochure"],
        )
        assert X.read_sheet(str(p)).cell(0, 0) == "Brochure"

    def test_rich_text_runs_are_concatenated(self, tmp_path):
        """Excel splits a formatted string across <r> runs; all <t> must be joined."""
        p = build_xlsx(
            tmp_path / "rt.xlsx",
            rows='<row r="1"><c r="A1" t="s"><v>0</v></c></row>',
            shared_raw="<si><r><t>Magna </t></r><r><t>Park</t></r></si>",
        )
        assert X.read_sheet(str(p)).cell(0, 0) == "Magna Park"

    def test_inline_string(self, tmp_path):
        p = build_xlsx(
            tmp_path / "i.xlsx",
            rows='<row r="1"><c r="A1" t="inlineStr"><is><t>Crick</t></is></c></row>',
        )
        assert X.read_sheet(str(p)).cell(0, 0) == "Crick"

    def test_number(self, tmp_path):
        p = build_xlsx(tmp_path / "n.xlsx", rows='<row r="1"><c r="A1"><v>451919</v></c></row>')
        assert X.read_sheet(str(p)).cell(0, 0) == "451919"

    def test_cached_formula_result_is_used(self, tmp_path):
        """A formula cell exposes its last computed value, not the formula."""
        p = build_xlsx(
            tmp_path / "f.xlsx",
            rows='<row r="1"><c r="A1" t="str"><f>E2*0.092903</f><v>41985</v></c></row>',
        )
        assert X.read_sheet(str(p)).cell(0, 0) == "41985"

    def test_empty_cells_absent(self, tmp_path):
        p = build_xlsx(tmp_path / "e.xlsx", rows='<row r="1"><c r="A1" t="s"><v>0</v></c></row>', shared=[""])
        sheet = X.read_sheet(str(p))
        assert sheet.cell(0, 0) == ""
        assert sheet.cell(5, 5) == ""

    def test_out_of_range_shared_index_is_ignored(self, tmp_path):
        p = build_xlsx(
            tmp_path / "oob.xlsx",
            rows='<row r="1"><c r="A1" t="s"><v>99</v></c></row>',
            shared=["only"],
        )
        assert X.read_sheet(str(p)).cell(0, 0) == ""


class TestHyperlinks:
    def test_external_hyperlink(self, tmp_path):
        p = build_xlsx(
            tmp_path / "h.xlsx",
            rows='<row r="1"><c r="Z1" t="s"><v>0</v></c></row>',
            shared=["Brochure"],
            hyperlinks=[("Z1", "https://example.com/a.pdf")],
        )
        sheet = X.read_sheet(str(p))
        assert sheet.link(0, 25) == "https://example.com/a.pdf"
        assert sheet.cell(0, 25) == "Brochure"

    def test_ranged_hyperlink_covers_every_cell(self, tmp_path):
        p = build_xlsx(
            tmp_path / "hr.xlsx",
            rows='<row r="1"><c r="Z1" t="s"><v>0</v></c></row>',
            shared=["Brochure"],
            hyperlinks=[("Z1:Z3", "https://example.com/b.pdf")],
        )
        sheet = X.read_sheet(str(p))
        for row in (0, 1, 2):
            assert sheet.link(row, 25) == "https://example.com/b.pdf"

    def test_hyperlink_formula_is_read(self, tmp_path):
        """Some longlists use =HYPERLINK(...) instead of a real hyperlink."""
        p = build_xlsx(
            tmp_path / "hf.xlsx",
            rows=(
                '<row r="1"><c r="Z1" t="str">'
                '<f>HYPERLINK("https://example.com/c.pdf","Brochure")</f>'
                "<v>Brochure</v></c></row>"
            ),
        )
        sheet = X.read_sheet(str(p))
        assert sheet.link(0, 25) == "https://example.com/c.pdf"
        assert sheet.cell(0, 25) == "Brochure"

    def test_no_hyperlink_yields_none(self, tmp_path):
        p = build_xlsx(tmp_path / "nh.xlsx", rows='<row r="1"><c r="A1"><v>1</v></c></row>')
        assert X.read_sheet(str(p)).link(0, 0) is None

    def test_real_hyperlink_wins_over_formula(self, tmp_path):
        """A real relationship is authoritative; the formula is only a fallback."""
        p = build_xlsx(
            tmp_path / "both.xlsx",
            rows=(
                '<row r="1"><c r="Z1" t="str">'
                '<f>HYPERLINK("https://example.com/formula.pdf","B")</f>'
                "<v>B</v></c></row>"
            ),
            hyperlinks=[("Z1", "https://example.com/real.pdf")],
        )
        assert X.read_sheet(str(p)).link(0, 25) == "https://example.com/real.pdf"


class TestSheetSelection:
    def test_named_sheet(self, tmp_path):
        p = build_xlsx(
            tmp_path / "named.xlsx",
            rows='<row r="1"><c r="A1" t="s"><v>0</v></c></row>',
            shared=["x"],
            sheet_name="Longlist",
        )
        assert X.read_sheet(str(p), sheet="Longlist").name == "Longlist"
        assert X.read_sheet(str(p), sheet="longlist").name == "Longlist"

    def test_missing_sheet_names_what_exists(self, tmp_path):
        p = build_xlsx(
            tmp_path / "m.xlsx",
            rows='<row r="1"><c r="A1" t="s"><v>0</v></c></row>',
            shared=["x"],
            sheet_name="Longlist",
        )
        with pytest.raises(X.XlsxError, match="Longlist"):
            X.read_sheet(str(p), sheet="Nope")

    def test_sheet_names(self, tmp_path):
        p = build_xlsx(
            tmp_path / "sn.xlsx",
            rows='<row r="1"><c r="A1" t="s"><v>0</v></c></row>',
            shared=["x"],
            sheet_name="Longlist",
        )
        assert X.sheet_names(str(p)) == ["Longlist"]

    def test_non_xlsx_raises(self, tmp_path):
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"not a zip")
        with pytest.raises(X.XlsxError):
            X.read_sheet(str(bad))


class TestRealLonglist:
    """End-to-end against the reference Temu UK longlist."""

    def test_reads_expected_shape(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        assert sheet.name == "Longlist"
        assert sheet.cell(0, 0) == "No."
        assert sheet.cell(0, 1) == "Address"
        assert sheet.cell(0, 25) == "Brochure"
        assert sheet.cell(1, 1) == "Campus 450 DIRFT, Railport Approach"

    def test_finds_22_brochure_links_on_column_z(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        col_z = [url for (row, col), url in sheet.links.items() if col == 25 and row > 0]
        assert len(col_z) == 22
        assert all(u.startswith("http") for u in col_z)

    def test_map_column_also_has_links(self, real_longlist):
        """Column Y holds Google Maps links - the reason column detection must exclude them."""
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        col_y = [url for (row, col), url in sheet.links.items() if col == 24 and row > 0]
        assert len(col_y) > 0

    def test_multiline_header_is_preserved(self, real_longlist):
        """Headers contain embedded newlines, which column matching must normalise."""
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        assert "\n" in sheet.cell(0, 4)
        assert "Total Size" in sheet.cell(0, 4)
