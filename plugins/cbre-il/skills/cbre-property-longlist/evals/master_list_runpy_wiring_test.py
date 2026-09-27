#!/usr/bin/env python3
"""master_list_runpy_wiring_test.py - the run.py side of P5 (2026-09-26 test run, fixes 3.1,
2.1, 1.6, 1.3 and 3.24). The helpers are pinned by their own evals (master_list_per_file,
master_list_speed, email_bodies, cluster_labels_optin, cluster_label_nomerge, long_path_intake);
this one pins that the SPINE calls them, in the right place, and that a real run.py pass behaves.

  A. `_cluster_cache_stamp_ok`: an old inventory (no key) with no cache is current; a cache the
     inventory was not built from, a deleted cache, a .SKIP decline, a missing or corrupt
     inventory all force the rescan (False).
  B. source pins: the folder-scan predicate consults the stamp unless the stage is out of scope;
     an EMPTY cluster_label_notes list still reaches note_suppressed; the reader dispatch skips
     per deck FILE (`excluded_deck_files`) inside the per-file loop, the label skip is gone; the
     master-list stage never enumerates when `_ml_skip` (P5 2.1 eval c), tries
     `migrate_per_file` before re-asking, passes `corpus_key`; `_first_page_text` asks for page 1
     only; the exit-17 render fills EMAIL_BODIES; "brochure deck(s)"; the cluster-labels job
     comes only from `intake.cluster_label_job` (no INVENTORY_PATH); the long-path line is
     printed from the inventory on a resumed or quiet pass.
  C. end to end (real run.py subprocesses, synthetic corpus: a tracker, two decks sharing the
     region "Madrid", a third deck, one .eml):
       1. pass 1 stops at exit 17; work/email_bodies.md exists and the rendered master-list
          prompt names it; the handoff counts one row per deck FILE ("3 brochure deck(s)").
       2. an OLD per-cluster sheet (one row for both Madrid decks = No) is migrated on pass 2:
          the re-keyed line prints, exit 17 does not re-fire, the backup is written, and the
          exit-3 manifest carries neither Madrid deck but does carry the third deck.
       3. no `inputs.cluster_labels` -> no cluster-labels prompt; with `agent` set -> the prompt
          renders with the stem's file on its line and no inventory.json instruction.
       4. `--from merge` puts the master list out of scope: master_candidates_auto.json is NOT
          re-built (it was deleted first, so a rebuild would recreate it).
  D. Windows without long-path support: an input past 260 characters is named by exactly ONE
     line per pass, quiet and resumed alike.

Offline. Run: python evals/master_list_runpy_wiring_test.py"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
HELPERS = SKILL / "helpers"
RUN_PY = HELPERS / "run.py"
sys.path.insert(0, str(SKILL / "evals"))
sys.path.insert(0, str(HELPERS))
import master_list as ML  # noqa: E402
import intake as IN  # noqa: E402
import run as R  # noqa: E402

FAILS: list = []
TIMEOUT = 300


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _run(folder: Path, work: Path, *flags):
    p = subprocess.run([sys.executable, str(RUN_PY), "--folder", str(folder), "--work", str(work),
                        "--client", "Example Ltd.", *flags],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=TIMEOUT)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


# ------------------------------------------------------------------ A. stamp predicate
def part_a():
    print("== A. _cluster_cache_stamp_ok ==")
    w = Path(tempfile.mkdtemp(prefix="cbre_stamp_"))
    try:
        ck(R._cluster_cache_stamp_ok(w) is False, "no inventory.json -> False (rescan)")
        (w / "inventory.json").write_text("{not json", encoding="utf-8")
        ck(R._cluster_cache_stamp_ok(w) is False, "a corrupt inventory.json -> False")
        (w / "inventory.json").write_text(json.dumps({"clusters": {}}), encoding="utf-8")
        ck(R._cluster_cache_stamp_ok(w) is True,
           "an old inventory (no cluster_cache_sha) and no cache -> True (no rescan)")
        (w / IN.CLUSTER_CACHE).write_text(json.dumps({"labels": {}}), encoding="utf-8")
        ck(R._cluster_cache_stamp_ok(w) is False,
           "an old inventory and a cache on disk -> False (one rescan)")
        (w / "inventory.json").write_text(
            json.dumps({"cluster_cache_sha": IN.cluster_cache_stamp(w)}), encoding="utf-8")
        ck(R._cluster_cache_stamp_ok(w) is True, "inventory built from this very cache -> True")
        (w / IN.CLUSTER_CACHE).write_text(json.dumps({"labels": {"x": "y"}}), encoding="utf-8")
        ck(R._cluster_cache_stamp_ok(w) is False, "the cache changed since -> False")
        (w / "inventory.json").write_text(
            json.dumps({"cluster_cache_sha": IN.cluster_cache_stamp(w)}), encoding="utf-8")
        (w / IN.CLUSTER_SKIP[0]).write_text("", encoding="utf-8")
        ck(R._cluster_cache_stamp_ok(w) is False, "the cache declined with .SKIP -> False")
        (w / IN.CLUSTER_SKIP[0]).unlink()
        (w / IN.CLUSTER_CACHE).unlink()
        ck(R._cluster_cache_stamp_ok(w) is False,
           "the cache DELETED after the inventory used it -> False (the label rollback)")
    finally:
        shutil.rmtree(w, ignore_errors=True)


# ------------------------------------------------------------------ B. source pins
def _between(src: str, start: str, end: str) -> str:
    i = src.find(start)
    j = src.find(end, i + 1) if i >= 0 else -1
    return src[i:j] if i >= 0 and j > i else ""


def part_b():
    print("== B. run.py wiring (source) ==")
    src = RUN_PY.read_text(encoding="utf-8")
    fs = _between(src, 'if _is_current(work / "inventory.json", [folder, work / "intake_clusters.json"]',
                  "_resumed(\"folder scan\")")
    ck('_stage_skipped("folder scan") or _cluster_cache_stamp_ok(work)' in fs,
       "3.1: the folder-scan predicate consults the cache stamp unless the stage is out of scope")
    ck('if _cl_notes or "cluster_label_notes" in inv:' in src,
       "3.1: an empty cluster_label_notes list still clears stale notes")
    ck("_ml_skip_clusters" not in src and "if region in _ml_skip" not in src,
       "3.1: the label-keyed dispatch skip is gone")
    loop = _between(src, "for rel in [*pdfs, *pptxs]:", "vision_targets.append((src, region, country))")
    ck("_ML.excluded_deck_files(work)" in src and "if src.name.lower() in _ml_skip_files:" in loop
       and loop.find("_ml_skip_files") < loop.find("_vision_supersedes"),
       "3.1: the No skip is per deck FILE, first thing inside the per-file loop")
    ml = _between(src, '_stage("master list")', "end MASTER LIST")
    ck('_ml_skip = bool(_ml_external) or _stage_skipped("master list")' in ml,
       "2.1: the _ml_skip line is present")
    ck('_ml_expect = "" if _ml_skip else _ML.expected_hash(' in ml,
       "2.1: no expected_hash is computed when the stage is skipped")
    i_skip = ml.find("if _ml_skip:\n")
    i_empty = ml.find("_ml_auto = {}", i_skip)
    i_ans = ml.find("elif _ml_answered:", i_skip)
    i_else = ml.find("else:", i_ans)
    i_build = ml.find("_ML.build_auto(", i_skip)
    ck(0 <= i_skip < i_empty < i_ans < i_else < i_build and src.count("_ML.build_auto(") == 1,
       "2.1 (P5 eval c): the ONLY build_auto call is in the else after `if _ml_skip: {}` and "
       "the answered branch - unreachable when _stage_skipped('master list')")
    ck('corpus_key=str(inv.get("input_hash") or "")' in ml[i_build:i_build + 400],
       "2.1: build_auto gets corpus_key = the inventory's input_hash")
    ck("font_grouped_blocks(p, max_pages=1)" in ml, "2.1: _first_page_text parses page 1 only")
    i_mig = ml.find("_ML.migrate_per_file(work, _ml_by_file, _ml_clusters)")
    ck(0 <= i_mig < i_ans and "is_answered(work, _ml_expect)" in ml[i_mig:i_ans]
       and "re-keyed to one row per deck file" in ml[i_mig:i_ans],
       "3.1: migrate_per_file is tried before re-asking, re-checked, and announced")
    ck('"EMAIL_BODIES": (' in ml and "_ML.EMAIL_BODIES" in ml
       and "none - this run has no email files" in ml
       and "not available - read the .msg/.eml files in" in ml,
       "1.6: the exit-17 render fills EMAIL_BODIES (file / no emails / not available)")
    ck('deck(s)). The USER decides' in ml,
       "3.1: the exit-17 handoff says 'brochure deck(s)'")
    ck("cluster(s)). The USER" not in src, "3.1: 'brochure cluster(s)' is gone from the handoff")
    ck("intake.cluster_label_job(_inv3, cfg, work)" in src and "INVENTORY_PATH" not in src,
       "1.3: the cluster-labels job comes only from intake.cluster_label_job (no INVENTORY_PATH)")
    fs2 = _between(src, "_fs_resumed = False", "SEAM-3")
    ck("if _fs_resumed or QUIET:" in fs2 and "intake.long_path_warning(inv)" in fs2,
       "3.24: the long-path line is printed from the inventory on a resumed or quiet pass")


# ------------------------------------------------------------------ C. end to end
A_PDF, B_PDF, C_PDF = "Options - Madrid.pdf", "New stock - Madrid.pdf", "Brochure_v02_final.pdf"


def _pdf(path: Path, lines: list):
    """A born-digital deck with a real text layer (a cover plus a spec page), so it routes to
    text interpretation (exit 3) rather than to photo-match as a textless brochure."""
    import fitz
    doc = fitz.open()
    spec = lines + ["Office area: 900 sq m", "Rent: EUR 5.10 per sq m per month",
                    "Clear height: 11.0 m", "Dock doors: 12", "Car parking: 80 spaces",
                    "Developer: Example Developments", "Available: Q1 2027",
                    "Motorway: A14 (2 km)", "BREEAM: Very Good"]
    for page_lines in (lines, spec):
        pg = doc.new_page(width=595, height=842)
        y = 80
        for ln in page_lines:
            pg.insert_text((60, y), ln, fontsize=12)
            y += 24
    doc.save(str(path))
    doc.close()


def _eml(path: Path):
    m = EmailMessage()
    m["From"] = "Jane Broker <jane@example.com>"
    m["To"] = "agent@example.com"
    m["Subject"] = "Warehouse options"
    m["Date"] = "Mon, 07 Sep 2026 10:00:00 +0000"
    m.set_content("Hello,\n\nPlease find the options we discussed below. Riverside Park unit 3 "
                  "offers 9,500 sq m with 10 m clear height.\n\nThanks,\nJane\n")
    path.write_bytes(bytes(m))


def _corpus(folder: Path):
    import cowork_sim as CS
    folder.mkdir(parents=True, exist_ok=True)
    CS.build_xlsx(folder, 2)
    _pdf(folder / A_PDF, ["Riverside Park", "Madrid 28001", "Warehouse area: 12,000 sq m"])
    _pdf(folder / B_PDF, ["North Gate Logistics", "Madrid 28021", "Warehouse area: 8,000 sq m"])
    _pdf(folder / C_PDF, ["Hilltop Estate", "Northtown", "Warehouse area: 15,000 sq m"])
    _eml(folder / "offer.eml")


def _manifest_decks(out: str) -> list:
    m = re.search(r"Manifest: (.+?\.json)", out)
    if not m:
        return []
    man = json.loads(Path(m.group(1).strip()).read_text(encoding="utf-8-sig"))
    return [Path(str(d.get("source_file") or d.get("file") or "")).name for d in man.get("decks") or []]


def part_c():
    print("== C. end to end through run.py ==")
    td = Path(tempfile.mkdtemp(prefix="cbre_p5run_"))
    folder, work = td / "in", td / "work"
    _corpus(folder)
    try:
        rc, out, err = _run(folder, work)
        ck(rc == 17, f"C1: pass 1 stops at the master list (exit {rc}; {(out + err)[-300:]!r})")
        if rc != 17:
            return
        eb = work / ML.EMAIL_BODIES
        ck(eb.exists() and "Warehouse options" in eb.read_text(encoding="utf-8"),
           "C1: work/email_bodies.md was written before exit 17")
        prompts = sorted((work / "prompts").rglob("master-list*.md"))
        ptxt = prompts[0].read_text(encoding="utf-8") if prompts else ""
        ck(str(eb) in ptxt and "never the .msg/.eml" in ptxt,
           f"C1: the rendered master-list prompt names the bodies file ({[p.name for p in prompts]})")
        ck("3 brochure deck(s)" in out, "C1: the handoff counts one row per deck FILE (3 decks)")
        auto = json.loads((work / ML.AUTO_CANDIDATES).read_text(encoding="utf-8-sig"))
        ck(bool(auto.get("candidates_key")), "C1: build_auto ran with a corpus_key (cache stamped)")

        # C2 - an OLD per-cluster answered sheet: one row for both Madrid decks, No
        inv = json.loads((work / "inventory.json").read_text(encoding="utf-8-sig"))
        mad = [(k, c) for k, c in (inv.get("clusters") or {}).items()
               if sorted(Path(f).name for f in (c.get("pdfs") or [])) == sorted([A_PDF, B_PDF])]
        ck(len(mad) == 1, f"C2 precondition: both Madrid decks share one cluster ({list(inv.get('clusters') or {})})")
        if len(mad) != 1:
            return
        label, cl = mad[0]
        rec_rows = [r for r in auto.get("rows") or [] if r.get("source_type") != "Brochure"]
        other = [r for r in auto.get("rows") or [] if r.get("source_type") == "Brochure"
                 and Path(str((r.get("source_files") or [""])[0])).name == C_PDF]
        rows = [{"row_id": r["row_id"], "include": "Yes", "run_notes": "",
                 "property": r.get("property") or "", "source_type": r.get("source_type"),
                 "cluster": r.get("cluster"), "source_files": r.get("source_files") or [],
                 "duplicate_group": ""} for r in rec_rows + other]
        rows.append({"row_id": ML.cluster_row_id(label, list(cl.get("pdfs") or [])), "include": "No",
                     "run_notes": "", "property": f"{label} options", "source_type": "Brochure",
                     "cluster": label, "source_files": [Path(f).name for f in cl.get("pdfs") or []],
                     "duplicate_group": ""})
        ml = {"generated": "2026-09-01T10:00:00", "source_workbook": "Master List.xlsx",
              "input_hash": ML.fingerprint(rows), "counts": {"rows": len(rows)}, "rows": rows,
              "run_notes": {}, "hand_typed": [], "deleted_since_build": []}
        (work / ML.ANSWERS).write_text(json.dumps(ml), encoding="utf-8")

        rc, out, err = _run(folder, work)
        ck("re-keyed to one row per deck file - nothing re-asked" in out,
           "C2: the answered sheet is re-keyed and the operator is told once")
        ck(rc != 17, f"C2: exit 17 does not re-fire (exit {rc})")
        ck((work / ML.PRE_SPLIT_BACKUP).exists(), "C2: the old sheet is backed up")
        ml2 = ML.load_answers(work) or {}
        ck(bool(ml2.get("migrated")) and ML.excluded_deck_files(work) == {A_PDF.lower(), B_PDF.lower()},
           "C2: master_list.json is per-file now, both Madrid decks still No")
        decks = _manifest_decks(out)
        ck(rc == 3 and C_PDF in decks and A_PDF not in decks and B_PDF not in decks,
           f"C2: the exit-3 manifest carries the third deck and neither Madrid deck ({decks})")
        ck(not list((work / "prompts").rglob("cluster-labels*.md")),
           "C3: without inputs.cluster_labels no cluster-labels prompt is rendered")

        # C3 - opt in through project.yaml
        low = sorted({s for c in (inv.get("clusters") or {}).values()
                      if c.get("confidence") == "low" for s in c.get("stems") or []})
        proj = work / "project.yaml"
        ytxt = proj.read_text(encoding="utf-8")
        if re.search(r"^inputs:\s*$", ytxt, re.M):
            ytxt = re.sub(r"^inputs:\s*$", "inputs:\n  cluster_labels: agent", ytxt, count=1, flags=re.M)
        else:
            ytxt += "\ninputs:\n  cluster_labels: agent\n"
        proj.write_text(ytxt, encoding="utf-8")
        rc, out, err = _run(folder, work)
        cl_p = sorted((work / "prompts").rglob("cluster-labels*.md"))
        if not low:
            ck(not cl_p, "C3: no low-confidence stem -> still no job, even opted in")
        else:
            ctxt = cl_p[0].read_text(encoding="utf-8") if cl_p else ""
            ck(bool(cl_p) and f'"{low[0]}"' in ctxt and "file: " in ctxt
               and "filename label now:" in ctxt and "do NOT open inventory.json" in ctxt,
               f"C3: opted in, the prompt renders with each stem's line ({low}; exit {rc})")
        ck(rc != 17 and "re-keyed" not in out, f"C3: the migrated sheet stays answered (exit {rc})")

        # C4 - --from merge: the master list is out of scope and must not enumerate
        (work / ML.AUTO_CANDIDATES).unlink()
        rc, out, err = _run(folder, work, "--from", "merge")
        tj = {}
        try:
            tj = json.loads((work / "timings.json").read_text(encoding="utf-8-sig"))
        except Exception:
            pass
        reached = any(str(s.get("stage")) == "master list" for s in (tj.get("stages") or []))
        ck(reached, f"C4 precondition: the --from merge pass went through the master-list stage (exit {rc})")
        ck(not (work / ML.AUTO_CANDIDATES).exists() and "MASTER LIST:" not in out,
           "C4: --from merge did not rebuild master_candidates_auto.json (no enumeration)")
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ------------------------------------------------------------------ D. long paths
def part_d():
    print("== D. long-path line once per pass ==")
    if os.name != "nt":
        print("  [PASS] (not Windows - the long-path case does not apply)")
        return
    td = tempfile.mkdtemp(prefix="cbre_p5lp_")
    try:
        import cowork_sim as CS
        folder, work = Path(td) / "in", Path(td) / "w"
        CS.build_xlsx(folder, 2)
        deep = folder
        while len(str(deep)) < 250:
            deep = deep / ("d" * 30)
        name = "Riverside Park brochure - very long file name.pdf"
        os.makedirs(IN._extended(str(deep)), exist_ok=True)
        with open(IN._extended(str(deep / name)), "wb") as fh:
            fh.write(b"%PDF-1.4\n% deep\n%%EOF\n")
        try:
            os.stat(str(deep / name))
            print("  [PASS] (this host supports long paths - nothing to warn about)")
            return
        except OSError:
            pass
        for i, flags in enumerate([(), (), ("--verbose",)], 1):
            rc, out, err = _run(folder, work, *flags)
            n = sum(1 for ln in (out + err).splitlines() if "longer than Windows allows" in ln)
            ck(n == 1, f"D{i}: pass {i} {' '.join(flags) or '(quiet)'} names the long path exactly "
                       f"once (got {n}; exit {rc})")
    finally:
        shutil.rmtree(IN._extended(td), ignore_errors=True)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    part_a()
    part_b()
    part_c()
    part_d()
    print()
    if FAILS:
        print(f"MASTER LIST RUN.PY WIRING TEST: FAIL ({len(FAILS)})")
        return 1
    print("MASTER LIST RUN.PY WIRING TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
