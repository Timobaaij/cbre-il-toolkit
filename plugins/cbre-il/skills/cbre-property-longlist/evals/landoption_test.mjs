// landoption_test.mjs - v31. A LAND/plot option (plotArea + landPrice, no warehouseArea) must be
// VISIBLE AT REST and must remain reachable at every slider position the broker can actually set.
//
// The defect this locks SHIPPED a client dashboard whose KPI strip said 37 options while the grid,
// the count and the map rendered 36. v26 guarded the size filter against a 'tbd' with `f.size > 0`,
// correct while the slider started at 0. v13 then made the bounds DATA-DRIVEN: initSizeSlider sets
// `el.min = lo` AND `state.filters.size = lo`, where lo is the floor of the smallest REAL area. So
// on a corpus whose smallest warehouse is 35,773 sq m the default f.size is 35,000 - already > 0 -
// and every area-less option vanished on first load. Worse, el.min === lo means the slider cannot
// be dragged below it, so the card was unreachable by ANY interaction: not filtered, erased.
//
// This eval executes the TEMPLATE'S OWN predicate branch (extracted by regex, never restated) so it
// fails if the comparison ever reverts to a literal. Driven by landoption_test.py.
import fs from "node:fs";

const src = fs.readFileSync(process.argv[2], "utf8");
const fails = [];
const ck = (ok, label) => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) fails.push(label); };

const NUMOK_SRC = /const NUMOK = [^;]+;/.exec(src);
if (!NUMOK_SRC) { console.log("  [FAIL] could not locate NUMOK in the template"); process.exit(1); }
const { NUMOK } = new Function(`${NUMOK_SRC[0]}\nreturn {NUMOK};`)();

// the size-filter line, lifted verbatim from filterList
const LINE = /if\(!NUMOK\(p\.warehouseArea\) \? ([\s\S]*?) : p\.warehouseArea < f\.size\) return false;/.exec(src);
if (!LINE) { console.log("  [FAIL] could not locate the size-filter line in filterList"); process.exit(1); }
const unknownBranch = LINE[1].trim();
console.log(`  size filter, unknown-area branch as written in the template: \`${unknownBranch}\``);

ck(!/^f\.size > 0$/.test(unknownBranch),
   "the unknown-area branch is NOT compared against a literal 0 (that hid land options at rest)");
ck(/SIZE_MIN/.test(unknownBranch),
   "the unknown-area branch compares f.size against SIZE_MIN, the slider's own data-driven floor");

// SIZE_MIN really is the slider's floor AND its resting value - the reason a literal 0 was wrong
ck(/el\.min = lo;/.test(src) && /SIZE_MIN = lo;/.test(src) && /state\.filters\.size = lo;/.test(src),
   "initSizeSlider still sets el.min, SIZE_MIN and the resting f.size all to lo (so f.size > 0 at rest)");

// execute the template's own branch
const keep = new Function("NUMOK", "p", "f", "SIZE_MIN",
  `return !(!NUMOK(p.warehouseArea) ? ${unknownBranch} : p.warehouseArea < f.size);`);

// a Spanish longlist: one land/plot option among real warehouses. Areas mirror the live run.
const LAND = { id: 3, park: "Tarragona Chemical Cluster", plotArea: 115487, landPrice: "120 EUR/sqm" };
const P = [
  LAND,
  { id: 5, park: "Nave Logistica", warehouseArea: 35773 },
  { id: 30, park: "Santa Margarida", warehouseArea: 38476 },
  { id: 28, park: "Magna Park Tauro", warehouseArea: 176444 },
];
const SIZE_MIN = 35000;   // what initSizeSlider derives from the areas above

const atRest = P.filter(p => keep(NUMOK, p, { size: SIZE_MIN }, SIZE_MIN));
ck(atRest.length === P.length,
   `every option is shown AT REST, land option included (${atRest.length}/${P.length} - was ${P.length - 1}/${P.length})`);
ck(atRest.some(p => p.id === LAND.id),
   "the land/plot option specifically survives the resting filter");

const raised = P.filter(p => keep(NUMOK, p, { size: 100000 }, SIZE_MIN));
ck(!raised.some(p => p.id === LAND.id),
   "once the broker RAISES the slider, the area-less option drops out - v26's intent is preserved");
ck(raised.length === 1 && raised[0].id === 28,
   `a raised floor still filters real areas correctly (${raised.length} shown at 100,000)`);

// a corpus with no numeric area at all: SIZE_MIN is 0 and nothing may be hidden
const noneNumeric = [LAND].filter(p => keep(NUMOK, p, { size: 0 }, 0));
ck(noneNumeric.length === 1,
   "on an all-unknown corpus (SIZE_MIN 0) the option is still shown");

console.log(`\n${fails.length ? "FAIL" : "OK"} landoption_test: ${fails.length} failure(s)`);
process.exit(fails.length ? 1 : 0);
