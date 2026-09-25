# Jurisdictions: contracting entity and terms clause

Always ask which jurisdiction the letter is for, even when the client and the search are in
the same country. The jurisdiction decides the CBRE contracting entity, the terms clause,
the approval block and sometimes the letter status. Search geography and contracting
entity are often different (for example a five-country search contracted by CBRE Limited).

**Never invent a legal entity name or a terms regime.** If the jurisdiction is not in the
verified table, ask the user for the entity name and the terms regime, or put
`[[CBRE contracting entity]]` in the letter and flag it.

## Verified (from letters CBRE has actually issued)

| Jurisdiction | Contracting entity | Terms regime | Source |
|---|---|---|---|
| United Kingdom | CBRE Limited | Standard Terms of Business (STOB), enclosed separately. Not "General Terms". | Confirmed by user, occupier letter 2026 |
| Netherlands | CBRE B.V. | General Terms of CBRE B.V., filed with the District Court of Amsterdam, available at www.cbre.nl | Occupier letter 2022 |
| Poland | CBRE Sp. z o.o. | Letter records scope only; binding appointment under a separate advisory agreement issued by CBRE Sp. z o.o., governed by its standard terms (incl. limitation of liability) | Capital markets letter 2026 |
| Romania | CBRE Real Estate Consultancy SRL | The 2023 letter was issued without a terms clause ("No TC" version). Ask whether terms should be added. | Occupier letter 2023 |

## Everything else (Germany, Austria, Czechia, Slovakia, Hungary, Belgium, France, Spain, Italy, Nordics, Ukraine, ...)

Status: **confirm with the user or the local team**. Ask for:
1. The exact legal name of the CBRE entity that signs.
2. Which terms apply (general terms, standard terms of business, separate agreement, none).
3. Whether the terms are enclosed, referenced by URL or filed somewhere.

When the user confirms a new jurisdiction, suggest adding a row to the verified table.

## Terms clause wording by regime

Heading follows the regime: "Terms of business" (STOB), "General terms" (general terms),
"Status of this letter and next steps" (separate agreement follows).

**Standard Terms of Business, enclosed (UK pattern):**
> [Entity] is the contracting party for all work under this letter. The work is governed by
> the Standard Terms of Business of [Entity], which include a limitation of liability and are
> enclosed separately. By signing this letter, [Client] accepts those terms. If this letter
> and the Standard Terms of Business conflict, this letter prevails.

Add to the approval block: `"enclosures": ["[Entity] Standard Terms of Business"]`.

**General terms, filed and published (NL pattern):**
> [Entity] is the exclusive contracting party for all work under this letter. The work and all
> legal relations with third parties are governed by the General Terms of [Entity], which
> include a limitation of liability. These terms have been filed with [court] and can be
> consulted at [URL]. If this letter and the general terms conflict, this letter prevails.

**Separate agreement follows (PL / capital markets pattern):**
> This letter sets out the scope and the commercial terms. It is not signed and does not
> create a binding engagement. The binding appointment will be made under a separate advisory
> agreement issued by [Entity], which is the contracting party for [the transaction]. That
> agreement will carry over the scope, the team and the fee set out above, and will be
> governed by [Entity]'s standard terms, which include a limitation of liability.

In this pattern there is no approval block and the letter-page paragraph asking for a
signed copy is replaced by a sentence saying the letter is not itself the appointment.

## Things that change with the jurisdiction (check each)

- Approval block entity, and who in that entity can sign (ask; do not assume the author).
- VAT line (keep generic "at the applicable rate" unless the user gives specifics).
- Late-payment interest ("statutory rate of interest" works across Europe; do not cite a
  specific act unless asked).
- Language: letters are in English unless the user asks otherwise.
