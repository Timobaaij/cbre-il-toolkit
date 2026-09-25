# Spec format for build_letter.py

The builder takes one JSON file. A complete working example is in
`assets/example_spec.json` (an anonymised occupier search). Copy it and change the content;
do not change the structure unless the letter needs it.

## Markup inside any string

- `[[text]]` becomes a yellow-highlighted `[text]`: use for anything unknown.
- `**text**` becomes bold (use sparingly, e.g. the lead-in of a fee cell).

## Top-level fields

| Field | Required | Meaning |
|---|---|---|
| `title` | yes | Cover title, e.g. "Engagement Letter [Client]". Also the default page header and document title. |
| `client` | no | Client name, written to the document properties. |
| `header` | no | Page header text if different from `title`. |
| `footer_line` | no | Footer text. Default "CBRE \| Industrial & Logistics". Use "CBRE \| Capital Markets \| Industrial & Logistics" for capital markets letters (this longer line wraps onto two lines, as in the original template). |
| `author` | no | Document author property. |
| `cover_lines` | yes | Addressee block on the cover: legal entity, Attn., street, postcode and city, country, registration number. |
| `salutation` | no | Default "Dear [[Name]],". |
| `letter_paragraphs` | yes | The letter page paragraphs (usually four). |
| `closing_greeting` | no | Default "Yours sincerely,". |
| `signatories` | yes | List of `{"name", "role"}`; laid out two per row. |
| `blocks` | yes | Everything after the letter page, in order (see below). |
| `thank_you_contacts` | yes | List of `{"name", "role", "phone", "email"}` for the back page. |

## Block types (each block is a one-key object)

| Block | Example | Renders as |
|---|---|---|
| `h1` | `{"h1": "The instruction"}` | Large green section heading |
| `h2` | `{"h2": "The requirement"}` | Teal subheading |
| `h3` | `{"h3": "Phase 1: Search and shortlist"}` | Small heading above bullets |
| `p` | `{"p": "Text"}` | Justified body paragraph |
| `bullets` | `{"bullets": ["a", "b"]}` | Bullet list |
| `note` | `{"note": "Areas are indicative."}` | Italic small note |
| `empty` | `{"empty": true}` | Blank line |
| `pagebreak` | `{"pagebreak": true}` | New page |
| `table` | see below | Branded table |
| `approval` | see below | "For approval" heading and signature grid |

### table

```json
{"table": {"style": "detail", "header": ["Item", "Detail"], "rows": [["Purpose", "..."]], "widths": [4253, 5657]}}
```

- `style`: `detail` (grey two-column), `team` (celadon, any number of columns; use for the
  team table and option comparisons) or `fee` (grey two-column, cells can hold several
  paragraphs).
- A cell can be a string or a list of strings (one paragraph each).
- `widths` in DXA, optional; total width is about 9,975. Good defaults: detail
  `[4253, 5657]`, team `[2150, 3900, 3925]`, options `[2575, 3700, 3700]`.
- Rows never split across pages; header rows stay with the first data row.

### approval

```json
{"approval": {"cbre_entity": "CBRE Limited", "client_entity": "[[Client legal entity]]",
              "cbre_name": "[[Signatory]]", "cbre_function": "[[Function]]",
              "client_name": "", "client_function": "",
              "enclosures": ["CBRE Limited Standard Terms of Business"]}}
```

Omit the approval block for scope-only letters (separate agreement follows).

## Layout tips learned in practice

- Put `{"pagebreak": true}` before "Our team" and before "Remuneration" if the heading
  would otherwise sit alone at the bottom of a page. Check the render.
- Put `{"empty": true}` before the approval block, not after it (a trailing blank line can
  push the section break onto an empty page).
- Keep the approval block on the same page as the closing lines when it fits.
