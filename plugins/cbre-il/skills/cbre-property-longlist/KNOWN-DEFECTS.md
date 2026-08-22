# Known defects: guard ergonomics and stage ordering

> **STATUS: ALL FIXED, 2026-08-17.** Every defect below shipped a fix and an eval; the analysis is
> kept because it is the evidence each eval exists to protect. See "What shipped" at the end. Two
> further defects from the same run (the `needs_raster` livelock and capture-symmetry's buried
> signal) were fixed in the same pass and are recorded there too.

Recorded 2026-08-16 from the TEDi Spain run (9 PDF brochures, 37 properties, 0 trackers).

None of the four below is specific to that corpus. Each is a property of the mechanism and will
recur on any run that reaches the same stage. They are grouped because they share one shape: **the
guards are right to fail closed, but they fail closed against exactly what the documentation tells
the orchestrator to write, or against a claim the pipeline makes without testing it.** The cost is
paid in full re-runs and re-dispatched sub-agents, not in wrong data, which is why none of them
shows up in a scorecard.

Ordered as they were ranked in the run report, so D5 to D8.

---

## D5. `expect` cannot express "this field is absent"

**Symptom.** Every guarded repair or override written against a field the pipeline struck is
reported `SUPERSEDED` and applies nothing. The whole batch fails at once, so the first attempt at
any correction round is wasted.

**Where.** `helpers/repairs.py:227` (`wrong = [k for k, v in exp.items() if not _same(...)]`) and
the same comparison in `helpers/merge.py:370`
(`if fld in ov["expect"] and str(cur) != str(ov["expect"][fld])`).

**Root cause.** Two vocabularies for one state. Every surface a human or sub-agent reads the current
value from renders an absent field as the sentinel `tbd`: the gate scorecard, `notes.md` under
"Unknowns", the Gaps Report, `sources.csv`, and the ledger row a plausibility strike writes
(`warehouseArea,tbd,(none),"stated as ... in a unit this dataset cannot express"`). `canonical.json`
stores `None`, or omits the key entirely. So `expect: {"warehouseArea": "tbd"}`, which is what those
surfaces dictate, compares `'tbd'` against `'None'` and supersedes. There is no way to discover the
correct value to write, because no readable surface prints `None`.

**Evidence.** 17 of 17 area repairs superseded on the first pass, all with
`` `expect` said warehouseArea=='tbd' but the property now holds warehouseArea==None ``. Rewriting
`"tbd"` to `null` in all 17 and re-running applied all 17 unchanged.

**Fix.** One shared predicate, used by both call sites. `gate_runner.py` already has two copies of
it (`_absent` at line 672, `_cov_filled` at line 162): promote one to `_common.is_absent(v)` and
compare through it, so `None`, `""`, `"tbd"`, `"tbc"`, `"—"`, `"-"`, `"??"` and `"n/a"` are all one
equivalence class. Only compare literally when both sides are present. `repairs.py` already carries
the precedent for this reasoning in its own already-applied exemption at lines 219 to 226.

**Eval `repair_expect_sentinel_test`.** Given a property holding `warehouseArea: None`:
a repair with `expect: {"warehouseArea": "tbd"}` APPLIES; one with `expect: {"warehouseArea": null}`
APPLIES; one with `expect: {"warehouseArea": 21759}` still SUPERSEDES. Same three cases for an
override against a record whose field is missing entirely. The third assertion is the one that
matters: the fix must not turn the guard off.

---

## D6. A shared match key defeats the documented `{key, id}` pair

**Symptom.** A repair carrying both identifiers, as the reference file instructs, resolves
`AMBIGUOUS` and applies nothing, even though its `id` identifies exactly one property.

**Where.** `helpers/repairs.py:181` `_resolve`. `hits = by_key or by_id`, then
`if len(hits) > 1: return None, "ambiguous"`. A key matching several properties short-circuits
before the unique `id` is ever consulted.

**Root cause.** The match key is `city|developer|park`, and none of those three distinguishes two
units in one park or two plots on one estate. Multi-property parks are the normal case in a
longlist, not the exception. `reference/per-property.md` says "Give both", and `notes.md` prints the
key without warning that it is shared, so following the documentation is what triggers the failure.

**Evidence.** Two sub-agents hit this independently in one run and both diagnosed it correctly
before writing: ids 5, 6 and 7 all key to `marchamalo|tbd|pol ind ciudad del transporte`, and ids 22
and 23 both to `illescas|tbd|pol ind urban ii`. Both agents omitted `key` and gave `id` alone, and
recorded the reason in `why`. A third batch written to the documented shape did supersede on ids 5,
6 and 7 and had to be rewritten.

**Fix.** Two parts.
1. In `_resolve`, when both are given: if `by_id` is unique and `by_id[0] in by_key`, resolve to it.
   Reserve `AMBIGUOUS` for the case it exists for, which is `key` and `id` pointing at genuinely
   different properties. A key that is merely non-unique but contains the id is a confirmation, not
   a conflict.
2. In the per-property projection, mark a shared key where it is printed:
   `Repair key: marchamalo|tbd|pol ind ciudad del transporte (SHARED with ids 5, 7 - pass id alone)`.
   The surface that hands you the key should tell you when it will not resolve.

**Eval `repair_shared_key_test`.** A fixture with three properties in one park:
a repair with `{key: <shared>, id: 6}` APPLIES to id 6 only; `{id: 6}` alone APPLIES;
`{key: <shared>}` alone still returns AMBIGUOUS; `{key: <park A key>, id: <a property in park B>}`
still returns AMBIGUOUS. Plus a projection assertion: every `notes.md` whose key matches more than
one property carries the SHARED warning.

---

## D7. The `[pending]` lines assert non-existence without testing it

**Symptom.** After a manifest rebuild, the guard lists decks whose interpretation outputs are
present on disk as `pending: its interpretation output does not exist yet`. Followed literally, as
SKILL.md instructs, that is one redundant reader dispatch per deck.

**Where.** `helpers/run.py:2392` to `2395`. The loop appends the string
`f"deck '...' ({mode}) pending: its interpretation output does not exist yet: {_o}"` for every entry
in `interpret_decks`, with no `_o.exists()` check anywhere in it.

**Root cause.** The diagnosis block was written to expose the guard's predicate, but it restates a
predicate rather than evaluating one. It is a template, not a test, so it is only ever accidentally
true. This is aggravated by SKILL.md giving it maximum authority: "satisfy THESE lines; never guess
at what the guard reads", and "the guard's EXACT pending predicates this pass - it reads nothing
else". The one diagnostic the orchestrator is told to trust unconditionally is the one that does not
check.

**Evidence.** A pass triggered by a single `needs_raster` escalation printed nine `[pending]` lines.
Eight named files that existed, with mtimes hours old and correct content;
`python -c "os.path.exists(...)"` over the manifest's own `output` paths returned True for eight and
False for one. Only the raster deck was genuinely pending. I dispatched one reader instead of nine
by ignoring the instruction, which is not a habit the skill should be teaching.

**Fix.** Evaluate the predicate and print the outcome:

```python
for _d in interpret_decks:
    _o = _deck_output_path(work, _d)
    _state = "MISSING" if not _o.exists() else ("empty" if _o.stat().st_size == 0 else "present")
    _diag.append(f"deck '{_d.get('source_file')}' ({_d.get('mode')}) pending: output {_state}: {_o}")
```

If any line reports `present`, the deck is in `interpret_decks` for some reason other than a missing
output, so print that reason (mode change, `needs_raster` escalation, stamp invalidated) instead of
a false one.

**Open question that belongs with this fix.** Why did eight decks with current outputs re-enter
`interpret_decks` at all? A one-deck raster escalation should invalidate one deck. Either the
`force_raster` path rebuilds the whole manifest and bypasses the
`_vision_supersedes(...) or has_vision` guard at `run.py:1561` more widely than the `must_raster`
flag intends, or the manifest rebuild resets the per-region `has_vision` computation. Worth pinning
before the diagnosis text is fixed, because a truthful diagnosis would have said "output present"
nine times and left the real cause unexplained.

**Eval `pending_diagnosis_truth_test`.** Run a fixture to exit 3 with one deck's output present and
one absent. Assert no `[pending]` line says "does not exist yet" about a path that exists, and that
`work/pending_diagnosis.json` records the observed state per deck rather than a fixed string.

---

## D8. Two ordering and concurrency faults in the correction loop

Separate causes, same effect: correcting one thing costs several round-trips it should not.

### D8a. Repairs are applied after the data-translation bake

**Symptom.** Any prose or free-text value a repair introduces re-fires the translation gate, so the
run exits 12 and needs a fresh isolated translation sub-agent, once per repair round.

**Where.** Stage ordering in `run.py`: the exit-12 eligibility scan and the translation bake run
inside enrichment, and `repairs.run()` executes after it, immediately before the pre-build gates
(as `reference/per-property.md` documents: "Repairs run BEFORE the pre-build gates").

**Root cause.** The translation cache is keyed on source text, and a repair-set value has never been
through the scan, so it is eligible and uncached by construction. The repair loop is therefore
guaranteed to be at least two passes long whenever it touches a translatable field, and the
translation gate blocks in between.

**Evidence.** Three exit-12 rounds in one run, for two values that needed no translation at all:
`"Turnkey"` (3 items, 1 unique) and `"Upcoming construction"` (1 item). Each round cost a spine
re-run plus a sub-agent dispatch, and both returned the string unchanged. A fourth would have fired
for the 20 `status: "For rent"` repairs had they not reused a cached string.

**Fix.** Move `repairs.run()` ahead of the translation eligibility scan, so a repair-set value is
scanned with everything else in one pass. Repairs already own no upstream dependency that requires
them to be late: they read `canonical.json` and write it back. Failing that, exempt a value whose
provenance is `repair` and whose text is already in the target language, since `why` and
`verified_by` make the human attribution explicit and `is_translatable_value` already refuses
identifiers and codes.

**Eval `repair_translate_order_test`.** A fixture at `output.language: English` with a repair setting
`status: "Turnkey"`: the spine reaches the pre-build gates in ONE pass with no exit 12. Then the same
fixture at `output.language: German` with a repair setting a Spanish description: exactly one exit 12
fires, and the request contains the repair-set text. The second assertion stops the fix from
suppressing translation that is genuinely needed.

### D8b. `placeholder_audit_ack.json` is a whole-file write with independent authors

**Symptom.** Two sub-agents fixing two different blocked gates in parallel silently overwrite each
other's acknowledgement, and the lost gate blocks again on the next pass with no trace of why.

**Where.** The file is read at `gate_runner.py:1024` (images) and `1420` (arithmetic), and also at
`run.py:2925` and `merge.py:2137`. It is a single JSON object whose top-level keys
(`nonphoto_hero_ok`, `duplicate_photos_ok`, `arithmetic_ok`) belong to different gates and different
authors, and there is no writer helper, so every author hand-writes the whole object.

**Root cause.** Shared mutable state with no merge discipline, in a workflow the skill explicitly
tells you to parallelise ("dispatch the gate batch concurrently"). Note that `overrides.json` and
`repairs.json` are both append-only lists, and their docs say the list shape was chosen so entries
stay diffable and additive. The ack file did not get the same treatment.

**Evidence.** The arithmetic agent created the file with `arithmetic_ok: ["25"]`. The image agent,
running concurrently, wrote the file with its own two keys and no `arithmetic_ok`. The arithmetic
gate blocked again on the next pass; its own ack had been correct for several minutes. The image
agent had been told to merge and believed it had, because it read the file before the other agent
created it.

**Fix.** Either shape works; the CLI is better because it also captures the `why` and
`verified_by` the file currently records only by convention:

```
python helpers/gate_runner.py ack add --work <work> --key arithmetic_ok --value 25 \
    --why "..." --verified-by you@cbre.com
```

with an atomic read, merge and write. Then change the gates' block messages to name that command
instead of describing the JSON, and have `run.py` print any key it read at startup so a lost
acknowledgement is visible in the same pass rather than the next one.

**Eval `ack_concurrent_write_test`.** Two writers, interleaved: A reads, B reads, A writes
`nonphoto_hero_ok`, B writes `arithmetic_ok`. Assert both keys survive. Under the current
whole-file shape this test fails, which is the point. Add a second assertion that both gates read
the merged file and pass.

---

## Suggested order

D5 and D6 first: they are small, local, and each currently costs a guaranteed wasted pass on every
run that corrects anything. D8b next, because it loses work silently, which is worse than losing it
loudly. D8a is a stage reorder and wants care. D7 is two changes, and the open question above should
be answered before the text is rewritten, or the truthful message will simply be confusing instead
of wrong.

---

# What shipped (2026-08-17)

All six fixed in one pass, each with an eval. Full suite green before and after.

| # | Fix | Where | Eval |
|---|---|---|---|
| D1 | The `needs_raster` escalation is PERSISTED to `work/vision/force_raster.json` (it used to be derived from stubs the same loop deleted, so it survived zero passes), is retired the moment that deck's records exist, and an escalated deck is no longer offered to photo-match - the reader has already read it, so `unrelated` was the only possible verdict and it spent the escalation on the wrong branch. Those two together were the livelock. | `run.py` `_load_force_raster` / `_save_force_raster` / `photo_match_candidates` / `keep_vision_targets` | `raster_escalation_test` |
| D4 | capture-symmetry now weighs each finding by the RECORDS it affects and by how established the field is elsewhere (`weight = min(affected, present)`), always treats a coverage-core field as a SIGNAL, prints SIGNAL findings first and uncapped, and writes the full ranked list to `work/capture_symmetry.json`. Ranking on affected records alone floats the RAREST field to the top - the eval caught that during implementation. | `gate_runner.cmd_capture_symmetry`, `CAPTURE_CORE_FIELDS`, `SIGNAL_MIN_RECORDS`, `SIGNAL_MIN_PRESENT` | `capture_symmetry_signal_test` |
| D5 | `expect` treats absence as one bucket, so `{"f": "tbd"}` matches a struck field holding `None`. Deliberately NARROWER than `normalize.looks_unknown` (a market phrase such as "a consultar" is still drift), and widened at the caller as that function's docstring instructs. `_same` is untouched. | `repairs._expect_same`, `merge._ov_expect_same` | `expect_sentinel_test` |
| D6 | `key` and `id` are INTERSECTED rather than compared first-hit, so an id disambiguates a key several properties share. An id outside the key's matches is still AMBIGUOUS. | `repairs._resolve` | `repair_shared_key_test` |
| D7 | A durable `work/vision/deck_outputs.json` remembers each deck's output, so a finished deck still supersedes once the manifest shrinks past it, and an assigned path is stable across manifests of different composition. The exit-3 diagnosis now states the predicate it actually evaluated. | `run.py` `load_deck_outputs` / `save_deck_outputs` / `assign_deck_outputs(known=)` / `_vision_supersedes` | `deck_output_memory_test` |
| D8a | Repairs moved ABOVE the translation stage, so one pass sees both. The projection stays after it, so the view shows shipped prose. | `run.py` stage order | `repair_before_translate_test` |
| D8b | `gate_runner.py ack --work <w> --add key=v1,v2` merges atomically instead of authoring the file whole; a corrupt ack file blocks rather than being overwritten. Documented in SKILL.md as the only sanctioned way to write it. | `gate_runner.cmd_ack` | `ack_merge_test` |

Two bugs were found BY the new evals during implementation, which is the argument for writing them:
`save_deck_outputs`/`_save_force_raster` used a module-level `_common` alias that does not exist in
`run.py` (imports are function-local there), and the failure was swallowed by the sidecar
`except Exception: pass`; and capture-symmetry's first ranking metric promoted the rarest fields.

---

# Second batch: path coupling and non-idempotent disclosure (2026-08-20)

Found while restructuring a live project into the three-folder layout (`1. Input` / `2. Work Files`
/ `3. Output`). Both are pure MECHANISM defects, both cost DISCLOSURE - lines that belong in the
honesty document silently stopped being written - and neither shows up in any scorecard, which is
exactly why they lasted. Both are fixed, each with an eval.

| # | Defect | Why it mattered | Fix | Eval |
|---|---|---|---|---|
| D9 | `_qa_run_key` hashed `Path(work).resolve()` alongside the intake `input_hash`, so the QA window was **path-coupled**. Renaming or moving the project folder changed the key, `_qa_load` treated a byte-identical `qa_state.json` as "a different corpus", wiped `rounds`, `qa_carried()` returned `[]` and `qa_round_number()` fell to 0. | Observed live: the very next `deliver.py` shipped a Gaps Report with **no "Known limitations" section at all** - 51 reviewed-and-accepted limitations gone from the one document whose job is honesty - and PASS-WITH-REMEDIATION was disabled, all because a folder was renamed. `final_gate` still printed ALL-PASS, because the delivered report matched the (now empty) recorded pass. | The key hashes the CORPUS identity only (`corpus\|<input_hash>`). The work dir's path added nothing - `qa_state.json` lives IN the work dir, so it is per-work-dir by construction. `_qa_run_key_legacy` is accepted on read in an UNMOVED dir and re-keyed in place, so the upgrade itself never wipes a window; a genuinely different `input_hash` still opens a fresh one. | `project_layout_test` (D2) |
| D10 | `harmonise_region_levels` returned early (`if not changed: return 0`) whenever every property already carried its bound NUTS-3 name - i.e. on the SECOND and every later `--regions` pass - while the regions layer REPLACES its gap bucket each run. | The "region labels were stated at more than one administrative level ... each property's region is now the NUTS-3 area its own coordinates fall inside" line dropped out of the delivered Gaps Report on every re-run, even though `meta.regionHarmonised` still recorded the harmonisation. The deliverable stopped saying the shipped region label is DERIVED rather than source-stated. A disclosure that disappears when you re-run is worse than no disclosure. | The line is RESTATED from `meta.regionHarmonised`, and only while it is still true (every recorded property still carries the bound name it records). The return value stays honest - `0`, because nothing was rewritten this pass. | `region_harmony_test` |

The shape both share: a guard or a bucket that is correct on the FIRST pass and quietly lossy on
the second. Re-running is the skill's normal mode (resume is the default, every shell-cap kill is a
re-run), so "correct only on a cold run" is not correct.
