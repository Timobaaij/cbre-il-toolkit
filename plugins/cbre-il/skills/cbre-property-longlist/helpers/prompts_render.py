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

READER CONTRACT, RENDERED (2026-09-26 test run, fix 1.1). A reader used to be told to open the
whole of reference/interpretation.md (~60 KB, a fifth of it for tracker / region / photo-match
jobs and maintainer history) and templates/record_schema.json (whose only reader-relevant part is
the `__meta` key list) before reading a single page - ~21 k tokens per deck. That file now marks
its reader rules with whole-line `<!-- reader-contract: text raster -->` ... `<!-- /reader-contract
-->` blocks (optionally holding `<!-- maintainer-only -->` history), and reader_contract(mode)
renders the blocks of one mode plus meta_keys_block() into the reader template's
{{READER_CONTRACT_BODY}} slot, with {{READER_CONTRACT}} saying it is there. Any problem (an
unreadable file, unbalanced markers, an oversized result) falls back to today's pointer text
(CONTRACT_POINTER_FALLBACK) with the reason, and write_prompts prints one note: a reader is never
handed half a contract.

HOST TOOL-CALL CAP (2026-09-26 test run, fix 2.4). A host that denies a 4th parallel tool call
turned the reader's "every visual aid in ONE message" batch into 7-9 messages of denied turns,
and a reader had no way to learn the cap. When the caller passes no CONTEXT, the default Run
context gains one host fact read from CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE (the skill's own
override) or CLAUDE_MAX_PARALLEL_TOOLS (honoured when set); unset or not a positive integer ->
today's text exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
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
# where a wipe MOVES the previous pass's prompts (a subdirectory, so it is never "pending")
DONE_DIRNAME = "_done"

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
    "It IS your instruction: the ground rules, your contract, the field registry, every\n"
    "load-bearing rule and your final-message format. Every rule in it binds you exactly as if\n"
    "it were printed here; it is not background reading and it is not optional. It is shared\n"
    "by every deck of this kind in this pass only because those rules do not vary per deck;\n"
    "this stub carries the facts that do. If you cannot open it, STOP: write nothing to the\n"
    "output path and say so in your final message. Never work from this stub alone.")

COMMON_HEADER_TEMPLATE = (
    "<!-- {rel}: the invariant half of every '{kind}' dispatch in this pass. NOT a dispatch\n"
    "prompt on its own: each per-deck stub in the parent directory points here and the\n"
    "sub-agent reads this file itself.{extra} Regenerated on every render pass. -->\n"
    "# {kind}: shared instruction (read in full; it binds you exactly as if printed in your stub)\n\n")
# said in the header only when the condensed contract really is in the file (fix 1.1)
COMMON_HEADER_CONTRACT_NOTE = " It also carries this mode's contract."

# --- the rendered reader contract (2026-09-26 test run, fix 1.1) ------------------------------
# Module constants, not literals inside the functions, so an eval can point them at a temp copy.
CONTRACT_FILE = ROOT / "reference" / "interpretation.md"
RECORD_SCHEMA_FILE = ROOT / "templates" / "record_schema.json"
# the template kinds that carry {{READER_CONTRACT}} / {{READER_CONTRACT_BODY}}, and their mode
READER_CONTRACT_KINDS = {"reader-text": "text", "reader-raster": "raster"}
READER_MODES = ("text", "raster")
# the common half of a reader prompt stays one comfortable read; past these the condensed
# contract is withdrawn and the reader is pointed at the full file instead (fail safe)
READER_COMMON_MAX_BYTES = 80_000
READER_COMMON_MAX_LINES = 1_800
CONTRACT_BODY_MARK = "# CONTRACT (rendered for "

# what {{READER_CONTRACT}} says when the body IS appended to the common file
CONTRACT_POINTER = (
    "The contract is printed IN FULL at the end of this file (CONTRACT, rendered from\n"
    "reference/interpretation.md this pass). It binds you exactly like the rules above. Do not\n"
    "open reference/interpretation.md or templates/record_schema.json as well.\n"
    "Print your deck's manifest entry in your FIRST tool call.")
# ...and when it is NOT (today's pointer, verbatim, plus the reason): {mode}, {skill_dir}, {why}
CONTRACT_POINTER_FALLBACK = (
    "Follow it exactly ({mode} mode). Request it in the SAME message as your manifest-entry print\n"
    "(both paths are known now) and act on the entry only once you have read it:\n"
    "{skill_dir}/reference/interpretation.md\n"
    "(The condensed contract was not rendered this pass: {why}.)")
RASTER_CONTRACT_PREAMBLE = (
    "RASTER MODE: the 'Raster mode' section governs; the shared rules are written in text-mode "
    "terms and apply with the page image as the source and the prov tag (vision transcription).")
META_KEYS_UNAVAILABLE = (
    "## __meta keys\n(the key list could not be rendered from templates/record_schema.json this "
    "pass: read `properties.__meta` in that file)")

_RC_OPEN_RE = re.compile(r"^<!--\s*reader-contract:\s*([A-Za-z ]*?)\s*-->$")
_RC_CLOSE = "<!-- /reader-contract -->"
_MO_OPEN = "<!-- maintainer-only -->"
_MO_CLOSE = "<!-- /maintainer-only -->"
# anything that LOOKS like one of the markers; a near-miss spelling is an error, never ignored
_MARKER_HINT_RE = re.compile(r"^\s*<!--\s*/?\s*(reader-contract|maintainer-only)", re.I)

# --- host tool-call cap (2026-09-26 test run, fix 2.4) ----------------------------------------
HOST_CAP_ENV = ("CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE", "CLAUDE_MAX_PARALLEL_TOOLS")
HOST_FACT_TEMPLATE = (
    "\n- Host fact: at most {n} tool calls may run in one message on this host; send any batch "
    "as consecutive messages of {n}.")

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


def parse_contract(text: str) -> dict:
    """Parse reference/interpretation.md's reader-contract markers (fix 1.1). Pure, never raises.

    Returns {"blocks": [(frozenset(modes), body_text)], "maintainer": [text, ...],
    "outside_headings": [heading line, ...], "error": ""}. Marker lines are dropped and
    maintainer-only text is collected apart, never into a block's body. `error` is non-empty
    (and the other keys must not be trusted) on: a nested or unclosed reader block, a close
    without an open, a maintainer-only block outside a reader block or nested, a marker inside a
    fenced block, a marker that is not a whole unindented line, an unknown mode word, a
    misspelled marker, or an unbalanced ``` fence. Refusing is the point: a silently mis-parsed
    marker would drop rules from every reader's contract with nothing to show for it."""
    out = {"blocks": [], "maintainer": [], "outside_headings": [], "error": ""}

    def _fail(n, msg):
        out["error"] = f"line {n}: {msg}"
        return out

    try:
        modes = None            # frozenset while inside a reader block
        body: list[str] = []
        mo: list[str] | None = None
        fence = False
        lines = str(text).split("\n")
        for n, raw in enumerate(lines, 1):
            line = raw.rstrip("\r")
            s = line.strip()
            if s.startswith("```"):
                fence = not fence
            elif _MARKER_HINT_RE.match(line):
                if fence:
                    return _fail(n, "a contract marker inside a fenced block")
                if line != s:
                    return _fail(n, "a contract marker must be a whole, unindented line")
                m = _RC_OPEN_RE.match(s)
                if m:
                    if modes is not None:
                        return _fail(n, "a reader-contract block opened inside another")
                    words = m.group(1).split()
                    if (not words or len(set(words)) != len(words)
                            or any(w not in READER_MODES for w in words)):
                        return _fail(n, f"reader-contract modes must be text and/or raster, got "
                                        f"{m.group(1)!r}")
                    modes, body = frozenset(words), []
                    continue
                if s == _RC_CLOSE:
                    if modes is None:
                        return _fail(n, "a reader-contract block closed that was never opened")
                    if mo is not None:
                        return _fail(n, "a reader-contract block closed inside maintainer-only")
                    out["blocks"].append((modes, "\n".join(body).strip("\n")))
                    modes = None
                    continue
                if s == _MO_OPEN:
                    if modes is None:
                        return _fail(n, "a maintainer-only block outside every reader block")
                    if mo is not None:
                        return _fail(n, "a maintainer-only block opened inside another")
                    mo = []
                    continue
                if s == _MO_CLOSE:
                    if mo is None:
                        return _fail(n, "a maintainer-only block closed that was never opened")
                    out["maintainer"].append("\n".join(mo).strip("\n"))
                    mo = None
                    continue
                return _fail(n, f"unrecognised contract marker {s[:60]!r}")
            elif modes is None and not fence and s.startswith("#"):
                out["outside_headings"].append(s)
            if mo is not None:
                mo.append(line)
            elif modes is not None:
                body.append(line)
        if fence:
            return _fail(len(lines), "an unbalanced ``` fence")
        if mo is not None or modes is not None:
            return _fail(len(lines), "a block is still open at the end of the file")
    except Exception as e:  # pure text work; belt and braces all the same
        out["error"] = f"parse error ({e.__class__.__name__}: {e})"
    return out


def meta_keys_block() -> str:
    """The `__meta` key list of templates/record_schema.json as Markdown bullets (fix 1.1):
    `- `name` (type): description` verbatim, plus the required list. It is the only part of that
    file a reader needs (`not_in_text_layer`, for one, is documented nowhere else), so a reader
    handed this never opens the schema. Never raises: an unreadable schema yields a line telling
    the reader where to look."""
    try:
        schema = json.loads(Path(RECORD_SCHEMA_FILE).read_text(encoding="utf-8-sig"))
        meta = ((schema.get("properties") or {}).get("__meta") or {})
        props = meta.get("properties") or {}
        if not isinstance(props, dict) or not props:
            return META_KEYS_UNAVAILABLE
        lines = ["## __meta keys (from templates/record_schema.json; you need not open that file)"]
        for name, node in props.items():
            node = node if isinstance(node, dict) else {}
            tstr = _type_str(node.get("type")) or "any"
            if isinstance(node.get("enum"), list) and node["enum"]:
                tstr += "; one of " + ", ".join(repr(str(v)) for v in node["enum"])
            desc = str(node.get("description") or "")
            lines.append(f"- `{name}` ({tstr})" + (f": {desc}" if desc else ""))
        req = meta.get("required") or []
        if isinstance(req, list) and req:
            lines.append("Required in `__meta`: " + ", ".join(f"`{r}`" for r in req) + ".")
        return "\n".join(lines)
    except Exception:
        return META_KEYS_UNAVAILABLE


_CONTRACT_MEMO: dict = {}


def _file_sig(p) -> tuple:
    try:
        st = Path(p).stat()
        return (str(p), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(p), None, None)


def _build_reader_contract(mode: str) -> tuple:
    if mode not in READER_MODES:
        return None, f"unknown reader mode {mode!r}"
    try:
        raw = Path(CONTRACT_FILE).read_bytes()
    except OSError as e:
        return None, f"reference/interpretation.md unreadable ({e.__class__.__name__})"
    parsed = parse_contract(raw.decode("utf-8-sig", errors="replace"))
    if parsed["error"]:
        return None, f"reader-contract markers invalid ({parsed['error']})"
    chunks = [b for m, b in parsed["blocks"] if mode in m and b.strip()]
    if not chunks:
        return None, f"no reader-contract block for {mode} mode"
    sha8 = hashlib.sha256(raw).hexdigest()[:8]
    M = mode.upper()
    head = [f"# CONTRACT (rendered for {M} mode from reference/interpretation.md, sha {sha8}). "
            f"Every rule of that file that binds a {M}-mode reader is below; sections for other "
            f"jobs and maintainer history are left out."]
    if mode == "raster":
        head.append(RASTER_CONTRACT_PREAMBLE)
    return "\n\n".join(head + chunks + [meta_keys_block()]) + "\n", ""


def reader_contract(mode: str) -> tuple:
    """(body, why) - the condensed reader contract for `mode` ('text' / 'raster'), or
    (None, why) when it cannot be rendered. Memoised on the two source files' size + mtime, so a
    pass rendering many decks reads them once and an edited file is re-read. Never raises."""
    mode = str(mode or "").strip().lower()
    key = (mode, _file_sig(CONTRACT_FILE), _file_sig(RECORD_SCHEMA_FILE))
    hit = _CONTRACT_MEMO.get(key)
    if hit is not None:
        return hit
    try:
        res = _build_reader_contract(mode)
    except Exception as e:
        res = (None, f"render error ({e.__class__.__name__}: {e})")
    if len(_CONTRACT_MEMO) > 16:
        _CONTRACT_MEMO.clear()
    _CONTRACT_MEMO[key] = res
    return res


def _contract_fallback_slots(mode: str, why: str) -> dict:
    return {"READER_CONTRACT": CONTRACT_POINTER_FALLBACK.format(
                mode=str(mode).upper(), skill_dir=str(ROOT), why=why),
            "READER_CONTRACT_BODY": ""}


def _contract_slots(kind: str) -> dict:
    """{READER_CONTRACT, READER_CONTRACT_BODY} for a reader kind, {} for any other kind. On any
    render problem the pointer is today's text plus the reason and the body is empty."""
    mode = READER_CONTRACT_KINDS.get(kind)
    if not mode:
        return {}
    body, why = reader_contract(mode)
    if body is None:
        _note_fallback(why)
        return _contract_fallback_slots(mode, why)
    return {"READER_CONTRACT": CONTRACT_POINTER, "READER_CONTRACT_BODY": body}


# reasons the condensed contract fell back during the current write_prompts() call (bounded: a
# long-lived process calling render() over and over must not grow it without limit)
_CONTRACT_FALLBACKS: list = []


def _note_fallback(why: str) -> None:
    if len(_CONTRACT_FALLBACKS) < 64:
        _CONTRACT_FALLBACKS.append(why)


def host_tool_cap() -> int | None:
    """The host's per-message tool-call cap when the environment states one (fix 2.4): the
    skill's own CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE first, then CLAUDE_MAX_PARALLEL_TOOLS. A
    value that is not a positive integer is ignored, never guessed at."""
    for name in HOST_CAP_ENV:
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return None


def _context_default() -> str:
    try:
        n = host_tool_cap()
    except Exception:
        n = None
    return CONTEXT_DEFAULT + (HOST_FACT_TEMPLATE.format(n=n) if n else "")


def _merged_slots(slots: dict | None, kind: str | None = None, tpl: str | None = None) -> dict:
    merged = {"SKILL_DIR": str(ROOT), "CONTEXT": _context_default(),
              "COMMON_POINTER": COMMON_POINTER_DEFAULT}
    for k, v in (slots or {}).items():
        merged[str(k).upper()] = str(v)
    # F19: the registry is derived from the manifest the job names unless the caller rendered
    # it already (an eval, or a manifest-less kind that happens to use the slot).
    if "FIELD_REGISTRY" not in merged:
        merged["FIELD_REGISTRY"] = (field_registry_block(merged["MANIFEST_PATH"])
                                    if "MANIFEST_PATH" in merged else FIELD_REGISTRY_UNAVAILABLE)
    # fix 1.6 (2026-09-26 test run): the master-list prompt names the pre-extracted email bodies
    # file. A caller that does not pass the slot (an older spine, an eval) must still get a
    # prompt that RENDERS, pointing the agent at the source files the way it always did.
    if tpl is not None and "{{EMAIL_BODIES}}" in tpl and "EMAIL_BODIES" not in merged:
        merged["EMAIL_BODIES"] = ("not available this pass - read the .msg/.eml files named in the "
                                  "Emails list instead")
    # fix 1.1: the reader contract, when the template uses it and the caller did not fill it
    if (kind and tpl is not None and "{{READER_CONTRACT" in tpl
            and ("READER_CONTRACT" not in merged or "READER_CONTRACT_BODY" not in merged)):
        for k, v in _contract_slots(kind).items():
            merged.setdefault(k, v)
    return merged


def _substitute(kind: str, tpl: str, merged: dict) -> tuple[str, str | None]:
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


def _render_parts(kind: str, slots: dict | None = None) -> tuple[str, str | None]:
    """Render prompts/<kind>.md and split it at the COMMON_SPLIT marker line -> (head, tail).
    tail is None for a template without a marker. The marker line itself is dropped. Raises on
    a missing template or an unfilled slot.

    Fix 1.1: when the condensed contract was filled in automatically and the rendered common half
    comes out over READER_COMMON_MAX_BYTES / _LINES, it is re-rendered with the fallback pointer
    (the reader then opens the full reference, today's behaviour) rather than shipped oversized."""
    tpl_path = TEMPLATE_DIR / f"{kind}.md"
    tpl = tpl_path.read_text(encoding="utf-8")
    caller = {str(k).upper() for k in (slots or {})}
    merged = _merged_slots(slots, kind=kind, tpl=tpl)
    head, tail = _substitute(kind, tpl, merged)
    mode = READER_CONTRACT_KINDS.get(kind)
    if (mode and tail is not None and "READER_CONTRACT_BODY" not in caller
            and merged.get("READER_CONTRACT_BODY")):
        nbytes, nlines = len(tail.encode("utf-8")), tail.count("\n") + 1
        if nbytes > READER_COMMON_MAX_BYTES or nlines > READER_COMMON_MAX_LINES:
            why = (f"the common half would be {nbytes} bytes / {nlines} lines, over the "
                   f"{READER_COMMON_MAX_BYTES} / {READER_COMMON_MAX_LINES} cap")
            _note_fallback(why)
            merged.update(_contract_fallback_slots(mode, why))
            head, tail = _substitute(kind, tpl, merged)
    return head, tail


def render(kind: str, slots: dict | None = None) -> str:
    """Render prompts/<kind>.md with the given slots as ONE complete prompt (the marker line,
    if any, is dropped). Raises on a missing template or an unfilled slot - callers that must
    not crash go through write_prompts()."""
    head, tail = _render_parts(kind, slots)
    return head if tail is None else head + tail


def _safe_id(job_id) -> str:
    return re.sub(r"[^\w\-.]+", "_", str(job_id)).strip("_.") if job_id else ""


def _wipe_md(d: Path, done: Path, repoint: tuple[bytes, bytes] | None = None) -> None:
    """MOVE every *.md in `d` into `done` (same name, overwriting) rather than deleting it.

    Deleting them meant one deck could not be re-dispatched later without a whole new pass.
    They must still LEAVE `d`, because the handoff treats every top-level file there as a
    pending job. A stub's pointer is an ABSOLUTE path into prompts/common/, and that file is
    moved (or overwritten by the next pass) too, so `repoint` rewrites that one path in the
    moved copy to its `_done/common/` twin; every other byte is kept."""
    for old in d.glob("*.md"):
        try:
            done.mkdir(parents=True, exist_ok=True)
            data = old.read_bytes()
            if repoint and repoint[0] in data:
                (done / old.name).write_bytes(data.replace(*repoint))
                old.unlink()
            else:
                old.replace(done / old.name)
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
    common dir too, so a stale common half can never be pointed at by a fresh stub; the
    previous pass's files are MOVED to prompts/_done/ (common/ to _done/common/), not deleted,
    so an earlier deck's prompt can still be re-dispatched by hand."""
    out_dir = Path(work) / "prompts"
    common_dir = out_dir / COMMON_DIRNAME
    done_dir = out_dir / DONE_DIRNAME
    written: list = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        common_dir.mkdir(parents=True, exist_ok=True)
        if wipe:
            old_c = str(common_dir.resolve()) + os.sep
            new_c = str((done_dir / COMMON_DIRNAME).resolve()) + os.sep
            _wipe_md(out_dir, done_dir, (old_c.encode("utf-8"), new_c.encode("utf-8")))
            _wipe_md(common_dir, done_dir / COMMON_DIRNAME)
    except Exception as e:  # an unwritable work dir must never stop the spine
        print(f"  (prompt rendering skipped: {e})")
        return []
    del _CONTRACT_FALLBACKS[:]             # fix 1.1: this call's fallback reasons only
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
                    header = COMMON_HEADER_TEMPLATE.format(
                        rel=rel, kind=kind,
                        extra=COMMON_HEADER_CONTRACT_NOTE if CONTRACT_BODY_MARK in tail else "")
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
    # fix 1.1: ONE note per distinct reason, so a fallback is visible and never noisy
    for why in dict.fromkeys(_CONTRACT_FALLBACKS):
        try:
            print(f"  (reader contract not condensed: {why}; readers are pointed at the full "
                  f"reference)")
        except Exception:
            pass
    return written


def retire_kind(work, kind: str) -> int:
    """MOVE prompts/<kind>.md and prompts/<kind>--*.md into prompts/_done/ (2026-09-26 test run,
    fix 1.5b) and return how many moved. A per-deck repair stub describes ONE refused output; once
    that output validates, the stub must leave prompts/, where the handoff treats every top-level
    file as pending work - but only THAT kind's files may go, since a wave of reader prompts may
    still be pending beside it (so this is not a wipe). Same move semantics as a wipe: overwrite
    in _done/, never delete. Never raises; 0 on any problem."""
    moved = 0
    try:
        out_dir = Path(work) / "prompts"
        if not out_dir.is_dir() or not str(kind or "").strip():
            return 0
        done = out_dir / DONE_DIRNAME
        names = {f"{kind}.md"}
        prefix = f"{kind}--"
        for p in sorted(out_dir.iterdir()):
            try:
                if not p.is_file() or p.suffix != ".md":
                    continue
                if p.name not in names and not p.name.startswith(prefix):
                    continue
                done.mkdir(parents=True, exist_ok=True)
                p.replace(done / p.name)
                moved += 1
            except OSError:
                continue
    except Exception:
        return moved
    return moved


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
