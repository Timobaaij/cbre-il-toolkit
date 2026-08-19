#!/usr/bin/env python3
r"""Toolkit step 0 (deterministic): make a per-run SHADOW COPY of the live
cbre-property-longlist toolkit skill, so Kato never writes into the installed skill.

Why this exists
---------------
Kato does NOT carry its own dashboard template - it deliberately reuses whatever
template the installed toolkit ships, so every run inherits the latest CBRE chrome
(see patch_template.py). But patch_template.py has to WRITE its card/modal tweaks
into `assets/dashboard_template.html` and re-stamp `assets/VERSION`, because the
toolkit resolves both from its own skill root (`_common.py: SKILL_ROOT = <that
file>/../..`) with no path override.

Under Cowork the toolkit is unpacked fresh per session, so patching it in place is
harmless. On a durable install (`~/.claude/skills/cbre-property-longlist`) it is not:
the tweaks and the `-kato` VERSION tag persist, and every LATER non-Kato longlist run
silently inherits Kato's presentation decisions.

Shadowing removes the assumption. We copy the installed toolkit into the run's work
dir and run the whole toolkit spine from the copy. `SKILL_ROOT` is derived from
`__file__`, so the copy is fully self-contained: template, VERSION, integrity manifest,
i18n, datasets and gates all resolve inside the shadow. The install stays byte-pristine
and still supplies the newest chrome on the next run.

Not copied: `evals/`, `docs/`, `.git*`, `__pycache__` - test and history weight the
toolkit spine never reads. `vendor/` (a 24 MB read-only wheel store) is hardlinked when
the filesystem allows and copied otherwise; nothing in the pipeline writes to it.

Runtime caches are unaffected: the toolkit writes `geocode_cache.json` /
`poi_osm_cache.json` / `osrm_cache.json` / `regions_cache.json` into the WORK dir, not
the skill dir (run.py, seed_geocode.py --cache-dir). `reference/*.json` are read-only
seed caches and are copied in, so the shadow starts just as warm as the install.

Usage
-----
    python toolkit_shadow.py --source "<installed toolkit skill dir>" --work "<work dir>"
    python toolkit_shadow.py --source ... --work ... --keep      # reuse for a --resume
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

SHADOW_MARKER = ".kato-shadow.json"

# Directory names skipped wholesale. The toolkit spine (run.py -> merge/enrich/gates ->
# build_dashboard -> deliver) reads none of them.
SKIP_DIRS = {"evals", "docs", "__pycache__", ".git"}
SKIP_SUFFIXES = (".pyc", ".pyo")

# Copied by hardlink when possible: large and never written by the pipeline.
LINK_DIRS = {"vendor"}

# What must exist for a directory to be the toolkit at all.
REQUIRED = [
    os.path.join("helpers", "build_dashboard.py"),
    os.path.join("helpers", "_common.py"),
    os.path.join("assets", "dashboard_template.html"),
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def version_label(toolkit):
    p = os.path.join(toolkit, "assets", "VERSION")
    if not os.path.isfile(p):
        return "unknown"
    lines = open(p, encoding="utf-8").read().splitlines()
    return lines[0].strip() if lines else "unknown"


def copy_tree(src, dst):
    """Copy src -> dst, skipping SKIP_DIRS/SKIP_SUFFIXES and hardlinking LINK_DIRS.
    Returns (files, bytes, linked)."""
    files = nbytes = linked = 0
    for root, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(root, src)
        rel = "" if rel == "." else rel
        top = rel.split(os.sep)[0] if rel else ""
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        target_dir = os.path.join(dst, rel) if rel else dst
        os.makedirs(target_dir, exist_ok=True)
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIXES):
                continue
            s = os.path.join(root, name)
            d = os.path.join(target_dir, name)
            if top in LINK_DIRS:
                try:
                    os.link(s, d)          # same volume: free, and vendor/ is read-only
                    linked += 1
                    files += 1
                    nbytes += os.path.getsize(s)
                    continue
                except OSError:
                    pass                   # cross-volume or no link support -> copy
            shutil.copy2(s, d)
            files += 1
            nbytes += os.path.getsize(s)
    return files, nbytes, linked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True,
                    help="the INSTALLED cbre-property-longlist skill dir to shadow")
    ap.add_argument("--work", help="Kato work dir; the shadow lands in <work>/toolkit")
    ap.add_argument("--dest", help="explicit shadow path (overrides --work)")
    ap.add_argument("--keep", action="store_true",
                    help="reuse an existing shadow instead of rebuilding it (for --resume)")
    args = ap.parse_args()

    src = os.path.abspath(args.source)
    for rel in REQUIRED:
        if not os.path.isfile(os.path.join(src, rel)):
            sys.exit("ERROR: %s is not a cbre-property-longlist toolkit (missing %s)" % (src, rel))

    if args.dest:
        dst = os.path.abspath(args.dest)
    elif args.work:
        dst = os.path.join(os.path.abspath(args.work), "toolkit")
    else:
        sys.exit("ERROR: pass --work (shadow -> <work>/toolkit) or --dest")

    if os.path.normcase(dst) == os.path.normcase(src):
        sys.exit("ERROR: --dest is the source itself; the shadow must be a separate directory")

    if os.path.isfile(os.path.join(src, SHADOW_MARKER)):
        print("note: --source is itself a shadow (%s); copying it anyway" % src, file=sys.stderr)

    src_tpl = os.path.join(src, "assets", "dashboard_template.html")
    src_sha = sha256_file(src_tpl)
    src_ver = version_label(src)

    if src_ver.endswith("-kato"):
        print("WARNING: the INSTALLED toolkit at %s is already Kato-patched (VERSION %r). "
              "A previous run patched it in place. Reinstall or update the toolkit to restore "
              "pristine CBRE chrome; shadowing from here just carries the old patch forward."
              % (src, src_ver), file=sys.stderr)

    if os.path.exists(dst):
        if args.keep:
            marker = os.path.join(dst, SHADOW_MARKER)
            if not os.path.isfile(marker):
                sys.exit("ERROR: --keep given but %s carries no %s; refusing to reuse a "
                         "directory this helper did not create" % (dst, SHADOW_MARKER))
            info = json.load(open(marker, encoding="utf-8"))
            print("toolkit_shadow: reusing %s (shadow of %s)" % (dst, info.get("source_version")))
            print(dst)
            return
        if not os.path.isfile(os.path.join(dst, SHADOW_MARKER)):
            sys.exit("ERROR: %s exists and is not a Kato shadow (no %s). Refusing to delete it. "
                     "Move it aside or pass --dest." % (dst, SHADOW_MARKER))
        shutil.rmtree(dst)

    files, nbytes, linked = copy_tree(src, dst)

    # Byte-exactness of the one file everything downstream hashes.
    dst_sha = sha256_file(os.path.join(dst, "assets", "dashboard_template.html"))
    if dst_sha != src_sha:
        sys.exit("ERROR: template copy is not byte-identical (%s != %s)"
                 % (dst_sha[:12], src_sha[:12]))

    json.dump({
        "source": src,
        "source_version": src_ver,
        "source_template_sha256": src_sha,
        "files": files,
        "bytes": nbytes,
        "hardlinked": linked,
        "note": "Per-run shadow of the installed cbre-property-longlist toolkit. "
                "Kato patches THIS copy; the install stays pristine. Safe to delete.",
    }, open(os.path.join(dst, SHADOW_MARKER), "w", encoding="utf-8"), indent=2)

    print("toolkit_shadow: %s -> %s" % (src_ver, dst))
    print("  %d files, %.1f MB (%d hardlinked), template SHA %s (install untouched)"
          % (files, nbytes / 1048576.0, linked, src_sha[:16]))
    print(dst)


if __name__ == "__main__":
    main()
