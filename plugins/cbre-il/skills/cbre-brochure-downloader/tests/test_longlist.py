"""Tests for longlist interpretation."""

from __future__ import annotations

import pytest

from conftest import build_xlsx
from helpers import longlist as L
from helpers import xlsx_links as X


def sheet_from(rows: str, shared=None, hyperlinks=None, tmp_path=None, name="Longlist"):
    path = build_xlsx(tmp_path / "t.xlsx", rows=rows, shared=shared, hyperlinks=hyperlinks, sheet_name=name)
    return X.read_sheet(str(path))


def row(index: int, cells: dict[str, tuple[str, int]]) -> str:
    """Build a <row>. `cells` maps column letter -> (kind, shared index or literal)."""
    out = []
    for col, (kind, value) in cells.items():
        if kind == "s":
            out.append(f'<c r="{col}{index}" t="s"><v>{value}</v></c>')
        else:
            out.append(f'<c r="{col}{index}"><v>{value}</v></c>')
    return f'<row r="{index}">' + "".join(out) + "</row>"


class TestNormalise:
    def test_collapses_embedded_newlines(self):
        assert L.normalise_header("Total Size \n(sq ft)") == "total size (sq ft)"

    def test_handles_none_and_blank(self):
        assert L.normalise_header("") == ""
        assert L.normalise_header("   ") == ""


class TestClassify:
    @pytest.mark.parametrize("url", [
        "https://example.com/a.pdf",
        "https://eu.glp.com/wp-content/uploads/2021/05/62495-GLP-Brochure-web.pdf",
        "https://example.com/A.PDF",
    ])
    def test_pdf(self, url):
        assert L.classify_url(url) == "pdf"

    def test_extensionless_guid_is_probable(self):
        """Azure blob storage serves PDFs from extensionless GUID paths."""
        url = "https://listingsprod.blob.core.windows.net/ourlistings-gbr/2f9f/75984bdd-081e-480d-b806-b280d6deea67"
        assert L.classify_url(url) == "probable-pdf"

    def test_extensionless_hex_hash_is_probable(self):
        assert L.classify_url("https://x.com/assets/d457ece2394b81bae575ce8919859d80") == "probable-pdf"

    def test_extensionless_readable_slug_is_not_pdf(self):
        """A human-readable slug with no extension is a page, not a stored file.

        This is the reference longlist's No. 15 - a CBRE listing page that would
        otherwise have been downloaded as though it were a brochure.
        """
        url = (
            "https://www.cbre.co.uk/property-search/industrial-space/listings/details/"
            "GB-Plus-512817/stoke-439-trentham-lakes-eastern-rise-stoke-on-trent-st4-8wg"
        )
        assert L.classify_url(url) == "not-pdf"

    @pytest.mark.parametrize("url", [
        "https://www.cbre.co.uk/property-search/industrial-space/listings/details/GB-512817/stoke-439",
        "https://example.com/page.html",
        "https://example.com/thing.aspx",
        "https://example.com/file.xlsx",
        "https://example.com/view?id=7",
        "https://www.google.com/maps/place/Crick",
    ])
    def test_not_pdf(self, url):
        assert L.classify_url(url) == "not-pdf"

    def test_landing_page_with_trailing_slug_is_not_pdf(self):
        """A multi-segment path ending in a slug with a dot is a page, not a file."""
        assert L.classify_url("https://example.com/a/b/c.aspx") == "not-pdf"

    def test_empty(self):
        assert L.classify_url("") == "missing"


class TestMapDetection:
    @pytest.mark.parametrize("url", [
        "https://www.google.com/maps/place/Crick",
        "https://goo.gl/maps/abc",
        "https://maps.app.goo.gl/xyz",
        "https://www.openstreetmap.org/#map=15/52.3/-1.1",
    ])
    def test_recognised(self, url):
        assert L.is_map_url(url)

    def test_pdf_is_not_a_map(self):
        assert not L.is_map_url("https://example.com/brochure.pdf")


class TestSlugify:
    def test_basic(self):
        assert L.slugify("Campus 450 DIRFT, Railport Approach") == "Campus-450-DIRFT-Railport-Approach"

    def test_transliterates(self):
        assert L.slugify("Zaragoza Almussafes Nave 3") == "Zaragoza-Almussafes-Nave-3"
        assert L.slugify("Gdansk Port Polnocny") == "Gdansk-Port-Polnocny"

    def test_strips_punctuation_runs(self):
        assert L.slugify("Unit 2 -- East Midlands (EMDC)") == "Unit-2-East-Midlands-EMDC"

    def test_caps_without_splitting_a_word(self):
        out = L.slugify("A" * 20 + " " + "B" * 20 + " " + "C" * 40, limit=55)
        assert len(out) <= 55
        assert not out.endswith("-")
        assert "C" not in out

    def test_empty(self):
        assert L.slugify("") == ""
        assert L.slugify("!!!") == ""


class TestPredictedFilename:
    def test_plain(self):
        assert L.predicted_filename("https://f.tlcollect.com/fr2/526/36389/Wayfair_Lutterworth.pdf") == "Wayfair_Lutterworth.pdf"

    def test_url_decoded(self):
        assert L.predicted_filename("https://x.com/a%20b%20c.pdf") == "a b c.pdf"

    def test_extensionless(self):
        assert L.predicted_filename("https://x.com/ourlistings/75984bdd-081e") == "75984bdd-081e"

    def test_empty_path(self):
        assert L.predicted_filename("https://x.com/") == "download"


class TestHeaderRow:
    def test_first_row(self, tmp_path):
        rows = row(1, {"A": ("s", 0), "B": ("s", 1), "Z": ("s", 2)}) + row(2, {"A": ("n", 1), "B": ("s", 3)})
        sheet = sheet_from(rows, shared=["No.", "Address", "Brochure", "Crick"], tmp_path=tmp_path)
        assert L.find_header_row(sheet) == 0

    def test_skips_a_title_row(self, tmp_path):
        """A client name above the real header must not be mistaken for it."""
        rows = (
            row(1, {"A": ("s", 0)})
            + row(2, {"A": ("s", 1), "B": ("s", 2), "C": ("s", 3), "D": ("s", 4)})
            + row(3, {"A": ("n", 1), "B": ("s", 5)})
        )
        sheet = sheet_from(
            rows,
            shared=["Warehouse Availability - Temu UK", "No.", "Address", "Town", "Brochure", "Crick"],
            tmp_path=tmp_path,
        )
        assert L.find_header_row(sheet) == 1


class TestBrochureColumn:
    def test_found_by_header_name(self, tmp_path):
        rows = row(1, {"A": ("s", 0), "Z": ("s", 1)}) + row(2, {"A": ("n", 1), "Z": ("s", 2)})
        sheet = sheet_from(
            rows,
            shared=["Address", "Brochure", "Brochure"],
            hyperlinks=[("Z2", "https://x.com/a.pdf")],
            tmp_path=tmp_path,
        )
        col, how = L.find_brochure_column(sheet, 0)
        assert col == 25
        assert how == "header name"

    def test_multiline_header_name_matches(self, tmp_path):
        rows = row(1, {"A": ("s", 0), "Z": ("s", 1)}) + row(2, {"A": ("n", 1)})
        sheet = sheet_from(rows, shared=["Address", "Brochure\nLink"], tmp_path=tmp_path)
        col, how = L.find_brochure_column(sheet, 0)
        assert col == 25
        assert how == "header name"

    def test_fallback_prefers_pdf_links(self, tmp_path):
        """With no usable header, the column full of PDFs wins."""
        rows = (
            row(1, {"A": ("s", 0), "B": ("s", 1), "C": ("s", 2)})
            + row(2, {"A": ("n", 1)})
            + row(3, {"A": ("n", 2)})
        )
        sheet = sheet_from(
            rows,
            shared=["Address", "Docs", "Other"],
            hyperlinks=[
                ("B2", "https://x.com/one.pdf"),
                ("B3", "https://x.com/two.pdf"),
                ("C2", "https://x.com/page.html"),
            ],
            tmp_path=tmp_path,
        )
        col, how = L.find_brochure_column(sheet, 0)
        assert col == 1
        assert how == "most PDF hyperlinks"

    def test_fallback_must_not_pick_the_map_column(self, tmp_path):
        """The regression this guard exists for: a Map column outnumbers the brochures."""
        rows = (
            row(1, {"A": ("s", 0), "B": ("s", 1), "C": ("s", 2)})
            + row(2, {"A": ("n", 1)})
            + row(3, {"A": ("n", 2)})
            + row(4, {"A": ("n", 3)})
        )
        sheet = sheet_from(
            rows,
            shared=["Address", "Location", "Docs"],
            hyperlinks=[
                ("B2", "https://www.google.com/maps/place/A"),
                ("B3", "https://www.google.com/maps/place/B"),
                ("B4", "https://www.google.com/maps/place/C"),
                ("C2", "https://x.com/only-one.pdf"),
            ],
            tmp_path=tmp_path,
        )
        col, _ = L.find_brochure_column(sheet, 0)
        assert col == 2, "map links must be excluded from the density fallback"

    def test_none_found(self, tmp_path):
        rows = row(1, {"A": ("s", 0)}) + row(2, {"A": ("n", 1)})
        sheet = sheet_from(rows, shared=["Address"], tmp_path=tmp_path)
        col, how = L.find_brochure_column(sheet, 0)
        assert col is None
        assert how == "not found"


class TestExtract:
    def _sheet(self, tmp_path, hyperlinks, extra_rows=""):
        rows = (
            row(1, {"A": ("s", 0), "B": ("s", 1), "C": ("s", 2), "Z": ("s", 3)})
            + row(2, {"A": ("n", 1), "B": ("s", 4), "C": ("s", 6), "Z": ("s", 3)})
            + row(3, {"A": ("n", 2), "B": ("s", 5), "C": ("s", 7), "Z": ("s", 3)})
            + extra_rows
        )
        return sheet_from(
            rows,
            shared=["No.", "Address", "Town", "Brochure", "Campus 450 DIRFT", "Wayfair Lutterworth", "Crick", "Leicestershire"],
            hyperlinks=hyperlinks,
            tmp_path=tmp_path,
        )

    def test_basic_extraction(self, tmp_path):
        sheet = self._sheet(tmp_path, [("Z2", "https://x.com/a.pdf"), ("Z3", "https://x.com/b.pdf")])
        result = L.extract(sheet)
        assert len(result.properties) == 2
        assert len(result.downloads) == 2
        assert result.properties[0].address == "Campus 450 DIRFT"
        assert result.properties[0].town == "Crick"
        assert result.properties[0].number == "1"
        assert result.columns["brochure"] == "Z"

    def test_target_filenames(self, tmp_path):
        sheet = self._sheet(tmp_path, [("Z2", "https://x.com/a.pdf"), ("Z3", "https://x.com/b.pdf")])
        result = L.extract(sheet)
        assert result.downloads[0].target == "01_Campus-450-DIRFT_Crick.pdf"
        assert result.downloads[1].target == "02_Wayfair-Lutterworth_Leicestershire.pdf"

    def test_town_not_repeated_when_already_in_address(self, tmp_path):
        rows = (
            row(1, {"A": ("s", 0), "B": ("s", 1), "C": ("s", 2), "Z": ("s", 3)})
            + row(2, {"A": ("n", 1), "B": ("s", 4), "C": ("s", 5), "Z": ("s", 3)})
        )
        sheet = sheet_from(
            rows,
            shared=["No.", "Address", "Town", "Brochure", "Wayfair Lutterworth", "Lutterworth"],
            hyperlinks=[("Z2", "https://x.com/a.pdf")],
            tmp_path=tmp_path,
        )
        result = L.extract(sheet)
        assert result.downloads[0].target == "01_Wayfair-Lutterworth.pdf"

    def test_shared_url_deduplicates(self, tmp_path):
        """Rows 9 and 10 of the reference longlist share one file."""
        same = "https://panattoni.co.uk/x/Panattoni-Park-Milton-Keynes_PC_Brochure.pdf"
        sheet = self._sheet(tmp_path, [("Z2", same), ("Z3", same)])
        result = L.extract(sheet)
        assert len(result.properties) == 2
        assert len(result.downloads) == 1
        download = result.downloads[0]
        assert download.numbers == ["1", "2"]
        assert download.target.startswith("01+02_")
        assert any("share one brochure URL" in w for w in result.warnings)

    def test_not_pdf_is_flagged_and_excluded(self, tmp_path):
        sheet = self._sheet(
            tmp_path,
            [("Z2", "https://x.com/a.pdf"), ("Z3", "https://www.cbre.co.uk/property-search/details/stoke-439")],
        )
        result = L.extract(sheet)
        assert len(result.flagged) == 1
        assert result.flagged[0].kind == "not-pdf"
        assert len(result.automatable) == 1
        assert any("not a PDF" in w for w in result.warnings)

    def test_missing_link_is_recorded_not_dropped(self, tmp_path):
        sheet = self._sheet(tmp_path, [("Z2", "https://x.com/a.pdf")])
        result = L.extract(sheet)
        assert len(result.properties) == 2
        assert len(result.downloads) == 1
        assert result.properties[1].url is None
        assert result.properties[1].kind == "missing"
        assert any("no brochure link" in w for w in result.warnings)

    def test_same_name_different_row_numbers_do_not_collide(self, tmp_path):
        """Identically-named properties are separated by their row numbers alone."""
        rows = (
            row(1, {"A": ("s", 0), "B": ("s", 1), "C": ("s", 2), "Z": ("s", 3)})
            + row(2, {"A": ("n", 1), "B": ("s", 4), "C": ("s", 5), "Z": ("s", 3)})
            + row(3, {"A": ("n", 2), "B": ("s", 4), "C": ("s", 5), "Z": ("s", 3)})
        )
        sheet = sheet_from(
            rows,
            shared=["No.", "Address", "Town", "Brochure", "Unit 1", "Rugby"],
            hyperlinks=[("Z2", "https://x.com/a.pdf"), ("Z3", "https://x.com/b.pdf")],
            tmp_path=tmp_path,
        )
        names = [d.target for d in L.extract(sheet).downloads]
        assert names == ["01_Unit-1_Rugby.pdf", "02_Unit-1_Rugby.pdf"]

    def test_duplicate_numbering_gets_a_suffix(self, tmp_path):
        """A badly numbered sheet (two rows both "1") still yields unique filenames."""
        rows = (
            row(1, {"A": ("s", 0), "B": ("s", 1), "C": ("s", 2), "Z": ("s", 3)})
            + row(2, {"A": ("n", 1), "B": ("s", 4), "C": ("s", 5), "Z": ("s", 3)})
            + row(3, {"A": ("n", 1), "B": ("s", 4), "C": ("s", 5), "Z": ("s", 3)})
        )
        sheet = sheet_from(
            rows,
            shared=["No.", "Address", "Town", "Brochure", "Unit 1", "Rugby"],
            hyperlinks=[("Z2", "https://x.com/a.pdf"), ("Z3", "https://x.com/b.pdf")],
            tmp_path=tmp_path,
        )
        names = [d.target for d in L.extract(sheet).downloads]
        assert len(set(n.lower() for n in names)) == 2
        assert names[1].endswith("-2.pdf")

    def test_raises_when_no_brochure_column(self, tmp_path):
        rows = row(1, {"A": ("s", 0), "B": ("s", 1)}) + row(2, {"A": ("n", 1), "B": ("s", 2)})
        sheet = sheet_from(rows, shared=["No.", "Address", "Unit 1"], tmp_path=tmp_path)
        with pytest.raises(L.LonglistError, match="no brochure column"):
            L.extract(sheet)


class TestRealLonglist:
    """End-to-end against the reference Temu UK longlist."""

    def test_shape(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        result = L.extract(sheet)
        assert result.header_row == 0
        assert result.columns["brochure"] == "Z"
        assert result.columns["brochure_found_by"] == "header name"
        assert result.columns["number"] == "A"
        assert result.columns["address"] == "B"
        assert result.columns["town"] == "C"
        assert len(result.properties) == 22

    def test_dedupes_to_21_downloads(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        result = L.extract(sheet)
        assert len(result.downloads) == 21
        shared = [d for d in result.downloads if len(d.properties) > 1]
        assert len(shared) == 1
        assert shared[0].numbers == ["9", "10"]

    def test_stoke_439_is_flagged(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        result = L.extract(sheet)
        assert len(result.flagged) == 1
        assert "stoke" in result.flagged[0].url.lower()
        assert result.flagged[0].numbers == ["15"]
        assert len(result.automatable) == 20

    def test_extensionless_urls_are_probable_not_rejected(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        result = L.extract(sheet)
        probable = [d for d in result.downloads if d.kind == "probable-pdf"]
        assert len(probable) == 2
        assert all("blob.core.windows.net" in d.url for d in probable)

    def test_target_filenames_are_unique_and_ordered(self, real_longlist):
        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        result = L.extract(sheet)
        names = [d.target for d in result.downloads]
        assert len(set(n.lower() for n in names)) == len(names)
        assert names[0] == "01_Campus-450-DIRFT-Railport-Approach_Crick.pdf"
        assert all(n[:2].isdigit() for n in names)

    def test_payload_is_json_serialisable(self, real_longlist):
        import json

        sheet = X.read_sheet(str(real_longlist), sheet="Longlist")
        result = L.extract(sheet)
        data = L.payload(result, client="Temu UK", source=real_longlist.name)
        text = json.dumps(data)
        assert '"</script>' not in text
        assert data["counts"] == {
            "properties": 22,
            "downloads": 21,
            "automatable": 20,
            "flagged": 1,
            "missing_links": 0,
        }
