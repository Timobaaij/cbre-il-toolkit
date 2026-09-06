#!/usr/bin/env python3
"""d15_epc_token_test.py - the EPC gate judges the RATING TOKEN, not the words around it. (D15)

THE DEFECT. `_pick_gate_verdict`'s epc band was anchored `^...$` over the WHOLE string, so it
accepted a bare "A+" or "Target EPC A" and nothing else. A deck that stated its EPC three times in
plain prose had the composite string struck to `tbd` on BOTH units it produced, with a conflict
note calling the value implausible, while the same band passed a bare "A+" on three other
properties in the same run. It was rejecting the surrounding words, not the rating. A gate that
fires STRIKES the field (`out[field] = "tbd"`), so this was a stated datum withdrawn from a client
card by a parse defect.

WHAT THIS PINS, and why the third item matters most:
  1. Every value that passed before still passes: "A+", "A", "Target A", "Target EPC A", "EPC A+".
  2. A composite prose string CONTAINING a rating token now passes: the Panattoni shape ("The
     building will achieve an EPC rating of A. Targeting EPC A on completion."), "EPC A+ rated",
     "Energy Performance Certificate rating B", "EPC: A". Against the old anchored band each of
     these returns "fail", so a regression to `^...$` trips every one of them.
  2b. A real certificate prints a SCORE AND a BAND, and BOTH orderings pass. The filler chain
     between the anchor word and the band accepted only WORDS, so a numeric asset rating broke it:
     "EPC 85 (B)", "EPC: 82 (B)", "Energy Performance Asset Rating: 85 (D)" and friends were struck
     to tbd, while "EPC B (85)" and "EPC score 85, band B" passed - the same datum off the same
     certificate, decided by word order. The adversarial half of this lives in item 3: admitting a
     score must not admit a STREET NUMBER, so the score cannot cross a full stop or a newline on
     either side ("EPC. 12 A Smith Street, Corby" must fail), and four digits are a year, not a
     rating ("EPC 2023 A" must fail).
  3. A string with NO rating token still FAILS: "EPC assessment shows a modern building", "rating
     of a modern unit" (a lower-case indefinite article is not a band), "Grade A specification" (a
     building spec, not an energy rating), "Energy efficient design", a BREEAM word. A gate that
     became a rubber stamp would let a description ship as a certificate AND would let the mirror
     case (a BREEAM grade misfiled under epc) pass unjudged, which is a worse defect than the one
     being fixed. Both directions are asserted with the same verdict function.
  4. The sibling `breeam` gate is UNCHANGED: it passes on containing a grade word ("Target BREEAM
     Excellent", "Very Good", "Outstanding (targeted)") and fails on an EPC letter or a non-grade.
  5. `_route_certifications` (B5) leaves the epc prose where it is (no BREEAM word in it), still
     moves a misfiled "A+" from breeam to epc, does not churn a clean pair, and - the second and
     more damaging consumer of the same expression - KEEPS a score-and-band value under `epc`
     instead of re-filing it wholesale ("BREEAM Excellent. EPC 85 (B)." used to leave epc empty and
     ship a string reading "EPC 85 (B)" under BREEAM).
  6. The real `merge.main`: a prose epc SHIPS on the property (not tbd) with no plausibility note;
     a bare "A+" ships; a no-rating string is struck to tbd WITH the T1-worded note on
     `meta.conflicts`, so the strike path is proven live rather than inferred from the verdict.

Sits beside `evals/epc_breeam_test.py` (B5: an EPC never ships as a BREEAM grade, the routing)
and `evals/pick_gate_test.py` (B3: three-state verdicts; it covers only the bare bands for epc).
Offline: pure verdicts, the router, and the real merge via subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import merge  # noqa: E402

FAILS: list[str] = []
V = merge._pick_gate_verdict

PANATTONI = "The building will achieve an EPC rating of A. Targeting EPC A on completion."
NO_RATING = "EPC assessment shows a modern building"


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _r(src, park, **kw):
    r = {"park": park, "city": "Corby", "country": "GB", "developer": "Dev",
         "warehouseArea": 200000, "areaUnit": "sq ft",
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": "page 1"}}
    r.update(kw)
    return r


def _run_merge(recs: list[dict], tag: str):
    d = Path(tempfile.mkdtemp(prefix=f"cbre_d15_{tag}_"))
    (d / "inputs").mkdir()
    (d / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (p.stderr or "")
    if not (d / "c.json").exists():
        return None, out
    return json.loads((d / "c.json").read_text(encoding="utf-8")), out


def main() -> int:
    print("== 1. every value the OLD anchored band passed still passes ==")
    for s in ("A+", "A", "B", "G", "Target A", "Target EPC A", "EPC A+", "targeting A"):
        ck(V("epc", s) == "pass", f"epc {ascii(s)} -> pass ({V('epc', s)})")

    print()
    print("== 2. a composite prose string CONTAINING a rating token passes (the old band failed all of these) ==")
    for s in (PANATTONI,
              "EPC A+ rated",
              "Energy Performance Certificate rating B",
              "EPC: A",
              "EPC rating of A",
              "Targeting EPC A on completion",
              "The unit is EPC A rated with a 15 m clear height",
              "EPC A (2023)",
              "Energy performance: B"):
        ck(V("epc", s) == "pass", f"epc {ascii(s)} -> pass ({V('epc', s)})")

    print()
    print("== 2b. a real certificate prints a SCORE AND a BAND - both orderings pass ==")
    # D15 follow-up. The filler chain between the anchor word and the band accepted only WORDS, so
    # a numeric asset rating broke it: every string in the first group below returned "fail" and was
    # STRUCK to tbd with a note against the source, while the same datum written the other way round
    # (second group) passed. Same certificate, same rating, opposite verdicts on word order alone.
    for s in ("EPC 85 (B)",
              "EPC 85 B",
              "EPC: 82 (B)",
              "EPC rating 85 (B)",
              "Energy Performance Certificate: 85 (B)",
              "Energy Performance Asset Rating: 85 (D)",
              # these two always passed; they are kept so a regression that fixes one ordering by
              # breaking the other is caught here rather than in a live run
              "EPC B (85)",
              "EPC score 85, band B"):
        ck(V("epc", s) == "pass", f"epc {ascii(s)} -> pass ({V('epc', s)})")

    print()
    print("== 3. a string with NO rating token still FAILS (the gate must not become a rubber stamp) ==")
    for s in (NO_RATING,
              "EPC assessment shows a modern building",
              "rating of a modern unit",
              "Grade A specification",
              "Energy efficient design throughout",
              "EPC to be confirmed on completion",
              "Excellent",
              "Very Good",
              "Target: Outstanding",
              "Energy performance: H",
              "garble",
              # D15 follow-up adversarials. Admitting a numeric score must NOT admit a street
              # number: the score run cannot cross a full stop or a newline on EITHER side of the
              # digits. A one-sided guard (score-to-band only) passes all three of these address
              # strings as an EPC band A, which is why the two-sided form is the one in merge.py.
              "EPC. 12 A Smith Street, Corby",
              "EPC\n12A Smith Street",
              "EPC rating.\n12 A Smith Street",
              # a four-digit number is a YEAR, not an asset rating (ratings run 0 to ~150 plus)
              "EPC 2023 A",
              # no anchor word at all: a floor area next to a building SPEC grade is not a rating
              "85,000 sq ft, Grade A",
              # the anchor and the score are real, but the band letter is a new sentence's first
              # word - the full stop is exactly what the guard exists to refuse
              "EPC rating of 85. A modern building of 250,000 sq ft."):
        ck(V("epc", s) == "fail", f"epc {ascii(s)} -> fail ({V('epc', s)})")
    ck(V("epc", "EPC assessment shows a modern building") != V("epc", PANATTONI),
       "the two prose strings get DIFFERENT verdicts: the words are not what is judged, the token is")

    print()
    print("== 4. the sibling breeam gate is unchanged ==")
    for s in ("Excellent", "Very Good", "Target BREEAM Excellent", "Outstanding (targeted)", "Pass"):
        ck(V("breeam", s) == "pass", f"breeam {ascii(s)} -> pass ({V('breeam', s)})")
    for s in ("A+", "EPC A", "garble", "Grade A specification"):
        ck(V("breeam", s) == "fail", f"breeam {ascii(s)} -> fail ({V('breeam', s)})")

    print()
    print("== 5. the B5 router leaves the prose alone and still re-files a misfiled band ==")
    rec = {"epc": PANATTONI, "__meta": {}}
    merge._route_certifications(rec)
    ck(rec.get("epc") == PANATTONI and "breeam" not in rec,
       "the Panattoni prose stays under epc, unchanged")
    rec = {"breeam": "A+", "__meta": {}}
    merge._route_certifications(rec)
    ck(rec.get("epc") == "A+" and not rec.get("breeam"),
       "a bare A+ misfiled under breeam still moves to epc")
    # D15 follow-up: the router SHARES `_EPC_GATE_RX`, so widening the gate widens this decision.
    # Measured before the fix, this composite re-filed WHOLESALE - epc came back None and breeam
    # came back holding a string reading "EPC 85 (B)". A stated EPC rating was deleted from the
    # card and shipped under the wrong certificate. The value carries a rating of its own, so it
    # must STAY under epc however many BREEAM words sit beside it.
    both = {"epc": "BREEAM Excellent. EPC 85 (B).", "__meta": {}}
    merge._route_certifications(both)
    ck(both.get("epc") == "BREEAM Excellent. EPC 85 (B)." and not both.get("breeam"),
       f"a score-and-band EPC keeps its value under epc, not re-filed to breeam "
       f"(epc={ascii(str(both.get('epc')))[:44]}, breeam={ascii(str(both.get('breeam')))})")

    clean = {"breeam": "Excellent", "epc": "A+", "__meta": {}}
    after = dict(clean)
    merge._route_certifications(after)
    ck(after == clean, "a clean pair is untouched")
    # informational only: a prose epc that ALSO carries a BREEAM grade word is the router's B5
    # mirror case; recorded here so a reader of this eval knows where the two rules meet
    mixed = {"epc": "EPC A. BREEAM Excellent.", "__meta": {}}
    merge._route_certifications(mixed)
    print(f"  [INFO] an epc prose string carrying a BREEAM word routes as: {ascii(str({k: v for k, v in mixed.items() if k != '__meta'}))}")

    print()
    print("== 6. the real merge: prose ships, bare ships, no-rating is struck WITH its note ==")
    # four DISTINCT properties: different towns, names and areas, or the deduper clusters two of
    # them into one and the assertions read the wrong record (it did, on a first draft)
    recs = [
        _r("Panattoni.pdf", "Panattoni Unit 1", city="Corby", warehouseArea=200000, epc=PANATTONI),
        _r("Bare.pdf", "Alpha 150", city="Daventry", warehouseArea=150000, epc="A+"),
        _r("NoRating.pdf", "Beta 120", city="Rugby", warehouseArea=120000, epc=NO_RATING),
        _r("Breeam.pdf", "Gamma 90", city="Northampton", warehouseArea=90000,
           breeam="Target BREEAM Excellent", epc="Target EPC A"),
    ]
    canon, out = _run_merge(recs, "live")
    ck(canon is not None, f"merge completes {ascii(out[-200:]) if canon is None else ''}")
    if canon is not None:
        props = canon.get("properties") or []
        ck(len(props) == 4, f"the four fixture records ship as four properties ({len(props)})")
        by = {q.get("park"): q for q in props}
        conflicts = (canon.get("meta") or {}).get("conflicts") or []

        def _note_for(pid, field):
            return [c for c in conflicts if str(c).startswith(f"id {pid} {field}:")]

        q = by.get("Panattoni Unit 1") or {}
        ck(q.get("epc") == PANATTONI,
           f"Panattoni: the prose epc SHIPS, not tbd ({ascii(str(q.get('epc')))[:60]})")
        ck(not _note_for(q.get("id"), "epc"),
           "Panattoni: no plausibility note against a value the source plainly prints")

        q = by.get("Alpha 150") or {}
        ck(q.get("epc") == "A+", f"Bare: A+ ships ({ascii(str(q.get('epc')))})")

        q = by.get("Beta 120") or {}
        ck(q.get("epc") == "tbd", f"No Rating: struck to tbd ({ascii(str(q.get('epc')))})")
        notes = _note_for(q.get("id"), "epc")
        ck(len(notes) == 1 and "plausibility band" in notes[0] and NO_RATING in notes[0],
           f"No Rating: ONE conflicts note naming the parsed value and the band ({ascii(notes[0][:90]) if notes else 'none'})")
        ck(bool(notes) and "implausible" not in notes[0].lower(),
           "No Rating: ...worded per T1 (names the PARSED value, never accuses the source)")

        # a value ALREADY filed under epc keeps its wording: the router strips the redundant
        # "EPC" token only when it MOVES a value out of breeam (epc_breeam_test pins that path)
        q = by.get("Gamma 90") or {}
        ck(q.get("breeam") == "Target BREEAM Excellent" and q.get("epc") == "Target EPC A",
           f"Gamma 90: both certificates ship side by side ({ascii(str(q.get('breeam')))}, {ascii(str(q.get('epc')))})")
        ck(not _note_for(q.get("id"), "breeam") and not _note_for(q.get("id"), "epc"),
           "Gamma 90: neither gate fired")

    print()
    if FAILS:
        print(f"D15 EPC TOKEN TEST: FAIL ({len(FAILS)})")
        return 1
    print("D15 EPC TOKEN TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
