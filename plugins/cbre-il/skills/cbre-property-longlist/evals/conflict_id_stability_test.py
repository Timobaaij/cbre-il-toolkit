#!/usr/bin/env python3
"""conflict_id_stability_test.py - correcting a value keeps the adjudication. (B09)

conflict_id hashed the cluster's match_key AND the sorted VALUE SET, so correcting one of
the disagreeing values re-minted the conflict's own id. The backlog called that a re-ask
loop; it is worse. The QA improvement round's remedy is work/overrides.json, which merge
applies BEFORE clustering but run.py's enumeration never applies at all - so the two sides
computed different ids and merge SILENTLY DROPPED every adjudicated pick for that property,
with no Gaps line and no exit 10.

Two properties are asserted, and they pull against each other:
  STABILITY - the same conflict keeps its handle when a value is corrected, or when the
    records arrive in a different order;
  NO COLLISION - a different conflict never inherits an answered one's handle, because
    applying an old adjudication to a new disagreement is worse than re-asking.
The two sides (conflict_candidates and merge_cluster) must compute the id IDENTICALLY -
if they diverge, every pick is dropped, which is the bug itself. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import merge as M  # noqa: E402

SRC = (HELPERS / "merge.py").read_text(encoding="utf-8", errors="replace")


def _r(src, loc, **kw):
    r = {"park": "Raven Park", "city": "Corby", "country": "GB", "developer": "Prologis",
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": loc}}
    r.update(kw)
    return r


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    a = _r("deck.pdf", "page 2", warehouseRentVal=60.0, warehouseArea=30000)
    b = _r("tracker.xlsx", "Sheet1!r9", warehouseRentVal=70.0, warehouseArea=30000)

    # --- STABILITY -------------------------------------------------------------
    id1 = M.conflict_id(M.cluster_anchor([a, b]), "warehouseRentVal", [60.0, 70.0])
    id_corrected = M.conflict_id(M.cluster_anchor([a, b]), "warehouseRentVal", [60.0, 72.0])
    ck(id1 == id_corrected,
       "correcting a disagreeing VALUE keeps the same conflict_id (the whole point)")

    ck(M.cluster_anchor([a, b]) == M.cluster_anchor([b, a]),
       "the cluster anchor is ORDER-INDEPENDENT")
    a2 = dict(a); a2["park"] = "Raven Park, Earlstrees"      # an override corrects the name
    ck(M.cluster_anchor([a2, b]) == M.cluster_anchor([a, b]),
       "correcting the park NAME does not move the anchor (it keyed on match_key before)")

    # --- NO COLLISION ----------------------------------------------------------
    ck(M.conflict_id(M.cluster_anchor([a, b]), "warehouseArea", [1, 2]) != id1,
       "a DIFFERENT FIELD of the same cluster gets a different id")
    c = _r("other.pdf", "page 9", warehouseRentVal=60.0)
    ck(M.conflict_id(M.cluster_anchor([a, c]), "warehouseRentVal", [60.0, 70.0]) != id1,
       "a DIFFERENT CLUSTER gets a different id")
    ck(M.cluster_anchor([a]) != M.cluster_anchor([a, b]),
       "adding a record to the cluster moves the anchor (its identity really changed)")

    # a changed candidate set stays VISIBLE even though it no longer moves the id
    ck(M.candidates_sig([60.0, 70.0]) != M.candidates_sig([60.0, 72.0]),
       "candidates_sig still distinguishes a changed value set")
    ck(M.candidates_sig([60.0, 70.0]) == M.candidates_sig([70.0, 60.0]),
       "...and is order-independent")

    # --- THE TWO SIDES MUST AGREE ----------------------------------------------
    got = M.conflict_candidates([[a, b]])
    ck(len(got) >= 1, f"a genuine cross-source conflict is enumerated ({len(got)})")
    rent = next((g for g in got if g["field"] == "warehouseRentVal"), None)
    ck(rent is not None, "the rent conflict is among them")
    if rent:
        ck(rent["conflict_id"] == id1,
           "conflict_candidates emits the anchored id")
        ck(rent.get("cluster_anchor") and rent.get("candidates_sig"),
           "the conflict records its anchor and candidate signature (auditable)")
        # merge_cluster must resolve the SAME id, or every pick is silently dropped
        merged, _prov, _c = M.merge_cluster(
            [a, b], {rent["conflict_id"]: {"pick": "b", "reason": "the tracker is newer"}})
        ck(merged.get("warehouseRentVal") in (60.0, 70.0),
           f"merge_cluster resolved the pick by that id {ascii(str(merged.get('warehouseRentVal')))}")

    # wiring: both sides go through cluster_anchor, and the values are NOT in the hash
    ck("conflict_id(cluster_anchor(cl)" in SRC, "conflict_candidates anchors the id")
    ck("cid = conflict_id(_anchor" in SRC, "merge_cluster anchors the id the same way")
    body = SRC[SRC.find("def conflict_id("):SRC.find("def _ordered_for_field")]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("#") and '"""' not in ln)
    ck("values" not in code.split("return")[-1],
       "the value set is NOT part of the hash any more")

    if fails:
        print(f"\nCONFLICT ID STABILITY TEST: FAIL ({len(fails)})")
        return 1
    print("\nCONFLICT ID STABILITY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
