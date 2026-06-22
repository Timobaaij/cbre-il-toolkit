# cbre-il

CBRE IL skills for Claude Code, packaged as a plugin.

## What's in here

```
plugins/cbre-il/
├── .claude-plugin/
│   └── plugin.json          # plugin manifest (name, version, author)
└── skills/
    └── <skill-name>/
        └── SKILL.md         # one folder per skill
```

## Adding a skill

1. Create a folder under `skills/` named in kebab-case (e.g. `skills/lease-abstraction/`).
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown
   instructions in the body. Copy `skills/example-skill/SKILL.md` as a starting point.
3. The `description` field is what Claude uses to decide when to auto-invoke the
   skill — make it specific about *when* to use it.

Each skill becomes available as `/cbre-il:<skill-name>` once the plugin is installed.

## Versioning

Bump `version` in `.claude-plugin/plugin.json` (and the matching entry in the
repo's `.claude-plugin/marketplace.json`) whenever you ship changes. Installed
users only pull updates when the version changes.
