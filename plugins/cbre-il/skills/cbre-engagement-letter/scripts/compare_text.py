#!/usr/bin/env python3
"""
Compare the text of two versions of a letter and list every difference, paragraph by
paragraph. Run this BEFORE delivering any revision, with the user's latest version as
the reference, and report every difference in the reply.

Usage:
    python compare_text.py reference.docx|reference.txt  new.docx

- .docx on both sides: paragraph-level diff (body paragraphs and table cells, in order).
- .txt as reference (e.g. text read from SharePoint/OneDrive when the file itself cannot
  be downloaded): whitespace-insensitive character diff grouped into regions, because
  extracted text loses paragraph breaks.

Formatting-only changes (bold, font, spacing) are NOT detected. Say so in the reply.
"""
import difflib, re, sys, zipfile
from lxml import etree

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def docx_paragraphs(path):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    out = []
    for p in body.iter(W + 'p'):
        # skip text inside text boxes / drawings (the Thank you page disclaimer)
        if any(a.tag in (W + 'txbxContent',) for a in p.iterancestors()):
            continue
        t = ''.join(x.text or '' for x in p.iter(W + 't')).strip()
        if t:
            out.append(re.sub(r'\s+', ' ', t))
    return out


def norm_chars(t):
    t = t.replace('\u2022', '').replace('\u2212', '-').replace('\u00a0', ' ')
    t = t.replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
    return re.sub(r'\s+', '', t).lower()


def para_diff(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    n = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        n += 1
        if op == 'replace' and (i2 - i1) == (j2 - j1):
            for x, y in zip(a[i1:i2], b[j1:j2]):
                print('CHANGED\n  was: %s\n  now: %s\n' % (x, y))
        else:
            for x in a[i1:i2]:
                print('REMOVED: %s\n' % x)
            for y in b[j1:j2]:
                print('ADDED:   %s\n' % y)
    return n


def char_diff(a_text, b_paras):
    a = norm_chars(a_text)
    b = norm_chars(' '.join(b_paras))
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    regions, cur = [], None
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        if cur and i1 - cur['end'] < 60:
            cur['old'] += a[cur['end']:i2] if i1 > cur['end'] else a[i1:i2]
            cur['new'] += b[j1:j2]
            cur['end'] = i2
        else:
            cur = {'ctx': a[max(0, i1 - 30):i1], 'old': a[i1:i2], 'new': b[j1:j2], 'end': i2}
            regions.append(cur)
    for r in regions:
        print('after "...%s"\n  was: %s\n  now: %s\n' % (r['ctx'], r['old'][:300], r['new'][:300]))
    return len(regions)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ref, new = sys.argv[1], sys.argv[2]
    b = docx_paragraphs(new)
    if ref.lower().endswith('.docx'):
        n = para_diff(docx_paragraphs(ref), b)
    else:
        n = char_diff(open(ref, encoding='utf-8').read(), b)
        print('(Text reference: spacing and capitals ignored; paragraph order from extraction may differ.)')
    print('%d difference(s) found.' % n if n else 'No text differences.')
