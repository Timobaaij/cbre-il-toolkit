#!/usr/bin/env python3
"""f16_cluster_label_note_test.py - a cluster label's reasoning has somewhere to land. (F16)

THE LIVE FAILURE. The cluster-label sub-agent reported two genuine either-way calls in its final
chat message (an estate name vs an address village; a city vs a more specific settlement). Those
are routing labels only, so the agent was right not to block - but the reasoning reached the
orchestrator's chat and evaporated: intake_clusters.json carried the chosen label with no field
for "this was a close call between X and Y". A surprising label on a later run had no trail.

The contract pinned here (intake's half; the prompt that asks for the field and the Gaps Report
row that prints it are other owners'):
  1. each `labels[]` entry MAY carry an optional string `note`;
  2. intake PRESERVES it: inventory.json gains a top-level `cluster_label_notes` list of
     {stem, region, country, note}, one entry per label that carried a non-empty note;
  3. intake IGNORES it safely: absent -> no entry; non-string / blank -> no entry; the whole
     cache is NEVER discarded because of the note (it is optional), and a runaway note is
     capped, never dropped;
  4. the key is ALWAYS present (empty on a regex-only run) so a reader never guesses;
  5. the note reaches NO cluster key and NO card: the region label is exactly what it was.
Offline.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import intake as IN  # noqa: E402

fails: list[str] = []


def ck(cond, name):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


def corpus():
    root = Path(tempfile.mkdtemp(prefix="cbre_f16_"))
    (root / "Options-Fenwick.pdf").write_bytes(b"a")
    (root / "Brochure Two.pdf").write_bytes(b"b")
    ih = IN._brochure_input_hash(["Brochure Two.pdf", "Options-Fenwick.pdf"])
    return root, ih


NOTE = "Fenwick (the estate) or Ashcombe (the address village); chose the estate name"

# ---------------------------------------------------------------- 1-2. preserved
root, ih = corpus()
cache = {"input_hash": ih, "schema_version": 1,
         "labels": [{"stem": "Options-Fenwick", "region": "Fenwick", "country": "XX", "note": NOTE},
                    {"stem": "Brochure Two", "region": "Ashcombe"}]}
inv = IN.discover(root, cluster_cache=cache)
notes = inv.get("cluster_label_notes")
ck(isinstance(notes, list) and len(notes) == 1,
   f"one label carried a note -> ONE cluster_label_notes entry (got {notes!r})")
ck(notes and notes[0] == {"stem": "Options-Fenwick", "region": "Fenwick", "country": "XX", "note": NOTE},
   "the entry carries stem, the applied region, the applied country and the note verbatim")
ck("Fenwick" in inv["clusters"] and "Ashcombe" in inv["clusters"],
   "both labels are applied as before - the note changes NO cluster key")
ck(json.dumps(inv["clusters"]).count(NOTE) == 0,
   "the note is NOT copied into the cluster entries (it is not routing data)")
# the verifier exposes it as the third element of the override tuple
ov = IN._verified_cluster_overrides(cache, ih, {"Options-Fenwick", "Brochure Two"})
ck(ov.get("Options-Fenwick") == ("Fenwick", "XX", NOTE) and ov.get("Brochure Two") == ("Ashcombe", "", ""),
   "the verifier returns (region, country, note), '' when the note is absent")

# ---------------------------------------------------------------- 3. ignored safely
for bad, why in ((None, "null"), (12, "a number"), (["x"], "a list"), ("   ", "whitespace")):
    c2 = {"input_hash": ih, "schema_version": 1,
          "labels": [{"stem": "Options-Fenwick", "region": "Fenwick", "note": bad}]}
    iv = IN.discover(root, cluster_cache=c2)
    ck("Fenwick" in iv["clusters"] and iv["cluster_label_notes"] == [],
       f"a {why} note is ignored: the label is STILL applied and no note entry is written")
long = "x" * 5000
c3 = {"input_hash": ih, "schema_version": 1,
      "labels": [{"stem": "Options-Fenwick", "region": "Fenwick", "note": long}]}
iv = IN.discover(root, cluster_cache=c3)
ck(iv["cluster_label_notes"] and len(iv["cluster_label_notes"][0]["note"]) == IN._NOTE_MAX_CHARS,
   f"a runaway note is capped at {IN._NOTE_MAX_CHARS} chars, not dropped and not shipped whole")

# ---------------------------------------------------------------- 4. always present
iv0 = IN.discover(root)
ck(iv0.get("cluster_label_notes") == [],
   "a regex-only run (no cache) publishes an EMPTY list, so the key always exists")
iv1 = IN.discover(root, cluster_cache={"input_hash": "stale", "labels": [{"stem": "Options-Fenwick", "region": "Fenwick", "note": NOTE}]})
ck(iv1.get("cluster_label_notes") == [] and "Options-Fenwick" in iv1["clusters"],
   "a REJECTED cache contributes no note either (a note is only as trusted as its label)")

# ---------------------------------------------------------------- 5. the docs name the seam
src = (ROOT / "helpers" / "intake.py").read_text(encoding="utf-8")
ck("Noted, not put to you" in src,
   "intake names where the note is meant to land (the Gaps Report section), for the owner wiring it")

print("\nF16 CLUSTER LABEL NOTE TEST: " + ("FAIL" if fails else "PASS"))
sys.exit(1 if fails else 0)
