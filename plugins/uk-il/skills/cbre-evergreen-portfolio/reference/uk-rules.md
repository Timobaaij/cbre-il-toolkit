# UK rules the analysis may rely on

The ONLY outside facts a report may state. Each is dated and sourced. Verified
September 2026. If the report's as-at date is more than six months after that,
say in the provenance line that rules are "as at September 2026".

Status words matter. Write **"is"** only for law in force. Write **"is set to" /
"is proposed"** for a government target or consultation outcome. Never turn a
proposal into a deadline. ("From April 2030 a let building needs an EPC of B" is
the classic error: that proposal was superseded, so the line is wrong.)

---

## 1. MEES: minimum energy efficiency for let non-domestic property

**Where:** England and Wales only. Scotland and Northern Ireland differ (below).
**Who:** the obligation is the **landlord's**. For an occupier client it is
leverage: an upgrade the landlord must fund before it can keep letting, which
belongs in the renewal, regear or dilapidations conversation.

| Rule | Status | Source |
|---|---|---|
| Since **1 Apr 2018**, a landlord may not grant a new lease or renew one below **EPC E**. | In force | Energy Efficiency (Private Rented Property) (England and Wales) Regulations 2015 |
| Since **1 Apr 2023**, a landlord may not **continue** to let below EPC E (all existing lets). | In force | same |
| Applies to leases of **more than 6 months and less than 99 years** (a ≤6-month lease is caught if it has a renewal option or the tenant has already been in occupation >12 months). | In force | same |
| Exemptions (7-year payback, consent, devaluation, new landlord, all relevant improvements made) are registered on the **PRS Exemptions Register**. | In force | same |
| **From 2031**, let non-domestic buildings **over 1,000 m²** are set to need **EPC B, where cost-effective**. Buildings of 1,000 m² or less stay at EPC E with no further deadline. | **Target, not yet law.** Government interim response, 18 Jun 2026: "not the final position". Full response expected later in 2026 | GOV.UK, *MEES in the non-domestic private rented sector: interim response*, 18 Jun 2026 |
| The previously proposed **interim EPC C by 2027** will **not** go ahead. | Confirmed in the interim response | same |
| The 7-year payback test and exemptions remain. | Confirmed in the interim response | same |

**How to apply it to an EverGreen export**. There are two tests; never merge them.
- **Today's minimum (in force):** every **let** building in **England or Wales**,
  **of any size**, must be EPC **E or better** or hold a registered exemption. An
  F or G on a let building is a compliance issue now. Say so plainly, and say
  that an exemption may be registered (EverGreen doesn't record exemptions).
- **The 2031 target (not yet law):** let buildings in England or Wales **over
  1,000 m² (10,764 sq ft)** are set to need **EPC B, where cost-effective**. The
  interim response gives **no day or month**, so write "from 2031", never "from
  1 April 2031". A lease ending during 2031 is "around the time the target is set
  to start". Don't place it before or after the target.
- In both tests, a building is "let" when it is leased, not owned (an
  owner-occupied freehold is not let), and `region` is not Scotland or Northern
  Ireland. By lease state: **running**, **passed** (holding over is still a let)
  and **undated** leases are let. A **not started** lease is not yet let, so the
  rules bite from its start date; say so. An **intra-group** lease is still a let,
  so MEES applies. State each scope count explicitly ("41 of the 44 leased units are over
  1,000 m²; all 44 are subject to today's E minimum").
- EPC bands below B within scope = the upgrade list. **No EPC recorded is not the
  same as failing**: write "unrated" or "no EPC on record", and make getting the
  EPCs the first action.
- EverGreen holds the rating, not the certificate date. EPCs last **10 years**, so
  some recorded ratings may have expired. Say so if you rely on them. **Never
  infer an EPC's age or band from the build year.**
- **Lease length.** MEES covers leases of more than 6 months and less than 99
  years. EverGreen's `Lease terms (yrs)` is often unknown, so treat a let unit as
  in scope and say "assuming a lease within MEES's 6-month to 99-year range".
- **"Ending before 2031"** means a **running** lease whose recorded expiry, or
  first future break, falls before 1 Jan 2031. That is the moment to agree who
  funds the upgrade, because any renewal runs past 2031. Report passed expiries
  (already holding over?) and undated leases separately. Don't fold them into
  the count.

**Scotland:** Assessment of Energy Performance of Non-domestic Buildings (Scotland)
Regulations 2016. On **sale or a new lease** of a building **over 1,000 m²** that
does not meet 2002 building standards, the owner must provide a **Section 63
Action Plan** (improvements to be done within 42 months, or operational ratings
reported instead). A new Scottish EPC regime (Energy Performance of Buildings
(Scotland) Regulations 2025) takes effect **31 Oct 2026**. Mention it only if the
portfolio has Scottish units, and without detail beyond this.
**Northern Ireland:** no minimum standard for let non-domestic property.

## 2. Security of tenure: Landlord and Tenant Act 1954, Part II (England and Wales)

- A business tenancy is **protected** unless it was **contracted out**. At contractual
  expiry a protected tenancy **continues automatically on the same terms**
  ("holding over") until ended under the Act.
- Either side ends or renews it by statutory notice: the landlord by a **s.25
  notice**, the tenant by a **s.26 request**, each **6 to 12 months** ahead of the
  date given. The landlord can oppose a new lease only on the statutory grounds (s.30).
- **So a lease expiry date in the past does NOT mean the client has no lease.** It
  means: holding over, regeared but not updated in EverGreen, or vacated. Report
  past expiries as a data-and-risk finding ("6 recorded expiries have already
  passed"), never as "expired leases".
- EverGreen has an `Is lease outside the L&T act?` column (`contractedOut` in
  units.json). Where it says yes, the lease is contracted out and there is **no
  right to renew**, so the expiry is a hard date. If such a lease's recorded
  expiry has **passed**, there is no statutory continuation. The occupier may be
  staying on without security, so flag it as the most urgent status to confirm.
  If the column is empty, say protection is not recorded.
- Scotland has no equivalent statutory continuation. There the lease continues by
  **tacit relocation** unless notice is served.

## 3. Lease events: describe, don't invent

- **Break options** are usually conditional (vacant possession, rent paid, notice
  served in time). Break notice periods are **contractual and lease-specific**.
  **Never state or derive a break notice deadline**: "the break date is X; the
  notice date depends on the lease".
- **The 1954 Act windows are statutory**, so they may be described generically
  against a recorded expiry: "a landlord's s.25 notice or a tenant's s.26 request
  can be served between 6 and 12 months before the date it gives". Never present
  that as a deadline the client has missed. EverGreen does not record whether
  notices have been served, or whether the lease is protected.
- **Rent reviews**: `OMRR` = open market rent review, usually upward-only.
  `Index Linked` = RPI or CPI, usually with a collar and cap. A review date in the
  past with no newer record means the outcome is not recorded.
- **Dilapidations** fall due at lease end. Under s.18(1) of the Landlord and Tenant
  Act 1927, damages for disrepair are capped at the diminution in the value of the
  landlord's reversion. Only mention this if the report discusses exits.

## 4. Business rates (England)

- The **2026 revaluation** took effect on **1 Apr 2026**, based on rental values at
  **1 Apr 2024**.
- From 1 Apr 2026 there is a **high-value multiplier of 50.8p** for properties with
  a rateable value of **£500,000 or more** (standard 48.0p, small business 43.2p),
  with transitional relief phasing in increases over three years. Large
  distribution warehouses often sit in the high-value band.
- EverGreen holds no rateable values. Mention rates only as a question to take to
  the rates team, never as a figure.
Sources: GOV.UK *Business rates revaluation 2026*; House of Commons Library CBP-10438.

## 5. Units and measurement

- EverGreen `Size (sq ft)` is **GIA**, the `Size Unit` column confirms it. 1 m² = 10.7639 sq ft.
- The MEES 1,000 m² threshold refers to building floor area. Using GIA is a
  reasonable proxy; say "over 1,000 m² GIA".
- WAULT = floorspace-weighted average unexpired term to **expiry**. Say "to expiry"
  or "to first break" every time, and state which leases it covers.
