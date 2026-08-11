#!/usr/bin/env python3
"""deliver_atomic_test.py - the delivery is complete or it is not delivered. (B01)

deliver writes FOUR artefacts - dashboard, Source Ledger, Gaps Report, Longlist - each
individually atomic, but the SET was not, and run.py's Stage-7 resume guard keyed on the
DASHBOARD, which is written FIRST. So the guard was satisfied the instant step 1 committed.
A cap-kill in steps 2-4 then wedged Stage 7 two ways:

  Mode A (hard livelock): three artefacts never exist, every later run resume-skips, and
    final_gate FAILs them with no remediation line. Stage 7 exits 0, so it carries no
    _exit_round_trip accounting to bound the loop.
  Mode B (silent mixed-version ship): on a RE-delivery, a v2 dashboard ships beside a v1
    Gaps Report and Longlist, and all four presence checks pass.

The fix is a completion marker written LAST, with the guard keyed on the marker. NOT
"require all four artefacts": deliver.py deliberately swallows a Longlist failure so a
workbook hiccup can never block the hand-off, so a permanently failing Longlist would make
that predicate unsatisfiable - deliver would re-run every pass forever while final_gate
still blocked. That trades one unbounded loop for another. Offline."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import deliver as D  # noqa: E402
import run as RUN  # noqa: E402

RUN_SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def _canon():
    return {"meta": {"client": "Acme", "units": {"area": "sq ft"},
                     "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                              "lede": "", "footer_copyright": ""}},
            "properties": [{"id": 1, "park": "Alpha", "city": "Corby", "country": "GB",
                            "warehouseArea": 120000}],
            "pois": [], "regions": {}}


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    ck(hasattr(D, "MARKER_NAME"), "deliver.MARKER_NAME exists")
    ck(hasattr(D, "delivery_complete"), "deliver.delivery_complete() exists")
    if not (hasattr(D, "MARKER_NAME") and hasattr(D, "delivery_complete")):
        print(f"\nDELIVER ATOMIC TEST: FAIL ({len(fails)})")
        return 1

    d = Path(tempfile.mkdtemp(prefix="cbre_dlv_"))
    work = d / "work"; work.mkdir()
    (work / "canonical.json").write_text(json.dumps(_canon()), encoding="utf-8")
    (work / "built.html").write_text("<html>dash</html>", encoding="utf-8")
    (work / "source_ledger.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    outd = work / "deliverables"

    def _deliver():
        return subprocess.run(
            [sys.executable, str(HELPERS / "deliver.py"),
             "--canonical", str(work / "canonical.json"), "--html", str(work / "built.html"),
             "--ledger", str(work / "source_ledger.csv"), "--out-dir", str(outd),
             "--slug", "Acme", "--filename", "dash.html"],
            capture_output=True, text=True, errors="replace")

    p = _deliver()
    ck(p.returncode == 0, f"deliver completes {ascii((p.stdout + p.stderr)[-120:])}")
    marker = outd / D.MARKER_NAME
    ck(marker.exists(), "a completion marker is written")
    ck(D.delivery_complete(outd), "delivery_complete() is True after a full delivery")

    # the marker must be LAST: it may not predate any artefact it vouches for
    m_m = marker.stat().st_mtime_ns
    for f in outd.iterdir():
        if f.name != D.MARKER_NAME:
            ck(f.stat().st_mtime_ns <= m_m,
               f"the marker is not older than {ascii(f.name)}")

    # MODE A: the sidecars vanish (or never landed). The marker must stop vouching.
    (outd / "Acme_Gaps_Report.md").unlink()
    ck(not D.delivery_complete(outd),
       "a missing Gaps Report invalidates the delivery (Mode A cannot resume-skip)")
    p = _deliver()
    ck((outd / "Acme_Gaps_Report.md").exists(), "and a re-delivery restores it")

    # MODE B: a kill after step 1. Simulate by removing the marker and the sidecars,
    # leaving only a NEWER dashboard - exactly the on-disk state the old guard accepted.
    (outd / D.MARKER_NAME).unlink()
    (outd / "dash.html").write_text("<html>v2</html>", encoding="utf-8")
    ck(not D.delivery_complete(outd),
       "a v2 dashboard with no marker does NOT read as delivered (Mode B cannot ship)")

    # a Longlist that ALWAYS fails must not make the predicate unsatisfiable
    ck("Longlist export failed" in (HELPERS / "deliver.py").read_text(
        encoding="utf-8", errors="replace"),
       "the Longlist failure is still swallowed (the hand-off is never blocked by it)")
    names = json.loads(marker.read_text(encoding="utf-8")).get("artefacts") \
        if marker.exists() else None
    if names is None:
        p = _deliver()
        names = json.loads((outd / D.MARKER_NAME).read_text(encoding="utf-8")).get("artefacts")
    ck(isinstance(names, list) and any("Gaps_Report" in n for n in names),
       f"the marker records what it vouches for {ascii(str(names)[:80])}")

    # WIRING: run.py's Stage-7 guard must key on the marker, not the dashboard
    ck("delivery_complete" in RUN_SRC, "run.py consults deliver.delivery_complete")
    i_guard = RUN_SRC.find("_is_current(deliverables / filename")
    ck(i_guard != -1, "the input-freshness half of the guard is still there")
    # the two conditions must be CONJOINED in one statement: input-freshness alone was the
    # defect, and delivery-completeness alone would never re-deliver after a data change.
    stmt = RUN_SRC[i_guard:i_guard + 400].split("_resumed(")[0]
    ck("delivery_complete(deliverables)" in stmt and "and" in stmt,
       "it is ANDed with delivery_complete in the same guard")

    if fails:
        print(f"\nDELIVER ATOMIC TEST: FAIL ({len(fails)})")
        return 1
    print("\nDELIVER ATOMIC TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
