# Changelog

All notable changes to the **CBRE I&L Toolkit** (`cbre-il`) plugin and its
marketplace are recorded here. Versions follow [Semantic Versioning](https://semver.org):
`MAJOR.MINOR.PATCH`. The version in `plugin.json` is the one Claude Code uses to
decide whether an installed plugin is out of date, so it is bumped on every release.

How to update to the latest version is in the [README](./README.md#updating).

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

[0.6.2]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.6.2
[0.6.1]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.6.1
[0.6.0]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.6.0
[0.5.0]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.5.0
[0.4.0]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.4.0
[0.3.6]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.3.6
[0.3.5]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.3.5
[0.3.4]: https://github.com/Timobaaij/cbre-il-plugin/releases/tag/v0.3.4
