# Environment & install

Moved verbatim from SKILL.md (workstream 1 item 1.1 - the orchestrator card keeps only the
loop; environment nuance lives here). Read this when something about the RUNTIME is unusual -
the loop itself never needs it.

## Which shell runs the helpers

Extraction is native in BOTH environments - pick by what is present, not by preference:

- **Cowork / the sandbox (the PRIMARY path).** Run the helpers with the sandbox shell from the
  skill directory (`python helpers/...`). Pillow ships with the sandbox; the bundled `vendor/`
  PyMuPDF wheel (loaded by `_vendor_wheels` when the system lacks PyMuPDF) gives NATIVE PDF
  extraction - spec tables, areas, clear heights, rents and embedded photos at full fidelity,
  no MCP shell required. The ~45s cap + resume (see the loop) keep a capped run alive.
- **`mcp__shell__run_command` when present (OPTIONAL for extraction - native system PyMuPDF;
  the PREFERRED tier for the exit-8 drive-time fetch because it has outbound network; NOT
  Windows-only, probe for it).** It has **no persistent working directory**, so pass the
  **ABSOLUTE path** to the script (relative paths fail). The helpers live beside SKILL.md, in
  this skill's `helpers/` folder - on Windows that is
  `C:\Users\<you>\.claude\skills\cbre-property-longlist\helpers\` (substitute your own user
  folder; do not hardcode someone else's). Example:
  ```
  mcp__shell__run_command: python "C:\Users\<you>\.claude\skills\cbre-property-longlist\helpers\run.py" --folder "<inputs>" --work "<work>" --client "<Name>" --geocode --pois
  ```
  On this path PyMuPDF is native, `fitz_shim` never fires and there is no 45s shell cap.
  - **Output + shell behaviour (READ - this avoids a large, common time sink).** On many hosts
    `mcp__shell__run_command` runs the command as a **direct process, not through a shell**: a
    real executable (`python`, `node`) returns its stdout to you normally - even thousands of
    lines - but shell **built-ins** (`echo`, `cd`, `dir`, `del`), **operators** (`&&`, `||`,
    `;`, `|`) and **redirection** (`>`) produce EMPTY output and silently do nothing. So
    **call each helper directly, one `python "<abs path>" ...` command per call** - its stdout
    (the gate scorecards, the step markers, any error) comes straight back. Do **NOT** chain
    helpers with `&&`, and do **NOT** write a helper's output to a file and read it back
    through another tool: the output is already returned to you; the file-bounce is pure
    wasted round-trips. If you genuinely need a shell feature (a redirect, a real chain), wrap
    the WHOLE command in `cmd /c "..."` (e.g. `cmd /c "python ... > out.txt 2>&1"`) - that
    restores built-ins, chaining and output together. One-time check on an unfamiliar host: if
    `echo hi` returns nothing but `cmd /c echo hi` returns `hi`, you are on a direct-executor
    shell - follow this rule.

## Media pre-warm knobs (media-heavy runs)

Rasterising + compressing brochure pages is the slow part of merge; `run.py` pre-warms the
per-page image cache in a bounded, CPU-parallel pass so merge runs as cache hits. Knobs:
`CBRE_IMAGE_WORKERS` (default `min(cores, 8)`; `1` forces serial, no process pool) and
`CBRE_PREWARM_SECONDS` (default `30`). Every unit is cached atomically and per-page, so a
capped/killed run converges - the printed `photo cache: X/Y images ready` line tracks it.
The pre-warm only POPULATES the same cache merge reads, so the built dashboard is
byte-identical whether it ran or not.

## No network / no pip needed

Every third-party dependency degrades to a bundled shim automatically: `PyMuPDF`->`fitz_shim`
(pypdfium2 + pdfplumber; if even pypdfium2 is absent, a pdfplumber-ONLY tier still extracts
text and embedded JPEG photos - only page rendering is lost, and the hero pipeline degrades
gracefully through its tiers) and `rapidfuzz`->`rapidfuzz_shim` (stdlib difflib). `Pillow` has
no shim (with no decoder there is no image to harvest), so if it is absent the whole hero
pipeline degrades to the pre-baked placeholder (`assets/placeholder.uri`) and the run prints
one honest note that every option shows a placeholder; the data, map and filters are
unaffected. A blocked pip never stops a run.

**The bundled native wheel (sandbox accelerator).** Because the shim/placeholder degradations
above hurt extraction quality, the skill ships a native **PyMuPDF** wheel under `vendor/` -
the one native library the Cowork sandbox lacks (Pillow and the other Python deps are already
present there, so no Pillow wheel ships; that also keeps the skill under the org
upload-size cap). `helpers/_vendor_wheels.py` unpacks and uses it automatically when the
system package is absent - no pip, no network: it checks the package is importable first (a
strict NO-OP otherwise, so native installs and the shim tests are untouched), then unpacks the
matching wheel ONCE to a temp cache and prepends it to `sys.path`. The wheel is
**platform-locked** (it targets the Cowork sandbox: Linux x86_64, CPython 3.10; PyMuPDF needs
glibc >= 2.28): on any non-matching interpreter `_vendor_wheels` rejects it and the skill
degrades exactly as before (fitz_shim / placeholder). The wheel is intentionally NOT in the
integrity manifest (a corrupt/truncated wheel simply fails to load -> graceful shim fallback,
never a crash). To refresh/retarget, drop the matching manylinux PyMuPDF wheel into `vendor/`;
fitz binds via `fitz_shim` becoming real PyMuPDF. (If a future sandbox also lacks Pillow, a
matching Pillow wheel dropped here is picked up the same way via the
`images.py`/`contact_sheet.py` import fallbacks - but mind the upload-size cap.)

## Offline by design (what actually needs the network)

The Python helpers may have no outbound network in a sandbox. Your `WebFetch`/`WebSearch`
tools reach **general web PAGES** (so region-research prose is fine to hand to the helpers via
`<work>/regions_cache.json`), but they do **NOT** reach the structured geocoding/routing/POI
**API** endpoints (Nominatim/Overpass/OSRM/ORS) - do not try; that path is dead. It rarely
matters, because most of the data needs no network at all:

- **Geocoding: NO network for European cities.** `assets/cities_dataset.json.gz` bundles a
  ~19k-city European gazetteer (GeoNames, name + country + real coordinates), so
  `enrich.py --geocode` resolves map coordinates AND fills an unknown country fully OFFLINE.
  A city the gazetteer does not carry (rare) is geocoded by the exit-8 **fetcher page itself**
  (it self-chains geocode -> route targets -> routes in one pass) - never a `WebFetch` to
  Nominatim. On an ONLINE host where Python reaches the web,
  `python helpers/seed_geocode.py coords.json --cache-dir <work>` seeds the cache from a real
  geocoder result.
- **POIs: NO network at all.** `assets/poi_dataset.json.gz` bundles COMPLETE datasets (all
  scheduled airports worldwide via OurAirports, all ports, all SGKV intermodal terminals -
  ~6,900 facilities), so the genuine nearest air/port/rail is a pure offline computation
  ("nearest of a complete set" IS the genuine nearest); borders/cities come from the curated
  library.
- **Region workforce: NO network in the standard case** (the bundled Oxford Economics NUTS-3
  dataset - see "Region research" in reference/agentic-steps.md); researched extras go via
  `<work>/regions_cache.json`.
- **Drive-times/live routing are the ONE genuinely network-bound step** - that is exit 8, with
  its four-tier fetch and universal chat fallback ("Web enrichment (exit 8)" in
  reference/agentic-steps.md).

## Install (teammates)

- Drop the `cbre-property-longlist/` folder into `~/.claude/skills/` (Windows:
  `C:\Users\<you>\.claude\skills\`); it triggers on the phrases in the description. Nothing
  client-specific is baked in - every run reads a per-project `project.yaml` in the working
  folder.
- **One-time per user, Windows-MCP-host hardening ONLY (Cowork needs none of this):**
  `python helpers/setup_permissions.py --yes` does two things in your user `settings.json`:
  (a) pre-approves the skill's four FIXED fetch domains (ORS/OSRM/Nominatim/Overpass) so runs
  never stop for per-fetch permission clicks; and (b) installs a **PreToolUse shell-guard
  hook** (`helpers/shell_guard_hook.py`, shipped with the skill) that blocks the sandboxed
  bash (`mcp__workspace__bash`) from running the skill's helpers and redirects them to
  `mcp__shell__run_command` - keeping that host on its native system PyMuPDF rather than the
  shim. Restart the session once after (hooks load at session start).
- Get a free openrouteservice key (trucking drive-times) and set it as the `ORS_API_KEY` env
  var - personal per user, never shared inside the skill.
- Python deps: `pypdf`, `python-pptx`, `openpyxl`, `Pillow`, `rapidfuzz`, `jsonschema`,
  `PyYAML`, `requests`, plus a PDF engine - `PyMuPDF` (fitz) preferred, otherwise `pypdfium2`
  + `pdfplumber` via `fitz_shim` (automatic; see "No network / no pip needed" - the bundled
  wheel usually makes this moot).
- Optional: `pillow-heif` (HEIC images; degrades silently if absent), `extract-msg` (only the
  `.msg` email fallback), `playwright` (only `render_qa.py`'s headless screenshots), and
  **LibreOffice** (headless `soffice` - the only reliable PPTX slide renderer: with it, vision
  rasterisation and slide heroes cover vector/text-only slides too; without it both degrade to
  the slides' embedded pictures).

## For Cowork / non-technical users

Nothing technical to learn. Put all your property files - agent and landlord emails,
availability spreadsheets, brochures, photos - into one folder, then ask for the longlist
(e.g. "build the property longlist for this folder").

**Your folder ends up with three folders in it, numbered so they sort in order:** `1. Input`
(your files), `2. Work Files` (the machinery - you never need to open it) and `3. Output`.
**The dashboard is the `.html` file in `3. Output`** - double-click it. Only four files ever
land there: the dashboard, the Gaps Report, the Longlist spreadsheet and the Source Ledger.

Two things will happen along the way:

- **One quick setup form first.** A single box asks the client name, which extras to add
  (drive-time maps, a workforce snapshot, logistics landmarks), an optional routing key,
  whether to also pull details from your Outlook emails, and the dashboard language. Pick what
  you want and submit once - there is no wrong answer, and you are only asked once per project.
- **A question or two, if your files disagree.** If your spreadsheet lists 17 options and the
  brochures add up to 41, or half your sizes are in sq ft and half in sq m, the run stops and
  asks rather than picking for you. Answer in plain language; if you genuinely have no
  preference, say "skip" and it takes the sensible default and writes down that it did.
- **You may be handed a small web page.** If you are sent a file called `web_enrich.html`,
  open it in your own browser, click "Fetch all", wait for it to finish, then drop the
  downloaded `web_seeds.json` file back into the chat. This is how real drive-times and map
  data are pulled when the office network blocks them - a home or hotspot connection works if
  the office one does not. It happens at most once.

When it finishes you get your **dashboard** (a single ready-to-share file, in `3. Output`)
and a **Gaps Report** listing anything that could not be confirmed, so you know exactly what
to chase (a Source Ledger that traces every figure to its file is saved alongside them for
audit). Nothing is ever invented - if a figure is not in your files it is shown as missing,
not guessed.
