#!/usr/bin/env python3
"""f10_prov_marker_honoured_test.py - prov-containment honours `__meta.not_in_text_layer`, and a
`seen_as` turns the disclosure into a check rather than a hole. (F10, gate half)

A2 defined the marker in templates/record_schema.json (see f10_not_in_text_layer_marker_test):
per field, {reason, note?, seen_as?}, where `seen_as` is the text layer's own garbled form of the
value. `__meta` never survives merge, so the gate reads it from the PRE-MERGE records in
work/extract/*.json and joins to a ledger row on (source_file, field), disambiguated by value on
a multi-property deck.

WHAT THIS PINS:
  1. the marker is consulted ONLY after the normalised comparison has failed (no new bypass);
  2. with a `seen_as` that IS on the cited page: pass, and the PASS line counts it as verified;
  3. with a `seen_as` that is NOT on the page: reported at the field's own severity, naming
     the disclosed form (blocking for `region`, advisory otherwise);
  4. without a `seen_as`: skipped as disclosed for a stated reason (like the prose marker);
  5. a marker whose `reason` is outside the schema's closed list is ignored, not honoured;
  6. a multi-property deck: the ledger value picks the record; an ambiguity honours none;
  7. the legacy prose marker in `prov` still skips, unchanged.
Offline; in-process against the real command.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import gate_runner as G  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


# the cited page: a letter-spaced region, and a rent whose currency symbol is U+FFFD
PAGE = ("A NEW LOGISTICS FACILITY   R E G I O N :  N O R T H  V A L L E Y  C O R R I D O R   "
        "�12.50 PER SQ FT   HIGHFIELD BUSINESS PARK")


def build(rows, records):
    """rows: (pid, field, value, locator). records: pre-merge dicts for extract/deck_vision.json."""
    d = Path(tempfile.mkdtemp(prefix="cbre_f10_"))
    (d / "vision").mkdir()
    (d / "extract").mkdir()
    (d / "vision" / "manifest.json").write_text(json.dumps({"decks": [{
        "source_file": "deck.pdf", "mode": "text",
        "pages": [{"locator": "page 1", "text": PAGE}]}]}), encoding="utf-8")
    (d / "extract" / "deck_vision.json").write_text(json.dumps(records), encoding="utf-8")
    with open(d / "source_ledger.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["property_id", "record_type", "field", "value", "source_file",
                    "source_locator", "source_type", "extractor", "confidence",
                    "conflict_note", "verified"])
        for pid, f, v, loc in rows:
            w.writerow([pid, "property", f, v, "deck.pdf", loc, "pdf", "E-pdf", "High", "", "no"])
    (d / "canonical.json").write_text(json.dumps(
        {"meta": {}, "properties": [{"id": 1}, {"id": 2}], "pois": [], "regions": {}}), encoding="utf-8")
    return d


def run(d) -> tuple[int, str]:
    class A:
        canonical = str(d / "canonical.json")
        work = str(d)
        ledger = str(d / "source_ledger.csv")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = G.cmd_prov_containment(A())
    return rc, buf.getvalue()


LOC = "page 1 (text interpretation)"


def rec(**kw):
    meta = {"source_file": "deck.pdf", "source_type": "pdf"}
    if "nitl" in kw:
        meta["not_in_text_layer"] = kw.pop("nitl")
    return dict(kw, __meta=meta)


def main() -> int:
    print("0. baseline: the letter-spaced region already passes on the normalised comparison")
    rc, out = run(build([(1, "region", "North Valley Corridor", LOC)],
                        [rec(region="North Valley Corridor")]))
    ck(rc == 0 and "disclosed" not in out,
       "flattening both sides matches the spaced-out page; no marker needed, none consulted")

    print("1. the marker is consulted only AFTER the comparison fails")
    rc, out = run(build([(1, "region", "North Valley Corridor", LOC)],
                        [rec(region="North Valley Corridor",
                             nitl={"region": {"reason": "spacing", "seen_as": "NOT ON THE PAGE AT ALL"}})]))
    ck(rc == 0 and "disclosed" not in out,
       "a value that verifies directly passes even with a wrong seen_as: the marker is never a "
       "path INTO a failure")

    print("2. a failing value with a seen_as that IS on the page: verified")
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC)],      # not what the page says
                        [rec(region="Northern Valley Corridor",
                             nitl={"region": {"reason": "spacing",
                                              "seen_as": "N O R T H  V A L L E Y  C O R R I D O R"}})]))
    ck(rc == 0, "the disclosed text-layer form occurs on the page: no block")
    ck("1 disclosed via __meta.not_in_text_layer of which 1 verified by seen_as" in out,
       "the PASS line counts the disclosure AND the verification, so a reviewer sees it happened")

    print("3. a seen_as that is NOT on the page is reported at the field's own severity")
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC)],
                        [rec(region="Northern Valley Corridor",
                             nitl={"region": {"reason": "spacing", "seen_as": "SOUTH VALLEY"}})]))
    ck(rc == 1 and "STATUS: BLOCKED" in out, "`region` with a false seen_as BLOCKS")
    ck("marker says the text layer shows it as 'SOUTH VALLEY'" in out
       and "THAT form appears nowhere on that page either" in out,
       "...and the message names the disclosed form, so the fix is one lookup")
    rc, out = run(build([(1, "park", "Highfield Enterprise Park", LOC)],
                        [rec(park="Highfield Enterprise Park",
                             nitl={"park": {"reason": "composed", "seen_as": "HIGHFIELD ENTERPRISE"}})]))
    ck(rc == 0 and "[note] property=1 field=park" in out and "SOUTH" not in out,
       "the same failure on an advisory field (`park`) is a note, not a block")

    print("4. a marker with no seen_as is a disclosure for a stated reason: skipped")
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC)],
                        [rec(region="Northern Valley Corridor", nitl={"region": {"reason": "image"}})]))
    ck(rc == 0 and "1 disclosed via __meta.not_in_text_layer of which 0 verified" in out,
       "an `image` marker without seen_as skips the row and is counted as disclosed, not verified")
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC)],
                        [rec(region="Northern Valley Corridor",
                             nitl={"region": {"reason": "glyph", "seen_as": "�"}})]))
    ck(rc == 0 and "0 verified" in out,
       "a seen_as too short to be evidence once flattened is treated as no claim, not as verified")

    print("5. a marker outside the schema's closed reason list is ignored")
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC)],
                        [rec(region="Northern Valley Corridor",
                             nitl={"region": {"reason": "because", "seen_as": "N O R T H  V A L L E Y"}})]))
    ck(rc == 1 and "disclosed" not in out,
       "reason 'because' is not in {image, glyph, spacing, composed, other}: the row is judged "
       "as if unmarked, and blocks")
    ck(G.PROV_MARKER_REASONS == {"image", "glyph", "spacing", "composed", "other"},
       "the gate's reason list is the schema's")
    schema = json.loads((ROOT / "templates" / "record_schema.json").read_text(encoding="utf-8-sig"))
    enum = schema["properties"]["__meta"]["properties"]["not_in_text_layer"]["additionalProperties"]["properties"]["reason"]["enum"]
    ck(set(enum) == G.PROV_MARKER_REASONS, "...pinned against record_schema.json itself")

    print("6. a multi-property deck: the ledger value picks the record")
    two = [rec(region="Northern Valley Corridor",
               nitl={"region": {"reason": "spacing", "seen_as": "N O R T H  V A L L E Y  C O R R I D O R"}}),
           rec(region="Southern Valley Corridor",
               nitl={"region": {"reason": "spacing", "seen_as": "S O U T H  V A L L E Y"}})]
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC),
                         (2, "region", "Southern Valley Corridor", LOC)], two))
    ck(rc == 1 and "property=2 field=region" in out and "property=1 field=region" not in out,
       "each row is joined to ITS record's marker: property 1 verifies, property 2's disclosed "
       "form is not on the page and blocks")
    same = [rec(region="Northern Valley Corridor", nitl={"region": {"reason": "image"}}),
            rec(region="Northern Valley Corridor", nitl={"region": {"reason": "image"}})]
    rc, out = run(build([(1, "region", "Northern Valley Corridor", LOC)], same))
    ck(rc == 1 and "disclosed" not in out,
       "two records marking the same field with the same value are AMBIGUOUS: neither is "
       "honoured, because a marker is an admission about one specific reading")

    print("7. the legacy prose marker still skips, unchanged")
    rc, out = run(build([(1, "region", "Northern Valley Corridor",
                          f"page 1 (text interpretation; {G.PROV_NOT_IN_TEXT}: cover artwork)")],
                        [rec(region="Northern Valley Corridor")]))
    ck(rc == 0 and "checked" in out, "prose `not in text layer` in the locator skips the row")

    print("8. the blocking message tells the reader about BOTH hatches")
    rc, out = run(build([(1, "region", "Eastern Plains", LOC)], [rec(region="Eastern Plains")]))
    ck(rc == 1 and "__meta.not_in_text_layer.region = {reason, seen_as}" in out
       and G.PROV_NOT_IN_TEXT in out,
       "an unmarked failure names the structured marker (with seen_as) and the prose one")

    print()
    if FAILS:
        print(f"F10 PROV MARKER HONOURED TEST: FAIL ({len(FAILS)})")
        return 1
    print("F10 PROV MARKER HONOURED TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
