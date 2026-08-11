#!/usr/bin/env python3
"""Run the eval suite. (B57)

SKILL.md used to name FOUR evals. There are sixty. The gap is not theoretical: in a single
session `cowork_sim` caught a manifest-rename livelock (23 consecutive non-convergence rounds -
exactly what a real orchestrator would have hit) and a bug in the source-authority
single-source-family logic. BOTH would have shipped green under the four named evals.

Each eval runs in a SUBPROCESS on purpose: several mutate global state, chdir, or call sys.exit,
so importing them would let one eval corrupt the next.

  python evals/run_all.py               # everything - the documented default after a skill edit
  python evals/run_all.py --quick       # the four fast ones, for a mid-edit sanity check
  python evals/run_all.py -k translate  # filter by substring while iterating
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent
QUICK = ("extract_test", "fixture_test", "smoke_test", "translate_e2e_test")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the cbre-property-longlist eval suite.")
    ap.add_argument("--quick", action="store_true",
                    help="only the four fast evals (NOT sufficient before shipping)")
    ap.add_argument("-k", dest="filt", default="",
                    help="only evals whose name contains this substring")
    ap.add_argument("--timeout", type=int, default=900, help="per-eval seconds (default 900)")
    a = ap.parse_args()

    names = sorted({p.stem for p in EVALS.glob("*_test.py")}
                   | {p.stem for p in EVALS.glob("*_sim.py")})
    if a.quick:
        names = [n for n in names if n in QUICK]
    if a.filt:
        names = [n for n in names if a.filt.lower() in n.lower()]
    if not names:
        print("no evals matched")
        return 1

    width = max(len(n) for n in names)
    failed = []
    for n in names:
        r = None
        try:
            r = subprocess.run([sys.executable, str(EVALS / f"{n}.py")],
                               capture_output=True, text=True, timeout=a.timeout)
            ok, tail = r.returncode == 0, ""
        except subprocess.TimeoutExpired:
            ok, tail = False, f"  (timed out after {a.timeout}s)"
        print(f"{n:<{width}}  {'PASS' if ok else 'FAIL'}{tail}", flush=True)
        if not ok:
            failed.append((n, r))

    scope = "--quick" if a.quick else (f"-k {a.filt}" if a.filt else "full suite")
    print(f"\nPASS={len(names) - len(failed)} FAIL={len(failed)} ({scope})")
    for n, r in failed:
        print(f"\n--- {n} ---")
        out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines() if r else []
        print("\n".join(out[-15:]) if out else "(no output)")
    if a.quick and not failed:
        print("\nNOTE: --quick is a sanity check, not the bar. Run the full suite before "
              "shipping a skill edit.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
