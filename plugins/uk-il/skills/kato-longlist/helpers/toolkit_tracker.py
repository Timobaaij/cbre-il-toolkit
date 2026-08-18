#!/usr/bin/env python3
"""Toolkit step 1 (deterministic): from our enriched _dataset.json, write the inputs the
cbre-il-toolkit longlist skill consumes as its DATA source - one availability tracker xlsx +
a project.yaml (all enrichment on, ORS key baked, emails none). No brochures here (we inject
photos ourselves and pull site plans via vision), so the toolkit data build stays fast."""
import os, sys, argparse, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, read_json, dedupe_props
from openpyxl import Workbook

_BARE_UNIT = re.compile(r"(?i)^units?\b[\s\w\-\/&]{0,4}$")

def display_name(p):
    """A descriptive, UNIQUE card title. Kato's address.name is often blank or a bare
    'Unit 2', which leaves cards untitled and - worse - lets the toolkit matcher merge two
    distinct nameless units (e.g. Premier Park Unit A vs Unit B). So compose from the address:
    take the unit designator + the scheme name, never leaving it blank."""
    a = p.get("address") or {}
    name = (a.get("name") or "").strip()
    addr = ", ".join(x for x in [(a.get("line1") or "").strip(), (a.get("line2") or "").strip()] if x)
    segs = [s.strip() for s in addr.split(",") if s.strip()]
    scheme = next((s for s in segs if not _BARE_UNIT.match(s)), "")
    unit = next((s for s in segs if _BARE_UNIT.match(s)), "")
    if name and not _BARE_UNIT.match(name):
        return name                                   # already descriptive
    if name:                                          # bare unit -> enrich with scheme
        return f"{name}, {scheme}" if scheme and scheme.lower() not in name.lower() else name
    if unit and scheme:
        return f"{unit}, {scheme}"                    # blank name, addr has both
    if scheme:
        return scheme
    # last resort: folder middle segment ("07 - Alfreds Way Barking - IG11 9PG" -> "Alfreds Way Barking")
    fol = re.sub(r"^\d+\s*-\s*", "", p.get("folder") or "")
    pc = a.get("postcode")
    if pc and fol.endswith(pc):
        fol = fol[: -len(pc)].rstrip(" -")
    return fol or addr or "tbd"

HEADERS = ["Property", "Address", "City", "Region", "Country", "Postcode", "Coordinates (lat,lng)",
           "GLA (sq ft)", "Tenure", "Availability", "Warehouse rent (GBP/sq ft/yr)", "Rent basis",
           "Service charge (GBP/sq ft)", "Rates payable (GBP/yr)", "Clear height", "Power",
           "Loading doors", "Yard depth", "Car parking", "Floor loading", "EPC", "BREEAM",
           "Agent", "Description"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--inputs", default=None, help="toolkit inputs dir (default: <work>/longlist_inputs)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    work = cfg["work_dir"]
    inputs = args.inputs or os.path.join(work, "longlist_inputs")
    os.makedirs(inputs, exist_ok=True)
    ds = read_json(os.path.join(work, "properties", "_dataset.json"), {}) or {}
    props_all = ds.get("properties", [])
    props = dedupe_props(props_all)
    n_dupes = len(props_all) - len(props)

    wb = Workbook(); ws = wb.active; ws.title = "Availability"; ws.append(HEADERS)
    for p in props:
        a = p.get("address") or {}; sp = p.get("spec") or {}; og = p.get("outgoings") or {}
        r = p.get("rent") or {}; ags = p.get("agents") or []
        mp = (p.get("coordinates") or {}).get("map") or {}
        coord = f"{mp.get('lat')},{mp.get('lng')}" if mp.get("lat") is not None else ""
        agent = "; ".join(x for x in [p.get("agent_organisation"),
                                      (ags[0]["name"] if ags and ags[0].get("name") else None)] if x)
        rent = r.get("value") if r.get("value") is not None else (
            "tbd" if (r.get("text") or "").lower().startswith("on application") else (r.get("text") or "tbd"))
        ws.append([display_name(p), ", ".join(x for x in [a.get("line1"), a.get("line2")] if x),
                   a.get("town"), p.get("area") or a.get("town"), "United Kingdom", a.get("postcode"), coord,
                   (p.get("size") or {}).get("sqft"), p.get("tenure"), sp.get("availability"),
                   rent, r.get("basis"), og.get("service_charge"), og.get("rates_payable"),
                   sp.get("clear_height"), sp.get("power"), sp.get("loading"), sp.get("yard"),
                   sp.get("parking"), sp.get("floor_loading"), sp.get("epc"), sp.get("breeam"),
                   agent, p.get("summary")])
    wb.save(os.path.join(inputs, "Kato Longlist - Availability Schedule.xlsx"))

    client = cfg.get("client") or ds.get("client") or "Kato Longlist"
    ors = cfg.get("ors_api_key") or ""
    yaml_txt = f'''client:
  name: "{client}"
  confidential: true
market:
  title_html: "Industrial &amp; Logistics <em>options</em>."
  eyebrow: ""
  region_label: ""
  countries: ["GB"]
  lede: ""
output:
  filename: ""
  compiled_date: ""
  language: "English"
inputs:
  folder: "."
  emails:
    source: none
enrichment:
  geocode: true
  pois: true
  osrm: true
  regions: true
  osrm_endpoint: "https://router.project-osrm.org"
  ors_api_key: "{ors}"
qa:
  fill_threshold: 0.6
'''
    open(os.path.join(inputs, "project.yaml"), "w", encoding="utf-8").write(yaml_txt)
    print(f"tracker + project.yaml -> {inputs} ({len(props)} rows, {n_dupes} multi-broker duplicate(s) merged) "
          f"| client={client!r} | ors_key={'set' if ors else 'MISSING'}")

if __name__ == "__main__":
    main()
