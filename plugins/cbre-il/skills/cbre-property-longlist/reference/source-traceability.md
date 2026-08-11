# Source traceability - the field-level ledger

Every populated property field (and every explicit `"tbd"`) is one row, so every cell in the dashboard is auditable to its origin. `merge.py` emits `source_ledger.csv`; `ledger.py` validates and exports the `.xlsx` deliverable.

## Columns (canonical order - this section IS the column spec)

| # | Column | Filled by | Notes |
|---|---|---|---|
| 1 | `property_id` | extractor/merge | the PROPS `id`; blank for poi/region rows |
| 2 | `record_type` | extractor/merge | `property` / `poi` / `region` / `override` (a manual `work/overrides.json` correction - `grep ,override,` lists every manual touch) / `offspec` (an off-spec pre-merge disclosure) |
| 3 | `field` | extractor | canonical field name (`warehouseRent`, `clearHeight`, `photo`...) **required** |
| 4 | `value` | extractor | value written to canonical (or `tbd`/`—`/`null`) **required** |
| 5 | `source_file` | extractor | exact input filename or email subject **required** |
| 6 | `source_locator` | extractor | `page 4` / `slide 4` / `Sheet1!C12` / `email <date>` **required** |
| 7 | `source_type` | extractor | `pdf`/`pptx`/`xlsx`/`image`/`email`/`msg`/`web`/`osrm`/`poi_library`/`gap` **required** |
| 8 | `extractor` | extractor | which extractor produced it (`E-pdf`, `E-xlsx`) |
| 9 | `confidence` | Stage 2 | High / Medium / Low |
| 10 | `conflict_note` | Stage 2 | discarded value + which won and why |
| 11 | `verified` | G-trace | yes / no (no -> struck to `tbd`, moved to Gaps Report) |

Required at merge (a row missing any is rejected): `field, value, source_file, source_locator, source_type`.

- `source_locator` - where exactly: `page 4`, `slide 4`, `Sheet1!C12`, `email <date>`, `page 4 (description)`. A derived companion value (e.g. the rent display synthesised from `warehouseRentVal`) carries its basis field's locator plus `(derived from <field>)`.
- `source_type` - `pdf | pptx | xlsx | image | email | msg | web | osrm | poi_library | gap` (`gap` = the positive record that a sentinel value was genuinely absent in all sources; `web`/`osrm`/`poi_library` rows are upserted by `enrich.py --ledger` for everything enrichment fills, so the ledger never contradicts the deliverable).
- `confidence` - High (a DETERMINISTIC structured extract: a tracker cell or an email field) / Medium (an LLM read - a brochure **text interpretation** or a **vision transcription** - or an image-read / enriched value) / Low (inferred); merge derives this from the row's real source, and Medium/Low are the G-honesty spot-check priorities. (Brochure fields are interpreted by the isolated sub-agent, so they are Medium, not High - an LLM read is a less-certain source than a structured tracker.)
- `conflict_note` - if sources disagreed, the discarded value + which won and why.
- `verified` - set by G-trace; `no` means struck to `"tbd"` and moved to the Gaps Report.

## How it is populated
Extractors attach a `prov` map per field in `__meta`; `merge.py` records the winning source per field as a ledger row, and `enrich.py --ledger` upserts rows for the fields enrichment fills (geocoded `lat`/`lng`/`country`, pre-baked drive-times, region figures with their cited sources). **One of those upserts REPLACES a source-stated value rather than filling a gap, and it is meant to:** when the sources state `region` at more than one administrative level, `harmonise_regions` sets each property's label to the NUTS-3 area its own coordinates fall inside, and the replacement row cites `assets/regions_dataset.json (<code>)` with the locator `NUTS-3 area containing <lat>, <lng>` and carries the value the source actually stated in `conflict_note`. So a `region` row attributed to `enrich` on a longlist whose brochure named a county is expected, not a provenance error - the brochure's own value is in that row's `conflict_note`, and `meta.regionHarmonised` plus a Gaps line record the whole set. (I11) The exported `<Client>_Source_Ledger.xlsx` (frozen header, autofilter) is the defensible "where did every number come from" sheet a broker can hand a client. `ledger.py validate` runs inside the pre-build gate scorecard (`gate1_scorecard.md`); an incomplete row blocks.
