# EverGreen data: rules, traps and judgement

EverGreen is CBRE's building database. A client export is one sheet, one row per
building/demise, about 79 columns. The columns look complete. Many are not: the
system writes **0** and **1950-01-01** where nobody entered anything. Most wrong
numbers in a portfolio report come from here.

## The rules that never bend

1. **Literal 0 in a measurement column means UNKNOWN.** Rent, eaves, yard, doors,
   power, office content, site area, lease term, incentive: 0 becomes null.
   A genuine zero is almost never recorded. If one might be real (for example
   0 dock doors on a known cross-dock site), say why in the ledger.
2. **Dates with year ≤ 1950 are placeholders** (`1950-01-01` deal dates,
   `1905-06-01` construction dates). They become null and are never plotted.
3. **Every aggregate carries its denominator.** "Rent is recorded on 14 of 52
   units", never "average rent £6.40" alone. A weighted average states what it
   is weighted by and what it covers.
4. **"Not recorded" is a finding, not a gap to paper over.** Never extrapolate a
   known subset across the portfolio (no "estimated total rent roll" grossed up from a handful of rents).
   In copy: *n/r* = not recorded, *—* = not applicable.
5. **Owned vs leased.** `Status = Sold (To Owner Occupier)` means the client owns
   the freehold. EverGreen still fills `Landlord` on those rows (often the seller
   or the client itself), so **landlord analysis uses leased units only**.
   Including freeholds once understated a landlord concentration by six points.
6. **One lease vocabulary: `leaseState`.** The mapper gives every unit one of
   `running` (started, recorded end not reached), `not started` (starts after the
   as-at date), `passed` (recorded expiry already passed), `undated` or `owned`.
   A past expiry ≠ no lease: it means holding over, regeared but not updated, or
   vacated. Write "recorded expiry already passed" (uk-rules.md §2), never
   "expired lease". WAULT and "unexpired" figures use **running leases only**,
   and say so. A not-started lease is a future commitment, reported separately.
7. **As-at date.** Everything time-based (years to expiry, "next 5 years", lapsed)
   is measured from the export date, not the day you run the skill. It is usually
   in the file name (`Building_Data_DD_MM_YYYY.xlsx`). Put it in `meta.json`.
8. **Never hand-edit a figure.** Change the mapping or the code, re-run, re-verify.

## Workflow for the data agent

```
python scripts/profile_export.py <export.xlsx> work/      # raw.json + profile.md
# read profile.md in full, then write work/mapping.json (see evergreen_units.py docstring)
python scripts/evergreen_units.py work/raw.json report/units.json --mapping work/mapping.json --as-at YYYY-MM-DD
```
Read every WARNING it prints. Then write `work/data-notes.md`: what you mapped and
why, every judgement call, every anomaly (duplicates, impossible values such as a
site cover above 100%, sizes that look like m², postcodes outside the stated
region), and the fill rate of every field the analysis might lean on.

**Judgement calls that belong to you, not the script:**
- **Group / operating company labels.** `Tenant/Occupier` holds the legal or
  trading entity ("Parent / Brand", "X Distribution Limited"). Choose short,
  client-recognisable labels, and keep the full name in `groupFull`. If the
  client is a single occupier, the group dimension is meaningless: say so, and
  let the storyline and dashboard drop it.
- **Intra-group landlords.** Where `Landlord` is the client itself or a sister
  company, set `intra_landlords`. Those units are not third-party exposure.
- **Tenure mapping** for any `Status` value the defaults don't know.
- **Duplicates.** The script disambiguates identical names. You decide whether
  they are two demises (keep both) or one record entered twice (exclude one, with
  the reason in `notes`).
- **Names.** If a generated short name or display name reads badly, fix it with
  `short_override` / `name_override` in mapping.json (keyed by Building ID).
  Don't post-process `units.json`. The table and charts print `short`, but the
  **drawer, map pop-ups and CSV print `name`**. When a marketing name carries
  another company's brand (a previous occupier, a developer), fix **both**. A
  run once leaked a former occupier's name into the client file through `name`
  alone.
- **Per-unit corrections.** `overrides` in mapping.json sets any field for one
  Building ID: a tenure (`{"tenure": "Owned", "owned": true}`), a size you've
  converted from m², or `null` for an impossible value. The mapper recomputes
  `leaseState` and records the change in `overridden`.
- **Client-specific fields** go in `work/extend_units.py`, which defines
  `extend(units, raw, as_at)`. Pass it with `--extend` on every run, so a re-run
  never wipes them.
- **What the mapper already does.** EPC takes a band only (A+ to G). "Exempt" or
  "N/A" become null, with the text kept in `epcRaw`. `contractedOut` comes from
  `Is lease outside the L&T act?`. `yearsToExpiry` is null once an expiry has
  passed, with `yearsSinceExpiry` instead. The deal year falls back to
  `Deal quarter` (`dealYearFrom` says which). Owned statuses add to the defaults.
- **Fill rates** are stated against the right base: all units for building
  fields, leased units for lease fields, running leases for events.
- **Regions** are EverGreen's own labels ("Yorkshire & NE"), not ONS regions.
  Don't present them as official statistics geography.
- **Templated dates.** If the mapper warns that lease dates look templated (one
  term length, a handful of start days), treat every date-driven headline as
  "as recorded, to be verified against the leases", and say so in the ledger.
- **The client as landlord.** A "Let" row whose landlord is the client or a
  sister company is either an intra-group lease or a mis-recorded freehold.
  Decide which (set `intra_landlords` or `tenure`) and note it.
- **Extra fields.** If this client needs something the canonical schema lacks,
  add it to `units.json` in your own code and document it (e.g. a flag for
  temperature-controlled sites derived from `Cold storage`).
- **Wording.** Notes that may surface in the client file (drawer notes,
  provenance) must be client English: "Lease dates as recorded; not yet checked
  against the lease", never "ISO dates", "relabelled" or column names.

## Column guide (what each column really tells you)

| Column | Use | Trap |
|---|---|---|
| Building ID | stable key | — |
| Marketing Name / Address | display name | many start "Unit 1" or "Plot A": qualify with park (the script does) |
| Town, Region, Postcode, Road corridor, Logistics park | geography, clustering | `M25 segment` is "N/A" for anything outside the M25 |
| Latitude, Longitude | one text cell "lat, lng" | check the coverage count in profile.md |
| Tenant/Occupier | operating company | legal names; relabel |
| Landlord | counterparty | filled on freeholds too; inconsistent casing (all lower-case, ALL CAPS); placeholder names such as "Not Applicable" |
| Status | tenure | Let / Lease Regear / Sold (To Owner Occupier) |
| Size (sq ft) + Size Unit | floorspace, GIA | the only measure present on every row |
| Achieved rent (£ per sq ft) | passing rent | usually 0 (unknown) on most rows; quoting-rent columns are almost always 0 |
| Rent per annum (£) | contracted rent | rarely filled |
| Deal date / Deal quarter | when the rent was struck | 1950 placeholders |
| Lease start / expiry / terms, Break date, Next rent review, Type of rent review | lease events | often half empty; past dates are common and meaningful |
| Is lease outside the L&T act? | contracted out? | usually empty: say "not recorded" |
| Incentive (months) | rent-free | 0 = unknown |
| EPC rating, BREEAM rating | ESG | sparse; no EPC date held |
| Quality of unit, Speculative/BTS/Second hand, PC of construction | asset quality and age | 1905 placeholders in PC |
| Eaves, Yard depth, Floor loading, doors, Power, Site area, Site ratio, Office content/ratio, trailer/car spaces | operational spec | 0 = unknown on many rows; Site ratio can exceed 100 (data error) |
| Cold storage, Cross docked, 360 HGV circulation, Gatehouse, Truckwash, HGV refuelling, VMU, Shared HGV/Car access, Rail connected, Solus unit/park | capability flags | blank ≠ No. "Shared HGV/Car access = Yes" is a negative |
| EV charge, electric charging spaces, Solar panels | ESG infrastructure | often single-valued or empty: a finding in itself |
| Disposal / Acquisition agent 1-3 | market history | "Unknown", "Not Applicable" are placeholders |
| Landlord Verified, Tenant Verified | data assurance | usually all "No": worth one line in provenance |
| Building last updated (by / date), created | provenance | shows how fresh the record is |
| Confidential, Asset manager, Sector, Construction status | usually empty or single-valued | drop them from the analysis |

## Hand-off

The data agent hands over `report/units.json`, `work/mapping.json`,
`work/data-notes.md` and `work/profile.md`. Analysts compute from `units.json` with
their own code (Python or JS) and cite every figure in the ledger (committees.md).
