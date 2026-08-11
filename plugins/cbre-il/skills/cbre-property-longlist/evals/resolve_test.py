#!/usr/bin/env python3
"""resolve_test.py - one deterministic basename -> path resolver. (B13)

Three resolvers existed and all three were wrong in different ways:
  merge._resolve_source          - UNSORTED first rglob hit
  vision_validate._resolve_source - UNSORTED first rglob hit
  extract_pdf._resolve_pdf        - sorted, but sorted PATH OBJECTS (case-folded on
                                    Windows, case-sensitive on POSIX) and passed the
                                    basename as a GLOB PATTERN, so "Unit [1].pdf" -> None

Worse than filesystem-order flakiness: with two same-named decks, records from BOTH resolve
to ONE path, and because _deck_ownership keys on the resolved path string the collision
reads as a two-cluster page anchor - so BOTH properties silently lose their gallery.
sorted() alone would only make that wrong answer reproducible, so intake also NOTES the
collision. It does not refuse it: "Site A/photos.pdf" + "Site B/photos.pdf" is a legitimate
folder, and refusing it would hard-code an input-shape assumption. Offline."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))
import _common as C  # noqa: E402
import merge as M  # noqa: E402
import vision_validate as VV  # noqa: E402
import extract_pdf as XP  # noqa: E402


def main() -> int:
    fails = []

    def ck(ok, l):
        print(f"  [{'PASS' if ok else 'FAIL'}] {l}")
        if not ok:
            fails.append(l)

    ck(hasattr(C, "resolve_by_name") and hasattr(C, "resolve_candidates"),
       "_common.resolve_by_name / resolve_candidates exist")
    if not hasattr(C, "resolve_candidates"):
        print(f"\nRESOLVE TEST: FAIL ({len(fails)})")
        return 1

    d = Path(tempfile.mkdtemp(prefix="cbre_res_"))
    (d / "Site B").mkdir(parents=True)
    (d / "Site A").mkdir(parents=True)
    (d / "Site A" / "photos.pdf").write_bytes(b"%PDF-A")
    (d / "Site B" / "photos.pdf").write_bytes(b"%PDF-B")
    (d / "top.pdf").write_bytes(b"%PDF-TOP")
    (d / "Unit [1].pdf").write_bytes(b"%PDF-BRACKET")

    # deterministic, and STABLE across repeated calls
    r1 = C.resolve_by_name(d, "photos.pdf")
    r2 = C.resolve_by_name(d, "photos.pdf")
    ck(r1 == r2 and r1 is not None, f"a colliding basename resolves stably {ascii(str(r1))}")
    ck(r1.parent.name == "Site A",
       f"...to the POSIX-relpath-first candidate, not a filesystem-order one ({r1.parent.name})")
    ck(len(C.resolve_candidates(d, "photos.pdf")) == 2, "both candidates are reported")

    # a file directly under the root wins over any nested namesake
    (d / "Site A" / "top.pdf").write_bytes(b"%PDF-NESTED")
    ck(C.resolve_by_name(d, "top.pdf") == d / "top.pdf",
       "a root-level file wins over a nested namesake")

    # GLOB METACHARACTERS: the old sorted(rglob(base)) treated these as a pattern
    ck(C.resolve_by_name(d, "Unit [1].pdf") == d / "Unit [1].pdf",
       "a bracketed filename resolves (it is a NAME, never a glob pattern)")
    ck(C.resolve_by_name(d, "nope.pdf") is None, "a missing name resolves to None")
    ck(C.resolve_by_name(d, "") is None, "an empty name resolves to None")

    # all three call sites must agree - that is the whole point of sharing one resolver
    M._SRC_RESOLVE.clear()
    a = M._resolve_source(d, "photos.pdf")
    b = VV._resolve_source(d, "photos.pdf")
    c = XP._resolve_pdf(d, "photos.pdf")
    ck(a == b == c == r1,
       f"merge, vision_validate and extract_pdf resolve IDENTICALLY {ascii(str((a, b, c)))}")
    ck(XP._resolve_pdf(d, "Unit [1].pdf") == d / "Unit [1].pdf",
       "extract_pdf handles the bracketed name too (it used to return None)")

    # the memo must be keyed on the DIRECTORY as well as the name
    d2 = Path(tempfile.mkdtemp(prefix="cbre_res2_"))
    (d2 / "photos.pdf").write_bytes(b"%PDF-OTHER")
    ck(M._resolve_source(d2, "photos.pdf") == d2 / "photos.pdf",
       "a second source_dir is not served the first one's memoised hit")

    # the collision must be SURFACED, not silently resolved
    ck(hasattr(C, "basename_collisions"), "_common.basename_collisions exists")
    if hasattr(C, "basename_collisions"):
        col = C.basename_collisions(d)
        ck("photos.pdf" in col and len(col["photos.pdf"]) == 2,
           f"the collision is reported {ascii(str(list(col)))}")
        ck("top.pdf" in col, "a root/nested collision is reported too")
        ck("Unit [1].pdf" not in col, "a unique name is not reported")
    isrc = (HELPERS / "intake.py").read_text(encoding="utf-8", errors="replace")
    ck("basename_collisions" in isrc, "intake surfaces the collision as a NOTE")
    ck("sys.exit" not in isrc.split("basename_collisions")[-1][:400],
       "...and does NOT refuse the folder (two same-named decks is legitimate)")

    # the ownership mark must survive an edit to _common
    csrc = (HELPERS / "_common.py").read_text(encoding="utf-8", errors="replace")
    ck("OWNER_MARK" in csrc and "OWNER_NOTICE" in csrc,
       "the _common ownership constants are intact (preflight checks them)")

    if fails:
        print(f"\nRESOLVE TEST: FAIL ({len(fails)})")
        return 1
    print("\nRESOLVE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
