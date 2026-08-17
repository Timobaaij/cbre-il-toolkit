"""Build the brochure downloader tool from a property longlist.

    python helpers/build.py --xlsx "<longlist.xlsx>" --out "<dir>" [--client NAME] [--sheet NAME]

Writes brochure-downloader.html plus gaps.md, and prints a summary so the orchestrator can
report what happened without opening the spreadsheet itself.

Runs with no network access and no third-party packages, which is what the Cowork sandbox
provides.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):        # allow `python helpers/build.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from helpers import longlist as L
    from helpers import render as R
    from helpers import xlsx_links as X
else:
    from . import longlist as L
    from . import render as R
    from . import xlsx_links as X


def infer_client(path: Path) -> str:
    """Guess a client name from the filename, e.g. "Warehouse Availability - Temu UK (6)".

    Takes the segment after a dash and drops a trailing copy counter.
    """
    stem = path.stem
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    if " - " in stem:
        stem = stem.split(" - ", 1)[1]
    return stem.strip() or path.stem


def gaps_markdown(result: L.Longlist, client: str, source: str) -> str:
    lines = [
        f"# Gaps — {client} brochure extraction",
        "",
        f"Source: `{source}` (sheet `{result.sheet_name}`)",
        "",
        f"- Properties in longlist: **{len(result.properties)}**",
        f"- Distinct brochure files: **{len(result.downloads)}**",
        f"- Downloadable automatically: **{len(result.automatable)}**",
        f"- Need attention: **{len(result.flagged)}**",
        f"- Rows with no link: **{sum(1 for p in result.properties if not p.url)}**",
        "",
        "Detected columns: "
        + ", ".join(f"{k}={v}" for k, v in result.columns.items() if k != "brochure_found_by")
        + f" (brochure column found by {result.columns.get('brochure_found_by', 'unknown')})",
        "",
    ]
    if result.flagged:
        lines += ["## Not a direct PDF link", ""]
        for d in result.flagged:
            lines.append(f"- **No. {'+'.join(d.numbers)}** {d.label} — {d.url}")
        lines.append("")
    no_link = [p for p in result.properties if not p.url]
    if no_link:
        lines += ["## No brochure link in the spreadsheet", ""]
        for p in no_link:
            lines.append(f"- **No. {p.number}** {p.label}")
        lines.append("")
    if result.warnings:
        lines += ["## All warnings", ""]
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")
    lines += [
        "This file records what the spreadsheet could not supply. The tool writes its own",
        "`_gaps.md` into the zip covering what actually downloaded.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the brochure downloader HTML tool.")
    ap.add_argument("--xlsx", required=True, help="path to the longlist spreadsheet")
    ap.add_argument("--out", default=".", help="output directory (default: current)")
    ap.add_argument("--client", default=None, help="client name for titles and the zip filename")
    ap.add_argument("--sheet", default=None, help="worksheet name (default: first, or 'Longlist')")
    ap.add_argument("--name", default="brochure-downloader.html", help="output HTML filename")
    args = ap.parse_args(argv)

    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        print(f"error: no such file: {xlsx}", file=sys.stderr)
        return 2

    sheet_name = args.sheet
    if sheet_name is None:
        try:
            names = X.sheet_names(str(xlsx))
        except X.XlsxError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        # Prefer a sheet actually called Longlist when the workbook has several.
        preferred = [n for n in names if n.strip().lower() in ("longlist", "long list")]
        sheet_name = preferred[0] if preferred else (names[0] if names else None)

    try:
        sheet = X.read_sheet(str(xlsx), sheet=sheet_name)
    except X.XlsxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        result = L.extract(sheet)
    except L.LonglistError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    client = args.client or infer_client(xlsx)
    data = L.payload(result, client=client, source=xlsx.name)

    out_dir = Path(args.out)
    html_path = R.render(data, client=client, out_path=out_dir / args.name)
    gaps_path = out_dir / "gaps.md"
    gaps_path.write_text(gaps_markdown(result, client, xlsx.name), encoding="utf-8")

    print(f"client:      {client}")
    print(f"sheet:       {result.sheet_name} (header row {result.header_row + 1})")
    print(f"columns:     {result.columns}")
    print(f"properties:  {len(result.properties)}")
    print(f"downloads:   {len(result.downloads)} distinct files")
    print(f"automatable: {len(result.automatable)}")
    print(f"flagged:     {len(result.flagged)}")
    print(f"no link:     {sum(1 for p in result.properties if not p.url)}")
    print(f"html:        {html_path}")
    print(f"gaps:        {gaps_path}")
    if result.warnings:
        print("warnings:")
        for w in result.warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
