# Maintenance (whoever EDITS the skill - never part of a broker run)

Moved verbatim from SKILL.md (workstream 1 item 1.1).

- After editing any helper/template: `python helpers/make_integrity.py` (regenerates the
  manifest; a broker run never calls this), then run the evals with
  **`python evals/run_all.py`** - the WHOLE suite (110+), which is the bar for shipping a
  skill edit. `--quick` runs only the four fast ones (`extract_test`, `fixture_test`,
  `smoke_test`, `translate_e2e_test`) as a mid-edit sanity check and `-k <substr>` filters
  while iterating, but **neither is sufficient on its own**. That is not pedantry: in ONE
  session `cowork_sim` caught a manifest-rename livelock (23 consecutive non-convergence
  rounds, exactly what a real orchestrator would hit) and a source-authority logic bug - and
  all four fast evals passed straight through both. A file merely EDITED since the manifest
  was built is an advisory preflight note, never a restart.
- `evals/conformance_sim_test.py` is the NO-RECALL bar for the orchestrator loop: it drives
  the real run.py through the FULL lifecycle knowing only the exit table, the printed
  handoffs and `work/prompts/`. An edit that reintroduces a prose-only obligation (a step the
  handoffs do not carry) fails there, not on a live run.
- Template edits follow the hand-edit order in `reference/template-contract.md` ("Versioning").
- **The finding-to-gate flywheel:** `python helpers/gate_runner.py flywheel` lists the
  reviewer finding classes recurring ACROSS runs (`qa-round record` appends every finding to a
  per-user ledger in `state/` - deliberately outside the integrity manifest - and prints a
  `[flywheel]` nudge when a class recurs). A class seen in >= 2 runs is review money spent
  twice: convert it into a mechanical pre-build gate plus an eval, and the reviews trend
  toward `FINDINGS: none` - reviewers as the safety net, not the primary defect-removal
  mechanism.
  - **2026-09, input-accounting cried wolf at an email that carried brochures.** A 16-email,
    22-brochure corpus blocked with eleven copies of "contributed NOTHING ... silently
    vanished" on a run where every brochure was read and shipped: a saved attachment enters
    the ledger under its OWN filename, never its carrier's, so an email whose body held no
    quotable data was invisible to every bucket. A gate that reds a correct run gets switched
    off, which is the whole reason this one has six honest outcomes rather than two. Now
    `_accounting_buckets` has a seventh, `attachment_carrier`, credited from the
    `.from_email.json` sidecars and only when EVERY saved attachment is itself accounted for,
    so the genuine loss (a declared attachment nothing saved) still blocks. Pinned by
    `evals/input_accounting_attachment_carrier_test.py`. Its sibling half: the exit-17
    sub-agent contract never asked for `source_files` on an email-prose row, so the
    `master_list_no` exemption could not fire either - `prompts/master-list.md` now asks for
    it. The lesson worth carrying: when a gate's exemption keys on a field, check that
    something actually POPULATES that field on every path into it.
- The dispatch-prompt templates live in `prompts/` (one per sub-agent kind) and are
  integrity-guarded: after editing one, run `make_integrity.py` and the evals
  (`prompt_render_test` pins the load-bearing clauses so a template edit cannot silently drop
  one).
- Dataset refreshes: a fresh GeoNames cities dump -> `python helpers/build_cities_dataset.py
  <cities.txt>`; updated POI exports in a folder -> `python helpers/build_poi_dataset.py
  <folder>`; a new Oxford Economics export -> `python helpers/build_regions_dataset.py`; then
  `python helpers/make_integrity.py` after any of them.
- The broker-in-the-loop / Sonnet-drivability implementation history (phases, blind reviews,
  regressions) is in `docs/CHANGELOG-broker-in-the-loop.md` and
  `docs/IMPLEMENTATION-PLAN-broker-in-the-loop.md`; the skill's git repo carries per-phase
  tags (`baseline`, `phase-1`, `phase-1-reviewed`, `phase-2`, ...) as rollback points.
- **CLIENT DATA NEVER LIVES IN THE SKILL FOLDER - not even gitignored.** Teammates install
  the skill by COPYING THE FOLDER, so everything on disk ships; gitignore protects the git
  history, not the copy. Regression fixtures are synthetic (cowork_sim builds its own
  corpus in a temp dir) or live OUTSIDE the skill (a scratch directory). Enforced by
  `evals/no_client_data_test.py`, which fails on any property-input file type or project
  folder anywhere in the tree. This exists because a live project's ~100 MB of inputs
  once sat under a gitignored `.regression/` and the "installable" skill silently grew to
  156 MB carrying a client's brochures.
- **Ship copies also exclude `state/` contents** (`state/qa_findings.jsonl` is the
  PER-USER flywheel ledger and quotes finding text from that user's real runs - it must
  never travel in a zip or a commit; `.gitignore` keeps it out of the repo, and whoever
  zips the skill deletes/empties `state/` first).
- **The git history lives OUTSIDE the skill folder** (same lesson: the folder ships whole,
  and the baseline commit's copy of the vendor wheel doubled the zip). The repo is at
  `~/.claude/skill-repos/cbre-property-longlist.git` (tags `baseline` ..
  `phase-4-reviewed` are the rollback points). Work with it via:
  `git --git-dir "%USERPROFILE%\.claude\skill-repos\cbre-property-longlist.git" --work-tree "%USERPROFILE%\.claude\skills\cbre-property-longlist" <command>`
  The skill folder itself stays git-free (~32 MB, <30 MB zipped - under the org
  upload-size cap).
