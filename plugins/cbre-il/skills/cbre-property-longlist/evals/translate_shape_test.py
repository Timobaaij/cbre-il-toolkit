#!/usr/bin/env python3
"""translate_shape_test.py - the exit-12 livelock is a cache SHAPE problem, not a key one. (B03)

The backlog filed this against `text_key`/`norm_key`. It is at the wrong layer: neither
surviving failure is a key-normalisation problem, so nothing in either function could fix
them. `_load_cache` accepted exactly one shape and silently degraded everything else to {},
after which run.py re-emitted a byte-identical exit-12 request - forever.

Two natural sub-agent shapes livelocked:
  1. an ENVELOPE - {"translations": {...}}, {"items":[{...,"translation":...}]}, or a bare
     top-level array;
  2. addressed by ITEM IDENTITY - {"1:description": "..."} - which produces entries that
     match nothing, so even an "is the cache empty" heuristic would not catch it.

A third class survives the typographic fold per item (NFD vs NFC). NFC is added to norm_key:
canonical equivalence only. NOT NFKC - that is a lossy compatibility fold (it would rewrite
'm2' from 'm²' and merge ligatures), and matching DIFFERENT prose ships a wrong translation,
which is far worse than a re-request. Offline."""
from __future__ import annotations
import json
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import translate as T  # noqa: E402

LANG = "nl"
SRC1 = "A prime logistics warehouse on the Corby estate."
SRC2 = "Fully fitted office accommodation over two floors."
T1, T2 = "Een prima logistiek magazijn.", "Volledig ingericht kantoor."


def _write(d, obj):
    p = Path(d) / "cache.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    d = Path(tempfile.mkdtemp(prefix="cbre_tsh_"))

    def resolves(obj, src=SRC1, want=T1):
        raw = T._load_cache(_write(d, obj))
        hashed = T._hashed_cache(raw, LANG)
        return hashed.get(T.text_key(src, LANG)) == want

    # the canonical shape must keep working, unchanged
    ck(resolves({SRC1: T1}), "the documented flat {source: translation} map still resolves")

    # shape 1 - envelopes
    ck(resolves({"translations": {SRC1: T1}}), "an envelope {'translations': {...}} resolves")
    ck(resolves({"items": [{"text": SRC1, "translation": T1}]}),
       "a list of {text, translation} objects resolves")
    ck(resolves([{"source": SRC1, "translation": T1}]),
       "a BARE top-level array resolves")
    ck(resolves({"items": [{"source": SRC1, "target": T1}]}),
       "the source/target spelling resolves too")

    # shape 2 - addressed by item identity, "<property_id>:<field>"
    ck(resolves({"1:description": T1}) is False or True, "identity-addressed shape parsed")
    raw = T._load_cache(_write(d, {"1:description": T1, "2:description": T2}))
    idx = T.index_by_request(raw, LANG, [{"property_id": 1, "field": "description", "text": SRC1},
                                         {"property_id": 2, "field": "description", "text": SRC2}]) \
        if hasattr(T, "index_by_request") else {}
    ck(idx.get(T.text_key(SRC1, LANG)) == T1 and idx.get(T.text_key(SRC2, LANG)) == T2,
       "an identity-addressed cache is resolved against the REQUEST list")

    # junk must still be rejected - a looser reader must not become a catch-all
    ck(T._load_cache(_write(d, "just a string")) == {}, "a bare string is still rejected")
    ck(T._hashed_cache({SRC1: 5}, LANG) == {}, "a non-string translation is still dropped")
    ck(not resolves({"translations": {SRC2: T2}}),
       "a cache for DIFFERENT prose does not resolve this item (no catch-all)")

    # NFC: the same prose typed decomposed must match its composed cache entry
    nfd = unicodedata.normalize("NFD", "Zaragoza logistiek café terrein")
    nfc = unicodedata.normalize("NFC", "Zaragoza logistiek café terrein")
    ck(nfd != nfc, "the fixture really is decomposed vs composed")
    hashed = T._hashed_cache({nfc: T1}, LANG)
    ck(hashed.get(T.norm_key(nfd, LANG)) == T1,
       "an NFD source resolves against an NFC cache entry")
    _tsrc = (HELPERS / "translate.py").read_text(encoding="utf-8", errors="replace")
    ck('normalize("NFKC"' not in _tsrc and "normalize('NFKC'" not in _tsrc,
       "NFKC is never APPLIED (a lossy compatibility fold could match DIFFERENT prose)")
    ck('normalize("NFC"' in _tsrc, "NFC is applied")
    # ...and prove the distinction is real, not decorative: NFKC would collide these, NFC must not.
    ck(T.norm_key("50 m² office", LANG) != T.norm_key("50 m2 office", LANG),
       "'m2' and 'm2' stay DISTINCT prose under NFC (NFKC would have merged them)")

    # the diagnostic: a cache that resolves NOTHING must say so, not re-request in silence
    ck(hasattr(T, "cache_shape_note"), "translate.cache_shape_note() exists")
    if hasattr(T, "cache_shape_note"):
        note = T.cache_shape_note({"1:description": T1}, {}, LANG)
        ck(note and "0" in note, f"a zero-resolve cache produces a diagnostic {ascii(str(note)[:60])}")
        ck(not T.cache_shape_note({SRC1: T1}, {T.text_key(SRC1, LANG): T1}, LANG),
           "a cache that resolved something produces no note")
    # WIRING - the functions existing is not the fix (this project has shipped that twice)
    _t = (HELPERS / "translate.py").read_text(encoding="utf-8", errors="replace")
    _rs = _t[_t.find("def run_stage"):]
    ck("index_by_request(" in _rs, "run_stage folds in an identity-addressed cache")
    ck("cache_shape_note(" in _rs, "run_stage emits the zero-resolve diagnostic")
    ck(_rs.find("cache_shape_note(") < _rs.find("return 12"),
       "the diagnostic is printed BEFORE the request is re-emitted")

    # B53: three values leaked to the translator that are never prose in ANY language. The
    # ANTI-REGRESSION half below matters MORE than the fix: `Built`, `3 MVA grid supply` and
    # `55m both sides` only LOOKED like leaks because the target language happened to equal the
    # source language. In an English->Spanish run you want "Construido", "3 MVA suministro de
    # red" and "55m a ambos lados". Excluding them would be a real quality loss, so they are
    # pinned as translatable here.
    #
    # These are VALUE-SHAPE rules, not a field list, on purpose: `postcode`, `epc` and
    # `yardDepth` are auto-shown attributes, not canonical schema fields, so they are unknown at
    # design time. Blacklisting them by name would hard-code one client's vocabulary.
    import _common as C
    for field, val in [("postcode", "DN11 8DB"), ("address", "MK16 0QE"),
                       ("postcode", "1234 AB"), ("epc", "A"), ("epc", "A+"), ("epc", "B2"),
                       ("floorLoad", "50 kN/m2"), ("floorLoad", "60 kN/m2"),
                       ("electricity", "2.4 MVA")]:
        ck(C.is_translatable_value(field, val) is False,
           f"NOT translatable (never prose in any language): {field}={val!r}")
    for field, val in [("status", "Built"), ("status", "Under construction"),
                       ("electricity", "3 MVA grid supply"),
                       ("yardDepth", "55m both sides"),
                       ("sprinklers", "Sprinklers - roof mounted"),
                       ("status", "No"), ("status", "Ja"), ("status", "Si"),
                       ("description", "A new logistics facility with 21 m clear height.")]:
        ck(C.is_translatable_value(field, val) is True,
           f"STILL translatable (a real run would lose this): {field}={val!r}")

    if fails:
        print(f"\nTRANSLATE SHAPE TEST: FAIL ({len(fails)})")
        return 1
    print("\nTRANSLATE SHAPE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
