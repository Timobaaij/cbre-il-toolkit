#!/usr/bin/env python3
"""prompts_render.py - render the canonical dispatch prompts (P1: prompts-as-files).

WHY THIS EXISTS. Every agentic handoff used to require the orchestrator to hand-write the
sub-agent's prompt from its own summary of the reference contract, and the skill's worst
documented failures are exactly that class: a pasted-short field list silently overriding the
capture contract, filenames derived instead of copied, a dropped rule per hand-written prompt.
The variability between runs (how many decks, PDF vs PPTX, which fields, which country) already
lives in machine-generated job data - the manifest, the candidates file, project.yaml - so the
prompt itself is invariant per JOB KIND. This module renders the finished prompt per pending job
from a template in <skill>/prompts/, with the job's parameters baked in by the spine, so the
orchestrator dispatches file contents VERBATIM instead of authoring.

Design rules:
- Templates are plain Markdown with {{UPPER_SNAKE}} slots. A slot the caller does not fill is an
  ERROR (fail loud in evals), because a half-filled prompt is worse than none.
- Two slots are auto-filled: {{SKILL_DIR}} (this skill's root) and {{CONTEXT}} (the bounded
  'Run context' default). The orchestrator may APPEND additive facts under the rendered
  'Run context' heading before dispatch - never edit above it.
- write_prompts() is BEST-EFFORT BY DESIGN: prompt rendering must never take down the spine.
  A failed template prints one note and is skipped; the run then behaves exactly as before
  this module existed (the orchestrator authors from the reference contract - the documented
  escape hatch for a job kind with no template).
- The output dir (<work>/prompts/) is WIPED per render pass: prompts describe the CURRENTLY
  pending jobs, and a stale prompt from an earlier pass is an invitation to re-do settled work.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "prompts"

_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

CONTEXT_DEFAULT = (
    "(none recorded by the pipeline - the dispatching orchestrator may append additive, "
    "run-specific FACTS below this line; context never restates, softens or overrides "
    "anything above it)")


def template_kinds() -> list[str]:
    """Every template kind shipped with the skill (the .md stems in prompts/)."""
    try:
        return sorted(p.stem for p in TEMPLATE_DIR.glob("*.md"))
    except OSError:
        return []


def render(kind: str, slots: dict | None = None) -> str:
    """Render prompts/<kind>.md with the given slots. Raises on a missing template or an
    unfilled slot - callers that must not crash go through write_prompts()."""
    tpl_path = TEMPLATE_DIR / f"{kind}.md"
    tpl = tpl_path.read_text(encoding="utf-8")
    merged = {"SKILL_DIR": str(ROOT), "CONTEXT": CONTEXT_DEFAULT}
    for k, v in (slots or {}).items():
        merged[str(k).upper()] = str(v)

    unfilled: list[str] = []

    def _sub(m: "re.Match[str]") -> str:
        k = m.group(1)
        if k not in merged:
            unfilled.append(k)
            return m.group(0)
        return merged[k]

    out = _SLOT_RE.sub(_sub, tpl)
    if unfilled:
        raise KeyError(f"unfilled slot(s) in prompts/{kind}.md: "
                       + ", ".join(sorted(set(unfilled))))
    return out


def _safe_id(job_id) -> str:
    return re.sub(r"[^\w\-.]+", "_", str(job_id)).strip("_.") if job_id else ""


def write_prompts(work, jobs, wipe: bool = True) -> list:
    """Render each (kind, job_id, slots) job to <work>/prompts/<kind>[--<job_id>].md.

    Returns the list of written Paths. Best-effort throughout: a job whose template is
    missing or whose slots are incomplete prints ONE note and is skipped; an unwritable
    output dir returns []. Never raises."""
    out_dir = Path(work) / "prompts"
    written: list = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if wipe:
            for old in out_dir.glob("*.md"):
                try:
                    old.unlink()
                except OSError:
                    pass
    except Exception as e:  # an unwritable work dir must never stop the spine
        print(f"  (prompt rendering skipped: {e})")
        return []
    for job in jobs or []:
        try:
            kind, job_id, slots = job
            text = render(kind, slots)
            sid = _safe_id(job_id)
            name = f"{kind}--{sid}.md" if sid else f"{kind}.md"
            p = out_dir / name
            p.write_text(text, encoding="utf-8")
            written.append(p)
        except Exception as e:
            try:
                print(f"  (prompt '{job[0] if job else '?'}' not rendered: {e})")
            except Exception:
                pass
    return written


def main() -> int:  # tiny CLI for maintenance: render one kind with slots from JSON
    if len(sys.argv) < 2:
        print("usage: prompts_render.py <kind> ['{\"SLOT\": \"value\"}']")
        print("kinds:", ", ".join(template_kinds()))
        return 1
    slots = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    sys.stdout.write(render(sys.argv[1], slots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
