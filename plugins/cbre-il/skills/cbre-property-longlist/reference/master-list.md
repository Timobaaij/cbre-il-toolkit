# The master list: the user decides what the run builds (exit 17)

One sheet, one row per candidate option, Include? Yes or No on every row, built before a single
brochure is read. It is the only point in the run where scope is decided, and it is decided by
the person who owns the deliverable rather than by the run.

## Why it exists

On the Kapdaa run the broker learned what the run had decided to build by reading the FINISHED
dashboard. Nothing before that point had asked. The tracker contributed one row per line whether
or not the line was a live option; a brochure that happened to be in the folder became a card;
an option named only in the prose of an email reached the deliverable only if some later agent
happened to write a record for it. The one question that does put scope to a human - the
exit-13 source-authority question - is asked AFTER matching and merging, which is two problems
at once:

- every brochure has already been read by its own reader agent, so the expensive work has been
  paid for on options nobody wanted;
- the question is phrased in terms of the opinion the run has already formed ("these 14 are only
  in the brochures"), so the broker is editing a conclusion rather than setting a scope.

The master list replaces both. An answered sheet IS the authority, and the source-authority
question is then not asked at all.

## Where it sits, and why not somewhere cheaper

| Placement | For | Against |
|---|---|---|
| Before anything is read | Cheapest | The run knows filenames and nothing else; the sheet would be a list of filenames, which is not a decision a broker can take |
| **After the tracker rows and the email bodies, before the deck readers** | Every route has produced its candidates; the expensive step (one reader agent per deck, vision on the raster ones) runs only on Yes rows; the user's duplicate groups pre-answer exit 10 for the pairs they cover | Option identity is not final until match and merge, so the sheet carries pre-match duplicates and needs the postcode sweep plus the user's eye |
| After match and merge | A clean option list | Every brochure has already been read, and this is exactly where the source-authority question already sits - the placement that failed on Kapdaa |

Emails have to be read before the sheet, because an email-only option exists only in the prose.
That read is cheap relative to a deck.

**Every message gets a deterministic row, and the sub-agent refines it.** The spine enumerates one
row per .msg/.eml on disk (including inside a zip, which intake unpacks), named by its subject,
using the parse `intake` already performed to harvest that email's attachments. Splitting a body
that names three buildings into three options is judgement, and `prompts/master-list.md` still
asks the model for it - but the presence of the message on the scope sheet is not allowed to
depend on an optional agentic step. Emails are the one input class that can hold an option nobody
else listed, and an option that never reaches the sheet is not struck off by anyone: it simply is
not built, and nothing says so. Where the model (or an earlier agent) has already written
per-option records for a message, those finer rows win and the coarse message row is not added.

An attachment that arrived stapled to an email needs nothing special here. `intake` saves it
beside its message before classification, so it is discovered, clustered and enumerated as a
Brochure row exactly like a deck dropped in the folder by hand - which is why its **Brochure?**
cell is a flat `Yes` and not red.

## The four steps

1. **The spine enumerates** (`helpers/master_list.py`). It writes
   `work/master_candidates_auto.json`: one row per tracker record, one per email record, one per
   email MESSAGE on disk that no record row already covers, one per
   brochure CLUSTER (the unit a reader agent is dispatched on), with name, postcode and size for
   a deck row taken from the cluster label plus the deck's FIRST PAGE only - enough for a human
   to recognise a scheme, and explicitly not data. It then runs a blunt duplicate sweep on postal
   code alone. Then it STOPS with **exit 17**.
2. **The model judges** (`prompts/master-list.md`, rendered into `work/prompts/`). It adds the
   rows that exist only in email prose and adjudicates the duplicate groups, into
   `work/master_candidates.json`. It never deletes, re-words or re-keys a spine row.
3. **The workbook** (`helpers/master_list_build.py --work <work>`) merges the two, paints the
   Brochure? column, and writes `<work>/Master List.xlsx` plus `master_list_manifest.json`.
   **The user answers it.** Yes or No on every row, free text in "Your Run notes for the AI".
4. **The read-back** (`helpers/master_list_read.py --work <work>`) writes
   `work/master_list.json` and the spine resumes.

## What the workbook looks like

- **Master list** tab. Rank, Include?, Your Run notes for the AI, then the facts: property,
  source type, source, duplicate group and status, Brochure? and its detail, address, postcode,
  town, size from/to and unit, rent, availability, landlord/developer, notes. Include? and Run
  notes are the two pale-yellow columns; a row in a duplicate group is amber.
- **Include? is Yes or No, with no third value.** A deferred answer has to be resolved before the
  run can start in any case, so carrying "maybe" in the sheet would only move the same decision
  to a point where a log reader takes it instead of the person who owns the deliverable. The
  read-back **refuses with exit 2** on any row that is blank, deferred or unreadable, and names
  every one, so resolving them is one pass through the sheet.
- **Brochure? is painted red** wherever it is not a flat `Yes`, as real conditional formatting on
  that column and nothing else, keyed off the cell's own value so it survives the user sorting,
  filtering or re-ranking the sheet. A row with no machine-readable document ships a card whose
  specification comes from source text with no page citation behind it, which is what the
  evidence gates refuse - so the flag belongs on the sheet, before the decision, not in the Gaps
  Report afterwards.
- **Row ID is hidden and load-bearing.** Row position is not an identity: the user may sort,
  filter and re-rank freely. Every answer is keyed back on the Row ID, and a rebuild (a second
  email export, three more brochures) carries every existing Include? and Run note forward by
  that id. `--fresh` discards them deliberately.
- **Duplicate check** tab. Every flagged group, its members side by side, read-only. The decision
  still goes in Include? on the master list tab, so there is exactly one place a decision lives.
  Groups are the model's adjudication first, then the postcode sweep behind it. The sweep is
  crude on purpose: it over-groups and says so, because a group the user glances at and dismisses
  costs a second, and a missed duplicate puts the same building on the client's dashboard twice.

## What the answer binds

`work/master_list.json` is read in four places and nowhere else:

| Consumer | Effect |
|---|---|
| Deck reader dispatch (`run.py`, extract) | A cluster whose rows are ALL No is never prepped, rendered or dispatched. This is the economic argument for the whole stage |
| Source authority (`run.py`, merge path) | A USER-answered sheet means the authority is the master list: the included options are kept, and the exit-13 source-authority question is not asked |
| Match adjudication (`run.py`, before `grey_pairs`) | Each user duplicate group becomes `same` verdicts in `work/match_decisions.json`, keyed with `match.pair_id`, so exit 10 asks only about pairs the user did not group |
| Gaps Report (`deliver.py`) | Every excluded option is named under "Options excluded by the master list", with its source and any note the user wrote |

Plus `merge.py --master-list`, which applies the same cluster filter inside the merge itself, so
the two clustering calls cannot disagree about which options exist.

## Resume, and a changed inputs set

`master_candidates_auto.json` carries an `input_hash`: a digest of the ROW IDENTITY SET, not of
the row values. An answered `master_list.json` records the hash it answered.

- Same hash: the sheet is honoured on every later pass, silently.
- Different hash (a new deck, a new email, a removed file): exit 17 re-opens, the builder carries
  every still-matching answer forward by Row ID, and the user answers only what is new.

The hash deliberately ignores values. Re-reading the same tracker can produce a cosmetically
different size string, and re-asking a broker forty questions because a number gained a decimal
place is how a gate gets disabled by the people it protects.

## Scope owned by a wrapper skill (`master_list.mode: external`)

A caller that has already put its OWN scope sheet to the same person - `kato-longlist`, at its
step 2.5, which then generates this skill's `project.yaml` and inputs folder from the rows that
survived - sets `master_list: {mode: external, confirmed_by: "<text>"}` in `project.yaml`. Exit 17
then never fires on that run.

It is a DECLINED STOP, not an answer. No `work/master_list.json` is written, so none of the four
consumers above can read one: the source authority is not derived (exit 13 asks its question
exactly as it did before this stage existed), nothing is seeded into `match_decisions.json`, and
every cluster is prepped and read. The Gaps Report carries one line naming where scope was settled
and the `confirmed_by` text, and no master-list section. Everything else about the run is
byte-identical to the pre-master-list spine. Absent, misspelt or unparseable means interactive -
the full contract is in `reference/config.md`.

## Headless

`work/clarify.SKIP_ALL` or `clarify.assume_defaults: true` skips the stop and includes
everything. The file written carries `skipped: true`, which means it is NOT read as a scope
decision: the source-authority question is still asked on the next interactive pass, and the Gaps
Report prints "Scope was not put to you (the run decided)" naming the option count. Interactive
is fixed by policy - the ask-mode question was removed from the setup form - so the stop is the
default and this is the deliberate escape hatch, not a mode.
