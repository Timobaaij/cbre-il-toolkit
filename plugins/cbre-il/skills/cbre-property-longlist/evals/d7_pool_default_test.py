#!/usr/bin/env python3
"""d7_pool_default_test.py - the image pre-warm process POOL is the DEFAULT, not an opt-in. (D7)

THE GAP THIS CLOSES (not a defect fix - a pin over behaviour that is already correct and is
currently unguarded). A performance item was carried as an open optimisation claiming merge ran
17.3s SERIAL against 10.0s POOLED on a real 7-PDF corpus, about 40 per cent. Investigation showed
the claim was an artefact of how it was measured: the "serial" figure came from a profiling harness
that had forced `CBRE_IMAGE_WORKERS=1`. `merge.prewarm_images` already resolves
`min(os.cpu_count(), 8)` workers when the caller passes no `workers=` and the environment is unset,
and `helpers/run.py` (the ONLY production call site) passes no `workers=`. So every real run is
already pooled and there is nothing to optimise.

WHAT WAS ACTUALLY WRONG WAS THE BATTERY, AND THAT IS WHAT THIS FILE FIXES. Nothing in the suite
asserted the pool is the DEFAULT. `evals/prewarm_test.py` proves the multi-worker path RUNS, banks
its work and respects its budget, but it reaches that path by passing `workers=4` explicitly, and
every other call that REACHES the resolution passes an explicit `workers=` too. (Two calls pass
none - `prewarm_test.py:152` and `merge_truth_test.py:650` - but both pass `image_cache=None`,
which returns at merge.py:3319 before the resolution runs, so neither exercises the default
either.) A
change that flipped the default to serial - a "safer" `workers = 1`, a cap typo, an `or` that eats
a truthy value, a well-meant `workers=1` added at the run.py call site - would therefore pass all
185 evals while making EVERY real, media-heavy run take the 17.3s path instead of the 10.0s one.
That is a silent 40 per cent regression on the slowest stage of the pipeline, visible to nobody
until a Cowork run started missing its shell ceiling and resuming. This file is the tripwire.

HOW IT TESTS THAT WITHOUT SPAWNING WORKERS. Real worker processes are slow to start (spawn on
Windows re-imports the world) and are exactly what `prewarm_test.py` already covers, so this eval
must not repeat them: it would add seconds and a flake surface for no new coverage. Instead it
substitutes a recording stand-in for `concurrent.futures.ProcessPoolExecutor` and stubs the two
`images` entry points the units go through, then reads back WHICH BRANCH the real, unmodified
resolution code chose and WITH HOW MANY WORKERS. The stand-in's `submit` deliberately does NOT run
the unit, so the two branches leave unambiguous, non-overlapping fingerprints:
    pooled  -> a pool was constructed with max_workers=N, and `_prewarm_unit` was never called;
    serial  -> no pool was constructed, and `_prewarm_unit` was called once per unit in-process.
Every probe also asserts `total > 0`. Without that a probe whose units failed to enumerate would
warm nothing, construct no pool, and be scored as "serial" - a broken harness reading as a real
result is how a pinning eval rots into a rubber stamp.

The deck files on disk are deliberately NOT valid PDFs. Geometry enumeration wraps its page count
in `except Exception -> pages = 0`, so a garbage file yields zero geometry units while the
per-record hero units still enumerate: the eval needs no PDF engine, no Pillow, and no network, and
it stays well under a second.

WHAT IS PINNED:
  * `workers=None` is the parameter default - "decide from the environment", never a hardcoded 1.
  * env UNSET and no `workers=` -> more than one worker on any machine reporting more than one CPU,
    i.e. the pooled branch. On a genuinely single-CPU machine that assertion is SKIPPED with a
    printed note, because `min(1, 8) -> 1 -> serial` is correct there and failing on it would make
    the battery machine-dependent.
  * the auto-derived default is capped at 8 (a 64-core build agent must not fork 64 rasterisers)
    and 0 or a negative resolves to the serial branch rather than to a 0-worker pool. Note WHICH
    line does that work: it is the `workers <= 1` branch test, which routes 0, 1 and negatives to
    serial before any pool is constructed. `max(1, workers)` is defence in depth BEHIND that test,
    not a crash guard in front of it - deleting the floor alone changes no observable behaviour,
    and this file pins the composite outcome rather than the floor itself.
  * `CBRE_IMAGE_WORKERS=1` still selects the serial branch. This is the documented operator opt-out
    (reference/environment.md) and the path the profiling harness used; it must keep working, or
    the next person trying to reproduce the 17.3s figure cannot.
  * an explicit `workers=` argument still beats the environment in BOTH directions.
  * run.py's single call site passes no `workers=` and never sets `CBRE_IMAGE_WORKERS` itself, so
    the default is what production actually gets.

Offline; stdlib only. Run: python evals/d7_pool_default_test.py"""
from __future__ import annotations

import concurrent.futures as CF
import inspect
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import merge as MG  # noqa: E402

IMG = MG.IMG                 # the very `images` module object merge calls through
ENV = "CBRE_IMAGE_WORKERS"
UNSET = object()             # distinct from None, which is a meaningful value for cpu_count


class _RecordingPool:
    """Stands in for `ProcessPoolExecutor` so the resolved worker count can be read back.

    `prewarm_images` does its `from concurrent.futures import ProcessPoolExecutor` INSIDE the
    function body, so the name is looked up on the module at call time and patching
    `concurrent.futures.ProcessPoolExecutor` is enough - no edit to merge.py, and the resolution
    arithmetic under test runs completely unmodified.

    `submit` returns an already-resolved Future WITHOUT calling the unit. That is what makes the
    branch fingerprint unambiguous (see the module docstring): the serial branch is the only one
    that can call `_prewarm_unit` in-process. Returning a real, already-done Future keeps the
    genuine `as_completed(futs, timeout=...)` loop in merge.py on its normal path, so the pooled
    branch is exercised end to end rather than short-circuited."""

    made: list = []          # max_workers of every construction, newest last

    def __init__(self, max_workers=None, **kw):
        _RecordingPool.made.append(max_workers)

    def submit(self, fn, *a, **kw):
        f = CF.Future()
        f.set_result(None)
        return f

    def shutdown(self, wait=True, cancel_futures=False):
        pass                 # merge calls this in a `finally`; it must never raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _probe(src: Path, recs: list, *, env=UNSET, workers=UNSET, cpu=UNSET) -> dict:
    """Run the real `prewarm_images` under a controlled environment and report which branch it
    took. Returns {'pool': max_workers or None, 'pools': n, 'serial': n_units_run, 'total': n}.

    EVERYTHING PATCHED HERE IS RESTORED IN THE `finally`, including the caller's own
    CBRE_IMAGE_WORKERS (absent and empty are different states, hence the UNSET sentinel) and
    `os.cpu_count`. A probe that leaked either would silently rewrite the environment for every
    eval that runs after it in the same process, which is a far nastier failure than the one this
    file exists to catch."""
    calls: list = []
    old_env = os.environ.get(ENV, UNSET)
    old_cached, old_unit = IMG._unit_cached, IMG._prewarm_unit
    old_cpu, old_pool = os.cpu_count, CF.ProcessPoolExecutor
    _RecordingPool.made = []
    try:
        if env is UNSET:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = str(env)
        if cpu is not UNSET:
            os.cpu_count = lambda: cpu   # merge does `import os` inside the function -> same object
        # never cached, never actually warmed: the units exist only to make the branch fire
        IMG._unit_cached = lambda spec: False
        IMG._prewarm_unit = lambda spec: calls.append(spec)
        CF.ProcessPoolExecutor = _RecordingPool
        kw = {} if workers is UNSET else {"workers": workers}
        _done, total = MG.prewarm_images(recs, src, src / ".image_cache", 110, seconds=30.0, **kw)
    finally:
        CF.ProcessPoolExecutor = old_pool
        IMG._unit_cached, IMG._prewarm_unit, os.cpu_count = old_cached, old_unit, old_cpu
        if old_env is UNSET:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old_env
    made = list(_RecordingPool.made)
    return {"pool": made[0] if made else None, "pools": len(made),
            "serial": len(calls), "total": total}


def _shape(p: dict) -> str:
    """A one-line, human-readable branch verdict for the PASS/FAIL labels."""
    return (f"pool(max_workers={p['pool']})" if p["pool"] is not None
            else f"serial({p['serial']} unit(s) in-process)")


def _call_text(src: str, needle: str) -> str:
    """The full text of the first `needle(...)` call in `src`, by brace balance. The call sites
    this reads have no parentheses inside string literals, so a plain depth count is exact and
    does not need a real parser."""
    i = src.index(needle)
    j, depth = i + len(needle), 1
    while j < len(src) and depth:
        depth += (src[j] == "(") - (src[j] == ")")
        j += 1
    return src[i:j]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fails = []

    def ck(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            fails.append(label)

    # ---- 1. the signature itself: the default must mean "derive it", not "one" -----------------
    par = inspect.signature(MG.prewarm_images).parameters
    ck("workers" in par and par["workers"].default is None,
       "prewarm_images(workers=None) - the default defers to the environment, not a hardcoded 1")

    # ---- 2. production really does take the default -------------------------------------------
    # run.py is the only caller that ships. If it ever grew a `workers=` of its own, the whole of
    # the rest of this file would be pinning a default that production had stopped using.
    rsrc = (ROOT / "helpers" / "run.py").read_text(encoding="utf-8")
    n_calls = rsrc.count("merge.prewarm_images(")
    ck(n_calls == 1, f"run.py has exactly one merge.prewarm_images call site ({n_calls})")
    call = _call_text(rsrc, "merge.prewarm_images(") if n_calls else ""
    ck(bool(call) and "workers" not in call,
       "and it passes NO workers= argument, so the env default applies on every production run")
    ck(not re.search(r"""(environ\[\s*["']CBRE_IMAGE_WORKERS|setdefault\(\s*["']CBRE_IMAGE_WORKERS"""
                     r"""|putenv\(\s*["']CBRE_IMAGE_WORKERS)""", rsrc),
       "and run.py never SETS CBRE_IMAGE_WORKERS itself (that would be a workers= by the back door)")

    # NOT CHECKED HERE, deliberately: whether reference/environment.md still describes the
    # default in the same words. That was tried and removed. It is not behavioural, the operator
    # doc is edited far more often than this resolution, and a battery that fails because someone
    # rewrote a sentence teaches people to distrust it. What this file pins is the CODE.

    # ---- 3. the resolution itself, branch by branch --------------------------------------------
    # ignore_cleanup_errors mirrors prewarm_test.py: a teardown race on Windows must never be
    # reported as a failed assertion. Nothing here spawns a process, but the enumeration step does
    # try to open the deck files, and a held handle would exit non-zero with every check PASSing.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_s:
        src = Path(td_s)
        for d in range(2):
            # DELIBERATELY NOT A PDF. Geometry enumeration is wrapped in `except Exception ->
            # pages = 0`, so this yields zero geometry units and the eval needs no PDF engine; the
            # per-record hero units below are all that is required to make the branch fire.
            (src / f"Deck{d}.pdf").write_bytes(b"not a pdf, and never opened")
        recs = [{"__meta": {"source_file": f"Deck{d}.pdf", "source_type": "pdf", "page_no": p}}
                for d in range(2) for p in range(3)]

        probes = {}

        def probe(name, **kw):
            p = _probe(src, recs, **kw)
            probes[name] = p
            return p

        # 3a. THE HEADLINE: nothing set, nothing passed -> the pool.
        real_cpu = os.cpu_count() or 1
        p = probe("default", env=UNSET, workers=UNSET)
        if real_cpu > 1:
            ck(p["pool"] is not None and p["pool"] > 1 and p["serial"] == 0,
               f"env UNSET + no workers= -> POOLED on this {real_cpu}-CPU machine [{_shape(p)}]")
            ck(p["pool"] == min(real_cpu, 8),
               f"and the count is min(cpu_count, 8) = {min(real_cpu, 8)} [{p['pool']}]")
        else:
            # correct behaviour, not a failure: min(1, 8) is 1 and 1 means serial. Asserting the
            # pool here would make the battery pass or fail on the size of the build agent.
            print(f"  [SKIP] this machine reports {real_cpu} CPU, so serial IS the correct default "
                  f"here; the pooled assertion needs >1 CPU [{_shape(p)}]")

        # 3b. the cap: a 64-core agent must not fork 64 rasterisers, each of which opens its own
        # PDF handles and can shell out to soffice.
        p = probe("cap", env=UNSET, workers=UNSET, cpu=64)
        ck(p["pool"] == 8, f"the auto-derived default is CAPPED at 8 on a 64-CPU box [{_shape(p)}]")
        p = probe("cpu4", env=UNSET, workers=UNSET, cpu=4)
        ck(p["pool"] == 4, f"below the cap it tracks cpu_count exactly (4) [{_shape(p)}]")

        # 3c. the floor, on both routes into it. cpu_count() legitimately returns None on some
        # platforms, and `or 1` is what stops that becoming min(None, 8) -> TypeError.
        p = probe("cpu1", env=UNSET, workers=UNSET, cpu=1)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"a 1-CPU machine resolves to serial, no pool [{_shape(p)}]")
        p = probe("cpunone", env=UNSET, workers=UNSET, cpu=None)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"cpu_count() -> None is floored to 1, not a TypeError [{_shape(p)}]")

        # 3d. THE DOCUMENTED OPT-OUT MUST KEEP WORKING. This is the switch the 17.3s profiling run
        # used; if it stopped selecting serial, nobody could reproduce or re-measure the figure.
        p = probe("env1", env=1, workers=UNSET, cpu=8)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"CBRE_IMAGE_WORKERS=1 still selects the SERIAL branch on an 8-CPU box [{_shape(p)}]")

        # 3e. the environment beats the machine default, and is floored like everything else.
        p = probe("env4", env=4, workers=UNSET, cpu=2)
        ck(p["pool"] == 4, f"CBRE_IMAGE_WORKERS=4 overrides a 2-CPU default [{_shape(p)}]")
        p = probe("envneg", env=-4, workers=UNSET, cpu=8)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"a negative CBRE_IMAGE_WORKERS is floored to 1 -> serial, never a bad pool [{_shape(p)}]")
        # `env or min(...)` - 0 and unparseable both mean "no opinion", so the DEFAULT survives an
        # empty or fat-fingered variable rather than collapsing to serial.
        p = probe("env0", env=0, workers=UNSET, cpu=4)
        ck(p["pool"] == 4, f"CBRE_IMAGE_WORKERS=0 falls back to the pooled default [{_shape(p)}]")
        p = probe("envjunk", env="four", workers=UNSET, cpu=4)
        ck(p["pool"] == 4,
           f"an unparseable CBRE_IMAGE_WORKERS falls back to the pooled default [{_shape(p)}]")

        # 3f. an explicit argument still wins, in BOTH directions. prewarm_test.py and
        # merge_truth_test.py depend on this: they pin the pooled and serial paths by passing
        # workers= while the surrounding environment is whatever the operator happens to have.
        p = probe("arg_over_env", env=1, workers=3, cpu=8)
        ck(p["pool"] == 3, f"workers=3 overrides CBRE_IMAGE_WORKERS=1 [{_shape(p)}]")
        p = probe("arg_over_env2", env=8, workers=1, cpu=8)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"workers=1 overrides CBRE_IMAGE_WORKERS=8 [{_shape(p)}]")
        # 0 and negatives must reach the SERIAL branch, never a 0-worker pool. The line that
        # guarantees it is the `workers <= 1` branch test, not the `max(1, workers)` floor above
        # it: with the test in place the floor is unreachable, and deleting the floor on its own
        # leaves every check here passing. What these two cases pin is the composite outcome, and
        # that is the honest way to describe them.
        p = probe("arg0", env=UNSET, workers=0, cpu=8)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"workers=0 resolves to serial, never a 0-worker pool [{_shape(p)}]")
        p = probe("argneg", env=UNSET, workers=-2, cpu=8)
        ck(p["pool"] is None and p["serial"] == p["total"],
           f"workers=-2 resolves to serial, never a negative-worker pool [{_shape(p)}]")

        # 3g. HARNESS SELF-CHECK. Every verdict above reads "no pool was built" as "serial". If the
        # units had failed to enumerate, prewarm_images would return (0, 0) early, build no pool,
        # and every serial assertion would pass while testing nothing at all.
        empty = sorted(n for n, pr in probes.items() if pr["total"] <= 0)
        ck(not empty, f"every probe actually enumerated units to warm (total > 0) [{empty}]")
        n_units = probes["cap"]["total"]
        print(f"  [info] {n_units} hero unit(s) over 2 decks; {len(probes)} probe(s), "
              f"no worker process spawned")

    print(f"\n{'OK' if not fails else 'FAIL'} d7_pool_default_test: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
