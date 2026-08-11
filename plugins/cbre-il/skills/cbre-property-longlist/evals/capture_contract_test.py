#!/usr/bin/env python3
"""capture_contract_test.py - the exit-3 handoff HANDS the reader the field registry. (B58)

THE DEFECT. Nothing in the interpretation handoff ever named the field set. `reference/
interpretation.md` gave an illustrative list ending in an ellipsis; `templates/record_schema.json`
names 17 of 53 fields with `additionalProperties: true`, which reads as a closed set; and the
contract's fallback pointer, "the same names the deterministic extractors emit", does not cover
`sprinklers`, `permitting`, `divisibleFrom`, `rentFree` or the `expansion*` family at all (they are
absent from extract_xlsx.COLUMN_MAP - grep it).

THE COST, measured. On one live run all three interpretation readers independently reported "no
canonical field exists for office rent / sprinklers / permitting / expansion, so they are dropped",
for rows printed on the page. Merge then wrote each omission as a ledger row asserting "absent in
all sources" - roughly 100 false claims in a client deliverable, telling the broker to chase an
agent for data already in the deck. Two Opus reviewers found it independently; no mechanical gate
could, because every gate checks that POPULATED fields trace to a source and none can know what the
page said.

WHAT THIS PINS:
  1. the manifest's `fields` array is GENERATED from _common.canonical_property_fields(), so it can
     never drift from what the pipeline actually carries;
  2. it excludes exactly the pipeline-ASSIGNED fields and nothing else - in particular it still
     contains every field the live failure dropped;
  3. `warehouseRentVal` stays on the reader list (the contract requires the numeric annual rate)
     while the derived *Val twins do not;
  4. `field_rules` states all three capture rules, including that a stated NEGATIVE is data;
  5. the contract file itself no longer ends its field list in an ellipsis.
Offline, no build.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import run as R  # noqa: E402

# the six families the live failure dropped, plus the parties/commercials around them
MUST_OFFER = [
    "sprinklers", "permitting", "divisibleFrom", "rentFree",
    "expansionBuilding", "expansionPark", "officeRent", "serviceCharge",
    "landlord", "reit", "incentives", "leaseTerm", "landPrice", "epc",
]


def main() -> int:
    fails = []

    def ck(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    fields = R._reader_field_list()
    registry = set(C.canonical_property_fields())

    ck(bool(fields), "the manifest offers a non-empty field list")
    ck(fields == sorted(fields), "the list is sorted, so the manifest is byte-deterministic")

    for f in MUST_OFFER:
        ck(f in fields, f"`{f}` is offered to the reader (it was DROPPED on the live run)")

    # generated, never restated: every offered field is a real registry field
    ck(set(fields) <= registry,
       "every offered field exists in _common.canonical_property_fields()")
    # and the only omissions are the pipeline-assigned ones
    missing = registry - set(fields)
    ck(missing == set(R._PIPELINE_ASSIGNED_FIELDS),
       f"the ONLY registry fields withheld are the pipeline-assigned ones (got {sorted(missing)})")

    ck("warehouseRentVal" in fields,
       "warehouseRentVal IS asked of the reader - the contract requires the numeric annual rate")
    for twin in ("officeRentVal", "officeAreaVal", "expansionParkVal"):
        ck(twin not in fields, f"{twin} is NOT asked of the reader - the pipeline derives it")
    for assigned in ("id", "photo", "plan", "gallery", "preBaked", "regionCode"):
        ck(assigned not in fields, f"{assigned} is NOT asked of the reader - merge/enrich assigns it")

    # the rules that turn the list into a floor rather than a ceiling
    # assert the ASSEMBLED string, not the source text: an implicitly-concatenated literal
    # splits phrases across lines, so a source grep silently misses them.
    rules = R._FIELD_RULES
    ck("NOT a limit" in rules or "NOT A LIMIT" in rules.upper(),
       "field_rules says the registry is a floor, not a ceiling")
    ck("STATED NEGATIVE IS DATA" in rules.upper(),
       "field_rules states that a printed 'Not charged' / 'No' is DATA, not an absence")
    ck("additionalProperties" in rules or "OPEN" in rules,
       "field_rules states the schema is open, so an unlisted stated row is emitted, not dropped")
    ck("never a reason" in rules.lower(),
       "field_rules bans 'there is no field for X' as a reason to omit X")

    # the contract file must not reintroduce the ellipsis list that caused this
    contract = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    ck("earlyAccess, …`" not in contract,
       "reference/interpretation.md no longer ends its field list in an ellipsis")
    ck("NOT a limit" in contract,
       "reference/interpretation.md states the registry is not a limit")
    ck("Do NOT paste an abbreviated" in contract,
       "reference/interpretation.md warns the ORCHESTRATOR not to inline a shorter list "
       "(the actual root cause)")

    # the schema must not read as closed
    schema = (ROOT / "templates" / "record_schema.json").read_text(encoding="utf-8")
    ck("ILLUSTRATIVE, NOT A CLOSED SET" in schema,
       "record_schema.json says its named fields are illustrative, not the field set")

    # The rule must live in the SKILL, not in any one operator's memory - this skill is shared.
    # These three assertions are what make it portable: the orchestrator rule, the
    # reader-report tripwire, and the reviewer's under-capture mandate.
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ck("Do NOT paste an abbreviated field list" in skill,
       "SKILL.md forbids inlining a shorter field list in a sub-agent prompt (root cause)")
    ck("BLOCKING signal, not an accepted limitation" in skill,
       "SKILL.md makes a reader's 'no canonical field for X, so I dropped it' a BLOCKING signal")
    ck("CAPTURE EVERY FIELD THE SOURCE STATES" in skill,
       "SKILL.md states the capture rule at Stage 1, where the dispatch happens")
    ck("capture-symmetry" in skill,
       "SKILL.md tells the orchestrator to run the capture-symmetry gate")

    gates = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8")
    ck("UNDER-CAPTURE IS THE MIRROR IMAGE OF FABRICATION" in gates,
       "gates.md gives G-honesty an explicit under-capture mandate, ranked with fabrication")
    ck("capture-symmetry" in gates,
       "gates.md points the reviewer at the capture-symmetry notes as its starting point")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
