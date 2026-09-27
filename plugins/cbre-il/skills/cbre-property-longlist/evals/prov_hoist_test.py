#!/usr/bin/env python3
"""prov_hoist_test.py - a top-level `prov` is a structural slip, repaired without a re-read
(2026-09-26 test run, fix 1.5).

THE DEFECT. 3 of 22 readers on one run wrote `prov` beside the fields instead of under `__meta`.
The validator refused each (correctly: merge quarantines a top-level prov and every ledger row
loses its locator), and the only remedy on offer was re-dispatching the whole reader: 120-145 k
tokens each for a slip that moves no value. A record that carried BOTH a top-level and a
`__meta.prov` passed, and its extra locators were silently lost to the quarantine.

THE FIX (the parts owned by the reader side; run.py's load-time call and repair-stub rendering
are pinned by the spine owner's additions to this file):
  * vision_validate.hoist_toplevel_prov(records): pure, in place, idempotent, never raises;
    moves a {field: locator-string} prov under __meta, drops an identical duplicate, and NEVER
    overwrites a different locator already under __meta (that one stays top level).
  * the validator's verdict is unchanged (PROV-1 in extract_test stays green); its message now
    says whether the spine will move it or the reader must rewrite it;
  * prompts/reader-repair.md: a bounded correction prompt, whose record shape is the reader
    prompts' shape VERBATIM (one shape, never two drifting copies);
  * prompts_render.retire_kind(work, kind): moves ONE kind's stubs to prompts/_done/.

Run: python evals/prov_hoist_test.py"""
from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import vision_validate as VV  # noqa: E402
import prompts_render as PR  # noqa: E402


def _json_block(text: str) -> str:
    m = re.search(r"```json\n(.*?)\n```", text.replace("\r\n", "\n"), re.S)
    return m.group(1) if m else ""


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    # --- the pure hoist -------------------------------------------------------------------
    recs = [
        {"park": "A", "prov": {"park": "page 1 (text interpretation)"}, "__meta": {"page_no": 0}},
        {"park": "B", "prov": {"park": "page 2 (text interpretation)"}},                # no __meta
        {"park": "C", "prov": {"park": "page 3", "city": "page 3"},
         "__meta": {"page_no": 2, "prov": {"park": "page 3", "city": "page 4"}}},       # collision
        {"park": "D", "prov": ["page 1"], "__meta": {"page_no": 0}},                   # a list
        {"park": "E", "prov": {"park": {"page": 1}}, "__meta": {"page_no": 0}},        # nested
        {"park": "F", "__meta": {"page_no": 0, "prov": {"park": "page 1"}}},           # clean
        "not a record",
    ]
    before = copy.deepcopy(recs)
    notes = VV.hoist_toplevel_prov(recs)
    by = {n["record"]: n for n in notes}
    check(recs[0].get("__meta", {}).get("prov") == {"park": "page 1 (text interpretation)"}
          and "prov" not in recs[0] and by.get(1, {}).get("moved") == ["park"],
          "a lone top-level prov moves under __meta and the top-level key goes")
    check(recs[1].get("__meta", {}).get("prov") == {"park": "page 2 (text interpretation)"}
          and "prov" not in recs[1], "__meta absent -> created, prov moved into it")
    check(recs[2]["__meta"]["prov"] == {"park": "page 3", "city": "page 4"}
          and recs[2].get("prov") == {"city": "page 3"}
          and by.get(3, {}).get("moved") == ["park"]
          and by.get(3, {}).get("kept_top_level") == ["city"],
          "an identical locator counts as moved; a DIFFERENT one is never overwritten (kept)")
    check(recs[3] == before[3] and recs[4] == before[4] and recs[5] == before[5]
          and recs[6] == before[6] and set(by) == {1, 2, 3},
          "a list / nested prov, a clean record and a non-record are untouched")
    check(VV.hoist_toplevel_prov(recs) == [], "idempotent: a second pass changes nothing")
    check(VV.hoist_toplevel_prov(None) == [] and VV.hoist_toplevel_prov([{"prov": None}]) == [],
          "never raises on junk input")

    # --- the validator: verdict unchanged, message split ----------------------------------
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "vision").mkdir()
        (work / "extract").mkdir()
        (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [
            {"source_file": "d.pdf", "cluster_label": "d", "output": "work/extract/d_vision.json",
             "pages": [{"page_no": 0}]}]}), encoding="utf-8")
        vf = work / "extract" / "d_vision.json"

        def _run(rs):
            vf.write_text(json.dumps(rs), encoding="utf-8")
            return VV.validate(work)

        base = {"source_file": "d.pdf", "source_type": "pdf", "page_no": 0}
        e, _ = _run([{"park": "A", "prov": {"park": "page 1"}, "__meta": dict(base)}])
        check(any("record 1" in x and "top-level `prov`" in x and "__meta.prov" in x
                  and "moves" in x and "automatically" in x for x in e),
              "a plain top-level prov is still an ERROR, and it says the spine will move it")
        e, _ = _run([{"park": "A", "prov": ["page 1"], "__meta": dict(base)}])
        check(any("top-level `prov`" in x and "cannot be moved automatically" in x for x in e),
              "a non-{field: locator} prov is an ERROR that asks for a rewrite")
        rs = [{"park": "A", "prov": {"park": "page 1"}, "__meta": dict(base)}]
        VV.hoist_toplevel_prov(rs)
        e, _ = _run(rs)
        check(not any("prov" in x for x in e), "after the hoist the file validates clean")

        # --- retire_kind: only that kind leaves prompts/ -----------------------------------
        pdir = work / "prompts"
        pdir.mkdir()
        for n in ("reader-repair--d_vision.md", "reader-repair.md", "reader-text--x_vision.md",
                  "reader-repair-notes.md"):
            (pdir / n).write_text("x", encoding="utf-8")
        moved = PR.retire_kind(work, "reader-repair")
        left = sorted(p.name for p in pdir.glob("*.md"))
        check(moved == 2 and left == ["reader-repair-notes.md", "reader-text--x_vision.md"]
              and (pdir / "_done" / "reader-repair--d_vision.md").exists(),
              f"retire_kind moves exactly that kind's stubs to _done/ ({moved}, left {left})")
        check(PR.retire_kind(work / "nowhere", "reader-repair") == 0
              and PR.retire_kind(work, "") == 0, "retire_kind never raises")

        # --- the repair template -------------------------------------------------------------
        (pdir / "reader-text--x_vision.md").write_text("pending reader", encoding="utf-8")
        files = PR.write_prompts(work, [("reader-repair", "d_vision", {
            "DECK_NAME": "d.pdf", "OUTPUT_PATH": str(vf),
            "ERRORS": "- d_vision.json record 1 (A): __meta.page_no missing/non-integer",
            "ORIGINAL_PROMPT": "(not on disk - reference/interpretation.md is the contract)"})],
            wipe=False)
        txt = files[0].read_text(encoding="utf-8") if files else ""
        check(files and files[0].name == "reader-repair--d_vision.md"
              and "__meta.page_no missing" in txt and str(vf) in txt
              and "MOVE, never retype" in txt and "NOT a re-read" in txt,
              "the repair stub carries the error, the output path and the bounded-edit rules")
        check((pdir / "reader-text--x_vision.md").exists(),
              "rendering a repair stub with wipe=False leaves a pending reader prompt alone")
        rep = _json_block((PR.TEMPLATE_DIR / "reader-repair.md").read_text(encoding="utf-8"))
        rdr = _json_block((PR.TEMPLATE_DIR / "reader-text.md").read_text(encoding="utf-8"))
        check(rep and rep == rdr,
              "the repair prompt's record shape is the reader prompt's shape VERBATIM")
        shape = json.loads(rep) if rep else [{}]
        check(isinstance(shape[0].get("__meta", {}).get("prov"), dict) and "prov" not in shape[0],
              "that shape puts prov under __meta and nowhere else")

    # --- run.py (the spine owner's half): the load-time hoist and the repair stubs ---------
    import os
    import time
    import run as R  # noqa: E402
    import _common as C  # noqa: E402
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        ext = work / "extract"
        ext.mkdir()
        (work / "vision").mkdir()
        vf = ext / "h_vision.json"
        clean = ext / "c_vision.json"
        vf.write_text(json.dumps([{"park": "A", "prov": {"park": "page 1"},
                                   "__meta": {"source_file": "h.pdf", "page_no": 0}}]),
                      encoding="utf-8")
        clean_bytes = json.dumps([{"park": "B", "__meta": {"source_file": "c.pdf", "page_no": 0,
                                                            "prov": {"park": "page 1"}}}])
        clean.write_text(clean_bytes, encoding="utf-8")
        R._RECFILE_CACHE.clear()
        out = R._hoist_vision_prov(work, ext)
        disk = json.loads(vf.read_text(encoding="utf-8"))
        check(len(out) == 1 and out[0]["file"] == "h_vision.json"
              and disk[0].get("__meta", {}).get("prov") == {"park": "page 1"} and "prov" not in disk[0],
              "run._hoist_vision_prov rewrites the file on disk with prov under __meta")
        check(clean.read_text(encoding="utf-8") == clean_bytes,
              "a file with no top-level prov is byte-untouched")
        log = work / "vision" / "structural_fixes.json"
        lg = json.loads(log.read_text(encoding="utf-8")) if log.exists() else {}
        check(lg.get("v") == 1 and len(lg.get("fixes") or []) == 1
              and lg["fixes"][0].get("file") == "h_vision.json"
              and lg["fixes"][0].get("moved") == ["park"],
              "the fix is logged once in work/vision/structural_fixes.json")
        m1 = vf.stat().st_mtime_ns
        time.sleep(0.05)
        R._RECFILE_CACHE.clear()
        out2 = R._hoist_vision_prov(work, ext)
        lg2 = json.loads(log.read_text(encoding="utf-8")) if log.exists() else {}
        check(out2 == [] and vf.stat().st_mtime_ns == m1 and len(lg2.get("fixes") or []) == 1,
              "a second pass writes nothing (mtime unchanged) and logs nothing new")
        (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [
            {"source_file": "h.pdf", "cluster_label": "h", "output": "work/extract/h_vision.json",
             "pages": [{"page_no": 0}]},
            {"source_file": "c.pdf", "cluster_label": "c", "output": "work/extract/c_vision.json",
             "pages": [{"page_no": 0}]}]}), encoding="utf-8")
        e, _ = VV.validate(work)
        check(not any("h_vision.json" in x for x in e),
              f"the hoisted file validates clean on the next pass ({[x for x in e if 'h_vision' in x]})")
        (work / "vision" / "manifest.json").unlink()

        # a failing write leaves the disk bytes AND the cached parse un-hoisted
        bad = ext / "f_vision.json"
        bad_bytes = json.dumps([{"park": "F", "prov": {"park": "page 2"},
                                 "__meta": {"source_file": "f.pdf", "page_no": 1}}])
        bad.write_text(bad_bytes, encoding="utf-8")
        R._RECFILE_CACHE.clear()
        _real = C.atomic_write_text

        def _boom(path, text, **kw):
            if Path(path).name.endswith("_vision.json"):
                raise OSError("disk full (simulated)")
            return _real(path, text, **kw)
        C.atomic_write_text = _boom
        try:
            import io
            import contextlib
            with contextlib.redirect_stderr(io.StringIO()):
                R._hoist_vision_prov(work, ext)
        finally:
            C.atomic_write_text = _real
        check(bad.read_text(encoding="utf-8") == bad_bytes and str(bad) not in R._RECFILE_CACHE,
              "a failed write leaves the file untouched and drops the cached (hoisted) parse")
        check("prov" in R._load_records(bad)[0],
              "so the next load sees the original record and the validator refuses as before")
        R._RECFILE_CACHE.clear()

        # the repair stubs
        pdir = work / "prompts"
        pdir.mkdir()
        (pdir / "reader-text--y_vision.md").write_text("pending reader", encoding="utf-8")
        (pdir / "_done").mkdir()
        (pdir / "_done" / "reader-text--x_vision.md").write_text("original", encoding="utf-8")
        xv = ext / "x_vision.json"
        xv.write_text(json.dumps([{"park": "X", "__meta": {"source_file": "x deck.pdf"}}]),
                      encoding="utf-8")
        errs = ["x_vision.json record 1 (X): __meta.page_no missing/non-integer - copy it",
                "y_vision.json record 1 (Y): something else", "manifest-level: unrelated"]
        msg = R._render_reader_repairs(work, [xv], errs)
        stub = pdir / "reader-repair--x_vision.md"
        txt = stub.read_text(encoding="utf-8") if stub.exists() else ""
        check(stub.exists() and "__meta.page_no missing" in txt and str(xv) in txt
              and "MOVE, never retype" in txt and "x deck.pdf" in txt
              and "something else" not in txt,
              "run._render_reader_repairs writes one stub carrying ONLY that file's errors, the "
              "output path, the deck name and the bounded-edit rules")
        check(str(pdir / "_done" / "reader-text--x_vision.md") in txt,
              "the stub points at the deck's original reader prompt when it is on disk")
        check((pdir / "reader-text--y_vision.md").exists(),
              "an unrelated pending reader prompt is NOT moved (wipe=False)")
        check(msg.startswith("(orchestrator:") and "reader-repair--x_vision.md" in msg
              and "RESUMING" in msg and "Never re-dispatch the full reader" in msg,
              "the handoff names the stub and says resume, never a full re-read")
        check(R._render_reader_repairs(work, [xv], ["unrelated: nothing"]) == "",
              "no error for any file -> nothing rendered, empty handoff")
        check(PR.retire_kind(work, "reader-repair") == 1 and not stub.exists(),
              "once the output validates, retire_kind moves the stub to _done/")

    # --- run.py source pins: where the three calls sit ---------------------------------------
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    body = src[src.find("\ndef main("):] if "\ndef main(" in src else src
    i_h = body.find("_hoist_vision_prov(work, extract)")
    i_nr = body.find("NEEDS-RASTER ESCALATION")
    i_vd = body.find("vision_done = {")
    i_rk = body.find('retire_kind(work, "reader-repair")')
    i_vv = body.find("vision_validate.validate(work")
    i_fail = body.find('_say_orchestrator(f"  [FAIL] {e}"', i_vv)
    i_rr = body.find("_render_reader_repairs(work, vision_files, v_errors)", i_vv)
    i_x3 = body.find('_exit_round_trip(work, 3, _attempts, "brochure/tracker interpretation"', i_vv)
    check(0 < i_h < i_nr < i_vd < i_vv,
          "the hoist runs at record load: before the needs_raster loop, vision_done and validate")
    check(0 < i_rk < i_vv, "retire_kind('reader-repair') runs just before validate")
    check(0 < i_fail < i_rr < i_x3,
          "the repair stubs render after the [FAIL] lines and before the exit-3 round trip")

    print(f"\n{'PASS' if not fails else 'FAIL'} prov_hoist_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
