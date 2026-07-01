# Output template, worked example, final QA (Stage 6)

The deliverable is **three artefacts**:
1. the **sheet in markdown** (structure below), which is the gate-validated source of truth;
2. the **self-contained HTML file** rendered from that validated markdown by `helpers/render_html.py` (this is what the broker actually reads and shares); and
3. the **Source Ledger** that backs every claim (schema in `evidence-and-ledger.md`).

Author the markdown, run the gate on the markdown, THEN render the HTML from the validated markdown. The markdown is never skipped: it is where the fact-checking happens. The HTML is a faithful, prettier presentation of the same content, with the finance detail tucked behind collapsible sections so it is digestible by default.

## Design principles

- **Plain English leads; the finance rigour supports.** A broker who is not finance-trained must be able to read the top of the sheet and understand what is going on and why to call, without a glossary in hand. The rigorous, sourced evidence stays in the document (it is the skill's whole value) but sits below or behind a collapsible section, not in the reader's face.
- **Explain the jargon, always.** Every specialist term the sheet uses (Schuldschein, Lazard, sale-and-leaseback, covenant, EBITDA, activist investor, carve-out, and so on) is defined in plain words in a Jargon buster, placed at the foot of the sheet as a reference to consult. Assume the reader is smart but not an MBA. (The renderer always emits the jargon buster last, so its position in the markdown does not matter, but author it near the foot for a clean source.)
- **Say what it means for THEM and for the broker.** Each opportunity is written so the reader sees, in plain words, what is happening, what it means for the company, and what their way in is, before the evidence.
- **Rank on developability; label trigger strength.** As in v2: the single ranked list is ordered by how developable each opportunity is (the size and likelihood of an I&L transaction), with trigger strength shown as a label (Event-driven = a dated forcing function; Structural = a sourced, company-specific inefficiency, fenced to two sourced facts), never a gate. The freshness split lives inside each item as a Readiness label (Send now / Verify first: <the one fact>).
- **Length is not capped.** The 1-to-2-page limit is retired. The sheet should be as long as it needs to be to explain the situation clearly; a broker would rather read three clear pages than one dense one.

## The markdown structure (author to this exactly; the gate and renderer key on it)

No em or en dashes. Full sentences in the prose. Reproduce figures verbatim from the source. Tag facts `[FACT]` / `[INFERENCE]` / `[ASSUMPTION]` inline (brackets exactly; the gate keys on them).

```
# Outreach angles: [Company]
[Geography lens] | Researched [run date] | Listed/Private | Focus: [focus or "none set"] | Door: [door or "none set"]

[One plain sentence saying what the company makes or does, its scale, and where it is based.]

## The situation in plain English
Four to six short sentences, no jargon, telling the whole story a non-finance broker can follow: what
the company is going through, what is forcing the issue, and (last sentence) the gap an I&L adviser can
fill. This replaces the old dense "Snapshot". Any specialist term used here must appear in the Jargon
buster below.

## Why this is a live prospect for us
Two to four sentences in plain English: why this company is worth an I&L adviser's time right now, tying
the situation above to the opportunities below (owned property as an untapped cash lever, a footprint in
motion, a decision window, and so on).

## At a glance
A scannable table, one row per ranked opportunity, so the whole sheet can be grasped in under a minute:
| # | The opportunity, in one line | How big / likely (developability) | The trigger | Send now or check first | Who to call |
| --- | --- | --- | --- | --- | --- |
| 1 | [plain one-liner] | High/Medium/Low: [why] | Event-driven/Structural: [plain + date] | Send now / Check first | [role + name] |

## Angles (ranked)
Ranked by developability, highest first. Each item is written plain-English-first, then the evidence.

### 1. [Title that names the specific opportunity in plain words, not a category]
What is happening: [one or two plain sentences, no jargon, on the concrete event or situation]
What it means for them: [one or two plain sentences on the consequence for the company: why they would care]
Your way in: [one or two plain sentences on why this is the broker's opening and what to lead with]
Developability: [High / Medium / Low]. [One line: the size and transactability of the I&L opportunity.]
Trigger: [Event-driven / Structural]. [The dated event, or the two sourced facts of the structural tension, with source and date; ageing evidence flagged.]
Readiness: [Send now] OR [Verify first: <the single fact to confirm before sending>]
Email hook:
  - First line: [an opening line referencing something specifically true about THEM, not a template]
  - The one consequence: [the single consequence that makes it matter to them now]
  - Soft ask: [a low-friction ask, never a hard pitch]
Call opener: [one line for a live conversation, peer-referenced and problem-forward, phrased as a question; grounded per the peer-pattern rule in evidence-and-ledger.md]
Evidence: [the hard, sourced facts behind this opportunity, each with source and date and a `[FACT]` / `[INFERENCE]` / `[ASSUMPTION]` tag; a structural trigger shows its two sourced facts and the inferred tension. This is the field the HTML tucks behind a collapsible "Show the evidence" toggle.]
Stakeholder: [the role and name to approach, why that person, and a reachability note tied to the stated door]
Confidence: [High / Medium / Low, set by the weakest link, one-line reason]

### 2. [...]
### 3. [...]   (ranked by developability; the list may be as few as zero, and is NOT padded to a number)

## Watch-list
Real but not-yet-developable or not-yet-sourced signals, one plain line each, with the dated event that
would activate them. Generic ESG pledges, ongoing expansion trends with no company-specific anchor, and
clockless background signals live here, never in the ranked list.

## Jargon buster
Placed at the foot of the sheet, as a reference the reader consults. One bullet per specialist term
actually used anywhere above, each defined in plain words (a sentence or two, a plain-English analogy is
welcome). If the sheet genuinely uses no jargon, write the single line "None needed for this sheet."
Example bullet:
- **Sale-and-leaseback**: sell a building you own to a property investor and immediately rent it back on a long lease, so you get a lump of cash now but keep using the building.

## Source Ledger
Either the full claim-by-claim table (angle ref, claim as stated, value as found, source + URL, date,
access date, recency grade, F/I/A) or a one-line pointer to a separate ledger.md that carries it plus the
European footprint coverage map and the `RECONCILIATION: RECONCILED` or `RECONCILIATION: UNRESOLVED GAP`
status line. Every ageing-graded row carries its refresh outcome (`refresh: confirmed-ageing` or
`refresh: none`). See evidence-and-ledger.md for the schema.
```

Required per item (the gate FAILs a missing one): `What is happening:`, `What it means for them:`, `Your way in:`, `Developability:`, `Trigger:`, `Readiness:`, `Email hook:`, `Call opener:`, `Evidence:`, `Stakeholder:`, `Confidence:`. Required document sections when there are ranked items: `## The situation in plain English`, `## Jargon buster`, `## Why this is a live prospect for us`, `## At a glance`, `## Angles`. A zero-item "do not call" sheet still needs `## The situation in plain English`, `## Angles`, and either a watch-list or a no-call verdict.

## Rendering the HTML (Stage 6, after the gate passes)

Run the renderer from the skill directory (resolve it against the skill's own folder; on Windows run it with native Python via the MCP shell):

`python helpers/render_html.py <sheet.md> [--out <sheet.html>] [--ledger <ledger.md>]`

It produces one self-contained `.html` file (all CSS inline, no external assets, opens in any browser, prints to PDF). It is CBRE-branded, leads with the situation and the at-a-glance table, shows each opportunity as a card with the plain-English fields and the email hook prominent, and puts each item's `Evidence:`, `Call opener:` and `Confidence:` inside a collapsible "Show the evidence and call script" toggle so the default view is digestible. Deliver the `.html` as the primary artefact, with the validated `.md` and the ledger alongside.

## Worked example (illustrative, dates are placeholders, not real)

See `Gerresheimer/sheet-plain-english.md` in the project for a full worked example of the markdown structure: a levered pharma-packaging manufacturer with a dated refinancing deadline and an untapped owned-property estate, whose strongest opportunity (a sale-and-leaseback to raise cash before the refinancing) leads the list, each opportunity written plain-English-first with the evidence beneath, a jargon buster defining Schuldschein, Lazard, covenant, sale-and-leaseback and the rest, and an at-a-glance table.

The item to **reject from the ranked list** (watch-list at best): "As sustainability rises up the agenda, we would welcome a conversation about your net-zero commitments." No company-specific anchor, no consequence, heard from ten brokers already.

## Final QA self-check (before declaring the sheet ready)

Read the whole sheet once with fresh eyes and confirm:
- A broker with no finance training could read `## The situation in plain English` and the `## At a glance` table and understand what is going on and why to call, without help.
- Every specialist term used anywhere on the sheet is defined in plain words in the `## Jargon buster` (Schuldschein, Lazard, covenant, EBITDA, sale-and-leaseback, activist, carve-out, and the like). No undefined jargon survives.
- Every ranked item has `What is happening`, `What it means for them` and `Your way in` in plain English, before the evidence.
- The list is **ranked by developability**, highest first, both labels (Developability and Trigger) visible; a high-developability, weak-trigger opportunity leads with its trigger labelled, never demoted for lacking a date.
- Every item has either an **Event-driven** trigger (a dated forcing function) or a fenced **Structural** trigger (two company-specific sourced facts and the inferred tension). Generic trends are on the watch-list.
- Every item carries a **Readiness** label (`Send now`, or `Verify first:` naming the single fact) and an **Email hook** with all three parts, whose first line could not be sent to a different company unchanged.
- Every figure, date and named fact traces to a dated source in the Source Ledger; the load-bearing numbers were re-retrieved; no unverified anchor ships as a `Send now`.
- Fact, inference and assumption are distinct throughout; any peer pattern is grounded or framed as experience, never an invented statistic.
- The ranked list may be as few as zero (then the watch-list and a no-call verdict still ship); it is never padded to a number.
- Footprint is reconciled against all-Europe coverage, never sales geography; the ledger carries the coverage map and `RECONCILIATION: RECONCILED` only when every country is evidence-positive-with-source or evidence-absent-after-a-real-native-language-search, otherwise `UNRESOLVED GAP` (which ships and only bars saturation wording).
- Nothing on the sheet says or implies "we found no X" as evidence; a centralised or single-DC model appears only when positively sourced.
- Every ageing trigger had the recency-refresh micro-pass and its ledger row carries `refresh: confirmed-ageing` or `refresh: none`.
- Every chase pointer was resolved or logged as a gap before authoring; the gate is run with `--evidence <evidence.md>`.
- UK English (when English). No em or en dashes anywhere.
- **The gate has passed and the HTML has been rendered:** `python helpers/final_gate.py <sheet.md> --ledger <ledger.md> --evidence <evidence.md>` returns `STATUS: PASS`, then `python helpers/render_html.py <sheet.md> --ledger <ledger.md>` produces the self-contained HTML. Fix any FAIL and re-run before delivery.
