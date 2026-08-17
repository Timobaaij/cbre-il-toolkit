/* v36 Certification - executes the REAL certName/certStr extracted from the built template,
   so this pins behaviour rather than a restatement of it. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const tpl = readFileSync(join(ROOT, "assets", "dashboard_template.html"), "utf8");

function grab(name) {
  const start = tpl.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in template`);
  let i = tpl.indexOf("{", start), depth = 0;
  for (; i < tpl.length; i++) {
    const c = tpl[i];
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) { i++; break; } }
  }
  return tpl.slice(start, i);
}

const ctx = vm.createContext({});
vm.runInContext(grab("certName") + "\n" + grab("certStr"), ctx);
const certStr = (p) => vm.runInContext("certStr", ctx)(p);

let fails = 0;
function eq(actual, expected, label) {
  const ok = actual === expected;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${label} -> ${JSON.stringify(actual)}`);
  if (!ok) { console.log(`         expected ${JSON.stringify(expected)}`); fails++; }
}

console.log("  node: certStr behaviour");
eq(certStr({ breeam: "Excellent", epc: "A+" }), "BREEAM Excellent, EPC A+",
   "both present, names prefixed");
eq(certStr({ breeam: "Excellent" }), "BREEAM Excellent", "breeam only");
eq(certStr({ epc: "A+" }), "EPC A+", "epc only");
eq(certStr({}), "", "neither present yields empty, so the row is omitted");
eq(certStr({ breeam: "tbd", epc: "tbd" }), "", "tbd sentinels are absent, never rendered");
eq(certStr({ breeam: "tbd", epc: "A" }), "EPC A", "a tbd half does not leave a stray comma");
eq(certStr({ breeam: "Targeting BREEAM 'Outstanding'", epc: "Targeting EPC A" }),
   "Targeting BREEAM 'Outstanding', Targeting EPC A",
   "a value already naming its certificate is left untouched");
eq(certStr({ breeam: "Target Excellent", epc: "Target A" }),
   "Target BREEAM Excellent, Target EPC A",
   "a leading Target keeps its place in front of the certificate name");
eq(certStr({ breeam: "Very Good", epc: "B" }), "BREEAM Very Good, EPC B",
   "multi-word grade survives intact");
eq(certStr({ breeam: null, epc: undefined }), "", "null/undefined are absent");
eq(certStr({ breeam: "—", epc: "-" }), "", "dash sentinels are absent");

console.log(fails ? `  node: ${fails} failure(s)` : "  node: all behaviour checks passed");
process.exit(fails ? 1 : 0);
