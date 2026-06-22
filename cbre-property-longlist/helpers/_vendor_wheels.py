"""_vendor_wheels.py - use a BUNDLED manylinux wheel (the skill's `vendor/*.whl`) when
the system package is absent and there is no pip/network (the Cowork sandbox).

`ensure(import_name, wheel_kw)` returns one of:
  "system"   - already importable from the environment; nothing done.
  "vendored" - was absent; a bundled wheel matching THIS interpreter (python tag + abi +
               linux arch) was unpacked ONCE to a temp cache, prepended to sys.path, and
               now imports.
  "missing"  - still not importable (no system package AND no compatible bundled wheel,
               or the wheel failed to load).

It NEVER raises and is a strict NO-OP whenever the package is already importable - so the
native-PyMuPDF / system-Pillow paths and the shim's own tests are completely untouched.
The bundled wheels are platform-locked: on any non-matching interpreter `_compatible`
rejects them and the skill degrades exactly as before (fitz_shim / Pillow-absent
placeholder). Pure stdlib.
"""
from __future__ import annotations

import re
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent.parent / "vendor"


def _compatible(fn) -> bool:
    """True if the wheel filename matches THIS interpreter: linux, same arch, and a
    python/abi tag this Python satisfies (cp3X-cp3X exact, or cp3Y-abi3 with Y <= X).

    Accepts a str OR a pathlib.Path: a Path has no `.endswith`/substring support, so a
    Path argument would otherwise raise AttributeError, get swallowed by `ensure`'s
    try/except, and silently reject EVERY wheel (the wheel never loads -> the shim runs ->
    decks needlessly route to vision). `str(fn)` makes the check work either way."""
    fn = str(fn)
    if not fn.endswith(".whl"):
        return False
    plat = sysconfig.get_platform()              # 'linux-x86_64' | 'win-amd64' | ...
    if "linux" not in plat:
        return False
    if plat.split("-")[-1] not in fn:            # 'x86_64' / 'aarch64' must appear
        return False
    v = sys.version_info
    if v.major != 3:
        return False
    tag = f"cp3{v.minor}"
    if f"-{tag}-{tag}-" in fn or f"-{tag}-abi3-" in fn:
        return True
    m = re.search(r"-cp3(\d{1,2})-abi3-", fn)    # abi3 is forward-compatible
    return bool(m) and int(m.group(1)) <= v.minor


# Why the most recent ensure() did NOT yield a usable package (when it returns "missing").
# Empty on "system"/"vendored". Surfaced by run.py's PDF-engine line so a real glibc/arch/
# version mismatch is diagnosable instead of a silent shim fallback.
_LAST_ERROR = ""


def ensure(import_name: str, wheel_kw: str | None = None) -> str:
    global _LAST_ERROR
    _LAST_ERROR = ""
    try:
        __import__(import_name)
        return "system"
    except Exception:
        pass
    try:
        if not _VENDOR.is_dir():
            _LAST_ERROR = f"no vendor/ directory at {_VENDOR}"
            return "missing"
        kw = (wheel_kw or import_name).lower()
        cands = sorted(_VENDOR.glob("*.whl"))
        whl = next((w for w in cands if kw in w.name.lower() and _compatible(w.name)), None)
        if whl is None:
            named = [w.name for w in cands if kw in w.name.lower()] or [w.name for w in cands]
            _LAST_ERROR = (f"no bundled '{kw}' wheel matches this interpreter "
                           f"(platform={sysconfig.get_platform()}, cp3{sys.version_info.minor}); "
                           f"candidates: {named}")
            return "missing"
        cache = Path(tempfile.gettempdir()) / "cbre_longlist_vendor" / whl.stem
        if not (cache / ".ok").exists():
            cache.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(whl) as z:
                z.extractall(cache)
            (cache / ".ok").write_text("ok")
        if str(cache) not in sys.path:
            sys.path.insert(0, str(cache))
        __import__(import_name)
        return "vendored"
    except Exception as e:
        # e.g. the manylinux .so needs a newer glibc than the sandbox has, or a corrupt wheel
        _LAST_ERROR = f"{type(e).__name__}: {e}"
        return "missing"
