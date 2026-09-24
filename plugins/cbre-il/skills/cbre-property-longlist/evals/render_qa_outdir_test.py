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

ALSO PINNED: the INSTALLED-BROWSER fallback. 'pip install playwright' without 'playwright
install chromium' made the default launch raise, and the check fell to the structural floor
(NEEDS-PREVIEW-MCP) on Windows hosts that had Edge all along. A stub Playwright whose default
launch raises and whose `channel="msedge"` launch works must now render for real; with no
browser at all, the -1 branch must print the install command.
"""
from __future__ import annotations
import contextlib
import io
import sys
import tempfile
import types
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


def _run_with_stub_playwright(argv, launchable: set):
    """Run render_qa.main() against a stub `playwright.sync_api` whose chromium.launch(**kw)
    succeeds only for the channels in `launchable` ('' = the bundled Chromium). Returns
    (the launch kwargs tried, stdout, exit code)."""
    tried = []

    class _Page:
        def on(self, *a): pass
        def goto(self, *a): pass
        def wait_for_timeout(self, *a): pass
        def eval_on_selector_all(self, *a): return 2
        def evaluate(self, expr): return 2 if "PROPS" in expr else None
        def screenshot(self, path, full_page=False): Path(path).write_bytes(path.encode())

    class _Browser:
        def new_page(self, **k): return _Page()
        def close(self): pass

    class _Chromium:
        def launch(self, **kw):
            tried.append(kw)
            if kw.get("channel", "") not in launchable:
                raise RuntimeError("Executable doesn't exist - run 'playwright install'")
            return _Browser()

    @contextlib.contextmanager
    def sync_playwright():
        yield types.SimpleNamespace(chromium=_Chromium())

    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = sync_playwright
    saved = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}
    sys.modules["playwright"] = types.ModuleType("playwright")
    sys.modules["playwright.sync_api"] = api
    class _Buf(io.StringIO):              # main() calls sys.stdout.reconfigure()
        def reconfigure(self, **k): pass

    saved_argv, buf, code = sys.argv, _Buf(), None
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(buf):
            try:
                R.main()
            except SystemExit as e:
                code = e.code
    finally:
        sys.argv = saved_argv
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return tried, buf.getvalue(), code


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
    print("== bundled Chromium missing, Edge installed: renders with Edge ==")
    shots = work / "edge_shots"
    tried, out, code = _run_with_stub_playwright(
        ["render_qa.py", str(html), "--out", str(shots)], {"msedge"})
    ck(tried[:2] == [{}, {"channel": "msedge"}],
       f"the default launch is tried first, then channel='msedge' ({tried})")
    ck("NEEDS-PREVIEW-MCP" not in out and "STATUS: ALL-PASS" in out and code == 0,
       f"a real render ran - STATUS is not NEEDS-PREVIEW-MCP (exit {code}, "
       f"{[ln for ln in out.splitlines() if ln.startswith('STATUS')]})")
    ck("installed msedge" in out, "...and the output says which browser rendered it")

    print()
    print("== no browser at all: the fallback path names the install command ==")
    tried, out, code = _run_with_stub_playwright(
        ["render_qa.py", str(html), "--out", str(shots)], set())
    ck([k.get("channel") for k in tried] == [None, "msedge", "chrome"],
       f"Edge and then Chrome are tried before giving up ({tried})")
    ck("-m playwright install chromium" in out,
       "the -1 branch prints `python -m playwright install chromium`")

    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
