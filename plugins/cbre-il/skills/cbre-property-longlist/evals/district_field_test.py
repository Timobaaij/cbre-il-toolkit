#!/usr/bin/env python3
"""district_field_test.py - `district` is a plain first-class STRING field (like city/park/
postcode), never a reserved container object; the labour-market micro-profile object that
used to squat that key is renamed to `districtProfile`.

THE DEFECT: canonical.schema.json declared top-level `district` as an OBJECT (an
orchestrator-filled labour-market research container - nothing in helpers/ ever writes to
it), yet `_common.canonical_property_fields()` (which derives its set from that same schema)
feeds `district` to EVERY interpretation sub-agent as a "reader-fillable" name via
reference/interpretation.md's live-generated `fields` array, and gate_runner.py's own
PROV_ADVISE_FIELDS = {"city", "district", "park", "address", "postcode"} already expects it
to be a flat checkable string grouped with exactly those siblings. A reader that (correctly,
per its own contract) filled `district` with a plain estate name - e.g. "Earlstree Industrial
Estate" - hard-blocked validate-data with "'Earlstree Industrial Estate' is not of type
'object'" on a live run, for every property that carried it. This is a genuine, recurring
trap for any client: 'district' is the single most natural key for 'the estate/sub-area a
park sits within', which two independent brochures on one live run reached for unprompted.

Offline, no build (except a lightweight template-JS text check)."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import merge as M  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    props = schema["$defs"]["property"]["properties"] if "$defs" in schema else schema["properties"]

    print("== schema: district is a plain string, districtProfile is the container ==")
    ck("district" in props, "canonical.schema.json declares a top-level `district` property")
    ck(props.get("district", {}).get("type") == "string",
       f"`district` is type string, got {props.get('district', {}).get('type')!r}")
    ck("districtProfile" in props,
       "canonical.schema.json declares the renamed `districtProfile` container")
    ck(props.get("districtProfile", {}).get("type") == "object",
       f"`districtProfile` is type object, got {props.get('districtProfile', {}).get('type')!r}")
    ck("district" in (props.get("districtProfile", {}).get("properties") or {}),
       "the renamed container keeps its OWN nested `district` string sub-field (the name being profiled)")

    print()
    print("== canonical_property_fields() reflects the rename ==")
    C._CANON_PROPERTY_FIELDS = None  # force a fresh scan (module-level cache)
    fields = C.canonical_property_fields()
    ck("district" in fields, "`district` (the plain string) is a live canonical field")
    ck("districtProfile" in fields, "`districtProfile` (the container) is a live canonical field")

    print()
    print("== merge.py protects the CONTAINER from an override, not the plain string ==")
    ck("districtProfile" in M._OV_FORBIDDEN,
       "the renamed container is in merge._OV_FORBIDDEN (an override may never inject structure)")
    ck("district" not in M._OV_FORBIDDEN,
       "the plain `district` string is NOT forbidden - it is correctable like city/park")

    print()
    print("== _common.py: district stays non-translatable; districtProfile joins it ==")
    ck("district" in C.IDENTIFIER_FIELDS,
       "`district` (a proper-noun estate name) stays out of the translator's reach, like city/park")
    ck("districtProfile" in C.IDENTIFIER_FIELDS,
       "`districtProfile` (structural container) is protected from translation too")

    print()
    print("== the template's JS reads the renamed key ==")
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")
    ck("p.districtProfile" in tpl, "the template reads p.districtProfile for the workforce panel")
    ck("p.district ||" not in tpl and "p.district||" not in tpl,
       "the template no longer reads the old p.district object (bare property access)")
    # the human-visible UI label/CSS class names legitimately keep the word "District" -
    # only the JSON property ACCESS on `p` was reserved and needed to move.
    ck("district-panel" in tpl, "the CSS class name (a UI label, not a JSON key) is untouched")
    ck('T("wf_district_label")' in tpl, "the i18n label key (a UI label, not a JSON key) is untouched")

    print()
    print("== version bump ==")
    version = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8")
    # >= v38, not the literal: the rename landed at v38, so any LATER label is equally valid.
    # A literal here re-breaks on the very next unrelated bump - exactly what a literal "v28"
    # cost areaunit_test once already (see its own recorded note), and what v39 hit.
    _lbl = version.splitlines()[0].strip()
    ck(int(re.sub(r"\D", "", _lbl) or 0) >= 38,
       f"assets/VERSION was bumped at/after the district rename (v38) {ascii(_lbl)}")
    import hashlib
    tmpl_text = C.load_template()
    expected_sha = hashlib.sha256(tmpl_text.encode("utf-8")).hexdigest()
    recorded_sha = C.load_version().get("chrome_sha256", "")
    ck(recorded_sha == expected_sha,
       f"VERSION's chrome_sha256 matches the CRLF-normalised TEXT hash of the live template "
       f"(recorded {recorded_sha[:12]}, computed {expected_sha[:12]})")

    print()
    print("== the changelog documents the rename ==")
    changelog = (ROOT / "reference" / "template-contract.md").read_text(encoding="utf-8")
    ck("**v38**" in changelog, "reference/template-contract.md has a v38 entry")
    ck("districtProfile" in changelog, "the v38 entry names the rename")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
