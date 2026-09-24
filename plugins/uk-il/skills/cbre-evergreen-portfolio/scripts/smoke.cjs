#!/usr/bin/env node
/* smoke.cjs - the post-fix smoke check (committees.md, Phase 5). NOT a QA round.

   usage
     node smoke.cjs <file.html | http://...> [--playwright <path>]

   Loads the file at 1440x900 and at 390x844, runs scripts/smoke.js in each, and
   adds any console error or uncaught exception. Takes about a minute.
   exit 0 = pass, 1 = something is broken (listed), 2 = could not run: use the
   Playwright MCP route in smoke.js instead. */
'use strict';
const fs = require('fs'), path = require('path'), url = require('url'), cp = require('child_process');

const argv = process.argv.slice(2);
let target = null, pw = null;
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--playwright') pw = argv[++i];
  else if (!target) target = argv[i];
}
if (!target) { console.log('usage: node smoke.cjs <file.html> [--playwright <path>]'); process.exit(2); }
const remote = /^(https?|file):\/\//.test(target);
const abs = remote ? process.cwd() : path.resolve(target);
if (!remote && !fs.existsSync(abs)) { console.log('smoke: file not found: ' + abs); process.exit(2); }
const pageUrl = remote ? target : url.pathToFileURL(abs).href;
const SMOKE = fs.readFileSync(path.join(__dirname, 'smoke.js'), 'utf8');

function loadPlaywright() {
  const tries = [pw, process.env.PLAYWRIGHT_PATH].filter(Boolean).map(p => path.resolve(p));
  tries.push('playwright', 'playwright-core');
  for (let d = remote ? process.cwd() : path.dirname(abs), i = 0; i < 6; i++, d = path.dirname(d)) {
    for (const n of ['playwright', 'playwright-core']) tries.push(path.join(d, 'node_modules', n));
  }
  try {
    const g = cp.execSync('npm root -g', { stdio: ['ignore', 'pipe', 'ignore'], timeout: 8000 }).toString().trim();
    if (g) for (const n of ['playwright', 'playwright-core', path.join('@playwright', 'mcp', 'node_modules', 'playwright')]) tries.push(path.join(g, n));
  } catch (e) { /* no npm */ }
  for (const t of tries) { try { const m = require(t); if (m && m.chromium) return m; } catch (e) { /* next */ } }
  return null;
}

(async () => {
  const P = loadPlaywright();
  if (!P) { console.log('smoke: Node Playwright not found. Run scripts/smoke.js through the Playwright MCP instead.'); process.exit(2); }
  let browser;
  try { browser = await P.chromium.launch(); }
  catch (e) { console.log('smoke: could not start a browser: ' + String(e.message).split('\n')[0]); process.exit(2); }
  let failed = false;
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    const errs = [];
    page.on('pageerror', e => errs.push('uncaught: ' + String(e.message).split('\n')[0]));
    page.on('console', m => { if (m.type() === 'error' && !/favicon/i.test(m.text())) errs.push('console: ' + m.text().slice(0, 200)); });
    let r;
    try {
      await page.goto(pageUrl);
      await page.waitForTimeout(1500);
      r = await page.evaluate(`(${SMOKE})({})`);
    } catch (e) { r = { problems: ['smoke.js could not run: ' + String(e.message).split('\n')[0]], checked: {} }; }
    const problems = [...new Set(errs)].slice(0, 8).concat(r.problems || []);
    console.log(`${w}x${h}  ${problems.length ? 'FAIL' : 'pass'}  ${JSON.stringify(r.checked || {})}`);
    problems.forEach(p => console.log('  - ' + p));
    if (problems.length) failed = true;
    await page.close();
  }
  await browser.close();
  console.log(failed ? 'SMOKE: FAIL' : 'SMOKE: PASS');
  process.exit(failed ? 1 : 0);
})();
