#!/usr/bin/env python3
"""f17_form_disagreement_signal_test.py - two records disagreeing on the FORM of one value is a
[SIGNAL], printed by capture-symmetry beside its asymmetry signals.

THE NEAR MISS, live. Two isolated readers wrote two different forms of the same country (the
two-letter code and the country's common abbreviation). `normalize.country_iso` happened to
converge them at merge, so nothing was wrong. But that depends on ONE call site and on the alias
table holding whichever form each reader chose: a name in the deck's own language, or an alias
the table lacks, would split a KPI or a filter chip silently, with every value individually
correct. Country is the instance found; the signal is written for the class.

THE RULE: for each field, group raw forms by the form the pipeline would normalise them TO
(registered normalisers for the fields merge normalises; a whitespace-and-case fold for every
other short, non-numeric value, which is what a filter chip splits on) and name any field where
one normalised value arrives in two or more raw forms.

WHAT THIS PINS:
  1. country in three forms -> ONE signal naming all three forms and their sources;
  2. a short label differing only by case -> a signal via the fold, with the fold's own remedy;
  3. prose, numbers, and pipeline-assigned keys never signal; two DIFFERENT values never do;
  4. a single source can disagree with itself (two unit records): the signal prints even where
     the asymmetry check is not applicable;
  5. the gate stays ADVISORY (exit 0), the signal lands in capture_symmetry.json too.
Offline; subprocess against the real CLI.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"
sys.path.insert(0, str(ROOT / "helpers"))
import gate_runner as G  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def rec(src, **kw):
    return dict(kw, __meta={"source_file": src, "source_type": "pdf"})


def run(work: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GATE), "capture-symmetry", "--work", str(work)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "work"
        ex = w / "extract"
        ex.mkdir(parents=True)
        common = {"park": "Park", "city": "Town", "warehouseArea": 1000, "warehouseRent": "EUR 45"}
        ex.joinpath("a_vision.json").write_text(json.dumps([
            rec("a.pdf", **common, country="DE", status="Available Now", clearHeight="12 m",
                description="A long prose description of the scheme that no fold should touch"),
            rec("a.pdf", **common, country="DE", status="Available Now", clearHeight="12 M"),
        ]), encoding="utf-8")
        ex.joinpath("b_vision.json").write_text(json.dumps([
            rec("b.pdf", **common, country="Deutschland", status="AVAILABLE NOW", clearHeight="10 m",
                description="a long prose description of the scheme that no fold should touch"),
        ]), encoding="utf-8")
        ex.joinpath("c_vision.json").write_text(json.dumps([
            rec("c.pdf", **common, country="Germany", status="Under Offer", loadingDocks="12"),
        ]), encoding="utf-8")
        ex.joinpath("SomeTracker_map.json").write_text(json.dumps({"x": 1}), encoding="utf-8")

        print("1. country in three forms is ONE signal")
        rc, out = run(w)
        ck(rc == 0 and "STATUS: ALL-PASS" in out, "the gate stays advisory")
        sig = [l for l in out.splitlines() if "[SIGNAL]" in l and "FORMS of one value" in l]
        country = [l for l in sig if "`country`" in l]
        ck(len(country) == 1, "exactly one form-disagreement signal for `country`")
        ck(country and "'DE' (2 record(s): a.pdf)" in country[0] and "'Deutschland' (1 record(s): b.pdf)" in country[0]
           and "'Germany' (1 record(s): c.pdf)" in country[0] and "('DE')" in country[0],
           "it names every form with its record count and sources, and the normalised value")
        ck(country and "registered normaliser" in country[0],
           "for a normalised field it says merge converges them today, and why that is fragile")

        print("2. a label differing only by case signals via the fold")
        status = [l for l in sig if "`status`" in l]
        ck(len(status) == 1 and "'Available Now' (2 record(s): a.pdf)" in status[0]
           and "'AVAILABLE NOW' (1 record(s): b.pdf)" in status[0],
           "`status` 'Available Now' vs 'AVAILABLE NOW' is one signal")
        ck(status and "Under Offer" not in status[0],
           "...and a genuinely DIFFERENT status is not folded into it")
        ck(status and "differ only by case or spacing" in status[0] and "repairs.json" in status[0],
           "the fold case gets the fold's remedy (pick one form), not the alias-table one")
        ch = [l for l in sig if "`clearHeight`" in l]
        ck(len(ch) == 1 and "'12 m'" in ch[0] and "'12 M'" in ch[0] and "'10 m'" not in ch[0],
           "a measured value in two casings signals; a different magnitude does not join it")

        print("3. what never signals")
        ck(not any("`description`" in l for l in sig), "prose longer than a label is never compared by form")
        ck(not any("`warehouseArea`" in l or "`loadingDocks`" in l for l in sig), "numbers never signal")
        ck(not any("`park`" in l or "`city`" in l for l in sig), "identical forms never signal")
        ck(len(sig) == 3, f"exactly three form signals in total (found {len(sig)})")

        print("4. the signal reaches the JSON, and prints first")
        side = json.loads((w / "capture_symmetry.json").read_text(encoding="utf-8"))
        fd = side.get("form_disagreements") or []
        ck({f["field"] for f in fd} == {"country", "status", "clearHeight"},
           "capture_symmetry.json carries the same three under form_disagreements")
        c = next(f for f in fd if f["field"] == "country")
        ck(c["via"] == "normaliser" and c["normalised"] == "DE" and c["forms"][0]["form"] == "DE"
           and c["forms"][0]["records"] == 2,
           "each entry says how it was normalised, to what, and lists forms most-frequent first")
        first = next(l for l in out.splitlines() if "[SIGNAL]" in l or "[note]" in l)
        ck("FORMS of one value" in first, "form signals print before the asymmetry findings")
        ck("form disagreement SIGNAL(s)" in out, "the PASS line counts them")

        print("5. one source can disagree with itself")
        w2 = Path(td) / "one"
        (w2 / "extract").mkdir(parents=True)
        (w2 / "extract" / "d_vision.json").write_text(json.dumps([
            rec("d.pdf", **common, country="FR"), rec("d.pdf", **common, country="France")]),
            encoding="utf-8")
        rc, out = run(w2)
        ck(rc == 0 and "not applicable" in out and "`country`" in out and "FORMS of one value" in out,
           "with ONE source the asymmetry check is not applicable but the form signal still prints")

        print("6. the pure function and the code-field reading")
        fd_na = G.form_disagreements([rec("x.pdf", country="NA"), rec("y.pdf", country="na")])
        ck(len(fd_na) == 1 and {x["form"] for x in fd_na[0]["forms"]} == {"NA", "na"},
           "a bare assigned alpha-2 code in `country` is a VALUE (the code reading, not the prose "
           "one), so its two casings disagree by form rather than being skipped as unknown")
        ck(G.form_disagreements([rec("x.pdf", unit="n/a"), rec("y.pdf", unit="N/A")]) == [],
           "two unknown forms never disagree: unknowns are skipped before the fold")
        ck("country" in G._FORM_NORMALISERS and G._form_key("country", "Deutschland") == "DE",
           "the country normaliser is the same one merge applies (normalize.country_iso)")

    print()
    if FAILS:
        print(f"F17 FORM DISAGREEMENT SIGNAL TEST: FAIL ({len(FAILS)})")
        return 1
    print("F17 FORM DISAGREEMENT SIGNAL TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
