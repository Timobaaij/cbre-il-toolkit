#!/usr/bin/env python3
"""setup_permissions.py - ONE-TIME, explicit pre-approval of the skill's web access.

Without pre-approval, every orchestrator-side WebSearch/WebFetch raises a
permission prompt and an unattended run stops dead. This merges allow rules into
the USER-level ~/.claude/settings.json (persists across sessions and projects)
for exactly two groups, nothing broader:

  CORE (fixed fetch infrastructure): the ORS trucking matrix, the OSRM fallback,
  Nominatim geocoding, Overpass (only if the bundled POI dataset is ever absent).

  RESEARCH (the --regions labour-data sub-agent): WebSearch plus the OFFICIAL
  European statistics offices - Eurostat and the national offices, i.e. where
  most labour figures happen to live. This is CONVENIENCE ONLY: the researcher
  always uses the BEST source for each figure, and a better source that is not
  on this list is still the right choice - it just raises one prompt.

Run once per machine/user (each colleague runs it themselves - a skill must never
silently grant itself network access):

    python helpers/setup_permissions.py        # show what would change
    python helpers/setup_permissions.py --yes  # apply

NOTE: a settings change takes effect after a session restart (or /hooks reload).
The browser artifact (web_enrich.html) needs no permissions at all - it runs in
YOUR browser and stays the preferred path for the big fetch batches.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# fixed fetch infrastructure (routing / geocoding / POI fallback)
CORE_RULES = [
    "WebFetch(domain:api.openrouteservice.org)",
    "WebFetch(domain:router.project-osrm.org)",
    "WebFetch(domain:nominatim.openstreetmap.org)",
    "WebFetch(domain:overpass-api.de)",
]

# labour-data research (the --regions sub-agent): WebSearch plus the official
# European statistics offices - pre-approved because most figures live there,
# NOT because the researcher is steered to them (best source always wins; an
# off-list source simply raises one prompt).
RESEARCH_RULES = [
    "WebSearch",
    "WebFetch(domain:ec.europa.eu)",          # Eurostat
    "WebFetch(domain:ine.es)",                # Spain
    "WebFetch(domain:destatis.de)",           # Germany
    "WebFetch(domain:insee.fr)",              # France
    "WebFetch(domain:istat.it)",              # Italy
    "WebFetch(domain:cbs.nl)",                # Netherlands
    "WebFetch(domain:statbel.fgov.be)",       # Belgium
    "WebFetch(domain:czso.cz)",               # Czechia
    "WebFetch(domain:slovak.statistics.sk)",  # Slovakia
    "WebFetch(domain:statistics.sk)",
    "WebFetch(domain:ksh.hu)",                # Hungary
    "WebFetch(domain:stat.gov.pl)",           # Poland
    "WebFetch(domain:ine.pt)",                # Portugal
    "WebFetch(domain:statistik.at)",          # Austria
    "WebFetch(domain:bfs.admin.ch)",          # Switzerland
    "WebFetch(domain:ons.gov.uk)",            # United Kingdom
    "WebFetch(domain:cso.ie)",                # Ireland
    "WebFetch(domain:dst.dk)",                # Denmark
    "WebFetch(domain:scb.se)",                # Sweden
    "WebFetch(domain:ssb.no)",                # Norway
    "WebFetch(domain:stat.fi)",               # Finland
    "WebFetch(domain:insse.ro)",              # Romania
    "WebFetch(domain:nsi.bg)",                # Bulgaria
    "WebFetch(domain:stat.si)",               # Slovenia
    "WebFetch(domain:dzs.hr)",                # Croatia
    "WebFetch(domain:stat.ee)",               # Estonia
    "WebFetch(domain:stat.gov.lv)",           # Latvia
    "WebFetch(domain:osp.stat.gov.lt)",       # Lithuania
]

RULES = CORE_RULES + RESEARCH_RULES

# A PreToolUse hook that keeps the skill's helpers OFF the sandboxed bash (mcp__workspace__bash) -
# whose dependency shims degrade extraction and push the run into the vision fallback - and
# redirects the model to mcp__shell__run_command. The hook script SHIPS WITH the skill
# (helpers/shell_guard_hook.py), so the enforcement travels to every colleague; we point the
# user's settings.json at this machine's copy of it. Requires the host to have mcp__shell (and,
# for the automated exit-8 fetch, the Playwright MCP).
HOOK_SCRIPT = Path(__file__).resolve().parent / "shell_guard_hook.py"
HOOK_MATCHER = "mcp__workspace__bash"


def _hook_entry() -> dict:
    return {"matcher": HOOK_MATCHER,
            "hooks": [{"type": "command", "command": f'python "{HOOK_SCRIPT.as_posix()}"'}]}


def _is_cbre_guard(entry) -> bool:
    s = json.dumps(entry)
    return "shell_guard_hook.py" in s or "cbre_longlist_shell_guard" in s


def _hook_present_correct(settings: dict) -> bool:
    return _hook_entry() in ((settings.get("hooks") or {}).get("PreToolUse") or [])


def _install_hook(settings: dict) -> None:
    """Add the shell-guard PreToolUse hook, idempotently. Drops any prior cbre guard entry first
    (a legacy ~/.claude/hooks standalone, or an older skill path) so re-running never duplicates."""
    hooks = settings.setdefault("hooks", {})
    cleaned = [e for e in (hooks.get("PreToolUse") or []) if not _is_cbre_guard(e)]
    hooks["PreToolUse"] = cleaned + [_hook_entry()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true", help="apply (default: dry-run preview)")
    ap.add_argument("--settings", default=str(Path.home() / ".claude" / "settings.json"),
                    help="settings file to merge into (default: user-level)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    f = Path(args.settings)
    try:
        settings = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception as e:
        print(f"Cannot read {f} ({e}) - fix or remove it first; NOT touching it.")
        return 1
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    missing = [r for r in RULES if r not in allow]
    hook_ok = _hook_present_correct(settings)
    if not missing and hook_ok:
        print(f"OK - all {len(RULES)} fetch-domain rules + the shell-guard hook already present in {f}")
        return 0
    if missing:
        print(f"Would add {len(missing)} allow rule(s) to {f}:")
        for r in missing:
            print(f"  + {r}")
    if not hook_ok:
        if not HOOK_SCRIPT.exists():
            print(f"WARNING: {HOOK_SCRIPT} is missing - the shell-guard hook will not be installed.")
        else:
            print(f"Would install the PreToolUse shell-guard hook (matcher '{HOOK_MATCHER}') -> "
                  f"{HOOK_SCRIPT.as_posix()}\n  (keeps the skill's helpers off the sandbox bash; "
                  f"redirects them to mcp__shell__run_command for native PyMuPDF extraction)")
    if not args.yes:
        print("\nDry-run only. Re-run with --yes to apply.")
        return 0
    if f.exists():  # keep a backup - we are editing the user's settings
        backup = f.with_suffix(".json.bak")
        backup.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  (backup -> {backup})")
    allow.extend(missing)
    if HOOK_SCRIPT.exists():
        _install_hook(settings)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print("OK - merged permissions + installed the shell-guard hook. "
          "Takes effect after a session restart (or /hooks reload).")
    return 0


if __name__ == "__main__":
    main()
