/* ===================================================================
   Import a legacy hand-written tour app into tour.json.

     node import_legacy_tour.js old-index.html > tour.json

   The first generation of these apps kept their data in top-level JS
   arrays (PROPS / DAYS / MARKETS) inside the page. This lifts those out
   by evaluating just the declarations in a bare context, then reshapes
   them to the tour.json schema. Meta fields are guessed from <title>
   and the markup and should be reviewed by hand afterwards.
   =================================================================== */

const fs = require('fs');
const vm = require('vm');

const file = process.argv[2];
if (!file) {
  process.stderr.write('usage: node import_legacy_tour.js <old-index.html>\n');
  process.exit(2);
}
const html = fs.readFileSync(file, 'utf8');

/* Pull out the const declarations we care about, brace-matched so nested
   objects and arrays survive. Regex alone cannot do this reliably. */
function extractDecl(src, name) {
  const re = new RegExp('(?:const|let|var)\\s+' + name + '\\s*=\\s*', 'g');
  const m = re.exec(src);
  if (!m) return null;
  let i = m.index + m[0].length;
  const open = src[i];
  const close = open === '[' ? ']' : open === '{' ? '}' : null;
  if (!close) return null;
  let depth = 0, inStr = null, esc = false;
  for (let j = i; j < src.length; j++) {
    const c = src[j];
    if (esc) { esc = false; continue; }
    if (c === '\\') { esc = true; continue; }
    if (inStr) { if (c === inStr) inStr = null; continue; }
    if (c === '"' || c === "'" || c === '`') { inStr = c; continue; }
    if (c === open) depth++;
    else if (c === close) {
      depth--;
      if (depth === 0) return src.slice(i, j + 1);
    }
  }
  return null;
}

const tbcMatch = html.match(/(?:const|let|var)\s+TBC\s*=\s*(['"])(.*?)\1/);
const TBC = tbcMatch ? tbcMatch[2] : 'To be confirmed';

const parts = {};
for (const name of ['PROPS', 'DAYS', 'MARKETS']) {
  const raw = extractDecl(html, name);
  if (!raw) {
    process.stderr.write('could not find ' + name + ' in ' + file + '\n');
    process.exit(2);
  }
  // Evaluate in a sandbox with TBC defined; the arrays are plain literals.
  parts[name] = vm.runInNewContext('(' + raw + ')', { TBC });
}

/* ------------------------------------------------------------- reshape */
const props = parts.PROPS.map((p) => {
  const out = {
    id: p.id,
    market: p.market,
    name: p.name,
  };
  if (p.no != null) out.no = p.no;
  if (p.tour) out.tour = true;
  if (p.city) out.city = p.city;
  if (p.region) out.region = p.region;
  if (p.dev) out.dev = p.dev;
  if (p.lat != null) { out.lat = p.lat; out.lng = p.lng; }
  if (p.desc) out.desc = p.desc;

  if (p.query) out.query = p.query;

  // Lift the two headline numbers onto chips so cards read without opening.
  // Prefix match, because real sheets say "Warehouse area, building 01".
  const facts = p.facts || [];
  const terms = p.terms || [];
  const wh = facts.find((f) => /^warehouse area/i.test(f[0]) && f[1] !== TBC);
  if (wh) out.size = wh[1];

  const rent = terms.find((f) => /^warehouse rent/i.test(f[0]) && f[1] !== TBC);
  if (rent) {
    // "EUR 62.40 per sq m per annum at 10 m clear height" -> "EUR62.40 / sq m"
    const money = String(rent[1]).match(/EUR\s[\d.,]+(?:\sto\s[\d.,]+)?/);
    out.rent = money ? money[0].replace('EUR ', 'EUR ') + ' / sq m' : rent[1];
  }

  // null means "to be confirmed" in tour.json; the runtime renders it as such.
  if (facts.length) out.facts = facts.map((f) => [f[0], f[1] === TBC ? null : f[1]]);
  if (terms.length) out.terms = terms.map((f) => [f[0], f[1] === TBC ? null : f[1]]);
  return out;
});

const days = parts.DAYS.map((d) => {
  const out = {
    id: d.id,
    n: d.n,
    date: d.date,
    dow: d.dow,
    label: d.label,
  };
  // Legacy apps put the big day heading in the label; keep a short title too.
  if (d.title) out.title = d.title;
  if (d.region) out.region = d.region;
  if (d.market) out.market = d.market;
  if (d.note) out.note = d.note;
  out.stops = (d.stops || []).map((s) => {
    const st = { t: s.t, name: s.name };
    if (s.kind) st.kind = s.kind;
    if (s.prop) st.prop = s.prop;
    if (s.also) st.also = s.also;
    if (s.note) st.note = s.note;
    if (s.query) st.query = s.query;
    // Legacy encoded attendance in prose; promote it to a real field.
    if (s.note && /developer attending/i.test(s.note)) st.attend = true;
    if (s.note && /attendance to be confirmed/i.test(s.note)) st.attend = 'tbc';
    return st;
  });
  return out;
});

const markets = {};
for (const [k, v] of Object.entries(parts.MARKETS)) {
  markets[k] = { name: v.name, code: k };
  if (v.sub) markets[k].sub = v.sub;
  if (v.pack) markets[k].pack = v.pack;
}

/* ---------------------------------------------------------------- meta */
const titleTag = (html.match(/<title>([^<]*)<\/title>/) || [])[1] || '';
const h1 = (html.match(/<h1[^>]*>([^<]*)<\/h1>/) || [])[1] || '';
const segs = titleTag.split('·').map((s) => s.trim());

const meta = {
  title: (h1 || segs[0] || 'Site tour').trim(),
  documentTitle: titleTag || undefined,
  dateRange: segs[1] || undefined,
  wordmark: 'CBRE',
  appTitle: (h1 || segs[0] || 'Tour').trim(),
  lang: (html.match(/<html[^>]*lang="([^"]*)"/) || [])[1] || 'en',
  tbc: TBC,
};

const out = {
  meta,
  labels: { tbc: TBC },
  markets,
  properties: props,
  days,
};

process.stdout.write(JSON.stringify(out, null, 2) + '\n');
process.stderr.write(
  'imported ' + props.length + ' properties, ' + days.length + ' days, ' +
  Object.keys(markets).length + ' markets\n' +
  'REVIEW meta.* by hand: title, dateRange, subtitle, disclaimer, compiled.\n'
);
