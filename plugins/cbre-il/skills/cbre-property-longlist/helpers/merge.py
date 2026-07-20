#!/usr/bin/env python3
# © 2026 Timo Baaij (timo.baaij@cbre.com). All rights reserved. (see NOTICE)
"""merge.py - Stage 2. Combine candidate records into the canonical dataset.

Reads one or more extractor record files, dedupes cross-source duplicates
(match.py), merges each cluster by field-class source precedence, assigns stable
ids, attaches a compressed base64 hero image per property (a PPTX slide picture
if one was extracted, else a brochure PDF-page raster, else a placeholder),
seeds POIs from the library, and writes canonical.json plus a field-level
source_ledger.csv.

Precedence:
  commercial fields (rent/terms/incentives/land): newest email > excel > brochure
  physical specs / geo / everything else:          brochure (pdf>pptx) > excel > email

CLI:
  python merge.py --records a.json b.json --source-dir <folder> \
                  --project-yaml project.yaml --out canonical.json [--ledger ledger.csv]
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C
import match
import normalize as N
import images as IMG
import extract_pdf as XP  # best_description_in_deck for the photo-match path
import i18n as I18N        # Phase 2: EN key whitelist for the --ui-overrides bake

COMMERCIAL = {"warehouseRent", "warehouseRentVal", "officeRent", "serviceCharge",
              "leaseTerm", "rentFree", "incentives", "landPrice"}

# lower rank = preferred
SPEC_RANK = {"pdf": 0, "pptx": 1, "xlsx": 2, "msg": 3, "email": 3, "image": 4, "web": 5}
COMM_RANK = {"email": 0, "msg": 0, "xlsx": 1, "pdf": 2, "pptx": 3, "image": 4, "web": 5}
# IMAGE-source preference (distinct from field precedence): a slide picture (PPTX)
# is higher-res than a PDF-page raster, so it outranks pdf here - the inverse of
# SPEC_RANK. PDF stays the preferred FIELD source.
IMG_RANK = {"pptx": 0, "image": 1, "pdf": 2, "web": 3, "xlsx": 4, "email": 5, "msg": 5}

# a seeded library POI farther than this from EVERY property is not this dataset's
# region (we never surface a 'nearest' POI beyond ~this range anyway), so it is
# dropped. Region-neutral: pure distance, no place names or country adjacency.
SEED_MAX_KM = 800


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _st(rec):  # source type
    return rec.get("__meta", {}).get("source_type", "pdf")


def _date(rec):
    return rec.get("__meta", {}).get("date", "")


def _normalise_offspec(rec: dict) -> dict:
    """Move off-spec STRUCTURES out of the record's top level into __meta.offspec BEFORE
    clustering, so they can never become a displayed field: (a) a dict/list whose key is
    NOT a canonical field (a stray provenance/meta map), or (b) a scalar whose value is a
    pipeline locator string. Genuine scalar attributes (canonical AND brand-new) and
    canonical container objects (gallery/preBaked/district) are KEPT so auto-show is
    preserved. Deterministic; a clean record is unchanged."""
    canon = C.canonical_property_fields()
    meta = rec.setdefault("__meta", {})
    for k in [k for k in rec if k != "__meta"]:
        v = rec[k]
        if (isinstance(v, (dict, list)) and k not in canon) or C.looks_like_locator(v):
            meta.setdefault("offspec", {})[k] = v
            del rec[k]
    return rec


_FILE_UNRELIABLE: dict[str, bool] = {}


def compute_file_quality(records: list[dict]) -> dict[str, bool]:
    """Mark each BROCHURE source file (pdf/pptx) whose records MOSTLY parsed
    poorly - the same probe run.py routes files to vision with. Records from
    such a file lose every field-precedence contest to a cleaner twin:
    'PDF preferred for fields' holds only while the PDF parse is actually
    reliable (a print-export PDF with a flattened text layer used to outrank
    its clean PPTX twin on the static rank alone). Non-brochure sources
    (xlsx/email) keep their ranks - their records are legitimately sparse."""
    by_file: dict[str, list] = {}
    for r in records:
        meta = r.get("__meta", {}) or {}
        if meta.get("source_type") in ("pdf", "pptx"):
            by_file.setdefault(meta.get("source_file", ""), []).append(r)
    _FILE_UNRELIABLE.clear()
    for f, recs in by_file.items():
        poor = sum(1 for r in recs if C.record_is_poor(r))
        _FILE_UNRELIABLE[f] = bool(recs) and poor / len(recs) > 0.5
    return _FILE_UNRELIABLE


def _unreliable(r) -> bool:
    return _FILE_UNRELIABLE.get((r.get("__meta", {}) or {}).get("source_file", ""), False)


def dominant_units(records: list[dict]) -> tuple[str, str]:
    """The dataset's unit convention = the units MOST source records state
    (UK/imperial inputs ship imperial, metric inputs ship metric - user rule).
    Defaults: 'sq m' and '€/sq m/yr' when no record states a unit."""
    from collections import Counter
    a = Counter(r.get("areaUnit") for r in records
                if isinstance(r, dict) and r.get("areaUnit"))
    rn = Counter(r.get("rentUnit") for r in records
                 if isinstance(r, dict) and r.get("rentUnit"))
    return (a.most_common(1)[0][0] if a else "sq m",
            rn.most_common(1)[0][0] if rn else "€/sq m/yr")


# structured spec fields a RICH building tracker (>=8 mapped columns,
# __meta.tracker_rich) is more authoritative on than a marketing brochure:
# curated internal data beats brochure prose for measured values. Naming and
# narrative (park, city, developer, description) stay brochure-first.
TRACKER_AUTHORITATIVE = {
    "warehouseArea", "plotArea", "officeArea", "clearHeight", "floorLoad",
    "loadingDocks", "overheadDoors", "electricity", "truckParking", "carParking",
    "breeam", "lat", "lng", "status", "earlyAccess", "areaUnit",
}


def _is_rich(r) -> bool:
    return bool(r.get("__meta", {}).get("tracker_rich"))


# ----- cross-source VALUE-conflict adjudication (#4) ----------------------- #
# A genuine conflict is a field where >= 2 cluster records hold DIFFERENT
# non-unknown values. The fixed precedence above is the DEFAULT winner; an
# isolated sub-agent may OVERRIDE it with one of the given candidate values, but
# ONLY when the picked value passes the field's deterministic plausibility gate.
# The decision is cached (work/field_decisions.json) keyed by a stable,
# order-independent conflict_id, so merge reads it offline and never calls an LLM
# live (byte-identical resume). Mirrors the match grey-pair / pair_id contract.

# fields whose override is gate-VERIFIED before it is honoured. A field absent
# from this map falls back to precedence on any pick (it can still be annotated).
_RENT_GATE_FIELDS = {"warehouseRent", "warehouseRentVal", "officeRent"}
_AREA_GATE_FIELDS = {"warehouseArea", "plotArea", "officeArea", "officeAreaVal"}


def _pick_passes_gate(field: str, value, rent_unit: str | None,
                      area_unit: str | None = None) -> bool:
    """Run a candidate VALUE through its field's deterministic plausibility check
    before an LLM override is honoured (the verifier from the #4 design). A rent
    must sit in its own per-area band (and a numeric must parse), an area must be
    > 0 AND inside its conservative plausibility band (the area twin of the rent
    band; the picked record's areaUnit chooses the band, else the sq m band), a
    coordinate must be in bounds. A field with NO defined gate returns False so
    precedence stands (the override is never honoured, only annotated). A pick that
    fails is DISCARDED and the fixed precedence is kept (it NEVER blocks the build)."""
    if field in _RENT_GATE_FIELDS:
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else N.extract_first_number(str(value))
        if num is None:
            return False
        unit = rent_unit or (N.rent_unit_of_text(str(value)) if isinstance(value, str) else None)
        lo, hi = N.rent_unit_band(unit)
        return lo <= num <= hi
    if field in _AREA_GATE_FIELDS:
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else N.extract_first_number(str(value))
        if num is None or num <= 0:
            return False
        lo, hi = N.area_band_for(area_unit)
        return lo <= num <= hi
    if field in ("lat", "lng"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        return (-90 <= value <= 90) if field == "lat" else (-180 <= value <= 180)
    return False  # no defined gate -> precedence stands (the pick can only annotate)


def conflict_id(cluster_key: str, field: str, values: list) -> str:
    """A STABLE, ORDER-INDEPENDENT id for a value conflict: a sha1 of the merged
    property's match_key + field + the SORTED set of disagreeing values. The id
    depends ONLY on the conflict's content (identity + field + the value set), not
    on record-file order, so a cached verdict in work/field_decisions.json keyed by
    it is reproducible across re-runs. Mirrors match.pair_id."""
    import hashlib
    parts = chr(0).join(sorted(str(v) for v in values))
    raw = f"{cluster_key}|{field}|{parts}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _ordered_for_field(field, cluster, comm_order, spec_order, tracker_order, has_rich):
    """The precedence order merge_cluster applies for one field (single source of
    truth so conflict_candidates and merge_cluster agree on the default winner)."""
    if field in COMMERCIAL:
        return comm_order
    if has_rich and field in TRACKER_AUTHORITATIVE:
        return tracker_order
    return spec_order


def conflict_candidates(clusters: list[list[dict]]) -> list[dict]:
    """Enumerate EVERY genuine cross-source value conflict across the clusters,
    PURE PYTHON (no LLM). A conflict = a field where >= 2 records in one cluster
    hold DIFFERENT non-unknown values (the exact looks_unknown test merge_cluster
    uses). Deterministic: clusters in order, sorted(fields), a content-keyed id.
    Returns one dict per conflict with the candidate values + their source meta +
    the precedence-winner `default` label, ready for work/match_candidates.json's
    `field_conflicts` array. Typically 0-3 per run (like grey pairs)."""
    out: list[dict] = []
    for cl in clusters:
        if len(cl) < 2:
            continue  # a <=1-record cluster can hold no value conflict (needs >=2 disagreeing records) - #44
        comm_order = sorted(cl, key=lambda r: (COMM_RANK.get(_st(r), 9), _unreliable(r), -_datekey(r)))
        spec_order = sorted(cl, key=lambda r: (_unreliable(r), SPEC_RANK.get(_st(r), 9)))
        tracker_order = sorted(cl, key=lambda r: (not _is_rich(r), _unreliable(r),
                                                  SPEC_RANK.get(_st(r), 9)))
        has_rich = any(_is_rich(r) for r in cl)
        merged_key = match.match_key(cl[0]) if cl else ""
        fields = set()
        for r in cl:
            fields.update(k for k in r if k != "__meta")
        for field in sorted(fields):
            order = _ordered_for_field(field, cl, comm_order, spec_order, tracker_order, has_rich)
            cands: list[dict] = []
            seen_vals: set = set()
            for r in order:
                if field not in r:
                    continue
                v = r[field]
                if N.looks_unknown(v) and field not in ("landPrice", "reit"):
                    continue
                if str(v) in seen_vals:
                    continue  # the same value from two records is not a disagreement
                seen_vals.add(str(v))
                meta = r.get("__meta", {})
                st = meta.get("source_type", "")
                cands.append({
                    "label": chr(ord("a") + len(cands)),
                    "value": v,
                    "source_type": st,
                    "date": meta.get("date", ""),
                    "locator": meta.get("prov", {}).get(field, meta.get("locator_base", "")),
                    "source_file": meta.get("source_file", ""),
                    "prov_tag": ("vision transcription" if "vision" in str(
                        meta.get("prov", {}).get(field, "")).lower()
                        else "text interpretation" if "interpretation" in str(
                        meta.get("prov", {}).get(field, "")).lower()
                        else st),
                    "precedence_rank": len(cands),
                })
            if len(cands) < 2:
                continue  # not a genuine conflict (one or zero distinct non-unknown values)
            values = [c["value"] for c in cands]
            out.append({
                "conflict_id": conflict_id(merged_key, field, values),
                "cluster_key": merged_key,
                "field": field,
                "candidates": cands,
                "default": cands[0]["label"],  # the precedence winner (order[0])
            })
    return out


def merge_cluster(cluster: list[dict], decisions: dict | None = None) -> tuple[dict, dict, dict]:
    out: dict = {}
    prov: dict = {}
    conflicts: dict = {}  # field -> "discarded <val> from <file> (kept <winner>)"
    # newest email wins among commercials (rank 0, date desc); brochure wins for
    # specs - but an UNRELIABLE brochure (mostly-poor parse) loses to any cleaner
    # source, so a garbled PDF cannot outrank its clean PPTX twin on rank alone;
    # and a RICH tracker leads the structured spec fields + coordinates
    comm_order = sorted(cluster, key=lambda r: (COMM_RANK.get(_st(r), 9), _unreliable(r), -_datekey(r)))
    spec_order = sorted(cluster, key=lambda r: (_unreliable(r), SPEC_RANK.get(_st(r), 9)))
    tracker_order = sorted(cluster, key=lambda r: (not _is_rich(r), _unreliable(r),
                                                   SPEC_RANK.get(_st(r), 9)))
    has_rich = any(_is_rich(r) for r in cluster)
    cluster_key = match.match_key(cluster[0]) if cluster else ""
    # rent-unit hint for the per-field plausibility gate (the cluster's stated unit,
    # else the €/sq m default) - so a £/sq ft override is judged against its own band.
    rent_unit = next((r.get("rentUnit") for r in cluster if r.get("rentUnit")), None)

    fields = set()
    for r in cluster:
        fields.update(k for k in r if k != "__meta")

    for field in sorted(fields):  # sorted -> deterministic output bytes
        order = _ordered_for_field(field, cluster, comm_order, spec_order, tracker_order, has_rich)
        chosen = None
        # candidate records that hold a distinct non-unknown value, in precedence
        # order (used both for the discard note and the override lookup)
        cand_recs: list[dict] = []
        seen_vals: set = set()
        for r in order:
            if field not in r:
                continue
            v = r[field]
            if N.looks_unknown(v) and field not in ("landPrice", "reit"):
                continue
            meta = r.get("__meta", {})
            if chosen is None:
                chosen = v
                out[field] = v
                prov[field] = {
                    "source_file": meta.get("source_file", ""),
                    "source_type": meta.get("source_type", ""),
                    "locator": meta.get("prov", {}).get(field, meta.get("locator_base", "")),
                }
            elif str(v) != str(chosen):
                # a different non-unknown value lost the precedence contest - record it
                conflicts[field] = (f"discarded '{v}' from {meta.get('source_file','?')} "
                                    f"(kept '{chosen}')")
            if str(v) not in seen_vals:
                seen_vals.add(str(v))
                cand_recs.append(r)
        # LLM VALUE-CONFLICT OVERRIDE (#4): a GENUINE conflict (>= 2 distinct non-
        # unknown values) may carry a cached sub-agent pick keyed by an order-
        # independent conflict_id. The precedence winner (chosen) is the DEFAULT; the
        # pick OVERRIDES it ONLY when (a) it selects one of the given candidate values
        # AND (b) that value PASSES the field's deterministic plausibility gate. A
        # pick that fails the gate, names no candidate, or selects the default is
        # ignored and precedence stands. SELECTION-ONLY: never a free/invented value.
        if decisions and len(cand_recs) >= 2:
            values = [c[field] for c in cand_recs]
            cid = conflict_id(cluster_key, field, values)
            verdict = decisions.get(cid)
            if isinstance(verdict, dict):
                pick = verdict.get("pick")
                reason = verdict.get("reason", "")
            else:
                pick, reason = (verdict, "") if isinstance(verdict, str) else (None, "")
            # labels are assigned a,b,c,... in precedence order, matching conflict_candidates
            labels = [chr(ord("a") + i) for i in range(len(cand_recs))]
            if pick in labels and pick != labels[0]:  # a non-default candidate pick
                picked = cand_recs[labels.index(pick)]
                pv = picked[field]
                if _pick_passes_gate(field, pv, rent_unit, picked.get("areaUnit")):
                    out[field] = pv
                    pmeta = picked.get("__meta", {})
                    prov[field] = {
                        "source_file": pmeta.get("source_file", ""),
                        "source_type": pmeta.get("source_type", ""),
                        "locator": pmeta.get("prov", {}).get(field, pmeta.get("locator_base", "")),
                    }
                    conflicts[field] = (f"LLM override -> '{pv}' from "
                                        f"{pmeta.get('source_file','?')} (precedence default was "
                                        f"'{chosen}'){f': {reason}' if reason else ''}")
                else:
                    # the pick failed its plausibility gate - precedence stands, noted
                    conflicts[field] = (f"LLM pick '{pv}' rejected (failed {field} "
                                        f"plausibility gate); kept precedence '{chosen}'"
                                        + (f". {conflicts.get(field, '')}" if conflicts.get(field) else ""))
    return out, prov, conflicts


def _datekey(rec) -> float:
    d = _date(rec)
    try:
        return _dt.datetime.fromisoformat(d).timestamp()
    except Exception:
        pass
    try:  # RFC-2822 ("Mon, 12 May 2025 10:11:00 +0200") - raw email headers
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(d).timestamp()
    except Exception:
        return 0.0


_SRC_RESOLVE: dict[str, Path | None] = {}


def _resolve_source(source_dir: Path, name: str) -> Path | None:
    """A record's source_file is a bare filename, but inputs may live in subfolders
    (intake scans recursively) - resolve directly, then by recursive name search
    (memoised; name-equality walk, not rglob, so glob metacharacters in client
    filenames cannot break it). Without this, a subfolder brochure's hero image
    silently degraded to the placeholder."""
    if not name:
        return None
    if name in _SRC_RESOLVE:
        return _SRC_RESOLVE[name]
    cand = source_dir / name
    if not cand.is_file():
        cand = next((p for p in source_dir.rglob("*") if p.is_file() and p.name == name), None) \
            if source_dir.exists() else None
    _SRC_RESOLVE[name] = cand if (cand and cand.is_file()) else None
    return _SRC_RESOLVE[name]


def _meta_image_pages(meta: dict) -> list[int]:
    """The validated 0-based image_pages of a record's __meta: ints >= 0 only.
    A non-list, or any non-int / negative entry, is silently dropped (the
    validator surfaces those; merge must never crash on a malformed value).
    Absence -> [] so pages_by_src reduces to page_no-only (byte-identical)."""
    ip = meta.get("image_pages")
    if not isinstance(ip, list):
        return []
    return [p for p in ip if isinstance(p, int) and not isinstance(p, bool) and p >= 0]


def _cluster_pages_by_src(cluster: list[dict], source_dir: Path) -> dict[str, set]:
    """The deck pages this cluster lays claim to, keyed by resolved source path:
    each pdf/pptx record's page_no UNION its validated __meta.image_pages. Mirrors
    the union attach_media builds, so the guard and the harvester see the SAME set."""
    out: dict[str, set] = {}
    for r in cluster:
        m = r.get("__meta", {})
        if m.get("source_type") in ("pdf", "pptx") and isinstance(m.get("page_no"), int):
            s = _resolve_source(source_dir, m.get("source_file", ""))
            if s:
                slot = out.setdefault(str(s), set())
                slot.add(m["page_no"])
                slot.update(_meta_image_pages(m))
    return out


_PAGE_UNCLAIMED = object()  # sentinel: a (src,page) anchored by zero or >1 clusters - owned by nobody


def _deck_ownership(clusters: list[list[dict]], source_dir: Path):
    """Shared post-merge ownership over the deck pages (the unique-claimant guard's input).
    Returns (pages_per_cluster, anchor_owner, claims):
    - pages_per_cluster[i][src] = cluster i's claimed pages (page_no U image_pages).
    - anchor_owner[(src, p)] = the cluster whose record page_no == p; _PAGE_UNCLAIMED when
      zero or MORE THAN ONE cluster anchors there (a clustering anomaly -> un-owned).
    - claims[(src, p)] = the set of cluster indices whose (page_no U image_pages) include p."""
    pages_per_cluster = [_cluster_pages_by_src(cl, source_dir) for cl in clusters]
    anchor_owner: dict[tuple, object] = {}
    for i, cl in enumerate(clusters):
        for r in cl:
            m = r.get("__meta", {})
            if m.get("source_type") in ("pdf", "pptx") and isinstance(m.get("page_no"), int):
                s = _resolve_source(source_dir, m.get("source_file", ""))
                if not s:
                    continue
                key = (str(s), m["page_no"])
                if key not in anchor_owner:
                    anchor_owner[key] = i
                elif anchor_owner[key] != i:
                    anchor_owner[key] = _PAGE_UNCLAIMED  # >1 distinct cluster anchors here
    claims: dict[tuple, set] = {}
    for i, pbs in enumerate(pages_per_cluster):
        for s, pgs in pbs.items():
            for p in pgs:
                claims.setdefault((s, p), set()).add(i)
    return pages_per_cluster, anchor_owner, claims


def _page_allowed(i: int, s: str, p: int, anchor_owner: dict, claims: dict) -> bool:
    """A page p of deck s is ALLOWED for cluster i iff cluster i anchors it, OR it is
    anchored by nobody AND cluster i is its SOLE claimant; otherwise another property owns
    it (foreign)."""
    owner = anchor_owner.get((s, p), _PAGE_UNCLAIMED)
    return (owner == i) or (owner is _PAGE_UNCLAIMED and claims.get((s, p)) == {i})


def build_foreign_pages(clusters: list[list[dict]], source_dir: Path) -> list[dict[str, set]]:
    """UNIQUE-CLAIMANT GUARD (pure Python, deterministic over the post-merge clusters).
    Python ENFORCES that every deck page feeds AT MOST ONE property's carousel, so no
    brochure topology can cross-contaminate even if the LLM over-claims image_pages.

    Returns a list parallel to `clusters`: foreign[i][src] = the set of cluster i's OWN
    claimed pages that are FOREIGN to it (owned/claimed by another property) and must be
    subtracted before harvesting. The gallery + the deterministic plan fallback subtract it
    from the cluster's own pages. (The plan_page HINT may name ANY page, not just the
    cluster's own, so it uses the BROADER `plan_offlimits_pages` instead.)

    Backward-compat: with NO image_pages anywhere, each cluster's claimed pages are its
    own page_no(s) - distinct per property in a correctly-clustered deck - so claims[p]
    is a singleton on each cluster's own page and foreign[i] is empty everywhere. A
    cluster's own page_no is never foreign -> byte-identical harvest set."""
    pages_per_cluster, anchor_owner, claims = _deck_ownership(clusters, source_dir)
    foreign: list[dict[str, set]] = []
    for i, pbs in enumerate(pages_per_cluster):
        fmap: dict[str, set] = {}
        for s, pgs in pbs.items():
            bad = {p for p in pgs if not _page_allowed(i, s, p, anchor_owner, claims)}
            if bad:
                fmap[s] = bad
        foreign.append(fmap)
    return foreign


def plan_offlimits_pages(clusters: list[list[dict]], source_dir: Path) -> list[dict[str, set]]:
    """Per cluster, EVERY page of the decks it touches that is OWNED BY ANOTHER property -
    the off-limits set for the plan_page HINT. Unlike the gallery/fallback (which only
    subtract from a cluster's OWN claimed pages), an LLM plan_page may name ANY page, so the
    guard needs the full other-owned set to reject a neighbour's page. Same allow-rule as
    `build_foreign_pages`; broader page coverage (all pages any cluster claims/anchors on
    that src). A single-property deck yields an empty set (no other owner)."""
    pages_per_cluster, anchor_owner, claims = _deck_ownership(clusters, source_dir)
    pages_on_src: dict[str, set] = {}
    for (s, p) in claims:
        pages_on_src.setdefault(s, set()).add(p)
    for (s, p) in anchor_owner:
        pages_on_src.setdefault(s, set()).add(p)
    out: list[dict[str, set]] = []
    for i, pbs in enumerate(pages_per_cluster):
        omap: dict[str, set] = {}
        for s in pbs:  # only the sources this cluster actually touches
            bad = {p for p in pages_on_src.get(s, set())
                   if not _page_allowed(i, s, p, anchor_owner, claims)}
            if bad:
                omap[s] = bad
        out.append(omap)
    return out


def attach_media(cluster: list[dict], source_dir: Path, budget_kb: int,
                 image_cache: Path | None = None,
                 foreign_pages: dict[str, set] | None = None,
                 plan_offlimits: dict[str, set] | None = None,
                 plan_near_miss: list | None = None
                 ) -> tuple[str, str | None, dict | None, dict | None, list, list]:
    """(photo_uri, plan_uri, photo_rec, plan_rec, tried_pages, gallery) for a merged property.

    Photo precedence (honours 'PPTX is the preferred IMAGE source'): a picture an
    extractor already embedded on a record first, else the source page's hero
    via the engine-agnostic ladder - PDF pages AND PPTX slides both harvest
    (slide records, e.g. vision transcriptions of a deck, used to silently
    degrade to the placeholder because only the PDF branch existed). The SITE
    PLAN comes from a record-level
    'plan' data URI (orchestrator-bound standalone file) first, else the page's
    plan picker. Combination rules per the broker's brief: photo found -> photo
    is the hero and the plan fills the plan slot (or stays absent); plan-only
    page -> the plan IS the hero AND the plan slot; neither -> placeholder.
    photo_rec/plan_rec is None when the placeholder / no plan was used."""
    photo = plan = None
    photo_rec = plan_rec = None
    tried: list[tuple] = []  # (source path, page/slide no, kind) - the placeholder audit trail
    embedded = [r for r in cluster
                if isinstance(r.get("photo"), str) and r["photo"].startswith("data:image/")]
    if embedded:
        embedded.sort(key=lambda r: IMG_RANK.get(_st(r), 9))
        photo, photo_rec = embedded[0]["photo"], embedded[0]
    bound_plans = [r for r in cluster
                   if isinstance(r.get("plan"), str) and r["plan"].startswith("data:image/")]
    if bound_plans:
        bound_plans.sort(key=lambda r: IMG_RANK.get(_st(r), 9))  # source-quality order, like the hero
        plan, plan_rec = bound_plans[0]["plan"], bound_plans[0]
    for r in cluster:
        if photo is not None and plan is not None:
            break
        meta = r.get("__meta", {})
        if meta.get("source_type") in ("pdf", "pptx") and isinstance(meta.get("page_no"), int):
            src = _resolve_source(source_dir, meta["source_file"])
            if not src:
                continue
            # route by the RESOLVED file's suffix, not the record's tag - a
            # vision agent's source_type slip must not send a .pdf to python-pptx
            kind = "pptx" if src.suffix.lower() == ".pptx" else "pdf"
            page_no = meta["page_no"]
            tried.append((src, page_no, kind))
            # LLM-PICKS-THE-HERO: when the interpretation sub-agent chose a heroRef (an int
            # index into this page's candidates_for_page list), bind THAT image - the
            # classifier + the G-images gate VERIFY it (a non-photo pick is blocked for
            # sign-off). heroRef None/absent falls through to the deterministic ladder below,
            # so a no-LLM / no-ref run still works. Same for planRef -> the plan slot. An
            # extractor-embedded record photo (set above) still wins first; a bound standalone
            # plan still wins the plan slot first - both are checked via `photo is None` /
            # `plan is None`. A null heroRef = 'no real photo on this page' STILL falls through
            # to the deterministic path; if that yields a non-photo the gate blocks it.
            href = meta.get("heroRef")
            pref = meta.get("planRef")
            if photo is None and isinstance(href, int):
                try:
                    h = IMG.embedded_by_index(src, page_no, href, budget_kb)
                except Exception:
                    h = None
                if h:
                    photo, photo_rec = h, r
                    # stash the locator so the caller's prov['photo'] reflects the LLM pick
                    meta.setdefault("prov", {})["photo"] = \
                        f"page {page_no + 1} (hero chosen by interpretation)"
            if plan is None and isinstance(pref, int):
                try:
                    pp = IMG.embedded_by_index(src, page_no, pref, budget_kb)
                except Exception:
                    pp = None
                if pp:
                    plan, plan_rec = pp, r
                    meta.setdefault("prov", {})["plan"] = \
                        f"page {page_no + 1} (site plan chosen by interpretation)"
            # LLM-PICKS-THE-PLAN-PAGE: a SITE PLAN that is VECTOR line-art rendered into the
            # page (not an embedded raster) - planRef cannot reach it (pulled as an image it
            # goes solid black). The sub-agent names the page in __meta.plan_page (it sees a
            # per-page render thumbnail); merge RENDERS that page, ink-crops it and binds it
            # to the PLAN SLOT ONLY (a vector plan is never the card hero). Lenient verify
            # (bind unless an obvious photo / near-blank). Only when the plan slot is empty.
            ppage = meta.get("plan_page")
            # PER-PROPERTY SCOPE: a plan_page that the unique-claimant guard assigned to
            # ANOTHER property of this multi-property deck is OFF-LIMITS and must NOT bind - so
            # an erroneous or over-claimed plan_page can never pull a NEIGHBOUR'S vector plan
            # into this card. The HINT may name ANY page (not just this cluster's own claimed
            # pages), so it uses the BROAD plan_offlimits set, not the narrow foreign_pages.
            _plan_off = (plan_offlimits or {}).get(str(src), set())
            if (plan is None and isinstance(ppage, int) and not isinstance(ppage, bool)
                    and ppage >= 0 and ppage not in _plan_off):
                try:
                    rp = IMG.page_render_plan(src, ppage, budget_kb, cache_dir=image_cache)
                except Exception:
                    rp = None
                # TRUST the interpreter's visual pick: bind unless an INDEPENDENT LLM verify judged it
                # NOT a site plan (Phase 2, consulted below). No pixel-classifier veto here.
                if rp:
                    plan, plan_rec = rp, r
                    meta.setdefault("prov", {})["plan"] = \
                        f"page {ppage + 1} (site plan page render chosen by interpretation)"
            # DETERMINISTIC FALLBACK (heroRef None/absent or the bind failed): the existing
            # classifier-ranked ladder. Only runs when a slot is still empty.
            if photo is None or plan is None:
                try:  # an out-of-range page_no (vision-agent arithmetic) must
                    # degrade gracefully, never crash the merge
                    if kind == "pptx":
                        h, p = IMG.slide_hero_and_plan(src, page_no, budget_kb,
                                                       cache_dir=image_cache)
                    else:
                        h, p = IMG.page_hero_and_plan(src, page_no, budget_kb,
                                                      cache_dir=image_cache)
                except Exception:
                    continue
                if photo is None and h:
                    photo, photo_rec = h, r
                if plan is None and p:
                    plan, plan_rec = p, r
    if photo is None:
        photo, photo_rec = IMG.placeholder(), None
    # GALLERY (cap IMG.GALLERY_MAX, best-first): the photos for the carousel. PAGE-SCOPED
    # per record so a MULTI-PROPERTY deck contributes only THIS property's pages, never a
    # neighbour's. The hero is guaranteed first; extractor-embedded record photos are
    # included; deduped by URI bytes. A render-tier hero that no embedded scan reproduces
    # simply stays as the sole/first entry. The placeholder property gets a 1-item gallery.
    gallery: list[str] = []

    def _g_add(uri):
        if isinstance(uri, str) and uri.startswith("data:image/") and uri not in gallery:
            gallery.append(uri)

    _g_add(photo)
    for r in embedded:
        _g_add(r.get("photo"))
    # PAGES this property may draw carousel photos from: each record's page_no
    # UNION its validated __meta.image_pages (the LLM's "these pages show THIS
    # property" pick), keyed by the resolved source. When NO record carries
    # image_pages this reduces to the page_no-only set -> byte-identical to today.
    # the SAME union the anti-leak guard computes (shared helper), so the harvester and
    # the guard can never diverge and leak a neighbouring property's page (audit S2-26).
    pages_by_src = _cluster_pages_by_src(cluster, source_dir)
    # per-source exclude map: the interpreter's __meta.exclude_refs (0-based page -> the candidate
    # indices it judged DECORATIVE / non-building via vision), unioned across this cluster's records
    # for each source. Absent/empty -> no exclusion, byte-identical to today. Honoured by SIG in
    # IMG.gallery_for_pages (never touches the hero, which is added separately above). (exclude_refs)
    excl_by_src: dict = {}
    for r in cluster:
        m = r.get("__meta", {}) or {}
        er = m.get("exclude_refs")
        if not isinstance(er, dict) or not er:
            continue
        s = _resolve_source(source_dir, m.get("source_file", ""))
        if not s:
            continue
        d = excl_by_src.setdefault(str(s), {})
        for pg, refs in er.items():
            try:
                p = int(pg)
            except (TypeError, ValueError):
                continue
            if isinstance(refs, list):
                d.setdefault(p, set()).update(
                    x for x in refs if isinstance(x, int) and not isinstance(x, bool) and x >= 0)
    for src_str, pgs in sorted(pages_by_src.items()):
        # the deterministic anti-leak guard (computed once over ALL clusters)
        # tells us which of these pages are FOREIGN (owned/claimed by another
        # property of the same deck); subtract them before harvesting. None /
        # absent -> no-op, so a cluster's own page_no is never foreign.
        allowed = pgs - (foreign_pages or {}).get(src_str, set())
        if not allowed:
            continue  # every claimed page was foreign: harvest nothing for this deck
            # (gallery_for_pages treats an empty page set as "whole deck" - never that here).
            # A cluster's own page_no is normally its own anchor (not foreign), so this rarely
            # fires; the skip is a DEFENSIVE guard - if a clustering anomaly made two properties
            # anchor the same page it is foreign to both, and this prevents the empty-set
            # whole-deck leak.
        try:
            uris, _total = IMG.gallery_for_pages(Path(src_str), sorted(allowed), budget_kb, image_cache,
                                                 exclude_by_page=excl_by_src.get(src_str))
        except Exception:
            uris = []
        for uri in uris:
            _g_add(uri)
    # DETERMINISTIC RENDERED-PLAN FALLBACK (no plan_page hint, or the hint missed): scan the
    # property's OWN pages - the SAME per-property allowed set the gallery uses (pages_by_src
    # minus foreign_pages) so a neighbour's plan page can never bind on a multi-property deck -
    # render+classify each and bind the most plan-like (CONSERVATIVE: classify 'plan' AND a
    # balanced white fraction, never a photo/map/blank). Plan slot ONLY (never the hero). Runs
    # only when the plan slot is still empty; a no-plan property keeps an honest None (today's
    # behaviour). Cached per (source, page, budget) -> byte-deterministic resume.
    if plan is None:
        _nm_acc: list = []  # near-miss pages (a plan signal that a precision guard rejected)
        for src_str, pgs in sorted(pages_by_src.items()):
            allowed = pgs - (foreign_pages or {}).get(src_str, set())
            if not allowed:
                continue
            _nm: list = []
            try:
                uri, pno = IMG.best_plan_page_render(Path(src_str), sorted(allowed),
                                                     budget_kb, image_cache, near_miss=_nm)
            except Exception:
                uri, pno = None, None
            for _e in _nm:
                _e["file"] = Path(src_str).name
                _nm_acc.append(_e)
            if uri:
                plan = uri
                plan_rec = next((r for r in cluster
                                 if _resolve_source(source_dir,
                                                    (r.get("__meta", {}) or {}).get("source_file", ""))
                                 and str(_resolve_source(source_dir,
                                                         r["__meta"]["source_file"])) == src_str), None)
                if plan_rec is not None:
                    plan_rec.get("__meta", {}).setdefault("prov", {})["plan"] = \
                        (f"page {pno + 1} (site plan page render, detected)"
                         if isinstance(pno, int) else "site plan page render (detected)")
                break
        if plan is None and plan_near_miss is not None and _nm_acc:
            plan_near_miss.extend(_nm_acc)
    return photo, plan, photo_rec, plan_rec, tried, gallery[:IMG.GALLERY_MAX]


def prewarm_images(all_records, source_dir, image_cache, budget_kb,
                   seconds: float = 30.0, workers: int | None = None) -> tuple:
    """Warm the image cache merge needs, in PARALLEL and TIME-BOUNDED, so the slow
    raster+compress harvest happens up front across CPUs instead of serially inside merge
    (which then runs as cache hits and finishes in one shell window). Each unit writes its
    own atomic cache, so a budget/kill exit loses at most the unit in flight - a re-run
    continues. Returns (done_units, total_units). Pure accelerator: identical cache bytes,
    so merge output is unchanged."""
    import os
    import time
    from concurrent.futures import ProcessPoolExecutor, as_completed
    if image_cache is None:
        return (0, 0)
    cache_str = str(image_cache)
    decks: dict = {}                 # resolved deck path -> suffix
    page_units: list = []            # per-record hero/slidehero specs
    for r in all_records:
        m = r.get("__meta", {})
        if m.get("source_type") in ("pdf", "pptx") and isinstance(m.get("page_no"), int):
            s = _resolve_source(source_dir, m.get("source_file", ""))
            if not s:
                continue
            decks.setdefault(str(s), s.suffix.lower())
            kind = "slidehero" if s.suffix.lower() == ".pptx" else "hero"
            page_units.append((kind, str(s), m["page_no"], budget_kb, cache_str))
    geom_units: list = []            # per-(deck,page) gallery + geometry (the whole-deck scans)
    for s_str, sfx in decks.items():
        s = Path(s_str)
        try:
            n = (min(len(list(IMG._get_pptx(s).slides)), 80) if sfx == ".pptx"
                 else min(IMG._get_doc(s).page_count, 80))
        except Exception:
            n = 0
        for p in range(n):
            geom_units.append(("gidxpage", s_str, p, budget_kb, cache_str))
            if sfx != ".pptx":       # PPTX has no pdfplumber geometry tier
                geom_units.append(("placedpage", s_str, p, 0, cache_str))
    IMG.close_doc_cache()            # release parent PDF handles before forking workers
    all_units = geom_units + page_units
    total = len(all_units)
    if total == 0:
        return (0, 0)
    if workers is None:
        env = 0
        try:
            env = int(os.environ.get("CBRE_IMAGE_WORKERS") or 0)
        except ValueError:
            env = 0
        workers = env or min(os.cpu_count() or 1, 8)
    workers = max(1, workers)
    deadline = time.monotonic() + max(1.0, seconds)

    def _prebatch_geometry(specs):
        # SERIAL/fallback only: warm each deck's pdfplumber GEOMETRY with ONE deck-wide open
        # (via _placed_layout) instead of one open per placedpage unit (and per hero unit that
        # reads geometry). _placed_layout writes each page's .placedpage.json exactly as
        # _placed_page would, so the per-unit calls then all hit the cache -> byte-identical
        # caches, merge output unchanged. The parallel path cannot share a handle across
        # processes, so this is scoped to the serial branches only. (#20)
        seen: set = set()
        for spec in specs:
            if spec[0] == "placedpage" and spec[1] not in seen:
                seen.add(spec[1])
                if time.monotonic() > deadline:
                    return
                try:
                    IMG._placed_layout(Path(spec[1]), spec[4])
                except Exception:
                    pass

    def _run(units):
        todo = [u for u in units if not IMG._unit_cached(u)]
        if not todo or time.monotonic() > deadline:
            return
        if workers <= 1:             # serial, no process pool (workers=1 opt-out / test path)
            _prebatch_geometry(todo)  # #20: one deck-wide geometry open, not one per page
            for u in todo:
                if time.monotonic() > deadline:
                    break
                IMG._prewarm_unit(u)
            return
        pool_ok = True
        try:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(IMG._prewarm_unit, u) for u in todo]
                for f in as_completed(futs):
                    try:
                        f.result()
                    except Exception:
                        pool_ok = False  # a broken pool (restricted spawn/fork) -> serial-fill
                    if time.monotonic() > deadline:
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
        except Exception:
            pool_ok = False
        if not pool_ok:              # no usable process pool -> finish serially in-process
            _prebatch_geometry(todo)  # #20: one deck-wide geometry open, not one per page
            for u in todo:
                if time.monotonic() > deadline:
                    break
                if not IMG._unit_cached(u):
                    IMG._prewarm_unit(u)

    _run(geom_units)                 # phase 1: page-grained geometry + gallery (no herd)
    _run(page_units)                 # phase 2: heroes (geometry now warm)
    done = sum(1 for u in all_units if IMG._unit_cached(u))
    return (done, total)


def canonicalize(p: dict) -> dict:
    # country: schema caps it at 2-3 chars, so a spelled-out name from an agent
    # ("Spain", "España") is a FORMATTING issue merge owns - never a gate failure
    # (37 validate-data blocks in one real run came from exactly this)
    if p.get("country") and not N.looks_unknown(p.get("country")):
        p["country"] = N.country_iso(p["country"])
    # rent: merge OWNS the display/numeric pair. When the numeric exists, the
    # display is ALWAYS regenerated from it (an agent-written "3,75 €/m²/mes"
    # string must not block the pair-consistency gate); when only a display
    # string exists, derive the numeric from it (annualising a monthly quote x12)
    # if it lands in its OWN convention's plausibility band - else keep the
    # honest text alone. Source units are KEPT: a '£8.50 psf' quote ships as
    # £/sq ft/yr (rentUnit), never converted to €/m² (FX would be invention).
    val = p.get("warehouseRentVal")
    if isinstance(val, (int, float)):
        p["warehouseRent"] = N.rent_display(val, p.get("rentUnit"))
    else:
        disp = p.get("warehouseRent")
        if isinstance(disp, str) and disp.strip() and not N.looks_unknown(disp):
            unit = p.get("rentUnit") or N.rent_unit_of_text(disp)
            num = N.extract_first_number(disp)
            if num is not None and N.MONTHLY_RX.search(disp):
                num = round(num * 12, 2)
            lo, hi = N.rent_unit_band(unit)
            if num is not None and lo <= num <= hi:
                p["warehouseRentVal"] = num
                if unit:
                    p["rentUnit"] = unit
                p["warehouseRent"] = N.rent_display(num, unit)
    # office rent NUMERIC (officeRentVal) for the total-rent split: parse the office
    # rent string in the SAME currency/per-area convention + plausibility band as the
    # warehouse rent (annualising a monthly quote x12). The office DISPLAY string is
    # left untouched; only a clean numeric is extracted. Never invented - absent stays absent.
    if not isinstance(p.get("officeRentVal"), (int, float)):
        odisp = p.get("officeRent")
        if isinstance(odisp, str) and odisp.strip() and not N.looks_unknown(odisp):
            ounit = p.get("rentUnit") or N.rent_unit_of_text(odisp)
            onum = N.extract_first_number(odisp)
            if onum is not None and N.MONTHLY_RX.search(odisp):
                onum = round(onum * 12, 2)
            olo, ohi = N.rent_unit_band(ounit)
            if onum is not None and olo <= onum <= ohi:
                p["officeRentVal"] = onum
    # office area NUMERIC (officeAreaVal) for total GLA: officeArea may be a number or
    # a string ('13576 sq ft'); extract the figure in the record's OWN area unit (the
    # minority-unit conversion in main() then aligns it to the dataset unit, like
    # warehouseArea). A '% of GLA' phrasing is skipped (not an absolute area).
    if not isinstance(p.get("officeAreaVal"), (int, float)):
        oa = p.get("officeArea")
        if isinstance(oa, (int, float)) and not isinstance(oa, bool):
            if oa > 0:
                p["officeAreaVal"] = float(oa)
        elif isinstance(oa, str) and oa.strip() and not N.looks_unknown(oa) and "%" not in oa:
            oan = N.extract_first_number(oa)
            if oan is not None and oan > 0:
                p["officeAreaVal"] = oan
    # expansionParkVal companion
    if "expansionPark" in p and "expansionParkVal" not in p:
        v = N.normalize_number(p["expansionPark"])
        if v is not None and v >= 1000:
            p["expansionParkVal"] = v
    # fill sentinels for every chrome-read key (honest unknowns, never invented)
    return C.fill_render_sentinels(p)


def load_hero(project_yaml: Path | None, properties: list[dict], default_date: str = "") -> dict:
    cfg = _load_yaml(project_yaml)
    client = (cfg.get("client") or {}).get("name") or "Client"
    market = cfg.get("market") or {}
    out = cfg.get("output") or {}
    eyebrow = market.get("eyebrow") or "Property Shortlist"
    region_label = market.get("region_label") or ""
    # compiled date: project.yaml wins; else the inputs' date (deterministic per
    # input set); wall-clock today only as the last resort
    compiled = out.get("compiled_date") or default_date or _dt.date.today().isoformat()
    n = len(properties)
    hero = {
        "topbar_meta": (f"{region_label} · {compiled}".strip(" ·")) or compiled,
        "eyebrow": eyebrow if "shortlist" in eyebrow.lower() else f"Property Shortlist · {eyebrow}",
        "title_html": market.get("title_html") or "logistics <em>options</em> for your next facility.",
        "lede": market.get("lede") or (
            f"{n} logistics development opportunities. Switch between the map and grid, "
            f"filter by country, city, developer or scale, and compare properties "
            f"side-by-side with drive-time estimates to the main ports, rail "
            f"terminals, airports and border crossings."),
        "footer_copyright": f"© {compiled[:4]} CBRE · {client} shortlist compiled {compiled}",
    }
    return hero


def _ws_norm(s) -> str:
    """Whitespace-normalise for the deterministic quote-verify (collapse runs,
    strip), so a copy-paste with reflowed spacing still matches the text layer."""
    return " ".join(str(s or "").split())


def _deck_text_hash(blocks) -> str:
    """Stable short hash of a deck's concatenated font_grouped_blocks text. The
    sub-agent's cached pick is accepted ONLY if this matches the stored text_hash,
    so editing the source deck invalidates a stale pick rather than reusing it."""
    import hashlib
    joined = "\n".join(b.get("text", "") for b in blocks)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _verified_photo_description(bsrc, entry):
    """Return (description, page_no_0based) from a sub-agent description pick ONLY
    if it passes the deterministic gate; else None. Gate: (a) the stored text_hash
    matches the deck's CURRENT font_grouped_blocks text (no stale pick after an
    edit) AND (b) the description_source_quote, whitespace-normalised, OCCURS
    verbatim in the cited page's text layer. A fabricated description physically
    cannot pass, so it can never reach canonical.json - the heuristic is the
    fallback at the call site."""
    if not isinstance(entry, dict):
        return None
    desc = entry.get("description")
    quote = entry.get("quote")
    if not desc or not quote:
        return None
    try:
        blocks = XP.font_grouped_blocks(bsrc)
    except Exception:
        return None
    if not blocks:
        return None  # raster/shim deck: no text layer to verify against -> heuristic
    want_hash = entry.get("text_hash")
    if want_hash and want_hash != _deck_text_hash(blocks):
        return None  # the deck changed since the pick was made -> reject (re-pick / heuristic)
    page = entry.get("page")
    nq = _ws_norm(quote)
    if not nq:
        return None
    # the quote must occur in the cited page's text (if a page is given), else any page
    if isinstance(page, int):
        page_text = " ".join(b.get("text", "") for b in blocks if b.get("page") == page)
        if nq in _ws_norm(page_text):
            return N.clean_value(str(desc)), max(page - 1, 0)
        return None
    whole = " ".join(b.get("text", "") for b in blocks)
    if nq in _ws_norm(whole):
        return N.clean_value(str(desc)), 0
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", nargs="+", required=True)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--project-yaml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ledger")
    ap.add_argument("--language", default="", help="dashboard chrome language (Stage-0 Q3) "
                    "-> meta.language; the builder resolves it to the i18n table at render "
                    "time (per-key English fallback). Blank -> English.")
    ap.add_argument("--locale", default="", help="optional explicit BCP-47 locale "
                    "-> meta.locale (e.g. de-AT); blank -> the language's default region.")
    ap.add_argument("--ui-overrides", dest="ui_overrides", default="", help="Phase-2 FALLBACK "
                    "chrome translation cache (work/i18n/<code>.json) for a SUPPORTED-but-not-"
                    "bundled language. When it loads + is a non-empty dict, its EN-keyed entries "
                    "are baked into meta.ui_overrides (a leading _en_sha / any _* meta key and "
                    "any non-EN/DATA key are dropped) so render() reproduces the fallback from "
                    "canonical alone. Blank/absent/invalid -> meta.ui_overrides is NOT set "
                    "(byte-identical to the bundled/EN path).")
    ap.add_argument("--requirements", help="JSON file of client questionnaire requirements -> meta.requirements")
    ap.add_argument("--image-budget-kb", type=int, default=IMG.DEFAULT_BUDGET_KB)
    ap.add_argument("--image-cache", help="dir for the persistent hero-image cache "
                    "(re-runs reuse identical bytes instead of re-rastering/compressing)")
    ap.add_argument("--photo-map", help="JSON {match_key: brochure_relpath} of confident "
                    "sub-agent photo matches: a 0-record brochure's deck hero fills that "
                    "property's placeholder (P0-1)")
    ap.add_argument("--photo-descriptions", help="JSON {brochure_name: {description, page, "
                    "quote, text_hash}} of the photo-match sub-agent's per-brochure description "
                    "pick (verbatim deck prose). Accepted ONLY when the text_hash matches the "
                    "deck's current text AND the quote occurs verbatim in the cited page - a "
                    "deterministic gate so a hallucinated description can never enter a record. "
                    "Absent/empty/malformed/unverified -> best_description_in_deck is the offline "
                    "fallback (byte-identical to today).")
    ap.add_argument("--match-decisions", help="JSON {pair_id: 'same'|'different'|{verdict,reason}} "
                    "of the cross-source match sub-agent's grey-zone verdicts (run.py exit 10). "
                    "Resolves ONLY the ambiguous pairs; the deterministic auto/forbidden tiers are "
                    "unchanged and a forbidden pair never merges even on 'same'. Absent -> the "
                    "deterministic matcher is the offline fallback (byte-identical to today).")
    ap.add_argument("--field-decisions", help="JSON {conflict_id: {pick: '<label>', reason: '...'}} "
                    "of the cross-source VALUE-conflict sub-agent's picks (run.py exit 10, same "
                    "candidates file as --match-decisions). The fixed precedence is the DEFAULT; a "
                    "pick OVERRIDES it ONLY when it selects a given candidate value that PASSES the "
                    "field's plausibility gate (rent band / area > 0 / coord bounds) - a failing or "
                    "absent pick keeps precedence. Absent -> precedence is the offline fallback "
                    "(byte-identical to today).")
    ap.add_argument("--match-conflicts", help="JSON [str, ...] of ADVISORY grey-match disagreement "
                    "lines (the blind match verifier disagreed with the matching pass; run.py "
                    "computes them in pure Python). Folded verbatim into meta.conflicts -> the Gaps "
                    "'Source conflicts' section. Does NOT change clustering (the matching pass's "
                    "verdict already drove --match-decisions). Absent / empty -> no extra line "
                    "(byte-identical to today).")
    args = ap.parse_args()

    all_records = []
    for f in args.records:
        all_records.extend(json.loads(Path(f).read_text(encoding="utf-8")))

    for _r in all_records:            # v22 Phase 1: quarantine off-spec structures pre-merge
        _normalise_offspec(_r)

    compute_file_quality(all_records)  # demote mostly-poor brochures in precedence
    area_unit, rent_unit = dominant_units(all_records)
    MATCH_DECISIONS = {}  # pair_id -> 'same'|'different'|{verdict,reason} (grey-zone sub-agent)
    if args.match_decisions and Path(args.match_decisions).exists():
        try:
            loaded = json.loads(Path(args.match_decisions).read_text(encoding="utf-8"))
            MATCH_DECISIONS = loaded if isinstance(loaded, dict) else {}
        except Exception:
            MATCH_DECISIONS = {}  # best-effort, exactly like PHOTO_MAP - a bad file -> deterministic
    # First-party map-link pins (bug #D): fill lat/lng + mapLink from each brochure page's
    # 'click for location' maps hyperlink BEFORE clustering/geocode. The author's own pin is
    # better than any geocoder and fully offline; this recovers the coords the current
    # interpretation record source does not carry (the harvest used to live only in the
    # deprecated extract_pdf own-line path). Deterministic (pure function of the PDFs) -> resume-safe.
    if getattr(args, "source_dir", None):
        XP.backfill_link_coords(all_records, Path(args.source_dir))
    clusters = match.dedupe(all_records, MATCH_DECISIONS or None)
    FIELD_DECISIONS = {}  # conflict_id -> {pick, reason} (cross-source value-conflict sub-agent)
    if args.field_decisions and Path(args.field_decisions).exists():
        try:
            loaded = json.loads(Path(args.field_decisions).read_text(encoding="utf-8"))
            FIELD_DECISIONS = loaded if isinstance(loaded, dict) else {}
        except Exception:
            FIELD_DECISIONS = {}  # best-effort, exactly like MATCH_DECISIONS - a bad file -> precedence
    source_dir = Path(args.source_dir)
    PHOTO_MAP = {}  # match_key -> brochure relpath (confident photo matches from the sub-agent)
    if args.photo_map and Path(args.photo_map).exists():
        try:
            PHOTO_MAP = json.loads(Path(args.photo_map).read_text(encoding="utf-8")) or {}
        except Exception:
            PHOTO_MAP = {}
    PHOTO_DESCRIPTIONS = {}  # brochure name -> {description, page, quote, text_hash} (sub-agent pick)
    if args.photo_descriptions and Path(args.photo_descriptions).exists():
        try:
            loaded = json.loads(Path(args.photo_descriptions).read_text(encoding="utf-8"))
            PHOTO_DESCRIPTIONS = loaded if isinstance(loaded, dict) else {}
        except Exception:
            PHOTO_DESCRIPTIONS = {}  # best-effort, exactly like PHOTO_MAP - a bad file -> heuristic
    # persistent hero-image cache: DEFAULT next to the canonical, so a manual
    # `python helpers/merge.py` call (no --image-cache flag) still checkpoints
    # per page and survives a capped/killed shell exactly like a run.py call
    image_cache = (Path(args.image_cache) if args.image_cache
                   else Path(args.out).resolve().parent / ".image_cache")
    try:
        image_cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        image_cache = None  # unwritable cache dir must never break the merge

    def _is_sentinel(v):
        return v is None or str(v).strip().lower() in {"tbd", "—", "", "none", "??"}

    properties, ledger_rows, all_conflicts = [], [], []
    meta_offspec = []   # v22 Phase 1: off-spec keys quarantined pre-merge (-> Gaps Report)
    placeholder_audit: dict = {}  # prop id -> discarded image candidates (audited, never silent)
    regions_on = bool(((_load_yaml(args.project_yaml) or {}).get("enrichment") or {}).get("regions"))
    # UNIQUE-CLAIMANT GUARD: precompute, once over ALL clusters, the per-deck pages each
    # property may NOT draw carousel photos from (a neighbour's anchor/uniquely-claimed
    # pages). attach_media subtracts its own foreign set before harvesting. With no
    # image_pages anywhere this is empty everywhere -> byte-identical to today.
    foreign_by_cluster = build_foreign_pages(clusters, source_dir)
    # the BROADER per-deck other-owned set for the plan_page HINT (which may name any page,
    # not just the cluster's own) - so an LLM plan_page can never bind a neighbour's plan.
    plan_offlimits_by_cluster = plan_offlimits_pages(clusters, source_dir)
    plan_near_miss_all: list = []  # per-property near-miss plan pages -> Gaps Report (light Fix 4)
    for i, cl in enumerate(clusters, start=1):
        merged, prov, conflicts = merge_cluster(cl, FIELD_DECISIONS or None)
        merged["id"] = i
        merged = canonicalize(merged)
        # regionCode auto-derivation: the workforce block keys on regionCode, but no
        # extractor sets it - a real run shipped an EMPTY workforce block because
        # nothing ever bound properties to profiles. When the regions extra is on,
        # derive it from the region label (the Oxford Economics dataset then matches
        # it by NUTS code or unique province name; validate-data blocks LOUDLY if a
        # code matches no profile). Only when regions are requested - otherwise the
        # regionCode-resolves check would block runs that never wanted workforce data.
        if regions_on and not merged.get("regionCode") and not _is_sentinel(merged.get("region")):
            merged["regionCode"] = N.clean_value(merged["region"])
        # provenance for DERIVED companions: a value canonicalize() synthesises from a
        # sourced field (the rent display from warehouseRentVal, the numeric from
        # expansionPark) inherits that field's source. Without this, trace-coverage
        # flags the derived value as "untraceable - possible fabrication" on EVERY
        # run whose rent arrived numeric-only (xlsx trackers, vision records) - an
        # unresolvable gate loop, since re-running merge reproduces the same state.
        for derived, basis in (("warehouseRent", "warehouseRentVal"),
                               ("warehouseRentVal", "warehouseRent"),  # numeric derived from a display string
                               ("officeRentVal", "officeRent"),        # office rent numeric for the total-rent split
                               ("officeAreaVal", "officeArea"),        # office area numeric for total GLA
                               ("expansionParkVal", "expansionPark")):
            if derived not in prov and basis in prov and not _is_sentinel(merged.get(derived)):
                src = dict(prov[basis])
                src["locator"] = (f"{src.get('locator', '')} (derived from {basis})").strip()
                prov[derived] = src
        # DATASET UNIT CONVENTION: the dominant area unit wins; a minority-unit
        # record converts ARITHMETICALLY (prov-noted). Currency is never touched
        # (FX would be invention) - a lone €/m² rent in a £/sq ft dataset keeps
        # its own honest unit and simply sits out the hero rent range.
        if merged.get("areaUnit") and merged["areaUnit"] != area_unit:
            f = N.SQFT_PER_SQM if area_unit == "sq ft" else 1.0 / N.SQFT_PER_SQM
            for fld in ("warehouseArea", "plotArea", "officeAreaVal"):
                if isinstance(merged.get(fld), (int, float)):
                    merged[fld] = round(merged[fld] * f)
                    if fld in prov:
                        prov[fld]["locator"] = (f"{prov[fld].get('locator', '')} "
                                                f"(converted {merged['areaUnit']} -> {area_unit})").strip()
        merged["areaUnit"] = area_unit
        _cluster_nm: list = []
        merged["photo"], plan_uri, photo_rec, plan_rec, tried_pages, gallery = attach_media(
            cl, source_dir, args.image_budget_kb, image_cache=image_cache,
            foreign_pages=foreign_by_cluster[i - 1],
            plan_offlimits=plan_offlimits_by_cluster[i - 1],
            plan_near_miss=_cluster_nm)
        if not plan_uri and _cluster_nm:  # a page LOOKED plan-ish but no plan bound -> surface it
            plan_near_miss_all.append({"property": merged.get("park") or merged.get("city") or "?",
                                       "city": merged.get("city", ""), "pages": _cluster_nm})
        merged["gallery"] = gallery  # carousel photos (hero first); always >= [photo]
        # PHOTO MATCH OVERRIDE (P0-1): a 0-record brochure the sub-agent CONFIDENTLY
        # matched to this property supplies the hero, scanned across the whole deck
        # (cheap embedded-image tier). Fills the placeholder; never overrides a photo
        # the property's own cluster already produced.
        matched_hero = False
        if photo_rec is None and PHOTO_MAP:
            brel = PHOTO_MAP.get(match.match_key(merged))
            if brel:
                bsrc = _resolve_source(source_dir, Path(brel).name)
                hero = IMG.best_hero_in_deck(bsrc, args.image_budget_kb, image_cache) if bsrc else None
                if hero:
                    merged["photo"] = hero
                    # the matched brochure IS this property (single-property deck), so the
                    # gallery is the whole-deck top photos (best_hero_in_deck's pick is the
                    # first of that ranked set, so the hero stays gallery[0]).
                    try:
                        g_uris, _gt = IMG.gallery_for_deck(bsrc, args.image_budget_kb, image_cache)
                    except Exception:
                        g_uris = []
                    merged["gallery"] = g_uris or [hero]
                    prov["photo"] = {"source_file": Path(brel).name,
                                     "source_type": (Path(brel).suffix.lstrip(".") or "pdf"),
                                     "locator": "deck photo (brochure matched to this property)"}
                    matched_hero = True
                # also harvest the brochure's DESCRIPTION prose: the deck had no spec
                # record, so parse_property_page never captured it - same confident
                # brochure->property link as the photo. PREFER the photo-match sub-agent's
                # LLM verbatim pick (handles multi-paragraph / novel-market decks the
                # EN-keyword heuristic misses), but ONLY when it passes the deterministic
                # quote-verify gate (the quote occurs verbatim in the cited page + the
                # deck text is unchanged); otherwise fall through to best_description_in_deck
                # UNCHANGED. Verbatim from the deck; a tbd stays tbd when none is usable.
                if bsrc and _is_sentinel(merged.get("description")):
                    dtext, dpno, dtag = None, None, "brochure description"
                    entry = PHOTO_DESCRIPTIONS.get(Path(brel).name) if PHOTO_DESCRIPTIONS else None
                    if entry:
                        v = _verified_photo_description(bsrc, entry)
                        if v:
                            dtext, dpno = v
                            dtag = "brochure description, text interpretation"
                    if dtext is None:  # no pick, or the gate rejected it -> deterministic fallback
                        try:
                            dtext, dpno = XP.best_description_in_deck(bsrc)
                        except Exception:
                            dtext, dpno = None, None
                    if dtext:
                        merged["description"] = dtext
                        prov["description"] = {
                            "source_file": Path(brel).name,
                            "source_type": (Path(brel).suffix.lstrip(".") or "pdf"),
                            "locator": f"page {(dpno or 0) + 1} ({dtag})"}
        if matched_hero:
            pass  # prov["photo"] already set from the matched brochure
        elif photo_rec is None:  # placeholder: an honest, COMPLETE gap row (an empty
            # source_file/type would fail ledger validate - now a scorecard gate)
            prov["photo"] = {"source_file": "(none)", "source_type": "gap",
                             "locator": "no usable photo in any source (placeholder shown)"}
            # PLACEHOLDER AUDIT: a placeholder is never a silent default - dump
            # every image candidate from the pages we examined so the G-images
            # reviewer can SEE the discard pile and sign off (or rescue a usable
            # photo/plan). The images gate BLOCKS until that sign-off exists.
            if tried_pages:
                audit_dir = Path(args.out).resolve().parent / "render" / "placeholder_audit"
                files: list[str] = []
                for srcf, pno, kind in tried_pages:
                    try:
                        if kind == "pptx":
                            files += IMG.slide_image_audit(
                                srcf, pno, audit_dir, f"prop{i}", cache_dir=image_cache)
                        else:
                            files += IMG.page_image_audit(srcf, pno, audit_dir, f"prop{i}")
                    except Exception:
                        pass
                unit = "slide" if tried_pages[0][2] == "pptx" else "page"
                placeholder_audit[str(i)] = {
                    "source": tried_pages[0][0].name,
                    "locator": f"{unit} {tried_pages[0][1] + 1}",
                    "candidates": len(files), "files": files,
                }
        else:
            photo_src = photo_rec.get("__meta", {})
            prov["photo"] = {"source_file": photo_src.get("source_file", ""),
                             "source_type": photo_src.get("source_type", ""),
                             "locator": (photo_src.get("prov", {}).get("photo")
                                         or photo_src.get("locator_base", ""))}
        if plan_uri:  # the modal's Site Plan toggle reads p.plan
            merged["plan"] = plan_uri
            plan_src = (plan_rec or {}).get("__meta", {})
            pno = plan_src.get("page_no")
            prov["plan"] = {"source_file": plan_src.get("source_file", ""),
                            "source_type": plan_src.get("source_type", ""),
                            "locator": (plan_src.get("prov", {}).get("plan")
                                        or (f"page {pno + 1} (site plan)" if isinstance(pno, int)
                                            else plan_src.get("locator_base", "")))}
        merged.pop("__meta", None)
        properties.append(merged)
        # v22 Phase 1: audit every quarantined off-spec key (never silently dropped)
        for _r in cl:
            for _k, _v in (_r.get("__meta", {}).get("offspec", {}) or {}).items():
                ledger_rows.append({
                    "property_id": i, "record_type": "offspec", "field": _k,
                    "value": _short(_v), "source_file": _r.get("__meta", {}).get("source_file", ""),
                    "source_locator": "", "source_type": _r.get("__meta", {}).get("source_type", ""),
                    "extractor": "boundary", "confidence": "",
                    "conflict_note": "off-spec structure (provenance/meta) quarantined - not a displayable value",
                    "verified": "",
                })
                meta_offspec.append({"property_id": i, "key": _k, "value": _short(_v)})
        # ledger rows for every populated field (with conflict note where one occurred)
        for field, pr in prov.items():
            ledger_rows.append({
                "property_id": i, "record_type": "property", "field": field,
                "value": _short(merged.get(field)), "source_file": pr.get("source_file", ""),
                "source_locator": pr.get("locator", ""), "source_type": pr.get("source_type", ""),
                "extractor": f"E-{pr.get('source_type','')}", "confidence": _confidence(pr),
                "conflict_note": conflicts.get(field, ""), "verified": "",
            })
        # a ledger row for every chrome-read field left as a sentinel (the positive
        # record that the value was genuinely absent - checked by G-honesty). Covers
        # the identity fields too (developer/city/park/country/reit/mapLink/...): a
        # sentinel without its row is a gap G-honesty cannot verify.
        for field in (C.STRING_FIELDS + list(C.REQUIRED_TEXT_SENTINELS)
                      + ["landPrice", "warehouseArea", "lat", "lng",
                         "plotArea", "reit", "mapLink", "expansionParkVal"]):
            if field in prov:
                continue
            val = merged.get(field)
            if _is_sentinel(val):
                ledger_rows.append({
                    "property_id": i, "record_type": "property", "field": field,
                    # an empty-string sentinel (mapLink) still needs a non-empty
                    # ledger value, or the row fails ledger validate
                    "value": (str(val).strip() if val is not None and str(val).strip() else "tbd"),
                    "source_file": "(none)",
                    "source_locator": "absent in all sources", "source_type": "gap",
                    "extractor": "", "confidence": "", "conflict_note": "", "verified": "no",
                })
        for field, note in conflicts.items():
            all_conflicts.append(f"id {i} {field}: {note}")

    # SEMANTIC VERIFIER (grey-match): fold the blind verifier's ADVISORY disagreement lines
    # into meta.conflicts so the Gaps 'Source conflicts' section surfaces them. These do NOT
    # affect clustering (the matching pass's verdict already drove --match-decisions); they
    # are appended LAST so the field-conflict order above is byte-stable. Best-effort - a bad
    # file is treated as absent (no advisory, never a crash), exactly like --match-decisions.
    if args.match_conflicts and Path(args.match_conflicts).exists():
        try:
            mv_lines = json.loads(Path(args.match_conflicts).read_text(encoding="utf-8"))
            if isinstance(mv_lines, list):
                all_conflicts.extend(str(s) for s in mv_lines if str(s).strip())
        except Exception:
            pass

    IMG.close_doc_cache()  # release the per-brochure PDF handles opened during photo harvest

    # Seed POIs from the library ONLY where they are plausibly near this dataset,
    # so a non-CEE run never inherits the CEE library's POIs. Region-neutral test:
    # keep a library POI within SEED_MAX_KM of any located property; if no property
    # has coordinates yet, fall back to country-code membership; otherwise seed
    # none and let --pois (live OSM) / the dashboard's client-side discovery supply
    # the genuine nearest POIs. Cross-border POIs (e.g. a German port serving a
    # Czech site) survive because the test is distance, not same-country.
    pois = []
    poi_lib = C.ASSETS / "poi_library.json"
    if poi_lib.exists():
        lib = json.loads(poi_lib.read_text(encoding="utf-8"))
        lib_pois = (lib.get("pois", lib) if isinstance(lib, dict) else lib) or []
        located = [p for p in properties
                   if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))]
        countries = {str(p.get("country", "")).upper() for p in properties if p.get("country")}
        if located:
            pois = [q for q in lib_pois
                    if isinstance(q.get("lat"), (int, float)) and isinstance(q.get("lng"), (int, float))
                    and min(_haversine_km(p["lat"], p["lng"], q["lat"], q["lng"]) for p in located) <= SEED_MAX_KM]
        else:
            pois = [q for q in lib_pois if str(q.get("country", "")).upper() in countries]
        if len(pois) != len(lib_pois):
            print(f"   POI seed: kept {len(pois)}/{len(lib_pois)} library POIs near this dataset "
                  f"(out-of-region dropped; live --pois / client-side discovery supply the rest)")

    # generatedAt derives from the INPUTS, not wall-clock now(): same inputs ->
    # byte-identical canonical.json, so the enrich resume stamp, freeze diffs and
    # "same inputs -> identical built.html" all actually hold. Prefer the SOURCE
    # files' mtimes (stable even when --no-resume rewrites the record files);
    # fall back to the record files when no source file is resolvable.
    src_files = [_resolve_source(source_dir, r.get("__meta", {}).get("source_file", ""))
                 for r in all_records]
    newest_in = max((f.stat().st_mtime for f in src_files if f is not None), default=0.0) \
        or max((Path(f).stat().st_mtime for f in args.records if Path(f).exists()),
               default=0.0)
    # round to DATE (not seconds): the HTML hero/footer show this same input-date at
    # DATE granularity (load_hero `compiled`/`default_date` below), and generatedAt
    # is never rendered with a time component - nothing reads it as a datetime. A
    # bare-second stamp made canonical.json byte-unstable across environments whose
    # input mtimes differ by seconds (re-download / unzip / checkout of identical
    # content); a date collapses that jitter to the day, matching the only place the
    # date is shown. HTML and ledger bytes are unaffected (neither reads generatedAt).
    generated_date = _dt.datetime.fromtimestamp(newest_in).date().isoformat() if newest_in else ""
    meta = {
        "client": ((_load_yaml(args.project_yaml) or {}).get("client") or {}).get("name", "Client"),
        "generatedAt": generated_date,
        "templateVersion": C.load_version().get("label", ""),
        "hero": load_hero(Path(args.project_yaml) if args.project_yaml else None, properties,
                          default_date=generated_date),
        "sourceFiles": sorted({r.get("__meta", {}).get("source_file", "?") for r in all_records}),
        "conflicts": all_conflicts,
        "placeholderAudit": placeholder_audit,
        # the dataset's unit convention (source units KEPT) - the builder formats
        # the hero KPI strip and its sub-labels from this
        "units": {"area": area_unit, "rent": rent_unit},
        # dashboard chrome language (Stage-0 Q3). OPTIONAL + default-safe: absent ->
        # "English" -> en. The builder resolves it to the i18n table at render time
        # (per-key English fallback); DATA is never translated.
        "language": (args.language or "English"),
    }
    if meta_offspec:
        meta["offspec"] = meta_offspec
    if plan_near_miss_all:
        meta["planNearMiss"] = plan_near_miss_all
    # an explicit BCP-47 locale (e.g. de-AT) overrides the language's default region
    if str(getattr(args, "locale", "") or "").strip():
        meta["locale"] = args.locale.strip()
    # Phase 2 (fallback): bake the translate-once cache into meta.ui_overrides so the
    # fallback chrome rides canonical and render()/validate-html reproduce it byte-for-
    # byte. ONLY keys that exist in i18n.EN are kept - a leading _en_sha (or any _* meta
    # key) and any stray/DATA key are dropped, never injected; CHROME only, never data.
    # Optional + default-safe: blank/absent/unloadable/empty -> the key is NOT set, so
    # the bundled/EN path is byte-identical to Phase 1.
    _ui_ov_path = str(getattr(args, "ui_overrides", "") or "").strip()
    if _ui_ov_path:
        _loaded = I18N.load_fallback_cache(_ui_ov_path)
        if isinstance(_loaded, dict) and _loaded:
            _baked = {k: v for k, v in _loaded.items() if k in I18N.EN}
            if _baked:
                meta["ui_overrides"] = _baked
    # carry the client's questionnaire requirements through, if any (the orchestrator
    # uses them for the size-slider default and hard-requirement flags). Not injected
    # into the HTML - meta is audit/orchestrator data, so this never affects the chrome.
    if args.requirements and Path(args.requirements).exists():
        try:
            reqs = json.loads(Path(args.requirements).read_text(encoding="utf-8"))
            if reqs:
                meta["requirements"] = reqs
        except Exception:
            pass

    canonical = {
        "meta": meta,
        "properties": properties,
        "pois": pois,
        "regions": {},
    }

    # ATOMIC write: a shell-cap kill mid-write (routine in Cowork's ~45s cap) must
    # never leave a truncated canonical that --resume then treats as current
    out_path = Path(args.out)
    C.atomic_write_text(out_path, json.dumps(canonical, ensure_ascii=False, indent=2))
    print(f"OK canonical -> {args.out}  ({len(properties)} properties, {len(pois)} POIs)")

    if args.ledger:
        import io as _io
        buf = _io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(ledger_rows[0].keys()) if ledger_rows else
                           ["property_id", "field", "value"], lineterminator="\n")
        w.writeheader()
        w.writerows(ledger_rows)
        C.atomic_write_text(Path(args.ledger), buf.getvalue())  # atomic + LF, like canonical (review #2)
        print(f"OK ledger -> {args.ledger}  ({len(ledger_rows)} rows)")


def _confidence(pr: dict) -> str:
    """Ledger confidence from the row's real source. An LLM read is Medium: a brochure
    'text interpretation' OR a 'vision transcription' (both produced by the isolated
    interpretation sub-agent), as is an image/web read (source-traceability.md - a
    less-certain source, and a G-honesty spot-check priority). High is reserved for a
    DETERMINISTIC structured extract (a tracker cell, an email field). Derived values
    inherit via the locator (which carries the basis locator)."""
    loc = str(pr.get("locator", "")).lower()
    if ("vision" in loc or "interpretation" in loc
            or pr.get("source_type") in ("image", "web")):
        return "Medium"
    return "High"


def _short(v, n=60):
    s = str(v)
    return s[:n] + ("…" if len(s) > n else "")


def _load_yaml(path):
    if not path or not Path(path).exists():
        return {}
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
