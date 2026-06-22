"""fitz_shim.py - a minimal PyMuPDF (fitz) stand-in for sandboxes where PyMuPDF
cannot be installed (no pip / no network). TWO degradation tiers:

  * pypdfium2 present  : page render + embedded-image extraction via pdfium,
                         page text via pdfplumber (or pdfium - see TEXT_BACKEND).
  * pdfplumber ONLY    : page text via pdfplumber; embedded images decoded
                         STRAIGHT FROM THE PDF STREAMS (DCTDecode = JPEG bytes,
                         JPXDecode = JPEG2000 - the formats brochure photos
                         actually use, both PIL-openable as-is). Page RENDERING is
                         unavailable: get_pixmap raises a clear RuntimeError and
                         the callers degrade (hero falls back to the best embedded
                         photo; vision_prep reports "could not rasterise").

It implements ONLY the nine-call surface this skill uses across extract_pdf.py
and images.py:

  fitz.open(path)            -> Document
  Document[i]                -> Page
  Document.page_count        -> int
  Document.extract_image(xr) -> {"image": <bytes>}      (xr comes from get_images)
  Document.close()
  Page.get_text()            -> str   (plain "text" layout, like fitz default)
  Page.get_images(full=True) -> list of tuples; tuple[0] is an opaque xref
  Page.get_pixmap(dpi=N)     -> Pixmap
  Pixmap.tobytes("png")      -> bytes

This is a FALLBACK only: the callers do
    try: import fitz
    except Exception: import fitz_shim as fitz
so real PyMuPDF is always preferred where present and is never shadowed. The
pixel bytes a renderer returns differ from PyMuPDF's, but the build re-encodes
every image to a budgeted JPEG anyway, and validate-html (delivered == render)
is engine-independent, so the QA guarantees are unaffected.
"""
from __future__ import annotations

import io
import sys

# Prefer a BUNDLED PyMuPDF wheel over this pure-python shim: if the environment has no
# PyMuPDF but the skill ships a manylinux wheel matching THIS interpreter, unpack it and
# BECOME real fitz - every caller falls back to `import fitz_shim as fitz`, so this hands
# them full-fidelity PyMuPDF with no per-site change. Strictly skipped when no compatible
# wheel exists (the shim below then runs) AND when fitz is already importable (`ensure`
# returns "system", not "vendored"), so the shim's own tests keep getting the shim.
try:
    import _vendor_wheels as _vw
    if _vw.ensure("fitz", "pymupdf") == "vendored":
        import fitz as _real_fitz
        sys.modules[__name__] = _real_fitz
except Exception:
    pass

try:
    import pypdfium2 as pdfium
    _HAVE_PDFIUM = True
except Exception:  # pdfplumber-only tier (a real Cowork sandbox state)
    pdfium = None
    _HAVE_PDFIUM = False

ENGINE = "pypdfium2" if _HAVE_PDFIUM else "pdfplumber-only"

# Which engine reconstructs page text. pdfplumber groups characters spatially
# (closest to PyMuPDF's "text" mode for single-column spec sheets); "pdfium"
# follows the content-stream order. Switchable so the A/B check against real
# fitz can pick whichever reproduces the label-anchored layout best.
TEXT_BACKEND = "pdfplumber"  # "pdfplumber" | "pdfium"


def open(path):  # noqa: A001 - deliberately mirrors fitz.open
    return Document(path)


class Pixmap:
    """Wraps a rendered PIL image; only .tobytes('png') is read downstream."""

    def __init__(self, pil):
        self._pil = pil

    def tobytes(self, fmt: str = "png") -> bytes:
        buf = io.BytesIO()
        self._pil.convert("RGB").save(buf, format="PNG" if fmt.lower() == "png" else fmt.upper())
        return buf.getvalue()


class Page:
    def __init__(self, doc: "Document", index: int):
        self._doc = doc
        self._index = index
        self._page = doc._pdfium[index] if _HAVE_PDFIUM else None

    def get_text(self, *args, **kwargs) -> str:
        return self._doc._page_text(self._index)

    def get_images(self, full: bool = False) -> list:
        if _HAVE_PDFIUM:
            return self._images_pdfium()
        return self._images_plumber()

    def _images_pdfium(self) -> list:
        out = []
        try:
            objs = list(self._page.get_objects(max_depth=10))
        except TypeError:  # older pypdfium2 without max_depth
            objs = list(self._page.get_objects())
        for obj in objs:
            if not isinstance(obj, pdfium.PdfImage):
                continue
            # render=False extracts at the STORED resolution; the plain render
            # path applies the placement matrix, which can shrink a 1280px photo
            # to its ~250pt placed size and push it under the hero size floor
            try:
                pil = obj.get_bitmap(render=False).to_pil()
            except Exception:
                try:
                    pil = obj.get_bitmap().to_pil()
                except Exception:
                    continue
            xref = self._doc._stash_image(pil)
            # mimic PyMuPDF's get_images tuple shape; only [0] (xref) is read by the caller
            out.append((xref, 0, pil.width, pil.height, 8, "", "", "", "", 0))
        return out

    def _images_plumber(self) -> list:
        """pdfplumber-only tier: decode embedded images straight from the PDF
        object streams. DCTDecode data IS a JPEG file and JPXDecode IS a JPEG2000
        file (PIL opens both as-is) - which covers the photo objects real
        brochures embed. Anything else (raw Flate bitmaps, exotic colourspaces)
        is skipped; the caller's bbox-crop / placeholder tiers absorb that."""
        out = []
        try:
            page = self._doc._plumber_pages()[self._index]
            images = page.images
        except Exception:
            return out
        for im in images:
            stream = im.get("stream")
            if stream is None:
                continue
            try:
                filters = [f[0].name if hasattr(f[0], "name") else str(f[0])
                           for f in (stream.get_filters() or [])]
            except Exception:
                filters = []
            raw = None
            if any(f in ("DCTDecode", "DCT", "JPXDecode") for f in filters):
                try:
                    raw = stream.rawdata if len(filters) == 1 else stream.get_data()
                except Exception:
                    raw = getattr(stream, "rawdata", None)
            if not raw:
                continue
            try:
                from PIL import Image
                pil = Image.open(io.BytesIO(raw))
                pil.load()
            except Exception:
                continue
            xref = self._doc._stash_image(pil)
            out.append((xref, 0, pil.width, pil.height, 8, "", "", "", "", 0))
        return out

    def get_links(self) -> list:
        """URI links on the page (PyMuPDF-shaped dicts, 'uri' key only), via
        pdfplumber's hyperlinks. The map-link coordinate mining keys on this."""
        out = []
        try:
            for hl in self._doc._plumber_pages()[self._index].hyperlinks:
                uri = hl.get("uri")
                if uri:
                    out.append({"kind": 2, "uri": str(uri)})
        except Exception:
            pass
        return out

    def get_pixmap(self, dpi: int = 150, **kwargs) -> Pixmap:
        if not _HAVE_PDFIUM:
            raise RuntimeError(
                "fitz_shim: no page renderer in this sandbox (pypdfium2 missing). "
                "Embedded-image extraction and text still work; page rasters do not.")
        scale = (dpi or 72) / 72.0
        bitmap = self._page.render(scale=scale)
        return Pixmap(bitmap.to_pil())


class Document:
    def __init__(self, path):
        self._path = str(path)
        self._pdfium = pdfium.PdfDocument(self._path) if _HAVE_PDFIUM else None
        self._pages: dict[int, Page] = {}
        self._plumber = None
        self._img_store: dict[int, object] = {}  # xref -> PIL image (encoded lazily)
        self._img_bytes: dict[int, bytes] = {}
        self._counter = 0

    @property
    def page_count(self) -> int:
        if _HAVE_PDFIUM:
            return len(self._pdfium)
        return len(self._plumber_pages())

    def __len__(self) -> int:
        return self.page_count

    def __getitem__(self, i: int) -> Page:
        pg = self._pages.get(i)
        if pg is None:
            pg = Page(self, i)
            self._pages[i] = pg
        return pg

    def _stash_image(self, pil) -> int:
        """Keep the PIL object; PNG-encode lazily in extract_image (the old eager
        encode burned CPU + memory for every image on every page touched)."""
        self._counter += 1
        self._img_store[self._counter] = pil
        return self._counter

    def extract_image(self, xref) -> dict:
        data = self._img_bytes.get(xref)
        if data is None:
            pil = self._img_store.get(xref)
            if pil is None:
                return {"image": b"", "ext": "png"}
            buf = io.BytesIO()
            pil.convert("RGB").save(buf, format="PNG")
            data = buf.getvalue()
            self._img_bytes[xref] = data
        return {"image": data, "ext": "png"}

    def _plumber_pages(self):
        if self._plumber is None:
            import pdfplumber
            self._plumber = pdfplumber.open(self._path)
        return self._plumber.pages

    def _page_text(self, i: int) -> str:
        # P2-2: normalise line endings - the own-line label regex anchors on \n, so a
        # CRLF/CR (pdfium emits CRLF) would drop a clean spec sheet to 0 records
        if TEXT_BACKEND == "pdfium" and _HAVE_PDFIUM:
            tp = self._pdfium[i].get_textpage()
            try:
                return (tp.get_text_range() or "").replace("\r\n", "\n").replace("\r", "\n")
            finally:
                tp.close()
        return (self._plumber_pages()[i].extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")

    def close(self) -> None:
        if self._pdfium is not None:
            try:
                self._pdfium.close()
            except Exception:
                pass
        if self._plumber is not None:
            try:
                self._plumber.close()
            except Exception:
                pass
        self._img_store.clear()
        self._img_bytes.clear()
