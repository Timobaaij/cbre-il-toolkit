# Content Rules and Tone

These govern every slide and every sentence. The editorial gate (G6) and density check enforce them.

> **Canonical CBRE voice — and how it applies here.** The house CBRE tone-of-voice system (Clear / Bold / Connected, the seven writing principles, the volume control) lives in the `cbre-tone-of-voice` skill: `${CLAUDE_PLUGIN_ROOT}/skills/cbre-tone-of-voice/SKILL.md` (or `~/.claude/skills/cbre-tone-of-voice/SKILL.md` as a standalone skill). Read it once at the narrative-outline stage. **An intelligence brief is the most dialed-DOWN application of that voice** — clarity-first and subdued, never advertising. Pull from it only the principles that reinforce this register: *have a point of view, say it simply, less is more, convey action (active voice), no jargon, do not be egotistical*. **Explicitly do NOT use** the "dial-up" approaches (make a proclamation, intensify word choice, issue a challenge, create a maxim) — they read as a pitch and break the evidence-first stance. **On any conflict, the rules in this file win:** UK English, no em/en dashes, no pitch language, honesty over rhetoric, every claim sourced.

## Content rules
- **Explain, do not tabulate.** The brief tells the company's story in prose so the reader *understands* it. `prose` cells carry the story in full paragraphs; tables are evidence behind the narrative, never the way to make a point. Every material event (an acquisition, divestiture, JV, strategic pivot) gets a dedicated prose-led scene that says what happened, why, and what it means, never a single table row.
- **The relevance test.** Every slide must help a CBRE I&L leader understand where logistics or industrial demand is being created, destroyed or transferred, or identify a transaction or advisory angle. If not, cut it.
- **Lead with the "so what".** State the insight first, then the supporting explanation. The reader gets the point from the headline and the first line of each block.
- **It is an intelligence brief, not a pitch.** No generic recommendations. Any CBRE-relevance angle ties to a specific, sourced fact, and acknowledges incumbents and what is not yet known. This governs the opportunity-intersection answer especially: it is a demand-signal synthesis (where demand is created, destroyed or transferred, each tied to a Claim ID), never a services pitch; and the executive read (`bluf`) leads with the thesis and the single best-evidenced opportunity, not a sales line.
- **Specific numbers, all sourced.** Facility counts, sqm, capex, lease figures, dates. Every number traces to a Claim ID in the Source Ledger.
- **No generic filler.** Never "X is a leading global company". Every sentence carries a fact the reader can act on.
- **Complete, explanatory sentences, never fragments.** Prose paragraphs explain in connected sentences; a table cell may be compact but a `prose` cell may not be a half-sentence. The density gate rejects a prose cell too short to be a real sentence. This is the rule that keeps the deck from reading like filled tables.
- **No em or en dashes anywhere.** Use commas, semicolons, colons, or separate sentences. The builder sweeps for them and G6a checks; the hyphen is fine in compounds (build-to-suit, sale-and-leaseback) and prefer "to" for ranges.

## The density rules (these make the brief dense AND explanatory, not thin and not a matrix)
1. **Prose fills the story slides.** A prose-led scene carries one to four full paragraphs that explain; the renderer auto-fits each cell so its text fills the cell. A prose cell too short to be a sentence is a density defect.
2. **Every table carries a rightmost "I&L read" column**, written as a CBRE inference, never a restatement of the row. The density check asserts the last cell of every data row is non-empty.
3. **Every slide lands its point.** Every scene carries a `lead` line stating the so-what under the headline, and every `table` carries its rightmost analytical-read column; every divider carries a one-line section thesis. No slide is left mostly empty; where one under-fills, the fix is real validated content, not stretching, and the visual gate (G7) confirms this on the rendered pixels.

Keep prose paragraphs to three or four sentences so the auto-fit stays readable. Use short stat values with the unit in the label (a 72pt value like "EUR 17.8bn" wraps; use "17.8"). Cap rows per table (about 8 network, 7 stakeholder, 6 challenge, 5 competitor). Build analysis into paragraphs, read columns and bands rather than leaving white space.

## Tone and register
Write as a senior CBRE strategist briefing a managing director: confident, direct, analytical. Not consultancy-speak, not equity-research jargon. The voice of someone who has walked a warehouse floor and respects the reader's time. UK English throughout (optimise, centre, programme, organisation). Honesty over rhetoric: struck claims, intel gaps, thin sources and incumbents are reported straight.
