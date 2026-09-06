#!/usr/bin/env python3
"""f01_reader_common_split_test.py - F1 (shared reader COMMON + per-deck stub) and the F19
prompt half (the manifest's typed field registry rendered into the prompt).

THE DEFECT. On a 7-deck run the six rendered text-mode reader prompts were 6.7-6.8 KB each and
differed in EXACTLY four lines (H1 deck name, the `- Deck:` line, the output path, the
`needs_raster` stub filename). SKILL.md requires the orchestrator to dispatch each file
VERBATIM, so it read all ~47 KB into its context and re-emitted all ~47 KB into the agent
prompts, on the most context-loaded turn of the run, scaling linearly with deck count - and
a transcription slip was observed in that re-emission. The renderer now writes the invariant
half ONCE per kind to <work>/prompts/common/<kind>.md and a small per-deck stub that makes the
common file mandatory reading.

What this pins:
(1) write_prompts() returns ONE path per job (the common files are a side effect, not jobs),
    and writes exactly one common file per reader kind, in a SUBDIRECTORY so the top-level
    listing stays "one file per pending job" for the orchestrator;
(2) the per-deck stub carries the four variable facts and NOTHING of the common half, and is
    small (the whole point) - measured against the single-file rendering;
(3) the stub makes the common file MANDATORY: absolute path, read-first, binds-as-if-printed,
    a STOP clause if it cannot be opened, never-work-from-the-stub-alone;
(4) the common half carries every load-bearing clause prompt_render_test pins on the reader,
    and NO per-deck value (a deck name or output path leaking into the shared file would make
    it wrong for six of seven decks);
(5) the verbatim guarantee is preserved as an equation: every line of render() (the canonical
    single-file instruction) appears in the stub or the common file - the split is transport,
    not a paraphrase;
(6) F19: typed registry entries render as `name: type. format`, an orchestrator-filled entry
    is dropped, and a bare-string (older) manifest renders names plus the four type facts the
    prose used to carry - so the prose is gone exactly as far as the types cover it;
(7) wiping clears stale common files too, a different tail for one kind in one pass gets its
    own file, an unreadable manifest degrades to "read the registry yourself";
(8) no em dash is authored into any rendered output.

Run: python evals/f01_reader_common_split_test.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

import prompts_render as PR  # noqa: E402

# the same needles prompt_render_test.py pins on render(); they must now live in the COMMON half
READER_NEEDLES = ("FLOOR, not a ceiling", "copied VERBATIM", "cluster_label", "NEVER convert",
                  "Transcribe, never invent", "map_candidates")
MANDATORY_NEEDLES = ("READ THIS FILE IN FULL, FIRST", "binds you exactly as if",
                     "not background reading", "STOP", "Never work from this stub alone")

TYPED_FIELDS = [
    {"name": "areaUnit", "type": "string", "fills": "reader"},
    {"name": "lat", "type": "number", "fills": "reader"},
    {"name": "lng", "type": "number", "fills": "reader"},
    {"name": "officeAreaVal", "type": ["number", "null"], "fills": "orchestrator"},
    {"name": "park", "type": "string", "fills": "reader"},
    {"name": "warehouseAreaSqm", "type": ["string", "null"], "fills": "reader",
     "format": "the square-metre figure as a display string, e.g. '21,891 sq m'"},
    {"name": "warehouseRentVal", "type": ["number", "null"], "fills": "reader",
     "format": "ANNUAL per-area rate in the source's own convention; x12 a monthly quote"},
]


def _jobs(kind: str, n: int, work: Path, stem: str = "deck") -> list:
    return [(kind, f"{stem}{i}_ab12cd{i}_vision", {
        "DECK_NAME": f"{stem}{i}.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": 3 + i,
        "COUNTRY": "XX", "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
        "OUTPUT_PATH": str(work / "extract" / f"{stem}{i}_ab12cd{i}_vision.json")})
        for i in range(n)]


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "vision").mkdir()
        (work / "vision" / "manifest.json").write_text(
            json.dumps({"decks": [], "fields": TYPED_FIELDS}), encoding="utf-8")

        for kind in ("reader-text", "reader-raster"):
            jobs = _jobs(kind, 7, work)
            files = PR.write_prompts(work, jobs)
            common_dir = work / "prompts" / PR.COMMON_DIRNAME
            commons = sorted(common_dir.glob("*.md"))

            # (1) one returned path per job; exactly one common file, in the subdirectory
            check(len(files) == 7 and all(p.parent == work / "prompts" for p in files),
                  f"{kind}: write_prompts returns one top-level file per job")
            check([c.name for c in commons] == [f"{kind}.md"],
                  f"{kind}: exactly one common file, prompts/common/{kind}.md")
            check(sorted(p.name for p in (work / "prompts").glob("*.md")) ==
                  sorted(p.name for p in files),
                  f"{kind}: the top-level prompts/ listing is only the per-job stubs")
            if len(files) != 7 or not commons:
                continue
            common = commons[0].read_text(encoding="utf-8")
            stub = files[0].read_text(encoding="utf-8")
            full = PR.render(kind, jobs[0][2])

            # (2) the stub is small and carries the four variable facts only
            stub_bytes = len(stub.encode("utf-8"))
            full_bytes = len(full.encode("utf-8"))
            total_after = sum(len(p.read_bytes()) for p in files) + len(commons[0].read_bytes())
            check(stub_bytes < 2200, f"{kind}: stub is small ({stub_bytes} B; was ~{full_bytes} B)")
            check(total_after < 0.45 * 7 * full_bytes,
                  f"{kind}: 7 decks render to {total_after} B all-in vs "
                  f"{7 * full_bytes} B single-file (< 45%)")
            for fact in ('"deck0.pdf"', "3 page(s)", str(work / "vision" / "manifest.json"),
                         str(work / "extract" / "deck0_ab12cd0_vision.json")):
                check(fact in stub, f"{kind}: stub carries the per-deck fact {fact[:40]!r}")
            if kind == "reader-text":
                check('"source_file": "deck0.pdf", "needs_raster": true' in stub,
                      "reader-text: the needs_raster stub line (deck-specific) stays in the stub")
            for heading in ("## Ground rules", "## Load-bearing reminders", "## Final message",
                            "## The field registry"):
                check(heading not in stub, f"{kind}: stub does not carry {heading!r}")
            check("## Run context" in stub,
                  f"{kind}: the Run context slot (orchestrator-appended facts) is in the stub")

            # (3) the stub makes the common file mandatory reading
            check(str(commons[0].resolve()) in stub,
                  f"{kind}: stub names the common file by ABSOLUTE path")
            for needle in MANDATORY_NEEDLES:
                check(needle in stub, f"{kind}: stub says {needle!r}")
            check(PR.COMMON_POINTER_DEFAULT not in stub,
                  f"{kind}: stub does not carry the single-file placeholder text")

            # (4) the common half carries the load-bearing clauses and no per-deck value
            for needle in READER_NEEDLES:
                check(needle in common, f"{kind}: common carries {needle!r}")
            for leak in ("deck0", "deck6", "_vision.json", "3 page(s)", "9 page(s)"):
                check(leak not in common, f"{kind}: common carries no per-deck value {leak!r}")
            check("NOT a dispatch" in common and "prompt on its own" in common,
                  f"{kind}: common says it is not a dispatch prompt on its own")

            # (5) verbatim as an equation: every render() line is in stub or common
            body = {ln.rstrip() for ln in (stub + "\n" + common).splitlines()}
            missing = [ln for ln in full.splitlines()
                       if ln.rstrip() and ln.rstrip() not in body
                       and ln.rstrip() != PR.COMMON_POINTER_DEFAULT]
            check(not missing,
                  f"{kind}: every line of the single-file render() is in stub or common "
                  f"(missing: {missing[:2]})")
            check(PR.COMMON_SPLIT not in full and PR.COMMON_SPLIT not in stub
                  and PR.COMMON_SPLIT not in common,
                  f"{kind}: the split marker line is dropped from every output")

            # (6) F19: typed entries render name, type and format; orchestrator entries drop
            check("- `lat`: number" in common and "- `lng`: number" in common,
                  f"{kind}: registry renders lat/lng as numbers")
            check("- `warehouseRentVal`: number | null. ANNUAL per-area rate" in common,
                  f"{kind}: registry renders a union type and the format")
            check("- `warehouseAreaSqm`: string | null. the square-metre figure" in common,
                  f"{kind}: registry renders the C1 example entry")
            check("officeAreaVal" not in common,
                  f"{kind}: an orchestrator-filled entry is not offered to the reader")
            check("predates the typed registry" not in common,
                  f"{kind}: a fully typed registry carries no untyped fallback note")
            check("numeric EUR/m2/year" not in common,
                  f"{kind}: the prose no longer spells out warehouseRentVal's type")

            # (8) no em dash authored (the code point is spelled as an escape on purpose: the
            # house rule forbids authoring the character itself, in evals included)
            check("\u2014" not in stub and "\u2014" not in common,
                  f"{kind}: no em dash in the rendered stub or common file")

        # (6b) an older bare-string manifest: names + the four type facts
        (work / "vision" / "manifest.json").write_text(
            json.dumps({"decks": [], "fields": ["areaUnit", "lat", "park", "warehouseArea"]}),
            encoding="utf-8")
        PR.write_prompts(work, _jobs("reader-text", 1, work))
        common = (work / "prompts" / PR.COMMON_DIRNAME / "reader-text.md").read_text(encoding="utf-8")
        check("- `warehouseArea`\n" in common and "- `lat`\n" in common,
              "bare-string registry renders the names")
        check("no type recorded for 4 of these" in common,
              "bare-string registry counts the untyped entries")
        for fact in ("`lat`/`lng` are numbers", "`warehouseRentVal` is a", "ANNUAL",
                     "keep the printed unit inside the value"):
            check(fact in common, f"untyped fallback carries the type fact {fact!r}")

        # (7) wipe clears stale commons; a different tail per kind gets its own file
        PR.write_prompts(work, [("g-images", None, {"WORK": "w", "REVIEWS_ROUND_DIR": "r"})])
        check(not list((work / "prompts" / PR.COMMON_DIRNAME).glob("*.md")),
              "a render pass with no reader jobs wipes the stale common files")
        check(not (work / "prompts" / "reader-text--deck0_ab12cd0_vision.md").exists(),
              "and the stale stubs")
        # two manifests in one pass (never happens today; the name must not collide)
        (work / "vision2").mkdir()
        (work / "vision2" / "manifest.json").write_text(
            json.dumps({"decks": [], "fields": ["park"]}), encoding="utf-8")
        j = _jobs("reader-text", 2, work)
        j[1][2]["MANIFEST_PATH"] = str(work / "vision2" / "manifest.json")
        files = PR.write_prompts(work, j)
        names = sorted(p.name for p in (work / "prompts" / PR.COMMON_DIRNAME).glob("*.md"))
        check(len(names) == 2 and "reader-text.md" in names
              and any(n.startswith("reader-text--") for n in names),
              f"a second, different common half gets its own file ({names})")
        for p in files:
            s = p.read_text(encoding="utf-8")
            pointed = [n for n in names if n in s]
            check(len(pointed) == 1, f"{p.name} points at exactly one common file ({pointed})")
        # unreadable manifest -> the reader is told to read the registry itself
        j = _jobs("reader-text", 1, work)
        j[0][2]["MANIFEST_PATH"] = str(work / "nowhere.json")
        files = PR.write_prompts(work, j)
        common = (work / "prompts" / PR.COMMON_DIRNAME / "reader-text.md").read_text(encoding="utf-8")
        check(len(files) == 1 and "could not be read at render time" in common,
              "an unreadable manifest still renders, with the read-it-yourself registry block")
        # a manifest-less template is untouched by the split machinery
        out = PR.write_prompts(work, [("g-images", None, {"WORK": "w", "REVIEWS_ROUND_DIR": "r"})])
        check(len(out) == 1 and PR.COMMON_POINTER_DEFAULT not in out[0].read_text(encoding="utf-8"),
              "a template without the marker renders exactly as before")

    print(f"\n{'PASS' if not fails else 'FAIL'} f01_reader_common_split_test "
          f"({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
