# Gate failure & recovery - real cases from the Normal build

How the gates caught real problems and how each was resolved (the honest way).

## 1. Grid rendered zero cards (G-visual / DOM assertion)
**Symptom:** data loaded (`PROPS.length === 30`) but `document.querySelectorAll('.card').length === 0`, no console error initially.
**Root cause:** one property had no `warehouseArea`; the chrome's `fmt = n => n.toLocaleString(...)` threw on `undefined`, and then `cardHTML` did `warehouseRent.replace(...)` on a missing key - a single bad record killed the whole grid.
**Fix (two-pronged, both honest):**
1. Data: `merge.canonicalize()` now fills every chrome-read key with its sentinel (`"tbd"`/`"—"`/`null`) - the canonical rule "never drop a key the chrome reads".
2. Template: a `POST_PATCH` makes `fmt()` return `"tbd"` for non-numbers; template bumped **v1 -> v2** (a template/render defect is fixed in the template + re-versioned, never by inventing data).
**Lesson:** the reference HTML assumed complete data; a general ingestion tool must tolerate gaps. Logged in `reference/memory.md`.

## 2. warehouseArea = 10 (G-coverage / validate-data)
**Symptom:** CTPark Bor showed a 10 sqm warehouse.
**Root cause:** the area value was "BOR 10: 35 604 sq. m." and the parser grabbed the first number ("10").
**Fix:** area fields now take the largest plausible number (>=1000) in the value. Result: 35604. A sub-1000 parse is dropped to unknown rather than shown.

## 3. Two "BHM Dunajska streda" flagged as a duplicate (G-coverage)
**Symptom:** coverage flagged ids 7 and 8 as duplicates.
**Root cause:** they share a park name but are different buildings (53,000 vs 60,000 sqm).
**Fix:** the dup key now includes warehouse area, so distinct phases are not merged; `match.dedupe` already refuses to merge two records from the same brochure.

## 4. Missing coordinates (G-coverage, pre-enrichment)
**Symptom:** HU/SK brochures carry no lat/lng -> map markers missing, coverage thin.
**Fix:** `enrich.py --geocode` fills them from the city (Nominatim, cached) with `coordsApprox: true`. One compound city string would not resolve and was left as an explicit Gaps-Report line - **not** guessed.

## The principle
Every fix either (a) parses the real source better, (b) fills a sentinel and reports the gap, or (c) fixes the template and re-versions. None invents data. When a loop cannot close a gap, it escalates to the Gaps Report rather than loosening a criterion.
