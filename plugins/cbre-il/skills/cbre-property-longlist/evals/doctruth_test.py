#!/usr/bin/env python3
# (c) 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""doctruth_test.py - the docs must tell the truth about the live code. (B48-B50)

Every check pins a claim that WAS stale on 2026-08-01 and was fixed in the b48-b52 batch,
so a future patch that reintroduces the stale claim (or resurrects a dead file) goes red
here instead of misleading the next orchestrator. Assertions are on doc/manifest CONTENT
and file EXISTENCE only - no behaviour is driven, so this suite is fast and dependency-free.

Design notes (lessons already paid for):
  * labels are ASCII-only (a non-ASCII label crashes the cp1252 console even on pass);
  * patterns are the SPECIFIC stale phrasings, not broad symbols, so a legitimate future
    mention (e.g. a historical comment in match.py) can never false-trip it;
  * run.py is matched on its docstring head only - the body is free to say anything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
REF = ROOT / "reference"

fails: list[str] = []


def ck(cond: bool, label: str) -> None:
    print(("OK  " if cond else "FAIL") + " " + label)
    if not cond:
        fails.append(label)


def rd(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def main() -> int:
    skill = rd(ROOT / "SKILL.md")
    gates = rd(REF / "gates.md")
    visual = rd(REF / "visual-qa.md")
    loc = rd(REF / "localisation.md")
    config = rd(REF / "config.md")
    pipeline = rd(REF / "pipeline.md")
    dataeng = rd(REF / "data-engine.md")
    failmodes = rd(REF / "failure-modes.md")
    contract = rd(REF / "template-contract.md")
    trace = rd(REF / "source-traceability.md")
    gr = rd(HELPERS / "gate_runner.py")
    run_head = "\n".join(rd(HELPERS / "run.py").splitlines()[:160])
    mi = rd(HELPERS / "make_integrity.py")
    mt = rd(HELPERS / "make_template.py")
    ledger_labels = rd(ROOT / "assets" / "label_ledger.json")
    integrity = rd(ROOT / "assets" / "integrity.json")

    print("1: the qa-round CLI form the docs teach must actually parse")
    ck("qa-round --open" not in gates, "gates.md never says 'qa-round --open' (positional, not a flag)")
    ck("qa-round --open" not in visual, "visual-qa.md never says 'qa-round --open'")

    print("\n2: developer disagreement is a GREY pair, not a hard block (match.py:166-181)")
    stale = "developer disagreement / >15%"
    ck(stale not in run_head, "run.py docstring no longer calls dev-disagreement forbidden")
    ck(stale not in skill, "SKILL.md no longer calls dev-disagreement forbidden")
    ck(stale not in gates, "gates.md no longer calls dev-disagreement forbidden")

    print("\n3: no hardcoded EN chrome key count (the gate asserts set equality; counts rot)")
    ck("175" not in gates, "gates.md carries no stale key count")
    ck("175" not in loc, "localisation.md carries no stale key count")
    ck("(175" not in gr, "gate_runner.py comments carry no stale key count")

    print("\n4: the Stage-0 setup flow is ONE visualize widget, never AskUserQuestion")
    ck("AskUserQuestion" not in config, "config.md does not commission the forbidden setup flow")

    print("\n5: bundled language count")
    ck("bundled 12" not in skill, "SKILL.md says bundled 13, not 12")

    print("\n6: run.py's own exit-code table documents every agentic exit")
    ck(" 12 =" in run_head, "exit 12 (data translation) is in run.py's docstring table")
    ck(" 13 =" in run_head, "exit 13 (clarification) is in run.py's docstring table")

    print("\n7: pipeline.md describes the live routing (unconditional interpretation)")
    ck("interpret_prep" in pipeline, "pipeline.md names interpret_prep as the stage-1 router")

    print("\n8: data-engine.md describes the post-interpretation architecture")
    ck("the preferred FIELD source" not in dataeng,
       "data-engine.md no longer frames extract_pdf as the brochure record source")

    print("\n9: failure-modes.md rows match the code")
    ck("passes trivially" not in failmodes,
       "no-images row: G-images BLOCKS at >=50% placeholders, never 'passes trivially'")
    ck("unmatchedAssets" not in failmodes,
       "no code writes meta.unmatchedAssets (deliver.py prints 'Not checked')")
    ck("clarif" in failmodes.lower(), "the exit-13 clarify channel is in the degradation matrix")

    print("\n10: SKILL.md's pre-build gate list includes every gate the spine runs")
    ck("arithmetic" in skill, "SKILL.md names the arithmetic gate")

    print("\n11: template-contract.md matches the live template version")
    ck("The current template is v25" not in contract, "the contract no longer claims v25 is current")
    ck("v28" in contract, "the contract records v28")

    print("\n12: the ledger column spec lives in source-traceability.md, complete")
    ck(not (ROOT / "templates" / "ledger_columns.md").exists(),
       "templates/ledger_columns.md is folded away (was near-orphaned + incomplete)")
    ck("override" in trace, "source-traceability.md documents the override record_type")

    print("\n13: the eval-pinned SKILL.md anchors + the complete reference index")
    ck("The QA window" in skill and "qa-round" in skill,
       "SKILL.md keeps the bounded-window anchors (qa_round_test pins these too)")
    for doc in ("interpretation", "matching", "localisation", "setup-form"):
        ck("reference/" + doc + ".md" in skill, "SKILL.md indexes reference/" + doc + ".md")

    print("\n14: the dead files stay dead")
    ck(not (ROOT / "_poi2.txt").exists(), "_poi2.txt is gone (zero references)")
    ck(not (HELPERS / "_ph_const.txt").exists(),
       "helpers/_ph_const.txt is gone (byte-dupe of assets/placeholder.uri)")
    ck(not (ROOT / "examples").exists(), "examples/ is gone (orphaned, pre-interpretation era)")
    ck(not (REF / "memory.md").exists(), "reference/memory.md is archived out of the skill")
    ck(not (REF / "vision-fallback.md").exists(),
       "reference/vision-fallback.md is archived (interpretation.md is the one contract)")
    ck(not (ROOT / "assets" / "dashboard_template.v18.html").exists(),
       "the v18 template is archived (no loader exists; patch-only could only make v19)")

    print("\n15: the manifest no longer guards the archived v18 template")
    ck("dashboard_template.v18" not in integrity, "integrity.json has no v18 entry")
    ck("dashboard_template.v18" not in mi, "make_integrity.py TARGETS has no v18 entry")

    print("\n16: one interpretation contract - no live pointer to vision-fallback.md")
    hit = [str(p.name) for p in sorted(REF.glob("*.md")) if "vision-fallback" in rd(p)]
    hit += [str(p.name) for p in sorted(HELPERS.glob("*.py")) if "vision-fallback" in rd(p)]
    if "vision-fallback" in skill:
        hit.append("SKILL.md")
    ck(not hit, "no live doc/helper points at vision-fallback.md " + ascii(hit))

    print("\n17: no live pointer to the archived memory.md")
    ck("memory.md" not in skill, "SKILL.md does not point at reference/memory.md")
    ck("memory.md" not in ledger_labels, "label_ledger.json _comment does not point at memory.md")
    ck("memory.md" not in mt, "make_template.py comments do not point at memory.md")

    if fails:
        print("\nDOCTRUTH TEST: FAIL (" + str(len(fails)) + ")")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nDOCTRUTH TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
