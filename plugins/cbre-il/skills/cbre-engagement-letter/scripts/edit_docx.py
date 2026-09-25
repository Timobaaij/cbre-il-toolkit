#!/usr/bin/env python3
"""
Make targeted edits to an EXISTING letter (typically the user's own edited version)
without rebuilding it, so every other edit and all formatting survive.

Usage:
    python edit_docx.py input.docx edits.json output.docx

edits.json is a list of operations, applied in order. Each must match exactly once
(the script stops otherwise, so nothing is changed by accident):

    [
      {"replace": "Name: A. Author", "with": "Name: [[Signatory]]"},
      {"replace_paragraph": "General terms", "with": "Terms of business"},
      {"delete_paragraph": "The availability date and the requirement"},
      {"insert_after": "We look forward to working with your organisation.",
       "text": "Enclosure: CBRE Limited Standard Terms of Business"}
    ]

- replace:            swaps text inside one paragraph. Works across runs; the new text
                      takes the formatting of the first run it touches. If the new text
                      contains [[..]] or **..**, only that paragraph is re-rendered.
- replace_paragraph:  replaces the whole text of the paragraph that contains the match.
- delete_paragraph:   removes the paragraph that contains the match.
- insert_after:       adds a new paragraph (formatted like the matched one) after it.
Text matched is the visible paragraph text. [[x]] in new text becomes a yellow placeholder.
"""
import copy, json, os, re, shutil, sys, tempfile, zipfile
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_letter import para, q  # reuse the same run/placeholder handling


def ptext(p):
    return ''.join(t.text or '' for t in p.iter(q('t')))


def find_one(root, needle):
    hits = [p for p in root.iter(q('p')) if needle in ptext(p)]
    if len(hits) != 1:
        sys.exit('Edit stopped: "%s" matched %d paragraphs (needs exactly 1).' % (needle, len(hits)))
    return hits[0]


def replace_in_paragraph(p, old, new):
    runs = [r for r in p.iter(q('r')) if r.find(q('t')) is not None]
    full = ''.join(r.find(q('t')).text or '' for r in runs)
    start = full.index(old)
    end = start + len(old)
    pos = 0
    first = True
    for r in runs:
        t = r.find(q('t'))
        s = t.text or ''
        a, b = pos, pos + len(s)
        pos = b
        if b <= start or a >= end:
            continue
        lo, hi = max(start, a) - a, min(end, b) - a
        t.text = s[:lo] + (new if first else '') + s[hi:]
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        first = False


def main(src, edits_path, dst):
    edits = json.load(open(edits_path, encoding='utf-8'))
    work = tempfile.mkdtemp()
    with zipfile.ZipFile(src) as z:
        z.extractall(work)
    doc = os.path.join(work, 'word', 'document.xml')
    tree = etree.parse(doc)
    root = tree.getroot()
    for e in edits:
        if 'replace' in e:
            p = find_one(root, e['replace'])
            if '[[' in e['with'] or '**' in e['with']:
                # placeholder or bold requested: rebuild this one paragraph with markup
                p.getparent().replace(p, para(p, ptext(p).replace(e['replace'], e['with'])))
            else:
                replace_in_paragraph(p, e['replace'], e['with'])
        elif 'replace_paragraph' in e:
            p = find_one(root, e['replace_paragraph'])
            p.getparent().replace(p, para(p, e['with']))
        elif 'delete_paragraph' in e:
            p = find_one(root, e['delete_paragraph'])
            p.getparent().remove(p)
        elif 'insert_after' in e:
            p = find_one(root, e['insert_after'])
            p.addnext(para(p, e['text']))
        else:
            sys.exit('Unknown edit: %s' % e)
        print('done:', list(e.items())[0])
    tree.write(doc, xml_declaration=True, encoding='UTF-8', standalone=True)
    if os.path.exists(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        for r, _, fs in os.walk(work):
            for f in fs:
                full = os.path.join(r, f)
                z.write(full, os.path.relpath(full, work))
    shutil.rmtree(work)
    print('Saved:', dst)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
