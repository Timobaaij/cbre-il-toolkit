# project.yaml + auto-discovery

One `project.yaml` per client project, kept in the **work dir** (`2. Work Files/project.yaml` in the three-folder project layout; never in the skill - nothing client-specific is baked into the skill). `intake.py` scaffolds it from auto-discovery; the orchestrator confirms it with the broker before running.

`inputs.folder` is relative to the inputs folder itself, and every persisted path in the work dir (the inventory's relpaths, the extract filenames, the image-cache keys) is **relative or name-keyed, never an absolute project path** - which is why a project folder can be renamed or restructured into the three-folder layout without invalidating a single cached stage. The one absolute path any run writes is `<work>/.claude/launch.json` (the preview server), and it is rewritten from scratch every time it is needed.

```yaml
client:
  name: Normal                 # display + deliverable filenames
  confidential: true
market:
  title_html: "CEE logistics <em>options</em> for your next facility."  # hero <h1> (HTML allowed)
  eyebrow: "Hungary, Czech Republic & Slovakia"                          # hero eyebrow
  region_label: "CEE"          # topbar meta prefix
  countries: ["HU", "CZ", "SK"]
  lede: ""                     # optional; a sensible default is generated if blank
output:
  filename: "CBRE_Property_Dashboard_Normal.html"
  compiled_date: "2026-04-23"  # ISO; defaults to today if blank
  language: "English"          # Stage 0 Q3: dashboard CHROME language (see "Dashboard language" below)
inputs:
  folder: "."
  present_types: ["pdf", "pptx"]   # auto-filled by intake
  clusters:                        # region -> country (auto-inferred by regex, LLM-refined at Stage 0 for ambiguous filenames, broker-confirmed; fix if wrong)
    Pilsen: CZ
    Budapest: HU
    Bratislava: SK
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
  osrm_endpoint: "https://router.project-osrm.org"
  ors_api_key: ""              # openrouteservice key -> TRUCKING (driving-hgv) distances/times
                               # via the ORS matrix API (1 request per property, throttled to the
                               # free tier's 40/min; falls back to the ORS_API_KEY env var).
                               # Blank = car routing via public OSRM, flagged in the ledger.
                               # Per-project/per-user - NEVER commit a key into the shared skill.
qa:
  fill_threshold: 0.6          # min fraction of core fields populated (non-tbd) per record (run.py passes this to the coverage gate)
```

(The template version is **not** a `project.yaml` setting - the chrome is pinned by `assets/VERSION` and enforced by `gate_runner.py validate-html`, which fails the build if the template's SHA-256 drifts from the recorded `chrome_sha256`. Nothing client-specific pins it.)

## Dashboard language (`output.language`, Stage 0 Q3)
`output.language` chooses the language of the dashboard CHROME (the fixed UI vocabulary: tabs, filters, sort options, the KPI strip labels, section titles, row labels, the compare table, map controls, the footer disclaimer). It accepts an English name ("German"), an endonym ("Deutsch") or an ISO code ("de"); blank or "English" means English. **Any European Latin-script language works, plus Simplified Chinese** ("Chinese" / "Mandarin" / "zh" / "中文") - 13 are bundled (instant); any other SUPPORTED one is translated once in Cowork and cached (the exit-11 fallback). See `reference/localisation.md` for the full supported-vs-bundled list, the cache, exit 11 and the G-i18n gate.

The flow is: `run.py` reads `output.language` (the `--language` flag overrides it) and passes it to `merge.py`, which stamps it on `canonical.json` as `meta.language` (and an optional explicit `meta.locale`, a BCP-47 tag such as `de-AT`). At build time `build_dashboard.render()` resolves `meta.language` to the bundled chrome table in `helpers/i18n.py` and injects it into the page as a compact, sorted JSON block (the `{{ui_json}}` token) plus a `{{locale}}` for number and country-name formatting. The page applies the table to the static chrome once on load and reads it for every dynamically built card, modal and compare row.

Two safety properties hold by construction:
- **Per-key English fall-back.** `i18n.py` carries a COMPLETE English baseline; every other language is layered on top key by key. A language not yet translated, or a single missing key, falls back to the English text - never a blank, never a raw key. (English + 11 European languages + Simplified Chinese are bundled as `assets/i18n/*.json`; any other SUPPORTED European Latin-script language is translated on demand and cached - see `reference/localisation.md`.)
- **DATA is never translated.** Only chrome is localised. Property, developer, landlord, region, city and POI names, every figure, date, unit and source citation, and the canonical `tbd` / `—` sentinel all stay exactly as sourced. The build is deterministic: the same `canonical.json` and language always produce byte-identical HTML, so `validate-html` re-running the render still passes.

Because `project.yaml` is a merge input, changing the language re-runs the cached merge (and rebuild) on the next pass.

## Auto-discovery (`intake.py`)
Globs the folder for `*.pdf *.pptx *.xlsx *.msg *.eml` and images; infers a city/region cluster per brochure from its filename (`Normal Options - Pilsen.pdf` -> Pilsen) and the country from `assets/poi_library.json`'s `city_country` index (a CEE-seeded **convenience** - a miss leaves `??`); writes `inventory.json`; scaffolds `project.yaml` pre-filled from what was found (incl. `inputs.emails.source` defaulted to `folder` when `.msg`/`.eml` are present in the folder, else `none`). Confirm the inferred clusters and countries before extracting - and a remaining `??` is filled automatically by `enrich.py --geocode`, which reverse-geocodes the country code from the resolved coordinates (any geography, no index needed).

Each cluster in `inventory.json` also carries a `confidence` (`high`/`low`) and the raw source `stems`: `low` marks the whole-stem fallback (no clean ` - ` separator and the unspaced-dash tail is not a known city, e.g. `Options-Oporto`), so the Stage-0 orchestrator can judge ONLY the ambiguous tail. This is a purely additive signal - it never changes the regex's chosen region, so an offline run is unchanged.

### `work/intake_clusters.json` (the Stage-0 LLM label cache)
For low-confidence clusters the orchestrator judges the likely city/region from the filename stem(s) and writes an **input-hashed** cache the next intake pass applies deterministically:

```json
{"input_hash": "<copy inventory.json's `cluster_input_hash` - the BROCHURE-SET identity. Do NOT copy `input_hash`, which is the whole-corpus key (every classified input + its content) that the QA window uses; it will never match. Both key NAMES are accepted here, so `cluster_input_hash` may be used verbatim.>",
 "schema_version": 1,
 "labels": [{"stem": "Options-Oporto", "region": "Oporto", "country": "PT"}]}
```

`intake.discover` applies a cached label ONLY when (a) `input_hash` matches the current brochure set, (b) the label's `stem` is a real discovered file, and (c) its `region` is non-empty and not a noise token; ANY failure discards the WHOLE cache and falls back to the regex (`infer_cluster`) verbatim. A changed brochure set changes the hash and invalidates the cache, so no stale label survives a folder change. The cache is added to `run.py`'s Stage-0 resume inputs, so writing it re-clusters and then `main()` MERGES the corrected `region -> country` into the existing (broker-confirmed) `project.yaml inputs.clusters` rather than overwriting it.

**Absence of the cache IS the regex opt-out** - no `.SKIP` sentinel is needed (unlike the tracker map, there is no exit/dispatch to decline). A no-LLM / non-interactive / offline run simply never writes `work/intake_clusters.json`, so the deterministic regex stands and the offline evals are byte-identical. The LLM sets ONLY `inputs.clusters` (a routing/scaffold label + the `market.countries` seed); the card's displayed region/city are read from the brochure body at extraction, so a wrong cluster label can never fabricate a displayed field - the existing coverage gate (a hallucinated region maps zero brochures -> an empty cluster -> blocked) and the broker confirmation are the backstops.

## Stage-0 setup prompt (ONE consolidated widget form)
At intake the orchestrator presents ONE consolidated `visualize` widget form with ALL FIVE setup questions at once (client name, enrichment extras, the optional openrouteservice key as an inline field, the email scope - **a named Outlook mail folder** via the `outlook_email_search` sub-agent with `folderName`, **across all of Outlook**, or **none** - and the dashboard language). The verbatim form and its submission parsing are in `reference/setup-form.md`; the mandate (single widget, all five together, one submit, plain-text fallback only when the widget tool is genuinely unavailable) is SKILL.md "The broker setup prompt". (A Windows `.msg`/`.eml` folder is a no-MCP fallback only.) The answers are written to `client:`, `enrichment:`, `inputs.emails:` and `output.language` so subsequent re-runs are non-interactive.

## Empty-string handling
Blank `project.yaml` strings fall back to defaults (today's date, a generated lede, a generic eyebrow) - the build never emits empty hero text.
