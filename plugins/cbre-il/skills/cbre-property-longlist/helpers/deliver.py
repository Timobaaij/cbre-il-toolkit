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
import shutil
import sys

import _common as C
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def _is_tbd(v):
    return v is None or str(v).strip().lower() in {"tbd", "tbc", "—", "", "none"}


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

    # enrichment gaps
    eg = meta.get("enrichmentGaps", [])
    lines.append("## Enrichment gaps")
    lines += ([f"- {g}" for g in eg] if eg else ["- None."])
    lines.append("")

    # unmatched assets
    ua = meta.get("unmatchedAssets", [])
    lines.append("## Unmatched assets")
    lines += ([f"- {a}" for a in ua] if ua else ["- None - every image bound to a property."])
    lines.append("")

    # conflicts
    cf = meta.get("conflicts", [])
    lines.append("## Source conflicts")
    lines += ([f"- {c}" for c in cf] if cf else ["- None recorded."])
    lines.append("")

    # photo matches to confirm (run.py writes <work>/photo_doubts.json) - an uncertain
    # brochure<->property pairing shows a placeholder and is surfaced as a yes/no the
    # broker can confirm to pull the photo in
    pd = (Path(work_dir) / "photo_doubts.json") if work_dir else None
    if pd and pd.exists():
        try:
            doubts = json.loads(pd.read_text(encoding="utf-8"))
        except Exception:
            doubts = []
        if doubts:
            lines.append("## Photo matches to confirm")
            lines += [f"- **{d.get('park')}** -> Is this `{d.get('brochure')}`? "
                      f"If yes, confirm and the photo is pulled in immediately"
                      + (f" ({d.get('note')})" if d.get('note') else "") for d in doubts]
            lines.append("")

    # unreadable / skipped input files (run.py writes <work>/unreadable.json) - the
    # honesty standard: a corrupt/encrypted/empty input is a named gap, never a silent drop
    ur = (Path(work_dir) / "unreadable.json") if work_dir else None
    if ur and ur.exists():
        try:
            items = json.loads(ur.read_text(encoding="utf-8"))
        except Exception:
            items = []
        if items:
            lines.append("## Unreadable / skipped input files")
            lines += [f"- **{it.get('file')}**: {it.get('reason')} "
                      f"(re-save or unlock it and re-run to include it)" for it in items]
            lines.append("")

    # extraction yield (run.py writes <work>/yield_report.md when a field-rich
    # spreadsheet yielded a thin parse - surfaced here so it cannot pass silently)
    yr = (Path(work_dir) / "yield_report.md") if work_dir else None
    if yr and yr.exists():
        lines.append("## Extraction yield (unmapped tracker columns)")
        body = [ln for ln in yr.read_text(encoding="utf-8").splitlines()
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
    ("incentives", "Incentives"), ("breeam", "Certification"),
    ("motorway", "Motorway / corridor"), ("lat", "Latitude"), ("lng", "Longitude"),
    ("mapLink", "Map link"),
]
_WIDE = {"park", "__rent_annual", "__rent_monthly", "__total_annual", "__total_monthly",
         "incentives", "mapLink", "developer", "landlord"}


def _cell(v):
    """Keep numbers numeric (so the sheet sorts), pass strings through, and turn an
    empty/None into an explicit 'tbd' (the honesty standard - never a blank guess)."""
    if v is None:
        return "tbd"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, str) and v.strip() == "":
        return "tbd"
    return v


def _rent_monthly(p: dict, default_ru: str = "€/sq m/yr") -> str:
    """Monthly headline rent = annual warehouseRentVal / 12, KEPT in its own currency
    and per-area convention. 'tbd' when there is no numeric annual rate to divide."""
    v = p.get("warehouseRentVal")
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
        return "tbd"
    ru = (p.get("rentUnit") or default_ru).split("/")
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
        return "tbd"
    if not isinstance(wa, (int, float)) or isinstance(wa, bool) or wa <= 0:
        return "tbd"
    oa = p.get("officeAreaVal")
    oa = oa if isinstance(oa, (int, float)) and not isinstance(oa, bool) and oa > 0 else 0
    orr = p.get("officeRentVal")
    orr = orr if isinstance(orr, (int, float)) and not isinstance(orr, bool) and orr > 0 else None
    annual = (wa * wr + oa * orr) if (orr is not None and oa > 0) else ((wa + oa) * wr)
    v = annual / 12 if monthly else annual
    cur = ((p.get("rentUnit") or "€/x/yr").split("/")[0] or "€").strip()
    return f"{cur} {round(v):,} / {'mo' if monthly else 'yr'}"


def longlist_xlsx(canonical: dict, out_path: Path) -> None:
    """Write the flat one-property-per-row workbook (CSV fallback if no openpyxl)."""
    props = canonical.get("properties", [])
    units = (canonical.get("meta", {}) or {}).get("units", {}) or {}
    default_ru = units.get("rent") or "€/sq m/yr"
    headers = [h for _, h in LONGLIST_COLUMNS]

    def value_for(p, key):
        if key == "__rent_annual":
            return _cell(p.get("warehouseRent"))
        if key == "__rent_monthly":
            return _rent_monthly(p, default_ru)
        if key == "__total_annual":
            return _total_rent(p, False)
        if key == "__total_monthly":
            return _total_rent(p, True)
        return _cell(p.get(key))

    rows = [[value_for(p, key) for key, _ in LONGLIST_COLUMNS] for p in props]
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
        for i, (key, _h) in enumerate(LONGLIST_COLUMNS, start=1):
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
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--slug", default="Longlist")
    ap.add_argument("--filename")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    canonical = json.loads(Path(args.canonical).read_text(encoding="utf-8"))

    # 1. html
    fname = args.filename or f"CBRE_Property_Dashboard_{args.slug}.html"
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
                ledger=args.ledger, out=str(out / f"{args.slug}_Source_Ledger.xlsx")))
        except Exception as e:
            print(f"WARNING: Source Ledger export failed: {e}", file=sys.stderr)

    # 3. gaps report (the work dir = the canonical's folder; yield_report.md lives there)
    gaps = out / f"{args.slug}_Gaps_Report.md"
    C.atomic_write_text(gaps, gaps_report(canonical, args.slug,
                                          work_dir=Path(args.canonical).resolve().parent))
    print(f"OK gaps report -> {gaps}")

    # 4. flat longlist workbook (one property per row, variables in columns) - a
    # broker-facing data view alongside the field-level Source Ledger. Guarded so a
    # workbook hiccup can never block the dashboard hand-off.
    try:
        longlist_xlsx(canonical, out / f"{args.slug}_Longlist.xlsx")
    except Exception as e:
        print(f"WARNING: Longlist export failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
