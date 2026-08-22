#!/usr/bin/env python3
"""repairs.py - PROPERTY-KEYED corrections, applied after the merge.

WHY THIS EXISTS, given `overrides.json` already corrects data.

`overrides.json` targets a SOURCE RECORD - a spreadsheet row, a brochure page - and is
applied during extraction, before anything is matched or merged. That is the right shape
for "this cell was mis-transcribed". It is the wrong shape for the other half of the work,
which only becomes visible AFTER the merge: a value that survived precedence but is wrong
for the property, a field the property lacks entirely, a plausibility gate that struck a
figure the source plainly states, a hero photo bound to the wrong building.

Every repair of that kind in a live run had to be expressed as a source-record override,
which meant finding which of several records supplied the value, and re-running the whole
spine to see the effect. Worse, a per-property fix has a dataset-wide blast radius: a
corrected area re-derives the cluster anchors, which re-keys settled conflict decisions and
triggers a fresh adjudication round for one changed pair. That cost is what this module
removes. A repair names the PROPERTY, is applied once the properties exist, and touches
nothing else.

WHAT IT IS NOT. It is not a way to write into `canonical.json` by hand. Repairs are declared
in one auditable, re-applied file; they run BEFORE the pre-build gates, so validate-data,
arithmetic, coverage and trace-coverage all judge the repaired dataset exactly as they judge
any other; and every applied field writes its own Source Ledger row. A repair is therefore
disclosed in the same breath as it is made, never laundered into looking like source data.

The projection under `work/properties/` is READ-ONLY and is not the input here. Two writable
representations of the same dataset is a drift bug waiting to happen; the projection is a
view, this file is the edit.

GUARDS, all failing CLOSED - an entry that cannot be resolved with certainty applies NOTHING
and is reported, because a repair landing on the wrong card is worse than a repair that did
not land:
  * `property.key` must match a property's match_key. `property.id` is a second confirmation.
    Given both, they are INTERSECTED: a key several properties share (every multi-unit park
    shares one) is disambiguated by the id, while an id outside the key's matches is a real
    disagreement -> AMBIGUOUS.
  * zero matches -> STALE. More than one, with nothing to disambiguate -> AMBIGUOUS.
  * `expect` is compared against the property's CURRENT values; any mismatch -> SUPERSEDED.
    This is what makes the entry safe across a re-match: if identity moved under it, the
    guard fires instead of the value. Absence is one bucket for this comparison: a field a
    gate struck holds None but reads `tbd` everywhere a human looks, so `expect: {"f": "tbd"}`
    matches it (see `_expect_same`).
  * a denied field -> INVALID. `id`/`photo`/`gallery`/`plan`/`preBaked` are structural or
    media (media has its own key); `areaUnit`/`rentUnit` are denied for the same reason
    overrides deny them - they relabel every figure at once, which is the 10.76x error class.
  * `why` and `verified_by` are REQUIRED and non-empty; both ship in the ledger.

CLI (offline, used by run.py and by hand):
  python repairs.py apply --work <dir>          apply to <work>/canonical.json in place
  python repairs.py check --work <dir>          report only, change nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    import match as _match
except Exception:                                    # pragma: no cover - offline shim
    _match = None

# structural, media-owned, or dataset-wide unit labels: never settable by a repair
DENIED_FIELDS = frozenset({
    "id", "photo", "gallery", "plan", "preBaked",
    "areaUnit", "rentUnit",
})
MEDIA_SLOTS = ("hero", "plan")
REPORT_KEYS = ("applied", "stale", "ambiguous", "superseded", "invalid")


def _mk(rec: dict) -> str:
    if _match is not None:
        try:
            return _match.match_key(rec)
        except Exception:
            pass
    return "|".join(str(rec.get(k, "") or "").strip().lower()
                    for k in ("city", "developer", "park"))


def _image_uri(src: Path, slot: str):
    """Compress a supplied image the SAME way the pipeline compresses every other one, so a
    repaired hero is indistinguishable in weight and encoding from a harvested one. Returns
    None when the file is not a decodable image - reported, never silently skipped."""
    try:
        import images as IMG
    except Exception:
        return None
    try:
        img = IMG._open(src.read_bytes())
        if img is None:
            return None
        edge = IMG.PLAN_MAX_EDGE if slot == "plan" else IMG.HERO_MAX_EDGE
        return IMG.to_data_uri(IMG.compress(img, edge, IMG.DEFAULT_BUDGET_KB))
    except Exception:
        return None


def _same(a, b) -> bool:
    """Value equality that survives the int/float and whitespace noise of hand-written JSON."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return str(a).strip() == str(b).strip()


# The sentinel family for the `expect` guard ONLY. Deliberately NARROWER than
# normalize.looks_unknown: that set carries market phrases ("a consultar", "auf anfrage")
# which a broker may legitimately want the guard to notice, and its docstring says to widen
# at the caller rather than in the shared set (deliver._is_tbd does the same). This is the
# canonical-sentinel family and nothing else.
_EXPECT_ABSENT = frozenset({"", "tbd", "tbc", "—", "-", "n/a", "none", "??"})


def _absent_like(v) -> bool:
    return v is None or str(v).strip().lower() in _EXPECT_ABSENT


def _expect_same(cur, want) -> bool:
    """Equality for the `expect` guard, where BOTH SIDES ABSENT counts as a match.

    A field a plausibility gate struck holds None, but every surface a human reads - the card,
    the Source Ledger, the Gaps Report, work/properties/<id>/notes.md - displays it as `tbd`.
    So `expect: {"warehouseArea": "tbd"}`, which is the value the docs invite you to write,
    could never match and every such entry returned SUPERSEDED. One live run lost a batch of
    17 repairs and a full re-run to exactly that. `_same` itself is untouched, so this widening
    reaches the guard and nothing else.
    """
    return _same(cur, want) or (_absent_like(cur) and _absent_like(want))


def load(path) -> tuple[list, list]:
    """Parse repairs.json -> (entries, invalid_reasons). NEVER raises."""
    p = Path(str(path or ""))
    if not str(path) or not p.exists():
        return [], []
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return [], [f"{p.name} is not valid JSON ({type(e).__name__}) - NO repair was applied"]
    if not isinstance(raw, list):
        return [], [f"{p.name} must be a JSON LIST of repair entries - NO repair was applied"]

    canon = set(C.canonical_property_fields())
    out, bad, seen = [], [], set()
    for n, e in enumerate(raw, start=1):
        tag = f"entry #{n}"
        if not isinstance(e, dict):
            bad.append(f"{tag} is not an object")
            continue
        rid = str(e.get("id") or "").strip()
        tag = f"repair {rid}" if rid else tag
        if not rid:
            bad.append(f"{tag}: no `id`")
            continue
        if rid in seen:
            bad.append(f"{tag}: duplicate id")
            continue
        seen.add(rid)
        if not str(e.get("why") or "").strip():
            bad.append(f"{tag}: `why` is required and non-empty (it ships in the Source Ledger)")
            continue
        if not str(e.get("verified_by") or "").strip():
            bad.append(f"{tag}: `verified_by` is required (it ships in the Source Ledger)")
            continue
        prop = e.get("property")
        if not isinstance(prop, dict) or not (prop.get("key") or prop.get("id") is not None):
            bad.append(f"{tag}: `property` needs a `key` and/or an `id`")
            continue
        sets = e.get("set") or {}
        media = e.get("media") or {}
        if not isinstance(sets, dict) or not isinstance(media, dict):
            bad.append(f"{tag}: `set`/`media` must be objects")
            continue
        if not sets and not media:
            bad.append(f"{tag}: nothing to do - give a `set` and/or a `media`")
            continue
        denied = sorted(set(sets) & DENIED_FIELDS)
        if denied:
            bad.append(f"{tag}: {', '.join(denied)} is structural or a dataset-wide unit label "
                       f"and can never be repaired - correct the figures themselves")
            continue
        unknown = sorted(k for k in sets if k not in canon)
        if unknown:
            bad.append(f"{tag}: {', '.join(unknown)} is not a canonical property field "
                       f"(a typo cannot be allowed to create one)")
            continue
        blank = sorted(k for k, v in sets.items()
                       if v is None or (isinstance(v, str) and not v.strip()))
        if blank:
            bad.append(f"{tag}: {', '.join(blank)} is blank - a repair sets a value, it never "
                       f"clears one (an empty ledger cell hard-blocks the build)")
            continue
        bad_slot = sorted(k for k in media if k not in MEDIA_SLOTS)
        if bad_slot:
            bad.append(f"{tag}: media slot(s) {', '.join(bad_slot)} unknown "
                       f"(expected {', '.join(MEDIA_SLOTS)})")
            continue
        out.append(e)
    return out, bad


def _resolve(props: list, prop_ref: dict) -> tuple[int | None, str | None]:
    """-> (index, failure_kind). failure_kind in {'stale','ambiguous'} when index is None."""
    want_key = str(prop_ref.get("key") or "").strip().lower()
    want_id = prop_ref.get("id")
    by_key = [i for i, p in enumerate(props) if want_key and _mk(p).lower() == want_key]
    by_id = [i for i, p in enumerate(props)
             if want_id is not None and str(p.get("id")) == str(want_id)]
    if want_key and want_id is not None:
        if not by_key and not by_id:
            return None, "stale"
        if by_key and by_id:
            # INTERSECT, never compare first hits. A match key is city|developer|park, so any
            # two properties in one park share it - `by_key=[5,6,7]` beside `by_id=[6]` is a
            # shared key the id RESOLVES, not a disagreement, and reading it as one made the
            # documented "give both" form fail closed on every multi-unit park. An id inside
            # the key's matches disambiguates; an id OUTSIDE them is a genuine key/id conflict
            # and still fails closed.
            both = [i for i in by_key if i in by_id]
            if not both:
                return None, "ambiguous"
            hits = both
        else:
            hits = by_key or by_id
    else:
        hits = by_key or by_id
    if not hits:
        return None, "stale"
    if len(hits) > 1:
        return None, "ambiguous"
    return hits[0], None


def apply(canonical: dict, entries: list, base_dir: Path | None = None) -> dict:
    """Apply in place. Returns a report dict with the five REPORT_KEYS."""
    rep = {k: [] for k in REPORT_KEYS}
    props = canonical.get("properties") or []
    for e in entries:
        rid = e["id"]
        idx, fail = _resolve(props, e["property"])
        if idx is None:
            rep[fail].append({
                "id": rid,
                "reason": (f"`property` matched {'no' if fail == 'stale' else 'more than one'} "
                           f"property - applied NOTHING. Check the key against "
                           f"work/properties/ (the projection names every property's key)."),
            })
            continue
        p = props[idx]
        exp = e.get("expect") or {}
        sets = e.get("set") or {}
        # A repair is RE-APPLIED on every run, so after the first pass the field already holds
        # the target and a naive `expect` check would call its own success a supersede. That is
        # not hypothetical: resume skips merge when nothing upstream changed, so the second run
        # of any guarded repair would refuse, leave the value in place with no fresh ledger row,
        # and trace-coverage would then block it as untraceable. A field that already equals
        # what this entry sets is therefore ALREADY APPLIED, not drift; anything else still
        # supersedes.
        wrong = [k for k, v in exp.items()
                 if not _expect_same(p.get(k), v)
                 and not (k in sets and _same(p.get(k), sets[k]))]
        if wrong:
            rep["superseded"].append({
                "id": rid,
                "reason": (f"`expect` said {', '.join(f'{k}=={exp[k]!r}' for k in wrong)} but the "
                           f"property now holds "
                           f"{', '.join(f'{k}=={p.get(k)!r}' for k in wrong)} - applied NOTHING. "
                           f"The dataset moved under this entry; re-check it against the source."),
            })
            continue
        changed = {}
        for k, v in (e.get("set") or {}).items():
            changed[k] = {"from": p.get(k), "to": v}
            p[k] = v
        # A merge-time plausibility-gate strike writes a permanent-sounding
        # `meta.conflicts` sentence ("... so the card ships tbd ...") BEFORE this repair
        # ever runs. Once the repair restores a real value that sentence is simply false,
        # and it ships verbatim into the Gaps Report alongside the (correct) repair note -
        # a live run shipped three such contradictions to the client. Annotate the stale
        # sentence in place (never delete - the strike's own reasoning is still real audit
        # history) rather than leave a false claim standing next to its own correction.
        # NOTE: do not skip on ch["from"] == ch["to"] here - resume/caching means a repair
        # already applied on a PRIOR run reads back as a same-value no-op on this run, but
        # merge.py's meta.conflicts is a leftover from the ORIGINAL (pre-repair) merge pass
        # and never regenerates on a resumed run, so the stale note can easily still be sitting
        # unannotated even when this run's `changed` looks like a no-op.
        pid = p.get("id")
        conflicts = (canonical.get("meta") or {}).get("conflicts")
        if isinstance(conflicts, list):
            for field, ch in changed.items():
                if ch["to"] in (None, "tbd"):
                    continue  # nothing to correct the note WITH - the field is still unknown
                prefix = f"id {pid} {field}:"
                # Two stale-note shapes precede this repair: a plausibility-band STRIKE
                # ("... so the card ships tbd ...") and a cross-source VALUE-CONFLICT note
                # ("discarded 'X' from <source> (kept 'Y')") where this repair overrides the
                # precedence winner Y that the note itself still asserts as current. Both are
                # stale the instant the repair lands and both must be annotated, not just the
                # first - a "kept 'Y'" note about a value this repair just replaced is exactly
                # as false to a broker as a "ships tbd" note about a value now restored.
                kept_marker = f"kept '{ch['from']}')" if ch["from"] is not None else None
                for i, note in enumerate(conflicts):
                    if not isinstance(note, str) or not note.startswith(prefix) \
                            or "[RESOLVED" in note:
                        continue
                    if "ships tbd" in note:
                        conflicts[i] = (f"{note} [RESOLVED by repair {rid}: the card now ships "
                                        f"{ch['to']!r}, not tbd - see \"Manual corrections "
                                        f"applied (property-level repairs)\" below.]")
                    elif kept_marker and kept_marker in note:
                        conflicts[i] = (f"{note} [RESOLVED by repair {rid}: the card now ships "
                                        f"{ch['to']!r}, not {ch['from']!r} - see \"Manual "
                                        f"corrections applied (property-level repairs)\" below.]")
        media = {}
        for slot, rel in (e.get("media") or {}).items():
            src = Path(rel)
            if base_dir is not None and not src.is_absolute():
                src = Path(base_dir) / rel
            if not src.exists():
                rep["invalid"].append(f"repair {rid}: media file not found: {src}")
                continue
            uri = _image_uri(src, slot)
            if uri is None:
                rep["invalid"].append(f"repair {rid}: {src.name} could not be decoded as an image")
                continue
            if slot == "hero":
                # the hero IS gallery[0] (v12), so both move together or the carousel
                # would open on the photo this repair was written to replace
                gal = [g for g in (p.get("gallery") or []) if g != p.get("photo")]
                p["photo"] = uri
                p["gallery"] = [uri] + gal
            else:
                p[slot] = uri
            media[slot] = src.name
        rep["applied"].append({
            "id": rid, "property_id": p.get("id"), "key": _mk(p),
            "changed": changed, "media": media,
            "why": e.get("why", ""), "verified_by": e.get("verified_by", ""),
        })
    return rep


def ledger_rows(rep: dict) -> list[dict]:
    """One Source Ledger row per repaired field, so the change is disclosed, not laundered."""
    rows = []
    for a in rep.get("applied", []):
        for field, ch in (a.get("changed") or {}).items():
            rows.append({
                "property_id": a.get("property_id"), "record_type": "repair", "field": field,
                "value": ch["to"], "source_file": "repairs.json",
                "source_locator": a["id"], "source_type": "repair", "extractor": "repairs.py",
                "confidence": "verified",
                "conflict_note": (f"property-keyed repair {a['id']}: {a.get('why','')} "
                                  f"(was {ch['from']!r})"),
                "verified": a.get("verified_by", ""),
            })
    return rows


def format_report(rep: dict) -> list[str]:
    """Operator-facing lines, in the same voice as the override outcomes run.py prints."""
    out = []
    for a in rep.get("applied", []):
        for f, ch in (a.get("changed") or {}).items():
            out.append(f"  - {a['id']}: property {a.get('property_id')} {f}: "
                       f"{ch['from']!r} -> {ch['to']!r}  ({a.get('why','')})")
        for slot, path in (a.get("media") or {}).items():
            out.append(f"  - {a['id']}: property {a.get('property_id')} {slot} image <- "
                       f"{Path(path).name}  ({a.get('why','')})")
    for key, tag in (("stale", "STALE REPAIR"), ("ambiguous", "AMBIGUOUS REPAIR"),
                     ("superseded", "SUPERSEDED REPAIR")):
        for s in rep.get(key, []):
            out.append(f"[{tag}] {s['id']} {s['reason']}")
    for s in rep.get("invalid", []):
        out.append(f"[INVALID REPAIR] {s} - this entry does NOTHING until it is fixed.")
    return out


def run(work: Path, write: bool = True) -> dict:
    work = Path(work)
    cpath = work / "canonical.json"
    entries, invalid = load(work / "repairs.json")
    canonical = json.loads(cpath.read_text(encoding="utf-8-sig")) if cpath.exists() else {}
    rep = apply(canonical, entries, base_dir=work) if entries else {k: [] for k in REPORT_KEYS}
    rep["invalid"] = list(rep.get("invalid", [])) + list(invalid)
    if write and rep["applied"]:
        C.atomic_write_text(cpath, json.dumps(canonical, ensure_ascii=False)) \
            if hasattr(C, "atomic_write_text") else \
            cpath.write_text(json.dumps(canonical, ensure_ascii=False), encoding="utf-8")
    (work / "repairs_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("apply", "check"))
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    rep = run(Path(a.work), write=(a.cmd == "apply"))
    for line in format_report(rep):
        print(line)
    n = len(rep["applied"])
    bad = sum(len(rep[k]) for k in ("stale", "ambiguous", "superseded", "invalid"))
    print(f"OK {n} repair(s) applied, {bad} not applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
