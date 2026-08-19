---
name: kato-longlist
description: >
  Build a client-ready Industrial & Logistics property LONGLIST from a Kato (agency.kato.app)
  requirement, enriched with rents and specs from the broker emails, ending in a comprehensive
  per-property dataset, a clean client Excel, and a CBRE-branded HTML dashboard. Trigger when the
  user wants to "run the Kato longlist", build/refresh a Kato requirement's longlist or client
  schedule, or turn a Kato requirement URL + its broker emails export into a dashboard/spreadsheet.
---

# Kato-Longlist

**Principle:** the LLM makes every judgement (matching broker rents, curating specs, picking site
plans, choosing client columns); the Python helpers move bytes (login, API pulls, downloads, image
resizing, .msg parsing, writing files). Run every helper with native Windows Python via
`mcp__shell__run_command` or the PowerShell tool where those exist; in **Claude Cowork** use whatever
code-execution tool is available instead, and see step 0. `HELP` = this skill's own `helpers` directory
(on Timo's PC, `C:\Users\TBaaij\.claude\skills\Kato-Longlist\helpers`; elsewhere, wherever the skill is
installed — never hardcode that path in Cowork).

## Inputs

**Toolkit update check (run once, first).** Run `python helpers/version_check.py`. It prints a
one-line note to stderr *only* if a newer UK I&L Toolkit version has been published (otherwise it is
silent); it does nothing but a single public version lookup, never blocks the run, and is safe to
ignore.

A `run.yaml` in the working directory (copy `run.example.yaml`): `kato_url`, `email`, `password`,
`emails_zip` (default `Emails.zip`), `image_max_px` (1200), `image_quality` (70), `client` (label for
the dashboard/deliverables), `ors_api_key` (openrouteservice, for HGV drive-times). The broker email
export (`Emails.zip` of Outlook `.msg` files) sits in the working directory.

**ASK for the Kato credentials; never ship them.** `email` and `password` arrive blank in
`run.example.yaml` on purpose. Before the first helper that logs in, ask the user for their **CBRE
email** and **Kato password**, and write them into the working directory's `run.yaml` — which is
git-ignored, so a filled-in config can never be committed. Do not paste either value into the chat,
a deliverable, or any file other than that `run.yaml`, and do not carry them between projects: ask
again per working directory. If `run.yaml` already has both filled in, use them and do not re-ask.
The `ors_api_key` is the free organisation-wide key and already ships filled in, so it never needs
asking for.

## Pipeline

**0. Preflight — ALWAYS FIRST, BEFORE ANY OTHER STEP** —
`python "%HELP%\kato_preflight.py" --config run.yaml`
Measures what this environment can actually do (network to Kato, Playwright, packages, bundles already
present) and prints a **VERDICT**. Never guess which stage-1 path to use — branch on it:
- **`DIRECT_FETCH_OK`** → step 1.
- **`BUNDLE_REQUIRED`** and a bundle is present → step **1-alt**.
- **`BUNDLE_REQUIRED`** and NO bundle → run
  `python "%HELP%\deliver_extension.py" --out <a folder the user can download from>`, then **give the
  user both files** (`kato-capture-extension.zip` + `HOW-TO-CAPTURE-KATO.md`), tell them plainly that
  this environment cannot reach Kato so they must capture it in their own browser, and **STOP and wait
  for their bundle.** Do not attempt step 1 anyway: in Cowork it dies on a Playwright `ImportError` or a
  silent network timeout, which reads as a broken skill to a non-technical colleague.

Honour the `degradations` it prints — e.g. no `pymupdf` → no site plans (step 7d); no network → the
toolkit's enrichment needs its `web_enrich.py` browser handoff rather than live
`--geocode/--pois/--osrm/--regions`. **Step 2 is never a degradation:** .msg parsing is done by this
skill's own `msg_reader.py` (standard library only), so it works in Cowork with no pip and no network.
If a run ever reports emails as unavailable, that is a bug or a missing export — never "the sandbox
cannot do it".

**1. Fetch** — `python "%HELP%\kato_fetch.py" --config run.yaml`
Logs into Kato, enumerates the Longlist, and per property saves `_raw.json` + `_derived.json` and
downloads the brochures/docs and photos (photos capped at 1200px / <500KB). Idempotent; re-runnable.

**1-alt. Ingest a browser-captured bundle (NO Playwright, NO network)** —
`python "%HELP%\kato_ingest.py" --config run.yaml --bundle kato_bundle_<reqid>_<date>.zip`
Use this INSTEAD of step 1 whenever Playwright or outbound network is unavailable — above all in
**Claude Cowork**, which is fully sandboxed (only WebSearch/WebFetch have egress), so the Kato API is
unreachable no matter what credentials are held. The colleague captures the requirement with the
Chrome extension (`kato-cowork-bridge/extension`, see its README) while signed in to Kato, which
writes one bundle; this rebuilds the exact tree step 1 would have produced by calling the same
`common.py` functions, so steps 2-7 are unchanged. Pass `--bundle` once per part for a split capture.
It ABORTS if the bundle's requirement id does not match `run.yaml`'s `kato_url`. In Cowork, run the
helpers with whatever code-execution tool is available rather than `mcp__shell__run_command`, and
expect `--bundle` media to be all the media there is: there is no way to fetch a missing file later.

**2. Parse emails** — `python "%HELP%\emails_parse.py" --config run.yaml`
Turns the `.msg` files into clean text (`emails/emails.md`, `emails.json`) and saves every attachment
(`emails/attachments/NN/`, with the broker's inline signature logos kept apart in `NN/inline/` so the
brochures are obvious). Parsing uses `msg_reader.py` from this skill — **standard library only, so it
needs no install and works in Cowork**. It also reads emails attached to emails, because broker rents
are regularly one reply deep.
It finds the export even when it is not called `Emails.zip` (any zip in the working directory holding
.msg files) and **says which file it used** — so check that line rather than assuming. Read the
`parsed=X/Y failed=Z` line: anything less than all of them means text is missing and belongs in the Gaps
Report. Zero parsed exits non-zero.
To prove .msg reading works in an unfamiliar environment before running the pipeline:
`python "%HELP%\msg_reader.py" --selftest <the export zip or folder>` (takes seconds, needs nothing).

**3. Facts for the model** — `python "%HELP%\make_facts.py" --config run.yaml`
Writes `emails/_property_facts.json` (each property's identifiers + key_points + summary + its
**`kato_messages`**: the Kato in-app broker threads). **Most rents and much of the enrichment live
in `kato_messages`, NOT the Outlook export** — a broker's quote is usually posted on the Kato match
thread. These messages are frequently MULTI-OPTION (one message lists several buildings, each with a
rent, and is attached to several property threads), so map each figure to the RIGHT building by
name/size; never blanket-apply a whole message to every property it is attached to.

**4. Enrich (you)** — read `emails/emails.md` + `emails/_property_facts.json` and write
`enrichment.json` (`{"overrides": {"<property folder>": {rent, spec, outgoings, description, notes}}}`).
- **You MUST read every property's `kato_messages` (in `_property_facts.json`) as well as
  `emails.md`** — the Kato in-app threads carry most of the rents and a lot of the spec, and a
  property with no email quote very often DOES have a Kato-message quote. Do NOT leave a rent at
  "On application" without first checking that property's `kato_messages` (and the multi-option
  messages attached to OTHER properties, which routinely name this building too).
- Rent = the broker quote, taken in order: email quote → Kato-message quote → Kato structured →
  `"On application"`. Attach a rent only when a broker clearly names that exact building; otherwise
  leave it null. Keep the qualifier ("guiding, exc + VAT", "sublease assignment", "assignment til
  <date>"). Kato messages are multi-option — match each figure to the right building by name/size.
- Specs (clear height, power, loading, yard, parking, floor loading, EPC, BREEAM, availability) come
  from each property's own key_points/amenities/summary. Add outgoings where a broker states them.
- **`description`** (REQUIRED, every property): author a 3-4 sentence dashboard description from that
  property's own `summary` + `description` + `location_text` (in its `_derived.json`/`property.json`).
  Cover what the unit is + headline spec, then the location/connectivity. UK English, no em/en dashes,
  no invention (only what the source states). This is the prose shown on each card's detail modal;
  `build_dataset.py` carries it to `property.json.curated_description` and `patch_canonical.py` injects
  it into the dashboard. (The toolkit's tracker path cannot carry a description, so without this the
  cards show none.)

**5. Assemble** — `python "%HELP%\build_dataset.py" --config run.yaml`
Merges enrichment + Kato data + media into `properties/<folder>/property.json`, `_dataset.json`,
`_gaps.json`.

**6. Client Excel** — `python "%HELP%\build_excel.py" --config run.yaml`
Writes the client workbook (Longlist + For Sale sheets, merged header bands, links shown as "link").

**7. CBRE HTML dashboard** — via the toolkit skill `cbre-il-toolkit:cbre-property-longlist` (invoke it
to resolve its `helpers/` path; run its helpers with `mcp__shell`, absolute paths). Set
`ORS_API_KEY` in the running shell so drive-times are HGV.

> **Two paths, don't mix them.** Both are the toolkit's **skill root** (the dir containing `helpers/`
> and `assets/`), not its `helpers/` dir — so toolkit scripts are `<toolkit>\helpers\<name>.py`.
> `<install>` is the resolved toolkit skill directory — whatever is installed right now, so Kato always
> inherits the newest CBRE chrome; Kato ships **no** dashboard template of its own. `<toolkit>` is the
> per-run **shadow** of it (step 7a.5) and is what every later step uses. Kato writes only to the
> shadow, never to `<install>`.

- **7a.** `python "%HELP%\toolkit_tracker.py" --config run.yaml` — writes `longlist_inputs/` (the
  availability tracker + `project.yaml`, all enrichment on, ORS key baked).
- **7a.5. Shadow the toolkit** — `python "%HELP%\toolkit_shadow.py" --source "<install>" --work <work>`
  → prints `<work>\toolkit`, which is `<toolkit>` for the rest of step 7. Copies the installed
  toolkit (~28 MB, ~1 s; skips `evals/`, `docs/`, hardlinks `vendor/`) so step 7e.5 can patch the
  template without touching the install. The toolkit derives its `SKILL_ROOT` from `__file__`, so
  the shadow is self-contained — template, VERSION, integrity manifest, i18n, datasets and gates all
  resolve inside it. Rebuilt fresh each run, so a toolkit update is picked up automatically; pass
  `--keep` to reuse the existing shadow when resuming. Runtime caches are unaffected (the toolkit
  writes `geocode_cache.json` / `poi_osm_cache.json` / `osrm_cache.json` / `regions_cache.json` into
  the **work** dir, not the skill dir). It warns if `<install>` is already `-kato` tagged, which means
  an older Kato run patched it in place — reinstall or update the toolkit to get pristine chrome back.
- **7b.** Run the toolkit spine on that folder:
  `python "<toolkit>\helpers\run.py" --folder <work>\longlist_inputs --work <work>\longlist_work --client "<client>" --geocode --pois --osrm --regions`.
  When it asks for the tracker column map (exit 3), write the map + its blind-check file, then re-run;
  it builds `canonical.json` and passes its data gates. (Drive-times report `driving-hgv`.)
- **7c.** `python "%HELP%\inject_photos.py" --config run.yaml` — put our photos into `canonical.json`.
- **7c.5. Patch canonical (our data the toolkit drops)** — `python "%HELP%\patch_canonical.py" --config run.yaml`.
  Injects, per property, straight from `property.json`: the curated **description**, the **landlord**
  (real name / "Confidential"), the **brochure / video / website** URLs, a **Street View** URL (from
  the geocoded street-view pano/coords), and **EPC**. The toolkit has ONE green-cert field (`breeam`)
  and no tracker path to description/links, so these are dropped in its column-mapping step — we own
  `property.json`, so we inject them here (same pattern as `inject_photos.py`). `developer` is left
  `tbd` on purpose (the source rarely names one).
- **7d. Site plans (vision).** `python "%HELP%\brochure_montages.py" --config run.yaml` → look at each
  `plan_qa/broch_NN.png` and pick the site-plan page for each property (0-based global page label);
  write `decisions.json` (`{"<order>": <page>|null}`, null where the brochure has none) →
  `python "%HELP%\bind_site_plans.py" --config run.yaml --decisions decisions.json`.
- **7e. QA.** `python "%HELP%\qa_montages.py" --config run.yaml` → look at `plans_qa_*.png` (every bound
  plan is a real plan) and `heroes_qa_*.png` (right photo on the right property); fix any via 7d.
- **7e.5. Patch the toolkit template (card/modal presentation)** — `python "%HELP%\patch_template.py" --toolkit "<toolkit>"`
  (the SHADOW from step 7a.5 — the same dir whose `build_dashboard.py` you run below, never `<install>`;
  the helper refuses any target that is not a shadow, so this cannot go wrong silently).
  Applies Kato's idempotent card/modal tweaks to `<toolkit>\assets\dashboard_template.html` and
  re-versions it (rewrites `assets\VERSION` chrome_sha256 so the toolkit's own template-SHA + byte-
  equality gates stay green). What it changes: card 4th cell `Early access`→`Electricity`; card eyebrow
  `developer · motorway` (both tbd → "TBD · TBD") → developer-or-city (no dangling separator); drop the
  hero **Developers** KPI tile when ≤1 distinct developer; add **Brochure / Video / Website / Street
  View** links to the modal top row; and hide the bare `motorway`/`status`/`breeam`/`early-access`
  "tbd" chips there. Two patches are RETIRED because template v38 does the job natively: the
  `DENY_FIELDS` guard (v38 has no auto "Additional Details" section at all) and the separate modal EPC
  row (v36+ renders a combined BREEAM/EPC row via `certStr(p)`). Retired patches are not deleted - each
  keeps a premise re-asserted every run, so a toolkit regression bringing the old condition back fails
  loudly instead of quietly shipping a dashboard missing the fix. Idempotent + version-agnostic: re-run
  each session (the shadow is rebuilt pristine from the install every run); it reports EVERY moved anchor
  in one run and writes nothing rather than shipping unpatched. Use `--dry-run` to check a new toolkit
  version without touching it — that one is safe to point straight at `<install>`.
  **NEVER hand-edit `built.html`** (the byte-equality gate rejects it) — the patch goes in the template.
- **7f. Build + deliver** — `python "<toolkit>\helpers\build_dashboard.py" <work>\longlist_work\canonical.json --out <work>\longlist_work\built.html`
  then the toolkit `deliver.py` (dashboard, Source Ledger, Gaps Report, Longlist xlsx).
- **7g. Reviewer gates** — run the toolkit's isolated reviewer gates (G-honesty, G-trace, G-images,
  G-visual, G-enrich) per its `reference/gates.md`, then its `final_gate.py`.

**8. Finalise — ALWAYS LAST, NEVER SKIP** — `python "%HELP%\finalize_run.py" --config run.yaml`
Collects every client-facing file into `OUTPUT/`, writes a plain-English `START-HERE.md`, and deletes
junk (`__pycache__`, `.pyc`, stray temp files) from a fixed allowlist. It touches nothing a re-run or an
audit needs, and is idempotent. **Do not tell the user the run is finished until this has run and you
have given them the one path to open.** Use `--dry-run` to preview.

## Outputs (working directory)
- `OUTPUT/` — **the only folder the user needs**: dashboard, spreadsheet, Gaps Report, Source Ledger.
- `START-HERE.md` — what to open, what to send, what to ignore. Written by step 8.
- `properties/<NN - Name - Postcode>/` — `_raw.json`, `_derived.json`, `property.json`, `media/`.
- `properties/_dataset.json`, `_index.json`, `_gaps.json`; `emails/`; `enrichment.json`.
- `longlist_work/` — toolkit working data (the deliverables are moved out of it by step 8).

## Working directory discipline (NOT optional)

A real run was handed over as twenty mixed folders with the dashboard buried three levels down beside QA
montages and `__pycache__`, and the colleague who asked for it could not tell which file to send their
client. Producing the bytes is not the job; producing something a non-technical person can use is.

- **Everything goes in the working directory.** Never write to the user's home, Desktop, Downloads or a
  system temp path, and never leave files outside the folder they gave you.
- **One place for scratch.** If you need intermediates of your own, put them in `_scratch/` inside the
  working directory and **delete it before you finish**. No `test2.json`, no `output_final_v3.xlsx`, no
  half-written files left where a human will find them and wonder.
- **Do not duplicate inputs.** Never leave a second copy of a 50 MB export lying around; unpack to a temp
  location and clean up (step 2 already does this).
- **Use the documented layout.** Do not invent folder or file names. If something has no documented home,
  it belongs in `_scratch/` and then in the bin.
- **Finish with step 8, then say one sentence naming one path** — the `OUTPUT/` folder. Do not hand back
  a list of six paths and let the user work out which matters.
- **Never present a gap as a success.** If emails failed to parse, a rent is unconfirmed, or a site plan
  is missing, it goes in the Gaps Report and in what you tell the user.
