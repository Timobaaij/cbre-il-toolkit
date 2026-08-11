#!/usr/bin/env python3
"""relpath_test.py - the unambiguous source identity exists before anything consumes it. (B43 ph1)

Every extractor writes __meta.source_file as a bare BASENAME - deliberately, since an extractor
is root-blind - so `Site A/photos.pdf` and `Site B/photos.pdf` are indistinguishable downstream.
B13 made the CHOICE between them deterministic, which is not the same as correct.

PHASE 1 IS ADDITIVE AND CONSUMES NOTHING. `source_file` is frozen as the documented,
client-visible ledger contract (it legitimately holds an email subject), `source_relpath` is the
new unambiguous identity, and `_common.source_key()` falls back to the basename - so this pass
changes NO output byte. That is the point: prove the stamp EXISTS before anything depends on it,
rather than discovering a dead join after the fact for the fourth time. Phases 2-4 are B45.

The byte-identity assertion is therefore the load-bearing one here. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import run as RUN  # noqa: E402


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # --- the accessor -----------------------------------------------------------
    ck(hasattr(C, "source_key"), "_common.source_key exists")
    ck(C.source_key({"source_file": "photos.pdf"}) == "photos.pdf",
       "with no relpath it returns the basename EXACTLY (so no caller changes behaviour)")
    ck(C.source_key({"source_file": "photos.pdf", "source_relpath": "Site A/photos.pdf"})
       == "Site A/photos.pdf", "with a relpath it PREFERS the unambiguous identity")
    ck(C.source_key({}) == "" and C.source_key(None) == "",
       "an empty meta is empty, never a crash")
    # the case the whole item exists for
    a = {"source_file": "photos.pdf", "source_relpath": "Site A/photos.pdf"}
    b = {"source_file": "photos.pdf", "source_relpath": "Site B/photos.pdf"}
    ck(C.source_key(a) != C.source_key(b),
       "two same-named inputs in different folders are DISTINGUISHABLE")
    ck(a["source_file"] == b["source_file"],
       "...while source_file stays identical - the ledger contract is untouched")

    # --- the stamp --------------------------------------------------------------
    ck(hasattr(RUN, "_stamp_source_relpath"), "run._stamp_source_relpath exists")
    recs = [{"park": "A", "__meta": {"source_file": "t.xlsx"}},
            {"park": "B", "__meta": {"source_file": "t.xlsx"}}]
    n = RUN._stamp_source_relpath(recs, "Corby/t.xlsx")
    ck(n == 2, f"every record in the file is stamped ({n})")
    ck(all(r["__meta"]["source_relpath"] == "Corby/t.xlsx" for r in recs),
       "with the POSIX relpath")
    ck(all(r["__meta"]["source_file"] == "t.xlsx" for r in recs),
       "and source_file is NOT rewritten")
    win = [{"__meta": {}}]
    RUN._stamp_source_relpath(win, "Corby\\sub\\t.xlsx")
    ck(win[0]["__meta"]["source_relpath"] == "Corby/sub/t.xlsx",
       "a Windows separator is normalised, so the key is machine-independent")
    ck(RUN._stamp_source_relpath([{"__meta": {}}], "") == 0, "an empty relpath stamps nothing")
    ck(RUN._stamp_source_relpath(None, "x") == 0, "no records is not a crash")

    # --- WIRING: it is called where run.py knows the pairing --------------------
    RSRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")
    ck("_stamp_source_relpath(recs, xl)" in RSRC,
       "run.py stamps the xlsx records with the inventory relpath that produced them")

    # --- PHASE 1 CHANGES NO OUTPUT BYTE ----------------------------------------
    # merge the SAME records with and without the stamp; canonical + ledger must be identical.
    import subprocess

    def _merge(stamped):
        d = Path(tempfile.mkdtemp(prefix="cbre_rp_"))
        (d / "inputs").mkdir()
        rs = [{"park": "Alpha", "city": "Corby", "country": "GB", "developer": "D",
               "warehouseArea": 10000, "areaUnit": "sq ft",
               "__meta": {"source_file": "t.xlsx", "source_type": "xlsx",
                          "locator_base": "row 2"}}]
        if stamped:
            RUN._stamp_source_relpath(rs, "Corby/t.xlsx")
        (d / "r.json").write_text(json.dumps(rs), encoding="utf-8")
        subprocess.run([sys.executable, str(HELPERS / "merge.py"), "--records", str(d / "r.json"),
                        "--source-dir", str(d / "inputs"), "--out", str(d / "c.json"),
                        "--ledger", str(d / "l.csv")],
                       capture_output=True, text=True, errors="replace")
        return ((d / "c.json").read_bytes() if (d / "c.json").exists() else b"",
                (d / "l.csv").read_bytes() if (d / "l.csv").exists() else b"")

    c_off, l_off = _merge(False)
    c_on, l_on = _merge(True)
    ck(c_off and c_on, "both merges produced a canonical")
    ck(c_off == c_on, "canonical.json is BYTE-IDENTICAL with and without the stamp")
    ck(l_off == l_on, "source_ledger.csv is BYTE-IDENTICAL too (the client-visible column)")
    ck(b"source_relpath" not in c_on,
       "source_relpath never reaches canonical (it rides __meta, which merge pops)")

    if fails:
        print(f"\nRELPATH TEST: FAIL ({len(fails)})")
        return 1
    print("\nRELPATH TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
