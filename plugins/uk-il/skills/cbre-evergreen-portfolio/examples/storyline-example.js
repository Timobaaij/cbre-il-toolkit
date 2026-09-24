/* storyline-example.js — a complete eleven-scene storyline, written as a
   classic script against window.Story. This is the reference build of the
   CBRE portfolio storyline: copy it to report/story.js, then cut, reorder,
   rewrite and invent.

   HARD RULE it demonstrates: the file holds NO client facts. Every number,
   name and ranking below is computed from Story.units / Story.meta when the
   page opens ("the largest single building", "the landlord with the most
   floorspace expiring by <year>" ...). Copy may carry a voice; it may not
   carry a figure. If a scene's premise is not true of this portfolio, its
   `use` flag drops it and the rail follows automatically.

   Motion: a chart given progress=${true} grows as it scrolls into view and is
   finished once 70% of it has entered; inside a PinnedScene pass the pin's
   progress instead (followed only while the stage is actually pinned — on a
   phone the pin degrades and the chart drives itself). Never hand a static
   chart a section-wide progress: it would still be growing while read.
   Print needs nothing from this file: the kit's charts, Reveal and Counter
   print finished. Anything you animate yourself needs className "mv" (see
   new-scene-example.js and reference/storyline-engine.md §7 rule 10).

   Syntax: htm tagged templates (Story.html) — see reference/storyline-engine.md.
   Unicode characters, never HTML entities: htm does not decode &rsquo; etc.
   Never break a line directly after ${…} or a closing tag when the next line
   starts with text, or directly before ${…} / <b> after text: htm drops
   whitespace that contains a newline at those joins and the words fuse. */
(function () {
  'use strict'

  const { html, kit, charts, fmt: F, data: D, palette, geo } = Story
  const {
    Shell, Scene, PinnedScene, Reveal, Prov, Rows, HeroStat, BandKey,
    Appendix, CTA, Credits,
  } = kit
  const {
    Constellation, CompanyKey, GroupBars, LandlordTree, ExpiryTimeline, CoverageGrid,
    EpcStack, RentScatter, COVERAGE_BANDS, COVERAGE_FLAG,
  } = charts

  /* ================================================================ DATA
     Every rollup is computed once, here, never inside a component. A null is
     a null: nothing substitutes 0 for "not recorded", and every aggregate
     keeps its own denominator so a caption can never overstate its base. */
  const U = Story.units
  const META = Story.meta
  const N = U.length
  const TOTAL = D.sum(U)
  const NOW_Y = D.asAt().getUTCFullYear()
  const CLIENT = META.client || 'The client'
  // The short name for running prose ("what X rents"): meta.clientShort, the
  // same field the dashboard uses, then the older meta.short, else "Acme
  // Group" -> "Acme".
  const WHO = META.clientShort || META.short || CLIENT.replace(/\s+(Group|Holdings|plc|PLC|Ltd|Limited)$/, '')
  const SOURCE = META.source || 'EverGreen export'
  const EXPORTED = F.dLong(META.exportDate || META.asAt)
  const bySize = rows => D.sortBy(rows, 'size', 'desc')
  const units = n => (n === 1 ? 'unit' : 'units')
  const buildings = n => (n === 1 ? 'building' : 'buildings')

  // Lease state is ONE vocabulary (units.json leaseState, or derived for older
  // files): 'running' | 'not started' | 'passed' | 'undated' | 'owned'.
  // A lease that starts after the as-at date is NOT running: it never counts
  // towards WAULT or any "unexpired" figure.
  const state = u => D.leaseStateOf(u)
  const leased = U.filter(u => state(u) !== 'owned')
  const owned = U.filter(u => state(u) === 'owned')
  const LEASED_SF = D.sum(leased)
  const OWNED_SF = D.sum(owned)

  // Groups: slot 1 of the palette goes to the largest. The categorical slots
  // carry no meaning; pale ones need their edge on light grounds.
  const GROUP_KEYS = D.groupBy(U, 'group').map(g => g.key)
  const GC = palette.assign(GROUP_KEYS)
  const GE = palette.assignEdges(GROUP_KEYS)
  const groups = D.groupBy(U, 'group').map(g => ({ ...g, colour: GC[g.key], edge: GE[g.key] }))
  const [G1, G2] = groups
  // Prose name: a "Parent / Brand" record reads "Parent/Brand"; else the key.
  const gName = u => {
    const f = u && u.groupFull
    return f && f.includes('/') ? f.replace(/\s*\/\s*/g, '/') : (u && u.group) || ''
  }
  const byGroupColour = u => GC[u.group] || 'var(--oc-other)'

  // Geography: the region holding the most units, the busiest road corridor,
  // and the largest clusters (parks) on that corridor.
  const placed = U.filter(geo.placeable)
  const REG = D.groupBy(U, 'region', { sort: 'n' })[0]
  const COR = D.groupBy(U, 'corridor', { sort: 'n' })[0]
  const PARKS = COR ? D.groupBy(COR.rows, 'park', { sort: 'n' }).filter(p => p.n >= 2) : []

  // Landlords — LEASED ONLY. EverGreen leaves a landlord value on freeholds
  // the client owns; counting them credits the client's own property to a
  // landlord and inflates every concentration claim.
  // And THIRD-PARTY only: a lease from a group company is not counterparty
  // exposure. The dashboard measures concentration on the same base, so the two
  // views print the same share.
  const thirdParty = leased.filter(u => u.landlord && !u.landlordIntra)
  const THIRD_SF = D.sum(thirdParty)
  const LANDLORDS = D.groupBy(thirdParty, 'landlord')
  const TOPN = Math.min(6, LANDLORDS.length)        // an editorial choice, not a fact
  const TOP = LANDLORDS.slice(0, TOPN)
  const TOP_SF = D.sum(TOP.flatMap(l => l.rows))
  const TOP_UNITS = TOP.reduce((a, l) => a + l.n, 0)
  const TOP_PCT = F.pct(TOP_SF, THIRD_SF)

  // Lease events.
  const dated = U.filter(u => u.expiry)                  // an expiry is recorded
  const live = U.filter(D.isRunning)                     // running leases only
  const lapsed = D.byLeaseState(U, 'passed')
  const notStarted = D.byLeaseState(U, 'not started')
  const LIVE_SF = D.sum(live)
  const WAULT = D.wavg(live, 'yearsToExpiry')
  const noExpiryLeased = D.byLeaseState(U, 'undated')
  // Calendar years of expiry (a late-2027/early-2028 cliff stays one column),
  // plus the undated block the timeline shows detached and hatched.
  const EXP = D.expiryByYear(U)
  const YEARS = EXP.years
  // The hero year: the heaviest expiry year in the next five.
  const HOT = D.sortBy(YEARS.filter(y => y.year <= NOW_Y + 4), 'sf', 'desc')[0] || null
  const NEXT = HOT ? YEARS.find(y => y.year === HOT.year + 1) || null : null
  const BY = HOT ? HOT.year + 2 : null
  // The landlord with the most floorspace expiring by BY.
  const LL = HOT ? D.groupBy(live.filter(u => F.year(u.expiry) <= BY), 'landlord')[0] || null : null
  const LL_ROWS = LL ? leased.filter(u => u.landlord === LL.key) : []
  const LL_SF = D.sum(LL_ROWS)

  // Rent.
  const rented = U.filter(u => u.rent)
  const RENT_SF = D.sum(rented)
  const RENT_WAVG = D.wavg(rented, 'rent')
  const rentPlot = rented.filter(u => u.dealYear)

  // EPC. MEES scope: the government's interim response (June 2026) sets EPC B
  // for let non-domestic buildings over 1,000 m² from 2031, where
  // cost-effective. Owned freeholds are not let, so sit outside.
  const MEES_MIN_SF = 1000 * D.SQFT_PER_SQM
  const scope = leased.filter(u => u.size >= MEES_MIN_SF)
  const epcRated = scope.filter(u => u.epc)
  const epcNone = scope.filter(u => !u.epc)
  const epcBplus = scope.filter(u => /^[AB]/.test(u.epc || ''))
  const epcBelow = scope.filter(u => /^[C-G]/.test(u.epc || ''))
  const epcAll = U.filter(u => u.epc)
  const grades = D.uniq(epcBelow.map(u => u.epc[0])).sort()
  const belowLabel = grades.length <= 1 ? (grades[0] || 'Below B')
    : grades.length === 2 ? grades.join(' or ') : `${grades[0]} to ${grades[grades.length - 1]}`
  // Worked example: the in-scope unit with the lowest EPC and the soonest
  // live expiry — the one where the rating and the renewal collide first.
  const WORST = epcBelow.filter(D.isRunning)
    .sort((a, b) => b.epc.localeCompare(a.epc) || a.expiry.localeCompare(b.expiry))[0] || null

  // Cold storage (recorded true only; null is "not recorded", not "no").
  const cold = U.filter(u => u.coldStore === true)
  const COLD_SF = D.sum(cold)
  const coldBy = D.groupBy(cold, 'group', { sort: 'n' })
  const noCold = groups.find(g => !g.rows.some(u => u.coldStore === true)) || null

  // The single building: the largest, and whether it is also the longest
  // certainty (most floorspace-years to run) in the estate.
  const BIG = bySize(U)[0] || null
  const CERTAIN = live.filter(u => u.yearsToExpiry > 0)
    .sort((a, b) => b.size * b.yearsToExpiry - a.size * a.yearsToExpiry)[0] || null
  const RECENT = rented.filter(u => u.dealDate)
    .sort((a, b) => b.dealDate.localeCompare(a.dealDate) || b.rent - a.rent)[0] || null

  /* ============================================================== SCENES */

  /* 1 · OPENING — "a big number, and the catch in it". The headline figure
     rounded to words, then the share that qualifies it, over the full map.
     Always usable; if almost nothing is leased, the catch changes. */
  function Opening({ id }) {
    const share = TOTAL ? LEASED_SF / TOTAL : 0
    return html`
      <${Scene} id=${id} mode="dark" className="lead">
        <div className="two">
          <div>
            <${Reveal} as="h1" className="opening">
              ${F.cap(F.magnitude(TOTAL))} square feet.${' '}
              <em>${share >= 0.05 ? `${F.cap(F.fraction(share))} of it on somebody else’s terms.`
                : 'Almost all of it on its own terms.'}</em>
            <//>
            <${Reveal} delay=${0.12}>
              <p className="scene-sub">
                ${F.Words(N)} ${buildings(N)} across the United Kingdom${groups.length > 1 ? `, run by ${F.words(groups.length)} operating companies` : ''}. ${CLIENT} owns <b>${owned.length ? F.words(owned.length) : 'none'}</b> of them.
              </p>
              <${Prov}>${placed.length} of ${N} units<//>
            <//>
          </div>
          ${placed.length ? html`
            <${Reveal} delay=${0.05}>
              <${Constellation} units=${U} height="66svh"
                colour=${u => (state(u) === 'not started' ? 'var(--sem-unknown)' : byGroupColour(u))}
                form=${u => (state(u) === 'not started' ? 'dash' : 'fill')}
                ariaLabel=${`All ${N} ${CLIENT} units plotted across the United Kingdom, ` +
                  'circle area proportional to floorspace. ' +
                  groups.map(g => `${g.key}: ${g.n}`).join('; ') + '.' +
                  (notStarted.length ? ` ${notStarted.length} signed but not yet started, drawn as dashed rings.` : '')} />
              ${/* group = colour, state = FORM: a not-started unit is a dashed ring
                   in --sem-unknown (design-system §3e), keyed below with the same
                   form; its group stays in its tooltip */ ''}
              ${groups.length > 1 || notStarted.length ? html`<${CompanyKey} items=${[
                ...(groups.length > 1 ? groups : []),
                ...(notStarted.length ? [{ key: 'not-started', label: 'Signed, not yet started', n: notStarted.length,
                                           colour: 'var(--sem-unknown)', form: 'dash' }] : []),
              ]} />` : ''}
            <//>` : ''}
        </div>
      <//>`
  }

  /* 2 · WHO RUNS IT — "two names carry most of it". Ranked bars by group.
     Skip with a single group; with 10+ groups fold the tail into "Other"
     first (the palette has eight slots). */
  function Companies({ id }) {
    const rest = groups.length - 2
    const tail = rest > 1 ? `The remaining ${F.words(rest)} share the rest — but a landlord does not care which of them signed.`
      : rest === 1 ? 'The last holds the rest — but a landlord does not care which of them signed.'
      : 'A landlord does not care which of them signed.'
    return html`
      <${Scene} id=${id} mode="light">
        <${Reveal} as="h2" className="scene-h">${F.Words(groups.length)} operating companies. One property position.<//>
        <${Reveal} delay=${0.08}>
          <p className="scene-sub">
            ${gName(G1.rows[0])} runs <b>${G1.n} ${units(G1.n)}</b> and ${F.fmt(G1.sf)} sq ft. ${gName(G2.rows[0])} runs <b>${G2.n}</b> and ${F.fmt(G2.sf)}. Between them that is <b>${F.pct(G1.sf + G2.sf, TOTAL)}%</b> of the estate. ${tail}
          </p>
        <//>
        <${Reveal} delay=${0.12}>
          <div style=${{ marginTop: 44 }}>
            <${GroupBars} rows=${groups} progress=${true}
              ariaLabel=${'Floorspace by operating company. ' + groups.map(g =>
                `${g.key}: ${F.fmt(g.sf)} square feet across ${g.n} ${units(g.n)}`).join('; ')} />
          </div>
        <//>
      <//>`
  }

  /* 3 · CONCENTRATION — "where it clusters", a pinned zoom into the densest
     region with the busiest corridor lit. Skip when fewer than ~10 units
     carry coordinates or no region holds a real cluster (3+ units). */
  function Cluster({ id }) {
    let parkLine = ''
    const [P1, P2] = PARKS
    if (P1) {
      const let1 = P1.rows.filter(u => state(u) !== 'owned')
      const lls = D.uniq(let1.map(u => u.landlord))
      const same = lls.length === 1 && let1.length === P1.n ? 'all with the same landlord'
        : lls.length === 1 && let1.length >= 2 ? `${F.words(let1.length)} of them let by the same landlord`
        : `across ${F.words(lls.length)} landlords`
      parkLine = `${F.Words(P1.n)} are at ${P1.key}, ${same}. ` +
        (P2 ? `${F.Words(P2.n)} are at ${P2.key}. ` : '')
    }
    const inFocus = u => u.region === REG.key || (COR && u.corridor === COR.key)
    return html`
      <${PinnedScene} id=${id} mode="dark" viewports=${3.2}>
        ${({ progress }) => html`
          <div className="two">
            <div>
              <h2 className="scene-h">${F.Words(REG.n)} of the ${F.words(N)} sit in ${F.the(REG.key)}.</h2>
              <p className="scene-sub">
                ${COR ? html`<><b>${COR.n} ${units(COR.n)}</b> sit on the ${COR.key} alone. <//>` : ''}${parkLine}Concentration is efficient right up to the moment it isn’t.
              </p>
              <${Prov}>${REG.n} of ${N} units in ${F.the(REG.key)}<//>
            </div>
            <${Constellation} units=${U} progress=${progress} view="zoom" height="74svh"
              colour=${byGroupColour} focus=${inFocus} zoomOn=${u => u.region === REG.key}
              ariaLabel=${`The ${N} units, zooming into ${F.the(REG.key)}.`} />
          </div>`}
      <//>`
  }

  /* 4 · WHAT IS OWNED — "the part with no renewal date". Freeholds lit on
     the map, the list one click away. Skip when nothing is owned; when
     everything is, this is the whole story and the landlord scenes go. */
  function Freeholds({ id }) {
    return html`
      <${Scene} id=${id} mode="deep">
        <div className="two">
          <div>
            <h2 className="scene-h">${F.Words(owned.length)} ${owned.length === 1 ? 'building answers' : 'buildings answer'} to no one.</h2>
            <${Reveal} delay=${0.06}>
              <p className="scene-sub">
                <b>${F.fmt(OWNED_SF)} sq ft</b> held freehold — ${F.pct(OWNED_SF, TOTAL)}% of the estate, and the only part of it with no renewal date attached. Everything that follows is about the other ${F.pct(LEASED_SF, TOTAL)}%.
              </p>
              <${Rows} label="Owned freehold" rows=${bySize(owned)} />
            <//>
          </div>
          ${placed.length ? html`
            <${Reveal} delay=${0.04}>
              <${Constellation} units=${U} height="68svh" focus=${u => state(u) === 'owned'}
                colour=${u => (state(u) === 'owned' ? 'var(--hot)' : 'var(--sage)')}
                ariaLabel=${`${owned.length} owned freeholds highlighted among ${N} units.`} />
            <//>` : ''}
        </div>
      <//>`
  }

  /* 5 · COUNTERPARTY CONCENTRATION — "a few landlords hold most of it", a
     pinned treemap with the top holders as figure. Leased units only. Skip
     with fewer than ~4 landlords, or when the top six hold under a third
     (then the story is fragmentation, and a different chart). */
  function Landlords({ id }) {
    return html`
      <${PinnedScene} id=${id} mode="soft" viewports=${3.4}>
        ${({ progress }) => html`<>
          <h2 className="scene-h wide">${LANDLORDS.length} landlords. ${F.Words(TOPN)} of them hold ${F.share(TOP_SF, THIRD_SF)} of what ${WHO} rents.</h2>
          <p className="scene-sub wide">
            ${TOP.map(l => F.llShort(l.key)).join(', ')} — together <b>${F.fmt(TOP_SF)} sq ft</b> across <b>${TOP_UNITS} units</b>, or <b>${TOP_PCT}%</b> of the ${F.msf(THIRD_SF)} sq ft ${WHO} leases from third parties. ${F.Words(TOPN)} conversations cover ${TOP_PCT > 50 ? 'most of the estate' : 'a large part of it'}. So does ${F.words(TOPN)} counterparties’ risk.
          </p>
          <div style=${{ marginTop: 30 }}>
            <${LandlordTree} rows=${LANDLORDS} highlight=${TOPN} progress=${progress}
              ariaLabel=${`Floorspace by landlord, leased units only. The ${F.words(TOPN)} largest hold ` +
                `${F.fmt(TOP_SF)} square feet, ${TOP_PCT} per cent of the floorspace leased from third parties, across ` +
                `${TOP_UNITS} units of ${LANDLORDS.length} landlords.`} />
          </div>
          <${Prov} wide>leased units only · the ${owned.length} freeholds ${WHO} owns are excluded<//>
        <//>`}
      <//>`
  }

  /* 6 · THE HERO — "the average hides a cliff". WAULT as the foil, then the
     heaviest expiry year of the next five, named on a leader, and the one
     landlord most exposed by two years later. Needs ~5+ live dated leases;
     skip when no year in the next five carries a material share. */
  function Expiry({ id }) {
    return html`
      <${PinnedScene} id=${id} mode="light" viewports=${4}>
        ${({ progress }) => html`<>
          <h2 className="scene-h" style=${{ maxWidth: '26ch' }}>
            The average lease has ${F.fixed(WAULT, 1)} years to run. The average is not the problem.
          </h2>
          <p className="scene-sub" style=${{ maxWidth: '70ch' }}>
            <b>${F.fmt(HOT.sf)} sq ft</b> falls due in ${HOT.year} across ${HOT.n} ${buildings(HOT.n)}. ${NEXT ? `Another ${F.fmt(NEXT.sf)} in ${NEXT.year}. ` : ''}${LL ? html`<>${F.llShort(LL.key)} alone has <b>${F.fmt(LL.sf)} sq ft</b> — ${F.pct(LL.sf, LL_SF)}% of everything it holds — reaching expiry by ${BY}.<//>` : ''}
          </p>
          <div style=${{ marginTop: 26 }}>
            <${ExpiryTimeline} years=${YEARS} undated=${EXP.undated} highlightYear=${HOT.year} progress=${progress}
              notStarted=${EXP.notStarted} from=${Math.min(NOW_Y, YEARS[0].year)} />
          </div>
          ${/* key only the forms that are drawn: dashed = signed, not started
               (never in the running figure), hatched = no expiry recorded */ ''}
          ${EXP.notStarted.years.length || EXP.undated.n ? html`<${BandKey} style=${{ marginTop: 10 }} items=${[
            { label: 'Running lease', colour: 'var(--sage)' },
            ...(EXP.notStarted.years.length ? [{ label: 'Signed, not yet started', form: 'dash', colour: palette.semantic.unknown }] : []),
            ...(EXP.undated.n ? [{ label: 'No expiry recorded', form: 'hatch' }] : []),
          ]} />` : ''}
          <${Prov}>${live.length} running leases with a recorded date · ${F.fmt(LIVE_SF)} sq ft of ${F.fmt(TOTAL)}${EXP.notStarted.n ? ` · ${EXP.notStarted.n} not yet started, dashed, not counted` : ''}<//>
        <//>`}
      <//>`
  }

  /* 7 · THE GAPS — "what the data cannot say", one cell per unit filling in
     passes and refusing to finish. Always worth keeping: it is the honesty
     scene. Reword the headline if rent coverage is high (80%+). */
  function Gaps({ id }) {
    return html`
      <${PinnedScene} id=${id} mode="light" ground="light" viewports=${3.6}>
        ${({ progress }) => html`
          <div className="two">
            <div>
              <h2 className="scene-h">We can price ${F.pct(RENT_SF, TOTAL)}% of the floorspace. We are not going to guess the rest.</h2>
              <p className="scene-sub">
                Rent is recorded on <b>${rented.length} of ${N}</b> buildings. A lease expiry on <b>${dated.length}</b>. An EPC on <b>${epcAll.length}</b>. <b>${lapsed.length}</b> recorded expiries have already passed, and <b>${noExpiryLeased.length} leased buildings</b> carry no expiry date at all.${notStarted.length ? ` ${F.Words(notStarted.length)} ${notStarted.length === 1 ? 'lease has' : 'leases have'} been signed but not yet started, so ${notStarted.length === 1 ? 'it counts' : 'they count'} in no average.` : ''}
              </p>
              <p className="scene-sub aside">
                Every empty cell is a question we can answer for you. None of them is a zero.
              </p>
              <${Rows} label="Leased, no expiry recorded" rows=${bySize(noExpiryLeased)}
                value=${r => r.landlord || 'n/r'} />
            </div>
            <div>
              <${CoverageGrid} units=${U} progress=${progress}
                ariaLabel=${`${N} cells, one per unit, ordered by floorspace. Rent is recorded on ` +
                  `${rented.length}, a lease expiry on ${dated.length}, an EPC on ${epcAll.length}. ` +
                  `${lapsed.length} units whose recorded expiry has already passed are marked. ` +
                  'The rest stay empty.'} />
              <${BandKey} items=${[...COVERAGE_BANDS, COVERAGE_FLAG]} />
              <${Prov} bare style=${{ marginTop: 14 }}>One cell per unit, ordered by floorspace · three bands per cell<//>
            </div>
          </div>`}
      <//>`
  }

  /* 8 · THE IRREPLACEABLE — "a capability, not a floor area": the units with
     a specialist feature (here cold storage) lit on the map. Skip when fewer
     than 3 units carry the flag, or when the flag is recorded on so few units
     that "none" cannot be told from "not recorded". */
  function Cold({ id }) {
    // "two flip": the map sits left on desktop; once stacked, the headline
    // must come before it.
    return html`
      <${Scene} id=${id} mode="midnight">
        <div className="two flip">
          ${placed.length ? html`
            <${Reveal}>
              <${Constellation} units=${U} height="66svh" focus=${u => u.coldStore === true}
                colour=${u => (u.coldStore === true ? 'var(--celadon)' : 'var(--sage)')}
                ariaLabel=${`${cold.length} units with recorded cold storage highlighted among ${N}.`} />
            <//>` : html`<div />`}
          <div>
            <${Reveal} as="h2" className="scene-h">${F.Words(cold.length)} buildings keep stock cold. They are the hardest ones to replace.<//>
            <${Reveal} delay=${0.08}>
              <p className="scene-sub">
                <b>${F.fmt(COLD_SF)} sq ft</b> of recorded cold storage — ${coldBy.map(g => `${F.words(g.n)} ${g.key}`).join(', ')}.${noCold ? ` ${gName(noCold.rows[0])}’s ${noCold.n} ${units(noCold.n)} and ${F.msf(noCold.sf)} sq ft record none.` : ''} The group’s hardest capability to move sits in <b>${F.pct(COLD_SF, TOTAL)}%</b> of the floorspace.
              </p>
              <p className="scene-sub" style=${{ fontSize: 17 }}>
                Square feet are fungible. A chilled facility with the power and the racking already in it is not. Treat these ${F.words(cold.length)} as immovable and plan the rest around them.
              </p>
              <${Rows} label="Cold storage recorded" rows=${bySize(cold)}
                value=${r => `${r.group} · ${F.fmt(r.size)} sq ft`} />
            <//>
          </div>
        </div>
      <//>`
  }

  /* 9 · REGULATION — "a deadline most units cannot yet evidence": a single
     part-of-whole bar over the MEES scope (it totals its own segments, never
     the estate) and one worked example. Skip outside England & Wales, or
     with fewer than ~5 leased units over 1,000 m². */
  function Epc({ id }) {
    const segments = [
      { label: 'B or better', n: epcBplus.length, colour: palette.semantic.secure },
      { label: belowLabel, n: epcBelow.length, colour: palette.semantic.risk },
      { label: 'No EPC on record', n: epcNone.length, colour: 'var(--not-rec)', form: 'hatch' },
    ]
    // EpcStack: labels="key" (the default) draws the same key on every screen
    // and in print; labels="inline" only when every label fits its segment.
    // format="sqft" | "pct" | fn prints n as floorspace or a share instead of
    // a count; a segment can take form 'dash' (not started) or 'outline'.
    const worked = WORST ? html`<> ${WORST.town} is the worked example: ${F.fmt(WORST.size)} sq ft, <b>EPC ${WORST.epc}</b>, lease ending ${F.my(WORST.expiry)}. ${F.year(WORST.expiry) < 2031
      ? 'Any renewal runs past 2031, so the upgrade belongs in the deal.'
      : 'The lease already runs past 2031, so the upgrade is due inside it.'}<//>` : ''
    return html`
      <${Scene} id=${id} mode="soft">
        <${Reveal} as="h2" className="scene-h">
          From 2031, let buildings over 1,000${' '}m² are set to need an EPC of B. ${F.Words(epcBplus.length)} of ${F.words(scope.length)} can prove it.
        <//>
        <${Reveal} delay=${0.08}>
          <p className="scene-sub wide">
            Only ${epcRated.length} of the <b>${scope.length} leased units in scope</b> carry an EPC at all. <b>${epcNone.length} are unrated</b> — not failing, unmeasured.${worked} That is leverage, but only if you know about it first.
          </p>
          <p className="scene-sub aside">
            Confirmed as a target in the government’s interim response of June 2026, where cost-effective; the detail is still to come. Until then the minimum is EPC E.
          </p>
        <//>
        <${Reveal} delay=${0.12}>
          <div style=${{ marginTop: 42, maxWidth: 880 }}>
            <${EpcStack} segments=${segments} progress=${true}
              ariaLabel=${`Of ${scope.length} leased units over 1,000 square metres, ${epcBplus.length} are ` +
                `evidenced at EPC B or better, ${epcBelow.length} are ${belowLabel}, and ` +
                `${epcNone.length} have no EPC on record.`} />
          </div>
        <//>
        <${Reveal} delay=${0.16}>
          <${Rows} label="Leased over 1,000 m², no EPC on record" rows=${bySize(epcNone)}
            value=${r => `${F.fmt(r.size)} sq ft`} />
        <//>
      <//>`
  }

  /* 10 · ONE BUILDING — "the single asset that moves the total": a hero
     numeral counting up, then its rent against every recorded deal. Skip the
     scatter (keep the numeral) when fewer than ~8 units carry both a rent
     and a deal year; skip the scene when no unit is over ~5% of the estate. */
  function OneBuilding({ id }) {
    const expY = BIG.expiry ? F.year(BIG.expiry) : null
    const claim = CERTAIN && CERTAIN.id === BIG.id
      ? 'the longest certainty in the estate, and the largest single building in it'
      : 'the largest single building in the estate'
    const tenure = state(BIG) === 'owned' ? 'held freehold' : `landlord ${F.llShort(BIG.landlord) || 'not recorded'}`
    return html`
      <${Scene} id=${id} mode="deep">
        <div className="two">
          <div>
            <${Reveal}>
              <h2 className="scene-h" style=${{ marginBottom: 30 }}>One building.</h2>
              <${HeroStat} value=${BIG.size} unit="square feet">
                ${BIG.short}, ${BIG.town}. ${gName(BIG)}, ${tenure}. ${BIG.rent && BIG.dealYear ? html`<>Signed in ${BIG.dealYear} at <b>${F.gbp(BIG.rent)} per sq ft</b>, <//>` : ''}${expY ? `running to ${expY} — ${claim}.` : `${F.cap(claim)}.`}
              <//>
              <${Prov}>1 of ${N} units<//>
            <//>
          </div>
          <${Reveal} delay=${0.08}>
            ${RECENT && BIG.rent ? html`
              <p className="scene-sub" style=${{ marginTop: 0 }}>
                The most recent rent recorded anywhere in this portfolio is <b>${F.gbp(RECENT.rent)}</b>, struck in ${RECENT.dealYear}. ${BIG.town} sits at ${F.gbp(BIG.rent)}, struck in ${BIG.dealYear}. Nothing has to happen until the review — but when it does, on ${F.fmt(BIG.size)} sq ft, every pound of reversion is roughly <b>£${F.fixed(BIG.size / 1e6, 2)}m a year</b>.
              </p>` : ''}
            ${rentPlot.length >= 8 ? html`<>
              <div style=${{ marginTop: 34 }}>
                <${RentScatter} rows=${rentPlot} progress=${true} colour=${byGroupColour}
                  average=${RENT_WAVG} maxSize=${BIG.size} />
              </div>
              <${Prov}>the ${rentPlot.length} units with both a rent and a usable deal date<//>
            <//>` : ''}
          <//>
        </div>
      <//>`
  }

  /* 11 · CLOSING — "the findings are one conversation": restate the three
     numbers, give ONE instruction, hand over to the dashboard. Always keep a
     closing; rebuild its parts from whichever scenes survived. */
  function Closing({ id }) {
    const parts = []
    if (HOT) parts.push(html`<><b>${F.fmt(HOT.sf + (NEXT ? NEXT.sf : 0))} sq ft</b> reaching expiry in ${NEXT ? `${HOT.year} and ${NEXT.year}` : HOT.year}.<//>`)
    if (TOPN >= 3) parts.push(html`<><b> ${F.Words(TOPN)} landlords</b> holding ${TOP_PCT}% of what ${WHO} rents.<//>`)
    if (epcNone.length) parts.push(html`<><b> ${epcNone.length} leased buildings</b> with no energy rating.<//>`)
    const years = HOT ? (NEXT ? NEXT.year : HOT.year) - NOW_Y + 1 : 4
    return html`
      <${Scene} id=${id} mode="dark">
        <${Reveal} as="h2" className="closing">
          The next ${F.words(years)} years decide the shape of this estate.
        <//>
        <${Reveal} delay=${0.1}>
          <p className="scene-sub wide">
            ${parts.map((p, i) => html`<${Story.Fragment} key=${i}>${p}<//>`)} Those are not ${F.words(parts.length)} problems. They are one conversation, and it is already in the diary.
          </p>
        <//>
        <${Reveal} delay=${0.16}>
          ${LL ? html`<>
            <p className="instruct">Start with ${F.llShort(LL.key)} and the ${HOT.year} ${F.words(HOT.n)}.</p>
            <p className="scene-sub">
              ${LL_ROWS.length} ${units(LL_ROWS.length)}, ${F.fmt(LL_SF)} sq ft, ${F.pct(LL.sf, LL_SF)}% of it expiring by ${BY} ${LL.n === 1 ? 'in a single negotiation' : `across ${F.words(LL.n)} separate negotiations`}. Run it as one.
            </p>
          <//>` : ''}
          <${CTA}>Open the portfolio dashboard →<//>
        <//>
      <//>`
  }

  /* ============================================================ THE PLAN
     Order, rail labels and the `use` test for each scene. A scene whose
     premise is not true of this portfolio is dropped here, and the rail
     follows. Labels are short; they are the rail's screen-reader text. */
  const PLAN = [
    { id: 's1', label: F.cap(F.magnitude(TOTAL)), use: N > 0, view: Opening },
    { id: 's2', label: `${F.Words(groups.length)} companies`, use: groups.length >= 2, view: Companies },
    { id: 's3', label: REG && /Midlands/.test(REG.key) ? 'The golden triangle' : (REG ? REG.key : ''),
      use: !!REG && REG.n >= 3 && placed.length >= 10, view: Cluster },
    { id: 's4', label: `The ${F.words(owned.length)}`, use: owned.length > 0, view: Freeholds },
    { id: 's5', label: `${F.Words(TOPN)} landlords`, use: LANDLORDS.length >= 4, view: Landlords },
    { id: 's6', label: HOT ? String(HOT.year) : '', use: !!HOT && live.length >= 5 && WAULT != null, view: Expiry },
    { id: 's7', label: 'What we don’t know', use: N > 0, view: Gaps },
    { id: 's8', label: 'Cold storage', use: cold.length >= 3, view: Cold },
    { id: 's9', label: 'EPC B by 2031', use: scope.length >= 5, view: Epc },
    { id: 's10', label: BIG ? BIG.town || 'One building' : '', use: !!BIG && BIG.size > 0.03 * TOTAL, view: OneBuilding },
    { id: 's11', label: 'What happens next', use: N > 0, view: Closing },
  ].filter(s => s.use)

  /* ============================================================ APPENDIX
     The full record behind every figure; n/r = not recorded, — = n/a. */
  const NOTE = `The full record behind every figure on this page. Where a field was not recorded in the source it shows as “n/r” and is excluded from every average on this page — it is never treated as zero. “—” means the field does not apply: a freehold has no landlord and no expiry. “Regeared” is a lease renegotiated with the existing landlord rather than a new letting. Source: ${SOURCE}, ${EXPORTED}.` +
    // Caveats about the source that no unit field carries (e.g. "Landlord and
    // tenant fields are flagged unverified at source.") come from meta.json.
    (META.sourceNote ? ' ' + META.sourceNote : '')

  const FOOTER = html`
    <${Credits} summary=${`${N} units · ${F.fmt(TOTAL)} sq ft`}>
      <b>${CLIENT} — Portfolio Storyline.</b> Prepared by CBRE from an ${SOURCE} dated ${EXPORTED}. Every figure on this page is computed from that export and is reproducible from the appendix above. Rent is recorded on ${rented.length} of ${N} units and an EPC on ${epcAll.length} of ${N}; no figure has been extrapolated beyond the units that carry it. Landlord concentration is measured across leased units only.
    <//>`

  function App() {
    return html`
      <${Shell} scenes=${PLAN} footer=${FOOTER}>
        ${PLAN.map(s => html`<${s.view} key=${s.id} id=${s.id} />`)}
        <${Appendix} units=${U} note=${NOTE} />
      <//>`
  }

  Story.mount(App)
})()
