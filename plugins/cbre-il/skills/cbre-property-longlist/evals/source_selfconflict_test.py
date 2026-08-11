#!/usr/bin/env python3
"""source_selfconflict_test.py - a source that contradicts ITSELF reaches the broker.

Every conflict path in merge compares one record against ANOTHER, so a single page that
disagrees with itself was invisible to the whole machinery. Live on a Spanish run: one brochure
page whose SUPERFICIES schedule totalled 180 loading docks while its own CARACTERISTICAS block
said 170, and another whose schedule totalled 50,843 m2 under a DESCRIPCION headline of
53,564 m2. The extractor saw both figures in each case and could only mention the loser in prose
inside its `prov` locator - so `conflict_note` stayed empty, `meta.conflicts` never carried it,
and the Gaps Report's "Source conflicts" section told the broker there was nothing to settle.
Two independent reviewers raised it as a blocking honesty defect.

An extractor may now declare `__meta.source_conflicts = {field: note}`. This pins that it lands
in the SAME channel as every cross-source conflict, that it never changes the chosen value, that
a cross-source note is not displaced by it, and that a record without the key is byte-identical
to before.

Drives real merge.main and real deliver.gaps_report. Offline."""
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


def _r(src, **kw):
    meta = kw.pop("meta", {})
    r = {"city": "Corby", "country": "GB",
         "__meta": {"source_file": src, "source_type": "pdf", "locator_base": "page 1", **meta}}
    r.update(kw)
    return r


def _merge(d: Path, recs: list, tag: str):
    (d / f"r_{tag}.json").write_text(json.dumps(recs), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HELPERS / "merge.py"),
                        "--records", str(d / f"r_{tag}.json"), "--source-dir", str(d / "inputs"),
                        "--out", str(d / f"c_{tag}.json"), "--ledger", str(d / f"l_{tag}.csv")],
                       capture_output=True, text=True, errors="replace")
    out = d / f"c_{tag}.json"
    return (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None,
            (d / f"l_{tag}.csv"), (p.stdout + p.stderr))


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_ssc_"))
    (d / "inputs").mkdir()

    NOTE = ("the source disagrees with itself: the SUPERFICIES schedule totals 180 docks "
            "(60+60+60) while the CARACTERISTICAS block on the same page states 170")
    # the SECOND shape the same channel must carry honestly - not a self-contradiction at all,
    # so no prefix may be imposed on the note by the pipeline
    RANGE_NOTE = ("the deck quotes an asking rent RANGE of 3.50 - 3.75 per sq m per month; the "
                  "card ships the annualised LOW end")

    # ---- 1. the declared self-conflict reaches canonical, the ledger and the Gaps Report
    canon, ledger, log = _merge(d, [
        _r("Selfcontra.pdf", park="Alpha Park", developer="Prologis",
           warehouseArea=50843, areaUnit="sq m", loadingDocks=180,
           meta={"source_conflicts": {"loadingDocks": NOTE}}),
    ], "self")
    ck(canon is not None, f"merge completes {ascii(log[-160:])}")
    if canon is None:
        print(f"\nSOURCE SELF-CONFLICT TEST: FAIL ({len(fails)})")
        return 1

    prop = canon["properties"][0]
    ck(str(prop.get("loadingDocks")) == "180",
       f"the CHOSEN value is untouched - a note never edits the datum ({prop.get('loadingDocks')})")
    ck(not any(k.startswith("source_conflict") for k in prop),
       "the declaration does not leak onto the property as a displayable field")

    conflicts = (canon.get("meta") or {}).get("conflicts") or []
    hit = [c for c in conflicts if "loadingDocks" in str(c)]
    ck(bool(hit), f"meta.conflicts carries it ({len(conflicts)} conflict line(s))")
    ck(any("disagrees with itself" in str(c) for c in hit),
       "the line says the SOURCE disagrees with itself, not that a record was discarded")
    ck(any("170" in str(c) and "180" in str(c) for c in hit),
       "both figures survive into the line the broker reads")
    ck(any("Selfcontra.pdf" in str(c) for c in hit), "the line names the file")
    # meta.conflicts lines are addressed as "id <n> <field>: <note>"; nothing may sit between
    # that address and the extractor's own words
    ck(all(str(c).split(": ", 1)[-1].startswith(NOTE) for c in hit),
       "the note is printed VERBATIM - the pipeline imposes no prefix of its own")

    rows = [r for r in ledger.read_text(encoding="utf-8", errors="replace").splitlines()
            if "loadingDocks" in r]
    ck(any("disagrees with itself" in r for r in rows),
       f"the ledger's conflict_note carries it too ({len(rows)} loadingDocks row(s))")

    text = D.gaps_report(canon, "Eval")
    ck("disagrees with itself" in text, "the Gaps Report prints it for the broker")

    # ---- 2. a cross-source conflict is NOT displaced by a self-conflict on the same field
    canon2, ledger2, _ = _merge(d, [
        _r("A.pdf", park="Beta Park", developer="Prologis", warehouseArea=40000,
           areaUnit="sq m", loadingDocks=180, meta={"source_conflicts": {"loadingDocks": NOTE}}),
        _r("B.pdf", park="Beta Park", developer="Prologis", warehouseArea=40000,
           areaUnit="sq m", loadingDocks=90),
    ], "both")
    ck(canon2 is not None, "merge completes on the two-source cluster")
    if canon2 is not None:
        c2 = [str(c) for c in ((canon2.get("meta") or {}).get("conflicts") or [])
              if "loadingDocks" in str(c)]
        ck(any("discarded" in c for c in c2),
           "the cross-source discard note still occupies the slot")
        ck(any("disagrees with itself" in c for c in c2),
           "and the self-conflict is appended rather than dropped")

    # ---- 2b. a NARROWED RANGE is the other shape this channel carries, and it must not be
    # described as a self-contradiction. Nothing in the source disagrees; the DELIVERABLE is
    # narrower than the quote, which the broker still has to know before quoting a rent.
    canon2b, _, _ = _merge(d, [
        _r("Range.pdf", park="Epsilon Park", developer="Prologis", warehouseArea=40000,
           areaUnit="sq m", warehouseRentVal=42.0, rentUnit="EUR/sq m/yr",
           meta={"source_conflicts": {"warehouseRentVal": RANGE_NOTE}}),
    ], "range")
    c2b = [str(c) for c in ((canon2b or {}).get("meta", {}).get("conflicts") or [])
           if "warehouseRentVal" in str(c)]
    ck(bool(c2b), "a narrowed-range disclosure reaches meta.conflicts")
    ck(all("disagrees with itself" not in c for c in c2b),
       "and is NOT mislabelled as a self-contradiction - the note stands as written")
    ck(any("3.50" in c and "3.75" in c for c in c2b),
       "the discarded top of the range survives into the broker's line")

    # ---- 3. no declaration -> byte-identical to the previous behaviour
    plain = [_r("Plain.pdf", park="Gamma Park", developer="Prologis",
                warehouseArea=40000, areaUnit="sq m", loadingDocks=180)]
    canon3, _, _ = _merge(d, plain, "plain")
    ck(canon3 is not None and not ((canon3.get("meta") or {}).get("conflicts") or []),
       "a record with NO declaration produces no conflict line at all")

    # ---- 4. a note on a field the property does not carry is ignored, never invented
    canon4, _, _ = _merge(d, [
        _r("Ghost.pdf", park="Delta Park", developer="Prologis", warehouseArea=40000,
           areaUnit="sq m", meta={"source_conflicts": {"loadingDocks": NOTE}}),
    ], "ghost")
    ck(canon4 is not None
       and not [c for c in ((canon4.get("meta") or {}).get("conflicts") or [])
                if "loadingDocks" in str(c)],
       "a note about a field the record never set is dropped - it cannot conjure a field")

    if fails:
        print(f"\nSOURCE SELF-CONFLICT TEST: FAIL ({len(fails)})")
        return 1
    print("\nSOURCE SELF-CONFLICT TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
