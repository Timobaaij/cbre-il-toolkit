# Source Ledger column spec

One row per populated property field (and per explicit `"tbd"`). Built by `merge.py`, validated/exported by `ledger.py`. Canonical column order:

| # | Column | Filled by | Notes |
|---|---|---|---|
| 1 | `property_id` | extractor/merge | the PROPS `id`; blank for poi/region rows |
| 2 | `record_type` | extractor | `property` / `poi` / `region` |
| 3 | `field` | extractor | canonical field name (`warehouseRent`, `clearHeight`, `photo`...) **required** |
| 4 | `value` | extractor | value written to canonical (or `tbd`/`—`/`null`) **required** |
| 5 | `source_file` | extractor | exact input filename or email subject **required** |
| 6 | `source_locator` | extractor | `page 4` / `slide 4` / `Sheet1!C12` / `email <date>` **required** |
| 7 | `source_type` | extractor | `pdf`/`pptx`/`xlsx`/`image`/`email`/`web`/`osrm`/`poi_library` **required** |
| 8 | `extractor` | extractor | which extractor produced it (`E-pdf`, `E-xlsx`) |
| 9 | `confidence` | Stage 2 | High / Medium / Low |
| 10 | `conflict_note` | Stage 2 | discarded value + which won and why |
| 11 | `verified` | G-trace | yes / no (no -> struck to `tbd`, moved to Gaps Report) |

Required-at-merge (a row missing any is rejected by `ledger.py validate`): `field, value, source_file, source_locator, source_type`.
