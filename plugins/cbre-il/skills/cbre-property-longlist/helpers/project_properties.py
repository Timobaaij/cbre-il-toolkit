#!/usr/bin/env python3
"""project_properties.py - a READ-ONLY per-property view of the merged dataset.

`canonical.json` is one file, ~11 MB of which is base64 image data, so the thing a broker or
a reviewer actually wants to look at - one option, its values, its photos, where each figure
came from - is not readable in it. Everything downstream of the merge is per-property work:
checking a hero is the right building, chasing a `tbd`, seeing why a rent looks wrong. This
writes that view.

  work/properties/
    01-indurent-park-chippenham-unit-c112/
      property.json     the record, readable, media replaced by filenames
      media/            hero.jpg, gallery-02.jpg ..., plan.jpg - real files, openable
      sources.csv       this property's Source Ledger rows and nothing else
      notes.md          its unknowns, its source conflicts, its repairs, its repair key

DERIVED, NEVER AUTHORITATIVE. It is rebuilt from `canonical.json` on every run and nothing
reads it back. Editing a file here changes nothing: corrections go in `work/repairs.json`,
which is applied before the gates and writes its own ledger rows. That asymmetry is the
design, not an omission - two writable copies of one dataset drift, and the drift is silent.

`notes.md` prints the property's `repair key` for exactly this reason: it is the string a
repair entry needs, so the view that shows you the problem also hands you what you need to
fix it.

CLI:  python project_properties.py --work <dir> [--canonical <path>] [--no-media]
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import match as _match
except Exception:                                    # pragma: no cover
    _match = None

MEDIA_FIELDS = ("photo", "plan")
_SLUG_RX = re.compile(r"[^a-z0-9]+")
_EXT = {"/9j/": "jpg", "iVBOR": "png", "R0lGO": "gif", "UklGR": "webp"}


def slug(text: str, cap: int = 60) -> str:
    s = _SLUG_RX.sub("-", str(text or "").strip().lower()).strip("-")
    return (s[:cap].rstrip("-") or "property")


def repair_key(rec: dict) -> str:
    if _match is not None:
        try:
            return _match.match_key(rec)
        except Exception:
            pass
    return "|".join(str(rec.get(k, "") or "").strip().lower()
                    for k in ("city", "developer", "park"))


def _decode(uri: str):
    """(bytes, ext) from a data URI, or (None, None). Never raises on a malformed value."""
    if not isinstance(uri, str) or "base64," not in uri:
        return None, None
    head, _, b64 = uri.partition("base64,")
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None, None
    m = re.search(r"image/([a-z0-9.+-]+)", head, re.I)
    ext = (m.group(1).lower() if m else "")
    if ext in ("jpeg", "jpg"):
        ext = "jpg"
    if not ext or ext not in ("jpg", "png", "gif", "webp", "svg+xml"):
        ext = _EXT.get(b64[:5], "img")
    return raw, ("svg" if ext == "svg+xml" else ext)


def _is_placeholder(raw: bytes) -> bool:
    return bool(raw) and len(raw) < 12_000


def write_property(prop: dict, out_dir: Path, ledger_rows: list, conflicts: list,
                   repairs: list, media: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mdir = out_dir / "media"
    if mdir.exists():
        shutil.rmtree(mdir, ignore_errors=True)

    view = {k: v for k, v in prop.items() if k not in ("photo", "plan", "gallery")}
    written = {}
    if media:
        mdir.mkdir(parents=True, exist_ok=True)
        raw, ext = _decode(prop.get("photo"))
        if raw:
            name = f"hero.{ext}"
            (mdir / name).write_bytes(raw)
            written["photo"] = name + (" (placeholder)" if _is_placeholder(raw) else "")
        raw, ext = _decode(prop.get("plan"))
        if raw:
            (mdir / f"plan.{ext}").write_bytes(raw)
            written["plan"] = f"plan.{ext}"
        gal = prop.get("gallery") or []
        names = []
        for i, uri in enumerate(gal, start=1):
            raw, ext = _decode(uri)
            if not raw:
                continue
            name = f"gallery-{i:02d}.{ext}"
            (mdir / name).write_bytes(raw)
            names.append(name)
        if names:
            written["gallery"] = names
    view["__media"] = written or {"note": "no image data on this property"}
    view["__repair_key"] = repair_key(prop)
    (out_dir / "property.json").write_text(
        json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    cols = ["field", "value", "source_file", "source_locator", "source_type",
            "record_type", "extractor", "confidence", "conflict_note", "verified"]
    with open(out_dir / "sources.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in ledger_rows:
            w.writerow(r)

    tbd = sorted(k for k, v in prop.items()
                 if isinstance(v, str) and v.strip().lower() in ("tbd", "tbc", "—", "-"))
    lines = [f"# {prop.get('park') or 'Property'}  (id {prop.get('id')})", ""]
    lines += [f"- **repair key**: `{view['__repair_key']}`",
              f"- **city**: {prop.get('city') or 'tbd'}    **region**: {prop.get('region') or 'tbd'}",
              ""]
    lines += ["## To correct anything here", "",
              "Edit `work/repairs.json`, not this folder - nothing reads these files back.", "",
              "```json", json.dumps([{
                  "id": "rp-001",
                  "property": {"key": view["__repair_key"], "id": prop.get("id")},
                  "expect": {"city": prop.get("city")},
                  "set": {"<field>": "<value>"},
                  "why": "why this is right, in one sentence",
                  "verified_by": "you@cbre.com",
              }], indent=2), "```", ""]
    lines += [f"## Unknown ({len(tbd)})", ""]
    lines += ([f"- `{k}`" for k in tbd] or ["- none"]) + [""]
    lines += [f"## Source conflicts ({len(conflicts)})", ""]
    lines += ([f"- {c}" for c in conflicts] or ["- none"]) + [""]
    lines += [f"## Repairs applied ({len(repairs)})", ""]
    lines += ([f"- `{r['id']}` {', '.join(r.get('changed', {}))} - {r.get('why','')}"
               for r in repairs] or ["- none"]) + [""]
    (out_dir / "notes.md").write_text("\n".join(lines), encoding="utf-8")
    return {"dir": out_dir.name, "media": written, "tbd": len(tbd)}


def build(work: Path, canonical_path: Path | None = None, media: bool = True) -> dict:
    work = Path(work)
    cpath = Path(canonical_path) if canonical_path else work / "canonical.json"
    data = json.loads(cpath.read_text(encoding="utf-8-sig"))
    props = data.get("properties") or []

    by_id: dict = {}
    lpath = work / "source_ledger.csv"
    if lpath.exists():
        with open(lpath, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                by_id.setdefault(str(row.get("property_id", "")).strip(), []).append(row)

    conf_by_id: dict = {}
    for c in (data.get("meta", {}).get("conflicts") or []):
        m = re.match(r"\s*id\s+(\d+)\s+(.*)", str(c))
        if m:
            conf_by_id.setdefault(m.group(1), []).append(m.group(2))

    rep_by_id: dict = {}
    rpath = work / "repairs_report.json"
    if rpath.exists():
        try:
            for a in (json.loads(rpath.read_text(encoding="utf-8-sig")).get("applied") or []):
                rep_by_id.setdefault(str(a.get("property_id")), []).append(a)
        except Exception:
            pass

    root = work / "properties"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    made = []
    for p in props:
        pid = str(p.get("id"))
        name = f"{pid.zfill(2)}-{slug(p.get('park') or p.get('city') or 'property')}"
        made.append(write_property(p, root / name, by_id.get(pid, []),
                                   conf_by_id.get(pid, []), rep_by_id.get(pid, []), media))
    (root / "index.json").write_text(
        json.dumps({"count": len(made), "properties": made}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"count": len(made), "root": str(root)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True)
    ap.add_argument("--canonical")
    ap.add_argument("--no-media", action="store_true")
    a = ap.parse_args()
    r = build(Path(a.work), Path(a.canonical) if a.canonical else None, media=not a.no_media)
    print(f"OK per-property projection: {r['count']} property folder(s) -> {r['root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
