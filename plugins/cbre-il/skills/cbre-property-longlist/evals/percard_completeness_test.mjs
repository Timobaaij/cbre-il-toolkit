// evals/percard_completeness_test.mjs - execute the REAL detailHTML() and compareHTML() from a
// BUILT dashboard and assert the per-property rule over the CURATED row set.
// Offline; no npm deps.  Usage: node percard_completeness_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node percard_completeness_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const code = scripts.join('\n;\n') +
  '\n;\n__capture__("PROPS", typeof PROPS !== "undefined" ? PROPS : undefined);' +
  '\n__capture__("detailHTML", typeof detailHTML !== "undefined" ? detailHTML : undefined);' +
  '\n__capture__("compareHTML", typeof compareHTML !== "undefined" ? compareHTML : undefined);' +
  '\n__capture__("FIELD_PRESENT", typeof FIELD_PRESENT !== "undefined" ? FIELD_PRESENT : undefined);\n';

// See modal_render_test.mjs for why this sandbox is shaped the way it is (top-level const does
// not land on the context global; a has-always-true trap would otherwise shadow the intrinsics).
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
const ctx = vm.createContext(new Proxy(target, {
  get: (t, p) => (p in t ? t[p] : sink),
  has: () => true,
}));

try { vm.runInContext(code, ctx, { filename: 'built.inline.js' }); }
catch (e) { console.error('FAIL: template script threw during eval:', e && e.message); process.exit(1); }

const { PROPS: props, detailHTML, compareHTML } = target;
if (typeof detailHTML !== 'function' || typeof compareHTML !== 'function' || !Array.isArray(props)) {
  console.error('FAIL: could not capture detailHTML/compareHTML/PROPS from the built chrome');
  process.exit(1);
}

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };

const rich = props.find(p => p.park === 'Rich Park');
const lean = props.find(p => p.park === 'Lean Park');
if (!rich || !lean) { console.error('FAIL: fixture properties missing from PROPS'); process.exit(1); }

const rHtml = detailHTML(rich);
const lHtml = detailHTML(lean);

// --- the rule: a curated variable renders for the property that HAS it, and for no other ---
const CURATED = [
  ['Sprinklers', 'sprinklers'],
  ['Permitting', 'permitting'],
  ['Land price', 'landPrice'],
  ['Incentives', 'incentives'],
];
for (const [label, key] of CURATED) {
  ck(rHtml.includes(label), `modal: the rich property shows "${label}" (it carries ${key})`);
  ck(!lHtml.includes(label), `modal: the lean property does NOT show "${label}" - it has no value`);
}

const specCount = h => (h.match(/class="spec-k"/g) || []).length;
ck(specCount(rHtml) > specCount(lHtml),
   `modal: per-property row counts differ (rich ${specCount(rHtml)} > lean ${specCount(lHtml)})`);

// no empty rows anywhere: every rendered spec value must be a real value
const emptyRow = /<div class="spec-v">\s*(tbd|tbc|—|-|)\s*<\/div>/i;
ck(!emptyRow.test(rHtml), 'modal: the rich property renders no tbd/empty spec row');
ck(!emptyRow.test(lHtml), 'modal: the lean property renders no tbd/empty spec row');

// --- a variable no curated row owns renders NOWHERE, however real its value ---
const UNCURATED = ['Yard Rent', 'yardRent', 'Rail Siding', 'railSiding'];
for (const label of UNCURATED) {
  ck(!rHtml.includes(label), `modal: "${label}" has no curated row, so it renders nowhere`);
}

// --- Compare: a matrix, so rows are the union of what the CURATED list covers ---
const cHtml = compareHTML([rich, lean]);
ck(cHtml.includes('Land price'), 'compare: carries the curated Land price row');
ck(cHtml.includes('Sprinklers'), 'compare: carries the curated Sprinklers row');
ck(cHtml.includes('Incentives'), 'compare: carries the curated Incentives row');
for (const label of UNCURATED) {
  ck(!cHtml.includes(label), `compare: "${label}" has no curated row, so it renders nowhere`);
}

// the v9 gate still holds: a curated row NO property carries appears nowhere
ck(!cHtml.includes('Never Stated'), 'compare: a field no property carries is still dropped');
ck(!rHtml.includes('Never Stated'), 'modal: likewise');

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
