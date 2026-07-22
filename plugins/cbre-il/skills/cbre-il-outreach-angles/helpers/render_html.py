#!/usr/bin/env python3
"""
render_html.py - render a gate-validated Outreach Angles markdown sheet into a
single self-contained, CBRE-branded HTML file.

The markdown (see reference/output-template.md) is the source of truth and is what
final_gate.py validates. This renderer is a faithful presentation layer only: it
adds NO facts and changes NO wording. It leads with the plain-English situation and
the at-a-glance table, shows each opportunity as a card with the plain-English
fields and the email hook prominent, and tucks each item's Evidence, Call opener
and Confidence behind a collapsible "Show the evidence and call script" toggle, so
the default view is digestible while the rigour is one click away.

Output is one .html file with all CSS inline, no external assets: it opens in any
browser and prints cleanly to PDF.

Usage:
    python render_html.py SHEET.md [--out SHEET.html] [--ledger LEDGER.md]

Stdlib only. Exit 0 on success, 2 on bad invocation.
"""
import argparse
import html
import os
import re
import sys

CSS = """
:root{
  --cbre-green:#003f2d; --cbre-dark:#012a2d; --cbre-accent:#17e88f;
  --cbre-mint:#c0d8cc; --cbre-sand:#f5f3ec; --ink:#1b211f; --muted:#5b6b64;
  --amber:#b8860b; --amber-bg:#fbf3dc; --green-bg:#e3f5ec; --grey-bg:#eceeed;
  --card-border:#d7ded9;
}
*{box-sizing:border-box}
body{margin:0;background:#e9ece9;color:var(--ink);
  font-family:"Segoe UI",Calibri,Helvetica,Arial,sans-serif;line-height:1.55;font-size:16px}
.wrap{max-width:900px;margin:0 auto;background:#fff;box-shadow:0 0 0 1px #dfe4e1}
h1,h2,h3,.serif{font-family:Georgia,"Times New Roman",serif}
header.masthead{background:var(--cbre-green);color:#fff;padding:32px 40px 26px}
header.masthead .kicker{color:var(--cbre-accent);letter-spacing:.14em;text-transform:uppercase;
  font-size:12px;font-weight:700;margin:0 0 8px}
header.masthead h1{margin:0;font-size:30px;line-height:1.15;font-weight:700}
header.masthead .oneliner{margin:12px 0 16px;color:#dbe7e0;font-size:15px;max-width:64ch}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:rgba(255,255,255,.12);color:#eafdf4;border:1px solid rgba(255,255,255,.22);
  border-radius:999px;padding:3px 12px;font-size:12.5px}
main{padding:8px 40px 44px}
section{padding:22px 0;border-bottom:1px solid #edf0ee}
section:last-child{border-bottom:0}
h2{color:var(--cbre-green);font-size:21px;margin:6px 0 12px}
section.situation{background:var(--cbre-sand);margin:0 -40px;padding:26px 40px}
section.situation h2{margin-top:0}
p{margin:0 0 12px}
.prospect{border-left:4px solid var(--cbre-accent);background:#f2faf6;padding:14px 18px;border-radius:0 6px 6px 0}
dl.jargon{margin:0;display:grid;grid-template-columns:1fr;gap:10px}
dl.jargon .term{border:1px solid var(--card-border);border-radius:8px;padding:12px 14px;background:#fbfcfb}
dl.jargon dt{font-weight:700;color:var(--cbre-dark);font-family:Georgia,serif;margin-bottom:3px}
dl.jargon dd{margin:0;color:#33403b;font-size:15px}
table.glance{width:100%;border-collapse:collapse;font-size:14px;margin-top:6px}
table.glance th{background:var(--cbre-green);color:#fff;text-align:left;padding:9px 10px;font-weight:600}
table.glance td{border-bottom:1px solid #e4e9e6;padding:9px 10px;vertical-align:top}
table.glance tr:nth-child(even) td{background:#f7f9f8}
table.glance td:first-child{font-weight:700;color:var(--cbre-green);width:26px}
.card{border:1px solid var(--card-border);border-radius:10px;padding:20px 22px;margin:16px 0;background:#fff}
.card h3{margin:0 0 12px;font-size:18px;color:var(--cbre-dark);display:flex;gap:10px;align-items:baseline}
.card h3 .rank{background:var(--cbre-green);color:#fff;font-family:"Segoe UI",sans-serif;font-size:13px;
  font-weight:700;min-width:24px;height:24px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;padding:0 6px}
.badges{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 14px}
.badge{font-size:12px;font-weight:600;border-radius:6px;padding:3px 10px;border:1px solid transparent}
.b-high{background:var(--green-bg);color:#0a6b45;border-color:#bfe6d3}
.b-med{background:var(--amber-bg);color:#8a6400;border-color:#ecdca8}
.b-low{background:var(--grey-bg);color:#4b5651;border-color:#d4dad7}
.b-trigger{background:#e8eef6;color:#274b7a;border-color:#c9d8ec}
.b-send{background:var(--green-bg);color:#0a6b45;border-color:#bfe6d3}
.b-verify{background:var(--amber-bg);color:#8a6400;border-color:#ecdca8}
.pe{margin:0 0 10px}
.pe .lbl{font-weight:700;color:var(--cbre-dark)}
.hook{background:#f2faf6;border:1px solid #cdeadd;border-radius:8px;padding:12px 16px;margin:14px 0}
.hook .hook-title{font-weight:700;color:var(--cbre-green);font-size:13px;text-transform:uppercase;
  letter-spacing:.06em;margin:0 0 8px}
.hook ul{margin:0;padding-left:18px}
.hook li{margin:0 0 5px}
.stake{font-size:14.5px;color:#33403b;margin:12px 0 0}
details.evidence{margin-top:14px;border-top:1px dashed #d7ded9;padding-top:10px}
details.evidence summary{cursor:pointer;color:var(--cbre-green);font-weight:600;font-size:14px;list-style:none}
details.evidence summary::-webkit-details-marker{display:none}
details.evidence summary::before{content:"\\25B8  ";color:var(--cbre-accent)}
details.evidence[open] summary::before{content:"\\25BE  "}
details.evidence .ev-body{margin-top:10px;font-size:14.5px;color:#39443f}
details.evidence .ev-body p{margin:0 0 8px}
details.evidence .ev-lbl{font-weight:700;color:var(--cbre-dark)}
ul.watch{margin:0;padding-left:18px}
ul.watch li{margin:0 0 8px}
code{background:#eef2f0;border-radius:4px;padding:1px 5px;font-size:.9em}
.ledger-note{font-size:14px;color:var(--muted)}
section.internal{background:#faf7ef;border:1px dashed #d8c9a0;margin:0 -40px;padding:22px 40px}
section.internal h2{color:#7a5c00}
.internal-banner{background:#4a3a12;color:#ffdf9e;border-radius:6px;padding:8px 12px;font-size:12px;font-weight:700;margin:0 0 14px;text-transform:uppercase;letter-spacing:.05em}
.bet-card{border:1px solid #e5dcc2;border-left:4px solid #b8860b;border-radius:8px;background:#fffdf7;padding:14px 16px;margin:12px 0}
.bet-h{margin:0 0 8px;font-size:15.5px;color:#5c4700;font-family:Georgia,serif;display:flex;gap:8px;align-items:baseline}
.bet-tag{background:#b8860b;color:#fff;font-family:"Segoe UI",sans-serif;font-size:11.5px;font-weight:700;border-radius:5px;padding:2px 7px;white-space:nowrap}
.bet-field{margin:0 0 6px;font-size:14.5px;color:#39443f}
.bet-lbl{font-weight:700;color:#5c4700}
footer.foot{padding:18px 40px 30px;color:var(--muted);font-size:12.5px;border-top:1px solid #edf0ee}
@media print{body{background:#fff}.wrap{box-shadow:none;max-width:100%}
  section.internal{display:none !important}
  details.evidence{border:0}details.evidence summary{display:none}details.evidence[open] .ev-body,
  details.evidence .ev-body{display:block !important}details.evidence:not([open]) .ev-body{display:block}}
"""


def esc(s):
    return html.escape(s, quote=False)


def inline(s):
    """Escape, then apply minimal inline markdown: **bold** and `code`."""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def split_sections(body_lines):
    """Split a list of lines into ('## Heading' -> [body lines]) preserving order."""
    sections, cur, curlines = [], None, []
    for ln in body_lines:
        m = re.match(r"^##\s+(.*)$", ln)
        if m:
            if cur is not None:
                sections.append((cur, curlines))
            cur, curlines = m.group(1).strip(), []
        else:
            if cur is not None:
                curlines.append(ln)
    if cur is not None:
        sections.append((cur, curlines))
    return sections


def paragraphs(lines):
    """Group non-empty lines into paragraphs on blank-line boundaries."""
    out, buf = [], []
    for ln in lines:
        if ln.strip():
            buf.append(ln.strip())
        elif buf:
            out.append(" ".join(buf)); buf = []
    if buf:
        out.append(" ".join(buf))
    return out


def render_paragraphs(lines):
    return "".join(f"<p>{inline(p)}</p>" for p in paragraphs(lines))


def render_jargon(lines):
    items = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("- "):
            continue
        s = s[2:]
        m = re.match(r"\*\*(.+?)\*\*\s*:\s*(.*)$", s)
        if m:
            items.append(f'<div class="term"><dt>{inline(m.group(1))}</dt>'
                         f'<dd>{inline(m.group(2))}</dd></div>')
        else:
            items.append(f'<div class="term"><dd>{inline(s)}</dd></div>')
    if not items:
        # e.g. "None needed for this sheet."
        txt = " ".join(l.strip() for l in lines if l.strip())
        return f"<p>{inline(txt)}</p>" if txt else ""
    return f'<dl class="jargon">{"".join(items)}</dl>'


def render_table(lines):
    rows = []
    for ln in lines:
        s = ln.strip()
        if s.count("|") < 2:
            continue
        if re.match(r"^\|?[\s:|-]+\|?$", s):  # separator row
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    thead = "<tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
    tbody = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<table class="glance"><thead>{thead}</thead><tbody>{tbody}</tbody></table>'


def render_watchlist(lines):
    lis = [f"<li>{inline(ln.strip()[2:])}</li>" for ln in lines if ln.strip().startswith("- ")]
    return f'<ul class="watch">{"".join(lis)}</ul>' if lis else render_paragraphs(lines)


FIELD_RE = re.compile(r"^([A-Z][A-Za-z' ]+):\s?(.*)$")


def parse_item(item_lines):
    """Parse a '### N. Title' block into (rank, title, fields dict).
    fields: name -> {'value': str, 'bullets': [str]}."""
    title_line = item_lines[0].strip()
    m = re.match(r"^###\s+(\d+)\.\s*(.*)$", title_line)
    rank = m.group(1) if m else ""
    title = m.group(2).strip() if m else title_line.lstrip("# ")
    fields, order, cur = {}, [], None
    for ln in item_lines[1:]:
        raw = ln.rstrip()
        stripped = raw.strip()
        bullet = re.match(r"^-\s+(.*)$", stripped)
        fm = FIELD_RE.match(stripped)
        if bullet and cur:  # sub-bullet belongs to the current field (e.g. Email hook)
            fields[cur]["bullets"].append(bullet.group(1))
        elif fm and not stripped.startswith("- "):
            name = fm.group(1).strip()
            fields[name] = {"value": fm.group(2).strip(), "bullets": []}
            order.append(name); cur = name
        elif stripped and cur:  # continuation of current field value
            fields[cur]["value"] = (fields[cur]["value"] + " " + stripped).strip()
    return rank, title, fields, order


def badge_dev(value):
    v = value.split(".")[0].strip().lower()
    cls = {"high": "b-high", "medium": "b-med", "low": "b-low"}.get(v, "b-low")
    label = value.split(".")[0].strip() or "?"
    return f'<span class="badge {cls}">Developability: {esc(label)}</span>'


def badge_trigger(value):
    v = value.split(".")[0].strip()
    return f'<span class="badge b-trigger">Trigger: {esc(v) or "?"}</span>'


def badge_readiness(value):
    low = value.lower()
    if low.startswith("send now"):
        return '<span class="badge b-send">Send now</span>'
    # Verify first: <fact>
    fact = value.split(":", 1)[1].strip() if ":" in value else ""
    tail = f": {esc(fact)}" if fact else ""
    return f'<span class="badge b-verify">Verify first{tail}</span>'


def render_hook(field):
    lis = "".join(f"<li>{inline(b)}</li>" for b in field["bullets"])
    if not lis and field["value"]:
        lis = f"<li>{inline(field['value'])}</li>"
    return (f'<div class="hook"><p class="hook-title">Email hook</p>'
            f'<ul>{lis}</ul></div>') if lis else ""


def pe_block(fields, name, label):
    f = fields.get(name)
    if not f or not f["value"]:
        return ""
    return f'<p class="pe"><span class="lbl">{esc(label)}:</span> {inline(f["value"])}</p>'


def ev_line(fields, name, label):
    f = fields.get(name)
    if not f or not f["value"]:
        return ""
    return f'<p><span class="ev-lbl">{esc(label)}:</span> {inline(f["value"])}</p>'


def render_item(item_lines):
    rank, title, fields, _ = parse_item(item_lines)
    badges = []
    if "Developability" in fields:
        badges.append(badge_dev(fields["Developability"]["value"]))
    if "Trigger" in fields:
        badges.append(badge_trigger(fields["Trigger"]["value"]))
    if "Readiness" in fields:
        badges.append(badge_readiness(fields["Readiness"]["value"]))
    badge_html = f'<div class="badges">{"".join(badges)}</div>' if badges else ""

    pe = (pe_block(fields, "What is happening", "What is happening")
          + pe_block(fields, "What it means for them", "What it means for them")
          + pe_block(fields, "Your way in", "Your way in"))

    hook = render_hook(fields["Email hook"]) if "Email hook" in fields else ""

    stake = ""
    if "Stakeholder" in fields and fields["Stakeholder"]["value"]:
        stake = f'<p class="stake"><span class="pe lbl">Who to call:</span> {inline(fields["Stakeholder"]["value"])}</p>'

    ev = (ev_line(fields, "Trigger", "The trigger in full")
          + ev_line(fields, "Evidence", "Evidence")
          + ev_line(fields, "Call opener", "Call opener")
          + ev_line(fields, "Confidence", "Confidence"))
    details = (f'<details class="evidence"><summary>Show the evidence and call script</summary>'
               f'<div class="ev-body">{ev}</div></details>') if ev else ""

    rank_badge = f'<span class="rank">{esc(rank)}</span>' if rank else ""
    return (f'<div class="card"><h3>{rank_badge}<span>{inline(title)}</span></h3>'
            f'{badge_html}{pe}{hook}{stake}{details}</div>')


def render_angles(lines):
    text = "\n".join(lines)
    starts = [m.start() for m in re.finditer(r"^###\s+\d+\.", text, re.M)]
    if not starts:
        return render_paragraphs(lines)
    cards = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        cards.append(render_item(text[s:e].splitlines()))
    return "".join(cards)


def render_bet(bet_lines):
    """Render one '### Bet N: ...' block as an internal bet card."""
    title_line = bet_lines[0].strip()
    m = re.match(r"^###\s+(Bet\s+\d+):\s*(.*)$", title_line)
    label = m.group(1) if m else "Bet"
    title = m.group(2).strip() if m else title_line.lstrip("# ")
    fields, order, cur = {}, [], None
    for ln in bet_lines[1:]:
        s = ln.strip()
        fm = re.match(r"^([A-Z][A-Za-z '/-]+):\s?(.*)$", s)
        if fm:
            cur = fm.group(1).strip()
            fields[cur] = fm.group(2).strip()
            order.append(cur)
        elif s and cur:
            fields[cur] = (fields[cur] + " " + s).strip()
    rows = "".join(
        f'<p class="bet-field"><span class="bet-lbl">{esc(k)}:</span> {inline(fields[k])}</p>'
        for k in order if fields[k])
    return (f'<div class="bet-card"><h3 class="bet-h"><span class="bet-tag">{esc(label)}</span>'
            f'<span>{inline(title)}</span></h3>{rows}</div>')


def render_inference(lines):
    """Render the internal '## Reading the signals' block: intro prose + one card per bet."""
    text = "\n".join(lines)
    starts = [m.start() for m in re.finditer(r"^###\s+Bet\b.*$", text, re.M)]
    intro = render_paragraphs(text[:(starts[0] if starts else len(text))].splitlines())
    if not starts:
        return intro
    cards = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        cards.append(render_bet(text[s:e].splitlines()))
    return intro + "".join(cards)


SECTION_RENDERERS = [
    ("situation in plain english", "situation", render_paragraphs),
    ("jargon buster", "jargon", render_jargon),
    ("why this is a live prospect", "prospect-sec", None),  # special-cased below
    ("at a glance", "glance", render_table),
    ("angles", "angles", render_angles),
    ("reading the signals", "internal", render_inference),
    ("watch", "watch", render_watchlist),
    ("source ledger", "ledger", render_paragraphs),
]


def render(md_text):
    lines = md_text.splitlines()
    # Title
    title_m = next((re.match(r"^#\s+(.*)$", l) for l in lines if re.match(r"^#\s+", l)), None)
    title = title_m.group(1).strip() if title_m else "Outreach angles"
    company = title.split(":", 1)[1].strip() if ":" in title else title
    # Meta line + one-liner (before the first "## ")
    meta_line, oneliner = "", ""
    for l in lines:
        if l.startswith("## "):
            break
        if "Researched" in l and "|" in l:
            meta_line = l.strip()
        elif l.strip() and not l.startswith("#") and not meta_line and False:
            pass
    # one-liner: first non-empty non-heading line after the meta line, before first "## "
    seen_meta = False
    for l in lines:
        if l.startswith("## "):
            break
        if l.strip() == meta_line:
            seen_meta = True; continue
        if seen_meta and l.strip() and not l.startswith("#"):
            oneliner = l.strip(); break
    chips = ""
    if meta_line:
        parts = [p.strip() for p in meta_line.split("|") if p.strip()]
        chips = "".join(f'<span class="chip">{inline(p)}</span>' for p in parts)

    body_start = next((i for i, l in enumerate(lines) if l.startswith("## ")), len(lines))
    sections = split_sections(lines[body_start:])

    html_sections = []
    jargon_html = None
    for heading, sec_lines in sections:
        key = heading.lower()
        rendered, cls = None, "generic"
        for match, css_cls, fn in SECTION_RENDERERS:
            if match in key:
                cls = css_cls
                if css_cls == "prospect-sec":
                    rendered = f'<div class="prospect">{render_paragraphs(sec_lines)}</div>'
                    cls = "prospect-wrap"
                else:
                    rendered = fn(sec_lines)
                break
        if rendered is None:
            rendered = render_paragraphs(sec_lines)
        is_jargon = "jargon" in key
        is_internal = cls == "internal"
        sec_class = ("situation" if cls == "situation"
                     else "jargon-sec" if is_jargon
                     else "internal" if is_internal
                     else "")
        banner = ('<div class="internal-banner">Internal thinking aid: inferred, not confirmed. '
                  'Not client-facing.</div>') if is_internal else ""
        sec_html = f'<section class="{sec_class}"><h2>{inline(heading)}</h2>{banner}{rendered}</section>'
        if is_jargon:
            # The jargon buster always renders at the foot of the sheet, as a reference
            # the reader consults, regardless of where it sits in the source markdown.
            jargon_html = sec_html
        else:
            html_sections.append(sec_html)
    if jargon_html:
        html_sections.append(jargon_html)

    oneliner_html = f'<p class="oneliner">{inline(oneliner)}</p>' if oneliner else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(company)} - CBRE I&amp;L Outreach</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header class="masthead">
<p class="kicker">CBRE Industrial &amp; Logistics &middot; Outreach opportunities</p>
<h1>{inline(company)}</h1>
{oneliner_html}
<div class="chips">{chips}</div>
</header>
<main>{"".join(html_sections)}</main>
<footer class="foot">Generated from the gate-validated markdown source. Every figure and date traces to the Source Ledger. Plain-English presentation of the CBRE I&amp;L outreach-angles analysis; not investment advice.</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Render an Outreach Angles markdown sheet to self-contained HTML.")
    ap.add_argument("sheet", help="path to the gate-validated sheet .md")
    ap.add_argument("--out", help="output .html path (default: alongside the sheet)")
    ap.add_argument("--ledger", help="optional ledger path (recorded in a note; content not inlined)")
    args = ap.parse_args()
    try:
        with open(args.sheet, encoding="utf-8") as f:
            md = f.read()
    except OSError as e:
        print(f"cannot read sheet: {e}", file=sys.stderr)
        return 2
    out = args.out or os.path.splitext(args.sheet)[0] + ".html"
    html_text = render(md)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"wrote {out} ({len(html_text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
