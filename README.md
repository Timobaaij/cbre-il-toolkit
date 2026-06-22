# CBRE I&L Toolkit

CBRE Industrial & Logistics skills for [Claude](https://www.claude.com/) — branded
decks, account briefings, property longlists, and on-brand writing. Packaged as a
Claude plugin so the whole team can install it in a couple of clicks.

## What's inside

| Skill | What it does |
|-------|--------------|
| **Corporate decks** | Polished, CBRE-branded PowerPoint decks built from your content. |
| **Account briefings** | Industrial & Logistics account-briefing decks built from your research. |
| **Property longlist** | An interactive longlist dashboard from a folder of brochures, emails, and spreadsheets. |
| **CBRE voice** | Any copy rewritten or reviewed in the CBRE tone of voice. |

Once it's installed, just describe what you need and Claude runs the right skill.

## Install

**In Claude Cowork:** open **Customize → Plugins → ＋ → Add marketplace → Add from a
repository**, enter `timobaaij/cbre-il-plugin`, then install **CBRE I&L Toolkit**.

**In Claude Code (CLI):**

```
/plugin marketplace add timobaaij/cbre-il-plugin
/plugin install cbre-il@cbre
```

To get updates later: re-sync the marketplace (Cowork) or run
`/plugin marketplace update cbre` (CLI).

---

### For maintainers

This repository is both the plugin and its marketplace. Skills live in
`plugins/cbre-il/skills/<name>/SKILL.md`. Before sharing changes, validate and
(optionally) load the plugin without installing:

```bash
claude plugin validate .
claude --plugin-dir ./plugins/cbre-il
```

Bump `version` in both `plugin.json` and `marketplace.json` when you ship changes.
Build artifacts (`__pycache__/`, `*.pyc`, `*.bak`) are kept out of git by the root
`.gitignore`; note the GitHub web upload UI bypasses `.gitignore`, so commit from a
clean tree.

Docs: [plugins](https://code.claude.com/docs/en/plugins) ·
[marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) ·
[skills](https://code.claude.com/docs/en/skills)
