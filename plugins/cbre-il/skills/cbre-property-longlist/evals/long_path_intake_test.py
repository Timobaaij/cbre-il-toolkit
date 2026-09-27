#!/usr/bin/env python3
"""long_path_intake_test.py - an input on a path longer than Windows allows is NAMED, never lost
silently. (2026-09-26 test run, fix 3.24.)

THE DEFECT. Without the LongPathsEnabled policy, a path of 260+ characters cannot be listed,
stat'ed or opened. A deep OneDrive project plus a subject-named attachment folder reaches it, and
intake's recursive walk skipped those directories without a word: on a scratch copy 7 of 23 PDFs
and 13 of 16 emails vanished and the run carried on as if they had never been sent.

WHAT THIS PINS
  * Windows: a file reachable only through the extended-length prefix is listed in
    inventory["unreadable_long_paths"] ({file, chars}), the short-path input beside it is
    discovered as usual, intake main prints ONE loud line naming it with the remedy, and a deep
    file under an underscore folder or the work dir is not reported (the walk's usual skips).
    (A host WITH long-path support simply discovers the file - also checked.)
  * everywhere: a short-path folder yields [] and no warning; the key is always present.
Offline; the deep tree is created and removed through the \\\\?\\ prefix.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import intake as I  # noqa: E402

FAILS: list = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def _ext(p: str) -> str:
    return I._extended(p) if os.name == "nt" else p


def main() -> int:
    print("== short paths: nothing changes ==")
    td = tempfile.mkdtemp(prefix="cbre_lp_")
    try:
        inputs = Path(td) / "in"
        inputs.mkdir()
        (inputs / "Options - Northtown.pdf").write_bytes(b"%PDF-1.4\n% a\n%%EOF\n")
        inv = I.discover(inputs, email_attachments=False)
        ck(inv.get("unreadable_long_paths") == [] and I.long_path_warning(inv) == "",
           "the key is present and empty; no warning")
        ck(list(inv["clusters"]) == ["Northtown"], "the ordinary file is discovered as before")
        if os.name != "nt":
            ck(I._unreadable_long_paths(inputs, set(), None) == [],
               "off Windows the extended-length walk is never run")
    finally:
        shutil.rmtree(td, ignore_errors=True)

    if os.name != "nt":
        print("  [PASS] (not Windows - the long-path cases below do not apply)")
    else:
        print("== Windows: a path past 260 characters ==")
        td = tempfile.mkdtemp(prefix="cbre_lp2_")
        try:
            inputs = Path(td) / "in"
            work = inputs / "work"
            inputs.mkdir()
            (inputs / "Options - Northtown.pdf").write_bytes(b"%PDF-1.4\n% a\n%%EOF\n")
            deep = inputs
            while len(str(deep)) < 250:
                deep = deep / ("d" * 30)
            name = "Riverside Park brochure - very long file name.pdf"
            os.makedirs(_ext(str(deep)), exist_ok=True)
            with open(_ext(str(deep / name)), "wb") as fh:
                fh.write(b"%PDF-1.4\n% deep\n%%EOF\n")
            for hidden in (inputs / "_prior" / ("x" * 240), work / ("y" * 240)):
                os.makedirs(_ext(str(hidden)), exist_ok=True)
                with open(_ext(str(hidden / name)), "wb") as fh:
                    fh.write(b"%PDF-1.4\n% skip\n%%EOF\n")
            try:
                os.stat(str(deep / name))
                long_ok = True
            except OSError:
                long_ok = False
            inv = I.discover(inputs, exclude_dir=work, email_attachments=False)
            lp = inv.get("unreadable_long_paths") or []
            if long_ok:
                ck(lp == [] and any(name in f for c in inv["clusters"].values()
                                    for f in c.get("pdfs") or []),
                   "this host supports long paths: the deep file is simply discovered")
            else:
                ck(len(lp) == 1 and lp[0]["file"].endswith(name) and lp[0]["chars"] > 260,
                   f"the deep file is listed with its length ({[(d['file'][-40:], d['chars']) for d in lp]})")
                ck("Northtown" in inv["clusters"], "...while the short-path input is discovered as usual")
                w = I.long_path_warning(inv)
                ck(w.startswith("WARNING: 1 input file(s)") and "shorter path" in w and name in w,
                   f"the warning names the count, the file and the remedy ({w[:90]}...)")
                p = subprocess.run([sys.executable, str(HELPERS / "intake.py"), str(inputs),
                                    "--out-dir", str(work), "--client", "Example"],
                                   capture_output=True, text=True, errors="replace")
                lines = [l for l in p.stdout.splitlines() if "longer than Windows allows" in l]
                ck(p.returncode == 0 and len(lines) == 1,
                   f"intake main prints exactly ONE loud line ({len(lines)})")
            ck(not any("_prior" in d["file"] or d["file"].startswith("work/") for d in lp),
               "an underscore folder and the work dir are skipped, as in the normal walk")
        finally:
            shutil.rmtree(_ext(td), ignore_errors=True)

    print()
    if FAILS:
        print(f"LONG PATH INTAKE TEST: FAIL ({len(FAILS)})")
        return 1
    print("LONG PATH INTAKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
