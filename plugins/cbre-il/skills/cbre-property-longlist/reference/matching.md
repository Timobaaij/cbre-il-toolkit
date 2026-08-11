# Cross-source adjudication (the match sub-agent, exit 10)

When `run.py` writes `work/match_candidates.json` and exits 10, the deterministic
matcher (`helpers/match.py`) has done everything it safely can and a handful of
GREY-ZONE cross-source pairs remain. An isolated sub-agent resolves them by MEANING -
exactly the discipline of the photo-match (exit 9) and brochure interpretation (exit 3)
handoffs: the LLM judges equivalence, Python keeps the deterministic blockers, and the
gates verify.

**Two kinds of ambiguity ride this ONE candidates file**: the `pairs` array - AMBIGUOUS
RECORD MATCHES (are two records the same property?) - and the `field_conflicts` array -
GENUINE VALUE DISAGREEMENTS (two sources state different values for one field of a merged
property). Resolve everything the file lists in ONE round-trip. The match verdict goes to
`work/match_decisions.json`; the value pick goes to `work/field_decisions.json`. A run can
carry either, both, or (the common case) neither.

**A run may see exit 10 a SECOND time, and that is correct, not a fault.** A `pairs`
verdict changes which records are one property, which changes which value conflicts exist
and what their `conflict_id` is - so a conflict inside a cluster an open pair could still
alter cannot be adjudicated yet. Conflicts in clusters that no outstanding pair can touch
ARE listed immediately, so most runs settle in one round. When a second round does come:

- it lists `field_conflicts` **only**, plus `settled_pairs` (a count, for information);
- the `pairs` / `verify_pairs` keys are **absent**, deliberately - they are done;
- **do not create, empty, rewrite or delete `work/match_decisions.json` or
  `work/match_verify.json`.** Those hold the settled verdicts. (Python keeps a durable
  copy and merges over it, so a clobber cannot lose an answer - but it still wastes a
  round.)

## What the gates already decided (you only see the middle)

The matcher classifies every record PAIR into four tiers BEFORE you are involved:

**The size veto is FOOTING-AWARE.** A >15% area gap hard-blocks a pair as `forbidden`, and
forbidden pairs are never shown to you - so the comparison has to be honest about units.
Both sides stating the same unit compare directly; a stated `sq m` against a stated `sq ft`
is converted first (they used to sit 90.7% apart and were vetoed as "different buildings",
which is how one property shipped as two cards that nobody could merge); and if only one
side states a unit, the footing is UNKNOWN and Python refuses to compare rather than block -
the pair comes to you instead. Python converts or abstains; it never decides sameness.

- **auto** - confidently the SAME property; already merged without asking you (a
  cross-source identical key + area agreement, a coordinate net <= 300 m with agreeing
  developers and no >15% size conflict, a postal-address park contained in a brochure
  scheme name, an empty-park tracker row with matching city/developer/area).
- **forbidden** - a HARD blocker the matcher will NEVER merge, **even if you say
  'same'**: a material size conflict (both warehouse areas present and differing by more
  than 15%), or two records from the SAME source file with differing areas (distinct
  phases). You are never shown a forbidden pair, and `same_property` returns False for it
  before your verdict is even read. The catastrophic over-merge class is therefore
  impossible by construction. **A developer DISAGREEMENT is NOT a hard blocker** - now
  that landlord and developer are distinct fields (`extract_xlsx` no longer conflates an
  owner/asset-manager/landlord into the developer), a genuine developer-name difference
  (a naming variant, a JV, an asset sale) is a GREY signal you adjudicate, not a veto;
  the >15% size conflict remains the hard blocker.
- **grey** - cross-source, NOT forbidden, NOT auto, but it cleared a RECALL pre-filter:
  within ~2 km, OR sharing >= 1 distinctive park token, OR a borderline fuzzy key in
  [70, 88), OR in the same city with the developer linking the two records (the same known
  developer on both, or one side's developer name appearing in the other's park string).
  This INCLUDES a developer-disagreement pair that clears the pre-filter. **These are the
  only pairs in `match_candidates.json`** - the genuinely ambiguous middle. (The coord-net
  AUTO path still requires developer agreement, so a disagreement is never auto-merged -
  it always comes to you as grey.)
  **A SHARED CITY ALONE DOES NOT CLEAR THE PRE-FILTER.** A longlist is usually one town or
  one market, so the city is the one attribute every record shares and it distinguishes
  nothing; treating it as a signal made the grey set quadratic and spent two LLM
  judgements per pair on questions with no evidence behind them. So if you are wondering
  why two obviously-unrelated buildings in the same town are not in your file: that is
  deliberate, and a wrong split is caught downstream by the coverage dedupe gate.
- **no** - definitely distinct; never shown to you.

So your job is narrow and honest: for each grey pair, decide whether `a` and `b`
describe the SAME physical property, like a human reading two listings.

## Input: `work/match_candidates.json`

```json
{
  "pairs": [
    { "pair_id": "<opaque stable hash>",
      "a": { /* full record: developer, city, park, region, country, warehouseArea,
                areaUnit, description, lat, lng, status, __meta.source_file, ... */ },
      "b": { /* the same fields for the other record */ } }
  ],
  "output": "work/match_decisions.json",
  "instructions": "..."
}
```

Each pair carries BOTH full records. `pair_id` is an order-independent content hash
(`pair_id(a, b) == pair_id(b, a)`); copy it verbatim into your output.

## Output: `work/match_decisions.json`

A single JSON object keyed by `pair_id`, covering EVERY pair_id you were given:

```json
{
  "<pair_id>": { "verdict": "same" | "different", "reason": "<one line for the audit>" }
}
```

(A bare `"same"`/`"different"` string is also accepted, but the `{verdict, reason}` form
is preferred because the reason lands in the audit trail.)

## How to judge

- **same** - the two records are the SAME building/site described twice from different
  sources. Example: `"Raven Park, Corby"` (a brochure scheme name) and
  `"Unit 1, Raven Park, Earlstrees Industrial Estate, Corby NN17 4XD"` (a tracker's full
  postal park) - the same property.
- **different** - two distinct properties that happen to look similar. Example:
  `"Alpha Park"` and `"Beta Park"`, same developer and city - different schemes.
- **DEFAULT TO 'different' WHEN UNSURE.** This is the honest, safe choice: an over-SPLIT
  is caught and force-fixed by the coverage dedupe gate (two cards with the same
  park+city+developer+area BLOCK the build until merged); an over-MERGE silently
  destroys a property - it is invisible and unrecoverable. The whole skill's principle is
  "a thin-but-honest record beats a confident-but-wrong one": splitting is the honest
  default.
- **NEVER invent a property, a field, or a fact** to justify a verdict. Read only the two
  records you were given; if the evidence does not show they are the same, they are
  `"different"`.
- You are resolving equivalence ONLY. Do not edit either record, do not transcribe or
  change any value, do not merge fields - the spine does the merge from your verdict.

## What happens next (determinism + verification)

- Your verdict is CACHED in `work/match_decisions.json`, keyed by the stable `pair_id`.
  On the re-run, `merge` reads it and clusters byte-deterministically - no live per-pair
  call, so a re-run with the same inputs and the same decisions yields a byte-identical
  `canonical.json`.
- If an input edit later creates a NEW grey pair your file does not cover, `run.py`
  re-emits `match_candidates.json` and exits 10 again (resume-safety) - it never silently
  guesses. A malformed or half-written decisions file is treated as absent (re-emit +
  exit 10).
- The **coverage dedupe gate** (`gate_runner.py coverage`) is the VERIFIER: a wrong
  SPLIT leaves two identical (park, city, developer, warehouse area) cards and BLOCKS the
  build (run.py exit 6) until fixed. The **forbidden tier** is the structural blocker
  against a wrong MERGE. `trace-coverage` still requires every merged field to trace to a
  source. The deterministic matcher remains the OFFLINE FALLBACK - with no decisions file
  it clusters exactly as it always has.

## Independent verification pass (`verify_pairs` -> `work/match_verify.json`)

The grey-zone MATCH verdict is the second of the two highest-risk LLM judgements, so it
is checked by a SECOND, BLIND, INDEPENDENT re-judgement. `match_candidates.json` carries
a `verify_pairs` array echoing the SAME grey `pairs` (same `pair_id`s, BOTH full
records, NEVER the matching pass's verdict) and a `verify_output` of
`work/match_verify.json`.

- **Independence is mandatory.** Dispatch a SEPARATE fresh agent for `verify_pairs` -
  NOT the one resolving `pairs`, and never shown its verdicts. It re-judges same/different
  from the two records alone, under this same "How to judge" contract, and writes
  `work/match_verify.json` in the SAME schema as `match_decisions.json` ({pair_id:
  {verdict, reason}}). Dispatch it CONCURRENTLY with the `pairs`/`field_conflicts` agents
  (one round-trip).
- **The diff is deterministic Python, ADVISORY only.** On the re-run `run.py` compares the
  two passes per `pair_id`; a pair where the verifier disagrees with the matching pass is
  written (pure Python) to `work/match_verify_conflicts.json` and folded into merge's
  `meta.conflicts` -> the Gaps Report **Source conflicts** section as a `match
  disagreement (broker to resolve)` line. The **matching pass's verdict still drives
  clustering** - the verifier NEVER flips it; the forbidden tier + coverage dedupe remain
  the only structural match blockers. The blind G-trace/G-honesty reviewers re-read both
  records and can escalate a confirmed-wrong `same` (a fused record) to a red.
- **Cached, deterministic.** The verify verdict is keyed by the same order-independent
  `pair_id`, so the diff is recomputed from the cached files on resume (no live
  re-dispatch) and `built.html` stays byte-identical. With NO `match_verify.json` present
  (every offline run / eval) the diff is empty - no conflict line, byte-identical
  `canonical.json`, exactly like `match_decisions.json` absent.

Then re-run the same `run.py` command - it resumes and merges.

---

# Cross-source value-conflict adjudication (the `field_conflicts`, same exit 10)

Once records are clustered into one property, `merge` chooses each field's value by a
FIXED source PRECEDENCE (commercials: newest email > excel > brochure; specs/geo:
brochure > excel > email; a rich tracker leads the structured specs). When two+ sources
in a cluster hold DIFFERENT non-unknown values for one field, that is a genuine
cross-source value conflict. The fixed precedence already picks a winner - the
`default` - and that default is shipped offline and whenever you are unsure. Your job is
narrow: for each conflict, decide whether one of the candidate values is clearly the
RIGHT one and the default is clearly WRONG; if so, pick it; otherwise keep the default.

## Input: `field_conflicts` in `work/match_candidates.json`

```json
{
  "field_conflicts": [
    { "conflict_id": "<opaque stable hash, copy verbatim>",
      "cluster_key": "lodz|prologis|delta park",
      "field": "warehouseRentVal",
      "candidates": [
        { "label": "a", "value": 55.0, "source_type": "xlsx", "date": "2025-02-01",
          "locator": "Sheet1!r9", "source_file": "Tracker.xlsx",
          "prov_tag": "xlsx", "precedence_rank": 0 },
        { "label": "b", "value": 70.0, "source_type": "pdf", "date": "2025-01-01",
          "locator": "page 2", "source_file": "Delta brochure.pdf",
          "prov_tag": "text interpretation", "precedence_rank": 1 }
      ],
      "default": "a" }
  ],
  "field_output": "work/field_decisions.json"
}
```

The records themselves are NOT re-transcribed - only the two+ disagreeing values plus
each source's metadata. `default` is the label the fixed precedence already chose.

## Output: `work/field_decisions.json`

A single JSON object keyed by `conflict_id`, covering EVERY conflict_id you were given:

```json
{
  "<conflict_id>": { "pick": "<label>", "reason": "<one line for the audit>" }
}
```

(A bare `"<label>"` string is also accepted; the `{pick, reason}` form is preferred so
the reason lands in the audit trail.)

## How to judge

- **KEEP the default** unless a candidate is CLEARLY the right value AND the default is
  CLEARLY wrong. Legitimate override cases: a typo in a newer email, a mislabelled
  tracker column, an ask-price quoted where a negotiated rate exists. The fixed
  precedence is right far more often than not - moving the needle is the exception.
- **NEVER invent a value.** Pick only among the given candidate labels. There is no
  free-text value field; you select, you do not author. A value neither source carries
  cannot be chosen (it would have no source to trace, breaking the "tbd, never invented"
  contract).
- **When unsure, pick the default** (or omit the override - an absent/default pick keeps
  precedence). Picking the default is always safe.
- You are resolving ONE field's value. Do not edit any other field, do not merge, do not
  re-transcribe - the spine applies your pick.

## What happens next (determinism + verification)

- Your pick is CACHED in `work/field_decisions.json`, keyed by the stable, order-
  independent `conflict_id` (a hash of the merged property's match_key + field + the
  SORTED set of disagreeing values). On the re-run `merge` reads it - no live per-field
  call - so the same inputs + the same picks yield a BYTE-IDENTICAL `canonical.json`.
- **The pick is ADVISORY: Python verifies it against the field's plausibility gate before
  honouring it.** The gate answers one of THREE things, each with a different outcome:
  - **`pass`** - the override is honoured.
  - **`fail`** - the value is implausible. The precedence default is kept **only if the
    default passes that same gate**; if NEITHER value passes, the field is struck to
    **`tbd`** with a note naming both. (It used to reinstate the rejected default
    unconditionally, so the gate could protect a default but never catch one - that is how
    an impossible BREEAM `A+` reached a client card.)
  - **`none`** - no gate is defined for this field. The selection **IS honoured**, labelled
    `[unverified: no deterministic gate is defined for this field]` in the Gaps Report. You
    only ever select among values that already exist in the sources, so an unverified
    selection cannot invent data - whereas discarding it made your judgement decorative on
    every non-numeric field.

  **Which fields are gate-verified:** `warehouseRent` / `warehouseRentVal` / `officeRent`
  (the per-area band: €/m² 1.5-500, £/sq ft 0.5-60); `warehouseArea` / `plotArea` /
  `officeArea` / `officeAreaVal` (> 0 and inside the area band); `lat` / `lng` (bounds);
  **`breeam`** (must CONTAIN a real BREEAM band - Pass / Good / Very Good / Excellent /
  Outstanding - so an EPC letter band is rejected); **`epc`** (a letter band A-G with an
  optional `+`, optionally prefixed `Target`); **`loadingDocks`** / **`overheadDoors`** /
  **`truckParking`** / **`carParking`** (a non-negative integer <= 2000); **`clearHeight`**
  (3-30 metres; a height stated in FEET is ungated rather than judged against a metre
  band). Every other field is `none` - honoured and labelled unverified.
- **The same gates also check the PRECEDENCE WINNER**, not only an override, so a bad value
  is caught whichever source it came from and whether or not a conflict exists. A default
  that fails its own gate is struck to `tbd` and named in the Gaps Report.
- Every adjudicated conflict - an honoured override (with your reason) OR a vetoed pick -
  is recorded in `meta.conflicts` and surfaced in the **Gaps Report** (Source conflicts
  section), so it is auditable, never silent. `trace-coverage` still requires the chosen
  value to trace to its real source; because you only ever SELECT an existing candidate,
  it always does.
- If an input edit later changes the set of disagreeing values, the `conflict_id`
  changes, your file no longer covers it, and `run.py` re-emits + exits 10 rather than
  silently reusing a stale pick (resume-safety, mirroring the grey-pair path). A
  malformed or half-written file is treated as absent (precedence is the fallback).

Then re-run the same `run.py` command - it resumes and merges.
