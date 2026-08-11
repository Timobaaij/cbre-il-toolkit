#!/usr/bin/env python3
"""engine_resume_test.py - a changed PDF engine invalidates the resume. (B17)

Half A of B17 was ALREADY FIXED before this batch: images._engine_tag() exists and is
folded into both cache-key builders. But its own docstring names the hole that remained -
"run._is_current keys purely on input MTIMES, so the tier is not a resume input" - and that
hole makes half A INERT on the real path: on the native re-run merge resume-skips entirely,
the image cache is never consulted, and the poisoned negative is served anyway while the run
prints "native PyMuPDF".

Correct function, dead wiring - the third time in this project. So the assertion that
matters here is the WIRING one: merge must not resume-skip when the engine tag changes.

Also closed: the two fitz_shim tiers collapsed to one key, and the engine VERSION was absent
from the tag, so a PyMuPDF upgrade that changes what is extractable looked identical. Offline."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import images as IMG  # noqa: E402
import run as RUN  # noqa: E402

RUN_SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    # --- the tag itself --------------------------------------------------------
    tag = IMG._engine_tag()
    ck(isinstance(tag, str) and tag, f"_engine_tag returns a tag {ascii(tag)}")
    ck("|" in tag, "the tag is composite (engine | pillow | version)")
    ck(sum(c.isdigit() for c in tag) > 0,
       f"the tag carries a VERSION - an engine upgrade changes what is extractable {ascii(tag)}")

    # the two shim tiers must not collapse to one key
    ck(hasattr(IMG, "_engine_tag"), "images._engine_tag exists")
    _real_fitz = IMG.fitz
    seen = set()
    try:
        class _F1:
            __name__ = "fitz_shim"
            _BACKEND = "pdfplumber"
            __version__ = "0"

        class _F2:
            __name__ = "fitz_shim"
            _BACKEND = "pypdfium2"
            __version__ = "0"
        for f in (_F1, _F2):
            IMG.fitz = f
            seen.add(IMG._engine_tag())
    finally:
        IMG.fitz = _real_fitz
    ck(len(seen) == 2,
       f"the two fitz_shim BACKENDS produce DIFFERENT tags {ascii(sorted(seen))}")

    # --- the wiring: a changed tag must invalidate the resume ------------------
    ck(hasattr(RUN, "_engine_stamp"), "run._engine_stamp exists")
    if not hasattr(RUN, "_engine_stamp"):
        print(f"\nENGINE RESUME TEST: FAIL ({len(fails)})")
        return 1

    d = Path(tempfile.mkdtemp(prefix="cbre_eng_"))
    prev_resume = RUN.RESUME
    RUN.RESUME = True
    try:
        stamp = RUN._engine_stamp(d)
        ck(Path(stamp).exists(), "the engine stamp is written into the work dir")
        m1 = Path(stamp).stat().st_mtime_ns

        # an unchanged engine must NOT churn the stamp, or merge re-fires every run
        stamp2 = RUN._engine_stamp(d)
        ck(Path(stamp2).stat().st_mtime_ns == m1,
           "an UNCHANGED engine leaves the stamp byte-identical (no mtime churn)")

        # mtimes are set explicitly. _is_current compares FLOAT st_mtime with >=, so three
        # writes inside one filesystem tick all read as equal and the test would prove
        # nothing. A live run has seconds between the stamp and the canonical, and minutes
        # before the next run rewrites the stamp - the offsets below model exactly that.
        import os
        out = d / "canonical.json"
        out.write_text("{}", encoding="utf-8")
        base = Path(stamp).stat().st_mtime
        os.utime(out, (base + 2, base + 2))          # canonical written after the stamp
        ck(RUN._is_current(out, [stamp]), "with the same engine, the stage is current")

        # now the engine changes
        _t = IMG._engine_tag
        try:
            IMG._engine_tag = lambda: "totally-different-engine|pil|9.9.9"
            stamp3 = RUN._engine_stamp(d)
        finally:
            IMG._engine_tag = _t
        # assert the CONTENT, not a real-clock mtime bump: three writes can land inside one
        # filesystem tick, which made the mtime form flaky under the battery's subprocess
        # while passing standalone. The content proves _write_if_changed actually rewrote it.
        ck("totally-different-engine" in Path(stamp3).read_text(encoding="utf-8"),
           "a CHANGED engine rewrites the stamp")
        os.utime(stamp3, (base + 60, base + 60))     # the NEXT run, a minute later
        ck(not RUN._is_current(out, [stamp3]),
           "so the stage is NO LONGER current - merge cannot resume-skip past a poisoned "
           "cache entry (this is the assertion half A needed and did not have)")
    finally:
        RUN.RESUME = prev_resume

    # the stamp must actually be listed as a merge input, or the above proves nothing
    ck("_engine_stamp(work)" in RUN_SRC, "run.py computes the engine stamp")
    i_stamp = RUN_SRC.find("merge_inputs.append(_eng_stamp")
    i_merge = RUN_SRC.find("if _is_current(canonical, merge_inputs)")
    ck(-1 < i_stamp < i_merge,
       "the stamp is appended to merge_inputs BEFORE the merge resume check reads them")

    if fails:
        print(f"\nENGINE RESUME TEST: FAIL ({len(fails)})")
        return 1
    print("\nENGINE RESUME TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
