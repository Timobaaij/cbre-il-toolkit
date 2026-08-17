# The per-property view and the repair path

Two artefacts, written between enrichment and the pre-build gates. One is how you SEE a single
option; the other is how you CORRECT it. They are deliberately not the same file.

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
    property.json     the record, readable, base64 blobs replaced by media filenames
    media/            hero.jpg, gallery-02.jpg ..., plan.jpg - real files you can open
    sources.csv       this property's Source Ledger rows and nothing else
    notes.md          its unknowns, its conflicts, its repairs, and its repair key
  index.json
```

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
- **`set`** takes any canonical field, INCLUDING one this property does not yet carry (filling
  an absent `region` is a real case). Denied: `id`, `photo`, `gallery`, `plan`, `preBaked`
  (structural or media-owned), and `areaUnit`/`rentUnit` - those relabel every figure at once,
  which is the 10.76x error class `overrides.json` denies for the same reason.
- **`media`** takes `hero` or `plan`, a path relative to the work dir. The image is compressed
  through `images.py` exactly like a harvested one, so a repaired hero is indistinguishable in
  weight and encoding. Setting `hero` moves `gallery[0]` with it, or the carousel would open on
  the photo the repair replaced.
- **`why`** and **`verified_by`** are REQUIRED and non-empty. Both ship in the Source Ledger.
- A repair can never create or delete a property.

## Every guard fails closed

A repair landing on the wrong card is worse than one that did not land, so an entry that cannot
be resolved with certainty applies NOTHING and is reported:

| outcome | when |
|---|---|
| `STALE` | the key matched no property |
| `AMBIGUOUS` | the key matched several and no `id` picks one out of them, or the `id` names a property the key does not match |
| `SUPERSEDED` | `expect` no longer matches - the dataset moved under this entry |
| `INVALID` | a denied field, a field name in no schema and on no record, a blank value, a missing `why`/`verified_by`, or a media file that is not there |

Outcomes print on every run, `--quiet` included, and land in `work/repairs_report.json`.

## Disclosure, not laundering

Each applied field writes its own Source Ledger row: `record_type=repair`, `source_file`
`repairs.json`, `source_locator` the repair id, `verified` the `verified_by`, and the `why` in
`conflict_note` alongside the previous value. `grep ,repair, source_ledger.csv` lists every
manual touch.

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
