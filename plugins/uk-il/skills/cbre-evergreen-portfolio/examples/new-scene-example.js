/* new-scene-example.js — inventing a scene from primitives.

   Nothing here comes from Story.charts: it is a LEASE-EVENT CALENDAR drawn
   from scratch with SVG, framer-motion (Story.motion) and the kit (Scene,
   Reveal, Prov, BandKey, useChartProgress, useWidth). Use it as the pattern for any chart
   the kit does not have.

   Insight pattern: "the diary, not the average" — every dated lease event in
   the next five years (expiries, tenant breaks, rent reviews) on a month
   grid, so clusters and the busiest month are visible at a glance.
   Do NOT use it when fewer than ~6 events fall in the window (a list reads
   better), or when breaks and reviews are unrecorded and the expiry
   timeline already tells the story.

   Rules it follows (see reference/storyline-engine.md):
   - data derived at run time, never typed in; nulls excluded, denominators stated
   - the END state is the default; motion only when reduced motion is off
   - one component per animated row, so each hook sits at a component's top
   - colours from tokens that follow the ground mode (var(--hot) etc.)
   - labels sized in viewBox units that land at >= 10px on screen, with a
     re-laid-out phone version below COMPACT_PX
   - finished by the time it is fully in view (useChartProgress)
   Standalone, this file mounts a one-scene story so it can be tested alone.
   In a real story.js, paste LeaseCalendar in and render it inside your Shell. */
(function () {
  'use strict'

  const { html, kit, fmt: F, data: D, motion: M } = Story
  const { Shell, Scene, Reveal, Prov, BandKey, Rows, SvgCounter, useChartProgress, useWidth, COMPACT_PX } = kit
  const { m, useTransform, useReducedMotion } = M
  const { useRef } = Story.hooks

  /* ---------------------------------------------------------------- data */
  const U = Story.units
  const AS_AT = D.asAt()
  const Y0 = AS_AT.getUTCFullYear()
  const M0 = AS_AT.getUTCMonth()
  const SPAN = 5                                   // years shown
  const END = Date.UTC(Y0 + SPAN, M0, 1)

  // Event TYPES are categories, so they take categorical slots (Story.palette),
  // never a semantic state colour: --hot stays free for the ONE emphasis (the
  // busiest month's frame). Slots 1, 2 and 5 pass 3:1 on white, so no edges.
  const P = Story.palette
  const TYPES = [
    { key: 'expiry', label: 'Lease expiry', colour: P.slot(0), field: 'expiry' },
    { key: 'break', label: 'Tenant break', colour: P.slot(1), field: 'breakDate' },
    { key: 'review', label: 'Rent review', colour: P.slot(4), field: 'rentReview' },
  ]

  // Lease state, not raw fields: owned freeholds have no lease events.
  const leased = U.filter(u => D.leaseStateOf(u) !== 'owned')
  const EVENTS = []
  for (const u of leased) {
    for (const t of TYPES) {
      const iso = u[t.field]
      if (!iso) continue
      const d = new Date(String(iso).slice(0, 10) + 'T00:00:00Z')
      if (isNaN(d) || d < AS_AT || d >= END) continue
      EVENTS.push({ u, t, d, y: d.getUTCFullYear(), mo: d.getUTCMonth(), sf: u.size || 0 })
    }
  }
  EVENTS.sort((a, b) => a.d - b.d)

  // Busiest month by floorspace touched.
  const byMonth = new Map()
  for (const e of EVENTS) {
    const k = e.y * 12 + e.mo
    const c = byMonth.get(k) || { y: e.y, mo: e.mo, n: 0, sf: 0 }
    c.n++; c.sf += e.sf; byMonth.set(k, c)
  }
  const BUSY = [...byMonth.values()].sort((a, b) => b.sf - a.sf)[0] || null
  const BREAKS = EVENTS.filter(e => e.t.key === 'break')
  const WITH_ANY = leased.filter(u => TYPES.some(t => u[t.field])).length
  const MAX_SF = Math.max(1, ...EVENTS.map(e => e.sf))

  /* ------------------------------------------------------------ geometry
     Built in viewBox units from the MEASURED width (kit.useWidth). The TEXT
     FLOOR (>=10px rendered at ANY width) decides the box: at or above the
     1080 design width the chart draws in a 1080-unit box (text at or above
     its declared size); below it, it is laid out at ONE unit per pixel
     (W = the measured width), so an 11-unit label is 11px in a 700px column
     too — a fixed 1080 box there printed 7px labels. Below kit.COMPACT_PX (a
     phone) it also re-arranges: narrower cells, smaller circles, marks
     stacked down the cell. */
  const geometry = w => {
    const compact = w > 0 && w < COMPACT_PX
    const W = w > 0 && w < 1080 ? w : 1080
    // PT holds two header rows: "now" on top, the month names under it.
    const PL = compact ? 40 : 64, PT = compact ? 40 : 48, ROW = compact ? 56 : 70
    const CW = (W - PL - (compact ? 2 : 8)) / 12
    const rMin = compact ? 3 : 4, rMax = compact ? 8 : 13
    return {
      compact, W, PL, PT, ROW, CW, H: PT + SPAN * ROW + 8,
      R: sf => rMin + (rMax - rMin) * Math.sqrt(sf / MAX_SF),   // area-true
      step: compact ? 18 : 22,                                   // mark spacing
      lab: compact ? 10 : 11, yr: compact ? 11 : 12,
    }
  }

  /* One row per year: its own scroll window and its own hook calls.
     PRINT CONTRACT, as applied to this chart (storyline-engine.md §8):
       - every animated element is className "mv", and its motion is only a
         delta from the finished attributes (cx/cy/r are final; style adds
         opacity and scale) — print drops the delta;
       - a layer that exists only DURING the build (the sweep band in
         Calendar) is .screen-only, so print leaves it out — a plain .mv
         would print it at full strength. (Don't finish colour-
         coded marks dimmed: at .55 the midnight expiry dots read as the
         slate review colour and the encoding was lost.);
       - the busiest-month frame fades in: .mv, so it prints (an unmarked
         fade-in prints at whatever opacity scrolling left it: often 0);
       - labels that sit ON a mark say so (.onmark-dark below);
       - the live total is an SvgCounter (a live copy on screen, the final
         copy in print). */
  function YearRow({ yi, g, progress, reduced }) {
    const yr = Y0 + yi
    const a = 0.08 + yi * 0.1
    const o = useTransform(progress, [a, a + 0.22], [0, 1])
    const s = useTransform(progress, [a, a + 0.22], [0.4, 1])
    const frameO = useTransform(progress, [0.72, 0.84], [0, 1])
    const y = g.PT + yi * g.ROW
    const cells = []
    for (let mo = 0; mo < 12; mo++) {
      const evs = EVENTS.filter(e => e.y === yr && e.mo === mo)
      const past = yi === 0 && mo < M0
      const busiest = BUSY && BUSY.y === yr && BUSY.mo === mo
      // Pack left to right, then wrap down the cell: never overlap two marks.
      const per = Math.max(1, Math.floor((g.CW - 8) / g.step))
      const x0 = per === 1 ? g.PL + mo * g.CW + g.CW / 2 : g.PL + mo * g.CW + 14
      cells.push(html`
        <g key=${mo}>
          <rect x=${g.PL + mo * g.CW + 2} y=${y + 2} width=${g.CW - 4} height=${g.ROW - 4}
                fill=${past ? 'var(--wash)' : 'none'} stroke="var(--line)" strokeWidth="1" />
          ${busiest ? html`
            <${m.rect} className="mv" x=${g.PL + mo * g.CW + 1} y=${y + 1} width=${g.CW - 2} height=${g.ROW - 2}
              fill="none" stroke="var(--hot)" strokeWidth="2"
              style=${reduced ? undefined : { opacity: frameO }}>
              <title>Busiest month: ${BUSY.n} ${BUSY.n === 1 ? 'event' : 'events'}, ${F.fmt(BUSY.sf)} sq ft</title>
            <//>` : null}
          ${evs.map((e, i) => {
            const cx = x0 + (i % per) * g.step
            const cy = y + (g.compact ? 15 : 20) + Math.floor(i / per) * g.step
            // A motion component is a VALUE: <${m.circle}>…<//>. A bare
            // <m.circle> would be a literal (unknown) DOM tag.
            // The pivot is a px STRING from this render's geometry (§7 rule
            // 10): a numeric originX/originY is resolved against a box framer
            // measures once, and goes stale when the chart re-lays out.
            return html`
              <${m.circle} className="mv" key=${e.u.id + e.t.key} cx=${cx} cy=${cy} r=${g.R(e.sf)}
                fill=${e.t.colour} fillOpacity=".9" stroke="#fff" strokeWidth="1.2"
                style=${reduced ? undefined : { opacity: o, scale: s, originX: `${cx}px`, originY: `${cy}px` }}>
                <title>${e.t.label} · ${[e.u.short || e.u.name, e.u.town].filter(Boolean).join(', ')} · ${F.dmy(e.d.toISOString())} · ${F.fmt(e.sf)} sq ft</title>
              <//>`
          })}
        </g>`)
    }
    return html`
      <g>
        <text className="c-num" x=${g.PL - (g.compact ? 7 : 12)} y=${y + g.ROW / 2 + 4} textAnchor="end"
              style=${{ fontSize: g.yr }}>${yr}</text>
        ${cells}
      </g>`
  }

  /* progress: true (static scene) or a PinnedScene's progress. useChartProgress
     follows a pin's progress only while the stage is really pinned; anywhere
     else — a static scene, or a pin degraded on a phone — it runs from the
     chart's OWN box and is 1 once 70% of the chart has entered the viewport,
     so the reader never reads a half-grown chart. */
  function Calendar({ progress }) {
    const reduced = useReducedMotion()
    const box = useRef(null)
    const p = useChartProgress(box, progress)
    const g = geometry(useWidth(box))
    const rows = []
    for (let yi = 0; yi < SPAN; yi++) {
      rows.push(html`<${YearRow} key=${yi} yi=${yi} g=${g} progress=${p} reduced=${reduced} />`)
    }
    // The "now" rule sits on the as-at month and never moves with scroll:
    // a reference line that drifts reads as data. Its label is a tab in a
    // header row of its own above the month names (beside the rule it
    // straddled into the shaded past cell on a phone). The label sits ON the
    // ink tab, so it is .onmark-dark: white on paper too (print re-points the
    // ground tokens to ink, which would have printed it ink on ink).
    const nowX = g.PL + M0 * g.CW + g.CW * (AS_AT.getUTCDate() - 1) / 31
    const TW = 3 * g.lab * 0.74 + 12
    const tabX = Math.min(Math.max(nowX, g.PL + TW / 2), g.W - TW / 2)
    // The total counts up; it sits on the side away from "now".
    const totalAtLeft = nowX > g.W / 2
    // The sweep: a faint band that runs down the years as they build and
    // FINISHES HIDDEN. It exists only during the build, so it is .screen-only:
    // never printed. (Not .mv: print forces .mv to full strength, and QA reads
    // a .mv held at opacity 0 as a half-built chart.)
    const sweepO = useTransform(p, [0.04, 0.1, 0.62, 0.72], [0, 1, 1, 0])
    const sweepY = useTransform(p, [0.08, 0.62], [0, (SPAN - 1) * g.ROW])
    // .knock paints the live ground behind the plot, so the page's 12-column
    // grid overlay cannot read as extra gridlines through it. className
    // "chart" marks the chart ROOT (phone rules size roots, never icons).
    return html`
      <div ref=${box} className="knock">
      <svg className="chart" viewBox=${`0 0 ${g.W} ${g.H}`} style=${{ width: '100%' }} role="img"
           aria-label=${`Lease events by month for the next ${SPAN} years: ${EVENTS.length} events ` +
             `across ${WITH_ANY} leased units with at least one date recorded.`}>
        ${F.MONTHS.map((mn, i) => html`
          <text key=${mn} className="c-lab" x=${g.PL + i * g.CW + g.CW / 2} y=${g.PT - 12}
                textAnchor="middle" style=${{ fontSize: g.lab, letterSpacing: g.compact ? '.04em' : undefined }}>${mn}</text>`)}
        ${reduced ? null : html`<${m.rect} className="screen-only" x=${g.PL} y=${g.PT} width=${12 * g.CW} height=${g.ROW}
          fill="var(--hot)" fillOpacity=".07" style=${{ opacity: sweepO, y: sweepY }} />`}
        ${rows}
        <line x1=${nowX} x2=${nowX} y1=${g.PT - 4} y2=${g.PT + g.ROW} stroke="var(--ink)" strokeWidth="1.5" />
        <rect x=${tabX - TW / 2} y=${g.PT - 40} width=${TW} height="16" fill="var(--ink)" />
        <text className="c-lab onmark-dark" x=${tabX} y=${g.PT - 28} textAnchor="middle"
              style=${{ fontSize: g.lab, fill: '#FFFFFF' }}>now</text>
        <${SvgCounter} to=${EVENTS.length} from=${0.5} progress=${p}
          format=${n => `${F.fmt(n)} ${F.round(n) === 1 ? 'event' : 'events'}`}
          x=${totalAtLeft ? g.PL : g.W - 2} y=${g.PT - 28} textAnchor=${totalAtLeft ? 'start' : 'end'}
          className="c-num" style=${{ fontSize: g.lab }} />
      </svg>
      </div>`
  }

  /* --------------------------------------------------------------- scene */
  function LeaseCalendar({ id = 'calendar' }) {
    const busyLine = BUSY
      ? `The busiest month is ${F.MONTHS[BUSY.mo]} ${BUSY.y}: ${BUSY.n} ${BUSY.n === 1 ? 'event' : 'events'} touching ${F.fmt(BUSY.sf)} sq ft.`
      : ''
    const breakLine = BREAKS.length === 1
      ? ' One is a tenant break — an option that lapses if nobody diarises it.'
      : BREAKS.length > 1
        ? ` ${F.Words(BREAKS.length)} are tenant breaks — options that lapse if nobody diarises them.`
        : ''
    return html`
      <${Scene} id=${id} mode="light">
        <${Reveal} as="h2" className="scene-h wide">
          ${F.Words(EVENTS.length)} lease events in the next ${F.words(SPAN)} years. Every one of them is a date to prepare for.
        <//>
        <${Reveal} delay=${0.08}>
          <p className="scene-sub wide">${busyLine}${breakLine}</p>
        <//>
        <div style=${{ marginTop: 36 }}>
          <${Calendar} progress=${true} />
        </div>
        <${BandKey} items=${TYPES} />
        <${Prov}>${WITH_ANY} of ${leased.length} leased units carry at least one dated event · circle area by floorspace<//>
        <${Rows} label="Events in the next twelve months"
          rows=${EVENTS.filter(e => e.d < Date.UTC(Y0 + 1, M0, AS_AT.getUTCDate())).map(e => ({ ...e.u, id: e.u.id + e.t.key, _e: e }))}
          value=${r => `${r._e.t.label} · ${F.dmy(r._e.d.toISOString())}`}
          noun=${['event', 'events']} />
      <//>`
  }

  /* ---------------------------------------------------- standalone mount */
  Story.mount(() => html`
    <${Shell} scenes=${[{ id: 'calendar', label: 'Lease calendar' }]}>
      <${LeaseCalendar} id="calendar" />
    <//>`)
})()
