async function smoke(opts) {
  /* The post-fix smoke check (committees.md, Phase 5). NOT a QA round: it looks
     for breakage only (a script error, a storyline that did not render, an empty
     chart, a drawer that will not open, NaN on screen), never for polish.

     Returns { pass, viewport, problems: [...], checked: {...} }.
     Console errors are the caller's job: smoke.cjs collects them itself; over the
     Playwright MCP, read browser_console_messages (errors) after this returns.

     How to call
       Node Playwright:  node <skill>/scripts/smoke.cjs <file.html>   (both viewports)
       Playwright MCP (copy this file into <run>/qa/ first, serve the run folder):
         async () => { const s = await (await fetch('qa/smoke.js')).text();
                       return (0, eval)('(' + s + ')')({}); }
       at 1440x900, then browser_resize 390x844, reload, and call it again. */
  opts = opts || {};
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const problems = [], checked = {};
  const fail = (where, what) => problems.push(where + ': ' + what);
  const BAD = /\b(NaN|undefined|null|Infinity)\b|\[object Object\]/;
  const badText = (root, where) => {
    if (!root) return;
    const hits = new Set();
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const n = tw.currentNode, p = n.parentElement;
      if (!p || p.closest('script, style, noscript, template')) continue;
      const m = n.nodeValue.match(BAD);
      if (m) hits.add(m[0] + ' in "' + n.nodeValue.trim().slice(0, 60) + '"');
    }
    for (const el of root.querySelectorAll('[aria-label], [title]')) {
      for (const a of ['aria-label', 'title']) {
        const v = el.getAttribute(a), m = v && v.match(BAD);
        if (m) hits.add(m[0] + ' in ' + a + ' "' + v.slice(0, 60) + '"');
      }
    }
    [...hits].slice(0, 5).forEach(h => fail(where, 'bad text: ' + h));
  };
  const sideways = where => {
    const w = document.documentElement.scrollWidth;
    if (w > innerWidth + 1) fail(where, 'page scrolls sideways at ' + innerWidth + 'px (' + w + 'px wide)');
  };
  const go = async v => {
    try { if (window.__setView) window.__setView(v); else location.hash = v === 'dash' ? '#dash' : '#story'; }
    catch (e) { fail(v, 'opening this view threw: ' + e.message); }
    await wait(v === 'dash' ? 1500 : 500);
  };

  /* storyline: scroll through once so every scene mounts and animates */
  const story = document.getElementById('view-story');
  if (!story) fail('story', 'no #view-story in the file');
  else {
    await go('story');
    const H = document.documentElement.scrollHeight;
    for (let y = 0; y < H + innerHeight; y += innerHeight) { scrollTo(0, y); await wait(70); }
    await wait(300);
    checked.scenes = story.querySelectorAll('section, [data-scene]').length;
    if (!checked.scenes) fail('story', 'no scenes rendered');
    if (story.querySelector('[role=alert]')) fail('story', 'the storyline failed to render (error notice shown)');
    checked.storyWords = (story.innerText || '').trim().split(/\s+/).filter(Boolean).length;
    if (checked.storyWords < 150) fail('story', 'almost no text rendered (' + checked.storyWords + ' words)');
    badText(story, 'story');
    sideways('story');
    scrollTo(0, 0);
  }

  /* dashboard: panels, map, charts, table, one filter, the drawer */
  const dash = document.getElementById('view-dash');
  if (!dash) fail('dash', 'no #view-dash in the file');
  else {
    await go('dash');
    const D = window.DASH, api = D && D.api;
    if (D && D.errors && D.errors.length) D.errors.slice(0, 5).forEach(e => fail('dash', 'DASH.errors: ' + String(e).slice(0, 140)));
    const unavailable = [...dash.querySelectorAll('*')].filter(e => !e.children.length && /^\s*Unavailable\s*$/.test(e.textContent)).length;
    if (unavailable) fail('dash', unavailable + ' panel(s) show "Unavailable"');
    if (dash.querySelector('.leaflet-container')) {
      checked.markers = dash.querySelectorAll('.leaflet-interactive, .leaflet-marker-icon').length;
      if (!checked.markers) fail('dash', 'the map has no markers');
    }
    const charts = [...dash.querySelectorAll('svg')].filter(s => s.getBoundingClientRect().width > 120 && !s.closest('.leaflet-container'));
    checked.charts = charts.length;
    const empty = charts.filter(s => !s.querySelector('rect, circle, path, line, polygon, polyline'));
    if (empty.length) fail('dash', empty.length + ' chart(s) drew nothing');
    const rows = () => [...dash.querySelectorAll('tbody tr')].filter(r => r.getClientRects().length && !r.classList.contains('empty-row'));
    checked.rows = rows().length;
    if (!checked.rows) fail('dash', 'the table has no rows');
    badText(dash, 'dash');
    sideways('dash');

    if (api && api.setFilter && api.reset && api.all) {
      const by = {};
      for (const r of api.all) if (!r.owned && r.landlord) by[r.landlord] = (by[r.landlord] || 0) + (+r.size || 0);
      const top = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
      if (top) {
        try {
          api.reset(); await wait(200);
          api.setFilter('landlord', top[0]); await wait(600);
          checked.filteredRows = rows().length;
          if (!checked.filteredRows) fail('dash', 'filtering by the largest landlord empties the table');
          badText(dash, 'dash, filtered');
        } catch (e) { fail('dash', 'setFilter threw: ' + e.message); }
        try { api.reset(); await wait(300); } catch (e) { fail('dash', 'reset threw: ' + e.message); }
      }
    }

    const open = () => document.querySelector('#view-dash [role=dialog][aria-hidden=false], #view-dash .drawer.on, #view-dash [aria-modal=true]:not([aria-hidden=true])');
    const tr = rows()[0];
    if (tr) {
      const btn = tr.querySelector('[aria-haspopup], [aria-controls*=drawer i], [data-open], button[data-id], button[data-unit]')
        || tr.querySelector(':scope > :first-child button, :scope > :first-child a[href], :scope > :first-child [role=button]');
      (btn || tr).click(); await wait(700);
      let d = open();
      if (!d && api && api.openDrawer && api.all && api.all[0]) { api.openDrawer(api.all[0]); await wait(700); d = open(); }
      if (!d) fail('dash', 'the unit drawer does not open');
      else {
        checked.drawerWords = (d.innerText || '').trim().split(/\s+/).filter(Boolean).length;
        if (checked.drawerWords < 10) fail('dash', 'the drawer opened empty');
        badText(d, 'drawer');
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await wait(500);
        if (open()) fail('dash', 'the drawer does not close on Escape');
      }
    }
  }

  try { if (window.__setView) window.__setView('story'); } catch (e) { /* reported above */ }
  scrollTo(0, 0);
  return { pass: problems.length === 0, viewport: innerWidth + 'x' + innerHeight, problems, checked };
}
