#!/usr/bin/env python3
"""Stage 1-alt - rebuild the Kato tree from a browser-captured bundle (NO network, NO Playwright).

WHY THIS EXISTS: kato_fetch.py needs Playwright to log in and a live socket to Kato. Claude Cowork has
neither - it is a fully sandboxed environment whose only egress is WebSearch/WebFetch, so the Kato API
is unreachable no matter what credentials you hold. The Chrome extension in ../extension does all the
network work inside a browser that is already signed in, and emits one bundle. This helper turns that
bundle into EXACTLY the tree kato_fetch.py would have written, so stages 2-7 of the skill run unchanged.

EQUIVALENCE IS STRUCTURAL, NOT MAINTAINED BY HAND: every naming and derivation decision is delegated to
the same common.py functions kato_fetch.py calls (derive, sanitize, property_folder, ensure_image_limits).
Nothing about Kato's JSON shape is re-interpreted here, and nothing about it is interpreted in the
extension either - the extension collects media by HOST and records where it found each URL, then this
helper asks derive() which URLs actually matter. A new Kato media field therefore needs a change in
common.py only; the bytes are already in the bundle.

Usage:
  python kato_ingest.py --config run.yaml --bundle kato_bundle_1708520_2026-08-17.zip
  python kato_ingest.py --config run.yaml --bundle part1.zip --bundle part2.zip [--refresh]
"""
import argparse
import os
import posixpath
import sys
import zipfile
from urllib.parse import urlparse


def _load_common(explicit=None):
    """common.py lives in the skill's helpers dir. Support running from anywhere."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        explicit,
        here,
        os.path.join(here, os.pardir, os.pardir, "helpers"),
        os.path.join(os.path.expanduser("~"), ".claude", "skills", "Kato-Longlist", "helpers"),
    ]
    for c in candidates:
        if c and os.path.exists(os.path.join(c, "common.py")):
            sys.path.insert(0, os.path.abspath(c))
            return os.path.abspath(c)
    raise SystemExit(
        "Could not find common.py. Pass --helpers <path to Kato-Longlist/helpers>."
    )


# ---------------------------------------------------------------- bundle reading


class Bundle:
    """One or more zip parts presented as a single name -> bytes namespace."""

    def __init__(self, paths):
        self.zips = []
        self.where = {}          # arcname -> zipfile
        self.parts = []          # {index, final, path}
        for p in paths:
            if not os.path.exists(p):
                raise SystemExit(f"Bundle not found: {p}")
            try:
                z = zipfile.ZipFile(p)
            except zipfile.BadZipFile as e:
                raise SystemExit(f"Not a readable zip (truncated upload?): {p} - {e}")
            self.zips.append(z)
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                self.where.setdefault(name, z)
            part = self._maybe_json(z, "part.json")
            if part is None:
                raise SystemExit(
                    f"{os.path.basename(p)} has no part.json, so it was not written by the capture "
                    f"extension (or is from an incompatible version)."
                )
            self.parts.append({"index": part.get("index"), "final": bool(part.get("final")),
                               "path": p, "requirement_id": part.get("requirement_id")})

        self.parts.sort(key=lambda x: (x["index"] is None, x["index"]))
        self._validate_parts()

    @staticmethod
    def _maybe_json(z, name):
        import json
        try:
            with z.open(name) as fh:
                return json.load(fh)
        except KeyError:
            return None

    def _validate_parts(self):
        idx = [p["index"] for p in self.parts]
        if any(i is None for i in idx):
            raise SystemExit("A part.json is missing its index; cannot establish bundle order.")
        if len(set(idx)) != len(idx):
            raise SystemExit(f"Duplicate bundle parts supplied: indices {idx}.")
        expected = list(range(1, len(idx) + 1))
        if idx != expected:
            raise SystemExit(
                f"Bundle parts are not contiguous from 1: got {idx}, expected {expected}. "
                f"A part is missing, so the capture is incomplete - supply every part with --bundle."
            )
        finals = [p for p in self.parts if p["final"]]
        if len(finals) != 1:
            raise SystemExit(
                f"Expected exactly one final part, found {len(finals)}. Without the final part the "
                f"manifest and media index are missing and the capture cannot be trusted."
            )
        if finals[0]["index"] != idx[-1]:
            raise SystemExit("The final part is not the last part; the parts supplied do not belong together.")

    def json(self, name, default=None, required=False):
        import json
        z = self.where.get(name)
        if z is None:
            if required:
                raise SystemExit(f"Bundle is missing required entry: {name}")
            return default
        with z.open(name) as fh:
            return json.load(fh)

    def read(self, name):
        z = self.where.get(name)
        if z is None:
            return None
        with z.open(name) as fh:
            return fh.read()

    def close(self):
        for z in self.zips:
            try:
                z.close()
            except Exception:
                pass


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--bundle", action="append", required=True,
                    help="bundle zip; repeat once per part for a split capture")
    ap.add_argument("--refresh", action="store_true",
                    help="re-derive and re-extract everything, overwriting existing files")
    ap.add_argument("--helpers", default=None, help="path to the Kato-Longlist helpers dir")
    args = ap.parse_args()

    _load_common(args.helpers)
    from common import (load_config, requirement_id, sanitize, property_folder,
                        read_json, write_json, derive)

    cfg = load_config(args.config)
    work = cfg["work_dir"]
    reqid = requirement_id(cfg["kato_url"])
    props_dir = os.path.join(work, "properties")
    os.makedirs(props_dir, exist_ok=True)

    bundle = Bundle(args.bundle)
    manifest = bundle.json("manifest.json", required=True)
    media_index = bundle.json("media_index.json", default={}) or {}
    listing = bundle.json("list.json", required=True)

    # ---- the guard that matters most: never build a longlist from the wrong requirement.
    b_req = manifest.get("requirement_id")
    if int(b_req) != int(reqid):
        raise SystemExit(
            f"REFUSING TO INGEST: this bundle is for requirement {b_req}, but run.yaml's kato_url is "
            f"requirement {reqid}. Ingesting it would build a client longlist for the wrong "
            f"requirement. Fix run.yaml, or capture the right requirement."
        )
    if int(manifest.get("schema_version", 0)) != 1:
        raise SystemExit(f"Unsupported bundle schema_version {manifest.get('schema_version')!r}; expected 1.")

    print(f"Requirement {reqid} | work_dir={work}", flush=True)
    print(f"Bundle: {len(bundle.parts)} part(s), captured {manifest.get('captured_at')} "
          f"by extension v{manifest.get('extension_version')} against {manifest.get('api_base')}", flush=True)
    if not manifest.get("complete", True):
        c = manifest.get("counts", {}) or {}
        print("  WARNING: the capture reported failures. Missing items are recorded below and will "
              "reach the Gaps Report rather than being silently absent.", flush=True)
        print(f"  raw {c.get('raw_ok')}/{c.get('raw_attempted')}  media {c.get('media_ok')}/{c.get('media_attempted')}",
              flush=True)
    v = manifest.get("validation") or {}
    for note in (v.get("notes") or []):
        print(f"  API SHAPE NOTE: {note}", flush=True)

    # ---- same selection and ordering as kato_fetch.py:125-126
    data = (listing or {}).get("data") or []
    longlist = [m for m in data if m.get("status") == 1]
    longlist.sort(key=lambda m: (m.get("group_position") if m.get("group_position") is not None else 1e9))
    print(f"Longlist matches (status==1): {len(longlist)} of {len(data)} total", flush=True)

    # ---- folder-name stability across re-captures, exactly as kato_fetch.py:130-131
    prev = read_json(os.path.join(props_dir, "_index.json"), {}) or {}
    prev_folder = {p["match_id"]: p["folder"] for p in prev.get("properties", [])}

    # PIL is only the safety net; imgix already guarantees the caps, so absence is survivable.
    try:
        from common import ensure_image_limits
        _ = ensure_image_limits
        have_pil = True
        try:
            import PIL  # noqa: F401
        except Exception:
            have_pil = False
    except Exception:
        have_pil = False
    if not have_pil:
        print("  NOTE: PIL unavailable - skipping the image size safety net. Images from the bundle "
              "are already capped at 1200px/<500KB by imgix, so this is normally a no-op.", flush=True)

    max_px, quality = cfg["image_max_px"], cfg["image_quality"]
    index, report = [], {"source": "bundle", "raw_fetched": 0, "raw_cached": 0,
                         "bundle_captured_at": manifest.get("captured_at"),
                         "bundle_parts": len(bundle.parts),
                         "bundle_complete": bool(manifest.get("complete", True)),
                         "media": {"ok": 0, "skip": 0, "fail": 0}, "media_failures": [],
                         "skipped_matches": []}

    for i, li in enumerate(longlist, 1):
        mid = li["id"]
        raw = bundle.json(f"raw/{mid}.json")
        if raw is None:
            # Its detail fetch failed during capture. Skip it wholesale rather than emit a
            # half-built property that would present as complete.
            report["skipped_matches"].append(
                {"match_id": mid, "name": li.get("address_name"),
                 "reason": f"no raw/{mid}.json in bundle (detail fetch failed during capture)"})
            print(f"  [{i:02d}/{len(longlist)}] SKIPPED match {mid} - missing detail in bundle", flush=True)
            continue

        rec0 = derive(raw, li)
        name = rec0["address"].get("name") or li.get("address_name") or f"match-{mid}"
        folder = prev_folder.get(mid) if not args.refresh else None
        if not folder:
            folder = property_folder(i, name, rec0["address"].get("postcode") or "")
        pdir = os.path.join(props_dir, folder)
        os.makedirs(pdir, exist_ok=True)

        raw_path = os.path.join(pdir, "_raw.json")
        if args.refresh or not os.path.exists(raw_path):
            write_json(raw_path, raw)
            report["raw_fetched"] += 1
        else:
            report["raw_cached"] += 1

        rec = derive(raw, li)
        write_json(os.path.join(pdir, "_derived.json"), rec)

        # ---- media: derive() decides WHAT is wanted; media_index says WHERE the bytes are.
        mi = media_index.get(str(mid)) or media_index.get(mid) or []
        by_url = {e.get("url"): e for e in mi if e.get("url")}

        def place(url, dest, label):
            entry = by_url.get(url)
            if entry is None:
                report["media"]["fail"] += 1
                report["media_failures"].append({"url": url, "dest": dest,
                                                 "error": "not present in bundle (excluded at capture, or failed)"})
                return
            if (not args.refresh) and os.path.exists(dest) and os.path.getsize(dest) > 0:
                report["media"]["skip"] += 1
                return
            blob = bundle.read(entry["file"])
            if blob is None:
                report["media"]["fail"] += 1
                report["media_failures"].append({"url": url, "dest": dest,
                                                 "error": f"media_index points at {entry['file']} which is not in any part"})
                return
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(blob)
            report["media"]["ok"] += 1

        for d in rec["documents"]:
            fn = sanitize(d.get("name") or posixpath.basename(urlparse(d["url"]).path)) or "file"
            place(d["url"], os.path.join(pdir, "media", fn), "doc")

        for j, im in enumerate(rec["images"], 1):
            nm = sanitize(im.get("name") or f"image-{j}")
            base, ext = os.path.splitext(nm)
            if not ext:
                ext = ".jpg"
            dest = os.path.join(pdir, "media", "images", f"{j:02d} - {base}{ext}")
            place(im["url"], dest, "image")
            if have_pil and os.path.exists(dest):
                try:
                    ensure_image_limits(dest, max_px, max_bytes=500 * 1024, quality=quality)
                except Exception as e:
                    print(f"    (image safety net failed on {dest}: {e})", flush=True)

        index.append({"order": i, "match_id": mid, "folder": folder,
                      "name": rec["address"].get("name"), "postcode": rec["address"].get("postcode"),
                      "for_sale": rec["for_sale"], "to_let": rec["to_let"],
                      "group_position": li.get("group_position")})
        print(f"  [{i:02d}/{len(longlist)}] {folder}  docs={len(rec['documents'])} imgs={len(rec['images'])}", flush=True)

    write_json(os.path.join(props_dir, "_index.json"),
               {"requirement_id": reqid, "count": len(index), "properties": index})

    # Fold the capture's own failures in, so the Gaps Report tells the whole truth.
    for f in (bundle.json("errors.json", default=[]) or []):
        report["media_failures"].append(f)
    report["properties"] = len(index)
    write_json(os.path.join(props_dir, "_fetch_report.json"), report)

    dl = report["media"]
    print(f"DONE. properties={len(index)} raw(written={report['raw_fetched']},kept={report['raw_cached']}) "
          f"media ok={dl['ok']} skip={dl['skip']} fail={dl['fail']} "
          f"skipped_matches={len(report['skipped_matches'])}", flush=True)
    if dl["fail"] or report["skipped_matches"]:
        print("  (failures are in properties/_fetch_report.json)", flush=True)
    bundle.close()


if __name__ == "__main__":
    main()
