#!/usr/bin/env python3
"""f19_typed_field_registry_test.py - the reader-facing field registry carries TYPES, and no
orchestrator-only field. (F19, contract C1)

THE DEFECT. The exit-3 manifest's `fields` was a flat list of 47 bare strings: no type, no format,
no note of who fills a field. On a live run validate-data failed 12 times and NOT ONE failure was
an open-schema problem - every one was a DECLARED canonical field filled with the wrong type. Ten
were `warehouseAreaSqm: <integer>` from six readers independently (the schema wants a display
string; "write the value the way the source prints it" produces the raw integer when nothing says
otherwise). Two were a prose paragraph in `districtProfile`, an `object` whose own description
says the spine never fills it - the ONLY ORCHESTRATOR-FILLED field in the schema, and it was in
the list handed to readers. Ten of eleven properties were affected, so this blocks essentially
every run with a dual-unit area.

WHAT THIS PINS (interpret_prep.reader_field_registry, the C1 producer):
  1. every entry is {name, type, fills} with `type` READ OFF A SCHEMA, never restated. WHICH schema
     was corrected in Wave 2 (SEAM-18): contract C1 first said canonical.schema.json, but that is
     the POST-MERGE shape; a reader writes the PRE-MERGE record (templates/record_schema.json),
     and the two disagree on `warehouseArea` (canonical `number`, record `number|string`). The
     reader contract says write a dimensioned value the way the source prints it and merge
     converts, so rendering canonical's `number` told the reader something the contract
     contradicts, on a headline field. The type is therefore record_schema.json's where that file
     declares the name, and canonical.schema.json's only for a name it does not;
  2. every `fills: "orchestrator"` entry is EXCLUDED from what readers are handed, and the
     orchestrator marker is the schema description's ORCHESTRATOR-FILLED, nothing else;
  3. no reader entry is typed `object` (a reader cannot fill one correctly);
  4. `format` exists exactly where the type alone is not enough: `warehouseAreaSqm` (the measured
     case), the four numeric names the prompt used to spell out in prose, and any enum field
     (derived from the enum itself, so hint and validator cannot disagree);
  5. the registry is sorted, JSON-serialisable and ASCII-only (F8), and a name the schema does not
     declare degrades to the schema's open-field scalar union rather than crashing.
Offline, no build.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import interpret_prep as IP  # noqa: E402
import run as R  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8-sig"))
    props = schema["$defs"]["property"]["properties"]
    record = json.loads((ROOT / "templates" / "record_schema.json").read_text(encoding="utf-8-sig"))["properties"]
    names = R._reader_field_list()
    ck(bool(names) and all(isinstance(n, str) for n in names),
       "run.py still supplies the NAME set (bare strings) - the registry types them, it does not pick them")

    reg = IP.reader_field_registry(names)
    full = IP.reader_field_registry(names, include_orchestrator=True)

    print("== 1. shape and type fidelity ==")
    ck(bool(reg), "the reader registry is non-empty")
    ck(all(set(e) >= {"name", "type", "fills"} for e in reg), "every entry carries name, type and fills")
    ck(all(set(e) <= {"name", "type", "fills", "format"} for e in reg),
       "no entry carries a key outside the C1 contract {name, type, fills, format?}")
    ck([e["name"] for e in reg] == sorted(e["name"] for e in reg), "entries are sorted by name (deterministic manifest)")
    # SEAM-18: the type source is the PRE-MERGE record schema where it declares the name (that is
    # the shape a reader writes), canonical only where it does not. Asserting canonical for every
    # name would re-recruit the next reader into the contract C1 mistake.
    expected = {n: (record[n].get("type") if n in record and record[n].get("type") is not None
                    else props[n].get("type")) for n in props}
    mismatch = [e["name"] for e in full if e["name"] in expected and e["type"] != expected[e["name"]]]
    ck(not mismatch, "every declared name's `type` equals record_schema.json's where it declares the name, "
                     f"else canonical.schema.json's (mismatch: {mismatch})")
    ck(props["warehouseArea"].get("type") == "number" and record["warehouseArea"].get("type") == ["number", "string"],
       "the two schemas still disagree on warehouseArea (canonical number, record number|string) - the case SEAM-18 exists for")
    ck(next(e["type"] for e in full if e["name"] == "warehouseArea") == ["number", "string"],
       "warehouseArea is rendered number|string (the reader writes it as printed; merge converts), NOT canonical's bare number")
    ck(all(e["fills"] in ("reader", "orchestrator") for e in full), "fills is exactly 'reader' or 'orchestrator'")

    print("== 2. orchestrator-only fields never reach a reader ==")
    orch_by_schema = {k for k, v in props.items() if "ORCHESTRATOR-FILLED" in str(v.get("description") or "")}
    ck(orch_by_schema == {"districtProfile"},
       f"the schema marks exactly districtProfile as ORCHESTRATOR-FILLED (got {sorted(orch_by_schema)}); "
       "if this changes, the registry follows the schema automatically")
    orch_in_full = {e["name"] for e in full if e["fills"] == "orchestrator"}
    ck(orch_in_full == orch_by_schema & set(names),
       "the registry derives `fills: orchestrator` from that marker and nothing else")
    ck(all(e["fills"] == "reader" for e in reg), "the READER registry contains no orchestrator entry")
    ck("districtProfile" not in IP.reader_field_names(reg),
       "districtProfile (object, orchestrator-filled) is NOT offered to readers - two of seven wrote prose into it")
    ck("district" in IP.reader_field_names(reg) and props["district"]["type"] == "string",
       "the plain string `district` (the estate name every reader fills) IS still offered")
    ck(set(IP.reader_field_names(reg)) == set(names) - orch_by_schema,
       "the reader registry is the caller's name set minus the orchestrator-filled ones and nothing else")

    print("== 3. no reader entry is an object ==")
    def _types(t):
        return set(t) if isinstance(t, list) else {t}
    objs = [e["name"] for e in reg if "object" in _types(e["type"]) or "array" in _types(e["type"])]
    ck(not objs, f"no reader entry is typed object/array (got {objs})")

    print("== 4. format hints where the type alone is not enough ==")
    by = {e["name"]: e for e in reg}
    ck("format" in by.get("warehouseAreaSqm", {}) and "sq m" in by["warehouseAreaSqm"]["format"]
       and "string" in _types(by["warehouseAreaSqm"]["type"]),
       "warehouseAreaSqm is typed string AND carries a display-string format hint with a sq m example")
    ck(by["warehouseAreaSqm"]["format"] == props["warehouseAreaSqm"]["x-reader-format"],
       "the hint is READ OFF the schema's x-reader-format, not restated in code")
    for n in ("lat", "lng", "warehouseArea", "warehouseRentVal"):
        ck(n in by and "number" in _types(by[n]["type"]) and "format" in by[n],
           f"{n} is typed number and carries a format hint (the prose workaround in the prompt can now go)")
    ck("format" in by.get("areaUnit", {}) and all(repr(v) in by["areaUnit"]["format"] for v in props["areaUnit"]["enum"]),
       "areaUnit's format is derived from its schema enum and names every admitted value")
    plain = [n for n, e in by.items() if e["type"] == "string" and "format" in e and "enum" not in props.get(n, {})
             and "x-reader-format" not in props.get(n, {})]
    ck(not plain, f"no plain string field carries an invented hint (got {plain}) - format is opt-in per schema node")

    print("== 5. serialisation, determinism, degradation ==")
    body = json.dumps(reg)
    ck(body.isascii(), "the registry serialises ASCII-only (F8: cp1252 json.load never trips on it)")
    ck(json.dumps(IP.reader_field_registry(list(reversed(names)))) == body,
       "input order does not change the output (sorted, deterministic)")
    fb = IP.reader_field_registry(["someTemplateOnlyName"])
    ck(fb and fb[0]["type"] == props_open(schema) and fb[0]["fills"] == "reader",
       "a name the schema does not declare gets the schema's open-field scalar union, not a crash")
    ck(IP.reader_field_names(reg) == [e["name"] for e in reg], "reader_field_names round-trips the bare names")

    print("STATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    return 1 if FAILS else 0


def props_open(schema):
    return schema["$defs"]["property"]["additionalProperties"]["type"]


if __name__ == "__main__":
    raise SystemExit(main())
