#!/usr/bin/env python3
"""render_qa_outdir_test.py - the --out default must anchor to the built HTML file's own
directory, never to the current working directory. (follow-up to B59's launch.json fix)

THE DEFECT: `ap.add_argument("--out", ..., default="render")` is a relative path, resolved
against argparse's caller's cwd. The skill's own documented invocation pattern runs this
script FROM the skill's install directory (`SKILL.md` "Which shell runs the helpers"), so
following the docs literally writes screenshots into the shared skill folder instead of the
client's work directory on every run that omits --out. `launch.json` got the correct fix
(anchored to html.resolve().parent) in the SAME file; the screenshot out-dir default did not.

This test never launches a browser - it only checks what `main()`'s argparse setup RESOLVES
the default to, by monkeypatching `playwright_check` to capture its `out` argument. Offline.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import render_qa as R  # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _run_main_capturing_out(argv):
    """Run render_qa.main() with sys.argv=argv, intercepting the `out` Path it would pass
    to playwright_check, without actually launching a browser."""
    captured = {}

    def fake_playwright_check(html, out):
        captured["out"] = out
        return 0  # pretend success so main() exits 0 without touching the launch.json branch

    saved_argv, saved_fn = sys.argv, R.playwright_check
    sys.argv = argv
    R.playwright_check = fake_playwright_check
    try:
        try:
            R.main()
        except SystemExit:
            pass
    finally:
        sys.argv = saved_argv
        R.playwright_check = saved_fn
    return captured.get("out")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="cbre_rq_outdir_"))
    html = work / "built.html"
    html.write_text("<html><body>ok</body></html>", encoding="utf-8")

    print("== --out omitted: default anchors to the HTML file's own directory ==")
    out = _run_main_capturing_out(["render_qa.py", str(html)])
    ck(out is not None, "playwright_check was invoked at all")
    ck(out == html.resolve().parent / "render",
       f"default out-dir is <html dir>/render, got {out!r}")
    ck(Path.cwd() not in (out.parents if out else []),
       "the default does NOT depend on the process cwd")

    print()
    print("== --out given explicitly: still honoured verbatim ==")
    explicit = work / "custom_shots"
    out2 = _run_main_capturing_out(["render_qa.py", str(html), "--out", str(explicit)])
    ck(out2 == explicit, f"explicit --out is used as-is, got {out2!r}")

    print()
    print("== --out-dir alias still works ==")
    out3 = _run_main_capturing_out(["render_qa.py", str(html), "--out-dir", str(explicit)])
    ck(out3 == explicit, f"--out-dir alias resolves the same way, got {out3!r}")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
