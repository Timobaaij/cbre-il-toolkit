// evals/office_breakdown_test.mjs - execute the REAL officeAreaHTML() / officeAreaStr() /
// detailHTML() / compareHTML() from a BUILT dashboard and assert the v39 officeArea breakdown.
// Offline; no npm deps.  Usage: node office_breakdown_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node office_breakdown_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const code = scripts.join('\n;\n') +
  '\n;\n__capture__("PROPS", typeof PROPS !== "undefined" ? PROPS : undefined);' +
  '\n__capture__("officeAreaHTML", typeof officeAreaHTML !== "undefined" ? officeAreaHTML : undefined);' +
  '\n__capture__("officeAreaStr", typeof officeAreaStr !== "undefined" ? officeAreaStr : undefined);' +
  '\n__capture__("detailHTML", typeof detailHTML !== "undefined" ? detailHTML : undefined);' +
  '\n__capture__("compareHTML", typeof compareHTML !== "undefined" ? compareHTML : undefined);\n';

// Same sandbox shape as modal_render_test.mjs / percard_completeness_test.mjs (a top-level const
// does not land on the context global, and a has-always-true trap would shadow the intrinsics).
const sink = new Proxy(function () {}, {
  get: (_t, p) => (p === Symbol.toPrimitive || p === 'toString' || p === 'valueOf') ? () => '' : sink,
  apply: () => sink, construct: () => sink, has: () => true,
});
const target = { console };
for (const name of Object.getOwnPropertyNames(globalThis)) {
  if (!(name in target)) { try { target[name] = globalThis[name]; } catch { /* ignore */ } }
}
target.globalThis = target;
target.__capture__ = (name, val) => { target[name] = val; };
const ctx = vm.createContext(new Proxy(target, { get: (t, p) => (p in t ? t[p] : sink), has: () => true }));

try { vm.runInContext(code, ctx, { filename: 'built.inline.js' }); }
catch (e) { console.error('FAIL: template script threw during eval:', e && e.message); process.exit(1); }

const { PROPS: props, officeAreaHTML, officeAreaStr, detailHTML, compareHTML } = target;
if ([officeAreaHTML, officeAreaStr, detailHTML, compareHTML].some(f => typeof f !== 'function')
    || !Array.isArray(props)) {
  console.error('FAIL: could not capture officeAreaHTML/officeAreaStr/detailHTML/compareHTML/PROPS');
  process.exit(1);
}

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };
const P = name => {
  const p = props.find(x => x.park === name);
  if (!p) { console.error('FAIL: fixture property missing: ' + name); process.exit(1); }
  return p;
};
const LI = h => (h.match(/<li>/g) || []).length;
const COUNT = (h, s) => h.split(s).length - 1;

// ---------------------------------------------------------------- shape A: summary + ( ; list )
{
  const h = officeAreaHTML(P('Shape A'));
  ck(h.startsWith('<strong>45,649 sq ft total non-warehouse area</strong>'),
     'A: the leading clause becomes a BOLD summary line, verbatim, with no unit re-appended');
  ck(h.includes('<ul class="oa-breakdown">'), 'A: the breakdown is a real <ul>');
  ck(LI(h) === 5, `A: one <li> per component (5, got ${LI(h)})`);
  for (const want of ['<li>Offices, 2 levels — 28,804 sq ft</li>',
                      '<li>2nd floor meeting room — 1,711 sq ft</li>',
                      '<li>Transport office 1 — 7,492 sq ft</li>',
                      '<li>Transport office 2 — 7,427 sq ft</li>',
                      '<li>Gatehouse — 215 sq ft</li>']) {
    ck(h.includes(want), `A: renders ${want}`);
  }
  ck(COUNT(h, 'sq ft') === 6 && !/sq ft\s+sq ft/.test(h),
     'A: exactly one unit per line (1 summary + 5 items) and never a doubled unit');
  ck(!h.includes(';') && !h.includes('('), 'A: no run-on punctuation survives into the markup');
  // the label/value split must not eat a trailing index that is part of the NAME
  ck(!/Transport office — 1 /.test(h) && !/Transport office — 2 /.test(h),
     'A: "transport office 1 7,492" splits after the index, not before it');
}

// ---------------------------------------------------------------- shape B: bare `;` list, no summary
{
  const h = officeAreaHTML(P('Shape B'));
  ck(!h.includes('<strong>'), 'B: no summary clause is invented when the string has none');
  ck(LI(h) === 3, `B: 3 items (got ${LI(h)})`);
  ck(h.includes('<li>Main Office 15,213 sq ft</li>')
     && h.includes('<li>Hub Office 3,975 sq ft</li>')
     && h.includes('<li>Gatehouse 294 sq ft</li>'),
     'B: an item that already states its own unit is rendered VERBATIM');
  ck(COUNT(h, 'sq ft') === 3 && !/sq ft\s+sq ft/.test(h),
     'B: no second unit is appended to an item that carries one');
}

// ---------------------------------------------------------------- shape C: per-item trailing qualifier
{
  const h = officeAreaHTML(P('Shape C'));
  ck(!h.includes('<strong>'), 'C: no summary line');
  ck(LI(h) === 2, `C: 2 items (got ${LI(h)})`);
  ck(h.includes('<li>14,486 sq ft (ground floor)</li>')
     && h.includes('<li>15,592 sq ft (first floor)</li>'),
     "C: each item keeps its OWN parenthesised qualifier (the ; split is paren-depth aware)");
  ck(COUNT(h, 'sq ft') === 2, 'C: no unit is appended');
}

// ---------------------------------------------------------------- the plain shapes: byte-identical
for (const [name, want] of [['Plain Number', '24,230 sq ft'],
                            ['Plain Unit', '8,547 sq ft'],
                            ['Tbd Park', 'tbd'],
                            ['No Office Park', 'tbd']]) {
  const p = P(name);
  const h = officeAreaHTML(p);
  ck(h === officeAreaStr(p),
     `${name}: officeAreaHTML === officeAreaStr (byte-identical to pre-v39)`);
  ck(h === want, `${name}: reads ${JSON.stringify(want)}`);
  ck(!h.includes('<ul') && !h.includes('<strong'), `${name}: no markup is introduced`);
}

// ---------------------------------------------------------------- a NAME ending in an index
{
  const h = officeAreaHTML(P('Index Name'));
  ck(h.includes('<li>Transport office 2</li>'),
     'a component with no area keeps its trailing index and gains NO invented area');
  ck(!/Transport office — 2/.test(h),
     'a 1-2 digit tail is never read as an area (no "2 sq ft" fabricated)');
  ck(h.includes('<li>Office block A — 12,000 sq ft</li>'),
     'its area-bearing sibling in the same string still splits and gains the unit');
}

// ---------------------------------------------------------------- a bare-number summary clause
{
  const h = officeAreaHTML(P('Bare Summary'));
  ck(h.startsWith('<strong>24,230 sq ft</strong>'),
     'a summary clause that is a BARE number gains the dataset unit (and only one)');
  ck(LI(h) === 2, 'its two components still bullet');
}

// ---------------------------------------------------------------- the modal renders REAL markup
{
  const h = detailHTML(P('Shape A'));
  ck(h.includes('<ul class="oa-breakdown">') && !h.includes('&lt;ul'),
     'modal: row() interpolates the value RAW, so the list is markup and not escaped text');
  ck(/<div class="spec-v"><strong>45,649 sq ft total non-warehouse area<\/strong><ul/.test(h),
     'modal: the summary + list sit inside the Office area spec value');
  const t = detailHTML(P('Tbd Park'));
  ck(!t.includes('Office area'), "modal: a 'tbd' office area still omits the row entirely");
}

// ---------------------------------------------------------------- Compare stays FLATTENED
{
  const c = compareHTML([P('Shape A'), P('Shape B')]);
  ck(!c.includes('oa-breakdown') && !c.includes('<li>'),
     'compare: the matrix cell keeps the flattened string - no list, so no blown row height');
  ck(c.includes(officeAreaStr(P('Shape A'))),
     'compare: the cell is exactly officeAreaStr, unchanged from v32');
}

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
