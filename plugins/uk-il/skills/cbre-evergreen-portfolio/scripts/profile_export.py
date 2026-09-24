# -*- coding: utf-8 -*-
"""Profile an EverGreen Excel export before anyone interprets it.

    python profile_export.py <export.xlsx|.csv> [work_dir]

Writes into work_dir (default ./work):
  raw.json      every row as {header: value}, dates as ISO strings
  profile.json  machine-readable column profile
  profile.md    the same, for a human or an agent to read first

It describes; it never cleans. The traps it flags are the ones that have
produced wrong numbers before: literal 0 meaning "unknown", 1950 / 1905
placeholder dates, empty and single-valued columns, duplicate addresses,
and columns this skill has never seen.
"""
import csv, datetime, json, os, re, sys
from collections import Counter

KNOWN = [
    "Building ID", "Marketing Name", "Confidential", "Address", "Town", "Region", "M25 segment",
    "Road corridor", "Postcode", "Logistics park", "Latitude, Longitude", "Construction status",
    "PC of construction", "Speculative, BTS or Second hand", "EPC rating", "BREEAM rating",
    "Landlord", "Landlord Verified", "Developer", "Asset manager", "Tenant/Occupier",
    "Tenant Verified", "Sector", "Status", "Deal date", "Deal quarter",
    "Historical quoting rent (£ per sq ft)", "Current quoting rent (£ per sq ft)",
    "Achieved rent (£ per sq ft)", "Rent per annum (£)", "Lease start date", "Lease terms (yrs)",
    "Lease expiry date", "Break date", "Is lease outside the L&T act?", "Type of rent review",
    "Incentive (months)", "Next rent review", "Size (sq ft)", "Size Unit", "Site area (acres)",
    "Eaves (m)", "Eaves 10m or above?", "Yard depth (m)", "Office content (sq ft)",
    "Floor loading (kN/sq m)", "No. of dock level doors", "No. of level access doors",
    "No. of euro dock doors", "Total doors", "Quality of unit", "Power (KVA)", "Site ratio",
    "Office ratio", "Door ratio", "No. of trailer spaces", "No. of car parking spaces",
    "EV charge", "No. of electric car charging spaces", "Solus unit/park", "Cross docked",
    "360 HGV circulation", "Cold storage", "Shared HGV/Car access", "VMU", "Gatehouse",
    "Solar panels", "Truckwash", "HGV refuelling facilities", "Rail connected",
    "Disposal agent 1", "Disposal agent 2", "Disposal agent 3", "Acquisition agent 1",
    "Acquisition agent 2", "Building last updated", "Building last updated date",
    "Building created", "Building created date",
]
ANCHORS = ("building id", "size (sq ft)", "tenant/occupier", "address")


def norm(h):
    return re.sub(r"[^a-z0-9]+", " ", str(h or "").lower()).strip()


def jsonable(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()[:10] if isinstance(v, datetime.datetime) and v.time() == datetime.time() \
            else v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def read_rows(path):
    """Return (sheet_name, header, rows) from the sheet that looks most like the export."""
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            grid = [r for r in csv.reader(f)]
        return "csv", grid
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    except ImportError:
        import pandas as pd
        book = pd.read_excel(path, sheet_name=None, header=None)
        sheets = [(n, df.where(df.notna(), None).values.tolist()) for n, df in book.items()]
    # the export is the sheet with the most filled rows
    return max(sheets, key=lambda s: sum(1 for r in s[1] if any(c not in (None, "") for c in r)))


def find_header(grid):
    for i, r in enumerate(grid[:15]):
        cells = [norm(c) for c in r if c not in (None, "")]
        if any(a in cells for a in ANCHORS) or (len(cells) >= 5 and all(not re.fullmatch(r"[\d .]+", c) for c in cells)):
            return i
    return 0


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.getcwd(), "work")
    os.makedirs(work, exist_ok=True)

    sheet, grid = read_rows(src)
    hi = find_header(grid)
    header = [str(h).strip() if h not in (None, "") else f"(blank col {j + 1})" for j, h in enumerate(grid[hi])]
    rows = []
    for r in grid[hi + 1:]:
        if not any(c not in (None, "") for c in r):
            continue
        rows.append({header[j]: jsonable(r[j]) if j < len(r) else None for j in range(len(header))})

    with open(os.path.join(work, "raw.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0, default=str)

    known_n = {norm(k) for k in KNOWN}
    cols = []
    for h in header:
        vals = [r.get(h) for r in rows]
        filled = [v for v in vals if v not in (None, "") and str(v).strip().lower() not in ("none", "nan")]
        s = [str(v).strip() for v in filled]
        zeros = sum(1 for v in s if re.fullmatch(r"0+(\.0+)?", v))
        placeholder = sum(1 for v in s if re.match(r"^(19[0-4]\d|1950)-\d\d-\d\d", v))
        numeric = sum(1 for v in s if re.fullmatch(r"-?\d+(\.\d+)?", v))
        dates = sum(1 for v in s if re.match(r"^\d{4}-\d\d-\d\d", v))
        top = Counter(s).most_common(6)
        flags = []
        if not s:
            flags.append("EMPTY")
        elif len(set(s)) == 1:
            flags.append("SINGLE-VALUED")
        if zeros and numeric >= len(s) * .8:
            flags.append(f"ZERO={zeros} (0 means unknown in EverGreen -> null)")
        if placeholder:
            flags.append(f"PLACEHOLDER-DATES={placeholder} (year <= 1950 -> null)")
        if norm(h) not in known_n:
            flags.append("UNKNOWN-COLUMN (new to this skill: inspect before use)")
        cols.append({
            "column": h, "filled": len(s), "zeros": zeros, "known": len(s) - zeros - placeholder,
            "distinct": len(set(s)), "type": "date" if dates >= len(s) * .8 and s else
            "number" if numeric >= len(s) * .8 and s else "text",
            "top": top, "flags": flags,
        })

    missing = [k for k in KNOWN if norm(k) not in {norm(h) for h in header}]
    by_addr = Counter((str(r.get("Address") or r.get("Marketing Name") or "")).strip().lower() for r in rows)
    dups = [a for a, n in by_addr.items() if a and n > 1]
    ll_col = next((h for h in header if norm(h) == "latitude longitude"), None)
    geo = sum(1 for r in rows if ll_col and r.get(ll_col) and "," in str(r.get(ll_col)))

    prof = {"source": os.path.basename(src), "sheet": sheet, "header_row": hi + 1,
            "rows": len(rows), "columns": cols, "missing_known_columns": missing,
            "duplicate_addresses": dups, "geocoded_rows": geo,
            "profiled": datetime.date.today().isoformat()}
    with open(os.path.join(work, "profile.json"), "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=1)

    L = [f"# Export profile: {prof['source']}",
         f"Sheet `{sheet}`, header on row {hi + 1}, **{len(rows)} records**, {len(header)} columns. "
         f"Geocoded: {geo}/{len(rows)}.", ""]
    if dups:
        L += [f"**Duplicate addresses ({len(dups)})** - decide: two demises, or one record twice?",
              *[f"- {a}" for a in dups], ""]
    if missing:
        L += [f"**Known EverGreen columns absent ({len(missing)}):** " + ", ".join(missing), ""]
    L += ["| Column | Known | Zeros | Distinct | Type | Top values | Flags |", "|---|---|---|---|---|---|---|"]
    for c in cols:
        tops = "; ".join(f"{v[:28]} x{n}" for v, n in c["top"][:4]).replace("|", "/")
        L.append(f"| {c['column']} | {c['known']}/{len(rows)} | {c['zeros']} | {c['distinct']} | {c['type']} "
                 f"| {tops} | {'; '.join(c['flags'])} |")
    with open(os.path.join(work, "profile.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"{len(rows)} records, {len(header)} columns from sheet '{sheet}' (header row {hi + 1})")
    print(f"geocoded {geo}/{len(rows)}; duplicate addresses {len(dups)}; unknown columns "
          f"{sum(1 for c in cols if any('UNKNOWN' in f for f in c['flags']))}; missing known {len(missing)}")
    print("wrote", os.path.join(work, "raw.json"), "+ profile.json + profile.md")


if __name__ == "__main__":
    main()
