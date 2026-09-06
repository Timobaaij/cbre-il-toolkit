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
  cross-source identical key + area agreement, a coordinate net <= 300 m with the SAME
  DEVELOPER STATED ON BOTH SIDES and no >15% size conflict, a postal-address park contained
  in a brochure scheme name on the same terms, an empty-park tracker row with matching
  city/developer/area). **No postal-code disagreement, on any of them** - see below.

  **THE AUTO TIER IS NO LONGER AUTHORITATIVE IN BOTH DIRECTIONS, AND THIS IS A CHANGED
  CONTRACT.** It used to read "an auto pair always merges, and `decisions` is not even
  consulted". It now merges **unless a recorded verdict says the two are `different`**. The
  reason is the asymmetry this whole file keeps returning to: an over-split puts two
  similar-looking cards in front of a reader who can see and query them, while a FUSION is
  offered to nobody and nothing in the pipeline can split a merged property afterwards - and
  yet the auto tier was the one tier no human was ever shown. The near-identical-key fuzzy
  tail merges on `city|developer|park` scoring >= 88, and that key CANNOT SEE a unit name, a
  building name or a street, so two units of one park fused into a single card while the other
  unit dropped off the longlist. `confirm_pairs` (below) is how you now see those, and the
  downgrade is what makes seeing them worth anything.

  **The downgrade is one-way and explicit-only.** Only the exact verdict `different` splits an
  auto pair. An absent verdict, no decisions file at all, `same`, `unsure` or anything
  unrecognised leave the merge precisely as the matcher made it - offline behaviour is
  unchanged to the byte. And it does not reach `forbidden`: a structural blocker still beats
  every verdict, in both directions.

  **THE CODE VETO IS NOW ONE GUARD COVERING ALL FOUR AUTO PATHS.** Two differing stated
  postal codes are two addresses. The code used to be read by the grey pre-filter's identity
  tokens and by nothing else, so two buildings on separate estates a few hundred metres apart
  with near-identical areas cleared the coordinate net. The first fix put the veto in two of
  the four merging paths; because the tiers are tested in the order auto, forbidden, grey, an
  auto path that does not check the code pre-empts the hard blocker below, so the empty-park
  branch and the near-identical-key fuzzy tail went on FUSING two unit codes on one park.
  Both are closed: the test is a single guard at the top of `_cross_source_auto`, ahead of
  every branch, so there is no path left to add one around. An ABSENT code is still no signal
  at all, in either direction: a market whose records carry no postal codes is entirely
  unaffected.

  **What that costs, plainly.** A code-vetoed pair goes to `forbidden`, and forbidden pairs
  are never enumerated for you - not even an explicit `same` verdict reaches them. So one
  building quoted with a unit-level code on one side and an estate-level code on the other is
  PERMANENTLY unmergeable and ships as two cards. That was accepted because an over-split
  puts two similar-looking cards in front of a reader who can query them, while a fusion is
  offered to nobody. Do not expect a gate to catch the split: see the note under "What
  happens next".

  **The developer rule is BOTH STATED AND EQUAL, which is wider than "two absences".** Both
  merging paths used to read an absence as "no disagreement", so a tracker row and a brochure
  that each named no party could merge on a pin and a floor area alone. They now require the
  developer stated on both sides and equal - which also demotes a **ONE-SIDED** absence, and
  that is deliberate: one stated party corroborates nothing on its own either.

  **The measured cost of that, also plainly.** A record whose city, park and developer are
  all unknown, pinned ~100 m from its named twin, is the founding incident the coordinate net
  was written for, and it now SPLITS. It lands in **grey**, so it reaches you and merges on a
  `same` verdict - but on a headless or offline run there is no adjudicator, the deterministic
  matcher is the whole decision, and it ships as two cards. **No gate catches it**: the two
  cards differ on park, city and developer, so the coverage dedupe key cannot match them.
  Pinned in `evals/extract_test.py` (coord-net section) and `evals/overmerge_guard_test.py`.
- **forbidden** - a HARD blocker the matcher will NEVER merge, **even if you say
  'same'**: a material size conflict (both warehouse areas present and differing by more
  than 15%), **two differing stated postal codes** (now on every cross-source pair, since
  no auto path can claim one first), or two records from the SAME source
  file with differing areas (distinct phases). You are never shown a forbidden pair, and
  `same_property` returns False for it before your verdict is even read. These blockers put
  the worst over-merges out of reach of any 'same' verdict; they are **not** a general
  guarantee against over-merging, and the paragraph under G-coverage in `gates.md` says
  what is still uncovered. **A developer DISAGREEMENT is NOT a hard blocker** - now
  that landlord and developer are distinct fields (`extract_xlsx` no longer conflates an
  owner/asset-manager/landlord into the developer), a genuine developer-name difference
  (a naming variant, a JV, an asset sale) is a GREY signal you adjudicate, not a veto;
  the >15% size conflict remains the hard blocker.
- **grey** - cross-source, NOT forbidden, NOT auto, but it cleared a RECALL pre-filter.
  **These are the pairs in `match_candidates.json`'s `pairs`** - the genuinely ambiguous
  middle, and the only ones a `same` verdict can MERGE. (They are no longer the only pairs in
  the file: `confirm_pairs` carries already-merged auto pairs for confirmation. See below.)
  This INCLUDES a developer-disagreement pair that clears the pre-filter. (Every AUTO
  merging path requires the same developer STATED on both sides, so a disagreement, a pair
  of absences and a ONE-SIDED absence are all kept out of auto - each comes to you as grey
  if it clears the pre-filter on some other signal. A stated-code disagreement is the
  exception: it is a hard blocker, so it goes to `forbidden` and never reaches you, which
  means the pairs you most want to rescue by hand are exactly the ones you will not see.)

  **The pre-filter reads the two records' identifying free text HOLISTICALLY, not
  field-by-field.** Each record contributes two bags of tokens:
  - an **identity bag** - every park / address / street / scheme / estate / building /
    site / postcode-ish field it happens to carry;
  - a **party bag** - every developer / landlord / owner-ish field it happens to carry.

  Both bags are stripped of the pair's **place words** (city, region, district, country),
  of generic scheme words ("park", "logistics", "estate", "unit"...), of street furniture
  and corporate boilerplate ("street", "north", "management", "holdings"...), of single
  characters, and of **area-code-shaped tokens** (a postcode OUTWARD code like `QX41`,
  a road number like `X9` - both label a whole town, not a building; the inward half
  `7ZP` survives, because it narrows to a handful of addresses).

  A pair then clears the pre-filter when ANY of these holds:
  - a pin within ~2 km; **OR**
  - the two **identity bags share a token** - in any direction and across any pair of
    fields, so the scheme name a broker typed into an "Address" column corroborates the
    scheme name a brochure printed as its title; **OR**
  - a borderline fuzzy key in [70, 88); **OR**
  - the two records state the **same known city** AND a **party name links them** - the
    same known developer on both, a party token of one record appearing in the other's
    identity bag (either direction), or the two party bags sharing a token (which is how
    a "Landlord" on one side meets a "Developer" on the other).

  **Why the identity bag is un-gated and the party bag is city-gated.** A scheme or street
  name discriminates on its own. A party name does not: one developer builds many sheds,
  so an un-gated party match would make the grey set quadratic across a whole country.

  **A SHARED CITY ALONE DOES NOT CLEAR THE PRE-FILTER.** A longlist is usually one town or
  one market, so the city is the one attribute every record shares and it distinguishes
  nothing; treating it as a signal made the grey set quadratic and spent two LLM
  judgements per pair on questions with no evidence behind them. The same argument is why
  region, district and country names are stripped from both bags. So if you are wondering
  why two obviously-unrelated buildings in the same town are not in your file: that is
  deliberate. If the pre-filter is ever wrong about such a pair, the result is two cards a
  reader can see - **not** something the coverage dedupe gate catches, since that gate needs
  two cards identical in park, city, developer and area, which a pair the pre-filter dropped
  essentially never is (measured: 13 of 13 on the corpus in
  `evals/grey_prefilter_test.py`).

  **What this means for you.** Because the field boundary is gone, a grey pair you receive
  may be corroborated by a name that sits in DIFFERENT fields on the two records - a park
  name against an address fragment, a landlord against a developer. That is a real signal,
  not a bug in the file. It is also only a *candidate* signal: the pre-filter's job is
  recall, yours is the judgement, and "LEAN 'different' ON THIN EVIDENCE" below is
  unchanged.
- **no** - definitely distinct; never shown to you.

### `confirm_pairs` - auto merges that disagree about their own identity

**These pairs are ALREADY MERGED.** They are not "should these become one card?" questions -
they are one card already, with the second record's fields blended into it. You are being
shown them because a fusion is the one matcher error a reader can never see and nothing can
undo, and because the auto tier used to be shown to nobody at all.

**Why these ones and not every auto pair.** Only auto pairs whose two records BOTH SPEAK in one
identity class and DISAGREE in it are surfaced. `disagrees_on` names the class:

| class | fields | what it means |
| --- | --- | --- |
| `party` | developer, landlord, owner, asset manager, freeholder | no party name in common. A naming variant, a JV or an asset sale looks like this - and so do two different buildings |
| `name` | park, scheme, estate, site, building name, property name | no distinctive scheme token in common ("Alpha Court" vs "Beta House") |
| `unit` | unit, unit name, building | different DESIGNATORS ("Unit 1" vs "Unit 7"). The merge key cannot see this class at all, which is why it is the most valuable one here |
| `street` | address, address line, street | no distinctive street token in common |

An exit that listed every auto pair would be noise, noise gets skimmed, and a skimmed
adjudication exit is worse than never asking - so the filter is deliberately strict. **A
one-sided absence is never a disagreement** (the same both-sides-stated discipline the size,
code and developer tests use: a gap is only evidence when both sides actually spoke), and
agreement is a SHARED token rather than an equal string, so "Kestrel Reach" against "Unit 1,
Kestrel Reach, Halston Industrial Estate" agrees - as it must, since containment is what the
auto tier's containment branch merges on. **The postal code is deliberately absent from that
table**: two differing stated codes send a pair to `forbidden` before the auto tier can claim
it, so a code conflict can never appear here. **The area is absent too**: every auto branch
already vetoes a material size gap, so anything that reached `auto` agrees on size within the
tier's own tolerance.

**How to answer one.** Write it into the SAME `work/match_decisions.json`, under its own
`pair_id`. Judge it ONE WAY ONLY:

- `"different"` - you are confident the two records describe TWO DIFFERENT physical
  properties. This SPLITS them back into two cards.
- anything else - `"same"`, `"unsure"`, or simply leaving the pair out of the file - leaves the
  merge exactly as it is.

So the cost of saying nothing is zero, and the cost of saying `different` when you are unsure
is a split the reader has to query. **Say `different` only when you are confident, never to be
safe.** Give a `reason` naming the evidence either way.

**They are offered ONCE.** `confirm_pairs` rides the same round-trip as `pairs` and is dropped
with them: once the grey pairs are settled, the round-two candidates file omits both, so a
merge somebody has already looked at and let stand is never re-offered. Re-offering it every
round would be an over-split by attrition.

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
  `"Unit 1, Raven Park, Earlstrees Industrial Estate, Corby QX41 8RD"` (a tracker's full
  postal park) - the same property.
- **different** - two distinct properties that happen to look similar. Example:
  `"Alpha Park"` and `"Beta Park"`, same developer and city - different schemes.
- **A DIFFERING PARTY NAME IS NOT, BY ITSELF, A 'different' VERDICT.** One record's
  `developer` may be the other's `landlord`, a JV partner, a fund that bought the asset, or
  the same house after a rebrand - and a broker's spreadsheet column headed "Landlord" is
  routinely bound to `developer` and vice versa. Weigh the PROPERTY evidence (the scheme
  name, the address, the size, the specification, the pin) and treat the party names as one
  more field that may disagree. Equally: two records sharing only a party name and nothing
  else are `different` - a developer builds many sheds in one town.
- **LEAN 'different' ON THIN EVIDENCE; GENUINELY TORN IS `"unsure"`.** Splitting is the
  safe lean, and here is exactly how safe. It is force-fixed by the coverage dedupe gate
  **only** when the two cards end up identical on park, city, developer AND warehouse area
  (that BLOCKS the build until merged); differ on any one of the four - which two records
  a broker wrote up differently usually do - and the gate cannot see the split at all, so
  what you are relying on is that two similar-looking cards sit in front of a reader who
  can query them. An over-MERGE blends two properties into one card and drops the other
  from the longlist: it is not offered to anybody for review, and the only thing that looks
  for it is the same gate's narrow postal-code check (below). But when you are
  GENUINELY torn after real effort, `"verdict": "unsure"` is a first-class answer: an
  interactive run puts the pair to the BROKER (who knows the market); a headless run
  ships 'different', disclosed. Never use it to avoid the work - most pairs are decidable
  from the records. (The blind VERIFY pass stays binary: same/different only.)
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
- The **coverage dedupe gate** (`gate_runner.py coverage`) is the VERIFIER **for one exact
  shape of wrong SPLIT**: two cards identical on park, city, developer AND warehouse area
  BLOCK the build (run.py exit 6) until merged. It keys on exact equality of all four, so a
  split whose two cards differ on any one of them is invisible to it - do not read it as
  general cover for splitting.
- The same gate now also carries an **over-MERGE check**: a property built from records that
  state two DIFFERENT postal codes BLOCKS, naming the files and the codes. That is a narrow
  net rather than a verifier - it needs the contributing records to state codes at all
  (entirely inert in a market that quotes none), it cannot see a fusion of records that
  agree on the code or state none, and it inspects the FINISHED dataset, so it catches a
  fusion rather than preventing one. The **forbidden tier** remains the structural blocker
  that prevents the named over-merge shapes up front. `gates.md` (under G-coverage) states
  what is and is not covered.
- `trace-coverage` still requires every merged field to trace to a source. The deterministic
  matcher remains the OFFLINE FALLBACK - with no decisions file it clusters as it always
  has, except where the A12/A12b/A13 tightenings deliberately split what it used to merge
  (see the **auto** bullet).

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
`default` - and that default is shipped offline and on an explicit decline. Your job is
narrow: for each conflict, decide whether one of the candidate values is clearly the
RIGHT one and the default is clearly WRONG; if so, pick it; if the default plainly holds,
keep it. When you are GENUINELY torn after real effort, `"pick": "unsure"` is a
first-class answer: an interactive run puts the choice to the broker (who can only pick
among the stated candidates); a headless run keeps the default, disclosed. Never use
"unsure" to avoid the work - most conflicts are decidable from the records.

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
- **Leaning-default is safe; GENUINELY torn is `"unsure"`.** When the default plainly
  holds (or nothing moves the needle), pick it. When you are genuinely torn after real
  effort, `"pick": "unsure"` hands the choice to the broker (interactive) or keeps the
  default disclosed (headless) - never a silent coin-flip either way. On an interactive
  run it reaches the broker only where the FIELD is material (`clarify.field_is_material`:
  the dashboard renders it, or the matcher reads it for identity). An `unsure` on an
  open tracker column or another Excel-only field keeps the precedence default, recorded
  as a disclosed decision in the Gaps Report - it is never left hanging, and the losing
  value still appears under Source conflicts.
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
