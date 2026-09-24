#!/usr/bin/env node
/* qa_run.cjs - Node Playwright driver for scripts/qa_audit.js (the mechanical sweep).

   Opens the assembled portfolio file and, at each viewport:
     storyline  every scene (pinned scenes at each progress point, tall scenes at
                0/0.5/1, the rest centred) plus a "rail jump" to each scene start;
                then the same walk again with REDUCED MOTION;
     dashboard  the default walk, the map zoomed +2/+4, a filtered state, a
                sparse state and the drawer (top and scrolled to the end).
   Then one PRINT pass (print media, fresh load: document-wide print checks, a
   walk, a real PDF with a blank-page check, page images if a renderer exists),
   a cross-viewport comparison of chart labels (a label one viewport drops),
   and the page-text dump for Numbers QA.

   usage
     node qa_run.cjs <file.html | http://...> [options]
       --out <dir>            screenshots + qa-report.json (default <run>/qa/shots
                              when the file sits in a run folder, else ./qa-shots)
       --viewports a,b        default 1536x730,1440x900,1366x768,390x844
       --progress a,b         pinned progress points (default 0.1,0.5,0.9)
       --quick                1536x730 + 390x844, progress 0.5; SKIPS the filtered
                              and sparse dashboard states and the rail jumps
       --story | --dash       one view only
       --scenes a,b           only these storyline scene ids (checking a fix)
       --filter k=v           dashboard filter(s) to audit, e.g. landlord=<Landlord>,
                              region=North West, group=<Company>, cold=true
                              (repeat the flag; default: the largest landlord)
       --drawer n|id          drawer(s) to open: a unit id or a 1-based table row
                              (repeat or comma-list; default: first row + sparsest)
       --no-rm | --no-print | --no-text    skip reduced motion / print / page text
       --print-only           only the print pass (A4 print media, both PDFs): a
                              check of a print fix in about a minute
       --text-out <file>      page text (default <run>/qa/page-text.txt)
       --no-shots             audit only
       --playwright <path>    a Playwright install to use (or env PLAYWRIGHT_PATH)
   exit 0 = no P1 defects, 1 = P1 defects or console errors, 2 = could not run

   qa-report.json is rewritten as the run goes ("partial": true until the end),
   so a killed run still leaves its results. Screenshot names depend only on
   viewport, state and scene id / panel heading, so they stay stable between
   rounds. It fails soft: if Playwright or a browser is missing it says so,
   names the alternatives and exits 2 without a stack trace. */
'use strict';
const fs = require('fs'), path = require('path'), url = require('url'), zlib = require('zlib'), cp = require('child_process');

/* ------------------------------------------------------------- arguments */
const argv = process.argv.slice(2);
const opt = { viewports: '1536x730,1440x900,1366x768,390x844', progress: '0.1,0.5,0.9', shots: true, filters: [], drawers: [] };
let target = null;
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--out') opt.out = argv[++i];
  else if (a === '--viewports') opt.viewports = argv[++i];
  else if (a === '--progress') opt.progress = argv[++i];
  else if (a === '--quick') opt.quick = true;
  else if (a === '--story') opt.only = 'story';
  else if (a === '--dash') opt.only = 'dash';
  else if (a === '--filter') opt.filters.push(argv[++i]);
  else if (a === '--drawer') opt.drawers.push(...String(argv[++i]).split(',').map(s => s.trim()).filter(Boolean));
  else if (a === '--scenes') opt.scenes = String(argv[++i]).split(',').map(s => s.trim()).filter(Boolean);
  else if (a === '--no-rm') opt.noRm = true;
  else if (a === '--no-print') opt.noPrint = true;
  else if (a === '--print-only') opt.printOnly = true;
  else if (a === '--no-text') opt.noText = true;
  else if (a === '--text-out') opt.textOut = argv[++i];
  else if (a === '--no-shots') opt.shots = false;
  else if (a === '--playwright') opt.pw = argv[++i];
  else if (a === '-h' || a === '--help') { console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]); process.exit(0); }
  else if (!target) target = a;
}
if (!target) { console.log('usage: node qa_run.cjs <file.html> [--quick] [--viewports 1536x730,390x844] [--filter landlord=X] [--drawer 3] [--out dir]'); process.exit(2); }
if (opt.quick) { opt.viewports = '1536x730,390x844'; opt.progress = '0.5'; }
if (opt.printOnly) { opt.viewports = ''; opt.noRm = true; opt.noText = true; opt.noPrint = false; }
const VIEWPORTS = opt.viewports.split(',').map(s => s.trim().split('x').map(Number)).filter(v => v[0] && v[1]);
const PROGRESS = opt.progress.split(',').map(Number).filter(n => n >= 0 && n <= 1);
const FILTERS = opt.filters.flatMap(f => String(f).split(/,(?=[a-z_]+=)/i)).map(f => { const i = f.indexOf('='); return i > 0 ? { k: f.slice(0, i).trim(), v: f.slice(i + 1).trim() } : null; }).filter(Boolean);

let pageUrl, htmlDir;
if (/^https?:\/\//.test(target) || /^file:\/\//.test(target)) { pageUrl = target; htmlDir = process.cwd(); }
else {
  const abs = path.resolve(target);
  if (!fs.existsSync(abs)) { console.log('QA driver: file not found: ' + abs); process.exit(2); }
  pageUrl = url.pathToFileURL(abs).href; htmlDir = path.dirname(abs);
}
const inRun = fs.existsSync(path.join(htmlDir, 'qa'));
const OUT = path.resolve(opt.out || (inRun ? path.join(htmlDir, 'qa', 'shots') : 'qa-shots'));
const PRINTDIR = path.join(OUT, 'print');
const TEXT_OUT = path.resolve(opt.textOut || (inRun ? path.join(htmlDir, 'qa', 'page-text.txt') : path.join(OUT, 'page-text.txt')));
const AUDIT = fs.readFileSync(path.join(__dirname, 'qa_audit.js'), 'utf8');
const PAGETEXT = fs.existsSync(path.join(__dirname, 'page_text.js')) ? fs.readFileSync(path.join(__dirname, 'page_text.js'), 'utf8') : null;
const slug = s => String(s || '').toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').split('-').filter(Boolean).slice(0, 5).join('-').slice(0, 36) || 'x';
const pad = n => String(n).padStart(2, '0');

/* ------------------------------------------------ find Playwright, softly */
function loadPlaywright() {
  const tries = [];
  if (opt.pw) tries.push(path.resolve(opt.pw));
  if (process.env.PLAYWRIGHT_PATH) tries.push(path.resolve(process.env.PLAYWRIGHT_PATH));
  tries.push('playwright', 'playwright-core', '@playwright/test');
  for (let d = htmlDir, i = 0; i < 6; i++, d = path.dirname(d)) {
    for (const n of ['playwright', 'playwright-core']) tries.push(path.join(d, 'node_modules', n));
  }
  try {
    const g = cp.execSync('npm root -g', { stdio: ['ignore', 'pipe', 'ignore'], timeout: 8000 }).toString().trim();
    if (g) {
      for (const n of ['playwright', 'playwright-core', '@playwright/test']) tries.push(path.join(g, n));
      for (const n of ['playwright', 'playwright-core']) tries.push(path.join(g, '@playwright', 'mcp', 'node_modules', n));
    }
  } catch (e) { /* no npm */ }
  try {
    const npx = path.join(require('os').homedir(), '.npm', '_npx');
    for (const d of fs.readdirSync(npx)) for (const n of ['playwright', 'playwright-core']) tries.push(path.join(npx, d, 'node_modules', n));
  } catch (e) { /* no cache */ }
  for (const t of tries) {
    try { const m = require(t); if (m && m.chromium) return { pw: m, from: t, tries }; } catch (e) { /* next */ }
  }
  return { pw: null, tries };
}
function softFail(msg, extra) {
  console.log('\nQA driver could not run: ' + msg);
  if (extra) console.log(extra);
  console.log([
    '',
    'This does not block the QA. Use, in order:',
    '  1. The Playwright MCP tools: serve the run folder over http, browser_navigate,',
    '     browser_resize, then browser_evaluate with scripts/qa_audit.js',
    '     (reference/qa-visual.md, "Route A").',
    '  2. An existing Playwright install:  --playwright /path/to/node_modules/playwright',
    '  3. Static checks only (qa-visual.md, "Route C"), stating the limitation in the report.',
    'Do not npm-install anything.',
  ].join('\n'));
  process.exit(2);
}

/* ------------------------------------------- PDF: pages and blank pages
   A renderer-free look inside Chromium's PDF: each page's content stream is
   inflated and checked for text (Tj/TJ), images (Do) and paint operators. */
function pdfInfo(file) {
  const s = fs.readFileSync(file).toString('latin1');
  const at = new Map(); const re = /(\d+)\s+(\d+)\s+obj\b/g; let m;
  while ((m = re.exec(s))) { const end = s.indexOf('endobj', re.lastIndex); at.set(+m[1], [re.lastIndex, end < 0 ? s.length : end]); }
  const body = n => { const r = at.get(n); return r ? s.slice(r[0], r[1]) : ''; };
  const dict = b => { const i = b.indexOf('stream'); return i >= 0 ? b.slice(0, i) : b; };
  let rootPages = null;
  for (const [n] of at) { const d = dict(body(n)); if (/\/Type\s*\/Pages\b/.test(d) && !/\/Parent\s/.test(d)) { rootPages = n; break; } }
  const order = [];
  const walk = (n, depth) => {
    if (depth > 20) return;
    const d = dict(body(n));
    if (/\/Type\s*\/Pages\b/.test(d)) { const k = d.match(/\/Kids\s*\[([^\]]*)\]/); if (k) for (const mm of k[1].matchAll(/(\d+)\s+\d+\s+R/g)) walk(+mm[1], depth + 1); }
    else if (/\/Type\s*\/Page\b/.test(d)) order.push(n);
  };
  if (rootPages != null) walk(rootPages, 0);
  const stream = n => {
    const b = body(n); const i = b.indexOf('stream'); if (i < 0) return '';
    let st = i + 6; if (b[st] === '\r') st++; if (b[st] === '\n') st++;
    let raw = Buffer.from(b.slice(st, b.lastIndexOf('endstream')), 'latin1');
    if (/FlateDecode/.test(b.slice(0, i))) { try { raw = zlib.inflateSync(raw); } catch (e) { try { raw = zlib.inflateSync(raw.subarray(0, raw.length - 1)); } catch (e2) { return '?'; } } }
    return raw.toString('latin1');
  };
  const pages = order.map((n, i) => {
    const d = dict(body(n));
    const c2 = d.match(/\/Contents\s*\[([^\]]*)\]/), c1 = d.match(/\/Contents\s+(\d+)\s+\d+\s+R/);
    const refs = c2 ? [...c2[1].matchAll(/(\d+)\s+\d+\s+R/g)].map(x => +x[1]) : c1 ? [+c1[1]] : [];
    const txt = refs.map(stream).join('\n');
    return { page: i + 1, text: /\bT[Jj]\b/.test(txt), img: /\/\S+\s+Do\b/.test(txt), paints: (txt.match(/(^|\s)(f\*?|F|B\*?|b\*?|S|s)(?=\s|$)/g) || []).length, unreadable: txt === '?' };
  });
  return { pages: pages.length, blank: pages.filter(p => !p.unreadable && !p.text && !p.img && p.paints <= 2).map(p => p.page),
           noText: pages.filter(p => !p.unreadable && !p.text && (p.img || p.paints > 2)).map(p => p.page), parsed: order.length > 0 };
}
function renderPdf(pdf, prefix) {
  const has = cmd => { const r = cp.spawnSync(cmd, ['-v'], { stdio: 'ignore' }); return !r.error; };
  try { if (has('pdftoppm')) { cp.execFileSync('pdftoppm', ['-r', '45', '-png', pdf, prefix], { stdio: 'ignore', timeout: 180000 }); return 'pdftoppm'; } } catch (e) { /* next */ }
  for (const py of ['python3', 'python']) {
    try {
      const r = cp.spawnSync(py, ['-c', 'import fitz'], { stdio: 'ignore' });
      if (r.error || r.status !== 0) continue;
      cp.execFileSync(py, ['-c', 'import fitz,sys\nd=fitz.open(sys.argv[1])\nfor i,p in enumerate(d): p.get_pixmap(dpi=45).save(sys.argv[2]+"-%02d.png"%(i+1))', pdf, prefix], { stdio: 'ignore', timeout: 180000 });
      return 'pymupdf';
    } catch (e) { /* next */ }
  }
  return null;
}

/* ------------------------------------------------------------ the run */
(async () => {
  const { pw, from, tries } = loadPlaywright();
  if (!pw) softFail('Playwright is not installed here.', '  looked in: ' + tries.slice(0, 8).join(' | ') + ' ...');
  let browser = null, lastErr = null;
  for (const o of [{}, { channel: 'chrome' }, { channel: 'msedge' }]) {
    try { browser = await pw.chromium.launch(o); break; } catch (e) { lastErr = e; }
  }
  if (!browser) softFail('Playwright was found (' + from + ') but no Chromium browser could be launched.',
    '  ' + String(lastErr && lastErr.message || lastErr).split('\n')[0]);
  fs.mkdirSync(OUT, { recursive: true });
  console.log('QA driver  ' + pageUrl + '\n  playwright: ' + from + '\n  out: ' + OUT + '\n');

  const runs = [], consoleLog = [], inventories = [], printInfo = {};
  const t0 = Date.now();
  let lastFlush = 0;
  const shotNames = new Map();

  const audit = async (page, o) => {
    try { return await page.evaluate(`(${AUDIT})(${JSON.stringify(o || {})})`); }
    catch (e) { return { error: String(e.message || e).split('\n')[0], issues: [] }; }
  };
  const shot = async (page, name) => {
    if (!opt.shots) return null;
    let base = name.replace(/[^\w.+-]+/g, '_');
    const n = (shotNames.get(base) || 0) + 1; shotNames.set(base, n);
    if (n > 1) base += '-' + n;
    const f = base + '.jpg';
    try { await page.screenshot({ path: path.join(OUT, f), type: 'jpeg', quality: 72 }); return f; } catch (e) { return null; }
  };
  const record = (vp, state, where, res, file) => {
    const m = res.meta ? Object.assign({}, res.meta) : null;
    if (m && m.inventory) { inventories.push({ vp, state, where, inv: m.inventory }); delete m.inventory; }
    runs.push({ viewport: vp, state, where, shot: file, meta: m, error: res.error || null,
                counts: res.counts || {}, issues: res.issues || [] });
    const n = (res.issues || []).length, p1 = (res.issues || []).filter(i => i.sev === 'P1').length;
    process.stdout.write(`  ${vp} ${state.padEnd(8)} ${String(where).padEnd(22)} ${res.error ? 'ERROR ' + res.error : (n ? n + ' issues' + (p1 ? ' (' + p1 + ' P1)' : '') : 'clean')}\n`);
    if (Date.now() - lastFlush > 4000) flush(true);
  };
  const newPage = async (w, h, extra) => {
    const ctx = await browser.newContext(Object.assign({ viewport: { width: w, height: h }, deviceScaleFactor: 1,
      isMobile: w < 500, hasTouch: w < 500, acceptDownloads: true }, extra || {}));
    const page = await ctx.newPage();
    const vp = w + 'x' + h;
    page.on('console', m => { if (m.type() === 'error') consoleLog.push({ vp, type: 'console', text: m.text().slice(0, 300) }); });
    page.on('pageerror', e => consoleLog.push({ vp, type: 'pageerror', text: String(e.message || e).slice(0, 300) }));
    await page.goto(pageUrl, { waitUntil: 'load', timeout: 60000 });
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(1200);
    return { ctx, page };
  };

  /* ---------------------------------------------------------- storyline */
  const storyWalk = async (page, vp, tag) => {
    const L = await audit(page, { action: 'list', view: 'story' });
    if (L.error || !L.scenes) { record(vp, tag, 'list', L.error ? L : { error: 'no storyline scenes found' }, null); return; }
    if (L.meta.view !== 'story') return;
    const [W, H] = vp.split('x').map(Number);
    const rm = tag === 'rm';
    for (const s of L.scenes) {
      if (!s.id || (opt.scenes && !opt.scenes.includes(s.id))) continue;
      if (s.pinned) {
        for (const p of PROGRESS) {
          const r = await audit(page, { scene: s.id, progress: p, wait: rm ? 500 : 1300, inventory: rm && p === PROGRESS[PROGRESS.length - 1] });
          record(vp, tag, s.id + ' p' + Math.round(p * 100), r, await shot(page, `${vp}-${tag}-${s.id}-p${Math.round(p * 100)}`));
        }
      } else if (s.height > H * 1.15 && !opt.quick) {
        for (const p of [0, 0.5, 1]) {
          const r = await audit(page, { scene: s.id, progress: p, wait: rm ? 500 : 1600, inventory: rm && p === 1 });
          record(vp, tag, s.id + ' @' + Math.round(p * 100), r, await shot(page, `${vp}-${tag}-${s.id}-at${Math.round(p * 100)}`));
        }
      } else {
        const r = await audit(page, { scene: s.id, progress: 'center', wait: rm ? 500 : 1600, inventory: rm });
        record(vp, tag, s.id, r, await shot(page, `${vp}-${tag}-${s.id}`));
      }
      if (!rm && !opt.quick && W > 820) {   // the rail (desktop only) jumps to a scene's start: its headline must clear the app bar
        const r = await audit(page, { scene: s.id, progress: 'start', headings: true, wait: 750 });   // > the 620ms ground fade
        r.issues = (r.issues || []).filter(i => /^(headingUnderBar|underBar|pinOverflow|clipped)$/.test(i.type));
        record(vp, tag, s.id + ' start', r, null);
      }
    }
  };

  /* ---------------------------------------------------------- dashboard */
  const dashSteps = async (page, vp, tag) => {
    const L = await audit(page, { action: 'list', view: 'dash' });
    if (L.error || !L.meta || L.meta.view !== 'dash') { record(vp, tag, 'list', L.error ? L : { error: 'no dashboard view' }, null); return false; }
    const vh = +vp.split('x')[1], H = L.meta.docHeight;
    const step = Math.round(vh * 0.8);
    for (let y = 0, i = 0; y < H - 10 && i < 99; y += step, i++) {
      const r = await audit(page, { y, wait: 350 });
      record(vp, tag, (r.meta && r.meta.anchor) || 'y' + y, r, await shot(page, `${vp}-${tag}-${(r.meta && r.meta.anchor) || 'y' + y}`));
    }
    return true;
  };
  const dashReset = async page => {
    await page.evaluate(() => {
      const D = window.DASH && window.DASH.api;
      if (D && D.reset) D.reset(); else if (window.__reset) window.__reset();
      else { const b = document.querySelector('#view-dash .btn-reset:not([hidden])'); if (b) b.click(); }
    }).catch(() => {});
    await page.waitForTimeout(400);
  };
  const applyFilter = (page, f) => page.evaluate(({ k, v }) => {
    const D = window.DASH && window.DASH.api;
    const val = v === 'true' ? true : v === 'false' ? false : v;
    if (D && D.setFilter) { try { D.setFilter(k, val); return 'api'; } catch (e) { /* DOM next */ } }
    for (const s of document.querySelectorAll('#view-dash select')) {
      const lab = ((s.id && document.querySelector('label[for="' + s.id + '"]')) || {}).textContent || s.id || s.name || '';
      if (!new RegExp(k, 'i').test(lab)) continue;
      const o = [...s.options].find(o => o.value === v || o.textContent.trim() === v) || [...s.options].find(o => o.textContent.toLowerCase().includes(String(v).toLowerCase()));
      if (o) { s.value = o.value; s.dispatchEvent(new Event('change', { bubbles: true })); return 'select'; }
    }
    const b = [...document.querySelectorAll('#view-dash [aria-pressed]')].find(b => b.textContent.toLowerCase().includes(String(v).toLowerCase()));
    if (b) { b.click(); return 'chip'; }
    return null;
  }, f);
  const largestLandlord = async page => {
    const viaApi = await page.evaluate(() => {
      const D = window.DASH && window.DASH.api;
      if (!D || !D.all) return null;
      const by = {};
      for (const r of D.all) { if (r.owned || !r.landlord) continue; by[r.landlord] = (by[r.landlord] || 0) + (+r.size || 0); }
      const top = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
      return top ? { k: 'landlord', v: top[0] } : null;
    }).catch(() => null);
    if (viaApi) return viaApi;
    // no API: try each landlord option and keep the one that shows the most units
    const n = await page.evaluate(() => { const s = [...document.querySelectorAll('#view-dash select')].find(s => /landlord/i.test(s.id + ' ' + (((s.id && document.querySelector('label[for="' + s.id + '"]')) || {}).textContent || ''))); if (!s) return 0; s.dataset.qaLandlord = '1'; return s.options.length; }).catch(() => 0);
    let best = null;
    for (let i = 1; i < Math.min(n, 41); i++) {
      const got = await page.evaluate(i => { const s = document.querySelector('#view-dash select[data-qa-landlord]'); s.selectedIndex = i; s.dispatchEvent(new Event('change', { bubbles: true }));
        return { v: s.options[i].textContent.trim(), n: document.querySelectorAll('#view-dash tbody tr:not(.empty-row)').length }; }, i).catch(() => null);
      if (got && (!best || got.n > best.n)) best = got;
    }
    await dashReset(page);
    return best ? { k: 'landlord', v: best.v } : null;
  };
  const openDrawer = (page, which) => page.evaluate(w => {
    const D = window.DASH && window.DASH.api;
    const rows = [...document.querySelectorAll('#view-dash tbody tr')].filter(r => r.getClientRects().length && !r.classList.contains('empty-row'));
    if (D && D.all && D.openDrawer && w !== 'first' && w !== 'sparse') {
      const u = D.all.find(u => String(u.id) === String(w));
      if (u) { D.openDrawer(u); return String(u.short || u.name || u.id); }
    }
    let tr = null;
    if (w === 'first') tr = rows[0];
    else if (w === 'sparse') { const s = rows.map(r => ({ r, n: (r.textContent.match(/n\/r|not recorded/g) || []).length })).sort((a, b) => b.n - a.n)[0]; tr = s && s.r; }
    else if (/^\d+$/.test(w)) tr = rows[+w - 1];
    if (!tr) return null;
    tr.scrollIntoView({ block: 'center', behavior: 'instant' }); tr.click();
    return (tr.querySelector('td') || tr).innerText.split('\n')[0].trim();
  }, which);

  const scrollToSel = (page, s) => page.evaluate(q => {
    const e = document.querySelector(q); if (!e) return false;
    scrollTo({ top: Math.max(0, e.getBoundingClientRect().top + scrollY - 140), behavior: 'instant' }); return true;
  }, s);

  const dashboard = async (page, vp) => {
    const okDash = await dashSteps(page, vp, 'dash');
    if (!okDash) return;
    await dashReset(page);
    // map zoomed in (labels and markers re-place themselves on zoom)
    if (await scrollToSel(page, '#view-dash .leaflet-container')) {
      for (const [n, lab] of [[2, 'z+2'], [2, 'z+4']]) {
        for (let k = 0; k < n; k++) { await page.click('#view-dash .leaflet-control-zoom-in', { timeout: 3000 }).catch(() => {}); await page.waitForTimeout(350); }
        await page.waitForTimeout(900);
        const r = await audit(page, { wait: 0 });
        record(vp, 'map', lab, r, await shot(page, `${vp}-map-${lab}`));
      }
      for (let k = 0; k < 4; k++) { await page.click('#view-dash .leaflet-control-zoom-out', { timeout: 3000 }).catch(() => {}); await page.waitForTimeout(250); }
    }
    // filtered and sparse states: every panel must survive thin data
    if (!opt.quick) {
      const list = FILTERS.length ? FILTERS : [await largestLandlord(page)].filter(Boolean);
      for (const f of list) {
        await dashReset(page);
        const how = await applyFilter(page, f).catch(() => null);
        await page.waitForTimeout(600);
        const tag = 'filter-' + slug(f.k + '-' + f.v);
        if (!how) { record(vp, tag, 'apply', { error: 'could not apply filter ' + f.k + '=' + f.v }, null); continue; }
        await dashSteps(page, vp, tag);
      }
      await dashReset(page);
      const sels = await page.$$('#view-dash select');
      if (sels.length) {
        for (const s of sels) {
          const n = await s.evaluate(e => e.options.length).catch(() => 0);
          if (n > 1) await s.selectOption({ index: n - 1 }).catch(() => {});
          await page.waitForTimeout(250);
        }
        await page.waitForTimeout(500);
        await dashSteps(page, vp, 'sparse');
      }
      await dashReset(page);
    }
    // drawer: named units / rows, else the first row and the sparsest record
    for (const w of (opt.drawers.length ? opt.drawers : ['first', 'sparse'])) {
      const name = await openDrawer(page, w).catch(() => null);
      if (!name) { record(vp, 'drawer', String(w), { error: 'could not open drawer ' + w }, null); continue; }
      await page.waitForTimeout(700);
      const lab = slug(name);
      let r = await audit(page, { wait: 0 });
      record(vp, 'drawer', lab + ' top', r, await shot(page, `${vp}-drawer-${lab}-top`));
      await page.evaluate(() => {
        const d = document.querySelector('#view-dash [role=dialog][aria-hidden=false], #view-dash .drawer.on, #view-dash [aria-modal=true]');
        if (!d) return; for (const e of d.querySelectorAll('*')) if (e.scrollHeight > e.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(e).overflowY)) e.scrollTop = e.scrollHeight;
      });
      await page.waitForTimeout(300);
      r = await audit(page, { wait: 0 });
      record(vp, 'drawer', lab + ' end', r, await shot(page, `${vp}-drawer-${lab}-end`));
      await page.keyboard.press('Escape');
      await page.waitForTimeout(400);
    }
  };

  /* -------------------------------------------------------------- print */
  const printPass = async () => {
    const PW_ = 688, PH_ = 1017;       // the printable area of A4 at 96 dpi with the 14mm @page margins
    const vp = 'print';
    console.log('print (A4, print media)');
    fs.mkdirSync(PRINTDIR, { recursive: true });
    const { ctx, page } = await newPage(PW_, PH_);
    const views = opt.only === 'dash' ? ['dash'] : opt.only === 'story' ? ['story'] : ['story', 'dash'];
    for (const view of views) {
      await page.emulateMedia({ media: 'screen' });
      await audit(page, { action: 'list', view });
      await page.evaluate(() => scrollTo(0, 0));
      await page.waitForTimeout(view === 'dash' ? 1500 : 300);
      await page.emulateMedia({ media: 'print' });
      await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
      await page.waitForTimeout(900);
      const r = await audit(page, { action: 'print' });
      record(vp, 'print', view + ' document', r, null);
      const H = await page.evaluate(() => document.documentElement.scrollHeight);
      for (let y = 0, i = 0; y < H - 10 && i < (view === 'dash' ? 24 : 60); y += Math.round(PH_ * 0.9), i++) {
        const a = await audit(page, { y, wait: 250 });
        record(vp, 'print', view + ' y' + y, a, await shot(page, `print-${view}-${pad(i)}`));
      }
      await page.evaluate(() => scrollTo(0, 0));
      const pdf = path.join(PRINTDIR, view + '.pdf');
      try {
        await page.pdf({ path: pdf, format: 'A4', printBackground: true, preferCSSPageSize: true });
        const info = pdfInfo(pdf);
        const renderer = opt.shots ? renderPdf(pdf, path.join(PRINTDIR, view)) : null;
        printInfo[view] = { pdf: path.relative(OUT, pdf), pages: info.pages, blank: info.blank, pagesWithoutText: info.noText, renderer: renderer || 'none (DOM checks and print-media screenshots only)', parsed: info.parsed };
        const issues = info.blank.map(p => ({ type: 'printBlank', sev: 'P2', scene: null, panel: null, node: null, text: view + ' PDF page ' + p,
          detail: { page: p, of: info.pages, note: 'a blank page in the printed ' + view + ': a pin spacer, a forced break or an empty block' }, rect: null }));
        record(vp, 'print', view + ' pdf', { meta: { view, pages: info.pages }, counts: { printBlank: issues.length }, issues }, null);
        console.log(`  ${view}.pdf: ${info.pages} pages${info.blank.length ? ', blank: ' + info.blank.join(', ') : ''}${renderer ? ', page images by ' + renderer : ''}`);
      } catch (e) { record(vp, 'print', view + ' pdf', { error: 'page.pdf failed: ' + String(e.message || e).split('\n')[0] }, null); }
    }
    await page.emulateMedia({ media: 'screen' });
    await ctx.close();
  };

  /* ------------------------------------------------ report (incremental) */
  const FOLD = /^(smallText|contrast|contrastDimmed|covered|clickNoKeyboard|smallTarget|lineThroughText|truncated|clipped|labelMark)$/;
  const sig = i => {
    const d = i.detail || {};
    if (i.type === 'smallText') return 'px' + Math.round(d.px || 0);
    if (i.type === 'clipped') return (d.by || '') + (d.note ? '|edge' : '');
    if (i.type === 'labelMark') return d.mark && /point|marker/.test(d.mark) ? d.mark : 'chart';
    if (/^contrast/.test(i.type)) return d.need + '|' + Math.round((d.ratio || 0) * 2) / 2;
    if (i.type === 'covered') return d.layer || d.by || '';
    if (i.type === 'clickNoKeyboard') return d.selector || '';
    if (i.type === 'lineThroughText') return d.line || '';
    return JSON.stringify(d).slice(0, 60);
  };
  const droppedText = () => {
    // chart labels rendered at one desktop viewport and missing at another, under
    // reduced motion (finished states only). A line counts as present when all
    // its words appear in that viewport's labels, so re-wrapping is not a drop.
    const words = s => String(s).toLowerCase().replace(/[…]|\.\.\./g, ' ').split(/[^a-z0-9£%.]+/i).map(w => w.replace(/\.+$/, '')).filter(Boolean);
    const per = new Map();
    for (const i of inventories) {
      if (+i.vp.split('x')[0] <= 820) continue;
      for (const [scene, list] of Object.entries(i.inv)) {
        if (!per.has(scene)) per.set(scene, new Map());
        const m = per.get(scene); if (!m.has(i.vp)) m.set(i.vp, new Set());
        for (const s of list) m.get(i.vp).add(s);
      }
    }
    // A label whose numbers change with the width ("2 km" vs "5 km" on a scale
    // bar, a different set of axis ticks) is a variant, not a drop: it is only
    // dropped when fewer labels of its shape (digits masked) are rendered here.
    const shape = s => String(s).replace(/\d+([.,]\d+)*/g, '#').replace(/\s+/g, ' ').trim().toLowerCase();
    const shapeCount = set => { const m = new Map(); for (const s of set) m.set(shape(s), (m.get(shape(s)) || 0) + 1); return m; };
    const out = [];
    for (const [scene, byVp] of per) {
      if (byVp.size < 2) continue;
      const bags = new Map([...byVp].map(([vp, set]) => [vp, new Set([...set].flatMap(words))]));
      const shapes = new Map([...byVp].map(([vp, set]) => [vp, shapeCount(set)]));
      for (const [vp, set] of byVp) {
        const bag = bags.get(vp), missing = new Map();
        for (const [ovp, oset] of byVp) {
          if (ovp === vp) continue;
          for (const s of oset) {
            if (set.has(s)) continue;
            const w = words(s); const trunc = /…|\.\.\.$/.test(s);
            const need = trunc ? w.slice(0, -1) : w;
            if (!need.length || need.every(x => bag.has(x))) continue;
            const sh = shape(s);
            if ((shapes.get(vp).get(sh) || 0) >= (shapes.get(ovp).get(sh) || 0)) continue;
            if (/^[#\s.,%£$kmx×–-]*$/i.test(sh)) continue;      // bare numbers: axis ticks thin out with width
            if (!missing.has(s)) missing.set(s, new Set()); missing.get(s).add(ovp);
          }
        }
        if (missing.size) out.push({ type: 'droppedText', sev: 'P2', scene: '#' + scene, panel: null, node: null,
          text: [...missing.keys()].slice(0, 4).join(' · '), detail: { viewport: vp, labels: missing.size, shownAt: [...new Set([...missing.values()].flatMap(s => [...s]))],
          note: 'a chart label shown at another viewport is not rendered here (dropped to fit); check the lane or tile that lost it' } });
      }
    }
    return out;
  };
  const build = () => {
    const groups = new Map();
    const allRuns = runs.concat(inventories.length ? [{ viewport: 'compare', state: 'compare', where: 'desktop viewports', shot: null, issues: droppedText() }] : []);
    for (const run of allRuns) {
      for (const i of run.issues) {
        const fold = FOLD.test(i.type);
        const key = [i.type, i.sev, i.scene || '', i.panel || '', i.node || '', fold ? sig(i) : (i.text || JSON.stringify(i.detail || {}).slice(0, 60))].join('|');
        if (!groups.has(key)) groups.set(key, { i, vps: new Set(), states: new Set(), shot: run.shot, n: 0, examples: new Set() });
        const g = groups.get(key); g.vps.add(i.type === 'droppedText' ? i.detail.viewport : run.viewport); g.states.add(run.state + ':' + run.where); g.n++;
        if (i.text) g.examples.add(i.text);
        if (!g.shot && run.shot) g.shot = run.shot;
      }
    }
    for (const g of groups.values()) if (FOLD.test(g.i.type) && g.examples.size > 1) {
      const ex = [...g.examples];
      g.i = Object.assign({}, g.i, { text: ex.slice(0, 4).map(s => '"' + s + '"').join(' · ') + (ex.length > 4 ? ' (+' + (ex.length - 4) + ' more)' : ''), items: ex.length, quoted: true });
    }
    const order = { P1: 0, P2: 1, P3: 2 };
    const list = [...groups.values()].sort((a, b) => order[a.i.sev] - order[b.i.sev] || a.i.type.localeCompare(b.i.type));
    const byType = {};
    for (const r of runs) for (const k of Object.keys(r.counts || {})) byType[k] = byType[k] || 0;
    for (const g of list) byType[g.i.type] = (byType[g.i.type] || 0) + 1;
    const bySev = { P1: 0, P2: 0, P3: 0 }; for (const g of list) bySev[g.i.sev]++;
    return { list, byType, bySev };
  };
  const errsOf = () => consoleLog.filter(c => !/arcgisonline|ERR_INTERNET_DISCONNECTED|ERR_NAME_NOT_RESOLVED|Failed to load resource/i.test(c.text));
  const flush = partial => {
    lastFlush = Date.now();
    try {
      const { list, byType, bySev } = build();
      const json = { file: pageUrl, when: new Date().toISOString(), partial: !!partial, elapsedS: Math.round((Date.now() - t0) / 1000),
        viewports: VIEWPORTS.map(v => v.join('x')), options: { quick: !!opt.quick, filters: FILTERS, drawers: opt.drawers, rm: !opt.noRm, print: !opt.noPrint },
        summary: { defects: list.length, ...bySev, consoleErrors: errsOf().length, byType },
        defects: list.map((g, n) => ({ n: n + 1, ...g.i, viewports: [...g.vps], states: [...g.states], shot: g.shot })),
        print: printInfo, pageText: fs.existsSync(TEXT_OUT) ? TEXT_OUT : null, console: consoleLog, runs };
      fs.writeFileSync(path.join(OUT, 'qa-report.json'), JSON.stringify(json, null, 1));
    } catch (e) { /* keep going */ }
  };

  /* -------------------------------------------------------------- sweep */
  for (const [w, h] of VIEWPORTS) {
    const vp = w + 'x' + h;
    console.log(vp);
    const { ctx, page } = await newPage(w, h);
    if (opt.only !== 'dash') await storyWalk(page, vp, 'story');
    if (opt.only !== 'story') await dashboard(page, vp);
    await ctx.close();
    if (opt.only !== 'dash' && !opt.noRm) {
      console.log(vp + ' reduced motion');
      const rmp = await newPage(w, h, { reducedMotion: 'reduce' });
      await storyWalk(rmp.page, vp, 'rm');
      await rmp.ctx.close();
    }
    flush(true);
  }
  if (!opt.noPrint) { await printPass(); flush(true); }
  if (!opt.noText && PAGETEXT) {
    try {
      const { ctx, page } = await newPage(1440, 900, { reducedMotion: 'reduce' });
      const txt = await page.evaluate(`(${PAGETEXT})(${JSON.stringify({ filters: FILTERS.map(f => [f.k, f.v]), drawers: opt.drawers })})`);
      fs.mkdirSync(path.dirname(TEXT_OUT), { recursive: true });
      fs.writeFileSync(TEXT_OUT, String(txt), 'utf8');
      console.log('page text: ' + TEXT_OUT + '  (' + String(txt).split('\n').length + ' lines)');
      await ctx.close();
    } catch (e) { console.log('page text failed: ' + String(e.message || e).split('\n')[0]); }
  }
  await browser.close();
  flush(false);

  /* ---------------------------------------------------------- printout */
  const { list, bySev } = build();
  const fmtDetail = d => {
    if (!d) return '';
    const { note, ...rest } = d;
    return Object.entries(rest).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => k + '=' + (Array.isArray(v) ? v.join(' ') : v)).join(' ');
  };
  console.log('\n================================================ QA REPORT');
  console.log(pageUrl + '\n' + runs.length + ' audited states, ' + ((Date.now() - t0) / 1000).toFixed(0) + 's\n');
  list.forEach((g, n) => {
    const where = [g.i.scene, g.i.panel ? '"' + g.i.panel + '"' : null].filter(Boolean).join(' ') || g.i.node || '';
    console.log(`${String(n + 1).padStart(3)}. ${g.i.sev} ${g.i.type.padEnd(15)} ${where}`);
    if (g.i.text) console.log('      text: ' + (g.i.quoted ? g.i.text : '"' + g.i.text + '"'));
    const d = fmtDetail(g.i.detail); if (d) console.log('      ' + d);
    console.log('      at: ' + [...g.vps].join(', ') + '  (' + [...g.states].slice(0, 3).join('; ') + (g.states.size > 3 ? '; +' + (g.states.size - 3) : '') + ')' + (g.shot ? '  shot: ' + g.shot : ''));
  });
  const notes = {};
  for (const g of list) if (g.i.detail && g.i.detail.note && !notes[g.i.type]) notes[g.i.type] = g.i.detail.note;
  if (Object.keys(notes).length) { console.log('\nnotes'); for (const [t, n] of Object.entries(notes)) console.log('  ' + t + ': ' + n); }
  for (const [v, p] of Object.entries(printInfo)) console.log(`\nprint ${v}: ${p.pdf}, ${p.pages} pages, blank ${p.blank.length ? p.blank.join(', ') : 'none'}, page images: ${p.renderer}`);
  const errs = errsOf();
  console.log('\nconsole: ' + (errs.length ? errs.length + ' errors' : 'clean') + (consoleLog.length > errs.length ? '  (' + (consoleLog.length - errs.length) + ' network/tile messages ignored)' : ''));
  errs.slice(0, 8).forEach(e => console.log('  [' + e.vp + '] ' + e.type + ': ' + e.text));
  console.log('\ndefects: ' + list.length + '  (P1 ' + bySev.P1 + ', P2 ' + bySev.P2 + ', P3 ' + bySev.P3 + ')' + (errs.length ? ' + console errors' : ''));
  console.log('report: ' + path.join(OUT, 'qa-report.json'));
  process.exit(bySev.P1 || errs.length ? 1 : 0);
})().catch(e => { console.log('\nQA driver crashed: ' + (e && e.stack || e)); process.exit(2); });
