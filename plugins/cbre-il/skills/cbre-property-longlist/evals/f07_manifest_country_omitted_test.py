#!/usr/bin/env python3
"""f07_manifest_country_omitted_test.py - a deck entry OMITS `country` when it is unknown, instead
of passing the `??` sentinel to the reader. (F7, manifest half)

THE DEFECT. run.py hands interpret_prep `cl.get("country") or "??"`, and the deck entry wrote that
straight into the manifest as `"country": "??"`. Five of seven readers on a live run said,
unprompted, that the manifest gave `??` and derived the country from the page themselves; across
seven decks that produced three different spellings and cost one broker question. A sentinel
where ABSENCE is meant makes every agent recognise and reason about it. An absent key is
unambiguous and needs no rule.

WHAT THIS PINS (interpret_prep):
  1. a fresh TEXT entry carries `country` only when the caller knows it - never `??`, never null;
  2. the RESUME path strips a cached entry's pre-F7 `"country": "??"` (a warm work dir) and
     re-states the country only when known;
  3. the router's RASTER branch applies the same rule to what vision_prep returns;
  4. the sentinel passthrough literals are gone from the source, so a revert is visible.
Offline; uses a byte-garbage "deck" so no renderer is needed (every image step is a guarded
no-op, exactly as on a renderer-less host).
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import interpret_prep as IP  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


TEXT = ["Example Park\nUnit 7\nWarehouse 12,500 sq m\nClear height 12 m\n" * 3]


def main() -> int:
    print("== 1. fresh text entry ==")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        deck = out / "deck.pdf"
        deck.write_bytes(b"not a real pdf, and that is the point")
        for given, expect in (("??", None), ("", None), (None, None), ("?", None), ("GB", "GB"), (" pl ", "pl")):
            e = IP._text_deck_entry(deck, "RegionLabel", given, TEXT, "pdf", out)
            if expect is None:
                ck("country" not in e, f"country={given!r}: the key is ABSENT (not the sentinel, not null)")
            else:
                ck(e.get("country") == expect, f"country={given!r}: the key is present and stripped ({e.get('country')!r})")
        e = IP._text_deck_entry(deck, "RegionLabel", "??", TEXT, "pdf", out)
        ck(e.get("mode") == "text" and e.get("cluster_label") == "RegionLabel" and e.get("pages"),
           "the rest of the entry is unchanged by the country rule")

        print("== 2. resume path strips a cached sentinel ==")
        cached = {"source_file": deck.name, "source_type": "pdf", "cluster_label": "RegionLabel",
                  "cluster_label_is_routing_only": True, "country": "??", "mode": "text",
                  "pages": [{"page_no": 0, "locator": "page 1", "text": TEXT[0], "candidates": [],
                             "candidates_sheet": None, "render": None}]}
        st = deck.stat()
        key = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "schema": IP.PREP_SCHEMA}
        IP._stamp_path(out, deck).write_text(json.dumps({"key": key, "entry": cached}), encoding="utf-8")
        served = IP.prepare(deck, "RegionLabel", "??", out, resume=True)
        ck(served.get("pages") == cached["pages"], "the cached entry was served (resume hit), not recomputed")
        ck("country" not in served, "a warm work dir's cached `\"country\": \"??\"` is dropped on resume")
        served2 = IP.prepare(deck, "RegionLabel", "DE", out, resume=True)
        ck(served2.get("country") == "DE", "a known country is re-stated on the reused entry")

        print("== 3. raster branch applies the same rule ==")
        orig = IP.VP.prepare
        try:
            IP.VP.prepare = lambda p, r, c, o, **k: {"source_file": Path(p).name, "source_type": "pdf",
                                                    "region": r, "country": c,
                                                    "pages": [{"page_no": 0, "locator": "page 1", "image": None}]}
            r1 = IP.prepare(out / "other.pdf", "R", "??", out, resume=False)
            ck(r1.get("mode") == "raster" and "country" not in r1,
               "an unopenable deck routes to raster and its vision_prep entry loses the `??`")
            r2 = IP.prepare(out / "other.pdf", "R", "FR", out, resume=False)
            ck(r2.get("country") == "FR", "a known country survives the raster branch")
        finally:
            IP.VP.prepare = orig

    print("== 4. the passthrough literals are gone ==")
    src = (HELPERS / "interpret_prep.py").read_text(encoding="utf-8")
    ck('"country": country' not in src and 'entry["country"] = country' not in src,
       "no unconditional `country` passthrough remains in interpret_prep.py")
    ck("def _country_kv" in src, "the absence rule has ONE home (_country_kv)")

    print("STATUS:", "ALL-PASS" if not FAILS else "BLOCKED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
