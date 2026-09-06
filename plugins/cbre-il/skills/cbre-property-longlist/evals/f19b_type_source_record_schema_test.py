#!/usr/bin/env python3
"""f19b_type_source_record_schema_test.py - the reader registry's `type` comes from the PRE-MERGE
record schema where it declares the field, and from canonical only where it does not. (SEAM-18)

THE DEFECT. Contract C1 told the registry to read each field's type off canonical.schema.json.
That is the POST-MERGE shape. A reader writes the PRE-MERGE record (templates/record_schema.json),
and merge converts it. The two schemas disagree on exactly the field a reader is most likely to be
got wrong: canonical declares `warehouseArea` a bare `number`, while the reader contract says write
a dimensioned quantity THE WAY THE SOURCE PRINTS IT (a string carrying its unit) and the record
schema correctly says `number|string`. So the registry rendered `warehouseArea: number` into every
reader prompt, contradicting the contract on a headline field; the prompt renderer had to hold the
line with a static precedence note, which is a workaround for a wrong type source.

WHAT THIS PINS (interpret_prep.reader_field_registry):
  1. for every name record_schema.json declares with a type, the registry's `type` IS that type;
  2. for every other declared name, the registry's `type` is canonical.schema.json's (unchanged);
  3. `warehouseArea` is rendered `number|string`, not canonical's bare `number`;
  4. the set of names on which the two schemas DISAGREE is exactly {warehouseArea}: a new
     disagreement must be decided on its merits, so this goes red rather than silently picking;
  5. everything A2 built survives: the `fills` classification, the exclusion of orchestrator-only
     fields, the `x-reader-format` hint, the enum-derived hint and `reader_field_names()`;
  6. an unreadable record schema DEGRADES to canonical-only typing (what the registry did before
     SEAM-18), never raises, and the undeclared-name fallback is still canonical's open union.
Offline, no build.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import interpret_prep as IP  # noqa: E402
import run as R  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def _types(t):
    return set(t) if isinstance(t, list) else {t}


def main() -> int:
    canonical = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8-sig"))
    props = canonical["$defs"]["property"]["properties"]
    open_type = canonical["$defs"]["property"]["additionalProperties"]["type"]
    record = json.loads((ROOT / "templates" / "record_schema.json").read_text(encoding="utf-8-sig"))["properties"]
    record = {k: v for k, v in record.items() if k != "__meta"}
    names = R._reader_field_list()
    full = IP.reader_field_registry(names, include_orchestrator=True)
    reg = IP.reader_field_registry(names)
    by = {e["name"]: e for e in full}

    print("== 1. record schema wins where it declares the name ==")
    ck(bool(record) and all(k in props for k in record),
       "every record-schema field is also a canonical field (the pre-merge shape is a subset by name)")
    wrong = [k for k in record if k in by and record[k].get("type") is not None and by[k]["type"] != record[k]["type"]]
    ck(not wrong, f"every record-declared name is typed off record_schema.json (wrong: {wrong})")

    print("== 2. canonical is the fallback for names the record schema does not declare ==")
    wrong = [k for k in props if k in by and k not in record and props[k].get("type") is not None
             and by[k]["type"] != props[k]["type"]]
    ck(not wrong, f"every name only canonical declares keeps canonical's type (wrong: {wrong})")

    print("== 3. the measured case ==")
    ck(by["warehouseArea"]["type"] == ["number", "string"],
       "warehouseArea is rendered number|string (write it as printed; merge converts), not the bare number")
    ck("format" in by["warehouseArea"],
       "warehouseArea still carries its x-reader-format hint (the fix changes the type source, not the hint)")

    print("== 4. the disagreement set is known and closed ==")
    differ = sorted(k for k in record if record[k].get("type") is not None
                    and record[k].get("type") != props[k].get("type"))
    ck(differ == ["warehouseArea"],
       f"the two schemas disagree on exactly [warehouseArea] (got {differ}); a new disagreement must be "
       "decided on its merits, not inherited silently")

    print("== 5. what A2 built survives ==")
    ck(all(e["fills"] == "reader" for e in reg) and "districtProfile" not in IP.reader_field_names(reg),
       "orchestrator-only fields are still excluded from the reader registry")
    ck(by["warehouseAreaSqm"]["format"] == props["warehouseAreaSqm"]["x-reader-format"],
       "x-reader-format is still read off the schema node")
    ck("format" in by["areaUnit"] and all(repr(v) in by["areaUnit"]["format"] for v in props["areaUnit"]["enum"]),
       "the enum-derived hint is still produced")
    ck(IP.reader_field_names(reg) == [e["name"] for e in reg], "reader_field_names round-trips")
    ck(json.dumps(full).isascii(), "the full registry still serialises ASCII-only (F8)")

    print("== 6. degradation ==")
    orig = IP.RECORD_SCHEMA_FILE
    try:
        IP.RECORD_SCHEMA_FILE = ROOT / "templates" / "does_not_exist.json"
        degraded = {e["name"]: e for e in IP.reader_field_registry(names, include_orchestrator=True)}
        ck(degraded["warehouseArea"]["type"] == props["warehouseArea"]["type"],
           "an unreadable record schema degrades to canonical-only typing, never raises")
        ck(all(degraded[k]["type"] == props[k]["type"] for k in degraded if k in props and props[k].get("type") is not None),
           "under degradation every declared name is typed off canonical (the pre-SEAM-18 behaviour)")
    finally:
        IP.RECORD_SCHEMA_FILE = orig
    fb = IP.reader_field_registry(["someTemplateOnlyName"])
    ck(fb and fb[0]["type"] == open_type, "a name neither schema declares still gets canonical's open scalar union")

    print("STATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
