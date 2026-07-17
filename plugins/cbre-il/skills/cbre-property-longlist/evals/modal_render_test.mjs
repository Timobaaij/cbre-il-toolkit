// evals/modal_render_test.mjs - evaluate the REAL detailHTML() from a BUILT dashboard
// html and assert the v21 data-driven modal behaviour. Offline; no npm deps.
// Usage: node modal_render_test.mjs <built_html_path>
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node modal_render_test.mjs <built_html_path>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');

// Concatenate every INLINE <script> (skip CDN <script src=...>). The app logic +
// the injected const PROPS/POIS/REGIONS + const UI/LOCALE all live in inline scripts.
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
// NOTE: top-level `const`/`let` declared inside vm-executed code do NOT become properties
// of the context's global object (only `var`/function declarations do) - so `ctx.PROPS`
// would silently read through the stub Proxy instead of the real array. `globalThis` itself
// also resolves through our own `has`-always-true trap and lands on the sink, not the real
// target, so a plain `globalThis.X = ...` capture doesn't work either. Instead expose a real
// capture function as an actual property of the target object (closed over `target`, so it
// writes directly to it, bypassing the trap entirely) and call it from the appended code.
const code = scripts.join('\n;\n') +
  '\n;\n__capture__("PROPS", typeof PROPS !== "undefined" ? PROPS : undefined);' +
  '\n__capture__("detailHTML", typeof detailHTML !== "undefined" ? detailHTML : undefined);\n';

// A single self-referential Proxy that is callable, constructable, and returns itself
// for any property access - absorbs ALL top-level DOM / Leaflet side effects without
// throwing, so every top-level const/function initialises. detailHTML itself touches
// no DOM, so it runs correctly afterwards.
const sink = new Proxy(function () {}, {
  get: (_t, p) => (p === Symbol.toPrimitive || p === 'toString' || p === 'valueOf') ? () => '' : sink,
  apply: () => sink, construct: () => sink, has: () => true,
});
// Seed the target with the REAL JS intrinsics (Object, Array, String, JSON, Math, ...)
// from the host realm first. Without this, the has-trap-always-true below (needed so that
// genuinely-undefined browser globals like `document`/`window`/`L`/`fetch` resolve to the
// sink instead of throwing ReferenceError) ALSO shadows real built-ins - since none of them
// are own properties of a bare `{ console }` object, `Object.keys(...)`, `String(...)`, etc.
// inside the template's top-level code would silently resolve to the sink and corrupt every
// computed value (e.g. FIELD_PRESENT ends up permanently empty, template literals collapse
// to '' via the sink's toString stub) without ever throwing.
const target = { console };
for (const name of Object.getOwnPropertyNames(globalThis)) {
  if (!(name in target)) { try { target[name] = globalThis[name]; } catch { /* ignore */ } }
}
// point the sandbox's `globalThis` at the sandbox itself (NOT the live host global copied
// above), so any vm code writing through `globalThis.x` mutates the sandbox, never the real
// host test-runner process (harness self-containment; e.g. a UMD bundle doing globalThis.foo=).
target.globalThis = target;
target.__capture__ = (name, val) => { target[name] = val; };
const ctx = vm.createContext(new Proxy(target, {
  get: (t, p) => (p in t ? t[p] : sink),
  has: () => true,   // make every free identifier resolve (to sink) instead of ReferenceError
}));

try { vm.runInContext(code, ctx, { filename: 'built.inline.js' }); }
catch (e) { console.error('FAIL: template script threw during eval:', e && e.message); process.exit(1); }

const props = target.PROPS;
const detailHTML = target.detailHTML;
if (typeof detailHTML !== 'function' || !Array.isArray(props)) {
  console.error('FAIL: detailHTML / PROPS not defined by the built script'); process.exit(1);
}
const byId = id => props.find(p => p.id === id);
const rich = detailHTML(byId(1));
const thin = detailHTML(byId(2));
const specCount = h => (h.match(/<div class="spec">/g) || []).length;

const fails = [];
const must = (ok, label) => { if (!ok) fails.push(label); };

// Bug 1 - a field name that exists NOWHERE in the schema/template renders with an auto-label
must(rich.includes('Soil Contamination Risk'), 'invented field auto-labelled ("Soil Contamination Risk")');
must(rich.includes('Low (Phase I clear)'), 'invented field VALUE rendered');
must(rich.includes('Commune') && rich.includes('Zoning Type'), 'other unknown scalars rendered (Commune / Zoning Type)');
must(rich.includes('Additional Details'), 'catch-all section header present on the rich property');
// v22 Phase 1: nested objects are NEVER flattened (supersedes the v21 "flatten one level"
// behaviour asserted here through v21) - a nested scalar like distances.publicTransport
// must NOT surface via the catch-all any more.
must(!rich.includes('Public Transport') && !rich.includes('Bus 612, 400 m'),
  'nested distances object is never flattened (Public Transport not surfaced)');
// v22 Phase 1: objects are never flattened; locator strings never shown; real scalars still show.
must(!rich.includes('page 1 (text interpretation)') && !rich.includes('page 2 (verbatim)'),
  'no provenance-locator string shown on the card (prov object not flattened, someRef skipped)');
must(rich.includes('Commune'), 'genuine new scalar attribute (Commune) still auto-shows');

// Bug 2 - the thin property shows NO row and NO placeholder for fields it lacks
must(!thin.includes('Soil Contamination Risk'), 'thin property has NO row for the invented field');
must(!thin.includes('Additional Details'), 'thin property has NO Additional Details section');
must(!rich.includes('>TBC<') && !thin.includes('>TBC<'), 'no "TBC" placeholder text anywhere');
must(!rich.toLowerCase().includes('val_tbc') && !thin.toLowerCase().includes('val_tbc'), 'no val_tbc key leaked');

// differing spec-row counts, each matching its OWN data
must(specCount(rich) > specCount(thin), `rich has more spec rows than thin (${specCount(rich)} vs ${specCount(thin)})`);
must(specCount(rich) !== specCount(thin), 'the two properties render different spec-row counts');

if (fails.length) {
  console.error('MODAL RENDER TEST: FAIL');
  for (const f of fails) console.error('  - ' + f);
  process.exit(1);
}
console.log(`MODAL RENDER TEST: PASS (rich=${specCount(rich)} rows, thin=${specCount(thin)} rows)`);
process.exit(0);
