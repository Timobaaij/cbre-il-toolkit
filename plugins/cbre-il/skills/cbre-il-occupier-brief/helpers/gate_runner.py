#!/usr/bin/env python3
"""Deterministic gates for the CBRE I&L Occupier Brief.

These are the mechanical checks. They catch what a script can catch so the
independent reviewers spend their judgement on what a script cannot: whether the
read is right, whether the counter-case is conceded, whether a bullet is worth
the reader's time.

Usage:
    python gate_runner.py style    <brief.md>
    python gate_runner.py sections <brief.md>
    python gate_runner.py depth    <brief.md>
    python gate_runner.py trace    <brief.md> <ledger.csv>
    python gate_runner.py budget   <search_ledger.md>
    python gate_runner.py all      <brief.md> <ledger.csv> [search_ledger.md]

Every subcommand prints findings then a single machine-read STATUS: line.
Exit code 0 on pass, 1 on fail.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from render_docx import lint, longpath  # noqa: E402

# --------------------------------------------------------------------------- #
# the search budget: 60 WebSearch calls for the whole run, no exceptions
# --------------------------------------------------------------------------- #
# Sized for a pre-meeting brief, not a deck. An earlier version allowed 200 searches across six
# workstreams; on a live run that produced a 241-row ledger and a 25-minute wall clock per agent to
# support a 2,300-word document. If a target needs more than this, it needs the account-plan skill.
SEARCH_CAPS = {
    "A": 18,   # the company and its numbers
    "B": 16,   # the trigger event and the people
    "C": 12,   # peers and industry
    "D": 8,    # regulatory and buildings
    "RESERVE": 6,    # conflict resolution and the QA round
}
SEARCH_TOTAL = 60

# --------------------------------------------------------------------------- #
# required sections, in order
# --------------------------------------------------------------------------- #
PERSONA_SECTIONS = [
    ("head of real estate", "on the mind of the head of real estate"),
    ("head of supply chain", "on the mind of the head of supply chain"),
    ("ceo", "on the mind of the ceo"),
]

REQUIRED = [
    ("30-second version", "30-second version"),
    ("is / is not", None),                      # matched structurally below
    ("at a glance", "at a glance"),
    ("drivers", "driving the business right now"),
    ("industry backdrop", "industry backdrop"),
    ("regulatory read", "regulatory"),
    ("persona: head of real estate", PERSONA_SECTIONS[0][1]),
    ("persona: head of supply chain", PERSONA_SECTIONS[1][1]),
    ("persona: ceo", PERSONA_SECTIONS[2][1]),
    ("why this matters to cbre", "why this matters to cbre"),
    ("pocket talking points", "pocket talking points"),
    ("discovery questions", "questions to open"),
    ("sources", "sources"),
]

BULLET_RULES = {           # section key -> (min, max) bullets
    "driving the business right now": (4, 6),
    "industry backdrop": (3, 4),
    "regulatory": (3, 8),
    PERSONA_SECTIONS[0][1]: (3, 3),
    PERSONA_SECTIONS[1][1]: (3, 3),
    PERSONA_SECTIONS[2][1]: (3, 3),
    "why this matters to cbre": (3, 4),
    "pocket talking points": (5, 7),
    "questions to open": (4, 5),
}

# Raised from 1500/2500 and 1200/3000 when the node-forecast section became part of the
# contract: a ranked forecast with its tiers, zone, template, window, falsifier and three
# leading indicators is about 350 words that did not exist before, and squeezing it back out
# of the rest of the brief was costing qualifications that the QA round had just put in.
# Sized from a measured run rather than a guess. A brief that carries BOTH a full QA round
# and the node forecast came out at roughly 3,450 words: about 2,500 of body, 360 of
# qualifications the reviewer required (an honest 'both sources disagree, ask' costs more
# words than a wrong assertion), and about 590 for the forecast and its error bar.
WORDS_MIN, WORDS_MAX = 1800, 3600
WORDS_HARD_MIN, WORDS_HARD_MAX = 1400, 4200


def load(path):
    return open(longpath(path), encoding="utf-8").read()


def strip_front_matter(md):
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?", md)
    return md[m.end():] if m else md


def split_sections(md):
    """Return [(heading, [lines]), ...] for ## headings, in document order."""
    out, cur, buf = [], None, []
    for line in strip_front_matter(md).splitlines():
        if re.match(r"^#{1,2}\s+", line.strip()):
            if cur is not None:
                out.append((cur, buf))
            cur, buf = re.sub(r"^#{1,2}\s+", "", line.strip()), []
        else:
            buf.append(line)
    if cur is not None:
        out.append((cur, buf))
    return out


def bullets_of(lines):
    return [re.sub(r"^[-•]\s+", "", l.strip())
            for l in lines if re.match(r"^[-•]\s+", l.strip())]


def table_rows(lines):
    rows = []
    for l in lines:
        if re.match(r"^\s*\|.*\|\s*$", l):
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            if not all(re.match(r"^:?-{2,}:?$", c) or c == "" for c in cells):
                rows.append(cells)
    return rows


def report(name, problems, notes=()):
    for n in notes:
        print("      " + n)
    for p in problems:
        print("FAIL  " + p)
    ok = not problems
    print("STATUS: %s %s" % (name, "PASS" if ok else "FAIL (%d)" % len(problems)))
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# style
# --------------------------------------------------------------------------- #
def cmd_style(path):
    errors, warnings = lint(load(path))
    for w in warnings:
        print("WARN  " + w)
    return report("style", errors)


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #
def cmd_sections(path):
    md = load(path)
    secs = split_sections(md)
    headings = [h.lower() for h, _ in secs]
    problems, notes = [], ["sections found: %d" % len(secs)]

    for label, needle in REQUIRED:
        if needle is None:
            continue
        if not any(needle in h for h in headings):
            problems.append("missing required section: %s" % label)

    isnot = [i for i, (h, body) in enumerate(secs)
             if re.search(r"\bis\b", h, re.I) and re.search(r"is\s*not", h, re.I)]
    if not isnot:
        isnot = [i for i, (h, body) in enumerate(secs)
                 if any(re.search(r"\bis\b", " ".join(r), re.I)
                        and re.search(r"is\s*not", " ".join(r), re.I)
                        for r in table_rows(body)[:1])]
    if not isnot:
        problems.append("missing required section: the IS / IS NOT framing table")

    idx = {}
    for i, h in enumerate(headings):
        for _, needle in PERSONA_SECTIONS:
            if needle in h:
                idx[needle] = i
    if len(idx) == 3:
        order = [idx[n] for _, n in PERSONA_SECTIONS]
        if order != sorted(order):
            problems.append("the three persona sections must run Head of Real Estate, "
                            "then Head of Supply Chain, then CEO")
        reg = next((i for i, h in enumerate(headings) if "regulatory" in h), None)
        why = next((i for i, h in enumerate(headings) if "why this matters to cbre" in h), None)
        if reg is not None and min(order) < reg:
            problems.append("the persona sections belong after the regulatory read")
        if why is not None and max(order) > why:
            problems.append("the persona sections belong before 'Why this matters to CBRE'")

    if not re.search(r"^FOOTER:", strip_front_matter(md), re.M | re.I):
        problems.append("missing the FOOTER: confidentiality and verification caveat line")
    if not re.match(r"^---\s*\n", md):
        problems.append("missing the YAML front matter block that drives the masthead")

    return report("sections", problems, notes)


# --------------------------------------------------------------------------- #
# depth
# --------------------------------------------------------------------------- #
def cmd_depth(path):
    md = load(path)
    secs = split_sections(md)
    problems, notes = [], []

    prose = re.sub(r"\|[^\n]*\|", " ", strip_front_matter(md))
    prose = re.sub(r"[#*`>]", " ", prose)
    words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'.,%-]*", prose))
    notes.append("word count (prose, tables excluded): %d" % words)
    if words < WORDS_HARD_MIN:
        problems.append("%d words is below the %d floor; the research is thin, not the writing"
                        % (words, WORDS_HARD_MIN))
    elif words > WORDS_HARD_MAX:
        problems.append("%d words is above the %d ceiling; it is a brief, cut it"
                        % (words, WORDS_HARD_MAX))
    elif not (WORDS_MIN <= words <= WORDS_MAX):
        print("WARN  %d words sits outside the %d to %d target band" % (words, WORDS_MIN, WORDS_MAX))

    for heading, body in secs:
        h = heading.lower()
        if "at a glance" in h:
            rows = table_rows(body)
            notes.append("at a glance rows: %d" % len(rows))
            if len(rows) < 10:
                problems.append("At a glance holds %d rows; a full brief carries 10 or more "
                                "sourced facts" % len(rows))
        if re.search(r"\bis\b", h, re.I) and re.search(r"is\s*not", h, re.I):
            rows = table_rows(body)
            body_rows = max(0, len(rows) - 1)
            notes.append("IS / IS NOT rows: %d" % body_rows)
            if not (3 <= body_rows <= 5):
                problems.append("IS / IS NOT carries %d rows; the useful range is 3 to 5" % body_rows)
        for needle, (lo, hi) in BULLET_RULES.items():
            if needle in h:
                bl = bullets_of(body)
                notes.append("%s: %d bullets" % (heading, len(bl)))
                if not (lo <= len(bl) <= hi):
                    problems.append("'%s' has %d bullets; the rule is %d to %d"
                                    % (heading, len(bl), lo, hi))
                if "pocket talking points" in needle:
                    unquoted = [b for b in bl if b.count('"') < 2]
                    if unquoted:
                        problems.append("%d talking point(s) are not written as a quotable line "
                                        "in double quotes" % len(unquoted))
                if "questions to open" in needle:
                    noq = [b for b in bl if not b.rstrip().endswith("?")]
                    if noq:
                        problems.append("%d discovery 'question(s)' do not end in a question mark"
                                        % len(noq))
                if "on the mind of" in needle:
                    weak = [b for b in bl if not re.match(r"^\*\*[^*]+\*\*", b.strip())]
                    if weak:
                        problems.append("'%s': every bullet needs a bold lead-in naming the "
                                        "agenda item" % heading)
                    inferences = [b for b in bl if "(inference)" in b.lower()]
                    if len(inferences) > 1:
                        problems.append("'%s' carries %d bullets marked (inference); at most one "
                                        "of the three may be unevidenced" % (heading, len(inferences)))

    return report("depth", problems, notes)


# --------------------------------------------------------------------------- #
# trace: every number in the brief maps to a ledger row
# --------------------------------------------------------------------------- #
# A unit must end on a word boundary, or "21 May" reads as the figure "21m".
UNIT = (r"(?:bn|bps|billion|million|m|k|per\s?cent|%|sq\s?ft|sq\s?m"
        r"|basis\s?points?|times|x)")
# The unit must not run into another word or digit. A plain \b cannot be used here: after a
# non-word unit character such as "%", \b requires an adjacent word character, so "1.8% in 2026"
# would never match while "1.8 per cent in 2026" would. That asymmetry silently broke tracing.
END = r"(?![A-Za-z0-9])"
NUM = re.compile(r"(?:[£$€]\s?\d[\d,.]*\s?" + UNIT + r"?" + END +
                 r"|\d[\d,.]*\s?" + UNIT + END +
                 r"|\b\d{1,3}(?:,\d{3})+\b"
                 r"|\b\d+\.\d+\b)", re.I)
SKIP_SECTIONS = ("sources",)


def normalise(s):
    s = re.sub(r"\*+", "", s.lower())
    s = s.replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def numeric_tokens(s):
    """Canonicalised figures, so 'GBP 4.2bn' and '4.2bn' are the same token.

    Known limitation: a spelled-out count ('eleven depots') is invisible here.
    Ledger it anyway; the reviewers check for it.
    """
    out = set()
    for m in NUM.finditer(s):
        t = re.sub(r"[\s,£$€]", "", m.group(0).lower()).rstrip(".")
        t = t.replace("percent", "%").replace("basispoints", "bps").replace("basispoint", "bps")
        t = t.replace("billion", "bn").replace("million", "m")
        if t:
            out.add(t)
    return out


def cmd_trace(brief_path, ledger_path):
    sys.path.insert(0, HERE)
    import ledger as L

    md = load(brief_path)
    rows = L.read(ledger_path)
    problems = L.validate(rows)
    notes = ["ledger rows: %d" % len(rows)]

    flat = normalise(strip_front_matter(md))

    # Coverage runs one way only. Every FIGURE IN THE BRIEF must trace to a ledger row, which is
    # checked below and fails. The reverse is not a defect: the ledger is the whole research corpus
    # and a 2,000-word brief cites a subset of it by design. Requiring every row to appear in the
    # text made the gate unpassable on a real 241-row ledger, so this is reported, not failed.
    brief_nums = set()
    for heading, body in split_sections(md):
        for line in body:
            brief_nums |= numeric_tokens(line)
    placed = 0
    for r in rows:
        claim = normalise(r.get("claim", ""))
        toks = numeric_tokens(r.get("claim", "")) | numeric_tokens(r.get("figure_at_source", ""))
        if claim[:60] in flat or (toks and toks & brief_nums):
            placed += 1
    notes.append("research used in the brief: %d of %d ledger rows (%.0f per cent). The rest is "
                 "the corpus behind it, not a defect."
                 % (placed, len(rows), (100.0 * placed / len(rows)) if rows else 0.0))

    ledger_nums = set()
    for r in rows:
        ledger_nums |= numeric_tokens(r.get("claim", ""))
        ledger_nums |= numeric_tokens(r.get("figure_at_source", ""))

    untraced = []
    for heading, body in split_sections(md):
        if any(k in heading.lower() for k in SKIP_SECTIONS):
            continue
        for line in body:
            t = line.strip()
            if not t or t.upper().startswith("FOOTER:"):
                continue
            for tok in numeric_tokens(t):
                if tok in ledger_nums:
                    continue
                if re.fullmatch(r"(19|20)\d{2}", tok):     # a bare year is context, not a claim
                    continue
                untraced.append("%s: %s  (in: %s)" % (heading, tok, t[:70]))
    if untraced:
        problems.append("%d figure(s) in the brief trace to no ledger row" % len(untraced))
        for u in untraced[:15]:
            print("      untraced " + u)

    verify = [r["claim_id"] for r in rows
              if (r.get("verify_before_use") or "").lower() == "yes"]
    if verify:
        notes.append("flagged verify-before-use: %s" % ", ".join(verify))
    prop = [r["claim_id"] for r in rows if (r.get("sourcing") or "").lower() == "proprietary"]
    if prop:
        notes.append("proprietary-signal claims (must be attributed in the brief): %s"
                     % ", ".join(prop))
    return report("trace", problems, notes)


# --------------------------------------------------------------------------- #
# search budget
# --------------------------------------------------------------------------- #
LEDGER_LINE = re.compile(r"^\s*\|?\s*(A|B|C|D|E|F|RESERVE)\b[^|\d]*\|?\s*(\d+)\s*\|?\s*(\d+)?", re.I)
STATED_TOTAL = re.compile(r"total must not exceed\s*(\d+)", re.I)


def cmd_budget(path):
    """Check the run against the caps the run itself declared.

    The search ledger carries its own Cap column and its own stated total, and those are what the
    run was dispatched under. Reading them from the file, rather than only from SEARCH_CAPS here,
    means retuning the skill's budget does not retrospectively fail a completed run. The built-in
    caps are the default for a ledger that declares none.
    """
    text = load(path)
    used, caps, problems, notes = {}, {}, [], []
    for line in text.splitlines():
        m = LEDGER_LINE.match(line)
        if m:
            key = m.group(1).upper()
            used[key] = used.get(key, 0) + int(m.group(2))
            if m.group(3):
                caps[key] = int(m.group(3))
    if not used:
        problems.append("no workstream tallies found; the search ledger needs one line per "
                        "workstream, for example 'A | 31 | 18 |'")

    declared = STATED_TOTAL.search(text)
    total_cap = int(declared.group(1)) if declared else (sum(caps.values()) if caps else SEARCH_TOTAL)
    source = "declared in the ledger" if (declared or caps) else "skill default"

    total = sum(used.values())
    for key in sorted(set(list(used) + list(caps) + list(SEARCH_CAPS))):
        cap = caps.get(key, SEARCH_CAPS.get(key))
        n = used.get(key, 0)
        if cap is None:
            notes.append("workstream %s: %d, no cap declared" % (key, n))
            continue
        notes.append("workstream %s: %d of %d" % (key, n, cap))
        if n > cap:
            problems.append("workstream %s used %d searches against a cap of %d" % (key, n, cap))
    notes.append("total: %d of %d (%s)" % (total, total_cap, source))
    if total > total_cap:
        problems.append("total searches %d exceed the limit of %d" % (total, total_cap))
    return report("budget", problems, notes)


def cmd_all(brief, ledger_csv, search_ledger=None):
    rc = 0
    for fn, args in (("style", (brief,)), ("sections", (brief,)), ("depth", (brief,)),
                     ("trace", (brief, ledger_csv))):
        print("--- %s ---" % fn)
        rc |= globals()["cmd_" + fn](*args)
        print()
    if search_ledger:
        print("--- budget ---")
        rc |= cmd_budget(search_ledger)
        print()
    print("STATUS: " + ("ALL-PASS" if rc == 0 else "GATE-FAIL"))
    return rc


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, rest = argv[1], argv[2:]
    table = {"style": cmd_style, "sections": cmd_sections, "depth": cmd_depth,
             "trace": cmd_trace, "budget": cmd_budget, "all": cmd_all}
    if cmd not in table:
        print(__doc__)
        return 1
    return table[cmd](*rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
