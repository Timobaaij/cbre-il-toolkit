#!/usr/bin/env python3
"""anchor_stability_test.py - a PHOTO rebind must not re-key a property's value conflicts. (B6)

THE DEFECT. `cluster_anchor`'s own docstring states the property it exists to guarantee: the anchor is
built from WHICH RECORDS are in the cluster, "never from their values", so that correcting a value
leaves an adjudicated conflict_id untouched. But the per-record key was
`source_file # locator_base # page_no`, and `__meta.page_no` is a PRESENTATIONAL binding - the
interpretation contract defines it as the page carrying this property's HERO PHOTO, which is routinely
a different page from the one the record's text came from.

So an image-only repair moved every conflict_id for that property. Observed three times on live runs:
rebinding Raven Park's hero re-keyed 9 settled value decisions, and rebinding Rockingham 161's re-keyed
2 - each time costing a fresh exit-10 round and an LLM dispatch to re-derive answers whose candidate
values, sources, locators and defaults were byte-identical. Worse, the repairs that trigger it are
exactly the ones the G-images gate asks for, so the two mechanisms worked against each other.

WHY DROPPING page_no IS SAFE, and this suite proves it rather than asserting it: page_no cannot
discriminate two DIFFERENT properties. Two options described on the same page of one deck share
`locator_base` AND `page_no` (the contract binds both to that page), so they already produce an
identical per-record key - removing page_no adds no collision that was not there. The only pairs
page_no separated were a single record whose TEXT page and HERO page diverge, which is one property,
not two. Offline, pure hashing - no build, no extraction."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402


def rec(src, locator, page, park="Raven Park", **kw):
    r = {"park": park, "city": "Corby", "warehouseArea": 169250, "areaUnit": "sq ft"}
    r.update(kw)
    r["__meta"] = {"source_file": src, "locator_base": locator, "page_no": page,
                   "source_type": "pdf"}
    return r


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    brochure = rec("Raven Park_Brochure_V8.1.pdf", "page 2", 1)
    tracker = {"park": "Unit 1, Raven Park", "city": "Corby", "warehouseRentVal": 8.95,
               "__meta": {"source_file": "Building_Data.xlsx", "locator_base": "Building Data",
                          "page_no": None, "source_type": "xlsx"}}
    cluster = [brochure, tracker]
    base_anchor = M.cluster_anchor(cluster)
    base_id = M.conflict_id(base_anchor, "warehouseRentVal", [8.95, 9.10])

    # --- THE FIX: a hero rebind leaves the anchor and every conflict id alone ---------- #
    rebound = [rec("Raven Park_Brochure_V8.1.pdf", "page 2", 0), tracker]   # page_no 1 -> 0
    ck(M.cluster_anchor(rebound) == base_anchor,
       "a HERO REBIND (page_no 1 -> 0) leaves the cluster anchor unchanged")
    ck(M.conflict_id(M.cluster_anchor(rebound), "warehouseRentVal", [8.95, 9.10]) == base_id,
       "...so a settled conflict_id survives it and needs no re-adjudication")
    for pno in (0, 2, 5, None):
        ck(M.cluster_anchor([rec("Raven Park_Brochure_V8.1.pdf", "page 2", pno), tracker])
           == base_anchor, f"...for any hero page ({pno!r}), including absent")

    # a plan/gallery rebind travels in the same __meta and must also be inert
    g = rec("Raven Park_Brochure_V8.1.pdf", "page 2", 1)
    g["__meta"].update({"plan_page": 2, "image_pages": [0, 1], "heroRef": 0,
                        "exclude_refs": {"2": [0, 1]}})
    ck(M.cluster_anchor([g, tracker]) == base_anchor,
       "plan_page / image_pages / heroRef / exclude_refs are inert for the anchor too")

    # --- the properties B09 established must SURVIVE this change ---------------------- #
    ck(M.cluster_anchor(cluster) == M.cluster_anchor([tracker, brochure]),
       "the anchor is still ORDER-INDEPENDENT")
    corrected = rec("Raven Park_Brochure_V8.1.pdf", "page 2", 1, park="Raven Park (corrected)",
                    warehouseArea=170000)
    ck(M.cluster_anchor([corrected, tracker]) == base_anchor,
       "correcting a VALUE still leaves the anchor untouched (the B09 guarantee)")
    ck(M.cluster_anchor([brochure]) != base_anchor,
       "REMOVING a record still moves the anchor - real membership change")
    ck(M.cluster_anchor(cluster + [rec("Third.pdf", "page 1", 0)]) != base_anchor,
       "ADDING a record still moves the anchor")
    ck(M.conflict_id(base_anchor, "warehouseArea", [1, 2]) != base_id,
       "different FIELDS still get different ids")

    # --- discrimination that must be PRESERVED ---------------------------------------- #
    ck(M.cluster_anchor([rec("Other_deck.pdf", "page 2", 1), tracker]) != base_anchor,
       "a different SOURCE FILE still discriminates")
    ck(M.cluster_anchor([rec("Raven Park_Brochure_V8.1.pdf", "page 4", 1), tracker])
       != base_anchor, "a different LOCATOR (the record's own text page) still discriminates")

    # --- the safety argument, proved rather than asserted ----------------------------- #
    # two options on ONE page of one deck: the contract gives both the same locator_base AND the
    # same page_no, so they were ALREADY indistinguishable - dropping page_no adds no collision.
    twinA = rec("Multi.pdf", "page 3", 2, park="Option A")
    twinB = rec("Multi.pdf", "page 3", 2, park="Option B")
    ck(M.cluster_anchor([twinA]) == M.cluster_anchor([twinB]),
       "same-page siblings already share an anchor (so removing page_no adds no new collision)")
    # and two records that differ ONLY by page_no are the same property's text vs hero page
    ck(M.cluster_anchor([rec("Multi.pdf", "page 3", 2)])
       == M.cluster_anchor([rec("Multi.pdf", "page 3", 7)]),
       "records differing only by page_no now share an anchor - that IS the fix")

    # --- the formula itself: page_no must be gone from the key ------------------------ #
    src = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8", errors="replace")
    body = src.split("def cluster_anchor(", 1)[1].split("\ndef ", 1)[0]
    # Scan the CODE, not the docstring - the docstring names page_no on purpose, to record why it
    # is excluded. Strip the leading triple-quoted docstring before looking.
    code = body.split('"""', 2)[2] if body.count('"""') >= 2 else body
    ck("page_no" not in code,
       f"cluster_anchor's CODE no longer reads page_no {ascii(code.strip()[:90])}")
    ck("locator_base" in code and "source_file" in code,
       "...and still keys on source_file + locator_base")

    # --- a real tracker-shaped cluster is unaffected ---------------------------------- #
    ck(M.cluster_anchor([tracker]) == M.cluster_anchor([dict(tracker)]),
       "a tracker record (no page_no at all) hashes stably")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
