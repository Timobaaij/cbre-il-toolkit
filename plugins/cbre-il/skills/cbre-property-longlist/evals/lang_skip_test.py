#!/usr/bin/env python3
"""The exit-12 round must not fire when the data is already in the dashboard's language. (B54)

A 12-property English run with an English dashboard queued 53 items for an English-to-English
translation - a full agent dispatch plus a shell round-trip, on the most common configuration
there is. The signal is cheap: the interpretation agent is reading the deck anyway, so it
declares `__meta.source_lang` and Python does the rest.

DEGRADATION IS THE POINT. No declaration anywhere, or ANY declaration that differs from the
target, must behave exactly as before - a skip that fires when it should not would ship
untranslated data under a translated dashboard. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M    # noqa: E402
import run as R      # noqa: E402

FAILURES = []


def ck(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def canon(langs):
    return {"meta": ({"sourceLanguages": langs} if langs else {}), "properties": []}


print("merge.collect_source_languages - the LLM declares, Python counts:")
ck("counts declarations, case-folded",
   M.collect_source_languages([{"__meta": {"source_lang": "en"}},
                               {"__meta": {"source_lang": "EN"}},
                               {"__meta": {}}, {"nope": 1}]) == {"en": 2})
ck("a mixed corpus keeps both codes",
   M.collect_source_languages([{"__meta": {"source_lang": "en"}},
                               {"__meta": {"source_lang": "pl"}}]) == {"en": 1, "pl": 1})
ck("no declaration -> empty dict (the meta key is then omitted entirely)",
   M.collect_source_languages([{"__meta": {}}]) == {})
ck("a non-string declaration is ignored",
   M.collect_source_languages([{"__meta": {"source_lang": 7}}]) == {})
ck("a blank declaration is ignored",
   M.collect_source_languages([{"__meta": {"source_lang": "   "}}]) == {})
ck("an empty record list is safe", M.collect_source_languages([]) == {})

print("\nrun._lang_skip - skip ONLY when every declared language is the target:")
ck("all-en + target en -> SKIP", R._lang_skip(canon({"en": 11}), "en") is True)
ck("target is case-folded too", R._lang_skip(canon({"en": 3}), "EN") is True)
ck("mixed en/pl + target en -> DO NOT skip",
   R._lang_skip(canon({"en": 9, "pl": 2}), "en") is False)
ck("all-es + target en -> DO NOT skip", R._lang_skip(canon({"es": 11}), "en") is False)
ck("nothing declared -> DO NOT skip (today's behaviour)",
   R._lang_skip(canon({}), "en") is False)
ck("missing meta -> DO NOT skip", R._lang_skip({"meta": {}}, "en") is False)
ck("a garbage sourceLanguages value -> DO NOT skip",
   R._lang_skip({"meta": {"sourceLanguages": "en"}}, "en") is False)
ck("an empty target never skips", R._lang_skip(canon({"en": 3}), "") is False)
ck("a None canonical is safe", R._lang_skip(None, "en") is False)

print("\nWiring - merge stores it conditionally, run.py consults it before emitting:")
m_src = (ROOT / "helpers" / "merge.py").read_text(encoding="utf-8")
ck("merge writes meta.sourceLanguages only when something declared",
   'if _src_langs:' in m_src and 'meta["sourceLanguages"] = _src_langs' in m_src)
r_src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
ck("run.py checks _lang_skip on the exit-12 path", "_lang_skip(_canon_obj" in r_src)
ck("...and drops the documented SKIP sentinel rather than inventing a new mechanism",
   'data_translate.SKIP' in r_src)
ck("...and the note DISCLOSES the tracker-inherits assumption",
   "assumed to share it" in r_src)
ck("the contract asks the agent for the declaration",
   "__meta.source_lang" in (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8"))

print()
if FAILURES:
    print(f"LANG SKIP TEST: FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("LANG SKIP TEST: PASS (skips only on a declared match; degrades to today otherwise)")
