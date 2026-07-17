#!/usr/bin/env python3
"""format_test.py - build EN + DE variants of one fixture and prove derived numbers
render per LOCALE while source strings stay verbatim. Offline.
Run: python evals/format_test.py   (exit 0 on success, 1 on failure)"""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import build_dashboard  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

def _canon(lang):
    meta = {"client": "FmtCo", "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
            "lede": "", "footer_copyright": ""}}
    if lang:
        meta["language"] = lang
    return {"meta": meta, "properties": [
        {"id": 1, "country": "PL", "park": "Fmt Park", "developer": "D", "city": "Wroclaw",
         "status": "Existing", "warehouseArea": 50000, "warehouseRent": "60 EUR / sq m / year",
         "warehouseRentVal": 60.0, "clearHeight": "12 m", "earlyAccess": "2027", "motorway": "A4",
         "photo": PX, "gallery": [PX]}], "pois": [], "regions": {}}

def main() -> int:
    node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
    d = Path(tempfile.mkdtemp(prefix="cbre_fmt_"))
    en = d / "en.html"; de = d / "de.html"
    (d / "en.json").write_text(json.dumps(_canon("English")), encoding="utf-8")
    (d / "de.json").write_text(json.dumps(_canon("de")), encoding="utf-8")
    build_dashboard.build(d / "en.json", en)
    build_dashboard.build(d / "de.json", de)
    mjs = Path(__file__).resolve().parent / "format_test.mjs"
    p = subprocess.run([node, str(mjs), str(en), str(de)], capture_output=True, text=True)
    sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
    return 0 if p.returncode == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
