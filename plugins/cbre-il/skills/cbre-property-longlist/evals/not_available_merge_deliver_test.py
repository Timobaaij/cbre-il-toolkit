#!/usr/bin/env python3
"""not_available_merge_deliver_test.py - fix 3.10b, merge + deliver halves (2026-09-26 test run).

A reader flags a building the source marks let / sold (`__meta.not_an_option: true`); clarify asks
the broker keep-or-exclude (not_available_exclusion_test.py pins that half). This pins the rest:
  * `merge.apply_not_available`: "exclude" drops a cluster ONLY when EVERY record in it is flagged
    and answered exclude; a cluster with an unflagged tracker record is kept; keep / junk / a
    decline / no answer drop nothing; the filter fails OPEN when it would empty the dataset;
  * a real `merge.py --answers <work>` run: meta.excluded carries the entry with
    `excluded_by: "not_available"`, the question id, and NO `likely_same_as`; the kept cards ship;
  * gate_runner `_accounting_buckets`: the deck whose only record was excluded lands in
    `excluded` (not `unaccounted`), a deck with a kept sibling stays in `records`;
    `_excluded_same_as_shipped` returns [];
  * deliver prints the new heading with the bring-it-back line, and the source-authority heading
    does not list the entry.

Every name is invented. Offline. Run: python evals/not_available_merge_deliver_test.py"""
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
import clarify as CQ  # noqa: E402
import deliver  # noqa: E402
import gate_runner as GR  # noqa: E402
import merge  # noqa: E402

FAILS: list = []
HEAD = "## Options excluded because the source marks them as no longer available"


def ck(ok, label):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILS.append(label)


def rec(park, city, src, area, stype="pdf", flag=False, status=None, unit=None):
    r = {"park": park, "city": city, "country": "ZZ", "developer": "Devco", "warehouseArea": area,
         "areaUnit": "sq m",
         "__meta": {"source_file": src, "source_type": stype, "locator_base": "page 1"}}
    if unit:
        r["unit"] = unit
    if status:
        r["status"] = status
    if flag:
        r["__meta"]["not_an_option"] = True
    return r


def _answer(w, mapping):
    (w / "answers.json").write_text(json.dumps(mapping), encoding="utf-8")
    CQ.ingest_answers(w)


def unit_filter() -> None:
    print("1. apply_not_available (function level)")
    let = rec("Larch Court", "Northtown", "larch.pdf", 20000, flag=True, status="Let")
    ok = rec("Maple Park", "Southville", "maple.pdf", 30000)
    qid = CQ.not_available_qid(let)
    kept, ent = merge.apply_not_available([[let], [ok]], {qid: CQ.NA_EXCLUDE})
    ck(len(kept) == 1 and kept[0][0]["park"] == "Maple Park" and len(ent) == 1,
       "exclude drops the flagged single-record cluster")
    e = ent[0] if ent else {}
    ck(e.get("excluded_by") == "not_available" and e.get("question_ids") == [qid]
       and "likely_same_as" not in e and "'Let'" in e.get("why", "") and e.get("source_files") == ["larch.pdf"],
       f"entry: excluded_by, question id, marker in the why, no likely_same_as ({e})")
    trk = rec("Larch Court", "Northtown", "tracker.xlsx", 20000, stype="xlsx")
    kept, ent = merge.apply_not_available([[let, trk], [ok]], {qid: CQ.NA_EXCLUDE})
    ck(len(kept) == 2 and ent == [], "a cluster with an unflagged tracker record is kept")
    for ans, why in (({qid: CQ.NA_KEEP}, "keep"), ({qid: "hmm, not sure"}, "junk"), ({}, "no answer")):
        kept, ent = merge.apply_not_available([[let], [ok]], ans)
        ck(len(kept) == 2 and ent == [], f"{why}: nothing dropped")
    kept, ent = merge.apply_not_available([[let], [ok]], {qid: CQ.NA_EXCLUDE}, declined=[qid])
    ck(len(kept) == 2 and ent == [], "declined: nothing dropped")
    kept, ent = merge.apply_not_available([[let]], {qid: CQ.NA_EXCLUDE})
    ck(len(kept) == 1 and ent == [], "fails OPEN when the filter would empty the dataset")
    kept, ent = merge.apply_not_available([[ok]], {})
    ck(kept == [[ok]] and ent == [], "an unflagged corpus is untouched")


def end_to_end() -> None:
    print("2. merge.py --answers, input accounting, deliver")
    w = Path(tempfile.mkdtemp(prefix="cbre_na_e2e_"))
    (w / "inputs").mkdir()
    recs = [rec("Larch Court", "Northtown", "larch.pdf", 20000, flag=True, status="Let"),
            rec("Oak Row", "Eastham", "oak_scheme.pdf", 12000, flag=True, status="Sold", unit="Unit 1"),
            rec("Oak Row", "Eastham", "oak_scheme.pdf", 18000, unit="Unit 2"),
            rec("Maple Park", "Southville", "maple.pdf", 30000)]
    qs = CQ.not_available_questions(recs)
    CQ.emit(w, CQ.pending(w, qs))
    _answer(w, {q["id"]: CQ.NA_EXCLUDE for q in qs})
    (w / "r.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(w / "r.json"),
                        "--source-dir", str(w / "inputs"), "--out", str(w / "canonical.json"),
                        "--ledger", str(w / "source_ledger.csv"), "--answers", str(w)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (p.stderr or "")
    if not (w / "canonical.json").exists():
        ck(False, f"merge completes: {ascii(out[-300:])}")
        return
    canon = json.loads((w / "canonical.json").read_text(encoding="utf-8"))
    import normalize as N
    parks = sorted(f"{q.get('park')} {'' if N.looks_unknown(q.get('unit')) else q.get('unit')}".strip()
                   for q in canon["properties"])
    ck(parks == ["Maple Park", "Oak Row Unit 2"], f"the two let/sold buildings are excluded ({parks})")
    ex = (canon.get("meta") or {}).get("excluded") or []
    ck(len(ex) == 2 and all(e.get("excluded_by") == "not_available" and e.get("question_ids")
                            and "likely_same_as" not in e for e in ex),
       f"meta.excluded: two not_available entries, question ids, no likely_same_as ({len(ex)})")
    ck("the source marks them no longer available" in out, "merge prints one line saying so")
    (w / "inventory.json").write_text(json.dumps(
        {"clusters": [{"files": ["larch.pdf", "oak_scheme.pdf", "maple.pdf"]}]}), encoding="utf-8")
    (w / "unreadable.json").write_text("[]", encoding="utf-8")
    b = GR._accounting_buckets(w, w / "canonical.json")
    ck("larch.pdf" in (b.get("excluded") or []) and "larch.pdf" not in (b.get("unaccounted") or []),
       f"the deck whose only record was excluded is in `excluded` ({ {k: v for k, v in b.items() if v} })")
    ck("oak_scheme.pdf" in (b.get("records") or []) and "oak_scheme.pdf" not in (b.get("excluded") or []),
       "the deck with a kept sibling stays in `records`")
    ck(GR._excluded_same_as_shipped(w / "canonical.json") == [],
       "_excluded_same_as_shipped reads no let building as a lost card")
    md = deliver.gaps_report(canon, "t", w)
    sec = md.split(HEAD, 1)[1].split("\n## ", 1)[0] if HEAD in md else ""
    ck(bool(sec) and "Larch Court" in sec and "'Let'" in sec and "found in: larch.pdf" in sec
       and "To bring it back, answer that question 'keep ...' and re-run." in sec,
       "deliver prints the new heading with the entry and the bring-it-back line")
    ck("## Options excluded (not evidenced by your guiding source)" not in md,
       "the source-authority heading does not list a let/sold exclusion")
    mixed = dict(canon)
    mixed["meta"] = dict(canon["meta"])
    mixed["meta"]["excluded"] = list(ex) + [{"name": "Auth Park", "source_files": ["auth.pdf"],
                                             "why": "not evidenced by the tracker"}]
    md2 = deliver.gaps_report(mixed, "t", w)
    auth = md2.split("## Options excluded (not evidenced by your guiding source)", 1)
    ck(HEAD in md2 and len(auth) == 2 and "Auth Park" in auth[1].split("\n## ", 1)[0]
       and "Larch Court" not in auth[1].split("\n## ", 1)[0],
       "a legacy entry (no excluded_by) keeps the source-authority heading; the let entry does not join it")


def main() -> int:
    unit_filter()
    end_to_end()
    print(f"\n{'PASS' if not FAILS else 'FAIL'} not_available_merge_deliver_test ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
