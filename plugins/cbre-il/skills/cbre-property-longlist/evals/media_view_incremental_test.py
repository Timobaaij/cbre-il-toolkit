#!/usr/bin/env python3
"""media_view_incremental_test.py - the per-property MEDIA half is carried while its inputs are
unchanged and rebuilt the moment any input moves. (2026-09-26 test run, fix 2.2)

WHY THIS EXISTS. The media half had no identity, so every pass either deleted it (`never`) or
re-rendered all of it (`always`): on the real 22-deck run each blocked pass paid ~95 s to
re-render 209 page renders it had rendered the pass before, and a run whose gates passed never
wrote a media view at all, so the QA reviewers told to verify images against
work/properties/<dir>/media had none. Each half now carries a `.media_stamp.json` keyed by a hash
of everything that decides its content, and is reused only when the key matches AND the files on
disk are exactly the files it lists. The riskiest property of this change is a stale half being
reused, so most cases below move ONE input and assert a rebuild.

Cases (fixture: 2 properties with data-URI photos, a 2-page PDF drawn here with PyMuPDF - a
rectangle and an embedded PNG - that property 1 considered, and one unclaimed page):
   1. always then always: carried 2, rebuilt 0, no media file rewritten (mtimes unchanged), and
      property.json reads exactly as the fresh full view did;
   2. a changed photo on property 2 rebuilds property 2 only;
   3. never after always keeps both halves: __media.carried, media_carried of 2, no marker;
   4. a changed considered entry on property 1, then never: property 1's half is deleted
      (__media.skipped), the marker names 1 carried, property 2 is kept;
   5. a hand edit of hero.png, then always, rebuilds that property;
   6. a touched deck (mtime change) rebuilds property 1;
   7. a corrupt stamp rebuilds and does not raise;
   8. a new code fingerprint rebuilds everything; an EMPTY one is never reusable;
   9. force_media=True rebuilds everything, and leaves stamps the next pass carries;
  10. _unassigned/ is carried and rebuilt by the same rules;
  11. a stamp recording a write failure is never current (a host that failed retries);
  12. a stray file added under media/ makes the half not current.
Synthetic; no client data. Needs PyMuPDF + Pillow (as the projection itself does).
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))
import project_properties as PP          # noqa: E402

FAILS = []


def ck(ok, msg):
    print(("  [PASS] " if ok else "  [FAIL] ") + msg)
    if not ok:
        FAILS.append(msg)


def png_bytes(size=(24, 24), color=(200, 40, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def uri(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def make_deck(path: Path) -> None:
    import fitz
    doc = fitz.open()
    for i in range(2):
        pg = doc.new_page(width=400, height=300)
        pg.draw_rect(fitz.Rect(20, 20, 380, 280), color=(0, 0, 0), width=2)
        pg.insert_image(fitz.Rect(60, 60, 340, 240),
                        stream=png_bytes((300, 200), (30 * (i + 1), 120, 200)))
    doc.save(str(path))
    doc.close()


class Fixture:
    def __init__(self):
        self.td = Path(tempfile.mkdtemp(prefix="cbre_media_incr_"))
        self.work = self.td / "work"
        self.work.mkdir()
        self.src = self.td / "input"
        self.src.mkdir()
        self.deck = self.src / "estate-deck.pdf"
        make_deck(self.deck)
        self.canonical = {"meta": {}, "properties": [
            {"id": 1, "park": "Alpha Park", "city": "Northwick",
             "photo": uri(png_bytes()), "gallery": [uri(png_bytes())]},
            {"id": 2, "park": "Beta Park", "city": "Southwick",
             "photo": uri(png_bytes((16, 16), (10, 160, 10)))},
        ]}
        self.considered = {"schema_version": 1, "properties": [
            {"id": 1, "property": "Alpha Park",
             "decks": {self.deck.name: {"path": str(self.deck), "looked": [0, 1],
                                         "claimed": [0, 1], "foreign": []}},
             "hero": {"bound": True, "placeholder": False}, "plan": {"bound": False},
             "near_miss": []}],
            "unassigned": [{"file": self.deck.name, "path": str(self.deck), "pages": [1],
                            "deck_pages": 2}]}
        self.save()

    def save(self):
        (self.work / "canonical.json").write_text(json.dumps(self.canonical), encoding="utf-8")
        (self.work / "media_considered.json").write_text(json.dumps(self.considered),
                                                         encoding="utf-8")

    def build(self, mode="always", **kw):
        return PP.build(self.work, source_dir=self.src, image_cache=self.td / "cache",
                        media_view=mode, **kw)

    @property
    def root(self) -> Path:
        return self.work / "properties"

    def pdir(self, pid: int) -> Path:
        return next(self.root.glob(f"{pid:02d}-*"))

    def pjson(self, pid: int) -> dict:
        return json.loads((self.pdir(pid) / "property.json").read_text(encoding="utf-8"))

    def index(self) -> dict:
        return json.loads((self.root / "index.json").read_text(encoding="utf-8"))

    def mtimes(self, sub: Path) -> dict:
        return {str(p.relative_to(sub)): p.stat().st_mtime_ns
                for p in sub.rglob("*") if p.is_file()} if sub.exists() else {}


def main() -> int:
    fx = Fixture()
    print("== 0. a first full view stamps every half ==")
    r0 = fx.build("always")
    ck(r0.get("rebuilt") == 2 and r0.get("carried") == 0, f"first pass rebuilds both {r0}")
    st1 = fx.pdir(1) / "media" / PP.MEDIA_STAMP
    ck(st1.exists() and (fx.pdir(2) / "media" / PP.MEDIA_STAMP).exists(),
       "each property's media/ carries a stamp")
    stamp = json.loads(st1.read_text(encoding="utf-8"))
    ck(PP._DECISIONS_REL in stamp.get("files", {}) and any(k.startswith("considered/")
                                                           for k in stamp.get("files", {})),
       "the stamp lists media_decisions.json and the considered/ renders")
    ck((fx.root / "_unassigned" / PP.MEDIA_STAMP).exists(), "_unassigned/ carries its own stamp")
    pj_fresh = (fx.pdir(1) / "property.json").read_text(encoding="utf-8")

    print()
    print("== 1. always then always: nothing re-rendered ==")
    before = {1: fx.mtimes(fx.pdir(1) / "media"), 2: fx.mtimes(fx.pdir(2) / "media"),
              "u": fx.mtimes(fx.root / "_unassigned")}
    time.sleep(0.05)
    r1 = fx.build("always")
    ck(r1.get("carried") == 2 and r1.get("rebuilt") == 0, f"carried 2, rebuilt 0 {r1}")
    ck(fx.mtimes(fx.pdir(1) / "media") == before[1] and fx.mtimes(fx.pdir(2) / "media")
       == before[2], "no media file rewritten (mtimes unchanged)")
    ck((fx.pdir(1) / "property.json").read_text(encoding="utf-8") == pj_fresh,
       "property.json of a carried half reads exactly as the fresh full view did")
    ck(fx.index().get("media_carried") == [fx.pdir(1).name, fx.pdir(2).name]
       and fx.index().get("media_rebuilt") == [], "index.json lists media_carried / media_rebuilt")

    print()
    print("== 2. a changed photo rebuilds that property only ==")
    fx.canonical["properties"][1]["photo"] = uri(png_bytes((18, 18), (0, 0, 250)))
    fx.save()
    r2 = fx.build("always")
    ck(r2.get("carried") == 1 and r2.get("rebuilt") == 1
       and fx.index()["media_rebuilt"] == [fx.pdir(2).name], f"only property 2 rebuilt {r2}")

    print()
    print("== 3. never after always keeps every current half ==")
    r3 = fx.build("never")
    ck(r3.get("carried") == 2, f"both halves carried on a never pass {r3}")
    ck((fx.pdir(1) / "media" / "hero.png").exists() and (fx.pdir(2) / "media").exists(),
       "the media files are still on disk")
    m1 = fx.pjson(1).get("__media") or {}
    ck(m1.get("carried") is True and not m1.get("skipped") and "photo" in m1,
       "__media says carried (not skipped) and still names its files")
    ck("carried from an earlier full view" in (fx.pdir(1) / "notes.md").read_text(
        encoding="utf-8"), "notes.md says the media half was carried")
    ck(len(fx.index().get("media_carried") or []) == 2, "index media_carried has both")
    ck(not (fx.root / PP.MEDIA_VIEW_MARKER).exists(), "no skip marker: nothing was skipped")
    ck(fx.index().get("unassigned_carried") is True and fx.index().get("unassigned_pages") == 1,
       "_unassigned/ carried on the never pass, its page count still reported")

    print()
    print("== 4. a changed considered entry, then never: that half goes ==")
    fx.considered["properties"][0]["decks"][fx.deck.name]["looked"] = [0]
    fx.save()
    r4 = fx.build("never")
    ck(not (fx.pdir(1) / "media").exists(), "property 1's stale media half is deleted")
    ck((fx.pjson(1).get("__media") or {}).get("skipped") is True,
       "property 1 says skipped, as a never pass always did")
    ck((fx.pdir(2) / "media" / PP.MEDIA_STAMP).exists()
       and (fx.pjson(2).get("__media") or {}).get("carried") is True, "property 2 is kept")
    mk = fx.root / PP.MEDIA_VIEW_MARKER
    ck(mk.exists() and "1 of 2 property folder(s) still hold a media half carried"
       in mk.read_text(encoding="utf-8"), "the marker names the 1 carried folder")
    ck(r4.get("carried") == 1 and "1 of 2" in (fx.index().get("media_note") or ""),
       "return + index media_note agree")

    print()
    print("== 5. a hand edit of hero.png is rebuilt ==")
    fx.build("always")
    hero = fx.pdir(2) / "media" / "hero.png"
    hero.write_bytes(b"hand edited bytes, not the card's image")
    r5 = fx.build("always")
    ck(fx.pdir(2).name in fx.index()["media_rebuilt"] and hero.read_bytes()[:4] == b"\x89PNG",
       f"property 2 rebuilt and its hero restored {r5}")

    print()
    print("== 6. a touched deck rebuilds the property that considered it ==")
    st = fx.deck.stat()
    os.utime(fx.deck, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    r6 = fx.build("always")
    ck(fx.index()["media_rebuilt"] == [fx.pdir(1).name] and r6.get("carried") == 1,
       f"property 1 rebuilt, property 2 carried {r6}")
    ck(fx.index().get("unassigned_carried") is False,
       "_unassigned/ (same deck) is rebuilt too - rule 10, deck stat")

    print()
    print("== 7. a corrupt stamp rebuilds, never raises ==")
    (fx.pdir(1) / "media" / PP.MEDIA_STAMP).write_text("{not json", encoding="utf-8")
    try:
        r7 = fx.build("always")
        ck(fx.pdir(1).name in fx.index()["media_rebuilt"], f"corrupt stamp -> rebuilt {r7}")
    except Exception as e:
        ck(False, f"a corrupt stamp raised {type(e).__name__}: {e}")

    print()
    print("== 8. the code fingerprint is part of the key ==")
    orig = PP._code_fingerprint
    try:
        PP._code_fingerprint = lambda: "0" * 64
        r8 = fx.build("always")
        ck(r8.get("rebuilt") == 2 and r8.get("carried") == 0
           and fx.index().get("unassigned_carried") is False,
           f"a new fingerprint rebuilds everything {r8}")
        PP._code_fingerprint = lambda: ""
        r8b = fx.build("always")
        r8c = fx.build("always")
        ck(r8b.get("rebuilt") == 2 and r8c.get("rebuilt") == 2 and r8c.get("carried") == 0,
           "an EMPTY fingerprint is never reusable (every pass rebuilds, today's behaviour)")
    finally:
        PP._code_fingerprint = orig
    ck(PP.media_key(fx.canonical["properties"][0], None, None, None, "") is None,
       "media_key is None without a code fingerprint")
    fx.build("always")

    print()
    print("== 9. force_media rebuilds everything, then the next pass carries ==")
    r9 = fx.build("always", force_media=True)
    ck(r9.get("rebuilt") == 2 and r9.get("carried") == 0
       and fx.index().get("unassigned_carried") is False, f"forced: all rebuilt {r9}")
    r9b = fx.build("always")
    ck(r9b.get("carried") == 2 and fx.index().get("unassigned_carried") is True,
       "a forced rebuild still leaves stamps the next pass carries")

    print()
    print("== 10. _unassigned/ follows the same rules ==")
    ua = fx.root / "_unassigned"
    ua_before = fx.mtimes(ua)
    fx.build("always")
    ck(fx.index().get("unassigned_carried") is True and fx.mtimes(ua) == ua_before,
       "carried on always: nothing under _unassigned/ rewritten")
    fx.considered["unassigned"][0]["pages"] = [0, 1]
    fx.save()
    fx.build("never")
    ck(not ua.exists() and fx.index().get("unassigned_pages") is None,
       "a changed unclaimed-page list on a never pass clears it (today's behaviour)")
    fx.build("always")
    ck(ua.exists() and fx.index().get("unassigned_carried") is False
       and fx.index().get("unassigned_pages") == 2, "and the next full view rebuilds it")

    print()
    print("== 11. a stamp that recorded a write failure is never current ==")
    sp = fx.pdir(2) / "media" / PP.MEDIA_STAMP
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["could_not_write"] = [{"page": 0, "what": "render", "why": "no engine"}]
    sp.write_text(json.dumps(s), encoding="utf-8")
    fx.build("always")
    ck(fx.pdir(2).name in fx.index()["media_rebuilt"], "a failed half retries on the next pass")

    print()
    print("== 12. a stray file under media/ is not part of a current half ==")
    (fx.pdir(2) / "media" / "stray.txt").write_text("x", encoding="utf-8")
    fx.build("always")
    ck(fx.pdir(2).name in fx.index()["media_rebuilt"]
       and not (fx.pdir(2) / "media" / "stray.txt").exists(),
       "the half is rebuilt and the stray file is gone")

    try:
        import images as IMG
        IMG.close_doc_cache()
    except Exception:
        pass
    print()
    if FAILS:
        print(f"MEDIA VIEW INCREMENTAL TEST: FAIL ({len(FAILS)})")
        return 1
    print("MEDIA VIEW INCREMENTAL TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
