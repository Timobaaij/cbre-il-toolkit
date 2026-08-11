#!/usr/bin/env python3
"""i18n_test.py - the v19 localisation eval (run by the maintenance battery).

Asserts the i18n machinery + the complete English baseline:
  1. i18n.EN is non-empty; TABLE['en'] is EN; ui_for('en') returns EN.
  2. Template <-> EN agreement: every data-i18n / data-i18n-ph / data-i18n-al value
     and every T('...')/T("...") key in the template is a key in EN, and EN has no
     orphan keys beyond the format/sub keys (consumed in Python, not referenced in
     the template). This keeps the table and template in lockstep.
  3. render(en) fills {{ui_json}} (valid JSON, round-trips, contains tab_grid) and
     {{locale}}="en-GB"; no leftover {{token}}; const UI / const LOCALE present.
  4. de is a real bundled translation (chrome translated, locale de-DE); an UNKNOWN
     language falls back per-key to EN. The 12 bundled langs (assets/i18n/*.json) each
     match the EN key set and preserve the {area}/{unit} placeholders.
  5. Byte-stability: render twice on the same canonical+language is byte-identical.

Run: python evals/i18n_test.py     (exit 0 on success, 1 on any failure)
Offline by design.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import types
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C          # noqa: E402
import build_dashboard       # noqa: E402
import gate_runner           # noqa: E402
import i18n as I18N          # noqa: E402

PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
      "lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class io_cap:
    """A tiny stdout+stderr capture context manager so a gate's scorecard text can be
    asserted on (the gates print their findings; cmd_i18n's silent-fallback message is
    checked by the eval). `.text` holds the captured output after the `with` block."""
    def __init__(self):
        import io
        self._buf = io.StringIO()
        self.text = ""

    def __enter__(self):
        import contextlib
        self._cm = contextlib.redirect_stdout(self._buf)
        self._cm2 = __import__("contextlib").redirect_stderr(self._buf)
        self._cm.__enter__(); self._cm2.__enter__()
        return self

    def __exit__(self, *a):
        self._cm2.__exit__(*a); self._cm.__exit__(*a)
        self.text = self._buf.getvalue()
        return False


def _canon(language=None):
    meta = {
        "client": "I18nCo",
        "hero": {
            "topbar_meta": "CEE · Test 2026",
            "eyebrow": "Property Shortlist · i18n Test",
            "title_html": "Test logistics <em>options</em> for your next facility.",
            "lede": "Fixture to prove the i18n token round-trip.",
            "footer_copyright": "© 2026 CBRE · i18n test build",
        },
    }
    if language is not None:
        meta["language"] = language
    return {
        "meta": meta,
        "properties": [
            {"id": 1, "country": "HU", "park": "Test Park One", "developer": "DevA",
             "city": "Budapest", "region": "Budapest", "regionCode": "BUD",
             "lat": 47.4979, "lng": 19.0402, "status": "BTS (Lease)",
             "warehouseArea": 40000, "warehouseRent": "€60 / sq m / year",
             "warehouseRentVal": 60.0, "clearHeight": "12 m", "earlyAccess": "2027",
             "motorway": "M0", "photo": PX, "gallery": [PX, PX]},
        ],
        "pois": [{"name": "Hamburg (Port)", "type": "port", "lat": 53.5441,
                  "lng": 9.9685, "country": "DE"}],
        "regions": {"BUD": {"name": "Budapest", "country": "Hungary", "unemployment": 4.0}},
    }


# EN keys consumed in Python only (compute_kpis .format()/phrase), not referenced
# in the template by data-i18n*/T() - they must NOT be flagged as orphans.
# Keys consumed in PYTHON, never by a data-i18n* attribute or a T('...') call in the
# template. The hero_* three are CONFIG TOKENS ({{eyebrow}}/{{title_html}}/{{lede}}) filled
# by build_dashboard._hero_copy, so the template legitimately never references them by key.
PY_ONLY_KEYS = {"kpi_wh_area_sub_fmt", "kpi_rent_sub_fmt", "kpi_regions_sub",
                "hero_eyebrow", "hero_title_html", "hero_lede_fmt"}


def _template_keys(tpl: str):
    """Every i18n key the template references: data-i18n* attribute values + T(...) keys."""
    keys = set()
    for attr in ("data-i18n", "data-i18n-ph", "data-i18n-al"):
        # attribute values are double-quoted in the template
        keys |= set(re.findall(attr + r'="([a-zA-Z0-9_]+)"', tpl))
    # T('key') or T("key")
    keys |= set(re.findall(r"""T\(\s*['"]([a-zA-Z0-9_]+)['"]\s*\)""", tpl))
    return keys


def main() -> int:
    fails: list[str] = []

    def check(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # 1. EN baseline + identity
    check(bool(I18N.EN), "i18n.EN is non-empty")
    check(I18N.TABLE.get("en") is I18N.EN or I18N.TABLE.get("en") == I18N.EN,
          "TABLE['en'] is EN")
    check(I18N.ui_for("en") == I18N.EN, "ui_for('en') == EN")
    # Phase 1b: EN + the 12 bundled languages, loaded from assets/i18n/*.json.
    # `zh` (Simplified Chinese) is the one non-Latin bundled pack - see the SCRIPT SCOPE
    # note in i18n.py. It is held to the SAME structural contract as every other pack by
    # the per-language loop below (exact EN key set, {area}/{unit} preserved, no {{token}}).
    EXPECTED_LANGS = {"en", "de", "fr", "es", "it", "nl", "pl", "pt", "cs", "sk", "hu", "ro",
                      "zh"}
    check(set(I18N.TABLE.keys()) == EXPECTED_LANGS,
          f"TABLE has EN + the 12 bundled languages (got {sorted(I18N.TABLE)})")
    en_keys = set(I18N.EN)
    for lang in sorted(k for k in I18N.TABLE if k != "en"):
        lk = set(I18N.TABLE[lang])
        check(lk == en_keys,
              f"{lang}: key set matches EN exactly (missing {sorted(en_keys - lk)[:4]}, extra {sorted(lk - en_keys)[:4]})")
        check("{area}" in I18N.TABLE[lang].get("kpi_wh_area_sub_fmt", "")
              and "{unit}" in I18N.TABLE[lang].get("kpi_rent_sub_fmt", ""),
              f"{lang}: kpi-sub format strings preserve the {{area}}/{{unit}} placeholders")
        # The hero lede's {count} is filled by .replace() in build_dashboard._hero_copy.
        # Losing it ships a lede with no property count. render() self-heals to EN rather
        # than blocking (cmd_i18n runs post-build, so a block there is an unclearable
        # exit 7 for a bundled pack) - THIS is the dev-time tripwire that catches it.
        check("{count}" in I18N.TABLE[lang].get("hero_lede_fmt", ""),
              f"{lang}: hero_lede_fmt preserves the {{count}} placeholder")
        check("<em>" in I18N.TABLE[lang].get("hero_title_html", "")
              and "</em>" in I18N.TABLE[lang].get("hero_title_html", ""),
              f"{lang}: hero_title_html keeps its <em>...</em> pair (the accent colour)")
    # FIX 4 (hardening for Phase 1b): NO EN value may contain a {{...}} token. ui_json is
    # injected verbatim into the template, so a smuggled {{...}} would survive render() and
    # be mistaken for an unfilled config token (or trip find_leftover_tokens). Lock it now
    # across EVERY language in TABLE so a future translation cannot slip one past the build.
    brace_offenders = sorted(
        f"{lang}:{k}" for lang, tbl in I18N.TABLE.items() for k, v in tbl.items()
        if isinstance(v, str) and C.find_leftover_tokens(v))
    check(not brace_offenders,
          f"no TABLE value contains a {{{{...}}}} token (offenders: {brace_offenders})")

    # 2. Template <-> EN agreement (both directions)
    tpl = C.load_template()
    tkeys = _template_keys(tpl)
    check(bool(tkeys), f"template references i18n keys ({len(tkeys)} found)")
    missing = sorted(k for k in tkeys if k not in I18N.EN)
    check(not missing, f"every template key exists in EN (missing: {missing})")
    orphans = sorted(k for k in I18N.EN if k not in tkeys and k not in PY_ONLY_KEYS)
    check(not orphans, f"EN has no orphan keys beyond the Python-only format/sub keys "
          f"(orphans: {orphans})")
    # the Python-only keys really are absent from the template (consumed by .format)
    check(all(k not in tkeys for k in PY_ONLY_KEYS),
          "the format/sub keys are Python-only (not referenced by data-i18n/T in the template)")

    # 3. render(en) fills the tokens
    en_html, en_tokens = build_dashboard.render(_canon("English"))
    check(not C.find_leftover_tokens(en_html), "no leftover {{token}} after render(en)")
    check(en_tokens.get("locale") == "en-GB", f"locale token == en-GB (got {en_tokens.get('locale')!r})")
    m = re.search(r"const UI = (\{.*?\});\nconst LOCALE = ", en_html, re.DOTALL)
    ui_obj = None
    if m:
        try:
            ui_obj = json.loads(m.group(1))
        except Exception as e:
            fails.append(f"const UI block is not valid JSON: {e}")
    check(ui_obj is not None, "const UI = {...}; block is present and valid JSON")
    check(isinstance(ui_obj, dict) and ui_obj.get("tab_grid") == "Grid",
          "ui_json round-trips and contains tab_grid == 'Grid'")
    check('const LOCALE = "en-GB";' in en_html, 'const LOCALE = "en-GB"; present in output')

    # 4. de is now a REAL bundled translation; an UNKNOWN language falls back to EN.
    check(I18N.normalize_lang("de") == "de" and I18N.normalize_lang("Deutsch") == "de",
          "normalize_lang maps de/Deutsch -> 'de'")
    de_ui = I18N.ui_for("de")
    check(set(de_ui) == set(I18N.EN) and de_ui != I18N.EN,
          "ui_for('de') is a complete REAL translation (full EN key set, values differ)")
    de_html, de_tokens = build_dashboard.render(_canon("de"))
    check(de_tokens.get("locale") == "de-DE", f"de locale token == de-DE (got {de_tokens.get('locale')!r})")
    check('const LOCALE = "de-DE";' in de_html, 'de build renders const LOCALE = "de-DE"')
    check(not C.find_leftover_tokens(de_html), "de build leaves no leftover {{token}}")
    # the chrome is now German: tab_grid is translated, not "Grid"
    md = re.search(r"const UI = (\{.*?\});\nconst LOCALE = ", de_html, re.DOTALL)
    de_tab = None
    if md:
        try:
            de_tab = json.loads(md.group(1)).get("tab_grid")
        except Exception:
            pass
    check(de_tab is not None and de_tab != "Grid",
          f"de build's chrome is translated (tab_grid={de_tab!r}, not 'Grid')")
    # an UNKNOWN language degrades gracefully to the full EN baseline (per-key fallback)
    check(I18N.ui_for("Klingon") == I18N.EN and I18N.ui_for("xx") == I18N.EN,
          "an unknown language falls back to the full EN baseline")
    xx_html, xx_tokens = build_dashboard.render(_canon("Klingon"))
    check(not C.find_leftover_tokens(xx_html) and xx_tokens.get("locale") == "en-GB",
          "unknown-language build succeeds, no leftover token, locale en-GB")

    # explicit meta.locale overrides the language default
    ov_meta = dict(_canon("de")["meta"]); ov_meta["locale"] = "de-AT"
    ov_canon = {**_canon("de"), "meta": ov_meta}
    ov_html, ov_tokens = build_dashboard.render(ov_canon)
    check(ov_tokens.get("locale") == "de-AT", "explicit meta.locale wins over the language default")

    # 5. byte-stability: render twice on same canonical+language is byte-identical
    a = build_dashboard.render(_canon("English"))[0]
    b = build_dashboard.render(_canon("English"))[0]
    check(a == b, "render(en) is byte-identical across two calls (determinism)")
    da = build_dashboard.render(_canon("de"))[0]
    db = build_dashboard.render(_canon("de"))[0]
    check(da == db, "render(de) is byte-identical across two calls (determinism)")

    # ===================================================================== #
    # PHASE 2 - non-bundled-language fallback + the deterministic G-i18n floor
    # ===================================================================== #

    # --- 6. SUPPORTED registry: is_bundled / is_supported / needs_fallback -------
    # a bundled language -> supported + bundled + NOT needing fallback
    check(I18N.is_supported("de") and I18N.is_bundled("de") and not I18N.needs_fallback("de"),
          "de: supported + bundled + not needs_fallback")
    check(I18N.is_supported("English") and I18N.is_bundled("en") and not I18N.needs_fallback("English"),
          "English: supported + bundled(en) + not needs_fallback")
    # a fallback-eligible language (Danish) -> supported, NOT bundled, needs_fallback,
    # and resolves to ITS OWN code (not 'en')
    check(I18N.normalize_lang("Danish") == "da" and I18N.normalize_lang("da") == "da"
          and I18N.normalize_lang("da-DK") == "da",
          "normalize_lang resolves Danish/da/da-DK -> 'da' (its own code, not 'en')")
    check(I18N.is_supported("Danish") and not I18N.is_bundled("da")
          and I18N.needs_fallback("Danish"),
          "Danish: supported + NOT bundled + needs_fallback")
    check(I18N.locale_for("Danish") == "da-DK" and I18N.locale_for("Norwegian") == "nb-NO",
          "locale_for gives the fallback language's BCP-47 (Danish da-DK, Norwegian nb-NO)")
    check(I18N.normalize_lang("Catalan") == "ca" and I18N.needs_fallback("Catalan")
          and I18N.normalize_lang("Galician") == "gl" and I18N.normalize_lang("Maltese") == "mt",
          "more fallback langs resolve to own code (Catalan ca, Galician gl, Maltese mt)")
    # an UNSUPPORTED value (non-Latin / nonsense) -> NOT supported -> 'en', no fallback
    check(not I18N.is_supported("Klingon") and not I18N.is_supported("Greek")
          and not I18N.is_supported("xx") and not I18N.is_supported(""),
          "Klingon/Greek/xx/'' are NOT supported")
    check(I18N.normalize_lang("Klingon") == "en" and not I18N.needs_fallback("Klingon")
          and not I18N.needs_fallback("Greek"),
          "an unsupported language -> 'en', never needs_fallback (renders English)")

    # --- 7. en_sha stability + change-sensitivity --------------------------------
    s1, s2 = I18N.en_sha(), I18N.en_sha()
    check(s1 == s2 and isinstance(s1, str) and len(s1) >= 12,
          f"en_sha() is stable across calls (={s1!r})")
    # simulate an EN change by hashing a perturbed dict the same way en_sha does
    import hashlib as _hl
    base_body = json.dumps(I18N.EN, sort_keys=True, ensure_ascii=True)
    changed = dict(I18N.EN); changed["tab_grid"] = changed["tab_grid"] + "X"
    chg_body = json.dumps(changed, sort_keys=True, ensure_ascii=True)
    h_base = _hl.sha256((I18N.I18N_SCHEMA_VERSION + "\n" + base_body).encode()).hexdigest()[:16]
    h_chg = _hl.sha256((I18N.I18N_SCHEMA_VERSION + "\n" + chg_body).encode()).hexdigest()[:16]
    check(h_base == s1 and h_chg != s1,
          "en_sha() changes when EN changes (stale cache would be re-requested)")

    # --- 8. ui_for(overrides=...) layering --------------------------------------
    # a fake 'da' overrides dict layers over EN; only EN keys honoured; missing -> EN;
    # a leading _en_sha / a stray non-EN key is dropped (here via ui_for's EN filter).
    da_ov = {"tab_grid": "Gitter", "tab_map": "Kort", "_en_sha": s1, "NOT_A_KEY": "junk"}
    u = I18N.ui_for("da", overrides=da_ov)
    check(u.get("tab_grid") == "Gitter" and u.get("tab_map") == "Kort",
          "ui_for(overrides=) layers the fallback values for EN keys")
    check("NOT_A_KEY" not in u and "_en_sha" not in u,
          "ui_for(overrides=) drops non-EN keys (_en_sha / a stray key never enter UI)")
    check(u.get("tab_grid") == "Gitter" and u.get("filter_reset") == I18N.EN["filter_reset"],
          "ui_for(overrides=) falls back per-key to EN for any key the cache omits")
    check(set(u) == set(I18N.EN), "ui_for(overrides=) keeps EXACTLY the EN key set")
    check(I18N.ui_for("da", overrides=None) == I18N.EN
          and I18N.ui_for("da") == I18N.EN,
          "ui_for with NO overrides is the Phase-1 behaviour (da not bundled -> EN)")
    check(I18N.ui_for("en") == I18N.EN, "ui_for('en') still == EN (Phase-1 unchanged)")

    # --- 9. load_fallback_cache --------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "da.json"
        good.write_text(json.dumps({"_en_sha": s1, "tab_grid": "Gitter", "tab_map": "Kort"}),
                        encoding="utf-8")
        lc = I18N.load_fallback_cache(good)
        check(isinstance(lc, dict) and lc.get("tab_grid") == "Gitter" and "_en_sha" not in lc,
              "load_fallback_cache reads the chrome dict and strips the _* meta key")
        bad = Path(td) / "bad.json"; bad.write_text("{ not json", encoding="utf-8")
        check(I18N.load_fallback_cache(bad) is None
              and I18N.load_fallback_cache(Path(td) / "missing.json") is None,
              "load_fallback_cache returns None on a corrupt / missing file (graceful)")

    # --- 10. merge bakes meta.ui_overrides from the cache (EN-keys only) ----------
    import merge as MERGE
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "da.json"
        # a realistic cache: full EN keys translated (here: prefixed), + the _en_sha meta,
        # + one stray non-EN key that MUST be dropped by the bake.
        fake = {k: ("DA_" + v if isinstance(v, str) else v) for k, v in I18N.EN.items()}
        fake["kpi_wh_area_sub_fmt"] = "{area} DA"     # keep the placeholder intact
        fake["kpi_rent_sub_fmt"] = "DA {unit}"
        fake["_en_sha"] = s1
        fake["STRAY_DATA_KEY"] = "must not enter canonical"
        cache.write_text(json.dumps(fake, ensure_ascii=False), encoding="utf-8")
        # merge.main bakes meta via its args; we exercise the bake unit directly through
        # the documented contract (load_fallback_cache + EN filter) to keep this offline.
        loaded = I18N.load_fallback_cache(cache)
        baked = {k: v for k, v in loaded.items() if k in I18N.EN}
        check("_en_sha" not in baked and "STRAY_DATA_KEY" not in baked,
              "merge bake drops _en_sha + any non-EN/DATA key")
        check(set(baked) == set(I18N.EN), "merge bake keeps EXACTLY the EN key set")

    # --- 11. THE CRUX: render() with meta.ui_overrides is byte-stable AND ----------
    # ---     validate-html (which re-runs render) PASSES byte-identity ------------
    fb_overrides = {k: ("DA_" + v if isinstance(v, str) else v) for k, v in I18N.EN.items()}
    fb_overrides["kpi_wh_area_sub_fmt"] = "{area} DA"
    fb_overrides["kpi_rent_sub_fmt"] = "DA {unit}"
    fb_canon = _canon("Danish")
    fb_canon["meta"]["ui_overrides"] = fb_overrides
    h1, t1 = build_dashboard.render(fb_canon)
    h2, _ = build_dashboard.render(fb_canon)
    check(not C.find_leftover_tokens(h1), "fallback render: no leftover {{token}}")
    check(h1 == h2, "fallback render (meta.ui_overrides) is byte-identical across two calls")
    check(t1.get("locale") == "da-DK", f"fallback locale token == da-DK (got {t1.get('locale')!r})")
    fb_ui = None
    mfb = re.search(r"const UI = (\{.*?\});\nconst LOCALE = ", h1, re.DOTALL)
    if mfb:
        try:
            fb_ui = json.loads(mfb.group(1))
        except Exception:
            pass
    check(fb_ui is not None and fb_ui.get("tab_grid") == "DA_Grid",
          "fallback const UI carries the OVERRIDDEN values (tab_grid='DA_Grid')")
    check(fb_ui is not None and "{area}" in str(fb_ui.get("kpi_wh_area_sub_fmt", "")),
          "fallback const UI preserves the {area} placeholder")

    # validate-html re-runs render(canonical) and asserts byte-identity. Prove the
    # fallback (ui_overrides on canonical) survives that gate: write the canonical + the
    # rendered HTML to a temp dir and run cmd_validate_html exactly as the post-build gate does.
    def _run_gate(fn, html_text, canon_obj):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "canonical.json"; cp.write_text(json.dumps(canon_obj), encoding="utf-8")
            hp = Path(td) / "built.html"; hp.write_text(html_text, encoding="utf-8")
            args = types.SimpleNamespace(html=str(hp), canonical=str(cp))
            buf = io_cap()
            with buf:
                rc = fn(args)
            return rc, buf.text

    vh_rc, _ = _run_gate(gate_runner.cmd_validate_html, h1, fb_canon)
    check(vh_rc == 0, "validate-html PASSES byte-identity on a canonical WITH meta.ui_overrides (the crux)")
    # negative twin: a tampered fallback HTML (one chrome byte changed) MUST fail validate-html,
    # so the crux test distinguishes a real byte-identity gate from a no-op (closes a tautology gap).
    vh_bad, _ = _run_gate(gate_runner.cmd_validate_html,
                          h1.replace("DA_Grid", "TAMPERED", 1), fb_canon)
    check(vh_bad != 0,
          "validate-html FAILS a tampered fallback HTML (the byte-identity gate bites WITH ui_overrides)")

    # --- 12. the deterministic G-i18n floor: PASS + FAIL cases -------------------
    # PASS on a complete EN build
    en_canon = _canon("English"); en_html2, _ = build_dashboard.render(en_canon)
    rc, _ = _run_gate(gate_runner.cmd_i18n, en_html2, en_canon)
    check(rc == 0, "G-i18n floor PASSES a complete EN build")
    # PASS on a real bundled lang (de)
    de_canon = _canon("de"); de_html2, _ = build_dashboard.render(de_canon)
    rc, _ = _run_gate(gate_runner.cmd_i18n, de_html2, de_canon)
    check(rc == 0, "G-i18n floor PASSES a real bundled language (de)")
    # PASS on the fallback build (ui_overrides)
    rc, _ = _run_gate(gate_runner.cmd_i18n, h1, fb_canon)
    check(rc == 0, "G-i18n floor PASSES the fallback build (meta.ui_overrides)")
    # FAIL: const UI missing a key (doctor the HTML)
    doctored = h1.replace('"tab_grid":"DA_Grid",', "", 1)
    rc, _ = _run_gate(gate_runner.cmd_i18n, doctored, fb_canon)
    check(rc != 0, "G-i18n floor FAILS a const UI missing an EN key")
    # FAIL: an unfilled {{token}} smuggled into a UI value
    tok_over = dict(fb_overrides); tok_over["empty_title"] = "{{not_filled}}"
    tok_canon = _canon("Danish"); tok_canon["meta"]["ui_overrides"] = tok_over
    tok_html, _ = build_dashboard.render(tok_canon, strict=False)
    rc, _ = _run_gate(gate_runner.cmd_i18n, tok_html, tok_canon)
    check(rc != 0, "G-i18n floor FAILS a UI value carrying an unfilled {{token}}")
    # FAIL: a non-EN language EXPECTED to be localised that silently equals EN. Build a
    # canonical with meta.ui_overrides == EN itself (a translation that collapsed to EN).
    silent_canon = _canon("Danish"); silent_canon["meta"]["ui_overrides"] = dict(I18N.EN)
    silent_html, _ = build_dashboard.render(silent_canon)
    rc, txt = _run_gate(gate_runner.cmd_i18n, silent_html, silent_canon)
    check(rc != 0 and "silently fell back" in txt,
          "G-i18n floor FAILS an expected-localised language that silently equals EN")
    # FAIL: a malformed LOCALE (explicit junk meta.locale)
    badloc_canon = _canon("de"); badloc_canon["meta"]["locale"] = "not a locale!"
    badloc_html, _ = build_dashboard.render(badloc_canon)
    rc, _ = _run_gate(gate_runner.cmd_i18n, badloc_html, badloc_canon)
    check(rc != 0, "G-i18n floor FAILS a malformed LOCALE tag")
    # an UNSUPPORTED language correctly rendered in EN must PASS (EN is the right answer,
    # the silent-fallback check is skipped for it)
    unsup_canon = _canon("Klingon"); unsup_html, _ = build_dashboard.render(unsup_canon)
    rc, _ = _run_gate(gate_runner.cmd_i18n, unsup_html, unsup_canon)
    check(rc == 0, "G-i18n floor PASSES an unsupported language (correctly EN, no silent-fallback flag)")

    # --- 13. schema accepts meta.ui_overrides ------------------------------------
    sc_errs = C.validate_canonical(fb_canon)
    check(not any("ui_overrides" in str(e) for e in sc_errs),
          f"canonical.schema.json accepts meta.ui_overrides (errs: {[e for e in sc_errs if 'ui_overrides' in str(e)][:2]})")

    # --- 14. HERO COPY is table-driven, localised, and verbatim-respecting -------
    # Before this, merge.load_hero hard-coded the eyebrow/headline/lede in ENGLISH, so the
    # LARGEST text on the page was English in all 12 supported languages, and a non-blank
    # eyebrow was force-prefixed with "Property Shortlist · " via an ASCII substring test
    # (making a non-Latin eyebrow impossible). Tests 14b and 14d FAIL against that code.
    def _blank_hero(language):
        c = _canon(language)
        c["meta"]["hero"] = {**c["meta"]["hero"], "eyebrow": "", "title_html": "", "lede": ""}
        return c

    # (a) a BLANK hero picks up the table default rather than rendering empty
    bh_canon = _blank_hero("English")
    bh_html, bh_tok = build_dashboard.render(bh_canon)
    check(bh_tok["eyebrow"] == I18N.EN["hero_eyebrow"]
          and bh_tok["title_html"] == I18N.EN["hero_title_html"],
          f"blank hero falls back to the i18n default (got {bh_tok['eyebrow']!r})")
    check("{count}" not in bh_tok["lede"] and "1" in bh_tok["lede"],
          f"blank lede fills {{count}} from the property count (got {bh_tok['lede'][:60]!r})")
    check(not C.find_leftover_tokens(bh_html),
          "a blank-hero build leaves no unfilled {{token}}")

    # (b) VERBATIM: a non-Latin eyebrow ships exactly, with NO English prefix composed on
    zh_canon = _blank_hero("Chinese")
    zh_canon["meta"]["hero"]["eyebrow"] = "物业初选名单"
    _, zh_tok = build_dashboard.render(zh_canon)
    # NB: ascii() not !r - a non-ASCII character in a check LABEL crashes the whole suite on
    # a cp1252 console even when every assertion passes (house rule, learned the hard way).
    check(zh_tok["eyebrow"] == "物业初选名单",
          f"a non-Latin eyebrow ships VERBATIM, unprefixed (got {ascii(zh_tok['eyebrow'])})")
    check("Property Shortlist" not in zh_tok["eyebrow"],
          "the old ASCII 'Property Shortlist · ' prefix is gone")

    # (c) a broker-authored value still wins over the localised default, in any language
    auth = _blank_hero("de")
    auth["meta"]["hero"]["title_html"] = "Mein <em>eigener</em> Titel."
    _, auth_tok = build_dashboard.render(auth)
    check(auth_tok["title_html"] == "Mein <em>eigener</em> Titel.",
          "a broker-authored title_html ships verbatim, not the table default")

    # (d) SELF-HEAL: a pack whose hero_lede_fmt lost {count} must still state the count,
    # never ship a countless lede. cmd_i18n runs POST-build, so a block there would be an
    # unclearable exit 7 for a bundled pack - the graceful path is the design.
    heal = _blank_hero("Danish")
    # a REALISTIC translated pack (every value differs from EN, so the separate
    # silent-fallback clause is satisfied) whose hero_lede_fmt has lost its {count}
    heal["meta"]["ui_overrides"] = {**{k: f"DA_{v}" for k, v in I18N.EN.items()},
                                    "hero_lede_fmt": "Ingen antal her."}
    heal_html, heal_tok = build_dashboard.render(heal)
    check("1" in heal_tok["lede"] and heal_tok["lede"] != "Ingen antal her.",
          f"a hero_lede_fmt missing {{count}} self-heals to the EN default "
          f"(got {heal_tok['lede'][:50]!r})")
    rc_heal, out_heal = _run_gate(gate_runner.cmd_i18n, heal_html, heal)
    check(rc_heal == 0, "the {count} loss is ADVISORY - cmd_i18n still passes (no exit-7 deadlock)")
    check("[note]" in out_heal and "hero_lede_fmt" in out_heal,
          "cmd_i18n prints a [note] naming hero_lede_fmt")

    # (e) the localised default is byte-stable across two renders (validate-html's premise)
    check(build_dashboard.render(_blank_hero("de"))[0]
          == build_dashboard.render(_blank_hero("de"))[0],
          "a blank-hero localised build is byte-identical across two renders")

    # (f) CJK FALLBACK (B29, template v27). The CBRE faces are Latin-only and embedded as
    # base64 woff2, so before this a zh dashboard resolved every ideograph through the
    # browser's per-glyph last-resort font. The added families must be SYSTEM names: the
    # dashboard is a single portable file and may never fetch a font.
    tpl = (Path(__file__).resolve().parent.parent / "assets"
           / "dashboard_template.html").read_text(encoding="utf-8", errors="replace")
    _css = tpl[tpl.find("--font-display"):tpl.find("--font-mono")]
    for fam in ("PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC"):
        check(fam in _css, f"the CJK stack names {fam}")
    check("--font-display" in _css and "PingFang SC" in _css.split("--font-body")[0],
          "the DISPLAY stack has a CJK fallback too (not just body)")
    check(_css.split("--font-body")[0].rstrip().rstrip(";").endswith("serif")
          and _css.rstrip().rstrip(";").endswith("sans-serif"),
          "both stacks still END in a generic keyword")
    for tc in ("PingFang TC", "Microsoft JhengHei", "Yu Gothic", "Malgun Gothic"):
        check(tc in _css, f"{tc} is pre-named so the next non-Latin language costs no bump")
    # self-contained: no font may be fetched. The only legitimate url() in the chrome is a
    # data: URI, and @font-face must not have grown a remote src.
    import re as _re
    # data: is inline; a bare '#...' is a same-document fragment (e.g. the legacy IE
    # behavior url(#default#VML) shim) and fetches nothing.
    _urls = [u for u in _re.findall(r"url\(\s*['\"]?([^'\")]+)", tpl)
             if not u.startswith(("data:", "#"))]
    check(not _urls, f"no external font/asset URL in the template {ascii(_urls[:3])}")
    check("@import" not in tpl, "no CSS @import (it would fetch at render time)")
    # a Latin build must be unaffected in practice: the CJK names sit in the TAIL
    _body = _css.split("--font-body", 1)[1] if "--font-body" in _css else ""
    check(_body.find("Calibre") < _body.find("PingFang SC"),
          "the CBRE face still wins for Latin (CJK names are tail placement)")

    if fails:
        print(f"\nI18N TEST: FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nI18N TEST: PASS (EN complete, template<->EN lockstep, 12 bundled langs "
          "key-complete + placeholders, tokens fill, unknown lang -> EN, byte-stable; "
          "Phase 2: SUPPORTED/fallback resolution, en_sha, ui_for(overrides=), "
          "load_fallback_cache, merge bake, validate-html byte-identity WITH ui_overrides, "
          "G-i18n floor PASS/FAIL cases, schema accepts ui_overrides; hero copy "
          "table-driven + verbatim + {count} self-heal)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
