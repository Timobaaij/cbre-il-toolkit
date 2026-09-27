#!/usr/bin/env python3
"""reader_rules_p1_test.py - the reader-contract rules added on the 2026-09-26 test run, pinned in
BOTH reader prompts' common files and in the rendered contract (the file readers no longer open
whole), plus the validator half of each new optional flag.

THE DEFECTS (one live 22-deck run):
  3.2a  10 of 12 broker questions were per-floor office doubts whose natural answer, "sum them",
        was not an option: the reader could not say "these options are PARTS of one quantity".
        -> doubt key `combinable: true` (Python offers the sum; the reader never writes it).
  3.5b  readers shipped `levelAccessDoors` as an open key while `overheadDoors` shipped "absent
        in all sources": no door rule anywhere, in any language. -> door rule + registry hints.
  3.6a  four printed compartment areas lived only inside a doubt's options, so no card, ledger
        row or gate ever saw them. -> every offered figure is ALSO a field.
  3.7a  (REDUCED by the SPEC) a lone printed whole-building total: ship it as warehouseArea as
        printed AND record it as the stated total; never net the office yourself - Python raises
        the basis question. No `totalBuildingArea`, never "leave warehouseArea absent".
  3.10a a LET unit shipped as an availability card: no way to say "the source says not
        available". -> `__meta.not_an_option: true`, status verbatim, broker decides.
  3.18  a count doubt's answer "as shipped" could not be recognised because `default` was free
        prose. -> `default` copied VERBATIM from `options` (REQUIRED on a count doubt).
  3.20  the contract said a co-claimed page nobody anchors is dropped from every carousel; the
        runtime now SHARES it (never the Site Plan slot), and the contract says so.

Run: python evals/reader_rules_p1_test.py"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import prompts_render as PR  # noqa: E402
import interpret_prep as IP  # noqa: E402
import vision_validate as VV  # noqa: E402


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def _commons(work: Path) -> dict:
    (work / "vision").mkdir(exist_ok=True)
    reg = IP.reader_field_registry(["park", "loadingDocks", "overheadDoors", "warehouseArea"])
    (work / "vision" / "manifest.json").write_text(
        json.dumps({"decks": [], "fields": reg}), encoding="utf-8")
    out = {}
    for kind in ("reader-text", "reader-raster"):
        PR.write_prompts(work, [(kind, "deckA_vision", {
            "DECK_NAME": "deckA.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": 3, "COUNTRY": "XX",
            "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
            "OUTPUT_PATH": str(work / "extract" / "deckA_vision.json")})])
        out[kind] = (work / "prompts" / PR.COMMON_DIRNAME / f"{kind}.md").read_text(
            encoding="utf-8")
    return out


def _validate(work: Path, records: list) -> tuple:
    (work / "vision").mkdir(exist_ok=True)
    (work / "extract").mkdir(exist_ok=True)
    (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [
        {"source_file": "deckA.pdf", "cluster_label": "deckA", "mode": "text",
         "output": "work/extract/deckA_vision.json",
         "pages": [{"page_no": 0}, {"page_no": 1}]}]}), encoding="utf-8")
    for old in (work / "extract").glob("*_vision.json"):
        old.unlink()
    (work / "extract" / "deckA_vision.json").write_text(json.dumps(records), encoding="utf-8")
    return VV.validate(work)


def _rec(**meta) -> dict:
    m = {"source_file": "deckA.pdf", "source_type": "pdf", "page_no": 0,
         "image_pages": [], "plan_page": None, "prov": {"park": "page 1 (text interpretation)"}}
    m.update(meta)
    return {"park": "Alpha Park", "__meta": m}


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    text_body, _ = PR.reader_contract("text")
    raster_body, _ = PR.reader_contract("raster")
    contract_raw = PR.CONTRACT_FILE.read_text(encoding="utf-8")
    schema = json.loads(PR.RECORD_SCHEMA_FILE.read_text(encoding="utf-8-sig"))
    meta_props = schema["properties"]["__meta"]["properties"]

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        commons = _commons(work)
        places = {"common reader-text": commons["reader-text"],
                  "common reader-raster": commons["reader-raster"],
                  "text contract": text_body or "", "raster contract": raster_body or ""}

        def everywhere(needle: str, label: str):
            for name, txt in places.items():
                check(needle in _flat(txt), f"{label}: {name} carries {needle!r}")

        # 3.2a combinable
        everywhere('"combinable": true', "3.2a")
        check("combinable" in meta_props["doubts"]["description"],
              "3.2a: record_schema's doubts description names `combinable`")
        # 3.5b doors
        for kind in ("reader-text", "reader-raster"):
            c = commons[kind]
            check("- `overheadDoors`: string. COUNT of doors a vehicle drives THROUGH" in c
                  and "- `loadingDocks`: string. COUNT of DOCK-LEVEL loading positions" in c,
                  f"3.5b: {kind} registry renders both door hints")
            check("Doors: level-access / ground-level / drive-in / roller-shutter doors" in _flat(c),
                  f"3.5b: {kind} carries the door reminder")
        for n in ("overheadDoors", "loadingDocks", "`loadingDoors`", "levelAccessDoors"):
            check(n in (text_body or "") and n in (raster_body or ""),
                  f"3.5b: both contract renders carry {n!r}")
        reg = IP.reader_field_registry(["loadingDocks", "overheadDoors"])
        check(all("format" in e and e["format"].isascii() for e in reg),
              "3.5b: both hints are on the registry and ASCII")
        # 3.6a
        everywhere("EVERY FIGURE YOU OFFER IN A DOUBT IS ALSO DATA", "3.6a")
        # 3.7a (reduced)
        everywhere("A LONE TOTAL IS SHIPPED AS PRINTED", "3.7a")
        everywhere("statedTotalArea", "3.7a")
        for name, txt in list(places.items()) + [("interpretation.md", contract_raw)]:
            check("totalBuildingArea" not in txt and "warehouseArea ABSENT" not in txt,
                  f"3.7a (reduced): {name} never asks for totalBuildingArea / an absent "
                  f"warehouseArea")
        check("never subtract the office" in _flat(commons["reader-text"]).lower()
              and "Never subtract the office" in _flat(text_body or ""),
              "3.7a: the reader is told never to net the office itself")
        # 3.10a
        everywhere('"not_an_option": true', "3.10a")
        na = meta_props.get("not_an_option") or {}
        check(na.get("type") == "boolean" and "let" in na.get("description", ""),
              "3.10a: record_schema __meta.not_an_option is a described boolean")
        check("`not_an_option` (boolean)" in (text_body or ""),
              "3.10a: the rendered __meta key list carries not_an_option")
        # 3.18 count-doubt default
        everywhere("`default` is copied VERBATIM from `options`", "3.18")
        check("REQUIRED on an `affects: count` doubt" in meta_props["doubts"]["description"],
              "3.18: record_schema's doubts description requires a verbatim default on a count doubt")
        # 3.20 contested page
        for name in ("text contract", "raster contract"):
            f = _flat(places[name])
            check("shared by **every** property that lists it in the carousel" in f
                  and "never in the Site Plan slot" in f and "dropped from **every**" not in f,
                  f"3.20: {name} says a co-claimed unanchored page is SHARED, never the plan slot")

        # validator half: WARNINGS only, never an error
        cases = [
            ("combinable not a bool", _rec(doubts=[{"subject": "office", "question": "q?",
                                                    "field": "officeArea",
                                                    "options": ["1 sq m", "2 sq m"],
                                                    "combinable": "yes"}]), "combinable"),
            ("combinable with one option", _rec(doubts=[{"subject": "office", "question": "q?",
                                                         "field": "officeArea",
                                                         "options": ["1 sq m"],
                                                         "combinable": True}]), "combinable"),
            ("not_an_option not a bool", _rec(not_an_option="let"), "not_an_option"),
            ("not_an_option without status", _rec(not_an_option=True), "not_an_option"),
        ]
        for label, rec, key in cases:
            e, w = _validate(work, [rec])
            check(not e and sum(key in x for x in w) == 1,
                  f"validator: {label} -> one warning, no error ({ascii(e[:1])} / {len([x for x in w if key in x])})")
        ok = _rec(not_an_option=True, doubts=[{"subject": "office", "question": "q?",
                                               "field": "officeArea", "combinable": True,
                                               "options": ["1 sq m", "2 sq m"]}])
        ok["status"] = "Let"
        e, w = _validate(work, [ok])
        check(not e and not any("combinable" in x or "not_an_option" in x for x in w),
              "validator: well-formed flags draw no note")

    print(f"\n{'PASS' if not fails else 'FAIL'} reader_rules_p1_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
