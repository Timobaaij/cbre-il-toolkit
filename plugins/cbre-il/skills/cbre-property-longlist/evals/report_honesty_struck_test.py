#!/usr/bin/env python3
"""report_honesty_struck_test.py - the honesty report must not contradict the strike ledger,
and the coverage gate must catch an over-MERGE as well as an over-split. (A11, A14b)

Two holes in the same seam: a value a source DID state, that the pipeline then discarded, was
reported as a value no source ever stated.

  A11 - `gaps_report` derived every unknown from whether the VALUE looks unknown and never from
        WHY, so a field the plausibility band struck to the unknown sentinel was indistinguishable
        from a field nothing ever mentioned. Two statements in the delivered Gaps Report were
        therefore false, in the one document a client reads to learn what is missing:
          * "Fields no source provided for any longlist entry" listed a field struck on EVERY
            property, under a heading asserting that no input carried it for any option and that
            this market does not quote it - while the same document's Source conflicts section
            named the file and quoted the parsed figure;
          * the per-property note read "not stated in any source supplied for this property"
            against a field whose own ledger row, printed lower down, named its source.
        A live G-honesty review read exactly that contradiction back off a delivered report.
        `meta.struck` is now consulted, so a struck field is subtracted from the "no source
        provided" inventory and gets a note that points at the conflict and the remedy.
  A14b- `cmd_coverage` blocked a duplicate property (an over-SPLIT: one building shipped as two
        cards) and had no counterpart for the opposite, more dangerous error - two different
        buildings fused into one card, which the skill's own reference documentation until
        recently called structurally impossible. Only GREY pairs are enumerated for adjudication,
        so a fused pair is appealable by nobody and visible to nothing. Two contributing records
        that state DIFFERENT postal codes now block.
  A14d- that block and the matcher's own veto judge THE SAME FACT - do these two records state
        conflicting codes - and they judged it with two different normalisers. The veto removes
        all whitespace and upper-cases (`match._stated_postcode`); the gate keyed on
        `str(entry["postcode"] or "").strip()`. Measured over the 35 pairs in section 6b, 15
        disagreed: 14 where the gate BLOCKED a fusion the veto had deliberately allowed (one
        code written 'QX41 7ZP' on one side and 'QX417ZP' on the other), naming a remedy that
        would have unfused a correct merge, and 1 where the gate was BLIND to a conflict the
        veto vetoes (a numeric 0, which `or ""` reads as absence). A backstop that judges the
        fact differently from the guard it backs is not a backstop, so the gate now borrows the
        veto's own reader and section 6b asserts the agreement itself from one shared list.

Postal codes here are INVENTED and deliberately mixed in format (letters-and-digits, all-digit,
digits-then-letters) - the check must hold for any country's format, must treat an absent code as
no signal rather than a disagreement, and must be completely inert where no record carries a code
at all. Sections 6 and 7 assert all three.

Both `meta.struck` and `meta.clusterSources` are treated as OPTIONAL by their consumers, exactly
as `meta.enrichmentGaps` and `meta.conflicts` already are: an older work directory, or a merge
that recorded neither, must behave precisely as it does today. Section 5 and section 7 pin that,
because a consumer that needs a producer is a consumer that breaks a resumed run.

Fixtures are hand-written canonicals, never a live merge - the point is the CONSUMER's reading of
the two artefacts, and a fixture cannot go green because a producer happened to change shape.

Offline, no network, no build. Run: python evals/report_honesty_struck_test.py"""
from __future__ import annotations

import contextlib
import io
import itertools
import json
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import deliver as DEL  # noqa: E402
# A14d drives the two sides of ONE fact against each other, so all three modules are imported:
# the matcher whose veto owns the judgement, the gate that backs it up, and the PRODUCER of the
# values the gate reads (whose own private copy is the residual section 6b pins).
import gate_runner as GR  # noqa: E402
import match as M  # noqa: E402
import merge as MG  # noqa: E402

# The heading `honesty_test.py` pins. Written out ONCE here and asserted against both the
# generated report and that eval's own source, so the two cannot drift apart silently.
INV_HEAD = "## Fields no source provided for any longlist entry"
OTHER_HEAD = "## Other missing fields by property"
ABSENT_NOTE = "not stated in any source supplied for this property"

# `country` is a deliberately unassigned code and every name is invented: nothing in this file
# may identify a client, a country or a real property.
CITY = "Northport"
DEV = "Ardent Estates"


def prop(pid: int, park: str, **over) -> dict:
    """One shipped property, core-complete so the coverage gate's fill check cannot fire and
    mask (or fake) an over-merge verdict. Distinct areas keep the dedupe check quiet too."""
    p = {"id": pid, "park": park, "city": CITY, "country": "ZZ", "developer": DEV,
         "status": "Built", "photo": "x", "warehouseArea": 10000 + pid,
         "warehouseRent": "9.50", "clearHeight": "12 m", "earlyAccess": "now",
         "motorway": "A1", "lat": 1.0, "lng": 2.0}
    p.update(over)
    return p


def strike(pid: int, field: str, value, src: str, loc: str = "page 4") -> dict:
    """One `meta.struck` row, in the frozen shape merge writes."""
    return {"id": pid, "field": field, "value": value, "source_file": src, "locator": loc}


def report(props: list, meta: dict | None = None) -> str:
    return DEL.gaps_report({"meta": meta or {}, "properties": props}, "T")


def section(md: str, head: str) -> str:
    """The body of one `## ` section, or "" when the section was not printed at all."""
    return md.split(head, 1)[1].split("\n## ", 1)[0] if head in md else ""


def line_for(md: str, pid: int) -> str:
    """The `- **Park** (City, id N): ...` line for one property inside the chase section."""
    for ln in section(md, OTHER_HEAD).splitlines():
        if ln.startswith("- ") and f"id {pid})" in ln:
            return ln
    return ""


def note_for(md: str, pid: int, field: str) -> str:
    """The note the chase line carries for ONE field on ONE property, isolated from the
    other fields on the same line. One line legitimately mixes both kinds of note (a struck
    field beside a genuinely absent one), so a whole-line assertion would prove nothing."""
    ln = line_for(md, pid)
    if not ln:
        return ""
    for item in ln.split(f"id {pid}): ", 1)[-1].split("; "):
        if item.startswith(f"`{field}` ("):
            return item[len(field) + 4:].rstrip(")")
    return ""


_TMP: list = []          # one scratch dir for the whole run, not one per gate invocation


def _canon(props: list, meta: dict | None = None) -> Path:
    """Write a hand-built canonical and return its path. A DISTINCT filename each time:
    `_common.load_canonical` caches on (mtime_ns, size, st_ino), and two same-size writes to
    one path inside a single coarse mtime tick is exactly the collision that cache guards
    against - but a fresh name never depends on the guard holding."""
    if not _TMP:
        _TMP.append(Path(tempfile.mkdtemp(prefix="cbre_struck_")))
    f = _TMP[0] / f"canonical_{len(list(_TMP[0].glob('canonical_*.json')))}.json"
    f.write_text(json.dumps(
        {"meta": meta or {}, "properties": props, "pois": [], "regions": {}}),
        encoding="utf-8")
    return f


def coverage(props: list, meta: dict | None = None):
    """Run the real G-coverage gate in a subprocess, so the exit code is the gate's own."""
    return subprocess.run(
        [sys.executable, str(HELPERS / "gate_runner.py"), "coverage", str(_canon(props, meta))],
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

    # ---------------- 1. the strike-ledger reader ----------------------------------------
    # It runs while a client deliverable is being written, so no shape of one meta key may
    # cost the whole Gaps Report.
    print("1. the strike ledger is read defensively (it runs mid-delivery)")
    m = DEL._struck_map({"struck": [strike(4, "epc", "C55", "alpha-deck.pdf")]})
    ck(m.get(("4", "epc"), {}).get("source_file") == "alpha-deck.pdf",
       "an int id is keyed as a STRING, so a property's own id looks it up")
    ck(DEL._struck_map({}) == {} and DEL._struck_map({"struck": None}) == {},
       "an absent or null ledger is an empty map, never an exception")
    ck(DEL._struck_map({"struck": ["nope", None, 7, {"field": "epc"}, {"id": 1},
                                   {"id": 2, "field": "  "}]}) == {},
       "a malformed row (not an object, no id, no field, a blank field) is skipped silently")

    # ---------------- 2. struck on EVERY property ----------------------------------------
    # The headline false statement. THREE fields, one per honest outcome, so the sections
    # have to separate them rather than agreeing by luck:
    #   `epc`           - unknown on both, struck on both: a field a source DID state.
    #   `serviceCharge` - unknown on both, struck on neither: a field nothing stated, which
    #                     is the inventory's own case and must stay in it.
    #   `sprinklers`    - carried by one, unknown on the other: the ordinary chase, whose
    #                     note must be untouched by any of this.
    print("\n2. a field struck on EVERY property is not one 'no source provided'")
    all_struck = [prop(1, "Alpha Court", epc="tbd", serviceCharge="tbd", sprinklers="tbd"),
                  prop(2, "Beta House", epc=None, serviceCharge="tbd", sprinklers="ESFR")]
    meta_all = {"struck": [strike(1, "epc", "C55", "alpha-deck.pdf"),
                           strike(2, "epc", "C61", "beta-deck.pdf")],
                "conflicts": ["id 1 epc: the parsed value 'C55' (from alpha-deck.pdf) falls "
                              "outside the epc plausibility band",
                              "id 2 epc: the parsed value 'C61' (from beta-deck.pdf) falls "
                              "outside the epc plausibility band"]}
    md = report(all_struck, meta_all)
    inv = section(md, INV_HEAD)
    ck(inv != "", "the inventory section is still printed (a genuinely absent field remains)")
    ck("`epc`" not in inv,
       "a field struck on every property is NOT listed as one no input carried")
    ck("`serviceCharge`" in inv,
       "...while a field nothing ever stated IS still listed there (the section still works)")
    for pid, src in ((1, "alpha-deck.pdf"), (2, "beta-deck.pdf")):
        note = note_for(md, pid, "epc")
        ck("plausibility band" in note,
           f"id {pid}: the struck field is chased per property, as a failed parse")
        ck(src in note, f"id {pid}: ...naming the source that DOES state it ({src})")
        ck(ABSENT_NOTE not in note,
           f"id {pid}: ...and never the false 'not stated in any source' note")
    _e1 = note_for(md, 1, "epc")
    ck("Source conflicts" in _e1 and "work/repairs.json" in _e1,
       "the struck note points at the conflicts section and at the honest remedy")
    # ONE line, BOTH kinds of note: the struck field and the ordinary absent field sit side
    # by side on id 1, which is what "reads correctly on each" has to mean at field level.
    ck(note_for(md, 1, "sprinklers") == DEL._close_note("sprinklers"),
       "the ordinary absent-field note on the SAME line is byte-for-byte today's note")
    ck(md.count(ABSENT_NOTE) == 1,
       f"exactly one note in the whole document claims an absence, and it is the true one "
       f"(got {md.count(ABSENT_NOTE)})")

    # ---------------- 3. the PARTIAL case ------------------------------------------------
    # A band strikes a field on some properties while no source ever stated it on the rest.
    # The two lines must disagree with each other, because the facts do.
    print("\n3. struck on SOME properties: every line reads on its own merit")
    part = [prop(1, "Alpha Court", epc="tbd"), prop(2, "Beta House", epc="tbd"),
            prop(3, "Gamma Point", epc="B42")]
    md = report(part, {"struck": [strike(1, "epc", "C55", "alpha-deck.pdf")]})
    ck("plausibility band" in line_for(md, 1) and "alpha-deck.pdf" in line_for(md, 1),
       "the STRUCK property points at its source and the failed parse")
    ck(ABSENT_NOTE in line_for(md, 2) and "plausibility band" not in line_for(md, 2),
       "the genuinely ABSENT property keeps the original note, unchanged")
    ck("`epc`" not in line_for(md, 3),
       "the property that carries a real value is not chased at all")

    # 3b. the same partial split with NOBODY carrying a surviving value - the shape that
    # `carried` alone cannot see, so the field reaches the chase list only via the ledger.
    md = report(part[:2], {"struck": [strike(1, "epc", "C55", "alpha-deck.pdf")]})
    ck("`epc`" not in section(md, INV_HEAD),
       "with no surviving value anywhere, a field struck on ONE property is still not "
       "reported as one no input carried")
    ck("plausibility band" in line_for(md, 1),
       "...the struck property is named, so the strike cannot go silent")
    ck(ABSENT_NOTE in line_for(md, 2) and "plausibility band" not in line_for(md, 2),
       "...and the property nothing stated it for still reads as absent")

    # a strike row that no longer bites (the value was repaired, overridden, or another
    # source's value won) must not resurrect a closed gap
    md = report([prop(1, "Alpha Court", epc="C55")],
                {"struck": [strike(1, "epc", "C55", "alpha-deck.pdf")]})
    ck("`epc`" not in md, "a strike row against a field that now holds a value lists nothing")

    # A STRIKE ON A FIELD THE CHASE SECTION DOES NOT OWN is inert there, deliberately. The ten
    # CORE fields report through "Missing data by property" instead, whose note is bespoke
    # chase advice rather than an absence claim, so there was no false statement to correct
    # and that section is left exactly as it was; a strike naming a field no property carries
    # at all belongs to no section. Pinned so the scope boundary is a recorded decision rather
    # than an omission, and so neither shape can crash a delivery or duplicate a line.
    md = report([prop(1, "Alpha Court", warehouseArea=None)],
                {"struck": [strike(1, "warehouseArea", 613779, "alpha-deck.pdf"),
                            strike(1, "notAFieldAnyoneCarries", "x", "alpha-deck.pdf")]})
    ck("Missing data by property" in md and "`warehouseArea`" in md,
       "a struck CORE field still reports through the CORE section (its own, unchanged, note)")
    ck("`warehouseArea`" not in section(md, OTHER_HEAD)
       and "`warehouseArea`" not in section(md, INV_HEAD),
       "...and does not leak a second line into the other two sections")
    ck("notAFieldAnyoneCarries" not in md,
       "a strike naming a field no property carries adds nothing to any section")

    # ---------------- 4. the pinned heading ---------------------------------------------
    print("\n4. the heading another eval pins is byte-identical")
    ck(INV_HEAD in report(all_struck, meta_all), "the report still emits it verbatim")
    ck(INV_HEAD in (ROOT / "evals" / "honesty_test.py").read_text(encoding="utf-8"),
       "honesty_test.py still pins the same string (the two have not drifted)")
    ck(INV_HEAD in (HELPERS / "deliver.py").read_text(encoding="utf-8"),
       "...and deliver.py still writes that exact literal")

    # ---------------- 5. an OLDER work directory is unchanged ---------------------------
    # `meta.struck` is optional. Without it the report must be what it is today, to the byte.
    print("\n5. absent meta.struck leaves the report exactly as it is today")
    base = report(part[:2])
    ck("`epc`" in section(base, INV_HEAD),
       "with no ledger the field is reported as one no source provided (today's behaviour)")
    ck(line_for(base, 1) == "" and line_for(base, 2) == "",
       "...and, unknown on every property, it draws no per-property chase line either - "
       "inventory-only, exactly as before (the struck path is what ADDS the line)")
    _no_ledger = report(part)          # the same fixture where a third property carries it
    ck(note_for(_no_ledger, 1, "epc") == DEL._close_note("epc")
       and note_for(_no_ledger, 2, "epc") == DEL._close_note("epc"),
       "...and where a chase line does exist, both notes are byte-for-byte today's note")
    ck("plausibility band" not in base, "...with no strike wording anywhere in the document")
    for label, meta in (("an empty ledger", {"struck": []}),
                        ("a null ledger", {"struck": None}),
                        ("an all-malformed ledger", {"struck": [None, {"id": 1}]})):
        ck(report(part[:2], meta) == base, f"{label} produces a BYTE-IDENTICAL report")

    # ---------------- 6. the over-merge block ------------------------------------------
    print("\n6. two contributing records stating different postal codes BLOCK")
    two = [prop(1, "Alpha Court"), prop(2, "Beta House")]

    def cs(pid, *entries):
        return {"clusterSources": {str(pid): [{"file": f, "postcode": c} for f, c in entries]}}

    r = coverage(two, cs(1, ("alpha-deck.pdf", "AB12 3CD"), ("tracker.xlsx", "XY9 8ZZ")))
    ck(r.returncode != 0 and "BLOCKED" in r.stdout,
       f"a fused pair with two stated codes blocks {ascii(r.stdout[-70:])}")
    ck("over-merge" in r.stdout and "id=1" in r.stdout, "...naming the property id")
    for tok in ("alpha-deck.pdf", "AB12 3CD", "tracker.xlsx", "XY9 8ZZ"):
        ck(tok in r.stdout, f"...and both files and both codes ({tok}), so nobody must open "
                            f"the work directory to act")
    ck("strike_from_source" in r.stdout, "...with the remedy named (the house rule for a block)")

    # THE SAME-SOURCE FUSION is now the ONLY residual auto path (A12b closed the other two by
    # moving the code veto to a single guard at the top of `_cross_source_auto`; `pair_class`
    # still answers its same-source branch and RETURNS before either cross-source tier runs, so
    # the veto never reaches it). It is a real shape, and `strike_from_source` is the WRONG verb
    # for it: it
    # withdraws everything that file gave the property rather than splitting the rows. A
    # refusal that names a remedy which would do something else is worse than one that names
    # none, so the message has to branch on it.
    r5 = coverage(two, cs(1, ("tracker.xlsx", "AB12 3CD"), ("tracker.xlsx", "AB12 4EF")))
    ck(r5.returncode != 0 and "over-merge" in r5.stdout,
       "two rows of ONE file stating two codes block as well (the same-source residual)")
    ck("AB12 3CD" in r5.stdout and "AB12 4EF" in r5.stdout and "tracker.xlsx" in r5.stdout,
       "...naming the file and both codes")
    ck("strike_from_source` cannot separate" in r5.stdout,
       "...and saying plainly that the unfuse verb cannot separate them")
    ck("work/overrides.json" in r5.stdout,
       "...pointing instead at the remedy that can (correct the code at source, re-run)")

    # the same verdict in two other countries' formats: all-digit, and digits-then-letters.
    # Plain inequality only - no shared prefix is ever read as agreement.
    for a, b in (("28860", "28820"), ("1234 AB", "1299 ZX"), ("AB12 3CD", "AB12 9ZZ")):
        r2 = coverage(two, cs(1, ("alpha-deck.pdf", a), ("tracker.xlsx", b)))
        ck(r2.returncode != 0,
           f"{a!r} vs {b!r} blocks too - any format, and a shared prefix is NOT agreement")

    # three contributing records, three codes: every one is named
    r3 = coverage(two, cs(1, ("a.pdf", "AB12 3CD"), ("b.pdf", "XY9 8ZZ"), ("c.xlsx", "QQ1 1QQ")))
    ck(r3.returncode != 0 and all(t in r3.stdout for t in ("a.pdf", "b.pdf", "c.xlsx")),
       "three disagreeing records are all named, not just the first pair")

    # only the offender is reported
    both = {"clusterSources": {
        "1": [{"file": "a.pdf", "postcode": "AB12 3CD"},
              {"file": "b.xlsx", "postcode": "XY9 8ZZ"}],
        "2": [{"file": "c.pdf", "postcode": "QQ1 1QQ"},
              {"file": "d.xlsx", "postcode": "QQ1 1QQ"}]}}
    r4 = coverage(two, both)
    ck(r4.stdout.count("over-merge") == 1 and "id=1" in r4.stdout and "id=2" not in r4.stdout,
       "a property whose records AGREE is not reported alongside one whose records do not")

    # ---------------- 6b. A14d: the veto and this gate judge ONE fact ------------------
    # THE ASSERTION HERE IS THE AGREEMENT ITSELF, so both sides are driven from ONE list of
    # pairs and each verdict is compared with the OTHER side's - never with a hand-written
    # expectation, which is exactly how two guards come to be pinned separately and drift
    # anyway. `match._postcode_conflict` VETOES an auto merge across two stated codes; this
    # gate BLOCKS a fusion that happened regardless. They are the guard and the backstop for
    # ONE failure, and a backstop that normalises the code differently from the guard it backs
    # is not a backstop. It fails in BOTH directions: it can refuse a fusion the veto
    # deliberately allowed - naming a remedy that would then unfuse a correct merge - and it
    # can be blind to a disagreement the veto would have caught.
    #
    # MEASURED over exactly the pairs below: 15 of 35 disagreed before the fix. 14 were the
    # false-refusal direction (one code written 'QX41 7ZP' on one side and 'QX417ZP' on the
    # other is ONE code to the veto, which removes all whitespace, and was TWO codes to a gate
    # that only trimmed the ends) and 1 was the blind direction (a numeric 0, which the gate's
    # `or ""` read as absence and the veto reads as the code '0'). After it: 0 of 35, and not
    # because a second normaliser was tuned to agree - the gate no longer normalises at all.
    #
    # THE INPUTS ARE CHOSEN TO CATCH NORMALISATION DRIFT, not to look realistic: differing
    # case, internal, leading and trailing whitespace, a NON-BREAKING space (which no reader
    # can see), numeric cells (int, integral float, non-integral float, zero), a bool, every
    # unknown-value sentinel, an omitted field, and several countries' shapes. EVERY CODE IS
    # INVENTED and the formats are mixed deliberately - the discipline `overmerge_guard_test`
    # states at its own top - because quoting one real national format is how the next
    # maintainer comes to write a parser for it.
    print("\n6b. A14d: the matcher's veto and this gate agree about every code pair")
    OMIT = object()          # the record OMITS the field, rather than stating an empty one
    NBSP = "\u00a0"
    PAIRS = [
        ("QX41 7ZP", "QX417ZP", "internal spacing: one code written two ways"),
        ("QX41  7ZP", "QX41 7ZP", "a doubled internal space"),
        (f"QX41{NBSP}7ZP", "QX417ZP", "a NON-BREAKING space, invisible to a reader"),
        (" QX417ZP ", "QX417ZP", "leading and trailing whitespace"),
        ("qx417zp", "QX417ZP", "case alone"),
        ("qx41 7zp", "QX417ZP", "case AND spacing together"),
        ("QX417ZP", "QX523AA", "two genuinely different codes"),
        ("QX41 7ZP", "QX41 7ZQ", "two codes one character apart (a keying error)"),
        ("QX41", "QX417ZP", "a PREFIX is not agreement"),
        ("48215", "48215", "an all-digit format, equal"),
        ("48215", "48216", "an all-digit format, different"),
        (48215, 48215, "the same all-digit code as a NUMERIC cell on both sides"),
        (48215, "48215", "a numeric cell against the same code as text"),
        (48215, 48216, "two numeric cells, different"),
        (48215.0, 48215, "an integral float against an int"),
        (1234.5, "QX417ZP", "a non-integral number is not a code at all"),
        (True, "QX417ZP", "a bool is not a code either"),
        (False, "QX417ZP", "...in either state"),
        (0, "QX417ZP", "a numeric ZERO is a stated code, not a falsy absence"),
        (0, 0, "...and two of them agree"),
        ("1234 AB", "1234AB", "digits-then-letters: one code written two ways"),
        ("1234 AB", "1299 ZX", "digits-then-letters: two codes"),
        ("300-0002", "300-0002", "a hyphenated format, equal"),
        ("300-0002", "150-0007", "a hyphenated format, different"),
        ("300-0002", "3000002", "a hyphen is NOT whitespace, so these stay two codes"),
        ("tbd", "QX417ZP", "an unknown sentinel is ABSENCE"),
        ("TBC", "QX417ZP", "...in any case"),
        ("n/a", "QX417ZP", "...and in any spelling"),
        ("-", "QX417ZP", "...including a bare dash"),
        ("tbd", "tbc", "two sentinels are not two agreeing codes either"),
        ("", "QX417ZP", "an empty string is absence"),
        ("   ", "QX417ZP", "so is whitespace only"),
        (None, "QX417ZP", "so is an explicit null"),
        (OMIT, "QX417ZP", "so is a record that omits the field"),
        (OMIT, OMIT, "neither side states anything at all"),
    ]

    def veto(a, b) -> bool:
        """THE MATCHER'S SIDE: does the auto-merge veto see a disagreement?"""
        return M._postcode_conflict({} if a is OMIT else {"postcode": a},
                                    {} if b is OMIT else {"postcode": b})

    def entry(f, v) -> dict:
        e = {"file": f}
        if v is not OMIT:
            e["postcode"] = v
        return e

    def gate_over_merge(a, b) -> bool:
        """THIS GATE'S SIDE: does the real `cmd_coverage` report an over-merge for a property
        built from two records stating `a` and `b`?

        The REAL entry point, run IN-PROCESS: a 35-pair sweep through `coverage()` above would
        pay 35 interpreter starts, and the values survive the JSON round trip either way (an
        int stays an int and a float stays a float, which is the whole point of the numeric
        rows). The two harnesses are spot-checked against each other below, because an
        in-process copy that had drifted from the shipped entry point would make every
        assertion in this section vacuous.

        Keyed on the FINDING, not on the exit code: the fixture is core-complete so nothing
        else can fire, but a check added to this gate later must not be able to turn the sweep
        green by failing for its own reasons."""
        meta = {"clusterSources": {"1": [entry("a.pdf", a), entry("b.xlsx", b)]}}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            GR.cmd_coverage(Namespace(canonical=str(_canon(two, meta)), fill_threshold=0.6))
        return "over-merge" in buf.getvalue()

    ck(not gate_over_merge(OMIT, OMIT) and gate_over_merge("QX417ZP", "QX523AA"),
       "the in-process harness reproduces the gate: silent on nothing, blocking on two codes")
    for a, b in (("QX417ZP", "QX523AA"), ("QX41 7ZP", "QX417ZP")):
        sub = coverage(two, {"clusterSources": {"1": [entry("a.pdf", a),
                                                      entry("b.xlsx", b)]}})
        ck(("over-merge" in sub.stdout) == gate_over_merge(a, b),
           f"...and the SUBPROCESS gate agrees with it on {a!r} vs {b!r}, so the sweep below "
           f"measures the shipped entry point")

    for a, b, why in PAIRS:
        v, g = veto(a, b), gate_over_merge(a, b)
        sa = "OMIT" if a is OMIT else repr(a)
        sb = "OMIT" if b is OMIT else repr(b)
        ck(v == g, f"{'CONFLICT' if v else 'agrees  '}  {sa} vs {sb}: veto={v}, gate={g} "
                   f"[{why}]")
    # NOT VACUOUS: two guards that both answered False to everything would sail through the
    # sweep above, so each side is required to have FIRED on some of these pairs - and on the
    # same number of them, which a sweep of per-pair equalities already implies but states
    # here as one readable line.
    ck(sum(veto(a, b) for a, b, _ in PAIRS)
       == sum(gate_over_merge(a, b) for a, b, _ in PAIRS) > 0,
       "both sides fire on the SAME NUMBER of these pairs, and on more than none of them")

    # AND THE AGREEMENT IS STRUCTURAL, NOT A COINCIDENCE OF TWO IMPLEMENTATIONS. The sweep
    # would go green for two separate normalisers that happen to agree on these 35 pairs and
    # part company on the 36th - precisely the state this fix replaced. So the SOURCE is
    # asserted too: the gate holds no private copy of the normalisation at all.
    gr_src = (HELPERS / "gate_runner.py").read_text(encoding="utf-8")
    i = gr_src.find("\ndef cmd_coverage(")
    j = gr_src.find("\ndef ", i + 1)
    body = gr_src[i:j if j != -1 else len(gr_src)]
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    ck(bool(body) and "_stated_postcode(" in code,
       "cmd_coverage BORROWS the veto's reader for its equality key")
    ck("import match" in code,
       "...imported inside the check that needs it (gate_runner is imported by final_gate, "
       "run and deliver, and match pulls rapidfuzz)")
    # Counted over EXECUTABLE lines only: this codebase records what a guard replaced, so the
    # retired expression is quoted in the comments on purpose and a raw scan would match the
    # block's own changelog.
    for retired in ('"postcode"', 'or "").strip()'):
        ck(retired not in code,
           f"...and names no postal field itself, so there is nothing left to drift "
           f"(`{retired}` is gone from what executes)")
    ck(callable(getattr(M, "_stated_postcode", None)) and bool(M._POSTCODE_FIELDS),
       "the borrowed names still exist in match, so a rename lands HERE and not mid-run")
    # THE FIELD LIST IS SHARED TOO, because the whole ENTRY is handed to the reader rather than
    # one field picked out of it: a column name added to `_POSTCODE_FIELDS` is read by the veto
    # and by this gate in the same commit, instead of one of the two going half-blind.
    ck("over-merge" in coverage(two, {"clusterSources": {"1": [
           {"file": "a.pdf", "postalCode": "QX417ZP"},
           {"file": "b.xlsx", "postalCode": "QX523AA"}]}}).stdout,
       f"...so the gate reads every field name the veto reads {M._POSTCODE_FIELDS}")

    # THE PRODUCER DELEGATES TOO, so the chain is closed END TO END and these lines assert the
    # AGREEMENT rather than recording a residual. `merge._stated_postcode` is what WRITES these
    # values, and it was a third private copy: trimmed and upper-cased without removing internal
    # whitespace, read only `postcode`, and stringified with `str()`. All 9 of the 9 measured
    # end-to-end disagreements are now closed - 5 when the GATE borrowed the shared reader, and
    # the last 4 when the PRODUCER did. Those 4 were the float and bool cases, and they were the
    # dangerous direction: merge wrote '48215.0' where the veto reads 48215 and 'TRUE' where the
    # veto reads absence, so the gate BLOCKED a fusion the veto had allowed and named a repair
    # that would have unfused a correct merge. They could not be closed in the gate, because a
    # rule collapsing a trailing '.0' would diverge from the veto on the genuine STRING
    # '48215.0'. Each pair below is asserted against the VETO'S OWN verdict rather than a
    # hand-written expectation, so reintroducing any of the three copies turns these red.
    print("\n   CLOSED: the producer delegates to the shared reader, so all three agree")
    for a, b, why in ((48215, 48215.0, "an int against an integral float"),
                      (1234.5, "QX417ZP", "a non-integral number, absence on both sides"),
                      (True, "QX417ZP", "a bool, absence on both sides")):
        stored = [MG._stated_postcode({"postcode": a}), MG._stated_postcode({"postcode": b})]
        ck(veto(a, b) == gate_over_merge(*stored),
           f"merge stores {stored} for {a!r} / {b!r}, so END TO END the two sides now AGREE "
           f"({why}) - the producer normalises with the veto's own reader")

    # A MARKET THAT QUOTES NO CODES AT ALL IS ENTIRELY UNAFFECTED, re-derived over every shape
    # of nothing rather than asserted once: absence, on either side, in any spelling, can never
    # reach the block.
    nothing = (OMIT, None, "", "   ", "tbd", "N/A", "-", "??")
    ck(not any(gate_over_merge(x, y) for x, y in itertools.product(nothing, repeat=2)),
       f"no pair of {len(nothing)} kinds of absence blocks, in either position "
       f"({len(nothing) ** 2} combinations)")
    # ...and a malformed value is absence too: not a block, and not a traceback. A gate that
    # raised here would abort the run with no scorecard fragment instead of failing honestly.
    for weird in ({"code": "QX417ZP"}, ["QX417ZP"], float("nan"), float("inf")):
        ck(not gate_over_merge(weird, "QX523AA"),
           f"a malformed entry value is absence, not a block and not a crash ({weird!r})")

    # ---------------- 7. every non-disagreement is inert -------------------------------
    print("\n7. the check is silent on anything that is not a disagreement")
    cases = [
        ("the two records state the SAME code", cs(1, ("a.pdf", "AB12 3CD"),
                                                  ("b.xlsx", "AB12 3CD"))),
        ("one record states a code and the other states none",
         cs(1, ("a.pdf", "AB12 3CD"), ("b.xlsx", ""))),
        ("neither record states a code", cs(1, ("a.pdf", ""), ("b.xlsx", ""))),
        ("NO record anywhere states a code (a country that quotes none)",
         {"clusterSources": {"1": [{"file": "a.pdf", "postcode": ""},
                                   {"file": "b.xlsx", "postcode": ""}],
                             "2": [{"file": "c.pdf", "postcode": ""}]}}),
        ("a record omits the postcode key entirely",
         {"clusterSources": {"1": [{"file": "a.pdf"}, {"file": "b.xlsx"}]}}),
        ("one record only (nothing to compare)", cs(1, ("a.pdf", "AB12 3CD"))),
        ("clusterSources is absent entirely (an older work directory)", {}),
        ("clusterSources is an empty map", {"clusterSources": {}}),
        ("a code disagrees under a key no shipped property has",
         {"clusterSources": {"99": [{"file": "a.pdf", "postcode": "AB12 3CD"},
                                    {"file": "b.xlsx", "postcode": "XY9 8ZZ"}]}}),
        ("clusterSources is the wrong SHAPE (a list, not a map)",
         {"clusterSources": [{"file": "a.pdf", "postcode": "AB12 3CD"}]}),
        ("the entries are the wrong shape (strings, not objects)",
         {"clusterSources": {"1": ["a.pdf", "b.xlsx"]}}),
        ("an entry is null", {"clusterSources": {"1": [None, None]}}),
        ("a property's whole entry is not even a list",
         {"clusterSources": {"1": 7, "2": "a.pdf"}}),
        ("a property's entry is a MAP of records (a plausible near-miss shape)",
         {"clusterSources": {"1": {"a.pdf": "AB12 3CD", "b.xlsx": "XY9 8ZZ"}}}),
    ]
    for label, meta in cases:
        r = coverage(two, meta)
        ck(r.returncode == 0 and "ALL-PASS" in r.stdout and "over-merge" not in r.stdout,
           f"{label}: ALL-PASS, no block, no crash {ascii(r.stdout[-40:])}")

    # the neighbouring checks are untouched: the over-SPLIT counterpart still blocks, and it
    # still blocks with clusterSources present and agreeing.
    print("\n   the over-SPLIT counterpart and the fill check still bite")
    dup = [prop(1, "Alpha Court"), prop(2, "Alpha Court", warehouseArea=10001)]
    r = coverage(dup)
    ck(r.returncode != 0 and "duplicate property" in r.stdout,
       "one building shipped as two cards still blocks (the check this one is modelled on)")
    r = coverage(dup, cs(1, ("a.pdf", "AB12 3CD"), ("b.xlsx", "AB12 3CD")))
    ck(r.returncode != 0 and "duplicate property" in r.stdout and "over-merge" not in r.stdout,
       "...and an agreeing cluster does not mask it")
    thin = [prop(1, "Alpha Court", warehouseArea=None, warehouseRent="tbd", status="tbd",
                 developer="tbd")]
    r = coverage(thin)
    ck(r.returncode != 0 and "core fill" in r.stdout, "the per-record fill check still blocks")

    print(f"\n{'OK' if not fails else 'FAIL'} report_honesty_struck_test: "
          f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
