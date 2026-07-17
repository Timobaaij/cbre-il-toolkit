// evals/format_test.mjs - prove pipeline-derived numbers render per the build's LOCALE.
// Usage: node format_test.mjs <en_html> <de_html>
import fs from 'node:fs';
import vm from 'node:vm';

function loadDetail(htmlPath){
  const html = fs.readFileSync(htmlPath, 'utf8');
  const code = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m=>m[1]).join('\n;\n')
    + '\n;\n__capture__("PROPS", typeof PROPS!=="undefined"?PROPS:undefined);'
    + '\n__capture__("detailHTML", typeof detailHTML!=="undefined"?detailHTML:undefined);\n';
  const sink = new Proxy(function(){}, {
    get:(_t,p)=>(p===Symbol.toPrimitive||p==='toString'||p==='valueOf')?()=>'':sink,
    apply:()=>sink, construct:()=>sink, has:()=>true });
  const target = { console };
  for(const n of Object.getOwnPropertyNames(globalThis)) if(!(n in target)){ try{ target[n]=globalThis[n]; }catch{} }
  target.globalThis = target;
  target.__capture__ = (n,v)=>{ target[n]=v; };
  const ctx = vm.createContext(new Proxy(target, { get:(t,p)=>(p in t?t[p]:sink), has:()=>true }));
  try { vm.runInContext(code, ctx, { filename:'built.inline.js' }); }
  catch (e) { console.error(`FORMAT TEST: FAIL - template script threw during eval (${htmlPath}):`, e && e.message); process.exit(1); }
  if (typeof target.detailHTML !== 'function' || !Array.isArray(target.PROPS)) {
    console.error(`FORMAT TEST: FAIL - detailHTML / PROPS not defined by the built script (${htmlPath})`); process.exit(1);
  }
  return { detailHTML: target.detailHTML, byId: id => target.PROPS.find(p=>p.id===id) };
}

const en = loadDetail(process.argv[2]);
const de = loadDetail(process.argv[3]);
const enRich = en.detailHTML(en.byId(1));
const deRich = de.detailHTML(de.byId(1));

const fails = [];
const must = (ok,l)=>{ if(!ok) fails.push(l); };
// warehouseRentVal 60 -> monthly 60/12 = 5.00 ; en decimal '.', de decimal ','
must(enRich.includes('5.00'), "en build: derived monthly rate uses '.' decimal (5.00)");
must(deRich.includes('5,00'), "de build: derived monthly rate uses ',' decimal (5,00)");
must(!deRich.includes('5.00 / '), "de build: derived monthly rate is NOT '.'-formatted");
// source rent STRING is verbatim + identical across locales (never reformatted)
must(enRich.includes('60 EUR / sq m / year') && deRich.includes('60 EUR / sq m / year'),
  "source rent string is byte-verbatim in both locales");

if(fails.length){ console.error('FORMAT TEST: FAIL'); for(const f of fails) console.error('  - '+f); process.exit(1); }
console.log('FORMAT TEST: PASS'); process.exit(0);
