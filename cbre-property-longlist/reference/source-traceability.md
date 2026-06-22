# Source traceability - the field-level ledger

Every populated property field (and every explicit `"tbd"`) is one row, so every cell in the dashboard is auditable to its origin. `merge.py` emits `source_ledger.csv`; `ledger.py` validates and exports the `.xlsx` deliverable.

## Columns (`templates/ledger_columns.md`)
`property_id, record_type, field, value, source_file, source_locator, source_type, extractor, confidence, conflict_note, verified`

Required at merge (a row missing any is rejected): `field, value, source_file, source_locator, source_type`.

- `source_locator` - where exactly: `page 4`, `slide 4`, `Sheet1!C12`, `email <date>`, `page 4 (description)`. A derived companion value (e.g. the rent display synthesised from `warehouseRentVal`) carries its basis field's locator plus `(derived from <field>)`.
- `source_type` - `pdf | pptx | xlsx | image | email | msg | web | osrm | poi_library | gap` (`gap` = the positive record that a sentinel value was genuinely absent in all sources; `web`/`osrm`/`poi_library` rows are upserted by `enrich.py --ledger` for everything enrichment fills, so the ledger never contradicts the deliverable).
- `confidence` - High (a DETERMINISTIC structured extract: a tracker cell or an email field) / Medium (an LLM read - a brochure **text interpretation** or a **vision transcription** - or an image-read / enriched value) / Low (inferred); merge derives this from the row's real source, and Medium/Low are the G-honesty spot-check priorities. (Brochure fields are interpreted by the isolated sub-agent, so they are Medium, not High - an LLM read is a less-certain source than a structured tracker.)
- `conflict_note` - if sources disagreed, the discarded value + which won and why.
- `verified` - set by G-trace; `no` means struck to `"tbd"` and moved to the Gaps Report.

## How it is populated
Extractors attach a `prov` map per field in `__meta`; `merge.py` records the winning source per field as a ledger row, and `enrich.py --ledger` upserts rows for the fields enrichment fills (geocoded `lat`/`lng`/`country`, pre-baked drive-times, region figures with their cited sources). The exported `<Client>_Source_Ledger.xlsx` (frozen header, autofilter) is the defensible "where did every number come from" sheet a broker can hand a client. `ledger.py validate` runs inside the pre-build gate scorecard (`gate1_scorecard.md`); an incomplete row blocks.
