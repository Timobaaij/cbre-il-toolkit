# -*- coding: utf-8 -*-
"""Map an EverGreen export (raw.json from profile_export.py) to canonical unit records.

    python evergreen_units.py work/raw.json report/units.json [--mapping work/mapping.json]
                              [--as-at YYYY-MM-DD]

A STARTING POINT, not a pipeline. It encodes the cleaning rules that must never
be broken (0 = unknown, placeholder dates, leased vs owned) and makes every
client-specific judgement overridable through mapping.json, which the data
agent writes after reading profile.md:

  {
    "asAt": "2026-09-22",                       export / valuation date
    "groups": {"<Tenant/Occupier value>": ["Short label", "Full name"]},
    "tenure": {"<Status value>": "Leased" | "Leased (regeared)" | "Owned" | ...},
    "owned_statuses": ["<extra Status values meaning owned>"],   added to the defaults
    "not_owned_statuses": ["<a default owned status that is not owned here>"],
    "overrides": {"<Building ID>": {"<field>": <value>, ...}},     per-unit corrections
                  e.g. {"tenure": "Owned", "owned": true} or {"siteCover": null}.
                  Applied last, after --extend, so they always win.
    "acknowledged": ["<Building ID>"],   warnings about these ids are dealt with (say how in notes)
    "intra_landlords": ["<landlord values that are the client itself>"],
    "landlord_fix": {"<raw landlord>": "<display name>"},
    "exclude_ids": ["<Building ID>"],             only with a stated reason in notes
    "short_override": {"<Building ID>": "<display short name>"},
    "name_override": {"<Building ID>": "<full display name / address line>"},
    "notes": "why each non-default choice was made"
  }

Read the warnings it prints. If the export has columns this script does not
map, or the client needs a field it does not produce, extend units.json in
your own code - never by hand-editing figures.
"""
import argparse, datetime, json, os, re, sys
from collections import Counter, defaultdict

GENERIC = re.compile(r"^(unit|plot|building|block|bay|warehouse|phase|site|dc)\b", re.I)
YES, NO = {"yes", "y", "true"}, {"no", "n", "false"}
DEFAULT_TENURE = {"Let": "Leased", "Lease Regear": "Leased (regeared)",
                  "Sold (To Owner Occupier)": "Owned", "Owner Occupied": "Owned",
                  "Freehold": "Owned", "Owned": "Owned"}
DEFAULT_OWNED = {"Sold (To Owner Occupier)", "Owner Occupied", "Freehold", "Owned"}
# Text EverGreen uses for 'nobody entered this'. Never a real counterparty.
PLACEHOLDERS = Counter()                  # placeholder dates nulled, reported at the end
PLACEHOLDER_NAMES = {"not applicable", "unknown", "n a", "na", "none", "tbc", "to be confirmed", "-", ""}
CORE = ["rent", "expiry", "epc", "eaves", "siteAcres", "dockDoors", "yard", "power", "leaseTerm", "coldStore"]


def norm(h):
    return re.sub(r"[^a-z0-9]+", " ", str(h or "").lower()).strip()


class Row:
    """Header-tolerant accessor: exact normalised match first, then 'contains'."""
    def __init__(self, rec, index):
        self.rec, self.index = rec, index

    def get(self, *names):
        for n in names:
            k = self.index.get(norm(n))
            if k is None:
                # 'contains' only when it is unambiguous: "Status" must never
                # quietly resolve to "Construction status".
                hits = [v for nk, v in self.index.items() if norm(n) in nk]
                k = hits[0] if len(hits) == 1 else None
            if k is not None and self.rec.get(k) not in (None, ""):
                return self.rec.get(k)
        return None


EPC_BAND = re.compile(r"^\s*(A\+{0,2}|[B-G])\s*$", re.I)


def epc_band(v):
    """EPC letter only when the cell is a band. 'Exempt', 'N/A', 'Awaiting' -> None
    (the raw text is kept in epcRaw); taking the first letter made 'Exempt' an E."""
    t = s(v)
    if not t:
        return None
    m = EPC_BAND.match(t)
    return m.group(1).upper()[0] if m else None


def s(v):
    if v is None:
        return None
    t = str(v).strip()
    return None if t == "" or t.lower() in ("none", "nan", "null") else t


def n(v):
    t = s(v)
    if t is None:
        return None
    try:
        return float(t.replace(",", "").replace("£", ""))
    except ValueError:
        return None


def nz(v):
    """Numeric where a literal 0 means UNKNOWN (EverGreen's empty value) -> None."""
    f = n(v)
    return None if f is None or f == 0 else f


def dt(v):
    t = s(v)
    if t is None:
        return None
    try:
        d = datetime.date.fromisoformat(t[:10])
    except ValueError:
        return None
    if d.year <= 1950:                         # 1950-01-01, 1905-06-01 = placeholders
        PLACEHOLDERS[t[:10]] += 1
        return None
    return d


def iso(d):
    return d.isoformat() if d else None


def yn(v):
    t = (s(v) or "").lower()
    return True if t in YES else False if t in NO else None


def tidy_landlord(v):
    """ALL CAPS or all-lower multi-word names -> readable case. A single all-caps
    token is a brand or an acronym (e.g. 'ACME', 'XYZ') and is kept as written."""
    if not v:
        return v
    words = v.split()
    if v.isupper() and len(words) == 1:
        return v
    if v.isupper() or v.islower():
        keep = {"PLC", "LLP", "LP", "UK", "REIT"}
        return " ".join(w.upper() if (v.isupper() and len(w) <= 3) or w.upper() in keep else w.capitalize()
                        for w in words)
    return v


def quarter_year(v):
    """'2019 Q3' -> 2019 (Deal quarter is often filled when Deal date is a placeholder)."""
    m = re.match(r"^\s*(\d{4})\s*Q[1-4]\s*$", s(v) or "")
    return int(m.group(1)) if m and int(m.group(1)) > 1950 else None


def lease_state(owned, start, expiry, as_at):
    """One vocabulary for every view. 'running' = started and not yet at its
    recorded end; a lease that starts after the as-at date is 'not started' and
    must never count towards WAULT or 'unexpired' figures."""
    if owned:
        return "owned"
    if not expiry:
        return "undated"
    if expiry < as_at:
        return "passed"
    if start and start > as_at:
        return "not started"
    return "running"


def group_label(t):
    """'Parent / Brand' -> 'Brand'; strips legal suffixes. Override in mapping.json."""
    if not t:
        return t
    lab = t.split("/")[-1].strip() if "/" in t else t
    lab = re.sub(r"\b(limited|ltd\.?|plc|llp|inc\.?|group)\b\.?", "", lab, flags=re.I).strip(" ,.-")
    return lab or t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw"); ap.add_argument("out")
    ap.add_argument("--mapping"); ap.add_argument("--as-at")
    ap.add_argument("--extend", help="a .py file defining extend(units, raw, as_at) -> units; runs after "
                                     "mapping on every run, so client-specific fields survive re-runs")
    a = ap.parse_args()

    raw = json.load(open(a.raw, encoding="utf-8"))
    mp = json.load(open(a.mapping, encoding="utf-8")) if a.mapping and os.path.exists(a.mapping) else {}
    as_at = datetime.date.fromisoformat(a.as_at or mp.get("asAt") or datetime.date.today().isoformat())
    groups = mp.get("groups", {})
    tenure_map = {**DEFAULT_TENURE, **mp.get("tenure", {})}
    # Added to the defaults, never replacing them; and any status the tenure map
    # calls "Owned" is owned, so the two settings cannot disagree.
    owned_set = set(DEFAULT_OWNED) | set(mp.get("owned_statuses", [])) | \
        {k for k, v in tenure_map.items() if str(v).lower() == "owned"}
    owned_set -= set(mp.get("not_owned_statuses", []))
    intra = {norm(x) for x in mp.get("intra_landlords", [])}
    overrides = {str(k): v for k, v in mp.get("overrides", {}).items()}
    ll_fix = mp.get("landlord_fix", {})
    exclude = {str(x) for x in mp.get("exclude_ids", [])}
    short_over = {str(k): v for k, v in mp.get("short_override", {}).items()}
    name_over = {str(k): v for k, v in mp.get("name_override", {}).items()}
    index = {norm(k): k for k in (raw[0].keys() if raw else [])}

    warn, zeroed = [], Counter()
    third_party_on_owned = []
    recs = []
    for rr in raw:
        r = Row(rr, index)
        bid = s(r.get("Building ID"))
        if bid in exclude:
            continue

        def z(*names, key):
            v = r.get(*names)
            out = nz(v)
            if out is None and n(v) == 0:
                zeroed[key] += 1
            return out

        lat = lng = None
        ll = s(r.get("Latitude, Longitude"))
        if ll and "," in ll:
            p, q = ll.split(",", 1)
            lat, lng = n(p), n(q)
        else:
            lat, lng = n(r.get("Latitude")), n(r.get("Longitude"))

        expiry, brk, start = dt(r.get("Lease expiry date")), dt(r.get("Break date")), dt(r.get("Lease start date"))
        future = [d for d in (brk, expiry) if d and d >= as_at]
        tenant = s(r.get("Tenant/Occupier", "Tenant", "Occupier"))
        short_g, full_g = groups.get(tenant, (group_label(tenant), tenant))
        ll_raw = s(r.get("Landlord"))
        if ll_raw and norm(ll_raw) in PLACEHOLDER_NAMES:    # 'Not Applicable', 'Unknown', 'N/A'
            ll_raw = None
        status = s(r.get("Status"))
        owned = status in owned_set
        name = s(r.get("Marketing Name")) or s(r.get("Address"))
        park, town = s(r.get("Logistics park")), s(r.get("Town"))

        short = "Unit"
        if name:
            parts = [x.strip() for x in name.split(",") if x.strip()]
            first = parts[0]
            if GENERIC.match(first):
                extra = park if park and park.lower() not in first.lower() else \
                    (parts[1] if len(parts) > 1 and parts[1].lower() != (town or "").lower() else None)
                short = first + ", " + extra if extra else first
            else:
                short = first

        if bid in short_over:
            short = short_over[bid]
        if bid in name_over:
            name = name_over[bid]
        pc = dt(r.get("PC of construction"))
        deal = dt(r.get("Deal date"))
        deal_q_year = quarter_year(r.get("Deal quarter"))
        state = lease_state(owned, start, expiry, as_at)
        if state != "owned" and ll_raw and (norm(ll_raw) in intra or (tenant and norm(ll_raw) == norm(tenant))):
            warn.append(f"{bid} {short}: recorded as '{status}' with the client itself as landlord - "
                        f"intra-group lease, or owned and mis-recorded? Decide and note it")
        if expiry and start and expiry <= start:
            warn.append(f"{bid} {short}: lease expiry {expiry} is not after its start {start}")
        if start and pc and (pc - start).days > 31:
            warn.append(f"{bid} {short}: lease starts {start} but the building completed {pc.isoformat()[:7]}")
        rev = dt(r.get("Next rent review"))
        upd = dt(r.get("Building last updated date"))
        rec = {
            "id": bid, "name": name, "short": short, "town": town,
            "postcode": s(r.get("Postcode")), "region": s(r.get("Region")),
            "corridor": s(r.get("Road corridor")), "park": park, "lat": lat, "lng": lng,
            "group": short_g, "groupFull": full_g, "tenantRaw": tenant,
            "landlord": ll_fix.get(ll_raw, tidy_landlord(ll_raw)),
            "landlordIntra": bool(ll_raw and (norm(ll_raw) in intra or (tenant and norm(ll_raw) == norm(tenant)))),
            "developer": s(r.get("Developer")),
            "status": status, "tenure": tenure_map.get(status, status), "owned": owned,
            "size": n(r.get("Size (sq ft)")) or 0,
            "siteAcres": z("Site area (acres)", key="siteAcres"), "siteCover": z("Site ratio", key="siteCover"),
            "provenance": s(r.get("Speculative, BTS or Second hand")), "quality": s(r.get("Quality of unit")),
            "pcYear": pc.year if pc else None, "pcDate": iso(pc),
            "dealQuarter": s(r.get("Deal quarter")) if deal_q_year else None,
            "rowOrder": len(recs) + 1,          # position in the export: patterns hide in entry order
            "rent": z("Achieved rent", key="rent"), "rentPa": z("Rent per annum", key="rentPa"),
            "dealDate": iso(deal), "dealYear": deal.year if deal else deal_q_year,
            "dealYearFrom": "date" if deal else ("quarter" if deal_q_year else None),
            "leaseStart": iso(start), "leaseTerm": z("Lease terms (yrs)", key="leaseTerm"),
            "expiry": iso(expiry), "expiryYear": expiry.year if expiry else None,
            # Unexpired term only while the recorded end is still ahead; a passed
            # expiry gets yearsSinceExpiry instead, so no average can go negative.
            "yearsToExpiry": round((expiry - as_at).days / 365.25, 2) if expiry and expiry >= as_at else None,
            "yearsSinceExpiry": round((as_at - expiry).days / 365.25, 2) if expiry and expiry < as_at else None,
            "contractedOut": yn(r.get("Is lease outside the L&T act?")),
            # 'expired' = the RECORDED expiry date has passed. It does not mean the
            # client has no lease (holding over / regeared / vacated). Say "recorded
            # expiry passed" in copy, never "expired lease".
            "expired": bool(expiry and expiry < as_at),
            "leaseState": state,
            "started": (start <= as_at) if start else None,
            "breakDate": iso(brk), "nearestEvent": iso(min(future)) if future else None,
            "rentReview": iso(rev), "reviewType": s(r.get("Type of rent review")),
            "incentive": z("Incentive (months)", key="incentive"),
            "eaves": z("Eaves (m)", key="eaves"), "yard": z("Yard depth (m)", key="yard"),
            "office": z("Office content (sq ft)", key="office"), "officeRatio": z("Office ratio", key="officeRatio"),
            "floorLoad": z("Floor loading", key="floorLoad"),
            "dockDoors": z("No. of dock level doors", key="dockDoors"),
            "levelDoors": z("No. of level access doors", key="levelDoors"),
            "totalDoors": z("Total doors", key="totalDoors"), "doorRatio": z("Door ratio", key="doorRatio"),
            "power": z("Power (KVA)", key="power"), "trailers": z("No. of trailer spaces", key="trailers"),
            "carSpaces": z("No. of car parking spaces", key="carSpaces"),
            "epc": epc_band(r.get("EPC rating")), "epcRaw": s(r.get("EPC rating")),
            "breeam": s(r.get("BREEAM rating")),
            "coldStore": yn(r.get("Cold storage")), "crossDock": yn(r.get("Cross docked")),
            "circ360": yn(r.get("360 HGV circulation")), "gatehouse": yn(r.get("Gatehouse")),
            "truckwash": yn(r.get("Truckwash")), "hgvFuel": yn(r.get("HGV refuelling facilities")),
            "vmu": yn(r.get("VMU")), "sharedAccess": yn(r.get("Shared HGV/Car access")),
            "solus": s(r.get("Solus unit/park")), "rail": s(r.get("Rail connected")),
            "agentDisposal": [x for x in (s(r.get(f"Disposal agent {i}")) for i in (1, 2, 3))
                              if x and x not in ("Unknown", "Not Applicable")],
            "agentAcq": [x for x in (s(r.get(f"Acquisition agent {i}")) for i in (1, 2))
                         if x and x not in ("Unknown", "Not Applicable")],
            "updatedBy": s(r.get("Building last updated")), "updated": iso(upd),
        }
        if bid in overrides:
            # Per-unit corrections from mapping.json, e.g. {"tenure":"Owned","owned":true},
            # {"size": 12500}, {"siteCover": null}. Recorded in 'overridden' for the ledger.
            rec.update(overrides[bid])
            rec["overridden"] = sorted(overrides[bid])
            if any(k in overrides[bid] for k in ("owned", "tenure", "expiry", "leaseStart")):
                d = lambda k: datetime.date.fromisoformat(rec[k]) if rec.get(k) else None
                rec["leaseState"] = lease_state(rec.get("owned"), d("leaseStart"), d("expiry"), as_at)
        if owned and ll_raw and not rec["landlordIntra"]:
            third_party_on_owned.append(f"{bid} {short} ({rec['landlord']})")
        rec["completeness"] = round(sum(1 for f in CORE if rec.get(f) is not None) / len(CORE) * 100)
        if not rec["size"]:
            warn.append(f"{bid} {short}: no size - excluded from floorspace totals, still listed")
        if lat is None:
            warn.append(f"{bid} {short}: no coordinates - will not appear on the map")
        if rec["siteCover"] and rec["siteCover"] > 100:
            warn.append(f"{bid} {short}: site cover {rec['siteCover']}% is impossible - treat as unknown in analysis")
        recs.append(rec)

    # Templated lease dates: when most leases share one term length and a handful
    # of start days, the dates may be defaults typed at record creation rather
    # than read from leases. Any headline built on them must say so.
    dated = [x for x in recs if x["leaseStart"] and x["expiry"]]
    if len(dated) >= 6:
        terms = Counter(round((datetime.date.fromisoformat(x["expiry"]) -
                               datetime.date.fromisoformat(x["leaseStart"])).days / 365.25, 1) for x in dated)
        days = Counter(x["leaseStart"][5:] for x in dated)
        t_share = terms.most_common(1)[0][1] / len(dated)
        d_share = sum(n for _, n in days.most_common(4)) / len(dated)
        if t_share >= .7 or d_share >= .7:
            warn.append(f"lease dates look templated: {terms.most_common(1)[0][1]}/{len(dated)} share a "
                        f"{terms.most_common(1)[0][0]}-year term; {sum(n for _, n in days.most_common(4))}/"
                        f"{len(dated)} start on 4 calendar days. Verify against leases before any headline rests on them")

    # Identical short names are unreadable in a table or a legend.
    seen = defaultdict(list)
    for x in recs:
        seen[x["short"]].append(x)
    for nm, xs in seen.items():
        if len(xs) > 1:
            tenures = {x["tenure"] for x in xs}
            for x in xs:
                x["short"] = f"{nm} ({x['tenure'].lower()})" if len(tenures) == len(xs) \
                    else f"{nm} ({format(int(x['size']), ',')} sq ft)"
            warn.append(f"duplicate name '{nm}' x{len(xs)} - disambiguated; check whether these are "
                        f"separate demises or one record entered twice")

    sizes = Counter(x["size"] for x in recs if x["size"])
    for sz, k in sizes.items():
        if k > 1:
            warn.append(f"{k} units share an identical size of {sz:,.0f} sq ft "
                        f"({', '.join(x['short'] for x in recs if x['size'] == sz)}) - duplicates or real?")
    if third_party_on_owned:
        warn.append(f"{len(third_party_on_owned)} owned unit(s) name a landlord that is not marked intra-group - "
                    f"confirm title before calling them freeholds: {'; '.join(third_party_on_owned)}")
    tenants = {norm(x["tenantRaw"]) for x in recs if x["tenantRaw"]}
    probable = sorted({x["landlord"] for x in recs if x["landlord"] and not x["landlordIntra"]
                       and any(re.search(r"\b" + re.escape(norm(x["landlord"])) + r"\b", t) for t in tenants)})
    if probable:
        warn.append(f"landlord names that also appear in Tenant/Occupier, probably intra-group - add to "
                    f"'intra_landlords' if so: {probable}")
    if PLACEHOLDERS:
        print(f"placeholder dates (year <= 1950) nulled: {sum(PLACEHOLDERS.values())}")

    if a.extend:
        import importlib.util
        spec = importlib.util.spec_from_file_location("extend_units", a.extend)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        recs = mod.extend(recs, raw, as_at) or recs
        print("extended with", a.extend)
        # Corrections win: re-apply overrides so an extension can never undo them.
        for x in recs:
            o = overrides.get(str(x.get("id")))
            if o:
                x.update(o)
                d = lambda k: datetime.date.fromisoformat(x[k]) if x.get(k) else None
                x["leaseState"] = lease_state(x.get("owned"), d("leaseStart"), d("expiry"), as_at)
    if overrides:
        print("overrides applied:", {k: sorted(v) for k, v in overrides.items()})

    # Warnings already dealt with (ids listed under "acknowledged" in mapping.json,
    # with the reason in notes) stay quiet; everything else prints every run.
    ack = {str(x) for x in mp.get("acknowledged", [])}
    if ack:
        before = len(warn)
        warn = [w for w in warn if not any(w.startswith(i + " ") or f" {i} " in w for i in ack)]
        print(f"acknowledged warnings suppressed: {before - len(warn)}")

    recs.sort(key=lambda x: -(x["size"] or 0))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, separators=(",", ":"))

    tot = sum(x["size"] or 0 for x in recs)
    leased = [x for x in recs if not x["owned"]]
    run = [x for x in leased if x["leaseState"] == "running"]
    print(f"{len(recs)} units, {tot:,.0f} sq ft, as at {as_at}")
    print(f"owned {sum(1 for x in recs if x['owned'])} | leased {len(leased)} | lease states "
          f"{dict(Counter(x['leaseState'] for x in recs))}")
    if run:
        w = sum(x["size"] * x["yearsToExpiry"] for x in run) / sum(x["size"] for x in run)
        print(f"WAULT to expiry, running leases only: {w:.2f} yrs on {len(run)} leases, "
              f"{sum(x['size'] for x in run):,.0f} sq ft")
    print("groups:", dict(Counter(x["group"] for x in recs)))
    print("tenure:", dict(Counter(x["tenure"] for x in recs)))
    unmapped = sorted({x["status"] for x in recs if x["status"] and x["status"] not in tenure_map})
    if unmapped:
        warn.append(f"Status values with no tenure mapping (passed through): {unmapped}")
    if not groups:
        warn.append("no 'groups' in mapping.json - group labels are heuristic; check them")
    if zeroed:
        print("literal 0 -> unknown:", dict(zeroed))
    for w in warn:
        print("WARNING", w)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
