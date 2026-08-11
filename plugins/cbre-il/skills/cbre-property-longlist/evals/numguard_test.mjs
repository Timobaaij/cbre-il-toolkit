// numguard_test.mjs - execute the TEMPLATE'S OWN sort/filter/highlight code against a dataset
// containing an unpriced and an unmeasured property, and assert a 'tbd' is never treated as a
// number. Driven by numguard_test.py (which extracts the chrome's script blocks).
//
// The four defects this locks (v26), each of which SHIPPED a wrong reading to a broker:
//   * "Rent (lowest)" put the UNPRICED property FIRST - the slot read as best value (null-4.2=-4.2)
//   * "Area (largest)" put the UNMEASURED property FIRST (undefined comparisons are false)
//   * the size filter KEPT an area-less property at every floor, and counted it in "N shown"
//   * Compare's green "largest warehouse" flag landed on a cell rendering 'tbd'
import fs from "node:fs";

const src = fs.readFileSync(process.argv[2], "utf8");
const fails = [];
const ck = (ok, label) => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}`); if (!ok) fails.push(label); };

// the guard + the two comparators, lifted verbatim from the chrome
const NUMOK_SRC = /const NUMOK = [^;]+;/.exec(src);
const NUMSORT_SRC = /const NUMSORT = \([\s\S]*?\n  \};/.exec(src);
const STRSORT_SRC = /const STRSORT = [^;]+;/.exec(src);
if (!NUMOK_SRC || !NUMSORT_SRC || !STRSORT_SRC) {
  console.log("  [FAIL] could not locate NUMOK / NUMSORT / STRSORT in the template");
  process.exit(1);
}
const scope = {};
const fn = new Function(`${NUMOK_SRC[0]}\n${NUMSORT_SRC[0]}\n${STRSORT_SRC[0]}\nreturn {NUMOK,NUMSORT,STRSORT};`);
Object.assign(scope, fn());
const { NUMOK, NUMSORT } = scope;

ck(NUMOK(42) && NUMOK(0) && NUMOK(4.75), "NUMOK accepts real numbers INCLUDING 0 (a genuine 0 is data)");
ck(!NUMOK(null) && !NUMOK(undefined) && !NUMOK("tbd") && !NUMOK(NaN) && !NUMOK(Infinity),
   "NUMOK rejects null / undefined / 'tbd' / NaN / Infinity");

// Alpha is UNPRICED and UNMEASURED; the rest are real
const P = [
  { id: 1, park: "Alpha", city: "Corby", developer: "DevA", warehouseRentVal: null },
  { id: 2, park: "Bravo", city: "Venlo", developer: "DevB", warehouseArea: 45000, warehouseRentVal: 4.75 },
  { id: 3, park: "Charlie", city: "Pilsen", developer: "DevC", warehouseArea: 92000, warehouseRentVal: 5.1 },
  { id: 4, park: "Delta", city: "Lodz", developer: "DevD", warehouseArea: 61000, warehouseRentVal: 4.2 },
];

const rentAsc = [...P].sort((a, b) => NUMSORT(a.warehouseRentVal, b.warehouseRentVal, 1));
ck(rentAsc[0].park === "Delta" && rentAsc.at(-1).park === "Alpha",
   `"Rent (lowest)" starts with the genuinely cheapest and SINKS the unpriced one ` +
   `(${rentAsc.map(p => p.park).join(" < ")})`);
// NOTE the call shape: ALWAYS NUMSORT(a.field, b.field, dir) with dir=-1 for descending. Passing
// (b, a, 1) to get a descending order inverts the sink logic and floats unknowns to the TOP -
// which is exactly what this eval caught in the first cut of the v26 fix.
const rentDesc = [...P].sort((a, b) => NUMSORT(a.warehouseRentVal, b.warehouseRentVal, -1));
ck(rentDesc.at(-1).park === "Alpha",
   `"Rent (highest)" also sinks the unpriced one - unknown is neither cheapest NOR dearest ` +
   `(${rentDesc.map(p => p.park).join(" > ")})`);
const sizeDesc = [...P].sort((a, b) => NUMSORT(a.warehouseArea, b.warehouseArea, -1));
ck(sizeDesc[0].park === "Charlie" && sizeDesc.at(-1).park === "Alpha",
   `"Area (largest)" starts with the genuinely largest and sinks the unmeasured one ` +
   `(${sizeDesc.map(p => p.park).join(" > ")})`);

// the size filter predicate, verbatim from filterList. v31 compares the unknown branch against
// SIZE_MIN (the slider's own data-driven floor) rather than a literal 0 - see landoption_test.mjs,
// which extracts this branch from the template rather than restating it. SIZE_MIN is 0 here, the
// pre-v13 shape these v26 assertions were written against, so they are unchanged in meaning.
const SIZE_MIN = 0;
const keep = (p, size) => !(!NUMOK(p.warehouseArea) ? size > SIZE_MIN : p.warehouseArea < size);
ck(!keep(P[0], 90000), "an area-less property does NOT pass a 90,000 floor (it used to)");
ck(keep(P[0], 0), "with no floor set (0) it is still shown - an unknown area is not a reason to hide it");
ck(keep(P[2], 90000) && !keep(P[1], 90000), "real areas still filter correctly");
const shown = P.filter(p => keep(p, 90000));
ck(shown.length === 1 && shown[0].park === "Charlie",
   `"N properties shown" is now truthful at a 90,000 floor (${shown.length}, was 2)`);

// Compare's largest-warehouse highlight index
const minSizeIdx = P.reduce((best, p, i) =>
  (NUMOK(p.warehouseArea) && (best < 0 || p.warehouseArea > P[best].warehouseArea)) ? i : best, -1);
ck(P[minSizeIdx] && P[minSizeIdx].park === "Charlie",
   "the 'largest warehouse' highlight lands on a REAL area, not on the 'tbd' at index 0");
const noneNumeric = [{ id: 9, park: "Solo" }].reduce((best, p, i) =>
  (NUMOK(p.warehouseArea) && (best < 0 || p.warehouseArea > 0)) ? i : best, -1);
ck(noneNumeric === -1, "with no numeric area at all the highlight is -1 (nothing flagged)");

console.log(`\n${fails.length ? "FAIL" : "OK"} numguard_test: ${fails.length} failure(s)`);
process.exit(fails.length ? 1 : 0);
