#!/usr/bin/env python3
"""final_gate.py - Stage 7 binary shippability check.

Re-runs the deterministic mechanical gates against the delivered artefacts and
confirms the three deliverables exist. Judgement gates (G-honesty, G-trace,
G-images, G-visual, and G-enrich when regions ran) are verdict files written by
isolated reviewers; if a reviews/ dir is given, every verdict file must exist
and carry a parseable non-blocking verdict (green or amber; amber = ship with
notes, red = block, missing/garbled = block). Exits non-zero if any line is
red - do not declare done while it is.

The gates run IN-PROCESS (gate_runner is imported once, not spawned per check),
and the set is trimmed to what is non-redundant at the final stage:
  * validate-html  - the byte-identity proof that the delivered file equals
                     render(canonical) AND the chrome SHA matches VERSION (this
                     subsumes the old self-check's token/marker check).
  * reconcile      - every id and the hero KPI strip still match the data.
  * freeze --check - in the reviewed path, proves canonical is byte-identical to
                     the bytes pre-build validate-data already cleared, so a
                     second validate-data here would be redundant.
  * validate-data  - run ONLY in --no-reviews (DEGRADED) mode, where there is no
                     freeze proof, so the schema/consistency net is kept.

CLI:
  python final_gate.py --canonical canonical.json --html built.html \
                       --deliverables deliverables/ [--reviews reviews/]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_runner  # noqa: E402

# Verdict protocol (reference/gates.md "Verdict semantics"): the reviewer's verdict
# is the LAST line of the file matching 'VERDICT: <word>'. red = the gate's blocking
# criteria are met; amber = non-blocking observations only (ships, notes go to the
# Gaps Report); green = clean. Missing or unrecognised verdict = BLOCK (fail safe).
# Only a LINE-INITIAL 'VERDICT' counts, so prose like "the verdict would be red if…"
# in a reviewer's reasoning can never false-trigger a block.
_VERDICT_LINE = re.compile(r"^[\s>*_#`-]*verdict\b[\s:*_`—–-]*\**([a-z][a-z-]*)",
                           re.IGNORECASE | re.MULTILINE)
BLOCKING_VERDICTS = {"red", "blocked", "fail", "reject", "fix-required"}
PASSING_VERDICTS = {"green", "amber", "pass", "ok", "clear"}


def parse_verdict(text: str) -> str | None:
    """The verdict word from the last line-initial 'VERDICT: …' in the file, or None."""
    hits = _VERDICT_LINE.findall(text)
    return hits[-1].lower() if hits else None


class _Buf(io.StringIO):
    def reconfigure(self, *a, **k):
        return None


def gate(*cmd) -> bool:
    """Run a gate_runner subcommand in-process; return True on ALL-PASS (rc 0)."""
    buf = _Buf()
    saved = sys.argv
    sys.argv = ["gate_runner", *[str(c) for c in cmd]]
    rc = 1
    try:
        with redirect_stdout(buf):
            gate_runner.main()
        rc = 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:
        buf.write(f"{type(e).__name__}: {e}")
    finally:
        sys.argv = saved
    ok = rc == 0
    tail = (buf.getvalue().strip().splitlines() or [""])[-1]
    print(f"  [{'PASS' if ok else 'FAIL'}] gate_runner {cmd[0]} :: {tail}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", required=True)
    ap.add_argument("--html", required=True)
    ap.add_argument("--deliverables", required=True)
    ap.add_argument("--reviews")
    ap.add_argument("--requested",
                    help="comma-separated enrichment layers the broker requested "
                         "(geocode,pois,osrm,regions) - runs the enrichment gate even if the run "
                         "crashed before stamping meta.enrichment (the P2-9 ship backstop)")
    ap.add_argument("--no-reviews", action="store_true",
                    help="acknowledge DEGRADED mode: ship without the isolated judgement reviewers")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    enr = (json.loads(Path(args.canonical).read_text(encoding="utf-8")).get("meta", {}) or {}).get("enrichment", {}) or {}

    print("Mechanical gates:")
    checks = [
        gate("validate-html", args.html, "--canonical", args.canonical),
        gate("reconcile", args.html, "--canonical", args.canonical),
    ]
    requested = [s.strip() for s in (args.requested or "").split(",") if s.strip()]
    if requested or any(enr.get(k) for k in ("geocode", "pois", "osrm", "regions")):
        # run the enrichment gate when enrichment was REQUESTED (even if the run crashed
        # before stamping meta.enrichment) OR when it was stamped done (audit S7-18)
        checks.append(gate("enrichment", args.canonical,
                           *(["--requested", ",".join(requested)] if requested else [])))
    # The artefact the parallel reviewers judged must be byte-identical to its
    # freeze snapshot; in the reviewed path that also makes a second validate-data
    # redundant (it already passed pre-build on these exact bytes). In acknowledged
    # DEGRADED mode there is no freeze, so re-validate the schema here as the net.
    if args.no_reviews:
        checks.append(gate("validate-data", args.canonical))
    else:
        checks.append(gate("freeze", args.canonical, "--check"))

    print("Deliverables present:")
    dpath = Path(args.deliverables)

    def _present(pattern, min_bytes=1):
        # non-empty AND not a half-written .tmp - a truncated / stub file must not pass
        return any(p.suffix != ".tmp" and p.stat().st_size >= min_bytes
                   for p in dpath.glob(pattern))

    have_html = _present("*.html", 5000)      # a real dashboard is large; a stub is not
    have_ledger = _present("*_Source_Ledger.*")
    have_gaps = _present("*_Gaps_Report.md")
    have_longlist = _present("*_Longlist.*")   # the flat broker table was never checked
    for name, ok in [("dashboard .html", have_html), ("Source Ledger", have_ledger),
                     ("Gaps Report", have_gaps), ("Longlist", have_longlist)]:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    checks += [have_html, have_ledger, have_gaps, have_longlist]

    print("Judgement verdicts (isolated reviewers):")
    rpath = Path(args.reviews) if args.reviews else None
    reviewers = ["G-honesty", "G-trace", "G-images", "G-visual"]
    if enr.get("regions"):
        reviewers.insert(2, "G-enrich")  # workforce figures verified vs cited source
    for g in reviewers:
        f = rpath / f"{g}.md" if rpath else None
        if f is None or not f.exists():
            if args.no_reviews:
                print(f"  [WARN] {g}.md absent (DEGRADED mode acknowledged via --no-reviews)")
                continue
            print(f"  [FAIL] {g}.md missing - run the isolated reviewer (or pass --no-reviews to ship DEGRADED)")
            checks.append(False)
            continue
        word = parse_verdict(f.read_text(encoding="utf-8"))
        if word is None:  # a review with no parseable verdict is NOT a pass - fail safe
            print(f"  [FAIL] {g}: no parseable 'VERDICT: <green|amber|red>' line - re-run the reviewer")
            checks.append(False)
            continue
        blocked = word in BLOCKING_VERDICTS
        if word not in BLOCKING_VERDICTS and word not in PASSING_VERDICTS:
            blocked = True  # unknown verdict word -> fail safe, never silently ship
            print(f"  [FAIL] {g}: unrecognised verdict '{word}' - re-run the reviewer")
        else:
            note = " (amber: non-blocking notes -> Gaps Report)" if word == "amber" else ""
            print(f"  [{'FAIL' if blocked else 'PASS'}] {g} (verdict: {word}){note}")
        checks.append(not blocked)

    ok = all(checks)
    print(f"\nSTATUS: {'ALL-PASS - shippable' if ok else 'BLOCKED - do not ship'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
