#!/usr/bin/env python3
"""
final_gate.py - deterministic structural gate for the CBRE I&L Outreach Angles sheet.

Checks the finished sheet in MARKDOWN (and, if present, its Source Ledger and the
internal evidence file) for the hard, mechanical rules a human self-check tends to
miss. The markdown is the gate-validated source of truth; the self-contained HTML
delivered to the broker is rendered from this validated markdown by
helpers/render_html.py.

The sheet is a SINGLE ranked list of opportunities, ranked by DEVELOPABILITY and
written PLAIN-ENGLISH-FIRST. As well as section/field shape, the gate now checks
CONTENT-SHAPE at the load-bearing lines, which is where quality actually lives:
  - developability bands are in non-increasing order (High, then Medium, then Low);
  - an Event-driven trigger carries a real date ON its own Trigger line;
  - a Structural trigger rests on >=2 [FACT] and >=1 [INFERENCE] on its Trigger line
    (the anti-trend fence);
  - a 'Send now' item carries at least one [FACT] on its Trigger line;
and it WARNs on an email-hook first line that is a meta-instruction rather than a
sendable sentence. These move the reviewer's most-variable judgements into the
deterministic layer, which is the biggest lever on run-to-run consistency.

It is STRUCTURE ONLY: it does not judge whether a source is real, whether the
developability band is honest, or whether an enumeration is complete. That is the
reviewer's job (Stage 5).

Usage:
    python final_gate.py SHEET.md [--ledger LEDGER.md] [--evidence EVIDENCE.md] [--json]

Output ends in a single machine-read line: "STATUS: PASS" or "STATUS: FAIL".
Exit code 0 on PASS, 1 on FAIL, 2 on bad invocation. WARN never fails the gate.
"""
import argparse
import json
import re
import sys

# Em (U+2014) and en (U+2013) dashes, plus the look-alikes a model slips in.
# The ASCII hyphen-minus "-" (U+002D) is allowed and NOT matched.
DASH_RE = re.compile(r"[‒–—―−]")

# A REAL date token. Strict, so a bare month-word or a spec fraction does NOT count.
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
# The per-item field set. Every "### N." item must carry all of these.
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
BAND_RANK = {"high": 3, "medium": 2, "low": 1}
WORD_BUDGET = 3000  # length cap retired for the deliverable; this is only a sanity WARN.
# Instruction verbs that mean an email-hook first line describes what to write rather
# than being the sendable sentence itself.
HOOK_INSTRUCTION_VERBS = ("note", "reference", "mention", "highlight", "flag",
                          "point", "lead", "open", "cite", "raise", "remind",
                          "stress", "underscore", "call")

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

ABSENCE_RE = re.compile(
    r"\b(?:found no|could not find|couldn't find|did not find|didn't find|we found no|"
    r"no evidence of|unable to find|no trace of|appears to have no|"
    r"not found in (?:my|our) search\w*)\b",
    re.I,
)
COVERAGE_INCONCLUSIVE_RE = re.compile(r"\bINCONCLUSIVE\b", re.I)
# Data-aggregator hosts a load-bearing figure should NOT rest on alone (primary source or a
# corroborating second row is expected). Advisory WARN only; the reviewer owns the real judgement.
AGGREGATOR_HOSTS = (
    "finance.yahoo.com", "investing.com", "marketscreener.com", "simplywall.st",
    "stockanalysis.com", "wallmine.com", "tipranks.com", "barchart.com",
)
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


def field_span(blk, field):
    """Return the text of a field, from its 'Field:' line up to the next known field
    label (so a wrapped value or sub-bullets, e.g. under 'Email hook:', are included).
    Returns '' if the field is absent."""
    span, capturing = [], False
    for ln in blk.splitlines():
        s = ln.strip()
        if not capturing:
            if s.startswith(field):
                capturing = True
                span.append(ln)
            continue
        if any(s.startswith(f) for f in ANGLE_FIELDS):
            break
        span.append(ln)
    return "\n".join(span)


def section_body(text, heading_prefix, flags=re.M):
    """Return the body of the first section whose heading starts with heading_prefix.
    Pass flags=re.M|re.I for case-insensitive heading matching."""
    m = re.search(r"^" + re.escape(heading_prefix) + r".*$", text, flags)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^##\s", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    return text[start:end]


def strip_inference_block(t):
    """Return t with the '## Reading the signals' block removed. That block is the Stage 3.5
    abductive inference block: it is explicitly inferential, quarantined, and inherently full of
    absence/tension language ("no real-estate resolution", a disconfirming "no evidence of ..."
    line), which would otherwise false-trip the content-integrity FAIL checks (no_unsourced_absence,
    saturation). Its own quality is the reviewer's job and its own advisory WARN; only the global
    dash check and that WARN apply to it, not the sourced-angle content checks."""
    m = re.search(r"^##\s+Reading the signals.*$", t, re.M | re.I)
    if not m:
        return t
    nxt = re.search(r"^##\s", t[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(t)
    return t[:m.start()] + t[end:]


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
    """True only for an AFFIRMATIVE closure claim (negated/hedged prose does not count)."""
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
    """Chase-list gate: the evidence file must carry no unresolved pointer."""
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
    # Content-integrity FAIL checks run on the sheet WITHOUT the Stage 3.5 inference block, which is
    # quarantined and inherently full of absence/tension language. The global dash check still uses
    # the full text, and the inference block gets its own advisory WARN below.
    text_ex = strip_inference_block(text)

    # 1. Banned dashes (sheet is authored text; ledger may quote sources, so skip it).
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

    # 3. Header meta line.
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
    blocks = find_angle_blocks(text_ex)
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
                    add(results, "FAIL", check, "'At a glance' section present but has no table row")
                else:
                    add(results, "PASS", check, f"'{heading[3:]}' present")
            else:
                add(results, "FAIL", check, f"missing required section '{heading}'")

        # 5b. Per-item checks.
        bands = []
        for idx, blk in enumerate(blocks, 1):
            missing_fields = [f for f in ANGLE_FIELDS if f not in blk]
            if missing_fields:
                add(results, "FAIL", f"angle{idx}_fields",
                    "missing field(s): " + ", ".join(missing_fields))
            else:
                add(results, "PASS", f"angle{idx}_fields", "all required fields present")

            # Block-level date is now only a WARN fallback; the binding date check is on the
            # Trigger line below.
            if DATE_RE.search(blk):
                add(results, "PASS", f"angle{idx}_dated", "item carries a real date")
            else:
                add(results, "WARN", f"angle{idx}_dated", "no real date found anywhere in the item")

            dev_m = DEVELOPABILITY_RE.search(blk)
            if dev_m:
                add(results, "PASS", f"angle{idx}_developability", "Developability High/Medium/Low")
                bands.append(BAND_RANK[dev_m.group(1).lower()])
            else:
                add(results, "FAIL", f"angle{idx}_developability",
                    "Developability must lead with High, Medium or Low")
                bands.append(None)

            trig_m = TRIGGER_TYPE_RE.search(blk)
            trig_span = field_span(blk, "Trigger:")
            read_span = field_span(blk, "Readiness:")
            if trig_m:
                add(results, "PASS", f"angle{idx}_trigger_type", "Trigger Event-driven/Structural")
                ttype = trig_m.group(1).lower()
                # Event-driven -> a real date must sit on the Trigger line itself.
                if ttype == "event-driven":
                    if DATE_RE.search(trig_span):
                        add(results, "PASS", f"angle{idx}_trigger_dated",
                            "Event-driven trigger carries a date on its own line")
                    else:
                        add(results, "FAIL", f"angle{idx}_trigger_dated",
                            "Event-driven trigger has no real date on the Trigger line "
                            "(a date elsewhere in the item does not count)")
                # Structural -> the two-fact fence, checked on the Trigger line.
                if ttype == "structural":
                    # Count tags tolerantly: the convention allows a date annotation,
                    # e.g. "[FACT, February 2026]", so match "[FACT" at a word boundary.
                    nfact = len(re.findall(r"\[FACT\b", trig_span, re.I))
                    ninf = len(re.findall(r"\[INFERENCE\b", trig_span, re.I))
                    if nfact >= 2 and ninf >= 1:
                        add(results, "PASS", f"angle{idx}_structural_fence",
                            f"Structural fence met ({nfact} [FACT], {ninf} [INFERENCE])")
                    else:
                        add(results, "FAIL", f"angle{idx}_structural_fence",
                            f"Structural trigger must rest on >=2 [FACT] and >=1 [INFERENCE] on the "
                            f"Trigger line (found {nfact} [FACT], {ninf} [INFERENCE]); one fact plus "
                            f"a generalisation is a trend, not a structural hook")
            else:
                add(results, "FAIL", f"angle{idx}_trigger_type",
                    "Trigger must be labelled Event-driven or Structural")

            read_m = READINESS_RE.search(blk)
            if read_m:
                add(results, "PASS", f"angle{idx}_readiness", "Readiness Send now/Verify first")
                # Send now -> the Trigger line must carry at least one [FACT].
                if read_m.group(1).lower() == "send now":
                    if re.search(r"\[FACT\b", trig_span, re.I):
                        add(results, "PASS", f"angle{idx}_sendnow_anchor",
                            "Send-now item has a [FACT] on its Trigger line")
                    else:
                        add(results, "FAIL", f"angle{idx}_sendnow_anchor",
                            "'Send now' requires at least one [FACT] on the Trigger line; an "
                            "inference-only trigger cannot ship as send-now (label it Verify first)")
            else:
                add(results, "FAIL", f"angle{idx}_readiness",
                    "Readiness must be 'Send now' or 'Verify first: <the one fact>'")

            conf = re.search(r"^Confidence:\s*([A-Za-z]+)", blk, re.M)
            if conf and conf.group(1).lower() in CONFIDENCE_VALUES:
                add(results, "PASS", f"angle{idx}_confidence", conf.group(1))
            else:
                add(results, "FAIL", f"angle{idx}_confidence", "Confidence must be High, Medium or Low")

            if re.search(r"\[(?:FACT|INFERENCE|ASSUMPTION)\b", blk, re.I):
                add(results, "PASS", f"angle{idx}_fia", "bracketed F/I/A tag present")
            else:
                add(results, "FAIL", f"angle{idx}_fia",
                    "no [FACT]/[INFERENCE]/[ASSUMPTION] tag in this item (brackets required)")

            # Email-hook first line should be a sendable sentence, not a meta-instruction.
            hook_span = field_span(blk, "Email hook:")
            fl = re.search(r"(?im)^\s*[-*+]?\s*First line:\s*(.+)$", hook_span)
            if fl:
                first_word = re.sub(r"[^a-z]", "", fl.group(1).strip().split(" ")[0].lower())
                if first_word in HOOK_INSTRUCTION_VERBS:
                    add(results, "WARN", f"angle{idx}_hook_pasteable",
                        f"Email hook first line begins with '{first_word}' (an instruction, not a "
                        f"sendable sentence); write the words the broker will paste")
                else:
                    add(results, "PASS", f"angle{idx}_hook_pasteable",
                        "email hook first line reads as a sendable sentence")

        # 5c. Rank order: developability bands must be non-increasing (High >= Medium >= Low).
        seq = [(i + 1, b) for i, b in enumerate(bands) if b is not None]
        inversion = next(((seq[k - 1][0], seq[k][0]) for k in range(1, len(seq))
                          if seq[k][1] > seq[k - 1][1]), None)
        if inversion:
            add(results, "FAIL", "angle_rank_order",
                f"developability out of order: item {inversion[1]} outranks the earlier item "
                f"{inversion[0]}; the list must run High, then Medium, then Low")
        else:
            add(results, "PASS", "angle_rank_order", "developability bands are non-increasing")

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
    combined = text_ex + "\n" + (ledger_text or "")
    if has_saturation_claim(text_ex):
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
    if ABSENCE_RE.search(text_ex):
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

    # 6f. Aggregator-source advisory (WARN only). A load-bearing figure cited only to a data
    # aggregator should be corroborated by a primary source; flags the ledger rows to check.
    ledger_scan = (text.split("## Source Ledger", 1)[1] if "## Source Ledger" in text else "") \
        + "\n" + (ledger_text or "")
    # Match on the URL HOST, not a bare substring, so an aggregator token inside an unrelated
    # path (e.g. https://acme.com/investing.commitments) does not false-fire.
    ledger_hosts = re.findall(r"https?://([a-z0-9.\-]+)", ledger_scan.lower())
    agg_hits = sorted({a for host in ledger_hosts for a in AGGREGATOR_HOSTS
                       if host == a or host.endswith("." + a)})
    if agg_hits:
        add(results, "WARN", "aggregator_sources",
            "ledger cites data-aggregator host(s) (" + ", ".join(agg_hits)
            + "); corroborate any load-bearing figure with a primary source (filing/IR/RNS) or a second row")
    else:
        add(results, "PASS", "aggregator_sources", "no aggregator-only sourcing detected in the ledger")

    # 6g. Inference block advisory (WARN only). The Stage 3.5 abductive block is optional and
    # quarantined; if present, sanity-check its shape (bet count, confirm/kill lines, two-fact
    # grounding). Bet QUALITY is the reviewer's job, so this never FAILs a run.
    inf = section_body(text, "## Reading the signals", re.M | re.I)
    bet_starts = [m.start() for m in re.finditer(r"^###\s+Bet\b", inf, re.M)]
    if bet_starts:
        problems = []
        if len(bet_starts) > 4:
            problems.append(f"{len(bet_starts)} bets exceed the cap of 4")
        for i, s in enumerate(bet_starts):
            e = bet_starts[i + 1] if i + 1 < len(bet_starts) else len(inf)
            span = inf[s:e]
            miss = []
            if "What would confirm it:" not in span:
                miss.append("a tripwire ('What would confirm it:')")
            if "What would kill it:" not in span:
                miss.append("a disconfirming line ('What would kill it:')")
            if len(re.findall(r"\[FACT\b", span)) < 2:
                miss.append("two grounding [FACT]s")
            if not re.search(r"(?im)^\s*move[ -]type:", span):
                miss.append("a Move type")
            if not re.search(r"(?im)^\s*posture:", span):
                miss.append("a Posture read")
            if miss:
                problems.append(f"bet {i + 1} lacks " + " and ".join(miss))
        if problems:
            add(results, "WARN", "inference_block",
                "; ".join(problems) + " (advisory; the reviewer owns bet quality)")
        else:
            add(results, "PASS", "inference_block",
                f"{len(bet_starts)} bet(s), each with a tripwire, a disconfirming line and >=2 [FACT]s")
    else:
        add(results, "PASS", "inference_block", "no inference bets (block absent or empty)")

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
