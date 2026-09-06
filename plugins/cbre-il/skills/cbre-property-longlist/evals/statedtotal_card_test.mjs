// evals/statedtotal_card_test.mjs - execute the REAL statedTotalHTML() and cardHTML() from a
// BUILT dashboard: the source's own printed total shows where it disagrees with the derived
// figure, and nowhere else.
// v41 (F26): glaVal() now ADOPTS that printed total, so the card's qualifier and the modal's
// "Total GLA" row read one figure. The assertion below that used to pin glaVal() as untouched
// pinned the very defect F26 removed (one label, two figures) and was rewritten, not weakened.
// evals/f26_gla_single_derivation_test.py carries the cross-surface check.
// Offline; no npm deps.  Usage: node statedtotal_card_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node statedtotal_card_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const code = scripts.join('\n;\n') +
  '\n;\n__capture__("PROPS", typeof PROPS !== "undefined" ? PROPS : undefined);' +
  '\n__capture__("statedTotalHTML", typeof statedTotalHTML !== "undefined" ? statedTotalHTML : undefined);' +
  '\n__capture__("cardHTML", typeof cardHTML !== "undefined" ? cardHTML : undefined);' +
  '\n__capture__("glaVal", typeof glaVal !== "undefined" ? glaVal : undefined);' +
  '\n__capture__("AREA_UNIT", typeof AREA_UNIT !== "undefined" ? AREA_UNIT : undefined);\n';

// See modal_render_test.mjs for why this sandbox is shaped the way it is.
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

const { PROPS: props, statedTotalHTML, cardHTML, glaVal, AREA_UNIT } = target;
if (typeof statedTotalHTML !== 'function' || typeof cardHTML !== 'function' || !Array.isArray(props)) {
  console.error('FAIL: could not capture statedTotalHTML/cardHTML/PROPS from the built chrome');
  process.exit(1);
}

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };
const sub = p => (cardHTML(p).match(/<small class="spec-total">([^<]*)</) || [])[1] || null;

const disagrees = props.find(p => p.park === 'Disagrees');
const agrees = props.find(p => p.park === 'Agrees');
const unstated = props.find(p => p.park === 'Unstated');
if (!disagrees || !agrees || !unstated) { console.error('FAIL: fixture properties missing'); process.exit(1); }

console.log('-- the printed total appears ONLY where it disagrees --');
ck(sub(disagrees) === `Total GLA 45,649 ${AREA_UNIT}`,
   `the disagreeing card shows the source's own total ${JSON.stringify(sub(disagrees))}`);
ck(sub(agrees) === null, 'the agreeing card shows nothing (inside the arithmetic tolerance)');
ck(sub(unstated) === null, 'a card whose source printed no total shows nothing');

console.log('\n-- it sits BESIDE the derived figure, and never replaces it --');
const card = cardHTML(disagrees);
ck(/40,000/.test(card), 'the derived warehouse figure is still on the card');
ck(card.indexOf('40,000') < card.indexOf('45,649'),
   'the derived figure leads and the printed total qualifies it');
ck(glaVal(disagrees) === 45649,
   `glaVal() ADOPTS the source's printed total (v41, F26) so the modal row shows the card's figure (${glaVal(disagrees)})`);
ck(glaVal(agrees) === 30000 && glaVal(unstated) === 20000,
   'where the builder surfaced no stated total, glaVal() is still warehouse + office');
ck(/<div class="spec-v">40,000 [^<]*<small class="spec-total">/.test(card),
   'both live inside the one warehouse spec tile');

console.log('\n-- the helper stays honest on every degenerate input --');
ck(statedTotalHTML({}) === '', 'no preBaked at all -> nothing');
ck(statedTotalHTML({ preBaked: {} }) === '', 'a preBaked with no statedTotal -> nothing');
ck(statedTotalHTML({ preBaked: { statedTotal: {} } }) === '', 'an empty statedTotal -> nothing');
ck(statedTotalHTML({ preBaked: { statedTotal: { value: 'tbd' } } }) === '',
   'a sentinel value -> nothing (NUMOK guards it, so no unit is ever glued to a sentinel)');
ck(statedTotalHTML({ preBaked: { statedTotal: { value: null } } }) === '', 'a null value -> nothing');
ck(statedTotalHTML({ preBaked: { statedTotal: { value: 45649, unit: 'sq ft' } } })
   === '<small class="spec-total">Total GLA 45,649 sq ft</small>',
   'a real figure carries a thousands separator and the STATED unit');
ck(statedTotalHTML({ preBaked: { statedTotal: { value: 45649, unit: '' } } })
   === `<small class="spec-total">Total GLA 45,649 ${AREA_UNIT}</small>`,
   "an unstated unit falls back to the dataset's own AREA_UNIT, never to a guess");

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
