# cbre-il-plugin

A shareable [Claude Code](https://code.claude.com/docs/en/overview) plugin for
CBRE skills. This repo is **both a plugin and a marketplace**, so colleagues can
add it and install the plugin in two commands.

## Repository layout

```
cbre-il-plugin/
├── .claude-plugin/
│   └── marketplace.json          # the shareable catalog (lists the plugin below)
├── plugins/
│   └── cbre-il/
│       ├── .claude-plugin/
│       │   └── plugin.json        # the plugin manifest
│       ├── skills/
│       │   └── example-skill/
│       │       └── SKILL.md       # one folder per skill
│       └── README.md
└── README.md
```

## Install (for your colleagues)

Inside any Claude Code session:

```
/plugin marketplace add timobaaij/cbre-il-plugin
/plugin install cbre-il@cbre
```

- `cbre-il` is the plugin name, `cbre` is the marketplace name (from
  `marketplace.json` → `name`).
- After installing, the plugin's skills appear as `/cbre-il:<skill-name>` and
  Claude can auto-invoke them based on each skill's `description`.

To update later: `/plugin marketplace update cbre` then re-install/enable.

## Add your own CBRE skills

1. Create a folder per skill under `plugins/cbre-il/skills/`, named in
   kebab-case (e.g. `skills/lease-abstraction/`).
2. Add a `SKILL.md` with frontmatter (`name`, `description`) + markdown
   instructions. Copy `plugins/cbre-il/skills/example-skill/SKILL.md` to start.
3. The `description` controls *when* Claude uses the skill — be specific about
   the trigger situation and keywords.
4. Delete `example-skill/` once you've added real skills.
5. Bump `version` in both `plugin.json` and `marketplace.json`, then commit and push.

> Tip: if you already have skills on your machine under `~/.claude/skills/`,
> copy each skill folder into `plugins/cbre-il/skills/` and commit it here.

## Test locally before sharing

```bash
# validate the plugin and marketplace manifests
claude plugin validate ./plugins/cbre-il
claude plugin validate .

# load the plugin in a session without installing it
claude --plugin-dir ./plugins/cbre-il
```

## Docs

- Plugins — https://code.claude.com/docs/en/plugins
- Plugin marketplaces — https://code.claude.com/docs/en/plugin-marketplaces
- Skills — https://code.claude.com/docs/en/skills
