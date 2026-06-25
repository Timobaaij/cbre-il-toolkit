#!/usr/bin/env python3
"""Stage 4 (optional precision upgrade): build a self-contained geocode.html.

The Cowork sandbox has no internet, so street-level geocoding cannot happen in
the pipeline. This generates a single HTML file with the run's sites baked in.
The USER opens it in their own browser (which does have internet); it geocodes
each site client-side and lets the user download coordinates.json, which goes
back to the pipeline via:  geocode.py --merge-coords coordinates.json

Three things make this resolve far more rows than a single-string lookup:

  * Candidate ladders, most-specific first. Each site gets several queries,
    tried in order: street + postcode + city, then postcode + city, then
    town (+ region) + country as a guaranteed fallback, so every row with a
    known town resolves at least to town level.
  * Diacritics preserved. The native spelling (Moenchengladbach written with
    its umlaut, Gluchow with its accents) is sent because it matches
    OpenStreetMap far better than an ASCII version. The subagents are asked to
    keep native spelling in address_parts.
  * Two providers. When Nominatim misses a query, the same query is retried
    against the Photon geocoder before moving to the next, coarser candidate.

Precision is reported honestly: never better than the matched candidate could
justify (a town-level query never reports "street"), and a site that resolves
nowhere stays "tbd". No coordinate is ever produced by a model.

Usage:
  python make_geocoder_html.py --in records.json --out geocode.html
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import TBD, extract_postcode, load_records  # noqa: E402

_HOUSE_NUM = re.compile(r"\d+\s*[a-zA-Z]?\b")


def _clean(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip().strip(",").strip()


def build_candidates(rec: dict[str, Any]) -> list[dict[str, str]]:
    """Most-specific-first query ladder for one site. Native spelling kept."""
    parts = rec.get("address_parts") or {}
    street = str(parts.get("street") or "").strip()
    # Prefer the native-spelling city from address_parts (with diacritics, which
    # match OpenStreetMap far better) over a possibly ASCII-folded top-level city.
    city = str(parts.get("city") or rec.get("city") or "").strip()
    region = str(parts.get("region") or "").strip()
    country = str(rec.get("country") or "").strip()
    full = str(rec.get("full_address") or "").strip()
    postcode = str(parts.get("postcode")
                   or extract_postcode(full, country) or "").strip()

    cands: list[dict[str, str]] = []

    def add(q: str, prec: str) -> None:
        q = _clean(q)
        if q and all(q.lower() != c["q"].lower() for c in cands):
            cands.append({"q": q, "prec": prec})

    # 1. Street level (rooftop if it carries a house number, else street).
    if street:
        loc = _clean(f"{postcode} {city}")
        add(", ".join(x for x in [street, loc, country] if x),
            "rooftop" if _HOUSE_NUM.search(street) else "street")
    elif full and full.lower() != TBD:
        add(full, "rooftop" if _HOUSE_NUM.search(full) else "street")

    # 2. Postcode + town (locality level).
    if postcode and city:
        add(", ".join(x for x in [f"{postcode} {city}".strip(), country] if x), "city")

    # 3. Town (+ region) + country: the guaranteed fallback.
    if city and region:
        add(", ".join([city, region, country]) if country else f"{city}, {region}", "city")
    if city:
        add(", ".join([city, country]) if country else city, "city")

    return cands


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warehouse network geocoder</title>
<style>
 :root{--green:#003F2D;--mint:#cfe5db;--accent:#17E88F;--ink:#16241f;}
 body{font-family:Calibre,Calibri,Arial,sans-serif;margin:0;padding:0;color:var(--ink);background:#fff}
 header{background:var(--green);color:#fff;padding:18px 24px}
 header h1{margin:0;font-size:20px}
 header p{margin:6px 0 0;opacity:.85;font-size:13px;max-width:980px;line-height:1.5}
 main{padding:18px 24px 60px}
 .bar{margin:14px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 button{background:var(--green);color:#fff;border:0;border-radius:6px;padding:10px 16px;font-size:14px;cursor:pointer}
 button:disabled{background:#9bb3aa;cursor:default}
 button.alt{background:var(--accent);color:var(--green);font-weight:600}
 input[type=email]{padding:9px 10px;border:1px solid #bbb;border-radius:6px;font-size:14px;min-width:230px}
 #prog{font-size:13px;color:#333}
 table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:8px}
 th,td{border:1px solid #e2e2e2;padding:6px 8px;text-align:left;vertical-align:top}
 th{background:var(--green);color:#fff;position:sticky;top:0}
 tr:nth-child(even){background:#f4f7f6}
 code{background:#eef3f1;padding:1px 4px;border-radius:3px}
 .src{font-size:11px;color:#777}
 .pill{font-size:11px;padding:2px 8px;border-radius:10px;color:#fff}
 .rooftop{background:#1b8a5a}.street{background:#6b8f3a}.city{background:#b8860b}
 .tbd{background:#c0392b}.pending{background:#9aa0a6}
</style></head><body>
<header>
 <h1>Warehouse network geocoder</h1>
 <p>Runs in your browser, which has internet (the Cowork sandbox does not, so this is how
 street-level coordinates are produced without a model ever guessing one). Each site is tried
 most-specific first (street, then postcode + town, then town + country), via OpenStreetMap
 Nominatim with Photon as a fallback when Nominatim misses. Throttled to about one request per
 second per Nominatim policy. Optionally enter your email so Nominatim can reach you about usage.
 When it finishes, click <b>Download coordinates.json</b> and hand the file back. Results cache in
 this browser, so you can stop and resume.</p>
</header>
<main>
 <div class="bar">
  <input type="email" id="email" placeholder="you@company.com (optional, recommended)">
  <button id="run">Geocode all</button>
  <button id="retry" class="alt" disabled>Retry failed only</button>
  <button id="dl" disabled>Download coordinates.json</button>
  <button id="clear">Clear cache</button>
  <span id="prog">Idle.</span>
 </div>
 <table id="tbl"><thead><tr><th>#</th><th>Site / town</th><th>Status</th><th>Precision</th>
  <th>Lat</th><th>Long</th><th>Matched query</th></tr></thead><tbody></tbody></table>
</main>
<script>
const DATA = /*__DATA__*/;
const ORD = {tbd:0, city:1, street:2, rooftop:3};
const results = {};
const tbody = document.querySelector('#tbl tbody');
const rowsEl = {};

function ck(d){ return "whg:"+d.i+":"+d.candidates.map(c=>c.q).join("|"); }
function pill(p){ return `<span class="pill ${p||'pending'}">${p||'pending'}</span>`; }
function setRow(i,st,cls,prec,lat,lon,q){
 const tr=rowsEl[i];
 const s=tr.querySelector('[data-st]'); s.textContent=st; s.className=cls;
 tr.querySelector('[data-pr]').innerHTML=pill(prec);
 tr.querySelector('[data-lat]').textContent=lat!=null?(+lat).toFixed(6):'';
 tr.querySelector('[data-lon]').textContent=lon!=null?(+lon).toFixed(6):'';
 tr.querySelector('[data-q]').innerHTML=q?`<code>${q}</code>`:'';
}
DATA.forEach(d=>{
 const tr=document.createElement('tr');
 tr.innerHTML=`<td>${d.i}</td><td><b>${d.label}</b><div class="src">${d.site||''}</div></td>`+
   `<td data-st class="pending">pending</td><td data-pr></td><td data-lat></td>`+
   `<td data-lon></td><td data-q></td>`;
 tbody.appendChild(tr); rowsEl[d.i]=tr;
 const cached=localStorage.getItem(ck(d));
 if(cached){ const r=JSON.parse(cached);
   if(r&&r.lat!=null){ results[d.i]=r; setRow(d.i,'cached',r.precision,r.precision,r.lat,r.long,r.matched||''); }
 }
});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function nominatim(q,email){
 let u='https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&addressdetails=1&q='+encodeURIComponent(q);
 if(email) u+='&email='+encodeURIComponent(email);
 const r=await fetch(u,{headers:{'Accept':'application/json'}}); if(!r.ok) return null;
 const j=await r.json(); if(!j.length) return null;
 const it=j[0]; let prec='city';
 const at=(it.addresstype||it.type||'').toLowerCase(), cls=(it.class||'').toLowerCase();
 if(it.address&&it.address.house_number) prec='rooftop';
 else if(['building','industrial','commercial','warehouse','retail','house'].includes(at)||cls==='building') prec='rooftop';
 else if(['road','residential','pedestrian'].includes(at)||cls==='highway') prec='street';
 return {lat:+it.lat,lon:+it.lon,prec,src:'nominatim'};
}
async function photon(q){
 const u='https://photon.komoot.io/api/?limit=1&q='+encodeURIComponent(q);
 const r=await fetch(u); if(!r.ok) return null;
 const j=await r.json(); if(!j.features||!j.features.length) return null;
 const f=j.features[0], c=f.geometry.coordinates, p=f.properties||{};
 let prec='city';
 if(p.housenumber) prec='rooftop'; else if(p.street) prec='street';
 return {lat:c[1],lon:c[0],prec,src:'photon'};
}
async function geocodeOne(d,email){
 for(const cand of d.candidates){
   let res=null;
   try{ res=await nominatim(cand.q,email); }catch(e){}
   await sleep(1100);
   if(!res){ try{ res=await photon(cand.q); }catch(e){} await sleep(500); }
   if(res){
     // honest precision: never better than the candidate could justify
     const prec = ORD[res.prec] <= ORD[cand.prec] ? res.prec : cand.prec;
     const out={i:d.i,lat:res.lat,long:res.lon,precision:prec,matched:cand.q,src:res.src};
     results[d.i]=out; localStorage.setItem(ck(d),JSON.stringify(out));
     setRow(d.i,'ok ('+res.src+')',prec,prec,res.lat,res.lon,cand.q);
     return true;
   }
 }
 setRow(d.i,'FAILED','tbd','tbd',null,null,d.candidates[0]?d.candidates[0].q:'');
 return false;
}
async function runList(list,email){
 document.getElementById('run').disabled=true; document.getElementById('retry').disabled=true;
 let done=0, fails=0;
 for(const d of list){
   if(results[d.i]){ done++; continue; }
   const ok=await geocodeOne(d,email); done++; if(!ok)fails++;
   document.getElementById('prog').textContent=`Geocoded ${done}/${list.length} (failed ${fails})...`;
 }
 const have=Object.keys(results).length;
 document.getElementById('prog').textContent=`Done: ${have}/${DATA.length} resolved. ${DATA.length-have} unresolved.`;
 document.getElementById('dl').disabled=have===0;
 document.getElementById('retry').disabled=have===DATA.length;
 document.getElementById('run').disabled=false;
}
document.getElementById('run').onclick=()=>runList(DATA,document.getElementById('email').value.trim());
document.getElementById('retry').onclick=()=>runList(DATA.filter(d=>!results[d.i]),document.getElementById('email').value.trim());
document.getElementById('dl').onclick=()=>{
 const out={generated_by:'geocode.html',count:Object.keys(results).length,
   coordinates:Object.values(results).sort((a,b)=>a.i-b.i)
     .map(r=>({i:r.i,lat:r.lat,long:r.long,precision:r.precision}))};
 const blob=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});
 const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
 a.download='coordinates.json'; a.click();
};
document.getElementById('clear').onclick=()=>{
 DATA.forEach(d=>localStorage.removeItem(ck(d)));
 for(const k in results) delete results[k];
 DATA.forEach(d=>setRow(d.i,'pending','pending','',null,null,''));
 document.getElementById('dl').disabled=true; document.getElementById('retry').disabled=true;
 document.getElementById('prog').textContent='Cache cleared.';
};
const haveInit=Object.keys(results).length;
if(haveInit){ document.getElementById('dl').disabled=false;
 document.getElementById('prog').textContent=`${haveInit}/${DATA.length} restored from cache.`; }
</script></body></html>
"""


def run(args: argparse.Namespace) -> int:
    records = load_records(args.infile)
    data, skipped = [], 0
    for i, rec in enumerate(records):
        cands = build_candidates(rec)
        if not cands:
            skipped += 1
            continue
        city = str(rec.get("city") or "").strip()
        country = str(rec.get("country") or "").strip()
        label = ", ".join(x for x in [city, country] if x) or f"record {i}"
        data.append({"i": i, "label": label,
                     "site": str(rec.get("site_name") or "").strip(),
                     "candidates": cands})
    html = _TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} with {len(data)} site(s) to geocode (of {len(records)} records).")
    print("Hand geocode.html to the user; they open it in a browser, click 'Geocode all', "
          "and return coordinates.json. Merge it back with geocode.py --merge-coords.")
    if skipped:
        print(f"  {skipped} record(s) had no town or address; they stay on the "
              "gazetteer baseline or tbd.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a browser geocoder HTML.")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", default="geocode.html")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
