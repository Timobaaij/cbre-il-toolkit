// evals/percard_completeness_test.mjs - execute the REAL detailHTML() and compareHTML() from a
// BUILT dashboard and assert per-property completeness (v33). Offline; no npm deps.
// Usage: node percard_completeness_test.mjs <built_html_path>
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

// --- the rule: A with more filled variables shows more rows than B, and B shows none of A's ---
const EXTRAS = [
  ['Sprinklers', 'a canonical field with a curated row'],
  ['Yard Rent', 'a BRAND-NEW key no schema carries (autoLabel-derived)'],
  ['Rail Siding', 'a second brand-new key'],
];
for (const [label, why] of EXTRAS) {
  ck(rHtml.includes(label), `modal: the rich property shows "${label}" - ${why}`);
  ck(!lHtml.includes(label), `modal: the lean property does NOT show "${label}" - it has no value`);
}

const specCount = h => (h.match(/class="spec-k"/g) || []).length;
ck(specCount(rHtml) > specCount(lean === rich ? '' : lHtml),
   `modal: per-property row counts differ (rich ${specCount(rHtml)} > lean ${specCount(lHtml)})`);

// no empty rows anywhere: every rendered spec value must be a real value
const emptyRow = /<div class="spec-v">\s*(tbd|tbc|—|-|)\s*<\/div>/i;
ck(!emptyRow.test(rHtml), 'modal: the rich property renders no tbd/empty spec row');
ck(!emptyRow.test(lHtml), 'modal: the lean property renders no tbd/empty spec row');

// --- Compare: a matrix, so rows are the union - but nothing the dataset carries may be missing ---
const cHtml = compareHTML([rich, lean]);
for (const [label] of EXTRAS) {
  ck(cHtml.includes(label), `compare: carries a row for "${label}" (v33 auto-rows)`);
}
ck(cHtml.includes('Land Price'),
   'compare: carries Land Price - a CANONICAL field the hand-written row list omitted before v33');
ck(cHtml.includes('Incentives'),
   'compare: carries Incentives - likewise absent from the curated list before v33');

// the v9 gate still holds: a field NO property carries appears nowhere
ck(!cHtml.includes('Never Stated'), 'compare: a field no property carries is still dropped');
ck(!rHtml.includes('Never Stated'), 'modal: likewise');

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
