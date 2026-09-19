#!/usr/bin/env python3
"""deliver.py - Stage 7. Assemble the three deliverables.

  1. the dashboard .html (copied into deliverables/ under the project filename)
  2. <slug>_Source_Ledger.xlsx (via ledger.py) - field-level traceability, one row
     per (property, field) -> the source file + locator it came from.
  3. <slug>_Gaps_Report.md - every 'tbd', unmatched asset, conflict and
     enrichment gap, each with a 'how to close it' note. Honest by construction.
  4. <slug>_Longlist.xlsx - a FLAT data view: one property per ROW, variables in
     COLUMNS (the broker-facing table). Sits alongside the Source Ledger, which keeps
     the field-level provenance. Falls back to CSV if openpyxl is unavailable.

CLI:
  python deliver.py --canonical canonical.json --html built.html --ledger ledger.csv \
                    --out-dir deliverables [--slug Normal] [--filename name.html]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

import _common as C
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MARKER_NAME = ".delivery_complete.json"  # written LAST by main(); see B01 at the write site

# F14: the client name is FREE TEXT from the Stage-0 form and the spine hands it straight in as
# --slug, so a name carrying a full stop produced `<Name>._Gaps_Report.md` and a name with spaces
# produced spaced filenames in the broker's output folder. Only the FILENAME component is
# sanitised here; the report title, the ledger and the marker keep the broker's exact text,
# because the client's name on the page is data and a filename is not.
_SLUG_JUNK = re.compile(r"[^A-Za-z0-9]+")
SLUG_FALLBACK = "Longlist"


def safe_slug(raw) -> str:
    """One filename component from a free-text client name: runs of anything that is not an
    ASCII letter or digit collapse to ONE underscore, leading/trailing underscores go, and an
    empty result falls back to SLUG_FALLBACK so a filename can never start with the suffix.

    IDEMPOTENT by construction (safe_slug(safe_slug(x)) == safe_slug(x)), which matters because
    final_gate derives the slug BACK out of the Gaps Report filename (it strips
    `_Gaps_Report.md`) and feeds it to this script again as --slug; a non-idempotent sanitiser
    would write a second report beside the first. Every name it produces still matches
    intake._OWN_OUTPUT (which keys on the SUFFIXES), so a re-run in the same folder still
    refuses to ingest its own deliverables."""
    s = _SLUG_JUNK.sub("_", str(raw or "")).strip("_")
    return s or SLUG_FALLBACK


def delivery_complete(out_dir, marker_dir=None) -> bool:
    """True only when a delivery finished AND everything it vouched for is still present.

    The Stage-7 resume guard keys on THIS, not on the dashboard. The dashboard is written
    first, so keying on it meant an incomplete delivery satisfied the guard forever. (B01)

    `marker_dir` is where the marker itself lives; the artefacts it names are ALWAYS
    resolved against `out_dir`. It exists because the marker is a TECHNICAL completion
    record, not a deliverable: in the three-folder layout the out dir is the broker's
    '3. Output' folder, which must hold the four client-facing files and nothing else, so
    the spine keeps the marker in the work dir. Defaults to `out_dir` (the legacy
    location), and the legacy location is still ACCEPTED as a fallback so a project
    delivered before the split is still recognised as complete instead of re-delivering."""
    out = Path(out_dir)
    cands = [Path(marker_dir) / MARKER_NAME] if marker_dir else []
    cands.append(out / MARKER_NAME)
    for m in cands:
        try:
            rec = json.loads(m.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        names = rec.get("artefacts")
        if not isinstance(names, list) or not names:
            continue
        if all((out / str(n)).exists() for n in names):
            return True
    return False


CORE = ["warehouseArea", "warehouseRent", "status", "city", "developer", "lat", "lng",
        "clearHeight", "earlyAccess", "motorway"]
CLOSE = {
    "warehouseRent": "request a headline rent from the landlord/agent",
    "warehouseArea": "confirm GLA with the developer",
    "clearHeight": "request the technical spec sheet",
    "lat": "geocode the site or ask for an exact pin",
    "lng": "geocode the site or ask for an exact pin",
    "motorway": "confirm the nearest motorway/corridor",
    "earlyAccess": "confirm the delivery / early-access date",
}


# Fields that are NEVER a broker chase, and why. Three groups, each load-bearing:
#  * INTERNAL / DERIVED - ids, media, the numeric twins of a display string, unit labels.
#  * THE PIPELINE'S OWN "not applicable" MARKERS - `landPrice` and `reit`. merge.py carves
#    both out of unknown-handling (twice, with the identical `field not in ("landPrice",
#    "reit")` line) and _common.fill_render_sentinels writes landPrice = BLANK (v45; it
#    used to write a long dash of its own). Listing them
#    would report a missing land price and a missing REIT flag for EVERY property in EVERY
#    lease-only longlist - measured: 2 of 11 phantom chases on a well-sourced UK property.
#  * `country`/`region` - ENRICHMENT DERIVES these (enrich.py fills an unknown country from
#    coordinates, with its own ledger trace), so telling a broker to chase an agent for a
#    field the next pass fills is a wrong action.
NOT_CHASEABLE = {
    "id", "photo", "plan", "gallery", "lat", "lng",          # lat/lng stay in CORE instead
    "warehouseAreaVal", "officeAreaVal", "warehouseRentVal", "officeRentVal",
    "areaUnit", "rentUnit", "regionCode", "preBaked", "distances",
    "landPrice", "reit",                                      # "not applicable" markers
    "country", "region",                                      # derived by enrichment
}


def _is_tbd(v):
    """Unknown for Gaps-Report purposes: the ONE shared predicate, nothing added.

    Until v41 this ADDED `"??"` locally because normalize.looks_unknown did not carry it, and
    its docstring defended the local widening by the blast radius of the shared set (it feeds
    _common.core_fill -> record_is_poor -> run.py's vision-routing probe). Fix plan contract C5
    measured that radius and moved `"??"` into the shared family on purpose: the only field
    the pipeline writes `"??"` into is `country`, which no core_fill field reads, so the routing
    probe is unchanged by it; and a record whose city or status a reader shipped as `TBA` IS
    thinner, so re-reading it is the right routing. Kept as a named wrapper because run.py's
    ship-readiness probe imports it by this name."""
    return C._N.looks_unknown(v)


def _chaseable_fields(props: list[dict]) -> list[str]:
    """Every field a broker could actually chase, in a stable order.

    Derived from the fields the DATA carries (union across properties) intersected with the
    schema, minus NOT_CHASEABLE - never from the schema alone, so a field this dataset's
    market does not use is not invented into an action list."""
    try:
        schema = json.loads(Path(C.SCHEMA_FILE).read_text(encoding="utf-8-sig"))
        allowed = set(((schema.get("$defs", {}).get("property", {})
                        or {}).get("properties", {}) or {}).keys())
    except Exception:
        allowed = set()
    seen: set = set()
    for p in props:
        seen |= set(p.keys())
    pool = (seen & allowed) if allowed else seen
    # `*Val` is the derived NUMERIC TWIN of a display string (warehouseAreaVal,
    # expansionParkVal, ...). It is never a broker chase - the string it mirrors already is.
    # Excluded by SUFFIX, not by enumeration, so a future twin cannot leak in.
    return [f for f in sorted(pool - NOT_CHASEABLE - set(CORE)) if not f.endswith("Val")]


def _struck_map(meta: dict) -> dict:
    """(property id as a string, field) -> its `meta.struck` row. (A11)

    The strike ledger records a field a source DID state and the plausibility band then
    rejected, per property and per field. Read here so the honesty report can tell the two
    kinds of unknown apart: a field nothing stated, and a field something stated that did
    not survive the band. They need opposite advice, and until this map existed the report
    gave the absent-field advice to both.

    ABSENT-TOLERANT on purpose, exactly like `meta.enrichmentGaps` and `meta.conflicts`
    below: a canonical written before merge recorded the ledger (an older work directory, a
    re-delivery of an archived run) simply yields an empty map and every consumer below
    behaves as it did before. Malformed rows are skipped rather than raising - this function
    runs while a client deliverable is being written, and no shape of one meta key may cost
    the whole Gaps Report."""
    out: dict = {}
    for e in (meta.get("struck") or []):
        if not isinstance(e, dict):
            continue
        f = str(e.get("field") or "").strip()
        if not f or e.get("id") is None:
            continue
        out[(str(e.get("id")).strip(), f)] = e
    return out


def _close_note(field: str, struck: dict | None = None) -> str:
    """How to close a gap.

    Bespoke, party-naming advice lives ONLY in CLOSE. Everything else gets a
    PROVENANCE-shaped note, never a party-shaped one: which counterparty holds a given
    figure is a fact about the deal that Python is not entitled to assert (a standing
    second-hand building's counterparty is a landlord, not a developer).

    `struck` is this property's `meta.struck` row for this field, when there is one. It
    takes precedence over BOTH the CLOSE advice and the default, because a struck field is
    unknown for the OPPOSITE reason to an absent one and the default text asserted the
    absence outright: "not stated in any source supplied for this property", printed against
    a field whose source file and parsed figure this same document names a few sections lower
    under Source conflicts. A live G-honesty review read that contradiction straight back off
    a delivered report (four properties, the struck field quoted verbatim from the deck). It
    beats CLOSE too: sending the reader to chase a figure that is already in the pack, in the
    extract and in the ledger is a wrong action, not merely a redundant one. (A11)"""
    if struck:
        # Kept SHORT and pointed at the ledger row rather than restating it: this note is
        # printed once per struck field per property, and one live run struck seven genuinely
        # printed values across six properties. The Source conflicts row carries merge's full
        # reasoning and the figure as it was parsed, so repeating either here would only crowd
        # out the two things the reader needs on this line - that a source does state it, and
        # what to do about it.
        src = str(struck.get("source_file") or "").strip()
        return ((f"{src} DOES state a value" if src else "a source DOES state a value")
                + " for this field and the parsed figure fell outside the plausibility band, "
                  "so the card ships the honest unknown - see Source conflicts below for the "
                  "value as it was read, then either restore it via `work/repairs.json` if the "
                  "source genuinely prints it or confirm the real figure with the agent")
    return CLOSE.get(field, "not stated in any source supplied for this property - ask the "
                            "sender if it is decision-relevant")


def _email_attachments_skipped(work_dir: Path | None) -> list:
    """Markdown lines for attachments the email reader REFUSED as inline images.

    extract_email drops an attachment that carries a Content-ID with no filename, or that is
    under 20 KB, because a broker signature block is five to twenty logos, award badges and
    social icons per email and every one of them otherwise lands in the inputs folder as a
    candidate hero photo. The rules are blunt on purpose and they are right almost always -
    but "almost" is doing real work there. A one-page floor plan exported thin, a site plan
    saved as a 14 KB PNG, a unit plan a broker screenshotted: each is a genuine document that
    this filter throws away, and until now the refusal was recorded in inventory.json and
    nowhere a human reads. The client got a dashboard with no site plan and no line anywhere
    saying one had arrived and been refused, which is precisely the silent-drop failure the
    rest of this report exists to prevent. So the refusals are printed: subject, filename,
    size and the rule, which is enough for a reader to say "that is a brochure" and fetch it.

    ABSENT-TOLERANT like every other work-dir read here: no inventory, an old inventory with
    no attachment record, or a malformed one yields no section rather than costing the report.
    """
    inv_p = (Path(work_dir) / "inventory.json") if work_dir else None
    if not inv_p or not inv_p.exists():
        return []
    try:
        inv = json.loads(inv_p.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    out: list = []
    for e in (inv.get("email_attachments") or []):
        if not isinstance(e, dict):
            continue
        who = str(e.get("subject") or "").strip() or str(e.get("email") or "").strip() or "(email)"
        for s in (e.get("skipped_inline") or []):
            if not isinstance(s, dict):
                continue
            try:
                kb = f"{int(s.get('bytes') or 0) / 1024:.1f} KB"
            except (TypeError, ValueError):
                kb = "size unknown"
            out.append(f"- **{who}** - `{s.get('name') or '(unnamed)'}` ({kb}): "
                       f"{s.get('why') or 'refused by the inline-image filter'}")
    if not out:
        return []
    return (["## Email attachments not read",
             "Refused by the inline-image filter, which exists to keep signature logos and "
             "award badges out of the run. Almost all of these are exactly that. Check the "
             "list anyway: a thin floor plan or a screenshotted unit plan is a real document "
             "that trips the same rule, and if one is listed below it is NOT in the "
             "dashboard. Forward it separately and re-run to include it."]
            + out + [""])


def master_list_lines(work_dir) -> list:
    """The Gaps Report's account of the MASTER LIST: what the user struck off, or that nobody
    was asked.

    An option removed from a client's own longlist must be VISIBLE. The exclusions here are the
    most defensible ones in the whole run - a named person looked at a named option and said no -
    and they are also the easiest to forget, because the option leaves before any card exists, so
    nothing downstream has a shape to report. Named here, by name and with the reason the sheet
    carried, so a reader comparing the dashboard against their own shortlist can see why an
    option they remember is not on it.

    The headless case gets its own paragraph rather than silence. A cron run cannot put a sheet
    to anybody, so it includes everything - which is the run's honest pre-master-list behaviour,
    but a reader who knows the sheet exists would otherwise assume somebody answered it.
    """
    if not work_dir:
        return []
    # SCOPE SETTLED UPSTREAM. A wrapper skill that owns the scope decision (project.yaml
    # `master_list: {mode: external}`) declines this skill's stop, so there is no sheet here to
    # report on and no exclusions of this skill's making to name. ONE line, not a section: a
    # reader comparing the dashboard against their own shortlist still needs to know where the
    # options were chosen and by whom, and silence would read as "nobody chose", which is the
    # exact misreading the headless paragraph below exists to prevent.
    try:
        _ext = json.loads((Path(work_dir) / "master_list_external.json")
                          .read_text(encoding="utf-8-sig"))
    except Exception:
        _ext = None
    if isinstance(_ext, dict) and str(_ext.get("mode") or "") == "external":
        return [f"Scope for this longlist was settled before this run, not on a sheet here: "
                f"{_ext.get('confirmed_by') or 'the calling skill'}.", ""]
    try:
        ml = json.loads((Path(work_dir) / "master_list.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(ml, dict) or not ml.get("rows"):
        return []
    out: list = []
    if ml.get("skipped"):
        out.append("## Scope was not put to you (the run decided)")
        out.append("This run was set to decide sensibly rather than ask, so the master list - "
                   "the sheet where you choose which options are built - was never put to "
                   "anyone, and EVERY option found in your files is on the dashboard: "
                   f"{(ml.get('counts') or {}).get('rows', '?')} of them. Reason on record: "
                   f"{ml.get('reason') or 'headless run'}. Re-run interactively to choose.")
        out.append("")
        return out
    rows = [r for r in ml.get("rows") or [] if isinstance(r, dict)]
    excluded = [r for r in rows if str(r.get("include") or "") == "No"]
    if not excluded:
        return out
    out.append("## Options excluded by the master list")
    out.append("You were shown every option this run found, on one sheet, before the brochures "
               "were read. These are the ones you marked **No**, so they were not built - their "
               "brochures were not read and they are not on the dashboard. Nothing failed. To "
               "bring one back, set its Include? to Yes on `Master List.xlsx`, re-read the sheet "
               "and re-run.")
    for r in sorted(excluded, key=lambda x: str(x.get("property") or "")):
        src = str(r.get("source") or "; ".join(r.get("source_files") or []) or "?")
        why = []
        if r.get("deleted_from_workbook"):
            why.append("the row was DELETED from the workbook rather than answered, which is "
                       "indistinguishable from a botched sort, so it was treated as No")
        if r.get("duplicate_group"):
            why.append(f"in duplicate group {r['duplicate_group']}")
        note = str(r.get("run_notes") or "").strip()
        if note:
            why.append(f"your note: {note}")
        out.append(f"- **{r.get('property') or '(unnamed row)'}** ({r.get('source_type') or '?'})"
                   f" - found in: {src}" + (f". {'; '.join(why)}." if why else "."))
    out.append("")
    return out


def gaps_report(canonical: dict, slug: str, work_dir: Path | None = None) -> str:
    props = canonical["properties"]
    meta = canonical.get("meta", {})
    lines = [f"# {slug} - Longlist Gaps Report", "",
             f"Generated {meta.get('generatedAt','')} from {len(props)} properties. "
             "Every item below is a genuine unknown surfaced honestly, not a defect. "
             "Close them with the landlord/agent before the dashboard goes to the client.", ""]

    # per-property tbd core fields
    lines.append("## Missing data by property")
    any_gap = False
    for p in props:
        tbd = [f for f in CORE if _is_tbd(p.get(f))]
        if tbd:
            any_gap = True
            notes = "; ".join(f"`{f}` ({CLOSE.get(f,'confirm with source')})" for f in tbd)
            lines.append(f"- **{p.get('park','?')}** ({p.get('city','?')}, id {p.get('id')}): {notes}")
    if not any_gap:
        lines.append("- None - every property carries all core fields.")
    lines.append("")

    # EVERY OTHER unknown, not just the core ten. Both critical reviewers concluded that
    # listing only CORE is WHY an extraction miss ships invisibly: the card shows `tbd`, the
    # ledger asserts "absent in all sources", and nothing in the delivered pack points at
    # it. Split in two so the action list stays readable:
    #   (1) per-property chases for fields SOME property carries - a real gap, because the
    #       market clearly quotes that attribute;
    #   (2) an INVENTORY of fields NO source carried for any option. These are NOT chases:
    #       the dashboard itself drops such a field (the chrome's FIELD_PRESENT hides a row
    #       no input ever filled), so calling them actions would invert the product's own
    #       rule and bury the real gaps under phantoms.
    chase = _chaseable_fields(props)
    carried = {f for f in chase if any(not _is_tbd(p.get(f)) for p in props)}
    # A11: A STRUCK FIELD IS NOT AN ABSENT ONE, and both lists below used to say it was.
    # `carried` asks only whether some property still HOLDS a real value, so a field a source
    # stated and the plausibility band struck to the unknown sentinel on every property landed
    # in `never` - printed under a heading asserting that no input carried it for any option
    # and that this market does not quote it, in the same document whose Source conflicts
    # section names the file and quotes the parsed figure. The two halves of one deliverable
    # contradicting each other is the worst failure this report can have: it is read precisely
    # to learn what is missing, and it was asserting an absence it elsewhere disproved.
    #
    # So the struck fields are subtracted from `never` AND added to the per-property chase
    # list. Subtracting alone would be a half-fix that turns a false statement into silence:
    # a field struck on every property would then appear in no section at all, while the
    # dashboard's own FIELD_PRESENT rule hides it from the cards, so the ONLY trace left would
    # be a ledger row the reader has no reason to look for. It belongs in the actionable half
    # by the same test that section already applies - a source quoted this attribute, so the
    # market quotes it - and each property's line then reads on its own merit: struck here,
    # genuinely absent there (`_close_note` decides per property, per field).
    struck = _struck_map(meta)
    struck_fields = {f for _i, f in struck} & set(chase)
    never = [f for f in chase if f not in carried and f not in struck_fields]

    reqs = meta.get("requirements") or {}
    lines.append("## Other missing fields by property")
    if reqs:
        lines.append(f"Ordered by this client's stated requirements first "
                     f"({', '.join(sorted(str(k) for k in reqs)[:8])}).")
    else:
        lines.append("No client requirements were supplied, so this list is the full set of "
                     "attributes the market quoted for at least one option - it is not "
                     "scoped to a brief.")
    _req_first = sorted(carried | struck_fields, key=lambda f: (f not in reqs, f))
    any_other = False
    for p in props:
        tbd = [f for f in _req_first if _is_tbd(p.get(f))]
        if tbd:
            any_other = True
            # THE PARTIAL CASE, which is the common one: a band strikes a field on some
            # properties and no source ever stated it on the rest. The strike row is keyed to
            # (id, field), so the note is decided per property and the same field reads
            # correctly on every line it appears on. A field whose strike was later repaired
            # (or overridden, or won by another source) now holds a real value and never
            # reaches this list at all, so a stale strike row cannot resurrect a closed gap.
            _pid = str(p.get("id")).strip()
            notes = "; ".join(f"`{f}` ({_close_note(f, struck.get((_pid, f)))})" for f in tbd)
            lines.append(f"- **{p.get('park','?')}** ({p.get('city','?')}, "
                         f"id {p.get('id')}): {notes}")
    if not any_other:
        lines.append("- None - every property carries every attribute the market quoted.")
    lines.append("")

    if never:
        lines.append("## Fields no source provided for any longlist entry")
        lines.append("Not action items: no input carried these for any option, so the "
                     "dashboard hides them entirely. Listed only so you can see what this "
                     "market does not quote - chase one only if the brief calls for it.")
        lines.append("- " + ", ".join(f"`{f}`" for f in never))
        lines.append("")

    # enrichment gaps
    eg = meta.get("enrichmentGaps", [])
    lines.append("## Enrichment gaps")
    lines += ([f"- {g}" for g in eg] if eg else ["- None."])
    lines.append("")

    # unmatched assets. NOTE the `in meta` test rather than a truthiness test: NO code path
    # writes meta.unmatchedAssets today (readers exist here and in gate_runner, a writer never
    # did), so an empty list was indistinguishable from "never computed" and every Gaps Report
    # printed the FALSE affirmative "None - every image bound to a property". Claiming a check
    # that never ran is exactly the kind of unearned assurance this report exists to avoid.
    # When a writer lands (with the inventory->properties reconciliation floor), the affirmative
    # becomes true and this needs no further change.
    lines.append("## Unmatched assets")
    if meta.get("unmatchedAssets"):
        lines += [f"- {a}" for a in meta["unmatchedAssets"]]
    elif "unmatchedAssets" in meta:
        lines.append("- None - every image bound to a property.")
    else:
        lines.append("- Not checked: image-to-property binding is not yet reconciled against the "
                     "input folder, so this run cannot confirm every supplied image was used. "
                     "Compare the folder's images against the cards if that matters.")
    lines.append("")

    # conflicts
    cf = meta.get("conflicts", [])
    lines.append("## Source conflicts")
    lines += ([f"- {c}" for c in cf] if cf else ["- None recorded."])
    lines.append("")

    # I10: notation variants. These are NOT conflicts - two sources stating the same fact in
    # different notation. They are listed so nothing is hidden (the Data Honesty Standard), and
    # kept OUT of "Source conflicts" so that list stays actionable: padding it with "12.5 m vs
    # 12.5" trains a broker to skim past the entries that need a call to the agent.
    nv = meta.get("notationVariants", [])
    lines.append("## Notation variants (same value, stated differently - no action needed)")
    if nv:
        lines.append("Checked and found to denote the same fact - a unit prefix, a date format, a "
                     "qualifier, or a scheme name inside its own full address.")
        lines += [f"- {v}" for v in nv]
    else:
        lines.append("- None recorded.")
    lines.append("")

    # off-spec keys quarantined at the render boundary (v22 Phase 1)
    osp = meta.get("offspec", [])
    lines.append("## Off-spec keys (quarantined provenance/meta - not shown on cards)")
    if osp:
        for e in osp:
            lines.append(f"- property {e.get('property_id')}: `{e.get('key')}` = {e.get('value')} "
                         f"(add to canonical.schema.json + template to display as a real value)")
    else:
        lines.append("- None.")
    lines.append("")

    # B7: brand-new SCALAR fields. Unlike the off-spec keys above these are KEPT and shown on the
    # card - the pipeline deliberately auto-shows any real scalar attribute. They are listed so the
    # drift is visible: `postcode` once shipped on half a longlist's properties while the section
    # above read "None.", because that section only covers quarantined structures.
    nf = meta.get("newFields", [])
    lines.append("## Fields shown but not declared in the schema")
    if nf:
        lines.append("These are real, sourced values and they DO appear on the card - the dashboard "
                     "auto-shows any scalar attribute. They are listed because the schema does not "
                     "declare them, so nothing else would record that. Declare one in "
                     "`templates/canonical.schema.json` to make it first-class.")
        for e in nf:
            lines.append(f"- property {e.get('property_id')}: `{e.get('key')}`"
                         + (f" (from {e.get('source_file')})" if e.get("source_file") else ""))
    else:
        lines.append("- None - every shown field is declared.")
    lines.append("")

    # possible site plans not captured: a page LOOKED plan-ish (classified 'plan' out of band, or
    # carried a plan title) but a precision guard rejected it and no plan bound - surfaced so a
    # genuinely missed plan is visible (never binds a wrong image; honest miss over false plan).
    pnm = meta.get("planNearMiss", [])
    lines.append("## Possible site plans not captured")
    if pnm:
        for e in pnm:
            for pg in e.get("pages", []):
                loc = f"{pg.get('file', '?')} page {int(pg.get('page', 0)) + 1}"
                lines.append(f"- **{e.get('property', '?')}** ({e.get('city', '')}): {loc} - "
                             f"{pg.get('why', '')} (check the deck; if it is the site plan, "
                             f"set __meta.plan_page)")
    else:
        lines.append("- None.")
    lines.append("")

    # ASSUMED UNITS: the source stated a numeric area but never named its unit, so the
    # dataset's dominant unit was applied WITHOUT conversion. Surfaced because the failure is
    # silent and large - a metric figure labelled sq ft is out by 10.76x, and the magnitude
    # cross-check is blind across the whole realistic warehouse range. Chase the source.
    ua = meta.get("unitAssumptions", [])
    # D11: the list now also carries ONE dataset-level entry (field "rentUnit", id "dataset")
    # when no source states a rent unit and merge derived the display basis from the dominant
    # area unit and country. It is a different kind of assumption - a label convention, with no
    # figure behind it to convert - so it gets its own heading and its own wording rather than
    # the area sentence, which would tell the broker to convert a number that does not exist.
    ua_area = [e for e in ua if isinstance(e, dict) and e.get("field") != "rentUnit"]
    ua_rent = [e for e in ua if isinstance(e, dict) and e.get("field") == "rentUnit"]
    if ua_area:
        lines.append("## Area units assumed (source did not state one)")
        for e in ua_area:
            lines.append(f"- **{e.get('property', '?')}**: {e.get('field', 'areaUnit')} assumed "
                         f"**{e.get('assumed', '?')}** - {e.get('why', '')}. Confirm the source's "
                         f"own unit; if it differs, the figure needs converting, not relabelling.")
        lines.append("")
    if ua_rent:
        lines.append("## Rent basis assumed (no source states a rent unit)")
        for e in ua_rent:
            lines.append(f"- **{e.get('property', 'whole longlist')}**: the rent basis shown on "
                         f"the dashboard (hero KPI sub-label and card footers) is "
                         f"**{e.get('assumed', '?')}** - {e.get('why', '')}. If the market quotes "
                         f"on a different basis, state a rent unit in a source or confirm the "
                         f"convention with the agent; no rent figure was relabelled with it.")
        lines.append("")

    # MANUAL CORRECTIONS (P1-4). Disclosed in the DELIVERABLE, not just in work/: a value a human
    # corrected by hand is not source data, and the Gaps Report is the one document whose job is
    # honesty. A correction that has stopped matching belongs here too - that is the failure this
    # whole mechanism exists to make impossible to miss (it used to be completely silent).
    # B47: options the broker's SOURCE-AUTHORITY answer removed from the longlist. This sits
    # high in the report and names every one: excluding a property from a client's own list is
    # the most consequential thing the pipeline can do to the dataset, and the broker must be
    # able to see exactly what went and why without opening canonical.json.
    # CLARIFICATIONS (B49). Every question the run asked, and what was decided. The declines
    # matter more than the answers: a blocking question exists because its fall-through default
    # is itself the damage, so "the default was accepted" is a decision the client-facing
    # report has to carry. Read from the work dir, best-effort - a run delivered without one
    # (or with a malformed state file) simply omits the section rather than failing to deliver.
    try:
        import clarify as _CQ
        _st = _CQ.load_state(work_dir) if work_dir else {}
    except Exception:
        _st = {}
    _titles = _st.get("titles") or {}
    _answers, _declined = (_st.get("answers") or {}), list(_st.get("declined") or [])
    if _answers or _declined:
        lines.append("## Clarifications (what the run asked, and what was decided)")
        lines.append("The run stops and asks rather than presuming. Each line is a decision "
                     "that shaped the dataset.")
        for _i, _v in sorted(_answers.items()):
            _t = _titles.get(_i) or {}
            _subj = _t.get("subject") or _t.get("kind") or _i
            lines.append(f"- **{_subj}**: answered **{_v}**."
                         + (f" ({_t.get('question', '')})" if _t.get("question") else ""))
        for _i in sorted(_declined):
            _t = _titles.get(_i) or {}
            _subj = _t.get("subject") or _t.get("kind") or _i
            lines.append(f"- **{_subj}**: NO PREFERENCE GIVEN - the default was accepted "
                         f"deliberately. {_t.get('if_unanswered', '')}".rstrip()
                         + (f" ({_t.get('question', '')})" if _t.get("question") else ""))
        lines.append("")

    # NOT ASKED (B62). The run only stops for a question whose answer would change what the
    # client SEES - a figure, a photo or a label on the dashboard, or how many options ship.
    # Everything else it noticed is written down HERE instead of costing an interruption.
    # This is what makes that trade honest: the doubt is not resolved, not guessed at and not
    # lost, only disclosed rather than asked. It is also the channel through which a reader's
    # doubt reaches the broker on a HEADLESS run, which the record schema has always promised
    # and nothing previously delivered.
    #
    # TWO SECTIONS, SPLIT ON WHY IT WAS NOT ASKED, because they say different things to a
    # broker. Printing a doubt about which warehouse area is right under "no effect on what
    # the dashboard shows" asserts the opposite of what the run concluded, in a client-facing
    # document - so the material ones get their own heading and their own wording.
    _sup = _st.get("suppressed") or {}
    if isinstance(_sup, dict) and _sup:
        # an entry that has since been answered or declined belongs in Clarifications above,
        # not here - it would otherwise appear in both
        _settled = set(_answers) | set(_declined)
        _rows = [(_i, _e if isinstance(_e, dict) else {}) for _i, _e in sorted(
            _sup.items(), key=lambda kv: (str((kv[1] or {}).get("kind")),
                                          str((kv[1] or {}).get("subject"))))
            if _i not in _settled]

        def _fmt_row(_i, _e) -> str:
            _subj = str(_e.get("subject") or _e.get("kind") or _i).strip()
            _q = str(_e.get("question") or "").strip().rstrip(".")
            # the question already opens with the subject on some kinds; do not say it twice
            if _q.lower().startswith(_subj.lower() + ":"):
                _q = _q[len(_subj) + 1:].strip()
            _d = str(_e.get("if_unanswered") or "").strip().rstrip(".")
            for _p in ("proceeds with:", "proceeds with"):
                if _d.lower().startswith(_p):
                    _d = _d[len(_p):].strip()
                    break
            _src = str(_e.get("source_file") or "").strip()
            out = f"- **{_subj}**" + (f": {_q}." if _q else ".")
            if _d:
                out += f" What shipped: {_d}."
            if _src:
                out += f" (from {_src})"
            return out

        _mat = [r for r in _rows if str(r[1].get("materiality") or "") != "ledger"]
        _led = [r for r in _rows if str(r[1].get("materiality") or "") == "ledger"]
        if _mat:
            lines.append("## Noticed but not asked about (worth a look)")
            _hl = any(str(e.get("why_not_asked") or "") == "headless" for _, e in _mat)
            lines.append(
                "Each of these COULD change something on the dashboard, and the run did not "
                "stop to ask you about it"
                + (" because it was set to decide sensibly rather than ask (the 'Decide "
                   "sensibly' option at the start)." if _hl else
                   " because more of them came up than one round of questions can carry.")
                + " Every one kept the value the source itself gave - nothing was invented. "
                  "If any of them matters, tell the run and re-run it: put your answer to "
                  "the question in `work/answers.json`, or correct the value directly in "
                  "`work/overrides.json`.")
            lines += [_fmt_row(_i, _e) for _i, _e in _mat]
            lines.append("")
        if _led:
            lines.append("## Noted, not put to you (no effect on what the dashboard shows)")
            lines.append("The run asks you about anything that would change a figure, a photo "
                         "or an option on the dashboard. These are the things it noticed that "
                         "would NOT, so it recorded them here and carried on with the value "
                         "the source already gave. Nothing was invented and nothing was "
                         "dropped. If one of them matters to you after all, correct the value "
                         "in `work/overrides.json` and re-run.")
            lines += [_fmt_row(_i, _e) for _i, _e in _led]
            lines.append("")

    excluded = meta.get("excluded") or []
    if excluded:
        lines.append("## Options excluded (not evidenced by your guiding source)")
        lines.append("You told the run which source decides what belongs on this longlist, so "
                     "these options were left OFF. They were found and read normally - nothing "
                     "failed. If any of them should be on the list, re-run and answer the "
                     "source-authority question with 'the union of both'.")
        def _hfmt(hl: dict) -> str:
            v = (hl or {}).get("warehouseArea")
            if v is None:
                return ""
            s = f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
            u = (hl or {}).get("areaUnit") or ""
            return f"{s} {u}".strip()

        for e in excluded:
            srcs = ", ".join(e.get("source_files") or []) or "?"
            lines.append(f"- **{e.get('name', '(unnamed option)')}** - {e.get('why', '')} "
                         f"(found in: {srcs})")
            # RECORD-LEVEL CONFLICT: this excluded record plausibly IS a shipped card
            # (a forbidden/grey pair kept them from merging). Print the actual figures
            # side by side - suppressing a conflicting figure for a shipped property
            # must never read as a distinct option quietly disappearing.
            ls = e.get("likely_same_as") or {}
            if ls:
                mine = _hfmt(e.get("headline"))
                theirs = _hfmt(ls.get("kept_headline"))
                why_apart = ("a >15% size conflict kept them from being treated as one "
                             "property" if ls.get("tier") == "forbidden"
                             else "they were judged distinct, but the match was borderline")
                cmp_txt = (f": the excluded record states {mine}, the shipped card states "
                           f"{theirs}" if mine and theirs else "")
                lines.append(f"  - LOOKS LIKE SHIPPED OPTION **{ls.get('name')}** "
                             f"({why_apart}){cmp_txt}. Confirm which figure is right - "
                             f"the card currently shows only its own source's value.")
        lines.append("")

    # The user's own scope decision, immediately after the run's derived one, because a reader
    # asking "why is X not here?" should find both answers in one place.
    lines += master_list_lines(work_dir)

    ov = meta.get("overrides", {}) or {}
    applied = ov.get("applied") or []
    if applied:
        lines.append("## Manual corrections applied")
        lines.append("Each was applied to the extracted data AFTER extraction and is re-applied on "
                     "every run, so it survives a re-extraction. Every one also has an `override` "
                     "row in the Source Ledger.")
        for e in applied:
            w = e.get("where", {}) or {}
            for f, new in (e.get("set") or {}).items():
                lines.append(f"- **{f}**: `{e.get('old', {}).get(f)}` -> `{new}` "
                             f"({w.get('source_file', '?')} {e.get('locator', '')}) - "
                             f"{e.get('why', '')}"
                             + (f" [verified by {e['verified_by']}]" if e.get("verified_by") else ""))
        lines.append("")
    _rot = [(k, e) for k in ("stale", "ambiguous", "superseded", "invalid")
            for e in (ov.get(k) or [])]
    if _rot:
        lines.append("## Manual corrections that matched NOTHING (stale - fix or delete)")
        lines.append("These were NOT applied, so the data still holds whatever the source said. "
                     "Either correct the `where` block in `work/overrides.json` or delete the "
                     "entry - a correction nobody notices has stopped working is worse than none.")
        for k, e in _rot:
            if isinstance(e, str):          # `invalid` entries are plain reason strings
                lines.append(f"- **{k}**: {e}")
                continue
            lines.append(f"- **{e.get('id', '?')}** ({k}): {e.get('reason', '')} "
                         f"Intended: {e.get('set', {})} - {e.get('why', '')}")
        lines.append("")

    # PROPERTY-LEVEL corrections (work/repairs.json, applied post-merge) are a separate
    # mechanism from the SOURCE-RECORD overrides above, but a client reading the Gaps Report
    # for "what was manually changed" needs both in one place - the override section alone
    # under-discloses (a real run shipped six repairs.json value changes visible only as
    # `repair` rows in the Source Ledger, absent from this client-facing section entirely).
    rp_rep = {}
    if work_dir:
        try:
            rp_rep = json.loads((Path(work_dir) / "repairs_report.json")
                                 .read_text(encoding="utf-8-sig"))
        except Exception:
            rp_rep = {}
    rp_applied = rp_rep.get("applied") or []
    if rp_applied:
        lines.append("## Manual corrections applied (property-level repairs)")
        lines.append("Each was applied to the merged property AFTER matching (work/repairs.json), "
                     "keyed to the property rather than a single source record, and is "
                     "re-applied on every run. Every one also has a `repair` row in the Source "
                     "Ledger.")
        for a in rp_applied:
            pid = a.get("property_id")
            for f, ch in (a.get("changed") or {}).items():
                lines.append(f"- **id {pid} {f}**: `{ch.get('from')}` -> `{ch.get('to')}` "
                             f"({a.get('id', '?')}) - {a.get('why', '')}"
                             + (f" [verified by {a['verified_by']}]" if a.get("verified_by") else ""))
        lines.append("")
    _rp_rot = [(k, e) for k in ("stale", "ambiguous", "superseded", "invalid")
               for e in (rp_rep.get(k) or [])]
    if _rp_rot:
        # ONE HEADING, TWO OUTCOMES, AND THEY NEED OPPOSITE ACTIONS. This used to read
        # "matched NOTHING (stale - fix or delete)", which is the right instruction for an
        # entry that never found its target and the WRONG one for a CLEARING entry that
        # already landed: `repairs.py` reports an `unset`/`strike` whose field is now gone as
        # `stale` on every run AFTER the one that worked (deliberately - see the note above
        # `struck` there, and the already-absent branch that says "a correct entry, doing
        # nothing"), because a clear cannot be re-applied to a field that is no longer there.
        # Telling the reader to fix or delete that entry is telling them to undo a working
        # correction, so the heading no longer asserts staleness and the framing sends the two
        # cases in their two directions. The per-entry reason strings already distinguish
        # them; only this heading was mis-instructing.
        lines.append("## Manual corrections that applied NOTHING (property-level repairs)")
        lines.append("These `work/repairs.json` entries changed nothing on this run, and the "
                     "reason beside each one says which of two things that means. An entry that "
                     "matched NOTHING is stale and needs attention: the property still holds "
                     "whatever matching/merge produced, so correct the entry's `property` block "
                     "or delete it. An entry whose reason says the work ALREADY LANDED on an "
                     "earlier run - a clear whose field is now gone - is correct and is meant to "
                     "do nothing: it reports here on every later run precisely because it "
                     "worked, and it needs no action.")
        for k, e in _rp_rot:
            if isinstance(e, str):
                lines.append(f"- **{k}**: {e}")
                continue
            lines.append(f"- **{e.get('id', '?')}** ({k}): {e.get('reason', '')}")
        lines.append("")

    # KNOWN LIMITATIONS: advisory QA findings that were reviewed, judged non-blocking by the
    # reviewer, and NOT fixed within the bounded QA window (one review round + one improvement
    # round - see gate_runner qa-round). This section is what makes the bound honest: before it,
    # the ONLY way to make a finding disappear was to fix it, so a fresh memoryless reviewer with
    # one more debatable layout nit could reopen the gate forever. "Not fixed" now has a
    # delivered home instead of an infinite loop, which is the skill's own stated doctrine -
    # escalate to the Gaps Report rather than loosen a criterion.
    qa_carried: list = []
    if work_dir:
        try:
            import gate_runner as _GR
            qa_carried = _GR.qa_carried(Path(work_dir))
        except Exception:
            qa_carried = []
    if qa_carried:
        lines.append("## Known limitations (reviewed and accepted at QA)")
        for entry in qa_carried:
            lines.append(f"- {entry}")
        lines.append("")

    # photo matches to confirm (run.py writes <work>/photo_doubts.json) - an uncertain
    # brochure<->property pairing shows a placeholder and is surfaced as a yes/no the
    # broker can confirm to pull the photo in
    pd = (Path(work_dir) / "photo_doubts.json") if work_dir else None
    if pd and pd.exists():
        try:
            doubts = json.loads(pd.read_text(encoding="utf-8-sig"))
        except Exception:
            doubts = []
        if doubts:
            lines.append("## Photo matches to confirm")
            lines += [f"- **{d.get('park')}** -> Is this `{d.get('brochure')}`? "
                      f"If yes, confirm and the photo is pulled in immediately"
                      + (f" ({d.get('note')})" if d.get('note') else "") for d in doubts]
            lines.append("")

    # unreadable / skipped input files (run.py writes <work>/unreadable.json) - the
    lines += _email_attachments_skipped(work_dir)

    # honesty standard: a corrupt/encrypted/empty input is a named gap, never a silent drop
    ur = (Path(work_dir) / "unreadable.json") if work_dir else None
    if ur and ur.exists():
        try:
            items = json.loads(ur.read_text(encoding="utf-8-sig"))
        except Exception:
            items = []
        if items:
            lines.append("## Unreadable / skipped input files")
            # The per-file REASON already carries its own remedy when one exists, so the
            # generic tail is appended only when it does not. An unsupported TYPE cannot be
            # fixed by re-saving the file (the file is fine; there is no reader for it), and
            # its reason already says to paste the data into an email or a tracker instead -
            # so the old unconditional tail contradicted the reason on the same line, in the
            # CLIENT-FACING report. Keyed on the reason already naming a re-run rather than
            # on a type list, so a new reason that carries its own remedy is handled too.
            for it in items:
                _r = str(it.get("reason") or "")
                _tail = "" if "re-run" in _r.lower() else (
                    " (re-save or unlock it and re-run to include it)")
                lines.append(f"- **{it.get('file')}**: {_r}{_tail}")
            lines.append("")

    # extraction yield (run.py writes <work>/yield_report.md when a field-rich
    # spreadsheet yielded a thin parse - surfaced here so it cannot pass silently)
    yr = (Path(work_dir) / "yield_report.md") if work_dir else None
    if yr and yr.exists():
        lines.append("## Extraction yield (unmapped tracker columns)")
        body = [ln for ln in yr.read_text(encoding="utf-8-sig").splitlines()
                if ln.startswith("- ")]
        lines += body or ["- (see yield_report.md in the work folder)"]
        lines.append("")
    return "\n".join(lines)


# The flat Longlist export - one property per ROW, variables in COLUMNS. Field name
# -> friendly header, in a sensible reading order. The two "__" keys are DERIVED:
# the annual rent display string and the monthly equivalent (annual / 12, same
# currency + per-area convention - no FX, no area maths).
LONGLIST_COLUMNS = [
    ("id", "ID"), ("park", "Property / Park"), ("developer", "Developer"),
    ("landlord", "Landlord"),
    ("city", "City"), ("region", "Region"), ("country", "Country"),
    ("status", "Status"), ("permitting", "Permitting"), ("earlyAccess", "Early access"),
    ("warehouseArea", "Warehouse area"), ("areaUnit", "Area unit"),
    ("plotArea", "Plot area"), ("divisibleFrom", "Divisible from"),
    ("officeArea", "Office area"), ("clearHeight", "Clear height"),
    ("floorLoad", "Floor load"), ("sprinklers", "Sprinklers"),
    ("loadingDocks", "Loading docks"), ("overheadDoors", "Overhead doors"),
    ("electricity", "Electricity"), ("truckParking", "Truck parking"),
    ("carParking", "Car parking"),
    ("__rent_annual", "Warehouse rent (annual)"),
    ("__rent_monthly", "Warehouse rent (monthly)"),
    ("__total_annual", "Total annual rent"),
    ("__total_monthly", "Total monthly rent"),
    ("rentUnit", "Rent unit"), ("officeRent", "Office rent"),
    ("serviceCharge", "Service charge"), ("landPrice", "Land price"),
    ("leaseTerm", "Lease term"), ("rentFree", "Rent-free period"),
    # BREEAM and EPC are DIFFERENT certificates and each needs its own column. A single
    # "Certification" column fed only by `breeam` meant a property whose BREEAM is genuinely
    # unstated read "tbd" in the client Excel while its EPC rating - stated twice at source and
    # shipping in canonical.json and the dashboard - appeared nowhere in the workbook at all.
    ("incentives", "Incentives"), ("breeam", "BREEAM"), ("epc", "EPC"),
    ("motorway", "Motorway / corridor"), ("lat", "Latitude"), ("lng", "Longitude"),
    ("mapLink", "Map link"),
]
_WIDE = {"park", "__rent_annual", "__rent_monthly", "__total_annual", "__total_monthly",
         "incentives", "mapLink", "developer", "landlord"}


def _cell(v):
    """Keep numbers numeric (so the sheet sorts), pass strings through, and turn an
    empty/None into the explicit blank (the honesty standard - never a blank guess).

    v45: that blank is _common.BLANK (normalize.BLANK), the one token the dashboard prints
    too, so a cell in the client workbook and the row it came from on the page read alike."""
    if v is None:
        return C.BLANK
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, str) and v.strip() == "":
        return C.BLANK
    return v


def _rent_monthly(p: dict, default_ru: str | None = None) -> str:
    """Monthly headline rent = annual warehouseRentVal / 12, KEPT in its own currency
    and per-area convention. 'tbd' when there is no numeric annual rate to divide.

    D11: a figure whose source states NO rent unit is printed with "(unit not stated)", the
    same words `normalize.rent_display` puts in the annual column (B06), never in a default
    currency and basis. This function used to fall back to "€/sq m/yr" (or the dataset default
    passed in), so a unit-silent UK figure shipped "€ 0.71 / sq m / mo" in the workbook beside
    an annual column that honestly said "8.5 (unit not stated)". `default_ru` is kept in the
    signature for any caller that still passes it; it is no longer read."""
    v = p.get("warehouseRentVal")
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
        return C.BLANK
    if not p.get("rentUnit"):
        return f"{v / 12:.2f} / mo (unit not stated)"
    ru = str(p["rentUnit"]).split("/")
    cur = (ru[0].strip() if ru and ru[0].strip() else "€")
    per = (ru[1].strip() if len(ru) > 1 and ru[1].strip() else "sq m")
    return f"{cur} {v / 12:.2f} / {per} / mo"


def _total_rent(p: dict, monthly: bool = False) -> str:
    """Total rent = GLA x rate, mirroring the dashboard's totalAnnualRent: split into
    warehouse + office when a separate office rate exists, else the single warehouse
    rate over total GLA (warehouse + office area). 'tbd' when no positive warehouse
    rate/area. Same currency only (no FX); areas are already aligned by merge."""
    wr, wa = p.get("warehouseRentVal"), p.get("warehouseArea")
    if not isinstance(wr, (int, float)) or isinstance(wr, bool) or wr <= 0:
        return C.BLANK
    if not isinstance(wa, (int, float)) or isinstance(wa, bool) or wa <= 0:
        return C.BLANK
    oa = p.get("officeAreaVal")
    oa = oa if isinstance(oa, (int, float)) and not isinstance(oa, bool) and oa > 0 else 0
    orr = p.get("officeRentVal")
    orr = orr if isinstance(orr, (int, float)) and not isinstance(orr, bool) and orr > 0 else None
    annual = (wa * wr + oa * orr) if (orr is not None and oa > 0) else ((wa + oa) * wr)
    v = annual / 12 if monthly else annual
    # D11: the currency is the property's OWN stated one or it is not named at all. The old
    # `or "€/x/yr"` fallback printed a euro sign in front of a total computed from a rate whose
    # source named no currency - FX-grade invention in the artefact the broker forwards.
    cur = (str(p.get("rentUnit") or "").split("/")[0] or "").strip()
    if not cur:
        return f"{round(v):,} / {'mo' if monthly else 'yr'} (currency not stated)"
    return f"{cur} {round(v):,} / {'mo' if monthly else 'yr'}"


def longlist_xlsx(canonical: dict, out_path: Path) -> None:
    """Write the flat one-property-per-row workbook (CSV fallback if no openpyxl)."""
    props = canonical.get("properties", [])
    meta = canonical.get("meta", {}) or {}
    # D11: no dataset-level rent default is read here any more. Every rent cell prints its own
    # property's stated unit or says the unit is not stated (`_rent_monthly`, `_total_rent`);
    # the dataset basis is a LABEL convention for the dashboard, never a currency for a number.
    # OPEN COLUMNS (read everything; display selectively): any scalar field present
    # on at least one property that has no fixed column ships as an extra column at
    # the right-hand end, header prettified from its camelCase key. The card grid
    # stays curated; this flat workbook is the COMPLETE view - a field that reached
    # canonical.json must never be absent from the broker's own table.
    _fixed = {k for k, _ in LONGLIST_COLUMNS}
    _open_deny = {"photo", "gallery", "plan", "preBaked", "id",
                  "warehouseAreaSqm", "officeAreaVal", "warehouseRentVal",
                  "officeRentVal", "expansionParkVal", "rentUnitAssumed",
                  "regionCode", "coordsApprox",
                  # merge stamps this display string on every property; the fixed
                  # "Warehouse rent (annual)" column already shows it
                  "warehouseRent"}
    extras = sorted({k for p in props for k, v in p.items()
                     if k not in _fixed and k not in _open_deny
                     and not k.startswith("_")
                     and isinstance(v, (str, int, float, bool))})

    def _pretty(k: str) -> str:
        words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", k).replace("_", " ")
        return (words[:1].upper() + words[1:].lower()) if words else k

    headers = [h for _, h in LONGLIST_COLUMNS] + [_pretty(k) for k in extras]
    # ASSUMED UNITS ARE DISCLOSED IN THE WORKBOOK, not only in the Gaps Report. (B38)
    #
    # This is the artefact the broker actually forwards, and an "Area unit" of a bare "sq ft"
    # reads as sourced when the source stated nothing - a 10.76x risk presented as fact. The
    # dashboard CARD cannot be fixed from here: its unit is DATASET-wide
    # (`PROPS.find(p => p.areaUnit)`), so no per-property data change touches it; that half is
    # a template item. But this column is already a free string, so the honest label costs no
    # schema change, no record mutation and no chrome edit.
    # Joined by ID, never by park name - two phases of one scheme share a name.
    _assumed_ids = {a.get("id") for a in (meta.get("unitAssumptions") or [])
                    if isinstance(a, dict) and a.get("id") is not None}

    def value_for(p, key):
        if key == "__rent_annual":
            return _cell(p.get("warehouseRent"))
        if key == "__rent_monthly":
            return _rent_monthly(p)
        if key == "__total_annual":
            return _total_rent(p, False)
        if key == "__total_monthly":
            return _total_rent(p, True)
        if key == "areaUnit" and p.get("id") in _assumed_ids and p.get("areaUnit"):
            return f"{p['areaUnit']} (assumed - source stated none)"
        return _cell(p.get(key))

    rows = [[value_for(p, key) for key, _ in LONGLIST_COLUMNS]
            + [_cell(p.get(k)) for k in extras] for p in props]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        wb = Workbook()
        ws = wb.active
        ws.title = "Longlist"
        ws.append(headers)
        hdr_fill = PatternFill("solid", fgColor="003F2D")
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = hdr_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "B2"  # freeze the header row + the ID column
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
        for i, key in enumerate([k for k, _ in LONGLIST_COLUMNS] + extras, start=1):
            ws.column_dimensions[get_column_letter(i)].width = (
                30 if key in _WIDE else 8 if key == "id" else 16)
        tmp = out.with_suffix(out.suffix + ".tmp")
        wb.save(tmp)
        os.replace(tmp, out)
        print(f"OK Longlist -> {out} ({len(rows)} properties x {len(headers)} fields)")
    except Exception as e:
        import csv as _csv
        fallback = out.with_suffix(".csv")
        tmp = fallback.with_suffix(fallback.suffix + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(headers)
            w.writerows(rows)
        os.replace(tmp, fallback)
        print(f"NOTE openpyxl unavailable ({e}); wrote CSV fallback -> {fallback}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", required=True)
    ap.add_argument("--html", required=True)
    ap.add_argument("--ledger")
    ap.add_argument("--out-dir", required=True,
                    help="where the four client-facing deliverables go ('3. Output' in the "
                         "three-folder project layout)")
    ap.add_argument("--marker-dir", dest="marker_dir", default="",
                    help="where the technical completion marker (.delivery_complete.json) is "
                         "written. Defaults to --out-dir; the spine points it at the WORK dir so "
                         "the broker's output folder holds only the four deliverables.")
    ap.add_argument("--slug", default="Longlist")
    ap.add_argument("--filename")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mark_dir = Path(args.marker_dir) if args.marker_dir else out
    try:
        mark_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        mark_dir = out
    canonical = json.loads(Path(args.canonical).read_text(encoding="utf-8-sig"))

    # F14: `slug` names FILES, `args.slug` is what the broker typed. An explicit --filename is
    # honoured byte-for-byte because the spine resolves it before calling here and later looks
    # the dashboard up under exactly that name (run.py composes it; sanitising it HERE would
    # break that lookup, so the spine applies safe_slug() itself at the point it composes).
    slug = safe_slug(args.slug)

    # 1. html
    fname = args.filename or f"CBRE_Property_Dashboard_{slug}.html"
    dst = out / fname
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copyfile(args.html, tmp)
    os.replace(tmp, dst)
    print(f"OK dashboard -> {dst}")

    # 2. ledger - exported IN-PROCESS (same interpreter, no subprocess) so it cannot
    # silently fail on a sandbox where sys.executable can't be re-invoked; the spine
    # captures this stdout in quiet mode. cmd_export already degrades to a .csv copy
    # if openpyxl is missing, so the deliverable is always written.
    if args.ledger and Path(args.ledger).exists():
        import ledger
        try:
            ledger.cmd_export(argparse.Namespace(
                ledger=args.ledger, out=str(out / f"{slug}_Source_Ledger.xlsx")))
        except Exception as e:
            print(f"WARNING: Source Ledger export failed: {e}", file=sys.stderr)

    # 3. gaps report (the work dir = the canonical's folder; yield_report.md lives there)
    gaps = out / f"{slug}_Gaps_Report.md"
    C.atomic_write_text(gaps, gaps_report(canonical, args.slug,      # the TITLE keeps the raw name
                                          work_dir=Path(args.canonical).resolve().parent))
    print(f"OK gaps report -> {gaps}")

    # 4. flat longlist workbook (one property per row, variables in columns) - a
    # broker-facing data view alongside the field-level Source Ledger. Guarded so a
    # workbook hiccup can never block the dashboard hand-off.
    try:
        longlist_xlsx(canonical, out / f"{slug}_Longlist.xlsx")
    except Exception as e:
        print(f"WARNING: Longlist export failed: {e}", file=sys.stderr)

    # 5. THE COMPLETION MARKER - written LAST, and the only thing that means "delivered".
    #
    # The four artefacts above are each atomic; the SET was not. Stage 7's resume guard used
    # to key on the DASHBOARD, which lands FIRST, so a kill in steps 2-4 left the guard
    # satisfied by an incomplete delivery: either three artefacts never appeared and every
    # later run resume-skipped past them (final_gate then failing with no remediation, and
    # Stage 7 exits 0 so nothing bounded the loop), or - worse, because it ships - a v2
    # dashboard sat beside a v1 Gaps Report and Longlist and every presence check passed.
    #
    # The marker names what it vouches for, so a later deletion is detectable. It does NOT
    # require the Longlist to exist: that export is deliberately allowed to fail (above), and
    # a predicate that demanded it would be unsatisfiable on a box where openpyxl is broken -
    # deliver would then re-run on every single pass forever while final_gate still blocked.
    # That would trade one unbounded loop for another. (B01)
    _vouched = [fname, f"{slug}_Gaps_Report.md"]
    if args.ledger and Path(args.ledger).exists():
        _led = out / f"{slug}_Source_Ledger.xlsx"
        _vouched.append(_led.name if _led.exists() else f"{slug}_Source_Ledger.csv")
    # `slug` is the filename component the artefacts were built from; `client` is the broker's
    # exact text (F14). Nothing reads either key today; they are here so a human can see both.
    C.atomic_write_text(mark_dir / MARKER_NAME, json.dumps(
        {"schema_version": 1, "slug": slug, "client": args.slug, "artefacts": _vouched,
         "out_dir": str(out)},
        ensure_ascii=False, indent=2))
    # A marker left in the OUT dir by a pre-split run would keep asserting an older
    # delivery beside the new one; the artefact list is now vouched for from mark_dir.
    if mark_dir.resolve() != out.resolve():
        try:
            (out / MARKER_NAME).unlink()
        except OSError:
            pass
    print(f"OK delivery complete -> {mark_dir / MARKER_NAME}")


if __name__ == "__main__":
    C.force_utf8_stdout()   # D16: a non-ASCII value in printed output must not
    #                        crash the print on a cp1252 Windows console
    main()
