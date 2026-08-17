#!/usr/bin/env python3
"""deck_output_memory_test.py - a finished deck must stay findable when the manifest shrinks. (B64)

The manifest lists the decks pending THIS pass, and it was also the only record of where each
deck's interpretation output lives. `_vision_supersedes` looked the deck up in it and returned
False when it was absent - so the moment the manifest shrank to the one deck still outstanding,
every FINISHED deck read as un-interpreted: re-prepped, re-listed, and the exit-3 diagnosis
asserted `its interpretation output does not exist yet` for eight files sitting on disk. SKILL.md
tells the orchestrator to satisfy those predicates verbatim and never guess what the guard reads,
so followed literally that is a redundant re-dispatch of every completed reader - the single most
expensive mistake available on a 23-property deck.

What this pins:
  * the durable map remembers a deck's output across a manifest that no longer mentions it;
  * `_vision_supersedes` uses it, so a finished deck stays finished;
  * a deck whose output was recorded but has since been DELETED does not supersede - the map is
    a memory of the path, never a substitute for the file;
  * an assigned path is STABLE: the name derived from a label depends on which other decks share
    the manifest, so without this a deck alone in a one-deck manifest and beside a label-twin in
    a nine-deck one would get two different filenames and strand its own records;
  * `assign_deck_outputs` with no map behaves exactly as before (pure function, unique paths).
Offline; no network, no build.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import run as RUN                        # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def deck(src, label):
    return {"source_file": src, "cluster_label": label, "mode": "text", "pages": []}


def write_manifest(w: Path, decks):
    (w / "vision").mkdir(parents=True, exist_ok=True)
    (w / "vision" / "manifest.json").write_text(json.dumps({"decks": decks}), encoding="utf-8")


def touch_output(w: Path, d):
    p = RUN._deck_output_path(w, d)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([{"park": "P", "__meta": {"source_file": d["source_file"]}}]),
                 encoding="utf-8")
    return p


def main() -> int:
    print("deck_output_memory_test - the manifest is the pending list, not the map")

    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        a, b = deck("Madrid.pdf", "Madrid"), deck("Valencia.pdf", "Valencia")
        RUN.assign_deck_outputs([a, b], RUN.load_deck_outputs(w))
        RUN.save_deck_outputs(w, [a, b])
        write_manifest(w, [a, b])
        touch_output(w, a)
        touch_output(w, b)
        ck(RUN._vision_supersedes(w, "Madrid", "Madrid.pdf"), "both decks supersede while listed")

        # the real shape: the next pass writes a manifest holding ONLY what is still pending
        c = deck("Santa Margarida.pdf", "Santa Margarida")
        RUN.assign_deck_outputs([c], RUN.load_deck_outputs(w))
        RUN.save_deck_outputs(w, [c])
        write_manifest(w, [c])
        ck(RUN._vision_supersedes(w, "Madrid", "Madrid.pdf")
           and RUN._vision_supersedes(w, "Valencia", "Valencia.pdf"),
           "a finished deck STILL supersedes after the manifest shrinks past it")
        ck(not RUN._vision_supersedes(w, "Santa Margarida", "Santa Margarida.pdf"),
           "and the genuinely pending deck still does not")

        RUN._deck_output_path(w, a).unlink()
        ck(not RUN._vision_supersedes(w, "Madrid", "Madrid.pdf"),
           "a remembered path whose FILE is gone does not supersede - memory, not substitute")

        ck(RUN.load_deck_outputs(w).get(RUN._vkey("Valencia.pdf")),
           "the durable map survives every rewrite and is keyed case/diacritic-insensitively")

    # path STABILITY across manifests of different composition
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        solo = deck("Options-A.pdf", "Options")
        RUN.assign_deck_outputs([solo], RUN.load_deck_outputs(w))
        first = solo["output"]
        RUN.save_deck_outputs(w, [solo])
        again = deck("Options-A.pdf", "Options")
        twin = deck("Options-B.pdf", "Options")        # same label -> would force a hashed name
        RUN.assign_deck_outputs([again, twin], RUN.load_deck_outputs(w))
        ck(again["output"] == first,
           "a deck KEEPS its assigned path when a label-twin joins the manifest")
        ck(twin["output"] != again["output"],
           "and the twin still gets a distinct path, so nothing collides")

    # unchanged behaviour with no map
    d1, d2 = deck("A.pdf", "Same"), deck("B.pdf", "Same")
    outs = RUN.assign_deck_outputs([d1, d2])
    ck(len(set(outs)) == 2 and all(o.startswith("work/extract/") for o in outs),
       "with no map the function is unchanged - deterministic and collision-free")
    ck(RUN.assign_deck_outputs([deck("A.pdf", "Same"), deck("B.pdf", "Same")]) == outs,
       "and still order-independent/repeatable")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
