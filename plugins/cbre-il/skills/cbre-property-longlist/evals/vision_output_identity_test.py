#!/usr/bin/env python3
"""vision_output_identity_test.py - two decks sharing a cluster label must not share an output. (B2)

THE DEFECT, and it was baited by the skill's own instructions. The interpretation output path was
DERIVED by the sub-agent as `work/extract/<cluster_label>_vision.json`, while SKILL.md tells the
orchestrator to refine ambiguous filename clusters onto a city label before confirming project.yaml.
Do both - which is the documented workflow - and four Corby brochures share ONE output path: four
concurrently dispatched agents write the same file and three decks are lost with no error, no gate
and no gap line. The property count silently drops.

Renaming the file was not enough on its own, which is why this is keyed to the SOURCE FILE instead.
The label was load-bearing in two further places, both by filename string match:
`run._vision_supersedes` (whether a deck's deterministic records are superseded - getting this wrong
duplicates properties, the documented "71 cards from ~35 properties" bug) and the `vision_done` scan
(whether a region still needs interpretation - getting this wrong re-preps the deck forever, the
exit-3 livelock the `_vkey` docstring records).

Offline, pure path logic - no build, no extraction."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import run as R  # noqa: E402

CORBY = ("Earlstree 160 Corby.pdf", "Evo-corby-169-brochure.pdf",
         "Raven Park_Brochure_V8.1.pdf", "lba-saxon132-brochure-nov25-1.pdf")


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # --- the exact shape the documented cluster refinement produces --------- #
    decks = [{"source_file": f, "cluster_label": "Corby"} for f in CORBY]
    outs = R.assign_deck_outputs(decks)
    ck(len(set(outs)) == 4, f"four decks sharing ONE label -> four DISTINCT outputs {ascii(str(outs))}")
    ck(all(o.endswith("_vision.json") for o in outs),
       "every output keeps the *_vision.json suffix that merge and vision_validate glob for")
    ck(all(d.get("output") for d in decks), "the path is written onto each deck entry")
    ck(all(o.startswith("work/extract/") for o in outs), "outputs live in work/extract/")

    # deterministic across runs - the path is hashed from source_file, never from ordering
    ck(R.assign_deck_outputs([dict(source_file=f, cluster_label="Corby") for f in CORBY]) == outs,
       "assignment is deterministic for the same inputs")
    shuffled = list(reversed(CORBY))
    out_s = R.assign_deck_outputs([dict(source_file=f, cluster_label="Corby") for f in shuffled])
    ck(set(out_s) == set(outs), "...and order-independent: the same file always gets the same path")

    # --- the common case must stay readable -------------------------------- #
    solo = R.assign_deck_outputs([{"source_file": "One.pdf", "cluster_label": "Valencia"}])
    ck(solo[0] == "work/extract/Valencia_vision.json",
       f"a label used by ONE deck keeps its clean filename {ascii(solo[0])}")
    two = R.assign_deck_outputs([{"source_file": "a.pdf", "cluster_label": "Valencia"},
                                 {"source_file": "b.pdf", "cluster_label": "Madrid"}])
    ck(two == ["work/extract/Valencia_vision.json", "work/extract/Madrid_vision.json"],
       f"distinct labels are both left clean {ascii(str(two))}")

    # a label that is only a separator/case variant of another still collides on _vkey, and must
    # therefore be disambiguated too - that is exactly what the supersede matcher folds together
    vk = R.assign_deck_outputs([{"source_file": "a.pdf", "cluster_label": "East Midlands"},
                                {"source_file": "b.pdf", "cluster_label": "East_Midlands"}])
    ck(len(set(vk)) == 2, f"separator variants of one label do NOT collide {ascii(str(vk))}")

    # an empty/missing label must still produce a usable unique path, never a bare '_vision.json'
    blank = R.assign_deck_outputs([{"source_file": "x.pdf", "cluster_label": ""},
                                   {"source_file": "y.pdf", "cluster_label": ""}])
    ck(len(set(blank)) == 2 and all(len(Path(b).name) > len("_vision.json") for b in blank),
       f"blank labels still yield distinct, non-empty names {ascii(str(blank))}")

    # a label with path-hostile characters must not escape work/extract/
    nasty = R.assign_deck_outputs([{"source_file": "z.pdf", "cluster_label": "../../etc/passwd"}])
    ck("/.." not in nasty[0] and nasty[0].startswith("work/extract/")
       and Path(nasty[0]).name.endswith("_vision.json"),
       f"a hostile label is sanitised, never a traversal {ascii(nasty[0])}")

    # --- completion + supersession are keyed to the deck's OWN output ------- #
    d = Path(tempfile.mkdtemp(prefix="cbre_vout_"))
    (d / "extract").mkdir(parents=True, exist_ok=True)
    deck = {"source_file": "Earlstree 160 Corby.pdf", "cluster_label": "Corby",
            "output": "work/extract/Corby__deadbeef_vision.json"}
    p = R._deck_output_path(d, deck)
    ck(p is not None and p.name == "Corby__deadbeef_vision.json",
       f"the deck's output resolves under the work dir {ascii(str(p))}")
    ck(not R._deck_interpreted(d, deck), "an absent output means NOT yet interpreted")
    p.write_text("[]", encoding="utf-8")
    ck(R._deck_interpreted(d, deck), "the output existing means interpreted - keyed to THIS deck")

    # a sibling deck sharing the label is NOT satisfied by the first deck's file
    sib = {"source_file": "Evo-corby-169-brochure.pdf", "cluster_label": "Corby",
           "output": "work/extract/Corby__feedface_vision.json"}
    ck(not R._deck_interpreted(d, sib),
       "a SIBLING deck on the same label is not satisfied by its neighbour's output - the bug")

    # --- legacy manifests keep working ------------------------------------- #
    legacy = {"source_file": "Old.pdf", "cluster_label": "Valencia"}   # no `output` key
    ck(R._deck_output_path(d, legacy) is None,
       "a legacy deck entry with no `output` returns None, so the caller falls back")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
