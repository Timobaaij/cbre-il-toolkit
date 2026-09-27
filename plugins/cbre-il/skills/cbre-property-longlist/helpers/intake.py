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
import os
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


def _nofuse_rejections(kept_brochures, det: dict, overrides: dict) -> dict:
    """{stem: (proposed region, why)} for every cached label that would MERGE decks.

    2026-09-26 test run, fix 3.1. A cluster is keyed on its region string, so two decks whose
    labels named the same town landed in ONE cluster: one master-list row for two brochures, two
    row ids deleted and one minted, the answered sheet no longer matched and exit 17 re-fired on
    a sheet the broker had finished. A label is a ROUTING NAME; it may rename a cluster (or split
    one), it may never put two files the filenames keep apart into one. So the final grouping is
    compared with the deterministic one: any final key whose members carry more than one
    deterministic region is a fusion, and every override pointing into it (other than one that
    merely repeats its own deck's filename label, which cannot fuse anything) is refused. Iterated
    until stable, because a refused label falls back to its filename region, which can itself be
    the target of another label. Exact string keys, mirroring the `setdefault` that builds the
    clusters. Bounded: every round refuses at least one override or stops."""
    rejected: dict = {}
    for _round in range(len(overrides) + 1):
        groups: dict = {}
        for rel, _ext, stem in kept_brochures:
            key = (overrides[stem][0] if stem in overrides and stem not in rejected
                   else det[rel][0])
            groups.setdefault(key, []).append((rel, stem))
        fresh = False
        for key, members in groups.items():
            if len({det[rel][0] for rel, _s in members}) < 2:
                continue
            stems_in = sorted({s for _r, s in members})
            why = (f"would put {len(members)} deck files the filenames keep apart into one "
                   f"cluster ('{key}'): {', '.join(stems_in)}")
            for rel, stem in members:
                if (stem in overrides and stem not in rejected
                        and overrides[stem][0] == key and det[rel][0] != key):
                    rejected[stem] = (key, why)
                    fresh = True
        if not fresh:
            break
    return rejected


# 2026-09-26 test run, fix 3.1 / 1.3: the Stage-0 cluster-label cache and its decline sentinel.
# Both .SKIP spellings count, the same tolerance the tracker map's decline already has (an
# "empty file at the output path with a .SKIP suffix" is read both ways by people).
CLUSTER_CACHE = "intake_clusters.json"
CLUSTER_SKIP = ("intake_clusters.SKIP", "intake_clusters.json.SKIP")


def cluster_labels_declined(work) -> bool:
    """True when the broker/orchestrator declined LLM cluster labels (a .SKIP sentinel)."""
    try:
        return any((Path(work) / n).exists() for n in CLUSTER_SKIP)
    except Exception:
        return False


def cluster_cache_stamp(work) -> str:
    """sha1(bytes of work/intake_clusters.json)[:12]; "" when absent, unreadable or declined.

    Written into inventory.json as `cluster_cache_sha` by intake main, and compared by run.py's
    folder-scan resume check. The resume predicate SKIPS a missing input, so deleting the cache
    never made inventory.json stale and a fused label outlived the file that made it (fix 3.1).
    One function computes the stamp on both sides so they cannot disagree about the recipe."""
    try:
        if cluster_labels_declined(work):
            return ""
        f = Path(work) / CLUSTER_CACHE
        if not f.is_file():
            return ""
        return hashlib.sha1(f.read_bytes()).hexdigest()[:12]
    except Exception:
        return ""


def cluster_labels_opted_in(cfg) -> bool:
    """`inputs.cluster_labels: agent` in project.yaml - the ONLY way the label job is dispatched.

    2026-09-26 test run, fix 1.3: the auto-dispatched job cost 74k tokens for 7 stems and changes
    no card field (labels are routing names; the readers read the country off the deck, and
    geocoding keys on each record's own address). Anything unreadable = not opted in, which is
    the deterministic filename label - the no-LLM path every offline run already takes."""
    try:
        v = ((cfg or {}).get("inputs") or {}).get("cluster_labels")
        return str(v or "").strip().lower() == "agent"
    except Exception:
        return False


def _human_date(v) -> str:
    try:
        import master_list as _ML
        return _ML.human_date(v) or str(v or "")
    except Exception:
        return str(v or "")


def cluster_label_stems_block(inv: dict, work=None, stems=None, cap: int = 40) -> str:
    """The rendered STEMS slot of prompts/cluster-labels.md: one line per stem, EVERYTHING the
    run knows about it, so the agent never has to open the 36 KB inventory.json (fix 1.3).

      - "<stem>" | file: <inputs-relative path(s)> | arrived with: "<subject>" (<email file>,
        <7 Sep 2026>[, <sender>]) | filename label now: "<region>"

    `stems` defaults to the low-confidence stems. Capped at `cap` lines; the remainder is NAMED
    on one line, never silently cut. The sender comes from master_candidates_auto.json's email
    index when that file exists (it is written later in a pass, so the first pass may lack it)."""
    clusters = {k: c for k, c in ((inv or {}).get("clusters") or {}).items() if isinstance(c, dict)}
    if stems is None:
        stems = sorted({str(s) for c in clusters.values() if c.get("confidence") == "low"
                        for s in (c.get("stems") or [])})
    stems = [str(s) for s in stems]
    files_of: dict = {}
    region_of: dict = {}
    for region, c in sorted(clusters.items()):
        for f in [*(c.get("pdfs") or []), *(c.get("pptxs") or [])]:
            st = Path(str(f)).stem
            files_of.setdefault(st, []).append(str(f))
            region_of.setdefault(st, str(region))
    carrier: dict = {}  # attachment path (lower) -> email_attachments entry
    for e in ((inv or {}).get("email_attachments") or []):
        if not isinstance(e, dict):
            continue
        for s in (e.get("saved") or []):
            f = s.get("file") if isinstance(s, dict) else s
            if f:
                carrier[str(f).replace("\\", "/").lower()] = e
    senders: dict = {}
    if work is not None:
        try:
            auto = json.loads((Path(work) / "master_candidates_auto.json")
                              .read_text(encoding="utf-8-sig"))
            for m in (auto.get("emails") or []):
                if isinstance(m, dict) and m.get("sender"):
                    senders[str(m.get("email_file") or "").lower()] = str(m["sender"])
        except Exception:
            senders = {}
    lines = []
    for st in stems[:cap]:
        fs = files_of.get(st) or []
        parts = [f'- "{st}"', "file: " + (", ".join(fs) if fs else "(not on disk)")]
        em = next((carrier[f.lower()] for f in fs if f.lower() in carrier), None)
        if em:
            who = senders.get(str(em.get("email") or "").lower(), "")
            bits = [str(em.get("email") or "")]
            d = _human_date(em.get("date"))
            if d:
                bits.append(d)
            if who:
                bits.append(who)
            parts.append(f'arrived with: "{em.get("subject") or ""}" ({", ".join(b for b in bits if b)})')
        parts.append(f'filename label now: "{region_of.get(st, "")}"')
        lines.append(" | ".join(parts))
    if len(stems) > cap:
        rest = stems[cap:]
        lines.append(f"- (+{len(rest)} more low-confidence stem(s), not labelled this round: "
                     + ", ".join(f'"{s}"' for s in rest) + ")")
    return "\n".join(lines)


def cluster_label_job(inv: dict, cfg, work):
    """The cluster-labels job's slots, or None when the job must not be dispatched.

    None unless ALL hold: project.yaml opts in (`inputs.cluster_labels: agent`), no .SKIP
    sentinel, no cache written yet, at least one low-confidence stem, and a brochure-set hash to
    key the cache on. Fail-safe: any error -> None (the deterministic label stands)."""
    try:
        if not cluster_labels_opted_in(cfg) or cluster_labels_declined(work):
            return None
        if (Path(work) / CLUSTER_CACHE).exists():
            return None
        low = sorted({str(s) for c in ((inv or {}).get("clusters") or {}).values()
                      if isinstance(c, dict) and c.get("confidence") == "low"
                      for s in (c.get("stems") or [])})
        cih = str((inv or {}).get("cluster_input_hash") or "")
        if not low or not cih:
            return None
        return {"STEMS": cluster_label_stems_block(inv, work, low),
                "OUTPUT_PATH": str(Path(work) / CLUSTER_CACHE),
                "CLUSTER_INPUT_HASH": cih}
    except Exception:
        return None


# 2026-09-26 test run, fix 3.24: Windows MAX_PATH. Without the LongPathsEnabled policy a path of
# 260+ characters (a deep OneDrive project plus a subject-named attachment folder reaches it)
# cannot be listed, stat'ed or opened: rglob silently skipped the directory and 7 of 23 PDFs and
# 13 of 16 emails vanished from a scratch copy with no line printed. The extended-length prefix
# (\\?\) lifts the limit, so it is used to SEE those files. They are then reported, not ingested:
# every later stage (the extractors, the renderers, the resume check) opens `folder / rel` with
# no prefix and would fail on them one by one, further from the cause. No effect off Windows.
_LONG_PATH_REMEDY = ("move the project folder to a shorter path (for example directly under "
                     "C:\\ or a short OneDrive folder) and run again")


def _extended(p: str) -> str:
    """The Windows extended-length spelling of a path (\\\\?\\C:\\... or \\\\?\\UNC\\srv\\share\\...)."""
    s = os.path.abspath(p)
    if s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def _unreadable_long_paths(folder: Path, seen: set, exclude_dir=None) -> list:
    """[{file, chars}] for every file the extended-length walk finds that the normal walk could
    not: listed only through the \\\\?\\ prefix, so no stage of the run can open it. Same skips as
    discover's walk (dot/underscore parts, Office ~$ locks, the work dir, a prior run's output).
    Windows only; [] elsewhere, and [] on any error (the caller prints that it was skipped)."""
    if os.name != "nt":
        return []
    root = _extended(str(folder))
    excl = os.path.normcase(_extended(str(exclude_dir))) if exclude_dir else ""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in dirnames:
            if d.startswith((".", "_")):
                continue
            if excl and os.path.normcase(os.path.join(dirpath, d)) == excl:
                continue
            keep.append(d)
        dirnames[:] = keep
        rel_dir = dirpath[len(root):].strip("\\/").replace("\\", "/")
        for fn in filenames:
            if fn.startswith(("~$", ".", "_")):
                continue
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            if rel in seen or _is_own_output(rel):
                continue
            normal = os.path.join(os.path.abspath(str(folder)), *rel.split("/"))
            try:
                os.stat(normal)
                continue  # reachable the normal way after all (created mid-walk): not a loss
            except OSError:
                pass
            out.append({"file": rel, "chars": len(normal)})
    return sorted(out, key=lambda d: d["file"])


def long_path_warning(inv: dict) -> str:
    """The ONE loud line for inventory["unreadable_long_paths"], or "" when there are none.
    intake prints it; run.py may print it on every pass from the inventory (fix 3.24)."""
    lp = [d for d in ((inv or {}).get("unreadable_long_paths") or []) if isinstance(d, dict)]
    if not lp:
        return ""
    names = ", ".join(str(d.get("file")) for d in lp[:3]) + (" ..." if len(lp) > 3 else "")
    return (f"WARNING: {len(lp)} input file(s) sit on a path longer than Windows allows "
            f"(260 characters), so NO stage of this run can open them and they are NOT in it: "
            f"{names}. Remedy: {_LONG_PATH_REMEDY}.")


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


# ---------------------------------------------------------------- containers (zip, email)
# A broker forwards their whole option folder as ONE .zip, and an Outlook export of a filed
# mail folder is a .zip of .msg files. Both used to land in `unclassified`: the run printed
# "1 file could not be classified" and then "no readable property sources", over a zip holding
# nine brochures. Nobody reads that as data loss, because nothing was lost from the FOLDER;
# it was lost from the RUN. So a zip is now a first-class input, opened here before anything
# is classified, and what comes out is classified exactly as if the broker had dropped the
# loose files in themselves.
_ARCHIVE_EXT = (".zip",)
_UNPACK_SUFFIX = "_unpacked"
_UNPACK_MARKER = ".unpacked.json"
# ONE level of nesting. A zip of zips is a real shape (one archive per city), a zip of zips of
# zips is not, and an unbounded recursion here is a zip bomb with a polite name.
_UNPACK_MAX_DEPTH = 1
# Refusal thresholds, not tuning knobs. 2 GB uncompressed and 5000 members are both far above
# any real option folder (the largest measured broker export was 310 MB / 94 files) and far
# below the point at which the sandbox's disk or the Windows directory walk gives out. A zip
# past either is REFUSED WITH A REASON rather than half-extracted: a half-extracted archive is
# the worst outcome, because the run then ships some of the options and says nothing.
_ZIP_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_ZIP_MAX_MEMBERS = 5000


def _zip_signature(zf) -> str:
    """A cheap, content-derived identity for a zip: every member's name, size and CRC.

    Read from the CENTRAL DIRECTORY, so it costs no decompression and no whole-file read.
    Deliberately not the zip's mtime: the resume guard rewrites inventory.json whenever the
    inputs folder's mtime moves, so an mtime key would re-extract a 300 MB export on every
    pass of a run that already exits and re-enters a dozen times.
    """
    return hashlib.sha1("\n".join(
        f"{i.filename}|{i.file_size}|{i.CRC}" for i in zf.infolist()
    ).encode("utf-8", "replace")).hexdigest()[:16]


def _safe_extract_target(root: Path, member_name: str):
    """The resolved path a zip member may be written to, or None if it escapes `root`.

    ZIP-SLIP. A member named `../../../../Users/x/AppData/Roaming/...` is extracted by a naive
    extractall straight outside the inputs folder, and the classic malicious payload is a
    Windows startup-folder script. This is not hypothetical for us: the inputs of this skill
    are archives forwarded by third parties through email, which is precisely the untrusted
    channel the attack assumes. Absolute members and drive-letter members escape the same way
    and are refused by the same test, because both resolve outside `root`.
    """
    name = str(member_name or "").replace("\\", "/").lstrip("/")
    if not name or name.endswith("/"):
        return None
    try:
        target = (root / name).resolve()
        target.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return target


def _unpack_one(zpath: Path, folder: Path) -> dict:
    """Unpack ONE zip into `<zipname>_unpacked` beside it. Idempotent, never destructive."""
    import zipfile
    rel = zpath.relative_to(folder).as_posix()
    dest = zpath.parent / (zpath.stem + _UNPACK_SUFFIX)
    rec = {"archive": rel, "unpacked_to": dest.relative_to(folder).as_posix() if dest != folder
           else "", "members": 0, "skipped_unsafe": [], "status": "unpacked"}
    try:
        with zipfile.ZipFile(zpath) as zf:
            infos = zf.infolist()
            sig = _zip_signature(zf)
            marker = dest / _UNPACK_MARKER
            if marker.exists():
                try:
                    prev = json.loads(marker.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    prev = {}
                if prev.get("signature") == sig:
                    # Already unpacked and CURRENT. Say so and touch nothing: re-extracting
                    # would rewrite every brochure's mtime, which invalidates the per-file
                    # extract cache and makes a resumed run re-read decks it already read.
                    rec.update({"status": "current",
                                "members": int(prev.get("members") or 0)})
                    return rec
            total = sum(max(0, i.file_size) for i in infos)
            if len(infos) > _ZIP_MAX_MEMBERS or total > _ZIP_MAX_TOTAL_BYTES:
                rec.update({"status": "refused",
                            "reason": f"{len(infos)} members / {total // (1024 * 1024)} MB "
                                      f"uncompressed exceeds the {_ZIP_MAX_MEMBERS} member / "
                                      f"{_ZIP_MAX_TOTAL_BYTES // (1024 ** 3)} GB cap - nothing "
                                      f"was extracted; unzip it by hand if it is genuine"})
                return rec
            dest.mkdir(parents=True, exist_ok=True)
            n = 0
            for info in infos:
                if info.is_dir():
                    continue
                target = _safe_extract_target(dest, info.filename)
                if target is None:
                    rec["skipped_unsafe"].append(info.filename)
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and target.stat().st_size == info.file_size:
                        n += 1
                        continue   # already there, same size: leave the mtime alone
                    with zf.open(info) as src:
                        target.write_bytes(src.read())
                    n += 1
                except OSError as e:
                    rec.setdefault("errors", []).append(f"{info.filename}: {e}")
            rec["members"] = n
            try:
                marker.write_text(json.dumps({"signature": sig, "members": n},
                                             ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass   # no marker means the next run re-extracts, which is merely slow
    except Exception as e:
        rec.update({"status": "refused", "reason": f"not a readable zip: {e}"})
    return rec


def unpack_archives(folder: Path, exclude_dir=None) -> list:
    """Unpack every zip in the inputs folder (one level of nesting), idempotently.

    Runs BEFORE classification so the contents are discovered on the SAME run. Returns one
    record per archive; the caller publishes them in inventory.json so a refused or
    partially-extracted archive is visible to the broker and to the gates instead of being a
    file that quietly produced nothing.
    """
    out: list = []
    if not folder.is_dir():
        return out
    try:
        excl = Path(exclude_dir).resolve() if exclude_dir else None
    except OSError:
        excl = None

    def _eligible(p: Path) -> bool:
        if p.suffix.lower() not in _ARCHIVE_EXT or not p.is_file():
            return False
        parts = p.relative_to(folder).parts
        # Same skip rules the classifier uses, so an archive parked in `_originals/` stays
        # parked: a leading underscore is the documented way to take a duplicate out of scope,
        # and unpacking one would put the duplicate straight back in.
        if any(s.startswith((".", "_")) for s in parts) or p.name.startswith("~$"):
            return False
        if _is_own_output("/".join(parts)):
            return False
        if excl is not None:
            try:
                p.resolve().relative_to(excl)
                return False
            except (ValueError, OSError):
                pass
        return True

    seen: set = set()
    frontier = [p for p in sorted(folder.rglob("*")) if _eligible(p)]
    for depth in range(_UNPACK_MAX_DEPTH + 1):
        nxt: list = []
        for z in frontier:
            key = z.resolve().as_posix() if z.exists() else z.as_posix()
            if key in seen:
                continue
            seen.add(key)
            rec = _unpack_one(z, folder)
            rec["depth"] = depth
            out.append(rec)
            if depth < _UNPACK_MAX_DEPTH and rec["status"] in ("unpacked", "current"):
                sub = z.parent / (z.stem + _UNPACK_SUFFIX)
                if sub.is_dir():
                    nxt += [p for p in sorted(sub.rglob("*")) if _eligible(p)]
        frontier = nxt
        if not frontier:
            break
    return out


def harvest_email_attachments(folder: Path, enabled: bool = True) -> list:
    """Save every .msg/.eml attachment beside its email, before classification.

    Delegated to `extract_email.harvest_folder` so there is ONE implementation of the inline
    filter, the naming and the sidecar; intake owns only the decision to run it. `enabled` is
    False when project.yaml says `inputs.emails.source: none`, which is what the kato-longlist
    wrapper sets after doing this work itself - reading the same export twice writes a second
    copy of every brochure, and the second copy does not merge with the first, it clusters as
    its own option and the client sees the same building on two cards.
    """
    try:
        import extract_email as EM
    except Exception as e:
        return [{"email": "(all)", "declared": None, "saved": [], "skipped_inline": [],
                 "error": f"extract_email could not be imported: {e}"}]
    return EM.harvest_folder(Path(folder), save_attachment_bytes=enabled)


def discover(folder: Path, cluster_cache=None, exclude_dir=None,
             email_attachments: bool = True) -> dict:
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
    falls back to infer_cluster VERBATIM, so an offline / no-LLM run is unchanged.

    CONTAINERS ARE OPENED FIRST. Zips are unpacked and email attachments are saved BEFORE
    the walk, so a brochure that arrived inside an archive or stapled to a .msg is
    discovered, clustered and read on THIS run. Doing either afterwards would mean the file
    needed a second run to appear, and a silent two-run requirement is how an option goes
    missing from a pack nobody re-ran."""
    archives = unpack_archives(folder, exclude_dir=exclude_dir)
    email_atts = harvest_email_attachments(folder, enabled=email_attachments)
    lib = _poi_lib()
    cc = lib.get("city_country", {})
    inv = {"folder": str(folder), "clusters": {}, "xlsx": [], "images": [],
           "emails": [], "present_types": [], "subfolders": [], "skipped_outputs": [],
           # The containers, published so a refused archive or a failed attachment save is
           # visible to the broker AND to gate_runner's input-accounting. An archive that
           # produced nothing used to be indistinguishable from an archive nobody sent.
           "archives": archives, "email_attachments": email_atts,
           "email_attachments_enabled": bool(email_attachments),
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
    _seen_rel: set = set()  # fix 3.24: every file the NORMAL walk could stat
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        _seen_rel.add(p.relative_to(folder).as_posix())
        if p.name.startswith("~$") \
                or any(part.startswith((".", "_")) for part in p.relative_to(folder).parts):
            continue
        if _under_workdir(p):
            _n_excluded += 1
            continue
        _cands.append(p)
    files = sorted(_cands, key=lambda p: p.relative_to(folder).as_posix())
    # fix 3.24: always present (empty off Windows and on short paths), so a reader never has to
    # guess whether the key exists. input-accounting may list it; intake main prints the line.
    try:
        inv["unreadable_long_paths"] = _unreadable_long_paths(folder, _seen_rel, _excl)
    except Exception as _e:
        inv["unreadable_long_paths"] = []
        print(f"  (long-path check skipped: {type(_e).__name__}: {_e})")
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
        elif ext in _ARCHIVE_EXT:
            # A CONTAINER, not an input. It was opened by unpack_archives above and its
            # contents are being classified individually in this same loop, so listing it
            # under `unclassified` would report a file the run in fact read, and counting it
            # as an input would make input-accounting BLOCK on a zip that can never carry a
            # ledger row of its own. It is accounted for in inv["archives"].
            continue
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
    # fix 3.1: the deterministic label of EVERY kept brochure first, then the no-fuse rule over
    # the overrides. `cluster_label_rejected` is always present (empty without a cache).
    det = {rel: infer_cluster(Path(rel).name, cc) for rel, _ext, _stem in kept_brochures}
    inv["cluster_label_rejected"] = []
    try:
        _refused = _nofuse_rejections(kept_brochures, det, overrides) if overrides else {}
    except Exception as _e:
        # Fail SAFE: a filename label can never merge two decks, so dropping every override is
        # the one fallback that cannot reintroduce the defect this rule exists for.
        print(f"  (cluster labels NOT applied - the no-merge check failed: "
              f"{type(_e).__name__}: {_e}; every deck keeps its filename label)")
        _refused, overrides = {}, {}
    for _st, (_reg, _why) in sorted(_refused.items()):
        inv["cluster_label_rejected"].append({"stem": _st, "region": _reg, "why": _why})
    overrides = {k: v for k, v in overrides.items() if k not in _refused}
    for rel, ext, stem in kept_brochures:
        region, country, confidence = det[rel]
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


def _slug(raw) -> str:
    """deliver.safe_slug, imported lazily; an identical local copy if the import fails (fix 3.19)."""
    try:
        import deliver as _D
        return _D.safe_slug(raw)
    except Exception:
        s = re.sub(r"[^A-Za-z0-9]+", "_", str(raw or "")).strip("_")
        return s or "Longlist"


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
    # 2026-09-26 test run, fix 3.19: the client name is free text from the Stage-0 form. Raw in
    # the filename it produced `CBRE_Property_Dashboard_Example Ltd..html` (run.py honours
    # output.filename verbatim); raw as the YAML scalar, "Acme: Retail" or "#1 Logistics" is not
    # valid YAML. The filename takes deliver.safe_slug (the same slug run.py's blank-filename
    # fallback and the ledger/Gaps names use); the name is written as a JSON string, which is a
    # valid YAML double-quoted scalar and loads back byte-identical. New scaffolds only.
    client_yaml = json.dumps(str(client), ensure_ascii=False)
    client_slug = _slug(client)
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
  name: {client_yaml}
  confidential: true
market:
  title_html: ""                 # headline; blank renders the localised default, which names the client. Keep ONE <em>..</em> pair for the accent colour
  eyebrow: ""                    # e.g. "Property Shortlist · Spain"; blank renders the localised default. A value ships VERBATIM (write the full eyebrow)
  region_label: ""
  countries: {json.dumps(countries)}
output:
  filename: "CBRE_Property_Dashboard_{client_slug}.html"
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
  mode: interactive              # FIXED BY POLICY, not a Stage-0 question and not a guess
                                 # like the values above it: the run always asks the broker
                                 # when a judgement call affects what a card shows.
                                 # 'headless' (or assume_defaults: true / the SKIP_ALL
                                 # sentinel) keeps the default-honestly-and-disclose
                                 # contract, and exists only for a run with no human in it
"""


def _load_cluster_cache(outdir: Path):
    """Best-effort read of the optional work/intake_clusters.json (the orchestrator's
    LLM-refined filename->region labels). A missing / malformed file returns None so
    discover falls back to infer_cluster verbatim - never a traceback.

    2026-09-26 (fix 3.1): a .SKIP sentinel (intake_clusters.SKIP) declines the labels, so the
    cache is not applied even when it exists - the filename labels are re-derived."""
    if cluster_labels_declined(outdir):
        return None
    f = outdir / CLUSTER_CACHE
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


def _emails_source(outdir: Path) -> str:
    """`inputs.emails.source` from an EXISTING project.yaml, or "" when there is none.

    Read defensively and never fatally: this decides only whether attachments are harvested,
    and a malformed project.yaml already has a louder reporter than intake. Returning "" on
    any doubt keeps the DEFAULT behaviour (harvest), because the failure of not harvesting is
    a brochure missing from the pack, while the failure of harvesting when the wrapper already
    did is a duplicate the match stage surfaces loudly.
    """
    p = Path(outdir) / "project.yaml"
    if not p.exists():
        return ""
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
        return str((((cfg.get("inputs") or {}).get("emails") or {}).get("source")) or "").strip().lower()
    except Exception:
        return ""


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
    # `inputs.emails.source: none` is the wrapper-skill contract (kato-longlist unzips the
    # export and saves its attachments in its own email step before this skill ever runs).
    # Harvesting them again here would write a SECOND copy of every brochure into the inputs
    # folder, and the second copy does not merge with the first: it clusters as its own
    # option and the client sees the same building twice. Absent project.yaml means a first
    # pass on a plain folder, where harvesting is exactly what is wanted.
    inv = discover(folder, cluster_cache=_load_cluster_cache(outdir), exclude_dir=outdir,
                   email_attachments=_emails_source(outdir) != "none")
    # fix 3.1: the cache's byte stamp ("" = no cache / declined), so run.py's resume check can
    # see a deleted or declined cache - the resume predicate skips a missing input by design.
    inv["cluster_cache_sha"] = cluster_cache_stamp(outdir)
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
    _lpw = long_path_warning(inv)
    if _lpw:  # fix 3.24: one loud line, never a silent loss
        print(_lpw)
    _rej = [r for r in (inv.get("cluster_label_rejected") or []) if isinstance(r, dict)]
    if _rej:  # fix 3.1: a refused label is named, with the decks it would have merged
        _by_region: dict = {}
        for r in _rej:
            _by_region.setdefault(str(r.get("region") or ""), []).append(str(r.get("stem") or ""))
        print(f"NOTE: {len(_rej)} cluster label(s) refused - a label may rename a cluster, never "
              f"merge two decks the filenames keep apart: "
              + "; ".join(f"{reg} ({', '.join(sts)})" for reg, sts in sorted(_by_region.items())))
    if cluster_labels_declined(outdir) and (outdir / CLUSTER_CACHE).exists():
        print(f"NOTE: {CLUSTER_SKIP[0]} is present, so work/{CLUSTER_CACHE} is NOT applied - "
              f"every deck keeps its filename label.")
    for a in inv.get("archives") or []:
        if a.get("status") == "refused":
            print(f"WARNING: {a['archive']} was NOT unpacked: {a.get('reason')}. Nothing inside "
                  f"it is in this run.")
        elif a.get("status") == "current":
            print(f"NOTE: {a['archive']} already unpacked and unchanged -> "
                  f"{a.get('unpacked_to')}/ ({a.get('members')} file(s), left untouched)")
        else:
            print(f"NOTE: unpacked {a['archive']} -> {a.get('unpacked_to')}/ "
                  f"({a.get('members')} file(s){', nested' if a.get('depth') else ''})")
        if a.get("skipped_unsafe"):
            # A member whose path escapes the inputs folder is refused and NAMED. Silence here
            # would be the wrong trade twice over: a benign archive built with odd relative
            # paths looks fine while losing files, and a hostile one gets to try again quietly.
            print(f"WARNING: {len(a['skipped_unsafe'])} member(s) of {a['archive']} name paths "
                  f"OUTSIDE the inputs folder and were refused (zip-slip): "
                  f"{', '.join(a['skipped_unsafe'][:4])}")
    _ea = inv.get("email_attachments") or []
    _n_saved = sum(len(e.get("saved") or []) for e in _ea)
    _n_inline = sum(len(e.get("skipped_inline") or []) for e in _ea)
    if _n_saved or _n_inline:
        print(f"NOTE: saved {_n_saved} email attachment(s) beside their emails and skipped "
              f"{_n_inline} inline image(s) (signature logos). The saved files are classified "
              f"and routed in this same run, exactly like a brochure dropped in the folder.")
    for e in _ea:
        if e.get("error"):
            print(f"WARNING: {e.get('email')}: attachments NOT extracted - {e['error']}. Any "
                  f"brochure attached to this email is NOT in the run; input-accounting blocks "
                  f"on it rather than letting the body's records stand in for the file.")
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
