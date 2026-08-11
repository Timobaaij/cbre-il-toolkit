#!/usr/bin/env python3
"""exit10_rounds_test.py - exit 10 stops costing two round-trips when it does not have
to, and round 2 can no longer destroy round 1's answers. (B20)

The backlog asked for the two rounds to be MERGED. They cannot be: a grey pair verdict
changes cluster membership, which changes both which value conflicts exist and their
conflict_id. That is a true data dependency. What IS fixable:

  1. Pull forward the conflicts that no outstanding pair answer can move. A cluster none
     of whose members appears in an unanswered grey pair has FINAL membership - links are
     only ever added, never removed, and any record that could join it would have to do so
     through a pair involving one of its own members. In the common case this collapses
     the run to a single exit 10.
  2. Stop round 2 re-listing the settled pairs. Today it re-emits them, which re-dispatches
     two sub-agents for nothing AND lets a re-dispatched author return one different
     verdict, re-keying the very conflicts being adjudicated in that round.

Piece 2's hazard is that a literal-minded agent writes an empty match_decisions.json and
clobbers the settled verdicts - a straight route to a third round. The instruction alone
is not a guard, so the load path MERGES over a durable settled copy. That is asserted here.

The oracle CANNOT cover any of this: it re-renders from a fixed canonical fixture and never
executes run.py's exit-10 block. This suite is the only net. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import run as RUN  # noqa: E402

SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def _r(name):
    return {"park": name, "country": "GB", "city": "Corby", "__meta": {"source_file": f"{name}.pdf"}}


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    for fn in ("_pair_answered", "_settled_clusters", "_load_match_decisions"):
        ck(hasattr(RUN, fn), f"run.{fn} exists")
    if not all(hasattr(RUN, f) for f in
               ("_pair_answered", "_settled_clusters", "_load_match_decisions")):
        print(f"\nEXIT10 ROUNDS TEST: FAIL ({len(fails)})")
        return 1

    # ---- the answered/unanswered predicate -----------------------------------
    g1 = {"pair_id": "p1", "a_idx": 0, "b_idx": 1, "a": None, "b": None}
    ck(not RUN._pair_answered(None, g1), "no decisions file -> unanswered")
    ck(not RUN._pair_answered({}, g1), "empty decisions -> unanswered")
    ck(RUN._pair_answered({"p1": "same"}, g1), "a bare verdict string counts")
    ck(RUN._pair_answered({"p1": {"verdict": "different"}}, g1), "the dict shape counts")
    ck(not RUN._pair_answered({"p1": {"verdict": "maybe"}}, g1), "junk does NOT count")

    # ---- the invariance predicate --------------------------------------------
    A, B, C, D, E = (_r(x) for x in "ABCDE")
    recs = [A, B, C, D, E]
    # clusters as merge would see them: {A,B} settled, {C,D} touched by an open pair, {E} alone
    clusters = [[A, B], [C, D], [E]]
    grey = [{"pair_id": "open1", "a_idx": 2, "b_idx": 4, "a": C, "b": E}]  # C <-> E open

    got = RUN._settled_clusters(clusters, grey, None, recs)
    ck([[r["park"] for r in cl] for cl in got] == [["A", "B"]],
       f"only the untouched cluster is pulled forward {[[r['park'] for r in cl] for cl in got]}")
    # TRANSITIVITY: D is in no pair, but its clustermate C is - the whole cluster is unsettled
    ck(all("D" not in [r["park"] for r in cl] for cl in got),
       "a clustermate of an open pair blocks the WHOLE cluster (links only ever get added)")
    ck(all("E" not in [r["park"] for r in cl] for cl in got),
       "the other side of the open pair is excluded too")

    got = RUN._settled_clusters(clusters, grey, {"open1": "different"}, recs)
    ck(len(got) == 3, "once the pair is answered, every cluster is settled")
    ck(RUN._settled_clusters(clusters, [], None, recs) == clusters,
       "no grey pairs at all -> nothing is withheld")

    # a pair whose BOTH sides sit in one cluster still blocks that cluster only
    grey2 = [{"pair_id": "o2", "a_idx": 0, "b_idx": 1, "a": A, "b": B}]
    got = RUN._settled_clusters(clusters, grey2, None, recs)
    ck([[r["park"] for r in cl] for cl in got] == [["C", "D"], ["E"]],
       "an intra-cluster open pair withholds only its own cluster")

    # ---- round 2 cannot lose round 1's verdicts ------------------------------
    d = Path(tempfile.mkdtemp(prefix="cbre_x10_"))
    (d / "match_decisions.json").write_text(
        json.dumps({"p1": {"verdict": "same", "reason": "same estate, same postcode"}}),
        encoding="utf-8")
    md = RUN._load_match_decisions(d)
    ck(md and md.get("p1", {}).get("verdict") == "same", "round 1's verdict loads")
    ck((d / "match_settled.json").exists(),
       "a durable settled copy is written when a verdict is read")

    # the clobber: a literal-minded round-2 agent empties the file
    (d / "match_decisions.json").write_text("{}", encoding="utf-8")
    md = RUN._load_match_decisions(d)
    ck(md and md.get("p1", {}).get("verdict") == "same",
       "an EMPTIED match_decisions.json does not lose the settled verdict")

    # a genuine NEW verdict still wins over the settled copy
    (d / "match_decisions.json").write_text(
        json.dumps({"p1": {"verdict": "different", "reason": "two schemes"},
                    "p2": {"verdict": "same", "reason": "x"}}), encoding="utf-8")
    md = RUN._load_match_decisions(d)
    ck(md.get("p1", {}).get("verdict") == "different", "a real new verdict overrides")
    ck(md.get("p2", {}).get("verdict") == "same", "and a new pair is picked up")

    # ---- wiring + the round-2 candidates shape -------------------------------
    ck("_settled_clusters(clusters" in SRC, "run.py scopes conflicts through _settled_clusters")
    ck("conflicts = [] if grey_uncovered" not in SRC,
       "the blanket 'suppress every conflict while any pair is open' is gone")
    ck("_load_match_decisions(work)" in SRC, "run.py loads decisions through the merging reader")
    ck("do NOT" in SRC.lower() or "Do NOT" in SRC,
       "the round-2 instruction warns against rewriting match_decisions.json")
    ck('"pairs"' in SRC and "pop(" in SRC,
       "the pairs keys are dropped from the round-2 candidates file")

    # ---- the docs that promised ONE round ------------------------------------
    m = (ROOT / "reference" / "matching.md").read_text(encoding="utf-8", errors="replace")
    ck("field_decisions.json" in m, "matching.md names the field-decisions output")
    ck("two round-trips" in m or "second round" in m or "SECOND round" in m,
       "matching.md no longer promises exit 10 always fits in ONE round-trip")

    if fails:
        print(f"\nEXIT10 ROUNDS TEST: FAIL ({len(fails)})")
        return 1
    print("\nEXIT10 ROUNDS TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
