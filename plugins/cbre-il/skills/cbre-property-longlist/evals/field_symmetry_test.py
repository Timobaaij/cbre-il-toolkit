#!/usr/bin/env python3
"""field_symmetry_test.py - one definition of "an existing field", on BOTH paths. (B7)

THE ASYMMETRY. `load_overrides` refused any field outside `canonical_property_fields()` with "is not a
canonical property field - an override may only correct an EXISTING field, never invent one". But
`_normalise_offspec` DELIBERATELY keeps a brand-new scalar attribute from an interpretation record,
because v22 Phase 1 added auto-show for exactly that. So an isolated LLM could introduce a field into
the client deliverable that the audited, verified_by-attributed, ledger-recorded HUMAN correction path
was forbidden to use. Live symptom: an override setting `epc` was refused while the property beside it
displayed an `epc` an LLM had introduced.

AND THE DRIFT WAS INVISIBLE. `postcode` shipped on 2 of 4 properties, was not canonical, and the Gaps
Report's off-spec section read "None." - because that section only ever covered quarantined STRUCTURES,
never a tolerated new SCALAR. A section asserting "None" while a non-schema key reaches the client is a
false statement in the honesty document.

THE FIX, and what this suite pins: the guard's notion of "existing" becomes `canonical ∪ fields present
on the records`, which is what its own message always claimed. A typo still matches nothing and is still
refused - that protection is the whole point of the guard and is asserted here in both directions. Any
brand-new scalar is recorded to `meta.newFields` so it can never ship invisibly again. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C  # noqa: E402
import merge as M  # noqa: E402


def ov(fld, val, **kw):
    e = {"id": "ov-t", "where": {"source_file": "T.xlsx", "sheet": "S", "row": 2},
         "set": {fld: val}, "why": "a sufficiently long and specific reason for the audit trail",
         "verified_by": "t@cbre.com"}
    e.update(kw)
    return e


def write(entries):
    d = Path(tempfile.mkdtemp(prefix="cbre_b7_"))
    p = d / "overrides.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    canon = C.canonical_property_fields()

    # --- postcode is now first-class, not merely tolerated ------------------- #
    ck("postcode" in canon, "postcode is a canonical property field")
    ck("epc" in canon, "epc is canonical (declared under B5)")

    # --- the guard accepts a field that EXISTS ON THE RECORDS --------------- #
    # `tenure` is deliberately NOT in the schema - it stands for the open-ended long tail.
    ck("tenure" not in canon, "control: tenure is NOT canonical, so this proves the new path")
    loaded, errs = M.load_overrides(write([ov("tenure", "Leasehold")]))
    ck(not loaded and errs, "without extra_fields, a non-canonical field is still refused")
    loaded, errs = M.load_overrides(write([ov("tenure", "Leasehold")]),
                                    extra_fields={"tenure"})
    ck(len(loaded) == 1 and not errs,
       f"WITH the field present on a record, the override is ACCEPTED {ascii(str(errs))}")

    # --- but a TYPO is still refused - the protection that matters ---------- #
    loaded, errs = M.load_overrides(write([ov("breeem", "Excellent")]),
                                    extra_fields={"tenure", "postcode"})
    ck(not loaded and errs, "a TYPO'd field name is still refused (it exists nowhere)")
    ck(any("breeem" in e for e in errs), "...and the refusal names the offending key")
    ck(any("no record" in e.lower() or "not a canonical" in e.lower() for e in errs),
       f"...and says what it checked {ascii(str(errs)[:150])}")

    # --- the other guards must not have been loosened ---------------------- #
    for fld, why in (("areaUnit", "DENIED unit"), ("rentUnit", "DENIED unit"),
                     ("id", "forbidden identity"), ("gallery", "forbidden structure"),
                     ("photo", "forbidden media"), ("regionCode", "forbidden derived")):
        loaded, errs = M.load_overrides(write([ov(fld, "x")]),
                                       extra_fields={fld})
        ck(not loaded and errs,
           f"{fld!r} is still refused even when present on a record ({why})")
    loaded, errs = M.load_overrides(write([ov("city", {"a": 1})]))
    ck(not loaded and errs, "a non-scalar value is still refused")
    loaded, errs = M.load_overrides(write([ov("city", "Corby", why="")]))
    ck(not loaded and errs, "a missing `why` is still refused")

    # --- a canonical field still works with no extra_fields at all ---------- #
    loaded, errs = M.load_overrides(write([ov("city", "Corby")]))
    ck(len(loaded) == 1 and not errs, "a canonical field needs no extra_fields (back-compatible)")

    # --- brand-new SCALARS are now DISCLOSED, not silently tolerated -------- #
    rec = {"park": "P", "city": "Corby", "tenure": "Leasehold", "postcode": "NN17 4XD",
           "__meta": {"source_file": "deck.pdf", "locator_base": "page 2"}}
    M._normalise_offspec(rec)
    ck(rec.get("tenure") == "Leasehold",
       "a brand-new scalar still SHIPS (auto-show is unchanged - it is not quarantined)")
    newf = (rec.get("__meta") or {}).get("new_fields") or []
    ck("tenure" in newf, f"...and is RECORDED as a new field {ascii(str(newf))}")
    ck("postcode" not in newf, "a now-canonical field is not reported as new")
    ck("city" not in newf and "park" not in newf, "canonical fields are never reported as new")

    # a structure is still QUARANTINED (the pre-existing behaviour, unchanged)
    rec2 = {"park": "P", "prov": {"park": "page 1"}, "__meta": {"source_file": "d.pdf"}}
    M._normalise_offspec(rec2)
    ck("prov" not in rec2 and "prov" in ((rec2["__meta"].get("offspec")) or {}),
       "an off-spec STRUCTURE is still quarantined into __meta.offspec")

    # --- the disclosure reaches the Gaps Report ----------------------------- #
    dsrc = (ROOT / "helpers" / "deliver.py").read_text(encoding="utf-8", errors="replace")
    ck("newFields" in dsrc, "deliver.py renders meta.newFields")
    msrc = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8", errors="replace")
    ck('"newFields"' in msrc, "merge writes meta.newFields")

    # --- both run.py call sites pass the record field set ------------------- #
    rsrc = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")
    ck(rsrc.count("extra_fields=") >= 2,
       f"both run.py load_overrides call sites pass extra_fields ({rsrc.count('extra_fields=')})")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
