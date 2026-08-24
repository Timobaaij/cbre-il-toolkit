# Agentic steps the orchestrator runs around the spine

Moved verbatim from SKILL.md (workstream 1 item 1.1). The LOOP in SKILL.md plus the printed
handoffs and the rendered `work/prompts/` files carry everything a normal run needs - this
file is the full background per step, for when a handoff is unusual or a job kind has no
rendered prompt.

- **Emails (Outlook MCP):** dispatch an isolated sub-agent that calls `outlook_email_search`
  (client/subject/date from `project.yaml`), reads offers, writes records in the schema of
  `templates/record_schema.json`, and re-routes attachments through the brochure/image
  extractors. **Its prompt is `prompts/outlook-ingest.md` - the ONE template you fill by hand**
  (email ingestion is dispatched at Stage 1, not from a spine exit, so `work/prompts/` never
  renders it): copy the file, fill its `SKILL_DIR`/`INPUTS_DIR`/`FOLDER`/`QUERY`/`OUTPUT_PATH`
  slots from `project.yaml inputs.emails`, and dispatch the result verbatim. Do NOT author
  this prompt from scratch - a hand-written paraphrase of a contract is the documented top
  error surface. **Map links belong to the deterministic resolver, not the model:** when an
  offer carries a Google/Apple/OSM maps link or a bare `lat,lng` pair (landlords paste these
  constantly), copy that raw string VERBATIM into the record's `__meta.map_candidates` (a list
  of strings) and do NOT set `lat`/`lng`/`mapLink` yourself - the shared resolver
  (`extract_pdf.backfill_link_coords`) parses it post-merge, so a first-party pin beats the
  town-centre geocode and no coordinate is ever model-invented. Falls back to a `.msg`/`.eml`
  folder (`extract_email.py`) when the MCP is absent - the fallback lists attachment names
  only and does not yet save or re-route their bytes (full byte-routing stays on the Outlook
  MCP path).
- **Brochure interpretation (text or raster):** when `run.py` writes `work/vision/manifest.json`
  (and exits 3), dispatch an isolated interpretation sub-agent. Each deck carries a `mode`:
  for **`text`** decks it reads the page `text` from the manifest and structures records
  (provenance `(text interpretation)`); for **`raster`** decks it reads each page image
  (provenance `(vision transcription)`, the historical vision path). Either way it writes
  **the deck's own `output` path** from the manifest (schema `templates/record_schema.json`) -
  rents annual, honest `tbd` for unreadable fields, never invented, `__meta.page_no` copied
  VERBATIM from the manifest; a garbled text deck sets `needs_raster` so it escalates on
  re-run. Then re-run the spine. Full contract, both modes: `reference/interpretation.md`.
  **First check the `PDF engine:` line run.py prints at startup:** if it says
  `native PyMuPDF ...`, the mode the manifest chose is right (a raster deck is genuinely
  image/vector-only). If it says `fitz_shim fallback (...)`, the bundled `vendor/` PyMuPDF
  wheel did NOT load (the line prints why); a whole run cascading to raster then is a wheel
  problem to FIX, not to paper over by transcribing images.
- **Tracker mapping (exit 3 - the `jobs` array of `work/vision/manifest.json`):** when
  `run.py` writes a `kind:"tracker"` job, an xlsx/CSV tracker's column->field mapping is being
  OFFERED to an isolated sub-agent. Dispatch it given ONLY the job's `sheets` (raw `headers` +
  a few `sample_rows`). It returns a **MAP, never records** - which raw column means which
  canonical field, plus each size/rent column's `basis`/`areaUnit`/`currency`/`perArea`/`period`
  hint - written to the job's `output` as `{input_hash, schema_version, map:{columns:[...],
  notes}}` (copy `input_hash` verbatim). It NEVER reads a cell value; Python parses every
  number with the same arithmetic. The deterministic dictionary already extracted the tracker,
  so this is a quality UPGRADE for a thin parse: the NEGATIVE table still vetoes a
  derived/penalty column, the dictionary backfills any column left `null`, validate-data + the
  rent band verify the named basis, and a thinner-than-dictionary map stays LOUD in the yield
  report. To decline the LLM map and keep the dictionary (a no-LLM / offline run), create an
  empty `.SKIP` file at the output path. Re-run the spine. Full contract:
  `reference/interpretation.md` "Tracker mode". **Independent verifier (same manifest):** the
  manifest ALSO carries a sibling `kind:"tracker_verify"` job per tracker - dispatch a
  SEPARATE fresh agent (CONCURRENTLY with the `tracker` job, never shown its map) to re-derive
  the SAME map blind into the `*_mapcheck.json` output. `run.py` diffs the two maps in pure
  Python and surfaces any field/basis disagreement to the Gaps Report (ADVISORY - the first
  map still drives the parse).
- **Intake cluster labels (exit 3, OPTIONAL job):** when `inventory.json` holds
  `confidence:"low"` filename clusters and `work/intake_clusters.json` does not exist, the
  round also renders `prompts/cluster-labels.md` - an isolated agent judges the named stems
  and writes the input-hashed cache. Absence of the output keeps the deterministic regex, so
  this job never blocks. This sets ONLY `inputs.clusters` (a routing/scaffold label + the
  `market.countries` seed) - the card's displayed region/city stay brochure-derived.
- **Photo match (exit 9 - brochures that are photos for known properties):** when `run.py`
  exits 9 and writes `work/photo_match_manifest.json`, some brochures yielded no text but the
  run already holds the property data from another source, so each brochure is most likely a
  PHOTO for a known property, not a new property. **Dispatch an isolated sub-agent** that
  matches each brochure to a property by MEANING - reading the filename against the property
  names/addresses, like a human, NEVER by rigid rules. It writes `work/photo_map.json`:
  `{"confident":[{"brochure","property_key"}], "uncertain":[...], "unrelated":[...]}` where
  `property_key` is the opaque `key` from the manifest. **confident** = sure; **uncertain** =
  plausible but unconfirmed (the property keeps a placeholder and the broker is asked to
  confirm); **unrelated** = a genuinely different property or no match (it goes to the vision
  path - never drop a property). Re-run the spine. On the broker's **yes** to an uncertain
  pair, move that entry from `uncertain` to `confident` in `photo_map.json` and re-run; on
  **no**, leave it `unrelated`. With no other records (a pure brochure run) exit 9 never fires.
- **Match adjudication (exit 10 - is this the same property from two sources?):** when
  `run.py` exits 10 and writes `work/match_candidates.json`, the deterministic matcher has
  auto-merged the confident cross-source pairs and hard-BLOCKED the impossible ones (a >15%
  size conflict; a developer DISAGREEMENT is NOT a hard block - it goes to the grey zone), and
  the GREY-zone pairs are adjudicated by an isolated sub-agent that decides, for EACH pair, by
  MEANING whether `a` and `b` are the SAME physical property. It writes
  `work/match_decisions.json`: `{"<pair_id>":{"verdict":"same"|"different","reason":"..."}}`
  covering every pair_id - leaning 'different' on thin evidence (an over-split is caught by
  the coverage dedupe gate; an over-merge silently loses a property), with **`"unsure"` as a
  first-class verdict when genuinely torn** (interactive runs put it to the broker via exit
  13; headless ships 'different', disclosed) - and NEVER inventing a property. The size-conflict **forbidden** tier BLOCKS a wrong over-merge by
  construction; the deterministic matcher is the offline fallback. The verdict is cached by an
  order-independent `pair_id`, so the re-run merges byte-deterministically. **The pre-filter
  reads the identifying free text HOLISTICALLY, not field-by-field (I12):** each record
  contributes one identity bag (park/address/street/scheme/estate/building/postcode-ish) and
  one party bag (developer/landlord/owner-ish), overlap tested ACROSS them in both directions;
  the identity bag is un-gated, the party bag is CITY-gated; both strip place words, generic
  scheme words, street furniture, corporate boilerplate and area-code-shaped tokens. A shared
  city ALONE is not a signal (I9). Full contract: `reference/matching.md`. **Independent
  verifier (same candidates file):** `match_candidates.json` also carries a `verify_pairs`
  array - dispatch a SEPARATE fresh agent (CONCURRENTLY, never shown the matching pass's
  verdict) to re-judge same/different blind into `work/match_verify.json`. `run.py` diffs the
  two verdicts in pure Python and folds any disagreement into `meta.conflicts` (ADVISORY).
- **Web enrichment (exit 8):** `run.py` has written `work/web_requests.json` (the exact
  requests, each with a ready `data_url`) and `work/web_enrich.html` (the full self-chaining
  fetcher page), plus `<work>/.claude/launch.json` serving the work dir. **It is ALWAYS the
  Cowork sandbox.** Do NOT branch on an environment label; PROBE which tools are present and
  use the FIRST available, in this priority order. **The chat handoff (tier 4) is the
  UNIVERSAL fallback and MUST be used whenever no earlier tier is present, the automated fetch
  cannot reach OSM/ORS, OR an attempted fetch failed - never let exit 8 end in an error, a
  skipped enrichment, or straight-line estimates.** **`WebFetch` is NOT a path here** - it
  cannot reach the Nominatim/Overpass/OSRM/ORS API hosts. Never substitute a curated POI list
  for the genuine fetch (the enrichment gate BLOCKS library-stopgap POIs).
  - **Tier 1 - `mcp__shell` (best when present; native, outbound network; NOT Windows-only).**
    Re-run the spine THROUGH it with the same flags - the helpers reach the live APIs directly
    and bake `poi_osm_cache.json` / `osrm_cache.json` / the geocode cache. No exit 8 next pass.
  - **Tier 2 - the Playwright MCP (the verified `data:` URL fetcher).** Playwright runs in a
    DIFFERENT network namespace from the sandbox shell (`file:` blocked, sandbox localhost
    unreachable - do NOT start a local HTTP server), but its browser has its OWN outbound
    internet and OSM/ORS/Nominatim/Overpass all send `Access-Control-Allow-Origin: *`. For
    EACH request in `work/web_requests.json` ({url, save_as, data_url}): (1)
    `browser_navigate` to `request["data_url"]` (a minimal `data:text/html` fetcher whose
    inline script `fetch()`es the URL onto `window.__m`); (2) `browser_wait_for` a few seconds
    (throttle per service - Nominatim ~1 req/s); (3) the **return bridge:** `browser_evaluate`
    with `function:"() => JSON.stringify(window.__m)"` AND `filename:request["save_as"]`; the
    saved content is itself JSON-stringified, so **`json.loads` it TWICE**, then write the raw
    body to `<work>/web_fetched/<save_as>`. Then `python helpers/web_enrich.py ingest --work
    <work>` and re-run the spine (repeat once if OSRM requests appear - drive times need the
    discovered POIs first).
  - **Tier 3 - the Claude Preview MCP (serves the FULL fetcher page).** The Preview MCP
    launches its OWN server in the namespace its own browser CAN reach (no `data:` URL size
    limit, so it serves the whole `web_enrich.html` via the `longlist-preview` `launch.json`
    the run wrote). Do NOT start a server with the sandbox shell. Steps: (1) `preview_start`
    with `name:"longlist-preview"` (`preview_list` first to reuse); (2) `preview_eval` to
    navigate to `/web_enrich.html`, wait ~2s; (3) `preview_click` the **"Fetch all"** button
    (`#go`); (4) poll until **"Download seeds"** (`#dl`) is enabled or the log shows "Done";
    (5) `preview_eval('JSON.stringify(seeds)')`; (6) Write that JSON to `<work>/web_seeds.json`;
    (7) `python helpers/web_enrich.py ingest --work <work>`; (8) re-run the spine. If the
    Preview MCP is absent, or the console shows the OSM/ORS fetches were BLOCKED, fall
    straight to tier 4. For both browser tiers there is no key field to fill: with
    `ORS_API_KEY`/`project.yaml enrichment.ors_api_key` the page/requests build **HGV**
    automatically; with no key they return CAR times and the Gaps Report names the downgrade.
  - **Tier 4 - chat handoff (the UNIVERSAL fallback, always available, any network).**
    **DELIVER `web_enrich.html` IN THE CHAT** with one plain sentence (open it in your
    browser, click "Fetch all", drop the downloaded `web_seeds.json` back into the chat). The
    page shows an optional **truck-routing key field**: a broker with an openrouteservice key
    not set at Stage 0 can paste it there for HGV times - it stays in their browser and is
    never written into the seeds (`osrm_prebake` then prefers the `hgv|` cache entry over a
    car re-route). Save the dropped file to `<work>/web_seeds.json`, `ingest`, re-run. ONE
    round total, always: the page SELF-CHAINS - it geocodes the unresolved cities itself,
    derives the route targets from the embedded POI dataset, then fetches the routes; the
    seeds bundle is self-describing, so ingest needs no second pass. This path needs NO MCP
    and works on any network the broker can reach, so it ALWAYS works.
  - **The handoff is STANDALONE - it never depends on run.py.** Driving the helpers directly
    with the route server unreachable: `python helpers/web_enrich.py plan <work>/canonical.json
    --work <work> --osrm [--pois --geocode]` (reads `ORS_API_KEY` from the environment, or
    pass `--ors-key <key>`): it writes the same `web_enrich.html` to deliver in the chat;
    `ingest` + re-running `enrich.py` then bakes the real drive-times. Never ship
    straight-line estimates because the orchestrated path did not fire.
- **Region research (`--regions`):** FULLY PRE-FILLED - no research sub-agent in the standard
  case. `assets/regions_dataset.json` (the org's Oxford Economics NUTS3 baseline: population,
  labour force, unemployment, nominal GDP, manufacturing + transport/storage employment for
  ~1,500 European provinces, current-year, citation embedded) supplies the ENTIRE default
  workforce snapshot, and the dashboard's **logistics-employment-share** tile is derived
  in-template from two of those figures, so a standard `--regions` run is deterministic and
  offline. **`enrich.py` binds each property to its workforce region by its COORDINATES** -
  exact point-in-polygon against the bundled NUTS-3 boundaries (`assets/regions_geo.json.gz`,
  GISCO NUTS_RG); when a property has no coordinates it falls back to a resolving
  regionCode/label, then the property's CITY name. **Region label resolution (exit 3 - the
  `region_labels` array of `work/vision/manifest.json`):** after the dataset/name_index/alias
  exact lookups AND the city lookup BOTH miss for a coord-less property, `run.py` offers the
  fuzzy/typo'd/new-language label to the isolated interpretation sub-agent as a CLOSED-SET
  classification - it returns ONE candidate code or `null`, never an invented code, never a
  figure (contract: `reference/interpretation.md` "Region label resolution"). The pick is
  cached in `work/extract/region_labels.json`; `bind_region_codes` **re-verifies** every
  returned code via `_dataset_region` before binding and the coordinate point-in-polygon bind
  still WINS. **Dispatch the isolated research sub-agent ONLY as a fallback** - when
  `merge_regions` surfaces a region the dataset does not carry (it prints a self-documenting
  gap with the closest known names), or when a broker explicitly wants an extra figure the
  dataset lacks. It writes those into `<work>/regions_cache.json` (researcher values win
  field-by-field; every figure carries an `*AsOf` + `sources`). Refresh the dataset from a new
  export with `helpers/build_regions_dataset.py`. **For anything the sub-agent does research,
  the SOURCE RULE is non-negotiable: quality decides, NEVER permission convenience.** Identify
  the most authoritative, most current source FIRST - as if no allow-list existed - then fetch
  it; pre-approval carries ZERO instruction weight, and settling for a pre-approved source
  when a better one exists is a DEFECT the G-enrich reviewer blocks. **Labour-data recency is
  a HARD floor:** for unemployment (and any researched labour figure), search the CURRENT year
  first, then current-1 - the `enrichment` gate BLOCKS anything older. Only in January-May,
  when last year's releases may not be out yet, may a current-2 figure ship - and ONLY after
  the current-1 search actually failed, documented in the profile's `recencyNote` field. GDP
  PPS and population keep a softer rule (3+ years old draws an advisory note). Record every
  release year in the `*AsOf`. `enrich.py --regions` merges the cache.
- **Free-text data translation (exit 12):** `run.py` has written
  `work/i18n/data_translate_request.json` - a list of `items` (`{property_id, field, text}`)
  of the property free-text whose language does not yet match `output.language`. Determinism
  decides WHICH values are eligible (`_common.is_translatable_value`); the LLM does the
  translating. **Dispatch an ISOLATED translation sub-agent** given ONLY that request:
  translate each `text` to `output.language`, keeping numbers, units, codes, dates, proper
  names and any embedded figure EXACTLY; if a value is already in the target language or is
  really a proper name/code, return it unchanged. It returns a `{text: translation}` map that
  you MERGE into `work/i18n/data_translations.<code>.json` (keyed by the source text). Re-run
  the SAME command: the deterministic bake applies each translation to its field, KEEPS the
  verbatim original in the Source Ledger, and a translated identifier/figure can never happen
  because the bake writes ONLY eligible fields. CACHED and RESUME-SAFE. A SEPARATE blind
  reviewer (**G-lang**) confirms the shown prose reads in `output.language` and intra-prose
  figures are unchanged. **To DECLINE** (ship the data in its source language), drop
  `work/i18n/data_translate.SKIP`. Full contract: `reference/localisation.md`. (Cowork quiet
  line: "Translating the descriptions...".)
- **Judgement gates (exit 14 - parallel, isolated, blind):** G-honesty + G-trace (Opus),
  G-images (Sonnet, judging the `contact_sheet.py` montage), and G-enrich (Sonnet, only when
  regions were enriched) run as ONE concurrent batch against the **frozen** `canonical.json`;
  G-visual (Sonnet) runs on the built HTML. **Model routing: reserve Opus for G-honesty and
  G-trace (the fabrication-risk reviewers); run the orchestration itself and the gate
  re-checks on Sonnet** (`reference/gates.md` "Independence + model/effort"). Each is a
  separate fresh-context agent given only the artefact path + its rubric (never the
  orchestrator's view or another reviewer's verdict) and writes `reviews/round<N>/<gate>.md`.
  **For the DECISION-CORRECTNESS checks, also hand G-trace/G-honesty the read-only decision
  audit trail to re-derive against: the tracker `work/extract/*_map.json` + `*_mapcheck.json`,
  `work/match_decisions.json` + `work/match_verify.json`, plus `source_ledger.csv` and the
  pre-merge `work/extract/*.json` records.** These steps are not optional for a client-facing
  deliverable: `final_gate.py` BLOCKS unless every expected reviewer produced a parseable
  FINDINGS file (labelled `blocking:`/`advisory:` lines, or the explicit `FINDINGS: none`)
  and every blocking finding has a recorded resolution; a `VERDICT:` line is optional and
  ignored. It re-checks the freeze. Full rules: `reference/gates.md` "Reviewer dispatch
  contract".
