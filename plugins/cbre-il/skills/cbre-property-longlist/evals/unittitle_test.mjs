// evals/unittitle_test.mjs - execute the REAL titleStr()/cardHTML()/propPopupHTML()/
// detailHTML()/compareHTML() from a BUILT dashboard and assert that a title identifies ONE
// option rather than one park.
// Offline; no npm deps.  Usage: node unittitle_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node unittitle_test.mjs <built_html>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const code = scripts.join('\n;\n') +
  '\n;\n__capture__("PROPS", typeof PROPS !== "undefined" ? PROPS : undefined);' +
  '\n__capture__("BLANK", typeof BLANK !== "undefined" ? BLANK : undefined);' +
  '\n__capture__("titleStr", typeof titleStr !== "undefined" ? titleStr : undefined);' +
  '\n__capture__("cardHTML", typeof cardHTML !== "undefined" ? cardHTML : undefined);' +
  '\n__capture__("detailHTML", typeof detailHTML !== "undefined" ? detailHTML : undefined);' +
  '\n__capture__("compareHTML", typeof compareHTML !== "undefined" ? compareHTML : undefined);' +
  '\n__capture__("propPopupHTML", typeof propPopupHTML !== "undefined" ? propPopupHTML : undefined);\n';

// See modal_render_test.mjs for why this sandbox is shaped the way it is (a top-level const does
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

const { PROPS: props, BLANK, titleStr, cardHTML, detailHTML, compareHTML, propPopupHTML } = target;
for (const [n, v] of Object.entries({ titleStr, cardHTML, detailHTML, compareHTML, propPopupHTML })) {
  if (typeof v !== 'function') { console.error(`FAIL: could not capture ${n}() from the built chrome`); process.exit(1); }
}
if (!Array.isArray(props)) { console.error('FAIL: could not capture PROPS'); process.exit(1); }

const fails = [];
const ck = (ok, label) => { console.log((ok ? '  ok   ' : '  FAIL ') + label); if (!ok) fails.push(label); };

const byId = id => props.find(p => p.id === id);
const u3 = byId(1), u4 = byId(2), already = byId(3), none = byId(4), lookalike = byId(5);

// the four title sites reachable from the sandbox, each read back out of the real markup
const SITES = [
  ['card title', p => (cardHTML(p).match(/<h3 class="card-title">([^<]*)</) || [])[1]],
  ['map popup title', p => (propPopupHTML(p).match(/<h4 class="popup-title">([^<]*)</) || [])[1]],
  ['modal title', p => (detailHTML(p).match(/<h2 class="modal-title">([^<]*)</) || [])[1]],
  ['compare column head', p => (compareHTML([p]).match(/<th>([^<]*)<span class="cmp-city">/) || [])[1]],
];

console.log('-- two units on one park render DISTINCT titles at every site --');
for (const [where, read] of SITES) {
  const a = read(u3), b = read(u4);
  ck(a === 'Kestrel Reach Unit 3', `${where}: unit 3 reads ${JSON.stringify(a)}`);
  ck(b === 'Kestrel Reach Unit 4', `${where}: unit 4 reads ${JSON.stringify(b)}`);
  ck(a !== b, `${where}: the two are DISTINGUISHABLE`);
}
// the compare table with BOTH columns present - the surface the reader actually chooses from
const bothTh = [...compareHTML([u3, u4]).matchAll(/<th>([^<]*)<span class="cmp-city">/g)].map(m => m[1]);
ck(bothTh.length === 2 && bothTh[0] !== bothTh[1],
   `compare table: the two column heads differ ${JSON.stringify(bothTh)}`);

console.log('\n-- no unit -> TODAY\'s title, byte-for-byte --');
for (const [where, read] of SITES) {
  const t = read(none);
  ck(t === 'Solo Park', `${where}: reads exactly the park name ${JSON.stringify(t)}`);
}
// v45: fill_render_sentinels writes normalize.BLANK; captured from the chrome so this stays a
// check that the FIXTURE carries a sentinel rather than a check on its spelling.
ck(none.unit === BLANK, 'the fixture really does carry the sentinel (not merely a missing key)');
ck(titleStr(none) === 'Solo Park', 'titleStr(): the sentinel renders NOTHING');
ck(!/tbd|tbc|\?\?/i.test(titleStr(none)), 'titleStr(): no word for unknown reaches the title');
ck(!/[\s·,\-]$/.test(titleStr(none)), 'titleStr(): no trailing separator or space');
ck(titleStr(none) === String(none.park), 'titleStr(): identical to the bare park name');

console.log('\n-- a park name that already carries the designator does NOT repeat it --');
for (const [where, read] of SITES) {
  const t = read(already);
  ck(t === 'Kestrel Reach Unit 5', `${where}: reads ${JSON.stringify(t)}`);
}
ck(titleStr({ park: 'Kestrel Reach Unit 3', unit: 'Unit 3' }) === 'Kestrel Reach Unit 3',
   'suffix position: no "... Unit 3 Unit 3"');
ck(titleStr({ park: 'Unit 3 Kestrel Reach', unit: 'Unit 3' }) === 'Unit 3 Kestrel Reach',
   'prefix position: contained anywhere counts, not only at the end');
ck(titleStr({ park: 'Kestrel Reach, Unit 3', unit: 'Unit 3' }) === 'Kestrel Reach, Unit 3',
   'punctuation between the words does not defeat the check');
ck(titleStr({ park: 'Kestrel Reach UNIT 3', unit: 'unit 3' }) === 'Kestrel Reach UNIT 3',
   'the check is case-insensitive');

console.log('\n-- a lookalike is NOT falsely suppressed (a substring test would lose real data) --');
ck(titleStr(lookalike) === 'Harrier Court 300 3',
   `a unit of "3" survives a park ending "300" ${JSON.stringify(titleStr(lookalike))}`);
ck(titleStr({ park: 'Harrier Court 3', unit: '3' }) === 'Harrier Court 3',
   'but a genuine whole-token match IS suppressed');

console.log('\n-- degenerate inputs stay honest --');
ck(titleStr({ park: 'tbd', unit: 'Unit 3' }) === 'Unit 3',
   'an unknown park with a real unit renders the unit alone');
ck(titleStr({ park: 'tbd', unit: 'tbd' }) === '',
   'both unknown -> falsy, so the fallback sites keep their T("label_option") path');
ck(titleStr({ park: 'Kestrel Reach', unit: '  Unit 3  ' }) === 'Kestrel Reach Unit 3',
   'a designator is trimmed, so stray whitespace cannot double the separator');
// the sentinel is written as an escape rather than the glyph, so the assertion cannot be
// broken by an editor or a pipe re-encoding one character of the file
ck(titleStr({ park: 'Kestrel Reach', unit: '\u2014' }) === 'Kestrel Reach',
   'the long-dash sentinel is treated as absent, like everywhere else in the chrome');
ck(titleStr({ park: 'Kestrel Reach', unit: '-' }) === 'Kestrel Reach',
   'and so is the short one');

console.log('STATUS:', fails.length ? 'BLOCKED' : 'ALL-PASS');
process.exit(fails.length ? 1 : 0);
