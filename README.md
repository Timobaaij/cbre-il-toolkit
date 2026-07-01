# CBRE I&L Toolkit

CBRE Industrial & Logistics skills for [Claude](https://www.claude.com/) — branded
decks, account briefings, outreach angles, property longlists, warehouse-network maps, and on-brand
writing. Packaged as a Claude plugin so the whole team can install it in a couple of
clicks.

## What's inside

| Skill | What it does |
|-------|--------------|
| **Corporate decks** | Polished, CBRE-branded PowerPoint decks built from your content. |
| **Account briefings** | Industrial & Logistics account-briefing decks built from your research. |
| **Outreach angles** | A ranked sheet of evidence-backed reasons to contact a company now — each with a trigger, a way in, and a ready-to-send email hook — as a shareable CBRE-branded HTML file. |
| **Property longlist** | An interactive longlist dashboard from a folder of brochures, emails, and spreadsheets. |
| **Warehouse network mapper** | An auditable Excel of a company's warehouse and distribution network across Europe (or one country), with every facility geocoded from a real address. |
| **CBRE voice** | Any copy rewritten or reviewed in the CBRE tone of voice. |

Once it's installed, just describe what you need and Claude runs the right skill.

## Install

**In Claude Cowork:** open **Customize → Plugins → ＋ → Add marketplace → Add from a
repository**, enter `Timobaaij/cbre-il-toolkit`, then install **CBRE I&L Toolkit**.

**In Claude Code (CLI):**

```
/plugin marketplace add Timobaaij/cbre-il-toolkit
/plugin install cbre-il-toolkit@cbre-il-toolkit
```

## Updating

The toolkit tells you when you're behind: from v0.4.0 on, each skill prints a
one-line "a newer version is available" note at startup, and the
[CHANGELOG](./CHANGELOG.md) lists what changed in each release.

**Step 1 — turn on auto-sync for the marketplace (one time).** This keeps the
marketplace catalogue refreshed automatically, so new versions appear without you
re-adding anything.

- **Cowork:** open **Customize → Plugins → Marketplaces**, click the **CBRE I&L
  Toolkit** marketplace (`cbre-il-toolkit`), and switch **Sync automatically** to **on**.
- **Claude Code (CLI):** run `/plugin` → **Marketplaces** → select **cbre-il-toolkit** →
  **Enable auto-update**. (Or set `"autoUpdate": true` on the marketplace in your
  settings.)

**Step 2 — apply an update when one is available.** Auto-sync refreshes the
*catalogue*; it does not always re-install the plugin by itself. So when you see the
update notice, apply it:

- **Cowork:** **Customize → Plugins → CBRE I&L Toolkit → Update**.
- **CLI:** `/plugin update cbre-il-toolkit@cbre-il-toolkit`.

Then restart Claude so the refreshed skills load.

> **If an update won't take (fallback).** Occasionally the in-place update reports
> "up to date" while staying on the old version. If that happens, remove the
> marketplace and add it again (the Install steps above) — a fresh add always lands
> the latest version.

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
