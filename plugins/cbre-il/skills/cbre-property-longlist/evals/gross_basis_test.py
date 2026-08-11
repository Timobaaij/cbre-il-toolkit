#!/usr/bin/env python3
"""A GROSS whole-building area must never populate warehouseArea when a net one exists. (B55)

extract_xlsx ALREADY derives the net figure when an office column sits in the SAME tracker row
(`warehouseArea = GIA - office`). It cannot when the office figure lives in the BROCHURE - a
different record, only comparable after clustering. So merge saw two numbers for one field and
raised a value conflict: 11 of 48 on a live run, every one resolved identically by a model, and
INCONSISTENTLY across rounds. That is a mechanical question being asked of a judge.

The signal needs no heuristic: a record whose warehouseArea equals its __meta.statedTotalArea is,
by construction, the source's gross figure with the office still inside it - a fact the extractor
itself recorded.

The must-NOT-fire cases matter as much as the fix. A tracker-only property must KEEP its gross
figure: there is no alternative, and dropping a client's only area would be far worse than
carrying a slightly gross one. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402

FAILURES = []


def ck(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def trk(area, stated=None, **kw):
    """A tracker row: gross when `stated` equals `area`, exactly as extract_xlsx leaves it."""
    r = {"park": "P", "city": "C", "warehouseArea": area, "areaUnit": "sq ft",
         "__meta": {"source_file": "t.xlsx", "source_type": "xlsx", "locator_base": "Longlist",
                    "prov": {"warehouseArea": "Longlist!r2"}}}
    if stated is not None:
        r["__meta"]["statedTotalArea"] = stated
    r.update(kw)
    return r


def broc(area, **kw):
    """A brochure record: an explicit warehouse-only figure."""
    r = {"park": "P", "city": "C", "warehouseArea": area, "areaUnit": "sq ft",
         "__meta": {"source_file": "d.pdf", "source_type": "pdf", "page_no": 1,
                    "prov": {"warehouseArea": "page 2 (text interpretation)"}}}
    r.update(kw)
    return r


print("is_gross_area - the structural signal:")
ck("a tracker row whose area IS its stated total is gross",
   M.is_gross_area(trk(549400, 549400)) is True)
ck("a record with no stated total is not gross", M.is_gross_area(trk(549400)) is False)
ck("a record whose area DIFFERS from its stated total is not gross (net already derived)",
   M.is_gross_area(trk(490891, 549400)) is False)
ck("a brochure record is not gross", M.is_gross_area(broc(514000)) is False)
ck("a malformed record is safe",
   M.is_gross_area({}) is False and M.is_gross_area(None) is False)
ck("a bool is not mistaken for a number",
   M.is_gross_area({"warehouseArea": True, "__meta": {"statedTotalArea": True}}) is False)

print("\n_gross_split - fires ONLY when both halves are present:")
mixed = [trk(549400, 549400), broc(514000)]
ng, gr = M._gross_split(mixed, "warehouseArea")
ck("a gross + net cluster splits", len(ng) == 1 and len(gr) == 1)
ck("...with the net record on the non-gross side",
   ng and ng[0]["__meta"]["source_type"] == "pdf")
ck("a tracker-ONLY cluster does not split (nothing to prefer)",
   M._gross_split([trk(549400, 549400)], "warehouseArea") == ([], []))
ck("two gross candidates do not split",
   M._gross_split([trk(1, 1), trk(2, 2)], "warehouseArea") == ([], []))
ck("two net candidates do not split",
   M._gross_split([broc(1), broc(2)], "warehouseArea") == ([], []))
ck("the rule is scoped to warehouseArea only",
   M._gross_split(mixed, "officeArea") == ([], []))
ck("an empty cluster is safe", M._gross_split([], "warehouseArea") == ([], []))

print("\nconflict_candidates - the pointless adjudication is gone:")
wa = [c for c in M.conflict_candidates([mixed]) if c["field"] == "warehouseArea"]
ck("no warehouseArea conflict is enumerated for a gross-vs-net split", wa == [], str(wa))
both_net = [broc(514000), broc(500000)]
ck("a GENUINE net-vs-net disagreement is STILL enumerated",
   any(c["field"] == "warehouseArea" for c in M.conflict_candidates([both_net])))
ck("other fields in the same cluster are unaffected",
   any(c["field"] == "city"
       for c in M.conflict_candidates([[trk(549400, 549400), broc(514000, city="Other")]])))

print("\nmerge_cluster - the net value wins and the gross one stays visible:")
merged, prov, conflicts = M.merge_cluster(mixed)
ck("the NET figure wins warehouseArea", merged.get("warehouseArea") == 514000,
   str(merged.get("warehouseArea")))
ck("the winning prov points at the BROCHURE, not the tracker",
   (prov.get("warehouseArea") or {}).get("source_file") == "d.pdf",
   str(prov.get("warehouseArea")))
_note = str((conflicts or {}).get("warehouseArea") or "")
ck("the discarded GROSS value is disclosed, not silently dropped", "549400" in _note, _note)
ck("...and the note explains WHY, so a broker is not left guessing",
   "gross" in _note.lower() and "office" in _note.lower(), _note)

solo, _p, _c = M.merge_cluster([trk(549400, 549400)])
ck("a tracker-only property KEEPS its gross figure (no alternative exists)",
   solo.get("warehouseArea") == 549400, str(solo.get("warehouseArea")))

print("\nThe two callers must agree (they share _ordered_for_field):")
_cl = mixed
_comm = sorted(_cl, key=lambda r: (M.COMM_RANK.get(M._st(r), 9), M._unreliable(r), -M._datekey(r)))
_spec = sorted(_cl, key=lambda r: (M._unreliable(r), M.SPEC_RANK.get(M._st(r), 9)))
_trko = sorted(_cl, key=lambda r: (not M._is_rich(r), M._unreliable(r),
                                   M.SPEC_RANK.get(M._st(r), 9)))
_order = M._ordered_for_field("warehouseArea", _cl, _comm, _spec, _trko,
                              any(M._is_rich(r) for r in _cl))
ck("_ordered_for_field puts the NET record first for warehouseArea",
   _order and _order[0]["__meta"]["source_type"] == "pdf")
_order_other = M._ordered_for_field("city", _cl, _comm, _spec, _trko,
                                    any(M._is_rich(r) for r in _cl))
ck("...and leaves an unrelated field's precedence untouched",
   [id(r) for r in _order_other] == [id(r) for r in _spec])

print()
if FAILURES:
    print(f"GROSS BASIS TEST: FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("GROSS BASIS TEST: PASS (net beats gross; tracker-only keeps its figure; nothing hidden)")
