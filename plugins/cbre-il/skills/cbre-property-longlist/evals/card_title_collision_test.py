#!/usr/bin/env python3
"""card_title_collision_test.py - two shipped cards may never render the SAME title. (A14c)

The card heading is the reader's whole handle on an option. Two genuinely DIFFERENT units at
one location that draw an identical heading are indistinguishable on the grid, and worse in
the COMPARISON VIEW, which stands the two identical headings side by side at exactly the
moment the reader is being asked to choose between them. That shape has shipped.

WHY A GATE AND NOT A DATA FIX, AND NOT THE `unit` FIELD EITHER. A canonical field is only as
present as the run that filled it: a designator this month's tracker states and next month's
omits collapses both cards back onto one heading, silently, with every field still
individually sourced and traceable. So the invariant is asserted about the DELIVERABLE - no
two cards share a heading - rather than about any one field being populated, and
`gate_runner.py coverage` asks the finished dataset, next to the over-SPLIT dedupe check and
the over-MERGE postal-code check it belongs beside.

NEITHER OF THOSE TWO SEES IT, and every fixture here is built so that neither can answer for
this one: the dedupe key demands park, city, developer AND warehouse area all equal, so each
property carries a per-id area, and the code check needs `meta.clusterSources`, which no
fixture writes. A block below can only be the title check speaking, and section 2 asserts
that as a positive control rather than claiming it in prose.

THE COMPOSITION IS DUPLICATED, BY DESIGN, AND THIS FILE IS WHERE THE DRIFT SHOWS. The chrome
composes the heading in `titleStr` (`assets/dashboard_template.html`), the single site behind
the card, the compare-tray chip, the map popup, the map-list row, the modal title and the
comparison-table column header; `gate_runner._card_title` is a hand-maintained Python copy of
it. There is nothing to import - `titleStr` runs in the reader's browser, and the gate runs
BEFORE the build, when no HTML exists - so the cost of duplicating is paid here instead:
section 1 asserts the Python copy rule by rule, and section 7 asserts that `titleStr`'s own
rule markers are still in the template, so a chrome that changes the composition without
changing the gate is a RED eval rather than a silent miss.

Names are invented; nothing in this file may identify a client, a country or a real property.
Offline, no network, no build. Run: python evals/card_title_collision_test.py"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import gate_runner as GR  # noqa: E402

CITY = "Northport"
DEV = "Ardent Estates"
_TMP: list = []


def prop(pid: int, park: str, **over) -> dict:
    """One shipped property, CORE-COMPLETE so the coverage gate's fill check cannot fire and
    fake (or mask) a title verdict, and with a per-id warehouse area so the dedupe check
    cannot either - the two checks this one has to be distinguishable from."""
    p = {"id": pid, "park": park, "city": CITY, "country": "ZZ", "developer": DEV,
         "status": "Built", "photo": "x", "warehouseArea": 10000 + pid,
         "warehouseRent": "9.50", "clearHeight": "12 m", "earlyAccess": "now",
         "motorway": "X9", "lat": 1.0, "lng": 2.0}
    p.update(over)
    return p


def coverage(props: list, meta: dict | None = None):
    """Run the REAL G-coverage gate in a subprocess, so the exit code is the gate's own and
    no in-process import can accidentally satisfy the assertion."""
    if not _TMP:
        _TMP.append(Path(tempfile.mkdtemp(prefix="cbre_title_")))
    # A DISTINCT filename EACH time: `_common.load_canonical` caches on
    # (mtime_ns, size, st_ino), and two same-size writes to one path inside a single coarse
    # mtime tick is exactly the collision that cache guards against.
    f = _TMP[0] / f"canonical_{len(list(_TMP[0].glob('canonical_*.json')))}.json"
    f.write_text(json.dumps({"meta": meta or {}, "properties": props,
                             "pois": [], "regions": {}}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(HELPERS / "gate_runner.py"), "coverage", str(f)],
        capture_output=True, text=True, errors="replace")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails: list[str] = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---------------- 1. the composition, rule by rule -----------------------------------
    print("1. _card_title mirrors the chrome's titleStr")
    ck(GR._card_title(prop(1, "Kestrel Reach")) == "Kestrel Reach",
       "no `unit` key at all: the park name alone (today's shape, and for ever the shape of "
       "a record whose source names no unit)")
    ck(GR._card_title(prop(1, "Kestrel Reach", unit="Unit 4")) == "Kestrel Reach Unit 4",
       "a stated unit is appended to the park name, joined by ONE space")
    ck(GR._card_title(prop(1, "Kestrel Reach Unit 4", unit="Unit 4"))
       == "Kestrel Reach Unit 4",
       "a park that already CARRIES the designator does not repeat it")
    ck(GR._card_title(prop(1, "Kestrel Reach Unit 4", unit="unit 4"))
       == "Kestrel Reach Unit 4",
       "...case-insensitively")
    ck(GR._card_title(prop(1, "Kestrel Reach, Unit 4", unit="Unit 4"))
       == "Kestrel Reach, Unit 4",
       "...and through punctuation, because the WORDS are what match")
    ck(GR._card_title(prop(1, "Unit 4 Kestrel Reach", unit="Unit 4"))
       == "Unit 4 Kestrel Reach",
       "...ANYWHERE in the park string, not only at its end - the chrome's rule is a "
       "whole-token run, not a suffix test")
    ck(GR._card_title(prop(1, "Kestrel Reach 300", unit="3")) == "Kestrel Reach 300 3",
       "a WHOLE-token run, so a unit '3' is NOT found inside a park 'Kestrel Reach 300' - a "
       "plain substring test would have suppressed a real designator there")
    ck(GR._card_title(prop(1, "Unit 4", unit="Unit 4")) == "Unit 4",
       "a park equal to the unit is not doubled")
    for sentinel in ("tbd", "TBC", "", "   ", "??", "-", None):
        ck(GR._card_title(prop(1, "Kestrel Reach", unit=sentinel)) == "Kestrel Reach",
           f"a sentinel unit ({sentinel!r}) is ABSENCE, not a designator, and adds no "
           f"trailing separator")
        ck(GR._card_title(prop(1, "tbd" if sentinel is None else sentinel,
                               unit="Unit 4")) == "Unit 4",
           f"a sentinel PARK ({sentinel!r}) is absence too: the unit becomes the whole title")
    # 'n/a' IS ABSENCE TO BOTH SIDES, AND FOR ONE REASON. This used to be pinned as a
    # DOCUMENTED DIVERGENCE: `_absent` carried its own seven-member sentinel tuple that read
    # 'n/a' as absence while the chrome's `isAbsent` list did not. Neither half of that reason
    # is true any more. Since v41 the chrome's list mirrors `normalize.UNKNOWN_FORMS`, and
    # since the SEAM-13 delegation `_absent` reads nothing but that same family through
    # `normalize.looks_unknown`, so the two sides agree by construction rather than by
    # coincidence, and a form added to the family reaches both on the same day. The
    # assertion below never went red across that change, which is exactly how a wrong stated
    # reason survives a green suite; the reason is what changed, so the reason is rewritten.
    ck(GR._card_title(prop(1, "Kestrel Reach", unit="n/a")) == "Kestrel Reach",
       "'n/a' is absence to `_absent` AND to the chrome's `isAbsent`, both reading the one "
       "shared family, so the gate and the chrome suppress the same designators")
    # The delegation itself, pinned: every member of the shared family is absence here, a
    # stated "none" is DATA (the extraction contract names it a stated negative, so a unit
    # or park literally reading "None" is a designator, not a gap), and the code-valued
    # `country` gets the narrower reading in which a bare assigned alpha-2 code that doubles
    # as a market abbreviation for "unknown" is a country. `_cov_filled` is the same
    # predicate from the other side. A private literal in gate_runner would make these
    # pass by accident; evals/f05_no_private_sentinel_sets_test.py fails the moment one
    # reappears under helpers/.
    import normalize as N  # noqa: E402
    ck(all(GR._absent(m) for m in N.UNKNOWN_FORMS) and GR._absent(None),
       f"every one of the {len(N.UNKNOWN_FORMS)} shared unknown forms is absence to `_absent`")
    ck(not GR._absent("None") and not GR._absent("none"),
       "a stated 'None' is NOT absence: the contract calls it a stated negative, i.e. data")
    ck(GR._card_title(prop(1, "Kestrel Reach", unit="None")) == "Kestrel Reach None",
       "...so a unit literally reading 'None' is rendered as the designator it is")
    ck(GR._absent("na") and GR._absent("nc") and GR._absent("sc"),
       "in the prose reading 'na'/'nc'/'sc' are unknown forms, as in every value cell")
    ck(not GR._absent("na", "country") and not GR._absent("nc", "country")
       and not GR._absent("sc", "country") and GR._absent("n/a", "country")
       and GR._absent("??", "country"),
       "in the `country` (code) reading the three bare assigned alpha-2 codes are COUNTRIES, "
       "while 'n/a' and '??' stay unknown - normalize.CODE_LIKE_EXEMPT, not a fourth set")
    ck(set(GR.CODE_FIELDS) == {"country"},
       "exactly one field gets the code reading today; widening it is a decision, not a drift")
    ck(all(not GR._cov_filled(m) for m in N.UNKNOWN_FORMS) and GR._cov_filled("None")
       and GR._cov_filled(0) and GR._cov_filled(-1.5),
       "`_cov_filled` is the same predicate from the other side: the family is empty, a stated "
       "'None', zero and a negative coordinate are filled")
    ck(GR._card_title({}) == "" and GR._card_title({"park": "tbd", "unit": "tbc"}) == "",
       "neither stated: NO title at all, exactly as titleStr returns falsy")
    ck(GR._norm_title("  Kestrel   Reach\tUnit 4 ") == "kestrel reach unit 4",
       "_norm_title collapses every run of whitespace, trims and case-folds")
    # THE NON-BREAKING SPACE IS BUILT WITH chr(0xa0), NOT PASTED IN AS A BYTE, deliberately: a
    # raw U+00A0 in this source is invisible to whoever reads the eval next, so the assertion
    # would look vacuous and get deleted as noise. For a str pattern `\s` matches it, which is
    # the whole reason the gate normalises rather than comparing raw strings.
    ck(GR._norm_title("Kestrel" + chr(0xa0) + "Reach") == GR._norm_title("Kestrel Reach")
       == "kestrel reach",
       "...including a NON-BREAKING space, which a reader cannot see at all")
    ck(GR._norm_title("Kestrel Reach, Unit 4") != GR._norm_title("Kestrel Reach Unit 4"),
       "_norm_title does NOT strip punctuation, and must not: a reader can see a comma, so "
       "two titles differing by one are two titles (word-reduction is `_title_words`' job)")

    # ---------------- 2. two colliding titles BLOCK ---------------------------------------
    print("\n2. two shipped properties rendering one title BLOCK")
    r = coverage([prop(1, "Kestrel Reach", unit="Unit 4"),
                  prop(2, "Kestrel Reach", unit="Unit 4")])
    ck(r.returncode != 0 and "BLOCKED" in r.stdout,
       f"the gate blocks {ascii(r.stdout[-60:])}")
    ck("identical card title" in r.stdout, "...as an identical-card-title finding")
    for tok in ("id=1", "id=2", "Kestrel Reach Unit 4"):
        ck(tok in r.stdout,
           f"...naming {tok}, so the reader can act without opening the work directory")
    ck("comparison view" in r.stdout,
       "...and saying where it hurts most (the view that asks the reader to choose)")
    ck("repairs.json" in r.stdout,
       "...with the remedy named (the house rule for every refusal)")
    ck("duplicate property" not in r.stdout and "over-merge" not in r.stdout,
       "POSITIVE CONTROL: the dedupe and over-merge checks are SILENT on this pair (distinct "
       "areas, no clusterSources), so the block is attributable to the title check alone")

    # the same collision reached from the OTHER direction: one record carries the designator
    # inside its park string, the other states it as a unit. This is the pair the
    # de-duplication rule exists for, and the pair a gate without it would miss.
    r2 = coverage([prop(1, "Kestrel Reach Unit 4"),
                   prop(2, "Kestrel Reach", unit="Unit 4")])
    ck(r2.returncode != 0 and "identical card title" in r2.stdout,
       "a park-borne designator colliding with a unit-borne one blocks too")

    # normalisation is what a READER does, so the gate must too
    for label, a, b in (
            ("case", "Kestrel Reach", "KESTREL REACH"),
            ("double spacing", "Kestrel Reach", "Kestrel  Reach"),
            ("a non-breaking space", "Kestrel Reach", "Kestrel" + chr(0xa0) + "Reach"),
            ("trailing whitespace", "Kestrel Reach", "Kestrel Reach  ")):
        rn = coverage([prop(1, a), prop(2, b)])
        ck(rn.returncode != 0 and "identical card title" in rn.stdout,
           f"two titles differing only by {label} are ONE title to a reader, and block")

    # three cards on one title: every collision is reported against the first, so nothing
    # falls off the tail
    r3 = coverage([prop(1, "Kestrel Reach"), prop(2, "Kestrel Reach"),
                   prop(3, "Kestrel Reach")])
    ck(r3.stdout.count("identical card title") == 2
       and "id=1 and id=2" in r3.stdout and "id=1 and id=3" in r3.stdout,
       "three cards on one title report BOTH collisions, each naming the first card")

    # ---------------- 3. distinct titles PASS ---------------------------------------------
    print("\n3. distinct titles are silent (the check is inert on a correct run)")
    ok_cases = [
        ("different parks", [prop(1, "Kestrel Reach"), prop(2, "Harrier Point")]),
        ("one park, two stated units", [prop(1, "Kestrel Reach", unit="Unit 4"),
                                        prop(2, "Kestrel Reach", unit="Unit 5")]),
        ("one park, the designator inside each park string",
         [prop(1, "Kestrel Reach Unit 4"), prop(2, "Kestrel Reach Unit 5")]),
        ("a park-borne designator against a DIFFERENT unit-borne one",
         [prop(1, "Kestrel Reach Unit 4"), prop(2, "Kestrel Reach", unit="Unit 5")]),
        ("one park where only ONE record states a unit",
         [prop(1, "Kestrel Reach", unit="Unit 4"), prop(2, "Kestrel Reach")]),
        ("an untitled record beside a titled one",
         [prop(1, "tbd"), prop(2, "Kestrel Reach")]),
    ]
    for label, props in ok_cases:
        rp = coverage(props)
        ck(rp.returncode == 0 and "ALL-PASS" in rp.stdout
           and "identical card title" not in rp.stdout,
           f"{label}: ALL-PASS {ascii(rp.stdout[-40:])}")

    # ---------------- 4. one property is inert --------------------------------------------
    print("\n4. a single-property run cannot reach the check at all")
    for label, props in (("with a unit", [prop(1, "Kestrel Reach", unit="Unit 4")]),
                         ("with no unit", [prop(1, "Kestrel Reach")]),
                         ("with no title at all", [prop(1, "", unit="")]),
                         ("no properties at all", [])):
        r1 = coverage(props)
        ck("identical card title" not in r1.stdout,
           f"one property ({label}): nothing to collide with, so nothing is reported")

    # ---------------- 5. `unit` absent ENTIRELY -------------------------------------------
    # The pre-field world, and the ordinary world afterwards: no record carries the key. The
    # gate must behave exactly as it would have before the field was conceived - a park-name
    # collision still blocks, distinct park names still pass - so nothing here depends on the
    # canonical schema having grown `unit` at all.
    print("\n5. the gate is correct with NO `unit` field anywhere in the dataset")
    no_unit_bad = [prop(1, "Kestrel Reach"), prop(2, "Kestrel Reach")]
    ck(all("unit" not in p for p in no_unit_bad), "the fixture really carries no `unit` key")
    rb = coverage(no_unit_bad)
    ck(rb.returncode != 0 and "identical card title" in rb.stdout
       and "Kestrel Reach" in rb.stdout,
       "two identical park names block on the park alone")
    rg = coverage([prop(1, "Kestrel Reach"), prop(2, "Harrier Point")])
    ck(rg.returncode == 0 and "identical card title" not in rg.stdout,
       "two different park names pass")

    # ---------------- 6. two BLANK headings are the purest collision -----------------------
    # `park` is NOT in the coverage gate's core-fill set, so nothing else stops two records
    # with no park name from shipping. `titleStr` returns falsy for them, and the card's own
    # `<h3>` and the comparison table's column header interpolate it with NO fallback, so both
    # cards ship a BLANK heading. Skipping the empty title as "nothing to compare" would be a
    # miss, not a kindness.
    print("\n6. two records that compose NO title collide (the chrome draws two blanks)")
    for label, props in (
            ("both sentinel parks", [prop(1, "tbd"), prop(2, "tbd")]),
            ("both empty parks", [prop(1, ""), prop(2, "")]),
            ("one sentinel, one empty - the same blank heading either way",
             [prop(1, "tbd"), prop(2, "")])):
        r6 = coverage(props)
        ck(r6.returncode != 0 and "identical card title" in r6.stdout, f"{label}: blocks")
        ck("EMPTY" in r6.stdout and "id=1" in r6.stdout and "id=2" in r6.stdout,
           f"{label}: ...and the message says the heading is EMPTY rather than sending the "
           f"reader off to look for a title, naming both ids")

    # ---------------- 7. the chrome's rule is still the rule this copies ------------------
    # THE COST OF DUPLICATING, PAID HERE. These markers are the exact clauses
    # `gate_runner._card_title` mirrors. If `titleStr` is rewritten, this section goes red and
    # names the file to look at, which is the whole reason the duplication is acceptable.
    print("\n7. titleStr's rule markers are still present in the chrome")
    tmpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")
    for marker, why in (
            ("function titleStr(p){", "the composition still lives in titleStr"),
            ("isAbsent(p.park)", "a sentinel park is still absence"),
            ("isAbsent(p.unit)", "a sentinel unit is still absence"),
            ('replace(/[^a-z0-9]+/g, " ")',
             "the comparison still reduces both sides to alphanumeric words"),
            ('(" " + n + " ").indexOf(" " + u + " ")',
             "suppression is still a WHOLE-TOKEN run anywhere in the park string"),
            ('return name + " " + unit;', "the join is still a single space"),
            ('class="card-title">${titleStr(p)}', "the card heading still comes from it")):
        ck(marker in tmpl, f"{why} ({marker!r})")

    print(f"\n{'FAILED: ' + str(len(fails)) if fails else 'ALL PASS'}")
    for f in fails:
        print(f"  - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
