#!/usr/bin/env python3
"""d12_repair_survival_test.py - a repair merge would throw away is refused, not reported applied. (D12)

THE DEFECT, from the measured client run. Four repairs restored motorway links that merge had
dropped. `work/repairs_report.json` recorded all four under `applied`, each with its full
`from` and `to`, and the run printed them as applied. NONE of them reached `canonical.json` or
the delivered pack. `normalize.short_motorway` (`MOTORWAY_MAX = 40`) condenses any motorway
value over 40 characters so it fits on a card, and it runs AFTER the repairs stage, inside
merge's post-repair re-derivation; every restored list exceeded 40 characters and was condensed
straight back to the value the repair had been written to correct.

The card-fit condensing is deliberate and correct and stays. The defect is that the correction
channel reported SUCCESS for a correction that was discarded: no STALE, no SUPERSEDED, no
note. An operator who trusted that report would ship a Source Ledger row asserting a value the
delivered pack does not contain. On the real run the operator caught it only by re-reading
canonical by hand, and then deleted the four repairs so the ledger would not make a false claim.

WHAT THIS PINS:
  1. a `motorway` repair whose value exceeds the limit is NOT under `applied`; it is refused
     under `invalid`, and canonical on disk still carries the pre-repair value;
  2. the refusal says WHY in operator language: it names the 40-character limit, names the
     stage (short_motorway), and shows the condensed form the value would have become;
  3. a `motorway` repair whose value FITS is applied completely normally, and so is the very
     condensed form the refusal suggested, so the fix cannot decay into a blanket refusal;
  4. a repair on an unrelated field, including one carrying a string well over 40 characters,
     is untouched by the new check;
  5. the refusal happens BEFORE anything is written: the pre-apply validator refuses the entry,
     `apply` leaves the canonical dict byte-for-byte unchanged, and an entry that mixes a doomed
     `motorway` with a sound `status` lands on NEITHER field (all-or-nothing).

HOW A REGRESSION TRIPS IT. The old code had no survival check at all, so the over-length
entry landed under `applied` with the full value in `to` and was written to canonical.json;
checks 1, 2 and 5 all fail against that behaviour. A fix that over-corrected into refusing
every motorway repair fails check 3.

Offline. Drives `repairs.run` on a temp work dir and `repairs.apply` directly; no build.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import normalize as N                    # noqa: E402
import repairs as R                      # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
FAILS = []

# the shape of the real ones: a semicolon-joined list of road, junction and distance triples,
# as an agent wrote it for the brochure. 78 characters, so it can never sit on a card as is.
FULL = ("Junction 18/18A M5 2 miles to the south; "
        "Junction 1 M49 4.5 miles to the north")
# what merge's re-derivation had already reduced it to on the card, and what the operator saw
# in canonical when writing the repair that tried to put the full sentence back
CONDENSED = N.short_motorway(FULL)[0]
# a value that already fits the card: applied normally
FITS = "M5 J18/18A 2 miles; M49 J1 4.5 miles"
# an unrelated string field, carried on the property, deliberately longer than the limit
LONG_TENURE = "Leasehold, new FRI lease on terms to be agreed with the landlord's agents"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def canon():
    return {"meta": {"client": "T", "units": {"area": "sq ft"}},
            "pois": [], "regions": {},
            "properties": [
                {"id": 1, "park": "Alpha Park", "city": "Avonmouth", "developer": "Devco",
                 "country": "GB", "warehouseArea": 100000, "areaUnit": "sq ft",
                 "status": "Available", "motorway": CONDENSED, "tenure": "Leasehold",
                 "photo": PX, "gallery": [PX]},
            ]}


def entry(**kw):
    e = {"id": "rp-001", "property": {"key": "avonmouth|devco|alpha park", "id": 1},
         "why": "merge dropped the M49 link the brochure states",
         "verified_by": "t@cbre.com"}
    e.update(kw)
    return e


def work_with(items):
    w = Path(tempfile.mkdtemp(prefix="cbre_d12_"))
    (w / "canonical.json").write_text(json.dumps(canon()), encoding="utf-8")
    (w / "repairs.json").write_text(json.dumps(items), encoding="utf-8")
    return w


def props_of(w):
    return json.loads((w / "canonical.json").read_text(encoding="utf-8"))["properties"]


def main() -> int:
    print("== fixture sanity: the over-length value really is over the limit ==")
    ck(len(FULL) > N.MOTORWAY_MAX,
       f"the full sentence is {len(FULL)} characters, over MOTORWAY_MAX={N.MOTORWAY_MAX}")
    ck(len(CONDENSED) <= N.MOTORWAY_MAX and CONDENSED != FULL,
       f"short_motorway condenses it to {CONDENSED!r} ({len(CONDENSED)} chars)")
    ck(len(FITS) <= N.MOTORWAY_MAX and N.short_motorway(FITS)[0] == FITS,
       f"the control value {FITS!r} fits and is left alone by short_motorway")
    ck(len(LONG_TENURE) > N.MOTORWAY_MAX,
       "the unrelated control field carries a string longer than the motorway limit")

    print()
    print("== 1. the over-length motorway repair is NOT reported applied ==")
    w = work_with([entry(set={"motorway": FULL}, expect={"motorway": CONDENSED})])
    rep = R.run(w)
    ck(not rep["applied"],
       f"the repair does not appear under `applied` (the D12 false success) {rep['applied']}")
    ck(len(rep["invalid"]) == 1,
       f"it is refused under `invalid`, once {rep['invalid']}")
    ck(not rep["stale"] and not rep["superseded"] and not rep["ambiguous"],
       "...and not misfiled as stale, superseded or ambiguous")
    ck(props_of(w)[0]["motorway"] == CONDENSED,
       "canonical.json still carries the pre-repair value: nothing was written")
    disk = json.loads((w / "repairs_report.json").read_text(encoding="utf-8"))
    ck(not disk.get("applied") and len(disk.get("invalid") or []) == 1,
       "repairs_report.json on disk agrees: nothing under applied, one refusal")

    print()
    print("== 2. the refusal says why, in operator language ==")
    msg = rep["invalid"][0] if rep["invalid"] else ""
    ck("rp-001" in msg, "the refusal names the repair id")
    ck("motorway" in msg, "...and the field")
    ck(str(N.MOTORWAY_MAX) in msg,
       f"...and the {N.MOTORWAY_MAX}-character limit itself")
    ck("short_motorway" in msg, "...and the stage that would condense it (short_motorway)")
    ck(repr(CONDENSED) in msg or CONDENSED in msg,
       f"...and SHOWS the condensed form the value would become {CONDENSED!r}")
    ck(str(len(FULL)) in msg, "...and the length of the value as written")
    ck("NOTHING" in msg.upper(), "...and states plainly that nothing was applied")
    lines = R.format_report(rep)
    ck(any("[INVALID REPAIR]" in ln and str(N.MOTORWAY_MAX) in ln for ln in lines),
       "the printed report line is an INVALID REPAIR that names the limit")
    ck(not any("->" in ln and repr(FULL) in ln for ln in lines),
       "...and no printed line claims the full value landed (the old 'from -> to' line)")

    print()
    print("== 3. a motorway repair that FITS is applied completely normally ==")
    w = work_with([entry(set={"motorway": FITS}, expect={"motorway": CONDENSED})])
    rep = R.run(w)
    ck(len(rep["applied"]) == 1 and not rep["invalid"],
       f"a fitting value is applied, not refused {rep['invalid']}")
    ch = (rep["applied"][0].get("changed") or {}).get("motorway") or {}
    ck(ch.get("from") == CONDENSED and ch.get("to") == FITS,
       f"...the report shows from -> to as written {ch}")
    ck(props_of(w)[0]["motorway"] == FITS, "...and the value actually reached canonical")
    # the escape hatch the refusal itself offers: write the condensed form yourself
    c = canon()
    c["properties"][0]["motorway"] = "M5 J18 2 miles"
    r = R.apply(c, [entry(set={"motorway": CONDENSED})])
    ck(len(r["applied"]) == 1 and c["properties"][0]["motorway"] == CONDENSED,
       "writing the condensed form the refusal suggested is applied, so the check is not a "
       "blanket refusal of motorway repairs")
    ok, after, why = R.survives_downstream("motorway", FITS)
    ck(ok and after == FITS and why is None,
       "survives_downstream says a fitting value survives as written")

    print()
    print("== 4. an unrelated field is untouched by the new check ==")
    ck(R._doomed_sets({"tenure": LONG_TENURE}) == [],
       "a long string on an unrelated field is not doomed: the limit is motorway's, not "
       "every field's")
    w = work_with([entry(set={"tenure": LONG_TENURE})])
    rep = R.run(w)
    ck(len(rep["applied"]) == 1 and not rep["invalid"],
       f"a 70-plus-character tenure repair is applied normally {rep['invalid']}")
    ck(props_of(w)[0]["tenure"] == LONG_TENURE, "...and lands verbatim")
    w = work_with([entry(set={"status": "Under Offer"})])
    rep = R.run(w)
    ck(len(rep["applied"]) == 1 and props_of(w)[0]["status"] == "Under Offer",
       "a plain status repair is applied normally")

    print()
    print("== 5. the refusal happens BEFORE anything is written ==")
    # the pre-apply validator, the same one `load` runs over work/repairs.json
    errs = R.validate_entry(entry(set={"motorway": FULL}))
    ck(bool(errs) and any(str(N.MOTORWAY_MAX) in e for e in errs),
       f"validate_entry refuses the entry before it reaches apply, naming the limit {errs}")
    passed, bad = R.validate_entries([entry(set={"motorway": FULL})])
    ck(not passed and len(bad) == 1, "validate_entries lets none of it through")
    ck(not R.validate_entry(entry(set={"motorway": FITS})),
       "...while the fitting value passes the same validator")
    # apply() directly: the canonical dict must be untouched, not written-then-reverted
    c = canon()
    before = json.dumps(c, sort_keys=True)
    r = R.apply(c, [entry(set={"motorway": FULL})])
    ck(not r["applied"] and len(r["invalid"]) == 1,
       "apply() alone refuses it too, so the guard cannot be walked around")
    ck(json.dumps(c, sort_keys=True) == before,
       "...and the canonical dict is byte-for-byte unchanged")
    # all-or-nothing: a doomed motorway alongside a sound status lands on NEITHER
    c = canon()
    r = R.apply(c, [entry(set={"motorway": FULL, "status": "Under Offer"})])
    ck(not r["applied"] and len(r["invalid"]) == 1,
       "an entry mixing a doomed motorway with a sound status is refused whole")
    ck(c["properties"][0]["status"] == "Available"
       and c["properties"][0]["motorway"] == CONDENSED,
       "...and NEITHER field was written (no half-applied entry)")
    # and the refusal does not depend on `expect` being satisfied
    c = canon()
    r = R.apply(c, [entry(set={"motorway": FULL}, expect={"motorway": "something else"})])
    ck(not r["applied"] and len(r["invalid"]) == 1 and not r["superseded"],
       "with a stale `expect` the verdict is still INVALID, not SUPERSEDED: the value can "
       "never land whatever the property currently says")

    print()
    print("== the registry that makes the check extensible ==")
    ck("motorway" in getattr(R, "POST_REPAIR_NORMALISERS", {}),
       "motorway is registered as a post-repair normaliser")
    reg = R.POST_REPAIR_NORMALISERS.get("motorway")
    ck(bool(reg) and reg[0](FULL) == CONDENSED,
       "...and the registered callable agrees with normalize.short_motorway")
    ck(bool(reg) and str(N.MOTORWAY_MAX) in reg[1],
       "...and its operator-facing description names the limit")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        for f in FAILS:
            print("   -", f)
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
