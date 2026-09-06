#!/usr/bin/env python3
"""f10_not_in_text_layer_marker_test.py - a reader can mark ONE field as "correct but not findable
verbatim in the cited page text, for this stated reason", machine-readably. (F10, schema half)

THE DEFECT. Ordinary PDF text-layer artefacts defeat the prov-containment gate on real decks:
letter-spaced display type puts runs like spaced-out digits in the text layer, and several decks
render a currency symbol as a replacement character. Readers transcribe correctly, disclose the
divergence in the field's own `prov` in PROSE, and still cannot satisfy the gate, because prose is
not something a gate can consume beyond one substring (`not in text layer`, the image escape
hatch). The structured twin lives in `__meta.not_in_text_layer` of record_schema.json: per field,
optional, with a closed `reason` class, a one-line `note`, and an optional `seen_as` (the text
layer's own form of the value) that turns the admission into a CHECKABLE claim.

WHAT THIS PINS (templates/record_schema.json; gate_runner honours the marker in a later wave):
  1. the marker exists at `__meta.not_in_text_layer`, keyed by field, each value an object;
  2. `reason` is required and closed to exactly {image, glyph, spacing, composed, other};
  3. `note` is required when reason is `other`, optional otherwise; `seen_as` is a string;
  4. the schema keeps continuity with the legacy prose marker (its description names the phrase
     gate_runner.PROV_NOT_IN_TEXT still accepts);
  5. it is NOT mirrored onto the canonical property (a record's `__meta` never survives merge,
     and canonical's open-field rule admits scalars only), so B4 reads it from the pre-merge
     records under work/extract/.
Offline, no build. Uses jsonschema when present; the structural checks run regardless.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

FAILS = []
REASONS = {"image", "glyph", "spacing", "composed", "other"}


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    rs = json.loads((ROOT / "templates" / "record_schema.json").read_text(encoding="utf-8-sig"))
    meta = rs["properties"]["__meta"]["properties"]

    print("== 1. shape ==")
    ck("not_in_text_layer" in meta, "record_schema.json declares __meta.not_in_text_layer")
    node = meta.get("not_in_text_layer") or {}
    ck(node.get("type") == "object", "it is an object keyed by field name")
    per = node.get("additionalProperties") or {}
    ck(isinstance(per, dict) and per.get("type") == "object", "each per-field value is an object")
    ck("not_in_text_layer" not in rs.get("required", []) and "not_in_text_layer" not in rs["properties"]["__meta"].get("required", []),
       "the marker is OPTIONAL (a record without one is unchanged)")

    print("== 2. reason class ==")
    ck(set((per.get("properties") or {}).get("reason", {}).get("enum") or []) == REASONS,
       f"`reason` is closed to exactly {sorted(REASONS)}")
    ck("reason" in (per.get("required") or []), "`reason` is required on every marker")

    print("== 3. note and seen_as ==")
    ck((per.get("properties") or {}).get("note", {}).get("type") == "string", "`note` is a string")
    ck((per.get("properties") or {}).get("seen_as", {}).get("type") == "string", "`seen_as` is a string")
    ck("note" not in (per.get("required") or []), "`note` is not required for a self-explaining class (image, glyph, ...)")
    ck((per.get("if") or {}).get("properties", {}).get("reason", {}).get("const") == "other"
       and "note" in ((per.get("then") or {}).get("required") or []),
       "`note` becomes required when reason is `other`")

    try:
        from jsonschema import Draft202012Validator as V
        V.check_schema(rs)
        val = V(rs)

        def errs(marker):
            rec = {"park": "Example Park", "__meta": {"source_file": "x.pdf", "source_type": "pdf",
                                                      "not_in_text_layer": marker}}
            return [e.message for e in val.iter_errors(rec)]
        ck(errs({"warehouseRent": {"reason": "glyph", "note": "currency symbol extracted as U+FFFD",
                                   "seen_as": "�12.50 per sq ft"}}) == [],
           "a full marker (reason + note + seen_as) validates")
        ck(errs({"park": {"reason": "image"}}) == [], "a bare `image` marker validates (note optional)")
        ck(errs({"park": {"reason": "other"}}) != [], "`other` without a note is rejected")
        ck(errs({"park": {"reason": "photo", "note": "x"}}) != [], "an unlisted reason is rejected")
        ck(errs({"park": "not in text layer"}) != [], "the legacy prose string is not accepted IN THIS SLOT (it belongs in prov)")
        ck(errs({}) == [], "an empty marker object validates")
    except ImportError:
        print("  skip  jsonschema not installed - structural checks only")

    print("== 4. continuity with the prose marker ==")
    import gate_runner as G  # noqa: E402
    ck(G.PROV_NOT_IN_TEXT == "not in text layer", "gate_runner still names the legacy prose marker")
    ck(G.PROV_NOT_IN_TEXT in str(node.get("description") or ""),
       "the schema description names that phrase, so a reader sees the two are one mechanism")
    ck("seen_as" in str(node.get("description") or "") and "CHECKABLE" in str(node.get("description") or ""),
       "the description says what seen_as is for (a checkable claim, not a bypass)")

    print("== 5. not mirrored onto the canonical property ==")
    cs = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8-sig"))
    prop = cs["$defs"]["property"]
    ck("not_in_text_layer" not in prop["properties"], "canonical.schema.json does not carry the marker as a property field")
    ck("object" not in (prop.get("additionalProperties") or {}).get("type", []),
       "canonical's open-field rule admits scalars only, which is why the marker stays on the pre-merge record")

    print("STATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
