# CBRE I&L Toolkit

CBRE Industrial & Logistics skills for [Claude](https://www.claude.com/) — branded
decks, account briefings, property longlists, warehouse-network maps, and on-brand
writing. Packaged as a Claude plugin so the whole team can install it in a couple of
clicks.

## What's inside

| Skill | What it does |
|-------|--------------|
| **Corporate decks** | Polished, CBRE-branded PowerPoint decks built from your content. |
| **Account briefings** | Industrial & Logistics account-briefing decks built from your research. |
| **Property longlist** | An interactive longlist dashboard from a folder of brochures, emails, and spreadsheets. |
| **Warehouse network mapper** | An auditable Excel of a company's warehouse and distribution network across Europe (or one country), with every facility geocoded from a real address. |
| **CBRE voice** | Any copy rewritten or reviewed in the CBRE tone of voice. |

Once it's installed, just describe what you need and Claude runs the right skill.

## Install

**In Claude Cowork:** open **Customize → Plugins → ＋ → Add marketplace → Add from a
repository**, enter `Timobaaij/cbre-il-plugin`, then install **CBRE I&L Toolkit**.

**In Claude Code (CLI):**

```
/plugin marketplace add Timobaaij/cbre-il-plugin
/plugin install cbre-il@cbre
```

## Updating

Each release bumps the plugin `version`, and Claude Code only swaps in a new copy
when that version changes — see the [CHANGELOG](./CHANGELOG.md) for what shipped.

**The reliable way to update (recommended):** remove the marketplace and add it
again. This forces a fresh copy and always lands the latest version.

- **Cowork:** Customize → Plugins → remove **CBRE I&L Toolkit** / its marketplace,
  then re-add it with the steps above.
- **CLI:**
  ```
  /plugin marketplace remove cbre
  /plugin marketplace add Timobaaij/cbre-il-plugin
  /plugin install cbre-il@cbre
  ```

Then restart Claude so the refreshed skills load.

> **Why remove-and-re-add rather than the in-place "update" button?** Claude Code's
> in-place marketplace refresh and plugin auto-update are currently unreliable —
> they can report success or "already up to date" while leaving you on the old
> version ([claude-code#35752](https://github.com/anthropics/claude-code/issues/35752),
> [#61854](https://github.com/anthropics/claude-code/issues/61854)). A fresh add is
> a clean clone and sidesteps the issue. If you prefer the in-place CLI path you can
> still try `/plugin marketplace update cbre` followed by `/plugin update cbre-il@cbre`,
> but verify the version actually changed.

---

### For maintainers

This repository is both the plugin and its marketplace. Skills live in
`plugins/cbre-il/skills/<name>/SKILL.md`. Before sharing changes, validate and
(optionally) load the plugin without installing:

```bash
claude plugin validate .
claude --plugin-dir ./plugins/cbre-il
```

When you ship changes: bump `version` in **both** `plugin.json` and
`marketplace.json` (keep them in sync — `plugin.json` wins), add an entry to the
[CHANGELOG](./CHANGELOG.md), and tag the release (`git tag v0.3.6 && git push origin v0.3.6`).
The version bump is what tells installed clients they are out of date, so a release
without it is invisible to existing users.

Build artifacts (`__pycache__/`, `*.pyc`, `*.bak`) are kept out of git by the root
`.gitignore`; note the GitHub web upload UI bypasses `.gitignore`, so commit from a
clean tree.

Docs: [plugins](https://code.claude.com/docs/en/plugins) ·
[marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) ·
[skills](https://code.claude.com/docs/en/skills)
