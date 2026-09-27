#!/usr/bin/env python3
"""reader_contract_render_test.py - the condensed per-mode reader contract (2026-09-26 test run,
fix 1.1) and the explicit record shape (fix 1.5c).

THE DEFECT. Every brochure reader was told to open the whole of reference/interpretation.md
(~60 KB, of which ~13 KB serves tracker / region-label / photo-match jobs and maintainer
history) plus templates/record_schema.json (whose only reader-relevant part is the `__meta` key
list) before reading one page: ~85 KB, ~21 k tokens per deck, one extra tool call, on every deck
of every run. And 3 of 22 readers on one run wrote `prov` beside the fields, because the prompt
listed it in prose as if it were a sibling of the fields and no shape was ever shown.

THE FIX. interpretation.md marks its reader rules with whole-line `reader-contract` blocks per
mode (history inside them in `maintainer-only` blocks); prompts_render renders one mode's blocks
plus the `__meta` key list into the reader's common file. Any render problem falls back to the
exact pointer text readers had before.

What this pins (synthetic data only):
  (a) the shipped markers parse, and both modes render;
  (b) NO RULE LOST: no maintainer-only block holds an imperative, and every section heading
      outside the reader blocks is on an explicit allow-list, so a new section forces a decision;
  (c) the right rules reach the right mode (shared, text-only, raster-only needles);
  (d) the saving is real: the text contract is < 60% of the full read, the common file < 80 KB;
  (e) no per-deck value, no em dash and no tracker section in either render;
  (f) fail safe: a broken marker or an oversized result -> the old pointer text + one note;
  (g) the split is still transport: every render() line is in the stub or the common file;
  (h) 1.5c: each common file shows the record shape as parseable JSON with prov under __meta;
  (i) the parser refuses nesting, a stray maintainer block, a marker in a fence, a misspelling.

Run: python evals/reader_contract_render_test.py"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import prompts_render as PR  # noqa: E402

IMPERATIVE = re.compile(r"\b(MUST|NEVER|REQUIRED|Do NOT|do not|never|always|only)\b")
OUTSIDE_ALLOWED = [
    "# Brochure interpretation - text-first, raster fallback",
    "## How the mode is decided",
    "## The interpretation sub-agent (orchestrator dispatches; isolated, fresh context)",
    '## Tracker mode (`kind:"tracker"` job - a MAP, never records)',
    '### Verification pass (`kind:"tracker_verify"` job - an INDEPENDENT second map)',
    "## Region label resolution (`region_labels[]` job - a CLOSED-SET code pick, never records)",
    "## Photo-match description (the exit-9 `photo_map.json` description fields)",
]
SHARED = ("Transcribe, never invent", "BTS", "not in text layer",
          "COORDINATES AND LOCATION HANDLES", "LEADS WITH THE FIGURE AND ITS UNIT",
          "statedTotalArea", "source_conflicts", "not_in_text_layer", "seen_as",
          "Required media keys", "copied VERBATIM from its")
TEXT_ONLY = ("Read `candidates_sheet`", "Mark decorative candidates for exclusion",
             "needs_raster", "LOOK at the `render_sheets`", "A **text** deck entry:")
RASTER_ONLY = ("`exclude_refs` is unavailable in raster", "A **raster** deck entry:")


def _jobs(kind: str, work: Path, n: int = 2) -> list:
    return [(kind, f"deck{i}_ab12cd{i}_vision", {
        "DECK_NAME": f"deck{i}.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": 4 + i,
        "COUNTRY": "XX", "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
        "OUTPUT_PATH": str(work / "extract" / f"deck{i}_ab12cd{i}_vision.json")})
        for i in range(n)]


def _fenced_json(text: str) -> list:
    out = []
    for m in re.finditer(r"```json\n(.*?)\n```", text, re.S):
        try:
            out.append(json.loads(m.group(1)))
        except Exception:
            pass
    return out


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    raw = PR.CONTRACT_FILE.read_text(encoding="utf-8")
    parsed = PR.parse_contract(raw)

    # (a) the shipped markers parse and both modes render
    check(parsed["error"] == "", f"the shipped markers parse ({parsed['error'] or 'ok'})")
    bodies = {}
    for mode in ("text", "raster"):
        body, why = PR.reader_contract(mode)
        bodies[mode] = body or ""
        check(body is not None and PR.CONTRACT_BODY_MARK in body,
              f"{mode}: the condensed contract renders ({why or 'ok'})")

    # (b) no rule lost
    bad = [b[:80] for b in parsed["maintainer"] if IMPERATIVE.search(b)]
    check(parsed["maintainer"] and not bad,
          f"{len(parsed['maintainer'])} maintainer-only block(s), none holds an imperative "
          f"({bad[:1]})")
    check(parsed["outside_headings"] == OUTSIDE_ALLOWED,
          f"the headings outside every reader block are exactly the allow-list "
          f"(got {parsed['outside_headings']})")
    for mode in ("text", "raster"):
        check("<!--" not in bodies[mode], f"{mode}: no marker line reaches the reader")
        leaked = [b[:60] for b in parsed["maintainer"] if b.strip() and b.strip() in bodies[mode]]
        check(not leaked, f"{mode}: no maintainer-only block reaches the reader ({leaked[:1]})")

    # (c) the right rules reach the right mode
    for mode in ("text", "raster"):
        for n in SHARED:
            check(n in bodies[mode], f"{mode}: carries the shared rule {n!r}")
    for n in TEXT_ONLY:
        check(n in bodies["text"] and n not in bodies["raster"], f"text only: {n!r}")
    for n in RASTER_ONLY:
        check(n in bodies["raster"] and n not in bodies["text"], f"raster only: {n!r}")
    check(PR.RASTER_CONTRACT_PREAMBLE in bodies["raster"]
          and PR.RASTER_CONTRACT_PREAMBLE not in bodies["text"],
          "raster: the render says the Raster mode section governs")
    schema = json.loads(PR.RECORD_SCHEMA_FILE.read_text(encoding="utf-8-sig"))
    meta_keys = list(schema["properties"]["__meta"]["properties"])
    mk = PR.meta_keys_block()
    check(all(f"- `{k}` (" in mk for k in meta_keys) and "Required in `__meta`" in mk,
          f"the __meta key block lists all {len(meta_keys)} record-schema keys + the required list")
    check(mk in bodies["text"] and mk in bodies["raster"],
          "both renders carry the __meta key block (no schema read needed)")

    # (d) the saving is real
    full = len(PR.CONTRACT_FILE.read_bytes()) + len(PR.RECORD_SCHEMA_FILE.read_bytes())
    tb = len(bodies["text"].encode("utf-8"))
    check(tb < 0.60 * full,
          f"text contract is {tb} B = {100.0 * tb / full:.1f}% of the full read ({full} B), < 60%")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "vision").mkdir()
        (work / "vision" / "manifest.json").write_text(
            json.dumps({"decks": [], "fields": [{"name": "park", "type": "string"}]}),
            encoding="utf-8")
        for kind in ("reader-text", "reader-raster"):
            jobs = _jobs(kind, work)
            files = PR.write_prompts(work, jobs)
            common_p = work / "prompts" / PR.COMMON_DIRNAME / f"{kind}.md"
            common = common_p.read_text(encoding="utf-8") if common_p.exists() else ""
            stub = files[0].read_text(encoding="utf-8") if files else ""
            cb = len(common.encode("utf-8"))
            check(PR.CONTRACT_BODY_MARK in common and cb < PR.READER_COMMON_MAX_BYTES,
                  f"{kind}: the common file carries the contract and stays under the cap ({cb} B)")
            check(PR.CONTRACT_POINTER in common
                  and "Print your deck's manifest entry in your FIRST tool call" in common,
                  f"{kind}: the pointer says the contract is below; manifest print first")
            check(PR.COMMON_HEADER_CONTRACT_NOTE.strip() in common,
                  f"{kind}: the common header says it carries the contract")
            check(PR.CONTRACT_BODY_MARK not in stub, f"{kind}: the contract is not in the stub")
            # (e)
            check("_vision.json" not in common and "deck0" not in common,
                  f"{kind}: no per-deck value in the common file")
            check("—" not in common, f"{kind}: no em dash in the common file")
            check("## Tracker mode" not in common and "Region label resolution" not in common,
                  f"{kind}: no tracker / region-label section reaches a reader")
            # (g) transport, not paraphrase
            full_r = PR.render(kind, jobs[0][2])
            have = {ln.rstrip() for ln in (stub + "\n" + common).splitlines()}
            missing = [ln for ln in full_r.splitlines()
                       if ln.rstrip() and ln.rstrip() not in have
                       and ln.rstrip() != PR.COMMON_POINTER_DEFAULT]
            check(not missing, f"{kind}: every render() line is in stub or common ({missing[:1]})")
            # (h) 1.5c: the record shape is shown, parseable, prov under __meta
            shapes = [j for j in _fenced_json(common)
                      if isinstance(j, list) and j and isinstance(j[0], dict)
                      and isinstance(j[0].get("__meta"), dict)]
            check(bool(shapes) and all(isinstance(s[0]["__meta"].get("prov"), dict)
                                       and "prov" not in s[0] for s in shapes),
                  f"{kind}: a fenced record-shape JSON parses, prov under __meta, none at top "
                  f"level ({len(shapes)} block(s))")
            check("prov is INSIDE __meta" in common, f"{kind}: says prov is INSIDE __meta")

        # (f) fail safe: a broken marker -> the old pointer, and ONE note
        broken = work / "interpretation_broken.md"
        broken.write_text(raw.replace("<!-- /reader-contract -->", "", 1), encoding="utf-8")
        saved = PR.CONTRACT_FILE
        try:
            PR.CONTRACT_FILE = broken
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                files = PR.write_prompts(work, _jobs("reader-text", work))
            common = (work / "prompts" / PR.COMMON_DIRNAME / "reader-text.md").read_text(
                encoding="utf-8")
            check(len(files) == 2 and "reference/interpretation.md" in common
                  and "SAME message as your manifest-entry print" in common
                  and PR.CONTRACT_BODY_MARK not in common,
                  "broken markers: the prompts still render, pointing at the full reference")
            check("not rendered this pass" in common,
                  "broken markers: the pointer says why the condensed contract is absent")
            check(PR.COMMON_HEADER_CONTRACT_NOTE.strip() not in common,
                  "broken markers: the header does not claim a contract it does not carry")
            notes = [ln for ln in buf.getvalue().splitlines() if "reader contract not condensed" in ln]
            check(len(notes) == 1, f"broken markers: exactly one note printed ({len(notes)})")
            PR.CONTRACT_FILE = work / "no_such_file.md"
            b2, why2 = PR.reader_contract("text")
            check(b2 is None and "unreadable" in why2, f"a missing contract file -> None ({why2})")
        finally:
            PR.CONTRACT_FILE = saved
        # an oversized result -> the same fallback, never an 80 KB+ common file
        saved_max = PR.READER_COMMON_MAX_BYTES
        try:
            PR.READER_COMMON_MAX_BYTES = 10_000
            with contextlib.redirect_stdout(io.StringIO()) as buf2:
                PR.write_prompts(work, _jobs("reader-raster", work, 1))
            common = (work / "prompts" / PR.COMMON_DIRNAME / "reader-raster.md").read_text(
                encoding="utf-8")
            check(PR.CONTRACT_BODY_MARK not in common and "over the" in common
                  and "reader contract not condensed" in buf2.getvalue(),
                  "oversized common half: falls back to the pointer, with the reason and a note")
        finally:
            PR.READER_COMMON_MAX_BYTES = saved_max
        with contextlib.redirect_stdout(io.StringIO()) as buf3:
            PR.write_prompts(work, _jobs("reader-text", work, 1))
        check("reader contract not condensed" not in buf3.getvalue(),
              "a healthy pass prints no fallback note")

    # (i) the parser refuses what it cannot parse safely
    base = "# T\n<!-- reader-contract: text -->\n## A\nrule\n<!-- /reader-contract -->\n"
    cases = {
        "nested block": base.replace("rule\n", "<!-- reader-contract: raster -->\nrule\n"),
        "maintainer-only outside a block": base + "<!-- maintainer-only -->\nx\n<!-- /maintainer-only -->\n",
        "marker inside a fence": base + "```\n<!-- reader-contract: text -->\n```\n",
        "misspelled marker": base + "<!-- reader-contracts: text -->\n",
        "unknown mode": base.replace("text -->", "txt -->"),
        "indented marker": base.replace("<!-- /reader-contract -->", "  <!-- /reader-contract -->"),
        "unclosed at end": base + "<!-- reader-contract: raster -->\nx\n",
    }
    for label, txt in cases.items():
        check(PR.parse_contract(txt)["error"] != "", f"parser refuses: {label}")
    ok = PR.parse_contract(base + "<!-- reader-contract: text raster -->\nshared\n"
                           "<!-- maintainer-only -->\nhistory\n<!-- /maintainer-only -->\n"
                           "<!-- /reader-contract -->\n")
    check(ok["error"] == "" and [sorted(m) for m, _ in ok["blocks"]] == [["text"], ["raster", "text"]]
          and ok["blocks"][1][1] == "shared" and ok["maintainer"] == ["history"],
          "parser: blocks in file order, maintainer text kept apart from the body")

    print(f"\n{'PASS' if not fails else 'FAIL'} reader_contract_render_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
