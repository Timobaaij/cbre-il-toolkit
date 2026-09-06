#!/usr/bin/env python3
"""merge_truth_test.py - the merge must not contradict itself about what it knows.

Six mechanisms, all of them cases where the pack made two incompatible statements about one
datum, or made none where it held the evidence for one:

  A9   AN OVERRIDE IS NOT A PARSE. The plausibility band struck a field regardless of whether a
       human had already reviewed that exact value, so one run could report a correction as
       APPLIED and, of the same field, that no source provides it. A band exists to catch a
       parse; a reviewed conclusion is exempt, and the exemption is DISCLOSED rather than merely
       silent. Nothing else is exempt: the identical value, unlocked, is still struck.
  A10  A COUNT FIELD PREFERS A COUNT. Source rank alone let a prose sentence outrank a clean
       numeric sibling in the SAME cluster, and when that prose then failed the band the field
       shipped tbd with the answer sitting in the pack. The band is now a tiebreak that runs
       before source rank for `_COUNT_GATE_FIELDS` and only for those, with the rejected
       candidate recorded as a discard.
  A9/  meta.struck - the ORIGINAL figure behind every strike, so the honesty report can print
  meta what was withdrawn beside the note explaining why, instead of asking a reader to
       reconstruct it from work/extract.
  A14a meta.clusterSources - which sources built each property, and the postcode each of them
       stated. This is what lets the over-merge gate ask "do these two records disagree about
       where the building is" as a pure function of canonical.json, with no matcher import and
       no re-clustering (a gate that re-derives clustering to check clustering can only agree
       with itself).
  A15  A FUSION MUST DISCLOSE ITSELF. When a matcher wrongly fused two buildings, two
       independent reviewers each found it by reading provenance line by line and the pack said
       nothing, because every row was individually correct. Containment is now stated once, out
       loud - and its exclusions are pinned here too, because a disclosure that fires on every
       property is noise that takes the real one with it.
  A18b AN OVERRIDE MAY CITE ITS OWN EVIDENCE. The ledger row stamped `where.source_file`, which
       is the TARGETING clause, so a value read off a document page and corrected through the
       spreadsheet row that carries it was attributed to the spreadsheet.
  A20  THE MEDIA PREWARM COMPLETES IN ONE PASS, and its `total` may not overstate what it
       looked at. Two phases ran exactly once, so a corpus that missed the single pass reported
       partial and cost another shell round-trip; and a hard-coded 80-page cap meant `total`
       could be smaller than the real document, licensing a "complete" message for pages that
       were never enumerated. The wall-clock deadline is unchanged and still bounds everything.

Offline. The prewarm section needs fitz (it builds throwaway PDFs) and SKIPS without it.
Run: python evals/merge_truth_test.py"""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import images as IMG    # noqa: E402
import ledger as LG     # noqa: E402
import merge as M       # noqa: E402

FAILS: list[str] = []


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def call(module, *cmd) -> tuple[int, str]:
    """Run a helper's main() in-process (the overrides_test idiom), capturing its stdout."""
    saved = sys.argv
    sys.argv = [getattr(module, "__name__", "h"), *[str(c) for c in cmd]]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            module.main()
        return 0, buf.getvalue()
    except SystemExit as e:
        return (e.code if isinstance(e.code, int) else 0), buf.getvalue()
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}\n{buf.getvalue()}"
    finally:
        sys.argv = saved


def build(td: Path, records: list, overrides: list | None = None, name="records.json"):
    """Run the REAL merge over `records` (+ optional overrides).

    -> (rc, stdout, canonical path, ledger path). The overrides_test idiom, unchanged."""
    rf = td / name
    rf.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    src = td / "inputs"
    src.mkdir(exist_ok=True)
    canon, led = td / "canonical.json", td / "source_ledger.csv"
    args = ["--records", rf, "--source-dir", src, "--out", canon, "--ledger", led]
    if overrides is not None:
        of = td / "overrides.json"
        of.write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")
        args += ["--overrides", of]
    rc, out = call(M, *args)
    return rc, out, canon, led


def rec(source_file: str, source_type: str, base: str, **fields) -> dict:
    """One record for ONE property (every record here clusters with every other: same park, city,
    country, developer). `base` is its locator; every field passed gets a prov entry pointing at
    it, which is what makes the ledger locators and meta.struck locators predictable below.

    DELIBERATELY NOT `tracker_rich`: that flag routes the count and spec fields through
    TRACKER_AUTHORITATIVE, which would decide the A10 contest on its own and prove nothing about
    the band tiebreak. Without it every field takes plain spec precedence - pdf over xlsx - so
    the prose-bearing brochure genuinely outranks the numeric tracker."""
    r = {"park": "Alpha Park", "city": "Swindon", "country": "United Kingdom",
         "developer": "GLP", "status": "Existing",
         "__meta": {"source_file": source_file, "source_type": source_type,
                    "locator_base": base, "prov": {"park": base, "city": base}}}
    if source_type == "pdf":
        r["__meta"]["page_no"] = 1
    r.update(fields)
    for k in fields:
        r["__meta"]["prov"][k] = base
    return r


def bare(park: str, **fields) -> dict:
    """A record with NO locator_base and NO prov map at all - an email-shaped source. Its point
    is the empty-string case: meta.struck's `locator` must then be "", not a fabricated one."""
    r = {"park": park, "city": "Corby", "country": "United Kingdom", "developer": "GLP",
         "status": "Existing", "__meta": {"source_file": "agent.msg", "source_type": "msg"}}
    r.update(fields)
    return r


def prop(canon: Path, park="Alpha Park") -> dict:
    d = json.loads(canon.read_text(encoding="utf-8"))
    return next((p for p in d["properties"] if p.get("park") == park), {})


def meta_of(canon: Path) -> dict:
    return json.loads(canon.read_text(encoding="utf-8")).get("meta") or {}


def ledger_rows(led: Path) -> list[dict]:
    with open(led, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- #
# A9 - an override-locked field is exempt from the band; an unlocked one is not
# --------------------------------------------------------------------------- #
def a9() -> None:
    print("\nA9 - a REVIEWED correction is not a parse, so the band must not strike it:")
    ov = {"id": "ov-ch", "where": {"source_file": "tracker.xlsx", "sheet": "Longlist", "row": 2},
          "set": {"clearHeight": "45 m"},
          "why": "the signed spec sheet states a 45 m stacked crane bay"}
    ck(M._pick_gate_verdict("clearHeight", "45 m") == "fail",
       "the test value really does FAIL the band (otherwise this whole section proves nothing)")

    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, [rec("tracker.xlsx", "xlsx", "Longlist!r2",
                                             clearHeight="12 m")], [ov])
        p, mt = prop(canon), meta_of(canon)
        ck(rc == 0, "merge completes with the override applied")
        ck(p.get("clearHeight") == "45 m",
           f"the OVERRIDE-LOCKED out-of-band value SHIPS (got {p.get('clearHeight')!r}) - it was "
           f"struck to tbd before A9, so the pack asserted the field was absent from every "
           f"source AND that an override had set it")
        ck(not mt.get("struck"),
           f"...and it is NOT recorded as struck, because it was not struck "
           f"(got {mt.get('struck')})")
        line = next((c for c in (mt.get("conflicts") or []) if "clearHeight" in c), "")
        ck("band was NOT applied" in line and "reviewed correction" in line,
           "the exemption is DISCLOSED, not silent: the note says the band was not applied and why")
        ck("ov-ch" in line, "and it names the override, so a reader can go back to the entry")
        ck(line.startswith("id 1 clearHeight: "),
           f"in the load-bearing `id N field:` prefix format (got {line[:24]!r})")

    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        # THE CONTROL, and the reason A9 is narrow: the SAME failing value, with no override
        # behind it, is still struck. An exemption that leaked to unlocked values would disarm
        # the band that catches a garbled parse.
        rc, out, canon, led = build(td, [rec("tracker.xlsx", "xlsx", "Longlist!r2",
                                             clearHeight="45 m")])
        p, mt = prop(canon), meta_of(canon)
        ck(p.get("clearHeight") == "tbd",
           f"the SAME value UNLOCKED is still struck to tbd (got {p.get('clearHeight')!r})")
        line = next((c for c in (mt.get("conflicts") or []) if "clearHeight" in c), "")
        ck("falls outside the clearHeight plausibility band" in line,
           "and still carries the T1 strike note (names the parse, never accuses the source)")
        ck(len(mt.get("struck") or []) == 1, "and IS recorded in meta.struck")


# --------------------------------------------------------------------------- #
# A10 - in a count field, a candidate the band accepts beats source rank
# --------------------------------------------------------------------------- #
def a10() -> None:
    print("\nA10 - a count field prefers a plausible count over the higher-ranked source:")
    PROSE = "dock and level access loading available"
    ck("loadingDocks" in M._COUNT_GATE_FIELDS and "clearHeight" not in M._COUNT_GATE_FIELDS,
       "the vocabulary is the EXISTING _COUNT_GATE_FIELDS, and clearHeight is outside it "
       "(so the two halves below are a genuine contrast, not two spellings of one rule)")
    ck(M._pick_gate_verdict("loadingDocks", PROSE) == "fail"
       and M._pick_gate_verdict("loadingDocks", 12) == "pass",
       "the prose FAILS the count band and the numeric sibling passes it")

    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        # ONE cluster, TWO records, and the prose sits on the HIGHER-ranked source (pdf beats
        # xlsx for a spec field). Both fields are shaped identically; only membership of
        # _COUNT_GATE_FIELDS differs, so the outcomes below isolate the tiebreak exactly.
        rc, out, canon, led = build(td, [
            rec("brochure.pdf", "pdf", "page 2", loadingDocks=PROSE, clearHeight="400 m"),
            rec("tracker.xlsx", "xlsx", "Longlist!r2", loadingDocks=12, clearHeight="12 m")])
        d = json.loads(canon.read_text(encoding="utf-8"))
        p, mt = prop(canon), meta_of(canon)
        ck(rc == 0 and len(d["properties"]) == 1,
           f"the two records merged into ONE property ({len(d['properties'])})")
        ck(str(p.get("loadingDocks")) == "12",
           f"the NUMERIC count wins the count field (got {p.get('loadingDocks')!r}) even though "
           f"the prose came from the higher-ranked brochure")
        ck(p.get("loadingDocks") != "tbd",
           "so the field is not struck either - the answer was in the pack all along")
        note = next((c for c in mt["conflicts"] if "loadingDocks" in c), "")
        ck(PROSE in note and "brochure.pdf" in note,
           "the rejected candidate is recorded as a DISCARD, naming the value and its file")
        ck("preferred over source precedence" in note and "no plausible loadingDocks count" in note,
           "and the note says the BAND is why it lost, not source rank - a bare 'discarded X "
           "(kept Y)' would read as an ordinary precedence loss")
        ck(note.startswith("id 1 loadingDocks: "), "in the `id N field:` prefix format")
        # the field OUTSIDE the count set: identical shape, untouched behaviour. The failing
        # top-ranked value still wins precedence and is still struck - which is also the proof
        # that source rank alone WOULD have shipped the prose above.
        ck(p.get("clearHeight") == "tbd",
           f"a field OUTSIDE _COUNT_GATE_FIELDS is unaffected: the failing brochure value still "
           f"wins and is still struck (got {p.get('clearHeight')!r})")
        ck([s["value"] for s in (mt.get("struck") or [])] == ["400 m"],
           "and it is the ONLY strike in the run (the count field was resolved, not struck)")


# --------------------------------------------------------------------------- #
# meta.struck - the frozen contract, field for field
# --------------------------------------------------------------------------- #
def struck_contract() -> None:
    print("\nmeta.struck - the frozen shape, including the ORIGINAL value:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, [
            rec("brochure.pdf", "pdf", "page 7", clearHeight="400 m"),
            bare("Beta Park", clearHeight="45 m")])
        d = json.loads(canon.read_text(encoding="utf-8"))
        mt = meta_of(canon)
        st = mt.get("struck") or []
        ck(len(d["properties"]) == 2 and len(st) == 2,
           f"two properties, one strike each ({len(d['properties'])} props, {len(st)} entries)")
        by_field = {(e.get("id"), e.get("field")): e for e in st}
        want = {
            (1, "clearHeight"): {"id": 1, "field": "clearHeight", "value": "400 m",
                                 "source_file": "brochure.pdf", "locator": "page 7"},
            (2, "clearHeight"): {"id": 2, "field": "clearHeight", "value": "45 m",
                                 "source_file": "agent.msg", "locator": ""},
        }
        for key, exp in want.items():
            got = by_field.get(key)
            ck(got == exp, f"struck entry {key} matches the contract EXACTLY: {exp} (got {got})")
        ck(all(isinstance(e.get("id"), int) and not isinstance(e.get("id"), bool) for e in st),
           "`id` is an INT matching the property id (the properties key on an int id)")
        ck(all(sorted(e) == ["field", "id", "locator", "source_file", "value"] for e in st),
           "exactly the five contract keys, no extras: a consumer written against this shape "
           "must not have to guess which ones are optional")
        ck(all(isinstance(e["value"], str) and e["value"] for e in st),
           "the ORIGINAL figure is carried, as the source printed it - the whole point of the "
           "artefact is that the struck value is otherwise only in work/extract")
        # meta.conflicts must NOT be reshaped by any of this: four separate consumers parse the
        # `id N field: ` prefix out of a FLAT list of strings.
        ck(isinstance(mt.get("conflicts"), list)
           and all(isinstance(c, str) for c in mt["conflicts"]),
           "meta.conflicts is still a FLAT LIST OF STRINGS beside it, not reshaped")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, [rec("tracker.xlsx", "xlsx", "Longlist!r2",
                                             clearHeight="12 m")])
        ck("struck" not in meta_of(canon),
           "a run that strikes nothing omits the key entirely (conditional, like meta.offspec) - "
           "so an unaffected run stays byte-identical")


# --------------------------------------------------------------------------- #
# A14a - meta.clusterSources, the frozen contract
# --------------------------------------------------------------------------- #
def cluster_sources() -> None:
    print("\nA14a - meta.clusterSources: which sources built each property, and their "
          "postcodes:")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, [
            rec("brochure.pdf", "pdf", "page 2", postcode="  qx41 7zp "),
            rec("tracker.xlsx", "xlsx", "Longlist!r2"),
            bare("Beta Park", postcode="TBD")])
        d = json.loads(canon.read_text(encoding="utf-8"))
        cs = meta_of(canon).get("clusterSources")
        ck(isinstance(cs, dict), f"meta.clusterSources is present and is an object ({type(cs)})")
        ck(sorted(cs or {}) == ["1", "2"],
           f"keyed by property id AS A STRING, matching the other per-property projections "
           f"(JSON object keys are strings, and a round-trip must not change them): "
           f"{sorted(cs or {})}")
        ck(all(isinstance(p.get("id"), int) for p in d["properties"])
           and {str(p["id"]) for p in d["properties"]} == set(cs or {}),
           "and every property has exactly one entry - no id is missing and none is invented")
        one = sorted(cs["1"], key=lambda e: e["file"])
        ck(one == [{"file": "brochure.pdf", "postcode": "QX417ZP"},
                   {"file": "tracker.xlsx", "postcode": ""}],
           f"one entry per contributing record, {{file, postcode}}, file as a BASENAME: {one}")
        # NORMALISED BY THE MATCHER'S OWN READER, and this assertion used to say the opposite.
        # It pinned "trimming and upper-casing, and by nothing else", on the reasoning that any
        # re-spacing "could fuse two genuinely different codes". THAT REASONING IS BACKWARDS,
        # and pinning it is what kept a third private copy of the normaliser alive in merge: a
        # code printed with an internal space and the same code printed without one are ONE
        # code in every national format, which is exactly why `match._stated_postcode` REMOVES
        # whitespace instead of trimming it. Leaving it in made the PRODUCER of these values
        # disagree with the veto that consumes them, so the over-merge gate blocked fusions the
        # veto had deliberately allowed, and named a remedy that would have unfused a correct
        # merge. Measured before the fix: 12 of 20 single-value probes normalised differently
        # from the shared reader, and 4 pairs reached a different end-to-end verdict.
        ck(cs["1"][0]["postcode"] != "  qx41 7zp "
           and "QX417ZP" in [e["postcode"] for e in one],
           "the postcode is normalised for EQUALITY: whitespace removed and the remainder "
           "upper-cased, so a code printed with an internal space and the same code printed "
           "without one compare equal - which is the comparison the over-merge gate makes")
        # AND IT IS THE SAME FUNCTION OBJECT, not merely the same answer today. A private copy
        # that happened to agree on the cases this file exercises is how the drift lasted, so
        # the delegation is pinned by identity: reintroducing a copy fails here immediately.
        import inspect
        import match as _MM
        _probe = ["  qx41 7zp ", "QX41 7ZP", "482 15", 48215, 48215.0, 1234.5,
                  True, False, "tbd", "n/a", "", "-", float("nan"), float("inf")]
        _same = all(M._stated_postcode({"postcode": v}) == _MM._stated_postcode({"postcode": v})
                    for v in _probe)
        ck(_same and "match._stated_postcode" in inspect.getsource(M._stated_postcode),
           f"merge DELEGATES to match._stated_postcode rather than normalising itself, proved "
           f"both ways: the same answer on all {len(_probe)} probe values AND the call is in "
           f"its body, so a reintroduced private copy fails here even if it agrees today")
        ck(M._stated_postcode({"postalCode": "qx41 7zp"}) == "QX417ZP",
           "...which also shares the FIELD LIST, so a record stating its code under the other "
           "spelling in match._POSTCODE_FIELDS is read here too, not silently dropped")
        ck([e["postcode"] for e in one if e["file"] == "tracker.xlsx"] == [""],
           "a record that states NO postcode carries the empty string, never a missing key")
        ck(cs["2"] == [{"file": "agent.msg", "postcode": ""}],
           f"an UNKNOWN-VALUE SENTINEL is the empty string too (got {cs['2']}) - two properties "
           f"both saying 'tbd' must never read as two properties agreeing on a postcode")
        ck(all(sorted(e) == ["file", "postcode"] for v in cs.values() for e in v),
           "exactly the two contract keys per entry")
        ck(M._stated_postcode({}) == "" and M._stated_postcode({"postcode": None}) == "",
           "an absent postcode is the empty string (a corpus need not have the field at all)")


# --------------------------------------------------------------------------- #
# A15 - the fusion disclosure, and every exclusion behind it
# --------------------------------------------------------------------------- #
def fusion() -> None:
    print("\nA15 - a fusion discloses itself, and NOTHING legitimate does:")
    cl = [rec("brochure.pdf", "pdf", "page 2"), rec("tracker.xlsx", "xlsx", "Longlist!r2")]
    # One prov map carrying every case at once, so an exclusion cannot pass by accident: the
    # positives and the negatives are decided in the same call.
    prov = {
        # GENUINELY FOREIGN: a spec field citing a file that contributed no record here
        "clearHeight": {"source_file": "other-building.pdf", "locator": "page 9"},
        # media + prose slots: legitimately foreign by design (park-level pages, photo-match)
        "photo": {"source_file": "park-shots.pdf", "locator": "page 1"},
        "plan": {"source_file": "park-shots.pdf", "locator": "page 4"},
        "gallery": {"source_file": "park-shots.pdf", "locator": "deck photos"},
        "description": {"source_file": "matched-brochure.pdf", "locator": "page 1"},
        # a DERIVED companion: its prov is COPIED from its basis, so it names the basis's file
        "warehouseRent": {"source_file": "tracker.xlsx",
                          "locator": "Longlist!r2 (derived from warehouseRentVal)"},
        # a GAP row attributes nothing; an enrichment/pipeline-assigned value has no prov at all,
        # which this models as the empty source_file a defensive caller might leave behind
        "region": {"source_file": "(none)", "locator": "no source"},
        "landlord": {"source_file": "", "locator": ""},
        # the SAME file by a work-dir path and in another case: not foreign, and a path must
        # never be what decides whether a card looks fused
        "epc": {"source_file": "work/inputs/BROCHURE.PDF", "locator": "page 4"},
    }
    got = M._fusion_disclosures(cl, prov)
    ck(got == [("clearHeight", "other-building.pdf")],
       f"exactly ONE disclosure, for the genuinely foreign file only: {got}")
    for fld in ("photo", "plan", "gallery", "description"):
        ck(fld not in [f for f, _ in got],
           f"{fld} is EXEMPT: the media/prose slots reach park-level and photo-matched decks by "
           f"design, and have their own audit trail and gate")
    ck("warehouseRent" not in [f for f, _ in got],
       "a DERIVED field never fires: it copies its basis field's prov, so it names an in-cluster "
       "file whenever the basis does")
    ck("region" not in [f for f, _ in got] and "landlord" not in [f for f, _ in got],
       "a gap/enrichment-shaped prov with no file to name never fires")
    ck("epc" not in [f for f, _ in got],
       "matched on BASENAME, case-insensitively - the same rule the override and repair channels "
       "apply to a cited file")
    ck(M._fusion_disclosures([], prov) and M._fusion_disclosures(cl, {}) == [],
       "an empty prov discloses nothing; an empty cluster discloses everything it can name "
       "(no crash either way)")

    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, out, canon, led = build(td, cl)
        conf = meta_of(canon).get("conflicts") or []
        ck(not any("contributed no record" in c for c in conf),
           "and an ORDINARY merge emits NONE of these: every prov entry merge_cluster writes "
           "comes from a record of the cluster it was handed, so this is a containment invariant "
           "and cannot cry wolf")
        ck(all(c.startswith("id ") and ": " in c for c in conf),
           f"every meta.conflicts line still opens `id N field: ` ({conf[:1]})")


# --------------------------------------------------------------------------- #
# A18b - an override may cite the evidence a human actually read
# --------------------------------------------------------------------------- #
def a18b() -> None:
    print("\nA18b - the override ledger row cites EVIDENCE, not the targeting clause:")
    base = {"id": "ov-city",
            "where": {"source_file": "tracker.xlsx", "sheet": "Longlist", "row": 2},
            "set": {"city": "Corby"}, "why": "the county sat in the city column"}
    recs = [rec("tracker.xlsx", "xlsx", "Longlist!r2")]

    def orow(td, entry):
        rc, out, canon, led = build(td, recs, [entry])
        rows = [r for r in ledger_rows(led) if r.get("record_type") == "override"]
        return rc, (rows[0] if rows else {}), canon, led

    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        rc, plain, canon, led = orow(td, dict(base))
        ck(rc == 0 and plain.get("source_file") == "tracker.xlsx",
           f"WITHOUT a citation the row is byte-identical to today: source_file is still the "
           f"`where` file (got {plain.get('source_file')!r})")
        ck("ov-city" in plain.get("source_locator", "")
           and "Corby" in plain.get("source_locator", "")
           and "county sat in the city column" in plain.get("source_locator", ""),
           "...and source_locator still carries the id, the old -> new and the WHY")
        applied = ((meta_of(canon).get("overrides") or {}).get("applied") or [{}])[0]
        ck("source_file" not in applied and "source_locator" not in applied,
           "and the citation keys are ABSENT from the applied report, so an uncited run's "
           "canonical + overrides_report bytes are unchanged")
        ck(call(LG, "validate", led)[0] == 0, "`ledger.py validate` ALL-PASS (uncited)")

    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        cited = dict(base, source_file="certificate.pdf",
                     source_locator="page 3 (the signed EPC certificate)")
        rc, row, canon, led = orow(td, cited)
        ck(rc == 0 and row.get("source_file") == "certificate.pdf",
           f"WITH a citation the row names the file the human READ, not tracker.xlsx (got "
           f"{row.get('source_file')!r}) - a value read off a document page and corrected through "
           f"a spreadsheet row was previously attributed to the spreadsheet")
        ck(row.get("source_locator") == "page 3 (the signed EPC certificate)",
           f"and the cited locator wins verbatim (got {row.get('source_locator')!r})")
        ck("county sat in the city column" in row.get("conflict_note", "")
           and "ov-city" in row.get("conflict_note", ""),
           "the was/now/why audit trail is NOT lost - it moves to conflict_note, which is the "
           "honest split: source_locator says where the value IS, the note says what changed")
        ck(row.get("record_type") == "override" and row.get("source_type") == "override"
           and row.get("confidence") == "manual",
           "every other column of the row is untouched")
        ck(call(LG, "validate", led)[0] == 0, "`ledger.py validate` ALL-PASS (cited)")
        applied = ((meta_of(canon).get("overrides") or {}).get("applied") or [{}])[0]
        ck(applied.get("source_file") == "certificate.pdf"
           and applied.get("source_locator") == "page 3 (the signed EPC certificate)",
           "the citation also rides canonical.meta.overrides, which is what the Gaps Report reads")
        ck(prop(canon, "Alpha Park").get("city") == "Corby",
           "and the correction itself still applies (a citation is provenance, never a predicate)")

    # the two keys are OPTIONAL, but present-and-empty is not a citation: they REPLACE a ledger
    # column, and an empty ledger cell hard-blocks the build. Same guard, same wording, as the
    # repair channel's A18a.
    with tempfile.TemporaryDirectory() as t:
        of = Path(t) / "overrides.json"
        of.write_text(json.dumps([dict(base, source_locator="   ")]), encoding="utf-8")
        loaded, errs = M.load_overrides(of)
        ck(not loaded and any("hard-blocks the build" in e for e in errs),
           f"an EMPTY citation is refused with a reason, never carried through: {errs}")
        of.write_text(json.dumps([dict(base, source_file="cert.pdf")]), encoding="utf-8")
        loaded, errs = M.load_overrides(of)
        ck(len(loaded) == 1 and not errs and loaded[0]["source_file"] == "cert.pdf"
           and loaded[0]["source_locator"] == "",
           "one key without the other is fine - each replaces its own column independently")
        of.write_text(json.dumps([{k: v for k, v in base.items() if k != "why"}]),
                      encoding="utf-8")
        loaded, errs = M.load_overrides(of)
        ck(not loaded and any("\"why\" is required" in e for e in errs),
           "`why` stays REQUIRED: a citation says where the value is, never why the old one "
           "was wrong")


# --------------------------------------------------------------------------- #
# A20 - the prewarm completes in one pass and cannot overstate what it saw
# --------------------------------------------------------------------------- #
def _text_deck(path: Path, pages: int) -> None:
    """A text-only PDF: this section fakes the unit worker, so no page is ever rasterised and
    the deck exists only to be a real document with a real page COUNT."""
    import fitz
    doc = fitz.open()
    for p in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((60, 70), f"Unit {p + 1}", fontsize=12)
    doc.save(str(path))
    doc.close()


def a20() -> None:
    print("\nA20 - the media prewarm converges in ONE call, and `total` tells the truth:")
    src = (HELPERS / "merge.py").read_text(encoding="utf-8")
    ck(M.PREWARM_MAX_DECK_PAGES == 80,
       f"the per-deck page cap is a NAMED module constant (= {M.PREWARM_MAX_DECK_PAGES}), not a "
       f"literal buried twice inside the enumeration")
    ck("page_count, 80" not in src and "slides), 80" not in src,
       "and no bare `80` cap survives in the enumeration")
    ck("deadline = time.monotonic() + max(1.0, seconds)" in src,
       "the wall-clock deadline is still computed ONCE for the whole call - the rounds converge "
       "inside the budget, they never extend it")
    ck("cancel_futures=True" in src and "wait=False" in src,
       "and the pool is still never JOINED (the measured 2.0s-budget-took-12.2s incident)")

    try:
        import fitz  # noqa: F401
    except Exception as e:
        print(f"  [SKIP] A20 runtime half: needs fitz ({e})")
        return

    # THE UNIT WORKER IS FAKED, deliberately, and modelled on the incident the real one records:
    # a `slidehero`/`hero` unit shells out to a converter that several workers race on, so the
    # first attempt can fail while a SIBLING unit banks the artefact it needed - and a retry then
    # succeeds. That is a corpus which makes progress in a round yet is not finished by it, i.e.
    # exactly the one that used to come back partial and cost the operator another whole pass.
    # Faking it also means no page is ever rasterised, so this section is fast and deterministic.
    real = (IMG._unit_cached, IMG._prewarm_unit, IMG._placed_layout)
    cap = M.PREWARM_MAX_DECK_PAGES
    banked: set = set()
    attempts: dict = {}
    delay = [0.0]
    needs = {}                # unit kind -> attempts it takes to bank (default 1)

    def fake_cached(u):
        return tuple(u) in banked

    def fake_prewarm(u):
        k = tuple(u)
        attempts[k] = attempts.get(k, 0) + 1
        if delay[0]:
            time.sleep(delay[0])
        if attempts[k] >= needs.get(u[0], 1):
            banked.add(k)

    def reset(retry_kinds=("hero",), tries=2, per_unit_delay=0.0):
        banked.clear()
        attempts.clear()
        needs.clear()
        needs.update({k: tries for k in retry_kinds})
        delay[0] = per_unit_delay

    # workers=1 throughout: the serial branch keeps this deterministic AND keeps the fakes
    # effective (a process pool's children re-import images and would never see them).
    IMG._unit_cached, IMG._prewarm_unit = fake_cached, fake_prewarm
    IMG._placed_layout = lambda *a, **k: None
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
            td = Path(t)
            inp = td / "inputs"
            inp.mkdir()
            _text_deck(inp / "Deck.pdf", 3)
            recs = [{"__meta": {"source_file": "Deck.pdf", "source_type": "pdf", "page_no": 0}}]

            # THE CONVERGENCE, as a controlled before/after: `max_rounds=1` reproduces the old
            # single-pass behaviour through the new knob, the default runs the change.
            reset()
            d1, t1 = M.prewarm_images(recs, inp, td / "c1", 110, seconds=30.0, workers=1,
                                      max_rounds=1)
            ck(t1 > 0 and d1 == t1 - 1,
               f"with ONE round (the behaviour before A20) the corpus comes back PARTIAL "
               f"({d1}/{t1}), one unit short, and needs a whole second pass to finish it")
            reset()
            d2, t2 = M.prewarm_images(recs, inp, td / "c2", 110, seconds=30.0, workers=1)
            ck(t2 == t1 and d2 == t2,
               f"the SAME corpus now converges in ONE call ({d2}/{t2}) - the two phases repeat "
               f"until done == total or a round banks nothing")
            ck(max(attempts.values()) == 2,
               f"and it converged by RETRYING the unfinished unit inside the one call, not by "
               f"counting differently (max attempts {max(attempts.values())})")

            # a PERMANENTLY failing unit must not spin, whatever max_rounds says: the round that
            # banks nothing new ends the loop, so the retry is bounded by progress, not by the cap
            reset(tries=99)
            t0 = time.perf_counter()
            d3, t3 = M.prewarm_images(recs, inp, td / "c3", 110, seconds=30.0, workers=1,
                                      max_rounds=10_000)
            dt3 = time.perf_counter() - t0
            ck(d3 == t3 - 1 and dt3 < 10.0,
               f"a permanently failing unit leaves the rest warm and stops on NO PROGRESS rather "
               f"than spinning ({d3}/{t3} in {dt3:.2f}s with max_rounds=10,000)")
            ck(max(attempts.values()) == 2,
               f"it was attempted exactly twice and then abandoned (max attempts "
               f"{max(attempts.values())})")

            # a corpus where NOTHING banks stops on the very first round, for the same reason
            reset(retry_kinds=("hero", "gidxpage", "placedpage"), tries=99)
            d3b, t3b = M.prewarm_images(recs, inp, td / "c3b", 110, seconds=30.0, workers=1,
                                        max_rounds=10_000)
            ck(d3b == 0 and max(attempts.values()) == 1,
               f"a corpus where NOTHING succeeds costs exactly one attempt per unit ({d3b}/{t3b})")

            # THE DEADLINE IS STILL THE SAFETY VALVE. Units bank fine but each costs real time,
            # the budget cannot cover them all, and max_rounds is enormous: what bounds the call
            # is the wall clock, exactly as before.
            # Each unit banks first time but costs 0.25s, so the 1.0s budget cannot cover all
            # seven however many rounds are allowed.
            reset(retry_kinds=(), per_unit_delay=0.25)
            t0 = time.perf_counter()
            d4, t4 = M.prewarm_images(recs, inp, td / "c4", 110, seconds=1.0, workers=1,
                                      max_rounds=10_000)
            dt4 = time.perf_counter() - t0
            ck(dt4 < 8.0,
               f"a pathological corpus is still bounded by the WALL CLOCK ({dt4:.2f}s on a 1.0s "
               f"budget with max_rounds=10,000), not by the round cap")
            ck(0 < d4 < t4,
               f"the budget really did cut it short ({d4}/{t4}) - so the bound is exercised here, "
               f"not merely asserted, and a spent budget reports partial instead of looping")

            # THE CAP AND THE HONEST TOTAL. A deck longer than the cap has pages this prewarm
            # deliberately never enumerates; `total` counts them anyway, so `done == total` can
            # never license a "complete" message for pages nobody looked at.
            _text_deck(inp / "Long.pdf", 5)
            long_recs = [{"__meta": {"source_file": "Long.pdf", "source_type": "pdf",
                                     "page_no": 0}}]
            M.PREWARM_MAX_DECK_PAGES = 3
            reset(retry_kinds=())
            d5, t5 = M.prewarm_images(long_recs, inp, td / "c5", 110, seconds=30.0, workers=1)
            # 3 enumerated pages x (gidxpage + placedpage) + 1 hero = 7 units warmed;
            # total also counts the 2 pages past the cap x 2 unit kinds = 11.
            ck(d5 == 7 and t5 == 11,
               f"`total` reflects the REAL page count ({d5}/{t5} for a 5-page deck capped at 3), "
               f"so the figure cannot overstate completeness")
            ck(d5 < t5,
               "a deck longer than the cap can therefore never report as complete - the old "
               "total described only what this function chose to look at")
            M.PREWARM_MAX_DECK_PAGES = cap
            reset(retry_kinds=())
            d6, t6 = M.prewarm_images(long_recs, inp, td / "c6", 110, seconds=30.0, workers=1)
            ck(d6 == t6 == 11,
               f"and under the real cap the same deck enumerates every page and completes "
               f"({d6}/{t6})")
            ck(M.prewarm_images(recs, inp, None, 110)[1] == 0,
               "no cache dir -> a clean (0, 0) no-op, never a crash (unchanged)")
    finally:
        IMG._unit_cached, IMG._prewarm_unit, IMG._placed_layout = real
        M.PREWARM_MAX_DECK_PAGES = cap


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    a9()
    a10()
    struck_contract()
    cluster_sources()
    fusion()
    a18b()
    a20()
    print(f"\n{'OK' if not FAILS else 'FAIL'} merge_truth_test: {len(FAILS)} failure(s)")
    for f in FAILS:
        print(f"  - {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
