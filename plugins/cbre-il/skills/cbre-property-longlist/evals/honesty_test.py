#!/usr/bin/env python3
"""honesty_test.py - the deliverable must never claim more than it checked (2026-07-30).

The skill's promise is that every field traces to a source, unknowns show as `tbd`, nothing is
invented and gaps are SURFACED. These four defects all broke it the same way: something was not
done, and nothing said so.

  * an input whose type has no reader was dropped SILENTLY - not the inventory, not the ledger,
    not the Gaps Report (the live break: a .json + photos handover failed with "no readable
    property sources" while the .json was never mentioned)
  * with `openpyxl` absent under `--quiet` (which SKILL.md instructs) the Excel tracker - usually
    the richest source - was skipped with NOT ONE WORD anywhere
  * a missing PDF backend was reported as "corrupt / unreadable", i.e. blamed on the FILE, so the
    broker was sent to chase re-sends of perfectly good decks
  * `jsonschema` absent silently degraded validate-data to a PRESENCE check that accepted
    `warehouseArea: "not a number"` and still printed "[PASS] schema ... clean" (a crash-to-pass)
  * every Gaps Report printed "None - every image bound to a property" from a field NO code path
    has ever written

Offline. Run: python evals/honesty_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C  # noqa: E402
import deliver as DEL  # noqa: E402
import intake as IN  # noqa: E402
import run as RUN  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---------------- #7 an unsupported input is NAMED, never silently dropped ----------------
    print("#7 an input with no reader is recorded and surfaced")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        (td / "properties.json").write_text('{"properties": []}', encoding="utf-8")
        (td / "broker-email.txt").write_text("Unit A, 12,000 sq m", encoding="utf-8")
        (td / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)
        inv = IN.discover(td)
        unc = {str(u.get("file")) for u in (inv.get("unclassified") or [])}
        ck("unclassified" in inv, "the inventory has an `unclassified` bucket at all")
        ck("properties.json" in unc, f"the .json is recorded ({sorted(unc)})")
        ck("broker-email.txt" in unc, "the .txt is recorded")
        ck("photo.jpg" in (inv.get("images") or []),
           "a real image is still classified normally (the new branch is a fallthrough)")
    rsrc = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    ck("unsupported file type" in rsrc,
       "run.py folds unsupported types into unreadable_inputs -> unreadable.json + Gaps Report")
    ck("this pipeline has no " in rsrc and "_unclassified[:8]" in rsrc,
       "the exit-2 message NAMES the files it could not read (the live break's symptom)")

    # ---------------- #18 a lost READER and a misdiagnosed file ----------------
    print("\n#18 a lost reader is announced; a missing dep is never blamed on the file")
    ck("PRINT UNCONDITIONALLY" in rsrc and "will be SKIPPED, not merely unparsed" in rsrc,
       "an optional-reader failure prints even under --quiet (it is data loss, not chatter)")
    ck("except ImportError:" in rsrc and "never be reported as a corrupt FILE" in rsrc,
       "_classify_unreadable returns None on ImportError instead of 'corrupt / unreadable'")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        # a GENUINELY VALID pdf must classify as fine, and a genuinely broken one must still be
        # reported - the ImportError change must not blunt the real corrupt-file detection
        try:
            import fitz
            d = fitz.open()
            d.new_page(width=595, height=842)
            good = td / "good.pdf"
            d.save(str(good))
            d.close()
            ck(RUN._classify_unreadable(good) is None,
               "a VALID pdf classifies as readable (no regression)")
        except Exception as e:
            print(f"  [note] fitz unavailable, skipping the valid-pdf check ({e})")
        broken = td / "broken.pdf"
        broken.write_bytes(b"%PDF-1.4\n" + b"0" * 200)
        ck(RUN._classify_unreadable(broken) is not None,
           "a genuinely CORRUPT pdf is still reported (the fix did not blunt real detection)")

    # ---------------- #19 the degraded validator has a TYPE floor and says so ----------------
    print("\n#19 the degraded schema check enforces types and discloses itself")
    bad = {"meta": {}, "pois": [], "regions": {}, "properties": [
        {"id": 1, "country": "GB", "park": "P", "developer": "D", "city": "C", "status": "S",
         "photo": "x", "warehouseArea": "not a number", "lat": "52N"},
        {"id": 2, "country": "GB", "park": "P2", "developer": "D", "city": "C", "status": 5,
         "photo": "x"}]}
    errs = C._structural_errors(bad)
    ck(any("warehouseArea must be a number" in e for e in errs),
       "a string in a numeric field is an ERROR (was silently accepted)")
    ck(any("lat must be a number" in e for e in errs), "so is a non-numeric lat")
    ck(any("status must be a string" in e for e in errs), "and an int where a string belongs")
    good = {"meta": {}, "pois": [], "regions": {}, "properties": [
        {"id": 1, "country": "GB", "park": "P", "developer": "D", "city": "C", "status": "S",
         "photo": "x", "warehouseArea": "tbd", "warehouseRentVal": None, "lat": 52.1}]}
    ck(C._structural_errors(good) == [],
       "a 'tbd' sentinel / None / a real number are NOT errors (the honest unknown still passes)")
    ck(callable(C.schema_degraded), "there is a way to ASK whether validation was degraded")
    C._SCHEMA_DEGRADED.clear()
    ck(C.schema_degraded() == "", "clean state reports no degradation")
    C.schema_degraded(reason="jsonschema is not available")
    ck(C.schema_degraded() == "jsonschema is not available", "a degradation is recorded")
    gsrc = (ROOT / "helpers" / "gate_runner.py").read_text(encoding="utf-8")
    ck("DEGRADED mode" in gsrc and "C.schema_degraded()" in gsrc,
       "the gate PRINTS the degradation instead of a bare '[PASS] schema clean'")
    C._SCHEMA_DEGRADED.clear()

    # ---------------- unmatchedAssets: no unearned affirmative ----------------
    print("\nthe Gaps Report never claims a check that did not run")
    props = [{"id": 1, "park": "P", "city": "C", "country": "GB", "developer": "D",
              "warehouseArea": 10000, "warehouseRent": "tbd"}]
    md_absent = DEL.gaps_report({"meta": {}, "properties": props}, "T")
    ck("every image bound to a property" not in md_absent,
       "with the field NEVER written, the false affirmative is gone")
    ck("Not checked" in md_absent, "it says plainly that the reconciliation did not run")
    md_empty = DEL.gaps_report({"meta": {"unmatchedAssets": []}, "properties": props}, "T")
    ck("every image bound to a property" in md_empty,
       "an explicitly EMPTY list still earns the affirmative (a real check that found nothing)")
    md_some = DEL.gaps_report({"meta": {"unmatchedAssets": ["stray.jpg"]}, "properties": props}, "T")
    ck("stray.jpg" in md_some, "and a real unmatched asset is listed")

    # ---------------- P1-3: EVERY unknown reaches the Gaps Report ----------------
    # Listing only the 10 CORE fields is WHY an extraction miss ships invisibly: the card
    # shows `tbd`, the ledger asserts "absent in all sources", and nothing in the delivered
    # pack points at it. These assertions FAIL against the CORE-only implementation.
    print("\nP1-3 every genuine unknown reaches the broker's chase list")
    ck(DEL._is_tbd("??") and DEL._is_tbd("n/a") and DEL._is_tbd("-"),
       "the '??' / 'n/a' / '-' sentinels count as unknown (the chrome's isAbsent set)")
    ck(not DEL._is_tbd(0) and not DEL._is_tbd("0") and not DEL._is_tbd("Built"),
       "a real 0 or a real value is NOT an unknown")

    # a two-property set: sprinklers is carried by ONE (so a real chase for the other),
    # serviceCharge by NEITHER (inventory, not an action), landPrice/reit absent entirely.
    p2 = [{"id": 1, "park": "Alpha", "city": "C", "country": "GB", "developer": "D",
           "warehouseArea": 10000, "warehouseRent": "£8", "status": "Built",
           "clearHeight": "12 m", "earlyAccess": "now", "motorway": "M1",
           "lat": 1.0, "lng": 2.0,
           "sprinklers": "ESFR", "serviceCharge": "tbd", "leaseTerm": "10 yrs"},
          {"id": 2, "park": "Beta", "city": "C", "country": "GB", "developer": "D",
           "warehouseArea": 20000, "warehouseRent": "£9", "status": "Built",
           "clearHeight": "15 m", "earlyAccess": "now", "motorway": "M1",
           "lat": 1.0, "lng": 2.0,
           "sprinklers": "tbd", "serviceCharge": "tbd", "leaseTerm": "tbd"}]
    md = DEL.gaps_report({"meta": {}, "properties": p2}, "T")

    ck("## Other missing fields by property" in md, "the secondary chase section exists")
    other = md.split("## Other missing fields by property", 1)[1].split("\n## ", 1)[0]
    ck("`sprinklers`" in other and "Beta" in other,
       "a field ONE property carries is a real chase for the property missing it")
    ck("`leaseTerm`" in other, "and so is a lease term one property quotes")

    inv_head = "## Fields no source provided for any longlist entry"
    ck(inv_head in md, "fields NO source carried get an INVENTORY section, not a chase list")
    inv = md.split(inv_head, 1)[1].split("\n## ", 1)[0]
    ck("`serviceCharge`" in inv and "`serviceCharge`" not in other,
       "a field NEITHER property carries is inventory-only - never an action item")
    ck("Not action items" in inv and "hides them" in inv,
       "the inventory says plainly that the dashboard hides these and they need no action")

    # the phantom-chase guard: the pipeline's own 'not applicable' markers must never appear
    ck("`landPrice`" not in md and "`reit`" not in md,
       "landPrice / reit (the pipeline's 'not applicable' markers) are never chased")
    ck("`country`" not in other and "`region`" not in other,
       "country / region are derived by enrichment, so they are not agent chases")
    ck(not any(f"`{k}Val`" in md for k in ("warehouseArea", "expansionPark", "warehouseRent")),
       "derived numeric twins (*Val) are never chased")

    # close notes: bespoke advice may name a party, generic ones must NOT
    ck("landlord/agent" in DEL._close_note("warehouseRent"),
       "a bespoke CLOSE note keeps its party-specific advice")
    for _f in ("serviceCharge", "rentFree", "permitting", "sprinklers"):
        _n = DEL._close_note(_f).lower()
        ck(not ("developer" in _n or "landlord" in _n),
           f"the generic note for {_f} is provenance-shaped, not party-shaped")

    # requirement scoping stays an LLM/broker judgement, and is DISCLOSED either way
    md_req = DEL.gaps_report({"meta": {"requirements": {"sprinklers": "ESFR required"}},
                              "properties": p2}, "T")
    ck("stated requirements first" in md_req,
       "with meta.requirements present, the section says it is ordered by the brief")
    ck("not scoped to a brief" in md,
       "without requirements, it says plainly the list is not requirement-scoped")

    # ---------------- #17 the image cache is engine-aware ----------------
    print("\n#17 the image cache key includes the active engine/tier")
    import images as IMG
    ck(callable(IMG._engine_tag) and IMG._engine_tag(),
       f"there is an engine tag ({IMG._engine_tag()!r})")
    with tempfile.TemporaryDirectory() as td_s:
        td = Path(td_s)
        f = td / "d.pdf"
        f.write_bytes(b"%PDF-1.4\n" + b"0" * 128)
        a = IMG._cache_file(f, 0, 110, "hero", td)
        real = IMG._engine_tag
        try:
            IMG._engine_tag = lambda: "fitz_shim|nopil"
            b = IMG._cache_file(f, 0, 110, "hero", td)
        finally:
            IMG._engine_tag = real
        ck(a is not None and b is not None and a != b,
           "the SAME (deck,page,budget,kind) hashes DIFFERENTLY per tier - a degraded pass can no "
           "longer serve its cached negative to a later native run")
        ck(IMG._cache_file(f, 0, 110, "hero", td) == a, "and the key is stable within a tier")

    print(f"\n{'OK' if not fails else 'FAIL'} honesty_test: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
