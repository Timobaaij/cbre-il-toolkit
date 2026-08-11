#!/usr/bin/env python3
"""code_stamp_test.py - a code change invalidates the CHEAP stages, and only warns for merge. (B42)

No resume predicate carried any code identity, so editing a helper left every work dir resuming
past the stage that helper feeds. Both obvious stamps are wrong: assets/VERSION is the TEMPLATE
version and does not move for a merge.py edit; sha256(integrity.json) only moves when a human
remembers to run make_integrity.py, and preflight merely notes a stale manifest to stderr, which
mcp__shell does not surface. So the stamp is over LIVE BYTES.

The split is by MEASURED cost, and the merge half is the load-bearing assertion:
  build   ~0.07-0.3 s -> auto-invalidate. A spurious rebuild is free; a missed one was an
                         exit-7 'chrome drift' dead end no re-run could clear.
  deliver  seconds     -> auto-invalidate.
  merge    40-90 s cold-cache photo harvest inside a ~45 s window -> WARN ONLY. Adding it to
                         merge_inputs would manufacture the kill/resume spiral that cost 2.5 h,
                         and buy almost nothing: images.py's cache key has no code component, so
                         merge would re-derive byte-identical images.
So `assert the merge stamp is ABSENT from merge_inputs` is a real assertion, not a formality."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import run as RUN  # noqa: E402

SRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    ck(hasattr(RUN, "_code_stamp"), "run._code_stamp exists")
    if not hasattr(RUN, "_code_stamp"):
        print(f"\nCODE STAMP TEST: FAIL ({len(fails)})")
        return 1

    d = Path(tempfile.mkdtemp(prefix="cbre_cs_"))
    a, b = d / "a.py", d / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("y = 2\n", encoding="utf-8")

    s1 = RUN._code_stamp(d, "t", [a, b])
    ck(Path(s1).exists(), "the stamp file is written")
    v1 = Path(s1).read_text(encoding="utf-8")

    # UNCHANGED bytes must not churn, or the stage re-fires on every single run
    RUN._code_stamp(d, "t", [a, b])
    ck(Path(s1).read_text(encoding="utf-8") == v1,
       "an UNCHANGED closure leaves the stamp byte-identical (no churn, no re-fire loop)")
    # order-independent: a different argument order is the same closure
    RUN._code_stamp(d, "t2", [b, a])
    ck(RUN._code_stamp(d, "t2", [a, b]).read_text(encoding="utf-8") == v1,
       "the digest is order-independent")

    # a CHANGED byte must move it
    b.write_text("y = 3\n", encoding="utf-8")
    RUN._code_stamp(d, "t", [a, b])
    ck(Path(s1).read_text(encoding="utf-8") != v1, "a CHANGED byte moves the stamp")
    # LIVE bytes, not a manifest someone must remember to regenerate
    # the function BODY, with its docstring removed - the docstring legitimately explains why
    # integrity.json is NOT used, and grepping the whole segment matched that explanation
    _fn = SRC.split("def _code_stamp")[1].split("\ndef ")[0]
    _body = _fn.split('"""')[2] if _fn.count('"""') >= 2 else _fn
    ck("read_bytes()" in _body,
       "it hashes LIVE file bytes (integrity.json can go stale; live bytes cannot)")
    ck("integrity.json" not in _body,
       "it does NOT hash integrity.json (the worst honest id - it needs a human to refresh)")

    # a missing file must not crash the run
    ck(Path(RUN._code_stamp(d, "t3", [d / "nope.py"])).exists(),
       "a missing path degrades to a digest, never a crash")

    # --- the SPLIT ---------------------------------------------------------------
    ck("_is_current(built, [canonical, _build_stamp])" in SRC,
       "BUILD consumes the stamp (cheap -> auto-invalidate)")
    ck('_code_stamp(work, "deliver"' in SRC and "_deliver_inputs = [" in SRC,
       "DELIVER consumes the stamp (cheap -> auto-invalidate)")
    ck('_code_stamp(work, "merge"' in SRC, "a merge stamp is computed")
    # the load-bearing one: it must NOT be a resume input
    code = "\n".join(ln for ln in SRC.splitlines() if not ln.strip().startswith("#"))
    ck("merge_inputs.append(_merge_code)" not in code
       and "_merge_code]" not in code and "_merge_code," not in code,
       "MERGE does NOT consume it - a 40-90s cold-cache re-harvest in a ~45s window is the "
       "kill/resume spiral this must not manufacture")
    ck("--no-resume" in SRC.split('_code_stamp(work, "merge"')[1][:1200],
       "instead the orchestrator is TOLD, and handed the remedy (--no-resume)")
    ck("_say_orchestrator(" in SRC.split('_code_stamp(work, "merge"')[1][:1200],
       "...on stdout, so it is visible through mcp__shell")

    # the template is part of the build closure - a chrome edit must rebuild
    seg = SRC.split('_code_stamp(work, "build"')[1][:400]
    ck("dashboard_template.html" in seg,
       "the frozen chrome is IN the build closure (a v29 bump must rebuild built.html)")

    if fails:
        print(f"\nCODE STAMP TEST: FAIL ({len(fails)})")
        return 1
    print("\nCODE STAMP TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
