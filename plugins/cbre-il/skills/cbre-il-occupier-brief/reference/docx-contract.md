# The markdown contract and the render

The renderer is `helpers/render_docx.py`. **Pure Python standard library**: no python-docx, no node,
no npm, nothing to install. It writes WordprocessingML into the zip directly, so it behaves the same
on Windows, macOS, Linux and in the Claude sandbox.

Do not hand-tune styling in the markdown and do not build the DOCX any other way. The styling below
is already implemented.

## Run it

From the run folder:

```bash
python helpers/render_docx.py working/brief.md deliverables/Testco_IL_OccupierBrief.docx
```

The output directory is created if it does not exist. Paths are relative to the run folder; there is
no hardcoded output location. On Windows the helpers apply the extended-length path prefix
automatically, but keep the run folder shallow anyway, because Word and Excel do not.

Flags:

| Flag | Effect |
|---|---|
| (none) | Lints house style first and **refuses to render** on an error |
| `--allow-dashes` | Downgrades em and en dash errors to warnings. For a brief that is mostly verbatim quotes. Needs a reason. |
| `--no-lint` | Skips the lint. Do not use it to get past a gate. |

The lint blocks on an em or en dash outside a double-quoted span, and on a lowercase US spelling. It
warns on a capitalised US spelling, which is usually a proper noun (the Global Logistics Center) and
usually fine.

Then the ledger and the final gate:

```bash
python helpers/ledger.py xlsx deliverables/Testco_Source_Ledger.csv
python helpers/final_gate.py --dir .
```

## The contract

````markdown
---
eyebrow: CBRE  |  INDUSTRIAL & LOGISTICS
title: OCCUPIER BRIEF
subject: Testco plc (LSE: TST): UK grocery distribution
descriptor: Getting the team match fit before the 22 September meeting
prepared: Confidential: internal pursuit material  |  CBRE Industrial & Logistics  |  Prepared September 2026
footer_label: CBRE  |  Industrial & Logistics
---

## The 30-second version
Prose. Wrapped lines join into one paragraph, so wrap at 100 characters for a readable diff.
**Bold** and *italic* work inline anywhere.

## Testco IS / IS NOT
| Testco IS | Testco IS NOT |
|---|---|
| A network mid-consolidation | A business looking for one more shed |

## At a glance
| Headquarters | Milton Keynes, UK |
| Revenue FY25 | GBP 4.2bn, up 6.1 per cent |

## What is likely on the mind of the Head of Real Estate
*Sarah Whitcombe, Property Director since 2023.*
- **The Daventry expiry.** 620,000 sq ft falls vacant in March 2027 with no announced replacement.

## Pocket talking points
- "You have a 2027 lease event and a 2028 network target. Those two dates need to agree."

## Sources
Narrative list keyed to the ledger, then: figures as reported; management estimates subject to revision.

FOOTER: Prepared September 2026. Confidential: internal CBRE material. Verify time-sensitive figures before any client-facing use.
````

## What the parser does with each construct

| Markdown | Renders as |
|---|---|
| Front matter | The masthead. `eyebrow`, `title` and `prepared` have sensible defaults; `subject` and `descriptor` are optional and recommended; `footer_label` overrides the page footer. |
| `##` or `#` | Green section header, 13pt bold, green bottom rule, kept with the text below it |
| `###` or a line that is only `**Bold**` | Bold ink subheading, 11pt |
| `*a whole line in italics*` | Grey italic label. This is how the persona post-holder line renders. |
| `- ` or a bullet character | A bullet, 620 indent, 300 hanging. Wrapped continuation lines join into the same bullet. |
| Consecutive prose lines | One paragraph. A blank line starts a new one. |
| `**bold**`, `*italic*` | Inline runs, parsed everywhere including inside table cells |
| `FOOTER:` | The small grey italic caveat with a grey top rule. Put it last. |

## Table modes, chosen automatically by the section

| Condition | Mode |
|---|---|
| Section heading contains "at a glance", "quick facts" | **Key and value**: first column tinted and bold, no header row. Emit rows only. |
| The top row contains both `IS` and `IS NOT` | **Framing**: green header row with white bold text, tinted body rows |
| Anything else (a stay-versus-go matrix, a peer comparison) | **Generic**: green header row, alternating tinted body rows |

Include a `|---|---|` separator row after a header row; the parser drops it. Column widths are fixed
and even, except key-and-value, which is 34 per cent for the label.

## The styling, for reference only

| Element | Spec |
|---|---|
| Font | Calibri throughout |
| Page | A4, 11906 by 16842 DXA, 1 inch margins, content width 9026 |
| Eyebrow | 8pt bold, grey 595959, caps, letter-spaced |
| Title | 18pt bold, CBRE green 006A4D, caps |
| Subject | 13pt bold, ink 1A1A1A |
| Descriptor | 10.5pt italic, grey |
| Prepared line | 8.5pt grey, green bottom rule |
| Section header | 13pt bold green, green bottom border |
| Subheading | 11pt bold ink |
| Body | 10.5pt ink, 1.08 line spacing |
| Bullets | 10.5pt, green bullet glyph, 620 indent, 300 hanging |
| Table header | Green fill, white bold 10pt |
| Table body and at-a-glance label | Tint EAF2EF, hairline rules C9D9D2 |
| Caveat | 8pt grey italic, grey top rule |
| Page footer | 7.5pt cement 7F8480, label left, page number right, grey top rule |

## If something looks wrong

The DOCX is a zip. Read it back rather than guessing:

```bash
python -c "import zipfile;z=zipfile.ZipFile('deliverables/Testco_IL_OccupierBrief.docx');print(z.read('word/document.xml').decode()[:2000])"
```

`final_gate.py` already checks that every part is well formed and that every `##` heading in
`brief.md` survived into the rendered text.
