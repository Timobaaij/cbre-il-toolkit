#!/usr/bin/env python3
"""project_layout_test.py - the THREE-FOLDER project layout.

THE DEFECT this closes. A project folder held an arbitrarily-named inputs folder beside a
`work/` dir carrying ~40 technical files, with the four CLIENT-FACING deliverables buried
three levels down in `work/deliverables/`. A non-technical broker opening that folder could
not tell which of ~15 items was the dashboard. The fix is a convention, not a rewrite: one
`--project <root>` derives `1. Input` / `2. Work Files` / `3. Output`, every helper keeps
taking the same `--work <path>` it always took, and the output folder holds ONLY the four
deliverables (the technical completion marker moves to the work dir).

What is pinned here:
  A. `--project` derives all three folders, and each slot is overridable.
  B. The LEGACY shape (`--folder` + `--work`, no `--project`) still delivers to
     `<work>/deliverables` - byte-for-byte the old behaviour, nothing broken.
  C. Neither shape given is a plain-English error, not an argparse usage dump.
  D. deliver.py's `--marker-dir` keeps `.delivery_complete.json` OUT of the output folder,
     `delivery_complete()` still finds a legacy marker, and the output folder is left with
     exactly the four deliverables.
  E. SKILL.md documents the layout (a convention nobody is told about is not a convention).
Fully offline; no PDF engine, no network.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    import run as RUN
    import deliver as D

    print("A: --project derives the three folders")
    ck((RUN.INPUT_DIRNAME, RUN.WORK_DIRNAME, RUN.OUTPUT_DIRNAME)
       == ("1. Input", "2. Work Files", "3. Output"),
       "the three folder names are numbered constants on run.py")
    ap = RUN._build_parser()

    def _lay(argv):
        return RUN._resolve_layout(ap.parse_args(argv))

    i, w, o = _lay(["--project", "P"])
    ck(i == (Path("P").resolve() / RUN.INPUT_DIRNAME), f"inputs -> {RUN.INPUT_DIRNAME}")
    ck(w == (Path("P").resolve() / RUN.WORK_DIRNAME), f"work   -> {RUN.WORK_DIRNAME}")
    ck(o == (Path("P").resolve() / RUN.OUTPUT_DIRNAME), f"output -> {RUN.OUTPUT_DIRNAME}")
    # every slot overridable, so a half-migrated project still runs
    i2, w2, o2 = _lay(["--project", "P", "--folder", "IN", "--work", "WK", "--out-dir", "OUT"])
    ck((i2, w2, o2) == (Path("IN").resolve(), Path("WK").resolve(), Path("OUT").resolve()),
       "--folder / --work / --out-dir each override their slot")

    print("\nB: the LEGACY shape is untouched")
    i3, w3, o3 = _lay(["--folder", "IN", "--work", "WK"])
    ck(i3 == Path("IN").resolve() and w3 == Path("WK").resolve(),
       "--folder/--work alone still resolve to exactly themselves")
    ck(o3 == Path("WK").resolve() / RUN.LEGACY_OUTPUT_SUBDIR,
       f"and still deliver to <work>/{RUN.LEGACY_OUTPUT_SUBDIR} (no --project, no new location)")

    print("\nC: neither shape given fails in plain English")
    try:
        _lay(["--client", "X"])
        ck(False, "a run with no --project and no --folder/--work is refused")
    except ValueError as e:
        ck(True, "a run with no --project and no --folder/--work is refused")
        ck("--project" in str(e) and "--folder" in str(e),
           "the message names BOTH accepted shapes")
        ck("usage:" not in str(e).lower(), "it is a sentence, not an argparse usage dump")
    except SystemExit:
        ck(False, "refusal must be a ValueError run.py can phrase, not argparse's SystemExit")

    print("\nD: the completion marker stays out of the broker's output folder")
    ck("marker_dir" in D.delivery_complete.__code__.co_varnames,
       "deliver.delivery_complete(out_dir, marker_dir=...) exists")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        work, out = td / RUN.WORK_DIRNAME, td / RUN.OUTPUT_DIRNAME
        work.mkdir(); out.mkdir()
        canon = work / "canonical.json"
        canon.write_text(json.dumps({
            "meta": {"client": "Fx", "units": {"area": "sq ft", "rent": "GBP"}},
            "properties": [{"id": 1, "park": "A", "city": "Corby", "warehouseArea": "100,000 sq ft"}],
            "pois": [], "regions": {}}), encoding="utf-8")
        html = work / "built.html"
        html.write_text("<html>" + "x" * 6000 + "</html>", encoding="utf-8")
        rc = subprocess.run([sys.executable, str(HELPERS / "deliver.py"),
                             "--canonical", str(canon), "--html", str(html),
                             "--out-dir", str(out), "--marker-dir", str(work),
                             "--slug", "Fx"], capture_output=True, text=True).returncode
        ck(rc == 0, "deliver.py runs with --marker-dir")
        ck((work / D.MARKER_NAME).exists(), "the marker is written into the WORK dir")
        ck(not (out / D.MARKER_NAME).exists(), "and NOT into the output folder")
        got = sorted(p.name for p in out.iterdir())
        ck(all(not n.startswith(".") for n in got) and all(not n.endswith(".json") for n in got),
           f"the output folder holds no dotfile and no .json {got}")
        ck(D.delivery_complete(out, work), "delivery_complete() reads the marker from the work dir")
        # a project delivered BEFORE the split (marker in the out dir) is still complete
        (work / D.MARKER_NAME).rename(out / D.MARKER_NAME)
        ck(D.delivery_complete(out, work),
           "a LEGACY marker left in the out dir is still accepted (no needless re-delivery)")

    print("\nD2: the QA window survives a RENAME of the work dir")
    # THE LIVE DEFECT: _qa_run_key hashed Path(work).resolve(), so restructuring a project
    # into 1. Input / 2. Work Files / 3. Output made _qa_load treat a byte-identical
    # qa_state.json as "a different corpus" - it wiped `rounds`, qa_carried() returned [],
    # and the very next deliver.py shipped a Gaps Report with NO "Known limitations"
    # section while qa_round_number fell to 0. 51 reviewed-and-accepted limitations
    # vanished from the honesty document because a folder was renamed.
    import gate_runner as GR
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        a, b = td / "work", td / RUN.WORK_DIRNAME
        a.mkdir()
        (a / "inventory.json").write_text(json.dumps(
            {"folder": str(td / "in"), "input_hash": "deadbeefcafe"}), encoding="utf-8")
        state = {"schema_version": 2, "run_key": GR._qa_run_key(a), "advisory_carried": [],
                 "rounds": [{"n": 1, "recorded": True, "blocking": [],
                             "advisory": ["G-x: property=1 field=rent issue=advisory one"],
                             "verdicts": {}}]}
        (a / "qa_state.json").write_text(json.dumps(state), encoding="utf-8")
        ck(len(GR.qa_carried(a)) == 1 and GR.qa_round_number(a) == 1,
           "baseline: the window is readable where it was written")
        a.rename(b)
        ck(len(GR.qa_carried(b)) == 1,
           "the carried limitation SURVIVES renaming the work dir (was: silently wiped)")
        ck(GR.qa_round_number(b) == 1,
           "and the recorded round survives too (PASS-WITH-REMEDIATION stays available)")
        # a genuinely DIFFERENT corpus in the same dir must still open a fresh window
        (b / "inventory.json").write_text(json.dumps(
            {"folder": str(td / "in"), "input_hash": "0123456789ab"}), encoding="utf-8")
        ck(GR.qa_carried(b) == [] and GR.qa_round_number(b) == 0,
           "a DIFFERENT corpus still resets the window (the key still means something)")
    # source pin: the hashed payload must be corpus-only (the docstring still NAMES the old
    # path-coupled recipe, so pin the return expression rather than the whole body)
    _body = (HELPERS / "gate_runner.py").read_text(encoding="utf-8") \
        .split("def _qa_run_key(")[1].split("\ndef ")[0]
    _ret = _body.split("return", 1)[1]
    ck("corpus|" in _ret and "resolve()" not in _ret,
       "_qa_run_key hashes the corpus identity only, never the work dir's path")

    print("\nE: SKILL.md tells a fresh orchestrator about the layout")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for tok in ("1. Input", "2. Work Files", "3. Output", "--project"):
        ck(tok in skill, f"SKILL.md documents {tok!r}")
    ck("--folder" in skill and "deliverables" in skill,
       "SKILL.md still documents the legacy shape (backward compatibility is discoverable)")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
