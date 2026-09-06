#!/usr/bin/env python3
"""f20_media_view_flag_test.py - the per-property view's EXPENSIVE half is opt-in. (F20)

WHY THIS EXISTS. Measured on a live run, `projection` was 42.06s of a 50.30s pass - 84%, more
than five times every other stage put together, while actually building the dashboard took 0.15s.
What it spends that on is `properties/`, 82 MB across 352 files, and `reference/per-property.md`
states in its own words that the view is rebuilt every run, that NOTHING READS IT BACK, that
editing a file there changes nothing, and that an eval asserts exactly that. It is a human
debugging aid. The work dir also commonly sits inside a cloud-synced folder, so every pass hands
that 82 MB to a sync client, which is not in the 42 seconds.

So the media half is now a flag, and this pins the flag rather than the timing: a wall-clock
assertion would be flaky on a loaded machine and would say nothing about correctness. What is
asserted is that the CHEAP half always survives - `notes.md` in particular, because it carries the
property's repair key, and the whole design principle is that the surface showing you the problem
hands you what you need to fix it - and that a skipped view SAYS it was skipped. An absent
`media/` is otherwise indistinguishable from a harvest that found nothing, which is a documented
failure class in this skill.

Offline. No network, no PDF engine, no image library beyond what a bound photo needs.
"""
import base64
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
import project_properties as PP  # noqa: E402

FAILED = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILED.append(msg)


# a real 1x1 PNG, so the bound-media path has something to write
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
DATA_URI = "data:image/png;base64," + base64.b64encode(PNG).decode()


def fixture():
    work = pathlib.Path(tempfile.mkdtemp(prefix="cbre_f20_"))
    canonical = {"meta": {}, "properties": [
        {"id": 1, "park": "Alpha Park", "city": "Northwick", "photo": DATA_URI,
         "gallery": [DATA_URI], "warehouseArea": 10000},
        {"id": 2, "park": "Beta Park", "city": "Southwick", "photo": DATA_URI},
    ]}
    (work / "canonical.json").write_text(json.dumps(canonical), encoding="utf-8")
    return work


def media_files(work):
    return sorted(p.name for p in (work / "properties").rglob("*")
                  if p.is_file() and p.parent.name in ("media", "considered"))


def main() -> int:
    print("== the flag itself: _want_media is the ONE reader ==")
    ck(PP.MEDIA_VIEW_CHOICES == ("auto", "always", "never"),
       "the three choices contract C4 names, in that order")
    ck(PP._want_media("always") is True, "'always' writes the media half")
    ck(PP._want_media("never") is False, "'never' skips it")
    ck(PP._want_media("auto") is False,
       "'auto' skips it too: the default is the CHEAP view, which is the whole point of F20")
    # None is not a fourth mode. It means "no flag was given", which an in-process caller written
    # before the flag existed relies on, so the older boolean still decides for them.
    ck(PP._want_media(None, True) is True and PP._want_media(None, False) is False,
       "media_view=None defers to the legacy `media` boolean, so a pre-flag caller is unchanged")
    try:
        PP._want_media("sometimes")
        ck(False, "an unknown mode raises rather than silently picking one")
    except ValueError as e:
        ck("sometimes" in str(e), "an unknown mode raises ValueError naming the bad value")

    print()
    print("== 'always' writes both halves ==")
    w = fixture()
    PP.build(w, media_view="always")
    root = w / "properties"
    ck((root / "index.json").exists(), "index.json written")
    ck(len(list(root.glob("0*-*"))) == 2, "one directory per property")
    ck(len(media_files(w)) > 0, "the media half is on disk")
    ck(not (root / PP.MEDIA_VIEW_MARKER).exists(),
       "no skip marker when nothing was skipped")

    print()
    print("== 'never' keeps the CHEAP half and drops only the expensive one ==")
    w2 = fixture()
    PP.build(w2, media_view="never")
    root2 = w2 / "properties"
    d1 = next(root2.glob("01-*"))
    for name in ("property.json", "sources.csv", "notes.md"):
        ck((d1 / name).exists(), f"{name} still written: the cheap half is not optional")
    ck((root2 / "index.json").exists(), "index.json still written")
    ck(media_files(w2) == [],
       "not one media or considered file written: this is the 82 MB and the 42 seconds")
    ck(not (d1 / "media").exists() and not (d1 / "media" / "considered").exists(),
       "the media directories are absent, not merely empty")

    print()
    print("== a skipped view SAYS it was skipped, and says how to get the full one ==")
    marker = root2 / PP.MEDIA_VIEW_MARKER
    ck(marker.exists(),
       "a marker file is written: an absent media/ is otherwise indistinguishable from a harvest "
       "that found nothing, which is a documented failure class here")
    txt = marker.read_text(encoding="utf-8")
    ck("--media-view always" in txt,
       "the marker carries the exact flag that rebuilds the full view, not a description of it")
    cmd = PP.rebuild_command(w2, source_dir="/some/input")
    ck("--media-view always" in cmd and "--work" in cmd,
       "rebuild_command() composes a runnable invocation rather than leaving the reader to "
       "reconstruct it from a docstring")

    print()
    print("== notes.md keeps the repair key, which is the reason the cheap half is kept ==")
    notes = (d1 / "notes.md").read_text(encoding="utf-8")
    ck("|" in notes and "alpha park" in notes.lower(),
       "the property's repair key is still printed in the skipped view: the surface that shows "
       "you the problem must hand you what you need to fix it")

    print()
    if FAILED:
        print(f"F20 MEDIA VIEW FLAG TEST: FAIL ({len(FAILED)})")
        for m in FAILED:
            print("   - " + m)
        return 1
    print("F20 MEDIA VIEW FLAG TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
