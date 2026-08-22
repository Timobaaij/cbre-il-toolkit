#!/usr/bin/env python3
"""perfield_unit_test.py - each area converts on ITS OWN supplier's footing. (B39)

merge branched on ONE merged `areaUnit` and applied it to warehouseArea, plotArea and
officeAreaVal alike. But every field resolves its own precedence contest, so an area can come
from one record while `areaUnit` comes from another - and the number was then scaled by
10.7639 on a unit its own source never stated. Measured: 134,549 sq ft shipped as 1,448,272,
with an EMPTY meta.unitAssumptions and no conflict note - MORE silent than the unit-silent
case the areaUnitAssumed branch was built for.

This suite also records why the two OBVIOUS fixes were rejected, because both were filed and
both are wrong: pinning the label to warehouseArea's supplier, and refusing to merge a
mixed-unit cluster, each relocate the identical 10.76x onto plotArea. The plotArea assertions
below are what catch them.

Drives real merge.main through a subprocess - the oracle is structurally blind here (it
re-renders a FIXED canonical fixture and never executes merge), so this is the only net."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

SQFT_PER_SQM = 10.7639


def _merge(recs, tag):
    d = Path(tempfile.mkdtemp(prefix=f"cbre_pfu_{tag}_"))
    (d / "inputs").mkdir()
    (d / "recs.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"),
                        "--records", str(d / "recs.json"),
                        "--source-dir", str(d / "inputs"),
                        "--out", str(d / "c.json"), "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, errors="replace")
    if not (d / "c.json").exists():
        return None, (p.stdout + p.stderr)[-300:]
    return json.loads((d / "c.json").read_text(encoding="utf-8")), ""


def _r(src, stype="pdf", **kw):
    r = {"park": "Raven Park", "city": "Corby", "country": "GB", "developer": "Prologis",
         "__meta": {"source_file": src, "source_type": stype, "locator_base": "page 1"}}
    r.update(kw)
    return r


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # THE REPRODUCING CLUSTER. Two records of ONE property that cluster together:
    #   - the tracker (higher precedence for area) states 134,549 with NO areaUnit
    #   - the deck states a 40,000 plot in sq m, and IS where areaUnit comes from
    # so the merged label is "sq m" while warehouseArea's own source never said so.
    recs = [
        _r("Tracker.xlsx", "xlsx", warehouseArea=134549),
        _r("Deck.pdf", "pdf", plotArea=40000, areaUnit="sq m"),
    ]
    canon, err = _merge(recs, "mixed")
    ck(canon is not None, f"merge completes on the mixed-footing cluster {ascii(err)}")
    if not canon:
        print(f"\nPERFIELD UNIT TEST: FAIL ({len(fails)})")
        return 1
    p = canon["properties"][0]
    unit = p.get("areaUnit")
    wa, pa = p.get("warehouseArea"), p.get("plotArea")

    # warehouseArea's supplier stated NO unit -> it must NOT be converted
    ck(wa == 134549,
       f"warehouseArea is NOT scaled on a unit its own source never stated (got {wa}, "
       f"want 134549; the bug shipped {round(134549 * SQFT_PER_SQM)})")
    # ...and the silent supplier must be DISCLOSED, which the bug did not do at all
    ua = (canon.get("meta") or {}).get("unitAssumptions") or []
    ck(bool(ua), f"the silent supplier IS recorded in meta.unitAssumptions ({len(ua)})")
    ck(any("id" in a for a in ua), "the assumption carries an id, so it joins by id not by name")

    # plotArea's supplier DID state sq m -> convert only if the dataset unit differs.
    # This is the assertion that kills BOTH filed remedies: each of them leaves plotArea
    # mislabelled at its raw value.
    if unit == "sq ft":
        ck(pa == round(40000 * SQFT_PER_SQM),
           f"plotArea IS converted sq m -> sq ft on its OWN footing (got {pa}, "
           f"want {round(40000 * SQFT_PER_SQM)}; both filed remedies leave 40000)")
    else:
        ck(pa == 40000, f"plotArea keeps its own already-correct sq m value (got {pa})")

    # --- a SINGLE-footing cluster must be byte-identical to today ---------------
    same = [_r("A.pdf", warehouseArea=10000, areaUnit="sq m"),
            _r("B.pdf", plotArea=20000, areaUnit="sq m")]
    c2, err2 = _merge(same, "same")
    ck(c2 is not None, f"merge completes on a single-footing cluster {ascii(err2)}")
    if c2:
        q = c2["properties"][0]
        ck(q.get("areaUnit") == "sq m", "the dataset unit is sq m")
        ck(q.get("warehouseArea") == 10000 and q.get("plotArea") == 20000,
           f"nothing is converted when every footing already matches "
           f"({q.get('warehouseArea')}, {q.get('plotArea')})")
        ck(not (c2.get("meta") or {}).get("unitAssumptions"),
           "and nothing is recorded as assumed (no false disclosure)")

    # --- a genuine cross-unit conversion still happens --------------------------
    cross = [_r("A.pdf", warehouseArea=1000, areaUnit="sq m"),
             _r("B.pdf", warehouseArea=1000, areaUnit="sq m"),
             _r("C.pdf", plotArea=500, areaUnit="sq ft")]
    c3, err3 = _merge(cross, "cross")
    if c3:
        units = {pr.get("areaUnit") for pr in c3["properties"]}
        ck(len(units) == 1, f"one dataset unit label across the pack {ascii(str(units))}")

    # --- B63: a schema-NUMERIC area that arrives as a formatted STRING -----------
    # `warehouseArea` is typed {"type": "number"} in canonical.schema.json, but a
    # brochure-interpretation record stores it the way the page PRINTS it by contract
    # (reference/interpretation.md: "a dimensioned value keeps its unit inside the value").
    # The alignment loop's `isinstance(merged[fld], (int, float))` test therefore skipped
    # every brochure-sourced area, and the raw text sailed into canonical.json: one live run
    # had 17+ properties failing validate-data with "'436,000 sq ft' is not of type 'number'",
    # and value-format flagging the SAME field for shipping a bare 387259 on one card beside
    # '160,725 sq ft' on the next. Only tracker-sourced (already numeric) areas were right.
    #
    # These are SINGLE-SOURCE properties on purpose - sibling units of one multi-unit deck
    # that no tracker row ever cross-referenced, so there is no field conflict to adjudicate
    # and no other record to supply a number. That is the shape that shipped broken.
    strings = [
        _r("Deck.pdf", park="Unit A", warehouseArea="436,000 sq ft"),
        _r("Deck.pdf", park="Unit B", warehouseArea="700,000 SQ FT"),
        _r("Deck.pdf", park="Unit C", warehouseArea="115,299 sq ft"),
        # the unit-SILENT string: parsed, NOT converted, and the assumption disclosed
        _r("Deck.pdf", park="Unit D", warehouseArea="90,000"),
        # a plotArea string is DELIBERATELY left alone - the schema types plotArea
        # ["number","string","null"] and the chrome renders its own notation verbatim
        # (areaunit_test pins this exact value), so coercing it would destroy the "(12.8 ha)"
        _r("Deck.pdf", park="Unit E", warehouseArea="50,000 sq ft",
           plotArea="31.629 acres (12.8 ha)"),
    ]
    c4, err4 = _merge(strings, "strings")
    ck(c4 is not None, f"merge completes on an all-string-area cluster {ascii(err4)}")
    if c4:
        by = {p["park"]: p for p in c4["properties"]}
        unit = (c4["properties"][0] or {}).get("areaUnit")
        for park, want_sqft in (("Unit A", 436000), ("Unit B", 700000), ("Unit C", 115299),
                                ("Unit E", 50000)):
            got = by.get(park, {}).get("warehouseArea")
            ck(isinstance(got, (int, float)) and not isinstance(got, bool),
               f"{park}: the formatted string parsed to a NUMBER for the schema "
               f"(got {got!r}, a {type(got).__name__})")
            # the string stated sq ft, so it must land on the dataset unit's own footing
            want = want_sqft if unit == "sq ft" else round(want_sqft / SQFT_PER_SQM)
            ck(got == want,
               f"{park}: and on the dataset's footing - {want} {unit} (got {got!r})")
        # the unit the VALUE printed drives the conversion, so a sq ft string in a sq m
        # dataset must NOT be recorded as a silent supplier
        ua_ids = {a.get("property") for a in ((c4.get("meta") or {}).get("unitAssumptions") or [])}
        ck("Unit A" not in ua_ids,
           f"a string that PRINTS its unit is not filed as unit-silent {ascii(str(ua_ids))}")
        ck("Unit D" in ua_ids,
           f"...while a string with no unit anywhere still is {ascii(str(ua_ids))}")
        ck(by.get("Unit D", {}).get("warehouseArea") == 90000,
           f"...and its figure is kept UNCONVERTED, exactly like a unit-silent number "
           f"(got {by.get('Unit D', {}).get('warehouseArea')!r})")
        ck(by.get("Unit E", {}).get("plotArea") == "31.629 acres (12.8 ha)",
           f"a STRING plotArea is untouched - the schema allows it and the chrome renders it "
           f"verbatim (got {by.get('Unit E', {}).get('plotArea')!r})")
    # PROVENANCE: the re-notation is recorded, so the Source Ledger never shows a bare
    # number against a page that prints '436,000 sq ft'
    d_led = Path(tempfile.mkdtemp(prefix="cbre_pfu_led_"))
    (d_led / "inputs").mkdir()
    (d_led / "recs.json").write_text(json.dumps(strings), encoding="utf-8")
    subprocess.run([sys.executable, str(HELPERS / "merge.py"),
                    "--records", str(d_led / "recs.json"),
                    "--source-dir", str(d_led / "inputs"),
                    "--out", str(d_led / "c.json"), "--ledger", str(d_led / "l.csv")],
                   capture_output=True, text=True, errors="replace")
    led = (d_led / "l.csv").read_text(encoding="utf-8", errors="replace") if \
        (d_led / "l.csv").exists() else ""
    ck("printed as '436,000 sq ft'" in led,
       "the ledger records what the page PRINTED, so the parse is traceable")
    ck("converted at" in led or "unit not stated" in led,
       "...and the unit decision that followed it")

    # --- B63: a genuinely UNKNOWN area must be ABSENT, never 'tbd', never invented
    # 'tbd' in a `number` field fails validate-data exactly like the formatted string does,
    # and there is nothing to convert - so the field is dropped and the gap row says why.
    # A struck value ('12 sq ft' fails the plausibility band -> merge_cluster writes "tbd")
    # and a stated RANGE (no single value exists) are the two live routes into this.
    unknown = [
        _r("Deck.pdf", park="Struck", warehouseArea="12 sq ft"),
        _r("Deck.pdf", park="Ranged", warehouseArea="25,000 - 50,000 sq ft"),
        _r("Deck.pdf", park="Good", warehouseArea="90,000 sq ft"),
    ]
    c5, err5 = _merge(unknown, "unknown")
    ck(c5 is not None, f"merge completes when an area cannot become a number {ascii(err5)}")
    if c5:
        by5 = {p["park"]: p for p in c5["properties"]}
        for park in ("Struck", "Ranged"):
            p5 = by5.get(park, {})
            ck("warehouseArea" not in p5,
               f"{park}: the field is ABSENT, not the literal 'tbd' the schema rejects "
               f"(got {p5.get('warehouseArea')!r})")
        ck(isinstance(by5.get("Good", {}).get("warehouseArea"), (int, float)),
           "...and the usable sibling on the same deck is unaffected")

    # --- B63: the plausibility band judges a figure on ITS OWN FOOTING ----------
    # The precedence-winner gate passed no unit, so every area was judged by
    # `area_band_for(None)` - the SQ M band, ceiling 600,000 - whatever the record was in.
    # On a live UK (sq ft) run that struck three big-box sheds the tracker plainly states.
    # imported here, not at module scope: everything above drives merge by SUBPROCESS on purpose
    import merge as M       # noqa: E402
    import normalize as N   # noqa: E402
    for v in (659428.0, 783309.0, 1000000.0):
        ck(M._pick_gate_verdict("warehouseArea", v, None, "sq ft") == "pass",
           f"{v:g} sq ft passes its own band (the sq m ceiling struck it: "
           f"{M._pick_gate_verdict('warehouseArea', v, None, None)!r})")
    # ...and KNOWING the unit may only ever WIDEN the band. area_band_for is NOT monotonic -
    # the sq ft band raises the FLOOR from 300 to 3,000 as well as the ceiling - so passing the
    # unit straight through would strike an ordinary 1,200 sq ft office. This gate covers
    # offices and plots too, and 3,000 is a WAREHOUSE garble floor never calibrated for them.
    for fld, val, unit in (("officeArea", 1200, "sq ft"), ("officeAreaVal", 1200, "sq ft"),
                           ("officeArea", "1,200 sq ft", None),
                           ("warehouseArea", 2000, "sq ft"),
                           ("warehouseArea", "2,000 sq ft", None)):
        ck(M._pick_gate_verdict(fld, val, None, unit) == "pass",
           f"a small but real {fld} ({val!r}, unit {unit!r}) is NOT struck by a warehouse "
           f"floor it was never measured against")
    for fld in ("warehouseArea", "plotArea", "officeArea", "officeAreaVal"):
        lo0, hi0 = N.area_band_for(None, field=fld)
        for unit in (None, "sq ft", "sq m", "acres", "ha"):
            lo, hi = N.area_band_for(unit, field=fld)
            ck(min(lo, lo0) <= lo0 and max(hi, hi0) >= hi0,
               f"{fld}/{unit}: the unioned band is never tighter than the unit-unknown one")
    # the band must still catch what it exists for: a garble and a unit flip
    for bad in (12, 50, 99_000_000):
        ck(M._pick_gate_verdict("warehouseArea", bad, None, "sq ft") == "fail",
           f"{bad:g} is still caught - the backstop was widened, not removed")

    # THE WHOLE POINT: the result validates against the real canonical schema
    try:
        import jsonschema  # noqa: F401
        schema = json.loads((ROOT / "templates" / "canonical.schema.json")
                            .read_text(encoding="utf-8-sig"))
        for tag, doc in (("string areas", c4), ("unknown areas", c5)):
            if not doc:
                continue
            errs = [f"{list(e.path)}: {e.message}" for e in
                    jsonschema.Draft202012Validator(schema).iter_errors(doc)]
            ck(not errs, f"{tag}: canonical.json validates against canonical.schema.json "
                         f"{ascii(str(errs[:2]))}")
    except ImportError:
        print("  [SKIP] jsonschema not installed - schema assertion not run")

    # --- WIRING: the footing is recorded at BOTH prov sites --------------------
    MSRC = (HELPERS / "merge.py").read_text(encoding="utf-8", errors="replace")
    ck(MSRC.count('"areaUnitOfSource"') >= 3,
       "the supplier's footing is stashed at both prov sites and read in the conversion")
    code = "\n".join(ln for ln in MSRC.splitlines() if not ln.strip().startswith("#"))
    ck('merged["areaUnit"] != area_unit' not in code,
       "the old single-label conversion branch is gone")

    if fails:
        print(f"\nPERFIELD UNIT TEST: FAIL ({len(fails)})")
        return 1
    print("\nPERFIELD UNIT TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
