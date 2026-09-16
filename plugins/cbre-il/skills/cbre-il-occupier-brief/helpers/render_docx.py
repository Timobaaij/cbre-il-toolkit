#!/usr/bin/env python3
"""CBRE Industrial & Logistics Occupier Brief renderer.

Usage:
    python render_docx.py <brief.md> [out.docx] [--allow-dashes] [--no-lint]

Turns the occupier-brief markdown contract (see reference/docx-contract.md) into a
CBRE-branded A4 DOCX. Pure standard library: no python-docx, no node, no npm.
It writes WordprocessingML into a zip directly, so it runs on Windows, macOS,
Linux and the Claude sandbox with nothing installed.

Styling is fixed and must not be hand-tuned in the markdown:
    Font        Calibri throughout
    Page        A4 (11906 x 16842 DXA), 1 inch margins
    Green       006A4D   title, section headers, table header fill
    Ink         1A1A1A   body
    Grey        595959   eyebrow, descriptor, caveat
    Cement      7F8480   page footer
    Tint        EAF2EF   table body rows and at-a-glance labels
    Rule        C9D9D2   hairlines
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

GREEN, INK, GREY, WHITE, TINT, RULE, CEMENT = (
    "006A4D", "1A1A1A", "595959", "FFFFFF", "EAF2EF", "C9D9D2", "7F8480",
)
FONT = "Calibri"
PAGE_W, PAGE_H, MARGIN = 11906, 16842, 1440
CONTENT_DXA = PAGE_W - 2 * MARGIN

EM, EN = chr(0x2014), chr(0x2013)   # never written into prose, only detected

US_SPELLINGS = {
    "organization": "organisation", "organizations": "organisations",
    "organize": "organise", "organized": "organised", "organizing": "organising",
    "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing",
    "analyzes": "analyses", "center": "centre", "centers": "centres",
    "centered": "centred", "labor": "labour", "favor": "favour",
    "favorable": "favourable", "behavior": "behaviour", "defense": "defence",
    "meter": "metre", "meters": "metres", "liter": "litre", "catalog": "catalogue",
    "fulfillment": "fulfilment", "installment": "instalment",
    "enrollment": "enrolment", "modeling": "modelling", "modeled": "modelled",
    "canceled": "cancelled", "traveled": "travelled", "utilization": "utilisation",
    "optimization": "optimisation", "optimize": "optimise", "optimized": "optimised",
    "prioritize": "prioritise", "capitalize": "capitalise", "realize": "realise",
    "recognize": "recognise", "recognized": "recognised", "specialized": "specialised",
    "minimize": "minimise", "maximize": "maximise", "standardize": "standardise",
    "standardized": "standardised", "digitize": "digitise", "localization": "localisation",
    "rationalization": "rationalisation", "rationalize": "rationalise",
    "neighboring": "neighbouring", "inquiry": "enquiry", "aluminum": "aluminium",
    "tire": "tyre", "tires": "tyres",
}

QUOTED = re.compile(r'"[^"\n]*"')


def longpath(path):
    """Windows MAX_PATH guard.

    Deep scratch folders routinely push an absolute path past 260 characters,
    which surfaces as a bogus FileNotFoundError. The extended-length prefix
    lifts the limit. No-op on POSIX and on short paths.
    """
    if os.name != "nt":
        return path
    absolute = os.path.abspath(path)
    if len(absolute) < 240 or absolute.startswith("\\\\?\\"):
        return absolute
    return "\\\\?\\" + absolute.replace("/", "\\")


def _strip_quoted(line):
    """Blank out double-quoted spans so verbatim quotes escape the lint."""
    return QUOTED.sub(lambda m: " " * len(m.group(0)), line)


def lint(md, allow_dashes=False):
    """Return (errors, warnings). Errors block the render unless overridden."""
    errors, warnings = [], []
    for n, raw in enumerate(md.splitlines(), start=1):
        unquoted = _strip_quoted(raw)
        for ch, label in ((EM, "em dash"), (EN, "en dash")):
            if ch in unquoted:
                msg = "line %d: %s in authored text: %s" % (n, label, raw.strip()[:90])
                (warnings if allow_dashes else errors).append(msg)
            elif ch in raw:
                warnings.append("line %d: %s inside a quote (allowed, confirm it is verbatim)" % (n, label))
        for word in re.findall(r"[A-Za-z]+", unquoted):
            uk = US_SPELLINGS.get(word.lower())
            if not uk:
                continue
            if word[0].isupper():
                warnings.append(
                    "line %d: '%s' reads as a US spelling but is capitalised; keep only if a proper noun"
                    % (n, word))
            else:
                errors.append("line %d: US spelling '%s', use '%s'" % (n, word, uk))
    return errors, warnings


def _rpr(size, color=INK, bold=False, italics=False, caps=False, spacing=None):
    out = ['<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>' % (FONT, FONT, FONT)]
    if bold:
        out.append("<w:b/>")
    if italics:
        out.append("<w:i/>")
    if caps:
        out.append("<w:caps/>")
    if spacing:
        out.append('<w:spacing w:val="%d"/>' % spacing)
    out.append('<w:color w:val="%s"/>' % color)
    out.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size))
    return "<w:rPr>" + "".join(out) + "</w:rPr>"


def _run(text, **kw):
    if not text:
        return ""
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (_rpr(**kw), escape(text))


INLINE = re.compile(r"(\*\*.+?\*\*|\*[^*\n]+?\*)")


def runs_from_inline(text, **base):
    """Parse **bold** and *italic* into runs; everything else is literal."""
    out = []
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(_run(part[2:-2], **dict(base, bold=True)))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(_run(part[1:-1], **dict(base, italics=True)))
        else:
            out.append(_run(part, **base))
    return "".join(out)


def _border(edge, color, size=6):
    return '<w:%s w:val="single" w:sz="%d" w:space="1" w:color="%s"/>' % (edge, size, color)


def para(inline, size=21, color=INK, bold=False, italics=False, caps=False,
         spacing_char=None, before=0, after=120, bottom_rule=None, top_rule=None,
         keep_next=False, bullet=False, align=None):
    ppr = ["<w:pPr>"]
    if bullet:
        ppr.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
        ppr.append('<w:ind w:left="620" w:hanging="300"/>')
    if keep_next:
        ppr.append("<w:keepNext/>")
    if bottom_rule or top_rule:
        b = ["<w:pBdr>"]
        if top_rule:
            b.append(_border("top", top_rule))
        if bottom_rule:
            b.append(_border("bottom", bottom_rule))
        b.append("</w:pBdr>")
        ppr.append("".join(b))
    if align:
        ppr.append('<w:jc w:val="%s"/>' % align)
    ppr.append('<w:spacing w:before="%d" w:after="%d" w:line="259" w:lineRule="auto"/>' % (before, after))
    ppr.append("</w:pPr>")
    return "<w:p>" + "".join(ppr) + runs_from_inline(
        inline, size=size, color=color, bold=bold, italics=italics, caps=caps,
        spacing=spacing_char) + "</w:p>"


def spacer(after=120):
    return '<w:p><w:pPr><w:spacing w:after="%d"/></w:pPr></w:p>' % after


# --------------------------------------------------------------------------- #
# masthead and block elements
# --------------------------------------------------------------------------- #
def eyebrow(text):
    return para(text, size=16, color=GREY, bold=True, caps=True, spacing_char=30, after=40)


def title(text):
    return para(text, size=36, color=GREEN, bold=True, caps=True, after=60)


def subject(text):
    return para(text, size=26, color=INK, bold=True, after=40)


def descriptor(text):
    return para(text, size=21, color=GREY, italics=True, after=60)


def prepared(text):
    return para(text, size=17, color=GREY, after=220, bottom_rule=GREEN)


def section_header(text):
    return para(text, size=26, color=GREEN, bold=True, before=200, after=120,
                bottom_rule=GREEN, keep_next=True)


def subheading(text):
    return para(text, size=22, color=INK, bold=True, before=120, after=60, keep_next=True)


def italic_label(text):
    return para(text, size=21, color=GREY, italics=True, after=60)


def caveat(text):
    return para(text, size=16, color=GREY, italics=True, before=240, after=0, top_rule=RULE)


# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #
def _cell(inline, width, fill=None, bold=False, color=INK, align_top=True):
    tcpr = ['<w:tcPr><w:tcW w:w="%d" w:type="dxa"/>' % width]
    if fill:
        tcpr.append('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill)
    if align_top:
        tcpr.append('<w:vAlign w:val="top"/>')
    tcpr.append('<w:tcMar><w:top w:w="80" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/>'
                '<w:left w:w="120" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tcMar>')
    tcpr.append("</w:tcPr>")
    body = "<w:p><w:pPr><w:spacing w:before=\"20\" w:after=\"20\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>" \
           + runs_from_inline(inline, size=20, color=color, bold=bold) + "</w:p>"
    return "<w:tc>" + "".join(tcpr) + body + "</w:tc>"


def build_table(rows, mode):
    """mode: keyvalue | isnot | generic."""
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    if mode == "keyvalue":
        widths = [int(CONTENT_DXA * 0.34)] + [CONTENT_DXA - int(CONTENT_DXA * 0.34)]
        if ncols > 2:
            widths = [CONTENT_DXA // ncols] * ncols
    else:
        widths = [CONTENT_DXA // ncols] * ncols
        widths[-1] = CONTENT_DXA - sum(widths[:-1])

    trs = []
    for i, row in enumerate(rows):
        header = mode in ("isnot", "generic") and i == 0
        tcs = []
        for j, text in enumerate(row):
            if header:
                tcs.append(_cell(text, widths[j], fill=GREEN, bold=True, color=WHITE))
            elif mode == "keyvalue":
                tcs.append(_cell(text, widths[j], fill=TINT if j == 0 else None, bold=(j == 0)))
            else:
                tcs.append(_cell(text, widths[j], fill=TINT if i % 2 == 1 else None))
        trow = "<w:tr>"
        if header:
            trow += "<w:trPr><w:tblHeader/></w:trPr>"
        trs.append(trow + "".join(tcs) + "</w:tr>")

    borders = ("<w:tblBorders>"
               + _border("top", RULE, 4) + _border("bottom", RULE, 4)
               + _border("left", RULE, 4) + _border("right", RULE, 4)
               + _border("insideH", RULE, 4) + _border("insideV", RULE, 4)
               + "</w:tblBorders>")
    grid = "<w:tblGrid>" + "".join('<w:gridCol w:w="%d"/>' % w for w in widths) + "</w:tblGrid>"
    tblpr = ('<w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/>%s</w:tblPr>'
             % (CONTENT_DXA, borders))
    return "<w:tbl>" + tblpr + grid + "".join(trs) + "</w:tbl>"


# --------------------------------------------------------------------------- #
# markdown parse
# --------------------------------------------------------------------------- #
FM_KV = re.compile(r"^([A-Za-z_]+)\s*:\s*(.*)$")


def parse_front_matter(text):
    fm = {}
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?", text)
    if not m:
        return fm, text
    for line in m.group(1).splitlines():
        kv = FM_KV.match(line)
        if kv:
            fm[kv.group(1).lower().strip()] = kv.group(2).strip()
    return fm, text[m.end():]


IS_TABLE = re.compile(r"^\s*\|.*\|\s*$")
SEP_CELL = re.compile(r"^:?-{2,}:?$")


def _is_sep(cells):
    return all(SEP_CELL.match(c.strip()) or c.strip() == "" for c in cells)


def build_body(md):
    fm, body = parse_front_matter(md)
    out = [
        eyebrow(fm.get("eyebrow", "CBRE  |  INDUSTRIAL & LOGISTICS")),
        title(fm.get("title", "OCCUPIER BRIEF")),
    ]
    if fm.get("subject"):
        out.append(subject(fm["subject"]))
    if fm.get("descriptor"):
        out.append(descriptor(fm["descriptor"]))
    out.append(prepared(fm.get(
        "prepared",
        "Confidential: internal pursuit material  |  CBRE Industrial & Logistics")))

    section = ""
    bullets = []
    tbuf = []
    pbuf = []          # consecutive body lines, joined into one paragraph
    blines = []        # continuation lines of the bullet being read

    def flush_bullets():
        if blines:
            bullets.append(" ".join(blines))
            del blines[:]
        while bullets:
            out.append(para(bullets.pop(0), bullet=True, after=60))

    def flush_para():
        if pbuf:
            out.append(para(" ".join(pbuf)))
            del pbuf[:]

    def flush_table():
        if not tbuf:
            return
        rows = []
        for line in tbuf:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not _is_sep(cells):
                rows.append(cells)
        del tbuf[:]
        if not rows:
            return
        sec = section.lower()
        if any(k in sec for k in ("at a glance", "at-a-glance", "quick facts", "the file")):
            mode = "keyvalue"
        elif re.search(r"\bis\b", " ".join(rows[0]), re.I) and re.search(r"is\s*not", " ".join(rows[0]), re.I):
            mode = "isnot"
        elif any(k in sec for k in ("is not", "is / is not", "is and is not")):
            mode = "isnot"
        else:
            mode = "generic"
        out.append(build_table(rows, mode))
        out.append(spacer(140))

    def flush_all():
        flush_bullets()
        flush_para()

    for raw in body.replace("\r", "").split("\n"):
        line = raw.rstrip()
        t = line.strip()
        if IS_TABLE.match(line):
            flush_all()
            tbuf.append(line)
            continue
        if tbuf:
            flush_table()
        if t == "":
            flush_all()
            continue
        if re.match(r"^FOOTER:", t, re.I):
            flush_all()
            out.append(caveat(re.sub(r"^FOOTER:\s*", "", t, flags=re.I)))
            continue
        if re.match(r"^#{1,2}\s+", t):
            flush_all()
            section = re.sub(r"\s*#*$", "", re.sub(r"^#{1,2}\s+", "", t))
            out.append(section_header(section))
            continue
        if re.match(r"^###\s+", t) or re.match(r"^\*\*[^*]+\*\*:?\s*$", t):
            flush_all()
            out.append(subheading(re.sub(r"^\*\*|\*\*:?$", "", re.sub(r"^###\s+", "", t))))
            continue
        if re.match(r"^\*[^*].*\*$", t) and "**" not in t:
            flush_all()
            out.append(italic_label(t.strip("*")))
            continue
        if re.match(r"^[-•]\s+", t):
            flush_para()
            if blines:
                bullets.append(" ".join(blines))
                del blines[:]
            blines.append(re.sub(r"^[-•]\s+", "", t))
            continue
        if blines:                      # wrapped continuation of the current bullet
            blines.append(t)
            continue
        pbuf.append(t)                  # wrapped body paragraph

    flush_all()
    flush_table()
    return fm, "".join(out)


# --------------------------------------------------------------------------- #
# package parts
# --------------------------------------------------------------------------- #
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles %s>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/><w:color w:val="%s"/><w:sz w:val="21"/><w:szCs w:val="21"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/></w:style>
</w:styles>""" % (NS, FONT, FONT, FONT, INK)

NUMBERING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering %s>
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/>
<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="620" w:hanging="300"/></w:pPr>
<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:hint="default"/><w:color w:val="%s"/></w:rPr></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>""" % (NS, FONT, FONT, GREEN)


def footer_part(label):
    left = _run(label, size=15, color=CEMENT)
    page = ('<w:r>%s<w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r>%s<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r>%s<w:fldChar w:fldCharType="end"/></w:r>'
            % (_rpr(15, CEMENT), _rpr(15, CEMENT), _rpr(15, CEMENT)))
    ppr = ('<w:pPr><w:pBdr>%s</w:pBdr>'
           '<w:tabs><w:tab w:val="right" w:pos="%d"/></w:tabs>'
           '<w:spacing w:before="120" w:after="0"/></w:pPr>'
           % (_border("top", RULE, 4), CONTENT_DXA))
    tab = "<w:r>%s<w:tab/></w:r>" % _rpr(15, CEMENT)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:ftr %s><w:p>%s%s%s%s</w:p></w:ftr>' % (NS, ppr, left, tab, page))


def core_props(subject_line, author):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>%s</dc:title><dc:creator>%s</dc:creator>'
            '<cp:lastModifiedBy>%s</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
            '</cp:coreProperties>'
            % (escape(subject_line), escape(author), escape(author), now, now))


APP_PROPS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
             'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
             '<Application>CBRE I&amp;L Occupier Brief renderer</Application></Properties>')


def document_part(body_xml):
    sect = ('<w:sectPr>'
            '<w:footerReference w:type="default" r:id="rId3"/>'
            '<w:pgSz w:w="%d" w:h="%d"/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
            'w:header="708" w:footer="566" w:gutter="0"/>'
            '<w:cols w:space="708"/><w:docGrid w:linePitch="360"/>'
            '</w:sectPr>' % (PAGE_W, PAGE_H, MARGIN, MARGIN, MARGIN, MARGIN))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document %s><w:body>%s%s</w:body></w:document>' % (NS, body_xml, sect))


def write_docx(md, out_path, footer_label="CBRE  |  Industrial & Logistics"):
    fm, body_xml = build_body(md)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(longpath(out_dir)):
        os.makedirs(longpath(out_dir), exist_ok=True)
    parts = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": document_part(body_xml),
        "word/_rels/document.xml.rels": DOC_RELS,
        "word/styles.xml": STYLES,
        "word/numbering.xml": NUMBERING,
        "word/footer1.xml": footer_part(fm.get("footer_label", footer_label)),
        "docProps/core.xml": core_props(
            fm.get("subject", "Occupier Brief"),
            "CBRE Industrial & Logistics"),
        "docProps/app.xml": APP_PROPS,
    }
    with zipfile.ZipFile(longpath(out_path), "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data.encode("utf-8"))
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a CBRE I&L Occupier Brief markdown file to DOCX.")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--allow-dashes", action="store_true",
                    help="downgrade em/en dash errors to warnings (verbatim-quote heavy briefs only)")
    ap.add_argument("--no-lint", action="store_true", help="skip the house-style lint entirely")
    args = ap.parse_args(argv)

    md = open(longpath(args.input), encoding="utf-8").read()
    if not args.no_lint:
        errors, warnings = lint(md, allow_dashes=args.allow_dashes)
        for w in warnings:
            print("WARN  " + w, file=sys.stderr)
        if errors:
            for e in errors:
                print("ERROR " + e, file=sys.stderr)
            print("\n%d house-style error(s). Fix the markdown and re-run." % len(errors), file=sys.stderr)
            return 2

    out = args.output
    if not out:
        base = os.path.splitext(os.path.basename(args.input))[0]
        out = os.path.join(os.path.dirname(os.path.abspath(args.input)), base + ".docx")
    write_docx(md, out)
    print("Wrote %s (%d bytes)" % (out, os.path.getsize(longpath(out))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
