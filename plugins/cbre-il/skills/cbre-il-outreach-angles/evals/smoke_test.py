#!/usr/bin/env python3
"""
smoke_test.py - self-test for helpers/final_gate.py and helpers/render_html.py.

Covers the v3 plain-English single-list output plus the Wave-1 content-shape gate:
  1. DATE_RE accepts real dates and REJECTS bare month-words / fractions.
  2. check_sheet PASSes a well-formed v3 sheet and FAILs a broken one.
  3. chase-list gate.
  4. footprint reconciliation.
  5. recency-refresh.
  6. absence-is-not-evidence (the retired NO STATED TOTAL machinery is gone).
  7. coverage-map integrity.
  8. zero-item sheet ships with a watch-list + no-call verdict.
  9. render_html turns a validated sheet into HTML with the key structural pieces.
 10. WAVE 1 content-shape: developability rank order (non-increasing), Event-driven
     trigger dated on its own line, the Structural two-fact fence, Send-now needs a
     [FACT] on the Trigger line, and the pasteable-hook WARN.

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

for s in ["appointed CSCO effective 1 May 2026", "results call on 2026-05-20",
          "lease expiry in Q3 2027", "contract signed in 2022 and therefore due",
          "decision due 20 May", "filed on May 21st", "permit dated 01/05/2026"]:
    expect(fg.DATE_RE.search(s) is not None, f"DATE_RE should MATCH: {s!r}")
for s in ["they may be expanding their automation footprint", "a march toward consolidation",
          "they are investing in automation", "sustainability is rising up the agenda",
          "spec is 3/4 of the dock doors", "margins are tightening this year-ish"]:
    expect(fg.DATE_RE.search(s) is None, f"DATE_RE should NOT match: {s!r}")


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
Developability: High. Scale is a multi-site regional fulfilment mandate; a named CSCO and a live network review raise near-term likelihood.
Trigger: Structural. Online share rising since 2024 [FACT] set against a single national hub [FACT], so service distance is widening [INFERENCE].
Readiness: Verify first: confirm there is no planned second hub before sending.
Email hook:
  - First line: You have grown online strongly since 2024 while still shipping from a single national hub.
  - The one consequence: service distance and cost climb with every new order that hub has to reach.
  - Soft ask: Worth a short call to check whether a second hub is already on your roadmap?
Call opener: where would the next hub sit given your growth corridors?
Evidence: growth and a single hub together imply a cost-to-serve gap [INFERENCE], grounded on two sourced facts dated 2024 and 2025 [FACT].
Stakeholder: the CSCO and the property lead.
Confidence: Medium, the single-hub model needs one confirmation.

### 2. New CSCO inside the first hundred days
What is happening: Acme appointed a new Chief Supply Chain Officer, effective 1 May 2026.
What it means for them: new leaders review the network they inherit, so the design is genuinely open now.
Your way in: a welcome-to-role note offering an outside view while decisions are still being made.
Developability: Medium. Scale is a single network-review mandate; a named owner in his decision window raises near-term likelihood.
Trigger: Event-driven. Appointed Chief Supply Chain Officer effective 1 May 2026 (newsroom, 2026-05-01) [FACT].
Readiness: Send now
Email hook:
  - First line: Congratulations on taking the CSCO seat from 1 May; the network you have inherited was built for an older channel mix.
  - The one consequence: that mismatch is cheapest to reset in the first hundred days.
  - Soft ask: Happy to share how peers sequenced an early network review, if useful.
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

bad_fails = {r["check"] for r in fg.check_sheet(BAD, "") if r["status"] == "FAIL"}
expect("angle1_fields" in bad_fails, "BAD should FAIL on missing item fields")
expect("angle1_developability" in bad_fails, "BAD should FAIL on missing Developability")
expect("angle1_readiness" in bad_fails, "BAD should FAIL on missing Readiness")
expect("jargon_buster" in bad_fails, "BAD (with an item) should FAIL missing Jargon buster")
expect("at_a_glance" in bad_fails, "BAD (with an item) should FAIL missing At a glance")
expect(bool(bad_fails), "BAD should FAIL overall")


# --- 3. chase-list gate ---------------------------------------------------------

EV_UNCLEARED = "## Chase list\n- A1 filing: pull if possible\n"
EV_CLEARED = "## Chase list\n- A1 filing: resolved (see A1), was flagged pull if possible\n- A2: gap: portal down\n"
expect(fg.check_evidence(EV_UNCLEARED)["status"] == "FAIL", "uncleared chase list should FAIL")
expect(fg.check_evidence(EV_CLEARED)["status"] == "PASS", "cleared chase list should PASS")
expect(fg.check_evidence("") is None, "no evidence file should yield None")


# --- 4. footprint reconciliation ------------------------------------------------

expect(check_status("the complete network is fully mapped", "footprint_reconciliation") == "FAIL",
       "saturation claim with no token should FAIL")
expect(check_status("the complete network is fully mapped\nRECONCILIATION: RECONCILED",
                    "footprint_reconciliation") == "PASS", "saturation + RECONCILED should PASS")
expect(check_status("complete network\nRECONCILIATION: UNRESOLVED GAP",
                    "footprint_reconciliation") == "FAIL", "saturation + UNRESOLVED GAP should FAIL")
for benign in ["The complete network is not yet established, so we use a floor of at least four sites.",
               "all 5 distribution centres remain unconfirmed"]:
    expect(check_status(benign, "footprint_reconciliation") == "PASS", f"hedged prose must PASS: {benign!r}")
expect("footprint_reconciliation" not in {r["check"] for r in good if r["status"] == "FAIL"},
       "GOOD should not FAIL footprint_reconciliation")


# --- 5. recency-refresh ---------------------------------------------------------

_AGEING_BAD = '| 3 | older lease deal | "signed earlier" | url | 2025-09-01 | 2026-06-25 | ageing | FACT |'
expect(check_status(GOOD, "recency_refresh", GOOD) == "PASS", "GOOD should PASS recency_refresh")
expect(check_status(GOOD + "\n" + _AGEING_BAD + "\n", "recency_refresh") == "FAIL",
       "ageing row with no refresh outcome should FAIL")
expect(check_status(GOOD + "\n" + _AGEING_BAD + " refresh: confirmed-ageing\n", "recency_refresh") == "PASS",
       "ageing row with a refresh outcome should PASS")


# --- 6. absence-is-not-evidence (NO STATED TOTAL machinery removed) -------------

for absent in ["We found no distribution centre in the south.", "There is no evidence of a second hub.",
               "A second site was not found in our searches.", "The group appears to have no regional DC."]:
    expect(check_status(absent, "no_unsourced_absence") == "FAIL", f"search-emptiness must FAIL: {absent!r}")
expect(check_status("The company states it runs a single central DC serving the region.",
                    "no_unsourced_absence") == "PASS", "positively-sourced centralised claim must PASS")
# The retired token no longer has any dedicated handling; it must not crash and must not be a check.
expect(check_status("RECONCILIATION: NO STATED TOTAL", "footprint_reconciliation") is not None,
       "footprint_reconciliation still runs; NO STATED TOTAL is just ignored text now")


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
expect("zero_angle_ok" not in {r["check"] for r in fg.check_sheet(ZERO_WL, "") if r["status"] == "FAIL"},
       "zero-item sheet with watch-list + no-call verdict must PASS")


# --- 9. render_html -------------------------------------------------------------

htmldoc = rh.render(GOOD)
expect(htmldoc.startswith("<!doctype html>"), "render should produce an HTML document")
expect("Acme Logistics BV" in htmldoc, "render should carry the company name")
expect('class="glance"' in htmldoc, "render should build the at-a-glance table")
expect("Show the evidence and call script" in htmldoc, "render should put evidence behind a details toggle")
expect('class="jargon"' in htmldoc, "render should build the jargon buster list")
expect(htmldoc.count('class="card"') == 2, "render should build one card per ranked item")
expect(htmldoc.rindex('class="jargon-sec"') > htmldoc.rindex('class="card"'),
       "jargon buster must render after the last opportunity card")
expect("—" not in htmldoc and "–" not in htmldoc, "render must not introduce em/en dashes")


# --- 10. WAVE 1 content-shape checks --------------------------------------------

# GOOD passes each new content-shape check.
expect(check_status(GOOD, "angle_rank_order") == "PASS", "GOOD is in non-increasing band order")
expect(check_status(GOOD, "angle1_structural_fence") == "PASS", "GOOD item1 meets the Structural fence")
expect(check_status(GOOD, "angle2_trigger_dated") == "PASS", "GOOD item2 Event-driven trigger is dated")
expect(check_status(GOOD, "angle2_sendnow_anchor") == "PASS", "GOOD item2 Send-now has a [FACT] trigger")
expect(check_status(GOOD, "angle1_hook_pasteable") == "PASS", "GOOD item1 hook is a sendable sentence")

# Rank inversion: item1 Medium above item2 High must FAIL angle_rank_order.
INVERTED = GOOD.replace("Developability: High. Scale is a multi-site regional",
                        "Developability: Medium. Scale is a multi-site regional") \
               .replace("Developability: Medium. Scale is a single network-review",
                        "Developability: High. Scale is a single network-review")
expect(check_status(INVERTED, "angle_rank_order") == "FAIL",
       "a Medium item above a High item must FAIL angle_rank_order")

# Structural fence: one [FACT] on the Trigger line must FAIL.
ONEFACT = GOOD.replace(
    "Trigger: Structural. Online share rising since 2024 [FACT] set against a single national hub [FACT], so service distance is widening [INFERENCE].",
    "Trigger: Structural. Online share rising since 2024 [FACT], and firms like this usually add a hub [INFERENCE].")
expect(check_status(ONEFACT, "angle1_structural_fence") == "FAIL",
       "a Structural trigger with one [FACT] must FAIL the fence")

# Dated tags like [FACT, 2024] must count toward the fence (the convention allows an
# in-bracket date annotation), so a fence of two dated facts + one inference PASSes.
DATED_FENCE = GOOD.replace(
    "Trigger: Structural. Online share rising since 2024 [FACT] set against a single national hub [FACT], so service distance is widening [INFERENCE].",
    "Trigger: Structural. Online share rising since 2024 [FACT, 2024] set against a single national hub [FACT, 2025], so service distance is widening [INFERENCE].")
expect(check_status(DATED_FENCE, "angle1_structural_fence") == "PASS",
       "dated [FACT, ...] tags must count toward the Structural fence")

# Event-driven trigger with no date ON the Trigger line must FAIL, even if a date sits elsewhere.
UNDATED = GOOD.replace(
    "Trigger: Event-driven. Appointed Chief Supply Chain Officer effective 1 May 2026 (newsroom, 2026-05-01) [FACT].",
    "Trigger: Event-driven. Appointed a new Chief Supply Chain Officer recently (newsroom) [FACT].")
expect(check_status(UNDATED, "angle2_trigger_dated") == "FAIL",
       "an Event-driven trigger with no date on its own line must FAIL")

# Send-now on an inference-only trigger must FAIL.
SENDNOW_INF = GOOD.replace("(newsroom, 2026-05-01) [FACT].", "(newsroom, 2026-05-01) [INFERENCE].")
expect(check_status(SENDNOW_INF, "angle2_sendnow_anchor") == "FAIL",
       "a Send-now item whose Trigger line has no [FACT] must FAIL")

# Pasteable-hook WARN: a first line beginning with an instruction verb WARNs (never FAILs).
HOOKWARN = GOOD.replace(
    "  - First line: You have grown online strongly since 2024 while still shipping from a single national hub.",
    "  - First line: reference their online growth and single-hub model.")
expect(check_status(HOOKWARN, "angle1_hook_pasteable") == "WARN",
       "an instruction-verb first line must WARN")
expect("angle1_hook_pasteable" not in {r["check"] for r in fg.check_sheet(HOOKWARN, "") if r["status"] == "FAIL"},
       "the pasteable-hook check must never FAIL a run")

# Broadened coverage: an extra instruction verb ('point') and a non-dash bullet ('*') still WARN.
HOOKWARN2 = GOOD.replace(
    "  - First line: You have grown online strongly since 2024 while still shipping from a single national hub.",
    "  * First line: point out their online growth and single-hub model.")
expect(check_status(HOOKWARN2, "angle1_hook_pasteable") == "WARN",
       "an asterisk-bulleted first line beginning 'point' must WARN (verb + bullet coverage)")


# --- Wave 2: aggregator-source advisory WARN (never a FAIL) ---------------------

AGG_LEDGER = ("## Source Ledger\n"
              "| 1 | net debt | \"1.9bn\" | https://finance.yahoo.com/quote/x | 2026-05-01 | 2026-06-25 | live | FACT |\n")
expect(check_status(AGG_LEDGER, "aggregator_sources") == "WARN",
       "a ledger row citing an aggregator host (finance.yahoo.com) must WARN aggregator_sources")
expect("aggregator_sources" not in {r["check"] for r in fg.check_sheet(AGG_LEDGER, "") if r["status"] == "FAIL"},
       "the aggregator advisory must never FAIL a run")
expect(check_status(GOOD, "aggregator_sources", GOOD) == "PASS",
       "GOOD (newsroom/primary sources only) must PASS aggregator_sources")
# Host-anchored match: an aggregator token inside an unrelated URL PATH must NOT WARN.
PRIMARY_PATH = ("## Source Ledger\n"
                "| 1 | net debt | \"1.9bn\" | https://ir.acme.com/investing.commitments-2026 | 2026-05-01 | 2026-06-25 | live | FACT |\n")
expect(check_status(PRIMARY_PATH, "aggregator_sources") == "PASS",
       "an aggregator token in a URL path (host is ir.acme.com) must NOT WARN aggregator_sources")


# --- Stage 3.5 inference block (quarantined; advisory-only) ---------------------

INFER = """## Reading the signals (inferred, not confirmed)
Internal use, not client-facing.

### Bet 1: Acme is weighing a second regional hub
The bet: they add a regional distribution centre to cut service distance. [INFERENCE]
Shape: a mid-size DC, likely in the south.
Why I think this: online growth since 2024 [FACT, A2] set against a single national hub [FACT, C1]; together they imply a widening service gap.
What would confirm it: a planning or permit filing for a new DC on the regional portal.
What would kill it: a stated decision to expand the existing hub instead, or no evidence of any site search within 12 months.
Confidence and horizon: Low, 12 to 24 months.

"""
GOOD_INF = GOOD.replace("## Source Ledger", INFER + "## Source Ledger")
gi = fg.check_sheet(GOOD_INF, "")
gi_names = {r["check"] for r in gi}
gi_fails = {r["check"] for r in gi if r["status"] == "FAIL"}
expect(not gi_fails, f"GOOD + a well-formed inference block should have no FAILs, got: {gi_fails}")
expect("angle3_fields" not in gi_names,
       "a '### Bet' must NOT be counted as a ranked angle (no angle3 checks)")
expect(check_status(GOOD_INF, "inference_block") == "PASS",
       "a well-formed single bet (>=2 [FACT], confirm + kill) must PASS inference_block")
expect(check_status(GOOD_INF, "no_unsourced_absence") == "PASS",
       "a bet's 'no evidence of ...' disconfirming line must NOT trip no_unsourced_absence (block is excised)")

# Missing disconfirming line -> WARN (never FAIL).
INFER_NO_KILL = INFER.replace("What would kill it: a stated decision to expand the existing hub instead, or no evidence of any site search within 12 months.\n", "")
expect(check_status(GOOD.replace("## Source Ledger", INFER_NO_KILL + "## Source Ledger"), "inference_block") == "WARN",
       "a bet missing 'What would kill it:' must WARN inference_block")
expect("inference_block" not in {r["check"] for r in fg.check_sheet(GOOD.replace("## Source Ledger", INFER_NO_KILL + "## Source Ledger"), "") if r["status"] == "FAIL"},
       "the inference-block check must never FAIL a run")

# More than four bets -> WARN.
BET = ("### Bet {n}: move {n} [INFERENCE]\n"
       "Why I think this: fact one [FACT, A2] and fact two [FACT, C1].\n"
       "What would confirm it: a permit filing.\n"
       "What would kill it: a stated decision otherwise.\n")
INFER_5 = "## Reading the signals (inferred, not confirmed)\nInternal use.\n" + "".join(BET.format(n=i) for i in range(1, 6))
expect(check_status(INFER_5, "inference_block") == "WARN", "more than four bets must WARN inference_block")

# No block at all -> PASS (the block is optional).
expect(check_status(GOOD, "inference_block", GOOD) == "PASS", "a sheet with no inference block must PASS inference_block")

# Renderer: the block renders as an internal, quarantined section with bet cards.
inf_html = rh.render(GOOD_INF)
expect('class="internal-banner"' in inf_html and "Not client-facing" in inf_html,
       "render must flag the inference block as internal / not client-facing")
expect('class="bet-card"' in inf_html, "render must build a bet card per bet")

# Case-insensitive heading: a title-cased "## Reading the Signals" must still be excised and counted
# (the renderer matches case-insensitively, so the gate must too, or a valid block false-FAILs).
INFER_TC = INFER.replace("## Reading the signals (inferred, not confirmed)",
                         "## Reading the Signals (inferred, not confirmed)")
GOOD_TC = GOOD.replace("## Source Ledger", INFER_TC + "## Source Ledger")
expect(check_status(GOOD_TC, "no_unsourced_absence") == "PASS",
       "a title-cased inference heading must still be excised (no false no_unsourced_absence FAIL)")
expect(check_status(GOOD_TC, "inference_block") == "PASS",
       "the advisory must find bets under a title-cased heading, not report 'no bets'")
expect(not [r for r in fg.check_sheet(GOOD_TC, "") if r["status"] == "FAIL"],
       "a well-formed title-cased inference block must not FAIL the sheet")


# --- report ---------------------------------------------------------------------

if failures:
    print(f"SMOKE TEST FAILED ({len(failures)} assertion(s)):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)

print("SMOKE TEST PASSED: dates, sections, item fields, chase, reconciliation, recency, coverage, "
      "zero-item, HTML render, and Wave-1 content-shape (rank order, trigger date, structural fence, "
      "send-now anchor, pasteable hook).")
sys.exit(0)
