// evals/chrome_v45_test.mjs - execute the REAL v45 chrome from a BUILT dashboard.
//
// The five behaviours here are the ones a structural grep cannot tell apart from a comment
// that mentions them, so they are EXECUTED:
//   1. titleStr()   - the client's own displayName wins over the park + unit composition.
//   2. partyLine()  - the card names the party, landlord first, and the label follows the
//                     VALUE so a developer is never printed under a "Landlord" label.
//   3. the FOUR RENT rows always print (BLANK included) while every other row still omits.
//   4. the modal's meta chips are sentinel-GUARDED, and a link chip is emitted only for a
//                     stated http(s) URL - never for the blank token, which is a string and
//                     would otherwise have shipped href="TBC" as a live link.
//   5. Compare cells carry no highlight class.
// Offline; no npm deps.  Usage: node chrome_v45_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node chrome_v45_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const code = scripts.join('\n;\n') +
  '\n;\n__capture__("PROPS", typeof PROPS !== "undefined" ? PROPS : undefined);' +
  '\n__capture__("BLANK", typeof BLANK !== "undefined" ? BLANK : undefined);' +
  '\n__capture__("titleStr", typeof titleStr !== "undefined" ? titleStr : undefined);' +
  '\n__capture__("partyLine", typeof partyLine !== "undefined" ? partyLine : undefined);' +
  '\n__capture__("cardHTML", typeof cardHTML !== "undefined" ? cardHTML : undefined);' +
  '\n__capture__("detailHTML", typeof detailHTML !== "undefined" ? detailHTML : undefined);\n';

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

const { PROPS: props, BLANK, titleStr, partyLine, cardHTML, detailHTML } = target;
for (const [n, v] of Object.entries({ titleStr, partyLine, cardHTML, detailHTML })) {
  if (typeof v !== 'function') { console.error(`FAIL: could not capture ${n}() from the built chrome`); process.exit(1); }
}
if (!Array.isArray(props)) { console.error('FAIL: could not capture PROPS'); process.exit(1); }

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };
const byPark = p => props.find(x => x.park === p);

console.log('-- BLANK: one token, and it is the one the pipeline writes --');
ck(BLANK === 'TBC', `the chrome's BLANK is ${JSON.stringify(BLANK)}`);

console.log('\n-- titleStr(): the client\'s own name wins --');
ck(titleStr({ displayName: 'Titan, Knowsley Business Park', park: 'Knowsley Business Park', unit: 'Titan' })
   === 'Titan, Knowsley Business Park', 'a stated displayName is the title, verbatim');
ck(titleStr({ displayName: BLANK, park: 'Kestrel Reach', unit: 'Unit 3' }) === 'Kestrel Reach Unit 3',
   'the BLANK sentinel is not a name, so park + unit still compose');
ck(titleStr({ displayName: 'tbd', park: 'Kestrel Reach', unit: 'Unit 3' }) === 'Kestrel Reach Unit 3',
   "...and so is a pre-v45 canonical's 'tbd'");
ck(titleStr({ displayName: '   ', park: 'Kestrel Reach' }) === 'Kestrel Reach',
   'whitespace is not a name either');
ck(titleStr({ park: 'Kestrel Reach', unit: 'Unit 3' }) === 'Kestrel Reach Unit 3',
   'the v40 park + unit rules are untouched when no displayName is stated');
ck(titleStr({ park: 'Kestrel Reach Unit 3', unit: 'Unit 3' }) === 'Kestrel Reach Unit 3',
   '...including the whole-token de-duplication');
ck(titleStr({ displayName: 'Titan' }) === 'Titan', 'a displayName alone is enough');

console.log('\n-- partyLine(): the label follows the value --');
ck(partyLine({ landlord: 'Tritax', developer: 'Panattoni' }) === 'Landlord: Tritax',
   'a stated landlord wins - it is the party to the lease');
ck(partyLine({ landlord: BLANK, developer: 'Panattoni' }) === 'Developer: Panattoni',
   'no landlord: the DEVELOPER is named, under its own label, never under "Landlord"');
ck(partyLine({ landlord: BLANK, developer: BLANK }) === `Landlord: ${BLANK}`,
   'neither stated: the label plus the blank, because "no party named" is the fact');
ck(partyLine({}) === `Landlord: ${BLANK}`, 'an empty property does not throw or print undefined');

console.log('\n-- the card --');
const titan = byPark('Knowsley Business Park');
if (!titan) { console.error('FAIL: fixture property missing'); process.exit(1); }
const card = cardHTML(titan);
ck(/<div class="dev-line">Landlord: Indurent<\/div>/.test(card),
   'the card prints the party line, and nothing else, in .dev-line');
ck(!/J\d|M\d\d?,/.test(card.split('</div>')[card.split('</div>').findIndex(x => /dev-line/.test(x))] || ''),
   'the motorway no longer rides along in that line');
ck(card.includes('Titan, Knowsley Business Park'), 'the card title is the displayName');

console.log('\n-- the modal: the four rent rows always print, every other row omits --');
const modal = detailHTML(titan);
// the label is escaped: 'Warehouse rent (monthly)' carries regex metacharacters, and an
// unescaped lookup silently returns null - which reads as "the row is absent" and would have
// passed the omission assertions below for the wrong reason.
const rx = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const rowIn = (h, label) => {
  const m = h.match(new RegExp('<div class="spec-k">' + rx(label)
                               + '<\\/div><div class="spec-v">([\\s\\S]*?)<\\/div>'));
  return m ? m[1] : null;
};
const rowOf = (label) => rowIn(modal, label);
ck(rowOf('Warehouse rent (monthly)') !== null, 'the monthly rent row is present');
ck(rowOf('Total annual rent') !== null, 'the total annual rent row is present');
ck(rowOf('Total monthly rent') !== null, 'the total monthly rent row is present');
ck(rowOf('Warehouse rent') !== null && /9\.50/.test(rowOf('Warehouse rent')),
   'a STATED rent prints its own figure, untouched');
ck(rowOf('Service charge') === null,
   'an unstated service charge still OMITS - the always-print rule is the four rent rows only');
ck(rowOf('Lease term') === null, '...and an unstated lease term omits');
ck(rowOf('Rent-free period') === null, '...and the rent-free period');
ck(rowOf('Incentives') === null, '...and incentives');
ck(rowOf('Land price') === null, '...and land price');
ck(rowOf('REIT') === null, '...and the REIT flag, which is not a quoted term at all');
ck(rowOf('Floor load') === null, 'an unstated TECHNICAL spec still omits its row entirely');
ck(rowOf('Sprinklers') === null, '...and so does an unstated sprinkler spec');
ck(rowOf('Clear height') === '15.25m', 'a stated technical spec is unchanged');
// Asserted on the ROW VALUES rather than on a slice of the modal: the chrome's shared prose
// (coords_rings_est, modal_approx_note) carries a long dash of its own and is not this
// change's to edit, while the defect v45 fixed was five rows whose VALUE was a bare dash.
ck(!/<div class="spec-v">\s*[—–]\s*<\/div>/.test(modal),
   'no row prints a bare long dash as its value (five rows used to: three rent, two lease)');

console.log('\n-- the modal head: guarded chips, and one chip per STATED link --');
ck(/<span>Knowsley<\/span>/.test(modal), 'the city chip is there');
ck(!new RegExp('<span>' + BLANK + '</span>').test(modal),
   'no chip is printed for a field whose value is the blank token');
ck((modal.match(/class="map-link"/g) || []).length === 5,
   'five link chips: maps, brochure, video, website, Street View');
ck(modal.includes('>Watch video ↗<') && modal.includes('>Visit website ↗<')
   && modal.includes('>Street View ↗<'), 'each media chip carries its own label');
ck(!modal.includes(`href="${BLANK}"`), 'the blank token is NEVER emitted as an href');

const thin = byPark('Thin Park');
if (thin) {
  const thinModal = detailHTML(thin);
  ck((thinModal.match(/class="map-link"/g) || []).length === 1,
     'a property that states no links gets the derived maps chip and nothing else');
  ck(!/<span>undefined<\/span>/.test(thinModal), 'and no chip renders the string "undefined"');
  const rentRows = ['Warehouse rent', 'Warehouse rent (monthly)', 'Total annual rent',
                    'Total monthly rent'].map(l => rowIn(thinModal, l));
  ck(rentRows.every(v => v === BLANK),
     `a property that quotes no rent at all prints ${BLANK} on all FOUR rent rows `
     + JSON.stringify(rentRows));
  ck(!new RegExp('<div class="spec-k">Service charge<\\/div>').test(thinModal),
     '...and still omits every other commercial row');
}

console.log('\n-- Compare: every cell neutral --');
ck(!/cmp-highlight/.test(html), 'the built file carries no cmp-highlight class at all');

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
