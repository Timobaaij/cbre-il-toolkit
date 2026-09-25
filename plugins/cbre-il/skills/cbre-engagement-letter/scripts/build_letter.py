#!/usr/bin/env python3
"""
Build a CBRE engagement letter (.docx) from a JSON spec, using the house template
in ../assets/template.docx. Layout, fonts, tables, header, footer, cover and the
Thank you page all come from the template; the spec only supplies content.

Usage:
    python build_letter.py spec.json output.docx

Text conventions inside any string in the spec:
    [[text]]   -> rendered as "[text]" with yellow highlight (a placeholder to fill in)
    **text**   -> bold

See references/spec_format.md for the full spec format and an example.
"""
import copy, json, os, re, shutil, sys, tempfile, zipfile
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'assets', 'template.docx')

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W14 = 'http://schemas.microsoft.com/office/word/2010/wordml'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
def q(t): return '{%s}%s' % (W, t)

RPR_ORDER = ['rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps', 'strike', 'dstrike',
             'outline', 'shadow', 'emboss', 'imprint', 'noProof', 'snapToGrid', 'vanish', 'webHidden',
             'color', 'spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight', 'u', 'effect',
             'bdr', 'shd', 'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang', 'eastAsianLayout',
             'specVanish', 'oMath']
TOKEN = re.compile(r'(\[\[.*?\]\]|\*\*.*?\*\*)')
TABLE_WIDTH = 9975  # usable width in the template, in DXA


# ---------------------------------------------------------------- xml helpers
def text_of(el):
    return ''.join(el.itertext())

def strip_ids(el):
    for n in el.iter():
        for a in list(n.attrib):
            if a.startswith('{%s}' % W14) and a.split('}')[1] in ('paraId', 'textId'):
                del n.attrib[a]
    return el

def set_flag(rpr, name, on, val=None):
    ex = rpr.find(q(name))
    if not on:
        if ex is not None:
            rpr.remove(ex)
        return
    if ex is None:
        ex = etree.Element(q(name))
        idx = RPR_ORDER.index(name)
        pos = len(rpr)
        for k, ch in enumerate(rpr):
            ln = etree.QName(ch).localname
            if ln in RPR_ORDER and RPR_ORDER.index(ln) > idx:
                pos = k
                break
        rpr.insert(pos, ex)
    if val is not None:
        ex.set(q('val'), val)

def base_rpr(p):
    for r in p.iter(q('r')):
        if r.find(q('rPr')) is not None and r.find(q('t')) is not None:
            return copy.deepcopy(r.find(q('rPr')))
    ppr = p.find(q('pPr'))
    if ppr is not None and ppr.find(q('rPr')) is not None:
        r = copy.deepcopy(ppr.find(q('rPr')))
        r.tag = q('rPr')
        return r
    return etree.Element(q('rPr'))

def para(proto, text='', bold=None, italic=None):
    """Clone a prototype paragraph and replace its text. Page-break runs are kept."""
    p = strip_ids(copy.deepcopy(proto))
    ppr = p.find(q('pPr'))
    rpr0 = base_rpr(p)
    br_runs = [r for r in p.findall(q('r')) if r.find(q('br')) is not None]
    for ch in list(p):
        if ch is not ppr:
            p.remove(ch)
    for r in br_runs:
        for t in r.findall(q('t')):
            r.remove(t)
        p.append(r)
    for part in TOKEN.split(text or ''):
        if not part:
            continue
        hl = part.startswith('[[')
        bd = part.startswith('**')
        txt = '[' + part[2:-2] + ']' if hl else (part[2:-2] if bd else part)
        rpr = copy.deepcopy(rpr0)
        if bold is not None:
            set_flag(rpr, 'b', bold); set_flag(rpr, 'bCs', bold)
        if italic is not None:
            set_flag(rpr, 'i', italic); set_flag(rpr, 'iCs', italic)
        if bd:
            set_flag(rpr, 'b', True); set_flag(rpr, 'bCs', True)
        if hl:
            set_flag(rpr, 'highlight', True, 'yellow')
        r = etree.SubElement(p, q('r'))
        r.append(rpr)
        t = etree.SubElement(r, q('t'))
        t.text = txt
        t.set(XML_SPACE, 'preserve')
    return p

def keep_next(p):
    ppr = p.find(q('pPr'))
    if ppr is None:
        ppr = etree.Element(q('pPr')); p.insert(0, ppr)
    if ppr.find(q('keepNext')) is None:
        ppr.insert(0, etree.Element(q('keepNext')))

def cant_split(tr):
    trpr = tr.find(q('trPr'))
    if trpr is None:
        trpr = etree.Element(q('trPr'))
        pos = 1 if tr.find(q('tblPrEx')) is not None else 0
        tr.insert(pos, trpr)
    if trpr.find(q('cantSplit')) is None:
        trpr.insert(0, etree.Element(q('cantSplit')))


# ---------------------------------------------------------------- template
class Template:
    def __init__(self, body):
        self.body = body
        els = list(body)
        idx = {}
        for i, el in enumerate(els):
            t = text_of(el)
            m = re.match(r'\s*\{\{([A-Z0-9_]+)\}\}', t)
            if m and m.group(1) not in idx:
                idx[m.group(1)] = i
        need = ['TITLE', 'COVER_LINE', 'SALUTATION', 'EMPTY', 'BODY', 'PAGEBREAK', 'H1', 'H2', 'H3',
                'BULLET', 'NOTE', 'TABLE_SIG', 'TABLE2', 'TABLE3', 'TABLE_FEE',
                'TY_INFO', 'TY_EMPTY', 'TY_NAME', 'TY_LINE']
        missing = [n for n in need if n not in idx]
        if missing:
            sys.exit('Template is missing prototypes: %s' % missing)
        self.p = {n: els[idx[n]] for n in need}
        self.cover_graphics = els[idx['TITLE'] + 1: idx['COVER_LINE']]
        self.cover_break = els[idx['COVER_LINE'] + 1]
        sect = [i for i, el in enumerate(els)
                if el.tag == q('p') and el.find(q('pPr')) is not None
                and el.find(q('pPr')).find(q('sectPr')) is not None]
        self.closing_pre = els[sect[0]: idx['TY_INFO']]
        self.trailing = els[idx['TY_LINE'] + 1:]


def build_table(proto, header, rows, widths=None, strip_bold=False, first_col_bold=False):
    tb = strip_ids(copy.deepcopy(proto))
    trs = tb.findall(q('tr'))
    hdr_tpl, body_tpls = trs[0], trs[1:] or trs[:1]
    for tr in trs:
        tb.remove(tr)
    ncols = len(header) if header else len(rows[0])
    if widths is None:
        grid_now = [int(g.get(q('w'))) for g in tb.find(q('tblGrid'))]
        widths = grid_now if len(grid_now) == ncols else [TABLE_WIDTH // ncols] * ncols
    grid = tb.find(q('tblGrid'))
    for g in list(grid):
        grid.remove(g)
    for w in widths:
        etree.SubElement(grid, q('gridCol')).set(q('w'), str(w))
    tw = tb.find(q('tblPr')).find(q('tblW'))
    if tw is not None and tw.get(q('type')) == 'dxa':
        tw.set(q('w'), str(sum(widths)))

    def make_row(rtpl, values, is_header):
        tr = copy.deepcopy(rtpl)
        tcs = tr.findall(q('tc'))
        ctpl = tcs[0]
        for tc in tcs:
            tr.remove(tc)
        for k, v in enumerate(values):
            tc = copy.deepcopy(ctpl)
            tcw = tc.find(q('tcPr')).find(q('tcW'))
            if tcw is not None:
                tcw.set(q('w'), str(widths[k])); tcw.set(q('type'), 'dxa')
            ptpl = tc.find(q('p'))
            for p in tc.findall(q('p')):
                tc.remove(p)
            for txt in (v if isinstance(v, list) else [v]):
                b = None
                if not is_header and strip_bold:
                    b = False
                if not is_header and first_col_bold and k == 0:
                    b = True
                p = para(ptpl, txt, bold=b)
                if is_header:
                    keep_next(p)
                tc.append(p)
            tr.append(tc)
        cant_split(tr)
        return tr

    if header:
        tb.append(make_row(hdr_tpl, header, True))
    for i, row in enumerate(rows):
        tb.append(make_row(body_tpls[i % len(body_tpls)], row, False))
    return tb


def signature_grid(T, people, approval=False):
    """Borderless two-column grid. people = list of dicts {name, role} (letter page),
    or for approval: list of two columns, each a list of lines (first line bold)."""
    tb = strip_ids(copy.deepcopy(T.p['TABLE_SIG']))
    rows = tb.findall(q('tr'))
    cells0 = rows[0].findall(q('tc'))
    bold_p = cells0[0].findall(q('p'))[0]
    line_p = cells0[0].findall(q('p'))[1]
    row_tpl = rows[1]
    for r in rows:
        tb.remove(r)

    def new_row(left, right):
        tr = copy.deepcopy(row_tpl)
        for tc, content in zip(tr.findall(q('tc')), (left, right)):
            for p in tc.findall(q('p')):
                tc.remove(p)
            for p in content:
                tc.append(p)
            if not content:
                tc.append(para(line_p, ''))
        cant_split(tr)
        tb.append(tr)
        return tr

    if not approval:
        blocks = [[para(bold_p, x['name']), para(line_p, x.get('role', ''))] for x in people]
        for i in range(0, len(blocks), 2):
            new_row(blocks[i], blocks[i + 1] if i + 1 < len(blocks) else [])
    else:
        left, right = people
        n = max(len(left), len(right))
        left = left + [''] * (n - len(left))
        right = right + [''] * (n - len(right))
        for i in range(n):
            if i == 0:
                lp, rp = [para(bold_p, left[i])], [para(bold_p, right[i])]
            else:
                lp, rp = [para(line_p, left[i], italic=False)], [para(line_p, right[i], italic=False)]
            tr = new_row(lp, rp)
            if i < n - 1:
                for p in tr.iter(q('p')):
                    keep_next(p)
    return tb


# ---------------------------------------------------------------- main build
def build(spec, out_path):
    work = tempfile.mkdtemp()
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(work)
    doc_path = os.path.join(work, 'word', 'document.xml')
    tree = etree.parse(doc_path)
    body = tree.getroot().find(q('body'))
    T = Template(body)
    out = []
    add = out.append
    P = T.p

    def empty(): add(para(P['EMPTY'], ''))
    def pagebreak(): add(para(P['PAGEBREAK'], ''))

    # cover
    add(para(P['TITLE'], spec['title']))
    out.extend(T.cover_graphics)
    for line in spec.get('cover_lines', []):
        add(para(P['COVER_LINE'], line))
    add(T.cover_break)

    # letter page
    add(para(P['SALUTATION'], spec.get('salutation', 'Dear [[Name]],')))
    empty()
    for t in spec.get('letter_paragraphs', []):
        add(para(P['BODY'], t))
    empty()
    add(para(P['SALUTATION'], spec.get('closing_greeting', 'Yours sincerely,')))
    empty()
    if spec.get('signatories'):
        add(signature_grid(T, spec['signatories']))
    empty()
    pagebreak()

    # body blocks
    for blk in spec.get('blocks', []):
        (kind, val), = blk.items()
        if kind in ('h1', 'h2', 'h3'):
            add(para(P[kind.upper()], val))
        elif kind == 'p':
            add(para(P['BODY'], val))
        elif kind == 'note':
            add(para(P['NOTE'], val))
        elif kind == 'bullets':
            for b in val:
                add(para(P['BULLET'], b))
        elif kind == 'empty':
            empty()
        elif kind == 'pagebreak':
            pagebreak()
        elif kind == 'table':
            style = val.get('style', 'detail')
            header, rows, widths = val.get('header'), val['rows'], val.get('widths')
            ncols = len(header) if header else len(rows[0])
            if style == 'fee':
                add(build_table(P['TABLE_FEE'], header, rows, widths, strip_bold=True))
            elif style == 'team' or ncols != 2:
                add(build_table(P['TABLE3'], header, rows, widths))
            else:
                add(build_table(P['TABLE2'], header, rows, widths))
        elif kind == 'approval':
            add(para(P['H2'], val.get('heading', 'For approval')))
            left = [val['cbre_entity'], 'Date:', 'Place:', ' ', '..........................................',
                    'Name: ' + val.get('cbre_name', ''), 'Function: ' + val.get('cbre_function', '')]
            right = [val['client_entity'], 'Date:', 'Place:', ' ', '..........................................',
                     'Name: ' + val.get('client_name', ''), 'Function: ' + val.get('client_function', '')]
            add(signature_grid(T, [left, right], approval=True))
            for enc in val.get('enclosures', []):
                empty()
                add(para(P['NOTE'], 'Enclosure: ' + enc))
        else:
            sys.exit('Unknown block type: %s' % kind)

    # closing section and Thank you page
    out.extend(T.closing_pre)
    add(para(P['TY_INFO'], 'For more information'))
    for c in spec.get('thank_you_contacts', []):
        add(para(P['TY_EMPTY'], ''))
        add(para(P['TY_NAME'], c['name']))
        for k in ('role', 'phone', 'email'):
            if c.get(k):
                add(para(P['TY_LINE'], c[k]))
    out.extend(T.trailing)

    for ch in list(body):
        body.remove(ch)
    for el in out:
        body.append(el)

    xml = etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True).decode('utf-8')
    dash_count = xml.count('\u2014') + xml.count('\u2013')
    xml = xml.replace('\u2014', ', ').replace('\u2013', '-')
    xml = xml.replace('\u2019', "'").replace('\u2018', "'").replace('\u201c', '"').replace('\u201d', '"')
    with open(doc_path, 'w', encoding='utf-8') as f:
        f.write(xml)

    # header, footer, document properties
    header = spec.get('header', spec['title'])
    footer = spec.get('footer_line', 'CBRE | Industrial & Logistics')
    def esc(s): return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    for name in os.listdir(os.path.join(work, 'word')):
        if re.match(r'(header|footer)\d*\.xml$', name):
            fp = os.path.join(work, 'word', name)
            s = open(fp, encoding='utf-8').read()
            s = s.replace('{{HEADER}}', esc(header)).replace('{{FOOTER}}', esc(footer))
            open(fp, 'w', encoding='utf-8').write(s)
    core = os.path.join(work, 'docProps', 'core.xml')
    s = open(core, encoding='utf-8').read()
    s = re.sub(r'<dc:title>[^<]*</dc:title>', '<dc:title>%s</dc:title>' % esc(spec['title']), s)
    s = re.sub(r'<dc:subject>[^<]*</dc:subject>', '<dc:subject>%s</dc:subject>' % esc(spec.get('client', '')), s)
    if spec.get('author'):
        s = re.sub(r'<dc:creator>[^<]*</dc:creator>', '<dc:creator>%s</dc:creator>' % esc(spec['author']), s)
        s = re.sub(r'<cp:lastModifiedBy>[^<]*</cp:lastModifiedBy>',
                   '<cp:lastModifiedBy>%s</cp:lastModifiedBy>' % esc(spec['author']), s)
    open(core, 'w', encoding='utf-8').write(s)
    app = os.path.join(work, 'docProps', 'app.xml')
    s = open(app, encoding='utf-8').read()
    s = s.replace('<vt:lpstr>Engagement Letter</vt:lpstr>', '<vt:lpstr>%s</vt:lpstr>' % esc(spec['title']))
    open(app, 'w', encoding='utf-8').write(s)

    # zip
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(work):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, work))
    shutil.rmtree(work)

    # report
    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
    placeholders = sorted({m for s_ in strings(spec) for m in re.findall(r'\[\[(.*?)\]\]', s_)})
    print('Built:', out_path)
    if dash_count:
        print('WARNING: %d em/en dash(es) were replaced automatically. Reword those sentences properly.' % dash_count)
    print('Open placeholders (yellow): %s' % (', '.join(placeholders) if placeholders else 'none'))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding='utf-8') as f:
        spec = json.load(f)
    build(spec, sys.argv[2])
