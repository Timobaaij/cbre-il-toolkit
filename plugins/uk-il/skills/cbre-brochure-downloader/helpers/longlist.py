"""Turn a worksheet into an ordered list of properties with brochure URLs.

Everything here is deliberately conservative: a URL that does not look like a PDF is
flagged rather than assumed, and a row without a link is recorded as a gap rather than
dropped. The downstream skill builds a Source Ledger from these filenames, so a wrong
guess here becomes a wrong provenance claim there.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from .xlsx_links import Sheet, index_to_col

# Header names that identify the brochure column, checked after normalisation.
BROCHURE_HEADERS = (
    "brochure",
    "brochure link",
    "brochure url",
    "brochure (pdf)",
    "brochure pdf",
    "pdf",
    "pdf link",
    "particulars",
    "marketing brochure",
    "marketing particulars",
    "brochure/particulars",
)

NUMBER_HEADERS = ("no.", "no", "#", "ref", "ref.", "id", "item", "property no.", "no. ")
ADDRESS_HEADERS = ("address", "property", "property name", "name", "site", "scheme", "building", "unit")
TOWN_HEADERS = ("town", "city", "town/city", "location", "locality", "town / city")

# Hosts and paths that mean "this is a map link, not a document".
MAP_MARKERS = (
    "google.com/maps",
    "goo.gl/maps",
    "maps.app.goo.gl",
    "bing.com/maps",
    "openstreetmap.org",
    "what3words.com",
    "maps.apple.com",
)

# Extensions that are definitely not a brochure PDF.
NON_PDF_EXTENSIONS = (
    ".htm", ".html", ".aspx", ".php", ".jsp", ".xlsx", ".xls", ".csv",
    ".doc", ".docx", ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".zip",
)

MAX_SLUG = 55

# An extensionless path may be a stored file or a web page. The discriminator is whether
# the last segment is an opaque identifier (Azure blob storage serves PDFs from GUID
# paths) or a human-readable slug (which is what a listing page looks like).
_UUID_SEGMENT = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX_SEGMENT = re.compile(r"^[0-9a-fA-F]{16,}$")


@dataclass
class Property:
    """One row of the longlist."""

    row: int                    # zero-based sheet row
    number: str                 # as printed in the sheet ("1", "12a")
    sort_key: int               # numeric part, for ordering and zero-padding
    address: str
    town: str
    url: str | None
    kind: str = "pdf"           # pdf | probable-pdf | not-pdf | missing
    note: str = ""

    @property
    def label(self) -> str:
        return self.address or self.town or f"Row {self.row + 1}"


@dataclass
class Download:
    """One file to fetch. Several properties may share it."""

    index: int
    url: str
    kind: str
    properties: list[Property]
    predicted: str              # basename the browser will probably save
    target: str                 # filename we rename it to

    @property
    def numbers(self) -> list[str]:
        return [p.number for p in self.properties]

    @property
    def label(self) -> str:
        return self.properties[0].label

    @property
    def town(self) -> str:
        return self.properties[0].town


@dataclass
class Longlist:
    """The interpreted sheet."""

    sheet_name: str
    properties: list[Property] = field(default_factory=list)
    downloads: list[Download] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)   # role -> column letter
    header_row: int = 0

    @property
    def flagged(self) -> list[Download]:
        """Downloads that need a human decision before they can be trusted."""
        return [d for d in self.downloads if d.kind == "not-pdf"]

    @property
    def automatable(self) -> list[Download]:
        return [d for d in self.downloads if d.kind != "not-pdf"]


class LonglistError(Exception):
    """The sheet could not be interpreted as a longlist."""


def normalise_header(value: str) -> str:
    """Collapse case, embedded newlines and runs of whitespace.

    Real longlist headers look like "Total Size \n(sq ft)", so exact matching fails
    without this.
    """
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip().lower()


def is_map_url(url: str) -> bool:
    low = (url or "").lower()
    return any(marker in low for marker in MAP_MARKERS)


def looks_like_pdf(url: str) -> bool:
    path = urlsplit(url or "").path.lower()
    return path.endswith(".pdf")


def _looks_opaque(segment: str) -> bool:
    """True for a GUID or long hex hash - the shape of a stored file, not a page slug."""
    return bool(_UUID_SEGMENT.match(segment) or _HEX_SEGMENT.match(segment))


def classify_url(url: str) -> str:
    """Classify a brochure URL.

    Returns one of:
      pdf           - path ends .pdf
      probable-pdf  - no extension, but an opaque identifier, so probably a stored file
      not-pdf       - anything else; flagged for a human rather than downloaded blind
      missing       - no URL

    Erring toward not-pdf is deliberate. A flagged URL is still shown to the user with
    its link, whereas a landing page downloaded as though it were a brochure would put
    an HTML file into the set the downstream skill treats as source evidence.
    """
    if not url:
        return "missing"
    split = urlsplit(url)
    path = split.path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if any(path.endswith(ext) for ext in NON_PDF_EXTENSIONS):
        return "not-pdf"
    if is_map_url(url):
        return "not-pdf"
    if split.query:
        return "not-pdf"
    last = posixpath.basename(path.rstrip("/"))
    if not last or "." in last:
        return "not-pdf"
    return "probable-pdf" if _looks_opaque(last) else "not-pdf"


def predicted_filename(url: str) -> str:
    """The basename a browser will most likely save this URL as.

    Used only to match dropped files back to properties, so it is allowed to be
    approximate - the matcher tries several tolerance tiers on top of it.
    """
    path = urlsplit(url or "").path
    name = unquote(posixpath.basename(path.rstrip("/")))
    return name or "download"


def slugify(value: str, limit: int = MAX_SLUG) -> str:
    """ASCII, alphanumerics and single hyphens, capped without splitting a word."""
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-") or text[:limit].strip("-")


def _numeric(value: str) -> int | None:
    m = re.search(r"\d+", value or "")
    return int(m.group()) if m else None


def find_header_row(sheet: Sheet, scan: int = 10) -> int:
    """The row with the most distinct non-empty text cells in the first `scan` rows.

    Longlists sometimes carry a title or client name above the real header.
    """
    best_row, best_score = 0, -1
    for row in range(min(scan, max(sheet.max_row, 1))):
        values = [v for v in sheet.row_values(row) if v]
        # Numeric-looking rows are data, not headers.
        wordy = [v for v in values if not re.fullmatch(r"[\d\s.,%-]+", v)]
        score = len(set(normalise_header(v) for v in wordy))
        if score > best_score:
            best_row, best_score = row, score
    return best_row


def _column_by_header(sheet: Sheet, header_row: int, candidates: tuple[str, ...]) -> int | None:
    """Exact normalised match first, then prefix match."""
    headers = {}
    for col in range(sheet.max_col):
        name = normalise_header(sheet.cell(header_row, col))
        if name and col not in headers:
            headers[col] = name

    for want in candidates:
        for col, name in headers.items():
            if name == want:
                return col
    for want in candidates:
        for col, name in headers.items():
            if name.startswith(want):
                return col
    return None


def find_brochure_column(sheet: Sheet, header_row: int) -> tuple[int | None, str]:
    """Locate the brochure column. Returns (column index, how it was found).

    Order matters. The header name is trusted first. The density fallbacks explicitly
    exclude map links, because a longlist's Map column is full of hyperlinks and would
    otherwise win.
    """
    by_name = _column_by_header(sheet, header_row, BROCHURE_HEADERS)
    if by_name is not None:
        return by_name, "header name"

    pdf_counts: dict[int, int] = {}
    link_counts: dict[int, int] = {}
    for (row, col), url in sheet.links.items():
        if row <= header_row or is_map_url(url):
            continue
        link_counts[col] = link_counts.get(col, 0) + 1
        if looks_like_pdf(url):
            pdf_counts[col] = pdf_counts.get(col, 0) + 1

    if pdf_counts:
        best = max(pdf_counts.items(), key=lambda kv: (kv[1], -kv[0]))
        return best[0], "most PDF hyperlinks"
    if link_counts:
        best = max(link_counts.items(), key=lambda kv: (kv[1], -kv[0]))
        return best[0], "most hyperlinks (non-map)"
    return None, "not found"


def _find_text_column(sheet: Sheet, header_row: int, skip: set[int]) -> int | None:
    """First column below the header holding mostly non-numeric text."""
    for col in range(sheet.max_col):
        if col in skip:
            continue
        values = [sheet.cell(r, col) for r in range(header_row + 1, min(header_row + 12, sheet.max_row))]
        values = [v for v in values if v]
        if len(values) >= 2 and sum(1 for v in values if not re.fullmatch(r"[\d\s.,%-]+", v)) >= len(values) - 1:
            return col
    return None


def extract(sheet: Sheet, sheet_label: str | None = None) -> Longlist:
    """Interpret a worksheet into properties and deduplicated downloads."""
    result = Longlist(sheet_name=sheet_label or sheet.name)
    result.header_row = find_header_row(sheet)
    header_row = result.header_row

    brochure_col, how = find_brochure_column(sheet, header_row)
    if brochure_col is None:
        seen = [sheet.cell(header_row, c) for c in range(sheet.max_col)]
        seen = [s for s in seen if s]
        raise LonglistError(
            "no brochure column found. Headers seen: "
            + (", ".join(seen[:20]) if seen else "(none)")
        )
    result.columns["brochure"] = index_to_col(brochure_col)
    result.columns["brochure_found_by"] = how

    number_col = _column_by_header(sheet, header_row, NUMBER_HEADERS)
    address_col = _column_by_header(sheet, header_row, ADDRESS_HEADERS)
    town_col = _column_by_header(sheet, header_row, TOWN_HEADERS)

    if address_col is None:
        address_col = _find_text_column(sheet, header_row, skip={brochure_col, number_col or -1})
        if address_col is not None:
            result.warnings.append(
                f"No address-like header found; using column {index_to_col(address_col)} "
                f"({sheet.cell(header_row, address_col) or 'unnamed'}) for property names."
            )

    for role, col in (("number", number_col), ("address", address_col), ("town", town_col)):
        if col is not None:
            result.columns[role] = index_to_col(col)

    # Rows are data if they carry an address or a brochure link.
    ordinal = 0
    for row in range(header_row + 1, sheet.max_row):
        address = sheet.cell(row, address_col) if address_col is not None else ""
        url = sheet.link(row, brochure_col)
        if not address and not url:
            continue
        ordinal += 1

        printed = sheet.cell(row, number_col) if number_col is not None else ""
        printed = printed.strip()
        if printed and printed.replace(".0", "").isdigit():
            printed = printed.replace(".0", "")
        number = printed or str(ordinal)

        prop = Property(
            row=row,
            number=number,
            sort_key=_numeric(number) or ordinal,
            address=re.sub(r"\s+", " ", address).strip(),
            town=re.sub(r"\s+", " ", sheet.cell(row, town_col) if town_col is not None else "").strip(),
            url=url,
            kind=classify_url(url) if url else "missing",
        )
        if url and is_map_url(url):
            prop.note = "link is a map, not a brochure"
        result.properties.append(prop)

    if not result.properties:
        raise LonglistError("no data rows found below the header")

    for prop in result.properties:
        if prop.url is None:
            result.warnings.append(f"No. {prop.number} ({prop.label}): no brochure link in the sheet.")

    result.downloads = _build_downloads(result.properties)
    for download in result.downloads:
        if download.kind == "not-pdf":
            result.warnings.append(
                f"No. {'+'.join(download.numbers)} ({download.label}): link is not a PDF "
                f"({download.url}) - excluded from the automated run."
            )
        if len(download.properties) > 1:
            result.warnings.append(
                f"Nos. {'+'.join(download.numbers)} share one brochure URL - "
                f"downloaded once as {download.target}."
            )
    return result


def _build_downloads(properties: list[Property]) -> list[Download]:
    """Group properties by URL, then assign unique target filenames."""
    order: list[str] = []
    grouped: dict[str, list[Property]] = {}
    for prop in properties:
        if not prop.url:
            continue
        if prop.url not in grouped:
            grouped[prop.url] = []
            order.append(prop.url)
        grouped[prop.url].append(prop)

    width = max((len(str(p.sort_key)) for p in properties), default=2)
    width = max(width, 2)

    downloads: list[Download] = []
    used: set[str] = set()

    for index, url in enumerate(order, start=1):
        props = grouped[url]
        prefix = "+".join(str(p.sort_key).zfill(width) for p in props)

        first = props[0]
        slug = slugify(first.address)
        town_slug = slugify(first.town, limit=24)
        if town_slug and town_slug.lower() not in slug.lower():
            slug = f"{slug}_{town_slug}" if slug else town_slug
        if not slug:
            slug = "brochure"

        target = f"{prefix}_{slug}.pdf"
        if target.lower() in used:
            suffix = 2
            while f"{prefix}_{slug}-{suffix}.pdf".lower() in used:
                suffix += 1
            target = f"{prefix}_{slug}-{suffix}.pdf"
        used.add(target.lower())

        downloads.append(
            Download(
                index=index,
                url=url,
                kind=props[0].kind,
                properties=props,
                predicted=predicted_filename(url),
                target=target,
            )
        )
    return downloads


def payload(longlist: Longlist, client: str, source: str) -> dict:
    """The JSON the HTML tool is built around."""
    return {
        "client": client,
        "source": source,
        "sheet": longlist.sheet_name,
        "columns": longlist.columns,
        "counts": {
            "properties": len(longlist.properties),
            "downloads": len(longlist.downloads),
            "automatable": len(longlist.automatable),
            "flagged": len(longlist.flagged),
            "missing_links": sum(1 for p in longlist.properties if not p.url),
        },
        "items": [
            {
                "id": d.index,
                "numbers": d.numbers,
                "label": d.label,
                "town": d.town,
                "url": d.url,
                "kind": d.kind,
                "predicted": d.predicted,
                "target": d.target,
                "shared": len(d.properties) > 1,
                "properties": [
                    {"number": p.number, "address": p.address, "town": p.town} for p in d.properties
                ],
            }
            for d in longlist.downloads
        ],
        "no_link": [
            {"number": p.number, "label": p.label} for p in longlist.properties if not p.url
        ],
        "warnings": longlist.warnings,
    }
