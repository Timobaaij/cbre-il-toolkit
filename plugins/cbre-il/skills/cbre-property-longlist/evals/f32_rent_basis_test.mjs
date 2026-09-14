// evals/f32_rent_basis_test.mjs - execute the REAL chrome from a BUILT dashboard and prove that
// every Total annual rent figure on the page carries the area x rate it was computed on, that
// the printed basis multiplies back to the printed figure, and that no money figure changed.
// (SEAM-16)  Offline; no npm deps.  Usage: node f32_rent_basis_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node f32_rent_basis_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const NAMES = ['PROPS', 'BLANK', 'glaVal', 'glaStr', 'rentBasis', 'rentBasisStr', 'totalAnnualRent', 'totalRentStr',
               'totalRentHTML', 'detailHTML', 'compareHTML', 'AREA_UNIT', 'T'];
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

const { PROPS: props, BLANK, glaVal, glaStr, rentBasis, rentBasisStr, totalAnnualRent, totalRentStr, totalRentHTML,
        detailHTML, compareHTML, AREA_UNIT, T } = target;
for (const [n, f] of Object.entries({ glaVal, glaStr, rentBasis, rentBasisStr, totalAnnualRent, totalRentStr,
                                      totalRentHTML, detailHTML, T })) {
  if (typeof f !== 'function') { console.error(`FAIL: could not capture ${n}() from the built chrome`); process.exit(1); }
}
if (!Array.isArray(props)) { console.error('FAIL: PROPS not captured'); process.exit(1); }

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const ANNUAL = T('row_total_annual_rent'), MONTHLY = T('row_total_monthly_rent'), GLA = T('row_total_gla');
// the modal row carrying a label -> its full spec-v innerHTML (null when the row is omitted)
const rowHtml = (h, label) => {
  const m = h.match(new RegExp(`<div class="spec-k">${esc(label)}</div><div class="spec-v">([\\s\\S]*?)</div></div>`));
  return m ? m[1] : null;
};
const num = s => Number(String(s).replace(/[^0-9.]/g, ''));
// parse every "(A [+ B]) u × C r / u" term back out of a basis line and re-multiply
const TERM_RX = new RegExp(`\\(?([\\d,.]+)(?: \\+ ([\\d,.]+))?\\)? ${esc(AREA_UNIT)} × \\S+ ([\\d,.]+) \\/ [^+]+?(?= \\+ |$)`, 'g');
const basisTotal = basis => {
  const terms = [...String(basis).matchAll(TERM_RX)];
  if (!terms.length) return NaN;
  return terms.reduce((acc, m) => acc + (num(m[1]) + (m[2] ? num(m[2]) : 0)) * num(m[3]), 0);
};

const byPark = n => props.find(p => p.park === n);
const disagrees = byPark('Disagrees'), split = byPark('Split'), ounk = byPark('OfficeUnknown'), runk = byPark('RentUnknown');
if (!disagrees || !split || !ounk || !runk) { console.error('FAIL: fixture properties missing'); process.exit(1); }

console.log('-- the figure and its basis, on a property whose GLA row reads a LARGER stated total --');
const mD = detailHTML(disagrees);
const annualD = rowHtml(mD, ANNUAL);
ck(rowHtml(mD, GLA) === '45,649 sq ft', `the GLA row prints the stated total (${JSON.stringify(rowHtml(mD, GLA))})`);
ck(annualD !== null && /^£ 399,000 \/ yr<small class="rent-basis">/.test(annualD),
   `the Total annual rent row prints the figure then a .rent-basis sub-line: ${JSON.stringify(annualD)}`);
const basisD = (annualD && annualD.match(/<small class="rent-basis">([^<]*)<\/small>/) || [])[1] || null;
ck(basisD === `(40,000 + 2,000) ${AREA_UNIT} × £ 9.50 / sq ft`,
   `the basis names the two lettable COMPONENTS at the quoted rate (${JSON.stringify(basisD)})`);
ck(basisD !== null && !/45,649/.test(basisD) && totalAnnualRent(disagrees) === 42000 * 9.5,
   'the rent is NOT computed on the stated total, and the basis does not claim it was');
ck(!/42,000/.test(mD), 'the summed figure itself appears nowhere in the modal (f26\'s pin for the GLA label holds)');
ck(Math.abs(basisTotal(basisD) - totalAnnualRent(disagrees)) < 0.5,
   `the printed basis multiplies back to the printed figure (${basisTotal(basisD)})`);
ck(annualD === totalRentHTML(disagrees, false), 'the modal row IS totalRentHTML(): no second composition');
ck(rowHtml(mD, MONTHLY) === '£ 33,250 / mo',
   `the monthly figure is the annual / 12 with no basis of its own (${JSON.stringify(rowHtml(mD, MONTHLY))})`);
ck(totalRentStr(disagrees, false) === '£ 399,000 / yr' && totalRentStr(disagrees, true) === '£ 33,250 / mo',
   'the money strings are byte-identical to v41: no money figure changed');

console.log('\n-- a separate office rate: two terms, each area at its own rate --');
const mS = detailHTML(split);
const basisS = (rowHtml(mS, ANNUAL) || '').match(/<small class="rent-basis">([^<]*)<\/small>/);
ck(basisS && basisS[1] === `30,000 ${AREA_UNIT} × £ 9.50 / sq ft + 1,000 ${AREA_UNIT} × £ 12.00 / sq ft`,
   `split basis: ${JSON.stringify(basisS && basisS[1])}`);
ck(totalAnnualRent(split) === 30000 * 9.5 + 1000 * 12 && Math.abs(basisTotal(basisS ? basisS[1] : '') - totalAnnualRent(split)) < 0.5,
   `split total ${totalAnnualRent(split)} equals the re-multiplied basis`);
ck(rentBasis(split).split === true && rentBasis(disagrees).split === false,
   'rentBasis().split decides BOTH the multiplication and the printed shape');

console.log('\n-- an unknown office area is absent from the formula: that absence is the disclosure --');
const basisO = (rowHtml(detailHTML(ounk), ANNUAL) || '').match(/<small class="rent-basis">([^<]*)<\/small>/);
ck(basisO && basisO[1] === `20,000 ${AREA_UNIT} × £ 9.50 / sq ft`,
   `warehouse area alone, no guessed office (${JSON.stringify(basisO && basisO[1])})`);
ck(totalAnnualRent(ounk) === 20000 * 9.5, 'and the money matches it');

console.log('\n-- an unknown rent stays unknown: no total, no basis, no figure --');
const mR = detailHTML(runk);
// v45: the commercial block always prints, so the two rows are PRESENT and carry the blank
// token. What this eval has always guarded is that no FIGURE and no BASIS is invented for a
// property with no stated rate, and that is asserted below on the helpers themselves.
ck(rowHtml(mR, ANNUAL) === BLANK && rowHtml(mR, MONTHLY) === BLANK,
   'both Total rent rows print the blank token, not a figure');
ck(!/rent-basis/.test(mR), 'no basis sub-line anywhere in that modal');
ck(totalAnnualRent(runk) === null && rentBasis(runk) === null && rentBasisStr(runk) === null && totalRentHTML(runk, false) === null,
   'every helper returns null rather than a figure');

console.log('\n-- the helpers refuse what totalAnnualRent() always refused --');
ck(rentBasis({ warehouseRentVal: 'tbd', warehouseArea: 1000 }) === null
   && rentBasis({ warehouseRentVal: 5, warehouseArea: 0 }) === null
   && rentBasis({ warehouseRentVal: -1, warehouseArea: 1000 }) === null,
   'sentinel, zero and negative inputs -> null');
const b = rentBasis({ warehouseRentVal: 5, warehouseArea: 1000, officeAreaVal: 100, officeRentVal: -2 });
ck(b && b.oa === 100 && b.or === null && b.split === false,
   'a non-positive office rate is dropped and the office area rides on the warehouse rate');

if (typeof compareHTML === 'function') {
  let cmp = null;
  try { cmp = compareHTML([disagrees, split]); } catch (e) { cmp = null; }
  if (typeof cmp === 'string' && cmp.length) {
    ck(/<small class="rent-basis">\(40,000 \+ 2,000\) /.test(cmp) && /<small class="rent-basis">30,000 /.test(cmp) && !/42,000/.test(cmp),
       'the COMPARE matrix prints each property\'s basis under its annual figure');
  } else {
    console.log('  skip compareHTML needs a DOM here; its row is pinned structurally by the Python driver');
  }
}

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
