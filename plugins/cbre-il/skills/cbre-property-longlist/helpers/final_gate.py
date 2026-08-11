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

# TIERS for the bounded QA window. CRITICAL gates protect the skill's actual promise - every
# field traces to a source, unknowns show as 'tbd', nothing is invented - and their remedies are
# DETERMINISTIC (strike the field to 'tbd', clear p.plan, surface the conflict), so they converge
# by construction and stay unbounded. ADVISORY gates are the ones whose findings are matters of
# degree on byte-frozen chrome (layout, spacing, crowding, a nicer photo); they get ONE review
# round and ONE improvement round, then anything still open is CARRIED to the Gaps Report.
# NOTE: the SEVERITY of an individual finding is still the REVIEWER'S call, never Python's -
# this is a per-GATE tier, not a content classifier.
# The verdict TIER sets are gone with the QA restructure: the reviewer's own `blocking:` /
# `advisory:` label on each FINDING decides now, not a per-gate verdict word, so no gate is
# inherently "critical" or "advisory". `parse_verdict` and the verdict word sets above are retained
# only because a reviewer MAY still end its file with a `VERDICT:` line - it is optional and ignored.


def parse_verdict(text: str) -> str | None:
    """The verdict word from the last line-initial 'VERDICT: …' in the file, or None."""
    hits = _VERDICT_LINE.findall(text)
    return hits[-1].lower() if hits else None


def qa_carry_consistency(deliverables, qa_state, canonical=None):
    """Does the DELIVERED Gaps Report's "Known limitations" describe the LATEST QA round?

    Returns (status, missing, stale, checked_file). status is:
      'skip'          - no QA round recorded (offline / eval run, or --qa-state omitted): INERT,
                        appends nothing to the gate's check list
      'skip-mismatch' - --qa-state is not the canonical's folder, so deliver.py read a DIFFERENT
                        qa_state.json than this check reads: WARN, never block. Blocking an
                        unsatisfiable comparison is a deadlock.
      'pass'          - the delivered list is the latest round's carried findings
      'fail'          - the report is STALE: written before the last `qa-round record`

    WHY. deliver.py writes that section during the spine from gate_runner.qa_carried(<work>);
    `qa-round record` is a SEPARATE command the orchestrator runs around it. Record a round AFTER
    deliver and the shipped report carries the PREVIOUS round's list. That shipped live: the report
    described the area basis with round-1 text the improvement round had already corrected,
    overstating the figures by 6-13% in the WRONG direction, and both blind reviewers flagged it,
    one as BLOCKING. A Known-limitations list that misdescribes the delivered data is a false
    statement in the one document whose job is honesty - the same reasoning that made qa_carried()
    latest-round-only. This closes the other half of it: the delivered FILE, not just the list.

    CONTAINMENT IN BOTH DIRECTIONS, NOT byte-exact set equality. Each carried finding must appear
    as a substring of some bullet (else MISSING); each bullet must contain some carried finding
    (else STALE). This tolerates a broker or a later pass CURATING the section - adding context
    around an entry, regrouping, adding a heading - which byte-exact equality would block. The live
    failure still blocks, because a superseded round's text contains none of the current entries.
    Blank entries are dropped first, so an empty string cannot match everything vacuously.

    KNOWN LIMIT (measured, and locked by qa_round_test section 7c): qa_carried() prefixes each
    entry with its gate name, so containment permits ADDING text around an entry but NOT rewording
    or TRANSLATING it. deliver.py has no i18n - the Gaps Report is English-only - so nothing is
    broken today. If that section is ever localised, this check must compare a stable finding ID
    instead of prose, or every localised run will block.
    """
    if not qa_state or not gate_runner.qa_round_number(qa_state):
        return "skip", [], [], None
    if canonical and Path(canonical).resolve().parent != Path(qa_state).resolve():
        return "skip-mismatch", [], [], None
    reports = [p for p in Path(deliverables).glob("*_Gaps_Report.md") if p.suffix != ".tmp"]
    if not reports:
        return "skip", [], [], None          # already FAILed above as a missing deliverable
    # Newest wins, so a lingering report from an earlier --client slug or a second-language
    # delivery is not read as 'stale'. mtime SELECTS which file to inspect; it never judges
    # freshness - the CONTENT does. (mtime as the freshness test was rejected: `qa-round record`
    # run twice rewrites qa_state.json with no content change, and any copy / sync / archive of
    # deliverables/ rewrites mtimes arbitrarily.)
    f = max(reports, key=lambda p: (p.stat().st_mtime, p.name))
    want = [w for w in (str(e).strip() for e in gate_runner.qa_carried(qa_state)) if w]
    got, inside = [], False
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("## "):
            inside = ln.startswith("## Known limitations")
            continue
        s = ln.strip()
        if inside and (s.startswith("- ") or s.startswith("* ")):
            got.append(s[2:].strip())
    missing = [w for w in want if not any(w in g for g in got)]
    stale = [g for g in got if not any(w in g for w in want)]
    return ("pass" if not missing and not stale else "fail"), missing, stale, f


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
    ap.add_argument("--qa-state", default="",
                    help="the work dir holding qa_state.json (gate_runner qa-round). With it, this "
                         "gate BLOCKS while any `blocking:` finding has no recorded repair, CARRIES "
                         "the advisory findings into the Gaps Report's 'Known limitations', and "
                         "checks the delivered report is the recorded pass's list. Omit it and only "
                         "the reviewer files themselves are checked.")
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

    # how many QA rounds have been OPENED (0 when the window was never used - then nothing is
    # carried and every reviewer blocks exactly as before, so an existing flow is unchanged)
    qa_round = gate_runner.qa_round_number(args.qa_state) if args.qa_state else 0
    _remediated = gate_runner.qa_resolved_count(args.qa_state) if args.qa_state else 0
    # The adjudication pass is gone with the QA restructure; the equivalent check - a BLOCKING
    # finding with no recorded repair - is `gate_runner.qa_blocking_open`, evaluated with the
    # reviewer findings below so its failures print alongside them.

    # P1-5: the DELIVERED "Known limitations" must be THIS round's carried list, not the previous
    # round's. Inert until a QA round has been recorded (see qa_carry_consistency).
    _cs, _missing, _stale, _gf = qa_carry_consistency(dpath, args.qa_state, args.canonical)
    if _cs == "skip-mismatch":
        print(f"  [WARN] Known-limitations consistency NOT checked: --qa-state "
              f"'{args.qa_state}' is not the canonical's folder "
              f"'{Path(args.canonical).resolve().parent}', so deliver.py read a different "
              f"qa_state.json - point both at the work dir")
    elif _cs != "skip":
        print(f"  [{'PASS' if _cs == 'pass' else 'FAIL'}] Known limitations in {_gf.name} match "
              f"qa_state.json (round {qa_round})")
        for m in _missing[:6]:
            print(f"      MISSING (recorded at QA, absent from the delivered report): {m}")
        for s in _stale[:6]:
            print(f"      STALE (in the delivered report, not in the latest round): {s}")
        if _cs != "pass":
            # The slug is DERIVED from the report actually inspected, and the dashboard filename
            # from the one actually present. Letting the orchestrator guess either writes a SECOND
            # report and leaves this stale one in the broker's folder - turning a block into the
            # silent honesty regression this check exists to close.
            _slug = _gf.name[: -len("_Gaps_Report.md")]
            _w = Path(args.qa_state)
            _dash = next((p.name for p in sorted(dpath.glob("*.html"))
                          if p.suffix != ".tmp" and p.stat().st_size >= 5000), "")
            print("      FIX: re-run deliver.py for THIS work dir - it re-reads qa_state.json and "
                  "rewrites the report. ONE command. Do NOT open another QA round, do NOT "
                  "re-dispatch a reviewer, do NOT edit the report by hand.")
            print(f'        python helpers/deliver.py --canonical "{_w / "canonical.json"}" '
                  f'--html "{_w / "built.html"}" --ledger "{_w / "source_ledger.csv"}" '
                  f'--out-dir "{dpath}" --slug "{_slug}"'
                  + (f' --filename "{_dash}"' if _dash else ""))
            print(f"      Use exactly that --slug ('{_slug}', derived from the report being "
                  f"inspected)" + (f" and --filename ('{_dash}')" if _dash else "")
                  + " - the SAME values the spine used. Do not invent new ones.")
        checks.append(_cs == "pass")

    # B60: an enrichment layer enabled AFTER a verdict was written leaves that verdict describing
    # an artefact that no longer exists - it happened live when regions and drive-times were
    # switched on after round 2 had closed. Say so LOUDLY rather than inheriting it in silence.
    # Deliberately NOT blocking: added layers introduce new fields, they do not falsify the ones
    # already reviewed, and G-enrich is a required reviewer whenever regions ran. Resetting the QA
    # window instead was rejected - it would wipe a recorded round and re-block a verified pack.
    stale_note = ""
    if args.qa_state:
        try:
            _st = json.loads((Path(args.qa_state) / "qa_state.json").read_text(encoding="utf-8"))
            _rec = [r.get("enrichment") for r in (_st.get("rounds") or []) if r.get("recorded")]
            _now = gate_runner.enrich_signature(args.qa_state)
            if _rec and _rec[-1] is not None and _rec[-1] != _now:
                stale_note = (f"enrichment changed since the last recorded round "
                              f"({_rec[-1] or '(none)'} -> {_now or '(none)'})")
        except Exception:
            stale_note = ""
    if stale_note:
        print(f"  [STALE] {stale_note} - the verdicts below predate it. Not blocking: added "
              f"layers do not falsify reviewed fields, and G-enrich covers the new data.")
    print("Reviewer findings (isolated, blind - one gate, one agent; they PROPOSE, the")
    print("orchestrator IMPLEMENTS, then we deliver):")
    rpath = Path(args.reviews) if args.reviews else None
    reviewers = ["G-honesty", "G-trace", "G-images", "G-visual"]
    if enr.get("regions"):
        reviewers.insert(2, "G-enrich")  # workforce figures verified vs cited source
    for g in reviewers:
        f = gate_runner.review_file(rpath, g) if rpath else None
        if f is None or not f.exists():
            if args.no_reviews:
                print(f"  [WARN] {g}.md absent (DEGRADED mode acknowledged via --no-reviews)")
                continue
            print(f"  [FAIL] {g}.md missing - dispatch the isolated reviewer "
                  f"(or pass --no-reviews to ship DEGRADED)")
            checks.append(False)
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        labelled = [ln for ln in txt.splitlines()
                    if re.match(r"\s*[-*]?\s*(blocking|advisory)\s*:", ln, re.I)]
        # A reviewer that found nothing must say so EXPLICITLY. Silence is indistinguishable from a
        # crashed, truncated or empty review, so it fails safe - the same reasoning the old
        # "no parseable VERDICT line" check used, applied to findings instead of verdict words.
        if not labelled and not re.search(r"^\s*FINDINGS:\s*none\s*$", txt, re.I | re.M):
            print(f"  [FAIL] {g}: no labelled findings and no explicit 'FINDINGS: none' - "
                  f"re-dispatch the reviewer")
            checks.append(False)
            continue
        print(f"  [PASS] {g}: {len(labelled)} finding(s) proposed")

    # The one safety property kept from verdict gating: a BLOCKING finding is a FALSE CLAIM by the
    # reviewer's own rubric, so it cannot ship until the orchestrator records what it changed.
    _open = gate_runner.qa_blocking_open(args.qa_state) if args.qa_state else []
    if _open:
        print()
        for o in _open:
            print(f"  [FAIL] BLOCKING finding not addressed: {str(o['finding'])[:130]}")
            print(f"      implement it, then record what you changed: gate_runner.py qa-round "
                  f"resolve --work <work> --id {o['id']} --because \"<what you changed>\"")
        checks.extend([False] * len(_open))

    ok = all(checks)
    # Only when there is actually something carried. An unconditional banner would be noise on a
    # run with no recorded QA pass, and it would assert a carry that did not happen.
    _carried = gate_runner.qa_carried(args.qa_state) if args.qa_state else []
    if _carried:
        print(f"\n[CARRIED] {len(_carried)} advisory finding(s) ship as 'Known limitations' in the "
              f"Gaps Report - the reviewers proposed them, they are not false claims, and they are "
              f"not re-reviewed.")
    if not ok:
        status = "BLOCKED - do not ship"
    elif args.no_reviews:
        # honesty: --no-reviews downgrades every judgement reviewer to [WARN], so this build was
        # never judged. It used to still print 'ALL-PASS - shippable', which reads as verified.
        status = ("DEGRADED - mechanical gates pass, judgement reviewers NOT run "
                  "(--no-reviews acknowledged)")
    elif _remediated:
        # PASS-WITH-REMEDIATION (B25). A pack whose findings were raised and FIXED inside
        # the window used to print the same plain ALL-PASS as one that was clean first
        # try, so the QA window left no trace of having done anything. The count comes
        # from qa_state.json's recorded `resolved` map - machine-checkable, and
        # unreachable by simply never recording a finding. Still exit 0: it ships.
        status = (f"ALL-PASS - shippable (PASS-WITH-REMEDIATION: {_remediated} "
                  f"finding(s) raised and fixed in-window)")
    else:
        status = "ALL-PASS - shippable"
    print(f"\nSTATUS: {status}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
