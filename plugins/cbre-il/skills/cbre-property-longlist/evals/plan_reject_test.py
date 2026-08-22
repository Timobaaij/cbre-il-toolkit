#!/usr/bin/env python3
# © 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""plan_reject_test.py - the durable site-plan rejection (`plan_rejected` ack).

WHY THIS EXISTS. The prescribed remedy for a wrongly-bound site plan was "clear `p.plan` in
canonical.json". That is not durable: `p.plan` is a merge OUTPUT, so the clearing survived
only while merge happened to resume-skip (canonical newer than the extracts). On a live run
the same interior-warehouse photo re-bound as a site plan THREE times, and the Source Ledger
kept asserting a plan the deck does not contain - a false claim in the audit trail.

WHAT IT LOCKS (the PATH, not just the function - the lesson from the prewarm/CACHE_DIR
regressions, where a unit test with hand-set globals passed while the live path was dead):
  1. `load_plan_rejected` parses all three ack forms and ignores a corrupt/missing file.
  2. `_plan_is_rejected` matches per-page and whole-file, case- and path-insensitively.
  3. attach_media honours the rejection in EVERY plan tier: a record-level bound plan, the
     planRef pick, the plan_page render, and the Tier-5 deterministic classifier.
  4. The PHOTO is never affected - only the plan slot.
  5. The ledger consequence: no plan bound -> merge emits NO `plan` prov -> no plan row.
  6. run.py WIRES the ack file into merge_args (the regression that would make all of the
     above dead code in the live pipeline).
Offline, no network, no PDF engine needed: the tiers are driven with monkeypatched IMG.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))

import merge as M  # noqa: E402

fails: list[str] = []


def check(ok, label):
    print(("  [PASS] " if ok else "  [FAIL] ") + label)
    if not ok:
        fails.append(label)


URI = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="
OTHER = "data:image/jpeg;base64,/9j/4AAQOTHERIMG=="


def _rec(src="Deck A.pdf", page=1, **kw):
    r = {"park": "P", "city": "C", "__meta": {"source_file": src, "source_type": "pdf",
                                              "page_no": page}}
    r["__meta"].update(kw.pop("meta", {}))
    r.update(kw)
    return r


class _FakeIMG:
    """Stands in for helpers.images: every tier returns a plan so a rejection is the ONLY
    thing that can stop one binding."""
    GALLERY_MAX = 6
    DEFAULT_BUDGET_KB = 100

    def __init__(self):
        self.calls = []

    def placeholder(self):
        return "data:image/png;base64,PLACEHOLDER"

    def embedded_by_index(self, src, page, idx, budget, cache_dir=None):
        self.calls.append(("embedded_by_index", Path(src).name, page, idx))
        return OTHER

    def page_render_plan(self, src, page, budget, cache_dir=None):
        self.calls.append(("page_render_plan", Path(src).name, page))
        return OTHER

    def page_hero_and_plan(self, src, page, budget, cache_dir=None):
        self.calls.append(("page_hero_and_plan", Path(src).name, page))
        return ("data:image/jpeg;base64,/9j/4AAQHERO==", OTHER)

    def slide_hero_and_plan(self, src, page, budget, cache_dir=None):
        return (None, None)

    def gallery_for_pages(self, *a, **k):
        return ([], 0)

    def uri_gallery_admissible(self, uri):
        """The carousel's card-quality floor. The fake's stand-in URIs are not decodable
        images, so 'admissible' here means 'a real data URI that is not the placeholder' -
        enough for merge's hero/gallery composition to behave as it does on real images,
        without this suite (whose subject is the PLAN slot) depending on pixel statistics."""
        return isinstance(uri, str) and uri.startswith("data:image/") and "PLACEHOLDER" not in uri

    def gallery_admissible(self, entry):
        return True

    def page_gallery(self, *a, **k):
        return []

    def slide_gallery(self, *a, **k):
        return []

    def page_image_audit(self, *a, **k):
        return []

    def slide_image_audit(self, *a, **k):
        return []

    def best_plan_page_render(self, src, pages, budget, cache_dir=None, near_miss=None,
                              own_figures=None):
        """TIER 5, the DETERMINISTIC fallback - and the tier the incident report blames for
        binding an interior photo into the Site Plan slot.

        This method was ABSENT from the fake, so merge's call raised AttributeError straight
        into the bare `except Exception` two lines below it, `uri` stayed None, and the two
        assertions that should have caught the missing rejection check passed VACUOUSLY. The
        suite's own "all 5 tiers" headline was true and completely misleading. (B04)

        KEEP THE SIGNATURE IN STEP WITH THE REAL ONE. Every new keyword merge passes must be
        accepted here, or the call raises TypeError into that same bare `except` and this whole
        tier silently stops being tested again - which is the exact failure the docstring above
        records. (`own_figures` added 2026-08-20 with the own-schedule plan ranking.)"""
        self.calls.append(("best_plan_page_render", Path(src).name, tuple(pages)))
        return (OTHER, sorted(pages)[0]) if pages else (None, None)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="planreject_"))
    (tmp / "Deck A.pdf").write_bytes(b"%PDF-1.4 stub")
    (tmp / "Deck B.pdf").write_bytes(b"%PDF-1.4 stub")

    # --- 1. load_plan_rejected: all three ack forms, plus graceful degradation ----
    print("\n1. load_plan_rejected")
    ack = tmp / "placeholder_audit_ack.json"
    ack.write_text(json.dumps({
        "confirmed": ["3"],
        "plan_rejected": [
            "Wayfair Lutterworth.pdf#2",                        # file + 1-based page
            "Whole Deck.pdf",                                    # every plan from a file
            {"source_file": r"C:\some\dir\Dict Form.pdf", "page": 5},   # dict form, full path
            {"source_file": "No Page.pdf"},                       # dict form, no page
            "",                                                  # junk, ignored
        ],
    }), encoding="utf-8")
    got = M.load_plan_rejected(ack)
    check(got == {"wayfair lutterworth.pdf#2", "whole deck.pdf", "dict form.pdf#5",
                  "no page.pdf"},
          f"parses page/file/dict forms, lowercases, strips dirs, drops junk (got {sorted(got)})")
    check(M.load_plan_rejected(tmp / "nope.json") == set(), "missing ack file -> empty set")
    bad = tmp / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    check(M.load_plan_rejected(bad) == set(), "corrupt ack file -> empty set, never raises")
    bad.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    check(M.load_plan_rejected(bad) == set(), "ack that is not an object -> empty set")

    # --- 2. _plan_is_rejected matching ------------------------------------------
    print("\n2. _plan_is_rejected")
    R = {"wayfair lutterworth.pdf#2", "whole deck.pdf"}
    check(M._plan_is_rejected(R, "Wayfair Lutterworth.pdf", 1),
          "per-page: 0-based page_no 1 == the ack's 1-based page 2")
    check(not M._plan_is_rejected(R, "Wayfair Lutterworth.pdf", 2),
          "a DIFFERENT page of the same file is NOT rejected")
    check(M._plan_is_rejected(R, "Whole Deck.pdf", 99),
          "bare filename rejects every page of that file")
    check(M._plan_is_rejected(R, r"D:\inputs\WAYFAIR LUTTERWORTH.PDF", 1),
          "case-insensitive and path-insensitive")
    check(not M._plan_is_rejected(set(), "Wayfair Lutterworth.pdf", 1),
          "empty ack rejects nothing")
    check(not M._plan_is_rejected(None, "Wayfair Lutterworth.pdf", 1),
          "None ack rejects nothing (the default path stays byte-identical)")

    # --- 3. every tier honours it ------------------------------------------------
    print("\n3. attach_media - all FIVE plan tiers")
    real = M.IMG
    fake = _FakeIMG()
    M.IMG = fake
    try:
        REJ = {"deck a.pdf#2"}   # 1-based page 2 == page_no 1

        # tier 1: a record-level bound plan data URI
        photo, plan, _, _, _, _ = M.attach_media([_rec(plan=URI)], tmp, 100)
        check(plan == URI, "tier 1 (record-level bound plan) binds when NOT rejected")
        photo, plan, _, _, _, _ = M.attach_media([_rec(plan=URI)], tmp, 100, plan_rejected=REJ)
        check(plan != URI, "tier 1 REJECTED -> the bound plan URI does not bind")

        # tier 2: planRef
        r = _rec(meta={"planRef": 3})
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100)
        check(plan == OTHER, "tier 2 (planRef) binds when NOT rejected")
        r = _rec(meta={"planRef": 3})
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100, plan_rejected=REJ)
        check(plan is None, "tier 2 (planRef) REJECTED -> no plan")
        check(r.get("__meta", {}).get("prov", {}).get("plan") is None,
              "tier 2 REJECTED -> no plan prov written (so no ledger row can be emitted)")

        # tier 3: plan_page render. The rejection names the RENDERED page (plan_page), which
        # need not be the record's own page - so assert on the CALL, not just the outcome:
        # after a rejection the renderer must never be invoked for that page. (Asserting
        # `plan is None` here would be wrong and would hide the real behaviour: a later tier
        # may still bind a plan from a DIFFERENT, un-rejected page, which is correct.)
        r = _rec(page=0, meta={"plan_page": 1})
        fake.calls.clear()
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100)
        check(("page_render_plan", "Deck A.pdf", 1) in fake.calls and plan == OTHER,
              "tier 3 (plan_page render) renders + binds page 2 when NOT rejected")
        r = _rec(page=0, meta={"plan_page": 1})
        fake.calls.clear()
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100, plan_rejected=REJ)
        check(("page_render_plan", "Deck A.pdf", 1) not in fake.calls,
              "tier 3 REJECTED -> the rejected page is never rendered as a plan")
        check(r.get("__meta", {}).get("prov", {}).get("plan", "").find("page 2") == -1,
              "tier 3 REJECTED -> no prov claims the rejected page as the site plan")
        # and with the record's OWN page rejected too, nothing binds at all
        r = _rec(page=1, meta={"plan_page": 1})
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100, plan_rejected=REJ)
        check(plan is None,
              "every candidate page rejected -> no plan binds anywhere (the live id-12 case)")

        # tier 4: the deterministic classifier - the tier that bound an interior photo live
        r = _rec()
        photo, plan, _, _, _, _ = M.attach_media([r], tmp, 100)
        check(plan == OTHER, "tier 4 (deterministic classifier) binds when NOT rejected")
        r = _rec()
        photo, plan, _, _, _, _ = M.attach_media([r], tmp, 100, plan_rejected=REJ)
        check(plan is None, "tier 4 REJECTED -> no plan")
        check(photo == "data:image/jpeg;base64,/9j/4AAQHERO==",
              "tier 4 REJECTED -> the PHOTO still binds (a rejection is plan-slot only)")

        # tier 5: best_plan_page_render, the DETERMINISTIC page-scan fallback. Until B04 this
        # tier consulted the ack nowhere - and the fake had no such method, so the failure was
        # invisible. Assert the ack reaches the scan itself: the rejected page must never even
        # be OFFERED to it, so the scan moves on rather than giving up.
        # tiers 1-4 must be silenced or one of them binds first and tier 5 is never reached -
        # which is exactly how this gap stayed invisible.
        _inline = fake.page_hero_and_plan
        fake.page_hero_and_plan = lambda src, page, budget, cache_dir=None: (
            "data:image/jpeg;base64,/9j/4AAQHERO==", None)
        fake.calls.clear()
        r = _rec(page=0, meta={"image_pages": [0, 1, 2]})
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100)
        offered = [c for c in fake.calls if c[0] == "best_plan_page_render"]
        check(bool(offered) and plan == OTHER, "tier 5 (page-scan fallback) binds when NOT rejected")
        fake.calls.clear()
        r = _rec(page=0, meta={"image_pages": [0, 1, 2]})
        _, plan, _, _, _, _ = M.attach_media([r], tmp, 100, plan_rejected=REJ)
        offered = [c for c in fake.calls if c[0] == "best_plan_page_render"]
        fake.page_hero_and_plan = _inline
        check(all(1 not in c[2] for c in offered),
              "tier 5 REJECTED -> the rejected page is never offered to the scan")
        check(not any(_p == 1 for c in offered for _p in c[2]),
              "tier 5 REJECTED -> and so cannot be bound from it")

        # a rejection must not leak across files
        _, plan, _, _, _, _ = M.attach_media([_rec(src="Deck B.pdf")], tmp, 100,
                                             plan_rejected=REJ)
        check(plan == OTHER, "a rejection for Deck A does not affect Deck B")
    finally:
        M.IMG = real

    # --- 4. the ledger consequence ----------------------------------------------
    print("\n4. ledger consequence")
    src = (HELPERS / "merge.py").read_text(encoding="utf-8")
    check(re.search(r"if plan_uri:\s*#[^\n]*\n\s*merged\[.plan.\] = plan_uri", src)
          and 'prov["plan"]' in src,
          "merge writes merged['plan'] + prov['plan'] ONLY under `if plan_uri:` - so no "
          "bind means no plan ledger row, by construction")

    # --- 5. run.py WIRING (the dead-code regression this class of fix invites) ---
    print("\n5. run.py wiring")
    rsrc = (HELPERS / "run.py").read_text(encoding="utf-8")
    check('"--plan-rejected"' in rsrc, "run.py passes --plan-rejected to merge")
    check(re.search(r"plan_ack_f\s*=\s*work\s*/\s*[\"']placeholder_audit_ack\.json[\"']", rsrc),
          "run.py resolves the ack at work/placeholder_audit_ack.json")
    check(re.search(r"merge_inputs\.append\(plan_ack_f\)", rsrc),
          "the ack is a merge_inputs RESUME KEY - recording a rejection re-fires merge "
          "(without this the fix silently does nothing until an unrelated edit)")
    msrc = src
    check('ap.add_argument("--plan-rejected"' in msrc, "merge.py declares --plan-rejected")
    check("plan_rejected=PLAN_REJECTED" in msrc,
          "merge.py passes the loaded set into the attach_media CALL (not just parses it)")

    print()
    if fails:
        print(f"PLAN REJECT TEST: FAIL ({len(fails)})")
        for f in fails:
            print("  -", f)
        return 1
    print("PLAN REJECT TEST: PASS (ack parsing, matching, all 5 tiers, photo unaffected, "
          "ledger consequence, run.py wiring + resume key)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
