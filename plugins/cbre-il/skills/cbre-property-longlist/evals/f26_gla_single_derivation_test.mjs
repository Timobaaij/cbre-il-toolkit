// evals/f26_gla_single_derivation_test.mjs - execute the REAL chrome from a BUILT dashboard and
// prove that every surface printing the "Total GLA" label prints the SAME figure. (F26)
// Offline; no npm deps.  Usage: node f26_gla_single_derivation_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node f26_gla_single_derivation_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const NAMES = ['PROPS', 'glaVal', 'glaStr', 'glaUnit', 'statedTotal', 'statedTotalHTML', 'cardHTML',
               'detailHTML', 'compareHTML', 'totalAnnualRent', 'AREA_UNIT', 'T'];
const code = scripts.join('\n;\n') + '\n;\n' +
  NAMES.map(n => `__capture__(${JSON.stringify(n)}, typeof ${n} !== "undefined" ? ${n} : undefined);`).join('\n') + '\n';

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

const { PROPS: props, glaVal, glaStr, glaUnit, statedTotal, statedTotalHTML, cardHTML, detailHTML,
        compareHTML, totalAnnualRent, AREA_UNIT, T } = target;
for (const [n, f] of Object.entries({ glaVal, glaStr, glaUnit, statedTotal, statedTotalHTML, cardHTML, detailHTML, T })) {
  if (typeof f !== 'function') { console.error(`FAIL: could not capture ${n}() from the built chrome`); process.exit(1); }
}
if (!Array.isArray(props)) { console.error('FAIL: PROPS not captured'); process.exit(1); }

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const LABEL = T('row_total_gla');
// the modal / compare cell that carries the Total GLA label -> its printed value
const rowValue = h => {
  const m = h.match(new RegExp(`<div class="spec-k">${esc(LABEL)}</div><div class="spec-v">([^<]*)</div>`));
  return m ? m[1] : null;
};
const cardSub = p => (cardHTML(p).match(/<small class="spec-total">([^<]*)</) || [])[1] || null;

const disagrees = props.find(p => p.park === 'Disagrees');
const agrees = props.find(p => p.park === 'Agrees');
const unstated = props.find(p => p.park === 'Unstated');
if (!disagrees || !agrees || !unstated) { console.error('FAIL: fixture properties missing'); process.exit(1); }

console.log('-- ONE figure under the one label, on a property whose source printed a larger total --');
const modalD = detailHTML(disagrees);
ck(glaVal(disagrees) === 45649, `glaVal() is the source's printed total (${glaVal(disagrees)})`);
ck(glaUnit(disagrees) === 'sq ft', `glaUnit() is the stated unit (${glaUnit(disagrees)})`);
ck(rowValue(modalD) === `45,649 sq ft`, `the MODAL row "${LABEL}" prints ${JSON.stringify(rowValue(modalD))}`);
ck(cardSub(disagrees) === `${LABEL} 45,649 sq ft`, `the CARD qualifier prints ${JSON.stringify(cardSub(disagrees))}`);
ck(rowValue(modalD) === glaStr(disagrees), 'the modal row IS glaStr(): no second derivation');
ck(!/42,000/.test(modalD), 'the summed 42,000 (warehouse + office) appears NOWHERE in the modal');
ck(!/42,000/.test(cardHTML(disagrees)), '...nor on the card');
if (typeof compareHTML === 'function') {
  let cmp = null;
  try { cmp = compareHTML([disagrees, agrees]); } catch (e) { cmp = null; }
  if (typeof cmp === 'string' && cmp.length) {
    ck(/45,649 sq ft/.test(cmp) && !/42,000/.test(cmp), 'the COMPARE matrix prints the stated total, never the sum');
  } else {
    console.log('  skip compareHTML needs a DOM here; its row is pinned structurally by the Python driver');
  }
}

console.log('\n-- the fallback is untouched where no stated total was surfaced --');
ck(glaVal(agrees) === 30000, `agreeing property (stated inside the tolerance, nothing attached): ${glaVal(agrees)}`);
ck(rowValue(detailHTML(agrees)) === `30,000 ${AREA_UNIT}` && cardSub(agrees) === null,
   'modal prints the sum, card prints no qualifier');
ck(glaVal(unstated) === 20000 && rowValue(detailHTML(unstated)) === `20,000 ${AREA_UNIT}`,
   'unstated total: warehouse + office, in the dataset unit');
ck(statedTotal({}) === null && statedTotal({ preBaked: { statedTotal: { value: 'tbd' } } }) === null
   && statedTotal({ preBaked: { statedTotal: { value: 0 } } }) === null,
   'statedTotal() refuses a missing, sentinel or non-positive figure');
ck(glaVal({ warehouseArea: 'tbd' }) === null && glaStr({ warehouseArea: 'tbd' }) === '\u2014',
   'no numeric warehouse area and no stated total -> null / the dash, exactly as before');
ck(glaVal({ warehouseArea: 1000, officeAreaVal: -5 }) === 1000 && glaVal({ warehouseArea: 1000, officeAreaVal: 250 }) === 1250,
   'the fallback keeps the > 0 office guard the arithmetic gate replicates');

console.log('\n-- money is NOT re-derived from the stated total --');
if (typeof totalAnnualRent === 'function') {
  ck(totalAnnualRent(disagrees) === 42000 * 9.5,
     `totalAnnualRent still multiplies the SUMMED areas (${totalAnnualRent(disagrees)}), never a total the source did not price`);
}

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
