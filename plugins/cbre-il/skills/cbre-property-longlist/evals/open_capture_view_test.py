#!/usr/bin/env python3
"""open_capture_view_test.py - read-but-not-shown captures reach the per-property view.

extract_xlsx routes commentary / denied-key / CJK-only columns to __meta.open_capture
(read, never client-shown), but merge pops __meta - so the values survived only in
work/extract, unreadable from the place people actually look when a card seems thin.
Pinned here: merge carries them into canonical.meta.openCapture (by property id) and
project_properties prints them in the property's notes.md. Offline.
"""
import json
import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "helpers"))
import project_properties as PP  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)


work = pathlib.Path(tempfile.mkdtemp(prefix="cbre_ocview_"))
canonical = {
    "meta": {"openCapture": {"1": [
        {"column": "Comments", "value": "internal note text",
         "locator": "Sheet1!r7", "source_file": "tracker.xlsx"}]}},
    "properties": [
        {"id": 1, "park": "Alpha Park", "city": "Corby"},
        {"id": 2, "park": "Beta Park", "city": "Rugby"},
    ],
}
(work / "canonical.json").write_text(json.dumps(canonical), encoding="utf-8")
PP.build(work, media=False)

root = work / "properties"
notes1 = next(root.glob("01-*/notes.md")).read_text(encoding="utf-8")
check("section", "Read but not shown on the card" in notes1)
check("value", "internal note text" in notes1)
check("column", "Comments" in notes1)
check("locator", "Sheet1!r7" in notes1)

notes2 = next(root.glob("02-*/notes.md")).read_text(encoding="utf-8")
check("no-section-when-empty", "Read but not shown" not in notes2)

print("OPEN CAPTURE VIEW TEST: PASS")
