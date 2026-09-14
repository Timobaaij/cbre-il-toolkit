# project.yaml + auto-discovery

One `project.yaml` per client project, kept in the **work dir** (`2. Work Files/project.yaml` in the three-folder project layout; never in the skill - nothing client-specific is baked into the skill). `intake.py` scaffolds it from auto-discovery; the orchestrator confirms it with the broker before running.

`inputs.folder` is relative to the inputs folder itself, and every persisted path in the work dir (the inventory's relpaths, the extract filenames, the image-cache keys) is **relative or name-keyed, never an absolute project path** - which is why a project folder can be renamed or restructured into the three-folder layout without invalidating a single cached stage. The one absolute path any run writes is `<work>/.claude/launch.json` (the preview server), and it is rewritten from scratch every time it is needed.

```yaml
# The scaffolded file opens with a header comment saying that EVERY value in it is a default
# the scaffold guessed and that `setup.confirmed` is the ONLY thing that says otherwise (B63,
# see "setup:" below). intake's cluster merge edits the file IN PLACE, so that header and every
# other comment survive a re-cluster.
setup:
  confirmed: false             # intake writes false; the orchestrator sets true after the Stage-0 form
client:
  name: Normal                 # display + deliverable filenames
  confidential: true           # informational; nothing in the pipeline reads it
market:
  title_html: ""               # hero <h1> (HTML allowed). BLANK renders the localised default, which names the client: "<client> - Industrial & Logistics opportunities". Keep ONE <em>..</em> pair for the accent colour
  eyebrow: "Hungary, Czech Republic & Slovakia"                          # hero eyebrow
  region_label: "CEE"          # topbar meta prefix
  countries: ["HU", "CZ", "SK"]  # seeded ONCE by the scaffold from the KNOWN cluster countries; informational (the dashboard derives its country filter from the records)
output:
  filename: "CBRE_Property_Dashboard_Normal.html"
  compiled_date: "2026-04-23"  # ISO; defaults to today if blank
  language: "English"          # Stage 0 Q3: dashboard CHROME language (see "Dashboard language" below)
inputs:
  folder: "."                      # informational; the run takes the inputs folder from its command line
  present_types: ["pdf", "pptx"]   # auto-filled by intake; informational (the run reads inventory.json)
  clusters:                        # region -> ISO-2 country (auto-inferred; fix if wrong; '' = not inferred: fill it, or let --geocode resolve it)
    Pilsen: CZ
    Budapest: HU
    Bratislava: SK
    Westford: ''                   # the city index did not know this one: BLANK, never a placeholder token
  emails:                          # Stage 0 Q2 (see SKILL.md "broker setup prompt")
    source: none                   # none | outlook | folder  (folder = .msg/.eml fallback for no-MCP)
    outlook_folder: ""             # Outlook mail FOLDER when source: outlook (e.g. Inbox, or "Normal CEE"); blank = all folders
    mailbox: ""                    # optional shared/delegated mailbox email
    query: ""                      # subject/keyword text (combine with a date window)
    folder: ""                     # filesystem path to .msg/.eml when source: folder (fallback only)
enrichment:                    # broker opt-in; ask in plain language before running (see SKILL.md)
  geocode: true                # fill map coordinates (recommended)
  pois: true                   # ports/rail/airports/borders on the map
  osrm: false                  # drive-times to the POIs (network or the web_enrich handoff)
  regions: false               # workforce profiles (bundled Oxford Economics NUTS-3 dataset by default; a research sub-agent only as fallback via regions_cache.json).
                               # ALSO harmonises the `region` LABEL: when the sources state
                               # regions at more than one administrative level (a county from a
                               # brochure, the wider region from a tracker), each property's label
                               # becomes the NUTS-3 area its own coordinates fall inside, disclosed
                               # in the Source Ledger and the Gaps Report. Without this extra the
                               # labels ship exactly as stated, mixed levels and all. (I11)
  osrm_endpoint: "https://router.project-osrm.org"   # NOT read by run.py today: enrich.py uses its own --osrm-endpoint default (the same URL), so editing this changes nothing
  ors_api_key: ""              # openrouteservice key -> TRUCKING (driving-hgv) distances/times
                               # via the ORS matrix API (1 request per property, throttled to the
                               # free tier's 40/min; falls back to the ORS_API_KEY env var).
                               # Blank = car routing via public OSRM, flagged in the ledger.
                               # Per-project/per-user - NEVER commit a key into the shared skill.
qa:
  fill_threshold: 0.6          # min fraction of core fields populated (non-tbd) per record (run.py passes this to the coverage gate)
clarify:
  mode: interactive            # the ask mode; see "clarify:" below
```

### Which keys are read, and by what
Not every key in the scaffold feeds a stage. Knowing which do stops a broker correcting a value that nothing will ever read:

| read by the helpers | `setup.confirmed`, `client.name`, `market.title_html` / `eyebrow` / `region_label`, `output.filename` / `compiled_date` / `language`, `inputs.emails.source`, `enrichment.geocode` / `pois` / `osrm` / `regions` / `ors_api_key`, `qa.fill_threshold`, `clarify.mode` / `assume_defaults` |
|---|---|
| read by the ORCHESTRATOR | `inputs.emails.outlook_folder` / `mailbox` / `query` / `folder`: they fill the slots of `prompts/outlook-ingest.md` |
| informational only | `client.confidential`, `market.countries`, `inputs.folder`, `inputs.present_types`, `enrichment.osrm_endpoint`, and `inputs.clusters` (next line) |

**`inputs.clusters` is the human-readable record of the inferred (and hand-corrected) region -> country map; it is not a data source.** The readers get each deck's country from `inventory.json`, which intake computes from the city index and the Stage-0 label cache on every pass. A country you correct in this block is preserved by every later merge (see "Auto-discovery"), but it does not reach a reader today; to change what a reader is told, fix the label cache (`work/intake_clusters.json`, `country`) or let `--geocode` resolve it.

(The template version is **not** a `project.yaml` setting - the chrome is pinned by `assets/VERSION` and enforced by `gate_runner.py validate-html`, which fails the build if the template's SHA-256 drifts from the recorded `chrome_sha256`. Nothing client-specific pins it.)

## Dashboard language (`output.language`, Stage 0 Q3)
`output.language` chooses the language of the dashboard CHROME (the fixed UI vocabulary: tabs, filters, sort options, the KPI strip labels, section titles, row labels, the compare table, map controls, the footer disclaimer). It accepts an English name ("German"), an endonym ("Deutsch") or an ISO code ("de"); blank or "English" means English. **Any European Latin-script language works, plus Simplified Chinese** ("Chinese" / "Mandarin" / "zh" / "中文") - 13 are bundled (instant); any other SUPPORTED one is translated once in Cowork and cached (the exit-11 fallback). See `reference/localisation.md` for the full supported-vs-bundled list, the cache, exit 11 and the G-i18n gate.

The flow is: `run.py` reads `output.language` (the `--language` flag overrides it) and passes it to `merge.py`, which stamps it on `canonical.json` as `meta.language` (and an optional explicit `meta.locale`, a BCP-47 tag such as `de-AT`). At build time `build_dashboard.render()` resolves `meta.language` to the bundled chrome table in `helpers/i18n.py` and injects it into the page as a compact, sorted JSON block (the `{{ui_json}}` token) plus a `{{locale}}` for number and country-name formatting. The page applies the table to the static chrome once on load and reads it for every dynamically built card, modal and compare row.

Two safety properties hold by construction:
- **Per-key English fall-back.** `i18n.py` carries a COMPLETE English baseline; every other language is layered on top key by key. A language not yet translated, or a single missing key, falls back to the English text - never a blank, never a raw key. (English + 11 European languages + Simplified Chinese are bundled as `assets/i18n/*.json`; any other SUPPORTED European Latin-script language is translated on demand and cached - see `reference/localisation.md`.)
- **DATA is never translated.** Only chrome is localised. Property, developer, landlord, region, city and POI names, every figure, date, unit and source citation, and the canonical `tbd` / `—` sentinel all stay exactly as sourced. The build is deterministic: the same `canonical.json` and language always produce byte-identical HTML, so `validate-html` re-running the render still passes.

Because `project.yaml` is a merge input, changing the language re-runs the cached merge (and rebuild) on the next pass.

## Auto-discovery (`intake.py`)
Scans the folder RECURSIVELY (hidden and underscore-prefixed directories, Office `~$` lock files and the work dir itself are skipped; scanned subfolders are named in the output) for brochures (`.pdf`, `.pptx`), trackers (`.xlsx`, `.xlsm`, `.csv`), images (`.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif`) and emails (`.msg`, `.eml`); any other file is listed under `unclassified` rather than silently ignored, and a byte-identical duplicate is extracted once and listed under `skipped_duplicates`. It infers a city/region cluster per brochure from its filename in two shapes: the last spaced-dash segment (`Options - Westford.pdf` -> Westford, trailing noise like `- FINAL` / `- v2` dropped), or a NUMBERED EXPORT's remainder once its 1-3 digit index is stripped (`03_Riverside_Park.pdf` -> Riverside Park; F3). The country comes from `assets/poi_library.json`'s `city_country` index, a CEE-seeded **convenience**: **a miss leaves the country BLANK** (`Region: ''` in the scaffold), never a placeholder token, because the old `??` token travelled into the reader manifest and readers derived the country themselves, three different ways (F7). It writes `inventory.json` and scaffolds `project.yaml` pre-filled from what was found (incl. `inputs.emails.source` defaulted to `folder` when `.msg`/`.eml` are present, else `none`). A blank country is filled automatically by `enrich.py --geocode`, which reverse-geocodes the country code from the resolved coordinates (any geography, no index needed).

Each cluster in `inventory.json` also carries a `confidence` (`high`/`low`) and the raw source `stems`: `low` marks the whole-stem fallback (no clean ` - ` separator, no numbered-export index, and the unspaced-dash tail is not a known city, e.g. `Options-Oporto`), so the Stage-0 orchestrator can judge ONLY the ambiguous tail. This is a purely additive signal - it never changes the regex's chosen region, so an offline run is unchanged. `inventory.json` also always carries a top-level `cluster_label_notes` list (empty on a regex-only run): one `{stem, region, country, note}` per cached label that recorded a close call (F16), for the Gaps Report's "Noted, not put to you".

### `work/intake_clusters.json` (the Stage-0 LLM label cache)
For low-confidence clusters the orchestrator judges the likely city/region from the filename stem(s) and writes an **input-hashed** cache the next intake pass applies deterministically:

```json
{"input_hash": "<copy inventory.json's `cluster_input_hash` - the BROCHURE-SET identity. Do NOT copy `input_hash`, which is the whole-corpus key (every classified input + its content) that the QA window uses; it will never match. Both key NAMES are accepted here, so `cluster_input_hash` may be used verbatim.>",
 "schema_version": 1,
 "labels": [{"stem": "Options-Oporto", "region": "Oporto", "country": "PT",
             "note": "<optional, one line, only for a genuine close call; capped at 400 chars>"}]}
```

`intake.discover` applies a cached label ONLY when (a) `input_hash` matches the current brochure set, (b) the label's `stem` is a real discovered file, and (c) its `region` is non-empty and not a noise token; ANY failure discards the WHOLE cache and falls back to the regex (`infer_cluster`) verbatim (`note` is optional and never a reason to discard). A changed brochure set changes the hash and invalidates the cache, so no stale label survives a folder change. The cache is added to `run.py`'s Stage-0 resume inputs, so writing it re-clusters and then `main()` MERGES the corrected `region -> country` map into the existing `project.yaml inputs.clusters` rather than overwriting it. The merge rules:

- **In place, comments kept.** Only the `clusters:` block is rewritten; every other byte of the file, every comment (the `setup.confirmed` header included), the line endings and the trailing-newline state survive. An unchanged entry is kept byte-exact, inline comment and all. The merge never deletes a comment: one that led a region that no longer exists stays where it was, for you to keep or remove.
- **A hand-set country wins.** A non-blank country in the file is kept whatever intake infers for that region, blank or different. The index gives the same answer for the same key every pass, so a different non-blank value can only be a human correction.
- **A blank means "not inferred yet", so it is re-filled** whenever the index or the label cache knows the region. THE LIMIT: the design cannot tell "not inferred yet" from "the broker cleared this"; there is no value that means "no country". If you want a region to carry no country, expect intake to put the inferred one back on the next re-cluster.
- **Placeholders fold together.** `''`, a bare `Region:` (null) and the legacy `'??'` an older scaffold wrote are all "unknown"; a file whose only difference is that spelling is not rewritten at all.
- **It refuses rather than guesses.** If the `clusters:` block cannot be located unambiguously (no or two top-level `inputs:` keys, two `clusters:` keys, an inline flow mapping `clusters: {A: XX}`, a body line that is not one `Region: country` entry), the file is left byte-identical and intake prints a `WARNING` naming the reason; the summary line then says `project.yaml exists; kept`. There is deliberately no whole-document rewrite behind that refusal, because a whole-document dump drops every comment. Fix: restore the block to the scaffold's shape, or copy `inventory.json`'s clusters in by hand.

**Absence of the cache IS the regex opt-out** - no `.SKIP` sentinel is needed (unlike the tracker map, there is no exit/dispatch to decline). A no-LLM / non-interactive / offline run simply never writes `work/intake_clusters.json`, so the deterministic regex stands and the offline evals are byte-identical. The LLM sets ONLY the inventory's cluster (its routing label, and the country the readers are handed for that deck), mirrored into `project.yaml inputs.clusters` for the record; it does not touch `market.countries`, which the scaffold seeds once from the index. The card's displayed region/city are read from the brochure body at extraction, so a wrong cluster label can never fabricate a displayed field - the existing coverage gate (a hallucinated region maps zero brochures -> an empty cluster -> blocked) and the broker confirmation are the backstops.

## Stage-0 setup prompt (ONE consolidated widget form)
At intake the orchestrator presents ONE consolidated `visualize` widget form with ALL SIX setup questions at once (client name, enrichment extras, the optional openrouteservice key as an inline field, the email scope - **a named Outlook mail folder** via the `outlook_email_search` sub-agent with `folderName`, **across all of Outlook**, or **none** - the dashboard language, and the ask mode). The verbatim form and its submission parsing are in `reference/setup-form.md`; the mandate (single widget, all six together, one submit, plain-text fallback only when the widget tool is genuinely unavailable) is SKILL.md "The broker setup prompt". (A Windows `.msg`/`.eml` folder is a no-MCP fallback only.) The answers are written to `client:`, `enrichment:`, `inputs.emails:`, `output.language` and `clarify.mode` so subsequent re-runs are non-interactive.

## setup: - did a HUMAN answer the Stage-0 form? (B63)
```yaml
setup:
  confirmed: false   # intake writes false; the orchestrator sets true after the form
```
The one flag that separates "the scaffold guessed these six values" from "the broker chose
them". `intake.scaffold_yaml` fills every Stage-0 key with a default on the first pass, so
the presence of values proves nothing: the old rule ("skip the widget when project.yaml
carries the answers") was therefore true on every run, and the form was skipped every time.
While `confirmed` is not true, `run.py` leads every hand-off with the setup instruction and,
on a pass with no other hand-off, stops at exit 13 (`setup_form`, blocking). The headless
escapes clear it as a recorded decision: `work/clarify.SKIP_ALL` or `clarify.assume_defaults`.

## clarify: - the ask mode (workstream 3; INTERACTIVE IS THE STANDARD)
```yaml
clarify:
  mode: interactive   # the STANDARD: judgement calls the files cannot settle become
                      # exit-13 broker questions (unsure match/pick verdicts, photo
                      # confirmations, reader doubts, excluded-figure conflicts).
                      # "headless": decide-sensibly-and-disclose - every new kind
                      # resolves to today's safe default, attributed in its reason.
  # assume_defaults: true   # also forces headless (as does work/clarify.SKIP_ALL)
```
`clarify_mode()` resolves it: an explicit `mode` wins; `assume_defaults: true` or the
`work/clarify.SKIP_ALL` sentinel force headless; absent = interactive. Headless behaviour
is unchanged from before the mode existed.

**Interactive does not mean chatty.** A question is only put to the broker when its answer
would change what the DASHBOARD SHOWS - a rendered value, photo or label, or how many options
ship (`clarify.materiality()`, `reference/evidence-standard.md` rule 4). Everything else the
run was unsure about is recorded and printed in the Gaps Report under "Noted, not put to
you", with the value that shipped instead. There is no config for this: it is the standard in
both modes, because a question that cannot change the deliverable is not worth an
interruption in either.

## Empty-string handling
Blank `project.yaml` strings fall back to defaults (today's date, the localised eyebrow, and the localised headline with `client.name` composed into it) - the build never emits empty hero text. A `market.lede` key is accepted and ignored: v45 removed the paragraph it filled.

## Correcting a datum - `work/overrides.json` (the full contract)

The ONE durable way to correct extracted data. Re-applied after extraction on **every** run,
so it survives re-extraction. A JSON **list**, so it is diffable and append-only:

```json
[
  {
    "id": "ov-001",
    "where": { "source_file": "Warehouse Availability.xlsx", "sheet": "Longlist", "row": 13 },
    "set": { "city": "Corby" },
    "expect": { "city": "Northamptonshire" },
    "why": "the county sat in the city column; the city is Corby (tracker Longlist!r13)",
    "verified_by": "you@cbre.com"
  }
]
```

- **`where`** targets an EXISTING record: `source_file` (basename, case-insensitive) plus ONE
  discriminator - `sheet` + `row` for a spreadsheet (**1-based, exactly as you read it in
  Excel**), or `page_no` for a brochure. Zero matches applies NOTHING and reports **STALE**;
  more than one applies NOTHING and reports **AMBIGUOUS** (it fails closed - a
  `source_file`-only entry must never quietly rewrite 12 tracker rows). Add **`"multi":
  "all"`** only if every match really should change - the one sanctioned multi-row correction.
- **`expect`** is optional but strongly recommended: if the current value no longer matches,
  the entry applies nothing and reports **SUPERSEDED** - the guard against a row being
  inserted upstream so `row 13` is now a different property.
- **`why`** is REQUIRED and non-empty - it ships in the Source Ledger and the Gaps Report.
- It can never create a property, a record or a new field, and **`areaUnit` / `rentUnit` are
  DENIED** (applied before the dataset unit vote, they could silently relabel every figure -
  the 10.76x class). Correct the area/rent figures themselves instead; the ONE sanctioned way
  a unit is set by a human is an exit-13 ANSWER (attributed - an override is silent).
- Every applied correction is DISCLOSED, not laundered: an `override` row in the Source Ledger
  (`grep ,override, source_ledger.csv` lists every manual touch), the field's own ledger row
  gains `(manual override ov-001: ...)`, and the Gaps Report gets a **"Manual corrections
  applied"** line with old -> new + why. A stale entry is named at startup, after merge, and
  in the Gaps Report - it cannot rot silently.
