#!/usr/bin/env python3
"""
smoke_test.py - self-test for helpers/final_gate.py and helpers/render_html.py.

Locks in the behaviour that matters for the v3 plain-English single-list output:
the sheet opens with a plain-English situation, a jargon buster, a "why this is a
live prospect" note and an at-a-glance table, then each ranked item is written
plain-English-first (What is happening / What it means for them / Your way in) and
still carries the machine-checkable labels (Developability / Trigger / Readiness),
an Email hook and an Evidence block with F/I/A tags.

Sections:
  1. DATE_RE accepts real dates and REJECTS bare month-words / fractions.
  2. check_sheet PASSes a well-formed v3 sheet and FAILs a broken one, including the
     new plain-English section checks and the 11-field per-item set.
  3. chase-list gate.
  4. footprint reconciliation.
  5. recency-refresh.
  6. NO STATED TOTAL retired; absence-is-not-evidence.
  7. coverage-map integrity.
  8. zero-item sheet ships with a watch-list + no-call verdict.
  9. render_html turns a validated sheet into HTML with the key structural pieces.

Run:  python evals/smoke_test.py
Exit 0 if all assertions hold, 1 otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "helpers"))
import final_gate as fg  # noqa: E402
import render_html as rh  # noqa: E402

failures = []


def expect(cond, msg):
    if not cond:
        failures.append(msg)


def check_status(sheet, name, ledger=""):
    for r in fg.check_sheet(sheet, ledger):
        if r["check"] == name:
            return r["status"]
    return None


# --- 1. DATE_RE -----------------------------------------------------------------

DATES_THAT_MUST_MATCH = [
    "appointed CSCO effective 1 May 2026", "results call on 2026-05-20",
    "lease expiry in Q3 2027", "contract signed in 2022 and therefore due",
    "decision due 20 May", "filed on May 21st", "permit dated 01/05/2026",
]
TREND_LINES_THAT_MUST_NOT_MATCH = [
    "they may be expanding their automation footprint", "a march toward consolidation is underway",
    "they are investing in automation", "sustainability is rising up the agenda",
    "spec is 3/4 of the dock doors", "margins are tightening this year-ish",
]
for s in DATES_THAT_MUST_MATCH:
    expect(fg.DATE_RE.search(s) is not None, f"DATE_RE should MATCH a real date: {s!r}")
for s in TREND_LINES_THAT_MUST_NOT_MATCH:
    expect(fg.DATE_RE.search(s) is None, f"DATE_RE should NOT match (trend/fraction): {s!r}")


# --- 2. check_sheet on a good and a broken sheet --------------------------------

GOOD = """# Outreach angles: Acme Logistics BV
Benelux lens | Researched 2026-06-25 | Listed | Focus: automation | Door: Head of Property

Acme is a mid-market omnichannel retailer across the Benelux, based in Antwerp.

## The situation in plain English
Acme borrowed to grow and now spends more cash than it makes. It appointed a new supply chain leader in
May 2026 and has guided its investment upward. The clearest reason to call is that this new leader is
still deciding how the network should look, and Acme owns buildings it has not tapped for cash.

## Jargon buster
- **Sale-and-leaseback**: sell a building you own to an investor and rent it back on a long lease, so you get cash now but keep using it.
- **CSCO**: Chief Supply Chain Officer, the executive who owns how goods move and where they are stored.

## Why this is a live prospect for us
Acme owns distribution space and is reviewing its network under a new leader, so both a capital-release
conversation and a network-design conversation are open right now.

## At a glance
| # | Opportunity | Developability | Trigger | Readiness | Who to call |
| --- | --- | --- | --- | --- | --- |
| 1 | Regional DC as online grows | High | Structural: online growth since 2024 vs single hub | Check first | CSCO |
| 2 | New CSCO in first 100 days | Medium | Event-driven: appointed 1 May 2026 | Send now | New CSCO |

## Angles (ranked)

### 1. Growing online while still single-hub served
What is happening: Acme's online orders keep rising but it still ships everything from one national hub.
What it means for them: the distance and cost to serve each order grow as they expand, which usually means a second regional warehouse.
Your way in: point out the mismatch and offer a short view of where a second hub could sit.
Developability: High. A regional fulfilment requirement is a sizeable, transactable I&L mandate.
Trigger: Structural. Online share rising since 2024 [FACT] set against a single national hub [FACT].
Readiness: Verify first: confirm there is no planned second hub before sending.
Email hook:
  - First line: name their online growth and the single-hub model, specific to them.
  - The one consequence: service distance and cost scale with every new order.
  - Soft ask: a one-page view of regional-DC options peers have taken.
Call opener: where would the next hub sit given your growth corridors?
Evidence: growth and a single hub together imply a cost-to-serve gap [INFERENCE], grounded on two sourced facts dated 2024 and 2025 [FACT].
Stakeholder: the CSCO and the property lead.
Confidence: Medium, the single-hub model needs one confirmation.

### 2. New CSCO inside the first hundred days
What is happening: Acme appointed a new Chief Supply Chain Officer, effective 1 May 2026.
What it means for them: new leaders review the network they inherit, so the design is genuinely open now.
Your way in: a welcome-to-role note offering an outside view while decisions are still being made.
Developability: Medium. A new network owner typically reviews site mix within the year, a real mandate.
Trigger: Event-driven. Appointed Chief Supply Chain Officer effective 1 May 2026 (newsroom, 2026-05-01) [FACT].
Readiness: Send now
Email hook:
  - First line: reference their named new CSCO and the channel mix they inherit.
  - The one consequence: the network was designed for an older channel mix and now needs a rethink.
  - Soft ask: a short call on how peers sequenced an early network review.
Call opener: which parts of the inherited network are you most likely to rethink first?
Evidence: the appointment is live [FACT] and new leaders inherit older networks [INFERENCE].
Stakeholder: the new CSCO, reachable via the known Head of Property.
Confidence: High, the appointment date re-retrieves to a real source.

## Watch-list
- ESG: an EPC regime with a 2030 horizon, not yet biting.

## Source Ledger
| angle | claim | value as found | source | date | access | grade | F/I/A |
| 2 | new CSCO | "effective 1 May 2026" | newsroom url | 2026-05-01 | 2026-06-25 | live | FACT |
"""

BAD = """# Outreach angles: Bad Co
Benelux lens | Focus: none

## The situation in plain English
A company with no real structure.

## Angles (ranked)

### 1. Vague expansion story
Trigger: they may be expanding and a march toward automation is underway
Evidence: looks interesting.
Call opener: let us chat about sustainability.
Stakeholder: someone senior.
"""

good = fg.check_sheet(GOOD, GOOD)
good_fails = [r for r in good if r["status"] == "FAIL"]
expect(not good_fails, f"GOOD sheet should have no FAILs, got: {[r['check'] for r in good_fails]}")

bad = fg.check_sheet(BAD, "")
bad_fails = {r["check"] for r in bad if r["status"] == "FAIL"}
expect("angle1_dated" in bad_fails, "BAD sheet undated item should FAIL angle1_dated")
expect("angle1_fields" in bad_fails, "BAD sheet should FAIL on missing item fields")
expect("angle1_developability" in bad_fails, "BAD sheet should FAIL on missing Developability")
expect("angle1_readiness" in bad_fails, "BAD sheet should FAIL on missing Readiness")
expect("jargon_buster" in bad_fails, "BAD sheet (with an item) should FAIL missing Jargon buster")
expect("at_a_glance" in bad_fails, "BAD sheet (with an item) should FAIL missing At a glance")
expect("why_prospect" in bad_fails, "BAD sheet (with an item) should FAIL missing Why prospect")
expect(bool(bad_fails), "BAD sheet should FAIL overall")


# --- 3. chase-list gate ---------------------------------------------------------

EVIDENCE_UNCLEARED = """## Findings
| A1 | A | parent group filing | pull if possible | registry | url | registry | 2026-05-01 | 2026-06-25 | live | FACT | not yet opened |
## Chase list
- A1 parent-group consolidated filing: pull if possible
"""
EVIDENCE_CLEARED = """## Findings
| A1 | A | parent group filing | "revenue 1.2bn FY25" | registry | url | registry | 2026-05-01 | 2026-06-25 | live | FACT | opened |
## Chase list
- A1 parent-group consolidated filing: resolved (see A1), was flagged pull if possible
- A2 regional permit: gap: portal unreachable within budget
"""
expect(fg.check_evidence(EVIDENCE_UNCLEARED)["status"] == "FAIL",
       "uncleared chase list should FAIL")
expect(fg.check_evidence(EVIDENCE_CLEARED)["status"] == "PASS", "cleared chase list should PASS")
expect(fg.check_evidence("") is None, "no evidence file should yield None")


# --- 4. footprint reconciliation ------------------------------------------------

expect(check_status("the complete network is fully mapped", "footprint_reconciliation") == "FAIL",
       "saturation claim with no token should FAIL")
expect(check_status("the complete network is fully mapped\nRECONCILIATION: RECONCILED",
                    "footprint_reconciliation") == "PASS", "saturation + RECONCILED should PASS")
expect(check_status("complete network\nRECONCILIATION: UNRESOLVED GAP",
                    "footprint_reconciliation") == "FAIL", "saturation + UNRESOLVED GAP should FAIL")
for benign in [
    "The complete network is not yet established from public sources, so we use a floor of at least four sites.",
    "all 5 distribution centres remain unconfirmed",
]:
    expect(check_status(benign, "footprint_reconciliation") == "PASS",
           f"hedged prose must not false-fail: {benign!r}")
expect("footprint_reconciliation" not in {r["check"] for r in good if r["status"] == "FAIL"},
       "GOOD should not FAIL footprint_reconciliation")


# --- 5. recency-refresh ---------------------------------------------------------

_AGEING_BAD = '| 3 | older lease deal | "signed earlier" | url | 2025-09-01 | 2026-06-25 | ageing | FACT |'
_AGEING_OK = _AGEING_BAD + " refresh: confirmed-ageing"
expect(check_status(GOOD, "recency_refresh", GOOD) == "PASS", "GOOD should PASS recency_refresh")
expect(check_status(GOOD + "\n" + _AGEING_BAD + "\n", "recency_refresh") == "FAIL",
       "ageing row with no refresh outcome should FAIL")
expect(check_status(GOOD + "\n" + _AGEING_OK + "\n", "recency_refresh") == "PASS",
       "ageing row with a refresh outcome should PASS")
_LIVE_MENTIONS_AGEING = '| 4 | note on an ageing fleet | "x" | url | 2026-05-01 | 2026-06-25 | live | FACT |'
expect(check_status(GOOD + "\n" + _LIVE_MENTIONS_AGEING + "\n", "recency_refresh") == "PASS",
       "a live row mentioning 'ageing' in its claim must not FAIL")


# --- 6. NO STATED TOTAL retired + absence-is-not-evidence -----------------------

expect(check_status("the complete network\nRECONCILIATION: NO STATED TOTAL",
                    "footprint_reconciliation") == "FAIL", "retired NO STATED TOTAL should FAIL")
for absent in ["We found no distribution centre in the south.", "There is no evidence of a second hub.",
               "A second site was not found in our searches.", "The group appears to have no regional DC."]:
    expect(check_status(absent, "no_unsourced_absence") == "FAIL",
           f"search-emptiness must FAIL: {absent!r}")
expect(check_status("The company states it runs a single central DC serving the region.",
                    "no_unsourced_absence") == "PASS", "positively-sourced centralised claim must PASS")
expect("no_unsourced_absence" not in {r["check"] for r in good if r["status"] == "FAIL"},
       "GOOD should not FAIL no_unsourced_absence")


# --- 7. coverage-map integrity --------------------------------------------------

COVERAGE_BAD = "## European footprint coverage map\n| DE | EVIDENCE-POSITIVE | plant | Werk X | url 2025-01 | de |\n| PL | INCONCLUSIVE | | | | pl |\nRECONCILIATION: RECONCILED\n"
COVERAGE_GAP = "## European footprint coverage map\n| PL | INCONCLUSIVE | | | | pl |\nRECONCILIATION: UNRESOLVED GAP\n"
expect(check_status(COVERAGE_BAD, "coverage_map") == "FAIL", "RECONCILED over INCONCLUSIVE should FAIL")
expect(check_status(COVERAGE_GAP, "coverage_map") == "PASS", "UNRESOLVED GAP + INCONCLUSIVE should PASS")


# --- 8. zero-item sheet ---------------------------------------------------------

ZERO_WL = """# Outreach angles: Test Co
Region | Researched 2026-06-26 | Private

## The situation in plain English
A quiet private company; nothing is live enough to lead with this quarter.

## Angles (ranked)

## Watch-list
- ESG: an EPC regime with a 2030 horizon, not yet biting.

## Source Ledger
| ref | claim | value | source | date | access | grade | F/I/A |
"""
zl_fails = {r["check"] for r in fg.check_sheet(ZERO_WL, "") if r["status"] == "FAIL"}
expect("zero_angle_ok" not in zl_fails, "zero-item sheet with watch-list + no-call verdict must PASS")

ZERO_EMPTY = """# Outreach angles: Test Co
Region | Researched 2026-06-26 | Private

## The situation in plain English
A company.

## Angles (ranked)
"""
expect(check_status(ZERO_EMPTY, "zero_angle_ok") == "FAIL", "truly empty sheet should FAIL zero_angle_ok")


# --- 9. render_html -------------------------------------------------------------

htmldoc = rh.render(GOOD)
expect(htmldoc.startswith("<!doctype html>"), "render should produce an HTML document")
expect("Acme Logistics BV" in htmldoc, "render should carry the company name")
expect('class="glance"' in htmldoc, "render should build the at-a-glance table")
expect("Show the evidence and call script" in htmldoc, "render should put evidence behind a details toggle")
expect('class="jargon"' in htmldoc, "render should build the jargon buster list")
expect("Email hook" in htmldoc, "render should surface the email hook")
expect(htmldoc.count('class="card"') == 2, "render should build one card per ranked item")
expect("—" not in htmldoc and "–" not in htmldoc, "render must not introduce em/en dashes")


# --- report ---------------------------------------------------------------------

if failures:
    print(f"SMOKE TEST FAILED ({len(failures)} assertion(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)

print("SMOKE TEST PASSED: dates, plain-English sections, item fields, chase-list, reconciliation, "
      "recency-refresh, coverage, zero-item, and HTML render.")
sys.exit(0)
