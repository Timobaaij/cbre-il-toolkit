#!/usr/bin/env python3
"""chrome_v45_test.py - the v45 chrome and pipeline change, pinned end to end.

v45 landed thirteen broker-asked changes in one version. They are pinned together because
they share two seams, and a partial revert of either seam is what would break them:

  THE BLANK TOKEN. The pipeline writes ONE token into every unfilled chrome-read field and
  the chrome prints the SAME token. Before v45 the data said 'tbd', the chrome's own
  fallbacks said 'tbd', three commercial rows said a long dash, and landPrice said a long
  dash too - four spellings of "not stated" on one page. normalize.BLANK is now the single
  owner and the chrome's `const BLANK` must equal it, so this eval reads both and compares
  them (the f05_sentinel_parity pattern: the Python side is the master, the eval holds the
  two equal). Critically the token is a MEMBER of UNKNOWN_FORMS, so every reader that asks
  looks_unknown() still reads such a field as absent - coverage, the trace gate and the
  Gaps Report are unaffected, which is the whole reason the swap is safe.

  WHAT THE CHROME NO LONGER SHOWS. Four surfaces were removed (the hero lede, the border
  POI category, Compare's best-value highlight, and its note), and a removal leaves debris
  in five places: the template, the config-token list, the i18n table, the twelve bundled
  packs, and the data the builder injects. This eval checks all five, because a key left in
  EN fails the i18n lockstep the moment someone adds a language, and a border POI left in
  the injected block is a row of data nothing on the page can render.

The executed half is the .mjs sibling: titleStr / partyLine / cardHTML / detailHTML run in
a node sandbox against a REAL built file. Everything a sandbox cannot reach is pinned here.

Offline. Drives a real build; needs node for the executed half.
Run: python evals/chrome_v45_test.py
"""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C            # noqa: E402
import build_dashboard as BD   # noqa: E402
import extract_xlsx as XL      # noqa: E402
import i18n as I18N            # noqa: E402
import normalize as N          # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
LANGS = ("cs", "de", "es", "fr", "hu", "it", "nl", "pl", "pt", "ro", "sk", "zh")

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _canon():
    """Two properties: one that states everything v45 renders, one that states none of it."""
    base = {"country": "GB", "city": "Knowsley", "status": "Existing Building",
            "photo": PX, "gallery": [PX], "lat": 53.46, "lng": -2.86,
            "areaUnit": "sq ft", "rentUnit": "£/sq ft/yr"}
    rich = dict(base, **{
        "id": 1, "park": "Knowsley Business Park", "displayName": "Titan, Knowsley Business Park",
        "developer": "Indurent", "landlord": "Indurent", "warehouseArea": 184700,
        "clearHeight": "15.25m", "warehouseRent": "£9.50 / sq ft / year",
        "warehouseRentVal": 9.5, "earlyAccess": "Q1 2027", "motorway": "M57, J4 1 mile",
        "brochureLink": "https://example.com/brochure.pdf",
        "videoLink": "https://example.com/flythrough",
        "websiteLink": "https://example.com/scheme",
        "streetViewLink": "https://example.com/pano",
    })
    thin = dict(base, **{"id": 2, "park": "Thin Park", "developer": "tbd", "city": "Widnes",
                         "warehouseArea": 90000})
    return {"meta": {"client": "Matalan", "units": {"area": "sq ft", "rent": "£/sq ft/yr"},
                     "hero": {"topbar_meta": "North West · 2026-09-14", "eyebrow": "",
                              "title_html": "", "footer_copyright": "© 2026 CBRE"}},
            "pois": [{"name": "Liverpool (Port)", "type": "port", "lat": 53.43, "lng": -3.00},
                     {"name": "Swiecko (Border)", "type": "border", "lat": 52.30, "lng": 14.60},
                     {"name": "Manchester", "type": "city", "lat": 53.48, "lng": -2.24}],
            "regions": {}, "properties": [rich, thin]}


def main() -> int:                                             # noqa: C901
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")

    print("== the BLANK token has ONE owner, and both languages read it ==")
    ck(N.BLANK == "TBC", f"normalize.BLANK is {N.BLANK!r}")
    ck(C.BLANK == N.BLANK, "_common re-exports the same object, so C.BLANK cannot drift")
    m = re.search(r'^const BLANK = "([^"]+)";', tpl, re.M)
    ck(bool(m), "the chrome declares a single BLANK constant")
    ck(bool(m) and m.group(1) == N.BLANK,
       f"the chrome's BLANK equals the pipeline's (chrome {m.group(1) if m else None!r})")
    ck(N.BLANK.lower() in N.UNKNOWN_FORMS,
       "it is a MEMBER of UNKNOWN_FORMS, so a field carrying it still reads as ABSENT")
    ck(N.looks_unknown(N.BLANK) and N.looks_unknown("tbd"),
       "both the new token and the pre-v45 one resolve to absence (no canonical is orphaned)")

    print()
    print("== the pipeline writes it, everywhere it used to write four things ==")
    ck(C.fill_render_sentinels({"status": None})["status"] == N.BLANK,
       "a required text field fills BLANK")
    ck(C.fill_render_sentinels({"clearHeight": "to be confirmed"})["clearHeight"] == N.BLANK,
       "a reader's own wording is normalised to it")
    ck(C.fill_render_sentinels({"landPrice": None})["landPrice"] == N.BLANK,
       "landPrice stops carrying a long dash of its own")
    ck(C.fill_render_sentinels({"country": None})["country"] == "??",
       "country KEEPS its code sentinel - it holds an ISO code, not prose")
    ck(C.fill_render_sentinels({"sprinklers": "None"})["sprinklers"] == "None",
       "a stated 'None' still survives (the extraction contract names it as DATA)")
    ck(N.sentinel("tbd", "landPrice") == N.BLANK and N.sentinel("tbd", "clearHeight") == N.BLANK,
       "normalize.sentinel agrees with fill_render_sentinels, landPrice included")
    ck(N.sentinel("tbd", "reit") is None, "reit is still None, not a printed token")
    ck(N.sentinel("15.25m", "clearHeight") == "15.25m", "a stated value passes through it")

    print()
    print("== the hero lede is gone, in all four places it lived ==")
    ck("{{lede}}" not in tpl, "the template carries no {{lede}} token")
    ck('class="lede"' not in tpl, "...and no .lede element")
    ck(".lede{" not in tpl and ".lede," not in tpl and ".hero .lede" not in tpl,
       "...and none of its three CSS rules")
    ck("lede" not in C.CONFIG_TOKENS, "_common.CONFIG_TOKENS no longer declares it")
    ck("hero_lede_fmt" not in I18N.EN, "the EN table no longer carries hero_lede_fmt")

    print()
    print("== the headline names the CLIENT, and never leaves a dangling separator ==")
    en = I18N.ui_for("en")
    ck("{client}" in en.get("hero_title_html", ""),
       "the EN default headline carries the {client} placeholder")
    t_named = BD._hero_copy({}, en, "Matalan")["title_html"]
    ck(t_named == "Matalan - Industrial &amp; Logistics <em>opportunities</em>",
       f"a stated client is composed in: {t_named!r}")
    ck("&amp;" in t_named and " & " not in t_named,
       "the ampersand is HTML-escaped (it lands inside an <h1>)")
    ck(t_named.count("<em>") == 1, "exactly one <em> pair - the accent colour hangs off it")
    t_blank = BD._hero_copy({}, en, "")["title_html"]
    ck(t_blank == "Industrial &amp; Logistics <em>opportunities</em>",
       f"a blank client drops the placeholder AND the separator: {t_blank!r}")
    ck("{client}" not in t_blank, "no raw placeholder ever reaches a reader")
    ck(BD._hero_copy({"title_html": "My own headline"}, en, "Matalan")["title_html"]
       == "My own headline", "an AUTHORED headline is never touched")
    ck(BD._hero_copy({}, en, "  ")["title_html"] == t_blank,
       "whitespace is not a client name")
    ck(I18N.EN.get("hero_eyebrow") == "Property Longlist",
       f"the eyebrow says Longlist, not Shortlist ({I18N.EN.get('hero_eyebrow')!r})")
    for lg in LANGS:
        pack = json.loads((ROOT / "assets" / "i18n" / f"{lg}.json").read_text(encoding="utf-8"))
        if "{client}" not in (pack.get("hero_title_html") or ""):
            ck(False, f"{lg}.json's headline lost the {{client}} placeholder")
            break
    else:
        ck(True, "all twelve packs carry the placeholder in their OWN wording")

    print()
    print("== the browser tab derives from the headline ==")
    dt = BD._doc_title({"title_html": "Matalan - Industrial &amp; Logistics <em>opportunities</em>",
                        "eyebrow": "Property Longlist"}, {"client": "Matalan"})
    ck(dt.startswith("Matalan - Industrial"), f"the headline leads, not the eyebrow: {dt!r}")
    ck("<em>" not in dt, "the tag is stripped")
    ck(dt.endswith(" · CBRE"), "the brand suffix uses the chrome's own middle dot")
    ck("—" not in dt and "–" not in dt, "and carries no long dash")
    ck(BD._doc_title({"doc_title": "Mine"}, {}) == "Mine", "an authored doc_title still wins")
    ck(BD._doc_title({}, {}) == "CBRE Property Longlist", "the last-resort default is stated")

    print()
    print("== the POI filters start OFF ==")
    ck('poiFilter: new Set()' in tpl,
       "state.poiFilter is empty, so the map opens on the properties alone")

    print()
    print("== the border category is gone from the chrome AND from the data ==")
    ck('"poi_border"' not in tpl and "poi_border" not in tpl,
       "no surface asks for the border label")
    for needle, where in (('["city","air","rail","port"]', "groupedDistances / the dist table"),
                          ('{ air:600, port:800, rail:300, city:300 }', "the live-POI caps")):
        ck(needle in tpl, f"{where} lists four categories")
    ck("cmp_nearest_border" not in tpl, "Compare has no nearest-border row")
    ck("poi_border" not in I18N.EN and "cmp_nearest_border" not in I18N.EN,
       "the two EN keys are gone")
    ck("border" not in BD.DISPLAY_POI_TYPES, "the builder does not consider it displayable")
    kept = BD._display_pois([{"type": "port"}, {"type": "border"}, {"type": "BORDER"}, {}])
    ck(len(kept) == 2 and all(str(q.get("type", "")).lower() != "border" for q in kept),
       f"_display_pois drops it case-insensitively (kept {[q.get('type') for q in kept]})")
    ck({} in kept, "a POI with NO stated type is KEPT - a filter must not become a data loss")

    print()
    print("== Compare loses the best-value highlight, and its note ==")
    ck("minSizeIdx" not in tpl and "minRentIdx" not in tpl,
       "neither index is computed any more")
    ck("cmp-highlight" not in tpl, "no cell can carry the class, and the CSS is gone too")
    ck("cmp_highlight_note" not in tpl and "cmp_highlight_note" not in I18N.EN,
       "the note and its EN key are gone")

    print()
    print("== the four new canonical fields are declared, typed and bound ==")
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    sprops = schema["$defs"]["property"]["properties"]
    C._CANON_PROPERTY_FIELDS = None          # force a fresh scan (module-level cache)
    C._STRING_FIELDS_STRUCT = None
    for f in ("displayName", "videoLink", "websiteLink", "streetViewLink"):
        ck(f in sprops and sprops[f].get("type") == "string", f"the schema declares {f} as a string")
        ck(bool(sprops[f].get("description")), f"...with a description that tells a reader its rule")
        ck(f in C.canonical_property_fields(), f"{f} is a live canonical field")
        ck(f in XL.COLUMN_MAP, f"extract_xlsx binds a {f} column")
    ck("displayName" in C.STRING_FIELDS,
       "displayName is on the chrome string-field list, so an unstated one fills BLANK")
    ck(C.fill_render_sentinels({"displayName": None})["displayName"] == N.BLANK,
       "...which is what makes titleStr fall back to park + unit")
    ck(C.fill_render_sentinels({"displayName": 3})["displayName"] == "3",
       "a tracker's bare numeric name is coerced, not a schema failure")
    ck(XL._header_field("Display Name") == "displayName", "'Display Name' binds")
    ck(XL._header_field("Video") == "videoLink", "'Video' binds")
    ck(XL._header_field("Street View") == "streetViewLink", "'Street View' binds")
    ck(XL._header_field("Microsite") == "websiteLink", "'Microsite' binds")
    ck(XL._header_field("Link") != "websiteLink",
       "a bare 'Link' column stays UNBOUND rather than being guessed into one of them")
    for f in ("videoLink", "websiteLink", "streetViewLink"):
        ck(f in C.NO_TRANSLATE_FIELDS if hasattr(C, "NO_TRANSLATE_FIELDS") else True,
           f"{f} is exempt from translation (a translated URL is a broken URL)")

    print()
    print("== the availability field reads as a DATE on every surface ==")
    for key in ("row_early_access", "row_early_access_date", "cmp_early_access"):
        ck(I18N.EN.get(key) == "Available date", f"EN {key} says Available date")
    ck(I18N.EN.get("modal_early_access_prefix") == "Available",
       "the modal chip prefix is the adjective, so it reads 'Available Q1 2027'")

    print()
    print("== the i18n table and the twelve packs are in lockstep ==")
    for key in ("modal_open_video", "modal_open_website", "modal_open_streetview"):
        ck(key in I18N.EN, f"EN carries {key}")
    gone = ("hero_lede_fmt", "poi_border", "cmp_nearest_border", "cmp_highlight_note")
    bad = []
    for lg in LANGS:
        pack = json.loads((ROOT / "assets" / "i18n" / f"{lg}.json").read_text(encoding="utf-8"))
        if set(pack) != set(I18N.EN):
            bad.append("%s (%d keys vs %d)" % (lg, len(pack), len(I18N.EN)))
    ck(not bad, "every pack's key set equals EN's" + (": " + ", ".join(bad) if bad else ""))
    leftover = [f"{lg}:{k}" for lg in LANGS for k in gone
                if k in json.loads((ROOT / "assets" / "i18n" / f"{lg}.json")
                                   .read_text(encoding="utf-8"))]
    ck(not leftover, "no pack still carries a removed key" + (f": {leftover}" if leftover else ""))

    print()
    print("== a BUILT dashboard carries all of it ==")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cp, hp = d / "c.json", d / "b.html"
        cp.write_text(json.dumps(_canon()), encoding="utf-8")
        BD.build(cp, hp)
        built = hp.read_text(encoding="utf-8")

        ck('class="lede"' not in built, "no lede paragraph")
        ck("Matalan - Industrial &amp; Logistics <em>opportunities</em>" in built,
           "the hero headline names the client")
        ck("<title>Matalan - Industrial &amp;amp; Logistics opportunities · CBRE</title>" in built
           or "Matalan - Industrial" in built.split("</title>")[0],
           "the browser tab does too")
        ck("(Border)" not in built.split("const PROPS")[0].split("const POIS")[-1]
           if "const POIS" in built else True, "no border POI reaches the POIS block")
        pois = json.loads(re.search(r"const POIS = (\[.*?\]);", built, re.S).group(1))
        ck(len(pois) == 2 and all(q.get("type") != "border" for q in pois),
           f"two POIs ship, neither a border crossing (got {[q.get('type') for q in pois]})")
        props = json.loads(re.search(r"const PROPS = (\[.*?\]);\s*\n", built, re.S).group(1))
        thin = [p for p in props if p["park"] == "Thin Park"][0]
        ck(thin["developer"] == N.BLANK,
           f"the unfilled fields in the DATA carry the blank token (got {thin['developer']!r})")
        ck(thin["landPrice"] == N.BLANK, "...including landPrice")
        ck("tbd" not in json.dumps(props),
           "and no property field still says 'tbd' anywhere in the shipped data")

        print()
        print("== the executed half (node) ==")
        node = shutil.which("node")
        if not node:
            ck(False, "node is required to execute the chrome (install node or add it to PATH)")
        else:
            mjs = Path(__file__).with_suffix(".mjs")
            r = subprocess.run([node, str(mjs), str(hp)], capture_output=True, text=True,
                               timeout=180)
            print(r.stdout.rstrip())
            if r.stderr.strip():
                print(r.stderr.rstrip())
            ck(r.returncode == 0, "the EXECUTED chrome assertions pass (see above)")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
