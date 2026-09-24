# Visual QA protocol

**Your stance:** *You did not build this. Assume it is wrong until you have
proved otherwise. Report defects, not praise.*

You check the **assembled** file (`<run>/<Client>_Portfolio.html`), never the
sources. You return `<run>/qa/visual.md` (the one QA pass, written as you go),
plus screenshots in `<run>/qa/shots/`. Numbers and claims belong to the Numbers
QA, but if a visual contradicts its own headline, report it. You also hand the
Numbers QA `<run>/qa/page-text.txt` (§3).

Tools, all in `<skill>/scripts/`:
- `qa_audit.js`: one in-page audit function.
- `qa_run.cjs`: a Node driver that walks every state and runs the audit.
- `page_text.js`: a dump of every word on the page, for the Numbers QA.

Pick the route in §3. The audit catches the mechanics. Your eyes on the
screenshots catch meaning (§4). You need both. The audit detects many classes of
defect, but people still find ones it misses by eye: it is a floor, not a
verdict.

---

## 1. What to inspect

**Viewports**

| Size | Why |
|---|---|
| 1536×730 | Short laptop or projector. The hardest fit for pinned scenes |
| 1440×900 | The common laptop |
| 1366×768 | Older laptop. The column widths change type size |
| 390×844 | Phone. Pins degrade to stacked scenes; charts must re-lay out |
| 1280×600 | Pinned-scene fit (storyline, desktop), with the full 0.1/0.5/0.9 walk: a fitted chart shrinks below its design height here, so a build whose origin assumes that height lands off its axis only at this size |
| 688×1017 | Print: the printable area of A4 with the 14mm page margins |

**States**

*Storyline*, at every viewport:
- Every scene centred. At 390×844, and for tall scenes, every scene at its top,
  middle and bottom.
- Every **pinned** scene at progress **0.1, 0.5 and 0.9**. Compare them. At 0.1
  the build has started. At 0.5 bars are mid-growth, and labels must ride on
  them. At 0.9 the emphasis has landed.
- On desktop, every scene at **start** (what a rail click shows), with the
  headline clear of the app bar.
- Light **and** dark scenes: the ground has changed and the text follows it.
- The same walk with **reduced motion**, at every viewport and with pins at
  0.1/0.5/0.9: every chart finished, counters at their final values.

*Dashboard*, at every viewport:
- Default, walked top to bottom.
- **Map zoomed** +2 and +4 (the labels re-place and hand over to street labels).
- **Filtered.** Use the **largest landlord**, not the first option: the first is
  often a one-unit landlord, which exercises nothing. Also filter on any
  dimension the brief leans on (a company chip, a region). Then a **sparse**
  state, with every select at its last option (0–2 units).
- **Drawer open** for the first row, the sparsest record and any unit the brief
  names, at the top and scrolled to the end.
- The table scrolled so its sticky header should be showing.

*Print*, once: a fresh, unscrolled load under print media, for both views.

Also check the **console** for errors. Offline tile and network messages
don't count.

## 2. Severity

| Level | Meaning | Examples |
|---|---|---|
| **P1: blocks delivery** | A reader is misled, can't read it, or can't use it | WCAG AA contrast fail on real content; text or a control hidden under the app bar or another layer; a pinned scene cutting its headline; horizontal scroll at 390px; NaN / undefined / null / Infinity / a 1950 date visible; a scale that moves or a value label detached from its bar; unfinished charts under reduced motion or in print; overlapping text; chart text under 8px on screen (5.5px in print); a sticky bar over 45% of the screen; a regulatory line stated more firmly than uk-rules.md |
| **P2: advisory, fixed in Phase 5** | Visibly wrong, but the meaning survives | A line or frame through a label; a top gridline below the tallest bar; two meanings drawn alike (the not-recorded hatch on a real category, a ring colour that is a near miss of a legend's); thousands and millions mixed in one chart; a desktop table wider than its frame; a sticky header that doesn't stick; a label that one viewport silently drops; labels clipped by a frame or cut by a tile edge; a label on a mark it doesn't describe; an unlabelled sizeable tile; secondary text at 8–10px (5.5–7px in print); duplicate unit names; a drawer caption under the bar; text still invisible in view (a late reveal); a legend arriving after its chart; a bar floating off its axis or baseline; repeated or uneven tick labels on even gridlines ("0.3m 0.3m"); small marks that print as dark discs or vanish on white; a word or figure broken mid-token in a printed table; a later headline as large as the opening |
| **P3: advisory (polish)** | Nobody is misled | Targets under 24px; a later headline within 10% of the opening size; a mid-word break in a table on screen; clickable marks with only a table as the keyboard path; dimmed disabled rows; mid-fade contrast at progress 0.1; attribution text size; truncation that keeps the full name in a tooltip; a phone table without a sticky first column; a dark KPI band in the dashboard print |

P1 is **blocking**; P2 and P3 are **advisory**. There is one QA pass and every
finding, of any severity, is fixed in Phase 5 (committees.md), so give each one
an exact fix. An author may decline one only with a stated reason, and it is
listed in the delivery summary.

## 3. How to run it

**Use Route B for the sweep and the MCP browser for looking.** If `node` can
find Playwright, `qa_run.cjs` does the mechanical walk (about 500 audited
states, every screenshot, the print PDFs, the page text) in about 9 minutes. Then
spend MCP calls on what only eyes can do: open the screenshots it names, and
check the states it can't reach (a named drawer, a keyboard walk, a filter the
brief cares about). If Node Playwright is missing, Route A does both, and costs
far more calls.

### Route A: Playwright MCP (Cowork)

The MCP browser **blocks `file://`**, so serve the run folder over HTTP.
Screenshots can only be written **inside the workspace** (relative filenames
resolve against the workspace root).

1. **Serve.** Copy `qa_audit.js` and `page_text.js` from `<skill>/scripts/` into
   `<run>/qa/`, so the page can fetch them. Pick a free port and call it `PORT`
   (8787 in these examples; 8795 etc. if another run or role holds it). Then start
   a server with the Ripple MCP `execute_command`. The host is often **Windows**
   even when Cowork's shell is Linux:
   - Windows (the `cmd` shell; `python3` and bash don't exist there):
     `set PORT=8787 && start "" /min python -m http.server %PORT% --bind 127.0.0.1 --directory "<run>"`.
     The console that ran `start` stays "busy" afterwards. That's harmless: the
     server runs in its own minimised window, and Ripple routes the next command
     to a standby console. To stop it: `netstat -ano | findstr :%PORT%`, then
     `taskkill /PID <pid> /F`.
   - macOS/Linux (`bash`): `PORT=8787; cd "<run>" && nohup python3 -m http.server $PORT --bind 127.0.0.1 > qa/server.log 2>&1 &`.
     To stop it: `pkill -f "http.server $PORT"`.
   If the port is busy, take the next one. Stop the server when QA ends.
2. `browser_navigate` → `http://localhost:<PORT>/<Client>_Portfolio.html?r=1`. To
   load a **rebuilt** file, change the query (`?r=2`, `?r=3` …). Navigating to the
   same URL, or changing only the hash (`#dash`), does **not** reload the page in the
   MCP browser, so you would audit the old build.
3. `browser_resize` → `{ "width": 1536, "height": 730 }`
4. **Install and list** (one `browser_evaluate`; `function` is exactly this):
   ```
   async () => { const src = await (await fetch('qa/qa_audit.js')).text();
     return (0, eval)('(' + src + ')')({ action: 'list', view: 'story' }); }
   ```
   It installs `window.__qaAudit` and returns the scenes. `pinned: true` marks a
   scene with a sticky stage; a sticky table column does not count. If fetch is
   impossible, pass the **whole text** of `qa_audit.js` as `function` instead.
   That also installs it, but it is about 90KB, so do it once per page load.
5. **Audit each state** with one-liners (keep `max: 6` so replies stay small):
   ```
   async () => window.__qaAudit({ scene: 's6', progress: 0.5, max: 6 })
   async () => window.__qaAudit({ scene: 's6', progress: 'start', headings: true, wait: 750, max: 6 })
   async () => window.__qaAudit({ scene: 's2', max: 6 })          // non-pinned: centred
   ```
   The storyline ground cross-fades over 620ms, and contrast read inside the fade
   is wrong. The audit therefore waits at least 700ms after any scroll in the
   storyline, whatever `wait` says, and then waits out any colour transition
   still running. If you scroll the page yourself (`browser_evaluate`,
   `browser_press_key`), wait 700ms before auditing without a scroll option.
   Audit each pinned scene at 0.1 **then** 0.5 **then** 0.9 without reloading in
   between. `scaleDrift` and `labelDrift` compare consecutive calls. After each
   state, run `browser_take_screenshot` →
   `{ "filename": "<run-relative-to-workspace>/qa/shots/1536x730-story-s6-p50.jpg", "type": "jpeg" }`.
   Use the names `qa_run.cjs` uses (§3 Route B) so rounds stay comparable. If the
   run folder is outside the workspace, save under `.playwright-mcp/` and move the
   files into `qa/shots/` afterwards.
6. **Dashboard.** `window.__qaAudit({ view: 'dash', action: 'list' })` returns
   every section and **every panel**, including the panels that share a row
   (those carry `row: <band>`). Scroll to one with `{ section: <index> }`. Then walk
   `window.__qaAudit({ y: 0, wait: 400, max: 6 })`, `{ y: 580, … }` and so on, in
   steps of 0.8 × the viewport height. `meta.anchor` names the panel in view: use
   it in the screenshot name. For the other states, drive the page with its own API
   (faster and deterministic), for example
   `async () => { DASH.api.reset(); DASH.api.setFilter('landlord', '<Landlord name>'); }`
   or `DASH.api.openDrawer(DASH.api.all.find(u => u.id == '<unit id>'))`. Or use
   `browser_snapshot` plus `browser_select_option` / `browser_click` /
   `browser_press_key` `Escape`. To find the largest landlord:
   `() => Object.entries(DASH.api.all.filter(r => !r.owned && r.landlord).reduce((a, r) => (a[r.landlord] = (a[r.landlord] || 0) + r.size, a), {})).sort((a, b) => b[1] - a[1])[0]`.
   Re-audit and screenshot each state.
7. **Other viewports.** `browser_resize` doesn't reload, so the audit stays
   installed. After any navigation or reload, repeat step 4.
8. **Reduced motion.** `browser_emulate_media` → `{ "reducedMotion": "reduce" }`,
   then navigate again (the page reads the preference at load), install, and
   repeat step 5 at each viewport (pins at 0.1/0.5/0.9). Any `rmHidden` or
   `hiddenText` is a P1 or P2. Reset with `{ "reducedMotion": "no-preference" }`.
9. `browser_console_messages` → errors are defects.
10. **Print pass.** `browser_resize` → `{ "width": 688, "height": 1017 }`,
    navigate again (fresh and unscrolled; don't scroll first, since printing
    must not depend on scrolling), install, then `browser_emulate_media` →
    `{ "media": "print" }`. Run `window.__qaAudit({ action: 'print' })` for the
    storyline, then `window.__qaAudit({ view: 'dash' })` followed by
    `{ action: 'print' }` for the dashboard. That call checks:
    - animated marks left translucent or part-grown (`printUnfinished`);
    - counters short of their final value (`printCounter`);
    - pinned stages still sticky, or spacers that print as blank pages
      (`printPinned`, `printBlank`);
    - solid dark blocks (`printDark`);
    - marks that change meaning on paper (`printMarks`). A "ring" faked with a
      dark-ground fill and a white stroke prints as a solid dark disc. A white
      mark, or a legend swatch drawn only in white, disappears.

    Then walk each view with `{ y, wait: 250 }` in steps of 900 and take
    screenshots. The ordinary checks run under print media too: contrast,
    overlap, lines through text, **words and figures split mid-token in table
    cells** (`midWordBreak`: "123,45 / 6"), and small text at a **7px print floor**
    (about 5pt). The screen-only checks (app bar, sticky bars, ground mode) are
    skipped automatically. The MCP can't produce a paged PDF, so page breaks
    and blank pages are only checked by Route B. Say so in "Not checked". Reset
    with `{ "media": "screen" }`.
11. **Page text for the Numbers QA** (if the orchestrator hasn't already). With
    reduced motion on, run one `browser_evaluate` with
    `async () => { const s = await (await fetch('qa/page_text.js')).text(); return (0, eval)('(' + s + ')')({}); }`.
    Save the returned string as **`<run>/qa/page-text.txt`**. If you use the
    tool's `filename` option, the file holds a JSON-escaped string: decode it
    (`json.loads`) before saving. §6 has the format.
12. Stop the server (step 1) and close the browser when done.

**Gotchas.**
- **Reloading:** the MCP browser doesn't reload on a hash-only change or on the
  same URL. After a rebuild, navigate with a new query (`?r=N`) and install the
  audit again.
- **Filters persist:** the dashboard may remember filters across a reload. After
  every navigation, call `DASH.api.reset()` (or press "Clear all") before auditing.
- **Element screenshots** (`target`) mislead on this page: the fixed ground and
  sticky bars don't follow the element, and the scene's motion restarts. Take
  viewport screenshots after scrolling instead.
- **Paths:** relative screenshot filenames resolve against the workspace root.
  `browser_run_code_unsafe` resolves relative paths under `C:\Windows\System32`
  on a Windows host, so always give it **absolute** paths (for a file it
  writes, or a script it reads).
- **Snapshots:** `browser_snapshot` and navigation results write `.yml` files to
  `.playwright-mcp\` at the workspace root. That is expected; leave them, and
  don't copy them into the run folder.
- **Print:** under print media, emulate *after* the fresh load, never after
  scrolling.
- **Windows server:** `start "" /min …` leaves its launching console busy. That
  is harmless (see step 1).

**Budget (Route A only).** A full pass is realistically **150–250 audit calls
and 40–60 screenshots** for a 10-scene storyline at four viewports, plus the
dashboard states and print. Prioritise, in order: pinned scenes, light scenes,
new (non-library) scenes and panels, the 390px pass, the drawer, print. Write
each defect to the report as you confirm it.

### Route B: Node Playwright (the sweep)

```
node <skill>/scripts/qa_run.cjs <run>/<Client>_Portfolio.html             # full: 4 viewports, RM, print, page text (~9 min)
node <skill>/scripts/qa_run.cjs <file> --quick                            # 1536x730 + 390x844 (~2.5 min)
node <skill>/scripts/qa_run.cjs <file> --viewports 1280x600 --story       # pinned fit + mid-build geometry (~3 min)
node <skill>/scripts/qa_run.cjs <file> --story --scenes s04,s06           # re-check named scenes
node <skill>/scripts/qa_run.cjs <file> --print-only                       # re-check print only: both PDFs (~40 s)
node <skill>/scripts/qa_run.cjs <file> --dash --filter landlord="<Landlord>" --filter group="<Company>" --drawer <unit id>,3
```
Measured on a laptop with the two test portfolios: the full run audited 482–517
states in 8.4–8.8 minutes; `--quick` audited 117 in 2.4 minutes. A 12-scene
storyline with a large dashboard takes longer.

`--quick` checks 1536×730 and 390×844 with pins at 0.5 only. It **skips** the
filtered and sparse dashboard states, the rail-jump checks and the tall-scene
top/bottom passes. It is a smoke test, not a QA pass.

| Option | Effect |
|---|---|
| `--viewports a,b` | the viewports (default 1536x730,1440x900,1366x768,390x844) |
| `--progress a,b` | pinned progress points (default 0.1,0.5,0.9) |
| `--story` / `--dash` | one view only |
| `--scenes a,b` | only these storyline scenes |
| `--filter k=v` | a dashboard filter to audit: `landlord=`, `region=`, `tenure=`, `group=`, or a custom filter id (`cold=true`). Repeat the flag for several. Default: the largest landlord by leased floorspace |
| `--drawer n\|id` | drawers to open: a unit id or a 1-based table row. Repeat or comma-list. Default: the first row and the sparsest record |
| `--no-rm`, `--no-print`, `--no-text` | skip the reduced-motion walks, the print pass, or the page text |
| `--print-only` | only the print pass (A4 print media, both PDFs and page images): the re-check for a print fix |
| `--text-out <file>` | where the page text goes (default `<run>/qa/page-text.txt`) |
| `--no-shots`, `--out <dir>`, `--playwright <path>` | as named (Playwright can also come from env `PLAYWRIGHT_PATH`) |

It writes:
- `qa/shots/*.jpg`. Names depend only on viewport, state and scene id or panel
  heading (`1536x730-story-s06-p90.jpg`, `1536x730-dash-p-expiry.jpg` (the panel's
  section id, or its heading as a slug),
  `1536x730-filter-landlord-<name>-….jpg`, `1536x730-drawer-<unit>-top.jpg`,
  `print-story-03.jpg`), so a later run overwrites an earlier one shot for
  shot. Use `--out qa/shots-fix` to keep both.
- `qa/shots/qa-report.json`. It is **rewritten every few seconds** with
  `"partial": true`, so a killed run still leaves its results, and it becomes
  `false` at the end. `summary.byType` lists every check, zeros included.
- `qa/shots/print/story.pdf` and `dash.pdf`: real `page.pdf()` output. Page
  count and **blank pages** are read from the PDF itself, and page images
  (`story-01.png` …) are added when `pdftoppm` or PyMuPDF is available. The
  report says which it used.
- `qa/page-text.txt`: the text dump for the Numbers QA.

It prints one line per grouped defect, with viewports, states and a screenshot
name. Exit code 0 = no P1, 1 = P1 defects or console errors, 2 = could not run
(the message says why and what to use instead). **Never `npm install`.** If it
exits 2, use Route A or C.

The driver walks everything, but it doesn't look. Open the screenshots it
names, plus one of every scene and a few print pages, and apply §4.

### Route C: no browser at all

Put this at the top of `qa/visual.md`: *"No browser was available. Rendering,
contrast against real backgrounds, collisions, fit, motion and print were NOT verified."*
Then run static checks and report what they find:
- Search the built HTML and `report/*.js` for `NaN`, `undefined`, `Infinity`,
  `null` in user-facing strings, `1950`, `1905`, and `[object`.
- Compute contrast for every colour pair the report's CSS and JS use against
  design-system.md §2 (a ten-line script). Flag raw hex values that aren't tokens.
- For each SVG: compare the viewBox width with the expected column width at 1440
  and 390px, and estimate the rendered size of the smallest label (under 10px is
  a finding). Do the same at 688px for print (under 7px).
- Hard-coded numbers in copy, labels, `aria-label`s and tooltips that the data
  could compute. Axis ticks computed with `< max` (a top gridline below the
  maximum) rather than rounded up to the next step.
- Every chart has `role="img"` and a computed `aria-label`. Every Framer
  `initial` is gated on `useReducedMotion`. Resizable pinned charts use
  `useFitHeight`. No `transform` on gridline groups. Fixed layers start at
  `var(--bar-h)`. Sticky offsets are written to the view root. No
  `overflow-x: auto` wrapper around a table whose header is meant to stick.
- Print: every animated element carries `.mv` (or its final state in its
  attributes), counters carry `data-final`, and the report's own print CSS
  keeps charts ink on white.

## 4. The checklist: look at every screenshot for these

The audit names in brackets flag the mechanical part. Your eyes confirm it and
catch the rest.

**Screen**
1. **Ground:** a light scene sits on a light ground, with no dark type on dark
   green. Colours finish their fade with the ground. [contrast, groundMismatch]
2. **Fit:** the headline is fully below the app bar. The pinned block isn't cut
   at the foot, at 1536×730 and 1280×600. [underBar, pinOverflow, headingUnderBar]
3. **Scales:** gridlines sit on their tick values. Tick labels step evenly at
   the precision of the step: a 0.25m step labelled "0.3m · 0.5m · 0.8m", or
   "0.3m" twice, misreads every bar. The top line sits at or above the tallest
   bar (check the filtered and sparse states too; this is where it breaks).
   Gridline positions are identical at progress 0.5 and 0.9. One unit style per
   chart ("0.4m", never "400k" beside "0.47m"). [tickLabels, topGridBelowMax,
   scaleDrift, numberFormat]
4. **Bound marks and labels:** at every progress point each bar grows **from its
   axis** (or from the bar below). A block that slides down into place, or
   scales about a point that isn't the axis (after `useFitHeight` changes the
   height), shows a false value mid-build. Every value label sits on its growing
   bar. Counters and percentages don't show until the marks they describe are
   drawn. [offBaseline, labelDrift]
5. **Leaders** start on their mark, are long enough to read as connectors
   (≥16px), and point at the right note. [floatingLeader]
6. **Collisions:** labels against labels, and labels against dots and bars. A
   today or threshold line, a dashed frame or a separator must not run through a
   label. An enlarged label must not hit its neighbours. [overlapText, labelMark,
   lineThroughText]
7. **Coverage:** every key item is labelled (the top holders, the highlighted
   year, the named building) at **every** viewport. A lane or tile that drops its
   denominator line at 1280 or under reduced motion has lost its base. Truncated
   names stay recognisable. [unlabelledTile, truncated, droppedText]
8. **Encodings:** each look means one thing. The 45° grey hatch means "not
   recorded" only, so a grouped tail is `--wash`. A mark's outline must not be a
   near miss of a legend ring that means something else. A solid ring and a
   dashed ring are different looks, and the audit compares fill, stroke, dash,
   shape and stroke weight together. The same state is drawn the same way in
   every scene and in the dashboard, including a stock panel that colours by
   group when the group dimension is off (a "passed" column in a running-lease
   colour). The audit can't compare across panels, so check it by eye.
   [encodingClash]
8b. **Type hierarchy:** the opening headline is the largest type in the
   storyline, decisively larger (≥1.1×) than any statement, the closing, or a
   scene headline. [openingNotLargest]
9. **Size:** chart text is readable at every viewport, especially 390px (the
   audit gives rendered px). [smallText]
10. **Text on marks:** labels on tiles and segments pass. Coral text uses the
    text tokens. [contrast]
11. **Map:** no raster labels at the overview. Place labels are not clipped by
    the frame, not on another town's dot, and have no dash-like leaders.
    Markers are crisp after fit. The offline note sits under the map, not
    inside the caption. [labelMark, clipped]
12. **Tables:** on desktop the table fits its frame, with no column off-frame and
    no header cut mid-word. On the phone it scrolls inside its box with a sticky
    first column and a cue. The sticky header sits directly under the filter
    bar once scrolled. [tableOverflow, stickyBroken, covered, dupLabel]
13. **Numbers on screen:** fixed decimals, one unit style, no placeholder years,
    a denominator in every provenance line, and the same figure in both views.
    [placeholderDate, badToken, numberFormat]
14. **Regulatory lines** use uk-rules.md's status words.
15. **Focus:** tab through the app bar, rail, CTA, filters, chips, table rows and
    drawer. The ring is visible everywhere, as an outline and not a box-shadow.
    There is no ring on the heading that receives focus when the view switches.
    Focus returns after the drawer closes. [progFocusRing]
16. **Keyboard:** Enter on a row opens the drawer. Escape closes it. Sort headers
    work from the keyboard. [clickNoKeyboard, smallTarget]
17. **Mobile:** no sideways scroll, pins stacked with their visuals finished,
    each headline before its visual, readable charts, a filter bar that doesn't
    swallow the screen, and a reachable drawer close button. [hScroll,
    stickyTooTall, smallText]
18. **Reduced motion:** every chart complete, counters final, nothing invisible,
    and no label lost to the tighter finished layout. [rmHidden, hiddenText,
    droppedText]
19. **Layout:** two columns collapse under 980px and nothing stays in desktop
    columns at 390px. No 300px voids from centring short text against a tall
    chart. Empty states are compact, not a 400px dashed box.
20. **Stability:** heights don't grow between two audits of the same state (a
    ResizeObserver loop), and nothing jumps when fonts land.
21. **Anti-patterns:** any item in design-system.md §11 is a defect (gradients,
    glass, emoji, card soup, everything centred, filler headlines…).
22. **Non-text contrast:** pale categorical marks on white (the accent, celadon
    and celadon-tint are under 3:1) carry a label or an outline (design-system §3).
    The audit doesn't measure this.

**Print** (Route B's PDFs and page images, or the print-media screenshots)
23. **Finished:** every chart is fully built. Bars are at full height, circles at
    full size, annotations and counters at their final values, whatever the
    scroll position was. [printUnfinished, printCounter]
24. **Stacked:** pinned scenes print as ordinary scenes. No sticky stage, no
    spacer printing blank pages, and no blank page anywhere. [printPinned,
    printBlank]
25. **Ink on white:** dark scenes print as ink on white paper, with no solid dark
    blocks in the storyline. Labels on marks keep their contrast, and tiles keep
    their edges (a white tile on white paper loses its area). Small marks keep
    their meaning: a hollow ring faked with a ground fill prints as a dark disc
    beside the real dark discs, and a white-only legend swatch prints as nothing.
    [contrast, printDark, printMarks]
26. **Readable at A4:** chart text is at least 7px at the 688px print width (a
    chart that scales instead of re-laying out prints at 4–5pt). Tables fit the
    page width, with no column cut at the right edge and no word or figure
    broken mid-token ("123,45 / 6", "REGIO / N"). Nowrap cells don't spill into
    their neighbours. [smallText, clipped, midWordBreak, overlapText]
27. **Breaks:** no headline alone at the foot of a page with its chart on the
    next. The opening map and key stay together. (Eyes only.)

## 5. Reading the audit

Every issue has `type`, `sev`, `scene` (the section or pinned wrapper id),
`panel` (the nearest heading), `node` (the nearest id), `text`, `detail`
and `rect`. `counts` lists every type, zeros included, and is complete even when
`issues` is capped by `max`. `meta.anchor` names what is in view.

| Type | What it means | Confirm | Typical fix |
|---|---|---|---|
| contrast | text against what is actually painted under it (SVG shapes and gradients at the text's position included) is under 4.5 or 3:1 | `fg`/`bg`/`ratio`, screenshot | next token in design-system §2; `--warm-text` / `--warm-ink` for coral |
| groundMismatch | text mode says light but the painted ground is dark (or the reverse). Screen only | screenshot | `isolation: isolate` on the view root; `GroundSection` for plain sections |
| underBar / headingUnderBar | content on a pinned or fixed layer, or a headline at "start", sits under the 56px bar | `hiddenPx` | fixed layers `top: var(--bar-h)`; scene padding; `useFitHeight` with a lower min height |
| pinOverflow | a pinned block is taller than its stage | `content` vs `room` | `useFitHeight`, `align-items: safe center`, shorter paragraph or provenance |
| covered | text hidden under another layer (a sticky header under the filter bar) | `by` | measured offsets written where the scoped CSS reads them |
| stickyTooTall | a stuck bar covers >30% of the viewport | `share` | collapse to a button or unstick on small screens |
| hScroll | page wider than the viewport | `widest` offenders | `minmax(0, …)`, `min-width: 0`, media query |
| overlapText | two text boxes from different blocks overlap | both texts, screenshot | move to the clear side, stagger, fewer labels |
| lineThroughText | a line, dashed marker, frame edge or HTML rule passes through a label (in one side, out the other). Gridline families and haloed labels are exempt | `line`, `at`, `over`/`under` | stop the line short of the label, move the label, or give it a ground-coloured halo (`paint-order: stroke`) |
| labelMark | a label straddles a bar or tile edge, sits over a dot, or sits on another place's point | `share` (fraction of the label box) | re-place the label; enlarge the tile threshold |
| floatingLeader | a diagonal leader line doesn't touch any mark | `gapPx` | compute the leader in the bars' scale |
| topGridBelowMax | the tallest (stacked) column rises above the top gridline, or the longest bar runs past the last one | `overshootPx`, `topLine` | ticks up to the first step ≥ max: `Math.ceil(max/step)*step` |
| numberFormat | "k" and "m" values mixed in one chart | `k`/`m` counts | one unit at every scale (0.10m … 0.50m) |
| tickLabels | equally spaced gridlines carry unequal or repeated tick values ("0 · 0.3m · 0.5m · 0.8m", "0.3m 0.3m"): the label precision is coarser than the step | the labels, `step` | format ticks at the precision of the step (0.25m → "0.25m"), or use a 1/2/5 × 10ⁿ step |
| offBaseline | a bar whose own geometry sits on the axis (or on the bar below) is drawn off it: it slides into place, or it scales about a point that isn't the axis | `offsetPx` (negative = floating above), `from` | grow with `scaleY` from the axis (`transform-box: fill-box; transform-origin: 50% 100%`), recompute the origin after `useFitHeight`, and never translate a bar into place |
| encodingClash | two meanings, one look: `hatch` (the grey not-recorded hatch on a real category), `legend` (two entries of one legend drawn the same: fill, stroke, dash, shape and weight all alike), `near-legend` (a mark's outline is a near miss of a legend ring of the same dash) | `kind`, `deltaE`, screenshot | `--wash` for a tail; a neutral outline plus a centre dot for company colour; one encoding per state |
| openingNotLargest | a later headline (a statement, the closing, a scene headline) is as large as the opening (P2) or within 10% of it (P3) | `openingPx`, `otherPx` | restore the opening size (shorten the line), or cap the later display lines at about 0.8× the opening |
| midWordBreak | a word or figure broken across lines inside a table cell: a hard break (inside a figure, or a word split with no hyphen) is P2 in print and P3 on screen; a word the browser hyphenated (`hyphens: auto`, "recor- / ded") is P3 | examples (`123,45\|6`, `rec-\|orded`), `breaks`, `hyphenated` | drop or merge columns for print (an A4 table rarely holds more than 7), `white-space: nowrap` on figures, no `overflow-wrap: anywhere` on numbers |
| unlabelledTile | tiles ≥2.5% of a treemap or mosaic with no label inside or named elsewhere (grouped per chart). Unit grids and translucent bands are skipped | `tiles`, `examples` | one-line fallback; an outside label on a leader; list in the Rows drawer |
| droppedText (driver) | a chart label rendered at one desktop viewport is missing at another (reduced-motion finished states) | `viewport`, `shownAt` | give the lines a priority and drop the descriptor first, never the denominator |
| scaleDrift | gridlines moved relative to their chart between two audits of a pinned scene | `movedPx` | remove any transform from the axis/gridline group |
| labelDrift | a value label (one that ends just above its bar) kept still while its bar grew | `gapBefore`/`gapNow` | drive the label from the bar's motion value |
| rmHidden / hiddenText | invisible marks under reduced motion; text at opacity 0 in view after settling | screenshot | gate `initial` on `useReducedMotion`; lower the Reveal `amount` for tall blocks |
| smallText | rendered size under 10px on screen, 7px in print (SVG scaled by its viewBox) | `px` vs `declared`, `print` | viewBox ≈ column width; re-lay out at 390px and at print width |
| clipped / truncated | text cut by an `overflow: hidden/clip` frame (not a scroller) / shortened with an ellipsis | `by`, `title` | widen, wrap or re-place; keep the full text in `title` |
| tableOverflow | a table wider than its frame: on desktop, columns sit off-frame (P2); on the phone, the row labels scroll away (P3) | `tableW`/`frameW`, `offFrameColumns`, `stickyFirstColumn` | drop or merge columns; `position: sticky; left: 0` on the first column plus a divider |
| stickyBroken | a header declared sticky scrolls away, because an overflow ancestor became its scroll container (P2 on desktop, P3 on the phone) | `scrollContainer` | no `overflow-x: auto` wrapper where the table fits; accept on the phone |
| badToken / badTokenHidden / placeholderDate | NaN, undefined, null, Infinity, a 1950/1905 year; "hidden" = in aria-labels or tooltips | text | null guards; placeholder dates to null in the data |
| dupLabel | identical first-column text on several table rows | text, `rows` | add unit ID or address |
| contrastDimmed | contrast fails only because the element is translucent | re-audit at 0.5/0.9 | if it is a resting state, use a token rather than opacity |
| printUnfinished / printCounter / printPinned / printBlank / printDark | from `action: 'print'` and the PDF: animated marks left mid-way, a counter short of its final value, a sticky stage or blank spacer, a blank PDF page, a solid dark block | `examples`, page numbers | `.mv` deltas and final values in attributes, `data-final`, the engine print CSS, print overrides for on-mark labels |
| printMarks | from `action: 'print'`: a "ring" faked with a ground fill and a white stroke, which prints as a dark disc. It is flagged when the fill is a ground-only colour (#012A2D, #032842, near-black) or when it merges with a plain dark mark in the same chart. Also flagged: white marks and white-only legend swatches with no dark edge, which vanish. Ink pins with a white halo, and company-colour dots re-inked for print, are real discs and are not flagged | `darkRings`, `vanishing`, examples | hollow = `fill: none` plus a toned stroke (`--sem-unknown`); give white marks and swatches a dark edge under `@media print` |
| smallTarget / clickNoKeyboard / progFocusRing / a11yName | interaction hygiene | selector | 24px targets; button role + tabindex, or a keyboard route; no ring on `tabindex="-1"`; `role="img"` + `aria-label` |

What the audit deliberately ignores:
- screen-reader-only text (1px clips) and closed `<details>`;
- text scrolled out of its own scroller (a wide table is `tableOverflow`'s job);
- ordinary flow text passing under the app bar while scrolling;
- app-bar or sticky-bar text over a chart scrolled beneath it;
- layers hidden on purpose (classes with `hide`, `pre`, `ghost`);
- muted marks at a resting opacity, and translucent reference bands (a shaded
  target range or period behind the marks);
- a table row that's clickable by mouse when a button inside it is the
  keyboard route (the button is enough);
- two legend entries that differ only in dash, shape or stroke weight (a hollow
  ring and a dashed ring are two encodings);
- contrast during the storyline's ground cross-fade: every audit waits at least
  700ms after a move, and then for any running colour transition;
- in print, a dark disc with a white halo that is a disc on screen too (an ink
  pin, or a company-colour dot re-inked for print). The audit can't see a scene's
  screen ground from print, so a ring faked with the ink green (#003F2D) on a
  dark scene is caught only when it merges with a plain dark mark. Look at the
  print pages for it.

What it can't judge: whether a chart says what its headline claims, copy
accuracy against the ledger, non-text contrast of marks, page breaks, and taste.
That is your job.

## 6. The report: `qa/visual.md`, and `qa/page-text.txt`

```
# Visual QA · <Client> · round <n>
Route: B (qa_run.cjs) + A for looking | A (Playwright MCP) | C (static only: <limitation>)
Viewports: 1536×730, 1440×900, 1366×768, 390×844 (+1280×600 fit, print 688×1017)
States: <scenes × progress points; RM; dashboard states incl. filter used; drawers; print>
Audit: <n> runs in <m> min · P1 <n> · P2 <n> · P3 <n> · console <clean | n errors> · print <pages, blank pages>
Verdict: FAIL (P1 open) | PASS WITH P2 (listed below) | PASS

## Defects
1. [P1] underBar · Dashboard drawer (#drawer) · all viewports · drawer open
   Evidence: the close button and location line sit under the 56px app bar
   (hiddenPx 34). Screenshot: qa/shots/1440x900-drawer-unit-1-top.jpg
   Fix: `.drawer { top: var(--bar-h) }` in the dashboard CSS; re-check at 390.
2. [P2] topGridBelowMax · Dashboard "When the leases move" · all viewports · default and filtered
   Evidence: the tallest column (3.1m) rises 20px above the top gridline (3m).
   Screenshot: qa/shots/1536x730-dash-p-expiry.jpg
   Fix: `ticks()`: loop to `Math.ceil(max/step)*step`.
…

## Checked and clean
- Pinned fit at 1536×730 / 1366×768 / 1280×600: all scenes clear the bar.
- Print: story.pdf 15 pages, no blank page, every chart finished.
…

## Not checked
- <anything you could not verify, and why>
```

Rules:
- Number the defects, **P1 first**, one defect per item. Group identical
  instances ("14 labels in #s6") and quote a few.
- Every item gives the scene or panel, viewport(s), state, **evidence** (audit
  detail and a screenshot file) and a **fix** a builder can apply without
  re-diagnosing it: file, selector or component, and the change.
- No praise and no "consider". If it isn't a defect, leave it out, or put it in
  "Checked and clean".
- **Re-check rounds** cover the previous defects plus anything the fix touched.
  Mark each one *fixed*, *still open* or *regressed*, and add new defects at
  the end. Keep the screenshot names: rerun `qa_run.cjs --scenes …` or the same
  MCP names.

**`qa/page-text.txt`** (for the Numbers QA) is tab-separated, **one line per
block element, in document order, never de-duplicated**: `view · where · kind ·
text`. A figure printed twice appears twice, so the Numbers QA can check every
place it appears, and each line is the block's whole sentence (a `<p>` with a
`<b>` figure inside it is one line, not three fragments).
- `view` is `story`, `dash`, `dash[landlord=X]` (a filtered state),
  `drawer:<unit>`, `popup` (map marker pop-ups and tooltips, `where` = the
  unit id and short name) or `csv`.
- `where` is the nearest scene, section or panel id.
- `kind` is:
  - the block's tag (`p`, `h2`, `li`, `td`, `dd`, `figcaption`, `button` …) or
    `svg-text`;
  - `tooltip` (an SVG `<title>` or a map tooltip), `aria-label`, `title`, `alt`;
  - `counter` (`shown=… final=…`, prefixed `MISMATCH` when the screen isn't at
    the final value; `counter·hidden` for a print twin);
  - `header` / `row` (the CSV the reader downloads).
  - A `·sr` suffix marks screen-reader-only text, and `·hidden` marks text in
    the DOM that isn't rendered.

The dump covers both views, every `<details>` opened, the first, largest and
sparsest units' drawers plus any you name, the largest landlord's filtered KPI
band and basis lines, every map pop-up, and the CSV. Produce it with reduced
motion on.
