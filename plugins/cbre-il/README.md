# CBRE I&L Toolkit

A set of CBRE Industrial & Logistics skills for Claude. Describe what you need in
plain language — Claude picks the right skill automatically, so there's nothing to
memorize.

## What's inside

| Skill | What it does for you |
|-------|----------------------|
| **Corporate decks** | Builds a polished, fully CBRE-branded PowerPoint deck from your content — the right fonts, colours, and editorial layout, story-led by default. |
| **Account briefings** | Turns your research into a sharp Industrial & Logistics account-briefing deck. |
| **Property longlist** | Turns a folder of brochures, emails, and spreadsheets into one interactive, filterable longlist dashboard — card grid, map, and side-by-side comparison. |
| **CBRE voice** | Rewrites or reviews any copy so it reads unmistakably like CBRE. |

Just ask — for example: *"Build me a CBRE deck on the Q3 logistics market,"*
*"Turn this folder of brochures into a longlist for client X,"* or *"Make this
paragraph sound like CBRE."*

---

### For maintainers

Skills live in `skills/<name>/SKILL.md`, each alongside its own supporting files.
To add one: create the folder, then write a `SKILL.md` with YAML frontmatter
(`name`, `description`) and markdown instructions. The `description` is what tells
Claude *when* to use the skill, so make it specific (and if it contains a
colon-space, quote it or use a `>-` block scalar so the YAML stays valid).

Bump `version` in `.claude-plugin/plugin.json` and the repo's
`.claude-plugin/marketplace.json` whenever you ship changes — installed users only
pull updates when the version changes.
