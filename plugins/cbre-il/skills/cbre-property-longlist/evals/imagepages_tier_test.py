#!/usr/bin/env python3
"""imagepages_tier_test.py - a same-deck __meta.image_pages over-claim is a WARNING, not
a blocking ERROR; a cross-deck one still blocks. (B21)

vision_validate raised a blocking ERROR - costing a full exit-3 round-trip - whenever two
records of one deck named the same page in image_pages. But merge's unique-claimant guard
already resolves that deterministically, and reference/interpretation.md explicitly
PROMISES the interpreter that "an honest over-list of a neighbour's page is dropped, never
leaked". So the gate blocked on a shape the contract sanctions - and it fired on the
contract-blessed "two properties on ONE page" topology, where a re-dispatched sub-agent
reading the same contract returns the same answer: a non-convergent exit-3 streak.

The downgrade is only safe because of what merge does, so this suite pins BOTH halves:
the validator's tiering AND merge._page_allowed's actual resolution. The cross-deck guard
(a page outside the deck's rasterised range) must stay an ERROR - that is the branch that
prevents a real leak, and it is a DIFFERENT branch. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import vision_validate as VV  # noqa: E402
import merge as M  # noqa: E402


def _rec(park, page_no, image_pages=None):
    meta = {"page_no": page_no}
    if image_pages is not None:
        meta["image_pages"] = image_pages
    return {"park": park, "__meta": meta}


def _run(records, pages=(0, 1, 2)):
    """Drive the REAL validate() over a work dir shaped like a live one."""
    d = Path(tempfile.mkdtemp(prefix="cbre_ipt_"))
    (d / "extract").mkdir()
    (d / "vision").mkdir()
    (d / "vision" / "manifest.json").write_text(json.dumps({"decks": [{
        "region": "R1", "source_file": "deck.pdf",
        "pages": [{"page_no": p} for p in pages]}]}), encoding="utf-8")
    (d / "extract" / "R1_vision.json").write_text(json.dumps(records), encoding="utf-8")
    errs, warns = VV.validate(d)
    ip = lambda xs: [x for x in xs if "image_pages" in x]  # noqa: E731
    return ip(errs), ip(warns)


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # --- the runtime contract the downgrade RELIES on -------------------------
    # cluster 0 anchors (deck,1); cluster 1 also claims it.
    anchor = {("deck.pdf", 1): 0}
    claims = {("deck.pdf", 1): {0, 1}}
    ck(M._page_allowed(0, "deck.pdf", 1, anchor, claims),
       "merge: the ANCHORING cluster keeps a contested page")
    ck(not M._page_allowed(1, "deck.pdf", 1, anchor, claims),
       "merge: the over-claimer is denied it (no leak, deterministically)")
    # nobody anchors it -> both are denied (lossy, but still not a leak)
    claims2 = {("deck.pdf", 1): {0, 1}}
    ck(not M._page_allowed(0, "deck.pdf", 1, {}, claims2)
       and not M._page_allowed(1, "deck.pdf", 1, {}, claims2),
       "merge: an UNANCHORED contested page is dropped from every carousel")
    ck(M._page_allowed(0, "deck.pdf", 2, {}, {("deck.pdf", 2): {0}}),
       "merge: a sole claimant keeps an unanchored page")

    # --- ANCHORED over-claim: provably a no-op -> warning, never an error -----
    e, w = _run([_rec("A", 0, [0, 1]), _rec("B", 1, [1])])
    ck(not e, f"anchored over-claim raises NO error {ascii(e[:1])}")
    ck(len(w) == 1, f"anchored over-claim raises exactly one warning ({len(w)})")
    ck(w and "1" in w[0], "the warning names the contested page")
    ck(w and ("anchor" in w[0].lower() or "awards" in w[0].lower()),
       "the warning says it resolves deterministically to the anchoring record")

    # --- UNANCHORED over-claim: lossy -> louder warning, still not an error ---
    e, w = _run([_rec("A", 0, [0, 2]), _rec("B", 1, [1, 2])])
    ck(not e, f"unanchored over-claim raises NO error {ascii(e[:1])}")
    ck(len(w) == 1, f"unanchored over-claim raises exactly one warning ({len(w)})")
    ck(w and ("dropped" in w[0].lower() or "loses" in w[0].lower()
              or "every carousel" in w[0].lower()),
       "the warning says BOTH properties lose the page (completeness, not correctness)")

    # --- the genuinely protective branch is UNTOUCHED -------------------------
    e, w = _run([_rec("A", 0, [0, 9])])
    ck(any("not a" in x and "rasterised page" in x for x in e),
       "a page outside the deck's rasterised range is STILL a blocking error")

    # --- no over-claim at all: silent ----------------------------------------
    e, w = _run([_rec("A", 0, [0]), _rec("B", 1, [1])])
    ck(not e and not w, f"a clean deck is silent {ascii((e + w)[:1])}")

    # --- the contract the interpreter is shown must state the lossy half ------
    doc = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8",
                                                               errors="replace")
    ck("never leaked" in doc, "interpretation.md still promises no leak")
    ck("anchors it" in doc and "every" in doc.lower(),
       "interpretation.md now tells the interpreter how a contested page is awarded "
       "AND names the lossy case")

    if fails:
        print(f"\nIMAGEPAGES TIER TEST: FAIL ({len(fails)})")
        return 1
    print("\nIMAGEPAGES TIER TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
