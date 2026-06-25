#!/usr/bin/env python3
"""Extra-deep mode, consolidation wave: bucket recon leads by the country they
are ABOUT, in code.

In extra-deep mode a first wave of cheap recon agents sweeps every country for
the mere presence and rough count of warehouses. The catch is cross-border
leakage: a Swedish trade-press article names a Spanish DC, a German release
mentions a Polish hub. If each country's deep agent only sees its own recon
output, those leads are lost.

Rather than pour every recon agent's prose into one overloaded "collection
agent" (a context bottleneck at Lidl scale), the recon agents emit structured
leads and this helper does the join deterministically: it routes each lead to
the country it concerns, dedups, and aggregates the per-country expected count
into one brief per country that seeds that country's deep search.

Input: a JSON array of recon outputs, each:
  {"searched_country": "Sweden",
   "leads": [{"country": "Spain", "city": "Illescas",
              "site_hint": "Zalando reverse-logistics centre",
              "confidence": "M", "sources": [{"url": "...", "tier": "trade-press"}]}],
   "self_count_hint": {"country": "Sweden", "expected": 2, "basis": "..."}}

Output: {country: {"expected_count_hint", "expected_basis", "lead_count",
                   "mentioned_by": [...], "leads": [...deduped...]}}

  python merge_leads.py --in recon_leads.json --out per_country_leads.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_records, save_records, strip_accents  # noqa: E402


def _key(country: str, city: str, site: str) -> str:
    base = strip_accents(f"{country}|{city or site}".lower())
    return " ".join(base.split())


def _blank() -> dict[str, Any]:
    return {"expected_count_hint": None, "expected_basis": "",
            "mentioned_by": [], "leads": []}


def _absorb(entry: dict[str, Any], key: str, lead: dict[str, Any], searched: str) -> None:
    for ex in entry["leads"]:
        if ex.get("_key") == key:
            urls = {(s or {}).get("url") for s in ex["sources"]}
            for s in lead.get("sources") or []:
                if (s or {}).get("url") not in urls:
                    ex["sources"].append(s)
            if searched and searched not in ex["mentioned_by"]:
                ex["mentioned_by"].append(searched)
            if searched and searched not in entry["mentioned_by"]:
                entry["mentioned_by"].append(searched)
            return


def run(args: argparse.Namespace) -> int:
    recon = load_records(args.infile)
    by_country: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    cross_border = 0

    for block in recon:
        searched = str(block.get("searched_country") or "").strip()

        # Per-country expected-count anchor from any recon agent's self count.
        hint = block.get("self_count_hint") or {}
        hc = str(hint.get("country") or searched).strip()
        if hc and hint.get("expected") is not None:
            entry = by_country.setdefault(hc, _blank())
            cur = entry["expected_count_hint"]
            if cur in (None, "tbd") or (isinstance(hint["expected"], (int, float))
                                        and hint["expected"] > (cur or 0)):
                entry["expected_count_hint"] = hint["expected"]
                entry["expected_basis"] = str(hint.get("basis") or "")

        for lead in block.get("leads") or []:
            about = str(lead.get("country") or "").strip()
            if not about:
                continue
            city = str(lead.get("city") or "").strip()
            site = str(lead.get("site_hint") or "").strip()
            k = _key(about, city, site)
            if k in seen:
                _absorb(by_country[about], k, lead, searched)
                continue
            seen.add(k)
            entry = by_country.setdefault(about, _blank())
            entry["leads"].append({
                "city": city, "site_hint": site,
                "confidence": lead.get("confidence", "tbd"),
                "sources": list(lead.get("sources") or []),
                "mentioned_by": [searched] if searched else [],
                "_key": k,
            })
            if searched and searched != about:
                cross_border += 1
            if searched and searched not in entry["mentioned_by"]:
                entry["mentioned_by"].append(searched)

    for e in by_country.values():
        e["lead_count"] = len(e["leads"])
        for lead in e["leads"]:
            lead.pop("_key", None)

    save_records(args.out, by_country)
    print(f"Consolidated {len(recon)} recon block(s) -> {len(by_country)} country brief(s) "
          f"-> {args.out}")
    print(f"  {sum(e['lead_count'] for e in by_country.values())} unique lead(s), "
          f"{cross_border} surfaced from a different country's search (cross-border).")
    anchored = [c for c, e in by_country.items()
                if e["expected_count_hint"] not in (None, "tbd")]
    if anchored:
        print(f"  per-country expected-count anchor set for: {', '.join(sorted(anchored))}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Consolidate recon leads per country.")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
