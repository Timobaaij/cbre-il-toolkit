---
name: cbre-property-longlist
description: Build a self-contained, CBRE-branded interactive HTML property LONGLIST DASHBOARD for Industrial & Logistics occupiers from raw market inputs. Ingests a folder of property materials (landlord/agent emails, Excel availability sheets, PPTX and PDF brochures, images) and structures them into ONE portable .html file (a filterable card grid, comparison, a Leaflet map and detail modals) visually identical to the CBRE reference, plus an auditable Source Ledger and a Gaps Report. Every field traces to a source and unknowns show as 'tbd', never invented; generalised per project via project.yaml, reusable across clients. Use whenever the user wants to build a longlist, build the property longlist, create the property dashboard, make the options HTML, a shortlist dashboard, a longlist of options, or turn a folder of brochures/emails into a dashboard. Trigger even when the need is only described (turn this folder of options into the usual dashboard; make the CBRE options page for client X).
---

# CBRE Property Longlist

Turns a folder of heterogeneous property inputs (emails, Excel, PPTX + PDF brochures, images) into **one self-contained, CBRE-branded interactive HTML longlist dashboard** - a filterable card grid, a Leaflet map, side-by-side comparison and per-property detail modals - identical in look to the CBRE reference. Reusable across client projects, defensible by construction.

## Run the helpers - do NOT read the inputs yourself (CRITICAL - read this before doing anything)

This skill builds the dashboard by **RUNNING the deterministic Python helpers through your shell tool**. It does **NOT** work by you reading or "looking at" the PDFs, spreadsheets or brochures and typing what you see. **Your FIRST action is always to run `helpers/run.py` through your shell**, and extraction is NATIVE in either environment - there is no "degraded" runtime to steer around:
- **Cowork is the primary environment: run the helpers with the sandbox shell** (`python helpers/...`). The sandbox already has **Pillow** (image harvesting) and the other Python deps; the one native library it lacks is **PyMuPDF**, so the skill **bundles a native PyMuPDF wheel** (`vendor/`) that `helpers/_vendor_wheels.py` loads automatically when the system package is absent - so the sandbox reads spec tables, areas, clear heights, rents and embedded photos at **full native fidelity, no MCP shell required**. (The old pdfplumber shim / placeholder is only a last resort, used only if the bundled wheel does not match the sandbox.)
- **A Windows host with the MCP shell is OPTIONAL:** run helpers with `mcp__shell__run_command` (ABSOLUTE path - see "Running the helpers"); it uses the host's system PyMuPDF. mcp__shell is no longer "required for PyMuPDF" - it was only ever the way to reach native PyMuPDF, which Cowork now has via the bundled wheel.
- **Coordinates + drive-times (geocode/OSRM) are the only step that still wants the network.** It is always the Cowork sandbox; the run PROBES which tools are present and uses the first available, in priority order: (1) **`mcp__shell`** if present (native, has outbound network - not Windows-only, it may be present in Cowork) runs the helpers so they hit the live APIs and bake the caches directly; (2) the **Playwright MCP** via a `data:` URL fetcher; (3) the **Claude Preview MCP** serving the full fetcher page; (4) the broker `web_enrich.html` chat handoff (see "Web enrichment (exit 8)"). `WebFetch` is NOT used for this - it cannot reach the geocode/route/Overpass APIs. Geocoding is mostly OFFLINE (the bundled ~19k-city gazetteer), so only REAL routed drive-times truly depend on this.

**This exact anti-pattern has happened and must not recur:** do NOT open, read, summarise, interpret or **vision-transcribe** the source files yourself **inline (in the orchestrator's own context)** to populate the dashboard. Brochure decks ARE structured by reading them - but that reading is done by an **ISOLATED interpretation sub-agent with fresh context** that `run.py` dispatches you to (exit 3 + a manifest), never by you typing what you see into `canonical.json`. The distinction is independence: an isolated author + the blind honesty gates preserve author != reviewer, whereas the orchestrator reading inputs inline bypasses the gates, the Source Ledger and the honesty checks (and **misreads dense spec tables**). **Interpretation is ONLY entered when `run.py` itself routes a deck to it (it exits 3 and writes `work/vision/manifest.json` with a per-deck `mode` - `text` to read the extracted text, `raster` to read page images)** - it is never a first resort and never a substitute for running the pipeline. If you have not yet run `run.py` via the shell, you are doing it wrong - run it first.

This is a **methodology with hard, independent gates**, not a loose script. The governing rule is the **Data Honesty Standard** (read `reference/evidence-standard.md` first): nothing reaches a card that does not trace to a source file, and every unknown is an explicit `"tbd"` (or `"—"`/`null`), never invented and never silently dropped.

Two non-negotiable design commitments (same as `cbre-il-account-briefing`):
- **Independent review (author != reviewer).** Every QA check that is a *judgement* about data the orchestrator produced runs in an isolated sub-agent with **fresh context, blind to the orchestrator's view**: the reviewer is handed only the artefact path (which it reads itself) and the gate rubric - never the orchestrator's conclusions, an expected answer, or a prior reviewer's note. The orchestrator runs deterministic scripts and adjudicates verdict files; it never writes a verdict and never self-certifies. The mandatory dispatch contract is in `reference/gates.md` ("Reviewer dispatch contract").
- **Shift-left.** The data is validated BEFORE the expensive image-embedding build, so "this rent is wrong / fabricated" is caught for the price of a JSON edit, not a rebuild.

## Driving the run - the loop (read this FIRST)

`run.py` IS the plan: it surveys the folder, prints a **`Plan:`** roadmap (what it found + which handoffs to expect), runs the deterministic spine, and tells you what to do next via its **exit code**. Your job is to follow this loop MECHANICALLY - not to improvise:

0. **Integrity:** `python helpers/preflight.py`. If it says the files didn't load correctly, restart the session (also signalled as exit 4), then continue.
1. **Run the spine ONCE:** `python helpers/run.py --folder <F> --work <W> --client <C> [--geocode --pois --osrm --regions] [--quiet]`. Read its `Plan:` line - that is your roadmap of what exists and which handoffs to expect.
2. **Read the EXIT CODE, do EXACTLY the one mapped action, then re-run the SAME command:**

| exit | meaning | the ONE sanctioned action |
|---|---|---|
| 0 | spine finished | run the agentic review steps below; `final_gate.py` must pass, then deliver |
| 2 | no usable inputs | check the folder / `project.yaml`, fix, re-run |
| 3 | a deck OR a tracker needs **interpretation** | dispatch the text/vision sub-agent per the manifest `mode` for each `deck`, AND the tracker-mapping sub-agent for each `kind:"tracker"` `job` PLUS a SEPARATE blind agent for each `kind:"tracker_verify"` job (`reference/interpretation.md`) -> re-run |
| 4 | skill files truncated | restart the session, then re-run |
| 5 | `validate-data` blocked | read `gate1_scorecard.md`, fix the flagged datum (a JSON/source fix), re-run |
| 6 | another **pre-build** gate blocked | read `gate1_scorecard.md`, fix the named gate, re-run |
| 7 | a **post-build** gate blocked | read the gate output, fix, re-run |
| 8 | **web enrichment** needed | deliver / auto-run `web_enrich.html`, drop the seeds back, re-run |
| 9 | **photo-match** needed | dispatch the match sub-agent -> `work/photo_map.json`, re-run |
| 10 | cross-source **match adjudication** needed | dispatch the match sub-agent -> `work/match_decisions.json` PLUS a SEPARATE blind verifier over `verify_pairs` -> `work/match_verify.json`, re-run |
| 11 | **dashboard-language fallback** needed (a SUPPORTED European Latin-script language that is not one of the bundled 12) | dispatch an ISOLATED translation sub-agent: translate the strings in `work/i18n/<code>_request.json` to the language (keep the keys, `{area}`/`{unit}`, the `&amp;`/glyph/CBRE/OSRM/BREEAM/etc. invariants; never translate DATA or the `tbd`/`—` sentinel; add `"_en_sha"`), save the flat `{key:value}` to `work/i18n/<code>.json`, blind-verify it as G-i18n, re-run. (Or `type nul > work/i18n/<code>.SKIP` for English.) See `reference/localisation.md`. |
| 12 | **free-text DATA translation** needed | dispatch an ISOLATED translation sub-agent: translate the `items` in `work/i18n/data_translate_request.json` to `output.language` (PROSE only; keep numbers/units/codes/names/dates verbatim), MERGE the `{text: translation}` map into the language-tagged cache `work/i18n/data_translations.<code>.json`, re-run. Blind-verify as G-lang. |

3. **Slow / killed / silent output / "it timed out"?** That is the ~45s sandbox shell cap, BY DESIGN - **just re-run the SAME command.** Re-running is RESUME: it continues from the work-dir cache, it does NOT restart, and every pass makes progress (watch the `PDF engine:` and `photo cache: X/Y` lines). A media-heavy run taking several passes is normal and expected - it converges.

**Forbidden moves (each of these was actually tried in a real run and is WRONG):**
- Do NOT hand-write or edit `canonical.json` / `built.html` - they are pipeline outputs; a hand-built one fails the gates anyway, so it is wasted effort.
- Do NOT monkey-patch, bypass, or "simplify" a helper, and do NOT skip image harvesting (there is no real "skip images" knob; `--image-budget-kb 0` does not do it).
- Do NOT read the source PDFs/sheets and type the data in yourself (the anti-pattern above).
- Do NOT invent or estimate any value (drive-times, areas, rents) - an unknown is `tbd`, never a guess.

When you feel the urge to improvise, the answer is almost always **re-run the same command** or **read `gate1_scorecard.md`** - never a workaround.

## Output discipline - quiet in Cowork (IMPORTANT)

These dashboards are run by brokers who neither read nor want the technical chatter; verbose output worries or distracts them. When running in Cowork (or any non-developer chat), keep the screen almost silent:

- **Show only four things:** (1) the Stage-0 setup form (ONE `visualize` `show_widget` elicitation with all five questions in one box — never `AskUserQuestion`, never one-at-a-time; see `reference/setup-form.md`); (2) ONE short plain-English step marker as each stage starts (e.g. "Reading the brochures…", "Building the dashboard…"); (3) anything that genuinely blocks and needs the broker to decide; (4) the final hand-off - the dashboard is ready and where it is, plus the Gaps Report if something needs chasing.
- **Suppress everything else:** no tool logs, no gate scorecards, no Python stdout, no per-property counts, no reasoning, no reassurance, no explaining what a gate is. Do not narrate beyond the one step marker.
- **Run the scripts quietly:** `python helpers/run.py … --quiet` prints only the step markers and swallows sub-step output; surface a script failure as ONE plain sentence (what's wrong + what you need from them), never a traceback or scorecard.
- **Step markers** are <=6 words, plain English, no stage numbers or jargon: "Scanning the folder", "Reading the brochures", "Organising the options", "Adding maps and extras", "Checking the data", "Building the dashboard", "Final checks", "Done - dashboard ready".
- **Only break silence when absolutely necessary.** If unsure whether something needs saying, it does not.
- **The drive-time fetch is automated whenever the network-capable tools are present** (see "Web enrichment (exit 8)"): it is always the Cowork sandbox, and the run PROBES which tools are present and uses the first available - (1) **`mcp__shell`** if present (native, has outbound network) runs the helpers directly against the live APIs, no page; (2) the **Playwright MCP** via a `data:` URL fetcher; (3) the **Claude Preview MCP** serving the full fetcher page (let the Preview MCP own the server via the `launch.json` the run writes - a server you start from the sandbox shell is in a different network namespace and is unreachable by the browser, which is the real cause of the "127.0.0.1 unreachable" dead-end, not a missing renderer). Either way the run stays silent like any other stage. **Whenever none of those tools is present, the automated fetch cannot reach the map services, OR the fetch fails for any reason**, fall back to the "open this page, drop the file back" chat handoff: the page (`web_enrich.html`) is ALWAYS written by the run, so deliver it to the broker - this is the universal fallback and is NEVER skipped and NEVER replaced by an error or by straight-line estimates. (`WebFetch` is not a path - it cannot reach the geocode/route/Overpass API hosts.)
- This governs the on-screen chat ONLY. The extraction agents, gates, freeze, and the isolated reviewers all still run in full and still write their verdict/scorecard/ledger files to the work dir for audit - they are simply not narrated.

## Architecture in one paragraph

The reference HTML is **byte-stable "chrome" plus exactly three data blocks** (`const PROPS`, `const POIS`, `const REGIONS`). ~99% of its size is base64 images inside `PROPS`. So the skill never regenerates the HTML; it extracts inputs into a canonical JSON dataset and **injects three blocks into a frozen, versioned template** (`assets/dashboard_template.html`). The chrome cannot drift: `gate_runner.py validate-html` re-runs the injection and asserts the delivered file is byte-identical to `render(canonical)`. Read `reference/template-contract.md`.

## What this produces

Four deliverables in `deliverables/`:
1. **`CBRE_Property_Dashboard_<Client>.html`** - the dashboard, in the CBRE reference style. Each card and
   detail modal carries a PHOTO CAROUSEL: ALL of a property's photos (best-first, capped at
   `images.GALLERY_MAX`, page-scoped so a multi-property deck never shows a neighbour's photo), navigated
   MANUALLY (prev/next, no autoplay); the Site Plan toggle stays in the modal. The warehouse-area filter
   slider is DATA-DRIVEN (bounds + step from the actual area range, labelled in the dataset's own unit, so
   it works in sq ft as well as sq m); warehouse rent is shown as a per-area rate (annual AND monthly) and,
   in the modal and compare table, the TOTAL annual and monthly rent (GLA x rate, split across warehouse +
   office when their rents differ, otherwise the single rate over total GLA; kept in its own currency, no FX);
   and when the dataset has ONE country the redundant 'Countries'
   KPI tile is dropped and the 'Regions' tile widens and lists the regions by name.
2. **`<Client>_Source_Ledger.xlsx`** - every property field mapped to the source file + locator it came from.
3. **`<Client>_Gaps_Report.md`** - every `"tbd"`, unmatched asset, conflict and enrichment gap, each with a "how to close it" note.
4. **`<Client>_Longlist.xlsx`** - a flat data view: one property per ROW, variables in COLUMNS (the broker-facing
   table), sitting alongside the field-level Source Ledger. Falls back to CSV if openpyxl is unavailable.

The single source of truth is `canonical.json` (`{meta, properties[], pois[], regions{}}`), schema in `templates/canonical.schema.json`.

## Install (teammates)

Drop the `cbre-property-longlist/` folder into `~/.claude/skills/` (Windows: `C:\Users\<you>\.claude\skills\`); it triggers on the phrases in the description. **One-time per user (each colleague runs it on their own machine):** `python helpers/setup_permissions.py --yes` does two things in your user `settings.json`: (a) pre-approves the skill's four FIXED fetch domains (ORS/OSRM/Nominatim/Overpass) so runs never stop for per-fetch permission clicks; and (b) installs a **PreToolUse shell-guard hook** (`helpers/shell_guard_hook.py`, shipped with the skill) that blocks the sandboxed bash (`mcp__workspace__bash`) from running the skill's helpers and redirects them to `mcp__shell__run_command` - keeping THAT host on its native system PyMuPDF rather than the shim. **This is an OPTIONAL Windows-MCP-host hardening only: Cowork (the primary environment) needs neither `setup_permissions.py` nor the hook** - extraction in Cowork is already native via the bundled `vendor/` PyMuPDF wheel, so on Cowork this whole one-time step is simply skipped (the shell-guard hook only applies on a Windows host, where the Linux wheels cannot load). The automated exit-8 drive-time fetch uses whichever network-capable tool is present - `mcp__shell` (if present), the Playwright MCP, or the Claude Preview MCP - so it benefits from those MCPs being installed, but always falls back to the chat handoff if none is. Restart the session once after (hooks load at session start). Get a free openrouteservice key (trucking drive-times) and set it as the `ORS_API_KEY` env var - personal per user, never shared inside the skill. Python deps: `pypdf`, `python-pptx`, `openpyxl`, `Pillow`, `rapidfuzz`, `jsonschema`, `PyYAML`, `requests`, plus a PDF engine - `PyMuPDF` (fitz) preferred, otherwise `pypdfium2` + `pdfplumber`, which `helpers/fitz_shim.py` falls back to automatically when PyMuPDF cannot be installed (e.g. a locked-down sandbox with no pip/network) - though the skill now **bundles a native PyMuPDF wheel** (`vendor/`) that loads automatically in the matching Cowork sandbox (Pillow already ships with the sandbox), so the shim/placeholder is only a last resort (see "No network / no pip needed"). Optional: `pillow-heif` (HEIC images; degrades silently if absent), `extract-msg` (only the `.msg` email fallback), `playwright` (only `render_qa.py`'s headless screenshots), and **LibreOffice** (headless `soffice` - the only reliable PPTX slide renderer: with it, vision rasterisation and slide heroes cover vector/text-only slides too; without it both degrade to the slides' embedded pictures). Nothing client-specific is baked in - every run reads a per-project `project.yaml` in the working folder.

### For Cowork / non-technical users

Nothing technical to learn. Put all your property files - agent and landlord emails, availability spreadsheets, brochures, photos - into one folder, then ask for the longlist (e.g. "build the property longlist for this folder"). Two things will happen along the way:

- **Two quick setup questions first.** You are asked which extras to add (drive-time maps, a workforce snapshot, logistics landmarks) and whether to also pull details from your Outlook emails. Pick what you want - there is no wrong answer, and you are only asked once per project.
- **You may be handed a small web page.** If you are sent a file called `web_enrich.html`, open it in your own browser, click "Fetch all", wait for it to finish, then drop the downloaded `web_seeds.json` file back into the chat. This is how real drive-times and map data are pulled when the office network blocks them - a home or hotspot connection works if the office one does not. It happens at most once.

When it finishes you get your **dashboard** (a single ready-to-share file) and a **Gaps Report** listing anything that could not be confirmed, so you know exactly what to chase (a Source Ledger that traces every figure to its file is saved alongside them for audit). Nothing is ever invented - if a figure is not in your files it is shown as missing, not guessed.

## Quick start (the deterministic spine)

**Running the helpers - which shell (READ FIRST).** Run the helpers through a shell (never read the
inputs yourself - see the CRITICAL note at the top); extraction is native in either case.
**Cowork (the primary path) is the second bullet below**; the sandbox shell is the default. `mcp__shell`
is OPTIONAL for extraction (the bundled wheel already gives native PyMuPDF) but, when present, it is the
PREFERRED tier for the exit-8 drive-time fetch (native, has outbound network - see "Web enrichment (exit
8)"). It is NOT Windows-only: probe for it and use it when present, whether on a Windows host or in Cowork.
- **`mcp__shell__run_command` when present (OPTIONAL for extraction - native system PyMuPDF).** Run every
  helper with `mcp__shell__run_command`, and because that tool has **no persistent working
  directory**, pass
  the **ABSOLUTE path** to the script (relative paths fail). The helpers live beside this SKILL.md,
  in this skill's `helpers/` folder - on Windows that is
  `C:\Users\<you>\.claude\skills\cbre-property-longlist\helpers\` (substitute your own user folder;
  do not hardcode someone else's). Example:
  ```
  mcp__shell__run_command: python "C:\Users\<you>\.claude\skills\cbre-property-longlist\helpers\run.py" --folder "<inputs>" --work "<work>" --client "<Name>" --geocode --pois
  ```
  On this path **PyMuPDF is installed natively**, so `fitz_shim` never fires and there is no 45s
  shell cap - the speed-cliff and shim caveats below simply do not apply. Every `python helpers/...`
  command in this doc means "run that helper by its absolute path via `mcp__shell__run_command`".
  - **Output + shell behaviour (READ - this avoids a large, common time sink).** On many hosts
    `mcp__shell__run_command` runs the command as a **direct process, not through a shell**: a real
    executable (`python`, `node`) returns its stdout to you normally - even thousands of lines - but
    shell **built-ins** (`echo`, `cd`, `dir`, `del`), **operators** (`&&`, `||`, `;`, `|`) and
    **redirection** (`>`) produce EMPTY output and silently do nothing. So **call each helper
    directly, one `python "<abs path>" ...` command per call** - its stdout (the gate scorecards,
    the step markers, any error) comes straight back. Do **NOT** chain helpers with `&&`, and do
    **NOT** write a helper's output to a file and read it back through another tool: the output is
    already returned to you; the file-bounce is pure wasted round-trips. If you genuinely need a
    shell feature (a redirect, a real chain), wrap the WHOLE command in `cmd /c "..."` (e.g.
    `cmd /c "python ... > out.txt 2>&1"`) - that restores built-ins, chaining and output together.
    One-time check on an unfamiliar host: if `echo hi` returns nothing but `cmd /c echo hi` returns
    `hi`, you are on a direct-executor shell - follow this rule.
- **Cowork / the sandbox (the PRIMARY path).** Run the helpers with the sandbox shell from the skill
  directory (`python helpers/...`); `mcp__shell` is not needed for extraction (but if it IS present here,
  it is the preferred tier for the exit-8 drive-time fetch - probe for it). Pillow ships with the sandbox;
  the bundled `vendor/` PyMuPDF wheel (loaded by `_vendor_wheels` when the system lacks PyMuPDF) gives
  NATIVE PDF extraction, so it is full-fidelity - the pdfplumber shim / placeholder is only a last
  resort if the wheel does not match the sandbox. The ~45s cap + resume (below) keep a capped run alive.

**Step 0 - preflight (always, especially in a sandbox/Cowork session).** Sandboxed
runtimes copy the skill in each session and a partial/flaky mount can deliver a
**truncated** helper. Run this FIRST:

```
python helpers/preflight.py
```

If it prints `OK skill integrity verified`, proceed. If it prints **"The skill
files didn't load correctly. Please restart the session and try again."** (or it
errors / won't run), tell the user exactly that - **restart the session and re-ask**;
do not try to debug Python. (`run.py` also runs this check internally and stops with
the same plain sentence rather than an opaque mid-file `SyntaxError`. A file that was
merely EDITED since the manifest was built is an advisory note only, never a restart -
restarting cannot fix a stale manifest.) **Regenerating the manifest is a step for whoever
EDITS the skill (a maintenance / CI task), NOT part of a normal run** - a broker run never edits
helpers and must never call `make_integrity`. After editing any helper/template, regenerate
the manifest with `python helpers/make_integrity.py` and run the evals:
`python evals/extract_test.py`, `python evals/fixture_test.py` (offline end-to-end:
merge/gates/build/final-gate must agree first try) and `python evals/smoke_test.py` (template round-trip).

**No network / no pip needed.** Every third-party dependency degrades to a bundled
shim automatically: `PyMuPDF`->`fitz_shim` (pypdfium2 + pdfplumber; if even
pypdfium2 is absent, a pdfplumber-ONLY tier still extracts text and embedded
JPEG photos - only page rendering is lost, and the hero pipeline degrades
gracefully through its tiers) and `rapidfuzz`->`rapidfuzz_shim` (stdlib
difflib). `Pillow` has no shim (with no decoder there is no image to harvest), so
if it is absent the whole hero pipeline degrades to the pre-baked placeholder
(`assets/placeholder.uri`) and the run prints one honest note that every option
shows a placeholder; the data, map and filters are unaffected. A blocked pip
never stops a run.

**Bundled native wheel (sandbox accelerator).** Because the shim/placeholder degradations
above hurt extraction quality, the skill ships a native **PyMuPDF** wheel under `vendor/` -
the one native library the Cowork sandbox lacks (Pillow and the other Python deps are already
present there, so no Pillow wheel ships; that also keeps the skill under the org upload-size
cap). `helpers/_vendor_wheels.py` unpacks and uses it automatically when the system package is
absent - no pip, no network: it checks the package is importable first (a strict NO-OP
otherwise, so native installs and the shim tests are untouched), then unpacks the matching
wheel ONCE to a temp cache and prepends it to `sys.path`. The wheel is **platform-locked** (it
targets the Cowork sandbox: Linux x86_64, CPython 3.10; PyMuPDF needs glibc >= 2.28): on any
non-matching interpreter `_vendor_wheels` rejects it and the skill degrades exactly as before
(fitz_shim / placeholder). The wheel is intentionally NOT in the integrity manifest (a
corrupt/truncated wheel simply fails to load -> graceful shim fallback, never a crash). To
refresh/retarget, drop the matching manylinux PyMuPDF wheel into `vendor/`; fitz binds via
`fitz_shim` becoming real PyMuPDF. (If a future sandbox also lacks Pillow, a matching Pillow
wheel dropped here is picked up the same way via the `images.py`/`contact_sheet.py` import
fallbacks - but mind the upload-size cap.)

**Sandbox offline (e.g. Cowork) - what your web tools CAN and CANNOT do:** the Python
helpers may have no outbound network (Nominatim/Overpass/OSRM unreachable). Your `WebFetch`/
`WebSearch` tools reach **general web PAGES** (so region-research prose - reading a statistics
page - is fine to do with them and hand to the helpers via `<work>/regions_cache.json`), but
they do **NOT** reach the structured geocoding/routing/POI **API** endpoints
(Nominatim/Overpass/OSRM/ORS): those return query-shaped JSON that `WebFetch` cannot fetch in
this environment. So do NOT try to WebFetch geocode/route/Overpass URLs - that path is dead
here; those go through the exit-8 fetch (run directly by `mcp__shell` if present, else the
**fetcher page** via a browser MCP or the broker's own browser - see "Web enrichment (exit 8)").
Most of the data needs no network at all:
- **Geocode needs NO network for European cities:** `assets/cities_dataset.json.gz` bundles a
  ~19k-city European gazetteer (GeoNames, name + country + real coordinates), so
  `enrich.py --geocode` resolves the map coordinates AND fills an unknown country fully
  OFFLINE - the exit-8 round-trip is reserved strictly for live ROUTING. A city the
  gazetteer does not carry (rare) is geocoded by the exit-8 **fetcher page itself** (it
  self-chains geocode -> route targets -> routes in one pass), so an unresolved city rides the
  same browser-MCP / chat handoff as the drive-times - never a `WebFetch` to Nominatim (that
  API is unreachable from `WebFetch` here). On an ONLINE host where Python itself can reach the
  web you can instead `python helpers/seed_geocode.py coords.json --cache-dir <work>` from a
  real geocoder result. Org maintenance: download a fresh GeoNames cities dump, `python
  helpers/build_cities_dataset.py <cities.txt>`, then `helpers/make_integrity.py`.
- **Region workforce:** write `<work>/regions_cache.json` from your web research.
- **POIs need NO network at all:** `assets/poi_dataset.json.gz` bundles COMPLETE
  datasets (all scheduled airports worldwide via OurAirports, all ports, all
  SGKV intermodal terminals - ~6,900 facilities), so the genuine nearest
  air/port/rail is a pure offline computation ("nearest of a complete set" IS the
  genuine nearest); borders/cities come from the curated library. Org maintenance:
  drop updated exports in a folder, `python helpers/build_poi_dataset.py <folder>`,
  then `helpers/make_integrity.py`.
- **Drive-times/geocodes (`helpers/web_enrich.py`):** REAL routed trucking times
  still need the web. When requested and the sandbox network is dead, `run.py`
  exits **8** and writes `<work>/web_enrich.html` - a self-contained fetcher page -
  AND a `<work>/.claude/launch.json` serving the work dir (so the Preview MCP can run it).
  **The fetch is automated by whichever network-capable tool is present** - it is
  always the Cowork sandbox, so PROBE and use the first available: (1) **`mcp__shell`**
  if present (native, has outbound network) runs the helpers directly against the live
  APIs, no page; (2) the **Playwright MCP** via a `data:` URL fetcher; (3) the **Claude
  Preview MCP** serving the full fetcher page - see the "Web enrichment (exit 8)"
  agentic step. The chat delivery described next is the **UNIVERSAL fallback** (used
  whenever none of those tools is present, the automated fetch cannot reach OSM/ORS,
  OR an attempted fetch failed - never let exit 8 end in an error or a skipped
  enrichment): you
  **DELIVER THE FILE TO THE USER IN THE CHAT** (attach it; org users never see a
  work folder). They open it in their own browser (throttled, retrying,
  full-fidelity; office proxy blocks it? home/hotspot works), click "Fetch all",
  and **drop the downloaded `web_seeds.json` back into the chat**; save that
  upload into the work dir, run `python helpers/web_enrich.py ingest --work
  <work>`, re-run. ONE round total, always: the page SELF-CHAINS - it geocodes the
  unresolved cities itself, derives the route targets from the embedded POI
  dataset (same data + caps as the build), then fetches the routes; the seeds
  bundle is self-describing, so ingest needs no second pass. (`<work>/web_requests.json`
  is the request list the fetcher PAGE executes; it is not a `WebFetch` to-do list -
  `WebFetch` cannot reach those API hosts here.)
  **The handoff is STANDALONE - it never depends on run.py.** If you are driving
  the helpers directly (e.g. working around a shell cap) and the route server is
  unreachable, run `python helpers/web_enrich.py plan <work>/canonical.json
  --work <work> --osrm [--pois --geocode]` yourself (it reads `ORS_API_KEY`
  from the environment automatically for trucking drive-times, or pass
  `--ors-key <key>` explicitly): it writes the same
  `web_enrich.html` to deliver in the chat; `ingest` + re-running `enrich.py`
  then bakes the real drive-times. Never ship straight-line estimates because
  the orchestrated path did not fire.

Then run the spine. On an MCP host this is a `mcp__shell__run_command` call with the ABSOLUTE path
(this is the command that does the extraction - run it, do not read the inputs yourself):

```
mcp__shell__run_command: python "C:\Users\<you>\.claude\skills\cbre-property-longlist\helpers\run.py" --folder "<inputs folder>" --work "<work dir>" --client "<Name>" --geocode --pois
```

(In Cowork, the same command via the sandbox bash: `python helpers/run.py --folder "<inputs folder>" --work "<work dir>" --client "<Name>" --geocode --pois`.)

`run.py` runs the deterministic Stages 0-7: intake -> extract (PDF for fields, PPTX for images, XLSX trackers) -> merge -> enrich -> pre-build gates (self-check, validate-data, coverage, **trace-coverage**, images, enrichment, ledger validate - all in `gate1_scorecard.md`; it **stops before build if ANY pre-build gate blocks** (exit 5 = validate-data, 6 = another gate), **stops before deliver if a post-build gate blocks** (exit 7), and **freezes `canonical.json` automatically** when the scorecard is ALL-PASS so the review window needs no manual freeze step) -> build -> post-build gates -> deliver. Output is byte-deterministic (same inputs -> identical `built.html`). Then run the **agentic steps** below - they are not optional for a client-facing deliverable: `final_gate.py` BLOCKS unless every judgement verdict file (the four core gates, plus G-enrich whenever regions were enriched) exists and carries a parseable non-blocking verdict - green or amber pass (amber = ship with notes), red/missing/garbled block (or pass `--no-reviews` to ship an acknowledged DEGRADED build). Re-running is safe and idempotent.

**Resume is the DEFAULT** (pass `--no-resume` to recompute everything): any deterministic stage whose output is already current is skipped - intake, per-file extract, merge, enrich (gated by a content-hash stamp + the chosen flags), and build. A run killed mid-way (Cowork's ~45s shell cap makes this routine) or interrupted for a vision pass re-runs from where it stopped instead of re-extracting and re-embedding every base64 photo from scratch; the canonical and cache writes are atomic, so a kill mid-write can never wedge the resume. **The gates and the freeze are never skipped** - `validate-data`/`validate-html`/`reconcile` re-run every time and re-assert byte-identity, so a resumed build can never ship something unverified. A changed input (newer mtime / different bytes) invalidates its stage and everything downstream automatically. Caches (geocode/POI/OSRM/region + the hero-image cache) live in the work dir and stay warm across runs.

**Image harvest is PRE-WARMED in parallel (the merge bottleneck).** Rasterising + compressing brochure pages for the heroes/galleries is the slow part of merge - it can sit silent for 40-90s and overrun the ~45s shell cap. Before merge, `run.py` runs a bounded, CPU-parallel pass (`merge.prewarm_images`) that fills the per-page image cache up front, so merge then runs as cache hits and finishes inside one window. Every unit is cached ATOMICALLY and per-page (heroes, the gallery scan, and the pdfplumber geometry are all resumable mid-deck), so a capped/killed run never restarts a deck from scratch - it converges. On a media-heavy run the printed `photo cache: X/Y images ready` line tracks progress; if it is not complete, just re-run the same command to warm the rest. Knobs: `CBRE_IMAGE_WORKERS` (default `min(cores, 8)`; `1` forces serial, no process pool) and `CBRE_PREWARM_SECONDS` (default `30`). The pre-warm only POPULATES the same cache merge reads, so the built dashboard is byte-identical whether it ran or not.

## The pipeline - eight stages

Full detail in `reference/pipeline.md`. The orchestrator (you) owns `canonical.json`, runs the scripts, and dispatches isolated sub-agents for the judgement gates and the agentic inputs.

- **0 Intake** (`intake.py`): discover inputs, infer city clusters, scaffold/confirm `project.yaml`. Halt if no property sources. **Before confirming `project.yaml`, refine any ambiguous filename->city clusters (see below), then ask the broker two plain-language questions: (1) which enrichment extras to add, and (2) whether to also pull property details from emails - their Outlook, a saved-email folder, or not at all.**
- **1 Extract.** Brochure decks (PDF/PPTX) are structured by an **isolated interpretation sub-agent**, NOT by a label dictionary: `run.py` (via `interpret_prep.py`) decides each deck's `mode` - **`text`** (the deck has a usable text layer, so the sub-agent reads the extracted text - cheap + accurate) or **`raster`** (the text layer is garbled/absent, so it reads page images, today's vision path) - writes `work/vision/manifest.json` with that per-deck mode, and **always exits 3 - also on a mixed run** (nothing is built until the interpreted records are in; records from other sources are cached). Dispatch the interpretation sub-agent (`reference/interpretation.md`) to write `work/extract/<region>_vision.json`, then re-run the same command - it resumes at merge. **xlsx trackers (`extract_xlsx.py`), images (`extract_image.py`) and emails (Outlook MCP) stay on their deterministic extractors** - they are structured and reliable (see `reference/data-engine.md`); each emits candidate records + ledger rows, unknowns `"tbd"`, never guessed. (`extract_pdf.py` is retained as a text-quality signal but is no longer the brochure record source.)
- **2 Match & merge** (`match.py`, `merge.py`): dedupe cross-source by city+developer+park (never within one brochure) - the confident (auto) and impossible (forbidden) pairs are deterministic, the GREY-zone ambiguous cross-source pairs are adjudicated by an isolated sub-agent (`run.py` exits 10 -> `work/match_candidates.json` -> `work/match_decisions.json` -> re-run; the deterministic matcher is the offline fallback and the hard blocker) - then merge by precedence (newest email wins commercials; brochure wins specs), assign ids, embed compressed base64 photos, write `canonical.json` + `source_ledger.csv`.
- **3 Enrich** (`enrich.py`, opt-in): `--geocode` (map coordinates), `--pois` (ports/rail/air/borders), `--osrm` (drive-time rings), `--regions` (workforce profiles via a research sub-agent). Degrades gracefully; never fabricates.
- **4 PRE-BUILD GATE** (BLOCKING): mechanical `gate_runner.py self-check|validate-data|coverage|trace-coverage|images|enrichment` + `ledger.py validate` (all in `gate1_scorecard.md`); then judgement reviewers **G-honesty + G-trace (Opus), G-images (Sonnet, via one `contact_sheet.py` montage of all photos), and G-enrich (Sonnet, only when workforce/regions were enriched)** dispatched **in parallel** against the **frozen** `canonical.json` (`run.py` freezes automatically at ALL-PASS; `freeze --check` after collecting verdicts). Proceed only at `STATUS: ALL-PASS`. The `enrichment` gate catches an unsourced or undated figure and empty POIs/distances; identical cross-region figures are an advisory note for G-enrich (real statistics can collide - a block on true data would force falsifying it).
- **5 Build** (`build_dashboard.py`): inject three blocks into the frozen template; nothing added.
- **6 POST-BUILD GATE** (BLOCKING): `gate_runner.py validate-html|reconcile` + **G-visual** (`render_qa.py` + isolated reviewer; `reference/visual-qa.md`). If Playwright is absent, `render_qa.py` prints `STATUS: NEEDS-PREVIEW-MCP` - drive G-visual via the **Claude Preview MCP** (don't skip it); only mark DEGRADED if neither Playwright nor the Preview MCP is available.
- **7 Deliver** (`deliver.py`, `final_gate.py`): export the ledger, write the Gaps Report, assemble; do not declare done while any line is red.

**Toolkit update check (quick, silent unless you're behind).** Run `python helpers/version_check.py` once at the start of a run. It prints a one-line note to stderr *only* if a newer CBRE I&L Toolkit version has been published; it does nothing but a single public version lookup, never blocks the run, and is safe to ignore otherwise. (This is just an update nudge - it does NOT replace running `helpers/run.py` as your first build action.)

## The broker setup prompt (ONE consolidated form, at Stage 0)

**First, refine ambiguous filename clusters (an orchestrator action, BEFORE you confirm `project.yaml`).** `intake.py` clusters each brochure by filename and flags each cluster's `confidence` in `inventory.json`: a `low` cluster is one the regex could not split cleanly (no ` - ` separator and the unspaced-dash tail is not a known city, e.g. `Options-Oporto`). Read `inventory.json`; for the `confidence:"low"` clusters ONLY, judge the likely city/region from the filename `stems` (e.g. `Options-Oporto` -> `Oporto`, `Naves Cataluna` -> `Cataluna`) in ONE batched judgement, and write `work/intake_clusters.json` `{"input_hash": <copied verbatim from inventory.json>, "schema_version": 1, "labels": [{"stem": "Options-Oporto", "region": "Oporto", "country": "PT"}, ...]}` (`country` is an optional ISO-2 hint; leave it blank if unsure - `--geocode` resolves country from coordinates regardless). Then re-run the spine: the resume guard re-clusters from the cache and `intake.py` merges the corrected `region -> country` into `project.yaml inputs.clusters`, so the broker confirms a better-clustered config with fewer corrections. **Determinism + offline fallback:** the decision lives in the input-hashed cache (a changed brochure set invalidates it), so a re-run is byte-identical, and when `work/intake_clusters.json` is absent (a non-interactive / offline run) the deterministic regex stands. This sets ONLY `inputs.clusters` (a routing/scaffold label + the `market.countries` seed) - the card's displayed region/city stay brochure-derived, so a wrong cluster label can never fabricate a displayed field (the coverage gate blocks a hallucinated region that maps zero brochures, and the broker confirms `project.yaml`).

Present **ONE consolidated setup form as a single `visualize` widget** — render it with `mcp__visualize__show_widget`, passing the `<form class="elicit">` elicitation form in **`reference/setup-form.md`** as `widget_code` (call `mcp__visualize__read_me` with `modules:["elicitation"]` once first; substitute the inferred client name). It shows **ALL FIVE questions below AT ONCE, in that ONE box**, and the broker submits everything together in a single click. **Do NOT use `AskUserQuestion`, and NEVER split any question into a single-question / one-at-a-time flow or a follow-up** — the client-name confirmation AND the openrouteservice key are FIELDS IN THIS SAME WIDGET, so the broker answers once and the run proceeds with zero further setup prompts. On submit the answers arrive as one chat line (`Property longlist details — Client: … · Extras: … · Ors key: … · Emails: … · Language: …`); parse it and persist every answer in `project.yaml` (mapping below) so re-runs are non-interactive. SKIP the whole widget only when `project.yaml` already carries the answers. **FALLBACK — only if the `visualize` tool is genuinely unavailable in this environment** — present all five in ONE consolidated plain-text message (a single elicitation), still never one question at a time.

**1 - Client name (confirm up front - it names every deliverable):**
> What should I call the client on the dashboard and file names?
> - offer the name inferred from the inputs folder / `project.yaml` `client:` as the options (e.g. `TEDi Spain` / `TEDi`), plus **Other** (free text).

This sets `CBRE_Property_Dashboard_<Client>.html`, `<Client>_Source_Ledger.xlsx`, `<Client>_Gaps_Report.md`, `<Client>_Longlist.xlsx` - so it MUST be settled in this form, never asked afterwards.

**2 - extras (enrichment):**
> Your dashboard already includes every option, its photos, filters, comparison and a map. Want me to add any of these extras? (each adds a little time)
> - **Drive-time maps** - how long it takes a *truck* (HGV) to reach key ports, airports, motorways and borders from each site
> - **Workforce snapshot** - labour availability, logistics employment and unemployment per region, with sources
> - **Logistics landmarks** - nearby ports, rail terminals, airports and border crossings on the map

**3 - truck-routing key (openrouteservice) - a FREE-TEXT FIELD IN THIS SAME FORM, never a follow-up:**
> If drive-time maps are on, got a free openrouteservice API key for real HGV routing? (Skip for car-based times instead)
> - a text field: "Paste ORS key, or leave blank".

HGV/truck drive-time is the metric an I&L brief lives on; without a key routing silently falls back to CAR. This field ALWAYS sits in the setup form (relevant when Drive-time maps is picked; harmless when left blank) - it is **NEVER asked as a separate follow-up.** Leave blank = accept car times (a Gaps-Report line names the car-vs-truck downgrade); a teammate can also paste a key into the `web_enrich.html` page later (used only from their browser, never re-entering the chat). OMIT the field only when a key is already in `project.yaml enrichment.ors_api_key` / the `ORS_API_KEY` env var. Persist a pasted key to `project.yaml enrichment.ors_api_key` so both `enrich.py` and the `web_enrich.html` fetcher route HGV from the start.

**4 - emails (an Outlook mail folder, not a Windows folder):**
> Should I also pull property details from your Outlook emails (landlord/agent offers)?
> - **Yes - a specific Outlook folder** - name the mail folder (e.g. "Inbox", or one you filed offers in like "Normal CEE") and I'll search just that
> - **Yes - across all of Outlook** - search every folder, filtered by client / subject / date
> - **No** - skip emails

**5 - language:**
> What language should the dashboard chrome be written in? (Property data stays as sourced)
> - **English** (default)
> - **Any European Latin-script language** - name it. 12 are bundled and render instantly (German, French, Spanish, Italian, Dutch, Polish, Portuguese, Czech, Slovak, Hungarian, Romanian); any other (Danish, Swedish, Norwegian, Finnish, Croatian, Catalan, ...) is translated once in Cowork on the first run and then cached.

Record the answers in `project.yaml`: the client under `client:`, the language under `output.language` (an English name, an endonym or an ISO code all work; blank or English means English), the extras under `enrichment:`, the email scope under `inputs.emails:`, and any pasted key under `enrichment.ors_api_key` (`reference/config.md`). **Any European Latin-script language works:** the bundled 12 are instant; any other SUPPORTED one triggers a single translate round in Cowork (exit 11 - see the exit table and `reference/localisation.md`) and is cached for every later run. A genuinely unsupported / non-Latin value renders cleanly in English (never a blank or a raw key). The builder resolves the language at render time with a per-key fall-back to English; numbers and country names follow the language's regional convention; the DATA is never translated.

Map the extras to `enrich.py` flags; map the email answer to Stage-1 ingestion via an isolated `outlook_email_search` sub-agent (`reference/data-engine.md`): pass **`folderName`** = the named Outlook mail folder (the tool resolves Inbox/Sent/Archive directly and looks up any other folder name by enumerating the mailbox; add `mailboxOwnerEmail` for a shared/delegated mailbox), plus a `query`/date scope. "Across all of Outlook" omits `folderName`. (A Windows folder of saved `.msg`/`.eml` via `extract_email.py` exists only as a fallback for teammates without the Outlook MCP.)

## Agentic steps the orchestrator runs around the spine

- **Emails (Outlook MCP):** dispatch an isolated sub-agent that calls `outlook_email_search` (client/subject/date from `project.yaml`), reads offers, writes records in the schema of `templates/record_schema.json`, and re-routes attachments through the brochure/image extractors. **Map links belong to the deterministic resolver, not the model:** when an offer carries a Google/Apple/OSM maps link or a bare `lat,lng` pair (landlords paste these constantly), copy that raw string VERBATIM into the record's `__meta.map_candidates` (a list of strings) and do NOT set `lat`/`lng`/`mapLink` yourself - the shared resolver (`extract_pdf.backfill_link_coords`) parses it post-merge, so a first-party pin beats the town-centre geocode and no coordinate is ever model-invented. Falls back to a `.msg`/`.eml` folder (`extract_email.py`) when the MCP is absent - the fallback lists attachment names only and does not yet save or re-route their bytes (full byte-routing stays on the Outlook MCP path).
- **Brochure interpretation (text or raster):** when `run.py` writes `work/vision/manifest.json` (and exits 3), dispatch an isolated interpretation sub-agent. Each deck carries a `mode`: for **`text`** decks it reads the page `text` from the manifest and structures records (provenance `(text interpretation)`); for **`raster`** decks it reads each page image (provenance `(vision transcription)`, the historical vision path). Either way it writes `work/extract/<region>_vision.json` (schema `templates/record_schema.json`) - rents annual, honest `tbd` for unreadable fields, never invented, `__meta.page_no` copied VERBATIM from the manifest; a garbled text deck sets `needs_raster` so it escalates on re-run. Then re-run the spine. Full contract: `reference/interpretation.md` (raster-mode detail in `reference/vision-fallback.md`). **First check the `PDF engine:` line run.py prints at startup:** if it says `native PyMuPDF …`, the mode the manifest chose is right (a raster deck is genuinely image/vector-only). If it says `fitz_shim fallback (…)`, the bundled `vendor/` PyMuPDF wheel did NOT load (the line prints why - e.g. arch/glibc/interpreter mismatch); a whole run cascading to raster then is a wheel problem to FIX, not to paper over by transcribing images - text-based brochures the shim mis-parses would have read natively as `text`.
- **Tracker mapping (exit 3 - the `jobs` array of `work/vision/manifest.json`):** when `run.py` writes a `kind:"tracker"` job (alongside any brochure `decks`), an xlsx/CSV tracker's column->field mapping is being OFFERED to an isolated sub-agent. Dispatch it given ONLY the job's `sheets` (raw `headers` + a few `sample_rows`). It returns a **MAP, never records** - which raw column means which canonical field, plus each size/rent column's `basis`/`areaUnit`/`currency`/`perArea`/`period` hint - written to the job's `output` as `{input_hash, schema_version, map:{columns:[...], notes}}` (copy `input_hash` verbatim). It NEVER reads a cell value; Python parses every number with the same arithmetic. The deterministic dictionary already extracted the tracker, so this is a quality UPGRADE for a thin parse: the NEGATIVE table still vetoes a derived/penalty column, the dictionary backfills any column left `null`, validate-data + the rent band verify the named basis, and a thinner-than-dictionary map stays LOUD in the yield report. To decline the LLM map and keep the dictionary (a no-LLM / offline run), create an empty `.SKIP` file at the output path. Re-run the spine. Full contract: `reference/interpretation.md` "Tracker mode". **Independent verifier (same manifest):** the manifest ALSO carries a sibling `kind:"tracker_verify"` job per tracker - dispatch a SEPARATE fresh agent (CONCURRENTLY with the `tracker` job, never shown its map) to re-derive the SAME map blind into the `*_mapcheck.json` output. `run.py` diffs the two maps in pure Python and surfaces any field/basis disagreement to the Gaps Report (ADVISORY - the first map still drives the parse). So the highest-risk MAPPING/BASIS judgement is checked by something that did not make it, not just by the same-model reviewers.
- **Photo match (exit 9 - brochures that are photos for known properties):** when `run.py` exits 9 and writes `work/photo_match_manifest.json`, some brochures yielded no text but the run already holds the property data from another source (a tracker, emails, other decks), so each brochure is most likely a PHOTO for a known property, not a new property. **Dispatch an isolated sub-agent** that matches each brochure to a property by MEANING - reading the filename against the property names/addresses, like a human, NEVER by rigid rules (filenames are wild and vary per client). It writes `work/photo_map.json`: `{"confident":[{"brochure","property_key"}], "uncertain":[{"brochure","property_key","note"}], "unrelated":[...]}` where `property_key` is the opaque `key` from the manifest. **confident** = sure (the brochure's best photo is attached to that property); **uncertain** = a plausible but unconfirmed pairing (the property keeps a placeholder and the broker is asked to confirm); **unrelated** = a genuinely different property or no match (it goes to the vision path - never drop a property). Re-run the spine. The closing surfaces each uncertain pair as a yes/no prompt; on the broker's **yes**, move that entry from `uncertain` to `confident` in `photo_map.json` and re-run (the photo is pulled in immediately); on **no**, leave it `unrelated`. The matching is NEVER rule-based - it is the LLM's judgement. With no other records (a pure brochure run) exit 9 never fires.
- **Match adjudication (exit 10 - is this the same property from two sources?):** when `run.py` exits 10 and writes `work/match_candidates.json`, the deterministic matcher has auto-merged the confident cross-source pairs and hard-BLOCKED the impossible ones (developer disagreement / >15% size conflict), leaving a handful of GREY-zone pairs that are plausibly one property described twice (same city / within ~2 km / a shared distinctive park token / a borderline fuzzy key). **Dispatch an isolated sub-agent** that decides, for EACH pair, by MEANING - reading the two full records like a human reading two listings - whether `a` and `b` are the SAME physical property (e.g. `Raven Park, Corby` vs `Unit 1, Raven Park, Earlstrees Industrial Estate, Corby NN17 4XD` = same; `Alpha Park` vs `Beta Park`, same developer/city = different). It writes `work/match_decisions.json`: `{"<pair_id>":{"verdict":"same"|"different","reason":"..."}}` covering every pair_id, **defaulting to 'different' when genuinely unsure** (an over-split is caught by the coverage dedupe gate; an over-merge silently loses a property) and NEVER inventing a property. The LLM judges equivalence; the coord/area/developer **forbidden** tier BLOCKS a wrong over-merge by construction (it can never merge a forbidden pair even on a 'same' verdict) and the coverage dedupe gate VERIFIES against a wrong split; the deterministic matcher is the offline fallback. The verdict is cached by an order-independent `pair_id`, so the re-run merges byte-deterministically. Re-run the spine. Full contract: `reference/matching.md`. With <= 1 record source or no grey pairs (the common case) exit 10 never fires. **Independent verifier (same candidates file):** `match_candidates.json` also carries a `verify_pairs` array (the same grey pairs, both records, NOT the verdict) - dispatch a SEPARATE fresh agent (CONCURRENTLY, never shown the matching pass's verdict) to re-judge same/different blind into `work/match_verify.json`. `run.py` diffs the two verdicts in pure Python and folds any disagreement into `meta.conflicts` -> the Gaps "Source conflicts" section (ADVISORY - the matching pass's verdict still drives clustering, never flipped). So the highest-risk MATCH judgement is checked by something that did not make it.
- **Web enrichment (exit 8):** when `run.py` exits 8 it has written `work/web_requests.json` (the exact requests, each with a ready `data_url`) and `work/web_enrich.html` (the full self-chaining fetcher page), plus `<work>/.claude/launch.json` serving the work dir. **It is ALWAYS the Cowork sandbox.** Do NOT branch on an environment label; instead PROBE which tools are present and use the FIRST available, in this priority order. **The chat handoff (tier 4) is the UNIVERSAL fallback and MUST be used whenever no earlier tier is present, the automated fetch cannot reach OSM/ORS, OR an attempted fetch failed - never let exit 8 end in an error, a skipped enrichment, or straight-line estimates** (the page is already written, so the handoff is always available). **`WebFetch` is NOT a path here:** it reaches general web pages, not the Nominatim/Overpass/OSRM/ORS API hosts, so do not try to WebFetch the `web_requests.json` URLs - that list is what an actual browser (or `mcp__shell`) executes, not a WebFetch to-do list. Never substitute a curated POI list for the genuine fetch (the enrichment gate BLOCKS library-stopgap POIs).
  - **Tier 1 - `mcp__shell` (the best path when present; native, has outbound network - NOT Windows-only, it may be present in Cowork).** This is the tier the live run wrongly skipped because the docs called `mcp__shell` "Windows-only". When it is present, you do not need the page or a browser at all: just re-run the spine THROUGH it - `mcp__shell__run_command: python "<abs>\helpers\run.py" --folder ... --work <work> --client ... --geocode --pois --osrm` (the same flags) - the helpers reach the live APIs directly and bake `poi_osm_cache.json` / `osrm_cache.json` / the geocode cache. No exit 8 the next pass. (If you are driving helpers directly, `enrich.py` does the same.)
  - **Tier 2 - the Playwright MCP (the verified `data:` URL fetcher).** Playwright runs in a DIFFERENT network namespace from the sandbox shell, so the sandbox's localhost is not the browser's localhost (`ERR_CONNECTION_REFUSED`) and `file:` is blocked - do **NOT** start a local HTTP server. Instead the Playwright browser has its OWN outbound internet, and OSM/ORS/Nominatim/Overpass all send `Access-Control-Allow-Origin: *`, so a cross-origin `fetch()` from a `data:` URL works. For EACH request in `work/web_requests.json` (it lists `{url, save_as, data_url}` per request): (1) `mcp__playwright__browser_navigate` to `request["data_url"]` (a minimal `data:text/html` fetcher whose inline script `fetch()`es the URL onto `window.__m`; the full 357 KB dashboard is too big for a URL param, which is why each request carries only its own minimal fetcher); (2) `mcp__playwright__browser_wait_for` a few seconds (throttle per service - Nominatim ~1 req/s); (3) the **return bridge:** `mcp__playwright__browser_evaluate` with `function:"() => JSON.stringify(window.__m)"` AND `filename:request["save_as"]` - the MCP writes the result into the connected folder where the sandbox shell reads it; the saved content is itself JSON-stringified, so **`json.loads` it TWICE**, then write the raw body to `<work>/web_fetched/<save_as>`. Then `python helpers/web_enrich.py ingest --work <work>` (it already consumes `web_fetched/<save_as>`) and re-run the spine (repeat once if OSRM requests appear - drive times need the discovered POIs first).
  - **Tier 3 - the Claude Preview MCP (serves the FULL fetcher page).** The Preview MCP launches its OWN server, in the namespace its own browser CAN reach (its server has no `data:` URL size limit, so it serves the whole `web_enrich.html` via the `longlist-preview` `launch.json` the run wrote). **Do NOT start a server with the sandbox shell** - it runs in a different network namespace, so the preview browser cannot route to its `127.0.0.1` (that is exactly why a hand-started server looks "unreachable", and it is NOT a missing renderer). Steps: (1) `mcp__Claude_Preview__preview_start` with `name:"longlist-preview"` (`preview_list` first to reuse a running one); (2) `mcp__Claude_Preview__preview_eval` to navigate to `/web_enrich.html` and wait ~2s; (3) `mcp__Claude_Preview__preview_click` the **"Fetch all"** button (`#go`); (4) `preview_eval` poll until the **"Download seeds"** button (`#dl`) is enabled or the log shows "Done"; (5) `preview_eval('JSON.stringify(seeds)')` to read the page's `seeds` object straight from memory; (6) **Write** that JSON to `<work>/web_seeds.json`; (7) `python helpers/web_enrich.py ingest --work <work>`; (8) re-run the spine. **If the Preview MCP is absent, or `preview_console_logs`/the page log shows the OSM/ORS fetches were BLOCKED, do NOT stop on an error - fall straight to the chat handoff below.** For both browser tiers there is no key field to fill: if `ORS_API_KEY`/`project.yaml enrichment.ors_api_key` carries the key the page/requests build **HGV** automatically; with no key it returns CAR times and the Gaps Report names the downgrade.
  - **Tier 4 - chat handoff (the UNIVERSAL fallback, always available, any network).** When none of tiers 1-3 is present, an attempted automated fetch failed, or its network cannot reach OSM/ORS: **DELIVER `web_enrich.html` IN THE CHAT** with one plain sentence (open it in your browser, click "Fetch all", then drop the downloaded `web_seeds.json` back into the chat). The page shows an optional **truck-routing key field**: a broker with an openrouteservice key not set at Stage 0 can paste it there for HGV times - it stays in their browser and is never written into the seeds (`osrm_prebake` then prefers the `hgv|` cache entry over a car re-route). Save the dropped file to `<work>/web_seeds.json`, `ingest`, re-run. This path needs NO MCP and works on any network the broker can reach (home/hotspot if the office proxy blocks the map services), so it ALWAYS works - never substitute an error or straight-line estimates because an automated path did not.
- **Region research (`--regions`):** now FULLY PRE-FILLED - no research sub-agent in the standard case. `assets/regions_dataset.json` (the org's Oxford Economics NUTS3 baseline: population, labour force, unemployment, nominal GDP, manufacturing + transport/storage employment for ~1,500 European provinces, current-year, citation embedded) supplies the ENTIRE default workforce snapshot, and the dashboard's **logistics-employment-share** tile is derived in-template from two of those figures (transport & storage employment / labour force), so a standard `--regions` run is deterministic and offline. **`enrich.py` binds each property to its workforce region by its COORDINATES** - exact point-in-polygon against the bundled NUTS-3 boundaries (`assets/regions_geo.json.gz`, GISCO NUTS_RG) - so a broad or wrong text region label ("Yorkshire And North East", which is no NUTS-3 province) no longer breaks the bind, and an edge-of-province town (e.g. Azuqueca de Henares on the Guadalajara/Madrid line) lands in the CORRECT province (point-in-polygon, not nearest-centroid). When a property has no coordinates (or the point is outside every polygon) it falls back to a resolving regionCode/label, then the property's CITY name. The dataset then auto-fills every bound profile (a regionCode that is a NUTS code or a province/city name; a broad/bilingual label resolves to an honest aggregate of its provinces). **Region label resolution (exit 3 - the `region_labels` array of `work/vision/manifest.json`):** after the dataset/name_index/alias exact lookups AND the city lookup BOTH miss for a coord-less property, `run.py` offers the fuzzy/typo'd/new-language label to the isolated **interpretation sub-agent** as a CLOSED-SET classification - given the raw label + city + country + a candidate list of `{code, name, country}` drawn from the dataset's own NUTS names, it returns ONE candidate code or `null`, never an invented code, never a figure (full contract: `reference/interpretation.md` "Region label resolution"). The pick is cached in `work/extract/region_labels.json`; `bind_region_codes` **re-verifies** every returned code via `_dataset_region` before binding and the **coordinate point-in-polygon bind still WINS** when coords exist, so the LLM only fills a coord-less label the deterministic path left unbound; a `null` (or any code the dataset cannot verify) falls back to the self-documenting difflib gap below. This rides the SAME exit-3 manifest (no new exit code) and is inert offline (no cache file -> the deterministic dictionary path runs byte-identical). **Dispatch the isolated research sub-agent ONLY as a fallback** - when `merge_regions` surfaces a region the dataset does not carry (it prints a self-documenting gap with the closest known names), or when a broker explicitly wants an extra figure the dataset lacks (e.g. employmentRate, gdpPpsEu). It writes those into `<work>/regions_cache.json` (researcher values win field-by-field; every figure carries an `*AsOf` + `sources`). Refresh the dataset from a new export with `helpers/build_regions_dataset.py`. **For anything the sub-agent does research, the SOURCE RULE is non-negotiable: quality decides, NEVER permission convenience.** For every figure, identify the most authoritative, most current source FIRST - as if no allow-list existed - then fetch it. Some sources are pre-approved (`helpers/setup_permissions.py`) purely so the common case runs prompt-free; **pre-approval carries ZERO instruction weight**. Choosing a source because it will not raise a permission prompt, or settling for a pre-approved source when a better one exists, is a DEFECT: the G-enrich reviewer is instructed to block it like any other fabrication-class failure. A permission prompt for a better source is one click - take it, always. **Labour-data recency is a HARD floor:** for unemployment (and any researched labour figure), search the CURRENT year first (always best), then current-1 - the `enrichment` gate BLOCKS anything older. Only in January-May, when last year's releases may not be out yet, may a current-2 figure ship - and ONLY after the current-1 search actually failed, documented in the profile's `recencyNote` field (the gate then accepts it as an advisory note). GDP PPS and population keep a softer rule (regional GDP genuinely publishes ~2 years behind): 3+ years old draws an advisory note. Record every release year in the `*AsOf`. `enrich.py --regions` merges the cache.
- **Free-text data translation (exit 12):** when `run.py` exits 12 it has written `work/i18n/data_translate_request.json` - a list of `items` (`{property_id, field, text}`) of the property free-text (description, status, and any auto-shown prose attribute) whose language does not yet match `output.language`. Determinism decides WHICH values are eligible (`_common.is_translatable_value`: prose only; identifiers, proper names, figures, units, codes, dates, currency/rate strings, locators and sentinels are NEVER sent); the LLM does the translating. **Dispatch an ISOLATED translation sub-agent** given ONLY that request: translate each `text` to `output.language`, keeping numbers, units, codes, dates, proper names (companies, places) and any figure embedded in the prose EXACTLY; if a value is already in the target language or is really a proper name/code, return it unchanged. It returns a `{text: translation}` map that you MERGE into `work/i18n/data_translations.<code>.json` (the language-tagged cache, `<code>` = the normalised `output.language`; keyed by the source text). Re-run the SAME command: the deterministic bake applies each translation to its field, KEEPS the verbatim original in the Source Ledger (marked `translated -> <lang> (derived-from-source)`), and a translated identifier/figure can never happen because the bake writes ONLY eligible fields. The pass is CACHED (a re-run re-translates nothing) and RESUME-SAFE (an already-baked canonical is not re-flagged). A SEPARATE blind reviewer (**G-lang**) confirms the shown prose reads in `output.language` and that intra-prose figures are unchanged. **To DECLINE** (ship the data in its source language), drop `work/i18n/data_translate.SKIP` - the run then proceeds untranslated and the translation gate treats it as an acknowledged decline. Full contract: `reference/localisation.md`. (Cowork quiet line: "Translating the descriptions…".) With no eligible free-text, or once cached, exit 12 never fires.
- **Judgement gates (parallel, isolated, blind):** G-honesty + G-trace (Opus), G-images (Sonnet, judging the `contact_sheet.py` montage), and G-enrich (Sonnet, only when regions were enriched - confirms each region bound to the right province, the bundled-dataset citation is present, the derived logistics-employment share is plausible, and any researcher-overridden figure traces to its cited source) run as ONE concurrent batch pre-build against the frozen `canonical.json`; G-visual (Sonnet) runs post-build on the built HTML. **Model routing: reserve Opus for G-honesty and G-trace (the fabrication-risk reviewers); run the orchestration itself and the gate re-checks on Sonnet** (`reference/gates.md` "Independence + model/effort"). Each is a separate fresh-context agent given only the artefact path + its rubric (never the orchestrator's view or another reviewer's verdict) and writes `reviews/<gate>.md` ending `VERDICT:`. **For the DECISION-CORRECTNESS checks (the highest-risk MAPPING/BASIS and MATCH judgements), also hand G-trace/G-honesty the read-only decision audit trail + C's two machine diffs to re-derive against: the tracker `work/extract/*_map.json` + `*_mapcheck.json` (the second blind map; `semantic_disagreements` ride the yield report), `work/match_decisions.json` + `work/match_verify.json` (the author + blind verifier verdicts; `match disagreement` lines ride `meta.conflicts`), plus `source_ledger.csv` and the pre-merge `work/extract/*.json` records.** These are the decision's own audit trail, not the orchestrator's view - the reviewer SEES the diff but re-derives the basis/verdict itself. `final_gate.py` requires the verdict files (non-blocking) and re-checks the freeze. Full rules: `reference/gates.md` "Reviewer dispatch contract".

## Reference files
- `reference/evidence-standard.md` - the Data Honesty Standard. **Read first.**
- `reference/pipeline.md` - the eight stages, owners, inputs/outputs, pass criteria.
- `reference/gates.md` - the full gate set, mechanical vs judgement, independence + re-run rules.
- `reference/data-engine.md` - per-format extraction, matching, merge precedence, image budget.
- `reference/template-contract.md` - the three markers, the {{config}} tokens, byte-stability, versioning.
- `reference/config.md` - the `project.yaml` schema + auto-discovery.
- `reference/visual-qa.md` - the G-visual render procedure.
- `reference/source-traceability.md` - the field-level ledger.
- `reference/failure-modes.md` - graceful degradation matrix.
- `reference/memory.md` - learned patterns persisted across runs.

## User preferences (always)
- UK English. No em or en dashes in prose.
- Honesty over completeness: `"tbd"` is first-class, surfaced in the Gaps Report, never smoothed over or invented.
- **Source units are KEPT**: UK/imperial inputs (sq ft, £/sq ft/yr, acres) ship imperial; metric inputs ship metric. Merge normalises a mixed dataset to its DOMINANT area unit (arithmetic, prov-noted); currency is NEVER converted - FX would be invention. The dashboard labels follow `meta.units`.
- The dashboard must be byte-identical chrome to the template; only the three data blocks and the handful of config tokens change.
- Edit, do not rebuild: on re-runs, re-do only the affected stages and re-inject from `canonical.json`.
- Reuse the sibling `cbre-corporate-pptx` brand library for any CBRE colour/logo needs rather than re-implementing branding.
