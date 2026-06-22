# project.yaml + auto-discovery

One `project.yaml` per client project, kept in the working folder (never in the skill - nothing client-specific is baked into the skill). `intake.py` scaffolds it from auto-discovery; the orchestrator confirms it with the broker before running.

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
  regions: false               # workforce profiles (research sub-agent + regions_cache.json)
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

## Auto-discovery (`intake.py`)
Globs the folder for `*.pdf *.pptx *.xlsx *.msg *.eml` and images; infers a city/region cluster per brochure from its filename (`Normal Options - Pilsen.pdf` -> Pilsen) and the country from `assets/poi_library.json`'s `city_country` index (a CEE-seeded **convenience** - a miss leaves `??`); writes `inventory.json`; scaffolds `project.yaml` pre-filled from what was found (incl. `inputs.emails.source` defaulted to `folder` when `.msg`/`.eml` are present in the folder, else `none`). Confirm the inferred clusters and countries before extracting - and a remaining `??` is filled automatically by `enrich.py --geocode`, which reverse-geocodes the country code from the resolved coordinates (any geography, no index needed).

Each cluster in `inventory.json` also carries a `confidence` (`high`/`low`) and the raw source `stems`: `low` marks the whole-stem fallback (no clean ` - ` separator and the unspaced-dash tail is not a known city, e.g. `Options-Oporto`), so the Stage-0 orchestrator can judge ONLY the ambiguous tail. This is a purely additive signal - it never changes the regex's chosen region, so an offline run is unchanged.

### `work/intake_clusters.json` (the Stage-0 LLM label cache)
For low-confidence clusters the orchestrator judges the likely city/region from the filename stem(s) and writes an **input-hashed** cache the next intake pass applies deterministically:

```json
{"input_hash": "<sha1[:8] over the sorted brochure relpaths, copied from inventory.json>",
 "schema_version": 1,
 "labels": [{"stem": "Options-Oporto", "region": "Oporto", "country": "PT"}]}
```

`intake.discover` applies a cached label ONLY when (a) `input_hash` matches the current brochure set, (b) the label's `stem` is a real discovered file, and (c) its `region` is non-empty and not a noise token; ANY failure discards the WHOLE cache and falls back to the regex (`infer_cluster`) verbatim. A changed brochure set changes the hash and invalidates the cache, so no stale label survives a folder change. The cache is added to `run.py`'s Stage-0 resume inputs, so writing it re-clusters and then `main()` MERGES the corrected `region -> country` into the existing (broker-confirmed) `project.yaml inputs.clusters` rather than overwriting it.

**Absence of the cache IS the regex opt-out** - no `.SKIP` sentinel is needed (unlike the tracker map, there is no exit/dispatch to decline). A no-LLM / non-interactive / offline run simply never writes `work/intake_clusters.json`, so the deterministic regex stands and the offline evals are byte-identical. The LLM sets ONLY `inputs.clusters` (a routing/scaffold label + the `market.countries` seed); the card's displayed region/city are read from the brochure body at extraction, so a wrong cluster label can never fabricate a displayed field - the existing coverage gate (a hallucinated region maps zero brochures -> an empty cluster -> blocked) and the broker confirmation are the backstops.

## Stage-0 setup prompt (two questions)
At intake the orchestrator asks the broker two plain-language questions (one `AskUserQuestion`, see SKILL.md): (1) which enrichment extras to add, and (2) whether to pull property details from emails - from **a named Outlook mail folder** (the `outlook_email_search` sub-agent with `folderName`, e.g. Inbox or a folder like "Normal CEE"), **across all of Outlook**, or **none**. (A Windows `.msg`/`.eml` folder is a no-MCP fallback only.) The answers are written to `enrichment:` and `inputs.emails:` so subsequent re-runs are non-interactive.

## Empty-string handling
Blank `project.yaml` strings fall back to defaults (today's date, a generated lede, a generic eyebrow) - the build never emits empty hero text.
