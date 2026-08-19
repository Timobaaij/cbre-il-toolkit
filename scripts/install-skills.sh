#!/usr/bin/env bash
#
# install-skills.sh - install the CBRE I&L Toolkit and UK I&L Toolkit skills
# into ~/.claude/skills as plain, standalone Claude Code skills.
#
# This is the alternative to installing the plugins from the marketplace. Use it
# when you want the skills available in every project without the plugin layer,
# or when you are working somewhere the marketplace is not reachable.
#
# Usage:
#   ./scripts/install-skills.sh              # install into ~/.claude/skills
#   ./scripts/install-skills.sh --dry-run    # list what would be installed
#   ./scripts/install-skills.sh --dest DIR   # install somewhere else
#
# Re-running is safe: each skill directory is replaced atomically, so an
# interrupted run can never leave a half-written skill behind.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HOME}/.claude/skills"
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --dest)    DEST="${2:?--dest needs a directory}"; shift 2 ;;
    # Print the header comment block: line 2 through the first blank line.
    -h|--help) sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# Every skill shipped by the two plugins in this marketplace.
PLUGIN_DIRS=(
  "${REPO_ROOT}/plugins/cbre-il/skills"
  "${REPO_ROOT}/plugins/uk-il/skills"
)

installed=0

for plugin_skills in "${PLUGIN_DIRS[@]}"; do
  if [ ! -d "${plugin_skills}" ]; then
    echo "skipping missing plugin skills dir: ${plugin_skills}" >&2
    continue
  fi

  for skill_src in "${plugin_skills}"/*/; do
    skill_src="${skill_src%/}"
    name="$(basename "${skill_src}")"

    # A directory without a SKILL.md is not a skill.
    if [ ! -f "${skill_src}/SKILL.md" ]; then
      echo "skipping ${name}: no SKILL.md" >&2
      continue
    fi

    if [ "${DRY_RUN}" -eq 1 ]; then
      echo "would install ${name} -> ${DEST}/${name}"
      installed=$((installed + 1))
      continue
    fi

    mkdir -p "${DEST}"

    # Stage into a temp dir next to the target, then swap, so a failure mid-copy
    # leaves the previously installed version untouched.
    staging="${DEST}/.${name}.incoming.$$"
    rm -rf "${staging}"
    cp -R "${skill_src}" "${staging}"
    rm -rf "${DEST}/${name}"
    mv "${staging}" "${DEST}/${name}"

    echo "installed ${name}"
    installed=$((installed + 1))
  done
done

if [ "${DRY_RUN}" -eq 1 ]; then
  echo "${installed} skill(s) would be installed into ${DEST}"
else
  echo "${installed} skill(s) installed into ${DEST}"
  echo "Restart Claude Code (or start a new session) to pick them up."
fi
