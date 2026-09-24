async function pageText(opts) {
  /* Every word a reader (or a screen reader) can meet, from BOTH views, for Numbers QA.

     Output: a tab-separated string, ONE LINE PER BLOCK, in document order, never
     de-duplicated (the same figure printed twice appears twice):
         view <TAB> where <TAB> kind <TAB> text
       view   story | dash | dash[landlord=X] (a filtered state) | drawer:<unit>
              | popup (map marker pop-ups) | csv
       where  the nearest scene / section / panel id (or a heading slug)
       kind   the block's tag: p, h1..h6, li, td, th, dt, dd, figcaption, caption,
              button, summary, label, div, span … or svg-text; plus
              tooltip (SVG <title>, a Leaflet tooltip), aria-label, title, alt,
              counter (shown=… final=…; "MISMATCH" when the screen is not at the
              final value), header / row (CSV). A trailing "·sr" marks text for
              screen readers only; "·hidden" text in the DOM that is not rendered
              (print twins, closed content).
       text   the block's whole sentence: inline children (b, em, span, a …)
              joined in reading order, <br> as a space, nested blocks on their
              own lines.
     Where it goes: <run>/qa/page-text.txt. qa_run.cjs writes it there itself.
     Over the Playwright MCP, save the returned string to that file (if you use
     browser_evaluate's `filename`, the file holds a JSON string: decode it first).

     How to call
       Playwright MCP (copy this file into <run>/qa/ first, like qa_audit.js):
         async () => { const s = await (await fetch('qa/page_text.js')).text();
                       return (0, eval)('(' + s + ')')({}); }
         Emulate reduced motion first (browser_emulate_media) so counters settle.
       Node Playwright:  page.evaluate(`(${src})(${JSON.stringify(opts)})`)
     Options: { filters: [['landlord','<Landlord>'], ...] (default: the largest
       landlord), drawers: ['<unit id>', '3', ...] (unit ids or 1-based table rows;
       the first, largest and sparsest units are always added), popups: true,
       csv: true }
     It opens every <details>, scrolls the storyline so reveals and counters
     fire, and restores the page (storyline view, filters reset) at the end. */
  opts = Object.assign({ filters: null, drawers: [], popups: true, csv: true }, (opts && typeof opts === 'object' && !opts.nodeType) ? opts : {});
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const clean = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const slug = s => clean(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').split('-').filter(Boolean).slice(0, 4).join('-');
  const out = [];
  const put = (view, where, kind, text) => { const t = clean(text); if (t) out.push(view + '\t' + where + '\t' + kind + '\t' + t); };
  const where = el => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      if (e.id && (e.matches('section, .pin-wrap, [data-scene], [data-panel], aside, [role=dialog], table, footer, header, .blk, .metrics, .filters, .title-band') || /^(s\d|p-|panel|drawer|appendix)/i.test(e.id))) return e.id;
      if (e.matches && e.matches('main > section, .blk, [data-panel]')) { const h = e.querySelector('h1, h2, h3'); if (h) return slug(h.textContent); }
    }
    return '';
  };
  const SKIP = /^(script|style|noscript|template|head|meta|link)$/;
  const INLINE = /^(inline|contents|inline-block|inline-flex|inline-grid|ruby)$/;
  const dispOf = new Map();
  const isBlock = el => {
    if (el instanceof SVGElement) return /^(text|title|desc|foreignObject)$/.test(el.localName);
    if (dispOf.has(el)) return dispOf.get(el);
    const d = getComputedStyle(el).display;
    // inline-block children of a line (a pill, a chip) stay inline with their sentence
    const b = !(d === 'inline' || d === 'contents' || (INLINE.test(d) && !/^(button|select|input)$/.test(el.localName)));
    dispOf.set(el, b); return b;
  };
  const srOnly = el => {
    for (let e = el, i = 0; e && e.nodeType === 1 && i < 5; e = e.parentElement, i++) {
      const cs = getComputedStyle(e);
      if (/rect\(0(px)?,?\s*0(px)?,?\s*0(px)?,?\s*0(px)?\)/.test(cs.clip || '') || /inset\(50%/.test(cs.clipPath || '')) return true;
      const r = e.getBoundingClientRect(); if (!(e instanceof SVGElement) && r.width <= 1.5 && r.height <= 1.5 && cs.overflow !== 'visible') return true;
    }
    return false;
  };
  // the block's own sentence: its text and its inline descendants, not nested blocks
  const ownText = b => {
    let s = '';
    const walk = n => {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) s += c.nodeValue;
        else if (c.nodeType === 1) {
          if (SKIP.test(c.localName) || c.localName === 'title') continue;
          if (c.localName === 'br') { s += ' '; continue; }
          if (isBlock(c)) { s += ' '; continue; }
          walk(c);
        }
      }
    };
    walk(b);
    return clean(s);
  };
  const kindOf = el => {
    if (el instanceof SVGElement) return el.localName === 'title' ? 'tooltip' : 'svg-' + el.localName;
    let k = el.localName;
    const rendered = el.getClientRects().length && (!el.checkVisibility || el.checkVisibility({ visibilityProperty: true }));
    if (!rendered) k += '·hidden'; else if (srOnly(el)) k += '·sr';
    return k;
  };
  const collect = (root, view) => {
    if (!root) return;
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
      acceptNode: n => SKIP.test(n.localName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    const visit = el => {
      if (el.hasAttribute && el.hasAttribute('data-final')) {
        const fin = clean(el.getAttribute('data-final')), shown = clean(el.innerText || el.textContent);
        const rendered = el.getClientRects().length && (!el.checkVisibility || el.checkVisibility({ visibilityProperty: true }));
        put(view, where(el), rendered ? 'counter' : 'counter·hidden', (rendered && shown && fin && !shown.includes(fin) ? 'MISMATCH ' : '') + 'shown=' + (shown || clean(el.textContent)) + ' final=' + fin);
      }
      if (el.localName === 'title' && el instanceof SVGElement) { put(view, where(el), 'tooltip', el.textContent); return; }
      if (isBlock(el) || el === root) { const t = ownText(el); if (t) put(view, where(el), kindOf(el), t); }
      for (const a of ['aria-label', 'title', 'alt', 'aria-valuetext', 'placeholder']) {
        const v = el.getAttribute && el.getAttribute(a); if (v && v.trim()) put(view, where(el), a, v);
      }
    };
    visit(root);
    while (tw.nextNode()) visit(tw.currentNode);
  };
  const openDetails = root => root && root.querySelectorAll('details').forEach(d => { d.open = true; });
  const D = () => window.DASH && window.DASH.api;
  // HTML that the page would show (a pop-up), serialised the same way
  const fromHtml = (html, view, whereTxt) => {
    const box = document.createElement('div');
    box.style.cssText = 'position:absolute;left:-99999px;top:0;width:320px';
    (document.getElementById('view-dash') || document.body).appendChild(box);
    if (typeof html === 'string') box.innerHTML = html; else if (html && html.nodeType) box.appendChild(html.cloneNode(true));
    const tw = document.createTreeWalker(box, NodeFilter.SHOW_ELEMENT);
    while (tw.nextNode()) { const el = tw.currentNode; if (isBlock(el)) { const t = ownText(el); if (t) put(view, whereTxt, el.localName, t); } }
    const loose = ownText(box); if (loose && !box.querySelector('*')) put(view, whereTxt, 'text', loose);
    box.remove();
  };

  out.push('# page-text · ' + document.title + ' · ' + location.pathname.split('/').pop() + ' · ' + innerWidth + 'x' + innerHeight +
    ' · reducedMotion=' + matchMedia('(prefers-reduced-motion: reduce)').matches + ' · ' + new Date().toISOString());
  out.push('# view\twhere\tkind\ttext   (one line per block, in document order, not de-duplicated)');

  /* storyline: scroll through so every reveal and counter fires */
  const story = document.getElementById('view-story');
  if (story) {
    if (window.__setView) window.__setView('story');
    await wait(400);
    const H = document.documentElement.scrollHeight;
    for (let y = 0; y < H + innerHeight; y += Math.round(innerHeight * 0.6)) { scrollTo(0, y); await wait(110); }
    for (const c of story.querySelectorAll('[data-final]')) { c.scrollIntoView({ block: 'center', behavior: 'instant' }); await wait(260); }
    openDetails(story);
    await wait(300);
    collect(story, 'story');
  }

  /* dashboard: default state, a filtered state, the drawers, pop-ups, the CSV */
  const dash = document.getElementById('view-dash');
  if (dash) {
    if (window.__setView) window.__setView('dash');
    await wait(1400);
    if (D() && D().reset) D().reset();
    await wait(300);
    openDetails(dash);
    collect(dash, 'dash');

    let filters = opts.filters && opts.filters.length ? opts.filters : null;
    if (!filters && D() && D().all) {
      const by = {};
      for (const r of D().all) { if (r.owned || !r.landlord) continue; by[r.landlord] = (by[r.landlord] || 0) + (+r.size || 0); }
      const top = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
      filters = top ? [['landlord', top[0]]] : [];
    }
    for (const [k, v] of (filters || [])) {
      if (!D() || !D().setFilter) break;
      D().reset(); await wait(200);
      try { D().setFilter(k, v === 'true' ? true : v === 'false' ? false : v); } catch (e) { continue; }
      await wait(600);
      const view = 'dash[' + k + '=' + v + ']';
      const parts = [...dash.querySelectorAll('.metrics, #readout, .readout, .basis, .sec-note, .sub, .title-band, [class*=kpi], [class*=basis]')]
        .filter((p, i, a) => !a.some((q, j) => j !== i && q.contains(p)));
      if (parts.length) parts.forEach(p => collect(p, view)); else collect(dash, view);
    }
    if (D() && D().reset) { D().reset(); await wait(300); }

    // map pop-ups and tooltips: read what each marker would show
    if (opts.popups) {
      const map = D() && D().map;
      let n = 0;
      if (map && map.eachLayer) {
        map.eachLayer(l => {
          const tag = l.options && (l.options.title || l.options.alt) || '';
          const pop = l.getPopup && l.getPopup(), tip = l.getTooltip && l.getTooltip();
          for (const [kind, p] of [['popup', pop], ['tooltip', tip]]) {
            if (!p || n > 400) continue;
            let c = p.getContent ? p.getContent() : p._content;
            if (typeof c === 'function') { try { c = c(l); } catch (e) { c = null; } }
            if (c == null) continue;
            n++;
            const ll = l.getLatLng ? l.getLatLng() : null;
            const u = ll && D().all ? D().all.find(x => Math.abs(x.lat - ll.lat) < 1e-6 && Math.abs(x.lng - ll.lng) < 1e-6) : null;
            const key = u ? String(u.id) + ' ' + clean(u.short || u.name || '') : (tag || (ll ? ll.lat.toFixed(4) + ',' + ll.lng.toFixed(4) : 'marker ' + n));
            if (kind === 'tooltip') { const box = document.createElement('div'); if (typeof c === 'string') box.innerHTML = c; else if (c.nodeType) box.appendChild(c.cloneNode(true)); put('popup', key, 'tooltip', box.textContent); }
            else fromHtml(c, 'popup', key);
          }
        });
      }
      if (!n) {   // no map handle: open each marker's pop-up by clicking it
        const markers = [...dash.querySelectorAll('.leaflet-interactive, .leaflet-marker-icon')].slice(0, 200);
        for (const m of markers) {
          m.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          await wait(60);
          const p = dash.querySelector('.leaflet-popup-content');
          if (p) { collect(p, 'popup'); n++; }
        }
        const close = dash.querySelector('.leaflet-popup-close-button'); if (close) close.click();
      }
    }

    // drawers: requested ids / rows, plus the first, the largest and the sparsest unit
    const rows = () => [...dash.querySelectorAll('tbody tr')].filter(r => r.getClientRects().length && !r.classList.contains('empty-row'));
    const units = D() && D().all ? D().all : null;
    const picks = [];
    for (const w of opts.drawers || []) picks.push(String(w));
    picks.push('#first');
    if (units && units.length) {
      const largest = units.slice().sort((a, b) => (+b.size || 0) - (+a.size || 0))[0];
      const nulls = u => Object.values(u).filter(v => v == null || v === '').length;
      const sparsest = units.slice().sort((a, b) => nulls(b) - nulls(a))[0];
      if (largest) picks.push(String(largest.id));
      if (sparsest) picks.push(String(sparsest.id));
    } else picks.push('#sparse');
    const done = new Set();
    for (const w of picks) {
      let name = null;
      const u = units && units.find(x => String(x.id) === w);
      if (u && D().openDrawer) { if (done.has(String(u.id))) continue; done.add(String(u.id)); D().openDrawer(u); name = u.short || u.name || u.id; }
      else {
        const rs = rows(); let tr = null;
        if (w === '#first') tr = rs[0];
        else if (w === '#sparse') { const s = rs.map(r => ({ r, n: (r.textContent.match(/n\/r|not recorded/g) || []).length })).sort((a, b) => b.n - a.n)[0]; tr = s && s.r; }
        else if (/^\d+$/.test(w)) tr = rs[+w - 1];
        if (!tr) continue;
        const id = tr.dataset.id || tr.textContent.slice(0, 40); if (done.has(id)) continue; done.add(id);
        // the row's own opener, not a landlord or company chip that filters the table
        const btn = tr.querySelector('[aria-haspopup], [aria-controls*=drawer i], [data-open], button[data-id], button[data-unit]')
          || tr.querySelector(':scope > :first-child button, :scope > :first-child a[href], :scope > :first-child [role=button]');
        (btn || tr).click(); name = (tr.querySelector('td, th') || tr).innerText.split('\n')[0];
      }
      await wait(500);
      const d = document.querySelector('#view-dash [role=dialog][aria-hidden=false], #view-dash .drawer.on, #view-dash [aria-modal=true]:not([aria-hidden=true])');
      if (d) { openDetails(d); collect(d, 'drawer:' + clean(name).slice(0, 40)); }
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await wait(300);
    }

    // the CSV the reader downloads, in the DEFAULT state (a click above may have
    // filtered the table): capture the Blob instead of downloading it
    if (D() && D().reset) { D().reset(); await wait(300); }
    if (opts.csv && typeof window.__dashExportCsv === 'function') {
      let blob = null;
      const oc = URL.createObjectURL, ocl = HTMLAnchorElement.prototype.click;
      URL.createObjectURL = b => { blob = b; return 'about:blank'; };
      HTMLAnchorElement.prototype.click = function () {};
      try { window.__dashExportCsv(); } catch (e) { /* ignore */ } finally { URL.createObjectURL = oc; HTMLAnchorElement.prototype.click = ocl; }
      if (blob && blob.text) {
        const lines = (await blob.text()).replace(/^﻿/, '').split(/\r?\n/).filter(Boolean);
        if (lines.length) { out.push('csv\t\theader\t' + lines[0]); lines.slice(1, 2001).forEach(l => out.push('csv\t\trow\t' + l)); }
      }
    }
  }

  if (window.__setView) window.__setView('story');
  scrollTo(0, 0);
  return out.join('\n');
}
