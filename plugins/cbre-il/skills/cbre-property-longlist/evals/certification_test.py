#!/usr/bin/env python3
"""Certification: ONE curated row carrying BREEAM and EPC, comma-separated.

Pins the rule rather than restating it: every assertion is extracted FROM the built
template, so a revert to `p.breeam` alone, or a dropped row on any of the three views,
fails here.

BREEAM and EPC are different certificates and both are first-class fields. They share one
row so a broker reads sustainability in a single place, and because the chrome renders a
fixed, hand-authored row set, a field without a curated home reaches the broker through the
Source Ledger and the Longlist workbook rather than the dashboard. This row is EPC's home.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import _common as C  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        FAILS.append(msg)


def main() -> int:
    t = C.load_template()
    print("== v36 certification ==")

    # ---- the helper exists and is a script global (all three views borrow it) ----
    check("function certStr(p){" in t, "certStr(p) is a script-global function")
    check("function certName(v, name){" in t, "certName(v, name) is a script-global function")
    check(t.index("function certStr(p){") < t.index("function detailHTML(p){"),
          "certStr is defined before detailHTML, so every view can reach it")

    # ---- it joins the two with a comma, never one alone ----
    m = re.search(r"function certStr\(p\)\{(.*?)\n\}", t, re.S)
    body = m.group(1) if m else ""
    check("p.breeam" in body and "p.epc" in body,
          "certStr reads BOTH p.breeam and p.epc")
    check('.join(", ")' in body, 'certStr joins the parts with ", "')
    check(".filter(Boolean)" in body,
          "certStr drops an absent half rather than emitting a stray separator")

    # ---- certName prefixes the certificate name, keeping a Target/Targeting lead ----
    mn = re.search(r"function certName\(v, name\)\{(.*?)\n\}", t, re.S)
    nbody = mn.group(1) if mn else ""
    check("new RegExp(name" in nbody,
          "certName leaves a value that already states its certificate untouched")
    check("target(?:ing|ed)?" in nbody,
          "certName keeps a leading Target/Targeting in front of the certificate name")
    check('"tbd"' in nbody and '"tbc"' in nbody,
          "certName treats the tbd/tbc sentinels as absent, so no row is invented")

    # ---- MODAL: a curated row ----
    check("row(T('cmp_certification'), certStr(p))" in t,
          "modal renders a curated Certification row")

    # ---- COMPARE: the row renders certStr, and epc is claimed only when it survives ----
    check("[T('cmp_certification'), p=>certStr(p) || '—', 'breeam']" in t,
          "compare Certification row renders certStr, not p.breeam alone")
    check("[T('row_land_price'), p=>p.landPrice, 'landPrice']" in t
          and "[T('row_incentives'), p=>p.incentives, 'incentives']" in t
          and "[T('row_reit'), p=>p.reit, 'reit']" in t,
          "compare carries the commercial rows the modal has, so the two views agree")

    # ---- FLYOVER: a curated row, and epc claimed in foCurated ----
    check('specs += specRow(T("cmp_certification"), certStr(p))' in t,
          "flyover renders a curated Certification row")
    check("autoLabel" not in t and "DENY_FIELDS" not in t and "LOCATOR_RE" not in t,
          "no auto-attribute machinery remains anywhere in the chrome")

    # ---- zero new i18n keys: cmp_certification must already exist ----
    check('"cmp_certification"' in t, "reuses the existing cmp_certification key (no new i18n key)")

    # ---- behaviour, executed for real in node ----
    node = ROOT / "evals" / "certification_test.mjs"
    if node.exists():
        r = subprocess.run(["node", str(node)], capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        print(out.rstrip())
        check(r.returncode == 0, "node behaviour check passed")
    else:
        print("  [note] certification_test.mjs absent - structural checks only")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
