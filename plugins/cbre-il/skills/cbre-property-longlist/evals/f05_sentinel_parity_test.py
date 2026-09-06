#!/usr/bin/env python3
"""f05_sentinel_parity_test.py - ONE unknown-value predicate, and every consumer agrees. (F5, F6)

WHAT WAS WRONG. The skill carried SEVEN private copies of "is this value an unknown?" (eight,
counting enrich._ok_region_city, which every count missed) and they disagreed: measured on the
live v40 code, 13 of 22 probe values drew at least two verdicts across the nine sites.
  * "??"  - the one sentinel the PIPELINE ITSELF writes (intake per cluster, _common for an
            unresolved country) - was DATA to the shared reader and UNKNOWN to every copy.
  * "n/a", "N/A", "TBC" were DATA to the two hero-KPI filters in build_dashboard.compute_kpis,
    so a source writing `n/a` for a country was counted as a real country in the headline.
  * a stated "none"/"None" was deleted by four copies. The extraction contract names it as a
    STATED NEGATIVE that is DATA, never an absence (reference/interpretation.md).
  * "TBA"/"TBS" were DATA to ALL copies, while prompts/reader-text.md tells readers those mark
    a genuine unknown - so a reader following its prompt shipped them to a card as a datum.

THE CONTRACT (fix plan C5). normalize.UNKNOWN_FORMS is the family; normalize.looks_unknown()
is the only predicate; every Python consumer delegates to it and the chrome's JS `isAbsent`
mirrors the list member for member. This eval drives EVERY consumer with the same probe table
and asserts the SAME verdict from each. Its sibling, f05_no_private_sentinel_sets_test.py, fails
when a new private literal appears.

Offline. Needs node to execute the chrome's isAbsent (as statedtotal_card_test does).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import normalize as N  # noqa: E402
import _common as C  # noqa: E402
import build_dashboard as BD  # noqa: E402
import deliver as DEL  # noqa: E402
import enrich as E  # noqa: E402

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


# The probe table: value -> the CONTRACT verdict (True = UNKNOWN, False = DATA). 24 probes.
PROBES: dict = {
    # sentinels every consumer must read as absence
    "": True, "   ": True, "tbd": True, "TBC": True, "tbc.": True, "Tbd.": True,
    "TBA": True, "TBS": True,                    # F6: the prompt names them, no copy agreed
    "??": True, "?": True,                       # F5: the pipeline's own sentinel
    "n/a": True, "N/A": True, "na": True, "-": True, "\u2014": True,
    "a consultar": True, "poa": True,
    # stated values every consumer must KEEP
    "none": False, "None": False,                # a stated negative is DATA
    "No": False, "Not charged": False, "BTS": False, "Built": False, "0": False,
}


def _kpi(field: str, key: str):
    def f(v):
        return BD.compute_kpis([{field: v}], {}, None, {})[key] == "0"
    return f


# Every consumer, as a callable returning True for UNKNOWN. Each entry names the site it drives
# so a failure line says WHICH consumer disagrees.
SITES = {
    "normalize.looks_unknown": N.looks_unknown,
    "deliver._is_tbd (Gaps Report, run.py ship probe)": DEL._is_tbd,
    "enrich._is_unknown_cc (geocoder, web_enrich)": E._is_unknown_cc,
    "enrich._ok_region_city (region resolution)": lambda v: not E._ok_region_city(v),
    "build_dashboard.compute_kpis: country KPI": _kpi("country", "kpi_countries"),
    "build_dashboard.compute_kpis: region KPI": _kpi("regionCode", "kpi_regions"),
    "_common.is_translatable_value (translator queue)":
        lambda v: not C.is_translatable_value("description", v),
}
# is_translatable_value also applies VALUE-SHAPE rules (a bare figure, a code, a date is never
# prose) that are not the sentinel rule. Those probes are excluded from THAT site only, and
# only they; the exclusion is stated here so nobody reads it as parity failing quietly.
SHAPE_EXCLUDED = {"_common.is_translatable_value (translator queue)": {"0"}}

# CODE-SCOPED SITES: parity is deliberately NOT total here, on exactly three probes.
#
# Three members of UNKNOWN_FORMS are also ASSIGNED ISO 3166-1 alpha-2 country codes. They belong
# in the family as ordinary VALUE abbreviations (the "n/a" family; the French and Spanish
# on-request forms), and in a rent or a spec cell that reading is right. In a field holding a
# two-letter COUNTRY CODE the same two characters are a country, so these sites read the family
# through `normalize.looks_unknown_code`, which exempts a bare assigned code and nothing else.
#
# THIS IS A MEASURED REGRESSION FIX, not a preference. The v41 consolidation pointed
# `enrich._is_unknown_cc` at the value-scoped reader; that test had deliberately never carried
# these three. Against the previous release the site moved False -> True for all three, so a
# property in one of those countries stopped being geocoded by country and dropped out of the
# country KPI. The shared reader already answered UNKNOWN for them before the consolidation; what
# moved was the CALLER. Consolidation should have delegated these two to a narrower named
# predicate, which is what they now do.
#
# The claim asserted below is STRONGER than plain parity, not weaker: a code-scoped site must
# agree with the shared reader on EVERY probe except these three, and must disagree on exactly
# these three. A site that quietly grew a fourth exemption fails here.
CODE_SCOPED = {
    "enrich._is_unknown_cc (geocoder, web_enrich)",
    "build_dashboard.compute_kpis: country KPI",
}


def main() -> int:
    print("== the family itself ==")
    ck(isinstance(N.UNKNOWN_FORMS, frozenset), "normalize.UNKNOWN_FORMS is a frozenset (a NAME, not an inline literal)")
    for m in ("??", "tba", "tbs", "tbd", "tbc", "n/a", "na", "-", "\u2014", ""):
        ck(m in N.UNKNOWN_FORMS, f"family carries {m!r}")
    for m in ("none", "bts", "null", "0", "no"):
        ck(m not in N.UNKNOWN_FORMS, f"family does NOT carry {m!r}")
    ck(all(m == m.strip().lower().rstrip(".") or m == "" for m in N.UNKNOWN_FORMS),
       "every member is already in looks_unknown()'s normal form (trimmed, lower, no trailing dots)")

    print()
    print("== the probe table: every Python consumer, one verdict ==")
    n_sites = 0
    for name, fn in SITES.items():
        n_sites += 1
        for probe, want in PROBES.items():
            if probe in SHAPE_EXCLUDED.get(name, set()):
                print(f"  [skip] {name}: {probe!r} excluded by a value-SHAPE rule, not the sentinel rule")
                continue
            exempt = (name in CODE_SCOPED
                      and str(probe or "").strip().lower().rstrip(".") in N.CODE_LIKE_EXEMPT)
            want_here = False if exempt else want
            try:
                got = bool(fn(probe))
            except Exception as e:  # a consumer that throws on a probe has no verdict at all
                got = f"raised {type(e).__name__}"
            why = (" (code-scoped: this probe is an assigned ISO alpha-2 code, so this site "
                   "reads it as a COUNTRY, not as the same two letters meaning unknown)"
                   if exempt else "")
            ck(got is want_here,
               f"{name}: {probe!r} -> {'UNKNOWN' if want_here else 'DATA'} (got {got}){why}")
    ck(n_sites >= 7, f"{n_sites} Python consumers driven (the seven the audit named, less the JS one)")

    print()
    print("== the code-scoped exemption: exactly three forms, and only where a code is read ==")
    ck(N.CODE_LIKE_EXEMPT == frozenset({"na", "nc", "sc"}),
       "the exemption is EXACTLY the three family members that are assigned ISO alpha-2 codes; "
       "a fourth would need its own measured justification, so it fails here first")
    ck(all(m in N.UNKNOWN_FORMS for m in N.CODE_LIKE_EXEMPT),
       "every exempt form is still a member of the family: the exemption narrows the READING, "
       "it does not remove the form")
    for m in sorted(N.CODE_LIKE_EXEMPT):
        ck(N.looks_unknown(m) and not N.looks_unknown_code(m),
           f"{m!r}: UNKNOWN to the value-scoped reader, DATA to the code-scoped one")
    ck(N.looks_unknown_code("n/a") and N.looks_unknown_code("??") and N.looks_unknown_code("tbd"),
       "the code-scoped reader still answers UNKNOWN for every NON-code form, so it is the family "
       "minus a stated exemption rather than a fourth private set")
    ck(not N.looks_unknown_code("GB") and not N.looks_unknown("GB"),
       "an ordinary country code is DATA to both readers")

    # THE THREE SITES THAT READ A CODE MUST AGREE ON WHICH FIELDS ARE CODES. Three separate
    # places grew the code-scoped reading independently (the enrichment country test, the gate
    # runner's field-aware `_unknown`, and the render boundary). A fourth site reading a
    # DIFFERENT field set is the same divergence this whole eval exists to prevent, one level up.
    import _common as _C
    import gate_runner as _G
    ck(_C.CODE_FIELDS == _G.CODE_FIELDS,
       f"_common.CODE_FIELDS and gate_runner.CODE_FIELDS name the same fields "
       f"({sorted(_C.CODE_FIELDS)})")
    for code in sorted(N.CODE_LIKE_EXEMPT):
        up = code.upper()
        ck(_C.fill_render_sentinels({"country": up}).get("country") == up,
           f"the RENDER boundary keeps a real {up!r} country instead of overwriting it with the "
           f"unknown sentinel: this is the last place the value could be lost, and the card "
           f"would have shown no country at all")
    ck(_C.fill_render_sentinels({"country": "tbd"}).get("country") == "??"
       and _C.fill_render_sentinels({"country": "n/a"}).get("country") == "??",
       "every NON-code unknown form still fills the country sentinel at the render boundary, so "
       "the exemption narrowed the reading and nothing else")
    # None is a Python-only probe (JSON null on the chrome side, covered below)
    ck(N.looks_unknown(None) and DEL._is_tbd(None) and E._is_unknown_cc(None),
       "None is UNKNOWN to the predicate and its wrappers")

    print()
    print("== the consequences the contract names ==")
    ck(N.sentinel("None") == "None" and N.sentinel("none") == "none",
       "sentinel() ships a stated 'None' verbatim (a stated negative is DATA)")
    ck(N.sentinel("TBA") == "tbd" and N.sentinel("TBS") == "tbd" and N.sentinel("??") == "tbd",
       "sentinel() maps TBA / TBS / ?? to the honest 'tbd'")
    ck(C.fill_render_sentinels({"country": "TBA"})["country"] == "??",
       "a country a reader shipped as TBA renders as the honest '??', never as a country")
    ck(C.fill_render_sentinels({"sprinklers": "None"}).get("sprinklers") == "None",
       "a stated 'None' survives fill_render_sentinels untouched")
    k = BD.compute_kpis([{"country": "n/a"}, {"country": "GB"}, {"country": "TBC"}], {}, None, {})
    ck(k["kpi_countries"] == "1" and k["kpi_countries_sub"] == "GB",
       f"the hero KPI counts one country for [n/a, GB, TBC], not three ({k['kpi_countries']}, {k['kpi_countries_sub']!r})")
    ck(C.is_translatable_value("sprinklers", "None") is True,
       "a stated 'None' is prose the translator may render (like 'No', 'Ja', 'Si')")
    ck(C.core_fill({"city": "??", "developer": "TBA", "warehouseArea": "TBS",
                    "warehouseRent": "tbd", "status": "tbc"}) == 0.0,
       "core_fill reads ??/TBA/TBS as unfilled - a record stuffed with them IS thin (routing changes knowingly)")

    print()
    print("== the chrome: the JS list mirrors the Python family, and isAbsent agrees ==")
    tpl = C.load_template()
    m = re.search(r"const UNKNOWN_FORMS = (\[[^\]]*\]);", tpl, re.S)
    ck(m is not None, "the template declares `const UNKNOWN_FORMS = [...]`")
    js_members = set(json.loads(m.group(1))) if m else set()
    ck(js_members == set(N.UNKNOWN_FORMS),
       f"JS UNKNOWN_FORMS == normalize.UNKNOWN_FORMS member for member "
       f"(JS-only: {sorted(js_members - set(N.UNKNOWN_FORMS))}, Python-only: {sorted(set(N.UNKNOWN_FORMS) - js_members)})")
    ck("\u2014" not in tpl.split("const UNKNOWN_FORMS", 1)[-1][:1200],
       "the dash sentinel is written as a JSON escape in the JS list, not as a character")
    m2 = re.search(r"const isAbsent = v => v === null \|\| v === undefined\s*\|\| UNKNOWN_FORMS\.includes\("
                   r"String\(v\)\.trim\(\)\.toLowerCase\(\)\.replace\(/\\\.\+\$/, \"\"\)\);", tpl)
    ck(m2 is not None, "isAbsent normalises exactly as looks_unknown does (trim, lower, strip trailing dots)")
    ck("const isTbd = isAbsent;" in tpl, "detailHTML's isTbd delegates to isAbsent (was a private five-member copy)")
    fly = tpl.split("function isTbd(v) {", 1)[-1][:400]
    ck("return isAbsent(v);" in fly, "the Flyover's isTbd delegates to isAbsent (was a private exact-case copy)")
    cert = tpl.split("function certName(v, name){", 1)[-1][:300]
    ck("if(isAbsent(t)) return" in cert and '=== "tbd"' not in cert,
       "certName() delegates to isAbsent (was a private four-member comparison chain)")
    ck(len(re.findall(r'===\s*"(?:tbd|tbc|\?\?|n/a)"', tpl)) == 0,
       "no JS code compares a value against a sentinel string by hand")

    node = shutil.which("node") or r"C:\Users\TBaaij\nodejs\node.exe"
    if not (shutil.which("node") or Path(node).exists()):
        ck(False, "node is required to execute the chrome's isAbsent (install node or add it to PATH)")
    elif m and m2:
        decl = tpl[m.start():m2.end()]
        probes = {k: v for k, v in PROBES.items()}
        js = (decl + "\nconst P = " + json.dumps(list(probes.keys()), ensure_ascii=True) + ";\n"
              "const out = {}; for (const p of P) out[p] = isAbsent(p);\n"
              "out['<null>'] = isAbsent(null); out['<undefined>'] = isAbsent(undefined);\n"
              "out['<0>'] = isAbsent(0); out['<empty-array>'] = isAbsent([]);\n"
              "process.stdout.write(JSON.stringify(out));\n")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "isabsent_probe.mjs"
            f.write_text(js, encoding="utf-8")
            r = subprocess.run([node, str(f)], capture_output=True, text=True, encoding="utf-8")
        ck(r.returncode == 0, f"node executed the chrome's isAbsent ({(r.stderr or '').strip()[:120]})")
        if r.returncode == 0:
            got = json.loads(r.stdout)
            for probe, want in probes.items():
                ck(got.get(probe) is want,
                   f"chrome isAbsent: {probe!r} -> {'UNKNOWN' if want else 'DATA'} (got {got.get(probe)})")
            ck(got["<null>"] is True and got["<undefined>"] is True, "chrome: null / undefined are absent")
            ck(got["<0>"] is False, "chrome: the number 0 is DATA (a stated zero)")
            ck(got["<empty-array>"] is True, "chrome: an empty array is absent (String([]) is '')")

    print()
    if FAILS:
        print(f"F05 SENTINEL PARITY TEST: FAIL ({len(FAILS)})")
        for f_ in FAILS[:12]:
            print("   -", f_)
        return 1
    print("F05 SENTINEL PARITY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
