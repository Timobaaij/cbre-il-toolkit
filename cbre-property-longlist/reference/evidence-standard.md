# The Data Honesty Standard (read first)

The single governing rule of this skill: **nothing reaches a card that does not trace to a real input, and every unknown is an explicit sentinel, never invented.**

## The sentinels
- `"tbd"` - a string field whose value is genuinely not in any source (most specs).
- `"—"` - specifically `landPrice` when unknown (matches the reference).
- `null` - a sortable numeric (`warehouseRentVal`, `expansionParkVal`) or `reit` when unknown.
- Never emit JS `undefined`, and **never drop a key the chrome reads** - emit the sentinel instead. The chrome calls string methods on some fields (e.g. `warehouseRent.replace(...)`), so a missing key crashes the whole render. `merge.canonicalize()` fills every chrome-read key.

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
