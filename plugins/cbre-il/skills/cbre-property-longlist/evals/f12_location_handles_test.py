#!/usr/bin/env python3
"""f12_location_handles_test.py - F12: three readers, three treatments of one location handle.

THE DEFECT. Five decks printed a three-word address handle. Three readers put it in
`__meta.map_candidates`; two kept it out, reasoning it is neither a decimal pair, a DMS
string nor a maps link. Read literally the contract covered only those three forms, so the
two who kept it out were RIGHT and the case was simply unnamed. Isolated readers cannot
converge on an unnamed case by construction. The contract now names the unhandled forms and
decides each, on one criterion: a form the pipeline can turn into a pin ITSELF goes to
`map_candidates`; a handle that needs a third-party service or a library the pipeline does
not carry is DATA under its own key, so nothing is claimed that nobody resolved.

What this pins:
(1) the contract names each case and states the decision: three-word handle, plus code,
    national grid reference, postal-code-only anchor, plus the swept extras (a comma decimal
    mark / uncertain order, hemisphere-letter pairs, an invisible hyperlink, a street
    address, a pin on a map image or a QR code);
(2) both reader prompts carry the same four decisions (the readers are isolated, so the
    prompt is where convergence has to happen);
(3) the decisions are GROUNDED in the resolver's real behaviour: `coords_and_link_from_text`
    does resolve a DMS pair, a labelled decimal pair and a maps URL (those ARE candidates)
    and does NOT resolve a three-word handle, a plus code, a grid reference or a postcode
    (so putting them there would be the silent no-op the contract warns about). If the
    resolver ever learns one of those forms, this eval goes red and the contract must be
    re-decided, which is the point.

Run: python evals/f12_location_handles_test.py"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import coords as CO  # noqa: E402
import prompts_render as PR  # noqa: E402

_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_AUTO = {"SKILL_DIR", "CONTEXT", "FIELD_REGISTRY", "COMMON_POINTER"}

# (case label, contract needle, decided destination key)
CASES = (
    ("three-word address handle", "**A three-word address handle**", "threeWordAddress"),
    ("plus code", "**A plus code**", "plusCode"),
    ("national grid reference", "**A national grid reference**", "gridReference"),
    ("postal code as the only anchor", "**A postal code that is the only location anchor**",
     "postcode"),
)
SWEPT = ("decimal mark is\n    a comma", "hemisphere\n    letters", "not visible in\n    the text",
         "**A street address, a town, a junction**", "**A pin on an embedded map image, or a QR code**")


def _render(kind: str) -> str:
    tpl = (PR.TEMPLATE_DIR / f"{kind}.md").read_text(encoding="utf-8")
    return PR.render(kind, {s: f"<{s}>" for s in set(_SLOT_RE.findall(tpl)) if s not in _AUTO})


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    contract = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    sect_start = contract.find("COORDINATES AND LOCATION HANDLES")
    check(sect_start > 0, "interpretation.md has the 'COORDINATES AND LOCATION HANDLES' bullet")
    sect = contract[sect_start:contract.find("A GENUINE doubt is recorded", sect_start)]

    # (1) each case is named, decided, and the decision is NOT map_candidates for a handle
    for label, needle, key in CASES:
        i = sect.find(needle)
        check(i > 0, f"contract names the case: {label}")
        if i < 0:
            continue
        body = sect[i:i + 700]
        check(f"`{key}`" in body, f"contract sends the {label} to `{key}`")
        check("NOT `map_candidates`" in body or "never `map_candidates`" in body,
              f"contract says the {label} is NOT a map_candidate")
    check("third-party service" in sect,
          "contract states the criterion: a service-only handle is not a coordinate")
    check("does NOTHING with any other string" in sect,
          "contract explains WHY a stray handle in map_candidates is harmful (silent no-op)")
    for needle in SWEPT:
        check(needle in sect, f"contract sweeps the extra case {needle.splitlines()[0][:40]!r}")
    check("WITH the\n    page's own label" in sect,
          "contract tells the reader a bare decimal pair needs its printed label to resolve")
    check("three of five readers" in sect,
          "contract records the live split so the next editor does not un-name the case")

    # (2) both reader prompts carry the four decisions
    for kind in ("reader-text", "reader-raster"):
        out = _render(kind)
        for _label, _needle, key in CASES:
            check(f"`{key}`" in out, f"{kind}: names `{key}` as the destination")
        check("map_candidates" in out, f"{kind}: still routes DMS/links to map_candidates")
        check("cannot turn them into a pin" in out,
              f"{kind}: states why those keys are data, not candidates")

    # (3) grounded in the resolver: what it does and does not parse
    def resolves(s: str) -> bool:
        c, _link = CO.coords_and_link_from_text(s)
        return c is not None

    check(resolves("48°29'51.0\"N 17°01'39.7\"E"), "resolver: a DMS pair resolves (candidate)")
    check(resolves("Coordinates: 48.4976, 17.0277"),
          "resolver: a LABELLED decimal pair resolves (candidate, label included)")
    check(not resolves("48.4976, 17.0277"),
          "resolver: an UNLABELLED bare decimal pair is deliberately ignored (hence 'with the label')")
    check(resolves("https://maps.google.com/?q=48.4976,17.0277"),
          "resolver: a maps URL with a pin resolves (candidate)")
    for label, sample in (("three-word handle", "///quiet.harbour.lantern"),
                          ("plus code", "8FVC9G8F+6X"),
                          ("grid reference", "TQ 3000 8000"),
                          ("grid reference (X/Y)", "X 123456 / Y 654321"),
                          ("postcode", "QX41 8RD")):
        c, link = CO.coords_and_link_from_text(sample)
        check(c is None and link is None,
              f"resolver: a {label} yields NOTHING ({sample!r}), so it is DATA, not a candidate")

    print(f"\n{'PASS' if not fails else 'FAIL'} f12_location_handles_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
