# Vision fallback - image / vector-only decks

Some brochures have no text layer: a scanned PDF, an exported-as-image deck, or a
vector/inline layout the text parser cannot read. Text extraction
(`extract_pdf` / `extract_pptx`, own-line **and** inline) then returns 0 records,
or only thin/garbled ones, for that file. Vision transcribes exactly those files;
a file that parsed cleanly never reaches here.

## How it triggers (PER SOURCE FILE, exact thresholds)
`run.py` assesses each source file's parse SEPARATELY (a region's messy PPTX twin
must not discard its clean PDF parse) and routes a file to vision when it yielded
**0 records** OR **parsed poorly**: more than 50% of its records are "poor", where
a poor record has core-field fill < 0.4 (core = city, developer, size, price,
status), a synthesised "option N" name with no city, or a `warehouseRentVal`
outside 1.5-500 EUR/m²/yr. Good files' records ship normally.

It rasterises the routed files' pages with `helpers/vision_prep.py` (`force=True` -
every page, since the file failed deterministically), drops only THOSE files' thin
records, writes `work/vision/manifest.json` (+ the page PNGs), and **always exits
3** - including on a mixed run. Nothing is merged or built until the vision
records are in: building first would produce a dashboard that is stale the moment
the transcription lands, wasting the build, the post-build gates and any
dispatched reviews. The good files' extractions are cached (resume is the
default), so the re-run starts at merge.

A `<region>_vision.json` you write **supersedes** the deterministic records of
every file the manifest rasterised for that region - OUTRIGHT, independent of
how well those files appeared to parse (a garbled-but-filled twin kept next to
its own transcription doubled a real longlist to 71 cards). Files of the region
that were never rasterised keep their records, so a clean PDF twin in a mixed
region is safe. The filename is matched case- and diacritic-insensitively, but
prefer the manifest's exact region name.

You can also run the prep stage by hand:
`python helpers/vision_prep.py <file.pdf|.pptx> --region R --country C --out-dir work/vision`.

## Manifest format (`work/vision/manifest.json`)
```json
{
  "decks": [
    {"source_file": "Naves Cataluña.pdf", "source_type": "pdf",
     "region": "Cataluña", "country": "ES",
     "pages": [
       {"page_no": 2, "locator": "page 3",
        "image": "C:/.../work/vision/Naves Cataluña_p3.png",
        "reason": "no extractable text/labels (image/scan/vector page)"}
     ]}
  ],
  "record_schema": "templates/record_schema.json",
  "output_pattern": "work/extract/<region>_vision.json (a JSON array of records)"
}
```
A page with `"image": null` could not be rasterised. For PPTX this happens only
when LibreOffice is absent (with `soffice` installed, `vision_prep` renders the
deck to PDF and rasterises EVERY slide, vector/text-only ones included) AND the
slide carries no embedded picture python-pptx can extract - export such a slide
to an image manually and transcribe. Slide-sourced records need no manual image
work for the dashboard itself: merge harvests slide heroes directly
(`images.slide_hero_and_plan`).

## The vision sub-agent (orchestrator dispatches; isolated, fresh context)
For each deck (or page), dispatch an isolated sub-agent given ONLY the page
image path(s) + this contract - never the orchestrator's view. It **reads each
PNG itself** and transcribes the property into a candidate record matching
`templates/record_schema.json`:

- One record per property page. Fill the canonical field names you can read:
  `park, developer, city, country, region, status, warehouseArea (number, m²),
  warehouseRent / warehouseRentVal, plotArea, landPrice, clearHeight, lat, lng,
  earlyAccess, …` - the same names the text extractors emit.
- **Rents are ANNUAL.** Store `warehouseRentVal` as a number in EUR/m²/**year** and
  make `warehouseRent` show that same number (e.g. `"€54 / sq m / year"`). If the
  brochure quotes a **monthly** rent (`€/m²/mes`, `/month`, …), multiply by 12 and
  note the conversion in `prov` (the consistency gate checks the display number
  equals `warehouseRentVal`). Numeric spec fields the schema types as strings
  (`loadingDocks`, `overheadDoors`, `clearHeight`, …) may be given as numbers - the
  builder coerces them - but a plain string is fine too.
- **`__meta` is required:** `source_type` = the brochure type (`"pdf"` or
  `"pptx"`, so merge precedence treats it as a brochure), `source_file` = the
  manifest's `source_file`, `locator_base` = the page `locator`, **`page_no` = the
  manifest page's `page_no` COPIED VERBATIM - do NOT compute it.** The manifest's
  `page_no` is 0-based; the PNG filename suffix (`_p7.png`) is 1-based for
  humans. Deriving page_no from the filename (or counting pages yourself) is
  off-by-one, which binds this property's hero image to the NEIGHBOURING
  property's page - a real defect from a real run. The integer in the manifest is
  the only correct value; copy it. (It binds the hero to this property's OWN
  page, so a multi-property file does not leak a neighbour's photo.) Finally
  `prov` = `{field: "<locator> (vision transcription)"}`
  for every field you set (the ledger and G-trace key on this; the
  `(vision transcription)` tag marks the source as a transcription so reviewers
  know to spot-check it).
- **Transcription, not invention.** A field you cannot read clearly → omit it or
  set `"tbd"`/`null`. Never guess a number, a rent, or coordinates. If a read is
  low-confidence, still record it but note the uncertainty in `prov`.
- `region`/`country` = the manifest's values for that deck.

Write the deck's records as a JSON array to **`work/extract/<region>_vision.json`**
(region exactly as in the manifest). `run.py` folds any `*_vision.json` into the
merge on the next run.

## After transcription
Re-run `python helpers/run.py --folder … --work …` (same args; resume is the
default, so the cached extractions are reused and the run continues at merge). It
picks up the `*_vision.json` records, merges them with everything else, and
proceeds through the gates. Vision-sourced records pass through the **same** pre-build gates as
any other - G-honesty (no invented values) and G-trace (sampled fields trace to
their locator) are exactly where a bad transcription would be caught, so they are
not relaxed for vision records; the `(vision transcription)` provenance tells the
reviewer to look at the page image rather than a text locator.

## Honesty
Vision transcription is the least-certain source, so it is labelled as such end
to end (provenance tag + Gaps Report). Prefer an explicit `"tbd"` over a shaky
read; a thin-but-honest record is correct, a confident-but-wrong one is the
failure this skill exists to prevent.
