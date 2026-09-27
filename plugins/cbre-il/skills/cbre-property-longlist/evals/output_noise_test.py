#!/usr/bin/env python3
"""output_noise_test.py - re-applied repairs are COUNTED, not re-listed, in the quiet report.
(2026-09-26 test run, fix 1.10, repairs.py half)

WHY THIS EXISTS. On the real run's final pass repairs_report.json held 64 applied entries with
85 changes, 83 of them `from == to` (a repair re-applied on a resumed pass moves nothing), plus
9 stale clears that had "landed on an earlier run" - and every one was re-printed on all 13
passes, burying the two lines that were news. `format_report(rep, compact=True)` counts those
two no-op classes in one line each and prints everything else exactly as before; the default
stays byte-identical so the CLI and every existing caller are unchanged.

What this pins:
  (a) compact=True: from==to changes and already-absent strikes are absent from the listing and
      summarised with a count; a moved value, a CLEARED real value, media and NOT struck lines
      still print; a `landed_earlier` stale is summarised WITH its id; an `alias_promoted` stale
      gets its own summary line; a typo stale, AMBIGUOUS, SUPERSEDED and INVALID always print;
      compact=False equals a golden list built here for a report WITHOUT the new keys (the
      pre-change output), so an old repairs_report.json prints as it always did;
  (b) repairs.apply sets the additive stale key `landed_earlier`: True for a clear whose key the
      Source Ledger still credits to the property, False for a misspelt key.
The run.py half, added by the run.py owner:
  (c) `run._print_once` prints the full lines the first time its content is seen and the short
      repeat afterwards (quiet only); changed content, --verbose, a corrupt or unwritable digest
      store all print the full lines; `handoff=True` goes through `_say_orchestrator`;
  (d) source pins: `format_report(_rrep, compact=QUIET)`; the duplicate note and the
      recorded-only block go through `_print_once`; the recorded-only full text is always in
      work/recorded_only_repairs.md; every repeat line starts with `(orchestrator:` or `(`.
Offline; synthetic.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import repairs as R                      # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def report(new_keys: bool = True) -> dict:
    stale_landed = {"id": "rp-L", "reason": "`unset` asked to clear oldKey ... landed on an "
                                            "earlier run - a correct entry, doing nothing."}
    stale_typo = {"id": "rp-T", "reason": "`unset` asked to clear oddKeyy ... check the spelling"}
    stale_promo = {"id": "rp-P", "reason": "`unset` asked to clear levelAccessDoors ... promoted"}
    if new_keys:
        stale_landed.update(landed_earlier=True, alias_promoted=False)
        stale_typo.update(landed_earlier=False, alias_promoted=False)
        stale_promo.update(landed_earlier=False, alias_promoted=True)
    return {
        "applied": [
            {"id": "rp-1", "property_id": 1, "why": "same again",
             "changed": {"warehouseArea": {"from": 10000, "to": 10000.0},
                         "status": {"from": "Available", "to": " Available "}}},
            {"id": "rp-2", "property_id": 2, "why": "a real fix",
             "changed": {"warehouseArea": {"from": 9000, "to": 9500}}},
            {"id": "rp-3", "property_id": 3, "why": "withdrawn",
             "changed": {"tenure": {"from": "Leasehold", "to": R.CLEARED, "cleared": True}}},
            {"id": "rp-4", "property_id": 4, "why": "unfused",
             "changed": {"yardDepth": {"from": None, "to": R.CLEARED, "cleared": True,
                                       "already_absent": True, "struck_from": "deck.pdf"}},
             "protected": ["photo"]},
            {"id": "rp-5", "property_id": 5, "why": "better hero", "changed": {},
             "media": {"hero": "repair_media/x.jpg"}},
        ],
        "stale": [stale_landed, stale_typo, stale_promo],
        "ambiguous": [{"id": "rp-A", "reason": "matched two"}],
        "superseded": [{"id": "rp-S", "reason": "expect moved"}],
        "invalid": ["repair rp-I: bad"],
    }


GOLDEN = [
    "  - rp-1: property 1 warehouseArea: 10000 -> 10000.0  (same again)",
    "  - rp-1: property 1 status: 'Available' -> ' Available '  (same again)",
    "  - rp-2: property 2 warehouseArea: 9000 -> 9500  (a real fix)",
    "  - rp-3: property 3 tenure: CLEARED, was 'Leasehold'  (withdrawn)",
    "  - rp-4: property 4 yardDepth: CLEARED, was None (struck with everything from deck.pdf)"
    " [already absent: an earlier run's strike removed it]  (unfused)",
    "  - rp-4: property 4 NOT struck: photo - structural, media-owned or schema-required. "
    "Replace a hero with `media`; re-state an identity field with `set`.",
    "  - rp-5: property 5 hero image <- x.jpg  (better hero)",
    "[STALE REPAIR] rp-L `unset` asked to clear oldKey ... landed on an earlier run - a correct "
    "entry, doing nothing.",
    "[STALE REPAIR] rp-T `unset` asked to clear oddKeyy ... check the spelling",
    "[STALE REPAIR] rp-P `unset` asked to clear levelAccessDoors ... promoted",
    "[AMBIGUOUS REPAIR] rp-A matched two",
    "[SUPERSEDED REPAIR] rp-S expect moved",
    "[INVALID REPAIR] repair rp-I: bad - this entry does NOTHING until it is fixed.",
]


def part_a():
    print("== (a) compact=False is the pre-change output ==")
    ck(R.format_report(report(new_keys=False)) == GOLDEN,
       "default output of a report WITHOUT the new keys equals the golden pre-change lines")
    ck(R.format_report(report(new_keys=True)) == GOLDEN,
       "default output ignores the new keys entirely (--verbose / CLI unchanged)")
    ck(R.format_report(report(), compact=False) == GOLDEN, "compact=False spelled out: same")
    ck(R.format_report(report(new_keys=False), compact=True)[-6:] == GOLDEN[-6:],
       "an OLD report (no landed_earlier key) prints its stale lines in full even when compact")

    print()
    print("== (a) compact=True counts the no-ops and keeps the news ==")
    out = R.format_report(report(), compact=True)
    txt = "\n".join(out)
    ck("rp-1:" not in txt, "the two from==to changes of rp-1 are not listed")
    ck("yardDepth" not in txt, "an already-absent strike re-application is not listed")
    ck(any(ln.startswith("  = 3 repaired value(s) on 2 entries already held") for ln in out),
       "one count line: 3 unmoved value(s) on 2 entr(ies)")
    ck(GOLDEN[2] in out, "a MOVED value still prints exactly as before")
    ck(GOLDEN[3] in out, "a CLEARED real value still prints")
    ck(GOLDEN[5] in out and GOLDEN[6] in out, "NOT struck and media lines still print")
    ck(any(ln.startswith("  = 1 clear(s) already landed on an earlier pass") and "rp-L" in ln
           for ln in out), "a landed_earlier stale is summarised with its id")
    ck(not any(ln.startswith("[STALE REPAIR] rp-L") for ln in out), "...and not re-printed")
    ck(any(ln.startswith("  = 1 clear(s) of an alias key") and "rp-P" in ln for ln in out),
       "an alias_promoted stale gets its own summary line with its id")
    ck(GOLDEN[8] in out, "a typo stale prints in full")
    for g in GOLDEN[-3:]:
        ck(g in out, f"always printed: {g[:40]}")
    ck(txt.index("  = ") < txt.index("[STALE REPAIR]"),
       "the summary lines sit after the applied section and before the bracketed buckets")

    many = report()
    many["stale"] = [{"id": f"rp-{i:02d}", "reason": "x", "landed_earlier": True}
                     for i in range(15)]
    ml = [ln for ln in R.format_report(many, compact=True) if "already landed" in ln]
    ck(len(ml) == 1 and "rp-11" in ml[0] and "rp-12" not in ml[0] and "+3 more" in ml[0],
       "more than 12 landed clears: the first 12 ids and '+3 more'")


def part_b():
    print()
    print("== (b) repairs.apply sets `landed_earlier` from the Source Ledger ==")
    canonical = {"meta": {}, "properties": [
        {"id": 1, "park": "Alpha Park", "city": "Northtown", "developer": "Devco",
         "country": "ZZ", "status": "Available", "warehouseArea": 10000}]}
    ledger = [{"property_id": "1", "record_type": "property", "field": "tenure",
               "value": "Leasehold", "source_file": "deck.pdf", "source_locator": "page 4",
               "source_type": "pdf"}]
    base = {"property": {"key": "northtown|devco|alpha park", "id": 1}, "why": "w",
            "verified_by": "t"}
    rep = R.apply(json.loads(json.dumps(canonical)),
                  [dict(base, id="rp-1", unset=["tenure"]),
                   dict(base, id="rp-2", unset=["tenrue"])], provenance=ledger)
    by = {s["id"]: s for s in rep["stale"]}
    ck(by.get("rp-1", {}).get("landed_earlier") is True,
       "a clear whose key the ledger still credits -> landed_earlier True")
    ck("landed on an earlier run" in by.get("rp-1", {}).get("reason", ""),
       "...and the reason text is unchanged")
    ck(by.get("rp-2", {}).get("landed_earlier") is False,
       "a misspelt key -> landed_earlier False (prints in full)")
    ck(by.get("rp-2", {}).get("alias_promoted") is False, "...and alias_promoted False")

    # the same through run(): the flag reaches work/repairs_report.json
    w = Path(tempfile.mkdtemp(prefix="cbre_noise_"))
    (w / "canonical.json").write_text(json.dumps(canonical), encoding="utf-8")
    (w / "repairs.json").write_text(json.dumps([dict(base, id="rp-1", unset=["tenure"])]),
                                    encoding="utf-8")
    with open(w / R.LEDGER_NAME, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(ledger[0]), lineterminator="\n")
        wr.writeheader()
        wr.writerows(ledger)
    R.run(w)
    saved = json.loads((w / "repairs_report.json").read_text(encoding="utf-8"))
    ck(saved["stale"] and saved["stale"][0].get("landed_earlier") is True,
       "the additive key is persisted in work/repairs_report.json")


def part_c():
    """run.py half (the run.py owner's addition): `_print_once` prints the full text the first
    time its content is seen and a short repeat afterwards, in quiet mode only, fail-safe."""
    print()
    print("== (c) run._print_once: full once, then the repeat; verbose and failures print full ==")
    import io
    import contextlib
    import run as RUN                    # noqa: E402

    def _call(work, content, full, rep, handoff=False, quiet=True):
        saved_q, saved_say = RUN.QUIET, RUN._say_orchestrator
        said = []
        RUN.QUIET = quiet
        RUN._say_orchestrator = lambda m: (said.append(m), saved_say(m))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                RUN._print_once(work, "k", content, full, rep, handoff=handoff)
        finally:
            RUN.QUIET, RUN._say_orchestrator = saved_q, saved_say
        return buf.getvalue().splitlines(), said

    w = Path(tempfile.mkdtemp(prefix="cbre_noise_c_"))
    full, rep = ["FULL line 1", "FULL line 2"], ["(short repeat)"]
    out, _ = _call(w, "content A", full, rep)
    ck(out == full, "first sight: the full lines")
    ck((w / RUN.PRINT_DIGESTS).exists(), "a digest store is written in the work dir")
    out, _ = _call(w, "content A", full, rep)
    ck(out == rep, "identical content on the next pass: only the repeat line")
    out, _ = _call(w, "content B", full, rep)
    ck(out == full, "changed content: the full lines again")
    out, _ = _call(w, "content B", full, rep)
    ck(out == rep, "...and the repeat after that")
    out, _ = _call(w, "content B", full, rep, quiet=False)
    ck(out == full, "--verbose always prints the full lines")
    d = json.loads((w / RUN.PRINT_DIGESTS).read_text(encoding="utf-8"))
    ck(d.get("v") == 1 and isinstance(d.get("digests"), dict) and "k" in d["digests"],
       "store shape is {v:1, digests:{key: sha}}")
    (w / RUN.PRINT_DIGESTS).write_text("{not json", encoding="utf-8")
    out, _ = _call(w, "content B", full, rep)
    ck(out == full, "a corrupt digest store: the full lines (fail safe)")
    blocker = w / "a_file"
    blocker.write_text("x", encoding="utf-8")
    o1, _ = _call(blocker, "content A", full, rep)
    o2, _ = _call(blocker, "content A", full, rep)
    ck(o1 == full and o2 == full, "an unwritable work path prints the full lines every time")
    w2 = Path(tempfile.mkdtemp(prefix="cbre_noise_c2_"))
    out, said = _call(w2, "c", ["(orchestrator: full)"], ["(orchestrator: again)"], handoff=True)
    ck(out == ["(orchestrator: full)"] and said == ["(orchestrator: full)"],
       "handoff=True routes the lines through _say_orchestrator, on stdout")
    out, said = _call(w2, "c", ["(orchestrator: full)"], ["(orchestrator: again)"], handoff=True)
    ck(out == ["(orchestrator: again)"] and said == ["(orchestrator: again)"],
       "...and its repeat too (a handoff is shortened, never dropped)")


def part_d():
    """run.py source pins for the three call sites (the run.py owner's addition)."""
    print()
    print("== (d) run.py call sites ==")
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    ck("format_report(_rrep, compact=QUIET)" in src and "format_report(_rrep)" not in src,
       "the repairs report prints compact in quiet mode (verbose lists everything)")
    i = src.find('_dups = inv.get("skipped_duplicates")')
    seg = src[i:i + 1200] if i != -1 else ""
    ck('_print_once(work, "skipped_duplicates"' in seg,
       "the duplicate-file note goes through _print_once")
    ck("work/inventory.json -> skipped_duplicates" in seg,
       "...and its repeat names where the full list lives")
    j = src.find("_ro = _recorded_only_doubt_answers(work)")
    k = src.find("_xf_pend = excluded_figure_questions(", j)
    blk = src[j:k] if 0 < j < k else ""
    ck('_print_once(work, "recorded_only_doubts"' in blk and "handoff=True" in blk,
       "the recorded-only doubt block goes through _print_once as a handoff")
    ck('work / "recorded_only_repairs.md"' in blk and "_write_if_changed(_ro_file" in blk,
       "the full recorded-only text is always written to work/recorded_only_repairs.md")
    r = blk.find("_ro_rep = (")
    rep_src = blk[r:blk.find("_print_once(", r)] if r != -1 else ""
    starts = re.findall(r'\[f"(.{0,14})', rep_src)
    ck(bool(starts) and all(s.startswith("(orchestrator:") or s.startswith("(") for s in starts),
       f"every repeat line starts with '(orchestrator:' or '(' ({starts})")
    ck("_say_orchestrator(_ln)" in blk,
       "when the file cannot be written the full text prints (nothing to point at)")


def main() -> int:
    part_a()
    part_b()
    part_c()
    part_d()
    print()
    if FAILS:
        print(f"OUTPUT NOISE TEST: FAIL ({len(FAILS)})")
        return 1
    print("OUTPUT NOISE TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
