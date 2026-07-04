#!/usr/bin/env python3
"""intake.py - Stage 0. Discover inputs and scaffold project.yaml.

Scans a folder RECURSIVELY (hidden/underscore dirs skipped, scanned subfolders
named in the output) for the five input types, infers a city/region cluster per
brochure from its filename (e.g. "Normal Options - Pilsen.pdf" -> Pilsen, noise
suffixes like "- FINAL"/"- v2" dropped), keeps EVERY brochure per cluster
(pdfs/pptxs lists - never a silent overwrite), looks up the country from the
POI library's city->country index, writes inventory.json, and (if absent)
scaffolds a project.yaml pre-filled from what was found. The orchestrator then
confirms the config with the broker.

CLI:
  python intake.py <folder> [--out-dir work/] [--client Normal]
  (aliases: --folder for the positional folder, --work for --out-dir, to match run.py)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

# region label = the last SPACED-dash segment of the stem, after dropping noise
# suffixes ("... - Pilsen - FINAL.pdf" -> Pilsen). Spaced separators only, so a
# hyphenated name ("CTPark Brno-South") is never split; dots ("St. Polten") and
# em-dashes are fine. The old single-regex approach clustered "... - FINAL.pdf"
# as region "FINAL" and missed dotted cities entirely.
_SEP = re.compile(r"\s+[-–—]\s+")
_NOISE = re.compile(r"^(?:final|draft|copy|copy\s*\(\d+\)|updated?|latest|new|clean|shared|issued|"
                    r"v\d+|rev\.?\s*\d+|r\d+|\d{6,8}|\(\d+\))$", re.I)


def _poi_lib() -> dict:
    f = C.ASSETS / "poi_library.json"
    try:  # a corrupt/truncated library is a degraded convenience, never a crash
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"city_country": {}}
    except Exception:
        return {"city_country": {}}


def infer_cluster(stem_file: str, city_country: dict) -> tuple[str, str, str]:
    """Best-effort (region_label, country, confidence) from a brochure filename. The
    region is the text after a ' - ' (e.g. 'Normal Options - Pilsen.pdf' -> 'Pilsen'),
    else the whole stem - it is only a cluster LABEL; the real city is read from the
    brochure at extraction. country comes from the POI library's city->country
    index, which is a CEE-seeded CONVENIENCE: a miss returns '' (-> '??') for the
    broker to confirm. Coordinates are resolved globally by --geocode regardless,
    so an unknown country here never blocks the map.

    confidence is a PURELY ADDITIVE structural signal (it never changes the chosen
    region) so the Stage-0 orchestrator can judge only the ambiguous tail:
      'high' = a clean spaced-dash split, OR the unspaced-dash tail was a known city;
      'low'  = the whole-stem fallback fired (no spaced dash AND the unspaced-dash
               tail was NOT a known city - the 'Options-Oporto' case)."""
    stem = Path(stem_file).stem
    parts = [s.strip() for s in _SEP.split(stem) if s.strip()]
    had_sep = len(parts) > 1
    while len(parts) > 1 and _NOISE.fullmatch(parts[-1]):
        parts.pop()  # drop trailing FINAL / draft / v2 / dates - they are not regions
    if len(parts) > 1:
        region = parts[-1]
        confidence = "high"  # a clean spaced-dash split produced a real tail
    elif had_sep and parts:
        # a single real segment survived after noise-stripping ('City - FINAL' -> 'City'):
        # use it, not the whole stem which would leak the ' - FINAL' noise (audit S0-41)
        region = parts[0]
        confidence = "high"
    else:
        region = stem
        confidence = "low"   # the whole-stem fallback fired
        # unspaced-dash fallback ONLY when the tail is a known city ("Options-Madrid"
        # -> Madrid) - never split a hyphenated park name like "Brno-South" blindly
        tail = re.split(r"[-–—]", stem)[-1].strip()
        if tail and tail.lower() != stem.lower() and tail.lower() in city_country:
            region = tail
            confidence = "high"  # the tail is a known city -> a confident split
    country = city_country.get(region.lower(), "")
    return region, country, confidence


def _brochure_input_hash(rels) -> str:
    """sha1[:8] over the SORTED brochure relpaths (the cluster INPUT) - the same
    recipe as the tracker map cache (run.py _tracker_struct_hash). A changed
    brochure set changes the hash, which invalidates a stale intake_clusters.json
    so the next pass re-clusters rather than re-applying stale labels."""
    payload = json.dumps(sorted(rels), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _verified_cluster_overrides(cache, input_hash: str, stems: set) -> dict:
    """STRUCTURAL CACHE VERIFIER. Returns a {stem -> (region, country)} override map
    from work/intake_clusters.json ONLY when EVERY guard holds; ANY failure discards
    the WHOLE cache (returns {}) and the caller falls back to infer_cluster verbatim
    - never a traceback. Guards: the cache parses to a dict; its input_hash matches
    the current brochure set; and each label's stem is a real discovered file with a
    non-empty region that is not a _NOISE token."""
    if not isinstance(cache, dict):
        return {}
    if cache.get("input_hash") != input_hash:  # a changed brochure set -> stale -> drop
        return {}
    labels = cache.get("labels")
    if not isinstance(labels, list):
        return {}
    overrides: dict = {}
    for lab in labels:
        if not isinstance(lab, dict):
            return {}  # malformed entry -> distrust the whole cache
        stem = lab.get("stem")
        region = (lab.get("region") or "").strip()
        if not isinstance(stem, str) or stem not in stems:
            return {}  # a label for a file that does not exist -> distrust the cache
        if not region or _NOISE.fullmatch(region):
            return {}  # an empty / noise-token region -> distrust the cache
        overrides[stem] = (region, (lab.get("country") or "").strip())
    return overrides


# a prior RUN's deliverables left in the inputs folder must never be re-ingested as
# inputs (a Source Ledger was once read as a questionnaire -> phantom requirements).
# Low-skill users routinely re-run in the same folder. The defensive twin is the
# ledger-schema refusal in extract_xlsx (catches a renamed ledger by its columns).
_OWN_OUTPUT = re.compile(r"_Source_Ledger\.(?:xlsx|csv)$|_Gaps_Report\.md$|_Longlist\.(?:xlsx|csv)$|^CBRE_Property_Dashboard_.*\.html$", re.I)

# INTAKE-036: the dedup hash reads the whole file into memory; a pathological huge file
# (a mis-dropped video, a runaway export) can raise MemoryError - which is NOT an OSError
# and so escaped the read guard, crashing the whole intake run. Files over this cap skip the
# byte-identical-dedup check (their bytes are never read) but are still discovered/classified
# normally. 512 MB is far above any real brochure/tracker/image, well under a memory-exhaustion
# level. A >cap exact-duplicate pair simply won't be collapsed - acceptable for a pathological input.
_DEDUP_MAX_BYTES = 512 * 1024 * 1024  # 512 MB


def _is_own_output(rel: str) -> bool:
    p = Path(rel)
    return ("deliverables" in [s.lower() for s in p.parts[:-1]]
            or bool(_OWN_OUTPUT.search(p.name)))


def discover(folder: Path, cluster_cache=None) -> dict:
    """Recursive discovery (hidden/underscore dirs skipped). EVERY brochure is kept:
    a cluster's brochures are LISTS (`pdfs`/`pptxs`) - the old one-slot-per-type
    layout silently overwrote "Options - Madrid.pdf" with "New stock - Madrid.pdf"
    and whole input files vanished with no warning. The legacy singular keys
    (`pdf`/`pptx` = first of each list) are still written for compatibility. Paths
    are stored RELATIVE to the inputs folder, so subfolder files resolve.

    cluster_cache (optional, the parsed work/intake_clusters.json) is the Stage-0
    orchestrator's LLM-refined filename->region labels. It OVERRIDES infer_cluster's
    region for the named stems ONLY when its input_hash matches the current brochure
    set and every label passes _verified_cluster_overrides; ANY failure (or absence)
    falls back to infer_cluster VERBATIM, so an offline / no-LLM run is unchanged."""
    lib = _poi_lib()
    cc = lib.get("city_country", {})
    inv = {"folder": str(folder), "clusters": {}, "xlsx": [], "images": [],
           "emails": [], "present_types": [], "subfolders": [], "skipped_outputs": [],
           "skipped_duplicates": [], "skipped_hash_oversize": []}
    files = sorted((p for p in folder.rglob("*") if p.is_file()
                    and not any(part.startswith((".", "_"))
                                for part in p.relative_to(folder).parts)),
                   key=lambda p: p.relative_to(folder).as_posix())
    subdirs: set[str] = set()
    seen_hashes: dict[str, str] = {}  # sha256 -> the rel path we kept (INTAKE-001)
    # PASS 1: collect the kept brochure files (post own-output + INTAKE-001 dedup) so the
    # input_hash + the cache verifier key against the EXACT cluster input, then apply the
    # verified LLM overrides; non-brochure inputs are classified in the same loop.
    kept_brochures: list = []  # (rel, ext, stem) for each kept pdf/pptx, in sorted order
    for p in files:
        relparts = p.relative_to(folder).parts
        rel = "/".join(relparts)
        if _is_own_output(rel):
            inv["skipped_outputs"].append(rel)  # a prior run's own deliverable - never an input
            continue
        # INTAKE-001: a byte-identical duplicate (an accidental "X copy.pdf") is extracted
        # only ONCE - keep the first in sorted order (deterministic), record the skip so the
        # broker sees it, and avoid a wasted extraction + a phantom duplicate card. A read
        # error never drops a file (it is treated as unique).
        # INTAKE-036: size-prefilter the whole-file dedup read so a pathological huge file
        # (multi-GB) is never slurped into memory, and backstop MemoryError/OverflowError
        # (NOT an OSError) so a bad file is skipped-from-dedup, never a crash of the whole run.
        try:
            oversize = p.stat().st_size > _DEDUP_MAX_BYTES
        except OSError:
            oversize = False
        if oversize:
            inv["skipped_hash_oversize"].append(rel)  # too big to hash; still discovered below
            digest = ""
        else:
            try:
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
            except (OSError, MemoryError, OverflowError):
                digest = ""
        if digest:
            if digest in seen_hashes:
                inv["skipped_duplicates"].append({"file": rel, "duplicate_of": seen_hashes[digest]})
                continue
            seen_hashes[digest] = rel
        if len(relparts) > 1:
            subdirs.add(relparts[0])
        ext = p.suffix.lower()
        if ext in (".pdf", ".pptx"):
            kept_brochures.append((rel, ext, p.stem))
        elif ext in (".xlsx", ".xlsm", ".csv"):
            inv["xlsx"].append(rel)
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
            inv["images"].append(rel)
        elif ext in (".msg", ".eml"):
            inv["emails"].append(rel)
    # PASS 2: cluster the kept brochures. The cluster INPUT is the sorted brochure
    # relpaths; the verified LLM cache (if any) overrides infer_cluster per stem.
    brochure_rels = [rel for rel, _ext, _stem in kept_brochures]
    stems = {stem for _rel, _ext, stem in kept_brochures}
    overrides = _verified_cluster_overrides(cluster_cache, _brochure_input_hash(brochure_rels), stems)
    for rel, ext, stem in kept_brochures:
        region, country, confidence = infer_cluster(Path(rel).name, cc)
        if stem in overrides:  # the broker-confirmed, input-hashed LLM label wins
            region, ov_country = overrides[stem]
            country = ov_country or cc.get(region.lower(), "")
            confidence = "high"  # an applied, verified label is no longer ambiguous
        cl = inv["clusters"].setdefault(region, {"region": region, "country": country,
                                                 "pdfs": [], "pptxs": [],
                                                 "confidence": "high", "stems": []})
        # the cluster is 'low' if ANY contributing brochure was ambiguous (so the
        # orchestrator judges it); an applied override / a clean split keeps it 'high'.
        if confidence == "low":
            cl["confidence"] = "low"
        if stem not in cl["stems"]:
            cl["stems"].append(stem)
        key = ext.lstrip(".")
        cl[key + "s"].append(rel)
        cl[key] = cl[key + "s"][0]  # legacy singular key = first brochure
    inv["subfolders"] = sorted(subdirs)
    types = []
    if any(c.get("pdfs") for c in inv["clusters"].values()):
        types.append("pdf")
    if any(c.get("pptxs") for c in inv["clusters"].values()):
        types.append("pptx")
    for t, key in (("xlsx", "xlsx"), ("image", "images"), ("email", "emails")):
        if inv[key]:
            types.append(t)
    inv["present_types"] = types
    return inv


def scaffold_yaml(inv: dict, client: str, inputs_folder: str = ".") -> str:
    import yaml
    countries = sorted({c.get("country") for c in inv["clusters"].values() if c.get("country")})
    # emit the cluster keys via safe_dump: a region label derived from a filename can
    # legally contain ':' or start with '['/'{' (e.g. 'Unit 5: Phase 2'), which as a
    # raw 'key: value' line is INVALID YAML and crashed load_yaml before any stage ran.
    _clusters = {r: (c.get("country") or "??") for r, c in inv["clusters"].items()}
    _cl = yaml.safe_dump(_clusters, default_flow_style=False, allow_unicode=True,
                         sort_keys=False).rstrip("\n") if _clusters else "{}"
    clusters_block = "\n".join("    " + ln for ln in _cl.splitlines())
    return f"""# project.yaml - one per client project. Confirm before running.
client:
  name: {client}
  confidential: true
market:
  title_html: "logistics <em>options</em> for your next facility."
  eyebrow: ""                    # market descriptor e.g. "Spain" or "Madrid & Catalonia"; blank renders "Property Shortlist"
  region_label: ""
  countries: {json.dumps(countries)}
  lede: ""                       # optional; a default is generated if blank
output:
  filename: "CBRE_Property_Dashboard_{client}.html"
  compiled_date: ""              # ISO date; defaults to today
  language: "English"            # Stage-0 Q3: dashboard language (orchestrator fills from the broker's answer)
inputs:
  folder: "."
  present_types: {json.dumps(inv['present_types'])}
  clusters:                      # region -> country (auto-inferred; fix if wrong)
{clusters_block}
  emails:                        # Stage 0 Q2: pull property info from Outlook emails? (broker picks at Stage 0)
    source: {"folder" if inv["emails"] else "none"}             # none | outlook | folder (.msg/.eml fallback)
    outlook_folder: ""           # Outlook mail FOLDER when source: outlook (e.g. Inbox, or "Normal CEE"); blank = all folders
    mailbox: ""                  # optional shared/delegated mailbox email
    query: ""                    # subject/keyword text (combine with a date window)
    folder: "{inputs_folder if inv["emails"] else ""}"                  # filesystem .msg/.eml folder when source: folder (fallback only)
enrichment:                      # broker opt-in; ask in plain language before running
  geocode: true                  # fill map coordinates (recommended)
  pois: true                     # nearby ports/rail/airports/borders on the map
  osrm: false                    # drive-times to the POIs (needs network or the web_enrich handoff)
  regions: false                 # workforce/labour profiles (research sub-agent)
  osrm_endpoint: "https://router.project-osrm.org"
  ors_api_key: ""                # openrouteservice key -> TRUCKING (HGV) drive times
                                 # (or set the ORS_API_KEY env var); blank = car routing, flagged
qa:
  fill_threshold: 0.6
"""


def _load_cluster_cache(outdir: Path):
    """Best-effort read of the optional work/intake_clusters.json (the orchestrator's
    LLM-refined filename->region labels). A missing / malformed file returns None so
    discover falls back to infer_cluster verbatim - never a traceback."""
    f = outdir / "intake_clusters.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _merge_clusters_into_yaml(yml: Path, inv: dict) -> bool:
    """When project.yaml already exists, MERGE the (re-clustered) region->country map
    into inputs.clusters rather than overwriting - keeping every other broker edit.
    Returns True if a merge was applied. Best-effort: any parse/dump failure leaves
    the existing file untouched (the broker's confirmed config wins)."""
    try:
        import yaml
        cfg = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        if not isinstance(cfg, dict):
            return False
        new_clusters = {r: (c.get("country") or "??") for r, c in inv["clusters"].items()}
        inputs = cfg.setdefault("inputs", {}) if isinstance(cfg.get("inputs", {}), dict) else None
        if inputs is None:
            return False
        cur = inputs.get("clusters") if isinstance(inputs.get("clusters"), dict) else {}
        # keep a broker-set country (not the '??' placeholder) for a region that survives
        merged = dict(new_clusters)
        for r, country in cur.items():
            if r in merged and merged[r] in ("", "??") and country not in ("", "??", None):
                merged[r] = country
        if merged == cur:
            return False  # nothing changed -> leave the file byte-identical
        inputs["clusters"] = merged
        C.atomic_write_text(yml, yaml.safe_dump(
            cfg, default_flow_style=False, allow_unicode=True, sort_keys=False))
        return True
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", help="inputs folder (or pass --folder)")
    ap.add_argument("--folder", dest="folder_opt", help="alias for the positional inputs folder")
    ap.add_argument("--out-dir", "--work", dest="out_dir", default=".",
                    help="work/output dir (--work is an alias, matching run.py's flag)")
    ap.add_argument("--client", default="Client")
    args = ap.parse_args()
    folder_arg = args.folder_opt or args.folder
    if not folder_arg:
        ap.error("provide the inputs folder (positional, or --folder)")
    folder = Path(folder_arg)
    if not folder.is_dir():
        ap.error(f"inputs folder does not exist or is not a directory: {folder} "
                 f"(a mistyped path? it must be an existing folder of property files) - S0-42")
    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    # The orchestrator's LLM-refined labels (work/intake_clusters.json) override the
    # regex per stem when present + verified; absence forces the deterministic regex.
    inv = discover(folder, cluster_cache=_load_cluster_cache(outdir))
    C.atomic_write_text(outdir / "inventory.json", json.dumps(inv, ensure_ascii=False, indent=2))
    yml = outdir / "project.yaml"
    if not yml.exists():
        C.atomic_write_text(yml, scaffold_yaml(inv, args.client, folder.as_posix()))
        scaffolded = " (scaffolded project.yaml)"
    elif _merge_clusters_into_yaml(yml, inv):
        scaffolded = " (project.yaml exists; clusters merged)"
    else:
        scaffolded = " (project.yaml exists; kept)"
    sys.stdout.reconfigure(encoding="utf-8")
    n_brochures = sum(len(c.get("pdfs", [])) + len(c.get("pptxs", []))
                      for c in inv["clusters"].values())
    print(f"OK inventory: {len(inv['clusters'])} clusters / {n_brochures} brochures "
          f"({', '.join(inv['clusters'])}), {len(inv['xlsx'])} xlsx, "
          f"{len(inv['images'])} images, {len(inv['emails'])} emails{scaffolded}")
    if inv.get("subfolders"):  # nothing silently invisible: name what was scanned
        print(f"NOTE: scanned {len(inv['subfolders'])} subfolder(s) too: "
              f"{', '.join(inv['subfolders'][:8])}")
    if inv.get("skipped_outputs"):  # transparency: a prior run's own files were ignored
        print(f"NOTE: ignored {len(inv['skipped_outputs'])} prior-run output file(s) in the "
              f"inputs folder (not treated as inputs): {', '.join(inv['skipped_outputs'][:6])}")
    if inv.get("skipped_hash_oversize"):  # transparency: a too-big file skipped the dedup check
        print(f"NOTE: {len(inv['skipped_hash_oversize'])} file(s) too large to de-duplicate "
              f"(>{_DEDUP_MAX_BYTES // (1024 * 1024)} MB) - still discovered, dedup check skipped: "
              f"{', '.join(inv['skipped_hash_oversize'][:4])}")
    unresolved = [r for r, c in inv["clusters"].items() if not c.get("country")]
    if inv["clusters"] and unresolved:
        print(f"NOTE: country not auto-inferred for {len(unresolved)}/{len(inv['clusters'])} cluster(s) "
              f"(the city->country index is CEE-seeded). Confirm 'country' for these in project.yaml "
              f"(else it stays '??'); --geocode resolves map coordinates regardless: {', '.join(unresolved)}")
    # Fire ONLY when no ACCEPTED source of any kind was found - an xlsx/CSV tracker,
    # emails or images extract fine without a single PDF/PPTX, so this must not fire
    # the moment brochures alone are absent (it once cried 'no sources' over a folder
    # that held a full tracker). Name every accepted source type so the broker knows
    # what to add.
    if not (inv["clusters"] or inv["xlsx"] or inv["emails"] or inv["images"]):
        print("WARNING: no usable inputs found - add PDF/PPTX brochures, Excel/CSV trackers, "
              "emails (.msg/.eml) or images, then run again.")


if __name__ == "__main__":
    main()
