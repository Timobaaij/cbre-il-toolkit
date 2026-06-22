# Failure modes - graceful degradation

The rule: **always degrade and report, never fabricate.** Every degraded case writes a Gaps Report line.

| Situation | Behaviour | Surfaced in |
|---|---|---|
| Partial inputs (a field absent across all sources) | field stays `"tbd"`; record ships if it clears `fill_threshold`; G-honesty confirms the `"tbd"` is genuine | Gaps Report (per property + how to close) |
| No emails / no Excel | those extractors skipped (driven by `inventory.json`); pipeline proceeds | Gaps Report notes absent types |
| No images | record ships without a real photo; a neutral CBRE placeholder is embedded; G-images passes trivially | Gaps Report: "no imagery for N properties" |
| Unreadable / scanned brochure | `extract_pdf` tries the text then page-raster path; fields not invented | Gaps Report: "<file> unreadable - manual entry", with the path |
| EMF/WMF vector image | rasterise the source page; else the CBRE placeholder | Gaps Report: "no imagery for N properties" (placeholder noted) |
| Unmatched asset (image matches no property) | listed in `meta.unmatchedAssets`; G-images requires it be explained | Gaps Report |
| Missing coordinates | `enrich.py --geocode` (Nominatim, cached, `coordsApprox: true`); a compound/unresolvable city is a gap; the map simply omits that marker | Gaps Report |
| OSRM unreachable | `preBaked.distances` omitted; the chrome degrades to its in-browser OSRM then a haversine estimate (the UI labels "estimated") | Gaps Report |
| Conflicting sources | both kept; higher-precedence value wins; loser in `conflict_note` | Gaps Report + ledger |
| Zero property sources | Stage 0 halts before any work with a written explanation; no empty dashboard | direct message to the user |

A render crash from a single bad record is prevented structurally: `merge.canonicalize()` fills every chrome-read key with a sentinel, and the template's `fmt()` returns `"tbd"` for non-numbers (`reference/template-contract.md`).
