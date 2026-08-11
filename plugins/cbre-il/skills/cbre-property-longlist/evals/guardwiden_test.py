#!/usr/bin/env python3
"""guardwiden_test.py - the guards must be WIDER than the set of legitimate LLM answers (2026-07-30).

The skill is LLM-driven by design: inputs, clients, countries and languages differ every run, so
judgement belongs to the model and Python's job is to verify and bind. A guard that is NARROWER
than the answers a model legitimately gives is therefore not "strict" - it is a LIVELOCK, because
the request is simply re-emitted until the model disobeys its own instructions. Four such guards
were found by transcribing them and executing them against realistic answers.

Locks:
  * `_vkey` folds SEPARATORS (space/_/-/.) so a sub-agent's sanitised filename matches its region,
    while KEEPING non-ASCII letters (a blunt [^a-z0-9] strip would silently turn 'Łódź' into 'odz')
  * a tracker decline is honoured in BOTH .SKIP spellings (the manifest wording produced one and
    the code read only the other)
  * a tracker map with NO echoed input_hash is ACCEPTED (the consumer documents that it takes a
    bare map; requiring the echo rejected a map the parser would happily use)
  * `_index_decisions` accepts the flat map, a wrapper-list and a bare list
  * an area with NO unit is recorded as an ASSUMPTION and surfaced in the Gaps Report - never
    silently stamped with the dataset's dominant unit (a 10.76x error), and never GUESSED by Python

Offline. Run: python evals/guardwiden_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import deliver as DEL  # noqa: E402
import run as RUN  # noqa: E402
import vision_validate as VV  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---------------- _vkey: fold separators, keep letters ----------------
    print("_vkey folds SEPARATORS (a sanitised filename still matches its region)")
    for a, b in [("East Midlands", "East_Midlands"), ("East Midlands", "east-midlands"),
                 ("Castilla La Mancha", "Castilla_La_Mancha"), ("Ile-de-France", "Ile de France"),
                 ("Nordrhein-Westfalen", "nordrhein_westfalen")]:
        ck(RUN._vkey(a) == RUN._vkey(b) == VV._vkey(a) == VV._vkey(b),
           f"{a!r} == {b!r} in BOTH copies -> {RUN._vkey(a)!r}")
    ck(RUN._vkey("Łódź") == "łodz",
       f"a non-ASCII letter is KEPT, not deleted ({RUN._vkey('Łódź')!r}, not 'odz')")
    for a, b in [("East Midlands", "West Midlands"), ("Venlo", "Vento")]:
        ck(RUN._vkey(a) != RUN._vkey(b), f"{a!r} still differs from {b!r} (no over-folding)")

    # ---------------- decisions files: shape tolerance ----------------
    print("\n_index_decisions accepts every legitimate shape, rejects junk")
    flat = {"p1": {"verdict": "same"}, "p2": "different"}
    ck(RUN._index_decisions(flat, ("pair_id",)) == flat, "the documented flat map passes through")
    wrapped = {"decisions": [{"pair_id": "p1", "verdict": "same"},
                             {"pair_id": "p2", "verdict": "different"}]}
    r = RUN._index_decisions(wrapped, ("pair_id",))
    ck(r and r["p1"]["verdict"] == "same" and r["p2"]["verdict"] == "different",
       "a wrapper-list {'decisions':[...]} is re-indexed by pair_id")
    r = RUN._index_decisions([{"pair_id": "p9", "verdict": "same"}], ("pair_id",))
    ck(r and r["p9"]["verdict"] == "same", "a BARE list is re-indexed too")
    r = RUN._index_decisions({"decisions": [{"conflict_id": "c1", "pick": "default"}]},
                             ("conflict_id", "field"))
    ck(r and r["c1"]["pick"] == "default", "field decisions index on conflict_id")
    ck(all(RUN._index_decisions(x, ("pair_id",)) is None
           for x in ("nope", None, 7, [], {"decisions": []})),
       "junk / empty answers are rejected (they must re-ask, not silently pass)")

    # ---------------- tracker: both .SKIP spellings + a hash-less map ----------------
    print("\ntracker: the DECLINE and a hash-less map are both honoured")
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    ck("_map.json.SKIP" in src and "_map.SKIP" in src,
       "both .SKIP spellings appear in run.py (the docs' wording AND the code's original)")
    ck("declined = skip_f.exists() or skip_alt.exists()" in src,
       "the decline test accepts either spelling")
    ck("mapcheck_skip_alt" in src, "the verify pass accepts either spelling too")
    ck("if got is None:" in src and "cached.get(\"map\") or cached.get(\"columns\")" in src,
       "a map with NO input_hash is accepted; only a PRESENT-but-mismatched hash re-asks")
    instr = src[src.find("To DECLINE the LLM map"):][:400]
    ck("_map.SKIP" in instr and ".json` REPLACED" in instr,
       "the manifest instruction now names the EXACT decline path (the mismatch's root cause)")

    # ---------------- an unstated area unit is an ASSUMPTION, never a silent stamp ----------------
    print("\nan area with no unit is recorded + surfaced, never silently relabelled")
    msrc = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8")
    ck("areaUnitAssumed" in msrc and "unit_assumptions.append" in msrc,
       "merge records the assumption instead of stamping the dominant unit silently")
    ck('meta["unitAssumptions"] = unit_assumptions' in msrc,
       "the assumptions ride canonical.meta so they can be surfaced")
    # B39 replaced the single-label branch with a PER-FIELD loop: each area converts on the
    # footing of the record that supplied THAT field, so the assumption fires per silent
    # supplier rather than per property. Strictly stronger than the old shape - the behaviour
    # (silent supplier -> not converted + disclosed; stated supplier -> converted) is asserted
    # end-to-end in evals/perfield_unit_test.py against a real merge.
    ck('(prov.get(fld) or {}).get("areaUnitOfSource")' in msrc,
       "the conversion keys on the SUPPLIER's own footing, per field")
    ck("if not _u:" in msrc and "_silent_any = True" in msrc,
       "the assumption fires ONLY where a supplier stated no unit (a stated unit converts)")
    canon = {"meta": {"unitAssumptions": [
        {"property": "Montea Park Venlo", "field": "areaUnit", "assumed": "sq ft",
         "why": "the source stated a numeric area but no unit"}]},
        "properties": [{"id": 1, "park": "P", "city": "C", "country": "GB",
                        "developer": "D", "warehouseArea": 12500, "warehouseRent": "tbd"}]}
    with tempfile.TemporaryDirectory() as td:
        md = DEL.gaps_report(canon, "Test", work_dir=Path(td))
    ck("Area units assumed" in md, "the Gaps Report has an 'Area units assumed' section")
    ck("Montea Park Venlo" in md and "sq ft" in md,
       "it names the property and the assumed unit so the broker can chase the source")
    md2 = DEL.gaps_report({"meta": {}, "properties": canon["properties"]}, "Test")
    ck("Area units assumed" not in md2, "absent when nothing was assumed (no empty scaffolding)")

    # the upstream fix: the interpretation contract must REQUIRE the unit
    ck("ALSO RETURN `areaUnit`" in src,
       "the deck manifest instructions now REQUIRE areaUnit with any numeric area")
    im = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8").lower()
    ck("requires `areaunit`" in im and "not infer the unit" in im,
       "interpretation.md requires the unit and forbids inferring it (LLM reads it, Python never guesses)")

    # ---------------- exit 12: a retyped source echo must not re-ask ----------------
    print("\nexit 12: the translation cache tolerates retyped typography")
    import translate as TR
    tc = "nl"
    src_txt = "the developer’s Corby scheme – 39,471 sq m of GIA"
    retyped = "the developer's Corby scheme - 39,471   sq m of GIA"   # ' and - and re-wrapped
    cache = TR._hashed_cache({retyped: "de Corby-ontwikkeling - 39.471 m2 GIA"}, tc)
    canon = {"properties": [{"id": 1, "description": src_txt}]}
    ck(TR.collect_requests(canon, tc, cache) == [],
       "a RETYPED echo (curly quote / en dash / re-wrapped space) is NOT re-requested")
    TR.bake(canon, cache, tc)
    ck(canon["properties"][0]["description"].startswith("de Corby"),
       "and it still BAKES through the tolerant key")
    c2 = TR._hashed_cache({src_txt: "EXACT", retyped: "FOLDED"}, tc)
    canon2 = {"properties": [{"id": 1, "description": src_txt}]}
    TR.bake(canon2, c2, tc)
    ck(canon2["properties"][0]["description"] == "EXACT",
       "an EXACT-byte entry still wins over the folded one")
    ck(len(TR.collect_requests(
        {"properties": [{"id": 2, "description": "A different building in Venlo."}]}, tc, cache)) == 1,
       "genuinely new prose is still requested (the fold is not a catch-all)")

    # ---------------- exit 8: an empty geocode answer is memoised ----------------
    print("\nexit 8: 'no such place' is a real answer and is remembered")
    wsrc = (ROOT / "helpers" / "web_enrich.py").read_text(encoding="utf-8")
    ck('geo_cache[g["key"]] = {"latlng": None, "cc": ""}' in wsrc,
       "an empty Nominatim array writes a NEGATIVE memo (was: nothing, so it re-asked forever)")
    ck("if n_geo or n_neg:" in wsrc, "the negative memo is PERSISTED (it must survive the run)")
    ck("or n_neg) else 1" in wsrc, "a negative memo counts as forward progress in the exit code")
    ck('if f"{city}|{country}".lower() in _gcache:' in wsrc,
       "_chain_spec consults the cache, so a settled city stops driving chain_work")
    # B02: the memo existed ONLY on the seeds-bundle path. The per-request/static branch and
    # the LIVE path are tiers 1-2 of the orchestrator's probe order - the transports actually
    # tried FIRST - so the livelock survived there after the bundle path was fixed.
    ck('geo_cache[req["key"]] = {"latlng": None, "cc": ""}' in wsrc,
       "the per-request/STATIC branch memoises the negative too")
    ck(wsrc.count('{"latlng": None, "cc": ""}') >= 2,
       "both web_enrich geocode paths write a negative memo")
    ck("nominatim body is not a JSON array" in wsrc,
       "an ERROR ENVELOPE is not memoised as 'no such place' (it is not an answer)")
    esrc = (ROOT / "helpers" / "enrich.py").read_text(encoding="utf-8")
    ck('cache[f"{city}|{country}".lower()] = {"latlng": None, "cc": ""}' in esrc,
       "the LIVE geocode path memoises the negative")
    # ...and the memo must NOT stop a later live retry: a place can be added to OSM later,
    # and the memo's only job is to stop the exit-8 emission.
    _i_neg = esrc.find('{"latlng": None, "cc": ""}')
    ck("if latlng is None and city" in esrc[:_i_neg],
       "the live retry guard still runs on latlng, so a negative memo never blocks a re-query")

    # ---------------- the round-trip backstop ----------------
    print("\nevery round-trip has a backstop: a silent livelock becomes a visible one")
    ck(RUN.ATTEMPT_WARN >= 3, f"the threshold allows legitimate multi-round work ({RUN.ATTEMPT_WARN})")
    n_routed = src.count("_exit_round_trip(work,")
    ck(n_routed >= 8, f"every orchestrator round-trip exits through the backstop ({n_routed} sites)")
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        streaks, warned_at = [], None
        for i in range(1, RUN.ATTEMPT_WARN + 2):
            prior = RUN._bump_attempts(w)
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    RUN._exit_round_trip(w, 3, prior, "interpretation")
            except SystemExit as e:
                ck_code = e.code
            st = json.loads((w / "attempts.json").read_text(encoding="utf-8"))
            streaks.append(st["streak"])
            # Marker must be one that survives the DEFAULT mode. Quiet is now the
            # default (B27) and the "NOT CONVERGING:" prefix is the verbose register
            # of the broker sentence; the livelock DIAGNOSIS is what has to reach the
            # orchestrator, in either mode, on stdout.
            if warned_at is None and "Do NOT loop again" in buf.getvalue():
                warned_at = i
        ck(streaks == list(range(1, len(streaks) + 1)), f"the streak counts up ({streaks})")
        ck(ck_code == 3, "the exit CODE is unchanged - the backstop diagnoses, it never blocks")
        ck(warned_at == RUN.ATTEMPT_WARN,
           f"it stays quiet until round {RUN.ATTEMPT_WARN} (warned at {warned_at})")
        prior = RUN._bump_attempts(w)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                RUN._exit_round_trip(w, 8, prior, "web enrichment")
        except SystemExit:
            pass
        ck(json.loads((w / "attempts.json").read_text(encoding="utf-8"))["streak"] == 1,
           "a DIFFERENT exit code resets the streak (progress is being made)")
        RUN._clear_attempts(w)
        ck(json.loads((w / "attempts.json").read_text(encoding="utf-8")).get("streak") is None,
           "a completed run clears the streak, so a later round-trip starts from zero")

    print(f"\n{'OK' if not fails else 'FAIL'} guardwiden_test: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
