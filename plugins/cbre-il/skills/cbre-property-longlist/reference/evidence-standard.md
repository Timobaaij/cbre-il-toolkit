# The Data Honesty Standard (read first)

The single governing rule of this skill: **nothing reaches a card that does not trace to a real input, and every unknown is an explicit sentinel, never invented.**

## The sentinels
- `"tbd"` - a string field whose value is genuinely not in any source (most specs).
- `"—"` - specifically `landPrice` when unknown (matches the reference).
- `null` - a sortable numeric (`warehouseRentVal`, `expansionParkVal`) or `reit` when unknown.
- Never emit JS `undefined`, and **never drop a key the chrome reads** - emit the sentinel instead. The chrome calls string methods on some fields (e.g. `warehouseRent.replace(...)`), so a missing key crashes the whole render. `merge.canonicalize()` fills every chrome-read key.

## Ambiguity is a QUESTION, asked during the run - not a caveat afterwards

A disclosed assumption is better than an invented value, but it is not the best available
answer. When the pipeline cannot know something, the honest move is to **ask, while the answer
can still change the deliverable** - not to write a line into a Gaps Report that is read after
the dashboard has already shipped.

The skill has always done this for five things: a deck that needs reading (exit 3), an
uncertain photo match (exit 9), an ambiguous property match or a value conflict (exit 10), a
language it does not carry (exit 11), and free-text data that needs translating (exit 12).
**Exit 13 is the general channel** for everything else:
an area or rent whose source states no unit, a deck that looks like it holds more properties
than it produced, two sources implying different property counts. See `helpers/clarify.py`.

Three rules make it safe:

1. **Ask once, then ship honestly.** Every question is asked exactly once per work dir. An
   answer is recorded durably; a question left unanswered is *also* never re-asked - it falls
   through to the disclosed gap. So the run always converges. This is not a preference: the QA
   window is a SINGLE review pass because "keep asking until it is clean" never terminated, and a
   new asking channel must not reintroduce that.
2. **Batched.** All questions ride ONE hand-off, the way exit 10 carries pairs and value
   conflicts together. N ambiguities cost one interruption, not N.
3. **The right answerer.** `asked_of: "agent"` is a reading call an isolated sub-agent makes
   from the source; `asked_of: "broker"` is a decision no amount of reading can settle. Python
   only ever asks - it never answers, and it never guesses when no answer comes.

An answered unit is a **source statement**, recorded with provenance naming it as confirmed,
and it fills `areaUnit`/`rentUnit` the way a deck printing the unit would. That is why it is a
separate channel from `work/overrides.json`, which may never set those fields: an override is a
*blind* correction applied before the dataset unit vote, and correcting the one record that
tips the vote would silently relabel every figure. Asked, answered, attributed is the opposite
of silent.

## What is forbidden
- Inventing a rent, area, clear height, date or coordinate that no source states.
- "Rounding up" an unknown to a plausible number.
- Silently picking one side of a conflict without recording the other.
- Letting a fuzzy/low-confidence match through as if certain.

## What is required
- Every populated field has a ledger row tracing it to `source_file` + `source_locator` (`reference/source-traceability.md`).
- Every `"tbd"` is also a ledger row (the positive record that the value was genuinely absent) and appears in the Gaps Report with a "how to close it" note.
- Conflicts keep both values: the winner in `canonical.json`, the loser in the ledger `conflict_note`.
- Coordinates filled by geocoding are flagged `coordsApprox: true`.
- Enriched figures (workforce) carry an `*AsOf` date and a `sources` citation, or stay `null`.

## How it is enforced
- **G-honesty** (isolated reviewer): confirms every `"tbd"`/`"—"`/`null` is genuinely unknown (not hiding a value present in the inputs) and that no number exists without a source. Blocks on any HIGH.
- **G-trace** (isolated reviewer): samples fields and confirms each appears at its cited locator; an untraceable field is struck to `"tbd"`.
- The Gaps Report makes the unknowns the broker's action list, not a hidden weakness.

Honesty is the product here. A defensible longlist a broker can hand a client is worth more than a falsely complete one.
