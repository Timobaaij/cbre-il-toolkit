# -*- coding: utf-8 -*-
"""Assemble ONE portable HTML file: CBRE app bar + Storyline + Dashboard.

    python assemble.py <report_dir> [-o <out.html>]

report_dir must contain meta.json, units.json, story.js and dash.js (see
SKILL.md). Everything else - fonts, React/Framer runtime, Leaflet, the vector
basemap, the dashboard core - comes from ../engine and is inlined, so the file
opens by double-click with no server and no network (street tiles load only
when a reader zooms right in).

Both stylesheets collide on dozens of selectors (:root, body, *, svg, table...),
so each is scoped under its own view root with cssscope.py.
"""
import argparse, base64, datetime, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True          # never write __pycache__ into the skill folder
from cssscope import scope_css  # noqa: E402

ENGINE = os.path.join(os.path.dirname(HERE), "engine")
FACES = [
    ("Calibre", "Calibre-400.woff2", 400, "woff2"), ("Calibre", "Calibre-500.woff2", 500, "woff2"),
    ("Calibre", "Calibre-600.woff2", 600, "woff2"), ("Calibre", "Calibre-700.woff2", 700, "woff2"),
    ("Financier Display", "FinancierDisplay-400.woff2", 400, "woff2"),
    ("Financier Display", "FinancierDisplay-600.woff2", 600, "woff2"),
    ("Space Mono", "SpaceMono-400.ttf", 400, "truetype"), ("Space Mono", "SpaceMono-700.ttf", 700, "truetype"),
]
MIME = {"woff2": "font/woff2", "truetype": "font/ttf"}


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def need(p, hint):
    if not os.path.exists(p):
        sys.exit(f"MISSING {p}\n  {hint}")
    return p


def font_css():
    out = []
    for fam, fn, w, fmt in FACES:
        b64 = base64.b64encode(open(need(os.path.join(ENGINE, "fonts", fn), "engine fonts missing"),
                                    "rb").read()).decode("ascii")
        out.append("@font-face{font-family:'%s';font-style:normal;font-weight:%d;font-display:block;"
                   "src:url(data:%s;base64,%s) format('%s')}" % (fam, w, MIME[fmt], b64, fmt))
    return "".join(out)


def syntax_check(label, js):
    """A syntax error in one inline script silently kills that whole view, so
    stop the build instead. Uses Node when present; skipped (and said so) if not."""
    import shutil, subprocess, tempfile
    node = shutil.which("node")
    if not node:
        print(f"NOTE node not found - {label} not syntax-checked; Visual QA must confirm it renders")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as t:
        t.write(js)
        path = t.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True, encoding="utf-8")
    finally:
        os.unlink(path)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).replace(path, label)
        sys.exit(f"SYNTAX ERROR in {label}:\n{msg.strip()[:1500]}")


def script_safe(js):
    """Inline scripts end at the first </script, wherever it appears."""
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)


APP_CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#012A2D;font-family:'Calibre',-apple-system,'Segoe UI',Arial,sans-serif}
:root{--bar-h:56px;--cbre:#003F2D;--acc:#17E88F}
::selection{background:#17E88F;color:#003F2D}
.sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap;border:0}
.skiplink{position:fixed;left:16px;top:-60px;z-index:300;background:var(--acc);
  color:var(--cbre);padding:10px 16px;font:400 13px/1 'Calibre',sans-serif;
  border-radius:2px;text-decoration:none;transition:top 180ms cubic-bezier(.2,0,.2,1)}
.skiplink:focus{top:10px}
.appbar{position:fixed;top:0;left:0;right:0;z-index:200;height:var(--bar-h);
  background:var(--cbre);display:flex;align-items:center}
.appbar-in{max-width:1520px;margin:0 auto;padding:0 clamp(18px,3vw,32px);width:100%;
  display:flex;align-items:center;gap:clamp(12px,2vw,24px)}
.brand{font:700 19px/1 'Calibre',sans-serif;letter-spacing:.14em;color:#fff;flex:0 0 auto}
.viewswitch{display:flex;flex:0 0 auto;border:1px solid rgba(255,255,255,.42);
  border-radius:2px;overflow:hidden}
.viewswitch button{font:400 10px/1 'Space Mono',monospace;letter-spacing:.14em;
  text-transform:uppercase;padding:9px 15px;min-height:34px;background:transparent;
  border:0;color:rgba(255,255,255,.76);cursor:pointer;white-space:nowrap;
  transition:background 120ms cubic-bezier(.2,0,.2,1),color 120ms cubic-bezier(.2,0,.2,1)}
.viewswitch button[aria-selected="true"]{background:var(--acc);color:var(--cbre)}
.viewswitch button:not([aria-selected="true"]):hover{background:rgba(255,255,255,.14);color:#fff}
.viewswitch button:focus-visible{outline:2px solid #fff;outline-offset:-3px}
.appbar-r{margin-left:auto;display:flex;align-items:center;gap:16px;min-width:0;
  font:400 12px/1 'Calibre',sans-serif;color:rgba(255,255,255,.78);white-space:nowrap}
.appbar-r .ctx{min-width:0;max-width:min(40vw,560px);overflow:hidden;text-overflow:ellipsis}
.btn-csv{font:400 10px/1 'Space Mono',monospace;letter-spacing:.14em;text-transform:uppercase;
  background:transparent;border:1px solid var(--acc);color:var(--acc);padding:9px 13px;
  min-height:34px;border-radius:2px;cursor:pointer;
  transition:background 120ms cubic-bezier(.2,0,.2,1),color 120ms cubic-bezier(.2,0,.2,1)}
.btn-csv:hover{background:var(--acc);color:var(--cbre)}
.btn-csv:focus-visible{outline:2px solid #fff;outline-offset:2px}
/* Focus moves to the new view's heading on switch; a programmatic target gets no ring. */
#view-story [tabindex="-1"]:focus,#view-dash [tabindex="-1"]:focus{outline:none!important;box-shadow:none!important}
#view-story,#view-dash{padding-top:var(--bar-h)}
#view-story[hidden],#view-dash[hidden]{display:none}
/* The story's fixed ground sits at z-index -2. Without isolation it paints
   beneath #view-story's own background and every light scene keeps a dark
   ground under dark-green type. */
#view-story{isolation:isolate}
body[data-view="story"]{background:#012A2D}
body[data-view="dash"]{background:#F5F7F7}
body[data-view="story"] .btn-csv{display:none}
@media (max-width:860px){
  .appbar-r .ctx{display:none}
  .btn-csv .lbl{display:none}
  .viewswitch button{padding:9px 11px;letter-spacing:.1em}
}
@media print{
  .appbar,.skiplink{display:none!important}
  #view-story,#view-dash{padding-top:0}
  [hidden]{display:none!important}
  body,body[data-view]{background:#fff!important}
}
"""

APP_JS = """
(function(){
  var story = document.getElementById('view-story');
  var dash  = document.getElementById('view-dash');
  var tabs  = [].slice.call(document.querySelectorAll('.viewswitch button'));
  var pos = { story: 0, dash: 0 }, current = 'story', dashReady = false;
  function setView(v, push){
    if (v !== 'story' && v !== 'dash') v = 'story';
    if (v === current && (v !== 'dash' || dashReady)) return;
    pos[current] = window.scrollY;
    current = v;
    story.hidden = v !== 'story';
    dash.hidden  = v !== 'dash';
    document.body.dataset.view = v;
    tabs.forEach(function(t){ t.setAttribute('aria-selected', t.dataset.view === v ? 'true' : 'false'); });
    if (v === 'dash'){
      if (!dashReady){ dashReady = true; window.__initDashboard(); }
      else if (window.__dashResize) window.__dashResize();
    }
    window.scrollTo(0, pos[v] || 0);
    if (push && location.hash !== '#' + v) history.replaceState(null, '', '#' + v);
    var h = document.querySelector('#view-' + v + ' h1, #view-' + v + ' h2');
    if (h){ h.setAttribute('tabindex','-1'); h.focus({preventScroll:true}); }
  }
  window.__setView = function(v){ setView(v, true); };
  tabs.forEach(function(t){ t.addEventListener('click', function(){ setView(t.dataset.view, true); }); });
  addEventListener('hashchange', function(){ setView((location.hash || '').replace('#',''), false); });
  document.body.dataset.view = 'story';
  if (/^#dash/.test(location.hash || '')) setView('dash', false);
})();
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("-o", "--out")
    ap.add_argument("--stub-missing", action="store_true",
                    help="build even if story.js or dash.js is not written yet (for an author's self-check)")
    a = ap.parse_args()
    R = a.report
    meta = json.load(open(need(os.path.join(R, "meta.json"), "write meta.json (see SKILL.md)"), encoding="utf-8"))
    units = json.load(open(need(os.path.join(R, "units.json"), "run scripts/evergreen_units.py"), encoding="utf-8"))

    def report_js(name, hint, stub):
        p = os.path.join(R, name)
        if os.path.exists(p):
            return read(p)
        if a.stub_missing:
            print(f"NOTE {name} not written yet - stubbed for this self-check build")
            return stub
        return read(need(p, hint))

    story_js = report_js("story.js", "the storyline author writes report/story.js (or pass --stub-missing)",
                         "document.getElementById('root').innerHTML='<p style=\"padding:140px 32px;color:#fff;"
                         "font:400 20px Calibre,sans-serif\">Storyline not written yet (self-check build).</p>';")
    dash_js_user = report_js("dash.js", "the dashboard author writes report/dash.js (or pass --stub-missing)",
                             "/* dash.js not written yet: engine defaults (self-check build) */")

    runtime = read(need(os.path.join(ENGINE, "story-runtime.js"), "engine/story-runtime.js is missing"))
    story_css = read(need(os.path.join(ENGINE, "story.css"), "engine/story.css is missing"))
    tpl = read(need(os.path.join(ENGINE, "dashboard.html"), "engine/dashboard.html is missing"))
    lcss = re.sub(r"url\((?!data:)[^)]*\)", "none", read(os.path.join(ENGINE, "vendor", "leaflet.css")))
    ljs = read(os.path.join(ENGINE, "vendor", "leaflet.js"))
    land = read(os.path.join(ENGINE, "land.json"))

    meta.setdefault("built", datetime.date.today().isoformat())
    client = meta.get("client", "Portfolio")
    title = meta.get("title") or f"{client} — Portfolio"
    ctx = meta.get("context") or " · ".join(x for x in (client, meta.get("sector")) if x)
    if len(ctx) > 90:
        print(f"NOTE meta.context is {len(ctx)} chars; the app bar shows about 60 before the ellipsis. "
              f"Keep it to 'Client · Sector' or similar")
    units_js = json.dumps(units, ensure_ascii=False, separators=(",", ":"))
    meta_js = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))

    # ---- dashboard: the template's own CSS, body and core script -------------
    d_css = re.findall(r"<style[^>]*>(.*?)</style>", tpl, re.S)[-1]
    d_body = re.search(r"<body[^>]*>(.*?)</body>", tpl, re.S).group(1)
    d_body = re.sub(r"<script[^>]*>.*?</script>", "", d_body, flags=re.S).strip()
    d_js = re.findall(r"<script[^>]*>(.*?)</script>", tpl, re.S)[-1]
    for ph in ("/*__UNITS__*/", "/*__LAND__*/null", "/*__META__*/", "/*__DASH__*/"):
        if ph not in d_js:
            sys.exit(f"engine/dashboard.html has no {ph} placeholder")
    d_js = (d_js.replace("/*__UNITS__*/", "window.__UNITS__")
                .replace("/*__LAND__*/null", land)
                .replace("/*__META__*/", "window.__META__")
                .replace("/*__DASH__*/", "\n/* ---- report dash.js ---- */\n" + dash_js_user + "\n/* ---- end dash.js ---- */\n"))
    d_js = "(function(){\n" + d_js + "\n})();"
    syntax_check("report/story.js", story_js)
    syntax_check("the dashboard script (engine core + report/dash.js)", d_js)

    hoist = []
    story_css = re.sub(r"@font-face\s*\{[^}]*\}", "", story_css)
    s_css = scope_css(story_css, "#view-story", hoist)
    dash_css = scope_css(d_css, "#view-dash", hoist)
    leaflet_css = scope_css(lcss, "#view-dash", hoist)
    hoist = [h for h in hoist if not h.lower().startswith("@font-face")]

    app_html = f"""
<a class="skiplink" href="#view-main">Skip to content</a>
<header class="appbar"><div class="appbar-in">
  <span class="brand">CBRE</span>
  <nav class="viewswitch" role="tablist" aria-label="Choose a view">
    <button type="button" role="tab" id="tab-story" data-view="story" aria-selected="true" aria-controls="view-story">Storyline</button>
    <button type="button" role="tab" id="tab-dash" data-view="dash" aria-selected="false" aria-controls="view-dash">Dashboard</button>
  </nav>
  <div class="appbar-r"><span class="ctx" title="{html.escape(ctx)}">{html.escape(ctx)}</span>
    <button class="btn-csv" id="btnCsv" type="button"><span class="lbl">Export </span>CSV</button></div>
</div></header>"""

    desc = meta.get("description") or f"CBRE portfolio storyline and dashboard for {client}."
    out = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} | CBRE</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23003F2D'/%3E%3Crect x='6' y='14' width='7' height='12' fill='%2317E88F'/%3E%3Crect x='15' y='9' width='7' height='17' fill='%23FFFFFF'/%3E%3Crect x='24' y='18' width='3' height='8' fill='%2380BBAD'/%3E%3C/svg%3E">
<style>{font_css()}</style>
<style>{"".join(hoist)}</style>
<style>{APP_CSS}</style>
<style>{leaflet_css}</style>
<style>{s_css}</style>
<style>{dash_css}</style>
</head>
<body>
{app_html}
<div id="view-main">
<div id="view-story"><div id="root"></div></div>
<div id="view-dash" hidden>{d_body}</div>
</div>
<noscript><div style="padding:80px 24px;font-family:Georgia,serif;color:#003F2D;background:#fff">
<h1>{html.escape(title)}</h1><p>This page needs JavaScript. {html.escape(desc)}</p></div></noscript>
<script>window.__UNITS__={script_safe(units_js)};window.__META__={script_safe(meta_js)};
window.STORY_DATA={{units:window.__UNITS__,meta:window.__META__}};</script>
<script>{script_safe(ljs)}</script>
<script>{script_safe(runtime)}</script>
<script>
/* ---- report story.js ---- */
{script_safe(story_js)}
</script>
<script>{script_safe(d_js)}</script>
<script>{APP_JS}</script>
</body>
</html>
"""
    bad = sorted({u for u in re.findall(r"https?://[^\s\"')<>]+", out)
                  if not any(k in u for k in ("arcgisonline.com", "openstreetmap.org", "www.w3.org",
                                              "leafletjs.com", "reactjs.org", "react.dev",
                                              "bugs.chromium.org", "bugzilla.mozilla.org"))})
    if bad:
        print("NOTE external references in the file (check none are fetched):", bad[:8])
    dest = a.out or os.path.join(R, re.sub(r"[^A-Za-z0-9]+", "_", client).strip("_") + "_Portfolio.html")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(out)
    print("wrote %s  (%.2f MB, %d units, built %s)" % (dest, os.path.getsize(dest) / 1048576, len(units),
                                                      datetime.date.today().isoformat()))


if __name__ == "__main__":
    main()
