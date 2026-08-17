#!/usr/bin/env python3
"""capture_symmetry_signal_test.py - the gate must surface its own signal. (B62)

capture-symmetry is the only gate that can see UNDER-capture, and on the run that prompted
this it DID see the one real defect: `status`, absent from every record of a 23-property deck
whose every page printed a tenure banner, which merge turned into 20 "absent in all sources"
ledger rows telling the broker to chase data the deck states. It printed as note 14 of 161,
above `... and 136 more`, indistinguishable from `carParking` missing off a one-page flyer.
Two Opus reviewers later found by hand what this gate had already computed.

Being ADVISORY is not a licence to be unreadable. What this pins:
  * a finding carries how many RECORDS it affects, not just how many sources carry the field -
    a field missing from a 23-record deck is 23 false claims, from a 1-record flyer it is one;
  * a CORE field (coverage's own core, minus the enrich-assigned lat/lng) is always a SIGNAL;
  * SIGNAL findings print FIRST and are never truncated away, whatever --max-notes says;
  * the full list is written to work/capture_symmetry.json, so the capped tail is not lost;
  * the gate stays ADVISORY - STATUS: ALL-PASS, never BLOCKED. Different readers legitimately
    use different templates, so an asymmetry is a question for the reviewers, never a verdict.
Offline; no network, no build.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GR = ROOT / "helpers" / "gate_runner.py"
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def build(work: Path):
    """A BIG deck missing a core field, beside small decks missing noise fields."""
    ex = work / "extract"
    ex.mkdir(parents=True, exist_ok=True)
    common = {"park": "P", "city": "C", "warehouseArea": 1000, "warehouseRent": "EUR 45"}
    # the big deck: 23 records, NO `status` (the real-world shape)
    big = [dict(common, __meta={"source_file": "big_deck.pdf"}) for _ in range(23)]
    ex.joinpath("big_vision.json").write_text(json.dumps(big), encoding="utf-8")
    # a small deck that DOES state status, plus 20 noise fields nothing else carries
    small = dict(common, status="For rent", __meta={"source_file": "small_deck.pdf"})
    for i in range(20):
        small[f"noiseField{i:02d}"] = "yes"
    ex.joinpath("small_vision.json").write_text(json.dumps([small]), encoding="utf-8")
    # a third deck so the noise fields are asymmetric against two sources, not one
    ex.joinpath("third_vision.json").write_text(
        json.dumps([dict(common, status="For rent", __meta={"source_file": "third_deck.pdf"})]),
        encoding="utf-8")


def main() -> int:
    print("capture_symmetry_signal_test - materiality, not just multiplicity")

    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        build(w)
        # a cap SMALLER than the noise, which is the condition that hid the real finding
        r = subprocess.run([sys.executable, str(GR), "capture-symmetry", "--work", str(w),
                            "--max-notes", "5"], capture_output=True, text=True)
        out = r.stdout
        ck(r.returncode == 0 and "STATUS: ALL-PASS" in out,
           "still ADVISORY - the gate reports, it never blocks")

        sig = [l for l in out.splitlines() if "[SIGNAL]" in l]
        note = [l for l in out.splitlines() if "[note]" in l and "more asymmetric" not in l]
        ck(any("`status`" in l for l in sig),
           "the core field missing from the big deck is a SIGNAL")
        ck(any("23 record(s)" in l for l in sig if "`status`" in l),
           "and it states how many records would ship a false 'absent' claim")
        ck(not any("`status`" in l for l in note),
           "it is NOT filed among the ordinary notes")
        first = next(l for l in out.splitlines() if "[SIGNAL]" in l or "[note]" in l)
        ck("[SIGNAL]" in first, "SIGNAL findings print FIRST, above the noise")
        ck(len(note) <= 5, "the noise is still capped by --max-notes")
        ck("more asymmetric field(s)" in out and "capture_symmetry.json" in out,
           "the truncated tail names the file that holds the rest")

        side = json.loads((w / "capture_symmetry.json").read_text(encoding="utf-8"))
        fields = {f["field"] for f in side["findings"]}
        ck(len(side["findings"]) > 5 and "status" in fields,
           "the FULL finding list is on disk, capped output notwithstanding")
        st = next(f for f in side["findings"] if f["field"] == "status")
        ck(st["affected_records"] == 23 and st["core"] and st["signal"],
           "the sidecar carries affected_records / core / signal per finding")
        noise = next(f for f in side["findings"] if f["field"].startswith("noiseField"))
        ck(not noise["signal"],
           "a field only ONE small deck states is not a signal - rarity is not materiality")
        ck(noise["affected_records"] >= st["affected_records"] and noise["weight"] < st["weight"],
           "which is why weight is min(affected, present): raw affected alone ranks the "
           "rarest field top, since everything else 'lacks' it")
        ck(side["findings"].index(st) < side["findings"].index(noise)
           and side["findings"][0]["field"] == "status",
           "so the real finding leads the ranked sidecar, not the noise")

    # a corpus with NO asymmetry must stay silent and clean
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        ex = w / "extract"
        ex.mkdir(parents=True)
        for n in ("a", "b"):
            ex.joinpath(f"{n}_vision.json").write_text(
                json.dumps([{"park": "P", "city": "C", "status": "For rent",
                             "__meta": {"source_file": f"{n}.pdf"}}]), encoding="utf-8")
        r = subprocess.run([sys.executable, str(GR), "capture-symmetry", "--work", str(w)],
                           capture_output=True, text=True)
        ck(r.returncode == 0 and "captured symmetrically" in r.stdout,
           "a symmetric corpus is still a clean single line")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
