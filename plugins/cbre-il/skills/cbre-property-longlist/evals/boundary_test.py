#!/usr/bin/env python3
"""boundary_test.py - render-boundary unit tests (Phase 1+). Offline.
Run: python evals/boundary_test.py   (exit 0 on success, 1 on any failure)"""
from __future__ import annotations
import sys
from pathlib import Path
HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402

def main() -> int:
    fails = []
    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    cf = C.canonical_property_fields()
    ck(isinstance(cf, frozenset) and len(cf) > 20, "canonical_property_fields is a non-trivial frozenset")
    ck({"warehouseArea", "description", "status", "gallery", "preBaked"} <= cf,
       "canonical set contains known schema fields")
    ck("prov" not in cf and "provenance" not in cf and "offspec" not in cf,
       "canonical set excludes provenance/meta keys")

    ck(C.looks_like_locator("page 16 (text interpretation)"), "locator: 'page 16 (text interpretation)'")
    ck(C.looks_like_locator("page 3 (SUPERFICIES nave total)"), "locator: 'page 3 (SUPERFICIES nave total)'")
    ck(C.looks_like_locator("slide 2 (vision transcription)"), "locator: 'slide 2 (vision transcription)'")
    ck(C.looks_like_locator("page 16 (verbatim)"), "locator: 'page 16 (verbatim)'")
    ck(not C.looks_like_locator("Plataforma logistica en construccion"), "prose is not a locator")
    ck(not C.looks_like_locator("12 m"), "'12 m' is not a locator")
    ck(not C.looks_like_locator(50000) and not C.looks_like_locator(None), "non-string is not a locator")
    ck(not C.looks_like_locator("Building on page 16 has clear height"),
       "prose merely mentioning a page is not a locator")

    import merge as M  # noqa: E402

    # _normalise_offspec: a non-canonical OBJECT (prov map) + a locator-scalar are quarantined;
    # a genuine scalar attribute (commune) + a canonical container (gallery) are KEPT.
    rec = {
        "city": "Wroclaw", "commune": "Katy Wroclawskie",
        "gallery": ["data:img"], "warehouseArea": 50000,
        "prov": {"city": "page 16 (text interpretation)", "clearHeight": "page 16 (text: Altura libre)"},
        "someRef": "page 2 (verbatim)",
        "extraList": ["Unit A", "Unit B"],
        "__meta": {"source_file": "deck.pdf"},
    }
    M._normalise_offspec(rec)
    ck("commune" in rec and rec["commune"] == "Katy Wroclawskie", "normalise keeps a genuine scalar (commune)")
    ck("gallery" in rec, "normalise keeps a canonical container object (gallery)")
    ck("prov" not in rec, "normalise quarantines a non-canonical object (prov)")
    ck("someRef" not in rec, "normalise quarantines a locator-shaped scalar (someRef)")
    ck("extraList" not in rec, "normalise quarantines a non-canonical LIST value (extraList)")
    off = rec.get("__meta", {}).get("offspec", {})
    ck("prov" in off and "someRef" in off and "extraList" in off, "quarantined keys land in __meta.offspec")
    ck("city" in rec and "warehouseArea" in rec, "normalise keeps canonical fields untouched")

    # after normalisation, merge_cluster's output excludes the off-spec keys but keeps commune
    out, prov, conflicts = M.merge_cluster([rec])
    ck("commune" in out and "prov" not in out and "someRef" not in out,
       "merge_cluster output has commune, not prov/someRef")

    import gate_runner as G  # noqa: E402
    import build_dashboard as B  # noqa: E402
    import tempfile, json as _json, types, io, contextlib

    def _reconcile(props):
        canon = {"meta": {"client": "T", "hero": {"topbar_meta": "", "eyebrow": "", "title_html": "",
                 "lede": "", "footer_copyright": ""}}, "properties": props, "pois": [], "regions": {}}
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "canonical.json"; cp.write_text(_json.dumps(canon), encoding="utf-8")
            hp = Path(td) / "b.html"; B.build(cp, hp)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = G.cmd_reconcile(types.SimpleNamespace(html=str(hp), canonical=str(cp)))
            return rc
    PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
          "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    base = {"id": 1, "country": "PL", "park": "P", "developer": "D", "city": "C",
            "status": "Existing", "warehouseArea": 1000, "photo": PX, "gallery": [PX]}
    ck(_reconcile([dict(base)]) == 0, "reconcile passes a clean property")
    ck(_reconcile([{**base, "prov": {"city": "page 1 (text interpretation)"}}]) != 0,
       "reconcile BLOCKS a non-canonical object on a property")
    ck(_reconcile([{**base, "someRef": "page 2 (verbatim)"}]) != 0,
       "reconcile BLOCKS a locator-shaped scalar value")
    ck(_reconcile([{**base, "extraList": ["Unit A", "Unit B"]}]) != 0,
       "reconcile BLOCKS a list-valued non-canonical key (list branch)")

    # v22 Phase 2: translation eligibility (deterministic exclusions; LLM translates the rest)
    T = C.is_translatable_value
    ck(T("description", "Plataforma logística en construcción"), "prose description is translatable")
    ck(T("status", "En construcción"), "prose status is translatable")
    ck(T("landUse", "uso industrial y logístico"), "a brand-new prose attribute is translatable")
    ck(not T("developer", "7R"), "developer (proper name field) is NOT translatable")
    ck(not T("city", "Wrocław"), "city (proper name field) is NOT translatable")
    ck(not T("zoningType", "MU-2"), "a code value is NOT translatable")
    ck(not T("clearHeight", "12 m"), "a number+unit value is NOT translatable")
    ck(not T("warehouseRent", "€60 / sq m / year"), "a currency/rate string is NOT translatable")
    ck(not T("warehouseArea", 50000), "a numeric value is NOT translatable")
    ck(not T("earlyAccess", "2027"), "a bare year is NOT translatable")
    ck(not T("description", "tbd") and not T("description", ""), "sentinel/empty is NOT translatable")
    ck(not T("someRef", "page 9 (text interpretation)"), "a locator string is NOT translatable")
    # prose that merely MENTIONS a price/figure/url is still prose -> translatable (multi-word)
    ck(T("description", "Priced at €60/sqm, fully fitted and available for immediate occupation"),
       "prose mentioning a price is still translatable (embedded figure not excluded)")
    ck(T("status", "En construcción, entrega prevista Q1 2026"),
       "prose mentioning a date is still translatable")
    ck(not T("warehouseRent", "€60 / sq m / year"), "a short rate string stays NON-translatable")

    if fails:
        print(f"\nBOUNDARY TEST: FAIL ({len(fails)})")
        return 1
    print("\nBOUNDARY TEST: PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
