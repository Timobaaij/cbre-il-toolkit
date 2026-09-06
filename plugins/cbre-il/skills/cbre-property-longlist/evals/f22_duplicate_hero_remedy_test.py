#!/usr/bin/env python3
"""f22_duplicate_hero_remedy_test.py - the duplicate-hero finding's remedy is reachable when it
blocks.

THE DEFECT, live. The `images` gate blocked with: have the G-images reviewer check the contact
sheet, fix the harvest, or acknowledge it. But `images` is PRE-BUILD (exit 5/6) and G-images is a
QA-window reviewer dispatched at exit 14, AFTER a build that cannot happen until this gate passes.
The remedy named a reader who could not yet exist and an aid (the contact sheet) the spine renders
only after the scorecard. The operator's real options at that moment were fix blind, or
acknowledge, and only then would anyone look.

THE CHOICE: the gate renders the contact sheet ITSELF, only when the finding fires, and prints the
path; the message says the reviewer runs later and that the choice now is fix-or-acknowledge,
with the exact `ack` command. The check stays pre-build: a duplicated hero is a data defect the
reviewers should judge FIXED, and moving it post-build would put the fix after the one review
round, which the one-round rule forbids (and would need run.py, which this fix does not own).

WHAT THIS PINS:
  1. two properties sharing one hero BLOCK, and the message no longer sends the operator to a
     reviewer who cannot run yet;
  2. render/contact_sheet.png exists beside the canonical after the block, and is named;
  3. the message carries the exact `gate_runner.py ack --add duplicate_photos_ok=<hash>` command;
  4. that ack clears the block through the real `ack` command;
  5. a clean run renders nothing (the sheet is an aid for a human about to look, not a cost on
     every pass).
Offline; needs Pillow for the render assertion (degrades to the fallback wording without it).
"""
from __future__ import annotations

import base64
import io
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "helpers" / "gate_runner.py"

FAILS: list[str] = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def photo(seed: str) -> str:
    """A tiny PHOTO-kind data URI (random texture, not a solid fill), byte-identical per seed."""
    from PIL import Image
    rnd = random.Random(seed)
    img = Image.new("RGB", (64, 48))
    img.putdata([(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))
                 for _ in range(64 * 48)])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def canon(d: Path, photos: list[str]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    c = d / "canonical.json"
    c.write_text(json.dumps({"meta": {}, "pois": [], "regions": {}, "properties": [
        {"id": i + 1, "park": f"Park {i + 1}", "developer": "Dev", "city": "Town",
         "country": "DE", "status": "Existing", "photo": ph} for i, ph in enumerate(photos)]}),
        encoding="utf-8")
    return c


def run(*args) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GATE), *[str(a) for a in args]],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    try:
        import PIL  # noqa: F401
        has_pil = True
    except ImportError:
        has_pil = False
        print("  (no Pillow: the render assertion degrades to the fallback wording)")
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        shared = photo("cover")

        print("1. two cards, one hero: BLOCK, and the remedy is for NOW")
        c = canon(t / "dup", [shared, shared, photo("other")])
        rc, out = run("images", c)
        ck(rc == 1 and "share ONE IDENTICAL hero photo" in out, "the duplicate hero blocks")
        ck("have the G-images reviewer check the contact sheet" not in out,
           "it no longer tells the operator to hand it to a reviewer who is dispatched after the build")
        ck("runs AFTER the build this blocks" in out and "nobody else can look now" in out,
           "it says the reviewer runs later and that the choice is the operator's now")
        ck("FIX the harvest" in out and "acknowledge it with" in out,
           "the two real options are named: fix, or acknowledge")
        sheet = t / "dup" / "render" / "contact_sheet.png"
        if has_pil:
            ck(sheet.exists() and sheet.stat().st_size > 0,
               "the contact sheet was rendered beside the canonical, by the gate, at block time")
            ck(str(sheet) in out and "rendered by this gate, now" in out,
               "...and its path is printed in the finding")
        else:
            ck("could not be rendered here" in out, "without Pillow the message says so and points at work/vision/")

        print("2. the printed ack command clears it, through the real `ack`")
        m = re.search(r"--add duplicate_photos_ok=([0-9a-f]{12})", out)
        ck(bool(m), "the message carries the exact --add duplicate_photos_ok=<hash> argument")
        if m:
            rc2, out2 = run("ack", "--work", t / "dup", "--add", f"duplicate_photos_ok={m.group(1)}")
            ck(rc2 == 0, "`ack` merges the key into placeholder_audit_ack.json")
            rc3, out3 = run("images", c)
            ck(rc3 == 0 and "STATUS: ALL-PASS" in out3, "the acknowledged duplicate no longer blocks")

        print("3. a clean run renders nothing")
        c2 = canon(t / "clean", [photo("a"), photo("b"), photo("c")])
        rc, out = run("images", c2)
        ck(rc == 0 and not (t / "clean" / "render").exists(),
           "distinct heroes: ALL-PASS and no render/ directory (the sheet is for a human about to look)")

        print("4. the WHY is in the gate")
        src = GATE.read_text(encoding="utf-8")
        ck("THE REMEDY MUST BE REACHABLE AT THE MOMENT IT BLOCKS" in src
           and "stays pre-build on purpose" in src,
           "gate_runner states the exit-5/6 vs exit-14 mismatch and why the check did not move")

    print()
    if FAILS:
        print(f"F22 DUPLICATE HERO REMEDY TEST: FAIL ({len(FAILS)})")
        return 1
    print("F22 DUPLICATE HERO REMEDY TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
