#!/usr/bin/env python3
"""ack_merge_test.py - placeholder_audit_ack.json must survive concurrent writers. (B63)

The images gate and the arithmetic gate both point the orchestrator at this one file, and the
QA window tells it to dispatch gate fixes CONCURRENTLY. Each agent authored the document
whole, so on a live run the second silently dropped the first's `arithmetic_ok` and a gate
that had already been answered re-blocked on the next pass. Nothing about the file's shape
caused that - the absence of a merge path did.

What this pins:
  * two `ack --add` calls for DIFFERENT keys both survive (the clobber that actually happened);
  * a second call for the SAME key unions rather than replaces, and de-duplicates;
  * values are order-stable, so a re-run is byte-identical;
  * `--note` appends and `--verified-by` sets, without touching the lists;
  * a corrupt file BLOCKS rather than being overwritten - this records what a reviewer has
    signed off, so silently discarding it is the one outcome that must be impossible;
  * the merged file is exactly what the images gate reads back.
Offline; no network, no build.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GR = ROOT / "helpers" / "gate_runner.py"
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def ack(work, *args):
    return subprocess.run([sys.executable, str(GR), "ack", "--work", str(work), *args],
                          capture_output=True, text=True)


def read(work):
    return json.loads((Path(work) / "placeholder_audit_ack.json").read_text(encoding="utf-8"))


def main() -> int:
    print("ack_merge_test - read-modify-write, never author-whole")

    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        r1 = ack(w, "--add", "nonphoto_hero_ok=8,9,12")
        ck(r1.returncode == 0 and "ALL-PASS" in r1.stdout, "first write creates the file")
        # the exact clobber from the live run: a SECOND agent, a DIFFERENT key
        r2 = ack(w, "--add", "arithmetic_ok=25")
        ck(r2.returncode == 0, "second writer succeeds")
        d = read(w)
        ck(d.get("arithmetic_ok") == ["25"], "the second writer's key is present")
        ck(d.get("nonphoto_hero_ok") == ["8", "9", "12"],
           "the FIRST writer's key survived - this is the regression that shipped")

        ack(w, "--add", "nonphoto_hero_ok=22,23")
        ck(read(w)["nonphoto_hero_ok"] == ["8", "9", "12", "22", "23"],
           "same key unions in order rather than replacing")
        ack(w, "--add", "nonphoto_hero_ok=9,22")
        ck(read(w)["nonphoto_hero_ok"] == ["8", "9", "12", "22", "23"],
           "re-adding an existing value is a no-op - de-duplicated and order-stable")

        before = (w / "placeholder_audit_ack.json").read_bytes()
        ack(w, "--add", "nonphoto_hero_ok=9")
        ck((w / "placeholder_audit_ack.json").read_bytes() == before,
           "a no-op write is byte-identical, so re-running changes nothing")

        ack(w, "--note", "checked page by page against each deck.",
            "--verified-by", "t@cbre.com")
        d = read(w)
        ck(d.get("verified_by") == "t@cbre.com" and "page by page" in d.get("note", ""),
           "--note and --verified-by land without disturbing the lists")
        ck(d["nonphoto_hero_ok"] == ["8", "9", "12", "22", "23"] and d["arithmetic_ok"] == ["25"],
           "and both lists are still intact afterwards")

        # the images gate must read back exactly what we merged
        ck(set(str(x) for x in read(w)["nonphoto_hero_ok"]) == {"8", "9", "12", "22", "23"},
           "the merged file is what a gate reads back")

    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        (w / "placeholder_audit_ack.json").write_text("{ not json", encoding="utf-8")
        r = ack(w, "--add", "arithmetic_ok=25")
        ck(r.returncode == 1 and "BLOCKED" in r.stdout,
           "a corrupt ack file BLOCKS instead of being overwritten")
        ck((w / "placeholder_audit_ack.json").read_text(encoding="utf-8") == "{ not json",
           "and the unreadable file is left exactly as it was")

    with tempfile.TemporaryDirectory() as td:
        r = ack(Path(td), "--add", "nokeyvalue")
        ck(r.returncode == 1 and "BLOCKED" in r.stdout, "a malformed --add is refused")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
