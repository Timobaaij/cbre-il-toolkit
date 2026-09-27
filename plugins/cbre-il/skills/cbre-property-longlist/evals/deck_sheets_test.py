#!/usr/bin/env python3
"""deck_sheets_test.py - deck-level contact sheets for readers (2026-09-26 test run, fix 1.2) and
the reader rule that survives a host per-message tool-call cap (fix 2.4).

THE DEFECTS (one live 22-deck run):
  1.2  the visual aids were PER PAGE: ~12 image reads per deck (149 renders + 44 sheets + the
       single-candidate thumbs, ~263 reads), each read a round trip, and under a host capping
       parallel calls at 3 every extra read is another ~17 s. Separately, a 3x3 sheet of 384 px
       tiles (1184x1262 = 1.49 MP) exceeded the ~1,600-token vision budget, so the API
       downscaled the whole canvas: the "native size" promise did not hold.
  2.4  the reader prompt demanded ONE message for the batch; a host that denies call 4+ turned a
       13-page deck into 7-9 messages of denied turns, and the reader could not learn the cap.

What this pins (synthetic 8-page PDF, flat-colour images, no client data):
  1. the deck entry carries render_sheets and candidate_sheets, paginated as the budget implies;
  2. every sheet is within both edge caps AND the pixel budget;
  3. every candidate's colour is present across the candidate sheets (none dropped);
  4. per-page renders / candidates / candidates_sheet are all still there (zoom + fallback);
  5. deleting one deck sheet makes the cached entry unusable (_entry_aids_intact False);
  6. PREP_SCHEMA is 4; without Pillow both keys are [] and the entry is otherwise valid;
  7. captions are `page_no N` / `page_no N / index K`;
  8. both reader renders carry the host-cap clause; CLAUDE_MAX_PARALLEL_TOOLS=3 puts
     "at most 3 tool calls" into a stub's Run context; the skill's own override wins; unset or
     invalid leaves the Run context default byte-identical.

Run: python evals/deck_sheets_test.py"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "helpers"))

try:
    import fitz  # noqa: E402
except Exception:  # pragma: no cover
    fitz = None
import contact_sheet as CS  # noqa: E402
import images as IMG  # noqa: E402
import interpret_prep as IP  # noqa: E402
import prompts_render as PR  # noqa: E402

FILLER = ("Unit specification: warehouse area 12,500 sq m, clear height 12 m, 10 dock doors, "
          "two level access doors, 40 m yard depth, BREEAM Very Good. ")
_SLOT_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_AUTO = {"SKILL_DIR", "CONTEXT", "FIELD_REGISTRY", "COMMON_POINTER",
         "READER_CONTRACT", "READER_CONTRACT_BODY"}


def _colour(p: int, k: int) -> tuple:
    return (20 + p * 25, 30 + k * 60, 200 - p * 15)


def _fixture(path: Path) -> dict:
    """8 pages, 1-3 flat-colour hero-size images each; returns {page: [colour, ...]}."""
    from PIL import Image
    doc = fitz.open()
    want = {}
    for p in range(8):
        pg = doc.new_page(width=842, height=595)
        pg.insert_text((20, 560), FILLER, fontsize=8)
        n = 1 + p % 3
        want[p] = []
        for k in range(n):
            col = _colour(p, k)
            b = io.BytesIO()
            Image.new("RGB", (800 - k * 60, 500 - k * 30), col).save(b, "PNG")
            pg.insert_image(fitz.Rect(10 + k * 270, 10, 270 + k * 270, 200), stream=b.getvalue())
            want[p].append(col)
    doc.save(str(path))
    doc.close()
    return want


def _expected_sheets(n: int, tile_w: int, tile_h: int) -> int:
    """Independent restatement of the budget: fewest sheets with every sheet under both edge caps
    and the pixel budget, tiles never resized."""
    sw = tile_w + CS.PAD
    sh = tile_h + CS.MONTAGE_CAPTION_H + CS.PAD
    best = n
    for cols in range(1, n + 1):
        W = CS.PAD + cols * sw
        if cols > 1 and W > CS.MONTAGE_MAX_EDGE:
            break
        rows = 0
        while (CS.PAD + (rows + 1) * sh <= CS.MONTAGE_MAX_EDGE
               and W * (CS.PAD + (rows + 1) * sh) <= CS.MONTAGE_MAX_PIXELS):
            rows += 1
        per = max(1, cols * max(1, rows))
        best = min(best, -(-n // per))
    return best


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print(f"[FAIL] {msg}")
        else:
            print(f"[PASS] {msg}")

    check(IP.PREP_SCHEMA == 4, f"PREP_SCHEMA is 4 (got {IP.PREP_SCHEMA})")

    if fitz is None or not CS._HAS_PIL or IMG.Image is None or not hasattr(fitz, "Rect"):
        print("[SKIP] native PyMuPDF + Pillow are needed for the sheet fixture")
    else:
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            pdf = td / "Sheet Deck.pdf"
            want = _fixture(pdf)
            seen: list = []
            real = CS.tile_native

            def spy(cells, out_path, *a, **k):
                seen.append((Path(out_path).name, [c.get("caption") for c in cells]))
                return real(cells, out_path, *a, **k)

            CS.tile_native = spy
            try:
                ent = IP.prepare(pdf, "Sheets", "XX", td / "vis", resume=False)
            finally:
                CS.tile_native = real
            pages = ent.get("pages") or []
            rs, cs = ent.get("render_sheets"), ent.get("candidate_sheets")
            check(ent.get("mode") == "text" and len(pages) == 8, "fixture: 8-page text deck")
            check(isinstance(rs, list) and rs and isinstance(cs, list) and cs,
                  f"entry carries render_sheets ({len(rs or [])}) and candidate_sheets "
                  f"({len(cs or [])})")
            def _size(p) -> tuple:
                with Image.open(p) as im:      # closed at once: Windows cleanup needs it
                    return im.size

            renders = [_size(p["render"]) for p in pages if p.get("render")]
            if renders:
                rw = min(IP.PAGE_RENDER_THUMB_EDGE, max(w for w, _ in renders))
                rh = min(IP.PAGE_RENDER_THUMB_EDGE, max(h for _, h in renders))
                exp = _expected_sheets(len(renders), rw, rh)
                check(len(rs or []) == exp,
                      f"render sheets paginate as the budget implies ({len(rs or [])} == {exp})")
            thumbs = [_size(c["image"]) for p in pages for c in p.get("candidates") or []]
            if thumbs:
                cw = min(IP.CANDIDATE_THUMB_EDGE, max(w for w, _ in thumbs))
                ch = min(IP.CANDIDATE_THUMB_EDGE, max(h for _, h in thumbs))
                exp = _expected_sheets(len(thumbs), cw, ch)
                check(len(cs or []) == exp,
                      f"candidate sheets paginate as the budget implies ({len(cs or [])} == {exp})")
            colours = set()
            for sp in (rs or []) + (cs or []):
                with Image.open(sp) as im:
                    w, h = im.size
                    if sp in (cs or []):
                        colours |= set(im.convert("RGB").getdata())
                check(w <= CS.MONTAGE_MAX_EDGE and h <= CS.MONTAGE_MAX_EDGE
                      and w * h <= CS.MONTAGE_MAX_PIXELS,
                      f"{Path(sp).name}: {(w, h)} within the edge caps and the pixel budget")
            missing = [c for cols in want.values() for c in cols if c not in colours]
            check(not missing, f"every candidate is tiled across the deck sheets ({missing[:2]})")
            check(all(p.get("render") and Path(p["render"]).exists() for p in pages)
                  and all(Path(c["image"]).exists() for p in pages for c in p["candidates"])
                  and any(p.get("candidates_sheet") for p in pages),
                  "per-page renders, candidate thumbnails and candidates_sheets are all kept")
            check(all(n.startswith("Sheet Deck_deck_") for n in (Path(x).name for x in rs + cs)),
                  "deck sheet names avoid the {stem}_p* / {stem}_s* names vision_prep deletes")
            rcap = next((c for n, c in seen if n.endswith("_deck_renders.png")), [])
            ccap = next((c for n, c in seen if n.endswith("_deck_candidates.png")), [])
            check(rcap == [f"page_no {i}" for i in range(8)],
                  f"render tiles are captioned page_no N in page order ({rcap[:3]})")
            exp_c = [f"page_no {p} / index {k}" for p in range(8) for k in range(len(want[p]))]
            check(ccap == exp_c, f"candidate tiles are captioned page_no N / index K in order "
                                 f"({ccap[:3]})")
            va = ent.get("visual_aids") or {}
            check(va.get("render_sheets") == len(rs) and va.get("candidate_sheets") == len(cs),
                  "visual_aids counts the deck sheets")
            check(IP._entry_aids_intact(ent, pdf), "the fresh entry's aids are intact")
            Path(cs[0]).unlink()
            check(not IP._entry_aids_intact(ent, pdf),
                  "a lost deck sheet makes the cached entry unusable (it is re-prepped)")
            IMG.close_doc_cache()

            # without Pillow: both keys [] and the entry is otherwise the same shape
            saved = CS._HAS_PIL
            try:
                CS._HAS_PIL = False
                ent2 = IP.prepare(pdf, "Sheets", "XX", td / "vis2", resume=False)
            finally:
                CS._HAS_PIL = saved
            check(ent2.get("render_sheets") == [] and ent2.get("candidate_sheets") == []
                  and len(ent2.get("pages") or []) == 8 and ent2.get("mode") == "text",
                  "no tiler -> render_sheets / candidate_sheets are [] and the entry is valid")
            IMG.close_doc_cache()

    # 8. host per-message cap (fix 2.4)
    for kind in ("reader-text", "reader-raster"):
        tpl = (PR.TEMPLATE_DIR / f"{kind}.md").read_text(encoding="utf-8")
        out = PR.render(kind, {s: f"<{s}>" for s in set(_SLOT_RE.findall(tpl)) if s not in _AUTO})
        flat = re.sub(r"\s+", " ", out)
        check("DENIED for exceeding one" in flat and "still the one batch" in flat,
              f"{kind}: the batch rule tolerates a host per-message cap")
    env_keys = ("CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE", "CLAUDE_MAX_PARALLEL_TOOLS")
    saved_env = {k: os.environ.get(k) for k in env_keys}

    def _stub_ctx(work: Path) -> str:
        (work / "vision").mkdir(exist_ok=True)
        (work / "vision" / "manifest.json").write_text(json.dumps({"decks": [], "fields": []}),
                                                         encoding="utf-8")
        f = PR.write_prompts(work, [("reader-text", "d_vision", {
            "DECK_NAME": "d.pdf", "SOURCE_TYPE": "pdf", "PAGE_COUNT": 3, "COUNTRY": "XX",
            "MANIFEST_PATH": str(work / "vision" / "manifest.json"),
            "OUTPUT_PATH": str(work / "o.json")})])
        s = f[0].read_text(encoding="utf-8") if f else ""
        return s.split("## Run context", 1)[-1].split("<!--", 1)[0]

    try:
        for k in env_keys:
            os.environ.pop(k, None)
        with tempfile.TemporaryDirectory() as td:
            ctx = _stub_ctx(Path(td))
            check(ctx.strip().endswith(PR.CONTEXT_DEFAULT) and "Host fact" not in ctx,
                  "no cap in the environment -> the Run context default is unchanged")
            os.environ["CLAUDE_MAX_PARALLEL_TOOLS"] = "3"
            ctx = _stub_ctx(Path(td))
            check("at most 3 tool calls" in ctx and "consecutive messages of 3" in ctx,
                  "CLAUDE_MAX_PARALLEL_TOOLS=3 -> the stub's Run context states the cap")
            os.environ["CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE"] = "5"
            check("at most 5 tool calls" in _stub_ctx(Path(td)),
                  "the skill's own override wins over the host variable")
            os.environ["CBRE_LONGLIST_MAX_TOOLS_PER_MESSAGE"] = "lots"
            os.environ["CLAUDE_MAX_PARALLEL_TOOLS"] = "0"
            ctx = _stub_ctx(Path(td))
            check("Host fact" not in ctx, "an invalid / non-positive value is ignored, not guessed")
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print(f"\n{'PASS' if not fails else 'FAIL'} deck_sheets_test ({len(fails)} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
