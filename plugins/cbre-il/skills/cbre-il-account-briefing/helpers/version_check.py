#!/usr/bin/env python3
"""version_check.py - best-effort "is a newer CBRE I&L Toolkit available?" nudge.

Compares THIS installed plugin's version (the cbre-il `plugin.json`) against the
latest version published on the marketplace's main branch, and - only if the
installed copy is behind - prints a one-line update hint to STDERR.

Design rules (all enforced here, because this runs at the start of a skill):
  * Best-effort only. ANY problem - offline, DNS, timeout, TLS, parse error,
    missing file - results in SILENCE. Never an error, never a traceback, never
    a non-zero exit. A failed update check must never derail a run.
  * Never blocks. The single network call has a short timeout; nothing else
    touches the network.
  * No telemetry. It performs ONE anonymous HTTP GET of a PUBLIC file. Nothing
    about the user, their machine, or their work is transmitted.
  * Quiet when current. Prints nothing unless a strictly newer version exists.

Safe to run unconditionally and to ignore both its output and its exit code.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

# The authoritative published version lives in plugin.json on the default branch.
RAW_PLUGIN_JSON = (
    "https://raw.githubusercontent.com/Timobaaij/cbre-il-plugin/main/"
    "plugins/cbre-il/.claude-plugin/plugin.json"
)
UPDATE_DOC = "https://github.com/Timobaaij/cbre-il-plugin#updating"
TIMEOUT_S = 2.5


def _find_plugin_json() -> Path | None:
    """Locate the installed cbre-il plugin.json. Prefer the env var Claude Code
    sets for a loaded plugin; otherwise walk up from this file."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        cand = Path(root) / ".claude-plugin" / "plugin.json"
        if cand.is_file():
            return cand
    for parent in Path(__file__).resolve().parents:
        cand = parent / ".claude-plugin" / "plugin.json"
        if cand.is_file():
            return cand
    return None


def _local_version() -> str | None:
    p = _find_plugin_json()
    if not p:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("version")
    except Exception:
        return None


def _remote_version() -> str | None:
    try:
        req = urllib.request.Request(
            RAW_PLUGIN_JSON, headers={"User-Agent": "cbre-il-version-check"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8")).get("version")
    except Exception:
        return None


def _parse(v: str) -> tuple:
    """'0.4.1' -> (0, 4, 1). A non-numeric piece compares as 0 so a malformed
    value can never masquerade as newer."""
    out = []
    for piece in str(v).split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _is_newer(remote: str, local: str) -> bool:
    try:
        return _parse(remote) > _parse(local)
    except Exception:
        return False


def main() -> int:
    local = _local_version()
    if not local:
        return 0  # can't determine our own version -> stay silent
    remote = _remote_version()
    if not remote or not _is_newer(remote, local):
        return 0  # current, or offline/unknown -> stay silent
    print(
        f"[update] CBRE I&L Toolkit {remote} is available (you have {local}).",
        file=sys.stderr,
    )
    print(
        f"[update] Update by removing and re-adding the marketplace: {UPDATE_DOC}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # an update check must never fail a run
