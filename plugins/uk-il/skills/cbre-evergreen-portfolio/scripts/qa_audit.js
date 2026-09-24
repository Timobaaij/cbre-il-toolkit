async function qaAudit(arg) {
  /* ======================================================================
     qa_audit.js - in-page visual QA for a CBRE EverGreen portfolio file.

     The whole file is ONE function expression, so it can be pasted as-is:
       - Playwright MCP:  browser_evaluate  { function: <this file's text> }
         or, cheaper, fetch it from the served run folder:
           async () => { const s = await (await fetch('qa/qa_audit.js')).text();
                         return (0, eval)('(' + s + ')')({ action: 'list' }); }
         The first call installs the audit as window.__qaAudit, so every later
         call on the same page is a one-liner:
           async () => window.__qaAudit({ scene: 's6', progress: 0.5, max: 6 })
         (install again after any navigation or reload)
       - Node Playwright: page.evaluate(`(${src})(${JSON.stringify(opts)})`)
     It inspects the CURRENT viewport and scroll position (after optionally
     scrolling there itself) and returns JSON:
       { meta, ok, bySev, counts, issues: [{type, sev, scene, panel, node, text, detail, rect}] }
     `counts` lists every type, zeros included; `issues` is capped by `max`.

     Options (all optional)
       action    'audit' (default) | 'list' (scenes / dashboard sections)
                 | 'print' (document-wide print checks; emulate print media first)
       view      'story' | 'dash'   switch view first (window.__setView)
       scene     storyline scene id to scroll to
       progress  0..1 = point inside a pinned scene | 'center' (default) | 'start'
       section   index into list().sections (dashboard) ; y = absolute scrollY
       wait      ms to settle after any scroll (default 1800; 700 for 'start')
       headings  true = flag h1-h3 hidden under the app bar (use with 'start')
       inventory true = also return every rendered chart label per scene
                 (the driver compares them across viewports: droppedText)
       minFont   smallest rendered text in px (default 10; printMinFont 7 under print media)
       max       issues kept per type (default 12; counts are always complete)
       root      CSS selector to audit instead of the visible view
     Under print media the screen-only checks (app bar, sticky bars, ground
     mode) are skipped automatically.
     ====================================================================== */
  const DEF = { action: 'audit', view: null, scene: null, progress: 'center', section: null,
    y: null, wait: null, headings: false, inventory: false, minFont: 10, printMinFont: 7, max: 12, root: null };
  const ext = (arg && typeof arg === 'object' && !arg.nodeType) ? arg : {};
  const O = Object.assign({}, DEF, window.__QA_OPTS || {}, ext);
  try { delete window.__QA_OPTS; } catch (e) { window.__QA_OPTS = undefined; }
  window.__qaAudit = qaAudit;       // later calls: window.__qaAudit({...})

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const frames = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const clean = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const R = r => ({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) });
  const inter = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
                          Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  const box = (l, t, r, b) => ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t });
  const shrink = (r, fy, fx) => box(r.left + (fx || 0), r.top + r.height * fy, r.right - (fx || 0), r.bottom - r.height * fy);
  const slug = s => clean(s).toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').split('-').filter(Boolean).slice(0, 5).join('-').slice(0, 36);
  const PRINT = matchMedia('print').matches;

  /* ---------------------------------------------------------- 0. navigate */
  let moved = false;
  if (O.view && document.body.dataset.view && document.body.dataset.view !== O.view) {
    if (typeof window.__setView === 'function') window.__setView(O.view);
    else location.hash = '#' + O.view;
    moved = true;
    await sleep(1200);
  }
  const findRoot = () => {
    if (O.root) return document.querySelector(O.root) || document.body;
    for (const s of ['#view-story', '#view-dash']) {
      const e = document.querySelector(s);
      if (e && !e.hidden && e.getClientRects().length) return e;
    }
    return document.body;
  };
  let root = findRoot();
  const vw = innerWidth, vh = innerHeight;
  // the dashboard's panels are section[id] too, but they are not scenes
  const isDash = () => root.id === 'view-dash' || (!!document.body.dataset.view && document.body.dataset.view === 'dash' && root === document.body);

  const CSm = new Map();
  const CS = e => { let c = CSm.get(e); if (!c) { c = getComputedStyle(e); CSm.set(e, c); } return c; };

  // fixed bars across the top (the CBRE app bar), and every fixed / sticky element
  const inventory = () => {
    const fixed = new Set(), sticky = new Set(), bars = [];
    for (const e of document.body.querySelectorAll('*')) {
      const p = CS(e).position;
      if (p !== 'fixed' && p !== 'sticky') continue;
      if (!e.getClientRects().length) continue;
      (p === 'fixed' ? fixed : sticky).add(e);
      if (p === 'fixed') {
        const r = e.getBoundingClientRect();
        if (r.top <= 1 && r.bottom > 20 && r.height >= 24 && r.height <= 140 && r.width >= vw * 0.6 &&
            CS(e).visibility !== 'hidden' && +CS(e).opacity > 0.1) bars.push(e);
      }
    }
    const barBottom = PRINT ? 0 : bars.reduce((a, b) => Math.max(a, b.getBoundingClientRect().bottom), 0);
    return { fixed, sticky, bars: PRINT ? [] : bars, barBottom };
  };
  let INV = inventory();

  // A scene is pinned when it holds a sticky STAGE (about a viewport tall);
  // a sticky table column or header inside a tall appendix is not a pin.
  const scenesOf = rt => {
    const all = [...rt.querySelectorAll('section[id], .pin-wrap[id], [data-scene]')];
    const set = new Set(all);
    const outer = all.filter(e => { for (let a = e.parentElement; a && a !== rt; a = a.parentElement) if (set.has(a)) return false; return true; });
    return outer.map(e => {
      const r = e.getBoundingClientRect();
      let pinned = false;
      if (r.height > vh * 1.3) {
        if (e.classList.contains('pin-wrap') && e.querySelector('.pin-stage')) pinned = CS(e.querySelector('.pin-stage')).position === 'sticky';
        else for (const d of e.querySelectorAll('*')) {
          if (CS(d).position !== 'sticky') continue;
          if (d.getBoundingClientRect().height >= vh * 0.8) { pinned = true; break; }
        }
      }
      const h = e.querySelector('h1, h2, h3');
      return { id: e.id || null, pinned, top: Math.round(r.top + scrollY), height: Math.round(r.height),
               heading: h ? clean(h.textContent).slice(0, 80) : null, el: e };
    });
  };
  // Dashboard sections, with every PANEL listed: a band that holds a row of
  // block panels (three panels in one grid) lists each panel, not the band.
  const PANEL = '[data-panel], [id^="p-"], .blk';
  const sectionsOf = rt => {
    const kids = [...rt.children];
    const main = rt.querySelector('main');
    if (main && kids.includes(main)) kids.splice(kids.indexOf(main), 1, ...main.children);
    const top = kids.filter(e => {
      if (/^(SCRIPT|STYLE|TEMPLATE)$/.test(e.tagName)) return false;
      const p = CS(e).position; if (p === 'fixed') return false;
      const r = e.getBoundingClientRect(); return r.height > 40;
    });
    const flat = [];
    for (const e of top) {
      const inner = e.matches(PANEL) ? [] : [...e.querySelectorAll(PANEL)].filter(p => { const up = p.parentElement && p.parentElement.closest(PANEL); return !up || !e.contains(up); })
        .filter(p => p.getBoundingClientRect().height > 40);
      if (inner.length) inner.forEach(p => flat.push({ e: p, row: e.id || (e.className && String(e.className).split(' ')[0]) || e.tagName.toLowerCase() }));
      else flat.push({ e, row: null });
    }
    return flat.map(({ e, row }, i) => {
      const r = e.getBoundingClientRect(), h = e.querySelector('h1, h2, h3');
      return { index: i, id: e.id || null, cls: (e.className && String(e.className).split(' ')[0]) || e.tagName.toLowerCase(),
               heading: h ? clean(h.textContent).slice(0, 80) : null, top: Math.round(r.top + scrollY),
               height: Math.round(r.height), row: row || undefined, el: e };
    });
  };

  if (O.scene) {
    const s = document.getElementById(O.scene);
    if (!s) return { error: 'scene not found: ' + O.scene };
    if (O.progress === 'start') s.scrollIntoView({ block: 'start', behavior: 'instant' });
    else {
      const r = s.getBoundingClientRect(), t = r.top + scrollY;
      const y = typeof O.progress === 'number' ? t + Math.max(0, r.height - vh) * O.progress : t + (r.height - vh) / 2;
      scrollTo({ top: Math.max(0, Math.round(y)), behavior: 'instant' });
    }
    moved = true;
  } else if (O.section != null) {
    const secs = sectionsOf(root), s = secs[O.section];
    if (!s) return { error: 'section index out of range', sections: secs.length };
    let stack = INV.barBottom;
    for (const e of INV.sticky) {
      const t = parseFloat(CS(e).top), r = e.getBoundingClientRect();
      if (!isNaN(t) && t <= INV.barBottom + 2 && r.height < 200 && root.contains(e)) stack = Math.max(stack, t + r.height);
    }
    scrollTo({ top: Math.max(0, s.top - stack - 8), behavior: 'instant' });
    moved = true;
  } else if (O.y != null) { scrollTo({ top: +O.y, behavior: 'instant' }); moved = true; }
  if (moved) {
    let w = O.wait != null ? O.wait : (O.progress === 'start' ? 750 : 1800);
    // the storyline ground cross-fades over 620ms: contrast read inside the fade
    // is wrong, so never settle for less than 700ms after a scroll there
    const fades = root.id === 'view-story' && document.querySelector('#ground') && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (fades) w = Math.max(w, 700);
    await sleep(w);
    await frames();
    // anything still fading (a ground, a mode colour, a fill)? wait for it, at most 1.5s more
    const running = (document.getAnimations ? document.getAnimations() : []).filter(a => a.playState === 'running' &&
      /color|background|fill|stroke|opacity/i.test(a.transitionProperty || '') && isFinite(a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming().endTime : 0));
    if (running.length) { await Promise.race([Promise.all(running.map(a => a.finished.catch(() => {}))), sleep(1500)]); await frames(); }
    CSm.clear(); root = findRoot(); INV = inventory();
  }

  // a stable name for "what is in view": the scene id, or the panel heading
  const anchorOf = () => {
    const y = INV.barBottom + (vh - INV.barBottom) * 0.3;
    const sc = (isDash() ? [] : scenesOf(root)).find(s => { const r = s.el.getBoundingClientRect(); return r.top <= y && r.bottom >= y; });
    if (sc && sc.id) return sc.id;
    const sec = sectionsOf(root).find(s => { const r = s.el.getBoundingClientRect(); return r.top <= y && r.bottom >= y; });
    if (!sec) return 'y' + Math.round(scrollY);
    let best = null;
    for (const h of sec.el.querySelectorAll('h1, h2, h3')) {
      const r = h.getBoundingClientRect(); if (r.height < 1) continue;
      if (r.top <= y + 40 && (!best || r.top > best.top)) best = { top: r.top, t: h.textContent };
    }
    if (!best) { const h = sec.el.querySelector('h1, h2, h3'); if (h) best = { t: h.textContent }; }
    return slug(best ? best.t : (sec.id || sec.cls)) || ('s' + sec.index);
  };

  const meta = {
    view: root.id ? root.id.replace(/^view-/, '') : 'page', viewport: vw + 'x' + vh,
    scrollY: Math.round(scrollY), docHeight: document.documentElement.scrollHeight,
    barBottom: Math.round(INV.barBottom), mode: root.dataset ? (root.dataset.mode || null) : null,
    fonts: document.fonts ? document.fonts.status : 'n/a',
    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches, print: PRINT,
  };

  if (O.action === 'list') {
    // storyline: its scenes (pinned ones flagged). Dashboard: every section and panel.
    const strip = a => a.map(({ el, ...x }) => Object.assign(x, { heading: x.heading && x.heading.slice(0, 60) }));
    const sc = isDash() ? [] : scenesOf(root);
    return sc.length ? { meta, scenes: strip(sc) } : { meta, sections: strip(sectionsOf(root)) };
  }

  /* ------------------------------------------------------------ helpers */
  const opM = new Map();
  const effOp = e => {
    if (!e || e.nodeType !== 1) return 1;
    if (opM.has(e)) return opM.get(e);
    const o = (+CS(e).opacity || 0) * effOp(e.parentElement);
    opM.set(e, o); return o;
  };
  const scM = new Map();
  const cssScale = e => {   // accumulated CSS transform scale of an HTML element
    if (!e || e.nodeType !== 1 || e === document.documentElement) return 1;
    if (scM.has(e)) return scM.get(e);
    let s = 1; const t = CS(e).transform;
    if (t && t !== 'none') {
      const m = t.match(/matrix\(([^)]+)\)/);
      if (m) { const v = m[1].split(',').map(Number); s = Math.sqrt(Math.abs(v[0] * v[3] - v[1] * v[2])) || 1; }
    }
    s *= cssScale(e.parentElement); scM.set(e, s); return s;
  };
  const px = document.createElement('canvas'); px.width = px.height = 1;
  const pctx = px.getContext('2d', { willReadFrequently: true });
  const colM = new Map();
  const parseColor = s => {
    if (!s) return null;
    s = String(s).trim();
    if (colM.has(s)) return colM.get(s);
    let out = null;
    const m = s.match(/^rgba?\(([^)]+)\)$/);
    if (m) {
      const v = m[1].split(/[\s,/]+/).filter(Boolean);
      const a = v[3] == null ? 1 : (String(v[3]).endsWith('%') ? parseFloat(v[3]) / 100 : +v[3]);
      out = [+v[0], +v[1], +v[2], a];
    } else if (s === 'transparent' || s === 'none') out = [0, 0, 0, 0];
    else {
      try {
        pctx.clearRect(0, 0, 1, 1); pctx.fillStyle = '#000'; pctx.fillStyle = s; pctx.fillRect(0, 0, 1, 1);
        const d = pctx.getImageData(0, 0, 1, 1).data; out = [d[0], d[1], d[2], d[3] / 255];
      } catch (e) { out = null; }
    }
    colM.set(s, out); return out;
  };
  const over = (t, b) => { const a = t[3]; return [t[0] * a + b[0] * (1 - a), t[1] * a + b[1] * (1 - a), t[2] * a + b[2] * (1 - a), 1]; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = c => '#' + c.slice(0, 3).map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
  const oklab = c => {
    const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    const r = f(c[0]), g = f(c[1]), b = f(c[2]);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
  };
  const dE = (a, b) => { const A = oklab(a), B = oklab(b); return 100 * Math.hypot(A[0] - B[0], A[1] - B[1], A[2] - B[2]); };
  const patternColor = id => {
    const p = document.getElementById(id); if (!p) return null;
    if (/gradient/i.test(p.localName)) { const st = p.querySelector('stop'); return st ? parseColor(CS(st).stopColor) : null; }
    const f = p.querySelector('rect, path, circle');
    return f ? parseColor(CS(f).fill) : null;
  };
  // the NOT-RECORDED hatch: a line pattern in neutral greys (a coral "passed"
  // hatch is a different encoding and may be used freely)
  const chroma = c => { const L = oklab(c); return Math.hypot(L[1], L[2]); };
  const isNRHatch = id => {
    const p = document.getElementById(id);
    if (!p || p.localName !== 'pattern') return false;
    const ln = p.querySelector('line, path');
    if (!ln && !/rotate/.test(p.getAttribute('patternTransform') || '')) return false;
    const base = p.querySelector('rect'), bc = base ? parseColor(CS(base).fill) : null, lc = ln ? parseColor(CS(ln).stroke) : null;
    const cols = [bc, lc].filter(c => c && c[3] >= 0.3);
    return cols.length > 0 && cols.every(c => chroma(c) < 0.035);
  };

  // CSS gradients, evaluated at the point where the text sits (a 1px divider
  // drawn as a hard-stop gradient is not the cell's background)
  const splitTop = s => { const out = []; let d = 0, cur = ''; for (const ch of s) { if (ch === '(') d++; else if (ch === ')') d--; if (ch === ',' && d === 0) { out.push(cur.trim()); cur = ''; } else cur += ch; } if (cur.trim()) out.push(cur.trim()); return out; };
  const COLSTART = /^(rgba?\(|hsla?\(|color\(|okl(ch|ab)\(|lab\(|lch\(|hwb\(|#|transparent\b|currentcolor\b|[a-z]+(\s|$))/i;
  const gradientAt = (g, rect, pt, op) => {
    const m = g.match(/^(repeating-)?(linear|radial|conic)-gradient\(([\s\S]*)\)$/);
    if (!m) return null;
    const args = splitTop(m[3]);
    let deg = 180;
    if (m[2] === 'linear' && args.length && !/^(rgba?\(|hsla?\(|color\(|okl|lab\(|lch\(|#|transparent)/i.test(args[0])) {
      const a0 = args.shift();
      if (/deg$/.test(a0)) deg = parseFloat(a0); else if (/turn$/.test(a0)) deg = parseFloat(a0) * 360; else if (/rad$/.test(a0)) deg = parseFloat(a0) * 180 / Math.PI;
      else { const map = { 'to top': 0, 'to right': 90, 'to bottom': 180, 'to left': 270, 'to top right': 45, 'to right top': 45, 'to bottom right': 135, 'to right bottom': 135, 'to bottom left': 225, 'to left bottom': 225, 'to top left': 315, 'to left top': 315 }; deg = map[a0] != null ? map[a0] : 180; }
    } else if (m[2] !== 'linear' && args.length && !/^(rgba?\(|hsla?\(|color\(|okl|lab\(|lch\(|#|transparent)/i.test(args[0])) args.shift();
    const W = rect.width, H = rect.height, a = deg * Math.PI / 180;
    const L = Math.abs(W * Math.sin(a)) + Math.abs(H * Math.cos(a)) || 1;
    const stops = [];
    for (const s of args) {
      const cm = s.match(/^((?:rgba?|hsla?|color|oklch|oklab|lab|lch|hwb)\([^)]*\)|#[0-9a-f]{3,8}|[a-z]+)\s*(.*)$/i);
      if (!cm) continue;
      const c = parseColor(cm[1]); if (!c) continue;
      const pos = (cm[2] || '').split(/\s+/).filter(Boolean).map(p => /%$/.test(p) ? parseFloat(p) / 100 * L : parseFloat(p));
      if (!pos.length) stops.push({ c, p: null }); else pos.forEach(p => stops.push({ c, p }));
    }
    if (!stops.length) return null;
    if (stops[0].p == null) stops[0].p = 0;
    if (stops[stops.length - 1].p == null) stops[stops.length - 1].p = L;
    for (let i = 1; i < stops.length; i++) {
      if (stops[i].p == null) { let j = i; while (stops[j].p == null) j++; const a0 = stops[i - 1].p, b0 = stops[j].p; for (let k = i; k < j; k++) stops[k].p = a0 + (b0 - a0) * (k - i + 1) / (j - i + 1); }
      stops[i].p = Math.max(stops[i].p, stops[i - 1].p);
    }
    const col = c => [c[0], c[1], c[2], c[3] * op];
    if (m[2] !== 'linear' || !pt) {
      // no exact position: every stop that occupies a real share of the box
      const keep = stops.filter((s, i) => { const nx = stops[i + 1] ? stops[i + 1].p : L, pv = stops[i - 1] ? stops[i - 1].p : 0; return (nx - pv) >= Math.max(3, L * 0.08); });
      return (keep.length ? keep : stops).map(s => col(s.c));
    }
    const cx = rect.left + W / 2, cy = rect.top + H / 2;
    let t = (pt.x - cx) * Math.sin(a) - (pt.y - cy) * Math.cos(a) + L / 2;
    if (m[1]) { const span = stops[stops.length - 1].p - stops[0].p; if (span > 0) t = stops[0].p + ((t - stops[0].p) % span + span) % span; }
    if (t <= stops[0].p) return [col(stops[0].c)];
    for (let i = 0; i < stops.length - 1; i++) {
      const A = stops[i], B = stops[i + 1];
      if (t >= A.p && t <= B.p) {
        const f = B.p - A.p < 0.01 ? 1 : (t - A.p) / (B.p - A.p);
        return [col([0, 1, 2, 3].map(k => A.c[k] + (B.c[k] - A.c[k]) * f))];
      }
    }
    return [col(stops[stops.length - 1].c)];
  };
  // colours an element paints behind whatever sits on top of it (at pt, if given)
  const layersOf = (e, pt) => {
    const cs = CS(e), op = effOp(e);
    if (op < 0.02 || cs.visibility === 'hidden') return [];
    if (e instanceof SVGElement && !(e instanceof SVGSVGElement)) {
      if (!(e instanceof SVGGeometryElement) || /^(line|polyline)$/.test(e.localName)) return [];
      const f = cs.fill; if (!f || f === 'none') return [];
      const u = f.match(/url\(["']?#([^"')]+)/);
      const c = u ? patternColor(u[1]) : parseColor(f);
      if (!c) return [];
      return [[c[0], c[1], c[2], c[3] * (+cs.fillOpacity) * op]];
    }
    if (/^(img|canvas|video|iframe|picture)$/.test(e.localName)) return 'image';
    const out = [];
    const bg = parseColor(cs.backgroundColor);
    if (bg && bg[3] > 0) out.push([bg[0], bg[1], bg[2], bg[3] * op]);
    const bi = cs.backgroundImage;
    if (bi && bi !== 'none') {
      const layers = splitTop(bi).reverse();      // the first listed layer paints on top
      const rect = e.getBoundingClientRect();
      for (const L of layers) {
        if (/gradient\(/.test(L)) { const g = gradientAt(L, rect, pt, op); if (g && g.length) out.push(g.length === 1 ? g[0] : { gradient: g }); }
        else if (/url\(/.test(L) && !(bg && bg[3] > 0.95)) return 'image';
      }
    }
    return out;
  };
  const isSrOnly = el => {
    for (let e = el, i = 0; e && e.nodeType === 1 && i < 5; e = e.parentElement, i++) {
      const cs = CS(e);
      if (cs.clip && /rect\(0(px)?,?\s*0(px)?,?\s*0(px)?,?\s*0(px)?\)/.test(cs.clip)) return true;
      if (cs.clipPath && /inset\(50%/.test(cs.clipPath)) return true;
      if (!(e instanceof SVGElement)) { const r = e.getBoundingClientRect(); if (r.width <= 1.5 && r.height <= 1.5 && cs.overflow !== 'visible') return true; }
    }
    return false;
  };
  // The part of a box that can be seen. Default mode: intersected with the
  // viewport and every ancestor that clips or scrolls. 'clip' mode: what an
  // overflow:hidden/clip frame cuts off from the part its scrollers show; text
  // scrolled out of a scroller (a wide table in its frame) is not "clipped".
  const visibleBox = (el, bb, mode) => {
    const clipMode = mode === 'clip';
    let v = { l: bb.left, t: bb.top, r: bb.right, b: bb.bottom }, by = null, ellipsis = false;
    if (!clipMode) { v.l = Math.max(v.l, 0); v.t = Math.max(v.t, 0); v.r = Math.min(v.r, vw); v.b = Math.min(v.b, vh); }
    let base = null;               // clip mode: the box after scrollers only
    let escaping = /^(absolute|fixed)$/.test(CS(el).position);
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const cs = CS(a);
      const positioned = cs.position !== 'static' || (cs.transform && cs.transform !== 'none');
      const clipX = /^(hidden|clip)$/.test(cs.overflowX), clipY = /^(hidden|clip)$/.test(cs.overflowY);
      const scrX = /^(auto|scroll)$/.test(cs.overflowX), scrY = /^(auto|scroll)$/.test(cs.overflowY);
      if ((clipX || clipY || scrX || scrY) && (!escaping || positioned || a instanceof SVGSVGElement)) {
        const r = a.getBoundingClientRect();
        const L0 = r.left + (parseFloat(cs.borderLeftWidth) || 0), R0 = r.right - (parseFloat(cs.borderRightWidth) || 0);
        const T0 = r.top + (parseFloat(cs.borderTopWidth) || 0), B0 = r.bottom - (parseFloat(cs.borderBottomWidth) || 0);
        const before = Math.max(0, v.r - v.l) * Math.max(0, v.b - v.t);
        const cutX = clipMode ? clipX : (clipX || scrX), cutY = clipMode ? clipY : (clipY || scrY);
        if (clipMode && (scrX || scrY)) {
          // a scroller shows part of its content; nothing beyond it counts as clipped
          if (scrX) { v.l = Math.max(v.l, L0); v.r = Math.min(v.r, R0); }
          if (scrY) { v.t = Math.max(v.t, T0); v.b = Math.min(v.b, B0); }
          base = { l: v.l, t: v.t, r: v.r, b: v.b };
        }
        if (cutX) { v.l = Math.max(v.l, L0); v.r = Math.min(v.r, R0); }
        if (cutY) { v.t = Math.max(v.t, T0); v.b = Math.min(v.b, B0); }
        if ((cutX || cutY) && Math.max(0, v.r - v.l) * Math.max(0, v.b - v.t) < before - 0.5 && !by) by = a;
        if (cs.textOverflow === 'ellipsis') ellipsis = true;
      }
      if (escaping && positioned) escaping = /^(absolute|fixed)$/.test(cs.position);
      if (cs.position === 'fixed') break;
    }
    const b0 = base || { l: bb.left, t: bb.top, r: bb.right, b: bb.bottom };
    return { l: v.l, t: v.t, r: v.r, b: v.b, w: Math.max(0, v.r - v.l), h: Math.max(0, v.b - v.t), by, ellipsis,
             baseW: Math.max(0, b0.r - b0.l), baseH: Math.max(0, b0.b - b0.t) };
  };
  const fixedAnc = el => { for (let a = el; a && a !== document.documentElement; a = a.parentElement) if (INV.fixed.has(a) || INV.sticky.has(a)) return a; return null; };
  const inBar = el => INV.bars.some(b => b.contains(el));
  const atStickyPos = e => {   // is this sticky element currently stuck?
    if (INV.fixed.has(e)) return true;
    const t = parseFloat(CS(e).top); if (isNaN(t)) return false;
    return Math.abs(e.getBoundingClientRect().top - t) < 1.5;
  };
  const whereOf = el => {
    let scene = null, panel = null, node = null;
    for (let e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      if (!node && e.id) node = '#' + e.id;
      if (!scene && e.id && e.matches('section, .pin-wrap, [data-scene], aside, [role=dialog], footer, header, nav')) scene = '#' + e.id;
      if (!panel && e.matches('.blk, .f-item, .legend, .map-side, [role=dialog], section, .pin-in, .scene-in, .metrics, .filters, .title-band, header, footer, figure, .panel, [data-panel]')) {
        const h = e.querySelector('h1, h2, h3, h4'); if (h) panel = clean(h.textContent).slice(0, 60);
      }
    }
    return { scene, panel, node };
  };
  const sel = e => e.id ? '#' + e.id : e.localName + (e.getAttribute && e.getAttribute('class') ? '.' + String(e.getAttribute('class')).trim().split(/\s+/)[0] : '');
  const heading = el => !!(el.closest && el.closest('h1, h2, h3'));
  const outerSvg = e => { let s = e.ownerSVGElement; while (s && s.ownerSVGElement) s = s.ownerSVGElement; return s; };
  const titleOf = e => {   // a mark's own tooltip, never a sibling's
    const own = e.querySelector && e.querySelector(':scope > title'); if (own) return clean(own.textContent);
    const g = e.parentElement;
    if (g && g.localName === 'g' && g.querySelectorAll(':scope > rect, :scope > circle, :scope > path, :scope > polygon, :scope > ellipse').length <= 4) {
      const t = g.querySelector(':scope > title'); if (t) return clean(t.textContent);
    }
    return null;
  };

  // what a swatch or mark looks like: fill, stroke, pattern, dash, shape and
  // stroke weight together (a solid hollow ring and a dashed ring of the same
  // colour are two different encodings)
  const lookOf = e => {
    const cs = CS(e), svgEl = e instanceof SVGElement;
    let fill = null, stroke = null, pattern = null, dash = false, shape = null, sw = 0;
    const r = e.getBoundingClientRect();
    if (svgEl) {
      const fu = cs.fill && cs.fill.match(/url\(["']?#([^"')]+)/);
      if (fu) pattern = fu[1]; else { const c = parseColor(cs.fill); if (c && c[3] * (+cs.fillOpacity) >= 0.3) fill = c; }
      const m = e.getScreenCTM && e.getScreenCTM(), k = m ? Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) : 1;
      if (cs.stroke && cs.stroke !== 'none' && !/url/.test(cs.stroke) && (parseFloat(cs.strokeWidth) || 0) * k >= 0.8) {
        const c = parseColor(cs.stroke); if (c && c[3] * (+cs.strokeOpacity) >= 0.3) { stroke = c; sw = (parseFloat(cs.strokeWidth) || 0) * k; }
        dash = !!(cs.strokeDasharray && !/^(none|0(px)?)$/.test(cs.strokeDasharray.trim()));
      }
      if (e.localName === 'line') { fill = stroke; shape = 'line'; }
      else if (/^(circle|ellipse)$/.test(e.localName)) shape = 'round';
      else if (e.localName === 'rect') shape = (parseFloat(e.getAttribute('rx')) || 0) >= Math.min(+e.getAttribute('width') || 0, +e.getAttribute('height') || 0) * 0.4 ? 'round' : 'square';
      else shape = Math.abs(r.width - r.height) < 1.5 && /a/i.test(e.getAttribute('d') || '') ? 'round' : 'path';
    } else {
      const c = parseColor(cs.backgroundColor); if (c && c[3] >= 0.3) fill = c;
      if (/gradient|url\(/.test(cs.backgroundImage || '')) pattern = 'css:' + cs.backgroundImage.slice(0, 80);
      const bw = parseFloat(cs.borderTopWidth) || 0;
      if (bw >= 1 && !/none|hidden/.test(cs.borderTopStyle)) { const b = parseColor(cs.borderTopColor); if (b && b[3] >= 0.3) { stroke = b; sw = bw; dash = /dashed|dotted/.test(cs.borderTopStyle); } }
      const sh = (cs.boxShadow || '').match(/inset[^,]*?(rgba?\([^)]*\))[^,]*?(-?[\d.]+)px\s*$|(rgba?\([^)]*\))\s+0px\s+0px\s+0px\s+([\d.]+)px\s+inset/);
      if (!stroke && sh) { const b = parseColor(sh[1] || sh[3]); if (b && b[3] >= 0.5) { stroke = b; sw = parseFloat(sh[2] || sh[4]) || 1; } }
      const rad = cs.borderTopLeftRadius || '';
      shape = /%/.test(rad) ? (parseFloat(rad) >= 40 ? 'round' : 'square') : ((parseFloat(rad) || 0) >= Math.min(r.width, r.height) * 0.4 ? 'round' : 'square');
    }
    if (stroke && fill && lum(stroke) > 0.85) stroke = null;          // a white keyline around a fill
    if (stroke && fill && dE(stroke, fill) < 3) stroke = null;
    const ring = !!(stroke && !fill && !pattern);
    return { fill, stroke, pattern, ring, dash, shape, sw };
  };
  const sameLook = (A, B) => {
    if ((A.pattern || '') !== (B.pattern || '')) return false;
    if (!!A.dash !== !!B.dash) return false;
    if (A.shape && B.shape && A.shape !== B.shape) return false;
    if (A.stroke && B.stroke && A.sw && B.sw && Math.max(A.sw, B.sw) / Math.min(A.sw, B.sw) > 1.6) return false;
    const d = (a, b) => (!a && !b) ? 0 : (!a || !b) ? 99 : dE(a, b);
    return d(A.fill, B.fill) < 3 && d(A.stroke, B.stroke) < 6;
  };
  const issues = [];
  const SEV = { contrast: 'P1', groundMismatch: 'P1', underBar: 'P1', headingUnderBar: 'P1', pinOverflow: 'P1', hScroll: 'P1',
    overlapText: 'P1', badToken: 'P1', placeholderDate: 'P1', scaleDrift: 'P1', labelDrift: 'P1', rmHidden: 'P1',
    printUnfinished: 'P1', printCounter: 'P1', printPinned: 'P1',
    lineThroughText: 'P2', topGridBelowMax: 'P2', encodingClash: 'P2', numberFormat: 'P2', tableOverflow: 'P2', stickyBroken: 'P2',
    offBaseline: 'P2', tickLabels: 'P2', printMarks: 'P2', midWordBreak: 'P2', openingNotLargest: 'P2',
    stickyTooTall: 'P2', clipped: 'P2', covered: 'P2', labelMark: 'P2', floatingLeader: 'P2', unlabelledTile: 'P2',
    smallText: 'P2', truncated: 'P2', hiddenText: 'P2', dupLabel: 'P2', badTokenHidden: 'P2', printDark: 'P2', printBlank: 'P2',
    droppedText: 'P2', contrastDimmed: 'P3', smallTarget: 'P3', clickNoKeyboard: 'P3', progFocusRing: 'P3', a11yName: 'P3' };
  const counts = {}; for (const k of Object.keys(SEV)) counts[k] = 0;
  const bySev = { P1: 0, P2: 0, P3: 0 };
  const add = (type, el, text, detail, rect, sev) => {
    counts[type] = (counts[type] || 0) + 1;
    sev = sev || SEV[type] || 'P2';
    bySev[sev]++;
    if (counts[type] > O.max) return;
    const w = el ? whereOf(el) : {};
    if (detail) for (const k of Object.keys(detail)) if (detail[k] === undefined) delete detail[k];
    issues.push({ type, sev, scene: w.scene || null, panel: w.panel || null, node: w.node || null,
      text: text != null ? clean(text).slice(0, 80) : null, detail: detail || null, rect: rect ? R(rect) : null });
  };
  const result = () => {
    const order = { P1: 0, P2: 1, P3: 2 };
    issues.sort((a, b) => order[a.sev] - order[b.sev] || a.type.localeCompare(b.type));
    return { meta, ok: bySev.P1 === 0, bySev, counts, issues };
  };

  /* ================================================ PRINT (action 'print')
     Document-wide checks for a printed copy. Emulate print media first
     (browser_emulate_media {media:'print'} / page.emulateMedia), then call. */
  if (O.action === 'print') {
    meta.anchor = 'print';
    if (!PRINT) meta.warning = 'print media is not active: emulate print before this check';
    const els = [...root.querySelectorAll('*')];
    // 1. motion left mid-way. "Motion-driven" = the engine's .mv contract, or an
    // inline opacity/transform written by the animation library. A layer that
    // is hidden on purpose (a class with hide / pre / ghost) is skipped; a
    // muted mark at a resting opacity has no inline style and is not counted.
    const HIDE = /(^|[-_\s])(hide|hidden|pre|ghost|noprint|print-hide|screen-only)([-_\s]|$)/i;
    const hiddenOnPurpose = e => { for (let a = e; a && a !== root; a = a.parentElement) { const c = a.getAttribute && a.getAttribute('class'); if (c && HIDE.test(c)) return true; } return false; };
    let nUnf = 0; const unf = [];
    const note = (e, why) => { nUnf++; if (unf.length < 6) unf.push(sel(e) + ' ' + why); };
    for (const e of els) {
      const cs = CS(e);
      if (cs.display === 'none' || !e.getClientRects().length) continue;
      if (e.checkVisibility && !e.checkVisibility({ visibilityProperty: true })) continue;
      const cls = e.getAttribute('class') || '';
      const motion = /(^|\s)mv(\s|$)/.test(cls) || (e.style && (e.style.opacity !== '' || e.style.transform !== ''));
      const textHere = [...e.childNodes].some(n => n.nodeType === 3 && /\S/.test(n.nodeValue));
      if (textHere && !(e instanceof SVGElement) && effOp(e) < 0.05 && !hiddenOnPurpose(e) && !isSrOnly(e)) { note(e, 'text at opacity 0'); continue; }
      if (!motion || hiddenOnPurpose(e)) continue;
      const own = +cs.opacity;
      if (own < 0.95) { note(e, 'opacity ' + own.toFixed(2)); continue; }
      if (e instanceof SVGGeometryElement) {
        const r = e.getBoundingClientRect();
        const zero = (e.localName === 'rect' && +e.getAttribute('width') > 1 && +e.getAttribute('height') > 1 && (r.width < 0.5 || r.height < 0.5)) ||
                     (e.localName === 'circle' && +e.getAttribute('r') > 1 && r.width < 0.5);
        if (zero) { note(e, 'scaled to 0'); continue; }
      }
      const t = cs.transform, mm = t && t.match(/matrix\(([^)]+)\)/);
      if (mm) { const v = mm[1].split(',').map(Number); const sx = Math.hypot(v[0], v[1]), sy = Math.hypot(v[2], v[3]); if (sx < 0.97 || sy < 0.97) note(e, 'scaled ' + sx.toFixed(2) + '×' + sy.toFixed(2)); }
    }
    if (nUnf) add('printUnfinished', root, null, { elements: nUnf, examples: unf, note: 'in print these animated marks or blocks are translucent or part-grown: the printed copy shows a half-built chart' });
    // 2. counters must print their final value
    for (const e of root.querySelectorAll('[data-final]')) {
      const fin = clean(e.getAttribute('data-final')); if (!fin) continue;
      const shown = clean(e.innerText) + ' ' + clean((getComputedStyle(e, '::after').content || '').replace(/^["']|["']$/g, ''));
      if (!shown.includes(fin)) add('printCounter', e, shown, { final: fin, note: 'the printed counter is not at its final value' }, e.getBoundingClientRect());
    }
    // SVG counters (Story SvgCounter) carry data-svg-final: SVG exposes no innerText,
    // so read the painted <text>/<tspan> in the counter's own SVG.
    for (const e of root.querySelectorAll('[data-svg-final]')) {
      const fin = clean(e.getAttribute('data-svg-final')); if (!fin) continue;
      const host = e.closest('svg') || e.parentNode;
      const painted = [...host.querySelectorAll('text, tspan')].filter(t => { const c = CS(t);
        return c.display !== 'none' && c.visibility !== 'hidden' && +c.opacity > 0.05; }).map(t => clean(t.textContent)).join(' ');
      if (!painted.includes(fin)) add('printCounter', e, painted.slice(0, 60), { final: fin, note: 'the printed SVG counter is not at its final value' }, e.getBoundingClientRect());
    }
    // 3. pins must print as ordinary stacked scenes
    for (const e of els) {
      const cs = CS(e);
      if (cs.display === 'none') continue;
      if ((cs.position === 'sticky' || cs.position === 'fixed') && e.getBoundingClientRect().height >= vh * 0.8)
        add('printPinned', e, null, { position: cs.position, note: 'a sticky stage in print clips its scene or repeats it on every page' }, e.getBoundingClientRect());
      if (e.classList && e.classList.contains('pin-wrap')) {
        const r = e.getBoundingClientRect(); let cb = r.top;
        for (const d of e.querySelectorAll('svg, p, h2, h3, table, li')) { const q = d.getBoundingClientRect(); if (q.height > 0) cb = Math.max(cb, q.bottom); }
        if (r.bottom - cb > 300) add('printPinned', e, null, { blankPx: Math.round(r.bottom - cb), note: 'the pin spacer prints as blank space (blank pages)' }, r);
      }
    }
    // 4. solid dark blocks (ink on white is the print contract) and 5. empty scenes
    for (const e of els) {
      const cs = CS(e); if (cs.display === 'none') continue;
      const bg = parseColor(cs.backgroundColor); if (!bg || bg[3] < 0.9) continue;
      const r = e.getBoundingClientRect(); if (r.width * r.height < 40000) continue;
      if (lum(bg) < 0.25) add('printDark', e, null, { bg: hex(bg), w: Math.round(r.width), h: Math.round(r.height), note: 'prints as a solid dark block; print should be ink on white' }, r, meta.view === 'dash' ? 'P3' : 'P2');
    }
    for (const s of (isDash() ? sectionsOf(root) : scenesOf(root))) {
      const r = s.el.getBoundingClientRect(); if (r.height < 400) continue;
      let lo = Infinity, hi = -Infinity;
      const ext = q => { if (q.height > 0 && q.width > 0) { lo = Math.min(lo, q.top); hi = Math.max(hi, q.bottom); } };
      for (const d of s.el.querySelectorAll('svg, p, h1, h2, h3, table, li, img, canvas, video, iframe')) ext(d.getBoundingClientRect());
      // text set straight into divs and spans (a footer, a credits block) is content too
      const tw = document.createTreeWalker(s.el, NodeFilter.SHOW_TEXT), rg = document.createRange();
      while (tw.nextNode()) { const n = tw.currentNode; if (!n.nodeValue.trim() || (n.parentElement && n.parentElement.closest('svg'))) continue; rg.selectNodeContents(n); ext(rg.getBoundingClientRect()); }
      const used = isFinite(lo) ? (hi - lo) / r.height : 0;
      if (used < 0.35) add('printBlank', s.el, s.heading, { heightPx: Math.round(r.height), contentShare: +used.toFixed(2), note: 'mostly empty in print: a blank gap or page' }, r);
    }
    // 6. marks that change meaning on paper: a "ring" faked by filling a dot with
    // the dark screen ground and a white stroke prints as a solid dark disc (the
    // white ring vanishes on white paper); a white mark or swatch with no dark
    // edge prints as nothing at all
    const DARKG = ['#012A2D', '#003F2D', '#032842'].map(parseColor);
    // Ink pins with a white halo and company-colour dots re-inked for print are real
    // discs, not faked rings. To tell a re-inked dot, candidates are re-read under
    // screen styles: the stylesheets' print rules are switched off and their screen
    // rules on for one synchronous read, then restored. (The screen ground can't be
    // read this way: the engine sets it per active scene from script.)
    const underScreen = fn => {
      const undo = [];
      const flip = ml => { const t = ml && ml.mediaText; if (!t) return; let n = null;
        if (/^\s*not\s+print\b/i.test(t)) n = t.replace(/not\s+print/i, 'all');
        else if (/\bprint\b/i.test(t)) { if (!/\bscreen\b/i.test(t)) n = 'not all'; }
        else if (/\bscreen\b/i.test(t)) n = t.replace(/\bscreen\b/gi, 'all');   // keeps any width condition
        if (n != null) { undo.push([ml, t]); ml.mediaText = n; } };
      const walk = rules => { for (const ru of rules || []) { if (ru.media && ru.cssRules) { flip(ru.media); walk(ru.cssRules); } else if (ru.cssRules) walk(ru.cssRules); } };
      for (const sh of document.styleSheets) { try { flip(sh.media); walk(sh.cssRules); } catch (_) { /* cross-origin sheet */ } }
      try { return fn(); } finally { for (const [ml, t] of undo.reverse()) { try { ml.mediaText = t; } catch (_) { /* keep going */ } } }
    };
    const ringCand = [], darkRings = [], vanishing = [];
    for (const svg of root.querySelectorAll('svg')) {
      if (svg.closest('.leaflet-container') || !svg.getClientRects().length) continue;
      for (const e of svg.querySelectorAll('circle, rect, path, polygon, ellipse')) {
        if (e.closest('defs, pattern, clipPath, mask, marker, symbol')) continue;
        const cs = CS(e); if (cs.display === 'none' || cs.visibility === 'hidden' || effOp(e) < 0.3) continue;
        const r = e.getBoundingClientRect(); if (r.width < 3 || r.height < 3) continue;
        const f = /url/.test(cs.fill || '') ? null : parseColor(cs.fill), fa = f ? f[3] * (+cs.fillOpacity) : 0;
        const s = cs.stroke && cs.stroke !== 'none' && !/url/.test(cs.stroke) ? parseColor(cs.stroke) : null, sa = s ? s[3] * (+cs.strokeOpacity) : 0;
        const small = r.width <= 40 && r.height <= 40;
        if (small && f && fa > 0.5 && (lum(f) < 0.03 || DARKG.some(d => dE(d, f) < 3)) && s && sa > 0.3 && lum(s) > 0.8) ringCand.push(e);
        else if (f && fa > 0.5 && lum(f) > 0.93 && (!s || sa < 0.3 || lum(s) > 0.9) && titleOf(e)) vanishing.push(e);
      }
    }
    // A candidate is a faked ring when its fill is a ground-only colour (the dark
    // grounds are never ink), or when, on paper, it merges with another dark mark in
    // the same chart that has no light edge. A dot whose screen fill is a real colour
    // (a company colour re-inked for print) is a disc on both, so it is skipped.
    if (ringCand.length) {
      const scr = new Map();
      underScreen(() => { for (const e of ringCand) { const c = CS(e); scr.set(e, c.display === 'none' ? null : c.fill); } });
      // #032842 is also categorical slot 1 on light grounds (design-system §3b), so a
      // slot-1 dot is a real company colour, not a faked ring; only #012A2D is ground-only.
      const GROUND_ONLY = ['#012A2D'].map(parseColor);
      const darkPlain = new Map();
      const plainOf = svg => { if (darkPlain.has(svg)) return darkPlain.get(svg); const out = [];
        for (const o of svg.querySelectorAll('circle, rect, path, polygon, ellipse')) {
          if (ringCand.includes(o) || o.closest('defs, pattern, clipPath, mask, marker, symbol')) continue;
          const c = CS(o); if (c.display === 'none' || c.visibility === 'hidden' || effOp(o) < 0.3 || /url/.test(c.fill || '')) continue;
          const q = o.getBoundingClientRect(); if (q.width < 3 || q.height < 3 || q.width > 40 || q.height > 40) continue;
          const of = parseColor(c.fill); if (!of || of[3] * (+c.fillOpacity) < 0.5 || lum(of) > 0.09) continue;
          const os = c.stroke && c.stroke !== 'none' && !/url/.test(c.stroke) ? parseColor(c.stroke) : null;
          if (os && os[3] * (+c.strokeOpacity) > 0.3 && lum(os) > 0.5) continue;       // it keeps a light edge too
          out.push(of); }
        darkPlain.set(svg, out); return out; };
      for (const e of ringCand) {
        const st = scr.get(e); if (!st) continue;                                        // print-only mark: drawn for paper
        const sf = /url/.test(st) ? null : parseColor(st); if (sf && sf[3] >= 0.5 && lum(sf) > 0.1) continue;
        const f = parseColor(CS(e).fill);
        const groundOnly = lum(f) < 0.012 || GROUND_ONLY.some(g => dE(g, f) < 3);
        if (groundOnly || (e.ownerSVGElement && plainOf(e.ownerSVGElement).some(of => dE(of, f) < 15))) darkRings.push(e);
      }
    }
    for (const e of root.querySelectorAll('span, i, b, em, div')) {
      if (e.children.length || e.textContent.trim() || !e.getClientRects().length) continue;
      const r = e.getBoundingClientRect(); if (r.width < 5 || r.width > 20 || r.height < 5 || r.height > 20) continue;
      if (!e.closest('li, .lg-row, label, [class*=key i], [class*=legend i]') || e.closest('table')) continue;
      const lk = lookOf(e);
      const white = c => c && lum(c) > 0.9;
      if (!lk.pattern && (!lk.fill || white(lk.fill)) && (!lk.stroke || white(lk.stroke))) vanishing.push(e);
    }
    if (darkRings.length || vanishing.length) {
      const ex = [...darkRings, ...vanishing].slice(0, 4).map(e => (titleOf(e) || clean((e.closest('li, .lg-row, label') || e.parentElement || e).textContent) || sel(e)).slice(0, 50));
      add('printMarks', darkRings[0] || vanishing[0], ex.join(' · '), { darkRings: darkRings.length || undefined, vanishing: vanishing.length || undefined,
        note: 'on paper these marks change meaning: ground-filled "rings" with a white stroke print as solid dark discs, and white marks or swatches with no dark edge disappear. Draw hollow rings with fill:none and a toned stroke, and give white marks an edge in print' }, (darkRings[0] || vanishing[0]).getBoundingClientRect());
    }
    return result();
  }

  /* Opaque fixed/sticky layers currently stuck at the top (app bar, sticky
     filter bar...). Flow text beneath them is simply scrolled out of sight. */
  const occluders = [];
  if (!PRINT) for (const e of [...INV.fixed, ...INV.sticky]) {
    const r = e.getBoundingClientRect();
    if (r.height >= vh * 0.9 || r.width < vw * 0.5 || r.bottom <= 0 || r.top >= vh) continue;
    if (!INV.fixed.has(e) && !atStickyPos(e)) continue;
    const L = layersOf(e);
    if (!(Array.isArray(L) && L.some(l => Array.isArray(l) && l[3] > 0.6))) continue;
    occluders.push({ e, r });
  }
  occluders.sort((a, b) => a.r.top - b.r.top);

  /* ------------------------------------------------------ 1. collect text */
  const SKIP = /^(script|style|noscript|template|option|optgroup|title|desc|metadata|textarea|select|head)$/;
  const texts = [], hiddenTexts = [];
  const rng = document.createRange();
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (n.nodeType === 1) {
        if (SKIP.test(n.localName) || n.hidden === true) return NodeFilter.FILTER_REJECT;
        if (CS(n).display === 'none') return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_SKIP;
      }
      return /\S/.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  while (tw.nextNode()) {
    const t = tw.currentNode, el = t.parentElement;
    if (!el) continue;
    const isSvg = el instanceof SVGElement;
    if (isSvg && !(el instanceof SVGTextContentElement)) continue;
    let rects, bb;
    if (isSvg) { bb = el.getBoundingClientRect(); rects = [bb]; }
    else {
      rng.selectNodeContents(t);
      rects = [...rng.getClientRects()].filter(r => r.width > 0.5 && r.height > 0.5);
      bb = rng.getBoundingClientRect();
    }
    if (!rects.length || bb.width < 1 || bb.height < 1) continue;
    if (bb.bottom <= 0 || bb.top >= vh || bb.right <= 0 || bb.left >= vw) continue;
    const cs = CS(el);
    if (cs.visibility === 'hidden' || cs.visibility === 'collapse') continue;
    // closed <details>, content-visibility:hidden and similar still report rects
    if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true, contentVisibilityAuto: false })) continue;
    if (isSrOnly(el)) continue;
    const vis = visibleBox(el, bb);
    if (vis.w < 1 || vis.h < 1) continue;     // scrolled out of its scroller, or outside a clipping frame
    // Flow text scrolled under a stuck bar is out of sight: keep only the part
    // below it. (Text on a pinned/fixed layer under the bar is judged by underBar.)
    if (!fixedAnc(el)) {
      for (const o of occluders) {
        if (o.e.contains(el)) continue;
        if (vis.l >= o.r.left - 1 && vis.r <= o.r.right + 1 && vis.t >= o.r.top - 1 && vis.t < o.r.bottom) {
          vis.t = Math.min(vis.b, o.r.bottom); vis.h = Math.max(0, vis.b - vis.t);
        }
      }
      if (vis.h < 1) continue;
    }
    const op = effOp(el);
    if (op < 0.05) {
      if (!isSvg && bb.top > vh * 0.15 && bb.bottom < vh * 0.85 && bb.left >= 0 && bb.right <= vw) hiddenTexts.push({ el, bb, str: clean(t.nodeValue) });
      continue;
    }
    // keep only the line boxes that can be seen
    const seen = rects.filter(r => r.right > vis.l && r.left < vis.r && r.bottom > vis.t && r.top < vis.b);
    texts.push({ t, el, isSvg, rects: seen.length ? seen : rects, bb, vis, cs, op, str: clean(t.nodeValue) });
  }
  meta.texts = texts.length;

  const sizeOf = x => {
    const fs = parseFloat(x.cs.fontSize) || 0;
    if (x.isSvg) {
      const m = x.el.getScreenCTM && x.el.getScreenCTM();
      return m ? fs * Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) : fs;
    }
    return fs * cssScale(x.el);
  };

  /* -------------------------------------------- 2. contrast + covered text */
  const seenEl = new Set();
  const barLike = e => INV.bars.some(b => b === e || b.contains(e));
  for (const x of texts) {
    const el = x.el, r0 = x.rects[0];
    // sample the middle of the first visible line, inside the visible box
    const l = Math.max(r0.left, x.vis.l), rr = Math.min(r0.right, x.vis.r), tp = Math.max(r0.top, x.vis.t), bt = Math.min(r0.bottom, x.vis.b);
    const cx = Math.min(vw - 1, Math.max(0, (l + rr) / 2)), cy = Math.min(vh - 1, Math.max(0, (tp + bt) / 2));
    const prevPE = el.style.pointerEvents;
    el.style.pointerEvents = 'auto';
    let list = [];
    try { list = document.elementsFromPoint(cx, cy); } catch (e) { list = []; }
    el.style.pointerEvents = prevPE;
    const idx = list.indexOf(el);

    // covered: something other than the text's own ancestors paints over it.
    // Text on a pinned/fixed layer is also sampled near its top edge, which is
    // where an app bar bites first.
    if (!seenEl.has(el) && !PRINT) {
      const coverAt = (lst, pt) => {
        const i = lst.indexOf(el); if (i <= 0) return null;
        return lst.slice(0, i).filter(e => !el.contains(e) && !e.contains(el)).find(e => {
          const L = layersOf(e, pt);
          return L === 'image' || (Array.isArray(L) && L.some(l => Array.isArray(l) && l[3] > 0.6)) || (e instanceof SVGTextContentElement);
        }) || null;
      };
      const fa = fixedAnc(el);
      let top = coverAt(list, { x: cx, y: cy });
      if (!top && fa) {
        const y2 = Math.min(vh - 1, Math.max(0, tp + (bt - tp) * 0.2));
        el.style.pointerEvents = 'auto';
        try { top = coverAt(document.elementsFromPoint(cx, y2), { x: cx, y: y2 }); } catch (e) {}
        el.style.pointerEvents = prevPE;
      }
      if (top) {
        const coverFixed = fixedAnc(top);
        const fullScreen = (() => { const r = top.getBoundingClientRect(); return r.width >= vw * 0.9 && r.height >= vh * 0.9; })();
        const sameMap = top instanceof SVGElement && el.closest && el.closest('.leaflet-container') && top.closest('.leaflet-container');
        const modal = top.closest && top.closest('dialog, [role=dialog], [aria-modal=true]') && !(el.closest && el.closest('dialog, [role=dialog], [aria-modal=true]'));
        // name the thing on top; another text on top is a collision, not a cover
        const isText = top instanceof SVGTextContentElement;
        const what = isText ? 'text "' + clean(top.textContent).slice(0, 40) + '"' : sel(top);
        if (!fullScreen && !sameMap && !modal) {
          if (fa && !inBar(el) && atStickyPos(fa) && (barLike(top) || coverFixed)) {
            const control = !!(el.closest && el.closest('button, a, [role=button], summary, select'));
            if (barLike(top)) add('underBar', el, x.str, { by: 'app bar', hiddenPx: Math.round(INV.barBottom - x.bb.top), control: control || undefined }, x.bb,
                (heading(el) || control || sizeOf(x) >= 24) ? 'P1' : 'P2');
            else add(isText ? 'overlapText' : 'covered', el, x.str, { by: what, layer: coverFixed === fa ? undefined : sel(coverFixed), control: control || undefined }, x.bb,
                (control || heading(el)) ? 'P1' : 'P2');
          } else if (!fa && !coverFixed) {
            add(isText ? 'overlapText' : 'covered', el, x.str, { by: what }, x.bb, 'P2');
          }
        }
      }
    }
    if (seenEl.has(el)) continue;
    seenEl.add(el);

    // background actually painted beneath the text
    // (the text's own element paints its background beneath its glyphs)
    let below;
    if (idx >= 0) below = [el].concat(list.slice(idx + 1).filter(e => !el.contains(e)));
    else {
      // not hit-testable here: ancestors, plus (inside one svg) shapes drawn earlier
      const svgRoot = el.ownerSVGElement;
      below = [el].concat(list.filter(e => e !== el && !el.contains(e) && (e.contains(el) ||
        (svgRoot && svgRoot.contains(e) && (e.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)))));
    }
    let cands = [[255, 255, 255, 1]], uncertain = false;
    for (let k = below.length - 1; k >= 0; k--) {
      const L = layersOf(below[k], { x: cx, y: cy });
      if (L === 'image') { uncertain = true; continue; }
      for (const lay of L) {
        if (lay.gradient) {
          const nc = []; for (const c of cands) for (const g of lay.gradient) nc.push(over(g, c));
          cands = nc.slice(0, 8);
        } else cands = cands.map(c => over(lay, c));
      }
    }
    let fgStr = x.isSvg ? x.cs.fill : x.cs.color;
    if (x.isSvg && (!fgStr || fgStr === 'none')) fgStr = x.cs.stroke;
    if (!fgStr || /url\(/.test(fgStr)) continue;
    const fg0 = parseColor(fgStr); if (!fg0) continue;
    const fa = fg0[3] * (x.isSvg ? +x.cs.fillOpacity : 1) * x.op;
    const fg = [fg0[0], fg0[1], fg0[2], fa];
    // halo: a text-shadow ring, or an SVG stroke painted under the fill
    const halos = [];
    if (x.cs.textShadow && x.cs.textShadow !== 'none') {
      for (const s of (x.cs.textShadow.match(/(rgba?\([^)]*\)|color\([^)]*\))/g) || [])) { const c = parseColor(s); if (c && c[3] > 0.5) halos.push(c); }
    }
    if (x.isSvg && x.cs.stroke && x.cs.stroke !== 'none' && parseFloat(x.cs.strokeWidth) >= 1.5) {
      const c = parseColor(x.cs.stroke); if (c && c[3] > 0.5) halos.push(c);
    }
    let worst = Infinity, worstBg = null;
    for (const b of cands) {
      let cr = ratio(over(fg, b), b);
      for (const h of halos) { const hb = over(h, b); cr = Math.max(cr, ratio(over(fg, hb), hb)); }
      if (cr < worst) { worst = cr; worstBg = b; }
    }
    if (uncertain && !halos.length) continue;   // text over imagery: check the screenshot
    const size = sizeOf(x), w = +x.cs.fontWeight || 400;
    const large = size >= 24 || (size >= 18.66 && w >= 700);
    const need = large ? 3 : 4.5;
    if (worst < need - 0.005) {
      const thirdParty = !!(el.closest && el.closest('.leaflet-control-attribution'));
      add(x.op < 0.98 ? 'contrastDimmed' : 'contrast', el, x.str,
        { ratio: +worst.toFixed(2), need, px: +size.toFixed(1), weight: w, fg: hex(over(fg, worstBg)) + (fa < 0.999 ? ' (' + hex(fg0) + ' @' + fa.toFixed(2) + ')' : ''),
          bg: hex(worstBg), opacity: +x.op.toFixed(2), thirdParty: thirdParty || undefined }, x.bb,
        x.op < 0.98 ? 'P3' : (thirdParty ? 'P2' : 'P1'));
    }
  }

  /* ------------------------------------------- 3. ground vs text mode
     (screen only: in print the page is white paper whatever the mode says) */
  if (!PRINT && root.dataset && root.dataset.mode) {
    let list = [];
    try { list = document.elementsFromPoint(vw / 2, vh / 2); } catch (e) {}
    let c = [255, 255, 255, 1];
    for (let k = list.length - 1; k >= 0; k--) {
      const e = list[k];
      // the ground is whatever fills the whole viewport, not a chart tile at its centre
      const r = e.getBoundingClientRect();
      if (!(r.width >= vw * 0.9 && r.height >= vh * 0.9) && !e.contains(root)) continue;
      const L = layersOf(e, { x: vw / 2, y: vh / 2 }); if (L === 'image') continue;
      for (const lay of L) c = over(lay.gradient ? lay.gradient[0] : lay, c);
    }
    const Lg = lum(c), mode = root.dataset.mode;
    if ((mode === 'light' && Lg < 0.18) || (mode === 'dark' && Lg > 0.6))
      add('groundMismatch', root, null, { mode, paintedGround: hex(c), note: 'text is styled for a ' + mode + ' ground but the ground painted at the viewport centre is ' + (Lg < 0.18 ? 'dark' : 'light') });
  }

  /* ----------------------------------------- 4. size, clipping, tokens */
  const TOK = /(^|[^A-Za-z])(NaN|undefined|null|Infinity|\[object Object\])([^A-Za-z]|$)/;
  const PH = /\b(1950|1905|1900|1899)\b/;
  const seen2 = new Set();
  const inWideTable = el => { const t = el.closest && el.closest('table'); if (!t) return false; for (let a = t.parentElement; a && a !== root; a = a.parentElement) { if (/^(auto|scroll)$/.test(CS(a).overflowX)) return true; } return false; };
  for (const x of texts) {
    const el = x.el;
    if (TOK.test(x.str)) add('badToken', el, x.str, { token: x.str.match(TOK)[2] }, x.bb);
    if (PH.test(x.str) && !/\b(19[0-9]{2})\s*[-–]\s*(19|20)\d{2}\b/.test(x.str)) add('placeholderDate', el, x.str, { note: 'EverGreen writes 1950-01-01 / 1905-06-01 for "no date"; verify this year is real' }, x.bb);
    if (seen2.has(el)) continue;
    seen2.add(el);
    const size = sizeOf(x);
    // screen floor 10px; print floor 7px (about 5pt on A4), since print is read close up
    const floor = PRINT ? O.printMinFont : O.minFont;
    if (size < floor - 0.25) add('smallText', el, x.str, { px: +size.toFixed(1), declared: x.cs.fontSize, print: PRINT || undefined },
      x.bb, size < (PRINT ? 5.5 : 8) ? 'P1' : (el.closest('.leaflet-control-attribution') ? 'P3' : 'P2'));

    // clipped by an ancestor with overflow hidden/clip (text scrolled out of a
    // scroller is not clipped: a wide table in its frame is tableOverflow's job)
    const cv = visibleBox(el, x.bb, 'clip'), by = cv.by;
    const ellipsis = x.cs.textOverflow === 'ellipsis' || cv.ellipsis;
    const hidW = Math.max(0, cv.baseW - cv.w), hidH = Math.max(0, cv.baseH - cv.h);
    if (by && (hidW > 2 || hidH > Math.max(2, x.bb.height * 0.25)) && !inWideTable(el)) {
      const bySel = sel(by);
      if (ellipsis && hidH <= 2) add('truncated', el, x.str, { by: bySel, hiddenPx: Math.round(hidW), title: !!(el.closest('[title]')) }, x.bb, el.closest('[title]') ? 'P3' : 'P2');
      else add('clipped', el, x.str, { by: bySel, hiddenW: Math.round(hidW), hiddenH: Math.round(hidH),
        note: (by === root || by === document.body) ? 'cut off at the page edge' : undefined }, x.bb, heading(el) ? 'P1' : 'P2');
    }
    if (x.isSvg && /…$|\.\.\.$/.test(x.str)) {
      const t = titleOf(el.localName === 'tspan' ? el.parentElement : el) || titleOf(el.parentElement || el);
      add('truncated', el, x.str, { note: 'label shortened with an ellipsis', title: !!t }, x.bb, t ? 'P3' : 'P2');
    }
  }
  // screen-reader text and tooltips also must not say NaN
  for (const e of root.querySelectorAll('[aria-label], title')) {
    const s = e.localName === 'title' ? e.textContent : e.getAttribute('aria-label');
    if (TOK.test(s)) add('badTokenHidden', e.localName === 'title' ? e.parentElement : e, s, { where: e.localName === 'title' ? 'svg <title> tooltip' : 'aria-label' });
  }
  for (const h of hiddenTexts) add('hiddenText', h.el, h.str, { note: 'text in the middle of the viewport is at opacity 0 after settling (a reveal that never fired, or a finished state that depends on scroll)' }, h.bb);

  /* ------------------------------------------------ 5. overlapping text */
  const blockOf = el => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      if (e instanceof SVGElement) { if (e.localName === 'text' || e.localName === 'foreignObject') return e; continue; }
      const d = CS(e).display; if (d !== 'inline' && d !== 'contents') return e;
    }
    return document.body;
  };
  // Pairs on different fixed/sticky layers are skipped: flow text scrolling
  // under the app bar is normal (underBar covers the pinned case).
  const tb = texts.map(x => ({ x, blk: blockOf(x.el), layer: fixedAnc(x.el), rs: x.rects.map(r => shrink(r, x.isSvg ? 0.16 : 0.2, 0.5)) }));
  const olSeen = new Set();
  for (let i = 0; i < tb.length; i++) {
    for (let j = i + 1; j < tb.length; j++) {
      const A = tb[i], B = tb[j];
      if (A.layer !== B.layer) continue;
      if (A.blk === B.blk || A.blk.contains(B.blk) || B.blk.contains(A.blk)) continue;
      if (inter(A.x.bb, B.x.bb) <= 0) continue;
      let hit = 0;
      for (const ra of A.rs) for (const rb of B.rs) {
        const ov = inter(ra, rb);
        if (ov > 3 && Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left) > 1.5 && Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > 1.5) hit = Math.max(hit, ov);
      }
      if (!hit) continue;
      const key = [A.x.str, B.x.str].sort().join('|');
      if (olSeen.has(key)) continue; olSeen.add(key);
      add('overlapText', A.x.el, A.x.str + '  ×  ' + B.x.str, { overlapPx2: Math.round(hit), other: whereOf(B.x.el).node }, A.x.bb,
        (A.x.op < 0.98 || B.x.op < 0.98) ? 'P2' : 'P1');
    }
  }

  /* ------------------------------------------- 6. labels against marks */
  const mkM = new Map();
  const isCircle = e => e.localName === 'circle' || e.localName === 'ellipse' ||
    (e.localName === 'path' && /a/i.test(e.getAttribute('d') || '') && (() => { const r = e.getBoundingClientRect(); return Math.abs(r.width - r.height) < 2; })());
  const marksOf = svg => {
    if (mkM.has(svg)) return mkM.get(svg);
    const sr = svg.getBoundingClientRect(), sa = Math.max(1, sr.width * sr.height);
    const out = [];
    for (const e of svg.querySelectorAll('rect, circle, ellipse, path, polygon')) {
      if (e.closest('defs, pattern, clipPath, mask, marker, symbol')) continue;
      const cs = CS(e); if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      if (!cs.fill || cs.fill === 'none') continue;
      const fc = /url\(/.test(cs.fill) ? [0, 0, 0, 1] : (parseColor(cs.fill) || [0, 0, 0, 0]);
      const op = effOp(e) * (+cs.fillOpacity) * fc[3];
      if (op < 0.15) continue;
      const r = e.getBoundingClientRect(); if (r.width < 2 || r.height < 2) continue;
      // a shaded reference band (a translucent full-height or full-width rect) is context, not a mark
      if (e.localName === 'rect' && op < 0.6 && (r.height >= sr.height * 0.6 || r.width >= sr.width * 0.6)) continue;
      out.push({ e, r, circle: isCircle(e), area: r.width * r.height, big: r.width * r.height > 0.25 * sa, op });
    }
    mkM.set(svg, out); return out;
  };
  const circleFrac = (rb, m) => {   // share of the label box inside a circular mark
    const cx = (m.r.left + m.r.right) / 2, cy = (m.r.top + m.r.bottom) / 2, rad = (m.r.width + m.r.height) / 4;
    let n = 0, k = 0;
    for (let i = 0; i < 8; i++) for (let j = 0; j < 4; j++) {
      const X = rb.left + (i + 0.5) / 8 * rb.width, Y = rb.top + (j + 0.5) / 4 * rb.height; k++;
      if (Math.hypot(X - cx, Y - cy) < rad) n++;
    }
    return n / k;
  };
  const markHit = (lb, m) => {
    if (inter(lb, m.r) <= 0) return 0;
    if (m.circle) { const f = circleFrac(lb, m); return f >= 0.999 ? 0 : f; }
    const inside = lb.left >= m.r.left - 1 && lb.right <= m.r.right + 1 && lb.top >= m.r.top - 1 && lb.bottom <= m.r.bottom + 1;
    return inside ? 0 : inter(lb, m.r) / Math.max(1, lb.width * lb.height);
  };
  const lmSeen = new Set();
  for (const x of texts) {
    if (!x.isSvg || x.el.localName === 'tspan' && lmSeen.has(x.el.parentElement)) continue;
    const svg = outerSvg(x.el); if (!svg) continue;
    const lb = shrink(x.bb, 0.16, 0.5);
    let worst = 0, wm = null;
    for (const m of marksOf(svg)) { if (m.big) continue; const f = markHit(lb, m); if (f > worst) { worst = f; wm = m; } }
    if (worst > 0.12 && !lmSeen.has(x.el)) {
      lmSeen.add(x.el);
      const t = titleOf(wm.e);
      add('labelMark', x.el, x.str, { share: +worst.toFixed(2), mark: wm.e.localName + (t ? ' "' + t.slice(0, 40) + '"' : '') }, x.bb);
    }
  }
  // HTML labels on a map (Leaflet): against the markers and other places' points
  for (const x of texts) {
    if (x.isSvg) continue;
    const mapEl = x.el.closest && x.el.closest('.leaflet-container, [data-qa-map]');
    if (!mapEl || x.el.closest('.leaflet-control-container, .leaflet-popup, .leaflet-control')) continue;
    const lb = shrink(x.bb, 0.18, 0.5);
    let worst = 0;
    for (const svg of mapEl.querySelectorAll('svg')) for (const m of marksOf(svg)) { if (m.big) continue; worst = Math.max(worst, markHit(lb, m)); }
    if (worst > 0.15) add('labelMark', x.el, x.str, { share: +worst.toFixed(2), mark: 'map marker' }, x.bb);
    const own = x.el.parentElement;
    for (const d of mapEl.querySelectorAll('i, b, span, div')) {
      if (d === x.el || own.contains(d) || d.contains(x.el) || d.textContent.trim()) continue;
      const r = d.getBoundingClientRect(); if (r.width < 2 || r.width > 9 || r.height < 2 || r.height > 9) continue;
      const bg = parseColor(CS(d).backgroundColor); if (!bg || bg[3] < 0.5) continue;
      if (inter(lb, r) > 1) { add('labelMark', x.el, x.str, { mark: 'another place\'s point', note: 'the label sits on a different town\'s dot' }, x.bb); break; }
    }
  }

  /* --------------------------- 6b. lines and frames running through text
     A today line, a threshold, a dashed frame or a leader that passes
     through a label (in and out the other side). Gridline families (3+
     parallel lines of one extent) are the chart's scale and are skipped. */
  const svgsAll = [...root.querySelectorAll('svg')].filter(s => !s.ownerSVGElement && !s.closest('.leaflet-container')).filter(s => {
    const r = s.getBoundingClientRect(); return r.width > 30 && r.height > 20 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw && effOp(s) > 0.05;
  });
  const strokeM = new Map();
  const strokesOf = svg => {
    if (strokeM.has(svg)) return strokeM.get(svg);
    const sr = svg.getBoundingClientRect(), sa = Math.max(1, sr.width * sr.height);
    const out = [];
    for (const e of svg.querySelectorAll('line, polyline, path, rect, circle, ellipse, polygon')) {
      if (e.closest('defs, pattern, clipPath, mask, marker, symbol')) continue;
      const cs = CS(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || !cs.stroke || cs.stroke === 'none' || /url\(/.test(cs.stroke)) continue;
      const sc = parseColor(cs.stroke); if (!sc) continue;
      if (effOp(e) * (+cs.strokeOpacity) * sc[3] < 0.25) continue;
      const m = e.getScreenCTM(); if (!m) continue;
      const k = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) || 1;
      if ((parseFloat(cs.strokeWidth) || 0) * k < 0.6) continue;
      if (!/^(line|polyline)$/.test(e.localName) && cs.fill && cs.fill !== 'none') {
        const f = /url\(/.test(cs.fill) ? [0, 0, 0, 1] : parseColor(cs.fill);
        if (f && f[3] * (+cs.fillOpacity) * effOp(e) > 0.3) continue;   // outline of a filled mark: labelMark's job
      }
      const r = e.getBoundingClientRect();
      if (!/^(line|rect)$/.test(e.localName) && r.width * r.height > 0.3 * sa) continue;      // coastlines and backdrops
      let len = 0; try { len = e.getTotalLength(); } catch (err) { len = 0; }
      if (!len) continue;
      const n = Math.min(900, Math.max(8, Math.ceil(len * k / 1.5)));
      const pts = [];
      for (let i = 0; i <= n; i++) { const p = e.getPointAtLength(len * i / n); const q = new DOMPoint(p.x, p.y).matrixTransform(m); pts.push([q.x, q.y]); }
      out.push({ e, r, pts, dash: !!(cs.strokeDasharray && cs.strokeDasharray !== 'none'), colour: hex(sc), grid: false });
    }
    const fam = new Map();
    for (const s of out) {
      if (s.e.localName !== 'line' && s.e.localName !== 'path') continue;
      const hz = s.r.height < 1.5 && s.r.width > 20, vt = s.r.width < 1.5 && s.r.height > 20;
      if (!hz && !vt) continue;
      const key = (hz ? 'h' : 'v') + ':' + Math.round((hz ? s.r.left : s.r.top) / 4) + ':' + Math.round((hz ? s.r.right : s.r.bottom) / 4);
      if (!fam.has(key)) fam.set(key, []); fam.get(key).push(s);
    }
    for (const g of fam.values()) if (g.length >= 3) for (const s of g) s.grid = true;
    strokeM.set(svg, out); return out;
  };
  const through = (tbx, s) => {
    if (s.r.right < tbx.left || s.r.left > tbx.right || s.r.bottom < tbx.top || s.r.top > tbx.bottom) return null;
    let first = -1, last = -1, n = 0, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    s.pts.forEach(([x, y], i) => {
      if (x >= tbx.left && x <= tbx.right && y >= tbx.top && y <= tbx.bottom) {
        if (first < 0) first = i; last = i; n++;
        x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      }
    });
    if (n < 2 || first === 0 || last === s.pts.length - 1) return null;     // it ends inside: a leader touching its label
    return ((y1 - y0) >= tbx.height * 0.75 || (x1 - x0) >= tbx.width * 0.6) ? { x: (x0 + x1) / 2, y: (y0 + y1) / 2 } : null;
  };
  const haloed = x => (x.cs.textShadow && x.cs.textShadow !== 'none') ||
    (x.isSvg && x.cs.stroke && x.cs.stroke !== 'none' && parseFloat(x.cs.strokeWidth) >= 1.5 && /stroke/.test(x.cs.paintOrder || ''));
  const backed = (x, s) => {   // an opaque shape drawn after the stroke and before the text, under the whole label
    const svg = outerSvg(x.el) || outerSvg(s.e); if (!svg) return false;
    for (const m of marksOf(svg)) {
      if (m.op < 0.9) continue;
      if (!(s.e.compareDocumentPosition(m.e) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      if (x.isSvg && !(m.e.compareDocumentPosition(x.el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      if (m.r.left <= x.bb.left + 1 && m.r.right >= x.bb.right - 1 && m.r.top <= x.bb.top + 1 && m.r.bottom >= x.bb.bottom - 1) return true;
    }
    return false;
  };
  const htmlLines = [];
  for (const e of root.querySelectorAll('*')) {
    const cs = CS(e);
    if (!/^(absolute|fixed)$/.test(cs.position) || (cs.transform && cs.transform !== 'none') || e.closest('.leaflet-container')) continue;
    if (e instanceof SVGElement || e.textContent.trim()) continue;
    const r = e.getBoundingClientRect(); if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > vh) continue;
    if (effOp(e) < 0.25) continue;
    const sides = [['Top', r.left, r.top, r.right, r.top], ['Bottom', r.left, r.bottom, r.right, r.bottom], ['Left', r.left, r.top, r.left, r.bottom], ['Right', r.right, r.top, r.right, r.bottom]];
    let any = false;
    for (const [sd, a, b, c, d] of sides) {
      if ((parseFloat(cs['border' + sd + 'Width']) || 0) < 1 || /none|hidden/.test(cs['border' + sd + 'Style'])) continue;
      const bc = parseColor(cs['border' + sd + 'Color']); if (!bc || bc[3] < 0.3) continue;
      htmlLines.push({ e, seg: [a, b, c, d], dash: /dash|dot/.test(cs['border' + sd + 'Style']) }); any = true;
    }
    if (!any && (r.width <= 3 || r.height <= 3)) {
      const bg = parseColor(cs.backgroundColor);
      if (bg && bg[3] >= 0.3) htmlLines.push({ e, seg: r.width <= 3 ? [r.left + r.width / 2, r.top, r.left + r.width / 2, r.bottom] : [r.left, r.top + r.height / 2, r.right, r.top + r.height / 2], dash: false });
    }
  }
  const segThrough = (tbx, [a, b, c, d]) => {
    if (Math.abs(a - c) < 1.5) return a > tbx.left + 1 && a < tbx.right - 1 && Math.min(b, d) < tbx.top - 1 && Math.max(b, d) > tbx.bottom + 1;
    if (Math.abs(b - d) < 1.5) return b > tbx.top + 1 && b < tbx.bottom - 1 && Math.min(a, c) < tbx.left - 1 && Math.max(a, c) > tbx.right + 1;
    return false;
  };
  const ltSeen = new Set();
  const underOccluder = (pt, layer) => occluders.some(o => o.e !== layer && !(layer && o.e.contains(layer)) && pt.x >= o.r.left && pt.x <= o.r.right && pt.y >= o.r.top && pt.y <= o.r.bottom);
  for (const x of texts) {
    if (ltSeen.has(x.el) || x.el.closest('.leaflet-container')) continue;
    const tbx = shrink(x.bb, 0.2, 1);
    if (tbx.width < 3 || tbx.height < 3) continue;
    const layerT = fixedAnc(x.el);           // text and line must share a layer (app bar text vs a chart scrolled under it is not a crossing)
    let hit = null;
    for (const svg of svgsAll) {
      const sr = svg.getBoundingClientRect();
      if (inter(sr, x.bb) <= 0 || fixedAnc(svg) !== layerT) continue;
      for (const s of strokesOf(svg)) {
        if (s.grid || s.e === x.el || s.e.contains(x.el)) continue;
        const at = through(tbx, s); if (!at) continue;
        if (underOccluder(at, layerT)) continue;
        const below = !!(s.e.compareDocumentPosition(x.el) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (below && (haloed(x) || backed(x, s))) continue;
        hit = { line: s.e.localName + (s.e.localName === 'rect' ? ' frame' : ''), dashed: s.dash || undefined, colour: s.colour, over: below ? 'under the text' : 'over the text', at: [Math.round(at.x), Math.round(at.y)], title: titleOf(s.e) || undefined };
        break;
      }
      if (hit) break;
    }
    if (!hit) for (const h of htmlLines) {
      if (h.e.contains(x.el) || x.el.contains(h.e) || fixedAnc(h.e) !== layerT) continue;
      if (segThrough(tbx, h.seg)) { hit = { line: 'html ' + (h.dash ? 'dashed ' : '') + 'rule/frame ' + sel(h.e) }; break; }
    }
    if (hit) { ltSeen.add(x.el); add('lineThroughText', x.el, x.str, Object.assign(hit, { note: 'a line or frame runs through this label: move the label, stop the line short of it, or give the label a ground-coloured halo' }), x.bb); }
  }

  /* ------------------------------ 7. svg structure: scales, legends, tiles */
  const svgs = svgsAll.concat(INV.bars.flatMap(b => [...b.querySelectorAll('svg')]));
  const ptOf = (line, xa, ya) => { const m = line.getScreenCTM(); if (!m) return null; const p = new DOMPoint(xa, ya).matrixTransform(m); return p; };
  const distBox = (p, r) => Math.hypot(Math.max(r.left - p.x, 0, p.x - r.right), Math.max(r.top - p.y, 0, p.y - r.bottom));
  const NR = /not recorded|n\/r|no (usable |recorded )?(date|expiry|epc|rent|record|data|lease)|unrated|undated|unknown|missing|not on record|no .{0,20} on record|\bno\b[^·|]{0,30}\brecorded\b|none recorded|not dated|no value|without (a |an )?(date|record|epc|rent)/i;
  const panelOf = e => (e.closest && e.closest('.blk, figure, .panel, [data-panel], .pin-in, .scene-in, .legend, section')) || root;
  const legendEntries = new Map();   // legend container -> [{label, fill, stroke, ring, pattern, el, r}]
  const addEntry = (cont, entry) => { if (!legendEntries.has(cont)) legendEntries.set(cont, []); legendEntries.get(cont).push(entry); };
  for (const svg of svgs) {
    const sr = svg.getBoundingClientRect(), sa = sr.width * sr.height, diag = Math.hypot(sr.width, sr.height);
    const marks = marksOf(svg);
    const svgTexts = [...svg.querySelectorAll('text')].filter(t => effOp(t) > 0.3 && t.getBoundingClientRect().width > 1);
    // leader lines that do not touch a mark
    for (const ln of svg.querySelectorAll('line')) {
      if (ln.closest('defs, pattern')) continue;
      if (effOp(ln) < 0.2 || CS(ln).stroke === 'none') continue;
      const a = ptOf(ln, +ln.getAttribute('x1') || 0, +ln.getAttribute('y1') || 0), b = ptOf(ln, +ln.getAttribute('x2') || 0, +ln.getAttribute('y2') || 0);
      if (!a || !b) continue;
      const dx = Math.abs(a.x - b.x), dy = Math.abs(a.y - b.y), len = Math.hypot(dx, dy);
      if (dx < 4 || dy < 4 || len < 6 || len > diag * 0.4) continue;
      const near = p => marks.reduce((m, k) => Math.min(m, k.circle ? Math.max(0, Math.hypot(p.x - (k.r.left + k.r.right) / 2, p.y - (k.r.top + k.r.bottom) / 2) - (k.r.width + k.r.height) / 4) : distBox(p, k.r)), Infinity);
      const gap = Math.min(near(a), near(b));
      if (gap > 4) add('floatingLeader', ln, null, { gapPx: Math.round(gap), note: 'a leader line should start on its mark; check it uses the same scale as the bars' }, box(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)));
    }
    // the top gridline must sit at or above the tallest bar (and the last
    // vertical gridline beyond the longest horizontal bar)
    {
      const fam = new Map();
      for (const s of strokesOf(svg)) {
        if (s.e.localName !== 'line' || !s.grid) continue;
        const hz = s.r.height < 1.5;
        const key = (hz ? 'h' : 'v') + ':' + Math.round((hz ? s.r.left : s.r.top) / 4) + ':' + Math.round((hz ? s.r.right : s.r.bottom) / 4);
        if (!fam.has(key)) fam.set(key, { hz, lines: [] }); fam.get(key).lines.push(s.r);
      }
      for (const f of fam.values()) {
        const L = f.lines;
        if (f.hz) {
          const top = Math.min(...L.map(r => r.top)), base = Math.max(...L.map(r => r.top)), left = Math.min(...L.map(r => r.left)), right = Math.max(...L.map(r => r.right));
          if (right - left < sr.width * 0.3) continue;
          // a column is its stacked segments chained up from the baseline
          const byCol = new Map();
          for (const m of marks) {
            if (m.circle || m.e.localName !== 'rect' || m.op < 0.3 || m.r.left < left - 2 || m.r.right > right + 2 || m.r.width >= (right - left) * 0.5) continue;
            const k = Math.round(m.r.left) + ':' + Math.round(m.r.width);
            if (!byCol.has(k)) byCol.set(k, []); byCol.get(k).push(m);
          }
          const cols = [];
          for (const segs of byCol.values()) {
            segs.sort((a, b) => b.r.bottom - a.r.bottom);
            if (Math.abs(segs[0].r.bottom - base) > 2.5) continue;
            let t = segs[0].r.top, topSeg = segs[0];
            for (const s of segs.slice(1)) if (Math.abs(s.r.bottom - t) <= 2.5) { t = s.r.top; topSeg = s; }
            cols.push({ top: t, seg: topSeg, r: box(segs[0].r.left, t, segs[0].r.right, segs[0].r.bottom) });
          }
          const over = cols.filter(c => c.top < top - 1.5).sort((a, b) => a.top - b.top);
          if (over.length) {
            const lab = svgTexts.find(t => { const q = t.getBoundingClientRect(); return Math.abs((q.top + q.bottom) / 2 - top) < 7 && q.right <= left + 6; });
            const b = over[0].r, vl = svgTexts.find(t => { const q = t.getBoundingClientRect(); return Math.abs((q.left + q.right) / 2 - (b.left + b.right) / 2) < 4 && q.bottom <= b.top + 2 && q.bottom > b.top - 30; });
            add('topGridBelowMax', over[0].seg.e, vl ? vl.textContent : titleOf(over[0].seg.e), { topLine: lab ? clean(lab.textContent) : undefined, overshootPx: Math.round(top - b.top), bars: over.length, note: 'the tallest bar rises above the top gridline: round the scale up to the next step' }, b);
          }
        } else {
          const lft = Math.min(...L.map(r => r.left)), rgt = Math.max(...L.map(r => r.left)), top = Math.min(...L.map(r => r.top)), bot = Math.max(...L.map(r => r.bottom));
          if (bot - top < 30) continue;
          const bars = marks.filter(m => !m.circle && m.e.localName === 'rect' && Math.abs(m.r.left - lft) <= 2.5 && m.r.top >= top - 2 && m.r.bottom <= bot + 2 && m.op >= 0.3);
          const over = bars.filter(m => m.r.right > rgt + 1.5).sort((a, b) => b.r.right - a.r.right);
          if (over.length) add('topGridBelowMax', over[0].e, titleOf(over[0].e), { overshootPx: Math.round(over[0].r.right - rgt), bars: over.length, note: 'the longest bar runs past the last gridline: round the scale up to the next step' }, over[0].r);
        }
      }
      // tick labels: equally spaced gridlines must carry equally stepped values
      // ("0 · 0.3m · 0.5m · 0.8m" is a 0.25m step rounded to 1 dp; "0.3m 0.3m" repeats)
      const tickVal = s => { const m = clean(s).replace(/[£$€,\s]/g, '').match(/^(-?\d+(?:\.\d+)?)(k|m|bn|%)?/i); if (!m) return null; const mul = { k: 1e3, m: 1e6, bn: 1e9 }[(m[2] || '').toLowerCase()] || 1; return +m[1] * mul; };
      for (const f of fam.values()) {
        // from the baseline, or from the left; one entry per position (the axis
        // line and the zero gridline are often two lines at the same place)
        const L = f.lines.slice().sort((a, b) => f.hz ? b.top - a.top : a.left - b.left)
          .filter((r, i, a) => i === 0 || Math.abs((f.hz ? r.top : r.left) - (f.hz ? a[i - 1].top : a[i - 1].left)) > 1);
        const lft = Math.min(...L.map(r => r.left)), rgt = Math.max(...L.map(r => r.right)), bot = Math.max(...L.map(r => r.bottom));
        const labs = [];
        for (const ln of L) {
          const t = svgTexts.find(tx => { const q = tx.getBoundingClientRect();
            return f.hz ? (Math.abs((q.top + q.bottom) / 2 - ln.top) < 6 && (q.right <= lft + 8 || q.left >= rgt - 8))
                        : (Math.abs((q.left + q.right) / 2 - ln.left) < 6 && q.top >= bot - 6); });
          if (!t) continue;
          const v = tickVal(t.textContent); if (v == null) continue;
          labs.push({ pos: f.hz ? ln.top : ln.left, v, s: clean(t.textContent) });
        }
        if (labs.length < 3) continue;
        const gaps = labs.slice(1).map((x, i) => Math.abs(x.pos - labs[i].pos));
        if (Math.max(...gaps) - Math.min(...gaps) > 1.5) continue;                     // not a uniform scale
        const steps = labs.slice(1).map((x, i) => x.v - labs[i].v);
        const s0 = steps.reduce((a, b) => a + b, 0) / steps.length;
        if (steps.some(d => d === 0) || steps.some(d => Math.abs(d - s0) > Math.abs(s0) * 0.02 + 1e-12))
          add('tickLabels', svg, labs.map(x => x.s).join(' · '), { step: +s0.toPrecision(3), repeated: steps.some(d => d === 0) || undefined,
            note: 'equally spaced gridlines carry unequal or repeated labels: the tick format is too coarse for its step; format ticks at the precision of the step, or use a 1/2/5 step' }, sr);
      }
    }
    // marks off their baseline mid-build: a bar whose designed bottom (its own
    // attributes, without the motion transforms) sits on the axis, or on the bar
    // below it, must be drawn there at every progress point
    {
      const designM = el => {
        let m = svg.getScreenCTM(); if (!m) return null;
        const chain = []; for (let a = el; a && a !== svg; a = a.parentNode) chain.push(a);
        for (const a of chain.reverse()) { const bv = a.transform && a.transform.baseVal; if (bv && bv.numberOfItems) { const t = bv.consolidate(); if (t) m = m.multiply(t.matrix); } }
        return m;
      };
      const hl = [...svg.querySelectorAll('line')].filter(l => !l.closest('defs, pattern') && effOp(l) > 0.1).map(l => l.getBoundingClientRect()).filter(r => r.height < 1.5 && r.width > sr.width * 0.4);
      const info = [];
      if (hl.length) for (const e of svg.querySelectorAll('rect')) {
        if (e.closest('defs, pattern, clipPath, mask, marker, symbol') || !e.hasAttribute('height')) continue;
        const cs = CS(e); if (!cs.fill || cs.fill === 'none' || cs.display === 'none') continue;
        const fc = /url/.test(cs.fill) ? [0, 0, 0, 1] : parseColor(cs.fill); if (!fc || fc[3] * (+cs.fillOpacity) * effOp(e) < 0.3) continue;
        const m = designM(e); if (!m) continue;
        const x = +e.getAttribute('x') || 0, y = +e.getAttribute('y') || 0, w = +e.getAttribute('width') || 0, h = +e.getAttribute('height') || 0;
        if (w <= 0 || h <= 1) continue;
        const p1 = new DOMPoint(x, y).matrixTransform(m), p2 = new DOMPoint(x + w, y + h).matrixTransform(m);
        const d = box(Math.min(p1.x, p2.x), Math.min(p1.y, p2.y), Math.max(p1.x, p2.x), Math.max(p1.y, p2.y));
        if (d.width > sr.width * 0.5 || d.height > sr.height * 0.9) continue;       // backgrounds and bands
        info.push({ e, d, r: e.getBoundingClientRect() });
      }
      const off = [];
      for (const o of info) {
        if (o.r.height < 1) continue;                                                // not drawn yet
        let target = null, from = null;
        const line = hl.find(L => Math.abs(L.top - o.d.bottom) <= 2 && o.d.left >= L.left - 2 && o.d.right <= L.right + 2);
        if (line) { target = line.top; from = 'axis'; }
        else {
          const below = info.find(q => q !== o && Math.abs(q.d.top - o.d.bottom) <= 1.5 &&
            Math.min(q.d.right, o.d.right) - Math.max(q.d.left, o.d.left) > 0.8 * Math.min(q.d.width, o.d.width));
          if (below && below.r.height >= 1) { target = below.r.top; from = 'the bar below'; }
        }
        if (target == null) continue;
        const gap = o.r.bottom - target;
        if (Math.abs(gap) > 2.5) off.push({ o, gap, from });
      }
      if (off.length) {
        const w = off.sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap))[0];
        add('offBaseline', w.o.e, titleOf(w.o.e), { marks: off.length, offsetPx: Math.round(w.gap), from: w.from,
          note: w.gap < 0 ? 'mid-build the mark floats above its baseline: it moves into place instead of growing from the axis'
                          : 'the mark hangs below its baseline: its growth origin is not the axis (check the origin after useFitHeight changes the height)' }, w.o.r);
      }
    }
    // one unit style per chart: "400k" and "0.47m" in one chart read as two scales
    {
      const u = { k: [], m: [] };
      for (const t of svgTexts) { const s = clean(t.textContent); const mm = s.match(/(^|[^\w.])[£$]?\d[\d,]*(\.\d+)?\s?(k|m)\b/i); if (mm) u[mm[3].toLowerCase()].push(s); }
      if (u.k.length && u.m.length) add('numberFormat', svg, u.k[0] + ' / ' + u.m[0], { k: u.k.length, m: u.m.length, note: 'thousands and millions mixed in one chart; use one unit (0.10m … 0.50m) for axis and labels' }, sr, (u.k.length >= 2 && u.m.length >= 2) ? 'P2' : 'P3');
    }
    // the not-recorded hatch is reserved for "not recorded"
    {
      const bad = [];
      for (const m of marks) {
        const f = CS(m.e).fill, u = f && f.match(/url\(["']?#([^"')]+)/);
        if (!u || !isNRHatch(u[1])) continue;
        let lab = titleOf(m.e);
        if (!lab) { const t = svgTexts.find(t => { const q = t.getBoundingClientRect(); return Math.abs((q.top + q.bottom) / 2 - (m.r.top + m.r.bottom) / 2) < 8 && q.right <= m.r.left + 4 && q.right > m.r.left - 260; }); lab = t ? clean(t.textContent) : null; }
        if (lab && !NR.test(lab)) bad.push({ m, lab });
      }
      if (bad.length) add('encodingClash', bad[0].m.e, bad[0].lab, { kind: 'hatch', marks: bad.length, examples: bad.slice(0, 3).map(b => b.lab.slice(0, 40)), note: 'the 45° hatch means "not recorded"; this mark is a real category drawn with it. Use --wash for a grouped tail' }, bad[0].m.r);
    }
    // legend swatches drawn in this svg, inside an explicit legend/key group:
    // a small shape with its label just to the right (data marks with labels
    // are not a legend, so nothing outside such a group is read as one)
    for (const e of svg.querySelectorAll('rect, circle, path, line')) {
      if (e.closest('defs, pattern, clipPath, mask, marker, symbol')) continue;
      const lg = e.closest('g[class*=legend i], g[class*=key i], g[id*=legend i], g[id*=key i], [data-legend]');
      if (!lg) continue;
      const r = e.getBoundingClientRect();
      const small = e.localName === 'line' ? (r.width >= 8 && r.width <= 30 && r.height <= 3) : (r.width >= 4 && r.width <= 20 && r.height >= 4 && r.height <= 20);
      if (!small || effOp(e) < 0.3) continue;
      const cy = (r.top + r.bottom) / 2;
      const t = [...lg.querySelectorAll('text')].find(tx => { const q = tx.getBoundingClientRect(); return q.left >= r.right + 1 && q.left <= r.right + 24 && Math.abs((q.top + q.bottom) / 2 - cy) <= 7; });
      if (!t) continue;
      const lab = clean(t.textContent);
      if (lab.length > 48 || (lab.match(/\d+/g) || []).length > 2) continue;
      addEntry(lg, Object.assign(lookOf(e), { label: lab, el: e, r, svg }));
    }
    // tiled charts (treemap, mosaic): every sizeable tile carries a label.
    // Translucent bands are not tiles, and a grid of equal cells is a unit
    // grid (one cell per unit, each with its own tooltip), not a treemap.
    {
      const rects = [...svg.querySelectorAll('rect')].filter(e => !e.closest('defs, pattern')).map(e => ({ e, r: e.getBoundingClientRect() }))
        .filter(o => {
          if (o.r.width <= 2 || o.r.height <= 2) return false;
          const cs = CS(o.e); if (!cs.fill || cs.fill === 'none') return false;
          const fc = /url\(/.test(cs.fill) ? [0, 0, 0, 1] : (parseColor(cs.fill) || [0, 0, 0, 0]);
          return fc[3] * (+cs.fillOpacity) * effOp(o.e) >= 0.5;
        });
      const uniq = new Map();
      for (const o of rects) uniq.set([o.r.left, o.r.top, o.r.width, o.r.height].map(v => Math.round(v)).join(','), o);
      const tiles = [...uniq.values()];
      const cover = tiles.reduce((a, o) => a + o.r.width * o.r.height, 0) / Math.max(1, sa);
      const big = tiles.filter(o => o.r.width * o.r.height >= 0.025 * sa && o.r.width * o.r.height < 0.9 * sa);
      const areas = big.map(o => o.r.width * o.r.height), mean = areas.reduce((a, b) => a + b, 0) / Math.max(1, areas.length);
      const cv = areas.length ? Math.sqrt(areas.reduce((a, b) => a + (b - mean) * (b - mean), 0) / areas.length) / Math.max(1, mean) : 0;
      const unitGrid = tiles.length >= 8 && cv < 0.25;
      if (tiles.length >= 5 && cover >= 0.6 && big.length >= 3 && !unitGrid) {
        // any rendered label counts, faded or not (a label mid-fade is not missing),
        // and a tile named by an outside label (on a leader) is labelled
        const allT = [...svg.querySelectorAll('text')].filter(t => t.getBoundingClientRect().width > 1 && effOp(t) > 0.02);
        const labs = allT.map(t => t.getBoundingClientRect());
        const names = allT.map(t => clean(t.textContent).toLowerCase()).filter(s => s.length >= 4).map(s => s.replace(/[…]|\.\.\.$/, '').split(' · ')[0].trim());
        const namedElsewhere = o => { const t = (titleOf(o.e) || '').toLowerCase(); return !!t && names.some(n => n.length >= 4 && t.startsWith(n.slice(0, Math.min(n.length, 14)))); };
        const miss = big.filter(o => !namedElsewhere(o) && !labs.some(l => { const cx = (l.left + l.right) / 2, cy = (l.top + l.bottom) / 2; return cx > o.r.left && cx < o.r.right && cy > o.r.top && cy < o.r.bottom; }))
          .sort((a, b) => b.r.width * b.r.height - a.r.width * a.r.height);
        if (miss.length) add('unlabelledTile', miss[0].e, titleOf(miss[0].e), { tiles: miss.length,
          examples: miss.slice(0, 4).map(o => (titleOf(o.e) || Math.round(o.r.width) + 'x' + Math.round(o.r.height) + 'px').slice(0, 50)),
          largestShare: +(miss[0].r.width * miss[0].r.height / sa).toFixed(3) }, miss[0].r);
      }
    }
    // accessible name for a chart
    if (!svg.closest('.leaflet-container') && svg.getAttribute('aria-hidden') !== 'true' && sr.width > 60 && sr.height > 40) {
      const named = svg.getAttribute('aria-label') || svg.getAttribute('aria-labelledby') || (svg.querySelector(':scope > title'));
      if (!named) add('a11yName', svg, null, { note: 'chart svg has no role="img" and aria-label (or is not aria-hidden)' }, sr);
      else if (TOK.test(svg.getAttribute('aria-label') || '')) add('badTokenHidden', svg, svg.getAttribute('aria-label'), { where: 'svg aria-label' }, sr);
    }
  }
  // HTML legend swatches: a small empty coloured box beside its label, in a
  // list or a key/legend container (never a table cell's status dot)
  // (every entry of a list is collected, on screen or not, so a uniform list of
  // twenty rows is recognised as data rather than as a pair of look-alikes)
  for (const e of root.querySelectorAll('span, i, b, em, div')) {
    if (e.children.length || e.textContent.trim()) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 5 || r.width > 20 || r.height < 5 || r.height > 20) continue;
    // (a dimmed row is a state such as "none in view", not a legend meaning)
    if (e.closest('table, .leaflet-container, [role=dialog], .drawer') || effOp(e) < 0.6) continue;
    const keyCont = e.closest('[class*=key i], [class*=legend i], [data-legend], [aria-label*=legend i]');
    const item = e.closest('li, .lg-row, label');
    if (!keyCont && !item) continue;
    const look = lookOf(e);
    if (!look.fill && !look.stroke && !look.pattern) continue;
    const host = item || e.parentElement;
    const label = host ? clean(host.innerText || host.textContent) : '';
    // a legend label is a short category name; a card or row of data is not a
    // legend, and a row reading "—" or 0 is the state "none in view"
    if (!label || label.length > 48 || (label.match(/\d+/g) || []).length > 2) continue;
    if (/[—–]\s*$|(^|\s)0(\.0+)?\s*(m|k|units?|%)?\s*$|\bnone\b/i.test(label)) continue;
    addEntry(keyCont || (item && item.parentElement) || host, Object.assign(look, { label, el: e, r, svg: null }));
  }
  // Two meanings, one look: two entries of one legend drawn the same, or chart
  // marks whose outline is a near miss of a legend ring (read as that state).
  // Three or more entries sharing a look are data items of one category, not
  // a legend, so only a pair counts.
  const normLab = s => s.replace(/[\d,.%£]+(\s?(m|k|sq ft|units?|leases?|yrs?))?/gi, '').replace(/\s+/g, ' ').trim().toLowerCase();
  for (const [cont, list0] of legendEntries) {
    const list = list0.filter((e, i) => list0.findIndex(o => o.el === e.el) === i);
    if (list.length < 2) continue;
    const groups = [];
    for (const e of list) { const g = groups.find(g => sameLook(g[0], e)); if (g) g.push(e); else groups.push([e]); }
    const onScreen = e => e.r.bottom > 0 && e.r.top < vh && e.r.right > 0 && e.r.left < vw;
    for (const g of groups) {
      const labs = [...new Set(g.map(e => normLab(e.label)))];
      if (g.length !== 2 || labs.length !== 2 || !g.some(onScreen)) continue;
      const [A, B] = g;
      const why = A.pattern ? 'the same pattern' : A.ring ? 'the same ring' + (A.stroke && B.stroke ? ' (ΔE ' + dE(A.stroke, B.stroke).toFixed(1) + ')' : '') : 'the same fill' + (A.fill && B.fill ? ' (ΔE ' + dE(A.fill, B.fill).toFixed(1) + ')' : '');
      add('encodingClash', A.el, A.label + '  ≈  ' + B.label, { kind: 'legend', why, note: 'two legend entries look the same but mean different things' }, A.r);
    }
    const rings = list.filter(e => e.ring && e.stroke && onScreen(e));
    if (!rings.length) continue;
    const legendEls = new Set(list.map(e => e.el));
    const panel = panelOf(cont);
    const svgsHere = panel === root ? svgs : svgs.filter(s => panel.contains(s));
    const reported = new Set();
    for (const svg of svgsHere) for (const e of svg.querySelectorAll('circle, path')) {
      if (legendEls.has(e) || e.closest('defs, pattern')) continue;
      const cs = CS(e); if (!cs.stroke || cs.stroke === 'none' || /url/.test(cs.stroke)) continue;
      const m = e.getScreenCTM(); const k = m ? Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) : 1;
      if ((parseFloat(cs.strokeWidth) || 0) * k < 1.2 || effOp(e) < 0.4) continue;
      const r = e.getBoundingClientRect(); if (r.width < 4 || r.width > 60) continue;
      const sc = parseColor(cs.stroke); if (!sc || sc[3] < 0.6) continue;
      if (lum(sc) > 0.85) continue;                       // white keylines separate marks
      const mDash = !!(cs.strokeDasharray && !/^(none|0(px)?)$/.test(cs.strokeDasharray.trim()));
      if (rings.some(g => dE(g.stroke, sc) < 1.5)) continue;   // it IS a legend ring
      const near = rings.find(g => !!g.dash === mDash && dE(g.stroke, sc) < 14);
      if (!near) continue;
      const key = hex(sc) + '|' + near.label; if (reported.has(key)) continue; reported.add(key);
      add('encodingClash', e, titleOf(e) || near.label, { kind: 'near-legend', markStroke: hex(sc), legend: near.label.slice(0, 50), legendStroke: hex(near.stroke), deltaE: +dE(near.stroke, sc).toFixed(1),
        note: 'this outline is a near miss of the legend ring "' + near.label.slice(0, 30) + '": at chart size it reads as that state' }, r);
    }
  }

  /* ------------- 8. scales and value labels that move while scrolling */
  const store = window.__qaSnap || (window.__qaSnap = new WeakMap());
  for (const svg of svgs) {
    const fa = fixedAnc(svg); if (!fa || !atStickyPos(fa)) continue;
    const sr = svg.getBoundingClientRect(), vb = svg.getAttribute('viewBox') || '';
    const lines = [...svg.querySelectorAll('line')].filter(l => !l.closest('defs, pattern') && effOp(l) > 0.1)
      .map(l => l.getBoundingClientRect()).filter(r => r.height < 1.5 && r.width > sr.width * 0.4).map(r => +(r.top - sr.top).toFixed(1));
    const bars = marksOf(svg).filter(m => !m.circle && !m.big && m.e.localName === 'rect');
    // where each bar ENDS (its attributes; the growth is a transform on the rect)
    const finalTop = m => {
      const pm = m.e.parentNode && m.e.parentNode.getScreenCTM && m.e.parentNode.getScreenCTM();
      const x = +m.e.getAttribute('x') || 0, y = +m.e.getAttribute('y') || 0;
      if (!pm || !m.e.hasAttribute('y')) return m.r.top;
      return new DOMPoint(x, y).matrixTransform(pm).y;
    };
    const pairs = [];
    [...svg.querySelectorAll('text')].forEach((t, i) => {
      const r = t.getBoundingClientRect(); if (r.width < 1 || effOp(t) < 0.5) return;
      const cx = (r.left + r.right) / 2;
      let best = null;
      for (const m of bars) {
        const mcx = (m.r.left + m.r.right) / 2;
        if (Math.abs(mcx - cx) > 3 || m.r.top < r.bottom - 2) continue;
        const gap = m.r.top - r.bottom;
        if (gap < sr.height * 0.9 && (!best || gap < best.gap)) best = { gap, h: m.r.height, gapFinal: finalTop(m) - r.bottom };
      }
      // only a VALUE label (one that ends just above its bar) can drift;
      // a static label far above the bars is not bound to them
      if (best && best.gapFinal > -4 && best.gapFinal < 24) pairs.push({ k: i + ':' + clean(t.textContent), gap: best.gap, h: best.h, el: t });
    });
    const prev = store.get(svg);
    if (prev && prev.vb === vb && Math.abs(prev.w - sr.width) < 1 && Math.abs(prev.h - sr.height) < 1) {
      if (prev.lines.length === lines.length && lines.length) {
        const mv = lines.reduce((a, y, i) => Math.max(a, Math.abs(y - prev.lines[i])), 0);
        if (mv > 1) add('scaleDrift', svg, null, { movedPx: +mv.toFixed(1), note: 'gridlines moved relative to their chart between two scroll positions (parallax on a scale)' }, sr);
      }
      for (const p of pairs) {
        const q = prev.pairs.find(z => z.k === p.k);
        if (q && Math.abs(q.h - p.h) > 2 && Math.abs(q.gap - p.gap) > 2)
          add('labelDrift', p.el, p.k.replace(/^\d+:/, ''), { gapBefore: Math.round(q.gap), gapNow: Math.round(p.gap), note: 'value label is not driven by the same motion value as its bar' }, p.el.getBoundingClientRect());
      }
    }
    store.set(svg, { vb, w: sr.width, h: sr.height, lines, pairs: pairs.map(({ el, ...z }) => z) });
  }

  /* ------------------ 9. reduced motion must show every finished state */
  if (meta.reducedMotion) {
    for (const svg of svgs) {
      let n = 0, ex = null;
      for (const e of svg.querySelectorAll('rect, circle, path, text, polygon, line')) {
        if (e.closest('defs, pattern')) continue;
        const r = e.getBoundingClientRect();
        const zero = (e.localName === 'rect' && (+e.getAttribute('width') > 1 && +e.getAttribute('height') > 1) && (r.width < 0.5 || r.height < 0.5)) ||
                     (e.localName === 'circle' && +e.getAttribute('r') > 1 && r.width < 0.5);
        if (effOp(e) < 0.05 || zero) { n++; ex = ex || e; }
      }
      if (n) add('rmHidden', ex, null, { hiddenMarks: n, note: 'with prefers-reduced-motion some marks are invisible or scaled to 0; reduced motion must render the END state' }, svg.getBoundingClientRect());
    }
  }

  /* --------------------------------------- 10. pinned stages that overflow */
  if (!PRINT) for (const s of INV.sticky) {
    const r = s.getBoundingClientRect();
    if (r.height < vh * 0.9 || !root.contains(s) || !atStickyPos(s)) continue;
    const cs = CS(s);
    const avail = s.clientHeight - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0);
    let t = Infinity, b = -Infinity;
    for (const c of s.children) { const cr = c.getBoundingClientRect(); if (cr.height < 1) continue; t = Math.min(t, cr.top); b = Math.max(b, cr.bottom); }
    if (!isFinite(t)) continue;
    const content = b - t, topLimit = r.top + (parseFloat(cs.paddingTop) || 0);
    if (content > avail + 1 || t < topLimit - 1 || b > r.bottom + 1)
      add('pinOverflow', s, null, { content: Math.round(content), room: Math.round(avail), overflowPx: Math.round(Math.max(content - avail, topLimit - t, b - r.bottom)),
        headlineTop: (() => { const h = s.querySelector('h1, h2, h3'); return h ? Math.round(h.getBoundingClientRect().top) : null; })() }, r);
  }

  // a sticky bar that eats the screen (a wrapping filter bar on a phone)
  if (!PRINT) for (const s of INV.sticky) {
    if (!root.contains(s) || !atStickyPos(s)) continue;
    const r = s.getBoundingClientRect(), share = r.height / vh;
    if (r.height >= vh * 0.9 || share <= 0.3 || r.width < vw * 0.5) continue;
    add('stickyTooTall', s, null, { heightPx: Math.round(r.height), share: +share.toFixed(2),
      note: 'a stuck bar this tall leaves too little room to read; collapse it behind a button or unstick it on small screens' }, r, share > 0.45 ? 'P1' : 'P2');
  }

  /* ------------------------------------------------ 11. horizontal scroll */
  const sw = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  if (sw > vw + 1) {
    const offenders = [];
    for (const e of root.querySelectorAll('*')) {
      const r = e.getBoundingClientRect(); if (r.right <= vw + 1 || r.width < 1) continue;
      let scroller = false;
      for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) { const ox = CS(a).overflowX; if (ox !== 'visible') { scroller = true; break; } }
      if (!scroller) offenders.push({ e, over: r.right - vw });
    }
    offenders.sort((a, b) => b.over - a.over);
    add('hScroll', offenders[0] ? offenders[0].e : root, null, { scrollWidth: sw, viewport: vw,
      widest: offenders.slice(0, 4).map(o => sel(o.e) + ' +' + Math.round(o.over) + 'px') });
  }

  /* --------------------------------------- 12. headings under the app bar */
  if (O.headings && INV.barBottom) {
    for (const h of root.querySelectorAll('h1, h2, h3')) {
      const r = h.getBoundingClientRect();
      if (r.height < 1 || r.bottom <= 0 || r.top >= vh) continue;
      if (r.top < INV.barBottom - 1) add('headingUnderBar', h, h.textContent, { hiddenPx: Math.round(INV.barBottom - r.top) }, r);
    }
  }

  /* ------------------------------------------------------- 13. tables */
  for (const t of root.querySelectorAll('table')) {
    const r = t.getBoundingClientRect(); if (r.bottom < 0 || r.top > vh || r.height < 1 || !t.getClientRects().length) continue;
    // duplicate row labels
    const seen = new Map();
    for (const tr of t.querySelectorAll('tbody tr')) {
      const c = tr.querySelector('td, th'); if (!c) continue;
      const k = clean(c.innerText || c.textContent); if (!k) continue;
      seen.set(k, (seen.get(k) || 0) + 1);
    }
    for (const [k, n] of seen) if (n > 1) add('dupLabel', t, k, { rows: n, note: 'identical first-column text on several rows: disambiguate (unit number, address or ID)' });
    // wider than its frame: columns sit off-frame
    let frame = null;
    for (let a = t.parentElement; a && a !== root.parentElement; a = a.parentElement) { if (/^(auto|scroll|hidden|clip)$/.test(CS(a).overflowX)) { frame = a; break; } }
    if (frame && !PRINT) {
      const fr = frame.getBoundingClientRect(), fw = frame.clientWidth;
      if (t.scrollWidth > fw + 2 || r.width > fw + 2) {
        const heads = [...t.querySelectorAll('thead th, thead td')].filter(th => th.getBoundingClientRect().right > fr.right - (frame.scrollLeft ? 0 : 1) + 0.5);
        const firstCell = t.querySelector('tbody tr td, tbody tr th');
        const stickyFirst = !!(firstCell && CS(firstCell).position === 'sticky');
        const desk = vw > 820;
        // the prescribed phone form (scrolls in its box, row labels stay) is not reported
        if (desk || !stickyFirst) add('tableOverflow', t, heads.map(h => clean(h.textContent)).slice(0, 5).join(', ') || null,
          { tableW: Math.round(Math.max(t.scrollWidth, r.width)), frameW: Math.round(fw), offFrameColumns: heads.length, stickyFirstColumn: stickyFirst, scroll: CS(frame).overflowX,
            note: desk ? 'the table is wider than its frame on a desktop screen: columns sit off-frame with no cue; drop or merge columns so it fits' :
              (stickyFirst ? 'scrolls inside its frame on the phone; the row labels stay (fine if a cue says it scrolls)' : 'scrolls inside its frame on the phone and the row labels scroll away: make the first column sticky') },
          fr, desk ? 'P2' : (stickyFirst ? 'P3' : 'P3'));
      }
    }
    // a word or a figure broken across two lines inside a cell ("123,45" / "6",
    // "REGIO" / "N"): overflow-wrap:anywhere on a column too narrow for it
    {
      // A hard break (inside a figure, or a word split with no hyphen drawn) misreads:
      // P2 in print. A word the browser hyphenated (hyphens:auto, letters on both
      // sides; the hyphen is drawn) still reads, so on its own it is P3.
      const wc = c => /[\p{L}\p{N}]/u.test(c), lc = c => /\p{L}/u.test(c);
      let n = 0, hy = 0; const ex = [], exH = [];
      for (const cell of t.querySelectorAll('th, td')) {
        const cr = cell.getBoundingClientRect();
        if (cr.bottom < 0 || cr.top > vh || cr.height < 1 || !cell.getClientRects().length) continue;
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          const tn = walker.currentNode, s = tn.nodeValue; if (!s || s.trim().length < 3) continue;
          rng.selectNodeContents(tn);
          const lines = new Set([...rng.getClientRects()].filter(q => q.width > 0.5).map(q => Math.round(q.top)));
          if (lines.size < 2) continue;
          const pcs = tn.parentElement && CS(tn.parentElement);
          const hyAuto = !!pcs && pcs.hyphens === 'auto' && pcs.wordBreak !== 'break-all';   // break-all draws no hyphen
          let prevTop = null, prevCh = null;
          for (let i = 0; i < s.length; i++) {
            const ch = s[i]; if (/\s/.test(ch)) { prevCh = ch; continue; }
            rng.setStart(tn, i); rng.setEnd(tn, i + 1);
            const q = rng.getBoundingClientRect(); if (q.width < 0.1) continue;
            if (prevTop != null && q.top > prevTop + 2 && prevCh && wc(prevCh) && wc(ch)) {
              const e2 = clean(s.slice(Math.max(0, i - 8), i)), e3 = clean(s.slice(i, i + 6));
              if (hyAuto && lc(prevCh) && lc(ch)) { hy++; if (exH.length < 3) exH.push(e2 + '-|' + e3); }
              else { n++; if (ex.length < 5) ex.push(e2 + '|' + e3); }
            }
            prevTop = q.top; prevCh = ch;
          }
        }
      }
      if (n || hy) add('midWordBreak', t, [...ex, ...exH].slice(0, 5).join(' · '), { breaks: n || undefined, hyphenated: hy || undefined, print: PRINT || undefined,
        note: n ? 'words or figures split across lines inside table cells; widen or drop columns, keep figures nowrap, and never use overflow-wrap:anywhere on numbers'
          : 'words hyphenated inside a narrow column (hyphens:auto): readable, but widen the column or drop one for print so whole words fit' }, r, n && PRINT ? 'P2' : 'P3');
    }
    // a sticky header that does not stick
    const th = t.querySelector('thead th, thead td');
    if (th && !PRINT && CS(th).position === 'sticky') {
      const topV = parseFloat(CS(th).top), hr = th.getBoundingClientRect();
      if (!isNaN(topV) && r.top < topV - 4 && r.bottom > topV + hr.height + 30 && hr.top < topV - 2) {
        let sc = null;
        for (let a = th.parentElement; a && a !== document.documentElement; a = a.parentElement) { const c = CS(a); if (/^(auto|scroll|hidden)$/.test(c.overflowX) || /^(auto|scroll|hidden)$/.test(c.overflowY)) { sc = a; break; } }
        add('stickyBroken', th, clean(th.textContent), { expectedTop: Math.round(topV), actualTop: Math.round(hr.top), scrollContainer: sc ? sel(sc) + ' (overflow ' + CS(sc).overflowX + '/' + CS(sc).overflowY + ')' : undefined,
          note: vw > 820 ? 'the table header is declared sticky but scrolls away: an overflow ancestor has become its scroll container'
                         : 'on the phone the table scrolls inside its box, so the header cannot stick (accepted if the table is short or the header repeats)' }, hr, vw > 820 ? 'P2' : 'P3');
      }
    }
  }

  /* ------------------------------------ 14. interaction and focus hygiene */
  const INTER = 'a[href], button, [role=button], [role=tab], select, input, summary, [tabindex="0"]';
  const tgSeen = new Set();
  if (!PRINT) for (const e of [...root.querySelectorAll(INTER), ...INV.bars.flatMap(b => [...b.querySelectorAll(INTER)])]) {
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
    if (isSrOnly(e) || effOp(e) < 0.1 || CS(e).visibility === 'hidden') continue;
    if (e.localName === 'a' && CS(e).display === 'inline') continue;   // links inside prose are exempt
    if (r.width < 23.5 || r.height < 23.5) {
      const sig = e.localName + '.' + String(e.getAttribute('class') || '').split(' ')[0];
      if (tgSeen.has(sig)) { counts.smallTarget++; bySev.P3++; continue; }
      tgSeen.add(sig);
      add('smallTarget', e, clean(e.textContent) || e.getAttribute('aria-label') || e.getAttribute('title'), { w: Math.round(r.width), h: Math.round(r.height), need: '24x24 (WCAG 2.2 2.5.8)' }, r);
    }
  }
  const ckSeen = new Map();
  if (!PRINT) for (const e of root.querySelectorAll('*')) {
    if (CS(e).cursor !== 'pointer') continue;
    if (e.closest(INTER + ', label, .leaflet-container, [tabindex]')) continue;
    if (e.querySelector(INTER)) continue;     // a row whose own button carries the action is reachable
    if (e.parentElement && CS(e.parentElement).cursor === 'pointer') continue;
    const r = e.getBoundingClientRect(); if (r.width < 1 || r.bottom < 0 || r.top > vh) continue;
    const sig = e.localName + '.' + String(e.getAttribute('class') || '').split(' ').join('.');
    if (!ckSeen.has(sig)) ckSeen.set(sig, { e, n: 0, r });
    ckSeen.get(sig).n++;
  }
  for (const [sig, o] of ckSeen) add('clickNoKeyboard', o.e, null, { selector: sig, count: o.n, note: 'clickable (cursor:pointer) but not focusable; give it a button/role and tabindex, or make sure the same action exists on a keyboard path' }, o.r);
  const ae = document.activeElement;
  if (!PRINT && ae && ae !== document.body && ae.getAttribute && ae.getAttribute('tabindex') === '-1') {
    const cs = CS(ae);
    const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');
    if (ring) add('progFocusRing', ae, ae.textContent, { note: 'a programmatic focus target (tabindex=-1) shows a focus ring' }, ae.getBoundingClientRect());
  }

  /* ------------------ 14b. the opening states the argument: largest type
     The storyline's opening headline must be decisively larger than every
     headline after it (a statement, the closing, any scene headline). */
  if (!PRINT && !isDash() && scenesOf(root).length) {
    const opening = root.querySelector('.opening') || root.querySelector('h1');
    if (opening && opening.getClientRects().length) {
      const os = parseFloat(CS(opening).fontSize) || 0;
      let big = null;
      for (const h of root.querySelectorAll('h1, h2, [class*=statement], [class*=closing]')) {
        if (h === opening || h.contains(opening) || opening.contains(h) || !h.getClientRects().length) continue;
        if (h.closest('.appendix, footer, [role=dialog], table')) continue;
        const fs = parseFloat(CS(h).fontSize) || 0;
        if (fs >= os * 0.9 && (!big || fs > big.fs)) big = { h, fs };
      }
      if (big) add('openingNotLargest', big.h, big.h.textContent, { openingPx: +os.toFixed(1), otherPx: +big.fs.toFixed(1),
        note: big.fs >= os ? 'a later headline is as large as or larger than the opening: the opening must be the largest type in the storyline'
                           : 'the opening is not decisively larger (under 1.1×) than a later headline' }, big.h.getBoundingClientRect(), big.fs >= os ? 'P2' : 'P3');
    }
  }

  /* -------------------------------------------- 15. label inventory
     Every rendered chart label per scene (whole scene, not only the viewport),
     so the driver can spot a label that one viewport silently drops. */
  if (O.inventory) {
    const inv = {};
    const groups = (!isDash() && scenesOf(root).length) ? scenesOf(root) : sectionsOf(root).map(s => Object.assign(s, { id: s.id || slug(s.heading || s.cls) }));
    for (const g of groups) {
      const out = new Set();
      for (const t of g.el.querySelectorAll('svg text')) {
        if (t.closest('.leaflet-container, defs')) continue;
        if (t.parentElement && t.parentElement.closest('text')) continue;
        if (t.checkVisibility && !t.checkVisibility({ visibilityProperty: true })) continue;
        const r = t.getBoundingClientRect(); if (r.width < 1 || effOp(t) < 0.3) continue;
        const s = clean(t.textContent); if (s) out.add(s.slice(0, 80));
      }
      if (out.size) inv[g.id || ('g' + g.index)] = [...out];
    }
    meta.inventory = inv;
  }

  meta.anchor = anchorOf();
  meta.scene = (() => {
    const s = (isDash() ? sectionsOf(root) : scenesOf(root)).find(s => { const r = s.el.getBoundingClientRect(); return r.top <= vh / 2 && r.bottom >= vh / 2; });
    return s ? s.id : null;
  })();
  return result();
}
