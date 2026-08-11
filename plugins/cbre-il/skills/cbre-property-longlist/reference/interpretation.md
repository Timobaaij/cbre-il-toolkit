# Brochure interpretation - text-first, raster fallback

Brochure decks (PDF/PPTX) are not parsed for FIELDS by a label dictionary - every
agent/country/template names things differently, so a dictionary is a losing
battle for the long tail. Instead an **isolated interpretation sub-agent**
structures each deck into records, reading the deck's extracted **text** when it
has a usable one (cheap, fast, accurate for a born-digital flyer) and the page
**rasters** only when the text layer is garbled/absent (a scan, an image export,
a vector slide). An xlsx/CSV **tracker** rides the SAME exit-3 handoff for one
narrow decision - which raw column means which canonical field (see "Tracker mode"
below); the deterministic dictionary stays its offline fallback, hard veto and
verifier, and Python still parses every number.

`run.py` decides the mode PER DECK (`helpers/interpret_prep.py`), writes
`work/vision/manifest.json` with each deck's `mode`, and **always exits 3** -
including on a mixed run. Nothing is merged or built until the interpreted records
are in: building first would produce a dashboard that is stale the moment the
records land, wasting the build, the post-build gates and any dispatched reviews.
Records that came from another source (a tracker, emails, prior decks) are cached
(resume is the default), so the re-run starts at merge.

A deck's `output` file you write **supersedes** that deck's own deterministic
records - OUTRIGHT (the filename keeps the historical `_vision.json` suffix so
merge/gates need no change; it is the "LLM-produced records" slot, used for both
modes). Supersession is keyed to the deck's **source file**, so a brochure the
manifest never listed keeps its records, and a sibling deck sharing the same
cluster label is judged on its own output rather than its neighbour's. (Before
this, both completion and supersession were decided by matching the output
FILENAME against the region name, which is why two decks on one label could not
be told apart.)

You can also run the prep stage by hand:
`python helpers/interpret_prep.py <file.pdf|.pptx> --region R --country C --out-dir work/vision`.

## How the mode is decided
A deck is **text** mode when at least half its pages carry >= ~80 characters of
extractable text; otherwise **raster**. The threshold is conservative: a
born-digital flyer with photo plates between spec pages still routes to the cheap
text path, while a mostly-image scan escalates to rasters. The `PDF engine:` line
`run.py` prints at startup matters: a whole run cascading to raster while it says
`fitz_shim fallback (…)` is a wheel problem to FIX (native PyMuPDF would have read
the text), not something to paper over by transcribing images.

## Manifest format (`work/vision/manifest.json`)
```json
{
  "decks": [
    {"source_file": "CBRE_Valencia_Options_TEDI.pdf", "source_type": "pdf",
     "region": "Valencia", "country": "ES", "mode": "text",
     "pages": [
       {"page_no": 0, "locator": "page 1",
        "text": "VALENCIA REGION\nOption 1\nCity Valencia\nTotal existing space 12,500 m2\n...",
        "render": "C:/.../work/vision/CBRE_Valencia_Options_TEDI_p0_render.png",
        "candidates": [
          {"index": 0, "image": "C:/.../work/vision/CBRE_Valencia_Options_TEDI_p0_c0.png",
           "w": 1600, "h": 900},
          {"index": 1, "image": "C:/.../work/vision/CBRE_Valencia_Options_TEDI_p0_c1.png",
           "w": 800, "h": 600}
        ]},
       {"page_no": 1, "locator": "page 2", "text": "", "low_text": true,
        "render": "C:/.../work/vision/CBRE_Valencia_Options_TEDI_p1_render.png",
        "candidates": []}
     ]},
    {"source_file": "Naves Cataluna.pdf", "source_type": "pdf",
     "region": "Cataluna", "country": "ES", "mode": "raster",
     "pages": [
       {"page_no": 2, "locator": "page 3",
        "image": "C:/.../work/vision/Naves Cataluna_p3.png",
        "reason": "no extractable text/labels (image/scan/vector page)"}
     ]}
  ],
  "jobs": [
    {"kind": "tracker", "source_file": "Building_Data.xlsx", "source_type": "xlsx",
     "region": "", "country": "", "input_hash": "8657b2cf",
     "output": "work/extract/Building_Data_7667711a_map.json",
     "sheets": [
       {"sheet": "Sheet1",
        "headers": ["Marketing Name", "Town", "Size", "Size Unit", "Office content",
                    "Current quoting rent (£ per sq ft)", "..."],
        "sample_rows": [["EVO 169", "Corby", "172867", "GIA", "13576", "8.5", "..."]],
        "populated_columns": 19, "unmapped_headers": ["Building ID", "Size Unit", "..."]}
     ]}
  ],
  "record_schema": "templates/record_schema.json",
  "output_pattern": "EACH DECK CARRIES ITS OWN `output` PATH - write it VERBATIM (a JSON array of records)"
}
```
The `decks` array is the brochure interpretation contract (unchanged); the `jobs`
array carries non-brochure interpretation jobs - presently `kind:"tracker"`. Both
ride the SAME exit 3, so one dispatch covers every file that still needs reading.
A `tracker` job carries each tracker SHEET's raw `headers` (in column order, the
index is the position), up to a few `sample_rows` (cell strings, for disambiguating
GIA vs warehouse), the dictionary's own `unmapped_headers` miss list (focus the
model on the long tail), the `input_hash` to copy verbatim, and the `output` path
to write.
For a **text** deck EVERY page carries `page_no` (0-based), `locator` (1-based
human label), `text` (the page's extracted text), `candidates` (the page's
hero-size embedded images, each with a stable 0-based `index` and a thumbnail
`image` path for you to LOOK at when choosing the hero/plan) and `render` (a small
thumbnail of the WHOLE-PAGE render - so a VECTOR site plan, invisible as an embedded
image, is visible - for picking `plan_page`; `null` when this deck cannot be
rendered). A page with little/no extractable text carries `"low_text": true`: it is
listed as **VISUAL reference only** (so you can pick it as `plan_page` or an
`image_pages` entry) - **never emit a record for a `low_text` page**. For a
**raster** deck each page carries `page_no`, `locator`, an `image` path and a
`reason` (a `null` image could not be rasterised - for PPTX this happens only without
LibreOffice AND with no extractable picture; export such a slide manually).

## The interpretation sub-agent (orchestrator dispatches; isolated, fresh context)
For each deck dispatch an isolated sub-agent given ONLY the manifest entry (the
page text or the page-image paths) + this contract - never the orchestrator's
view. The author is never the reviewer; the honesty gates below run blind.

### Three rules that apply to EVERY mode (read these first)

**The manifest's `cluster_label` is NOT evidence.** It is a filing and routing name derived from
the input FILENAME (the entry also carries `cluster_label_is_routing_only: true`). It exists so
your output file lands in the right slot, nothing more. Never copy it into `region`, `park`,
`city` or any other record field, and never cite it to a page. Set `region` ONLY from text you can
point at on a page; if the deck names no region, OMIT the field. This is not hypothetical: a live
run whose label read `MPC2 Magna Park Corby, 100 Kettering Road, Weldon` shipped exactly that
string as the property's region, cited to "page 1", on a deck where the token "MPC2" appears on
zero pages. Three of eleven agents made the same mistake in one round.

**If you read a value from an IMAGE rather than the text layer** - a name on a cover logo, a
figure in a rendered spec panel - append the marker `not in text layer` to that field's
provenance, e.g. `page 1 (text interpretation; not in text layer: read from the cover logo)`.
This is checked: the `prov-containment` gate verifies that a value citing a page actually occurs
in that page's extracted text, and this marker is the sanctioned way to declare a value it cannot
verify. Use it honestly and only when true - it is an admission, not a bypass.

**Return the unit the source states for THAT figure.** Whenever you return an area, return its
unit. If one figure uses a different unit from the rest of the deck - a site area in acres inside
a sq ft brochure, which is the normal UK shape - set `<field>Unit` alongside it, e.g.
`plotArea: 31.629` with `plotAreaUnit: "acres"`. **Never convert it yourself.** Python converts
with exact factors and records the conversion in the ledger. Two agents on one run split on this:
one dropped a stated "31.629 acres (12.8 ha)" site area as an "honest gap", the other converted
"30 ACRES" to sq ft citing a convention - and the dropped one shipped a ledger row claiming the
source was silent about a figure printed on its own page 2. Report the unit; let Python do the
arithmetic.

**Declare the deck's language.** Set `__meta.source_lang` to the ISO-639-1 code of the language the
deck is WRITTEN in (`en`, `es`, `pl`, `de`). You are reading the text anyway, so this costs you
nothing, and it lets the pipeline skip an entire translation round when the source already matches
the dashboard language. Omit it only if the deck is genuinely unreadable.

### Text mode (preferred)
Read each page's `text` and structure the property/properties into candidate
records matching `templates/record_schema.json`:

- **One record per property/option.** A page describing several options yields
  several records (repeating the same `page_no` is correct); never collapse them.
  A `low_text` page is VISUAL reference only - **never emit a record for it** (it is
  a cover/divider/photo plate or a vector site-plan page, offered so you can name it
  as `plan_page` / an `image_pages` entry, not so it becomes its own property).
- **Fill EVERY field the page states. The manifest's `fields` array is the canonical
  registry and it is NOT a limit** - it is generated at run time from
  `_common.canonical_property_fields()`, so it is always the live set the pipeline
  carries (43 reader-fillable names: `areaUnit, breeam, carParking, city,
  clearHeight, country, description, developer, district, divisibleFrom,
  earlyAccess, electricity, epc, expansionBuilding, expansionPark, floorLoad,
  incentives, landPrice, landlord, lat, leaseTerm, lng, loadingDocks, mapLink,
  motorway, officeArea, officeRent, overheadDoors, park, permitting, plotArea,
  postcode, region, reit, rentFree, rentUnit, serviceCharge, sprinklers, status,
  truckParking, warehouseArea, warehouseRent, warehouseRentVal`). Read `fields` from
  the manifest rather than trusting this copy. `description` may carry the brochure's
  own prose.
  Three rules govern capture, all three learned from a live failure:
  - **A STATED NEGATIVE IS DATA, NEVER AN ABSENCE.** "Land price: Not charged",
    "Sprinklers: No", "None", "N/A" are positive commercial statements - ship them as
    the value. Only a blank row, or one the deck marks `tbd`/`TBC`/`BTS`/`TBS`, is
    unknown. Shipping the unknown sentinel instead tells the broker to go and ask an
    agent about a question the deck already answered.
  - **THE SCHEMA IS OPEN.** `templates/record_schema.json` sets
    `additionalProperties: true` and names only 17 of the fields for illustration; it
    is NOT a closed set. If a stated row has no obvious home in `fields`, emit it under
    a descriptive camelCase key of your own (`yardRent`, `railSiding`). The dashboard
    auto-shows any real scalar attribute (v22) and `meta.newFields` discloses it, so
    nothing invented can hide and nothing stated need be lost.
  - **"There is no field for X" is NEVER a reason to omit X.** If you are about to
    write that sentence in your report, emit the field instead.
  - **WRITE THE VALUE THE WAY THE SOURCE PRINTS IT.** A dimensioned value carries its
    unit inside the value: `"10,000 sq. m"`, not `"5000"`; `"10 m"`, not `"10"`. Most
    fields render verbatim on the card and in the modal, so a bare magnitude sitting
    beside a written sibling quotes a different quantity to the client. Copy the printed
    form - do not normalise it, round it, strip the unit, or ADD a unit the page does not
    print. A pure COUNT is correctly bare (`"72"` loading docks); the rule is about
    dimensioned quantities, and a ratio (`"1 per 650 sq. m"`) is neither. If you can read
    the magnitude but genuinely cannot read its unit, return the number and say so in that
    field's `prov`: the deterministic `value-format` gate then catches the mismatch and the
    broker settles it, which is honest, whereas a unit you inferred is invention.
    This is not hypothetical: `divisibleFrom` shipped `"10,000 sq. m"` on twelve cards and
    a bare `"5000"` on the thirteenth, and `clearHeight` shipped `"10 m"` on twenty-three
    and a bare `"10"` on six, in one delivered client dashboard.
  Why this is spelled out at this length: on one live run all three readers wrote
  exactly that sentence and dropped office rent, sprinklers, permitting, rent-free,
  divisible-from and expansion, every one of them printed on the page. Merge then
  turned each omission into a ledger row asserting "absent in all sources" - roughly
  100 false claims in a client deliverable, because a field the dataset carries for
  one property but not another is recorded as a positive absence, not as silence.
- **Orchestrator note (this is where it went wrong).** Do NOT paste an abbreviated
  field list into a sub-agent prompt. A list in the prompt reads as the specification
  and overrides this contract. Point the reader at the manifest's `fields` array, or
  pass that array verbatim.
- **BREEAM and EPC are DIFFERENT fields - never fold one into the other.** `breeam` takes a
  BREEAM sustainability grade ONLY (Pass / Good / Very Good / Excellent / Outstanding, a
  `Target ...` prefix kept as printed). An EPC rating - a letter band like `A+`, `A`, `B` -
  goes in **`epc`**, which ships as Additional Details on the dashboard. A deck that prints
  only an EPC leaves `breeam` ABSENT; do not put the band there to fill the field. This is not
  hypothetical: a tracker whose EPC column was treated as a BREEAM alias shipped an impossible
  "BREEAM A+" to a client card, cited to an empty BREEAM cell.
- **Rents are ANNUAL.** Store `warehouseRentVal` as a number in EUR/m²/**year** and
  make `warehouseRent` show that same number (e.g. `"€54 / sq m / year"`). If the
  text quotes a **monthly** rent (`€/m²/mes`, `/month`, `/Monat`, …), multiply by
  12 and note the conversion in `prov` (the consistency gate checks the display
  number equals `warehouseRentVal`).
- **A numeric area REQUIRES `areaUnit`; a rent REQUIRES `rentUnit`.** Return the unit **as the
  source states it** (`"sq m"` / `"sq ft"`; `"£/sq ft/yr"`, `"€/sq m/yr"`) - read it off the deck
  (the figure's own suffix, the column header, the spec table's unit row). **Do NOT infer the unit
  from the country, and do NOT convert the number** - merge converts arithmetically once it knows
  the true unit, and currency is never converted at all.
  Why this is not optional: nothing downstream can recover a missing unit. An area with no
  `areaUnit` is stamped with the dataset's DOMINANT unit and **not converted**, so one metric deck
  in a UK-dominant corpus shipped 12,500 sq ft against a true 134,549 - a **10.76x** error on the
  client's card, carried into the annual-rent total. The magnitude guard cannot catch it (it is
  asymmetric and blind across the whole realistic 5,000-50,000 m² range).
  If the deck genuinely never states a unit, return the area and **omit** `areaUnit`: merge then
  records `areaUnitAssumed` and the Gaps Report says so under "Area units assumed", which is an
  honest gap rather than a false precision. Never write a unit you did not read.
- **`__meta` is required:** `source_type` = the brochure type (`"pdf"`/`"pptx"`),
  `source_file` = the manifest's `source_file`, `locator_base` = the page
  `locator`, **`page_no` = the manifest page's `page_no` COPIED VERBATIM** (it is
  0-based; do NOT compute or re-derive it - the integer in the manifest is the only
  correct value, and it binds this property's hero photo to its OWN page so a
  multi-property file never leaks a neighbour's picture). **`page_no` MUST be the
  page that carries this property's HERO PHOTO - NEVER a plan, divider, cover or
  `low_text` page number.** `page_no` anchors the hero AND the whole carousel, so if
  the photo is on page N and the site plan on page M, set `page_no` = N and put the
  plan in `plan_page` = M (and any extra photo pages in `image_pages`); putting a
  plan/divider page number in `page_no` binds the hero and the carousel to that page -
  this exact mistake once shipped a decorative brand graphic as the hero. `prov` =
  `{field: "<locator> (text interpretation)"}` for every field you set (the ledger
  and G-trace key on this; the `(text interpretation)` tag tells the reviewer the
  value came from interpreting the page text).
- **Pick the hero image.** Each page lists `candidates` (its embedded images, each
  with an `index` and a thumbnail `image` path) and `candidates_sheet` - the SAME
  candidates tiled into one image, each captioned with its `index`.
  **Read `candidates_sheet` once per page rather than opening each `candidates[].image`
  in turn.** The tiles are those exact thumbnails at their native size, so you lose no
  detail, and it costs one tool call instead of one per candidate. Open an individual
  `candidates[].image` only when a tile is genuinely ambiguous, and when you need several
  at once, request them in a single message. A page with fewer than two candidates has
  no sheet (`null`) - use `candidates[].image` there. LOOK at them. For each property
  record set `__meta.heroRef` = the `index` of the genuine marketing HERO (a real
  photo, aerial or render), or `null` if NONE of the candidates is a real photo - a
  road MAP, a location screenshot, a floor/site PLAN, an icon or a logo is NEVER the
  hero. Set `__meta.planRef` = the `index` of the SITE PLAN if present, else `null`.
  When unsure, prefer a photo/aerial/render as the hero and leave a map/plan as
  `planRef`. The classifier + the G-images gate VERIFY your pick: a `heroRef` that
  points to a non-photo is blocked for sign-off, and a `null`/absent `heroRef` falls
  back to the deterministic hero ladder, so an honest `null` is always safe.
- **Mark decorative candidates for exclusion (`__meta.exclude_refs`).** While you are already
  LOOKING at each page's candidate thumbnails, flag any candidate that is a DECORATIVE or abstract
  graphic - brand art, a gradient or geometric-pattern (e.g. isometric-cube) background, a
  full-bleed motif - that is NOT a real photo, aerial, render, site plan or location map. Add it to
  `__meta.exclude_refs` = `{"<page>": [<index>, ...]}` (page in the SAME 0-based numbering as
  `page_no`/`image_pages`; index = the candidate's `index` on that page) so it is DROPPED from the
  carousel. NEVER list the `heroRef` candidate. A genuine site plan or location map is NOT
  decorative - leave it (it belongs in the gallery + the Site Plan toggle); `exclude_refs` is only
  for non-informational brand/decorative graphics. Omit it when there are none (the default).
- **Pick the site-plan PAGE (`__meta.plan_page`).** Many site plans are VECTOR
  line-art drawn straight into the page (a whole page that IS the site plan), NOT a
  placed photo - `planRef` cannot reach those (pulled as an embedded image they go
  solid black). LOOK at each page's `render` thumbnail: if a page IS or CONTAINS the
  site plan, set `__meta.plan_page` = that page's 0-based `page_no` on the property
  record it belongs to; else `null`/omit. **This is a VISUAL judgment and it is
  TRUSTED**: merge renders that page and binds it (an independent visual-QA reviewer
  later confirms the slot, per `reference/visual-qa.md`) - there is NO pixel-classifier
  veto, so a full-bleed COLOUR plan, an aerial-overlay plan, or **a plan on ONE HALF of
  a 2-PAGE SPREAD** (the other half an aerial / spec-icon panel / accommodation table -
  VERY common in these decks) all qualify: flag the spread page as `plan_page` even
  though it is not pure white-paper line-art. Distinction: `plan_page` names a FULL
  PAGE whose RENDER is the plan; `planRef` is the `index` of an EMBEDDED-IMAGE plan on
  the property's own page. `plan_page` binds the PLAN SLOT only (never the card hero).
  A `null`/absent `plan_page` is safe (an offline deterministic fallback + the reviewer
  backstop it); never invent a plan page.
- **Set `__meta.image_pages` (the carousel scope).** List the 0-based pages
  whose photos belong to THIS property, in the SAME numbering as `page_no` (the
  manifest's). Set it for EVERY brochure topology: a single-page single-property
  deck → its one page (or omit it - it falls back to `page_no`); a multi-page
  single-property deck → ALL of this property's pages, EXCLUDING any appendix /
  "about us" / other-scheme pages; a multi-property deck with one page each →
  only that property's single page; a multi-property deck with several pages
  each → only that property's OWN pages. `page_no` STILL anchors the hero (it
  stays the carousel's first image) and its neighbour-protection is unchanged -
  `image_pages` only WIDENS which pages the carousel may draw from, never which
  page the hero binds to. When unsure, omit it or set `[]` (absence = today's
  `page_no`-only carousel). Python ENFORCES a deck page feeds at most one
  property's carousel, so an honest over-list of a neighbour's page is dropped,
  never leaked. **How a contested page is settled, so you can avoid the lossy
  case:** if one record's `page_no` IS that page, the record that anchors it keeps
  it and the other claim is silently dropped - harmless. But if TWO records list a
  page and NEITHER anchors it, it is not a sole claim for either, so it is dropped
  from **every** carousel and both properties lose the photo. So list a shared page
  in the `image_pages` of the ONE property it actually shows, not both. This is
  never an error and never sends the deck back for re-reading - a validation note
  tells the orchestrator which case occurred.
- **Pick the property description.** Set `description` to the property's own
  descriptive PROSE, copied verbatim from the page text (the marketing paragraph
  that says what the scheme is and where it sits, e.g. "EVO Corby 169 is a prime
  logistics development strategically located ..."). Copy it exactly; do NOT
  paraphrase, summarise or stitch unrelated lines together. NEVER use the
  legal/misrepresentation footer, an ALL-CAPS callout, a drive-time or spec table,
  or an icon caption. If no usable description prose exists on the page, set
  `description` to `null`/omit it (absent stays absent) - the deterministic
  font-size heuristic is the fallback, so an honest `null` is always safe. This is
  the same "transcribe, never invent" rule as the rest of the record.
- **OPTIONAL: if the schedule prints its own TOTAL, copy that number.** When a spec table shows a
  total/overall/GIA/GEA/GLA figure for the whole building alongside the individual areas (e.g.
  "Warehouse 440,000 / Office 12,500 / **Total GIA 452,500**"), set
  `"__meta": {"statedTotalArea": 452500, "statedTotalUnit": "sq ft"}` on that record — the number
  **exactly as printed**, never one you add up yourself. It is only ever compared against the
  areas; a total you computed would make the comparison circular and worthless.
  Purely optional: a deck that prints no total is unaffected, and omitting it costs nothing.
  Why it is worth the two keys: the dashboard derives `Total GLA = warehouse + office` and
  `rent = GLA × rate`, so a size figure that ALREADY included the office silently inflates both.
  That shipped once — GLA 11.7% above the source's own total and rent overstated by £702,108/yr.
  With the stated total recorded, `gate_runner arithmetic` catches it before anything is built.
- **When the page says MORE than the shipped value can carry, say so in `__meta.source_conflicts`.**
  A plain object mapping a field name to ONE COMPLETE SENTENCE, printed VERBATIM (only the source
  filename is appended) into the ledger's `conflict_note`, `meta.conflicts` and the Gaps Report's
  "Source conflicts" section. It NEVER changes the value you chose, and a note about a field the
  record does not carry is dropped. Two shapes both belong here:
  - **The page CONTRADICTS ITSELF** - brochures do this constantly. Pick the figure you judge
    governing (an itemised schedule usually beats a rounded headline) and disclose the other:
    `{"loadingDocks": "the source disagrees with itself: the SUPERFICIES schedule totals 180 docks
    (60+60+60) while the CARACTERISTICAS block on the same page states 170"}`.
  - **The source quotes a RANGE and the field can hold only a point value** - a rent of
    "3.50 - 3.75 €/m²/mes", a height of "6 - 10,5 m". Store the governing number (the LOW end for
    a rent, so it sorts honestly) and disclose the rest:
    `{"warehouseRentVal": "the deck quotes an asking rent RANGE of 3.50 - 3.75 per sq m per month;
    the card ships the annualised LOW end of 42, so the top of the range is not shown"}`. Do NOT
    try to put the range in the display string - `merge.canonicalize` re-derives `warehouseRent`
    from `warehouseRentVal`, and the pair-consistency gate rejects a display that does not match
    its number.

  Because the note is printed verbatim, write a full sentence that reads to a broker who has not
  seen the deck. Why it exists: every other conflict path compares one record against ANOTHER, so
  a self-contradicting or over-specified page was invisible - the loser could only be mentioned in
  `prov` prose, `conflict_note` stayed empty and the Gaps Report told the broker there was nothing
  to settle. Two independent reviewers raised that as a blocking honesty defect on a live run.
  Omit the key when the page is consistent (the normal case).
- **Transcribe, never invent.** A value you cannot read clearly → omit it or set
  `"tbd"`/`null`. Never guess a number, a rent, or coordinates.
- **COORDINATES: transcribe whatever form the page prints, and never convert.** `lat`/`lng`
  are numbers, so a DECIMAL pair goes straight in. If the page prints **DMS**
  (`48°29'51.0"N 17°01'39.7"E`), do NOT convert it and do NOT drop it - copy the printed
  string into `__meta.map_candidates` (a list of raw strings). Python converts it exactly
  (`coords.dms_from_text`: deg + min/60 + sec/3600), the same way it converts acres and
  annualises a monthly rent. Likewise copy any **maps link or 'click for location'
  hyperlink** verbatim into `__meta.map_candidates` - the resolver follows a shortener to
  the author's own pin. Never set `lat`/`lng`/`mapLink` from a link yourself.
  This is why it matters: a run where two pages printed DMS and a third carried only a
  Google Maps link shipped three town-centre pins, one of them a marker in the middle of a
  village, because the reader honestly refused to convert and nothing else owned it. The
  `coord-provenance` gate now blocks that, but the cheap fix is to hand the string over.
- **If the text is unusable/garbled** (mojibake, column-shuffled spec tables you
  cannot trust, a text layer that is clearly an OCR mess), do NOT force a record.
  Set `"needs_raster": true` on that deck's output (e.g. one stub record `{"__meta":
  {"source_file": "<file>", "needs_raster": true}}`) and note why - on the re-run
  the deck escalates to the raster path so you read the page images instead.
- `region`/`country` = the manifest's values for that deck.

### Raster mode (fallback - the historical vision contract)
Read each page **image** and transcribe - this section IS the raster contract:
one record per property page, rents annual,
`__meta.page_no` copied verbatim from the manifest, `prov[field] =
"<locator> (vision transcription)"`, transcribe never invent. Everything in the
text-mode `__meta` rules applies, only the source is the page image and the prov
tag is `(vision transcription)`. This INCLUDES `__meta.image_pages`: set it the
same way for every topology - single-page single-property → its one page (or
omit); multi-page single-property → all of this property's pages, EXCLUDING any
appendix / "about us" / other-scheme pages; multi-property one page each → only
that property's single page; multi-property several pages each → only that
property's own pages. `page_no` still anchors the hero and its
neighbour-protection is unchanged; `image_pages` only widens the carousel scope.
Omit or `[]` when unsure. This ALSO includes `__meta.plan_page`: in raster mode you
already see each page's full render, so when a page IS the site plan (a full page of
vector line-art / a site-plan diagram), set `plan_page` = that 0-based `page_no` on
the property it belongs to, else `null`/omit. It binds the PLAN SLOT only (never the
hero); `null` is always safe (the deterministic detector is the fallback).

## Tracker mode (`kind:"tracker"` job - a MAP, never records)
A tracker is a STRUCTURED source, so unlike a brochure the deterministic dictionary
already produced a usable parse. The sub-agent makes ONE narrow judgement - which raw
column means which canonical field, and each size/rent column's basis/unit - and
returns a **MAP**. It NEVER reads or transcribes a cell value; Python parses every
number from the columns the map names, with the same arithmetic the dictionary path
uses (acres x43,560, ha x10,000, monthly x12, GIA-office, the rent plausibility band),
so every numeric guarantee is byte-preserved.

Given ONLY the job's `sheets` (raw `headers` + a few `sample_rows`) + this contract,
write the job's `output` file:

```json
{ "input_hash": "<copied verbatim from the job>", "schema_version": 1,
  "map": {
    "columns": [
      {"index": 0, "field": "park"},
      {"index": 2, "field": "warehouseArea", "basis": "GIA", "areaUnit": "sq ft"},
      {"index": 3, "field": null, "role": "size_basis"},
      {"index": 5, "field": "warehouseRentVal", "currency": "GBP",
       "perArea": "sq ft", "period": "annual"}
    ],
    "notes": "free-text rationale for the reviewer"
  } }
```

Rules:
- Map each column to AT MOST one canonical field - the exact names extract_xlsx emits:
  `park, developer, city, country, region, warehouseArea, plotArea, officeArea,
  warehouseRentVal, serviceCharge, landPrice, leaseTerm, incentives, status,
  earlyAccess, clearHeight, floorLoad, loadingDocks, overheadDoors, electricity,
  truckParking, carParking, breeam, epc, motorway, lat, lng, latlng`.
  **`breeam` is a BREEAM grade column ONLY** (Pass/Good/Very Good/Excellent/Outstanding); an
  `EPC rating` column binds to **`epc`**, never to `breeam` - they are different certificates,
  and a tracker carrying both columns must map both. (The negative table now hard-vetoes the
  cross-binding either way, so naming it wrongly is corrected rather than honoured.)
- `field: null` for a column that is not a property field, OR any column you are unsure
  of - Python then falls back to the dictionary for it (a thin-but-honest map is fine;
  the dictionary backfills every column you leave unbound).
- **KEEP the source's own units** - do NOT convert; only NAME them so Python can apply
  the conversion faithfully: `basis` in `{GIA, GEA, GLA, warehouse}`; `areaUnit` in
  `{sq ft, sq m, acres, ha}`; `currency` ISO (`GBP`/`EUR`); `perArea` in `{sq ft,
  sq m}`; `period` in `{annual, monthly}`. A `role:"size_basis"` column is the per-row
  GIA/warehouse qualifier (the old `Size Unit` column).
- **NEVER read a cell value** - label the column only. The output schema has no value
  field, so a number can never enter a record from the model.
- Copy `input_hash` VERBATIM.

The dictionary keeps three safeguards regardless of the map: its NEGATIVE table is a
HARD VETO (a column whose header is a derived/penalty figure - `Rent free (months)`,
`Size Unit` - can never bind to a data field, even if the map says so; that one binding
falls back to the dictionary), a backfill of every column the map leaves unbound, and a
logged cross-check of any confident disagreement. The validate-data pair-consistency
gate + the rent plausibility band still verify the basis you named, and a map that
parses THINNER than the dictionary stays LOUD via the same `mapped<populated` yield
note. To decline the LLM map and keep the dictionary, create an empty file at the
output path with a `.SKIP` suffix instead.

### Verification pass (`kind:"tracker_verify"` job - an INDEPENDENT second map)

The column->field MAPPING/BASIS is one of the two highest-risk LLM judgements, so it
is checked by a SECOND, BLIND, INDEPENDENT re-derivation - not just by the reviewers
whose rubrics check value-at-cell. For every tracker offered for mapping, `run.py`
also emits a sibling `kind:"tracker_verify"` job on the SAME manifest (so the
orchestrator dispatches the author `tracker` job and the `tracker_verify` job
CONCURRENTLY, in one exit-3 batch). The two jobs carry BYTE-IDENTICAL input - the same
`sheets` (raw `headers` + `sample_rows`) and the same `input_hash` - and the verify
job's `output` is the `*_mapcheck.json` path.

- **Independence is mandatory.** Dispatch a SEPARATE fresh agent for the verify job; it
  must NOT be the agent that produced the first map, and it must NEVER be shown that
  map. It re-derives the map from the headers and the sample VALUES alone (cross-check
  each unit against value magnitude - a 172,867 value under a `sq m` header is almost
  certainly sq ft), and writes the SAME map schema (`{input_hash, schema_version,
  map:{columns:[...], notes}}`) to the verify `output`.
- **The diff is deterministic Python, ADVISORY only.** `run.py` compares the two maps
  by column index (`extract_xlsx.diff_tracker_maps`) and reports any `field`/`basis`/
  `areaUnit`/`currency`/`perArea`/`period` disagreement as a `semantic_disagreements`
  entry on the sheet's `header_report`, which becomes a loud line in
  `work/yield_report.md` and the Gaps Report. The **PRIMARY (first) map still drives the
  parse** - a disagreement is NEVER auto-rejected, and the broker confirms the correct
  basis/column with the landlord/agent. The blind G-trace/G-honesty reviewers
  (`reference/gates.md`) read this diff and re-derive the basis themselves; only a
  reviewer can escalate a confirmed-wrong basis to a blocking red.
- **Cached, asked once.** The `*_mapcheck.json` is keyed by the SAME `input_hash` as the
  primary map, so a present hash-matching check is reused on resume and the verify agent
  is dispatched at most once per tracker structure. With NO `*_mapcheck.json` present
  (every offline run / eval) the diff is empty - no Gaps line, byte-identical records.

## Region label resolution (`region_labels[]` job - a CLOSED-SET code pick, never records)
When `--regions` is on, `enrich.py` binds each property's workforce region by its
LOCATION first - exact point-in-polygon on the bundled NUTS-3 boundaries - then by a
resolving region code/label, then by city. A fuzzy, mis-spelled or new-language region
label that matches NEITHER the dataset name index/aliases NOR a city, on a property with
NO coordinates (so point-in-polygon cannot fix it), is left unbound. `run.py` then writes
a `region_labels[]` array to the SAME interpretation manifest and exits 3 (no new exit
code). The sub-agent makes ONE narrow judgement - which KNOWN dataset code names the same
province/region as the label - and returns a code FROM THE CANDIDATE LIST OR NULL. It never
reads a brochure, never returns a workforce figure, and never invents a code.

Given ONLY each job's `raw_label`, `city`, `country_cc` and `candidates` (a CLOSED list of
`{code, name, country}` drawn from the dataset's own NUTS names, scoped to the country) +
this contract, write the manifest's `output` file `work/extract/region_labels.json`:

```json
{ "resolutions": [
    {"raw_label": "Yorkshire And North East", "city": "Leeds", "country_cc": "GB",
     "code": "UKE42", "matched_name": "Leeds", "confidence": "high",
     "reason": "Leeds is the West Yorkshire NUTS-3 area for this label/city"},
    {"raw_label": "Region Unknown", "city": "tbd", "country_cc": "ES",
     "code": null, "matched_name": null, "confidence": "low",
     "reason": "no candidate confidently names this region"}
] }
```

Rules:
- **Pick a `code` from `candidates` only, or `null`.** The candidate list IS the dataset's
  bindable name set, so a code outside it could never bind; returning one is a contract
  breach. A typo, a renamed region or a genuine local-language synonym -> pick the matching
  candidate. Anything you cannot confidently place -> `null`.
- **Null over a guess.** A `null` is always safe: Python falls back to the self-documenting
  difflib gap in `merge_regions` (the closest known names are printed for the broker). A
  plausible-but-wrong neighbour bind is the exact harm to avoid - when unsure, return `null`.
- **Never a figure, never a record.** The output schema carries only the resolution; no
  number, coordinate or workforce statistic can enter from the model.
- The cache key is rebuilt deterministically from `raw_label + country_cc + city`; echo all
  three so the resolution keys correctly.

`bind_region_codes` RE-VERIFIES every returned code through `_dataset_region` before binding
(an unknown or stale code is discarded exactly as a `null` is), and the coordinate
point-in-polygon bind still WINS for any property that has - or later gains - coordinates,
so the LLM resolution only ever fills a coord-less property the deterministic path left
unbound. The isolated **G-enrich** reviewer gives a label bound this way the SAME
right-province scrutiny as a dataset match. To decline (a no-LLM / offline run), simply do
not write the cache file - the run falls back to the deterministic dictionary verbatim.

## Photo-match description (the exit-9 `photo_map.json` description fields)
A text-bearing brochure that was confidently photo-matched (exit 9) yields NO
interpretation record - its photo is attached to a property that already exists from
another source - so its description prose was never captured. The exit-9
`photo_match_manifest.json` therefore also carries, per brochure, a `brochure_text`
hint: `text_blocks` (the deck's font-size-grouped `{page (1-based), size, text}`
groups, boilerplate NOT pre-filtered so YOU judge), `heuristic_description` (what the
deterministic fallback would pick) and a short `text_hash`. Most exit-9 decks are
textless rasters and emit an EMPTY `text_blocks` - there is no description to pick
there. For the minority that DO carry text, the photo-match sub-agent may add a
DESCRIPTION to its `confident`/`uncertain` `work/photo_map.json` entries (all three
fields OPTIONAL):

```json
{ "confident": [
    {"brochure": "EVO Corby.pdf", "property_key": "corby|...|evo",
     "description": "EVO Corby 169 is a prime logistics development strategically located ...",
     "description_page": 2,
     "description_source_quote": "EVO Corby 169 is a prime logistics development strategically"}
] }
```

Rules:
- **Copy the description prose VERBATIM** from `text_blocks` into `description`; set
  `description_page` to its 1-based page and `description_source_quote` to the first
  ~80 characters copied EXACTLY (the deterministic verifier's needle).
- **Never** the legal/misrepresentation footer, an ALL-CAPS callout, a drive-time or
  spec table, or an icon caption. If no usable description prose exists, set
  `description` to `null` - absent stays absent, never synthesise.
- **Null is always safe.** A deterministic gate in `merge` accepts the pick ONLY when
  the `text_hash` still matches the deck AND `description_source_quote` occurs verbatim
  in the cited page's text layer; on any failure (or a `null`) it falls back to the
  font-size `best_description_in_deck` heuristic, so a fabricated description can never
  reach `canonical.json`. An accepted pick is prov-tagged
  `page N (brochure description, text interpretation)`; the heuristic fallback is
  `page N (brochure description)`.

## After interpretation
Write the deck's records as a JSON array to **the deck's own `output` path, copied VERBATIM from its
manifest entry** - exactly as a tracker `job` does. Do NOT derive the filename from the cluster label:
two decks can legitimately share a label (the documented cluster refinement collapses ambiguous
filename clusters onto a city), and deriving the name made four concurrent agents write ONE file, so
three decks were lost with no error and no gap line. Each deck's `output` is unique by construction.

(`work/extract/<region>_vision.json` is the LEGACY shape. A manifest that carries no `output` key
predates this change; derive that name only then.) Then re-run
`python helpers/run.py --folder … --work …` (same args; resume is the default, so
the cached records are reused and the run continues at merge). It folds any
`*_vision.json` into the merge, validates them structurally
(`vision_validate.py`: page-binding, un-annualised rents, implausible figures,
collapsed multi-property pages), merges them with everything else, and proceeds
through the gates.

Interpreted records pass through the **same** pre-build gates as any other -
`trace-coverage` (every populated field traces to a ledger row that is not a
`gap`), and the isolated **G-honesty** (no invented values) and **G-trace**
(sampled fields trace to their locator) reviewers are exactly where a bad
interpretation would be caught, so they are not relaxed for interpreted records;
the `(text interpretation)`/`(vision transcription)` provenance tells the reviewer
which source to re-read.

## Honesty
Interpretation is a less-certain source than a structured tracker, so it is
labelled as such end to end (provenance tag + Gaps Report). Prefer an explicit
`"tbd"` over a shaky read; a thin-but-honest record is correct, a
confident-but-wrong one is the failure this skill exists to prevent.
