# The committees: roles, briefs, hand-offs

Nine sub-agent roles in five phases, plus the orchestrator, who is the chair.
Each sub-agent has a fresh context, so it judges the work on the files, not on
the conversation that produced them. Run roles in parallel where marked, **at
most three at a time**.

```
Phase 1  Data steward ──────────────► report/units.json, work/data-notes.md
Phase 2  Analyst A ┐
         Analyst B ├─ parallel ─────► work/analysis/<A|B|C>.md (+ their code)
         Analyst C ┘
         (orchestrator as chair) ───► work/brief.md, work/ledger.md
Phase 3  Storyline author ┐ parallel ► report/story.js
         Dashboard author ┘         ► report/dash.js
         (orchestrator) assemble.py ► <Client>_Portfolio.html
Phase 4  (orchestrator) page_text.js ► qa/page-text.txt
         Visual QA    ┐              ► qa/visual.md (+ screenshots)
         Numbers QA   ├─ parallel, ► qa/numbers.md
         Storyline QA ┘  ONE pass    ► qa/storyline.md
Phase 5  Authors fix EVERY finding ─► qa/fixes-<story|dash>.md
         (orchestrator) re-assemble + smoke check ► qa/smoke.md
         (orchestrator) deliver + summary.   No second QA round.
```

**No sub-agents available?** Play each role yourself, in order, one at a time.
Write that role's output file before starting the next role. Re-read the inputs
from disk at the start of each role. Never QA your own build from memory: open the
built file and check it as if a stranger made it.

**Every sub-agent prompt starts with** the run folder path, the skill folder path,
the files to read, the exact deliverable, and this line: *"Write one short line of
progress text between tool calls; never run several tool calls back to back in
silence. At most three tool calls per message."*

---

## The ledger: how every number stays traceable

`work/ledger.md` opens with a **Definitions** block that every role uses word
for word. At least: *running* (`leaseState = running`: started, recorded end not
yet reached), *not started*, *recorded expiry passed*, *undated*, *third-party
leased* (leased, landlord not intra-group), *in MEES scope* (uk-rules.md §1),
and any window the report uses ("by end-2028", "next 24 months from the as-at
date"). Then one table. Every figure that appears in any copy gets a row:

| id | claim (as it will read) | value | printed as | computation | basis / denominator | fields | status |
|---|---|---|---|---|---|---|---|
| L07 | five landlords hold 61% of leased floorspace | 0.6100 (4,210,000 / 6,902,000) | 61% | `analysis/a.py::landlord_top5` | 38 third-party leased units; freeholds excluded | `landlord`, `owned`, `size` (EverGreen: Landlord, Status, Size (sq ft)) | fact |

`fields` names `units.json` fields, with the raw EverGreen columns in brackets.
`status` is one of: `fact` (computed from the export), `as recorded, dates to
verify` (rests on dates the mapper flagged as templated), `in force` (law), or
`target, not yet law` (anything uk-rules.md calls a target, proposal, or
"confirmed in the interim response").

**Default windows** (use them unless the brief defines others in Definitions):
*due within N years* = a running lease whose recorded expiry **or** first future
break falls on or before the as-at date + N years; *before 2031* = recorded
expiry or first future break before 1 Jan 2031; *passed* breaks and reviews are
reported as "recorded date passed", never as events still to come.

**Conventions.** Analysts' candidate ids are `A01`, `B01`, `C01`. The chair (you,
the orchestrator) renumbers kept rows `L01…`. Add a `printed as` column holding the exact string
the reader sees ("61%", "4.21m sq ft"). Rounding: percentages to whole numbers
("<1%" below one), floorspace of 1m sq ft and above as m sq ft to 2 dp, below 1m
as exact sq ft with separators in prose ("212,500 sq ft") and m to 2 dp only on
chart labels, years to 1 dp, £ psf to 2 dp, km and months to whole numbers,
acres to 1 dp (full precision always in `value`). Counts one to nine are words in
headlines and prose ("nine leases") and digits in tables, chart labels and
denominators ("9 of 14").
*Windows:* a window about **urgency** is rolling from the as-at date ("within 24
months of 15 Sep 2026"). A window about a **year or a rule** is calendar-bounded
("by end-2028", "before 2031"). Name both in Definitions. Note that the
dashboard's stock event bands are rolling (≤2 years, 2–5 years from the as-at date).
The chair also writes `work/ledger.json` (the same rows, machine-readable) so
authors and QA can load values rather than retype them. **After the brief**, rows
are added only in Phase 5, by the orchestrator. Each new row is marked `added in
fixes`, with its computation. If one changes a headline, update the brief and
tell the storyline author in the same message as its fixes.

Analysts write candidate rows in their own files. The chair recomputes each one it
keeps and merges them into `ledger.md`. Authors may only print figures that are in
the ledger, or that are computed at run time from `units.json` exactly as a
ledger row describes. Numbers QA verifies the ledger against the **raw export**
and the page against the ledger.

---

## Phase 1: Data steward

Read `reference/data-evergreen.md` and `reference/uk-rules.md` §1, §2 and §5.
Profile the export, write `work/mapping.json`, build `report/units.json`, and
write `work/data-notes.md` (every judgement call, anomaly and fill rate, and
every WARNING the mapper printed with your decision on it). Anything in the
notes that may reach the client goes under a **Client wording** heading, in plain
English. Analyst-only detail stays under **Analyst notes**. Also write
`report/meta.json`:
`{"client","sector","exportDate","asAt","title","description","context"}`. Keep
`context` to about 60 characters ("Client · UK logistics"): it is the app-bar line.
Deliver a ten-line summary: unit count, total sq ft, owned/leased split, dated
leases, the three biggest data gaps, and anything odd. Report **data quality,
not conclusions**: no precomputed "key facts", shares or rankings. The analysts
must find those independently.

## Phase 2: Insight committee

Three analysts explore **independently**. Each reads `reference/insight-playbook.md`,
`reference/uk-rules.md`, `work/data-notes.md`, and computes from `report/units.json`
with their own code (keep it in `work/analysis/`). Each returns 5–8 candidate
findings in `work/analysis/<letter>.md`. For each finding: the claim, why it
matters to this occupier, the action, the ledger rows, and a **visual idea**,
which is the best possible form for this point, not the nearest library chart.
Analysts deliberately do **not** read the component catalogues: the idea should
come from the finding. The chair (you) maps ideas to library parts or `NEW:` builds.

- **Analyst A: exposure and time.** Lenses: time, control. Lease events by year
  and floorspace, cliffs, WAULT and what it hides, lapsed and undated leases,
  landlord concentration (leased only), negotiations that should be bundled.
- **Analyst B: cost, capability and shape.** Lenses: shape, cost, capability.
  Clusters and concentration, hard-to-replace sites, rent against deal year and
  reversion arithmetic, spec strengths and weaknesses, owned freeholds as capital.
- **Analyst C: compliance, confidence and the contrarian.** Lenses: compliance/ESG,
  data confidence. MEES scope and exposure, EPC and BREEAM coverage, what the data
  cannot answer and what that costs. **Mandate:** find what A and B would miss,
  and attack the obvious story. Any claim a data gap could explain, say so.

## Phase 2b: Chair (you, the orchestrator)

There is no chair sub-agent: you do this yourself, so the brief, the data fixes
and the assembly stay in one head. Treat the analysts' files as claims to test,
not facts. Read the three analysis files, `work/data-notes.md`, the playbook,
uk-rules.md, `reference/storyline-craft.md`, `reference/dashboard-craft.md`, and
the component catalogues in `reference/storyline-engine.md` (charts and kit) and
`reference/dashboard-engine.md` (stock panels, config). You need them to name
library parts and their props, and to know what each one cannot do. Then:
1. **Recompute** every figure you keep (your own code in `work/analysis/chair.py`,
   from `units.json`), and drop or correct anything that does not reproduce.
2. **Rank** candidates by the five tests in the playbook. Reject description,
   extrapolation and anything regulatory beyond uk-rules.md.
3. **Choose the spine**: one sentence that is the whole argument.
4. Write `work/brief.md`:
   - **Spine** (one sentence) and **voice notes** for this client.
   - **Storyline plan**: 8–12 scenes. For each: id, ground mode (alternate
     dark/light with purpose), headline draft (a sentence with a number and a
     consequence), evidence points (ledger ids), visual, which is either
     `library: <component>` with the props it needs, or `NEW: <what it is, what it
     encodes, how it moves>`, plus pinned or not. The opening states the spine.
     The close hands the reader to the dashboard.
   - **Dashboard plan**: the title band; exactly **five findings** (`h` headline,
     `b` body with bolded figures, `a` action), each citing ledger ids; which
     default panels to keep, reorder, replace or drop, and why; any new panels
     (what, why, data); metrics; filters.
   - **Creativity check (required).** The plan contains at least one element
     designed for this client that is not in the library: a new scene, chart or
     panel. The alternative is a written reason why every library element is
     genuinely the best form for its point. Replacing library pieces is
     encouraged when something else serves the client better.
   - **Must-not-say**: claims considered and rejected, with the reason (so authors
     don't reintroduce them). Before finishing, check the brief's own draft
     headlines and finding copy against this list; a run once put a rejected
     count straight back into its own headline.
   - **Data corrections**: anything in `units.json` you found wrong (a flag, a
     label, a tenure). Fix it in `mapping.json` (`overrides`), re-run the mapper
     **before Phase 3**, and note it in data-notes. Corrections must never live
     only in the brief, or the drawer and table will still show the old value.
5. Write `work/ledger.md` and `work/ledger.json` (merged, recomputed).

## Phase 3: Authors (parallel)

**Storyline author.** Reads `work/brief.md`, `work/ledger.md`,
`reference/storyline-craft.md`, `reference/storyline-engine.md`,
`reference/design-system.md`, `examples/storyline-example.js` and `examples/new-scene-example.js`. Writes
`report/story.js`. Derives values from `Story.units` at run time, or uses ledger
values as constants with the ledger id in a comment. Builds every `NEW:` visual
from primitives, to the same finish as the library. Copy follows the craft guide:
plain English, occupier point of view, denominators, no jargon.

**Dashboard author.** Reads `work/brief.md`, `work/ledger.md`,
`reference/dashboard-craft.md`, `reference/dashboard-engine.md`,
`reference/design-system.md`, `examples/dashboard-example.js`. Writes
`report/dash.js`: config, the five findings, panel plan, and any new panels.

Both self-check before handing over. Build with
`python scripts/assemble.py <run>/report -o <run>/work/selfcheck-<story|dash>.html --stub-missing`,
since the other author's file may not exist yet and `--stub-missing` fills the gap.
The build syntax-checks both scripts when Node is present. Then look at the
result (see "Sharing the browser"). Check pinned scenes at 1536×730 **and**
1280×600, and every chart at 390×844. A build that throws, or shows
`NaN`/`undefined`, is not a hand-over.

### Sharing the browser

There is **one** Playwright MCP browser, and two roles driving it at once will
break each other's pages. So:
- **Phase 3:** the authors take turns, using a hand-off file. The storyline
  author holds the MCP browser first (new scenes carry the most visual risk). When
  it finishes a check it writes `qa/browser-free.txt` ("free since <time>") and
  closes the page. The dashboard author waits for that file, deletes it to take
  the browser, and writes it again when done. Neither author hands over work it
  hasn't seen rendered. If Node Playwright runs (`scripts/qa_run.cjs --dash`), the
  dashboard author may use it instead and skip the queue.
- **Phase 4:** Visual QA owns the MCP browser. Before spawning QA, the
  orchestrator runs `scripts/page_text.js` once (qa-visual.md §3) and saves
  `qa/page-text.txt`, so Numbers QA and Storyline QA can read every rendered word
  without a browser.
- **Phase 5 fixes:** every author checks its own fixes in the browser (same
  hand-off rule) before replying. There is no QA round after the fixes, so a fix
  nobody rendered ships as it is: fixes that were never rendered have caused new
  blocking defects before.
- Whoever holds the browser closes it (or navigates to `about:blank`) when done,
  and says so in their hand-over.
- If Node Playwright works, every role may use it in parallel. It has no shared state.

## Phase 4: QA (three in parallel, one pass, ruthless)

All three QA agents are told: *"You did not build this. Assume it is wrong until
you have proved otherwise. Report defects, not praise."* There is **one** QA
pass, so report everything in it: nothing gets a second look. Every finding
carries a severity: **P1 = blocking** (wrong, broken, misleading, or breaks a
non-negotiable) and **P2/P3 = advisory** (it makes the report better). All of
them are fixed in Phase 5, so give each one a concrete fix (the exact replacement
copy, value or CSS), never "consider improving".

**Numbers and claims QA.** Reads the ledger, `work/data-notes.md` and uk-rules.md.
1. Recomputes every ledger row **from the raw export** (`work/raw.json`, applying
   the data rules itself), so a mapping error cannot hide behind `units.json`.
2. Extracts every number and named claim from the built page (storyline and
   dashboard, including chart labels, tooltips, drawer notes and the appendix)
   and matches each to a ledger row or a run-time derivation. The source is
   `qa/page-text.txt` (every text run, aria-label, title and tooltip of both
   views, plus two open drawers). Search it case-sensitively for `NaN`,
   `undefined`, `null`, `Infinity`: "tenant" contains "nan".
   Severity: **P1** = a wrong figure, a figure with no ledger row, a derived number
   presented as recorded, a regulatory line stated more firmly than its status, or
   a claim on the must-not-say list. **P2** = the same fact reading differently in
   two places, a missing denominator, inconsistent rounding, or a banned phrase
   ("expired lease"). **P3** = wording or tone. Any open P1 fails the build.
3. Checks storyline against dashboard (the same fact must read the same), every
   denominator, every regulatory statement against uk-rules.md (status words), the
   as-at date, and the tone rules.
Returns `qa/numbers.md`: numbered defects (where, what it says, what it should
say, evidence).

**Visual QA.** Follows `reference/qa-visual.md` exactly. Uses the Playwright MCP
browser if present (`browser_navigate`, `browser_resize`, `browser_evaluate` with
`scripts/qa_audit.js`, `browser_take_screenshot`), otherwise Node Playwright via
`scripts/qa_run.cjs`, otherwise static checks, with the limitation stated. Returns
`qa/visual.md`: numbered defects with viewport, scene or panel, screenshot,
severity and fix.

**Storyline QA.** Judges the argument and the writing, not the figures (Numbers
QA owns those) and not the rendering (Visual QA owns that). Reads `work/brief.md`
(spine, voice notes, must-not-say), `reference/storyline-craft.md`,
`qa/page-text.txt` (every word of both views, in scene order), and
`report/story.js`. It does not take the MCP browser.
1. **The spine.** Write out the opening and every scene headline in order, alone,
   at the top of the report. Read as a list, they must make one argument that
   states the spine and ends on what the occupier should do next. Say where the
   thread breaks.
2. **One point per scene.** Each scene makes one point. Its headline is a sentence
   with a number and a consequence. The body supports that headline, and the
   chart shows what the headline says (compare the headline with the chart's
   labels and aria-label in the page text).
3. **Order and pacing.** Each scene earns its place and builds on the last; no
   point is made twice; the close hands the reader to the dashboard with a clear
   next step.
4. **Voice.** CBRE speaking to the occupier, in plain UK English: no jargon,
   hedging, filler or phrase the craft guide bans. Would a board member follow
   every sentence first time?
5. **One story across both views.** The dashboard's title band and five findings
   tell the same story as the storyline, in the same words for the same fact.
6. **Must-not-say.** No rejected claim has come back, in any wording.
Severity: **P1** = a headline or claim that misleads, contradicts the dashboard
or breaks the must-not-say list, a scene with no point, or a missing close.
**P2** = order or pacing, a headline without a consequence, jargon, or a chart
that shows something other than its headline. **P3** = wording. Every finding
gives the exact replacement copy. Returns `qa/storyline.md`.

**Write as you go.** All three QA agents append each defect to their report file
the moment they confirm it, so if the agent is stopped the findings survive.

## Phase 5: Fix everything, smoke check, deliver

**1. Sort the findings.** Read the three reports. Give each author every finding
on its file, blocking and advisory, with the QA report ids: the storyline author
gets storyline findings from all three reports, the dashboard author gets the
dashboard ones. Where two findings conflict, decide and say which in the message.
Before sending, copy `report/story.js` and `report/dash.js` to
`work/story.pre-fix.js` and `work/dash.pre-fix.js`.

**2. Data defects first.** Anything in `mapping.json`, `meta.json` or
`units.json` is yours: fix it, re-run the mapper, note it in
`work/data-notes.md`, update any ledger row that moved (marked `added in
fixes`), and tell the authors in the same message as their fixes.

**3. Authors fix every finding.** Resume the same agent if you can, since it keeps
its context. Every finding is implemented, blocking and advisory alike. An author
may decline one only if the fix would break a non-negotiable, contradict the
ledger, or contradict another finding it was told to follow, and must say why.
Each author checks its fixes rendered in the browser (see "Sharing the browser")
and writes `qa/fixes-<story|dash>.md`: one line per finding id, *fixed* (what
changed, where) or *declined* (why). If a resumed agent can't notify you when
it's done, poll for its fixes file.

**4. Re-assemble and smoke check.** This is not a QA round: nothing is
re-reviewed. It only catches a fix that broke the page.
- Node Playwright: `node <skill>/scripts/smoke.cjs <run>/<Client>_Portfolio.html`
  (both viewports, console included, about a minute; exit 0 = pass).
- Playwright MCP only: copy `scripts/smoke.js` into `<run>/qa/`, serve the run
  folder, open the file at 1440×900 and run the snippet at the top of
  `smoke.js` with `browser_evaluate`. Then `browser_resize` to 390×844, reload, and
  run it again. After each, read `browser_console_messages` for errors (ignore a
  favicon 404).
- Write the result to `qa/smoke.md`. If it fails, send only that failure to the
  author concerned, re-assemble, and run the smoke check again. After two failed
  repairs, restore that file from `work/<story|dash>.pre-fix.js`, re-assemble,
  confirm the smoke check passes, and list its unfixed findings in the summary.

**5. Deliver.** Copy the final HTML next to the export, named
`<Client>_Portfolio.html`. Write a short summary for the colleague:
- the spine and the five findings (one line each);
- the new, client-specific elements that were built;
- the biggest data gaps (the "questions we can answer for you");
- what QA checked, how many findings were fixed, any declined (and why), and the
  smoke check result. Nothing is hidden.
Keep `work/` and `qa/` in the run folder so the analysis can be audited.
