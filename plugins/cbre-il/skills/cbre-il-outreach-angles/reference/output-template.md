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
- **Anchor figures are primary-sourced.** The load-bearing figure behind an item (the trigger date, a debt or capex number, a size) cites a primary source (filing, IR, RNS, results, statutory register) or carries a second corroborating source. A number cited only to a data aggregator (Yahoo, investing.com and the like) does not belong under a senior operator's name; the gate raises an advisory WARN on aggregator hosts.
- **Never frame an inferred asset as owned.** If the fact that makes an item transactable is an *unconfirmed* ownership (a freehold you inferred, not sourced), the title and the at-a-glance line pose the open question ("confirm ownership, then sale-and-leaseback"), never "the owned warehouse". If the sourced evidence actually points away from ownership (e.g. a build-to-suit sold to a third-party investor), the item is a hypothesis to verify or a watch-list line, not a confident ranked slot.
- **Favour the strongest few; do not pad to a number.** Five to seven is a ceiling, not a target. A thin, highly speculative or barely-sourced angle belongs on the watch-list, not padded into the ranked list to reach five. Three sharp, well-anchored opportunities beat six where two are filler.
- **Length is not capped, but tight beats bloated.** The 1-to-2-page limit is retired; the sheet should be as long as it needs to explain the situation clearly. But every angle should earn its place: prefer three clear pages of real opportunities to six padded ones. The gate WARNs past a rough word budget as a bloat smell test.

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

## Why now, in one line
Optional but encouraged. A single sentence naming the sharpest reason to act THIS quarter, so a broker
with twenty seconds gets the hook. Keep it to one line, do not just restate the situation, and do NOT put
the word "optional" in the heading you actually write (it would show on the broker's sheet).

## At a glance
A scannable table, one row per ranked opportunity, so the whole sheet can be grasped in under a minute:
| # | The opportunity, in one line | How big / likely (developability) | The trigger | Send now or check first | Who to call |
| --- | --- | --- | --- | --- | --- |
| 1 | [plain one-liner] | High/Medium/Low: [why] | Event-driven/Structural: [plain + date] | Send now / Check first | [role + name] |

## Angles (ranked)
Ranked by developability, highest first, in NON-INCREASING band order (all High items, then Medium, then Low; the gate FAILs an out-of-order list). Within a band, order by trigger strength then anchor quality. An item whose anchor fact is an [INFERENCE] is capped at Medium (see the rubric), so an unverified premise never leads the sheet. Each item is written plain-English-first, then the evidence.

### 1. [Title that names the specific opportunity in plain words, not a category]
What is happening: [one or two plain sentences, no jargon, on the concrete event or situation]
What it means for them: [one or two plain sentences on the consequence for the company: why they would care]
Your way in: [one or two plain sentences on why this is the broker's opening and what to lead with]
Developability: [High / Medium / Low], stating BOTH sub-factors. [Name the SCALE (multi-site / portfolio sale-and-leaseback / defined multi-building mandate = High; a single significant site or one transaction type = Medium; a single small unit / prospective / hypothesis-to-test = Low) AND the NEAR-TERM likelihood (a named decision-owner plus a live dated workstream raises it). Anchor-quality cap: if the ANCHOR fact (the one that makes it transactable, e.g. that they OWN the plants) is [INFERENCE]/[ASSUMPTION], this line cannot be High; cap at Medium until the anchor is a sourced [FACT]. See the rubric in evidence-and-ledger.md.]
Trigger: [Event-driven / Structural]. [The dated event, or the two sourced facts of the structural tension, with source and date; ageing evidence flagged.]
Readiness: [Send now] OR [Verify first: <the single fact to confirm before sending>]
Email hook: [three quotation-ready sentences the broker can PASTE AND SEND, in the second person to the prospect. Write the actual words, never an instruction about them. FAIL-by-example: bad = "reference their February capex guidance"; good = "Saw your February guidance to more than double growth capex into the ConvaFoam and Esteem lines." Do NOT begin the first line with an instruction verb (note / reference / mention / highlight / flag).]
  - First line: [a sendable opening sentence referencing something specifically and verifiably true about THEM]
  - The one consequence: [the single consequence that makes it matter to them now, as a sentence]
  - Soft ask: [a low-friction ask as a sentence, never a hard pitch]
  HEDGE RULE (Verify-first items): when Readiness is "Verify first", the first line uses ONLY [FACT]s and the verify-first fact appears in the soft ask phrased as a QUESTION ("worth a short call to check which core plants are freehold"), never asserted. A pasteable hook must not make an unverified premise easier to send.
Call opener: [one line for a live conversation, peer-referenced and problem-forward, phrased as a question; grounded per the peer-pattern rule in evidence-and-ledger.md]
Evidence: [the hard, sourced facts behind this opportunity, each with source and date and a `[FACT]` / `[INFERENCE]` / `[ASSUMPTION]` tag; a structural trigger shows its two sourced facts and the inferred tension. The load-bearing anchor figure must cite a primary source or a second corroborating source, not a data aggregator alone. This is the field the HTML tucks behind a collapsible "Show the evidence" toggle.]
Stakeholder: [the role and name to approach, why that person, and a reachability note tied to the stated door]
Confidence: [High / Medium / Low, set by the weakest link, one-line reason]

### 2. [...]
### 3. [...]   (ranked by developability; the list may be as few as zero, and is NOT padded to a number)

## Watch-list
Real but not-yet-developable or not-yet-sourced signals, one plain line each, with the dated event that
would activate them. Generic ESG pledges, ongoing expansion trends with no company-specific anchor, and
clockless background signals live here, never in the ranked list.

## Reading the signals (inferred, not confirmed)
INTERNAL use, not client-facing. Reasoned bets on moves the company has NOT announced, built by
connecting sourced facts already in the evidence file (Stage 3.5). Each is an inference, labelled as one,
with the public signal that would confirm it. Zero to four bets; do not pad. These are NOT opportunities
to pitch and NOT ranked angles: they carry no developability or readiness label, are not in the at-a-glance
table, and never count toward the five-to-seven. They are where to point the next research pass and the
next conversation. The value is the tripwire, not the guess.

### Bet 1: [one plain sentence naming the un-announced move]
The bet: [what you think they are weighing, in plain words] [INFERENCE]
Shape: [what, roughly where, roughly how big, if inferable from the facts]
Why I think this: [the reasoning chain, naming the two or more sourced facts and the logic joining them; reference the evidence ids, each fact tagged [FACT]]
What would confirm it: [the single most likely public tripwire, mapped to a named source class (investment-incentive or zone register, planning or permit portal, company or statutory-registry filing, clustered hiring, developer or contractor PR)]
What would kill it: [the disconfirming evidence or event, stated plainly]
Confidence and horizon: [Low / Medium, and the rough time window; be honest, most start Low]

### Bet 2: [...]   (hard cap of four; if there is no disciplined bet, write "No inferred bets clear the fence this run" and stop)

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

The worked-example shape (illustrative, not a real company): a levered manufacturer with a dated refinancing deadline and an owned-property estate. Its ranked list leads with the highest-developability opportunity whose ANCHOR is a sourced `[FACT]` (for example a multi-plant carve-out with a dated separation decision), while a larger-in-theory but inference-anchored play (a sale-and-leaseback whose freehold is only inferred) sits BELOW it, capped at Medium under the anchor-quality rule and titled as an open question ("freehold to confirm"), never as "owned". Each opportunity is written plain-English-first with the evidence beneath; an at-a-glance table opens the list; a jargon buster at the foot defines the specialist terms; and the internal `## Reading the signals` block may carry a few fenced abductive bets, each with a tripwire and a disconfirming line. (Live client runs are kept outside the skill folder.)

The item to **reject from the ranked list** (watch-list at best): "As sustainability rises up the agenda, we would welcome a conversation about your net-zero commitments." No company-specific anchor, no consequence, heard from ten brokers already.

## Final QA self-check (before declaring the sheet ready)

Read the whole sheet once with fresh eyes and confirm:
- A broker with no finance training could read `## The situation in plain English` and the `## At a glance` table and understand what is going on and why to call, without help.
- Every specialist term used anywhere on the sheet is defined in plain words in the `## Jargon buster` (Schuldschein, Lazard, covenant, EBITDA, sale-and-leaseback, activist, carve-out, and the like). No undefined jargon survives.
- Every ranked item has `What is happening`, `What it means for them` and `Your way in` in plain English, before the evidence.
- The list is **ranked by developability**, highest first, in **non-increasing band order** (High, then Medium, then Low); each Developability line **names both sub-factors** (scale and near-term likelihood); an item whose **anchor fact is [INFERENCE]/[ASSUMPTION] is capped at Medium** and does not lead on scale alone. A high-developability, weak-trigger opportunity still leads over a thin dated one, with its trigger labelled.
- Every item has either an **Event-driven** trigger (a dated forcing function) or a fenced **Structural** trigger (two company-specific sourced facts and the inferred tension). Generic trends are on the watch-list.
- Every item carries a **Readiness** label (`Send now`, or `Verify first:` naming the single fact) and an **Email hook** that is a **pasteable draft**: three sentences the broker could send verbatim (not "reference their capex" but the actual sentence), whose first line could not be sent to a different company unchanged and does not begin with an instruction verb. On a **Verify-first** item, the first line uses only [FACT]s and the unverified fact is a question in the soft ask, never asserted.
- **Send now** items carry at least one [FACT] on the Trigger line; **Structural** triggers rest on two separately-sourced [FACT]s plus the inferred tension, on the Trigger line.
- Every figure, date and named fact traces to a dated source in the Source Ledger; the load-bearing numbers were re-retrieved; no unverified anchor ships as a `Send now`. Each item's **anchor figure cites a primary source or a corroborating second source**, not a data aggregator alone.
- No item is **framed as "owned"** when ownership is only inferred: its title and at-a-glance pose the open question, and an item whose evidence points away from ownership is a watch-list line, not a confident ranked slot.
- The ranked list is **not padded**: every angle earns its place, and a thin or highly speculative one sits on the watch-list rather than filling a slot to reach five.
- Fact, inference and assumption are distinct throughout; any peer pattern is grounded or framed as experience, never an invented statistic.
- The internal `## Reading the signals` block (if present) is fenced: at most four bets, each grounded in two or more cited `[FACT]`s with a shown reasoning chain, a real-estate consequence, a named public tripwire and a disconfirming line, tagged `[INFERENCE]`/`[ASSUMPTION]`; it is marked internal, is not in the at-a-glance table, and no bet carries a developability or readiness label. Zero bets is fine; never pad it.
- The ranked list may be as few as zero (then the watch-list and a no-call verdict still ship); it is never padded to a number.
- Footprint is reconciled against all-Europe coverage, never sales geography; the ledger carries the coverage map and `RECONCILIATION: RECONCILED` only when every country is evidence-positive-with-source or evidence-absent-after-a-real-native-language-search, otherwise `UNRESOLVED GAP` (which ships and only bars saturation wording).
- Nothing on the sheet says or implies "we found no X" as evidence; a centralised or single-DC model appears only when positively sourced.
- Every ageing trigger had the recency-refresh micro-pass and its ledger row carries `refresh: confirmed-ageing` or `refresh: none`.
- Every chase pointer was resolved or logged as a gap before authoring; the gate is run with `--evidence <evidence.md>`.
- UK English (when English). No em or en dashes anywhere.
- **The gate has passed and the HTML has been rendered:** `python helpers/final_gate.py <sheet.md> --ledger <ledger.md> --evidence <evidence.md>` returns `STATUS: PASS`, then `python helpers/render_html.py <sheet.md> --ledger <ledger.md>` produces the self-contained HTML. Fix any FAIL and re-run before delivery.
