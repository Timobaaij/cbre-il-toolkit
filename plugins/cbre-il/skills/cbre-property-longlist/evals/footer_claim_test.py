#!/usr/bin/env python3
"""footer_claim_test.py - the footer must not assert a drive-time METHOD it did not use. (v30)

THE DEFECT. The footer disclaimer is a STATIC string, and it asserted the methodology outright:
"Drive-time estimates are calculated from great-circle distance with a 1.25x road winding factor at
a 75 km/h motorway average". On any ROUTED run that is false - the shipped numbers are real
OSRM/openrouteservice road routes. A reviewer proved it arithmetically rather than by inspection:
the implied speeds across one live pack ranged 59.6-85.4 km/h, and individual legs came out both
SHORTER and LONGER than the formula predicts (id 1 -> DIRFT 52.5 km vs 47.9 predicted, id 1 ->
Northampton 37.3 vs 40.3). Because the sentence is static it made the claim whatever `DIST_MODE`
said, while the honest per-mode basis was already carried by `DIST_BADGE` and the legend tag right
beside the numbers.

WHY THE CLAUSE WAS DROPPED RATHER THAN MADE MODE-AWARE: a per-mode methodology sentence would have
had to be authored in 12 languages for a client-facing, legal-adjacent disclaimer. Cutting the
method and keeping each language's OWN existing "for orientation only" wording removes the false
claim in every language while authoring no new prose in any of them.

WHAT THIS PINS: no shipped surface claims the great-circle formula; the orientation-only caveat
survives (it is true in every mode); the per-mode labelling still exists to carry the real basis;
and EN plus all 12 packs agree, so a future edit cannot fix one language and leave the rest
asserting the old method. Offline, no build required for most of it."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import i18n as I18N  # noqa: E402

# every way the dropped method could be spelled, across the languages that carried it
METHOD_RX = re.compile(
    r"great[- ]circle|1[.,]25\s*[x×]|75\s*km/?[hu]"
    r"|ortodrom|orthodrom|ortodr[oó]m|Großkreis|hemelsbred|linii prostej"
    r"|c[ií]rculo m[aá]ximo|linie dreapt|nagykör|大圆距离",
    re.I)
# Each language's surviving orientation-only caveat, in ITS OWN words. Matched on the `orient`
# STEM rather than on per-language endings: an ending list missed Polish "orientacyjnym" and
# Portuguese "orientação" and reported a defect that was not there.
CAVEAT_RX = re.compile(r"orient|oriënt|Orientierung|titre indicatif|tájékozód|参考", re.I)


def main() -> int:
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # --- 1. EN, the source of truth ---------------------------------------- #
    en = I18N.EN["footer_disclaimer"]
    ck(not METHOD_RX.search(en), f"EN asserts no great-circle method {ascii(en[-150:])}")
    ck("orientation only" in en, "EN keeps the orientation-only caveat")
    for keep in ("subject to change without notice", "subject to negotiation",
                 "Not for public distribution"):
        ck(keep in en, f"EN keeps its legal content: {keep!r}")

    # --- 2. the template's inline EN copy must agree with it ---------------- #
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8",
                                                                 errors="replace")
    m = re.search(r'data-i18n="footer_disclaimer">(.*?)</div>', tpl, re.S)
    ck(bool(m), "the template carries a footer_disclaimer node")
    if m:
        inline = m.group(1).strip()
        ck(not METHOD_RX.search(inline),
           f"the template's inline copy asserts no method {ascii(inline[-120:])}")
        ck(inline == en, "the template's inline copy is BYTE-IDENTICAL to i18n.EN "
                         "(one source of truth, so they cannot drift)")

    # --- 3. every language pack, so no language is left asserting the method -- #
    packs = sorted((ROOT / "assets" / "i18n").glob("*.json"))
    ck(len(packs) == 12, f"all 12 bundled packs present ({len(packs)})")
    for p in packs:
        v = json.loads(p.read_text(encoding="utf-8")).get("footer_disclaimer", "")
        ck(bool(v), f"{p.stem}: has a footer_disclaimer")
        ck(not METHOD_RX.search(v), f"{p.stem}: asserts no great-circle method")
        ck(bool(CAVEAT_RX.search(v)),
           f"{p.stem}: keeps its own orientation-only caveat (no new prose authored)")

    # --- 4. the per-mode basis is still carried SOMEWHERE ------------------- #
    # dropping the footer claim is only honest because the real basis is still labelled.
    for tok in ("DIST_MODE", "DIST_LABEL", "DIST_BADGE"):
        ck(tok in tpl, f"the chrome still carries {tok} to state the real per-mode basis")
    for key in ("dist_badge_est", "dist_badge_car", "dist_badge_hgv"):
        ck(key in I18N.EN, f"EN still defines {key}")
    ck(I18N.EN["dist_badge_est"] != I18N.EN["dist_badge_hgv"],
       "the est and hgv badges genuinely differ, so the label distinguishes the modes")

    # --- 5. the version was bumped with the chrome edit -------------------- #
    ver = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8")
    n = int(re.sub(r"\D", "", ver.splitlines()[0]) or 0)
    ck(n >= 30, f"the template version is >= v30 {ascii(ver.splitlines()[0])}")
    import hashlib
    ck(hashlib.sha256(tpl.encode("utf-8")).hexdigest() in ver,
       "VERSION carries the CRLF-normalised text hash of the current template")

    print("STATUS:", "ALL-PASS" if not fails else "BLOCKED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
