#!/usr/bin/env python3
"""Stage 4 (optional precision upgrade): build a self-contained geocode.html.

The Cowork sandbox has no internet, so street-level geocoding cannot happen in
the pipeline. This generates a single HTML file with the run's addresses baked
in. The USER opens it in their own browser (which does have internet); it
geocodes each address against the public OpenStreetMap Nominatim service,
client-side, throttled to one request per second per Nominatim's usage policy,
and lets the user download coordinates.json. That file goes back to the
pipeline via:  geocode.py --merge-coords coordinates.json

No coordinate is ever produced by a model: addresses that do not resolve are
written back as precision "tbd".

Usage:
  python make_geocoder_html.py --in records.json --out geocode.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import TBD, load_records  # noqa: E402

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warehouse geocoder</title>
<style>
  :root { --green:#003f2d; --mint:#cfe5db; --accent:#17e88f; --ink:#1a1a1a; }
  * { box-sizing:border-box; }
  body { font-family:Calibre,Arial,Helvetica,sans-serif; margin:0; color:var(--ink); }
  header { background:var(--green); color:#fff; padding:18px 24px; }
  header h1 { margin:0; font-size:20px; font-weight:600; }
  header p { margin:6px 0 0; opacity:.85; font-size:13px; }
  main { padding:20px 24px 60px; max-width:1100px; }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:14px 0; }
  button { background:var(--green); color:#fff; border:0; padding:10px 16px;
           border-radius:6px; font-size:14px; cursor:pointer; }
  button:disabled { opacity:.45; cursor:default; }
  button.secondary { background:#fff; color:var(--green); border:1px solid var(--green); }
  input[type=email] { padding:9px 10px; border:1px solid #bbb; border-radius:6px;
                      font-size:14px; min-width:240px; }
  .progress { height:10px; background:var(--mint); border-radius:6px; overflow:hidden;
              flex:1; min-width:200px; }
  .progress > div { height:100%; width:0; background:var(--accent); transition:width .2s; }
  table { border-collapse:collapse; width:100%; font-size:13px; margin-top:10px; }
  th,td { text-align:left; padding:6px 8px; border-bottom:1px solid #eee; vertical-align:top; }
  th { background:var(--mint); color:var(--green); position:sticky; top:0; }
  .pill { font-size:11px; padding:2px 8px; border-radius:10px; color:#fff; }
  .rooftop { background:#1b8a5a; } .street { background:#6b8f3a; }
  .city { background:#b07d2b; } .tbd { background:#9aa0a6; } .pending { background:#c4c9ce; }
  .note { font-size:12px; color:#555; line-height:1.5; }
  code { background:#f3f3f3; padding:1px 4px; border-radius:3px; }
</style>
</head>
<body>
<header>
  <h1>Warehouse network geocoder</h1>
  <p>Runs in your browser, which has internet. The Cowork sandbox does not, so this
     is how street-level coordinates are produced without a model ever guessing one.</p>
</header>
<main>
  <p class="note">
    <b>How to use:</b> (optional) enter your email so Nominatim can contact you about
    usage, then click <b>Geocode all</b>. It runs one address per second, so a large
    network takes a few minutes; leave the tab open. When it finishes, click
    <b>Download coordinates.json</b> and hand that file back. Addresses that do not
    resolve are saved as <code>tbd</code>, never guessed. Results are cached in this
    browser, so you can stop and resume.
  </p>
  <div class="bar">
    <input type="email" id="email" placeholder="you@company.com (optional, recommended)">
    <button id="run">Geocode all</button>
    <button id="dl" class="secondary" disabled>Download coordinates.json</button>
    <button id="clear" class="secondary">Clear cache</button>
  </div>
  <div class="bar">
    <div class="progress"><div id="pfill"></div></div>
    <span id="pcount" class="note">0 / 0</span>
  </div>
  <table>
    <thead><tr><th>#</th><th>Address</th><th>Lat</th><th>Long</th><th>Precision</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main>
<script>
const ADDRESSES = /*__ADDRESSES__*/;
const ENDPOINT = "https://nominatim.openstreetmap.org/search";
const CITYISH = new Set(["city","town","village","hamlet","state","country","postcode",
  "suburb","municipality","administrative","county","region","province"]);
const results = new Array(ADDRESSES.length).fill(null);

function cacheKey(a){ return "wh-geo:" + a.address.toLowerCase(); }
function classify(hit){
  const cls = hit.class || "", typ = hit.type || "", at = hit.addresstype || "";
  if (CITYISH.has(at) || CITYISH.has(typ)) return "city";
  if ((hit.address && hit.address.house_number) ||
      ["building","amenity","shop","office","industrial"].includes(cls) ||
      ["warehouse","industrial","house","commercial"].includes(typ)) return "rooftop";
  return "street";
}
function pill(p){ return `<span class="pill ${p}">${p}</span>`; }

function renderRow(i){
  const a = ADDRESSES[i], r = results[i];
  const tr = document.getElementById("row-"+i);
  const lat = r && r.lat!=null ? r.lat.toFixed(5) : "";
  const lon = r && r.long!=null ? r.long.toFixed(5) : "";
  const prec = r ? r.precision : "pending";
  tr.innerHTML = `<td>${a.i}</td><td>${a.address}</td><td>${lat}</td>`+
                 `<td>${lon}</td><td>${pill(prec)}</td>`;
}
function build(){
  const tb = document.getElementById("rows");
  ADDRESSES.forEach((a,i)=>{
    const tr = document.createElement("tr"); tr.id = "row-"+i; tb.appendChild(tr);
    const cached = localStorage.getItem(cacheKey(a));
    if (cached) results[i] = JSON.parse(cached);
    renderRow(i);
  });
  document.getElementById("pcount").textContent =
    `${results.filter(Boolean).length} / ${ADDRESSES.length}`;
  if (ADDRESSES.length && results.every(Boolean)) document.getElementById("dl").disabled = false;
}
async function geocodeOne(a, email){
  const params = new URLSearchParams({q:a.address, format:"jsonv2", limit:"1",
    addressdetails:"1"});
  if (email) params.set("email", email);
  try {
    const resp = await fetch(`${ENDPOINT}?${params}`, {headers:{"Accept":"application/json"}});
    if (!resp.ok) throw new Error("HTTP "+resp.status);
    const data = await resp.json();
    if (!data.length) return {i:a.i, address:a.address, lat:null, long:null, precision:"tbd"};
    const h = data[0];
    return {i:a.i, address:a.address, lat:+(+h.lat).toFixed(6),
            long:+(+h.lon).toFixed(6), precision:classify(h)};
  } catch(e){
    return {i:a.i, address:a.address, lat:null, long:null, precision:"tbd", error:String(e)};
  }
}
const sleep = ms => new Promise(r=>setTimeout(r,ms));
async function runAll(){
  const run = document.getElementById("run"); run.disabled = true;
  const email = document.getElementById("email").value.trim();
  const fill = document.getElementById("pfill");
  for (let i=0;i<ADDRESSES.length;i++){
    if (!results[i]){
      results[i] = await geocodeOne(ADDRESSES[i], email);
      localStorage.setItem(cacheKey(ADDRESSES[i]), JSON.stringify(results[i]));
      renderRow(i);
      await sleep(1100); // Nominatim: max 1 request/second
    }
    const done = results.filter(Boolean).length;
    fill.style.width = (100*done/ADDRESSES.length)+"%";
    document.getElementById("pcount").textContent = `${done} / ${ADDRESSES.length}`;
  }
  document.getElementById("dl").disabled = false;
  run.disabled = false;
}
function download(){
  const payload = {generated_by:"geocode.html", count:results.length,
                   coordinates: results.map(r=>({i:r.i, address:r.address,
                     lat:r.lat, long:r.long, precision:r.precision}))};
  const blob = new Blob([JSON.stringify(payload,null,2)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "coordinates.json"; a.click();
}
document.getElementById("run").addEventListener("click", runAll);
document.getElementById("dl").addEventListener("click", download);
document.getElementById("clear").addEventListener("click", ()=>{
  ADDRESSES.forEach(a=>localStorage.removeItem(cacheKey(a)));
  results.fill(null); document.getElementById("rows").innerHTML=""; build();
  document.getElementById("dl").disabled = true;
  document.getElementById("pfill").style.width="0";
});
build();
</script>
</body>
</html>
"""


def run(args: argparse.Namespace) -> int:
    records = load_records(args.infile)
    addresses = []
    for i, rec in enumerate(records):
        addr = str(rec.get("full_address") or "").strip()
        if addr and addr.lower() != TBD:
            addresses.append({"i": i, "address": addr,
                              "country": rec.get("country", ""),
                              "city": rec.get("city", "")})
    html = _TEMPLATE.replace("/*__ADDRESSES__*/",
                             json.dumps(addresses, ensure_ascii=False))
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} with {len(addresses)} address(es) to geocode "
          f"(of {len(records)} records).")
    print("Hand geocode.html to the user; they open it in a browser, click "
          "'Geocode all', and return coordinates.json.")
    if len(addresses) < len(records):
        print(f"  {len(records) - len(addresses)} record(s) have no address; "
              "they stay on the city-centroid baseline or tbd.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a browser geocoder HTML.")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", default="geocode.html")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
