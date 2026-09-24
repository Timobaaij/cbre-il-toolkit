#!/usr/bin/env python3
"""preflight_deps_test.py - a missing Python package is named ONCE, up front, as the pip line
that fixes it; never as a traceback, and never as "a file could not be read".

THE DEFECT: on a Windows host the run degraded silently. `run.load_yaml` imported PyYAML
outside its try, so a missing package crashed the run with a traceback the moment a
project.yaml existed; and the quiet-mode step wrapper reported ANY stage exception - a
ModuleNotFoundError included - as "a file could not be read", sending the host looking for a
bad file when the fix was one pip install. Nothing said, at start, which packages were absent.

Pinned here:
  * `preflight.deps_line()` names every missing package in ONE line - the interpreter's own
    quoted path, `-m pip install --user`, the PIP names (pyyaml, python-pptx) - and is empty
    when all are present; `preflight.main()` prints it, and run.py's start block calls it
  * `run.load_yaml` without PyYAML prints one plain sentence and returns {}, no traceback
  * `run.call` in quiet mode reports a ModuleNotFoundError as the missing package

`importlib.util.find_spec` is stubbed, so the host's real installs do not matter. Offline.
Run: python evals/preflight_deps_test.py"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import preflight as PF  # noqa: E402
import run as RUN  # noqa: E402

FAILS = []
RSRC = (HELPERS / "run.py").read_text(encoding="utf-8", errors="replace")


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _with_find_spec(absent: set, fn):
    """Run fn() with find_spec reporting every module in `absent` as not installed and every
    other one as installed; returns (fn's result, captured stdout)."""
    saved = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name in absent else types.SimpleNamespace(name=name)

    importlib.util.find_spec = fake
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = fn()
    finally:
        importlib.util.find_spec = saved
    return res, buf.getvalue()


def _main_quiet_integrity():
    """preflight.main() with the integrity checks held healthy, so only the deps line varies."""
    saved = PF.problems, PF.ownership_problems
    PF.problems = lambda notes=None: []
    PF.ownership_problems = lambda: []
    try:
        return PF.main()
    finally:
        PF.problems, PF.ownership_problems = saved


def deps_line_cases() -> None:
    print("== 1. two packages missing -> exactly ONE pip line naming both ==")
    line, _ = _with_find_spec({"yaml", "pptx"}, PF.deps_line)
    ck("\n" not in line and "pyyaml" in line and "python-pptx" in line,
       f"one line naming pyyaml and python-pptx ({line!r})")
    ck(f'"{sys.executable}" -m pip install --user' in line,
       "...with the interpreter's own quoted path and `-m pip install --user`")
    ck(not any(p in line.split("--user", 1)[-1] for p in ("pymupdf", "pillow", "openpyxl")),
       "...and only the missing ones")
    rc, out = _with_find_spec({"yaml", "pptx"}, _main_quiet_integrity)
    pip_lines = [ln for ln in out.splitlines() if "pip install" in ln]
    ck(rc == 0 and len(pip_lines) == 1 and "pyyaml" in pip_lines[0]
       and "python-pptx" in pip_lines[0],
       f"preflight.main() prints it exactly once and still returns 0 ({pip_lines})")

    print("\n== 2. everything present -> no output at all ==")
    line, _ = _with_find_spec(set(), PF.deps_line)
    ck(line == "", f"deps_line() is empty ({line!r})")
    rc, out = _with_find_spec(set(), _main_quiet_integrity)
    ck(rc == 0 and "pip" not in out and "Missing" not in out,
       f"preflight.main() prints no dependency line ({out.strip()!r})")

    print("\n== 3. the coverage the run needs, and the start-of-run wiring ==")
    names = dict(PF.DEPS)
    for mod, pip_name in (("fitz", "pymupdf"), ("PIL", "pillow"), ("pptx", "python-pptx"),
                          ("pdfplumber", "pdfplumber"), ("openpyxl", "openpyxl"),
                          ("yaml", "pyyaml"), ("requests", "requests"),
                          ("jsonschema", "jsonschema")):
        ck(names.get(mod) == pip_name, f"{mod} is checked, as pip's '{pip_name}'")
    i = RSRC.find("preflight.problems()")
    j = RSRC.find("preflight.deps_line()")
    ck(i != -1 and j > i, "run.py's start block prints preflight.deps_line() after the "
                          "integrity check")


def load_yaml_case() -> None:
    print("\n== 4. load_yaml without PyYAML: a plain sentence, never a traceback ==")
    work = Path(tempfile.mkdtemp(prefix="cbre_deps_yaml_"))
    p = work / "project.yaml"
    p.write_text("client: Kestrel\n", encoding="utf-8")
    saved = sys.modules.get("yaml", "<absent>")
    sys.modules["yaml"] = None            # makes `import yaml` raise ImportError
    buf = io.StringIO()
    res, exc = None, None
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            res = RUN.load_yaml(p)
    except Exception as e:                # the defect: an ImportError escaping
        exc = e
    finally:
        if saved == "<absent>":
            sys.modules.pop("yaml", None)
        else:
            sys.modules["yaml"] = saved
    out = buf.getvalue()
    ck(exc is None and res == {}, f"it returns safe defaults instead of raising ({exc!r})")
    ck("missing Python package 'pyyaml'" in out and "pip install --user pyyaml" in out,
       f"...and says which package, with the install line ({out.strip()[:90]!r})")
    ck("Traceback" not in out, "...with no traceback")


def quiet_wrapper_case() -> None:
    print("\n== 5. quiet mode names a missing PACKAGE, not an unreadable file ==")

    def _mod(exc):
        m = types.ModuleType("stub_stage")

        def main():
            raise exc
        m.main = main
        return m

    saved = RUN.QUIET
    RUN.QUIET = True
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = RUN.call(_mod(ModuleNotFoundError("No module named 'pptx'", name="pptx")))
        out = buf.getvalue()
        ck(rc == 1 and "missing Python package 'python-pptx'" in out
           and "could not be read" not in out,
           f"a ModuleNotFoundError reads as the missing package ({out.strip()!r})")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            RUN.call(_mod(OSError("boom")))
        ck("a file could not be read" in buf.getvalue(),
           "...while any other failure keeps the neutral line")
    finally:
        RUN.QUIET = saved


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    deps_line_cases()
    load_yaml_case()
    quiet_wrapper_case()
    print()
    if FAILS:
        print(f"STATUS: BLOCKED ({len(FAILS)} failure(s))")
        return 1
    print("STATUS: ALL-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
