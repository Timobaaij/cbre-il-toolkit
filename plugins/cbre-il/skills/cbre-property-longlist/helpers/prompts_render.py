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
- Auto-filled slots: {{SKILL_DIR}} (this skill's root), {{CONTEXT}} (the bounded 'Run context'
  default), {{FIELD_REGISTRY}} (rendered from the manifest named by the job's MANIFEST_PATH, see
  below) and {{COMMON_POINTER}} (the two-file pointer, see F1 below). The orchestrator may
  APPEND additive facts under the rendered 'Run context' heading before dispatch - never edit
  above it.
- write_prompts() is BEST-EFFORT BY DESIGN: prompt rendering must never take down the spine.
  A failed template prints one note and is skipped; the run then behaves exactly as before
  this module existed (the orchestrator authors from the reference contract - the documented
  escape hatch for a job kind with no template).
- The output dir (<work>/prompts/) is WIPED per render pass: prompts describe the CURRENTLY
  pending jobs, and a stale prompt from an earlier pass is an invitation to re-do settled work.

F1: ONE SHARED COMMON HALF PER READER KIND, A SMALL STUB PER DECK. Measured on a 7-deck run,
the six rendered text-mode reader prompts were 6.7-6.8 KB each and differed in EXACTLY four
lines (the H1 deck name, the `- Deck:` line, the output path, the `needs_raster` stub
filename): 47 KB rendered, all of it read into the orchestrator's context and re-emitted
VERBATIM into the agent prompts, on the most context-loaded turn of the run, scaling linearly
with deck count - and the re-emission is where a transcription slip was observed. So a
template may carry ONE marker line beginning with COMMON_SPLIT. Everything below the marker
is identical for every job of that kind in a pass; write_prompts() writes it ONCE to
<work>/prompts/common/<kind>.md and replaces it in each per-job stub with a pointer block that
makes the common file MANDATORY reading (it is the instruction, not background). render()
still returns the WHOLE prompt as one string (marker line dropped), so the single-file
rendering stays the canonical instruction and the split is purely a transport optimisation:
stub + common file == render(). The common dir is a SUBDIRECTORY so the top-level listing of
<work>/prompts/ stays "one file per pending job" for the orchestrator, and the common file's
own header says it is not a dispatch prompt on its own.

F19: the manifest's `fields` registry is rendered INTO the prompt as {{FIELD_REGISTRY}} - name,
type and format per entry (contract C1: entries are objects {name, type, fills, format?}; a
bare-string entry from an older manifest renders as a name with no type, and the block then
carries the four type facts the prompt prose used to spell out). A `fills: "orchestrator"`
entry is skipped here too, belt and braces on top of the producer's own exclusion.
"""
from __future__ import annotations

import hashlib
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

# F1: the marker LINE (prefix match) that splits a template into the per-job head and the
# shared tail. Only the reader templates carry one today; any template may.
COMMON_SPLIT = "<!-- COMMON-SPLIT"
COMMON_DIRNAME = "common"

# what the {{COMMON_POINTER}} slot reads in a single-file rendering (render() / the CLI): the
# prompt is complete as printed, so the pointer has nothing to point at.
COMMON_POINTER_DEFAULT = (
    "(single-file rendering: this prompt is complete as printed - the shared half follows the "
    "per-deck facts below)")

# F1: the pointer block a per-job STUB carries in place of the common half. It has one job: make
# it impossible to read the stub as the whole instruction. SKILL.md's reason for VERBATIM
# dispatch is that a hand-written PARAPHRASE is the top error surface; pointing the agent at
# an exact file is not a paraphrase, but only if the agent treats that file as binding text
# and refuses to proceed without it - hence the STOP clause.
COMMON_POINTER_TEMPLATE = (
    "## Your instruction is TWO files. This stub is the SHORT half.\n"
    "**READ THIS FILE IN FULL, FIRST, BEFORE ANY OTHER ACTION:**\n"
    "{common_path}\n"
    "It IS your instruction: the ground rules, the contract pointer, the field registry, every\n"
    "load-bearing rule and your final-message format. Every rule in it binds you exactly as if\n"
    "it were printed here; it is not background reading and it is not optional. It is shared\n"
    "by every deck of this kind in this pass only because those rules do not vary per deck;\n"
    "this stub carries the facts that do. If you cannot open it, STOP: write nothing to the\n"
    "output path and say so in your final message. Never work from this stub alone.")

COMMON_HEADER_TEMPLATE = (
    "<!-- {rel}: the invariant half of every '{kind}' dispatch in this pass. NOT a dispatch\n"
    "prompt on its own: each per-deck stub in the parent directory points here and the\n"
    "sub-agent reads this file itself. Regenerated on every render pass. -->\n"
    "# {kind}: shared instruction (read in full; it binds you exactly as if printed in your stub)\n\n")

# F19: what the registry block says when the manifest cannot be read at render time (an eval
# with a dummy path, a manifest still being written). The reader is told to read the registry
# itself rather than being handed silence, which would read as "no fields".
FIELD_REGISTRY_UNAVAILABLE = (
    "(the manifest could not be read at render time, so the registry is not printed here: read\n"
    "the `fields` array FROM THE MANIFEST yourself - each entry is either a bare field name or an\n"
    "object {name, type, format?} - and treat it as a FLOOR, not a ceiling)")

# F19: the type facts the reader prompts used to carry in prose. They are rendered ONLY when at
# least one registry entry has no type, so the prose is gone exactly as far as the types cover.
FIELD_REGISTRY_UNTYPED_NOTE = (
    "(no type recorded for {n} of these - this manifest predates the typed registry. Until it\n"
    "carries one: `lat`/`lng` are numbers, from a DECIMAL pair only; `warehouseRentVal` is a\n"
    "number, ANNUAL, per area, in the source's own currency and area convention, the same\n"
    "number `warehouseRent` shows; `warehouseArea`, `officeArea`, `plotArea` and `divisibleFrom`\n"
    "keep the printed unit inside the value; everything else is a string written the way the\n"
    "source prints it.)")

_POINTER_TOKEN = "\x00COMMON_POINTER\x00"   # never appears in a template; replaced post-split


def template_kinds() -> list[str]:
    """Every template kind shipped with the skill (the .md stems in prompts/)."""
    try:
        return sorted(p.stem for p in TEMPLATE_DIR.glob("*.md"))
    except OSError:
        return []


def _type_str(t) -> str:
    if isinstance(t, list):
        return " | ".join(str(x) for x in t if x is not None and str(x).strip())
    return str(t).strip() if t is not None else ""


def field_registry_block(manifest_path) -> str:
    """Render the manifest's `fields` registry as one Markdown bullet per reader-fillable
    field: `name: type. format`. Typed object entries (C1) render name, type and format; a
    bare-string entry renders the name alone and triggers the untyped note. `fills:
    "orchestrator"` entries are skipped. Never raises: an unreadable manifest yields the
    'read it yourself' block."""
    try:
        data = json.loads(Path(str(manifest_path)).read_text(encoding="utf-8-sig"))
        fields = data.get("fields") if isinstance(data, dict) else None
    except Exception:
        return FIELD_REGISTRY_UNAVAILABLE
    if not isinstance(fields, list) or not fields:
        return FIELD_REGISTRY_UNAVAILABLE
    lines: list[str] = []
    untyped = 0
    for f in fields:
        if isinstance(f, dict):
            name = str(f.get("name") or "").strip()
            if not name:
                continue
            if str(f.get("fills") or "reader").strip().lower() == "orchestrator":
                continue          # the pipeline assigns it; never ask a reader for it
            tstr = _type_str(f.get("type"))
            fmt = str(f.get("format") or "").strip()
            line = f"- `{name}`"
            if tstr:
                line += f": {tstr}"
            else:
                untyped += 1
            if fmt:
                line += f". {fmt}"
            lines.append(line)
        elif isinstance(f, str) and f.strip():
            lines.append(f"- `{f.strip()}`")
            untyped += 1
    if not lines:
        return FIELD_REGISTRY_UNAVAILABLE
    if untyped:
        lines.append(FIELD_REGISTRY_UNTYPED_NOTE.format(n=untyped))
    return "\n".join(lines)


def _merged_slots(slots: dict | None) -> dict:
    merged = {"SKILL_DIR": str(ROOT), "CONTEXT": CONTEXT_DEFAULT,
              "COMMON_POINTER": COMMON_POINTER_DEFAULT}
    for k, v in (slots or {}).items():
        merged[str(k).upper()] = str(v)
    # F19: the registry is derived from the manifest the job names unless the caller rendered
    # it already (an eval, or a manifest-less kind that happens to use the slot).
    if "FIELD_REGISTRY" not in merged:
        merged["FIELD_REGISTRY"] = (field_registry_block(merged["MANIFEST_PATH"])
                                    if "MANIFEST_PATH" in merged else FIELD_REGISTRY_UNAVAILABLE)
    return merged


def _render_parts(kind: str, slots: dict | None = None) -> tuple[str, str | None]:
    """Render prompts/<kind>.md and split it at the COMMON_SPLIT marker line -> (head, tail).
    tail is None for a template without a marker. The marker line itself is dropped. Raises on
    a missing template or an unfilled slot."""
    tpl_path = TEMPLATE_DIR / f"{kind}.md"
    tpl = tpl_path.read_text(encoding="utf-8")
    merged = _merged_slots(slots)

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
    # split on the marker LINE. read_text() has already normalised a CRLF template to "\n",
    # and write_text() re-applies the platform newline on output, exactly as before.
    lines = out.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(COMMON_SPLIT):
            head = "\n".join(lines[:i]).rstrip("\n") + "\n"
            tail = "\n".join(lines[i + 1:]).lstrip("\n")
            return head, tail
    return out, None


def render(kind: str, slots: dict | None = None) -> str:
    """Render prompts/<kind>.md with the given slots as ONE complete prompt (the marker line,
    if any, is dropped). Raises on a missing template or an unfilled slot - callers that must
    not crash go through write_prompts()."""
    head, tail = _render_parts(kind, slots)
    return head if tail is None else head + tail


def _safe_id(job_id) -> str:
    return re.sub(r"[^\w\-.]+", "_", str(job_id)).strip("_.") if job_id else ""


def _wipe_md(d: Path) -> None:
    for old in d.glob("*.md"):
        try:
            old.unlink()
        except OSError:
            pass


def write_prompts(work, jobs, wipe: bool = True) -> list:
    """Render each (kind, job_id, slots) job to <work>/prompts/<kind>[--<job_id>].md.

    Returns the list of written per-job Paths (the shared common files under
    <work>/prompts/common/ are written as a side effect and NOT returned - the caller's
    contract is "one file per pending job"). Best-effort throughout: a job whose template is
    missing or whose slots are incomplete prints ONE note and is skipped; an unwritable
    output dir returns []. Never raises.

    F1: a template carrying the COMMON_SPLIT marker is written as a small per-job STUB (the
    head plus the mandatory pointer block) and ONE common file per kind holding the tail.
    The common file is written BEFORE its first stub and is named common/<kind>.md; should two
    jobs of one kind ever render a different tail (a different manifest in one pass), the
    second gets common/<kind>--<sha8>.md rather than overwriting the first. Wiping clears the
    common dir too, so a stale common half can never be pointed at by a fresh stub."""
    out_dir = Path(work) / "prompts"
    common_dir = out_dir / COMMON_DIRNAME
    written: list = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        common_dir.mkdir(parents=True, exist_ok=True)
        if wipe:
            _wipe_md(out_dir)
            _wipe_md(common_dir)
    except Exception as e:  # an unwritable work dir must never stop the spine
        print(f"  (prompt rendering skipped: {e})")
        return []
    commons: dict[str, Path] = {}          # sha256(tail) -> the common file holding it
    for job in jobs or []:
        try:
            kind, job_id, slots = job
            slots = {str(k).upper(): v for k, v in (slots or {}).items()}
            # a caller that passes COMMON_POINTER itself (an eval's dummy) keeps it; otherwise
            # the slot is a token that becomes the pointer block once the common path is known
            if "COMMON_POINTER" not in slots:
                slots["COMMON_POINTER"] = _POINTER_TOKEN
            head, tail = _render_parts(kind, slots)
            if tail is not None:
                sha = hashlib.sha256(tail.encode("utf-8")).hexdigest()
                cpath = commons.get(sha)
                if cpath is None:
                    cpath = common_dir / f"{kind}.md"
                    if cpath.exists():           # same kind, different tail, this pass
                        cpath = common_dir / f"{kind}--{sha[:8]}.md"
                    rel = f"{out_dir.name}/{COMMON_DIRNAME}/{cpath.name}"
                    header = COMMON_HEADER_TEMPLATE.format(rel=rel, kind=kind)
                    cpath.write_text(header + tail, encoding="utf-8")
                    commons[sha] = cpath
                pointer = COMMON_POINTER_TEMPLATE.format(common_path=str(cpath.resolve()))
                text = head.replace(_POINTER_TOKEN, pointer)
            else:
                text = head.replace(_POINTER_TOKEN, COMMON_POINTER_DEFAULT)
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
    try:                     # D16: UTF-8 console. Guarded and locally imported so a
        import _common as _C  # bootstrap tool is never stopped by this call itself.
        _C.force_utf8_stdout()
    except Exception:
        pass
    sys.exit(main())
