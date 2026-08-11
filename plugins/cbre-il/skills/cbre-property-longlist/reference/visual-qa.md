# G-visual - the visual-render gate

The mechanical half is `helpers/render_qa.py`; the judgement half is an isolated **Sonnet** reviewer (layout/look is an easier, faster judgement than the fabrication gates). Mirrors the account-briefing G7 (render -> reviewer -> fix -> re-render with a fresh reviewer).

## Procedure (orchestrator drives the Claude Preview MCP)
1. `render_qa.py <built.html>` - if Playwright is present it loads the page headless, asserts `.card` count == `PROPS.length`, captures console errors (any = fail), and saves `render/grid.png|modal.png|map.png`. Otherwise it runs a browser-free **static structural floor** (all three data blocks present, no unreplaced `{{config}}` tokens, a non-empty `PROPS` whose every photo is an embedded `data:` URI, the map + CBRE chrome intact), writes `.claude/launch.json`, prints the MCP steps, and emits `STATUS: BLOCKED` if the floor failed (the file is broken) or `STATUS: NEEDS-PREVIEW-MCP` if it passed.

**Playwright-MCP path (when `mcp__shell` + the Playwright MCP are present - the VERIFIED primary for the heavy dashboard, 2026-06-16).** The Playwright MCP **blocks the `file:` protocol**, so you serve the built file over **loopback HTTP** and navigate to that. The one thing that makes or breaks it: **start the server with the NATIVE `mcp__shell`, NOT the sandboxed bash** - the sandbox bash runs in a different network namespace, so a server it starts is unreachable at the browser's `127.0.0.1` (this was the real "renderer unreachable" dead-end, not a missing renderer). Steps:
   1. Start a detached native server (PowerShell `Start-Process` survives the call; `start /b` gets reaped): `mcp__shell__run_command:` `powershell -NoProfile -Command "Start-Process python -ArgumentList '-m','http.server','8799','--bind','127.0.0.1','--directory','<work dir>' -WindowStyle Hidden"`.
   2. `mcp__playwright__browser_navigate` to `http://127.0.0.1:8799/<built file name>.html` (**http, never `file://`**).
   3. `mcp__playwright__browser_snapshot` (asserts the cards/modal structure) and `mcp__playwright__browser_take_screenshot` for grid / modal / map; drive `openModal(1)` and `switchView('map')` via `mcp__playwright__browser_evaluate`.
   4. Dispatch the isolated reviewer on the screenshots; then STOP the server: `mcp__shell__run_command:` `powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8799 -State Listen -ErrorAction SilentlyContinue | %% { Stop-Process -Id $_.OwningProcess -Force }"`. (A bare favicon 404 shows as one benign console error - ignore it; the self-contained dashboard has no favicon ref.)

**Playwright absent is NOT a reason to skip G-visual.** When the Playwright MCP is not present, the Claude Preview MCP (`preview_*` tools) is the intended fallback - run the Preview-MCP procedure below, then dispatch the isolated reviewer. If NEITHER Playwright NOR the Preview MCP is available, the static structural floor `render_qa.py` printed is the mechanical proof that the file is a complete, openable, token-clean dashboard - it does NOT judge appearance, so mark the run **DEGRADED on the visual dimension** and say so plainly; never report a clean visual pass off the floor alone. A floor `STATUS: BLOCKED` is a real block (the build is structurally broken) regardless of any renderer.

**Same probe order as the exit-8 fetch, different transport.** The exit-8 drive-time fetch (SKILL.md "Web enrichment (exit 8)") probes the same tools in the same priority order, with two differences specific to it: its tier-1 `mcp__shell` run hits the live APIs and bakes the caches directly so it needs NO page or browser at all, and its Playwright tier uses a minimal `data:` URL fetcher (one request at a time) because the full 13 MB dashboard is far too big to carry in a `data:` URL - so for G-visual here you still serve the built file over the Preview MCP's own server (or `mcp__shell` loopback HTTP) rather than a `data:` URL.
2. Preview-MCP path:
   - `preview_start` the static server for the built file's directory.
   - `preview_eval`: navigate, wait ~3s, assert `document.querySelectorAll('.card').length === PROPS.length`.
   - `preview_eval('openModal(1)')` -> screenshot the modal.
   - `preview_eval("switchView('map')")` -> screenshot the map; toggle a POI layer only if `meta.enrichment.pois`, a 30-min isochrone only if `meta.enrichment.osrm` (opt-in extras - absent by configuration is not a defect).
   - `preview_console_logs` level error -> MUST be empty, EXCEPT failed network fetches to tile/Overpass/OSRM hosts in a sandboxed preview (blocked-host errors are environment, not defects).

Note: the dashboard embeds ~30 base64 images, so a full-page **screenshot can time out** on a heavy page; prefer DOM assertions via `preview_eval` (card count, modal opens, map markers present, console clean) when the renderer is slow - they are a reliable substitute for the mechanical pass.

## The isolated reviewer
Opens the view PNGs (Grid, Map, Flyover, Compare) and judges against `assets/reference_screenshots/` (**if that folder has no PNGs - it ships with only a README - judge against the rubric below and the CBRE house style; the missing baseline is NOT itself a finding**):
- **Grid:** cards populated (thumb, park title, city/developer, key specs, rent, "View details"); CBRE green + Financier/Calibre; no broken thumbnails or overflow.
- **Modal:** opens, populated, scrolls, closes; `"tbd"` shown honestly, never blank or a fabricated value.
- **Site Plan (the modal's Site Plan toggle, when a property has one) - the INDEPENDENT plan verify:** open it and confirm the image IS genuinely THIS property's SITE PLAN - a footprint / block / layout drawing of the plot (unit outline, site boundary, dock/yard/parking, dimensions). The mechanical images gate does NOT judge the plan slot, so THIS is the independent-LLM check that the interpreter's `plan_page` pick was right. REJECT and flag **HIGH** if it is instead a location / context / connectivity map, an interior or exterior photo, an accommodation / specification table, a contact / cover / agents page, or a DIFFERENT property's plan (a wrong image here is an authoritative false claim - the slot carries no on-image source trace). A missing plan is honest; a wrong one is not — so **verify the plans that ARE bound; do not go hunting for ones that are not.** If a missed plan happens to be obvious in a screenshot you already have open, note it as `advisory:` with the source + 0-based page; but do NOT open decks to search for candidates. "Find a plan we have not found yet" has no terminal state, and the deterministic `planNearMiss` scan already surfaces plan-ish pages into the Gaps Report's "Possible site plans not captured" without a reviewer round.
- **Map:** markers at correct positions; legend present. Check **POI layer toggles** only when `meta.enrichment.pois` is true, and **isochrone polygons** only when `meta.enrichment.osrm` is true - these are broker-opt-in extras; their absence on a build that did not request them is correct configuration, not a defect.
- **Compare (the fourth tab):** switch to it - it compares ALL properties by default (columns = properties + the pinned Attribute column). Confirm: the comparison table renders (reusing `compareHTML`), the **Attribute column stays pinned** while the property columns scroll horizontally (essential at 8/12+ properties), the deselect **chips wrap** and toggling one drops/adds its column, Select-all / Clear-all work, and the largest-warehouse / lowest-rent highlights are present. Flag overflow/clipping or a crushed layout as a visual MED. (The card tick-box popup compare is separate and unchanged.)
- **Flyover (the third tab):** navigation is prev/next buttons, arrow keys, space bar and marker-click ONLY - scrolling must NOT change the property. Confirm the map flies to the active option and one option shows at a time.
- **Localisation (when `meta.language` is non-English):** the visible chrome should be IN-LANGUAGE with no leftover English (beyond the legitimate invariants CBRE/OSRM/BREEAM/HGV/PPS/EU27/REIT/km/%), and no obvious **truncation/overflow/clipping** from a longer translated label (German/Finnish compounds and the footer disclaimer are the usual offenders). This is the VISUAL surface of localisation; the fluency/completeness/house-term judgement is **G-i18n** (`reference/gates.md`), and the deterministic floor is `gate_runner.py i18n`. Flag a clipped/overflowing localised label as a visual MED; flag leaked-English chrome to G-i18n.
- **Sandboxed preview (Cowork) network caveat:** the dashboard fetches map tiles (Carto/ArcGIS), client-side POIs (Overpass) and drive times (OSRM) from the internet AT OPEN TIME. A sandboxed Preview-MCP browser may block those hosts, so **grey/blank map tiles, missing POIs or "tbd" drive-times in a preview screenshot are an environment artefact, not a defect** - note them as `[ENV]`, judge the markers/cards/modals/chrome that render locally, and never block on them. On the broker's machine (normal internet) they resolve.
Writes `reviews/round<N>/G-visual.md` (the round you are dispatching; see `reference/gates.md` "Reviewer dispatch contract" rule 3) with per-view `[OK]/[ISSUE HIGH|MED|LOW]/[ENV]` finding lines (see `reference/gates.md` "Verdict semantics" for the machine-actionable format) ending in `VERDICT: <green|amber|red>`.

**LABEL EVERY FINDING `blocking:` OR `advisory:` — you decide which, and nothing downstream
second-guesses you.** Python counts the rounds; it never classifies a finding, because severity on
an unseen deck in an unseen language is a judgement only you can make. Use this rubric:

- **`blocking:`** — the build makes a **false claim** or is **structurally broken**: a mis-bound or
  wrong-property Site Plan; a `tbd` rendered as blank or as a fabricated value; a wrong property's
  photo; zero cards; a real (non-`[ENV]`) console error; an unopenable or empty view.
- **`advisory:`** — everything that is a **matter of degree on byte-frozen chrome**: layout,
  spacing, crowding, clipping, overflow, a crushed column, colour, a thumbnail that could be
  nicer, and every `[ENV]` note. Report them precisely; they do not block.

A `VERDICT:` line is optional and ignored - the LABEL on each finding is what carries. An
**advisory** finding never blocks: it is carried to the Gaps Report and shipped (see "Fixing"
below). A **blocking** finding blocks the ship gate until the orchestrator records a repair,
because its remedy is deterministic and therefore terminates: strike the field to `tbd`, clear
`p.plan`, or fix the data. If you found nothing, write the single line `FINDINGS: none` -
silence is indistinguishable from a crashed review and fails safe.

Why the split: a layout defect on frozen, version-pinned chrome is **identical on every run**, so it
is a template-level bug for the eval battery to catch once and for all — not a per-client QA round
that protects exactly one deliverable. A false claim about a property is the opposite: it is unique
to this run and nobody else will catch it.

## Fixing
- A **data** defect (e.g. a missing `lat`/`lng` so a marker is absent) -> unfreeze `canonical.json`, fix, re-run pre-build mechanical gates, re-freeze, rebuild.
- A **template/render** defect (a chrome layout bug) -> fix `assets/dashboard_template.html` and **bump the template version** (`reference/template-contract.md`).
- A **wrong Site Plan** (the reviewer rejected the bound plan image) -> a DATA fix: clear that property's `p.plan` in `canonical.json` and correct/remove the mis-picked `__meta.plan_page`. A **missed** plan (toggle absent but the deck has one, e.g. on a 2-page spread) -> set the correct 0-based `__meta.plan_page` and re-run the interpret->merge path. Both are DATA fixes (the plan is a data URI inside PROPS), never a template change.
  - **The rejection must be made DURABLE, or merge re-binds the same image on the next run.** Clearing `p.plan` alone is not enough: five separate tiers can bind a plan, and the last is a deterministic page scan that will re-pick the same page. Record it in the placeholder-audit ack as `<source file>#<1-based page>`; every tier consults that, so the page is never re-offered. **The REVIEWER must therefore state, for each rejected plan, the source file name and the 0-based page it came from** - the orchestrator cannot form the key without them, and a rejection it cannot key is a rejection that does not stick.
**ONE review pass. The reviewer PROPOSES, the orchestrator IMPLEMENTS, then we deliver.** There is
no second render-and-review cycle. `final_gate.py --qa-state <work>` BLOCKS while a `blocking:`
finding has no recorded repair (`qa-round resolve --id <id> --because "…"`) and CARRIES every
advisory finding instead, into the Gaps Report's **"Known limitations (reviewed and accepted at
QA)"** section, which ships with the dashboard. Do NOT re-dispatch a reviewer to "confirm the fix" on
a gate that returned no blocking finding, and do NOT reopen a gate to re-check an advisory finding
— **an advisory finding is CLOSED by being written down, not by being fixed.**

**Order matters: `qa-round record` → deliver → `final_gate`.** `deliver` is what actually writes the
carried findings into the report, so running the gate first blesses a report that is a round behind.
`final_gate --qa-state` now BLOCKS on that mismatch, and its remedy is ONE `deliver.py` re-run
(printed in full, slug and filename already derived) — never another review round.

(Why this is mechanical: this line used to read "re-review with a fresh reviewer until zero
HIGH/MED", which is an unbounded loop whose exit condition is a subjective verdict re-earned by a
deliberately memoryless reviewer. On a matter of degree — crowding, spacing, a clipped compound —
a fresh reviewer can always find one more, so it never terminated.)
