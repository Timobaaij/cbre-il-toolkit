#!/usr/bin/env python3
"""Size-unit normalisation, to the unit the user chose at intake.

Public sources state warehouse size in whatever unit is local: sq ft (UK/IE),
m2 (most of the Continent and ICPE filings), hectares of site area, acres, or
only "N pallet positions". Left alone, the Size column silently mixes units.

At Stage 0 the user picks metric (sqm) or imperial (sq ft). This helper reads
each record's raw "size_as_stated", converts it to a canonical sqm internally
(so dedup and comparisons stay consistent), then writes the display value in
the chosen unit. It never invents a sqm for pallet-position-only figures, and
it flags a bare number that has no unit rather than asserting one.

  python units.py --in records.json --out records.json --units metric
  python units.py --in records.json --out records.json --units imperial

Writes per record: size_sqm (canonical), size_out (value in chosen unit),
size_unit ("sqm" | "sq ft"), and appends a basis note to comments.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import TBD, is_number, load_records, save_records  # noqa: E402

SQFT_PER_SQM = 10.7639104
SQM_PER_SQFT = 0.09290304

# unit token -> multiplier to sqm. Order matters: match "sq ft" before "ft".
_UNIT_PATTERNS: list[tuple[re.Pattern[str], float, str]] = [
    (re.compile(r"\b(sq\.?\s*ft|sqft|square\s+feet|square\s+foot|ft2|ft\^?2|ft²)\b"),
     SQM_PER_SQFT, "sq ft"),
    (re.compile(r"\b(hectares?|ha)\b"), 10000.0, "ha"),
    (re.compile(r"\b(acres?)\b"), 4046.8564224, "acres"),
    (re.compile(r"(m²|m2|m\^?2|sq\.?\s*m|sqm|square\s+met(?:re|er)s?|"
                r"quadratmeter|metri\s+quadri|metros?\s+cuadrados?|"
                r"m(?:è|e)tres?\s+carr(?:é|e)s?)"), 1.0, "sqm"),
]

_PALLET_RE = re.compile(r"\bpallet", re.I)
_NUMBER_RE = re.compile(r"(\d[\d.,\s]*\d|\d)")


def _to_float(num_str: str) -> float | None:
    s = num_str.replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):       # 42.000,5 -> 42000.5
            s = s.replace(".", "").replace(",", ".")
        else:                                  # 42,000.5 -> 42000.5
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.search(r",\d{3}\b", s) else s.replace(",", ".")
    elif "." in s:
        if re.search(r"\.\d{3}\b", s) and not re.search(r"\.\d{1,2}\b", s):
            s = s.replace(".", "")             # 42.000 -> 42000
    try:
        return float(s)
    except ValueError:
        return None


def parse_size(stated: str, assume_unit: str = "sqm") -> dict[str, Any]:
    """Return {sqm, label, note}; sqm='tbd' when not convertible.

    assume_unit ('sqm' or 'sqft') is used only for a bare number with no unit.
    """
    if not stated or str(stated).strip().lower() == TBD:
        return {"sqm": TBD, "label": "", "note": ""}
    text = str(stated).lower()

    if _PALLET_RE.search(text):
        return {"sqm": TBD, "label": "pallet positions",
                "note": "pallet-position capacity, not a floor area; sqm tbd"}

    for rgx, mult, label in _UNIT_PATTERNS:
        m = rgx.search(text)
        if not m:
            continue
        head = text[: m.start()]
        nums = _NUMBER_RE.findall(head) or _NUMBER_RE.findall(text)
        if not nums:
            continue
        val = _to_float(nums[-1])
        if val is None:
            continue
        note = f"converted from {val:g} {label}" if label != "sqm" else "stated in sqm"
        return {"sqm": round(val * mult), "label": label, "note": note}

    nums = _NUMBER_RE.findall(text)
    if nums:
        val = _to_float(nums[-1])
        if val is not None and val >= 1000:
            mult = SQM_PER_SQFT if assume_unit == "sqft" else 1.0
            unit_word = "sq ft" if assume_unit == "sqft" else "sqm"
            return {"sqm": round(val * mult), "label": f"{unit_word}?",
                    "note": f"no unit stated; assumed {unit_word}, verify"}
    return {"sqm": TBD, "label": "", "note": "no parseable size"}


def run(args: argparse.Namespace) -> int:
    records = load_records(args.infile)
    imperial = args.units == "imperial"
    out_unit = "sq ft" if imperial else "sqm"
    assume = "sqft" if imperial else "sqm"
    filled = 0

    for rec in records:
        # Establish the canonical sqm value.
        if is_number(rec.get("size_sqm")):
            sqm: Any = float(rec["size_sqm"])
        else:
            stated = rec.get("size_as_stated") or rec.get("size_sqm") or ""
            parsed = parse_size(str(stated), assume_unit=assume)
            sqm = parsed["sqm"]
            if parsed["note"]:
                existing = str(rec.get("comments") or "").strip()
                rec["comments"] = (f"{existing} Size: {parsed['note']}.".strip()
                                   if existing else f"Size: {parsed['note']}.")
                if sqm != TBD and rec.get("size_basis") in (None, "", TBD):
                    rec["size_basis"] = "stated"
                filled += 1
            rec["size_sqm"] = round(sqm) if sqm != TBD else TBD

        # Display value in the chosen unit.
        if is_number(rec.get("size_sqm")):
            val = float(rec["size_sqm"])
            rec["size_out"] = round(val * SQFT_PER_SQM) if imperial else round(val)
        else:
            rec["size_out"] = TBD
        rec["size_unit"] = out_unit

    save_records(args.out, records)
    print(f"Units: output in {out_unit}; normalised {filled} raw size field(s) "
          f"-> {args.out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Normalise sizes to metric or imperial.")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--units", choices=["metric", "imperial"], default="metric",
                   help="metric -> sqm column; imperial -> sq ft column")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
