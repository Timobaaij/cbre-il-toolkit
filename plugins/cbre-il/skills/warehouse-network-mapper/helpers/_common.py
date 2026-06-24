"""Shared utilities for the warehouse-network-mapper helpers.

Pure standard library so the skill runs anywhere a Python 3.9+ interpreter is
present, with no pip install step. Holds the three things geocode.py and
dedup.py both need: JSON IO, haversine distance, and address normalisation.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

# The literal we use everywhere a value is genuinely unknown. Never a guess.
TBD = "tbd"


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON array of facility records (the pipeline lingua franca)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "records" in data:
        data = data["records"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of records")
    return data


def save_records(path: str | Path, records: list[dict[str, Any]]) -> None:
    Path(path).write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_number(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            return False
    return False


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


# Tokens that carry no disambiguating signal in an address string.
_NOISE = {
    "unit",
    "units",
    "building",
    "bldg",
    "warehouse",
    "dc",
    "block",
    "plot",
    "the",
    "no",
    "nr",
    "number",
    "ste",
    "suite",
    "floor",
    "fl",
}

# Light street-type canonicalisation so "Street"/"Str"/"Strasse" collapse.
_STREET_SYNONYMS = {
    "str": "street",
    "st": "street",
    "strasse": "strasse",
    "rd": "road",
    "ave": "avenue",
    "av": "avenue",
    "ln": "lane",
    "blvd": "boulevard",
}

# Postcode patterns by country (rough, enough to key a dedup, not validate post).
_POSTCODE_RE = {
    "united kingdom": re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I),
    "uk": re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I),
    "netherlands": re.compile(r"\b(\d{4}\s*[A-Z]{2})\b", re.I),
    "germany": re.compile(r"\b(\d{5})\b"),
    "france": re.compile(r"\b(\d{5})\b"),
    "spain": re.compile(r"\b(\d{5})\b"),
    "italy": re.compile(r"\b(\d{5})\b"),
    "poland": re.compile(r"\b(\d{2}-\d{3})\b"),
    "belgium": re.compile(r"\b(\d{4})\b"),
}
_GENERIC_POSTCODE_RE = re.compile(r"\b(\d{4,5}(?:-\d{3})?)\b")


def extract_postcode(address: str, country: str = "") -> str:
    if not address:
        return ""
    rgx = _POSTCODE_RE.get((country or "").strip().lower(), _GENERIC_POSTCODE_RE)
    m = rgx.search(address)
    return re.sub(r"\s+", "", m.group(1)).upper() if m else ""


def normalize_address(address: str) -> str:
    """Collapse an address to a comparable key.

    Lowercases, strips accents and punctuation, drops noise tokens
    ("Unit", "Building", "Warehouse" ...) and canonicalises street types, so
    that "Unit 4, Magna Park" and "Magna Park (Warehouse 4)" collapse to the
    same key without claiming they are identical on the string alone.
    """
    if not address or str(address).strip().lower() == TBD:
        return ""
    text = strip_accents(str(address)).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = []
    for tok in text.split():
        tok = _STREET_SYNONYMS.get(tok, tok)
        if tok in _NOISE:
            continue
        tokens.append(tok)
    return " ".join(sorted(set(tokens)))
