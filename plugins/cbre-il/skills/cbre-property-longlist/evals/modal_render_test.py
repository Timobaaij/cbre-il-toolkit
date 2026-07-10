#!/usr/bin/env python3
"""modal_render_test.py - build a fixture dashboard, then run the Node harness that
evals the REAL detailHTML() and asserts the v21 data-driven modal behaviour.

The modal spec rows are generated CLIENT-SIDE (detailHTML runs on card click), so the
static HTML does not contain them - this test executes the template's JS in node:vm.
Run: python evals/modal_render_test.py   (exit 0 on success, 1 on any failure)
Offline by design.
"""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import build_dashboard  # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

CANON = {
    "meta": {"client": "ModalCo", "hero": {
        "topbar_meta": "Test", "eyebrow": "Modal render test",
        "title_html": "Test <em>modal</em>.", "lede": "Fixture for the v21 catch-all.",
        "footer_copyright": "(c) 2026 CBRE"}},
    "properties": [
        # RICH: real fields with NO curated row + an INVENTED field name + a nested scalar
        {"id": 1, "country": "PL", "park": "Rich Park", "developer": "DevA", "city": "Wroclaw",
         "status": "Existing", "warehouseArea": 50000, "warehouseRent": "60 EUR / sq m / year",
         "warehouseRentVal": 60.0, "clearHeight": "12 m", "earlyAccess": "2027", "motorway": "A4",
         "photo": PX, "gallery": [PX],
         "commune": "Katy Wroclawskie", "zoningType": "MU-2",
         "soilContaminationRisk": "Low (Phase I clear)",
         "distances": {"publicTransport": "Bus 612, 400 m"}},
        # THIN: none of the above extra fields
        {"id": 2, "country": "PL", "park": "Thin Park", "developer": "DevB", "city": "Poznan",
         "status": "Speculative", "warehouseArea": 20000, "warehouseRent": "tbd",
         "clearHeight": "tbd", "earlyAccess": "tbd", "motorway": "A2", "photo": PX, "gallery": [PX]},
    ],
    "pois": [], "regions": {},
}


def main() -> int:
    node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
    outdir = Path(tempfile.mkdtemp(prefix="cbre_modal_"))
    canon = outdir / "canonical.json"; canon.write_text(json.dumps(CANON), encoding="utf-8")
    built = outdir / "built.html"
    build_dashboard.build(canon, built)
    mjs = Path(__file__).resolve().parent / "modal_render_test.mjs"
    p = subprocess.run([node, str(mjs), str(built)], capture_output=True, text=True)
    sys.stdout.write(p.stdout); sys.stderr.write(p.stderr)
    return 0 if p.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
