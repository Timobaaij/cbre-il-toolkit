#!/usr/bin/env python3
"""epc_breeam_test.py - an EPC never ships as a BREEAM grade. (B5)

THE DEFECT. `extract_xlsx.COLUMN_MAP` listed "epc rating" and "epc" as aliases of `breeam`.
BREEAM grades sustainability design (Pass / Good / Very Good / Excellent / Outstanding); an EPC
grades energy efficiency on a letter band (A+ / A / B). On a tracker carrying BOTH columns the
consequence was row-dependent and therefore nearly invisible: rows whose real BREEAM cell was
populated looked perfect, and the ONE row whose BREEAM cell was empty silently drew the EPC
value instead - so the defect appeared exactly where the true value was unknown and there was
nothing to compare against. A live run shipped "BREEAM A+" (not a grade that exists) to a
client card, to the compare table and to the client Excel, with a High-confidence Source Ledger
row citing the empty BREEAM cell. Both independent LLM column-map passes had refused that
binding in writing; the deterministic dictionary's backfill overrode them.

WHAT THIS PINS, at each layer the value passes through:
  1. the dictionary no longer aliases epc -> breeam, and `epc` is its own column field;
  2. the NEGATIVE table hard-vetoes the cross-binding in BOTH directions, so even an explicit
     (LLM) column map naming an EPC column as `breeam` is corrected rather than honoured;
  3. `merge._route_certifications` re-files a value that arrives misfiled anyway - which is what
     makes the fix retroactive for warm work dirs and cached interpretation records, with the
     provenance key moving WITH the value so the ledger follows;
  4. `epc` is a declared canonical field (so the override path accepts it - it did not before);
  5. the built chrome labels it EPC and does not deny it, so it auto-shows as Additional Details
     while `breeam` keeps its own curated Certification row.

Offline. Drives the real extractor, the real router and a real build.
"""
from __future__ import annotations
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import build_dashboard  # noqa: E402
import extract_xlsx  # noqa: E402
import merge  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

# the live shape that produced the defect: BOTH certificate columns, and the LAST row's BREEAM
# cell deliberately EMPTY while its EPC cell is populated.
HEADERS = ["Marketing Name", "Town", "Size (sq ft)", "Size Unit",
           "EPC rating", "BREEAM rating"]
ROWS = [
    ["Alpha 200", "Corby", 200000, "GIA", "A+", "Excellent"],
    ["Beta 150", "Corby", 150000, "GIA", "A", "Very Good"],
    ["Gamma 130", "Corby", 130000, "GIA", "A+", None],      # <- the silent-corruption row
]


def _sheet(path: Path) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Building Data"
    ws.append(HEADERS)
    for r in ROWS:
        ws.append(r)
    wb.save(path)


def _canon(props):
    meta = {"client": "EpcCo", "units": {"area": "sq ft"},
            "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "", "lede": "",
                     "footer_copyright": ""}}
    base = {"country": "GB", "developer": "D", "city": "Corby", "status": "Available",
            "photo": PX, "gallery": [PX], "lat": 52.5, "lng": -0.7, "areaUnit": "sq ft",
            "motorway": "A14 11 miles"}
    return {"meta": meta, "pois": [], "regions": {},
            "properties": [dict(base, **p) for p in props]}


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---- 1. the dictionary ------------------------------------------------- #
    breeam_aliases = {a.lower() for a in extract_xlsx.COLUMN_MAP.get("breeam", [])}
    ck(not (breeam_aliases & {"epc", "epc rating", "epc band"}),
       f"breeam claims no EPC alias {ascii(str(sorted(breeam_aliases)))}")
    ck("epc" in extract_xlsx.COLUMN_MAP, "epc is its own column field")
    ck("epc rating" in {a.lower() for a in extract_xlsx.COLUMN_MAP.get("epc", [])},
       "an 'EPC rating' header binds to epc")

    # ---- 2. the NEGATIVE hard veto, both directions ------------------------ #
    nb, ne = extract_xlsx.NEGATIVE.get("breeam"), extract_xlsx.NEGATIVE.get("epc")
    ck(bool(nb and nb.search("EPC rating")), "an EPC header is hard-vetoed for breeam")
    ck(bool(nb) and not nb.search("BREEAM rating"),
       "...while a real BREEAM header is still allowed")
    ck(bool(ne and ne.search("BREEAM rating")), "a BREEAM header is hard-vetoed for epc")

    # ---- 3. the real extractor on the real defect shape -------------------- #
    d = Path(tempfile.mkdtemp(prefix="cbre_epc_"))
    xp = d / "Building_Data.xlsx"
    _sheet(xp)
    recs = extract_xlsx.detect_and_extract(xp, region="Corby", country="GB")["records"]
    ck(len(recs) == 3, f"three rows extracted ({len(recs)})")
    by = {str(r.get("park", "")).split()[0]: r for r in recs}

    ck(by.get("Alpha", {}).get("breeam") == "Excellent", "a real BREEAM grade still lands")
    ck(str(by.get("Alpha", {}).get("epc", "")).upper() == "A+",
       "...alongside its own EPC band, in epc")
    g = by.get("Gamma", {})
    ck(str(g.get("breeam", "")).strip().lower() in {"", "tbd", "none", "null"},
       f"the EMPTY-BREEAM row leaves breeam unknown, not backfilled from EPC "
       f"(got {ascii(str(g.get('breeam')))})")
    ck(str(g.get("epc", "")).upper() == "A+",
       f"...and its EPC band is preserved in epc (got {ascii(str(g.get('epc')))})")

    # ---- 4. the retroactive router ----------------------------------------- #
    # a legacy/interpreted record that already conflated them self-corrects
    legacy = {"park": "Legacy", "breeam": "EPC A+",
              "__meta": {"source_file": "deck.pdf", "page_no": 1,
                         "prov": {"breeam": "page 6 (text interpretation)"}}}
    merge._route_certifications(legacy)
    ck(str(legacy.get("epc", "")).upper() == "A+",
       f"a misfiled 'EPC A+' moves to epc, redundant EPC token dropped "
       f"(got {ascii(str(legacy.get('epc')))})")
    ck("breeam" not in legacy or legacy.get("breeam") in (None, ""),
       "...and never remains under breeam")
    pv = legacy["__meta"]["prov"]
    ck("epc" in pv and "breeam" not in pv,
       "the provenance key moves WITH the value so the ledger row follows the field")
    ck("page 6" in pv.get("epc", "") and "re-filed" in pv.get("epc", ""),
       f"...keeping its locator and stating the re-route {ascii(pv.get('epc', ''))}")

    # a 'Target EPC A' keeps Target, drops only the redundant EPC token
    t = {"breeam": "Target EPC A", "__meta": {}}
    merge._route_certifications(t)
    ck(t.get("epc") == "Target A", f"'Target EPC A' -> {ascii(str(t.get('epc')))}")

    # the mirror: a BREEAM word filed under epc goes the other way
    m = {"epc": "Very Good", "__meta": {}}
    merge._route_certifications(m)
    ck(m.get("breeam") == "Very Good" and not m.get("epc"),
       "a BREEAM grade misfiled under epc moves to breeam")

    # a genuine pair is left ALONE - the router must not churn clean data
    clean = {"breeam": "Excellent", "epc": "A+", "__meta": {}}
    merge._route_certifications(dict(clean))
    after = dict(clean)
    merge._route_certifications(after)
    ck(after == clean, f"a correct pair is untouched {ascii(str(after))}")

    # destination occupied by a DIFFERENT value: the band is preserved for audit, never shown,
    # and breeam does not keep a grade that cannot exist
    occ = {"breeam": "A+", "epc": "B", "__meta": {}}
    merge._route_certifications(occ)
    ck(not occ.get("breeam"), "an impossible breeam band never survives, even if epc is taken")
    ck(occ["__meta"].get("offspec", {}).get("breeam_misfiled") == "A+",
       "...it is preserved in __meta.offspec for audit rather than dropped")
    ck(occ.get("epc") == "B", "...and the existing epc value is not clobbered")

    # ---- 5. schema + chrome ------------------------------------------------ #
    cs = json.loads((ROOT / "templates" / "canonical.schema.json")
                    .read_text(encoding="utf-8"))
    declared = ((cs.get("$defs") or {}).get("property") or {}).get("properties") or {}
    ck("epc" in declared, "epc is a DECLARED canonical field (so overrides may set it)")
    rs = json.loads((ROOT / "templates" / "record_schema.json").read_text(encoding="utf-8"))
    ck("epc" in (rs.get("properties") or {}),
       "epc is in the record schema the interpretation agent is handed")

    cp = d / "c.json"
    cp.write_text(json.dumps(_canon([
        dict(id=1, park="Alpha 200", warehouseArea=200000, breeam="Excellent", epc="A+"),
        dict(id=2, park="Gamma 130", warehouseArea=130000, breeam="tbd", epc="A+"),
    ])), encoding="utf-8")
    hp = d / "b.html"
    build_dashboard.build(cp, hp)
    h = hp.read_text(encoding="utf-8")

    ck("row(T('cmp_certification'), certStr(p))" in h,
       "the modal gives epc a curated Certification row")
    ck("certName(p.breeam" in h or "certName(p.breeam, " in h,
       "the Certification row renders BREEAM through certName")
    ck("certName(p.epc" in h or "certName(p.epc, " in h,
       "...and EPC alongside it, comma-separated")
    ck('"epc":"A+"' in h.replace(" ", ""), "the epc value reaches the built PROPS block")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
