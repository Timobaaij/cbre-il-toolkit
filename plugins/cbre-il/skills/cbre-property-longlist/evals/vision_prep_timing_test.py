"""Eval: vision prep is timed as its own TIMING-ONLY label (2026-09-26 test run, fix 2.6).

The deck render / candidate prep runs physically inside the "master list" span of run.py, so
before this fix a 54 s prep was booked to the scope decision in work/timings.json - the one
instrument meant to attribute time pointed at the wrong stage. The fix adds a timing-only
label, "vision prep", recorded like a stage but never part of the --from/--only vocabulary.

Pins:
  1. in process: master list -> _timing_part("vision prep") -> merge gives exactly the three
     payload entries [master list, vision prep, merge]; vision prep carries its own seconds and
     master list carries BOTH of its halves (coalesced into one entry).
  2. a `resumed` label recorded in either half of master list survives the coalescing.
  3. `_timing_part` with no open stage closes its own span and re-opens nothing.
  4. `_stage_skipped("vision prep")` is False under --from merge (a label is never skipped).
  5. the label is not in STAGE_ORDER, and `run.py --from "vision prep"` is refused with the
     ordinary unknown-stage message (a real subprocess).
  6. source: exactly two `with _timing_part("vision prep")` between `_stage("master list")` and
     `_stage("merge")`, one enclosing the interpret_prep prepare call and one enclosing the
     vision_prep prepare call.

Offline; one short subprocess. Run: python evals/vision_prep_timing_test.py"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import run as R  # noqa: E402


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

    print("\n1-2: payload coalescing around a timing-only sub-span")
    R._STAGE_LOG.clear()
    R._stage("master list")
    R._resumed("before-half label")
    time.sleep(0.03)
    with R._timing_part("vision prep"):
        time.sleep(0.06)
    R._resumed("after-half label")
    time.sleep(0.03)
    R._stage("merge")
    R._close_open_stage()
    pay = R._timings_payload()
    names = [s["stage"] for s in pay["stages"]]
    ck(names == ["master list", "vision prep", "merge"],
       f"payload names are exactly [master list, vision prep, merge] (got {names})")
    by = {s["stage"]: s for s in pay["stages"]}
    vp = float(by.get("vision prep", {}).get("seconds", 0.0))
    ml = float(by.get("master list", {}).get("seconds", 0.0))
    ck(vp >= 0.05, f"vision prep carries its own seconds (>= 0.05, got {vp})")
    ck(ml >= 0.05 and ml < vp + 0.2,
       f"master list carries both halves (~0.06s) and not the prep (got {ml})")
    ck(by.get("master list", {}).get("resumed") == ["before-half label", "after-half label"],
       f"resumed labels of both halves are concatenated ({by.get('master list', {}).get('resumed')})")
    ck(all(set(s) == {"stage", "seconds", "resumed"} for s in pay["stages"]),
       "every entry still has exactly {stage, seconds, resumed}")
    ck(len(R._STAGE_LOG) == 4,
       f"the raw log keeps the split (4 entries) - only the artefact is folded ({len(R._STAGE_LOG)})")

    print("\n3: no open stage -> the span closes itself and re-opens nothing")
    R._STAGE_LOG.clear()
    with R._timing_part("vision prep"):
        pass
    ck([s["stage"] for s in R._STAGE_LOG] == ["vision prep"] and "_t0" not in R._STAGE_LOG[-1],
       f"one closed 'vision prep' entry ({[s['stage'] for s in R._STAGE_LOG]})")

    # an exception inside the span still re-opens the enclosing stage
    R._STAGE_LOG.clear()
    R._stage("master list")
    try:
        with R._timing_part("vision prep"):
            raise ValueError("boom")
    except ValueError:
        pass
    ck(R._STAGE_LOG[-1]["stage"] == "master list" and "_t0" in R._STAGE_LOG[-1],
       "an exception inside the span still re-opens the enclosing stage")
    R._STAGE_LOG.clear()

    print("\n4-5: the label is never a stage")
    ck("vision prep" in R.TIMING_ONLY_LABELS and "vision prep" not in R.STAGE_ORDER,
       "vision prep is a timing-only label, not in STAGE_ORDER")
    _frm = R.FROM_STAGE
    try:
        R.FROM_STAGE = "merge"
        ck(R._stage_skipped("vision prep") is False,
           "_stage_skipped('vision prep') is False under --from merge")
    finally:
        R.FROM_STAGE = _frm
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "1. Input").mkdir(parents=True, exist_ok=True)
        (root / "2. Work Files").mkdir(parents=True, exist_ok=True)
        cp = subprocess.run([sys.executable, str(HELPERS / "run.py"), "--project", str(root),
                             "--from", "vision prep"], capture_output=True, text=True, timeout=120)
        out = (cp.stdout or "") + (cp.stderr or "")
        ck(cp.returncode != 0 and "I don't know a stage called" in out,
           f"--from \"vision prep\" is refused as an unknown stage (exit {cp.returncode})")

    print("\n6: source pins")
    src = (HELPERS / "run.py").read_text(encoding="utf-8")
    a = src.find('_stage("master list")')
    b = src.find('_stage("merge")')
    seg = src[a:b] if 0 < a < b else ""
    ck(seg.count('with _timing_part("vision prep")') == 2,
       f"exactly two `with _timing_part(\"vision prep\")` in the master-list span "
       f"({seg.count('with _timing_part(' + chr(34) + 'vision prep' + chr(34) + ')')})")

    def _enclosed(needle: str) -> bool:
        """Is `needle` inside the body of one of the two `with` blocks (by indentation)?"""
        lines = seg.splitlines()
        for i, ln in enumerate(lines):
            if 'with _timing_part("vision prep")' not in ln:
                continue
            ind = len(ln) - len(ln.lstrip())
            for ln2 in lines[i + 1:]:
                if ln2.strip() and (len(ln2) - len(ln2.lstrip())) <= ind:
                    break
                if needle in ln2:
                    return True
        return False
    ck(_enclosed('extant["interpret_prep"].prepare('),
       "one span encloses the text-deck prepare call")
    ck(_enclosed('extant["vision_prep"].prepare('),
       "one span encloses the raster prepare call")
    ck(src.count('_stage("vision prep")') == 0,
       "no `_stage(\"vision prep\")` literal (the exactly-once vocabulary pins stay true)")

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
