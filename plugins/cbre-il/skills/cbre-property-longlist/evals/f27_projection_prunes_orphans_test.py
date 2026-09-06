#!/usr/bin/env python3
"""f27_projection_prunes_orphans_test.py - a run whose property COUNT DROPS leaves no orphans. (F27)

WHY THIS EXISTS, from a live run. At the end of it `properties/` held ELEVEN numbered directories
for NINE shipped records, plus `_unassigned/`. Two were left over from the structure before a
broker collapsed one deck to a single card. Projection rebuilds the view on every pass and never
removed a directory that no longer corresponded to a property.

It was not cosmetic. A blind reviewer closed its report with "the 11 property directories against
9 shipped records are unexplained", so the orphans cost a reviewer real effort and left it unable
to close a question about the size of the dataset. An operator investigating a card would find
directories for buildings that are not on the dashboard. Any run whose count drops reaches it: a
broker collapsing records, an exclusion, or a re-read producing fewer.

The exact live sequence is what this reproduces: build a view, then rebuild from a canonical with
fewer properties, and assert the surplus is gone. It also pins the two things pruning must NOT do,
because a prune that is too eager is worse than the orphans it removes.

Offline.
"""
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


def canonical(n):
    names = ["Alpha Park", "Beta Park", "Gamma Park", "Delta Park"]
    return {"meta": {}, "properties": [
        {"id": i + 1, "park": names[i], "city": "Northwick", "warehouseArea": 1000 * (i + 1)}
        for i in range(n)]}


def dirs(work):
    return sorted(p.name for p in (work / "properties").iterdir() if p.is_dir())


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="cbre_f27_"))
    cpath = work / "canonical.json"

    print("== the live sequence: four properties, then two ==")
    cpath.write_text(json.dumps(canonical(4)), encoding="utf-8")
    PP.build(work, media_view="never")
    before = dirs(work)
    ck(len(before) == 4, f"four property directories written first: {before}")

    cpath.write_text(json.dumps(canonical(2)), encoding="utf-8")
    res = PP.build(work, media_view="never")
    after = dirs(work)
    ck(len(after) == 2,
       f"after a rebuild from two properties, exactly two directories remain: {after} "
       f"(this is the 11-against-9 defect: it used to be {len(before)})")
    ck(all(d.startswith(("01-", "02-")) for d in after),
       "the surviving directories are the ones that still correspond to a property")
    ck(isinstance(res, dict), "build() still returns its summary dict")

    print()
    print("== what pruning must NOT remove ==")
    root = work / "properties"
    (root / "notes-i-left-here").mkdir(exist_ok=True)
    (root / "notes-i-left-here" / "mine.txt").write_bytes(b"x")
    PP.build(work, media_view="never")
    now = dirs(work)
    # _unassigned/ is NOT a survivor case: it belongs to the MEDIA half (it holds page renders
    # of the pages no property claimed), so `never` deliberately does not write it and clears a
    # stale one. That is stated in index.json's own media_note rather than left to be inferred,
    # which is what stops an absent folder reading as a harvest that found nothing.
    ck("_unassigned" not in now,
       "_unassigned/ is part of the media half, so a skipped view clears it rather than leaving "
       "a stale one from a pass that did write it")
    ck("notes-i-left-here" in now,
       "a directory that does not match the numbered shape is LEFT ALONE, never assumed to be "
       "ours to delete: a prune that is too eager is worse than the orphans it removes")

    print()
    print("== the index never outlives the thing it describes ==")
    idx = json.loads((root / "index.json").read_text(encoding="utf-8-sig"))
    listed = sorted(str(e.get("dir")) for e in (idx.get("properties") or [])
                    if isinstance(e, dict))
    ck(listed == ["01-alpha-park", "02-beta-park"],
       f"index.json lists only the surviving property directories, never a stale eleventh: {listed}")
    ck(idx.get("count") == 2, "index.json's own count agrees with what is on disk")
    ck("_unassigned" in str(idx.get("media_note") or ""),
       "the media_note names _unassigned/ among what was deliberately not written, so its "
       "absence is a STATED decision rather than a silence a reader must interpret")
    ck("could_not_prune" in idx,
       "index.json always carries could_not_prune, so 'nothing was stuck' is a STATED result "
       "rather than an absence a reader has to interpret")
    ck(idx.get("could_not_prune") == [],
       "nothing was stuck on this run")
    ck(sorted(idx.get("unrecognised") or []) == ["notes-i-left-here"],
       "a directory pruning declined to touch is REPORTED rather than silently ignored: "
       "shutil.rmtree(ignore_errors=True) returning without a word is how the orphans came to "
       "exist in the first place")
    ck(PP._NUMBERED_DIR_RX.match("01-alpha-park") and not PP._NUMBERED_DIR_RX.match("_unassigned"),
       "the numbered-directory shape is what pruning keys on, and the underscore prefix is what "
       "keeps _unassigned/ out of its reach")

    print()
    if FAILED:
        print(f"F27 PROJECTION PRUNES ORPHANS TEST: FAIL ({len(FAILED)})")
        for m in FAILED:
            print("   - " + m)
        return 1
    print("F27 PROJECTION PRUNES ORPHANS TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
