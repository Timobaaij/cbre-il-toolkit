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
installed - never hardcode that path in Cowork).

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
email** and **Kato password**, and write them into the working directory's `run.yaml` - which is
git-ignored, so a filled-in config can never be committed. Do not paste either value into the chat,
a deliverable, or any file other than that `run.yaml`, and do not carry them between projects: ask
again per working directory. If `run.yaml` already has both filled in, use them and do not re-ask.
The `ors_api_key` is the free organisation-wide key and already ships filled in, so it never needs
asking for.

## Pipeline

**0. Preflight - ALWAYS FIRST, BEFORE ANY OTHER STEP**
`python "%HELP%\kato_preflight.py" --config run.yaml`
Measures what this environment can actually do (network to Kato, Playwright, packages, bundles already
present) and prints a **VERDICT**. Never guess which stage-1 path to use - branch on it:
- **`DIRECT_FETCH_OK`** → step 1.
- **`BUNDLE_REQUIRED`** and a bundle is present → step **1-alt**.
- **`BUNDLE_REQUIRED`** and NO bundle → run
  `python "%HELP%\deliver_extension.py" --out <a folder the user can download from>`, then **give the
  user both files** (`kato-capture-extension.zip` + `HOW-TO-CAPTURE-KATO.md`), tell them plainly that
  this environment cannot reach Kato so they must capture it in their own browser, and **STOP and wait
  for their bundle.** Do not attempt step 1 anyway: in Cowork it dies on a Playwright `ImportError` or a
  silent network timeout, which reads as a broken skill to a non-technical colleague.

Honour the `degradations` it prints - e.g. no `pymupdf` → no site plans (step 7d); no network → the
toolkit's enrichment needs its `web_enrich.py` browser handoff rather than live
`--geocode/--pois/--osrm/--regions`. **Step 2 is never a degradation:** .msg parsing is done by this
skill's own `msg_reader.py` (standard library only), so it works in Cowork with no pip and no network.
If a run ever reports emails as unavailable, that is a bug or a missing export - never "the sandbox
cannot do it".

**1. Fetch** - `python "%HELP%\kato_fetch.py" --config run.yaml`
Logs into Kato, enumerates the Longlist, and per property saves `_raw.json` + `_derived.json` and
downloads the brochures/docs and photos (photos capped at 1200px / <500KB). Idempotent; re-runnable.

**1-alt. Ingest a browser-captured bundle (NO Playwright, NO network)**
`python "%HELP%\kato_ingest.py" --config run.yaml --bundle kato_bundle_<reqid>_<date>.zip`
Use this INSTEAD of step 1 whenever Playwright or outbound network is unavailable - above all in
**Claude Cowork**, which is fully sandboxed (only WebSearch/WebFetch have egress), so the Kato API is
unreachable no matter what credentials are held. The colleague captures the requirement with the
Chrome extension (`kato-cowork-bridge/extension`, see its README) while signed in to Kato, which
writes one bundle; this rebuilds the exact tree step 1 would have produced by calling the same
`common.py` functions, so steps 2-7 are unchanged. Pass `--bundle` once per part for a split capture.
It ABORTS if the bundle's requirement id does not match `run.yaml`'s `kato_url`. In Cowork, run the
helpers with whatever code-execution tool is available rather than `mcp__shell__run_command`, and
expect `--bundle` media to be all the media there is: there is no way to fetch a missing file later.

**2. Parse emails** - `python "%HELP%\emails_parse.py" --config run.yaml`
Turns the `.msg` files into clean text (`emails/emails.md`, `emails.json`) and saves every attachment
(`emails/attachments/NN/`, with the broker's inline signature logos kept apart in `NN/inline/` so the
brochures are obvious). Parsing uses `msg_reader.py` from this skill - **standard library only, so it
needs no install and works in Cowork**. It also reads emails attached to emails, because broker rents
are regularly one reply deep.
It finds the export even when it is not called `Emails.zip` (any zip in the working directory holding
.msg files) and **says which file it used** - so check that line rather than assuming. Read the
`parsed=X/Y failed=Z` line: anything less than all of them means text is missing and belongs in the Gaps
Report. Zero parsed exits non-zero.
To prove .msg reading works in an unfamiliar environment before running the pipeline:
`python "%HELP%\msg_reader.py" --selftest <the export zip or folder>` (takes seconds, needs nothing).

**2.5. MASTER LIST: the user decides what the run builds. NEVER SKIP IT, NEVER ANSWER IT YOURSELF.**

Options arrive by three overlapping routes and nothing upstream reconciles them: the **Kato
longlist**, which raises one match request PER BROKER so the identical unit arrives two or three
times under different agencies; the **broker emails**, where agents re-send options that are
already on Kato and also name options that are on nobody's Kato; and **whatever extra files the
user drops in the working directory**, usually brochures for options already in one of the first
two. Before this step the run took every Kato match, silently merged whatever shared a postal code
and an exact floor area, and never saw an email-only option at all. The user found out what had
been decided by reading the finished dashboard.

So: inventory everything, put it in front of the user, and build only what they say. The workbook
is the single source of truth from here to the end of the run.

- **2.5a. Write the candidates (YOU, this is the judgement).** Read `emails/emails.md` and
  `emails/_property_facts.json` and write `master_candidates.json` in the working directory:
  ```json
  {"title": "...", "rank_basis": "distance to the client pin",
   "brief": {"size_min": 120000, "size_max": 400000},
   "rank": ["kato:6267947", "email:packington", "..."],
   "duplicate_groups": {"D1": {"status": "SAME BUILDING, two agents",
                               "note": "JLL listing carries 4 PDFs, LSH listing 1 - keep JLL.",
                               "members": ["kato:6268030", "kato:6277087"]}},
   "rows": [{"row_id": "email:packington", "property": "Packington Hill",
             "source_type": "Broker email", "source": "Email: Re Nottingham req (11), C&W",
             "address": "Pritchard Drive, Kegworth", "postcode": "DE74 2DF",
             "lat": 52.833, "lon": -1.283, "size_from": 140000, "size_to": 140000,
             "tenure": "To Let", "rent": "GBP10.50 psf", "availability": "U/C Q2 2027",
             "planning": "Consented", "agent": "Jai Raizada, C&W", "agent_email": "...",
             "notes": "15m eaves, 17 dock, 50m yard.",
             "files": ["uploads/Packington Hill Brochure.pdf"]}]}
  ```
  `rows` carries **only what is NOT already a Kato property**: every email-only option and every
  option whose sole source is an uploaded file. The Kato rows are read off disk. Row ids are
  yours to choose (`email:<slug>`, `file:<slug>`); Kato rows are always `kato:<match_id>`.
  `duplicate_groups` is your adjudication and it wins over the automatic sweep. Fill only the
  fields the source actually states; blanks stay blank and are never invented.
  **Running the build with no candidates file gives you the Kato rows alone**, which looks
  complete and is not. It warns, loudly. Do not ship that to the user.
- **2.5b. Build the workbook**: `python "%HELP%\master_list_build.py" --config run.yaml`
  Writes `Master List.xlsx` (three tabs: **Master list**, **Duplicate check**, **Unmatched
  files**) and `master_list_manifest.json`. On top of your groups it runs a blunt postal-code
  sweep to catch what you missed, labelled `(auto)` and with its looseness stated in the note.
  Re-runnable: existing Include? and Run notes are carried forward by the hidden Row ID, so a
  second email export does not cost the user their forty decisions. `--fresh` discards them.
  The **Brochure?** column is pre-formatted before the sheet is handed over: real conditional
  formatting paints any value that is not a flat `Yes` red with bold black text, so a broker
  scanning the sheet spots a missing brochure at a glance instead of reading 28 rows of detail.
  `Link only` is painted the same red as `No` on purpose: a URL nobody downloaded is not a
  document the run holds, and it is the exact case step 7a refuses as an unevidenced row. Only
  `Yes` is left in the normal row styling. The rule lives on the Brochure? cell alone, is keyed
  off the cell's own value rather than row position, and so survives the user sorting, filtering
  or re-ranking the sheet. Do not restate it as a static fill; a footnote under the table
  explains what the red means.
- **2.5c. STOP AND WAIT. Give the user the one path and nothing else.** They set **Include?** to
  **Yes or No** on every row and write anything the run must know in **Your Run notes for the AI**
  ("split this unit into three cards", "run but without rent", "take the spec from the brochure,
  not the email"). Do not fill the column in for them, do not infer it from the duplicate groups
  you just wrote, and do not proceed on a partly answered sheet. This is the only point in the run
  where the user decides scope.
- **2.5d. Read it back**: `python "%HELP%\master_list_read.py" --config run.yaml`
  Writes `master_list.json`, the file every later stage obeys, and **materialises a property
  folder for each included option that had none** (email-only and upload-only rows, and rows the
  user typed in by hand), copying any named file into its `media/`. Finds the workbook even if the
  user saved it under another name, and says which one it used.
  **It refuses (exit 2) on any row that is not Yes or No**, blanks and deferrals alike, and names
  them. There is no third value on purpose: a deferred answer has to be resolved before the run
  can start in any case, so carrying it would only move the same decision to a point where a log
  reader takes it instead of the person who owns the deliverable. Read the stderr: a row excluded
  inside a loose
  postcode-only group is NOT merged, so any document it held is unused, and it says so.
  Everything downstream inherits this automatically because step 5 filters `_dataset.json` once
  (see its docstring). An excluded row inside an adjudicated duplicate group is merged into the
  survivor rather than deleted, so its brochure still reaches the pipeline, and the automatic
  merge in `common.dedupe_props` switches itself off once a person has answered.

**3. Facts for the model** - `python "%HELP%\make_facts.py" --config run.yaml`
Writes `emails/_property_facts.json` (each property's identifiers + key_points + summary + its
**`kato_messages`**: the Kato in-app broker threads). **Most rents and much of the enrichment live
in `kato_messages`, NOT the Outlook export** - a broker's quote is usually posted on the Kato match
thread. These messages are frequently MULTI-OPTION (one message lists several buildings, each with a
rent, and is attached to several property threads), so map each figure to the RIGHT building by
name/size; never blanket-apply a whole message to every property it is attached to.

**4. Enrich (you)** - read `emails/emails.md` + `emails/_property_facts.json` and write
`enrichment.json` (`{"overrides": {"<property folder>": {rent, spec, outgoings, description, notes}}}`).
- **Read `master_list.json`'s `run_notes` FIRST, honour every one, and ANSWER every one in
  writing.** They are instructions from the person who owns the deliverable, keyed by property
  folder, and nothing in the pipeline acts on them but you: the helpers move the text, they never
  interpret it. "Split this unit into three cards" means three records, "run but without rent"
  means leave the rent null however good the quote is, "take the spec from the brochure" means
  prefer that source over the email.
  **Step 5 REFUSES to build until each noted property carries a `run_note_done` block** in its
  override, because carrying an instruction is not following one and nothing downstream could
  tell the difference:
  ```json
  "05 - Derby 167 - DE24 9FU": {
    "run_note_done": {"note": "Split unit in 3 cards", "status": "done",
                      "action": "Created three records, one per unit on the masterplan, sized
                                 55/56/56k sq ft from page 4 of the brochure."},
    "rent": {...}, "spec": {...}, "description": "..."}
  ```
  `note` is the user's own text quoted back, and it is compared (whitespace and case insensitive)
  against the master list: an acknowledgement of a note they have since changed is rejected, so
  quote it, do not paraphrase it. `status` is `done`, `partial` or `not_possible`; the last two
  are honest answers that SHIP, and the note plus your reason go into the Gaps Report so the user
  meets it there and not in the dashboard. `action` must be a sentence someone can check against
  the deliverable. Never invent a `done` you did not do: `not_possible` with a reason is a
  correct answer, a false tick is the failure this gate exists to catch.
- **You MUST read every property's `kato_messages` (in `_property_facts.json`) as well as
  `emails.md`** - the Kato in-app threads carry most of the rents and a lot of the spec, and a
  property with no email quote very often DOES have a Kato-message quote. Do NOT leave a rent at
  "On application" without first checking that property's `kato_messages` (and the multi-option
  messages attached to OTHER properties, which routinely name this building too).
- Rent = the broker quote, taken in order: email quote → Kato-message quote → Kato structured →
  `"On application"`. Attach a rent only when a broker clearly names that exact building; otherwise
  leave it null. Keep the qualifier ("guiding, exc + VAT", "sublease assignment", "assignment til
  <date>"). Kato messages are multi-option - match each figure to the right building by name/size.
- Specs (clear height, power, loading, yard, parking, floor loading, EPC, BREEAM, availability) come
  from each property's own key_points/amenities/summary. Add outgoings where a broker states them.
- **`description`** (REQUIRED, every property): author a 3-4 sentence dashboard description from that
  property's own `summary` + `description` + `location_text` (in its `_derived.json`/`property.json`).
  Cover what the unit is + headline spec, then the location/connectivity. UK English, no em/en dashes,
  no invention (only what the source states). This is the prose shown on each card's detail modal;
  `build_dataset.py` carries it to `property.json.curated_description` and `patch_canonical.py` injects
  it into the dashboard. (The toolkit's tracker path cannot carry a description, so without this the
  cards show none.)

**5. Assemble** - `python "%HELP%\build_dataset.py" --config run.yaml`
Merges enrichment + Kato data + media into `properties/<folder>/property.json`, `_dataset.json`,
`_gaps.json`. **This is where the master list bites**, and the only place it does: excluded rows
are dropped here, so the tracker, the photo injection, the canonical patch, the client Excel and
the dashboard all inherit one decision with no second list to keep in step. It prints what it
dropped and every run note it is carrying, each tagged `[done]`, `[partial]`, `[not_possible]`
or `[UNANSWERED]`.
**It also REFUSES (exit 2) before writing anything if any run note has no `run_note_done` block**
(see step 4), naming each one and why. Fix the enrichment and re-run; only where a note genuinely
needs no action use `--allow-unacknowledged-notes`, which builds and records every unanswered
note in `_gaps.json` instead, and you must then carry them into the Gaps Report yourself.
With no `master_list.json` it behaves exactly as it did before step 2.5 existed.

**6. Client Excel** - `python "%HELP%\build_excel.py" --config run.yaml`
Writes the client workbook (Longlist + For Sale sheets, merged header bands, links shown as "link").

**7. CBRE HTML dashboard** - via the toolkit skill `cbre-il-toolkit:cbre-property-longlist` (invoke it
to resolve its `helpers/` path; run its helpers with `mcp__shell`, absolute paths). Set
`ORS_API_KEY` in the running shell so drive-times are HGV.

> **Two paths, don't mix them.** Both are the toolkit's **skill root** (the dir containing `helpers/`
> and `assets/`), not its `helpers/` dir - so toolkit scripts are `<toolkit>\helpers\<name>.py`.
> `<install>` is the resolved toolkit skill directory - whatever is installed right now, so Kato always
> inherits the newest CBRE chrome; Kato ships **no** dashboard template of its own. `<toolkit>` is the
> per-run **shadow** of it (step 7a.5) and is what every later step uses. Kato writes only to the
> shadow, never to `<install>`.

- **7a.** `python "%HELP%\toolkit_tracker.py" --config run.yaml` writes the pipeline's inputs in
  two places, deliberately:
  - `longlist_inputs/` (the folder the pipeline SCANS): the availability tracker **and every
    property's own source documents**, PDF and PPTX, each named `NN <original stem> - <property
    label>` so that the pipeline's filename-derived clustering puts one property's documents in
    one reader deck and never mixes two properties. The label is routing only; what actually ties
    a document to its row is what the two of them state (scheme name, parties, postal code, area
    with its unit).
  - **The tracker states a WAREHOUSE area or none at all, never the marketed total.** Three
    columns carry area now: `Warehouse area (sq ft)` (mapped to the pipeline's `warehouseArea`,
    filled only from `size.warehouse_sqft`), `Office area (sq ft)`, and
    `Note: marketed total incl. ancillary (sq ft)`, which is deliberately bound to nothing and
    read only into `__meta`. The single old `GLA (sq ft)` column published `size.sqft`, the
    MARKETED TOTAL, into the field a brochure reader fills with the accommodation schedule's
    warehouse-only line. `match._cross_source_forbidden` permanently vetoes any cross-source pair
    whose two warehouse areas differ by more than 15%, and a forbidden pair is never written to
    `match_candidates.json`, never adjudicated and never merged, so the brochure's records formed
    their own cluster and the source-authority answer then dropped it. On a live run that cost
    three of twenty-one options every page-cited field, every photo and their site plans (IAMP
    Washington 30.2%, Logicor Spring 89 18.4%, Rugby106 18.0% - offices, plant decks, mezzanines
    and undercrofts are the whole difference). **On a first pass the warehouse column is blank on
    every row**, because Kato quotes one headline size and no split; the step says so in its
    output. Expect MORE grey pairs at exit 10 as a result. That is the point: a blank refuses to
    compare and sends the pair to an adjudicator, which is what the toolkit's own design says
    should happen. It cannot cause an over-merge, because every auto path in
    `_cross_source_auto` needs the developer stated on BOTH sides and this tracker publishes no
    developer column. After step 7h the column carries the warehouse-only figures the pipeline
    established, so a re-run restores the veto's protective value.
  - `longlist_work/project.yaml` (the folder the pipeline READS ITS CONFIG FROM): the config, all
    enrichment on, ORS key baked. **Not** in `longlist_inputs/`, because `.yaml` matches none of
    the pipeline's accepted input types, so a copy there was classified unreadable and shipped in
    the CLIENT-FACING Gaps Report under "Unreadable / skipped input files", advising the reader to
    re-save or unlock a file we generated ourselves. The pipeline reads `<work>/project.yaml` and
    its own intake merges its cluster map into ours rather than overwriting it.

  **It REFUSES (exit 2) when any longlist row has no machine-readable source in the inputs
  folder**, names every such row, and writes neither the tracker nor the config. This is the guard
  against the worst thing this skill has shipped: with no document for a property the pipeline
  dispatches zero document readers for it, so every specification field on its card comes from the
  tracker this very step generated, with no page-cited evidence behind any value. Nothing fails and
  every gate passes, so the run is silently wrong rather than late. Fix it by putting the missing
  document in that property's folder. **Expect this to fire on options the user accepted off the
  master list that exist only as a line in an email**: there is no brochure to read for them and
  there may never be one, which is exactly the case the refusal is meant to surface rather than
  paper over. Ask the user for the document, or accept the flag and carry those rows into the
  Gaps Report. Only when there genuinely is none, re-run with
  `--allow-unevidenced-rows`: it ships and records the affected rows in
  `longlist_work/kato_unevidenced_rows.json`, and you must then carry them into the Gaps Report
  yourself. `--include-sheets` also copies per-property spreadsheets, but each one becomes a
  SEPARATE tracker for the pipeline (one extra exit-3 column-map round-trip per file, and its rows
  merge in as further properties), so use it only where a sheet is a property's only source.
- **7a.5. Shadow the toolkit** - `python "%HELP%\toolkit_shadow.py" --source "<install>" --work <work>`
  → prints `<work>\toolkit`, which is `<toolkit>` for the rest of step 7. Copies the installed
  toolkit (~28 MB, ~1 s; skips `evals/`, `docs/`, hardlinks `vendor/`) so step 7e.5 can patch the
  template without touching the install. The toolkit derives its `SKILL_ROOT` from `__file__`, so
  the shadow is self-contained - template, VERSION, integrity manifest, i18n, datasets and gates all
  resolve inside it. Rebuilt fresh each run, so a toolkit update is picked up automatically; pass
  `--keep` to reuse the existing shadow when resuming. Runtime caches are unaffected (the toolkit
  writes `geocode_cache.json` / `poi_osm_cache.json` / `osrm_cache.json` / `regions_cache.json` into
  the **work** dir, not the skill dir). It warns if `<install>` is already `-kato` tagged, which means
  an older Kato run patched it in place - reinstall or update the toolkit to get pristine chrome back.
  **It also asserts the minimum wrapped-toolkit version** (`MIN_TOOLKIT_VERSION`, currently `v40`)
  and REFUSES an older or unreadable one, with the remedy, before copying anything. The wrapper owns
  that floor and the toolkit owns no ceiling, so there is exactly one place to change it. The
  comparison is numeric, not textual, so a future `v100` is correctly newer than `v40`; the `-kato`
  suffix a previous run may have stamped is reported but never compared, so re-shadowing the
  wrapper's own output still passes.
- **7b.** Run the toolkit spine on that folder:
  `python "<toolkit>\helpers\run.py" --folder <work>\longlist_inputs --work <work>\longlist_work --client "<client>" --geocode --pois --osrm --regions`.
  It builds `canonical.json` and passes its data gates. (Drive-times report `driving-hgv`.)

  **The Stage 0 setup gate (toolkit v45+) is already cleared for you.** v45's `run.py` refuses to
  read anything until a human has answered its five setup questions and `setup.confirmed: true` is in
  `project.yaml`, on the correct premise that every value its own scaffold writes is a guess. Under
  this wrapper they are not guesses: client name, enrichment flags, ORS key, email source and
  language all come from the `run.yaml` the user filled in, and Kato has already parsed the Outlook
  export itself, so `inputs.emails.source: none` is the answer rather than an omission. Step 7a
  therefore writes `setup.confirmed: true`, `setup.confirmed_by` and `clarify.mode: interactive`
  (the last of those is a policy constant the toolkit fixed on 2026-09-19, not an answer: the ask
  mode was its sixth question until then and is no longer asked at all).
  **Do not present the toolkit's five-question setup form**: it asks the same person the same
  questions twice in one run. If a future toolkit adds a question the wrapper does not answer,
  add it to `toolkit_tracker.py` rather than clearing the gate by hand.

  **Two different round-trip exits can stop this step, and both are normal.** They ask different
  questions and are answered with different files, so read which one you got before acting.
  - **Exit 3, the tracker column map.** "What do this spreadsheet's column headers mean?" It runs
    before any record exists and its answer is a schema map, never a value. Write the map plus its
    blind-check file where the manifest names them, then re-run the same command.
  - **Exit 10, the cross-source match adjudication.** "Are these two extracted records the same
    building, and which of two disagreeing values is right?" **This is EXPECTED, and it is a direct
    consequence of step 7a now shipping each property's source documents.** The exit can only fire
    when the corpus holds more than one record source; with a tracker alone it could not fire at
    all, which is why this flow used to document only exit 3. Getting it does not mean anything
    has broken.
    Answer it by writing a verdict for **every** pair id listed in
    `longlist_work/match_candidates.json` into `match_decisions.json`, plus `field_decisions.json`
    for any value conflict, plus the separate blind `match_verify.json`; then re-run the same
    command (`--from repairs` is rejected here, it needs a full pass). Read the candidate list
    rather than approving it blind: two records stating DIFFERENT postal codes can never be merged
    whatever verdict you give, so that pair ships as two cards for one building, and the fix is the
    source data, not the verdict.
    The same is true of a >15% warehouse-area gap, and that one is invisible here: a forbidden
    pair is NOT in the candidate list, so a missing pair is the thing to look for. `gate_runner.py
    input-accounting` (step 7e) now BLOCKS when an option excluded by the source-authority answer
    carries the same label as a shipped card, which is what that failure looks like from the
    other end.
    **Expect a `country` value conflict on most properties, and do not read it as a data problem.**
    Our per-property cluster labels cannot resolve in the pipeline's city-to-country index (they are
    routing strings, deliberately unique per property), so every brochure reader is handed the
    unknown-country sentinel and writes it into its record, where it disagrees with the country our
    tracker states. Answer it however you like: step 7c.5 repairs the field afterwards from a single
    market constant either way.
  - **Exit 13** follows if a verdict is `unsure`: the pipeline escalates that pair to a blocking
    question for the user in `answers.json`. Put it to them and write their answer. Do not guess it.
  - **Exit 17, the toolkit's own master list, must NEVER fire on a Kato run.** Scope was settled at
    step 2.5, on our workbook, by the same operator; step 7a therefore writes
    `master_list: {mode: external, confirmed_by: ...}` into `project.yaml` and the toolkit skips its
    stop. If you get exit 17, do NOT build or answer the toolkit's sheet - that would ask the
    operator to strike off the same options a second time. Check that `project.yaml` in
    `longlist_work` carries that `master_list:` block (an older `toolkit_tracker.py`, or a
    hand-edited project.yaml, is the cause) and re-run the same command.
- **7c.** `python "%HELP%\inject_photos.py" --config run.yaml` - put our photos into `canonical.json`.
- **7c.5. Patch canonical (our data the toolkit drops)** - `python "%HELP%\patch_canonical.py" --config run.yaml`.
  Injects, per property, straight from `property.json`: the curated **description**, the **landlord**
  (real name / "Confidential"), the **brochure / video / website** URLs, a **Street View** URL (from
  the geocoded street-view pano/coords), and **EPC**. The toolkit has ONE green-cert field (`breeam`)
  and no tracker path to description/links, so these are dropped in its column-mapping step - we own
  `property.json`, so we inject them here (same pattern as `inject_photos.py`). `developer` is left
  `tbd` on purpose (the source rarely names one).
  It also repairs **`country`**, which arrives as the pipeline's unknown sentinel on every card (the
  cause is in 7b above): left alone it shows as that sentinel in every detail modal, kills the flag
  icon, and makes the hero KPI strip count zero countries. Only the sentinel is overwritten; a real
  two-letter code the pipeline read off a page is kept and named on stderr, so check stderr if one
  appears.
- **7d. Site plans (vision).** `python "%HELP%\brochure_montages.py" --config run.yaml` → look at each
  `plan_qa/broch_NN.png` and pick the site-plan page for each property (0-based global page label);
  write `decisions.json` (`{"<order>": <page>|null}`, null where the brochure has none) →
  `python "%HELP%\bind_site_plans.py" --config run.yaml --decisions decisions.json`.
- **7e. QA.** `python "%HELP%\qa_montages.py" --config run.yaml` → look at `plans_qa_*.png` (every bound
  plan is a real plan) and `heroes_qa_*.png` (right photo on the right property); fix any via 7d.
- **7e.5. Patch the toolkit template (card/modal presentation)** - `python "%HELP%\patch_template.py" --toolkit "<toolkit>"`
  (the SHADOW from step 7a.5 - the same dir whose `build_dashboard.py` you run below, never `<install>`;
  the helper refuses any target that is not a shadow, so this cannot go wrong silently).
  Applies Kato's idempotent card/modal tweaks to `<toolkit>\assets\dashboard_template.html` and
  re-versions it (rewrites `assets\VERSION` chrome_sha256 so the toolkit's own template-SHA + byte-
  equality gates stay green). What it changes: card 4th cell `Early access`→`Electricity`; card eyebrow
  `developer · motorway` (both tbd → "TBD · TBD") → developer-or-city (no dangling separator); drop the
  hero **Developers** KPI tile when ≤1 distinct developer; add **Brochure / Video / Website / Street
  View** links to the modal top row; and hide the bare `motorway`/`status`/`breeam`/`early-access`
  "tbd" chips there. Two patches are RETIRED because the template does the job natively: the
  `DENY_FIELDS` guard (there is no auto "Additional Details" section at all) and the separate modal EPC
  row (v36+ renders a combined BREEAM/EPC row via `certStr(p)`). Retired patches are not deleted - each
  keeps a premise re-asserted every run, so a toolkit regression bringing the old condition back fails
  loudly instead of quietly shipping a dashboard missing the fix.
  **Verified against template v45:** 10 active patches, 4 retired premises, all holding. P3 (card
  eyebrow) and P13 (modal developer token) were RETIRED at v45, which does both jobs natively: the
  eyebrow now renders through `partyLine(p)` (landlord, else developer, else a blank landlord line),
  so the `TBD · TBD` dangling separator P3 existed to fix cannot occur, and the modal header now
  carries its own `isTbd(p.developer)` guard inline. They join P7 and P12 as premises re-asserted
  every run rather than deleted, so a regression reinstating the old condition fails loudly. The
  remaining 10 are wrapper-specific presentation choices rather than defect fixes, which is why
  native toolkit work only occasionally converges on them: when it does, retire the patch, do not
  force the anchor. Idempotent + version-agnostic: re-run
  each session (the shadow is rebuilt pristine from the install every run); it reports EVERY moved anchor
  in one run and writes nothing rather than shipping unpatched. Use `--dry-run` to check a new toolkit
  version without touching it - that one is safe to point straight at `<install>`.
  **NEVER hand-edit `built.html`** (the byte-equality gate rejects it) - the patch goes in the template.
- **7f. Build + deliver** - `python "<toolkit>\helpers\build_dashboard.py" <work>\longlist_work\canonical.json --out <work>\longlist_work\built.html`
  then the toolkit `deliver.py` (dashboard, Source Ledger, Gaps Report, Longlist xlsx).
- **7g. Reviewer gates: ONE ROUND, NEVER TWO.** Run the toolkit's isolated reviewer gates
  (G-honesty, G-trace, G-images, G-visual, G-enrich) per its `reference/gates.md`, then its
  `final_gate.py`.
  **The required shape, for every run: spawn the independent review agents ONCE, implement every
  blocking finding plus any advisory that is cheap and material, then deliver. A second review round
  is never correct.** Re-reviewing after the fixes buys nothing and costs a full cycle: the agents
  re-read the same deliverable and produce a fresh crop of advisories, which is indistinguishable
  from progress and has no termination condition.
  There is deliberately no threshold here for which advisories to fix, and none will be written down.
  An advisory that is one edit and changes what a reader concludes gets fixed; the rest ship
  disclosed in the Gaps Report. That judgement is the operator's, and encoding it as a rule would
  either wave through something material or mandate work that changes nothing.

**7h. REFRESH THE CLIENT EXCEL - ALWAYS, AFTER THE PIPELINE, NEVER BEFORE**
`python "%HELP%\sync_from_canonical.py" --config run.yaml` then
`python "%HELP%\build_excel.py" --config run.yaml`

**The client workbook from step 6 is out of date the moment the toolkit stage corrects anything,
and it stays that way silently.** Step 6 writes it from `_dataset.json`, which is Kato plus your
enrichment. Everything step 7 then establishes lands in the toolkit's `canonical.json` and NOWHERE
ELSE: a brochure's warehouse-only area against a gross total, an office line the Kato listing never
carried, an EPC or BREEAM rating read off a page, every `repairs.json` correction, every adjudicated
value conflict, every QA fix. On the run this was written for, the step-6 workbook's Warehouse column
fell back to the gross total on five properties, its Office column was empty on all twenty-one, and
its EPC column read `tbd` for four properties whose own brochures state a rating. The dashboard was
right and the spreadsheet beside it was wrong, which is worse than both being wrong: nothing on the
face of either tells a broker which to trust, and the spreadsheet is the one they paste into an email.

So the client Excel is **rebuilt at the end of every run, after 7g, and step 6's output is an
intermediate.** Keeping step 6 where it is buys nothing downstream: 7a builds its tracker from
`_dataset.json`, not from the workbook, and nothing else reads the workbook at all. It stays only
so a run abandoned before step 7 still leaves a spreadsheet on disk. If you are going through to
step 7, step 6 is dead work and 7h is the one that counts. Note also that the workbook is now built
AFTER the 7g reviewer gates, which makes it the one deliverable no gate inspects: the values in it
are the gated ones, but its own formatting and column choices are not reviewed by anything.
`sync_from_canonical.py` pairs each canonical property to our record with the same matcher
`inject_photos` and `patch_canonical` use, so a pairing failure REFUSES rather than skipping, and
folds back a fixed, narrow set: warehouse and office areas, EPC, BREEAM, curated description. It
deliberately does **not** touch the headline `size.sqft`, because warehouse + office under-sums any
building with a plant deck, undercroft or mezzanine (it pulled Rugby106 from its marketed 106,645
sq ft to 96,763 by dropping a 9,882 sq ft mezzanine), and it never touches rent, agent or tenure,
where our data is richer than the pipeline's. `--dry-run` shows the diff first.

**8. Finalise - ALWAYS LAST, NEVER SKIP** - `python "%HELP%\finalize_run.py" --config run.yaml`
Collects every client-facing file into `OUTPUT/`, writes a plain-English `START-HERE.md`, and deletes
junk (`__pycache__`, `.pyc`, stray temp files) from a fixed allowlist. It touches nothing a re-run or an
audit needs, and is idempotent. **Do not tell the user the run is finished until this has run and you
have given them the one path to open.** Use `--dry-run` to preview.
**One deliberate exception to the allowlist:** where a deliverable arriving from a re-run collides
with a file of the same name in `OUTPUT/`, the OLDER of the two is replaced, so re-running converges
on one copy of each rather than leaving `<name>` beside `<name> (newer)` for the user to date-compare.
A copy in `OUTPUT/` that is NEWER than the incoming build is treated as one the user edited and is
kept, with the incoming file taking the suffix instead.

## Outputs (working directory)
- `OUTPUT/` - **the only folder the user needs**: dashboard, spreadsheet, Gaps Report, Source Ledger.
- `START-HERE.md` - what to open, what to send, what to ignore. Written by step 8.
- `Master List.xlsx`: the inventory the user answered at step 2.5. **Internal, never sent to a
  client**, and deliberately left in the working directory rather than moved to `OUTPUT/`: it is
  the record of what was included and why, and the file to re-open when the run is refreshed.
- `master_candidates.json` (your input to 2.5), `master_list_manifest.json` (what was built),
  `master_list.json` (what the user decided; read by step 5 and by you at step 4).
- `properties/<NN - Name - Postcode>/` - `_raw.json`, `_derived.json`, `property.json`, `media/`.
  Folders materialised at step 2.5d have no `_raw.json` and carry `_derived.json._origin` instead.
- `properties/_dataset.json`, `_index.json`, `_gaps.json`; `emails/`; `enrichment.json`.
- `uploads/`: optional, where the user's extra brochures and sheets go. Loose files in the
  working directory root are picked up too; either way anything no row claims is listed on the
  workbook's **Unmatched files** tab, because a supplied file that nothing reads must be visible.
- `longlist_work/` - toolkit working data (the deliverables are moved out of it by step 8).

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
- **Finish with step 8, then say one sentence naming one path** - the `OUTPUT/` folder. Do not hand back
  a list of six paths and let the user work out which matters.
- **Never present a gap as a success.** If emails failed to parse, a rent is unconfirmed, or a site plan
  is missing, it goes in the Gaps Report and in what you tell the user.
