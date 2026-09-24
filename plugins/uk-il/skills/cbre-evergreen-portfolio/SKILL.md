---
name: cbre-evergreen-portfolio
description: Turn a CBRE EverGreen Excel export into one client-ready HTML file, a scroll storyline plus an interactive dashboard, built and checked by agent committees. UK occupier portfolios.
---

# CBRE EverGreen portfolio: storyline + dashboard

**Input:** an EverGreen building export (.xlsx, one row per building) for a UK
occupier client. **Output:** one self-contained HTML file with a CBRE app bar and
two views. **Storyline** (opens first) is a scroll narrative of the portfolio's
argument. **Dashboard** is where the reader explores: map, filters, charts, table,
unit drawer, CSV. The file opens by double-click, offline, with nothing to install.

It is written for the client (CBRE speaking to the occupier), so every figure
must be traceable and the design must hold up in front of a board.

## What makes this skill work

1. **Creativity over templates.** The engine is a kit of finished parts and a
   quality floor, never a mould. Each portfolio has its own two or three things
   that matter. The committee finds them, and may drop, reorder, replace or invent
   scenes and dashboard panels to show them. Forcing a client's data into last
   time's shape is the failure mode to avoid.
2. **Committees, not one pass.** Three independent analysts; you, the orchestrator,
   recompute and choose as chair; two authors build; then three ruthless QA agents
   (visual, numbers, storyline) check once, in parallel, assuming the build is
   wrong. Every finding is fixed, then a smoke check confirms nothing broke
   (reference/committees.md).
3. **Every number traceable.** A ledger links each figure to its computation and
   denominator. QA recomputes it from the raw export.
4. **Never guess.** A literal 0 means unknown, placeholder dates are null, and
   "not recorded" is a finding. Only the dated UK rules in reference/uk-rules.md
   may be stated, at their real status. No web lookups for market data.

## Run it

**Toolkit update check (run once, first).** Run `python scripts/version_check.py`. It prints a
one-line note to stderr *only* if a newer UK I&L Toolkit version has been published (otherwise
it is silent); it does nothing but a single public version lookup, never blocks the run, and is
safe to ignore.

Budget: **about 2½ to 3¼ hours**, end to end, with no stops for review (an
estimate): data 10 min, analysts 15, your brief and ledger 20–25,
authors 55–70, one parallel QA pass 30–40, fixes 20–30, smoke check 5. There is
exactly **one** QA pass and **one** fix pass: never add another QA round. Tell the
colleague at the start what will happen and roughly how long it takes, then run
without asking questions. Make reasonable calls and record them in
`work/data-notes.md`.

1. **Set up.** Find the export (ask only if there is none). Make a run folder next
   to it: `<Client>_portfolio/` with `work/`, `report/`, `qa/`. The as-at date is
   the export date, usually in the file name; otherwise use the latest
   `Building last updated date` and say so.
2. **Data** (Data steward, committees.md §Phase 1):
   `python -B <skill>/scripts/profile_export.py <export.xlsx> <run>/work`
   → write `work/mapping.json` →
   `python -B <skill>/scripts/evergreen_units.py <run>/work/raw.json <run>/report/units.json --mapping <run>/work/mapping.json --as-at <date>`
   (add `--extend <run>/work/extend_units.py` if the client needs extra fields; always
   re-run the full command after any mapping change) → `work/data-notes.md`, `report/meta.json`.
3. **Insight** (Analysts A, B, C in parallel) → `work/analysis/`. Then **you are
   the chair** (committees.md §Phase 2b): recompute, choose the spine, and write
   `work/brief.md` and `work/ledger.md` yourself.
4. **Build** (Storyline author and Dashboard author in parallel) →
   `report/story.js`, `report/dash.js`, then
   `python -B <skill>/scripts/assemble.py <run>/report -o <run>/<Client>_Portfolio.html`.
5. **QA, once** (Visual QA, Numbers QA and Storyline QA in parallel) →
   `qa/visual.md`, `qa/numbers.md`, `qa/storyline.md`.
6. **Fix everything, smoke check, deliver** (committees.md §Phase 5). The authors
   fix every finding, blocking and advisory. You re-assemble and run the smoke
   check (`node <skill>/scripts/smoke.cjs <file>`, or `scripts/smoke.js` through
   the Playwright MCP). No further QA. The deliverable is
   **`<Client>_Portfolio.html` next to the export**, copied from the final
   `<run>` build. Nothing else goes to the client. Write the summary described in
   committees.md §Phase 5.

The full briefs for every role, what each reads and writes, and the ledger format
are in **reference/committees.md**. Read it before spawning anyone. **Nine roles
are sub-agents:** the data steward, three analysts, two authors and three QA
agents. You, the orchestrator, set up, act as chair, fix data, assemble, dump the
page text, run the smoke check and deliver. Spawn at most three sub-agents at a time. Run them in the background: you're
notified when each finishes. If your environment doesn't notify, wait by
checking for the role's output file rather than re-spawning. If you cannot spawn
sub-agents, play the roles yourself in order, as that file describes.

## Environment

- **Python 3** with `openpyxl` or `pandas` (both usual). Nothing else is needed to
  build. **Do not `pip install` or `npm install`.** Everything compiled (React,
  Framer Motion, Leaflet, fonts, basemap, dashboard core) is prebuilt in `engine/`.
  Report code is plain JavaScript, with no build step.
- **Browser for Visual QA.** If Node can load Playwright, run
  `scripts/qa_run.cjs` for the mechanical sweep: every scene, viewport, reduced
  motion, print, and page text. Use the **Playwright MCP** tools for looking and
  for interactive states. If only the MCP exists, it does both. It **blocks
  file:// URLs**, so serve the run folder over HTTP first and browse
  `http://localhost:8787/...`. With neither, do static checks only and state the
  limitation in the summary. There is **one** MCP browser, and only one role uses
  it at a time (committees.md, "Sharing the browser").
- **Starting the local server** with the **Ripple MCP** `execute_command`. The
  host may be Windows even when Cowork's own shell is Linux:
  - Windows (use the `cmd` shell): `start "" /min python -m http.server 8787 --bind 127.0.0.1 --directory "<run>"`.
    To stop it, `netstat -ano | findstr :8787`, then `taskkill /PID <pid> /F`.
  - macOS/Linux (bash): `cd "<run>" && nohup python3 -m http.server 8787 --bind 127.0.0.1 >/dev/null 2>&1 &`.
    To stop it, `pkill -f "http.server 8787"`.
  - If port 8787 is taken, use the next free one. Always stop the server at the end.
  Exact QA steps are in reference/qa-visual.md §3.
- **Encoding:** every file is UTF-8. PowerShell 5.1's `Get-Content` shows it as mojibake (`Â·`). The file is fine: never "fix" it. Read files with the Read tool, or `Get-Content -Encoding utf8`.
- **Paths:** `<skill>` is this skill's folder. Keep all run files inside the run
  folder. Never write into the skill folder.

## Reference map (read when you reach that step)

| File | Read it when |
|---|---|
| reference/committees.md | before spawning any role; defines every brief and hand-off |
| reference/data-evergreen.md | data steward; anyone computing a figure |
| reference/uk-rules.md | analysts, you as chair, authors, numbers QA; the only outside facts allowed |
| reference/insight-playbook.md | analysts and you as chair; what "outstanding" means |
| reference/storyline-craft.md | you as chair, storyline author, storyline QA; scene grammar, headlines, pacing |
| reference/storyline-engine.md | storyline author; the `window.Story` API and htm |
| reference/dashboard-craft.md | you as chair, dashboard author |
| reference/dashboard-engine.md | dashboard author; the `window.DASH` API |
| reference/design-system.md | authors and visual QA; tokens, type, colour, motion, charts, anti-patterns |
| reference/qa-visual.md | visual QA; protocol, viewports, audit script, report format |
| examples/*.js | authors; a complete worked storyline and dashboard, plus a new-scene example |

## Non-negotiables (QA fails the build on any of these)

- WCAG AA contrast on every visible text run, on light and dark grounds.
- Nothing hidden under the 56px app bar. Pinned scenes fit 1536×730, 1366×768
  and 1280×600. No horizontal scroll at 390px.
- No `NaN`, `undefined`, `null`, `Infinity` or placeholder text anywhere.
- Chart scales never move relative to their marks. Labels never collide.
- Every aggregate states its denominator. Storyline and dashboard agree.
- Regulatory statements match uk-rules.md, including status ("is set to" vs "is").
- Landlord concentration uses leased units only.
- No client data, names or figures are written into the skill folder.
