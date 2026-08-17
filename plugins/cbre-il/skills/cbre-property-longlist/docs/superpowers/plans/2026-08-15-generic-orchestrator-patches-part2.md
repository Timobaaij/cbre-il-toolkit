# Generic Orchestrator-Patch Fixes Part 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four more generic, client-agnostic bugs found during the same live Corby, UK run of the `cbre-property-longlist` skill covered by `2026-08-15-generic-orchestrator-patches.md` (items 1/5/8/10 there; this plan covers items 2/3/6/9 from the same top-10 analysis): a certification field (BREEAM/EPC) that can silently ship an overclaimed "achieved" grade when the true source says "Target"; a tracker-mapping diff that reports a phantom disagreement whenever two semantically-equivalent maps express a column's basis two different (both valid) ways, producing a misleading Gaps Report disclosure; an open (reader-invented) schema field that can silently carry a list/object value with no clear error until a confusing downstream ledger failure; and an orchestrator hand-off message that tells the orchestrator to run `deliver.py`/`final_gate.py` without giving their required arguments.

**Architecture:** Each fix is independent and touches a disjoint set of files. None require the frozen `dashboard_template.html` or a version bump (unlike Part 1's Task 4) - these are all backend/orchestration logic and schema/prose changes.

**Tech Stack:** Python 3 (stdlib `re`, `json`), the skill's own `evals/*.py` harness (plain scripts with `sys.exit`, no pytest), JSON Schema (Draft 2020-12, via the `jsonschema` package).

## Global Constraints

- Same non-git environment as Part 1: `C:\Users\TBaaij\.claude\skills\cbre-property-longlist` has no `.git`. The Part 1 dated backup (`cbre-property-longlist.backup-2026-08-15`) is still the revert path for every file this plan touches too - do not create a second backup, and do not touch that folder.
- **Sequencing note:** if Part 1's plan is being executed at the same time (in a separate task track), the two plans touch DISJOINT files except that both may run `python evals/run_all.py --quick` and `python evals/run_all.py` concurrently - that is safe (read-only regression checks, no shared mutable state). Neither plan's tasks depend on the other's changes.
- Every change must stay **fully generic** - no client name, no run-specific filename, no tailoring to the Corby dataset. Every new test fixture uses synthetic/generic data.
- After **every** task: run that task's own new/modified eval file directly, then run `python evals/run_all.py --quick` as a fast regression check.
- After the **last** task: run the **full** `python evals/run_all.py` (all 60+ evals) - the skill's own documented bar for shipping any helper edit (`SKILL.md` "Maintenance").
- All file paths below are absolute Windows paths rooted at `C:\Users\TBaaij\.claude\skills\cbre-property-longlist\`.

---

### Task 1: Give the orchestrator hand-off the FULL, copy-paste-ready `deliver.py`/`final_gate.py` commands

**Files:**
- Modify: `helpers/run.py:3364-3376` (the exit-0 QA-window hand-off message)
- Create: `evals/handoff_commands_test.py`

**Interfaces:**
- Consumes: the local variables already in scope at this point in `run.py`'s `main()` - `work`, `canonical`, `built`, `ledger_csv`, `deliverables`, `args.client`, `filename` (all already used a few lines earlier at `run.py:3332-3334`'s own internal `call(deliver, "--canonical", canonical, "--html", built, "--ledger", ledger_csv, "--out-dir", deliverables, "--slug", args.client, "--filename", filename)`)
- Produces: nothing new consumed elsewhere - this only changes the printed STRING an orchestrator reads, never a return value or file

**The bug:** the hand-off message printed at exit 0 (spine done, QA window next) tells the orchestrator to "deliver" and run `` `final_gate.py ... --qa-state {work}` `` - the `...` is a literal ellipsis, not a placeholder resolved to real values. An orchestrator following this text literally must GUESS `deliver.py`'s and `final_gate.py`'s required flags, which costs one or more failed invocations (both scripts `argparse`-error on missing required arguments) before landing on the correct command - exactly what happened on the live run. Every value needed to build the full command is already a local variable a few lines above in the same function.

- [ ] **Step 1: Write the failing test**

Create `evals/handoff_commands_test.py`:

```python
#!/usr/bin/env python3
"""handoff_commands_test.py - the exit-0 QA-window hand-off gives the orchestrator FULL,
copy-paste-ready deliver.py/final_gate.py commands, never an ellipsis or a bare word.

THE DEFECT: the hand-off message printed at "spine done" told the orchestrator to
"deliver" (no command) and run `final_gate.py ... --qa-state {work}` (a literal ellipsis).
Every value needed to build the real command - --canonical, --html, --ledger, --out-dir,
--slug, --filename for deliver.py; --canonical, --html, --deliverables, --reviews,
--qa-state for final_gate.py - is already a local variable a few lines above in the SAME
function (run.py's own internal deliver.py call at line ~3332 proves it). An orchestrator
without those flags memorised had to discover them by triggering argparse's "required
arguments" error on both scripts before finding the right invocation - avoidable friction on
every future run, not just this one.

Source-text pin (matching this suite's convention for pipeline-wiring checks, e.g.
gate1_automation_test.py): the hand-off string must contain the actual flag names for
BOTH scripts, and must not contain a literal ellipsis standing in for arguments. Offline."""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def main() -> int:
    src = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    start = src.find('"(orchestrator: spine done')
    ck(start != -1, "run.py has the exit-0 QA-window hand-off message")
    # isolate just the _say_orchestrator(...) call so a match elsewhere in the file
    # (e.g. a different hand-off for a different exit code) cannot satisfy the pin
    end = src.find('return\n', start) if start != -1 else -1
    block = src[start:end] if start != -1 and end != -1 else ""

    ck("deliver.py --canonical" in block,
       "the hand-off gives the full deliver.py command, not the bare word 'deliver'")
    for flag in ("--canonical", "--html", "--ledger", "--out-dir", "--slug", "--filename"):
        ck(flag in block.split("deliver.py", 1)[-1].split("final_gate.py", 1)[0],
           f"deliver.py's hand-off command includes {flag}")

    ck("final_gate.py --canonical" in block,
       "the hand-off gives the full final_gate.py command, starting with --canonical")
    fg_part = block.split("final_gate.py", 1)[-1] if "final_gate.py" in block else ""
    for flag in ("--canonical", "--html", "--deliverables", "--reviews", "--qa-state"):
        ck(flag in fg_part, f"final_gate.py's hand-off command includes {flag}")

    ck("final_gate.py ..." not in block,
       "the old ellipsis placeholder for final_gate.py's arguments is gone")

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
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/handoff_commands_test.py
```

Expected: multiple `[FAIL]` lines (the hand-off still says bare "deliver" and has the ellipsis), `STATUS: BLOCKED`.

- [ ] **Step 3: Implement the fix in `helpers/run.py`**

The block currently reads (lines 3364-3376):

```python
        _say_orchestrator(
              "(orchestrator: spine done - run the remaining AGENTIC steps per SKILL.md "
              "(emails/region research as configured, then the isolated G-honesty / G-trace / "
              "G-images / G-visual reviewers). The QA window is ONE review pass: the reviewers "
              "PROPOSE findings, you IMPLEMENT them, then deliver. Dispatch the gate batch "
              f"concurrently -> `gate_runner.py qa-round record --work {work} --reviews "
              f"{work}\\reviews` -> implement each `blocking:` finding and record it with "
              "`qa-round resolve --id <id> --because \"<what you changed>\"` -> deliver -> "
              f"`final_gate.py ... --qa-state {work}`. Advisory findings are CARRIED to the Gaps "
              "Report's 'Known limitations', not fixed and not re-reviewed. There is no second "
              "review pass and no adjudication round. final_gate.py is the ship backstop - it "
              "blocks while any blocking finding has no recorded repair; do not declare done to "
              "the broker until it passes.)")
```

Replace it with:

```python
        _say_orchestrator(
              "(orchestrator: spine done - run the remaining AGENTIC steps per SKILL.md "
              "(emails/region research as configured, then the isolated G-honesty / G-trace / "
              "G-images / G-visual reviewers). The QA window is ONE review pass: the reviewers "
              "PROPOSE findings, you IMPLEMENT them, then deliver. Dispatch the gate batch "
              f"concurrently -> `gate_runner.py qa-round record --work {work} --reviews "
              f"{work}\\reviews` -> implement each `blocking:` finding and record it with "
              "`qa-round resolve --id <id> --because \"<what you changed>\"` -> deliver: "
              f"`deliver.py --canonical {canonical} --html {built} --ledger {ledger_csv} "
              f"--out-dir {deliverables} --slug {args.client} --filename {filename}` -> "
              f"`final_gate.py --canonical {canonical} --html {built} --deliverables "
              f"{deliverables} --reviews {work}\\reviews --qa-state {work}`. Advisory findings "
              "are CARRIED to the Gaps Report's 'Known limitations', not fixed and not "
              "re-reviewed. There is no second review pass and no adjudication round. "
              "final_gate.py is the ship backstop - it blocks while any blocking finding has no "
              "recorded repair; do not declare done to the broker until it passes.)")
```

(Note: `deliver` -> `deliver:` before the backtick-quoted command reads more naturally than `deliver ->`, since the arrow already appears before `final_gate.py`; either punctuation is acceptable as long as the full commands appear - the eval only checks for the flag substrings, not exact punctuation.)

- [ ] **Step 4: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/handoff_commands_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 5: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: all-clear.

---

### Task 2: Make a tracker-basis "disagreement" disclose the qualifier-column mechanism honestly, instead of implying pass 1 read nothing

**REVISION NOTE (post-review redesign):** the first version of this task tried to make `diff_tracker_maps` treat a qualifier-column-resolved basis and a direct-attribute basis as EQUIVALENT (suppress the diff entirely). An independent task reviewer proved that design wrong on two counts: (1) a per-row qualifier column's actual values are UNKNOWN at map-comparison time (the map only says WHICH column supplies the basis, never what that column's cells actually contain), so "GIA" (direct) can never be mechanically PROVEN equal to "resolved per-row via column 39" (indirect) - collapsing them into one sentinel string was a category error, and the eval that appeared to pass had been quietly reshaped (an unplanned `"basis": "GIA"` added directly to the qualifier column) to dodge exactly this; (2) comparing "basis" at the QUALIFIER COLUMN'S OWN index (e.g. 39) produced a brand-new spurious disagreement that did not exist before the change, because a role:size_basis column has no "basis" of its own to compare. The corrected design below does NOT try to prove equivalence - it keeps reporting the pair as a disagreement (honestly: it IS unverifiable from the map alone) but replaces a bare, misleading `None` with a value that names the actual mechanism, and it skips the comparison entirely at a qualifier column's own index so that column never generates diff noise about a "basis" it was never meant to carry.

**Files:**
- Modify: `helpers/extract_xlsx.py:959-1001` (`diff_tracker_maps`; add a new `_basis_display` helper just above it)
- Create: `evals/tracker_basis_diff_test.py`

**Interfaces:**
- Consumes: nothing new (the existing `_VERIFY_KEYS`, `_verify_norm` module-level names in `extract_xlsx.py`)
- Produces: `diff_tracker_maps(map1, map2, header_row=None) -> list[dict]` - SAME signature and SAME output shape (`{index, header, key, pass1, pass2}` dicts). For `key == "basis"`: a column whose OWN `role` is `size_basis` on either side is skipped entirely (no diff ever emitted for it); every other column's `basis` value is passed through `_basis_display`, which returns the raw attribute unchanged when present, and otherwise names the qualifier-column mechanism (`"(resolved per-row via qualifier column N, not a fixed value)"`) instead of a bare `None` - the pair still counts as a disagreement (unverifiable, so still surfaced), but the DISCLOSED values are now honest about why.

**The bug:** a tracker column's basis (GIA/GEA/GLA/warehouse) can be stated TWO valid ways per `reference/interpretation.md`'s "Tracker mode" contract: (a) a `"basis"` attribute directly on the size column's own map entry, or (b) a SEPARATE column flagged `"role": "size_basis"`, whose PER-ROW values supply the same information at PARSE time - information `diff_tracker_maps` cannot see, because it only has the column MAP, never the underlying sheet data. On a live run, the primary map expressed basis via (b) (a size column with no `basis` attribute of its own, `basis=None`) while the independent verify pass expressed it via (a) (`basis="GIA"` directly). The diff reported `pass1=None, pass2="GIA"`, and the Gaps Report disclosed this to the broker as "the dashboard used pass 1" - a sentence that reads as pass 1 having NO answer at all, when in fact pass 1 had wired a legitimate (if unverifiable-from-here) alternative mechanism. The fix does not (and cannot) prove the two mechanisms agree; it makes the disclosed values say what actually happened.

- [ ] **Step 1: Write the failing test**

Create `evals/tracker_basis_diff_test.py`:

```python
#!/usr/bin/env python3
"""tracker_basis_diff_test.py - a size column's basis resolved via a role:size_basis
qualifier column must be DISCLOSED as such (naming the mechanism), never as a bare `None`
that reads as "this pass had no answer" - and the qualifier column's OWN index must never
generate "basis" diff noise, since a role:size_basis column has no basis of its own.

THE DEFECT: diff_tracker_maps compared each column's raw `.get("basis")` by index only,
blind to a role:size_basis companion column supplying the SAME information per-row at
PARSE time (information the map itself does not contain). A live run's primary map
expressed a size column's basis via a size_basis qualifier column (basis=None on the size
column itself, by design); the independent verify pass expressed the same conclusion as a
direct "GIA" attribute. The diff reported pass1=None, pass2="GIA", and the Gaps Report
disclosed this as "the dashboard used pass 1" - reading as pass 1 having NO answer, when it
had a legitimate alternative mechanism. NOTE: this does NOT try to prove the two mechanisms
are equivalent (that is unverifiable from the map alone, since the qualifier column's real
per-row values are unknown here) - it is still reported as a disagreement, but with an
honest value naming the mechanism instead of a bare None.

The must-NOT-regress cases matter as much as the fix: a GENUINE basis disagreement (two
DIRECT attributes that actually differ, e.g. GIA vs GEA) must still be reported unchanged; a
column with NEITHER a direct basis NOR any qualifier column on either side is a genuine gap
and must still be reported; a non-basis key (e.g. "field") must be completely unaffected;
and - the regression an earlier attempt at this fix introduced - the qualifier column's OWN
index must produce ZERO "basis" diffs, on either side, in every case below. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import extract_xlsx as X  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _map(columns):
    return {"columns": columns}


def main() -> int:
    print("== the live defect: qualifier-column basis vs direct-attribute basis ==")
    # pass 1 (the primary map): size column (idx 38) has NO basis attribute of its own;
    # a separate column (idx 39) is flagged role:size_basis - the per-row qualifier that
    # supplies the basis instead, EXACTLY as reference/interpretation.md documents it (the
    # qualifier column itself carries no "basis" attribute - that is the whole point of it).
    pass1 = _map([
        {"index": 38, "field": "warehouseArea", "areaUnit": "sq ft"},
        {"index": 39, "field": None, "role": "size_basis"},
    ])
    # pass 2 (the blind verify): same size column, basis stated directly as "GIA", no
    # qualifier column at all.
    pass2 = _map([
        {"index": 38, "field": "warehouseArea", "areaUnit": "sq ft", "basis": "GIA"},
    ])
    diffs = X.diff_tracker_maps(pass1, pass2)
    basis38 = [d for d in diffs if d["key"] == "basis" and d["index"] == 38]
    ck(len(basis38) == 1,
       f"the pair is still surfaced as a disagreement (unverifiable from the map alone), "
       f"exactly once (got {diffs!r})")
    if basis38:
        ck(basis38[0]["pass1"] is not None and "39" in str(basis38[0]["pass1"]),
           f"pass1's disclosed value NAMES the qualifier column (39), instead of a bare "
           f"None that reads as 'no answer at all' (got {basis38[0]['pass1']!r})")
        ck(basis38[0]["pass2"] == "GIA",
           f"pass2's disclosed value is untouched - it had a direct attribute "
           f"(got {basis38[0]['pass2']!r})")
    ck(not any(d["key"] == "basis" and d["index"] == 39 for d in diffs),
       f"the qualifier column's OWN index (39) produces ZERO basis diffs - it has no basis "
       f"of its own to compare (got {diffs!r})")

    print()
    print("== must NOT suppress a GENUINE basis disagreement (two direct attributes) ==")
    pass1_gia = _map([{"index": 38, "field": "warehouseArea", "basis": "GIA"}])
    pass2_gea = _map([{"index": 38, "field": "warehouseArea", "basis": "GEA"}])
    diffs2 = X.diff_tracker_maps(pass1_gia, pass2_gea)
    ck(any(d["key"] == "basis" and d["index"] == 38
           and d["pass1"] == "GIA" and d["pass2"] == "GEA" for d in diffs2),
       f"GIA vs GEA (two direct attributes, genuinely different) still reported unchanged "
       f"(got {diffs2!r})")

    print()
    print("== must NOT suppress a genuine gap (neither side resolves the basis at all) ==")
    pass1_none = _map([{"index": 38, "field": "warehouseArea"}])
    pass2_gia = _map([{"index": 38, "field": "warehouseArea", "basis": "GIA"}])
    diffs3 = X.diff_tracker_maps(pass1_none, pass2_gia)
    ck(any(d["key"] == "basis" and d["index"] == 38 and d["pass1"] is None
           and d["pass2"] == "GIA" for d in diffs3),
       f"a genuinely unresolved side (no attribute, no qualifier column anywhere on that "
       f"side) still shows a bare None - there is no mechanism to name "
       f"(got {diffs3!r})")

    print()
    print("== other _VERIFY_KEYS are completely unaffected ==")
    pass1_field = _map([{"index": 5, "field": "park"}])
    pass2_field = _map([{"index": 5, "field": "developer"}])
    diffs4 = X.diff_tracker_maps(pass1_field, pass2_field)
    ck(any(d["key"] == "field" and d["pass1"] == "park" and d["pass2"] == "developer"
           for d in diffs4),
       f"a genuine field-binding disagreement is still reported unchanged (got {diffs4!r})")

    print()
    print("== the qualifier index produces no diff even when only ONE side has it ==")
    only_one_side = _map([{"index": 38, "field": "warehouseArea"}])  # pass2 has nothing at 39
    diffs5 = X.diff_tracker_maps(pass1, only_one_side)
    ck(not any(d["key"] == "basis" and d["index"] == 39 for d in diffs5),
       f"index 39 exists only in pass1 (as the qualifier column) and absent entirely from "
       f"pass2 - still zero basis diffs there (got {diffs5!r})")

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
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/tracker_basis_diff_test.py
```

Expected: `[FAIL]` on "pass1's disclosed value NAMES the qualifier column" (current code reports a bare `None`) and possibly on the index-39 checks, `STATUS: BLOCKED`.

- [ ] **Step 3: Implement the fix in `helpers/extract_xlsx.py`**

Immediately above `def diff_tracker_maps(...)` (line 959), insert:

```python
def _basis_display(map_: dict, idx: int, raw) -> str | None:
    """The value to SHOW for this column's basis in a semantic-disagreement report. `raw`
    is the column's own `.get("basis")` - returned unchanged when present. When absent, this
    does NOT invent an equivalence: a role:size_basis qualifier column's actual per-row
    values are unknown at map-comparison time (the map only says WHICH column supplies the
    basis, never what that column's cells contain), so an indirectly-resolved basis can
    never be mechanically PROVEN equal to a directly-stated one - the pair is still reported
    as a disagreement. This only replaces a bare, misleading `None` (which reads as "this
    pass had no answer at all") with a value that names the actual mechanism, so the
    downstream disclosure ("pass 1 read X, pass 2 read Y") is honest about what pass 1
    actually did, instead of implying it left the basis completely unresolved."""
    if raw:
        return str(raw)
    cols = (map_ or {}).get("columns", []) if isinstance(map_, dict) else []
    qualifier_idx = next((c.get("index") for c in cols
                          if isinstance(c, dict)
                          and str(c.get("role") or "").strip().lower() == "size_basis"),
                         None)
    if qualifier_idx is not None:
        return f"(resolved per-row via qualifier column {qualifier_idx}, not a fixed value)"
    return None
```

Then, inside `diff_tracker_maps`, change the value-lookup line. The loop currently reads (lines 990-994):

```python
    for idx in set(a) | set(b):
        ca, cb = a.get(idx, {}), b.get(idx, {})
        for key in _VERIFY_KEYS:
            va, vb = ca.get(key), cb.get(key)
            if _verify_norm(va) != _verify_norm(vb):
```

Change to:

```python
    for idx in set(a) | set(b):
        ca, cb = a.get(idx, {}), b.get(idx, {})
        for key in _VERIFY_KEYS:
            if key == "basis":
                # a role:size_basis column has no "basis" of its own to compare - it IS the
                # mechanism another column resolves through, so comparing it against itself
                # (or against the other map's absence of any column at this index) is noise,
                # never a genuine disagreement. Skip the key entirely at this index.
                a_role = str(ca.get("role") or "").strip().lower()
                b_role = str(cb.get("role") or "").strip().lower()
                if a_role == "size_basis" or b_role == "size_basis":
                    continue
                va = _basis_display(map1, idx, ca.get("basis"))
                vb = _basis_display(map2, idx, cb.get("basis"))
            else:
                va, vb = ca.get(key), cb.get(key)
            if _verify_norm(va) != _verify_norm(vb):
```

Everything else in the function (the `header`/`diffs.append`/`diffs.sort`/`return diffs` lines) is unchanged.

- [ ] **Step 4: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/tracker_basis_diff_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 5: Run the sibling tracker eval to confirm no regression**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/tracker_sample_test.py
```

Expected: passes exactly as before (that file only mentions `diff_tracker_maps` in a docstring narrative; it does not call it, so it cannot be affected by this change - running it is a sanity check, not a targeted regression test).

- [ ] **Step 6: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: all-clear.

---

### Task 3: Never let a "Target"/"Targeting"/"Targeted" hedge silently disappear on a certification field

**Files:**
- Modify: `helpers/merge.py:1053-1156` (`merge_cluster`'s per-field precedence loop; add a small helper above it)
- Create: `evals/qualifier_upgrade_test.py`

**Interfaces:**
- Consumes: the existing `_ENUM_EQ_FIELDS`, `_values_equivalent` module-level names in `merge.py`
- Produces: `merge_cluster(cluster, decisions=None, variants=None) -> (out, prov, conflicts)` - SAME signature and SAME 3-tuple shape; only the VALUE chosen for `breeam`/`epc` changes in the one specific case where two notation-equivalent values disagree solely on a Target-style hedge

**IMPORTANT - do not touch `_values_equivalent`, `_ENUM_STRIP_RX`, or `_enum_token`.** `evals/value_equivalence_test.py:53` DELIBERATELY pins `EQ("breeam", "Excellent", "Target BREEAM Excellent") == True` as INTENDED behaviour (the comment reads "the BREEAM word and Target drop out") - that equivalence check itself is correct and must not change. The bug is downstream: once two values are correctly recognised as equivalent (same underlying grade), `merge_cluster` currently keeps whichever one happened to win precedence, with no regard for which of the two equivalent SPELLINGS is safe to show. This task adds that missing check without touching the equivalence logic itself.

**The bug, confirmed against this codebase's own precedence tables:** `breeam` is in `TRACKER_AUTHORITATIVE` (merge.py:542-546), so a "rich" tracker (`__meta.tracker_rich: true`) wins the precedence contest for `breeam` over a brochure - `epc` is NOT in that set, so a brochure correctly wins `epc` regardless. On a live run, the tracker stated `breeam: "Excellent"` and the brochure (a building still under construction) stated `breeam: "Target Excellent"`; the tracker won precedence (rich-tracker-authoritative for `breeam`), so the dashboard shipped "Excellent" - an ACHIEVED certification the building does not yet hold - while the SAME property's `epc` correctly kept the brochure's "Target A" (since `epc` uses ordinary spec-precedence, brochure wins). The two fields, describing the same building in the same state, disagreed on whether to keep the hedge, for reasons that have nothing to do with which value is actually more accurate.

- [ ] **Step 1: Write the failing test**

Create `evals/qualifier_upgrade_test.py`:

```python
#!/usr/bin/env python3
"""qualifier_upgrade_test.py - a "Target"/"Targeting"/"Targeted" hedge on a certification
field (breeam/epc) never silently disappears just because the un-hedged notation happens
to win source precedence.

THE DEFECT: `breeam` is TRACKER_AUTHORITATIVE, so a rich tracker's bare "Excellent" beats a
brochure's "Target Excellent" on PRECEDENCE alone - even though _values_equivalent correctly
recognises them as the SAME underlying grade (evals/value_equivalence_test.py:53 pins that
equivalence as intended). Once recognised as equivalent, nothing compared which of the two
equivalent SPELLINGS is safe to ship: dropping "Target" on a building still under
construction overclaims an achieved certification. A live run shipped exactly this - breeam
"Excellent" from a rich tracker, while the SAME property's epc correctly kept the brochure's
"Target A" (epc is not tracker-authoritative, so ordinary spec-precedence - brochure wins -
applied instead). The fix does NOT touch _values_equivalent/_ENUM_STRIP_RX/_enum_token -
those are correct and pinned; it only changes which of two EQUIVALENT values `merge_cluster`
keeps once they are already known to describe the same fact.

The must-NOT-fire cases matter as much as the fix: two equally-hedged (or equally bare)
equivalent values must still resolve by ordinary precedence, and a GENUINE conflict (two
DIFFERENT grades, e.g. "Excellent" vs "Very Good") must still go through the normal
conflict path, never the qualifier-upgrade path. Offline."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as M  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def trk(**fields):
    r = {"park": "P", "city": "C", "developer": "D",
         "__meta": {"source_file": "t.xlsx", "source_type": "xlsx", "tracker_rich": True,
                    "locator_base": "Tracker", "prov": {}}}
    r.update(fields)
    return r


def broc(**fields):
    r = {"park": "P", "city": "C", "developer": "D",
         "__meta": {"source_file": "d.pdf", "source_type": "pdf", "page_no": 3,
                    "locator_base": "page 4", "prov": {}}}
    r.update(fields)
    return r


def main() -> int:
    print("== the live defect: rich tracker's bare grade vs brochure's Target-hedged grade ==")
    variants: dict = {}
    out, prov, conflicts = M.merge_cluster(
        [trk(breeam="Excellent"), broc(breeam="Target Excellent")], variants=variants)
    ck(out.get("breeam") == "Target Excellent",
       f"the Target-hedged spelling ships even though the rich tracker wins ordinary "
       f"precedence for breeam (got {out.get('breeam')!r})")
    ck("breeam" not in conflicts,
       "this stays a notation variant, never a genuine conflict needing adjudication")
    ck("breeam" in variants, "the variant is still disclosed (I10), just not as a conflict")

    print()
    print("== reverse order: brochure listed first, tracker second - same outcome ==")
    out2, _p2, _c2 = M.merge_cluster(
        [broc(breeam="Target Excellent"), trk(breeam="Excellent")])
    ck(out2.get("breeam") == "Target Excellent",
       f"record order must not matter, only which value carries the hedge "
       f"(got {out2.get('breeam')!r})")

    print()
    print("== epc is unaffected (not TRACKER_AUTHORITATIVE - brochure already wins precedence) ==")
    out3, _p3, _c3 = M.merge_cluster(
        [trk(epc="A"), broc(epc="Target A")])
    ck(out3.get("epc") == "Target A",
       f"epc already kept the hedge before this fix (ordinary spec precedence); confirm "
       f"it still does (got {out3.get('epc')!r})")

    print()
    print("== must NOT fire when BOTH sides already carry (or both lack) the hedge ==")
    out4, _p4, _c4 = M.merge_cluster(
        [trk(breeam="Target Excellent"), broc(breeam="Excellent, Target BREEAM")])
    ck(out4.get("breeam") == "Target Excellent",
       f"the tracker's own value (already hedged) wins ordinary precedence unchanged "
       f"(got {out4.get('breeam')!r})")

    print()
    print("== must NOT suppress a GENUINE grade conflict ==")
    out5, _p5, conflicts5 = M.merge_cluster(
        [trk(breeam="Excellent"), broc(breeam="Very Good")])
    ck("breeam" in conflicts5,
       f"two DIFFERENT grades are a real conflict, not a qualifier upgrade "
       f"(got out={out5.get('breeam')!r}, conflicts={conflicts5!r})")

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
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/qualifier_upgrade_test.py
```

Expected: `[FAIL]` on the first two checks (current code ships the tracker's bare "Excellent", dropping the brochure's "Target"), `STATUS: BLOCKED`.

- [ ] **Step 3: Implement the fix in `helpers/merge.py`**

Immediately above `def merge_cluster(...)` (line 1053), insert:

```python
_QUALIFIER_RX = re.compile(r"\btarget(?:ing|ed)?\b", re.I)
# certification-like fields where dropping a "Target"/"Targeting"/"Targeted" hedge is not
# mere notation - it silently converts an ASPIRATION on a not-yet-certified building into a
# claim of an ACHIEVED fact. Scoped narrowly (NOT all of _ENUM_EQ_FIELDS): `status` legitimately
# drops "now"/"immediately" as pure notation with no achieved-vs-aspirational ambiguity.
_QUALIFIER_PREFER_FIELDS = {"breeam", "epc"}


def _more_qualified(field: str, a, b) -> bool:
    """True if `b` states a Target/Targeting/Targeted hedge that `a` lacks, for a field where
    dropping that hedge overclaims a not-yet-achieved fact. Callers only reach this once `a`
    and `b` are ALREADY known equivalent (_values_equivalent) - same underlying grade,
    different notation - so this never decides whether two values conflict, only which of two
    equivalent spellings is safe to show."""
    if field not in _QUALIFIER_PREFER_FIELDS:
        return False
    return bool(_QUALIFIER_RX.search(str(b))) and not _QUALIFIER_RX.search(str(a))
```

Then, inside `merge_cluster`, factor the repeated `prov[field] = {...}` construction into a tiny local helper and use it in both the initial-assignment branch and the new upgrade branch. The loop currently reads (lines 1103-1137):

```python
        for r in order:
            if field not in r:
                continue
            v = r[field]
            if N.looks_unknown(v) and field not in ("landPrice", "reit"):
                continue
            meta = r.get("__meta", {})
            if chosen is None:
                chosen = v
                out[field] = v
                prov[field] = {
                    "source_file": meta.get("source_file", ""),
                    "source_type": meta.get("source_type", ""),
                    "locator": meta.get("prov", {}).get(field, meta.get("locator_base", "")),
                    # THE FOOTING OF THIS FIELD'S OWN SUPPLIER (B39). Every field resolves its
                    # own precedence contest, so an area can come from one record while
                    # `areaUnit` comes from another - and one dataset-wide label was then
                    # applied to all of them, scaling a figure by 10.7639 on a unit its own
                    # source never stated. `prov` is local to main() and never serialised into
                    # canonical, so recording it here cannot move a rendered byte.
                    # B58: a FIELD may state its own unit - a site area in acres inside a sq ft
                    # brochure is the normal UK shape. Prefer it; fall back to the record-level
                    # areaUnit. Without this the figure had nowhere to go, and two agents on one
                    # run split between dropping it and converting it themselves.
                    "areaUnitOfSource": (r.get(f"{field}Unit") or r.get("areaUnit") or None),
                }
            elif str(v) != str(chosen) and _values_equivalent(field, v, chosen):
                # I10: the same fact in different notation. NOT a conflict - but recorded, because
                # nothing may be silently dropped. It ships in its own Gaps Report section.
                # The `str(v) != str(chosen)` guard matters: an IDENTICAL value from a second record
                # was always a silent no-op and must stay one, not become a "variant" note.
                if variants is not None and field not in variants:
                    variants[field] = (
                        f"'{v}' from {meta.get('source_file','?')} states the same value as "
                        f"'{chosen}' in different notation - no action needed")
```

Change it to (the `def _prov_of` line is NEW, added once right before the `for r in order:` line; the `if chosen is None:` branch now calls it instead of inlining the dict; the new `if _more_qualified(...)` block is inserted right after the existing `variants[field] = (...)` assignment, still inside the `elif` branch):

```python
        def _prov_of(rec, meta_):
            return {
                "source_file": meta_.get("source_file", ""),
                "source_type": meta_.get("source_type", ""),
                "locator": meta_.get("prov", {}).get(field, meta_.get("locator_base", "")),
                # THE FOOTING OF THIS FIELD'S OWN SUPPLIER (B39). Every field resolves its
                # own precedence contest, so an area can come from one record while
                # `areaUnit` comes from another - and one dataset-wide label was then
                # applied to all of them, scaling a figure by 10.7639 on a unit its own
                # source never stated. `prov` is local to main() and never serialised into
                # canonical, so recording it here cannot move a rendered byte.
                # B58: a FIELD may state its own unit - a site area in acres inside a sq ft
                # brochure is the normal UK shape. Prefer it; fall back to the record-level
                # areaUnit. Without this the figure had nowhere to go, and two agents on one
                # run split between dropping it and converting it themselves.
                "areaUnitOfSource": (rec.get(f"{field}Unit") or rec.get("areaUnit") or None),
            }
        for r in order:
            if field not in r:
                continue
            v = r[field]
            if N.looks_unknown(v) and field not in ("landPrice", "reit"):
                continue
            meta = r.get("__meta", {})
            if chosen is None:
                chosen = v
                out[field] = v
                prov[field] = _prov_of(r, meta)
            elif str(v) != str(chosen) and _values_equivalent(field, v, chosen):
                # I10: the same fact in different notation. NOT a conflict - but recorded, because
                # nothing may be silently dropped. It ships in its own Gaps Report section.
                # The `str(v) != str(chosen)` guard matters: an IDENTICAL value from a second record
                # was always a silent no-op and must stay one, not become a "variant" note.
                if variants is not None and field not in variants:
                    variants[field] = (
                        f"'{v}' from {meta.get('source_file','?')} states the same value as "
                        f"'{chosen}' in different notation - no action needed")
                # B-target-qualifier: for a certificate field (breeam/epc), a "Target"/
                # "Targeting"/"Targeted" hedge is not mere notation once dropped - it is the
                # difference between an aspiration and an achieved fact. When two equivalent
                # notations disagree ONLY on that hedge, the MORE CAUTIOUS one always ships,
                # regardless of source precedence - never the reverse (_more_qualified is
                # directional: it only ever upgrades, never downgrades, an already-hedged
                # `chosen`). This never fires for a genuine conflict - that goes through the
                # `elif str(v) != str(chosen):` branch below instead, untouched.
                if _more_qualified(field, chosen, v):
                    chosen = v
                    out[field] = v
                    prov[field] = _prov_of(r, meta)
```

Everything below this (the `elif str(v) != str(chosen):` genuine-conflict branch, the `seen_vals`/`cand_recs` bookkeeping, and the rest of the function) is unchanged.

- [ ] **Step 4: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/qualifier_upgrade_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 5: Run the pinned equivalence eval to confirm it is untouched**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/value_equivalence_test.py
```

Expected: `STATUS: ALL-PASS`, unchanged - this task never modifies `_values_equivalent`/`_ENUM_STRIP_RX`/`_enum_token`, so every pinned case (including line 53's `EQ("breeam", "Excellent", "Target BREEAM Excellent")`) must still hold exactly as before.

- [ ] **Step 6: Run the sibling merge evals to confirm no regression**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/gross_basis_test.py && python evals/field_units_test.py
```

Expected: both pass unchanged - neither exercises `breeam`/`epc`, so the new `_more_qualified` branch (gated on `_QUALIFIER_PREFER_FIELDS = {"breeam", "epc"}`) never activates for their test data.

- [ ] **Step 7: Quick regression pass**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/run_all.py --quick
```

Expected: all-clear.

---

### Task 4: Reject array/object values on open (reader-invented) schema fields, with a clear error, and tell readers up front

**Files:**
- Modify: `templates/canonical.schema.json:65` (the `property` definition's `additionalProperties`)
- Modify: `helpers/run.py:168-189` (`_FIELD_RULES` - append a new numbered rule)
- Modify: `reference/interpretation.md` (the "Text mode" bullet list - add a matching bullet)
- Create: `evals/open_field_scalar_test.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `_common.validate_canonical(data) -> list[str]` (unchanged signature) now returns a non-empty list (via native `jsonschema` validation, no new Python logic) when any property carries a list/dict value on a field the schema does not explicitly declare

**The bug:** `templates/canonical.schema.json`'s `$defs.property` sets `"additionalProperties": true` (line 65) - meaning ANY undeclared ("open") field may hold ANY JSON type, including a list or a nested object. Two of four interpretation sub-agents on a live run independently wrote `sustainabilityFeatures` as a JSON array of strings and `agents` as an array of objects (the other two wrote semicolon-joined strings for the equivalent information). `validate_canonical` (jsonschema, `additionalProperties: true`) raised NOTHING - arrays and objects are perfectly valid JSON values under an unconstrained `additionalProperties`. The mistake only surfaced much later and far less clearly, as a `ledger validate` failure ("row 2: missing ['source_locator'] (field='sustainabilityFeatures')") - because the ledger-export code walks a list's ITEMS looking for their own locators, which the record's single top-level `prov[field]` string cannot supply. Nothing in `reference/interpretation.md`'s contract explicitly says "never a list or object" either - a reader reaching for a JSON array to represent "the source lists several items" is a completely natural, unprompted choice, and will recur for any client whose brochure lists e.g. several agents, several sustainability badges, or several occupiers.

- [ ] **Step 1: Write the failing test**

Create `evals/open_field_scalar_test.py`:

```python
#!/usr/bin/env python3
"""open_field_scalar_test.py - an OPEN (reader-invented, undeclared) property field must be
a scalar (string/number/bool/null), never a list or a nested object - caught immediately and
clearly by validate-data, not discovered later as a confusing ledger gate failure.

THE DEFECT: canonical.schema.json's $defs.property set additionalProperties: true, so an
undeclared field could hold ANY JSON type. Two of four interpretation sub-agents on a live
run independently wrote a JSON array (sustainabilityFeatures: [...]) and an array of objects
(agents: [{...}, ...]) for information the other two readers correctly expressed as one
semicolon-joined string. validate-data raised nothing (arrays/objects are valid under an
unconstrained additionalProperties); the mistake only surfaced later, far less clearly, as
`ledger validate`'s "missing ['source_locator']" - the ledger-export code walks a list's
items looking for their own locators, which a single top-level prov[field] string cannot
supply. This is a recurring trap: "the source lists several items" is a completely natural
reason to reach for a JSON array, for ANY client's brochure.

Offline (schema + reference/interpretation.md + run.py text checks only, no build)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _base_property(**extra):
    p = {
        "id": 1, "country": "GB", "park": "P", "developer": "D", "city": "C",
        "status": "Available", "photo": "data:image/jpeg;base64,AAAA",
    }
    p.update(extra)
    return p


def _canonical(prop):
    return {"meta": {"client": "Test", "hero": {
        "topbar_meta": "Test", "eyebrow": "Test", "title_html": "Test",
        "lede": "Test", "footer_copyright": "Test"}}, "properties": [prop],
            "pois": [], "regions": {}}


def main() -> int:
    print("== a list value on an OPEN field is now a clear validate-data error ==")
    bad = _canonical(_base_property(
        sustainabilityFeatures=["Photovoltaic roof panels", "Rainwater harvesting"]))
    errs = C.validate_canonical(bad)
    ck(bool(errs), "a list value on an undeclared field is now REJECTED by validate_canonical")
    ck(any("sustainabilityFeatures" in e for e in errs) if errs else False,
       f"...and the error names the offending field (got {errs!r})")

    print()
    print("== a dict / array-of-objects value on an OPEN field is also rejected ==")
    bad2 = _canonical(_base_property(
        agents=[{"name": "A", "email": "a@x.com"}, {"name": "B", "email": "b@x.com"}]))
    errs2 = C.validate_canonical(bad2)
    ck(bool(errs2), "an array-of-objects value on an undeclared field is rejected")

    print()
    print("== a plain scalar on an OPEN field is untouched (the common, correct case) ==")
    good = _canonical(_base_property(
        sustainabilityFeatures="Photovoltaic roof panels; Rainwater harvesting",
        agents="Alice, a@x.com; Bob, b@x.com",
        roofLights="10%", yardDepth="50m"))
    errs3 = C.validate_canonical(good)
    ck(errs3 == [], f"scalar-valued open fields still validate cleanly (got {errs3!r})")

    print()
    print("== a DECLARED array/object field (gallery, districtProfile, __meta) is unaffected ==")
    good2 = _canonical(_base_property(
        gallery=["data:image/jpeg;base64,AAAA", "data:image/jpeg;base64,BBBB"]))
    errs4 = C.validate_canonical(good2)
    ck(errs4 == [],
       f"a schema-DECLARED array field (gallery) still accepts a list (got {errs4!r})")

    print()
    print("== the schema change itself ==")
    schema = json.loads((ROOT / "templates" / "canonical.schema.json").read_text(encoding="utf-8"))
    prop_schema = schema["$defs"]["property"]
    ap = prop_schema.get("additionalProperties")
    ck(isinstance(ap, dict) and set(ap.get("type", [])) >= {"string", "number", "boolean", "null"},
       f"$defs.property.additionalProperties constrains undeclared fields to scalar types "
       f"(got {ap!r})")

    print()
    print("== the reader contract says so up front (not just a gate the reader discovers) ==")
    import run as R
    ck("NEVER a list" in R._FIELD_RULES.upper() or "NEVER A LIST" in R._FIELD_RULES.upper(),
       "run.py's _FIELD_RULES (the manifest's field_rules, handed to every reader) now bans "
       "list/object values explicitly")
    ck("scalar" in R._FIELD_RULES.lower(),
       "...and says what IS required (a scalar)")

    interp = (ROOT / "reference" / "interpretation.md").read_text(encoding="utf-8")
    ck("never a list" in interp.lower() or "never a JSON array".lower() in interp.lower(),
       "reference/interpretation.md's own Text-mode rules ALSO ban list/object values, so an "
       "orchestrator reading the contract file directly (not just the generated manifest) "
       "sees the same rule")

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
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/open_field_scalar_test.py
```

Expected: multiple `[FAIL]` lines (nothing rejects the list/dict values yet; the schema still says `additionalProperties: true`; neither prose file mentions the rule), `STATUS: BLOCKED`.

- [ ] **Step 3: Edit `templates/canonical.schema.json`**

The `property` definition currently reads (line 65, inside the surrounding block whose `required` array is `["id", "country", "park", "developer", "city", "status", "photo"]`):

```json
      "additionalProperties": true,
```

(this is the ONE at line 65, immediately after that `required` array - NOT the `additionalProperties: true` lines belonging to `meta` at line 14, `output` at line 28, `poi` at line 150, or `region` at line 163, which stay exactly as they are; and NOT line 122's `district`/`districtProfile` object's own `additionalProperties: true`, which also stays as-is since that governs what THAT nested object may contain, a separate concern).

Replace that ONE occurrence (line 65) with:

```json
      "additionalProperties": {"type": ["string", "number", "boolean", "null"]},
```

- [ ] **Step 4: Edit `helpers/run.py`'s `_FIELD_RULES`**

The string currently ends (lines 181-189):

```python
    "(4) WRITE A VALUE THE WAY THE SOURCE PRINTS IT. A dimensioned value carries its unit in "
    "the value itself - '10,000 sq. m', not '5000'; '10 m', not '10' - because the dashboard "
    "shows most fields verbatim and a bare magnitude beside a written sibling quotes a "
    "different quantity to the client. Copy the printed form; do not normalise, round or strip "
    "the unit, and do not ADD a unit the page does not print. A pure count ('72' loading docks) "
    "is correctly bare - the rule is about dimensioned quantities. If a page states a magnitude "
    "whose unit you genuinely cannot read, return the number, say so in that field's prov, and "
    "the value-format gate will surface it for the broker to settle."
)
```

Change the closing to add a fifth rule:

```python
    "(4) WRITE A VALUE THE WAY THE SOURCE PRINTS IT. A dimensioned value carries its unit in "
    "the value itself - '10,000 sq. m', not '5000'; '10 m', not '10' - because the dashboard "
    "shows most fields verbatim and a bare magnitude beside a written sibling quotes a "
    "different quantity to the client. Copy the printed form; do not normalise, round or strip "
    "the unit, and do not ADD a unit the page does not print. A pure count ('72' loading docks) "
    "is correctly bare - the rule is about dimensioned quantities. If a page states a magnitude "
    "whose unit you genuinely cannot read, return the number, say so in that field's prov, and "
    "the value-format gate will surface it for the broker to settle. "
    "(5) EVERY VALUE IS A SCALAR - a string or a number, NEVER a list or a nested object. When "
    "the page states several items for one field (several agents, several sustainability "
    "badges), join them into ONE string yourself - e.g. semicolon-separated - rather than "
    "emitting a JSON array or a list of objects. A list/object value on an open field now fails "
    "validate-data immediately with a clear message, instead of surfacing later as a confusing "
    "ledger gap."
)
```

- [ ] **Step 5: Edit `reference/interpretation.md`**

In the "### Text mode (preferred)" section, find the bullet list item beginning `- **THE SCHEMA IS OPEN.**` (part of the "Three rules" sub-list under "Fill EVERY field the page states"). Immediately after that bullet's closing sentence ("...nothing invented can hide and nothing stated need be lost."), insert a new bullet:

```markdown
  - **EVERY VALUE IS A SCALAR.** A field's value is a string or a number, never a list or a
    nested object - even when the page states SEVERAL of something (several agents, several
    sustainability badges, several occupiers). Join them into ONE string yourself (semicolon-
    separated is the house style: `"Alice, a@x.com, 07700 900001; Bob, b@x.com, 07700 900002"`),
    never a JSON array or a list of objects. This is not a style preference: the ledger records
    ONE locator per field, so a list's individual items have nowhere to attach their own
    provenance, and validate-data now rejects a list/object value on an open field outright
    rather than letting it surface later as a confusing ledger failure.
```

(Match the existing bullet's indentation and `**BOLD LEAD-IN.**` style exactly, as seen on the surrounding bullets in that same list.)

- [ ] **Step 6: Run the eval to verify it passes**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/open_field_scalar_test.py
```

Expected: all `[PASS]`, `STATUS: ALL-PASS`.

- [ ] **Step 7: Run the capture-contract eval to confirm no regression**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/capture_contract_test.py
```

Expected: `STATUS: ALL-PASS` - that eval greps `R._FIELD_RULES` for several EXISTING substrings ("NOT a limit", "STATED NEGATIVE IS DATA", "additionalProperties" or "OPEN", "never a reason") - Step 4 only APPENDS a new rule and never removes or edits the existing text those checks require, so all of them still match.

- [ ] **Step 8: Run the schema-touching evals to confirm no regression**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python evals/field_units_test.py && python evals/gross_basis_test.py
```

Expected: both pass unchanged - neither constructs a canonical record with a list/dict value on an undeclared field, so the new schema constraint never rejects their fixtures.

- [ ] **Step 9: Quick regression pass**

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

Expected: every eval `PASS`/`ALL-PASS`, 0 failures across all 60+ evals (now 60+4 = 64+, counting the four new files this plan adds). This is the skill's own documented bar for shipping any helper edit (`SKILL.md` "Maintenance"). If Part 1's plan (`2026-08-15-generic-orchestrator-patches.md`) is also complete by this point, this single run covers both plans' changes together.

- [ ] **Step 2: If anything fails, fix forward - do not skip evals to get a green run**

Read the failing eval's assertion, trace it to the specific edit that broke it, and fix that edit (consulting the Part 1 dated backup, `cbre-property-longlist.backup-2026-08-15`, for the exact prior text if needed). Re-run the full suite after any fix.

- [ ] **Step 3: Re-run `make_integrity.py`**

```bash
cd "C:/Users/TBaaij/.claude/skills/cbre-property-longlist" && python helpers/make_integrity.py
```

Expected: clean exit, no "file changed since manifest" advisories for any file this plan (or Part 1's) touched.
