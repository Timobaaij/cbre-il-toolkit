#!/usr/bin/env python3
"""open_field_scalar_test.py - an OPEN (reader-invented, undeclared) property field must be
a scalar (string/number/bool/null), never a list or a nested object - caught immediately and
clearly by validate-data, not discovered later as a confusing ledger gate failure.

THE DEFECT: canonical.schema.json's $defs.property set additionalProperties: true, so an
undeclared field could hold ANY JSON type. Two of four interpretation sub-agents on a live
run independently wrote a JSON array (sustainabilityFeatures: [...]) and an array of objects
(agents: [{...}, ...]) for information the other two readers correctly expressed as one
semicolon-joined string. validate-data raised nothing (arrays/objects are valid under an
unconstrained additionalProperties); the mistake only surfaced later, far less clearly, as
`ledger validate`'s "missing ['source_locator']" - the ledger-export code walks a list's
items looking for their own locators, which a single top-level prov[field] string cannot
supply. This is a recurring trap: "the source lists several items" is a completely natural
reason to reach for a JSON array, for ANY client's brochure.

Offline (schema + reference/interpretation.md + run.py text checks only, no build)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _base_property(**extra):
    p = {
        "id": 1, "country": "GB", "park": "P", "developer": "D", "city": "C",
        "status": "Available", "photo": "data:image/jpeg;base64,AAAA",
    }
    p.update(extra)
    return p


def _canonical(prop):
    return {"meta": {"client": "Test", "hero": {
        "topbar_meta": "Test", "eyebrow": "Test", "title_html": "Test",
        "lede": "Test", "footer_copyright": "Test"}}, "properties": [prop],
            "pois": [], "regions": {}}


def main() -> int:
    print("== a list value on an OPEN field is now a clear validate-data error ==")
    bad = _canonical(_base_property(
        sustainabilityFeatures=["Photovoltaic roof panels", "Rainwater harvesting"]))
    errs = C.validate_canonical(bad)
    ck(bool(errs), "a list value on an undeclared field is now REJECTED by validate_canonical")
    ck(any("sustainabilityFeatures" in e for e in errs) if errs else False,
       f"...and the error names the offending field (got {errs!r})")

    print()
    print("== a dict / array-of-objects value on an OPEN field is also rejected ==")
    bad2 = _canonical(_base_property(
        agents=[{"name": "A", "email": "a@x.com"}, {"name": "B", "email": "b@x.com"}]))
    errs2 = C.validate_canonical(bad2)
    ck(bool(errs2), "an array-of-objects value on an undeclared field is rejected")

    print()
    print("== a plain scalar on an OPEN field is untouched (the common, correct case) ==")
    good = _canonical(_base_property(
        sustainabilityFeatures="Photovoltaic roof panels; Rainwater harvesting",
        agents="Alice, a@x.com; Bob, b@x.com",
        roofLights="10%", yardDepth="50m"))
    errs3 = C.validate_canonical(good)
    ck(errs3 == [], f"scalar-valued open fields still validate cleanly (got {errs3!r})")

    print()
    print("== a DECLARED array/object field (gallery, districtProfile, __meta) is unaffected ==")
    good2 = _canonical(_base_property(
        gallery=["data:image/jpeg;base64,AAAA", "data:image/jpeg;base64,BBBB"]))
    errs4 = C.validate_canonical(good2)
    ck(errs4 == [],
       f"a schema-DECLARED array field (gallery) still accepts a list (got {errs4!r})")

    print()
    print("== the schema change itself ==")
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    prop_schema = schema["$defs"]["property"]
    ap = prop_schema.get("additionalProperties")
    ck(isinstance(ap, dict) and set(ap.get("type", [])) >= {"string", "number", "boolean", "null"},
       f"$defs.property.additionalProperties constrains undeclared fields to scalar types "
       f"(got {ap!r})")

    print()
    print("== the reader contract says so up front (not just a gate the reader discovers) ==")
    import run as R
    ck("NEVER a list" in R._FIELD_RULES.upper() or "NEVER A LIST" in R._FIELD_RULES.upper(),
       "run.py's _FIELD_RULES (the manifest's field_rules, handed to every reader) now bans "
       "list/object values explicitly")
    ck("scalar" in R._FIELD_RULES.lower(),
       "...and says what IS required (a scalar)")

    interp = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    ck("never a list" in interp.lower() or "never a JSON array".lower() in interp.lower(),
       "reference/interpretation.md's own Text-mode rules ALSO ban list/object values, so an "
       "orchestrator reading the contract file directly (not just the generated manifest) "
       "sees the same rule")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
