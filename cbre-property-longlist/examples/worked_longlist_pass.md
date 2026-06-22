# Worked example - Normal CEE (clean pass)

A real run that produced a 30-property dashboard from three brochures.

## Inputs
`Normal Options - Bratislava.pdf`, `Normal Options - Budapest.pdf`, `Normal Options - Pilsen.pdf` (+ matching .pptx). No emails, no standalone images, no Excel tracker (only a requirements questionnaire).

## Command
```
python helpers/run.py --folder "<Normal folder>" --work work/ --client Normal --geocode --pois --no-pptx
```

## What happened, stage by stage
- **Intake:** 3 clusters inferred (Bratislava->SK, Budapest->HU, Pilsen->CZ), `project.yaml` scaffolded.
- **Extract:** Pilsen has a TOC (6 properties); Budapest (11) and Bratislava (13) have no TOC - park names synthesised as developer + city ("WING Sosket", "Panattoni Gyal"). 30 records total, matching the reference's 30.
- **Merge:** 30 properties, 30/30 heroes embedded from PDF pages, ~1,077 ledger rows (one per populated field PLUS one per explicit `tbd` gap, so absence is itself recorded).
- **Enrich:** geocoded 14 missing coordinates (Nominatim, cached) -> 29/30 with coords; attached 29 POIs. One honest gap: "Triblavina, Greater Bratislava Area" did not resolve.
- **Pre-build gates:** self-check, validate-data, coverage, ledger validate -> ALL-PASS (coverage flagged only the one genuinely thin record before geocoding).
- **Build:** 4.49 MB single file (vs the reference's 11 MB - tighter image budget).
- **Post-build gates:** validate-html byte-identical, reconcile clean.
- **Deliver:** dashboard + `Normal_Source_Ledger.xlsx` + `Normal_Gaps_Report.md`. `final_gate.py` -> ALL-PASS, shippable.

## Final fill rates (honest)
photo 30/30, status 30/30, warehouseArea 29/30, warehouseRentVal 27/30, lat 29/30, clearHeight 29/30, motorway 16/30. The rest are genuine `"tbd"` on the Gaps Report with a "how to close it" note - not invented.

## Browser check
Loaded under the Preview MCP: 30 `.card` elements, real base64 photos, correct titles/rents, `"tbd"` shown honestly, zero console errors. (Full-page screenshots can time out on the heavy inline-image page; DOM assertions are the reliable substitute.)
