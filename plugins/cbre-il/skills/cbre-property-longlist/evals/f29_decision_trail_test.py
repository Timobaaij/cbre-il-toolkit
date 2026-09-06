#!/usr/bin/env python3
"""f29_decision_trail_test.py - a work dir says which decision stages had NOTHING to decide, and
why, so a reviewer can tell "not applicable" from "never ran". (F29)

THE DEFECT. A blind reviewer could not close its audit of a live work dir: no
match_decisions.json, no match_verify.json, no field_decisions.json, no tracker maps.
Consistent with a brochures-only corpus, in its own words, "but I cannot tell 'not applicable'
from 'never ran'". Absence is not evidence.

WHAT IS PINNED, on `run._write_decision_trail` and its call site:
  1. one record file -> every cross-source stage is `not_applicable` with a `why` that names the
     count, and no spreadsheet -> tracker maps `not_applicable`;
  2. two record files with grey pairs and no output -> `applicable_no_output`, which IS "never
     ran" and is exactly what the reviewer must be able to see; with the output present -> `ran`;
  3. a tracker offered to the mapping sub-agent is `ran` once its map or .SKIP exists, and is
     listed with both paths checked, so the evidence is re-countable rather than trusted;
  4. the stamp is written before the merge stage on every pass.

Offline. Run: python evals/f29_decision_trail_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import run as RUN  # noqa: E402

FAILS: list = []
RSRC = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8", errors="replace")


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def _trail(w: Path, *args) -> dict:
    with contextlib.redirect_stderr(io.StringIO()):
        RUN._write_decision_trail(w, *args)
    return json.loads((w / "decision_trail.json").read_text(encoding="utf-8"))["stages"]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("1. brochures only: everything cross-source is NOT APPLICABLE, with the count in words")
    w = Path(tempfile.mkdtemp(prefix="cbre_f29_"))
    st = _trail(w, [w / "extract" / "deck_a.json"], 0, [], None, None)
    ck(set(st) == {"match_decisions", "match_verify", "field_decisions", "tracker_maps"},
       f"the four decision stages are all named ({sorted(st)})")
    ck(all(v["status"] == "not_applicable" for v in st.values()),
       "all four are not_applicable")
    ck("produced 1" in st["match_decisions"]["why"]
       and st["match_decisions"]["evidence"]["record_files"] == ["deck_a.json"],
       f"the reason names the record-file count and lists the files "
       f"({st['match_decisions']['why']})")
    ck(st["match_decisions"]["evidence"]["grey_pairs"] is None,
       "grey_pairs is None: the enumeration never ran, and the stamp says so rather than 0")
    ck("no spreadsheet" in st["tracker_maps"]["why"],
       f"tracker maps: no spreadsheet in the inventory ({st['tracker_maps']['why']})")

    print("\n2. cross-source: an absent output is 'applicable_no_output', a present one 'ran'")
    w = Path(tempfile.mkdtemp(prefix="cbre_f29_x_"))
    st = _trail(w, ["a.json", "b.json"], 0, [], 3, 0)
    ck(st["match_decisions"]["status"] == "applicable_no_output",
       "2 record files, 3 grey pairs, no match_decisions.json -> applicable_no_output")
    ck(st["match_verify"]["status"] == "applicable_no_output"
       and st["match_verify"]["evidence"]["grey_pairs"] == 3,
       "the verify pass is applicable (grey pairs exist) and its absence is visible")
    ck(st["field_decisions"]["status"] == "not_applicable" and "found 0" in st["field_decisions"]["why"],
       f"0 field conflicts -> not_applicable, and the why says the enumeration found 0")
    (w / "match_decisions.json").write_text("{}", encoding="utf-8")
    st = _trail(w, ["a.json", "b.json"], 0, [], 3, 2)
    ck(st["match_decisions"]["status"] == "ran"
       and st["match_decisions"]["evidence"]["output_exists"] is True,
       "with match_decisions.json present -> ran, output_exists True")
    ck(st["field_decisions"]["status"] == "applicable_no_output",
       "2 conflicts and no field_decisions.json -> applicable_no_output")

    print("\n3. tracker maps: evidence is the output/.SKIP the guard itself checks")
    w = Path(tempfile.mkdtemp(prefix="cbre_f29_t_"))
    out = w / "extract" / "sheet_map.json"
    job = {"source_file": "sheet.xlsx", "kind": "tracker", "output": str(out)}
    st = _trail(w, ["a.json"], 1, [job], None, None)
    ev = st["tracker_maps"]["evidence"]["trackers_offered"]
    ck(st["tracker_maps"]["status"] == "applicable_no_output" and len(ev) == 1
       and ev[0]["output_exists"] is False and ev[0]["skip_exists"] is False,
       f"offered, neither map nor .SKIP -> applicable_no_output, both paths reported ({ev})")
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(str(out) + ".SKIP").write_text("", encoding="utf-8")
    st = _trail(w, ["a.json"], 1, [job], None, None)
    ck(st["tracker_maps"]["status"] == "ran"
       and st["tracker_maps"]["evidence"]["trackers_offered"][0]["skip_exists"] is True,
       "a .SKIP sentinel counts as decided -> ran")
    st = _trail(w, ["a.json"], 1, [], None, None)
    ck(st["tracker_maps"]["status"] == "not_applicable" and "built-in dictionary" in st["tracker_maps"]["why"],
       f"a spreadsheet the dictionary bound entirely offered nothing -> not_applicable, said so")

    print("\n4. the spine writes it before merge, every pass")
    i = RSRC.find("_write_decision_trail(work, record_files, len(inv.get(\"xlsx\") or []), interpret_trackers,")
    j = RSRC.find('_stage("merge")')
    ck(i != -1 and j != -1 and i < j and RSRC[i:j].count("\n") < 6,
       "called immediately before _stage(\"merge\")")
    ck("_n_grey = len(grey or [])" in RSRC and "_n_conflicts = len(conflicts or [])" in RSRC,
       "the grey-pair and conflict counts are captured where the enumeration runs")

    print("\nSTATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    if FAILS:
        print(f"F29 DECISION TRAIL TEST: FAIL ({len(FAILS)})")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("F29 DECISION TRAIL TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
