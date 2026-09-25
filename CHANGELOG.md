# Changelog

All notable changes to the **CBRE I&L Toolkit** (`cbre-il`) plugin and its
marketplace are recorded here. Versions follow [Semantic Versioning](https://semver.org):
`MAJOR.MINOR.PATCH`. The version in `plugin.json` is the one Claude Code uses to
decide whether an installed plugin is out of date, so it is bumped on every release.

How to update to the latest version is in the [README](./README.md#updating).

## [1.19.0] — 2026-09-25

Marketplace 1.19.0: **CBRE I&L Toolkit 1.14.0** gains an eighth skill. UK I&L Toolkit unchanged
at 1.7.0.

### Added
- **`cbre-engagement-letter` — an engagement or mandate letter in the CBRE house layout.**
  Cover, letter page, instruction, services, team, remuneration, exclusivity, term, a
  jurisdiction-specific terms clause, an approval block and the Thank you page, the same every
  time, with the content adapted to the requirement. It covers occupier search, lease,
  purchase, build-to-suit, sale and leaseback and capital markets mandates **anywhere in
  Europe**, which is why it lives in this plugin rather than the UK one.

  It **asks before it drafts**, in one message, and always asks three things it treats as easy
  to get wrong: the **jurisdiction** (which CBRE entity signs — the search geography is not the
  answer, since one entity can contract a five-country search), the **fee basis and abortive
  fee** (it never picks a structure or a number), and whether the letter is **signable or
  scope-only**. Contracting entities and terms regimes come from a per-country table; a
  country not in it is asked about rather than guessed. Anything unknown becomes a yellow
  placeholder, so the user is never blocked, and it never invents an entity, address, fee,
  date or job title. It can offer to search the user's email for the team, but only searches
  once they agree.

  **Revisions are where it is strictest**, because rebuilding a letter the user has already
  edited silently throws their edits away. The user's own latest file is always the base;
  changes are made in place with `edit_docx.py`, where every edit must match exactly one
  paragraph or the script stops; and `compare_text.py` lists every difference before anything
  is delivered. Every delivered file carries a new version number, so an old file card in the
  chat can never be mistaken for the current letter.

  The update notifier was not in the upload; it has been added at `scripts/version_check.py`
  and wired into the start of the workflow.

  **Verified on install, not just parsed:** the bundled example built into a valid letter and
  listed its open placeholders; rendered to **8 pages** matching the documented structure,
  with **no em or en dashes** (the skill's own rule); a one-line edit changed exactly one
  paragraph and the comparison reported exactly **1 difference**; and an edit that matched
  nothing was **refused** without writing a file. Checked for personal data with particular
  care, since engagement letters name clients and signatories: the example is fully
  anonymised (`Example Client`, every name and entity a placeholder), the template's hidden
  document properties name `CBRE` rather than a person, and the only real entities anywhere
  are CBRE's own public legal entities.

## [1.18.1] — 2026-09-24

Marketplace 1.18.1: **CBRE I&L Toolkit 1.13.1**. UK I&L Toolkit unchanged at 1.7.0.

### Added
- **A regression guard for the `city_major` schema gap fixed in 1.18.0**, in
  `evals/major_cities_test.py`. It reads the schema's list of allowed place types **directly
  from the file** rather than through `jsonschema`, and checks that every type the pipeline
  emits is on it. That closes the hole that let the original bug through: without
  `jsonschema`, `validate-data` falls back to a check that never looks at that list, so every
  eval passed on a machine without the package and the run failed everywhere else. Where
  `jsonschema` *is* installed, the guard also runs the real validator on the result.

  Verified against the bug itself, not just against the fix: with `city_major` taken back
  out of the schema, the guard **fails with and without `jsonschema`**, naming the offending
  type (`not allowed ['city_major']`); with the fix in place it passes both ways. A machine
  without `jsonschema` will now catch this class of mistake before it ships.

No behaviour change. This release adds one test and nothing else: after the example-name fix
was re-applied, `master_list.py` and the integrity manifest are byte-identical to 1.13.0, and
the schema already carried the fix.

## [1.18.0] — 2026-09-24

Marketplace 1.18.0: **CBRE I&L Toolkit 1.13.0** — dashboard template v45 → **v46**. UK I&L
Toolkit unchanged at 1.7.0.

### Changed — property longlist, template v46
- **KPI figures no longer wrap their tile.** The hero value is held on one line and a range
  now picks its suffix at each end, so a 25,000 to 1,000,000 range reads `25k - 1.0m` instead
  of `25 - 1000k` spilling out of the box.
- **Filter labels wrap instead of being cut short**, so "Min Warehouse Area" is readable at
  1440px.
- **The photo count on a card moves bottom-left**, so it no longer sits on top of the Compare
  tick-box. The modal hero keeps it bottom-right.
- **A stated annual total rent now has somewhere to go.** A new `quotingRentTotal` field is the
  fallback for Total annual rent — used **only** when no area × rate total can be computed. It
  ships verbatim, with no basis line, no monthly figure and no back-calculated rate, because a
  figure the source never broke down should not be broken down for it.
- **A property's nearest 400k+ city is never crowded out** of the "Major cities" group by
  smaller towns that happen to be closer.

### Fixed
- **v46 as uploaded would have blocked every run near a major city, for anyone with
  `jsonschema` installed.** The new major-city feature writes points of interest with type
  `city_major`, and the dashboard builder was updated to show them — but the canonical
  schema's list of allowed types was not, so `validate-data` rejected the data its own
  pipeline had just written (`'city_major' is not one of ['port', 'rail', 'air', 'border',
  'city']`) and the run stopped at exit 5. Three of the skill's own simulators caught it:
  `conformance_sim_test`, `master_list_external_test` and `cowork_sim`.

  **Why it wasn't visible upstream:** without `jsonschema`, `validate-data` falls back to a
  reduced check that never enforces that list. I confirmed all three simulators pass with it
  missing and fail with it present — so an author without the package gets a green suite, and
  a user with it gets a hard stop. It mattered more in this release than it would have before,
  because the new dependency report in `preflight` now tells users to install `jsonschema`.

  Fixed by adding `city_major` to the schema's allowed types, which is what the rest of the
  code already assumed: `enrich` writes it deliberately as its own type, `build_dashboard`
  admits it, and it has its own search radius. All three simulators now pass **with and
  without** `jsonschema`.

### Added
- Four evals: `kpi_format_test`, `major_cities_test`, `stated_total_rent_test`, and
  `preflight_deps_test` for the new dependency report in `preflight`, which now names any
  missing Python package and gives the exact install command.

### Worth knowing
- **`open_field_scalar_test` was never a code bug.** Listed here for many releases as one of
  three long-standing failures, it passes on this release **and** the previous one once
  `jsonschema` is installed. It was a missing dependency the whole time. That leaves two
  genuinely failing evals, `extract_test` and `plan_reject_test`, both unchanged.
- The author's integrity manifest now matches the files as shipped — the Windows line-ending
  problem that forced a regeneration on every earlier release is fixed at source.

### Security
- Re-applied the example-name fix (`Pearson, Sam` → `Hale, Robin`) and preserved
  `vendor/README.md` again; both were missing from the upload.

## [1.17.0] — 2026-09-24

Marketplace 1.17.0: **UK I&L Toolkit 1.7.0** gains a fourth skill. CBRE I&L Toolkit unchanged
at 1.12.3.

### Added
- **`cbre-evergreen-portfolio` — a CBRE EverGreen export becomes one portable HTML file.** It
  pairs a **scroll storyline** with an **interactive dashboard** in a single document, built
  and reviewed by agent committees, for UK occupier portfolios. The output opens by
  double-click: the CBRE fonts, Leaflet and a vector basemap are all inlined, so there is no
  server and no network call (street tiles load only if a reader zooms right in).

  The engineering worth noting is the collision handling — the storyline and dashboard
  stylesheets clash on dozens of selectors (`:root`, `body`, `*`, `svg`, `table`), so each is
  scoped under its own view root by `cssscope.py` rather than being hand-deconflicted. The
  boundary data is Eurostat GISCO, credited in the file it ships in. `assemble.py` takes a
  report directory and emits the single file; `--stub-missing` lets an author self-check a
  build before the storyline and dashboard are written.

  Its process discipline matches the rest of the toolkit: **exactly one QA pass and one fix
  pass, never another QA round**, with a separate post-fix smoke check that loads the built
  file at desktop and mobile widths and fails on any console error.

  The update notifier was not in the upload; it has been added at `scripts/version_check.py`,
  targeting the UK plugin, and wired into the top of "Run it".

  Verified on install: all 37 files land, every embedded font and the vendored Leaflet are
  byte-intact after line-ending normalisation, every Python and JavaScript file parses, and a
  real `--stub-missing` build produced a **1.27 MB** self-contained page carrying the embedded
  fonts, Leaflet, CBRE green and the boundary credit, with no external asset reference.

## [1.16.3] — 2026-09-21

Marketplace 1.16.3: **CBRE I&L Toolkit 1.12.3**. UK I&L Toolkit unchanged at 1.6.2.

### Fixed
- **An answered Master List no longer costs 37 seconds of first-page reads on every pass.**
  The check for "has the user answered the sheet?" needs the inputs hash, and that hash was
  falling out of the enumeration — so the enumeration ran first, every time, reading the first
  page of every deck to name its row and fill its postcode and size. On a live 23-deck run
  that was 37 seconds a pass, paid even when the sheet had been answered hours earlier.

  Under a Cowork sandbox capped near 45 seconds that is not a slow run, it is a **failed** one:
  a resumed stage costing 37 is the difference between a pass that reaches the final gate and
  one killed short of it. A new `expected_hash` computes the same digest from the row ids
  alone — a record's is its provenance locator, a cluster's is a digest of its file names,
  neither of which needs a page read — so the spine asks "is it answered?" first and only
  enumerates for a sheet that is genuinely unanswered or whose inputs set has changed.

  The equality is pinned rather than assumed: the eval asserts `expected_hash` digests exactly
  the id set `build_auto` digests, with records and clusters, with each alone, and that adding
  a deck still changes it so an answered sheet is correctly re-opened. The code carries the
  matching warning — if the cluster enumeration ever grows a new reason to skip a cluster, it
  has to be mirrored in `expected_hash`.

### Security
- Re-applied the example-name fix for the third release running (`Pearson, Sam` → `Hale,
  Robin`), and preserved `vendor/README.md`, the PyMuPDF provenance note, for the fourth.

## [1.16.2] — 2026-09-21

Marketplace 1.16.2: **CBRE I&L Toolkit 1.12.2**. UK I&L Toolkit unchanged at 1.6.2.

### Fixed
- **The input-accounting gate cried wolf at an email that carried brochures.** A live corpus
  of 16 broker emails and 22 brochures blocked with eleven copies of *"contributed NOTHING …
  a whole source has silently vanished"* on a run where every brochure was read and shipped.
  The cause: a saved attachment enters the ledger under its **own** filename, never its
  carrier's, so an email whose body held no quotable property data fell through every bucket
  into the one that blocks.

  The fix keeps the gate's teeth. A seventh bucket, `attachment_carrier`, credits the email
  from the `.from_email.json` sidecars — but **only when every saved attachment is itself
  accounted for**, so the genuine loss (a declared attachment nothing saved) still blocks.
  The new `evals/input_accounting_attachment_carrier_test.py` asserts the must-fire cases as
  hard as the must-not-fire ones.

  Its sibling half: the exit-17 sub-agent contract never asked for `source_files` on an
  email-prose row, so the existing exemption could not fire either. The dispatch prompt now
  asks for it. The author's own note on the lesson is worth repeating — *when a gate's
  exemption keys on a field, check that something actually populates that field on every path
  into it* — as is the reason it mattered: **a gate that reds a correct run gets switched
  off.**

### Security
- Re-applied the example-name fix from 1.16.1, which this upload reverted: a real-looking
  broker name had returned to both halves of a comment in `master_list.py`. It reads
  `Hale, Robin` / `Robin Hale` again.
- `vendor/README.md`, the PyMuPDF provenance note, was absent from this upload for the third
  release running and has again been preserved rather than deleted.

## [1.16.1] — 2026-09-19

Marketplace 1.16.1: **CBRE I&L Toolkit 1.12.1**. UK I&L Toolkit unchanged at 1.6.2.

### Security
- **The Master List's example broker names are now a consistent invented set** — `Alex Morgan
  (Cushman & Wakefield)`, `Sam Fletcher (Savills)`, `Priya Nair (C&W)`, `Jordan Blake`, `Casey
  Reid`, across the reference, the dispatch prompt, two helpers and an eval. Real firms, made-up
  people. The eval's fixture sender address became `fixture@savills.com` rather than a
  real-looking personal address.
- One example was renamed only on one side of the sentence, which left a real-looking name in
  the quoted text and made the comment contradict itself (it showed `Pearson, Sam` and then
  said it should read `Robin Hale`). Both halves now read `Hale, Robin` / `Robin Hale`, so the
  comment demonstrates the surname flip it is actually describing.

No behaviour change in this release — the code paths, the workbook and the gates are identical
to 1.12.0.

## [1.16.0] — 2026-09-19

Marketplace 1.16.0: **CBRE I&L Toolkit 1.12.0** and **UK I&L Toolkit 1.6.2**. The Kato upload
for this release was a stale August snapshot whose only difference was a reverted update
notice, so none of it was applied; the UK bump carries one change only, the broker-name
replacement below.

### Fixed — property longlist Master List
- **A pre-answered sheet could sail through the read-back with nobody having decided
  anything.** The live run came back with all 62 rows already filled in, because another
  column had been copied across into `Include?`. That defeats the entire point of the stop.
  `Include?` now has exactly one route in — `carry_forward`, which re-imports answers from a
  workbook a human has actually had in front of them, keyed on the hidden Row ID. Nothing else
  may write it: not the spine, not the candidates files, not the orchestrator, not the
  sub-agent.
- **Emails are no longer rows on the master list.** The earlier design put one row per `.msg`
  named after the subject, which asked the user to include or exclude *a source* — a question
  with no correct answer — and forced the sub-agent to invent "this message mentions these
  buildings" duplicate groups to explain itself. Messages now have their own **Emails** tab
  with sender, organisation, date, cleaned subject, attachments and the rows that came out of
  them; one that produced neither is flagged there as "nothing extracted".
- **A duplicate group now means one physical building reached by more than one source, and
  nothing else.** The builder normalises every status onto that, so the looser readings cannot
  be expressed. Group members are pulled onto adjacent lines, because the comparison is only
  cheap when the two rows sit next to each other.
- **A property is named from the deck's own first page**, with the filename as the last resort
  and marked `(from filename)` when it is used. Town is document-derived or blank, never a
  filename: a blank town is a question a colleague will ask, and a wrong one is a fact they
  will act on.
- **Source reads as provenance, not as a path** — "Brochure, attached to email from Jane Roe
  (Savills), 7 Sep 2026", "Brochure, input folder". Filenames are provenance for the run and
  live in the manifest; they are not an answer to "who told us about this".

### Security
- **Replaced five real-looking broker names carried over from a live run** — in the master-list
  reference, its dispatch prompt, two helpers, an eval, and the Kato skill card. They are now
  placeholder people at the same real agencies (`John Doe (Cushman & Wakefield)`, `Jane Roe
  (Savills)`, `Alex Doe (C&W)`, `Sam Roe`), matching the convention already used in the expense
  claim. Real firms are fine; named individuals in a public repository are not.
- `vendor/README.md`, the PyMuPDF provenance note added in 1.15.1, was absent from this upload
  and has been preserved rather than deleted.

## [1.15.2] — 2026-09-19

Marketplace 1.15.2: **CBRE I&L Toolkit 1.11.2**. UK I&L Toolkit unchanged at 1.6.1.

### Fixed
- **The last two missing skills: a `description` over 1024 characters stops a skill loading.**
  On 1.11.1, with the YAML fault from 1.14.1 already fixed, the plugin still listed **5 skills
  instead of 7** — `cbre-il-occupier-brief` and `cbre-site-tour-app` were still absent. With
  the YAML problem out of the way the pattern was unambiguous: every skill at or below **993**
  characters loaded, and both skills above **1024** did not.

  This is a measured limit, not a documented one. The published guidance says the description
  is *truncated* in the skill listing at 1,536 characters, which is a different thing and is
  why the length was dismissed the first time round — a mistake, since the two faults were
  masking each other. Both descriptions are now well under: occupier brief 1,208 → **892**,
  site tour app 1,157 → **928**. Every trigger phrase is kept; what came out is mechanism
  detail that belongs in the body of `SKILL.md` and reads better there.

### Changed
- **`tools/validate_skills.py` now enforces the length cap too**, failing above 1024 and
  warning above 950 so a description that grows by a sentence in a later release cannot
  quietly cross it. Two skills are already in the warning band — property longlist at 993 (31
  characters of headroom) and warehouse network mapper at 983 — so their descriptions need
  trimming, not extending, at the next revision. The README's maintainer section records both
  faults.

## [1.15.1] — 2026-09-19

Marketplace 1.15.1: **CBRE I&L Toolkit 1.11.1** and **UK I&L Toolkit 1.6.1**. Both plugins
move. A fix release on both sides — no new or removed files.

### Fixed
- **`cowork_sim` now answers exit 17.** The simulator had no Responder branch for the Master
  List round-trip and aborted on it in 1.15.0. It now plays the human properly: builds the
  workbook, answers the sheet, reads it back, and additionally checks that a **half-answered
  sheet is refused**. The suite converges at round 5, monotonic, idempotent and deterministic.
- Property longlist: fixes across `deliver`, `gate_runner`, `images`, `master_list`, `match`,
  `msg_reader` and `project_properties`, with the matching reference documents.
- Kato longlist: fixes in `build_excel`, `finalize_run`, `msg_reader` and `patch_template`.
- Re-applied the UK update-notice fix that the Kato upload reverted for the second release
  running. It had gone back to naming "CBRE I&L Toolkit" and the CBRE CLI install id while
  reading the UK plugin's own version, so a UK user acting on the nudge would update the wrong
  plugin.

### Security
- **Documented the provenance of the bundled PyMuPDF wheel**, in a new
  `cbre-property-longlist/vendor/README.md`. A security scan reports that this plugin contains
  something it "couldn't be confirmed" — that warning is about the wheel, and it is accurate in
  the literal sense: the wheel is a 25 MB **compiled binary**, so no automated scan can read
  what is inside it. It is not a finding of anything wrong.

  The wheel is the genuine upstream artefact. Its SHA256,
  `857842b4888827bd6155a1131341b2822a7ebe9a8c15a975fd7d490d7a64a30c`, matches byte for byte the
  digest PyPI publishes for `pymupdf-1.27.2.3-cp310-abi3-manylinux_2_28_x86_64.whl`. It has not
  been rebuilt, repacked or modified. The new README records the upstream link, the size, the
  digest and the licence, plus the one-line command to check it, so anybody asked to approve
  this plugin can confirm it themselves rather than take it on trust.

  It is bundled because PDF extraction has to work where PyMuPDF is not installed and cannot be
  installed, which is the ordinary case in Cowork. It is unpacked into a temp directory and
  imported from there, never installed into the system environment.

  **Recorded gap, for the author:** `assets/integrity.json` does not cover `vendor/*.whl` —
  `make_integrity.py` hashes `helpers/*.py`, `prompts/*.md` and a fixed asset list, so
  `preflight.py` reports OK even if the wheel were swapped. The published digest is the only
  check on it today. Adding `vendor/*.whl` to the manifest would close it.

## [1.15.0] — 2026-09-19

Marketplace 1.15.0: **CBRE I&L Toolkit 1.11.0** and **UK I&L Toolkit 1.6.0**. Both plugins
move, so update both.

### Added
- **The Master List — the user decides what the run builds, before a single brochure is read.**
  A new **exit 17** in the property longlist, and step 2.5 in the Kato longlist, sharing the
  same two helpers. The run inventories every candidate option it can see, writes them to
  `Master List.xlsx`, and **stops**. The user marks each row **Yes** or **No** and can leave
  free-text notes for the run. Only the Yes rows reach the deck readers.

  It sits between the cheap reads and the expensive ones on purpose: the sheet is built from
  trackers, emails and brochure clusters, and the brochures are only read afterwards, for the
  options that survived. The run refuses to guess — `master_list_read.py` **exits 2 on any row
  that is not Yes or No and names them**, and the skill is explicit that the orchestrator must
  never fill the column in, never infer it from the duplicate groups, and never proceed on a
  partly answered sheet. This is the one point in the run where scope is decided, and the
  options struck off are named in the Gaps Report rather than silently dropped.

  On the Kato side it closes a real defect: options arrive by three overlapping routes that
  nothing reconciled — the Kato longlist raises one match **per broker**, so the same unit
  arrives two or three times under different agencies; the broker emails re-send options
  already on Kato and name others that are on nobody's Kato; and the user drops in further
  files. The run used to take every Kato match, silently merge whatever shared a postal code
  and an exact floor area, and never see an email-only option at all — the user found out what
  had been decided by reading the finished dashboard. The workbook now carries three tabs
  (Master list, Duplicate check, Unmatched files), the agent's own duplicate adjudication wins
  over a blunt postal-code sweep that is labelled `(auto)` with its looseness stated, and
  re-running carries existing decisions forward by a hidden row id, so a second email export
  does not cost the user their decisions.

- **A saved email folder and a zip are first-class inputs to the property longlist.** A `.zip`
  is unpacked once into `<zipname>_unpacked` beside itself, and a `.msg`/`.eml` has its
  attachments saved under `<yyyy-mm-dd>_<subject>_attachments/`, both inside the inputs folder,
  both idempotent and never escaping it — so a brochure that arrived stapled to an offer email
  is clustered and read on the **same run**, exactly like a file dropped in by hand. Inline
  images (signature logos, `cid:` images, anything under 20 KB) are excluded. The skill now
  says plainly to move the zip and the email folder in **as they are**: unpacking by hand loses
  the `.from_email.json` sidecar and with it the ledger's record of which email carried which
  brochure. Reading the prose stays an LLM step — Python opens the container, the agent reads
  the offer.

- Property longlist: `master_list_test`, `master_list_external_test`, `email_folder_test` and
  `email_attachment_provenance_test`, all passing.

### Known issue
- **`cowork_sim` does not yet answer exit 17.** The simulator's Responder has no branch for the
  new round-trip, so it aborts with its own message: *"UNHANDLED exit 17: extend the Responder
  to cover it (this is a simulator gap, not necessarily a skill bug)."* The spine behaved
  correctly in that run — it stopped at exit 17 with a complete four-step handoff and clean
  input accounting. `conformance_sim_test`, the other scripted-orchestrator check, **was**
  updated for exit 17 and passes, so the exit table still has coverage. The Responder needs
  extending.

## [1.14.1] — 2026-09-19

Marketplace 1.14.1: **CBRE I&L Toolkit 1.10.1** and **UK I&L Toolkit 1.5.2**. Both plugins
move, so update both.

### Fixed
- **Four skills were installing but never loading, with no error anywhere.** Reported after
  `cbre-il-occupier-brief` failed to appear on two separate machines, both correctly on
  1.10.0. It was not a cache, not a version and not the install: **their YAML front matter
  was invalid.**

  A plain, unquoted YAML scalar cannot contain a colon followed by a space. Every one of
  these descriptions had one:

  ```yaml
  description: Produce a CBRE I&L OCCUPIER BRIEF: a short, dense dossier ...
                                                ^^ parser stops here
  ```

  The parser reads that second colon as the start of a nested mapping key and raises
  *"mapping values are not allowed here"*, so the skill is skipped. Everything else about the
  plugin looks healthy while it happens: the manifests validate, the install succeeds, the
  right version is reported, and the files are on disk. The skill just is not there.

  Affected, now fixed by quoting the description: **`cbre-il-occupier-brief`**,
  **`cbre-site-tour-app`** (shipped broken in 1.10.0, so it has been missing since it was
  released), **`cbre-il-outreach-angles`** and **`cbre-expense-claim`**. The description text
  is unchanged — each one was verified to round-trip byte-identically through the parser.

### Added
- **`tools/validate_skills.py`** — parses every skill's front matter the way a client does,
  checks `name` matches its directory and is lowercase-hyphenated, and names the colon-space
  fault explicitly when it sees it. `claude plugin validate` checks the *manifests* only and
  never looks at skill front matter, which is exactly why this shipped four times unnoticed.
  It is now the first step in the maintainer checklist in the README.

## [1.14.0] — 2026-09-16

Marketplace 1.14.0: **CBRE I&L Toolkit 1.10.0** gains a skill and loses one. UK I&L Toolkit
unchanged at 1.5.1.

### Added
- **`cbre-il-occupier-brief` — a traceable pre-meeting brief on a target company.** Internal
  enablement rather than a client deliverable: its job is to make the room fluent enough to
  hold a credible, forward-looking conversation, and the governing move in every section is to
  lead with the client's business problem rather than with a building.

  It runs a **four-way parallel research fan-out under a hard 60-search budget** (allocated per
  workstream and enforced by a script that reads the run's own search ledger, so a workstream
  that hits its cap stops and reports the gap instead of quietly overspending), then **one**
  independent QA round by a sub-agent that did not write the draft — the orchestrator
  implements every finding and records each disposition, with no second reviewer and no
  re-review. Three artefacts ship: a CBRE-branded A4 DOCX, a **Source Ledger where every
  material figure traces to a retrievable source** with the figure as the source states it and
  a publication date, and a **Verification Sheet** listing every time-sensitive or
  low-confidence claim with an action. Where the target's network is growing it also carries a
  ranked, falsifiable forecast of where the next distribution node goes, with its own audit
  trail so somebody can re-run or disagree with it.

  Required sections include the three persona reads — what is likely on the mind of the Head of
  Real Estate, the Head of Supply Chain and the CEO. UK English throughout, with em and en
  dashes rejected by a deterministic gate rather than by a style note.

  **Named `cbre-il-occupier-brief`.** It was authored as `cbre-il-pursuit-brief`; the skill, its
  directory, its heading, the artefact it produces and the DOCX filename all now read *Occupier
  Brief*. "Pursuit brief" and "pursuit intelligence brief" are kept as trigger phrases, so
  anyone still asking for the old name reaches the skill.

### Removed
- **`cbre-il-account-briefing` is no longer in the marketplace.** It shipped deck-length account
  briefings; the occupier brief covers the pre-meeting need it was most often used for, and a
  deck-length account plan is better built as a `cbre-corporate-pptx` deck on the occupier
  brief's own research. Every live pointer to it has been repointed: the outreach-angles
  description and its "use this, not the..." note, three hand-off lines inside the new skill,
  the README tables, and both plugin descriptions.

  **If you use it, it stays on disk until you update** — updating the plugin removes it. The
  skill's own history remains in this repository if it needs to come back.

## [1.13.0] — 2026-09-14

Marketplace 1.13.0: **CBRE I&L Toolkit 1.9.0** — dashboard template v43 → **v45**. UK I&L
Toolkit unchanged at 1.5.1.

### Fixed — property longlist
- **The street basemap moves off OpenStreetMap and onto Esri, because last release's fix
  failed in the same shape.** v1.11.0 moved the three street maps *to* OSM's keyless standard
  tiles to escape a provider that had started baking an "API KEY REQUIRED" watermark into its
  imagery. OSM has now blocked it, worse: its tile usage policy requires a request attributable
  to a named application, and a dashboard built by this template cannot supply one — the file
  opens from a `file://` path, so the request carries no usable `Referer`, and a page cannot
  set its own `User-Agent`. The server answers **403 with an HTML "Access blocked" page as the
  body**, which Leaflet paints into the tile grid as a readable wall of text telling the client
  the app breaks the rules — again with no console error, no failed fetch and no blank tile,
  because the response *succeeds*. The block is also plausibly against the whole corporate
  egress IP rather than any one file, and an office of readers opening longlists is the "heavy
  use" the policy forbids outright, so no amount of tuning the request would have fixed it.

  A keyed OSM reseller was rejected for one reason: the key would sit in plain text inside a
  file that gets emailed to clients, and key domain-locking cannot bind to a `file://` origin.
  Esri needs no key and already serves the satellite layer beside each of these three, which
  makes it a known quantity rather than a fresh bet. Three details are pinned identically at
  all three sites because each fails silently: the path order is **`{z}/{y}/{x}`**, not the
  OSM-style `{z}/{x}/{y}` — Esri takes row before column, and transposing them serves tiles of
  the wrong *place* rather than an error; the `{s}` subdomain placeholder is dropped, since
  Esri serves from one host; and the attribution is one byte-identical string crediting Esri
  alone, because three drifting variants of a credit is how the previous definitions came
  apart. The satellite layers are untouched.

  **Stated because it cannot be tested:** this is the second keyless provider to change its
  terms under this template, the failure mode returned HTTP success both times, and no
  automated check can read a watermark or a block page baked into imagery. The QA screenshot
  review is the only thing that catches a third time, and it takes a human looking at the
  picture.
- **The page carried four different words for "not stated".** The pipeline wrote `tbd` into
  unfilled fields, the chrome's own fallbacks wrote `tbd` or a long dash, three commercial rows
  printed a long dash, and land price had a long dash of its own — so a reader comparing two
  modals saw three spellings of the same fact, and the dashes read as values rather than
  absences. `normalize.BLANK` (`TBC`) is now the single owner, mirrored once in the chrome.
  Three properties make the swap safe rather than sweeping: the token is a member of
  `UNKNOWN_FORMS`, so coverage, the trace gate and the Gaps Report are untouched; `tbd` remains
  a recognised form, so an older canonical and a broker's own wording still resolve to absence;
  and `country` keeps its own sentinel because it holds an ISO code, not prose. An old
  canonical rebuilt today ships the new token with no migration.
- **The four rent rows now always print, blank included** — the only rows on any surface that
  do. The rent is the number the reader came for: a vanished rent row reads as "rent does not
  apply here" rather than "nobody has quoted yet", and it made two modals different *shapes* at
  exactly the four lines being compared. Every other row still omits when a source states
  nothing; printing eleven blanks to catch four would bury them.
- **The card's party line is labelled.** It printed a bare developer name beside the motorway,
  which read as a location fact and said nothing when the developer was unfilled. The label now
  follows the value — `landlord` wins because it is the party to the lease, `developer` is the
  fallback under its *own* label, and neither stated prints a labelled blank, because a
  developer printed under a "Landlord" label is a false statement about who the reader would
  sign with.
- The modal's meta chips are sentinel-guarded, so a chip never reads `TBC` in a row of facts.

### Changed — property longlist
- **Four surfaces removed from the dashboard**, each followed through all five places a removal
  leaves debris (the template, the config tokens, the EN table, the twelve bundled language
  packs, and the data the builder injects): the **hero lede paragraph**, which restated the KPI
  strip's count and described the filters two rows below it for a screenful above the first
  card; the **border POI category**, filtered at the render boundary so the dataset and its
  coverage checks stay correct and re-enabling is a one-line change; **Compare's best-value
  highlight**, because a longlist is read across many attributes at once and flagging two puts
  the dashboard's thumb on the scale of the reader's decision; and the **POI layers now start
  off**, so the map opens on the properties rather than twenty-two pins nobody asked for.
- **The headline names the occupier** — `{client} - Industrial & Logistics opportunities`,
  filled by replacement rather than formatting so a translator's stray brace degrades the
  headline instead of crashing the build. The region is deliberately absent: one longlist
  regularly spans two, and a stated region the option set outgrows is worse than none.
- **`displayName`** — the client's own name for an option as their tracker prints it — is a new
  canonical field that the card title prefers. Precedence, never replacement: it is absent on
  most datasets, so the existing park-plus-unit rules still carry those.
- **Three more media links** (video, website, Street View), each a chip beside the brochure,
  emitted only for a stated `http(s)` URL. That guard is load-bearing rather than defensive: the
  sentinel in an unfilled field is a *string*, so a truthiness test would have shipped a live
  link to the sentinel on every property with no video. Nothing is composed from a name or from
  coordinates — a generated Street View link is a claim about what the camera shows.
- The availability field reads as a date in English; the twelve packs keep their own wording
  until revised.

### Added
- `evals/chrome_v45_test.py` + `.mjs` — holds the chrome's blank token equal to the Python
  owner, executes the title, party-line, card and modal renderers in a node sandbox, and checks
  each removal in all five of its places. Fourteen existing evals that pinned the old spelling
  or the old omission were **re-pointed at the owner of the value** rather than loosened.

### Fixed — documentation
- The template contract's current-version line now agrees with `assets/VERSION` (both v45),
  which clears the one eval failure flagged in 1.11.0. The `v43` label was never a documented
  template revision — the sequence runs v42 → v44 → v45.

## [1.12.1] — 2026-09-14

Marketplace 1.12.1: **UK I&L Toolkit 1.5.1**. CBRE I&L Toolkit unchanged at 1.8.0.

### Security
- **All personal data is out of `cbre-expense-claim`.** The skill was written from one
  person's own claims, and it shipped their traces: the attendee examples used a real named
  person at a real company (in `SKILL.md`, `read_types.py`, and both the header note and the
  in-cell prompt of the generated spreadsheet), the PeopleSoft playbook named the account
  holder in the prefilled attendee row, and the references cited three real expense report IDs
  with their totals, a real client name, specific trips and a named merchant against a real
  card charge.

  Every attendee example is now an obvious placeholder name at a real UK logistics
  real-estate investor — `John Doe (Hillwood)`, and `John Doe (Hillwood); Jane Roe
  (Panattoni)` for the multi-person case — so the format still reads as realistic without
  naming anyone. Report IDs are described rather than quoted, the prefilled attendee row is
  documented as "the signed-in user (`Surname,Firstname` / `CBRE Ltd.`)", the approval email
  signs off with `<your first name>`, and trip, client and merchant references are replaced
  with neutral illustrations. The technical evidence that earned its place is kept: the
  exchange-rate lesson (853.88 PLN landing at £175.31, an effective 4.871 against a quoted
  5.01) and the compression measurements now read as illustrations rather than as one
  person's record.
- **The skill no longer assumes who installed it.** It described its owner in the third person
  throughout ("he fills Expense Type", "his call"), which was both a personal detail and
  simply wrong for everyone else installing from a public marketplace. All 29 such references
  now read as the user.

*Note: these values were present in the 1.12.0 commit, so they remain in this repository's
git history. Only the current tree is clean.*

## [1.12.0] — 2026-09-14

Marketplace 1.12.0: **UK I&L Toolkit 1.5.0** gains a third skill. CBRE I&L Toolkit unchanged
at 1.8.0.

### Added
- **`cbre-expense-claim` — receipts to a filed CBRE expense claim.** Reads a folder of mixed
  evidence with vision (iOS multi-page scans, phone photos, Uber and airline email
  screenshots, AMEX and Revolut app screens), deduplicates rescans, groups the pages into one
  claim line per transaction, and produces two files: a reconciled `Expenses.xlsx` and a
  page-stamped `Consolidated Expenses.pdf` whose navy band carries the line number and
  `{TYPE} - {Merchant} ({CCY} {amount})` on every page of a multi-page line. It then files the
  lines into PeopleSoft one at a time and reads every row back against the spreadsheet.

  The shape is two **hard stops**, and the judgement that matters happens in the gap between
  them. Stop 1 hands over the two files so the user sets **Expense Type** and **Attendees** in
  the spreadsheet's two cream columns — whether a given meal is Subsistence, Client
  Entertaining or Staff Entertaining turns on who was at the table, which no rule can infer, so
  the skill prefills `SUBSIST` and never pre-empts the call. Stop 2 hands back the Report ID
  and the per-line table. **Attaching receipts and Summary and Submit are never automated**,
  and MFA is never attempted — the sign-in number goes to the user.

  Where a wrong value would be silent and untraceable, the work is deterministic: a Python
  script builds both files and performs no judgement, amounts are never computed from a printed
  exchange rate (a real 853.88 PLN charge landed at £175.31, an effective 4.871 against the
  5.01 quoted that day), a split bill claims the payment block rather than the headline total,
  and a line with no card evidence stays in the receipt currency for PeopleSoft to convert.
  Attendee names are deliberately **read, not parsed** — names carry middle initials,
  particles and double-barrels, and a parser that guesses wrong files a real person's name
  incorrectly.

  The consolidated PDF has to stay attachable, so a companion script holds it under 9.5 MB and
  protects legibility in the right order: it walks JPEG quality from 92 down to 78 at **native
  resolution**, giving up no pixels, before it will consider resampling, then caps effective
  dpi from 240 to 150 — and fails loudly rather than ship an illegible claim. It leaves a file
  that already fits byte-identical, and refuses to be run twice on the same file.

### Fixed
- **Both existing UK skills' update notices named the wrong plugin.** They correctly read the
  UK I&L Toolkit's own version, but the message said "CBRE I&L Toolkit" and the CLI line gave
  `cbre-il-toolkit@cbre-il-toolkit`, so a UK user acting on the nudge would update the other
  plugin and the notice would never clear. All three UK skills now name **UK I&L Toolkit** and
  `uk-il-toolkit@cbre-il-toolkit`. The seven CBRE skills are unaffected.

### Security
- The PeopleSoft playbook shipped with a hard-coded **employee ID** and a Windows profile path
  containing a **username**. Both are personal to one person and wrong for anyone else
  installing from a public repository, so the Empl ID is now documented as prefilled from the
  signed-in user ("never type or hard-code one") and the profile path as `%USERPROFILE%\…`.

## [1.11.0] — 2026-09-06

Marketplace 1.11.0: **CBRE I&L Toolkit 1.8.0** and **UK I&L Toolkit 1.4.0**. Both plugins move,
so both need updating.

### Fixed — property longlist
- **The dashboard's street map was serving tiles with "API KEY REQUIRED" printed into the
  imagery.** The previous tile provider now bakes that watermark into what it serves on its
  keyless endpoint, so the text reached the reader inside real map tiles on every dashboard —
  and nothing detected it, because the tiles still return success: no console error, no failed
  fetch, no blank tile, only a human looking at the picture, by which point the file is with
  the client. All three map definitions (main map, modal mini-map, Flyover) now request the
  keyless OpenStreetMap standard tiles, with the subdomain list, the dropped `{r}` retina
  placeholder and the attribution applied identically at all three sites so they cannot drift
  apart again. The satellite layer beside each is untouched.
- **Two different units on one park rendered as two identical-looking cards** — in the grid,
  the map popup, the map list, the modal, the Flyover and both sets of comparison chips, which
  is the exact moment the broker is being asked to choose between them. A new canonical `unit`
  field carries the source's own designator as printed ("Unit 3", "Phase 2", "Block A"), and a
  single `titleStr(p)` helper composes every one of the nine title sites. An absent unit renders
  the park name unchanged, a park already named "Kestrel Reach Unit 3" is not doubled, and `unit`
  joins the search haystack, because a designator the reader can see must be typeable.
- **The card showed a smaller building than the brochure states.** The area figure is derived
  (warehouse + office), and a derivation reads below the printed total whenever real space sits
  inside that total and in no summed field — mezzanine, ancillary, plant. The source's own stated
  total now reaches the card as a sub-line beside the derived figure, never in place of it, and
  only when the two disagree beyond the arithmetic gate's own tolerance — quoted from the gate
  rather than re-invented, so the card and the gate cannot disagree about whether a difference
  matters. The modal then adopted the same figure, closing a gap where card and modal showed
  different numbers under the same "Total GLA" label.
- **A Total rent figure now says what area it was computed on.** The stated total may include a
  gatehouse or a plant room nobody pays warehouse rent on, so the money is unchanged and the
  basis is printed instead — one helper qualifies the inputs, and the formula that computes and
  the line that prints read the same components.
- **A site plan is no longer cropped.** The plan reused the photo hero's fixed 16/7
  `object-fit:cover` frame, which is right for a photograph and destructive for a plan, since a
  plan is the one image whose edges carry the information: yard depths, the plot boundary,
  dimension lines, the access road. Only the lightbox ever showed it whole. A `plan-mode` class
  toggled at the single existing swap point contains it over a neutral letterbox.
- **The chrome kept its own shorter vocabulary for "this value is absent".** Its private
  six-member list lacked `n/a`, `tba`, `tbs` and every market phrase, so a value a reader shipped
  as "TBA" rendered on the card as a real datum. It now mirrors the Python set member for member,
  with an eval holding the two equal. A stated `none` is deliberately still data, not an absence.

### Added — property longlist
- **Exit 16 — an invalid correction entry now refuses to start the run**, listing every fault in
  `work/overrides.json` and `work/repairs.json` in one pass, and saying plainly to fix the named
  entries **in place** rather than append new ones — appending re-runs into the same refusal with
  one more entry each round. `--allow-invalid-corrections` ships past a known-stale entry
  knowingly, with whatever it was meant to correct shipping uncorrected.
- **`--from <stage>` and `--only <stage>` narrow a re-run**, and are documented for what they
  actually guarantee: reach, not speed. They answer "can the correction I just made even reach
  this stage?", and the skill states outright that on a warm work dir `--from` behaves the same
  as ordinary resume. Neither can reach the pre-build gates, the post-build gates, the freeze or
  the QA window — those always run, so nothing ships unverified.
- **The QA window is one review round, with no mechanism for a second.** The spine records
  exactly one, and a review file that changes afterwards folds into it as further findings.
  Re-dispatching a reviewer is now prohibited for any reason, and which advisories to fix is
  stated as judgement with deliberately no threshold: one edit that changes what a reader
  concludes gets fixed and resolved; everything else ships disclosed.
- **The two-unnamed-units-at-one-location case is documented as expected**, not discovered. The
  matcher correctly keeps the records apart and the card-title gate correctly refuses two cards a
  reader cannot tell apart, so the run blocks at exit 6 and the operator sets `unit` per card from
  what the source actually says.
- **Around 67 new evals**, including the basemap provider extracted from the file itself, the
  single-derivation pins for GLA and rent basis, card-title collision, sentinel parity between
  Python and the chrome, stage-control scope, one-QA-round enforcement, over-merge guards and
  repair survival.

### Changed — UK I&L Toolkit (Kato longlist)
- **Every property's own source documents now reach the pipeline**, named so that filename-derived
  clustering puts one property's documents in one reader deck. This closes the worst thing the
  skill had shipped: with no document for a property the pipeline dispatches zero document readers
  for it, so every specification field on its card came from the tracker that same step had just
  generated, with no page-cited evidence behind any value — nothing failed, every gate passed, and
  the run was silently wrong rather than late. The step now **refuses (exit 2) when any longlist
  row has no machine-readable source**, names every such row, and writes nothing.
  `--allow-unevidenced-rows` ships anyway and records the affected rows for the Gaps Report.
- **`project.yaml` moved out of the scanned inputs folder.** `.yaml` matches none of the
  pipeline's accepted input types, so a copy there was classified unreadable and appeared in the
  **client-facing** Gaps Report, advising the reader to re-save or unlock a file we generated
  ourselves.
- **The wrapper asserts a minimum toolkit version** (currently v40) before copying anything, and
  refuses an older or unreadable one with the remedy. The comparison is numeric, so a future v100
  is correctly newer than v40, and the `-kato` suffix a previous run may have stamped is reported
  but never compared.
- **Exit 10 and exit 13 are documented as normal**, not as breakage. Shipping each property's
  documents means the corpus now holds more than one record source, so cross-source match
  adjudication can fire where a tracker alone could never have triggered it. The `country` value
  conflict expected on most properties is explained and repaired afterwards from a single market
  constant.
- The 12 active template patches are re-verified against template v40, each still matching its
  anchor exactly once, with neither retired premise regressed.

## [1.10.1] — 2026-09-02

Marketplace 1.10.1: **CBRE I&L Toolkit 1.7.1**. UK I&L Toolkit unchanged at 1.3.0.

### Fixed
- **Property longlist — the setup questions were never actually asked.** Reported from a live
  run on an up-to-date install: the skill opened without asking anything, then shipped an
  English dashboard with no email ingestion and car drive-times, because nobody was offered
  the choice. Neither the model nor a version drift — two defects, both reproduced on a clean
  probe run.

  First, **the scaffold looked like consent.** Intake writes a complete `project.yaml` on the
  very first pass — client name from `--client`, `output.language: English`,
  `inputs.emails.source: none`, the enrichment flags, `clarify.mode: interactive` — i.e. all
  six Stage-0 answers, pre-filled with guesses, before anything asks the broker. The skill's
  own instruction was to skip the form "when `project.yaml` already carries the answers", and
  it always did, so **skipping the form was the compliant reading.** The test is now a single
  explicit `setup.confirmed` flag: intake writes `false`, only the orchestrator sets `true`,
  and the presence of values proves nothing — the scaffold header, SKILL.md,
  `reference/setup-form.md` and `reference/config.md` all now say so.

  Second, **the instruction existed in exactly one place, phrased as a question** — a trailing
  clause about 85% of the way through the interpretation hand-off ("FIRST PASS? Present the
  Stage-0 setup form…"), which reads as optional, and which a corpus with no decks and no
  tracker to map never printed at all. Now every hand-off **leads** with the form as an
  imperative while it is unanswered (same message, so no extra round-trip), and a pass with no
  other hand-off stops on its own at exit 13 with a blocking `setup_form` question. That stop
  sits *after* the no-usable-inputs exit, so an empty folder is still reported as an empty
  folder rather than after six questions. The broker-facing line is now "A few setup questions
  first". Clearing the gate takes `setup.confirmed: true`, an explicit decline, or a headless
  escape — each a recorded decision; a stray `answers.json` entry deliberately does not, and
  the hand-off says so when it sees one.

- **Property longlist — `clarify.assume_defaults` was dead wiring.** `clarify.skip_all` read
  `project.yaml` from the work dir's *parent*, but `run.py` resolves it as
  `work / "project.yaml"`, which is where intake writes it. So the documented
  `assume_defaults: true` config never took effect and the `clarify.SKIP_ALL` sentinel was the
  only working headless escape. It now reads the work dir first and the parent second.

### Added
- Property longlist: `evals/setup_gate_test.py` — 37 checks covering the scaffold-is-not-consent
  rule, every escape, the prefix wording and its absence once confirmed, a tripwire on the
  exit-3 site count so a future hand-off can't be added without the prefix, the stop's ordering
  against the no-inputs exit, the question's kind/blocking/materiality, the
  answers.json-does-not-clear-it rule, and the three docs. The scripted-orchestrator sims
  (`conformance_sim_test`, `cowork_sim`) still pass unchanged, which is the real proof: an
  orchestrator that knows nothing but the exit table clears the new stop using the exit-13 rule
  it already had.

## [1.10.0] — 2026-08-26

Marketplace 1.10.0: **CBRE I&L Toolkit 1.7.0** gains a seventh skill. UK I&L Toolkit
unchanged at 1.3.0.

### Added
- **`cbre-site-tour-app` — a site-tour itinerary web app for the field.** Turns tour inputs
  (an agenda or schedule, coordinates, Google Maps links, and optionally availability sheets,
  brochures or emails) into ONE portable, self-contained `.html`: a day-by-day timeline where
  each day opens on an embedded Leaflet map with the stops numbered in running order, plus
  tap-through property detail, Google Maps deep links, copyable coordinates and an
  all-options list. Mobile-first for use on site, with a true desktop layout — sticky map
  beside the timeline — on a laptop. Handles one-day and multi-day tours.

  It is styled to match the property longlist dashboard, which is why it lives in this
  plugin: Financier Display, Calibre and Space Mono ship with it as embedded fonts, alongside
  CBRE green and the 2px radius, and Leaflet is vendored so the output has no external
  dependencies at all. Includes a legacy-tour importer and the shared update notifier.

## [1.9.1] — 2026-08-26

Marketplace 1.9.1: **CBRE I&L Toolkit 1.6.1**. UK I&L Toolkit unchanged at 1.3.0.

### Changed
- **Property longlist — the run only stops for what the client will actually see.** A live
  interactive run asked too often, so clarification questions now have to pass a
  **materiality test**: a question reaches the user only when its answer would change a value
  or photo shown on the dashboard, or the number of options that ship. Everything else is
  **disclosed rather than asked**, landing in the Gaps Report's new "Noted, not put to you"
  section. Because every surviving question has already passed that test, the orchestrator is
  told to put it to the user rather than second-guess whether it matters. `blocking:false`
  asks once then ships the honest gap; `blocking:true` returns each pass until answered or
  declined, and "decide sensibly" maps to headless — default honestly and disclose.
  Covered by a new `evals/clarify_materiality_test.py`, with updates to `helpers/clarify.py`,
  `helpers/deliver.py`, `helpers/run.py`, three dispatch prompts, `templates/record_schema.json`
  and six reference documents.

## [1.9.0] — 2026-08-24

Marketplace 1.9.0: **CBRE I&L Toolkit 1.6.0** — the property longlist's broker-in-the-loop
release. UK I&L Toolkit unchanged at 1.3.0. Marketplace and plugin names are unchanged.

### Added
- **Open capture in the spreadsheet extractor — read everything, display selectively.**
  Populated columns that no canonical field claims now land as top-level scalars or under
  `__meta.open_capture` rather than being dropped, with new first-class homes for address,
  postcode, buildType and description. `unmapped_headers` is redefined to mean *not read at
  all* and must be empty, and the Longlist workbook appends the surplus as dynamic columns
  (deterministic: sorted keys, mechanical header prettify, media/derived/internal keys denied).
- **Eleven new evals**, including a conformance simulator, an interactive-mode test,
  open-capture coverage for both the view and the workbook, combined `Lat Long` header
  misbinding, formula-rent rounding, excluded-conflict disclosure, QA-review ingest, and a
  **`no_client_data_test`** guard.
- **`prompts/cluster-labels.md`**, plus `reference/agentic-steps.md` and
  `reference/environment.md` — content moved verbatim out of `SKILL.md` so the orchestrator
  card carries only the loop, and `docs/MAINTENANCE.md` for whoever edits the skill rather
  than runs it.
### Fixed
- `repairs_projection_test` passes: a media repair resolves its file relative to the work dir.
- **The skill's `.gitignore` was restored.** A harness step had overwritten it with three
  lines (`printf >` instead of a merge), dropping the `state/`, `evals/_out/` and
  `.pytest_cache/` protections; all are back, plus a new `.regression/` rule, and the
  documented keep-list explaining what ships is retained.
### Security
- **Client data no longer ships with the skill.** A regression fixture had copied a live
  project's 16 inputs (~100 MB) into a `.regression/` directory *inside* the skill folder. Git
  history was verified clean — no client file was ever committed — but the folder is how
  teammates install the skill, so `.gitignore` protected nothing they receive. The data is
  deleted and a `no_client_data_test` guard now fails the suite if input-type files or project
  directories reappear. Verified passing before this release was pushed.

### Known issues
Two, both unchanged and still failing identically on an untouched copy of the upload:
`open_field_scalar_test` (3 assertions) and `plan_reject_test` (2, the POSIX/Windows path
case). With Pillow, PyMuPDF and openpyxl available the suite runs 118 passed / 3 failed; the
third, `extract_test`, is a real failure that only becomes visible once `openpyxl` is
installed, so it had previously been masked as a missing dependency.

## [1.8.0] — 2026-08-22

Marketplace 1.8.0: **CBRE I&L Toolkit 1.5.0** — two skills updated. UK I&L Toolkit unchanged
at 1.3.0.

### Added
- **Corporate decks — the deck is now *looked at*, not just asserted about.** The library could
  always render slides to PNG, but only ever used that to correct text-box heights; nothing
  inspected the result, and no assertion can catch "this deck reads as templated" or "slide 6 is
  a wall of grey". `scripts/contact_sheet.py` tiles a rendered deck into ONE image so the whole
  thing can be judged at once, and `scripts/critique/` judges that render against a **gold
  reference** set (dark-shift, dark-statement, white-evidence-table and a gold contact sheet).
  A new `references/chrome-spec.md` pins the part that never varies, measured from a signed-off
  CBRE proposal in inches on the 13.33 × 7.50 canvas. Supporting updates to `build.py`,
  `compose.py` and the layout, scene-composition and spacing references.
- **Property longlist — three new evals for v39.** `media_harvest_test` pins the media
  under-harvest fix end to end (every media tier degrades to an honest `None`/`[]` rather than
  quietly shipping less), `office_breakdown_test` (`.py` + `.mjs`) holds a multi-component
  `officeArea` to a bold summary line over a real bulleted breakdown while leaving every other
  shape untouched, and `project_layout_test` closes the arbitrary-inputs-folder defect with a
  fixed three-folder project layout.
### Changed
- **Property longlist — dashboard template v38 → v39** with a matching `chrome_sha256`, and
  broad updates across `clarify`, `deliver`, `enrich`, `final_gate`, `gate_runner`, `images`,
  `intake`, `interpret_prep`, `ledger`, `match`, `merge`, `plan_signal`, `project_properties`
  and eleven existing evals. Integrity manifest regenerated (93 files, 48 helpers).

### Known issues
Unchanged from 1.2.0 and still open upstream — each fails identically on an untouched copy:
`open_field_scalar_test` (3), `repairs_projection_test` (1) and `plan_reject_test` (2). 96 of
the longlist's 110 evals pass on a bare Linux box; the other 11 failures are only missing
Pillow/PyMuPDF/openpyxl, which Cowork provides.

## [1.7.0] — 2026-08-19

Marketplace 1.7.0: **UK I&L Toolkit 1.3.0**. CBRE I&L Toolkit unchanged at 1.4.0.

### Fixed
- **Kato longlist — broker emails were silently dropped in Cowork.** Stage 2 did
  `import extract_msg`, a package the Cowork sandbox does not have and cannot install (no pip,
  no network). The failure was quiet rather than loud: the import sat inside a per-file
  `try/except`, so every message was recorded as an error while the script still printed
  `DONE. parsed=N` and exited 0 — so broker rents and every email attachment vanished from the
  run without anyone being told. A new `helpers/msg_reader.py` reads `.msg` text and
  attachments using **only the standard library** (verified: `email`, `struct`, `zipfile` and
  friends, nothing external), so stage 2 now works anywhere and is explicitly **never** a
  degradation. It also reads emails attached to emails, because broker rents are regularly one
  reply deep, keeps signature logos apart from real brochures, finds the export even when it
  is not named `Emails.zip` (naming the file it used), reports `parsed=X/Y failed=Z` so missing
  text reaches the Gaps Report, and exits non-zero when nothing parsed.
  `msg_reader.py --selftest <zip|folder>` proves it works in an unfamiliar environment in
  seconds.
### Added
- **Kato longlist — a stage 8 that leaves the run openable by a colleague
  (`helpers/finalize_run.py`).** A real handover was a directory of ~20 mixed folders with the
  client dashboard buried three levels down beside QA montages, staging copies and
  `__pycache__`, and the person who asked for the longlist could not tell which file to send.
  Stage 8 now collects every client-facing file into `OUTPUT/`, writes a plain-English
  `START-HERE.md`, and deletes junk from a fixed allowlist — touching nothing a re-run or an
  audit needs, and idempotent, with `--dry-run` to preview. The run is not reported as finished
  until it has run and the user has been given the one path to open.

## [1.6.0] — 2026-08-19

Marketplace 1.6.0: **UK I&L Toolkit 1.2.0**. CBRE I&L Toolkit is unchanged at 1.4.0.

### Fixed
- **Kato longlist no longer writes into the installed CBRE property-longlist skill.** Kato
  deliberately ships no dashboard template of its own — it reuses whatever the installed
  toolkit provides, so every run inherits the newest CBRE chrome. But applying its card and
  modal tweaks meant `patch_template.py` writing into that skill's
  `assets/dashboard_template.html` and re-stamping its `assets/VERSION`, because the toolkit
  resolves both from its own skill root with no path override. A Kato run therefore mutated
  another plugin's installed files, leaving the install `-kato` tagged and its integrity
  manifest out of step.

  A new step 7a.5 (`helpers/toolkit_shadow.py`) now makes a per-run **shadow copy** of the
  installed toolkit (~28 MB in about a second: `evals/` and `docs/` skipped, `vendor/`
  hardlinked) and every later step uses the shadow. It is self-contained — the toolkit derives
  its `SKILL_ROOT` from `__file__`, so template, VERSION, integrity manifest, i18n, datasets
  and gates all resolve inside the shadow — and rebuilt fresh each run, so a toolkit update is
  picked up automatically (`--keep` reuses it when resuming). Runtime caches are unaffected,
  since the toolkit writes those into the work dir. `patch_template.py` now refuses any target
  that is not a shadow, so this cannot regress silently, and warns when an install is already
  `-kato` tagged by an older run.
- Corrected the documented toolkit entry point: `<toolkit>\helpers\run.py`, not
  `<toolkit>\run.py`.

## [1.5.0] — 2026-08-18

Marketplace 1.5.0: **UK I&L Toolkit 1.1.0** gains a second skill. CBRE I&L Toolkit is
unchanged at 1.4.0, so syncing this release does not re-download it.

### Added
- **`kato-longlist` in the UK I&L Toolkit.** Builds a client-ready I&L longlist straight from a
  Kato (`agency.kato.app`) requirement, enriched with rents and specs from the broker email
  export, and ends in three deliverables: a comprehensive per-property dataset, a clean client
  Excel, and a CBRE-branded HTML dashboard. The division of labour is explicit — the model makes
  every judgement (matching broker rents, curating specs, picking site plans, choosing client
  columns) while the Python helpers only move bytes (login, API pulls, downloads, image resizing,
  `.msg` parsing). Ships 16 helpers and a Chrome extension for the browser-side collection.
### Security
- **The Kato login is asked for, never shipped.** `email` and `password` arrive blank in
  `run.example.yaml`; the skill asks for the CBRE email and Kato password at the start of a run
  and writes them only into the working directory's `run.yaml`, which a new skill-level
  `.gitignore` excludes — so a filled-in config cannot be committed from a public repository.
  Real credentials present in the upload were removed before it was committed and never reached
  git history.
- The `ors_api_key` ships filled in, as the free organisation-wide openrouteservice key, and can
  be swapped for a personal key from `openrouteservice.org/dev`.

## [1.4.0] — 2026-08-17

The marketplace now carries **two plugins**, versioned and installed independently:
**CBRE I&L Toolkit 1.4.0** (six skills) and the new **UK I&L Toolkit 1.0.0** (one skill).

### Added
- **A second plugin: `uk-il-toolkit` ("UK I&L Toolkit"), at `plugins/uk-il`.** Same repo,
  same marketplace, same auto-sync — but its own manifest and version, so updating one
  plugin never re-syncs the other. Installed separately from the marketplace listing.
### Changed
- **The brochure downloader moved out of the CBRE I&L Toolkit and into the UK I&L Toolkit.**
  It is the same skill, unchanged, still invoked as `/cbre-brochure-downloader`. Its update
  notifier was retargeted at the UK plugin's own `plugin.json`; left pointing at the CBRE
  manifest it would have compared against the wrong plugin and reported phantom updates.
- CBRE I&L Toolkit is now six skills; its description, the marketplace description and the
  README's "What's inside" table were updated to match, and the README gained a section for
  the second plugin.

### Upgrade note
**If you had the brochure downloader via the CBRE I&L Toolkit, install "UK I&L Toolkit" to
keep it.** Syncing the CBRE plugin to 1.4.0 removes that skill, because it now lives in the
other plugin. Nothing else changes, and no other skill is affected.

## [1.3.1] — 2026-08-17
### Fixed
- **Brochure downloader — a fresh window per file, because a tab only gets one download.**
  Reusing one window silently lost every brochure after the first, and the cause took three
  failed mechanisms to pin down: a hidden iframe (the PDF viewer claims any sub-frame load, so
  it rendered invisibly and saved nothing), one reused window fire-and-forget (the
  multiple-downloads prompt blocked files 2..n while the loop raced past them), and one reused
  window pausing for that prompt (the second file silently degraded to *rendering*, with no
  prompt at all). The download allowance is per tab, so each file now gets its own fresh
  top-level window. Its one failure mode — a blocked popup — is **detectable**
  (`window.open` returns null), unlike a gated download that fails invisibly, so the run stops
  and says so instead of quietly producing a short zip. `TestDownloadMechanism` guards it.
### Changed
- **Brochure downloader — two routes in step 2, so no one is stuck behind a popup prompt.**
  *Save next brochure* is one click per file and needs no permission; *Start automated run* does
  all of them in one press but requires popups to be allowed for the page. Troubleshooting and
  `reference/browser-setup.md` updated to match, including the now-expected "popups blocked"
  stop.

## [1.3.0] — 2026-08-17
### Added
- **A seventh skill: `cbre-brochure-downloader`.** Turns the brochure links in a property
  longlist spreadsheet into one zip of correctly named, validated PDFs — the input
  `cbre-property-longlist` expects. It reads the longlist's *hidden* Excel hyperlinks (parsing
  the workbook straight out of its zip container, so no third-party packages are needed), then
  generates a self-contained HTML tool the user opens in Chrome or Edge.

  The browser is doing the downloading for a deliberate reason: the Cowork sandbox has no
  outbound network, and two measured browser facts rule out the obvious designs — most brochure
  hosts send no `Access-Control-Allow-Origin`, so a page cannot `fetch()` these PDFs, and almost
  none send `Content-Disposition: attachment`, so navigation opens the viewer instead of saving.
  The bytes therefore travel internet → top-level browser navigation → Downloads → dragged back
  onto the page → renamed, validated, zipped. The navigation must be top-level (a hidden iframe
  renders invisibly and saves nothing), and there is a test suite guarding that from regressing.

  Each PDF is renamed after its property, every file is checked to be a real PDF, shared links
  are deduplicated, and anything that is not a direct PDF is flagged in a `gaps.md` rather than
  guessed at. Ships with 100 tests (89 pass, 11 skipped) and the shared update notifier, and is
  registered in the plugin and marketplace manifests and the README.

## [1.2.1] — 2026-08-17
### Fixed
- **Property longlist — what ships with the skill is now stated correctly.** The flywheel
  ledger directory `state/` is ignored (it is per user and grows every run), and
  `reference/geocode_cache.json` is no longer ignored: `enrich.py` merges all three
  `reference/*.json` caches into every run as **read-only seeds** (runs write to the work dir),
  so ignoring one of them contradicted both the code and its sibling caches, which were already
  committed. It ships seeded via `helpers/seed_geocode.py`. The keep-list comment now
  enumerates the whole shipped skill, including why `vendor/` sits outside the integrity
  manifest — a truncated wheel must degrade to `fitz_shim`, never hard-fail a run.
### Changed
- **Property longlist — the one dispatch prompt you fill by hand is now named as such.**
  Email ingestion is dispatched at Stage 1 rather than from a spine exit, so `work/prompts/`
  never renders it; SKILL.md now says to copy `prompts/outlook-ingest.md` and fill its slots
  verbatim rather than author a paraphrase, which is the documented top error surface.

## [1.2.0] — 2026-08-17

Dashboard template v35 → **v38**, three new helpers, and the eval suite grows to **107 tests**.

### Added
- **Prompts as files (`prompts/`, `helpers/prompts_render.py`).** The 18 canonical sub-agent
  dispatch prompts (the gates, clarify, the readers, tracker mapping, match adjudication,
  translation, Outlook ingest, region labels) are now files rendered by code rather than text
  the orchestrator hand-writes from its own summary of a reference doc — the class that caused
  the skill's worst documented failures, where a pasted-short field list silently overrode the
  contract. They are covered by the integrity manifest, so a truncated prompt is caught like a
  truncated helper.
- **A per-property view and a repair path (`helpers/project_properties.py`,
  `helpers/repairs.py`, `reference/per-property.md`).** `canonical.json` is one ~11 MB file,
  mostly base64 image data, so the thing a broker or reviewer actually wants — one option, its
  values, its photos, the provenance of each figure — was not readable in it. A read-only
  per-property view now makes it legible, and `repairs.py` adds **property-keyed** corrections
  applied after the merge (distinct from `overrides.json`, which targets a source record such
  as a spreadsheet row or brochure page).
- **A finding-to-gate flywheel (`gate_runner.py flywheel`).** Reviewer findings accumulate in a
  ledger under `state/`, deliberately outside the integrity manifest because it grows per run,
  so a recurring finding can become a permanent gate instead of being re-litigated per client.
- **`KNOWN-DEFECTS.md`** — the defect register from a live 37-property run, each entry now
  shipping a fix and an eval, kept as the evidence those evals exist to protect.
- **26 new evals**, including certification, handoff commands, pending diagnosis, raster
  escalation, strike disclosure, workdir exclusion, BOM tolerance, repair ordering and
  projection, and district/open-field validation.
### Changed
- **Dashboard template v36 → v38** with a matching `chrome_sha256`, and broad updates across
  extraction, enrichment, matching, merge, delivery, the gates, `reference/{gates,interpretation,
  template-contract}.md` and the canonical schema. All 12 language packs stay on an identical
  191-key set. Integrity manifest regenerated: **93 files, 48 helpers** (now including `prompts/`).
### Known issues
Three evals fail for reasons that pre-date this packaging — each fails identically on an
untouched copy of the skill — and none is a data-correctness fault:
- `open_field_scalar_test` (3): `validate_canonical` does not yet reject a list or
  array-of-objects value on an undeclared field, nor name the offending field.
- `repairs_projection_test` (1): a media repair does not resolve its file relative to the work dir.
- `plan_reject_test` (2, carried from 1.1.0): the ack normaliser uses `Path(...).name`, which does
  not strip a Windows `c:\dir\` prefix on POSIX.

94 of the 107 evals pass on a bare Linux box; the other 10 failures are only missing
Pillow/PyMuPDF/openpyxl, which Cowork provides.

## [1.1.0] — 2026-08-11

A large property-longlist release: the dashboard template moves from v25 to **v35**, the
eval suite grows from a handful to **83 tests behind one runner**, and the QA stage becomes
a bounded, propose-then-implement window. It supersedes the withdrawn 1.0.16 (whose bounded-QA
and numguard work is included here).

### Added
- **A clarification channel (`helpers/clarify.py`, exit 13).** When the source is genuinely
  ambiguous, the skill now ASKS — during the run, while the answer can still change the
  deliverable — instead of writing a caveat into a Gaps Report nobody reads. Previously only
  three specific moments could ask (deck reading, photo match, conflict adjudication);
  everything else silently degraded to a flag.
- **A `G-arithmetic` gate.** The chrome's derived `GLA = warehouseArea + officeAreaVal` must
  not exceed the source's own stated total (`meta.statedTotals`), so a derived figure can
  never quietly overstate what the source said.
- **A Chinese dashboard locale (`assets/i18n/zh.json`).** Twelve bundled language packs, all
  sharing an identical 193-key set.
- **One eval runner (`evals/run_all.py`) and ~70 new evals.** SKILL.md used to name four
  evals; there are now 83. New coverage spans arithmetic, honesty, source authority and
  self-conflict, capture contract/symmetry, coordinate provenance, per-card completeness,
  unit disclosure and area basis, atomic delivery, freeze order, resume/livelock behaviour,
  translation end-to-end, and documentation truth (`doctruth_test.py`).
### Changed
- **The QA window: the reviewers PROPOSE, you IMPLEMENT, then DELIVER.** The post-build review
  is hard-bounded in code (`gate_runner.py qa-round`, with `resolve` per blocking finding)
  rather than the old "re-review until zero HIGH/MED" loop that a deliberately memoryless
  reviewer could never terminate. Reviewers judge exactly as before; advisory findings are
  closed by being written into the Gaps Report, not by another round. `final_gate.py` takes
  `--qa-state` and is checked against the delivered report.
- **“tbd is never a number” guards.** The chrome's comparators and predicates can no longer
  treat a `tbd`/`—` sentinel as a numeric value in sorting, filtering or KPIs.
- **Dashboard template v26 → v35**, with a matching `chrome_sha256`, plus broad updates across
  extraction, enrichment, matching, merge, delivery, the gates and every reference document.
### Removed
- **Archived four near-orphaned docs and two dead files**, each now asserted absent by
  `doctruth_test.py`: `reference/memory.md`, `reference/vision-fallback.md` (superseded by
  `interpretation.md` as the single interpretation contract), `templates/ledger_columns.md`,
  `examples/`, `helpers/_ph_const.txt` (a byte-duplicate of `assets/placeholder.uri`) and the
  preserved `assets/dashboard_template.v18.html`.
### Known issue
- `evals/plan_reject_test.py` fails on Linux (2 assertions): the plan-rejection ack normaliser
  uses `Path(...).name`, which does not strip a Windows-style `c:\dir\file.pdf` prefix on
  POSIX, so the test's path-insensitivity assertions do not hold there. Pre-existing and
  unrelated to packaging — it fails identically on an untouched copy of the skill. It is the
  suite's only logic failure: 74 of the 83 evals pass on a bare Linux box, and the remaining 8
  fail only for want of Pillow/PyMuPDF/openpyxl, which Cowork provides.

## [1.0.15] — 2026-07-29
### Fixed
- **Property longlist — two Cowork-resume convergence bugs.** (1) The placeholder-image
  audit now shares the SAME persistent on-disk geometry cache the image pickers use
  (threaded through `_page_crops`), so a resumed merge — the ~40-second shell-cap
  kill/re-run cycle — no longer re-parses a whole deck's page geometry uncached on every
  pass. (2) The region-label prompt loop now treats the ANSWERED keys as the "already
  asked" set (not the bind cache, which drops declined `code=null` entries), so a declined
  label is no longer re-emitted every re-run and the exit-3 handshake actually converges.
  Touches `helpers/enrich.py`, `helpers/images.py`, `helpers/merge.py` and `helpers/run.py`,
  with a new `evals/audit_resume_test.py` covering both traps.

## [1.0.14] — 2026-07-22
### Changed
- **`cbre-il-outreach-angles` — Stage 3.5 abductive synthesis now reasons in structured
  steps.** Rather than leaping from an unresolved tension to a single guess, each bet is
  worked in three steps: (1) enumerate the real-estate move-types a tension admits
  (expand, enter, consolidate, close, exit, relocate, change tenure, in-house vs 3PL) and
  drop responses with no European property consequence; (2) gate by the company's posture
  (additive vs defensive vs mixed) to select which move-type is live — a mixed posture can
  carry two bets; (3) run ONE bounded, bet-specific research pass for soft corroboration,
  then strengthen, drop, or promote the bet (a bet that gains a hard dated trigger becomes
  a ranked angle, not a bet). Every bet is a European move, and the inference fence now
  records the move-type and the posture that selected it. Updates `helpers/final_gate.py`,
  `helpers/render_html.py`, `reference/evidence-and-ledger.md`, `reference/output-template.md`
  and `evals/smoke_test.py`.

## [1.0.13] — 2026-07-21
### Added
- **`cbre-il-outreach-angles` — Stage 3.5 abductive synthesis (“Reading the signals”).**
  A new orchestrator pass reads the FULL merged evidence set (including the low-signal
  and pressure findings the angle logic discards) and asks what un-announced decisions,
  if any, would best explain the whole pattern of signals (up to four; zero allowed,
  never padded). Each hypothesis is fenced — two independent sourced facts, a shown
  reasoning chain, a real-estate consequence, a named public tripwire, a disconfirming
  line and an epistemic label — and lands in a separate, internal `## Reading the signals`
  block that never enters the ranked list or affects developability scoring (“the
  deliverable of a bet is the tripwire, not the guess”). Updates `helpers/final_gate.py`,
  `helpers/render_html.py`, `reference/evidence-and-ledger.md` (the inference fence),
  `reference/output-template.md` and `evals/smoke_test.py`.

## [1.0.12] — 2026-07-21
### Changed
- **Property longlist — Stage-0 setup is now a single `visualize` widget.** The broker
  setup (client name, enrichment extras, openrouteservice key, email scope, language)
  is presented as ONE `visualize` elicitation widget showing all five questions in a
  single box and submitted together, instead of `AskUserQuestion` — never one question
  at a time, with a plain-text single-message fallback when the tool is unavailable.
  Adds `reference/setup-form.md` (the elicitation form and how to render it) and updates
  `SKILL.md` to match.

## [1.0.11] — 2026-07-20
### Added
- **Property longlist — a persistent Compare view (dashboard template v25).** A new
  fourth tab (after Grid, Map and Flyover) compares all properties side-by-side by
  default, honouring the live filters and sort, with per-property deselect chips and
  no cap. It reuses the chrome's existing `compareHTML()` renderer so it can never
  drift from the card tick-box compare popup, which is unchanged. New i18n keys
  (`tab_compare`, `cmp_*`) added to English and all 11 language packs.
### Changed
- **Property longlist — Flyover navigation.** Scrolling no longer moves between
  options; the Flyover shows one property at a time and you navigate with the
  prev/next buttons, arrow keys, the space bar, or a marker click (the scroll-driven
  IntersectionObserver was removed). Template bumped to v25 (matching chrome hash),
  with supporting updates to `helpers/i18n.py`, `helpers/make_template.py`,
  `helpers/merge.py`, `reference/template-contract.md`, `reference/visual-qa.md` and a
  new `evals/compare_test.py`. Integrity manifest regenerated (71 files); preflight,
  smoke and compare tests pass.

## [1.0.10] — 2026-07-20
### Changed
- **Property longlist — independent Site Plan verification.** The detail modal's
  Site Plan slot (`p.plan`) now gets its own visual-QA reviewer check, which the
  mechanical images gate never judged: the reviewer confirms the bound image really
  is THIS property's site plan (rejecting a location/context map, a photo, a spec
  table, a cover/contact page, or a different property's plan) and flags a plan the
  interpreter missed — often one half of a two-page spread. `helpers/gate_runner.py`
  now surfaces the plan-attachment gap (plans attached vs. properties, plus
  near-misses) so it is never a silent pass, with supporting updates to
  `helpers/images.py`, `helpers/merge.py`, `reference/interpretation.md`,
  `reference/visual-qa.md` and `evals/plan_detect_test.py`. Integrity manifest
  regenerated (71 files); preflight and the smoke test pass.

## [1.0.9] — 2026-07-20
### Changed
- **Property longlist — sharper site-plan detection.** A new high-precision text
  signal (`helpers/plan_signal.py` with a curated multilingual title/marker lexicon
  `assets/plan_lexicon.json`) rescues designed site-plan pages that the pixel
  classifier misreads as a photo or map — it matches real plan titles ("SITE PLAN",
  "Lageplan", "plan de masse", and the like) and drawing markers, and deliberately
  ignores spec-sheet vocabulary so it never fires on a spec table. Wired into
  `helpers/images.py` (`_plan_page_eligible`), with supporting updates to
  `helpers/merge.py` and `helpers/deliver.py`, and a new `evals/plan_detect_test.py`.
  Integrity manifest regenerated (71 files, now guarding the lexicon); preflight and
  the smoke test pass.

## [1.0.8] — 2026-07-17
### Added
- **Property longlist — first-party coordinates from map links (`helpers/coords.py`).**
  A shared, pure parser pulls a landlord/agent's OWN Google/Apple/OSM maps link or
  a `lat,lng` pair out of brochures, trackers, Excel cells and email bodies and uses
  it verbatim (via `extract_pdf.backfill_link_coords`) — a first-party pin beats a
  town-centre geocode and works fully offline, so a blocked geocoder no longer
  strands a run. Coordinates are still never model-invented.
- **Property longlist — free-text data translation (`helpers/translate.py`, exit 12).**
  When the dashboard language differs from the source, eligible property *prose*
  (descriptions, status) is translated by an isolated sub-agent while numbers, units,
  codes, dates and proper names stay verbatim; the original is kept in the Source
  Ledger, the pass is cached and resume-safe, and a blind G-lang reviewer confirms it.
  Declinable with a `.SKIP` marker.
### Changed
- **Property longlist — consolidated Stage-0 setup and dashboard template v24.** The
  broker setup is now ONE `AskUserQuestion` form (client name, enrichment extras, the
  openrouteservice HGV key, email scope and language in a single prompt — no
  follow-ups). Dashboard template bumped to v24 (matching chrome hash). Broad updates
  to extraction (`extract_pdf`, `extract_pptx`, `extract_xlsx`), `merge`, `deliver`,
  `gate_runner`, `run`, `i18n`, `make_template`, all 11 language packs and
  `reference/{data-engine,localisation}.md`, plus new evals (coords, boundary, flyover,
  format, xlsx-coords, backfill-coords, off-spec premerge, translate). Integrity
  manifest regenerated (69 files); preflight and the smoke test pass.

## [1.0.7] — 2026-07-10
### Changed
- **Property longlist — dashboard template v21: data-driven detail modal.** A
  property's detail-modal spec rows are now generated client-side by the
  template's `detailHTML()` on card click (rather than baked into the static
  HTML), and the modal gains an "additional details" section (new `sec_additional`
  string added across all 11 bundled languages). Bumps `assets/VERSION` to v21
  with a matching chrome hash and updates `assets/dashboard_template.html`,
  `helpers/make_template.py` and `helpers/i18n.py`. Adds an offline Node-based
  modal-render eval (`evals/modal_render_test.py` + `.mjs`) that executes the real
  `detailHTML()` in `node:vm`, and refreshes `evals/smoke_test.py`. Integrity
  manifest regenerated; smoke test passes (byte-stable chrome).

## [1.0.6] — 2026-07-05
### Changed
- **Property longlist — catch and drop decorative graphics from photo carousels.**
  The interpretation sub-agent can now flag non-building / abstract images (brand
  art, gradient or geometric-pattern backgrounds) via a new optional
  `__meta.exclude_refs` field (`templates/record_schema.json`), so they are dropped
  from a property's carousel; the hero is never touched and genuine site plans and
  location maps are kept. `helpers/contact_sheet.py` gains a `carousel_secondaries`
  montage of every secondary slide, and the **G-images gate now reviews it** — a
  decorative graphic that slips into a carousel reads as a "plan" to the mechanical
  classifier, so only the vision reviewer can catch it. Supporting updates to
  `helpers/images.py`, `helpers/merge.py` and `helpers/vision_validate.py`, guidance
  in `reference/interpretation.md` and `reference/gates.md`, and new coverage in
  `evals/extract_test.py`. Integrity manifest regenerated.

## [1.0.5] — 2026-07-04
### Added
- **Property longlist — nearest-city and nearest-border geo layers.** Two new
  bundled datasets, `assets/cities_major_dataset.json.gz` (European cities of
  ~100k+) and `assets/borders_dataset.json.gz` (a complete OSM border-crossing
  set), with `helpers/build_cities_major_dataset.py` and
  `helpers/build_borders_dataset.py` to regenerate them, so property enrichment
  can place each site against its nearest major city and nearest border crossing.
### Changed
- **Property longlist — broad extraction and pipeline refresh.** Updates across
  extraction (`extract_pdf`, `extract_pptx`, `extract_email`), enrichment
  (`enrich`, `web_enrich`, `images`, `vision_prep`, `vision_validate`), the
  pipeline spine (`run`, `intake`, `merge`, `normalize`, `match`, `ledger`,
  `deliver`, `build_dashboard`, `interpret_prep`, `render_qa`) and the gates
  (`gate_runner`, `final_gate`), plus refreshed evals (`extract_test`,
  `fixture_test`, and a new `atomic_test.py`).
- Regenerated `assets/integrity.json` (now also guards the two new datasets and
  builder helpers — 67 files, LF-normalised); preflight verifies integrity and
  the ownership mark. The update notifier (`helpers/version_check.py`) is
  retained and still wired into SKILL.md.

## [1.0.4] — 2026-07-02
### Changed
- **Update notifier now covers every skill, with clearer, Cowork-first
  instructions.** The best-effort `version_check.py` nudge is wired into all six
  skills (added to `cbre-il-outreach-angles`, `warehouse-network-mapper` and
  `cbre-tone-of-voice`; already present in the other three), so a user on any
  entry point learns when a newer toolkit version is available. Its message is
  rewritten to be actionable: it now spells out the Cowork path (Customize →
  Plugins → CBRE I&L Toolkit → Update) and the reliable remove-and-re-add
  fallback, plus the CLI command. Still best-effort — one anonymous public
  version lookup, silent when current or offline, and it never blocks a run.

## [1.0.3] — 2026-07-02
### Changed
- **`cbre-il-outreach-angles` — tighter scoring and a stricter gate.**
  Developability is now scored to a stated two-sub-factor rubric (scale +
  near-term transaction likelihood) with an **anchor-quality cap**: an item whose
  anchor fact is only an inference (e.g. unconfirmed freehold) is capped at
  Medium, so an unverified premise can no longer lead the sheet on scale alone.
  The ranked list must run in **non-increasing developability-band order** — the
  deterministic gate now FAILs an out-of-order list — and is treated as a ceiling
  of about five to seven, not a target (thin or speculative angles go to the
  watch-list, never padded into a slot). Email hooks must be **pasteable,
  send-ready sentences** (no "reference their capex" instructions), and are
  **hedged on verify-first items** so an unverified fact is posed as a question in
  the soft ask, never asserted. New anchor-integrity rules: a load-bearing figure
  must cite a primary or corroborating source (a data-aggregator-only citation
  raises an advisory WARN), and inferred ownership is framed as an open question,
  never as "owned". Updates `helpers/final_gate.py` and `evals/smoke_test.py`,
  `SKILL.md`, `reference/evidence-and-ledger.md`, and `reference/output-template.md`.

## [1.0.2] — 2026-07-01
### Added
- **New skill: `cbre-il-outreach-angles`.** Turns a target company into a
  ranked **Outreach Opportunities** sheet — about five to seven evidence-backed
  reasons to make contact now, ordered by how developable each opportunity is,
  each labelled for trigger strength (a dated event or a sourced structural
  inefficiency) and readiness (send-now / verify-first), and each shipped with a
  ready-to-send email hook and a call opener. Runs an orchestrated harvest (a
  "now" machine, a pressure machine, and an all-Europe facility-evidence
  fan-out), enforces dated-source evidence integrity and footprint completeness,
  and delivers a self-contained, CBRE-branded HTML file that leads in plain
  English with a jargon buster and tucks each item's evidence behind a
  collapsible toggle. The lightweight prospecting sibling to
  `cbre-il-account-briefing`. Ships `SKILL.md`, `helpers/final_gate.py` (the
  deterministic structural gate) and `helpers/render_html.py` (the renderer),
  `reference/` (evidence-and-ledger, source-playbook, output-template), and
  `evals/smoke_test.py`.
### Changed
- README and the marketplace/plugin descriptions now list the outreach-angles
  capability.

## [1.0.1] — 2026-06-25
### Changed
- **`cbre-il-account-briefing` — sharpened the supply-chain-signature read.**
  Reframed the `supply-chain-signature` slide as supply-chain / network
  intelligence — network shape, capacity (peak-vs-base), inventory positioning,
  make-vs-buy, in-house vs 3PL — explicitly *not* the real-estate angle, which
  stays on the later `challenge-to-real-estate` slide. Made it work for
  manufacturers as well as retailers: added make-vs-buy / vertical-integration
  and production-rhythm dimensions, two archetypes (vertically integrated maker;
  make-to-stock/make-to-order manufacturer), and a worked
  vertically-integrated-maker example. Updates `reference/supply-chain-signatures.md`,
  `reference/synthesis-and-analysis.md`, and `reference/deck-structure.md`.

## [1.0.0] — 2026-06-24
### Changed
- **Renamed the marketplace and plugin identifiers** — marketplace `cbre` →
  `cbre-il-toolkit`, plugin `cbre-il` → `cbre-il-toolkit`. The install token is now
  `cbre-il-toolkit@cbre-il-toolkit`. Re-added the plugin `displayName`
  ("CBRE I&L Toolkit") on the marketplace entry.
  **⚠️ Breaking:** existing installs are keyed to the old `cbre-il@cbre` identity and
  do not migrate — each user must remove the old marketplace and add it again once.
- **`warehouse-network-mapper`** — added Facility scope (warehousing only vs plus
  manufacturing), Depth modes (normal / detail / extra-deep recon-then-deep funnel)
  with the new `helpers/merge_leads.py` lead consolidator, and `tenure`/`status`
  fields; updated `make_geocoder_html.py`. (Skill update that landed after 0.6.2.)

## [0.6.2] — 2026-06-24
### Changed
- **`warehouse-network-mapper` — scope is the whole region, not the company's
  operating footprint.** The skill now always covers every in-scope European
  market, explicitly including the logistics gateway countries (Netherlands,
  Belgium, Germany, Poland) even where the company has no presence, adds an
  import/port-of-entry DC hypothesis, batches non-operating countries, and flags
  the "operating-country trap" — because central EDCs, bonded import warehouses
  and 3PL-shared hubs often sit where the company does not trade and are often the
  largest sites in the network. (SKILL.md methodology; the plain-language
  description is unchanged.)

## [0.6.1] — 2026-06-24
### Changed
- Rewrote the `warehouse-network-mapper` skill description in plain language
  (dropped the internal pipeline jargon, kept the trigger phrasing).
- Updated the README and the marketplace/plugin descriptions to include the new
  warehouse-network-mapping capability.

## [0.6.0] — 2026-06-24
### Added
- **New skill: `warehouse-network-mapper`.** Maps a company's real warehouse and
  distribution network across Europe (or one country) to an auditable Excel —
  country, city, geocoded lat/long, landlord/developer, size (metric or imperial),
  year in use, operator (3PL or occupier-run) and facility type. Runs an
  orchestrated pipeline of parallel research subagents (searching in English and
  the local language), geocodes from real addresses in code (never modelled), and
  measures coverage against the company's own stated network size. Ships `SKILL.md`,
  helpers (`_common`, `dedup`, `geocode`, `make_geocoder_html`, `units`, plus an
  offline `gazetteer.json`), and `reference/source-playbook.md`.

## [0.5.0] — 2026-06-24
### Added
- **Property longlist — ownership / provenance & tamper-evidence.** Adds a
  `NOTICE` file and an authorship mark across the core helpers (visible copyright
  header; `helpers/_common.py` carries `OWNER_MARK` / `OWNER_FINGERPRINT` and a
  zero-width canary). `helpers/preflight.py` now verifies the mark on every run
  (surfaced as a warning, never blocks), and `assets/integrity.json` records the
  SHA-256 of the marked files so tampering is detectable.
### Changed
- Dashboard template bumped to **v20** (`assets/VERSION` + `dashboard_template.html`),
  with supporting updates to `build_dashboard`, `make_template`, `i18n`, `merge`,
  `run`, the smoke test, and `make_integrity`.
- Regenerated `assets/integrity.json` against LF-normalised content (now also
  covers the preserved `helpers/version_check.py` update notifier).

## [0.4.0] — 2026-06-23
### Added
- **Built-in update notifier.** Each runnable skill now runs a tiny
  `version_check.py` at startup that compares the installed plugin version against
  the latest published on `main` and prints a one-line update hint **only if you
  are behind**. It is best-effort by design: a single anonymous public GET, a short
  timeout, no telemetry, silent when current or offline, and it never blocks or
  fails a run. Wired into `cbre-il-account-briefing`, `cbre-property-longlist`, and
  `cbre-corporate-pptx`. This works around Claude Code's unreliable in-place
  marketplace update so users find out when a new version is available.

## [0.3.6] — 2026-06-23
### Added
- **Property longlist — dashboard internationalisation (i18n).** The dashboard
  chrome can now be localised. Ships `helpers/i18n.py`, 11 bundled language packs
  under `assets/i18n/` (cs, de, es, fr, hu, it, nl, pl, pt, ro, sk),
  `evals/i18n_test.py`, and `reference/localisation.md`.
- The canonical schema now accepts `meta.ui_overrides`.
### Changed
- Dashboard template bumped to **v19** (`assets/VERSION`); the prior **v18**
  template is preserved as `dashboard_template.v18.html` so existing projects
  rebuild identically.
- Supporting updates across `build_dashboard`, extract/intake/merge/run/vision
  helpers, eval fixtures, and reference docs.
- Regenerated `assets/integrity.json` against LF-normalised content.

## [0.3.5] — 2026-06-22
### Changed
- **Account briefing — output language is now an open question.** The skill asks
  the user to name any supported Latin-script European language (their free
  choice) rather than offering a company-home-language-vs-English binary, and the
  supported-language guidance is expanded. Updated in `SKILL.md` and
  `templates/variables.yaml`.

## [0.3.4] — 2026-06-22
### Changed
- **Account briefing — deck builder and gate runner overhaul.** Substantial
  updates to `helpers/build_deck.py` and `helpers/gate_runner.py`, plus supporting
  changes to `SKILL.md`, several reference docs, the content-plan schema, and
  `variables.yaml`.
### Removed
- Stopped tracking the regenerated `evals/_smoke_out/` smoke-test output (now
  git-ignored); added a skill-local `.gitignore`.

## Earlier
- **0.3.0 – 0.3.1** — Initial public packaging of the `cbre-il` plugin and the
  `cbre` marketplace (corporate decks, account briefings, property longlist, CBRE
  tone of voice), plus client-compatibility fixes.

[1.19.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.19.0
[1.18.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.18.1
[1.18.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.18.0
[1.17.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.17.0
[1.16.3]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.16.3
[1.16.2]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.16.2
[1.16.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.16.1
[1.16.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.16.0
[1.15.2]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.15.2
[1.15.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.15.1
[1.15.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.15.0
[1.14.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.14.1
[1.14.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.14.0
[1.13.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.13.0
[1.12.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.12.1
[1.12.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.12.0
[1.11.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.11.0
[1.10.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.10.1
[1.10.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.10.0
[1.9.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.9.1
[1.9.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.9.0
[1.8.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.8.0
[1.7.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.7.0
[1.6.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.6.0
[1.5.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.5.0
[1.4.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.4.0
[1.3.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.3.1
[1.3.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.3.0
[1.2.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.2.1
[1.2.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.2.0
[1.1.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.1.0
[1.0.15]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.15
[1.0.14]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.14
[1.0.13]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.13
[1.0.12]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.12
[1.0.11]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.11
[1.0.10]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.10
[1.0.9]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.9
[1.0.8]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.8
[1.0.7]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.7
[1.0.6]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.6
[1.0.5]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.5
[1.0.4]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.4
[1.0.3]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.3
[1.0.2]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.2
[1.0.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.1
[1.0.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v1.0.0
[0.6.2]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.6.2
[0.6.1]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.6.1
[0.6.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.6.0
[0.5.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.5.0
[0.4.0]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.4.0
[0.3.6]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.3.6
[0.3.5]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.3.5
[0.3.4]: https://github.com/Timobaaij/cbre-il-toolkit/releases/tag/v0.3.4
