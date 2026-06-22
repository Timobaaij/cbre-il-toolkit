#!/usr/bin/env python3
"""shell_guard_hook.py - PreToolUse guard that keeps this skill's helpers OFF the sandbox bash.

On a host with `mcp__shell__run_command` (native Windows Python + PyMuPDF), the skill MUST run
its helpers there: the sandboxed bash (`mcp__workspace__bash`) uses dependency shims that degrade
extraction and push the run into the vision fallback. `setup_permissions.py` wires this into the
user's `settings.json` as a PreToolUse hook on `mcp__workspace__bash`; it DENIES a sandbox-bash
call that targets a skill helper and redirects the model to `mcp__shell`. It fires ONLY on that
exact mis-step (the matcher + the signals below); every other sandbox-bash call passes through.

Ships WITH the skill so the enforcement travels to every colleague who installs it (the doc alone
could not reliably override the model's habit of defaulting to the sandbox bash). Reads the
PreToolUse payload on stdin; importing it has no side effect (the logic is under __main__).
"""
from __future__ import annotations

import json
import sys

# The skill folder name catches every absolute-path call (the documented convention);
# 'helpers/run.py' + the skill-DISTINCTIVE basenames catch a relative call too. Generic helper
# names (merge/deliver/preflight/intake/normalize/images/ledger/match) are deliberately omitted
# so this can never over-fire on an unrelated project's similarly-named script.
_SIGNALS = (
    "cbre-property-longlist", "helpers/run.py",
    "web_enrich.py", "gate_runner.py", "vision_prep.py", "make_integrity.py",
    "contact_sheet.py", "render_qa.py",
    "build_cities_dataset.py", "build_regions_dataset.py", "build_poi_dataset.py",
    "seed_geocode.py",
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unparseable payload -> never interfere
    cmd = ((payload.get("tool_input") or {}).get("command") or "")
    low = cmd.lower().replace("\\", "/")  # normalise separators so helpers\run.py == helpers/run.py
    if any(s in low for s in _SIGNALS):
        reason = (
            "BLOCKED: run cbre-property-longlist helpers via mcp__shell__run_command with the "
            "absolute Windows path, NOT the sandbox bash. The sandbox uses dependency shims "
            "(degraded extraction -> vision fallback); mcp__shell runs native Windows Python "
            "with PyMuPDF for accurate spec-table / area / clear-height / rent extraction. "
            "Re-issue as:\n  mcp__shell__run_command: " + cmd
        )
        # current Claude Code PreToolUse deny format + legacy keys (harmless on newer harnesses)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
            "decision": "block",
            "reason": reason,
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
