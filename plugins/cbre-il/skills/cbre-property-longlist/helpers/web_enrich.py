#!/usr/bin/env python3
"""web_enrich.py - the orchestrator-web handoff for POIs and drive times.

THE PROBLEM: the Python helpers run in the Cowork sandbox, where outbound
network is OFTEN dead, so live Overpass (genuine nearest POIs) and OSRM (real
drive times) can be unreachable at build time - and the dashboard's client-side
fallback can ALSO be blocked by the viewer's corporate proxy. A preloaded POI
list is NOT an acceptable substitute: the product's value is the GENUINE nearest
port/airport/rail/border per property, never the nearest of a curated set.

THE SOLUTION: it is ALWAYS the Cowork sandbox; the orchestrator PROBES which
tools are present and uses the FIRST available, in this priority order:
(1) mcp__shell, if present (it is native and HAS outbound network - NOT
Windows-only, it may be present in Cowork): run the enrichment THROUGH it so the
helpers hit the live APIs and bake the caches directly, no page, no browser;
(2) the Playwright MCP, via the data: URL fetcher (browser_navigate to a minimal
data:text/html fetcher whose inline fetch() hits the API - the browser has its
own outbound internet and the APIs send Access-Control-Allow-Origin:*; the
result is read back with browser_evaluate(filename=save_as), which writes it into
the connected folder the sandbox reads); (3) the Claude Preview MCP, serving the
full fetcher PAGE via the launch.json the run writes; (4) the chat handoff - the
broker runs the page in their own browser (the universal fallback, always
available). (WebFetch is NOT the mechanism: it reaches general web PAGES, not the
Nominatim/Overpass/OSRM/ORS API hosts.) This helper

  plan   <canonical> --work <dir> [--pois] [--osrm]
         emits <work>/web_enrich.html (the self-chaining fetcher page) plus
         <work>/web_requests.json - the EXACT HTTP requests the live enrichment
         would have made (one capped Overpass query per property location; one
         OSRM table call per property covering its relevant POIs). The PAGE
         executes those in the browser and downloads a self-describing
         web_seeds.json. (The same list can also be replayed into <work>/
         web_fetched/<save_as> on an ONLINE host whose own tools reach the APIs -
         ingest reads either source.)

  ingest --work <dir>
         converts the fetched responses into the same caches the live path
         writes (poi_osm_cache.json / osrm_cache.json), using the SAME
         classification and nearest-of-type logic as enrich.py - so a
         subsequent offline `enrich --pois --osrm` (or run.py re-run) attaches
         genuine-nearest POIs and real routed drive times with zero sandbox
         network.

ONE round: the fetcher page SELF-CHAINS - it geocodes the unresolved cities,
derives the route targets itself from the embedded POI dataset (same data +
caps as the build), fetches the routes, and returns a single self-describing
seeds bundle (v2). The geocode->routes dependency that used to force a second
round-trip is resolved inside the page. run.py exits 8 whenever fulfilable
requests are pending, so a build can never silently ship without the
enrichment the broker asked for.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich as E

FETCH_DIR = "web_fetched"
REQUESTS_FILE = "web_requests.json"
ARTIFACT_FILE = "web_enrich.html"
SEEDS_FILE = "web_seeds.json"

INSTRUCTIONS = (
    "Enrich the drive-times/POIs. It is ALWAYS the Cowork sandbox; PROBE which tools are "
    "present and use the FIRST available. (1) mcp__shell, if present (native, has outbound "
    "network - NOT Windows-only): just re-run run.py / enrich.py THROUGH it with the same "
    "--geocode/--pois/--osrm args - the helpers hit the live APIs and bake the caches "
    "directly, no page, no browser. (2) the Playwright MCP, via the DATA: URL fetcher: for "
    "each request in web_requests.json (it lists {url, save_as, data_url} per request), "
    "browser_navigate to request['data_url'] (a minimal data:text/html fetcher that fetch()es "
    "the URL into window.__m), browser_wait_for a few seconds (throttle per service, Nominatim "
    "~1 req/s), then browser_evaluate('() => JSON.stringify(window.__m)', filename=save_as) - "
    "the MCP writes the result into the connected folder the sandbox reads; json.loads it "
    "TWICE (the saved content is itself JSON-stringified) and write the raw body to "
    "<work>/web_fetched/<save_as>. NO local HTTP server (sandbox localhost != browser "
    "localhost - different network namespaces; file: is blocked too). (3) the Claude Preview "
    "MCP serving the FULL fetcher PAGE <work>/web_enrich.html via the 'longlist-preview' "
    "launch.json the run writes (preview_start, navigate, click #go, read the seeds object). "
    "(4) UNIVERSAL FALLBACK: DELIVER web_enrich.html TO THE USER IN THE CHAT (org users never "
    "see the work folder); they open it in any browser whose network reaches OSM services "
    "(corporate proxy blocks them? home network or hotspot - the file is portable), click "
    "'Fetch all', then 'Download seeds', and DROP the downloaded web_seeds.json BACK INTO THE "
    "CHAT - save it into the work dir as web_seeds.json. The page self-chains geocode -> route "
    "targets -> routes in a single 'Fetch all' click. (WebFetch is NOT a path - it cannot reach "
    "the Nominatim/Overpass/OSRM/ORS API hosts.) Then run: "
    "python helpers/web_enrich.py ingest --work <work>  and re-run run.py with the same "
    "arguments. This bakes real geocodes and routed drive times into the dashboard.")

_THROTTLE_MS = {"overpass": 2500, "osrm-table": 400, "nominatim": 1100,
                "ors-matrix": 1600}  # ORS free tier: 40 requests/minute


def _artifact_html(requests_out: list[dict], chain: dict | None = None) -> str:
    """A self-contained page the OPERATOR opens in their own browser: ONE 'Fetch
    all' click resolves the WHOLE enrichment - it geocodes the unresolved cities,
    derives the route targets itself from the embedded POI set (same data + caps
    as the build, so results are identical), fetches the routes, and downloads a
    single self-describing web_seeds.json. The geocode->routes dependency that
    used to force a second round-trip is resolved inside the page. Politely
    throttled per service with 429/504 backoff; full-fidelity transport (no
    WebFetch truncation) and the human picks a network that can reach the
    services. Static requests (e.g. the Overpass fallback) ride along."""
    payload = json.dumps(requests_out, ensure_ascii=False)
    chain_js = json.dumps(chain or {}, ensure_ascii=False)
    throttle = json.dumps(_THROTTLE_MS)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>CBRE Longlist - web enrichment fetcher</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;background:#0f1f18;color:#e8e7de;margin:0;padding:32px;max-width:860px}}
 h1{{font-size:20px;color:#7fd1ae}} .sub{{color:#9db5a9;font-size:13px;margin-bottom:18px}}
 button{{background:#17e88f;color:#012a2d;border:0;padding:10px 22px;border-radius:4px;font-weight:600;cursor:pointer;margin-right:10px}}
 button:disabled{{background:#3a5247;color:#7d9388;cursor:default}}
 #bar{{height:8px;background:#1e3329;border-radius:4px;margin:18px 0;overflow:hidden}}
 #fill{{height:100%;width:0;background:#17e88f;transition:width .3s}}
 #log{{font-family:Consolas,monospace;font-size:12px;color:#9db5a9;white-space:pre-wrap;max-height:300px;overflow:auto;background:#0a1812;padding:12px;border-radius:4px}}
</style></head><body>
<h1>Web enrichment fetcher</h1>
<div class="sub">Your dashboard assistant sent you this page. It looks up the nearest ports, airports,
rail terminals and drive times for your property options from YOUR browser (nothing but property
coordinates is sent). <b>1.</b> Click "Fetch all" and wait for the bar to finish. <b>2.</b> Click
"Download seeds". <b>3.</b> Drop the downloaded <b>web_seeds.json</b> back into the chat with the
assistant. If requests fail, your network blocks OpenStreetMap services - reopen this file on
another network (home / hotspot) and try again.</div>
<div class="sub" id="keyrow" style="display:none">Truck (HGV) drive-times need a free <a
 href="https://openrouteservice.org/dev/#/signup" target="_blank" style="color:#7fd1ae">openrouteservice
 key</a>. Paste it here and it is used ONLY from your own browser - it is never uploaded, saved or
 shared. Leave blank for car drive-times.<br><input id="orskey" type="text" autocomplete="off"
 placeholder="openrouteservice key (optional - blank = car times)" style="width:100%;margin-top:6px;padding:7px;border-radius:4px;border:1px solid #3a5247;background:#0a1812;color:#e8e7de"></div>
<button id="go">Fetch all</button><button id="dl" disabled>Download seeds</button>
<div id="bar"><div id="fill"></div></div><div id="log"></div>
<script>
const REQUESTS = {payload};
const CHAIN = {chain_js};
const THROTTLE = {throttle};
const out = {{}};
const seeds = {{v: 2, geocode: [], routes: [], static: out}};
const log = m => {{ const el = document.getElementById('log'); el.textContent += m + "\\n"; el.scrollTop = el.scrollHeight; }};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const hav = (a, b, c, d) => {{ const R = 6371, toR = x => x * Math.PI / 180;
  const dp = toR(c - a), dl = toR(d - b);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(toR(a)) * Math.cos(toR(c)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h))); }};
async function fetchOne(req, attempt) {{
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 90000);
  try {{
    const resp = await fetch(req.url, {{signal: ctl.signal, method: req.method || 'GET',
                                        headers: req.headers || undefined,
                                        body: req.body || undefined}});
    clearTimeout(t);
    if (resp.status === 429 || resp.status === 504) {{
      if (attempt < 3) {{ log(`  ${{req.id}}: HTTP ${{resp.status}} - backing off`); await sleep(8000 * attempt); return fetchOne(req, attempt + 1); }}
    }}
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const body = await resp.text();
    if (body.includes('"remark"') && /runtime error|timed out/i.test(body))
      throw new Error("Overpass server overloaded - retrying");
    return body;
  }} catch (e) {{ clearTimeout(t); if (attempt < 2) {{ await sleep(4000); return fetchOne(req, attempt + 1); }} throw e; }}
}}
let done = 0, failed = 0, total = 1;
const tick = () => {{ done++; document.getElementById('fill').style.width = (100 * Math.min(done, total) / total) + "%"; }};

async function runChain() {{
  const props = CHAIN.properties || [];
  // phase 1: geocode the unresolved cities (the page resolves the dependency
  // that used to force a second round-trip)
  const geocoded = [];  // PASS-B population: phase-1-resolved points only
  for (const p of props.filter(x => x.geocode_url)) {{
    try {{
      const body = await fetchOne({{id: "geocode " + p.geokey, url: p.geocode_url}}, 1);
      seeds.geocode.push({{key: p.geokey, body}});
      const arr = JSON.parse(body);
      if (arr.length) {{
        p.lat = parseFloat(arr[0].lat); p.lng = parseFloat(arr[0].lon);
        p.cc = String(((arr[0].address || {{}}).country_code) || "").toUpperCase();
        geocoded.push(p);
      }}
      log("OK geocode " + p.geokey);
    }} catch (e) {{ failed++; log("FAIL geocode " + p.geokey + ": " + e.message); }}
    tick(); await sleep(THROTTLE.nominatim);
  }}
  // PASS B (mirrors enrich.py geocode PASS B): a bare city is globally ambiguous.
  // Take the dataset-dominant country (mode of well-clustered points) and re-query
  // any UNKNOWN-COUNTRY point that landed >2000 km from the cluster, constrained to
  // that country - so a country="??" "Boston" cannot bake a wrong-continent pin.
  const pts = geocoded.filter(p => typeof p.lat === "number" && typeof p.lng === "number");
  if (pts.length) {{
    const med = a => {{ const s = [...a].sort((x, y) => x - y), n = s.length;
      return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; }};
    const medLat = med(pts.map(p => p.lat)), medLng = med(pts.map(p => p.lng));
    const near = {{}};  // modal cc among points within 1000 km of the centroid
    for (const p of pts) if (p.cc && hav(p.lat, p.lng, medLat, medLng) < 1000)
      near[p.cc] = (near[p.cc] || 0) + 1;
    let dominant = "", bestN = 0;
    for (const k in near) if (near[k] > bestN) {{ bestN = near[k]; dominant = k; }}
    if (dominant) {{
      for (const p of pts) {{
        if (p.known) continue;
        if (hav(p.lat, p.lng, medLat, medLng) <= 2000) continue;
        const u = new URL("https://nominatim.openstreetmap.org/search");
        u.search = new URLSearchParams({{q: p.city, format: "json", limit: "1",
          addressdetails: "1", countrycodes: dominant.toLowerCase()}}).toString();
        try {{
          const body2 = await fetchOne({{id: "geocode(reB) " + p.geokey, url: u.toString()}}, 1);
          const arr2 = JSON.parse(body2);
          if (arr2.length) {{
            // push the CORRECTED body under the SAME geokey - ingest iterates in
            // order so this later entry overwrites the phase-1 one
            seeds.geocode.push({{key: p.geokey, body: body2}});
            p.lat = parseFloat(arr2[0].lat); p.lng = parseFloat(arr2[0].lon);
            log("NOTE geocode " + p.geokey + ": ambiguous worldwide - constrained to "
                + dominant + " (verify the pin)");
          }} else {{
            log("NOTE geocode " + p.geokey + ": far from cluster, no " + dominant
                + " match - left as-is (verify the pin)");
          }}
        }} catch (e) {{ failed++; log("FAIL geocode(reB) " + p.geokey + ": " + e.message); }}
        tick(); await sleep(THROTTLE.nominatim);
      }}
    }}
  }}
  if (!CHAIN.do_routes) return;
  // phase 2: derive the route targets exactly like the build does - nearest of
  // each type per property (embedded POI set + the same distance caps), unioned
  const located = props.filter(p => typeof p.lat === "number");
  const U = new Map();
  for (const p of located) {{
    const best = {{}};
    for (const q of CHAIN.pois) {{
      const km = hav(p.lat, p.lng, q.lat, q.lng);
      if (km > (CHAIN.caps[q.type] || 400)) continue;
      if (!best[q.type] || km < best[q.type].km) best[q.type] = {{type: q.type, lat: q.lat, lng: q.lng, km}};
    }}
    for (const t in best) U.set(best[t].lat + "," + best[t].lng, best[t]);
  }}
  const targets = [...U.values()];
  // phase 3: routes per property (trucking matrix with a key, car OSRM without)
  for (const p of located) {{
    const dests = targets.filter(q => hav(p.lat, p.lng, q.lat, q.lng) <= (CHAIN.caps[q.type] || 800));
    if (!dests.length) {{ tick(); continue; }}
    let req;
    if (CHAIN.ors_key) {{
      req = {{id: "routes #" + p.id, kind: "ors-matrix", url: CHAIN.ors_url, method: "POST",
             headers: {{"Authorization": CHAIN.ors_key, "Content-Type": "application/json"}},
             body: JSON.stringify({{locations: [[p.lng, p.lat]].concat(dests.map(q => [q.lng, q.lat])),
                                   sources: [0], destinations: dests.map((_, i) => i + 1),
                                   metrics: ["distance", "duration"]}})}};
    }} else {{
      const coords = [p.lng + "," + p.lat].concat(dests.map(q => q.lng + "," + q.lat)).join(";");
      req = {{id: "routes #" + p.id, kind: "osrm-table",
             url: CHAIN.osrm_endpoint + "/table/v1/driving/" + coords + "?sources=0&annotations=duration,distance"}};
    }}
    try {{
      const body = await fetchOne(req, 1);
      seeds.routes.push({{kind: req.kind, src: [p.lat, p.lng],
                         dests: dests.map(q => [q.lat, q.lng]), body}});
      log("OK routes #" + p.id + " (" + dests.length + " target(s))");
    }} catch (e) {{ failed++; log("FAIL routes #" + p.id + ": " + e.message); }}
    tick(); await sleep(THROTTLE[req.kind] || 1000);
  }}
}}

document.getElementById('go').onclick = async () => {{
  document.getElementById('go').disabled = true;
  // a key pasted into the field upgrades route fetching to TRUCKING (HGV); it is used
  // ONLY here in the browser (Authorization header to openrouteservice) and is NEVER put
  // into the downloaded seeds, so it never re-enters the chat
  const _k = (document.getElementById('orskey') || {{}}).value;
  if (_k && _k.trim()) CHAIN.ors_key = _k.trim();
  const props = CHAIN.properties || [];
  total = REQUESTS.length + props.filter(x => x.geocode_url).length
        + (CHAIN.do_routes ? props.length : 0) || 1;
  for (const req of REQUESTS) {{
    try {{
      out[req.save_as] = await fetchOne(req, 1);
      log(`OK ${{req.id}}`);
    }} catch (e) {{ failed++; log(`FAIL ${{req.id}}: ${{e.message}} (network blocked? try another network)`); }}
    tick(); await sleep(THROTTLE[req.kind] || 1000);
  }}
  await runChain();
  log(`\\nDone` + (failed ? ` (${{failed}} failed - you can still download and re-try later)` : " - all fetched") + ".");
  document.getElementById('dl').disabled =
      seeds.geocode.length + seeds.routes.length + Object.keys(out).length === 0;
}};
document.getElementById('dl').onclick = () => {{
  const blob = new Blob([JSON.stringify(seeds)], {{type: "application/json"}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = "{SEEDS_FILE}";
  a.click();
  log("Saved {SEEDS_FILE} - now drop that file into the chat with the assistant and it will continue.");
}};
if (CHAIN.do_routes) document.getElementById('keyrow').style.display = '';
log(`${{REQUESTS.length}} request(s) planned. Click 'Fetch all'.`);
</script></body></html>
"""


def _ckey(lat: float, lng: float) -> str:
    return f"{round(lat, 3)},{round(lng, 3)}"


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)


def _data_url(url: str, method: str = "GET",
              headers: dict | None = None, body: str | None = None) -> str:
    """A minimal data:text/html fetcher carrying ONLY this one request (never the
    357 KB dashboard - too big for a URL param). The Playwright tier navigates to
    it; the inline fetch() runs in the browser's OWN network namespace (which has
    outbound internet) and the APIs send Access-Control-Allow-Origin:*, so the
    cross-origin fetch succeeds. The result lands on window.__m and is read back via
    browser_evaluate(() => JSON.stringify(window.__m), filename=<save_as>). A POST
    (the ORS trucking matrix) carries its method/headers/body inline."""
    opts: dict = {"method": method}
    if headers:
        opts["headers"] = headers
    if body is not None:
        opts["body"] = body
    script = ('window.__done=false;'
              'fetch(' + json.dumps(url) + ',' + json.dumps(opts) + ').then(r=>r.text())'
              '.then(t=>{try{window.__m=JSON.parse(t)}catch(e){window.__m=t}window.__done=true})'
              '.catch(e=>{window.__err=String(e);window.__done=true})')
    html = "<!doctype html><meta charset=utf-8><body><script>" + script + "</script></body>"
    return "data:text/html," + quote(html)


def _chain_spec(canonical: dict, args) -> dict:
    """Everything the browser page needs to resolve the WHOLE enrichment in ONE
    'Fetch all' click: geocode the unresolved cities itself, derive the route
    targets from the embedded POI set (the same dataset + caps Python uses, so
    the results are identical), then fetch the routes - one seeds file back.
    Two round-trips used to be needed only because route origins depend on the
    fresh geocodes; the page resolves that dependency locally."""
    props = []
    for p in canonical.get("properties", []):
        country = str(p.get("country", "")).strip()
        known = not E._is_unknown_cc(country)
        # known/country travel to the page so its PASS B can spot unknown-country
        # outliers and constrain the re-query to the dominant country (P2-8)
        ent = {"id": p.get("id"), "known": known, "country": country}
        if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float)):
            ent["lat"], ent["lng"] = p["lat"], p["lng"]
        else:
            city = str(p.get("city", "")).strip()
            if not city or E._is_unknown_cc(city):
                continue  # nothing to geocode - stays an honest gap
            from urllib.parse import urlencode
            q = {"q": city, "format": "json", "limit": 1, "addressdetails": 1}
            if known:
                q["countrycodes"] = country.lower()
            ent["city"] = city
            ent["geokey"] = f"{city}|{country}".lower()
            ent["geocode_url"] = "https://nominatim.openstreetmap.org/search?" + urlencode(q)
        props.append(ent)
    pois = []
    ds = E._poi_dataset()
    if ds:
        pois += [{"type": q["type"], "lat": q["lat"], "lng": q["lng"]}
                 for q in ds.get("pois", []) if q.get("type") in ("air", "port", "rail")]
    bd = E._borders_dataset()
    if bd:  # complete border set (the page picks nearest-of-type, so a full candidate set is fine)
        pois += [{"type": "border", "lat": q["lat"], "lng": q["lng"]}
                 for q in bd.get("pois", []) if isinstance(q.get("lat"), (int, float))]
    cm = E._cities_major_dataset()
    if cm:  # complete >=100k city set
        pois += [{"type": "city", "lat": c["lat"], "lng": c["lng"]}
                 for c in cm.get("cities", []) if isinstance(c.get("lat"), (int, float))]
    # outage fallback: source any type whose COMPLETE dataset is absent from the curated library
    _need = (({"air", "port", "rail"} if not ds else set())
             | ({"border"} if not bd else set()) | ({"city"} if not cm else set()))
    if _need:
        pois += [{"type": q.get("type"), "lat": q.get("lat"), "lng": q.get("lng")}
                 for q in E._poi_lib().get("pois", [])
                 if q.get("type") in _need and isinstance(q.get("lat"), (int, float))]
    return {
        "do_routes": bool(args.osrm),
        "properties": props, "pois": pois, "caps": E.POI_MAX_KM,
        "ors_key": args.ors_key or "", "osrm_endpoint": args.osrm_endpoint,
        "ors_url": "https://api.openrouteservice.org/v2/matrix/driving-hgv",
    }


def cmd_plan(args) -> int:
    # Resolve the effective ORS key ONCE here: an explicit --ors-key wins; if
    # absent, fall back to the ORS_API_KEY env var - the SAME resolution
    # enrich.py main() uses. Without this a standalone `plan --osrm` with only
    # the env key set would emit CAR (keyless OSRM) requests, ingest would cache
    # non-hgv keys, and the later offline enrich (which DOES read the env key)
    # would take the driving-hgv path, match 0 pairs, and loop on exit 8. The
    # orchestrated run.py path passes an explicit (truthy) --ors-key, so this
    # default never changes it. Written back onto args so both this function's
    # --osrm block and _chain_spec read the same resolved key.
    args.ors_key = (getattr(args, "ors_key", "") or os.environ.get("ORS_API_KEY", "")).strip()
    work = Path(args.work)
    canonical = json.loads(Path(args.canonical).read_text(encoding="utf-8"))
    E.CACHE_DIR = work  # caches live in the work dir
    located = [p for p in canonical.get("properties", [])
               if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))]
    requests_out: list[dict] = []

    if args.geocode:  # cities still without coordinates (no map link, cache cold)
        from urllib.parse import urlencode
        gcache = E._load_cache(E.GEOCODE_CACHE)
        seen_g = set()
        for p in canonical.get("properties", []):
            if isinstance(p.get("lat"), (int, float)):
                continue
            city = str(p.get("city", "")).strip()
            country = str(p.get("country", "")).strip()
            if not city or E._is_unknown_cc(city):
                continue
            gkey = f"{city}|{country}".lower()
            if gkey in gcache or gkey in seen_g:
                continue
            seen_g.add(gkey)
            params = {"q": city, "format": "json", "limit": 1, "addressdetails": 1}
            if not E._is_unknown_cc(country):
                params["countrycodes"] = country.lower()
            _gurl = "https://nominatim.openstreetmap.org/search?" + urlencode(params)
            requests_out.append({
                "id": f"geo_{_safe(gkey)}", "kind": "nominatim", "key": gkey,
                "url": _gurl,
                "save_as": f"geo_{_safe(gkey)}.json",
                "data_url": _data_url(_gurl),
            })

    if args.pois and E._poi_dataset():
        print("  (POIs come from the bundled complete dataset - no web requests needed)")
    elif args.pois:
        cache = E._load_cache(E.POI_OSM_CACHE)
        seen = set()
        for p in located:
            ck = _ckey(p["lat"], p["lng"])
            if ck in cache or ck in seen:
                continue
            seen.add(ck)
            q = E._overpass_query(round(p["lat"], 3), round(p["lng"], 3), cap=200)
            _purl = f"{E.OVERPASS_ENDPOINT}?data={quote(q)}"
            requests_out.append({
                "id": f"poi_{_safe(ck)}", "kind": "overpass", "key": ck,
                "src": [round(p["lat"], 3), round(p["lng"], 3)],
                "url": _purl,
                "save_as": f"poi_{_safe(ck)}.json",
                "data_url": _data_url(_purl),
            })

    if args.osrm:
        pois = canonical.get("pois", [])
        route_cache = E._load_cache(E.OSRM_CACHE)
        hgv = bool(args.ors_key)
        if pois:
            for p in located:
                dests = E._relevant_pois(p, pois)
                dests = [q for q in dests
                         if E._pair_key(hgv, p["lat"], p["lng"], q["lat"], q["lng"])
                         not in route_cache]
                if not dests:
                    continue
                if hgv:  # TRUCKING matrix via openrouteservice (the product path)
                    body = {"locations": [[p["lng"], p["lat"]]]
                                         + [[q["lng"], q["lat"]] for q in dests],
                            "sources": [0],
                            "destinations": list(range(1, len(dests) + 1)),
                            "metrics": ["distance", "duration"]}
                    _ors_url = "https://api.openrouteservice.org/v2/matrix/driving-hgv"
                    _ors_headers = {"Authorization": args.ors_key,
                                    "Content-Type": "application/json"}
                    _ors_body = json.dumps(body)
                    requests_out.append({
                        "id": f"ors_p{p.get('id')}", "kind": "ors-matrix",
                        "method": "POST",
                        "headers": _ors_headers,
                        "body": _ors_body,
                        "src": [p["lat"], p["lng"]],
                        "dests": [[q["lat"], q["lng"]] for q in dests],
                        "url": _ors_url,
                        "save_as": f"ors_p{_safe(str(p.get('id')))}.json",
                        "data_url": _data_url(_ors_url, "POST", _ors_headers, _ors_body),
                    })
                else:  # keyless fallback: car via the public OSRM demo (flagged)
                    coords = ";".join([f"{p['lng']},{p['lat']}"]
                                      + [f"{q['lng']},{q['lat']}" for q in dests])
                    _osrm_url = (f"{args.osrm_endpoint}/table/v1/driving/{coords}"
                                 f"?sources=0&annotations=duration,distance")
                    requests_out.append({
                        "id": f"osrm_p{p.get('id')}", "kind": "osrm-table",
                        "src": [p["lat"], p["lng"]],
                        "dests": [[q["lat"], q["lng"]] for q in dests],
                        "url": _osrm_url,
                        "save_as": f"osrm_p{_safe(str(p.get('id')))}.json",
                        "data_url": _data_url(_osrm_url),
                    })

    out = work / REQUESTS_FILE
    (work / FETCH_DIR).mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "instructions": INSTRUCTIONS,
        "fetched_dir": str((work / FETCH_DIR).resolve()),
        "requests": requests_out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # the page SELF-CHAINS geocode -> targets -> routes in one click, so it only
    # needs the static requests the chain does not cover (the Overpass fallback);
    # web_requests.json keeps the full static list - the PAGE executes it (and an
    # online host's own tools could replay it into web_fetched/; WebFetch cannot)
    chain = _chain_spec(canonical, args) if (args.geocode or args.osrm) else None
    chain_work = bool(chain and (any("geocode_url" in p for p in chain["properties"])
                                 or (chain["do_routes"] and chain["properties"])))
    page_static = [r for r in requests_out if r["kind"] == "overpass"]
    if requests_out or chain_work:  # the operator-facing fetcher page (PREFERRED transport)
        (work / ARTIFACT_FILE).write_text(_artifact_html(page_static, chain), encoding="utf-8")
        print(f"web-enrich plan: {len(requests_out)} static request(s) -> {out}"
              + (" + self-chaining geocode->routes in the page" if chain_work else ""))
        print(f"  fetcher page  -> {work / ARTIFACT_FILE}  (ONE 'Fetch all' click resolves "
              f"everything; save {SEEDS_FILE} into the work folder / drop it in the chat)")
    else:
        print("web-enrich plan: nothing fetchable (no located properties / caches warm)")
    return 0 if (requests_out or chain_work) else 1  # rc 1 = nothing fetchable (degraded)


def _parse_json_text(raw: str):
    """Lenient parse: a WebFetch save may carry stray text around the JSON body."""
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        for opener, closer in (("{", "}"), ("[", "]")):
            s, e = raw.find(opener), raw.rfind(closer)
            if 0 <= s < e:
                return json.loads(raw[s:e + 1])
        raise ValueError("no JSON found")


def _route_error(data) -> str | None:
    """Identify an ORS/OSRM ERROR envelope so it is never cached as 'no routes'.
    ORS error: {"error": {"code":.., "message":..}} or {"error": "..."}.
    OSRM error: {"code": <not 'Ok'>, "message": ...} (e.g. InvalidQuery, NoRoute).
    A SUCCESS body has durations/distances (OSRM code == 'Ok'), so this returns
    None and the happy path is untouched."""
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if err:
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code")
            return f"ORS error: {str(msg)[:80]}" if msg else "ORS error"
        return f"ORS error: {str(err)[:80]}"
    code = data.get("code")
    if code is not None and str(code) != "Ok":
        msg = data.get("message")
        return f"OSRM {code}" + (f": {str(msg)[:80]}" if msg else "")
    return None


def _num(v):
    """A real numeric cell (NOT bool), else None - so 'NA'/null/true never reach /60."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ingest_route(kind: str, src, dests, data, route_cache: dict):
    """Fold one matrix/table response into the route cache (shared by the static
    request path and the self-chaining v2 bundle). Returns (n_cached, err): err
    is a one-line description when the response is an ORS/OSRM ERROR envelope that
    produced no durations - so a quota/InvalidQuery is never cached as a silent
    'no routes nearby'. A genuinely empty-but-valid response (durations present,
    all null) returns (0, None) and is left uncached, which is correct.
    RAISE-SAFE by contract: the static caller has no try/except, so a malformed
    body (null/non-numeric durations, bad dests, bad src) must yield (0, err-or-None),
    never an exception."""
    d = data if isinstance(data, dict) else {}

    def _row(key):  # first row of a matrix, or [] for any malformed shape
        v = d.get(key)
        return v[0] if (isinstance(v, list) and v and isinstance(v[0], list)) else []
    durations, distances = _row("durations"), _row("distances")
    try:
        plat, plng = src
    except Exception:
        return 0, _route_error(data)
    hgv = kind == "ors-matrix"  # trucking entries are profile-tagged
    # OSRM tables include the source itself at index 0; ORS matrix rows
    # index the destinations directly
    off = 0 if hgv else 1
    n = 0
    for j, q in enumerate(dests if isinstance(dests, list) else []):
        if not (isinstance(q, (list, tuple)) and len(q) == 2):
            continue
        qlat, qlng = q
        k = j + off
        if k < len(durations) and _num(durations[k]) is not None:
            entry = {"min": round(durations[k] / 60)}
            if k < len(distances) and _num(distances[k]) is not None:
                entry["km"] = round(distances[k] / 1000, 1)
            entry.setdefault("km", round(E._haversine_km(plat, plng, qlat, qlng), 1))
            route_cache[E._pair_key(hgv, plat, plng, qlat, qlng)] = entry
            n += 1
    err = _route_error(data) if n == 0 else None
    return n, err


def cmd_ingest(args) -> int:
    work = Path(args.work)
    E.CACHE_DIR = work
    plan_file = work / REQUESTS_FILE
    if not plan_file.exists():
        print("no web_requests.json in the work dir - run `web_enrich.py plan` first")
        return 1
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    fetched = work / FETCH_DIR
    # the browser artifact's single-bundle output is the PREFERRED input; loose
    # per-request files in web_fetched/ (WebFetch fallback) still work
    bundle: dict = {}
    for cand in ([Path(args.seeds)] if args.seeds else []) + [work / SEEDS_FILE, fetched / SEEDS_FILE]:
        if cand and cand.exists():
            try:
                bundle = json.loads(cand.read_text(encoding="utf-8"))
                print(f"  using seeds bundle {cand}")
                break
            except Exception as e:
                print(f"  [warn] seeds bundle {cand} unreadable ({e})")
    geo_cache = E._load_cache(E.GEOCODE_CACHE)
    poi_cache = E._load_cache(E.POI_OSM_CACHE)
    route_cache = E._load_cache(E.OSRM_CACHE)
    n_geo = n_poi = n_osrm = n_missing = n_bad = 0
    used_v2_bundle = False  # the self-chaining page already fetched geocode + routes

    # v2 self-describing bundle (the chaining page): geocodes + routes carry their
    # own metadata, so ingest needs no request-matching; static responses (the
    # Overpass fallback) ride along under 'static'
    # accept v>=2 and never crash on a non-numeric v; a string "2" must not
    # silently degrade the bundle to static-only (P3-8). bool is excluded (it
    # subclasses int) so a stray v:true is treated as unrecognised, not v==1.
    _v = bundle.get("v") if isinstance(bundle, dict) else None
    _vnum = (int(_v) if (isinstance(_v, (int, float)) and not isinstance(_v, bool))
             or (isinstance(_v, str) and _v.strip().lstrip("+").isdigit()) else None)
    _fold_v2 = isinstance(bundle, dict) and _vnum is not None and _vnum >= 2
    _has_seed_keys = isinstance(bundle, dict) and (bundle.get("geocode") or bundle.get("routes"))
    if _has_seed_keys and not _fold_v2:
        # a self-describing seeds file (carries geocode/routes) whose version is
        # missing, unrecognised or too old to fold - WARN rather than silently drop
        # it to static-only, so a bundle's genuine data is never lost without a trace
        print(f"  [warn] seeds bundle has geocode/routes but v={_v!r} is missing or "
              f"unrecognised - NOT folding them; re-fetch with a current web_enrich.html")
    if _fold_v2:
        for g in bundle.get("geocode", []):
            try:
                arr = _parse_json_text(g.get("body", ""))
                if isinstance(arr, list) and arr:
                    cc = str((arr[0].get("address", {}) or {}).get("country_code", "")).upper()
                    geo_cache[g["key"]] = {"latlng": [float(arr[0]["lat"]), float(arr[0]["lon"])],
                                           "cc": cc}
                    n_geo += 1
            except Exception as e:
                print(f"  [skip] geocode {g.get('key')}: {e}")
                n_bad += 1
        for r in bundle.get("routes", []):
            try:
                cached, err = _ingest_route(r.get("kind", ""), r.get("src"), r.get("dests"),
                                            _parse_json_text(r.get("body", "")), route_cache)
                n_osrm += cached
                if err:
                    print(f"  [skip] route {r.get('kind', '')} src={r.get('src')}: {err}"
                          f" - 0 pair(s), re-fetch this request")
                    n_bad += 1
            except Exception as e:
                print(f"  [skip] route bundle entry: {e}")
                n_bad += 1
        used_v2_bundle = True
        bundle = bundle.get("static", {}) or {}

    # kinds the self-chaining page resolves itself; in a v2 ingest these are
    # already cached from the bundle's geocode/routes arrays, so a 'missing'
    # static duplicate here is expected and must NOT be reported as un-fetched
    CHAINED_KINDS = ("nominatim", "osrm-table", "ors-matrix")
    for req in plan.get("requests", []):
        raw = bundle.get(req["save_as"])
        if raw is None:
            f = fetched / req["save_as"]
            if not f.exists():
                if not (used_v2_bundle and req["kind"] in CHAINED_KINDS):
                    n_missing += 1
                continue
            raw = f.read_text(encoding="utf-8", errors="replace")
        try:
            data = _parse_json_text(raw)
        except Exception as e:
            print(f"  [skip] {req['save_as']}: unreadable JSON ({e})")
            n_bad += 1
            continue
        if req["kind"] == "nominatim":
            arr = data if isinstance(data, list) else []
            if arr:
                cc = str((arr[0].get("address", {}) or {}).get("country_code", "")).upper()
                geo_cache[req["key"]] = {"latlng": [float(arr[0]["lat"]), float(arr[0]["lon"])],
                                         "cc": cc}
                n_geo += 1
            continue
        if req["kind"] == "overpass":
            remark = str(data.get("remark", "")) if isinstance(data, dict) else ""
            if "error" in remark.lower():
                # an errored response cached as 'no POIs nearby' would poison the
                # cache silently - skip it and have the operator re-fetch
                print(f"  [skip] {req['save_as']}: Overpass error remark "
                      f"({remark[:60]}) - re-fetch this request")
                n_bad += 1
                continue
            lat, lng = req["src"]
            found = E._nearest_from_elements(lat, lng, data.get("elements", []))
            poi_cache[req["key"]] = found
            n_poi += 1
        elif req["kind"] in ("osrm-table", "ors-matrix"):
            cached, err = _ingest_route(req["kind"], req["src"], req.get("dests"),
                                        data, route_cache)
            n_osrm += cached
            if err:
                print(f"  [skip] {req['save_as']}: {err} - 0 pair(s), re-fetch this request")
                n_bad += 1

    if n_geo:
        E._save_cache(E.GEOCODE_CACHE, geo_cache)
    if n_poi:
        E._save_cache(E.POI_OSM_CACHE, poi_cache)
    if n_osrm:
        E._save_cache(E.OSRM_CACHE, route_cache)
    print(f"web-enrich ingest: {n_geo} geocode(s), {n_poi} POI location(s), {n_osrm} drive-time "
          f"pair(s) cached; {n_missing} response(s) not fetched yet, {n_bad} unreadable.")
    if n_missing:
        if used_v2_bundle:
            # the chain covered geocode + routes; only the Overpass (POI) static
            # requests can remain, and they ride the same fetcher page
            print("Some POI (Overpass) responses are still outstanding - re-open web_enrich.html "
                  "(or use web_requests.json), then ingest again.")
        else:
            print("Fetch the remaining requests (re-open web_enrich.html or use web_requests.json), then ingest again.")
    print("Now re-run run.py with the same arguments - enrichment will use the warm caches offline.")
    return 0 if (n_geo or n_poi or n_osrm) else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("canonical")
    p.add_argument("--work", required=True)
    p.add_argument("--geocode", action="store_true")
    p.add_argument("--pois", action="store_true")
    p.add_argument("--osrm", action="store_true")
    p.add_argument("--osrm-endpoint", default="https://router.project-osrm.org")
    p.add_argument("--ors-key", default="", help="openrouteservice key -> TRUCKING "
                   "(driving-hgv) matrix requests instead of car OSRM")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("ingest")
    p.add_argument("--work", required=True)
    p.add_argument("--seeds", help="path to the browser artifact's web_seeds.json "
                   "(default: <work>/web_seeds.json, then web_fetched/)")
    p.set_defaults(fn=cmd_ingest)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
