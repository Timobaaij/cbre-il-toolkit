---
name: example-skill
description: Template skill — REPLACE THIS. In one or two sentences say what the skill does and, most importantly, WHEN Claude should use it (the trigger situation plus keywords a user might say). Claude reads this description to decide when to auto-invoke the skill, so be specific.
---

# Example skill (template)

> Delete this folder once you've added your real CBRE skills. It only exists to
> demonstrate the format.

Everything below the YAML frontmatter is markdown, and it becomes the skill's
instructions. Write clear, step-by-step guidance that tells Claude exactly how
to carry out the task.

## How to turn this into a real skill

1. Copy this folder and rename it to your skill's name in kebab-case, e.g.
   `skills/lease-abstraction/`.
2. Update `name` and `description` in the frontmatter above. The `description`
   is the single most important field — it is how Claude decides when to use
   the skill.
3. Replace this body with your actual instructions.
4. (Optional) Add supporting files next to `SKILL.md` — reference docs, scripts,
   templates, checklists — and refer to them from the body. Use
   `${CLAUDE_PLUGIN_ROOT}` to build paths to bundled files.

## Optional frontmatter you can add

- `allowed-tools` — tools the skill may use without prompting, e.g.
  `Bash(git *) Read`
- `disable-model-invocation: true` — the skill is only run manually via
  `/cbre-il:example-skill`, never auto-invoked by Claude
- `argument-hint` / `arguments` — for skills that take input arguments

Once installed, this skill is available as `/cbre-il:example-skill` (the plugin
name namespaces every skill it ships).
