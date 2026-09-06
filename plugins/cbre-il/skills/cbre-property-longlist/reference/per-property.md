# The per-property view and the repair path

Two artefacts, written between enrichment and the pre-build gates. One is how you SEE a single
option; the other is how you CORRECT it. They are deliberately not the same file.

Both live in the **work dir** - `work/<x>` below means `<the work dir>/<x>`, i.e.
`2. Work Files/<x>` in the three-folder project layout (SKILL.md "The project folder"). They are
internal, never client-facing: nothing from `properties/` or `repairs.json` is ever copied into
`3. Output`.

## Why this exists

Everything upstream of the merge is about the SET: which sources describe the same building,
what the dominant area unit is, which fields any source ever stated. That work needs one global
dataset and it has one, `canonical.json`.

Everything downstream is about ONE property: is this hero the right building, why is this rent
odd, this figure is on page 6 but the card says `tbd`. `canonical.json` is a single file most of
whose bytes are base64 images, so it cannot be read that way, and until now the only correction
mechanism, `overrides.json`, targeted a SOURCE RECORD rather than a property.

That mismatch had two costs on live runs. Finding which of several records supplied a merged
value took longer than the fix. And a per-property correction re-derived the cluster anchors,
which re-keyed settled conflict decisions and triggered a fresh adjudication round for a single
changed pair - the same shape the `cluster_anchor` note records, where an image-only repair
re-keyed nine settled value decisions.

## `work/properties/` - the view (READ-ONLY)

```
work/properties/
  01-indurent-park-chippenham-unit-c112/
    property.json         the record, readable, base64 blobs replaced by media filenames
    media/                hero.jpg, gallery-02.jpg ..., plan.jpg - real files you can open
    media/considered/     the DISCARD PILE: every page render + candidate image this property
                          had to choose from - p<page>-render.png, p<page>-c<index>.jpg
    media_decisions.json  chosen vs rejected vs never-looked-at, each with WHY
    sources.csv           this property's Source Ledger rows and nothing else
    notes.md              its unknowns, its conflicts, its repairs, and its repair key
  _unassigned/            deck pages NO property claimed (once per run)
  index.json
```

### `media/considered/` and `media_decisions.json` - the discard pile

`media/` answers *what did this card ship*. It cannot answer the question anyone actually asks
when a card looks thin: *was there anything better, and why was it not used?* On a run whose
image layer was quietly degraded that question had no answerable form at all - every artefact of
a blind harvest is identical to one of an empty source.

So the projection also writes what merge CONSIDERED. Page and candidate numbers are **0-based**,
the same numbering as `__meta.page_no` and `__meta.heroRef` / `planRef`, so a reviewer who spots
the right image here can read its number off the filename and put it straight into
`repairs.json`. `media_decisions.json` states, per deck: the pages this property looked at, the
pages it did NOT (each with the rule that removed them - claimed by a neighbour, off-limits for
the plan slot, or rejected by a visual-QA reviewer), the candidates the interpreter excluded as
decorative, what was chosen for the hero/plan/gallery and where it came from, and the site-plan
near-misses (a page that LOOKED plan-ish but a precision guard refused, with the reason). The
per-deck block carries `claimed`, `foreign`, `plan_reach` and `gallery_reach` separately, so
"why is this carousel thin" is answerable without a debugger: a page in `claimed`/`gallery_reach`
whose image is not in `media/` was LOOKED AT and refused by a carousel floor (decorative, or below
`images.MIN_GALLERY_W/H`); a page in neither was never in reach at all. `hero.promoted` is true
when the bound hero itself failed those floors and a card-quality photograph replaced it.

It is per **PROPERTY**, not per brochure. Two units sharing one deck each get their own complete
folder and the same image can appear in both. That duplication is intended: the question is what
THIS card had to choose from, and an answer that makes you open a second folder to find out is
not an answer.

Requires `--source-dir` (the spine passes it automatically); without it the folder is simply
absent and the projection is exactly what it was before. Same for `--no-media`.

### `_unassigned/` - the pages nobody claimed

Once per run: every deck page that no property claimed, neither as its `__meta.page_no` nor in
its `__meta.image_pages`. Nothing in the harvest looked at these - not the carousel, not the
site-plan tier, not the placeholder audit - so on a multi-property or whole-park donor deck this
is exactly where a missed site plan hides. The `media-harvest` gate raises a `[SIGNAL]` for the
same pages. The fix is always a RECORD-level one (give the page to the property it shows via
`__meta.image_pages` / `__meta.plan_page` on a re-read), never an edit here.

Rebuilt from `canonical.json` on every run. **Nothing reads it back.** Editing a file here
changes nothing and the next run overwrites it - there is an eval that asserts exactly that.

That asymmetry is the design. Two writable representations of one dataset drift, and the drift
is silent; the sibling Kato skill maintains three patch helpers because of it. So the view is a
view, and edits go somewhere else.

`notes.md` prints the property's **repair key**, because the surface that shows you the problem
should hand you what you need to fix it.

## `work/repairs.json` - the correction (the only writable half)

A JSON list, append-only, re-applied on every run.

```json
[
  {
    "id": "rp-001",
    "property": { "key": "chippenham|indurent|indurent park chippenham unit c24", "id": 5 },
    "expect":   { "warehouseArea": 21759 },
    "set":      { "warehouseArea": 23567 },
    "why": "the tracker took the brochure's warehouse-and-GF-office line, not the unit total",
    "verified_by": "you@cbre.com"
  },
  {
    "id": "rp-002",
    "property": { "key": "chippenham|tbd|indurent park chippenham unit c106", "id": 2 },
    "media": { "hero": "repair_media/c106-estate-aerial.jpg" },
    "why": "no brochure exists for this unit, so nothing could be harvested",
    "verified_by": "you@cbre.com"
  },
  {
    "id": "rp-003",
    "property": { "key": "chippenham|indurent|indurent park chippenham unit c24", "id": 5 },
    "unset": ["serviceCharge"],
    "strike_from_source": "neighbouring-unit-brochure.pdf",
    "why": "the matcher merged two units; everything from that deck is the other one",
    "verified_by": "you@cbre.com",
    "source_file": "unit-brochure.pdf",
    "source_locator": "page 6 (specification table)"
  }
]
```

- **`property`** names the target. `key` is the property's match key, printed in its `notes.md`;
  `id` is a second confirmation. Give both. A key is `city|developer|park`, so every multi-unit
  park produces several properties sharing one - the two are INTERSECTED, so the id
  disambiguates a shared key. Only an id pointing OUTSIDE the key's matches is a conflict.
- **`expect`** is optional and strongly recommended. It is compared against the property's
  CURRENT values, and this is what lets an entry survive a re-match: if identity moved under it,
  the guard fires instead of the value. **Absence is one bucket**: a field a plausibility gate
  struck holds `None` but reads `tbd` on the card, in the ledger and in `notes.md`, so
  `"expect": {"warehouseArea": "tbd"}` matches it. A field now holding a different STATED value
  still supersedes, which is the whole point of the guard.
- **`set`** takes any field the SCHEMA declares OR any field **this property already carries**,
  including one it does not yet carry when the schema declares it (filling an absent `region` is
  a real case). The record half matters more than it sounds: the extraction contract emits a
  stated row with no canonical home under a descriptive key, so off-spec keys are a normal and
  large part of every record - and while the guard tested schema membership alone, a value that
  was already on the record and wrong could be corrected by neither channel, because
  `overrides.json` cannot address a merged property and this one refused the key. A name on
  NEITHER the schema nor the target property is still refused: a typo may not create a field.
  The check is per-TARGET, so an off-spec key that lives on a different property is refused too.
  Denied outright: `id`, `photo`, `gallery`, `plan`, `preBaked` (structural or media-owned), and
  `areaUnit`/`rentUnit` - those relabel every figure at once, which is the 10.76x error class
  `overrides.json` denies for the same reason.
- **`unset`** is a LIST of field names to CLEAR. Cleared means the key is **removed**, not
  overwritten with `tbd`: a sentinel written over a field is indistinguishable from a source
  that stated one, and the ledger row would then claim the repair SET a value when what you did
  was withdraw one. Removal returns the property to the state of a field no source ever stated,
  and `_common.fill_render_sentinels` re-fills every chrome-read key with its own honest unknown
  at the render boundary, so nothing the card reads can go blank while a genuinely off-spec key
  genuinely disappears. The ledger row says `CLEARED` in those words. Same `DENIED_FIELDS` as
  `set`. A field the schema lists as **required** (`city`, `country`, `developer`, `park`,
  `status`, plus `id` and `photo`, which `DENIED_FIELDS` refuses first) can never be cleared: an
  absent required key hard-blocks `validate-data`, so a one-card fix would cost the whole run.
  Its honest unknown is a sentinel VALUE - use `set`.
  **A name the target property does not carry clears nothing, writes no ledger row, and is
  reported `STALE`.** That is the accurate reading of both states it can mean - a clear that
  already landed on an earlier run, and a misspelling - so it never appears among the applied
  corrections and never mints a `repair` row for a field that exists nowhere. The message tells
  you which of the two it is when the Source Ledger can say (it still credits the property with
  a field that really was there), and tells you to check the spelling when it cannot. A `set` in
  the same entry still applies and still re-writes its own ledger row, so one satisfied clear
  never strands another field's provenance.
- **`strike_from_source`** is ONE source filename: *this property carries nothing from that
  file*. It removes every field whose merge-time provenance names it, which is the right shape
  of instruction for unfusing two records a matcher wrongly merged - nineteen hand-listed field
  names is not. Matched on **basename, case-insensitively**, the same rule `overrides.json`
  applies to `where.source_file`. Provenance is read from `work/source_ledger.csv` (a merged
  property carries none of its own: merge writes one ledger row per field instead), so the
  merge stage must have run. Each struck field gets its own ledger row, on every run, because a
  strike resolves its fields OUT OF the ledger and so every field it clears provably has a
  property row of its own. `DENIED_FIELDS` and the schema-required fields are **skipped and
  named** rather than removed, so you are told the hero still comes from that file (replace it
  with `media`) and the identity fields still do (re-state them with `set`). Zero fields matched
  is `STALE`; no ledger to read at all is `INVALID`, since "I could not look" is not the same
  answer as "that file contributed nothing".
  **A basename that names two different files strikes nothing and is `AMBIGUOUS`.** A folder of
  property materials from several senders routinely holds two files with one common name, and a
  strike DELETES, so guessing which of `inbox/sender-a/deck.pdf` and `inbox/sender-b/deck.pdf`
  you meant would silently drop correct, sourced data and then credit the removal to a file that
  never supplied it. The report names the competing paths verbatim; **disambiguate by re-stating
  `strike_from_source` with enough leading folders to pick one out** - a full path works, and so
  does any trailing part of one (`sender-a/deck.pdf`), matched a folder at a time rather than as
  a string, so `a/deck.pdf` is never read as part of `extra-a/deck.pdf`. One file the ledger
  happens to record at two depths (`deck.pdf` for one field, `work/inputs/deck.pdf` for another)
  is still ONE target, which is what basename matching exists for.

### What a clear actually changes

Removing a key is not always inert, and two of the consequences are invisible on the card:

- **Clearing `warehouseArea` can change what KIND of record the card is.** The coverage gate
  detects a land/plot option structurally (`gate_runner._is_land_record`): no real warehouse
  area, but a plot area or a land price. So on a property that also carries `plotArea` or
  `landPrice`, clearing `warehouseArea` silently reclassifies it as a LAND record and it is
  scored against `LAND_CORE` (`plotArea`, `landPrice`, `city`, `lat`, `lng`) instead of
  `WAREHOUSE_CORE` (`warehouseArea`, `warehouseRent`, `status`, `city`, `developer`, `lat`,
  `lng`). Its completeness score moves for four fields that are no longer expected of it and two
  that suddenly are. If the option really is a shed with an unreliable area figure, `set` the
  honest sentinel instead of clearing the key.
- **Clearing one half of a twin leaves the other half asserting a figure the primary no longer
  carries.** `warehouseArea`/`warehouseAreaSqm` is the pair that bites (the metric re-statement
  is display-only and is not derived at render time), and the same shape exists for
  `officeArea`/`officeAreaVal`, `officeRent`/`officeRentVal`,
  `expansionPark`/`expansionParkVal`, `warehouseRent`/`warehouseRentVal`, `region`/`regionCode`
  and `lat`/`lng`/`coordsApprox`. Clear the pair, not one of it. The stale twin still carries its
  own Source Ledger row, so the inconsistency is auditable rather than hidden, but nothing
  detects it for you.

The render boundary is what decides whether a clear is inert or not, and the split is uneven.
Of the **56** property keys the canonical schema declares:

| | count | what a clear does |
|---|---|---|
| schema-**required** | 7 | refused (`city`, `country`, `developer`, `park`, `status`, and `id`/`photo`, which are denied first) |
| further **denied** | 5 | refused (`areaUnit`, `rentUnit`, `gallery`, `plan`, `preBaked`) |
| clearable, **re-filled** at the render boundary | 29 | effectively inert on the card: `fill_render_sentinels` puts the key back with its own honest unknown (`tbd`, `—`, `??`, `""`, or `null` for `reit`/`warehouseRentVal`), so the card reads as an unknown rather than losing the row |
| clearable, **NOT re-filled** | 15 | the key is genuinely gone: `warehouseArea`, `warehouseAreaSqm`, `plotArea`, `epc`, `lat`, `lng`, `postcode`, `district`, `districtProfile`, `brochureLink`, `coordsApprox`, `regionCode`, `officeAreaVal`, `officeRentVal`, `expansionParkVal` |

An off-spec key (one the extraction contract emitted under a descriptive name, with no canonical
home) is never re-filled either, by definition. So a clear of anything in the last row, or of an
off-spec key, changes what the card ASSERTS; a clear of anything in the row above it changes
which sentinel it shows and nothing else.
- **`media`** takes `hero` or `plan`, a path relative to the work dir. The image is compressed
  through `images.py` exactly like a harvested one, so a repaired hero is indistinguishable in
  weight and encoding. Setting `hero` moves `gallery[0]` with it, or the carousel would open on
  the photo the repair replaced.
- **`why`** and **`verified_by`** are REQUIRED and non-empty. Both ship in the Source Ledger.
- **`source_file`** and **`source_locator`** are OPTIONAL and let a repair cite the evidence it
  was read from. They replace the Source Ledger columns of the same name; absent, the row reads
  `repairs.json` with the repair id as its locator, exactly as before. Cite them whenever a
  human read the value on a document page: without them, provenance can tell a reviewer that a
  correction happened but not where the value came from, which is the reviewer's next question.
  `overrides.json` takes the same two keys with the same semantics, so one habit covers both.
  A cited page is then EVIDENCE the `prov-containment` gate can check, so cite the page the
  value actually occurs on.
- A repair can never create or delete a property.

## Every guard fails closed

A repair landing on the wrong card is worse than one that did not land, so an entry that cannot
be resolved with certainty applies NOTHING and is reported:

| outcome | when |
|---|---|
| `STALE` | the key matched no property; `strike_from_source` named a file the ledger credits with no field on this property; or an `unset` named a key the resolved property does not carry (a clear that already landed, or a misspelling) |
| `AMBIGUOUS` | the key matched several and no `id` picks one out of them; the `id` names a property the key does not match; or `strike_from_source` named a basename the ledger credits to two or more genuinely different paths on this property |
| `SUPERSEDED` | `expect` no longer matches - the dataset moved under this entry |
| `INVALID` | a denied field; a **`set`** of a field name in no schema and on no record; an `unset` of a schema-required field; one field in both `set` and `unset`; a blank value; a blank `source_file`/`source_locator`; a missing `why`/`verified_by`; a `strike_from_source` with no ledger to read; the canonical schema's required-field list being unresolvable, so the clear guard cannot be armed; or a media file that is not there |

The membership rule reads differently on the two verbs, and the difference is deliberate. For
`set`, a name on no schema and on no record is `INVALID`: a typo must never be allowed to CREATE
a field. For `unset` it is `STALE`, because a clear cannot create anything - the entry is not
malformed, it simply did nothing - and `INVALID` would make a correctly re-applied clear refuse
itself for good on its second run, when the key it removed is on no property. What it must never
be is `APPLIED`: that is the bucket meaning a value moved, and reporting an absent key there
(with a Source Ledger row for it) is how a misspelling used to read as a success.

`expect` guards the new verbs too, and a re-applied entry is never mistaken for drift: a field
that already holds what this entry sets, or is already absent because this entry cleared it, is
its own success. A **strike** re-writes its ledger row on every run, so the withdrawal stays
disclosed rather than becoming an untraceable absence; it can do that safely because every field
it clears was found IN the ledger and therefore has a property row of its own. A hand-named
`unset` writes its row on the run that performs the withdrawal and none afterwards, since a
`repair` row for a key that is on no schema and on no property is a fabrication, not an audit
trail.

Outcomes print on every run, `--quiet` included, and land in `work/repairs_report.json`.

## Disclosure, not laundering

Each applied field writes its own Source Ledger row: `record_type=repair`, `verified` the
`verified_by`, and the `why` in `conflict_note` alongside the previous value. `source_file` and
`source_locator` are the repair's own citation when it gives one, and otherwise `repairs.json`
plus the repair id. `grep ,repair, source_ledger.csv` lists every manual touch either way -
citing evidence adds provenance, it never removes the disclosure that a human made the change.
A CLEARED field writes a row too: its `value` is the sentinel a reader sees for the now-absent
field, and the note states that the key is absent rather than holding that sentinel. The
invariant that keeps those rows honest is that **a repair row's field already has its own
`record_type=property` row** - so a clear only writes one when the property really carried the
key (or, for a strike, when the ledger itself supplied the field), and an `unset` naming a key
that is not there writes nothing at all and is reported `STALE` instead.

Repairs run BEFORE the pre-build gates, so `validate-data`, `arithmetic`, `coverage` and
`trace-coverage` judge the repaired dataset exactly as they judge anything else, and the freeze
covers what actually ships. A repair cannot be used to slip a value past a gate.

## Which mechanism to use

| use | when |
|---|---|
| `overrides.json` | the SOURCE is wrong - a mis-transcribed cell, a value read off the wrong row. Applied at extraction, keyed to a source record. |
| `repairs.json` | the PROPERTY is wrong after merging - precedence picked badly, a gate struck a stated figure, a field is absent, the hero is not this building. Keyed to a property. |

If both would work, prefer `overrides.json`: fixing the source fixes every downstream
derivation. Reach for a repair when there is no single source record to blame.

**While you are iterating on gate findings, prefer the repair channel.** A repair is applied
after the merge, so a re-run can skip merge and enrichment entirely and you see the effect in
the time it takes to re-gate; an override is applied at extraction, so it forces the whole
pipeline and re-derives the cluster anchors on the way, which re-keys settled conflict decisions
and can open a fresh adjudication round for one changed value. On a findings loop that is the
difference between minutes and a full run per fix.

The exception is plain: a correction that has to change **clustering, unit selection or longlist
membership** cannot be a repair, because all three happen INSIDE merge. Which records describe
one building, which area unit the dataset speaks, and whether a property is in the set at all
are settled before a repair ever runs, so those go in `overrides.json` and cost the full
pipeline. A repair also cannot create or delete a property, which is the same boundary seen from
the other side.
