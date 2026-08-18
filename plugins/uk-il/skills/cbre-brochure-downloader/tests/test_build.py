"""Tests for payload injection and the build CLI."""

from __future__ import annotations

import json
import re

import pytest

from conftest import build_xlsx
from helpers import build as B
from helpers import longlist as L
from helpers import render as R
from helpers import xlsx_links as X


def make_longlist_xlsx(tmp_path, url="https://x.com/a.pdf", address="Campus 450 DIRFT"):
    rows = (
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c><c r="Z1" t="s"><v>3</v></c>'
        "</row>"
        '<row r="2">'
        '<c r="A2"><v>1</v></c><c r="B2" t="s"><v>4</v></c>'
        '<c r="C2" t="s"><v>5</v></c><c r="Z2" t="s"><v>3</v></c>'
        "</row>"
    )
    return build_xlsx(
        tmp_path / "Warehouse Availability - Acme Ltd.xlsx",
        rows=rows,
        shared=["No.", "Address", "Town", "Brochure", address, "Crick"],
        hyperlinks=[("Z2", url)],
        sheet_name="Longlist",
    )


class TestRender:
    def _payload(self, tmp_path, **kw):
        path = make_longlist_xlsx(tmp_path, **kw)
        sheet = X.read_sheet(str(path), sheet="Longlist")
        return L.payload(L.extract(sheet), client="Acme Ltd", source=path.name)

    def test_writes_html_with_payload(self, tmp_path):
        data = self._payload(tmp_path)
        out = R.render(data, client="Acme Ltd", out_path=tmp_path / "tool.html")
        html = out.read_text(encoding="utf-8")
        assert "__PAYLOAD__" not in html
        assert "__CLIENT__" not in html
        assert "Acme Ltd" in html

    def test_payload_parses_back_out_of_the_script_tag(self, tmp_path):
        """The embedded JSON must survive escaping and still be valid JSON."""
        data = self._payload(tmp_path)
        out = R.render(data, client="Acme Ltd", out_path=tmp_path / "tool.html")
        html = out.read_text(encoding="utf-8")
        m = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S)
        assert m, "payload script tag not found"
        assert json.loads(m.group(1))["items"][0]["url"] == "https://x.com/a.pdf"

    def test_script_close_in_data_cannot_break_out(self, tmp_path):
        """A spreadsheet containing </script> must not terminate the script element."""
        data = self._payload(tmp_path, address="Evil </script><script>alert(1)</script> Unit")
        out = R.render(data, client="Acme Ltd", out_path=tmp_path / "tool.html")
        html = out.read_text(encoding="utf-8")
        body = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
        assert "</script>" not in body
        assert "\\u003c" in body
        assert "alert(1)" in json.loads(body)["items"][0]["label"]

    def test_client_name_is_html_escaped(self, tmp_path):
        data = self._payload(tmp_path)
        out = R.render(data, client='Acme <img src=x onerror=alert(1)>', out_path=tmp_path / "tool.html")
        html = out.read_text(encoding="utf-8")
        assert "<img src=x" not in html
        assert "&lt;img" in html

    def test_missing_placeholder_raises(self, tmp_path):
        tpl = tmp_path / "bad.html"
        tpl.write_text("<html>nothing here</html>", encoding="utf-8")
        with pytest.raises(ValueError, match="__PAYLOAD__"):
            R.render({}, client="x", out_path=tmp_path / "o.html", template=tpl)


class TestDownloadMechanism:
    """Guards the download trigger, which took three attempts to get right.

    A browser tab is allowed exactly one download. What fails afterwards varies and is
    never obvious:

    1. Hidden <iframe> — the built-in PDF viewer claims any PDF loaded into a sub-frame,
       so the brochure rendered invisibly and nothing was saved. The "Download PDFs"
       setting cannot help, because it governs top-level navigations only. Confirmed by
       observing an iframe load pull in Chrome's PDF viewer extension.
    2. One reused window, fire-and-forget — the browser's multiple-downloads prompt
       blocked files 2..n while the loop raced past them, so only the first arrived.
    3. One reused window with a pause for that prompt — the second file silently
       degraded to *rendering* in the viewer, with no prompt shown at all.

    The working mechanism is a fresh top-level window per file, never reused, so each
    download gets its own allowance. Its one failure mode — a blocked popup — is
    detectable via a null return from window.open, unlike a gated download.
    """

    @pytest.fixture
    def template(self):
        return R.TEMPLATE.read_text(encoding="utf-8")

    def test_no_iframe_is_created_for_downloads(self, template):
        assert 'createElement("iframe")' not in template
        assert "createElement('iframe')" not in template
        assert 'el("iframe")' not in template

    def test_opens_a_fresh_window_per_file(self, template):
        assert "function openFresh" in template
        assert 'window.open(url, "_blank"' in template

    def test_never_reuses_one_window_for_several_downloads(self, template):
        """Reuse is the defect that broke attempts 2 and 3."""
        assert "openWorker" not in template
        assert "driveTo" not in template
        assert "worker.location.href" not in template

    def test_detects_a_blocked_popup(self, template):
        assert "popup blocked" in template.lower()
        assert 'id="popup-note"' in template
        assert "blocked = true" in template

    def test_records_why_the_earlier_mechanisms_failed(self, template):
        """The reasoning must stay next to the code, or it will be undone later."""
        assert "sub-frame" in template
        assert "Do not reintroduce an iframe here." in template
        assert "ONE WINDOW PER FILE, never reused" in template

    def test_closes_each_window_after_the_download_starts(self, template):
        assert "CLOSE_AFTER_MS" in template
        assert "w.close()" in template

    def test_test_button_explains_how_to_read_the_outcome(self, template):
        """An early bug was a diagnostic that could not report; keep it explicit."""
        assert "stays blank" in template
        assert "appears on screen" in template

    def test_does_not_claim_downloads_are_confirmed(self, template):
        assert "sent</em> rather than" in template

    def test_offers_a_click_through_path_needing_no_permission(self, template):
        """The permission must be optional, because it is the only guaranteed path."""
        assert 'id="btn-next"' in template
        assert "Save next brochure" in template
        assert "nothing to allow" in template
        assert 'textContent: "Save"' in template

    def test_click_through_advances_by_itself(self, template):
        assert "function refreshNext" in template
        assert "left)" in template

    def test_automated_run_is_offered_separately(self, template):
        assert "Start automated run" in template
        assert "allow popups" in template
        assert "address bar" in template

    def test_drop_does_not_depend_on_webkit_get_as_entry(self, template):
        """webkitGetAsEntry() always exists in Chromium but can return null.

        Keying the whole drop branch on the method existing meant a plain file drop
        collected nothing and failed silently, while the file picker worked. The plain
        dataTransfer.files list must always be read, and used whenever no folder was
        dropped.
        """
        assert "Array.from(e.dataTransfer.files)" in template
        assert "entries.some(en => en.isDirectory)" in template
        assert "files = plainFiles" in template

    def test_drop_reports_when_it_collected_nothing(self, template):
        assert "nothing readable in that drop" in template

    def test_does_not_download_the_test_brochure_twice(self, template):
        """A second copy lands as "… (1).pdf" and step 3 reports it as unrecognised."""
        assert "testedId" in template
        assert "i.id !== testedId" in template


class TestInferClient:
    @pytest.mark.parametrize("name,expected", [
        ("Warehouse Availability - Temu UK (6).xlsx", "Temu UK"),
        ("Warehouse Availability - Temu UK.xlsx", "Temu UK"),
        ("Longlist.xlsx", "Longlist"),
        ("Options - Acme Ltd (12).xlsx", "Acme Ltd"),
    ])
    def test_infer(self, tmp_path, name, expected):
        assert B.infer_client(tmp_path / name) == expected


class TestCli:
    def test_end_to_end(self, tmp_path, capsys):
        xlsx = make_longlist_xlsx(tmp_path)
        out = tmp_path / "out"
        code = B.main(["--xlsx", str(xlsx), "--out", str(out)])
        assert code == 0
        assert (out / "brochure-downloader.html").exists()
        assert (out / "gaps.md").exists()
        printed = capsys.readouterr().out
        assert "client:      Acme Ltd" in printed
        assert "properties:  1" in printed

    def test_missing_file_exits_2(self, tmp_path, capsys):
        assert B.main(["--xlsx", str(tmp_path / "nope.xlsx")]) == 2
        assert "no such file" in capsys.readouterr().err

    def test_no_brochure_column_exits_3(self, tmp_path, capsys):
        rows = (
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>'
        )
        xlsx = build_xlsx(tmp_path / "x.xlsx", rows=rows, shared=["No.", "Address", "Unit 1"])
        assert B.main(["--xlsx", str(xlsx), "--out", str(tmp_path / "o")]) == 3
        assert "no brochure column" in capsys.readouterr().err

    def test_named_sheet_that_does_not_exist_exits_2(self, tmp_path, capsys):
        xlsx = make_longlist_xlsx(tmp_path)
        assert B.main(["--xlsx", str(xlsx), "--sheet", "Nope", "--out", str(tmp_path / "o")]) == 2
        assert "no sheet named" in capsys.readouterr().err

    def test_gaps_records_flagged_link(self, tmp_path):
        xlsx = make_longlist_xlsx(tmp_path, url="https://www.cbre.co.uk/property-search/details/stoke-439")
        out = tmp_path / "out"
        assert B.main(["--xlsx", str(xlsx), "--out", str(out)]) == 0
        gaps = (out / "gaps.md").read_text(encoding="utf-8")
        assert "Not a direct PDF link" in gaps
        assert "stoke-439" in gaps


class TestCliOnRealLonglist:
    def test_real_longlist(self, real_longlist, tmp_path, capsys):
        out = tmp_path / "out"
        assert B.main(["--xlsx", str(real_longlist), "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "client:      Temu UK" in printed
        assert "properties:  22" in printed
        assert "downloads:   21 distinct files" in printed
        assert "automatable: 20" in printed

        html = (out / "brochure-downloader.html").read_text(encoding="utf-8")
        body = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
        data = json.loads(body)
        assert len(data["items"]) == 21
        assert data["client"] == "Temu UK"
        targets = [i["target"] for i in data["items"]]
        assert "09+10_MK345-Panattoni-Park_Milton-Keynes.pdf" in targets
        assert len(set(targets)) == 21
