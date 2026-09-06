#!/usr/bin/env python3
"""intake.py - Stage 0. Discover inputs and scaffold project.yaml.

Scans a folder RECURSIVELY (hidden/underscore dirs skipped, scanned subfolders
named in the output) for the five input types, infers a city/region cluster per
brochure from its filename (e.g. "Normal Options - Pilsen.pdf" -> Pilsen, noise
suffixes like "- FINAL"/"- v2" dropped; a numbered export "03_Riverside_Park.pdf"
-> Riverside Park), keeps EVERY brochure per cluster (pdfs/pptxs lists - never a
silent overwrite), looks up the country from the POI library's city->country
index (a miss is left BLANK, never a placeholder token), writes inventory.json,
and (if absent) scaffolds a project.yaml pre-filled from what was found. The
orchestrator then confirms the config with the broker.

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
# NUMBERED EXPORT (F3). A broker who exports a numbered set writes "01_Riverside_Park.pdf" /
# "02-Harbour-Gate.pdf": a 1-3 digit index, an underscore or hyphen, then the name with the
# SAME character doing the word separation and no region delimiter anywhere. The spaced-dash
# splitter had nothing to split on, so on a live run EVERY brochure of such a corpus went to
# the "optional" cluster-label agent (7 of 7) and the agent's own diagnosis was exactly this
# shape. The index is stripped, the remainder becomes the label. Deliberately narrow:
#   1-3 digits only  - a 4-digit run is a year ("2024_Availability"), not an index;
#   the remainder must start with a letter - "12-14 Station Road" is an address RANGE, and
#                      stripping "12-" would relabel it as a different house number;
#   nothing else     - "2 Riverside Road" (digit + space) is a house number, and a dotted or
#                      bracketed index is left to the agent rather than guessed at.
# It sets ONLY the routing/scaffold label: the displayed region/city stay brochure-derived.
_INDEX = re.compile(r"^\d{1,3}\s*[-_]+\s*(?=[^\W\d_])")


def _poi_lib() -> dict:
    f = C.ASSETS / "poi_library.json"
    try:  # a corrupt/truncated library is a degraded convenience, never a crash
        return json.loads(f.read_text(encoding="utf-8-sig")) if f.exists() else {"city_country": {}}
    except Exception:
        return {"city_country": {}}


def _export_words(body: str) -> str:
    """The label for a numbered export's remainder ("Riverside_Park" -> "Riverside Park").
    Whichever character does the separating IS the word separator: underscores always
    become spaces; hyphens become spaces ONLY when the remainder has neither spaces nor
    underscores of its own ("Harbour-Gate-Estate"), because a name that already uses
    spaces keeps its hyphens ("CTPark Brookvale-South" is ONE park, and the spaced-dash
    path's rule that a hyphenated name is never split holds here too). Trailing noise
    tokens (FINAL, v2, draft) are dropped exactly as the spaced-dash path drops them."""
    s = body.replace("_", " ") if "_" in body else (
        re.sub(r"[-\u2013\u2014]", " ", body) if " " not in body else body)
    words = s.split()
    while len(words) > 1 and _NOISE.fullmatch(words[-1]):
        words.pop()
    return " ".join(words)


def infer_cluster(stem_file: str, city_country: dict) -> tuple[str, str, str]:
    """Best-effort (region_label, country, confidence) from a brochure filename. The
    region is the text after a ' - ' (e.g. 'Normal Options - Pilsen.pdf' -> 'Pilsen'),
    else the whole stem - it is only a cluster LABEL; the real city is read from the
    brochure at extraction. country comes from the POI library's city->country
    index, which is a CEE-seeded CONVENIENCE: a miss returns '' (left BLANK in the
    scaffold, never a placeholder token, F7) for the broker to confirm. Coordinates
    are resolved globally by --geocode regardless, so an unknown country here never
    blocks the map.

    A NUMBERED EXPORT ("03_Riverside_Park", "04-Harbour-Gate", see _INDEX) is tried
    ONLY after the whole stem has fallen through to the low fallback, so every shape
    that already split keeps its exact label ("07 - Riverside_Park" stays the spaced-
    dash result, and a re-run on an existing project.yaml keeps its cluster keys and
    the broker's countries under them). Then the index is stripped and the remainder
    judged as if it were the filename: "04_Options - Westford" splits on its spaced
    dash, "07_Options-Westford" finds the known-city tail, and only when neither fires
    does the word-separated remainder ("Riverside Park") become the label. (F3)

    confidence is a PURELY ADDITIVE structural signal (it never changes the chosen
    region) so the Stage-0 orchestrator can judge only the ambiguous tail:
      'high' = a clean spaced-dash split, OR the unspaced dash/underscore tail was a
               known city, OR a numbered export was stripped to a real name;
      'low'  = the whole-stem fallback fired (no spaced dash, no index prefix AND the
               unspaced tail was NOT a known city - the 'Options-Oporto' case)."""
    stem = Path(stem_file).stem
    region, confidence = _split_stem(stem, city_country)
    if confidence == "low":
        _idx = _INDEX.match(stem)
        if _idx:
            body = stem[_idx.end():]  # the export index is never a region
            region, confidence = _split_stem(body, city_country)
            if confidence == "low":
                # a numbered export with no other structure: the index WAS the split, and
                # the word-separated remainder is the name. Confident, because the agent
                # could add nothing here but a coin-flip between the estate name and a
                # village from the brochure body - and the body is read at extraction anyway.
                words = _export_words(body)
                if words and not _NOISE.fullmatch(words):
                    region, confidence = words, "high"
    if confidence == "low":
        region = stem  # the whole-stem fallback: the agent's to judge
    country = city_country.get(region.lower(), "")
    return region, country, confidence


def _split_stem(s: str, city_country: dict) -> tuple[str, str]:
    """The deterministic judgement of ONE stem: (region, confidence), where a 'low'
    region is `s` itself. Factored out of infer_cluster so a numbered export's remainder
    is judged by exactly the same rules as a whole filename."""
    parts = [p.strip() for p in _SEP.split(s) if p.strip()]
    had_sep = len(parts) > 1
    while len(parts) > 1 and _NOISE.fullmatch(parts[-1]):
        parts.pop()  # drop trailing FINAL / draft / v2 / dates - they are not regions
    if len(parts) > 1:
        return parts[-1], "high"  # a clean spaced-dash split produced a real tail
    if had_sep and parts:
        # a single real segment survived after noise-stripping ('City - FINAL' -> 'City'):
        # use it, not the whole stem which would leak the ' - FINAL' noise (audit S0-41)
        return parts[0], "high"
    # unspaced dash/underscore fallback ONLY when the tail is a known city
    # ("Options-Madrid" -> Madrid) - never split a hyphenated park name like
    # "Brno-South" blindly
    tail = re.split(r"[-\u2013\u2014_]", s)[-1].strip()
    if tail and tail.lower() != s.lower() and tail.lower() in city_country:
        return tail, "high"  # the tail is a known city -> a confident split
    return s, "low"  # the whole-stem fallback fired


def _brochure_input_hash(rels) -> str:
    """sha1[:8] over the SORTED brochure relpaths (the cluster INPUT) - the same
    recipe as the tracker map cache (run.py _tracker_struct_hash). A changed
    brochure set changes the hash, which invalidates a stale intake_clusters.json
    so the next pass re-clusters rather than re-applying stale labels."""
    payload = json.dumps(sorted(rels), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


# F16: the cap on one label's `note`. A close call fits in a sentence; a paragraph is the
# agent narrating, and inventory.json is a resume input read on every pass.
_NOTE_MAX_CHARS = 400


def _verified_cluster_overrides(cache, input_hash: str, stems: set) -> dict:
    """STRUCTURAL CACHE VERIFIER. Returns a {stem -> (region, country, note)} override
    map from work/intake_clusters.json ONLY when EVERY guard holds; ANY failure discards
    the WHOLE cache (returns {}) and the caller falls back to infer_cluster verbatim
    - never a traceback. Guards: the cache parses to a dict; its input_hash matches
    the current brochure set; and each label's stem is a real discovered file with a
    non-empty region that is not a _NOISE token.

    `note` (F16) is the label agent's OPTIONAL one-line reasoning for a close call ("X
    or Y; chose X because ..."). It used to reach only the orchestrator's chat and then
    evaporate, so a surprising label on a later run had no trail. It is carried, never
    judged: absent or non-string -> '' (an optional field must never be the reason a
    whole cache is thrown away), whitespace-trimmed, capped so a runaway paragraph
    cannot bloat inventory.json. It is a routing-label note and reaches NO card; the
    Gaps Report's "Noted, not put to you" is where it is meant to land."""
    if not isinstance(cache, dict):
        return {}
    # Accept `cluster_input_hash` as an alias: inventory.json now publishes BOTH hashes (B41),
    # and a sub-agent told to "copy input_hash from inventory.json" may reasonably copy the
    # brochure-set key under its own name. Reading either beats silently discarding the cache -
    # which is what happened while neither key was published at all.
    if input_hash not in (cache.get("input_hash"), cache.get("cluster_input_hash")):
        return {}  # a changed brochure set -> stale -> drop
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
        note = lab.get("note")
        note = note.strip()[:_NOTE_MAX_CHARS] if isinstance(note, str) else ""
        overrides[stem] = (region, (lab.get("country") or "").strip(), note)
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


# Folder names that ARE a run's own output tree. `deliverables` is the legacy location;
# `3. output` is the three-folder project layout's client-facing folder. In that layout the
# output folder is a SIBLING of `1. Input`, so this never fires on a correct run - it is the
# net for someone pointing `--folder` at the project root instead.
_OWN_OUTPUT_DIRS = frozenset({"deliverables", "3. output"})


def _is_own_output(rel: str) -> bool:
    p = Path(rel)
    return (any(s.lower() in _OWN_OUTPUT_DIRS for s in p.parts[:-1])
            or bool(_OWN_OUTPUT.search(p.name)))


def discover(folder: Path, cluster_cache=None, exclude_dir=None) -> dict:
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
           "skipped_duplicates": [], "skipped_hash_oversize": [],
           # A file whose extension matches NO branch below. It used to fall off the end of the
           # classifier silently - not a brochure, not a tracker, not an image, not an email, and
           # NOT recorded as unreadable either (that path only covers accepted-but-unparsed
           # files). So a broker who handed over a .json or .txt of property data got "no
           # readable property sources" while their file appeared NOWHERE: not the inventory,
           # not the ledger, not the Gaps Report. Believing your data was considered when it was
           # never opened is worse than a crash. Now every such file is named and surfaced.
           "unclassified": []}
    # `~$` = an Office LOCK/owner file, written by Word/Excel/PowerPoint while a document is OPEN
    # and left behind after a crash. It is not a document: ingesting one gave the run a SECOND
    # tracker/brochure that duplicated every property from the real file, which then had to be
    # de-duplicated through cross-source match adjudication (a sub-agent round-trip) - or worse,
    # shipped twice. A broker with the spreadsheet open in Excel hits this EVERY time.
    #
    # T1: the WORK DIR is excluded from the walk (exclude_dir = intake's --out-dir). Putting
    # `--work` INSIDE the inputs folder is the natural thing to do, and a live run that did it
    # ingested its own per-property `sources.csv` views as 31 phantom trackers and its own JSON
    # as unreadable inputs. The dot/underscore filter below only saved work dirs that happened
    # to be named `_something`; the run's own output tree must never be its input regardless of
    # its name. Disclosed (count in `excluded_workdir`), never silent.
    _excl = None
    if exclude_dir:
        try:
            _excl = Path(exclude_dir).resolve()
        except OSError:
            _excl = None

    def _under_workdir(p: Path) -> bool:
        if _excl is None:
            return False
        try:
            p.resolve().relative_to(_excl)
            return True
        except (ValueError, OSError):
            return False

    _n_excluded = 0
    _cands = []
    for p in folder.rglob("*"):
        if not p.is_file() or p.name.startswith("~$") \
                or any(part.startswith((".", "_")) for part in p.relative_to(folder).parts):
            continue
        if _under_workdir(p):
            _n_excluded += 1
            continue
        _cands.append(p)
    files = sorted(_cands, key=lambda p: p.relative_to(folder).as_posix())
    if _n_excluded:
        inv["excluded_workdir"] = {"dir": str(_excl), "files": _n_excluded}
        print(f"  (work dir sits inside the inputs folder - excluded its {_n_excluded} "
              f"file(s) from intake: {_excl})")
    # BASENAME COLLISIONS. Records reference their source by bare basename, so two inputs
    # sharing one name are indistinguishable downstream: one property can wear another's
    # photos, and because page ownership keys on the RESOLVED path, both can instead lose
    # their gallery entirely. Resolution is now deterministic (_common.resolve_by_name), but
    # deterministic is not correct - so say so, HERE, before the expensive stages, while the
    # broker can still rename a file. A NOTE, never a refusal: two site folders each holding
    # `photos.pdf` is a legitimate shape. (B13)
    for _bn, _rels in sorted(C.basename_collisions(folder).items()):
        print(f"NOTE {len(_rels)} input files share the basename {_bn!r} "
              f"({', '.join(_rels[:4])}{' ...' if len(_rels) > 4 else ''}) - records name "
              f"their source by basename only, so photos/pages may bind to the wrong one. "
              f"Rename them to be safe.")
    subdirs: set[str] = set()
    seen_hashes: dict[str, str] = {}  # sha256 -> the rel path we kept (INTAKE-001)
    corpus_sig: list = []             # (rel, sha256) per KEPT CLASSIFIED input -> input_hash (B41)
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
        # CORPUS IDENTITY (B41). Keep (rel, digest) for every KEPT CLASSIFIED input - the
        # sha256 is already computed just above for the INTAKE-001 duplicate check, so this is
        # free. It becomes inv["input_hash"], the key gate_runner._qa_run_key and gates.md
        # already CLAIM to read and which was never published: with it absent the QA window
        # silently fell back to inv["folder"], a constant for a given work dir, so the window
        # was blind to every in-place corpus change.
        if ext in (".pdf", ".pptx", ".xlsx", ".xlsm", ".csv",
                   ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".msg", ".eml"):
            corpus_sig.append((rel, digest))
        if ext in (".pdf", ".pptx"):
            kept_brochures.append((rel, ext, p.stem))
        elif ext in (".xlsx", ".xlsm", ".csv"):
            inv["xlsx"].append(rel)
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
            inv["images"].append(rel)
        elif ext in (".msg", ".eml"):
            inv["emails"].append(rel)
        else:
            inv["unclassified"].append({"file": rel, "ext": ext or "(none)"})
    # PASS 2: cluster the kept brochures. The cluster INPUT is the sorted brochure
    # relpaths; the verified LLM cache (if any) overrides infer_cluster per stem.
    brochure_rels = [rel for rel, _ext, _stem in kept_brochures]
    stems = {stem for _rel, _ext, stem in kept_brochures}
    # PUBLISH BOTH HASHES (B41). Two different identities, deliberately separate:
    #   input_hash         - the WHOLE corpus (every kept classified input + its content), what
    #                        the QA window keys on. Content-derived, NOT mtime-derived: the
    #                        resume guard rewrites inventory.json whenever the folder mtime
    #                        moves, so an mtime key would reset the window on an untouched
    #                        corpus - and a spurious reset is not cosmetic, because _qa_load
    #                        wipes `rounds`, qa_carried() returns [] and the delivered Gaps
    #                        Report silently loses every carried limitation.
    #   cluster_input_hash - the BROCHURE SET only, which is what the Stage-0 cluster-label
    #                        cache compares. It was computed here and thrown away, which left
    #                        that cache permanently unreachable.
    # Deliberately EXCLUDED: unclassified, skipped_* and the region labels - none of them
    # changes what ships, so including them would reset the window for nothing.
    inv["input_hash"] = hashlib.sha1(
        "\n".join(f"{r}|{d}" for r, d in sorted(corpus_sig)).encode("utf-8")).hexdigest()[:12]
    inv["cluster_input_hash"] = _brochure_input_hash(brochure_rels)
    overrides = _verified_cluster_overrides(cluster_cache, inv["cluster_input_hash"], stems)
    # F16: the label agent's close-call reasoning, one entry per label that carried a
    # `note`. Published flat and top-level (not buried per cluster) so the Gaps Report
    # writer can lift it straight into "Noted, not put to you". Always present, so a
    # reader never has to guess whether the key exists; empty on a regex-only run.
    inv["cluster_label_notes"] = []
    for rel, ext, stem in kept_brochures:
        region, country, confidence = infer_cluster(Path(rel).name, cc)
        if stem in overrides:  # the broker-confirmed, input-hashed LLM label wins
            region, ov_country, note = overrides[stem]
            country = ov_country or cc.get(region.lower(), "")
            confidence = "high"  # an applied, verified label is no longer ambiguous
            if note:
                inv["cluster_label_notes"].append(
                    {"stem": stem, "region": region, "country": country, "note": note})
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
    # An UNKNOWN country is written BLANK ('' -> `Region: ''`), never a '??' token (F7).
    # The token travelled: it was copied into the manifest, and five of seven readers on
    # one run said unprompted that they had to derive the country themselves because
    # they were handed '??' - producing three different spellings across seven decks and
    # one broker question. Blank is what every other unset value in this scaffold already
    # is (region_label, eyebrow, mailbox), it reads as "not filled" to a human, and
    # _merge_clusters_into_yaml treats '' / None / a legacy '??' as the same placeholder.
    _clusters = {r: (c.get("country") or "") for r, c in inv["clusters"].items()}
    _cl = yaml.safe_dump(_clusters, default_flow_style=False, allow_unicode=True,
                         sort_keys=False).rstrip("\n") if _clusters else "{}"
    clusters_block = "\n".join("    " + ln for ln in _cl.splitlines())
    return f"""# project.yaml - one per client project. Confirm before running.
#
# EVERY VALUE BELOW IS A DEFAULT THIS SCAFFOLD GUESSED, not an answer the broker gave.
# `setup.confirmed` is the ONLY thing that says otherwise, and it stays false until the
# orchestrator has put the Stage-0 form to the broker and written their answers in here.
# It exists because "does project.yaml carry the answers?" used to be the test for whether
# to ask - and this file always carried them, so a compliant orchestrator correctly skipped
# the form and every run silently shipped English, no emails and car drive-times. (B63)
setup:
  confirmed: false               # set true ONLY after the broker has answered the Stage-0 form
client:
  name: {client}
  confidential: true
market:
  title_html: ""                 # headline; blank renders the localised default. Keep ONE <em>..</em> pair for the accent colour
  eyebrow: ""                    # e.g. "Property Shortlist · Spain"; blank renders the localised default. A value ships VERBATIM (write the full eyebrow)
  region_label: ""
  countries: {json.dumps(countries)}
  lede: ""                       # optional; blank renders the localised default (in the dashboard's language)
output:
  filename: "CBRE_Property_Dashboard_{client}.html"
  compiled_date: ""              # ISO date; defaults to today
  language: "English"            # Stage-0 Q3: dashboard language (orchestrator fills from the broker's answer)
inputs:
  folder: "."
  present_types: {json.dumps(inv['present_types'])}
  clusters:                      # region -> ISO-2 country (auto-inferred; fix if wrong; '' = not inferred: fill it, or let --geocode resolve it)
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
clarify:
  mode: interactive              # the STANDARD: ask the broker when a judgement call
                                 # affects what a card shows. 'headless' (or
                                 # assume_defaults: true / the SKIP_ALL sentinel) keeps
                                 # the default-honestly-and-disclose contract instead
"""


def _load_cluster_cache(outdir: Path):
    """Best-effort read of the optional work/intake_clusters.json (the orchestrator's
    LLM-refined filename->region labels). A missing / malformed file returns None so
    discover falls back to infer_cluster verbatim - never a traceback."""
    f = outdir / "intake_clusters.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_comment_or_blank(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _split_inline_comment(body: str) -> tuple[str, str]:
    """Split one YAML line body into (content, inline comment). A '#' opens a comment only
    when it is preceded by whitespace and sits outside a quoted scalar, which is YAML's own
    rule, so `'Unit #5': XX` keeps its hash and `Northgate: XX   # hand-set` loses nothing."""
    q = None
    i = 0
    while i < len(body):
        ch = body[i]
        if q:
            if ch == q:
                if q == "'" and body[i + 1:i + 2] == "'":
                    i += 2  # a doubled quote is an escaped quote inside a single-quoted scalar
                    continue
                q = None
            elif q == '"' and ch == "\\":
                i += 1
        elif ch in "'\"" and (i == 0 or body[i - 1] in " \t"):
            q = ch
        elif ch == "#" and (i == 0 or body[i - 1] in " \t"):
            return body[:i].rstrip(), body[i:]
        i += 1
    return body.rstrip(), ""


def _entry_line(indent: int, region: str, country, comment: str = "") -> str:
    """One `Region: country` line, emitted through safe_dump so a label that is not a plain
    scalar ('Unit 5: Phase 2', a leading '[') is quoted correctly, then re-indented and given
    back the inline comment its predecessor carried."""
    import yaml
    body = yaml.safe_dump({region: country}, default_flow_style=False, allow_unicode=True,
                          sort_keys=False).strip("\n")
    if "\n" in body:  # a region label safe_dump cannot put on one line has no place in this block
        raise ValueError(f"cluster label {region!r} does not fit one YAML line")
    return " " * indent + body + (("  " + comment) if comment else "")


def _splice_clusters_block(text: str, cur: dict, merged: dict) -> tuple[str | None, str]:
    """Rewrite ONLY the `inputs.clusters` block of a project.yaml TEXT, in place, and return
    (new_text, "") - or (None, reason) when the block cannot be located UNAMBIGUOUSLY.

    WHY NOT safe_dump. A whole-document round-trip drops every comment in the file, and the
    header comment is the one that stops the B63 incident recurring: it tells the reader that
    every value in the file is a scaffold guess and that `setup.confirmed` alone says otherwise.
    The destroying pass was the ORDINARY one (cluster keys change on the pass right after the
    label agent writes its cache), so the warning was written on pass 1 and gone on pass 2.

    The block is found structurally, not parsed: exactly ONE top-level `inputs:` line, exactly
    ONE `clusters:` line at its child indent (zero means "insert one as the last child"), whose
    own value is empty or a bare `{}`. Its body is every following line that is blank, a
    comment, or indented deeper, and every CONTENT line in it must parse on its own as one
    `Region: country` pair; the pairs read this way must equal what safe_load read from the
    whole document (`cur`), so a duplicate key, a nested value or a merge key is a refusal, not
    a guess. Then, entry by entry: an unchanged entry is kept BYTE-EXACT (its inline comment
    with it), a changed value is rewritten on its own line with its inline comment carried
    over, a dropped region loses its line only, new regions are appended after the last entry.
    THIS FUNCTION NEVER DELETES A COMMENT OR A BLANK LINE: a comment that led a dropped region
    stays where it was, for the human to keep or remove. Line endings, a UTF-8 BOM and the
    trailing-newline state are the caller's to preserve; this works on LF text.

    Every refusal is a reason string the caller prints. Refusing is the safe answer: a file
    this function will not edit is a file that has been hand-shaped in a way the block scanner
    does not understand, and the broker's shape wins over an inferred country map."""
    lines = text.split("\n")
    # -- 1. the one top-level `inputs:` line
    hdrs = [i for i, ln in enumerate(lines) if re.match(r"^inputs:\s*(#.*)?$", ln)]
    if len(hdrs) != 1:
        return None, (f"found {len(hdrs)} top-level `inputs:` lines, expected exactly one"
                      if hdrs else "no top-level `inputs:` line")
    h = hdrs[0]
    end = len(lines)  # the inputs block runs to the next top-level content line
    for i in range(h + 1, len(lines)):
        if not _is_comment_or_blank(lines[i]) and _indent(lines[i]) == 0:
            end = i
            break
    children = [i for i in range(h + 1, end) if not _is_comment_or_blank(lines[i])]
    if children and _indent(lines[children[0]]) == 0:
        return None, "`inputs:` has no indented children to locate `clusters:` among"
    child_ind = _indent(lines[children[0]]) if children else 2
    # -- 2. the one `clusters:` child
    cands = [i for i in children
             if _indent(lines[i]) == child_ind and re.match(r"^\s*clusters:(\s|$)", lines[i])]
    if len(cands) > 1:
        return None, f"found {len(cands)} `clusters:` keys under `inputs:`, expected one"
    entry_ind = child_ind + 2
    if not cands:
        # no block at all under an unambiguous inputs: insert one after its last content line
        # (an inputs: with no children gets it directly beneath). Everything else is untouched.
        at = (children[-1] + 1) if children else (h + 1)
        block = [" " * child_ind + "clusters:"] + (
            [_entry_line(entry_ind, r, v) for r, v in merged.items()] or [" " * entry_ind + "{}"])
        new_lines = lines[:at] + block + lines[at:]
        return "\n".join(new_lines), ""
    c = cands[0]
    hdr_content, hdr_comment = _split_inline_comment(lines[c].strip()[len("clusters:"):].strip())
    if hdr_content not in ("", "{}"):
        return None, (f"`clusters:` carries an inline value ({hdr_content[:40]!r}); only a block "
                      f"mapping or a bare {{}} can be edited in place")
    # -- 3. the body: blank/comment lines belong to the block only while a deeper content line
    # still follows (so trailing comments before the next key are left outside it)
    b = c + 1
    while b < len(lines):
        if _is_comment_or_blank(lines[b]):
            nxt = next((j for j in range(b + 1, len(lines)) if not _is_comment_or_blank(lines[j])), None)
            if nxt is not None and _indent(lines[nxt]) > child_ind:
                b += 1
                continue
            break
        if _indent(lines[b]) > child_ind:
            b += 1
            continue
        break
    body = lines[c + 1:b]
    # -- 4. parse the body line by line into (leading lines, entry line, key, value)
    import yaml
    entries: list[tuple[list[str], str, str, object]] = []
    leading: list[str] = []
    placeholder_lines = 0
    for ln in body:
        if _is_comment_or_blank(ln):
            leading.append(ln)
            continue
        content, _cmt = _split_inline_comment(ln.strip())
        if content == "{}":
            placeholder_lines += 1  # the scaffold's empty-block marker: dropped on rewrite
            continue
        try:
            one = yaml.safe_load(ln)
        except Exception:
            one = None
        if not isinstance(one, dict) or len(one) != 1:
            return None, f"a line inside `clusters:` is not one `Region: country` entry: {ln.strip()[:60]!r}"
        (k, v), = one.items()
        entries.append((leading, ln, k, v))
        leading = []
    tail = leading  # comments/blanks after the last entry, still inside the block
    if entries:
        entry_ind = _indent(entries[0][1])
    read_back = {k: v for _l, _ln, k, v in entries}
    if len(read_back) != len(entries) or read_back != dict(cur):
        return None, ("the entries read line by line do not match what the document parses to "
                      "(a duplicate region, a merge key or a value that spans lines?)")
    # -- 5. emit
    out: list[str] = []
    seen: set = set()
    for lead, ln, k, v in entries:
        out.extend(lead)
        if k not in merged:
            continue  # a dropped region: its line goes, its comments stay (they are above it)
        seen.add(k)
        if merged[k] == v:
            out.append(ln)  # unchanged: byte-exact, inline comment and all
        else:
            out.append(_entry_line(_indent(ln), k, merged[k], _split_inline_comment(ln.strip())[1]))
    for k, v in merged.items():
        if k not in seen:
            out.append(_entry_line(entry_ind, k, v))
    if not merged and not any(not _is_comment_or_blank(x) for x in out):
        out.append(" " * entry_ind + "{}")  # an explicit empty mapping, as the scaffold writes it
    out.extend(tail)
    hdr_line = lines[c] if hdr_content == "" else (
        " " * child_ind + "clusters:" + (("  " + hdr_comment) if hdr_comment else ""))
    new_lines = lines[:c] + [hdr_line] + out + lines[b:]
    return "\n".join(new_lines), ""


def _merge_clusters_into_yaml(yml: Path, inv: dict) -> bool:
    """When project.yaml already exists, MERGE the (re-clustered) region->country map
    into inputs.clusters rather than overwriting - keeping every other broker edit AND
    every comment. Returns True if a merge was applied. Best-effort: any parse failure,
    and any file whose `clusters:` block cannot be located unambiguously, leaves the
    existing file byte-identical and says so on stdout (the broker's shape wins). There
    is deliberately NO whole-document fallback: see _splice_clusters_block."""
    try:
        import yaml
        raw = yml.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
        cfg = yaml.safe_load(text) or {}
        if not isinstance(cfg, dict):
            return False
        new_clusters = {r: (c.get("country") or "") for r, c in inv["clusters"].items()}
        inputs = cfg.get("inputs") if isinstance(cfg.get("inputs"), dict) else {}
        if cfg.get("inputs") is not None and not isinstance(cfg.get("inputs"), dict):
            return False
        cur = inputs.get("clusters") if isinstance(inputs.get("clusters"), dict) else {}
        # keep a broker-set country for a region that survives. The PLACEHOLDERS are '' (what
        # this scaffold writes now, F7), None (a bare `Region:` line a human left blank) and
        # the legacy '??' token an older scaffold wrote - all three mean "not known", none is
        # a broker answer, and a project.yaml from before F7 must keep working.
        # A NON-blank value in the file ALWAYS wins over the inference, blank or not. The index
        # returns the same country for the same key on every pass, so the only ways a key can
        # carry a different non-blank value are a human correcting it (must win) or the label
        # agent disagreeing with the index about an unchanged label (a routing guess either
        # way, and the broker confirmation is the backstop). The old rule let a non-blank
        # inference silently revert a hand edit on the next re-cluster.
        # The limit, stated: '' cannot mean "the broker cleared this". A blank is "not
        # inferred yet" by the file's own comment, so it is re-filled whenever the index knows
        # the region. There is no value that means "no country" in this design.
        _blank = ("", "??", None)
        merged = dict(new_clusters)
        for r, country in cur.items():
            if r in merged and country not in _blank:
                merged[r] = country
        # compare with the placeholders folded together: a file whose ONLY difference is a
        # legacy '??' where we would now write '' is NOT a change worth a rewrite.
        if merged == {r: ("" if v in _blank else v) for r, v in cur.items()}:
            return False  # nothing changed -> leave the file byte-identical
        # line endings: read off the file, restored on write; a mixed file is refused
        crlf = "\r\n" in text
        if crlf and text.count("\r\n") != text.count("\n"):
            print("WARNING: project.yaml mixes CRLF and LF line endings; inputs.clusters was NOT "
                  "merged and the file was left untouched. Normalise the line endings and re-run, "
                  "or copy inventory.json's clusters into inputs.clusters by hand.")
            return False
        lf_text = text.replace("\r\n", "\n") if crlf else text
        new_text, reason = _splice_clusters_block(lf_text, cur, merged)
        if new_text is not None:
            # the one guard that does not trust the scanner: the edited document must parse
            # to the SAME config with ONLY inputs.clusters replaced
            check = yaml.safe_load(new_text)
            want = dict(cfg)
            want["inputs"] = dict(inputs)
            want["inputs"]["clusters"] = merged
            if check != want:
                new_text, reason = None, "the edited text does not parse to the expected config"
        if new_text is None:
            print(f"WARNING: project.yaml: could not edit inputs.clusters in place ({reason}). "
                  f"The file was left untouched, its comments intact, and the re-clustered map was "
                  f"NOT merged. Copy inventory.json's clusters into inputs.clusters by hand, or "
                  f"restore the block to the scaffold's `Region: country` shape and re-run.")
            return False
        if crlf:
            new_text = new_text.replace("\n", "\r\n")
        C.atomic_write_bytes(yml, (b"\xef\xbb\xbf" if bom else b"") + new_text.encode("utf-8"))
        return True
    except Exception as e:
        # an unreadable / non-UTF-8 / malformed project.yaml (run.py's load_yaml says the same
        # in its own words): never a traceback, never a rewrite, and never silent either
        print(f"WARNING: project.yaml: inputs.clusters was NOT merged "
              f"({type(e).__name__}: {str(e).splitlines()[0][:100] if str(e) else 'no detail'}); "
              f"the file was left untouched.")
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
    inv = discover(folder, cluster_cache=_load_cluster_cache(outdir), exclude_dir=outdir)
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
              f"(the city->country index is CEE-seeded). Fill 'country' for these in project.yaml "
              f"(else it stays blank); --geocode resolves map coordinates regardless: {', '.join(unresolved)}")
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
