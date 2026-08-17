# Generic Orchestrator-Patch Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four generic, client-agnostic bugs found during a live Corby, UK run of the `cbre-property-longlist` skill: a motorway-locator condenser that can fuse the wrong distance onto the wrong road, a reserved schema key (`district`) that collides with the single most natural open-schema field name a reader would pick, a screenshot helper that writes outside the work directory when run from the skill's own folder (as the skill's own docs instruct), and two mechanical gates that the orchestrator must remember to run by hand instead of the spine running them itself.

**Architecture:** Each fix is independent and touches a disjoint set of files (only Task 4's schema rename touches the frozen `dashboard_template.html`, requiring the skill's documented template-versioning procedure). No client data, filenames, or run-specific values appear in any change — every fix is verified against the existing eval corpus plus a new pinned eval per task.

**Tech Stack:** Python 3 (stdlib `re`, `json`, `hashlib`, `argparse`), the skill's own `evals/*.py` harness (plain scripts with `sys.exit`, no pytest).

## Global Constraints

- This directory is **not a git repository** (verified: `git status` → "fatal: not a git repository"). The skill's own `reference/template-contract.md` accounts for this: step 1 of any template edit is "take a dated copy of the whole skill folder FIRST … the copy is your only revert." Task 0 does this for the WHOLE plan, once, up front — there are no per-step `git commit` steps anywhere below; read "commit" as "the dated backup already covers this."
- Every change must stay **fully generic** — no client name, no run-specific filename, no tailoring to the Corby dataset. Every new test fixture uses synthetic/generic data.
- After **every** task: run that task's own new/modified eval file directly, then run `python evals/run_all.py --quick` as a fast regression check.
- After the **last** task: run the **full** `python evals/run_all.py` (all 60+ evals) — this is the skill's own documented bar for shipping any helper/template edit (`SKILL.md` "Maintenance" section), and then `python helpers/make_integrity.py` must already be current (it is run inside Task 4, the only task that touches a helper file the manifest hashes — re-run it once more at the very end as a final check).
- Never touch `helpers/make_template.py`'s `CONFIG_REPLACEMENTS`/`POST_PATCHES` literals — that machinery is explicitly HISTORICAL (cannot regenerate the live v37+ template) and out of scope.
- All file paths below are absolute Windows paths rooted at `C:\Users\TBaaij\.claude\skills\cbre-property-longlist\`. Written with forward slashes below for readability inside code blocks; use the real path when running commands.

---

### Task 0: Safety backup

**Files:**
- Create: a dated copy of the whole skill folder (outside the skill folder itself)

- [ ] **Step 1: Copy the whole skill folder to a dated backup location**

```bash
cp -r "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" "C:/Users/TBaaij/.claude/skills/cbre-property-longlist.backup-2026-08-15"
```

- [ ] **Step 2: Verify the backup is complete**

```bash
diff -rq "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" "C:/Users/TBaaij/.claude/skills/cbre-property-longlist.backup-2026-08-15"
```

Expected: no output (the two trees are identical). This backup is the revert path for every task below — if anything goes wrong, restore the affected file(s) from here rather than trying to hand-reconstruct the original.

---

### Task 1: Fix the motorway-locator distance/road mis-pairing bug

**Files:**
- Modify: `helpers/normalize.py:409-473` (the `short_motorway` function and its regex constants at lines 396-406)
- Modify: `evals/header_brochure_motorway_test.py:84-93` (add a new pinned case)

**Interfaces:**
- Consumes: nothing new (the existing `_MW_ROAD`, `_MW_JCT`, `_MW_PAIRS`, `_MW_DIST`, `_MW_ADJACENT` module-level regexes in `normalize.py`)
- Produces: `short_motorway(text, limit=MOTORWAY_MAX) -> (str, bool)` — SAME signature as today, only its internal distance-selection logic changes. Nothing downstream (`merge.py:1883` calls `N.short_motorway(p["motorway"])[0]`) needs to change.

**The bug:** when a clause (a `;`/`.`-separated run) mentions **more than one** distance figure, `short_motorway` picks the FIRST distance anywhere in the clause via `_MW_DIST.search(clause)`, regardless of which road/junction it actually sits next to in the source text. A real example that shipped a wrong value: `"Evo Corby has immediate access to the A43, is only 11 miles to the A14, and 28 miles from Junction 19 of the M1."` has no `;`/`.` mid-sentence, so the WHOLE sentence is one clause; `_MW_PAIRS` correctly finds `Junction 19 of the M1` (road=`M1`, jct=`19`), but `_MW_DIST.search` then grabs the FIRST distance in the clause — `"11 miles"` (which belongs to the A14 mention, far earlier in the sentence) — instead of `"28 miles"` (which sits right next to `"Junction 19"`, a few words away). The result, `"M1 J19 11 miles"`, misstates a real published distance by 17 miles: a fabricated-looking value on a client-facing card.

**The fix:** make distance selection **proximity-aware** — when a road/junction match is found at some character span in the clause, prefer the `_MW_DIST` match whose span is CLOSEST to that road/junction span (by character distance), not simply the first one found anywhere in the clause. When only one distance exists in the clause (the common, already-tested case), "nearest" and "first" are identical, so no existing behaviour changes.

- [ ] **Step 1: Read the current function to confirm line numbers before editing**

```bash
python -c "
import re
p = r'C:/Users/TBaaij/.claude/skills/cbre-property-longlist/helpers/normalize.py'
print(open(p, encoding='utf-8').read().count('def short_motorway'))
"
```

Expected: `1` (confirms there is exactly one definition to edit).

- [ ] **Step 2: Write the failing test — add a new CASE to the existing motorway eval**

Edit `evals/header_brochure_motorway_test.py`. Insert a new tuple into the existing `CASES` list (right after the two already there, before the closing `]`, at line 90):

```python
    CASES = [
        ("Junction 18/18A M5 2 miles to the south; Junction 1 M49 4.5 miles to the north; "
         "M4/M5 interchange 10 miles to the north", "M5 J18/18A 2 miles; M49 J1 4.5 miles"),
        ("Adjacent to J19 M5 Portbury Docks; accessed just off J19 of the M5 motorway. "
         "The M49 (via J18/18a, M5) the link to South Wales is approximately 3 miles to "
         "the North", "M5 J19 adjacent; M49 3 miles"),
        # B-motorway-fix: a SINGLE clause (no ';'/'.' separator) naming three roads and two
        # distances. The road/junction pair found is M1 J19; the correct distance is the one
        # printed right beside it (28 miles), not the first distance in the sentence (11 miles,
        # which belongs to the A14 mention). A live run shipped "M1 J19 11 miles" here - a
        # fabricated-looking 17-mile error - before distance selection became proximity-aware.
        ("Evo Corby has immediate access to the A43, is only 11 miles to the A14, and 28 "
         "miles from Junction 19 of the M1.", "M1 J19 28 miles"),
    ]
```

- [ ] **Step 3: Run the eval to verify the new case fails**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/header_brochure_motorway_test.py
```

Expected: `[FAIL]` on the new case, reporting something like `got='M1 J19 11 miles'` where `want='M1 J19 28 miles'`, and `STATUS: BLOCKED (1 failure(s))`.

- [ ] **Step 4: Implement the fix in `helpers/normalize.py`**

Replace the whole `short_motorway` function body (lines 409-473) with:

```python
def _nearest_match(pattern, text, anchor):
    """Return the `pattern` match in `text` whose span sits closest to `anchor` (a
    (start, end) char span), preferring the leftmost on a tie. `None` if `pattern` has
    no match at all. `anchor=None` falls back to the first match (today's behaviour),
    used when no road/junction span was found to anchor against.

    Why this exists: a clause naming more than one road ("...11 miles to the A14, and
    28 miles from Junction 19 of the M1") has more than one distance too, and the FIRST
    one in the clause is not necessarily the one printed next to the road that was
    actually matched. Anchoring to the matched span picks the distance the source
    itself associates with that road, not merely whichever comes first."""
    if anchor is None:
        return pattern.search(text)
    a_start, a_end = anchor
    best, best_gap = None, None
    for m in pattern.finditer(text):
        if m.end() <= a_start:
            gap = a_start - m.end()
        elif m.start() >= a_end:
            gap = m.start() - a_end
        else:
            gap = 0
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, m
    return best


def short_motorway(text, limit: int = MOTORWAY_MAX):
    """Condense a prose motorway description into a locator that fits a card.

    Returns (value, shortened). A value already within `limit` is returned untouched, so
    the common "M4, J17" case is a no-op and nothing is rewritten for the sake of it.

    Longer values are prose an agent wrote for a brochure, e.g. "Junction 18/18A M5 2 miles
    to the south; Junction 1 M49 4.5 miles to the north; M4/M5 interchange 10 miles to the
    north". Those read as a paragraph on a card and push the meta line onto three rows. The
    ROAD + JUNCTION + DISTANCE triples are what a broker actually scans, so they are pulled
    out in the order the source states them, reformatted as "M5 J18/18A 2 miles", and joined
    with "; " while they fit. Nothing is invented: every road, junction and distance in the
    output appears verbatim in the input, and if no pair can be parsed the text is cut at a
    word boundary instead, which is honest rather than clever.

    Distance selection is PROXIMITY-AWARE: when a clause mentions more than one distance
    figure, the one nearest the matched road/junction wins, not merely the first one in the
    clause - see `_nearest_match`. A clause with only one distance is unaffected (nearest and
    first are the same match), so every previously-pinned case is unchanged.

    The full sentence is never lost - it stays in the Source Ledger against this field.
    """
    if not isinstance(text, str):
        return text, False
    s = " ".join(text.split())
    if len(s) <= limit:
        return s, False

    seen, items = set(), []
    for clause in re.split(r"\s*[;.]\s+", s):
        if not clause.strip():
            continue
        road = jct = anchor = None
        for rx in _MW_PAIRS:
            m = rx.search(clause)
            if not m:
                continue
            g = m.groups()
            road, jct = (g[1], g[0]) if rx is _MW_PAIRS[0] else (g[0], g[1])
            anchor = m.span()
            break
        if road is None:
            m = re.search(_MW_ROAD, clause, re.I)
            road = m.group(0) if m else None
            anchor = m.span() if m else None
        if not road:
            continue
        part = road.upper()
        if jct:
            part += " J" + re.sub(r"\s*", "", jct).upper()
        md = _nearest_match(_MW_DIST, clause, anchor)
        if md:
            part += f" {md.group(1)} {md.group(2).lower()}"
        elif _MW_ADJACENT.search(clause):
            part += " adjacent"
        key = part.split()[0] + (jct or "")
        if key in seen:
            continue
        seen.add(key)
        items.append(part)

    if items:
        out = items[0]
        for nxt in items[1:]:
            if len(out) + 2 + len(nxt) > limit:
                break
            out += "; " + nxt
        if len(out) <= limit:
            return out, True

    cut = s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or s[:limit]).strip(), True
```

- [ ] **Step 5: Run the eval to verify all cases (old and new) pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/header_brochure_motorway_test.py
```

Expected: every `[PASS]` line, including the three motorway `CASES` and the two "already short, untouched" checks, ending `STATUS: ALL-PASS`.

- [ ] **Step 6: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: `STATUS: ALL-PASS` (or the suite's equivalent all-clear line). If anything fails, stop and diagnose before continuing — do not proceed to Task 2 on a red quick-pass.

---

### Task 2: Fix `render_qa.py`'s screenshot directory default

**Files:**
- Modify: `helpers/render_qa.py:18-19` (module docstring CLI usage) and `helpers/render_qa.py:204-212` (`main()`)
- Create: `evals/render_qa_outdir_test.py`

**Interfaces:**
- Consumes: `playwright_check(html: Path, out: Path) -> int` (unchanged signature, already in the file at line 92)
- Produces: nothing new consumed elsewhere; `main()`'s CLI contract changes only in what `--out`/`--out-dir` DEFAULTS to when omitted (still overridable exactly as before when passed explicitly)

**The bug:** `ap.add_argument("--out", "--out-dir", dest="out", default="render", ...)` is a RELATIVE path resolved against the process's current working directory, not against the built HTML file's location. The skill's own documented invocation pattern (`SKILL.md` "Which shell runs the helpers": *"Run the helpers with the sandbox shell from the skill directory"*) means an orchestrator following the docs literally runs `python helpers/render_qa.py <path-to-built.html>` from INSIDE the skill's own install folder — so the default `render/` directory is created inside the shared skill folder itself, not the client's work directory, on essentially every run. (The SAME class of bug was already fixed once in this exact file for `launch.json`, at line 218-220 — `html.resolve().parent / ".claude"` — but the screenshot `--out` default was never given the same treatment.)

- [ ] **Step 1: Write the failing test**

Create `evals/render_qa_outdir_test.py`:

```python
#!/usr/bin/env python3
"""render_qa_outdir_test.py - the --out default must anchor to the built HTML file's own
directory, never to the current working directory. (follow-up to B59's launch.json fix)

THE DEFECT: `ap.add_argument("--out", ..., default="render")` is a relative path, resolved
against argparse's caller's cwd. The skill's own documented invocation pattern runs this
script FROM the skill's install directory (`SKILL.md` "Which shell runs the helpers"), so
following the docs literally writes screenshots into the shared skill folder instead of the
client's work directory on every run that omits --out. `launch.json` got the correct fix
(anchored to html.resolve().parent) in the SAME file; the screenshot out-dir default did not.

This test never launches a browser - it only checks what `main()`'s argparse setup RESOLVES
the default to, by monkeypatching `playwright_check` to capture its `out` argument. Offline.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import render_qa as R  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _run_main_capturing_out(argv):
    """Run render_qa.main() with sys.argv=argv, intercepting the `out` Path it would pass
    to playwright_check, without actually launching a browser."""
    captured = {}

    def fake_playwright_check(html, out):
        captured["out"] = out
        return 0  # pretend success so main() exits 0 without touching the launch.json branch

    saved_argv, saved_fn = sys.argv, R.playwright_check
    sys.argv = argv
    R.playwright_check = fake_playwright_check
    try:
        try:
            R.main()
        except SystemExit:
            pass
    finally:
        sys.argv = saved_argv
        R.playwright_check = saved_fn
    return captured.get("out")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="cbre_rq_outdir_"))
    html = work / "built.html"
    html.write_text("<html><body>ok</body></html>", encoding="utf-8")

    print("== --out omitted: default anchors to the HTML file's own directory ==")
    out = _run_main_capturing_out(["render_qa.py", str(html)])
    ck(out is not None, "playwright_check was invoked at all")
    ck(out == html.resolve().parent / "render",
       f"default out-dir is <html dir>/render, got {out!r}")
    ck(Path.cwd() not in (out.parents if out else []),
       "the default does NOT depend on the process cwd")

    print()
    print("== --out given explicitly: still honoured verbatim ==")
    explicit = work / "custom_shots"
    out2 = _run_main_capturing_out(["render_qa.py", str(html), "--out", str(explicit)])
    ck(out2 == explicit, f"explicit --out is used as-is, got {out2!r}")

    print()
    print("== --out-dir alias still works ==")
    out3 = _run_main_capturing_out(["render_qa.py", str(html), "--out-dir", str(explicit)])
    ck(out3 == explicit, f"--out-dir alias resolves the same way, got {out3!r}")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/render_qa_outdir_test.py
```

Expected: `[FAIL]` on `"default out-dir is <html dir>/render"` (it will report the resolved default as `<cwd>/render` instead), `STATUS: BLOCKED (1 failure(s))`.

- [ ] **Step 3: Implement the fix**

In `helpers/render_qa.py`, update the module docstring CLI usage block (lines 18-19):

```python
CLI:
  python render_qa.py <built.html> [--out DIR]   (--out-dir is an alias of --out)
  Default DIR is a 'render' folder NEXT TO <built.html> - never the current working
  directory, so running this from the skill's own install folder (the documented
  invocation pattern) still writes screenshots beside the client's build, not into
  the shared skill tree.
```

Then replace `main()` (lines 204-212 only — the `if rc == -1:` branch below is untouched):

```python
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--out", "--out-dir", dest="out", default=None,
                    help="output dir for screenshots (--out-dir is an alias, matching the "
                         "sibling scripts). Defaults to a 'render' folder NEXT TO <html> - "
                         "not the current working directory - so it is safe to run this "
                         "from the skill's own folder, per the documented invocation.")
    args = ap.parse_args()
    html = Path(args.html)
    out_dir = Path(args.out) if args.out else (html.resolve().parent / "render")
    sys.stdout.reconfigure(encoding="utf-8")
    rc = playwright_check(html, out_dir)
```

(Every line from `if rc == -1:` onward, currently lines 213-248, is unchanged — it already correctly anchors `launch.json` to `html.resolve().parent`.)

- [ ] **Step 4: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/render_qa_outdir_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 5: Run the pre-existing render eval to confirm no regression**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/render_capture_test.py
```

Expected: `RENDER CAPTURE TEST: PASS` (unchanged — that eval only exercises `capture_report`/source-text greps, neither of which this task touched).

- [ ] **Step 6: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: all-clear.

---

### Task 3: Fold `input-accounting` and `capture-symmetry` into `run.py`'s own gate1 scorecard

**Files:**
- Modify: `helpers/run.py:3180-3213` (the Stage-4 pre-build gate list)
- Modify: `SKILL.md:185` (the Stage-4 pipeline description line)
- Modify: `reference/gates.md:43` (the G-inputs table row)
- Create: `evals/gate1_automation_test.py`

**Interfaces:**
- Consumes: `run_gate(module, *cmd) -> int` (existing helper in `run.py`, already used for every other mechanical gate); `gate_runner.py`'s existing `input-accounting` and `capture-symmetry` subcommands (unchanged CLI: `input-accounting <canonical> --work <W>`, `capture-symmetry --work <W>`)
- Produces: two more entries appended to the `g1` list (the pre-build gate return-code list) and to `gate1_scorecard.md`'s printed fragments — nothing downstream reads `g1`'s length, only `any(rc != 0 for rc in g1)` and `all(rc == 0 for rc in g1)`, both unaffected in shape

**The bug:** `gate_runner.py input-accounting` (a REAL gate — it can return 1 and block, per `evals/input_accounting_test.py`'s "MUST FIRE" cases) and `gate_runner.py capture-symmetry` (an always-0 advisory-notes report, per `cmd_capture_symmetry`'s unconditional `return 0`) are both fully mechanical and deterministic, yet the spine never calls either — `SKILL.md` and `reference/gates.md` currently tell the ORCHESTRATOR to run them by hand "alongside the batch." This is exactly the kind of manual step that gets forgotten under time pressure, and both gates are cheap, pure-Python checks with no reason to stay manual — every other mechanical gate in the identical spirit is already wired into `run.py`'s `g1` list.

- [ ] **Step 1: Write the failing test**

Create `evals/gate1_automation_test.py`:

```python
#!/usr/bin/env python3
"""gate1_automation_test.py - input-accounting and capture-symmetry run AUTOMATICALLY as
part of the pre-build gate batch; the orchestrator has nothing to remember.

THE DEFECT: both gates are fully mechanical and deterministic (capture-symmetry always
returns 0; input-accounting can return 1, exactly like every other pre-build gate), yet
`run.py`'s Stage-4 gate list never called either - SKILL.md and reference/gates.md instead
told the ORCHESTRATOR to run them "yourself alongside the batch", which is the exact kind of
manual step that gets skipped under time pressure. Every sibling mechanical gate in the same
spirit (self-check, validate-data, coverage, ...) is already wired into `run.py`'s own `g1`
list - these two belong there too.

Pins, source-text style (matching this suite's existing convention, e.g.
header_brochure_motorway_test.py's `"N.short_motorway(...)" in mg` check):
  1. run.py's Stage-4 section literally invokes both gates via run_gate(gate_runner, ...).
  2. the orchestrator-must-run-it-yourself language is gone from SKILL.md and gates.md.
  3. both gate names are still mentioned in SKILL.md/gates.md (capture_contract_test.py
     already pins that - this test does not weaken or duplicate that pin, only adds the
     "no longer manual" half).
Offline, no build.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    run_src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    # isolate the Stage-4 pre-build gate section so a match elsewhere in the file
    # (e.g. a docstring) cannot satisfy the pin by accident
    start = run_src.find("# Stage 4 - pre-build gates")
    end = run_src.find("# Stage 5 - build")
    ck(start != -1 and end != -1 and end > start,
       "run.py has a locatable Stage 4 -> Stage 5 pre-build gate section")
    stage4 = run_src[start:end] if start != -1 and end != -1 else ""

    ck('"input-accounting"' in stage4,
       "run.py's Stage-4 section calls the input-accounting gate itself")
    ck('"capture-symmetry"' in stage4,
       "run.py's Stage-4 section calls the capture-symmetry gate itself")
    ck("run_gate(gate_runner, \"input-accounting\"" in stage4,
       "input-accounting is invoked the same way as every other mechanical gate (run_gate(...))")
    ck("run_gate(gate_runner, \"capture-symmetry\"" in stage4,
       "capture-symmetry is invoked the same way as every other mechanical gate (run_gate(...))")
    # input-accounting joins g1 (it can block, like coverage/validate-data/...);
    # capture-symmetry is advisory-only but its OUTPUT still belongs in the scorecard, so it
    # is called via run_gate too (its return code is always 0, appending it is harmless).
    ck("g1.append(run_gate(gate_runner, \"input-accounting\"" in stage4,
       "input-accounting's result joins g1 (it can block a build, exactly like coverage etc.)")

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ck("ORCHESTRATOR-run" not in skill,
       "SKILL.md no longer tells the orchestrator to run these two by hand")
    ck("capture-symmetry" in skill, "SKILL.md still mentions capture-symmetry")
    ck("input-accounting" in skill, "SKILL.md still mentions input-accounting")

    gates = (ROOT / "reference" / "gates.md").read_text(encoding="utf-8")
    ck("ORCHESTRATOR-RUN" not in gates,
       "reference/gates.md no longer marks G-inputs as orchestrator-run-by-hand")
    ck("G-inputs" in gates, "reference/gates.md still documents G-inputs")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/gate1_automation_test.py
```

Expected: multiple `[FAIL]` lines (the calls don't exist yet; the manual-run language is still present), `STATUS: BLOCKED`.

- [ ] **Step 3: Implement the fix in `helpers/run.py`**

In the Stage-4 section, immediately after the existing `coverage` gate call and before `trace-coverage` (this is where `reference/gates.md`'s own table already places "G-inputs" — between G-coverage and G-trace-coverage), insert two new lines. The block currently reads (lines 3184-3189):

```python
    cov_args = ["coverage", canonical]
    fill_thr = (cfg.get("qa") or {}).get("fill_threshold")
    if fill_thr is not None:
        cov_args += ["--fill-threshold", fill_thr]
    g1.append(run_gate(gate_runner, *cov_args))
    g1.append(run_gate(gate_runner, "trace-coverage", canonical, "--ledger", ledger_csv))
```

Change it to:

```python
    cov_args = ["coverage", canonical]
    fill_thr = (cfg.get("qa") or {}).get("fill_threshold")
    if fill_thr is not None:
        cov_args += ["--fill-threshold", fill_thr]
    g1.append(run_gate(gate_runner, *cov_args))
    # B-gate-automation: input-accounting and capture-symmetry are both fully mechanical
    # and deterministic, so the spine runs them itself instead of asking the orchestrator
    # to remember a manual step "alongside the batch". input-accounting can genuinely
    # block (a whole source vanished with nothing recorded); capture-symmetry always
    # returns 0 (it is an advisory cross-source asymmetry report for the G-honesty/G-trace
    # reviewers) - appending its result to g1 is harmless and keeps its notes in the same
    # scorecard file the reviewers already read.
    g1.append(run_gate(gate_runner, "input-accounting", canonical, "--work", work))
    g1.append(run_gate(gate_runner, "capture-symmetry", "--work", work))
    g1.append(run_gate(gate_runner, "trace-coverage", canonical, "--ledger", ledger_csv))
```

- [ ] **Step 4: Update `SKILL.md`'s Stage-4 description**

In `SKILL.md`, find the Stage-4 bullet (the long line beginning `- **4 PRE-BUILD GATE** (BLOCKING): mechanical`). Replace this substring:

Old:
```
mechanical `gate_runner.py self-check|validate-data|coverage|trace-coverage|prov-containment|images|arithmetic|enrichment|translation` + `ledger.py validate` (**`prov-containment`** asserts that a value citing "page N" actually OCCURS on that page - it is what stops the manifest's filename-derived `cluster_label` shipping as a sourced `region`; a value genuinely read from an image declares `not in text layer` in its prov and is skipped) (all run by the spine, results in `gate1_scorecard.md`; **`gate_runner.py input-accounting` and `gate_runner.py capture-symmetry --work <work>` are ORCHESTRATOR-run** - the spine does not invoke those two, so run them yourself alongside the batch. `capture-symmetry` is the cheap ADVISORY signal for UNDER-capture: it names any field captured from one source deck but from ZERO records of another, which is the one shape no other gate can see - every data gate checks that POPULATED fields trace to a source, and none can know what the page said. Hand its notes to G-honesty/G-trace to re-derive);
```

New:
```
mechanical `gate_runner.py self-check|validate-data|coverage|input-accounting|trace-coverage|prov-containment|images|arithmetic|enrichment|translation` + `ledger.py validate` (**`prov-containment`** asserts that a value citing "page N" actually OCCURS on that page - it is what stops the manifest's filename-derived `cluster_label` shipping as a sourced `region`; a value genuinely read from an image declares `not in text layer` in its prov and is skipped) (all run automatically by the spine, results in `gate1_scorecard.md` - **`gate_runner.py capture-symmetry`** runs in the same batch too; it is the cheap ADVISORY signal for UNDER-capture: it names any field captured from one source deck but from ZERO records of another, which is the one shape no other gate can see - every data gate checks that POPULATED fields trace to a source, and none can know what the page said. Hand its notes to G-honesty/G-trace to re-derive);
```

- [ ] **Step 5: Update `reference/gates.md`'s G-inputs row**

Find this row (currently line 43):

Old:
```
| G-inputs | `gate_runner.py input-accounting --work <W> <canonical>` — **ORCHESTRATOR-RUN: the spine does not invoke this one yet, so run it yourself alongside the other pre-build gates** | every discovered input either contributed fields (it appears in the Source Ledger), contributed a photo, was recorded unreadable/skipped, or has no consumer in the spine (a loose image). Anything else has silently vanished | a whole source dropped with nothing recorded |
```

New:
```
| G-inputs | `gate_runner.py input-accounting --work <W> <canonical>` — run automatically by `run.py` in the same pre-build batch as every other mechanical gate | every discovered input either contributed fields (it appears in the Source Ledger), contributed a photo, was recorded unreadable/skipped, or has no consumer in the spine (a loose image). Anything else has silently vanished | a whole source dropped with nothing recorded |
```

- [ ] **Step 6: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/gate1_automation_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 7: Run the two evals this task's doc changes could affect, to confirm no regression**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/capture_contract_test.py && python evals/input_accounting_test.py
```

Expected: both `STATUS: ALL-PASS` / `PASS` — `capture_contract_test.py` only checks that the STRING "capture-symmetry" still appears in `SKILL.md`/`reference/gates.md` (it does, per Step 4/5 above), never the removed "run it yourself" phrasing, so it is unaffected. `input_accounting_test.py` only exercises `gate_runner.py input-accounting` directly and `GR._accounting_buckets`, not `run.py`'s orchestration, so it is unaffected too.

- [ ] **Step 8: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: all-clear.

---

### Task 4: Free `district` for its natural open-schema meaning (rename the reserved labour-market object)

**Files:**
- Modify: `templates/canonical.schema.json:111-130`
- Modify: `helpers/merge.py:77` (docstring), `helpers/merge.py:184-185` (`_OV_FORBIDDEN`)
- Modify: `helpers/_common.py:486` (docstring), `helpers/_common.py:528` (`IDENTIFIER_FIELDS`)
- Modify: `assets/dashboard_template.html:2113` (the ONE `p.district` JS reference)
- Modify: `assets/VERSION` (version bump + new chrome_sha256)
- Modify: `reference/template-contract.md` (new v38 changelog line)
- Create: `evals/district_field_test.py`

**Interfaces:**
- Consumes: `_common.canonical_property_fields()` (unchanged signature; its OUTPUT set changes because it derives from `canonical.schema.json`'s top-level `properties` keys)
- Produces: canonical property records may now carry a plain STRING `district` field (like `city`/`park`/`postcode`), auto-discoverable by every reader via the manifest's `fields` array; the renamed `districtProfile` object keeps the exact same shape/behaviour the old `district` object had (orchestrator-filled labour-market micro-profile, never populated by the deterministic spine)

**Why this is a real, generic bug, not a one-off:** `reference/interpretation.md` (the actual contract every interpretation sub-agent reads) lists `district` as one of the 43 "reader-fillable" canonical field names — generated LIVE from `_common.canonical_property_fields()`, which in turn reads `canonical.schema.json`'s own top-level `properties` keys. `helpers/gate_runner.py`'s `PROV_ADVISE_FIELDS = frozenset({"city", "district", "park", "address", "postcode"})` (used by the `prov-containment` gate) already expects `district` to be a flat, checkable STRING field grouped with `city`/`park`/`postcode`. But `canonical.schema.json` currently declares top-level `district` as an OBJECT (an "ORCHESTRATOR-FILLED... labour-market micro-profile" — nothing in `helpers/` actually writes to it; it is a manual-edit-only feature). So the skill's own contract ADVERTISES `district` as a fillable string field, its own gate EXPECTS it to be a checkable string field, and its own schema REJECTS exactly that. This will recur for any client, any market — "district" is an obvious, natural key for "the estate/sub-area a park sits within" (this run's own two brochures independently reached for it, unprompted, for exactly that meaning).

- [ ] **Step 1: Write the failing test**

Create `evals/district_field_test.py`:

```python
#!/usr/bin/env python3
"""district_field_test.py - `district` is a plain first-class STRING field (like city/park/
postcode), never a reserved container object; the labour-market micro-profile object that
used to squat that key is renamed to `districtProfile`.

THE DEFECT: canonical.schema.json declared top-level `district` as an OBJECT (an
orchestrator-filled labour-market research container - nothing in helpers/ ever writes to
it), yet `_common.canonical_property_fields()` (which derives its set from that same schema)
feeds `district` to EVERY interpretation sub-agent as a "reader-fillable" name via
reference/interpretation.md's live-generated `fields` array, and gate_runner.py's own
PROV_ADVISE_FIELDS = {"city", "district", "park", "address", "postcode"} already expects it
to be a flat checkable string grouped with exactly those siblings. A reader that (correctly,
per its own contract) filled `district` with a plain estate name - e.g. "Earlstree Industrial
Estate" - hard-blocked validate-data with "'Earlstree Industrial Estate' is not of type
'object'" on a live run, for every property that carried it. This is a genuine, recurring
trap for any client: 'district' is the single most natural key for 'the estate/sub-area a
park sits within', which two independent brochures on one live run reached for unprompted.

Offline, no build (except a lightweight template-JS text check)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import merge as M  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    props = schema["$defs"]["property"]["properties"] if "$defs" in schema else schema["properties"]

    print("== schema: district is a plain string, districtProfile is the container ==")
    ck("district" in props, "canonical.schema.json declares a top-level `district` property")
    ck(props.get("district", {}).get("type") == "string",
       f"`district` is type string, got {props.get('district', {}).get('type')!r}")
    ck("districtProfile" in props,
       "canonical.schema.json declares the renamed `districtProfile` container")
    ck(props.get("districtProfile", {}).get("type") == "object",
       f"`districtProfile` is type object, got {props.get('districtProfile', {}).get('type')!r}")
    ck("district" in (props.get("districtProfile", {}).get("properties") or {}),
       "the renamed container keeps its OWN nested `district` string sub-field (the name being profiled)")

    print()
    print("== canonical_property_fields() reflects the rename ==")
    C._CANON_PROPERTY_FIELDS = None  # force a fresh scan (module-level cache)
    fields = C.canonical_property_fields()
    ck("district" in fields, "`district` (the plain string) is a live canonical field")
    ck("districtProfile" in fields, "`districtProfile` (the container) is a live canonical field")

    print()
    print("== merge.py protects the CONTAINER from an override, not the plain string ==")
    ck("districtProfile" in M._OV_FORBIDDEN,
       "the renamed container is in merge._OV_FORBIDDEN (an override may never inject structure)")
    ck("district" not in M._OV_FORBIDDEN,
       "the plain `district` string is NOT forbidden - it is correctable like city/park")

    print()
    print("== _common.py: district stays non-translatable; districtProfile joins it ==")
    ck("district" in C.IDENTIFIER_FIELDS,
       "`district` (a proper-noun estate name) stays out of the translator's reach, like city/park")
    ck("districtProfile" in C.IDENTIFIER_FIELDS,
       "`districtProfile` (structural container) is protected from translation too")

    print()
    print("== the template's JS reads the renamed key ==")
    tpl = (ROOT / "assets" / "dashboard_template.html").read_text(encoding="utf-8")
    ck("p.districtProfile" in tpl, "the template reads p.districtProfile for the workforce panel")
    ck("p.district ||" not in tpl and "p.district||" not in tpl,
       "the template no longer reads the old p.district object (bare property access)")
    # the human-visible UI label/CSS class names legitimately keep the word "District" -
    # only the JSON property ACCESS on `p` was reserved and needed to move.
    ck("district-panel" in tpl, "the CSS class name (a UI label, not a JSON key) is untouched")
    ck('T("wf_district_label")' in tpl, "the i18n label key (a UI label, not a JSON key) is untouched")

    print()
    print("== version bump ==")
    version = (ROOT / "assets" / "VERSION").read_text(encoding="utf-8")
    ck("v38" in version, "assets/VERSION was bumped to v38")
    import hashlib
    tmpl_text = C.load_template()
    expected_sha = hashlib.sha256(tmpl_text.encode("utf-8")).hexdigest()
    recorded_sha = C.load_version().get("chrome_sha256", "")
    ck(recorded_sha == expected_sha,
       f"VERSION's chrome_sha256 matches the CRLF-normalised TEXT hash of the live template "
       f"(recorded {recorded_sha[:12]}, computed {expected_sha[:12]})")

    print()
    print("== the changelog documents the rename ==")
    changelog = (ROOT / "reference" / "template-contract.md").read_text(encoding="utf-8")
    ck("**v38**" in changelog, "reference/template-contract.md has a v38 entry")
    ck("districtProfile" in changelog, "the v38 entry names the rename")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/district_field_test.py
```

Expected: multiple `[FAIL]` lines (nothing renamed yet), `STATUS: BLOCKED`.

- [ ] **Step 3: Edit `templates/canonical.schema.json`**

The file currently reads (lines 111-130):

```json
        "postcode": {"type": "string", "description": "The property's postcode, as the source states it (e.g. 'NN17 4XD'). Declared first-class rather than merely tolerated as an auto-shown extra: it ships, it materially improves geocoding, and two independent reviewers flagged it as droppable-but-dropped."},
        "motorway": {"type": "string"},
        "mapLink": {"type": "string"},
        "brochureLink": {"type": "string", "description": "URL of the agent/landlord brochure or listing page for THIS property. Rendered as a View brochure link in the detail modal; never invented, only carried from a source that states it."},
        "description": {"type": "string"},
        "photo": {"type": "string", "description": "data:image/...;base64,... or a placeholder data URI. This is the HERO (gallery[0])."},
        "gallery": {"type": "array", "items": {"type": "string"}, "description": "Up to GALLERY_MAX photo data URIs for the carousel, best-first (photographic_score), hero first. PAGE-SCOPED so a multi-property deck contributes only this property's photos. Always contains at least [photo]; the carousel falls back to [photo] when absent."},
        "plan": {"type": "string", "description": "A site-plan image data URI. merge.py harvests it from the brochure page (page_plan: balanced white/ink signature; the hyperlinked location map and boilerplate are excluded); a standalone plan file bound by the orchestrator (extract_image.py kind=plan) takes precedence. On a plan-only page the plan also serves as the hero."},
        "district": {
          "type": "object",
          "description": "ORCHESTRATOR-FILLED: optional local labour-market micro-profile from research. The deterministic spine does not populate it; region-level workforce data lives in top-level regions{} via enrich --regions.",
          "additionalProperties": true,
          "properties": {
            "district": {"type": "string"},
            "unemployment": {"type": ["number", "string", "null"]},
            "asOf": {"type": "string"},
            "applicantsPerVacancy": {"type": ["number", "string", "null"]},
            "note": {"type": "string"}
          }
        },
```

Replace it with:

```json
        "postcode": {"type": "string", "description": "The property's postcode, as the source states it (e.g. 'NN17 4XD'). Declared first-class rather than merely tolerated as an auto-shown extra: it ships, it materially improves geocoding, and two independent reviewers flagged it as droppable-but-dropped."},
        "district": {"type": "string", "description": "The district / industrial estate / sub-area a park or building sits within, as the source states it (e.g. 'Earlstrees Industrial Estate', 'Oakley Hay Industrial Estate'). A plain, reader-fillable field like city/park - NOT to be confused with `districtProfile`, the separate orchestrator-filled labour-market research object below."},
        "motorway": {"type": "string"},
        "mapLink": {"type": "string"},
        "brochureLink": {"type": "string", "description": "URL of the agent/landlord brochure or listing page for THIS property. Rendered as a View brochure link in the detail modal; never invented, only carried from a source that states it."},
        "description": {"type": "string"},
        "photo": {"type": "string", "description": "data:image/...;base64,... or a placeholder data URI. This is the HERO (gallery[0])."},
        "gallery": {"type": "array", "items": {"type": "string"}, "description": "Up to GALLERY_MAX photo data URIs for the carousel, best-first (photographic_score), hero first. PAGE-SCOPED so a multi-property deck contributes only this property's photos. Always contains at least [photo]; the carousel falls back to [photo] when absent."},
        "plan": {"type": "string", "description": "A site-plan image data URI. merge.py harvests it from the brochure page (page_plan: balanced white/ink signature; the hyperlinked location map and boilerplate are excluded); a standalone plan file bound by the orchestrator (extract_image.py kind=plan) takes precedence. On a plan-only page the plan also serves as the hero."},
        "districtProfile": {
          "type": "object",
          "description": "ORCHESTRATOR-FILLED: optional local labour-market micro-profile from research. The deterministic spine does not populate it; region-level workforce data lives in top-level regions{} via enrich --regions. Renamed from `district` (v38) because that key collided with the plain, reader-fillable district/estate-name STRING field every interpretation sub-agent is told is fillable - the two are unrelated concepts and must never share a key.",
          "additionalProperties": true,
          "properties": {
            "district": {"type": "string"},
            "unemployment": {"type": ["number", "string", "null"]},
            "asOf": {"type": "string"},
            "applicantsPerVacancy": {"type": ["number", "string", "null"]},
            "note": {"type": "string"}
          }
        },
```

(Note: `district` moved up next to `postcode` since it is now grouped with the other plain-string location fields, matching `gate_runner.py`'s `PROV_ADVISE_FIELDS` grouping of `{city, district, park, address, postcode}`; `districtProfile` stays where the old `district` object was, right after `plan`.)

- [ ] **Step 4: Edit `helpers/merge.py`**

Docstring at line ~75-78, currently:

```python
    NOT a canonical field (a stray provenance/meta map), or (b) a scalar whose value is a
    pipeline locator string. Genuine scalar attributes (canonical AND brand-new) and
    canonical container objects (gallery/preBaked/district) are KEPT so auto-show is
    preserved. Deterministic; a clean record is unchanged."""
```

Change `district` to `districtProfile`:

```python
    NOT a canonical field (a stray provenance/meta map), or (b) a scalar whose value is a
    pipeline locator string. Genuine scalar attributes (canonical AND brand-new) and
    canonical container objects (gallery/preBaked/districtProfile) are KEPT so auto-show is
    preserved. Deterministic; a clean record is unchanged."""
```

`_OV_FORBIDDEN` at lines 184-185, currently:

```python
_OV_FORBIDDEN = frozenset({"id", "__meta", "hero", "gallery", "plan", "preBaked", "photo",
                           "district", "regionCode"})
```

Change to:

```python
_OV_FORBIDDEN = frozenset({"id", "__meta", "hero", "gallery", "plan", "preBaked", "photo",
                           "districtProfile", "regionCode"})
```

- [ ] **Step 5: Edit `helpers/_common.py`**

Docstring at line ~484-487, currently:

```python
def canonical_property_fields() -> frozenset:
    """Property field names the SCHEMA declares ($defs.property.properties) UNION every
    p.<field> the template reads. Used to protect canonical CONTAINER objects
    (gallery/preBaked/district) at the merge boundary and by the render-boundary gate.
    NOT a display allowlist for scalars: any real scalar attribute still auto-shows."""
```

Change `district` to `districtProfile`:

```python
def canonical_property_fields() -> frozenset:
    """Property field names the SCHEMA declares ($defs.property.properties) UNION every
    p.<field> the template reads. Used to protect canonical CONTAINER objects
    (gallery/preBaked/districtProfile) at the merge boundary and by the render-boundary gate.
    NOT a display allowlist for scalars: any real scalar attribute still auto-shows."""
```

`IDENTIFIER_FIELDS` at line ~525-533, currently:

```python
IDENTIFIER_FIELDS = frozenset({
    "id", "country", "developer", "park", "city", "landlord", "motorway", "region", "regionCode",
    "lat", "lng", "coordsApprox", "breeam", "rentUnit", "areaUnit", "mapLink", "photo", "gallery",
    "plan", "preBaked", "district", "reit",
    "warehouseRentVal", "officeRentVal", "officeAreaVal", "expansionParkVal",
    # rent/price/area strings are figure+unit+currency -> kept verbatim (source convention)
    "warehouseRent", "officeRent", "serviceCharge", "landPrice", "plotArea", "warehouseArea",
    "officeArea", "divisibleFrom", "earlyAccess",
})
```

Add `"districtProfile"` alongside the existing `"district"` (both now need protection - one as a proper-noun name, one as a structural container):

```python
IDENTIFIER_FIELDS = frozenset({
    "id", "country", "developer", "park", "city", "landlord", "motorway", "region", "regionCode",
    "lat", "lng", "coordsApprox", "breeam", "rentUnit", "areaUnit", "mapLink", "photo", "gallery",
    "plan", "preBaked", "district", "districtProfile", "reit",
    "warehouseRentVal", "officeRentVal", "officeAreaVal", "expansionParkVal",
    # rent/price/area strings are figure+unit+currency -> kept verbatim (source convention)
    "warehouseRent", "officeRent", "serviceCharge", "landPrice", "plotArea", "warehouseArea",
    "officeArea", "divisibleFrom", "earlyAccess",
})
```

- [ ] **Step 6: Edit `assets/dashboard_template.html`**

Line 2113, currently:

```javascript
  const dist = p.district || null;
```

Change to:

```javascript
  const dist = p.districtProfile || null;
```

This is the ONLY `p.district` reference in the whole template (verified by grep before starting this task) - every other `district`-containing string in the file (`district-panel`, `district-label`, `district-name`, `district-metric`, `district-note`, `T("wf_district_label")`, `dist.district`/`dist.unemployment`/`dist.asOf`/`dist.applicantsPerVacancy`/`dist.note`) is either a CSS class name, an i18n label key, or a property access on the LOCAL `dist` variable (not on `p`) - none of those reference the canonical schema key and none need to change.

- [ ] **Step 7: Bump `assets/VERSION`**

Compute the new CRLF-normalised text hash of the just-edited template:

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python -c "
import hashlib
from pathlib import Path
text = Path('assets/dashboard_template.html').read_text(encoding='utf-8')
print(hashlib.sha256(text.encode('utf-8')).hexdigest())
"
```

Write `assets/VERSION` (replacing its current two lines) with:

```
v38
chrome_sha256=<paste the hash Step 7's command printed>
```

- [ ] **Step 8: Add the v38 changelog entry to `reference/template-contract.md`**

Immediately after the existing `- **v37** ...` paragraph (the last entry before the `## Generalising to a new reference look` section), add:

```markdown

- **v38** the reserved labour-market micro-profile object is renamed from `district` to `districtProfile`. `district` collided with the single most natural open-schema key a reader would pick for "the industrial estate / sub-area a park sits within" - `reference/interpretation.md`'s own live-generated `fields` array already advertised `district` as reader-fillable (it is derived from `canonical.schema.json`'s top-level keys), and `gate_runner.py`'s `PROV_ADVISE_FIELDS` already grouped `district` with `city`/`park`/`address`/`postcode` as a checkable plain string - but the schema typed top-level `district` as an OBJECT, so a reader that (correctly, per its own contract) wrote a plain estate name into it hard-blocked `validate-data` with "'X' is not of type 'object'". `district` is now a first-class STRING field (grouped with `city`/`park`/`postcode`); the renamed `districtProfile` object is otherwise unchanged (still orchestrator-filled only, never populated by the deterministic spine - nothing in `helpers/` writes to it). One template line moved: `p.district` -> `p.districtProfile` (the workforce panel's `const dist = ...` assignment); every `district`-named CSS class and i18n label (`district-panel`, `wf_district_label`, ...) is a UI label, not a JSON key, and is untouched. Eval: `evals/district_field_test.py`.
```

Also update the version-number reference near the top of the "Versioning" section (the sentence beginning "The current template is **v32**, cumulative..."): change `**v32**` to `**v38**` (this sentence is already stale relative to v33-v37 documented further down; correcting it to v38 fixes it for the first time in this pass rather than compounding the drift further).

- [ ] **Step 9: Run `make_integrity.py` (required after any helper/template edit)**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python helpers/make_integrity.py
```

Expected: exits cleanly, regenerating the integrity manifest to reflect the edited files.

- [ ] **Step 10: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/district_field_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 11: Run the template-contract-mandated eval set for any hand-edit**

Per `reference/template-contract.md`'s hand-edit order (step 5): run `smoke_test.py`, `i18n_test.py`, `compare_test.py`, `flyover_test.py`, `numguard_test.py`, and `areaunit_test.py` explicitly, plus the two evals that reference `district`/`canonical_property_fields()` directly:

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && \
python evals/smoke_test.py && \
python evals/i18n_test.py && \
python evals/compare_test.py && \
python evals/flyover_test.py && \
python evals/numguard_test.py && \
python evals/areaunit_test.py && \
python evals/prov_containment_test.py && \
python evals/capture_contract_test.py
```

Expected: every one `STATUS: ALL-PASS` / `PASS`. `smoke_test.py` re-asserts the three data blocks round-trip and the chrome is byte-stable against the NEW `VERSION` hash from Step 7 - if this fails with a SHA mismatch, the hash in Step 7 was computed or pasted wrong; recompute and re-check, do not skip. `prov_containment_test.py` and `capture_contract_test.py` are the two evals identified during planning as directly touching `district`/`PROV_ADVISE_FIELDS` or the SKILL.md/gates.md prose - both should already pass unchanged (neither asserts anything about the OBJECT vs STRING type, only that the flat string-field set and the doc mentions are intact).

- [ ] **Step 12: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: all-clear.

---

### Task 5: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete eval suite**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py
```

Expected: every eval `PASS`/`ALL-PASS`, final summary line reports 0 failures across all 60+ evals. This is the skill's own documented bar for shipping any helper/template edit (`SKILL.md` "Maintenance").

- [ ] **Step 2: If anything fails, fix forward - do not skip evals to get a green run**

If a failure surfaces that Tasks 1-4 didn't anticipate, treat it as a real regression: read the failing eval's assertion, trace it to the specific edit that broke it, and fix that edit (consulting the dated backup from Task 0 for the exact prior text if needed). Re-run the full suite after any fix.

- [ ] **Step 3: Re-run `make_integrity.py` once more as a final check**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python helpers/make_integrity.py
```

Expected: clean exit, no "file changed since manifest" advisories for any file this plan touched.

- [ ] **Step 4: Leave the Task 0 backup in place**

Do not delete `cbre-property-longlist.backup-2026-08-15` - it is the only revert path for this non-git directory. It is safe to remove manually later, once the next several real client runs confirm the four fixes behave correctly in practice.
