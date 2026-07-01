#!/usr/bin/env python3
"""
final_gate.py - deterministic structural gate for the CBRE I&L Outreach Angles sheet.

Checks the finished sheet in MARKDOWN (and, if present, its Source Ledger and the
internal evidence file) for the hard, mechanical rules a human self-check tends to
miss. The markdown is the gate-validated source of truth; the self-contained HTML
delivered to the broker is rendered from this validated markdown by
helpers/render_html.py.

The sheet is a SINGLE ranked list of opportunities (ranked by developability),
written PLAIN-ENGLISH-FIRST: it opens with a plain-language situation, a jargon
buster, a "why this is a live prospect" note and an at-a-glance table, then each
ranked item is written in plain words (What is happening / What it means for them /
Your way in) before its labelled evidence. Each item still carries the machine-
checkable axis labels (Developability, Trigger type), a Readiness label (Send now /
Verify first) and an Email hook, so the digestibility is enforced alongside the
rigour.

It is STRUCTURE ONLY: it does not judge content quality, the strength of a trigger,
whether developability is rated honestly, or whether a source is real or an
enumeration truly complete. That is the reviewer's job (Stage 5).

Usage:
    python final_gate.py SHEET.md [--ledger LEDGER.md] [--evidence EVIDENCE.md] [--json]

Output ends in a single machine-read line: "STATUS: PASS" or "STATUS: FAIL".
Exit code 0 on PASS, 1 on FAIL, 2 on bad invocation. WARN never fails the gate.
"""
import argparse
import json
import re
import sys

# Em (U+2014) and en (U+2013) dashes, plus the look-alikes a model slips in:
# figure dash (U+2012), horizontal bar (U+2015), minus sign (U+2212).
# The ASCII hyphen-minus "-" (U+002D) is allowed and NOT matched.
DASH_RE = re.compile(r"[‒–—―−]")

# A REAL date token. Deliberately strict so a bare month-word ("may", "march")
# or a spec fraction ("3/4") does NOT count as a date:
#   - a 4-digit year (also covers ISO YYYY-MM-DD and "May 2026");
#   - a numeric date that INCLUDES a year, e.g. 01/05/2026 or 1-5-26 (so "3/4" fails);
#   - a day adjacent to a month name, e.g. "1 May", "21 March";
#   - a month name adjacent to a day, e.g. "May 1", "May 21st".
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b\d{1,2}\s+" + _MONTH + r"\b"
    r"|\b" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?\b",
    re.I,
)

# Always-required sections (present even on a zero-item "do not call" sheet).
REQUIRED_SECTIONS = ["## The situation in plain English", "## Angles"]
# Sections required only once there are ranked items (the plain-English scaffolding).
CONDITIONAL_SECTIONS = [
    ("## Jargon buster", "jargon_buster"),
    ("## Why this is a live prospect", "why_prospect"),
    ("## At a glance", "at_a_glance"),
]
# The per-item field set. Every "### N." item must carry all of these. The first three
# are the plain-English layer (digestibility); Developability/Trigger are the ranking
# axes; Readiness is the send-now/verify-first split; Email hook is the cold-email
# deliverable; Evidence carries the sourced facts and F/I/A tags.
ANGLE_FIELDS = [
    "What is happening:",
    "What it means for them:",
    "Your way in:",
    "Developability:",
    "Trigger:",
    "Readiness:",
    "Email hook:",
    "Call opener:",
    "Evidence:",
    "Stakeholder:",
    "Confidence:",
]
FIA_TAGS = ["[FACT]", "[INFERENCE]", "[ASSUMPTION]"]
CONFIDENCE_VALUES = {"high", "medium", "low"}
WORD_BUDGET = 3000  # length cap retired for the deliverable; this is only a sanity WARN.

# Per-item label validators. Keyed to the start of their own line in an item block.
DEVELOPABILITY_RE = re.compile(r"^Developability:\s*(High|Medium|Low)\b", re.I | re.M)
TRIGGER_TYPE_RE = re.compile(r"^Trigger:\s*(Event-driven|Structural)\b", re.I | re.M)
READINESS_RE = re.compile(r"^Readiness:\s*(Send now|Verify first)\b", re.I | re.M)

# Closure/saturation language that asserts OUR footprint mapping is complete. Kept to
# unambiguous claims: bare "whole network" / "entire network" are excluded because they
# are ordinary business phrasing (e.g. "the COO reviews the whole network") and false-fired.
SATURATION_RE = re.compile(
    r"\b(?:saturat\w*|complete network|full footprint|fully mapped|"
    r"complete (?:european )?footprint|"
    r"all\s+\d+\s+(?:sites|distribution centres|warehouses|logistics centres))\b",
    re.I,
)
_NEG_RE = re.compile(
    r"\b(?:no|not|without|never|lacks?|lacking|incomplete|cannot|can't|isn't|aren't|"
    r"yet to|too early|unconfirmed|unverified|provisional|tbd|n't)\b"
)
_SENTENCE_BOUNDARY = ".;\n"
RECON_RECONCILED_RE = re.compile(r"RECONCILIATION:\s*RECONCILED\b", re.I)
RECON_GAP_RE = re.compile(r"RECONCILIATION:\s*UNRESOLVED GAP\b", re.I)
RECON_NOSTATED_RE = re.compile(r"RECONCILIATION:\s*NO STATED TOTAL", re.I)

ABSENCE_RE = re.compile(
    r"\b(?:found no|could not find|couldn't find|did not find|didn't find|we found no|"
    r"no evidence of|unable to find|no trace of|appears to have no|"
    r"not found in (?:my|our) search\w*)\b",
    re.I,
)
COVERAGE_INCONCLUSIVE_RE = re.compile(r"\bINCONCLUSIVE\b", re.I)
UNRESOLVED_CHASE_RE = re.compile(r"pull if possible|pointer not opened", re.I)
_CHASE_DONE_RE = re.compile(r"\b(?:resolved|gap:)", re.I)


def add(results, status, check, detail):
    results.append({"status": status, "check": check, "detail": detail})


def find_angle_blocks(text):
    """Return the text of each '### N.' angle block, up to the next ## or ### heading."""
    heads = [m.start() for m in re.finditer(r"^###\s+\d+\.", text, re.M)]
    stops = [m.start() for m in re.finditer(r"^#{2,3}\s", text, re.M)]
    blocks = []
    for start in heads:
        later = [s for s in stops if s > start]
        end = min(later) if later else len(text)
        blocks.append(text[start:end])
    return blocks


def section_body(text, heading_prefix):
    """Return the body of the first section whose heading starts with heading_prefix,
    up to the next '## ' heading (or end)."""
    m = re.search(r"^" + re.escape(heading_prefix) + r".*$", text, re.M)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^##\s", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    return text[start:end]


def has_table_row(text):
    """A markdown table row: a non-heading line with at least two pipe characters."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if s.count("|") >= 2 and set(s) - set("|-: "):
            return True
    return False


def has_saturation_claim(text):
    """True only for an AFFIRMATIVE closure claim. A closure phrase whose enclosing
    sentence carries any negation/uncertainty token does not count."""
    for m in SATURATION_RE.finditer(text):
        start = max((text.rfind(ch, 0, m.start()) for ch in _SENTENCE_BOUNDARY), default=-1) + 1
        ends = [text.find(ch, m.end()) for ch in _SENTENCE_BOUNDARY]
        ends = [e for e in ends if e != -1]
        end = min(ends) if ends else len(text)
        if _NEG_RE.search(text[start:end].lower()):
            continue
        return True
    return False


def check_evidence(evidence_text):
    """Chase-list gate: the internal evidence file handed to the gate must carry no
    unresolved pointer. Returns a single result dict, or None if no file was given."""
    if not evidence_text:
        return None
    bad = [i + 1 for i, ln in enumerate(evidence_text.splitlines())
           if UNRESOLVED_CHASE_RE.search(ln) and not _CHASE_DONE_RE.search(ln)]
    if bad:
        return {"status": "FAIL", "check": "chase_list_cleared",
                "detail": "unresolved chase pointer ('pull if possible' / 'pointer not opened') "
                          "still in evidence file on line(s): " + ", ".join(map(str, bad))
                          + "; resolve or log as a gap before authoring"}
    return {"status": "PASS", "check": "chase_list_cleared",
            "detail": "no unresolved chase pointer in evidence file"}


def check_sheet(text, ledger_text):
    results = []

    # 1. Banned dashes (sheet is authored text; ledger may quote sources verbatim, so skip it).
    dash_lines = [i + 1 for i, ln in enumerate(text.splitlines()) if DASH_RE.search(ln)]
    if dash_lines:
        add(results, "FAIL", "no_em_en_dashes",
            "em/en dash found on line(s): " + ", ".join(map(str, dash_lines)))
    else:
        add(results, "PASS", "no_em_en_dashes", "none found")

    # 2. Title line.
    if re.search(r"^#\s+Outreach angles:", text, re.M):
        add(results, "PASS", "title", "present")
    else:
        add(results, "FAIL", "title", "missing '# Outreach angles: <Company>' title")

    # 3. Header meta line: the line carrying 'Researched' must also carry a real date.
    header_line = next((ln for ln in text.splitlines() if "Researched" in ln), "")
    if header_line and DATE_RE.search(header_line):
        add(results, "PASS", "header_run_date", "'Researched <date>' present")
    else:
        add(results, "WARN", "header_run_date", "header should carry 'Researched <date>'")
    if re.search(r"\b(Listed|Private)\b", text):
        add(results, "PASS", "header_listed_private", "listed/private flag present")
    else:
        add(results, "WARN", "header_listed_private", "header should state Listed or Private")

    # 4. Always-required sections.
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    if missing:
        add(results, "FAIL", "required_sections", "missing: " + ", ".join(missing))
    else:
        add(results, "PASS", "required_sections",
            "'The situation in plain English' and 'Angles' present")

    # 5. Item-level checks (only when ranked items exist).
    blocks = find_angle_blocks(text)
    no_call_verdict = bool(re.search(
        r"do not call|no live reason to call|no shortlist angle is live|"
        r"no opportunity is developable", text, re.I))
    has_watchlist = bool(re.search(r"##\s*Watch-?list", text, re.I))

    if not blocks:
        if no_call_verdict or has_watchlist:
            add(results, "PASS", "zero_angle_ok",
                "no ranked items, but the sheet still surfaces a watch-list or a no-call verdict")
        else:
            add(results, "FAIL", "zero_angle_ok",
                "no ranked items and nothing else to ship (no watch-list, no no-call verdict)")
        if has_watchlist:
            add(results, "PASS", "watchlist", "watch-list present")
        else:
            add(results, "WARN", "watchlist", "a zero-item sheet should carry a watch-list")
    else:
        add(results, "PASS", "angle_count", f"{len(blocks)} ranked item(s) found")

        # 5a. Plain-English scaffolding sections are required once items exist.
        for heading, check in CONDITIONAL_SECTIONS:
            if heading in text:
                if check == "at_a_glance" and not has_table_row(section_body(text, heading)):
                    add(results, "FAIL", check,
                        "'At a glance' section present but has no table row")
                else:
                    add(results, "PASS", check, f"'{heading[3:]}' present")
            else:
                add(results, "FAIL", check, f"missing required section '{heading}'")

        for idx, blk in enumerate(blocks, 1):
            missing_fields = [f for f in ANGLE_FIELDS if f not in blk]
            if missing_fields:
                add(results, "FAIL", f"angle{idx}_fields",
                    "missing field(s): " + ", ".join(missing_fields))
            else:
                add(results, "PASS", f"angle{idx}_fields", "all required fields present")

            if DATE_RE.search(blk):
                add(results, "PASS", f"angle{idx}_dated", "item carries a real date")
            else:
                add(results, "FAIL", f"angle{idx}_dated",
                    "item must rest on at least one dated source (a real date, not a stray month word)")

            if DEVELOPABILITY_RE.search(blk):
                add(results, "PASS", f"angle{idx}_developability", "Developability High/Medium/Low")
            else:
                add(results, "FAIL", f"angle{idx}_developability",
                    "Developability must lead with High, Medium or Low")

            if TRIGGER_TYPE_RE.search(blk):
                add(results, "PASS", f"angle{idx}_trigger_type", "Trigger Event-driven/Structural")
            else:
                add(results, "FAIL", f"angle{idx}_trigger_type",
                    "Trigger must be labelled Event-driven or Structural")

            if READINESS_RE.search(blk):
                add(results, "PASS", f"angle{idx}_readiness", "Readiness Send now/Verify first")
            else:
                add(results, "FAIL", f"angle{idx}_readiness",
                    "Readiness must be 'Send now' or 'Verify first: <the one fact>'")

            conf = re.search(r"^Confidence:\s*([A-Za-z]+)", blk, re.M)
            if conf and conf.group(1).lower() in CONFIDENCE_VALUES:
                add(results, "PASS", f"angle{idx}_confidence", conf.group(1))
            else:
                add(results, "FAIL", f"angle{idx}_confidence",
                    "Confidence must be High, Medium or Low")

            if any(tag in blk for tag in FIA_TAGS):
                add(results, "PASS", f"angle{idx}_fia", "bracketed F/I/A tag present")
            else:
                add(results, "FAIL", f"angle{idx}_fia",
                    "no [FACT]/[INFERENCE]/[ASSUMPTION] tag in this item (brackets required)")

        # 6. A backing ledger is required once items exist.
        ledger_in_sheet = "## Source Ledger" in text and (
            has_table_row(text.split("## Source Ledger", 1)[1])
            or "ledger.md" in text.split("## Source Ledger", 1)[1].lower())
        ledger_in_file = bool(ledger_text) and has_table_row(ledger_text)
        if ledger_in_sheet or ledger_in_file:
            add(results, "PASS", "source_ledger", "ledger table or pointer present")
        else:
            add(results, "FAIL", "source_ledger",
                "no Source Ledger table or ledger.md pointer found (in sheet section or --ledger file)")

        # 6b. Recency-refresh: an 'ageing'-graded ledger row must record a refresh outcome.
        ledger_blob = (text.split("## Source Ledger", 1)[1] if "## Source Ledger" in text else "") \
            + "\n" + (ledger_text or "")
        refresh_ok_re = re.compile(r"refresh:\s*(?:confirmed-ageing|none)", re.I)

        def _grade_is_ageing(ln):
            if ln.count("|") < 2:
                return False
            return any(c.strip().lower() in ("ageing", "aging") for c in ln.split("|"))

        ageing_rows = [ln for ln in ledger_blob.splitlines() if _grade_is_ageing(ln)]
        unrefreshed = [ln for ln in ageing_rows if not refresh_ok_re.search(ln)]
        if not ageing_rows:
            add(results, "PASS", "recency_refresh", "no ageing-graded ledger rows")
        elif unrefreshed:
            add(results, "FAIL", "recency_refresh",
                f"{len(unrefreshed)} ageing ledger row(s) lack a refresh outcome "
                "('refresh: confirmed-ageing' or 'refresh: none')")
        else:
            add(results, "PASS", "recency_refresh",
                f"{len(ageing_rows)} ageing row(s) carry a refresh outcome")

    # 6c. Footprint completeness reconciliation. Top-level so it runs on every sheet.
    combined = text + "\n" + (ledger_text or "")
    if RECON_NOSTATED_RE.search(combined):
        add(results, "FAIL", "footprint_reconciliation",
            "'RECONCILIATION: NO STATED TOTAL' off-ramp is retired; with no published total, "
            "reconcile against the all-Europe coverage map to RECONCILED or UNRESOLVED GAP")
    elif has_saturation_claim(text):
        if RECON_GAP_RE.search(combined):
            add(results, "FAIL", "footprint_reconciliation",
                "saturation/complete-network claim present while reconciliation is 'UNRESOLVED GAP'")
        elif RECON_RECONCILED_RE.search(combined):
            add(results, "PASS", "footprint_reconciliation",
                "saturation claim backed by 'RECONCILIATION: RECONCILED'")
        else:
            add(results, "FAIL", "footprint_reconciliation",
                "saturation/complete-network language present without a 'RECONCILIATION: RECONCILED' token")
    elif RECON_GAP_RE.search(combined):
        add(results, "PASS", "footprint_reconciliation",
            "unresolved footprint gap recorded and no saturation claim made")
    else:
        add(results, "PASS", "footprint_reconciliation", "no saturation claim to reconcile")

    # 6d. Absence is a gap, never evidence.
    if ABSENCE_RE.search(text):
        add(results, "FAIL", "no_unsourced_absence",
            "sheet contains search-emptiness language ('found no' / 'could not find' / "
            "'no evidence of' / ...); absence is a gap, not evidence, and a non-existence "
            "claim must rest on a positive source")
    else:
        add(results, "PASS", "no_unsourced_absence", "no search-emptiness language on the sheet")

    # 6e. Coverage-map integrity: a RECONCILED token may not co-exist with an INCONCLUSIVE row.
    inconclusive_row = any(
        ln.count("|") >= 2 and COVERAGE_INCONCLUSIVE_RE.search(ln) for ln in combined.splitlines())
    if RECON_RECONCILED_RE.search(combined) and inconclusive_row:
        add(results, "FAIL", "coverage_map",
            "RECONCILIATION: RECONCILED present while a coverage row reads INCONCLUSIVE; "
            "resolve the country or downgrade to UNRESOLVED GAP")
    else:
        add(results, "PASS", "coverage_map", "no RECONCILED-over-INCONCLUSIVE contradiction")

    # 7. Length heuristic (WARN only; the page cap is retired for the deliverable).
    words = len(re.findall(r"\S+", text))
    if words > WORD_BUDGET:
        add(results, "WARN", "length", f"{words} words, unusually long (>{WORD_BUDGET})")
    else:
        add(results, "PASS", "length", f"{words} words")

    return results


def main():
    ap = argparse.ArgumentParser(description="Deterministic gate for the Outreach Angles sheet.")
    ap.add_argument("sheet", help="path to the finished sheet .md")
    ap.add_argument("--ledger", help="path to the Source Ledger .md (optional)")
    ap.add_argument("--evidence", help="path to the internal evidence file .md (optional); when given, "
                                       "the chase list must be cleared (no surviving 'pull if possible' "
                                       "/ 'pointer not opened')")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args()

    try:
        with open(args.sheet, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"cannot read sheet: {e}", file=sys.stderr)
        print("STATUS: FAIL")
        return 2

    ledger_text = ""
    if args.ledger:
        try:
            with open(args.ledger, encoding="utf-8") as f:
                ledger_text = f.read()
        except OSError as e:
            print(f"warning: cannot read ledger: {e}", file=sys.stderr)

    evidence_text = ""
    if args.evidence:
        try:
            with open(args.evidence, encoding="utf-8") as f:
                evidence_text = f.read()
        except OSError as e:
            print(f"warning: cannot read evidence file: {e}", file=sys.stderr)

    results = check_sheet(text, ledger_text)
    chase = check_evidence(evidence_text)
    if chase is not None:
        results.append(chase)
    failed = [r for r in results if r["status"] == "FAIL"]
    warned = [r for r in results if r["status"] == "WARN"]
    status = "FAIL" if failed else "PASS"

    if args.json:
        print(json.dumps({"status": status, "results": results}, indent=2))
    else:
        for r in results:
            print(f"  [{r['status']:4}] {r['check']}: {r['detail']}")
        print(f"\n{len(failed)} fail, {len(warned)} warn, "
              f"{len(results) - len(failed) - len(warned)} pass")

    print(f"STATUS: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
